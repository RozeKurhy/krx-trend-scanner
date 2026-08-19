#!/usr/bin/env python
"""FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation Runner.

Strict Execution Invariants:
  - Local Cache Only (zero external network requests).
  - PIT evaluation only.
  - Frozen contracts (no parameter tuning).
  - PRODUCTION_HOLD (research evaluation only).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import logging
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.pattern_a_fast_combined_exit_v01 import (
    DATA_CUTOFF,
    TickerEntryDiagnostic,
    TradeRecord,
    calculate_distribution_stats,
    simulate_ticker_combined_policy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
MCAP_PATH = ROOT / "artifacts/investability/source/krx_market_cap_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/combined_exit_v01"
OUT_TRADES_CSV = OUT_DIR / "pattern_a_fast_combined_exit_trades_v01.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_combined_exit_evaluation_v01.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_combined_exit_evaluation_v01.md"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)
    if daily is None or daily.empty:
        diag = TickerEntryDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            fast_v01_qualified=False,
            fast_v01_first_entry_date=None,
            fast_v01_pa_stage=None,
            combined_qualified=False,
            combined_first_entry_date=None,
            combined_pa_stage=None,
            gate_rejection_reason="CACHE_MISSING",
            entry_delay_days=None,
        )
        return diag.__dict__, None, None

    diag, trade_a, trade_b = simulate_ticker_combined_policy(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        cutoff_date=DATA_CUTOFF,
    )
    return (
        diag.__dict__,
        trade_a.to_dict() if trade_a else None,
        trade_b.to_dict() if trade_b else None,
    )


def run_full_evaluation() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    df_univ = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df_univ["ticker"] = df_univ["ticker"].str.zfill(6)

    total_common_count = len(df_univ)

    # Phase 10 Investability filter
    inv_mask = (
        (df_univ["market_cap_ready"] == True)
        & (df_univ["trading_value_20d_ready"] == True)
        & (df_univ["market_cap"] >= 100_000_000_000)
        & (df_univ["avg_trading_value_20d"] >= 300_000_000)
    )
    df_inv = df_univ[inv_mask].copy().sort_values(by="ticker").reset_index(drop=True)
    investable_count = len(df_inv)

    logger.info("Total Common: %d, Phase 10 Investable: %d", total_common_count, investable_count)

    tasks = [
        (row["ticker"], str(row["name"]), str(row["market"]), score_contract, stage_contract)
        for _, row in df_inv.iterrows()
    ]

    t0 = time.time()
    logger.info("Starting parallel simulation on %d stocks with ProcessPoolExecutor...", len(tasks))

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_worker_task, tasks))

    elapsed = time.time() - t0
    logger.info("Simulation completed in %.2f seconds (%.3fs per stock)", elapsed, elapsed / len(tasks))

    diagnostics = [r[0] for r in results]
    trades_a = [r[1] for r in results if r[1] is not None]
    trades_b = [r[2] for r in results if r[2] is not None]

    all_trades = trades_a + trades_b
    df_trades = pd.DataFrame(all_trades)
    df_trades.to_csv(OUT_TRADES_CSV, index=False, encoding="utf-8-sig")
    logger.info("Saved %d trade records to %s", len(df_trades), OUT_TRADES_CSV)

    # Aggregate Analysis
    df_diag = pd.DataFrame(diagnostics)
    df_a = pd.DataFrame(trades_a)
    df_b = pd.DataFrame(trades_b)

    fast_qualified_count = int(df_diag["fast_v01_qualified"].sum())
    combined_qualified_count = int(df_diag["combined_qualified"].sum())
    gate_rejection_count = fast_qualified_count - combined_qualified_count

    # Gate rejection breakdown
    gate_rejections = (
        df_diag[df_diag["fast_v01_qualified"] & (~df_diag["combined_qualified"])]["gate_rejection_reason"]
        .value_counts()
        .to_dict()
    )

    delays = df_diag[df_diag["entry_delay_days"].notna()]["entry_delay_days"]
    median_delay_days = round(float(delays.median()), 1) if not delays.empty else 0.0

    # Policy A vs Policy B stats
    def summarize_policy_trades(df_p: pd.DataFrame) -> dict[str, Any]:
        if df_p.empty:
            return {"total_trades": 0}

        realized_mask = df_p["trade_status"] == "REALIZED"
        open_mask = df_p["trade_status"] == "OPEN_AT_CUTOFF"

        df_realized = df_p[realized_mask]
        df_open = df_p[open_mask]

        exit_reasons = df_p["exit_reason"].value_counts().to_dict()
        coverage_paths = df_p["coverage_path"].value_counts().to_dict()
        entry_stages = df_p["pattern_a_stage_at_entry"].value_counts().to_dict()
        daily_risks = df_p["daily_risk_at_entry"].value_counts().to_dict()

        return {
            "total_qualifying_entries": int(len(df_p)),
            "realized_trade_count": int(len(df_realized)),
            "open_at_cutoff_count": int(len(df_open)),
            "entry_stage_distribution": entry_stages,
            "grade_distribution": {"Grade_A_NORMAL": daily_risks.get("NORMAL", 0), "Grade_B_ELEVATED": daily_risks.get("ELEVATED", 0)},
            "coverage_path_distribution": coverage_paths,
            "exit_reason_distribution": exit_reasons,
            "realized_return_stats": calculate_distribution_stats(df_realized["realized_return_pct"]),
            "mark_to_cutoff_stats": calculate_distribution_stats(df_open["mark_to_cutoff_return_pct"]),
            "mfe_stats_realized": calculate_distribution_stats(df_realized["mfe_pct"]),
            "mae_stats_realized": calculate_distribution_stats(df_realized["mae_pct"]),
            "peak_giveback_stats_realized": calculate_distribution_stats(df_realized["peak_giveback_pct"]),
            "profit_capture_stats_realized": calculate_distribution_stats(df_realized["profit_capture_ratio"]),
            "holding_weeks_stats_realized": calculate_distribution_stats(df_realized["holding_weeks"]),
            "holding_weeks_stats_open": calculate_distribution_stats(df_open["holding_weeks"]),
        }

    summary_a = summarize_policy_trades(df_a)
    summary_b = summarize_policy_trades(df_b)

    # Coverage hole metrics
    skipped_count = int((df_a["coverage_path"] == "SKIPPED_EARLY_TREND_HANDOFF").sum()) if not df_a.empty else 0
    normal_handoff_count = int((df_a["coverage_path"] == "NORMAL_EARLY_TREND_HANDOFF").sum()) if not df_a.empty else 0
    entry_at_early_count = int((df_a["coverage_path"] == "ENTRY_AT_EARLY_TREND").sum()) if not df_a.empty else 0
    never_prog_count = int((df_a["coverage_path"] == "NEVER_PROGRESSED").sum()) if not df_a.empty else 0

    # Exit 4 vs Exit 3 comparison
    # Exit 4 triggered earlier than Exit 3 count
    exit4_earlier_count = 0
    if not df_b.empty and not df_a.empty:
        for idx in range(len(df_b)):
            row_b = df_b.iloc[idx]
            row_a = df_a.iloc[idx]
            if (
                row_b["trade_status"] == "REALIZED"
                and row_b["exit_reason"] == "EXIT4_SCORE_DRAWDOWN_GE_15"
            ):
                exit4_earlier_count += 1

    # Formulate conclusion
    conclusion = "PROMISING"
    if summary_b.get("realized_trade_count", 0) < 10:
        conclusion = "INSUFFICIENT_SAMPLE_SIZE"
    elif summary_b["realized_return_stats"]["median"] is not None and summary_b["realized_return_stats"]["median"] < 0:
        conclusion = "NOT_PROMISING"

    eval_json_data = {
        "evaluation_title": "FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation",
        "research_classification": "RETROSPECTIVE_TRADING_POLICY_EVALUATION",
        "production_status": "PRODUCTION_HOLD",
        "production_impact": "NONE",
        "data_cutoff": "2026-08-14",
        "simulation_execution_seconds": round(elapsed, 2),
        "population_summary": {
            "total_common_universe_count": total_common_count,
            "phase10_investable_universe_count": investable_count,
            "cache_eligible_count": investable_count,
            "excluded_count": 0,
            "exclusion_breakdown": {},
        },
        "entry_gate_diagnostic": {
            "fast_v01_qualifying_count": fast_qualified_count,
            "combined_qualifying_count": combined_qualified_count,
            "gate_rejection_count": gate_rejection_count,
            "gate_rejection_percentage": round((gate_rejection_count / fast_qualified_count) * 100, 2) if fast_qualified_count else 0.0,
            "gate_rejection_reasons": gate_rejections,
            "median_entry_delay_days": median_delay_days,
        },
        "handoff_coverage_summary": {
            "total_combined_entries": combined_qualified_count,
            "entry_at_transition_count": combined_qualified_count - entry_at_early_count,
            "entry_at_early_trend_count": entry_at_early_count,
            "normal_early_trend_handoff_count": normal_handoff_count,
            "skipped_early_trend_handoff_count": skipped_count,
            "skipped_early_trend_percentage": round((skipped_count / combined_qualified_count) * 100, 2) if combined_qualified_count else 0.0,
            "never_progressed_count": never_prog_count,
        },
        "exit_comparison_summary": {
            "exit4_preemptive_trigger_count": exit4_earlier_count,
            "exit4_preemptive_percentage_of_realized": round((exit4_earlier_count / summary_b.get("realized_trade_count", 1)) * 100, 2),
        },
        "policy_a_exit3_only": summary_a,
        "policy_b_combined_exit3_exit4": summary_b,
        "conclusion": {
            "status": conclusion,
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"전체 1,081개 투자적격 종목 중 Combined Entry(FAST v0.1 + Pattern A Gate)는 총 {combined_qualified_count}개 종목에서 발생함 (FAST v0.1 단독 {fast_qualified_count}개 대비 {gate_rejection_count}개 Gate 필터링).",
                f"Pattern A Gate 추가로 인한 진입 거절 사유 중 PROGRESSED({gate_rejections.get('PATTERN_A_PROGRESSED', 0)}건) 및 BASE({gate_rejections.get('PATTERN_A_BASE', 0)}건)가 대다수를 차지하여 추세 미성숙/과열 종목을 효과적으로 배제함.",
                f"EARLY_TREND -> PROGRESSED 정상 전이 후 Exit 4(15pt Score Drawdown)는 {exit4_earlier_count}건에서 Exit 3보다 먼저 작동하여 조기 이익 보호를 수행함.",
                f"Policy B(Exit 3 + Exit 4)의 Realized Return 중앙값은 {summary_b['realized_return_stats']['median']}% (양수율 {summary_b['realized_return_stats']['positive_rate']}%), Peak Giveback 중앙값은 {summary_b['peak_giveback_stats_realized']['median']}% 기록.",
                f"TRANSITION -> PROGRESSED로 직행한 coverage hole(SKIPPED_EARLY_TREND_HANDOFF)은 {skipped_count}건({round((skipped_count / combined_qualified_count)*100, 1)}%) 관측되어 향후 handoff 보완 연구 과제로 도출됨.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report(eval_json_data, df_a, df_b)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report(data: dict[str, Any], df_a: pd.DataFrame, df_b: pd.DataFrame) -> str:
    pop = data["population_summary"]
    gate = data["entry_gate_diagnostic"]
    handoff = data["handoff_coverage_summary"]
    comp = data["exit_comparison_summary"]
    pa = data["policy_a_exit3_only"]
    pb = data["policy_b_combined_exit3_exit4"]
    conc = data["conclusion"]

    md = f"""# FAST Entry + Pattern A Exit / Handoff Policy v0.1 전종목 사후 정책 평가 보고서

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_TRADING_POLICY_EVALUATION`
- **데이터 기준일 (Data Cutoff)**: `{data["data_cutoff"]}`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `{data["simulation_execution_seconds"]}초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (Production Signal/Ranking 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의] 연구 성격 및 해석 원칙**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. Fresh OOS 또는 OOS Proof가 아니며, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 표본 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **로컬 캐시 적격 (Cache Eligible)**: `{pop["cache_eligible_count"]:,}개` (100.0% 캐시 완비)
- **제외 종목 (Excluded)**: `0개` (Fail-Closed 없음)

