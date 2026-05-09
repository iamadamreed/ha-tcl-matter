"""
TCL Matter integration.

Decodes TCL's vendor-specific Matter clusters (0x1334FC00 / 0x1334FC03)
that the built-in matter integration exposes as opaque attributes. This
component coexists with the built-in matter integration: it reuses the
same device identifier (("matter", node_id)) so both integrations share
one device card in the HA UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    LOGGER,
    MATTER_DOMAIN,
    TCL_CLUSTER_FC03,
    TCL_VENDOR_ID,
)
from .coordinator import TclMatterCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.HUMIDIFIER,
    Platform.SELECT,
    Platform.SENSOR,
]


@dataclass
class TclDevice:
    """
    Per-node runtime container.

    Stores the matter node reference plus the most recent attribute snapshot
    pulled from cluster 0x1334FC03. The dict is keyed by attribute ID.
    """

    node_id: int
    node: Any
    attributes: dict[int, Any] = field(default_factory=dict)


@dataclass
class TclMatterRuntimeData:
    """Runtime data attached to the config entry."""

    coordinator: TclMatterCoordinator
    devices: dict[int, TclDevice]
    matter_client: Any
    unsubscribers: list[Callable[[], None]] = field(default_factory=list)


type TclMatterConfigEntry = ConfigEntry[TclMatterRuntimeData]


def _get_matter_client(hass: HomeAssistant) -> Any | None:
    """
    Return the matter client from the loaded matter ConfigEntry, or None.

    The location of the client moved across HA releases. We try the modern
    ``runtime_data`` path first and fall back to ``hass.data["matter"]``.
    """
    matter_entries = hass.config_entries.async_entries(MATTER_DOMAIN)
    for matter_entry in matter_entries:
        # Modern HA: ConfigEntry.runtime_data
        runtime_data = getattr(matter_entry, "runtime_data", None)
        if runtime_data is not None:
            adapter = getattr(runtime_data, "adapter", None)
            if adapter is not None and hasattr(adapter, "matter_client"):
                return adapter.matter_client

        # Legacy: hass.data["matter"][entry_id].adapter.matter_client
        matter_data = hass.data.get(MATTER_DOMAIN, {})
        entry_data = matter_data.get(matter_entry.entry_id)
        if entry_data is not None:
            adapter = getattr(entry_data, "adapter", None)
            if adapter is not None and hasattr(adapter, "matter_client"):
                return adapter.matter_client

    return None


def _node_vendor_id(node: Any) -> int | None:
    """
    Extract the vendor ID from a matter node, tolerating API variants.

    Tries (in order):
      1. ``node.device_info.vendorID`` — python-matter-server 5.x decoded form
      2. ``node.get_attribute_value(0, 0x0028, 2)`` — BasicInformation/VendorID
      3. Direct ``node.vendor_id`` attribute (older versions)
    """
    # Path 1: BasicInformation dataclass on the node
    device_info = getattr(node, "device_info", None)
    if device_info is not None:
        for field_name in ("vendorID", "vendor_id", "vendorId"):
            value = getattr(device_info, field_name, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass

    # Path 2: get_attribute_value(endpoint, cluster, attribute)
    get_attr = getattr(node, "get_attribute_value", None)
    if callable(get_attr):
        try:
            value = get_attr(0, 0x0028, 2)  # BasicInformation, VendorID
        except Exception:  # noqa: BLE001
            value = None
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

    # Path 3: legacy direct attribute
    vendor_id = getattr(node, "vendor_id", None)
    if vendor_id is not None:
        try:
            return int(vendor_id)
        except (TypeError, ValueError):
            pass

    return None


def _discover_tcl_nodes(matter_client: Any) -> list[Any]:
    """Return all TCL-vendor matter nodes known to the matter client."""
    nodes: list[Any] = []
    get_nodes = getattr(matter_client, "get_nodes", None)
    if callable(get_nodes):
        try:
            raw_nodes = list(get_nodes())
        except TypeError:
            raw_nodes = list(getattr(matter_client, "nodes", {}).values())
    else:
        raw_nodes = list(getattr(matter_client, "nodes", {}).values())

    LOGGER.debug(
        "TCL discovery: matter_client type=%s, %d nodes found",
        type(matter_client).__name__,
        len(raw_nodes),
    )
    for node in raw_nodes:
        vid = _node_vendor_id(node)
        nid = getattr(node, "node_id", None)
        if vid == TCL_VENDOR_ID:
            LOGGER.info("TCL Matter node discovered: node_id=%s vendor_id=0x%04X", nid, vid)
            nodes.append(node)
        else:
            LOGGER.debug("Skipping non-TCL node node_id=%s vendor_id=%s", nid, vid)
    return nodes


async def async_setup_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> bool:
    """
    Set up TCL Matter from a config entry.

    Hard-depends on the matter integration being loaded. Discovers TCL
    nodes by VendorID, builds a coordinator that polls cluster 0x1334FC03
    every 30s as a fallback, and subscribes to push attribute updates from
    the matter client when supported.
    """
    matter_client = _get_matter_client(hass)
    if matter_client is None:
        LOGGER.debug("Matter integration not yet loaded; deferring TCL Matter setup")
        raise ConfigEntryNotReady("matter integration not loaded")

    tcl_nodes = _discover_tcl_nodes(matter_client)
    if not tcl_nodes:
        LOGGER.warning(
            "No TCL Matter devices (VendorID 0x%04X) found on the matter fabric",
            TCL_VENDOR_ID,
        )

    devices: dict[int, TclDevice] = {}
    for node in tcl_nodes:
        node_id = int(getattr(node, "node_id", getattr(node, "nodeid", 0)))
        devices[node_id] = TclDevice(node_id=node_id, node=node)
        LOGGER.info("Discovered TCL Matter node %s", node_id)

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=matter_client,
        devices=devices,
    )

    # Initial attribute snapshot. If this fails, surface as ConfigEntryNotReady
    # so HA retries instead of leaving entities permanently unknown.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"initial TCL attribute read failed: {err}") from err

    runtime = TclMatterRuntimeData(
        coordinator=coordinator,
        devices=devices,
        matter_client=matter_client,
    )

    # Try to attach a push subscription. If the matter client doesn't support
    # vendor-cluster subscriptions yet, we silently fall back to coordinator
    # polling — both paths feed the same coordinator.data dict.
    _attach_push_subscription(matter_client, runtime, coordinator)

    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


@callback
def _attach_push_subscription(
    matter_client: Any,
    runtime: TclMatterRuntimeData,
    coordinator: TclMatterCoordinator,
) -> None:
    """
    Subscribe to attribute-updated events on the matter client.

    The python-matter-server client exposes ``subscribe_events`` /
    ``subscribe`` with varying signatures across versions. We attempt the
    common shapes and degrade gracefully.
    """

    @callback
    def _on_event(event: Any, data: Any = None) -> None:
        """Handle a push attribute update from the matter client."""
        try:
            coordinator.handle_push_event(event, data)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error handling matter push event")

    # Try modern signature: subscribe_events(callback, event_filter=...)
    subscribe_events = getattr(matter_client, "subscribe_events", None)
    if callable(subscribe_events):
        try:
            unsub = subscribe_events(_on_event)
            if callable(unsub):
                runtime.unsubscribers.append(unsub)
                LOGGER.debug("Attached matter_client.subscribe_events listener")
                return
        except TypeError:
            LOGGER.debug("subscribe_events signature differs; falling through")

    # Try legacy: subscribe(callback)
    subscribe = getattr(matter_client, "subscribe", None)
    if callable(subscribe):
        try:
            unsub = subscribe(_on_event)
            if callable(unsub):
                runtime.unsubscribers.append(unsub)
                LOGGER.debug("Attached matter_client.subscribe listener")
                return
        except TypeError:
            LOGGER.debug("subscribe signature differs; falling through")

    interval = coordinator.update_interval
    poll_secs = interval.total_seconds() if interval else 30
    LOGGER.info(
        "Matter client does not expose a compatible subscription API; "
        "TCL Matter will rely on %ds polling",
        poll_secs,
    )


async def async_unload_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> bool:
    """Unload a TCL Matter config entry."""
    runtime = entry.runtime_data
    for unsub in runtime.unsubscribers:
        try:
            unsub()
        except Exception:  # noqa: BLE001
            LOGGER.debug("Error unsubscribing matter listener", exc_info=True)
    runtime.unsubscribers.clear()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: TclMatterConfigEntry) -> None:
    """Reload the TCL Matter config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


__all__ = [
    "TCL_CLUSTER_FC03",
    "TclDevice",
    "TclMatterConfigEntry",
    "TclMatterRuntimeData",
    "async_reload_entry",
    "async_setup_entry",
    "async_unload_entry",
]
