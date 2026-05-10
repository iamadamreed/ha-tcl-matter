# Mainline PR plan — Home Assistant core matter integration

This document is the executable spec for the eventual PR to [`home-assistant/core`](https://github.com/home-assistant/core) that adds first-class TCL Matter dehumidifier support, retiring this custom integration once mainline ships.

## Status

| Repo | Status |
|---|---|
| `matter-js/matterjs-server` | [PR #630](https://github.com/matter-js/matterjs-server/pull/630) **OPEN** — adds `TclDehumidifierCluster` (`0x1334FC03`) decoder, with `mode` as `enum8` + a `TclMode` named-values mapping. Auto-generates the corresponding Python class into `matter-python-client`. Maintainer review (Apollon77) handled 2026-05-10; head is `d7a3632`. |
| `home-assistant/core` matter integration | **BLOCKED on #630** — cannot import `matter_server.common.custom_clusters.TclDehumidifierCluster` until matter-js merges + a `matter-python-client` release ships. Fork prepared at [`iamadamreed/core`](https://github.com/iamadamreed/core); branch `matter-tcl-discovery` reserved for the diff. |

## Why this PR is the real mainline path

`iamadamreed/ha-tcl-matter` is a HACS custom integration. That's the right distribution channel for community use today, but it's not "mainline." The mainline contribution that benefits every TCL Matter dehumidifier owner is **enhancing HA core's built-in matter integration to recognize TCL devices and surface proper entities** — same way it does for spec-compliant Matter humidifiers, lights, etc.

When this PR ships, the custom integration becomes redundant and we can deprecate it.

## Key research findings

(From upfront analysis of `homeassistant/components/matter/` on the `dev` branch.)

- **Discovery schemas live IN each platform file**, not in a `discovery_schemas/` subdirectory. `binary_sensor.py`, `select.py`, `sensor.py`, etc. each export a `DISCOVERY_SCHEMAS` constant. `discovery.py` aggregates them.
- **`MatterDiscoverySchema.required_attributes` takes typed `ClusterAttributeDescriptor` subclasses, not raw integers.** So we reference `TclDehumidifierCluster.Attributes.TargetHumidity`, not `0x1334FC03`.
- **Vendor clusters are first-class** through `matter_server.common.custom_clusters`. Direct precedent: `EveCluster` in `sensor.py`. The discovery engine treats vendor and spec clusters identically.
- **`humidifier.py` does not exist in HA core's matter component today.** This PR is the first Matter→humidifier wiring in HA core. The `humidifier.py` we ship in this custom integration is a clean reference for what mainline `matter/humidifier.py` should look like.
- **No parallel `matter-python-client` PR is needed** — the matter-js TS source auto-generates the Python class on build (verified against `EveCluster` and `HeimanCluster`). Once #630 merges and the next `matter-python-client` release tags, the import works.

## Changes required (mechanical once #630 lands)

### 1. `homeassistant/components/matter/manifest.json`
Bump `matter-python-client` requirement to the version that ships `TclDehumidifierCluster`.

### 2. `homeassistant/components/matter/humidifier.py` (NEW FILE)
First Matter→humidifier platform handler. Model after `homeassistant/components/matter/select.py` for structure.

```python
"""Matter humidifier platform."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from matter_server.common.custom_clusters import TclDehumidifierCluster

from .entity import MatterEntity
from .helpers import get_matter
from .models import MatterDiscoverySchema

# Mode int↔str maps mirror TCL app order:
TCL_MODE_TO_HA = {0: "set", 1: "continue", 2: "comfort", 3: "smart", 4: "dry"}
TCL_MODE_TO_INT = {v: k for k, v in TCL_MODE_TO_HA.items()}

class MatterTclDehumidifier(MatterEntity, HumidifierEntity):
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_available_modes = list(TCL_MODE_TO_HA.values())
    _attr_min_humidity = 35
    _attr_max_humidity = 85

    @property
    def target_humidity(self) -> int | None:
        return self.get_matter_attribute_value(
            TclDehumidifierCluster.Attributes.TargetHumidity
        )

    @property
    def current_humidity(self) -> int | None:
        return self.get_matter_attribute_value(
            TclDehumidifierCluster.Attributes.CurrentHumidity
        )

    @property
    def mode(self) -> str | None:
        raw = self.get_matter_attribute_value(
            TclDehumidifierCluster.Attributes.Mode
        )
        return TCL_MODE_TO_HA.get(raw) if raw is not None else None

    @property
    def is_on(self) -> bool:
        return self.mode is not None

    async def async_set_humidity(self, humidity: int) -> None:
        clamped = max(35, min(85, int(humidity)))
        await self.write_attribute(
            value=clamped,
            matter_attribute=TclDehumidifierCluster.Attributes.TargetHumidity,
        )

    async def async_set_mode(self, mode: str) -> None:
        if mode not in TCL_MODE_TO_INT:
            return
        await self.write_attribute(
            value=TCL_MODE_TO_INT[mode],
            matter_attribute=TclDehumidifierCluster.Attributes.Mode,
        )

DISCOVERY_SCHEMAS = [
    MatterDiscoverySchema(
        platform=Platform.HUMIDIFIER,
        entity_description=...,  # TBD: HumidifierEntityDescription
        entity_class=MatterTclDehumidifier,
        required_attributes=(
            TclDehumidifierCluster.Attributes.TargetHumidity,
            TclDehumidifierCluster.Attributes.Mode,
        ),
        vendor_id=(0x1334,),
    ),
]
```

### 3. `homeassistant/components/matter/discovery.py`
Wire up the new humidifier platform's schemas alongside the existing ones:

```python
from .humidifier import DISCOVERY_SCHEMAS as HUMIDIFIER_SCHEMAS
# ...
DISCOVERY_SCHEMAS: dict[Platform, list[MatterDiscoverySchema]] = {
    # ... existing entries ...
    Platform.HUMIDIFIER: HUMIDIFIER_SCHEMAS,
}
```

### 4. `homeassistant/components/matter/binary_sensor.py`
Append two TCL schemas:

```python
MatterDiscoverySchema(
    platform=Platform.BINARY_SENSOR,
    entity_description=BinarySensorEntityDescription(
        key="MatterTclWaterBucketFull",
        translation_key="water_bucket_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    entity_class=MatterBinarySensor,
    required_attributes=(TclDehumidifierCluster.Attributes.WaterBucketFull,),
    vendor_id=(0x1334,),
),
MatterDiscoverySchema(
    platform=Platform.BINARY_SENSOR,
    entity_description=BinarySensorEntityDescription(
        key="MatterTclFilterAlert",
        translation_key="filter_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    entity_class=MatterBinarySensor,
    required_attributes=(TclDehumidifierCluster.Attributes.FilterAlert,),
    vendor_id=(0x1334,),
),
```

### 5. `homeassistant/components/matter/select.py`
Append a TCL mode select schema (use `MatterAttributeSelectEntity` or a small subclass with the int↔str map).

### 6. `homeassistant/components/matter/sensor.py`
Optional additions for `CurrentHumidity` (likely supplanted by humidifier entity) and `ErrorCodes` JSON sensor.

### 7. `homeassistant/components/matter/strings.json` + `icons.json`
Translation keys for the new entities + icons (use `mdi:water` family for bucket states, `mdi:air-filter` for filter).

### 8. `tests/components/matter/`
- New file `test_humidifier.py` modeled on existing platform tests (e.g. `test_select.py`).
- Captured node JSON snapshot from a real H50D44W under `tests/components/matter/fixtures/nodes/`. Snapshot contents available from `iamadamreed`'s H50D44W via `matter_client.send_command("dump_node", node_id=N)`.
- Test cases: target_humidity reads attr 1, mode maps correctly, set_humidity writes through, bucket_full sensor reflects attr 3, etc.

### 9. PR description must reference the dependency chain
- [matter-js/matterjs-server PR #630](https://github.com/matter-js/matterjs-server/pull/630) (decoder)
- [iamadamreed/ha-tcl-matter](https://github.com/iamadamreed/ha-tcl-matter) (custom integration, slated for deprecation post-merge)
- [iamadamreed/addons](https://github.com/iamadamreed/addons) (live-now patched matter-server)

## Estimated effort post-unblock

A focused day of work. Most of the code is mechanical (mirroring existing vendor schemas), the design decisions are settled, and the test fixture is a one-shot dump.

## When to file

Once **all three** are true:
1. `matter-js/matterjs-server` PR #630 is merged
2. A `matter-python-client` release tagged that re-exports `TclDehumidifierCluster`
3. HA core's `matter-python-client` requirement either already pins that version or this PR bumps it
