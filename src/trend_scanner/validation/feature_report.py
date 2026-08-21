"""Feature Validation v0.1: 실제 종목의 Feature 원본값을 계산해 사람이 비교할 수 있는
Report row로 만든다.

Pattern A 점수는 만들지 않는다. 기존 features/ 함수를 최대한 재사용하고, 여기서
새로 계산하는 값(range_36m, compression_ratio 등)은 기존 Pattern A 스펙 문서
(docs/patterns/pattern_a/spec/production_authority.md)에 이미 정의된 산식을 그대로 옮긴 것일 뿐, 새로운
Feature 라이브러리 함수로 승격하지 않는다.

계산과 출력을 분리한다: 이 모듈은 값을 계산만 하고 print/CSV 쓰기는 하지 않는다.
scripts/validate_features.py가 이 모듈의 결과를 받아 화면/CSV로 출력한다.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable

import pandas as pd

from trend_scanner.features.moving_average import (
    ma_slope,
    ma_slope_acceleration,
    ma_spread,
    ma_spread_ratio,
    moving_average,
)
from trend_scanner.features.pivot import find_pivot_lows, pivot_low_regression_slope
from trend_scanner.features.resistance import distance_to_resistance, range_position
from trend_scanner.features.volatility import atr_pct

NAN = float("nan")


def _safe(fn: Callable[..., float], *args: Any, **kwargs: Any) -> float:
    """lookback 부족 등으로 fn이 IndexError/ValueError를 던지면 NaN으로 대체한다."""
    try:
        return fn(*args, **kwargs)
    except (IndexError, ValueError):
        return NAN


def _at_or_nan(series: pd.Series, position: int) -> float:
    """series.iloc[position]. out-of-range면 NaN(빈 series 포함)."""
    try:
        return series.iloc[position]
    except IndexError:
        return NAN


def _is_missing(value: Any) -> bool:
    """NaN/None/NaT를 모두 '값 없음'으로 취급한다(pd.isna 기반)."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _safe_div(numerator: float, denominator: float) -> float:
    if _is_missing(numerator) or _is_missing(denominator) or denominator == 0:
        return NAN
    return numerator / denominator


@dataclass
class FeatureRow:
    ticker: str
    name: str
    as_of: Any
    daily_rows: int
    weekly_rows: int
    monthly_rows: int
    monthly_bar_may_be_incomplete: bool
    weekly_bar_may_be_incomplete: bool

    # 가격 구조
    close: float
    high_36m: float
    low_36m: float
    high_24m: float
    low_24m: float
    high_12m: float
    low_12m: float
    range_36m: float
    range_24m: float
    range_12m: float
    compression_ratio: float
    avg_price_change_12m: float
    range_position: float
    distance_to_resistance: float

    # Pivot Low 구조
    pivot_low_count: int
    pivot_low_1: float
    pivot_low_1_date: Any
    pivot_low_2: float
    pivot_low_2_date: Any
    pivot_low_3: float
    pivot_low_3_date: Any
    pivot_low_slope: float

    # Moving Average 구조
    ma6: float
    ma12: float
    ma24: float
    ma6_slope: float
    ma12_slope: float
    ma24_slope: float
    ma24_slope_acceleration: float
    ma_spread: float
    ma_spread_12m_ago: float
    ma_spread_ratio: float

    # Volatility (참고용, Pattern score에 사용하지 않음)
    atr_pct: float
    atr_pct_12m_ago: float
    atr_ratio: float
    avg_monthly_hl_range_12m: float

    # 거래량 / 거래대금 (참고용)
    volume_3m_avg: float
    volume_12m_avg: float
    volume_ratio_3m_12m: float
    trading_value_3m_avg: float
    trading_value_12m_avg: float
    trading_value_ratio_3m_12m: float
    trading_value_nan_ratio_daily: float

    # Weekly confirmation
    range_position_52w: float
    weekly_ma12_slope: float


def _window_high_low(monthly: pd.DataFrame, months: int) -> tuple[float, float]:
    if len(monthly) < months:
        return NAN, NAN
    window = monthly.tail(months)
    return float(window["high"].max()), float(window["low"].min())


def _range(monthly: pd.DataFrame, months: int) -> float:
    if len(monthly) < months:
        return NAN
    window = monthly.tail(months)
    high = window["high"].max()
    low = window["low"].min()
    mean_close = window["close"].mean()
    return _safe_div(high - low, mean_close)


def _avg_price_change_12m(monthly: pd.DataFrame) -> float:
    """최근 12개월 평균 종가 대비 직전 12개월 평균 종가의 변화율. 24개월 미만이면 NaN."""
    if len(monthly) < 24:
        return NAN
    recent_12 = monthly["close"].tail(12).mean()
    prior_12 = monthly["close"].iloc[-24:-12].mean()
    return _safe_div(recent_12 - prior_12, prior_12)


def _pivot_low_slots(pivots: list[tuple]) -> tuple[list[float], list[Any]]:
    recent = pivots[-3:]
    prices = [float(v) for _, v in recent]
    dates = [d for d, _ in recent]
    while len(prices) < 3:
        prices.append(NAN)
        dates.append(None)
    return prices, dates


