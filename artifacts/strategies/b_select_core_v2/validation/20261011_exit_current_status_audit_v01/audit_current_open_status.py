#!/usr/bin/env python3
"""Independent read-only audit of B Select Core V2 open positions as of 2026-10-08."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "artifacts/strategies/b_select_core_v2/validation/20261011_exit_current_status_audit_v01"
PRIOR_STATUS = ROOT / "artifacts/strategies/b_select_core_v2/production/20261003/status.json"
CURRENT_STATUS = ROOT / "artifacts/strategies/b_select_core_v2/production/20261011/status.json"
PRIOR_AUDIT = ROOT / "artifacts/strategies/b_select_core_v2/validation/20261003_trade_history_full_audit_v01"
MONITOR = ROOT / "web/data/strategy-monitor.json"
STOCK_INDEX = ROOT / "web/data/stock-index.json"
REFERENCE = "2026-10-08"
REQUESTED_AS_OF = "2026-10-11"
SESSION_DATES = ["2026-10-06", "2026-10-07", "2026-10-08"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def norm_ticker(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def norm_isu(value: Any) -> str:
    return str(value or "").strip().upper()


def day(value: Any) -> str:
    return str(value or "")[:10]


def position_key(row: dict[str, Any]) -> tuple[str, str, int, str, str]:
    return (
        norm_ticker(row.get("ticker")), norm_isu(row.get("isu_cd")),
        int(row.get("trade_sequence") or 0), day(row.get("entry_signal_date")),
        day(row.get("entry_execution_date")),
    )


def item_key(row: dict[str, Any]) -> tuple[str, str]:
    return norm_ticker(row.get("ticker")), norm_isu(row.get("isu_cd"))


def num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def equal(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0, abs_tol=tolerance)
    return left == right


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row.get(k) for k in fields} for row in rows)


def main() -> int:
    from scripts.run_pattern_b_pure_simple_backtest_v01 import _load_authorities
    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2
    from trend_scanner.patterns import pattern_b_operational
    from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

    prior = read_json(PRIOR_STATUS)
    current = read_json(CURRENT_STATUS)
    monitor = read_json(MONITOR)
    stock_index = read_json(STOCK_INDEX)
    prior_audit_summary = read_json(PRIOR_AUDIT / "summary.json")
    prior_audit_rows_path = PRIOR_AUDIT / "trade_lifecycle_audit.csv"
    with prior_audit_rows_path.open(encoding="utf-8", newline="") as f:
        prior_audit_rows = list(csv.DictReader(f))

    # The production calendar loader validates merged PIT/calendar against its rolling authority.
    rolling_calendar = load_rolling_production_market_calendar(ROOT)
    if rolling_calendar is None:
        raise RuntimeError("ROLLING_KRX_CALENDAR_UNAVAILABLE")
    intervals, trading_dates, _source_provenance = _load_authorities(ROOT)
    calendar_dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in rolling_calendar.trading_dates]
    if calendar_dates != trading_dates:
        raise RuntimeError("MERGED_CALENDAR_AUTHORITY_DISAGREEMENT")
    calendar_set = set(calendar_dates)
    if any(d not in calendar_set for d in SESSION_DATES):
        raise RuntimeError("REQUESTED_AUDIT_DAY_NOT_EXACT_KRX_SESSION")
    repository = build_production_repository_v2(ROOT, end=REFERENCE)

    prior_rows = prior.get("canonical_trade_history") or []
    current_rows = current.get("canonical_trade_history") or []
    prior_open = [r for r in prior_rows if r.get("trade_status") == "OPEN_AT_REFERENCE"]
    current_open = [r for r in current_rows if r.get("trade_status") == "OPEN_AT_REFERENCE"]
    canonical_open_rows = current.get("canonical_current_open_positions") or []
    old_keys = [position_key(r) for r in prior_open]
    current_keys = [position_key(r) for r in current_open]
    canonical_open_keys = [position_key(r) for r in canonical_open_rows]
    current_trade_keys = [position_key(r) for r in current_rows]
    prior_trade_keys = [position_key(r) for r in prior_rows]
    prior_realized_by_key = {position_key(r): r for r in prior_rows if r.get("trade_status") == "REALIZED"}
    current_by_key = {position_key(r): r for r in current_rows}
    prior_by_key = {position_key(r): r for r in prior_rows}
    realized_mutations = []
    for key, row in prior_realized_by_key.items():
        if key not in current_by_key or current_by_key[key] != row:
            realized_mutations.append(key)

    strategy_id = "PATTERN_B_SELECT_CORE_V02"
    monitor_strategy = next(s for s in monitor.get("strategies", []) if s.get("id") == strategy_id)
    monitor_trades = monitor_strategy.get("trade_history") or []
    monitor_trade_by_key = {position_key(r): r for r in monitor_trades}
    monitor_trade_mismatches: list[dict[str, Any]] = []
    trade_field_map = {
        "trade_status": "trade_status",
        "entry_signal_date": "entry_signal_date",
        "entry_execution_date": "entry_execution_date",
        "entry_open": "entry_price",
        "exit_signal_date": "exit_signal_date",
        "exit_execution_date": "exit_execution_date",
        "exit_price": "exit_price",
        "return_pct": "return_pct",
        "exit_reason": "exit_reason",
    }
    for key, row in current_by_key.items():
        other = monitor_trade_by_key.get(key)
        if other is None:
            monitor_trade_mismatches.append({"key": key, "field": "missing_trade"})
            continue
        for canonical_field, monitor_field in trade_field_map.items():
            if not equal(row.get(canonical_field), other.get(monitor_field)):
                monitor_trade_mismatches.append({
                    "key": key, "field": canonical_field,
                    "canonical": row.get(canonical_field), "monitor": other.get(monitor_field),
                })

    public_items = current.get("items") or []
    public_map = {item_key(r): r for r in public_items}
    monitor_items = monitor_strategy.get("items") or []
    monitor_item_map = {item_key(r): r for r in monitor_items}
    index_items = stock_index.get("items") or []
    current_index = [r for r in index_items if r.get("report_available") is True and r.get("asset_type") == "COMMON"]
    index_map = {item_key(r): r for r in current_index}
    public_key_set = set(public_map)
    monitor_key_set = set(monitor_item_map)
    index_key_set = set(index_map)
    current_public_open = [r for r in public_items if r.get("canonical_position") == "OPEN"]

    public_report_audit: list[dict[str, Any]] = []
    public_report_hashes: list[dict[str, Any]] = []
    report_identity_mismatches = []
    report_eval_mismatches = []
    report_market_mismatches = []
    report_price_mismatches = []
    item_monitor_mismatches = []
    unavailable_rows: list[dict[str, Any]] = []
    report_pattern_status_counts: Counter[str] = Counter()
    report_availability_counts: Counter[str] = Counter()
    b_unavailable_reason_counts: Counter[str] = Counter()

    item_fields = [
        "action", "strategy_state", "canonical_position", "action_reason", "data_status",
        "pattern_b_state", "latest_close", "latest_close_as_of", "bucket", "component_id",
        "permanent_identity_excluded",
    ]
    for key, item in sorted(public_map.items()):
        monitor_item = monitor_item_map.get(key)
        if monitor_item is None:
            item_monitor_mismatches.append({"key": key, "field": "missing_monitor_item"})
        else:
            for field in item_fields:
                if not equal(item.get(field), monitor_item.get(field)):
                    item_monitor_mismatches.append({"key": key, "field": field})
            left_trade, right_trade = item.get("current_trade") or {}, monitor_item.get("current_trade") or {}
            for field in ("trade_sequence", "entry_signal_date", "entry_execution_date", "entry_open", "return_pct", "trade_status"):
                if not equal(left_trade.get(field), right_trade.get(field)):
                    item_monitor_mismatches.append({"key": key, "field": f"current_trade.{field}"})

        index_item = index_map.get(key)
        if index_item is None:
            report_identity_mismatches.append({"key": key, "source": "stock-index missing exact current COMMON identity"})
        else:
            for f in ("name", "market", "asset_type"):
                if item.get(f) != index_item.get(f):
                    report_market_mismatches.append({"key": key, "field": f, "status": item.get(f), "index": index_item.get(f)})

        report_path = ROOT / "web/data/stocks" / f"{key[0]}.json"
        if not report_path.is_file():
            report_identity_mismatches.append({"key": key, "source": "stock report file missing"})
            continue
        report_digest = sha256(report_path)
        public_report_hashes.append({"ticker": key[0], "isu_cd": key[1], "path": report_path.relative_to(ROOT).as_posix(), "sha256": report_digest})
        report = read_json(report_path)
        identity = report.get("identity") or {}
        report_key = (norm_ticker(identity.get("ticker")), norm_isu(identity.get("isu_cd")))
        if report_key != key:
            report_identity_mismatches.append({"key": key, "report_key": report_key})
        if identity.get("market") != item.get("market") or identity.get("asset_type") != item.get("asset_type"):
            report_market_mismatches.append({"key": key, "report_market": identity.get("market"), "status_market": item.get("market")})
        p_b = report.get("pattern_b") or {}
        p_status = str(p_b.get("evaluation_status") or "MISSING")
        p_asof = day(p_b.get("as_of"))
        report_pattern_status_counts[p_status] += 1
        report_availability_counts[str((report.get("availability") or {}).get("report_status") or "MISSING")] += 1
        excluded = bool(item.get("permanent_identity_excluded"))
        expected_state = p_b.get("pattern_b_state") if p_status == "READY" else None
        if excluded:
            if item.get("action_reason") != "PERMANENT_IDENTITY_EXCLUSION" or item.get("data_status") != "NOT_APPLICABLE" or item.get("canonical_position") != "NOT_APPLICABLE":
                report_eval_mismatches.append({"key": key, "source": "exclusion not surfaced as NOT_APPLICABLE"})
        else:
            if p_asof != REFERENCE or item.get("pattern_b_state") != expected_state:
                report_eval_mismatches.append({"key": key, "field": "pattern_b_state/as_of", "report": (p_status, expected_state, p_asof), "status": (item.get("data_status"), item.get("pattern_b_state"), item.get("latest_close_as_of"))})
            expected_data_status = "READY" if p_status == "READY" else "UNAVAILABLE" if p_status == "UNAVAILABLE" else None
            if expected_data_status is None or item.get("data_status") != expected_data_status:
                report_eval_mismatches.append({"key": key, "field": "data_status", "report": p_status, "status": item.get("data_status")})
        p_price = report.get("price_trend") or {}
        if not excluded:
            if p_price.get("latest_close") != item.get("latest_close") or day(p_price.get("latest_close_as_of")) != day(item.get("latest_close_as_of")):
                report_price_mismatches.append({"key": key, "report": (p_price.get("latest_close"), p_price.get("latest_close_as_of")), "status": (item.get("latest_close"), item.get("latest_close_as_of"))})
        if item.get("bucket") == "unavailable":
            pending = item.get("pending_event")
            if not excluded:
                for reason in p_b.get("reason_codes") or ["UNSPECIFIED"]:
                    b_unavailable_reason_counts[str(reason)] += 1
            unavailable_rows.append({
                "ticker": key[0], "isu_cd": key[1], "name": item.get("name"),
                "action": item.get("action"), "strategy_state": item.get("strategy_state"),
                "canonical_position": item.get("canonical_position"),
                "action_reason": item.get("action_reason"), "data_status": item.get("data_status"),
                "permanent_identity_excluded": excluded,
                "pattern_b_evaluation_status": p_status,
                "pattern_b_state": p_b.get("pattern_b_state"), "pattern_b_as_of": p_asof,
                "pattern_b_reason_codes": json.dumps(p_b.get("reason_codes") or [], ensure_ascii=False),
                "pattern_b_reason_details": json.dumps(p_b.get("reason_details") or [], ensure_ascii=False),
                "current_trade_present": bool(item.get("current_trade")),
                "pending_event_present": bool(pending),
            })
        public_report_audit.append({
            "ticker": key[0], "isu_cd": key[1], "name": item.get("name"),
            "market": item.get("market"), "public_report": True,
            "status_action": item.get("action"), "status_reason": item.get("action_reason"),
            "status_state": item.get("strategy_state"), "status_data_status": item.get("data_status"),
            "status_position": item.get("canonical_position"), "status_bucket": item.get("bucket"),
            "status_pattern_b_state": item.get("pattern_b_state"),
            "status_as_of": item.get("latest_close_as_of"), "status_close": item.get("latest_close"),
            "pattern_b_evaluation_status": p_status, "pattern_b_state": p_b.get("pattern_b_state"),
            "pattern_b_as_of": p_asof,
            "pattern_b_reason_codes": json.dumps(p_b.get("reason_codes") or [], ensure_ascii=False),
            "report_status": (report.get("availability") or {}).get("report_status"),
            "report_close": p_price.get("latest_close"), "report_close_as_of": p_price.get("latest_close_as_of"),
            "monitor_action": (monitor_item or {}).get("action"),
            "monitor_reason": (monitor_item or {}).get("action_reason"),
            "monitor_position": (monitor_item or {}).get("canonical_position"),
            "permanent_identity_excluded": excluded,
            "exact_key_match": report_key == key and key in monitor_key_set and key in index_key_set,
        })

    exclusions = {(norm_ticker(k[0]), norm_isu(k[1])) for k in PERMANENT_IDENTITY_EXCLUSIONS}
    open_identity_set = {(k[0], k[1]) for k in current_keys}
    hidden_open_rows = [r for r in canonical_open_rows if item_key(r) not in public_key_set]
    unavailable_open_rows = [r for r in public_items if r.get("bucket") == "unavailable" and r.get("canonical_position") == "OPEN"]
    open_identities_in_unavailable = [r for r in public_items if r.get("bucket") == "unavailable" and item_key(r) in open_identity_set]

    # Independently evaluate every canonical OPEN from current Repository V2 adjusted OHLC.
    open_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    open_evaluation_errors: list[dict[str, Any]] = []
    state_counts = {d: Counter() for d in SESSION_DATES}
    normal_signals: list[dict[str, Any]] = []
    entry_price_mismatches: list[dict[str, Any]] = []
    close_missing: list[dict[str, Any]] = []
    return_mismatches: list[dict[str, Any]] = []
    active_identity_errors: list[dict[str, Any]] = []
    first_normal_execution_issues: list[dict[str, Any]] = []
    pending_by_key = {}
    for event in current.get("canonical_pending_events") or []:
        ek = (norm_ticker(event.get("ticker")), norm_isu(event.get("isu_cd")), int(event.get("trade_sequence") or 0), day(event.get("signal_date")))
        pending_by_key[ek] = event

    for trade in sorted(canonical_open_rows, key=position_key):
        ticker = norm_ticker(trade.get("ticker"))
        isu_cd = norm_isu(trade.get("isu_cd"))
        identity = (ticker, isu_cd)
        key = position_key(trade)
        matching_ref = [iv for iv in intervals if norm_ticker(iv.get("ticker")) == ticker and norm_isu(iv.get("isu_cd")) == isu_cd and str(iv.get("state", "")).upper() == "COMMON" and day(iv.get("effective_from")) <= REFERENCE <= day(iv.get("effective_to"))]
        if len(matching_ref) != 1:
            active_identity_errors.append({"key": key, "reference_matches": len(matching_ref)})
            open_evaluation_errors.append({"key": key, "error": "ACTIVE_PIT_IDENTITY_NOT_UNIQUE"})
            continue
        active = matching_ref[0]
        for d in SESSION_DATES:
            matches = [iv for iv in intervals if norm_ticker(iv.get("ticker")) == ticker and norm_isu(iv.get("isu_cd")) == isu_cd and str(iv.get("state", "")).upper() == "COMMON" and day(iv.get("effective_from")) <= d <= day(iv.get("effective_to"))]
            if len(matches) != 1 or str(matches[0].get("market", "")).upper() != str(trade.get("market", "")).upper():
                active_identity_errors.append({"key": key, "date": d, "matches": len(matches), "market": [x.get("market") for x in matches]})
        try:
            chain = pattern_b_operational.history_chain(ticker, active, intervals, trading_dates)
            daily = pattern_b_operational.load_history(repository, ticker, chain, REFERENCE)
            if daily is None or daily.empty:
                raise RuntimeError("REPOSITORY_V2_PATTERN_B_HISTORY_UNAVAILABLE")
            if daily.index.max().strftime("%Y-%m-%d") > REFERENCE:
                raise RuntimeError("FUTURE_PRICE_ROW_READ")
            entry_day = day(trade.get("entry_execution_date"))
            entry_open = num(trade.get("entry_open"))
            if entry_day not in daily.index or entry_open is None or entry_open <= 0:
                entry_price_mismatches.append({"key": key, "entry_day": entry_day, "stored_entry_open": entry_open, "repository_entry_open": None})
                repo_entry_open = None
            else:
                repo_entry_open = num(daily.loc[pd.Timestamp(entry_day), "open"])
                if repo_entry_open is None or not math.isclose(repo_entry_open, entry_open, rel_tol=0, abs_tol=1e-7):
                    entry_price_mismatches.append({"key": key, "entry_day": entry_day, "stored_entry_open": entry_open, "repository_entry_open": repo_entry_open})
            if pd.Timestamp(REFERENCE) not in daily.index:
                close = None
                close_missing.append({"key": key, "reference": REFERENCE})
            else:
                close = num(daily.loc[pd.Timestamp(REFERENCE), "close"])
                if close is None or close <= 0:
                    close_missing.append({"key": key, "reference": REFERENCE, "close": close})
            return_pct = (close / entry_open - 1.0) * 100.0 if close is not None and close > 0 and entry_open and entry_open > 0 else None
            if return_pct is not None and num(trade.get("return_pct")) is not None and not math.isclose(return_pct, float(trade["return_pct"]), rel_tol=0, abs_tol=1e-8):
                return_mismatches.append({"key": key, "repository_return_pct": return_pct, "canonical_return_pct": trade.get("return_pct")})

            local_evaluations = []
            for d in SESSION_DATES:
                if d not in calendar_set:
                    raise RuntimeError(f"NON_EXACT_KRX_SESSION:{d}")
                result = evaluate_pattern_b(ticker, daily, d, name=str(trade.get("name") or ticker))
                status_value = result.evaluation_status.value
                state = result.pattern_b_state if status_value == "READY" else None
                if result.as_of != d:
                    raise RuntimeError(f"EVALUATION_DATE_MISMATCH:{d}:{result.as_of}")
                if result.monthly_last_bar and result.monthly_last_bar > d:
                    raise RuntimeError(f"FUTURE_MONTHLY_EVIDENCE:{d}:{result.monthly_last_bar}")
                if result.weekly_last_bar and result.weekly_last_bar > d:
                    raise RuntimeError(f"FUTURE_WEEKLY_EVIDENCE:{d}:{result.weekly_last_bar}")
                state_counts[d][state or "UNAVAILABLE"] += 1
                session_row = {
                    "ticker": ticker, "name": trade.get("name"), "isu_cd": isu_cd,
                    "trade_sequence": int(trade.get("trade_sequence") or 0), "entry_signal_date": day(trade.get("entry_signal_date")),
                    "entry_execution_date": entry_day, "evaluation_date": d,
                    "evaluation_status": status_value, "state": state,
                    "reason_codes": json.dumps(list(result.reason_codes), ensure_ascii=False),
                    "reason_details": json.dumps(list(result.reason_details), ensure_ascii=False),
                    "range_36m": result.range_36m, "monthly_ma24_distance": result.monthly_ma24_distance,
                    "range_52w": result.range_52w, "monthly_last_bar": result.monthly_last_bar,
                    "weekly_last_bar": result.weekly_last_bar,
                    "feature_contract_version": result.feature_contract_version,
                    "state_rule_version": result.state_rule_version,
                    "repository_data_last_date": daily.index.max().strftime("%Y-%m-%d"),
                    "pit_market": str(active.get("market", "")).upper(),
                    "pit_segment_from": day(active.get("effective_from")),
                    "pit_segment_to": day(active.get("effective_to")),
                    "history_chain": json.dumps([{
                        "market": seg.market, "isu_cd": seg.isu_cd,
                        "effective_from": seg.effective_from, "effective_to": seg.effective_to,
                    } for seg in chain.segments], ensure_ascii=False),
                }
                session_rows.append(session_row)
                local_evaluations.append(session_row)
            normal_dates = [r["evaluation_date"] for r in local_evaluations if r["evaluation_status"] == "READY" and r["state"] == "NORMAL"]
            for signal_date in normal_dates:
                normal_signals.append({"key": key, "signal_date": signal_date})
                if signal_date < REFERENCE:
                    pos = calendar_dates.index(signal_date)
                    next_date = calendar_dates[pos + 1] if pos + 1 < len(calendar_dates) else None
                    if next_date is None or next_date > REFERENCE:
                        first_normal_execution_issues.append({"key": key, "signal_date": signal_date, "type": "UNSCHEDULED_BEFORE_REFERENCE"})
                    else:
                        next_open = num(daily.loc[pd.Timestamp(next_date), "open"]) if pd.Timestamp(next_date) in daily.index else None
                        if next_open is not None and next_open > 0:
                            first_normal_execution_issues.append({"key": key, "signal_date": signal_date, "next_session": next_date, "next_open": next_open, "type": "EXECUTABLE_EXIT_MISSING_FROM_OPEN_LEDGER"})
                        else:
                            first_normal_execution_issues.append({"key": key, "signal_date": signal_date, "next_session": next_date, "type": "NEXT_OPEN_UNAVAILABLE_CHECK_REQUIRED"})
                elif signal_date == REFERENCE:
                    pending_key = (ticker, isu_cd, int(trade.get("trade_sequence") or 0), signal_date)
                    if pending_key not in pending_by_key:
                        first_normal_execution_issues.append({"key": key, "signal_date": signal_date, "type": "PENDING_EXIT_MISSING"})

            public_item = public_map.get(identity)
            monitor_item = monitor_item_map.get(identity)
            visibility = "PUBLIC" if public_item is not None else "HISTORICAL_ONLY"
            expected_current_trade = {
                "trade_sequence": int(trade.get("trade_sequence") or 0),
                "entry_signal_date": day(trade.get("entry_signal_date")),
                "entry_execution_date": entry_day,
            }
            for source_name, source_item in (("status", public_item), ("monitor", monitor_item)):
                if source_item is None:
                    if source_name == "status" and visibility == "PUBLIC":
                        item_monitor_mismatches.append({"key": key, "source": source_name, "field": "missing_public_item"})
                    continue
                if source_item.get("action") != "HOLD" or source_item.get("canonical_position") != "OPEN" or source_item.get("action_reason") != "POSITION_OPEN_PATTERN_B_NOT_NORMAL":
                    item_monitor_mismatches.append({"key": key, "source": source_name, "field": "open_action_or_reason"})
                actual_trade = source_item.get("current_trade") or {}
                if any(not equal(actual_trade.get(field), value) for field, value in expected_current_trade.items()):
                    item_monitor_mismatches.append({"key": key, "source": source_name, "field": "current_trade_identity"})

            local_state = {r["evaluation_date"]: r for r in local_evaluations}
            open_rows.append({
                "ticker": ticker, "name": trade.get("name"), "isu_cd": isu_cd,
                "market": str(trade.get("market", "")).upper(), "visibility": visibility,
                "trade_sequence": int(trade.get("trade_sequence") or 0),
                "entry_signal_date": day(trade.get("entry_signal_date")),
                "entry_execution_date": entry_day, "entry_price": entry_open,
                "repository_entry_open": repo_entry_open,
                "last_evaluation_date": REFERENCE, "last_close": close,
                "current_return_pct": return_pct, "canonical_return_pct": trade.get("return_pct"),
                "state_2026_10_06": local_state[SESSION_DATES[0]]["state"],
                "evaluation_status_2026_10_06": local_state[SESSION_DATES[0]]["evaluation_status"],
                "state_2026_10_07": local_state[SESSION_DATES[1]]["state"],
                "evaluation_status_2026_10_07": local_state[SESSION_DATES[1]]["evaluation_status"],
                "state_2026_10_08": local_state[SESSION_DATES[2]]["state"],
                "evaluation_status_2026_10_08": local_state[SESSION_DATES[2]]["evaluation_status"],
                "normal_signal_dates": json.dumps(normal_dates),
                "exit_condition_met": bool(normal_dates),
                "next_action": "EXIT_PENDING" if REFERENCE in normal_dates else "EXIT_REQUIRED" if normal_dates else "HOLD",
                "source_authority": "MarketDataRepositoryV2 + official Pattern B evaluator",
                "evaluation_validation": "READY" if all(r["evaluation_status"] == "READY" for r in local_evaluations) else "CHECK_REQUIRED",
                "monthly_evidence_dates": json.dumps(sorted({r["monthly_last_bar"] for r in local_evaluations})),
                "weekly_evidence_dates": json.dumps(sorted({r["weekly_last_bar"] for r in local_evaluations})),
                "pit_segment_from": day(active.get("effective_from")),
                "pit_segment_to": day(active.get("effective_to")),
                "pit_identity_active_all_sessions": all(
                    any(norm_ticker(iv.get("ticker")) == ticker and norm_isu(iv.get("isu_cd")) == isu_cd and str(iv.get("state", "")).upper() == "COMMON" and day(iv.get("effective_from")) <= d <= day(iv.get("effective_to")) for iv in intervals)
                    for d in SESSION_DATES
                ),
            })
        except Exception as exc:
            open_evaluation_errors.append({"key": key, "error": f"{type(exc).__name__}:{exc}"})

    bucket_counts = Counter(str(r.get("bucket")) for r in public_items)
    status_counts = current.get("counts") or {}
    recomputed_counts = {name: int(bucket_counts.get(name, 0)) for name in ("entry", "hold", "exit", "watch", "unavailable")}
    status_count_mismatches = {name: (status_counts.get(name), recomputed_counts[name]) for name in recomputed_counts if int(status_counts.get(name, -1)) != recomputed_counts[name]}
    monitor_count_mismatches = {name: (monitor_strategy.get("counts", {}).get(name), recomputed_counts[name]) for name in recomputed_counts if int(monitor_strategy.get("counts", {}).get(name, -1)) != recomputed_counts[name]}
    status_key_missing_monitor = sorted(public_key_set - monitor_key_set)
    monitor_key_extra = sorted(monitor_key_set - public_key_set)
    status_key_missing_index = sorted(public_key_set - index_key_set)
    index_key_extra = sorted(index_key_set - public_key_set)
    exact_old_new_trade_keys_equal = Counter(prior_trade_keys) == Counter(current_trade_keys)
    old_open_new_open_exact = Counter(old_keys) == Counter(current_keys) == Counter(canonical_open_keys)
    history_identity_count = len({(norm_ticker(r.get("ticker")), norm_isu(r.get("isu_cd"))) for r in current_rows})
    hidden_identity_count = len({(norm_ticker(r.get("ticker")), norm_isu(r.get("isu_cd"))) for r in current_rows if (norm_ticker(r.get("ticker")), norm_isu(r.get("isu_cd"))) not in public_key_set})
    exclusion_open_leaks = sorted(open_identity_set & exclusions)

    prior_audit_open_keys = {
        (norm_ticker(r.get("ticker")), norm_isu(r.get("isu_cd")), int(r.get("trade_sequence") or 0), day(r.get("entry_signal_date")), day(r.get("entry_execution_date")))
        for r in prior_audit_rows if r.get("trade_status") == "OPEN_AT_REFERENCE"
    }
    prior_audit_open_coverage = len(set(old_keys) & prior_audit_open_keys)
    prior_audit_checks = prior_audit_summary.get("checks") or {}

    required_open_pass = (
        len(canonical_open_rows) == 37 and len(open_rows) == 37 and not open_evaluation_errors
        and not active_identity_errors and not entry_price_mismatches and not close_missing
        and not return_mismatches and not first_normal_execution_issues
        and all(state_counts[d].get("UNAVAILABLE", 0) == 0 for d in SESSION_DATES)
    )
    severe_data_issues = bool(
        not old_open_new_open_exact or realized_mutations or not exact_old_new_trade_keys_equal
        or monitor_trade_mismatches or item_monitor_mismatches or report_identity_mismatches
        or report_eval_mismatches or report_market_mismatches or report_price_mismatches
        or status_count_mismatches or monitor_count_mismatches or status_key_missing_monitor
        or monitor_key_extra or status_key_missing_index or index_key_extra or exclusion_open_leaks
        or unavailable_open_rows or open_identities_in_unavailable
    )
    prior_audit_pass = (
        prior_audit_summary.get("status") == "B_SELECT_CORE_V02_TRADE_HISTORY_AUDIT_PASS"
        and int(prior_audit_checks.get("current_open_executable_normal_exit_missing", -1)) == 0
        and int(prior_audit_checks.get("pending_exit_events", -1)) == 0
        and prior_audit_open_coverage == 37
    )
    pass_status = "PASS" if required_open_pass and not severe_data_issues and prior_audit_pass else "CHECK_REQUIRED"
    severity = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0}
    if first_normal_execution_issues:
        severity["CRITICAL"] += len(first_normal_execution_issues)
    if open_evaluation_errors or active_identity_errors or close_missing or any(state_counts[d].get("UNAVAILABLE", 0) for d in SESSION_DATES):
        severity["MAJOR"] += len(open_evaluation_errors) + len(active_identity_errors) + len(close_missing) + sum(state_counts[d].get("UNAVAILABLE", 0) for d in SESSION_DATES)
    if severe_data_issues and severity["CRITICAL"] == 0 and severity["MAJOR"] == 0:
        severity["MAJOR"] = 1
    if not prior_audit_pass and severity["CRITICAL"] == 0:
        severity["MAJOR"] += 1

    merged_pit_path = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
    merged_calendar_path = ROOT / "data/market/rolling_authority/merged_trading_calendar.json"
    manifest_path = ROOT / "data/market/rolling_authority/manifest.json"
    source_paths = [
        PRIOR_STATUS, CURRENT_STATUS, PRIOR_AUDIT / "report.md", PRIOR_AUDIT / "summary.json", prior_audit_rows_path,
        MONITOR, STOCK_INDEX, merged_pit_path, merged_calendar_path, manifest_path,
        ROOT / "docs/patterns/pattern_b/strategy/PATTERN_B_SELECT_CORE_V02.md",
        ROOT / "docs/validation/backtest_common_rules.md",
        ROOT / "scripts/build_b_select_core_v2_status.py", ROOT / "scripts/export_strategy_monitor_web.py",
        ROOT / "scripts/audit_b_select_core_v2_trade_history_v01.py",
        ROOT / "scripts/run_pattern_b_pure_simple_backtest_v01.py",
        ROOT / "src/trend_scanner/data/repository_v2.py", ROOT / "src/trend_scanner/data/repository_v2_loader.py",
        ROOT / "src/trend_scanner/data/market_calendar.py", ROOT / "src/trend_scanner/patterns/pattern_b_operational.py",
        ROOT / "src/trend_scanner/patterns/pattern_b_evaluator.py", ROOT / "src/trend_scanner/patterns/pattern_b_features_v01.py",
        ROOT / "src/trend_scanner/patterns/pattern_b_state_v02.py",
    ]
    source_manifest = [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)} for p in source_paths]
    write_csv(OUT / "source_manifest.csv", source_manifest)
    write_csv(OUT / "public_report_sha256.csv", public_report_hashes)
    write_csv(OUT / "public_status_audit.csv", public_report_audit)
    write_csv(OUT / "unavailable_status_audit.csv", unavailable_rows)
    write_csv(OUT / "canonical_trade_parity.csv", [
        {
            "ticker": position_key(r)[0], "isu_cd": position_key(r)[1], "trade_sequence": position_key(r)[2],
            "entry_signal_date": position_key(r)[3], "entry_execution_date": position_key(r)[4],
            "prior_status": prior_by_key.get(position_key(r), {}).get("trade_status"),
            "current_status": r.get("trade_status"),
            "prior_realized_unchanged": position_key(r) not in prior_realized_by_key or (position_key(r) in current_by_key and current_by_key[position_key(r)] == prior_realized_by_key[position_key(r)]),
            "monitor_trade_present": position_key(r) in monitor_trade_by_key,
            "monitor_trade_status": monitor_trade_by_key.get(position_key(r), {}).get("trade_status"),
        } for r in current_rows
    ])
    write_csv(OUT / "open_positions.csv", open_rows)
    write_csv(OUT / "open_session_evaluations.csv", session_rows)

    merged_calendar = read_json(merged_calendar_path)
    merged_pit = read_json(merged_pit_path)
    authority_manifest = read_json(manifest_path)
    prior_audit_sha = {p.name: sha256(p) for p in [PRIOR_AUDIT / "report.md", PRIOR_AUDIT / "summary.json", prior_audit_rows_path]}
    source_hashes = {row["path"]: row["sha256"] for row in source_manifest}
    summary = {
        "work_id": "B_SELECT_CORE_V2_20261011_EXIT_AND_CURRENT_STATUS_AUDIT_V01",
        "status": pass_status,
        "severity_counts": severity,
        "requested_as_of": REQUESTED_AS_OF,
        "reference_market_date": REFERENCE,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "origin_main": subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
        "source_hashes": source_hashes,
        "prior_sealed_full_audit": {
            "status": prior_audit_summary.get("status"),
            "sha256": prior_audit_sha,
            "current_open_executable_normal_exit_missing": prior_audit_checks.get("current_open_executable_normal_exit_missing"),
            "current_open_latest_valuation_missing": prior_audit_checks.get("current_open_latest_valuation_missing"),
            "current_open_latest_valuation_mismatch": prior_audit_checks.get("current_open_latest_valuation_mismatch"),
            "pending_exit_events": prior_audit_checks.get("pending_exit_events"),
            "open_key_coverage": f"{prior_audit_open_coverage}/37",
        },
        "authorities": {
            "pit_frontier": merged_pit.get("pit_frontier"),
            "pit_content_digest": merged_pit.get("content_digest"),
            "calendar_frontier": merged_calendar.get("calendar_frontier"),
            "calendar_content_digest": merged_calendar.get("content_digest"),
            "manifest_certified_through": authority_manifest.get("certified_through"),
            "manifest_sha256": authority_manifest.get("manifest_sha256"),
            "sessions": SESSION_DATES,
            "exact_sessions_confirmed": {d: d in calendar_set for d in SESSION_DATES},
            "2026-10-09_in_calendar": "2026-10-09" in calendar_set,
            "2026-10-10_in_calendar": "2026-10-10" in calendar_set,
            "2026-10-11_in_calendar": "2026-10-11" in calendar_set,
            "first_calendar_session_after_reference": next((d for d in calendar_dates if d > REFERENCE), None),
            "future_prices_queried": False,
        },
        "canonical_history": {
            "prior_rows": len(prior_rows), "current_rows": len(current_rows),
            "prior_realized_rows": len(prior_realized_by_key),
            "current_realized_rows": sum(r.get("trade_status") == "REALIZED" for r in current_rows),
            "prior_open_rows": len(prior_open), "current_open_rows": len(current_open),
            "canonical_open_projection_rows": len(canonical_open_rows),
            "exact_key_set_equal": exact_old_new_trade_keys_equal,
            "open_keys_1_to_1_equal": old_open_new_open_exact,
            "realized_mutations": len(realized_mutations),
            "unique_current_identities": history_identity_count,
            "historical_only_identity_count": hidden_identity_count,
            "canonical_pending_events": len(current.get("canonical_pending_events") or []),
            "permanent_identity_exclusion_pairs": len(exclusions),
            "open_exclusion_leakage": len(exclusion_open_leaks),
        },
        "open_exit_audit": {
            "positions_expected": 37, "positions_evaluated": len(open_rows),
            "session_evaluations_expected": 111, "session_evaluations_completed": len(session_rows),
            "evaluation_errors": len(open_evaluation_errors),
            "active_identity_errors": len(active_identity_errors),
            "entry_price_mismatches": len(entry_price_mismatches),
            "reference_close_missing": len(close_missing),
            "return_mismatches": len(return_mismatches),
            "first_normal_signals": len(normal_signals),
            "pending_exit_events": sum(str(e.get("kind") or e.get("event_type") or "").upper() == "EXIT" for e in current.get("canonical_pending_events") or []),
            "exit_signal_or_pending_issues": len(first_normal_execution_issues),
            "state_counts_by_date": {d: {state: state_counts[d].get(state, 0) for state in ["NORMAL", "DEPRESSED", "DEEP_DEPRESSED", "OVERHEATED", "EXTREME_OVERHEATED", "UNAVAILABLE"]} for d in SESSION_DATES},
            "current_open_visibility": {"public": len(open_rows) - len(hidden_open_rows), "historical_only": len(hidden_open_rows)},
            "open_key_coverage_in_prior_full_audit": f"{prior_audit_open_coverage}/37",
            "prior_full_audit_missed_exits_through_2026_10_02": prior_audit_checks.get("current_open_executable_normal_exit_missing"),
            "next_session_after_reference_known_in_certified_calendar": next((d for d in calendar_dates if d > REFERENCE), None),
        },
        "public_universe": {
            "status_count": current.get("count"), "status_item_count": len(public_items),
            "status_recomputed_counts": recomputed_counts, "status_declared_counts": status_counts,
            "monitor_item_count": len(monitor_items), "monitor_counts": monitor_strategy.get("counts"),
            "stock_index_current_common_count": len(current_index),
            "stock_reports_hashed": len(public_report_hashes),
            "bucket_denominator_sum": sum(recomputed_counts.values()),
            "data_status_counts": dict(Counter(str(r.get("data_status")) for r in public_items)),
            "action_counts": dict(Counter(str(r.get("action")) for r in public_items)),
            "unavailable_reason_counts": dict(Counter(str(r.get("action_reason")) for r in public_items if r.get("bucket") == "unavailable")),
            "permanent_exclusion_count": sum(bool(r.get("permanent_identity_excluded")) for r in public_items),
            "open_in_unavailable_bucket": len(unavailable_open_rows) + len(open_identities_in_unavailable),
            "pattern_b_report_evaluation_status_counts": dict(report_pattern_status_counts),
            "stock_report_availability_counts": dict(report_availability_counts),
            "pattern_b_unavailable_reason_counts": dict(b_unavailable_reason_counts),
            "monitor_item_mismatches": len(item_monitor_mismatches),
            "report_identity_mismatches": len(report_identity_mismatches),
            "report_evaluation_mismatches": len(report_eval_mismatches),
            "report_market_mismatches": len(report_market_mismatches),
            "report_price_mismatches": len(report_price_mismatches),
            "status_count_mismatches": status_count_mismatches,
            "monitor_count_mismatches": monitor_count_mismatches,
            "status_monitor_key_delta": {"missing_in_monitor": len(status_key_missing_monitor), "extra_in_monitor": len(monitor_key_extra)},
            "status_index_key_delta": {"missing_in_index": len(status_key_missing_index), "extra_in_index": len(index_key_extra)},
        },
        "monitor_trade_parity": {
            "current_trade_history_rows": len(current_rows), "monitor_trade_history_rows": len(monitor_trades),
            "monitor_trade_key_count": len(monitor_trade_by_key),
            "field_mismatches": len(monitor_trade_mismatches),
        },
        "diagnostic_examples": {
            "open_evaluation_errors": open_evaluation_errors[:10],
            "active_identity_errors": active_identity_errors[:10],
            "entry_price_mismatches": entry_price_mismatches[:10],
            "reference_close_missing": close_missing[:10],
            "return_mismatches": return_mismatches[:10],
            "exit_issues": first_normal_execution_issues[:10],
            "realized_mutations": realized_mutations[:10],
            "monitor_trade_mismatches": monitor_trade_mismatches[:10],
            "item_monitor_mismatches": item_monitor_mismatches[:10],
            "report_identity_mismatches": report_identity_mismatches[:10],
            "report_eval_mismatches": report_eval_mismatches[:10],
            "report_market_mismatches": report_market_mismatches[:10],
            "report_price_mismatches": report_price_mismatches[:10],
            "excluded_open_keys": exclusion_open_leaks[:10],
        },
        "network_requests": 0,
        "production_or_data_mutations": 0,
    }
    write_json(OUT / "summary.json", summary)
    print(json.dumps({
        "status": pass_status,
        "severity": severity,
        "open_positions": len(open_rows),
        "evaluations": len(session_rows),
        "states": summary["open_exit_audit"]["state_counts_by_date"],
        "public": summary["public_universe"]["status_recomputed_counts"],
        "mismatches": {k: summary["public_universe"][k] for k in [
            "monitor_item_mismatches", "report_identity_mismatches", "report_evaluation_mismatches",
            "report_market_mismatches", "report_price_mismatches",
        ]},
    }, ensure_ascii=False, indent=2))
    return 0 if pass_status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
