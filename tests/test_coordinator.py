"""Tests for ``custom_components.tcl_matter.coordinator``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tcl_matter.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    NUM_TCL_FC03_DATA_ATTRS,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.coordinator import TclMatterCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


# ---------------------------------------------------------------------------
# _parse_cluster_response
# ---------------------------------------------------------------------------


def test_parse_cluster_response_flat_paths() -> None:
    """Flat ``"endpoint/cluster/attr"`` keys yield an attr-id keyed dict."""
    result = {
        f"1/{TCL_CLUSTER_FC03}/0": 0,
        f"1/{TCL_CLUSTER_FC03}/1": 50,
        f"1/{TCL_CLUSTER_FC03}/2": 58,
    }
    out = TclMatterCoordinator._parse_cluster_response(result)
    assert out == {0: 0, 1: 50, 2: 58}


def test_parse_cluster_response_skips_metadata_attrs() -> None:
    """Attrs >= NUM_TCL_FC03_DATA_ATTRS (e.g. 65528, 65532) are dropped."""
    result = {
        f"1/{TCL_CLUSTER_FC03}/1": 45,
        f"1/{TCL_CLUSTER_FC03}/65528": [],
        f"1/{TCL_CLUSTER_FC03}/65532": 0,
    }
    out = TclMatterCoordinator._parse_cluster_response(result)
    assert out == {1: 45}


def test_parse_cluster_response_skips_other_clusters() -> None:
    """Path entries for other clusters / endpoints are ignored."""
    result = {
        f"1/{TCL_CLUSTER_FC03}/0": 0,
        "0/40/1": 0x1334,  # BasicInformation/VendorID — wrong cluster
        "1/6/0": True,  # OnOff cluster — wrong cluster
        f"2/{TCL_CLUSTER_FC03}/1": 99,  # right cluster, wrong endpoint
    }
    out = TclMatterCoordinator._parse_cluster_response(result)
    assert out == {0: 0}


def test_parse_cluster_response_handles_unparseable() -> None:
    """Path components that aren't ints are silently dropped."""
    result = {f"1/{TCL_CLUSTER_FC03}/abc": 99, f"1/{TCL_CLUSTER_FC03}/2": 58}
    out = TclMatterCoordinator._parse_cluster_response(result)
    assert out == {2: 58}


def test_parse_cluster_response_non_dict_input() -> None:
    """Non-dict inputs return an empty dict rather than raising."""
    assert TclMatterCoordinator._parse_cluster_response(None) == {}
    assert TclMatterCoordinator._parse_cluster_response([1, 2]) == {}
    assert TclMatterCoordinator._parse_cluster_response("nope") == {}


# ---------------------------------------------------------------------------
# _read_cluster — live read via matter_client.read_attribute
# ---------------------------------------------------------------------------


async def test_read_cluster_issues_wildcard_read(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """``_read_cluster`` issues a single wildcard ``read_attribute`` call."""
    device = make_tcl_device(5, {0: 0, 1: 50, 2: 58})
    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )

    out = await coordinator._read_cluster(5)

    # The fixture's read_attribute returns the default_node_attributes snapshot.
    assert out[ATTR_TARGET_HUMIDITY] == 50
    assert out[ATTR_CURRENT_HUMIDITY] == 58
    mock_matter_client.read_attribute.assert_awaited_once_with(
        node_id=5,
        attribute_path=f"1/{TCL_CLUSTER_FC03}/*",
    )


async def test_read_cluster_returns_device_truth_not_node_data_cache(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """Regression: the coordinator must NOT read from ``node_data.attributes``.

    This is the bug that v0.4.0 fixes — node_data.attributes is the
    matter-python-client's local cache which never updates for vendor
    clusters. Even when that cache is wildly wrong, the coordinator must
    return the live server truth.
    """
    device = make_tcl_device(5, {1: 50})
    # Poison node_data.attributes with stale wrong values to prove the
    # coordinator never reads them.
    device.node.node_data.attributes[f"1/{TCL_CLUSTER_FC03}/1"] = 99
    device.node.node_data.attributes[f"1/{TCL_CLUSTER_FC03}/2"] = 99
    # Configure read_attribute to return the device truth.
    truth = {
        f"1/{TCL_CLUSTER_FC03}/0": 0,
        f"1/{TCL_CLUSTER_FC03}/1": 45,
        f"1/{TCL_CLUSTER_FC03}/2": 52,
    }
    mock_matter_client.read_attribute = AsyncMock(return_value=truth)

    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )

    out = await coordinator._read_cluster(5)
    assert out[1] == 45  # device truth, not node_data's stale 99
    assert out[2] == 52


async def test_read_cluster_raises_on_unknown_node(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
) -> None:
    """An unknown node_id surfaces UpdateFailed."""
    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={}
    )
    with pytest.raises(UpdateFailed):
        await coordinator._read_cluster(99)


async def test_read_cluster_raises_when_server_returns_nothing(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If the server response yields zero parsed attrs, raise UpdateFailed."""
    device = make_tcl_device(5)
    mock_matter_client.read_attribute = AsyncMock(return_value={})

    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )
    with pytest.raises(UpdateFailed):
        await coordinator._read_cluster(5)


async def test_read_cluster_raises_when_server_returns_garbage(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """Garbage server response (non-dict) also raises UpdateFailed."""
    device = make_tcl_device(5)
    mock_matter_client.read_attribute = AsyncMock(return_value="not a dict")

    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )
    with pytest.raises(UpdateFailed):
        await coordinator._read_cluster(5)


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


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
        hass=hass, matter_client=mock_matter_client, devices=devices
    )

    snapshot = await coordinator._async_update_data()
    # Each device gets a wildcard read; both snapshots reflect the fixture data.
    assert snapshot[5][ATTR_TARGET_HUMIDITY] == 50
    assert snapshot[6][ATTR_TARGET_HUMIDITY] == 50
    assert mock_matter_client.read_attribute.await_count == 2


async def test_async_update_data_preserves_cache_on_failure(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """A failing poll on a device with cached data is logged but not raised."""
    cached = {ATTR_MODE: 0, ATTR_TARGET_HUMIDITY: 50}
    device = make_tcl_device(5, cached)
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("net"))

    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )

    snapshot = await coordinator._async_update_data()
    assert snapshot[5] == cached  # cached value retained, no exception


async def test_async_update_data_raises_when_no_cache(
    hass: HomeAssistant,
    mock_matter_client: MagicMock,
    make_tcl_device: Any,
) -> None:
    """If a device has no cache and the read fails, surface UpdateFailed."""
    device = make_tcl_device(5)
    device.attributes.clear()
    mock_matter_client.read_attribute = AsyncMock(side_effect=RuntimeError("net"))

    coordinator = TclMatterCoordinator(
        hass=hass, matter_client=mock_matter_client, devices={5: device}
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# handle_push_event
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Defensive: cluster constant must exist for test sanity
# ---------------------------------------------------------------------------


def test_data_attribute_id_range_is_sensible() -> None:
    """Sanity: the attribute-ID range used by the parser stays small."""
    # If this changes, _parse_cluster_response's metadata cutoff also must.
    assert NUM_TCL_FC03_DATA_ATTRS == 7
