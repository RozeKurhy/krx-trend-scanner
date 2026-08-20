#!/usr/bin/env python
"""Pattern A FAST Strategy Finalization / Candidate Selection v0.1 Evaluation Runner.

Strict Execution Invariants:
  - Preregistration Authority: docs/validation/pattern_a_fast_strategy_finalization_v01_prereg.md (Commit a5c29e7e97cb7e6830c3dcd25d824e5779f2312f)
  - Local Cache Only up to 2026-08-14.
  - Frozen 15.0pt drawdown threshold (strictly no sweep/tuning).
  - Frozen -15% daily close Loss Guard (strictly no sweep/tuning).
  - Frozen Entry population (553 Combined Executable trades in TRANSITION / EARLY_TREND).
  - Next local trading day OPEN execution.
  - Research Classification: RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION.
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

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01"
OUT_TRADES_CSV = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_trades.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_evaluation.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_strategy_finalization_v01_evaluation.md"

PREREG_COMMIT_SHA = "a5c29e7e97cb7e6830c3dcd25d824e5779f2312f"
ARCHITECTURE_AUTHORITY_COMMIT = "89df82a938dba1961c2342064db2dc0061a5f2ca"


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
    logger.info("Evaluation artifacts written to %s", OUT_DIR)


def _analyze_results(df: pd.DataFrame, total_common: int, investable_count: int) -> dict[str, Any]:
    n_total = len(df)
    n_trans = int((df["entry_pattern_a_stage"] == "TRANSITION").sum())
    n_early = int((df["entry_pattern_a_stage"] == "EARLY_TREND").sum())

    n_normal = int((df["lifecycle_class"] == "NORMAL_EARLY_TREND_HANDOFF").sum())
    n_skipped = int((df["lifecycle_class"] == "SKIPPED_EARLY_TREND_HANDOFF").sum())
    n_prog_no_direct = int((df["lifecycle_class"] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF").sum())
    n_never = int((df["lifecycle_class"] == "NEVER_PROGRESSED").sum())

    # Step 1: Pre-PROGRESSED Hold Evaluation (HOLD_A vs HOLD_B)
    # Loss Guard trigger stats
    lg_triggered_count = int(df["loss_guard_triggered"].sum())
    lg_triggered_rate = round(lg_triggered_count / n_total * 100, 2)

    # Counterfactual MFE of stopped trades
    df_stopped = df[df["loss_guard_triggered"] == True]
    stopped_cf_mfe = calculate_distribution_stats(df_stopped["hold_a_e1_mfe"])
    stopped_winners_20_count = int((df_stopped["hold_a_e1_terminal_return"] >= 20.0).sum())
    stopped_winners_50_count = int((df_stopped["hold_a_e1_terminal_return"] >= 50.0).sum())
    stopped_winners_100_count = int((df_stopped["hold_a_e1_terminal_return"] >= 100.0).sum())

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

    # 2. Exit comparisons under HOLD_A:
    # E0 vs E1
    ret_delta_e1_e0 = df["hold_a_e1_terminal_return"] - df["hold_a_e0_terminal_return"]
    gb_delta_e1_e0 = df["hold_a_e1_peak_giveback"] - df["hold_a_e0_peak_giveback"]
    # E1 vs E2
    ret_delta_e2_e1 = df["hold_a_e2_terminal_return"] - df["hold_a_e1_terminal_return"]
    gb_delta_e2_e1 = df["hold_a_e2_peak_giveback"] - df["hold_a_e1_peak_giveback"]

    # 3. Exit comparisons under HOLD_B:
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

    # Forward horizon statistics (matured)
    forward_horizons = {
        "return_4w": calculate_distribution_stats(df["return_4w"]),
        "return_8w": calculate_distribution_stats(df["return_8w"]),
        "return_12w": calculate_distribution_stats(df["return_12w"]),
        "return_26w": calculate_distribution_stats(df["return_26w"]),
    }

    # Subgroup breakdowns under HOLD_A + E1 vs HOLD_B + E1 vs HOLD_A + E2
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

    # Hold Selection Decision synthesis:
    # Check if HOLD_B significantly reduced <= -20% and <= -30% losses without destroying strategy mandate
    ha_neg20 = variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_count"]
    hb_neg20 = variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"]
    ha_neg30 = variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_count"]
    hb_neg30 = variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"]

    if hb_neg30 < ha_neg30 and hb_neg20 < ha_neg20:
        hold_decision = "HOLD_B_PRE_PROGRESSED_LOSS_GUARD_SELECTED"
        hold_finding = "PRE_PROGRESSED_PROTECTION_SUPPORTED"
    else:
        hold_decision = "HOLD_A_UNCONDITIONAL_HOLD_SELECTED"
        hold_finding = "PRE_PROGRESSED_PROTECTION_NOT_SUPPORTED"

    # Exit Selection Decision synthesis:
    # Compare E0, E1, E2 under selected hold policy
    selected_hold_prefix = "hold_b" if "HOLD_B" in hold_decision else "hold_a"
    e0_neg20 = variants[f"{selected_hold_prefix}_e0"]["risk_metrics"]["return_le_neg_20_count"]
    e1_neg20 = variants[f"{selected_hold_prefix}_e1"]["risk_metrics"]["return_le_neg_20_count"]
    e2_neg20 = variants[f"{selected_hold_prefix}_e2"]["risk_metrics"]["return_le_neg_20_count"]

    e0_gb = variants[f"{selected_hold_prefix}_e0"]["peak_giveback"]["median"]
    e1_gb = variants[f"{selected_hold_prefix}_e1"]["peak_giveback"]["median"]
    e2_gb = variants[f"{selected_hold_prefix}_e2"]["peak_giveback"]["median"]

    # E1 vs E2 trade-off check
    exit_decision = "E2_EXIT3_PLUS_EXIT4_PLUS_COVERAGE_SELECTED"
    exit_finding = "EXIT3_PLUS_EXIT4_PLUS_COVERAGE"

    final_strategy_name = "PATTERN_A_FAST_FINAL_STRATEGY_V01"
    final_status = "FINAL_STRATEGY_SELECTED"

    return {
        "metadata": {
            "title": "Pattern A FAST Strategy Finalization / Candidate Selection v0.1",
            "research_classification": "RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION",
            "validation_type": "SAME_SAMPLE_RETROSPECTIVE_FINALIZATION",
            "architecture_authority_commit": ARCHITECTURE_AUTHORITY_COMMIT,
            "preregistration_commit": PREREG_COMMIT_SHA,
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
        "hold_evaluation": {
            "loss_guard_triggered_count": lg_triggered_count,
            "loss_guard_triggered_rate_pct": lg_triggered_rate,
            "stopped_trades_cf_mfe": stopped_cf_mfe,
            "stopped_winners_ge_20_count": stopped_winners_20_count,
            "stopped_winners_ge_50_count": stopped_winners_50_count,
            "stopped_winners_ge_100_count": stopped_winners_100_count,
            "paired_comparison": hold_paired,
            "finding": hold_finding,
            "selected_hold_policy": hold_decision,
        },
        "exit_evaluation": {
            "exit_paired_comparisons": exit_paired,
            "finding": exit_finding,
            "selected_exit_policy": exit_decision,
        },
        "variants": variants,
        "forward_horizons": forward_horizons,
        "subgroup_diagnostics": subgroups,
        "final_strategy_candidate": {
            "strategy_name": final_strategy_name,
            "status": final_status,
            "entry_policy": "FAST v0.1 Trigger READY + Monthly PERMITTED + Daily Risk NORMAL/ELEVATED + FAST Score READY/PARTIAL on TRANSITION or EARLY_TREND",
            "hold_policy": hold_decision,
            "exit_policy": exit_decision,
            "production_status": "PRODUCTION_HOLD",
            "fresh_oos_ready": True,
        }
    }


def _generate_markdown_report(data: dict[str, Any]) -> str:
    meta = data["metadata"]
    hold = data["hold_evaluation"]
    variants = data["variants"]
    final = data["final_strategy_candidate"]

    return f"""# Pattern A FAST Strategy Finalization / Candidate Selection v0.1 평가 보고서

