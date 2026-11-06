"""Tests for the filter reset button, device identity, power state and push."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tcl_matter.button import TclFilterResetButton
from custom_components.tcl_matter.const import (
    ATTR_FILTER_ALERT,
    ATTR_MODE,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.entity import _matter_device_identifier
from custom_components.tcl_matter.humidifier import TclDehumidifier
from custom_components.tcl_matter.sensor import TclCurrentHumiditySensor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.tcl_matter.coordinator import TclMatterCoordinator

NODE_ID = 5
FILTER_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_FILTER_ALERT}"


async def test_reset_button_writes_false(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Pressing the button writes False to the filter alert attribute."""
    primed_coordinator.data[NODE_ID][ATTR_FILTER_ALERT] = True
    primed_coordinator._devices[NODE_ID].attributes[ATTR_FILTER_ALERT] = True
    # The live read says the alert is still set, so the write must happen.
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: True})
    button = TclFilterResetButton(primed_coordinator, NODE_ID)
    await button.async_press()
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID, attribute_path=FILTER_PATH, value=False
    )
    assert primed_coordinator.data[NODE_ID][ATTR_FILTER_ALERT] is False


async def test_reset_button_skips_when_already_clear(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """No write is sent when the device already reports the alert as clear."""
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: False})
    button = TclFilterResetButton(primed_coordinator, NODE_ID)
    await button.async_press()
    mock_matter_client.write_attribute.assert_not_called()


async def test_reset_button_raises_on_failure(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed write surfaces as HomeAssistantError."""
    mock_matter_client.read_attribute = AsyncMock(return_value={FILTER_PATH: True})
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("x"))
    button = TclFilterResetButton(primed_coordinator, NODE_ID)
    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_write_proceeds_when_live_read_fails(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed pre-write read must not block the write."""
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("x"))
    await primed_coordinator.async_write_attribute(NODE_ID, ATTR_MODE, 3)
    mock_matter_client.write_attribute.assert_awaited_once()


def test_device_identifier_matches_matter_integration() -> None:
    """The identifier is deviceid_<fabric>-<node>-MatterNodeDevice, as 16 hex digits."""
    client = MagicMock()
    client.server_info.compressed_fabric_id = 0x55A6683D17125EED
    assert _matter_device_identifier(client, 161) == (
        "matter",
        "deviceid_55A6683D17125EED-00000000000000A1-MatterNodeDevice",
    )


def test_device_identifier_none_without_fabric_id() -> None:
    """Without a usable fabric id the caller falls back to a standalone device."""
    assert _matter_device_identifier(MagicMock(), 161) is None
    assert _matter_device_identifier(object(), 161) is None


def test_entity_links_to_matter_device_via_device(
    hass: HomeAssistant,
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """The device is a child of the matter integration's device when it exists."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    mock_matter_client.server_info.compressed_fabric_id = 0xABC
    matter_entry = MockConfigEntry(domain="matter")
    matter_entry.add_to_hass(hass)
    parent = dr.async_get(hass).async_get_or_create(
        config_entry_id=matter_entry.entry_id,
        identifiers={
            ("matter", f"deviceid_{0xABC:016X}-{NODE_ID:016X}-MatterNodeDevice")
        },
    )
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    entity.hass = hass
    info = entity.device_info
    assert info["identifiers"] == {("matter", str(NODE_ID))}
    assert info["via_device_id"] == parent.id
    assert info["name"]


def test_entity_has_no_parent_link_without_fabric_id(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Without a usable fabric id the device stands alone."""
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert "via_device_id" not in entity.device_info


def test_entity_unavailable_when_node_unreachable(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Entities go unavailable when the matter server marks the node offline."""
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    assert entity.available is True
    primed_coordinator._devices[NODE_ID].node.available = False
    assert entity.available is False


@pytest.mark.parametrize(("on_off", "expected"), [(True, True), (False, False)])
def test_is_on_follows_onoff_cluster(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    on_off: bool,
    expected: bool,
) -> None:
    """Power state comes from the OnOff cluster when it can be read."""
    node = primed_coordinator._devices[NODE_ID].node
    node.node_data.attributes["1/6/0"] = on_off
    entity = TclDehumidifier(primed_coordinator, mock_matter_client, NODE_ID)
    assert entity.is_on is expected


async def test_turn_off_sends_onoff_command(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """turn_off sends the standard OnOff Off command."""
    mock_matter_client.send_command = AsyncMock()
    entity = TclDehumidifier(primed_coordinator, mock_matter_client, NODE_ID)
    await entity.async_turn_off()
    mock_matter_client.send_command.assert_awaited_once_with(
        "device_command",
        node_id=NODE_ID,
        endpoint_id=1,
        cluster_id=6,
        command_name="Off",
        payload={},
    )


async def test_turn_on_failure_raises(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failed OnOff command raises HomeAssistantError."""
    mock_matter_client.send_command = AsyncMock(side_effect=RuntimeError("x"))
    entity = TclDehumidifier(primed_coordinator, mock_matter_client, NODE_ID)
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()


def test_push_event_accepts_matter_client_tuple(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """ATTRIBUTE_UPDATED events arrive as (node_id, path, value) tuples."""
    primed_coordinator.handle_push_event(
        "attribute_updated", (NODE_ID, FILTER_PATH, True)
    )
    assert primed_coordinator.data[NODE_ID][ATTR_FILTER_ALERT] is True


def test_push_event_ignores_other_clusters(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Tuples for other clusters are ignored."""
    before = dict(primed_coordinator.data[NODE_ID])
    primed_coordinator.handle_push_event("x", (NODE_ID, "1/6/0", True))
    assert primed_coordinator.data[NODE_ID] == before


async def test_remove_device_allowed_only_when_not_active() -> None:
    """A device for a node we serve can't be removed; a stray one can."""
    from types import SimpleNamespace

    from custom_components.tcl_matter import async_remove_config_entry_device

    entry = SimpleNamespace(runtime_data=SimpleNamespace(devices={NODE_ID: object()}))
    active = SimpleNamespace(identifiers={("matter", str(NODE_ID))})
    stray = SimpleNamespace(identifiers={("matter", "deviceid_X-MatterNodeDevice")})
    assert await async_remove_config_entry_device(None, entry, active) is False
    assert await async_remove_config_entry_device(None, entry, stray) is True
