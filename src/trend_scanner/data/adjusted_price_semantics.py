"""Shared adjusted-price source/closure semantics.

The authoritative source may contain finite positive OHLC values that do not
form a physically valid candle.  Such rows are source observations and must
not be rewritten before the closure accounting layer has seen them.
"""

from __future__ import annotations

from enum import Enum
import math
from typing import Any

import pandas as pd

from trend_scanner.data.errors import MarketDataError


TRADABILITY_CONTRACT_VERSION = "adjusted_price_tradability_v02"
CLOSURE_ACCOUNTING_SCHEMA_VERSION = "adjusted_price_closure_accounting_v02"


class ClosureState(str, Enum):
    USABLE_ADJUSTED_OBSERVATION = "USABLE_ADJUSTED_OBSERVATION"
    CONFIRMED_NONTRADING = "CONFIRMED_NONTRADING"
    ADJUDICATED_SOURCE_NONUSABLE = "ADJUDICATED_SOURCE_NONUSABLE"
    SILENT_MISSING = "SILENT_MISSING"
    UNEXPECTED_SOURCE_DATE = "UNEXPECTED_SOURCE_DATE"
    SUSPENSION_METADATA_CONFLICT_WITH_OBSERVED_ACTIVITY = (
        "SUSPENSION_METADATA_CONFLICT_WITH_OBSERVED_ACTIVITY"
    )
    UNRESOLVED_ACTIVITY_EVIDENCE = "UNRESOLVED_ACTIVITY_EVIDENCE"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def is_zero_ohlc_phantom(open_val: Any, high_val: Any, low_val: Any, close_val: Any) -> bool:
    """Return the source's exact zero-OHL, positive-close shape."""

    return (
        _finite(open_val)
        and _finite(high_val)
        and _finite(low_val)
        and _finite(close_val)
        and float(open_val) == 0.0
        and float(high_val) == 0.0
        and float(low_val) == 0.0
        and float(close_val) > 0.0
    )


def classify_source_row(
    open_val: Any,
    high_val: Any,
    low_val: Any,
    close_val: Any,
    volume: Any | None = None,
    trading_value: Any | None = None,
) -> ClosureState:
    """Classify one raw source row without manufacturing an OHLC candle.

    Missing activity evidence is deliberately *not* treated as confirmed
    non-trading.  This prevents a shape-only heuristic from erasing an
    expected date.
    """

    values = (open_val, high_val, low_val, close_val)
    if not all(_finite(value) for value in values):
        return ClosureState.ADJUDICATED_SOURCE_NONUSABLE

    if is_zero_ohlc_phantom(*values):
        if volume is None and trading_value is None:
            return ClosureState.UNRESOLVED_ACTIVITY_EVIDENCE
        if not (_finite(volume) and _finite(trading_value)):
            return ClosureState.ADJUDICATED_SOURCE_NONUSABLE
        if float(volume) == 0.0 and float(trading_value) == 0.0:
            return ClosureState.CONFIRMED_NONTRADING
        return ClosureState.ADJUDICATED_SOURCE_NONUSABLE

    if any(float(value) <= 0.0 for value in values):
        return ClosureState.ADJUDICATED_SOURCE_NONUSABLE
    return ClosureState.USABLE_ADJUSTED_OBSERVATION


def is_confirmed_nontrading(
    open_val: Any,
    high_val: Any,
    low_val: Any,
    close_val: Any,
    volume: Any | None = None,
    trading_value: Any | None = None,
) -> bool:
    return classify_source_row(
        open_val, high_val, low_val, close_val, volume, trading_value
    ) == ClosureState.CONFIRMED_NONTRADING


def analytic_candle_is_valid(frame: pd.DataFrame) -> pd.Series:
    """Return physical candle validity independently of source integrity."""

    required = ("open", "high", "low", "close")
    if tuple(frame.columns) != required:
        raise MarketDataError(f"수정주가 frame schema가 정확히 OHLC가 아닙니다: {list(frame.columns)}")
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    finite = numeric.notna().all(axis=1)
    positive = (numeric > 0).all(axis=1)
    relation = (
        (numeric["high"] >= numeric[["open", "close"]].max(axis=1))
        & (numeric["low"] <= numeric[["open", "close"]].min(axis=1))
        & (numeric["high"] >= numeric["low"])
    )
    return finite & positive & relation


def validate_source_integrity(frame: pd.DataFrame) -> None:
    """Validate source shape/order/finiteness while allowing relation anomalies."""

    required = ("open", "high", "low", "close")
    if tuple(frame.columns) != required:
        raise MarketDataError(
            f"수정주가 frame schema가 정확히 OHLC가 아닙니다: {list(frame.columns)}"
        )
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise MarketDataError(f"index가 DatetimeIndex가 아닙니다: {type(frame.index)}")
    if frame.empty:
        return
    if not frame.index.is_monotonic_increasing:
        raise MarketDataError("수정주가 거래일 index가 오름차순이 아닙니다.")
    if not frame.index.is_unique:
        raise MarketDataError("수정주가 거래일 index에 중복이 있습니다.")
    numeric = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    finite = numeric.apply(lambda column: column.map(_finite))
    if not finite.all().all():
        raise MarketDataError("수정주가 source OHLC에 finite하지 않은 값이 있습니다.")


__all__ = [
    "CLOSURE_ACCOUNTING_SCHEMA_VERSION",
    "ClosureState",
    "TRADABILITY_CONTRACT_VERSION",
    "analytic_candle_is_valid",
    "classify_source_row",
    "is_confirmed_nontrading",
    "is_zero_ohlc_phantom",
    "validate_source_integrity",
]
