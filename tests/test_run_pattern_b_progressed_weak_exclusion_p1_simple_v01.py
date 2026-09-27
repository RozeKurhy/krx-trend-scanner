from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as study
from scripts import run_pattern_b_pure_simple_backtest_v01 as base


def test_p1_window_resolves_to_instruction_dates() -> None:
    _, resolved = study._resolve_p1(study.ROOT)

    assert resolved["window_id"] == "P1"
    assert resolved["effective_start"] == "2014-01-02"
    assert resolved["effective_end"] == "2026-08-31"
    assert resolved["execution_support"] == "2026-09-01"


def test_p2_p3_windows_resolve_to_instruction_dates() -> None:
    expected = {
        "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
        "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
        "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
        "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
    }
    for window_id, dates in expected.items():
        _, resolved = study._resolve_window(study.ROOT, window_id)
        assert (
            resolved["effective_start"], resolved["effective_end"], resolved["execution_support"]
        ) == dates


def test_only_exact_weak_to_progressed_transition_is_excluded() -> None:
    assert study._filter_decisions("PROGRESSED", "WEAK") == (
        "PASS_PATTERN_A_PROGRESSED", "REJECTED_PREVIOUS_STAGE_WEAK"
    )
    assert study._filter_decisions("PROGRESSED", "UNAVAILABLE") == (
        "PASS_PATTERN_A_PROGRESSED", "PASS_PATTERN_A_PROGRESSED"
    )
    assert study._filter_decisions("TRANSITION", "WEAK") == (
        "REJECTED_PATTERN_A_NOT_PROGRESSED", "REJECTED_PATTERN_A_NOT_PROGRESSED"
    )


