"""
DataUpdateCoordinator for TCL Matter vendor cluster reads.

This coordinator is the single source of truth for the per-node attribute
snapshot of cluster 0x1334FC03. It supports two ingestion paths:

* **Push** — the integration subscribes to the matter client's attribute
  events and forwards relevant updates via :meth:`handle_push_event`.
* **Poll** — every :data:`POLL_INTERVAL_SECONDS` seconds the coordinator
  performs a wildcard attribute read on cluster 0x1334FC03 for each known
  node, in case push delivery is not available for vendor clusters in the
  current python-matter-server release.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_PATH_PARTS,
    LOGGER,
    NUM_TCL_FC03_DATA_ATTRS,
    POLL_INTERVAL_SECONDS,
    TCL_CLUSTER_FC03,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import TclDevice


class TclMatterCoordinator(DataUpdateCoordinator[dict[int, dict[int, Any]]]):
    """Coordinator that maintains {node_id: {attr_id: value}} for TCL devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        matter_client: Any,
        devices: dict[int, TclDevice],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="tcl_matter",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )
        self._matter_client = matter_client
        self._devices = devices

    async def _async_update_data(self) -> dict[int, dict[int, Any]]:
        """Poll cluster 0x1334FC03 for every known TCL node."""
        snapshot: dict[int, dict[int, Any]] = {
            node_id: dict(device.attributes)
            for node_id, device in self._devices.items()
        }

        for node_id, device in self._devices.items():
            try:
                attrs = await self._read_cluster(node_id)
            # Defensive: matter-server raises an open-ended set of exception
            # types across versions; we want to fall back to cached values
            # rather than crash the coordinator.
            except Exception as err:
                LOGGER.debug("Polling node %s failed: %s", node_id, err)
                # Re-raise as UpdateFailed only if we have nothing cached yet,
                # so a transient miss does not blank-out a working device.
                if not device.attributes:
                    msg = f"node {node_id}: {err}"
                    raise UpdateFailed(msg) from err
                continue

            device.attributes.update(attrs)
            snapshot[node_id] = dict(device.attributes)

        return snapshot

    async def _read_cluster(self, node_id: int) -> dict[int, Any]:
        """
        Read all known attributes of cluster 0x1334FC03 for ``node_id``.

        Uses ``node.get_attribute_value(endpoint, cluster_id, attribute_id)``
        which returns the live cached value the matter-server already
        subscribes to — no extra Matter round trip needed.

        We enumerate the 7 known attribute IDs (0-6) on cluster 0x1334FC03
        rather than wildcard-walking, so the response is always a clean
        ``{attr_id: value}`` dict.
        """
        device = self._devices.get(node_id)
        if device is None:
            msg = f"unknown node_id {node_id}"
            raise UpdateFailed(msg)

        node = device.node
        get_attr = getattr(node, "get_attribute_value", None)
        if not callable(get_attr):
            msg = "MatterNode has no get_attribute_value() method"
            raise UpdateFailed(msg)

        out: dict[int, Any] = {}

        # Primary: read from node.node_data.attributes (raw dict from matter-server).
        # This is the only path that works for vendor-specific clusters because
        # MatterNode.get_attribute_value() relies on a cluster registry that
        # python-matter-server doesn't ship with TCL definitions yet (until
        # the upstream cluster decoder PR lands).
        node_data = getattr(node, "node_data", None)
        raw_attrs = getattr(node_data, "attributes", None) if node_data else None
        if isinstance(raw_attrs, dict):
            prefix = f"1/{TCL_CLUSTER_FC03}/"
            for path, value in raw_attrs.items():
                if not isinstance(path, str) or not path.startswith(prefix):
                    continue
                attr_str = path[len(prefix) :]
                try:
                    attr_id = int(attr_str)
                except ValueError:
                    continue
                # Keep only our known data attrs; skip cluster metadata (>=0xFFF8).
                if 0 <= attr_id < NUM_TCL_FC03_DATA_ATTRS:
                    out[attr_id] = value

        # Fallback: get_attribute_value (works once a cluster decoder is registered).
        if not out:
            for attr_id in range(NUM_TCL_FC03_DATA_ATTRS):
                try:
                    value = get_attr(1, TCL_CLUSTER_FC03, attr_id)
                # Defensive: skip individual attrs that the matter client
                # cannot decode rather than failing the whole poll.
                except Exception as err:  # noqa: BLE001
                    LOGGER.debug(
                        "node %s attr %s read fallback failed: %s",
                        node_id,
                        attr_id,
                        err,
                    )
                    continue
                if value is not None:
                    out[attr_id] = value

        if not out:
            msg = "no attributes readable from cluster 0x1334FC03"
            raise UpdateFailed(msg)
        return out

    @staticmethod
    def _normalize_read_result(result: Any) -> dict[int, Any]:
        """
        Coerce a matter read response into ``{attr_id: value}``.

        The matter client may return either:
        * ``{"1/322239491/0": value, ...}`` — flat path → value, or
        * ``{node_id: {endpoint: {cluster: {attr: value}}}}`` — nested.
        """
        out: dict[int, Any] = {}
        if not isinstance(result, dict):
            return out

        for key, value in result.items():
            if isinstance(key, str) and key.count("/") == ATTR_PATH_PARTS - 1:
                _, _, attr_str = key.split("/")
                try:
                    out[int(attr_str)] = value
                except ValueError:
                    continue
                continue

            # Nested form: drill down to attr-keyed dict.
            # value is endpoint -> cluster -> attr -> v, or cluster -> attr -> v.
            if isinstance(value, dict):
                for inner in _walk_to_attr_dict(value):
                    for attr_id, attr_val in inner.items():
                        try:
                            out[int(attr_id)] = attr_val
                        except TypeError, ValueError:
                            continue
        return out

    def handle_push_event(self, event: Any, data: Any = None) -> None:  # noqa: PLR0911
        """
        Apply a single push update to the cached snapshot.

        ``event`` may be a string event-type or an enum; ``data`` contains
        the payload. We accept several shapes because python-matter-server
        has not stabilised its event API across versions. Anything we do
        not recognise is logged at debug level and ignored.

        The early-return guard clauses validate untrusted input shapes from
        the matter client; collapsing them into a single return path would
        hurt readability, so PLR0911 is accepted here.
        """
        payload = data if data is not None else event
        if not isinstance(payload, dict):
            return

        node_id = payload.get("node_id") or payload.get("nodeId")
        path = payload.get("attribute_path") or payload.get("path")
        value = payload.get("value")

        if node_id is None or not isinstance(path, str):
            return
        try:
            node_id_int = int(node_id)
        except TypeError, ValueError:
            return
        if node_id_int not in self._devices:
            return

        # The path string is endpoint, cluster, and attr separated by slashes.
        parts = path.split("/")
        if len(parts) != ATTR_PATH_PARTS:
            return
        try:
            cluster_id = int(parts[1])
            attr_id = int(parts[2])
        except ValueError:
            return

        if cluster_id != TCL_CLUSTER_FC03:
            return

        self._devices[node_id_int].attributes[attr_id] = value
        new_snapshot = dict(self.data or {})
        new_snapshot.setdefault(node_id_int, {})[attr_id] = value
        self.async_set_updated_data(new_snapshot)


def _walk_to_attr_dict(d: dict[Any, Any]) -> list[dict[Any, Any]]:
    """
    Walk a nested dict and return every leaf-level dict.

    Used by :meth:`TclMatterCoordinator._normalize_read_result` to handle
    nested response shapes without committing to one library version.
    """
    leaves: list[dict[Any, Any]] = []
    stack: list[Any] = [d]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        # Leaf if no value is itself a dict
        if all(not isinstance(v, dict) for v in current.values()):
            leaves.append(current)
            continue
        stack.extend(current.values())
    return leaves
