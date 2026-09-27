from __future__ import annotations

import pandas as pd
import numpy as np

from scripts.analyze_pattern_b_depressed_entry_pattern_a_state_v01 import (
    _build_cached_snapshot,
    _build_cached_stage_snapshot,
    _build_stage_summary,
    _path_outcome,
)
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot, to_csv_row


def _event() -> dict[str, str]:
    return {
        "signal_id": "000001_KR7000000001_2024-01-31",
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "entry_signal_date": "2024-01-31",
        "component_id": "000001:KR7000000001:000",
    }


def _interval(end: str = "2099-12-31") -> list[dict[str, str]]:
    return [{
        "effective_from": "2010-01-01",
        "effective_to": end,
    }]


def test_path_outcome_uses_first_observed_target_and_session_offsets() -> None:
    event = _event()
    component_key = (event["ticker"], event["isu_cd"], event["component_id"])
    result = _path_outcome(
        event,
        {component_key: ("2024-02-29", "2024-03-29", "2024-04-30")},
        {
            (*component_key, "2024-02-29"): "NORMAL",
            (*component_key, "2024-03-29"): "DEEP_DEPRESSED",
            (*component_key, "2024-04-30"): "NORMAL",
        },
        {
            "2024-01-31": 0,
            "2024-02-29": 20,
            "2024-03-29": 40,
            "2024-04-30": 60,
        },
        "2024-05-31",
        _interval(),
        "2024-04-30",
    )
    assert result["pattern_b_path_outcome"] == "NORMAL_FIRST"
    assert result["first_normal_state_date"] == "2024-02-29"
    assert result["first_deep_depressed_state_date"] == "2024-03-29"
    assert result["sessions_to_first_normal"] == 20
    assert result["sessions_to_first_deep_depressed"] == 40
    assert result["path_order_verified"] is True


def test_missing_state_before_observed_target_makes_path_unevaluated() -> None:
    event = _event()
    component_key = (event["ticker"], event["isu_cd"], event["component_id"])
    result = _path_outcome(
        event,
        {component_key: ("2024-02-29", "2024-03-29")},
        {(*component_key, "2024-03-29"): "DEEP_DEPRESSED"},
        {"2024-01-31": 0, "2024-02-29": 20, "2024-03-29": 40},
        "2024-05-31",
        _interval(),
        "2024-03-29",
    )
    assert result["pattern_b_path_outcome"] == "OTHER_UNEVALUATED"
    assert result["pattern_b_path_reason"] == "MISSING_PATTERN_B_STATE_BEFORE_FIRST_EVENT"
    assert result["sessions_to_first_deep_depressed"] is None
    assert result["path_order_verified"] is False


def test_no_target_state_separates_active_identity_from_ended_identity() -> None:
    event = _event()
    component_key = (event["ticker"], event["isu_cd"], event["component_id"])
    common = (
        event,
        {component_key: ("2024-02-29", "2024-03-29")},
        {
            (*component_key, "2024-02-29"): "DEPRESSED",
            (*component_key, "2024-03-29"): "DEPRESSED",
        },
        {"2024-01-31": 0, "2024-02-29": 20, "2024-03-29": 40},
        "2024-05-31",
    )
    active = _path_outcome(*common, _interval(), "2024-03-29")
    ended = _path_outcome(*common, _interval("2024-04-15"), "2024-03-29")
    assert active["pattern_b_path_outcome"] == "NEITHER_BY_CUTOFF"
    assert active["path_order_verified"] is True
    assert ended["pattern_b_path_outcome"] == "OTHER_UNEVALUATED"
    assert ended["path_order_verified"] is False


