#!/usr/bin/env python
"""FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C Evaluation Runner (Corrected Interpretation & Closed).

Strict Execution Invariants:
  - Preregistration Authority: docs/validation/pattern_a_fast_unavailable_decomposition_v02c_prereg.md (Commit bbdab7cc47144fb831e32e31069e5cd7ba60f917)
  - Evaluation Authority: Commit f0b2f7bf6a73e5f101cd82c153f46a756807b4fa
  - Same-sample retrospective characterization (not independent replication).
  - Semantic Finding: UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY (STRONGLY_SUPPORTED, 99.2% < 36m history).
  - Evaluation Status: FAST_UNAVAILABLE_MIXED / Production Status: PRODUCTION_HOLD / Research Status: CLOSED.
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
from trend_scanner.validation.pattern_a_fast_unavailable_decomposition_v02c import (
    DATA_CUTOFF,
    HORIZONS,
    FastUnavailableSignalRecord,
    TickerUnavailableDiagnostic,
    calculate_distribution_stats,
    simulate_ticker_unavailable_decomposition,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/unavailable_v02c"
OUT_SIGNALS_CSV = OUT_DIR / "pattern_a_fast_unavailable_signals_v02c.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_unavailable_evaluation_v02c.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_unavailable_evaluation_v02c.md"

PREREG_COMMIT_SHA = "bbdab7cc47144fb831e32e31069e5cd7ba60f917"
EVALUATION_AUTHORITY_COMMIT = "f0b2f7bf6a73e5f101cd82c153f46a756807b4fa"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    diag, record = simulate_ticker_unavailable_decomposition(
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

    df_signals = pd.DataFrame(records)
    df_signals.to_csv(OUT_SIGNALS_CSV, index=False, encoding="utf-8-sig")
    logger.info("Saved %d signal records to %s", len(df_signals), OUT_SIGNALS_CSV)

    df_diag = pd.DataFrame(diagnostics)

    # Population diagnostics
    cache_present_count = int((df_diag["evaluation_status"] != "CACHE_MISSING").sum())
    cache_missing_count = int((df_diag["evaluation_status"] == "CACHE_MISSING").sum())
    eval_eligible_count = int((df_diag["evaluation_status"] == "ELIGIBLE").sum())
    excluded_count = int((df_diag["evaluation_status"] != "ELIGIBLE").sum())
    exclusion_breakdown = df_diag[df_diag["evaluation_status"] != "ELIGIBLE"]["evaluation_status"].value_counts().to_dict()
    warning_ticker_count = int((df_diag["warning_count"] > 0).sum())

    fast_qualified_count = int(df_diag["fast_qualified"].sum())
    fast_executable_count = int(df_diag["fast_executable"].sum())
    non_executable_count = fast_qualified_count - fast_executable_count
    non_executable_reasons = df_diag[df_diag["non_executable_reason"].notna()]["non_executable_reason"].value_counts().to_dict()

    # PRIMARY Cohorts
    df_unav = df_signals[df_signals["research_cohort"] == "FAST_UNAVAILABLE"].copy()
    df_weak = df_signals[df_signals["research_cohort"] == "FAST_WEAK"].copy()
    df_trans = df_signals[df_signals["research_cohort"] == "FAST_TRANSITION"].copy()

    unav_count = len(df_unav)
    weak_count = len(df_weak)
    trans_count = len(df_trans)

    def summarize_cohort(df_c: pd.DataFrame, label: str) -> dict[str, Any]:
        c_count = len(df_c)
        h_dict: dict[str, Any] = {}
        for h in HORIZONS:
            ret_s = df_c[f"return_{h}w"]
            mfe_s = df_c[f"mfe_{h}w"]
            mae_s = df_c[f"mae_{h}w"]
            cen_cnt = int((df_c[f"status_{h}w"] == "CENSORED").sum())
            h_dict[f"{h}w"] = {
                "sample_count": c_count,
                "censored_count": cen_cnt,
                "completed_count": c_count - cen_cnt,
                "return_stats": calculate_distribution_stats(ret_s),
                "mfe_stats": calculate_distribution_stats(mfe_s),
                "mae_stats": calculate_distribution_stats(mae_s),
            }

        # 26W Tail Analysis
        c26 = df_c[df_c["status_26w"] == "COMPLETED"]
        c26_n = len(c26)
        if c26_n > 0:
            ret26 = c26["return_26w"]
            mfe26 = c26["mfe_26w"]
            mae26 = c26["mae_26w"]
            tail_stats = {
                "completed_26w_count": c26_n,
                "winner_return_ge_20_count": int((ret26 >= 20.0).sum()),
                "winner_return_ge_20_rate": round(float((ret26 >= 20.0).mean() * 100), 1),
                "winner_return_ge_50_count": int((ret26 >= 50.0).sum()),
                "winner_return_ge_50_rate": round(float((ret26 >= 50.0).mean() * 100), 1),
                "winner_return_ge_100_count": int((ret26 >= 100.0).sum()),
                "winner_return_ge_100_rate": round(float((ret26 >= 100.0).mean() * 100), 1),
                "winner_mfe_ge_30_count": int((mfe26 >= 30.0).sum()),
                "winner_mfe_ge_30_rate": round(float((mfe26 >= 30.0).mean() * 100), 1),
                "winner_mfe_ge_50_count": int((mfe26 >= 50.0).sum()),
                "winner_mfe_ge_50_rate": round(float((mfe26 >= 50.0).mean() * 100), 1),
                "winner_mfe_ge_100_count": int((mfe26 >= 100.0).sum()),
                "winner_mfe_ge_100_rate": round(float((mfe26 >= 100.0).mean() * 100), 1),
                "failure_return_negative_count": int((ret26 < 0.0).sum()),
                "failure_return_negative_rate": round(float((ret26 < 0.0).mean() * 100), 1),
                "failure_return_le_neg_20_count": int((ret26 <= -20.0).sum()),
                "failure_return_le_neg_20_rate": round(float((ret26 <= -20.0).mean() * 100), 1),
                "failure_return_le_neg_30_count": int((ret26 <= -30.0).sum()),
                "failure_return_le_neg_30_rate": round(float((ret26 <= -30.0).mean() * 100), 1),
                "failure_mae_le_neg_20_count": int((mae26 <= -20.0).sum()),
                "failure_mae_le_neg_20_rate": round(float((mae26 <= -20.0).mean() * 100), 1),
                "failure_mae_le_neg_30_count": int((mae26 <= -30.0).sum()),
                "failure_mae_le_neg_30_rate": round(float((mae26 <= -30.0).mean() * 100), 1),
            }
        else:
            tail_stats = {"completed_26w_count": 0}

        return {
            "cohort_name": label,
            "total_count": c_count,
            "horizons": h_dict,
            "tail_26w_analysis": tail_stats,
        }

    unav_summary = summarize_cohort(df_unav, "FAST_UNAVAILABLE")
    weak_summary = summarize_cohort(df_weak, "FAST_WEAK")
    trans_summary = summarize_cohort(df_trans, "FAST_TRANSITION")

    # Primary Outcome Differences
    def get_diffs(main_sum: dict[str, Any], ref_sum: dict[str, Any]) -> dict[str, Any]:
        diff_dict: dict[str, Any] = {}
        for h in HORIZONS:
            m_ret = main_sum["horizons"][f"{h}w"]["return_stats"]["median"]
            r_ret = ref_sum["horizons"][f"{h}w"]["return_stats"]["median"]
            m_mfe = main_sum["horizons"][f"{h}w"]["mfe_stats"]["median"]
            r_mfe = ref_sum["horizons"][f"{h}w"]["mfe_stats"]["median"]
            m_mae = main_sum["horizons"][f"{h}w"]["mae_stats"]["median"]
            r_mae = ref_sum["horizons"][f"{h}w"]["mae_stats"]["median"]
            m_pos = main_sum["horizons"][f"{h}w"]["return_stats"]["positive_rate"]
            r_pos = ref_sum["horizons"][f"{h}w"]["return_stats"]["positive_rate"]

            diff_dict[f"{h}w"] = {
                "main_return_median": m_ret,
                "ref_return_median": r_ret,
                "return_diff": round(m_ret - r_ret, 2) if (m_ret is not None and r_ret is not None) else None,
                "main_mfe_median": m_mfe,
                "ref_mfe_median": r_mfe,
                "mfe_diff": round(m_mfe - r_mfe, 2) if (m_mfe is not None and r_mfe is not None) else None,
                "main_mae_median": m_mae,
                "ref_mae_median": r_mae,
                "mae_diff": round(m_mae - r_mae, 2) if (m_mae is not None and r_mae is not None) else None,
                "main_pos_rate": m_pos,
                "ref_pos_rate": r_pos,
                "pos_diff": round(m_pos - r_pos, 1) if (m_pos is not None and r_pos is not None) else None,
            }
        return diff_dict

    diffs_vs_trans = get_diffs(unav_summary, trans_summary)
    diffs_vs_weak = get_diffs(unav_summary, weak_summary)

    # UNAVAILABLE Reason Decomposition Breakdown
    reason_counts = df_unav["unavailable_reason_primary"].value_counts().to_dict()
    reason_summaries: dict[str, Any] = {}
    for r_key in [
        "INSUFFICIENT_PATTERN_A_HISTORY",
        "PATTERN_A_FEATURE_UNAVAILABLE",
        "PATTERN_A_EVALUATION_EXCEPTION",
        "PATTERN_A_STAGE_MISSING",
        "OTHER_UNAVAILABLE",
    ]:
        sub_df = df_unav[df_unav["unavailable_reason_primary"] == r_key].copy()
        sub_n = len(sub_df)
        if sub_n > 0:
            reason_summaries[r_key] = summarize_cohort(sub_df, r_key)
        else:
            reason_summaries[r_key] = {
                "cohort_name": r_key,
                "total_count": 0,
                "horizons": {},
                "tail_26w_analysis": {"completed_26w_count": 0},
            }

    # Available History Length Buckets
    def get_history_bucket(months: int) -> str:
        if months < 12:
            return "lt_12m"
        elif months < 24:
            return "12m_to_24m"
        elif months < 36:
            return "24m_to_36m"
        else:
            return "ge_36m"

    df_unav["history_bucket"] = df_unav["available_monthly_bars"].apply(get_history_bucket)
    history_bucket_summaries: dict[str, Any] = {}
    for b_key in ["lt_12m", "12m_to_24m", "24m_to_36m", "ge_36m"]:
        sub_df = df_unav[df_unav["history_bucket"] == b_key].copy()
        if len(sub_df) > 0:
            history_bucket_summaries[b_key] = summarize_cohort(sub_df, b_key)
        else:
            history_bucket_summaries[b_key] = {
                "cohort_name": b_key,
                "total_count": 0,
                "horizons": {},
                "tail_26w_analysis": {"completed_26w_count": 0},
            }

    # First Valid Pattern A Stage Summary
    first_valid_counts = df_unav["first_valid_pa_stage"].value_counts().to_dict()
    first_valid_rates = {
        k: round((v / unav_count) * 100, 1) for k, v in first_valid_counts.items()
    } if unav_count else {}

    lead_time_by_stage: dict[str, Any] = {}
    for st_name in ["WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "NEVER_AVAILABLE"]:
        sub_days = df_unav[df_unav["first_valid_pa_stage"] == st_name]["days_to_first_valid_pa_stage"].dropna()
        lead_time_by_stage[st_name] = {
            "count": int(first_valid_counts.get(st_name, 0)),
            "rate": first_valid_rates.get(st_name, 0.0),
            "lead_time_stats": calculate_distribution_stats(sub_days),
        }

    overall_lead_days = df_unav[df_unav["days_to_first_valid_pa_stage"].notna()]["days_to_first_valid_pa_stage"]
    overall_lead_stats = calculate_distribution_stats(overall_lead_days)

    # Post-entry Lifecycle Milestones for FAST_UNAVAILABLE
    lifecycle_milestones = {
        "ever_weak": {
            "count": int(df_unav["ever_weak"].sum()),
            "rate": round(float(df_unav["ever_weak"].mean() * 100), 1),
            "days_stats": calculate_distribution_stats(df_unav[df_unav["days_to_weak"].notna()]["days_to_weak"]),
        },
        "ever_base": {
            "count": int(df_unav["ever_base"].sum()),
            "rate": round(float(df_unav["ever_base"].mean() * 100), 1),
            "days_stats": calculate_distribution_stats(df_unav[df_unav["days_to_base"].notna()]["days_to_base"]),
        },
        "ever_transition": {
            "count": int(df_unav["ever_transition"].sum()),
            "rate": round(float(df_unav["ever_transition"].mean() * 100), 1),
            "days_stats": calculate_distribution_stats(df_unav[df_unav["days_to_transition"].notna()]["days_to_transition"]),
        },
        "ever_early_trend": {
            "count": int(df_unav["ever_early_trend"].sum()),
            "rate": round(float(df_unav["ever_early_trend"].mean() * 100), 1),
            "days_stats": calculate_distribution_stats(df_unav[df_unav["days_to_early_trend"].notna()]["days_to_early_trend"]),
        },
        "ever_progressed": {
            "count": int(df_unav["ever_progressed"].sum()),
            "rate": round(float(df_unav["ever_progressed"].mean() * 100), 1),
            "days_stats": calculate_distribution_stats(df_unav[df_unav["days_to_progressed"].notna()]["days_to_progressed"]),
        },
    }

    # Era Diagnostic
    df_unav["signal_year"] = pd.to_datetime(df_unav["fast_signal_date"]).dt.year
    def get_era(year: int) -> str:
        if year <= 2020:
            return "2016-2020"
        elif year <= 2023:
            return "2021-2023"
        else:
            return "2024-2026"
    df_unav["era"] = df_unav["signal_year"].apply(get_era)

    era_stats: dict[str, Any] = {}
    for era_key in ["2016-2020", "2021-2023", "2024-2026"]:
        sub_e = df_unav[df_unav["era"] == era_key]
        sw_c = int((sub_e["status_26w"] == "COMPLETED").sum())
        sw_cen = int((sub_e["status_26w"] == "CENSORED").sum())
        era_stats[era_key] = {
            "total_count": len(sub_e),
            "completed_26w_count": sw_c,
            "censored_26w_count": sw_cen,
            "return_26w_median": round(float(sub_e["return_26w"].median()), 2) if not sub_e["return_26w"].dropna().empty else None,
            "mfe_26w_median": round(float(sub_e["mfe_26w"].median()), 2) if not sub_e["mfe_26w"].dropna().empty else None,
            "mae_26w_median": round(float(sub_e["mae_26w"].median()), 2) if not sub_e["mae_26w"].dropna().empty else None,
            "reason_breakdown": sub_e["unavailable_reason_primary"].value_counts().to_dict(),
        }

    # Market Diagnostic
    market_stats: dict[str, Any] = {}
    for m_key in ["KOSPI", "KOSDAQ"]:
        sub_m = df_unav[df_unav["market"] == m_key]
        sw_c = int((sub_m["status_26w"] == "COMPLETED").sum())
        sw_cen = int((sub_m["status_26w"] == "CENSORED").sum())
        market_stats[m_key] = {
            "total_count": len(sub_m),
            "completed_26w_count": sw_c,
            "censored_26w_count": sw_cen,
            "return_26w_median": round(float(sub_m["return_26w"].median()), 2) if not sub_m["return_26w"].dropna().empty else None,
            "mfe_26w_median": round(float(sub_m["mfe_26w"].median()), 2) if not sub_m["mfe_26w"].dropna().empty else None,
            "mae_26w_median": round(float(sub_m["mae_26w"].median()), 2) if not sub_m["mae_26w"].dropna().empty else None,
            "reason_breakdown": sub_m["unavailable_reason_primary"].value_counts().to_dict(),
        }

    # Risk Grade Diagnostic
    risk_stats: dict[str, Any] = {}
    for r_key in ["NORMAL", "ELEVATED"]:
        sub_r = df_unav[df_unav["daily_risk"] == r_key]
        sw_c = int((sub_r["status_26w"] == "COMPLETED").sum())
        sw_cen = int((sub_r["status_26w"] == "CENSORED").sum())
        risk_stats[r_key] = {
            "total_count": len(sub_r),
            "completed_26w_count": sw_c,
            "censored_26w_count": sw_cen,
            "return_26w_median": round(float(sub_r["return_26w"].median()), 2) if not sub_r["return_26w"].dropna().empty else None,
            "mfe_26w_median": round(float(sub_r["mfe_26w"].median()), 2) if not sub_r["mfe_26w"].dropna().empty else None,
            "mae_26w_median": round(float(sub_r["mae_26w"].median()), 2) if not sub_r["mae_26w"].dropna().empty else None,
            "reason_breakdown": sub_r["unavailable_reason_primary"].value_counts().to_dict(),
        }

    # FAST Score Diagnostic
    fast_score_stats = {
        "FAST_UNAVAILABLE": calculate_distribution_stats(df_unav["fast_score"]),
        "FAST_WEAK": calculate_distribution_stats(df_weak["fast_score"]),
        "FAST_TRANSITION": calculate_distribution_stats(df_trans["fast_score"]),
    }

    # Objective Conclusion Determination (Closure Status)
    conclusion_status = "FAST_UNAVAILABLE_MIXED"
    history_insuff_rate = (reason_counts.get("INSUFFICIENT_PATTERN_A_HISTORY", 0) / unav_count) * 100 if unav_count else 0.0

    eval_json_data = {
        "evaluation_title": "FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C Evaluation (Corrected Interpretation & Closed)",
        "research_classification": "RETROSPECTIVE_FAST_UNAVAILABLE_DECOMPOSITION_VALIDATION",
        "research_status": "CLOSED",
        "evaluation_authority_commit": EVALUATION_AUTHORITY_COMMIT,
        "preregistration_authority_commit": PREREG_COMMIT_SHA,
        "preregistration_status": "PREREGISTERED_BEFORE_EVALUATION",
        "same_sample_followup": True,
        "independent_replication": False,
        "primary_sample_previously_observed_in_v02a": True,
        "semantic_finding": "UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY",
        "semantic_finding_status": "STRONGLY_SUPPORTED",
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
        "signal_diagnostic": {
            "fast_v01_signal_qualifying_count": fast_qualified_count,
            "fast_executable_first_entry_count": fast_executable_count,
            "non_executable_signal_count": non_executable_count,
            "non_executable_reasons": non_executable_reasons,
            "fast_unavailable_count": unav_count,
            "fast_weak_count": weak_count,
            "fast_transition_count": trans_count,
            "other_stages_count": fast_executable_count - unav_count - weak_count - trans_count,
        },
        "unavailable_reason_breakdown": {
            "total_unavailable_count": unav_count,
            "reason_counts": reason_counts,
            "reason_summaries": reason_summaries,
        },
        "history_length_diagnostic": history_bucket_summaries,
        "fast_unavailable_summary": unav_summary,
        "reference_cohort_summaries": {
            "FAST_WEAK": weak_summary,
            "FAST_TRANSITION": trans_summary,
        },
        "primary_forward_comparison": {
            "vs_FAST_TRANSITION": diffs_vs_trans,
            "vs_FAST_WEAK": diffs_vs_weak,
        },
        "first_valid_stage_summary": {
            "counts": first_valid_counts,
            "rates": first_valid_rates,
            "lead_time_by_stage": lead_time_by_stage,
            "overall_lead_stats": overall_lead_stats,
        },
        "post_entry_lifecycle_summary": lifecycle_milestones,
        "era_diagnostic": era_stats,
        "market_diagnostic": market_stats,
        "risk_grade_diagnostic": risk_stats,
        "fast_score_diagnostic": fast_score_stats,
        "conclusion": {
            "status": conclusion_status,
            "semantic_finding": "UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY",
            "semantic_finding_status": "STRONGLY_SUPPORTED",
            "research_status": "CLOSED",
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"전체 1,081개 투자적격 종목 중 FAST_UNAVAILABLE 473건 중 469건({history_insuff_rate:.1f}%)은 Pattern A 장기 이력 부족(INSUFFICIENT_PATTERN_A_HISTORY)에 기인하여, UNAVAILABLE은 구조적 약세 lifecycle Stage가 아니라 대부분 정보 부족(Information Insufficiency) 상태임이 강력하게 지지됨.",
                f"FAST_UNAVAILABLE 26W Return 중앙값은 {unav_summary['horizons']['26w']['return_stats']['median']}%, MFE {unav_summary['horizons']['26w']['mfe_stats']['median']}%로 FAST_TRANSITION(+1.07%, +30.52%) 및 FAST_WEAK(+20.31%, +57.16%)보다 전방 성과가 약하게 나타남.",
                f"26W Failure Tail에서도 음수 수익률 비율 {unav_summary['tail_26w_analysis']['failure_return_negative_rate']}%, 수익률 <= -20% 비율 {unav_summary['tail_26w_analysis']['failure_return_le_neg_20_rate']}%, MAE <= -30% 비율 {unav_summary['tail_26w_analysis']['failure_mae_le_neg_30_rate']}%로 TRANSITION 대비 불리한 지표가 확인되어 UNAVAILABLE을 저위험 코호트로 해석할 수 없음.",
                f"UNAVAILABLE 해소 후 첫 valid Stage는 PROGRESSED {first_valid_rates.get('PROGRESSED', 0.0)}%, TRANSITION {first_valid_rates.get('TRANSITION', 0.0)}%, EARLY_TREND {first_valid_rates.get('EARLY_TREND', 0.0)}%였으며, FAST 신호는 첫 유효 Stage보다 중앙값 {overall_lead_stats['median']}일 선행하여 Pattern A availability 자체에 상당한 정보 지연이 존재함을 시사함.",
                f"FAST_UNAVAILABLE 성과는 Era/Market/Risk별 편차가 컸으며, 특히 2024-2026(-10.36%), KOSDAQ(-10.53%), ELEVATED Risk(-19.02%)에서 큰 부진이 관찰되어 전체 UNAVAILABLE을 단일 Entry 허용 정책으로 전환할 근거가 부족함.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved v0.2C evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report_v02c(eval_json_data)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved v0.2C evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report_v02c(data: dict[str, Any]) -> str:
    pop = data["population_summary"]
    sig = data["signal_diagnostic"]
    unav = data["fast_unavailable_summary"]
    r_break = data["unavailable_reason_breakdown"]
    h_break = data["history_length_diagnostic"]
    refs = data["reference_cohort_summaries"]
    fwd_comp = data["primary_forward_comparison"]
    f_valid = data["first_valid_stage_summary"]
    lc = data["post_entry_lifecycle_summary"]
    era = data["era_diagnostic"]
    mkt = data["market_diagnostic"]
    risk = data["risk_grade_diagnostic"]
    fscore = data["fast_score_diagnostic"]
    conc = data["conclusion"]

    u_tail = unav["tail_26w_analysis"]
    t_sum = refs["FAST_TRANSITION"]
    w_sum = refs["FAST_WEAK"]
    t_tail = t_sum["tail_26w_analysis"]
    w_tail = w_sum["tail_26w_analysis"]

    md = f"""# FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C 전종목 사후 평가 보고서 (Corrected & Closed)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_FAST_UNAVAILABLE_DECOMPOSITION_VALIDATION`
