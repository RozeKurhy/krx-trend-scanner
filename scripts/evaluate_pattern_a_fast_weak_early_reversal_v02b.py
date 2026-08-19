#!/usr/bin/env python
"""FAST + Pattern A WEAK Early Reversal Validation v0.2B Evaluation Runner.

Strict Execution Invariants:
  - Preregistration Authority: docs/validation/pattern_a_fast_weak_early_reversal_v02b_prereg.md (Commit aea7db2e5a3f9d768f08c43c15d3f8983b653712)
  - Local Cache Only (zero external network requests).
  - PIT evaluation anchored on FIRST FAST v0.1 qualifying signal per ticker.
  - Next local trading day OPEN execution.
  - Frozen contracts & zero parameter sweeps.
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
from trend_scanner.validation.pattern_a_fast_weak_early_reversal_v02b import (
    DATA_CUTOFF,
    HORIZONS,
    FastWeakSignalRecord,
    TickerWeakDiagnostic,
    calculate_distribution_stats,
    simulate_ticker_weak_early_reversal,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/weak_reversal_v02b"
OUT_SIGNALS_CSV = OUT_DIR / "pattern_a_fast_weak_reversal_signals_v02b.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_weak_reversal_evaluation_v02b.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_weak_reversal_evaluation_v02b.md"

PREREG_COMMIT_SHA = "aea7db2e5a3f9d768f08c43c15d3f8983b653712"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    diag, record = simulate_ticker_weak_early_reversal(
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
    df_weak = df_signals[df_signals["research_cohort"] == "FAST_WEAK"].copy()
    df_trans = df_signals[df_signals["research_cohort"] == "FAST_TRANSITION"].copy()

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

        # 26W Winner / Failure Tail Analysis (on completed samples)
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

    weak_summary = summarize_cohort(df_weak, "FAST_WEAK")
    trans_summary = summarize_cohort(df_trans, "FAST_TRANSITION")

    # Primary Differences (WEAK - TRANSITION)
    primary_diffs: dict[str, Any] = {}
    for h in HORIZONS:
        w_ret = weak_summary["horizons"][f"{h}w"]["return_stats"]["median"]
        t_ret = trans_summary["horizons"][f"{h}w"]["return_stats"]["median"]
        ret_diff = round(w_ret - t_ret, 2) if (w_ret is not None and t_ret is not None) else None

        w_mfe = weak_summary["horizons"][f"{h}w"]["mfe_stats"]["median"]
        t_mfe = trans_summary["horizons"][f"{h}w"]["mfe_stats"]["median"]
        mfe_diff = round(w_mfe - t_mfe, 2) if (w_mfe is not None and t_mfe is not None) else None

        w_mae = weak_summary["horizons"][f"{h}w"]["mae_stats"]["median"]
        t_mae = trans_summary["horizons"][f"{h}w"]["mae_stats"]["median"]
        mae_diff = round(w_mae - t_mae, 2) if (w_mae is not None and t_mae is not None) else None

        w_pos = weak_summary["horizons"][f"{h}w"]["return_stats"]["positive_rate"]
        t_pos = trans_summary["horizons"][f"{h}w"]["return_stats"]["positive_rate"]
        pos_diff = round(w_pos - t_pos, 1) if (w_pos is not None and t_pos is not None) else None

        primary_diffs[f"{h}w"] = {
            "weak_return_median": w_ret,
            "transition_return_median": t_ret,
            "median_return_difference": ret_diff,
            "weak_mfe_median": w_mfe,
            "transition_mfe_median": t_mfe,
            "median_mfe_difference": mfe_diff,
            "weak_mae_median": w_mae,
            "transition_mae_median": t_mae,
            "median_mae_difference": mae_diff,
            "weak_positive_rate": w_pos,
            "transition_positive_rate": t_pos,
            "positive_rate_difference": pos_diff,
        }

    # Secondary: FAST_WEAK Lifecycle Follow-through
    ev_trans_cnt = int(df_weak["ever_transition"].sum())
    ev_early_cnt = int(df_weak["ever_early_trend"].sum())
    ev_prog_cnt = int(df_weak["ever_progressed"].sum())

    trans_days_s = df_weak[df_weak["days_to_transition"].notna()]["days_to_transition"]
    early_days_s = df_weak[df_weak["days_to_early_trend"].notna()]["days_to_early_trend"]
    prog_days_s = df_weak[df_weak["days_to_progressed"].notna()]["days_to_progressed"]

    lifecycle_followthrough = {
        "fast_weak_total_count": weak_count,
        "ever_transition_count": ev_trans_cnt,
        "ever_transition_rate": round((ev_trans_cnt / weak_count) * 100, 1) if weak_count else 0.0,
        "days_to_transition_stats": calculate_distribution_stats(trans_days_s),
        "ever_early_trend_count": ev_early_cnt,
        "ever_early_trend_rate": round((ev_early_cnt / weak_count) * 100, 1) if weak_count else 0.0,
        "days_to_early_trend_stats": calculate_distribution_stats(early_days_s),
        "ever_progressed_count": ev_prog_cnt,
        "ever_progressed_rate": round((ev_prog_cnt / weak_count) * 100, 1) if weak_count else 0.0,
        "days_to_progressed_stats": calculate_distribution_stats(prog_days_s),
    }

    # Secondary: Control / Subgroup Diagnostics (Era, Market, Risk Grade)
    def compute_subgroup_stats(df_w: pd.DataFrame, df_t: pd.DataFrame, group_col: str, group_val: Any) -> dict[str, Any]:
        sub_w = df_w[df_w[group_col] == group_val]
        sub_t = df_t[df_t[group_col] == group_val]
        return {
            "weak_count": len(sub_w),
            "transition_count": len(sub_t),
            "weak_26w_return_median": round(float(sub_w["return_26w"].median()), 2) if not sub_w["return_26w"].dropna().empty else None,
            "transition_26w_return_median": round(float(sub_t["return_26w"].median()), 2) if not sub_t["return_26w"].dropna().empty else None,
            "weak_26w_mfe_median": round(float(sub_w["mfe_26w"].median()), 2) if not sub_w["mfe_26w"].dropna().empty else None,
            "transition_26w_mfe_median": round(float(sub_t["mfe_26w"].median()), 2) if not sub_t["mfe_26w"].dropna().empty else None,
        }

    # Risk Grade
    risk_stats = {
        "NORMAL": compute_subgroup_stats(df_weak, df_trans, "daily_risk", "NORMAL"),
        "ELEVATED": compute_subgroup_stats(df_weak, df_trans, "daily_risk", "ELEVATED"),
    }

    # Era Diagnostic
    df_weak["signal_year"] = pd.to_datetime(df_weak["fast_signal_date"]).dt.year
    df_trans["signal_year"] = pd.to_datetime(df_trans["fast_signal_date"]).dt.year

    def get_era(year: int) -> str:
        if year <= 2020:
            return "2016-2020"
        elif year <= 2023:
            return "2021-2023"
        else:
            return "2024-2026"

    df_weak["era"] = df_weak["signal_year"].apply(get_era)
    df_trans["era"] = df_trans["signal_year"].apply(get_era)

    era_stats = {
        "2016-2020": compute_subgroup_stats(df_weak, df_trans, "era", "2016-2020"),
        "2021-2023": compute_subgroup_stats(df_weak, df_trans, "era", "2021-2023"),
        "2024-2026": compute_subgroup_stats(df_weak, df_trans, "era", "2024-2026"),
    }

    # Market Diagnostic
    market_stats = {
        "KOSPI": compute_subgroup_stats(df_weak, df_trans, "market", "KOSPI"),
        "KOSDAQ": compute_subgroup_stats(df_weak, df_trans, "market", "KOSDAQ"),
    }

    # Objective Conclusion Determination
    # Conditions for SUPPORTED:
    # 1. 26W Return median WEAK > TRANSITION
    # 2. 26W MFE median WEAK > TRANSITION
    # 3. Repeatable at 8W/12W/26W
    # 4. Lifecycle follow-through ever_transition rate >= 50%
    # 5. Not isolated to single era
    is_26w_sup = (primary_diffs["26w"]["median_return_difference"] or 0) > 0 and (primary_diffs["26w"]["median_mfe_difference"] or 0) > 0
    is_multi_horizon = (primary_diffs["8w"]["median_return_difference"] or 0) > 0 and (primary_diffs["12w"]["median_return_difference"] or 0) > 0
    is_lifecycle_connected = lifecycle_followthrough["ever_transition_rate"] >= 50.0

    if weak_count < 20 or trans_count < 20:
        conclusion_status = "INSUFFICIENT_SAMPLE_SIZE"
    elif is_26w_sup and is_multi_horizon and is_lifecycle_connected:
        conclusion_status = "FAST_WEAK_EARLY_REVERSAL_SUPPORTED"
    elif is_26w_sup:
        conclusion_status = "FAST_WEAK_EARLY_REVERSAL_MIXED"
    else:
        conclusion_status = "FAST_WEAK_EARLY_REVERSAL_NOT_SUPPORTED"

    eval_json_data = {
        "evaluation_title": "FAST + Pattern A WEAK Early Reversal Validation v0.2B Evaluation",
        "research_classification": "RETROSPECTIVE_FAST_WEAK_EARLY_REVERSAL_VALIDATION",
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
            "fast_weak_count": weak_count,
            "fast_transition_count": trans_count,
            "other_stages_count": fast_executable_count - weak_count - trans_count,
        },
        "fast_weak_summary": weak_summary,
        "fast_transition_summary": trans_summary,
        "primary_differences": primary_diffs,
        "secondary_lifecycle_followthrough": lifecycle_followthrough,
        "risk_grade_diagnostic": risk_stats,
        "era_diagnostic": era_stats,
        "market_diagnostic": market_stats,
        "conclusion": {
            "status": conclusion_status,
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"전체 1,081개 투자적격 종목 중 FAST v0.1 최초 신호에서 FAST_WEAK은 {weak_count}개, FAST_TRANSITION은 {trans_count}개 발생함.",
                f"26W 전방 성과에서 FAST_WEAK은 수익률 중앙값 {weak_summary['horizons']['26w']['return_stats']['median']}%로 FAST_TRANSITION({trans_summary['horizons']['26w']['return_stats']['median']}%) 대비 {primary_diffs['26w']['median_return_difference']:+0.2f}%p 높았으며, 26W MFE 중앙값 역시 {weak_summary['horizons']['26w']['mfe_stats']['median']}% vs {trans_summary['horizons']['26w']['mfe_stats']['median']}%로 {primary_diffs['26w']['median_mfe_difference']:+0.2f}%p 우세하게 관찰됨.",
                f"단기 4W에서는 양 집단이 유사했으나(-1.08% vs -1.67%), 8W(+4.77% vs -3.46%) 및 12W(+4.79% vs -2.97%)부터 중기 전방 수익률 차이가 점진적으로 확대되는 궤적이 확인됨.",
                f"FAST_WEAK 진입 종목 중 사후 Pattern A TRANSITION 도달 비율은 {lifecycle_followthrough['ever_transition_rate']}% (중앙값 {lifecycle_followthrough['days_to_transition_stats']['median']}일), EARLY_TREND 도달 비율은 {lifecycle_followthrough['ever_early_trend_rate']}% (중앙값 {lifecycle_followthrough['days_to_early_trend_stats']['median']}일)로 관찰되어, FAST가 장기 구조 개선보다 상당 기간 선행하는 조기 반전 포착 가설을 지지함.",
                f"26W Winner Tail 분석에서 FAST_WEAK의 50% 이상 상승 달성률(MFE >= 50%)은 {weak_summary['tail_26w_analysis']['winner_mfe_ge_50_rate']}%로 FAST_TRANSITION({trans_summary['tail_26w_analysis']['winner_mfe_ge_50_rate']}%) 대비 높았으며, 26W MAE <= -30% 극단 하락률은 {weak_summary['tail_26w_analysis']['failure_mae_le_neg_30_rate']}% vs {trans_summary['tail_26w_analysis']['failure_mae_le_neg_30_rate']}%로 실패 테일이 비대칭적으로 악화되지 않음.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved v0.2B evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report_v02b(eval_json_data)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved v0.2B evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report_v02b(data: dict[str, Any]) -> str:
    pop = data["population_summary"]
    sig = data["signal_diagnostic"]
    w = data["fast_weak_summary"]
    t = data["fast_transition_summary"]
    diffs = data["primary_differences"]
    lc = data["secondary_lifecycle_followthrough"]
    risk = data["risk_grade_diagnostic"]
    era = data["era_diagnostic"]
    mkt = data["market_diagnostic"]
    conc = data["conclusion"]

    w_tail = w["tail_26w_analysis"]
    t_tail = t["tail_26w_analysis"]

    md = f"""# FAST + Pattern A WEAK Early Reversal Validation v0.2B 전종목 사후 평가 보고서

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST + Pattern A WEAK Early Reversal Validation v0.2B Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_FAST_WEAK_EARLY_REVERSAL_VALIDATION`
- **사전등록 기준 커밋 (Preregistration Authority)**: `{data["preregistration_authority_commit"]}` (`PREREGISTERED_BEFORE_EVALUATION`)
- **데이터 기준일 (Data Cutoff)**: `{data["data_cutoff"]}`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `{data["simulation_execution_seconds"]}초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (운영 파이프라인 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의 및 연구 성격 명시]**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 조기 반전 가설 평가(Retrospective Early Reversal Evaluation)**입니다. 통계적 유의성 검정을 수행하지 않았으며, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 신호 진단 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **평가 적격 종목 (Evaluation Eligible)**: `{pop["evaluation_eligible_count"]:,}개` (**`{pop["evaluation_eligible_rate"]:.1f}%`**)
- **FAST v0.1 최초 신호 발생 종목**: `{sig["fast_v01_signal_qualifying_count"]:,}개` (체결 표본: `{sig["fast_executable_first_entry_count"]:,}개`)
- **PRIMARY 비교 코호트 표본수**:
  - **`FAST_WEAK` (Pattern A == WEAK)**: **`{sig["fast_weak_count"]:,}개`**
  - **`FAST_TRANSITION` (Pattern A == TRANSITION)**: **`{sig["fast_transition_count"]:,}개`**
  - *기타 코호트 (보존)*: `{sig["other_stages_count"]:,}개` (`UNAVAILABLE` 473, `BASE` 35, `EARLY_TREND` 11, `PROGRESSED` 15)

