#!/usr/bin/env python3
"""Compare fresh fixed-horizon replays with each other and prior ledgers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
OLD = ROOT / "artifacts/strategies/a_fast_core_v2/research"
FIXED = OUT
WINDOWS = {
    "P3-1": {
        "old": OLD / "fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01",
        "fixed": FIXED / "p3_1",
        "prefix": "p3_1",
    },
    "P3-2": {
        "old": OLD / "fast_core_v2_p3_2_ma60_vs_bullish_alignment_simple_backtest_v01",
        "fixed": FIXED / "p3_2",
        "prefix": "p3_2",
    },
    "P2-2": {
        "old": OLD / "fast_core_v2_p2_2_ma60_vs_bullish_alignment_simple_backtest_v01",
        "fixed": FIXED / "p2_2",
        "prefix": "p2_2",
    },
}
STRATEGIES = ("CONTROL", "MA60", "ALIGNMENT")
REPRO_TICKERS = ("039200", "086790", "122870", "267270")
ENTRY_KEY = ("ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date", "entry_open")
EXIT_FIELDS = ("exit_type", "exit_signal_date", "exit_execution_date", "exit_price")
LIFECYCLE_FIELDS = (
    "lifecycle_class",
    "first_progressed_date",
    "first_progressed_effective_trading_date",
    "loss_guard_triggered",
    "loss_guard_signal_date",
)


def load_ledger(directory: Path, prefix: str, strategy: str) -> pd.DataFrame:
    path = directory / f"{prefix}_{strategy.lower()}_trades.csv"
    frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str, "market": str})
    for column in ("ticker", "isu_cd", "market"):
        if column in frame:
            frame[column] = frame[column].fillna("").astype(str)
    frame["ticker"] = frame["ticker"].str.zfill(6)
    frame["isu_cd"] = frame["isu_cd"].str.strip().str.upper()
    frame["market"] = frame["market"].str.strip().str.upper()
    frame["entry_open"] = pd.to_numeric(frame["entry_open"], errors="coerce")
    return frame


def value_equal(left: Any, right: Any, numeric: bool = False) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    if numeric:
        try:
            return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return str(left) == str(right)


def entry_key(row: pd.Series) -> tuple[Any, ...]:
    return tuple(
        round(float(row[name]), 8) if name == "entry_open" and pd.notna(row[name]) else row[name]
        for name in ENTRY_KEY
    )


def compare_prefix(short: pd.DataFrame, long: pd.DataFrame) -> dict[str, Any]:
    short_realized = short[short["trade_status"].astype(str).eq("REALIZED")]
    short_open = short[short["trade_status"].astype(str).eq("OPEN_AT_CUTOFF")]
    long_by_key: dict[tuple[Any, ...], pd.Series] = {}
    duplicate_long = 0
    for _, row in long.iterrows():
        key = entry_key(row)
        if key in long_by_key:
            duplicate_long += 1
        long_by_key[key] = row

    missing = 0
    exit_mismatch = 0
    return_mismatch = 0
    lifecycle_mismatch = 0
    status_mismatch = 0
    for _, row in short_realized.iterrows():
        match = long_by_key.get(entry_key(row))
        if match is None:
            missing += 1
            continue
        changed_exit = any(
            not value_equal(row[field], match[field], numeric=field == "exit_price")
            for field in EXIT_FIELDS
        )
        changed_lifecycle = any(
            not value_equal(row[field], match[field], numeric=field == "loss_guard_triggered")
            for field in LIFECYCLE_FIELDS
        )
        if changed_exit:
            exit_mismatch += 1
        if not value_equal(row.get("net_realized_return_pct"), match.get("net_realized_return_pct"), numeric=True):
            return_mismatch += 1
        if changed_lifecycle:
            lifecycle_mismatch += 1
        if str(match.get("trade_status")) != "REALIZED":
            status_mismatch += 1

    passed = not any((missing, duplicate_long, exit_mismatch, return_mismatch, lifecycle_mismatch, status_mismatch))
    return {
        "short_realized_count": int(len(short_realized)),
        "short_open_at_cutoff_count": int(len(short_open)),
        "long_trade_count": int(len(long)),
        "missing_in_long_count": missing,
        "duplicate_long_entry_key_count": duplicate_long,
        "exit_mismatch_count": exit_mismatch,
        "net_realized_return_mismatch_count": return_mismatch,
        "lifecycle_event_mismatch_count": lifecycle_mismatch,
        "status_mismatch_count": status_mismatch,
        "prefix_invariance_pass": passed,
    }


def compare_loss_guard(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, Any]:
    old_lg = old[old["exit_type"].astype(str).eq("LOSS_GUARD_CLOSE_LE_NEG_15")]
    new_lg = new[new["exit_type"].astype(str).eq("LOSS_GUARD_CLOSE_LE_NEG_15")]
    result = compare_prefix(
        old_lg.assign(trade_status="REALIZED"),
        new_lg.assign(trade_status="REALIZED"),
    )
    return {
        "old_loss_guard_trade_count": int(len(old_lg)),
        "new_loss_guard_trade_count": int(len(new_lg)),
        "missing_loss_guard_trade_count": result["missing_in_long_count"],
        "exit_mismatch_count": result["exit_mismatch_count"],
        "net_realized_return_mismatch_count": result["net_realized_return_mismatch_count"],
        "loss_guard_exit_return_stable": (
            result["missing_in_long_count"] == 0
            and result["exit_mismatch_count"] == 0
            and result["net_realized_return_mismatch_count"] == 0
        ),
    }


def case_rows(directory: Path, prefix: str, version: str, window: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        frame = load_ledger(directory, prefix, strategy)
        for ticker in REPRO_TICKERS:
            ticker_rows = frame[frame["ticker"].eq(ticker)]
            if ticker_rows.empty:
                rows.append({"window": window, "version": version, "strategy": strategy, "ticker": ticker, "trade_status": "NO_TRADE"})
                continue
            for _, trade in ticker_rows.sort_values("trade_sequence").iterrows():
                rows.append({
                    "window": window,
                    "version": version,
                    "strategy": strategy,
                    "ticker": ticker,
                    "trade_sequence": int(trade["trade_sequence"]),
                    "entry_signal_date": trade["entry_signal_date"],
                    "entry_execution_date": trade["entry_execution_date"],
                    "entry_open": trade["entry_open"],
                    "lifecycle_class": trade.get("lifecycle_class"),
                    "first_progressed_date": trade.get("first_progressed_date"),
                    "exit_type": trade.get("exit_type"),
                    "exit_signal_date": trade.get("exit_signal_date"),
                    "exit_execution_date": trade.get("exit_execution_date"),
                    "exit_price": trade.get("exit_price"),
                    "net_realized_return_pct": trade.get("net_realized_return_pct"),
                    "trade_status": trade.get("trade_status"),
                })
    return rows


def p2_2_change_rows(old: pd.DataFrame, new: pd.DataFrame, strategy: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return row-level realized changes and newly replayed entries for P2-2."""
    new_by_key = {entry_key(row): row for _, row in new.iterrows()}
    old_keys = {entry_key(row) for _, row in old.iterrows()}
    changed_rows: list[dict[str, Any]] = []
    additional_rows: list[dict[str, Any]] = []

    for _, row in old[old["trade_status"].astype(str).eq("REALIZED")].iterrows():
        match = new_by_key.get(entry_key(row))
        if match is None:
            continue
        changed_fields = [
            field for field in (*EXIT_FIELDS, "net_realized_return_pct", *LIFECYCLE_FIELDS)
            if not value_equal(
                row.get(field),
                match.get(field),
                numeric=field in {"exit_price", "net_realized_return_pct", "loss_guard_triggered"},
            )
        ]
        if not changed_fields:
            continue
        changed_rows.append({
            "strategy": strategy,
            "ticker": row.get("ticker"),
            "isu_cd": row.get("isu_cd"),
            "market": row.get("market"),
            "entry_signal_date": row.get("entry_signal_date"),
            "entry_execution_date": row.get("entry_execution_date"),
            "entry_open": row.get("entry_open"),
            "old_lifecycle_class": row.get("lifecycle_class"),
            "new_lifecycle_class": match.get("lifecycle_class"),
            "old_first_progressed_date": row.get("first_progressed_date"),
            "new_first_progressed_date": match.get("first_progressed_date"),
            "old_exit_type": row.get("exit_type"),
            "new_exit_type": match.get("exit_type"),
            "old_exit_signal_date": row.get("exit_signal_date"),
            "new_exit_signal_date": match.get("exit_signal_date"),
            "old_exit_execution_date": row.get("exit_execution_date"),
            "new_exit_execution_date": match.get("exit_execution_date"),
            "old_exit_price": row.get("exit_price"),
            "new_exit_price": match.get("exit_price"),
            "old_net_realized_return_pct": row.get("net_realized_return_pct"),
            "new_net_realized_return_pct": match.get("net_realized_return_pct"),
            "changed_fields": ";".join(changed_fields),
        })

    for _, row in new.iterrows():
        if entry_key(row) in old_keys:
            continue
        additional_rows.append({
            "strategy": strategy,
            "ticker": row.get("ticker"),
            "isu_cd": row.get("isu_cd"),
            "market": row.get("market"),
            "entry_signal_date": row.get("entry_signal_date"),
            "entry_execution_date": row.get("entry_execution_date"),
            "entry_open": row.get("entry_open"),
            "trade_sequence": row.get("trade_sequence"),
            "previous_exit_type": row.get("previous_exit_type"),
            "trade_status": row.get("trade_status"),
            "exit_type": row.get("exit_type"),
            "exit_signal_date": row.get("exit_signal_date"),
            "net_realized_return_pct": row.get("net_realized_return_pct"),
        })

    return changed_rows, additional_rows


