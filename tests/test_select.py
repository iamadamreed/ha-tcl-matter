"""Tests for ``custom_components.tcl_matter.select``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tcl_matter.const import (
    ATTR_MODE,
    MODE_VALUE_MAP,
    TCL_CLUSTER_FC03,
)
from custom_components.tcl_matter.select import TclModeSelect

if TYPE_CHECKING:
    from custom_components.tcl_matter.coordinator import TclMatterCoordinator


NODE_ID = 5
EXPECTED_MODE_PATH = f"1/{TCL_CLUSTER_FC03}/{ATTR_MODE}"


DFL_PRODUCT_ID = 0x8002
OTHER_PRODUCT_ID = 0x9999


@pytest.mark.parametrize(
    ("product_id", "raw", "expected"),
    [
        *[
            pytest.param(OTHER_PRODUCT_ID, raw, name, id=f"other-{name}")
            for raw, name in MODE_VALUE_MAP.items()
        ],
        pytest.param(DFL_PRODUCT_ID, 0, "set", id="dfl-set"),
        pytest.param(DFL_PRODUCT_ID, 2, "comfort", id="dfl-comfort"),
        pytest.param(DFL_PRODUCT_ID, 3, "smart", id="dfl-smart-passes-through"),
    ],
)
def test_current_option_maps_correctly(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    product_id: int,
    raw: int,
    expected: str,
) -> None:
    """Each mode integer maps to the matching option name."""
    primed_coordinator.get_node(NODE_ID).device_info.productID = product_id
    primed_coordinator.data[NODE_ID][ATTR_MODE] = raw
    select = TclModeSelect(primed_coordinator, NODE_ID)
    assert select.current_option == expected


@pytest.mark.parametrize(
    ("product_id", "expected"),
    [
        pytest.param(DFL_PRODUCT_ID, ["set", "comfort"], id="dfl"),
        pytest.param(
            OTHER_PRODUCT_ID,
            ["set", "continue", "comfort", "smart", "dry"],
            id="other",
        ),
    ],
)
def test_options_follow_the_product(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
    product_id: int,
    expected: list[str],
) -> None:
    """The DFL-series product offers Set and Comfort; unknown products keep all five."""
    primed_coordinator.get_node(NODE_ID).device_info.productID = product_id
    select = TclModeSelect(primed_coordinator, NODE_ID)
    assert select.options == expected


def test_current_option_none_when_missing(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A missing mode yields None."""
    primed_coordinator.data[NODE_ID].pop(ATTR_MODE)
    select = TclModeSelect(primed_coordinator, NODE_ID)
    assert select.current_option is None


def test_current_option_none_for_unparseable(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A non-int mode yields None."""
    primed_coordinator.data[NODE_ID][ATTR_MODE] = "??"
    select = TclModeSelect(primed_coordinator, NODE_ID)
    assert select.current_option is None


async def test_async_select_option_writes_correct_value(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A known option calls ``write_attribute`` with the matching integer."""
    select = TclModeSelect(primed_coordinator, NODE_ID)
    await select.async_select_option("smart")
    mock_matter_client.write_attribute.assert_awaited_once_with(
        node_id=NODE_ID,
        attribute_path=EXPECTED_MODE_PATH,
        value=3,
    )


async def test_async_select_option_updates_local_cache(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Optimistically applies the new value to the coordinator snapshot."""
    select = TclModeSelect(primed_coordinator, NODE_ID)
    await select.async_select_option("dry")
    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == 4


async def test_select_dedup_skips_when_already_at_value(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """Selecting the option that already matches the cache does NOT round-trip."""
    select = TclModeSelect(primed_coordinator, NODE_ID)
    # primed cache has ATTR_MODE = 0 (set).
    await select.async_select_option("set")
    mock_matter_client.write_attribute.assert_not_called()


async def test_select_raises_on_write_failure(
    primed_coordinator: TclMatterCoordinator,
    mock_matter_client: MagicMock,
) -> None:
    """A failing write raises to the caller and leaves the cache untouched."""
    mock_matter_client.write_attribute = AsyncMock(side_effect=RuntimeError("boom"))
    select = TclModeSelect(primed_coordinator, NODE_ID)
    before = primed_coordinator.data[NODE_ID][ATTR_MODE]

    with pytest.raises(HomeAssistantError):
        await select.async_select_option("comfort")

    assert primed_coordinator.data[NODE_ID][ATTR_MODE] == before
