"""Pattern B State Rule V02 — sealed 5-state rule, V01 plus one DEEP condition change.

Record: docs/patterns/pattern_b/validation/state_rule_v02.md
Seal:   docs/patterns/pattern_b/validation/state_rule_v02_seal.json

Research candidate A1/B0 (docs/patterns/pattern_b/validation/state_rule_v02_research_v01.md):
features, thresholds and every other step are the sealed State Rule V01. The only
change: when the 36M band is DEEP_DEPRESSED and the MA24 band is on the depressed side
(DEEP_DEPRESSED or DEPRESSED), the state stays DEEP_DEPRESSED instead of stepping back.
Thresholds and logic are sealed: do not edit.
"""

from __future__ import annotations

from trend_scanner.patterns.pattern_b_state_v01 import (
    FEATURES,
    MA24_DISTANCE,
    NORMAL,
    RANGE_36M,
    RANGE_52W,
    STATES,
    THRESHOLDS,
    combine_bands as combine_bands_v01,
    feature_band,
)

__all__ = [
    "FEATURES", "MA24_DISTANCE", "NORMAL", "RANGE_36M", "RANGE_52W", "STATES", "THRESHOLDS",
    "classify_pattern_b_state_v02", "combine_bands", "feature_band",
]


def combine_bands(m36: int, ma24: int, w52: int) -> int:
    """V02 on bands; returns a state index 0~4."""
    if m36 == 0 and ma24 < NORMAL:
        return 0
    return combine_bands_v01(m36, ma24, w52)


def classify_pattern_b_state_v02(
    range_36m: float,
    monthly_ma24_distance: float,
    range_52w: float,
) -> str:
    """Pattern B V02 state from raw 36M range position, MA24 distance, 52W range position."""
    bands = (
        feature_band(RANGE_36M, range_36m),
        feature_band(MA24_DISTANCE, monthly_ma24_distance),
        feature_band(RANGE_52W, range_52w),
    )
    return STATES[combine_bands(*bands)]
