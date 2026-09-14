"""Focused tests for the FastCore V3 failure-mode review."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import analyze_fastcore_v3_failure_review_v01 as review


def _path(highs: list[float], closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2021-04-01", periods=len(highs), freq="D")
    return pd.DataFrame({"high": highs, "close": closes}, index=index)


def test_first_winner_activation_uses_running_high_hwm_and_20_percent_boundary() -> None:
    path = _path([105.0, 119.0, 120.0], [104.0, 110.0, 118.0])
    assert review.first_winner_activation_date(path, 100.0) == pd.Timestamp("2021-04-03")
    assert review.first_winner_activation_date(_path([105.0, 119.999], [104.0, 110.0]), 100.0) is None


def test_activation_before_loss_breach_is_excluded_from_pre_activation_window() -> None:
    path = _path([100.0, 120.0], [90.0, 118.0])
    activation = review.first_winner_activation_date(path, 100.0)
    assert activation == pd.Timestamp("2021-04-02")
    before_activation = path.loc[path.index < activation]
    assert review.first_breach_trading_days(before_activation, 100.0, -10.0) == 0
    assert review.first_breach_trading_days(path.loc[path.index < path.index[0]], 100.0, -10.0) is None


def test_threshold_breach_days_are_zero_based_from_entry_execution_day() -> None:
    path = _path([100.0, 101.0, 102.0], [99.0, 95.0, 89.0])
    assert review.first_breach_trading_days(path, 100.0, -10.0) == 2
    assert review.first_breach_trading_days(path, 100.0, -15.0) is None


def test_official_cohort_counts_sum_to_973() -> None:
    matched = pd.read_csv(Path("artifacts/backtests/fastcore_v3_matched_ab_official_v01/matched_trades.csv"))
    counts = review.cohort_counts(matched)
    assert counts == {review.PRE_WINNER: 236, review.WINNER_CAPABLE: 737}
    assert sum(counts.values()) == 973


def test_representative_tie_breaker_is_deterministic() -> None:
    frame = pd.DataFrame([
        {"ticker": "000002", "entry_execution_date": "2021-04-01", "control_trade_id": "B", "return_delta_v3_minus_v2": -10.0},
        {"ticker": "000001", "entry_execution_date": "2021-04-01", "control_trade_id": "A", "return_delta_v3_minus_v2": -10.0},
    ])
    result = review._representative_records(frame, "TEST", limit=2, ascending=True)
    assert [row["ticker"] for row in result] == ["000001", "000002"]
