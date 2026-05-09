"""Tests for ``custom_components.tcl_matter.coordinator``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tcl_matter.coordinator import (
    TclMatterCoordinator,
    _walk_to_attr_dict,
)
from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    TCL_CLUSTER_FC03,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def test_normalize_read_result_flat_paths() -> None:
    """Flat ``"endpoint/cluster/attr"`` keys yield an attr-id keyed dict."""
    result = {
        f"1/{TCL_CLUSTER_FC03}/0": 0,
        f"1/{TCL_CLUSTER_FC03}/1": 50,
        f"1/{TCL_CLUSTER_FC03}/2": 58,
    }
    out = TclMatterCoordinator._normalize_read_result(result)
    assert out == {0: 0, 1: 50, 2: 58}


def test_normalize_read_result_nested() -> None:
    """Nested {node:{endpoint:{cluster:{attr:v}}}} also flattens correctly."""
    nested: dict[Any, Any] = {
        5: {
            1: {
                TCL_CLUSTER_FC03: {0: 0, 1: 50, 2: 58},
            },
        },
    }
    out = TclMatterCoordinator._normalize_read_result(nested)
    assert out == {0: 0, 1: 50, 2: 58}


def test_normalize_read_result_non_dict_input() -> None:
    """Non-dict inputs return an empty dict rather than raising."""
    assert TclMatterCoordinator._normalize_read_result(None) == {}
    assert TclMatterCoordinator._normalize_read_result([1, 2]) == {}


def test_normalize_read_result_skips_unparseable_attr() -> None:
    """Path components that aren't ints are silently dropped."""
    result = {f"1/{TCL_CLUSTER_FC03}/abc": 99, f"1/{TCL_CLUSTER_FC03}/2": 58}
    out = TclMatterCoordinator._normalize_read_result(result)
    assert out == {2: 58}


def test_walk_to_attr_dict_returns_leaves() -> None:
    """Helper returns every leaf-level dict in a nested structure."""
    nested = {"a": {"b": {"c": 1, "d": 2}}, "e": {"f": 3}}
    leaves = _walk_to_attr_dict(nested)
    assert {"c": 1, "d": 2} in leaves
    assert {"f": 3} in leaves


async def test_async_update_data_polls_each_node(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """``_async_update_data`` calls read_attribute once per device."""
    devices = {
        5: make_tcl_device(5),
        6: make_tcl_device(6),
    }
    mock_matter_client.read_attribute = AsyncMock(
        return_value={f"1/{TCL_CLUSTER_FC03}/0": 0, f"1/{TCL_CLUSTER_FC03}/1": 50},
    )
    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices=devices,
    )

    snapshot = await coordinator._async_update_data()
    assert mock_matter_client.read_attribute.await_count == 2
    assert snapshot[5] == {0: 0, 1: 50}
    assert snapshot[6] == {0: 0, 1: 50}
    # Per-device cache populated
    assert devices[5].attributes == {0: 0, 1: 50}


async def test_async_update_data_falls_back_to_positional_call(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If kw-args raise TypeError, the coordinator retries with positional args."""
    devices = {5: make_tcl_device(5)}
    flat = {f"1/{TCL_CLUSTER_FC03}/1": 50}

    async def _read(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs:
            raise TypeError("kwargs not supported")
        return flat

    mock_matter_client.read_attribute = AsyncMock(side_effect=_read)
    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices=devices,
    )

    snapshot = await coordinator._async_update_data()
    assert snapshot[5] == {1: 50}


async def test_async_update_data_preserves_cache_on_failure(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """A failing poll on a device with cached data is logged but not raised."""
    cached = {ATTR_MODE: 0, ATTR_TARGET_HUMIDITY: 50}
    devices = {5: make_tcl_device(5, cached)}
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("net"))
    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices=devices,
    )

    snapshot = await coordinator._async_update_data()
    assert snapshot[5] == cached


async def test_async_update_data_raises_when_no_cache(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If a device has no cache and the read fails, surface UpdateFailed."""
    devices = {5: make_tcl_device(5)}
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("net"))
    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices=devices,
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_async_update_data_missing_read_attribute_raises(
    hass: HomeAssistant,
    make_tcl_device: Any,
) -> None:
    """A matter client without read_attribute is treated as a poll failure."""
    devices = {5: make_tcl_device(5)}
    client = MagicMock(spec=[])
    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=client,
        devices=devices,
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_handle_push_event_updates_one_attribute(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A well-formed push event updates one attribute and broadcasts new data."""
    listener = MagicMock()
    primed_coordinator.async_add_listener(listener)

    primed_coordinator.handle_push_event(
        event="attribute_updated",
        data={
            "node_id": 5,
            "attribute_path": f"1/{TCL_CLUSTER_FC03}/{ATTR_CURRENT_HUMIDITY}",
            "value": 42,
        },
    )

    assert primed_coordinator.data[5][ATTR_CURRENT_HUMIDITY] == 42
    listener.assert_called()


async def test_handle_push_event_ignores_other_clusters(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Cluster IDs outside FC03 are ignored without changing data."""
    before = dict(primed_coordinator.data[5])
    primed_coordinator.handle_push_event(
        event="attribute_updated",
        data={"node_id": 5, "attribute_path": "1/6/0", "value": True},
    )
    assert primed_coordinator.data[5] == before


async def test_handle_push_event_ignores_unknown_node(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """A push for a node that isn't ours is ignored."""
    before = dict(primed_coordinator.data)
    primed_coordinator.handle_push_event(
        event="attribute_updated",
        data={
            "node_id": 999,
            "attribute_path": f"1/{TCL_CLUSTER_FC03}/0",
            "value": 1,
        },
    )
    assert primed_coordinator.data == before


async def test_handle_push_event_rejects_non_dict_payload(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Non-dict payloads silently no-op."""
    primed_coordinator.handle_push_event(event="x", data="not a dict")
    primed_coordinator.handle_push_event(event="x", data=None)


async def test_handle_push_event_rejects_malformed_path(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Malformed path strings are dropped silently."""
    before = dict(primed_coordinator.data[5])
    primed_coordinator.handle_push_event(
        event="x",
        data={"node_id": 5, "attribute_path": "not/a/full/path", "value": 1},
    )
    assert primed_coordinator.data[5] == before


async def test_handle_push_event_with_camelcase_keys(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """Both ``node_id``/``attribute_path`` and ``nodeId``/``path`` are accepted."""
    primed_coordinator.handle_push_event(
        event="x",
        data={
            "nodeId": 5,
            "path": f"1/{TCL_CLUSTER_FC03}/{ATTR_TARGET_HUMIDITY}",
            "value": 60,
        },
    )
    assert primed_coordinator.data[5][ATTR_TARGET_HUMIDITY] == 60


async def test_handle_push_event_uses_event_when_data_none(
    primed_coordinator: TclMatterCoordinator,
) -> None:
    """If ``data`` is None, the event itself is treated as the payload."""
    primed_coordinator.handle_push_event(
        event={
            "node_id": 5,
            "attribute_path": f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}",
            "value": 3,
        },
        data=None,
    )
    assert primed_coordinator.data[5][ATTR_MODE] == 3
