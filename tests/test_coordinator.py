"""Tests for ``custom_components.tcl_matter.coordinator``."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tcl_matter import const
from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_PUMP,
    ATTR_TARGET_HUMIDITY,
    NUM_TCL_FC03_DATA_ATTRS,
    TCL_CLUSTER_FC03,
    UNAVAILABLE_AFTER_FAILURES,
)
from custom_components.tcl_matter.coordinator import TclMatterCoordinator

from .conftest import strip_decoded_values

if TYPE_CHECKING:
    from collections.abc import Callable

NODE_ID = 5
OTHER_NODE_ID = 6


def _path(attr_id: int) -> str:
    return f"1/{TCL_CLUSTER_FC03}/{attr_id}"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_cluster_response_flat_paths() -> None:
    """A flat path-keyed response becomes {attr_id: value}."""
    result = {_path(0): 2, _path(1): 50, _path(5): "[]"}
    assert TclMatterCoordinator._parse_cluster_response(result) == {
        0: 2,
        1: 50,
        5: "[]",
    }


def test_parse_cluster_response_skips_metadata_attrs() -> None:
    """Cluster metadata attributes (>= 0xFFF8) are dropped."""
    result = {_path(1): 50, _path(65528): [], _path(65533): 1}
    assert TclMatterCoordinator._parse_cluster_response(result) == {1: 50}


def test_parse_cluster_response_skips_other_clusters() -> None:
    """Paths for other clusters or endpoints are ignored."""
    result = {_path(1): 50, "1/6/0": True, f"2/{TCL_CLUSTER_FC03}/1": 9}
    assert TclMatterCoordinator._parse_cluster_response(result) == {1: 50}


@pytest.mark.parametrize("bad", [None, [], "text", 5, [("a", 1)]])
def test_parse_cluster_response_rejects_non_dict(bad: Any) -> None:
    """Anything but a dict yields an empty result."""
    assert TclMatterCoordinator._parse_cluster_response(bad) == {}


def test_parse_cluster_response_handles_unparseable_keys() -> None:
    """Keys that are not paths, or have a non-numeric attribute, are skipped."""
    result = {5: 1, "junk": 2, f"1/{TCL_CLUSTER_FC03}/x": 3, _path(2): 58}
    assert TclMatterCoordinator._parse_cluster_response(result) == {2: 58}


def test_data_attribute_range_covers_defined_attributes() -> None:
    """The data-attribute window includes every attribute the integration uses."""
    used = {
        const.ATTR_MODE,
        const.ATTR_TARGET_HUMIDITY,
        const.ATTR_CURRENT_HUMIDITY,
        const.ATTR_BUCKET_FULL,
        const.ATTR_PUMP,
        const.ATTR_ERROR_CODES,
        const.ATTR_FEATURE_SET,
    }
    assert used == set(range(NUM_TCL_FC03_DATA_ATTRS))


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


async def test_poll_uses_the_decoded_values_without_a_round_trip(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """The client's decoded cluster values are used and nothing is read remotely."""
    node = primed_coordinator.get_node(NODE_ID)
    node.node_data.attributes[_path(ATTR_TARGET_HUMIDITY)] = 61
    await primed_coordinator.async_refresh()
    mock_matter_client.read_attribute.assert_not_called()
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 61


