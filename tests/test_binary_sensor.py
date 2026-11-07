"""Tests for ``custom_components.tcl_matter.binary_sensor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.tcl_matter.binary_sensor import (
    TclBucketFullBinarySensor,
)
from custom_components.tcl_matter.const import (
    ATTR_BUCKET_FULL,
    ATTR_ERROR_CODES,
    ERROR_CODE_BUCKET_FULL,
)

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5


def test_bucket_full_is_on_false(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Default snapshot (attr 3 = False, error_codes = []) → bucket not full."""
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is False


def test_bucket_full_is_on_when_attr_3_true(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Defensive read of attr 3: if a future TCL firmware ever wires up the
    dedicated bool, we still surface it as bucket-full."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = True
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "[]"
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is True


def test_bucket_full_is_on_when_error_code_5_present(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Canonical signal on H50D44W: error code 5 in error_codes → bucket full,
    even though attr 3 stays False. Empirically verified 2026-05-11."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = False
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "[5]"
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is True


def test_bucket_full_off_when_other_error_codes_present(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Other error codes don't imply bucket full."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = False
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "[3, 7]"
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is False


def test_bucket_full_handles_pre_parsed_list_codes(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """If error_codes is already a list (e.g. coordinator pre-parsed it),
    the sensor still finds code 5."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = False
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = [5, 1]
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is True


def test_bucket_full_is_none_when_both_missing(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Both signals missing → unknown (None)."""
    primed_coordinator.data[NODE_ID].pop(ATTR_BUCKET_FULL)
    primed_coordinator.data[NODE_ID].pop(ATTR_ERROR_CODES)
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is None


def test_bucket_full_is_false_when_error_codes_unparseable(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A garbage error_codes payload falls back to the attr 3 reading."""
    primed_coordinator.data[NODE_ID][ATTR_BUCKET_FULL] = False
    primed_coordinator.data[NODE_ID][ATTR_ERROR_CODES] = "not-json"
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.is_on is False


def test_error_code_constant_is_five() -> None:
    """Document the empirical value at the test level."""
    assert ERROR_CODE_BUCKET_FULL == 5


def test_bucket_full_unique_id(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Unique id reflects the sensor's role."""
    sensor = TclBucketFullBinarySensor(primed_coordinator, NODE_ID)
    assert sensor.unique_id == f"tcl_matter_{NODE_ID}_bucket_full"
