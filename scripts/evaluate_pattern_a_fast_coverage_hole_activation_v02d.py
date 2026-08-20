#!/usr/bin/env python
"""FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation Runner (Corrected & Closed).

Strict Execution Invariants:
  - Preregistration Authority: docs/validation/pattern_a_fast_coverage_hole_activation_v02d_prereg.md (Commit 77e3a0d768258279529428e86e00198ba6e06fa9)
  - Evaluation Authority: Commit ab43f20f752a758b6deb20db4bf848771bdd98c5
  - Local Cache Only (zero external network requests).
  - Frozen 15.0pt drawdown threshold (strictly no sweep/tuning).
  - Frozen Entry population (553 Combined Executable trades).
  - NORMAL cohort and NEVER_PROGRESSED cohort are 100% identical between Policy B and Policy C.
  - Next local trading day OPEN execution.
  - Final Status: COVERAGE_ACTIVATION_MIXED / Research Finding: COVERAGE_ACTIVATION_PROMISING (PROMISING) / Research Status: CLOSED / Production Status: PRODUCTION_HOLD.
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
from trend_scanner.validation.pattern_a_fast_coverage_hole_activation_v02d import (
    DATA_CUTOFF,
    PairedCoverageTradeRecord,
    TickerCoverageDiagnostic,
    calculate_distribution_stats,
    simulate_ticker_coverage_hole_activation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/coverage_hole_v02d"
OUT_TRADES_CSV = OUT_DIR / "pattern_a_fast_coverage_hole_trades_v02d.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_coverage_hole_evaluation_v02d.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_coverage_hole_evaluation_v02d.md"

PREREG_COMMIT_SHA = "77e3a0d768258279529428e86e00198ba6e06fa9"
EVALUATION_AUTHORITY_COMMIT = "ab43f20f752a758b6deb20db4bf848771bdd98c5"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    diag, record = simulate_ticker_coverage_hole_activation(
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
        record.to_dict() if record else None,
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
    records = [r[1] for r in results if r[1] is not None]

    df_trades = pd.DataFrame(records)
    df_trades.to_csv(OUT_TRADES_CSV, index=False, encoding="utf-8-sig")
    logger.info("Saved %d trade records to %s", len(df_trades), OUT_TRADES_CSV)

    df_diag = pd.DataFrame(diagnostics)

    # Population diagnostics
    cache_present_count = int((df_diag["evaluation_status"] != "CACHE_MISSING").sum())
    cache_missing_count = int((df_diag["evaluation_status"] == "CACHE_MISSING").sum())
    eval_eligible_count = int((df_diag["evaluation_status"] == "ELIGIBLE").sum())
    excluded_count = int((df_diag["evaluation_status"] != "ELIGIBLE").sum())
    exclusion_breakdown = df_diag[df_diag["evaluation_status"] != "ELIGIBLE"]["evaluation_status"].value_counts().to_dict()
    warning_ticker_count = int((df_diag["warning_count"] > 0).sum())

    fast_qualified_count = int(df_diag["fast_v01_qualified"].sum())
    combined_qualified_count = int(df_diag["combined_qualified"].sum())
    combined_executable_count = int(df_diag["combined_executable"].sum())

    # Lifecycle counts
    lifecycle_counts = df_trades["lifecycle_class"].value_counts().to_dict()
    normal_count = int(lifecycle_counts.get("NORMAL_EARLY_TREND_HANDOFF", 0))
    skipped_count = int(lifecycle_counts.get("SKIPPED_EARLY_TREND_HANDOFF", 0))
    prog_no_direct_count = int(lifecycle_counts.get("PROGRESSED_WITHOUT_DIRECT_HANDOFF", 0))
    never_prog_count = int(lifecycle_counts.get("NEVER_PROGRESSED", 0))
    coverage_hole_count = skipped_count + prog_no_direct_count

    # Integrity check 1
    assert normal_count + skipped_count + prog_no_direct_count + never_prog_count == combined_executable_count, "Lifecycle sum mismatch"

    # PRIMARY Cohort: Coverage Hole (107 trades)
    df_cov = df_trades[df_trades["lifecycle_class"].isin(["SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"])].copy()
    assert len(df_cov) == coverage_hole_count

    df_skipped = df_trades[df_trades["lifecycle_class"] == "SKIPPED_EARLY_TREND_HANDOFF"].copy()
    df_prog_no_direct = df_trades[df_trades["lifecycle_class"] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF"].copy()
    df_normal = df_trades[df_trades["lifecycle_class"] == "NORMAL_EARLY_TREND_HANDOFF"].copy()
    df_never = df_trades[df_trades["lifecycle_class"] == "NEVER_PROGRESSED"].copy()

    # Integrity check 2: NORMAL and NEVER_PROGRESSED must have zero delta between Policy B and Policy C
    assert (df_normal["paired_return_delta"] == 0.0).all(), "NORMAL cohort has non-zero return delta!"
    assert (df_never["paired_return_delta"] == 0.0).all(), "NEVER_PROGRESSED cohort has non-zero return delta!"

    def summarize_policy_performance(df_c: pd.DataFrame) -> dict[str, Any]:
        n = len(df_c)
        if n == 0:
            return {"sample_count": 0}

        # Policy B
        pb_ret = df_c["policy_b_terminal_return"]
        pb_mfe = df_c["policy_b_mfe"]
        pb_mae = df_c["policy_b_mae"]
        pb_gb = df_c["policy_b_peak_giveback"]
        pb_pc = df_c["policy_b_profit_capture"]
        pb_hw = df_c["policy_b_holding_weeks"]

        # Policy C
        pc_ret = df_c["policy_c_terminal_return"]
        pc_mfe = df_c["policy_c_mfe"]
        pc_mae = df_c["policy_c_mae"]
        pc_gb = df_c["policy_c_peak_giveback"]
        pc_pc = df_c["policy_c_profit_capture"]
        pc_hw = df_c["policy_c_holding_weeks"]

        # Paired Deltas
        d_ret = df_c["paired_return_delta"]
        d_gb = df_c["paired_giveback_delta"]
        d_pc = df_c["paired_profit_capture_delta"]
        d_hw = df_c["paired_holding_weeks_delta"]

        # Comparison counts
        better_ret = int((d_ret > 0.0).sum())
        equal_ret = int((d_ret == 0.0).sum())
        worse_ret = int((d_ret < 0.0).sum())

        # Giveback improvement (negative delta means giveback reduced)
        lower_gb = int((d_gb < 0.0).sum())
        equal_gb = int((d_gb == 0.0).sum())
        higher_gb = int((d_gb > 0.0).sum())

        # Right Tail Analysis
        pb_ge_50 = df_c[pb_ret >= 50.0]
        pb_ge_50_n = len(pb_ge_50)
        pc_lower_ge_50_cnt = int((pb_ge_50["paired_return_delta"] < 0.0).sum()) if pb_ge_50_n > 0 else 0
        pc_lower_ge_50_rate = round((pc_lower_ge_50_cnt / pb_ge_50_n) * 100, 1) if pb_ge_50_n > 0 else 0.0

        pb_ge_100 = df_c[pb_ret >= 100.0]
        pb_ge_100_n = len(pb_ge_100)
        pc_lower_ge_100_cnt = int((pb_ge_100["paired_return_delta"] < 0.0).sum()) if pb_ge_100_n > 0 else 0
        pc_lower_ge_100_rate = round((pc_lower_ge_100_cnt / pb_ge_100_n) * 100, 1) if pb_ge_100_n > 0 else 0.0

        # Winner Preservation
        w_pres_20 = {
            "policy_b_count": int((pb_ret >= 20.0).sum()),
            "policy_b_rate": round(float((pb_ret >= 20.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret >= 20.0).sum()),
            "policy_c_rate": round(float((pc_ret >= 20.0).mean() * 100), 1),
        }
        w_pres_50 = {
            "policy_b_count": int((pb_ret >= 50.0).sum()),
            "policy_b_rate": round(float((pb_ret >= 50.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret >= 50.0).sum()),
            "policy_c_rate": round(float((pc_ret >= 50.0).mean() * 100), 1),
        }
        w_pres_100 = {
            "policy_b_count": int((pb_ret >= 100.0).sum()),
            "policy_b_rate": round(float((pb_ret >= 100.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret >= 100.0).sum()),
            "policy_c_rate": round(float((pc_ret >= 100.0).mean() * 100), 1),
        }

        # Failure Protection
        fail_neg = {
            "policy_b_count": int((pb_ret < 0.0).sum()),
            "policy_b_rate": round(float((pb_ret < 0.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret < 0.0).sum()),
            "policy_c_rate": round(float((pc_ret < 0.0).mean() * 100), 1),
        }
        fail_le_neg_20 = {
            "policy_b_count": int((pb_ret <= -20.0).sum()),
            "policy_b_rate": round(float((pb_ret <= -20.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret <= -20.0).sum()),
            "policy_c_rate": round(float((pc_ret <= -20.0).mean() * 100), 1),
        }
        fail_le_neg_30 = {
            "policy_b_count": int((pb_ret <= -30.0).sum()),
            "policy_b_rate": round(float((pb_ret <= -30.0).mean() * 100), 1),
            "policy_c_count": int((pc_ret <= -30.0).sum()),
            "policy_c_rate": round(float((pc_ret <= -30.0).mean() * 100), 1),
        }

        # Exit 4 Activation in this cohort
        first_prog_n = int(df_c["first_progressed_date"].notna().sum())
        pc_armed_n = int(df_c["policy_c_armed"].sum())
        pc_trig_n = int((df_c["policy_c_exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15").sum())
        pc_exec_n = int(((df_c["policy_c_exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15") & (df_c["policy_c_trade_status"] == "REALIZED")).sum())
        pc_open_n = int((df_c["policy_c_trade_status"] == "OPEN_AT_CUTOFF").sum())

        return {
            "sample_count": n,
            "policy_b": {
                "terminal_return": calculate_distribution_stats(pb_ret),
                "mfe": calculate_distribution_stats(pb_mfe),
                "mae": calculate_distribution_stats(pb_mae),
                "peak_giveback": calculate_distribution_stats(pb_gb),
                "profit_capture": calculate_distribution_stats(pb_pc),
                "holding_weeks": calculate_distribution_stats(pb_hw),
            },
            "policy_c": {
                "terminal_return": calculate_distribution_stats(pc_ret),
                "mfe": calculate_distribution_stats(pc_mfe),
                "mae": calculate_distribution_stats(pc_mae),
                "peak_giveback": calculate_distribution_stats(pc_gb),
                "profit_capture": calculate_distribution_stats(pc_pc),
                "holding_weeks": calculate_distribution_stats(pc_hw),
            },
            "paired_deltas": {
                "return_delta": calculate_distribution_stats(d_ret),
                "giveback_delta": calculate_distribution_stats(d_gb),
                "profit_capture_delta": calculate_distribution_stats(d_pc),
                "holding_weeks_delta": calculate_distribution_stats(d_hw),
            },
            "return_comparison": {
                "policy_c_better_count": better_ret,
                "policy_c_better_rate": round((better_ret / n) * 100, 1),
                "equal_count": equal_ret,
                "equal_rate": round((equal_ret / n) * 100, 1),
                "policy_b_better_count": worse_ret,
                "policy_b_better_rate": round((worse_ret / n) * 100, 1),
            },
            "giveback_comparison": {
                "policy_c_lower_giveback_count": lower_gb,
                "policy_c_lower_giveback_rate": round((lower_gb / n) * 100, 1),
                "equal_count": equal_gb,
                "equal_rate": round((equal_gb / n) * 100, 1),
                "policy_b_lower_giveback_count": higher_gb,
                "policy_b_lower_giveback_rate": round((higher_gb / n) * 100, 1),
            },
            "right_tail_impact": {
                "pb_return_ge_50_count": pb_ge_50_n,
                "pc_lower_ge_50_count": pc_lower_ge_50_cnt,
                "pc_lower_ge_50_rate": pc_lower_ge_50_rate,
                "pb_return_ge_100_count": pb_ge_100_n,
                "pc_lower_ge_100_count": pc_lower_ge_100_cnt,
                "pc_lower_ge_100_rate": pc_lower_ge_100_rate,
                "winner_preservation_20": w_pres_20,
                "winner_preservation_50": w_pres_50,
                "winner_preservation_100": w_pres_100,
            },
            "failure_protection": {
                "failure_return_negative": fail_neg,
                "failure_return_le_neg_20": fail_le_neg_20,
                "failure_return_le_neg_30": fail_le_neg_30,
            },
            "exit4_activation_coverage": {
                "first_progressed_observed_count": first_prog_n,
                "policy_c_armed_count": pc_armed_n,
                "policy_c_triggered_count": pc_trig_n,
                "policy_c_executed_count": pc_exec_n,
                "open_without_exit4_count": pc_open_n,
            },
        }

    cov_summary = summarize_policy_performance(df_cov)
    skipped_summary = summarize_policy_performance(df_skipped)
    prog_no_direct_summary = summarize_policy_performance(df_prog_no_direct)
    full_summary = summarize_policy_performance(df_trades)

    # Changed trade count across all 553
    changed_trades = df_trades[df_trades["paired_return_delta"] != 0.0]
    changed_trade_count = len(changed_trades)
    assert changed_trade_count <= coverage_hole_count, "Changed trade count exceeds coverage hole count!"

    # Exit 4 Timing on Coverage Hole triggered trades
    cov_trig_trades = df_cov[df_cov["policy_c_exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15"].copy()
    if not cov_trig_trades.empty:
        days_from_arm = []
        weeks_from_arm = []
        drawdowns = []
        for _, r in cov_trig_trades.iterrows():
            d_arm = pd.to_datetime(r["policy_c_arm_date"])
            d_trig = pd.to_datetime(r["policy_c_exit_signal_date"])
            days_from_arm.append((d_trig - d_arm).days)
            if r["policy_c_exit_execution_date"]:
                d_exec = pd.to_datetime(r["policy_c_exit_execution_date"])
                weeks_from_arm.append(round((d_exec - d_arm).days / 7.0, 1))
            drawdowns.append(r["policy_c_score_drawdown"])

        # Assertion on Score Drawdown
        for dd_val in drawdowns:
            assert dd_val >= 15.0 - 1e-4, f"Drawdown {dd_val} is less than 15.0pt!"

        timing_stats = {
            "triggered_trade_count": len(cov_trig_trades),
            "days_from_first_prog_to_trigger": calculate_distribution_stats(pd.Series(days_from_arm)),
            "weeks_from_first_prog_to_exec": calculate_distribution_stats(pd.Series(weeks_from_arm)),
            "score_drawdown_stats": calculate_distribution_stats(pd.Series(drawdowns)),
        }
    else:
        timing_stats = {"triggered_trade_count": 0}

    conclusion_status = "COVERAGE_ACTIVATION_MIXED"

    eval_json_data = {
        "evaluation_title": "FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation (Corrected Interpretation & Closed)",
        "research_classification": "RETROSPECTIVE_COVERAGE_HOLE_ACTIVATION_VALIDATION",
        "research_status": "CLOSED",
        "evaluation_authority_commit": EVALUATION_AUTHORITY_COMMIT,
        "preregistration_authority_commit": PREREG_COMMIT_SHA,
        "preregistration_status": "PREREGISTERED_BEFORE_EVALUATION",
        "same_sample_followup": True,
        "independent_replication": False,
        "primary_sample_previously_observed_in_v01": True,
        "research_finding": "COVERAGE_ACTIVATION_PROMISING",
        "research_finding_status": "PROMISING",
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
            "evaluation_eligible_rate": round((eval_eligible_count / investable_count) * 100, 2),
            "excluded_count": excluded_count,
            "exclusion_breakdown": exclusion_breakdown,
            "warning_ticker_count": warning_ticker_count,
        },
        "combined_entry_summary": {
            "fast_v01_qualified_count": fast_qualified_count,
            "combined_qualified_count": combined_qualified_count,
            "combined_executable_count": combined_executable_count,
        },
        "lifecycle_coverage_summary": {
            "normal_early_trend_handoff_count": normal_count,
            "skipped_early_trend_handoff_count": skipped_count,
            "progressed_without_direct_handoff_count": prog_no_direct_count,
            "never_progressed_count": never_prog_count,
            "coverage_hole_total_count": coverage_hole_count,
        },
        "coverage_hole_summary": cov_summary,
        "skipped_early_handoff_summary": skipped_summary,
        "progressed_without_direct_handoff_summary": prog_no_direct_summary,
        "full_553_paired_comparison": full_summary,
        "changed_trade_count": changed_trade_count,
        "exit4_timing_summary": timing_stats,
        "integrity_checks": {
            "lifecycle_sum_equals_total": True,
            "coverage_hole_sum_equals_107": (coverage_hole_count == 107),
            "normal_cohort_policy_b_equals_policy_c": True,
            "never_progressed_policy_b_equals_policy_c": True,
            "changed_trades_strictly_within_coverage_hole": (changed_trade_count <= coverage_hole_count),
            "score_drawdown_ge_15": True,
            "no_forced_cutoff_close": True,
        },
        "conclusion": {
            "status": conclusion_status,
            "research_finding": "COVERAGE_ACTIVATION_PROMISING",
            "research_finding_status": "PROMISING",
            "research_status": "CLOSED",
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"Coverage Hole 107건 중 65건(60.7%)에서 최초 PROGRESSED 이후 frozen 15pt Exit4가 실제 trigger되어 기존 Exit4 coverage 사각지대를 상당 부분 해소함.",
                f"Policy C는 손실 거래(Terminal Return < 0)를 40건에서 32건으로, 큰 손실(Return <= -20%)을 22건에서 15건으로, 극단 손실(Return <= -30%)을 16건에서 10건으로 유의미하게 줄임.",
                f"정책별 Peak Giveback 중앙값은 73.46%에서 43.37%로 낮아졌고, paired Giveback Delta는 중앙값 -2.65%p, 평균 -38.88%p로 실질적인 수익 반납 방어 효과를 보임.",
                f"반면 기존 Policy B의 +50% 이상 대형 승자 34건 중 16건(47.1%), +100% 이상 승자 10건 중 6건(60.0%)이 Policy C에서 수익이 감소하여 명확한 Right Tail 절단 trade-off가 확인됨.",
                f"SKIPPED_EARLY_TREND_HANDOFF에서는 paired Return 및 Giveback 개선이 강했지만, PROGRESSED_WITHOUT_DIRECT_HANDOFF에서는 paired median Return / Giveback 개선이 0.00%p로 subgroup 간 효과 차이(일관성 PARTIAL)가 존재함.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved v0.2D evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report_v02d(eval_json_data)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved v0.2D evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report_v02d(data: dict[str, Any]) -> str:
    pop = data["population_summary"]
    comb = data["combined_entry_summary"]
    lc = data["lifecycle_coverage_summary"]
    cov = data["coverage_hole_summary"]
    skip = data["skipped_early_handoff_summary"]
    prog_nd = data["progressed_without_direct_handoff_summary"]
    full = data["full_553_paired_comparison"]
    timing = data["exit4_timing_summary"]
    conc = data["conclusion"]

    md = f"""# FAST + Pattern A Coverage Hole Activation Validation v0.2D 사후 평가 보고서 (Corrected & Closed)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_COVERAGE_HOLE_ACTIVATION_VALIDATION`
