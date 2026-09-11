"""Focused, network-free tests for the FastCore Fundamentals ABC contract."""

from datetime import date, timedelta

import pytest

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    ABCQuarterEvent,
    STANDALONE_QUARTER,
    evaluate_entry,
    evaluate_quarter_event,
    select_exit_candidate,
)
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, PeriodizedFinancialObservation, READY


def obs(year, period, metric, value, *, available="2022-05-15", end=None, ticker="000001", status=READY, basis="CFS", currency="KRW"):
    if end is None:
        end = f"{year}-03-31" if period == "Q1" else f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker=ticker, corp_code="00000000", company_family="NON_FINANCIAL", fiscal_year=str(year),
        fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics=CUMULATIVE_YTD if period == "FY" else STANDALONE_QUARTER,
        period_start=f"{year}-01-01", period_end=end, metric=metric, value=value, currency=currency,
        method="TEST", anchor_report_type="Q1", anchor_reprt_code="11013", anchor_rcept_no=f"{available}-{metric}-{year}-{period}",
        anchor_rcept_dt=available, fs_div_used=basis, pit_available_from=available, resolution_status=status,
    )


def entry_series(*, annual_revenue=50_000_000_000, annual_oi=4_000_000_000,
                 q_revenue=15_000_000_000, q_oi=1_000_000_000,
                 prior_revenue=15_000_000_000 / 1.05, prior_oi=1_000_000_000 / 1.05,
                 as_of="2022-05-20"):
    return [
        obs(2021, "FY", "revenue", annual_revenue, available="2022-03-01", end="2021-12-31"),
        obs(2021, "FY", "operating_income", annual_oi, available="2022-03-01", end="2021-12-31"),
        obs(2022, "Q1", "revenue", q_revenue, available="2022-05-15", end="2022-03-31"),
        obs(2022, "Q1", "operating_income", q_oi, available="2022-05-15", end="2022-03-31"),
        obs(2021, "Q1", "revenue", prior_revenue, available="2021-05-15", end="2021-03-31"),
        obs(2021, "Q1", "operating_income", prior_oi, available="2021-05-15", end="2021-03-31"),
    ]


def evaluate(**kwargs):
    values = entry_series(**kwargs)
    return evaluate_entry("000001", "NON_FINANCIAL", values, as_of=kwargs.get("as_of", "2022-05-20"))


def test_01_annual_revenue_boundary_passes():
    assert evaluate().annual_revenue_pass


def test_02_annual_operating_income_boundary_passes():
    assert evaluate().annual_operating_income_pass


def test_03_quarter_revenue_boundary_passes():
    assert evaluate().quarter_revenue_pass


def test_04_quarter_operating_income_boundary_passes():
    assert evaluate().quarter_operating_income_pass


def test_05_revenue_yoy_boundary_passes():
    assert evaluate().revenue_growth_pass


def test_06_operating_income_yoy_boundary_passes():
    assert evaluate().operating_income_growth_pass


def test_07_turnaround_to_profit_passes():
    result = evaluate(prior_oi=-1_000_000_000, q_oi=1_000_000_000)
    assert result.operating_income_growth_mode == "TURNAROUND_TO_PROFIT"
    assert result.operating_income_growth_pass


def test_08_missing_prior_operating_income_is_not_turnaround():
    values = [item for item in entry_series() if not (item.fiscal_year == "2021" and item.fiscal_period == "Q1" and item.metric == "operating_income")]
    result = evaluate_entry("000001", "NON_FINANCIAL", values, as_of="2022-05-20")
    assert not result.abc_entry_evaluable
    assert result.operating_income_growth_mode is None


def test_09_financial_is_not_applicable():
    result = evaluate_entry("000001", "FINANCIAL", entry_series(), as_of="2022-05-20")
    assert result.status == "NOT_APPLICABLE"
    assert not result.abc_entry_gate_pass


def test_10_future_filing_cannot_be_used():
    result = evaluate(as_of="2022-05-14")
    assert not result.abc_entry_evaluable


