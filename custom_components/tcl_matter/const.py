"""Constants for the TCL Matter integration.

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

# Vendor-specific cluster IDs (endpoint 1 on the dehumidifier)
TCL_CLUSTER_FC00: Final = 0x1334FC00  # opaque (one string attribute, currently empty)
TCL_CLUSTER_FC03: Final = 0x1334FC03  # primary control/state cluster

# Attribute IDs on TCL_CLUSTER_FC03
ATTR_MODE: Final = 0  # uint8 — operating mode (Set/Continue/Comfort/Smart/Dry)
ATTR_TARGET_HUMIDITY: Final = 1  # uint8 — writable RH setpoint (35-85)
ATTR_CURRENT_HUMIDITY: Final = 2  # uint8 — current ambient RH
ATTR_BUCKET_FULL: Final = 3  # bool — water bucket full
ATTR_LOCK_OR_FILTER: Final = 4  # bool — child lock or filter alert (TBD)
ATTR_ERROR_CODES: Final = 5  # string — JSON-encoded list, e.g. "[]"
ATTR_FEATURE_SET: Final = 6  # string — JSON-encoded list, e.g. "[3]"

# Attribute on TCL_CLUSTER_FC00 (vendor-prefixed ID, opaque for now)
TCL_CLUSTER_FC00_OPAQUE_ATTR: Final = 0x1334E000  # 322174976

# Operating mode mapping. NOTE: integer-to-name pairings are educated guesses
# based on the TCL Home app's mode order. Adam needs to confirm by toggling
# each mode on the device while watching the attribute change.
# TODO(empirical): confirm MODE_VALUE_MAP integer values.
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
