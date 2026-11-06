"""Tests for the integration lifecycle in ``custom_components.tcl_matter``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from matter_server.common.models import EventType

from custom_components.tcl_matter import (
    TclMatterRuntimeData,
    _node_vendor_id,
    async_remove_config_entry_device,
)
from custom_components.tcl_matter.const import (
    ATTR_FILTER_ALERT,
    DOMAIN,
    MATTER_DOMAIN,
    NUM_TCL_FC03_DATA_ATTRS,
    TCL_CLUSTER_FC03,
    TCL_VENDOR_ID,
)
from custom_components.tcl_matter.device import (
    matter_device_identifier,
    tcl_device_identifier,
)

from .conftest import FABRIC_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

NODE_ID = 5
LEGACY_IDENTIFIER = (MATTER_DOMAIN, str(NODE_ID))
TCL_IDENTIFIER = (DOMAIN, f"{FABRIC_ID:016X}-{NODE_ID:016X}")
MATTER_PARENT_IDENTIFIER = (
    MATTER_DOMAIN,
    f"deviceid_{FABRIC_ID:016X}-{NODE_ID:016X}-MatterNodeDevice",
)

# Every entity unique id the integration creates for one node.
UNIQUE_IDS = {
    ("binary_sensor", "tcl_matter_5_bucket_full"),
    ("binary_sensor", "tcl_matter_5_filter_alert"),
    ("button", "tcl_matter_5_reset_filter"),
    ("humidifier", "tcl_matter_5_dehumidifier"),
    ("select", "tcl_matter_5_mode"),
    ("sensor", "tcl_matter_5_current_humidity"),
    ("sensor", "tcl_matter_5_error_codes"),
}


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the TCL entry up through Home Assistant and let it settle."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None, f"{platform} {unique_id} not registered"
    return entity_id


# ---------------------------------------------------------------------------
# Setup and unload
# ---------------------------------------------------------------------------


async def test_setup_creates_every_entity(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """Setup loads the entry, fills runtime_data and registers all platforms."""
    await _setup(hass, mock_tcl_entry)

    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    runtime: TclMatterRuntimeData = mock_tcl_entry.runtime_data
    assert list(runtime.devices) == [NODE_ID]
    registry = er.async_get(hass)
    found = {
        (e.domain, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, mock_tcl_entry.entry_id)
    }
    assert found == UNIQUE_IDS
    state = hass.states.get(_entity_id(hass, "humidifier", "tcl_matter_5_dehumidifier"))
    assert state is not None
    assert state.attributes["humidity"] == 50


async def test_setup_without_matter_retries(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
) -> None:
    """With no loaded matter entry the TCL entry retries instead of failing."""
    with patch(
        "homeassistant.setup.async_setup_component",
        new=AsyncMock(return_value=True),
    ):
        await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_with_no_tcl_nodes_warns_and_loads(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No TCL device on the fabric still loads, with a warning and no entities."""
    mock_matter_client.get_nodes.return_value = []
    with caplog.at_level(logging.WARNING, logger="custom_components.tcl_matter"):
        await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    assert any("No TCL Matter devices" in r.message for r in caplog.records)
    registry = er.async_get(hass)
    assert not er.async_entries_for_config_entry(registry, mock_tcl_entry.entry_id)


async def test_setup_ignores_non_tcl_nodes(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
    mock_matter_node: MagicMock,
    non_tcl_matter_node: MagicMock,
) -> None:
    """Only TCL-vendor nodes are served."""
    mock_matter_client.get_nodes.return_value = [non_tcl_matter_node, mock_matter_node]
    await _setup(hass, mock_tcl_entry)
    assert list(mock_tcl_entry.runtime_data.devices) == [NODE_ID]