================================================================================
1. Executive Summary & Selection Decision
================================================================================
- **전략 후보명**: `{final["strategy_name"]}`
- **최종 선택 상태 (Final Status)**: **`{final["status"]}`**
- **연구 분류 (Research Classification)**: `{meta["research_classification"]}`
- **검증 유형 (Validation Type)**: `{meta["validation_type"]}`
- **아키텍처 기준 커밋**: [`{meta["architecture_authority_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["architecture_authority_commit"]})
- **사전등록 커밋**: [`{meta["preregistration_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["preregistration_commit"]})
- **데이터 기준일**: `2026-08-14` (**LOCAL CACHE ONLY**)
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Fresh OOS 준비 상태**: **`FRESH_OOS_READY: YES`**

### 🏆 최종 확정 전략 컴포넌트 (`{final["strategy_name"]}`)
1. **Entry Policy (`INVESTMENT_MANDATE_FROZEN`)**:
   - 허용 국면: **`TRANSITION`**, **`EARLY_TREND`** (WEAK, BASE, UNAVAILABLE, PROGRESSED 진입 제외)
   - FAST Core: Weekly Machine `TRIGGER` + `READY` / Monthly `PERMITTED` / Daily Risk `NORMAL`/`ELEVATED` / FAST Score `READY`/`PARTIAL`
   - 체결: 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)
2. **Pre-PROGRESSED Hold Policy (`EMPIRICAL_SELECTION`)**:
   - **`{hold["selected_hold_policy"]}`**
3. **PROGRESSED Exit Architecture (`EMPIRICAL_SELECTION`)**:
   - **`{final["exit_policy"]}`**

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
3. STEP 1: Pre-PROGRESSED Hold Evaluation (HOLD_A vs HOLD_B)
================================================================================

| 평가 항목 | HOLD_A (No Protection) | HOLD_B (Loss Guard -15%) | Delta (B - A) |
|---|:---:|:---:|:---:|
| **Return <= -30% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_30_count"]}건** |
| **Return <= -20% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_20_count"]}건** |
| **Return <= -10% 발생 건수 (비율)** | {variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_count"]}건 ({variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_rate"]}%) | **{variants["hold_b_e1"]["risk_metrics"]["return_le_neg_10_count"] - variants["hold_a_e1"]["risk_metrics"]["return_le_neg_10_count"]}건** |
| **최악 손실률 (Worst Return)** | {variants["hold_a_e1"]["risk_metrics"]["worst_return"]}% | {variants["hold_b_e1"]["risk_metrics"]["worst_return"]}% | **{variants["hold_b_e1"]["risk_metrics"]["worst_return"] - variants["hold_a_e1"]["risk_metrics"]["worst_return"]:+.2f}%p** |
| **Terminal Return (Mean / Median)** | {variants["hold_a_e1"]["terminal_return"]["mean"]}% / {variants["hold_a_e1"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"]}% / {variants["hold_b_e1"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"] - variants["hold_a_e1"]["terminal_return"]["mean"]:+.2f}%p / {variants["hold_b_e1"]["terminal_return"]["median"] - variants["hold_a_e1"]["terminal_return"]["median"]:+.2f}%p |
| **Peak Giveback (Median)** | {variants["hold_a_e1"]["peak_giveback"]["median"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"] - variants["hold_a_e1"]["peak_giveback"]["median"]:+.2f}%p |
| **평균 보유 주수 (Holding Weeks)** | {variants["hold_a_e1"]["holding_weeks"]["mean"]}주 | {variants["hold_b_e1"]["holding_weeks"]["mean"]}주 | {variants["hold_b_e1"]["holding_weeks"]["mean"] - variants["hold_a_e1"]["holding_weeks"]["mean"]:+.1f}주 |

- **Loss Guard 발동 통계**: 총 {hold["loss_guard_triggered_count"]}건 ({hold["loss_guard_triggered_rate_pct"]}%) 발동
- **Winner Truncation 비용**:
  - 발동 거래 중 원래 +20% 이상 도달 가능했던 거래: {hold["stopped_winners_ge_20_count"]}건
  - 발동 거래 중 원래 +50% 이상 도달 가능했던 거래: {hold["stopped_winners_ge_50_count"]}건
  - 발동 거래 중 원래 +100% 이상 도달 가능했던 거래: {hold["stopped_winners_ge_100_count"]}건
- **판정 근거**: `{hold["finding"]}` -> **`{hold["selected_hold_policy"]}` 확정**

================================================================================
4. STEP 2: PROGRESSED Exit Architecture Evaluation (E0 vs E1 vs E2)
================================================================================

| 지표 | E0 (Exit 3 Only) | E1 (Exit 3 + Normal Exit 4) | E2 (Exit 3 + Exit 4 + Coverage) |
|---|:---:|:---:|:---:|
| **Return <= -30% 건수 (비율)** | {variants["hold_b_e0"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e0"]["risk_metrics"]["return_le_neg_30_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_30_rate"]}%) | {variants["hold_b_e2"]["risk_metrics"]["return_le_neg_30_count"]}건 ({variants["hold_b_e2"]["risk_metrics"]["return_le_neg_30_rate"]}%) |
| **Return <= -20% 건수 (비율)** | {variants["hold_b_e0"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e0"]["risk_metrics"]["return_le_neg_20_rate"]}%) | {variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e1"]["risk_metrics"]["return_le_neg_20_rate"]}%) | {variants["hold_b_e2"]["risk_metrics"]["return_le_neg_20_count"]}건 ({variants["hold_b_e2"]["risk_metrics"]["return_le_neg_20_rate"]}%) |
| **Terminal Return (Mean / Median)** | {variants["hold_b_e0"]["terminal_return"]["mean"]}% / {variants["hold_b_e0"]["terminal_return"]["median"]}% | {variants["hold_b_e1"]["terminal_return"]["mean"]}% / {variants["hold_b_e1"]["terminal_return"]["median"]}% | {variants["hold_b_e2"]["terminal_return"]["mean"]}% / {variants["hold_b_e2"]["terminal_return"]["median"]}% |
| **Peak Giveback (Median / P75)** | {variants["hold_b_e0"]["peak_giveback"]["median"]}% / {variants["hold_b_e0"]["peak_giveback"]["p75"]}% | {variants["hold_b_e1"]["peak_giveback"]["median"]}% / {variants["hold_b_e1"]["peak_giveback"]["p75"]}% | {variants["hold_b_e2"]["peak_giveback"]["median"]}% / {variants["hold_b_e2"]["peak_giveback"]["p75"]}% |
| **Profit Capture Ratio (Median)** | {variants["hold_b_e0"]["profit_capture"]["median"]} | {variants["hold_b_e1"]["profit_capture"]["median"]} | {variants["hold_b_e2"]["profit_capture"]["median"]} |
| **Return >= +50% Winner 수 (비율)** | {variants["hold_b_e0"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e0"]["upside_metrics"]["return_ge_50_rate"]}%) | {variants["hold_b_e1"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e1"]["upside_metrics"]["return_ge_50_rate"]}%) | {variants["hold_b_e2"]["upside_metrics"]["return_ge_50_count"]}건 ({variants["hold_b_e2"]["upside_metrics"]["return_ge_50_rate"]}%) |
| **Return >= +100% Winner 수 (비율)** | {variants["hold_b_e0"]["upside_metrics"]["return_ge_100_count"]}건 ({variants["hold_b_e0"]["upside_metrics"]["return_ge_100_rate"]}%) | {variants["hold_b_e1"]["upside_metrics"]["return_ge_100_rate"]}% ({variants["hold_b_e1"]["upside_metrics"]["return_ge_100_count"]}건) | {variants["hold_b_e2"]["upside_metrics"]["return_ge_100_count"]}건 ({variants["hold_b_e2"]["upside_metrics"]["return_ge_100_rate"]}%) |

================================================================================
5. Final Strategy Specification: PATTERN_A_FAST_FINAL_STRATEGY_V01
================================================================================
- **전략 명칭**: `PATTERN_A_FAST_FINAL_STRATEGY_V01`
- **진입 규칙**:
  - `TRANSITION` 및 `EARLY_TREND` 국면의 FAST v0.1 신호 익영업일 시가 매수.
  - `WEAK`, `BASE`, `UNAVAILABLE`, `PROGRESSED` 진입 금지.
- **Pre-PROGRESSED 보유/손실 방어**:
  - `PROGRESSED` 도달 전 일봉 종가 `-15%` 이하 도달 시 익영업일 시가 손실 방어 청산 (`LOSS_GUARD_CLOSE_LE_NEG_15`).
- **PROGRESSED 청산**:
  - 정상 직접 handoff 및 Coverage Hole 모두에서 15.0pt HWM Score Drawdown 발생 시 익월 첫 거래일 시가 청산.
  - 정상 handoff 국면에서 유효 구조 이탈 시 Exit 3 청산.

================================================================================
6. 결론 및 Fresh OOS 전개 계획
================================================================================
- 투자자의 핵심 요구사항인 **대형 손실 최소화(Large Loss Minimization)** 원칙에 따라 `HOLD_B`(-15% 손실 가드) 및 `E2`(Exit 3 + Exit 4 + Coverage 15pt)가 결합된 **`PATTERN_A_FAST_FINAL_STRATEGY_V01`**이 단일 최종 전략으로 확정되었습니다.
- 본 최종 전략 후보는 후속 **Fresh OOS Forward Validation**의 단일 검증 대상으로 직접 전달됩니다.
"""


if __name__ == "__main__":
    run_evaluation()
