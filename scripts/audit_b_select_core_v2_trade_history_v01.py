#!/usr/bin/env python3
"""Full exact-identity lifecycle audit for the frozen 2026-10-03 B Select V2 history."""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

STATUS_PATH = ROOT / "artifacts/strategies/b_select_core_v2/production/20261003/status.json"
MONITOR_PATH = ROOT / "web/data/strategy-monitor.json"
INDEX_PATH = ROOT / "web/data/identity-report-routes.json"
STAGE_PATH = ROOT / "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/candidate_signal_stage_history.csv"
SAMPLE_PATH = ROOT / "artifacts/patterns/pattern_b/state_forward_return_v01/snapshot_samples.csv.gz"
OUTPUT_ROOT = ROOT / "artifacts/strategies/b_select_core_v2/validation/20261003_trade_history_full_audit_v01"
REFERENCE_DATE = "2026-10-02"
ALLOWED_PREVIOUS_STAGES = {"EARLY_TREND", "TRANSITION"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ticker(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def isu(value: Any) -> str:
    return str(value or "").strip().upper()


def date_text(value: Any) -> str:
    return str(value or "")[:10]


def close_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def active_rows(
    intervals: list[dict[str, Any]], key: tuple[str, str], day: str,
) -> list[dict[str, Any]]:
    return [
        row for row in intervals
        if ticker(row.get("ticker")) == key[0]
        and isu(row.get("isu_cd")) == key[1]
        and str(row.get("state", "")).upper() == "COMMON"
        and date_text(row.get("effective_from")) <= day <= date_text(row.get("effective_to"))
    ]


def value_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-9)
    return left == right


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(field for row in rows for field in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def run() -> dict[str, Any]:
    from scripts import build_b_select_core_v2_status as builder
    from scripts.run_pattern_b_pure_simple_backtest_v01 import _load_authorities
    from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

    status = load_json(STATUS_PATH)
    monitor = load_json(MONITOR_PATH)
    routes = load_json(INDEX_PATH)
    route_items = routes["items"]
    route_map = {(ticker(row.get("ticker")), isu(row.get("isu_cd"))): row for row in route_items}
    trades = status["canonical_trade_history"]
    monitor_strategy = next(
        strategy for strategy in monitor["strategies"]
        if strategy.get("id") == "PATTERN_B_SELECT_CORE_V02"
    )
    monitor_trades = monitor_strategy["trade_history"]
    intervals, trading_dates, _calendar_provenance = _load_authorities(ROOT)
    calendar_set = set(trading_dates)
    calendar_index = {day: index for index, day in enumerate(trading_dates)}
    # A direct YYYY-MM -> final exact KRX session lookup is used for ENTRY checks.
    month_end_by_month = {
        month: max(day for day in trading_dates if day[:7] == month)
        for month in {day[:7] for day in trading_dates}
    }
    exclusion_keys = {(ticker(key[0]), isu(key[1])) for key in PERMANENT_IDENTITY_EXCLUSIONS}
    stage_rows = list(csv.DictReader(STAGE_PATH.open(encoding="utf-8-sig", newline="")))
    stage_by_trade = {
        (ticker(row.get("ticker")), isu(row.get("isu_cd")), date_text(row.get("entry_signal_date"))): row
        for row in stage_rows
    }
    if len(stage_by_trade) != len(stage_rows):
        raise RuntimeError("DUPLICATE_PATTERN_A_STAGE_AUTHORITY_KEY")
    catchup_by_trade = {
        (ticker(row.get("ticker")), isu(row.get("isu_cd")), date_text(row.get("entry_signal_date"))): row
        for row in status.get("catchup_entry_pattern_a_authorities", [])
    }
    sample = pd.read_csv(SAMPLE_PATH, compression="gzip", dtype={"ticker": "string", "isu_cd": "string"})
    sample["ticker"] = sample["ticker"].map(ticker)
    sample["isu_cd"] = sample["isu_cd"].map(isu)
    sample["snapshot_date"] = sample["snapshot_date"].astype(str).str[:10]
    sample_by_trade = {
        (row.ticker, row.isu_cd, row.snapshot_date): row.state
        for row in sample.itertuples(index=False)
    }

    key_to_trades: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        key_to_trades[(ticker(row.get("ticker")), isu(row.get("isu_cd")))].append(row)

    repository = build_production_repository_v2(ROOT, end=REFERENCE_DATE)
    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    adjusted_cache: dict[str, pd.DataFrame] = {}
    contexts_by_identity: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for key, identity_trades in sorted(key_to_trades.items()):
        open_rows = [row for row in identity_trades if row.get("trade_status") in {"OPEN", "OPEN_AT_REFERENCE"}]
        realized_rows = [row for row in identity_trades if row.get("trade_status") == "REALIZED"]
        target = REFERENCE_DATE if open_rows else max(date_text(row.get("exit_signal_date")) for row in realized_rows)
        start = min(date_text(row.get("entry_signal_date")) for row in identity_trades)
        matching_active = active_rows(intervals, key, target)
        if len(matching_active) != 1:
            raise RuntimeError(f"IDENTITY_CONTEXT_TARGET_NOT_ACTIVE:{key}:{target}:{len(matching_active)}")
        identity_row = matching_active[0]
        session_date_set = {target}
        for trade in identity_trades:
            signal_day = date_text(trade.get("entry_signal_date"))
            entry_day = date_text(trade.get("entry_execution_date"))
            exit_signal_day = date_text(trade.get("exit_signal_date"))
            exit_execution_day = date_text(trade.get("exit_execution_date"))
            lifecycle_end = exit_signal_day or target
            session_date_set.update({signal_day, entry_day})
            if exit_signal_day:
                session_date_set.add(exit_signal_day)
            if exit_execution_day:
                session_date_set.add(exit_execution_day)
            session_date_set.update(
                builder._feature_boundary_sessions(trading_dates, entry_day, lifecycle_end)
            )
        session_dates = sorted(day for day in session_date_set if start <= day <= target)
        contexts = builder._build_exact_session_contexts(
            root=ROOT,
            ticker=key[0],
            name=str(identity_trades[0].get("name") or key[0]),
            identity={
                "ticker": key[0], "isu_cd": key[1],
                "market": str(identity_row.get("market", "")).upper(),
                "effective_from": date_text(identity_row.get("effective_from")),
                "effective_to": date_text(identity_row.get("effective_to")),
            },
            intervals=intervals,
            trading_dates=trading_dates,
            session_dates=session_dates,
            report_pattern_history=[],
            repository=repository,
            pattern_a_evaluation_dates=set(),
        )
        contexts_by_identity[key] = {date_text(row.get("date")): row for row in contexts}

    trade_keys = Counter(
        (ticker(row.get("ticker")), isu(row.get("isu_cd")), date_text(row.get("entry_signal_date")))
        for row in trades
    )
    trade_identities = {(ticker(row.get("ticker")), isu(row.get("isu_cd"))) for row in trades}
    duplicate_rows = sum(count - 1 for count in trade_keys.values() if count > 1)
    exclusion_leakage = sorted(trade_identities & exclusion_keys)
    realized = [row for row in trades if row.get("trade_status") == "REALIZED"]
    opened = [row for row in trades if row.get("trade_status") in {"OPEN", "OPEN_AT_REFERENCE"}]
    sequence_error_count = 0
    for identity_trades in key_to_trades.values():
        observed_sequences = [int(row.get("trade_sequence", 0)) for row in identity_trades]
        expected_sequences = list(range(1, len(identity_trades) + 1))
        if sorted(observed_sequences) != expected_sequences:
            sequence_error_count += 1
    invalid_pattern_b_entry = 0
    invalid_pattern_a_entry = 0
    invalid_previous_stage = 0
    invalid_lookahead = 0
    midmonth_entries = 0
    invalid_identity_dates = 0
    wrong_entry_next_session = 0
    invalid_entry_open = 0
    entry_price_mismatch = 0
    invalid_exit_state = 0
    invalid_exit_position = 0
    wrong_exit_next_session = 0
    invalid_exit_open = 0
    exit_price_mismatch = 0
    lifecycle_rows: list[dict[str, Any]] = []
    duplicate_executions: Counter[tuple[str, str, str, str]] = Counter()

    monitor_map = {
        (
            ticker(row.get("ticker")), isu(row.get("isu_cd")), int(row.get("trade_sequence", 0)),
        ): row for row in monitor_trades
    }
    monitor_mismatch = 0
    monitor_keys_seen: set[tuple[str, str, int]] = set()
    parity_field_map = {
        "entry_signal_date": "entry_signal_date",
        "entry_execution_date": "entry_execution_date",
        "entry_open": "entry_price",
        "exit_signal_date": "exit_signal_date",
        "exit_execution_date": "exit_execution_date",
        "exit_price": "exit_price",
        "return_pct": "return_pct",
        "trade_status": "trade_status",
        "exit_reason": "exit_reason",
    }
    for row in trades:
        key = (ticker(row.get("ticker")), isu(row.get("isu_cd")))
        signal = date_text(row.get("entry_signal_date"))
        execution = date_text(row.get("entry_execution_date"))
        if signal not in calendar_set or month_end_by_month.get(signal[:7]) != signal:
            midmonth_entries += 1
        next_day = trading_dates[calendar_index[signal] + 1] if signal in calendar_index and calendar_index[signal] + 1 < len(trading_dates) else None
        if next_day != execution:
            wrong_entry_next_session += 1
        intervals_at_dates = [signal, execution]
        exit_signal = date_text(row.get("exit_signal_date"))
        exit_execution = date_text(row.get("exit_execution_date"))
        if row.get("trade_status") == "REALIZED":
            intervals_at_dates.extend([exit_signal, exit_execution])
        if any(len(active_rows(intervals, key, day)) != 1 for day in intervals_at_dates):
            invalid_identity_dates += 1
        if row.get("market") != next((str(item.get("market", "")).upper() for item in active_rows(intervals, key, signal)), None):
            invalid_identity_dates += 1
        contexts = contexts_by_identity[key]
        entry_context = contexts.get(signal)
        if not entry_context or entry_context.get("pattern_b_evaluation_status") != "READY" or entry_context.get("pattern_b_state") != "DEPRESSED":
            invalid_pattern_b_entry += 1
        authority_key = (key[0], key[1], signal)
        stage = stage_by_trade.get(authority_key)
        catchup = catchup_by_trade.get(authority_key)
        if stage:
            current_stage = stage.get("entry_pattern_a_stage_recomputed")
            previous_stage = stage.get("previous_pattern_a_stage")
            lookahead_free = str(stage.get("entry_pattern_a_lookahead_free", "")).lower() == "true"
            if date_text(stage.get("entry_pattern_a_requested_asof")) != signal:
                invalid_lookahead += 1
        elif catchup:
            current_stage = catchup.get("entry_pattern_a_stage_recomputed")
            previous_stage = catchup.get("previous_pattern_a_stage")
            lookahead_free = catchup.get("source") == "REPOSITORY_V2_EXACT_SESSION_EVALUATORS" and signal <= REFERENCE_DATE
        else:
            current_stage, previous_stage, lookahead_free = None, None, False
        if current_stage != "PROGRESSED":
            invalid_pattern_a_entry += 1
        if previous_stage not in ALLOWED_PREVIOUS_STAGES:
            invalid_previous_stage += 1
        if not lookahead_free:
            invalid_lookahead += 1
        monthly_authority_state = sample_by_trade.get(authority_key)
        if monthly_authority_state is not None and monthly_authority_state != "DEPRESSED":
            invalid_pattern_b_entry += 1
        # Every entry date must be supported by the exact-date Repository V2 OPEN.
        if key[0] not in adjusted_cache:
            adjusted_cache[key[0]] = adjusted_store.load_daily_source(key[0])
        price_frame = adjusted_cache[key[0]]
        entry_open = close_number(price_frame.loc[pd.Timestamp(execution)].get("open")) if pd.Timestamp(execution) in price_frame.index else None
        if entry_open is None or entry_open <= 0:
            invalid_entry_open += 1
        elif not math.isclose(entry_open, float(row["entry_open"]), rel_tol=0, abs_tol=1e-9):
            entry_price_mismatch += 1
        duplicate_executions[(key[0], key[1], execution, "ENTRY")] += 1

        if row.get("trade_status") == "REALIZED":
            if exit_signal < execution:
                invalid_exit_position += 1
            exit_context = contexts.get(exit_signal)
            if not exit_context or exit_context.get("pattern_b_evaluation_status") != "READY" or exit_context.get("pattern_b_state") != "NORMAL":
                invalid_exit_state += 1
            # The first daily NORMAL signal while this position is open must be the canonical exit.
            first_normal = next((day for day in sorted(contexts) if execution <= day <= exit_signal and contexts[day].get("pattern_b_evaluation_status") == "READY" and contexts[day].get("pattern_b_state") == "NORMAL"), None)
            if first_normal != exit_signal:
                invalid_exit_state += 1
            exit_next = trading_dates[calendar_index[exit_signal] + 1] if exit_signal in calendar_index and calendar_index[exit_signal] + 1 < len(trading_dates) else None
            if exit_next != exit_execution:
                wrong_exit_next_session += 1
            exit_open = close_number(price_frame.loc[pd.Timestamp(exit_execution)].get("open")) if exit_next and pd.Timestamp(exit_execution) in price_frame.index else None
            if exit_open is None or exit_open <= 0:
                invalid_exit_open += 1
            elif not math.isclose(exit_open, float(row["exit_price"]), rel_tol=0, abs_tol=1e-9):
                exit_price_mismatch += 1
            duplicate_executions[(key[0], key[1], exit_execution, "EXIT")] += 1
        lifecycle_rows.append({
            "ticker": key[0], "isu_cd": key[1], "trade_sequence": row["trade_sequence"],
            "entry_signal_date": signal, "entry_execution_date": execution,
            "entry_pattern_b_state": (entry_context or {}).get("pattern_b_state"),
            "pattern_a_stage": current_stage, "previous_pattern_a_stage": previous_stage,
            "exit_signal_date": exit_signal or None, "exit_execution_date": exit_execution or None,
            "exit_pattern_b_state": (contexts.get(exit_signal) or {}).get("pattern_b_state") if exit_signal else None,
            "trade_status": row.get("trade_status"), "identity_excluded": key in exclusion_keys,
        })
        monitor_key = (*key, int(row.get("trade_sequence", 0)))
        monitor_row = monitor_map.get(monitor_key)
        if monitor_row is None:
            monitor_mismatch += 1
        else:
            monitor_keys_seen.add(monitor_key)
            for canonical_field, monitor_field in parity_field_map.items():
                if not value_equal(row.get(canonical_field), monitor_row.get(monitor_field)):
                    monitor_mismatch += 1

    duplicate_execution_count = sum(count - 1 for count in duplicate_executions.values() if count > 1)
    overlap_count = 0
    for key, identity_trades in key_to_trades.items():
        ordered = sorted(identity_trades, key=lambda row: (date_text(row.get("entry_execution_date")), int(row["trade_sequence"])))
        last_exit_execution = None
        for row in ordered:
            if last_exit_execution and date_text(row.get("entry_execution_date")) <= last_exit_execution:
                overlap_count += 1
            if row.get("trade_status") == "REALIZED":
                last_exit_execution = date_text(row.get("exit_execution_date"))
            else:
                last_exit_execution = "9999-99-99"

    current_open_missed_normal_exit = 0
    open_valuation_missing = 0
    open_valuation_mismatch = 0
    for row in opened:
        key = (ticker(row.get("ticker")), isu(row.get("isu_cd")))
        entry_exec = date_text(row.get("entry_execution_date"))
        contexts = contexts_by_identity[key]
        for day, context in contexts.items():
            if day < entry_exec or day > REFERENCE_DATE or context.get("pattern_b_evaluation_status") != "READY" or context.get("pattern_b_state") != "NORMAL":
                continue
            if day not in calendar_index:
                continue
            next_position = calendar_index[day] + 1
            if next_position < len(trading_dates) and trading_dates[next_position] <= REFERENCE_DATE:
                if key[0] not in adjusted_cache:
                    adjusted_cache[key[0]] = adjusted_store.load_daily_source(key[0])
                frame = adjusted_cache[key[0]]
                next_date = trading_dates[next_position]
                open_value = close_number(frame.loc[pd.Timestamp(next_date)].get("open")) if pd.Timestamp(next_date) in frame.index else None
                if open_value is not None and open_value > 0:
                    current_open_missed_normal_exit += 1
                    break
        if key[0] not in adjusted_cache:
            adjusted_cache[key[0]] = adjusted_store.load_daily_source(key[0])
        frame = adjusted_cache[key[0]]
        latest = close_number(frame.loc[pd.Timestamp(REFERENCE_DATE)].get("close")) if pd.Timestamp(REFERENCE_DATE) in frame.index else None
        route = route_map.get(key)
        report = None
        if route:
            report_path = ROOT / "web" / str(route.get("url", "")).removeprefix("./")
            if report_path.is_file():
                report = load_json(report_path)
        canonical_mark = close_number((report or {}).get("price_trend", {}).get("latest_close"))
        if latest is None or latest <= 0:
            open_valuation_missing += 1
        elif canonical_mark is None or not math.isclose(latest, canonical_mark, rel_tol=0, abs_tol=1e-9):
            open_valuation_mismatch += 1

    route_missing_or_bad = []
    for key in trade_identities:
        route = route_map.get(key)
        if not route:
            route_missing_or_bad.append((key, "ROUTE_MISSING"))
            continue
        relative_path = route.get("url", "")
        path = ROOT / "web" / relative_path.removeprefix("./")
        if not path.is_file():
            route_missing_or_bad.append((key, "FILE_MISSING"))
            continue
        report = load_json(path)
        report_identity = report.get("identity") or {}
        if ticker(report_identity.get("ticker")) != key[0] or isu(report_identity.get("isu_cd")) != key[1]:
            route_missing_or_bad.append((key, "WRONG_IDENTITY"))
        if route.get("report_type") == "HISTORICAL_ARCHIVE" and (report.get("availability") or {}).get("identity_status") != "HISTORICAL / NOT_CURRENT_COMMON":
            route_missing_or_bad.append((key, "HISTORICAL_STATUS_MISSING"))
    current_open_keys = {(ticker(row.get("ticker")), isu(row.get("isu_cd"))) for row in opened}
    open_route_resolved = sum(key in route_map and key not in {item[0] for item in route_missing_or_bad} for key in current_open_keys)
    baseline_index = json.loads(__import__("subprocess").check_output(["git", "show", "HEAD:web/data/stock-index.json"], cwd=ROOT, text=True))
    baseline_tickers = {
        ticker(row.get("ticker")) for row in baseline_index.get("items", [])
        if row.get("report_available") is True and row.get("asset_type") == "COMMON"
    }
    current_history_identities = {
        key for key in trade_identities if active_rows(intervals, key, REFERENCE_DATE)
    }
    report_before = len({key for key in current_history_identities if key[0] in baseline_tickers})
    open_keys = {(ticker(row.get("ticker")), isu(row.get("isu_cd"))) for row in opened}
    open_report_before = sum(key in current_history_identities and key[0] in baseline_tickers for key in open_keys)
    route_type_counts = Counter(row.get("report_type") for row in route_items)
    realized_identity_missing_before = len({
        (ticker(row.get("ticker")), isu(row.get("isu_cd")))
        for row in realized
        if (ticker(row.get("ticker")), isu(row.get("isu_cd"))) not in current_history_identities
        or ticker(row.get("ticker")) not in baseline_tickers
    })
    all_trade_ids = {
        (ticker(row.get("ticker")), isu(row.get("isu_cd")), int(row.get("trade_sequence", 0)))
        for row in trades
    }
    monitor_extra = len(set(monitor_map) - all_trade_ids)

    audit_checks = {
        "canonical_trade_rows": len(trades),
        "unique_exact_identities": len(trade_identities),
        "realized_trade_rows": len(realized),
        "open_trade_rows": len(opened),
        "identity_interval_errors": invalid_identity_dates,
        "permanent_exclusion_leakage": len(exclusion_leakage),
        "midmonth_entry_signals": midmonth_entries,
        "invalid_pattern_b_entry": invalid_pattern_b_entry,
        "invalid_pattern_a_stage_entry": invalid_pattern_a_entry,
        "invalid_previous_pattern_a_stage_entry": invalid_previous_stage,
        "lookahead_or_unverified_pattern_a_entry": invalid_lookahead,
        "wrong_entry_next_session": wrong_entry_next_session,
        "missing_or_invalid_entry_open": invalid_entry_open,
        "entry_open_price_mismatch": entry_price_mismatch,
        "invalid_exit_normal_signal": invalid_exit_state,
        "exit_signal_without_open_position": invalid_exit_position,
        "wrong_exit_next_session": wrong_exit_next_session,
        "missing_or_invalid_exit_open": invalid_exit_open,
        "exit_open_price_mismatch": exit_price_mismatch,
        "current_open_executable_normal_exit_missing": current_open_missed_normal_exit,
        "current_open_latest_valuation_missing": open_valuation_missing,
        "current_open_latest_valuation_mismatch": open_valuation_mismatch,
        "duplicate_trade_rows": duplicate_rows,
        "duplicate_executions": duplicate_execution_count,
        "overlapping_same_identity_positions": overlap_count,
        "trade_sequence_errors": sequence_error_count,
        "monitor_parity_mismatches": monitor_mismatch,
        "monitor_extra_rows": monitor_extra,
        "pending_entry_events": sum(row.get("event_type") == "ENTRY" for row in status.get("canonical_pending_events", [])),
        "pending_exit_events": sum(row.get("event_type") == "EXIT" for row in status.get("canonical_pending_events", [])),
        "current_v1_source_rows": int(status.get("current_v1_source_row_count", -1)),
        "broken_or_wrong_identity_report_routes": len(route_missing_or_bad),
        "current_open_report_routes": open_route_resolved,
    }
    severity = {
        "CRITICAL": sum(audit_checks[key] for key in (
            "identity_interval_errors", "permanent_exclusion_leakage", "midmonth_entry_signals",
            "invalid_pattern_b_entry", "invalid_pattern_a_stage_entry", "invalid_previous_pattern_a_stage_entry",
            "lookahead_or_unverified_pattern_a_entry", "wrong_entry_next_session", "missing_or_invalid_entry_open",
            "entry_open_price_mismatch", "invalid_exit_normal_signal", "exit_signal_without_open_position",
            "wrong_exit_next_session", "missing_or_invalid_exit_open", "exit_open_price_mismatch",
            "current_open_executable_normal_exit_missing", "current_open_latest_valuation_missing",
            "current_open_latest_valuation_mismatch", "duplicate_trade_rows", "duplicate_executions",
            "overlapping_same_identity_positions", "trade_sequence_errors", "monitor_parity_mismatches",
            "monitor_extra_rows", "pending_entry_events", "pending_exit_events", "current_v1_source_rows",
            "broken_or_wrong_identity_report_routes",
        )),
        "MAJOR": 0,
        "MINOR": 0,
    }
    expected = {
        "canonical_trade_rows": 488, "unique_exact_identities": 399,
        "realized_trade_rows": 451, "open_trade_rows": 37,
        "current_open_report_routes": 37,
    }
    expected_failures = {key: (audit_checks.get(key), value) for key, value in expected.items() if audit_checks.get(key) != value}
    if expected_failures:
        severity["CRITICAL"] += len(expected_failures)
    status_token = "B_SELECT_CORE_V02_TRADE_HISTORY_AUDIT_PASS" if severity["CRITICAL"] == 0 else "B_SELECT_CORE_V02_TRADE_HISTORY_AUDIT_CHECK_REQUIRED"
    audit_rows_by_id = {(row["ticker"], row["isu_cd"], int(row["trade_sequence"])): row for row in lifecycle_rows}
    for key in all_trade_ids:
        if key not in audit_rows_by_id:
            continue

    summary = {
        "status": status_token,
        "requested_as_of": status.get("requested_as_of"),
        "reference_market_date": REFERENCE_DATE,
        "severity_counts": severity,
        "checks": audit_checks,
        "expected_count_failures": expected_failures,
        "report_coverage": {
            "canonical_trades": len(trades),
            "unique_exact_identities": len(trade_identities),
            "existing_current_exact_report_routes_before": report_before,
            "missing_exact_report_routes_before": len(trade_identities) - report_before,
            "current_open_exact_report_routes_before": open_report_before,
            "current_open_exact_reports_missing_before": len(open_keys) - open_report_before,
            "realized_history_identities_missing_before": realized_identity_missing_before,
            "current_open_route_coverage": f"{open_route_resolved}/{len(opened)}",
            "all_history_route_coverage": f"{len(trade_identities) - len(route_missing_or_bad)}/{len(trade_identities)}",
            "historical_archive_reports": route_type_counts.get("HISTORICAL_ARCHIVE", 0),
            "identity_only_current_reports": route_type_counts.get("IDENTITY_ONLY_CURRENT", 0),
            "current_stock_report_routes_after": route_type_counts.get("CURRENT_STOCK_REPORT", 0),
            "broken_or_wrong_identity_routes": route_missing_or_bad,
            "ticker_only_fallback_count": 0,
        },
        "exit_cadence": {
            "realized": len(realized),
            "month_end_signal_count": sum(date_text(row.get("exit_signal_date")) == month_end_by_month.get(date_text(row.get("exit_signal_date"))[:7]) for row in realized),
            "midmonth_signal_count": sum(date_text(row.get("exit_signal_date")) != month_end_by_month.get(date_text(row.get("exit_signal_date"))[:7]) for row in realized),
            "non_first_month_session_execution_count": sum(
                trading_dates[calendar_index[date_text(row.get("exit_execution_date"))] - 1][:7] == date_text(row.get("exit_execution_date"))[:7]
                for row in realized if date_text(row.get("exit_execution_date")) in calendar_index and calendar_index[date_text(row.get("exit_execution_date"))] > 0
            ),
            "non_normal_exit_reason_count": sum(row.get("exit_reason") != "PATTERN_B_NORMAL_NEXT_OPEN" for row in realized),
        },
        "monitor_parity_fields": parity_field_map,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_ROOT / "trade_lifecycle_audit.csv", lifecycle_rows)
    write_json(OUTPUT_ROOT / "summary.json", summary)
    report = [
        "# B Select Core V2 canonical trade history full audit",
        "",
        f"- Status: `{status_token}`",
        f"- CRITICAL / MAJOR / MINOR: {severity['CRITICAL']} / {severity['MAJOR']} / {severity['MINOR']}",
        "- Authority: frozen 2026-10-03 V2 canonical status; local exact Repository V2 evaluator and adjusted OHLC; PIT identity/calendar authorities.",
        "",
        "## Coverage and lifecycle",
        "",
        "| Check | Result |",
        "|---|---:|",
    ]
    for key, value in audit_checks.items():
        report.append(f"| {key} | {value} |")
    report.extend([
        "",
        "## Exact identity report coverage",
        "",
        f"- Exact identities: {len(trade_identities)}; exact published report routes before this change: {report_before}; missing before: {len(trade_identities) - report_before}.",
        f"- Current OPEN reports before: {open_report_before}/{len(open_keys)}; missing before: {len(open_keys) - open_report_before}.",
        f"- Current OPEN route coverage: {open_route_resolved}/{len(opened)}; all history: {len(trade_identities) - len(route_missing_or_bad)}/{len(trade_identities)}.",
        f"- Current stock reports: {route_type_counts.get('CURRENT_STOCK_REPORT', 0)}; current identity-only: {route_type_counts.get('IDENTITY_ONLY_CURRENT', 0)}; historical archive: {route_type_counts.get('HISTORICAL_ARCHIVE', 0)}.",
        "- Routes are resolved only by exact `(ticker, ISU_CD)`; ticker-only fallback count: 0.",
        "",
        "## EXIT cadence",
        "",
        f"- Month-end signal: {summary['exit_cadence']['month_end_signal_count']}; midmonth signal: {summary['exit_cadence']['midmonth_signal_count']}.",
        f"- Non-first-month-session execution: {summary['exit_cadence']['non_first_month_session_execution_count']}; non-NORMAL exit: {summary['exit_cadence']['non_normal_exit_reason_count']}.",
        "",
    ])
    (OUTPUT_ROOT / "report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
