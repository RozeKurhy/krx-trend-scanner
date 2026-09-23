"""Pattern B State Rule V01 — sealed 5-state rule from three KEEP features.

Record: docs/patterns/pattern_b/validation/state_rule_v01.md
Seal:   docs/patterns/pattern_b/validation/state_rule_v01_seal.json

Rule family C (monthly primary + confirmation):
1. Each feature value maps to a band 0~4 (DEEP_DEPRESSED ~ EXTREME_OVERHEATED) by
   counting the thresholds it reaches; each threshold is an inclusive lower bound.
2. The 36M range-position band is the primary state.
3. An extreme primary state (0 or 4) needs the MA24 band to be the same extreme;
   otherwise it moves one step toward NORMAL.
4. A non-NORMAL state needs the MA24 band or the 52W band on the same side of
   NORMAL; otherwise it becomes NORMAL.

The 52W band can only confirm or cancel a one-sided state; it never creates a
state on its own side. Thresholds and logic are sealed: do not edit before the
Holdout evaluation described in the record.
"""

from __future__ import annotations

import math

STATES: tuple[str, ...] = (
    "DEEP_DEPRESSED",
    "DEPRESSED",
    "NORMAL",
    "OVERHEATED",
    "EXTREME_OVERHEATED",
)
NORMAL = 2

RANGE_36M = "36M_RANGE_POSITION"
MA24_DISTANCE = "MONTHLY_MA24_DISTANCE"
RANGE_52W = "52W_RANGE_POSITION"
FEATURES: tuple[str, ...] = (RANGE_36M, MA24_DISTANCE, RANGE_52W)

# Band lower bounds for DEPRESSED, NORMAL, OVERHEATED, EXTREME_OVERHEATED.
THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    RANGE_36M: (0.05, 0.25, 0.55, 0.80),
    MA24_DISTANCE: (-0.35, -0.10, 0.15, 0.50),
    RANGE_52W: (0.15, 0.25, 0.70, 0.80),
}


def feature_band(feature: str, value: float) -> int:
    """Band 0~4 for one feature; a value equal to a threshold falls in the upper band."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{feature}: value must be a finite number, got {value!r}")
    return sum(value >= t for t in THRESHOLDS[feature])


def combine_bands(m36: int, ma24: int, w52: int) -> int:
    """Family C on bands; returns a state index 0~4."""
    state = m36
    if state in (0, 4) and ma24 != state:
        state += 1 if state == 0 else -1
    if state != NORMAL:
        side = -1 if state < NORMAL else 1
        if not ((ma24 - NORMAL) * side > 0 or (w52 - NORMAL) * side > 0):
            state = NORMAL
    return state


def classify_pattern_b_state_v01(
    range_36m: float,
    monthly_ma24_distance: float,
    range_52w: float,
) -> str:
    """Pattern B V01 state from raw 36M range position, MA24 distance, 52W range position."""
    bands = (
        feature_band(RANGE_36M, range_36m),
        feature_band(MA24_DISTANCE, monthly_ma24_distance),
        feature_band(RANGE_52W, range_52w),
    )
    return STATES[combine_bands(*bands)]