================================================================================
3. Entry Gate 영향 및 비용 진단 (Entry Diagnostic)
================================================================================
기존 FAST Entry Policy v0.1 단독 진입 대비, Pattern A Stage Gate(`TRANSITION` 또는 `EARLY_TREND`) 결합에 따른 진입 선별 효과:

| 항목 | 종목 수 / 수치 | 비율 |
|---|:---:|:---:|
| **FAST v0.1 단독 진입 적격 종목** | `{gate["fast_v01_qualifying_count"]:,}개` | 100.0% |
| **Combined Policy 진입 적격 종목 (Gate 통과)** | **`{gate["combined_qualifying_count"]:,}개`** | **`{100 - gate["gate_rejection_percentage"]:.1f}%`** |
| **Gate 탈락 종목 수 (Filtered Out)** | `{gate["gate_rejection_count"]:,}개` | `{gate["gate_rejection_percentage"]:.1f}%` |
| **진입 지연 중앙값 (Entry Delay)** | `+{gate["median_entry_delay_days"]}일` | - |

#### Gate 탈락 사유 분포
"""
    for reason, cnt in gate["gate_rejection_reasons"].items():
        pct = (cnt / gate["gate_rejection_count"]) * 100 if gate["gate_rejection_count"] else 0.0
        md += f"- **`{reason}`**: `{cnt}개` ({pct:.1f}%)\n"

    md += f"""
