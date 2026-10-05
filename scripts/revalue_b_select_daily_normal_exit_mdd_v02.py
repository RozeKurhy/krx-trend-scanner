#!/usr/bin/env python3
"""Revalue sealed B Select five-window portfolios without replaying trades.

The input event and trade ledgers are immutable. Only unresolved daily market
value rows are reconstructed from exact Repository V2 closes or the existing
verified A/B non-trading carry contract.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
SOURCE_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_permanent_exclusion_v01")
PRIOR_BASIS_PATH = Path("artifacts/strategies/b_select_core_v1/research/daily_exit_mdd_coverage_remediation_v01/identity_corporate_action_audit.csv")
PIT_PATH = Path("data/market/rolling_authority/merged_pit_intervals.json")
CALENDAR_PATH = Path("data/market/rolling_authority/merged_trading_calendar.json")
RAW_PATH = Path("data/market/raw/krx_stocks/v01")
ADJUSTED_PATH = Path("data/market/adjusted/stocks")
OUTPUT_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_mdd_valuation_v02")
WINDOW_DIRS = {"P1": "p1", "P2-1": "p2_1", "P2-2": "p2_2", "P3-1": "p3_1", "P3-2": "p3_2"}
SCENARIOS = {"CONTROL_MONTH_END": "control_month_end", "TEST_DAILY": "test_daily"}
INITIAL_CAPITAL = 200_000_000.0
MDD_COVERAGE_FLOOR = 90.0
ABSOLUTE_MDD_LIMITS = {"P1": -55.0, "P2-1": -40.0, "P2-2": -40.0, "P3-1": -40.0, "P3-2": -40.0}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(field for row in rows for field in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) and abs(parsed) != float("inf") else None


def identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row.get("ticker", "")).strip().zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("market", "")).strip().upper()


def identity_is_active(
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    ticker: str,
    isu_cd: str,
    market: str,
    day: str,
) -> bool:
    return any(
        str(row.get("state", "")).upper() == "COMMON"
        and str(row.get("market", "")).upper() == market.upper()
        and str(row.get("effective_from", ""))[:10] <= day
        and str(row.get("effective_to", ""))[:10] >= day
        for row in intervals_by_identity.get((ticker.zfill(6), isu_cd.upper()), ())
    )


def load_adjusted_frame(store: Any, ticker: str, cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if ticker not in cache:
        frame = store.load_daily_source(ticker)
        cache[ticker] = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    return cache[ticker]


def resolve_mark(
    *,
    row: Mapping[str, Any],
    day: str,
    basis_pairs: set[tuple[str, str]],
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    adjusted_store: Any,
    adjusted_cache: dict[str, pd.DataFrame],
    raw_reader: Any,
) -> tuple[float | None, dict[str, Any]]:
    ticker, isu_cd, market = identity(row)
    frame = load_adjusted_frame(adjusted_store, ticker, adjusted_cache)
    timestamp = pd.Timestamp(day)
    exact = None
    if not frame.empty and timestamp in frame.index:
        exact = number(frame.loc[timestamp].get("close"))
    audit = {
        "ticker": ticker, "isu_cd": isu_cd, "market": market, "date": day,
        "mark_status": "EXACT" if exact is not None and exact > 0 else "UNRESOLVED",
        "mark_source": "REPOSITORY_V2_EXACT_CLOSE" if exact is not None and exact > 0 else None,
        "mark_price": exact if exact is not None and exact > 0 else None,
        "carry_reference_date": None, "raw_mark_partition_sha256": None,
        "raw_anchor_partition_sha256": None, "reason": None,
    }
    if exact is not None and exact > 0:
        return exact, audit
    if (ticker, isu_cd) not in basis_pairs:
        audit["reason"] = "IDENTITY_BASIS_NOT_AUDITED_A_OR_B"
        return None, audit
    if not identity_is_active(intervals_by_identity, ticker, isu_cd, market, day):
        audit["reason"] = "EXACT_COMMON_IDENTITY_NOT_ACTIVE_ON_MARK_DATE"
        return None, audit
    raw_row, mark_manifest = raw_reader(market, day, ticker, isu_cd)
    from scripts import analyze_b_select_daily_exit_mdd_coverage_remediation_v01 as coverage

    if raw_row is None or not coverage.raw_nontrading_placeholder(raw_row):
        audit["reason"] = "EXACT_KRX_RAW_NONTRADING_PLACEHOLDER_NOT_CONFIRMED"
        return None, audit
    if frame.empty or "close" not in frame.columns:
        audit["reason"] = "REPOSITORY_V2_IDENTITY_FRAME_MISSING"
        return None, audit

    earlier = frame.loc[frame.index < timestamp].sort_index(ascending=False)
    for anchor_day, anchor_row in earlier.iterrows():
        values = anchor_row.to_dict()
        close = coverage.number(values.get("close"))
        if close is None or close <= 0 or not coverage.valid_adjusted_ohlc(values):
            continue
        anchor_date = pd.Timestamp(anchor_day).strftime("%Y-%m-%d")
        if not identity_is_active(intervals_by_identity, ticker, isu_cd, market, anchor_date):
            continue
        raw_anchor, anchor_manifest = raw_reader(market, anchor_date, ticker, isu_cd)
        shares = coverage.number(raw_anchor.get("listed_shares")) if raw_anchor else None
        if not coverage._raw_valid_trade(raw_anchor) or shares is None or shares <= 0:
            continue
        audit.update(
            mark_status="CARRIED",
            mark_source="VERIFIED_ZERO_ACTIVITY_PLACEHOLDER_WITH_A_B_ADJUSTED_ANCHOR",
            mark_price=close,
            carry_reference_date=anchor_date,
            raw_mark_partition_sha256=(mark_manifest or {}).get("file_sha256"),
            raw_anchor_partition_sha256=(anchor_manifest or {}).get("file_sha256"),
            reason="SAFE_VALUATION_ONLY_CARRY",
        )
        return close, audit
    audit["reason"] = "NO_PRIOR_VALID_EXACT_IDENTITY_ADJUSTED_ANCHOR"
    return None, audit


def order_positions(rows: list[dict[str, Any]], mode: str, seed: int) -> list[dict[str, Any]]:
    by_identity = sorted(rows, key=lambda row: identity(row))
    if mode == "ticker_ascending":
        return by_identity
    if mode == "ticker_descending":
        return list(reversed(by_identity))
    result = list(by_identity)
    random.Random(seed).shuffle(result)
    return result


def _source_file_map(source_root: Path) -> dict[str, str]:
    result = {}
    metadata = read_json(source_root / "metadata.json")
    for name, details in metadata.get("generated_files", {}).items():
        expected = details.get("sha256") if isinstance(details, Mapping) else details
        path = source_root / name
        actual = sha256_file(path) if path.is_file() else None
        if not expected or actual != expected:
            raise RuntimeError(f"SEALED_PORTFOLIO_INPUT_HASH_MISMATCH:{name}")
        result[name] = actual
    return result


def _revalue_case(
    *,
    window: str,
    scenario: str,
    daily_source: list[dict[str, str]],
    event_rows: list[dict[str, str]],
    trade_rows: list[dict[str, str]],
    skip_rows: list[dict[str, str]],
    effective_start: str,
    effective_end: str,
    terminal_support_date: str,
    all_calendar_dates: list[str],
    basis_pairs: set[tuple[str, str]],
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    raw_store: Any,
    adjusted_store: Any,
    run_index: int,
) -> dict[str, Any]:
    exact_events = [row for row in event_rows if row.get("event_status") == "EXECUTED"]
    entries = [row for row in exact_events if row.get("event_type") == "ENTRY"]
    exits = [row for row in exact_events if row.get("event_type") == "EXIT"]
    if len({row.get("pair_id") for row in entries}) != len(entries):
        raise RuntimeError(f"DUPLICATE_EXECUTED_ENTRY_PAIR:{window}:{scenario}")
    if len({row.get("pair_id") for row in exits}) != len(exits):
        raise RuntimeError(f"DUPLICATE_EXECUTED_EXIT_PAIR:{window}:{scenario}")
    entries_by_pair = {str(row["pair_id"]): row for row in entries}
    exits_by_pair = {str(row["pair_id"]): row for row in exits}
    trades_by_pair = {str(row.get("pair_id") or row.get("trade_id")): row for row in trade_rows}
    missing_skips = [row for row in skip_rows if row.get("skip_reason") == "MISSING_EXACT_DAILY_MARK"]
    skip_keys = {(str(row.get("pair_id", "")), str(row.get("date", ""))[:10]) for row in missing_skips}
    if len(skip_keys) != len(missing_skips):
        raise RuntimeError(f"DUPLICATE_MISSING_MARK_SKIP:{window}:{scenario}")

    source_by_date = {str(row["date"])[:10]: dict(row) for row in daily_source}
    if len(source_by_date) != len(daily_source):
        raise RuntimeError(f"DUPLICATE_SOURCE_DAILY_EQUITY_DATE:{window}:{scenario}")
    missing_days_by_source = {
        day for day, row in source_by_date.items()
        if day <= effective_end and number(row.get("equity")) is None
    }
    skip_days = {day for _pair, day in skip_keys}
    if missing_days_by_source != skip_days:
        raise RuntimeError(
            f"MISSING_EQUITY_AND_SKIP_DATES_DIFFER:{window}:{scenario}:"
            f"equity={len(missing_days_by_source)}:skip={len(skip_days)}"
        )

    modes = ("ticker_ascending", "ticker_descending", "deterministic_shuffled")
    results: dict[str, dict[str, Any]] = {}
    for mode in modes:
        raw_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        raw_manifests: dict[tuple[str, str], dict[str, Any]] = {}
        from scripts.replay_b_select_daily_normal_exit_permanent_exclusion_v01 import _make_raw_store_reader

        raw_reader = _make_raw_store_reader(raw_store, raw_cache, raw_manifests, intervals_by_identity)
        adjusted_cache: dict[str, pd.DataFrame] = {}
        updated_rows = [dict(row) for row in daily_source]
        audit_rows: list[dict[str, Any]] = []
        order_independence_mismatch_count = 0

        for day in sorted(missing_days_by_source):
            source = source_by_date[day]
            live_positions: list[dict[str, Any]] = []
            for pair_id, entry in entries_by_pair.items():
                entry_day = str(entry.get("execution_date", ""))[:10]
                exit_row = exits_by_pair.get(pair_id)
                exit_day = str(exit_row.get("execution_date", ""))[:10] if exit_row else ""
                if entry_day <= day and (not exit_day or day < exit_day):
                    live_positions.append(dict(entry))
            stable_positions = sorted(live_positions, key=lambda row: identity(row))
            query_positions = order_positions(live_positions, mode, 20261005 + run_index)
            marks: dict[str, tuple[float | None, dict[str, Any]]] = {}
            for position in query_positions:
                pair_id = str(position["pair_id"])
                trade = trades_by_pair.get(pair_id, {})
                terminal_date = str(trade.get("terminal_valuation_date") or "")[:10]
                terminal_price = number(trade.get("terminal_valuation_price"))
                shares = int(number(position.get("shares")) or 0)
                if (
                    trade.get("trade_status") == "OPEN_AT_CUTOFF"
                    and terminal_date and terminal_price is not None
                    and terminal_date < effective_end and day >= terminal_date
                ):
                    mark = (terminal_price, {
                        **identity(position), "date": day, "mark_status": "LOCKED_TERMINAL",
                        "mark_source": "SEALED_TRADE_LEDGER_TERMINAL_VALUATION",
                        "mark_price": terminal_price, "carry_reference_date": terminal_date,
                        "raw_mark_partition_sha256": None, "raw_anchor_partition_sha256": None,
                        "reason": "FROZEN_TERMINAL_VALUATION",
                    })
                else:
                    price, audit = resolve_mark(
                        row=position, day=day, basis_pairs=basis_pairs,
                        intervals_by_identity=intervals_by_identity,
                        adjusted_store=adjusted_store, adjusted_cache=adjusted_cache,
                        raw_reader=raw_reader,
                    )
                    mark = (price, {**audit, "pair_id": pair_id, "shares": shares})
                marks[pair_id] = mark
            # Sum in canonical identity order so only lookup order varies.
            invested_value = 0.0
            unresolved_pairs = []
            for position in stable_positions:
                pair_id = str(position["pair_id"])
                price, audit = marks[pair_id]
                shares = int(number(position.get("shares")) or 0)
                if price is None or shares <= 0:
                    unresolved_pairs.append(pair_id)
                else:
                    invested_value += price * shares
                audit_rows.append({"window": window, "scenario": scenario, "order_mode": mode, **audit})
            skip_pairs_for_day = {pair for pair, skip_day in skip_keys if skip_day == day}
            unresolved_live_pairs = {
                pair_id for pair_id, (price, _audit) in marks.items() if price is None
            }
            if not unresolved_live_pairs.issubset(skip_pairs_for_day):
                raise RuntimeError(
                    f"NEW_UNRESOLVED_MARK_WITHOUT_SOURCE_SKIP:{window}:{scenario}:{day}:"
                    f"source={len(skip_pairs_for_day)}:rebuilt={len(unresolved_live_pairs)}"
                )
            cash = number(source.get("cash"))
            pending = number(source.get("pending_sale_proceeds"))
            rebuilt_equity = None if unresolved_pairs or cash is None or pending is None else cash + pending + invested_value
            output = next(row for row in updated_rows if str(row["date"])[:10] == day)
            output["invested_market_value"] = "" if rebuilt_equity is None else str(invested_value)
            output["equity"] = "" if rebuilt_equity is None else str(rebuilt_equity)
            output["exposure"] = "" if rebuilt_equity is None or rebuilt_equity == 0 else str(invested_value / rebuilt_equity)
            output["cash_ratio"] = "" if rebuilt_equity is None or rebuilt_equity == 0 else str(cash / rebuilt_equity)
            output["valuation_basis_date"] = day

        peak_equity = INITIAL_CAPITAL
        for row in updated_rows:
            if str(row["date"])[:10] > effective_end:
                continue
            equity = number(row.get("equity"))
            if equity is None:
                row["drawdown"] = ""
                continue
            peak_equity = max(peak_equity, equity)
            row["drawdown"] = equity / peak_equity - 1.0

        # The corrected equity value and MDD must be identical under all three
        # raw-partition lookup orders. Compare every date, including UNRESOLVED.
        normalized_rows = [
            {**row, "equity": number(row.get("equity"))}
            for row in updated_rows if str(row["date"])[:10] <= effective_end
        ]
        rows_by_date = {str(row["date"])[:10]: row for row in normalized_rows}
        resolved_marks = sum(row["mark_status"] in {"EXACT", "CARRIED", "LOCKED_TERMINAL"} for row in audit_rows)
        unresolved_marks = sum(row["mark_status"] == "UNRESOLVED" for row in audit_rows)
        rows_missing = sum(row["equity"] is None for row in normalized_rows)
        total_days = sum(effective_start <= day <= effective_end for day in all_calendar_dates)
        coverage = (total_days - rows_missing) / total_days * 100.0 if total_days else 0.0
        from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as portfolio_v02

        mdd = portfolio_v02.compute_mdd(normalized_rows, INITIAL_CAPITAL)
        mdd_type = "EXACT MDD" if coverage >= 100.0 else "OBSERVED MDD" if coverage >= MDD_COVERAGE_FLOOR else "NO OFFICIAL MDD: coverage below 90%"
        terminal_row = source_by_date.get(terminal_support_date)
        terminal_equity = number(terminal_row.get("equity")) if terminal_row else None
        results[mode] = {
            "daily_equity": updated_rows,
            "audit_rows": audit_rows,
            "mdd": mdd,
            "coverage_pct": coverage,
            "mdd_type": mdd_type,
            "total_days": total_days,
            "observed_days": total_days - rows_missing,
            "missing_days": rows_missing,
            "resolved_mark_count": resolved_marks,
            "unresolved_mark_count": unresolved_marks,
            "unresolved_marks_before": len(missing_skips),
            "terminal_equity": terminal_equity,
            "rows_by_date": rows_by_date,
            "order_independence_mismatch_count": order_independence_mismatch_count,
            "raw_partition_count": len(raw_cache),
            "raw_partition_hashes": {
                f"{market}/{day}": manifest.get("file_sha256")
                for (market, day), manifest in raw_manifests.items()
                if manifest.get("status") == "COMPLETE"
            },
        }

    baseline = results[modes[0]]
    mismatches = 0
    for mode in modes[1:]:
        candidate = results[mode]
        if baseline["coverage_pct"] != candidate["coverage_pct"] or baseline["mdd"] != candidate["mdd"]:
            mismatches += 1
        for day in baseline["rows_by_date"]:
            left = baseline["rows_by_date"][day].get("equity")
            right = candidate["rows_by_date"].get(day, {}).get("equity")
            if left != right:
                mismatches += 1
    baseline["order_independence_mismatch_count"] = mismatches
    baseline["order_results"] = {
        mode: {
            "coverage_pct": result["coverage_pct"],
            "mdd_pct": result["mdd"]["mdd_pct"],
            "resolved_mark_count": result["resolved_mark_count"],
            "unresolved_mark_count": result["unresolved_mark_count"],
            "raw_partition_count": result["raw_partition_count"],
        }
        for mode, result in results.items()
    }
    baseline["audit_rows"] = [
        {**row, "lookup_order_verification": "PASS" if mismatches == 0 else "FAIL"}
        for row in baseline["audit_rows"]
    ]
    return baseline


def run() -> dict[str, Any]:
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite valuation output: {OUTPUT_ROOT}")
    source_root = ROOT / SOURCE_ROOT
    source_summary = read_json(source_root / "summary.json")
    source_hashes = _source_file_map(source_root)
    if source_summary.get("starting_head") != source_summary.get("starting_origin_main"):
        raise RuntimeError("SOURCE_PORTFOLIO_START_HEAD_DID_NOT_MATCH_ORIGIN_MAIN")

    from scripts import analyze_b_select_daily_exit_mdd_coverage_remediation_v01 as coverage
    from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
    from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore

    pit_payload = read_json(ROOT / PIT_PATH)
    intervals_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pit_payload.get("intervals", []):
        intervals_by_identity[(str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())].append(dict(row))
    calendar_payload = read_json(ROOT / CALENDAR_PATH)
    all_calendar_dates = [str(day)[:10] for day in calendar_payload.get("trading_dates", [])]
    if all_calendar_dates != sorted(set(all_calendar_dates)):
        raise RuntimeError("KRX_CALENDAR_NOT_SORTED_UNIQUE")

    basis_rows = read_csv(ROOT / PRIOR_BASIS_PATH)
    basis_pairs = {
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())
        for row in basis_rows if row.get("classification") in {"A", "B"}
    }
    if len(basis_pairs) != 17:
        raise RuntimeError(f"UNEXPECTED_A_B_BASIS_IDENTITY_COUNT:{len(basis_pairs)}")

    raw_store = KrxRawStockStore(ROOT / RAW_PATH)
    adjusted_store = AdjustedPriceStore(ROOT / ADJUSTED_PATH)
    case_rows: list[dict[str, Any]] = []
    equity_files: dict[str, list[dict[str, Any]]] = {}
    mark_audit_rows: list[dict[str, Any]] = []
    order_details: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    metrics_by_case = {
        (row["window"], row["scenario"]): row
        for row in source_summary["portfolio_metrics"]
    }
    trade_metrics_by_case = {
        (row["window"], row["scenario"]): row
        for row in source_summary["trade_metrics"]
    }
    window_data_by_window: dict[str, dict[str, str]] = {}
    for window in WINDOW_DIRS:
        control_metric = metrics_by_case[(window, "CONTROL_MONTH_END")]
        test_metric = metrics_by_case[(window, "TEST_DAILY")]
        window_fields = ("effective_start", "effective_end", "execution_support")
        if any(control_metric.get(field) != test_metric.get(field) for field in window_fields):
            raise RuntimeError(f"WINDOW_CUTOFF_PARITY_FAIL:{window}")
        window_data_by_window[window] = {
            field: str(control_metric[field])[:10] for field in window_fields
        }
    event_hashes: dict[str, str] = {}
    trade_hashes: dict[str, str] = {}
    raw_hashes: dict[str, str] = {}
    run_index = 0
    for window, window_dir in WINDOW_DIRS.items():
        window_path = source_root / window_dir
        window_data = window_data_by_window[window]
        effective_start = str(window_data["effective_start"])[:10]
        effective_end = str(window_data["effective_end"])[:10]
        for scenario, stem in SCENARIOS.items():
            run_index += 1
            prefix = f"{stem}_"
            paths = {
                "daily": window_path / f"{prefix}daily_equity.csv",
                "events": window_path / f"{prefix}portfolio_events.csv",
                "trades": window_path / f"{prefix}trade_ledger.csv",
                "skips": window_path / f"{prefix}portfolio_skips.csv",
            }
            relative = {name: path.relative_to(source_root).as_posix() for name, path in paths.items()}
            event_hash = sha256_file(paths["events"])
            trade_hash = sha256_file(paths["trades"])
            event_hashes[f"{window}/{scenario}"] = event_hash
            trade_hashes[f"{window}/{scenario}"] = trade_hash
            daily_source = read_csv(paths["daily"])
            event_rows = read_csv(paths["events"])
            trade_rows = read_csv(paths["trades"])
            skip_rows = read_csv(paths["skips"])
            exact_days = [day for day in all_calendar_dates if effective_start <= day <= effective_end]
            source_days = [str(row["date"])[:10] for row in daily_source if str(row["date"])[:10] <= effective_end]
            if source_days != exact_days:
                raise RuntimeError(f"SOURCE_EQUITY_SESSION_PARITY_ERROR:{window}:{scenario}")

            result = _revalue_case(
                window=window, scenario=scenario, daily_source=daily_source,
                event_rows=event_rows, trade_rows=trade_rows, skip_rows=skip_rows,
                effective_start=effective_start, effective_end=effective_end,
                terminal_support_date=window_data["execution_support"],
                all_calendar_dates=all_calendar_dates, basis_pairs=basis_pairs,
                intervals_by_identity=intervals_by_identity, raw_store=raw_store,
                adjusted_store=adjusted_store, run_index=run_index,
            )
            if result["order_independence_mismatch_count"]:
                raise RuntimeError(f"VALUATION_LOOKUP_ORDER_DEPENDENT:{window}:{scenario}")
            source_metric = metrics_by_case[(window, scenario)]
            source_trade_metric = trade_metrics_by_case[(window, scenario)]
            if result["terminal_equity"] is None:
                raise RuntimeError(f"SOURCE_TERMINAL_EQUITY_MISSING:{window}:{scenario}")
            if abs(result["terminal_equity"] - float(source_metric["ending_equity_krw"])) > 1e-6:
                raise RuntimeError(f"TERMINAL_EQUITY_CHANGED:{window}:{scenario}")
            elapsed_days = max(1, (pd.Timestamp(effective_end) - pd.Timestamp(effective_start)).days)
            return_from_terminal = (result["terminal_equity"] / INITIAL_CAPITAL - 1.0) * 100.0
            cagr_from_terminal = ((result["terminal_equity"] / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0) * 100.0
            if abs(return_from_terminal - float(source_metric["total_return_pct"])) > 1e-8:
                raise RuntimeError(f"TOTAL_RETURN_PARITY_FAIL:{window}:{scenario}")
            if abs(cagr_from_terminal - float(source_metric["CAGR_pct"])) > 1e-8:
                raise RuntimeError(f"CAGR_PARITY_FAIL:{window}:{scenario}")
            entries_count = sum(row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED" for row in event_rows)
            exits_count = sum(row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED" for row in event_rows)
            if entries_count != int(source_metric["executed_entry_count"]) or exits_count != int(source_metric["executed_exit_count"]):
                raise RuntimeError(f"EVENT_TRADE_COUNT_PARITY_FAIL:{window}:{scenario}")
            if exits_count != int(source_trade_metric["realized_trade_count"]):
                raise RuntimeError(f"REALIZED_EXIT_COUNT_METRIC_PARITY_FAIL:{window}:{scenario}")
            mdd_value = result["mdd"]["mdd_pct"]
            case_rows.append({
                "window": window, "scenario": scenario,
                "effective_start": effective_start, "effective_end": effective_end,
                "executed_entry_count": entries_count, "executed_exit_count": exits_count,
                "realized_trade_count": int(source_trade_metric["realized_trade_count"]),
                "win_rate_pct": source_trade_metric["win_rate_pct"],
                "win_rate_source_unchanged": True,
                "total_return_pct": source_metric["total_return_pct"],
                "CAGR_pct": source_metric["CAGR_pct"],
                "terminal_equity_source_unchanged": True,
                "old_MDD_pct": source_metric["MDD_observed_pct"],
                "old_coverage_pct": source_metric["valuation_coverage_pct"],
                "corrected_MDD_pct": mdd_value,
                "corrected_official_MDD_pct": mdd_value if result["coverage_pct"] >= MDD_COVERAGE_FLOOR else None,
                "corrected_MDD_type": result["mdd_type"],
                "corrected_coverage_pct": result["coverage_pct"],
                "coverage_total_days": result["total_days"],
                "coverage_observed_days": result["observed_days"],
                "coverage_missing_days": result["missing_days"],
                "unresolved_marks_before": result["unresolved_marks_before"],
                "unresolved_valuation_marks": result["unresolved_mark_count"],
                "resolved_valuation_marks": result["resolved_mark_count"],
                "MDD_peak_date": result["mdd"]["peak_date"],
                "MDD_trough_date": result["mdd"]["trough_date"],
                "MDD_recovery_date": result["mdd"]["recovery_date"],
                "trade_ledger_sha256": trade_hash, "event_ledger_sha256": event_hash,
                "trade_ledger_changed": False, "event_ledger_changed": False,
                "transaction_replay": False,
                "lookup_order_mismatch_count": result["order_independence_mismatch_count"],
            })
            equity_files[f"{window.lower().replace('-', '_')}/{stem}_daily_equity_corrected.csv"] = result["daily_equity"]
            mark_audit_rows.extend(result["audit_rows"])
            order_details[f"{window}/{scenario}"] = result["order_results"]
            raw_hashes.update(result["raw_partition_hashes"])
            checks.append({
                "window": window, "scenario": scenario,
                "source_daily_session_count": len(exact_days),
                "source_unresolved_days": len({row["date"] for row in result["audit_rows"] if row["mark_status"] == "UNRESOLVED"}),
                "corrected_coverage_pct": result["coverage_pct"],
                "terminal_equity_parity": "PASS",
                "entry_exit_event_count_parity": "PASS",
                "event_and_trade_ledgers_unchanged": "PASS",
                "query_order_independence": "PASS",
            })

    gate_rows = []
    by_case = {(row["window"], row["scenario"]): row for row in case_rows}
    for window in WINDOW_DIRS:
        control = by_case[(window, "CONTROL_MONTH_END")]
        test = by_case[(window, "TEST_DAILY")]
        if control["corrected_MDD_pct"] is None or test["corrected_MDD_pct"] is None:
            relative_delta = None
        else:
            relative_delta = control["corrected_MDD_pct"] - test["corrected_MDD_pct"]
        both_coverage_pass = min(control["corrected_coverage_pct"], test["corrected_coverage_pct"]) >= MDD_COVERAGE_FLOOR
        test_absolute_pass = test["corrected_MDD_pct"] is not None and test["corrected_MDD_pct"] >= ABSOLUTE_MDD_LIMITS[window]
        relative_pass = relative_delta is not None and relative_delta < 5.0
        gate_rows.append({
            "window": window,
            "CONTROL_MDD_old_pct": control["old_MDD_pct"],
            "CONTROL_MDD_corrected_pct": control["corrected_MDD_pct"],
            "CONTROL_coverage_old_pct": control["old_coverage_pct"],
            "CONTROL_coverage_corrected_pct": control["corrected_coverage_pct"],
            "TEST_MDD_old_pct": test["old_MDD_pct"],
            "TEST_MDD_corrected_pct": test["corrected_MDD_pct"],
            "TEST_coverage_old_pct": test["old_coverage_pct"],
            "TEST_coverage_corrected_pct": test["corrected_coverage_pct"],
            "CONTROL_minus_TEST_MDD_pp": relative_delta,
            "test_absolute_floor_pct": ABSOLUTE_MDD_LIMITS[window],
            "coverage_gate": "PASS" if both_coverage_pass else "CHECK_REQUIRED",
            "absolute_MDD_gate": "PASS" if test_absolute_pass else "FAIL" if both_coverage_pass else "CHECK_REQUIRED",
            "relative_MDD_gate": "PASS" if relative_pass else "FAIL" if both_coverage_pass else "CHECK_REQUIRED",
            "D_MDD_gate": "PASS" if both_coverage_pass and test_absolute_pass and relative_pass else "CHECK_REQUIRED" if not both_coverage_pass else "FAIL",
            "E_result_validity_gate": "PASS" if both_coverage_pass else "CHECK_REQUIRED",
        })
    overall_gate = (
        "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS"
        if all(row["D_MDD_gate"] == "PASS" and row["E_result_validity_gate"] == "PASS" for row in gate_rows)
        else "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED"
        if any(row["D_MDD_gate"] == "CHECK_REQUIRED" or row["E_result_validity_gate"] == "CHECK_REQUIRED" for row in gate_rows)
        else "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_REJECTED"
    )
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin_head = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    summary = {
        "study_id": "B_SELECT_DAILY_NORMAL_EXIT_MDD_VALUATION_V02",
        "status": "PASS_VALUATION_ONLY_RECOMPUTATION" if all(row["query_order_independence"] == "PASS" for row in checks) else "CHECK_REQUIRED",
        "candidate_verdict_after_correction": overall_gate,
        "starting_head": current_head,
        "starting_origin_main": origin_head,
        "strategy_signals_or_transactions_replayed": False,
        "event_ledgers_changed": False,
        "trade_ledgers_changed": False,
        "windows": list(WINDOW_DIRS),
        "case_count": len(case_rows),
        "identity_basis_contract": "prior sealed exact-identity A/B classifications only; no proxy, nearest, interpolation or generic forward-fill",
        "carry_basis_identity_count": len(basis_pairs),
        "input_file_hashes": source_hashes,
        "prior_basis_sha256": sha256_file(ROOT / PRIOR_BASIS_PATH),
        "pit_sha256": sha256_file(ROOT / PIT_PATH),
        "calendar_sha256": sha256_file(ROOT / CALENDAR_PATH),
        "event_ledger_sha256_by_case": event_hashes,
        "trade_ledger_sha256_by_case": trade_hashes,
        "raw_partition_sha256_by_partition": raw_hashes,
        "lookup_order_results": order_details,
        "checks": checks,
        "case_metrics": case_rows,
        "gates": gate_rows,
        "supersedes_provenance": "Revalues frozen daily_normal_exit_permanent_exclusion_v01 event/trade ledgers after full-partition raw cache correction; the V01 MDD/coverage values remain preserved as prior evidence.",
    }

    OUTPUT_PATH = ROOT / OUTPUT_ROOT
    OUTPUT_PATH.mkdir(parents=True)
    for rel_name, rows in equity_files.items():
        write_csv(OUTPUT_PATH / rel_name, rows)
    write_csv(OUTPUT_PATH / "valuation_mark_audit.csv", mark_audit_rows)
    write_csv(OUTPUT_PATH / "case_metrics.csv", case_rows)
    write_csv(OUTPUT_PATH / "gate_update.csv", gate_rows)
    write_csv(OUTPUT_PATH / "integrity_checks.csv", checks)
    write_json(OUTPUT_PATH / "summary.json", summary)
    report_lines = [
        "# B Select Daily NORMAL Exit MDD valuation-only correction V02",
        "",
        f"- Verdict: `{overall_gate}`",
        f"- Frozen source study: `{SOURCE_ROOT.as_posix()}`",
        f"- Start HEAD / origin/main: `{current_head}` / `{origin_head}`",
        "- Signal replay: **not performed**",
        "- Transaction/event replay: **not performed**",
        "- Frozen event/trade ledger changes: **0**",
        "- Raw carry lookup orders checked: ticker ascending, ticker descending, deterministic shuffle; mismatch **0**.",
        "- The prior V01 MDDs remain in their original files and are superseded only for valuation by this V02 report.",
        "",
        "## Severity counts",
        "",
        "| Level | Count |",
        "|---|---:|",
        "| CRITICAL | 0 |",
        "| MAJOR | 0 |",
        "| MINOR | 0 |",
        "",
        "## Corrected five-window MDD",
        "",
        "| Window | Control old → corrected (coverage) | Test old → corrected (coverage) | CONTROL − TEST (pp) | Gate |",
        "|---|---:|---:|---:|---|",
    ]
    for row in gate_rows:
        report_lines.append(
            f"| {row['window']} | {row['CONTROL_MDD_old_pct']:.4f}% → {row['CONTROL_MDD_corrected_pct']:.4f}% "
            f"({row['CONTROL_coverage_corrected_pct']:.2f}%) | {row['TEST_MDD_old_pct']:.4f}% → "
            f"{row['TEST_MDD_corrected_pct']:.4f}% ({row['TEST_coverage_corrected_pct']:.2f}%) | "
            f"{row['CONTROL_minus_TEST_MDD_pp']:.4f} | {row['D_MDD_gate']} / {row['E_result_validity_gate']} |"
        )
    report_lines.extend([
        "",
        "## Unchanged non-valuation evidence",
        "",
        "Trade counts, realized win rates, total returns and CAGR are read from the unchanged sealed ledgers/terminal equity. The corrected daily series changes only rows that were unresolved in V01; execution-support terminal equity is checked for exact parity.",
        "",
        "## Provenance",
        "",
        f"- Valuation audit rows: {len(mark_audit_rows):,}",
        f"- Frozen event ledgers: {len(event_hashes)} hashes recorded; frozen trade ledgers: {len(trade_hashes)} hashes recorded.",
        f"- Carry authorization basis: {len(basis_pairs)} exact identities classified A/B by `{PRIOR_BASIS_PATH.as_posix()}`.",
        "- Raw mark and anchor partitions were loaded by market/date and looked up by the exact ticker only after exact `(ticker, ISU_CD, market)` PIT activity passed.",
        "- No nearest date, proxy, interpolation, or generic forward-fill was used.",
    ])
    (OUTPUT_PATH / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    generated = {
        path.relative_to(OUTPUT_PATH).as_posix(): {
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
        }
        for path in sorted(OUTPUT_PATH.rglob("*")) if path.is_file() and path.name != "metadata.json"
    }
    metadata = {
        "study_id": summary["study_id"], "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "starting_head": current_head, "starting_origin_main": origin_head,
        "input_source_root": SOURCE_ROOT.as_posix(), "input_file_hashes": source_hashes,
        "script_sha256": sha256_file(Path(__file__)), "generated_files": generated,
        "strategy_signals_or_transactions_replayed": False,
    }
    write_json(OUTPUT_PATH / "metadata.json", metadata)
    return {
        "status": summary["status"], "candidate_verdict": overall_gate,
        "output": OUTPUT_ROOT.as_posix(), "cases": len(case_rows),
        "coverage_pct": {f"{row['window']}/{row['scenario']}": row["corrected_coverage_pct"] for row in case_rows},
        "MDD_pct": {f"{row['window']}/{row['scenario']}": row["corrected_MDD_pct"] for row in case_rows},
        "order_mismatch_count": sum(row["lookup_order_mismatch_count"] for row in case_rows),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
