"""Pattern B development V02 feature evaluation V01 — recomputed from public sealed files."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from trend_scanner.patterns import pattern_b_state_v01 as rule

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/evaluate_pattern_b_development_v02_features_v01.py"
_spec = importlib.util.spec_from_file_location("evaluate_pattern_b_development_v02_features_v01", _SCRIPT)
ev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ev
_spec.loader.exec_module(ev)
rs = ev._load("research_pattern_b_robust_current_position_v01",
              "scripts/research_pattern_b_robust_current_position_v01.py")
fit = ev._load("analyze_pattern_b_feature_fitness_v01", "scripts/analyze_pattern_b_feature_fitness_v01.py")
dev = ev._load("build_pattern_b_development_v02_chart_pack", "scripts/build_pattern_b_development_v02_chart_pack.py")

RESULT = json.loads(ev.OUT_JSON.read_text(encoding="utf-8"))
PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/development_v02_human_labels.csv": "c5dd216ffa793c0b00b28a09d13b598b80fb87a15454cea1a8b704eb4c9d9e2d",
    "docs/patterns/pattern_b/validation/development_v02_human_labels.md": "1728bf02ab1ac020bbda536947b5b579ac7033c85599b4d4eb488feb6915980a",
    "docs/patterns/pattern_b/validation/development_v02_seal.json": "a9b406830da243e4ffd96c4bb47383811fc862e0069fb0a959f4b1cd67213854",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01_seal.json": "a91eaaceea94ad610a6c2be86f1581e35bb61c32765b7e627b680c3eb4a35af9",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _features() -> dict[str, dict]:
    with ev.RAW_CSV.open(encoding="utf-8") as fh:
        return {r["sample_id"]: {k: float(r[k]) for k in ev.FEATURE_COLUMNS} for r in csv.DictReader(fh)}


def _labels() -> dict[str, dict]:
    with ev.LABELS.open(encoding="utf-8") as fh:
        return {r["sample_id"]: r for r in csv.DictReader(fh)}


@pytest.mark.skipif(not dev.MANIFEST.exists(), reason="private development manifest is local only")
def test_seals_and_sample_set():
    ev.verify_seals(dev)
    assert sorted(_features()) == ev.SAMPLE_IDS and sorted(_labels()) == ev.SAMPLE_IDS
    assert RESULT["raw_values_sha256"] == _sha(ev.RAW_CSV)
    assert RESULT["labels_sha256"] == _sha(ev.LABELS)


def test_feature_row_reproduces_contract_and_candidates():
    dates = pd.bdate_range("2012-01-02", "2022-12-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(8).normal(0, 0.02, len(dates))))
    daily = pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=dates)
    row = ev.feature_row(daily, "2022-06-15", rs)
    pos = rs.position_features(daily, "2022-06-15")
    assert row["36M_CLOSE_PERCENTILE_POSITION"] == pos["percentile"]["36M"]
    assert row["52W_ROBUST_CLOSE_RANGE_POSITION"] == pos["robust_range"]["52W"]
    future = daily.copy()
    future.loc[future.index > "2022-06-15", "close"] *= 4
    assert ev.feature_row(future, "2022-06-15", rs) == row


def test_rule_predictions_and_metrics_recompute():
    f, labels = _features(), _labels()
    pred = {s: rule.classify_pattern_b_state_v01(*(f[s][k] for k in ev.KEEP)) for s in ev.SAMPLE_IDS}
    assert pred == RESULT["rule_v01_predictions"]
    m = ev.rule_metrics(pred, labels)
    assert m == RESULT["rule_v01_metrics"]
    assert (m["all"]["exact"], m["all"]["within_1"], m["all"]["error_ge_2"], m["all"]["error_ge_3"]) == (17, 35, 1, 0)
    assert m["all"]["mae"] == 0.5556
    assert sum(sum(r.values()) for r in m["confusion"].values()) == 36
    assert ev.one_step_mechanism(f, pred, labels) == RESULT["one_step_error_mechanism"]


def test_feature_and_candidate_diagnostics_recompute():
    f, labels = _features(), _labels()
    assert json.loads(json.dumps(ev.feature_diagnostics(f, labels, fit), default=rs._plain)) \
        == RESULT["feature_diagnostics"]
    assert json.loads(json.dumps(ev.candidate_structure(f, rs), default=rs._plain)) == RESULT["candidate_structure"]
    large = [e["sample_id"] for e in RESULT["large_errors"]]
    assert large == ["PBDEV2_019"]


def test_public_artifacts_hold_no_identity():
    for path in (ev.RAW_CSV, ev.OUT_JSON, ev.OUT_JSON.with_suffix(".md")):
        text = path.read_text(encoding="utf-8")
        assert '"ticker"' not in text and '"as_of"' not in text and "stock_name" not in text


@pytest.mark.skipif(not dev.MANIFEST.exists(), reason="private development manifest is local only")
def test_public_artifacts_hold_no_private_values():
    rows = dev._manifest_rows(dev.MANIFEST)
    identity = {r["ticker"] for r in rows} | {r["stock_name"] for r in rows if r["stock_name"]} | {r["as_of"] for r in rows}
    for path in (ev.RAW_CSV, ev.OUT_JSON, ev.OUT_JSON.with_suffix(".md")):
        text = path.read_text(encoding="utf-8")
        assert not [t for t in identity if t in text], path.name


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
