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
ATTR_BUCKET_FULL: Final = 3  # bool — dedicated water-bucket flag (DEAD on H50D44W;
#                                empirically verified 2026-05-11 to stay False even when the
#                                bucket is full. Kept as a defensive read in case TCL wires it
#                                up on a future model or firmware. Real bucket-full signal is
#                                code 5 in ATTR_ERROR_CODES.)
ATTR_LOCK_OR_FILTER: Final = 4  # bool — child lock or filter alert (TBD)
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

# Humidity bounds (typical range for residential dehumidifiers; verify on device)
MIN_HUMIDITY: Final = 35
MAX_HUMIDITY: Final = 85

# Fallback poll interval when push subscription is unavailable
POLL_INTERVAL_SECONDS: Final = 30

# Matter integration domain (built-in)
MATTER_DOMAIN: Final = "matter"

# Standard Matter cluster + attribute IDs we read directly
BASIC_INFORMATION_CLUSTER: Final = 0x0028
BASIC_INFORMATION_VENDOR_ID_ATTR: Final = 2

# Number of TCL_CLUSTER_FC03 data attributes (0..6) we surface as entities.
# Cluster metadata attributes (>=0xFFF8) are intentionally skipped.
NUM_TCL_FC03_DATA_ATTRS: Final = 7

# Path-string format used by the matter-server to identify attribute tuples.
# "endpoint/cluster/attr" — three integer fields separated by slashes.
ATTR_PATH_PARTS: Final = 3
