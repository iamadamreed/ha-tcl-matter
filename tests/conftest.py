"""Shared pytest fixtures for the TCL Matter integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

from custom_components.tcl_matter import TclDevice
from custom_components.tcl_matter.const import (
    ATTR_BUCKET_FULL,
    ATTR_CURRENT_HUMIDITY,
    ATTR_ERROR_CODES,
    ATTR_FEATURE_SET,
    ATTR_MODE,
    ATTR_PUMP,
    ATTR_TARGET_HUMIDITY,
    DOMAIN,
    MATTER_DOMAIN,
    TCL_CLUSTER_FC03,
    TCL_VENDOR_ID,
)
from custom_components.tcl_matter.coordinator import TclMatterCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# Default node id used across the suite.
DEFAULT_NODE_ID = 5

# Compressed fabric id the fake matter server reports.
FABRIC_ID = 0x55A6683D17125EED


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
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
        ATTR_PUMP: False,
        ATTR_FEATURE_SET: "[1,3]",
        ATTR_ERROR_CODES: "[]",
    }


def _make_device_info(
    *,
    vendor_id: int = TCL_VENDOR_ID,
    product_id: int = 0x8002,
    product_name: str = "TCL Dehumidifier",
    vendor_name: str = "TCL",
    hardware_version_string: str = "1.0",
    software_version_string: str = "1.0.0",
) -> SimpleNamespace:
    """Build a BasicInformation-shaped device_info object.

    Mirrors python-matter-server 5.x ``MatterNode.device_info`` (a dataclass
    that exposes ``vendorID``, ``productID``, ``vendorName``, ``productName``,
    ``hardwareVersionString``, ``softwareVersionString``).
    """
    return SimpleNamespace(
        vendorID=vendor_id,
        productID=product_id,
        vendorName=vendor_name,
        productName=product_name,
        hardwareVersionString=hardware_version_string,
        softwareVersionString=software_version_string,
    )


def strip_decoded_values(node: Any) -> None:
    """Make a fake node look like a client that has no decoder for the cluster.

    ``get_attribute_value`` then returns None for every vendor attribute, so
    the coordinator has to fall back to a live read.
    """
    prefix = f"1/{TCL_CLUSTER_FC03}/"
    node.node_data.attributes = {
        k: v for k, v in node.node_data.attributes.items() if not k.startswith(prefix)
    }


def _make_node_data(attributes: dict[str, Any]) -> SimpleNamespace:
    """Build a ``node_data`` namespace whose ``.attributes`` is a path-keyed dict."""
    return SimpleNamespace(attributes=dict(attributes))


@pytest.fixture
def mock_matter_node(default_node_attributes: dict[int, Any]) -> MagicMock:
    """Return a fake MatterNode pre-populated with TCL cluster data.

    Provides the modern ``device_info`` dataclass, ``node_data.attributes``
    path-string dict, and ``get_attribute_value(endpoint, cluster, attr)``
    method that the current integration uses.
    """
    node = MagicMock(name="MatterNode")
    node.node_id = DEFAULT_NODE_ID
    node.available = True
    # Modern path-string node_data dict (the only path the coordinator reads now).
    node_attrs: dict[str, Any] = {
        f"1/{TCL_CLUSTER_FC03}/{attr_id}": value
        for attr_id, value in default_node_attributes.items()
    }
    # Cluster metadata attributes the coordinator must skip.
    node_attrs[f"1/{TCL_CLUSTER_FC03}/65528"] = []
    node_attrs[f"1/{TCL_CLUSTER_FC03}/65532"] = 0
    # BasicInformation cluster is also present at endpoint 0.
    node_attrs["0/40/1"] = TCL_VENDOR_ID
    node.node_data = _make_node_data(node_attrs)

    # python-matter-server 5.x BasicInformation dataclass.
    node.device_info = _make_device_info()

    # get_attribute_value(endpoint, cluster, attr) — returns from node_data.attributes.
    def _get_attr(endpoint: int, cluster: int, attr: int) -> Any:
        return node.node_data.attributes.get(f"{endpoint}/{cluster}/{attr}")

    node.get_attribute_value = MagicMock(side_effect=_get_attr)

    return node


@pytest.fixture
def non_tcl_matter_node() -> MagicMock:
    """Return a fake MatterNode from a non-TCL vendor (should be ignored)."""
    node = MagicMock(name="NonTclMatterNode")
    node.node_id = 99
    node.device_info = _make_device_info(
        vendor_id=0x1234,
        product_id=0x0001,
        product_name="OtherDevice",
        vendor_name="OtherCo",
    )
    node.node_data = _make_node_data({"0/40/1": 0x1234})
    node.available = True
    node.get_attribute_value = MagicMock(
        side_effect=lambda e, c, a: node.node_data.attributes.get(f"{e}/{c}/{a}")
    )
    return node


@pytest.fixture
def mock_matter_client(
    mock_matter_node: MagicMock,
    default_node_attributes: dict[int, Any],
) -> MagicMock:
    """
    Return a fake MatterClient with the methods our integration uses.

    ``read_attribute`` returns a flat path-keyed dict for cluster FC03.
    ``write_attribute`` mutates the same backing dict so a subsequent read
    sees the new value — mimicking the matter-server's behaviour where a
    push subscription would deliver the updated value back.
    """
    client = MagicMock(name="MatterClient")

    # get_nodes returns an iterable of node objects.
    client.get_nodes = MagicMock(return_value=[mock_matter_node])

    flat_response = {
        f"1/{TCL_CLUSTER_FC03}/{attr_id}": value
        for attr_id, value in default_node_attributes.items()
    }

    async def _read_attribute(*, node_id: int, attribute_path: str) -> Any:
        return dict(flat_response)

    async def _write_attribute(
        *, node_id: int, attribute_path: str, value: Any
    ) -> None:
        flat_response[attribute_path] = value

    client.read_attribute = AsyncMock(side_effect=_read_attribute)
    client.write_attribute = AsyncMock(side_effect=_write_attribute)

    client.server_info = SimpleNamespace(compressed_fabric_id=FABRIC_ID)

    # subscribe_events records every subscription so tests can fire events and
    # check that each one is released.
    client.subscriptions = []

    def _subscribe_events(
        callback: Any,
        event_filter: Any = None,
        node_filter: int | None = None,
        attr_path_filter: str | None = None,
    ) -> Any:
        record = SimpleNamespace(
            callback=callback,
            event_filter=event_filter,
            node_filter=node_filter,
            attr_path_filter=attr_path_filter,
            active=True,
        )

        def _unsubscribe() -> None:
            record.active = False

        client.subscriptions.append(record)
        return _unsubscribe

    client.subscribe_events = MagicMock(side_effect=_subscribe_events)

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
    # Mimic the HA matter integration: runtime_data.adapter.matter_client
    entry.runtime_data = SimpleNamespace(
        adapter=SimpleNamespace(matter_client=mock_matter_client),
    )
    entry.mock_state(hass, ConfigEntryState.LOADED)
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
def setup_matter_dependency(
    hass: HomeAssistant, mock_matter_entry: MockConfigEntry
) -> MockConfigEntry:
    """Register the mocked matter entry and a stub matter integration.

    The stub keeps HA from setting up the real matter integration (which would
    try to reach a server) when the TCL entry's dependency is resolved.
    """
    mock_integration(hass, MockModule(MATTER_DOMAIN))
    return mock_matter_entry


@pytest.fixture
def make_tcl_device() -> Any:
    """Return a factory that builds a TclDevice with the given attributes.

    The underlying mock node carries a ``node_data.attributes`` dict whose
    keys mirror the live attributes (``"1/{TCL_CLUSTER_FC03}/{attr}"``), a
    ``device_info`` dataclass, and a working ``get_attribute_value`` method
    so the coordinator's primary read path succeeds.
    """

    def _factory(
        node_id: int = DEFAULT_NODE_ID,
        attributes: dict[int, Any] | None = None,
    ) -> Any:
        attributes = dict(attributes) if attributes else {}
        node_attrs: dict[str, Any] = {
            f"1/{TCL_CLUSTER_FC03}/{attr_id}": value
            for attr_id, value in attributes.items()
        }
        node_attrs["0/40/1"] = TCL_VENDOR_ID
        node = MagicMock(name=f"Node{node_id}")
        node.node_id = node_id
        node.node_data = _make_node_data(node_attrs)
        node.device_info = _make_device_info()
        node.available = True
        node.get_attribute_value = MagicMock(
            side_effect=lambda e, c, a: node.node_data.attributes.get(f"{e}/{c}/{a}")
        )

        return TclDevice(node_id=node_id, node=node)

    return _factory


@pytest.fixture
def make_coordinator(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
) -> Any:
    """Return a factory that builds a TclMatterCoordinator with given devices."""

    def _factory(devices: dict[int, Any]) -> Any:
        return TclMatterCoordinator(
            hass=hass,
            config_entry=None,
            matter_client=mock_matter_client,
            devices=devices,
        )

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
