from __future__ import annotations

import pandas as pd

from scripts import close_etf_36_zero_ohlc_sentinel_clean_eligibility_v01 as closure


def test_extracts_current_signal_path_max_history() -> None:
    score, stage = closure.study.base._read_contracts()
    lookbacks = closure.extract_signal_path_lookbacks(score, stage)

    assert lookbacks["max_bars_by_timeframe"] == {"monthly": 36, "weekly": 200, "daily": 20}
    assert lookbacks["controlling_feature"] == "close_vs_wma200_pct"
    assert any(row["feature"] == "pattern_a.range_position" and row["required_history_bars"] == 36
               for row in lookbacks["features"])


def test_sentinel_free_requires_each_actual_timeframe_tail_to_be_clear() -> None:
    monthly = pd.DataFrame(index=pd.date_range("2020-01-31", periods=40, freq="ME"))
    weekly = pd.DataFrame(index=pd.date_range("2020-01-03", periods=220, freq="W-FRI"))
    daily = pd.DataFrame(index=pd.bdate_range("2025-01-01", periods=25))
    lookbacks = {"max_bars_by_timeframe": {"monthly": 36, "weekly": 200, "daily": 20}}
    sentinel = {
        "months": {monthly.index[-36]},
        "weeks": {weekly.index[-200]},
        "dates": {daily.index[-20]},
    }

    status = closure._sentinel_free_at(monthly, weekly, daily, sentinel, lookbacks)

    assert not status["clean"]
    assert len(status["monthly_sentinel_labels"]) == 1
    assert len(status["weekly_sentinel_labels"]) == 1
    assert len(status["daily_sentinel_dates"]) == 1


def test_span_replay_starts_at_clean_date_and_marks_cutoff_exclusion() -> None:
    base = {
        "ticker": "123456", "window_id": "P1", "window_start": "2014-01-02",
        "window_end": "2026-08-31", "v2_strategy_eligible_date": "2017-01-06",
        "julia_strategy_eligible_date": "2017-01-06", "comparison_effective_start": "2017-01-06",
        "comparison_effective_end": "2026-08-31", "coverage_status": "PARTIAL_WINDOW",
        "coverage_sessions": 2000, "reason_if_not_evaluable": "",
    }
    revised = closure.revise_span_row(base, "2021-01-08", {"window_start": "2014-01-02", "window_end": "2026-08-31"}, [])
    assert revised["comparison_effective_start"] == "2021-01-08"
    assert revised["coverage_status"] == "PARTIAL_WINDOW"
    assert revised["span_changed"]
    assert revised["targeted_replay_required"]

    beyond = closure.revise_span_row(base, "2027-01-04", {"window_start": "2014-01-02", "window_end": "2026-08-31"}, [])
    assert beyond["coverage_status"] == "NOT_EVALUABLE"
    assert not beyond["targeted_replay_required"]


def test_risk_identity_closure_maps_later_replacement() -> None:
    exposed = pd.DataFrame([{
        "trade_identity": "STRAT|P1|123456|2020-01-03|2020-01-06",
        "ticker": "123456", "window_id": "P1", "strategy_id": "STRAT", "signal_date": "2020-01-03",
    }])
    certified = pd.DataFrame([{
        "trade_identity": "STRAT|P1|123456|2021-01-08|2021-01-11",
        "ticker": "123456", "window_id": "P1", "strategy_id": "STRAT", "signal_date": "2021-01-08",
    }])

    result = closure.close_risk_identities(exposed, certified)

    assert result.loc[0, "disposition"] == "REPLACED_BY_LATER_ENTRY"
    assert result.loc[0, "replacement_signal_date"] == "2021-01-08"