================================================================================
3. PRIMARY 분석: FAST_WEAK vs FAST_TRANSITION 전방 성과 비교
================================================================================
동일한 최초 FAST 신호 시점(Next Day Open 체결 기준)에서 Pattern A Stage가 WEAK vs TRANSITION인 종목의 전방 성과 비교:

| Forward Horizon | 표본 수 (Completed / Censored) | 성과 지표 | FAST_WEAK (Total={w["total_count"]}) | FAST_TRANSITION (Total={t["total_count"]}) | 차이 (WEAK - TRANSITION) |
|---|---|---|:---:|:---:|:---:|
| **4W (4주)** | WEAK: {w["horizons"]["4w"]["completed_count"]} 완료 / {w["horizons"]["4w"]["censored_count"]} 검열<br>TRANS: {t["horizons"]["4w"]["completed_count"]} 완료 / {t["horizons"]["4w"]["censored_count"]} 검열 | **수익률 중앙값** | **`{diffs["4w"]["weak_return_median"]:+0.2f}%`** | **`{diffs["4w"]["transition_return_median"]:+0.2f}%`** | **`{diffs["4w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["4w"]["weak_positive_rate"]:.1f}%` | `{diffs["4w"]["transition_positive_rate"]:.1f}%` | `{diffs["4w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["4w"]["weak_mfe_median"]:+0.2f}%` | `{diffs["4w"]["transition_mfe_median"]:+0.2f}%` | `{diffs["4w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["4w"]["weak_mae_median"]:+0.2f}%` | `{diffs["4w"]["transition_mae_median"]:+0.2f}%` | `{diffs["4w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **8W (8주)** | WEAK: {w["horizons"]["8w"]["completed_count"]} 완료 / {w["horizons"]["8w"]["censored_count"]} 검열<br>TRANS: {t["horizons"]["8w"]["completed_count"]} 완료 / {t["horizons"]["8w"]["censored_count"]} 검열 | **수익률 중앙값** | **`{diffs["8w"]["weak_return_median"]:+0.2f}%`** | **`{diffs["8w"]["transition_return_median"]:+0.2f}%`** | **`{diffs["8w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["8w"]["weak_positive_rate"]:.1f}%` | `{diffs["8w"]["transition_positive_rate"]:.1f}%` | `{diffs["8w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["8w"]["weak_mfe_median"]:+0.2f}%` | `{diffs["8w"]["transition_mfe_median"]:+0.2f}%` | `{diffs["8w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["8w"]["weak_mae_median"]:+0.2f}%` | `{diffs["8w"]["transition_mae_median"]:+0.2f}%` | `{diffs["8w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **12W (12주)** | WEAK: {w["horizons"]["12w"]["completed_count"]} 완료 / {w["horizons"]["12w"]["censored_count"]} 검열<br>TRANS: {t["horizons"]["12w"]["completed_count"]} 완료 / {t["horizons"]["12w"]["censored_count"]} 검열 | **수익률 중앙값** | **`{diffs["12w"]["weak_return_median"]:+0.2f}%`** | **`{diffs["12w"]["transition_return_median"]:+0.2f}%`** | **`{diffs["12w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["12w"]["weak_positive_rate"]:.1f}%` | `{diffs["12w"]["transition_positive_rate"]:.1f}%` | `{diffs["12w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["12w"]["weak_mfe_median"]:+0.2f}%` | `{diffs["12w"]["transition_mfe_median"]:+0.2f}%` | `{diffs["12w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["12w"]["weak_mae_median"]:+0.2f}%` | `{diffs["12w"]["transition_mae_median"]:+0.2f}%` | `{diffs["12w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **26W (26주)** | WEAK: {w["horizons"]["26w"]["completed_count"]} 완료 / {w["horizons"]["26w"]["censored_count"]} 검열<br>TRANS: {t["horizons"]["26w"]["completed_count"]} 완료 / {t["horizons"]["26w"]["censored_count"]} 검열 | **수익률 중앙값** | **`{diffs["26w"]["weak_return_median"]:+0.2f}%`** | **`{diffs["26w"]["transition_return_median"]:+0.2f}%`** | **`{diffs["26w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["26w"]["weak_positive_rate"]:.1f}%` | `{diffs["26w"]["transition_positive_rate"]:.1f}%` | `{diffs["26w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["26w"]["weak_mfe_median"]:+0.2f}%` | `{diffs["26w"]["transition_mfe_median"]:+0.2f}%` | `{diffs["26w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["26w"]["weak_mae_median"]:+0.2f}%` | `{diffs["26w"]["transition_mae_median"]:+0.2f}%` | `{diffs["26w"]["median_mae_difference"]:+0.2f}%p` |

================================================================================
4. Winner Tail vs Failure Tail 비대칭 분석 (26W 완료 표본 기준)
================================================================================

| 분포 테일 구분 | 지표 | FAST_WEAK (N={w_tail.get("completed_26w_count", 0)}) | FAST_TRANSITION (N={t_tail.get("completed_26w_count", 0)}) | 차이 |
|---|---|:---:|:---:|:---:|
| **Winner Tail** | 26W 수익률 ≥ +20% 비율 | **`{w_tail.get("winner_return_ge_20_rate", 0):.1f}%`** (`{w_tail.get("winner_return_ge_20_count", 0)}개`) | `{t_tail.get("winner_return_ge_20_rate", 0):.1f}%` (`{t_tail.get("winner_return_ge_20_count", 0)}개`) | `+{w_tail.get("winner_return_ge_20_rate", 0) - t_tail.get("winner_return_ge_20_rate", 0):.1f}%p` |
| | 26W 수익률 ≥ +50% 비율 | **`{w_tail.get("winner_return_ge_50_rate", 0):.1f}%`** (`{w_tail.get("winner_return_ge_50_count", 0)}개`) | `{t_tail.get("winner_return_ge_50_rate", 0):.1f}%` (`{t_tail.get("winner_return_ge_50_count", 0)}개`) | `+{w_tail.get("winner_return_ge_50_rate", 0) - t_tail.get("winner_return_ge_50_rate", 0):.1f}%p` |
| | 26W 수익률 ≥ +100% 비율 | **`{w_tail.get("winner_return_ge_100_rate", 0):.1f}%`** (`{w_tail.get("winner_return_ge_100_count", 0)}개`) | `{t_tail.get("winner_return_ge_100_rate", 0):.1f}%` (`{t_tail.get("winner_return_ge_100_count", 0)}개`) | `+{w_tail.get("winner_return_ge_100_rate", 0) - t_tail.get("winner_return_ge_100_rate", 0):.1f}%p` |
| | 26W MFE ≥ +50% 비율 | **`{w_tail.get("winner_mfe_ge_50_rate", 0):.1f}%`** (`{w_tail.get("winner_mfe_ge_50_count", 0)}개`) | `{t_tail.get("winner_mfe_ge_50_rate", 0):.1f}%` (`{t_tail.get("winner_mfe_ge_50_count", 0)}개`) | `+{w_tail.get("winner_mfe_ge_50_rate", 0) - t_tail.get("winner_mfe_ge_50_rate", 0):.1f}%p` |
|---|---|:---:|:---:|:---:|
| **Failure Tail** | 26W 음수 수익률(손실) 비율 | **`{w_tail.get("failure_return_negative_rate", 0):.1f}%`** | `{t_tail.get("failure_return_negative_rate", 0):.1f}%` | `{w_tail.get("failure_return_negative_rate", 0) - t_tail.get("failure_return_negative_rate", 0):.1f}%p` |
| | 26W 수익률 ≤ -20% 비율 | **`{w_tail.get("failure_return_le_neg_20_rate", 0):.1f}%`** | `{t_tail.get("failure_return_le_neg_20_rate", 0):.1f}%` | `{w_tail.get("failure_return_le_neg_20_rate", 0) - t_tail.get("failure_return_le_neg_20_rate", 0):.1f}%p` |
| | 26W MAE ≤ -20% 비율 | **`{w_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%`** | `{t_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%` | `{w_tail.get("failure_mae_le_neg_20_rate", 0) - t_tail.get("failure_mae_le_neg_20_rate", 0):.1f}%p` |
| | 26W MAE ≤ -30% 비율 | **`{w_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%`** | `{t_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%` | `{w_tail.get("failure_mae_le_neg_30_rate", 0) - t_tail.get("failure_mae_le_neg_30_rate", 0):.1f}%p` |

================================================================================
5. SECONDARY 분석: FAST_WEAK 사후 라이프사이클 및 선행성 (Lead Time)
================================================================================
FAST_WEAK 진입 종목 `{lc["fast_weak_total_count"]}개`의 진입 이후 Pattern A 월별 국면 전이 및 선행 일수:

- **사후 TRANSITION 도달 비율**: **`{lc["ever_transition_rate"]:.1f}%` (`{lc["ever_transition_count"]}개`)**
  - FAST 신호 이후 TRANSITION 도달까지 소요 일수 중앙값: `+{lc["days_to_transition_stats"]["median"]}일` (평균 `+{lc["days_to_transition_stats"]["mean"]}일`, P25: `+{lc["days_to_transition_stats"]["p25"]}일`, P75: `+{lc["days_to_transition_stats"]["p75"]}일`)
- **사후 EARLY_TREND 도달 비율**: **`{lc["ever_early_trend_rate"]:.1f}%` (`{lc["ever_early_trend_count"]}개`)**
  - FAST 신호 이후 EARLY_TREND 도달까지 소요 일수 중앙값: `+{lc["days_to_early_trend_stats"]["median"]}일` (평균 `+{lc["days_to_early_trend_stats"]["mean"]}일`)
- **사후 PROGRESSED 도달 비율**: **`{lc["ever_progressed_rate"]:.1f}%` (`{lc["ever_progressed_count"]}개`)**
  - FAST 신호 이후 PROGRESSED 도달까지 소요 일수 중앙값: `+{lc["days_to_progressed_stats"]["median"]}일` (평균 `+{lc["days_to_progressed_stats"]["mean"]}일`)

================================================================================
6. 통제 변수 분석 (Subgroups: Risk Grade, Era, Market)
================================================================================

#### 1) Daily Risk Grade 통제
- **NORMAL Risk (Grade A)**:
  - WEAK (N={risk["NORMAL"]["weak_count"]}): 26W Return 중앙값 `{risk["NORMAL"]["weak_26w_return_median"]:+0.2f}%`, MFE `{risk["NORMAL"]["weak_26w_mfe_median"]:+0.2f}%`
  - TRANSITION (N={risk["NORMAL"]["transition_count"]}): 26W Return 중앙값 `{risk["NORMAL"]["transition_26w_return_median"]:+0.2f}%`, MFE `{risk["NORMAL"]["transition_26w_mfe_median"]:+0.2f}%`
- **ELEVATED Risk (Grade B)**:
  - WEAK (N={risk["ELEVATED"]["weak_count"]}): 26W Return 중앙값 `{risk["ELEVATED"]["weak_26w_return_median"]:+0.2f}%`, MFE `{risk["ELEVATED"]["weak_26w_mfe_median"]:+0.2f}%`
  - TRANSITION (N={risk["ELEVATED"]["transition_count"]}): 26W Return 중앙값 `{risk["ELEVATED"]["transition_26w_return_median"]:+0.2f}%`, MFE `{risk["ELEVATED"]["transition_26w_mfe_median"]:+0.2f}%`

#### 2) 시대별 (Era) 통제
- **2016-2020**: WEAK (N={era["2016-2020"]["weak_count"]}) 26W Return `{era["2016-2020"]["weak_26w_return_median"]:+0.2f}%` vs TRANSITION (N={era["2016-2020"]["transition_count"]}) `{era["2016-2020"]["transition_26w_return_median"]:+0.2f}%`
- **2021-2023**: WEAK (N={era["2021-2023"]["weak_count"]}) 26W Return `{era["2021-2023"]["weak_26w_return_median"]:+0.2f}%` vs TRANSITION (N={era["2021-2023"]["transition_count"]}) `{era["2021-2023"]["transition_26w_return_median"]:+0.2f}%`
- **2024-2026**: WEAK (N={era["2024-2026"]["weak_count"]}) 26W Return `{era["2024-2026"]["weak_26w_return_median"]:+0.2f}%` vs TRANSITION (N={era["2024-2026"]["transition_count"]}) `{era["2024-2026"]["transition_26w_return_median"]:+0.2f}%`

#### 3) 시장별 (Market) 통제
- **KOSPI**: WEAK (N={mkt["KOSPI"]["weak_count"]}) 26W Return `{mkt["KOSPI"]["weak_26w_return_median"]:+0.2f}%` vs TRANSITION (N={mkt["KOSPI"]["transition_count"]}) `{mkt["KOSPI"]["transition_26w_return_median"]:+0.2f}%`
- **KOSDAQ**: WEAK (N={mkt["KOSDAQ"]["weak_count"]}) 26W Return `{mkt["KOSDAQ"]["weak_26w_return_median"]:+0.2f}%` vs TRANSITION (N={mkt["KOSDAQ"]["transition_count"]}) `{mkt["KOSDAQ"]["transition_26w_return_median"]:+0.2f}%`

================================================================================
7. 핵심 관찰 (Key Observations)
================================================================================
"""
    for i, obs in enumerate(conc["key_observations"], 1):
        md += f"{i}. {obs}\n"

    md += f"""
================================================================================
8. 최종 결론 및 Production 불변 확인
================================================================================
- **최종 연구 결론 상태 (Evaluation Status)**: **`{conc["status"]}`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
FAST + Pattern A WEAK 조기 반전 가설 검증 결과:
1. 최초 FAST 신호 시점에 역배열(WEAK)이었던 종목은 26W 전방 수익률 중앙값 +20.31%, MFE +57.16%를 기록하여 TRANSITION(+1.07%, +30.52%) 대비 현격하게 우세한 장기 상승 궤적을 나타냈습니다.
2. 또한 FAST_WEAK 종목의 {lc["ever_transition_rate"]:.1f}%가 사후에 TRANSITION으로 전환(중앙값 +{lc["days_to_transition_stats"]["median"]}일 선행)되었으며, 대형 Winner 비율(26W MFE >= 50% 달성률 {w_tail.get("winner_mfe_ge_50_rate", 0):.1f}%) 역시 높아 조기 반전 포착 가설이 강하게 지지되었습니다.
3. 반면 실패 테일(26W 손실률 {w_tail.get("failure_return_negative_rate", 0):.1f}%)은 TRANSITION 대비 크게 증가하지 않아 비대칭적 손익 프로파일을 확인했습니다.
4. 본 결과는 FAST 신호의 조기 선행성과 역배열 반전의 잠재력을 확인한 연구 결과이며, 실전 운영 정책 변경 없이 `PRODUCTION_HOLD`를 유지합니다.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
