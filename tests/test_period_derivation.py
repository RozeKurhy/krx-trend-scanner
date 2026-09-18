"""2단계 주봉·월봉 최소 구현(period_derivation.py) 집중 시험.

w.md(KRX 데일리 업데이트 V01 — 2단계 주봉·월봉 최소 구현 보정 지시서) §8
A~I에 대응한다. I(FAST 신호 기준점 보호)는 이 파일에서 새로 만들지 않고
tests/test_pattern_a_fast_evaluator_parity.py,
tests/test_pattern_a_fast_stock_report.py,
tests/test_pattern_a_fast_weekly_close.py를 별도로 재실행해서 확인한다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data import period_derivation
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.data.period_derivation import (
    BLOCKED,
    COMPLETE,
    FAILED,
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
    """가장 중요한 시험: 휴장 금요일에서 캘린더가 확장돼 있지 않아도 COMPLETE다.

    목요일(2026-01-15)이 캘린더 권위가 아는 마지막 실제 거래일이고, 금요일
    (2026-01-16)은 휴장이라 캘린더에도 daily에도 아예 존재하지 않는다.
    주봉 판정은 W-FRI 라벨과 target_as_of만 비교하므로,
    `calendar.max_observed_trading_date`가 W-FRI 라벨(금요일)에 못 미친다는
    사실 자체가 판정에 관여하지 않는다 — 1단계가 이미 인증한 `daily`를
    그대로 신뢰한다.
    """
    # 시장/종목 모두 2026-01-15(목)까지만 실제 거래일이 존재한다. 캘린더
    # 권위도 실제 운영처럼 마지막 확인된 거래일(목)까지만 안다 — 미래로
    # 인위 확장하지 않는다.
    dates = pd.bdate_range("2026-01-05", "2026-01-15")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(dates, last_completed_month="2025-12")

    target_as_of = "2026-01-16"  # 마지막 실제 거래일(목)보다 뒤, 휴장 금요일
    assert pd.Timestamp(target_as_of) > calendar.max_observed_trading_date  # 전제 조건 명시

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


def test_d_halted_ticker_weekly_is_still_complete():
    """거래정지 종목: 시장 주간은 끝났는데 종목 마지막 관측일은 화요일뿐이다.

    시장은 월~금(2026-01-05~09) 정상 거래했다고 가정한다. 이 종목은
    월·화(01-05, 01-06)까지만 거래되고 수~금은 거래정지라 일봉이 없다.
    target_as_of=금요일이면, 시장 주간이 이미 끝났으므로 weekly_status는
    COMPLETE여야 한다 — 종목 마지막 관측일(화)을 시장 완료 경계로 쓰면
    안 된다.
    """
    market_dates = pd.bdate_range("2026-01-05", "2026-01-09")  # 시장: 월~금 정상
    ticker_dates = market_dates[:2]  # 종목: 월, 화만 거래(수~금 거래정지)
    daily = _daily_frame(ticker_dates)
    calendar = MarketCalendarAuthority.from_dates(market_dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2026-01-09", calendar)

    assert result.final_status == PASS
    assert result.weekly_status == COMPLETE
    assert result.effective_daily_boundary == "2026-01-06"  # 종목 마지막 관측일(화)은 메타데이터로만 남는다


def test_e_halted_ticker_monthly_is_still_complete():
    """거래정지 종목: 운영 캘린더가 그 달을 완료 확정했는데 종목은 월초에 거래정지됐다.

    캘린더 권위는 2025-12을 완료 월로 확정한다. 이 종목의 마지막 일봉은
    2025-12-05(거래정지 이전)뿐이다. target_as_of가 그 완료 월 기준일이면
    monthly_status는 COMPLETE여야 한다 — 종목 마지막 관측일을 시장 월봉
    완료 경계로 쓰면 안 된다.
    """
    market_dates = pd.bdate_range("2025-12-01", "2026-01-15")  # 캘린더: 다음 달까지 관측됨
    ticker_dates = pd.bdate_range("2025-12-01", "2025-12-05")  # 종목: 12월 첫 주만 거래
    daily = _daily_frame(ticker_dates)
    calendar = MarketCalendarAuthority.from_dates(market_dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2025-12-31", calendar)

    assert result.final_status == PASS
    assert result.monthly_status == COMPLETE
    assert result.effective_daily_boundary == "2025-12-05"  # 종목 마지막 관측일(거래정지 직전)은 메타데이터로만 남는다


def test_completed_month_is_complete():
    dates = pd.bdate_range("2025-12-01", "2026-01-15")
    daily = _daily_frame(dates)
    # 2025-12은 완료 월로 확정, 2026-01은 아직 진행 중(2026-01-15까지만 관측).
    calendar = MarketCalendarAuthority.from_dates(dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2025-12-31", calendar)

    assert result.final_status == PASS
    assert result.monthly_status == COMPLETE


def test_f_latest_observed_month_is_provisional():
    dates = pd.bdate_range("2025-12-01", "2026-01-15")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(dates, last_completed_month="2025-12")

    result = derive_periods(daily, "2026-01-15", calendar)

    assert result.final_status == PASS
    assert result.monthly_status == PROVISIONAL


def test_g_same_input_is_deterministic():
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


def test_h_weekly_ignores_calendar_frontier():
    """주봉 판정이 calendar.max_observed_trading_date(캘린더 프런티어)에
    의존하지 않는다는 것을 직접 확인한다.

    daily는 2026-01-16(금)까지 있지만, 캘린더 권위는 2026-01-09(금)까지만
    확장돼 있어 그 주(2026-01-16 W-FRI)의 실제 거래일을 캘린더로는 검증할
    수 없는 상태다. 과거 구현은 이런 경우를
    `REQUIRED_WEEK_TRADING_DATES_UNVERIFIABLE`로 `BLOCKED`했지만, 이는
    2단계가 1단계 인증 충분성을 캘린더 프런티어로 다시 추론하려던 잘못된
    로직이었다. 지금은 주봉 판정이 W-FRI 라벨과 target_as_of만 비교하므로,
    캘린더가 그 주까지 확장돼 있는지와 무관하게 정상적으로 COMPLETE가
    나와야 한다.
    """
    dates = pd.bdate_range("2026-01-05", "2026-01-16")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-01-09"),  # 캘린더는 그 주 초까지만 확장됨(오래된 상태)
        last_completed_month="2025-12",
    )
    assert calendar.max_observed_trading_date == pd.Timestamp("2026-01-09")

    result = derive_periods(daily, "2026-01-16", calendar)

    assert result.final_status == PASS
    assert result.weekly_status == COMPLETE
    assert result.reason is None


def test_no_certified_daily_is_blocked():
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    result = derive_periods(None, "2026-01-16", calendar)

    assert result.final_status == BLOCKED
    assert result.reason == "DATA_UNAVAILABLE: NO_CERTIFIED_DAILY"


def test_unexpected_error_is_failed_not_blocked(monkeypatch):
    """예상치 못한 구현 오류는 BLOCKED가 아니라 FAILED로 나와야 한다(계약 §12)."""
    dates = pd.bdate_range("2026-01-05", "2026-01-16")
    daily = _daily_frame(dates)
    calendar = MarketCalendarAuthority.from_dates(
        pd.bdate_range("2026-01-05", "2026-03-31"),
        last_completed_month="2025-12",
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated unexpected implementation error")

    monkeypatch.setattr(period_derivation, "to_weekly", _boom)

    result = derive_periods(daily, "2026-01-16", calendar)

    assert result.final_status == FAILED
    assert result.reason is not None and result.reason.startswith("UNEXPECTED_ERROR:RuntimeError")
