"""Sensor platform for TCL Matter dehumidifiers.

Surfaces the diagnostic side of the vendor cluster:

* Current ambient humidity (attr 2)
* Active error codes (attr 5, JSON-encoded list)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory

from .const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_ERROR_CODES,
    LOGGER,
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
    """Set up TCL Matter sensors."""
    runtime = entry.runtime_data
    entities: list[TclMatterEntity] = []
    for node_id in runtime.devices:
        entities.append(TclCurrentHumiditySensor(runtime.coordinator, node_id))
        entities.append(TclErrorCodeSensor(runtime.coordinator, node_id))
    async_add_entities(entities)


class TclCurrentHumiditySensor(TclMatterEntity, SensorEntity):
    """Ambient humidity reported by the dehumidifier (attr 2)."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "current_humidity"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the current humidity sensor."""
        super().__init__(coordinator, node_id, "current_humidity")

    @property
    def native_value(self) -> int | None:
        """Return the current humidity reading."""
        value = self._node_data.get(ATTR_CURRENT_HUMIDITY)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class TclErrorCodeSensor(TclMatterEntity, SensorEntity):
    """Active TCL error codes (attr 5).

    The raw value is a JSON-encoded list (e.g. ``"[]"`` for no errors).
    The state is the count of active codes; the raw list is exposed as an
    extra state attribute for users who want to surface specifics.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "error_codes"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the error code sensor."""
        super().__init__(coordinator, node_id, "error_codes")

    @property
    def native_value(self) -> int | None:
        """Return the number of active error codes."""
        codes = self._parse_codes()
        if codes is None:
            return None
        return len(codes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw decoded list of codes."""
        codes = self._parse_codes()
        return {"codes": codes if codes is not None else []}

    def _parse_codes(self) -> list[Any] | None:
        """Decode the JSON-encoded error code list."""
        raw = self._node_data.get(ATTR_ERROR_CODES)
        if raw is None:
            return None
        if isinstance(raw, list):
            return raw
        if not isinstance(raw, str):
            return None
        if not raw.strip():
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.debug("Could not parse TCL error_codes payload: %r", raw)
            return None
        return decoded if isinstance(decoded, list) else [decoded]
