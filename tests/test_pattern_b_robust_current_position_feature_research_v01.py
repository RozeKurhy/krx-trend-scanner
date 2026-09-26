"""Robust current-position feature research V01 — formulas, sensitivity, isolation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_V = _ROOT / "docs/patterns/pattern_b/validation"
_SCRIPT = _ROOT / "scripts/research_pattern_b_robust_current_position_v01.py"
_spec = importlib.util.spec_from_file_location("research_pattern_b_robust_current_position_v01", _SCRIPT)
rs = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rs
_spec.loader.exec_module(rs)

RESULT = json.loads(rs.OUT_JSON.read_text(encoding="utf-8"))
PROTECTED_SHA256 = {
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01_seal.json": "a91eaaceea94ad610a6c2be86f1581e35bb61c32765b7e627b680c3eb4a35af9",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02_seal.json": "e4ffac7a0345a821cc4658b837f76f68d184e7966d0863fe8b32d4c84b9ea9f6",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_predictions.csv": "86163eaad28916e0c53ddb111d570b97147f4ff9e6c4689975236e76c6ad81a4",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
    "docs/patterns/pattern_b/validation/pbhold_028_structure_diagnostic_v01.json": "c80e4f7a630b47ce0a27d5e4b49ab5bffb99b3f89e795550d836435c103d0c16",
    "docs/patterns/pattern_b/validation/pbhold_028_structure_diagnostic_v01.md": "4932ccaea23f40fbb77af854ce12ab9c3510edd8eff24ac19ee87530062041e6",
    "docs/patterns/pattern_b/validation/feature_raw_values_v02.csv": "5613bc03f0126ea6dbf3609e6826709c1ed119a0f919b02dec7f1eb74ce8f986",
}


def _bars(closes, highs=None, lows=None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "high": closes * 1.01 if highs is None else np.asarray(highs, dtype=float),
        "low": closes * 0.99 if lows is None else np.asarray(lows, dtype=float),
        "close": closes,
    }, index=pd.date_range("2015-01-31", periods=len(closes), freq="ME"))


def test_candidate_a_is_mid_rank_of_current_vs_other_closes():
    closes = [1.0, 2.0, 2.0, 3.0, 2.0]  # current 2.0 vs [1,2,2,3]: (1 + 0.5*2)/4
    assert rs.close_percentile_position(_bars(closes), 5) == pytest.approx(0.5)
    assert rs.close_percentile_position(_bars([1, 2, 3, 4, 9]), 5) == 1.0
    assert rs.close_percentile_position(_bars([5, 2, 3, 4, 1]), 5) == 0.0
    assert rs.close_percentile_position(_bars([1, 2, 3]), 5) is None


def test_candidate_b_is_clipped_q10_q90_position():
    closes = np.arange(1, 11, dtype=float)  # current 10
    q10, q90 = np.percentile(closes, [10, 90])
    assert rs.robust_close_range_position(_bars(closes), 10) == pytest.approx(min(1.0, (10 - q10) / (q90 - q10)))
    mid = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 5.0])
    q10, q90 = np.percentile(mid, [10, 90])
    assert rs.robust_close_range_position(_bars(mid), 10) == pytest.approx((5 - q10) / (q90 - q10))
    assert rs.robust_close_range_position(_bars([4.0] * 10), 10) is None


def test_pit_cutoff_and_completed_bars():
    dates = pd.bdate_range("2012-01-02", "2022-12-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.02, len(dates))))
    daily = pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=dates)
    as_of = "2022-06-15"  # mid-month, Wednesday
    full = rs.position_features(daily, as_of)
    cut = rs.position_features(daily[daily.index <= as_of], as_of)
    assert full == cut
    changed = daily.copy()
    changed.loc[changed.index > as_of, "close"] *= 5  # future-only change
    assert rs.position_features(changed, as_of) == full


def test_synthetic_spike_sensitivity_is_recorded_and_recomputes():
    s = rs.synthetic_sensitivity()
    assert s == RESULT["synthetic"]
    for scenario in ("high_only", "close"):
        assert s[scenario]["baseline"]["delta"] < -0.5
        assert abs(s[scenario]["percentile"]["delta"]) < 0.05
        assert abs(s[scenario]["robust_range"]["delta"]) < 0.05


def test_pbhold_028_baseline_matches_sealed_and_v02_set():
    sealed = {r["sample_id"]: r for r in csv.DictReader((_V / "feature_raw_values_v02.csv").open(encoding="utf-8"))}
    p = RESULT["pbhold_028"]
    assert p["baseline"]["36M"] == float(sealed["PBHOLD_028"]["36M_RANGE_POSITION"])
    assert p["baseline"]["52W"] == float(sealed["PBHOLD_028"]["52W_RANGE_POSITION"])
    assert sorted(RESULT["v02_positions"]) == [f"PBHOLD_{i:03d}" for i in range(1, 37)]
    for sid, row in RESULT["v02_positions"].items():
        assert row["baseline"]["36M"] == float(sealed[sid]["36M_RANGE_POSITION"])


def test_label_free_comparison_uses_no_labels_and_recomputes():
    body = inspect.getsource(rs.label_free_comparison).split('"""')[2]  # after signature and docstring
    for token in ("label", "posthoc", "human", "confidence", "hgt"):
        assert token not in body
    sealed = {r["sample_id"]: float(r["MONTHLY_MA24_DISTANCE"])
              for r in csv.DictReader((_V / "feature_raw_values_v02.csv").open(encoding="utf-8"))}
    assert json.loads(json.dumps(rs.label_free_comparison(RESULT["v02_positions"], sealed), default=rs._plain)) \
        == RESULT["v02_label_free"]


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert hashlib.sha256((_ROOT / rel).read_bytes()).hexdigest() == digest, rel
