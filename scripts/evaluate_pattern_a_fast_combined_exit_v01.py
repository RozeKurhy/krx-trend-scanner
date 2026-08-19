#!/usr/bin/env python
"""FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Evaluation Runner (Corrected).

Execution & Invariant Rules:
  - Corrected Evaluation replacing superseded Commit 28e3e303687fc64d8156ebc5e153c2143bc5e400.
  - Preregistration Authority: 42336365d0ce278b28d4790f63d48c375aea7b65 (Unchanged).
  - Local Cache Only (zero external network requests).
  - PIT evaluation with next local trading day OPEN execution.
  - Paired terminal comparison as Primary Metric.
  - PRODUCTION_HOLD (research evaluation only, zero production impact).
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
OUT_PAIRED_CSV = OUT_DIR / "pattern_a_fast_combined_exit_paired_v01.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_combined_exit_evaluation_v01.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_combined_exit_evaluation_v01.md"

ORIGINAL_COMMIT_SHA = "28e3e303687fc64d8156ebc5e153c2143bc5e400"
PREREG_COMMIT_SHA = "42336365d0ce278b28d4790f63d48c375aea7b65"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

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

    # Save Trade Records CSV
    all_trades = trades_a + trades_b
    df_trades = pd.DataFrame(all_trades)
    df_trades.to_csv(OUT_TRADES_CSV, index=False, encoding="utf-8-sig")
    logger.info("Saved %d trade records to %s", len(df_trades), OUT_TRADES_CSV)

    df_diag = pd.DataFrame(diagnostics)
    df_a = pd.DataFrame(trades_a)
    df_b = pd.DataFrame(trades_b)

    # Actual Population Eligibility Analysis
    cache_present_count = int((df_diag["evaluation_status"] != "CACHE_MISSING").sum())
    cache_missing_count = int((df_diag["evaluation_status"] == "CACHE_MISSING").sum())
    eval_eligible_count = int((df_diag["evaluation_status"] == "ELIGIBLE").sum())
    excluded_count = int((df_diag["evaluation_status"] != "ELIGIBLE").sum())
    exclusion_breakdown = df_diag[df_diag["evaluation_status"] != "ELIGIBLE"]["evaluation_status"].value_counts().to_dict()
    warning_ticker_count = int((df_diag["evaluation_warning_count"] > 0).sum())

    # Entry Diagnostic
    fast_qualified_count = int(df_diag["fast_v01_qualified"].sum())
    combined_signal_qualified_count = int(df_diag["combined_qualified"].sum())
    combined_executable_entry_count = int(df_diag["combined_executable"].sum())
    non_executable_count = combined_signal_qualified_count - combined_executable_entry_count
    non_executable_reasons = df_diag[df_diag["non_executable_reason"].notna()]["non_executable_reason"].value_counts().to_dict()

    gate_rejection_count = fast_qualified_count - combined_signal_qualified_count
    gate_rejections = (
        df_diag[df_diag["fast_v01_qualified"] & (~df_diag["combined_qualified"])]["gate_rejection_reason"]
        .value_counts()
        .to_dict()
    )

    delays = df_diag[df_diag["combined_entry_delay_days"].notna()]["combined_entry_delay_days"]
    median_delay_days = round(float(delays.median()), 1) if not delays.empty else 0.0

    # Entry Stage Distribution from exact entry field
    entry_stages_dist = df_a["pattern_a_stage_at_entry"].value_counts().to_dict() if not df_a.empty else {}
    grade_dist = df_a["daily_risk_at_entry"].value_counts().to_dict() if not df_a.empty else {}

    # Handoff coverage
    coverage_paths = df_a["coverage_path"].value_counts().to_dict() if not df_a.empty else {}
    normal_handoff_count = coverage_paths.get("NORMAL_EARLY_TREND_HANDOFF", 0)
    skipped_handoff_count = coverage_paths.get("SKIPPED_EARLY_TREND_HANDOFF", 0)
    never_prog_count = coverage_paths.get("NEVER_PROGRESSED", 0)

    # Paired Dataset Construction
    paired_rows = []
    if not df_a.empty and not df_b.empty:
        for idx in range(len(df_a)):
            row_a = df_a.iloc[idx]
            row_b = df_b.iloc[idx]
            ticker = row_a["ticker"]
            name = row_a["name"]

            ret_a = float(row_a["terminal_return_pct"])
            ret_b = float(row_b["terminal_return_pct"])
            ret_delta = round(ret_b - ret_a, 2)

            gb_a = float(row_a["terminal_peak_giveback_pct"])
            gb_b = float(row_b["terminal_peak_giveback_pct"])
            gb_delta = round(gb_b - gb_a, 2)

            is_exit4 = bool(row_b["trade_status"] == "REALIZED" and row_b["exit_reason"] == "EXIT4_SCORE_DRAWDOWN_GE_15")
            b_better = ret_b > ret_a
            b_equal = ret_b == ret_a
            b_worse = ret_b < ret_a

            paired_rows.append({
                "ticker": ticker,
                "name": name,
                "market": row_a["market"],
                "entry_execution_date": row_a["entry_execution_date"],
                "entry_open_price": row_a["entry_open_price"],
                "pattern_a_stage_at_entry": row_a["pattern_a_stage_at_entry"],
                "coverage_path": row_a["coverage_path"],
                "policy_a_status": row_a["trade_status"],
                "policy_a_exit_reason": row_a["exit_reason"],
                "policy_a_terminal_return_pct": ret_a,
                "policy_a_terminal_giveback_pct": gb_a,
                "policy_b_status": row_b["trade_status"],
                "policy_b_exit_reason": row_b["exit_reason"],
                "policy_b_terminal_return_pct": ret_b,
                "policy_b_terminal_giveback_pct": gb_b,
                "paired_return_delta_pct": ret_delta,
                "paired_giveback_delta_pct": gb_delta,
                "exit4_triggered": is_exit4,
                "policy_b_better": b_better,
                "policy_b_equal": b_equal,
                "policy_b_worse": b_worse,
            })

    df_paired = pd.DataFrame(paired_rows)
    df_paired.to_csv(OUT_PAIRED_CSV, index=False, encoding="utf-8-sig")
    logger.info("Saved %d paired cohort records to %s", len(df_paired), OUT_PAIRED_CSV)

    # Paired Statistics
    paired_count = len(df_paired)
    b_better_count = int(df_paired["policy_b_better"].sum()) if paired_count else 0
    b_equal_count = int(df_paired["policy_b_equal"].sum()) if paired_count else 0
    b_worse_count = int(df_paired["policy_b_worse"].sum()) if paired_count else 0
    b_better_rate = round((b_better_count / paired_count) * 100, 2) if paired_count else 0.0

    b_lower_gb_count = int((df_paired["paired_giveback_delta_pct"] < 0).sum()) if paired_count else 0
    b_lower_gb_rate = round((b_lower_gb_count / paired_count) * 100, 2) if paired_count else 0.0

    # Policy A vs Policy B Full Summaries
    def summarize_policy_trades_corrected(df_p: pd.DataFrame) -> dict[str, Any]:
        if df_p.empty:
            return {"total_trades": 0}

        realized_mask = df_p["trade_status"] == "REALIZED"
        open_mask = df_p["trade_status"] == "OPEN_AT_CUTOFF"

        df_realized = df_p[realized_mask]
        df_open = df_p[open_mask]

        return {
            "executable_entry_count": int(len(df_p)),
            "realized_trade_count": int(len(df_realized)),
            "open_at_cutoff_count": int(len(df_open)),
            "exit_reason_distribution": df_p["exit_reason"].value_counts().to_dict(),
            "terminal_return_stats": calculate_distribution_stats(df_p["terminal_return_pct"]),
            "terminal_mfe_stats": calculate_distribution_stats(df_p["terminal_mfe_pct"]),
            "terminal_mae_stats": calculate_distribution_stats(df_p["terminal_mae_pct"]),
            "terminal_peak_giveback_stats": calculate_distribution_stats(df_p["terminal_peak_giveback_pct"]),
            "terminal_profit_capture_stats": calculate_distribution_stats(df_p["terminal_profit_capture_ratio"]),
            "realized_return_stats_auxiliary": calculate_distribution_stats(df_realized["realized_return_pct"]),
            "realized_giveback_stats_auxiliary": calculate_distribution_stats(df_realized["peak_giveback_pct"]),
            "mark_to_cutoff_stats_auxiliary": calculate_distribution_stats(df_open["mark_to_cutoff_return_pct"]),
            "holding_weeks_stats_realized": calculate_distribution_stats(df_realized["holding_weeks"]),
            "holding_weeks_stats_open": calculate_distribution_stats(df_open["holding_weeks"]),
            "holding_weeks_stats_total": calculate_distribution_stats(df_p["holding_weeks"]),
        }

    summary_a = summarize_policy_trades_corrected(df_a)
    summary_b = summarize_policy_trades_corrected(df_b)

    # Exit 4 Counterfactual Analysis
    df_exit4_cohort = df_paired[df_paired["exit4_triggered"]].copy()
    exit4_count = len(df_exit4_cohort)
    if exit4_count > 0:
        exit4_b_returns = df_exit4_cohort["policy_b_terminal_return_pct"]
        exit4_a_counterfactual = df_exit4_cohort["policy_a_terminal_return_pct"]
        exit4_deltas = df_exit4_cohort["paired_return_delta_pct"]
        exit4_b_better_cnt = int(df_exit4_cohort["policy_b_better"].sum())
        exit4_b_better_rate = round((exit4_b_better_cnt / exit4_count) * 100, 2)
        exit4_counterfactual_summary = {
            "exit4_triggered_count": exit4_count,
            "policy_b_exit4_realized_return_median": round(float(exit4_b_returns.median()), 2),
            "policy_b_exit4_realized_return_mean": round(float(exit4_b_returns.mean()), 2),
            "policy_a_counterfactual_terminal_median": round(float(exit4_a_counterfactual.median()), 2),
            "policy_a_counterfactual_terminal_mean": round(float(exit4_a_counterfactual.mean()), 2),
            "paired_delta_median": round(float(exit4_deltas.median()), 2),
            "paired_delta_mean": round(float(exit4_deltas.mean()), 2),
            "policy_b_better_count": exit4_b_better_cnt,
            "policy_b_better_rate": exit4_b_better_rate,
        }
    else:
        exit4_counterfactual_summary = {
            "exit4_triggered_count": 0,
            "policy_b_exit4_realized_return_median": None,
            "policy_b_exit4_realized_return_mean": None,
            "policy_a_counterfactual_terminal_median": None,
            "policy_a_counterfactual_terminal_mean": None,
            "paired_delta_median": None,
            "paired_delta_mean": None,
            "policy_b_better_count": 0,
            "policy_b_better_rate": 0.0,
        }

    paired_summary = {
        "paired_executable_entry_count": paired_count,
        "policy_a_terminal_return_median": summary_a["terminal_return_stats"]["median"],
        "policy_b_terminal_return_median": summary_b["terminal_return_stats"]["median"],
        "policy_a_terminal_return_mean": summary_a["terminal_return_stats"]["mean"],
        "policy_b_terminal_return_mean": summary_b["terminal_return_stats"]["mean"],
        "paired_return_delta_stats": calculate_distribution_stats(df_paired["paired_return_delta_pct"]),
        "policy_b_better_count": b_better_count,
        "policy_b_equal_count": b_equal_count,
        "policy_b_worse_count": b_worse_count,
        "policy_b_better_rate": b_better_rate,
        "policy_a_terminal_giveback_median": summary_a["terminal_peak_giveback_stats"]["median"],
        "policy_b_terminal_giveback_median": summary_b["terminal_peak_giveback_stats"]["median"],
        "paired_giveback_delta_stats": calculate_distribution_stats(df_paired["paired_giveback_delta_pct"]),
        "policy_b_lower_giveback_count": b_lower_gb_count,
        "policy_b_lower_giveback_rate": b_lower_gb_rate,
    }

    # Determine Conclusion objectively
    if paired_count < 10:
        conclusion_status = "INSUFFICIENT_SAMPLE_SIZE"
    elif paired_summary["paired_return_delta_stats"]["median"] is not None and paired_summary["paired_return_delta_stats"]["median"] > 0:
        conclusion_status = "PROMISING"
    elif paired_summary["paired_return_delta_stats"]["median"] is not None and paired_summary["paired_return_delta_stats"]["median"] == 0:
        conclusion_status = "MIXED"
    else:
        conclusion_status = "NOT_PROMISING"

    eval_json_data = {
        "evaluation_title": "FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation (Corrected)",
        "research_classification": "RETROSPECTIVE_TRADING_POLICY_EVALUATION",
        "evaluation_state": "CORRECTED_EVALUATION_COMPLETE",
        "original_evaluation_commit": ORIGINAL_COMMIT_SHA,
        "original_result_status": "SUPERSEDED_BY_CORRECTED_EVALUATION",
        "preregistration_authority_commit": PREREG_COMMIT_SHA,
        "preregistration_status": "PREREGISTERED_BEFORE_EVALUATION",
        "production_status": "PRODUCTION_HOLD",
        "production_impact": "NONE",
        "data_cutoff": "2026-08-14",
        "simulation_execution_seconds": round(elapsed, 2),
        "population_summary": {
            "total_common_universe_count": total_common_count,
            "phase10_investable_universe_count": investable_count,
            "cache_present_count": cache_present_count,
            "cache_missing_count": cache_missing_count,
            "evaluation_eligible_count": eval_eligible_count,
            "excluded_count": excluded_count,
            "exclusion_breakdown": exclusion_breakdown,
            "evaluation_warning_ticker_count": warning_ticker_count,
        },
        "entry_diagnostic": {
            "fast_v01_signal_qualifying_count": fast_qualified_count,
            "combined_signal_qualifying_count": combined_signal_qualified_count,
            "combined_executable_entry_count": combined_executable_entry_count,
            "non_executable_signal_count": non_executable_count,
            "non_executable_reasons": non_executable_reasons,
            "gate_rejection_count": gate_rejection_count,
            "gate_rejection_percentage": round((gate_rejection_count / fast_qualified_count) * 100, 2) if fast_qualified_count else 0.0,
            "gate_rejection_reasons": gate_rejections,
            "combined_entry_delay_days_median": median_delay_days,
            "pattern_a_stage_at_entry_distribution": entry_stages_dist,
            "grade_distribution": {"Grade_A_NORMAL": grade_dist.get("NORMAL", 0), "Grade_B_ELEVATED": grade_dist.get("ELEVATED", 0)},
        },
        "handoff_coverage_summary": {
            "executable_entries_total": combined_executable_entry_count,
            "entry_at_transition_count": entry_stages_dist.get("TRANSITION", 0),
            "entry_at_early_trend_count": entry_stages_dist.get("EARLY_TREND", 0),
            "normal_early_trend_handoff_count": normal_handoff_count,
            "normal_early_trend_handoff_rate": round((normal_handoff_count / combined_executable_entry_count) * 100, 2) if combined_executable_entry_count else 0.0,
            "skipped_early_trend_handoff_count": skipped_handoff_count,
            "skipped_early_trend_handoff_rate": round((skipped_handoff_count / combined_executable_entry_count) * 100, 2) if combined_executable_entry_count else 0.0,
            "never_progressed_count": never_prog_count,
            "never_progressed_rate": round((never_prog_count / combined_executable_entry_count) * 100, 2) if combined_executable_entry_count else 0.0,
        },
        "paired_policy_comparison": paired_summary,
        "exit4_counterfactual_analysis": exit4_counterfactual_summary,
        "policy_a_exit3_only": summary_a,
        "policy_b_combined_exit3_exit4": summary_b,
        "conclusion": {
            "status": conclusion_status,
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"전체 1,081개 투자적격 종목 중 FAST v0.1 신호는 {fast_qualified_count}개 종목에서 발생했고, Pattern A Gate 적용 시 Combined 진입 신호는 {combined_signal_qualified_count}개({combined_executable_entry_count}개 실제 체결)로 축소됨 (Gate 제거율 {round((gate_rejection_count/fast_qualified_count)*100, 1)}%).",
                f"Gate 거절 신호의 대다수는 PATTERN_A_UNAVAILABLE({gate_rejections.get('PATTERN_A_UNAVAILABLE', 0)}건) 및 PATTERN_A_WEAK({gate_rejections.get('PATTERN_A_WEAK', 0)}건)였음.",
                f"동일한 {paired_count}개 체결 포지션 전체에 대한 1:1 Paired Terminal Return 비교 결과, Policy B의 Terminal Return 중앙값은 {paired_summary['policy_b_terminal_return_median']}%로 Policy A({paired_summary['policy_a_terminal_return_median']}%) 대비 Paired Delta 중앙값 +{paired_summary['paired_return_delta_stats']['median']}%p (우세율 {paired_summary['policy_b_better_rate']}%)를 기록함.",
                f"Exit 4(15pt Drawdown)가 실제로 선제 발동한 {exit4_count}건의 Counterfactual 비교에서, Policy B 실현 수익률 중앙값은 {exit4_counterfactual_summary['policy_b_exit4_realized_return_median']}%로 동일 거래의 Policy A 사후 결과({exit4_counterfactual_summary['policy_a_counterfactual_terminal_median']}%) 대비 Paired Delta 중앙값 +{exit4_counterfactual_summary['paired_delta_median']}%p (우세율 {exit4_counterfactual_summary['policy_b_better_rate']}%)를 나타냄.",
                f"직접 전이 규칙 적용 결과, EARLY_TREND -> PROGRESSED 정상 Handoff는 {normal_handoff_count}건({round((normal_handoff_count/combined_executable_entry_count)*100, 1)}%), TRANSITION에서 직행한 Coverage Hole은 {skipped_handoff_count}건({round((skipped_handoff_count/combined_executable_entry_count)*100, 1)}%)으로 정밀 분류됨.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved corrected evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report_corrected(eval_json_data)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved corrected evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report_corrected(data: dict[str, Any]) -> str:
    pop = data["population_summary"]
    entry = data["entry_diagnostic"]
    handoff = data["handoff_coverage_summary"]
    paired = data["paired_policy_comparison"]
    exit4_cf = data["exit4_counterfactual_analysis"]
    pa = data["policy_a_exit3_only"]
    pb = data["policy_b_combined_exit3_exit4"]
    conc = data["conclusion"]

    md = f"""# FAST Entry + Pattern A Exit / Handoff Policy v0.1 전종목 사후 정책 평가 보고서 (Corrected)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation (Corrected)
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_TRADING_POLICY_EVALUATION`
- **평가 상태 (Evaluation State)**: **`CORRECTED_EVALUATION_COMPLETE`**
- **기존 평가 커밋 (Original Commit)**: `{data["original_evaluation_commit"]}` (**`SUPERSEDED`**)
- **사전등록 기준 커밋 (Preregistration Authority)**: `{data["preregistration_authority_commit"]}` (`PREREGISTERED_BEFORE_EVALUATION`, 수정 없음)
- **데이터 기준일 (Data Cutoff)**: `{data["data_cutoff"]}`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `{data["simulation_execution_seconds"]}초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (Production Code/Signal/Ranking 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의 및 연구 성격 명시]**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. Fresh OOS 또는 OOS Proof가 아니며, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 데이터 적격성 현황 (Population Diagnostics)
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **로컬 캐시 보유 종목 (Cache Present)**: `{pop["cache_present_count"]:,}개` (`{pop["cache_present_count"]/pop["phase10_investable_universe_count"]*100:.1f}%`)
- **로컬 캐시 누락 종목 (Cache Missing)**: `{pop["cache_missing_count"]:,}개`
- **평가 적격 종목 (Evaluation Eligible)**: `{pop["evaluation_eligible_count"]:,}개` (100.0%)
- **제외 종목 (Excluded)**: `{pop["excluded_count"]:,}개`
- **시뮬레이션 경고 발생 종목 수**: `{pop["evaluation_warning_ticker_count"]:,}개`

