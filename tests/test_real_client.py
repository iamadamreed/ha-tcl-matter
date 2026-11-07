"""Drive the integration through the real matter client.

The other tests use fakes for the client, so they share my assumptions about
it. These build a real ``MatterClient`` and real ``MatterNode`` objects and
feed them real ``EventMessage`` objects, so subscription keys, callback
signatures, decoding and cache updates are the client's own.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigFlow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from matter_server.client.client import MatterClient
from matter_server.client.models.node import MatterNode
from matter_server.common.models import (
    EventMessage,
    EventType,
    MatterNodeData,
    ServerInfoMessage,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_fire_time_changed,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.tcl_matter.const import DOMAIN, MATTER_DOMAIN, TCL_CLUSTER_FC03

from .conftest import FABRIC_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

C = TCL_CLUSTER_FC03
NODE = 5


def node_data(
    node_id: int = NODE,
    *,
    attrs: dict[str, Any] | None = None,
    available: bool = True,
    with_endpoint_0: bool = True,
    firmware: str = "1.0",
) -> MatterNodeData:
    """Build the data the matter server sends for a TCL node."""
    data: dict[str, Any] = {}
    if with_endpoint_0:
        data.update(
            {
                "0/40/1": "TCL",
                "0/40/2": 0x1334,
                "0/40/3": "T50DC9SPB",
                "0/40/4": 0x8002,
                "0/40/8": "1",
                "0/40/10": firmware,
            }
        )
    data.update(
        {
            "1/6/0": True,
            f"1/{C}/0": 0,
            f"1/{C}/1": 50,
            f"1/{C}/2": 58,
            f"1/{C}/3": False,
            f"1/{C}/4": False,
            f"1/{C}/5": "[]",
            f"1/{C}/6": "[1,3]",
        }
    )
    data.update(attrs or {})
    return MatterNodeData(
        node_id=node_id,
        date_commissioned=datetime.now(UTC),
        last_interview=datetime.now(UTC),
        interview_version=6,
        available=available,
        attributes=data,
    )


def real_client(nodes: list[MatterNode]) -> MatterClient:
    """Return a real MatterClient whose server round trips are faked."""
    client = MatterClient("ws://none", MagicMock())
    client._nodes = {n.node_id: n for n in nodes}
    client.connection.server_info = ServerInfoMessage(
        fabric_id=1,
        compressed_fabric_id=FABRIC_ID,
        schema_version=11,
        min_supported_schema_version=9,
        sdk_version="x",
        wifi_credentials_set=False,
        thread_credentials_set=False,
        bluetooth_enabled=False,
    )
    state = {
        n.node_id: {
            k: v for k, v in n.node_data.attributes.items() if k.startswith(f"1/{C}/")
        }
        for n in nodes
    }

    async def read(node_id: int, attribute_path: str) -> dict[str, Any]:
        if attribute_path.endswith("/*"):
            return dict(state[node_id])
        return {attribute_path: state[node_id][attribute_path]}

    async def write(node_id: int, attribute_path: str, value: Any) -> list[Any]:
        state[node_id][attribute_path] = value
        return [{"Path": {"EndpointId": 1}, "Status": 0}]

    client.read_attribute = AsyncMock(side_effect=read)
    client.write_attribute = AsyncMock(side_effect=write)
    client.send_command = AsyncMock(return_value=None)
    return client


def push(client: MatterClient, node_id: int, path: str, value: Any) -> None:
    """Deliver an ATTRIBUTE_UPDATED event the way the server does."""
    client._handle_event_message(
        EventMessage(event=EventType.ATTRIBUTE_UPDATED, data=[node_id, path, value])
    )


@pytest.fixture
def rc() -> MatterClient:
    """A real client with one TCL node."""
    return real_client([MatterNode(node_data())])


@pytest.fixture
def matter_entry(
    setup_matter_dependency: MockConfigEntry, rc: MatterClient
) -> MockConfigEntry:
    """The loaded matter entry, holding the real client."""
    setup_matter_dependency.runtime_data = SimpleNamespace(
        adapter=SimpleNamespace(matter_client=rc)
    )
    return setup_matter_dependency


def _entity(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_reads_values_the_client_decoded(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
) -> None:
    """The real client decodes the vendor cluster; no remote read is needed."""
    await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    humidifier = hass.states.get(
        _entity(hass, "humidifier", "tcl_matter_5_dehumidifier")
    )
    assert humidifier.attributes["humidity"] == 50
    assert humidifier.attributes["current_humidity"] == 58
    rc.read_attribute.assert_not_called()


async def test_push_through_the_clients_own_dispatch(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
) -> None:
    """Pushes, an OnOff change and a node going offline all reach the entities."""
    await _setup(hass, mock_tcl_entry)
    alert = _entity(hass, "switch", "tcl_matter_5_pump")
    humidifier = _entity(hass, "humidifier", "tcl_matter_5_dehumidifier")
    assert hass.states.get(alert).state == "off"

    alert_on = True
    push(rc, NODE, f"1/{C}/4", alert_on)
    await hass.async_block_till_done()
    assert hass.states.get(alert).state == "on"

    push(rc, NODE, f"1/{C}/1", 62)
    await hass.async_block_till_done()
    assert hass.states.get(humidifier).attributes["humidity"] == 62

    powered = False
    push(rc, NODE, "1/6/0", powered)  # the client updates its cache first
    await hass.async_block_till_done()
    assert hass.states.get(humidifier).state == "off"

    rc._handle_event_message(
        EventMessage(
            event=EventType.NODE_UPDATED,
            data=asdict(node_data(available=False)),
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get(alert).state == "unavailable"


async def test_unload_leaves_no_subscriber_on_the_client(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
) -> None:
    """Every subscription made at setup is released at unload."""
    await _setup(hass, mock_tcl_entry)
    assert any(rc._subscribers.values())
    assert await hass.config_entries.async_unload(mock_tcl_entry.entry_id)
    await hass.async_block_till_done()
    assert {k: v for k, v in rc._subscribers.items() if v} == {}


async def test_node_without_endpoint_0_cannot_break_the_client_or_setup(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
) -> None:
    """A node whose interview failed is ignored, in setup and when it is added."""
    broken = MatterNode(
        MatterNodeData(
            node_id=9,
            date_commissioned=datetime.now(UTC),
            last_interview=datetime.now(UTC),
            interview_version=0,
            attributes={},
        )
    )
    rc._nodes[9] = broken
    await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    assert list(mock_tcl_entry.runtime_data.devices) == [NODE]

    with patch.object(hass.config_entries, "async_schedule_reload") as reload_mock:
        rc._handle_event_message(
            EventMessage(
                event=EventType.NODE_ADDED,
                data=asdict(node_data(node_id=10, with_endpoint_0=False)),
            )
        )
        reload_mock.assert_not_called()


async def test_an_error_in_a_callback_is_logged_not_raised(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing handler must not propagate into the client's dispatch loop."""
    await _setup(hass, mock_tcl_entry)
    coordinator = mock_tcl_entry.runtime_data.coordinator
    with (
        patch.object(coordinator, "_store", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.ERROR, logger="custom_components.tcl_matter"),
    ):
        push(rc, NODE, f"1/{C}/1", 70)  # must not raise
    assert any("Error handling a matter event" in r.message for r in caplog.records)


