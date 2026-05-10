"""
Select platform for TCL Matter dehumidifiers.

Mirrors the humidifier's mode attribute as a standalone select entity.
This is convenient for users who want to bind mode to a dashboard tile or
trigger automations off mode changes without going through the humidifier
entity.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity

from .const import (
    ATTR_MODE,
    AVAILABLE_MODES,
    LOGGER,
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
    from .coordinator import TclMatterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TclMatterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TCL Matter select entities."""
    runtime = entry.runtime_data
    entities = [
        TclModeSelect(runtime.coordinator, runtime.matter_client, node_id)
        for node_id in runtime.devices
    ]
    async_add_entities(entities)


class TclModeSelect(TclMatterEntity, SelectEntity):
    """Operating mode selector mirroring humidifier attr 0."""

    _attr_options = AVAILABLE_MODES
    _attr_translation_key = "mode"

    def __init__(
        self,
        coordinator: TclMatterCoordinator,
        matter_client: Any,
        node_id: int,
    ) -> None:
        """Initialize the mode selector."""
        super().__init__(coordinator, node_id, "mode")
        self._matter_client = matter_client
        self._write_lock = asyncio.Lock()

    @property
    def current_option(self) -> str | None:
        """Return the active mode name."""
        raw = self._node_data.get(ATTR_MODE)
        if raw is None:
            return None
        try:
            return MODE_VALUE_MAP.get(int(raw))
        except TypeError, ValueError:
            return None

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode back to the device."""
        if option not in MODE_NAME_MAP:
            LOGGER.warning("Unknown TCL mode requested via select: %s", option)
            return

        target = MODE_NAME_MAP[option]
        path = f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}"

        async with self._write_lock:
            current = self._node_data.get(ATTR_MODE)
            if current == target:
                LOGGER.debug(
                    "select dedup: node=%s mode already %r — skipping",
                    self._node_id,
                    option,
                )
                return

            try:
                await live_write_attribute(
                    self._matter_client, self._node_id, path, target
                )
            # Defensive: matter-server raises an open-ended set of types.
            except Exception as err:  # noqa: BLE001
                LOGGER.error(
                    "live mode write failed: node=%s option=%s err=%s",
                    self._node_id,
                    option,
                    err,
                )
                return

            self.coordinator._devices[self._node_id].attributes[ATTR_MODE] = target  # noqa: SLF001
            snapshot = dict(self.coordinator.data or {})
            snapshot.setdefault(self._node_id, {})[ATTR_MODE] = target
            self.coordinator.async_set_updated_data(snapshot)
