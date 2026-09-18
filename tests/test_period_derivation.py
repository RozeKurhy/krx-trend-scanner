"""2단계 주봉·월봉 최소 구현(period_derivation.py) 집중 시험.

w.md(KRX 데일리 업데이트 V01 — 2단계 주봉·월봉 최소 구현 지시서) §10 A~G에
대응한다. H(FAST 신호 기준점 보호)는 기존 test_pattern_a_fast_weekly_close.py
등으로 별도 확인한다(이 파일에서는 새로 만들지 않음).
"""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.data.period_derivation import (
    BLOCKED,
    COMPLETE,
    PASS,
    PROVISIONAL,
    derive_periods,
)
from trend_scanner.data.resampler import to_weekly


def _daily_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    close = [100.0 + i * 0.1 for i in range(len(dates))]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * len(dates),
            "trading_value": [1.0e8] * len(dates),
        },
        index=dates,
    )


def test_a_normal_trading_friday_is_complete():
    # 2026-01-05(월) ~ 2026-01-16(금): 정상 2주, 휴장 없음.
    dates = pd.bdate_range("2026-01-05", "2026-01-16")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    result = derive_periods(daily, "2026-01-16", calendar)

    assert result.final_status == PASS
    assert result.weekly_status == COMPLETE
    assert result.weekly.index[-1] == pd.Timestamp("2026-01-16")


def test_b_friday_holiday_is_still_complete():
    """가장 중요한 시험: 목요일이 실제 마지막 거래일, 금요일 휴장.

    target_as_of = 금요일이라도 `target_as_of > certified_through`라는
    이유만으로 BLOCKED되면 실패다.
    """
    # 2026-01-15(목)까지만 일봉 존재. 2026-01-16(금)은 휴장이라 데이터 없음.
    dates = pd.bdate_range("2026-01-05", "2026-01-15")
    daily = _daily_frame(dates)
    # 캘린더 권위는 2026-01-16(금)을 제외한 채로 그 이후까지 넓게 확장돼 있다
    # (KRX 휴장일은 사전에 알려져 있어, 캘린더 프론티어가 실제 인증 경계보다
    # 앞서 있는 것이 정상적인 운영 형태다).
    wide_dates = pd.bdate_range("2026-01-05", "2026-03-31").drop(pd.Timestamp("2026-01-16"))
    calendar = MarketCalendarAuthority.from_dates(wide_dates, last_completed_month="2025-12")

    target_as_of = "2026-01-16"  # 마지막 실제 거래일(목)보다 뒤, 휴장 금요일
    certified_through = daily.index.max()
    assert pd.Timestamp(target_as_of) > certified_through  # 전제 조건 명시

    result = derive_periods(daily, target_as_of, calendar)

    assert result.final_status == PASS
    assert result.weekly_status == COMPLETE
    assert result.reason is None


def test_c_midweek_target_as_of_is_provisional():
    # 2026-01-05(월) ~ 2026-01-07(수)까지만 데이터, target_as_of=수요일.
    dates = pd.bdate_range("2026-01-05", "2026-01-07")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    result = derive_periods(daily, "2026-01-07", calendar)

    weekly_full = to_weekly(daily)
    assert weekly_full.index[-1] > pd.Timestamp("2026-01-07")  # W-FRI 라벨(금) > target(수)
    assert result.final_status == PASS
    assert result.weekly_status == PROVISIONAL


def test_d_completed_month_is_complete():
    dates = pd.bdate_range("2025-12-01", "2026-01-15")
    daily = _daily_frame(dates)
    # 2025-12은 완료 월로 확정, 2026-01은 아직 진행 중(2026-01-15까지만 관측).
    calendar = MarketCalendarAuthority.from_dates(dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2025-12-31", calendar)

    assert result.final_status == PASS
    assert result.monthly_status == COMPLETE


def test_e_latest_observed_month_is_provisional():
    dates = pd.bdate_range("2025-12-01", "2026-01-15")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2026-01-15", calendar)

    assert result.final_status == PASS
    assert result.monthly_status == PROVISIONAL


def test_f_same_input_is_deterministic():
    dates = pd.bdate_range("2026-01-05", "2026-01-16")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    first = derive_periods(daily, "2026-01-16", calendar)
    second = derive_periods(daily, "2026-01-16", calendar)

    assert first.final_status == second.final_status == PASS
    assert first.weekly_status == second.weekly_status
    assert first.monthly_status == second.monthly_status
    pd.testing.assert_frame_equal(first.weekly, second.weekly)
    pd.testing.assert_frame_equal(first.monthly, second.monthly)


def test_g_required_week_dates_unverifiable_is_blocked():
    # daily는 2026-01-16(금)까지 있지만, 캘린더 권위는 2026-01-09(금)까지만
    # 확장돼 있어 그 주(2026-01-16 W-FRI)의 필요 거래일을 증명할 수 없다.
    dates = pd.bdate_range("2026-01-05", "2026-01-16")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-01-09"),
        last_completed_month="2025-12",
    )

    result = derive_periods(daily, "2026-01-16", calendar)

    assert result.final_status == BLOCKED
    assert result.reason == "REQUIRED_WEEK_TRADING_DATES_UNVERIFIABLE"


def test_no_certified_daily_is_blocked():
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    result = derive_periods(None, "2026-01-16", calendar)

    assert result.final_status == BLOCKED
    assert result.reason == "DATA_UNAVAILABLE: NO_CERTIFIED_DAILY"