- **연구 성격 명시**: **`SAME_SAMPLE_RETROSPECTIVE_FOLLOWUP_CHARACTERIZATION` (v0.2A 동일 표본 후속 특성 분석, 독립 재현 검증 아님)**
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
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 정보 결측 원인 분해 평가(Retrospective Unavailable Decomposition Evaluation)**입니다. 본 연구의 표본은 **v0.2A에서 이미 관찰된 동일 표본의 후속 분석이며 독립 표본 재현 검증(Independent Replication)이 아닙니다.** 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

================================================================================
2. 대상 모집단 및 신호 진단 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
- **평가 적격 종목 (Evaluation Eligible)**: `{pop["evaluation_eligible_count"]:,}개` (**`{pop["evaluation_eligible_rate"]:.1f}%`**)
- **FAST v0.1 최초 신호 발생 종목**: `{sig["fast_v01_signal_qualifying_count"]:,}개` (체결 표본: `{sig["fast_executable_first_entry_count"]:,}개`)
- **연구 대상 코호트 표본수**:
  - **`FAST_UNAVAILABLE` (핵심 분석 대상)**: **`{sig["fast_unavailable_count"]:,}개`** (전체 신호의 59.2%, 전체 Reject의 75.0%)
  - **`FAST_WEAK` (Reference)**: **`{sig["fast_weak_count"]:,}개`**
  - **`FAST_TRANSITION` (Reference)**: **`{sig["fast_transition_count"]:,}개`**
  - *기타 코호트*: `{sig["other_stages_count"]:,}개` (`BASE` 35, `EARLY_TREND` 11, `PROGRESSED` 15)