def main() -> int:
    prefix_rows: list[dict[str, Any]] = []
    loss_rows: list[dict[str, Any]] = []
    reproduction_rows: list[dict[str, Any]] = []
    p2_2_impact: list[dict[str, Any]] = []
    p2_2_changed_trades: list[dict[str, Any]] = []
    p2_2_additional_entries: list[dict[str, Any]] = []

    for window in ("P3-1", "P3-2", "P2-2"):
        config = WINDOWS[window]
        for strategy in STRATEGIES:
            old = load_ledger(config["old"], config["prefix"], strategy)
            new = load_ledger(config["fixed"], config["prefix"], strategy)
            loss = compare_loss_guard(old, new)
            loss_rows.append({"window": window, "strategy": strategy, **loss})
            if window == "P2-2":
                old_realized_comparison = compare_prefix(
                    old,
                    new,
                )
                p2_2_impact.append({
                    "window": window,
                    "strategy": strategy,
                    "old_trade_count": int(len(old)),
                    "new_trade_count": int(len(new)),
                    "trade_count_delta": int(len(new) - len(old)),
                    "old_realized_count": int(old["trade_status"].astype(str).eq("REALIZED").sum()),
                    "new_realized_count": int(new["trade_status"].astype(str).eq("REALIZED").sum()),
                    "old_realized_missing_in_new_count": old_realized_comparison["missing_in_long_count"],
                    "old_realized_exit_mismatch_count": old_realized_comparison["exit_mismatch_count"],
                    "old_realized_return_mismatch_count": old_realized_comparison["net_realized_return_mismatch_count"],
                    "loss_guard_exit_return_stable": loss["loss_guard_exit_return_stable"],
                })
                changed, additional = p2_2_change_rows(old, new, strategy)
                p2_2_changed_trades.extend(changed)
                p2_2_additional_entries.extend(additional)
        reproduction_rows.extend(case_rows(config["old"], config["prefix"], "PRE_FIX", window))
        reproduction_rows.extend(case_rows(config["fixed"], config["prefix"], "FIXED", window))

    for strategy in STRATEGIES:
        short = load_ledger(WINDOWS["P3-1"]["fixed"], "p3_1", strategy)
        long = load_ledger(WINDOWS["P3-2"]["fixed"], "p3_2", strategy)
        prefix_rows.append({"strategy": strategy, **compare_prefix(short, long)})

    control_long = load_ledger(WINDOWS["P3-2"]["fixed"], "p3_2", "CONTROL")
    reentry = control_long[
        control_long["ticker"].eq("267270")
        & control_long["entry_signal_date"].astype(str).eq("2025-01-24")
    ]
    reentry_present = not reentry.empty

    prefix_frame = pd.DataFrame(prefix_rows)
    loss_frame = pd.DataFrame(loss_rows)
    cases_frame = pd.DataFrame(reproduction_rows)
    impact_frame = pd.DataFrame(p2_2_impact)
    changed_frame = pd.DataFrame(p2_2_changed_trades)
    additional_frame = pd.DataFrame(p2_2_additional_entries)
    prefix_frame.to_csv(OUT / "prefix_invariance_by_strategy.csv", index=False, lineterminator="\n")
    loss_frame.to_csv(OUT / "loss_guard_stability.csv", index=False, lineterminator="\n")
    cases_frame.to_csv(OUT / "reproduction_cases.csv", index=False, lineterminator="\n")
    impact_frame.to_csv(OUT / "p2_2_impact_comparison.csv", index=False, lineterminator="\n")
    changed_frame.to_csv(OUT / "p2_2_changed_realized_trades.csv", index=False, lineterminator="\n")
    additional_frame.to_csv(OUT / "p2_2_additional_entries.csv", index=False, lineterminator="\n")

    prefix_pass = bool(prefix_frame["prefix_invariance_pass"].all())
    loss_guard_pass = bool(loss_frame["loss_guard_exit_return_stable"].all())
    p2_2_old_realized_present = bool((impact_frame["old_realized_missing_in_new_count"] == 0).all())
    replay_status = {
        window: json.loads((WINDOWS[window]["fixed"] / f"{WINDOWS[window]['prefix']}_execution_audit.json").read_text(encoding="utf-8")).get("status")
        for window in ("P3-1", "P3-2", "P2-2")
    }
    all_replays_pass = all(status == "PASS" for status in replay_status.values())
    exit_or_return_fields = {
        "exit_type", "exit_signal_date", "exit_execution_date", "exit_price", "net_realized_return_pct"
    }
    p2_2_exit_return_mismatch_rows = int(
        changed_frame["changed_fields"].fillna("").map(
            lambda value: any(field in set(value.split(";")) for field in exit_or_return_fields)
        ).sum()
    )
    p2_2_lifecycle_changed_rows = int(
        changed_frame["changed_fields"].fillna("").map(
            lambda value: any(field in set(value.split(";")) for field in LIFECYCLE_FIELDS)
        ).sum()
    )
    summary = {
        "prefix_invariance_by_strategy": prefix_rows,
        "all_prefix_invariance_pass": prefix_pass,
        "loss_guard_stability_by_window_strategy": loss_rows,
        "all_loss_guard_exit_return_stable": loss_guard_pass,
        "replay_status_by_window": replay_status,
        "all_replays_pass": all_replays_pass,
        "p2_2_was_replayed": True,
        "p2_2_impact_comparison": p2_2_impact,
        "p2_2_old_realized_entries_all_present": p2_2_old_realized_present,
        "p2_2_realized_exit_or_return_mismatch_rows": p2_2_exit_return_mismatch_rows,
        "p2_2_realized_lifecycle_field_change_rows": p2_2_lifecycle_changed_rows,
        "p2_2_additional_entry_count": int(len(p2_2_additional_entries)),
        "267270_2025_01_24_control_reentry_in_fixed_p3_2": reentry_present,
        "final_gate": "PASS" if (
            prefix_pass and loss_guard_pass and p2_2_old_realized_present
            and all_replays_pass and reentry_present
        ) else "CHECK_REQUIRED",
    }
    summary["final_token"] = (
        "FAST_CORE_V2_LIFECYCLE_PREFIX_INVARIANCE_FIX_V01_PASS"
        if summary["final_gate"] == "PASS"
        else "FAST_CORE_V2_LIFECYCLE_PREFIX_INVARIANCE_FIX_V01_CHECK_REQUIRED"
    )
    (OUT / "prefix_invariance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["final_gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
