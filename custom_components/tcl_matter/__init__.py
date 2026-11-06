"""
TCL Matter integration.

Decodes TCL's vendor-specific Matter cluster 0x1334FC03, which the built-in
matter integration exposes only as opaque attributes. It runs alongside the
matter integration and reads and writes the device through the matter client
that integration holds. Its devices are linked to the matter integration's
device with ``via_device_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial, wraps
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from matter_server.common.models import EventType

from .const import (
    LOGGER,
    MATTER_DOMAIN,
    NUM_TCL_FC03_DATA_ATTRS,
    ONOFF_ATTR_ON_OFF,
    ONOFF_CLUSTER,
    ONOFF_ENDPOINT,
    TCL_CLUSTER_FC03,
    TCL_VENDOR_ID,
)
from .coordinator import TclMatterCoordinator
from .device import async_migrate_devices, async_sync_device_info, tcl_device_identifier

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceEntry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.HUMIDIFIER,
    Platform.SELECT,
    Platform.SENSOR,
]


@dataclass
class TclDevice:
    """Per-node runtime container: the matter node object."""

    node_id: int
    node: Any


@dataclass
class TclMatterRuntimeData:
    """Runtime data attached to the config entry."""

    coordinator: TclMatterCoordinator
    devices: dict[int, TclDevice]


type TclMatterConfigEntry = ConfigEntry[TclMatterRuntimeData]


def _get_matter(hass: HomeAssistant) -> tuple[ConfigEntry, Any] | None:
    """Return the loaded matter config entry and its client, or None."""
    for matter_entry in hass.config_entries.async_loaded_entries(MATTER_DOMAIN):
        adapter = getattr(getattr(matter_entry, "runtime_data", None), "adapter", None)
        client = getattr(adapter, "matter_client", None)
        if client is not None:
            return matter_entry, client
    return None


def _node_vendor_id(node: Any) -> int | None:
    """Return the BasicInformation vendor id of a matter node, if readable."""
    try:
        return int(node.device_info.vendorID)
    # A node whose interview failed has no endpoint 0, which raises KeyError.
    except AttributeError, KeyError, TypeError, ValueError:
        return None


async def async_setup_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> bool:
    """
    Set up TCL Matter from a config entry.

    Depends on the matter integration being loaded. Finds TCL nodes by vendor
    id, subscribes to pushed attribute updates, and polls as a safety net.
    """
    found = _get_matter(hass)
    if found is None:
        msg = "matter integration not loaded"
        raise ConfigEntryNotReady(msg)
    matter_entry, matter_client = found

    devices: dict[int, TclDevice] = {}
    for node in matter_client.get_nodes():
        if _node_vendor_id(node) == TCL_VENDOR_ID:
            devices[node.node_id] = TclDevice(node_id=node.node_id, node=node)
            LOGGER.info("Discovered TCL Matter node %s", node.node_id)
    if not devices:
        LOGGER.warning(
            "No TCL Matter devices (VendorID 0x%04X) found on the matter fabric",
            TCL_VENDOR_ID,
        )

    async_migrate_devices(hass, entry, matter_client, devices)

    coordinator = TclMatterCoordinator(hass, entry, matter_client, devices)
    # Raises ConfigEntryNotReady itself if no node can be read.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TclMatterRuntimeData(coordinator=coordinator, devices=devices)

    _subscribe(hass, entry, matter_entry, matter_client, coordinator, devices)
    if matter_entry.state is not ConfigEntryState.LOADED:
        # The matter integration reloaded while this entry was starting, so the
        # client above is already dead. Retry with the new one.
        msg = "matter integration reloaded during setup"
        raise ConfigEntryNotReady(msg)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _subscribe(  # noqa: PLR0913, PLR0917
    hass: HomeAssistant,
    entry: TclMatterConfigEntry,
    matter_entry: ConfigEntry,
    matter_client: Any,
    coordinator: TclMatterCoordinator,
    devices: dict[int, TclDevice],
) -> None:
    """
    Register push subscriptions and lifecycle watchers.

    The matter client calls back with only ``(event, value)``, so each
    attribute gets its own subscription with the node and attribute bound in.
    Every subscription is released through ``entry.async_on_unload``.
    """

    def subscribe(callback_fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Subscribe, wrapping the callback so it can never raise into the client."""
        return matter_client.subscribe_events(_safe(callback_fn), *args, **kwargs)

    for node_id in devices:
        # Attribute 6 (feature set) is read by the poll but nothing displays it.
        for attr_id in range(NUM_TCL_FC03_DATA_ATTRS - 1):
            entry.async_on_unload(
                subscribe(
                    partial(coordinator.handle_attribute_update, node_id, attr_id),
                    EventType.ATTRIBUTE_UPDATED,
                    node_filter=node_id,
                    attr_path_filter=f"1/{TCL_CLUSTER_FC03}/{attr_id}",
                )
            )
        # Power state is read from the matter node's own cache; these events
        # only tell entities to re-render.
        entry.async_on_unload(
            subscribe(
                coordinator.handle_state_change,
                EventType.ATTRIBUTE_UPDATED,
                node_filter=node_id,
                attr_path_filter=(
                    f"{ONOFF_ENDPOINT}/{ONOFF_CLUSTER}/{ONOFF_ATTR_ON_OFF}"
                ),
            )
        )
        entry.async_on_unload(
            subscribe(
                partial(_on_node_updated, hass, entry, matter_client, coordinator),
                EventType.NODE_UPDATED,
                node_filter=node_id,
            )
        )

    @callback
    def _reload() -> None:
        hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def _on_node_added(_event: Any, node: Any) -> None:
        if _node_vendor_id(node) == TCL_VENDOR_ID and node.node_id not in devices:
            LOGGER.info("TCL node %s added; reloading", node.node_id)
            _reload()

    @callback
    def _on_node_removed(_event: Any, node_id: Any) -> None:
        if node_id in devices:
            LOGGER.info("TCL node %s removed; reloading", node_id)
            _reload()

    @callback
    def _on_matter_state_change() -> None:
        # The matter integration replaces its client when it reloads, which
        # leaves this entry holding a dead one. Reload to pick up the new one.
        if matter_entry.state is not ConfigEntryState.LOADED:
            LOGGER.info("matter integration left the loaded state; reloading")
            _reload()

    entry.async_on_unload(subscribe(_on_node_added, EventType.NODE_ADDED))
    entry.async_on_unload(subscribe(_on_node_removed, EventType.NODE_REMOVED))
    entry.async_on_unload(matter_entry.async_on_state_change(_on_matter_state_change))


