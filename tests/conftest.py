"""Shared pytest fixtures for the TCL Matter integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tcl_matter.const import (
    ATTR_BUCKET_FULL,
    ATTR_CURRENT_HUMIDITY,
    ATTR_ERROR_CODES,
    ATTR_LOCK_OR_FILTER,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    DOMAIN,
    MATTER_DOMAIN,
    TCL_CLUSTER_FC03,
    TCL_VENDOR_ID,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Default node id used across the suite.
DEFAULT_NODE_ID = 5


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,  # noqa: ARG001
) -> None:
    """Enable loading of the custom integration in every test."""
    return


@pytest.fixture
def default_node_attributes() -> dict[int, Any]:
    """Return a representative attribute snapshot for a TCL node."""
    return {
        ATTR_MODE: 0,  # Set
        ATTR_TARGET_HUMIDITY: 50,
        ATTR_CURRENT_HUMIDITY: 58,
        ATTR_BUCKET_FULL: False,
        ATTR_LOCK_OR_FILTER: False,
        ATTR_ERROR_CODES: "[]",
    }


@pytest.fixture
def mock_matter_node(default_node_attributes: dict[int, Any]) -> MagicMock:
    """Return a fake MatterNode pre-populated with TCL cluster data."""
    node = MagicMock(name="MatterNode")
    node.node_id = DEFAULT_NODE_ID
    node.vendor_id = TCL_VENDOR_ID
    # python-matter-server exposes node attributes keyed by "endpoint/cluster/attr"
    node.attributes = {
        f"1/{TCL_CLUSTER_FC03}/{attr_id}": value
        for attr_id, value in default_node_attributes.items()
    }
    # Also expose BasicInformation VendorID at the conventional 0/40/1 path so
    # the integration's vendor-id fallback works if direct access is bypassed.
    node.attributes["0/40/1"] = TCL_VENDOR_ID
    return node


@pytest.fixture
def non_tcl_matter_node() -> MagicMock:
    """Return a fake MatterNode from a non-TCL vendor (should be ignored)."""
    node = MagicMock(name="NonTclMatterNode")
    node.node_id = 99
    node.vendor_id = 0x1234
    node.attributes = {"0/40/1": 0x1234}
    return node


@pytest.fixture
def mock_matter_client(
    mock_matter_node: MagicMock,
    default_node_attributes: dict[int, Any],
) -> MagicMock:
    """Return a fake MatterClient with the methods our integration uses."""
    client = MagicMock(name="MatterClient")

    # get_nodes returns an iterable of node objects.
    client.get_nodes = MagicMock(return_value=[mock_matter_node])

    # read_attribute returns the flat-path response shape for cluster FC03.
    flat_response = {
        f"1/{TCL_CLUSTER_FC03}/{attr_id}": value
        for attr_id, value in default_node_attributes.items()
    }
    client.read_attribute = AsyncMock(return_value=flat_response)
    client.write_attribute = AsyncMock(return_value=None)

    # subscribe_events returns a no-op unsubscribe callable.
    unsub = MagicMock(name="UnsubscribeFn")
    client.subscribe_events = MagicMock(return_value=unsub)
    client.subscribe = MagicMock(return_value=unsub)

    return client


@pytest.fixture
def mock_matter_entry(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
) -> MockConfigEntry:
    """Install a mocked matter ConfigEntry exposing ``adapter.matter_client``."""
    entry = MockConfigEntry(
        domain=MATTER_DOMAIN,
        title="Matter",
        data={},
        entry_id="matter_mock_entry",
    )
    entry.add_to_hass(hass)
    # Mimic the modern HA matter integration: runtime_data.adapter.matter_client
    entry.runtime_data = SimpleNamespace(
        adapter=SimpleNamespace(matter_client=mock_matter_client),
    )
    return entry


@pytest.fixture
def mock_tcl_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return an unloaded TCL Matter ConfigEntry attached to ``hass``."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TCL Matter",
        data={},
        unique_id=DOMAIN,
        entry_id="tcl_matter_test_entry",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def setup_matter_dependency(mock_matter_entry: MockConfigEntry) -> MockConfigEntry:
    """Ensure the mocked matter ConfigEntry is registered before TCL setup."""
    return mock_matter_entry


@pytest.fixture
def make_tcl_device() -> Any:
    """Return a factory that builds a TclDevice with the given attributes."""

    def _factory(
        node_id: int = DEFAULT_NODE_ID,
        attributes: dict[int, Any] | None = None,
    ) -> Any:
        from custom_components.tcl_matter import TclDevice

        return TclDevice(
            node_id=node_id,
            node=MagicMock(name=f"Node{node_id}"),
            attributes=dict(attributes) if attributes else {},
        )

    return _factory


@pytest.fixture
def make_coordinator(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
) -> Any:
    """Return a factory that builds a TclMatterCoordinator with given devices."""

    def _factory(devices: dict[int, Any]) -> Any:
        from custom_components.tcl_matter.coordinator import TclMatterCoordinator

        coordinator = TclMatterCoordinator(
            hass=hass,
            matter_client=mock_matter_client,
            devices=devices,
        )
        return coordinator

    return _factory


@pytest.fixture
def primed_coordinator(
    make_coordinator: Any,
    make_tcl_device: Any,
    default_node_attributes: dict[int, Any],
) -> Any:
    """Return a coordinator pre-loaded with one device and snapshot data."""
    device = make_tcl_device(DEFAULT_NODE_ID, default_node_attributes)
    coordinator = make_coordinator({DEFAULT_NODE_ID: device})
    coordinator.data = {DEFAULT_NODE_ID: dict(default_node_attributes)}
    return coordinator


