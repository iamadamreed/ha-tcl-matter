"""
Config flow for TCL Matter.

Single-instance, no user input. The integration auto-discovers TCL nodes
from the built-in matter integration at runtime, so there is nothing to
configure during setup. We use a fixed unique_id (the domain itself) to
prevent multiple entries.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class TclMatterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TCL Matter."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle the only step: confirm and create the single entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="TCL Matter", data={})