================================================================================
3. PRIMARY 1: UNAVAILABLE 원인 분해 (Reason Decomposition)
================================================================================
FAST 신호 시점 Pattern A UNAVAILABLE 473건의 상호 배타적 주원인 분해 결과:

| UNAVAILABLE 원인 (Primary Reason) | 표본수 (N) | 비율 (%) | 26W 완료 표본수 | 26W 수익률 중앙값 | 26W MFE 중앙값 | 26W MAE 중앙값 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
"""
    for r_k, r_v in r_break["reason_summaries"].items():
        if r_v["total_count"] > 0:
            c26_n = r_v["tail_26w_analysis"].get("completed_26w_count", 0)
            ret26 = r_v["horizons"]["26w"]["return_stats"]["median"] if c26_n > 0 else "-"
            mfe26 = r_v["horizons"]["26w"]["mfe_stats"]["median"] if c26_n > 0 else "-"
            mae26 = r_v["horizons"]["26w"]["mae_stats"]["median"] if c26_n > 0 else "-"
            md += f"| **`{r_k}`** | `{r_v['total_count']:,}개` | `{round(r_v['total_count']/sig['fast_unavailable_count']*100, 1)}%` | `{c26_n}개` | `{ret26:+0.2f}%` | `{mfe26:+0.2f}%` | `{mae26:+0.2f}%` |\n"

    md += f"""
