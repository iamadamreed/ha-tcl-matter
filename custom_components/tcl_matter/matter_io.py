"""
Live attribute I/O against the matter-server.

The matter client keeps a local attribute cache in
``MatterNode.node_data.attributes``. For vendor clusters it has no decoder for
(such as TCL's 0x1334FC03) that cache is not refreshed, so the integration
reads the device through the server instead. This module is the single place
that touches the client's read, write and command calls, and it adds what the
client does not: a timeout on every round trip and a check of the per-path
status that a write returns.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .const import READ_TIMEOUT_SECONDS, WRITE_TIMEOUT_SECONDS


class WriteRejectedError(Exception):
    """The device accepted the request but rejected the write."""

    def __init__(self, path: str, status: int) -> None:
        """Remember the attribute path and the Matter status code."""
        super().__init__(f"{path} rejected with status {status}")
        self.path = path
        self.status = status


async def live_read_attribute(
    matter_client: Any,
    node_id: int,
    attribute_path: str,
) -> Any:
    """
    Issue a fresh attribute read against the matter-server.

    The server returns a flat path-keyed dict (``{"1/322239491/1": 45}``).
    Wildcard paths (``"1/322239491/*"``) yield every attribute on the cluster
    in one round trip. Raises :class:`TimeoutError` if the server is silent.
    """
    async with asyncio.timeout(READ_TIMEOUT_SECONDS):
        return await matter_client.read_attribute(
            node_id=node_id,
            attribute_path=attribute_path,
        )


async def live_write_attribute(
    matter_client: Any,
    node_id: int,
    attribute_path: str,
    value: Any,
) -> None:
    """
    Write an attribute and check the status the device reports for it.

    The server answers with a list of ``{"Path": ..., "Status": ...}`` items
    and does not raise when the device rejects the value, so a non-zero status
    is turned into :class:`WriteRejectedError`.
    """
    async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
        result = await matter_client.write_attribute(
            node_id=node_id,
            attribute_path=attribute_path,
            value=value,
        )
    if not isinstance(result, list):
        return
    for item in result:
        status = item.get("Status") if isinstance(item, dict) else None
        if status not in (None, 0):
            raise WriteRejectedError(attribute_path, status)


async def live_device_command(
    matter_client: Any,
    node_id: int,
    endpoint_id: int,
    cluster_id: int,
    command_name: str,
) -> None:
    """Send a standard cluster command that takes no arguments."""
    async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
        await matter_client.send_command(
            "device_command",
            node_id=node_id,
            endpoint_id=endpoint_id,
            cluster_id=cluster_id,
            command_name=command_name,
            payload={},
        )
