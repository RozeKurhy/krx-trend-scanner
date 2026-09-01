"""Pattern A Full Universe Scanner Integration v0.1.

Official KRX KOSPI / KOSDAQ AssetType.COMMON Universe를 대상으로
Pattern A Score v0.2, Stage Classifier v0.1, Candidate State, Score Momentum v0.1,
Readiness 및 Data Quality Flags를 종목별 단일 Row로 통합하는 Orchestration 계층이다.

[핵심 설계 원칙]:
1. **Official COMMON Universe Contract**:
   - 오직 KRX KOSPI / KOSDAQ의 `AssetType.COMMON`(보통주)만을 스캔 대상으로 한다.
   - PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX는 평가 대상에서 엄격히 배제한다.
2. **Fail-Closed Universe & Row Count 보존**:
   - 캐시 누락(Missing Cache)이나 히스토리 부족(Short History) 종목도 Universe에서 삭제하지 않고,
     단일 Row를 유지하며 INSUFFICIENT_DATA 및 명확한 reason provenance로 fail closed 표현한다.
   - Official COMMON Universe Count == Scanner Output Row Count (1 ticker = 1 row).
3. **Frozen Component 직결 및 독립성 보장**:
   - Score v0.2, Stage v0.1, Evaluator v0.1, Score Momentum v0.1 결과를 변형 없이 그대로 기록한다.
   - 단일 종목당 로컬 캐시 Parquet 로드는 단 1회만 수행하여 효율성을 극대화한다.
4. **No Ranking / No Cutoff Policy**:
   - Ranking, Top N, Cutoff 필터링, Unified/Composite Score, BUY/SELL 해석을 일체 배제한다.
5. **Deterministic Ordering & Exception Isolation**:
   - 결과는 (MarketType, Ticker) 순으로 결정론적으로 정렬된다.
   - 단일 종목 계산 시 예외가 발생해도 전체 스캔을 중단시키지 않고 ERROR 상태로 격리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    PatternAEvaluationResult,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score_momentum import (
    PatternAScoreMomentumResult,
    compute_pattern_a_score_momentum,
)
from trend_scanner.filters.investability import (
    InvestabilityEvaluationResult,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.flow.foreign_flow import (
    FlowDataStatus,
    ForeignFlowFeatureResult,
    compute_foreign_flow_features,
)
from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthDataStatus,
    RelativeStrengthFeatureResult,
    compute_relative_strength_features,
)
from trend_scanner.relative_strength.cross_section import (
    CROSS_SECTION_COLUMNS,
    compute_market_rs_cross_section,
)
from trend_scanner.relative_strength.repository_adapter import (
    resolve_market_rs_repository_input,
)
from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.krx_universe import (
    get_latest_market_trading_date,
    load_krx_equity_universe,
)
from trend_scanner.universe.models import (
    AssetType,
    FreshnessStatus,
    MarketType,
    UniverseSecurity,
)
from trend_scanner.universe.quality_auditor import audit_ticker_quality
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_investability_audit import load_canonical_mcap_snapshot

logger = logging.getLogger(__name__)

# Building the Repository V2 raw partition index is intentionally a run-scoped
# operation.  Scanner calls made in one process (including test suites and
# batch report generation) reuse the same immutable index instead of allocating
# ~1GB for every invocation.  A caller may still inject its own repository for
# isolation or alternate stores.
_DEFAULT_MARKET_RS_REPOSITORIES: dict[tuple[str, str], MarketDataRepositoryV2] = {}


def _default_market_rs_repository(repo_root: Path) -> MarketDataRepositoryV2:
    key = (
        str((repo_root / "data/market/adjusted/stocks").resolve()),
        str((repo_root / "data/market/raw/krx_stocks/v01").resolve()),
    )
    repository = _DEFAULT_MARKET_RS_REPOSITORIES.get(key)
    if repository is None:
        repository = MarketDataRepositoryV2(
            AdjustedPriceStore(key[0]),
            KrxRawStockStore(key[1]),
        )
        _DEFAULT_MARKET_RS_REPOSITORIES[key] = repository
    return repository


def _relative_strength_row_updates(result: RelativeStrengthFeatureResult) -> dict[str, Any]:
    """Map a RelativeStrengthFeatureResult onto scanner row fields."""

    return {
        "market_rs_data_status": result.market_rs_data_status.value,
        "market_benchmark_name": result.market_benchmark_name,
        "market_benchmark_code": result.market_benchmark_code,
        "market_benchmark_last_observation_date": result.market_benchmark_last_observation_date,
        "stock_return_3m": result.stock_return_3m,
        "stock_return_6m": result.stock_return_6m,
        "stock_return_12m": result.stock_return_12m,
        "market_return_3m": result.market_return_3m,
        "market_return_6m": result.market_return_6m,
        "market_return_12m": result.market_return_12m,
        "market_rs_3m": result.market_rs_3m,
        "market_rs_6m": result.market_rs_6m,
        "market_rs_12m": result.market_rs_12m,
        "market_anchor_date_3m": result.market_anchor_date_3m,
        "market_anchor_date_6m": result.market_anchor_date_6m,
        "market_anchor_date_12m": result.market_anchor_date_12m,
        "sector_rs_data_status": result.sector_rs_data_status.value,
        "sector_name": result.sector_name,
        "sector_code": result.sector_code,
        "sector_benchmark_code": result.sector_benchmark_code,
        "sector_benchmark_last_observation_date": result.sector_benchmark_last_observation_date,
        "sector_return_3m": result.sector_return_3m,
        "sector_return_6m": result.sector_return_6m,
        "sector_return_12m": result.sector_return_12m,
        "sector_rs_3m": result.sector_rs_3m,
        "sector_rs_6m": result.sector_rs_6m,
        "sector_rs_12m": result.sector_rs_12m,
        "sector_anchor_date_3m": result.sector_anchor_date_3m,
        "sector_anchor_date_6m": result.sector_anchor_date_6m,
        "sector_anchor_date_12m": result.sector_anchor_date_12m,
    }


def _cross_section_value(value: Any) -> float | None:
    """Convert pandas missing values to the scanner's None representation."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class ScannerRowStatus(str, Enum):
    """Scanner Row 단위의 실행 및 가용성 상태."""

    OK = "OK"
    """Evaluator 및 주요 점수가 정상 산출됨."""

    PARTIAL = "PARTIAL"
    """Evaluator는 정상이나 일부 Momentum Horizon이 부족함."""

    UNAVAILABLE = "UNAVAILABLE"
    """캐시 부재 또는 36m 히스토리 부족으로 Pattern A 평가 불가 (정상 Fail-Closed)."""

    ERROR = "ERROR"
    """예상치 못한 예외 또는 스캐너 계산 장애."""


