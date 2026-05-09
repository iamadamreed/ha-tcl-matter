"""Select platform for TCL Matter dehumidifiers.

Mirrors the humidifier's mode attribute as a standalone select entity.
This is convenient for users who want to bind mode to a dashboard tile
or trigger automations off mode changes without going through the
humidifier entity.
"""

from __future__ import annotations

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

    @property
    def current_option(self) -> str | None:
        """Return the active mode name."""
        raw = self._node_data.get(ATTR_MODE)
        if raw is None:
            return None
        try:
            return MODE_VALUE_MAP.get(int(raw))
        except (TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode back to the device."""
        if option not in MODE_NAME_MAP:
            LOGGER.warning("Unknown TCL mode requested via select: %s", option)
            return
        path = f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}"
        write = getattr(self._matter_client, "write_attribute", None)
        if not callable(write):
            LOGGER.error("matter_client has no write_attribute(); cannot push mode")
            return

        value = MODE_NAME_MAP[option]
        try:
            await write(node_id=self._node_id, attribute_path=path, value=value)
        except TypeError:
            try:
                await write(self._node_id, path, value)
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "write_attribute failed for node=%s mode=%s",
                    self._node_id,
                    option,
                )
                return

        self.coordinator._devices[self._node_id].attributes[ATTR_MODE] = value  # noqa: SLF001
        snapshot = dict(self.coordinator.data or {})
        snapshot.setdefault(self._node_id, {})[ATTR_MODE] = value
        self.coordinator.async_set_updated_data(snapshot)
