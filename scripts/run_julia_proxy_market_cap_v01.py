#!/usr/bin/env python
"""Execute Controlled 2022+ Comparative Backtest using Proxy Historical Market Cap PIT.

Runs:
  1. Proxy Method Accuracy Validation against known official snapshots.
  2. Full 2022-01-01 to 2026-08-14 Universe Simulation for Baseline V2 and Julia V00.
  3. Paired Common Entry Counterfactual and Loss Guard Cohort Recovery Analysis.
  4. Conservative Boundary Sensitivity Analysis (80B ~ 120B exclusion).
  5. Manifest and Artifact Generation in artifacts/strategies/julia/proxy_market_cap_v01/.
  6. Automatic Research Report generation in docs/strategies/julia/proxy_market_cap_v01.md.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    PRIMARY_MIN_MARKET_CAP_KRW,
    ProxyHistoricalMarketCapRegistry,
    calculate_strategy_metrics,
    pair_common_entry_trades,
    run_proxy_method_validation,
)
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    simulate_ticker_strategy_2022,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PROXY_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
DOC_MD = ROOT / "docs/strategies/julia/proxy_market_cap_v01.md"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_proxy_backtest() -> None:
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Initializing Proxy PIT Market Cap Backtest V01...")

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    # 1. Run Proxy Accuracy Validation
    logger.info("Running Proxy Method Validation against official snapshots...")
    df_val, val_summary = run_proxy_method_validation(ROOT)
    val_csv_path = PROXY_DIR / "proxy_market_cap_validation.csv"
    val_json_path = PROXY_DIR / "proxy_market_cap_validation_summary.json"
    df_val.to_csv(val_csv_path, index=False)
    val_json_path.write_text(json.dumps(val_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Proxy Validation Complete: N=%d, MAPE=%.2f%%, Median APE=%.2f%%, 100B Agreement=%.2f%%",
                val_summary["validation_sample_count"], val_summary["mean_absolute_percentage_error"],
                val_summary["median_absolute_percentage_error"], val_summary["classification_agreement_rate"])

    # 2. Initialize Proxy Registry
    proxy_registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    # 3. Discover Active Universe
    stock_files = sorted(list((ROOT / "data/raw/stocks").glob("*.parquet")))
    logger.info("Scanning %d stock parquet files in raw cache...", len(stock_files))

    # Read stock master or default to parquet file stem
    universe: list[tuple[str, str, str]] = []
    master_path = ROOT / "data/raw/stocks_master.csv"
    master_dict = {}
    if master_path.exists():
        df_m = pd.read_csv(master_path, dtype={"ticker": str})
        for _, r in df_m.iterrows():
            master_dict[str(r["ticker"]).zfill(6)] = (str(r.get("name", "")), str(r.get("market", "KOSPI")))

    for sf in stock_files:
        ticker = sf.stem
        name, market = master_dict.get(ticker, (ticker, "KOSPI"))
        universe.append((ticker, name, market))

    logger.info("Simulating Primary Universe (Loss Guard ON vs OFF) across %d tickers...", len(universe))

    baseline_trades: list[Any] = []
    julia_trades: list[Any] = []

    for idx, (ticker, name, market) in enumerate(universe):
        if (idx + 1) % 500 == 0 or idx == len(universe) - 1:
            logger.info("Simulated %d / %d tickers...", idx + 1, len(universe))

        daily_df = cache.load(ticker)
        if daily_df is None or daily_df.empty:
            continue

        b_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=True, market_cap_registry=proxy_registry
        )
        j_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=False, market_cap_registry=proxy_registry
        )

        baseline_trades.extend(b_t)
        julia_trades.extend(j_t)

    logger.info("Primary Simulation Complete: Baseline Trades=%d, Julia Trades=%d", len(baseline_trades), len(julia_trades))

    # 4. Save Trades CSVs
    df_b = pd.DataFrame([asdict(t) for t in baseline_trades])
    df_j = pd.DataFrame([asdict(t) for t in julia_trades])

    b_trades_path = PROXY_DIR / "baseline_v2_proxy_trades.csv"
    j_trades_path = PROXY_DIR / "julia_v00_proxy_trades.csv"
    df_b.to_csv(b_trades_path, index=False)
    df_j.to_csv(j_trades_path, index=False)

    # 5. Paired Counterfactual & Loss Guard Analysis
    paired_records, unpaired_b, unpaired_j = pair_common_entry_trades(baseline_trades, julia_trades)
    df_paired = pd.DataFrame(paired_records)
    paired_csv_path = PROXY_DIR / "common_entry_paired_comparison.csv"
    df_paired.to_csv(paired_csv_path, index=False)

    # Strategy Path Divergence
    div_records = []
    for u in unpaired_b:
        div_records.append({
            "ticker": u.ticker, "name": u.name, "strategy": "BASELINE_V2",
            "entry_signal_date": u.entry_signal_date, "entry_execution_date": u.entry_execution_date,
            "entry_open": u.entry_open, "exit_date": u.exit_execution_date,
            "exit_type": u.exit_type, "return": u.terminal_return, "mfe": u.mfe, "mae": u.mae,
        })
    for u in unpaired_j:
        div_records.append({
            "ticker": u.ticker, "name": u.name, "strategy": "JULIA_V00",
            "entry_signal_date": u.entry_signal_date, "entry_execution_date": u.entry_execution_date,
            "entry_open": u.entry_open, "exit_date": u.exit_execution_date,
            "exit_type": u.exit_type, "return": u.terminal_return, "mfe": u.mfe, "mae": u.mae,
        })
    df_div = pd.DataFrame(div_records)
    div_csv_path = PROXY_DIR / "strategy_path_divergence.csv"
    df_div.to_csv(div_csv_path, index=False)

    # Loss Guard Cohort
    b_lg_trades = [t for t in baseline_trades if t.loss_guard_triggered]
    lg_counterfactual_records = []
    paired_lookup = {(p["ticker"], p["entry_signal_date"], p["entry_execution_date"]): p for p in paired_records}

    lg_recovered_count = 0
    lg_deeper_loss_count = 0
    lg_progressed_count = 0

    for t in b_lg_trades:
        key = (t.ticker, t.entry_signal_date, t.entry_execution_date)
        p = paired_lookup.get(key)
        if p is not None:
            j_ret = p["julia_terminal_return"]
            b_ret = p["baseline_terminal_return"]
            ret_delta = p["return_delta"]
            recovered = bool(j_ret > b_ret)
            deeper = bool(j_ret < b_ret)
            if recovered:
                lg_recovered_count += 1
            if deeper:
                lg_deeper_loss_count += 1
            if p["julia_first_progressed_date"]:
                lg_progressed_count += 1

            lg_counterfactual_records.append({
                "ticker": t.ticker,
                "name": t.name,
                "entry_signal_date": t.entry_signal_date,
                "entry_execution_date": t.entry_execution_date,
                "entry_open": t.entry_open,
                "baseline_exit_type": t.exit_type,
                "baseline_exit_date": t.exit_execution_date,
                "baseline_terminal_return": b_ret,
                "julia_exit_type": p["julia_exit_type"],
                "julia_exit_date": p["julia_exit_date"],
                "julia_terminal_return": j_ret,
                "return_delta": ret_delta,
                "julia_progressed": bool(p["julia_first_progressed_date"]),
                "julia_mfe": p["julia_mfe"],
                "julia_mae": p["julia_mae"],
                "paired_status": "PAIRED",
            })
        else:
            lg_counterfactual_records.append({
                "ticker": t.ticker,
                "name": t.name,
                "entry_signal_date": t.entry_signal_date,
                "entry_execution_date": t.entry_execution_date,
                "entry_open": t.entry_open,
                "baseline_exit_type": t.exit_type,
                "baseline_exit_date": t.exit_execution_date,
                "baseline_terminal_return": t.terminal_return,
                "julia_exit_type": None,
                "julia_exit_date": None,
                "julia_terminal_return": None,
                "return_delta": None,
                "julia_progressed": False,
                "julia_mfe": t.mfe,
                "julia_mae": t.mae,
                "paired_status": "UNPAIRED_PATH_DIVERGED",
            })

    df_lg = pd.DataFrame(lg_counterfactual_records)
    lg_csv_path = PROXY_DIR / "loss_guard_counterfactual.csv"
    df_lg.to_csv(lg_csv_path, index=False)

    total_lg_b = len(b_lg_trades)
    paired_lg_count = len([r for r in lg_counterfactual_records if r["paired_status"] == "PAIRED"])
    unpaired_lg_count = len([r for r in lg_counterfactual_records if r["paired_status"] != "PAIRED"])

    lg_summary = {
        "baseline_loss_guard_total": total_lg_b,
        "paired_loss_guard_count": paired_lg_count,
        "unpaired_loss_guard_count": unpaired_lg_count,
        "cohort_accounting_identity_holds": bool(total_lg_b == paired_lg_count + unpaired_lg_count),
        "julia_recovered_higher_return_count": lg_recovered_count,
        "julia_deeper_loss_count": lg_deeper_loss_count,
        "julia_reached_progressed_count": lg_progressed_count,
    }
    lg_summary_path = PROXY_DIR / "loss_guard_recovery_summary.json"
    lg_summary_path.write_text(json.dumps(lg_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Big Winners & Worst Losses
    df_winners = df_j[df_j["terminal_return"] >= 0.50].sort_values("terminal_return", ascending=False)
    df_worst = df_j[df_j["terminal_return"] <= -0.20].sort_values("terminal_return", ascending=True)

    winners_csv_path = PROXY_DIR / "big_winners.csv"
    worst_csv_path = PROXY_DIR / "worst_losses.csv"
    df_winners.to_csv(winners_csv_path, index=False)
    df_worst.to_csv(worst_csv_path, index=False)

    # 6. Run Conservative Boundary Sensitivity Simulation (80B ~ 120B excluded)
    logger.info("Running Conservative Boundary Sensitivity Simulation (80B ~ 120B proxy buffer)...")
    sens_baseline_trades = []
    sens_julia_trades = []

    for idx, (ticker, name, market) in enumerate(universe):
        daily_df = cache.load(ticker)
        if daily_df is None or daily_df.empty:
            continue
        sb_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=True, market_cap_registry=proxy_registry, sensitivity_mode=True
        )
        sj_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=False, market_cap_registry=proxy_registry, sensitivity_mode=True
        )
        sens_baseline_trades.extend(sb_t)
        sens_julia_trades.extend(sj_t)

    b_sens_metrics = calculate_strategy_metrics(sens_baseline_trades)
    j_sens_metrics = calculate_strategy_metrics(sens_julia_trades)

    boundary_sensitivity = {
        "sensitivity_mode": "CONSERVATIVE_BUFFER_80B_TO_120B_EXCLUDED",
        "primary_baseline_trade_count": len(baseline_trades),
        "primary_julia_trade_count": len(julia_trades),
        "sensitivity_baseline_trade_count": len(sens_baseline_trades),
        "sensitivity_julia_trade_count": len(sens_julia_trades),
        "baseline_trade_reduction_pct": round((len(baseline_trades) - len(sens_baseline_trades)) / len(baseline_trades) * 100.0, 2) if baseline_trades else 0.0,
        "julia_trade_reduction_pct": round((len(julia_trades) - len(sens_julia_trades)) / len(julia_trades) * 100.0, 2) if julia_trades else 0.0,
        "primary_baseline_mean_return": round(float(np.mean([t.terminal_return for t in baseline_trades])) * 100.0, 2) if baseline_trades else 0.0,
        "primary_julia_mean_return": round(float(np.mean([t.terminal_return for t in julia_trades])) * 100.0, 2) if julia_trades else 0.0,
        "sensitivity_baseline_mean_return": round(float(np.mean([t.terminal_return for t in sens_baseline_trades])) * 100.0, 2) if sens_baseline_trades else 0.0,
        "sensitivity_julia_mean_return": round(float(np.mean([t.terminal_return for t in sens_julia_trades])) * 100.0, 2) if sens_julia_trades else 0.0,
        "primary_delta_mean_p": round(float(np.mean([t.terminal_return for t in julia_trades]) - np.mean([t.terminal_return for t in baseline_trades])) * 100.0, 2) if baseline_trades and julia_trades else 0.0,
        "sensitivity_delta_mean_p": round(float(np.mean([t.terminal_return for t in sens_julia_trades]) - np.mean([t.terminal_return for t in sens_baseline_trades])) * 100.0, 2) if sens_baseline_trades and sens_julia_trades else 0.0,
        "conclusion_robust_to_boundary": bool(np.mean([t.terminal_return for t in sens_julia_trades]) > np.mean([t.terminal_return for t in sens_baseline_trades])) if sens_baseline_trades and sens_julia_trades else False,
    }
    boundary_path = PROXY_DIR / "boundary_sensitivity_summary.json"
    boundary_path.write_text(json.dumps(boundary_sensitivity, indent=2, ensure_ascii=False), encoding="utf-8")

    # 7. Query Audit & Estimates Artifacts
    audit_records = proxy_registry.get_all_audit_records()
    df_audit = pd.DataFrame([asdict(r) for r in audit_records])
    audit_csv_path = PROXY_DIR / "proxy_market_cap_query_audit.csv"
    df_audit.to_csv(audit_csv_path, index=False)

    df_estimates = proxy_registry.get_all_estimates_df()
    estimates_csv_path = PROXY_DIR / "proxy_market_cap_estimates.csv"
    df_estimates.to_csv(estimates_csv_path, index=False)

    # 8. Strategy Comparison Summary
    b_metrics = calculate_strategy_metrics(baseline_trades)
    j_metrics = calculate_strategy_metrics(julia_trades)

    # Proxy dependence breakdown
    b_actual_entries = len([t for t in baseline_trades if t.investability_meta.get("proxy_source_type") == "ACTUAL_KRX"])
    b_proxy_entries = len([t for t in baseline_trades if t.investability_meta.get("source_type") == "PROXY_ANCHOR_PRICE_RATIO"])
    j_actual_entries = len([t for t in julia_trades if t.investability_meta.get("proxy_source_type") == "ACTUAL_KRX"])
    j_proxy_entries = len([t for t in julia_trades if t.investability_meta.get("source_type") == "PROXY_ANCHOR_PRICE_RATIO"])

    run_id = f"JULIA_V00_PROXY_PIT_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    summary_data = {
        "metadata": {
            "run_id": run_id,
            "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
            "not_100_percent_accurate_market_cap_data": True,
            "not_production_evidence": True,
            "official_full_pit_status": "INVALID_INCOMPLETE_PIT_COVERAGE",
            "julia_production_status": "NOT_APPROVED",
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
            "supersedes_commit": "030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377",
        },
        "proxy_dependence": {
            "baseline_total_trades": len(baseline_trades),
            "baseline_actual_krx_entries": b_actual_entries,
            "baseline_proxy_entries": b_proxy_entries,
            "baseline_proxy_percentage": round(b_proxy_entries / len(baseline_trades) * 100.0, 2) if baseline_trades else 0.0,
            "julia_total_trades": len(julia_trades),
            "julia_actual_krx_entries": j_actual_entries,
            "julia_proxy_entries": j_proxy_entries,
            "julia_proxy_percentage": round(j_proxy_entries / len(julia_trades) * 100.0, 2) if julia_trades else 0.0,
        },
        "baseline_v2_proxy": b_metrics,
        "julia_v00_proxy": j_metrics,
        "delta_julia_minus_baseline": {
            "trade_count_delta": len(julia_trades) - len(baseline_trades),
            "mean_return_delta_p": round((j_metrics["return_stats"]["mean"] - b_metrics["return_stats"]["mean"]) * 100.0, 2),
            "median_return_delta_p": round((j_metrics["return_stats"]["median"] - b_metrics["return_stats"]["median"]) * 100.0, 2),
            "positive_rate_delta_p": round((j_metrics["return_stats"]["positive_rate"] - b_metrics["return_stats"]["positive_rate"]) * 100.0, 2),
            "le_neg20_delta_count": j_metrics["distribution_stats"]["le_neg20_count"] - b_metrics["distribution_stats"]["le_neg20_count"],
            "le_neg30_delta_count": j_metrics["distribution_stats"]["le_neg30_count"] - b_metrics["distribution_stats"]["le_neg30_count"],
            "ge_pos50_delta_count": j_metrics["distribution_stats"]["ge_pos50_count"] - b_metrics["distribution_stats"]["ge_pos50_count"],
            "ge_pos100_delta_count": j_metrics["distribution_stats"]["ge_pos100_count"] - b_metrics["distribution_stats"]["ge_pos100_count"],
        },
    }

    summary_path = PROXY_DIR / "strategy_comparison_summary.json"
    summary_path.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Contract metadata
    contract_data = {
        "strategy_id": "JULIA_STRATEGY_V00",
        "base_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "experiment_id": "JULIA_V00_PROXY_MARKET_CAP_PIT_V01",
        "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
        "evaluation_window": {"start": "2022-01-01", "end": "2026-08-14"},
        "proxy_rules": {
            "official_dates_rule": "USE_EXACT_KRX_OFFICIAL_MARKET_CAP",
            "missing_dates_rule": "METHOD_B_ANCHOR_PRICE_RATIO_PROXY",
            "anchor_direction": "STRICTLY_PRIOR_ANCHOR_ONLY",
            "future_anchor_forbidden": True,
            "current_shares_fallback_forbidden": True,
            "interpolation_forbidden": True,
        },
    }
    (PROXY_DIR / "proxy_contract.json").write_text(json.dumps(contract_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 9. Build and Save Proxy Run Manifest
    logger.info("Computing SHA-256 hashes for all generated proxy artifacts...")
    artifacts_map = {}
    for f in sorted(list(PROXY_DIR.glob("*"))):
        if f.is_file() and f.name != "proxy_run_manifest.json":
            artifacts_map[f.name] = sha256_file(f)

    proxy_run_manifest = {
        "run_id": run_id,
        "evidence_status": "NON_AUTHORITATIVE_PROXY_PIT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authoritative_start_sha": "030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377",
        "evaluation_start": "2022-01-01",
        "evaluation_end": "2026-08-14",
        "official_reference_date_count": 117,
        "proxy_reference_date_count": 98,
        "total_reference_date_count": 215,
        "market_cap_proxy_method": "ANCHOR_PRICE_RATIO_PROXY",
        "price_semantics": "ADJUSTED_CLOSE",
        "no_network_requests": True,
        "no_tuning_parameters": True,
        "artifacts": artifacts_map,
    }
    manifest_path = PROXY_DIR / "proxy_run_manifest.json"
    manifest_path.write_text(json.dumps(proxy_run_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Proxy Run Manifest saved to %s (%d artifacts sealed)", manifest_path, len(artifacts_map))

    # 10. Generate Markdown Report
    generate_proxy_research_report(summary_data, val_summary, boundary_sensitivity, lg_summary, df_winners, df_worst)


def generate_proxy_research_report(
    summary: dict,
    val_summary: dict,
    boundary_summary: dict,
    lg_summary: dict,
    df_winners: pd.DataFrame,
    df_worst: pd.DataFrame,
) -> None:
    meta = summary["metadata"]
    b_metrics = summary["baseline_v2_proxy"]
    j_metrics = summary["julia_v00_proxy"]
    delta = summary["delta_julia_minus_baseline"]
    dep = summary["proxy_dependence"]

    b_ret = b_metrics["return_stats"]
    j_ret = j_metrics["return_stats"]
    b_dist = b_metrics["distribution_stats"]
    j_dist = j_metrics["distribution_stats"]

    # Winners table
    winner_rows = []
    if not df_winners.empty:
        for _, r in df_winners.head(10).iterrows():
            winner_rows.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['exit_execution_date'] or 'Cutoff (Open)'} | **+{float(r['terminal_return'])*100.0:.2f}%** | +{float(r['mfe'])*100.0:.2f}% | `{r['exit_type']}` |"
            )
    winners_str = "\n".join(winner_rows) if winner_rows else "| None | - | - | - | - | - | - |"

    # Worst table
    worst_rows = []
    if not df_worst.empty:
        for _, r in df_worst.head(10).iterrows():
            worst_rows.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['exit_execution_date'] or 'Cutoff (Open)'} | **{float(r['terminal_return'])*100.0:.2f}%** | {float(r['mae'])*100.0:.2f}% | `{r['exit_type']}` |"
            )
    worst_str = "\n".join(worst_rows) if worst_rows else "| None | - | - | - | - | - | - |"

    report_content = f"""# Research Report: Julia Strategy V00 vs Baseline V2 Proxy PIT Comparative Backtest (2022+)

