"""
DataUpdateCoordinator for TCL Matter vendor cluster reads.

``coordinator.data`` (``{node_id: {attr_id: value}}``) is the single cache of
cluster 0x1334FC03. Three paths feed it:

* **Push** - the integration subscribes to each attribute path on the matter
  client. The client calls back with only the new value, so the node and
  attribute are bound into the callback when it is registered (see
  ``__init__``). Updates reach :meth:`handle_attribute_update`.
* **Writes** - :meth:`async_write_attribute` stores the value it wrote.
* **Poll** - every :data:`POLL_INTERVAL_SECONDS` seconds the cluster is
  re-read. The matter client decodes TCL's cluster (client 1.3.0 and newer)
  and keeps the decoded values on the node object, so the poll reads them
  from there at no cost. A client without the decoder leaves them empty, and
  the poll then falls back to a wildcard read against the matter-server.

Every store bumps a per-attribute sequence number. A poll remembers the
numbers it started with and drops any value that was written or pushed while
the read was in flight, so a slow poll cannot put an old value back. Stores
do not restart the poll timer, so a busy node cannot starve the poll for the
others.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    LOGGER,
    NUM_TCL_FC03_DATA_ATTRS,
    POLL_INTERVAL_SECONDS,
    TCL_CLUSTER_FC03,
    UNAVAILABLE_AFTER_FAILURES,
)
from .matter_io import (
    WriteRejectedError,
    live_device_command,
    live_read_attribute,
    live_write_attribute,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from . import TclDevice


class TclMatterCoordinator(DataUpdateCoordinator[dict[int, dict[int, Any]]]):
    """Coordinator that maintains {node_id: {attr_id: value}} for TCL devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry | None,
        matter_client: Any,
        devices: dict[int, TclDevice],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="tcl_matter",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )
        self._matter_client = matter_client
        self._devices = devices
        self._write_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._write_seq: dict[tuple[int, int], int] = {}
        self._failures: dict[int, int] = dict.fromkeys(devices, 0)

    @property
    def matter_client(self) -> Any:
        """Return the matter client this coordinator reads and writes through."""
        return self._matter_client

    def get_node(self, node_id: int) -> Any | None:
        """Return the matter node object for ``node_id``, if known."""
        device = self._devices.get(node_id)
        return device.node if device else None

    def node_available(self, node_id: int) -> bool:
        """
        Return True while the node is reachable.

        A node is unreachable when the matter server marks it unavailable or
        when its last few polls failed.
        """
        node = self.get_node(node_id)
        if node is None:
            return False
        if self._failures.get(node_id, 0) >= UNAVAILABLE_AFTER_FAILURES:
            return False
        return node.available is not False

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[int, dict[int, Any]]:
        """Poll cluster 0x1334FC03 for every node, in parallel."""
        started = dict(self._write_seq)
        node_ids = list(self._devices)
        results = await asyncio.gather(*(self._poll_node(n) for n in node_ids))

        if node_ids and all(r is None for r in results):
            msg = "no TCL node could be read"
            raise UpdateFailed(msg)

        # Merge into whatever is current now, so pushes and writes that landed
        # during the read are kept.
        data = {nid: dict(attrs) for nid, attrs in (self.data or {}).items()}
        for node_id, attrs in zip(node_ids, results, strict=True):
            if attrs is None:
                continue
            current = data.setdefault(node_id, {})
            for attr_id, value in attrs.items():
                key = (node_id, attr_id)
                if self._write_seq.get(key, 0) == started.get(key, 0):
                    current[attr_id] = value
        return data

    def _decoded_values(self, node_id: int) -> dict[int, Any]:
        """
        Return the cluster values the matter client holds for this node.

        Empty if the client has no decoder for the cluster or the node has no
        endpoint 1.
        """
        node = self.get_node(node_id)
        values: dict[int, Any] = {}
        for attr_id in range(NUM_TCL_FC03_DATA_ATTRS):
            try:
                value = node.get_attribute_value(1, TCL_CLUSTER_FC03, attr_id)
            # Defensive: a node without endpoint 1 or without the cluster
            # raises KeyError or AttributeError depending on client version.
            except AttributeError, KeyError, TypeError:
                return {}
            if value is not None:
                values[attr_id] = value
        return values

    async def _poll_node(self, node_id: int) -> dict[int, Any] | None:
        """Read one node. Returns None on failure and tracks availability."""
        if decoded := self._decoded_values(node_id):
            self._record_success(node_id)
            return decoded
        try:
            result = await live_read_attribute(
                self._matter_client, node_id, f"1/{TCL_CLUSTER_FC03}/*"
            )
            attrs = self._parse_cluster_response(result)
            if not attrs:
                msg = "no attributes returned for cluster 0x1334FC03"
                raise UpdateFailed(msg)  # noqa: TRY301
        # Defensive: the matter client raises an open-ended set of exception
        # types (transport, timeout, node errors). Any of them means this read
        # failed; the other nodes are still polled.
        except Exception as err:  # noqa: BLE001
            self._record_failure(node_id, err)
            return None
        self._record_success(node_id)
        return attrs

    def _record_failure(self, node_id: int, err: Exception) -> None:
        """Count a failed poll and log once when the node goes unavailable."""
        count = self._failures.get(node_id, 0) + 1
        self._failures[node_id] = count
        if count == UNAVAILABLE_AFTER_FAILURES:
            LOGGER.warning("TCL node %s is unavailable: %s", node_id, err)
        else:
            LOGGER.debug("Polling node %s failed: %s", node_id, err)

    def _record_success(self, node_id: int) -> None:
        """Reset the failure count and log once when the node comes back."""
        if self._failures.get(node_id, 0) >= UNAVAILABLE_AFTER_FAILURES:
            LOGGER.info("TCL node %s is available again", node_id)
        self._failures[node_id] = 0

    @staticmethod
    def _parse_cluster_response(result: Any) -> dict[int, Any]:
        """
        Extract ``{attr_id: value}`` for cluster 0x1334FC03 from a server response.

        Accepts the flat path-keyed dict the matter-server returns
        (``{"1/322239491/1": 45, ...}``). Other shapes return an empty dict.
        """
        if not isinstance(result, dict):
            return {}

        prefix = f"1/{TCL_CLUSTER_FC03}/"
        out: dict[int, Any] = {}
        for full_path, value in result.items():
            if not isinstance(full_path, str) or not full_path.startswith(prefix):
                continue
            try:
                attr_id = int(full_path[len(prefix) :])
            except ValueError:
                continue
            # Keep only data attrs; skip cluster metadata (>= 0xFFF8).
            if 0 <= attr_id < NUM_TCL_FC03_DATA_ATTRS:
                out[attr_id] = value
        return out

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def handle_attribute_update(
        self,
        node_id: int,
        attr_id: int,
        event: Any,  # noqa: ARG002
        value: Any,
    ) -> None:
        """
        Apply a pushed attribute value.

        Registered per (node, attribute) with those two arguments bound,
        because the matter client passes only ``(event, value)``.
        """
        if (self.data or {}).get(node_id, {}).get(attr_id) == value:
            return
        self._store(node_id, attr_id, value)

    def handle_state_change(self, *_args: Any) -> None:
        """Re-render entities after a node or OnOff change (no cluster data)."""
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Writes and commands
    # ------------------------------------------------------------------

    async def async_write_attribute(
        self,
        node_id: int,
        attr_id: int,
        value: Any,
    ) -> None:
        """
        Write a vendor-cluster attribute, serialised per (node, attribute).

        Skips the write when the device already holds ``value``. That check is
        a live read, not the cache, because the cache can lag a change made at
        the unit. If the read fails or times out the write goes ahead. Raises
        :class:`HomeAssistantError` if the write fails or is rejected.
        """
        path = f"1/{TCL_CLUSTER_FC03}/{attr_id}"
        key = (node_id, attr_id)
        if key not in self._write_locks:
            self._write_locks[key] = asyncio.Lock()
        async with self._write_locks[key]:
            try:
                live = await live_read_attribute(self._matter_client, node_id, path)
            # Defensive: a failed read must not block the write itself.
            except Exception:  # noqa: BLE001
                live = None
            if isinstance(live, dict) and live.get(path) == value:
                LOGGER.debug(
                    "write dedup: node=%s attr=%s already %r on device",
                    node_id,
                    attr_id,
                    value,
                )
                self._store(node_id, attr_id, value)
                return

            try:
                await live_write_attribute(self._matter_client, node_id, path, value)
            except WriteRejectedError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="write_rejected",
                    translation_placeholders={
                        "path": path,
                        "status": str(err.status),
                    },
                ) from err
            # Defensive: the matter client raises an open-ended set of
            # exception types for transport, timeout and device errors.
            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="write_failed",
                    translation_placeholders={"path": path, "error": str(err)},
                ) from err

            self._store(node_id, attr_id, value)

    async def async_send_command(
        self,
        node_id: int,
        endpoint_id: int,
        cluster_id: int,
        command_name: str,
    ) -> None:
        """Send an argument-less cluster command. Raises HomeAssistantError."""
        try:
            await live_device_command(
                self._matter_client, node_id, endpoint_id, cluster_id, command_name
            )
        # Defensive: the matter client raises an open-ended set of types.
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={
                    "command": command_name,
                    "error": str(err),
                },
            ) from err
        # The node cache updates on the pushed OnOff event; refresh listeners
        # in case that event arrives before this call returns.
        self.async_update_listeners()

    def _store(self, node_id: int, attr_id: int, value: Any) -> None:
        """
        Record a value and publish it to listeners.

        Deliberately not ``async_set_updated_data``: that restarts the poll
        timer, so frequent pushes from one node would keep the poll from ever
        running for the others.
        """
        key = (node_id, attr_id)
        self._write_seq[key] = self._write_seq.get(key, 0) + 1
        new_snapshot = dict(self.data or {})
        new_snapshot[node_id] = {**new_snapshot.get(node_id, {}), attr_id: value}
        self.data = new_snapshot
        self.async_update_listeners()
