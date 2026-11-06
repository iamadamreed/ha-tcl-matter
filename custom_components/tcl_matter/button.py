"""
Button platform for TCL Matter dehumidifiers.

The H50D44W has no Matter command to reset its filter reminder. The alert is
a plain boolean (attr 4 on cluster 0x1334FC03), and writing ``False`` clears
it; the unit beeps to confirm. This button performs that write, but only
when the alert is set: if the device already reports it clear, no write is sent
and the unit stays silent, so a beep means a reset actually happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .const import ATTR_FILTER_ALERT
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
    """Set up TCL Matter buttons."""
    runtime = entry.runtime_data
    async_add_entities(
        TclFilterResetButton(runtime.coordinator, node_id)
        for node_id in runtime.devices
    )


class TclFilterResetButton(TclMatterEntity, ButtonEntity):
    """Clear the filter-clean alert on the dehumidifier."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reset_filter"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the filter reset button."""
        super().__init__(coordinator, node_id, "reset_filter")

    async def async_press(self) -> None:
        """Write False to the filter alert attribute."""
        await self.coordinator.async_write_attribute(
            self._node_id,
            ATTR_FILTER_ALERT,
            False,  # noqa: FBT003
        )
