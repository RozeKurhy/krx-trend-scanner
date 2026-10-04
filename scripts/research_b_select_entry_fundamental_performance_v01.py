#!/usr/bin/env python3
"""Descriptive B Select Core V1 trade performance by entry-date PIT status.

This script reads the completed production status snapshot, resolves the
fundamental state through the existing PIT authority at each trade's exact
entry_signal_date, and writes research-only tables. It does not run a
backtest, call a network service, write the PIT ledger, or modify production
trade history.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.strategies.b_select_core_fundamental_status import (  # noqa: E402
    EVALUATOR,
    FUNDAMENTAL_STATUSES,
    status_key,
    resolve_statuses,
)


STRATEGY_ID = "PATTERN_B_SELECT_CORE_V01"
SOURCE_RELATIVE = Path("artifacts/strategies/b_select_core_v1/production/20261003/status.json")
MONITOR_RELATIVE = Path("web/data/strategy-monitor.json")
CALENDAR_RELATIVE = Path("data/market/rolling_authority/merged_trading_calendar.json")
OUTPUT_RELATIVE = Path(
    "artifacts/strategies/b_select_core_v1/research/entry_fundamental_performance_v01"
)
RETURN_BANDS = (
    ("le_neg30", lambda value: value <= -30),
    ("neg30_to_neg15", lambda value: -30 < value <= -15),
    ("neg15_to_zero", lambda value: -15 < value <= 0),
    ("zero_to_20", lambda value: 0 < value <= 20),
    ("20_to_50", lambda value: 20 < value <= 50),
    ("50_to_100", lambda value: 50 < value < 100),
    ("ge_100", lambda value: value >= 100),
)
UP_TAILS = (10, 20, 30, 50, 100)
DOWN_TAILS = (10, 15, 20, 30, 40)
OPEN_DOWN_TAILS = (10, 15, 20, 30)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def normalize_compact_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def safe_float(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return number


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def sample_band(count: int) -> str:
    if count < 20:
        return "VERY_SMALL"
    if count < 50:
        return "LIMITED"
    return "BASIC_COMPARISON"


def trade_identity(item: Mapping[str, Any], trade: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(item.get("ticker") or "").strip().zfill(6),
        str(item.get("isu_cd") or "").strip().upper(),
        int(trade["trade_sequence"]),
        str(trade["entry_execution_date"])[:10],
    )


def monitor_identity(trade: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(trade.get("ticker") or "").strip().zfill(6),
        int(trade["trade_sequence"]),
        str(trade["entry_execution_date"])[:10],
    )


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def closed_group_metrics(status: str, rows: list[dict[str, Any]], total_closed: int) -> dict[str, Any]:
    returns = [row["return_pct"] for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    flats = [value for value in returns if value == 0]
    holding_days = [float(row["holding_calendar_days"]) for row in rows]
    holding_sessions = [float(row["holding_trading_sessions"]) for row in rows]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    mean_win = _mean(wins)
    mean_loss = _mean(losses)
    bands = {
        f"return_band_{name}_count": sum(predicate(value) for value in returns)
        for name, predicate in RETURN_BANDS
    }
    result: dict[str, Any] = {
        "fundamental_status": status,
        "closed_trade_count": len(rows),
        "closed_trade_share_pct": (len(rows) / total_closed * 100) if total_closed else None,
        "sample_interpretation": sample_band(len(rows)),
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate_pct": (len(wins) / len(rows) * 100) if rows else None,
        "mean_return_pct": _mean(returns),
        "median_return_pct": _median(returns),
        "min_return_pct": min(returns) if returns else None,
        "max_return_pct": max(returns) if returns else None,
        "mean_win_return_pct": mean_win,
        "mean_loss_return_pct": mean_loss,
        "payoff_ratio": (mean_win / abs(mean_loss)) if mean_win is not None and mean_loss else None,
        "payoff_ratio_note": "" if mean_win is not None and mean_loss else "UNDEFINED_MISSING_WIN_OR_LOSS_SIDE",
        "trade_expectancy_pct": _mean(returns),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "profit_factor_note": "" if gross_loss else "UNDEFINED_NO_LOSSES",
        "gross_profit_pct_sum": gross_profit,
        "gross_loss_pct_abs_sum": gross_loss,
        "p10_return_pct": percentile(returns, 0.10),
        "p25_return_pct": percentile(returns, 0.25),
        "p50_return_pct": percentile(returns, 0.50),
        "p75_return_pct": percentile(returns, 0.75),
        "p90_return_pct": percentile(returns, 0.90),
        "mean_holding_calendar_days": _mean(holding_days),
        "median_holding_calendar_days": _median(holding_days),
        "min_holding_calendar_days": min(holding_days) if holding_days else None,
        "max_holding_calendar_days": max(holding_days) if holding_days else None,
        "mean_holding_trading_sessions": _mean(holding_sessions),
        "median_holding_trading_sessions": _median(holding_sessions),
    }
    for threshold in UP_TAILS:
        count = sum(value >= threshold for value in returns)
        result[f"ge_{threshold}_pct_count"] = count
        result[f"ge_{threshold}_pct_share"] = (count / len(rows) * 100) if rows else None
    for threshold in DOWN_TAILS:
        count = sum(value <= -threshold for value in returns)
        result[f"le_neg{threshold}_pct_count"] = count
        result[f"le_neg{threshold}_pct_share"] = (count / len(rows) * 100) if rows else None
    result.update(bands)
    return result


def open_group_metrics(status: str, rows: list[dict[str, Any]], total_open: int) -> dict[str, Any]:
    returns = [row["unrealized_return_pct"] for row in rows]
    calendar_days = [float(row["holding_calendar_days"]) for row in rows]
    sessions = [float(row["holding_trading_sessions"]) for row in rows]
    result: dict[str, Any] = {
        "fundamental_status": status,
        "open_trade_count": len(rows),
        "open_trade_share_pct": (len(rows) / total_open * 100) if total_open else None,
        "sample_interpretation": sample_band(len(rows)),
        "valuation_as_of": rows[0]["valuation_as_of"] if rows else "2026-10-02",
        "mean_unrealized_return_pct": _mean(returns),
        "median_unrealized_return_pct": _median(returns),
        "mean_holding_calendar_days": _mean(calendar_days),
        "median_holding_calendar_days": _median(calendar_days),
        "mean_holding_trading_sessions": _mean(sessions),
        "median_holding_trading_sessions": _median(sessions),
    }
    for threshold in UP_TAILS[:4]:
        count = sum(value >= threshold for value in returns)
        result[f"ge_{threshold}_pct_count"] = count
        result[f"ge_{threshold}_pct_share"] = (count / len(rows) * 100) if rows else None
    for threshold in OPEN_DOWN_TAILS:
        count = sum(value <= -threshold for value in returns)
        result[f"le_neg{threshold}_pct_count"] = count
        result[f"le_neg{threshold}_pct_share"] = (count / len(rows) * 100) if rows else None
    return result


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite values cannot be written to the summary")
        return round(value, 10)
    return value


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _metric_csv_fields() -> list[str]:
    fields = [
        "fundamental_status", "closed_trade_count", "closed_trade_share_pct", "sample_interpretation",
        "win_count", "loss_count", "flat_count", "win_rate_pct", "mean_return_pct", "median_return_pct",
        "min_return_pct", "max_return_pct", "mean_win_return_pct", "mean_loss_return_pct", "payoff_ratio",
        "payoff_ratio_note", "trade_expectancy_pct", "profit_factor", "profit_factor_note",
        "gross_profit_pct_sum", "gross_loss_pct_abs_sum", "p10_return_pct", "p25_return_pct", "p50_return_pct",
        "p75_return_pct", "p90_return_pct", "mean_holding_calendar_days", "median_holding_calendar_days",
        "min_holding_calendar_days", "max_holding_calendar_days", "mean_holding_trading_sessions",
        "median_holding_trading_sessions",
    ]
    for threshold in UP_TAILS:
        fields.extend((f"ge_{threshold}_pct_count", f"ge_{threshold}_pct_share"))
    for threshold in DOWN_TAILS:
        fields.extend((f"le_neg{threshold}_pct_count", f"le_neg{threshold}_pct_share"))
    fields.extend(f"return_band_{name}_count" for name, _ in RETURN_BANDS)
    return fields


def _open_csv_fields() -> list[str]:
    fields = [
        "fundamental_status", "open_trade_count", "open_trade_share_pct", "sample_interpretation", "valuation_as_of",
        "mean_unrealized_return_pct", "median_unrealized_return_pct", "mean_holding_calendar_days",
        "median_holding_calendar_days", "mean_holding_trading_sessions", "median_holding_trading_sessions",
    ]
    for threshold in UP_TAILS[:4]:
        fields.extend((f"ge_{threshold}_pct_count", f"ge_{threshold}_pct_share"))
    for threshold in OPEN_DOWN_TAILS:
        fields.extend((f"le_neg{threshold}_pct_count", f"le_neg{threshold}_pct_share"))
    return fields


def analyze(repo_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    output = Path(output_dir).resolve() if output_dir is not None else root / OUTPUT_RELATIVE
    source_path = root / SOURCE_RELATIVE
    monitor_path = root / MONITOR_RELATIVE
    calendar_path = root / CALENDAR_RELATIVE
    if not source_path.is_file() or not monitor_path.is_file() or not calendar_path.is_file():
        missing = [str(path.relative_to(root)) for path in (source_path, monitor_path, calendar_path) if not path.is_file()]
        raise FileNotFoundError(f"required authority file(s) are missing: {missing}")

    source_hash_before = sha256_file(source_path)
    ledger_path = root / "artifacts/strategies/b_select_core_v1/fundamental_status/pit_status_ledger.csv"
    ledger_hash_before = sha256_file(ledger_path) if ledger_path.exists() else None
    production = _read_json(source_path)
    if production.get("status") != "PASS" or production.get("strategy_id") != STRATEGY_ID:
        raise ValueError("production status is not a passing B Select Core V1 snapshot")
    if production.get("requested_as_of") != "2026-10-03":
        raise ValueError("production status does not match the requested 2026-10-03 authority")
    reference_date = str(production.get("reference_market_date") or "")[:10]
    if not reference_date:
        raise ValueError("production snapshot has no reference_market_date")

    calendar_hash = sha256_file(calendar_path)
    calendar_authority = production.get("calendar_authority") or {}
    if calendar_hash != calendar_authority.get("sha256"):
        raise ValueError("calendar content does not match the production snapshot calendar authority")
    calendar = _read_json(calendar_path)
    trading_dates = [str(value)[:10] for value in calendar.get("trading_dates", [])]
    if not trading_dates or trading_dates != sorted(set(trading_dates)):
        raise ValueError("rolling KRX trading calendar dates must be nonempty, sorted and unique")
    if trading_dates[-1] != reference_date or calendar_authority.get("frontier") != reference_date:
        raise ValueError("rolling KRX trading calendar frontier does not match production reference date")
    trading_positions = {day: index for index, day in enumerate(trading_dates)}

    items = production.get("items") or []
    source_trades: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in items:
        for trade in item.get("trade_history") or []:
            source_trades.append((item, trade))
    closed_pairs = [(item, trade) for item, trade in source_trades if trade.get("trade_status") == "REALIZED"]
    open_pairs = [(item, trade) for item, trade in source_trades if trade.get("trade_status") == "OPEN_AT_REFERENCE"]
    unexpected_statuses = sorted({str(trade.get("trade_status")) for _, trade in source_trades}
                                 - {"REALIZED", "OPEN_AT_REFERENCE"})
    if unexpected_statuses:
        raise ValueError(f"unexpected trade statuses: {unexpected_statuses}")

    identities = [trade_identity(item, trade) for item, trade in source_trades]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate production trade identity detected")
    required_closed = (
        "entry_signal_date", "entry_execution_date", "entry_open", "exit_execution_date", "exit_price", "return_pct"
    )
    missing_closed_fields = {
        field: sum(trade.get(field) in (None, "") for _, trade in closed_pairs)
        for field in required_closed
    }
    if any(missing_closed_fields.values()):
        raise ValueError(f"closed production trades have missing required fields: {missing_closed_fields}")
    required_open = ("entry_signal_date", "entry_execution_date", "entry_open")
    missing_open_fields = {
        field: sum(trade.get(field) in (None, "") for _, trade in open_pairs)
        for field in required_open
    }
    if any(missing_open_fields.values()):
        raise ValueError(f"open production trades have missing required fields: {missing_open_fields}")

    keys = [status_key(item.get("ticker"), item.get("isu_cd"), trade["entry_signal_date"])
            for item, trade in source_trades]
    resolved = resolve_statuses(keys, root)
    if set(resolved) != set(keys):
        raise ValueError("PIT resolver did not resolve every entry-date key")
    if any(row.get("evaluator") != EVALUATOR for row in resolved.values()):
        raise ValueError("PIT resolver returned a non-authoritative evaluator")
    if any(row.get("fundamental_status") not in FUNDAMENTAL_STATUSES for row in resolved.values()):
        raise ValueError("PIT resolver returned a status outside the five production categories")

    entry_date_mismatches = sum(key[2] != str(trade["entry_signal_date"])[:10]
                                for (item, trade), key in zip(source_trades, keys))
    if entry_date_mismatches:
        raise ValueError("entry fundamental status date is not the exact entry_signal_date")
    future_source_dates = 0
    future_first_filing_dates = 0
    missing_status_assignment = 0
    closed_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []

    def attach_status(item: dict[str, Any], trade: dict[str, Any]) -> tuple[tuple[str, str, str], dict[str, str]]:
        nonlocal missing_status_assignment, future_source_dates, future_first_filing_dates
        key = status_key(item.get("ticker"), item.get("isu_cd"), trade["entry_signal_date"])
        status_row = resolved[key]
        if not status_row.get("fundamental_status"):
            missing_status_assignment += 1
        for field, counter_name in (
            ("fundamental_source_date", "source"),
            ("latest_quarter_first_rcept_dt", "first"),
        ):
            value = normalize_compact_date(status_row.get(field))
            if value and value > key[2]:
                if counter_name == "source":
                    future_source_dates += 1
                else:
                    future_first_filing_dates += 1
        return key, status_row

    for item, trade in closed_pairs:
        key, status_row = attach_status(item, trade)
        entry_day = str(trade["entry_execution_date"])[:10]
        exit_day = str(trade["exit_execution_date"])[:10]
        if entry_day not in trading_positions or exit_day not in trading_positions:
            raise ValueError(f"closed trade dates are absent from the authoritative KRX calendar: {entry_day}, {exit_day}")
        holding_sessions = trading_positions[exit_day] - trading_positions[entry_day]
        holding_days = (parse_day(exit_day) - parse_day(entry_day)).days
        if holding_sessions < 0 or holding_days < 0:
            raise ValueError("closed trade exits before entry")
        entry_price = safe_float(trade["entry_open"])
        exit_price = safe_float(trade["exit_price"])
        return_pct = safe_float(trade["return_pct"])
        reconstructed = (exit_price / entry_price - 1) * 100
        if not math.isclose(return_pct, reconstructed, rel_tol=0, abs_tol=1e-8):
            raise ValueError("closed trade return_pct does not match the production entry/exit prices")
        row = {
            "ticker": str(item["ticker"]).zfill(6),
            "name": item.get("name") or "",
            "isu_cd": str(item["isu_cd"]).upper(),
            "trade_sequence": int(trade["trade_sequence"]),
            "entry_signal_date": str(trade["entry_signal_date"])[:10],
            "entry_execution_date": entry_day,
            "entry_price": entry_price,
            "exit_signal_date": str(trade.get("exit_signal_date") or "")[:10],
            "exit_execution_date": exit_day,
            "exit_price": exit_price,
            "entry_fundamental_status": status_row["fundamental_status"],
            "fundamental_status_date": key[2],
            "fundamental_source_date": status_row.get("fundamental_source_date") or "",
            "latest_quarter_first_rcept_dt": status_row.get("latest_quarter_first_rcept_dt") or "",
            "fundamental_evaluator": status_row["evaluator"],
            "fundamental_retryable": status_row.get("retryable") == "true",
            "return_pct": return_pct,
            "holding_calendar_days": holding_days,
            "holding_trading_sessions": holding_sessions,
            "exit_reason": trade.get("exit_reason") or "",
        }
        closed_rows.append(row)

    open_mark_mismatches = 0
    open_price_asof_mismatches = 0
    for item, trade in open_pairs:
        key, status_row = attach_status(item, trade)
        entry_day = str(trade["entry_execution_date"])[:10]
        latest_close = item.get("latest_close")
        latest_close_as_of = str(item.get("latest_close_as_of") or "")[:10]
        if latest_close in (None, "") or latest_close_as_of != reference_date:
            open_price_asof_mismatches += 1
            raise ValueError("open position lacks a current production mark at the reference market date")
        if entry_day not in trading_positions or reference_date not in trading_positions:
            raise ValueError("open trade dates are absent from the authoritative KRX calendar")
        entry_price = safe_float(trade["entry_open"])
        mark_price = safe_float(latest_close)
        unrealized_return = (mark_price / entry_price - 1) * 100
        stored_return = trade.get("return_pct")
        if stored_return not in (None, "") and not math.isclose(
            safe_float(stored_return), unrealized_return, rel_tol=0, abs_tol=1e-8
        ):
            open_mark_mismatches += 1
        holding_days = (parse_day(reference_date) - parse_day(entry_day)).days
        holding_sessions = trading_positions[reference_date] - trading_positions[entry_day]
        if holding_sessions < 0 or holding_days < 0:
            raise ValueError("open trade entry is after the reference date")
        row = {
            "ticker": str(item["ticker"]).zfill(6),
            "name": item.get("name") or "",
            "isu_cd": str(item["isu_cd"]).upper(),
            "trade_sequence": int(trade["trade_sequence"]),
            "entry_signal_date": str(trade["entry_signal_date"])[:10],
            "entry_execution_date": entry_day,
            "entry_fundamental_status": status_row["fundamental_status"],
            "fundamental_status_date": key[2],
            "entry_price": entry_price,
            "valuation_as_of": reference_date,
            "latest_close": mark_price,
            "unrealized_return_pct": unrealized_return,
            "production_open_return_pct": safe_float(stored_return) if stored_return not in (None, "") else None,
            "holding_calendar_days": holding_days,
            "holding_trading_sessions": holding_sessions,
            "fundamental_source_date": status_row.get("fundamental_source_date") or "",
            "fundamental_evaluator": status_row["evaluator"],
            "fundamental_retryable": status_row.get("retryable") == "true",
        }
        open_rows.append(row)

    if missing_status_assignment:
        raise ValueError("one or more trades have no fundamental status assignment")
    if future_source_dates or future_first_filing_dates:
        raise ValueError("future-dated fundamental source evidence was found")
    if open_mark_mismatches:
        raise ValueError("open production return_pct does not match the production latest_close mark")

    closed_groups = defaultdict(list)
    open_groups = defaultdict(list)
    for row in closed_rows:
        closed_groups[row["entry_fundamental_status"]].append(row)
    for row in open_rows:
        open_groups[row["entry_fundamental_status"]].append(row)
    closed_metrics = [closed_group_metrics(status, closed_groups[status], len(closed_rows))
                      for status in FUNDAMENTAL_STATUSES]
    open_metrics = [open_group_metrics(status, open_groups[status], len(open_rows))
                    for status in FUNDAMENTAL_STATUSES]

    monitor = _read_json(monitor_path)
    b_monitor = [strategy for strategy in monitor.get("strategies", [])
                 if strategy.get("id") == STRATEGY_ID]
    if len(b_monitor) != 1:
        raise ValueError("Strategy Monitor does not contain exactly one B Select Core V1 strategy")
    monitor_trades = b_monitor[0].get("trade_history") or []
    source_monitor_keys = [(ticker, sequence, entry_date) for ticker, _isu, sequence, entry_date in identities]
    monitor_keys = [monitor_identity(row) for row in monitor_trades]
    if len(monitor_keys) != len(set(monitor_keys)):
        raise ValueError("Strategy Monitor has duplicate B Select trade identities")
    missing_in_monitor = sorted(set(source_monitor_keys) - set(monitor_keys))
    extra_in_monitor = sorted(set(monitor_keys) - set(source_monitor_keys))
    monitor_by_key = {monitor_identity(row): row for row in monitor_trades}
    monitor_status_mismatches = 0
    for row in closed_rows + open_rows:
        key = (row["ticker"], row["trade_sequence"], row["entry_execution_date"])
        monitor_row = monitor_by_key.get(key)
        if monitor_row is None or monitor_row.get("fundamental_status") != row["entry_fundamental_status"]:
            monitor_status_mismatches += 1

    # Year cells below the user's n=20 interpretation threshold are omitted.
    yearly_counts: Counter[tuple[str, int]] = Counter(
        (row["entry_fundamental_status"], parse_day(row["entry_execution_date"]).year) for row in closed_rows
    )
    yearly_rows: list[dict[str, Any]] = []
    for (status, year), n in sorted(yearly_counts.items(), key=lambda pair: (FUNDAMENTAL_STATUSES.index(pair[0][0]), pair[0][1])):
        sample = [row for row in closed_rows
                  if row["entry_fundamental_status"] == status and parse_day(row["entry_execution_date"]).year == year]
        if n >= 20:
            yearly_rows.append({
                "fundamental_status": status,
                "entry_execution_year": year,
                "closed_trade_count": n,
                "win_rate_pct": sum(row["return_pct"] > 0 for row in sample) / n * 100,
                "median_return_pct": _median([row["return_pct"] for row in sample]),
                "sample_interpretation": sample_band(n),
            })
    yearly_small_cells = sum(n < 20 for n in yearly_counts.values())

    exit_groups = defaultdict(list)
    for row in closed_rows:
        if row["exit_reason"]:
            exit_groups[(row["entry_fundamental_status"], row["exit_reason"])].append(row)
    exit_rows = []
    for (status, reason), sample in sorted(exit_groups.items(), key=lambda pair: (FUNDAMENTAL_STATUSES.index(pair[0][0]), pair[0][1])):
        values = [row["return_pct"] for row in sample]
        exit_rows.append({
            "fundamental_status": status,
            "exit_reason": reason,
            "trade_count": len(sample),
            "mean_return_pct": _mean(values),
            "median_return_pct": _median(values),
        })

    category_counts = Counter(row["entry_fundamental_status"] for row in closed_rows + open_rows)
    closed_counts = Counter(row["entry_fundamental_status"] for row in closed_rows)
    open_counts = Counter(row["entry_fundamental_status"] for row in open_rows)
    retryable_counts = Counter(row["entry_fundamental_status"] for row in closed_rows + open_rows if row["fundamental_retryable"])
    source_hash_after = sha256_file(source_path)
    ledger_hash_after = sha256_file(ledger_path) if ledger_path.exists() else None
    history_unchanged = source_hash_before == source_hash_after
    ledger_unchanged = ledger_hash_before == ledger_hash_after

    integrity = {
        "production_status": production.get("status"),
        "source_path": SOURCE_RELATIVE.as_posix(),
        "source_sha256": source_hash_before,
        "requested_as_of": production.get("requested_as_of"),
        "reference_market_date": reference_date,
        "strategy_id": production.get("strategy_id"),
        "total_history_count": len(source_trades),
        "closed_trade_count": len(closed_rows),
        "open_trade_count": len(open_rows),
        "closed_required_field_missing_counts": missing_closed_fields,
        "open_required_field_missing_counts": missing_open_fields,
        "duplicate_trade_identity_count": len(identities) - len(set(identities)),
        "fundamental_status_assignment_missing_count": missing_status_assignment,
        "fundamental_status_counts_total": {status: category_counts.get(status, 0) for status in FUNDAMENTAL_STATUSES},
        "closed_fundamental_status_counts": {status: closed_counts.get(status, 0) for status in FUNDAMENTAL_STATUSES},
        "open_fundamental_status_counts": {status: open_counts.get(status, 0) for status in FUNDAMENTAL_STATUSES},
        "entry_status_date_mismatch_count": entry_date_mismatches,
        "future_fundamental_source_date_count": future_source_dates,
        "future_latest_quarter_first_filing_date_count": future_first_filing_dates,
        "fundamental_reclassification_from_current_values_count": 0,
        "pit_evaluator": EVALUATOR,
        "pit_resolved_key_count": len(resolved),
        "pit_retryable_resolved_key_count": sum(row.get("retryable") == "true" for row in resolved.values()),
        "retryable_key_counts_by_assigned_status": {status: retryable_counts.get(status, 0) for status in FUNDAMENTAL_STATUSES},
        "pit_resolution_mutated_ledger": not ledger_unchanged,
        "production_history_unchanged": history_unchanged,
        "closed_return_reconstruction_mismatch_count": 0,
        "open_return_vs_authority_mark_mismatch_count": open_mark_mismatches,
        "open_valuation_asof_mismatch_count": open_price_asof_mismatches,
        "monitor_trade_count": len(monitor_trades),
        "monitor_identity_basis": ["ticker", "trade_sequence", "entry_execution_date"],
        "monitor_identity_missing_count": len(missing_in_monitor),
        "monitor_identity_extra_count": len(extra_in_monitor),
        "monitor_fundamental_status_mismatch_count": monitor_status_mismatches,
        "calendar_path": CALENDAR_RELATIVE.as_posix(),
        "calendar_sha256": calendar_hash,
        "calendar_authority_sha256_match": calendar_hash == calendar_authority.get("sha256"),
        "calendar_frontier": trading_dates[-1],
        "calendar_session_date_count": len(trading_dates),
        "yearly_status_year_cells_below_n20_omitted": yearly_small_cells,
        "integrity_status": "PASS" if (
            history_unchanged and ledger_unchanged and len(identities) == len(set(identities))
            and not missing_status_assignment and not entry_date_mismatches and not future_source_dates
            and not future_first_filing_dates and not open_mark_mismatches and not open_price_asof_mismatches
            and not missing_in_monitor and not extra_in_monitor and not monitor_status_mismatches
            and calendar_hash == calendar_authority.get("sha256")
        ) else "CHECK_REQUIRED",
    }
    if integrity["integrity_status"] != "PASS":
        raise ValueError(f"integrity checks did not pass: {integrity}")

    total_mean_candidates = [row for row in closed_metrics if row["closed_trade_count"] >= 20]
    mean_high = max(total_mean_candidates, key=lambda row: row["mean_return_pct"])
    mean_low = min(total_mean_candidates, key=lambda row: row["mean_return_pct"])
    win_high = max(total_mean_candidates, key=lambda row: row["win_rate_pct"])
    win_low = min(total_mean_candidates, key=lambda row: row["win_rate_pct"])
    median_high = max(total_mean_candidates, key=lambda row: row["median_return_pct"])
    median_low = min(total_mean_candidates, key=lambda row: row["median_return_pct"])
    notes = [
        (f"n≥20 그룹 중 평균 실현수익률 범위는 {mean_low['fundamental_status']} "
         f"({_fmt(mean_low['mean_return_pct'])}%, n={mean_low['closed_trade_count']})부터 "
         f"{mean_high['fundamental_status']} ({_fmt(mean_high['mean_return_pct'])}%, "
         f"n={mean_high['closed_trade_count']})까지야."),
        (f"n≥20 그룹의 승률 범위는 {win_low['fundamental_status']} "
         f"({_fmt(win_low['win_rate_pct'])}%)부터 {win_high['fundamental_status']} "
         f"({_fmt(win_high['win_rate_pct'])}%)까지야."),
        (f"n≥20 그룹의 중앙 수익률 범위는 {median_low['fundamental_status']} "
         f"({_fmt(median_low['median_return_pct'])}%)부터 {median_high['fundamental_status']} "
         f"({_fmt(median_high['median_return_pct'])}%)까지야."),
        (f"미상 그룹은 closed n={closed_counts.get('미상', 0)}로 표본 기준상 "
         f"{sample_band(closed_counts.get('미상', 0))}에 해당해. 이 그룹의 수치는 참고용으로만 봐야 해."),
        (f"청산 사유는 {len({row['exit_reason'] for row in closed_rows})}종류이며, "
         f"모든 실현 거래에서 사유 누락은 {sum(not row['exit_reason'] for row in closed_rows)}건이야."),
    ]

    output.mkdir(parents=True, exist_ok=True)
    closed_fields = [
        "ticker", "name", "isu_cd", "trade_sequence", "entry_signal_date", "entry_execution_date", "entry_price",
        "exit_signal_date", "exit_execution_date", "exit_price", "entry_fundamental_status",
        "fundamental_status_date", "fundamental_source_date", "latest_quarter_first_rcept_dt", "fundamental_evaluator",
        "fundamental_retryable", "return_pct", "holding_calendar_days", "holding_trading_sessions", "exit_reason",
    ]
    open_fields = [
        "ticker", "name", "isu_cd", "trade_sequence", "entry_signal_date", "entry_execution_date",
        "entry_fundamental_status", "fundamental_status_date", "entry_price", "valuation_as_of", "latest_close",
        "unrealized_return_pct", "production_open_return_pct", "holding_calendar_days", "holding_trading_sessions",
        "fundamental_source_date", "fundamental_evaluator", "fundamental_retryable",
    ]
    _write_csv(output / "closed_trade_metrics_by_fundamental.csv", closed_metrics, _metric_csv_fields())
    _write_csv(output / "closed_trade_detail.csv", closed_rows, closed_fields)
    _write_csv(output / "open_trade_snapshot_by_fundamental.csv", open_metrics, _open_csv_fields())
    _write_csv(output / "open_trade_detail.csv", open_rows, open_fields)
    _write_csv(
        output / "yearly_metrics.csv", yearly_rows,
        ["fundamental_status", "entry_execution_year", "closed_trade_count", "win_rate_pct", "median_return_pct", "sample_interpretation"],
    )
    _write_csv(
        output / "exit_reason_metrics.csv", exit_rows,
        ["fundamental_status", "exit_reason", "trade_count", "mean_return_pct", "median_return_pct"],
    )

    csv_specs = {
        "closed_trade_metrics_by_fundamental.csv": (_metric_csv_fields(), len(FUNDAMENTAL_STATUSES)),
        "closed_trade_detail.csv": (closed_fields, len(closed_rows)),
        "open_trade_snapshot_by_fundamental.csv": (_open_csv_fields(), len(FUNDAMENTAL_STATUSES)),
        "open_trade_detail.csv": (open_fields, len(open_rows)),
        "yearly_metrics.csv": (
            ["fundamental_status", "entry_execution_year", "closed_trade_count", "win_rate_pct", "median_return_pct", "sample_interpretation"],
            len(yearly_rows),
        ),
        "exit_reason_metrics.csv": (
            ["fundamental_status", "exit_reason", "trade_count", "mean_return_pct", "median_return_pct"],
            len(exit_rows),
        ),
    }
    csv_readbacks: dict[str, list[dict[str, str]]] = {}
    for filename, (expected_fields, expected_count) in csv_specs.items():
        with (output / filename).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if reader.fieldnames != expected_fields or len(rows) != expected_count:
                raise ValueError(f"output CSV schema/count check failed: {filename}")
            csv_readbacks[filename] = rows
    expected_status_order = list(FUNDAMENTAL_STATUSES)
    if [row["fundamental_status"] for row in csv_readbacks["closed_trade_metrics_by_fundamental.csv"]] != expected_status_order:
        raise ValueError("closed metric output does not contain the exact five production status categories")
    if [row["fundamental_status"] for row in csv_readbacks["open_trade_snapshot_by_fundamental.csv"]] != expected_status_order:
        raise ValueError("open metric output does not contain the exact five production status categories")
    output_detail_identities = {
        (
            str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper(), int(row["trade_sequence"]),
            str(row["entry_execution_date"])[:10],
        )
        for filename in ("closed_trade_detail.csv", "open_trade_detail.csv")
        for row in csv_readbacks[filename]
    }
    if output_detail_identities != set(identities):
        raise ValueError("closed/open detail output identities do not reconcile to production history")
    if sum(int(row["closed_trade_count"]) for row in csv_readbacks["closed_trade_metrics_by_fundamental.csv"]) != len(closed_rows):
        raise ValueError("closed status group counts do not reconcile to closed detail")
    if sum(int(row["open_trade_count"]) for row in csv_readbacks["open_trade_snapshot_by_fundamental.csv"]) != len(open_rows):
        raise ValueError("open status group counts do not reconcile to open detail")
    integrity["output_schema_status"] = "PASS"
    integrity["output_count_status"] = "PASS"
    integrity["output_detail_identity_reconciliation_status"] = "PASS"
    integrity["output_files_validated"] = sorted(csv_specs)

    comparison_fields = [
        "fundamental_status", "closed_trade_count", "win_rate_pct", "mean_return_pct", "median_return_pct",
        "mean_holding_calendar_days", "mean_holding_trading_sessions", "ge_50_pct_share", "ge_100_pct_share",
        "le_neg15_pct_share", "le_neg30_pct_share", "profit_factor", "sample_interpretation",
    ]
    comparison = [{field: metric.get(field) for field in comparison_fields} for metric in closed_metrics]
    result = {
        "analysis_id": "B_SELECT_CORE_V1_ENTRY_FUNDAMENTAL_PERFORMANCE_ANALYSIS_V01",
        "analysis_as_of": "2026-10-04",
        "strategy_change": False,
        "portfolio_backtest_or_cagr": False,
        "return_unit": "percentage points (e.g. 10 means +10%)",
        "holding_period_convention": {
            "calendar_days": "execution date difference; exit day minus entry day",
            "trading_sessions": "KRX calendar index difference; sessions after entry through exit",
            "calendar_authority": CALENDAR_RELATIVE.as_posix(),
            "calendar_sha256": calendar_hash,
        },
        "closed_return_band_boundaries": [
            "<= -30", "(-30, -15]", "(-15, 0]", "(0, 20]", "(20, 50]", "(50, 100)", ">= 100"
        ],
        "integrity": integrity,
        "closed_metrics_by_fundamental_status": closed_metrics,
        "open_snapshot_by_fundamental_status": open_metrics,
        "key_comparison_table": comparison,
        "exit_reason_metrics": exit_rows,
        "yearly_metrics_n_at_least_20": yearly_rows,
        "yearly_insufficient_cells_omitted": yearly_small_cells,
        "descriptive_observations": notes,
        "limitations": [
            "거래 단위 성과 분포이며 동시 보유 거래를 복리 연결한 포트폴리오 수익률이나 CAGR이 아님.",
            "표본 수가 작을수록 상태 간 수치 차이는 불안정하며, n<20은 매우 작은 표본으로 해석.",
            "미상은 운영 계약상 유효한 상태이며 다른 상태로 재배정하지 않음.",
            "OPEN 평가는 production latest_close의 reference_market_date 기준이며 CLOSED 지표에 합산하지 않음.",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(_json_safe(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    lines = [
        "# B Select Core V1 진입 시점 PIT 펀더멘탈 상태별 거래 성과",
        "",
        f"- 분석 기준: 최신 완료 production snapshot `{SOURCE_RELATIVE.as_posix()}` (요청일 2026-10-03, 시장 기준일 {reference_date})",
        f"- 기준 commit: `{_git_head(root)}`",
        f"- 전략 ID: `{STRATEGY_ID}` / 상태 평가기: `{EVALUATOR}`",
        "- 각 거래의 분류는 `entry_signal_date`에 고정한 PIT resolver 결과야. 현재 재무상태를 과거에 적용하지 않았어.",
        "- 수익률 단위는 퍼센트포인트야. 예를 들어 `10`은 `+10%`를 뜻해.",
        "- 동시 보유 거래를 복리 연결하지 않았고, 아래 수치는 portfolio backtest나 CAGR이 아니야.",
        "",
        "## 모집단 및 상태 표본",
        "",
        f"- 전체 trade history: **{len(source_trades)}** (CLOSED {len(closed_rows)}, OPEN {len(open_rows)})",
        f"- CLOSED 중복 identity: **0**; PIT 상태 배정 누락: **0**; 진입일 불일치: **0**; 미래 공시 증거: **0**.",
        f"- PIT resolver의 retryable 상태: **{integrity['pit_retryable_resolved_key_count']}개 key**가 재평가 후에도 retryable로 남았고 상태는 계약대로 `미상`으로 유지됐어.",
        "- 범주별 표본 수와 전체 CLOSED 비중:",
        "",
        "| 진입 PIT 상태 | CLOSED n | CLOSED 비중 | OPEN n | 해석 표본 구간 |",
        "|---|---:|---:|---:|---|",
    ]
    for status in FUNDAMENTAL_STATUSES:
        metric = next(row for row in closed_metrics if row["fundamental_status"] == status)
        lines.append(
            f"| {status} | {metric['closed_trade_count']} | {_fmt(metric['closed_trade_share_pct'])}% | "
            f"{open_counts.get(status, 0)} | {metric['sample_interpretation']} |"
        )
    lines.extend([
        "",
        "## 핵심 비교",
        "",
        "| 진입 PIT 상태 | n | 승률 | 평균 수익률 | 중앙 수익률 | 평균 보유일 | 평균 보유 세션 | +50% | +100% | -15% 이하 | -30% 이하 | PF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for metric in closed_metrics:
        lines.append(
            f"| {metric['fundamental_status']} | {metric['closed_trade_count']} | {_fmt(metric['win_rate_pct'])}% | "
            f"{_fmt(metric['mean_return_pct'])}% | {_fmt(metric['median_return_pct'])}% | "
            f"{_fmt(metric['mean_holding_calendar_days'])} | {_fmt(metric['mean_holding_trading_sessions'])} | "
            f"{metric['ge_50_pct_count']} ({_fmt(metric['ge_50_pct_share'])}%) | "
            f"{metric['ge_100_pct_count']} ({_fmt(metric['ge_100_pct_share'])}%) | "
            f"{metric['le_neg15_pct_count']} ({_fmt(metric['le_neg15_pct_share'])}%) | "
            f"{metric['le_neg30_pct_count']} ({_fmt(metric['le_neg30_pct_share'])}%) | "
            f"{_fmt(metric['profit_factor']) if metric['profit_factor'] is not None else '정의 불가'} |"
        )
    lines.extend(["", "## 가장 눈에 띄는 차이", ""])
    lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "- 이 비교는 분포와 효과 크기를 기술하는 용도야. 전략 채택·필터 승격을 뜻하지 않아.",
        "",
        "## CLOSED 상세 분포와 보조 지표",
        "",
        "상세 5분위수, 승·패/보합, 손익비, 기대값, profit factor, 수익 구간과 tail count/share는 `closed_trade_metrics_by_fundamental.csv`와 `closed_trade_detail.csv`에 있어.",
        "연도별 표는 상태×연도 표본이 n≥20인 셀만 담았고, 작은 셀은 `INSUFFICIENT_SAMPLE` 원칙으로 뺐어.",
        "Exit reason은 production trade history의 값을 그대로 집계했어.",
        "",
        "## OPEN 보조 현황 (CLOSED와 분리)",
        "",
        f"- 평가 기준일: **{reference_date}**; production `latest_close`를 사용했어.",
        f"- 보유 거래: **{len(open_rows)}**; 현재가 누락 또는 기준일 불일치: **{open_price_asof_mismatches}**; source 기록 수익률과 mark 재계산 불일치: **{open_mark_mismatches}**.",
        "- 상태별 미실현 평균/중앙 수익률, 보유기간과 +10/+20/+30/+50%, -10/-15/-20/-30% 건수·비중은 `open_trade_snapshot_by_fundamental.csv`에 있어.",
        "- 종목별 OPEN snapshot은 `open_trade_detail.csv`에 따로 있어.",
        "",
        "## 무결성 검증",
        "",
        f"- 결과: **{integrity['integrity_status']}**",
        "- 산출 CSV schema/count 및 상세 거래 identity 재대조: **PASS**.",
        f"- source history / Strategy Monitor: 원본 {len(source_trades)}건, monitor {len(monitor_trades)}건; identity 누락 {len(missing_in_monitor)}, 추가 {len(extra_in_monitor)}, 상태 불일치 {monitor_status_mismatches}.",
        f"- PIT entry date: 각 거래 `entry_signal_date`와 resolver status date 일치; 미래 source date {future_source_dates}, 미래 first filing date {future_first_filing_dates}.",
        f"- KRX session authority: `{CALENDAR_RELATIVE.as_posix()}` SHA-256이 production calendar authority와 일치; frontier {trading_dates[-1]}; 해당 달력으로 보유 거래 세션 계산.",
        f"- production history 파일 변경: {not history_unchanged}; PIT ledger 변경: {not ledger_unchanged}; production 코드·전략·웹 데이터 수정: 없음.",
        "- `web/data/strategy-monitor.json`은 count/identity/status parity만 확인했고 거래 원본 authority로 사용하지 않았어.",
        "",
        "## 산출물",
        "",
        f"- `{(output / 'summary.md').relative_to(root).as_posix()}`",
        f"- `{(output / 'summary.json').relative_to(root).as_posix()}`",
        f"- `{(output / 'closed_trade_metrics_by_fundamental.csv').relative_to(root).as_posix()}`",
        f"- `{(output / 'closed_trade_detail.csv').relative_to(root).as_posix()}`",
        f"- `{(output / 'open_trade_snapshot_by_fundamental.csv').relative_to(root).as_posix()}`",
        f"- `{(output / 'open_trade_detail.csv').relative_to(root).as_posix()}`",
        f"- `{(output / 'yearly_metrics.csv').relative_to(root).as_posix()}`",
        f"- `{(output / 'exit_reason_metrics.csv').relative_to(root).as_posix()}`",
        "",
        "이번 작업은 descriptive research이며 전략 규칙이나 production history를 변경하지 않았어.",
    ])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def _git_head(root: Path) -> str:
    import subprocess

    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    result = analyze(args.repo_root, args.output_dir)
    print(json.dumps({
        "integrity_status": result["integrity"]["integrity_status"],
        "total_history_count": result["integrity"]["total_history_count"],
        "closed_trade_count": result["integrity"]["closed_trade_count"],
        "open_trade_count": result["integrity"]["open_trade_count"],
        "output_dir": str(Path(args.output_dir).resolve() if args.output_dir else Path(args.repo_root).resolve() / OUTPUT_RELATIVE),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
