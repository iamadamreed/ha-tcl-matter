# PROJECT_STATUS — TCL Matter Integration

**Last updated:** 2026-05-10
**Property:** 2504 Canyon Bay
**Owner:** Adam Reed (`iamadamreed`)
**Current release:** [v0.4.2](https://github.com/iamadamreed/ha-tcl-matter/releases/tag/v0.4.2)

---

## Mainline / upstream chain

The full path to retiring this custom integration in favour of first-class HA core support:

| Step | Repo | Status |
|---|---|---|
| 1. Server-side cluster decoder | `matter-js/matterjs-server` | **[PR #630 OPEN](https://github.com/matter-js/matterjs-server/pull/630)** — branch `add-tcl-vendor-cluster` in [iamadamreed/matterjs-server](https://github.com/iamadamreed/matterjs-server). **Maintainer review handled** (Apollon77, 2026-05-10) — diagnostic dump posted, all 5 inline review threads addressed in commits `91f79b2` and `d7a3632` (PR head) and resolved. |
| 2. matter-python-client release | (auto from #630) | Pending — auto-generated when #630 builds. |
| 3. Live-now patched addon | [iamadamreed/addons](https://github.com/iamadamreed/addons) | **Live in production** at `8.4.0-tclpatch.4`. Retires when steps 1+2 land. |
| 4. HA core matter integration discovery PR | [iamadamreed/core](https://github.com/iamadamreed/core/tree/matter-tcl-discovery) | **Plan ready** — see [MAINLINE_PR_PLAN.md](./MAINLINE_PR_PLAN.md). Branch `matter-tcl-discovery` reserved. Filing blocked on steps 1+2. |
| 5. This custom integration | `iamadamreed/ha-tcl-matter` | **Live for HACS users today at v0.4.1.** Deprecates once step 4 ships. |

---

## What works today (end-to-end verified on H50D44W)

- **Read** — `humidifier.tcl_dehumidifier`, `binary_sensor.tcl_dehumidifier_water_bucket_full`, `binary_sensor.tcl_dehumidifier_filter_alert`, `select.tcl_dehumidifier_mode`, `sensor.tcl_dehumidifier_current_humidity`, `sensor.tcl_dehumidifier_error_codes` all reflect live device truth via `matter_client.read_attribute` (no stale cache).
- **Write** — target humidity and mode writes land on the device and persist across re-reads. The dedicated dehumidifier-enforcer automation pushes `input_number.target_humidity` to the unit on change or every 10 minutes.
- **Bucket alert** — fires within seconds of bucket fill; persistent notification.
- **Anti-loop** — per-attribute `asyncio.Lock` plus write deduplication. The integration cannot be the source of a runaway loop.

---

## v0.4.2 — bucket-full sensor reads error code 5

**Empirical finding (2026-05-11):** on the **TCL H50D44W** the dedicated `waterBucketFull` bool (cluster `0x1334FC03`, attr 3) is **dead** — it stays `false` even when the bucket is physically full and the unit has stopped. The only attribute that flips on bucket fill/empty is `errorCodes` (attr 5) going from `"[]"` ↔ `"[5]"`. Verified by running a polling watcher across a full bucket-empty-reinsert cycle: only `errorCodes` (and one point of `currentHumidity` measurement noise) changed.

`TclBucketFullBinarySensor.is_on` now returns `True` when **either** `attr 3` is true **or** `5` is in the parsed `error_codes` list. Defensive OR so any future TCL firmware that wires up attr 3 still works. Added `ERROR_CODE_BUCKET_FULL = 5` constant in `const.py`. Tests cover all combinations (139 passing at 91.3 % coverage).

## v0.4.1 architecture (current)

`v0.3.0` polled `node.node_data.attributes` (the python-matter-server local cache). For vendor clusters with no client-side decoder, that cache is populated only at commissioning and never refreshed — push events fire, but the cache itself stays stale forever. Every poll cycle clobbered our optimistic-cached writes with the wrong original value, triggering an auto-restore loop that wrote the canonical value once per poll interval forever.

**v0.4.0 fixed this at the root.** `matter_ws.py` owns two single-purpose helpers:

- `live_read_attribute(matter_client, node_id, path)` — issues `matter_client.read_attribute(...)`, going straight to the matter-server WS and returning device truth. No client-side cache, no decoder dependency.
- `live_write_attribute(matter_client, node_id, path, value)` — same channel, same bypass.

`coordinator.py`, `humidifier.py`, and `select.py` share these helpers — there is exactly one path for matter I/O.

**Anti-loop write semantics** at the integration layer:

- **Per-attribute `asyncio.Lock`** serialises concurrent writes to the same attribute.
- **Write deduplication** under the lock: if the requested value matches the cached value, the round trip is skipped.

**v0.4.1** added friendlier label translations for the bucket and filter binary sensors (`Empty / Full`, `OK / Needs attention`).

Tests: **125 passing, 91.56 % coverage**. `test_matter_ws.py` covers the helpers directly; `test_humidifier.py` and `test_select.py` exercise dedup + concurrent-lock behaviour explicitly.

---

## Maintainer feedback — PR #630

Apollon77 (matter.js collaborator) reviewed on 2026-05-10 and left one top-level review plus five inline comments. All addressed in commits `91f79b2` (initial response) and `d7a3632` (tightening per maintainer's implicit standards). All five review threads marked resolved.

| Reviewer ask | Resolution |
|---|---|
| Top review: "Please provide a diagnostic dump of such a device that I can verify the datatypes and details." | Posted [issue comment #4416017065](https://github.com/matter-js/matterjs-server/pull/630#issuecomment-4416017065) — formatted summary of `BasicInformation`, `Descriptor` on endpoint 1, all 7 vendor-cluster data attributes with live values + types, plus `AttributeList` confirming the PR's cluster definition matches the device 1:1. Serial redacted; MAC not included. |
| Follow-up (2026-05-11): "Can you please just attach the plain diagnostic JSON file ... values not post-processed by AI." | Posted [issue comment #4421202513](https://github.com/matter-js/matterjs-server/pull/630#issuecomment-4421202513) linking the raw HA matter integration diagnostics JSON as a public gist ([gist/e96a537](https://gist.github.com/iamadamreed/e96a537639f5bbddf75085d612783995)). Only the device serial number is redacted; everything else is verbatim from HA's diagnostics export. |
| Inline (mode attr): "Should we define that as real enum?" | **Done.** Switched `mode` from `uint8` to `enum8` and bound a `const enum TclMode { Set=0, Continue=1, Comfort=2, Smart=3, Dry=4 }` alongside the cluster (`d7a3632`). No regression in the auto-generated Python client (`Optional[uint]` either way). |
| Inline (errorCodes / featureSet): "really a json encoded string? Or a real array of numbers?" / "string?" / "string or array?" | Verified by live read: device emits literal text `'[]'` and `'[3]'` on the wire (JSON-encoded strings), not Matter list TLVs. Modeling them as `array[uint16]` would tell matter.js to expect a list-TLV header that doesn't exist and would break reads. Kept as `string`; JSDoc strengthened to make the JSON-string-vs-list distinction explicit and to direct consumers to JSON-parse application-side. |
| Inline (TclPrivateCluster): "Do we need to define it here when we have no clue what it means?" | **Dropped** in `d7a3632`. Apollon77's implicit point was right — declaring a cluster whose contents we can't interpret adds noise without signal. The cluster still appears in the device's `Descriptor.ServerList`, but matter.js's default handling is enough. If/when the vendor-prefixed attribute's contents are identified, it can return as a follow-up PR with the right type. |

The diagnostic dump confirmed:
- Vendor 0x1334 / Product 0x8002 / Software 1.0.
- Device type **0x002B (Fan)** on endpoint 1 — exactly the misregistration the PR addresses.
- `AttributeList` on `0x1334FC03` is `[0..6, 65528..65533]` — every attribute the PR defines, no extras.
- All 7 data attributes (`mode`, `targetHumidity`, `currentHumidity`, `waterBucketFull`, `filterAlert`, `errorCodes`, `featureSet`) read with the types declared in the PR.

**Net change:** PR scope tightened — single `TclDehumidifierCluster` decoder, `mode` now a real `enum8` with named values, no speculative cluster. Commit `d7a3632` is the current PR head.

---

## Stupid-simple HA automation architecture (post v0.4)

After several iterations of over-engineered state machines (4 automations, drift detection, auto-restore, tampering alerts), the design is now **two helpers + two enforcers + one alert**:

| Helper | Default | Purpose |
|---|---|---|
| `input_number.target_temperature` | 74 °F | Single AC setpoint; range 65–85, step 0.5. |
| `input_number.target_humidity` | 50 % | Single dehumidifier setpoint; range 35–65, step 1. |
| `input_boolean.mold_prevention_enabled` | on | Master kill-switch for both enforcers. |

| Automation | Behaviour |
|---|---|
| `automation.climate_summer_cool` | Bang-bang AC on `sensor.trisensor_8_air_temperature` (bedroom) with 0.5 °F hysteresis. Bedroom-only because the entrance thermostat reading is biased by dehumidifier exhaust. Anti-spam: the service call only fires when the resulting setpoint would actually change. |
| `automation.dehumidifier_enforcer` | On change of `input_number.target_humidity` OR every 10 min, writes the helper value to the device. Integration's write-dedup makes no-op rewrites cheap. |
| `automation.mold_prevention_dehumidifier_bucket_full` | Persistent notification every 30 min while `binary_sensor.tcl_dehumidifier_water_bucket_full` is on. |

Everything else (dual-sensor heat, fan-mode dispatcher, climate_apply_settings, mold_prevention_ac_dehumidify / restore_normal / watchdog / disabled, the 4-automation TCL state machine, auto-restore, tampered alerts, offline alert, 7 helpers) was deleted.

**Why bedroom-only AC trigger:** the dehumidifier sits near the entrance thermostat. Its dry-air exhaust biases the thermostat reading 3-5 °F warm, which previously caused the AC to over-cool the bedroom while the entrance read at setpoint.

**Why no heat path:** summer-only operation. If we add heat in winter, it'll be a separate, equally-simple automation.

---

## Repos & forks

| Repo | URL | Local clone | Purpose |
|---|---|---|---|
| `ha-tcl-matter` | https://github.com/iamadamreed/ha-tcl-matter | `integrations/ha-tcl-matter/` | Custom HA integration. Public, MIT, **v0.4.1 released**. 125 tests, 91.56 % coverage. |
| `matterjs-server` (fork) | https://github.com/iamadamreed/matterjs-server | `integrations/matterjs-server/` | Branch `add-tcl-vendor-cluster` — source of PR #630. |
| `addons` (fork) | https://github.com/iamadamreed/addons | `integrations/ha-addons/` | Branch `master` — ships `matter_server` add-on `8.4.0-tclpatch.4` with the cluster decoder pre-bundled. |
| `core` (fork) | https://github.com/iamadamreed/core | (not cloned locally) | Branch `matter-tcl-discovery` reserved for the eventual mainline PR (see [MAINLINE_PR_PLAN.md](./MAINLINE_PR_PLAN.md)). |
| `python-matter-server` (fork) | https://github.com/iamadamreed/python-matter-server | (deleted locally, **archived on GitHub**) | Forked before we discovered upstream had moved to matter.js. Archived as part of legacy cleanup. |

### CI status (ha-tcl-matter)

- Test workflow passing (125 tests, 91.56 % coverage).
- Lint (ruff) passing.
- Validate (hassfest + HACS) passing.

---

## Outstanding tasks

1. **Wait for PR #630 review follow-up.** Maintainer received the diagnostic dump 2026-05-10; respond to any further requests.
2. **Once #630 merges:** new `matter-python-client` release will auto-publish; HA core's matter integration can then `import TclDehumidifierCluster`.
3. **File the mainline HA core PR** per [MAINLINE_PR_PLAN.md](./MAINLINE_PR_PLAN.md). Adds `humidifier.py` (first Matter→humidifier platform), discovery schemas in `binary_sensor.py` / `select.py` / `sensor.py`, translations, and a node fixture.
4. **Once mainline ships:** mark this custom integration deprecated in `README.md`; pin a final HACS release that points users at HA core.
5. **Retire the addon fork** — uninstall `fa40c075_matter_server` and remove the `iamadamreed/addons` repo from HA → reinstall the official `core_matter_server`.

---

## How to resume after a break

```bash
# Pull all forks
cd integrations/ha-tcl-matter && git pull
cd ../matterjs-server      && git fetch upstream main && git fetch origin add-tcl-vendor-cluster
cd ../ha-addons            && git fetch upstream master && git fetch origin master

# Run tests
cd integrations/ha-tcl-matter
source .venv/bin/activate
python -m pytest tests/   # 125 should pass

# Upstream status
gh pr view 630 --repo matter-js/matterjs-server

# Live state on Adam's HA
PATH="$HOME/.local/bin:$PATH" uvx --quiet --with websockets python3 /tmp/diag_dump.py
```

---

## Reference data

| Item | Value |
|---|---|
| TCL Vendor ID | `0x1334` (4916 decimal) |
| Product ID | `0x8002` |
| Cluster ID | `0x1334FC03` (dehumidifier control/state) — single cluster, scope reduced from two after maintainer review on PR #630 |
| Fabric / node (Adam's setup) | fabric_index=2, node_id=5 |
| Patched addon slug | `fa40c075_matter_server` (hostname `fa40c075-matter-server`) |
| HA Core | 2026.5.1 |
| Test framework | `pytest-homeassistant-custom-component==0.13.300` on Python 3.14 |