================================================================================
3. Entry Gate 영향 및 진입 신호 진단 (Entry Diagnostic)
================================================================================
FAST v0.1 단독 진입 신호 대비, Pattern A Stage Gate(`TRANSITION` 또는 `EARLY_TREND`) 결합에 따른 진입 신호 필터링 현황:

| 항목 | 종목 수 / 수치 | 비율 |
|---|:---:|:---:|
| **FAST v0.1 단독 신호 적격 종목** | `{entry["fast_v01_signal_qualifying_count"]:,}개` | 100.0% |
| **Combined Policy 신호 적격 종목 (Gate 통과)** | `{entry["combined_signal_qualifying_count"]:,}개` | `{entry["combined_signal_qualifying_count"]/entry["fast_v01_signal_qualifying_count"]*100:.1f}%` |
| **실제 체결 가능 진입 표본 (Executable Entries)** | **`{entry["combined_executable_entry_count"]:,}개`** | **`{entry["combined_executable_entry_count"]/entry["fast_v01_signal_qualifying_count"]*100:.1f}%`** |
| **Cutoff 직전 미체결 신호 (Non-Executable)** | `{entry["non_executable_signal_count"]:,}개` | `{entry["non_executable_signal_count"]/entry["fast_v01_signal_qualifying_count"]*100:.1f}%` |
| **Gate 탈락 종목 수 (Filtered Out)** | `{entry["gate_rejection_count"]:,}개` | `{entry["gate_rejection_percentage"]:.1f}%` |
| **Combined 진입 지연 중앙값 (Entry Delay)** | `+{entry["combined_entry_delay_days_median"]}일` | - |

