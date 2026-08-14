"""Pattern A Universe & Data Quality Models.

종목 Universe 정의, 자산 유형, 데이터 품질 상태, 및 감사 결과 데이터 구조를 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


class MarketType(str, Enum):
    """한국 거래소 시장 구분."""

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    KONEX = "KONEX"
    UNKNOWN = "UNKNOWN"


class AssetType(str, Enum):
    """자산 유형 구분."""

    COMMON = "COMMON"
    """일반 보통주 (Pattern A 기본 Universe 대상)."""

    PREFERRED = "PREFERRED"
    """우선주 (유동성/호가 구조 차이로 제외)."""

    SPAC = "SPAC"
    """기업인수목적회사 (일반 기업 성장 사이클과 상이하여 제외)."""

    REIT = "REIT"
    """부동산투자회사/리츠."""

    ETF = "ETF"
    """상장지수펀드."""

    ETN = "ETN"
    """상장지수증권."""

    OTHER = "OTHER"
    """기타 특수 자산."""

    UNKNOWN = "UNKNOWN"
    """식별 불가 자산 (자동으로 보통주로 간주하지 않음)."""


class QualityStatus(str, Enum):
    """종목 단위 최종 데이터 품질 상태."""

    OK = "OK"
    """모든 품질 및 준비도 기준을 충족하여 정상 평가 가능."""

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    """Pattern A 핵심 앵커(36개월 완성 월봉) 계산에 필요한 히스토리 부족 (신규 상장 등)."""

    STALE_DATA = "STALE_DATA"
    """최신 시장 거래일 대비 데이터가 지연됨."""

    MISSING_COLUMNS = "MISSING_COLUMNS"
    """필수 OHLCV 컬럼 누락."""

    MISSING_VALUES = "MISSING_VALUES"
    """핵심 가격/거래량에 결측치(NaN) 존재."""

    DUPLICATE_DATE = "DUPLICATE_DATE"
    """중복된 거래일 존재."""

    UNSORTED_DATE = "UNSORTED_DATE"
    """거래일 정렬 불일치."""

    INVALID_OHLC = "INVALID_OHLC"
    """OHLC 가격 관계(high < low 등) 위반 또는 음수 가격/거래량."""

    FUTURE_DATE = "FUTURE_DATE"
    """기준 시장일보다 미래 날짜 존재 (데이터 오염)."""

    FEATURE_NOT_READY = "FEATURE_NOT_READY"
    """FeatureRow 생성 실패 또는 required anchor 결측."""

    EVALUATOR_NOT_READY = "EVALUATOR_NOT_READY"
    """Score/Stage/Evaluator 실행 실패."""

    UNSUPPORTED_ASSET = "UNSUPPORTED_ASSET"
    """우선주/SPAC/ETF 등 Pattern A 대상 외 자산."""

    MISSING_CACHE = "MISSING_CACHE"
    """로컬 데이터 캐시 부재."""

    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    """기타 예외 발생."""


class FreshnessStatus(str, Enum):
    """최신 시장일 대비 데이터 신선도."""

    FRESH = "FRESH"
    """0~1 거래일 이내 최신 데이터."""

    STALE = "STALE"
    """2~5 거래일 지연."""

    VERY_STALE = "VERY_STALE"
    """6 거래일 이상 지연."""

    UNKNOWN = "UNKNOWN"
    """신선도 확인 불가 (캐시 부재 등)."""


@dataclass(frozen=True)
class UniverseSecurity:
    """Official KRX 종목 마스터 메타데이터."""

    ticker: str
    name: str
    market: MarketType
    metadata_source: str = "OFFICIAL_KRX"


@dataclass(frozen=True)
class TickerQualityRecord:
    """종목 단위 데이터 품질 및 평가 준비도 상세 레코드."""

    ticker: str
    name: str
    market: MarketType
    asset_type: AssetType
    metadata_source: str
    data_available: bool
    cache_present: bool
    first_date: str | None
    last_date: str | None
    rows: int
    history_days: int
    history_months: int
    required_history_sufficient: bool
    freshness_status: FreshnessStatus
    staleness_trading_days: int
    raw_data_ready: bool
    feature_ready: bool
    score_ready: bool
    stage_ready: bool
    evaluator_ready: bool
    included_in_pattern_a_universe: bool
    quality_status: QualityStatus
    quality_flags: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class UniverseQualitySummary:
    """Universe 전체 데이터 품질 감사 종합 요약."""

    generated_at: str
    reference_market_date: str
    reference_date_source: str
    min_history_months: int
    official_universe_count: int
    official_kospi_count: int
    official_kosdaq_count: int
    official_konex_count: int
    local_cache_file_count: int
    official_universe_cache_present_count: int
    orphan_cache_count: int
    cache_present_count: int
    cache_missing_count: int
    cache_coverage_pct: float
    common_stock_count: int
    preferred_stock_count: int
    spac_count: int
    reit_count: int
    etf_etn_count: int
    unknown_asset_count: int
    raw_data_ready_count: int
    feature_ready_count: int
    score_ready_count: int
    stage_ready_count: int
    evaluator_ready_count: int
    included_tickers: int
    excluded_tickers: int
    fresh_count: int
    stale_count: int
    very_stale_count: int
    insufficient_history_count: int
    missing_columns_count: int
    duplicate_date_count: int
    unsorted_date_count: int
    invalid_ohlc_count: int
    future_date_count: int
    extreme_return_count: int
    exception_count: int
    exclusion_reason_counts: dict[str, int] = field(default_factory=dict)
    history_distribution: dict[str, int] = field(default_factory=dict)
    freshness_distribution: dict[str, int] = field(default_factory=dict)
