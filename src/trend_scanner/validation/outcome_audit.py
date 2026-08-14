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

**부분 horizon 처리**: 캐시된 daily가 base_date + N개월까지 실제로
도달하지 못하면(예: 최근 snapshot이라 아직 12개월이 안 지남) 그 구간은
"완성되지 않음"이다. `complete_3m`/`complete_6m`/`complete_12m`으로
구간별 완성 여부를 노출한다. `return_6m_end`/`return_12m_end`는 구간이
완성되지 않았으면 NaN이다(있는 데이터의 마지막 값을 "그 시점의 수익률"
이라고 잘못 부르지 않기 위해서). `return_*_max`/drawdown/peak까지의
개월수는 구간이 미완성이어도 있는 데이터로 계산은 하되, 반드시
`complete_*` 플래그와 같이 봐야 한다(부분 데이터 기준값일 수 있다).
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
    complete_3m: bool
    complete_6m: bool
    complete_12m: bool


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
        complete_3m=False,
        complete_6m=False,
        complete_12m=False,
    )


def _window_end(base_date: pd.Timestamp, months: int) -> pd.Timestamp:
    return base_date + pd.Timedelta(days=months * _DAYS_PER_MONTH)


def _forward_close(daily: pd.DataFrame, base_date: pd.Timestamp, months: int) -> pd.Series:
    window_end = _window_end(base_date, months)
    mask = (daily.index > base_date) & (daily.index <= window_end)
    return daily.loc[mask, "close"]


def _max_return(close: pd.Series, base_close: float) -> float:
    if close.empty or base_close == 0:
        return NAN
    return (close.max() - base_close) / base_close


def _end_return(close: pd.Series, base_close: float, complete: bool) -> float:
    if not complete or close.empty or base_close == 0:
        return NAN
    return (close.iloc[-1] - base_close) / base_close


def _max_drawdown(base_close: float, close: pd.Series) -> float:
    """구간 내 running max 대비 최대 낙폭(peak-to-trough, 음수).

    base_close를 시작값으로 포함해서 running max를 만든다. 그러지 않으면
    snapshot 직후(구간의 첫 거래일 이전) 발생한 하락이 계산에서 빠진다 —
    예: base_close=100인데 그 다음 거래일부터 80, 70으로 떨어지면, close만
    보고 만든 running max는 80에서 시작해 낙폭을 -12.5%로 과소평가한다.
    base_close를 포함하면 100 -> 80 -> 70의 진짜 낙폭 -30%가 잡힌다.
    """
    if close.empty:
        return NAN
    combined = pd.concat([pd.Series([base_close]), close], ignore_index=True)
    running_max = combined.cummax()
    drawdown = (combined - running_max) / running_max
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
    부족한 구간(예: 최근 snapshot이라 아직 12개월이 안 지남)은 있는
    만큼만 계산하되, complete_3m/6m/12m으로 그 사실을 노출한다 — 실패시키지
    않는다.
    """
    requested = pd.Timestamp(base_date)
    available = daily.index[daily.index <= requested]
    if len(available) == 0:
        return _empty()

    base_date_actual = available.max()
    base_close = daily.loc[base_date_actual, "close"]
    data_end = daily.index.max()

    close_3m = _forward_close(daily, base_date_actual, 3)
    close_6m = _forward_close(daily, base_date_actual, 6)
    close_12m = _forward_close(daily, base_date_actual, 12)

    complete_3m = data_end >= _window_end(base_date_actual, 3)
    complete_6m = data_end >= _window_end(base_date_actual, 6)
    complete_12m = data_end >= _window_end(base_date_actual, 12)

    return OutcomeMetrics(
        base_date=base_date_actual,
        base_close=base_close,
        return_3m_max=_max_return(close_3m, base_close),
        return_6m_max=_max_return(close_6m, base_close),
        return_12m_max=_max_return(close_12m, base_close),
        return_6m_end=_end_return(close_6m, base_close, complete_6m),
        return_12m_end=_end_return(close_12m, base_close, complete_12m),
        drawdown_12m_max=_max_drawdown(base_close, close_12m),
        months_to_peak_12m=_months_to_peak(close_12m, base_date_actual),
        complete_3m=complete_3m,
        complete_6m=complete_6m,
        complete_12m=complete_12m,
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
        "complete_3m": outcome.complete_3m,
        "complete_6m": outcome.complete_6m,
        "complete_12m": outcome.complete_12m,
    }
