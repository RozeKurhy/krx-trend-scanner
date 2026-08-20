"""Historical Snapshot Validation v0.1: 과거 특정 시점까지의 데이터만으로
그 시점 기준 Feature를 다시 계산한다.

Pattern A 점수는 만들지 않는다. 새 Feature 산식도 만들지 않는다. 기존
build_feature_row()를 그대로 호출해서 현재 시점 계산과 과거 시점 계산이
항상 같은 계산 경로를 타도록 한다.

핵심 원칙(look-ahead 방지): snapshot_date 이후 데이터는 어떤 방식으로도
계산에 포함되지 않는다. daily를 index <= snapshot_date로 먼저 자르고,
그렇게 잘라낸 결과만 resample과 build_feature_row에 넘긴다. snapshot_date가
비거래일이어도 실패시키지 않고, 그 이하에서 가장 최근 거래일까지의 데이터를
그대로 쓴다(별도의 "가장 가까운 거래일 조회" 로직이 필요 없다 — index <=
필터 자체가 이미 그 결과를 만든다).

completed monthly/weekly 정책:
- monthly: KRX 시장 캘린더 Authority(trend_scanner.data.market_calendar.MarketCalendarAuthority)
  기준. snapshot_date가 그 달의 실제 KRX 마지막 거래일 이전이면 마지막
  월봉을 "진행 중"으로 보고 제거한다. 실제 마지막 거래일과 같거나 이후이면
  완성된 월봉으로 유지한다. (캘린더 부재 시 silent fallback 금지, fail closed)
- weekly: `weekly.index[-1] > effective_as_of`이면(W-FRI resample 특성상
  snapshot_date가 월~목이면 그 주 금요일 label의 미완성 주봉이 생길 수
  있다) 마지막 주봉을 제거한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    is_completed_market_month,
)
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.validation.feature_report import FeatureRow, build_feature_row
from trend_scanner.validation.feature_report import to_csv_row as _feature_row_to_csv_row


@dataclass
class HistoricalSnapshot:
    requested_snapshot_date: pd.Timestamp
    effective_as_of: pd.Timestamp | None
    include_incomplete_periods: bool
    monthly_as_of: pd.Timestamp | None
    weekly_as_of: pd.Timestamp | None
    features: FeatureRow
    # look-ahead 방지가 이미 적용된 월봉 원본(OHLCV) 프레임. FeatureRow에
    # 없는 새 Feature 후보를 analysis-only로 시험할 때, 별도로 slicing
    # 로직을 복제하지 않고 이 필드를 그대로 쓰기 위해 추가했다(v0.2 설계
    # 재리뷰 후속). Score/FeatureRow 계산에는 쓰이지 않는다.
    monthly: pd.DataFrame
    # monthly와 동일한 이유(Phase 13E Weekly Feature Research)로 추가한
    # look-ahead 방지 적용된 주봉 원본 프레임. default를 둬서 기존
    # keyword-construction 호출부(예: 합성 테스트)를 깨지 않는다.
    weekly: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))


def _drop_incomplete_current_month(
    monthly: pd.DataFrame,
    requested: pd.Timestamp,
    market_calendar: MarketCalendarAuthority | None = None,
) -> pd.DataFrame:
    """실제 KRX 시장 캘린더 Authority 기준으로 진행 중인 마지막 월봉을 제거한다."""
    if monthly.empty:
        return monthly

    last_label = monthly.index[-1]
    same_month = (last_label.year == requested.year) and (last_label.month == requested.month)
    if same_month and not is_completed_market_month(requested, calendar=market_calendar):
        return monthly.iloc[:-1]
    return monthly


def _drop_incomplete_weekly(weekly: pd.DataFrame, effective_as_of: pd.Timestamp | None) -> pd.DataFrame:
    """weekly.index[-1] > effective_as_of이면 아직 완성되지 않은 마지막 주봉을 제거한다."""
    if weekly.empty or effective_as_of is None:
        return weekly

    if weekly.index[-1] > effective_as_of:
        return weekly.iloc[:-1]
    return weekly


def _last_or_none(df: pd.DataFrame) -> pd.Timestamp | None:
    return df.index[-1] if len(df) else None


def build_historical_snapshot(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    snapshot_date: str | pd.Timestamp,
    include_incomplete_periods: bool = True,
    market_calendar: MarketCalendarAuthority | None = None,
) -> HistoricalSnapshot:
    requested = pd.Timestamp(snapshot_date)

    # look-ahead 방지: snapshot_date 이후 행은 여기서 걸러내고, 이후 계산은
    # 전부 이 sliced만 사용한다.
    sliced = daily[daily.index <= requested]
    effective_as_of = sliced.index.max() if len(sliced) else None

    weekly = to_weekly(sliced)
    monthly = to_monthly(sliced)
    if not include_incomplete_periods:
        monthly = _drop_incomplete_current_month(monthly, requested, market_calendar=market_calendar)
        weekly = _drop_incomplete_weekly(weekly, effective_as_of)

    features = build_feature_row(ticker, name, sliced, weekly, monthly)

    return HistoricalSnapshot(
        requested_snapshot_date=requested,
        effective_as_of=effective_as_of,
        include_incomplete_periods=include_incomplete_periods,
        monthly_as_of=_last_or_none(monthly),
        weekly_as_of=_last_or_none(weekly),
        features=features,
        monthly=monthly,
        weekly=weekly,
    )


def to_csv_row(label: str, snapshot: HistoricalSnapshot) -> dict[str, Any]:
    row: dict[str, Any] = {
        "label": label,
        "requested_snapshot_date": snapshot.requested_snapshot_date,
        "effective_as_of": snapshot.effective_as_of,
        "include_incomplete_periods": snapshot.include_incomplete_periods,
        "monthly_as_of": snapshot.monthly_as_of,
        "weekly_as_of": snapshot.weekly_as_of,
    }
    row.update(_feature_row_to_csv_row(snapshot.features))
    return row
