"""Tests for the filter reset button."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tcl_matter.button import TclFilterResetButton
from custom_components.tcl_matter.const import ATTR_FILTER_ALERT, TCL_CLUSTER_FC03

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator

NODE_ID = 5
FILTER_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_FILTER_ALERT}"


async def test_press_writes_false_when_alert_is_set(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """With the alert set, pressing writes False and updates the cache."""
    primed_coordinator.data[NODE_ID][ATTR_FILTER_ALERT] = True
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: True})
    await TclFilterResetButton(primed_coordinator, NODE_ID).async_press()
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID, attribute_path=FILTER_PATH, value=False
    )
    assert primed_coordinator.data[NODE_ID][ATTR_FILTER_ALERT] is False


async def test_press_is_silent_when_alert_already_clear(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """No write is sent when the device already reports the alert clear."""
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: False})
    await TclFilterResetButton(primed_coordinator, NODE_ID).async_press()
    mock_matter_client.write_attribute.assert_not_called()


async def test_press_failure_raises(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed write is reported to the caller."""
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: True})
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("x"))
    with pytest.raises(HomeAssistantError):
        await TclFilterResetButton(primed_coordinator, NODE_ID).async_press()


def test_button_metadata(primed_coordinator: TclMatterCoordinator) -> None:
    """The button is a config-category entity with a stable unique id."""
    button = TclFilterResetButton(primed_coordinator, NODE_ID)
    assert button.unique_id == f"tcl_matter_{NODE_ID}_reset_filter"
    assert button.entity_category == "config"
