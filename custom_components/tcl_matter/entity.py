"""
Base entity for TCL Matter platforms.

All TCL Matter entities share a coordinator and bind to the same device
identifier as the built-in matter integration (``("matter", node_id)``)
so that the two integrations share one device card in the HA UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MATTER_DOMAIN

if TYPE_CHECKING:
    from .coordinator import TclMatterCoordinator


def _node_basic_info(coordinator: TclMatterCoordinator, node_id: int) -> dict[str, Any]:
    """Return BasicInformation fields (vendor, product, etc.) for a node."""
    device = coordinator._devices.get(node_id)  # noqa: SLF001
    if device is None:
        return {}
    info = getattr(device.node, "device_info", None)
    if info is None:
        return {}
    return {
        "vendor_name": getattr(info, "vendorName", None),
        "vendor_id": getattr(info, "vendorID", None),
        "product_name": getattr(info, "productName", None),
        "product_id": getattr(info, "productID", None),
        "hw_version": getattr(info, "hardwareVersionString", None),
        "sw_version": getattr(info, "softwareVersionString", None),
    }


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

        info = _node_basic_info(coordinator, node_id)
        self._attr_device_info = DeviceInfo(
            # Reuse the matter integration's identifier so HA merges devices.
            identifiers={(MATTER_DOMAIN, str(node_id))},
            name=info.get("product_name") or "TCL Dehumidifier",
            manufacturer=info.get("vendor_name") or "TCL",
            model=info.get("product_name") or "TCL Dehumidifier",
            hw_version=info.get("hw_version"),
            sw_version=info.get("sw_version"),
        )

    @property
    def _node_data(self) -> dict[int, Any]:
        """Return the latest attribute snapshot for this node."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._node_id, {})

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this node."""
        return super().available and bool(self._node_data)
