"""
Humidifier platform for TCL Matter dehumidifiers.

Exposes a single :class:`TclDehumidifier` per discovered TCL node. The
target humidity (attr 1) and operating mode (attr 0) are written back to
the device through ``matter_ws.live_write_attribute``, which talks to the
matter-server WebSocket directly so the vendor cluster decoder (matter-js
PR #630 / iamadamreed/addons fork) handles the wire format.

Two safety measures live in this module to prevent runaway write loops:

* **Per-attribute :class:`asyncio.Lock`** — serialises concurrent writes
  to the same attribute, so a tampered + auto-restore double-fire cannot
  interleave.
* **Write deduplication** — under the lock, compares the requested value
  to the cached value and skips the round trip when they match. Breaks
  the flap loop that would otherwise occur if a stale push event re-
  triggered an automation that wrote the same value back.
"""

from __future__ import annotations

import asyncio
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
from .matter_ws import live_write_attribute

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
        # One lock per attribute id; created lazily so we don't carry empty
        # lock objects for attrs we never write.
        self._write_locks: dict[int, asyncio.Lock] = {}

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

    def _lock_for(self, attr_id: int) -> asyncio.Lock:
        """Return (lazily-created) write lock for ``attr_id``."""
        lock = self._write_locks.get(attr_id)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[attr_id] = lock
        return lock

    async def _write_attr(self, attr_id: int, value: Any) -> None:
        """
        Write a TCL vendor cluster attribute on the device.

        Acquires the per-attribute lock, dedupes against the cached value,
        then issues a live write through the matter-server WebSocket. On
        success, the local cache is optimistically updated so the UI
        reflects the change without waiting for the next poll/push.
        """
        path = f"1/{TCL_CLUSTER_FC03}/{attr_id}"
        async with self._lock_for(attr_id):
            current = self._node_data.get(attr_id)
            if current == value:
                LOGGER.debug(
                    "write dedup: node=%s attr=%s already %r — skipping",
                    self._node_id,
                    attr_id,
                    value,
                )
                return

            try:
                await live_write_attribute(
                    self._matter_client, self._node_id, path, value
                )
            # Defensive: the matter-server raises an open-ended set of
            # exception types for transport, validation, and device-side
            # errors. Logging here is the right place; callers shouldn't
            # have to wrap every set_humidity/set_mode call in try/except.
            except Exception as err:  # noqa: BLE001
                LOGGER.error(
                    "live write failed: node=%s path=%s value=%r err=%s",
                    self._node_id,
                    path,
                    value,
                    err,
                )
                return

            self.coordinator._devices[self._node_id].attributes[attr_id] = value  # noqa: SLF001
            snapshot = dict(self.coordinator.data or {})
            snapshot.setdefault(self._node_id, {})[attr_id] = value
            self.coordinator.async_set_updated_data(snapshot)
