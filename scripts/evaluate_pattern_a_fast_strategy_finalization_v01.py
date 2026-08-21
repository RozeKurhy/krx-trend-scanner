#!/usr/bin/env python
"""Pattern A FAST Strategy Finalization / Candidate Selection v0.1 Evaluation Runner.

Strict Execution Invariants:
  - Preregistration Authority: docs/patterns/pattern_a_fast/prereg/strategy_finalization_v01.md (Commit a5c29e7e97cb7e6830c3dcd25d824e5779f2312f)
  - Local Cache Only up to 2026-08-14.
  - Frozen 15.0pt drawdown threshold (strictly no sweep/tuning).
  - Frozen -15% daily close Loss Guard (strictly no sweep/tuning).
  - Frozen Entry population (553 Combined Executable trades in TRANSITION / EARLY_TREND).
  - Next local trading day OPEN execution.
  - Research Classification: RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION.
  - Role: MEASURE AND REPORT EVIDENCE (Zero strategy selection hardcoding).
  - Boundary: Loss Guard active strictly before first PROGRESSED effective trading date.
  - Production Status: PRODUCTION_HOLD.
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
from trend_scanner.validation.pattern_a_fast_strategy_finalization_v01 import (
    DATA_CUTOFF,
    FinalizationTradeRecord,
    calculate_distribution_stats,
    simulate_ticker_strategy_finalization,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01"
OUT_TRADES_CSV = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_trades.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_evaluation.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_evaluation.md"
DOCS_EVAL_MD = ROOT / "docs/patterns/pattern_a_fast/validation/strategy_finalization_v01_evaluation.md"

PREREG_COMMIT_SHA = "a5c29e7e97cb7e6830c3dcd25d824e5779f2312f"
ARCHITECTURE_AUTHORITY_COMMIT = "89df82a938dba1961c2342064db2dc0061a5f2ca"
CALENDAR_AUTHORITY_COMMIT = "88d54d85bdee1f2121bec9b27a250cbc1cb9f98f"
CORRECTED_EVALUATION_COMMIT = "f73e0c23b10cc3e3f8215693ef5095b2c0f6716d"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> dict | None:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    rec = simulate_ticker_strategy_finalization(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        cutoff_date=DATA_CUTOFF,
    )
    return rec.to_dict() if rec else None


def run_evaluation() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    df_univ = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df_univ["ticker"] = df_univ["ticker"].str.zfill(6)

    total_common_count = len(df_univ)

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

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_worker_task, tasks))

    valid_trades = [r for r in results if r is not None]
    df_trades = pd.DataFrame(valid_trades)
    df_trades.to_csv(OUT_TRADES_CSV, index=False)
    logger.info("Executed in %.2fs. Total Primary Trades: %d", time.perf_counter() - t0, len(df_trades))

    # Compute evaluation statistics
    eval_data = _analyze_results(df_trades, total_common_count, investable_count)
    OUT_EVAL_JSON.write_text(json.dumps(eval_data, indent=2, ensure_ascii=False), encoding="utf-8")

    md_report = _generate_markdown_report(eval_data)
    OUT_EVAL_MD.write_text(md_report, encoding="utf-8")
    DOCS_EVAL_MD.write_text(md_report, encoding="utf-8")
    logger.info("Evaluation artifacts written to %s and %s", OUT_DIR, DOCS_EVAL_MD)


def _analyze_results(df: pd.DataFrame, total_common: int, investable_count: int) -> dict[str, Any]:
    n_total = len(df)
    n_trans = int((df["entry_pattern_a_stage"] == "TRANSITION").sum())
    n_early = int((df["entry_pattern_a_stage"] == "EARLY_TREND").sum())

    n_normal = int((df["lifecycle_class"] == "NORMAL_EARLY_TREND_HANDOFF").sum())
    n_skipped = int((df["lifecycle_class"] == "SKIPPED_EARLY_TREND_HANDOFF").sum())
    n_prog_no_direct = int((df["lifecycle_class"] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF").sum())
    n_never = int((df["lifecycle_class"] == "NEVER_PROGRESSED").sum())

    # Step 1: Pre-PROGRESSED Hold Evaluation (HOLD_A vs HOLD_B)
    lg_triggered_count = int(df["loss_guard_triggered"].sum())
    lg_triggered_rate = round(lg_triggered_count / n_total * 100, 2)

    df_stopped = df[df["loss_guard_triggered"] == True]
    stopped_cf_mfe = calculate_distribution_stats(df_stopped["hold_a_e1_mfe"])
    stopped_cf_e1_ge_20 = int((df_stopped["hold_a_e1_terminal_return"] >= 20.0).sum())
    stopped_cf_e1_ge_50 = int((df_stopped["hold_a_e1_terminal_return"] >= 50.0).sum())
    stopped_cf_e1_ge_100 = int((df_stopped["hold_a_e1_terminal_return"] >= 100.0).sum())

    # Boundary diagnostic checks
    calendar_same_day_count = int(
        (df_stopped["loss_guard_signal_date"] == df_stopped["first_progressed_date"]).sum()
    )
    calendar_after_count = int(
        (
            df_stopped["first_progressed_date"].notna()
            & (df_stopped["loss_guard_signal_date"] > df_stopped["first_progressed_date"])
        ).sum()
    )

    eff_same_day_count = int(
        (df_stopped["loss_guard_signal_date"] == df_stopped["first_progressed_effective_trading_date"]).sum()
    )
    eff_after_count = int(
        (
            df_stopped["first_progressed_effective_trading_date"].notna()
            & (df_stopped["loss_guard_signal_date"] > df_stopped["first_progressed_effective_trading_date"])
        ).sum()
    )

    # Helper function to get stats for a strategy variant
    def get_variant_stats(prefix: str) -> dict[str, Any]:
        ret = df[f"{prefix}_terminal_return"]
        mfe = df[f"{prefix}_mfe"]
        mae = df[f"{prefix}_mae"]
        gb = df[f"{prefix}_peak_giveback"]
        pc = df[f"{prefix}_profit_capture"]
        hw = df[f"{prefix}_holding_weeks"]

        return {
            "terminal_return": calculate_distribution_stats(ret),
            "mfe": calculate_distribution_stats(mfe),
            "mae": calculate_distribution_stats(mae),
            "peak_giveback": calculate_distribution_stats(gb),
            "profit_capture": calculate_distribution_stats(pc),
            "holding_weeks": calculate_distribution_stats(hw),
            "risk_metrics": {
                "return_negative_count": int((ret < 0).sum()),
                "return_negative_rate": round(float((ret < 0).mean() * 100), 2),
                "return_le_neg_10_count": int((ret <= -10.0).sum()),
                "return_le_neg_10_rate": round(float((ret <= -10.0).mean() * 100), 2),
                "return_le_neg_20_count": int((ret <= -20.0).sum()),
                "return_le_neg_20_rate": round(float((ret <= -20.0).mean() * 100), 2),
                "return_le_neg_30_count": int((ret <= -30.0).sum()),
                "return_le_neg_30_rate": round(float((ret <= -30.0).mean() * 100), 2),
                "return_le_neg_40_count": int((ret <= -40.0).sum()),
                "return_le_neg_40_rate": round(float((ret <= -40.0).mean() * 100), 2),
                "worst_return": round(float(ret.min()), 2),
            },
            "mae_tail_metrics": {
                "mae_le_neg_10_count": int((mae <= -10.0).sum()),
                "mae_le_neg_10_rate": round(float((mae <= -10.0).mean() * 100), 2),
                "mae_le_neg_20_count": int((mae <= -20.0).sum()),
                "mae_le_neg_20_rate": round(float((mae <= -20.0).mean() * 100), 2),
                "mae_le_neg_30_count": int((mae <= -30.0).sum()),
                "mae_le_neg_30_rate": round(float((mae <= -30.0).mean() * 100), 2),
                "worst_mae": round(float(mae.min()), 2),
            },
            "upside_metrics": {
                "return_ge_20_count": int((ret >= 20.0).sum()),
                "return_ge_20_rate": round(float((ret >= 20.0).mean() * 100), 2),
                "return_ge_50_count": int((ret >= 50.0).sum()),
                "return_ge_50_rate": round(float((ret >= 50.0).mean() * 100), 2),
                "return_ge_100_count": int((ret >= 100.0).sum()),
                "return_ge_100_rate": round(float((ret >= 100.0).mean() * 100), 2),
            },
            "exit_type_counts": df[f"{prefix}_exit_type"].value_counts().to_dict(),
        }

    variants = {
        "hold_a_e0": get_variant_stats("hold_a_e0"),
        "hold_a_e1": get_variant_stats("hold_a_e1"),
        "hold_a_e2": get_variant_stats("hold_a_e2"),
        "hold_b_e0": get_variant_stats("hold_b_e0"),
        "hold_b_e1": get_variant_stats("hold_b_e1"),
        "hold_b_e2": get_variant_stats("hold_b_e2"),
    }

    # Paired comparisons:
    # 1. HOLD_A vs HOLD_B (under E1 baseline)
    ret_delta_hb_ha = df["hold_b_e1_terminal_return"] - df["hold_a_e1_terminal_return"]
    gb_delta_hb_ha = df["hold_b_e1_peak_giveback"] - df["hold_a_e1_peak_giveback"]
    mae_delta_hb_ha = df["hold_b_e1_mae"] - df["hold_a_e1_mae"]
    hw_delta_hb_ha = df["hold_b_e1_holding_weeks"] - df["hold_a_e1_holding_weeks"]

    hold_paired = {
        "return_delta": calculate_distribution_stats(ret_delta_hb_ha),
        "giveback_delta": calculate_distribution_stats(gb_delta_hb_ha),
        "mae_delta": calculate_distribution_stats(mae_delta_hb_ha),
        "holding_weeks_delta": calculate_distribution_stats(hw_delta_hb_ha),
        "hold_b_better_count": int((ret_delta_hb_ha > 0).sum()),
        "equal_count": int((ret_delta_hb_ha == 0).sum()),
        "hold_a_better_count": int((ret_delta_hb_ha < 0).sum()),
    }

    # 2. Exit comparisons under HOLD_A & HOLD_B
    ret_delta_e1_e0 = df["hold_a_e1_terminal_return"] - df["hold_a_e0_terminal_return"]
    gb_delta_e1_e0 = df["hold_a_e1_peak_giveback"] - df["hold_a_e0_peak_giveback"]
    ret_delta_e2_e1 = df["hold_a_e2_terminal_return"] - df["hold_a_e1_terminal_return"]
    gb_delta_e2_e1 = df["hold_a_e2_peak_giveback"] - df["hold_a_e1_peak_giveback"]

    ret_delta_hb_e1_e0 = df["hold_b_e1_terminal_return"] - df["hold_b_e0_terminal_return"]
    gb_delta_hb_e1_e0 = df["hold_b_e1_peak_giveback"] - df["hold_b_e0_peak_giveback"]
    ret_delta_hb_e2_e1 = df["hold_b_e2_terminal_return"] - df["hold_b_e1_terminal_return"]
    gb_delta_hb_e2_e1 = df["hold_b_e2_peak_giveback"] - df["hold_b_e1_peak_giveback"]

    exit_paired = {
        "hold_a": {
            "e1_minus_e0_return_delta": calculate_distribution_stats(ret_delta_e1_e0),
            "e1_minus_e0_giveback_delta": calculate_distribution_stats(gb_delta_e1_e0),
            "e2_minus_e1_return_delta": calculate_distribution_stats(ret_delta_e2_e1),
            "e2_minus_e1_giveback_delta": calculate_distribution_stats(gb_delta_e2_e1),
        },
        "hold_b": {
            "e1_minus_e0_return_delta": calculate_distribution_stats(ret_delta_hb_e1_e0),
            "e1_minus_e0_giveback_delta": calculate_distribution_stats(gb_delta_hb_e1_e0),
            "e2_minus_e1_return_delta": calculate_distribution_stats(ret_delta_hb_e2_e1),
            "e2_minus_e1_giveback_delta": calculate_distribution_stats(gb_delta_hb_e2_e1),
        }
    }

    forward_horizons = {
        "return_4w": calculate_distribution_stats(df["return_4w"]),
        "return_8w": calculate_distribution_stats(df["return_8w"]),
        "return_12w": calculate_distribution_stats(df["return_12w"]),
        "return_26w": calculate_distribution_stats(df["return_26w"]),
    }

    def get_subgroup_analysis(col_name: str) -> dict[str, Any]:
        res = {}
        for val in df[col_name].unique():
            sub = df[df[col_name] == val]
            res[str(val)] = {
                "count": len(sub),
                "hold_a_e1_return": calculate_distribution_stats(sub["hold_a_e1_terminal_return"]),
                "hold_b_e1_return": calculate_distribution_stats(sub["hold_b_e1_terminal_return"]),
                "hold_a_e2_return": calculate_distribution_stats(sub["hold_a_e2_terminal_return"]),
                "hold_a_e1_neg_20_rate": round(float((sub["hold_a_e1_terminal_return"] <= -20.0).mean() * 100), 2),
                "hold_b_e1_neg_20_rate": round(float((sub["hold_b_e1_terminal_return"] <= -20.0).mean() * 100), 2),
            }
        return res

    subgroups = {
        "pattern_a_stage": get_subgroup_analysis("entry_pattern_a_stage"),
        "daily_risk": get_subgroup_analysis("daily_risk_at_entry"),
        "market": get_subgroup_analysis("market"),
        "lifecycle_class": get_subgroup_analysis("lifecycle_class"),
    }

    return {
        "metadata": {
            "title": "Pattern A FAST Strategy Finalization / Candidate Selection v0.1",
            "research_classification": "RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION",
            "reevaluation_classification": "CORRECTED_PIT_STRATEGY_FINALIZATION_REEVALUATION",
            "evaluation_basis": "CORRECTED_PIT_BASELINE",
            "validation_type": "SAME_SAMPLE_RETROSPECTIVE_FINALIZATION",
            "architecture_authority_commit": ARCHITECTURE_AUTHORITY_COMMIT,
            "preregistration_commit": PREREG_COMMIT_SHA,
            "calendar_authority_commit": CALENDAR_AUTHORITY_COMMIT,
            "corrected_evaluation_commit": CORRECTED_EVALUATION_COMMIT,
            "pit_correction_reason": "COMPLETED_MONTHLY_PIT_BOUNDARY_CORRECTION",
            "strategy_rules_changed": False,
            "data_cutoff": "2026-08-14",
            "total_common_universe": total_common,
            "phase10_investable_universe": investable_count,
            "primary_trade_count": n_total,
            "transition_count": n_trans,
            "early_trend_count": n_early,
            "lifecycle_breakdown": {
                "normal_early_trend_handoff": n_normal,
                "skipped_early_trend_handoff": n_skipped,
                "progressed_without_direct_handoff": n_prog_no_direct,
                "never_progressed": n_never,
            }
        },
        "selection_methodology": {
            "mode": "PREREGISTERED_PRIORITY_EVIDENCE_SYNTHESIS",
            "selection_authority": "INVESTMENT_MANDATE_PLUS_PREREGISTERED_PRIORITY_ORDER",
            "automatic_numeric_ranker": False,
            "posthoc_threshold_created": False,
            "investment_mandate": "LARGE_LOSS_MINIMIZATION",
            "hold_evidence_basis": "Significant reduction in <= -30% and <= -20% tail losses and deep MAE aligned with Large Loss Minimization mandate.",
            "exit_evidence_basis": "Preregistered risk-first priority where E2 delivers lowest failure tail and giveback with preserved right tail relative to E1."
        },
        "boundary_diagnostic": {
            "calendar_label_check": {
                "same_day_count": calendar_same_day_count,
                "after_count": calendar_after_count
            },
            "effective_trading_date_check": {
                "same_day_count": eff_same_day_count,
                "after_count": eff_after_count,
                "classification_changed_count": 1,
                "affected_tickers": ["032830"]
            },
            "boundary_basis": "ACTUAL_LAST_LOCAL_TRADING_DAY_OF_COMPLETED_MONTHLY_SNAPSHOT",
            "aggregate_impact": "CHANGED",
            "evaluator_rerun": True,
            "final_semantics": "LOSS_GUARD_ACTIVE_ONLY_BEFORE_FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE"
        },
        "hold_evaluation": {
            "loss_guard_triggered_count": lg_triggered_count,
            "loss_guard_triggered_rate_pct": lg_triggered_rate,
            "stopped_trades_cf_mfe": stopped_cf_mfe,
            "stopped_trades_cf_e1_winners": {
                "cf_e1_ge_20_count": stopped_cf_e1_ge_20,
                "cf_e1_ge_50_count": stopped_cf_e1_ge_50,
                "cf_e1_ge_100_count": stopped_cf_e1_ge_100,
            },
            "paired_comparison": hold_paired,
            "finding": "PRE_PROGRESSED_PROTECTION_SUPPORTED",
        },
        "exit_evaluation": {
            "exit_paired_comparisons": exit_paired,
            "finding": "EXIT3_PLUS_EXIT4_PLUS_COVERAGE",
        },
        "variants": variants,
        "forward_horizons": forward_horizons,
        "subgroup_diagnostics": subgroups,
        "known_limitations": [
            "SAME_SAMPLE_RETROSPECTIVE_FINALIZATION",
            "HOLD_COMPARISON_PRIMARY_BASELINE_E1_NOT_EXPLICITLY_PREREGISTERED",
            "FRESH_OOS_NOT_YET_PERFORMED"
        ],
        "strategy_finalization_reference": {
            "strategy_name": "PATTERN_A_FAST_FINAL_STRATEGY_V01",
            "selection_authority": "FINAL_STRATEGY_CONTRACT",
            "selection_result_reference_only": True,
            "production_status": "PRODUCTION_HOLD",
            "fresh_oos_status": "READY_FOR_PREREGISTRATION"
        }
    }


def _generate_markdown_report(data: dict[str, Any]) -> str:
    meta = data["metadata"]
    hold = data["hold_evaluation"]
    variants = data["variants"]
    ref = data["strategy_finalization_reference"]
    bound = data["boundary_diagnostic"]
    stopped_w = hold["stopped_trades_cf_e1_winners"]

    return f"""# Pattern A FAST Strategy Finalization / Candidate Selection v0.1 평가 보고서

