"""Tests for ``custom_components.tcl_matter.matter_io``."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tcl_matter import matter_io
from custom_components.tcl_matter.matter_io import (
    WriteRejectedError,
    live_device_command,
    live_read_attribute,
    live_write_attribute,
)


async def test_read_calls_typed_method_with_keywords() -> None:
    """The read goes through ``read_attribute`` with keyword arguments."""
    client = MagicMock()
    client.read_attribute = AsyncMock(return_value={"1/2/3": 4})
    result = await live_read_attribute(client, 7, "1/2/3")
    assert result == {"1/2/3": 4}
    client.read_attribute.assert_awaited_once_with(node_id=7, attribute_path="1/2/3")


async def test_read_propagates_errors() -> None:
    """Server errors are not swallowed here."""
    client = MagicMock()
    client.read_attribute = AsyncMock(side_effect=RuntimeError("nope"))
    with pytest.raises(RuntimeError, match="nope"):
        await live_read_attribute(client, 7, "1/2/3")


async def test_read_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent server raises TimeoutError instead of hanging."""
    monkeypatch.setattr(matter_io, "READ_TIMEOUT_SECONDS", 0.01)
    client = MagicMock()

    async def _hang(**_kwargs: object) -> None:
        await asyncio.sleep(1)

    client.read_attribute = AsyncMock(side_effect=_hang)
    with pytest.raises(TimeoutError):
        await live_read_attribute(client, 7, "1/2/3")


async def test_write_calls_typed_method_with_keywords() -> None:
    """The write goes through ``write_attribute`` with keyword arguments."""
    client = MagicMock()
    client.write_attribute = AsyncMock(return_value=[{"Path": {}, "Status": 0}])
    await live_write_attribute(client, 7, "1/2/3", 42)
    client.write_attribute.assert_awaited_once_with(
        node_id=7, attribute_path="1/2/3", value=42
    )


@pytest.mark.parametrize("result", [None, [], [{"Status": 0}], [{"Path": {}}], "ok"])
async def test_write_accepts_clean_results(result: object) -> None:
    """Missing, empty or zero statuses are accepted."""
    client = MagicMock()
    client.write_attribute = AsyncMock(return_value=result)
    await live_write_attribute(client, 7, "1/2/3", 42)


async def test_write_rejected_status_raises() -> None:
    """A non-zero status is raised as WriteRejectedError."""
    client = MagicMock()
    client.write_attribute = AsyncMock(return_value=[{"Path": {}, "Status": 135}])
    with pytest.raises(WriteRejectedError) as err:
        await live_write_attribute(client, 7, "1/2/3", 42)
    assert err.value.status == 135
    assert err.value.path == "1/2/3"


async def test_write_propagates_errors() -> None:
    """Server errors are not swallowed here."""
    client = MagicMock()
    client.write_attribute = AsyncMock(side_effect=RuntimeError("nope"))
    with pytest.raises(RuntimeError, match="nope"):
        await live_write_attribute(client, 7, "1/2/3", 42)


async def test_write_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent server raises TimeoutError instead of hanging."""
    monkeypatch.setattr(matter_io, "WRITE_TIMEOUT_SECONDS", 0.01)
    client = MagicMock()

    async def _hang(**_kwargs: object) -> None:
        await asyncio.sleep(1)

    client.write_attribute = AsyncMock(side_effect=_hang)
    with pytest.raises(TimeoutError):
        await live_write_attribute(client, 7, "1/2/3", 42)


async def test_device_command_shape() -> None:
    """The command goes out as a device_command with an empty payload."""
    client = MagicMock()
    client.send_command = AsyncMock()
    await live_device_command(client, 7, 1, 6, "On")
    client.send_command.assert_awaited_once_with(
        "device_command",
        node_id=7,
        endpoint_id=1,
        cluster_id=6,
        command_name="On",
        payload={},
    )
