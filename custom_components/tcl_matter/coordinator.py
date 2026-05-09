"""DataUpdateCoordinator for TCL Matter vendor cluster reads.

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
    LOGGER,
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
            node_id: dict(device.attributes) for node_id, device in self._devices.items()
        }

        for node_id, device in self._devices.items():
            try:
                attrs = await self._read_cluster(node_id)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Polling node %s failed: %s", node_id, err)
                # Re-raise as UpdateFailed only if we have nothing cached yet,
                # so a transient miss does not blank-out a working device.
                if not device.attributes:
                    raise UpdateFailed(f"node {node_id}: {err}") from err
                continue

            device.attributes.update(attrs)
            snapshot[node_id] = dict(device.attributes)

        return snapshot

    async def _read_cluster(self, node_id: int) -> dict[int, Any]:
        """Wildcard-read cluster 0x1334FC03 for ``node_id``.

        The python-matter-server ``read_attribute`` method accepts a path
        string of the form ``"<endpoint>/<cluster>/<attr>"`` where ``*`` is
        a wildcard. We always read endpoint 1 (the appliance endpoint).
        """
        path = f"1/{TCL_CLUSTER_FC03}/*"
        read_attribute = getattr(self._matter_client, "read_attribute", None)
        if not callable(read_attribute):
            msg = "matter_client has no read_attribute()"
            raise UpdateFailed(msg)

        try:
            result = await read_attribute(node_id=node_id, attribute_path=path)
        except TypeError:
            # Some versions take positional args
            result = await read_attribute(node_id, path)

        return self._normalize_read_result(result)

    @staticmethod
    def _normalize_read_result(result: Any) -> dict[int, Any]:
        """Coerce a matter read response into ``{attr_id: value}``.

        The matter client may return either:
        * ``{"1/322239491/0": value, ...}`` — flat path → value, or
        * ``{node_id: {endpoint: {cluster: {attr: value}}}}`` — nested.
        """
        out: dict[int, Any] = {}
        if not isinstance(result, dict):
            return out

        for key, value in result.items():
            if isinstance(key, str) and key.count("/") == 2:
                _, _, attr_str = key.split("/")
                try:
                    out[int(attr_str)] = value
                except ValueError:
                    continue
                continue

            # Nested form: drill down to attr-keyed dict
            if isinstance(value, dict):
                # value might be {endpoint: {cluster: {attr: v}}} or {cluster: {attr: v}}
                for inner in _walk_to_attr_dict(value):
                    for attr_id, attr_val in inner.items():
                        try:
                            out[int(attr_id)] = attr_val
                        except (TypeError, ValueError):
                            continue
        return out

    def handle_push_event(self, event: Any, data: Any = None) -> None:
        """Apply a single push update to the cached snapshot.

        ``event`` may be a string event-type or an enum; ``data`` contains
        the payload. We accept several shapes because python-matter-server
        has not stabilised its event API across versions. Anything we do
        not recognise is logged at debug level and ignored.
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
        except (TypeError, ValueError):
            return
        if node_id_int not in self._devices:
            return

        # Path: "endpoint/cluster/attr"
        parts = path.split("/")
        if len(parts) != 3:
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
    """Walk a nested dict and return every leaf-level dict.

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
