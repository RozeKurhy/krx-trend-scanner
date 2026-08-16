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

from dataclasses import dataclass
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
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

    # 7. Row Execution Status & Error Provenance
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

    # Counts
    investability_investable_count: int
    investability_filtered_market_cap_count: int
    investability_filtered_liquidity_count: int
    investability_data_unavailable_count: int

    # Numeric Distributions
    score_distribution: dict[str, Any]
    momentum_1m_distribution: dict[str, Any]
    momentum_3m_distribution: dict[str, Any]
    momentum_6m_distribution: dict[str, Any]

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
    if universe_securities is None:
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

    # 2. Authoritative Universe 로딩 및 COMMON 종목 추출
    if universe_securities is None:
        raw_univ = load_krx_equity_universe(as_of=ref_market_date)
    else:
        raw_univ = universe_securities

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

    # 3.0 Market Cap PIT Snapshot 로드 (1회 로드)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        df_mcap_snap, _ = load_canonical_mcap_snapshot(repo_root=repo_root, as_of=ref_market_date)
        mcap_dict = {
            str(row["ticker"]).strip().zfill(6): float(row["market_cap"])
            for _, row in df_mcap_snap.iterrows()
            if pd.notna(row.get("market_cap"))
        }
    except Exception as exc:
        logger.warning("Failed to load canonical market cap snapshot for %s: %s", ref_market_date, exc)
        mcap_dict = {}

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
            completed_months = quality_record.history_months
            freshness = quality_record.freshness_status
            staleness_days = quality_record.staleness_trading_days
            q_flags = quality_record.quality_flags
            q_reasons = quality_record.exclusion_reasons

            raw_ready = quality_record.raw_data_ready
            feature_ready = quality_record.feature_ready
            score_ready = quality_record.score_ready
            stage_ready = quality_record.stage_ready
            evaluator_ready = quality_record.evaluator_ready

            # 3.3.1 Downstream Investability Evaluation
            mcap_val = mcap_dict.get(ticker)
            inv_eval: InvestabilityEvaluationResult = evaluate_investability(
                ticker=ticker,
                as_of=req_as_of,
                daily=daily_as_of if (has_raw_cache and not daily_as_of.empty) else None,
                market_cap=mcap_val,
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
                    freshness_status=FreshnessStatus.UNKNOWN,
                    staleness_trading_days=-1,
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
                    row_status=ScannerRowStatus.UNAVAILABLE,
                )
                rows.append(row)
                continue

            # 3.5 Historical Snapshot & Evaluator 실행 (Completed Periods Only)
            snapshot = build_historical_snapshot(
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

            # 진단용 서브스코어 추출
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
                row_status=ScannerRowStatus.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            rows.append(row)

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

    inv_dist: dict[str, int] = {
        inv_status.value: sum(1 for r in rows if r.investability_status == inv_status)
        for inv_status in InvestabilityStatus
    }

    inv_investable_cnt = inv_dist.get(InvestabilityStatus.INVESTABLE.value, 0)
    inv_mcap_cnt = inv_dist.get(InvestabilityStatus.FILTERED_MARKET_CAP.value, 0)
    inv_liq_cnt = inv_dist.get(InvestabilityStatus.FILTERED_LIQUIDITY.value, 0)
    inv_unavail_cnt = inv_dist.get(InvestabilityStatus.DATA_UNAVAILABLE.value, 0)

    valid_scores = [r.pattern_a_score for r in rows if r.pattern_a_score is not None]
    score_dist = _calc_stats(valid_scores)

    valid_1m = [r.score_delta_1m for r in rows if r.score_delta_1m is not None]
    mom_1m_dist = _calc_stats(valid_1m)

    valid_3m = [r.score_delta_3m for r in rows if r.score_delta_3m is not None]
    mom_3m_dist = _calc_stats(valid_3m)

    valid_6m = [r.score_delta_6m for r in rows if r.score_delta_6m is not None]
    mom_6m_dist = _calc_stats(valid_6m)

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
