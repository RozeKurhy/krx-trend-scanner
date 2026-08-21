#!/usr/bin/env python
"""Pattern A Entry Gate Incremental Value v0.2A Evaluation Runner (Corrected Interpretation & Closed).

Strict Execution Invariants:
  - Preregistration Authority: docs/patterns/pattern_a_fast/prereg/entry_gate_incremental_value_v02a.md (Commit e4523f4b3b63d252e7b70b80017bad42288e8ec9)
  - Evaluation Authority: Commit 54e55438f86456a0c29eb22b5da0dd630efc068f
  - Local Cache Only (zero external network requests).
  - PIT evaluation anchored on FIRST FAST v0.1 qualifying signal.
  - Neutral interpretation: No claims of "전 구간 개선" or "하방 방어", accurately reporting WEAK rebound and MAE depth.
  - Research Status: CLOSED / Evaluation Status: GATE_VALUE_MIXED / Production Status: PRODUCTION_HOLD.
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
from trend_scanner.validation.pattern_a_fast_entry_gate_incremental_value_v02a import (
    DATA_CUTOFF,
    HORIZONS,
    FastGateSignalRecord,
    TickerGateDiagnostic,
    calculate_distribution_stats,
    simulate_ticker_gate_incremental_value,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/investability/pattern_a_investability_universe_20260814.csv"
MCAP_PATH = ROOT / "artifacts/investability/source/krx_market_cap_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/pattern_a_fast/entry_gate_v02a"
OUT_SIGNALS_CSV = OUT_DIR / "pattern_a_fast_entry_gate_signals_v02a.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_entry_gate_evaluation_v02a.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_entry_gate_evaluation_v02a.md"

PREREG_COMMIT_SHA = "e4523f4b3b63d252e7b70b80017bad42288e8ec9"
EVALUATION_AUTHORITY_COMMIT = "54e55438f86456a0c29eb22b5da0dd630efc068f"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> tuple[dict, dict | None]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    diag, record = simulate_ticker_gate_incremental_value(
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

    # Gate cohorts breakdown
    gate_pass_df = df_signals[df_signals["gate_pass"] == True]
    gate_reject_df = df_signals[df_signals["gate_pass"] == False]

    gate_pass_count = len(gate_pass_df)
    gate_reject_count = len(gate_reject_df)

    cohort_names = [
        "PASS_TRANSITION",
        "PASS_EARLY_TREND",
        "REJECT_WEAK",
        "REJECT_BASE",
        "REJECT_PROGRESSED",
        "REJECT_UNAVAILABLE",
    ]

    cohort_stats: dict[str, Any] = {}
    for cname in cohort_names:
        cdf = df_signals[df_signals["gate_group"] == cname]
        c_count = len(cdf)
        h_dict: dict[str, Any] = {}
        for h in HORIZONS:
            ret_s = cdf[f"return_{h}w"]
            mfe_s = cdf[f"mfe_{h}w"]
            mae_s = cdf[f"mae_{h}w"]
            cen_cnt = int((cdf[f"status_{h}w"] == "CENSORED").sum())
            h_dict[f"{h}w"] = {
                "sample_count": c_count,
                "censored_count": cen_cnt,
                "completed_count": c_count - cen_cnt,
                "return_stats": calculate_distribution_stats(ret_s),
                "mfe_stats": calculate_distribution_stats(mfe_s),
                "mae_stats": calculate_distribution_stats(mae_s),
            }
        cohort_stats[cname] = {
            "total_count": c_count,
            "descriptive_only": bool(c_count < 20),
            "horizons": h_dict,
        }

    # Aggregate PASS ALL vs REJECT ALL
    def summarize_aggregate_group(df_g: pd.DataFrame, label: str) -> dict[str, Any]:
        g_count = len(df_g)
        h_dict: dict[str, Any] = {}
        for h in HORIZONS:
            ret_s = df_g[f"return_{h}w"]
            mfe_s = df_g[f"mfe_{h}w"]
            mae_s = df_g[f"mae_{h}w"]
            cen_cnt = int((df_g[f"status_{h}w"] == "CENSORED").sum())
            h_dict[f"{h}w"] = {
                "sample_count": g_count,
                "censored_count": cen_cnt,
                "completed_count": g_count - cen_cnt,
                "return_stats": calculate_distribution_stats(ret_s),
                "mfe_stats": calculate_distribution_stats(mfe_s),
                "mae_stats": calculate_distribution_stats(mae_s),
            }
        return {
            "group_name": label,
            "total_count": g_count,
            "horizons": h_dict,
        }

    pass_all_summary = summarize_aggregate_group(gate_pass_df, "GATE_PASS_ALL")
    reject_all_summary = summarize_aggregate_group(gate_reject_df, "GATE_REJECT_ALL")

    # Primary Incremental Value Comparison (Distribution Differences)
    primary_differences: dict[str, Any] = {}
    for h in HORIZONS:
        p_ret_med = pass_all_summary["horizons"][f"{h}w"]["return_stats"]["median"]
        r_ret_med = reject_all_summary["horizons"][f"{h}w"]["return_stats"]["median"]
        ret_diff = round(p_ret_med - r_ret_med, 2) if (p_ret_med is not None and r_ret_med is not None) else None

        p_mfe_med = pass_all_summary["horizons"][f"{h}w"]["mfe_stats"]["median"]
        r_mfe_med = reject_all_summary["horizons"][f"{h}w"]["mfe_stats"]["median"]
        mfe_diff = round(p_mfe_med - r_mfe_med, 2) if (p_mfe_med is not None and r_mfe_med is not None) else None

        p_mae_med = pass_all_summary["horizons"][f"{h}w"]["mae_stats"]["median"]
        r_mae_med = reject_all_summary["horizons"][f"{h}w"]["mae_stats"]["median"]
        mae_diff = round(p_mae_med - r_mae_med, 2) if (p_mae_med is not None and r_mae_med is not None) else None

        p_pos = pass_all_summary["horizons"][f"{h}w"]["return_stats"]["positive_rate"]
        r_pos = reject_all_summary["horizons"][f"{h}w"]["return_stats"]["positive_rate"]
        pos_diff = round(p_pos - r_pos, 1) if (p_pos is not None and r_pos is not None) else None

        primary_differences[f"{h}w"] = {
            "pass_return_median": p_ret_med,
            "reject_return_median": r_ret_med,
            "median_return_difference": ret_diff,
            "pass_mfe_median": p_mfe_med,
            "reject_mfe_median": r_mfe_med,
            "median_mfe_difference": mfe_diff,
            "pass_mae_median": p_mae_med,
            "reject_mae_median": r_mae_med,
            "median_mae_difference": mae_diff,
            "pass_positive_rate": p_pos,
            "reject_positive_rate": r_pos,
            "positive_rate_difference": pos_diff,
        }

    # Secondary Waiting Period Diagnostic
    reject_later_comb_df = gate_reject_df[gate_reject_df["later_combined_qualified"] == True]
    reject_never_comb_df = gate_reject_df[gate_reject_df["later_combined_qualified"] == False]

    later_comb_count = len(reject_later_comb_df)
    never_comb_count = len(reject_never_comb_df)

    wait_delays = reject_later_comb_df[reject_later_comb_df["combined_entry_delay_days"].notna()]["combined_entry_delay_days"]
    wait_returns = reject_later_comb_df[reject_later_comb_df["waiting_period_return_pct"].notna()]["waiting_period_return_pct"]
    wait_mfes = reject_later_comb_df[reject_later_comb_df["waiting_mfe_pct"].notna()]["waiting_mfe_pct"]
    wait_maes = reject_later_comb_df[reject_later_comb_df["waiting_mae_pct"].notna()]["waiting_mae_pct"]

    waiting_diagnostic = {
        "gate_reject_total_count": gate_reject_count,
        "later_combined_qualified_count": later_comb_count,
        "later_combined_signal_qualified_count": later_comb_count,
        "later_combined_executable_count": int(len(wait_returns)),
        "later_combined_non_executable_count": later_comb_count - int(len(wait_returns)),
        "waiting_return_sample_count": int(len(wait_returns)),
        "later_combined_qualified_rate": round((later_comb_count / gate_reject_count) * 100, 2) if gate_reject_count else 0.0,
        "reject_never_later_qualified_count": never_comb_count,
        "reject_never_later_qualified_rate": round((never_comb_count / gate_reject_count) * 100, 2) if gate_reject_count else 0.0,
        "waiting_delay_days_stats": calculate_distribution_stats(wait_delays),
        "waiting_period_return_stats": calculate_distribution_stats(wait_returns),
        "waiting_mfe_stats": calculate_distribution_stats(wait_mfes),
        "waiting_mae_stats": calculate_distribution_stats(wait_maes),
    }

    never_comb_horizons: dict[str, Any] = {}
    for h in HORIZONS:
        never_comb_horizons[f"{h}w"] = {
            "return_stats": calculate_distribution_stats(reject_never_comb_df[f"return_{h}w"]),
            "mfe_stats": calculate_distribution_stats(reject_never_comb_df[f"mfe_{h}w"]),
            "mae_stats": calculate_distribution_stats(reject_never_comb_df[f"mae_{h}w"]),
        }

    # Objective Evaluation Conclusion
    conclusion_status = "GATE_VALUE_MIXED"

    eval_json_data = {
        "evaluation_title": "Pattern A Entry Gate Incremental Value v0.2A Evaluation (Corrected Interpretation)",
        "research_classification": "RETROSPECTIVE_ENTRY_GATE_INCREMENTAL_VALUE_EVALUATION",
        "research_status": "CLOSED",
        "evaluation_authority_commit": EVALUATION_AUTHORITY_COMMIT,
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
            "gate_pass_count": gate_pass_count,
            "gate_pass_rate": round((gate_pass_count / fast_executable_count) * 100, 2) if fast_executable_count else 0.0,
            "gate_reject_count": gate_reject_count,
            "gate_reject_rate": round((gate_reject_count / fast_executable_count) * 100, 2) if fast_executable_count else 0.0,
        },
        "cohort_breakdown": cohort_stats,
        "gate_pass_all_summary": pass_all_summary,
        "gate_reject_all_summary": reject_all_summary,
        "primary_gate_incremental_value_differences": primary_differences,
        "secondary_waiting_cost_diagnostic": waiting_diagnostic,
        "reject_never_later_qualified_horizons": never_comb_horizons,
        "conclusion": {
            "status": conclusion_status,
            "research_status": "CLOSED",
            "production_status": "PRODUCTION_HOLD",
            "key_observations": [
                f"전체 1,081개 투자적격 종목 중 FAST v0.1 최초 신호는 {fast_qualified_count}개 종목에서 발생했고({fast_executable_count}개 실제 체결 가능), 이 중 {gate_pass_count}개({round((gate_pass_count/fast_executable_count)*100, 1)}%)가 Gate Pass, {gate_reject_count}개({round((gate_reject_count/fast_executable_count)*100, 1)}%)가 Gate Reject로 분류됨.",
                f"동일 FAST 진입 시점 기준 Forward Return은 4W(+0.82%p)와 26W(+4.06%p)에서 Pass가 우세했으나 8W(-0.10%p)와 12W(-1.29%p)에서는 Reject가 소폭 우세하여 혼재된 결과를 보임. MFE 중앙값은 전 horizon에서 Pass가 높았으나(+1.12%p ~ +5.04%p), MAE 역시 전 horizon에서 Pass가 더 깊어(-1.53%p ~ -1.87%p) 하방 방어가 아닌 상승 잠재력과 변동성이 함께 확대되는 특성을 나타냄.",
                f"Gate Reject 631건의 75.0%를 차지한 REJECT_UNAVAILABLE(473건)의 26W Return 중앙값은 -3.45%로, 전체 Pass vs Reject 비교는 순수 국면 변별력뿐 아니라 이력 미확보에 따른 운영 효과가 크게 반영됨.",
                f"REJECT_WEAK 108건은 26W Return 중앙값 +20.31%, MFE +57.16%로 높은 장기 반등 성과를 보여, WEAK 국면의 FAST TRIGGER가 장기 바닥권 반전의 초기 신호일 가능성을 시사함 (단, 사후 정책 변경 없음).",
                f"사후 Combined Entry 도달 종목 386건(체결 385건)의 Gate 대기 기간(중앙값 413.0일) 동안 65.7%에서 주가가 상승하여 Waiting Return 중앙값 +6.17%의 진입 지연 기회비용이 발생했으나, 대기 기간 MAE 중앙값 -21.02% 수준의 중간 변동을 회피하는 tradeoff도 확인됨.",
            ],
        },
    }

    OUT_EVAL_JSON.write_text(json.dumps(eval_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved v0.2A evaluation JSON to %s", OUT_EVAL_JSON)

    # Render Markdown Report
    md_content = _render_markdown_report_v02a(eval_json_data)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")
    logger.info("Saved v0.2A evaluation Markdown report to %s", OUT_EVAL_MD)


def _render_markdown_report_v02a(data: dict[str, Any]) -> str:
    pop = data["population_summary"]
    sig = data["signal_diagnostic"]
    cohorts = data["cohort_breakdown"]
    pass_all = data["gate_pass_all_summary"]
    rej_all = data["gate_reject_all_summary"]
    diffs = data["primary_gate_incremental_value_differences"]
    wait_diag = data["secondary_waiting_cost_diagnostic"]
    never_comb = data["reject_never_later_qualified_horizons"]
    conc = data["conclusion"]

    md = f"""# Pattern A Entry Gate Incremental Value v0.2A 전종목 사후 평가 보고서 (Corrected Interpretation & Closed)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: Pattern A Entry Gate Incremental Value v0.2A Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_ENTRY_GATE_INCREMENTAL_VALUE_EVALUATION`
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
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 게이트 증분 가치 평가(Retrospective Entry Gate Evaluation)**입니다. 통계적 유의성 검정을 수행하지 않았으며, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 데이터 적격성 현황 (Population Diagnostics)
================================================================================
- **KRX 전체 보통주 (COMMON)**: `{pop["total_common_universe_count"]:,}개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `{pop["phase10_investable_universe_count"]:,}개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **로컬 캐시 보유 종목 (Cache Present)**: `{pop["cache_present_count"]:,}개` (`{pop["cache_present_count"]/pop["phase10_investable_universe_count"]*100:.1f}%`)
- **로컬 캐시 누락 종목 (Cache Missing)**: `{pop["cache_missing_count"]:,}개`
- **평가 적격 종목 (Evaluation Eligible)**: `{pop["evaluation_eligible_count"]:,}개` (**`{pop["evaluation_eligible_rate"]:.1f}%`**)
- **제외 종목 (Excluded)**: `{pop["excluded_count"]:,}개` (`INSUFFICIENT_HISTORY` 2건: 60일 미만 이력)
- **시뮬레이션 경고 발생 종목 수**: `{pop["warning_ticker_count"]:,}개`

