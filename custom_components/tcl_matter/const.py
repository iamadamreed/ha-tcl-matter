"""
Constants for the TCL Matter integration.

Empirical mapping of TCL vendor-specific Matter clusters discovered on
TCL H50D44W dehumidifier (VendorID 0x1334). All values were observed by
walking the device's attribute tree; semantics for the TODO items still
need empirical confirmation.
"""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "tcl_matter"

LOGGER: Final = logging.getLogger(__package__)

# TCL vendor identifier (from BasicInformation cluster, endpoint 0)
TCL_VENDOR_ID: Final = 0x1334  # 4916

# Vendor-specific cluster ID (endpoint 1 on the dehumidifier)
TCL_CLUSTER_FC03: Final = 0x1334FC03  # primary control/state cluster

# Attribute IDs on TCL_CLUSTER_FC03
ATTR_MODE: Final = 0  # uint8 — operating mode (Set/Continue/Comfort/Smart/Dry)
ATTR_TARGET_HUMIDITY: Final = 1  # uint8 — writable RH setpoint (35-85)
ATTR_CURRENT_HUMIDITY: Final = 2  # uint8 — current ambient RH
ATTR_BUCKET_FULL: Final = 3  # bool — dedicated water-bucket flag.
# DEAD on H50D44W: empirically verified 2026-05-11 to stay False even when the
# bucket is full. Kept as a defensive read in case TCL wires it up on a future
# model or firmware. Real bucket-full signal is code 5 in ATTR_ERROR_CODES.
# bool — filter-clean alert. Verified on a T50DC9SPB (product ID 0x8002):
# writing False clears the alert and the unit beeps (it also beeps when True
# is written). The cluster has no command for it, so a reset is this write.
ATTR_FILTER_ALERT: Final = 4
ATTR_ERROR_CODES: Final = 5  # string — JSON-encoded list, e.g. "[]" or "[5]"
ATTR_FEATURE_SET: Final = 6  # string — JSON-encoded list, e.g. "[3]"

# Known error-code semantics (empirically verified against H50D44W on firmware 1.0).
# Other codes will appear over time; document them here as they're identified.
ERROR_CODE_BUCKET_FULL: Final = 5

# Operating mode mapping. The integer-to-name pairings follow the order shown
# in the TCL Home app and have been confirmed for mode 0 (Set) and 1 (Continue)
# on H50D44W firmware 1.0; modes 2-4 mirror the app order and are validated
# opportunistically by the tampering automation. See PROJECT_STATUS.md for the
# verification status.
MODE_SET: Final = "set"
MODE_CONTINUE: Final = "continue"
MODE_COMFORT: Final = "comfort"
MODE_SMART: Final = "smart"
MODE_DRY: Final = "dry"

MODE_VALUE_MAP: Final[dict[int, str]] = {
    0: MODE_SET,
    1: MODE_CONTINUE,
    2: MODE_COMFORT,
    3: MODE_SMART,
    4: MODE_DRY,
}

# Reverse map for writes
MODE_NAME_MAP: Final[dict[str, int]] = {v: k for k, v in MODE_VALUE_MAP.items()}

AVAILABLE_MODES: Final[list[str]] = list(MODE_VALUE_MAP.values())

# Standard OnOff cluster, which carries the unit's power state.
ONOFF_ENDPOINT: Final = 1
ONOFF_CLUSTER: Final = 0x0006
ONOFF_ATTR_ON_OFF: Final = 0

# Humidity bounds (typical range for residential dehumidifiers; verify on device)
MIN_HUMIDITY: Final = 35
MAX_HUMIDITY: Final = 85

# Safety-net poll interval. Push updates (see __init__) normally arrive first.
POLL_INTERVAL_SECONDS: Final = 60

# Timeouts for matter-server round trips (seconds).
READ_TIMEOUT_SECONDS: Final = 10
WRITE_TIMEOUT_SECONDS: Final = 15

# Consecutive failed polls before a node's entities go unavailable.
UNAVAILABLE_AFTER_FAILURES: Final = 2

# Matter integration domain (built-in)
MATTER_DOMAIN: Final = "matter"

# Number of TCL_CLUSTER_FC03 data attributes (0..6) we surface as entities.
# Cluster metadata attributes (>=0xFFF8) are intentionally skipped.
NUM_TCL_FC03_DATA_ATTRS: Final = 7