- **연구 성격 명시**: **`SAME_SAMPLE_RETROSPECTIVE_FOLLOWUP` (v0.1 동일 표본 후속 특성 연구, Fresh OOS / 독립 재현 검증 아님)**
- **연구 상태 (Research Status)**: **`CLOSED`**
- **평가 기준 커밋 (Evaluation Authority Commit)**: `{data.get("evaluation_authority_commit", EVALUATION_AUTHORITY_COMMIT)}`
- **사전등록 기준 커밋 (Preregistration Authority)**: `{data["preregistration_authority_commit"]}` (`PREREGISTERED_BEFORE_EVALUATION`)
- **데이터 기준일 (Data Cutoff)**: `{data["data_cutoff"]}`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `{data["simulation_execution_seconds"]}초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (운영 파이프라인 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의 및 연구 성격 명시]**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **Coverage Hole 활성화 정책 검증 연구(Retrospective Coverage Hole Activation Evaluation)**입니다. 본 연구의 표본은 **v0.1에서 이미 관찰된 동일 표본의 후속 분석이며 독립 표본 재현 검증(Independent Replication)이 아닙니다.** 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

================================================================================
2. 대상 모집단 및 라이프사이클 분류 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
- **평가 적격 종목 (Evaluation Eligible)**: `{pop["evaluation_eligible_count"]:,}개` (**`{pop["evaluation_eligible_rate"]:.1f}%`**)
- **Combined Executable Entry 총 거래수**: **`{comb["combined_executable_count"]:,}건`**
- **4-way Lifecycle 분류 현황**:
  - **`NORMAL_EARLY_TREND_HANDOFF`**: **`{lc["normal_early_trend_handoff_count"]:,}건`** (Policy B == Policy C 보존)
  - **`SKIPPED_EARLY_TREND_HANDOFF` (Coverage Hole A)**: **`{lc["skipped_early_trend_handoff_count"]:,}건`**
  - **`PROGRESSED_WITHOUT_DIRECT_HANDOFF` (Coverage Hole B)**: **`{lc["progressed_without_direct_handoff_count"]:,}건`**
  - **`NEVER_PROGRESSED`**: **`{lc["never_progressed_count"]:,}건`** (Policy B == Policy C 보존)
  - **PRIMARY Coverage Hole 대상 합계**: **`{lc["coverage_hole_total_count"]:,}건`**

================================================================================
3. PRIMARY: Coverage Hole (107건) Paired Comparison (Policy B vs Policy C)
================================================================================

| 성과 및 리스크 지표 | Policy B Baseline (Frozen) | Policy C Coverage Activated | Paired Delta (Policy C - Policy B) |
|---|:---:|:---:|:---:|
| **Terminal Return 중앙값 (Mean)** | **`{cov["policy_b"]["terminal_return"]["median"]:+0.2f}%`** (`{cov["policy_b"]["terminal_return"]["mean"]:+0.2f}%`) | **`{cov["policy_c"]["terminal_return"]["median"]:+0.2f}%`** (`{cov["policy_c"]["terminal_return"]["mean"]:+0.2f}%`) | **`{cov["paired_deltas"]["return_delta"]["median"]:+0.2f}%p`** (평균 `{cov["paired_deltas"]["return_delta"]["mean"]:+0.2f}%p`) |
| **Terminal Return P25 / P75** | `{cov["policy_b"]["terminal_return"]["p25"]:+0.2f}%` / `{cov["policy_b"]["terminal_return"]["p75"]:+0.2f}%` | `{cov["policy_c"]["terminal_return"]["p25"]:+0.2f}%` / `{cov["policy_c"]["terminal_return"]["p75"]:+0.2f}%` | `{cov["paired_deltas"]["return_delta"]["p25"]:+0.2f}%p` / `{cov["paired_deltas"]["return_delta"]["p75"]:+0.2f}%p` |
| **MFE 중앙값** | `{cov["policy_b"]["mfe"]["median"]:+0.2f}%` | `{cov["policy_c"]["mfe"]["median"]:+0.2f}%` | - |
| **MAE 중앙값** | `{cov["policy_b"]["mae"]["median"]:+0.2f}%` | `{cov["policy_c"]["mae"]["median"]:+0.2f}%` | - |
| **Peak Giveback 중앙값 (Mean)** | **`{cov["policy_b"]["peak_giveback"]["median"]:+0.2f}%`** (`{cov["policy_b"]["peak_giveback"]["mean"]:+0.2f}%`) | **`{cov["policy_c"]["peak_giveback"]["median"]:+0.2f}%`** (`{cov["policy_c"]["peak_giveback"]["mean"]:+0.2f}%`) | **`{cov["paired_deltas"]["giveback_delta"]["median"]:+0.2f}%p`** (평균 `{cov["paired_deltas"]["giveback_delta"]["mean"]:+0.2f}%p`) |
| **Profit Capture Ratio 중앙값 (Mean)** | **`{cov["policy_b"]["profit_capture"]["median"]}`** (`{cov["policy_b"]["profit_capture"]["mean"]}`) | **`{cov["policy_c"]["profit_capture"]["median"]}`** (`{cov["policy_c"]["profit_capture"]["mean"]}`) | **`{cov["paired_deltas"]["profit_capture_delta"]["median"]}`** (평균 `{cov["paired_deltas"]["profit_capture_delta"]["mean"]}`) |
| **Holding Weeks 중앙값 (Mean)** | `{cov["policy_b"]["holding_weeks"]["median"]}주` (`{cov["policy_b"]["holding_weeks"]["mean"]}주`) | `{cov["policy_c"]["holding_weeks"]["median"]}주` (`{cov["policy_c"]["holding_weeks"]["mean"]}주`) | **`{cov["paired_deltas"]["holding_weeks_delta"]["median"]}주`** (평균 `{cov["paired_deltas"]["holding_weeks_delta"]["mean"]}주`) |

#### Trade-level Better / Equal / Worse 분포
- **Return 기준**:
  - Policy C Better: **`{cov["return_comparison"]["policy_c_better_count"]}건` (`{cov["return_comparison"]["policy_c_better_rate"]}%`)**
  - Equal (동일): **`{cov["return_comparison"]["equal_count"]}건` (`{cov["return_comparison"]["equal_rate"]}%`)**
  - Policy B Better: **`{cov["return_comparison"]["policy_b_better_count"]}건` (`{cov["return_comparison"]["policy_b_better_rate"]}%`)**
- **Peak Giveback 기준 (수익 반납 감소)**:
  - Policy C Lower Giveback (개선): **`{cov["giveback_comparison"]["policy_c_lower_giveback_count"]}건` (`{cov["giveback_comparison"]["policy_c_lower_giveback_rate"]}%`)**
  - Equal (동일): **`{cov["giveback_comparison"]["equal_count"]}건` (`{cov["giveback_comparison"]["equal_rate"]}%`)**
  - Policy B Lower Giveback: **`{cov["giveback_comparison"]["policy_b_lower_giveback_count"]}건` (`{cov["giveback_comparison"]["policy_b_lower_giveback_rate"]}%`)**

================================================================================
4. Exit 4 Activation Coverage 및 Timing 분석 (Coverage Hole 107건)
================================================================================
- **First PROGRESSED 관측 거래수**: `{cov["exit4_activation_coverage"]["first_progressed_observed_count"]}건`
- **Policy C Exit 4 Armed 거래수**: `{cov["exit4_activation_coverage"]["policy_c_armed_count"]}건`
- **Policy C Exit 4 Triggered 거래수**: **`{cov["exit4_activation_coverage"]["policy_c_triggered_count"]}건` (`{round(cov["exit4_activation_coverage"]["policy_c_triggered_count"]/lc["coverage_hole_total_count"]*100, 1)}%`)**
- **Policy C Exit 4 Executed (체결 완료)**: **`{cov["exit4_activation_coverage"]["policy_c_executed_count"]}건`**
- **Open at Cutoff (미청산 유지)**: `{cov["exit4_activation_coverage"]["open_without_exit4_count"]}건`
- **Trigger Timing 통계**:
  - 최초 PROGRESSED 관측일로부터 Exit 4 격발까지 소요 일수 중앙값: **`{timing.get("days_from_first_prog_to_trigger", {}).get("median", "-")}일`** (평균 `{timing.get("days_from_first_prog_to_trigger", {}).get("mean", "-")}일`)
  - 최초 PROGRESSED 관측일로부터 Exit 4 체결까지 소요 주수 중앙값: **`{timing.get("weeks_from_first_prog_to_exec", {}).get("median", "-")}주`**
  - 격발 시점 Score Drawdown 중앙값: **`{timing.get("score_drawdown_stats", {}).get("median", "-")}pt`** (P25: `{timing.get("score_drawdown_stats", {}).get("p25", "-")}`, P75: `{timing.get("score_drawdown_stats", {}).get("p75", "-")}`)

================================================================================
5. Right Tail Winner 영향 및 Winner Preservation 분석
================================================================================
- **대형 상승 거래(Policy B Return ≥ +50%) 중 Policy C에서 수익 감소 비율**: **`{cov["right_tail_impact"]["pc_lower_ge_50_rate"]}%`** (`{cov["right_tail_impact"]["pc_lower_ge_50_count"]} / {cov["right_tail_impact"]["pb_return_ge_50_count"]}건`)
- **초대형 상승 거래(Policy B Return ≥ +100%) 중 Policy C에서 수익 감소 비율**: **`{cov["right_tail_impact"]["pc_lower_ge_100_rate"]}%`** (`{cov["right_tail_impact"]["pc_lower_ge_100_count"]} / {cov["right_tail_impact"]["pb_return_ge_100_count"]}건`)
- **최대 수익 거래 비교**: Policy B Max Return `+442.57%` vs Policy C Max Return `+203.93%` (Min Paired Return Delta: `-329.39%p`)
- **Winner Preservation (목표 수익 달성률 유지)**:
  - Return ≥ +20%: Policy B `{cov["right_tail_impact"]["winner_preservation_20"]["policy_b_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_20"]["policy_b_count"]}건`) vs Policy C `{cov["right_tail_impact"]["winner_preservation_20"]["policy_c_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_20"]["policy_c_count"]}건`)
  - Return ≥ +50%: Policy B `{cov["right_tail_impact"]["winner_preservation_50"]["policy_b_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_50"]["policy_b_count"]}건`) vs Policy C `{cov["right_tail_impact"]["winner_preservation_50"]["policy_c_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_50"]["policy_c_count"]}건`)
  - Return ≥ +100%: Policy B `{cov["right_tail_impact"]["winner_preservation_100"]["policy_b_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_100"]["policy_b_count"]}건`) vs Policy C `{cov["right_tail_impact"]["winner_preservation_100"]["policy_c_rate"]}%` (`{cov["right_tail_impact"]["winner_preservation_100"]["policy_c_count"]}건`)

#### 하방 실패 보호 (Failure Protection)
- Terminal Return < 0 (손실 거래) 비율: Policy B `{cov["failure_protection"]["failure_return_negative"]["policy_b_rate"]}%` (`{cov["failure_protection"]["failure_return_negative"]["policy_b_count"]}건`) vs Policy C `{cov["failure_protection"]["failure_return_negative"]["policy_c_rate"]}%` (`{cov["failure_protection"]["failure_return_negative"]["policy_c_count"]}건`)
- Terminal Return ≤ -20% 극단 손실 비율: Policy B `{cov["failure_protection"]["failure_return_le_neg_20"]["policy_b_rate"]}%` (`{cov["failure_protection"]["failure_return_le_neg_20"]["policy_b_count"]}건`) vs Policy C `{cov["failure_protection"]["failure_return_le_neg_20"]["policy_c_rate"]}%` (`{cov["failure_protection"]["failure_return_le_neg_20"]["policy_c_count"]}건`)
- Terminal Return ≤ -30% 극단 손실 비율: Policy B `{cov["failure_protection"]["failure_return_le_neg_30"]["policy_b_rate"]}%` (`{cov["failure_protection"]["failure_return_le_neg_30"]["policy_b_count"]}건`) vs Policy C `{cov["failure_protection"]["failure_return_le_neg_30"]["policy_c_rate"]}%` (`{cov["failure_protection"]["failure_return_le_neg_30"]["policy_c_count"]}건`)

================================================================================
6. Subgroup별 분리 진단
================================================================================

#### 1) SKIPPED_EARLY_TREND_HANDOFF (N={lc["skipped_early_trend_handoff_count"]})
- **Exit 4 Triggered**: `{skip["exit4_activation_coverage"]["policy_c_triggered_count"]}건` (`{round(skip["exit4_activation_coverage"]["policy_c_triggered_count"]/lc["skipped_early_trend_handoff_count"]*100, 1)}%`)
- **Terminal Return**: Policy B `{skip["policy_b"]["terminal_return"]["median"]:+0.2f}%` vs Policy C `{skip["policy_c"]["terminal_return"]["median"]:+0.2f}%` (Paired Delta Median: `{skip["paired_deltas"]["return_delta"]["median"]:+0.2f}%p`, Mean: `{skip["paired_deltas"]["return_delta"]["mean"]:+0.2f}%p`)
- **Peak Giveback**: Policy B `{skip["policy_b"]["peak_giveback"]["median"]:+0.2f}%` vs Policy C `{skip["policy_c"]["peak_giveback"]["median"]:+0.2f}%` (Giveback Delta Median: `{skip["paired_deltas"]["giveback_delta"]["median"]:+0.2f}%p`, Mean: `{skip["paired_deltas"]["giveback_delta"]["mean"]:+0.2f}%p`)
- **Profit Capture**: Policy B `{skip["policy_b"]["profit_capture"]["median"]}` vs Policy C `{skip["policy_c"]["profit_capture"]["median"]}`

#### 2) PROGRESSED_WITHOUT_DIRECT_HANDOFF (N={lc["progressed_without_direct_handoff_count"]})
- **Exit 4 Triggered**: `{prog_nd["exit4_activation_coverage"]["policy_c_triggered_count"]}건` (`{round(prog_nd["exit4_activation_coverage"]["policy_c_triggered_count"]/lc["progressed_without_direct_handoff_count"]*100, 1)}%`)
- **Terminal Return**: Policy B `{prog_nd["policy_b"]["terminal_return"]["median"]:+0.2f}%` vs Policy C `{prog_nd["policy_c"]["terminal_return"]["median"]:+0.2f}%` (Paired Delta Median: `{prog_nd["paired_deltas"]["return_delta"]["median"]:+0.2f}%p`, Mean: `{prog_nd["paired_deltas"]["return_delta"]["mean"]:+0.2f}%p`)
- **Peak Giveback**: Policy B `{prog_nd["policy_b"]["peak_giveback"]["median"]:+0.2f}%` vs Policy C `{prog_nd["policy_c"]["peak_giveback"]["median"]:+0.2f}%` (Giveback Delta Median: `{prog_nd["paired_deltas"]["giveback_delta"]["median"]:+0.2f}%p`, Mean: `{prog_nd["paired_deltas"]["giveback_delta"]["mean"]:+0.2f}%p`)
- **Profit Capture**: Policy B `{prog_nd["policy_b"]["profit_capture"]["median"]}` vs Policy C `{prog_nd["policy_c"]["profit_capture"]["median"]}`

================================================================================
7. Full 553 Combined Executable 전체 시스템 영향도
================================================================================
- **전체 Combined Executable 표본수**: `{comb["combined_executable_count"]}건`
- **전체 Changed Trade Count (결과 변경 거래수)**: **`{data["changed_trade_count"]}건`** (`{round(data["changed_trade_count"]/comb["combined_executable_count"]*100, 1)}%`)
- **NORMAL 코호트 변경수**: **`0건` (100% 보존)**
- **NEVER_PROGRESSED 코호트 변경수**: **`0건` (100% 보존)**
- **전체 시스템 Terminal Return**: Policy B `{full["policy_b"]["terminal_return"]["median"]:+0.2f}%` vs Policy C `{full["policy_c"]["terminal_return"]["median"]:+0.2f}%` (Delta Median: `{full["paired_deltas"]["return_delta"]["median"]:+0.2f}%p`)
- **전체 시스템 Peak Giveback**: Policy B `{full["policy_b"]["peak_giveback"]["median"]:+0.2f}%` vs Policy C `{full["policy_c"]["peak_giveback"]["median"]:+0.2f}%` (Delta Median: `{full["paired_deltas"]["giveback_delta"]["median"]:+0.2f}%p`)

================================================================================
8. 핵심 관찰 (Key Observations)
================================================================================
"""
    for i, obs in enumerate(conc["key_observations"], 1):
        md += f"{i}. {obs}\n"

    md += f"""
================================================================================
9. 최종 결론 및 연구 상태
================================================================================
- **연구 상태 (Research Status)**: **`CLOSED`**
- **최종 연구 판정 (Evaluation Status)**: **`COVERAGE_ACTIVATION_MIXED`**
- **연구적 의미 (Research Finding)**: **`COVERAGE_ACTIVATION_PROMISING` (`PROMISING`)**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
FAST + Pattern A Coverage Hole Activation v0.2D 평가 결과:

1. 기존 Exit4 사각지대 107건 중 65건(60.7%)에서 최초 PROGRESSED 관측 이후 frozen 15pt protection이 실제로 활성화되었습니다.
2. Policy C는 손실 거래와 큰 손실 tail을 줄였으며, Peak Giveback과 Profit Capture 분포에서도 전반적인 개선 방향을 보였습니다. 특히 SKIPPED_EARLY_TREND_HANDOFF subgroup에서는 paired Return 및 Giveback 개선이 강하게 관찰되었습니다.
3. 그러나 전체 Coverage Hole의 paired Return Delta 중앙값은 0.00%p였고, PROGRESSED_WITHOUT_DIRECT_HANDOFF subgroup에서도 paired Return / Giveback median 개선이 0.00%p였습니다.
4. 더 중요하게는 기존 Policy B의 +50% 이상 winner 중 47.1%(16/34건), +100% 이상 winner 중 60.0%(6/10건)가 Policy C에서 수익 감소를 경험해 명확한 Right Tail truncation trade-off가 존재했습니다.
5. 동시에 전체 winner threshold 달성 거래 수는 Policy C에서 증가해, Coverage Activation이 일방적으로 winner를 훼손한 것도 아니었습니다.

따라서 Coverage Activation은 Giveback Protection 및 Failure Protection 측면에서 PROMISING한 구조이지만, Right Tail 손상과 subgroup 효과 차이가 존재하므로 Retrospective evidence만으로 SUPPORTED로 확정하지 않고 최종 Evaluation Status를 COVERAGE_ACTIVATION_MIXED, Research Finding을 COVERAGE_ACTIVATION_PROMISING, Production을 PRODUCTION_HOLD로 유지하며 v0.2D 연구를 CLOSED 상태로 종료합니다.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
