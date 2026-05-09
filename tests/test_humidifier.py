"""Tests for ``custom_components.tcl_matter.humidifier``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    MAX_HUMIDITY,
    MIN_HUMIDITY,
    MODE_VALUE_MAP,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.humidifier import TclDehumidifier

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5
EXPECTED_TARGET_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_TARGET_HUMIDITY}"
EXPECTED_MODE_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}"


def _make_entity(
    primed_coordinator: TclMatterCoordinator,
    matter_client: MagicMock,
) -> TclDehumidifier:
    """Construct a TclDehumidifier wired to the primed test coordinator."""
    return TclDehumidifier(primed_coordinator, matter_client, NODE_ID)


def test_target_humidity_reflects_attr_1(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """target_humidity reads attr 1 from the coordinator snapshot."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.target_humidity == 50


def test_current_humidity_reflects_attr_2(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """current_humidity reads attr 2 from the coordinator snapshot."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.current_humidity == 58


def test_target_humidity_returns_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """If attr 1 is absent, target_humidity is None."""
    primed_coordinator.data[NODE_ID].pop(ATTR_TARGET_HUMIDITY)
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.target_humidity is None


def test_target_humidity_handles_unparseable(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Non-int values for target_humidity yield None rather than raising."""
    primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] = "garbage"
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.target_humidity is None


def test_current_humidity_handles_unparseable(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Non-int values for current_humidity yield None rather than raising."""
    primed_coordinator.data[NODE_ID][ATTR_CURRENT_HUMIDITY] = object()
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.current_humidity is None


@pytest.mark.parametrize(("raw", "expected"), list(MODE_VALUE_MAP.items()))
def test_mode_maps_via_value_map(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    raw: int,
    expected: str,
) -> None:
    """Every integer in MODE_VALUE_MAP maps to the right mode string."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = raw
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.mode == expected


def test_mode_returns_none_for_unknown_int(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """An unknown mode integer returns None."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = 99
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.mode is None


def test_mode_returns_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A missing mode attribute returns None."""
    primed_coordinator.data[NODE_ID].pop(ATTR_MODE)
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.mode is None


def test_mode_handles_non_int(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Garbage in the mode attribute is treated as unknown."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = "??"
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.mode is None


def test_is_on_true_when_mode_known(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """is_on is True whenever mode resolves to a known value."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.is_on is True


def test_is_on_false_for_unknown_mode(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """is_on is False when the mode attribute is absent or unknown."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = 99
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.is_on is False


async def test_async_set_humidity_writes_target_path(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A normal set_humidity call writes the target path with the given value."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(50)
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID,
        attribute_path=EXPECTED_TARGET_PATH,
        value=50,
    )


async def test_async_set_humidity_clamps_low(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Values below MIN_HUMIDITY are clamped before writing."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(20)
    _, kwargs = mock_matter_client.write_attribute.call_args
    assert kwargs["value"] == MIN_HUMIDITY


async def test_async_set_humidity_clamps_high(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Values above MAX_HUMIDITY are clamped before writing."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(99)
    _, kwargs = mock_matter_client.write_attribute.call_args
    assert kwargs["value"] == MAX_HUMIDITY


async def test_async_set_humidity_updates_local_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """After a successful write the optimistic local cache is updated."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(60)
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 60


async def test_async_set_mode_writes_int_for_known_mode(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """``async_set_mode("comfort")`` writes integer 2 to the mode path."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_mode("comfort")
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID,
        attribute_path=EXPECTED_MODE_PATH,
        value=2,
    )


async def test_async_set_mode_unknown_logs_warning(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unknown mode logs a warning and does not write."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    with caplog.at_level(logging.WARNING, logger="custom_components.tcl_matter"):
        await entity.async_set_mode("turbo")
    mock_matter_client.write_attribute.assert_not_called()
    assert any("Unknown TCL mode" in rec.message for rec in caplog.records)


async def test_write_attribute_falls_back_to_positional(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """If kw-arg write raises TypeError, positional invocation is retried."""
    calls: list[Any] = []

    async def _write(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        if kwargs:
            msg = "unsupported"
            raise TypeError(msg)

    mock_matter_client.write_attribute = AsyncMock(side_effect=_write)
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(50)

    # First attempt with kwargs, second attempt positional.
    assert len(calls) == 2
    assert calls[1][0] == (NODE_ID, EXPECTED_TARGET_PATH, 50)


async def test_write_attribute_missing_method_no_op(
    primed_coordinator: TclMatterCoordinator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If matter_client has no write_attribute, the call logs and no-ops."""
    bad_client = MagicMock(spec=[])
    entity = TclDehumidifier(primed_coordinator, bad_client, NODE_ID)
    with caplog.at_level(logging.ERROR, logger="custom_components.tcl_matter"):
        await entity.async_set_humidity(50)
    assert any("write_attribute" in rec.message for rec in caplog.records)
