"""Pattern B evaluator — official Pattern B state from adjusted daily OHLC.

Contract: docs/patterns/pattern_b/spec/production_contract_v01.md

Composition only; no formula, threshold, or state lives here:
1. ``compute_pattern_b_features_v01(daily, as_of)`` (Feature Contract V01).
2. Readiness uses only the three features State Rule V02 consumes.
3. All three OK -> ``classify_pattern_b_state_v02`` -> READY with one of the five states.
   Any of them unavailable -> UNAVAILABLE with ``pattern_b_state=None``.

``UNAVAILABLE`` is an evaluation status, not a sixth Pattern B state. Invalid input
(``PatternBFeatureInputError``) and rule input errors are raised, never hidden.

The caller supplies adjusted daily prices from MarketDataRepositoryV2, limited to the
PIT COMMON identity segment that contains ``as_of``; this module does not load data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from trend_scanner.patterns.pattern_b_features_v01 import (
    STATUS_OK,
    compute_pattern_b_features_v01,
)
from trend_scanner.patterns.pattern_b_state_v02 import (
    FEATURES,
    MA24_DISTANCE,
    RANGE_36M,
    RANGE_52W,
    classify_pattern_b_state_v02,
)

FEATURE_CONTRACT_VERSION = "V01"
STATE_RULE_VERSION = "PATTERN_B_STATE_RULE_V02"


class PatternBEvaluationStatus(str, Enum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class PatternBEvaluationResult:
    ticker: str
    name: str
    as_of: str
    evaluation_status: PatternBEvaluationStatus
    pattern_b_state: str | None
    reason_codes: tuple[str, ...]
    reason_details: tuple[str, ...]
    range_36m: float | None
    monthly_ma24_distance: float | None
    range_52w: float | None
    monthly_last_bar: str | None
    weekly_last_bar: str | None
    feature_contract_version: str = FEATURE_CONTRACT_VERSION
    state_rule_version: str = STATE_RULE_VERSION


def _date(value: pd.Timestamp | None) -> str | None:
    return None if value is None else value.date().isoformat()


def evaluate_pattern_b(ticker: str, daily: pd.DataFrame, as_of, name: str = "") -> PatternBEvaluationResult:
    """Pattern B evaluation for one ticker as of one date."""
    computed = compute_pattern_b_features_v01(daily, as_of)
    used = {f: computed.features[f] for f in FEATURES}
    missing = [f for f in FEATURES if used[f].status != STATUS_OK]
    if missing:
        status, state = PatternBEvaluationStatus.UNAVAILABLE, None
    else:
        status = PatternBEvaluationStatus.READY
        state = classify_pattern_b_state_v02(*(used[f].value for f in FEATURES))
    return PatternBEvaluationResult(
        ticker=ticker,
        name=name,
        as_of=_date(computed.as_of),
        evaluation_status=status,
        pattern_b_state=state,
        reason_codes=tuple(f"{f}:{used[f].status}" for f in missing),
        reason_details=tuple(f"{f}: {used[f].reason}" for f in missing),
        range_36m=used[RANGE_36M].value,
        monthly_ma24_distance=used[MA24_DISTANCE].value,
        range_52w=used[RANGE_52W].value,
        monthly_last_bar=_date(computed.monthly_last_bar),
        weekly_last_bar=_date(computed.weekly_last_bar),
    )
