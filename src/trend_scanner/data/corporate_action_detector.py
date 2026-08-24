"""Corporate-action dirty evidence detector.

This module answers only whether an adjusted history should be refreshed.  It
does not infer an event type and never changes OHLC values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.errors import MarketDataError


LISTED_SHARES_CHANGED = "LISTED_SHARES_CHANGED"
PAR_VALUE_CHANGED = "PAR_VALUE_CHANGED"
LISTED_SHARES_AND_PAR_VALUE_CHANGED = "LISTED_SHARES_AND_PAR_VALUE_CHANGED"
INITIAL_BASELINE = "INITIAL_BASELINE"
SOURCE_SEMANTIC_CONFLICT = "SOURCE_SEMANTIC_CONFLICT"


def normalise_as_of(value: Any) -> date:
    """Return a strict calendar date or fail closed."""

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"유효하지 않은 as_of입니다: {value!r}") from exc
    if pd.isna(timestamp):
        raise MarketDataError(f"유효하지 않은 as_of입니다: {value!r}")
    return timestamp.date()


def _normalise_listed_shares(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise MarketDataError("listed_shares는 0보다 큰 정수여야 합니다.")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"listed_shares를 숫자로 변환할 수 없습니다: {value!r}") from exc
    if not math.isfinite(numeric) or numeric <= 0 or not numeric.is_integer():
        raise MarketDataError("listed_shares는 0보다 큰 정수여야 합니다.")
    return int(numeric)


def _normalise_par_value(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        raise MarketDataError("par_value는 음수가 아닌 숫자여야 합니다.")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"par_value를 숫자로 변환할 수 없습니다: {value!r}") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise MarketDataError("par_value는 음수가 아닌 숫자여야 합니다.")
    return int(numeric) if numeric.is_integer() else numeric


@dataclass(frozen=True)
class CorporateActionSnapshot:
    """Point-in-time authority facts used by the dirty detector."""

    ticker: str
    as_of: date | str
    listed_shares: int | float | str
    par_value: int | float | str | None = None
    listed_shares_semantics: str = "RAW_DAILY_LISTED_SHARES"
    source_name: str = "KRX_AUTHORITY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        object.__setattr__(self, "as_of", normalise_as_of(self.as_of))
        object.__setattr__(self, "listed_shares", _normalise_listed_shares(self.listed_shares))
        object.__setattr__(self, "par_value", _normalise_par_value(self.par_value))
        if not self.listed_shares_semantics:
            raise MarketDataError("listed_shares_semantics는 비어 있을 수 없습니다.")
        if not self.source_name:
            raise MarketDataError("source_name은 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class CorporateActionDecision:
    """Comparison result; ``is_dirty`` is the only refresh signal."""

    ticker: str
    previous_as_of: date | None
    current_as_of: date
    is_dirty: bool
    dirty_reasons: tuple[str, ...]
    previous_listed_shares: int | None
    current_listed_shares: int
    previous_par_value: int | float | None
    current_par_value: int | float | None
    listed_shares_ratio: float | None = None
    par_value_ratio: float | None = None


class CorporateActionDetector:
    """Compare two authority snapshots without classifying corporate actions."""

    def evaluate(
        self,
        previous: CorporateActionSnapshot | None,
        current: CorporateActionSnapshot,
    ) -> CorporateActionDecision:
        if previous is not None and previous.ticker != current.ticker:
            raise MarketDataError("서로 다른 ticker snapshot은 비교할 수 없습니다.")
        if previous is None:
            return CorporateActionDecision(
                ticker=current.ticker,
                previous_as_of=None,
                current_as_of=current.as_of,
                is_dirty=False,
                dirty_reasons=(),
                previous_listed_shares=None,
                current_listed_shares=current.listed_shares,
                previous_par_value=None,
                current_par_value=current.par_value,
            )
        if previous.listed_shares_semantics != current.listed_shares_semantics:
            raise MarketDataError(
                f"{SOURCE_SEMANTIC_CONFLICT}: listed_shares semantic namespace가 다릅니다."
            )
        if previous.as_of > current.as_of:
            raise MarketDataError("OUT_OF_ORDER: previous.as_of가 current.as_of보다 늦습니다.")
        if previous.as_of == current.as_of and (
            previous.listed_shares != current.listed_shares
            or previous.par_value != current.par_value
        ):
            raise MarketDataError("SOURCE_CONFLICT: 동일 날짜에 authority 값이 다릅니다.")

        listed_changed = previous.listed_shares != current.listed_shares
        par_comparable = previous.par_value is not None and current.par_value is not None
        par_changed = par_comparable and previous.par_value != current.par_value
        if listed_changed and par_changed:
            reasons = (LISTED_SHARES_AND_PAR_VALUE_CHANGED,)
        elif listed_changed:
            reasons = (LISTED_SHARES_CHANGED,)
        elif par_changed:
            reasons = (PAR_VALUE_CHANGED,)
        else:
            reasons = ()

        listed_ratio = current.listed_shares / previous.listed_shares
        par_ratio = None
        if par_comparable and previous.par_value != 0:
            par_ratio = float(current.par_value / previous.par_value)
        return CorporateActionDecision(
            ticker=current.ticker,
            previous_as_of=previous.as_of,
            current_as_of=current.as_of,
            is_dirty=bool(reasons),
            dirty_reasons=reasons,
            previous_listed_shares=previous.listed_shares,
            current_listed_shares=current.listed_shares,
            previous_par_value=previous.par_value,
            current_par_value=current.par_value,
            listed_shares_ratio=listed_ratio,
            par_value_ratio=par_ratio,
        )


__all__ = [
    "CorporateActionDecision",
    "CorporateActionDetector",
    "CorporateActionSnapshot",
    "INITIAL_BASELINE",
    "LISTED_SHARES_AND_PAR_VALUE_CHANGED",
    "LISTED_SHARES_CHANGED",
    "PAR_VALUE_CHANGED",
    "SOURCE_SEMANTIC_CONFLICT",
    "normalise_as_of",
]
