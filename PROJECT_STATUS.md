# PROJECT_STATUS — TCL Matter Integration

**Last updated:** 2026-05-09
**Property:** 2504 Canyon Bay
**Owner:** Adam Reed (`iamadamreed`)

---

## Bottom line

- **Goal:** Get the TCL H50D44W dehumidifier fully integrated with HA for mold prevention — bucket-full alerts, tamper self-healing, full read/write of target humidity + mode. Build it RIGHT, no legacy/maintenance shortcuts.
- **State today:** Reads work end-to-end via matter.js. All read-side automations live (bucket-full alerts persistent every 30 min, offline detection, tampering detection, AC dehumidify demoted to backup). Writes silently no-op pending upstream PR.
- **Blocked on:** Upstream [matter-js/matterjs-server PR #630](https://github.com/matter-js/matterjs-server/pull/630) to register TLV types for TCL vendor cluster `0x1334FC03`. Until merged + propagated to the HA addon, write_attribute can't serialize. PR is OPEN, MERGEABLE, no review activity yet.
- **Next concrete step:** Wait on PR #630. When it merges → matter-server npm release → HA addon image build (~1 week total) → writes start working with no integration code changes. At that point: enable the auto-restore action in `mold_prevention_dehumidifier_tampered`, end-to-end test that physical-button changes get reverted by HA.

---

## 1. The actual goal

Adam's TCL H50D44W is the primary mold-prevention path for 2504 Canyon Bay (replacing AC-as-dehumidifier, which fails in mild weather). Hard requirements:

1. **Bucket-full notifications** — persistent, repeating until bucket is emptied.
2. **Tampering self-healing** — if a kid presses buttons on the unit, HA notices and resets target/mode to canonical values.
3. **Full read/write** — target humidity and operating mode controllable from HA, not read-only.

Adam's directive: *"we are NOT aiming for a legacy or maintenance integration, build this RIGHT."* That ruled out the unofficial cloud integration (`nemesa/ha-tcl-home-unofficial-integration`) and pushed us to local Matter via the unit's Matter commissioning support.

---

## 2. Current state on Adam's HA (192.168.2.107)

### Matter Server addon
- Version **8.4.0**
- **`beta=true`** flipped on → addon now runs **matter.js (TypeScript)**, not python-matter-server (legacy).
- TCL device migrated cleanly: `fabric_id=2`, `node_id=5`.

### Custom integration
- Deployed at `/config/custom_components/tcl_matter/` (manual install — see HACS note below).
- Coexists with built-in `matter` integration on the same device card via `("matter", str(node_id))` identifier.

### Live entities
| Entity | Value (last read) | Notes |
|---|---|---|
| `humidifier.tcl_dehumidifier` | target=45, current=52, mode=`set` | dehumidifier device class |
| `binary_sensor.tcl_dehumidifier_water_bucket_full` | off | |
| `binary_sensor.tcl_dehumidifier_filter_alert` | off | |
| `select.tcl_dehumidifier_mode` | set | |
| `sensor.tcl_dehumidifier_current_humidity` | 52% | |
| `sensor.tcl_dehumidifier_error_codes` | 0 | |
| `fan.tcl_dehumidifier` | (built-in) | OnOff + FanControl writes work today |

### HACS
- **Removed.** tcl_matter is manually installed; its dependencies aren't HACS-distributed. Don't reinstall HACS for this project.

### Mold-prevention automations (live)
| Automation | Behavior |
|---|---|
| `mold_prevention_dehumidifier_bucket_full` | Repeats every 30 min while bucket sensor is on |
| `mold_prevention_dehumidifier_offline` | Notify after 10 min unavailable |
| `mold_prevention_dehumidifier_tampered` | Alerts when target≠45 or mode∉{'set','continue'}. Hardcoded thresholds (helpers approach was scrapped). Auto-restore activates after PR #630 |
| `mold_prevention_ac_dehumidify` | **Demoted** — only fires if TCL is unavailable >5 min |

---

## 3. Resolved — helpers approach scrapped

Originally planned `input_number.dehumidifier_target_humidity` + `input_select.dehumidifier_mode` helpers to make the canonical target/mode user-configurable. The REST API for user helpers returned 404 and rather than fight that, the tampering automation now hardcodes `45%` and accepts modes `set` or `continue` directly in the template. Adam can edit those values inline if he wants different canonical setpoints — small enough to not need helper plumbing.

---

## 4. Repos & forks

| Repo | URL | Local clone | Purpose |
|---|---|---|---|
| `ha-tcl-matter` | https://github.com/iamadamreed/ha-tcl-matter | `/Users/smarter/dev/family/house/2504canyonbay/integrations/ha-tcl-matter/` | Custom HA integration. Public, MIT, **v0.1.0** released. **112 tests passing at 89% coverage.** |
| `matterjs-server` (fork) | https://github.com/iamadamreed/matterjs-server | `/Users/smarter/dev/family/house/2504canyonbay/integrations/matterjs-server/` | Branch `add-tcl-vendor-cluster` — source of PR #630 |
| `python-matter-server` (fork) | https://github.com/iamadamreed/python-matter-server | (deleted locally, **archived on GitHub**) | Forked before we discovered upstream had moved to matter.js. Archived as part of legacy cleanup. |

### CI status (ha-tcl-matter)
- ✅ **Test workflow:** passing (112 tests, 89% coverage).
- ✅ **Lint (ruff):** passing — only formatter-incompat + ANN401 ignored; the 36 real warnings were FIXED (named constants, message-to-variable for raises, narrowed excepts) not silenced.
- ✅ **Validate (hassfest + HACS):** passing — repo topics added (`home-assistant`, `homeassistant`, `hacs`, `matter`, `tcl`, `dehumidifier`, `iot`, `home-automation`, `python`).

---

## 5. Upstream PR in flight

**[matter-js/matterjs-server PR #630](https://github.com/matter-js/matterjs-server/pull/630)** — adds:
- `TclDehumidifierCluster` (`0x1334FC03`) — control/state
- `TclPrivateCluster` (`0x1334FC00`) — opaque

Tagged `@marcelveldt`, `@agners`, `@Apollon77`. Awaiting review. Heiman/Inovelli vendor-cluster precedents merged in **3-day median**.

License: **Apache 2.0** (matches matterjs-server's existing license).

---

## 6. What works today vs. after PR #630

| Capability | Today | After PR #630 |
|---|---|---|
| Read target humidity, current humidity, mode, bucket, filter, errors | OK | OK (typed instead of path-keyed) |
| Write target humidity from HA | **silently no-ops** | OK |
| Write mode from HA | **broken** | OK |
| Bucket-full notifications | OK | OK |
| Offline alert | OK | OK |
| Tampering detection alert | OK | OK |
| Tampering auto-restore | **commented out** | OK (uncomment) |
| OnOff toggle from HA | OK (via `fan.tcl_dehumidifier`) | OK |

---

## 7. Architecture decisions (and why)

- **Custom HACS integration coexists with built-in `matter`.** matter integration handles pairing + the standard Fan/OnOff/FanControl entities; `tcl_matter` reads the vendor cluster and creates `humidifier`/`sensor`/`binary_sensor`/`select`. Same device card via `("matter", str(node_id))`.
- **matter.js (TypeScript) over python-matter-server (legacy).** Legacy README explicitly says: *"maintenance mode — all new features land in matter.js."* HA addon 8.4.0 already supports `beta=true` to flip. We're on the forward-looking codebase.
- **Read path uses `node.node_data.attributes` path-keyed dict.** Vendor cluster TLV types aren't registered until PR #630 merges, so `MatterNode.get_attribute_value` returns `None` for vendor attrs. The raw path-keyed dict bypasses typed lookup.
- **Write path silently no-ops today.** Same root cause — without TLV type registration, `write_attribute` can't serialize the bytes. Resolved by PR #630.
- **Apache 2.0 on the cluster decoder PR** to match matterjs-server's license.

---

## 8. How to resume after a break

### Verify state
```bash
ssh -i ~/.ssh/id_ed25519 root@192.168.2.107 'ls /config/custom_components/'   # should show only tcl_matter
gh pr view 630 --repo matter-js/matterjs-server                                # upstream status
```

### Pull both forks
```bash
cd /Users/smarter/dev/family/house/2504canyonbay/integrations/ha-tcl-matter
git pull

cd /Users/smarter/dev/family/house/2504canyonbay/integrations/matterjs-server
git fetch upstream main
git fetch origin add-tcl-vendor-cluster
```

### Run tests
```bash
cd /Users/smarter/dev/family/house/2504canyonbay/integrations/ha-tcl-matter
source .venv/bin/activate
python -m pytest tests/   # 112 should pass
```

### Tail matter-server addon log
```bash
curl -sS -H "Authorization: Bearer $HA_TOKEN" -H "Accept: text/plain" \
  http://192.168.2.107:8123/api/hassio/addons/core_matter_server/logs?lines=50
```

### When PR #630 merges
1. matter-server npm release ships (~days after merge).
2. HA addon picks up next image build (~1 week after npm release).
3. Restart matter-server addon on HA → typed cluster attrs become available.
4. Update `tcl_matter` to import `TclDehumidifierCluster.Attributes.TargetHumidity` etc. instead of raw path strings. Internal change; entity IDs stay the same.
5. Uncomment auto-restore actions in `mold_prevention_dehumidifier_tampered`.
6. End-to-end test: change target humidity in HA UI → verify the unit's display changes.

---

## 9. Questions for Adam (manual confirmation)

- **Mode integer mapping** — confirm provisional: `0=set / 1=continue / 2=comfort / 3=smart / 4=dry`. Walk through each mode in the TCL Home app while watching attr 0 on the device.
- **Canonical tampering values** — currently `45%` target, `'set'` mode. Confirm or override.

---

## 10. Outstanding tasks (priority order)

1. **Fix the helpers.** Create `input_number.dehumidifier_target_humidity` + `input_select.dehumidifier_mode` via UI or `configuration.yaml` so the tampering automation resolves.
2. **Wait for PR #630.** When it merges, follow §8 "When PR #630 merges."
3. **Update `tcl_matter` to typed cluster references** once writes work.
4. **(Optional follow-up)** Open architecture discussion at `home-assistant/architecture/discussions` for adding a humidifier platform to HA's matter integration. Long-tail; not blocking.
5. **(Optional follow-up)** PR `home-assistant/core` matter integration with discovery schemas (`number` for target humidity, `sensor` for current humidity, `binary_sensor` for bucket, `select` for mode). When this lands, the standalone `tcl_matter` HACS integration becomes redundant — mark legacy and link users upstream.

---

## 11. Reference data

| Item | Value |
|---|---|
| TCL Vendor ID | `0x1334` (4916 decimal) |
| Product ID | `0x8002` |
| Cluster IDs | `0x1334FC03` (control/state), `0x1334FC00` (opaque) |
| IPv6 ULA prefixes (UDM Pro) | `fd00:abcd:1234:1::/64` Default, `:2::/64` Services, `:3::/64` Devices |
| Matter Server addon | 8.4.0, `beta=true` (matter.js mode) |
| HA Core | 2026.5.1 |
| Test framework | `pytest-homeassistant-custom-component==0.13.300` on Python 3.14 |
| Fabric / node | fabric_id=2, node_id=5 |