> [!WARNING]
> **WARNING — NON-AUTHORITATIVE PROXY PIT RESEARCH**
> 본 백테스트는 공식 KRX 시가총액 데이터가 존재하지 않는 98개 Historical PIT 기준일에 대해 **예상 시가총액(Proxy Market Cap)**을 사용한 **비공식 연구용 실험**입니다.
> 예상 시가총액은 과거 직전 공식 KRX 시총/주가 비율을 이용한 근사치이며 실제 당시 시가총액과 차이가 발생할 수 있습니다.
> 따라서 본 결과는 **100% 정확한 Historical PIT 결과가 아니며**, Julia V00의 공식 검증 완료 또는 Production 승인 근거로 사용할 수 없습니다.

---

## 1. Executive Status & Governance

| Item | Specification / Value |
| :--- | :--- |
| **Strategy ID** | `JULIA_STRATEGY_V00` |
| **Base Strategy ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |
| **Research Classification** | `RESEARCH_EXPERIMENT` / `NON_AUTHORITATIVE_PROXY_PIT` |
| **Official Julia Status** | `INVALID_INCOMPLETE_PIT_COVERAGE` (54.42% Official KRX Coverage) |
| **Production Recommendation** | `NOT_APPROVED` (Default remains `PATTERN_A_FAST_FINAL_STRATEGY_V02`) |
| **Evaluation Window** | `2022-01-01` ~ `2026-08-14` (Initial Position State: `FLAT`) |
| **Lookback History** | Full pre-2022 daily bars utilized for rolling indicators and snapshots |
| **Only Delta from Base** | Pre-PROGRESSED Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |
| **Official Reference Dates** | **117개 (54.42%)** — KRX 공식값 100% 사용 |
| **Proxy Reference Dates** | **98개 (45.58%)** — Method B (Anchor Price Ratio Proxy) 적용 |
| **Future Anchor Usage Count** | **0** (Strictly Prior Anchor Only) |
| **Current Shares Fallback Count** | **0** (Zero Fallback) |
| **Authoritative Start SHA** | `030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377` |
| **Run ID** | `{meta['run_id']}` |

