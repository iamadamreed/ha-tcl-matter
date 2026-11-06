"""Tests for ``custom_components.tcl_matter.humidifier``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

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
    return TclDehumidifier(primed_coordinator, NODE_ID)


# ---------------------------------------------------------------------------
# Read properties — driven entirely off the coordinator snapshot.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Write path — live writes via matter_client.write_attribute.
# ---------------------------------------------------------------------------


async def test_async_set_humidity_calls_write_attribute(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """``set_humidity`` invokes the typed ``write_attribute`` for attr 1."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    # primed default is 50; write 60 so dedup doesn't short-circuit.
    await entity.async_set_humidity(60)
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID,
        attribute_path=EXPECTED_TARGET_PATH,
        value=60,
    )


async def test_async_set_humidity_clamps_low(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Values below MIN_HUMIDITY are clamped before writing."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(20)
    assert mock_matter_client.write_attribute.call_args.kwargs["value"] == MIN_HUMIDITY


async def test_async_set_humidity_clamps_high(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Values above MAX_HUMIDITY are clamped before writing."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(99)
    assert mock_matter_client.write_attribute.call_args.kwargs["value"] == MAX_HUMIDITY


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


async def test_async_set_mode_unknown_raises_validation_error(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """An unknown mode is a user error: raise, and write nothing."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    with pytest.raises(ServiceValidationError) as err:
        await entity.async_set_mode("turbo")
    assert err.value.translation_key == "unknown_mode"
    mock_matter_client.write_attribute.assert_not_called()


async def test_write_failure_raises_without_cache_update(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failing live write raises to the caller and leaves the cache untouched."""
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("nope"))
    entity = _make_entity(primed_coordinator, mock_matter_client)
    before = primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY]

    with pytest.raises(HomeAssistantError):
        await entity.async_set_humidity(60)

    # Cache must NOT optimistically advance when the device write failed.
    assert primed_coordinator.data[NODE_ID][ATTR_TARGET_HUMIDITY] == before


# ---------------------------------------------------------------------------
# Defensive write-loop semaphore behaviour.
# ---------------------------------------------------------------------------


async def test_write_dedup_skips_redundant_value(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Writing the same value as the current cache must NOT round-trip."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    # primed cache says target_humidity=50 already.
    await entity.async_set_humidity(50)
    mock_matter_client.write_attribute.assert_not_called()


async def test_write_dedup_does_not_block_a_real_change(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A different value DOES still issue the write."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(60)
    assert mock_matter_client.write_attribute.await_count == 1


async def test_write_dedup_per_attribute_independent(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Dedup is per-attribute: writing humidity then mode both go through."""
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_set_humidity(60)  # different from cached 50 → writes
    await entity.async_set_mode("continue")  # different from cached 0 → writes
    assert mock_matter_client.write_attribute.await_count == 2


# ---------------------------------------------------------------------------
# Power: OnOff cluster
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("on_off", "expected"), [(True, True), (False, False)])
def test_is_on_follows_onoff_cluster(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    on_off: bool,
    expected: bool,
) -> None:
    """Power state comes from the OnOff cluster when it can be read."""
    node = primed_coordinator.get_node(NODE_ID)
    node.node_data.attributes["1/6/0"] = on_off
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.is_on is expected


def test_is_on_survives_a_failing_node_lookup(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """If the node cache lookup raises, fall back to the mode heuristic."""
    node = primed_coordinator.get_node(NODE_ID)
    node.get_attribute_value = MagicMock(side_effect=RuntimeError("x"))
    entity = _make_entity(primed_coordinator, mock_matter_client)
    assert entity.is_on is True  # mode attribute is a known value


async def test_turn_off_sends_onoff_command(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """turn_off sends the standard OnOff Off command."""
    mock_matter_client.send_command = AsyncMock()
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_turn_off()
    mock_matter_client.send_command.assert_awaited_once_with(
        "device_command",
        node_id=NODE_ID,
        endpoint_id=1,
        cluster_id=6,
        command_name="Off",
        payload={},
    )


async def test_turn_on_sends_onoff_command(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """turn_on sends the standard OnOff On command."""
    mock_matter_client.send_command = AsyncMock()
    entity = _make_entity(primed_coordinator, mock_matter_client)
    await entity.async_turn_on()
    assert mock_matter_client.send_command.await_args.kwargs["command_name"] == "On"


async def test_turn_on_failure_raises(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed OnOff command raises HomeAssistantError."""
    mock_matter_client.send_command = AsyncMock(side_effect=RuntimeError("x"))
    entity = _make_entity(primed_coordinator, mock_matter_client)
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()
