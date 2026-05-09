"""Tests for ``custom_components.tcl_matter.__init__``."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.tcl_matter import (
    TclMatterRuntimeData,
    _discover_tcl_nodes,
    _get_matter_client,
    _node_vendor_id,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.tcl_matter.const import (
    DOMAIN,
    MATTER_DOMAIN,
    TCL_VENDOR_ID,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def patch_platform_forwarding() -> Generator[None, None, None]:
    """Patch hass platform forward / unload helpers so we can drive setup directly.

    The TCL Matter platforms exercise their own behavior in dedicated test
    modules; here we only care about the ``__init__`` lifecycle, so the
    platform fan-out is short-circuited.
    """
    with (
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new=AsyncMock(return_value=True),
        ),
    ):
        yield


async def test_setup_entry_happy_path(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """One TCL node loads successfully and runtime_data is populated."""
    assert await async_setup_entry(hass, mock_tcl_entry) is True

    runtime: TclMatterRuntimeData = mock_tcl_entry.runtime_data
    assert isinstance(runtime, TclMatterRuntimeData)
    assert runtime.matter_client is mock_matter_client
    assert list(runtime.devices.keys()) == [5]


async def test_setup_entry_matter_not_loaded(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
) -> None:
    """If the matter integration isn't loaded, raise ConfigEntryNotReady."""
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, mock_tcl_entry)