@dataclass(frozen=True)
class PatternAUniverseScanRow:
    """단일 보통주 종목에 대한 Pattern A 전체 측정 및 품질 통합 Row."""

    # 1. Identity
    ticker: str
    name: str
    market: MarketType
    asset_type: AssetType

    # 2. Data Provenance & Freshness
    requested_as_of: pd.Timestamp
    effective_as_of: pd.Timestamp | None
    cache_present: bool
    cache_first_date: pd.Timestamp | None
    cache_last_date: pd.Timestamp | None
    daily_rows: int
    completed_month_count: int
    freshness_status: FreshnessStatus
    staleness_trading_days: int
    quality_flags: tuple[str, ...]
    quality_reason_codes: tuple[str, ...]

    # 3. Layer Readiness
    raw_data_ready: bool
    feature_ready: bool
    score_ready: bool
    stage_ready: bool
    evaluator_ready: bool
    momentum_current_ready: bool
    momentum_1m_ready: bool
    momentum_3m_ready: bool
    momentum_6m_ready: bool

    # 4. Pattern A Evaluation (Score & Stage & Candidate State)
    pattern_a_score: float | None
    official_stage: PatternAStage | None
    candidate_state: PatternACandidateState
    evaluator_reason_codes: tuple[str, ...]

    # Diagnostic Sub-scores
    base_score: float | None = None
    transition_score: float | None = None
    core_score: float | None = None
    support_score: float | None = None
    confirmation_bonus: float | None = None
    balanced_core_score: float | None = None
    alignment_bonus: float | None = None
    progressed_penalty: float | None = None

    # 5. Score Momentum (1M / 3M / 6M Raw Deltas)
    score_delta_1m: float | None = None
    score_delta_3m: float | None = None
    score_delta_6m: float | None = None
    momentum_reason_codes_1m: tuple[str, ...] = ()
    momentum_reason_codes_3m: tuple[str, ...] = ()
    momentum_reason_codes_6m: tuple[str, ...] = ()

    # Diagnostic Momentum Deltas
    base_score_delta_1m: float | None = None
    base_score_delta_3m: float | None = None
    base_score_delta_6m: float | None = None
    transition_score_delta_1m: float | None = None
    transition_score_delta_3m: float | None = None
    transition_score_delta_6m: float | None = None

    # 6. Investability & Liquidity Layer (Phase 10C Downstream)
    market_cap: float | None = None
    market_cap_eok: float | None = None
    avg_trading_value_20d: float | None = None
    avg_trading_value_20d_eok: float | None = None
    avg_trading_value_60d: float | None = None
    avg_trading_value_60d_eok: float | None = None
    investability_status: InvestabilityStatus = InvestabilityStatus.DATA_UNAVAILABLE
    investability_reason: str = "REQUIRED_METRIC_UNAVAILABLE"
    investability_ready: bool = False
    market_cap_effective_date: str | None = None
    close_effective_date: str | None = None
    tv20_last_observation_date: str | None = None

    # 7. Foreign Flow Layer (Phase 11 Flow Confirmation Infrastructure)
    foreign_flow_data_status: str = "NOT_EVALUATED"
    foreign_flow_last_observation_date: str | None = None
    foreign_flow_first_observation_date: str | None = None
    foreign_flow_observation_count: int = 0
    foreign_net_buy_value_1d: float | None = None
    foreign_net_buy_value_5d: float | None = None
    foreign_net_buy_value_20d: float | None = None
    foreign_net_buy_value_60d: float | None = None
    foreign_flow_intensity_5d: float | None = None
    foreign_flow_intensity_20d: float | None = None
    foreign_flow_intensity_60d: float | None = None
    foreign_positive_days_5d: int | None = None
    foreign_positive_days_20d: int | None = None
    foreign_positive_days_60d: int | None = None
    foreign_positive_day_ratio_5d: float | None = None
    foreign_positive_day_ratio_20d: float | None = None
    foreign_positive_day_ratio_60d: float | None = None
    foreign_net_buy_avg_5d: float | None = None
    foreign_net_buy_avg_20d: float | None = None
    foreign_net_buy_avg_60d: float | None = None

    # 8. Relative Strength Layer (Phase 12 Relative Strength Infrastructure)
    market_rs_data_status: str = "NOT_EVALUATED"
    market_benchmark_name: str | None = None
    market_benchmark_code: str | None = None
    market_benchmark_last_observation_date: str | None = None
    market_rs_input_reason: str | None = None
    stock_return_3m: float | None = None
    stock_return_6m: float | None = None
    stock_return_12m: float | None = None
    market_return_3m: float | None = None
    market_return_6m: float | None = None
    market_return_12m: float | None = None
    market_rs_3m: float | None = None
    market_rs_6m: float | None = None
    market_rs_12m: float | None = None
    market_anchor_date_3m: str | None = None
    market_anchor_date_6m: str | None = None
    market_anchor_date_12m: str | None = None
    # Phase 12 completion layer: derived from the complete COMMON reference.
    market_rs_delta_3m_vs_6m: float | None = None
    market_rs_delta_6m_vs_12m: float | None = None
    market_rs_acceleration_3_6_12m: float | None = None
    all_market_rs_rank_3m: float | None = None
    all_market_rs_rank_6m: float | None = None
    all_market_rs_rank_12m: float | None = None
    all_market_rs_percentile_3m: float | None = None
    all_market_rs_percentile_6m: float | None = None
    all_market_rs_percentile_12m: float | None = None

    sector_rs_data_status: str = "NOT_EVALUATED"
    sector_name: str | None = None
    sector_code: str | None = None
    sector_benchmark_code: str | None = None
    sector_benchmark_last_observation_date: str | None = None
    sector_return_3m: float | None = None
    sector_return_6m: float | None = None
    sector_return_12m: float | None = None
    sector_rs_3m: float | None = None
    sector_rs_6m: float | None = None
    sector_rs_12m: float | None = None
    sector_anchor_date_3m: str | None = None
    sector_anchor_date_6m: str | None = None
    sector_anchor_date_12m: str | None = None

    # 9. Row Execution Status & Error Provenance
    row_status: ScannerRowStatus = ScannerRowStatus.UNAVAILABLE
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화 및 CSV 출력을 위한 딕셔너리 변환."""
        def _fmt(d: Any) -> str | None:
            if d is None or pd.isna(d):
                return None
            if isinstance(d, pd.Timestamp):
                return d.strftime("%Y-%m-%d")
            return str(d)

        return {
            "ticker": self.ticker,
            "name": self.name,
            "market": self.market.value,
            "asset_type": self.asset_type.value,
            "requested_as_of": _fmt(self.requested_as_of),
            "effective_as_of": _fmt(self.effective_as_of),
            "cache_present": self.cache_present,
            "cache_first_date": _fmt(self.cache_first_date),
            "cache_last_date": _fmt(self.cache_last_date),
            "daily_rows": self.daily_rows,
            "completed_month_count": self.completed_month_count,
            "freshness_status": self.freshness_status.value,
            "staleness_trading_days": self.staleness_trading_days,
            "raw_data_ready": self.raw_data_ready,
            "feature_ready": self.feature_ready,
            "score_ready": self.score_ready,
            "stage_ready": self.stage_ready,
            "evaluator_ready": self.evaluator_ready,
            "momentum_current_ready": self.momentum_current_ready,
            "momentum_1m_ready": self.momentum_1m_ready,
            "momentum_3m_ready": self.momentum_3m_ready,
            "momentum_6m_ready": self.momentum_6m_ready,
            "pattern_a_score": self.pattern_a_score,
            "official_stage": self.official_stage.value if self.official_stage else None,
            "candidate_state": self.candidate_state.value,
            "base_score": self.base_score,
            "transition_score": self.transition_score,
            "core_score": self.core_score,
            "support_score": self.support_score,
            "confirmation_bonus": self.confirmation_bonus,
            "balanced_core_score": self.balanced_core_score,
            "alignment_bonus": self.alignment_bonus,
            "progressed_penalty": self.progressed_penalty,
            "score_delta_1m": self.score_delta_1m,
            "score_delta_3m": self.score_delta_3m,
            "score_delta_6m": self.score_delta_6m,
            "base_score_delta_1m": self.base_score_delta_1m,
            "base_score_delta_3m": self.base_score_delta_3m,
            "base_score_delta_6m": self.base_score_delta_6m,
            "transition_score_delta_1m": self.transition_score_delta_1m,
            "transition_score_delta_3m": self.transition_score_delta_3m,
            "transition_score_delta_6m": self.transition_score_delta_6m,
            "market_cap": self.market_cap,
            "market_cap_eok": self.market_cap_eok,
            "avg_trading_value_20d": self.avg_trading_value_20d,
            "avg_trading_value_20d_eok": self.avg_trading_value_20d_eok,
            "avg_trading_value_60d": self.avg_trading_value_60d,
            "avg_trading_value_60d_eok": self.avg_trading_value_60d_eok,
            "investability_status": self.investability_status.value,
            "investability_reason": self.investability_reason,
            "investability_ready": self.investability_ready,
            "market_cap_effective_date": self.market_cap_effective_date,
            "close_effective_date": self.close_effective_date,
            "tv20_last_observation_date": self.tv20_last_observation_date,
            "foreign_flow_data_status": self.foreign_flow_data_status,
            "foreign_flow_last_observation_date": self.foreign_flow_last_observation_date,
            "foreign_flow_first_observation_date": self.foreign_flow_first_observation_date,
            "foreign_flow_observation_count": self.foreign_flow_observation_count,
            "foreign_net_buy_value_1d": self.foreign_net_buy_value_1d,
            "foreign_net_buy_value_5d": self.foreign_net_buy_value_5d,
            "foreign_net_buy_value_20d": self.foreign_net_buy_value_20d,
            "foreign_net_buy_value_60d": self.foreign_net_buy_value_60d,
            "foreign_flow_intensity_5d": self.foreign_flow_intensity_5d,
            "foreign_flow_intensity_20d": self.foreign_flow_intensity_20d,
            "foreign_flow_intensity_60d": self.foreign_flow_intensity_60d,
            "foreign_positive_days_5d": self.foreign_positive_days_5d,
            "foreign_positive_days_20d": self.foreign_positive_days_20d,
            "foreign_positive_days_60d": self.foreign_positive_days_60d,
            "foreign_positive_day_ratio_5d": self.foreign_positive_day_ratio_5d,
            "foreign_positive_day_ratio_20d": self.foreign_positive_day_ratio_20d,
            "foreign_positive_day_ratio_60d": self.foreign_positive_day_ratio_60d,
            "foreign_net_buy_avg_5d": self.foreign_net_buy_avg_5d,
            "foreign_net_buy_avg_20d": self.foreign_net_buy_avg_20d,
            "foreign_net_buy_avg_60d": self.foreign_net_buy_avg_60d,
            "market_rs_data_status": self.market_rs_data_status,
            "market_benchmark_name": self.market_benchmark_name,
            "market_benchmark_code": self.market_benchmark_code,
            "market_benchmark_last_observation_date": self.market_benchmark_last_observation_date,
            "market_rs_input_reason": self.market_rs_input_reason,
            "stock_return_3m": self.stock_return_3m,
            "stock_return_6m": self.stock_return_6m,
            "stock_return_12m": self.stock_return_12m,
            "market_return_3m": self.market_return_3m,
            "market_return_6m": self.market_return_6m,
            "market_return_12m": self.market_return_12m,
            "market_rs_3m": self.market_rs_3m,
            "market_rs_6m": self.market_rs_6m,
            "market_rs_12m": self.market_rs_12m,
            "market_anchor_date_3m": self.market_anchor_date_3m,
            "market_anchor_date_6m": self.market_anchor_date_6m,
            "market_anchor_date_12m": self.market_anchor_date_12m,
            "market_rs_delta_3m_vs_6m": self.market_rs_delta_3m_vs_6m,
            "market_rs_delta_6m_vs_12m": self.market_rs_delta_6m_vs_12m,
            "market_rs_acceleration_3_6_12m": self.market_rs_acceleration_3_6_12m,
            "all_market_rs_rank_3m": self.all_market_rs_rank_3m,
            "all_market_rs_rank_6m": self.all_market_rs_rank_6m,
            "all_market_rs_rank_12m": self.all_market_rs_rank_12m,
            "all_market_rs_percentile_3m": self.all_market_rs_percentile_3m,
            "all_market_rs_percentile_6m": self.all_market_rs_percentile_6m,
            "all_market_rs_percentile_12m": self.all_market_rs_percentile_12m,
            "sector_rs_data_status": self.sector_rs_data_status,
            "sector_name": self.sector_name,
            "sector_code": self.sector_code,
            "sector_benchmark_code": self.sector_benchmark_code,
            "sector_benchmark_last_observation_date": self.sector_benchmark_last_observation_date,
            "sector_return_3m": self.sector_return_3m,
            "sector_return_6m": self.sector_return_6m,
            "sector_return_12m": self.sector_return_12m,
            "sector_rs_3m": self.sector_rs_3m,
            "sector_rs_6m": self.sector_rs_6m,
            "sector_rs_12m": self.sector_rs_12m,
            "sector_anchor_date_3m": self.sector_anchor_date_3m,
            "sector_anchor_date_6m": self.sector_anchor_date_6m,
            "sector_anchor_date_12m": self.sector_anchor_date_12m,
            "row_status": self.row_status.value,
            "quality_flags": ";".join(self.quality_flags),
            "quality_reason_codes": ";".join(self.quality_reason_codes),
            "evaluator_reason_codes": ";".join(self.evaluator_reason_codes),
            "momentum_reason_codes_1m": ";".join(self.momentum_reason_codes_1m),
            "momentum_reason_codes_3m": ";".join(self.momentum_reason_codes_3m),
            "momentum_reason_codes_6m": ";".join(self.momentum_reason_codes_6m),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def _calc_stats(values: list[float]) -> dict[str, Any]:
    """수치형 시리즈에 대한 기초 통계량 산출."""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "q25": None,
            "median": None,
            "q75": None,
            "max": None,
        }
    arr = np.array(values, dtype=float)
    return {
        "count": int(len(arr)),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4) if len(arr) > 1 else 0.0,
        "min": round(float(np.min(arr)), 4),
        "q25": round(float(np.percentile(arr, 25)), 4),
        "median": round(float(np.median(arr)), 4),
        "q75": round(float(np.percentile(arr, 75)), 4),
        "max": round(float(np.max(arr)), 4),
    }


@dataclass(frozen=True)
class PatternAUniverseScanSummary:
    """Scanner 실행 결과 종합 통계 및 분포 Summary."""

    requested_as_of: str
    reference_market_date: str
    official_common_total: int
    scan_target_count: int
    rows_emitted: int

    # Counts
    cache_present_count: int
    cache_missing_count: int
    raw_ready_count: int
    feature_ready_count: int
    score_ready_count: int
    stage_ready_count: int
    evaluator_ready_count: int
    momentum_current_ready_count: int
    momentum_1m_ready_count: int
    momentum_3m_ready_count: int
    momentum_6m_ready_count: int
    scanner_error_count: int

    # Distributions
    stage_distribution: dict[str, int]
    candidate_state_distribution: dict[str, int]
    row_status_distribution: dict[str, int]
    investability_distribution: dict[str, int]

    # Universe Investability Counts
    investability_investable_count: int
    investability_filtered_market_cap_count: int
    investability_filtered_liquidity_count: int
    investability_data_unavailable_count: int

    # Numeric Distributions
    score_distribution: dict[str, Any]
    momentum_1m_distribution: dict[str, Any]
    momentum_3m_distribution: dict[str, Any]
    momentum_6m_distribution: dict[str, Any]

    # Candidate Downstream Filter Counts (Phase 10C Specification)
    candidate_raw_count: int = 0
    candidate_investable_count: int = 0
    candidate_filtered_market_cap_count: int = 0
    candidate_filtered_liquidity_count: int = 0
    candidate_data_unavailable_count: int = 0
    candidate_investability_distribution: dict[str, int] = field(default_factory=dict)

    # Foreign Flow Confirmation Counts (Phase 11 Specification)
    flow_ready_count: int = 0
    flow_partial_count: int = 0
    flow_data_unavailable_count: int = 0
    flow_not_evaluated_count: int = 0
    candidate_flow_ready_count: int = 0
    candidate_flow_partial_count: int = 0
    candidate_flow_data_unavailable_count: int = 0
    candidate_flow_distribution: dict[str, int] = field(default_factory=dict)

    # Relative Strength Confirmation Counts (Phase 12 Specification)
    market_rs_ready_count: int = 0
    market_rs_partial_count: int = 0
    market_rs_data_unavailable_count: int = 0
    market_rs_not_evaluated_count: int = 0
    candidate_market_rs_ready_count: int = 0
    candidate_market_rs_partial_count: int = 0
    candidate_market_rs_data_unavailable_count: int = 0
    candidate_market_rs_distribution: dict[str, int] = field(default_factory=dict)

    sector_rs_ready_count: int = 0
    sector_rs_partial_count: int = 0
    sector_rs_data_unavailable_count: int = 0
    sector_rs_not_evaluated_count: int = 0
    candidate_sector_rs_ready_count: int = 0
    candidate_sector_rs_partial_count: int = 0
    candidate_sector_rs_data_unavailable_count: int = 0
    candidate_sector_rs_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Summary 딕셔너리 직렬화."""
        return {
            "requested_as_of": self.requested_as_of,
            "reference_market_date": self.reference_market_date,
            "official_common_total": self.official_common_total,
            "scan_target_count": self.scan_target_count,
            "rows_emitted": self.rows_emitted,
            "cache_present_count": self.cache_present_count,
            "cache_missing_count": self.cache_missing_count,
            "raw_ready_count": self.raw_ready_count,
            "feature_ready_count": self.feature_ready_count,
            "score_ready_count": self.score_ready_count,
            "stage_ready_count": self.stage_ready_count,
            "evaluator_ready_count": self.evaluator_ready_count,
            "momentum_current_ready_count": self.momentum_current_ready_count,
            "momentum_1m_ready_count": self.momentum_1m_ready_count,
            "momentum_3m_ready_count": self.momentum_3m_ready_count,
            "momentum_6m_ready_count": self.momentum_6m_ready_count,
            "scanner_error_count": self.scanner_error_count,
            "stage_distribution": self.stage_distribution,
            "candidate_state_distribution": self.candidate_state_distribution,
            "row_status_distribution": self.row_status_distribution,
            "investability_distribution": self.investability_distribution,
            "investability_investable_count": self.investability_investable_count,
            "investability_filtered_market_cap_count": self.investability_filtered_market_cap_count,
            "investability_filtered_liquidity_count": self.investability_filtered_liquidity_count,
            "investability_data_unavailable_count": self.investability_data_unavailable_count,
            "candidate_raw_count": self.candidate_raw_count,
            "candidate_investable_count": self.candidate_investable_count,
            "candidate_filtered_market_cap_count": self.candidate_filtered_market_cap_count,
            "candidate_filtered_liquidity_count": self.candidate_filtered_liquidity_count,
            "candidate_data_unavailable_count": self.candidate_data_unavailable_count,
            "candidate_investability_distribution": self.candidate_investability_distribution,
            "flow_ready_count": self.flow_ready_count,
            "flow_partial_count": self.flow_partial_count,
            "flow_data_unavailable_count": self.flow_data_unavailable_count,
            "flow_not_evaluated_count": self.flow_not_evaluated_count,
            "candidate_flow_ready_count": self.candidate_flow_ready_count,
            "candidate_flow_partial_count": self.candidate_flow_partial_count,
            "candidate_flow_data_unavailable_count": self.candidate_flow_data_unavailable_count,
            "candidate_flow_distribution": self.candidate_flow_distribution,
            "market_rs_ready_count": self.market_rs_ready_count,
            "market_rs_partial_count": self.market_rs_partial_count,
            "market_rs_data_unavailable_count": self.market_rs_data_unavailable_count,
            "market_rs_not_evaluated_count": self.market_rs_not_evaluated_count,
            "candidate_market_rs_ready_count": self.candidate_market_rs_ready_count,
            "candidate_market_rs_partial_count": self.candidate_market_rs_partial_count,
            "candidate_market_rs_data_unavailable_count": self.candidate_market_rs_data_unavailable_count,
            "candidate_market_rs_distribution": self.candidate_market_rs_distribution,
            "sector_rs_ready_count": self.sector_rs_ready_count,
            "sector_rs_partial_count": self.sector_rs_partial_count,
            "sector_rs_data_unavailable_count": self.sector_rs_data_unavailable_count,
            "sector_rs_not_evaluated_count": self.sector_rs_not_evaluated_count,
            "candidate_sector_rs_ready_count": self.candidate_sector_rs_ready_count,
            "candidate_sector_rs_partial_count": self.candidate_sector_rs_partial_count,
            "candidate_sector_rs_data_unavailable_count": self.candidate_sector_rs_data_unavailable_count,
            "candidate_sector_rs_distribution": self.candidate_sector_rs_distribution,
            "score_distribution": self.score_distribution,
            "momentum_1m_distribution": self.momentum_1m_distribution,
            "momentum_3m_distribution": self.momentum_3m_distribution,
            "momentum_6m_distribution": self.momentum_6m_distribution,
        }


