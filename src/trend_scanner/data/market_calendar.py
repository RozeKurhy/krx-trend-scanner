"""Canonical KRX Exchange Trading Calendar & Completed Period Authority.

Provides official exchange-level trading dates and month-end dates based on
the canonical KRX trading calendar artifact (data/reference/krx_trading_calendar.parquet).
Zero reliance on individual stock price series (e.g. 005930) to prevent trading halt distortions.

Ensures unified completed-monthly and completed-weekly period semantics across:
  - Historical Snapshot (build_historical_snapshot)
  - Pattern A FAST Evaluator (evaluate_pattern_a_fast)
  - Stock Report (generate_stock_report)
  - Strategy Finalization & Scanner
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Sequence

import pandas as pd

DEFAULT_CALENDAR_PATH = Path("data/reference/krx_trading_calendar.parquet")


class MarketCalendarUnavailableError(RuntimeError):
    """Raised when KRX Market Calendar Authority is unavailable.
    
    Silent fallback to calendar month-end is strictly forbidden in PIT paths.
    """


@dataclass
class MarketCalendarAuthority:
    """KRX 시장 영업일 및 월말 판정을 담당하는 독립 캘린더 Authority."""

    trading_dates: pd.DatetimeIndex
    source_name: str = "KRX_CANONICAL"
    metadata: dict[str, object] = field(default_factory=dict)

    # Instance-level memoized cache (prevents cross-contamination across fixtures/sources)
    _month_end_map: dict[tuple[int, int], pd.Timestamp] = field(default_factory=dict, init=False, repr=False)
    _trading_dates_set: set[pd.Timestamp] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.trading_dates) > 0:
            norm_dates = pd.DatetimeIndex(self.trading_dates.normalize()).sort_values()
            self.trading_dates = norm_dates
            self._trading_dates_set = set(norm_dates)
            # Build (year, month) -> actual market month end map
            temp_df = pd.DataFrame({"dt": norm_dates}, index=norm_dates)
            monthly_groups = temp_df.groupby([temp_df.index.year, temp_df.index.month])
            self._month_end_map = {
                (int(year), int(month)): group.index.max().normalize()
                for (year, month), group in monthly_groups
            }
        else:
            self._trading_dates_set = set()
            self._month_end_map = {}

    @classmethod
    def from_parquet(
        cls,
        parquet_path: Path | str = DEFAULT_CALENDAR_PATH,
    ) -> MarketCalendarAuthority:
        """Parquet 파일로부터 Canonical Market Calendar Authority를 로드한다."""
        p = Path(parquet_path)
        if not p.exists():
            raise MarketCalendarUnavailableError(
                f"KRX canonical trading calendar file not found at: {p.resolve()}. "
                "Silent fallback to calendar MonthEnd is forbidden."
            )

        df = pd.read_parquet(p)
        if "trading_date" not in df.columns or df.empty:
            raise MarketCalendarUnavailableError(
                f"Invalid KRX trading calendar format in {p.resolve()}: 'trading_date' column missing or empty."
            )

        meta: dict[str, object] = {}
        json_meta_path = p.with_suffix(".json")
        if json_meta_path.exists():
            try:
                meta = json.loads(json_meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        return cls(
            trading_dates=pd.DatetimeIndex(df["trading_date"]),
            source_name=str(meta.get("calendar_source", p.name)),
            metadata=meta,
        )

    @classmethod
    def from_dates(
        cls,
        dates: Sequence[str | pd.Timestamp],
        source_name: str = "SYNTHETIC_CALENDAR",
    ) -> MarketCalendarAuthority:
        """임의의 날짜 목록으로부터 Market Calendar Authority 인스턴스를 생성한다 (테스트 전용)."""
        dt_idx = pd.to_datetime(list(dates))
        return cls(trading_dates=dt_idx, source_name=source_name)

    def is_trading_day(self, date: str | pd.Timestamp) -> bool:
        """해당 날짜가 KRX 시장 영업일인지 여부를 반환한다."""
        return pd.Timestamp(date).normalize() in self._trading_dates_set

    def get_actual_month_end(self, year: int, month: int) -> pd.Timestamp | None:
        """특정 (연도, 월)의 실제 KRX 시장 마지막 거래일을 반환한다."""
        return self._month_end_map.get((year, month))

    def is_completed_month(self, requested: str | pd.Timestamp) -> bool:
        """요청 일자(requested) 시점에 해당 월의 KRX 시장 월봉이 완전히 완성되었는지 판정한다.
        
        해당 월의 실제 마지막 거래일과 같거나 이후이면 True를 반환한다.
        """
        req_norm = pd.Timestamp(requested).normalize()
        actual_me = self.get_actual_month_end(req_norm.year, req_norm.month)
        if actual_me is None:
            raise MarketCalendarUnavailableError(
                f"No KRX trading days found for year={req_norm.year}, month={req_norm.month} "
                f"in calendar source '{self.source_name}'."
            )
        return req_norm >= actual_me

    def get_month_ends(self, requested_as_of: str | pd.Timestamp | None = None) -> list[pd.Timestamp]:
        """요청 시점까지의 실제 KRX 시장 월말 최종 거래일 목록을 반환한다."""
        sorted_mes = sorted(self._month_end_map.values())
        if requested_as_of is not None:
            req_norm = pd.Timestamp(requested_as_of).normalize()
            return [me for me in sorted_mes if me <= req_norm]
        return sorted_mes


# Module-level registry keyed by canonical path (isolated, not a single unkeyed global)
_KEYED_CALENDAR_CACHE: dict[str, MarketCalendarAuthority] = {}


def get_canonical_market_calendar(
    parquet_path: Path | str = DEFAULT_CALENDAR_PATH,
) -> MarketCalendarAuthority:
    """Canonical KRX Market Calendar Authority 인스턴스를 반환한다 (경로별 캐시)."""
    p_str = str(Path(parquet_path).resolve())
    if p_str not in _KEYED_CALENDAR_CACHE:
        _KEYED_CALENDAR_CACHE[p_str] = MarketCalendarAuthority.from_parquet(parquet_path)
    return _KEYED_CALENDAR_CACHE[p_str]


def clear_calendar_cache() -> None:
    """캐시된 캘린더 Authority 인스턴스를 초기화한다 (테스트 격리용)."""
    _KEYED_CALENDAR_CACHE.clear()


# Convenience functional API (delegates to canonical authority)
def is_completed_market_month(
    requested: str | pd.Timestamp,
    calendar: MarketCalendarAuthority | None = None,
) -> bool:
    """요청 일자 시점에 시장 월봉이 완성되었는지 판정한다."""
    cal = calendar or get_canonical_market_calendar()
    return cal.is_completed_month(requested)


def get_reference_market_month_ends(
    calendar: MarketCalendarAuthority | None = None,
    requested_as_of: str | pd.Timestamp | None = None,
) -> list[pd.Timestamp]:
    """요청 시점까지의 실제 KRX 시장 월말 거래일 목록을 반환한다."""
    cal = calendar or get_canonical_market_calendar()
    return cal.get_month_ends(requested_as_of)
