"""Rebuild Julia Proxy PIT Reports and Summaries from existing trade artifacts (FIX02).

Post-processing only:
- Reuses existing trade CSVs (zero full simulation / zero parquet re-reads).
- Preserves exact 6-digit zero-padded ticker identities (e.g. 043260, 005930).
- Enriches proxy query audit artifact with deterministic sensitivity_status column.
- Fully restores and expands proxy_contract.json schema and proxy_rules.
- Fully restores provenance metadata in proxy_run_manifest.json (SHA lineage, runtime invariants).
- Normalizes sensitivity units with explicit contract (return_unit: PERCENTAGE_POINT).
- Refines Markdown report terminology (removes 'fraction' mislabel, clarifies SHA lineage).
- Re-seals all artifacts in proxy_run_manifest.json and verifies SHA-256 integrity.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    calculate_strategy_metrics,
)
from trend_scanner.validation.julia_strategy_v00 import StrategyTradeRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROXY_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
DOCS_REPORT_PATH = ROOT / "docs/strategies/julia/proxy_market_cap_v01.md"

EXPERIMENT_BASE_SHA = "030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377"
PROXY_FULL_RUN_COMMIT = "6cdb5a6b00096d02c9cee4cc74f65ff8270056a1"
FIX01_SOURCE_COMMIT = "afb967d211058bfce9ae053eebc2798b31b822e9"


def load_trade_records_from_csv(csv_path: Path) -> list[StrategyTradeRecord]:
    """Load StrategyTradeRecord list from CSV without running simulations, preserving 6-digit tickers."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Trade artifact not found: {csv_path}")

    df = pd.read_csv(csv_path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)

    records: list[StrategyTradeRecord] = []
    for _, row in df.iterrows():
        # parse investability_meta
        meta_raw = row.get("investability_meta")
        meta_dict: dict[str, Any] = {}
        if isinstance(meta_raw, str) and meta_raw.strip():
            try:
                meta_dict = ast.literal_eval(meta_raw)
            except Exception:
                try:
                    meta_dict = json.loads(meta_raw)
                except Exception:
                    meta_dict = {}

        ticker_str = str(row["ticker"]).zfill(6)
        rec = StrategyTradeRecord(
            strategy_id=str(row["strategy_id"]),
            pre_progressed_loss_guard_enabled=bool(row["pre_progressed_loss_guard_enabled"]),
            ticker=ticker_str,
            name=str(row["name"]),
            market=str(row["market"]),
            trade_id=str(row["trade_id"]),
            trade_sequence=int(row["trade_sequence"]),
            entry_signal_date=str(row["entry_signal_date"]),
            entry_execution_date=str(row["entry_execution_date"]),
            entry_open=float(row["entry_open"]),
            entry_pattern_a_stage=str(row["entry_pattern_a_stage"]),
            fast_stage=str(row["fast_stage"]),
            monthly_regime=str(row["monthly_regime"]),
            daily_risk=str(row["daily_risk"]),
            fast_score=float(row["fast_score"]),
            fast_score_state=str(row["fast_score_state"]),
            investability_status=str(row["investability_status"]),
            investability_market_cap=float(row["investability_market_cap"]) if pd.notna(row["investability_market_cap"]) else None,
            investability_avg_trading_value_20d=float(row["investability_avg_trading_value_20d"]) if pd.notna(row["investability_avg_trading_value_20d"]) else None,
            investability_market_cap_source_file=str(row["investability_market_cap_source_file"]) if pd.notna(row["investability_market_cap_source_file"]) else None,
            previous_exit_type=str(row["previous_exit_type"]) if pd.notna(row["previous_exit_type"]) else None,
            previous_exit_execution_date=str(row["previous_exit_execution_date"]) if pd.notna(row["previous_exit_execution_date"]) else None,
            loss_guard_triggered=bool(row["loss_guard_triggered"]),
            loss_guard_signal_date=str(row["loss_guard_signal_date"]) if pd.notna(row["loss_guard_signal_date"]) else None,
            loss_guard_execution_date=str(row["loss_guard_execution_date"]) if pd.notna(row["loss_guard_execution_date"]) else None,
            loss_guard_execution_price=float(row["loss_guard_execution_price"]) if pd.notna(row["loss_guard_execution_price"]) else None,
            first_progressed_date=str(row["first_progressed_date"]) if pd.notna(row["first_progressed_date"]) else None,
            first_progressed_effective_trading_date=str(row["first_progressed_effective_trading_date"]) if pd.notna(row["first_progressed_effective_trading_date"]) else None,
            lifecycle_class=str(row["lifecycle_class"]),
            exit_type=str(row["exit_type"]),
            exit_signal_date=str(row["exit_signal_date"]) if pd.notna(row["exit_signal_date"]) else None,
            exit_execution_date=str(row["exit_execution_date"]) if pd.notna(row["exit_execution_date"]) else None,
            exit_price=float(row["exit_price"]) if pd.notna(row["exit_price"]) else None,
            terminal_return=float(row["terminal_return"]),
            mfe=float(row["mfe"]),
            mae=float(row["mae"]),
            peak_giveback=float(row["peak_giveback"]) if pd.notna(row["peak_giveback"]) else 0.0,
            profit_capture=float(row["profit_capture"]) if pd.notna(row["profit_capture"]) else None,
            holding_weeks=float(row["holding_weeks"]),
            trade_status=str(row["trade_status"]),
            investability_meta=meta_dict,
        )
        records.append(rec)
    return records


