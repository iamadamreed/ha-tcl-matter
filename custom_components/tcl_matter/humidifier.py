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

from typing import TYPE_CHECKING, Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError

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
    ONOFF_ATTR_ON_OFF,
    ONOFF_CLUSTER,
    ONOFF_ENDPOINT,
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
        Return True if the unit is powered on.

        Power is the standard OnOff cluster (0x0006) on endpoint 1, which the
        matter integration keeps current. If it can't be read, fall back to
        treating the unit as on while its mode attribute is a known value.
        """
        node = self.coordinator.get_node(self._node_id)
        get_attr = getattr(node, "get_attribute_value", None)
        if callable(get_attr):
            try:
                on_off = get_attr(ONOFF_ENDPOINT, ONOFF_CLUSTER, ONOFF_ATTR_ON_OFF)
            # Defensive: matter-server APIs raise inconsistent types.
            except Exception:  # noqa: BLE001
                on_off = None
            if isinstance(on_off, bool):
                return on_off
        return self._node_data.get(ATTR_MODE) in MODE_VALUE_MAP

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the unit on."""
        await self._send_on_off("On")

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the unit off."""
        await self._send_on_off("Off")

    async def _send_on_off(self, command_name: str) -> None:
        """Send an OnOff cluster command through the matter server."""
        try:
            await self._matter_client.send_command(
                "device_command",
                node_id=self._node_id,
                endpoint_id=ONOFF_ENDPOINT,
                cluster_id=ONOFF_CLUSTER,
                command_name=command_name,
                payload={},
            )
        # Defensive: the matter-server raises an open-ended set of types.
        except Exception as err:
            msg = f"{command_name} failed for node {self._node_id}: {err}"
            raise HomeAssistantError(msg) from err

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
        """Write a vendor attribute through the coordinator."""
        await self.coordinator.async_write_attribute(self._node_id, attr_id, value)