async def test_setup_retries_when_nothing_can_be_read(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
) -> None:
    """If the first read fails the entry goes to setup-retry."""
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("down"))
    await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_releases_every_subscription(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
) -> None:
    """Unloading unsubscribes everything that setup subscribed."""
    await _setup(hass, mock_tcl_entry)
    assert mock_matter_client.subscriptions
    assert all(s.active for s in mock_matter_client.subscriptions)

    assert await hass.config_entries.async_unload(mock_tcl_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_tcl_entry.state is ConfigEntryState.NOT_LOADED
    assert not any(s.active for s in mock_matter_client.subscriptions)


# ---------------------------------------------------------------------------
# Push subscriptions
# ---------------------------------------------------------------------------


async def test_subscribes_per_attribute_with_node_and_path_filters(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
) -> None:
    """Each cluster attribute gets its own filtered ATTRIBUTE_UPDATED subscription."""
    await _setup(hass, mock_tcl_entry)
    attr_subs = {
        s.attr_path_filter
        for s in mock_matter_client.subscriptions
        if s.event_filter is EventType.ATTRIBUTE_UPDATED and s.node_filter == NODE_ID
    }
    expected = {f"1/{TCL_CLUSTER_FC03}/{a}" for a in range(NUM_TCL_FC03_DATA_ATTRS)}
    assert expected <= attr_subs
    assert "1/6/0" in attr_subs  # OnOff
    events = {s.event_filter for s in mock_matter_client.subscriptions}
    assert {EventType.NODE_UPDATED, EventType.NODE_ADDED, EventType.NODE_REMOVED} <= (
        events
    )


async def test_pushed_value_updates_the_entity(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
) -> None:
    """A real-shaped client callback, (event, value), reaches the entity state."""
    await _setup(hass, mock_tcl_entry)
    entity_id = _entity_id(hass, "binary_sensor", "tcl_matter_5_filter_alert")
    assert hass.states.get(entity_id).state == "off"

    sub = next(
        s
        for s in mock_matter_client.subscriptions
        if s.attr_path_filter == f"1/{TCL_CLUSTER_FC03}/{ATTR_FILTER_ALERT}"
    )
    pushed_value = True  # the client passes only (event, value)
    sub.callback(EventType.ATTRIBUTE_UPDATED, pushed_value)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "on"


# ---------------------------------------------------------------------------
# Reload triggers
# ---------------------------------------------------------------------------


def _callback_for(client: MagicMock, event: EventType) -> Any:
    return next(s.callback for s in client.subscriptions if s.event_filter is event)


async def test_new_tcl_node_schedules_reload(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
    non_tcl_matter_node: MagicMock,
) -> None:
    """A TCL node added later reloads the entry; others and known nodes do not."""
    await _setup(hass, mock_tcl_entry)
    added = _callback_for(mock_matter_client, EventType.NODE_ADDED)
    new_node = make_tcl_device(8).node
    known_node = make_tcl_device(NODE_ID).node

    with patch.object(hass.config_entries, "async_schedule_reload") as reload_mock:
        added(EventType.NODE_ADDED, non_tcl_matter_node)
        added(EventType.NODE_ADDED, known_node)
        reload_mock.assert_not_called()
        added(EventType.NODE_ADDED, new_node)
        reload_mock.assert_called_once_with(mock_tcl_entry.entry_id)


async def test_removed_tcl_node_schedules_reload(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
    mock_matter_client: MagicMock,
) -> None:
    """Removing a node we serve reloads the entry; an unknown node does not."""
    await _setup(hass, mock_tcl_entry)
    removed = _callback_for(mock_matter_client, EventType.NODE_REMOVED)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload_mock:
        removed(EventType.NODE_REMOVED, 99)
        reload_mock.assert_not_called()
        removed(EventType.NODE_REMOVED, NODE_ID)
        reload_mock.assert_called_once_with(mock_tcl_entry.entry_id)


async def test_matter_integration_leaving_loaded_state_schedules_reload(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """When matter reloads (new client), the TCL entry reloads to pick it up."""
    await _setup(hass, mock_tcl_entry)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload_mock:
        setup_matter_dependency.mock_state(hass, ConfigEntryState.NOT_LOADED)
        reload_mock.assert_called_once_with(mock_tcl_entry.entry_id)

        reload_mock.reset_mock()
        setup_matter_dependency.mock_state(hass, ConfigEntryState.LOADED)
        reload_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


async def test_device_uses_own_identifier_and_links_to_matter_device(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """The TCL device has its own identifier and is a child of the matter device."""
    registry = dr.async_get(hass)
    parent = registry.async_get_or_create(
        config_entry_id=setup_matter_dependency.entry_id,
        identifiers={MATTER_PARENT_IDENTIFIER},
    )
    await _setup(hass, mock_tcl_entry)

    device = registry.async_get_device_by_identifier(
        TCL_IDENTIFIER, mock_tcl_entry.entry_id
    )
    assert device is not None
    assert device.via_device_id == parent.id
    assert device.model_id == "32770"
    assert device.manufacturer == "TCL"


async def test_legacy_device_identifier_is_migrated_in_place(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """A 0.5.x device keeps its id (and area) but moves to the new identifier."""
    registry = dr.async_get(hass)
    legacy = registry.async_get_or_create(
        config_entry_id=mock_tcl_entry.entry_id,
        identifiers={LEGACY_IDENTIFIER},
        name="TCL Dehumidifier",
    )
    registry.async_update_device(legacy.id, area_id="attic")
    await _setup(hass, mock_tcl_entry)

    assert (
        registry.async_get_device_by_identifier(
            LEGACY_IDENTIFIER, mock_tcl_entry.entry_id
        )
        is None
    )
    migrated = registry.async_get_device_by_identifier(
        TCL_IDENTIFIER, mock_tcl_entry.entry_id
    )
    assert migrated is not None
    assert migrated.id == legacy.id
    assert migrated.area_id == "attic"


async def test_remove_device_only_when_not_served(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """A device for a node we serve can't be removed; a stray one can."""
    await _setup(hass, mock_tcl_entry)
    registry = dr.async_get(hass)
    active = registry.async_get_device_by_identifier(
        TCL_IDENTIFIER, mock_tcl_entry.entry_id
    )
    stray = registry.async_get_or_create(
        config_entry_id=mock_tcl_entry.entry_id,
        identifiers={(DOMAIN, "stray")},
    )
    assert await async_remove_config_entry_device(hass, mock_tcl_entry, active) is False
    assert await async_remove_config_entry_device(hass, mock_tcl_entry, stray) is True


def test_matter_identifier_matches_home_assistants_own_helper() -> None:
    """Our copy of the matter device identifier must agree with HA's helper."""
    helpers = pytest.importorskip("homeassistant.components.matter.helpers")
    server_info = MagicMock(compressed_fabric_id=FABRIC_ID)
    client = MagicMock(server_info=server_info)
    assert matter_device_identifier(client, NODE_ID) == (
        helpers.get_node_device_identifier(server_info, NODE_ID)
    )


def test_identifiers_without_a_fabric_id() -> None:
    """Without a fabric id there is no parent link and a bare-node own identifier."""
    client = MagicMock()  # server_info.compressed_fabric_id is a MagicMock
    assert matter_device_identifier(client, NODE_ID) is None
    assert tcl_device_identifier(client, NODE_ID) == (DOMAIN, str(NODE_ID))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_node_vendor_id_reads_device_info() -> None:
    """The vendor id comes from the node's BasicInformation."""
    node = MagicMock()
    node.device_info.vendorID = TCL_VENDOR_ID
    assert _node_vendor_id(node) == TCL_VENDOR_ID


@pytest.mark.parametrize("vendor", [None, "x", object()])
def test_node_vendor_id_unreadable_is_none(vendor: object) -> None:
    """Missing or non-numeric vendor ids give None."""
    node = MagicMock()
    node.device_info.vendorID = vendor
    assert _node_vendor_id(node) is None
    assert _node_vendor_id(object()) is None
