"""Device registry helpers for TCL Matter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, LOGGER, MATTER_DOMAIN

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _fabric_id(matter_client: Any) -> int | None:
    """Return the compressed fabric id the matter server reports, if any."""
    fabric_id = getattr(
        getattr(matter_client, "server_info", None), "compressed_fabric_id", None
    )
    return fabric_id if isinstance(fabric_id, int) else None


def matter_device_identifier(
    matter_client: Any, node_id: int
) -> tuple[str, str] | None:
    """
    Return the identifier the matter integration uses for this node's device.

    It is ``deviceid_<compressed fabric id>-<node id>-MatterNodeDevice``, with
    both ids as 16 hex digits. Returns ``None`` when the fabric id is not
    available.
    """
    fabric_id = _fabric_id(matter_client)
    if fabric_id is None:
        return None
    return (
        MATTER_DOMAIN,
        f"deviceid_{fabric_id:016X}-{node_id:016X}-MatterNodeDevice",
    )


def tcl_device_identifier(matter_client: Any, node_id: int) -> tuple[str, str]:
    """
    Return this integration's own identifier for a node's device.

    Scoped to the fabric so two fabrics can't collide on a node id. Falls back
    to the bare node id if the fabric id is not available.
    """
    fabric_id = _fabric_id(matter_client)
    if fabric_id is None:
        return (DOMAIN, str(node_id))
    return (DOMAIN, f"{fabric_id:016X}-{node_id:016X}")


@callback
def async_migrate_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    matter_client: Any,
    node_ids: Iterable[int],
) -> None:
    """
    Move devices created by 0.5.x to this integration's own identifier.

    Versions up to 0.5.x registered the device as ``("matter", "<node id>")``,
    an identifier in another integration's domain. The device keeps its id, so
    its area, name and entities are untouched.
    """
    registry = dr.async_get(hass)
    for node_id in node_ids:
        legacy = (MATTER_DOMAIN, str(node_id))
        device = registry.async_get_device_by_identifier(legacy, entry.entry_id)
        if device is None:
            continue
        new = tcl_device_identifier(matter_client, node_id)
        existing = registry.async_get_device_by_identifier(new, entry.entry_id)
        if existing is not None and existing.id != device.id:
            # Both exist, for example after rolling back to 0.5.x and upgrading
            # again. Keep the older device, which has the user's area and name,
            # and drop the newer one; its entities re-attach by unique id.
            registry.async_remove_device(existing.id)
        try:
            registry.async_update_device(device.id, new_identifiers={new})
        except dr.DeviceIdentifierCollisionError:
            LOGGER.warning("Could not migrate device identifier for node %s", node_id)


@callback
def async_sync_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    matter_client: Any,
    node: Any,
) -> None:
    """
    Copy the node's current firmware and hardware versions to its device.

    HA reads ``device_info`` only when an entity is added, so a firmware update
    would otherwise never show. Called when the node reports a change.
    """
    basic = getattr(node, "device_info", None)
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        tcl_device_identifier(matter_client, node.node_id), entry.entry_id
    )
    if device is None or basic is None:
        return
    sw_version = getattr(basic, "softwareVersionString", None)
    hw_version = getattr(basic, "hardwareVersionString", None)
    if (device.sw_version, device.hw_version) != (sw_version, hw_version):
        registry.async_update_device(
            device.id, sw_version=sw_version, hw_version=hw_version
        )