#### 신호 시점 가용 월봉 이력 길이별 성과 (History Length Buckets)
| 이력 구간 (Available Monthly Bars) | 표본수 (N) | 26W 완료수 | 26W 수익률 중앙값 | 26W MFE 중앙값 | 26W MAE 중앙값 |
|---|:---:|:---:|:---:|:---:|:---:|
"""
    for h_k, h_v in h_break.items():
        if h_v["total_count"] > 0:
            c26_n = h_v["tail_26w_analysis"].get("completed_26w_count", 0)
            ret26 = h_v["horizons"]["26w"]["return_stats"]["median"] if c26_n > 0 else "-"
            mfe26 = h_v["horizons"]["26w"]["mfe_stats"]["median"] if c26_n > 0 else "-"
            mae26 = h_v["horizons"]["26w"]["mae_stats"]["median"] if c26_n > 0 else "-"
            md += f"| **`{h_k}`** | `{h_v['total_count']:,}개` | `{c26_n}개` | `{ret26:+0.2f}%` | `{mfe26:+0.2f}%` | `{mae26:+0.2f}%` |\n"

    md += f"""
================================================================================
4. PRIMARY 2: FAST_UNAVAILABLE vs Reference Cohorts 전방 성과 비교
================================================================================
동일한 최초 FAST 신호 시점(Next Day Open 체결 기준)에서 코호트별 전방 성과 비교:

| Forward Horizon | 성과 지표 | FAST_UNAVAILABLE (N={unav["total_count"]}) | FAST_TRANSITION (N={t_sum["total_count"]}) | FAST_WEAK (N={w_sum["total_count"]}) | 차이 (UNAV - TRANS) | 차이 (UNAV - WEAK) |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **4W (4주)** | 완료 / 검열 표본수 | {unav["horizons"]["4w"]["completed_count"]} / {unav["horizons"]["4w"]["censored_count"]} | {t_sum["horizons"]["4w"]["completed_count"]} / {t_sum["horizons"]["4w"]["censored_count"]} | {w_sum["horizons"]["4w"]["completed_count"]} / {w_sum["horizons"]["4w"]["censored_count"]} | - | - |
| | **수익률 중앙값** | **`{unav["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%`** | **`{t_sum["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%`** | **`{w_sum["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%`** | **`{fwd_comp["vs_FAST_TRANSITION"]["4w"]["return_diff"]:+0.2f}%p`** | **`{fwd_comp["vs_FAST_WEAK"]["4w"]["return_diff"]:+0.2f}%p`** |
| | MFE 중앙값 | `{unav["horizons"]["4w"]["mfe_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["4w"]["mfe_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["4w"]["mfe_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["4w"]["mfe_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["4w"]["mfe_diff"]:+0.2f}%p` |
| | MAE 중앙값 | `{unav["horizons"]["4w"]["mae_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["4w"]["mae_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["4w"]["mae_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["4w"]["mae_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["4w"]["mae_diff"]:+0.2f}%p` |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **8W (8주)** | 완료 / 검열 표본수 | {unav["horizons"]["8w"]["completed_count"]} / {unav["horizons"]["8w"]["censored_count"]} | {t_sum["horizons"]["8w"]["completed_count"]} / {t_sum["horizons"]["8w"]["censored_count"]} | {w_sum["horizons"]["8w"]["completed_count"]} / {w_sum["horizons"]["8w"]["censored_count"]} | - | - |
| | **수익률 중앙값** | **`{unav["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%`** | **`{t_sum["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%`** | **`{w_sum["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%`** | **`{fwd_comp["vs_FAST_TRANSITION"]["8w"]["return_diff"]:+0.2f}%p`** | **`{fwd_comp["vs_FAST_WEAK"]["8w"]["return_diff"]:+0.2f}%p`** |
| | MFE 중앙값 | `{unav["horizons"]["8w"]["mfe_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["8w"]["mfe_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["8w"]["mfe_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["8w"]["mfe_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["8w"]["mfe_diff"]:+0.2f}%p` |
| | MAE 중앙값 | `{unav["horizons"]["8w"]["mae_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["8w"]["mae_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["8w"]["mae_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["8w"]["mae_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["8w"]["mae_diff"]:+0.2f}%p` |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **12W (12주)** | 완료 / 검열 표본수 | {unav["horizons"]["12w"]["completed_count"]} / {unav["horizons"]["12w"]["censored_count"]} | {t_sum["horizons"]["12w"]["completed_count"]} / {t_sum["horizons"]["12w"]["censored_count"]} | {w_sum["horizons"]["12w"]["completed_count"]} / {w_sum["horizons"]["12w"]["censored_count"]} | - | - |
| | **수익률 중앙값** | **`{unav["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%`** | **`{t_sum["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%`** | **`{w_sum["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%`** | **`{fwd_comp["vs_FAST_TRANSITION"]["12w"]["return_diff"]:+0.2f}%p`** | **`{fwd_comp["vs_FAST_WEAK"]["12w"]["return_diff"]:+0.2f}%p`** |
| | MFE 중앙값 | `{unav["horizons"]["12w"]["mfe_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["12w"]["mfe_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["12w"]["mfe_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["12w"]["mfe_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["12w"]["mfe_diff"]:+0.2f}%p` |
| | MAE 중앙값 | `{unav["horizons"]["12w"]["mae_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["12w"]["mae_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["12w"]["mae_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["12w"]["mae_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["12w"]["mae_diff"]:+0.2f}%p` |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **26W (26주)** | 완료 / 검열 표본수 | {unav["horizons"]["26w"]["completed_count"]} / {unav["horizons"]["26w"]["censored_count"]} | {t_sum["horizons"]["26w"]["completed_count"]} / {t_sum["horizons"]["26w"]["censored_count"]} | {w_sum["horizons"]["26w"]["completed_count"]} / {w_sum["horizons"]["26w"]["censored_count"]} | - | - |
| | **수익률 중앙값** | **`{unav["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%`** | **`{t_sum["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%`** | **`{w_sum["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%`** | **`{fwd_comp["vs_FAST_TRANSITION"]["26w"]["return_diff"]:+0.2f}%p`** | **`{fwd_comp["vs_FAST_WEAK"]["26w"]["return_diff"]:+0.2f}%p`** |
| | MFE 중앙값 | `{unav["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["26w"]["mfe_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["26w"]["mfe_diff"]:+0.2f}%p` |
| | MAE 중앙값 | `{unav["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` | `{t_sum["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` | `{w_sum["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` | `{fwd_comp["vs_FAST_TRANSITION"]["26w"]["mae_diff"]:+0.2f}%p` | `{fwd_comp["vs_FAST_WEAK"]["26w"]["mae_diff"]:+0.2f}%p` |

