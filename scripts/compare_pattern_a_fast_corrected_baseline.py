#!/usr/bin/env python
"""Deterministic CSV Comparison Utility for Pattern A FAST Strategy Finalization.

Compares:
  - Legacy Authority: artifacts/pattern_a_fast/strategy_finalization_v01_legacy/pattern_a_fast_strategy_finalization_v01_trades.csv (553 trades)
  - Corrected Authority: artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/pattern_a_fast_strategy_finalization_v01_trades.csv (551 trades)

Strict Invariants:
  - Zero strategy recalculation
  - Zero market data loading
  - Direct CSV-to-CSV deterministic comparison
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

LEGACY_CSV = ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01_legacy/pattern_a_fast_strategy_finalization_v01_trades.csv"
CORRECTED_CSV = ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/pattern_a_fast_strategy_finalization_v01_trades.csv"


def compare_baselines(
    legacy_csv_path: Path = LEGACY_CSV,
    corrected_csv_path: Path = CORRECTED_CSV,
) -> dict[str, Any]:
    df_leg = pd.read_csv(legacy_csv_path, dtype={"ticker": str})
    df_leg["ticker"] = df_leg["ticker"].str.zfill(6)

    df_cor = pd.read_csv(corrected_csv_path, dtype={"ticker": str})
    df_cor["ticker"] = df_cor["ticker"].str.zfill(6)

    leg_map = {row["ticker"]: row for _, row in df_leg.iterrows()}
    cor_map = {row["ticker"]: row for _, row in df_cor.iterrows()}

    leg_tickers = set(leg_map.keys())
    cor_tickers = set(cor_map.keys())

    legacy_only_tickers = sorted(list(leg_tickers - cor_tickers))
    corrected_only_tickers = sorted(list(cor_tickers - leg_tickers))
    common_tickers = sorted(list(leg_tickers & cor_tickers))

    # Invariant assertions
    assert len(df_leg) == len(common_tickers) + len(legacy_only_tickers), "Legacy cardinality invariant failed"
    assert len(df_cor) == len(common_tickers) + len(corrected_only_tickers), "Corrected cardinality invariant failed"

    # Shifted entry dates
    shifted_entries = []
    for t in common_tickers:
        l_row = leg_map[t]
        c_row = cor_map[t]
        if l_row["entry_signal_date"] != c_row["entry_signal_date"]:
            shifted_entries.append({
                "ticker": t,
                "name": str(c_row["name"]),
                "legacy_entry_signal_date": str(l_row["entry_signal_date"]),
                "corrected_entry_signal_date": str(c_row["entry_signal_date"]),
                "legacy_entry_execution_date": str(l_row["entry_execution_date"]),
                "corrected_entry_execution_date": str(c_row["entry_execution_date"]),
            })

    # Changed exit types
    changed_exit_types = []
    for t in common_tickers:
        l_row = leg_map[t]
        c_row = cor_map[t]
        if l_row["hold_b_e2_exit_type"] != c_row["hold_b_e2_exit_type"]:
            changed_exit_types.append({
                "ticker": t,
                "name": str(c_row["name"]),
                "legacy_exit_type": str(l_row["hold_b_e2_exit_type"]),
                "corrected_exit_type": str(c_row["hold_b_e2_exit_type"]),
            })

    # Changed loss guard triggers
    changed_loss_guards = []
    for t in common_tickers:
        l_row = leg_map[t]
        c_row = cor_map[t]
        if bool(l_row["loss_guard_triggered"]) != bool(c_row["loss_guard_triggered"]):
            changed_loss_guards.append({
                "ticker": t,
                "name": str(c_row["name"]),
                "legacy_loss_guard_triggered": bool(l_row["loss_guard_triggered"]),
                "corrected_loss_guard_triggered": bool(c_row["loss_guard_triggered"]),
                "legacy_loss_guard_signal_date": str(l_row["loss_guard_signal_date"]),
                "corrected_loss_guard_signal_date": str(c_row["loss_guard_signal_date"]),
            })

    # Changed first progressed dates
    changed_first_prog_dates = []
    for t in common_tickers:
        l_row = leg_map[t]
        c_row = cor_map[t]
        l_d = str(l_row["first_progressed_date"]) if pd.notna(l_row["first_progressed_date"]) else None
        c_d = str(c_row["first_progressed_date"]) if pd.notna(c_row["first_progressed_date"]) else None
        if l_d != c_d:
            changed_first_prog_dates.append({
                "ticker": t,
                "name": str(c_row["name"]),
                "legacy_first_progressed_date": l_d,
                "corrected_first_progressed_date": c_d,
            })

    legacy_only_details = [{"ticker": t, "name": str(leg_map[t]["name"])} for t in legacy_only_tickers]
    corrected_only_details = [{"ticker": t, "name": str(cor_map[t]["name"])} for t in corrected_only_tickers]

    return {
        "legacy_trade_count": len(df_leg),
        "corrected_trade_count": len(df_cor),
        "common_count": len(common_tickers),
        "legacy_only_count": len(legacy_only_tickers),
        "legacy_only_tickers": legacy_only_tickers,
        "legacy_only_details": legacy_only_details,
        "corrected_only_count": len(corrected_only_tickers),
        "corrected_only_tickers": corrected_only_tickers,
        "corrected_only_details": corrected_only_details,
        "shifted_entry_date_count": len(shifted_entries),
        "shifted_entry_date_tickers": [r["ticker"] for r in shifted_entries],
        "shifted_entries": shifted_entries,
        "changed_exit_type_count": len(changed_exit_types),
        "changed_exit_type_tickers": [r["ticker"] for r in changed_exit_types],
        "changed_exit_types": changed_exit_types,
        "changed_loss_guard_count": len(changed_loss_guards),
        "changed_loss_guard_tickers": [r["ticker"] for r in changed_loss_guards],
        "changed_loss_guards": changed_loss_guards,
        "changed_first_progressed_date_count": len(changed_first_prog_dates),
        "changed_first_progressed_date_tickers": [r["ticker"] for r in changed_first_prog_dates],
        "changed_first_progressed_dates": changed_first_prog_dates,
    }


def main() -> None:
    res = compare_baselines()
    print("=" * 80)
    print("DETERMINISTIC CSV BASELINE COMPARISON RESULT")
    print("=" * 80)
    print(f"Legacy Total Trades:    {res['legacy_trade_count']}")
    print(f"Corrected Total Trades: {res['corrected_trade_count']}")
    print(f"Common Trades:          {res['common_count']}")
    print("-" * 80)
    print(f"Legacy Only (Dropped) Count: {res['legacy_only_count']}")
    for d in res["legacy_only_details"]:
        print(f"  - {d['ticker']} ({d['name']})")
    print("-" * 80)
    print(f"Corrected Only (Gained) Count: {res['corrected_only_count']}")
    for d in res["corrected_only_details"]:
        print(f"  - {d['ticker']} ({d['name']})")
    print("-" * 80)
    print(f"Shifted Entry Date Count: {res['shifted_entry_date_count']}")
    for s in res["shifted_entries"]:
        print(f"  - {s['ticker']} ({s['name']}): Signal {s['legacy_entry_signal_date']} -> {s['corrected_entry_signal_date']} | Exec {s['legacy_entry_execution_date']} -> {s['corrected_entry_execution_date']}")
    print("-" * 80)
    print(f"Changed Exit Type Count: {res['changed_exit_type_count']}")
    for c in res["changed_exit_types"]:
        print(f"  - {c['ticker']} ({c['name']}): {c['legacy_exit_type']} -> {c['corrected_exit_type']}")
    print("-" * 80)
    print(f"Changed Loss Guard Trigger Count: {res['changed_loss_guard_count']}")
    for g in res["changed_loss_guards"]:
        print(f"  - {g['ticker']} ({g['name']}): {g['legacy_loss_guard_triggered']} -> {g['corrected_loss_guard_triggered']}")
    print("-" * 80)
    print(f"Changed First Progressed Date Count: {res['changed_first_progressed_date_count']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
