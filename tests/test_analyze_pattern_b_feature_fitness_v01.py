"""Pattern B Feature fitness diagnostics — input contract and math (synthetic data only)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/analyze_pattern_b_feature_fitness_v01.py"
_spec = importlib.util.spec_from_file_location("analyze_pattern_b_feature_fitness_v01", _SCRIPT)
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)


def _hgt() -> pd.DataFrame:
    labels = [l for l, n in fit.EXPECTED_LABEL_COUNTS.items() for _ in range(n)]
    confidence = ["HIGH"] * 22 + ["MEDIUM"] * 14
    return pd.DataFrame({
        "sample_id": list(fit.SAMPLE_IDS), "label": labels, "confidence": confidence, "note": ["n"] * 36,
    })


def _raw(hgt: pd.DataFrame) -> pd.DataFrame:
    ordinal = hgt["label"].map(fit.ORDINAL).to_numpy(dtype=float)
    data = {"sample_id": hgt["sample_id"]}
    for i, feature in enumerate(fit.FEATURES):
        data[feature] = ordinal + 0.01 * np.arange(36) + i
        data[f"{feature}_status"] = "OK"
    return pd.DataFrame(data)[list(fit.RAW_COLUMNS)]


def test_ordinal_is_exactly_zero_to_four():
    assert fit.ORDINAL == {
        "DEEP_DEPRESSED": 0, "DEPRESSED": 1, "NORMAL": 2, "OVERHEATED": 3, "EXTREME_OVERHEATED": 4,
    }


def test_valid_inputs_join_36_rows_without_private_columns():
    hgt = _hgt()
    joined = fit.load_joined(hgt, _raw(hgt))
    assert len(joined) == 36
    assert not {"ticker", "stock_name", "as_of"} & set(joined.columns)
    assert not {"ticker", "stock_name", "as_of"} & set(fit.RAW_COLUMNS + fit.HGT_COLUMNS)


def test_sample_id_mismatch_fails():
    hgt = _hgt()
    raw = _raw(hgt)
    raw.loc[0, "sample_id"] = "PBHGT_099"
    with pytest.raises(fit.InputContractError):
        fit.load_joined(hgt, raw)
    dup = _hgt()
    dup.loc[1, "sample_id"] = "PBHGT_001"
    with pytest.raises(fit.InputContractError):
        fit.load_joined(dup, _raw(_hgt()))


def test_label_or_confidence_contract_mismatch_fails():
    hgt = _hgt()
    hgt.loc[0, "label"] = "NORMAL"
    with pytest.raises(fit.InputContractError):
        fit.load_joined(hgt, _raw(_hgt()))
    hgt = _hgt()
    hgt.loc[0, "confidence"] = "LOW"
    with pytest.raises(fit.InputContractError):
        fit.load_joined(hgt, _raw(_hgt()))


def test_non_ok_raw_status_fails():
    hgt = _hgt()
    raw = _raw(hgt)
    raw.loc[5, f"{fit.FEATURES[2]}_status"] = "INSUFFICIENT_BARS"
    with pytest.raises(fit.InputContractError):
        fit.load_joined(hgt, raw)


def test_label_summary_and_spearman_on_synthetic_fixture():
    df = pd.DataFrame({
        "label": ["DEEP_DEPRESSED", "DEEP_DEPRESSED", "NORMAL", "NORMAL", "NORMAL", "OVERHEATED"],
        "x": [1.0, 3.0, 4.0, 6.0, 8.0, 10.0],
    })
    s = fit.label_summary(df, "x")
    assert s.at["DEEP_DEPRESSED", "n"] == 2
    assert s.at["DEEP_DEPRESSED", "median"] == 2.0
    assert s.at["DEEP_DEPRESSED", "q1"] == 1.5 and s.at["DEEP_DEPRESSED", "q3"] == 2.5
    assert s.at["NORMAL", "median"] == 6.0 and s.at["NORMAL", "q1"] == 5.0
    assert s.at["DEPRESSED", "n"] == 0
    # Monotone relation -> rho 1; reversed -> -1; tied ranks share the mean rank.
    assert fit.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert fit.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    x, y = [1, 2, 3, 4], [0, 0, 1, 1]
    rx, ry = np.array([1, 2, 3, 4.0]), np.array([1.5, 1.5, 3.5, 3.5])
    assert fit.spearman(x, y) == pytest.approx(np.corrcoef(rx, ry)[0, 1])


def test_ordering_and_overlap_flags():
    summary = pd.DataFrame(
        {"median": [0.0, 1.0, 2.0, 1.5, 3.0], "q1": [-0.1, 0.9, 1.0, 1.4, 2.9], "q3": [0.1, 1.1, 2.5, 1.6, 3.1]},
        index=list(fit.LABEL_ORDER),
    )
    ordering = fit.median_ordering(summary)
    assert [o["expected"] for o in ordering] == [True, True, False, True]
    overlap = fit.iqr_overlap(summary)
    assert [o["overlap"] for o in overlap] == [False, True, True, False]