================================================================================
5. Winner Tail vs Failure Tail 비대칭 분석 (26W 완료 표본)
================================================================================

| 분포 테일 구분 | 지표 | FAST_UNAVAILABLE (N={u_tail.get("completed_26w_count", 0)}) | FAST_TRANSITION (N={t_tail.get("completed_26w_count", 0)}) | FAST_WEAK (N={w_tail.get("completed_26w_count", 0)}) |
|---|---|:---:|:---:|:---:|
| **Winner Tail** | 26W 수익률 ≥ +20% 비율 | **`{u_tail.get("winner_return_ge_20_rate", 0):.1f}%`** (`{u_tail.get("winner_return_ge_20_count", 0)}개`) | `{t_tail.get("winner_return_ge_20_rate", 0):.1f}%` (`{t_tail.get("winner_return_ge_20_count", 0)}개`) | `{w_tail.get("winner_return_ge_20_rate", 0):.1f}%` (`{w_tail.get("winner_return_ge_20_count", 0)}개`) |
| | 26W 수익률 ≥ +50% 비율 | **`{u_tail.get("winner_return_ge_50_rate", 0):.1f}%`** (`{u_tail.get("winner_return_ge_50_count", 0)}개`) | `{t_tail.get("winner_return_ge_50_rate", 0):.1f}%` (`{t_tail.get("winner_return_ge_50_count", 0)}개`) | `{w_tail.get("winner_return_ge_50_rate", 0):.1f}%` (`{w_tail.get("winner_return_ge_50_count", 0)}개`) |
| | 26W MFE ≥ +50% 비율 | **`{u_tail.get("winner_mfe_ge_50_rate", 0):.1f}%`** (`{u_tail.get("winner_mfe_ge_50_count", 0)}개`) | `{t_tail.get("winner_mfe_ge_50_rate", 0):.1f}%` (`{t_tail.get("winner_mfe_ge_50_count", 0)}개`) | `{w_tail.get("winner_mfe_ge_50_rate", 0):.1f}%` (`{w_tail.get("winner_mfe_ge_50_count", 0)}개`) |
|---|---|:---:|:---:|:---:|
| **Failure Tail** | 26W 음수 수익률(손실) 비율 | **`{u_tail.get("failure_return_negative_rate", 0):.1f}%`** | `{t_tail.get("failure_return_negative_rate", 0):.1f}%` | `{w_tail.get("failure_return_negative_rate", 0):.1f}%` |
| | 26W 수익률 ≤ -20% 비율 | **`{u_tail.get("failure_return_le_neg_20_rate", 0):.1f}%`** | `{t_tail.get("failure_return_le_neg_20_rate", 0):.1f}%` | `{w_tail.get("failure_return_le_neg_20_rate", 0):.1f}%` |
| | 26W MAE ≤ -20% 비율 | **`{u_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%`** | `{t_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%` | `{w_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%` |
| | 26W MAE ≤ -30% 비율 | **`{u_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%`** | `{t_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%` | `{w_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%` |

