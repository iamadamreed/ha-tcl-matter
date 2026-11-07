"""Tests for the shared entity base: availability and device info."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tcl_matter.const import MATTER_DOMAIN
from custom_components.tcl_matter.sensor import TclCurrentHumiditySensor

from .conftest import FABRIC_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.tcl_matter.coordinator import TclMatterCoordinator

NODE_ID = 5


def test_available_when_node_reachable_and_data_present(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Data present and node reachable means available."""
    assert TclCurrentHumiditySensor(primed_coordinator, NODE_ID).available is True


def test_unavailable_when_matter_server_marks_node_offline(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """node.available False from the matter server makes entities unavailable."""
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    primed_coordinator.get_node(NODE_ID).available = False
    assert entity.available is False


def test_unavailable_without_data(primed_coordinator: TclMatterCoordinator) -> None:
    """No snapshot for the node means unavailable."""
    primed_coordinator.data[NODE_ID] = {}
    assert TclCurrentHumiditySensor(primed_coordinator, NODE_ID).available is False


def test_device_info_comes_from_the_node(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Name, model and versions are read from the node's BasicInformation."""
    info = TclCurrentHumiditySensor(primed_coordinator, NODE_ID).device_info
    assert info["name"] == "TCL Dehumidifier"
    assert info["manufacturer"] == "TCL"
    assert info["model_id"] == str(0x8002)
    assert info["sw_version"] == "1.0.0"
    assert "via_device_id" not in info  # entity not added to hass yet


def test_device_info_follows_a_firmware_change(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """The software version is not frozen when the entity is created."""
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    primed_coordinator.get_node(NODE_ID).device_info.softwareVersionString = "2.0"
    assert entity.device_info["sw_version"] == "2.0"


def test_device_info_falls_back_without_basic_information(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A node with no readable BasicInformation still gets a sensible device."""
    primed_coordinator.get_node(NODE_ID).device_info = None
    info = TclCurrentHumiditySensor(primed_coordinator, NODE_ID).device_info
    assert info["name"] == "TCL Dehumidifier"
    assert info["manufacturer"] == "TCL"
    assert "model_id" not in info


def test_device_info_links_to_the_matter_device(
    hass: HomeAssistant,
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """When the matter device exists, via_device_id points at it."""
    matter_entry = MockConfigEntry(domain=MATTER_DOMAIN)
    matter_entry.add_to_hass(hass)
    parent = dr.async_get(hass).async_get_or_create(
        config_entry_id=matter_entry.entry_id,
        identifiers={
            (
                MATTER_DOMAIN,
                f"deviceid_{FABRIC_ID:016X}-{NODE_ID:016X}-MatterNodeDevice",
            )
        },
    )
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    entity.hass = hass
    assert entity.device_info["via_device_id"] == parent.id


def test_device_info_has_no_link_without_a_matter_device(
    hass: HomeAssistant,
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """If the matter device isn't registered yet there is simply no link."""
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    entity.hass = hass
    assert "via_device_id" not in entity.device_info


def test_device_info_without_fabric_id_has_no_link(
    hass: HomeAssistant,
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """With no fabric id the matter device can't be named, so no link is set."""
    mock_matter_client.server_info = MagicMock()
    entity = TclCurrentHumiditySensor(primed_coordinator, NODE_ID)
    entity.hass = hass
    assert "via_device_id" not in entity.device_info
