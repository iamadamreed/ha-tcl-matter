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
from functools import partial
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
from .device import async_migrate_devices, tcl_device_identifier

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
    except AttributeError, TypeError, ValueError:
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
    subscribe = matter_client.subscribe_events

    for node_id in devices:
        for attr_id in range(NUM_TCL_FC03_DATA_ATTRS):
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
                coordinator.handle_state_change,
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


async def async_unload_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> bool:
    """Unload a TCL Matter config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow removing a device unless it belongs to a node we currently serve."""
    client = entry.runtime_data.coordinator.matter_client
    active = {
        identifier
        for node_id in entry.runtime_data.devices
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