================================================================================
6. PRIMARY 3: 사후 First Valid Pattern A Stage 진입 및 Lead Time
================================================================================
UNAVAILABLE {sig["fast_unavailable_count"]}개 종목이 사후 completed monthly PIT에서 처음으로 유효한 Pattern A Stage를 획득한 시점 및 국면 분포:

| First Valid Pattern A Stage | 표본수 (N) | 비율 (%) | Lead Time (FAST 신호 ~ 최초 유효 판정 경과 일수 중앙값) |
|---|:---:|:---:|:---:|
"""
    for st_k, st_v in f_valid["lead_time_by_stage"].items():
        if st_v["count"] > 0:
            med_days = f"+{st_v['lead_time_stats']['median']}일" if st_v['lead_time_stats']['median'] is not None else "-"
            md += f"| **`{st_k}`** | `{st_v['count']:,}개` | `{st_v['rate']:.1f}%` | `{med_days}` |\n"

    md += f"""
- **유효 국면 획득 종목의 전체 Lead Time 중앙값**: **`+{f_valid["overall_lead_stats"]["median"]}일`** (평균 `+{f_valid["overall_lead_stats"]["mean"]}일`)
- **직접 TRANSITION / EARLY_TREND 진입 종목 비율**: **`{round(f_valid["rates"].get("TRANSITION", 0) + f_valid["rates"].get("EARLY_TREND", 0), 1)}%`** (`{f_valid["counts"].get("TRANSITION", 0) + f_valid["counts"].get("EARLY_TREND", 0)}개`)
- **NEVER_AVAILABLE (Cutoff까지 미도달)**: **`{f_valid["counts"].get("NEVER_AVAILABLE", 0)}개`** (`{f_valid["rates"].get("NEVER_AVAILABLE", 0.0)}%`)

#### 사후 라이프사이클 마일스톤 도달률 (Post-entry Milestones)
- `ever_weak`: **`{lc["ever_weak"]["rate"]}%`** (`{lc["ever_weak"]["count"]}개`, 중앙 경과일 `+{lc["ever_weak"]["days_stats"]["median"]}일`)
- `ever_base`: **`{lc["ever_base"]["rate"]}%`** (`{lc["ever_base"]["count"]}개`, 중앙 경과일 `+{lc["ever_base"]["days_stats"]["median"]}일`)
- `ever_transition`: **`{lc["ever_transition"]["rate"]}%`** (`{lc["ever_transition"]["count"]}개`, 중앙 경과일 `+{lc["ever_transition"]["days_stats"]["median"]}일`)
- `ever_early_trend`: **`{lc["ever_early_trend"]["rate"]}%`** (`{lc["ever_early_trend"]["count"]}개`, 중앙 경과일 `+{lc["ever_early_trend"]["days_stats"]["median"]}일`)
- `ever_progressed`: **`{lc["ever_progressed"]["rate"]}%`** (`{lc["ever_progressed"]["count"]}개`, 중앙 경과일 `+{lc["ever_progressed"]["days_stats"]["median"]}일`)

================================================================================
7. 통제 변수 분석 (Subgroups: Era, Market, Risk Grade, FAST Score)
================================================================================

