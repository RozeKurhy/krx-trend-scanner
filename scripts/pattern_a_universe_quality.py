"""Pattern A Universe Data Quality Audit Runner.

공인 KRX 종목 마스터(KOSPI, KOSDAQ)를 authoritative source로 로딩하여
전체 Universe Data Quality 감사를 수행하고 `data/processed/pattern_a_universe_quality.csv`를 생성한다.

실행:
    python scripts/pattern_a_universe_quality.py
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from trend_scanner.universe import (
    AssetType,
    MarketType,
    QualityStatus,
    audit_universe_quality,
    get_latest_market_trading_date,
    load_krx_equity_universe,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "pattern_a_universe_quality.csv"


def main() -> None:
    print("=" * 70)
    print("Pattern A Official KRX Universe & Data Quality Audit v0.1 실행")
    print("=" * 70)

    # 1. Official Reference Market Date 획득
    official_ref_date = get_latest_market_trading_date()
    print(f"공식 시장 기준일 (Official Reference Market Date): {official_ref_date}")

    # 2. Official KRX KOSPI/KOSDAQ 종목 마스터 로딩
    print("공인 KRX KOSPI 및 KOSDAQ 종목 마스터 조회 중...")
    securities = load_krx_equity_universe(as_of=official_ref_date)
    print(f"공식 Universe 로드 완료: 총 {len(securities)}개 종목 (KOSPI + KOSDAQ)")

    # 3. Universe Data Quality 감사 수행
    print(f"데이터 품질 감사 진행 중 (로컬 캐시 경로: {CACHE_DIR})...")
    records, summary = audit_universe_quality(
        ticker_metadata=securities,
        cache_dir=CACHE_DIR,
        reference_market_date=official_ref_date,
        min_history_months=36,
    )

    # 4. CSV 저장
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ticker",
                "name",
                "market",
                "asset_type",
                "metadata_source",
                "data_available",
                "cache_present",
                "first_date",
                "last_date",
                "rows",
                "history_days",
                "history_months",
                "required_history_sufficient",
                "freshness_status",
                "staleness_trading_days",
                "raw_data_ready",
                "feature_ready",
                "score_ready",
                "stage_ready",
                "evaluator_ready",
                "included_in_pattern_a_universe",
                "quality_status",
                "quality_flags",
                "exclusion_reasons",
                "error_type",
                "error_message",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    r.ticker,
                    r.name,
                    r.market.value,
                    r.asset_type.value,
                    r.metadata_source,
                    r.data_available,
                    r.cache_present,
                    r.first_date or "",
                    r.last_date or "",
                    r.rows,
                    r.history_days,
                    r.history_months,
                    r.required_history_sufficient,
                    r.freshness_status.value,
                    r.staleness_trading_days,
                    r.raw_data_ready,
                    r.feature_ready,
                    r.score_ready,
                    r.stage_ready,
                    r.evaluator_ready,
                    r.included_in_pattern_a_universe,
                    r.quality_status.value,
                    ";".join(r.quality_flags),
                    ";".join(r.exclusion_reasons),
                    r.error_type or "",
                    r.error_message or "",
                ]
            )

    print(f"\nCSV 저장 완료: {OUTPUT_CSV} ({len(records)} rows)")

    # 동적 비율 계산 헬퍼
    def _pct(num: int, den: int) -> str:
        if den == 0:
            return "0.0%"
        return f"{num / den * 100.0:.1f}%"

    cp = summary.cache_present_count

    # 5. 콘솔 종합 보고서 출력
    print("\n" + "=" * 70)
    print("Official KRX Universe & Data Quality Audit Summary")
    print("=" * 70)
    print(f"생성 일시 (generated_at)               : {summary.generated_at}")
    print(f"공식 시장 기준일 (reference_market_date) : {summary.reference_market_date}")
    print(f"기준일 출처 (reference_date_source)     : {summary.reference_date_source}")
    print(f"최소 히스토리 기준 (min_months)          : {summary.min_history_months} completed monthly bars")
    print("-" * 70)
    print("1. Official Universe 마스터 현황:")
    print(f"  - 총 종목 수 (Official Universe Total) : {summary.official_universe_count:,}개")
    print(f"  - KOSPI                               : {summary.official_kospi_count:,}개")
    print(f"  - KOSDAQ                              : {summary.official_kosdaq_count:,}개")
    print(f"  - KONEX (제외)                        : {summary.official_konex_count}개")
    print("-" * 70)
    print("2. 자산 유형 분포 (Asset Types):")
    print(f"  - 보통주 (COMMON)                      : {summary.common_stock_count:,}개")
    print(f"  - 우선주 (PREFERRED)                   : {summary.preferred_stock_count:,}개")
    print(f"  - SPAC                                 : {summary.spac_count:,}개")
    print(f"  - REIT                                 : {summary.reit_count:,}개")
    print(f"  - ETF / ETN                            : {summary.etf_etn_count:,}개")
    print(f"  - UNKNOWN Asset                        : {summary.unknown_asset_count:,}개")
    print("-" * 70)
    print("3. 로컬 캐시 스코프 및 커버리지 (Cache Scope & Coverage):")
    print(f"  - 로컬 캐시 파일 수 (Local Cache Files): {summary.local_cache_file_count}개")
    print(f"  - 공식 Universe 교집합 캐시 (Intersect): {summary.official_universe_cache_present_count}개")
    print(f"  - Orphan 캐시 (과거/상폐 등 Master 밖): {summary.orphan_cache_count}개")
    print(f"  - 로컬 캐시 부재 (Missing Cache)       : {summary.cache_missing_count:,}개")
    print(f"  - 캐시 커버리지 (Coverage %)           : {summary.cache_coverage_pct:.2f}%")
    print("-" * 70)
    print("4. 보유 캐시 데이터 품질 감사 (Cached Dataset Quality):")
    print(f"  - Raw Data Ready                       : {summary.raw_data_ready_count} / {cp} ({_pct(summary.raw_data_ready_count, cp)})")
    print(f"  - Feature Ready                        : {summary.feature_ready_count} / {cp} ({_pct(summary.feature_ready_count, cp)})")
    print(f"  - Score Ready                          : {summary.score_ready_count} / {cp} ({_pct(summary.score_ready_count, cp)})")
    print(f"  - Stage Ready                          : {summary.stage_ready_count} / {cp} ({_pct(summary.stage_ready_count, cp)})")
    print(f"  - Evaluator Ready                      : {summary.evaluator_ready_count} / {cp} ({_pct(summary.evaluator_ready_count, cp)})")
    print(f"  - Missing Columns                      : {summary.missing_columns_count}건")
    print(f"  - Duplicate Dates                      : {summary.duplicate_date_count}건")
    print(f"  - Unsorted Dates                       : {summary.unsorted_date_count}건")
    print(f"  - Invalid OHLC                         : {summary.invalid_ohlc_count}건")
    print(f"  - Future Dates                         : {summary.future_date_count}건")
    print(f"  - Structural Exceptions                : {summary.exception_count}건")
    print("-" * 70)
    print(f"5. 절대 시장 신선도 (Absolute Market Freshness vs {summary.reference_market_date}):")
    print(f"  - FRESH (0~1 trading days)             : {summary.fresh_count}개")
    print(f"  - STALE (2~5 trading days)             : {summary.stale_count}개")
    print(f"  - VERY_STALE (6+ trading days)         : {summary.very_stale_count}개 (과거 검증 시점 고정 캐시)")
    print("-" * 70)
    print("6. 최종 Pattern A Universe 평가 현황:")
    print(f"  - Included in Universe                 : {summary.included_tickers}개 (캐시 완비 및 신선도 충족 종목)")
    print(f"  - Excluded from Universe               : {summary.excluded_tickers:,}개 (캐시 부재, 비보통주, Stale 등)")
    print("-" * 70)
    print("7. 제외 사유 상세 (Top Exclusion Reasons):")
    for reason, count in sorted(summary.exclusion_reason_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {reason:35s} : {count:5d}건")
    print("=" * 70)


if __name__ == "__main__":
    main()
