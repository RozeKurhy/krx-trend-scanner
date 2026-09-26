"""Pattern B HGT raw feature runner — public-output guards (synthetic data only)."""

from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path
import subprocess

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


def _rows_and_provenance() -> tuple[list[dict], list[dict]]:
    daily = _daily()
    pairs = [runner.feature_row(m["sample_id"], daily, m["as_of"]) for m in _manifest()]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _rows() -> list[dict]:
    return _rows_and_provenance()[0]


def test_sample_id_set_must_be_exact():
    runner.validate_sample_ids(list(runner.SAMPLE_IDS))
    with pytest.raises(ValueError):
        runner.validate_sample_ids(list(runner.SAMPLE_IDS[:-1]))
    with pytest.raises(ValueError):
        runner.validate_sample_ids(list(runner.SAMPLE_IDS[:-1]) + ["PBHGT_001"])


def test_public_rows_have_exactly_15_contract_columns():
    rows = _rows()
    runner.validate_public_rows(rows, _manifest())
    assert len(runner.OUTPUT_COLUMNS) == 15
    assert tuple(rows[0]) == runner.OUTPUT_COLUMNS
    assert not runner.FORBIDDEN_COLUMNS & set(rows[0])


def test_private_provenance_is_separate():
    _, provenance = _rows_and_provenance()
    first = provenance[0]
    assert set(first) == {"sample_id", *runner.PROVENANCE_COLUMNS}
    assert first["requested_history_start"] == "1900-01-01"
    assert first["effective_history_end"] <= "2023-06-30"
    assert first["monthly_last_bar"] <= "2023-06-30"
    assert first["weekly_last_bar"] <= "2023-06-30"


@pytest.mark.parametrize(
    "extra",
    [{"ticker": "900000"}, {"stock_name": "테스트0"}, {"as_of": "2023-06-30"},
     {"label": "NORMAL"}, {"confidence": "HIGH"}, {"note": "x"},
     {"monthly_last_bar": "2023-06-30"}, {"weekly_bar_count": 595}],
)
def test_public_rows_reject_forbidden_columns(extra):
    rows = _rows()
    rows[0] = {**rows[0], **extra}
    with pytest.raises(ValueError):
        runner.validate_public_rows(rows, _manifest())


def test_public_rows_reject_ticker_values():
    rows = _rows()
    manifest = _manifest()
    rows[3][runner.OUTPUT_COLUMNS[1]] = manifest[0]["ticker"]
    with pytest.raises(ValueError):
        runner.validate_public_rows(rows, manifest)


def test_baseline_projection_detects_value_changes():
    rows = _rows()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=runner.OUTPUT_COLUMNS + ("monthly_bar_count",))
    writer.writeheader()
    writer.writerows({**r, "monthly_bar_count": 1} for r in rows)
    assert runner.compare_with_baseline(rows, buf.getvalue()) == []
    changed = [dict(r) for r in rows]
    changed[0][runner.OUTPUT_COLUMNS[1]] = "0.123"
    assert runner.compare_with_baseline(changed, buf.getvalue()) == [f"PBHGT_001.{runner.OUTPUT_COLUMNS[1]}"]


def test_committed_public_csv_matches_first_sealed_values():
    try:
        baseline = runner._baseline_csv()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("baseline commit not available")
    with runner.DEFAULT_OUT.open(encoding="utf-8") as fh:
        current = list(csv.DictReader(fh))
    assert tuple(current[0]) == runner.OUTPUT_COLUMNS
    assert len(current) == 36
    assert runner.compare_with_baseline(current, baseline) == []


def test_feature_row_rejects_rows_after_as_of():
    daily = _daily()
    future = pd.DataFrame(
        {"high": [101.0], "low": [99.0], "close": [100.0]}, index=[pd.Timestamp("2023-07-03")]
    )
    with pytest.raises(RuntimeError):
        runner.feature_row("PBHGT_001", pd.concat([daily, future]), "2023-06-30")