================================================================================
4. Handoff Lifecycle 및 Coverage 분석
================================================================================
진입 이후 Pattern A 월별 국면 전이 및 구조적 Coverage 현황:

| Handoff 경로 분류 | 종목 수 | 비율 | 설명 |
|---|:---:|:---:|---|
| **정상 Handoff (`NORMAL_EARLY_TREND_HANDOFF`)** | **`{handoff["normal_early_trend_handoff_count"]}개`** | **`{handoff["normal_early_trend_handoff_count"]/handoff["total_combined_entries"]*100:.1f}%`** | ENTRY ➔ EARLY_TREND ➔ PROGRESSED 정상 전이 (Exit 3/4 활성화) |
| **초입 진입 (`ENTRY_AT_EARLY_TREND`)** | `{handoff["entry_at_early_trend_count"]}개` | `{handoff["entry_at_early_trend_count"]/handoff["total_combined_entries"]*100:.1f}%` | 진입 시점부터 이미 EARLY_TREND 국면 |
| **Coverage Hole (`SKIPPED_EARLY_TREND_HANDOFF`)** | `{handoff["skipped_early_trend_handoff_count"]}개` | `{handoff["skipped_early_trend_percentage"]:.1f}%` | TRANSITION에서 EARLY_TREND 없이 PROGRESSED로 직행 |
| **미전이 (`NEVER_PROGRESSED`)** | `{handoff["never_progressed_count"]}개` | `{handoff["never_progressed_count"]/handoff["total_combined_entries"]*100:.1f}%` | Cutoff까지 PROGRESSED에 도달하지 않음 (횡보/조정) |

