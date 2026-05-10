"""
Humidifier platform for TCL Matter dehumidifiers.

Exposes a single :class:`TclDehumidifier` per discovered TCL node. The
target humidity (attr 1) and operating mode (attr 0) are written back
to the device through the matter client's ``write_attribute`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)

from .const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    AVAILABLE_MODES,
    LOGGER,
    MAX_HUMIDITY,
    MIN_HUMIDITY,
    MODE_NAME_MAP,
    MODE_VALUE_MAP,
    TCL_CLUSTER_FC03,
)
from .entity import TclMatterEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import TclMatterConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dehumidifier entities for every TCL node."""
    runtime = entry.runtime_data
    entities = [
        TclDehumidifier(runtime.coordinator, runtime.matter_client, node_id)
        for node_id in runtime.devices
    ]
    async_add_entities(entities)


class TclDehumidifier(TclMatterEntity, HumidifierEntity):
    """Dehumidifier entity backed by TCL vendor cluster 0x1334FC03."""

    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_min_humidity = MIN_HUMIDITY
    _attr_max_humidity = MAX_HUMIDITY
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_available_modes = AVAILABLE_MODES
    _attr_translation_key = "tcl_dehumidifier"
    _attr_name = None  # use device name

    def __init__(
        self,
        coordinator: Any,
        matter_client: Any,
        node_id: int,
    ) -> None:
        """Initialize the dehumidifier entity."""
        super().__init__(coordinator, node_id, "dehumidifier")
        self._matter_client = matter_client

    @property
    def is_on(self) -> bool:
        """
        Return True if the unit appears to be running.

        TCL exposes power as a separate OnOff cluster on the same node.
        Until we wire that in, we treat the device as on whenever its
        mode attribute reports a known value.

        TODO(empirical): bind to the OnOff cluster (0x0006) on endpoint 1
        once the matter client lets us read it cheaply.
        """
        mode_value = self._node_data.get(ATTR_MODE)
        return mode_value in MODE_VALUE_MAP

    @property
    def target_humidity(self) -> int | None:
        """Return the configured target humidity (RH %)."""
        value = self._node_data.get(ATTR_TARGET_HUMIDITY)
        try:
            return int(value) if value is not None else None
        except TypeError, ValueError:
            return None

    @property
    def current_humidity(self) -> int | None:
        """Return the device's measured ambient humidity (RH %)."""
        value = self._node_data.get(ATTR_CURRENT_HUMIDITY)
        try:
            return int(value) if value is not None else None
        except TypeError, ValueError:
            return None

    @property
    def mode(self) -> str | None:
        """Return the active operating mode."""
        raw = self._node_data.get(ATTR_MODE)
        if raw is None:
            return None
        try:
            return MODE_VALUE_MAP.get(int(raw))
        except TypeError, ValueError:
            return None

    async def async_set_humidity(self, humidity: int) -> None:
        """Write the target humidity attribute on the device."""
        clamped = max(MIN_HUMIDITY, min(MAX_HUMIDITY, int(humidity)))
        await self._write_attr(ATTR_TARGET_HUMIDITY, clamped)

    async def async_set_mode(self, mode: str) -> None:
        """Write the operating mode attribute on the device."""
        if mode not in MODE_NAME_MAP:
            LOGGER.warning("Unknown TCL mode requested: %s", mode)
            return
        await self._write_attr(ATTR_MODE, MODE_NAME_MAP[mode])

    async def _write_attr(self, attr_id: int, value: Any) -> None:
        """
        Write a TCL vendor cluster attribute on the device.

        First tries the HA matter client's typed `write_attribute`. The
        matter-python-client library validates attribute paths against its
        cluster registry; vendor clusters that aren't pre-registered raise
        "Attribute X on cluster Y unknown". When that happens we fall back to
        a direct WebSocket send to the matter-server addon, which (with the
        cluster decoder loaded server-side) accepts the write.

        Both paths converge on the matter-server addon; the fallback just
        skips the client-side schema check.
        """
        path = f"1/{TCL_CLUSTER_FC03}/{attr_id}"
        wrote = await self._write_via_client(path, value)
        if not wrote:
            wrote = await self._write_via_direct_ws(path, value)
        if not wrote:
            LOGGER.error(
                "write_attribute failed via both paths for node=%s path=%s value=%r",
                self._node_id,
                path,
                value,
            )
            return
        # Optimistically update local cache so the UI reflects the change
        # without waiting for the next push/poll.
        self.coordinator._devices[self._node_id].attributes[attr_id] = value  # noqa: SLF001
        snapshot = dict(self.coordinator.data or {})
        snapshot.setdefault(self._node_id, {})[attr_id] = value
        self.coordinator.async_set_updated_data(snapshot)

    async def _write_via_client(self, path: str, value: Any) -> bool:
        """Try the HA matter client's typed write_attribute. Returns True on success."""
        write = getattr(self._matter_client, "write_attribute", None)
        if not callable(write):
            return False
        try:
            await write(node_id=self._node_id, attribute_path=path, value=value)
        except TypeError:
            try:
                await write(self._node_id, path, value)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("client positional write failed: %s", err)
                return False
        # The matter-python-client raises ValueError on unknown vendor attrs
        # before sending. Catch broadly because the upstream error type isn't
        # stable across releases.
        except Exception as err:  # noqa: BLE001
            LOGGER.debug(
                "client write rejected for %s; falling back to direct WS: %s",
                path,
                err,
            )
            return False
        return True

    async def _write_via_direct_ws(self, path: str, value: Any) -> bool:
        """
        Send write_attribute directly to the matter-server addon's WS.

        Bypasses the HA client's local cluster-registry check. The addon
        ships the TCL cluster decoder so the wire format succeeds.
        """
        import aiohttp  # noqa: PLC0415 — local-only fallback path

        url = "ws://core-matter-server:5580/ws"
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.ws_connect(url, timeout=10) as ws,
            ):
                await ws.receive_json()  # server hello
                await ws.send_json(
                    {
                        "message_id": "tcl_write",
                        "command": "write_attribute",
                        "args": {
                            "node_id": self._node_id,
                            "attribute_path": path,
                            "value": value,
                        },
                    }
                )
                msg = await ws.receive_json(timeout=10)
                if msg.get("error_code") or msg.get("error"):
                    LOGGER.warning("direct WS write failed: %s", msg)
                    return False
                return True
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("direct WS write to matter-server failed: %s", err)
            return False
