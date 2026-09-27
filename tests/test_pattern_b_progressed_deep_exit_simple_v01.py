from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_pattern_b_progressed_deep_exit_simple_v01 as runner


def _event(ticker: str, stage: str, date: str = "2020-01-31") -> dict:
    return {
        "ticker": ticker,
        "isu_cd": f"KR{ticker}",
        "entry_signal_date": date,
        "pattern_a_stage": stage,
        "pattern_a_requested_asof": date,
        "pattern_a_lookahead_free": True,
    }


def test_candidate_selector_keeps_only_exact_progressed_keys() -> None:
    events = [
        _event("000001", "PROGRESSED"),
        _event("000002", "TRANSITION"),
        _event("000003", "PROGRESSED", "2020-02-28"),
    ]

    by_identity, selected = runner._select_progressed_events(
        events,
        {("000001", "KR000001", "2020-01-31"), ("000003", "KR000003", "2020-02-28")},
    )

    assert len(selected) == 2
    assert set(by_identity) == {("000001", "KR000001"), ("000003", "KR000003")}
    assert all(event["entry_signal_status"] == "PENDING" for event in selected)


def test_candidate_selector_rejects_nonexact_or_lookahead_stage() -> None:
    event = _event("000001", "PROGRESSED")
    event["pattern_a_requested_asof"] = "2020-02-28"

    with pytest.raises(RuntimeError, match="non-exact or lookahead-contaminated"):
        runner._select_progressed_events([event], {("000001", "KR000001", "2020-01-31")})


def test_loss_rescue_only_counts_realized_test_outcomes_as_rescues() -> None:
    pairs = pd.DataFrame([
        {
            "control_trade_status": "REALIZED",
            "control_final_or_marked_gross_return_pct": -35.0,
            "test_outcome_basis": "REALIZED_GROSS",
            "test_final_or_marked_gross_return_pct": -10.0,
        },
        {
            "control_trade_status": "REALIZED",
            "control_final_or_marked_gross_return_pct": -35.0,
            "test_outcome_basis": "CUTOFF_MARK",
            "test_final_or_marked_gross_return_pct": 5.0,
        },
    ])

    frame, summary = runner._loss_rescue_analysis(pairs)

    assert summary["-30"]["control_loss_denominator"] == 2
    assert summary["-30"]["test_realized_rescue_count"] == 1
    at_minus_30 = frame.loc[frame["control_loss_threshold_pct"].eq(-30)]
    assert at_minus_30["rescued_after_realized_test_exit"].tolist() == [True, None]
