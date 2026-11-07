"""Tests for ``custom_components.tcl_matter.helpers``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.tcl_matter.const import MODE_VALUE_MAP
from custom_components.tcl_matter.helpers import (
    coerce_bool,
    coerce_int,
    has_pump,
    mode_name,
    parse_json_list,
    supported_modes,
)


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
def testcoerce_bool_handles_inputs(raw: object, expected: bool | None) -> None:
    """`coerce_bool` mirrors the documented coercion table."""
    assert coerce_bool(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("[]", []),
        ("[5]", [5]),
        ("[3, 5, 7]", [3, 5, 7]),
        ([5, 1], [5, 1]),
        ("", []),
        ("garbage", None),
        (3.14, None),
    ],
)
def testparse_json_list(raw: object, expected: list[object] | None) -> None:
    """`parse_json_list` handles the same shapes as the sensor parser."""
    assert parse_json_list(raw) == expected


def testparse_json_list_scalar_wrapped_in_list() -> None:
    """A bare JSON scalar in the payload is wrapped to a single-item list."""
    assert parse_json_list("5") == [5]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), (5, 5), ("7", 7), (3.9, 3), ("x", None), (object(), None)],
)
def test_coerce_int(raw: object, expected: int | None) -> None:
    """Numeric-looking values become ints; anything else is None."""
    assert coerce_int(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), list(MODE_VALUE_MAP.items()))
def test_mode_name_maps_known_values(raw: int, expected: str) -> None:
    """Every known mode integer maps to its name, also as a string."""
    assert mode_name(raw) == expected
    assert mode_name(str(raw)) == expected


@pytest.mark.parametrize("raw", [None, 99, "garbage", object()])
def test_mode_name_unknown_is_none(raw: object) -> None:
    """Unknown or unparseable modes map to None."""
    assert mode_name(raw) is None


@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        (0x8002, ["set", "comfort"]),
        (0x9999, ["set", "continue", "comfort", "smart", "dry"]),
        (None, ["set", "continue", "comfort", "smart", "dry"]),
    ],
)
def test_supported_modes_by_product(
    product_id: int | None, expected: list[str]
) -> None:
    """Known products list their modes; unknown or missing IDs keep all five."""
    node = SimpleNamespace(device_info=SimpleNamespace(productID=product_id))
    assert supported_modes(node) == expected


def test_supported_modes_without_device_info() -> None:
    """A node with no BasicInformation keeps all five modes."""
    assert supported_modes(SimpleNamespace(device_info=None)) == [
        "set",
        "continue",
        "comfort",
        "smart",
        "dry",
    ]


@pytest.mark.parametrize(
    ("feature_set", "expected"),
    [
        ("[1,3]", True),
        ("[3]", False),
        ("[1]", True),
        ("[]", False),
        ("garbage", False),
        (None, False),
    ],
)
def test_has_pump_reads_the_feature_set(feature_set: object, expected: bool) -> None:
    """Value 1 in the feature set marks a pump model."""
    assert has_pump(feature_set) is expected