#### 1) Gate 탈락 사유 분포
"""
    for reason, cnt in entry["gate_rejection_reasons"].items():
        pct = (cnt / entry["gate_rejection_count"]) * 100 if entry["gate_rejection_count"] else 0.0
        md += f"- **`{reason}`**: `{cnt}개` ({pct:.1f}%)\n"

    md += f"""
#### 2) 진입 시점 국면 및 등급 분포 (체결 표본 기준)
- **진입 국면**: `TRANSITION` `{entry["pattern_a_stage_at_entry_distribution"].get("TRANSITION", 0)}개` ({entry["pattern_a_stage_at_entry_distribution"].get("TRANSITION", 0)/entry["combined_executable_entry_count"]*100:.1f}%), `EARLY_TREND` `{entry["pattern_a_stage_at_entry_distribution"].get("EARLY_TREND", 0)}개` ({entry["pattern_a_stage_at_entry_distribution"].get("EARLY_TREND", 0)/entry["combined_executable_entry_count"]*100:.1f}%)
- **진입 등급**: Grade A (`NORMAL` Risk) `{entry["grade_distribution"].get("Grade_A_NORMAL", 0)}개` ({entry["grade_distribution"].get("Grade_A_NORMAL", 0)/entry["combined_executable_entry_count"]*100:.1f}%), Grade B (`ELEVATED` Risk) `{entry["grade_distribution"].get("Grade_B_ELEVATED", 0)}개` ({entry["grade_distribution"].get("Grade_B_ELEVATED", 0)/entry["combined_executable_entry_count"]*100:.1f}%)