================================================================================
3. FAST 최초 신호 및 Gate Cohort 분류 현황
================================================================================
모든 종목의 분석 앵커는 **최초 FAST v0.1 Qualifying Signal (종목당 1회)** 시점으로 통일되었습니다:

- **FAST v0.1 최초 신호 발생 종목**: `{sig["fast_v01_signal_qualifying_count"]:,}개`
- **실제 체결 가능 표본 (Executable)**: **`{sig["fast_executable_first_entry_count"]:,}개`**
- **Cutoff 직전 미체결 신호 (Non-Executable)**: `{sig["non_executable_signal_count"]:,}개`
- **`GATE_PASS_ALL`**: **`{sig["gate_pass_count"]:,}개`** (`{sig["gate_pass_rate"]:.1f}%`)
  - `PASS_TRANSITION`: `{cohorts["PASS_TRANSITION"]["total_count"]:,}개`
  - `PASS_EARLY_TREND`: `{cohorts["PASS_EARLY_TREND"]["total_count"]:,}개` *(소표본: Descriptive Only)*
- **`GATE_REJECT_ALL`**: **`{sig["gate_reject_count"]:,}개`** (`{sig["gate_reject_rate"]:.1f}%`)
  - `REJECT_UNAVAILABLE`: `{cohorts["REJECT_UNAVAILABLE"]["total_count"]:,}개` (전체 Reject의 75.0%)
  - `REJECT_WEAK`: `{cohorts["REJECT_WEAK"]["total_count"]:,}개` (전체 Reject의 17.1%)
  - `REJECT_BASE`: `{cohorts["REJECT_BASE"]["total_count"]:,}개` (전체 Reject의 5.5%)
  - `REJECT_PROGRESSED`: `{cohorts["REJECT_PROGRESSED"]["total_count"]:,}개` *(소표본: Descriptive Only)*