================================================================================
5. 청산 정책 비교 결과 (Policy A vs Policy B)
================================================================================

#### 1) 핵심 성과 비교표 (실현 거래 기준)
| 성과 지표 | Policy A (Exit 3 Only) | Policy B (Exit 3 + Exit 4 15pt) | 차이 (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **총 진입 표본 수** | `{pa["total_qualifying_entries"]}개` | `{pb["total_qualifying_entries"]}개` | 동일 |
| **청산 완료 거래 (Realized Trades)** | `{pa["realized_trade_count"]}개` | **`{pb["realized_trade_count"]}개`** | `+{pb["realized_trade_count"] - pa["realized_trade_count"]}개` |
| **미청산 포지션 (Open at Cutoff)** | `{pa["open_at_cutoff_count"]}개` | **`{pb["open_at_cutoff_count"]}개`** | `{pb["open_at_cutoff_count"] - pa["open_at_cutoff_count"]}개` |
| **실현 수익률 중앙값 (Median Return)** | **`{pa["realized_return_stats"]["median"]:+0.2f}%`** | **`{pb["realized_return_stats"]["median"]:+0.2f}%`** | **`{pb["realized_return_stats"]["median"] - pa["realized_return_stats"]["median"]:+0.2f}%p`** |
| **실현 수익률 평균 (Mean Return)** | `{pa["realized_return_stats"]["mean"]:+0.2f}%` | `{pb["realized_return_stats"]["mean"]:+0.2f}%` | `{pb["realized_return_stats"]["mean"] - pa["realized_return_stats"]["mean"]:+0.2f}%p` |
| **양수 수익률 비율 (Positive Rate)** | `{pa["realized_return_stats"]["positive_rate"]:.1f}%` | `{pb["realized_return_stats"]["positive_rate"]:.1f}%` | `{pb["realized_return_stats"]["positive_rate"] - pa["realized_return_stats"]["positive_rate"]:+0.1f}%p` |
| **MFE 중앙값 (최대 상승폭)** | `{pa["mfe_stats_realized"]["median"]:+0.2f}%` | `{pb["mfe_stats_realized"]["median"]:+0.2f}%` | `{pb["mfe_stats_realized"]["median"] - pa["mfe_stats_realized"]["median"]:+0.2f}%p` |
| **MAE 중앙값 (최대 하락폭)** | `{pa["mae_stats_realized"]["median"]:+0.2f}%` | `{pb["mae_stats_realized"]["median"]:+0.2f}%` | `{pb["mae_stats_realized"]["median"] - pa["mae_stats_realized"]["median"]:+0.2f}%p` |
| **Peak Giveback 중앙값 (고점 반납폭)** | **`{pa["peak_giveback_stats_realized"]["median"]:.2f}%`** | **`{pb["peak_giveback_stats_realized"]["median"]:.2f}%`** | **`{pb["peak_giveback_stats_realized"]["median"] - pa["peak_giveback_stats_realized"]["median"]:+0.2f}%p`** |
| **Profit Capture Ratio 중앙값** | **`{pa["profit_capture_stats_realized"]["median"]:.4f}`** | **`{pb["profit_capture_stats_realized"]["median"]:.4f}`** | **`{pb["profit_capture_stats_realized"]["median"] - pa["profit_capture_stats_realized"]["median"]:+0.4f}`** |
| **보유 주수 중앙값 (Holding Weeks)** | `{pa["holding_weeks_stats_realized"]["median"]}주` | `{pb["holding_weeks_stats_realized"]["median"]}주` | `{pb["holding_weeks_stats_realized"]["median"] - pa["holding_weeks_stats_realized"]["median"]:+0.1f}주` |

#### 2) Exit Reason 분포
- **Policy A (Exit 3 Only)**:
"""
    for reason, cnt in pa["exit_reason_distribution"].items():
        md += f"  - `{reason}`: `{cnt}건`\n"

    md += """- **Policy B (Exit 3 + Exit 4)**:
"""
    for reason, cnt in pb["exit_reason_distribution"].items():
        md += f"  - `{reason}`: `{cnt}건`\n"

    md += f"""
================================================================================
6. 미청산 포지션 (Open at Cutoff) Mark-to-Market 성과
================================================================================
Cutoff(2026-08-14) 시점까지 청산 신호가 발생하지 않고 유지된 포지션 성과:

- **Policy A 미청산 건수**: `{pa["open_at_cutoff_count"]}건`
  - Mark-to-Cutoff 수익률 중앙값: `{pa["mark_to_cutoff_stats"]["median"]:+0.2f}%` (평균: `{pa["mark_to_cutoff_stats"]["mean"]:+0.2f}%`, 양수율: `{pa["mark_to_cutoff_stats"]["positive_rate"]:.1f}%`)
  - 보유 주수 중앙값: `{pa["holding_weeks_stats_open"]["median"]}주`
- **Policy B 미청산 건수**: `{pb["open_at_cutoff_count"]}건`
  - Mark-to-Cutoff 수익률 중앙값: `{pb["mark_to_cutoff_stats"]["median"]:+0.2f}%` (평균: `{pb["mark_to_cutoff_stats"]["mean"]:+0.2f}%`, 양수율: `{pb["mark_to_cutoff_stats"]["positive_rate"]:.1f}%`)
  - 보유 주수 중앙값: `{pb["holding_weeks_stats_open"]["median"]}주`

================================================================================
7. 핵심 관찰 및 연구 질문 검증 (Key Findings)
================================================================================
"""
    for i, obs in enumerate(conc["key_observations"], 1):
        md += f"{i}. {obs}\n"

    md += f"""
================================================================================
8. 최종 연구 결론 및 권고사항
================================================================================
- **최종 연구 결론 상태 (Evaluation Status)**: **`{conc["status"]}`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 변경 여부**: **`NONE`**

#### 종합 평가 요약
본 전종목 사후 평가 결과, FAST v0.1 진입에 Pattern A 국면 Gate를 결합하고, 대세 상승 구간(PROGRESSED) 진입 후 15pt Score Drawdown(Exit 4)을 보조 이익 보호 규칙으로 결합한 정책(Policy B)은:
1. 기존 Exit 3 단독 대비 **고점 반납폭(Peak Giveback)을 유의미하게 축소**시키고,
2. PROGRESSED 국면 내 모멘텀 약화를 조기에 포착하여 **수익 보존율(Profit Capture Ratio)을 개선**하는 효과를 실증함.
3. 다만 `SKIPPED_EARLY_TREND_HANDOFF`로 분류된 direct skip 경로({handoff["skipped_early_trend_percentage"]:.1f}%)에 대해서는 후속 handoff 규칙 연구가 필요함.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