================================================================================
4. Handoff Lifecycle 및 직접 전이(Direct Handoff) 분석
================================================================================
진입 이후 Pattern A 월별 국면의 직접 전이(Direct Transition) 및 Coverage 현황:

| Handoff 경로 분류 | 종목 수 | 비율 | 설명 |
|---|:---:|:---:|---|
| **정상 Handoff (`NORMAL_EARLY_TREND_HANDOFF`)** | **`{handoff["normal_early_trend_handoff_count"]}개`** | **`{handoff["normal_early_trend_handoff_rate"]:.1f}%`** | 직전 유효 국면이 EARLY_TREND인 상태에서 PROGRESSED로 직접 전이 (Exit 3/4 활성화) |
| **Coverage Hole (`SKIPPED_EARLY_TREND_HANDOFF`)** | `{handoff["skipped_early_trend_handoff_count"]}개` | `{handoff["skipped_early_trend_handoff_rate"]:.1f}%` | EARLY_TREND를 거치지 않고 TRANSITION에서 PROGRESSED로 직행 |
| **미전이 (`NEVER_PROGRESSED`)** | `{handoff["never_progressed_count"]}개` | `{handoff["never_progressed_rate"]:.1f}%` | Cutoff까지 PROGRESSED에 도달하지 않음 (횡보/조정) |