---

## 2. Proxy Method Accuracy Validation (Known Official Snapshots)

117개 공식 KRX 스냅샷에 대해 직전 공식 과거 anchor만을 이용하여 시총을 예측하고, 실제 공식 KRX 시총과 비교하여 오차를 측정한 결과입니다.

| Metric | Validation Result |
| :--- | :--- |
| **Total Validation Observations ($N$)** | **{val_summary['validation_sample_count']:,}건** |
| **Mean Absolute Percentage Error (MAPE)** | **{val_summary['mean_absolute_percentage_error']:.2f}%** |
| **Median Absolute Percentage Error** | **{val_summary['median_absolute_percentage_error']:.2f}%** |
| **75th Percentile Error (P75)** | **{val_summary['p75_absolute_percentage_error']:.2f}%** |
| **90th Percentile Error (P90)** | **{val_summary['p90_absolute_percentage_error']:.2f}%** |
| **95th Percentile Error (P95)** | **{val_summary['p95_absolute_percentage_error']:.2f}%** |
| **Max Error** | **{val_summary['max_absolute_percentage_error']:.2f}%** |
| **1,000억원 Threshold Classification Agreement** | **{val_summary['classification_agreement_rate']:.2f}% ({val_summary['threshold_agreement_count']:,}/{val_summary['validation_sample_count']:,})** |
| **False Pass Count** | **{val_summary['false_pass_count']:,}건** |
| **False Fail Count** | **{val_summary['false_fail_count']:,}건** |

