"""Binary sensor platform for TCL Matter dehumidifiers.

Exposes the two boolean status flags on cluster 0x1334FC03:

* :class:`TclBucketFullBinarySensor` (attr 3) — water bucket full,
  causes the device to stop running.
* :class:`TclFilterAlertBinarySensor` (attr 4) — semantics still TBD;
  TCL's app shows it as either a child-lock indicator or a filter-clean
  reminder depending on the SKU.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import ATTR_BUCKET_FULL, ATTR_LOCK_OR_FILTER
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
    """Set up TCL Matter binary sensors."""
    runtime = entry.runtime_data
    entities: list[TclMatterEntity] = []
    for node_id in runtime.devices:
        entities.append(TclBucketFullBinarySensor(runtime.coordinator, node_id))
        entities.append(TclFilterAlertBinarySensor(runtime.coordinator, node_id))
    async_add_entities(entities)


def _coerce_bool(value: object) -> bool | None:
    """Best-effort coercion of an attribute payload into a bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", ""}:
            return False
    return None


class TclBucketFullBinarySensor(TclMatterEntity, BinarySensorEntity):
    """Water bucket full indicator (attr 3)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "bucket_full"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the bucket-full sensor."""
        super().__init__(coordinator, node_id, "bucket_full")

    @property
    def is_on(self) -> bool | None:
        """Return True when the bucket is full."""
        return _coerce_bool(self._node_data.get(ATTR_BUCKET_FULL))


class TclFilterAlertBinarySensor(TclMatterEntity, BinarySensorEntity):
    """Filter / lock alert (attr 4).

    TODO(empirical): confirm whether this attribute reports a filter
    clean reminder, a child lock state, or both. Toggle the lock and
    run the device long enough to trigger the filter reminder, then
    correlate.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "filter_alert"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the filter alert sensor."""
        super().__init__(coordinator, node_id, "filter_alert")

    @property
    def is_on(self) -> bool | None:
        """Return True when the filter / lock alert is set."""
        return _coerce_bool(self._node_data.get(ATTR_LOCK_OR_FILTER))
