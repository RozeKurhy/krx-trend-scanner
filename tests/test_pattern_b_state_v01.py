"""Pattern B State Rule V01 — sealed rule behaviour and seal integrity."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import sys

import pandas as pd
import pytest

from trend_scanner.patterns import pattern_b_state_v01 as rule

_ROOT = Path(__file__).resolve().parents[1]
_DESIGN = _ROOT / "scripts/design_pattern_b_state_rule_v01.py"
_spec = importlib.util.spec_from_file_location("design_pattern_b_state_rule_v01", _DESIGN)
design = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = design
_spec.loader.exec_module(design)

GRID = list(itertools.product(range(5), repeat=3))


def _value_in_band(feature: str, band: int) -> float:
    """A value strictly inside ``band`` for ``feature``."""
    t = rule.THRESHOLDS[feature]
    if band == 0:
        return t[0] - 0.05
    if band == 4:
        return t[3] + 0.05
    return (t[band - 1] + t[band]) / 2


@pytest.mark.parametrize("feature", rule.FEATURES)
def test_threshold_is_inclusive_lower_bound(feature):
    for i, t in enumerate(rule.THRESHOLDS[feature]):
        assert rule.feature_band(feature, t - 1e-9) == i
        assert rule.feature_band(feature, t) == i + 1
        assert rule.feature_band(feature, t + 1e-9) == i + 1


def test_classifier_uses_bands_and_returns_only_five_states():
    for bands in GRID:
        values = [_value_in_band(f, b) for f, b in zip(rule.FEATURES, bands)]
        assert [rule.feature_band(f, v) for f, v in zip(rule.FEATURES, values)] == list(bands)
        state = rule.classify_pattern_b_state_v01(*values)
        assert state in rule.STATES
        assert rule.STATES.index(state) == rule.combine_bands(*bands)


def test_monotone_in_every_input():
    for m36, ma24, w52 in GRID:
        base = rule.combine_bands(m36, ma24, w52)
        for bumped in ((m36 + 1, ma24, w52), (m36, ma24 + 1, w52), (m36, ma24, w52 + 1)):
            if max(bumped) <= 4:
                assert rule.combine_bands(*bumped) >= base


def test_extremes_need_both_monthly_features():
    for m36, ma24, w52 in GRID:
        out = rule.combine_bands(m36, ma24, w52)
        if out in (0, 4):
            assert m36 == ma24 == out


def test_weekly_only_confirms_or_cancels_one_side():
    for m36, ma24 in itertools.product(range(5), repeat=2):
        outs = {rule.combine_bands(m36, ma24, w) for w in range(5)}
        non_normal = outs - {rule.NORMAL}
        assert len(non_normal) <= 1
        if len(outs) > 1:
            assert rule.NORMAL in outs and len(outs) == 2


def test_monthly_conflict_handling():
    # 36M overheated, MA24 depressed: overheated only when weekly confirms the 36M side.
    assert rule.combine_bands(3, 1, 3) == 3
    assert rule.combine_bands(3, 1, 2) == rule.NORMAL
    assert rule.combine_bands(3, 1, 0) == rule.NORMAL
    # 36M in NORMAL stays NORMAL whatever the others say.
    assert {rule.combine_bands(2, b, w) for b in range(5) for w in range(5)} == {rule.NORMAL}
    # Extreme 36M with non-extreme MA24 steps back one.
    assert rule.combine_bands(4, 3, 4) == 3
    assert rule.combine_bands(0, 1, 0) == 1


def test_instruction_reading_of_family_b_equals_family_a():
    def b_with_weekly_boundary(m1, m2, w):
        if (m1 - 2) * (m2 - 2) < 0:
            return 2
        lo, hi = sorted((m1, m2), key=lambda x: abs(x - 2))
        if abs(m1 - m2) == 1 and abs(w - 2) >= abs(hi - 2) and (w - 2) * (hi - 2) >= 0:
            return hi
        return lo

    assert all(b_with_weekly_boundary(*g) == design.family_a(*g) for g in GRID)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, None, "0.5", True])
def test_non_finite_or_non_numeric_input_fails(bad):
    with pytest.raises(ValueError):
        rule.classify_pattern_b_state_v01(bad, 0.0, 0.5)
    with pytest.raises(ValueError):
        rule.classify_pattern_b_state_v01(0.5, bad, 0.5)
    with pytest.raises(ValueError):
        rule.classify_pattern_b_state_v01(0.5, 0.0, bad)


def test_sealed_36_samples_match_predictions_and_seal():
    df = design.load()
    assert len(df) == 36
    assert design.recipe_thresholds(df) == {f: rule.THRESHOLDS[f] for f in rule.FEATURES}
    pred = design.predictions(df)
    on_disk = pd.read_csv(design.PREDICTIONS_PATH, dtype={"sample_id": str})
    assert on_disk.astype(str).equals(pred.astype(str))
    seal = json.loads(design.SEAL_PATH.read_text(encoding="utf-8"))
    for key, value in design.sealed_metrics(df, pred).items():
        assert seal[key] == value
    assert seal["thresholds"] == {f: list(rule.THRESHOLDS[f]) for f in rule.FEATURES}
    assert seal["rule_family"] == "C" and seal["hgt_sample_count"] == 36
    for key, path in (("rule_file_sha256", design.RULE_PATH), ("report_sha256", design.REPORT_PATH),
                      ("predictions_sha256", design.PREDICTIONS_PATH)):
        assert seal[key] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_no_holdout_reference():
    for path in (design.RULE_PATH, _DESIGN, design.PREDICTIONS_PATH):
        text = path.read_text(encoding="utf-8").lower()
        for token in ("holdout_v02", "pattern_b_holdout", "pbhold", "private_manifest"):
            assert token not in text