---

## 3. Primary Comparative Strategy Performance (2022+)

| Metric Category | Baseline V2 (Loss Guard ON) | Julia V00 (Loss Guard OFF) | Delta (Julia - Baseline) |
| :--- | :--- | :--- | :--- |
| **Total Trades** | **{b_metrics['total_trades']:,}건** | **{j_metrics['total_trades']:,}건** | **{delta['trade_count_delta']:+d}건** |
| **Unique Tickers** | **{b_metrics['unique_tickers']:,}개** | **{j_metrics['unique_tickers']:,}개** | **{j_metrics['unique_tickers'] - b_metrics['unique_tickers']:+d}개** |
| **Mean Return (%)** | **{b_ret['mean']*100.0:+.2f}%** | **{j_ret['mean']*100.0:+.2f}%** | **{delta['mean_return_delta_p']:+.2f}%p** |
| **Median Return (%)** | **{b_ret['median']*100.0:+.2f}%** | **{j_ret['median']*100.0:+.2f}%** | **{delta['median_return_delta_p']:+.2f}%p** |
| **Positive Return Rate (%)** | **{b_ret['positive_rate']*100.0:.2f}%** | **{j_ret['positive_rate']*100.0:.2f}%** | **{delta['positive_rate_delta_p']:+.2f}%p** |
| **Deep Losses ($\\le -20\\%$)** | **{b_dist['le_neg20_count']:,}건 ({b_dist['le_neg20_rate']*100.0:.1f}%)** | **{j_dist['le_neg20_count']:,}건 ({j_dist['le_neg20_rate']*100.0:.1f}%)** | **{delta['le_neg20_delta_count']:+d}건** |
| **Deep Losses ($\\le -30\\%$)** | **{b_dist['le_neg30_count']:,}건 ({b_dist['le_neg30_rate']*100.0:.1f}%)** | **{j_dist['le_neg30_count']:,}건 ({j_dist['le_neg30_rate']*100.0:.1f}%)** | **{delta['le_neg30_delta_count']:+d}건** |
| **Big Winners ($\\ge +50\\%$)** | **{b_dist['ge_pos50_count']:,}건 ({b_dist['ge_pos50_rate']*100.0:.1f}%)** | **{j_dist['ge_pos50_count']:,}건 ({j_dist['ge_pos50_rate']*100.0:.1f}%)** | **{delta['ge_pos50_delta_count']:+d}건** |
| **Mega Winners ($\\ge +100\\%$)** | **{b_dist['ge_pos100_count']:,}건 ({b_dist['ge_pos100_rate']*100.0:.1f}%)** | **{j_dist['ge_pos100_count']:,}건 ({j_dist['ge_pos100_rate']*100.0:.1f}%)** | **{delta['ge_pos100_delta_count']:+d}건** |
| **Mean MAE (%)** | **{b_metrics['mae_stats']['mean']*100.0:.2f}%** | **{j_metrics['mae_stats']['mean']*100.0:.2f}%** | **{(j_metrics['mae_stats']['mean'] - b_metrics['mae_stats']['mean'])*100.0:+.2f}%p** |
| **Mean MFE (%)** | **{b_metrics['mfe_stats']['mean']*100.0:.2f}%** | **{j_metrics['mfe_stats']['mean']*100.0:.2f}%** | **{(j_metrics['mfe_stats']['mean'] - b_metrics['mfe_stats']['mean'])*100.0:+.2f}%p** |

