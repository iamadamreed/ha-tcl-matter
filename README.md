# TCL Matter — Home Assistant Integration

[![hacs][hacs_badge]][hacs]
[![License][license_badge]][license]

Home Assistant integration that surfaces **target humidity, current humidity, mode, and water-bucket-full** sensors for TCL Matter dehumidifiers.

## Why this exists

TCL ships dehumidifiers (e.g. **H50D44W**, **H50D66KW**) as Matter-over-Wi-Fi devices, but registers them with the CSA as a generic **Fan** device type. Home Assistant's built-in Matter integration follows the spec literally and exposes only `fan.*` (on/off + speed) — losing the actual dehumidifier features.

The dehumidifier-specific data **is** present on the device — just inside TCL's vendor-specific Matter cluster `0x1334FC03` that no generic Matter ecosystem decodes. This integration reads that cluster via the existing Matter pairing and exposes proper entities.

## Features

Entity names below are shown as they appear in the UI; entity IDs are generated from the device name and depend on what your unit is called.

- 💧 **Dehumidifier** (`humidifier`) — target humidity (35–85 %), mode, and on/off from the real power state (Matter OnOff cluster)
- 📊 **Current humidity** (`sensor`) — ambient RH from the unit's onboard sensor
- 🪣 **Water bucket** (`binary_sensor`) — alerts when the bucket fills (reads error code 5 on product ID `0x8002`; falls back to the dedicated bool for any firmware that ever wires it up)
- 🚰 **Pump** (`switch`, pump models only) — the same setting as the Pump button on the panel. With it on, the unit pumps water out through its drain hose once the bucket is almost full. Writing it moves the pump light and the unit beeps, as it does for the button. Pump models are recognised by the feature set containing `1` (`[1,3]` on a T50DC9SPB, `[3]` on a model without a pump); that is inferred from two units, not documented by TCL
- ⚠️ **Error codes** (`sensor`, diagnostic) — known codes: **5 = water bucket full**
- 🎛️ **Mode** (`select`) — Set or Comfort on the DFL-series units (product ID `0x8002`: T50DC9SPB, H50D44W). The unit accepts the other three values but falls back to Comfort a few seconds later, and its control panel has no such modes (TCL's DFL-Series manual: "Continuous" is the lowest humidity setting, not a mode). Products not listed in `PRODUCT_MODES` offer all five (Set / Continue / Comfort / Smart / Dry).
- 🔗 The device is linked to the built-in Matter device ("connected via"). HA 2026 keeps one device per integration, so the two cannot be merged into one card

## Requirements

- Home Assistant **2026.10.0** or newer (the version the test suite runs against)
- The TCL dehumidifier already paired to the built-in Matter integration
- HACS installed

## Installation

### Via HACS (recommended)

1. HACS → 3-dot menu → **Custom repositories** → add `https://github.com/iamadamreed/ha-tcl-matter` (Category: *Integration*)
2. HACS → search "**TCL Matter**" → Install
3. Restart Home Assistant
4. Settings → Devices & Services → Add Integration → "**TCL Matter**"

### Manual install

Copy `custom_components/tcl_matter/` into your `<config>/custom_components/` directory, restart, then add the integration via the UI.

## Pairing a TCL dehumidifier first

This integration **requires the device to already be paired via the built-in Matter integration**. The pairing code is on a sticker on the unit (look for the Matter `∗` logo + 11-digit code).

> ⚠️ **Matter requires IPv6 routing on your LAN.** This is a Matter spec requirement, not specific to TCL. If pairing fails with `Network is unreachable` in the Matter Server addon log, your network is IPv4-only and Matter cannot operate. The fix is to enable IPv6 on every VLAN that needs to reach Matter devices — typically with a ULA prefix from `fd00::/8` plus SLAAC + Router Advertisements. Most consumer routers support this (look for "IPv6 LAN" / "Local IPv6" / "ULA" settings); see your router's documentation. If your router only supports DHCP-PD from your ISP and your ISP doesn't provide IPv6, you can still configure a static ULA prefix locally.

> ⚠️ **mDNS must reach across VLANs.** If Home Assistant and your Matter device are on different VLANs, ensure your router has an mDNS reflector / repeater enabled and that inter-VLAN ICMPv6 (Neighbor Discovery) is permitted. Without these, Matter discovery silently fails.

## Tested devices

| Model | Vendor ID | Product ID | Status |
|---|---|---|---|
| TCL H50D44W | `0x1334` | `0x8002` | ✅ Verified |
| TCL T50DC9SPB (50 pint, with pump) | `0x1334` | `0x8002` | ✅ Verified (firmware 1.0, hardware 1; mode, humidity, power and pump) |
| TCL H50D66KW | `0x1334` | `0x8002` | Likely (same family — please report) |

If you have a different TCL Matter dehumidifier, [open an issue][issue_tracker] with the model + vendor/product IDs.

## Architecture notes

- Runs alongside the built-in Matter integration. Each TCL node gets its own device (identifier `("tcl_matter", "<fabric>-<node>")`), linked to the Matter device with `via_device_id`. Devices created by 0.5.x under the `("matter", "<node>")` identifier are migrated in place on upgrade, keeping their area and name.
- Reads/writes attributes through the loaded `matter_client` — no separate Matter pairing, no cloud, no TCL Home dependency.
- **Live reads, not stale cache.** Vendor cluster attributes are fetched fresh from the matter-server itself with `matter_client.read_attribute(…)`, bypassing the client's local cache (which is not refreshed for clusters it lacks decoders for). Each attribute also has its own push subscription, and a 60-second poll is the safety net. Every round trip has a timeout, and a node is marked unavailable after two failed polls.
- **Anti-loop write semantics.** Writes to one attribute are serialised by a lock, and a write is skipped when a live read shows the device already holds the value (the cache is not trusted for this, since it can lag a change made at the unit). An automation that fires `set_humidity(45)` 100 times against a device already at 45 sends no writes. A write the device rejects, or that times out, raises an error instead of being cached as if it worked.
- **Lifecycle.** The entry reloads itself when the Matter integration reloads (it replaces its client), and when a TCL node is added or removed.

## Server-side requirement

The matter-server must decode TCL's vendor cluster (`0x1334FC03`) and the Matter client in Home Assistant must know it. The client has had the decoder since `matter-python-client` 1.3.0, which every supported Home Assistant version ships. The server side is the TCL decoder from [matter-js/matterjs-server PR #630](https://github.com/matter-js/matterjs-server/pull/630). The official Matter Server app includes it from 1.5.5 (matter.js 0.18.0), which is what the verified unit runs. On an older server, the maintainer's patched app [github.com/iamadamreed/addons](https://github.com/iamadamreed/addons) bundles the decoder.

## Contributing

PRs welcome. The cluster decoder is also being upstreamed to [`home-assistant-libs/python-matter-server`](https://github.com/home-assistant-libs/python-matter-server) so future TCL Matter products work out of the box.

## License

MIT — see [LICENSE](LICENSE).

[hacs]: https://hacs.xyz
[hacs_badge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license]: ./LICENSE
[license_badge]: https://img.shields.io/github/license/iamadamreed/ha-tcl-matter.svg?style=for-the-badge
[issue_tracker]: https://github.com/iamadamreed/ha-tcl-matter/issues