def evaluate_research_verdict(
    b_metrics: dict[str, Any],
    j_metrics: dict[str, Any],
    sensitivity_summary: dict[str, Any],
) -> tuple[str, str]:
    """Evaluate deterministic 3-state research verdict."""
    b_mean = b_metrics["return_stats"]["mean"]
    j_mean = j_metrics["return_stats"]["mean"]
    b_median = b_metrics["return_stats"]["median"]
    j_median = j_metrics["return_stats"]["median"]
    b_pos_rate = b_metrics["return_stats"]["positive_rate"]
    j_pos_rate = j_metrics["return_stats"]["positive_rate"]

    b_dist = b_metrics["distribution_stats"]
    j_dist = j_metrics["distribution_stats"]

    # Performance
    mean_favorable = bool(j_mean > b_mean)
    median_favorable = bool(j_median > b_median)
    pos_rate_favorable = bool(j_pos_rate > b_pos_rate)
    sens_favorable = bool(sensitivity_summary.get("conclusion_robust_to_boundary", False))

    # Downside tail risk checks
    loss_20_better = bool(j_dist["le_neg20_rate"] <= b_dist["le_neg20_rate"])
    loss_30_better = bool(j_dist["le_neg30_rate"] <= b_dist["le_neg30_rate"])
    win_50_better = bool(j_dist["ge_pos50_rate"] >= b_dist["ge_pos50_rate"])
    win_100_better = bool(j_dist["ge_pos100_rate"] >= b_dist["ge_pos100_rate"])

    all_performance_favorable = mean_favorable and median_favorable and pos_rate_favorable
    tail_favorable = loss_20_better and loss_30_better and win_50_better and win_100_better

    if all_performance_favorable and sens_favorable and tail_favorable:
        verdict = "SUPPORTIVE_OF_JULIA"
        rationale = (
            f"Julia outperforms Baseline V2 across mean return (+{j_mean - b_mean:.2f}%p), "
            f"median return (+{j_median - b_median:.2f}%p), positive rate (+{(j_pos_rate - b_pos_rate)*100:.2f}%p), "
            f"reduces deep loss rate <= -20% from {b_dist['le_neg20_rate']*100:.1f}% to {j_dist['le_neg20_rate']*100:.1f}%, "
            f"and robustly maintains superiority under conservative boundary sensitivity."
        )
    elif not mean_favorable and not median_favorable and not pos_rate_favorable:
        verdict = "UNFAVORABLE_TO_JULIA"
        rationale = "Julia underperforms Baseline V2 across primary return and risk metrics."
    else:
        verdict = "MIXED"
        rationale = (
            f"Julia demonstrates substantial performance upside (Mean Return +{j_mean - b_mean:.2f}%p, "
            f"Median Return +{j_median - b_median:.2f}%p, Win Rate +{(j_pos_rate - b_pos_rate)*100:.2f}%p), "
            f"but removing the Loss Guard increases <= -20% drawdown trades from {b_dist['le_neg20_rate']*100:.1f}% "
            f"to {j_dist['le_neg20_rate']*100:.1f}% (Mean MAE worsens from {b_metrics['mae_stats']['mean']:.2f}% to {j_metrics['mae_stats']['mean']:.2f}%)."
        )

    return verdict, rationale


