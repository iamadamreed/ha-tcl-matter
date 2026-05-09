"""Tests for ``custom_components.tcl_matter.binary_sensor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from custom_components.tcl_matter.binary_sensor import (
    TclBucketFullBinarySensor,
    TclFilterAlertBinarySensor,
    _coerce_bool,
)
from custom_components.tcl_matter.const import (
    ATTR_BUCKET_FULL,
    ATTR_LOCK_OR_FILTER,
)

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (5, True),
        ("true", True),
        ("FALSE", False),
        ("1", True),
        ("0", False),
        ("yes", True),
        ("no", False),
        ("", False),
        ("???", None),
        (3.14, None),
    ],
)
def test_coerce_bool_handles_inputs(raw: object, expected: bool | None) -> None:
    """`_coerce_bool` mirrors the documented coercion table."""
    assert _coerce_bool(raw) is expected


def test_bucket_full_is_on_false(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Default snapshot has bucket-full == False."""
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is False


def test_bucket_full_is_on_true(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Setting attr 3 True flips the sensor on."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = True
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is True


def test_bucket_full_is_on_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Missing attribute yields None."""
    primed_coordinator.data[NODE_ID].pop(ATTR_BUCKET_FULL)
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is None


def test_filter_alert_default_off(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Default snapshot has filter-alert == False."""
    sensor = TclFilterAlertBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is False


def test_filter_alert_on(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Setting attr 4 to a truthy value flips the alert on."""
    primed_coordinator.data[NODE_ID][ATTR_LOCK_OR_FILTER] = 1
    sensor = TclFilterAlertBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is True


def test_filter_alert_unique_id(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Unique id reflects the sensor's role."""
    sensor = TclFilterAlertBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.unique_id == f"tcl_matter_{NODE_ID}_filter_alert"


def test_bucket_full_unique_id(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Unique id reflects the sensor's role."""
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.unique_id == f"tcl_matter_{NODE_ID}_bucket_full"