def _bar_may_be_incomplete(bar_index: pd.DatetimeIndex, as_of: Any) -> bool:
    if len(bar_index) == 0 or as_of is None:
        return False
    return bool(bar_index.max() > as_of)


def build_feature_row(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    monthly: pd.DataFrame,
) -> FeatureRow:
    as_of = daily.index.max() if len(daily) else None
    if _is_missing(as_of):
        as_of = None

    monthly_close = monthly["close"] if "close" in monthly.columns else pd.Series(dtype=float)
    close = _at_or_nan(monthly_close, -1)

    high_36m, low_36m = _window_high_low(monthly, 36)
    high_24m, low_24m = _window_high_low(monthly, 24)
    high_12m, low_12m = _window_high_low(monthly, 12)

    range_36m = _range(monthly, 36)
    range_24m = _range(monthly, 24)
    range_12m = _range(monthly, 12)
    compression_ratio = _safe_div(range_12m, range_36m)

    pos_range_position = range_position(close, low_36m, high_36m)
    pos_distance_to_resistance = distance_to_resistance(close, high_36m)

    pivots = find_pivot_lows(monthly["low"], window=2) if "low" in monthly.columns else []
    pivot_prices, pivot_dates = _pivot_low_slots(pivots)
    pivot_slope = pivot_low_regression_slope(pivots, lookback=4)

    ma6_series = moving_average(monthly_close, 6)
    ma12_series = moving_average(monthly_close, 12)
    ma24_series = moving_average(monthly_close, 24)

    ma6_now = _at_or_nan(ma6_series, -1)
    ma12_now = _at_or_nan(ma12_series, -1)
    ma24_now = _at_or_nan(ma24_series, -1)

    ma6_slope = _safe(ma_slope, ma6_series, periods=3)
    ma12_slope = _safe(ma_slope, ma12_series, periods=3)
    ma24_slope = _safe(ma_slope, ma24_series, periods=3)
    ma24_slope_acceleration = _safe(ma_slope_acceleration, ma24_series, periods=3, lag=3)

    spread_now = (
        ma_spread([ma6_now, ma12_now, ma24_now], close) if not _is_missing(close) else NAN
    )
    ma6_ago = _at_or_nan(ma6_series, -13)
    ma12_ago = _at_or_nan(ma12_series, -13)
    ma24_ago = _at_or_nan(ma24_series, -13)
    close_ago = _at_or_nan(monthly_close, -13)
    spread_ago = (
        ma_spread([ma6_ago, ma12_ago, ma24_ago], close_ago)
        if not _is_missing(close_ago)
        else NAN
    )
    spread_ratio = ma_spread_ratio(spread_now, spread_ago)

    atr_series = atr_pct(monthly) if {"high", "low", "close"} <= set(monthly.columns) else pd.Series(dtype=float)
    atr_now = _at_or_nan(atr_series, -1)
    atr_ago = _at_or_nan(atr_series, -13)
    atr_ratio_value = _safe_div(atr_now, atr_ago)

    avg_monthly_hl_range_12m = (
        float((monthly["high"] - monthly["low"]).tail(12).mean()) if len(monthly) >= 12 else NAN
    )

    volume_3m_avg = float(monthly["volume"].tail(3).mean()) if len(monthly) >= 3 else NAN
    volume_12m_avg = float(monthly["volume"].tail(12).mean()) if len(monthly) >= 12 else NAN
    volume_ratio = _safe_div(volume_3m_avg, volume_12m_avg)

    trading_value_3m_avg = (
        float(monthly["trading_value"].tail(3).mean()) if len(monthly) >= 3 else NAN
    )
    trading_value_12m_avg = (
        float(monthly["trading_value"].tail(12).mean()) if len(monthly) >= 12 else NAN
    )
    trading_value_ratio = _safe_div(trading_value_3m_avg, trading_value_12m_avg)

    trading_value_nan_ratio_daily = (
        float(daily["trading_value"].isna().mean())
        if "trading_value" in daily.columns and len(daily)
        else NAN
    )

    weekly_close_series = weekly["close"] if "close" in weekly.columns else pd.Series(dtype=float)
    weekly_close = _at_or_nan(weekly_close_series, -1)
    high_52w, low_52w = _window_high_low(weekly, 52)
    range_position_52w = range_position(weekly_close, low_52w, high_52w)

    weekly_ma12_series = moving_average(weekly_close_series, 12)
    weekly_ma12_slope = _safe(ma_slope, weekly_ma12_series, periods=4)

    return FeatureRow(
        ticker=ticker,
        name=name,
        as_of=as_of,
        daily_rows=len(daily),
        weekly_rows=len(weekly),
        monthly_rows=len(monthly),
        monthly_bar_may_be_incomplete=_bar_may_be_incomplete(monthly.index, as_of),
        weekly_bar_may_be_incomplete=_bar_may_be_incomplete(weekly.index, as_of),
        close=close,
        high_36m=high_36m,
        low_36m=low_36m,
        high_24m=high_24m,
        low_24m=low_24m,
        high_12m=high_12m,
        low_12m=low_12m,
        range_36m=range_36m,
        range_24m=range_24m,
        range_12m=range_12m,
        compression_ratio=compression_ratio,
        avg_price_change_12m=_avg_price_change_12m(monthly),
        range_position=pos_range_position,
        distance_to_resistance=pos_distance_to_resistance,
        pivot_low_count=len(pivots),
        pivot_low_1=pivot_prices[0],
        pivot_low_1_date=pivot_dates[0],
        pivot_low_2=pivot_prices[1],
        pivot_low_2_date=pivot_dates[1],
        pivot_low_3=pivot_prices[2],
        pivot_low_3_date=pivot_dates[2],
        pivot_low_slope=pivot_slope,
        ma6=ma6_now,
        ma12=ma12_now,
        ma24=ma24_now,
        ma6_slope=ma6_slope,
        ma12_slope=ma12_slope,
        ma24_slope=ma24_slope,
        ma24_slope_acceleration=ma24_slope_acceleration,
        ma_spread=spread_now,
        ma_spread_12m_ago=spread_ago,
        ma_spread_ratio=spread_ratio,
        atr_pct=atr_now,
        atr_pct_12m_ago=atr_ago,
        atr_ratio=atr_ratio_value,
        avg_monthly_hl_range_12m=avg_monthly_hl_range_12m,
        volume_3m_avg=volume_3m_avg,
        volume_12m_avg=volume_12m_avg,
        volume_ratio_3m_12m=volume_ratio,
        trading_value_3m_avg=trading_value_3m_avg,
        trading_value_12m_avg=trading_value_12m_avg,
        trading_value_ratio_3m_12m=trading_value_ratio,
        trading_value_nan_ratio_daily=trading_value_nan_ratio_daily,
        range_position_52w=range_position_52w,
        weekly_ma12_slope=weekly_ma12_slope,
    )