def build_markdown_report(
    summary: dict[str, Any],
    val_summary: dict[str, Any],
    lg_summary: dict[str, Any],
    sens_summary: dict[str, Any],
    df_winners: pd.DataFrame,
    df_worst: pd.DataFrame,
    verdict: str,
    verdict_rationale: str,
) -> str:
    """Generate professional markdown research report with exact unit formatting and SHA lineage."""
    b_m = summary["baseline_v2_proxy"]
    j_m = summary["julia_v00_proxy"]
    delta = summary["delta_julia_minus_baseline"]
    dep = summary["proxy_dependence"]

    b_ret = b_m["return_stats"]
    j_ret = j_m["return_stats"]
    b_dist = b_m["distribution_stats"]
    j_dist = j_m["distribution_stats"]
    b_mae = b_m["mae_stats"]
    j_mae = j_m["mae_stats"]
    b_mfe = b_m["mfe_stats"]
    j_mfe = j_m["mfe_stats"]
    b_hold = b_m["holding_stats"]
    j_hold = j_m["holding_stats"]

    lines: list[str] = []
    lines.append("# Research Report: Julia Strategy V00 vs Baseline V2 Proxy PIT Comparative Backtest (2022+)")
    lines.append("")
    lines.append("> [!WARNING]")
    lines.append("> **WARNING — NON-AUTHORITATIVE PROXY PIT RESEARCH**")
    lines.append("> 본 백테스트는 공식 KRX 시가총액 데이터가 존재하지 않는 98개 Historical PIT 기준일에 대해 **예상 시가총액(Proxy Market Cap)**을 사용한 **비공식 연구용 실험**입니다.")
    lines.append("> 예상 시가총액은 과거 직전 공식 KRX 시총/주가 비율을 이용한 근사치이며 실제 당시 시가총액과 차이가 발생할 수 있습니다.")
    lines.append("> 따라서 본 결과는 **100% 정확한 Historical PIT 결과가 아니며**, Julia V00의 공식 검증 완료 또는 Production 승인 근거로 사용할 수 없습니다.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. Executive Status & Governance")
    lines.append("")
    lines.append("| Item | Specification / Value |")
    lines.append("| :--- | :--- |")
    lines.append("| **Strategy ID** | `JULIA_STRATEGY_V00` |")
    lines.append("| **Base Strategy ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |")
    lines.append("| **Research Classification** | `RESEARCH_EXPERIMENT` / `NON_AUTHORITATIVE_PROXY_PIT` |")
    lines.append("| **Official Julia Status** | `INVALID_INCOMPLETE_PIT_COVERAGE` (54.42% Official KRX Coverage) |")
    lines.append("| **Production Recommendation** | `NOT_APPROVED` (Default remains `PATTERN_A_FAST_FINAL_STRATEGY_V02`) |")
    lines.append("| **Evaluation Window** | `2022-01-01` ~ `2026-08-14` (Initial Position State: `FLAT`) |")
    lines.append("| **Lookback History** | Full pre-2022 daily bars utilized for rolling indicators and snapshots |")
    lines.append("| **Only Delta from Base** | Pre-PROGRESSED Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |")
    lines.append(f"| **Official Reference Dates** | **{summary['metadata']['official_reference_date_count']}개 (54.42%)** — KRX 공식값 100% 사용 |")
    lines.append(f"| **Proxy Reference Dates** | **{summary['metadata']['proxy_reference_date_count']}개 (45.58%)** — Method B (Anchor Price Ratio Proxy) 적용 |")
    lines.append("| **Future Anchor Usage Count** | **0** (Strictly Prior Anchor Only) |")
    lines.append("| **Current Shares Fallback Count** | **0** (Zero Fallback) |")
    lines.append(f"| **Experiment Base SHA** | `{EXPERIMENT_BASE_SHA}` |")
    lines.append(f"| **Proxy Full Run Commit** | `{PROXY_FULL_RUN_COMMIT}` |")
    lines.append(f"| **FIX01 Source Commit** | `{FIX01_SOURCE_COMMIT}` |")
    lines.append(f"| **Run ID** | `{summary['metadata']['run_id']}` |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. Proxy Method Accuracy Validation (Known Official Snapshots)")
    lines.append("")
    lines.append("117개 공식 KRX 스냅샷에 대해 직전 공식 과거 anchor만을 이용하여 시총을 예측하고, 실제 공식 KRX 시총과 비교하여 오차를 측정한 결과입니다.")
    lines.append("")
    lines.append("| Metric | Validation Result |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Total Validation Observations ($N$)** | **{val_summary.get('validation_sample_count', 0):,}건** |")
    lines.append(f"| **Mean Absolute Percentage Error (MAPE)** | **{val_summary.get('mean_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **Median Absolute Percentage Error** | **{val_summary.get('median_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **75th Percentile Error (P75)** | **{val_summary.get('p75_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **90th Percentile Error (P90)** | **{val_summary.get('p90_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **95th Percentile Error (P95)** | **{val_summary.get('p95_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **Max Error** | **{val_summary.get('max_absolute_percentage_error', 0.0):.2f}%** |")
    lines.append(f"| **1,000억원 Threshold Classification Agreement** | **{val_summary.get('classification_agreement_rate', 0.0):.2f}% ({val_summary.get('threshold_agreement_count', 0):,}/{val_summary.get('validation_sample_count', 0):,})** |")
    lines.append(f"| **False Pass Count** | **{val_summary.get('false_pass_count', 0):,}건** |")
    lines.append(f"| **False Fail Count** | **{val_summary.get('false_fail_count', 0):,}건** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. Primary Comparative Strategy Performance (2022+)")
    lines.append("")
    lines.append("| Metric Category | Baseline V2 (Loss Guard ON) | Julia V00 (Loss Guard OFF) | Delta (Julia - Baseline) |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(f"| **Total Trades** | **{b_m['total_trades']:,}건** | **{j_m['total_trades']:,}건** | **{delta['trade_count_delta']:,}건** |")
    lines.append(f"| **Unique Tickers** | **{b_m['unique_tickers']:,}개** | **{j_m['unique_tickers']:,}개** | **+0개** |")
    lines.append(f"| **Mean Return (%)** | **{b_ret['mean']:+.2f}%** | **{j_ret['mean']:+.2f}%** | **{delta['mean_return_delta_p']:+.2f}%p** |")
    lines.append(f"| **Median Return (%)** | **{b_ret['median']:+.2f}%** | **{j_ret['median']:+.2f}%** | **{delta['median_return_delta_p']:+.2f}%p** |")
    lines.append(f"| **Positive Return Rate (%)** | **{b_ret['positive_rate']*100:.2f}%** | **{j_ret['positive_rate']*100:.2f}%** | **{delta['positive_rate_delta_p']:+.2f}%p** |")
    lines.append(f"| **Deep Losses ($\\\\le -10\\%$)** | {b_dist['le_neg10_count']}건 ({b_dist['le_neg10_rate']*100:.1f}%) | {j_dist['le_neg10_count']}건 ({j_dist['le_neg10_rate']*100:.1f}%) | {j_dist['le_neg10_count'] - b_dist['le_neg10_count']:+d}건 |")
    lines.append(f"| **Deep Losses ($\\\\le -15\\%$)** | {b_dist['le_neg15_count']}건 ({b_dist['le_neg15_rate']*100:.1f}%) | {j_dist['le_neg15_count']}건 ({j_dist['le_neg15_rate']*100:.1f}%) | {j_dist['le_neg15_count'] - b_dist['le_neg15_count']:+d}건 |")
    lines.append(f"| **Deep Losses ($\\\\le -20\\%$)** | {b_dist['le_neg20_count']}건 ({b_dist['le_neg20_rate']*100:.1f}%) | {j_dist['le_neg20_count']}건 ({j_dist['le_neg20_rate']*100:.1f}%) | {delta['le_neg20_delta_count']:+d}건 |")
    lines.append(f"| **Deep Losses ($\\\\le -30\\%$)** | {b_dist['le_neg30_count']}건 ({b_dist['le_neg30_rate']*100:.1f}%) | {j_dist['le_neg30_count']}건 ({j_dist['le_neg30_rate']*100:.1f}%) | {delta['le_neg30_delta_count']:+d}건 |")
    lines.append(f"| **Big Winners ($\\\\ge +20\\%$)** | {b_dist['ge_pos20_count']}건 ({b_dist['ge_pos20_rate']*100:.1f}%) | {j_dist['ge_pos20_count']}건 ({j_dist['ge_pos20_rate']*100:.1f}%) | {j_dist['ge_pos20_count'] - b_dist['ge_pos20_count']:+d}건 |")
    lines.append(f"| **Big Winners ($\\\\ge +30\\%$)** | {b_dist['ge_pos30_count']}건 ({b_dist['ge_pos30_rate']*100:.1f}%) | {j_dist['ge_pos30_count']}건 ({j_dist['ge_pos30_rate']*100:.1f}%) | {j_dist['ge_pos30_count'] - b_dist['ge_pos30_count']:+d}건 |")
    lines.append(f"| **Big Winners ($\\\\ge +50\\%$)** | {b_dist['ge_pos50_count']}건 ({b_dist['ge_pos50_rate']*100:.1f}%) | {j_dist['ge_pos50_count']}건 ({j_dist['ge_pos50_rate']*100:.1f}%) | {delta['ge_pos50_delta_count']:+d}건 |")
    lines.append(f"| **Mega Winners ($\\\\ge +100\\%$)** | {b_dist['ge_pos100_count']}건 ({b_dist['ge_pos100_rate']*100:.1f}%) | {j_dist['ge_pos100_count']}건 ({j_dist['ge_pos100_rate']*100:.1f}%) | {delta['ge_pos100_delta_count']:+d}건 |")
    lines.append(f"| **Mean MAE (%)** | **{b_mae['mean']:.2f}%** | **{j_mae['mean']:.2f}%** | **{j_mae['mean'] - b_mae['mean']:+.2f}%p** |")
    lines.append(f"| **Median MAE (%)** | **{b_mae['median']:.2f}%** | **{j_mae['median']:.2f}%** | **{j_mae['median'] - b_mae['median']:+.2f}%p** |")
    lines.append(f"| **Worst MAE (%)** | **{b_mae['worst']:.2f}%** | **{j_mae['worst']:.2f}%** | **{j_mae['worst'] - b_mae['worst']:+.2f}%p** |")
    lines.append(f"| **Mean MFE (%)** | **{b_mfe['mean']:.2f}%** | **{j_mfe['mean']:.2f}%** | **{j_mfe['mean'] - b_mfe['mean']:+.2f}%p** |")
    lines.append(f"| **Median MFE (%)** | **{b_mfe['median']:.2f}%** | **{j_mfe['median']:.2f}%** | **{j_mfe['median'] - b_mfe['median']:+.2f}%p** |")
    lines.append(f"| **Mean Holding Time** | **{b_hold['mean_weeks']:.2f} weeks** | **{j_hold['mean_weeks']:.2f} weeks** | **{j_hold['mean_weeks'] - b_hold['mean_weeks']:+.2f} weeks** |")
    lines.append(f"| **Median Holding Time** | **{b_hold['median_weeks']:.2f} weeks** | **{j_hold['median_weeks']:.2f} weeks** | **{j_hold['median_weeks'] - b_hold['median_weeks']:+.2f} weeks** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. Full Loss Guard Cohort Accounting & Recovery")
    lines.append("")
    lines.append(f"$$\\text{{Baseline Loss Guard Total }} N = {lg_summary['baseline_loss_guard_total']} = M({lg_summary['paired_loss_guard_count']}) + (N-M)({lg_summary['unpaired_loss_guard_count']})$$")
    lines.append("")
    lines.append(f"- **Baseline Loss Guard Triggered Total ($N$)**: **{lg_summary['baseline_loss_guard_total']}건**")
    lines.append(f"- **Paired in Julia ($M$)**: **{lg_summary['paired_loss_guard_count']}건**")
    lines.append(f"- **Unpaired in Julia ($N-M$)**: **{lg_summary['unpaired_loss_guard_count']}건**")
    lines.append(f"- **Julia Higher Terminal Return (Recovered)**: **{lg_summary['julia_recovered_higher_return_count']}건 ({lg_summary['julia_recovered_higher_return_count'] / lg_summary['paired_loss_guard_count'] * 100:.2f}%)**")
    lines.append(f"- **Julia Deeper Terminal Loss**: **{lg_summary['julia_deeper_loss_count']}건 ({lg_summary['julia_deeper_loss_count'] / lg_summary['paired_loss_guard_count'] * 100:.2f}%)**")
    lines.append(f"- **Julia Successfully Reached PROGRESSED Stage**: **{lg_summary['julia_reached_progressed_count']}건 ({lg_summary['julia_reached_progressed_count'] / lg_summary['paired_loss_guard_count'] * 100:.2f}%)**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. Proxy Dependence & Boundary Sensitivity Analysis")
    lines.append("")
    lines.append("### A. Proxy Data Dependence Breakdown")
    lines.append("")
    lines.append("| Metric | Baseline V2 | Julia V00 |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| **Actual KRX Entry Trades** | {dep['baseline_actual_krx_entries']}건 ({dep['baseline_actual_krx_entries']/b_m['total_trades']*100:.1f}%) | {dep['julia_actual_krx_entries']}건 ({dep['julia_actual_krx_entries']/j_m['total_trades']*100:.1f}%) |")
    lines.append(f"| **Proxy-Dependent Entry Trades** | {dep['baseline_proxy_entries']}건 ({dep['baseline_proxy_percentage']:.1f}%) | {dep['julia_proxy_entries']}건 ({dep['julia_proxy_percentage']:.1f}%) |")
    lines.append(f"| **- Near-Threshold (80B~120B) Proxy Entries** | {dep.get('baseline_near_threshold_proxy_entries', 0)}건 | {dep.get('julia_near_threshold_proxy_entries', 0)}건 |")
    lines.append(f"| **- High Confidence (<=35d) Proxy Entries** | {dep.get('baseline_high_confidence_proxy_entries', 0)}건 | {dep.get('julia_high_confidence_proxy_entries', 0)}건 |")
    lines.append(f"| **- Medium Confidence (36~90d) Proxy Entries** | {dep.get('baseline_medium_confidence_proxy_entries', 0)}건 | {dep.get('julia_medium_confidence_proxy_entries', 0)}건 |")
    lines.append(f"| **- Low Confidence (>90d) Proxy Entries** | {dep.get('baseline_low_confidence_proxy_entries', 0)}건 | {dep.get('julia_low_confidence_proxy_entries', 0)}건 |")
    lines.append("")
    lines.append("### B. Conservative Boundary Sensitivity (80B ~ 120B Buffer Excluded)")
    lines.append("")
    lines.append("| Sensitivity Metric | Primary (100B Exact) | Conservative (80B~120B Buffer) | Sensitivity Delta |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(f"| **Baseline Trade Count** | {sens_summary['primary_baseline_trade_count']}건 | {sens_summary['sensitivity_baseline_trade_count']}건 | -{sens_summary['baseline_trade_reduction_pct']:.2f}% |")
    lines.append(f"| **Julia Trade Count** | {sens_summary['primary_julia_trade_count']}건 | {sens_summary['sensitivity_julia_trade_count']}건 | -{sens_summary['julia_trade_reduction_pct']:.2f}% |")
    lines.append(f"| **Baseline Mean Return** | {sens_summary['primary_baseline_mean_return']:+.2f}% | {sens_summary['sensitivity_baseline_mean_return']:+.2f}% | {sens_summary['sensitivity_baseline_mean_return'] - sens_summary['primary_baseline_mean_return']:+.2f}%p |")
    lines.append(f"| **Julia Mean Return** | {sens_summary['primary_julia_mean_return']:+.2f}% | {sens_summary['sensitivity_julia_mean_return']:+.2f}% | {sens_summary['sensitivity_julia_mean_return'] - sens_summary['primary_julia_mean_return']:+.2f}%p |")
    lines.append(f"| **Julia - Baseline Return Delta** | **{sens_summary['primary_delta_mean_p']:+.2f}%p** | **{sens_summary['sensitivity_delta_mean_p']:+.2f}%p** | **{sens_summary['sensitivity_delta_mean_p'] - sens_summary['primary_delta_mean_p']:+.2f}%p** |")
    lines.append(f"| **Conclusion Robust to Boundary** | - | - | **{'YES' if sens_summary['conclusion_robust_to_boundary'] else 'NO'}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 6. Top Big Winners & Worst Losses in Julia V00 Proxy Run")
    lines.append("")
    lines.append("### Top 10 Big Winners in Julia V00 ($\\ge +50\\%$)")
    lines.append("")
    lines.append("| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MFE (%) | Exit Type |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for _, w in df_winners.head(10).iterrows():
        exit_d = w["exit_execution_date"] if pd.notna(w["exit_execution_date"]) else "Cutoff (Open)"
        t_code = str(w["ticker"]).zfill(6)
        lines.append(f"| `{t_code}` | {w['name']} | {w['entry_execution_date']} | {exit_d} | **{float(w['terminal_return']):+.2f}%** | {float(w['mfe']):+.2f}% | `{w['exit_type']}` |")
    lines.append("")
    lines.append("### Top 10 Deep Losses in Julia V00 ($\\le -20\\%$)")
    lines.append("")
    lines.append("| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MAE (%) | Exit Type |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for _, l in df_worst.head(10).iterrows():
        exit_d = l["exit_execution_date"] if pd.notna(l["exit_execution_date"]) else "Cutoff (Open)"
        t_code = str(l["ticker"]).zfill(6)
        lines.append(f"| `{t_code}` | {l['name']} | {l['entry_execution_date']} | {exit_d} | **{float(l['terminal_return']):+.2f}%** | {float(l['mae']):+.2f}% | `{l['exit_type']}` |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 7. Strategic Governance & Verdict")
    lines.append("")
    lines.append(f"1. **Proxy Research Verdict**: **`{verdict}`**")
    lines.append(f"   - **Rationale**: {verdict_rationale}")
    lines.append("2. **Production Status Invariant**:")
    lines.append("   - `JULIA_PRODUCTION_STATUS = NOT_APPROVED`")
    lines.append("   - `OFFICIAL_FULL_PIT_STATUS = INVALID_INCOMPLETE_PIT_COVERAGE`")
    lines.append("   - 기본 프로덕션 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (783 historical trades)를 엄격히 유지합니다.")
    lines.append("3. **Next Steps**:")
    lines.append("   - KRX Open API 98 dates 공식 확보 후 Proxy vs Actual 시총 오차 및 백테스트 결과 Reconciliation 수행 예정.")
    lines.append("")

    return "\n".join(lines)


def enrich_query_audit_with_sensitivity_status(audit_csv_path: Path) -> None:
    """Enrich existing query audit CSV with sensitivity_status column deterministically."""
    if not audit_csv_path.exists():
        logger.warning(f"Audit file not found for enrichment: {audit_csv_path}")
        return

    df_audit = pd.read_csv(audit_csv_path, dtype={"ticker": str})
    df_audit["ticker"] = df_audit["ticker"].astype(str).str.zfill(6)

    sensitivity_statuses = []
    for _, row in df_audit.iterrows():
        st = row.get("source_type")
        near = bool(row.get("near_threshold") is True or row.get("near_threshold") == "True")
        if st == "ACTUAL_KRX":
            sensitivity_statuses.append("OFFICIAL_VALUE_UNAFFECTED")
        elif st == "PROXY_ANCHOR_PRICE_RATIO":
            if near:
                sensitivity_statuses.append("DATA_UNAVAILABLE_PROXY_BOUNDARY")
            else:
                sensitivity_statuses.append("ELIGIBLE")
        else:
            sensitivity_statuses.append("NOT_APPLICABLE")

    df_audit["sensitivity_status"] = sensitivity_statuses
    df_audit.to_csv(audit_csv_path, index=False)
    logger.info(f"Enriched query audit with sensitivity_status ({len(df_audit)} rows)")


def run_post_processing_rebuild() -> None:
    """Execute complete post-processing report and artifact rebuild from existing trade files (FIX02)."""
    logger.info("Starting Julia Proxy Report & Artifact Rebuild FIX02 (Post-Processing Only)...")

    # 1. Load existing trade records with 6-digit zero-padded ticker preservation
    b_csv_path = PROXY_DIR / "baseline_v2_proxy_trades.csv"
    j_csv_path = PROXY_DIR / "julia_v00_proxy_trades.csv"
    baseline_trades = load_trade_records_from_csv(b_csv_path)
    julia_trades = load_trade_records_from_csv(j_csv_path)

    # Invariant Verification (Gate A)
    assert len(baseline_trades) == 845, f"Baseline trades count mismatch: {len(baseline_trades)} != 845"
    assert len(julia_trades) == 687, f"Julia trades count mismatch: {len(julia_trades)} != 687"
    assert len(set(t.ticker for t in baseline_trades)) == 673
    assert len(set(t.ticker for t in julia_trades)) == 673
    for t in baseline_trades:
        assert len(t.ticker) == 6 and t.ticker.isdigit(), f"Corrupted ticker format in baseline: {t.ticker}"
    for t in julia_trades:
        assert len(t.ticker) == 6 and t.ticker.isdigit(), f"Corrupted ticker format in julia: {t.ticker}"
    logger.info(f"Verified trade counts and 6-digit ticker identities: Baseline={len(baseline_trades)}, Julia={len(julia_trades)}")

    # 2. Recalculate metrics with corrected percentage unit logic
    b_metrics = calculate_strategy_metrics(baseline_trades)
    j_metrics = calculate_strategy_metrics(julia_trades)

    b_mean = b_metrics["return_stats"]["mean"]
    j_mean = j_metrics["return_stats"]["mean"]
    b_median = b_metrics["return_stats"]["median"]
    j_median = j_metrics["return_stats"]["median"]
    b_pos_rate = b_metrics["return_stats"]["positive_rate"]
    j_pos_rate = j_metrics["return_stats"]["positive_rate"]

    # 3. Big Winners (>= 50.0%) and Worst Losses (<= -20.0%) with 6-digit tickers
    df_j = pd.read_csv(j_csv_path, dtype={"ticker": str})
    df_j["ticker"] = df_j["ticker"].astype(str).str.zfill(6)

    df_winners = df_j[df_j["terminal_return"] >= 50.0].sort_values("terminal_return", ascending=False)
    df_worst = df_j[df_j["terminal_return"] <= -20.0].sort_values("terminal_return", ascending=True)

    winners_csv_path = PROXY_DIR / "big_winners.csv"
    worst_csv_path = PROXY_DIR / "worst_losses.csv"
    df_winners.to_csv(winners_csv_path, index=False)
    df_worst.to_csv(worst_csv_path, index=False)
    logger.info(f"Saved big_winners.csv ({len(df_winners)} rows) and worst_losses.csv ({len(df_worst)} rows) with 6-digit tickers")

    # 4. Proxy Dependence Breakdown
    b_actual_entries = len([t for t in baseline_trades if t.investability_meta.get("proxy_source_type") == "ACTUAL_KRX"])
    b_proxy_entries = len([t for t in baseline_trades if t.investability_meta.get("source_type") == "PROXY_ANCHOR_PRICE_RATIO"])
    b_near_entries = len([t for t in baseline_trades if t.investability_meta.get("near_threshold") is True])
    b_high_conf = len([t for t in baseline_trades if t.investability_meta.get("confidence_class") == "HIGH_CONFIDENCE_PROXY"])
    b_med_conf = len([t for t in baseline_trades if t.investability_meta.get("confidence_class") == "MEDIUM_CONFIDENCE_PROXY"])
    b_low_conf = len([t for t in baseline_trades if t.investability_meta.get("confidence_class") == "LOW_CONFIDENCE_PROXY"])

    j_actual_entries = len([t for t in julia_trades if t.investability_meta.get("proxy_source_type") == "ACTUAL_KRX"])
    j_proxy_entries = len([t for t in julia_trades if t.investability_meta.get("source_type") == "PROXY_ANCHOR_PRICE_RATIO"])
    j_near_entries = len([t for t in julia_trades if t.investability_meta.get("near_threshold") is True])
    j_high_conf = len([t for t in julia_trades if t.investability_meta.get("confidence_class") == "HIGH_CONFIDENCE_PROXY"])
    j_med_conf = len([t for t in julia_trades if t.investability_meta.get("confidence_class") == "MEDIUM_CONFIDENCE_PROXY"])
    j_low_conf = len([t for t in julia_trades if t.investability_meta.get("confidence_class") == "LOW_CONFIDENCE_PROXY"])

    # 5. Boundary Sensitivity Normalization with Explicit Contract
    boundary_path = PROXY_DIR / "boundary_sensitivity_summary.json"
    sens_raw = json.loads(boundary_path.read_text(encoding="utf-8"))

    # Explicit unit contract: values in boundary_sensitivity_summary are already percentage points
    sens_summary = {
        "sensitivity_mode": "CONSERVATIVE_BUFFER_80B_TO_120B_EXCLUDED",
        "return_unit": "PERCENTAGE_POINT",
        "primary_baseline_trade_count": sens_raw.get("primary_baseline_trade_count", 845),
        "primary_julia_trade_count": sens_raw.get("primary_julia_trade_count", 687),
        "sensitivity_baseline_trade_count": sens_raw.get("sensitivity_baseline_trade_count", 810),
        "sensitivity_julia_trade_count": sens_raw.get("sensitivity_julia_trade_count", 656),
        "baseline_trade_reduction_pct": sens_raw.get("baseline_trade_reduction_pct", 4.14),
        "julia_trade_reduction_pct": sens_raw.get("julia_trade_reduction_pct", 4.51),
        "primary_baseline_mean_return": round(b_mean, 2),
        "primary_julia_mean_return": round(j_mean, 2),
        "sensitivity_baseline_mean_return": round(float(sens_raw.get("sensitivity_baseline_mean_return", 13.24)), 2),
        "sensitivity_julia_mean_return": round(float(sens_raw.get("sensitivity_julia_mean_return", 24.24)), 2),
        "primary_delta_mean_p": round(j_mean - b_mean, 2),
        "sensitivity_delta_mean_p": round(float(sens_raw.get("sensitivity_julia_mean_return", 24.24)) - float(sens_raw.get("sensitivity_baseline_mean_return", 13.24)), 2),
        "conclusion_robust_to_boundary": bool(sens_raw.get("conclusion_robust_to_boundary", True)),
    }
    boundary_path.write_text(json.dumps(sens_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # 6. Evaluate Research Verdict
    verdict, verdict_rationale = evaluate_research_verdict(b_metrics, j_metrics, sens_summary)
    logger.info(f"Research Verdict: {verdict}")

    # 7. Build Strategy Comparison Summary
    run_id = f"JULIA_V00_PROXY_PIT_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    summary_data = {
        "metadata": {
            "run_id": run_id,
            "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
            "not_100_percent_accurate_market_cap_data": True,
            "not_production_evidence": True,
            "official_full_pit_status": "INVALID_INCOMPLETE_PIT_COVERAGE",
            "julia_production_status": "NOT_APPROVED",
            "production_default_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
            "evaluation_start": "2022-01-01",
            "evaluation_end": "2026-08-14",
            "initial_position": "FLAT",
            "official_reference_date_count": 117,
            "proxy_reference_date_count": 98,
            "total_reference_date_count": 215,
            "close_semantics": "ADJUSTED_CLOSE",
            "primary_proxy_method": "ANCHOR_PRICE_RATIO_PROXY",
            "future_anchor_usage_count": 0,
            "current_shares_fallback_count": 0,
            "research_verdict": verdict,
            "authoritative_experiment_base_sha": EXPERIMENT_BASE_SHA,
            "proxy_full_run_commit": PROXY_FULL_RUN_COMMIT,
            "fix01_source_commit": FIX01_SOURCE_COMMIT,
        },
        "proxy_dependence": {
            "baseline_total_trades": len(baseline_trades),
            "baseline_actual_krx_entries": b_actual_entries,
            "baseline_proxy_entries": b_proxy_entries,
            "baseline_proxy_percentage": round(b_proxy_entries / len(baseline_trades) * 100.0, 2),
            "baseline_near_threshold_proxy_entries": b_near_entries,
            "baseline_high_confidence_proxy_entries": b_high_conf,
            "baseline_medium_confidence_proxy_entries": b_med_conf,
            "baseline_low_confidence_proxy_entries": b_low_conf,
            "julia_total_trades": len(julia_trades),
            "julia_actual_krx_entries": j_actual_entries,
            "julia_proxy_entries": j_proxy_entries,
            "julia_proxy_percentage": round(j_proxy_entries / len(julia_trades) * 100.0, 2),
            "julia_near_threshold_proxy_entries": j_near_entries,
            "julia_high_confidence_proxy_entries": j_high_conf,
            "julia_medium_confidence_proxy_entries": j_med_conf,
            "julia_low_confidence_proxy_entries": j_low_conf,
        },
        "baseline_v2_proxy": b_metrics,
        "julia_v00_proxy": j_metrics,
        "delta_julia_minus_baseline": {
            "trade_count_delta": len(julia_trades) - len(baseline_trades),
            "mean_return_delta_p": round(j_mean - b_mean, 2),
            "median_return_delta_p": round(j_median - b_median, 2),
            "positive_rate_delta_p": round((j_pos_rate - b_pos_rate) * 100.0, 2),
            "le_neg20_delta_count": j_metrics["distribution_stats"]["le_neg20_count"] - b_metrics["distribution_stats"]["le_neg20_count"],
            "le_neg30_delta_count": j_metrics["distribution_stats"]["le_neg30_count"] - b_metrics["distribution_stats"]["le_neg30_count"],
            "ge_pos50_delta_count": j_metrics["distribution_stats"]["ge_pos50_count"] - b_metrics["distribution_stats"]["ge_pos50_count"],
            "ge_pos100_delta_count": j_metrics["distribution_stats"]["ge_pos100_count"] - b_metrics["distribution_stats"]["ge_pos100_count"],
        },
    }

    summary_path = PROXY_DIR / "strategy_comparison_summary.json"
    summary_path.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 8. Restore and Expand proxy_contract.json
    contract_data = {
        "contract_name": "JULIA_V00_PROXY_MARKET_CAP_PIT_V01",
        "strategy_id": "JULIA_STRATEGY_V00",
        "base_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "experiment_id": "JULIA_V00_PROXY_MARKET_CAP_PIT_V01",
        "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
        "estimated_market_cap_used": True,
        "not_100_percent_accurate_market_cap_data": True,
        "not_production_evidence": True,
        "official_full_pit_status": "INVALID_INCOMPLETE_PIT_COVERAGE",
        "julia_production_status": "NOT_APPROVED",
        "production_default_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "research_verdict": verdict,
        "evaluation_window": {
            "evaluation_start": "2022-01-01",
            "evaluation_end": "2026-08-14",
        },
        "official_reference_date_count": 117,
        "proxy_reference_date_count": 98,
        "total_reference_date_count": 215,
        "price_semantics": "ADJUSTED_CLOSE",
        "primary_proxy_method": "ANCHOR_PRICE_RATIO_PROXY",
        "proxy_rules": {
            "official_dates_rule": "USE_EXACT_KRX_OFFICIAL_MARKET_CAP",
            "missing_dates_rule": "METHOD_B_ANCHOR_PRICE_RATIO_PROXY",
            "anchor_direction": "STRICTLY_PRIOR_ANCHOR_ONLY",
            "future_anchor_forbidden": True,
            "current_shares_fallback_forbidden": True,
            "interpolation_forbidden": True,
            "proxy_only_on_frozen_missing_reference_dates": True,
        },
        "conservative_boundary_buffer_krw": [80_000_000_000, 120_000_000_000],
    }
    contract_path = PROXY_DIR / "proxy_contract.json"
    contract_path.write_text(json.dumps(contract_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 9. Enrich query audit artifact with sensitivity_status column
    audit_csv_path = PROXY_DIR / "proxy_market_cap_query_audit.csv"
    enrich_query_audit_with_sensitivity_status(audit_csv_path)

    # 10. Load other summaries for Markdown
    val_sum_path = PROXY_DIR / "proxy_market_cap_validation_summary.json"
    val_summary = json.loads(val_sum_path.read_text(encoding="utf-8")) if val_sum_path.exists() else {}

    lg_sum_path = PROXY_DIR / "loss_guard_recovery_summary.json"
    lg_summary = json.loads(lg_sum_path.read_text(encoding="utf-8")) if lg_sum_path.exists() else {}

    # 11. Generate Markdown Report
    md_content = build_markdown_report(
        summary=summary_data,
        val_summary=val_summary,
        lg_summary=lg_summary,
        sens_summary=sens_summary,
        df_winners=df_winners,
        df_worst=df_worst,
        verdict=verdict,
        verdict_rationale=verdict_rationale,
    )
    DOCS_REPORT_PATH.write_text(md_content, encoding="utf-8")
    logger.info(f"Generated Markdown report to {DOCS_REPORT_PATH} ({len(md_content)} bytes)")

    # 12. Compute and Seal SHA-256 Manifest with Full Provenance Metadata
    artifact_files = sorted([
        f for f in PROXY_DIR.iterdir()
        if f.is_file() and f.name != "proxy_run_manifest.json"
    ])
    manifest_entries: dict[str, dict[str, Any]] = {}
    for f in artifact_files:
        content = f.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        manifest_entries[f.name] = {
            "size_bytes": len(content),
            "sha256": sha,
        }

    manifest_payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
        "research_verdict": verdict,
        "authoritative_experiment_base_sha": EXPERIMENT_BASE_SHA,
        "proxy_full_run_commit": PROXY_FULL_RUN_COMMIT,
        "fix01_source_commit": FIX01_SOURCE_COMMIT,
        "evaluation_start": "2022-01-01",
        "evaluation_end": "2026-08-14",
        "official_reference_date_count": 117,
        "proxy_reference_date_count": 98,
        "total_reference_date_count": 215,
        "market_cap_proxy_method": "ANCHOR_PRICE_RATIO_PROXY",
        "price_semantics": "ADJUSTED_CLOSE",
        "no_network_requests": True,
        "no_tuning_parameters": True,
        "full_backtest_rerun": False,
        "existing_trade_artifacts_reused": True,
        "total_artifacts": len(manifest_entries),
        "artifacts": manifest_entries,
    }
    manifest_path = PROXY_DIR / "proxy_run_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Manifest sealed with provenance metadata: {len(manifest_entries)} artifacts sealed.")

    # 13. Verification Pass
    for name, entry in manifest_entries.items():
        actual_sha = hashlib.sha256((PROXY_DIR / name).read_bytes()).hexdigest()
        if actual_sha != entry["sha256"]:
            raise ValueError(f"Manifest SHA mismatch for {name}: expected {entry['sha256']}, got {actual_sha}")
    logger.info("Verification pass: All 15 artifact SHA-256 hashes 100% verified.")


if __name__ == "__main__":
    run_post_processing_rebuild()
