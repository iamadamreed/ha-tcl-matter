"""Tests for the pump switch."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tcl_matter.const import ATTR_PUMP, TCL_CLUSTER_FC03
from custom_components.tcl_matter.switch import TclPumpSwitch

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator

NODE_ID = 5
PUMP_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_PUMP}"


@pytest.mark.parametrize(("raw", "expected"), [(True, True), (False, False)])
def test_pump_state_follows_the_attribute(
    primed_coordinator: TclMatterCoordinator, raw: bool, expected: bool
) -> None:
    """The switch shows the pump setting."""
    primed_coordinator.data[NODE_ID][ATTR_PUMP] = raw
    assert TclPumpSwitch(primed_coordinator, NODE_ID).is_on is expected


@pytest.mark.parametrize(
    ("method", "current", "value"),
    [("async_turn_on", False, True), ("async_turn_off", True, False)],
)
async def test_turning_the_switch_writes_the_attribute(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    method: str,
    current: bool,
    value: bool,
) -> None:
    """Turning the switch on or off writes the new value and stores it."""
    primed_coordinator.data[NODE_ID][ATTR_PUMP] = current
    mock_matter_client.read_attribute = AsyncMock(return_value={PUMP_PATH: current})
    await getattr(TclPumpSwitch(primed_coordinator, NODE_ID), method)()
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID, attribute_path=PUMP_PATH, value=value
    )
    assert primed_coordinator.data[NODE_ID][ATTR_PUMP] is value


async def test_a_failed_write_is_reported(
    primed_coordinator: TclMatterCoordinator, mock_matter_client: MagicMock
) -> None:
    """A write that fails raises to the caller."""
    mock_matter_client.read_attribute = AsyncMock(return_value={PUMP_PATH: False})
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("x"))
    with pytest.raises(HomeAssistantError):
        await TclPumpSwitch(primed_coordinator, NODE_ID).async_turn_on()


def test_switch_unique_id(primed_coordinator: TclMatterCoordinator) -> None:
    """The unique id reflects the switch's role."""
    switch = TclPumpSwitch(primed_coordinator, NODE_ID)
    assert switch.unique_id == f"tcl_matter_{NODE_ID}_pump"
