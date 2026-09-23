"""PBHOLD_028 structure diagnostic V01 — read-only, recomputed from sealed public files."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from trend_scanner.patterns.pattern_b_state_v01 import classify_pattern_b_state_v01

_ROOT = Path(__file__).resolve().parents[1]
_V = _ROOT / "docs/patterns/pattern_b/validation"
_SCRIPT = _ROOT / "scripts/diagnose_pattern_b_pbhold_028_v01.py"
_spec = importlib.util.spec_from_file_location("diagnose_pattern_b_pbhold_028_v01", _SCRIPT)
diag = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = diag
_spec.loader.exec_module(diag)

RESULT = json.loads(diag.OUT_JSON.read_text(encoding="utf-8"))
PROTECTED_SHA256 = {
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01.md": "247e274a8a5255332be5ed1a84c30a7bd95f1b1899be6013590128dde9f860f5",
    "docs/patterns/pattern_b/validation/state_rule_v01_seal.json": "a91eaaceea94ad610a6c2be86f1581e35bb61c32765b7e627b680c3eb4a35af9",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02_seal.json": "e4ffac7a0345a821cc4658b837f76f68d184e7966d0863fe8b32d4c84b9ea9f6",
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv": "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_predictions.csv": "86163eaad28916e0c53ddb111d570b97147f4ff9e6c4689975236e76c6ad81a4",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation.md": "bb3ab8cadfdc149065738811d9d80d7b28508b7834066ac36311b33edca1073f",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01.csv": "b4bae186f90af60530683ca4d839359cc9285336973a7e4d0b56dd64bb9906c2",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01.md": "b2345b3cc1f1a9a4431b8e41b8e8a707e970c3d825a6716a4799d21d6f5115ea",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
    "docs/patterns/pattern_b/validation/feature_raw_values_v02.csv": "5613bc03f0126ea6dbf3609e6826709c1ed119a0f919b02dec7f1eb74ce8f986",
}


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _features() -> dict[str, dict]:
    return {r["sample_id"]: r for r in _read(_V / "feature_raw_values_v02.csv")}


def test_target_keep_values_equal_sealed_features():
    row = _features()["PBHOLD_028"]
    assert RESULT["keep_values"] == {f: float(row[f]) for f in diag.KEEP}
    for f in diag.KEEP:
        assert RESULT["seven_features"][f]["value"] == float(row[f])


def test_family_c_decomposition_uses_the_sealed_rule():
    values = {f: float(_features()["PBHOLD_028"][f]) for f in diag.KEEP}
    assert classify_pattern_b_state_v01(*values.values()) == "DEPRESSED"
    fc = diag.family_c_decomposition(values)
    assert fc == RESULT["family_c"]
    assert fc["bands"] == {"36M_RANGE_POSITION": 1, "MONTHLY_MA24_DISTANCE": 3, "52W_RANGE_POSITION": 0}
    assert fc["final_state"] == fc["classifier_state"] == "DEPRESSED"
    assert fc["probe_52w_neutral"] == "NORMAL"
    assert set(fc["probe_ma24_sweep_given_52w"]) == {"DEPRESSED"}
    assert fc["reachable_states_given_primary"] == ["DEPRESSED", "NORMAL"]


def test_posthoc_comparison_and_conflict_counts_recompute():
    posthoc = _read(_V / "holdout_v02_posthoc_adjudication_v01.csv")
    assert sorted(r["sample_id"] for r in posthoc) == [
        "PBHOLD_012", "PBHOLD_017", "PBHOLD_018", "PBHOLD_019", "PBHOLD_024", "PBHOLD_026", "PBHOLD_028",
    ]
    row028 = next(r for r in posthoc if r["sample_id"] == "PBHOLD_028")
    assert (row028["posthoc_label"], row028["posthoc_confidence"]) == ("OVERHEATED", "MEDIUM")
    comparison = diag.posthoc_comparison(_features(), posthoc)
    assert comparison == RESULT["posthoc_comparison"]
    assert [r["sample_id"] for r in comparison if r["range_low_ma24_high_posthoc_high"]] == ["PBHOLD_028"]
    assert diag.conflict_counts(_features()) == RESULT["v02_label_free_conflict_counts"]
    assert RESULT["v02_label_free_conflict_counts"]["ranges_depressed_ma24_overheated"] == 1


def test_public_artifact_has_no_identity_or_absolute_prices():
    text = diag.OUT_JSON.read_text(encoding="utf-8")
    for key in ('"ticker"', '"as_of"', '"stock_name"'):
        assert key not in text
    spike = RESULT["spike"]
    assert spike["monthly_36"]["high_to_close"] > 1 and spike["ma24_to_close"] < 1
    assert 0 < spike["monthly_36"]["low_to_close"] < 1


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert hashlib.sha256((_ROOT / rel).read_bytes()).hexdigest() == digest, rel