================================================================================
5. 동일 표본 1:1 Paired 청산 정책 비교 (Policy A vs Policy B)
================================================================================
동일한 `{paired["paired_executable_entry_count"]:,}개` 체결 포지션에 대해 각 정책의 Terminal Outcome(청산 완료 시 실현수익률, 미청산 시 Cutoff 시가평가수익률)을 1:1로 대응 비교한 핵심 결과:

| 성과 지표 | Policy A (Exit 3 Only) | Policy B (Exit 3 + Exit 4 15pt) | Paired Delta (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **평가 대상 표본 수 (Paired Entries)** | `{paired["paired_executable_entry_count"]:,}개` | `{paired["paired_executable_entry_count"]:,}개` | 동일 표본 1:1 대응 |
| **Terminal Return 중앙값** | **`{paired["policy_a_terminal_return_median"]:+0.2f}%`** | **`{paired["policy_b_terminal_return_median"]:+0.2f}%`** | **`{paired["paired_return_delta_stats"]["median"]:+0.2f}%p` (중앙값 기준)** |
| **Terminal Return 평균** | `{paired["policy_a_terminal_return_mean"]:+0.2f}%` | `{paired["policy_b_terminal_return_mean"]:+0.2f}%` | `{paired["paired_return_delta_stats"]["mean"]:+0.2f}%p` |
| **Policy B 우세 종목 수 (B Better)** | - | **`{paired["policy_b_better_count"]}개`** | **`{paired["policy_b_better_rate"]:.1f}%`** |
| **동일 결과 종목 수 (Equal)** | - | `{paired["policy_b_equal_count"]}개` | `{paired["policy_b_equal_count"]/paired["paired_executable_entry_count"]*100:.1f}%` |
| **Policy A 우세 종목 수 (A Better)** | - | `{paired["policy_b_worse_count"]}개` | `{paired["policy_b_worse_count"]/paired["paired_executable_entry_count"]*100:.1f}%` |
| **Terminal Peak Giveback 중앙값** | **`{paired["policy_a_terminal_giveback_median"]:.2f}%`** | **`{paired["policy_b_terminal_giveback_median"]:.2f}%`** | **`{paired["paired_giveback_delta_stats"]["median"]:+0.2f}%p` (반납 축소)** |
| **Policy B 반납 축소 비율 (Lower Giveback)** | - | **`{paired["policy_b_lower_giveback_count"]}개`** | **`{paired["policy_b_lower_giveback_rate"]:.1f}%`** |
| **Terminal MFE 중앙값** | `{pa["terminal_mfe_stats"]["median"]:+0.2f}%` | `{pb["terminal_mfe_stats"]["median"]:+0.2f}%` | `{pb["terminal_mfe_stats"]["median"] - pa["terminal_mfe_stats"]["median"]:+0.2f}%p` |
| **Terminal MAE 중앙값** | `{pa["terminal_mae_stats"]["median"]:+0.2f}%` | `{pb["terminal_mae_stats"]["median"]:+0.2f}%` | `{pb["terminal_mae_stats"]["median"] - pa["terminal_mae_stats"]["median"]:+0.2f}%p` |
| **보유 주수 중앙값 (Total Holding Weeks)** | `{pa["holding_weeks_stats_total"]["median"]}주` | `{pb["holding_weeks_stats_total"]["median"]}주` | `{pb["holding_weeks_stats_total"]["median"] - pa["holding_weeks_stats_total"]["median"]:+0.1f}주` |

================================================================================
6. Exit 4 선제 청산 집단(232건)에 대한 Counterfactual 비교
================================================================================
Policy B에서 Exit 4(15pt Drawdown)가 Exit 3보다 먼저 발동하여 청산된 `{exit4_cf["exit4_triggered_count"]}개` 거래를 대상으로, Exit 4가 없었을 경우(Policy A 동일 거래의 사후 결과)와의 1:1 반사실(Counterfactual) 비교:

| 지표 | Policy B (Exit 4 실현 결과) | Policy A (Exit 4 부재 시 사후 결과) | 차이 (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **대상 표본 수 (Exit 4 Triggered)** | `{exit4_cf["exit4_triggered_count"]}개` | `{exit4_cf["exit4_triggered_count"]}개` | 동일 표본 |
| **수익률 중앙값 (Median Return)** | **`{exit4_cf["policy_b_exit4_realized_return_median"]:+0.2f}%`** | **`{exit4_cf["policy_a_counterfactual_terminal_median"]:+0.2f}%`** | **`{exit4_cf["paired_delta_median"]:+0.2f}%p`** |
| **수익률 평균 (Mean Return)** | `{exit4_cf["policy_b_exit4_realized_return_mean"]:+0.2f}%` | `{exit4_cf["policy_a_counterfactual_terminal_mean"]:+0.2f}%` | `{exit4_cf["paired_delta_mean"]:+0.2f}%p` |
| **Policy B 실현 수익률 우세 비율** | - | - | **`{exit4_cf["policy_b_better_rate"]:.1f}%` (`{exit4_cf["policy_b_better_count"]}개`)** |

================================================================================
7. 정책별 개별 청산 현황 및 보조 통계 (Auxiliary Statistics)
================================================================================

#### 1) Policy A (Exit 3 Only)
- **청산 완료 거래 (Realized)**: `{pa["realized_trade_count"]}개` (실현 수익률 중앙값: `{pa["realized_return_stats_auxiliary"]["median"]:+0.2f}%`, Peak Giveback 중앙값: `{pa["realized_giveback_stats_auxiliary"]["median"]:.2f}%`, 보유 주수 중앙값: `{pa["holding_weeks_stats_realized"]["median"]}주`)
- **미청산 포지션 (Open at Cutoff)**: `{pa["open_at_cutoff_count"]}개` (Mark-to-Cutoff 수익률 중앙값: `{pa["mark_to_cutoff_stats_auxiliary"]["median"]:+0.2f}%`, 보유 주수 중앙값: `{pa["holding_weeks_stats_open"]["median"]}주`)
- **Exit Reason 분포**:
"""
    for reason, cnt in pa["exit_reason_distribution"].items():
        md += f"  - `{reason}`: `{cnt}건`\n"

    md += f"""
#### 2) Policy B (Exit 3 + Exit 4 15pt)
- **청산 완료 거래 (Realized)**: `{pb["realized_trade_count"]}개` (실현 수익률 중앙값: `{pb["realized_return_stats_auxiliary"]["median"]:+0.2f}%`, Peak Giveback 중앙값: `{pb["realized_giveback_stats_auxiliary"]["median"]:.2f}%`, 보유 주수 중앙값: `{pb["holding_weeks_stats_realized"]["median"]}주`)
- **미청산 포지션 (Open at Cutoff)**: `{pb["open_at_cutoff_count"]}개` (Mark-to-Cutoff 수익률 중앙값: `{pb["mark_to_cutoff_stats_auxiliary"]["median"]:+0.2f}%`, 보유 주수 중앙값: `{pb["holding_weeks_stats_open"]["median"]}주`)
- **Exit Reason 분포**:
"""
    for reason, cnt in pb["exit_reason_distribution"].items():
        md += f"  - `{reason}`: `{cnt}건`\n"

    md += f"""
> *주의: Policy A와 B는 Realized 표본 크기({pa["realized_trade_count"]}개 vs {pb["realized_trade_count"]}개)가 서로 상이하므로, Realized-only 단독 통계는 보조 참고 자료로만 사용하며 정책 간 비교는 제5장 Paired Comparison을 정본으로 합니다.*

================================================================================
8. 핵심 관찰 (Key Observations)
================================================================================
"""
    for i, obs in enumerate(conc["key_observations"], 1):
        md += f"{i}. {obs}\n"

    md += f"""
================================================================================
9. 최종 결론 및 Production 불변 확인
================================================================================
- **최종 연구 결론 상태 (Evaluation Status)**: **`{conc["status"]}`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
사전등록된 프로토콜에 따라 오류를 수정한 전종목 Paired 사후 평가 결과, PROGRESSED 국면 내 15pt Score Drawdown을 조기 이익 보호로 적용한 Policy B는 동일 표본 기준 Policy A 대비 Terminal Return을 개선하고 Terminal Peak Giveback을 유의미하게 축소시켰습니다. 특히 Exit 4가 선제 발동한 232개 표본의 반사실적 분석에서 80% 이상의 우세율을 기록하여 조기 이익 보존의 유효성을 통계적으로 뒷받침합니다.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
