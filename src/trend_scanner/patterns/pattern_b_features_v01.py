"""Pattern B Feature Contract V01 — raw feature values (research only).

Contract: docs/patterns/pattern_b/spec/feature_contract_v01.md

Computes the seven V01 raw features from adjusted daily OHLC as of one date.
No threshold, score, weighting, or state classification lives here.

PIT order of operations:
1. Drop every daily row after ``as_of``.
2. Validate the remaining adjusted high/low/close (fail loudly, never fall back).
3. Aggregate completed bars: a month (MonthEnd) or week (W-FRI) counts only when
   its calendar label is on or before ``as_of``. Periods without any session
   (trading halts) produce no bar.
4. Windows and return offsets count completed bars, not calendar periods.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


RANGE_POSITION_36M = "36M_RANGE_POSITION"
MONTHLY_MA24_DISTANCE = "MONTHLY_MA24_DISTANCE"
RETURN_12M_PERCENTILE = "12M_RETURN_HISTORICAL_PERCENTILE"
HIGH_DRAWDOWN_36M = "36M_HIGH_DRAWDOWN"
RANGE_POSITION_52W = "52W_RANGE_POSITION"
WEEKLY_MA40_DISTANCE = "WEEKLY_MA40_DISTANCE"
RETURN_26W_PERCENTILE = "26W_RETURN_HISTORICAL_PERCENTILE"

FEATURE_NAMES: tuple[str, ...] = (
    RANGE_POSITION_36M,
    MONTHLY_MA24_DISTANCE,
    RETURN_12M_PERCENTILE,
    HIGH_DRAWDOWN_36M,
    RANGE_POSITION_52W,
    WEEKLY_MA40_DISTANCE,
    RETURN_26W_PERCENTILE,
)

MONTHLY_RANGE_BARS = 36
MONTHLY_MA_BARS = 24
MONTHLY_RETURN_BARS = 12
MONTHLY_MIN_REFERENCE = 24
WEEKLY_RANGE_BARS = 52
WEEKLY_MA_BARS = 40
WEEKLY_RETURN_BARS = 26
WEEKLY_MIN_REFERENCE = 52

STATUS_OK = "OK"
STATUS_INSUFFICIENT_BARS = "INSUFFICIENT_BARS"
STATUS_FLAT_RANGE = "FLAT_RANGE"
STATUS_INSUFFICIENT_REFERENCE = "INSUFFICIENT_REFERENCE"

_REQUIRED_COLUMNS = ("high", "low", "close")
_OHLC_AGG = {"high": "max", "low": "min", "close": "last"}


class PatternBFeatureInputError(ValueError):
    """Adjusted OHLC input is missing or invalid; no fallback is attempted."""


@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    status: str
    reason: str = ""


@dataclass(frozen=True)
class PatternBFeaturesV01:
    as_of: pd.Timestamp
    monthly_last_bar: pd.Timestamp | None
    weekly_last_bar: pd.Timestamp | None
    monthly_bar_count: int
    weekly_bar_count: int
    features: dict[str, FeatureValue]


def _ok(value: float) -> FeatureValue:
    return FeatureValue(float(value), STATUS_OK)


def _unavailable(status: str, reason: str) -> FeatureValue:
    return FeatureValue(None, status, reason)


def _validated_daily(daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Truncate to ``as_of`` first, then validate; rows after ``as_of`` are never inspected."""
    if not isinstance(daily.index, pd.DatetimeIndex):
        raise PatternBFeatureInputError("daily index must be a DatetimeIndex")
    missing = [c for c in _REQUIRED_COLUMNS if c not in daily.columns]
    if missing:
        raise PatternBFeatureInputError(f"missing adjusted columns: {missing}")
    frame = daily.sort_index()
    frame = frame.loc[frame.index <= as_of, list(_REQUIRED_COLUMNS)]
    if frame.index.has_duplicates:
        raise PatternBFeatureInputError("duplicate daily dates")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise PatternBFeatureInputError("adjusted OHLC contains missing or non-finite values")
    if (values <= 0).any():
        raise PatternBFeatureInputError("adjusted OHLC contains non-positive values")
    high, low, close = frame["high"], frame["low"], frame["close"]
    if ((low > high) | (close > high) | (close < low)).any():
        raise PatternBFeatureInputError("adjusted OHLC violates low <= close <= high")
    return frame


