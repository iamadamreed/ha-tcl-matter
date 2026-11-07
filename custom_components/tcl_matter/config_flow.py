"""
Config flow for TCL Matter.

Single instance, no user input. The integration finds TCL nodes from the
built-in matter integration at runtime, so there is nothing to configure.
``single_config_entry`` in the manifest stops a second entry.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, MATTER_DOMAIN


class TclMatterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TCL Matter."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Create the single entry, once the matter integration is set up."""
        if not self.hass.config_entries.async_entries(MATTER_DOMAIN):
            return self.async_abort(reason="matter_not_loaded")
        return self.async_create_entry(title="TCL Matter", data={})
