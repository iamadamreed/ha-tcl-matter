"""Tests for ``custom_components.tcl_matter.coordinator``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.coordinator import (
    TclMatterCoordinator,
    _walk_to_attr_dict,
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
    """``_async_update_data`` reads cluster attributes for every device."""
    device_a = make_tcl_device(5, {0: 0, 1: 50})
    device_b = make_tcl_device(6, {0: 0, 1: 50})
    devices = {5: device_a, 6: device_b}

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices=devices,
    )

    snapshot = await coordinator._async_update_data()
    assert snapshot[5] == {0: 0, 1: 50}
    assert snapshot[6] == {0: 0, 1: 50}
    # Per-device cache populated.
    assert devices[5].attributes == {0: 0, 1: 50}


async def test_read_cluster_uses_node_data_attributes_dict(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """``_read_cluster`` walks node_data.attributes and only keeps attrs 0..6.

    Cluster metadata attributes (65528, 65532) must be skipped, and
    ``get_attribute_value`` must NOT be invoked when node_data already
    yields data.
    """
    device = make_tcl_device(5, {0: 0, 1: 50, 2: 58, 3: False})
    # Inject metadata attributes that should be skipped.
    device.node.node_data.attributes[f"1/{TCL_CLUSTER_FC03}/65528"] = []
    device.node.node_data.attributes[f"1/{TCL_CLUSTER_FC03}/65532"] = 0
    # And an out-of-range attribute that should also be skipped.
    device.node.node_data.attributes[f"1/{TCL_CLUSTER_FC03}/7"] = "ignored"

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices={5: device},
    )

    out = await coordinator._read_cluster(5)
    assert out == {0: 0, 1: 50, 2: 58, 3: False}
    # Primary path must not require the get_attribute_value fallback.
    device.node.get_attribute_value.assert_not_called()


async def test_read_cluster_falls_back_to_get_attribute_value_when_node_data_empty(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If node_data.attributes is empty, fall back to ``get_attribute_value``."""
    device = make_tcl_device(5)
    # Wipe node_data so the primary path returns nothing.
    device.node.node_data.attributes = {}

    # Configure get_attribute_value to return a value only for attrs 0 and 2.
    def _get_attr(endpoint: int, cluster: int, attr: int) -> Any:
        if endpoint == 1 and cluster == TCL_CLUSTER_FC03 and attr in (0, 2):
            return {0: 1, 2: 60}[attr]
        return None

    device.node.get_attribute_value = MagicMock(side_effect=_get_attr)

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices={5: device},
    )

    out = await coordinator._read_cluster(5)
    assert out == {0: 1, 2: 60}
    # Fallback should have walked all 7 attribute IDs (0..6).
    assert device.node.get_attribute_value.call_count == 7


async def test_async_update_data_preserves_cache_on_failure(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """A failing poll on a device with cached data is logged but not raised."""
    cached = {ATTR_MODE: 0, ATTR_TARGET_HUMIDITY: 50}
    device = make_tcl_device(5, cached)
    # Force the read path to fail: empty node_data + raising get_attribute_value.
    device.node.node_data.attributes = {}
    device.node.get_attribute_value = MagicMock(side_effect=RuntimeError("net"))

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices={5: device},
    )

    snapshot = await coordinator._async_update_data()
    assert snapshot[5] == cached


async def test_async_update_data_raises_when_no_cache(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If a device has no cache and the read fails, surface UpdateFailed."""
    device = make_tcl_device(5)
    device.attributes.clear()
    device.node.node_data.attributes = {}
    device.node.get_attribute_value = MagicMock(side_effect=RuntimeError("net"))

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices={5: device},
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_async_update_data_raises_when_node_returns_no_attributes(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If neither node_data nor get_attribute_value yields data, raise UpdateFailed."""
    device = make_tcl_device(5)
    device.attributes.clear()
    device.node.node_data.attributes = {}
    # get_attribute_value returns None for everything → no data.
    device.node.get_attribute_value = MagicMock(return_value=None)

    coordinator = TclMatterCoordinator(
        hass=hass,
        matter_client=mock_matter_client,
        devices={5: device},
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
