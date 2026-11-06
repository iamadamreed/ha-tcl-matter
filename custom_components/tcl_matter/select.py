"""
Select platform for TCL Matter dehumidifiers.

Mirrors the humidifier's mode attribute as a standalone select entity, for
dashboard tiles and automations that trigger on mode changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .const import ATTR_MODE, AVAILABLE_MODES, MODE_NAME_MAP
from .entity import TclMatterEntity
from .helpers import mode_name

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import TclMatterConfigEntry
    from .coordinator import TclMatterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TCL Matter select entities."""
    runtime = entry.runtime_data
    async_add_entities(
        TclModeSelect(runtime.coordinator, node_id) for node_id in runtime.devices
    )


class TclModeSelect(TclMatterEntity, SelectEntity):
    """Operating mode selector mirroring humidifier attr 0."""

    _attr_translation_key = "mode"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the mode selector."""
        super().__init__(coordinator, node_id, "mode")
        self._attr_options = list(AVAILABLE_MODES)

    @property
    def current_option(self) -> str | None:
        """Return the active mode name."""
        return mode_name(self._node_data.get(ATTR_MODE))

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode back to the device."""
        # HA validates ``option`` against ``options`` before calling this.
        await self.coordinator.async_write_attribute(
            self._node_id, ATTR_MODE, MODE_NAME_MAP[option]
        )
