"""Negative Control 재리뷰 후속: Outcome Audit.

label(pre_breakout/early_trend/.../failed_breakout 등)이 우리가 원하는
"대세 상승 성공/실패" 개념과 실제로 맞는지 점검하기 위한, snapshot 이후
실제 가격이 어떻게 움직였는지 보여주는 metadata 계산 모듈이다.

**중요**: 이 모듈이 계산하는 값(미래 수익률, drawdown 등)은
- Feature에 절대 넣지 않는다.
- Pattern A Score에 사용하지 않는다.
- Feature threshold 최적화에도 사용하지 않는다.

오직 기존에 사람이 붙인 label을 검토하기 위한 참고 자료다. 성공/실패
threshold를 새로 정의하지도 않는다 — raw 수치만 보여준다.

Historical Snapshot의 look-ahead 방지 원칙과는 별개의 코드 경로다.
`build_historical_snapshot()`은 여전히 snapshot_date 이하 데이터만
사용해서 Feature를 계산하고, 이 모듈은 그 반대로 snapshot_date **이후**
데이터만 의도적으로 사용해서 outcome을 계산한다. 두 계산은 완전히
독립적이며, 이 모듈의 결과가 Feature 계산 경로로 흘러 들어가는 곳은
없다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

NAN = float("nan")

# 1개월을 30.4375일(365.25/12)로 근사한다. 실제 거래일 캘린더는 쓰지 않는다
# (Historical Snapshot의 completed monthly 정책과 같은 수준의 v0.1 단순화).
_DAYS_PER_MONTH = 30.4375


@dataclass
class OutcomeMetrics:
    base_date: pd.Timestamp | None
    base_close: float
    return_3m_max: float
    return_6m_max: float
    return_12m_max: float
    return_6m_end: float
    return_12m_end: float
    drawdown_12m_max: float
    months_to_peak_12m: float


def _empty(base_date: pd.Timestamp | None = None, base_close: float = NAN) -> OutcomeMetrics:
    return OutcomeMetrics(
        base_date=base_date,
        base_close=base_close,
        return_3m_max=NAN,
        return_6m_max=NAN,
        return_12m_max=NAN,
        return_6m_end=NAN,
        return_12m_end=NAN,
        drawdown_12m_max=NAN,
        months_to_peak_12m=NAN,
    )


def _forward_close(daily: pd.DataFrame, base_date: pd.Timestamp, months: int) -> pd.Series:
    window_end = base_date + pd.Timedelta(days=months * _DAYS_PER_MONTH)
    mask = (daily.index > base_date) & (daily.index <= window_end)
    return daily.loc[mask, "close"]


def _max_return(close: pd.Series, base_close: float) -> float:
    if close.empty or base_close == 0:
        return NAN
    return (close.max() - base_close) / base_close


def _end_return(close: pd.Series, base_close: float) -> float:
    if close.empty or base_close == 0:
        return NAN
    return (close.iloc[-1] - base_close) / base_close


def _max_drawdown(close: pd.Series) -> float:
    """구간 내 running max 대비 최대 낙폭(peak-to-trough, 음수)."""
    if close.empty:
        return NAN
    running_max = close.cummax()
    drawdown = (close - running_max) / running_max
    return drawdown.min()


def _months_to_peak(close: pd.Series, base_date: pd.Timestamp) -> float:
    if close.empty:
        return NAN
    peak_date = close.idxmax()
    return (peak_date - base_date).days / _DAYS_PER_MONTH


def compute_outcome(daily: pd.DataFrame, base_date: str | pd.Timestamp) -> OutcomeMetrics:
    """base_date 이후 daily close로 outcome metric을 계산한다.

    base_date가 daily에 없으면 그 이하에서 가장 최근 거래일을 쓴다
    (Historical Snapshot의 effective_as_of와 같은 방식). base_date 이전
    데이터가 아예 없으면 전부 NaN을 반환한다. base_date 이후 미래 데이터가
    부족한 구간(예: 최근 snapshot이라 아직 12개월이 안 지남)은 그 구간만
    NaN이 된다 — 있는 만큼만 계산하고 실패시키지 않는다.
    """
    requested = pd.Timestamp(base_date)
    available = daily.index[daily.index <= requested]
    if len(available) == 0:
        return _empty()

    base_date_actual = available.max()
    base_close = daily.loc[base_date_actual, "close"]

    close_3m = _forward_close(daily, base_date_actual, 3)
    close_6m = _forward_close(daily, base_date_actual, 6)
    close_12m = _forward_close(daily, base_date_actual, 12)

    return OutcomeMetrics(
        base_date=base_date_actual,
        base_close=base_close,
        return_3m_max=_max_return(close_3m, base_close),
        return_6m_max=_max_return(close_6m, base_close),
        return_12m_max=_max_return(close_12m, base_close),
        return_6m_end=_end_return(close_6m, base_close),
        return_12m_end=_end_return(close_12m, base_close),
        drawdown_12m_max=_max_drawdown(close_12m),
        months_to_peak_12m=_months_to_peak(close_12m, base_date_actual),
    )


def outcome_csv_row(ticker: str, name: str, label: str, outcome: OutcomeMetrics) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "label": label,
        "base_date": outcome.base_date,
        "base_close": outcome.base_close,
        "return_3m_max": outcome.return_3m_max,
        "return_6m_max": outcome.return_6m_max,
        "return_12m_max": outcome.return_12m_max,
        "return_6m_end": outcome.return_6m_end,
        "return_12m_end": outcome.return_12m_end,
        "drawdown_12m_max": outcome.drawdown_12m_max,
        "months_to_peak_12m": outcome.months_to_peak_12m,
    }
