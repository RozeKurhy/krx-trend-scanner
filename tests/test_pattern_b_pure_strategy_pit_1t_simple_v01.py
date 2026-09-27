from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as study


def _event(ticker: str, isu: str, date: str) -> dict:
    return {
        "signal_id": f"{ticker}_{isu}_{date}",
        "ticker": ticker,
        "isu_cd": isu,
        "entry_signal_date": date,
        "entry_signal_status": "PENDING",
    }


def test_exact_signal_date_cap_is_inclusive_and_under_cap_is_rejected() -> None:
    samples = pd.DataFrame([
        {"ticker": "000001", "isu_cd": "KR7000000001", "snapshot_date": "2020-01-31", "market_cap_krw": 1_000_000_000_000, "pit_market_cap_exact": True},
        {"ticker": "000002", "isu_cd": "KR7000000002", "snapshot_date": "2020-01-31", "market_cap_krw": 999_999_999_999, "pit_market_cap_exact": True},
    ])
    events = [
        _event("000001", "KR7000000001", "2020-01-31"),
        _event("000002", "KR7000000002", "2020-01-31"),
    ]

    eligible, audit = study._attach_exact_entry_caps(events, samples)

    assert list(eligible) == [("000001", "KR7000000001")]
    assert eligible[("000001", "KR7000000001")][0]["entry_market_cap_krw"] == 1_000_000_000_000
    assert events[1]["entry_signal_status"] == "REJECTED_BELOW_1T"
    assert [row["filter_status"] for row in audit] == [
        "ELIGIBLE_EXACT_PIT_GE_1T",
        "REJECTED_BELOW_1T",
    ]


def test_missing_nonexact_or_adjacent_date_cap_fails_closed() -> None:
    samples = pd.DataFrame([
        {"ticker": "000003", "isu_cd": "KR7000000003", "snapshot_date": "2020-01-31", "market_cap_krw": 2_000_000_000_000, "pit_market_cap_exact": False},
        {"ticker": "000004", "isu_cd": "KR7000000004", "snapshot_date": "2020-01-30", "market_cap_krw": 2_000_000_000_000, "pit_market_cap_exact": True},
        {"ticker": "000005", "isu_cd": "KR7000000005", "snapshot_date": "2020-01-31", "market_cap_krw": None, "pit_market_cap_exact": True},
    ])
    events = [
        _event("000003", "KR7000000003", "2020-01-31"),
        _event("000004", "KR7000000004", "2020-01-31"),
        _event("000005", "KR7000000005", "2020-01-31"),
    ]

    eligible, audit = study._attach_exact_entry_caps(events, samples)

    assert eligible == {}
    assert all(event["entry_signal_status"] == "REJECTED_MISSING_OR_NONEXACT_PIT_CAP" for event in events)
    assert all(event["entry_market_cap_krw"] is None for event in events)
    assert all(row["filter_status"] == "REJECTED_MISSING_OR_NONEXACT_PIT_CAP" for row in audit)


def test_verdict_rubric_requires_quality_and_downside_improvement() -> None:
    control = {
        "closed_median_gross_pct": 5.0,
        "closed_win_rate_pct": 60.0,
        "closed_ge_50_rate_pct": 4.0,
        "open_marked_mean_gross_pct": -20.0,
        "open_marked_median_gross_pct": -10.0,
        "open_marked_le_30_rate_pct": 30.0,
        "open_marked_le_50_rate_pct": 15.0,
        "deep_arrival_rate_of_filled_pct": 25.0,
    }
    improved = {
        "closed_median_gross_pct": 6.0,
        "closed_win_rate_pct": 62.0,
        "closed_ge_50_rate_pct": 4.0,
        "open_marked_mean_gross_pct": -15.0,
        "open_marked_median_gross_pct": -8.0,
        "open_marked_le_30_rate_pct": 25.0,
        "open_marked_le_50_rate_pct": 12.0,
        "deep_arrival_rate_of_filled_pct": 20.0,
    }

    assert study._verdict(control, improved)[0] == "PATTERN_B_PIT_1T_SIMPLE_IMPROVED"
    no_benefit = {key: value for key, value in control.items()}
    no_benefit["closed_median_gross_pct"] = 4.0
    no_benefit["closed_win_rate_pct"] = 55.0
    no_benefit["closed_ge_50_rate_pct"] = 3.0
    no_benefit["open_marked_mean_gross_pct"] = -21.0
    no_benefit["open_marked_median_gross_pct"] = -11.0
    no_benefit["open_marked_le_30_rate_pct"] = 31.0
    no_benefit["open_marked_le_50_rate_pct"] = 15.0
    no_benefit["deep_arrival_rate_of_filled_pct"] = 25.0
    assert study._verdict(control, no_benefit)[0] == "PATTERN_B_PIT_1T_SIMPLE_NO_BENEFIT"