async def test_poll_falls_back_to_a_wildcard_read_without_a_decoder(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A client with no decoder leaves nothing on the node, so the poll reads."""
    strip_decoded_values(primed_coordinator.get_node(NODE_ID))
    await primed_coordinator.async_refresh()
    mock_matter_client.read_attribute.assert_awaited_once_with(
        node_id=NODE_ID, attribute_path=f"1/{TCL_CLUSTER_FC03}/*"
    )
    assert primed_coordinator.last_update_success is True
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 50


async def test_node_without_endpoint_1_falls_back_to_a_read(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A KeyError from the node lookup is treated as 'no decoded values'."""
    node = primed_coordinator.get_node(NODE_ID)
    node.get_attribute_value = MagicMock(side_effect=KeyError(1))
    await primed_coordinator.async_refresh()
    mock_matter_client.read_attribute.assert_awaited_once()


async def test_poll_all_nodes_failing_raises(
    make_coordinator: Callable[..., TclMatterCoordinator],
    make_tcl_device: Callable[..., Any],
    mock_matter_client: MagicMock,
) -> None:
    """If no node can be read the update fails."""
    device = make_tcl_device(NODE_ID)
    strip_decoded_values(device.node)
    coordinator = make_coordinator({NODE_ID: device})
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("down"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_poll_empty_response_counts_as_failure(
    make_coordinator: Callable[..., TclMatterCoordinator],
    make_tcl_device: Callable[..., Any],
    mock_matter_client: MagicMock,
) -> None:
    """A response with no cluster attributes is treated as a failed read."""
    device = make_tcl_device(NODE_ID)
    strip_decoded_values(device.node)
    coordinator = make_coordinator({NODE_ID: device})
    mock_matter_client.read_attribute = AsyncMock(return_value={"junk": 1})
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator.node_available(NODE_ID) is True  # one failure only


async def test_one_failing_node_does_not_fail_the_others(
    make_coordinator: Callable[..., TclMatterCoordinator],
    make_tcl_device: Callable[..., Any],
    mock_matter_client: MagicMock,
) -> None:
    """A node that can't be read leaves the other node's data intact."""
    devices = {
        NODE_ID: make_tcl_device(NODE_ID),
        OTHER_NODE_ID: make_tcl_device(OTHER_NODE_ID),
    }
    for device in devices.values():
        strip_decoded_values(device.node)
    coordinator = make_coordinator(devices)

    async def _read(*, node_id: int, attribute_path: str) -> dict[str, Any]:
        if node_id == OTHER_NODE_ID:
            msg = "offline"
            raise RuntimeError(msg)
        return {_path(ATTR_TARGET_HUMIDITY): 55}

    mock_matter_client.read_attribute = AsyncMock(side_effect=_read)
    data = await coordinator._async_update_data()
    assert data == {NODE_ID: {ATTR_TARGET_HUMIDITY: 55}}


async def test_node_goes_unavailable_after_repeated_failures_and_recovers(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failures mark the node unavailable (one warning), and success restores it."""
    strip_decoded_values(primed_coordinator.get_node(NODE_ID))
    good = mock_matter_client.read_attribute
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("down"))
    with caplog.at_level(logging.INFO, logger="custom_components.tcl_matter"):
        for _ in range(UNAVAILABLE_AFTER_FAILURES + 1):
            await primed_coordinator.async_refresh()
        assert primed_coordinator.node_available(NODE_ID) is False
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

        mock_matter_client.read_attribute = good
        await primed_coordinator.async_refresh()
    assert primed_coordinator.node_available(NODE_ID) is True
    assert any("available again" in r.message for r in caplog.records)


async def test_node_unavailable_when_matter_server_says_so(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """node.available False from the matter server makes the node unavailable."""
    primed_coordinator.get_node(NODE_ID).available = False
    assert primed_coordinator.node_available(NODE_ID) is False


def test_unknown_node_is_unavailable(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A node id the coordinator doesn't serve is not available."""
    assert primed_coordinator.node_available(999) is False
    assert primed_coordinator.get_node(999) is None


async def test_poll_in_flight_does_not_overwrite_a_newer_write(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A value written while a poll is reading is kept when the poll returns."""
    strip_decoded_values(primed_coordinator.get_node(NODE_ID))
    release = asyncio.Event()

    async def _slow_read(*, node_id: int, attribute_path: str) -> dict[str, Any]:
        if attribute_path.endswith("/*"):
            await release.wait()  # sampled before the write lands
            return {_path(ATTR_TARGET_HUMIDITY): 50, _path(ATTR_CURRENT_HUMIDITY): 61}
        return {attribute_path: 50}  # pre-write dedupe read: device not at 45

    mock_matter_client.read_attribute = AsyncMock(side_effect=_slow_read)
    poll = asyncio.create_task(primed_coordinator.async_refresh())
    await asyncio.sleep(0)
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, 45)
    release.set()
    await poll

    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 45
    # Attributes that were not touched still take the polled value.
    assert primed_coordinator.data[NODE_ID][ATTR_CURRENT_HUMIDITY] == 61


async def test_poll_in_flight_does_not_overwrite_a_newer_push(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A pushed value that arrives during a poll is kept."""
    strip_decoded_values(primed_coordinator.get_node(NODE_ID))
    release = asyncio.Event()

    async def _slow_read(*, node_id: int, attribute_path: str) -> dict[str, Any]:
        await release.wait()
        return {_path(ATTR_PUMP): False}

    mock_matter_client.read_attribute = AsyncMock(side_effect=_slow_read)
    poll = asyncio.create_task(primed_coordinator.async_refresh())
    await asyncio.sleep(0)
    pushed = True
    primed_coordinator.handle_attribute_update(NODE_ID, ATTR_PUMP, "e", pushed)
    release.set()
    await poll
    assert primed_coordinator.data[NODE_ID][ATTR_PUMP] is True


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


async def test_handle_attribute_update_stores_value(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A pushed value for a known node replaces the cached one."""
    primed_coordinator.handle_attribute_update(NODE_ID, ATTR_MODE, "event", 3)
    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == 3
    # The rest of the node's data is untouched.
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 50


async def test_handle_attribute_update_skips_an_unchanged_value(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A push that repeats the cached value does not notify listeners."""
    calls: list[int] = []
    primed_coordinator.async_add_listener(lambda: calls.append(1))
    primed_coordinator.handle_attribute_update(NODE_ID, ATTR_MODE, "event", 0)
    assert calls == []
    primed_coordinator.handle_attribute_update(NODE_ID, ATTR_MODE, "event", 2)
    assert calls == [1]


async def test_stores_do_not_restart_the_poll_timer(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A push or write must not push the next poll back (it would starve it)."""
    with patch.object(primed_coordinator, "_schedule_refresh") as schedule:
        primed_coordinator.handle_attribute_update(NODE_ID, ATTR_MODE, "event", 3)
        await primed_coordinator.async_write_attribute(
            NODE_ID, ATTR_TARGET_HUMIDITY, 60
        )
    schedule.assert_not_called()


async def test_handle_state_change_notifies_listeners(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A node or OnOff event re-renders listeners without touching the data."""
    calls: list[int] = []
    primed_coordinator.async_add_listener(lambda: calls.append(1))
    before = {k: dict(v) for k, v in primed_coordinator.data.items()}
    primed_coordinator.handle_state_change("event", object())
    assert calls == [1]
    assert primed_coordinator.data == before


# ---------------------------------------------------------------------------
# Writes and commands
# ---------------------------------------------------------------------------


async def test_write_sends_value_and_stores_it(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A changed value is written to the device and stored."""
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, 60)
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID, attribute_path=_path(ATTR_TARGET_HUMIDITY), value=60
    )
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 60


async def test_write_dedupes_against_the_device_not_the_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """The skip decision uses a live read: a stale cache must not drop a write."""
    # Cache says 50; the device was changed at the unit to 70.
    mock_matter_client.read_attribute = AsyncMock(
        return_value={_path(ATTR_TARGET_HUMIDITY): 70}
    )
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, 50)
    mock_matter_client.write_attribute.assert_awaited_once()


async def test_write_skipped_when_device_already_holds_value(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """No write is sent when the device already has the value."""
    mock_matter_client.read_attribute = AsyncMock(
        return_value={_path(ATTR_TARGET_HUMIDITY): 60}
    )
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, 60)
    mock_matter_client.write_attribute.assert_not_called()
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == 60


async def test_write_proceeds_when_prewrite_read_fails(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed or timed-out dedupe read must not block the write."""
    mock_matter_client.read_attribute = AsyncMock(side_effect=TimeoutError)
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_MODE, 3)
    mock_matter_client.write_attribute.assert_awaited_once()


async def test_write_failure_raises_and_keeps_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed write raises HomeAssistantError and leaves the cache alone."""
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(HomeAssistantError) as err:
        await primed_coordinator.async_write_attribute(NODE_ID, ATTR_MODE, 3)
    assert err.value.translation_key == "write_failed"
    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == 0


async def test_rejected_write_raises_and_keeps_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A write the device rejects with a non-zero status is not stored."""
    mock_matter_client.write_attribute = AsyncMock(
        return_value=[{"Path": {}, "Status": 135}]
    )
    with pytest.raises(HomeAssistantError) as err:
        await primed_coordinator.async_write_attribute(NODE_ID, ATTR_MODE, 3)
    assert err.value.translation_key == "write_rejected"
    assert err.value.translation_placeholders["status"] == "135"
    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == 0


async def test_concurrent_writes_to_one_attribute_do_not_overlap(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Writes to the same attribute are serialised by a per-attribute lock."""
    inflight = 0
    peak = 0

    async def _slow_write(**_kwargs: Any) -> None:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1

    mock_matter_client.write_attribute = AsyncMock(side_effect=_slow_write)
    await asyncio.gather(
        *(
            primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, v)
            for v in (60, 61, 62)
        )
    )
    assert peak == 1
    assert mock_matter_client.write_attribute.await_count == 3


async def test_writes_to_different_attributes_can_overlap(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Locks are per attribute, so different attributes don't wait on each other."""
    inflight = 0
    peak = 0

    async def _slow_write(**_kwargs: Any) -> None:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1

    mock_matter_client.write_attribute = AsyncMock(side_effect=_slow_write)
    await asyncio.gather(
        primed_coordinator.async_write_attribute(NODE_ID, ATTR_TARGET_HUMIDITY, 60),
        primed_coordinator.async_write_attribute(NODE_ID, ATTR_MODE, 3),
    )
    assert peak == 2


async def test_send_command_forwards_to_the_server(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """An argument-less cluster command goes out as a device_command."""
    mock_matter_client.send_command = AsyncMock()
    await primed_coordinator.async_send_command(NODE_ID, 1, 6, "Off")
    mock_matter_client.send_command.assert_awaited_once_with(
        "device_command",
        node_id=NODE_ID,
        endpoint_id=1,
        cluster_id=6,
        command_name="Off",
        payload={},
    )


async def test_send_command_failure_raises(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed command surfaces as HomeAssistantError."""
    mock_matter_client.send_command = AsyncMock(side_effect=RuntimeError("x"))
    with pytest.raises(HomeAssistantError) as err:
        await primed_coordinator.async_send_command(NODE_ID, 1, 6, "On")
    assert err.value.translation_key == "command_failed"
