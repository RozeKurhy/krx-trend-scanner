"""Pattern B State Rule V02 — A1/B0 reproduction, V01 equivalence outside DEEP, seal integrity."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import sys

import pytest

from trend_scanner.patterns import pattern_b_state_v01 as v01
from trend_scanner.patterns import pattern_b_state_v02 as v02

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/research_pattern_b_state_rule_v02_v01.py"
_spec = importlib.util.spec_from_file_location("research_pattern_b_state_rule_v02_v01", _SCRIPT)
rv2 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rv2
_spec.loader.exec_module(rv2)

V = "docs/patterns/pattern_b/validation/"
RULE_PATH = _ROOT / "src/trend_scanner/patterns/pattern_b_state_v02.py"
RECORD_PATH = _ROOT / V / "state_rule_v02.md"
SEAL = json.loads((_ROOT / V / "state_rule_v02_seal.json").read_text(encoding="utf-8"))
RESEARCH = json.loads(rv2.OUT_JSON.read_text(encoding="utf-8"))["candidates"]
GRID = list(itertools.product(range(5), repeat=3))
PROTECTED_SHA256 = {
    V + "development_v02_human_labels.csv": "c5dd216ffa793c0b00b28a09d13b598b80fb87a15454cea1a8b704eb4c9d9e2d",
    V + "development_v02_feature_raw_values_v01.csv": "d2d9eebc378fc559b7ca7ec2583c00217cac11154307f650d843117aaa82225e",
    V + "human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    V + "state_rule_v01_seal.json": "a91eaaceea94ad610a6c2be86f1581e35bb61c32765b7e627b680c3eb4a35af9",
    V + "state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    V + "holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
}


def _sha(rel: str | Path) -> str:
    return hashlib.sha256((_ROOT / rel).read_bytes()).hexdigest()


def _dev_predictions() -> tuple[dict[str, str], dict[str, str]]:
    rows = {r["sample_id"]: r for r in rv2._read(rv2.RAW)}
    labels = {r["sample_id"]: r["label"] for r in rv2._read(rv2.LABELS)}
    pred = {s: v02.classify_pattern_b_state_v02(*(float(rows[s][f]) for f in v02.FEATURES)) for s in rv2.SAMPLE_IDS}
    return pred, labels


def test_reproduces_research_a1_b0_on_development_v02():
    pred, labels = _dev_predictions()
    assert pred == RESEARCH["A1/B0"]["predictions"]
    base = RESEARCH["A0/B0"]["predictions"]
    m = rv2.evaluate(pred, labels, base)
    assert (m["exact"], m["within_1"], m["mae"], m["error_ge_2"]) == (22, 35, 0.4167, 1)
    assert (m["per_state"]["DEEP_DEPRESSED"]["exact"], m["per_state"]["DEEP_DEPRESSED"]["n"]) == (9, 11)
    assert m["changed_predictions_vs_v01"] == RESEARCH["A1/B0"]["changed_predictions_vs_v01"]
    assert m["changed_predictions_vs_v01"] == SEAL["development_metrics"]["changed_predictions_vs_v01"]


def test_only_deep_36m_with_depressed_ma24_differs_from_v01():
    diff = {g for g in GRID if v02.combine_bands(*g) != v01.combine_bands(*g)}
    assert diff == {(0, 1, w) for w in range(5)}
    for g in diff:
        assert (v01.combine_bands(*g), v02.combine_bands(*g)) == (1, 0)
    for g in GRID:
        if g[0] != 0:
            assert v02.combine_bands(*g) == v01.combine_bands(*g)


def test_overheated_side_is_v01():
    for g in GRID:
        if g[0] >= v02.NORMAL or v01.combine_bands(*g) >= v02.NORMAL or v02.combine_bands(*g) >= v02.NORMAL:
            assert v02.combine_bands(*g) == v01.combine_bands(*g)
    for g in GRID:
        if v02.combine_bands(*g) == 4:
            assert g[0] == g[1] == 4


def test_thresholds_and_features_are_v01():
    assert v02.THRESHOLDS is v01.THRESHOLDS and v02.FEATURES == v01.FEATURES
    assert v02.THRESHOLDS[v02.RANGE_36M] == (0.05, 0.25, 0.55, 0.80)
    assert SEAL["thresholds"] == {f: list(v01.THRESHOLDS[f]) for f in v01.FEATURES}
    assert SEAL["feature_names"] == list(v01.FEATURES)


def test_deep_needs_deep_36m_and_depressed_side_ma24():
    for g in GRID:
        if v02.combine_bands(*g) == 0:
            assert g[0] == 0 and g[1] < v02.NORMAL


def test_monotone_in_every_input():
    for m36, ma24, w52 in GRID:
        base = v02.combine_bands(m36, ma24, w52)
        for bumped in ((m36 + 1, ma24, w52), (m36, ma24 + 1, w52), (m36, ma24, w52 + 1)):
            if max(bumped) <= 4:
                assert v02.combine_bands(*bumped) >= base


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, "0.5", True])
def test_non_finite_or_non_numeric_input_fails(bad):
    for args in ((bad, 0.0, 0.5), (0.5, bad, 0.5), (0.5, 0.0, bad)):
        with pytest.raises(ValueError):
            v02.classify_pattern_b_state_v02(*args)


def test_seal_integrity():
    assert SEAL["version"] == "PATTERN_B_STATE_RULE_V02" and SEAL["research_candidate"] == "A1/B0"
    assert SEAL["performance_scope"] == "DEVELOPMENT_SET_ONLY_NOT_HOLDOUT"
    assert SEAL["implementation_sha256"] == _sha(RULE_PATH)
    assert SEAL["record_sha256"] == _sha(RECORD_PATH)
    for rel, digest in {**SEAL["research_source_sha256"], **SEAL["protected_input_sha256"]}.items():
        assert _sha(rel) == digest, rel
    res = RESEARCH["A1/B0"]
    dm = SEAL["development_metrics"]
    assert (dm["exact"], dm["within_1"], dm["ordinal_mae"], dm["errors_ge_2"], dm["errors_ge_3"]) == (
        res["exact"], res["within_1"], res["mae"], res["error_ge_2"], res["error_ge_3"])


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(rel) == digest, rel
        assert SEAL["protected_input_sha256"][rel] == digest


def test_no_holdout_reference_in_rule():
    text = RULE_PATH.read_text(encoding="utf-8").lower()
    for token in ("holdout", "pbhold", "private_manifest"):
        assert token not in text