def completed_bars(daily: pd.DataFrame, rule, as_of: pd.Timestamp) -> pd.DataFrame:
    """Completed bars for ``rule`` whose calendar label is on or before ``as_of``."""
    bars = daily.resample(rule).agg(_OHLC_AGG).dropna(subset=["close"])
    return bars[bars.index <= as_of]


def mid_rank_percentile(reference: np.ndarray, current: float) -> float:
    """Empirical mid-rank percentile of ``current`` within ``reference`` (0~100)."""
    reference = np.asarray(reference, dtype=float)
    below = np.count_nonzero(reference < current)
    equal = np.count_nonzero(reference == current)
    return 100.0 * (below + 0.5 * equal) / len(reference)


def _range_position(bars: pd.DataFrame, window: int) -> FeatureValue:
    if len(bars) < window:
        return _unavailable(STATUS_INSUFFICIENT_BARS, f"need {window} bars, have {len(bars)}")
    recent = bars.iloc[-window:]
    low, high = recent["low"].min(), recent["high"].max()
    if high == low:
        return _unavailable(STATUS_FLAT_RANGE, f"{window}-bar high equals low")
    return _ok((recent["close"].iloc[-1] - low) / (high - low))


def _ma_distance(bars: pd.DataFrame, window: int) -> FeatureValue:
    if len(bars) < window:
        return _unavailable(STATUS_INSUFFICIENT_BARS, f"need {window} bars, have {len(bars)}")
    closes = bars["close"].iloc[-window:]
    return _ok(closes.iloc[-1] / closes.mean() - 1.0)


def _high_drawdown(bars: pd.DataFrame, window: int) -> FeatureValue:
    if len(bars) < window:
        return _unavailable(STATUS_INSUFFICIENT_BARS, f"need {window} bars, have {len(bars)}")
    recent = bars.iloc[-window:]
    return _ok(recent["close"].iloc[-1] / recent["high"].max() - 1.0)


def _return_percentile(bars: pd.DataFrame, lag: int, min_reference: int) -> FeatureValue:
    """Current ``lag``-bar return vs. every earlier return (expanding, current excluded)."""
    if len(bars) < lag + 1:
        return _unavailable(STATUS_INSUFFICIENT_BARS, f"need {lag + 1} bars, have {len(bars)}")
    closes = bars["close"].to_numpy(dtype=float)
    returns = closes[lag:] / closes[:-lag] - 1.0
    current, reference = returns[-1], returns[:-1]
    if len(reference) < min_reference:
        return _unavailable(
            STATUS_INSUFFICIENT_REFERENCE,
            f"need {min_reference} reference returns, have {len(reference)}",
        )
    return _ok(mid_rank_percentile(reference, current))


def compute_pattern_b_features_v01(daily: pd.DataFrame, as_of) -> PatternBFeaturesV01:
    """Seven V01 raw features from adjusted daily OHLC (DatetimeIndex; high/low/close)."""
    as_of = pd.Timestamp(as_of).normalize()
    frame = _validated_daily(daily, as_of)
    monthly = completed_bars(frame, pd.offsets.MonthEnd(), as_of)
    weekly = completed_bars(frame, "W-FRI", as_of)
    features = {
        RANGE_POSITION_36M: _range_position(monthly, MONTHLY_RANGE_BARS),
        MONTHLY_MA24_DISTANCE: _ma_distance(monthly, MONTHLY_MA_BARS),
        RETURN_12M_PERCENTILE: _return_percentile(monthly, MONTHLY_RETURN_BARS, MONTHLY_MIN_REFERENCE),
        HIGH_DRAWDOWN_36M: _high_drawdown(monthly, MONTHLY_RANGE_BARS),
        RANGE_POSITION_52W: _range_position(weekly, WEEKLY_RANGE_BARS),
        WEEKLY_MA40_DISTANCE: _ma_distance(weekly, WEEKLY_MA_BARS),
        RETURN_26W_PERCENTILE: _return_percentile(weekly, WEEKLY_RETURN_BARS, WEEKLY_MIN_REFERENCE),
    }
    return PatternBFeaturesV01(
        as_of=as_of,
        monthly_last_bar=monthly.index[-1] if len(monthly) else None,
        weekly_last_bar=weekly.index[-1] if len(weekly) else None,
        monthly_bar_count=len(monthly),
        weekly_bar_count=len(weekly),
        features=features,
    )