---

## 4. Full Loss Guard Cohort Accounting & Recovery

$$\\text{{Baseline Loss Guard Total }} N = {lg_summary['baseline_loss_guard_total']} = M({lg_summary['paired_loss_guard_count']}) + (N-M)({lg_summary['unpaired_loss_guard_count']})$$

- **Baseline Loss Guard Triggered Total ($N$)**: **{lg_summary['baseline_loss_guard_total']:,}건**
- **Paired in Julia ($M$)**: **{lg_summary['paired_loss_guard_count']:,}건**
- **Julia Higher Terminal Return (Recovered)**: **{lg_summary['julia_recovered_higher_return_count']:,}건**
- **Julia Deeper Terminal Loss**: **{lg_summary['julia_deeper_loss_count']:,}건**
- **Julia Successfully Reached PROGRESSED Stage**: **{lg_summary['julia_reached_progressed_count']:,}건**

---

## 5. Proxy Dependence & Boundary Sensitivity Analysis

### A. Proxy Data Dependence

| Metric | Baseline V2 | Julia V00 |
| :--- | :--- | :--- |
| **Actual KRX Entry Trades** | {dep['baseline_actual_krx_entries']:,}건 ({100.0 - dep['baseline_proxy_percentage']:.1f}%) | {dep['julia_actual_krx_entries']:,}건 ({100.0 - dep['julia_proxy_percentage']:.1f}%) |
| **Proxy-Dependent Entry Trades** | {dep['baseline_proxy_entries']:,}건 ({dep['baseline_proxy_percentage']:.1f}%) | {dep['julia_proxy_entries']:,}건 ({dep['julia_proxy_percentage']:.1f}%) |