async def test_setup_entry_no_tcl_nodes_logs_warning(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """No TCL devices on fabric still results in a successful (empty) setup."""
    mock_matter_client.get_nodes.return_value = []

    with caplog.at_level(logging.WARNING, logger="custom_components.tcl_matter"):
        result = await async_setup_entry(hass, mock_tcl_entry)

    assert result is True
    assert mock_tcl_entry.runtime_data.devices == {}
    assert any("No TCL Matter devices" in rec.message for rec in caplog.records)


async def test_setup_entry_ignores_non_tcl_nodes(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    mock_matter_node: MagicMock,
    non_tcl_matter_node: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """Nodes from other vendors are filtered out."""
    mock_matter_client.get_nodes.return_value = [mock_matter_node, non_tcl_matter_node]

    assert await async_setup_entry(hass, mock_tcl_entry) is True
    assert list(mock_tcl_entry.runtime_data.devices) == [mock_matter_node.node_id]


async def test_unload_entry_clears_subscriptions(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """Unloading invokes every subscription teardown function exactly once."""
    unsub = MagicMock()
    mock_matter_client.subscribe_events.return_value = unsub

    assert await async_setup_entry(hass, mock_tcl_entry) is True

    runtime: TclMatterRuntimeData = mock_tcl_entry.runtime_data
    assert unsub in runtime.unsubscribers

    assert await async_unload_entry(hass, mock_tcl_entry) is True
    unsub.assert_called_once_with()
    assert runtime.unsubscribers == []


async def test_unload_entry_tolerates_unsub_errors(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """A raising unsubscriber should not break unload."""
    bad_unsub = MagicMock(side_effect=RuntimeError("boom"))
    mock_matter_client.subscribe_events.return_value = bad_unsub

    assert await async_setup_entry(hass, mock_tcl_entry) is True
    assert await async_unload_entry(hass, mock_tcl_entry) is True


def test_get_matter_client_runtime_data(hass: HomeAssistant) -> None:
    """``_get_matter_client`` returns the modern ``runtime_data.adapter`` client."""
    client = MagicMock()
    entry = SimpleNamespace(
        entry_id="x",
        runtime_data=SimpleNamespace(adapter=SimpleNamespace(matter_client=client)),
    )
    hass.config_entries.async_entries = MagicMock(return_value=[entry])  # type: ignore[method-assign]
    assert _get_matter_client(hass) is client


def test_get_matter_client_legacy_data(hass: HomeAssistant) -> None:
    """Legacy ``hass.data["matter"][entry_id]`` path is still supported."""
    client = MagicMock()
    entry = SimpleNamespace(entry_id="legacy", runtime_data=None)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])  # type: ignore[method-assign]
    hass.data[MATTER_DOMAIN] = {
        "legacy": SimpleNamespace(adapter=SimpleNamespace(matter_client=client)),
    }
    assert _get_matter_client(hass) is client


def test_get_matter_client_not_loaded(hass: HomeAssistant) -> None:
    """Returns None when no matter entries exist."""
    hass.config_entries.async_entries = MagicMock(return_value=[])  # type: ignore[method-assign]
    assert _get_matter_client(hass) is None


def test_node_vendor_id_direct_attribute() -> None:
    """The fast path reads ``node.vendor_id`` directly."""
    node = SimpleNamespace(vendor_id=TCL_VENDOR_ID, attributes={})
    assert _node_vendor_id(node) == TCL_VENDOR_ID


def test_node_vendor_id_via_basic_information() -> None:
    """Falls back to BasicInformation cluster path 0/40/1."""
    node = SimpleNamespace(vendor_id=None, attributes={"0/40/1": TCL_VENDOR_ID})
    assert _node_vendor_id(node) == TCL_VENDOR_ID


def test_node_vendor_id_unknown_returns_none() -> None:
    """Returns None when vendor cannot be determined."""
    node = SimpleNamespace(vendor_id=None, attributes={})
    assert _node_vendor_id(node) is None


def test_discover_tcl_nodes_filters_by_vendor(
    mock_matter_client: MagicMock,
    mock_matter_node: MagicMock,
    non_tcl_matter_node: MagicMock,
) -> None:
    """Only TCL-vendor nodes are returned."""
    mock_matter_client.get_nodes.return_value = [mock_matter_node, non_tcl_matter_node]
    nodes = _discover_tcl_nodes(mock_matter_client)
    assert nodes == [mock_matter_node]


def test_discover_tcl_nodes_falls_back_to_nodes_dict(
    mock_matter_node: MagicMock,
) -> None:
    """If ``get_nodes`` is missing, fall back to the ``nodes`` dict property."""
    client = MagicMock(spec=["nodes"])
    client.nodes = {mock_matter_node.node_id: mock_matter_node}
    nodes = _discover_tcl_nodes(client)
    assert nodes == [mock_matter_node]


async def test_setup_entry_propagates_first_refresh_failure(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
) -> None:
    """A failing initial poll surfaces as ConfigEntryNotReady."""
    mock_matter_client.read_attribute.side_effect = RuntimeError("transport down")

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, mock_tcl_entry)


async def test_setup_entry_falls_back_to_subscribe_when_subscribe_events_missing(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """If ``subscribe_events`` is unavailable, ``subscribe`` is used instead."""
    del mock_matter_client.subscribe_events
    unsub = MagicMock()
    mock_matter_client.subscribe = MagicMock(return_value=unsub)

    assert await async_setup_entry(hass, mock_tcl_entry) is True
    runtime: TclMatterRuntimeData = mock_tcl_entry.runtime_data
    assert unsub in runtime.unsubscribers


async def test_setup_entry_handles_no_subscription_api(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
    mock_matter_client: MagicMock,
    patch_platform_forwarding: object,  # noqa: ARG001
) -> None:
    """Setup still succeeds when neither subscribe* method exists."""
    del mock_matter_client.subscribe_events
    del mock_matter_client.subscribe

    assert await async_setup_entry(hass, mock_tcl_entry) is True
    assert mock_tcl_entry.runtime_data.unsubscribers == []


async def test_setup_entry_forwards_to_platforms(
    hass: HomeAssistant,
    mock_tcl_entry: MockConfigEntry,
    setup_matter_dependency: MockConfigEntry,  # noqa: ARG001
) -> None:
    """async_forward_entry_setups is called once with all our platforms."""
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        new=AsyncMock(return_value=True),
    ) as forward:
        assert await async_setup_entry(hass, mock_tcl_entry) is True

    forward.assert_awaited_once()
    # When patching a bound method via the class, the call args include self.
    args = forward.await_args.args
    platforms = args[-1]
    assert "humidifier" in {str(p) for p in platforms}


async def test_domain_constant() -> None:
    """Sanity: the domain constant matches manifest."""
    assert DOMAIN == "tcl_matter"
