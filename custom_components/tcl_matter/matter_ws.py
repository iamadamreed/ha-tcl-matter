"""
Live attribute I/O against the matter-server WebSocket.

The python-matter-server client maintains a local attribute cache in
``MatterNode.node_data.attributes``. For VENDOR-specific clusters that the
client lacks a decoder for (e.g. TCL's 0x1334FC03), this cache is populated
only at commissioning and is never refreshed — push events fire to
subscribers, but the cache itself stays stale forever.

To get device-truth for vendor cluster attributes we issue fresh reads
against the matter-server itself via the client's typed API methods. Those
typed methods wrap ``send_command`` with the correct ``require_schema``
version pin, then the matter-server (with the TCL decoder shipped in
``iamadamreed/addons`` / matter-js PR #630) handles the wire format and
returns a flat path-keyed dict.

This module exists so the rest of the integration depends on a small,
mockable surface rather than touching the matter client directly — which
makes both versioning and testing simpler.
"""

from __future__ import annotations

from typing import Any


async def live_read_attribute(
    matter_client: Any,
    node_id: int,
    attribute_path: str,
) -> Any:
    """
    Issue a fresh attribute read against the matter-server.

    The server returns a flat path-keyed dict (``{"1/322239491/1": 45}``).
    Wildcard paths (``"1/322239491/*"``) yield every attribute on the
    cluster in one round trip.
    """
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
    Issue a fresh attribute write against the matter-server.

    Raises whatever the server raises on failure; the caller is responsible
    for catching and logging.
    """
    await matter_client.write_attribute(
        node_id=node_id,
        attribute_path=attribute_path,
        value=value,
    )