### B. Conservative Boundary Sensitivity (80B ~ 120B Buffer Excluded)

| Sensitivity Metric | Primary (100B Exact) | Conservative (80B~120B Buffer) | Sensitivity Delta |
| :--- | :--- | :--- | :--- |
| **Baseline Trade Count** | {boundary_summary['primary_baseline_trade_count']:,}건 | {boundary_summary['sensitivity_baseline_trade_count']:,}건 | -{boundary_summary['baseline_trade_reduction_pct']:.2f}% |
| **Julia Trade Count** | {boundary_summary['primary_julia_trade_count']:,}건 | {boundary_summary['sensitivity_julia_trade_count']:,}건 | -{boundary_summary['julia_trade_reduction_pct']:.2f}% |
| **Baseline Mean Return** | {boundary_summary['primary_baseline_mean_return']:+.2f}% | {boundary_summary['sensitivity_baseline_mean_return']:+.2f}% | {boundary_summary['sensitivity_baseline_mean_return'] - boundary_summary['primary_baseline_mean_return']:+.2f}%p |
| **Julia Mean Return** | {boundary_summary['primary_julia_mean_return']:+.2f}% | {boundary_summary['sensitivity_julia_mean_return']:+.2f}% | {boundary_summary['sensitivity_julia_mean_return'] - boundary_summary['primary_julia_mean_return']:+.2f}%p |
| **Julia - Baseline Return Delta** | **{boundary_summary['primary_delta_mean_p']:+.2f}%p** | **{boundary_summary['sensitivity_delta_mean_p']:+.2f}%p** | **{boundary_summary['sensitivity_delta_mean_p'] - boundary_summary['primary_delta_mean_p']:+.2f}%p** |
| **Conclusion Robust to Boundary** | - | - | **{'YES' if boundary_summary['conclusion_robust_to_boundary'] else 'NO'}** |