def to_csv_row(row: FeatureRow) -> dict[str, Any]:
    return {f.name: getattr(row, f.name) for f in fields(row)}


def format_human_report(row: FeatureRow) -> str:
    def fmt(value: Any, digits: int = 4) -> str:
        if value is None:
            return "N/A"
        if _is_missing(value):
            return "NaN"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    lines = [
        f"[{row.ticker} {row.name}]",
        "",
        f"As Of: {fmt(row.as_of, 0)}",
        f"Daily Bars: {row.daily_rows}",
        f"Monthly Bars: {row.monthly_rows}"
        + (" (마지막 봉 미완성 가능)" if row.monthly_bar_may_be_incomplete else ""),
        f"Weekly Bars: {row.weekly_rows}"
        + (" (마지막 봉 미완성 가능)" if row.weekly_bar_may_be_incomplete else ""),
        "",
        "Price Structure",
        f"  Close: {fmt(row.close, 0)}",
        f"  Range 36M: {fmt(row.range_36m)}",
        f"  Range 24M: {fmt(row.range_24m)}",
        f"  Range 12M: {fmt(row.range_12m)}",
        f"  Compression Ratio: {fmt(row.compression_ratio)}",
        f"  Avg Price Change 12M: {fmt(row.avg_price_change_12m)}",
        f"  Range Position: {fmt(row.range_position)}",
        f"  Distance to Resistance: {fmt(row.distance_to_resistance)}",
        "",
        "Low Structure",
        f"  Recent Pivot Lows: {fmt(row.pivot_low_1, 0)} ({fmt(row.pivot_low_1_date, 0)}), "
        f"{fmt(row.pivot_low_2, 0)} ({fmt(row.pivot_low_2_date, 0)}), "
        f"{fmt(row.pivot_low_3, 0)} ({fmt(row.pivot_low_3_date, 0)})",
        f"  Pivot Low Count: {row.pivot_low_count}",
        f"  Pivot Low Slope: {fmt(row.pivot_low_slope, 6)}",
        "",
        "MA Transition",
        f"  MA6: {fmt(row.ma6, 0)}",
        f"  MA12: {fmt(row.ma12, 0)}",
        f"  MA24: {fmt(row.ma24, 0)}",
        f"  MA24 Slope: {fmt(row.ma24_slope)}",
        f"  MA24 Acceleration: {fmt(row.ma24_slope_acceleration)}",
        f"  MA Spread: {fmt(row.ma_spread)}",
        f"  MA Spread Ratio: {fmt(row.ma_spread_ratio)}",
        "",
        "Volatility (참고용)",
        f"  ATR%: {fmt(row.atr_pct)}",
        f"  ATR Ratio: {fmt(row.atr_ratio)}",
        "",
        "Volume (참고용)",
        f"  3M/12M Ratio: {fmt(row.volume_ratio_3m_12m)}",
        "",
        "Trading Value (참고용)",
        f"  3M/12M Ratio: {fmt(row.trading_value_ratio_3m_12m)}",
        f"  Daily NaN Ratio: {fmt(row.trading_value_nan_ratio_daily)}",
        "",
        "Weekly Confirmation",
        f"  Range Position 52W: {fmt(row.range_position_52w)}",
        f"  Weekly MA12 Slope: {fmt(row.weekly_ma12_slope)}",
    ]
    return "\n".join(lines)
