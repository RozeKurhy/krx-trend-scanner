"""Focused tests for ABC coverage recovery and common-start discovery."""

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    classify_recovery,
    first_four_qualifying_quarters,
    future_filing_violations,
    qualifies_quarter,
)


def test_01_exactly_90_percent_qualifies():
    assert qualifies_quarter(candidate_count=10, evaluable_count=9, evaluation_error_count=0)


def test_02_89_999_percent_does_not_qualify():
    assert not qualifies_quarter(candidate_count=100000, evaluable_count=89999, evaluation_error_count=0)


def test_03_evaluation_error_blocks_quarter():
    assert not qualifies_quarter(candidate_count=10, evaluable_count=10, evaluation_error_count=1)


def test_04_zero_candidate_quarter_does_not_qualify():
    assert not qualifies_quarter(candidate_count=0, evaluable_count=0, evaluation_error_count=0)


def test_05_first_four_consecutive_qualifying_quarters_selected():
    rows = [{"quarter": f"2021Q{i}", "qualifying_90pct": True} for i in range(1, 5)]
    assert first_four_qualifying_quarters(rows) == "2021Q1"


def test_06_three_qualifying_plus_one_failure_has_no_window():
    rows = [{"quarter": f"2021Q{i}", "qualifying_90pct": i != 4} for i in range(1, 5)]
    assert first_four_qualifying_quarters(rows) is None


def test_07_later_window_does_not_beat_earlier_valid_window():
    rows = [
        {"quarter": "2021Q1", "qualifying_90pct": True},
        {"quarter": "2021Q2", "qualifying_90pct": True},
        {"quarter": "2021Q3", "qualifying_90pct": True},
        {"quarter": "2021Q4", "qualifying_90pct": True},
        {"quarter": "2022Q1", "qualifying_90pct": True},
    ]
    assert first_four_qualifying_quarters(rows) == "2021Q1"


def test_08_future_filing_recovery_is_detected():
    assert future_filing_violations(["2021-08-06", "2021-08-17"], "2021-08-06") == 1


def test_09_existing_evaluable_candidate_is_not_recovery_target():
    assert classify_recovery(
        initial_evaluable=True, final_evaluable=True, opendart_live_used=False,
        evaluation_error=False, local_cache_missing=False, confirmed_historical_absence=False,
    ) == "ALREADY_EVALUABLE"


def test_10_true_unavailable_and_evaluation_error_are_distinct():
    assert classify_recovery(
        initial_evaluable=False, final_evaluable=False, opendart_live_used=False,
        evaluation_error=False, local_cache_missing=False, confirmed_historical_absence=True,
    ) == "TRUE_DATA_UNAVAILABLE"
    assert classify_recovery(
        initial_evaluable=False, final_evaluable=False, opendart_live_used=False,
        evaluation_error=True, local_cache_missing=False, confirmed_historical_absence=False,
    ) == "EVALUATION_ERROR"