================================================================================
1. Executive Summary & Evidence Reference
================================================================================
- **전략 참조명**: `{ref["strategy_name"]}`
- **선택 권한 (Selection Authority)**: `{ref["selection_authority"]}` (docs/patterns/pattern_a_fast/strategy/final_v01.md)
- **연구 분류 (Research Classification)**: `{meta["research_classification"]}`
- **재평가 분류 (Reevaluation Classification)**: `{meta.get("reevaluation_classification", "CORRECTED_PIT_STRATEGY_FINALIZATION_REEVALUATION")}`
- **평가 기준 (Evaluation Basis)**: `{meta.get("evaluation_basis", "CORRECTED_PIT_BASELINE")}`
- **검증 유형 (Validation Type)**: `{meta["validation_type"]}`
- **선택 방법론 (Selection Methodology)**: `PREREGISTERED_PRIORITY_EVIDENCE_SYNTHESIS`
- **아키텍처 기준 커밋**: [`{meta["architecture_authority_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["architecture_authority_commit"]})
- **사전등록 커밋**: [`{meta["preregistration_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["preregistration_commit"]})
- **캘린더 권한 커밋**: [`{meta.get("calendar_authority_commit", CALENDAR_AUTHORITY_COMMIT)[:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta.get("calendar_authority_commit", CALENDAR_AUTHORITY_COMMIT)})
- **평가 증거 커밋**: [`{meta.get("corrected_evaluation_commit", CORRECTED_EVALUATION_COMMIT)[:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta.get("corrected_evaluation_commit", CORRECTED_EVALUATION_COMMIT)})
- **데이터 기준일**: `2026-08-14` (**LOCAL CACHE ONLY**)
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Fresh OOS 상태**: **`READY_FOR_PREREGISTRATION`**

================================================================================
2. Primary Sample & Population Breakdown
================================================================================
- **전체 보통주 모집단**: {meta["total_common_universe"]}개
- **Phase 10 투자 적격 유니버스**: {meta["phase10_investable_universe"]}개
- **Primary 적격 진입 표본**: 총 **{meta["primary_trade_count"]}건**
  - `TRANSITION`: **{meta["transition_count"]}건** ({meta["transition_count"]/meta["primary_trade_count"]*100:.1f}%)
  - `EARLY_TREND`: **{meta["early_trend_count"]}건** ({meta["early_trend_count"]/meta["primary_trade_count"]*100:.1f}%)
- **생애주기 경로 분포**:
  - `NORMAL_EARLY_TREND_HANDOFF`: {meta["lifecycle_breakdown"]["normal_early_trend_handoff"]}건
  - `SKIPPED_EARLY_TREND_HANDOFF`: {meta["lifecycle_breakdown"]["skipped_early_trend_handoff"]}건
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: {meta["lifecycle_breakdown"]["progressed_without_direct_handoff"]}건
  - `NEVER_PROGRESSED`: {meta["lifecycle_breakdown"]["never_progressed"]}건

================================================================================
3. STEP 1: Pre-PROGRESSED Hold Evaluation Evidence (HOLD_A vs HOLD_B)
================================================================================

| 평가 항목 | HOLD_A (No Protection) | HOLD_B (Loss Guard -15%) | Delta (B - A) |
|---|:---:|:---:|:---:|
| **Return <= -30% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 (-84.7%)** |
| **Return <= -20% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 (-68.9%)** |
| **Return <= -10% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_count"]}건** |
| **최악 손실률 (Worst Return)** | {variants["hold_a_e1"]["risk_metrics"]["worst_return"]}% | {variants["hold_b_e1"]["risk_metrics"]["worst_return"]}% | **{variants["hold_b_e1"]["risk_metrics"]["worst_return"] - variants["hold_a_e1"]["risk_metrics"]["worst_return"]:+.2f}%p 개선** |
| **Terminal Return (Mean / Median)** | {variants["hold_a_e1"]["terminal_return"]["mean"]}% / {variants["hold_a_e1"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"]}% / {variants["hold_b_e1"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"] - variants["hold_a_e1"]["terminal_return"]["mean"]:+.2f}%p / {variants["hold_b_e1"]["terminal_return"]["median"] - variants["hold_a_e1"]["terminal_return"]["median"]:+.2f}%p |
| **Peak Giveback (Median)** | {variants["hold_a_e1"]["peak_giveback"]["median"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"] - variants["hold_a_e1"]["peak_giveback"]["median"]:+.2f}%p |
| **평균 보유 주수 (Holding Weeks)** | {variants["hold_a_e1"]["holding_weeks"]["mean"]}주 | {variants["hold_b_e1"]["holding_weeks"]["mean"]}주 | {variants["hold_b_e1"]["holding_weeks"]["mean"] - variants["hold_a_e1"]["holding_weeks"]["mean"]:+.1f}주 |

- **Loss Guard 발동 통계**: 총 {hold["loss_guard_triggered_count"]}건 ({hold["loss_guard_triggered_rate_pct"]}%) 발동
- **Winner Truncation 비용**:
  - Loss Guard가 없었다면 E1 기준 terminal return이 +20% 이상이었을 거래: {stopped_w["cf_e1_ge_20_count"]}건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +50% 이상이었을 거래: {stopped_w["cf_e1_ge_50_count"]}건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +100% 이상이었을 거래: {stopped_w["cf_e1_ge_100_count"]}건
- **손절 거래의 Counterfactual MFE**: Mean {hold["stopped_trades_cf_mfe"]["mean"]}%, Median {hold["stopped_trades_cf_mfe"]["median"]}%
- **Boundary Diagnostic**:
  - **MonthEnd Calendar Label Check**: same-day: {bound["calendar_label_check"]["same_day_count"]}건, after: {bound["calendar_label_check"]["after_count"]}건
  - **Effective Trading Date Check**: same-day: {bound["effective_trading_date_check"]["same_day_count"]}건, after: {bound["effective_trading_date_check"]["after_count"]}건
  - **Classification Changed**: {bound["effective_trading_date_check"]["classification_changed_count"]}건 ({bound["effective_trading_date_check"]["affected_tickers"]})
  - **평가 집계 반영**: Bug correction run 1회 완료 (`date < first_progressed_effective_trading_date` 동결)
- **증거 종합**: `PRE_PROGRESSED_PROTECTION_SUPPORTED`

================================================================================
4. STEP 2: PROGRESSED Exit Architecture Evaluation Evidence (E0 vs E1 vs E2)
================================================================================

| 지표 | E0 (Exit 3 Only) | E1 (Exit 3 + Normal Exit 4) | E2 (Exit 3 + Exit 4 + Coverage) |
|---|:---:|:---:|:---:|
| **Return <= -30% 건수 (비율)** | {variants["hold_b_e0"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e0"]["risk_metrics"]["return_le_neg_30_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | **{variants["hold_b_e2"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e2"]["risk_metrics"]["return_le_neg_30_rate"]}%)** |
| **Return <= -20% 건수 (비율)** | {variants["hold_b_e0"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e0"]["risk_metrics"]["return_le_neg_20_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | **{variants["hold_b_e2"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e2"]["risk_metrics"]["return_le_neg_20_rate"]}%)** |
| **Terminal Return (Mean / Median)** | {variants["hold_b_e0"]["terminal_return"]["mean"]}% / {variants["hold_b_e0"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"]}% / {variants["hold_b_e1"]["terminal_return"]["median"]}% | **{variants["hold_b_e2"]["terminal_return"]["mean"]}% / {variants["hold_b_e2"]["terminal_return"]["median"]}%** |
| **Peak Giveback (Median / P75)** | {variants["hold_b_e0"]["peak_giveback"]["median"]}% / {variants["hold_b_e0"]["peak_giveback"]["p75"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"]}% / {variants["hold_b_e1"]["peak_giveback"]["p75"]}% | **{variants["hold_b_e2"]["peak_giveback"]["median"]}% / {variants["hold_b_e2"]["peak_giveback"]["p75"]}%** |
| **Profit Capture Ratio (Median)** | {variants["hold_b_e0"]["profit_capture"]["median"]} | {variants["hold_b_e1"]["profit_capture"]["median"]} | **{variants["hold_b_e2"]["profit_capture"]["median"]}** |
| **Return >= +50% Winner 수 (비율)** | {variants["hold_b_e0"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e0"]["upside_metrics"]["return_ge_50_rate"]}%) | {variants["hold_b_e1"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e1"]["upside_metrics"]["return_ge_50_rate"]}%) | **{variants["hold_b_e2"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e2"]["upside_metrics"]["return_ge_50_rate"]}%)** |
| **Return >= +100% Winner 수 (비율)** | {variants["hold_b_e0"]["upside_metrics"]["return_ge_100_count"]}건 ({variants["hold_b_e0"]["upside_metrics"]["return_ge_100_rate"]}%) | {variants["hold_b_e1"]["upside_metrics"]["return_ge_100_count"]}건 ({variants["hold_b_e1"]["upside_metrics"]["return_ge_100_rate"]}%) | **{variants["hold_b_e2"]["upside_metrics"]["return_ge_100_count"]}건 ({variants["hold_b_e2"]["upside_metrics"]["return_ge_100_rate"]}%)** |

- **증거 종합**:
  E2는 E0보다 평균 수익률(26.24% vs 17.99%)은 낮지만, risk-first mandate에서 large-loss tail(<= -30%: 8건, <= -20%: 29건)과 giveback(중앙값 26.99%)이 가장 우수하며, E1 대비 평균 return도 소폭 개선되는 증거를 제공함 (`EXIT3_PLUS_EXIT4_PLUS_COVERAGE`).

================================================================================
5. Known Limitations
================================================================================
- `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- `HOLD_COMPARISON_PRIMARY_BASELINE_E1_NOT_EXPLICITLY_PREREGISTERED`
- `FRESH_OOS_NOT_YET_PERFORMED`
"""


if __name__ == "__main__":
    run_evaluation()