async def test_pushes_do_not_starve_the_poll(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
    freezer: Any,
) -> None:
    """The 60 s poll still runs while a node keeps pushing."""
    await _setup(hass, mock_tcl_entry)
    coordinator = mock_tcl_entry.runtime_data.coordinator
    with patch.object(coordinator, "_poll_node", wraps=coordinator._poll_node) as poll:
        for i in range(10):  # a push every 40 s for 400 s
            freezer.tick(timedelta(seconds=40))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
            push(rc, NODE, f"1/{C}/2", 50 + i)
            await hass.async_block_till_done()
    # Ticks are 40 s apart, so a 60 s timer fires about every 80 s. With the old
    # behaviour (every push restarts the timer) this was zero.
    assert poll.call_count >= 3


async def test_node_update_syncs_firmware_to_the_device(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
    rc: MatterClient,
) -> None:
    """A firmware change reaches the device registry, not just the first add."""
    await _setup(hass, mock_tcl_entry)
    registry = dr.async_get(hass)
    identifier = (DOMAIN, f"{FABRIC_ID:016X}-{NODE:016X}")
    device = registry.async_get_device_by_identifier(
        identifier, mock_tcl_entry.entry_id
    )
    assert device.sw_version == "1.0"

    rc._handle_event_message(
        EventMessage(
            event=EventType.NODE_UPDATED, data=asdict(node_data(firmware="2.0"))
        )
    )
    await hass.async_block_till_done()
    device = registry.async_get_device_by_identifier(
        identifier, mock_tcl_entry.entry_id
    )
    assert device.sw_version == "2.0"


class _Flow(ConfigFlow):
    VERSION = 1


