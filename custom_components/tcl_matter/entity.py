"""Base entity for TCL Matter platforms.

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
        self._attr_device_info = DeviceInfo(
            # Reuse the matter integration's identifier so HA merges devices.
            identifiers={(MATTER_DOMAIN, str(node_id))},
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
