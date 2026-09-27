from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_pattern_b_state_forward_return_v01 import (  # noqa: E402
    HORIZONS,
    _run_survivorship_checks,
    horizon_endpoint,
    month_end_snapshot_dates,
    state_from_precomputed_bars,
    summarize_outcomes,
)
from trend_scanner.patterns.pattern_b_features_v01 import (  # noqa: E402
    STATUS_OK,
    compute_pattern_b_features_v01,
    completed_bars,
)
from trend_scanner.patterns.pattern_b_state_v02 import (  # noqa: E402
    FEATURES,
    MA24_DISTANCE,
    RANGE_36M,
    RANGE_52W,
    classify_pattern_b_state_v02,
)


def _daily_frame(end: str = "2020-12-31") -> pd.DataFrame:
    index = pd.bdate_range("2014-01-02", end)
    phase = np.arange(len(index), dtype=float)
    close = 100.0 + phase * 0.015 + 8.0 * np.sin(phase / 19.0) + 2.0 * np.sin(phase / 4.0)
    return pd.DataFrame(
        {"high": close + 1.5, "low": close - 1.25, "close": close}, index=index,
    )


def test_precomputed_bar_path_matches_authoritative_pattern_b_for_pit_dates():
    daily = _daily_frame()
    full_max = daily.index.max()
    monthly = completed_bars(daily, pd.offsets.MonthEnd(), full_max)
    weekly = completed_bars(daily, "W-FRI", full_max)
    dates = [
        "2017-01-31", "2017-03-31", "2017-08-31", "2018-02-28",
        "2019-06-28", "2020-11-30",
    ]
    for as_of in dates:
        fast = state_from_precomputed_bars(monthly, weekly, as_of)
        official = compute_pattern_b_features_v01(daily, as_of)
        features = {key: official.features[key] for key in FEATURES}
        assert all(value.status == STATUS_OK for value in features.values())
        assert fast["state"] == classify_pattern_b_state_v02(
            features[RANGE_36M].value,
            features[MA24_DISTANCE].value,
            features[RANGE_52W].value,
        )
        assert np.isclose(fast["range_36m"], features[RANGE_36M].value, atol=1e-12)
        assert np.isclose(fast["monthly_ma24_distance"], features[MA24_DISTANCE].value, atol=1e-12)
        assert np.isclose(fast["range_52w"], features[RANGE_52W].value, atol=1e-12)
        assert fast["monthly_last_bar"] == official.monthly_last_bar.date().isoformat()
        assert fast["weekly_last_bar"] == official.weekly_last_bar.date().isoformat()


def test_future_price_mutation_cannot_change_as_of_state():
    daily = _daily_frame()
    as_of = "2018-06-29"
    monthly = completed_bars(daily, pd.offsets.MonthEnd(), daily.index.max())
    weekly = completed_bars(daily, "W-FRI", daily.index.max())
    baseline = state_from_precomputed_bars(monthly, weekly, as_of)

    changed = daily.copy()
    future = changed.index > pd.Timestamp(as_of)
    changed.loc[future, "close"] *= 25.0
    changed.loc[future, "high"] *= 25.0
    changed.loc[future, "low"] *= 25.0
    changed_monthly = completed_bars(changed, pd.offsets.MonthEnd(), changed.index.max())
    changed_weekly = completed_bars(changed, "W-FRI", changed.index.max())
    after = state_from_precomputed_bars(changed_monthly, changed_weekly, as_of)
    assert {key: baseline[key] for key in ("state", "range_36m", "monthly_ma24_distance", "range_52w")} == {
        key: after[key] for key in ("state", "range_36m", "monthly_ma24_distance", "range_52w")
    }


def test_monthly_snapshot_excludes_incomplete_frontier_month():
    dates = [
        "2025-03-28", "2025-03-31", "2025-04-01", "2025-04-29", "2025-04-30",
        "2025-05-02", "2025-05-15",
    ]
    assert month_end_snapshot_dates(dates, "2025-05-15") == ["2025-03-31", "2025-04-30"]


def test_horizon_endpoint_is_exact_nth_future_session():
    dates = [day.date().isoformat() for day in pd.bdate_range("2025-01-02", periods=140)]
    assert horizon_endpoint(dates[0], "3M", dates) == dates[HORIZONS["3M"]]
    assert horizon_endpoint(dates[-1], "3M", dates) is None


def test_summary_contains_tail_thresholds_and_panel_b_filter():
    outcomes = pd.DataFrame([
        {"panel_b_eligible": True, "horizon": "3M", "state": "DEEP_DEPRESSED",
         "forward_return": 0.60, "mfe": 0.72, "mae": -0.22},
        {"panel_b_eligible": False, "horizon": "3M", "state": "DEEP_DEPRESSED",
         "forward_return": -0.55, "mfe": 0.10, "mae": -0.62},
        {"panel_b_eligible": True, "horizon": "3M", "state": "NORMAL",
         "forward_return": 0.10, "mfe": 0.20, "mae": -0.15},
    ])
    states, groups = summarize_outcomes(outcomes)
    all_deep = states.loc[
        (states["panel"] == "ALL") & (states["horizon"] == "3M")
        & (states["state_or_group"] == "DEEP_DEPRESSED")
    ].iloc[0]
    pit_deep = states.loc[
        (states["panel"] == "PIT_1T_PLUS") & (states["horizon"] == "3M")
        & (states["state_or_group"] == "DEEP_DEPRESSED")
    ].iloc[0]
    low_group = groups.loc[
        (groups["panel"] == "ALL") & (groups["horizon"] == "3M")
        & (groups["state_or_group"] == "LOW")
    ].iloc[0]
    assert all_deep["n"] == 2
    assert np.isclose(all_deep["ge_50_ratio"], 0.5)
    assert np.isclose(all_deep["le_50_ratio"], 0.5)
    assert pit_deep["n"] == 1
    assert low_group["n"] == 2


def test_terminal_identity_snapshot_is_retained_and_future_outcome_censored():
    dates = [day.date().isoformat() for day in pd.bdate_range("2024-01-02", periods=510)]
    snapshot, end = dates[0], dates[1]
    intervals = {}
    samples = []
    for i in range(20):
        ticker = f"{i + 1:06d}"
        isu_cd = f"KR7{i + 1:09d}"
        intervals[ticker] = [{
            "ticker": ticker, "isu_cd": isu_cd, "market": "KOSPI", "state": "COMMON",
            "effective_from": snapshot, "effective_to": end,
        }]
        samples.append({
            "snapshot_date": snapshot, "ticker": ticker, "isu_cd": isu_cd,
            "effective_to": end, "state": "NORMAL",
        })
    outcomes = pd.DataFrame(columns=["snapshot_date", "ticker", "isu_cd", "horizon"])
    checks = _run_survivorship_checks(
        pd.DataFrame(samples), outcomes, intervals, dates, dates[-1], seed=7,
    )
    assert len(checks) == 20
    assert all(row["panel_a_snapshot_retained"] for row in checks)
    assert all(row["endpoint_after_identity_interval_end"] for row in checks)
    assert all(not row["outcome_row_present"] for row in checks)