async def test_matter_reload_hands_the_entry_to_the_new_client(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Reloading the matter integration replaces its client; TCL must follow."""
    clients: list[MatterClient] = []

    async def setup_entry(_hass: HomeAssistant, entry: MockConfigEntry) -> bool:
        client = real_client([MatterNode(node_data())])
        clients.append(client)
        entry.runtime_data = SimpleNamespace(
            adapter=SimpleNamespace(matter_client=client)
        )
        return True

    async def unload_entry(_hass: HomeAssistant, _entry: MockConfigEntry) -> bool:
        return True

    mock_integration(
        hass,
        MockModule(
            MATTER_DOMAIN,
            async_setup_entry=setup_entry,
            async_unload_entry=unload_entry,
        ),
    )
    mock_platform(hass, f"{MATTER_DOMAIN}.config_flow", None)
    matter = MockConfigEntry(domain=MATTER_DOMAIN, entry_id="matter_real")
    matter.add_to_hass(hass)
    with mock_config_flow(MATTER_DOMAIN, _Flow):
        assert await hass.config_entries.async_setup(matter.entry_id)
        await hass.async_block_till_done()
        await _setup(hass, mock_tcl_entry)
        assert mock_tcl_entry.state is ConfigEntryState.LOADED
        assert mock_tcl_entry.runtime_data.coordinator.matter_client is clients[0]

        assert await hass.config_entries.async_reload(matter.entry_id)
        await hass.async_block_till_done()
        for _ in range(6):  # setup retries with a back-off
            freezer.tick(timedelta(seconds=30))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    assert mock_tcl_entry.runtime_data.coordinator.matter_client is clients[1]
    assert {k: v for k, v in clients[0]._subscribers.items() if v} == {}


async def test_migration_survives_both_identifiers_existing(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
) -> None:
    """Old and new device both present (rollback then upgrade) does not break setup."""
    registry = dr.async_get(hass)
    old = registry.async_get_or_create(
        config_entry_id=mock_tcl_entry.entry_id,
        identifiers={(MATTER_DOMAIN, str(NODE))},
    )
    registry.async_update_device(old.id, area_id="attic")
    registry.async_get_or_create(
        config_entry_id=mock_tcl_entry.entry_id,
        identifiers={(DOMAIN, f"{FABRIC_ID:016X}-{NODE:016X}")},
    )
    await _setup(hass, mock_tcl_entry)
    assert mock_tcl_entry.state is ConfigEntryState.LOADED
    kept = registry.async_get_device_by_identifier(
        (DOMAIN, f"{FABRIC_ID:016X}-{NODE:016X}"), mock_tcl_entry.entry_id
    )
    assert kept.id == old.id
    assert kept.area_id == "attic"


async def test_real_node_offers_only_the_modes_its_product_has(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
) -> None:
    """The product ID comes from the real node's BasicInformation (0x8002)."""
    await _setup(hass, mock_tcl_entry)
    humidifier = hass.states.get(
        _entity(hass, "humidifier", "tcl_matter_5_dehumidifier")
    )
    mode_select = hass.states.get(_entity(hass, "select", "tcl_matter_5_mode"))
    assert humidifier.attributes["available_modes"] == ["set", "comfort"]
    assert mode_select.attributes["options"] == ["set", "comfort"]


async def test_no_pump_switch_on_a_model_without_a_pump(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """A unit whose feature set is [3] (no pump) gets no pump switch."""
    node = MatterNode(node_data(attrs={f"1/{C}/6": "[3]"}))
    setup_matter_dependency.runtime_data = SimpleNamespace(
        adapter=SimpleNamespace(matter_client=real_client([node]))
    )
    await _setup(hass, mock_tcl_entry)
    assert (
        er.async_get(hass).async_get_entity_id("switch", DOMAIN, "tcl_matter_5_pump")
        is None
    )


async def test_old_filter_entities_are_removed_on_upgrade(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    matter_entry: MockConfigEntry,
) -> None:
    """The filter sensor and reset button of 0.6.x are cleaned out of the registry."""
    registry = er.async_get(hass)
    for platform, suffix in (
        ("binary_sensor", "filter_alert"),
        ("button", "reset_filter"),
    ):
        registry.async_get_or_create(
            platform, DOMAIN, f"tcl_matter_5_{suffix}", config_entry=mock_tcl_entry
        )
    await _setup(hass, mock_tcl_entry)
    for platform, suffix in (
        ("binary_sensor", "filter_alert"),
        ("button", "reset_filter"),
    ):
        assert (
            registry.async_get_entity_id(platform, DOMAIN, f"tcl_matter_5_{suffix}")
            is None
        )
