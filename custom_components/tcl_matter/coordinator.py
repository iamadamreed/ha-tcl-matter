"""
DataUpdateCoordinator for TCL Matter vendor cluster reads.

The coordinator is the single source of truth for the per-node attribute
snapshot of cluster 0x1334FC03. Two ingestion paths feed it:

* **Push** — the integration subscribes to the matter client's attribute
  events and forwards relevant updates via :meth:`handle_push_event`.
* **Poll** — every :data:`POLL_INTERVAL_SECONDS` seconds the coordinator
  issues a wildcard live-read on cluster 0x1334FC03 against the matter-
  server itself (not the client's stale cache). See ``matter_ws`` for the
  rationale.
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
from .matter_ws import live_read_attribute

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
                if not device.attributes:
                    msg = f"node {node_id}: {err}"
                    raise UpdateFailed(msg) from err
                continue

            device.attributes.update(attrs)
            snapshot[node_id] = dict(device.attributes)

        return snapshot

    async def _read_cluster(self, node_id: int) -> dict[int, Any]:
        """
        Live-read every TCL_CLUSTER_FC03 attribute for ``node_id``.

        Issues a single wildcard ``read_attribute`` over the matter-server
        WebSocket and parses the flat path-keyed response. Skips cluster
        metadata attributes (>=0xFFF8) and out-of-range IDs.
        """
        if node_id not in self._devices:
            msg = f"unknown node_id {node_id}"
            raise UpdateFailed(msg)

        wildcard_path = f"1/{TCL_CLUSTER_FC03}/*"
        result = await live_read_attribute(self._matter_client, node_id, wildcard_path)

        out = self._parse_cluster_response(result)
        if not out:
            msg = "no attributes returned for cluster 0x1334FC03"
            raise UpdateFailed(msg)
        return out

    @staticmethod
    def _parse_cluster_response(result: Any) -> dict[int, Any]:
        """
        Extract ``{attr_id: value}`` for cluster 0x1334FC03 from a server response.

        Accepts the flat path-keyed dict shape the matter-server returns
        (``{"1/322239491/1": 45, ...}``). Other shapes return an empty dict.
        """
        if not isinstance(result, dict):
            return {}

        prefix = f"1/{TCL_CLUSTER_FC03}/"
        out: dict[int, Any] = {}
        for full_path, value in result.items():
            if not isinstance(full_path, str) or not full_path.startswith(prefix):
                continue
            attr_str = full_path[len(prefix) :]
            try:
                attr_id = int(attr_str)
            except ValueError:
                continue
            # Keep only data attrs; skip cluster metadata (>= 0xFFF8).
            if 0 <= attr_id < NUM_TCL_FC03_DATA_ATTRS:
                out[attr_id] = value
        return out

    def handle_push_event(self, event: Any, data: Any = None) -> None:  # noqa: PLR0911
        """
        Apply a single push update to the cached snapshot.

        ``event`` may be a string event-type or an enum; ``data`` carries
        the payload. Several payload shapes are accepted because the matter
        client has not stabilised its event API across versions. Anything
        unrecognised is logged at debug level and ignored.

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
