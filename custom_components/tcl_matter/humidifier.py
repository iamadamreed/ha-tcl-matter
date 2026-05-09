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
        Issue a matter write_attribute for one of our vendor attrs.

        The matter client API has shifted between releases: some take
        ``attribute_path=`` with a string, others take a parsed Attribute
        descriptor. We try the path-string form first and fall back to
        positional args.

        TODO(matter-api): unify on whichever signature ships in the HA
        release we target once the python-matter-server API stabilises
        for vendor cluster writes.
        """
        path = f"1/{TCL_CLUSTER_FC03}/{attr_id}"
        write = getattr(self._matter_client, "write_attribute", None)
        if not callable(write):
            LOGGER.error("matter_client has no write_attribute(); cannot push value")
            return

        try:
            await write(node_id=self._node_id, attribute_path=path, value=value)
        except TypeError:
            try:
                await write(self._node_id, path, value)
            # Defensive: matter-server APIs raise inconsistent types across versions.
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "write_attribute failed for node=%s path=%s value=%r",
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
