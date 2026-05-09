"""Tests for ``custom_components.tcl_matter.select``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tcl_matter.const import (
    ATTR_MODE,
    MODE_VALUE_MAP,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.select import TclModeSelect

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5
EXPECTED_MODE_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}"


@pytest.mark.parametrize(("raw", "expected"), list(MODE_VALUE_MAP.items()))
def test_current_option_maps_correctly(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    raw: int,
    expected: str,
) -> None:
    """Each mode integer maps to the matching option name."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = raw
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    assert select.current_option == expected


def test_current_option_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A missing mode yields None."""
    primed_coordinator.data[NODE_ID].pop(ATTR_MODE)
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    assert select.current_option is None


def test_current_option_none_for_unparseable(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A non-int mode yields None."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = "??"
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    assert select.current_option is None


async def test_async_select_option_writes_correct_value(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A known option writes the matching integer to the mode path."""
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    await select.async_select_option("smart")
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID,
        attribute_path=EXPECTED_MODE_PATH,
        value=3,
    )


async def test_async_select_option_updates_local_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Optimistically applies the new value to the coordinator snapshot."""
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    await select.async_select_option("dry")
    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == 4


async def test_async_select_option_unknown_logs_warning(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unknown option logs a warning and does not write."""
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    with caplog.at_level(logging.WARNING, logger="custom_components.tcl_matter"):
        await select.async_select_option("turbo")
    mock_matter_client.write_attribute.assert_not_called()
    assert any("Unknown TCL mode" in rec.message for rec in caplog.records)


async def test_async_select_option_falls_back_to_positional(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Positional fallback is exercised when kwargs raise TypeError."""
    calls: list[Any] = []

    async def _write(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        if kwargs:
            raise TypeError("kwargs not supported")

    mock_matter_client.write_attribute = AsyncMock(side_effect=_write)
    select = TclModeSelect(primed_coordinator, mock_matter_client, NODE_ID)
    await select.async_select_option("comfort")

    assert len(calls) == 2
    assert calls[1][0] == (NODE_ID, EXPECTED_MODE_PATH, 2)


async def test_async_select_option_missing_write_attribute(
    primed_coordinator: TclMatterCoordinator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A matter client without write_attribute logs an error and no-ops."""
    bad_client = MagicMock(spec=[])
    select = TclModeSelect(primed_coordinator, bad_client, NODE_ID)
    with caplog.at_level(logging.ERROR, logger="custom_components.tcl_matter"):
        await select.async_select_option("comfort")
    assert any("write_attribute" in rec.message for rec in caplog.records)
