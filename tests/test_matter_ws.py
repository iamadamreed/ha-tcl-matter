"""Tests for ``custom_components.tcl_matter.matter_ws``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tcl_matter.const import TCL_CLUSTER_FC03
from custom_components.tcl_matter.matter_ws import (
    live_read_attribute,
    live_write_attribute,
)


async def test_live_read_attribute_calls_typed_method() -> None:
    """``live_read_attribute`` delegates to ``matter_client.read_attribute``."""
    client = MagicMock()
    client.read_attribute = AsyncMock(return_value={"1/322239491/1": 45})

    out = await live_read_attribute(client, node_id=5, attribute_path="1/322239491/1")

    assert out == {"1/322239491/1": 45}
    client.read_attribute.assert_awaited_once_with(
        node_id=5, attribute_path="1/322239491/1"
    )


async def test_live_read_attribute_returns_server_response_unchanged() -> None:
    """The function must return the matter-server response verbatim."""
    expected: dict[str, Any] = {
        f"1/{TCL_CLUSTER_FC03}/0": 0,
        f"1/{TCL_CLUSTER_FC03}/1": 45,
        f"1/{TCL_CLUSTER_FC03}/2": 52,
    }
    client = MagicMock()
    client.read_attribute = AsyncMock(return_value=expected)

    out = await live_read_attribute(
        client, node_id=5, attribute_path=f"1/{TCL_CLUSTER_FC03}/*"
    )

    assert out == expected


async def test_live_read_attribute_propagates_server_errors() -> None:
    """Errors from the typed method bubble up to the caller, not swallowed."""
    client = MagicMock()
    client.read_attribute = AsyncMock(side_effect=RuntimeError("transport closed"))

    with pytest.raises(RuntimeError, match="transport closed"):
        await live_read_attribute(client, node_id=5, attribute_path="1/0/0")


async def test_live_write_attribute_calls_typed_method() -> None:
    """``live_write_attribute`` delegates to ``matter_client.write_attribute``."""
    client = MagicMock()
    client.write_attribute = AsyncMock(return_value=None)

    await live_write_attribute(
        client,
        node_id=5,
        attribute_path=f"1/{TCL_CLUSTER_FC03}/1",
        value=45,
    )

    client.write_attribute.assert_awaited_once_with(
        node_id=5,
        attribute_path=f"1/{TCL_CLUSTER_FC03}/1",
        value=45,
    )


async def test_live_write_attribute_propagates_server_errors() -> None:
    """Server-side write errors propagate so callers can log them once."""
    client = MagicMock()
    client.write_attribute = AsyncMock(side_effect=ValueError("invalid value"))

    with pytest.raises(ValueError, match="invalid value"):
        await live_write_attribute(
            client, node_id=5, attribute_path="1/322239491/1", value=999
        )


async def test_write_value_round_trips_via_fixture(
    mock_matter_client: MagicMock,
) -> None:
    """Round trip: write through the fixture, subsequent read returns it.

    The shared ``mock_matter_client`` fixture stores writes in its
    response dict. This test verifies both helpers are wired against the
    same backing channel — important for confidence that integration
    tests using the same fixture exercise a coherent matter-server.
    """
    path = f"1/{TCL_CLUSTER_FC03}/1"
    await live_write_attribute(
        mock_matter_client, node_id=5, attribute_path=path, value=44
    )
    snapshot = await live_read_attribute(
        mock_matter_client, node_id=5, attribute_path=f"1/{TCL_CLUSTER_FC03}/*"
    )
    assert snapshot[path] == 44
