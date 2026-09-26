"""Pattern B Holdout V02 post-hoc adjudication V01 — diagnosis only, official files untouched."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/analyze_pattern_b_holdout_v02_posthoc_adjudication_v01.py"
_spec = importlib.util.spec_from_file_location("analyze_pattern_b_holdout_v02_posthoc_adjudication_v01", _SCRIPT)
ph = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ph
_spec.loader.exec_module(ph)

EXPECTED_POSTHOC = {
    "PBHOLD_012": ("NORMAL", "MEDIUM"),
    "PBHOLD_017": ("DEEP_DEPRESSED", "HIGH"),
    "PBHOLD_018": ("DEEP_DEPRESSED", "HIGH"),
    "PBHOLD_019": ("DEPRESSED", "HIGH"),
    "PBHOLD_024": ("DEPRESSED", "HIGH"),
    "PBHOLD_026": ("NORMAL", "MEDIUM"),
    "PBHOLD_028": ("OVERHEATED", "MEDIUM"),
}
PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv":
        "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "docs/patterns/pattern_b/validation/human_ground_truth_v02.md":
        "c48b5f190fc2c49d488764139e2abc91b1df9b6a2b422576855eb3df92bb5c0e",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_predictions.csv":
        "86163eaad28916e0c53ddb111d570b97147f4ff9e6c4689975236e76c6ad81a4",
    "src/trend_scanner/patterns/pattern_b_state_v01.py":
        "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/feature_raw_values_v02.csv":
        "5613bc03f0126ea6dbf3609e6826709c1ed119a0f919b02dec7f1eb74ce8f986",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _rows() -> list[dict]:
    return _read(ph.POSTHOC_CSV)


def test_posthoc_rows_are_exactly_the_seven_official_large_errors():
    rows = _rows()
    assert tuple(rows[0]) == ph.FIELDS and len(rows) == 7
    assert sorted(r["sample_id"] for r in rows) == sorted(EXPECTED_POSTHOC)
    official = {r["sample_id"]: r for r in _read(ph.OFFICIAL_PREDICTIONS)}
    assert sorted(s for s, r in official.items() if int(r["absolute_error"]) >= 2) == sorted(EXPECTED_POSTHOC)


def test_official_values_are_copied_and_posthoc_values_match_the_user():
    hgt = {r["sample_id"]: r for r in _read(ph.OFFICIAL_HGT)}
    official = {r["sample_id"]: r for r in _read(ph.OFFICIAL_PREDICTIONS)}
    for r in _rows():
        sid = r["sample_id"]
        assert r["official_hgt_label"] == hgt[sid]["label"]
        assert r["official_confidence"] == hgt[sid]["confidence"]
        assert r["automatic_label"] == official[sid]["automatic_label"]
        assert int(r["official_absolute_error"]) == int(official[sid]["absolute_error"])
        assert (r["posthoc_label"], r["posthoc_confidence"]) == EXPECTED_POSTHOC[sid]
        error = ph.ORDINAL[r["automatic_label"]] - ph.ORDINAL[r["posthoc_label"]]
        assert int(r["posthoc_ordinal_error"]) == error and int(r["posthoc_absolute_error"]) == abs(error)


def test_subset_and_counterfactual_diagnostics():
    rows = [{**r, "posthoc_absolute_error": int(r["posthoc_absolute_error"])} for r in _rows()]
    d = ph.diagnostics(rows, _read(ph.OFFICIAL_PREDICTIONS))
    s, f = d["subset"], d["full"]
    assert (s["exact_match_count"], s["within_1_count"], s["error_ge_2_count"], s["error_ge_3_count"]) == (5, 6, 1, 0)
    assert (f["exact_match_count"], f["within_1_count"], f["error_ge_2_count"], f["error_ge_3_count"]) == (17, 35, 1, 0)
    assert f["absolute_error_sum"] == 20 and f["ordinal_mae"] == 0.5556
    assert d["remaining_ge_2"] == ["PBHOLD_028"]
    seal = json.loads(ph.POSTHOC_SEAL.read_text(encoding="utf-8"))
    assert seal["subset_diagnostic"] == s and seal["full_counterfactual_diagnostic"] == f


def test_record_matches_generator_and_states_limits():
    rows = [{**r, "official_absolute_error": int(r["official_absolute_error"]),
             "posthoc_ordinal_error": int(r["posthoc_ordinal_error"]),
             "posthoc_absolute_error": int(r["posthoc_absolute_error"])} for r in _rows()]
    d = ph.diagnostics(rows, _read(ph.OFFICIAL_PREDICTIONS))
    official = json.loads(ph.OFFICIAL_EVALUATION_SEAL.read_text(encoding="utf-8"))
    features = {r["sample_id"]: r for r in _read(ph.FEATURES)}
    record = ph.POSTHOC_RECORD.read_text(encoding="utf-8")
    assert record == ph.render_record(rows, d, official, features)
    assert "자동 판정에 대해 가려진 판정이 아니다" in record
    assert "독립 검증 결과를 주장할 수 없다" in record
    assert "공식 수치 아님" in record
    for banned in ("Holdout PASS", "성능 정정", "공식 정확도 47", "다시 통과"):
        assert banned not in record


def test_seal_flags_and_hashes():
    seal = json.loads(ph.POSTHOC_SEAL.read_text(encoding="utf-8"))
    assert seal["official_holdout_unchanged"] is True and seal["posthoc_only"] is True
    assert seal["automatic_prediction_blind"] is False and seal["sample_count"] == 7
    assert seal["sample_ids"] == sorted(EXPECTED_POSTHOC)
    assert seal["posthoc_csv_sha256"] == _sha(ph.POSTHOC_CSV)
    assert seal["posthoc_record_sha256"] == _sha(ph.POSTHOC_RECORD)
    assert seal["official_evaluation_seal_sha256"] == _sha(ph.OFFICIAL_EVALUATION_SEAL)
    assert seal["official_predictions_sha256"] == _sha(ph.OFFICIAL_PREDICTIONS)
    assert seal["official_hgt_labels_sha256"] == _sha(ph.OFFICIAL_HGT)


def test_official_and_sealed_inputs_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
    official = json.loads(ph.OFFICIAL_EVALUATION_SEAL.read_text(encoding="utf-8"))
    assert official["predictions_file_sha256"] == _sha(ph.OFFICIAL_PREDICTIONS)
    assert official["evaluation_record_sha256"] == _sha(
        _ROOT / "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation.md"
    )
    assert official["state_rule_sha256"] == _sha(_ROOT / "src/trend_scanner/patterns/pattern_b_state_v01.py")
    assert official["feature_raw_values_sha256"] == _sha(ph.FEATURES)