@dataclass(frozen=True)
class PatternAUniverseScanResult:
    """전체 유니버스 스캔 최종 결과 컨테이너."""

    requested_as_of: pd.Timestamp
    summary: PatternAUniverseScanSummary
    rows: tuple[PatternAUniverseScanRow, ...]

    def to_dataframe(self) -> pd.DataFrame:
        """스캔 결과를 pandas DataFrame으로 변환."""
        return pd.DataFrame([r.to_dict() for r in self.rows])

    def get_investable_candidates(self) -> list[PatternAUniverseScanRow]:
        """Pattern A Candidate 중 Investability Filter를 통과한 종목 추출 (Optional Filtered View)."""
        return [
            r for r in self.rows
            if r.candidate_state == PatternACandidateState.CANDIDATE
            and r.investability_status == InvestabilityStatus.INVESTABLE
        ]

    def to_csv(self, filepath: str | Path) -> Path:
        """스캔 결과를 CSV 파일로 저장."""
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        df.to_csv(out_path, index=False)
        return out_path

    def save_artifacts(
        self,
        output_dir: str | Path,
        prefix: str = "pattern_a_universe_scan",
    ) -> tuple[Path, Path]:
        """스캔 CSV 아티팩트와 JSON Summary 아티팩트를 동시에 저장."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = self.requested_as_of.strftime("%Y%m%d")

        csv_path = out_dir / f"{prefix}_{date_str}.csv"
        json_path = out_dir / f"{prefix}_{date_str}_summary.json"

        self.to_csv(csv_path)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.summary.to_dict(), f, indent=2, ensure_ascii=False)

        return csv_path, json_path


def scan_pattern_a_universe(
    cache: ParquetCache | Path | str,
    as_of: str | pd.Timestamp | None = None,
    universe_securities: list[UniverseSecurity] | list[dict[str, Any]] | None = None,
    reference_market_date: str | None = None,
    target_tickers: list[str] | set[str] | None = None,
    target_markets: list[MarketType | str] | set[MarketType | str] | None = None,
    limit: int | None = None,
    flow_df: pd.DataFrame | None = None,
    flow_data_path: Path | str | None = None,
    enrich_flow_for_candidates: bool = True,
    market_index_df: pd.DataFrame | None = None,
    market_index_path: Path | str | None = None,
    sector_index_df: pd.DataFrame | None = None,
    sector_index_path: Path | str | None = None,
    sector_mapping: dict[str, tuple[str, str]] | None = None,
    sector_mapping_path: Path | str | None = None,
    enrich_rs_for_candidates: bool = True,
    enrich_market_rs_cross_section: bool = False,
    market_rs_repository: MarketDataRepositoryV2 | None = None,
) -> PatternAUniverseScanResult:
    """Official KRX COMMON Universe를 대상으로 Pattern A 스캔을 수행한다.

    Args:
        cache: ParquetCache 인스턴스 또는 캐시 디렉토리 경로
        as_of: 평가 기준일 (생략 시 reference_market_date 또는 최신 영업일)
        universe_securities: 대상 유니버스 메타데이터 (생략 시 authoritative KRX universe 로드)
        reference_market_date: 신선도 판정 기준일 (생략 시 as_of 또는 최신 영업일)
        target_tickers: 특정 종목만 스캔할 경우 필터 (Smoke / Subset 테스트용)
        target_markets: 특정 시장만 스캔할 경우 필터 (KOSPI, KOSDAQ)
        limit: 최대 처리 종목 수 (Subset 개발용)
        flow_df: 외부에서 제공된 외국인 수급 DataFrame
        flow_data_path: 외국인 수급 데이터 파일 경로 (Parquet / CSV)
        enrich_flow_for_candidates: Candidate 종목 대상 Flow 피처 산출 여부
        market_index_df: 외부에서 제공된 대표 시장 지수 DataFrame
        market_index_path: 대표 시장 지수 데이터 파일 경로 (Parquet / CSV)
        sector_index_df: 외부에서 제공된 업종 지수 DataFrame
        sector_index_path: 업종 지수 데이터 파일 경로 (Parquet / CSV)
        sector_mapping: 종목별 업종 매핑 딕셔너리
        sector_mapping_path: 종목별 업종 매핑 파일 경로 (CSV)
        enrich_rs_for_candidates: Candidate 종목 대상 상대강도(RS) 피처 산출 여부
        enrich_market_rs_cross_section: 공식 COMMON 전체를 기준으로 Market RS
            improvement/rank/percentile을 계산해 모든 scanner row에 연결할지 여부.
            명시적으로 활성화한 Full COMMON 실행에서만 사용하며, 기존 기본값은 유지한다.
        market_rs_repository: 공유 Repository V2 인스턴스. Market RS가 활성화되면
            이 인스턴스만 사용하며, 생략 시 canonical local stores로 한 번 생성한다.

    Returns:
        PatternAUniverseScanResult: 통합 결과 객체
    """
    # 1. Cache 및 As-Of 결정
    parquet_cache = cache if isinstance(cache, ParquetCache) else ParquetCache(base_dir=cache)

    if as_of is None:
        if reference_market_date is not None:
            as_of_str = str(reference_market_date).strip()
        else:
            as_of_str = get_latest_market_trading_date()
    else:
        as_of_str = str(as_of).strip()

    req_as_of = pd.Timestamp(as_of_str)
    ref_market_date = (
        str(reference_market_date).strip() if reference_market_date else req_as_of.strftime("%Y-%m-%d")
    )

    # 2. Authoritative Universe 로딩 및 COMMON 종목 필터링
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    if universe_securities is None:
        req_clean = req_as_of.strftime("%Y%m%d")
        ref_clean = ref_market_date.replace("-", "")
        canonical_univ_csv = repo_root / "artifacts/patterns/pattern_a/production/investability" / f"pattern_a_investability_universe_{req_clean}.csv"
        if not canonical_univ_csv.exists():
            canonical_univ_csv = repo_root / "artifacts/patterns/pattern_a/production/investability" / f"pattern_a_investability_universe_{ref_clean}.csv"

        canonical_scan_csv = repo_root / "artifacts/patterns/pattern_a/production/scanner" / f"pattern_a_universe_scan_{req_clean}.csv"
        if not canonical_scan_csv.exists():
            canonical_scan_csv = repo_root / "artifacts/patterns/pattern_a/production/scanner" / f"pattern_a_universe_scan_{ref_clean}.csv"

        if canonical_univ_csv.exists():
            df_univ = pd.read_csv(canonical_univ_csv)
            raw_univ = [
                UniverseSecurity(
                    ticker=str(row["ticker"]).zfill(6),
                    name=str(row["name"]),
                    market=MarketType(str(row["market"]).upper()),
                    metadata_source="OFFICIAL_KRX",
                )
                for _, row in df_univ.iterrows()
            ]
        elif canonical_scan_csv.exists():
            df_univ = pd.read_csv(canonical_scan_csv)
            raw_univ = [
                UniverseSecurity(
                    ticker=str(row["ticker"]).zfill(6),
                    name=str(row["name"]),
                    market=MarketType(str(row["market"]).upper()),
                    metadata_source="OFFICIAL_KRX",
                )
                for _, row in df_univ.iterrows()
            ]
        else:
            raw_univ = load_krx_equity_universe(as_of=ref_market_date)
    else:
        raw_univ = universe_securities

    # Normalize securities and filter for AssetType.COMMON and KOSPI/KOSDAQ
    common_targets: list[tuple[str, str, MarketType]] = []
    target_ticker_set = set(target_tickers) if target_tickers is not None else None
    target_market_set: set[MarketType] | None = None
    if target_markets is not None:
        target_market_set = set()
        for m in target_markets:
            if isinstance(m, MarketType):
                target_market_set.add(m)
            else:
                try:
                    target_market_set.add(MarketType(str(m).upper()))
                except ValueError:
                    pass

    # 2.1 전체 Global Official COMMON 종목 목록 (official_common_total 계산용)
    all_common_targets: list[tuple[str, str, MarketType]] = []
    for item in raw_univ:
        if isinstance(item, UniverseSecurity):
            t = item.ticker
            n = item.name
            m = item.market
        else:
            t = str(item["ticker"]).strip().zfill(6)
            n = str(item.get("name", "")).strip()
            m_str = str(item.get("market", "UNKNOWN")).upper()
            try:
                m = MarketType(m_str)
            except ValueError:
                m = MarketType.UNKNOWN

        if m in (MarketType.KOSPI, MarketType.KOSDAQ):
            if classify_asset_type(t, n) == AssetType.COMMON:
                all_common_targets.append((t, n, m))

    all_common_targets.sort(key=lambda x: (x[2].value, x[0]))
    official_common_total = len(all_common_targets)

    # 2.2 Subset Filter 적용 (target_tickers, target_markets, limit)
    target_ticker_set = set(target_tickers) if target_tickers is not None else None
    target_market_set: set[MarketType] | None = None
    if target_markets is not None:
        target_market_set = set()
        for m in target_markets:
            if isinstance(m, MarketType):
                target_market_set.add(m)
            else:
                try:
                    target_market_set.add(MarketType(str(m).upper()))
                except ValueError:
                    pass

    scan_targets: list[tuple[str, str, MarketType]] = []
    for t, n, m in all_common_targets:
        if target_ticker_set is not None and t not in target_ticker_set:
            continue
        if target_market_set is not None and m not in target_market_set:
            continue
        scan_targets.append((t, n, m))

    if limit is not None and limit > 0:
        scan_targets = scan_targets[:limit]

    scan_target_count = len(scan_targets)

    # 3.0 Market Cap PIT Snapshot 로드 (반드시 requested as_of 기준)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    req_as_of_str = req_as_of.strftime("%Y-%m-%d")
    try:
        df_mcap_snap, _ = load_canonical_mcap_snapshot(repo_root=repo_root, as_of=req_as_of_str)
        mcap_dict = {
            str(row["ticker"]).strip().zfill(6): float(row["market_cap"])
            for _, row in df_mcap_snap.iterrows()
            if pd.notna(row.get("market_cap"))
        }
        mcap_effective_date = req_as_of_str
    except Exception as exc:
        logger.warning("Failed to load canonical market cap snapshot for %s: %s", req_as_of_str, exc)
        mcap_dict = {}
        mcap_effective_date = None

    # 3.0.1 Foreign Flow Data Cache 로드 (Phase 11 Exact Parity)
    flow_df_loaded = flow_df
    if flow_df_loaded is None and flow_data_path is not None:
        p = Path(flow_data_path)
        if p.exists():
            flow_df_loaded = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    elif flow_df_loaded is None:
        def_p = repo_root / "artifacts/patterns/pattern_a/production/flow/source" / f"foreign_flow_daily_{req_as_of.strftime('%Y%m%d')}.parquet"
        if def_p.exists():
            flow_df_loaded = pd.read_parquet(def_p)

    # 3.0.2 Relative Strength Data Cache 로드 (Phase 12)
    market_index_df_loaded = market_index_df
    try:
        if market_index_df_loaded is None and market_index_path is not None:
            p = Path(market_index_path)
            if p.exists():
                market_index_df_loaded = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        elif market_index_df_loaded is None:
            # Production Market RS benchmark authority is the verified
            # canonical INDEX_STORE family.  The historical relative-strength
            # artifact remains a legacy comparison input for parity evidence
            # only and must never be selected implicitly by the scanner.
            market_index_df_loaded = IndexStore(
                repo_root / "data/market/index/v01"
            ).load_family(
                MARKET_INDEX_FAMILY,
                end=req_as_of_str,
                index_codes=("1001", "2001"),
            )
    except Exception as exc:
        logger.warning("Failed loading market index source (%s): %s", market_index_path, exc)
        market_index_df_loaded = None

    sector_index_df_loaded = sector_index_df
    try:
        if sector_index_df_loaded is None and sector_index_path is not None:
            p = Path(sector_index_path)
            if p.exists():
                sector_index_df_loaded = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        elif sector_index_df_loaded is None:
            def_p = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source" / f"sector_index_daily_{req_as_of.strftime('%Y%m%d')}.parquet"
            if def_p.exists():
                sector_index_df_loaded = pd.read_parquet(def_p)
    except Exception as exc:
        logger.warning("Failed loading sector index source (%s): %s", sector_index_path, exc)
        sector_index_df_loaded = None

    sector_map_loaded: dict[str, tuple[str, str]] | None = None
    try:
        if sector_mapping is not None:
            valid_map = {}
            for k, v in sector_mapping.items():
                if isinstance(v, (tuple, list)) and len(v) >= 3:
                    sc, sn, eff = v[0], v[1], str(v[2]).strip()
                    if eff <= req_as_of_str:
                        valid_map[str(k).zfill(6)] = (str(sc), str(sn), eff)
                # Provenance-less 2-tuples are strictly rejected in production evaluation
            sector_map_loaded = valid_map if valid_map else None
        elif sector_mapping_path is not None:
            p = Path(sector_mapping_path)
            if p.exists():
                df_sm = pd.read_csv(p)
                df_sm["ticker"] = df_sm["ticker"].astype(str).str.zfill(6)
                if "effective_date" in df_sm.columns:
                    # Strict PIT enforcement: only use mappings with effective_date <= requested_as_of
                    df_sm_pit = df_sm[df_sm["effective_date"].astype(str) <= req_as_of_str]
                    if not df_sm_pit.empty:
                        sector_map_loaded = {
                            row["ticker"]: (str(row["sector_code"]), str(row["sector_name"]), str(row["effective_date"]))
                            for _, row in df_sm_pit.iterrows()
                        }
                # Missing effective_date column results in sector_map_loaded = None (Fail-Closed)
        else:
            def_p = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source" / f"sector_mapping_{req_as_of.strftime('%Y%m%d')}.csv"
            if def_p.exists():
                df_sm = pd.read_csv(def_p)
                df_sm["ticker"] = df_sm["ticker"].astype(str).str.zfill(6)
                if "effective_date" in df_sm.columns:
                    df_sm_pit = df_sm[df_sm["effective_date"].astype(str) <= req_as_of_str]
                    if not df_sm_pit.empty:
                        sector_map_loaded = {
                            row["ticker"]: (str(row["sector_code"]), str(row["sector_name"]), str(row["effective_date"]))
                            for _, row in df_sm_pit.iterrows()
                        }
    except Exception as exc:
        logger.warning("Failed loading sector mapping source (%s): %s", sector_mapping_path, exc)
        sector_map_loaded = None

    if enrich_market_rs_cross_section:
        if target_tickers is not None or target_markets is not None or limit is not None:
            raise ValueError(
                "enrich_market_rs_cross_section requires an unfiltered Full COMMON scan "
                "so percentiles cannot be recomputed from a subset"
            )
        if market_index_df_loaded is None or market_index_df_loaded.empty:
            raise ValueError(
                "enrich_market_rs_cross_section requires the local market index reference"
            )

    # Market RS has one and only one production stock-input authority.  Build
    # the repository once per scan and never fall back to ``ParquetCache`` for
    # the RS calculation.  Pattern A itself continues to use the legacy cache
    # until its separately scoped migration phase.
    rs_requested = bool(enrich_market_rs_cross_section or enrich_rs_for_candidates)
    if (
        rs_requested
        and market_rs_repository is None
        and market_index_df_loaded is not None
        and not market_index_df_loaded.empty
    ):
        market_rs_repository = _default_market_rs_repository(repo_root)

    # 3. Ticker별 순차 평가 (One Cache Load -> One daily_as_of Slice -> Shared Context)
    rows: list[PatternAUniverseScanRow] = []

    for ticker, name, market in scan_targets:
        try:
            # 3.1 1회 단일 캐시 로드 및 물리적 캐시 메타데이터
            raw_daily = parquet_cache.load(ticker)
            has_raw_cache = raw_daily is not None and not raw_daily.empty
            cache_first_raw = raw_daily.index.min() if has_raw_cache else None
            cache_last_raw = raw_daily.index.max() if has_raw_cache else None
            raw_rows_count = len(raw_daily) if has_raw_cache else 0

            # 3.2 Single Temporal Context 생성 (Lookahead 배제 & FUTURE_DATE 방지)
            if has_raw_cache and raw_daily is not None:
                daily_as_of = raw_daily.loc[raw_daily.index <= req_as_of]
            else:
                daily_as_of = pd.DataFrame()

            # 3.3 Data Quality & Freshness 감사 (daily_as_of 컨텍스트 사용)
            quality_record = audit_ticker_quality(
                ticker=ticker,
                name=name,
                market=market,
                daily=daily_as_of if not daily_as_of.empty else None,
                reference_market_date=ref_market_date,
            )

            cache_present = quality_record.cache_present
            freshness = quality_record.freshness_status
            staleness_days = quality_record.staleness_trading_days
            q_flags = quality_record.quality_flags
            q_reasons = quality_record.exclusion_reasons
            completed_months = quality_record.history_months

            raw_ready = quality_record.raw_data_ready
            feature_ready = quality_record.feature_ready
            score_ready = quality_record.score_ready
            stage_ready = quality_record.stage_ready
            evaluator_ready = quality_record.evaluator_ready

            # 3.3.1 Downstream Investability Evaluation (PIT requested as_of)
            mcap_val = mcap_dict.get(ticker)
            inv_eval: InvestabilityEvaluationResult = evaluate_investability(
                ticker=ticker,
                as_of=req_as_of,
                daily=daily_as_of if (has_raw_cache and not daily_as_of.empty) else None,
                market_cap=mcap_val,
                market_cap_effective_date=mcap_effective_date if mcap_val is not None else None,
            )

            # 3.4 Missing Cache Fail-Closed 처리
            if not cache_present or daily_as_of.empty:
                row = PatternAUniverseScanRow(
                    ticker=ticker,
                    name=name,
                    market=market,
                    asset_type=AssetType.COMMON,
                    requested_as_of=req_as_of,
                    effective_as_of=None,
                    cache_present=has_raw_cache,
                    cache_first_date=cache_first_raw,
                    cache_last_date=cache_last_raw,
                    daily_rows=raw_rows_count,
                    completed_month_count=0,
                    freshness_status=freshness,
                    staleness_trading_days=staleness_days,
                    quality_flags=q_flags,
                    quality_reason_codes=q_reasons,
                    raw_data_ready=False,
                    feature_ready=False,
                    score_ready=False,
                    stage_ready=False,
                    evaluator_ready=False,
                    momentum_current_ready=False,
                    momentum_1m_ready=False,
                    momentum_3m_ready=False,
                    momentum_6m_ready=False,
                    pattern_a_score=None,
                    official_stage=None,
                    candidate_state=PatternACandidateState.INSUFFICIENT_DATA,
                    evaluator_reason_codes=("CACHE_MISSING",),
                    score_delta_1m=None,
                    score_delta_3m=None,
                    score_delta_6m=None,
                    momentum_reason_codes_1m=("CACHE_MISSING",),
                    momentum_reason_codes_3m=("CACHE_MISSING",),
                    momentum_reason_codes_6m=("CACHE_MISSING",),
                    market_cap=inv_eval.market_cap,
                    market_cap_eok=inv_eval.market_cap_eok,
                    avg_trading_value_20d=inv_eval.avg_trading_value_20d,
                    avg_trading_value_20d_eok=inv_eval.avg_trading_value_20d_eok,
                    avg_trading_value_60d=inv_eval.avg_trading_value_60d,
                    avg_trading_value_60d_eok=inv_eval.avg_trading_value_60d_eok,
                    investability_status=inv_eval.status,
                    investability_reason=inv_eval.reason,
                    investability_ready=inv_eval.data_ready,
                    market_cap_effective_date=inv_eval.market_cap_effective_date,
                    close_effective_date=inv_eval.close_effective_date,
                    tv20_last_observation_date=inv_eval.tv20_last_observation_date,
                    row_status=ScannerRowStatus.UNAVAILABLE,
                )
                if enrich_market_rs_cross_section:
                    market_code = "1001" if market == MarketType.KOSPI else "2001" if market == MarketType.KOSDAQ else None
                    repository_input = resolve_market_rs_repository_input(
                        market_rs_repository,
                        ticker=ticker,
                        as_of=req_as_of_str,
                        market_code=market_code,
                        market_index_df=market_index_df_loaded,
                    )
                    unavailable_rs = compute_relative_strength_features(
                        ticker=ticker,
                        as_of=req_as_of_str,
                        stock_df=repository_input.stock_df,
                        market_index_df=market_index_df_loaded,
                        market=market,
                        sector_index_df=sector_index_df_loaded,
                        sector_mapping=sector_map_loaded,
                    )
                    row = replace(row, **_relative_strength_row_updates(unavailable_rs))
                    row = replace(row, market_rs_input_reason=repository_input.reason)
                rows.append(row)
                continue

            # 3.5 Single Snapshot 구축 (HistoricalSnapshot 생성 및 Frozen Component 직결)
            snapshot: HistoricalSnapshot = build_historical_snapshot(
                ticker=ticker,
                name=name,
                daily=daily_as_of,
                snapshot_date=req_as_of,
                include_incomplete_periods=False,
            )

            eval_res: PatternAEvaluationResult = evaluate_pattern_a(snapshot)

            pattern_score = eval_res.score
            official_stage = eval_res.lifecycle_stage
            cand_state = eval_res.candidate_state
            eval_reasons = eval_res.evaluator_reason_codes

            sub_base = eval_res.score_result.base_score
            sub_trans = eval_res.score_result.transition_score
            sub_core = eval_res.score_result.core_score
            sub_supp = eval_res.score_result.support_score
            sub_conf = eval_res.score_result.confirmation_bonus
            sub_bal = eval_res.score_result.balanced_core_score
            sub_align = eval_res.score_result.alignment_bonus
            sub_prog = eval_res.score_result.progressed_penalty

            # 3.6 Score Momentum 실행 및 Current Observation 기반 Readiness 산출
            momentum_res: PatternAScoreMomentumResult = compute_pattern_a_score_momentum(
                ticker=ticker,
                name=name,
                daily=daily_as_of,
                as_of=req_as_of,
            )

            current_obs = next(
                (
                    obs
                    for obs in momentum_res.observations
                    if momentum_res.momentum_anchor is not None
                    and obs.anchor_date == momentum_res.momentum_anchor
                ),
                None,
            )
            mom_curr_ready = current_obs is not None and current_obs.score is not None

            mom_1m_ready = momentum_res.horizon_1m.ready
            mom_3m_ready = momentum_res.horizon_3m.ready
            mom_6m_ready = momentum_res.horizon_6m.ready

            score_d_1m = momentum_res.horizon_1m.score_delta
            score_d_3m = momentum_res.horizon_3m.score_delta
            score_d_6m = momentum_res.horizon_6m.score_delta

            mom_reasons_1m = momentum_res.horizon_1m.reason_codes
            mom_reasons_3m = momentum_res.horizon_3m.reason_codes
            mom_reasons_6m = momentum_res.horizon_6m.reason_codes

            base_d_1m = momentum_res.horizon_1m.base_score_delta
            base_d_3m = momentum_res.horizon_3m.base_score_delta
            base_d_6m = momentum_res.horizon_6m.base_score_delta
            trans_d_1m = momentum_res.horizon_1m.transition_score_delta
            trans_d_3m = momentum_res.horizon_3m.transition_score_delta
            trans_d_6m = momentum_res.horizon_6m.transition_score_delta

            # 3.6.1 Downstream Foreign Flow Confirmation Feature (Phase 11)
            market_rs_input_reason: str | None = None
            if (
                cand_state == PatternACandidateState.CANDIDATE
                and enrich_flow_for_candidates
                and flow_df_loaded is not None
                and not flow_df_loaded.empty
            ):
                flow_res: ForeignFlowFeatureResult = compute_foreign_flow_features(
                    ticker=ticker,
                    as_of=req_as_of_str,
                    flow_df=flow_df_loaded,
                    price_df=daily_as_of if (has_raw_cache and not daily_as_of.empty) else None,
                )
            else:
                flow_res = ForeignFlowFeatureResult(
                    ticker=ticker,
                    as_of=req_as_of_str,
                    data_status=FlowDataStatus.NOT_EVALUATED,
                    foreign_flow_last_observation_date=None,
                    foreign_flow_first_observation_date=None,
                    foreign_flow_observation_count=0,
                    foreign_net_buy_value_1d=None,
                    foreign_net_buy_value_5d=None,
                    foreign_net_buy_value_20d=None,
                    foreign_net_buy_value_60d=None,
                    foreign_flow_intensity_5d=None,
                    foreign_flow_intensity_20d=None,
                    foreign_flow_intensity_60d=None,
                    foreign_positive_days_5d=None,
                    foreign_positive_days_20d=None,
                    foreign_positive_days_60d=None,
                    foreign_positive_day_ratio_5d=None,
                    foreign_positive_day_ratio_20d=None,
                    foreign_positive_day_ratio_60d=None,
                    foreign_net_buy_avg_5d=None,
                    foreign_net_buy_avg_20d=None,
                    foreign_net_buy_avg_60d=None,
                )

            # 3.6.2 Downstream Relative Strength Confirmation Feature (Phase 12)
            if (
                (
                    enrich_market_rs_cross_section
                    or (cand_state == PatternACandidateState.CANDIDATE and enrich_rs_for_candidates)
                )
                and market_index_df_loaded is not None
                and not market_index_df_loaded.empty
            ):
                market_code = "1001" if market == MarketType.KOSPI else "2001" if market == MarketType.KOSDAQ else None
                repository_input = resolve_market_rs_repository_input(
                    market_rs_repository,
                    ticker=ticker,
                    as_of=req_as_of_str,
                    market_code=market_code,
                    market_index_df=market_index_df_loaded,
                )
                market_rs_input_reason = repository_input.reason
                rs_res: RelativeStrengthFeatureResult = compute_relative_strength_features(
                    ticker=ticker,
                    as_of=req_as_of_str,
                    stock_df=repository_input.stock_df,
                    market_index_df=market_index_df_loaded,
                    market=market,
                    sector_index_df=sector_index_df_loaded,
                    sector_mapping=sector_map_loaded,
                )
            else:
                rs_res = RelativeStrengthFeatureResult(
                    ticker=ticker,
                    as_of=req_as_of_str,
                    market_rs_data_status=RelativeStrengthDataStatus.NOT_EVALUATED,
                    market_benchmark_name=None,
                    market_benchmark_code=None,
                    market_benchmark_last_observation_date=None,
                    stock_return_3m=None,
                    stock_return_6m=None,
                    stock_return_12m=None,
                    market_return_3m=None,
                    market_return_6m=None,
                    market_return_12m=None,
                    market_rs_3m=None,
                    market_rs_6m=None,
                    market_rs_12m=None,
                    market_anchor_date_3m=None,
                    market_anchor_date_6m=None,
                    market_anchor_date_12m=None,
                    sector_rs_data_status=RelativeStrengthDataStatus.NOT_EVALUATED,
                    sector_name=None,
                    sector_code=None,
                    sector_benchmark_code=None,
                    sector_benchmark_last_observation_date=None,
                    sector_return_3m=None,
                    sector_return_6m=None,
                    sector_return_12m=None,
                    sector_rs_3m=None,
                    sector_rs_6m=None,
                    sector_rs_12m=None,
                    sector_anchor_date_3m=None,
                    sector_anchor_date_6m=None,
                    sector_anchor_date_12m=None,
                )

            # 3.7 Row Status 결정
            if pattern_score is not None and official_stage is not None:
                if mom_1m_ready and mom_3m_ready and mom_6m_ready:
                    row_status = ScannerRowStatus.OK
                else:
                    row_status = ScannerRowStatus.PARTIAL
            else:
                row_status = ScannerRowStatus.UNAVAILABLE

            row = PatternAUniverseScanRow(
                ticker=ticker,
                name=name,
                market=market,
                asset_type=AssetType.COMMON,
                requested_as_of=req_as_of,
                effective_as_of=snapshot.effective_as_of,
                cache_present=has_raw_cache,
                cache_first_date=cache_first_raw,
                cache_last_date=cache_last_raw,
                daily_rows=raw_rows_count,
                completed_month_count=completed_months,
                freshness_status=freshness,
                staleness_trading_days=staleness_days,
                quality_flags=q_flags,
                quality_reason_codes=q_reasons,
                raw_data_ready=raw_ready,
                feature_ready=feature_ready,
                score_ready=score_ready,
                stage_ready=stage_ready,
                evaluator_ready=evaluator_ready,
                momentum_current_ready=mom_curr_ready,
                momentum_1m_ready=mom_1m_ready,
                momentum_3m_ready=mom_3m_ready,
                momentum_6m_ready=mom_6m_ready,
                pattern_a_score=pattern_score,
                official_stage=official_stage,
                candidate_state=cand_state,
                evaluator_reason_codes=eval_reasons,
                base_score=sub_base,
                transition_score=sub_trans,
                core_score=sub_core,
                support_score=sub_supp,
                confirmation_bonus=sub_conf,
                balanced_core_score=sub_bal,
                alignment_bonus=sub_align,
                progressed_penalty=sub_prog,
                score_delta_1m=score_d_1m,
                score_delta_3m=score_d_3m,
                score_delta_6m=score_d_6m,
                momentum_reason_codes_1m=mom_reasons_1m,
                momentum_reason_codes_3m=mom_reasons_3m,
                momentum_reason_codes_6m=mom_reasons_6m,
                base_score_delta_1m=base_d_1m,
                base_score_delta_3m=base_d_3m,
                base_score_delta_6m=base_d_6m,
                transition_score_delta_1m=trans_d_1m,
                transition_score_delta_3m=trans_d_3m,
                transition_score_delta_6m=trans_d_6m,
                market_cap=inv_eval.market_cap,
                market_cap_eok=inv_eval.market_cap_eok,
                avg_trading_value_20d=inv_eval.avg_trading_value_20d,
                avg_trading_value_20d_eok=inv_eval.avg_trading_value_20d_eok,
                avg_trading_value_60d=inv_eval.avg_trading_value_60d,
                avg_trading_value_60d_eok=inv_eval.avg_trading_value_60d_eok,
                investability_status=inv_eval.status,
                investability_reason=inv_eval.reason,
                investability_ready=inv_eval.data_ready,
                market_cap_effective_date=inv_eval.market_cap_effective_date,
                close_effective_date=inv_eval.close_effective_date,
                tv20_last_observation_date=inv_eval.tv20_last_observation_date,
                foreign_flow_data_status=flow_res.data_status.value,
                foreign_flow_last_observation_date=flow_res.foreign_flow_last_observation_date,
                foreign_flow_first_observation_date=flow_res.foreign_flow_first_observation_date,
                foreign_flow_observation_count=flow_res.foreign_flow_observation_count,
                foreign_net_buy_value_1d=flow_res.foreign_net_buy_value_1d,
                foreign_net_buy_value_5d=flow_res.foreign_net_buy_value_5d,
                foreign_net_buy_value_20d=flow_res.foreign_net_buy_value_20d,
                foreign_net_buy_value_60d=flow_res.foreign_net_buy_value_60d,
                foreign_flow_intensity_5d=flow_res.foreign_flow_intensity_5d,
                foreign_flow_intensity_20d=flow_res.foreign_flow_intensity_20d,
                foreign_flow_intensity_60d=flow_res.foreign_flow_intensity_60d,
                foreign_positive_days_5d=flow_res.foreign_positive_days_5d,
                foreign_positive_days_20d=flow_res.foreign_positive_days_20d,
                foreign_positive_days_60d=flow_res.foreign_positive_days_60d,
                foreign_positive_day_ratio_5d=flow_res.foreign_positive_day_ratio_5d,
                foreign_positive_day_ratio_20d=flow_res.foreign_positive_day_ratio_20d,
                foreign_positive_day_ratio_60d=flow_res.foreign_positive_day_ratio_60d,
                foreign_net_buy_avg_5d=flow_res.foreign_net_buy_avg_5d,
                foreign_net_buy_avg_20d=flow_res.foreign_net_buy_avg_20d,
                foreign_net_buy_avg_60d=flow_res.foreign_net_buy_avg_60d,
                market_rs_data_status=rs_res.market_rs_data_status.value,
                market_benchmark_name=rs_res.market_benchmark_name,
                market_benchmark_code=rs_res.market_benchmark_code,
                market_benchmark_last_observation_date=rs_res.market_benchmark_last_observation_date,
                market_rs_input_reason=market_rs_input_reason,
                stock_return_3m=rs_res.stock_return_3m,
                stock_return_6m=rs_res.stock_return_6m,
                stock_return_12m=rs_res.stock_return_12m,
                market_return_3m=rs_res.market_return_3m,
                market_return_6m=rs_res.market_return_6m,
                market_return_12m=rs_res.market_return_12m,
                market_rs_3m=rs_res.market_rs_3m,
                market_rs_6m=rs_res.market_rs_6m,
                market_rs_12m=rs_res.market_rs_12m,
                market_anchor_date_3m=rs_res.market_anchor_date_3m,
                market_anchor_date_6m=rs_res.market_anchor_date_6m,
                market_anchor_date_12m=rs_res.market_anchor_date_12m,
                sector_rs_data_status=rs_res.sector_rs_data_status.value,
                sector_name=rs_res.sector_name,
                sector_code=rs_res.sector_code,
                sector_benchmark_code=rs_res.sector_benchmark_code,
                sector_benchmark_last_observation_date=rs_res.sector_benchmark_last_observation_date,
                sector_return_3m=rs_res.sector_return_3m,
                sector_return_6m=rs_res.sector_return_6m,
                sector_return_12m=rs_res.sector_return_12m,
                sector_rs_3m=rs_res.sector_rs_3m,
                sector_rs_6m=rs_res.sector_rs_6m,
                sector_rs_12m=rs_res.sector_rs_12m,
                sector_anchor_date_3m=rs_res.sector_anchor_date_3m,
                sector_anchor_date_6m=rs_res.sector_anchor_date_6m,
                sector_anchor_date_12m=rs_res.sector_anchor_date_12m,
                row_status=row_status,
            )
            rows.append(row)

        except Exception as exc:
            logger.exception("Scanner error on ticker %s (%s): %s", ticker, name, exc)
            row = PatternAUniverseScanRow(
                ticker=ticker,
                name=name,
                market=market,
                asset_type=AssetType.COMMON,
                requested_as_of=req_as_of,
                effective_as_of=None,
                cache_present=False,
                cache_first_date=None,
                cache_last_date=None,
                daily_rows=0,
                completed_month_count=0,
                freshness_status=FreshnessStatus.UNKNOWN,
                staleness_trading_days=-1,
                quality_flags=(f"EXCEPTION_{type(exc).__name__}",),
                quality_reason_codes=("SCANNER_EXCEPTION",),
                raw_data_ready=False,
                feature_ready=False,
                score_ready=False,
                stage_ready=False,
                evaluator_ready=False,
                momentum_current_ready=False,
                momentum_1m_ready=False,
                momentum_3m_ready=False,
                momentum_6m_ready=False,
                pattern_a_score=None,
                official_stage=None,
                candidate_state=PatternACandidateState.INSUFFICIENT_DATA,
                evaluator_reason_codes=(f"ERROR_{type(exc).__name__}",),
                score_delta_1m=None,
                score_delta_3m=None,
                score_delta_6m=None,
                momentum_reason_codes_1m=(f"ERROR_{type(exc).__name__}",),
                momentum_reason_codes_3m=(f"ERROR_{type(exc).__name__}",),
                momentum_reason_codes_6m=(f"ERROR_{type(exc).__name__}",),
                market_cap=None,
                market_cap_eok=None,
                avg_trading_value_20d=None,
                avg_trading_value_20d_eok=None,
                avg_trading_value_60d=None,
                avg_trading_value_60d_eok=None,
                investability_status=InvestabilityStatus.DATA_UNAVAILABLE,
                investability_reason="SCANNER_EXCEPTION",
                investability_ready=False,
                market_cap_effective_date=None,
                close_effective_date=None,
                tv20_last_observation_date=None,
                row_status=ScannerRowStatus.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            rows.append(row)

    # 3.8 Optional operational Phase 12 enrichment. The reference is built once
    # from every row in the unfiltered COMMON scan, then looked up by ticker.
    # Candidate/investable subsets are never used to recompute a percentile.
    if enrich_market_rs_cross_section:
        reference = compute_market_rs_cross_section(
            pd.DataFrame([row.to_dict() for row in rows])
        )
        reference_by_ticker = reference.drop_duplicates("ticker").set_index("ticker")
        if len(reference_by_ticker) != len(rows):
            raise ValueError("Duplicate or missing ticker in operational Market RS reference")
        enriched_rows: list[PatternAUniverseScanRow] = []
        for row in rows:
            if row.ticker not in reference_by_ticker.index:
                raise ValueError(f"Operational Market RS reference missing ticker: {row.ticker}")
            reference_row = reference_by_ticker.loc[row.ticker]
            cross_section_updates = {
                column: _cross_section_value(reference_row[column])
                for column in CROSS_SECTION_COLUMNS
            }
            enriched_rows.append(replace(row, **cross_section_updates))
        rows = enriched_rows

    # 4. 종합 통계 및 분포 산출
    cache_present_cnt = sum(1 for r in rows if r.cache_present)
    cache_missing_cnt = sum(1 for r in rows if not r.cache_present)
    raw_ready_cnt = sum(1 for r in rows if r.raw_data_ready)
    feat_ready_cnt = sum(1 for r in rows if r.feature_ready)
    score_ready_cnt = sum(1 for r in rows if r.score_ready)
    stage_ready_cnt = sum(1 for r in rows if r.stage_ready)
    eval_ready_cnt = sum(1 for r in rows if r.evaluator_ready)
    mom_curr_cnt = sum(1 for r in rows if r.momentum_current_ready)
    mom_1m_cnt = sum(1 for r in rows if r.momentum_1m_ready)
    mom_3m_cnt = sum(1 for r in rows if r.momentum_3m_ready)
    mom_6m_cnt = sum(1 for r in rows if r.momentum_6m_ready)
    err_cnt = sum(1 for r in rows if r.row_status == ScannerRowStatus.ERROR)

    stage_dist: dict[str, int] = {
        stage.value: sum(1 for r in rows if r.official_stage == stage)
        for stage in PatternAStage
    }
    stage_dist["UNAVAILABLE"] = sum(1 for r in rows if r.official_stage is None)

    cand_dist: dict[str, int] = {
        state.value: sum(1 for r in rows if r.candidate_state == state)
        for state in PatternACandidateState
    }

    status_dist: dict[str, int] = {
        status.value: sum(1 for r in rows if r.row_status == status)
        for status in ScannerRowStatus
    }

    # Universe Investability Distribution
    inv_dist: dict[str, int] = {
        inv_status.value: sum(1 for r in rows if r.investability_status == inv_status)
        for inv_status in InvestabilityStatus
    }

    inv_investable_cnt = inv_dist.get(InvestabilityStatus.INVESTABLE.value, 0)
    inv_mcap_cnt = inv_dist.get(InvestabilityStatus.FILTERED_MARKET_CAP.value, 0)
    inv_liq_cnt = inv_dist.get(InvestabilityStatus.FILTERED_LIQUIDITY.value, 0)
    inv_unavail_cnt = inv_dist.get(InvestabilityStatus.DATA_UNAVAILABLE.value, 0)

    # Candidate Downstream Filter Breakdown (Phase 10C Specification)
    candidate_rows = [r for r in rows if r.candidate_state == PatternACandidateState.CANDIDATE]
    cand_raw_cnt = len(candidate_rows)
    cand_inv_dist: dict[str, int] = {
        inv_status.value: sum(1 for r in candidate_rows if r.investability_status == inv_status)
        for inv_status in InvestabilityStatus
    }
    cand_investable_cnt = cand_inv_dist.get(InvestabilityStatus.INVESTABLE.value, 0)
    cand_mcap_cnt = cand_inv_dist.get(InvestabilityStatus.FILTERED_MARKET_CAP.value, 0)
    cand_liq_cnt = cand_inv_dist.get(InvestabilityStatus.FILTERED_LIQUIDITY.value, 0)
    cand_unavail_cnt = cand_inv_dist.get(InvestabilityStatus.DATA_UNAVAILABLE.value, 0)

    valid_scores = [r.pattern_a_score for r in rows if r.pattern_a_score is not None]
    score_dist = _calc_stats(valid_scores)

    valid_1m = [r.score_delta_1m for r in rows if r.score_delta_1m is not None]
    mom_1m_dist = _calc_stats(valid_1m)

    valid_3m = [r.score_delta_3m for r in rows if r.score_delta_3m is not None]
    mom_3m_dist = _calc_stats(valid_3m)

    valid_6m = [r.score_delta_6m for r in rows if r.score_delta_6m is not None]
    mom_6m_dist = _calc_stats(valid_6m)

    # Foreign Flow Distribution & Counts (Phase 11 Specification)
    flow_ready_cnt = sum(1 for r in rows if r.foreign_flow_data_status == FlowDataStatus.READY.value)
    flow_partial_cnt = sum(1 for r in rows if r.foreign_flow_data_status == FlowDataStatus.PARTIAL.value)
    flow_unavail_cnt = sum(1 for r in rows if r.foreign_flow_data_status == FlowDataStatus.DATA_UNAVAILABLE.value)
    flow_not_eval_cnt = sum(1 for r in rows if r.foreign_flow_data_status == FlowDataStatus.NOT_EVALUATED.value)

    cand_flow_dist: dict[str, int] = {
        status.value: sum(1 for r in candidate_rows if r.foreign_flow_data_status == status.value)
        for status in FlowDataStatus
    }
    cand_flow_ready_cnt = cand_flow_dist.get(FlowDataStatus.READY.value, 0)
    cand_flow_partial_cnt = cand_flow_dist.get(FlowDataStatus.PARTIAL.value, 0)
    cand_flow_unavail_cnt = cand_flow_dist.get(FlowDataStatus.DATA_UNAVAILABLE.value, 0)

    # Relative Strength Distribution & Counts (Phase 12 Specification)
    mkt_rs_ready_cnt = sum(1 for r in rows if r.market_rs_data_status == RelativeStrengthDataStatus.READY.value)
    mkt_rs_partial_cnt = sum(1 for r in rows if r.market_rs_data_status == RelativeStrengthDataStatus.PARTIAL.value)
    mkt_rs_unavail_cnt = sum(1 for r in rows if r.market_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE.value)
    mkt_rs_not_eval_cnt = sum(1 for r in rows if r.market_rs_data_status == RelativeStrengthDataStatus.NOT_EVALUATED.value)

    cand_mkt_rs_dist: dict[str, int] = {
        status.value: sum(1 for r in candidate_rows if r.market_rs_data_status == status.value)
        for status in RelativeStrengthDataStatus
    }
    cand_mkt_rs_ready_cnt = cand_mkt_rs_dist.get(RelativeStrengthDataStatus.READY.value, 0)
    cand_mkt_rs_partial_cnt = cand_mkt_rs_dist.get(RelativeStrengthDataStatus.PARTIAL.value, 0)
    cand_mkt_rs_unavail_cnt = cand_mkt_rs_dist.get(RelativeStrengthDataStatus.DATA_UNAVAILABLE.value, 0)

    sec_rs_ready_cnt = sum(1 for r in rows if r.sector_rs_data_status == RelativeStrengthDataStatus.READY.value)
    sec_rs_partial_cnt = sum(1 for r in rows if r.sector_rs_data_status == RelativeStrengthDataStatus.PARTIAL.value)
    sec_rs_unavail_cnt = sum(1 for r in rows if r.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE.value)
    sec_rs_not_eval_cnt = sum(1 for r in rows if r.sector_rs_data_status == RelativeStrengthDataStatus.NOT_EVALUATED.value)

    cand_sec_rs_dist: dict[str, int] = {
        status.value: sum(1 for r in candidate_rows if r.sector_rs_data_status == status.value)
        for status in RelativeStrengthDataStatus
    }
    cand_sec_rs_ready_cnt = cand_sec_rs_dist.get(RelativeStrengthDataStatus.READY.value, 0)
    cand_sec_rs_partial_cnt = cand_sec_rs_dist.get(RelativeStrengthDataStatus.PARTIAL.value, 0)
    cand_sec_rs_unavail_cnt = cand_sec_rs_dist.get(RelativeStrengthDataStatus.DATA_UNAVAILABLE.value, 0)

    summary = PatternAUniverseScanSummary(
        requested_as_of=req_as_of.strftime("%Y-%m-%d"),
        reference_market_date=ref_market_date,
        official_common_total=official_common_total,
        scan_target_count=scan_target_count,
        rows_emitted=len(rows),
        cache_present_count=cache_present_cnt,
        cache_missing_count=cache_missing_cnt,
        raw_ready_count=raw_ready_cnt,
        feature_ready_count=feat_ready_cnt,
        score_ready_count=score_ready_cnt,
        stage_ready_count=stage_ready_cnt,
        evaluator_ready_count=eval_ready_cnt,
        momentum_current_ready_count=mom_curr_cnt,
        momentum_1m_ready_count=mom_1m_cnt,
        momentum_3m_ready_count=mom_3m_cnt,
        momentum_6m_ready_count=mom_6m_cnt,
        scanner_error_count=err_cnt,
        stage_distribution=stage_dist,
        candidate_state_distribution=cand_dist,
        row_status_distribution=status_dist,
        investability_distribution=inv_dist,
        investability_investable_count=inv_investable_cnt,
        investability_filtered_market_cap_count=inv_mcap_cnt,
        investability_filtered_liquidity_count=inv_liq_cnt,
        investability_data_unavailable_count=inv_unavail_cnt,
        candidate_raw_count=cand_raw_cnt,
        candidate_investable_count=cand_investable_cnt,
        candidate_filtered_market_cap_count=cand_mcap_cnt,
        candidate_filtered_liquidity_count=cand_liq_cnt,
        candidate_data_unavailable_count=cand_unavail_cnt,
        candidate_investability_distribution=cand_inv_dist,
        flow_ready_count=flow_ready_cnt,
        flow_partial_count=flow_partial_cnt,
        flow_data_unavailable_count=flow_unavail_cnt,
        flow_not_evaluated_count=flow_not_eval_cnt,
        candidate_flow_ready_count=cand_flow_ready_cnt,
        candidate_flow_partial_count=cand_flow_partial_cnt,
        candidate_flow_data_unavailable_count=cand_flow_unavail_cnt,
        candidate_flow_distribution=cand_flow_dist,
        market_rs_ready_count=mkt_rs_ready_cnt,
        market_rs_partial_count=mkt_rs_partial_cnt,
        market_rs_data_unavailable_count=mkt_rs_unavail_cnt,
        market_rs_not_evaluated_count=mkt_rs_not_eval_cnt,
        candidate_market_rs_ready_count=cand_mkt_rs_ready_cnt,
        candidate_market_rs_partial_count=cand_mkt_rs_partial_cnt,
        candidate_market_rs_data_unavailable_count=cand_mkt_rs_unavail_cnt,
        candidate_market_rs_distribution=cand_mkt_rs_dist,
        sector_rs_ready_count=sec_rs_ready_cnt,
        sector_rs_partial_count=sec_rs_partial_cnt,
        sector_rs_data_unavailable_count=sec_rs_unavail_cnt,
        sector_rs_not_evaluated_count=sec_rs_not_eval_cnt,
        candidate_sector_rs_ready_count=cand_sec_rs_ready_cnt,
        candidate_sector_rs_partial_count=cand_sec_rs_partial_cnt,
        candidate_sector_rs_data_unavailable_count=cand_sec_rs_unavail_cnt,
        candidate_sector_rs_distribution=cand_sec_rs_dist,
        score_distribution=score_dist,
        momentum_1m_distribution=mom_1m_dist,
        momentum_3m_distribution=mom_3m_dist,
        momentum_6m_distribution=mom_6m_dist,
    )

    return PatternAUniverseScanResult(
        requested_as_of=req_as_of,
        summary=summary,
        rows=tuple(rows),
    )
