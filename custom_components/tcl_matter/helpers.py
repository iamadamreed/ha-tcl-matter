"""Small value-decoding helpers shared by the sensor platforms."""

from __future__ import annotations

import json
from typing import Any

from .const import AVAILABLE_MODES, FEATURE_PUMP, LOGGER, MODE_VALUE_MAP, PRODUCT_MODES


def coerce_bool(value: object) -> bool | None:
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


def parse_json_list(value: object) -> list[Any] | None:
    """
    Decode a TCL JSON-encoded list payload (for example error codes).

    Returns ``None`` if the value is missing or cannot be parsed, and ``[]`` if
    the device reports an empty list.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return None
    if not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        LOGGER.debug("Could not parse TCL list payload: %r", value)
        return None
    return decoded if isinstance(decoded, list) else [decoded]


def coerce_int(value: object) -> int | None:
    """Return ``value`` as an int, or None if it is missing or not numeric."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except TypeError, ValueError:
        return None


def mode_name(raw: object) -> str | None:
    """Map the device's integer mode to its name, or None if unknown."""
    number = coerce_int(raw)
    return MODE_VALUE_MAP.get(number) if number is not None else None


def supported_modes(node: Any) -> list[str]:
    """Return the modes this node's product supports, from its product ID."""
    product_id = coerce_int(
        getattr(getattr(node, "device_info", None), "productID", None)
    )
    return list(PRODUCT_MODES.get(product_id, AVAILABLE_MODES))


def has_pump(feature_set: object) -> bool:
    """Return True if the node's feature set (a JSON list) marks a pump model."""
    return FEATURE_PUMP in (parse_json_list(feature_set) or [])