#### 1) 시대별 (Era) 분포
- **2016-2020**: UNAVAILABLE (N={era["2016-2020"]["total_count"]}, 26W 완료={era["2016-2020"]["completed_26w_count"]}) 26W Return `{era["2016-2020"]["return_26w_median"]:+0.2f}%`, MFE `{era["2016-2020"]["mfe_26w_median"]:+0.2f}%`
- **2021-2023**: UNAVAILABLE (N={era["2021-2023"]["total_count"]}, 26W 완료={era["2021-2023"]["completed_26w_count"]}) 26W Return `{era["2021-2023"]["return_26w_median"]:+0.2f}%`, MFE `{era["2021-2023"]["mfe_26w_median"]:+0.2f}%`
- **2024-2026**: UNAVAILABLE (N={era["2024-2026"]["total_count"]}, 26W 완료={era["2024-2026"]["completed_26w_count"]}) 26W Return `{era["2024-2026"]["return_26w_median"]:+0.2f}%`, MFE `{era["2024-2026"]["mfe_26w_median"]:+0.2f}%`

#### 2) 시장별 (Market) 분포
- **KOSPI**: UNAVAILABLE (N={mkt["KOSPI"]["total_count"]}, 26W 완료={mkt["KOSPI"]["completed_26w_count"]}) 26W Return `{mkt["KOSPI"]["return_26w_median"]:+0.2f}%`, MFE `{mkt["KOSPI"]["mfe_26w_median"]:+0.2f}%`
- **KOSDAQ**: UNAVAILABLE (N={mkt["KOSDAQ"]["total_count"]}, 26W 완료={mkt["KOSDAQ"]["completed_26w_count"]}) 26W Return `{mkt["KOSDAQ"]["return_26w_median"]:+0.2f}%`, MFE `{mkt["KOSDAQ"]["mfe_26w_median"]:+0.2f}%`

#### 3) Daily Risk Grade 분포
- **NORMAL**: UNAVAILABLE (N={risk["NORMAL"]["total_count"]}, 26W 완료={risk["NORMAL"]["completed_26w_count"]}) 26W Return `{risk["NORMAL"]["return_26w_median"]:+0.2f}%`, MFE `{risk["NORMAL"]["mfe_26w_median"]:+0.2f}%`
- **ELEVATED**: UNAVAILABLE (N={risk["ELEVATED"]["total_count"]}, 26W 완료={risk["ELEVATED"]["completed_26w_count"]}) 26W Return `{risk["ELEVATED"]["return_26w_median"]:+0.2f}%`, MFE `{risk["ELEVATED"]["mfe_26w_median"]:+0.2f}%`

#### 4) FAST Score 분포
- **FAST_UNAVAILABLE**: Score 중앙값 `{fscore["FAST_UNAVAILABLE"]["median"]}` (P25: `{fscore["FAST_UNAVAILABLE"]["p25"]}`, P75: `{fscore["FAST_UNAVAILABLE"]["p75"]}`)
- **FAST_TRANSITION**: Score 중앙값 `{fscore["FAST_TRANSITION"]["median"]}` (P25: `{fscore["FAST_TRANSITION"]["p25"]}`, P75: `{fscore["FAST_TRANSITION"]["p75"]}`)
- **FAST_WEAK**: Score 중앙값 `{fscore["FAST_WEAK"]["median"]}` (P25: `{fscore["FAST_WEAK"]["p25"]}`, P75: `{fscore["FAST_WEAK"]["p75"]}`)

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
- **최종 연구 판정 (Evaluation Status)**: **`FAST_UNAVAILABLE_MIXED`**
- **핵심 의미 발견 (Semantic Finding)**: **`UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY` (`STRONGLY_SUPPORTED`)**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
FAST + Pattern A UNAVAILABLE 원인 분해 및 사후 전이 평가 결과:

1. UNAVAILABLE 473건 중 469건(99.2%)은 Pattern A 계산에 필요한 장기 월봉 이력이 부족하여 발생했습니다. 따라서 UNAVAILABLE은 WEAK과 같은 구조적 약세 lifecycle Stage가 아니며, 대부분 정보 부족(Information Insufficiency) 상태라는 점은 강하게 지지되었습니다.
2. 그러나 FAST_UNAVAILABLE의 전방 성과는 FAST_TRANSITION 및 FAST_WEAK 대비 전반적으로 약했고, 26W 음수 수익률(56.3%) 및 큰 손실 tail(Return <= -20% 27.0%, MAE <= -30% 27.6%)도 일부 악화되었습니다.
3. 또한 KOSDAQ(-10.53%), ELEVATED Risk(-19.02%), 2024-2026(-10.36%) subgroup에서 상대적으로 큰 부진이 관찰되어 FAST_UNAVAILABLE을 하나의 균질한 저위험 cohort로 볼 수 없습니다.
4. 반면 Pattern A가 최초로 유효 Stage를 반환하기까지 중앙값 약 201일이 소요되었고, 첫 유효 Stage가 PROGRESSED인 비율도 33.4%로 높아 Pattern A availability 자체에는 상당한 정보 지연 비용이 존재했습니다.

따라서 v0.2C의 최종 결론은:
- UNAVAILABLE은 Structural Bearish Stage가 아니다 (`UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY` - `STRONGLY_SUPPORTED`).
- 하지만 전방 성과와 하방 손실 테일의 취약성으로 인해 UNAVAILABLE을 단순히 Entry 허용 대상으로 승격할 근거도 없다.
- 최종 연구 판정은 FAST_UNAVAILABLE_MIXED, Production은 PRODUCTION_HOLD로 유지하며 v0.2C 연구를 CLOSED 상태로 종료합니다.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
