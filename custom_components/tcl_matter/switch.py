"""
Switch platform for TCL Matter dehumidifiers.

The pump setting is attribute 4 of cluster 0x1334FC03. It is the same setting
as the Pump button on the unit's panel: writing it moves the pump light and
the unit beeps as it does for the button. With it on, the unit pumps water out
through its drain hose once the bucket is almost full (TCL DFL-Series manual).
Only pump models get the switch. They are recognised by the feature set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import ATTR_FEATURE_SET, ATTR_PUMP
from .entity import TclMatterEntity
from .helpers import coerce_bool, has_pump

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
    """Set up a pump switch for every pump model."""
    runtime = entry.runtime_data
    data = runtime.coordinator.data or {}
    async_add_entities(
        TclPumpSwitch(runtime.coordinator, node_id)
        for node_id in runtime.devices
        if has_pump(data.get(node_id, {}).get(ATTR_FEATURE_SET))
    )


class TclPumpSwitch(TclMatterEntity, SwitchEntity):
    """The pump setting, as on the panel's Pump button."""

    _attr_translation_key = "pump"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the pump switch."""
        super().__init__(coordinator, node_id, "pump")

    @property
    def is_on(self) -> bool | None:
        """Return True when the pump is enabled."""
        return coerce_bool(self._node_data.get(ATTR_PUMP))

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable the pump."""
        await self.coordinator.async_write_attribute(self._node_id, ATTR_PUMP, True)  # noqa: FBT003

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable the pump."""
        await self.coordinator.async_write_attribute(self._node_id, ATTR_PUMP, False)  # noqa: FBT003
