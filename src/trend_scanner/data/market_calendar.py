"""Canonical Derived KRX Exchange Trading Calendar & Completed Period Authority.

Provides official exchange-level trading dates and completed month-end dates based on
the canonical derived KRX trading calendar artifact (data/reference/krx_trading_calendar.parquet).
Zero reliance on individual stock price series (e.g. 005930) to prevent trading halt distortions.

Explicitly distinguishes between:
  1. max_observed_trading_date: latest observed KRX trading date in the artifact (e.g. 2026-08-14)
  2. last_completed_market_month: the latest month confirmed to be fully completed (e.g. 2026-07)
  3. completed_month_ends: immutable mapping of confirmed actual market month-end trading days.

Ensures terminal partial months (e.g. August 2026 when cutoff is 2026-08-14)
are strictly excluded from completed months, preventing Point-In-Time leakage.

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
from typing import Any, Sequence

import pandas as pd

DEFAULT_CALENDAR_PATH = Path("data/reference/krx_trading_calendar.parquet")


class MarketCalendarUnavailableError(RuntimeError):
    """Raised when KRX Market Calendar Authority is unavailable or invalid.
    
    Silent fallback to calendar month-end is strictly forbidden in PIT paths.
    """


@dataclass
class MarketCalendarAuthority:
    """KRX 시장 영업일 및 월말 판정을 담당하는 독립 캘린더 Authority."""

    trading_dates: pd.DatetimeIndex
    completed_month_ends: Sequence[pd.Timestamp] | None = None
    source_name: str = "CANONICAL_DERIVED_KRX_CALENDAR"
    metadata: dict[str, Any] = field(default_factory=dict)

    # Instance-level memoized cache (prevents cross-contamination across fixtures/sources)
    _completed_month_end_map: dict[tuple[int, int], pd.Timestamp] = field(default_factory=dict, init=False, repr=False)
    _trading_dates_set: set[pd.Timestamp] = field(default_factory=set, init=False, repr=False)
    _min_date: pd.Timestamp | None = field(default=None, init=False, repr=False)
    _max_observed_date: pd.Timestamp | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.trading_dates) > 0:
            norm_dates = pd.DatetimeIndex(self.trading_dates.normalize()).sort_values()
            self.trading_dates = norm_dates
            self._trading_dates_set = set(norm_dates)
            self._min_date = norm_dates[0]
            self._max_observed_date = norm_dates[-1]

            # Build (year, month) -> actual completed market month end map
            if self.completed_month_ends is not None:
                norm_cmes = pd.DatetimeIndex(pd.to_datetime(list(self.completed_month_ends)).normalize()).sort_values()
                self._completed_month_end_map = {
                    (int(d.year), int(d.month)): d for d in norm_cmes
                }
            elif "completed_month_ends" in self.metadata and self.metadata["completed_month_ends"]:
                norm_cmes = pd.DatetimeIndex(pd.to_datetime(self.metadata["completed_month_ends"]).normalize()).sort_values()
                self._completed_month_end_map = {
                    (int(d.year), int(d.month)): d for d in norm_cmes
                }
            elif "last_completed_market_month" in self.metadata and self.metadata["last_completed_market_month"]:
                # Derive completed month ends up to last_completed_market_month
                last_ym_str = str(self.metadata["last_completed_market_month"])
                last_y, last_m = int(last_ym_str.split("-")[0]), int(last_ym_str.split("-")[1])
                temp_df = pd.DataFrame({"dt": norm_dates}, index=norm_dates)
                monthly_groups = temp_df.groupby([temp_df.index.year, temp_df.index.month])
                self._completed_month_end_map = {
                    (int(year), int(month)): group.index.max().normalize()
                    for (year, month), group in monthly_groups
                    if (year < last_y) or (year == last_y and month <= last_m)
                }
            else:
                # If neither completed_month_ends nor metadata boundary is provided,
                # we require explicit completion authority to prevent partial month leakage.
                raise MarketCalendarUnavailableError(
                    f"MarketCalendarAuthority for '{self.source_name}' requires explicit "
                    f"completed_month_ends or 'last_completed_market_month' metadata."
                )
        else:
            self._trading_dates_set = set()
            self._completed_month_end_map = {}
            self._min_date = None
            self._max_observed_date = None

    @property
    def min_date(self) -> pd.Timestamp | None:
        return self._min_date

    @property
    def max_observed_trading_date(self) -> pd.Timestamp | None:
        return self._max_observed_date

    @classmethod
    def from_parquet(
        cls,
        parquet_path: Path | str = DEFAULT_CALENDAR_PATH,
    ) -> MarketCalendarAuthority:
        """Parquet 파일로부터 Canonical Market Calendar Authority를 로드하고 Invariant를 검증한다."""
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

        meta: dict[str, Any] = {}
        json_meta_path = p.with_suffix(".json")
        if json_meta_path.exists():
            try:
                meta = json.loads(json_meta_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise MarketCalendarUnavailableError(
                    f"Failed to read calendar metadata JSON at {json_meta_path}: {exc}"
                ) from exc

        # Extract completed_month_ends from parquet column or metadata
        completed_dates: list[pd.Timestamp] | None = None
        if "is_completed_month_end" in df.columns:
            completed_dates = list(df.loc[df["is_completed_month_end"] == True, "trading_date"])
        elif "completed_month_ends" in meta:
            completed_dates = [pd.Timestamp(d) for d in meta["completed_month_ends"]]

        trading_dates = pd.DatetimeIndex(df["trading_date"]).normalize()

        # Invariant Validations
        if not meta:
            raise MarketCalendarUnavailableError(f"Missing calendar metadata JSON at {json_meta_path}")

        min_d = trading_dates.min()
        max_d = trading_dates.max()
        if min_d > max_d:
            raise MarketCalendarUnavailableError(f"Calendar min_date {min_d} > max_date {max_d}")

        if completed_dates is not None and len(completed_dates) > 0:
            last_cme = completed_dates[-1]
            if last_cme > max_d:
                raise MarketCalendarUnavailableError(
                    f"last_completed_month_end {last_cme} > max_observed_trading_date {max_d}"
                )
            if last_cme not in set(trading_dates):
                raise MarketCalendarUnavailableError(
                    f"last_completed_month_end {last_cme} is not in trading_dates"
                )
            # Check strictly ascending
            for i in range(len(completed_dates) - 1):
                if completed_dates[i] >= completed_dates[i + 1]:
                    raise MarketCalendarUnavailableError("completed_month_ends is not strictly ascending")

        return cls(
            trading_dates=trading_dates,
            completed_month_ends=completed_dates,
            source_name=str(meta.get("calendar_source", p.name)),
            metadata=meta,
        )

    @classmethod
    def from_dates(
        cls,
        dates: Sequence[str | pd.Timestamp],
        completed_month_ends: Sequence[str | pd.Timestamp] | None = None,
        last_completed_month: str | None = None,
        source_name: str = "SYNTHETIC_CALENDAR",
    ) -> MarketCalendarAuthority:
        """임의의 날짜 목록으로부터 Market Calendar Authority 인스턴스를 생성한다 (테스트 전용)."""
        dt_idx = pd.to_datetime(list(dates)).normalize()
        meta: dict[str, Any] = {}
        if last_completed_month is not None:
            meta["last_completed_market_month"] = last_completed_month
        elif completed_month_ends is None and len(dt_idx) > 0:
            # Default for synthetic full calendar: assume all observed months are completed
            meta["last_completed_market_month"] = f"{dt_idx[-1].year:04d}-{dt_idx[-1].month:02d}"

        cmes = [pd.Timestamp(d).normalize() for d in completed_month_ends] if completed_month_ends is not None else None
        return cls(
            trading_dates=dt_idx,
            completed_month_ends=cmes,
            source_name=source_name,
            metadata=meta,
        )

    def is_trading_day(self, date: str | pd.Timestamp) -> bool:
        """해당 날짜가 KRX 시장 영업일인지 여부를 반환한다."""
        return pd.Timestamp(date).normalize() in self._trading_dates_set

    def get_actual_month_end(self, year: int, month: int) -> pd.Timestamp | None:
        """특정 (연도, 월)의 실제 완료된 KRX 시장 마지막 거래일을 반환한다.
        
        해당 월이 아직 진행 중이거나(terminal partial month) 미완료 상태이면 None을 반환한다.
        """
        return self._completed_month_end_map.get((year, month))

    def is_completed_month(self, requested: str | pd.Timestamp) -> bool:
        """요청 일자(requested) 시점에 해당 월의 KRX 시장 월봉이 완전히 완성되었는지 판정한다.
        
        해당 월이 완료 확정 목록에 있고, 요청 일자가 그 월의 실제 마지막 거래일과 같거나 이후이면 True를 반환한다.
        진행 중인 월(terminal partial month 등)은 항상 False를 반환한다.
        """
        req_norm = pd.Timestamp(requested).normalize()

        if self._max_observed_date is not None and req_norm > self._max_observed_date:
            raise MarketCalendarUnavailableError(
                f"Requested date {req_norm.strftime('%Y-%m-%d')} is beyond the calendar authority's "
                f"max observed trading date {self._max_observed_date.strftime('%Y-%m-%d')}."
            )

        actual_me = self.get_actual_month_end(req_norm.year, req_norm.month)
        if actual_me is None:
            # 해당 월이 아직 진행 중이거나 완료되지 않은 월임 (예: 2026-08-14)
            return False

        return req_norm >= actual_me

    def get_month_ends(self, requested_as_of: str | pd.Timestamp | None = None) -> list[pd.Timestamp]:
        """요청 시점까지의 실제 완료된 KRX 시장 월말 최종 거래일 목록을 반환한다."""
        sorted_mes = sorted(self._completed_month_end_map.values())
        if requested_as_of is not None:
            req_norm = pd.Timestamp(requested_as_of).normalize()
            return [me for me in sorted_mes if me <= req_norm]
        return sorted_mes


# Module-level registry keyed by canonical path (isolated, not a single unkeyed global)
_KEYED_CALENDAR_CACHE: dict[str, MarketCalendarAuthority] = {}


def get_canonical_market_calendar(
    parquet_path: Path | str = DEFAULT_CALENDAR_PATH,
) -> MarketCalendarAuthority:
    """Canonical Derived KRX Market Calendar Authority 인스턴스를 반환한다 (경로별 캐시)."""
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
