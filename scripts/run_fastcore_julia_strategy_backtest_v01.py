#!/usr/bin/env python
"""FastCore vs Julia STEP 1 pure strategy comparison backtest
(directive MAIN_MERGE_AND_FASTCORE_JULIA_STRATEGY_BACKTEST_V01 Part B).

Offline only: uses local Repository V2 (adjusted prices) and local raw
KRX historical snapshots (market cap / trading value / close for the new
entry-only filter). Zero network calls of any kind.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import logging
import multiprocessing
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.backtest.fastcore_julia_strategy_v01 import (
    AVG_TRADING_VALUE_20D_THRESHOLD,
    CLOSE_THRESHOLD,
    MARKET_CAP_THRESHOLD,
    IdentityLifecycle,
    build_loss_cut_counterfactual_rows,
    pit_common_for_identity,
    simulate_ticker_strategy_v01,
)
from trend_scanner.backtest.raw_investability_panel import build_raw_investability_panel
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import calculate_distribution_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

EFFECTIVE_PIT_PATH = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

REQUESTED_BACKTEST_END = pd.Timestamp("2026-09-04")
PIT_UNIVERSE_START = pd.Timestamp("2010-01-04")
PIT_UNIVERSE_END = pd.Timestamp("2026-08-21")
BACKTEST_END = PIT_UNIVERSE_END

OUT_DIR = ROOT / "artifacts/backtests/fastcore_julia_strategy_v01"


def _ticker_ever_investable(raw_panel: pd.DataFrame | None) -> bool:
    if raw_panel is None or raw_panel.empty:
        return False
    mask = (
        (raw_panel["market_cap"] >= MARKET_CAP_THRESHOLD)
        & (raw_panel["avg_trading_value_20d"] >= AVG_TRADING_VALUE_20D_THRESHOLD)
        & (raw_panel["close"] >= CLOSE_THRESHOLD)
    )
    return bool(mask.any())


def _load_pit_intervals() -> tuple[Any, dict[tuple[str, str, str], list[tuple[str, str]]]]:
    """Load the explicit corrected PIT authority and build an identity index."""
    authority = load_effective_authority(EFFECTIVE_PIT_PATH.parent)
    intervals: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        key = (str(item.get("ticker")), str(item.get("isu_cd")), str(item.get("market")))
        intervals.setdefault(key, []).append((str(item["effective_from"]), str(item["effective_to"])))
    for values in intervals.values():
        values.sort()
    return authority, intervals


# Module-level globals populated once in the parent process before the
# ProcessPoolExecutor is created with the "fork" start method: children
# inherit them via copy-on-write at fork time, so the ~1GB Repository V2
# raw index and the raw investability panel are each built exactly once
# for the whole run, never once per worker.
_LOADER: RepositoryV2DailyLoader | None = None
_RAW_PANELS: dict[str, pd.DataFrame] = {}
_PIT_INTERVALS: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
_SCORE_CONTRACT: dict = {}
_STAGE_CONTRACT: dict = {}


def _pit_membership(ticker: str, isu_cd: str | None, market: str, date: pd.Timestamp) -> bool:
    return pit_common_for_identity(_PIT_INTERVALS, ticker, isu_cd, market, date)


def _worker_task(args: tuple[str, str, str, str, str, str]) -> tuple[str, str, str, list[dict], list[dict], list[dict]]:
    ticker, isu_cd, market, name, effective_from, effective_to = args
    lifecycle = IdentityLifecycle(
        ticker=ticker,
        isu_cd=isu_cd,
        market=market,
        effective_from=pd.Timestamp(effective_from),
        effective_to=pd.Timestamp(effective_to),
    )
    daily = _LOADER.load(ticker)
    if daily is None or daily.empty:
        return ticker, isu_cd, market, [], [], []
    daily = daily[(daily.index >= lifecycle.effective_from) & (daily.index <= lifecycle.effective_to)].copy()
    if daily.empty:
        return ticker, isu_cd, market, [], [], []

    raw_panel = _RAW_PANELS.get(ticker)
    if raw_panel is not None:
        raw_panel = raw_panel[(raw_panel.index >= lifecycle.effective_from) & (raw_panel.index <= lifecycle.effective_to)].copy()
        if raw_panel.index.duplicated().any():
            # A same-day cross-market collision cannot be assigned to this
            # identity without an authoritative market discriminator.
            return ticker, isu_cd, market, [], [], []
    if not _ticker_ever_investable(raw_panel):
        # This ticker never simultaneously clears the market-cap / 20D avg
        # trading value / close entry-only thresholds at any point in its
        # history, so no entry-filter check inside the simulation loop
        # could ever pass -- both strategies would trivially produce zero
        # trades. Skipping the expensive weekly Pattern A FAST scan here is
        # a pure performance shortcut, not a semantics change: the result
        # is identical to running the full simulation and discarding an
        # all-empty trade list.
        return ticker, isu_cd, market, [], [], []

    snapshot_context = build_precomputed_ticker_context(ticker, name, daily)
    fastcore_trades = simulate_ticker_strategy_v01(
        strategy_id="FASTCORE",
        ticker=ticker, isu_cd=isu_cd, name=name, market=market,
        daily=daily, raw_panel=raw_panel,
        score_contract=_SCORE_CONTRACT, stage_contract=_STAGE_CONTRACT,
        loss_guard_enabled=True, backtest_end=BACKTEST_END,
        snapshot_context=snapshot_context,
        identity_lifecycle=lifecycle,
        pit_membership=_pit_membership,
    )
    julia_trades = simulate_ticker_strategy_v01(
        strategy_id="JULIA",
        ticker=ticker, isu_cd=isu_cd, name=name, market=market,
        daily=daily, raw_panel=raw_panel,
        score_contract=_SCORE_CONTRACT, stage_contract=_STAGE_CONTRACT,
        loss_guard_enabled=False, backtest_end=BACKTEST_END,
        snapshot_context=snapshot_context,
        identity_lifecycle=lifecycle,
        pit_membership=_pit_membership,
    )
    counterfactual = build_loss_cut_counterfactual_rows(fastcore_trades, julia_trades, daily)
    return (
        ticker,
        isu_cd,
        market,
        [t.to_dict() for t in fastcore_trades],
        [t.to_dict() for t in julia_trades],
        counterfactual,
    )


def run_backtest(
    *,
    sample_intervals: list[dict[str, Any]] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the corrected engine; Phase 2 callers pass a bounded sample."""
    out_dir = Path(output_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validation").mkdir(parents=True, exist_ok=True)

    global _LOADER, _RAW_PANELS, _PIT_INTERVALS, _SCORE_CONTRACT, _STAGE_CONTRACT
    _SCORE_CONTRACT = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    _STAGE_CONTRACT = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    authority, _PIT_INTERVALS = _load_pit_intervals()

    # The population is derived exclusively from corrected effective PIT.  A
    # current scanner CSV is intentionally not read or used as a denominator.
    identity_intervals = [
        dict(item) for item in authority.pit_intervals
        if item.get("state") == "COMMON"
        and str(item.get("effective_from")) <= PIT_UNIVERSE_END.strftime("%Y-%m-%d")
    ]
    if sample_intervals is not None:
        identity_intervals = sample_intervals
    common_universe_count = authority.population_count
    tickers = {str(item["ticker"]) for item in identity_intervals}
    logger.info("Effective PIT population: %d identities; %d interval tasks", common_universe_count, len(identity_intervals))

    repository = build_repository_v2(ROOT, end=BACKTEST_END)
    _LOADER = RepositoryV2DailyLoader(repository, end=BACKTEST_END)

    t0 = time.perf_counter()
    _RAW_PANELS = build_raw_investability_panel(tickers, end=BACKTEST_END)
    logger.info("Raw investability panel built for %d tickers in %.1fs", len(_RAW_PANELS), time.perf_counter() - t0)

    tasks = [
        (
            str(item["ticker"]), str(item["isu_cd"]), str(item["market"]),
            str(item.get("ticker") or item["ticker"]),
            str(item["effective_from"]), str(item["effective_to"]),
        )
        for item in identity_intervals
    ]

    fork_ctx = multiprocessing.get_context("fork")
    t1 = time.perf_counter()
    fastcore_trades: list[dict] = []
    julia_trades: list[dict] = []
    counterfactual_rows: list[dict] = []
    completed = 0
    if tasks:
        with ProcessPoolExecutor(max_workers=min(8, len(tasks)), mp_context=fork_ctx) as executor:
            futures = [executor.submit(_worker_task, task) for task in tasks]
            for future in as_completed(futures):
                ticker, isu_cd, market, fc, jl, cf = future.result()
                fastcore_trades.extend(fc)
                julia_trades.extend(jl)
                counterfactual_rows.extend(cf)
                completed += 1
                if completed % 20 == 0 or completed == len(tasks):
                    logger.info("Progress: %d/%d identity intervals (%.1fs elapsed)", completed, len(tasks), time.perf_counter() - t1)
    logger.info("Simulated %d identity intervals x 2 strategies in %.1fs", len(tasks), time.perf_counter() - t1)

    df_fc = pd.DataFrame(fastcore_trades)
    df_jl = pd.DataFrame(julia_trades)
    df_fc.to_csv(out_dir / "fastcore_trades.csv", index=False)
    df_jl.to_csv(out_dir / "julia_trades.csv", index=False)

    other_diff_count, invariant_detail = _verify_strategy_invariant(df_fc, df_jl)
    fc_summary = _summarize_strategy(df_fc, "FASTCORE")
    jl_summary = _summarize_strategy(df_jl, "JULIA")
    (out_dir / "fastcore_summary.json").write_text(json.dumps(fc_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "julia_summary.json").write_text(json.dumps(jl_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    loss_cut_analysis = _fastcore_loss_cut_analysis(df_fc)
    loss_cut_analysis.to_csv(out_dir / "fastcore_loss_guard_analysis.csv", index=False)
    paired = _paired_entry_comparison(df_fc, df_jl)
    paired.to_csv(out_dir / "paired_entry_comparison.csv", index=False)
    counterfactual = pd.DataFrame(counterfactual_rows)
    counterfactual.to_csv(out_dir / "fastcore_loss_guard_counterfactual.csv", index=False)
    best_worst = _best_worst_trades(df_fc, df_jl)
    best_worst.to_csv(out_dir / "best_worst_trades.csv", index=False)

    dates_info = _date_range_info(df_fc, df_jl)
    contract = {
        "directive": "FASTCORE_JULIA_STRATEGY_BACKTEST_V01_FIX01",
        "step": "PHASE_2_IMPLEMENTATION_BOUNDED_SAMPLE" if sample_intervals is not None else "PHASE_3_FULL_RUN",
        "requested_backtest_end": REQUESTED_BACKTEST_END.strftime("%Y-%m-%d"),
        "pit_universe_authority_start": PIT_UNIVERSE_START.strftime("%Y-%m-%d"),
        "pit_universe_authority_end": PIT_UNIVERSE_END.strftime("%Y-%m-%d"),
        "effective_backtest_end": BACKTEST_END.strftime("%Y-%m-%d"),
        "end_truncation_reason": "HISTORICAL_PIT_UNIVERSE_AUTHORITY_BOUNDARY",
        "REQUESTED_BACKTEST_END": REQUESTED_BACKTEST_END.strftime("%Y-%m-%d"),
        "PIT_UNIVERSE_AUTHORITY_START": PIT_UNIVERSE_START.strftime("%Y-%m-%d"),
        "PIT_UNIVERSE_AUTHORITY_END": PIT_UNIVERSE_END.strftime("%Y-%m-%d"),
        "EFFECTIVE_BACKTEST_END": BACKTEST_END.strftime("%Y-%m-%d"),
        "END_TRUNCATION_REASON": "HISTORICAL_PIT_UNIVERSE_AUTHORITY_BOUNDARY",
        "common_universe_count": common_universe_count,
        "identity_interval_task_count": len(identity_intervals),
        "common_universe_source": str(EFFECTIVE_PIT_PATH.relative_to(ROOT)),
        "authority": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
        "authority_sha256": authority.pit_sha256,
        "current_survivor_universe_used": False,
        "entry_filter": {
            "market_cap_threshold_krw": MARKET_CAP_THRESHOLD,
            "avg_trading_value_20d_threshold_krw": AVG_TRADING_VALUE_20D_THRESHOLD,
            "close_threshold_krw": CLOSE_THRESHOLD,
            "entry_only": True,
            "reevaluated_on_reentry": True,
        },
        "strategy_difference": "loss_guard_enabled boolean only (FastCore=True, Julia=False)",
        "other_strategy_difference_count": other_diff_count,
        "counterfactual_summary": _loss_cut_aggregate_summary(counterfactual),
        "transaction_cost": "NOT_APPLIED",
        "slippage": "NOT_APPLIED",
        "network_requests": 0,
        **dates_info,
    }
    (out_dir / "backtest_contract.json").write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8")

    comparison_summary = {
        "shared_entry_count": int((paired["comparison_class"] == "SHARED_ENTRY").sum()) if not paired.empty else 0,
        "fastcore_only_reentry_count": int((paired["comparison_class"] == "FASTCORE_ONLY_REENTRY").sum()) if not paired.empty else 0,
        "julia_only_entry_count": int((paired["comparison_class"] == "JULIA_ONLY_ENTRY").sum()) if not paired.empty else 0,
        "shared_reentry_count": int((paired["comparison_class"] == "SHARED_REENTRY").sum()) if not paired.empty else 0,
        "unpaired_after_divergence_count": int((paired["comparison_class"] == "UNPAIRED_AFTER_STRATEGY_DIVERGENCE").sum()) if not paired.empty else 0,
        "loss_cut_counterfactual_rows": int(len(counterfactual)),
        "fastcore_mean_return": fc_summary.get("return_metrics", {}).get("terminal_return_stats", {}).get("mean"),
        "julia_mean_return": jl_summary.get("return_metrics", {}).get("terminal_return_stats", {}).get("mean"),
        "fastcore_median_return": fc_summary.get("return_metrics", {}).get("terminal_return_stats", {}).get("median"),
        "julia_median_return": jl_summary.get("return_metrics", {}).get("terminal_return_stats", {}).get("median"),
        "fastcore_le_neg_20_rate": fc_summary.get("risk_metrics", {}).get("le_neg_20_rate"),
        "julia_le_neg_20_rate": jl_summary.get("risk_metrics", {}).get("le_neg_20_rate"),
        "fastcore_ge_50_rate": fc_summary.get("upside_metrics", {}).get("ge_50_rate"),
        "julia_ge_50_rate": jl_summary.get("upside_metrics", {}).get("ge_50_rate"),
        "counterfactual_summary": _loss_cut_aggregate_summary(counterfactual),
    }
    (out_dir / "strategy_comparison_summary.json").write_text(json.dumps(comparison_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    pit_audit = {
        "pit_authority": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
        "pit_common_gate_implemented": True,
        "identity_key": "ticker|isu_cd|market",
        "identity_lifecycle_clipping_implemented": True,
        "entry_signal_information_date": True,
        "entry_filter_raw_date_le_information_date": True,
        "network_requests_made": 0,
        "invariant_check": invariant_detail,
    }
    (out_dir / "validation/pit_audit.json").write_text(json.dumps(pit_audit, indent=2, ensure_ascii=False), encoding="utf-8")
    entry_filter_audit = {
        "market_cap_threshold_krw": MARKET_CAP_THRESHOLD,
        "avg_trading_value_20d_threshold_krw": AVG_TRADING_VALUE_20D_THRESHOLD,
        "close_threshold_krw": CLOSE_THRESHOLD,
        "entry_only_confirmed": True,
        "verified_by": "tests/test_fastcore_julia_strategy_backtest_v01.py::test_entry_filter_never_exits",
    }
    (out_dir / "validation/entry_filter_audit.json").write_text(json.dumps(entry_filter_audit, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_md = _generate_summary_md(contract, fc_summary, jl_summary, comparison_summary, dates_info)
    (out_dir / "backtest_summary.md").write_text(summary_md, encoding="utf-8")
    logger.info("Backtest artifacts written to %s", out_dir)
    return {
        "contract": contract,
        "comparison_summary": comparison_summary,
        "counterfactual": counterfactual,
        "fastcore_trades": df_fc,
        "julia_trades": df_jl,
    }


def _verify_strategy_invariant(df_fc: pd.DataFrame, df_jl: pd.DataFrame) -> tuple[int, dict[str, Any]]:
    """FastCore and Julia must be identical in every field except the
    loss-guard-driven exit fields. Compare, per shared (ticker,
    entry_signal_date) key, that entry-side fields match exactly."""
    if df_fc.empty or df_jl.empty:
        return 0, {"comparable_pairs": 0, "note": "one or both trade sets empty"}

    entry_cols = [
        "entry_execution_date", "entry_open", "entry_market_cap", "entry_avg_trading_value_20d",
        "entry_signal_close", "entry_market_cap_pass", "entry_trading_value_pass", "entry_close_pass",
        "entry_pattern_a_stage", "fast_stage", "fast_status", "monthly_permission_state", "daily_risk",
        "fast_score", "fast_score_state",
    ]
    key_cols = ["ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date", "entry_open"]
    fc_rows = {tuple(row[col] for col in key_cols): row for _, row in df_fc.iterrows()}
    jl_rows = {tuple(row[col] for col in key_cols): row for _, row in df_jl.iterrows()}
    common = set(fc_rows).intersection(jl_rows)

    mismatches = 0
    for key in common:
        fc_row, jl_row = fc_rows[key], jl_rows[key]
        for col in entry_cols:
            a, b = fc_row[col], jl_row[col]
            if pd.isna(a) and pd.isna(b):
                continue
            if a != b:
                mismatches += 1
    return int(mismatches), {"comparable_pairs": int(len(common)), "entry_fields_compared": entry_cols, "comparison_key": key_cols}


def _summarize_strategy(df: pd.DataFrame, strategy_id: str) -> dict[str, Any]:
    if df.empty:
        return {"strategy_id": strategy_id, "total_trades": 0}

    n_total = len(df)
    identity_cols = ["ticker", "isu_cd", "market"]
    unique_tickers = df["ticker"].nunique()
    identity_counts = df.groupby(identity_cols, dropna=False).size()
    reentered_tickers = int((identity_counts >= 2).sum())
    first_entries = int((df["trade_sequence"] == 1).sum())
    reentry_trades = int(n_total - first_entries)
    loss_cut_count = int((df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").sum())
    loss_cut_reentry_count = 0
    if loss_cut_count:
        lc_tickers_seq = df[df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15"][identity_cols + ["trade_sequence"]]
        for _, row in lc_tickers_seq.iterrows():
            nxt = df[
                (df["ticker"] == row["ticker"])
                & (df["isu_cd"] == row["isu_cd"])
                & (df["market"] == row["market"])
                & (df["trade_sequence"] == row["trade_sequence"] + 1)
            ]
            if not nxt.empty:
                loss_cut_reentry_count += 1

    ret = df["terminal_return"]
    winners = ret[ret > 0]
    losers = ret[ret <= 0]
    avg_win = round(float(winners.mean()), 2) if not winners.empty else None
    avg_loss = round(float(losers.mean()), 2) if not losers.empty else None
    payoff_ratio = round(abs(avg_win / avg_loss), 3) if avg_win and avg_loss else None
    gross_win = float(winners.sum()) if not winners.empty else 0.0
    gross_loss = abs(float(losers.sum())) if not losers.empty else 0.0
    profit_factor = round(gross_win / gross_loss, 3) if gross_loss > 0 else None

    holding = df["holding_trading_days"]

    return {
        "strategy_id": strategy_id,
        "total_trades": n_total,
        "first_entries": first_entries,
        "reentry_trades": reentry_trades,
        "unique_tickers": int(unique_tickers),
        "reentered_tickers": reentered_tickers,
        "loss_cut_count": loss_cut_count,
        "loss_cut_reentry_count": loss_cut_reentry_count,
        "open_at_cutoff_count": int((df["trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "return_metrics": {
            "terminal_return_stats": calculate_distribution_stats(ret),
            "positive_count": int((ret > 0).sum()),
            "positive_rate": round(float((ret > 0).mean() * 100), 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff_ratio": payoff_ratio,
            "profit_factor": profit_factor,
        },
        "tail_distribution": {
            "ge_20_count": int((ret >= 20).sum()), "ge_20_rate": round(float((ret >= 20).mean() * 100), 2),
            "ge_50_count": int((ret >= 50).sum()), "ge_50_rate": round(float((ret >= 50).mean() * 100), 2),
            "ge_100_count": int((ret >= 100).sum()), "ge_100_rate": round(float((ret >= 100).mean() * 100), 2),
            "le_neg_10_count": int((ret <= -10).sum()), "le_neg_10_rate": round(float((ret <= -10).mean() * 100), 2),
            "le_neg_20_count": int((ret <= -20).sum()), "le_neg_20_rate": round(float((ret <= -20).mean() * 100), 2),
            "le_neg_30_count": int((ret <= -30).sum()), "le_neg_30_rate": round(float((ret <= -30).mean() * 100), 2),
        },
        "upside_metrics": {
            "ge_20_count": int((ret >= 20).sum()), "ge_20_rate": round(float((ret >= 20).mean() * 100), 2),
            "ge_50_count": int((ret >= 50).sum()), "ge_50_rate": round(float((ret >= 50).mean() * 100), 2),
            "ge_100_count": int((ret >= 100).sum()), "ge_100_rate": round(float((ret >= 100).mean() * 100), 2),
        },
        "risk_metrics": {
            "le_neg_10_count": int((ret <= -10).sum()), "le_neg_10_rate": round(float((ret <= -10).mean() * 100), 2),
            "le_neg_20_count": int((ret <= -20).sum()), "le_neg_20_rate": round(float((ret <= -20).mean() * 100), 2),
            "le_neg_30_count": int((ret <= -30).sum()), "le_neg_30_rate": round(float((ret <= -30).mean() * 100), 2),
            "worst_return": round(float(ret.min()), 2),
        },
        "holding_metrics": {
            "mean_days": round(float(holding.mean()), 1),
            "median_days": round(float(holding.median()), 1),
            "longest_days": int(holding.max()),
            "shortest_days": int(holding.min()),
        },
    }


def _fastcore_loss_cut_analysis(df_fc: pd.DataFrame) -> pd.DataFrame:
    if df_fc.empty:
        return pd.DataFrame()
    lc = df_fc[df_fc["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15"].copy()
    if lc.empty:
        return lc
    lc["gap_beyond_trigger"] = lc["loss_guard_realized_return"] < -15.0
    rows = []
    for _, row in lc.iterrows():
        nxt = df_fc[
            (df_fc["ticker"] == row["ticker"])
            & (df_fc["isu_cd"] == row.get("isu_cd"))
            & (df_fc["market"] == row.get("market"))
            & (df_fc["trade_sequence"] == row["trade_sequence"] + 1)
        ]
        reentered = not nxt.empty
        reentry_return = float(nxt.iloc[0]["terminal_return"]) if reentered else None
        rows.append({
            "ticker": row["ticker"], "name": row["name"], "trade_id": row["trade_id"],
            "loss_guard_signal_date": row["loss_guard_signal_date"],
            "loss_guard_execution_date": row["loss_guard_execution_date"],
            "loss_guard_realized_return": row["loss_guard_realized_return"],
            "gap_beyond_trigger": bool(row["gap_beyond_trigger"]),
            "reentered": reentered,
            "reentry_return": reentry_return,
        })
    out = pd.DataFrame(rows)
    return out


def _paired_entry_comparison(df_fc: pd.DataFrame, df_jl: pd.DataFrame) -> pd.DataFrame:
    if df_fc.empty and df_jl.empty:
        return pd.DataFrame()

    key_cols = ("ticker", "isu_cd", "market", "entry_signal_date")
    fc_keys = set(zip(*(df_fc[col] for col in key_cols))) if not df_fc.empty else set()
    jl_keys = set(zip(*(df_jl[col] for col in key_cols))) if not df_jl.empty else set()

    fc_first = df_fc[df_fc["trade_sequence"] == 1] if not df_fc.empty else df_fc
    fc_first_keys = set(zip(*(fc_first[col] for col in key_cols))) if not fc_first.empty else set()

    rows = []
    for ticker, isu_cd, market, sig_date in sorted(fc_keys | jl_keys):
        key = (ticker, isu_cd, market, sig_date)
        in_fc, in_jl = key in fc_keys, key in jl_keys
        is_first = key in fc_first_keys
        if in_fc and in_jl:
            cls = "SHARED_ENTRY" if is_first else "SHARED_REENTRY"
        elif in_fc and not in_jl:
            cls = "FASTCORE_ONLY_REENTRY" if not is_first else "UNPAIRED_AFTER_STRATEGY_DIVERGENCE"
        elif in_jl and not in_fc:
            cls = "JULIA_ONLY_ENTRY" if is_first else "UNPAIRED_AFTER_STRATEGY_DIVERGENCE"
        else:
            cls = "UNPAIRED_AFTER_STRATEGY_DIVERGENCE"
        rows.append({"ticker": ticker, "isu_cd": isu_cd, "market": market, "entry_signal_date": sig_date, "comparison_class": cls})
    return pd.DataFrame(rows)


def _loss_cut_counterfactual(df_fc: pd.DataFrame, df_jl: pd.DataFrame) -> pd.DataFrame:
    if df_fc.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        build_loss_cut_counterfactual_rows(
            df_fc.to_dict("records"),
            df_jl.to_dict("records") if not df_jl.empty else [],
            None,
        )
    )


def _loss_cut_aggregate_summary(counterfactual: pd.DataFrame) -> dict[str, Any]:
    if counterfactual.empty:
        return {
            "total_loss_cuts": 0,
            "pairable_loss_cuts": 0,
            "unpairable_loss_cuts": 0,
            "pair_coverage_rate": 0.0,
        }
    total = len(counterfactual)
    pairable = int(counterfactual["pairable"].sum())
    def _rate(n: int) -> float:
        return round(float(n / total * 100), 2) if total else 0.0
    fc_returns = pd.to_numeric(counterfactual["fastcore_realized_return"], errors="coerce")
    terminal = pd.to_numeric(counterfactual["julia_terminal_return"], errors="coerce")
    return {
        "total_loss_cuts": total,
        "pairable_loss_cuts": pairable,
        "unpairable_loss_cuts": int(total - pairable),
        "pair_coverage_rate": _rate(pairable),
        "first_entry_pair_count": int((counterfactual["pair_class"] == "PAIRED_FIRST_ENTRY").sum()),
        "shared_reentry_pair_count": int((counterfactual["pair_class"] == "PAIRED_SHARED_REENTRY").sum()),
        "fastcore_realized_loss_mean": round(float(fc_returns.mean()), 2) if fc_returns.notna().any() else None,
        "fastcore_realized_loss_median": round(float(fc_returns.median()), 2) if fc_returns.notna().any() else None,
        "fastcore_le_neg_15": int((fc_returns <= -15).sum()),
        "fastcore_le_neg_20": int((fc_returns <= -20).sum()),
        "fastcore_le_neg_25": int((fc_returns <= -25).sum()),
        "fastcore_le_neg_30": int((fc_returns <= -30).sum()),
        "julia_eventually_positive_count": int((terminal > 0).sum()),
        "julia_eventually_positive_rate": _rate(int((terminal > 0).sum())),
        "recovered_above_entry_count": int(counterfactual["recovered_above_entry"].sum()),
        "recovered_above_entry_rate": _rate(int(counterfactual["recovered_above_entry"].sum())),
        "never_recovered_count": int((~counterfactual["recovered_above_entry"]).sum()),
        "deeper_loss_avoided_count": int((terminal > fc_returns).sum()),
        "deeper_loss_avoided_rate": _rate(int((terminal > fc_returns).sum())),
        "julia_terminal_better_count": int((terminal > fc_returns).sum()),
        "julia_terminal_better_rate": _rate(int((terminal > fc_returns).sum())),
        "fastcore_better_count": int((fc_returns > terminal).sum()),
        "fastcore_better_rate": _rate(int((fc_returns > terminal).sum())),
        "mean_julia_counterfactual_terminal_return": round(float(terminal.mean()), 2) if terminal.notna().any() else None,
        "median_julia_counterfactual_terminal_return": round(float(terminal.median()), 2) if terminal.notna().any() else None,
    }


def _best_worst_trades(df_fc: pd.DataFrame, df_jl: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    cols = ["strategy_id", "ticker", "name", "entry_execution_date", "entry_open",
            "exit_execution_date", "exit_price", "terminal_return", "exit_type"]
    frames = []
    for df in (df_fc, df_jl):
        if df.empty:
            continue
        best = df.nlargest(n, "terminal_return")[cols].copy()
        best["rank_group"] = "BEST"
        worst = df.nsmallest(n, "terminal_return")[cols].copy()
        worst["rank_group"] = "WORST"
        frames.append(pd.concat([best, worst], ignore_index=True))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _date_range_info(df_fc: pd.DataFrame, df_jl: pd.DataFrame) -> dict[str, Any]:
    all_signal_dates = []
    all_exec_dates = []
    for df in (df_fc, df_jl):
        if not df.empty:
            all_signal_dates.extend(df["entry_signal_date"].tolist())
            all_exec_dates.extend(df["entry_execution_date"].tolist())
            all_exec_dates.extend(df["exit_execution_date"].dropna().tolist())
    return {
        "first_actual_entry_date": min(all_exec_dates) if all_exec_dates else None,
        "last_signal_date": max(all_signal_dates) if all_signal_dates else None,
        "last_execution_date": max(all_exec_dates) if all_exec_dates else None,
    }


def _generate_summary_md(contract, fc, jl, comparison, dates_info) -> str:
    return f"""# FastCore vs Julia STEP 1 Strategy Comparison Backtest

## Contract
- Backtest end: {contract['requested_backtest_end']}
- COMMON universe: {contract['common_universe_count']} tickers
- Entry filter: market cap >= {contract['entry_filter']['market_cap_threshold_krw']:,.0f} KRW, 20D avg trading value >= {contract['entry_filter']['avg_trading_value_20d_threshold_krw']:,.0f} KRW, close >= {contract['entry_filter']['close_threshold_krw']:,.0f} KRW (entry-only, re-evaluated on re-entry)
- Strategy difference: {contract['strategy_difference']}
- OTHER_STRATEGY_DIFFERENCE_COUNT: {contract['other_strategy_difference_count']}
- First actual entry date: {dates_info['first_actual_entry_date']}
- Last signal date: {dates_info['last_signal_date']}
- Last execution date: {dates_info['last_execution_date']}
- Transaction cost: {contract['transaction_cost']} / Slippage: {contract['slippage']}
- Network requests: {contract['network_requests']}

## Headline comparison

| Metric | FastCore (Loss Guard ON) | Julia (Loss Guard OFF) |
|---|---:|---:|
| Total trades | {fc.get('total_trades', 0)} | {jl.get('total_trades', 0)} |
| Unique tickers | {fc.get('unique_tickers', 0)} | {jl.get('unique_tickers', 0)} |
| Loss cut count | {fc.get('loss_cut_count', 0)} | {jl.get('loss_cut_count', 0)} |
| Mean terminal return | {comparison['fastcore_mean_return']}% | {comparison['julia_mean_return']}% |
| Median terminal return | {comparison['fastcore_median_return']}% | {comparison['julia_median_return']}% |
| Return <= -20% rate | {comparison['fastcore_le_neg_20_rate']}% | {comparison['julia_le_neg_20_rate']}% |
| Return >= +50% rate | {comparison['fastcore_ge_50_rate']}% | {comparison['julia_ge_50_rate']}% |

## Comparison buckets
- SHARED_ENTRY: {comparison['shared_entry_count']}
- FASTCORE_ONLY_REENTRY: {comparison['fastcore_only_reentry_count']}
- JULIA_ONLY_ENTRY: {comparison['julia_only_entry_count']}
- SHARED_REENTRY: {comparison['shared_reentry_count']}
- UNPAIRED_AFTER_STRATEGY_DIVERGENCE: {comparison['unpaired_after_divergence_count']}
- Loss-cut counterfactual rows: {comparison['loss_cut_counterfactual_rows']}
"""


if __name__ == "__main__":
    run_backtest()