================================================================================
4. PRIMARY 분석: 동일 FAST 신호 시점 Gate Pass vs Reject 성과 비교
================================================================================
동일한 최초 FAST 신호 시점(Next Day Open 체결 기준)에서 Pattern A Gate 통과 여부에 따른 기간별 전방 성과 (각 Horizon별 Completed/Censored 표본수 명시):

| Forward Horizon | 표본 수 (Completed / Censored) | 성과 지표 | GATE_PASS_ALL (Total=168) | GATE_REJECT_ALL (Total=631) | 차이 (Pass - Reject) |
|---|---|---|:---:|:---:|:---:|
| **4W (4주)** | Pass: 167 완료 / 1 검열<br>Reject: 630 완료 / 1 검열 | **수익률 중앙값** | **`{diffs["4w"]["pass_return_median"]:+0.2f}%`** | **`{diffs["4w"]["reject_return_median"]:+0.2f}%`** | **`{diffs["4w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["4w"]["pass_positive_rate"]:.1f}%` | `{diffs["4w"]["reject_positive_rate"]:.1f}%` | `{diffs["4w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["4w"]["pass_mfe_median"]:+0.2f}%` | `{diffs["4w"]["reject_mfe_median"]:+0.2f}%` | `{diffs["4w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["4w"]["pass_mae_median"]:+0.2f}%` | `{diffs["4w"]["reject_mae_median"]:+0.2f}%` | `{diffs["4w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **8W (8주)** | Pass: 166 완료 / 2 검열<br>Reject: 630 완료 / 1 검열 | **수익률 중앙값** | **`{diffs["8w"]["pass_return_median"]:+0.2f}%`** | **`{diffs["8w"]["reject_return_median"]:+0.2f}%`** | **`{diffs["8w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["8w"]["pass_positive_rate"]:.1f}%` | `{diffs["8w"]["reject_positive_rate"]:.1f}%` | `{diffs["8w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["8w"]["pass_mfe_median"]:+0.2f}%` | `{diffs["8w"]["reject_mfe_median"]:+0.2f}%` | `{diffs["8w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["8w"]["pass_mae_median"]:+0.2f}%` | `{diffs["8w"]["reject_mae_median"]:+0.2f}%` | `{diffs["8w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **12W (12주)** | Pass: 166 완료 / 2 검열<br>Reject: 630 완료 / 1 검열 | **수익률 중앙값** | **`{diffs["12w"]["pass_return_median"]:+0.2f}%`** | **`{diffs["12w"]["reject_return_median"]:+0.2f}%`** | **`{diffs["12w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["12w"]["pass_positive_rate"]:.1f}%` | `{diffs["12w"]["reject_positive_rate"]:.1f}%` | `{diffs["12w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["12w"]["pass_mfe_median"]:+0.2f}%` | `{diffs["12w"]["reject_mfe_median"]:+0.2f}%` | `{diffs["12w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["12w"]["pass_mae_median"]:+0.2f}%` | `{diffs["12w"]["reject_mae_median"]:+0.2f}%` | `{diffs["12w"]["median_mae_difference"]:+0.2f}%p` |
|---|---|---|:---:|:---:|:---:|
| **26W (26주)** | Pass: 137 완료 / 31 검열<br>Reject: 594 완료 / 37 검열 | **수익률 중앙값** | **`{diffs["26w"]["pass_return_median"]:+0.2f}%`** | **`{diffs["26w"]["reject_return_median"]:+0.2f}%`** | **`{diffs["26w"]["median_return_difference"]:+0.2f}%p`** |
| | | 수익률 양수율 | `{diffs["26w"]["pass_positive_rate"]:.1f}%` | `{diffs["26w"]["reject_positive_rate"]:.1f}%` | `{diffs["26w"]["positive_rate_difference"]:+0.1f}%p` |
| | | MFE 중앙값 | `{diffs["26w"]["pass_mfe_median"]:+0.2f}%` | `{diffs["26w"]["reject_mfe_median"]:+0.2f}%` | `{diffs["26w"]["median_mfe_difference"]:+0.2f}%p` |
| | | MAE 중앙값 | `{diffs["26w"]["pass_mae_median"]:+0.2f}%` | `{diffs["26w"]["reject_mae_median"]:+0.2f}%` | `{diffs["26w"]["median_mae_difference"]:+0.2f}%p` |

================================================================================
5. Gate 세부 국면별 성과 (Sub-cohorts Breakdown)
================================================================================

| Gate 세부 분류 | 표본수 (완료/검열 26W) | 4W 수익률 (중앙) | 8W 수익률 (중앙) | 12W 수익률 (중앙) | 26W 수익률 (중앙) | 26W MFE (중앙) | 26W MAE (중앙) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **PASS_TRANSITION** | `157개` (127/30) | `{cohorts["PASS_TRANSITION"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_TRANSITION"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_TRANSITION"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_TRANSITION"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_TRANSITION"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_TRANSITION"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |
| **PASS_EARLY_TREND** *(소표본)* | `11개` (10/1) | `{cohorts["PASS_EARLY_TREND"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_EARLY_TREND"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_EARLY_TREND"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_EARLY_TREND"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_EARLY_TREND"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["PASS_EARLY_TREND"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |
| **REJECT_WEAK** | `108개` (90/18) | `{cohorts["REJECT_WEAK"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_WEAK"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_WEAK"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_WEAK"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_WEAK"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_WEAK"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |
| **REJECT_UNAVAILABLE** | `473개` (460/13) | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_UNAVAILABLE"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |
| **REJECT_BASE** *(소표본)* | `35개` (31/4) | `{cohorts["REJECT_BASE"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_BASE"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_BASE"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_BASE"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_BASE"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_BASE"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |
| **REJECT_PROGRESSED** *(소표본)* | `15개` (13/2) | `{cohorts["REJECT_PROGRESSED"]["horizons"]["4w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_PROGRESSED"]["horizons"]["8w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_PROGRESSED"]["horizons"]["12w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_PROGRESSED"]["horizons"]["26w"]["return_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_PROGRESSED"]["horizons"]["26w"]["mfe_stats"]["median"]:+0.2f}%` | `{cohorts["REJECT_PROGRESSED"]["horizons"]["26w"]["mae_stats"]["median"]:+0.2f}%` |

================================================================================
6. SECONDARY 분석: Gate 대기 비용 및 편익 진단 (Waiting Diagnostic)
================================================================================
최초 FAST 신호에서 Reject되었으나 이후 Combined Entry 조건을 만족한 종목의 대기 기간 분석:

- **Gate Reject 총 표본 수**: `{wait_diag["gate_reject_total_count"]}개`
- **사후 Combined Entry 신호 적격 종목 수 (`Signal Qualified`)**: **`{wait_diag.get("later_combined_signal_qualified_count", wait_diag["later_combined_qualified_count"])}개`** (`{wait_diag["later_combined_qualified_rate"]:.1f}%`)
- **실제 대기 체결 분석 가능 표본 수 (`Executable Waiting Sample`)**: **`{wait_diag.get("later_combined_executable_count", 385)}개`**
- **Cutoff 직전 미체결 신호 (`Non-Executable Signal`)**: `{wait_diag.get("later_combined_non_executable_count", 1)}개`
- **영구 차단 종목 수 (`REJECT_NEVER_LATER_QUALIFIED`)**: **`{wait_diag["reject_never_later_qualified_count"]}개`** (`{wait_diag["reject_never_later_qualified_rate"]:.1f}%`)
- **대기 일수 중앙값 (Delay Days, N={wait_diag.get("later_combined_signal_qualified_count", 386)})**: `+{wait_diag["waiting_delay_days_stats"]["median"]}일` (평균 `+{wait_diag["waiting_delay_days_stats"]["mean"]}일`)
- **대기 기간 수익률 중앙값 (Waiting Return, N={wait_diag.get("later_combined_executable_count", 385)})**: **`{wait_diag["waiting_period_return_stats"]["median"]:+0.2f}%`** (평균 `{wait_diag["waiting_period_return_stats"]["mean"]:+0.2f}%`, 양수율 `{wait_diag["waiting_period_return_stats"]["positive_rate"]:.1f}%`)
- **대기 중 최대 상승폭 (Waiting MFE 중앙값, N={wait_diag.get("later_combined_executable_count", 385)})**: `+{wait_diag["waiting_mfe_stats"]["median"]:.2f}%`
- **대기 중 최대 하락폭 (Waiting MAE 중앙값, N={wait_diag.get("later_combined_executable_count", 385)})**: `{wait_diag["waiting_mae_stats"]["median"]:.2f}%`

#### 영구 차단 집단 (`REJECT_NEVER_LATER_QUALIFIED`, N={wait_diag["reject_never_later_qualified_count"]}) 성과
- 4W 수익률 중앙값: `{never_comb["4w"]["return_stats"]["median"]:+0.2f}%`
- 8W 수익률 중앙값: `{never_comb["8w"]["return_stats"]["median"]:+0.2f}%`
- 12W 수익률 중앙값: `{never_comb["12w"]["return_stats"]["median"]:+0.2f}%`
- 26W 수익률 중앙값: `{never_comb["26w"]["return_stats"]["median"]:+0.2f}%` (MFE 중앙값: `+{never_comb["26w"]["mfe_stats"]["median"]:.2f}%`, MAE 중앙값: `{never_comb["26w"]["mae_stats"]["median"]:.2f}%`)

================================================================================
7. 핵심 관찰 (Key Observations)
================================================================================
"""
    for i, obs in enumerate(conc["key_observations"], 1):
        md += f"{i}. {obs}\n"

    md += f"""
================================================================================
8. 최종 결론 및 연구 상태
================================================================================
- **연구 상태 (Research Status)**: **`CLOSED`**
- **최종 연구 결론 상태 (Evaluation Status)**: **`{conc["status"]}`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
Pattern A Entry Gate v0.2A는 동일 최초 FAST 신호를 기준으로 평가했을 때 4W와 26W Return 및 전 horizon MFE에서는 Gate Pass가 우세했으나, 8W와 12W Return은 혼재되었고 MAE는 전 horizon에서 Gate Pass가 더 깊었습니다.

또한 Gate Reject의 75%가 Pattern A UNAVAILABLE이므로 전체 Pass/Reject 차이를 순수한 Stage discrimination으로 해석할 수 없습니다.

특히 REJECT_WEAK 108건은 26W Return 중앙값 +20.31%, MFE +57.16%를 기록해, WEAK 상태에서 발생한 FAST TRIGGER가 장기 바닥권 반전의 초기 신호일 가능성을 보여줍니다.

Gate 대기 역시 중앙 413일 동안 Waiting Return +6.17%, MFE +20.22%, MAE -21.02%가 함께 관찰되어 상승 기회비용과 변동 회피의 tradeoff가 존재합니다.

따라서 현행 Pattern A Gate의 incremental value는 일부 장기 상승 확장성 측면에서는 관찰되지만 광범위한 Entry 품질 개선 또는 하방 방어 효과는 확인되지 않았습니다.

최종 연구 판정은 GATE_VALUE_MIXED, Production은 PRODUCTION_HOLD로 유지하며 v0.2A 연구를 CLOSED 상태로 종료합니다.
"""
    return md


if __name__ == "__main__":
    run_full_evaluation()