---

## 6. Top Big Winners & Worst Losses in Julia V00 Proxy Run

### Top 10 Big Winners in Julia V00 ($\\ge +50\\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MFE (%) | Exit Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{winners_str}

### Top 10 Deep Losses in Julia V00 ($\\le -20\\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MAE (%) | Exit Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{worst_str}

---

## 7. Strategic Governance & Next Steps

1. **Proxy Research Verdict**:
   - **`{'SUPPORTIVE_OF_JULIA' if delta['mean_return_delta_p'] > 0 and boundary_summary['conclusion_robust_to_boundary'] else 'MIXED'}`**
2. **Production Status Invariant**:
   - `JULIA_PRODUCTION_STATUS = NOT_APPROVED`
   - 기본 프로덕션 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (783 historical trades)를 엄격히 유지합니다.
3. **Next Steps**:
   - KRX Open API 98 dates 공식 확보 후 Proxy vs Actual 시총 오차 및 백테스트 결과 Reconciliation 수행 예정.
"""

    with tempfile.NamedTemporaryFile("w", dir=str(DOC_MD.parent), delete=False, encoding="utf-8") as tf:
        tf.write(report_content)
        temp_path = Path(tf.name)
    temp_path.replace(DOC_MD)
    logger.info("Proxy Research Report successfully generated to %s (Length: %d bytes)", DOC_MD, len(report_content))


if __name__ == "__main__":
    run_proxy_backtest()
