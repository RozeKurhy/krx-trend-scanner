"""Pattern B Holdout V02 KEEP feature raw values — sealed output and isolation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from trend_scanner.patterns.pattern_b_features_v01 import compute_pattern_b_features_v01

_ROOT = Path(__file__).resolve().parents[1]
_V = _ROOT / "docs/patterns/pattern_b/validation"
_RUNNER = _ROOT / "scripts/compute_pattern_b_holdout_feature_raw_v02.py"
_spec = importlib.util.spec_from_file_location("compute_pattern_b_holdout_feature_raw_v02", _RUNNER)
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)

RAW = _V / "feature_raw_values_v02.csv"
RECORD = _V / "feature_raw_values_v02.md"
SEAL = _V / "feature_raw_values_v02_seal.json"
PRIVATE_REPORT = runner.DEFAULT_PRIVATE_REPORT
KEEP = ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION")

PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv":
        "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "src/trend_scanner/patterns/pattern_b_state_v01.py":
        "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01.md":
        "247e274a8a5255332be5ed1a84c30a7bd95f1b1899be6013590128dde9f860f5",
    "docs/patterns/pattern_b/validation/state_rule_v01_predictions.csv":
        "7188b00b820b4cf2464693a74c17336ec10c651645956bfee445534653468ae8",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict]:
    with RAW.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_raw_values_have_exact_samples_and_three_finite_features():
    rows = _rows()
    assert tuple(rows[0]) == ("sample_id",) + KEEP
    ids = [r["sample_id"] for r in rows]
    assert ids == [f"PBHOLD_{i:03d}" for i in range(1, 37)] and len(set(ids)) == 36
    for r in rows:
        for name in KEEP:
            assert r[name] != "" and math.isfinite(float(r[name]))
        assert 0.0 <= float(r["36M_RANGE_POSITION"]) <= 1.0
        assert 0.0 <= float(r["52W_RANGE_POSITION"]) <= 1.0
        assert float(r["MONTHLY_MA24_DISTANCE"]) > -1.0


def test_keep_values_come_from_feature_contract_v01():
    dates = pd.bdate_range("2012-01-02", "2022-06-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(4).normal(0, 0.02, len(dates))))
    daily = pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=dates)
    values, provenance = runner.keep_values(daily, "2022-06-30")
    expected = compute_pattern_b_features_v01(daily, "2022-06-30")
    assert values == {n: repr(expected.features[n].value) for n in KEEP}
    assert provenance["monthly_last_bar"] <= "2022-06-30" and provenance["weekly_last_bar"] <= "2022-06-30"
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    assert seal["feature_module_sha256"] == _sha(_ROOT / "src/trend_scanner/patterns/pattern_b_features_v01.py")


def test_seal_matches_outputs_and_holdout_seal():
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    assert seal["sample_count"] == 36 and seal["feature_names"] == list(KEEP)
    assert seal["raw_values_file_sha256"] == _sha(RAW)
    assert seal["record_file_sha256"] == _sha(RECORD)
    holdout = json.loads((_V / "holdout_v02_seal.json").read_text(encoding="utf-8"))
    assert seal["holdout_private_manifest_sha256"] == holdout["private_manifest_sha256"]
    assert seal["holdout_chart_pack_sha256"] == holdout["chart_pack_sha256"]


@pytest.mark.skipif(not PRIVATE_REPORT.exists(), reason="private run report is local only")
def test_private_run_is_future_data_invariant():
    report = json.loads(PRIVATE_REPORT.read_text(encoding="utf-8"))
    checks, summary = report["checks"], report["summary"]
    assert len(checks) == 36
    assert summary["sample_count"] == 36 and summary["samples_with_future_rows_loaded"] == 36
    for c in checks:
        assert c["request_end_equals_as_of"] and c["last_bars_match_chart_pack"] and c["future_invariant"]
        assert c["effective_history_end"] <= c["request_end"]
        assert c["monthly_last_bar"] <= c["request_end"] and c["weekly_last_bar"] <= c["request_end"]
    future_rows = [c["future_rows_loaded"] for c in checks]
    assert all(x > 0 for x in future_rows)
    assert min(future_rows) == 57 and max(future_rows) == 248
    assert sum(x < 60 for x in future_rows) == 9
    assert sorted(x for x in future_rows if 60 <= x < 240) == [234, 239]
    assert sum(x >= 240 for x in future_rows) == 25


def test_record_states_the_actual_future_data_check():
    record = RECORD.read_text(encoding="utf-8")
    assert "기준일 이후 최대 365일까지 추가 데이터를 요청" in record and "365일은 요청 범위다" in record
    assert "36개 모두 실제로 기준일 이후 거래일이 포함된 입력을 받았고" in record
    assert "불일치 0개" in record
    assert "최소 57거래일, 최대\n  248거래일" in record
    assert "60거래일 미만 9개, 234거래일과 239거래일 각 1개, 240거래일 이상\n  25개" in record
    assert "1년 치" not in record and "27개" not in record


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
    hgt = json.loads((_V / "human_ground_truth_v02_seal.json").read_text(encoding="utf-8"))
    assert hgt["labels_file_sha256"] == PROTECTED_SHA256[
        "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv"
    ]


def test_no_state_rule_or_comparison_in_this_step():
    source = _RUNNER.read_text(encoding="utf-8")
    for token in ("pattern_b_state_v01", "human_ground_truth_labels", "classify_pattern_b_state"):
        assert token not in source
    header = RAW.read_text(encoding="utf-8").splitlines()[0]
    assert "predicted" not in header and "label" not in header
    assert not list(_V.glob("*v02*evaluation*")) and not list(_V.glob("*v02*comparison*"))
