"""Official State Rule V01 evaluation on Holdout V02 — recomputed from sealed inputs."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from trend_scanner.patterns.pattern_b_state_v01 import STATES, classify_pattern_b_state_v01

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/evaluate_pattern_b_state_rule_v01_holdout_v02.py"
_spec = importlib.util.spec_from_file_location("evaluate_pattern_b_state_rule_v01_holdout_v02", _SCRIPT)
ev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ev
_spec.loader.exec_module(ev)

PROTECTED_SHA256 = {
    "src/trend_scanner/patterns/pattern_b_state_v01.py":
        "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01.md":
        "247e274a8a5255332be5ed1a84c30a7bd95f1b1899be6013590128dde9f860f5",
    "docs/patterns/pattern_b/validation/state_rule_v01_predictions.csv":
        "7188b00b820b4cf2464693a74c17336ec10c651645956bfee445534653468ae8",
    "docs/patterns/pattern_b/validation/feature_raw_values_v02.csv":
        "5613bc03f0126ea6dbf3609e6826709c1ed119a0f919b02dec7f1eb74ce8f986",
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv":
        "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _predictions() -> list[dict]:
    return _read(ev.PREDICTIONS)


def _seal() -> dict:
    return json.loads(ev.SEAL.read_text(encoding="utf-8"))


def test_sample_sets_match_exactly():
    preds = _predictions()
    ids = [r["sample_id"] for r in preds]
    assert len(preds) == 36 and len(set(ids)) == 36 and ids == ev.SAMPLE_IDS
    assert sorted(r["sample_id"] for r in _read(ev.FEATURES)) == ev.SAMPLE_IDS
    assert sorted(r["sample_id"] for r in _read(ev.LABELS)) == ev.SAMPLE_IDS
    assert tuple(preds[0]) == ev.PREDICTION_FIELDS


def test_predictions_equal_sealed_rule_on_sealed_features():
    features = {r["sample_id"]: r for r in _read(ev.FEATURES)}
    labels = {r["sample_id"]: r for r in _read(ev.LABELS)}
    for p in _predictions():
        f = features[p["sample_id"]]
        auto = classify_pattern_b_state_v01(*(float(f[k]) for k in ev.KEEP))
        assert p["automatic_label"] == auto and auto in STATES
        assert p["human_label"] == labels[p["sample_id"]]["label"]
        assert p["confidence"] == labels[p["sample_id"]]["confidence"]
        error = ev.ORDINAL[auto] - ev.ORDINAL[p["human_label"]]
        assert int(p["ordinal_error"]) == error and int(p["absolute_error"]) == abs(error)


def test_metrics_in_seal_match_recomputation():
    rows = [{**p, "ordinal_error": int(p["ordinal_error"]), "absolute_error": int(p["absolute_error"])}
            for p in _predictions()]
    m = ev.metrics(rows)
    seal = _seal()
    for key, value in m.items():
        if key not in ("extremes", "confusion"):
            assert seal[key] == value, key
    assert m["high_count"] == 22
    assert sum(sum(row.values()) for row in m["confusion"].values()) == 36
    assert m["negative_error_count"] + m["zero_error_count"] + m["positive_error_count"] == 36
    e = m["extremes"]
    for k in e["combined"]:
        assert e["combined"][k] == e["DEEP_DEPRESSED"][k] + e["EXTREME_OVERHEATED"][k]
    assert e["DEEP_DEPRESSED"]["sample_count"] == sum(r["human_label"] == "DEEP_DEPRESSED" for r in rows)


def test_record_matches_recomputation():
    rows = [{**p, "ordinal_error": int(p["ordinal_error"]), "absolute_error": int(p["absolute_error"])}
            for p in _predictions()]
    assert ev.RECORD.read_text(encoding="utf-8") == ev.render_record(ev.metrics(rows), rows)
    record = ev.RECORD.read_text(encoding="utf-8")
    big = [r["sample_id"] for r in rows if r["absolute_error"] >= 2]
    huge = [r["sample_id"] for r in rows if r["absolute_error"] >= 3]
    section7 = record.split("## 7.")[1].split("## 8.")[0]
    section8 = record.split("## 8.")[1].split("## 9.")[0]
    assert sorted(s for s in ev.SAMPLE_IDS if f"`{s}`" in section7) == big
    assert sorted(s for s in ev.SAMPLE_IDS if f"`{s}`" in section8) == huge
    assert "공식 1회 평가 완료" in record and "소진됐다" in record


def test_seal_hashes_and_flags():
    seal = _seal()
    assert seal["official_holdout_evaluation"] is True and seal["holdout_consumed"] is True
    assert seal["sample_count"] == 36 and seal["state_rule_family"] == "C"
    assert seal["predictions_file_sha256"] == _sha(ev.PREDICTIONS)
    assert seal["evaluation_record_sha256"] == _sha(ev.RECORD)
    assert seal["state_rule_sha256"] == _sha(ev.RULE_PATH)
    assert seal["feature_raw_values_sha256"] == _sha(ev.FEATURES)
    assert seal["hgt_v02_labels_sha256"] == _sha(ev.LABELS)


def test_protected_inputs_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
    source = _SCRIPT.read_text(encoding="utf-8")
    for token in ("0.55", "0.80", "-0.35", "combine_bands", "THRESHOLDS"):
        assert token not in source
