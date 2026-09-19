"""1단계 인증 일봉에서 2단계 주봉·월봉을 얇게 조율해 파생한다.

계약: docs/architecture/daily_update_phase2_weekly_monthly_derivation_contract_v01.md

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

from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.data.resampler import to_monthly, to_weekly

COMPLETE = "COMPLETE"
PROVISIONAL = "PROVISIONAL"
PASS = "PASS"
BLOCKED = "BLOCKED"
FAILED = "FAILED"


@dataclass(frozen=True)
class PeriodDerivationResult:
    """주봉·월봉 파생 결과와 기간 완료 상태 요약.

    ``effective_daily_boundary``는 전달받은 ``daily``(해당 종목)의 마지막
    실제 관측일이며, 결과 메타데이터일 뿐이다. 거래정지 종목에서는 시장
    전체의 완료 경계보다 뒤처질 수 있으므로, ``weekly_status``/
    ``monthly_status`` 판정에는 쓰지 않는다. ``weekly_status``는
    ``target_as_of``만으로, ``monthly_status``는 ``calendar``의 완료 월
    권위와 ``target_as_of``로 판정한다 — 둘 다 1단계가 이미 인증한 ``daily``
    범위를 그대로 신뢰하며 1단계 인증 충분성을 다시 추론하지 않는다.
    """

    target_as_of: str
    effective_daily_boundary: str | None
    weekly: pd.DataFrame
    monthly: pd.DataFrame
    weekly_status: str | None
    monthly_status: str | None
    final_status: str
    reason: str | None = None


def _weekly_status(weekly: pd.DataFrame, target: pd.Timestamp) -> str | None:
    """가장 마지막 주봉 bar의 DERIVED_WEEK_COMPLETE 상태를 판정한다.

    2단계는 1단계 인증 충분성을 다시 추론하지 않는다 — `daily`가 이미 1단계
    인증 범위 안의 일봉이라는 전제를 그대로 신뢰한다. 따라서 판정은 W-FRI
    라벨과 `target_as_of`의 단순 비교만으로 충분하며, `MarketCalendarAuthority`
    (마지막 실제 거래일 등)를 별도로 참조하지 않는다. weekly가 비어 있으면
    None을 반환한다(sliced가 비어 있지 않은 한 실제로는 발생하지 않는다).
    """
    if weekly.empty:
        return None

    week_label = weekly.index[-1].normalize()
    return COMPLETE if week_label <= target else PROVISIONAL


def _monthly_status(
    monthly: pd.DataFrame,
    target: pd.Timestamp,
    calendar: MarketCalendarAuthority,
) -> str | None:
    """실제로 반환된 마지막 월봉(``monthly.index[-1]``)의 완료 상태를 판정한다.

    판정 대상은 ``target_as_of``가 속한 (연, 월)이 아니라, 실제로 파생된
    마지막 월봉의 (연, 월)이다. 거래정지·장기 미거래로 마지막 월봉이 과거
    달에 머물러 있으면(``target_as_of``가 이미 다음 달로 넘어간 경우),
    ``target_as_of``의 (연, 월)을 조회하면 아직 진행 중인 최신 달을 잘못
    가리키게 된다. `get_actual_month_end()`는 (연, 월)이 완료 월 목록에
    없으면 예외 없이 `None`을 반환하므로, 비거래일 `target_as_of`에서도
    별도 클램프 없이 안전하게 조회할 수 있다.
    """
    if monthly.empty:
        return None
    last_month_label = monthly.index[-1]
    actual_month_end = calendar.get_actual_month_end(last_month_label.year, last_month_label.month)
    return COMPLETE if actual_month_end is not None and target >= actual_month_end else PROVISIONAL


def derive_periods(
    daily: pd.DataFrame | None,
    target_as_of: str | pd.Timestamp,
    calendar: MarketCalendarAuthority | None,
) -> PeriodDerivationResult:
    """1단계 인증 일봉과 하나의 target_as_of로 주봉·월봉을 파생한다.

    daily는 이미 1단계 인증 경계 안에서 로드된 DataFrame이어야 한다(예:
    RepositoryV2DailyLoader.load()의 반환값). 이 함수는 daily.index를
    target_as_of 이하로 한 번 더 슬라이싱해서 방어적으로 사용하지만, 1단계
    인증 경계를 넘어선 데이터가 애초에 들어오지 않았다고 신뢰한다 — 새로운
    일봉 중간 공백 검증은 하지 않는다(daily_gap_authority = INHERITED_FROM_PHASE1).

    ``calendar``는 `load_rolling_production_market_calendar()`가 병합 캘린더
    산출물이 없을 때 `None`을 반환할 수 있으므로, 월봉 완료 권위가 없는
    예상 가능한 입력 상태로 보고 `BLOCKED`로 처리한다(예상치 못한 구현
    오류가 아니므로 `FAILED`로 흘려보내지 않는다).
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
    effective_boundary_str = effective_boundary.strftime("%Y-%m-%d")

    if calendar is None:
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=effective_boundary_str,
            weekly=pd.DataFrame(),
            monthly=pd.DataFrame(),
            weekly_status=None,
            monthly_status=None,
            final_status=BLOCKED,
            reason="MONTHLY_AUTHORITY_UNAVAILABLE: CALENDAR_NOT_PROVIDED",
        )

    try:
        weekly = to_weekly(sliced)
        monthly = to_monthly(sliced)
        weekly_status = _weekly_status(weekly, target)
        monthly_status = _monthly_status(monthly, target, calendar)
    except Exception as exc:  # noqa: BLE001 - 예상치 못한 구현 오류만 FAILED로 변환한다.
        return PeriodDerivationResult(
            target_as_of=target_str,
            effective_daily_boundary=effective_boundary_str,
            weekly=pd.DataFrame(),
            monthly=pd.DataFrame(),
            weekly_status=None,
            monthly_status=None,
            final_status=FAILED,
            reason=f"UNEXPECTED_ERROR:{type(exc).__name__}:{exc}",
        )

    return PeriodDerivationResult(
        target_as_of=target_str,
        effective_daily_boundary=effective_boundary_str,
        weekly=weekly,
        monthly=monthly,
        weekly_status=weekly_status,
        monthly_status=monthly_status,
        final_status=PASS,
        reason=None,
    )


__all__ = [
    "PeriodDerivationResult",
    "derive_periods",
    "COMPLETE",
    "PROVISIONAL",
    "PASS",
    "BLOCKED",
    "FAILED",
]
