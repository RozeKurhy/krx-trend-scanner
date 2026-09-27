from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_pattern_a_entry_filter_simple_v01 as study


def _event(stage: str, day: str) -> dict[str, object]:
    return {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "entry_signal_date": day,
        "pattern_a_stage": stage,
        "entry_signal_status": "SUPPRESSED_ALREADY_HOLDING",
        "trade_id": "old",
        "entry_execution_date": "old",
        "entry_reference_open": 1.0,
        "status_reason": "old reason",
    }


def test_stage_filter_selects_only_exact_stage_and_copies_events() -> None:
    source = [_event("TRANSITION", "2020-01-31"), _event("PROGRESSED", "2020-02-28")]

    grouped, selected = study._copy_stage_events(source, "TRANSITION")

    assert len(selected) == 1
    assert list(grouped) == [("000001", "KR7000000001")]
    assert selected[0]["pattern_a_stage"] == "TRANSITION"
    assert selected[0]["entry_signal_status"] == "PENDING"
    assert selected[0]["trade_id"] is None
    assert source[0]["entry_signal_status"] == "SUPPRESSED_ALREADY_HOLDING"
    assert source[0]["trade_id"] == "old"


def test_year_summary_uses_realized_metrics_and_filled_open_rate() -> None:
    events = [_event("TRANSITION", "2020-01-31"), _event("TRANSITION", "2020-06-30")]
    trades = [
        {
            "entry_signal_date": "2020-01-31",
            "trade_status": "REALIZED",
            "gross_return_pct": 60.0,
        },
        {
            "entry_signal_date": "2020-06-30",
            "trade_status": "OPEN_AT_CUTOFF",
            "gross_return_pct": None,
        },
    ]

    result = study._annual_summary({"TRANSITION": (events, trades)})
    row = result.iloc[0]

    assert row["raw_entry_candidates"] == 2
    assert row["filled_trades"] == 2
    assert row["realized_trades"] == 1
    assert row["open_at_cutoff"] == 1
    assert row["open_rate_pct"] == 50.0
    assert row["realized_median_gross_pct"] == 60.0
    assert row["realized_ge_50_rate_pct"] == 100.0


def _summary(median: float, win: float, ge50: float, le30: float, le50: float, open_le30: float, open_le50: float, deep_rate: float, deep_loss: float) -> dict[str, object]:
    gross = study.base._metric_summary([median])
    gross.update({
        "median_pct": median,
        "expectancy_pct": median,
        "win_rate_pct": win,
        "ge_50_rate_pct": ge50,
        "le_30_rate_pct": le30,
        "le_50_rate_pct": le50,
    })
    opened = study.base._metric_summary([-1.0])
    opened.update({"le_30_rate_pct": open_le30, "le_50_rate_pct": open_le50})
    return {
        "closed_gross": gross,
        "open_marked_gross": opened,
        "post_entry_deep_state": {
            "deep_arrival_rate_of_filled_pct": deep_rate,
            "deep_realized_loss_rate_pct": deep_loss,
        },
    }


def test_equal_metrics_do_not_create_false_improvement_verdict() -> None:
    same = _summary(10.0, 70.0, 20.0, 5.0, 1.0, 10.0, 2.0, 25.0, 40.0)
    summaries = {"CONTROL": same, "TRANSITION": same, "PROGRESSED": same}
    annual = pd.DataFrame([
        {"strategy": name, "entry_signal_year": 2020, "realized_trades": 10,
         "realized_median_gross_pct": 10.0, "realized_win_rate_pct": 70.0}
        for name in summaries
    ])

    assessments, verdict = study._candidate_assessments(summaries, annual)

    assert verdict == "PATTERN_B_PATTERN_A_ENTRY_FILTER_NO_BENEFIT"
    assert assessments["TRANSITION"]["candidate_assessment"] == "NO_BENEFIT"


def test_profit_risk_tradeoff_is_classified_as_mixed() -> None:
    control = _summary(10.0, 70.0, 20.0, 5.0, 1.0, 10.0, 2.0, 25.0, 40.0)
    candidate = _summary(12.0, 75.0, 25.0, 7.0, 2.0, 12.0, 3.0, 28.0, 45.0)
    summaries = {"CONTROL": control, "TRANSITION": candidate, "PROGRESSED": control}
    annual = pd.DataFrame([
        {"strategy": name, "entry_signal_year": 2020, "realized_trades": 10,
         "realized_median_gross_pct": (12.0 if name == "TRANSITION" else 10.0),
         "realized_win_rate_pct": (75.0 if name == "TRANSITION" else 70.0)}
        for name in summaries
    ])

    assessments, verdict = study._candidate_assessments(summaries, annual)

    assert verdict == "PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED"
    assert assessments["TRANSITION"]["candidate_assessment"] == "MIXED"
    assert assessments["TRANSITION"]["recommend_for_next_validation"] is True


def test_csv_nan_is_normalized_as_unresolved_mark() -> None:
    frame = pd.DataFrame([{"mark_to_cutoff_gross_return_pct": float("nan")}])

    record = study._clean_records(frame)[0]

    assert record["mark_to_cutoff_gross_return_pct"] is None
    assert study._finite_number(record["mark_to_cutoff_gross_return_pct"]) is False


def test_deep_cohort_stops_at_normal_exit_signal_boundary() -> None:
    samples = pd.DataFrame([
        {"ticker": "000001", "isu_cd": "KR7000000001", "snapshot_date": "2020-01-31", "component_id": "component", "state": "DEPRESSED"},
        {"ticker": "000001", "isu_cd": "KR7000000001", "snapshot_date": "2020-02-28", "component_id": "component", "state": "DEEP_DEPRESSED"},
        {"ticker": "000001", "isu_cd": "KR7000000001", "snapshot_date": "2020-03-31", "component_id": "component", "state": "NORMAL"},
    ])
    trades = [
        {"trade_id": "held_through_deep", "ticker": "000001", "isu_cd": "KR7000000001", "entry_signal_date": "2020-01-31", "exit_signal_date": "2020-03-31", "component_id": "component"},
        {"trade_id": "exited_before_deep", "ticker": "000001", "isu_cd": "KR7000000001", "entry_signal_date": "2020-01-31", "exit_signal_date": "2020-02-15", "component_id": "component"},
    ]

    cohort = study._deep_cohort(trades, samples)

    assert [trade["trade_id"] for trade in cohort] == ["held_through_deep"]