def test_stage_summary_keeps_realized_and_open_performance_separate() -> None:
    linked = pd.DataFrame([
        {
            "pattern_a_stage": "BASE",
            "pattern_b_path_outcome": "NORMAL_FIRST",
            "control_entry_signal_status": "FILLED",
            "control_trade_status": "REALIZED",
            "control_gross_return_pct": 50.0,
            "control_mfe_pct": 60.0,
            "control_mae_pct": -20.0,
            "control_holding_krx_sessions": 10,
            "control_holding_calendar_days": 14,
            "control_mark_to_cutoff_gross_return_pct": None,
            "sessions_to_first_normal": 20,
            "sessions_to_first_deep_depressed": None,
        },
        {
            "pattern_a_stage": "BASE",
            "pattern_b_path_outcome": "DEEP_FIRST",
            "control_entry_signal_status": "FILLED",
            "control_trade_status": "OPEN_AT_CUTOFF",
            "control_gross_return_pct": None,
            "control_mfe_pct": None,
            "control_mae_pct": None,
            "control_holding_krx_sessions": None,
            "control_holding_calendar_days": None,
            "control_mark_to_cutoff_gross_return_pct": -30.0,
            "sessions_to_first_normal": None,
            "sessions_to_first_deep_depressed": 40,
        },
        {
            "pattern_a_stage": "BASE",
            "pattern_b_path_outcome": "NEITHER_BY_CUTOFF",
            "control_entry_signal_status": "SUPPRESSED_ALREADY_HOLDING",
            "control_trade_status": None,
            "control_gross_return_pct": None,
            "control_mfe_pct": None,
            "control_mae_pct": None,
            "control_holding_krx_sessions": None,
            "control_holding_calendar_days": None,
            "control_mark_to_cutoff_gross_return_pct": None,
            "sessions_to_first_normal": None,
            "sessions_to_first_deep_depressed": None,
        },
    ])
    summary = _build_stage_summary(linked).iloc[0]
    assert summary["signal_count"] == 3
    assert summary["realized_trade_count"] == 1
    assert summary["open_position_count"] == 1
    assert summary["median_gross_return_pct"] == 50.0
    assert summary["open_mark_observation_count"] == 1
    assert summary["open_mark_median_gross_return_pct"] == -30.0


def test_cached_snapshot_matches_official_pit_builder_at_completed_month_ends() -> None:
    dates = pd.bdate_range("2018-01-01", "2024-03-29")
    trend = np.linspace(80.0, 150.0, len(dates)) + 4.0 * np.sin(np.arange(len(dates)) / 18.0)
    daily = pd.DataFrame(
        {
            "open": trend * 0.995,
            "high": trend * 1.02,
            "low": trend * 0.98,
            "close": trend,
            "volume": np.full(len(dates), 1000.0),
            "trading_value": trend * 1000.0,
        },
        index=dates,
    )
    frame = pd.DataFrame({"date": dates}, index=dates)
    by_month = frame.groupby([frame.index.year, frame.index.month])
    month_ends = [group.index.max() for _, group in by_month]
    calendar = MarketCalendarAuthority(
        trading_dates=pd.DatetimeIndex(dates),
        completed_month_ends=month_ends,
        source_name="SYNTHETIC_TEST_CALENDAR",
    )
    monthly_bars = to_monthly(daily)
    weekly_bars = to_weekly(daily)

    for snapshot_date in ("2023-03-31", "2023-08-31", "2024-03-29"):
        official = build_historical_snapshot(
            "000001",
            "000001",
            daily,
            snapshot_date,
            include_incomplete_periods=False,
            market_calendar=calendar,
        )
        cached = _build_cached_snapshot(
            "000001",
            daily,
            snapshot_date,
            monthly_bars,
            weekly_bars,
            calendar,
        )
        stage_only = _build_cached_stage_snapshot(
            "000001",
            daily,
            snapshot_date,
            monthly_bars,
            weekly_bars,
            calendar,
        )
        pd.testing.assert_frame_equal(official.monthly, cached.monthly)
        pd.testing.assert_frame_equal(official.weekly, cached.weekly)
        pd.testing.assert_frame_equal(
            pd.DataFrame([to_csv_row("", official)]),
            pd.DataFrame([to_csv_row("", cached)]),
            check_dtype=False,
        )
        required_fields = (
            "ma24_slope",
            "weekly_ma12_slope",
            "ma24_slope_acceleration",
            "avg_price_change_12m",
            "ma_spread",
            "range_position",
            "distance_to_resistance",
        )
        for field in required_fields:
            assert np.isclose(
                getattr(official.features, field),
                getattr(stage_only.features, field),
                equal_nan=True,
            )
        assert classify_pattern_a_stage(official).stage == classify_pattern_a_stage(cached).stage
        assert classify_pattern_a_stage(official).stage == classify_pattern_a_stage(stage_only).stage
        assert classify_pattern_a_stage(official).reason_codes == classify_pattern_a_stage(stage_only).reason_codes
