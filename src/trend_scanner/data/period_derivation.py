"""1단계 인증 일봉에서 2단계 주봉·월봉을 얇게 조율해 파생한다.

계약: docs/architecture/weekly_monthly_derivation_contract_v01.md

이 모듈은 새 거래일 권위나 새 resample 로직을 만들지 않는다.
`to_weekly()`/`to_monthly()`(resampler.py)와 `MarketCalendarAuthority`
(market_calendar.py)의 완료 월 권위를 그대로 재사용하며, `target_as_of`
하나를 받아 주봉·월봉 DataFrame과 `COMPLETE`/`PROVISIONAL` 상태를 계산하는
실행 시점 결정적 파생만 수행한다. 영구 저장소나 캐시는 두지 않는다.

호출부는 `RepositoryV2DailyLoader`(repository_v2_loader.py)로 1단계 인증
일봉을 먼저 로드하고, `load_rolling_production_market_calendar()`로 운영
거래일 권위를 얻은 뒤 이 모듈의 `derive_periods()`에 전달한다. 이는
`historical_snapshot.py`의 `build_historical_snapshot(daily, ...)`가 이미
따르는 것과 같은 호출 방식이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    MarketCalendarUnavailableError,
)
from trend_scanner.data.resampler import to_monthly, to_weekly

COMPLETE = "COMPLETE"
PROVISIONAL = "PROVISIONAL"
PASS = "PASS"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PeriodDerivationResult:
    """주봉·월봉 파생 결과와 기간 완료 상태 요약."""

    target_as_of: str
    effective_daily_boundary: str | None
    weekly: pd.DataFrame
    monthly: pd.DataFrame
    weekly_status: str | None
    monthly_status: str | None
    final_status: str
    reason: str | None = None


def _weekly_status(
    weekly: pd.DataFrame,
    target: pd.Timestamp,
    effective_boundary: pd.Timestamp,
    calendar: MarketCalendarAuthority,
) -> tuple[str | None, str | None]:
    """가장 마지막 주봉 bar의 DERIVED_WEEK_COMPLETE 상태를 판정한다.

    반환: (status, blocked_reason). weekly가 비어 있으면 (None, None).
    필요한 실제 거래일을 캘린더 권위로 확인할 수 없으면 (None, reason)을
    반환해 호출부가 BLOCKED로 처리하게 한다.
    """
    if weekly.empty:
        return None, None

    week_label = weekly.index[-1].normalize()

    if week_label > target:
        # 계약 조건 2(W-FRI 라벨 <= target_as_of) 자체를 만족하지 못하므로
        # 조건 3을 볼 것도 없이 진행 중인 주간이다.
        return PROVISIONAL, None

    week_start = week_label - pd.Timedelta(6, unit="D")

    if calendar.max_observed_trading_date is None or calendar.max_observed_trading_date < week_label:
        return None, "REQUIRED_WEEK_TRADING_DATES_UNVERIFIABLE"

    required_dates = [d for d in calendar.trading_dates if week_start <= d <= week_label]
    if not required_dates:
        # 그 구간에 실제 거래일 자체가 없다(예: 연휴 주). 완성을 주장할 근거가 없으므로 진행 중으로 본다.
        return PROVISIONAL, None

    status = COMPLETE if max(required_dates) <= effective_boundary else PROVISIONAL
    return status, None


def _monthly_status(
    monthly: pd.DataFrame,
    effective_boundary: pd.Timestamp,
    calendar: MarketCalendarAuthority,
) -> str | None:
    """가장 마지막 월봉 bar의 완료 상태를 기존 운영 월 완료 권위로 판정한다."""
    if monthly.empty:
        return None
    return COMPLETE if calendar.is_completed_month(effective_boundary) else PROVISIONAL


def derive_periods(
    daily: pd.DataFrame | None,
    target_as_of: str | pd.Timestamp,
    calendar: MarketCalendarAuthority,
) -> PeriodDerivationResult:
    """1단계 인증 일봉과 하나의 target_as_of로 주봉·월봉을 파생한다.

    daily는 이미 1단계 인증 경계 안에서 로드된 DataFrame이어야 한다(예:
    RepositoryV2DailyLoader.load()의 반환값). 이 함수는 daily.index를
    target_as_of 이하로 한 번 더 슬라이싱해서 방어적으로 사용하지만, 1단계
    인증 경계를 넘어선 데이터가 애초에 들어오지 않았다고 신뢰한다 — 새로운
    일봉 중간 공백 검증은 하지 않는다(daily_gap_authority = INHERITED_FROM_PHASE1).
    """
    target = pd.Timestamp(target_as_of).normalize()
    target_str = target.strftime("%Y-%m-%d")

    if daily is None or daily.empty:
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=None,
            weekly=pd.DataFrame(),
            monthly=pd.DataFrame(),
            weekly_status=None,
            monthly_status=None,
            final_status=BLOCKED,
            reason="DATA_UNAVAILABLE: NO_CERTIFIED_DAILY",
        )

    sliced = daily[daily.index <= target]
    if sliced.empty:
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=None,
            weekly=pd.DataFrame(),
            monthly=pd.DataFrame(),
            weekly_status=None,
            monthly_status=None,
            final_status=BLOCKED,
            reason="DATA_UNAVAILABLE: NO_CERTIFIED_DAILY_AT_OR_BEFORE_TARGET",
        )

    effective_boundary = sliced.index.max().normalize()
    weekly = to_weekly(sliced)
    monthly = to_monthly(sliced)

    weekly_status, weekly_block_reason = _weekly_status(weekly, target, effective_boundary, calendar)
    if weekly_block_reason is not None:
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=effective_boundary.strftime("%Y-%m-%d"),
            weekly=weekly,
            monthly=monthly,
            weekly_status=None,
            monthly_status=None,
            final_status=BLOCKED,
            reason=weekly_block_reason,
        )

    try:
        monthly_status = _monthly_status(monthly, effective_boundary, calendar)
    except MarketCalendarUnavailableError as exc:
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=effective_boundary.strftime("%Y-%m-%d"),
            weekly=weekly,
            monthly=monthly,
            weekly_status=weekly_status,
            monthly_status=None,
            final_status=BLOCKED,
            reason=f"MONTHLY_AUTHORITY_UNAVAILABLE:{exc}",
        )

    return PeriodDerivationResult(
        target_as_of=target_str,
        effective_daily_boundary=effective_boundary.strftime("%Y-%m-%d"),
        weekly=weekly,
        monthly=monthly,
        weekly_status=weekly_status,
        monthly_status=monthly_status,
        final_status=PASS,
        reason=None,
    )


__all__ = ["PeriodDerivationResult", "derive_periods", "COMPLETE", "PROVISIONAL", "PASS", "BLOCKED"]