@callback
def _on_node_updated(
    hass: HomeAssistant,
    entry: TclMatterConfigEntry,
    matter_client: Any,
    coordinator: TclMatterCoordinator,
    _event: Any,
    node: Any,
) -> None:
    """Re-render entities and copy firmware versions after a node update."""
    coordinator.handle_state_change()
    async_sync_device_info(hass, entry, matter_client, node)


def _safe(callback_fn: Any) -> Any:
    """
    Wrap a subscription callback so an exception is logged, not raised.

    The matter client calls subscribers from its own dispatch loop. An
    exception there is treated as a client failure and makes Home Assistant
    reload the whole matter integration.
    """

    @wraps(callback_fn)
    def _wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            callback_fn(*args, **kwargs)
        # Defensive: nothing here may propagate into the matter client.
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error handling a matter event")

    return _wrapper


async def async_unload_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> bool:
    """Unload a TCL Matter config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow removing a device unless it belongs to a node we currently serve."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return True  # not loaded, so nothing is being served
    client = runtime.coordinator.matter_client
    active = {
        identifier
        for node_id in runtime.devices
        for identifier in (
            tcl_device_identifier(client, node_id),
            (MATTER_DOMAIN, str(node_id)),
        )
    }
    return not (device_entry.identifiers & active)


__all__ = [
    "TclDevice",
    "TclMatterConfigEntry",
    "TclMatterRuntimeData",
    "async_remove_config_entry_device",
    "async_setup_entry",
    "async_unload_entry",
]
