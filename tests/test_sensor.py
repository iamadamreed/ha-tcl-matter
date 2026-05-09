"""Tests for ``custom_components.tcl_matter.sensor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_ERROR_CODES,
)
from custom_components.tcl_matter.sensor import (
    TclCurrentHumiditySensor,
    TclErrorCodeSensor,
)

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5


def test_current_humidity_sensor_native_value(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Sensor exposes the integer reading from attr 2."""
    sensor = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert sensor.native_value == 58


def test_current_humidity_sensor_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Native value is None when attr 2 is absent."""
    primed_coordinator.data[NODE_ID].pop(ATTR_CURRENT_HUMIDITY)
    sensor = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert sensor.native_value is None


def test_current_humidity_sensor_handles_unparseable(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Non-int value yields None rather than raising."""
    primed_coordinator.data[NODE_ID][ATTR_CURRENT_HUMIDITY] = "??"
    sensor = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert sensor.native_value is None


def test_current_humidity_sensor_unique_id(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Unique id includes node id and the suffix."""
    sensor = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert sensor.unique_id == f"tcl_matter_{NODE_ID}_current_humidity"


@pytest.mark.parametrize(
    ("raw", "expected_count", "expected_codes"),
    [
        ("[]", 0, []),
        ('["E1"]', 1, ["E1"]),
        ('["E1", "E2"]', 2, ["E1", "E2"]),
        ([], 0, []),
        (["E3"], 1, ["E3"]),
    ],
)
def test_error_code_sensor_parses_lists(
    primed_coordinator: TclMatterCoordinator,
    raw: object,
    expected_count: int,
    expected_codes: list[object],
) -> None:
    """Error code sensor decodes strings or accepts lists directly."""
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = raw
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value == expected_count
    assert sensor.extra_state_attributes == {"codes": expected_codes}


def test_error_code_sensor_returns_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Native value is None when the raw attribute is absent."""
    primed_coordinator.data[NODE_ID].pop(ATTR_ERROR_CODES)
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"codes": []}


def test_error_code_sensor_returns_none_for_invalid_json(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Malformed JSON yields a None native value (couldn't decode)."""
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "{not json"
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value is None


def test_error_code_sensor_empty_string(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """An empty string is treated as zero codes."""
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "   "
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value == 0


def test_error_code_sensor_wraps_non_list_decode(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A scalar JSON payload is wrapped in a single-element list."""
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = '"E9"'
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes == {"codes": ["E9"]}


def test_error_code_sensor_unsupported_type(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """An unsupported payload type yields a None native value."""
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = 12345
    sensor = TclErrorCodeSensor(primed_coordinator, NODE_ID)
    assert sensor.native_value is None
