"""Pattern B HGT raw feature runner — public-output guards (synthetic data only)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/compute_pattern_b_hgt_feature_raw_v01.py"
_spec = importlib.util.spec_from_file_location("compute_pattern_b_hgt_feature_raw_v01", _SCRIPT)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _manifest() -> list[dict]:
    return [
        {"sample_id": sid, "ticker": f"9{i:05d}", "stock_name": f"테스트{i}", "as_of": "2023-06-30"}
        for i, sid in enumerate(runner.SAMPLE_IDS)
    ]


def _daily() -> pd.DataFrame:
    dates = pd.bdate_range("2012-01-02", "2023-06-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, len(dates))))
    return pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=dates)


def _rows() -> list[dict]:
    daily = _daily()
    return [runner.feature_row(m["sample_id"], daily, m["as_of"]) for m in _manifest()]


def test_sample_id_set_must_be_exact():
    runner.validate_sample_ids(list(runner.SAMPLE_IDS))
    with pytest.raises(ValueError):
        runner.validate_sample_ids(list(runner.SAMPLE_IDS[:-1]))
    with pytest.raises(ValueError):
        runner.validate_sample_ids(list(runner.SAMPLE_IDS[:-1]) + ["PBHGT_001"])


def test_public_rows_have_contract_columns_only():
    rows = _rows()
    runner.validate_public_rows(rows, _manifest())
    assert tuple(rows[0]) == runner.OUTPUT_COLUMNS
    assert not runner.FORBIDDEN_COLUMNS & set(rows[0])
    assert rows[0]["requested_history_start"] == "1900-01-01"
    assert rows[0]["monthly_last_bar"] <= "2023-06-30"


def test_public_rows_reject_manifest_columns():
    rows = _rows()
    manifest = _manifest()
    leaked = [{**r, "ticker": m["ticker"], "as_of": m["as_of"]} for r, m in zip(rows, manifest)]
    with pytest.raises(ValueError):
        runner.validate_public_rows(leaked, manifest)


def test_public_rows_reject_ticker_values():
    rows = _rows()
    manifest = _manifest()
    rows[3]["effective_history_start"] = manifest[0]["ticker"]
    with pytest.raises(ValueError):
        runner.validate_public_rows(rows, manifest)


def test_feature_row_rejects_rows_after_as_of():
    daily = _daily()
    future = pd.DataFrame(
        {"high": [101.0], "low": [99.0], "close": [100.0]}, index=[pd.Timestamp("2023-07-03")]
    )
    with pytest.raises(RuntimeError):
        runner.feature_row("PBHGT_001", pd.concat([daily, future]), "2023-06-30")
