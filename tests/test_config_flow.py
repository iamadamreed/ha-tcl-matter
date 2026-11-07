"""Tests for ``custom_components.tcl_matter.config_flow``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tcl_matter.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_user_flow_creates_entry(
    hass: HomeAssistant,
    setup_matter_dependency: MockConfigEntry,
) -> None:
    """A fresh flow with no input creates the single instance entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TCL Matter"
    assert result["data"] == {}


async def test_user_flow_aborts_without_matter(hass: HomeAssistant) -> None:
    """Without the matter integration there is nothing to serve, so abort."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "matter_not_loaded"


async def test_user_flow_rejects_duplicate(hass: HomeAssistant) -> None:
    """With an entry present, single_config_entry aborts a second flow."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="TCL Matter",
        data={},
        unique_id=DOMAIN,
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
