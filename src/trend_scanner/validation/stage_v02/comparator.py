"""Frozen Stage Match Comparator Contract for Stage v0.2 Validation."""

from __future__ import annotations

from enum import Enum
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage

STAGE_COMPARISON_ORDER: dict[PatternAStage, int] = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}


class StageMatchClass(str, Enum):
    EXACT = "EXACT"
    ADJACENT = "ADJACENT"
    SEVERE = "SEVERE"
    NODATA = "NODATA"


def classify_stage_match(
    expected: PatternAStage | None,
    predicted: PatternAStage | None,
) -> StageMatchClass:
    """Classify stage prediction match against expected stage under frozen comparator contract.

    Rules:
    - predicted is None -> NODATA
    - expected is None -> NODATA
    - expected == predicted -> EXACT
    - absolute order distance == 1 -> ADJACENT
    - otherwise -> SEVERE
    """
    if predicted is None or expected is None:
        return StageMatchClass.NODATA
    if expected == predicted:
        return StageMatchClass.EXACT
    exp_idx = STAGE_COMPARISON_ORDER.get(expected)
    pred_idx = STAGE_COMPARISON_ORDER.get(predicted)
    if exp_idx is None or pred_idx is None:
        return StageMatchClass.NODATA
    if abs(exp_idx - pred_idx) == 1:
        return StageMatchClass.ADJACENT
    return StageMatchClass.SEVERE
