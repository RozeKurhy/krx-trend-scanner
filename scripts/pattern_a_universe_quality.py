"""Pattern A Universe Data Quality Audit Runner.

로컬 캐시 및 종목 메타데이터에 대해 Universe Data Quality 감사를 수행하고
`data/processed/pattern_a_universe_quality.csv`를 생성하며 종합 결과를 출력한다.

실행:
    python scripts/pattern_a_universe_quality.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from trend_scanner.data.cache import ParquetCache
from trend_scanner.universe import (
    AssetType,
    MarketType,
    QualityStatus,
    audit_universe_quality,
)
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "pattern_a_universe_quality.csv"

# 대표적인 KOSPI / KOSDAQ 티커명 사전 (Manifest에서 우선 매핑)
_KNOWN_NAMES: dict[str, tuple[str, MarketType]] = {}
for label in PATTERN_A_STAGE_LABELS:
    _KNOWN_NAMES[label.ticker] = (label.name, MarketType.KOSPI)
for snap in PATTERN_A_STAGE_OOS_V01_LABELS:
    _KNOWN_NAMES[snap.ticker] = (snap.name, MarketType.KOSPI)

# 추가 코스닥/코스피 종목명 보정
_EXTRA_NAMES = {
    "086520": ("에코프로", MarketType.KOSDAQ),
    "247540": ("에코프로비엠", MarketType.KOSDAQ),
    "035900": ("JYP Ent.", MarketType.KOSDAQ),
    "041510": ("에스엠", MarketType.KOSDAQ),
    "271560": ("오리온", MarketType.KOSPI),
    "272210": ("한화시스템", MarketType.KOSPI),
    "316140": ("우리금융지주", MarketType.KOSPI),
    "214150": ("클래시스", MarketType.KOSDAQ),
    "145020": ("휴젤", MarketType.KOSDAQ),
    "042700": ("한미반도체", MarketType.KOSPI),
    "069620": ("대웅제약", MarketType.KOSPI),
    "078930": ("GS", MarketType.KOSPI),
    "079550": ("LIG넥스원", MarketType.KOSPI),
    "086790": ("하나금융지주", MarketType.KOSPI),
    "105560": ("KB금융", MarketType.KOSPI),
    "138040": ("메리츠금융지주", MarketType.KOSPI),
    "207940": ("삼성바이오로직스", MarketType.KOSPI),
}
_KNOWN_NAMES.update(_EXTRA_NAMES)


def main() -> None:
    print("=" * 70)
    print("Pattern A Universe & Data Quality Audit v0.1 실행")
    print("=" * 70)

    # 1. 로컬 캐시 내 parquet 파일 탐색
    parquet_files = sorted(list(CACHE_DIR.glob("*.parquet")))
    print(f"로컬 캐시 발견: {len(parquet_files)}개 파일 ({CACHE_DIR})")

    # 2. 메타데이터 구성
    metadata_list: list[dict[str, str]] = []
    for p in parquet_files:
        ticker = p.stem
        name, market = _KNOWN_NAMES.get(ticker, (ticker, MarketType.KOSPI))
        metadata_list.append(
            {
                "ticker": ticker,
                "name": name,
                "market": market.value,
            }
        )

    # 3. Universe Data Quality 감사 수행
    records, summary = audit_universe_quality(
        ticker_metadata=metadata_list,
        cache_dir=CACHE_DIR,
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
                "data_available",
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
                    r.data_available,
                    r.first_date,
                    r.last_date,
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

    # 5. 콘솔 종합 보고서 출력
    print("\n" + "=" * 70)
    print("Universe Quality Audit Summary")
    print("=" * 70)
    print(f"생성 일시 (generated_at)          : {summary.generated_at}")
    print(f"기준 시장일 (reference_market_date)  : {summary.reference_market_date}")
    print(f"최소 히스토리 기준 (min_months)     : {summary.min_history_months}개월 (3년)")
    print("-" * 70)
    print(f"총 검사 종목 수 (total_tickers)      : {summary.total_tickers}")
    print(f"  - KOSPI                           : {summary.kospi_count}")
    print(f"  - KOSDAQ                          : {summary.kosdaq_count}")
    print(f"  - KONEX                           : {summary.konex_count}")
    print("-" * 70)
    print(f"Pattern A Universe 포함 (included)  : {summary.included_tickers} ({summary.included_tickers / summary.total_tickers * 100:.1f}%)")
    print(f"Pattern A Universe 제외 (excluded)  : {summary.excluded_tickers} ({summary.excluded_tickers / summary.total_tickers * 100:.1f}%)")
    print("-" * 70)
    print("자산 유형 분포 (Asset Types):")
    print(f"  - 보통주 (COMMON)                 : {summary.common_stock_count}")
    print(f"  - 우선주 (PREFERRED)              : {summary.preferred_stock_count}")
    print(f"  - SPAC                            : {summary.spac_count}")
    print(f"  - REIT                            : {summary.reit_count}")
    print(f"  - ETF / ETN                       : {summary.etf_etn_count}")
    print("-" * 70)
    print("계층별 준비도 (Readiness):")
    print(f"  - Raw Data Ready                  : {summary.raw_data_ready_count} / {summary.total_tickers}")
    print(f"  - Feature Ready                   : {summary.feature_ready_count} / {summary.total_tickers}")
    print(f"  - Score Ready                     : {summary.score_ready_count} / {summary.total_tickers}")
    print(f"  - Stage Ready                     : {summary.stage_ready_count} / {summary.total_tickers}")
    print(f"  - Evaluator Ready                 : {summary.evaluator_ready_count} / {summary.total_tickers}")
    print("-" * 70)
    print("데이터 품질 및 이상치 현황:")
    print(f"  - Missing Cache                   : {summary.missing_cache_count}")
    print(f"  - Insufficient History (<36m)     : {summary.insufficient_history_count}")
    print(f"  - Stale Data (2+ days)            : {summary.stale_count}")
    print(f"  - Missing Columns                 : {summary.missing_columns_count}")
    print(f"  - Duplicate Dates                 : {summary.duplicate_date_count}")
    print(f"  - Invalid OHLC                    : {summary.invalid_ohlc_count}")
    print(f"  - Future Dates                    : {summary.future_date_count}")
    print(f"  - Diagnostic Extreme Returns      : {summary.extreme_return_count}")
    print(f"  - Exceptions                      : {summary.exception_count}")
    print("-" * 70)
    print("히스토리 길이 분포 (History Distribution):")
    for bucket, count in summary.history_distribution.items():
        print(f"  - {bucket:12s} : {count:3d}건")
    print("-" * 70)
    print("신선도 분포 (Freshness Distribution):")
    for bucket, count in summary.freshness_distribution.items():
        print(f"  - {bucket:22s} : {count:3d}건")
    print("-" * 70)
    print("제외 사유 분포 (Exclusion Reasons):")
    if summary.exclusion_reason_counts:
        for reason, count in summary.exclusion_reason_counts.items():
            print(f"  - {reason:30s} : {count:3d}건")
    else:
        print("  - 없음 (0건)")
    print("=" * 70)


if __name__ == "__main__":
    main()
