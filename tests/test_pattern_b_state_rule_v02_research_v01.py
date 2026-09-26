"""State Rule V02 research V01 — fixed candidate space, V01 reproduction, protections."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import sys

from trend_scanner.patterns import pattern_b_state_v01 as rule

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/research_pattern_b_state_rule_v02_v01.py"
_spec = importlib.util.spec_from_file_location("research_pattern_b_state_rule_v02_v01", _SCRIPT)
rv2 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rv2
_spec.loader.exec_module(rv2)

RESULT = json.loads(rv2.OUT_JSON.read_text(encoding="utf-8"))
GRID = list(itertools.product(range(5), repeat=3))
PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/development_v02_human_labels.csv": "c5dd216ffa793c0b00b28a09d13b598b80fb87a15454cea1a8b704eb4c9d9e2d",
    "docs/patterns/pattern_b/validation/development_v02_feature_raw_values_v01.csv": "d2d9eebc378fc559b7ca7ec2583c00217cac11154307f650d843117aaa82225e",
    "docs/patterns/pattern_b/validation/development_v02_feature_evaluation_v01.json": "03fe86ae277a6248fbc001c09efa85a0339274118db2cf831d43fe8c6dbfc605",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01_seal.json": "a91eaaceea94ad610a6c2be86f1581e35bb61c32765b7e627b680c3eb4a35af9",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "docs/patterns/pattern_b/validation/holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
}


def test_candidate_space_is_fixed():
    assert rv2.DEEP_MODES == ("A0", "A1", "A2")
    assert rv2.BOUNDARIES == {"B0": 0.25, "B1": 0.30, "B2": 0.35}
    assert sorted(RESULT["candidates"]) == sorted(f"{a}/{b}" for a in rv2.DEEP_MODES for b in rv2.BOUNDARIES)
    assert len(RESULT["candidates"]) == 9


def test_a0_equals_v01_and_upper_side_is_unchanged():
    for mode in rv2.DEEP_MODES:
        for m36, ma24, w52 in GRID:
            v01 = rule.combine_bands(m36, ma24, w52)
            cand = rv2.combine_candidate(m36, ma24, w52, mode)
            if mode == "A0" or m36 >= 1:
                assert cand == v01, (mode, m36, ma24, w52)
            else:
                assert cand in (0, v01)
    for x in (0.0, 0.049, 0.05, 0.249, 0.25, 0.3, 0.55, 0.8, 0.99):
        assert rv2.band_36m(x, 0.25) == rule.feature_band(rule.RANGE_36M, x)


def test_baseline_reproduces_rule_v01_development_metrics():
    base = RESULT["candidates"]["A0/B0"]
    assert (base["exact"], base["within_1"], base["mae"], base["error_ge_2"]) == (17, 35, 0.5556, 1)
    assert base["changed_predictions_vs_v01"] == []
    evaluation = json.loads((rv2.V / "development_v02_feature_evaluation_v01.json").read_text(encoding="utf-8"))
    assert base["predictions"] == evaluation["rule_v01_predictions"]


def test_result_recomputes_from_sealed_inputs():
    assert rv2.run() == RESULT


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert hashlib.sha256((_ROOT / rel).read_bytes()).hexdigest() == digest, rel
