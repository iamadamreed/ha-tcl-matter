"""
Base entity for TCL Matter platforms.

All TCL Matter entities share a coordinator and one device per node. That
device is linked to the matter integration's device with ``via_device_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MATTER_DOMAIN
from .device import matter_device_identifier, tcl_device_identifier

if TYPE_CHECKING:
    from .coordinator import TclMatterCoordinator


class TclMatterEntity(CoordinatorEntity["TclMatterCoordinator"]):
    """Base class for all TCL Matter entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TclMatterCoordinator,
        node_id: int,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the entity for a specific TCL node."""
        super().__init__(coordinator)
        self._node_id = node_id
        self._attr_unique_id = f"{DOMAIN}_{node_id}_{unique_id_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        """
        Return device info, linked to the matter integration's device.

        HA keeps one device per integration, so this integration has its own
        device and points ``via_device_id`` at the matter one. Built on each
        call so versions follow the node.
        """
        node = self.coordinator.get_node(self._node_id)
        basic = getattr(node, "device_info", None)
        product = getattr(basic, "productName", None) or "TCL Dehumidifier"
        info = DeviceInfo(
            identifiers={
                tcl_device_identifier(self.coordinator.matter_client, self._node_id)
            },
            name=product,
            manufacturer=getattr(basic, "vendorName", None) or "TCL",
            model=product,
            hw_version=getattr(basic, "hardwareVersionString", None),
            sw_version=getattr(basic, "softwareVersionString", None),
        )
        product_id = getattr(basic, "productID", None)
        if isinstance(product_id, int):
            info["model_id"] = str(product_id)
        parent = matter_device_identifier(self.coordinator.matter_client, self._node_id)
        if parent is not None and self.hass is not None:
            registry = dr.async_get(self.hass)
            for matter_entry in self.hass.config_entries.async_entries(MATTER_DOMAIN):
                device = registry.async_get_device_by_identifier(
                    parent, matter_entry.entry_id
                )
                if device is not None:
                    info["via_device_id"] = device.id
                    break
        return info

    @property
    def _node_data(self) -> dict[int, Any]:
        """Return the latest attribute snapshot for this node."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._node_id, {})

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this node."""
        return (
            super().available
            and bool(self._node_data)
            and self.coordinator.node_available(self._node_id)
        )
