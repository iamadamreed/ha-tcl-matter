"""
Binary sensor platform for TCL Matter dehumidifiers.

Exposes the two boolean status flags on cluster 0x1334FC03:

* :class:`TclBucketFullBinarySensor` — water bucket full. The dedicated
  bool at attr 3 is dead on the H50D44W (empirically verified
  2026-05-11), so the canonical signal is error code 5 in ATTR_ERROR_CODES
  (attr 5). We OR both sources so any future firmware that wires up attr 3
  is also caught.
* :class:`TclFilterAlertBinarySensor` (attr 4) — the filter-clean alert.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import (
    ATTR_BUCKET_FULL,
    ATTR_ERROR_CODES,
    ATTR_FILTER_ALERT,
    ERROR_CODE_BUCKET_FULL,
)
from .entity import TclMatterEntity
from .helpers import coerce_bool, parse_json_list

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


class TclBucketFullBinarySensor(TclMatterEntity, BinarySensorEntity):
    """
    Water bucket full indicator.

    On the H50D44W (firmware 1.0) the dedicated ``ATTR_BUCKET_FULL`` bool
    is never set — empirically verified 2026-05-11 by cycling the bucket
    in/out and watching the full attribute table. The canonical bucket-full
    signal is **error code 5** in ``ATTR_ERROR_CODES``. We OR both sources
    so:

    * any TCL device that does wire up attr 3 keeps working, and
    * the H50D44W (and any TCL SKU using the same error-code table) gets
      a real signal via the error-code channel.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "bucket_full"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the bucket-full sensor."""
        super().__init__(coordinator, node_id, "bucket_full")

    @property
    def is_on(self) -> bool | None:
        """Return True when the bucket is full."""
        attr_3 = coerce_bool(self._node_data.get(ATTR_BUCKET_FULL))
        if attr_3 is True:
            return True
        codes = parse_json_list(self._node_data.get(ATTR_ERROR_CODES))
        if codes is None:
            return attr_3  # fall back to the bool reading (may be None)
        return ERROR_CODE_BUCKET_FULL in codes


class TclFilterAlertBinarySensor(TclMatterEntity, BinarySensorEntity):
    """
    Filter-clean alert (attr 4).

    Verified on the H50D44W: this is the filter reminder, and writing
    ``False`` to it clears the alert. See :class:`button.TclFilterResetButton`.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "filter_alert"

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the filter alert sensor."""
        super().__init__(coordinator, node_id, "filter_alert")

    @property
    def is_on(self) -> bool | None:
        """Return True when the filter alert is set."""
        return coerce_bool(self._node_data.get(ATTR_FILTER_ALERT))
