"""Reference Market Calendar & Completed Period Authority for KRX.

Provides canonical market trading dates and month-end dates based on
the reference market stock (005930 - 삼성전자).
Ensures unified completed-monthly and completed-weekly period semantics across:
  - Historical Snapshot (build_historical_snapshot)
  - Pattern A FAST Evaluator (evaluate_pattern_a_fast)
  - Stock Report (generate_stock_report)
  - Strategy Finalization & Scanner
"""

from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from typing import Mapping

import pandas as pd

from trend_scanner.data.cache import ParquetCache

logger = logging.getLogger(__name__)

REFERENCE_TICKER = "005930"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data/raw/stocks"

_CACHED_MONTH_END_MAP: dict[tuple[int, int], pd.Timestamp] | None = None
_CACHED_MARKET_DATES: pd.DatetimeIndex | None = None


def get_reference_market_trading_days(cache: ParquetCache | None = None) -> pd.DatetimeIndex:
    """KRX 기준 종목(005930)의 전체 실제 영업일 목록을 반환한다."""
    global _CACHED_MARKET_DATES
    if _CACHED_MARKET_DATES is not None:
        return _CACHED_MARKET_DATES

    c = cache or ParquetCache(base_dir=DEFAULT_CACHE_DIR)
    ref_daily = c.load(REFERENCE_TICKER)
    if ref_daily is not None and not ref_daily.empty:
        _CACHED_MARKET_DATES = pd.DatetimeIndex(ref_daily.sort_index().index.normalize())
        return _CACHED_MARKET_DATES
    return pd.DatetimeIndex([])


def get_reference_market_month_end_map(cache: ParquetCache | None = None) -> dict[tuple[int, int], pd.Timestamp]:
    """(연도, 월) -> 실제 KRX 시장 월말 최종 거래일 매핑 딕셔너리를 반환한다."""
    global _CACHED_MONTH_END_MAP
    if _CACHED_MONTH_END_MAP is not None:
        return _CACHED_MONTH_END_MAP

    c = cache or ParquetCache(base_dir=DEFAULT_CACHE_DIR)
    ref_daily = c.load(REFERENCE_TICKER)
    if ref_daily is not None and not ref_daily.empty:
        ref_daily = ref_daily.sort_index()
        monthly_groups = ref_daily.groupby([ref_daily.index.year, ref_daily.index.month])
        _CACHED_MONTH_END_MAP = {
            (int(year), int(month)): group.index.max().normalize()
            for (year, month), group in monthly_groups
        }
        return _CACHED_MONTH_END_MAP
    return {}


def get_reference_market_month_ends(
    cache: ParquetCache | None = None,
    requested_as_of: pd.Timestamp | None = None,
) -> list[pd.Timestamp]:
    """요청 시점까지의 실제 KRX 시장 월말 최종 거래일 목록을 반환한다."""
    m_map = get_reference_market_month_end_map(cache)
    sorted_mes = sorted(m_map.values())
    if requested_as_of is not None:
        req_norm = requested_as_of.normalize()
        return [me for me in sorted_mes if me <= req_norm]
    return sorted_mes


def get_actual_market_month_end(
    year: int,
    month: int,
    cache: ParquetCache | None = None,
) -> pd.Timestamp | None:
    """특정 (연도, 월)의 실제 KRX 마지막 거래일을 반환한다."""
    m_map = get_reference_market_month_end_map(cache)
    return m_map.get((year, month))


def is_completed_market_month(
    requested: pd.Timestamp,
    cache: ParquetCache | None = None,
) -> bool:
    """요청 일자(requested) 시점에 해당 월의 KRX 시장 월봉이 완전히 완성되었는지 판정한다.
    
    해당 월의 실제 마지막 거래일과 같거나 이후이면 True를 반환한다.
    만약 기준 캘린더가 없는 경우(단위 테스트 등) calendar month end로 fallback한다.
    """
    req_norm = requested.normalize()
    actual_me = get_actual_market_month_end(req_norm.year, req_norm.month, cache)
    if actual_me is not None:
        return req_norm >= actual_me
    # Fallback to calendar month end when reference cache is not present
    cal_me = req_norm + pd.offsets.MonthEnd(0)
    return req_norm >= cal_me.normalize()
