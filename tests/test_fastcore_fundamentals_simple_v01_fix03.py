"""Focused FIX03 tests for COMMON_START quarter sequencing."""

from __future__ import annotations

import pandas as pd

from scripts import run_fastcore_fundamentals_simple_v01 as runner


def test_quarter_sequence_from_q1():
    assert runner._quarter_sequence("2017Q1") == [
        "2017Q1", "2017Q2", "2017Q3", "2017Q4",
    ]


def test_quarter_sequence_from_q2_rolls_year():
    assert runner._quarter_sequence("2017Q2") == [
        "2017Q2", "2017Q3", "2017Q4", "2018Q1",
    ]


def test_quarter_sequence_from_q3_rolls_year():
    assert runner._quarter_sequence("2017Q3") == [
        "2017Q3", "2017Q4", "2018Q1", "2018Q2",
    ]


def test_quarter_sequence_from_q4_rolls_year():
    assert runner._quarter_sequence("2017Q4") == [
        "2017Q4", "2018Q1", "2018Q2", "2018Q3",
    ]


def _coverage(rows: list[tuple[str, float, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["quarter", "evaluable_rate", "total_nonfinancial_candidates"],
    )


def test_select_common_start_uses_first_valid_actual_sequence(monkeypatch):
    coverage = _coverage([
        ("2017Q1", 80.0, 10),
        ("2017Q2", 91.0, 10),
        ("2017Q3", 95.0, 10),
        ("2017Q4", 93.0, 10),
        ("2018Q1", 92.0, 10),
    ])
    monkeypatch.setattr(runner, "_first_trading_day_of_quarter", lambda label: f"{label}-DAY1")

    start, reason = runner.select_common_start(coverage)

    assert start == "2017Q2-DAY1"
    assert reason["selected_quarter"] == "2017Q2"
    assert reason["quarters"] == ["2017Q2", "2017Q3", "2017Q4", "2018Q1"]


def test_select_common_start_rejects_missing_quarter():
    coverage = _coverage([
        ("2017Q2", 91.0, 10),
        ("2017Q3", 95.0, 10),
        ("2018Q1", 92.0, 10),
        ("2018Q2", 93.0, 10),
    ])

    start, reason = runner.select_common_start(coverage)

    assert start is None
    assert reason["reason"] == "NO_FOUR_CONSECUTIVE_QUARTERS_AT_90_PERCENT"