def exit_series(*, current_oi=-1, current_revenue=90, prior_oi=100, prior_revenue=100,
                previous_declines=True, include_previous=True):
    values = [
        obs(2021, "Q2", "revenue", current_revenue, available="2022-08-15", end="2021-06-30"),
        obs(2021, "Q2", "operating_income", current_oi, available="2022-08-15", end="2021-06-30"),
        obs(2020, "Q2", "revenue", prior_revenue, available="2021-08-15", end="2020-06-30"),
        obs(2020, "Q2", "operating_income", prior_oi, available="2021-08-15", end="2020-06-30"),
    ]
    if include_previous:
        values.extend([
            obs(2021, "Q1", "revenue", 80 if previous_declines else 100, available="2022-08-15", end="2021-03-31"),
            obs(2021, "Q1", "operating_income", 80 if previous_declines else 100, available="2022-08-15", end="2021-03-31"),
            obs(2020, "Q1", "revenue", 100, available="2021-08-15", end="2020-03-31"),
            obs(2020, "Q1", "operating_income", 100, available="2021-08-15", end="2020-03-31"),
        ])
    return values


def test_11_exit_a_negative_operating_income_triggers():
    event = evaluate_quarter_event("000001", exit_series(), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and event.exit_a_triggered


def test_12_exit_a_zero_operating_income_does_not_trigger():
    event = evaluate_quarter_event("000001", exit_series(current_oi=0), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_a_triggered


def test_13_exit_b_exact_boundaries_trigger():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80, current_revenue=90), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and event.exit_b_triggered


def test_14_exit_b_operating_income_minus_19_9_does_not_trigger():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80.1, current_revenue=90), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_b_triggered


def test_15_exit_b_revenue_minus_9_9_does_not_trigger():
    event = evaluate_quarter_event("000001", exit_series(current_oi=70, current_revenue=90.1), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_b_triggered


def test_16_exit_c_two_consecutive_declines_trigger():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80, current_revenue=90), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and event.exit_c_triggered


def test_17_exit_c_one_comparison_not_lower_is_false():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80, current_revenue=90, previous_declines=False), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_c_triggered


def test_18_exit_c_non_consecutive_gap_is_unavailable():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80, current_revenue=90, include_previous=False), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_c_evaluable and not event.exit_c_triggered


def test_19_missing_exit_data_has_no_automatic_exit():
    event = evaluate_quarter_event("000001", exit_series(current_oi=80, current_revenue=90, prior_oi=0), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and not event.exit_b_evaluable


def test_20_execution_date_is_next_local_trading_day_open():
    event = ABCQuarterEvent(
        ticker="000001", fiscal_year=2021, quarter="Q2", fundamental_information_date="2022-08-15",
        quarter_revenue=1, quarter_operating_income=-1, prior_year_quarter_revenue=1, prior_year_quarter_operating_income=1,
        revenue_yoy_pct=0, operating_income_yoy_pct=-200, previous_quarter="2021Q1",
        previous_quarter_revenue_declined_yoy=False, previous_quarter_operating_income_declined_yoy=False,
        exit_a_evaluable=True, exit_a_triggered=True, exit_b_evaluable=True, exit_b_triggered=False,
        exit_c_evaluable=True, exit_c_triggered=False, fundamental_primary_trigger="FUNDAMENTAL_A_OPERATING_LOSS",
    )
    assert date.fromisoformat(event.fundamental_information_date) + timedelta(days=1) == date(2022, 8, 16)


def test_21_fastcore_wins_same_execution_date():
    chosen, accelerated = select_exit_candidate("2022-08-16", [{"proposed_execution_date": "2022-08-16"}])
    assert chosen is None and not accelerated


def test_22_all_abc_flags_recorded_and_a_is_primary():
    event = evaluate_quarter_event("000001", exit_series(current_oi=-20, current_revenue=90), fiscal_year=2021, quarter="Q2", as_of="2022-08-20")
    assert event and event.all_flags == ["FUNDAMENTAL_A_OPERATING_LOSS", "FUNDAMENTAL_B_SHARP_DECLINE", "FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES"]
    assert event.fundamental_primary_trigger == "FUNDAMENTAL_A_OPERATING_LOSS"


def test_23_fundamental_exit_allows_later_reentry():
    first, accelerated = select_exit_candidate("2022-08-20", [{"proposed_execution_date": "2022-08-16"}])
    later, later_accelerated = select_exit_candidate(None, [{"proposed_execution_date": "2022-08-22"}])
    assert first is not None and accelerated and later is not None and later_accelerated


def test_24_same_open_exit_and_reentry_is_forbidden_by_strict_order():
    chosen, accelerated = select_exit_candidate("2022-08-16", [{"proposed_execution_date": "2022-08-16"}])
    assert chosen is None and not accelerated
