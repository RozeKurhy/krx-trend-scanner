"""Pattern B evaluator — composition of Feature Contract V01 and State Rule V02, READY/UNAVAILABLE."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trend_scanner.patterns import pattern_b_features_v01 as feat
from trend_scanner.patterns import pattern_b_state_v02 as v02
from trend_scanner.patterns.pattern_b_evaluator import (
    PatternBEvaluationResult,
    PatternBEvaluationStatus,
    evaluate_pattern_b,
)

_ROOT = Path(__file__).resolve().parents[1]
FROZEN_SHA256 = {
    "src/trend_scanner/patterns/pattern_b_features_v01.py": "2480497c2cdc85289f30ea215f67dc0a6d715a1d81a8045a4c0c97c8c3da00db",
    "src/trend_scanner/patterns/pattern_b_state_v02.py": "72adacfacde1529bde7ffc1cd748cee3b6e934565873a9f8d9c998e9aa03b37e",
}


def _daily(start: str, end: str, seed: int = 4, drift: float = 0.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, len(dates))))
    return pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=dates)


def _direct_state(daily: pd.DataFrame, as_of: str) -> str:
    f = feat.compute_pattern_b_features_v01(daily, as_of).features
    return v02.classify_pattern_b_state_v02(*(f[name].value for name in v02.FEATURES))


@pytest.mark.parametrize("seed,drift", [(4, 0.0), (7, 0.002), (11, -0.002), (19, 0.001)])
def test_ready_matches_direct_composition(seed, drift):
    daily = _daily("2012-01-02", "2022-06-30", seed, drift)
    result = evaluate_pattern_b("000000", daily, "2022-06-30", name="sample")
    assert result.evaluation_status is PatternBEvaluationStatus.READY
    assert result.pattern_b_state == _direct_state(daily, "2022-06-30")
    assert result.pattern_b_state in v02.STATES
    assert result.reason_codes == () and result.reason_details == ()
    f = feat.compute_pattern_b_features_v01(daily, "2022-06-30")
    assert result.range_36m == f.features[v02.RANGE_36M].value
    assert result.monthly_ma24_distance == f.features[v02.MA24_DISTANCE].value
    assert result.range_52w == f.features[v02.RANGE_52W].value
    assert (result.ticker, result.name, result.as_of) == ("000000", "sample", "2022-06-30")
    assert result.monthly_last_bar == "2022-06-30" and result.weekly_last_bar == "2022-06-24"


def test_insufficient_history_is_unavailable_without_state():
    daily = _daily("2020-01-02", "2022-06-30")
    result = evaluate_pattern_b("000000", daily, "2022-06-30")
    assert result.evaluation_status is PatternBEvaluationStatus.UNAVAILABLE
    assert result.pattern_b_state is None
    assert result.reason_codes == ("36M_RANGE_POSITION:INSUFFICIENT_BARS",)
    assert result.range_36m is None
    assert result.monthly_ma24_distance is not None and result.range_52w is not None


def test_flat_range_is_unavailable_without_state():
    dates = pd.bdate_range("2012-01-02", "2022-06-30")
    daily = pd.DataFrame({"high": 100.0, "low": 100.0, "close": 100.0}, index=dates)
    result = evaluate_pattern_b("000000", daily, "2022-06-30")
    assert result.evaluation_status is PatternBEvaluationStatus.UNAVAILABLE
    assert result.pattern_b_state is None
    assert result.reason_codes == ("36M_RANGE_POSITION:FLAT_RANGE", "52W_RANGE_POSITION:FLAT_RANGE")
    assert result.monthly_ma24_distance == 0.0


def test_unavailable_is_not_a_pattern_b_state():
    assert "UNAVAILABLE" not in v02.STATES and "READY" not in v02.STATES
    for daily in (_daily("2020-01-02", "2022-06-30"), _daily("2012-01-02", "2022-06-30")):
        result = evaluate_pattern_b("000000", daily, "2022-06-30")
        assert result.pattern_b_state is None or result.pattern_b_state in v02.STATES


def test_readiness_uses_only_rule_v02_features():
    # 36 completed monthly bars: 12M percentile lacks reference returns, rule inputs are all OK.
    daily = _daily("2019-07-01", "2022-06-30")
    f = feat.compute_pattern_b_features_v01(daily, "2022-06-30")
    assert f.monthly_bar_count == 36
    assert f.features[feat.RETURN_12M_PERCENTILE].status != feat.STATUS_OK
    result = evaluate_pattern_b("000000", daily, "2022-06-30")
    assert result.evaluation_status is PatternBEvaluationStatus.READY
    assert result.pattern_b_state == _direct_state(daily, "2022-06-30")


@pytest.mark.parametrize("column,value", [("close", np.nan), ("close", np.inf), ("low", -1.0), ("high", 50.0)])
def test_invalid_input_raises(column, value):
    daily = _daily("2012-01-02", "2022-06-30")
    daily.iloc[100, daily.columns.get_loc(column)] = value
    with pytest.raises(feat.PatternBFeatureInputError):
        evaluate_pattern_b("000000", daily, "2022-06-30")


def test_missing_column_raises():
    daily = _daily("2012-01-02", "2022-06-30").drop(columns=["low"])
    with pytest.raises(feat.PatternBFeatureInputError):
        evaluate_pattern_b("000000", daily, "2022-06-30")


def test_future_rows_are_ignored():
    daily = _daily("2012-01-02", "2023-06-30")
    cut = evaluate_pattern_b("000000", daily.loc[:"2022-06-30"], "2022-06-30")
    full = evaluate_pattern_b("000000", daily, "2022-06-30")
    assert cut == full


def test_versions_and_result_shape():
    result = evaluate_pattern_b("000000", _daily("2012-01-02", "2022-06-30"), "2022-06-30")
    assert (result.feature_contract_version, result.state_rule_version) == ("V01", "PATTERN_B_STATE_RULE_V02")
    assert [f.name for f in dataclasses.fields(PatternBEvaluationResult)] == [
        "ticker", "name", "as_of", "evaluation_status", "pattern_b_state", "reason_codes", "reason_details",
        "range_36m", "monthly_ma24_distance", "range_52w", "monthly_last_bar", "weekly_last_bar",
        "feature_contract_version", "state_rule_version",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.pattern_b_state = "NORMAL"


def test_frozen_modules_are_unchanged():
    for rel, digest in FROZEN_SHA256.items():
        assert hashlib.sha256((_ROOT / rel).read_bytes()).hexdigest() == digest, rel
