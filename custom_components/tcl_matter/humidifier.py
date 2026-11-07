"""
Humidifier platform for TCL Matter dehumidifiers.

Exposes one :class:`TclDehumidifier` per TCL node. Target humidity (attr 1) and
operating mode (attr 0) are written through
:meth:`TclMatterCoordinator.async_write_attribute`, which serialises writes per
attribute and skips a write the device already holds. Power is the standard
OnOff cluster (0x0006) on endpoint 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.exceptions import ServiceValidationError

from .const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_MODE,
    ATTR_TARGET_HUMIDITY,
    DOMAIN,
    MODE_NAME_MAP,
    MODE_VALUE_MAP,
    ONOFF_ATTR_ON_OFF,
    ONOFF_CLUSTER,
    ONOFF_ENDPOINT,
)
from .entity import TclMatterEntity
from .helpers import (
    coerce_int,
    humidity_limits,
    mode_name,
    snap_humidity,
    supported_modes,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import TclMatterConfigEntry
    from .coordinator import TclMatterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dehumidifier entities for every TCL node."""
    runtime = entry.runtime_data
    async_add_entities(
        TclDehumidifier(runtime.coordinator, node_id) for node_id in runtime.devices
    )


class TclDehumidifier(TclMatterEntity, HumidifierEntity):
    """Dehumidifier entity backed by TCL vendor cluster 0x1334FC03."""

    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_translation_key = "tcl_dehumidifier"
    _attr_name = None  # use device name

    def __init__(self, coordinator: TclMatterCoordinator, node_id: int) -> None:
        """Initialize the dehumidifier entity."""
        super().__init__(coordinator, node_id, "dehumidifier")
        node = coordinator.get_node(node_id)
        self._attr_available_modes = supported_modes(node)
        self._limits = humidity_limits(node)
        (
            self._attr_min_humidity,
            self._attr_max_humidity,
            self._attr_target_humidity_step,
        ) = self._limits

    @property
    def is_on(self) -> bool:
        """
        Return True if the unit is powered on.

        Power is the OnOff cluster, which the matter integration keeps current
        and pushes to this entity through the OnOff subscription. If it can't
        be read, fall back to treating the unit as on while its mode attribute
        is a known value.
        """
        node = self.coordinator.get_node(self._node_id)
        try:
            on_off = node.get_attribute_value(
                ONOFF_ENDPOINT, ONOFF_CLUSTER, ONOFF_ATTR_ON_OFF
            )
        # A node without endpoint 1 or the OnOff cluster raises KeyError.
        except AttributeError, KeyError:
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
        """Send an OnOff cluster command through the coordinator."""
        await self.coordinator.async_send_command(
            self._node_id, ONOFF_ENDPOINT, ONOFF_CLUSTER, command_name
        )

    @property
    def target_humidity(self) -> int | None:
        """Return the configured target humidity (RH %)."""
        return coerce_int(self._node_data.get(ATTR_TARGET_HUMIDITY))

    @property
    def current_humidity(self) -> int | None:
        """Return the device's measured ambient humidity (RH %)."""
        return coerce_int(self._node_data.get(ATTR_CURRENT_HUMIDITY))

    @property
    def mode(self) -> str | None:
        """Return the active operating mode."""
        mode = mode_name(self._node_data.get(ATTR_MODE))
        return mode if mode in self._attr_available_modes else None

    async def async_set_humidity(self, humidity: int) -> None:
        """Write the target humidity attribute on the device."""
        await self.coordinator.async_write_attribute(
            self._node_id,
            ATTR_TARGET_HUMIDITY,
            snap_humidity(humidity, self._limits),
        )

    async def async_set_mode(self, mode: str) -> None:
        """Write the operating mode attribute on the device."""
        if mode not in self.available_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_not_supported",
                translation_placeholders={"mode": mode},
            )
        await self.coordinator.async_write_attribute(
            self._node_id, ATTR_MODE, MODE_NAME_MAP[mode]
        )
