# TCL Matter — Home Assistant Integration

[![hacs][hacs_badge]][hacs]
[![License][license_badge]][license]

Home Assistant integration that surfaces **target humidity, current humidity, mode, and water-bucket-full** sensors for TCL Matter dehumidifiers.

## Why this exists

TCL ships dehumidifiers (e.g. **H50D44W**, **H50D66KW**) as Matter-over-Wi-Fi devices, but registers them with the CSA as a generic **Fan** device type. Home Assistant's built-in Matter integration follows the spec literally and exposes only `fan.*` (on/off + speed) — losing the actual dehumidifier features.

The dehumidifier-specific data **is** present on the device — just inside TCL's vendor-specific Matter clusters (`0x1334FC00`, `0x1334FC03`) that no generic Matter ecosystem decodes. This integration reads those clusters via the existing Matter pairing and exposes proper entities.

## Features

- 💧 `humidifier.tcl_dehumidifier` — target humidity (35–85 %), mode select
- 📊 `sensor.tcl_dehumidifier_current_humidity` — ambient RH from the unit's onboard sensor
- 🪣 `binary_sensor.tcl_dehumidifier_water_bucket_full` — alerts when bucket fills
- ⚠️ `sensor.tcl_dehumidifier_error_codes` — diagnostic
- 🎛️ `select.tcl_dehumidifier_mode` — direct mode control (Set / Continue / Comfort / Smart / Dry)

## Requirements

- Home Assistant **2026.5.0** or newer
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
| TCL H50D66KW | `0x1334` | `0x8002` | Likely (same family — please report) |

If you have a different TCL Matter dehumidifier, [open an issue][issue_tracker] with the model + vendor/product IDs.

## Architecture notes

- Coexists with the built-in Matter integration on the same device card via shared `("matter", node_id)` device identifier.
- Reads/writes attributes through the loaded `matter_client` — no separate Matter pairing, no cloud, no TCL Home dependency.
- **Live reads, not stale cache.** Vendor cluster attributes are fetched fresh from the matter-server itself via `matter_client.send_command("read_attribute", …)` — bypassing the python-matter-server local cache (which is never refreshed for clusters it lacks decoders for). Subscribes to push updates in parallel; the 30-second poll is a safety net.
- **Anti-loop write semantics.** Each writable attribute has a per-instance `asyncio.Lock`, and writes are deduplicated against the cached value. An automation that fires `set_humidity(45)` 100 times against a device already at 45 results in zero device round trips — the integration cannot be the source of a runaway loop.

## Server-side requirement

This integration depends on the matter-server having a decoder registered for TCL's vendor clusters (`0x1334FC03`). Two paths get you there:

1. **Wait for upstream.** [matter-js/matterjs-server PR #630](https://github.com/matter-js/matterjs-server/pull/630) ships the decoder. Once merged + released into the official `core_matter_server` add-on image, no extra work is needed.
2. **Run the patched add-on now.** [github.com/iamadamreed/addons](https://github.com/iamadamreed/addons) ships a Matter Server add-on with the decoder pre-bundled. Add the repo to Home Assistant → Settings → Add-ons → 3-dot menu → Repositories, install, and point the built-in Matter integration at it.

## Contributing

PRs welcome. The cluster decoder is also being upstreamed to [`home-assistant-libs/python-matter-server`](https://github.com/home-assistant-libs/python-matter-server) so future TCL Matter products work out of the box.

## License

MIT — see [LICENSE](LICENSE).

[hacs]: https://hacs.xyz
[hacs_badge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license]: ./LICENSE
[license_badge]: https://img.shields.io/github/license/iamadamreed/ha-tcl-matter.svg?style=for-the-badge
[issue_tracker]: https://github.com/iamadamreed/ha-tcl-matter/issues
