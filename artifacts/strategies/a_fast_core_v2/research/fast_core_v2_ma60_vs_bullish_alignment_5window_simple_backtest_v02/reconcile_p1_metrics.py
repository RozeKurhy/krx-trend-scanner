#!/usr/bin/env python3
"""Reconcile P1 PROGRESSED counts from saved trade ledgers only; never runs backtests."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CUTOFF = "2026-08-31"
STRATEGIES = {
    "CONTROL": "p1_control_trades.csv",
    "MA60": "p1_ma60_trades.csv",
    "ALIGNMENT": "p1_alignment_trades.csv",
}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    metrics_path = ROOT / "p1_strategy_metrics.csv"
    metrics = load_csv(metrics_path)
    rows_by_strategy = {name: load_csv(ROOT / filename) for name, filename in STRATEGIES.items()}
    metrics_by_strategy = {row["strategy"]: row for row in metrics}
    if set(metrics_by_strategy) != set(STRATEGIES):
        raise ValueError("P1 strategy set mismatch")

    extra_fields = [
        "progressed_ledger_field_nonempty_count",
        "progressed_field_date_after_exit_count",
        "progressed_scope",
    ]
    fieldnames = list(metrics[0])
    fieldnames.extend(name for name in extra_fields if name not in fieldnames)

    for strategy, trades in rows_by_strategy.items():
        metric = metrics_by_strategy[strategy]
        if len(trades) != int(metric["trade_count"]):
            raise ValueError(f"{strategy}: trade count mismatch")
        raw_nonempty = 0
        progressed_while_open = 0
        for trade in trades:
            event_date = trade["first_progressed_effective_trading_date"]
            if not event_date:
                continue
            raw_nonempty += 1
            if trade["trade_status"] == "REALIZED":
                end_date = trade["exit_signal_date"]
            elif trade["trade_status"] == "OPEN_AT_CUTOFF":
                end_date = CUTOFF
            else:
                raise ValueError(f"{strategy}: unexpected status {trade['trade_status']}")
            if trade["entry_execution_date"] <= event_date <= end_date:
                progressed_while_open += 1
        metric["progressed_ledger_field_nonempty_count"] = str(raw_nonempty)
        metric["progressed_field_date_after_exit_count"] = str(raw_nonempty - progressed_while_open)
        metric["progressed_count"] = str(progressed_while_open)
        metric["progressed_rate_pct"] = f"{progressed_while_open / len(trades) * 100:.12f}"
        metric["progressed_scope"] = (
            "entry_execution_date <= event <= exit_signal_date; "
            "OPEN_AT_CUTOFF uses 2026-08-31"
        )

    output = ROOT / "p1_strategy_metrics_reconciled.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(metrics)


if __name__ == "__main__":
    main()