def test_window_end_entry_is_not_filled_on_exit_only_execution_support() -> None:
    period_end = "2026-08-31"
    support = "2026-09-01"
    event = {
        "ticker": "000001", "isu_cd": "KR7000000001", "market_at_signal": "KOSPI",
        "component_id": "000001:KR7000000001:000", "entry_signal_date": period_end,
        "previous_state_date": "2026-07-31", "previous_state": "NORMAL",
        "entry_signal_state": "DEPRESSED", "entry_signal_status": "PENDING",
    }
    observations = [{
        "ticker": "000001", "isu_cd": "KR7000000001", "component_id": event["component_id"],
        "snapshot_date": period_end, "state": "DEPRESSED",
    }]
    daily = pd.DataFrame(
        {"open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0], "market": ["KOSPI"]},
        index=pd.DatetimeIndex([support]),
    )

    trades, _ = base._simulate_identity(
        observations, [event], {event["component_id"]: daily}, period_end
    )
    assert trades == []
    assert event["entry_signal_status"] == "ENTRY_UNFILLED_AFTER_CUTOFF"

    study._normalize_unfilled_window_end_entries([event], period_end)
    assert event["entry_signal_status"] == "ENTRY_NOT_FILLED_AFTER_WINDOW_END"
    assert event["entry_execution_date"] is None
    assert event["window_entry_support_not_allowed_date"] == support


def test_p1_execution_support_completes_only_a_pre_end_exit() -> None:
    period_end = "2026-08-31"
    support = "2026-09-01"
    trade = {
        "ticker": "000001", "isu_cd": "KR7000000001", "component_id": "component",
        "trade_status": "OPEN_AT_CUTOFF", "exit_signal_date": period_end,
        "exit_signal_state": "NORMAL", "exit_fill_status": "UNFILLED_BY_CUTOFF",
        "latest_state_date": period_end, "cutoff_close": 9.0,
        "valuation_status": "MARKED_EXACT_CUTOFF_CLOSE",
    }
    pending = {"kind": "EXIT", "signal_date": period_end, "fill_date": support, "trade": trade}
    daily = pd.DataFrame(
        {"open": [11.0], "high": [11.0], "low": [11.0], "close": [11.0], "market": ["KOSPI"]},
        index=pd.Index([support]),
    )

    state = study._finish_exit_on_support(
        [trade], {"position": trade, "pending": pending}, {"component": daily}, period_end, support
    )

    assert state == {"position": None, "pending": None}
    assert trade["trade_status"] == "REALIZED"
    assert trade["exit_execution_date"] == support
    assert trade["exit_reference_open"] == 11.0
    assert trade["exit_fill_status"] == "FILLED"
    assert trade["window_execution_support_exit_fill"] is True
    assert "cutoff_close" not in trade


def _scenario_summary(median: float, win: float, ge50: float, le30: float, le50: float, deep: float) -> dict:
    return {
        "realized_gross": {
            "median_pct": median, "win_rate_pct": win, "ge_50_rate_pct": ge50,
            "le_30_rate_pct": le30, "le_50_rate_pct": le50,
        },
        "deep_cohort": {"deep_arrival_rate_of_filled_pct": deep},
    }


def _annual_risk_table(year_count: int, control: tuple[float, float], test: tuple[float, float]) -> pd.DataFrame:
    rows = []
    for year in range(2018, 2018 + year_count):
        rows.extend([
            {"scenario": "CONTROL", "entry_year": year, "realized_le_30_rate_pct": control[0], "realized_le_50_rate_pct": control[1]},
            {"scenario": "TEST", "entry_year": year, "realized_le_30_rate_pct": test[0], "realized_le_50_rate_pct": test[1]},
        ])
    return pd.DataFrame(rows)


def test_verdict_improved_uses_exact_tolerance_and_multiyear_risk_spread() -> None:
    control = _scenario_summary(10.0, 60.0, 5.0, 10.0, 5.0, 25.0)
    test = _scenario_summary(9.9, 59.9, 4.9, 9.0, 4.0, 24.0)
    annual = _annual_risk_table(3, (10.0, 5.0), (9.0, 4.0))

    verdict, rubric = study._verdict(control, test, annual)

    assert verdict == "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED"
    assert rubric["quality_all_nonworse"] is True
    assert rubric["risk_metrics_improved_count"] == 3
    assert rubric["risk_improved_entry_years"] == [2018, 2019, 2020]


def test_verdict_no_benefit_and_mixed_boundaries_follow_instruction() -> None:
    control = _scenario_summary(10.0, 60.0, 5.0, 10.0, 5.0, 25.0)
    no_benefit = _scenario_summary(9.0, 58.0, 4.0, 10.0, 5.0, 25.0)
    annual = _annual_risk_table(4, (10.0, 5.0), (10.0, 5.0))
    assert study._verdict(control, no_benefit, annual)[0] == "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_NO_BENEFIT"

    mixed = _scenario_summary(10.0, 60.0, 5.0, 9.0, 5.0, 24.0)
    short_spread = _annual_risk_table(2, (10.0, 5.0), (9.0, 5.0))
    assert study._verdict(control, mixed, short_spread)[0] == "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_MIXED"


def test_verdict_label_uses_non_p1_window_without_changing_the_rule() -> None:
    control = _scenario_summary(10.0, 60.0, 5.0, 10.0, 5.0, 25.0)
    test = _scenario_summary(10.0, 60.0, 5.0, 9.0, 4.0, 24.0)
    annual = _annual_risk_table(3, (10.0, 5.0), (9.0, 4.0))

    verdict, _ = study._verdict(control, test, annual, "P2-1")

    assert verdict == "PATTERN_B_PROGRESSED_WEAK_FILTER_P2_1_IMPROVED"


def test_deep_arrival_for_open_position_stops_at_window_cutoff() -> None:
    trade = {
        "ticker": "000001", "isu_cd": "KR7000000001", "component_id": "000001:KR7000000001:000",
        "entry_signal_date": "2025-04-30", "exit_signal_date": None,
    }
    samples = pd.DataFrame([
        {"ticker": trade["ticker"], "isu_cd": trade["isu_cd"], "component_id": trade["component_id"], "snapshot_date": "2025-04-30", "state": "DEPRESSED"},
        {"ticker": trade["ticker"], "isu_cd": trade["isu_cd"], "component_id": trade["component_id"], "snapshot_date": "2025-05-30", "state": "DEPRESSED"},
        {"ticker": trade["ticker"], "isu_cd": trade["isu_cd"], "component_id": trade["component_id"], "snapshot_date": "2025-06-30", "state": "DEEP_DEPRESSED"},
    ])

    assert study._deep_trade_keys([trade], samples, "2025-05-30") == set()
    samples.loc[samples["snapshot_date"] == "2025-05-30", "state"] = "DEEP_DEPRESSED"
    assert study._deep_trade_keys([trade], samples, "2025-05-30") == {study._key(trade)}


def test_annual_comparison_marks_fixed_cutoff_year_as_right_censored() -> None:
    event = {"entry_signal_date": "2025-04-30"}

    annual = study._annual_comparison([event], [], [], [], [], "2025-05-30")

    assert annual["right_censored_recent_year"].tolist() == [True, True]


def test_direct_effect_reports_realized_weak_outcomes_and_independent_replay_delta() -> None:
    weak = {
        "ticker": "000001", "isu_cd": "KR7000000001", "entry_signal_date": "2020-01-31",
        "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "WEAK",
        "control_filter_status": "PASS_PATTERN_A_PROGRESSED",
        "test_filter_status": "REJECTED_PREVIOUS_STAGE_WEAK",
    }
    shared = {
        "ticker": "000001", "isu_cd": "KR7000000001", "entry_signal_date": "2020-02-29",
        "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "BASE",
        "control_filter_status": "PASS_PATTERN_A_PROGRESSED",
        "test_filter_status": "PASS_PATTERN_A_PROGRESSED",
    }
    replay_only = {
        "ticker": "000001", "isu_cd": "KR7000000001", "entry_signal_date": "2020-03-31",
        "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION",
        "control_filter_status": "PASS_PATTERN_A_PROGRESSED",
        "test_filter_status": "PASS_PATTERN_A_PROGRESSED",
    }
    control_trades = [
        {**weak, "trade_status": "REALIZED", "gross_return_pct": -40.0},
        {**shared, "trade_status": "REALIZED", "gross_return_pct": 60.0},
    ]
    test_trades = [
        {**shared, "trade_status": "REALIZED", "gross_return_pct": 60.0},
        {**replay_only, "trade_status": "REALIZED", "gross_return_pct": 20.0},
    ]

    result = study._direct_effect([weak, shared, replay_only], control_trades, test_trades).set_index("group")

    assert result.loc["CONTROL_WEAK_ORIGIN_FILLED", "filled"] == 1
    assert result.loc["CONTROL_WEAK_ORIGIN_FILLED", "loser_count"] == 1
    assert result.loc["CONTROL_WEAK_ORIGIN_FILLED", "le_30_count"] == 1
    assert result.loc["TEST_NEW_ENTRY_KEYS_VS_CONTROL", "filled"] == 1
    assert result.loc["TEST_INDEPENDENT_MINUS_CONTROL_POSTHOC", "filled"] == 1
