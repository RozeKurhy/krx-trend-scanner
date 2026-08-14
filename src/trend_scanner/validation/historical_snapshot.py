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

completed monthly 정책(v0.1 한계, calendar month 기준): include_incomplete_
periods=False일 때, 진행 중인 월봉인지 판단할 실제 거래소 캘린더를 새로
도입하지 않고 단순 calendar month 기준을 쓴다. snapshot_date가 그 달의
calendar month 마지막 날보다 이르면 마지막 월봉을 "진행 중"으로 보고
제거한다. weekly에는 이 정책을 적용하지 않는다(범위 밖).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.validation.feature_report import FeatureRow, build_feature_row
from trend_scanner.validation.feature_report import to_csv_row as _feature_row_to_csv_row


@dataclass
class HistoricalSnapshot:
    requested_snapshot_date: pd.Timestamp
    effective_as_of: pd.Timestamp | None
    include_incomplete_periods: bool
    features: FeatureRow


def _drop_incomplete_current_month(monthly: pd.DataFrame, requested: pd.Timestamp) -> pd.DataFrame:
    """calendar month 기준으로 진행 중인 마지막 월봉을 제거한다(v0.1 한계, 위 docstring 참고)."""
    if monthly.empty:
        return monthly

    last_label = monthly.index[-1]
    month_end = requested + pd.offsets.MonthEnd(0)
    same_month = (last_label.year == requested.year) and (last_label.month == requested.month)
    if same_month and requested < month_end:
        return monthly.iloc[:-1]
    return monthly


def build_historical_snapshot(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    snapshot_date: str | pd.Timestamp,
    include_incomplete_periods: bool = True,
) -> HistoricalSnapshot:
    requested = pd.Timestamp(snapshot_date)

    # look-ahead 방지: snapshot_date 이후 행은 여기서 걸러내고, 이후 계산은
    # 전부 이 sliced만 사용한다.
    sliced = daily[daily.index <= requested]
    effective_as_of = sliced.index.max() if len(sliced) else None

    weekly = to_weekly(sliced)
    monthly = to_monthly(sliced)
    if not include_incomplete_periods:
        monthly = _drop_incomplete_current_month(monthly, requested)

    features = build_feature_row(ticker, name, sliced, weekly, monthly)

    return HistoricalSnapshot(
        requested_snapshot_date=requested,
        effective_as_of=effective_as_of,
        include_incomplete_periods=include_incomplete_periods,
        features=features,
    )


def to_csv_row(label: str, snapshot: HistoricalSnapshot) -> dict[str, Any]:
    row: dict[str, Any] = {
        "label": label,
        "requested_snapshot_date": snapshot.requested_snapshot_date,
        "effective_as_of": snapshot.effective_as_of,
        "include_incomplete_periods": snapshot.include_incomplete_periods,
    }
    row.update(_feature_row_to_csv_row(snapshot.features))
    return row
