"""
Select platform for TCL Matter dehumidifiers.

Mirrors the humidifier's mode attribute as a standalone select entity.
This is convenient for users who want to bind mode to a dashboard tile or
trigger automations off mode changes without going through the humidifier
entity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity

from .const import (
    ATTR_MODE,
    AVAILABLE_MODES,
    LOGGER,
    MODE_NAME_MAP,
    MODE_VALUE_MAP,
)
from .entity import TclMatterEntity

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
    entities = [
        TclModeSelect(runtime.coordinator, runtime.matter_client, node_id)
        for node_id in runtime.devices
    ]
    async_add_entities(entities)


class TclModeSelect(TclMatterEntity, SelectEntity):
    """Operating mode selector mirroring humidifier attr 0."""

    _attr_options = AVAILABLE_MODES
    _attr_translation_key = "mode"

    def __init__(
        self,
        coordinator: TclMatterCoordinator,
        matter_client: Any,
        node_id: int,
    ) -> None:
        """Initialize the mode selector."""
        super().__init__(coordinator, node_id, "mode")
        self._matter_client = matter_client

    @property
    def current_option(self) -> str | None:
        """Return the active mode name."""
        raw = self._node_data.get(ATTR_MODE)
        if raw is None:
            return None
        try:
            return MODE_VALUE_MAP.get(int(raw))
        except TypeError, ValueError:
            return None

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode back to the device."""
        if option not in MODE_NAME_MAP:
            LOGGER.warning("Unknown TCL mode requested via select: %s", option)
            return

        await self.coordinator.async_write_attribute(
            self._node_id, ATTR_MODE, MODE_NAME_MAP[option]
        )
