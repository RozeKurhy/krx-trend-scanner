"""Phase 13C ground truth preparation helper 테스트.

PIT boundary(leakage 방지), completed-weekly reference date 검증,
source_reason 분류 규칙의 결정론성, sample_id 유일성만 다룬다. 이 모듈은
weekly_stage_at_reference/human_label을 만들지 않으므로 그에 대한 테스트는
없다(만들지 않는다는 것 자체가 계약).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import (
    DATA_UNAVAILABLE,
    MONTHLY_HISTORY_INSUFFICIENT,
    MONTHLY_HISTORY_MIN_BARS,
    MONTHLY_HISTORY_OK,
    build_chart_slices,
    classify_source_reason,
    compute_reference_snapshot,
    find_base_reference_before_entry,
    load_raw_daily,
    make_sample_id,
    monthly_history_status,
    resolve_completed_weekly_reference,
)


def _make_daily(start: str, periods: int) -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=periods)
    rng = np.random.default_rng(42)
    close = 10_000 + np.cumsum(rng.normal(0, 50, size=periods))
    close = np.clip(close, 1_000, None)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000, 10_000, size=periods),
            "trading_value": close * rng.integers(1_000, 10_000, size=periods),
        },
        index=idx,
    )


@pytest.fixture
def daily() -> pd.DataFrame:
    # 5년치 영업일(자유로운 완료 monthly/weekly 다수 포함)
    return _make_daily("2019-01-02", periods=252 * 5)


def test_resolve_completed_weekly_reference_returns_completed_friday_label(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2020-06-17")
    assert ref is not None
    assert ref.weekday() == 4  # Friday
    assert ref <= pd.Timestamp("2020-06-17")


def test_resolve_completed_weekly_reference_none_before_data_start(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2015-01-01")
    assert ref is None


def test_compute_reference_snapshot_fails_closed_on_non_completed_date(daily):
    # 2020-06-17은 수요일이라 완료 주봉 라벨(금요일)이 아니다.
    snap = compute_reference_snapshot("000000", "테스트종목", daily, pd.Timestamp("2020-06-17"))
    assert snap.data_status == DATA_UNAVAILABLE
    assert snap.pattern_a_stage is None


def test_compute_reference_snapshot_ok_on_completed_friday(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2021-03-19")
    snap = compute_reference_snapshot("000000", "테스트종목", daily, ref)
    assert snap.data_status == "OK"
    assert snap.reference_date == ref


def test_build_chart_slices_no_future_leakage(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2021-03-19")
    outcome_end = min(ref + pd.Timedelta(weeks=26), daily.index.max())
    slices = build_chart_slices(daily, ref, outcome_end)

    assert slices.monthly_pit.empty or slices.monthly_pit.index.max() <= ref
    assert slices.weekly_pit.empty or slices.weekly_pit.index.max() <= ref
    assert slices.daily_pit.empty or slices.daily_pit.index.max() <= ref
    # PIT과 달리 outcome은 reference_date 이후 데이터를 포함할 수 있다.
    assert slices.weekly_outcome.index.max() <= outcome_end


def test_build_chart_slices_daily_pit_excludes_future_rows_even_if_present(daily):
    ref = pd.Timestamp("2021-03-19")
    slices = build_chart_slices(daily, ref, ref + pd.Timedelta(weeks=4))
    assert (slices.daily_pit.index <= ref).all()
    assert (slices.monthly_pit.index <= ref).all()
    assert (slices.weekly_pit.index <= ref).all()


@pytest.mark.parametrize(
    "metrics,expected",
    [
        (
            {"trailing_return": 0.20, "forward_return": 0.0, "forward_max_drawdown": -0.10,
             "forward_max_runup": 0.05, "trailing_52w_return": 0.0},
            "FAILED_BREAKOUT",
        ),
        (
            {"trailing_return": 0.05, "forward_return": 0.0, "forward_max_drawdown": -0.02,
             "forward_max_runup": 0.02, "trailing_52w_return": -0.40},
            "LONG_DOWNTREND_BOUNCE",
        ),
        (
            {"trailing_return": 0.10, "forward_return": 0.0, "forward_max_drawdown": -0.02,
             "forward_max_runup": 0.02, "trailing_52w_return": 0.80},
            "STRONG_UPTREND_ALREADY_EXTENDED",
        ),
        (
            {"trailing_return": -0.05, "forward_return": 0.0, "forward_max_drawdown": -0.02,
             "forward_max_runup": 0.02, "trailing_52w_return": -0.35},
            "NEGATIVE_CONTROL",
        ),
        (
            {"trailing_return": 0.01, "forward_return": 0.0, "forward_max_drawdown": -0.02,
             "forward_max_runup": 0.02, "trailing_52w_return": 0.0},
            "RANGE_BOUND",
        ),
        (
            {"trailing_return": 0.09, "forward_return": 0.02, "forward_max_drawdown": -0.03,
             "forward_max_runup": 0.06, "trailing_52w_return": 0.10},
            "AMBIGUOUS_STRUCTURE",
        ),
    ],
)
def test_classify_source_reason_is_deterministic(metrics, expected):
    assert classify_source_reason(metrics) == expected
    # 같은 입력이면 항상 같은 결과(순수 함수, side effect 없음).
    assert classify_source_reason(dict(metrics)) == expected


def test_make_sample_id_is_deterministic_and_unique_per_date():
    a = make_sample_id("005930", pd.Timestamp("2020-01-03"))
    b = make_sample_id("005930", pd.Timestamp("2020-01-03"))
    c = make_sample_id("005930", pd.Timestamp("2020-01-10"))
    assert a == b == "005930_20200103"
    assert a != c


_REAL_TICKER, _REAL_NAME = "003100", "선광"
_HAS_REAL_CACHE = load_raw_daily(_REAL_TICKER, ParquetCache()) is not None
_SKIP_REASON = "실제 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_find_base_reference_before_entry_enforces_min_lead_weeks():
    daily = load_raw_daily(_REAL_TICKER, ParquetCache())
    ref, entry_boundary, entry_stage = find_base_reference_before_entry(
        _REAL_TICKER, _REAL_NAME, daily, "2026-08-14", min_lead_weeks=12, max_lookback_weeks=104
    )
    assert ref is not None
    assert entry_boundary is not None
    assert entry_stage in ("transition", "early_trend")
    # 회귀 방지: "entry 바로 직전 BASE"로 되돌아가면 이 여유(gap)가 거의 0이
    # 된다 — 최소 min_lead_weeks만큼 떨어져 있어야 한다.
    assert (entry_boundary - ref).days // 7 >= 12
    snap = compute_reference_snapshot(_REAL_TICKER, _REAL_NAME, daily, ref)
    assert snap.pattern_a_stage == "base"


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_find_base_reference_before_entry_reference_is_not_inside_episode():
    """2차 회귀 방지: reference가 TRANSITION 사이의 1주짜리 dip이 아니라
    진짜로 episode "이전"인지 forward로 4주 이상 확인한다. 이 확인이
    없으면 gap-tolerant entry_boundary 탐색만으로는 reference 자체가
    이미 진행 중인 episode 내부의 되돌림 주간일 수 있다(1차 correction의
    실제 회귀 사례: 000050/001800/002460 등에서 reference 다음 주가 바로
    transition으로 이어졌었음).
    """
    daily = load_raw_daily(_REAL_TICKER, ParquetCache())
    ref, _, _ = find_base_reference_before_entry(
        _REAL_TICKER, _REAL_NAME, daily, "2026-08-14", min_lead_weeks=12, max_lookback_weeks=104
    )
    assert ref is not None
    weekly_index = to_weekly(daily).index
    forward = sorted(d for d in weekly_index if d > ref)[:4]
    assert len(forward) == 4
    forward_stages = [
        compute_reference_snapshot(_REAL_TICKER, _REAL_NAME, daily, d).pattern_a_stage for d in forward
    ]
    assert all(s not in ("transition", "early_trend") for s in forward_stages), forward_stages


# --- Monthly Review Data Sufficiency Gate (13C-1 correction) -------------


def test_monthly_history_gate_fails_closed_below_min_bars(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2020-01-10")
    snap = compute_reference_snapshot("000000", "테스트종목", daily, ref)
    assert snap.completed_monthly_bars is not None
    assert snap.completed_monthly_bars < MONTHLY_HISTORY_MIN_BARS
    assert monthly_history_status(snap.completed_monthly_bars) == MONTHLY_HISTORY_INSUFFICIENT


def test_monthly_history_gate_ok_at_or_above_min_bars(daily):
    ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2023-06-16")
    snap = compute_reference_snapshot("000000", "테스트종목", daily, ref)
    assert snap.completed_monthly_bars is not None
    assert snap.completed_monthly_bars >= MONTHLY_HISTORY_MIN_BARS
    assert monthly_history_status(snap.completed_monthly_bars) == MONTHLY_HISTORY_OK


def test_monthly_history_gate_excludes_incomplete_current_month(daily):
    # 2023-06-16은 6월 중순이므로 6월 자체는 아직 완료된 monthly bar가 아니다.
    ref_mid_month = pd.Timestamp("2023-06-16")
    snapshot = build_historical_snapshot(
        "000000", "테스트종목", daily, ref_mid_month, include_incomplete_periods=False
    )
    assert not snapshot.monthly.empty
    assert snapshot.monthly.index.max() < ref_mid_month.replace(day=1)


def test_monthly_history_gate_excludes_future_bars(daily):
    early_ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2021-01-08")
    later_ref = resolve_completed_weekly_reference("000000", "테스트종목", daily, "2023-06-16")
    early_snap = compute_reference_snapshot("000000", "테스트종목", daily, early_ref)
    later_snap = compute_reference_snapshot("000000", "테스트종목", daily, later_ref)
    # early_ref 시점에서 계산한 월봉 개수는 later_ref 이후의 월봉을 포함하지
    # 않으므로 later_ref 시점 개수보다 항상 적어야 한다(미래 데이터 미포함).
    assert early_snap.completed_monthly_bars < later_snap.completed_monthly_bars
    early_full = build_historical_snapshot(
        "000000", "테스트종목", daily, early_ref, include_incomplete_periods=False
    )
    assert early_full.monthly.index.max() <= early_ref
