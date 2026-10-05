#!/usr/bin/env python3
"""Audit missing daily valuation marks in the sealed B Select cadence replay.

This is a research-only postprocessor. It does not alter the replay, strategy,
official history, permanent exclusions, or Repository V2 source data.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_cadence_v01")
OUTPUT_RELATIVE = Path("artifacts/strategies/b_select_core_v1/research/mdd_coverage_root_cause_audit_v01")
RAW_ROOT = Path("data/market/raw/krx_stocks/v01")
ADJUSTED_ROOT = Path("data/market/adjusted/stocks")
PIT_PATH = Path("data/market/rolling_authority/merged_pit_intervals.json")
CALENDAR_PATH = Path("data/market/rolling_authority/merged_trading_calendar.json")
EXCLUSION_PATH = Path("src/trend_scanner/universe/permanent_identity_exclusions.py")
COMMON_RULES_PATH = Path("docs/validation/backtest_common_rules.md")
ADOPTION_CRITERIA_PATH = Path("docs/validation/official_strategy_adoption_criteria.md")
WINDOWS = ("p1", "p2_1", "p2_2", "p3_1", "p3_2")
SCENARIOS = {
    "CONTROL_MONTH_END": "control_month_end",
    "TEST_DAILY": "test_daily",
}
RAW_COLUMNS = (
    "date", "ticker", "open", "high", "low", "close", "volume",
    "trading_value", "market_cap", "listed_shares",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def identity_key(ticker: Any, isu_cd: Any) -> tuple[str, str]:
    return str(ticker or "").zfill(6), str(isu_cd or "").upper()


def numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def raw_nontrading_placeholder(row: Mapping[str, Any] | None) -> bool:
    """Match Repository V2's exact non-trading placeholder and listed-share evidence."""
    if row is None:
        return False
    return (
        numeric(row.get("open")) == 0
        and numeric(row.get("high")) == 0
        and numeric(row.get("low")) == 0
        and (numeric(row.get("close")) or 0) > 0
        and numeric(row.get("volume")) == 0
        and numeric(row.get("trading_value")) == 0
        and (numeric(row.get("listed_shares")) or 0) > 0
    )


def valid_raw_trade(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    values = [numeric(row.get(field)) for field in ("open", "high", "low", "close")]
    return all(value is not None and value > 0 for value in values) and (numeric(row.get("volume")) or 0) > 0


def valid_adjusted_close(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    values = {field: numeric(row.get(field)) for field in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in values.values()):
        return False
    return (
        values["high"] >= values["open"]
        and values["high"] >= values["low"]
        and values["high"] >= values["close"]
        and values["low"] <= values["open"]
        and values["low"] <= values["close"]
    )


def max_consecutive_dates(dates: Iterable[str], session_dates: Sequence[str]) -> int:
    """Return the longest run of dates adjacent in the exact KRX session list."""
    if not session_dates:
        return 0
    positions = {date: index for index, date in enumerate(session_dates)}
    indexes = sorted({positions[date] for date in dates if date in positions})
    longest = current = 0
    previous = None
    for index in indexes:
        current = current + 1 if previous is not None and index == previous + 1 else 1
        longest = max(longest, current)
        previous = index
    return longest


def classify_missing_day(open_positions: int, has_missing_marks: bool) -> str:
    if open_positions == 0:
        return "CASH_ONLY_DAY_MISSING"
    if has_missing_marks:
        return "POSITION_WITH_UNPRICED_MARK"
    return "PORTFOLIO_EQUITY_GENERATION_BUG_CANDIDATE"


def recoverable_by_carry(mark_rows: Sequence[Mapping[str, Any]]) -> bool:
    """A missing NAV date is recoverable only when every missing mark is authorized."""
    return bool(mark_rows) and all(bool(row.get("valuation_carry_allowed")) for row in mark_rows)


def _window_files(window: str, stem: str) -> dict[str, Path]:
    directory = ROOT / REPLAY_ROOT / window
    return {
        "metadata": directory / "metadata.json",
        "equity": directory / f"{stem}_daily_equity.csv",
        "events": directory / f"{stem}_portfolio_events.csv",
        "skips": directory / f"{stem}_portfolio_skips.csv",
        "trades": directory / f"{stem}_trade_ledger.csv",
    }


def _verify_generated_manifest(directory: Path, generated: Mapping[str, Any], *, hash_only: bool) -> dict[str, Any]:
    checks = {}
    for name, expected_value in generated.items():
        path = directory / name
        expected_hash = expected_value if hash_only else expected_value.get("sha256")
        expected_bytes = None if hash_only else expected_value.get("bytes")
        exists = path.is_file()
        actual_hash = sha256_file(path) if exists else None
        actual_bytes = path.stat().st_size if exists else None
        checks[name] = {
            "exists": exists,
            "expected_sha256": expected_hash,
            "actual_sha256": actual_hash,
            "expected_bytes": expected_bytes,
            "actual_bytes": actual_bytes,
            "status": "PASS" if exists and actual_hash == expected_hash and (expected_bytes is None or actual_bytes == expected_bytes) else "MISMATCH",
        }
    return checks


def _latest_basic_info(root: Path) -> tuple[str, dict[tuple[str, str], dict[str, Any]], list[Path]]:
    base = root / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info"
    dates = sorted(path.name for path in (base / "2026").glob("*") if path.is_dir())
    if not dates:
        raise RuntimeError("MISSING_LATEST_ROLLING_KRX_BASIC_INFO")
    asof = dates[-1]
    directory = base / "2026" / asof
    identity_rows: dict[tuple[str, str], dict[str, Any]] = {}
    files = []
    for market in ("KOSPI", "KOSDAQ"):
        path = directory / f"{market}.json"
        if not path.is_file():
            continue
        files.append(path)
        payload = read_json(path)
        rows = payload if isinstance(payload, list) else payload.get("OutBlock_1", [])
        for row in rows:
            key = identity_key(row.get("ISU_SRT_CD"), row.get("ISU_CD"))
            identity_rows[key] = dict(row)
    return f"2026-{asof[4:6]}-{asof[6:8]}", identity_rows, files


def _load_adjusted_files(root: Path, tickers: Iterable[str]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    rows_by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    metadata = {}
    for ticker in sorted(set(tickers)):
        path = root / ADJUSTED_ROOT / f"{ticker}.parquet"
        if not path.is_file():
            rows_by_ticker[ticker] = {}
            metadata[ticker] = {"exists": False, "sha256": None, "row_count": 0, "first_date": None, "last_date": None}
            continue
        table = pq.read_table(path, columns=["date", "open", "high", "low", "close"])
        raw_rows = table.to_pylist()
        date_map = {str(row["date"])[:10]: row for row in raw_rows}
        rows_by_ticker[ticker] = date_map
        dates = sorted(date_map)
        metadata[ticker] = {
            "exists": True,
            "sha256": sha256_file(path),
            "row_count": len(raw_rows),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
        }
    flattened = {
        (ticker, date): row
        for ticker, date_map in rows_by_ticker.items()
        for date, row in date_map.items()
    }
    return flattened, metadata


def run(output_relative: Path = OUTPUT_RELATIVE) -> Path:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

    replay_root = ROOT / REPLAY_ROOT
    replay_metadata = read_json(replay_root / "metadata.json")
    replay_manifest_checks = _verify_generated_manifest(
        replay_root, replay_metadata.get("generated_files", {}), hash_only=False,
    )
    if any(item["status"] != "PASS" for item in replay_manifest_checks.values()):
        raise RuntimeError("SEALED_CADENCE_ROOT_MANIFEST_MISMATCH")

    loaded: dict[tuple[str, str], dict[str, Any]] = {}
    source_hashes: dict[str, str] = {
        REPLAY_ROOT.joinpath("metadata.json").as_posix(): sha256_file(replay_root / "metadata.json"),
    }
    window_sessions: dict[tuple[str, str], list[str]] = {}
    equity_rows_by_scope: dict[tuple[str, str], list[dict[str, str]]] = {}
    skip_rows_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    entry_by_scope: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    exit_by_scope: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    trade_by_scope: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    scope_ends: dict[str, str] = {}
    root_manifest_checks: dict[str, Any] = {}

    # Read and verify the exact same daily-equity, skip and event records that
    # produced the prior MDD coverage result.
    for window in WINDOWS:
        window_meta_path = replay_root / window / "metadata.json"
        window_meta = read_json(window_meta_path)
        window_checks = _verify_generated_manifest(
            replay_root / window, window_meta.get("generated_files_sha256", {}), hash_only=True,
        )
        root_manifest_checks[window] = window_checks
        if any(item["status"] != "PASS" for item in window_checks.values()):
            raise RuntimeError(f"SEALED_CADENCE_WINDOW_MANIFEST_MISMATCH:{window}")
        scope_ends[window] = str(window_meta["window"]["effective_end"])[:10]
        source_hashes[(REPLAY_ROOT / window / "metadata.json").as_posix()] = sha256_file(window_meta_path)
        for scenario, stem in SCENARIOS.items():
            scope = (window, scenario)
            paths = _window_files(window, stem)
            for key in ("equity", "events", "skips", "trades"):
                source_hashes[(REPLAY_ROOT / window / paths[key].name).as_posix()] = sha256_file(paths[key])
            equity_rows = [row for row in read_csv(paths["equity"]) if row["date"] <= scope_ends[window]]
            if not equity_rows:
                raise RuntimeError(f"EMPTY_EFFECTIVE_WINDOW_EQUITY:{window}:{scenario}")
            dates = [row["date"] for row in equity_rows]
            if dates != sorted(set(dates)):
                raise RuntimeError(f"EQUITY_DATES_NOT_SORTED_UNIQUE:{window}:{scenario}")
            events = read_csv(paths["events"])
            entry_map: dict[str, dict[str, str]] = {}
            exit_map: dict[str, dict[str, str]] = {}
            for event in events:
                if event.get("event_status") != "EXECUTED":
                    continue
                pair_id = event.get("pair_id", "")
                if event.get("event_type") == "ENTRY":
                    if pair_id in entry_map:
                        raise RuntimeError(f"DUPLICATE_EXECUTED_ENTRY_PAIR:{window}:{scenario}:{pair_id}")
                    entry_map[pair_id] = event
                elif event.get("event_type") == "EXIT":
                    if pair_id in exit_map:
                        raise RuntimeError(f"DUPLICATE_EXECUTED_EXIT_PAIR:{window}:{scenario}:{pair_id}")
                    exit_map[pair_id] = event
            trade_rows = read_csv(paths["trades"])
            trade_map = {row.get("trade_id", ""): row for row in trade_rows}
            skip_rows: list[dict[str, Any]] = []
            for raw_skip in read_csv(paths["skips"]):
                if raw_skip.get("skip_reason") != "MISSING_EXACT_DAILY_MARK" or raw_skip.get("date", "") > scope_ends[window]:
                    continue
                pair_id = raw_skip.get("pair_id", "")
                entry = entry_map.get(pair_id)
                identity = identity_key(entry.get("ticker"), entry.get("isu_cd")) if entry else (identity_key(raw_skip.get("ticker"), ""))
                if entry and identity[0] != str(raw_skip.get("ticker", "")).zfill(6):
                    raise RuntimeError(f"SKIP_ENTRY_TICKER_MISMATCH:{window}:{scenario}:{pair_id}")
                trade = trade_map.get(pair_id, {})
                skip_rows.append({
                    **raw_skip,
                    "window": window.upper().replace("_", "-"),
                    "scenario": scenario,
                    "identity_ticker": identity[0],
                    "identity_isu_cd": identity[1],
                    "market": entry.get("market", "") if entry else "",
                    "entry_execution_date": entry.get("execution_date", "") if entry else "",
                    "exit_execution_date": exit_map.get(pair_id, {}).get("execution_date", ""),
                    "identity_effective_from": trade.get("identity_effective_from", ""),
                    "identity_effective_to": trade.get("identity_effective_to", ""),
                    "component_id": trade.get("component_id", ""),
                    "entry_event_found": entry is not None,
                })
            loaded[scope] = {"paths": paths, "window_meta": window_meta}
            window_sessions[scope] = dates
            equity_rows_by_scope[scope] = equity_rows
            skip_rows_by_scope[scope] = skip_rows
            entry_by_scope[scope] = entry_map
            exit_by_scope[scope] = exit_map
            trade_by_scope[scope] = trade_map

    if sum(len(rows) for rows in skip_rows_by_scope.values()) == 0:
        raise RuntimeError("NO_MISSING_EXACT_DAILY_MARK_ROWS")
    if any(not row["entry_event_found"] or not row["identity_isu_cd"] for rows in skip_rows_by_scope.values() for row in rows):
        raise RuntimeError("MISSING_EXACT_ENTRY_IDENTITY_FOR_VALUATION_MARK")

    mark_tickers = {row["identity_ticker"] for rows in skip_rows_by_scope.values() for row in rows}
    adjusted_rows, adjusted_file_metadata = _load_adjusted_files(ROOT, mark_tickers)
    source_hashes.update({(ADJUSTED_ROOT / f"{ticker}.parquet").as_posix(): item["sha256"] for ticker, item in adjusted_file_metadata.items() if item["exists"]})

    pit_payload = read_json(ROOT / PIT_PATH)
    calendar_payload = read_json(ROOT / CALENDAR_PATH)
    pit_intervals = pit_payload.get("intervals", [])
    calendar_dates = [str(value)[:10] for value in calendar_payload.get("trading_dates", [])]
    if calendar_dates != sorted(set(calendar_dates)):
        raise RuntimeError("MERGED_KRX_CALENDAR_NOT_SORTED_UNIQUE")
    source_hashes[PIT_PATH.as_posix()] = sha256_file(ROOT / PIT_PATH)
    source_hashes[CALENDAR_PATH.as_posix()] = sha256_file(ROOT / CALENDAR_PATH)
    source_hashes[EXCLUSION_PATH.as_posix()] = sha256_file(ROOT / EXCLUSION_PATH)
    source_hashes[COMMON_RULES_PATH.as_posix()] = sha256_file(ROOT / COMMON_RULES_PATH)
    source_hashes[ADOPTION_CRITERIA_PATH.as_posix()] = sha256_file(ROOT / ADOPTION_CRITERIA_PATH)

    latest_basic_asof, basic_info, basic_info_files = _latest_basic_info(ROOT)
    metadata_path = ROOT / "data/reference/krx_instrument_metadata.parquet"
    metadata_names: dict[str, str] = {}
    if metadata_path.is_file():
        metadata_table = pq.read_table(metadata_path, columns=["ticker", "name"])
        metadata_names = {
            str(row["ticker"]).zfill(6): str(row["name"] or "")
            for row in metadata_table.to_pylist()
        }
    for path in basic_info_files:
        source_hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    exclusion_keys = {identity_key(ticker, isu) for ticker, isu in PERMANENT_IDENTITY_EXCLUSIONS}
    raw_store = KrxRawStockStore(ROOT / RAW_ROOT)
    raw_manifest_path = ROOT / RAW_ROOT / "manifest.sqlite3"
    if not raw_manifest_path.is_file():
        raise RuntimeError("MISSING_KRX_RAW_MANIFEST")
    source_hashes[(RAW_ROOT / "manifest.sqlite3").as_posix()] = sha256_file(raw_manifest_path)

    # Pull each affected KRX market/date partition once, validate its manifest
    # hashes, and retain only exact identity rows referenced by missing marks.
    tickers_by_partition: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rows in skip_rows_by_scope.values():
        for row in rows:
            tickers_by_partition[(row["market"], row["date"])].add(row["identity_ticker"])
    raw_rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw_partition_audit: list[dict[str, Any]] = []
    for market, date in sorted(tickers_by_partition):
        manifest_row = raw_store.get_manifest(market, date)
        if manifest_row is None:
            raw_partition_audit.append({
                "market": market, "date": date, "status": "MISSING_MANIFEST", "valid": False,
                "row_count": None, "file_sha256": None, "content_sha256": None,
                "target_ticker_rows": 0,
            })
            continue
        if manifest_row.get("status") == "COMPLETE":
            frame = raw_store._verify_complete_row(manifest_row)
            target = frame.loc[frame["ticker"].astype(str).isin(tickers_by_partition[(market, date)])]
            target_by_ticker = {str(row["ticker"]): row.to_dict() for _, row in target.iterrows()}
            for ticker, raw_row in target_by_ticker.items():
                raw_rows_by_key[(market, date, ticker)] = raw_row
            valid = True
            target_count = len(target_by_ticker)
        elif manifest_row.get("status") == "NO_DATA":
            valid = manifest_row.get("schema_version") == "KRX_RAW_STOCK_V01" and int(manifest_row.get("row_count", -1)) == 0
            target_count = 0
        else:
            valid = False
            target_count = 0
        raw_partition_audit.append({
            "market": market,
            "date": date,
            "status": manifest_row.get("status"),
            "valid": valid,
            "row_count": manifest_row.get("row_count"),
            "file_sha256": manifest_row.get("file_sha256"),
            "content_sha256": manifest_row.get("content_sha256"),
            "schema_version": manifest_row.get("schema_version"),
            "source_endpoint": manifest_row.get("source_endpoint"),
            "target_ticker_rows": target_count,
        })
        if not valid:
            raise RuntimeError(f"INVALID_KRX_RAW_PARTITION:{market}:{date}:{manifest_row.get('status')}")

    partition_by_key = {(row["market"], row["date"]): row for row in raw_partition_audit}
    pit_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    pit_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pit_frontier = str(pit_payload.get("pit_frontier", ""))[:10]
    for interval in pit_intervals:
        key = identity_key(interval.get("ticker"), interval.get("isu_cd"))
        pit_by_identity[key].append(dict(interval))
        pit_by_ticker[key[0]].append(dict(interval))

    # Attach the exact current KRX company name/status, raw KRX evidence,
    # adjusted row presence and strict reason classification to every mark.
    for rows in skip_rows_by_scope.values():
        for mark in rows:
            ticker = mark["identity_ticker"]
            isu_cd = mark["identity_isu_cd"]
            date = mark["date"]
            key = identity_key(ticker, isu_cd)
            raw_row = raw_rows_by_key.get((mark["market"], date, ticker))
            adj_row = adjusted_rows.get((ticker, date))
            active_common = [
                interval for interval in pit_by_identity.get(key, [])
                if interval.get("state") == "COMMON"
                and str(interval.get("effective_from", ""))[:10] <= date <= str(interval.get("effective_to", ""))[:10]
            ]
            latest = basic_info.get(key)
            exact_excluded = key in exclusion_keys
            placeholder = raw_nontrading_placeholder(raw_row)
            raw_trade = valid_raw_trade(raw_row)
            if exact_excluded:
                cause = "PERMANENT_EXCLUSION_AUTHORITY_MISS"
            elif not active_common:
                future_isu = any(
                    other.get("isu_cd") != isu_cd and str(other.get("effective_from", ""))[:10] > date
                    for other in pit_by_ticker.get(ticker, [])
                )
                cause = "MERGER_OR_SUCCESSOR" if future_isu else "UNRESOLVED"
            elif placeholder:
                cause = "TRADING_SUSPENDED_OR_NON_TRADING"
            elif raw_row is not None and raw_trade and not valid_adjusted_close(adj_row):
                cause = "RAW_DATA_GAP"
            elif raw_row is None and adj_row is None:
                cause = "PRICE_ROW_DISAPPEARED"
            else:
                cause = "UNRESOLVED"
            name = str(latest.get("ISU_ABBRV") or "") if latest else ""
            if not name:
                name = metadata_names.get(ticker, "")
            mark.update({
                "company_name": name,
                "cause": cause,
                "raw_row_found": raw_row is not None,
                "raw_placeholder_match": placeholder,
                "raw_valid_trade_row": raw_trade,
                "raw_open": raw_row.get("open") if raw_row else None,
                "raw_high": raw_row.get("high") if raw_row else None,
                "raw_low": raw_row.get("low") if raw_row else None,
                "raw_close": raw_row.get("close") if raw_row else None,
                "raw_volume": raw_row.get("volume") if raw_row else None,
                "raw_trading_value": raw_row.get("trading_value") if raw_row else None,
                "raw_market_cap": raw_row.get("market_cap") if raw_row else None,
                "raw_listed_shares": raw_row.get("listed_shares") if raw_row else None,
                "adjusted_row_present": adj_row is not None,
                "adjusted_close": adj_row.get("close") if adj_row else None,
                "pit_common_active_on_mark_date": bool(active_common),
                "current_permanent_exclusion": exact_excluded,
                "latest_krx_basic_info_asof": latest_basic_asof,
                "latest_krx_basic_info_present": latest is not None,
                "latest_krx_name": latest.get("ISU_ABBRV") if latest else None,
                "latest_krx_list_date": latest.get("LIST_DD") if latest else None,
                "latest_krx_market": latest.get("MKT_TP_NM") if latest else None,
                "latest_krx_security_type": latest.get("SECUGRP_NM") if latest else None,
                "current_common_interval_count": sum(i.get("state") == "COMMON" and str(i.get("effective_to", ""))[:10] >= str(pit_payload.get("pit_frontier", "")) for i in pit_by_identity.get(key, [])),
                "raw_partition_valid": partition_by_key.get((mark["market"], date), {}).get("valid", False),
                "raw_partition_file_sha256": partition_by_key.get((mark["market"], date), {}).get("file_sha256"),
                "raw_partition_content_sha256": partition_by_key.get((mark["market"], date), {}).get("content_sha256"),
            })

    # A carry anchor is considered only at the start of a consecutive missing
    # run for this exact executed position. Every carried date must itself have
    # an official KRX non-trading placeholder, and the immediately preceding
    # exact KRX session must have a valid traded raw row and adjusted close for
    # the same exact identity while its PIT COMMON interval is active on both dates.
    for scope, marks in skip_rows_by_scope.items():
        dates = window_sessions[scope]
        date_positions = {day: index for index, day in enumerate(calendar_dates)}
        marks_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for mark in marks:
            marks_by_pair[mark["pair_id"]].append(mark)
        entry_map = entry_by_scope[scope]
        for pair_id, pair_marks in marks_by_pair.items():
            pair_marks.sort(key=lambda row: row["date"])
            prior_mark = None
            inherited_anchor_date = None
            inherited_anchor_close = None
            for mark in pair_marks:
                date = mark["date"]
                contiguous = (
                    prior_mark is not None
                    and prior_mark["cause"] == "TRADING_SUSPENDED_OR_NON_TRADING"
                    and mark["cause"] == "TRADING_SUSPENDED_OR_NON_TRADING"
                    and date_positions.get(date, -999) == date_positions.get(prior_mark["date"], -998) + 1
                )
                if contiguous and inherited_anchor_date is not None:
                    anchor_date, anchor_close = inherited_anchor_date, inherited_anchor_close
                else:
                    pos = bisect.bisect_left(calendar_dates, date)
                    anchor_date = calendar_dates[pos - 1] if pos > 0 else None
                    anchor_close = None
                    event = entry_map.get(pair_id)
                    key = identity_key(mark["identity_ticker"], mark["identity_isu_cd"])
                    if (
                        anchor_date is not None
                        and event is not None
                        and anchor_date >= str(event.get("execution_date", ""))[:10]
                    ):
                        prev_partition_key = (mark["market"], anchor_date)
                        anchor_row_key = (mark["market"], anchor_date, mark["identity_ticker"])
                        if anchor_row_key not in raw_rows_by_key:
                            manifest_row = raw_store.get_manifest(*prev_partition_key)
                            if manifest_row and manifest_row.get("status") == "COMPLETE":
                                frame = raw_store._verify_complete_row(manifest_row)
                                prev_row = frame.loc[frame["ticker"].astype(str).eq(mark["identity_ticker"])]
                                if not prev_row.empty:
                                    raw_rows_by_key[anchor_row_key] = prev_row.iloc[0].to_dict()
                                if prev_partition_key not in partition_by_key:
                                    audit_row = {
                                        "market": mark["market"], "date": anchor_date, "status": "COMPLETE",
                                        "valid": True, "row_count": manifest_row.get("row_count"),
                                        "file_sha256": manifest_row.get("file_sha256"),
                                        "content_sha256": manifest_row.get("content_sha256"),
                                        "schema_version": manifest_row.get("schema_version"),
                                        "source_endpoint": manifest_row.get("source_endpoint"),
                                        "target_ticker_rows": int(anchor_row_key in raw_rows_by_key),
                                        "target_tickers": mark["identity_ticker"] if anchor_row_key in raw_rows_by_key else "",
                                        "partition_role": "CARRY_ANCHOR",
                                    }
                                    partition_by_key[prev_partition_key] = audit_row
                                    raw_partition_audit.append(audit_row)
                                else:
                                    audit_row = partition_by_key[prev_partition_key]
                                    if anchor_row_key in raw_rows_by_key and mark["identity_ticker"] not in str(audit_row.get("target_tickers", "")).split("|"):
                                        audit_row["target_ticker_rows"] = int(audit_row.get("target_ticker_rows") or 0) + 1
                                        audit_row["target_tickers"] = "|".join(filter(None, [str(audit_row.get("target_tickers", "")), mark["identity_ticker"]]))
                            elif manifest_row and manifest_row.get("status") == "NO_DATA":
                                if prev_partition_key not in partition_by_key:
                                    audit_row = {
                                        "market": mark["market"], "date": anchor_date, "status": "NO_DATA",
                                        "valid": True, "row_count": 0, "file_sha256": None,
                                        "content_sha256": None, "schema_version": manifest_row.get("schema_version"),
                                        "source_endpoint": manifest_row.get("source_endpoint"), "target_ticker_rows": 0,
                                        "target_tickers": "", "partition_role": "CARRY_ANCHOR",
                                    }
                                    partition_by_key[prev_partition_key] = audit_row
                                    raw_partition_audit.append(audit_row)
                            else:
                                if prev_partition_key not in partition_by_key:
                                    audit_row = {
                                        "market": mark["market"], "date": anchor_date,
                                        "status": "MISSING_MANIFEST" if manifest_row is None else manifest_row.get("status"),
                                        "valid": False, "row_count": manifest_row.get("row_count") if manifest_row else None,
                                        "file_sha256": manifest_row.get("file_sha256") if manifest_row else None,
                                        "content_sha256": manifest_row.get("content_sha256") if manifest_row else None,
                                        "schema_version": manifest_row.get("schema_version") if manifest_row else None,
                                        "source_endpoint": manifest_row.get("source_endpoint") if manifest_row else None,
                                        "target_ticker_rows": 0, "target_tickers": "",
                                        "partition_role": "CARRY_ANCHOR",
                                    }
                                    partition_by_key[prev_partition_key] = audit_row
                                    raw_partition_audit.append(audit_row)
                        prev_raw = raw_rows_by_key.get((mark["market"], anchor_date, mark["identity_ticker"]))
                        prev_adjusted = adjusted_rows.get((mark["identity_ticker"], anchor_date))
                        prev_pit_active = any(
                            interval.get("state") == "COMMON"
                            and str(interval.get("effective_from", ""))[:10] <= anchor_date <= str(interval.get("effective_to", ""))[:10]
                            for interval in pit_by_identity.get(key, [])
                        )
                        if prev_pit_active and valid_raw_trade(prev_raw) and valid_adjusted_close(prev_adjusted):
                            anchor_close = float(prev_adjusted["close"])
                mark["carry_reference_date"] = anchor_date
                mark["carry_reference_adjusted_close"] = anchor_close
                mark["valuation_carry_allowed"] = bool(
                    mark["cause"] == "TRADING_SUSPENDED_OR_NON_TRADING"
                    and mark["raw_placeholder_match"]
                    and mark["pit_common_active_on_mark_date"]
                    and mark["latest_krx_basic_info_present"]
                    and anchor_date is not None
                    and anchor_close is not None
                    and mark["raw_partition_valid"]
                )
                mark["carry_decision_reason"] = (
                    "official exact-session KRX non-trading placeholder; previous exact session has valid same-identity adjusted close"
                    if mark["valuation_carry_allowed"]
                    else "not eligible: a required raw, PIT, placeholder, or previous exact close condition is unconfirmed"
                )
                if mark["valuation_carry_allowed"]:
                    inherited_anchor_date, inherited_anchor_close = anchor_date, anchor_close
                else:
                    inherited_anchor_date, inherited_anchor_close = None, None
                prior_mark = mark

    # Classify every valuation date before aggregating identity and window impact.
    marks_by_scope_day: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    missing_date_rows: list[dict[str, Any]] = []
    day_class_rows: list[dict[str, Any]] = []
    scope_metrics: dict[tuple[str, str], dict[str, Any]] = {}
    for scope, equity_rows in equity_rows_by_scope.items():
        window, scenario = scope
        marks_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for mark in skip_rows_by_scope[scope]:
            marks_by_day[mark["date"]].append(mark)
        marks_by_scope_day[scope] = marks_by_day
        missing_equity = [row for row in equity_rows if numeric(row.get("equity")) is None]
        unexpected_skips = sorted(set(marks_by_day) - {row["date"] for row in missing_equity})
        missing_without_skip = sorted({row["date"] for row in missing_equity} - set(marks_by_day))
        cash_only = sum(int(row.get("open_positions") or 0) == 0 for row in missing_equity)
        no_skip_positions = [row for row in missing_equity if not marks_by_day.get(row["date"])]
        day_class_rows.append({
            "window": window.upper().replace("_", "-"),
            "scenario": scenario,
            "total_trading_days": len(equity_rows),
            "observed_equity_days": len(equity_rows) - len(missing_equity),
            "missing_equity_days": len(missing_equity),
            "cash_only_day_missing": cash_only,
            "position_day_with_missing_mark": len(missing_equity) - cash_only - len(no_skip_positions),
            "position_day_without_missing_mark": len(no_skip_positions),
            "skip_dates_outside_missing_equity": len(unexpected_skips),
            "missing_equity_dates_without_skip": len(missing_without_skip),
            "classification": "PASS" if cash_only == 0 and not no_skip_positions and not unexpected_skips else "CHECK_REQUIRED",
        })
        for row in missing_equity:
            marks_for_day = marks_by_day.get(row["date"], [])
            cause_set = sorted({mark["cause"] for mark in marks_for_day})
            day_type = classify_missing_day(int(row.get("open_positions") or 0), bool(marks_for_day))
            missing_date_rows.append({
                "window": window.upper().replace("_", "-"),
                "scenario": scenario,
                "date": row["date"],
                "open_positions": int(row.get("open_positions") or 0),
                "cash_krw": numeric(row.get("cash")),
                "missing_mark_count": len(marks_for_day),
                "day_classification": day_type,
                "cause_classes": "|".join(cause_set),
                "identity_keys": "|".join(sorted({f"{mark['identity_ticker']}:{mark['identity_isu_cd']}" for mark in marks_for_day})),
                "all_marks_carry_eligible": recoverable_by_carry(marks_for_day),
            })
        total_marks = sum(len(values) for values in marks_by_day.values())
        recovered = sum(
            1 for row in missing_equity
            if recoverable_by_carry(marks_by_day.get(row["date"], []))
        )
        total = len(equity_rows)
        observed = total - len(missing_equity)
        scope_metrics[scope] = {
            "total_days": total,
            "observed_days": observed,
            "missing_days": len(missing_equity),
            "missing_marks": total_marks,
            "scenario_b_recovered_days": recovered,
            "scenario_b_unresolved_days": len(missing_equity) - recovered,
            "scenario_a_coverage_pct": (observed / total * 100) if total else 0.0,
            "scenario_b_coverage_pct": ((observed + recovered) / total * 100) if total else 0.0,
            "scenario_c_coverage_pct": (observed / total * 100) if total else 0.0,
            "scenario_c_exclusion_leakage_marks": sum(1 for rows in marks_by_day.values() for mark in rows if mark["current_permanent_exclusion"]),
        }

    if any(row["classification"] != "PASS" for row in day_class_rows):
        structural_day_class_fail = True
    else:
        structural_day_class_fail = False

    # Per-identity / per-window / per-scenario impact, including actual active
    # holding sessions reconstructed from exact executed ENTRY/EXIT events.
    identity_grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for scope, rows in skip_rows_by_scope.items():
        for mark in rows:
            identity_grouped[(scope[0], scope[1], mark["identity_ticker"], mark["identity_isu_cd"])].append(mark)
    total_all_marks = sum(len(rows) for rows in skip_rows_by_scope.values())
    identity_scope_rows = []
    for (window, scenario, ticker, isu_cd), marks in sorted(identity_grouped.items()):
        scope = (window, scenario)
        sessions = window_sessions[scope]
        entry_map = entry_by_scope[scope]
        exit_map = exit_by_scope[scope]
        active_identity_dates = set()
        for day in sessions:
            for pair_id, entry in entry_map.items():
                if identity_key(entry.get("ticker"), entry.get("isu_cd")) != (ticker, isu_cd):
                    continue
                entry_day = str(entry.get("execution_date", ""))[:10]
                exit_event = exit_map.get(pair_id)
                exit_day = str(exit_event.get("execution_date", ""))[:10] if exit_event else ""
                if entry_day <= day and (not exit_day or exit_day > day):
                    active_identity_dates.add(day)
                    break
        dates = sorted({mark["date"] for mark in marks})
        first_mark = min(marks, key=lambda mark: mark["date"])
        last_mark = max(marks, key=lambda mark: mark["date"])
        meta_row = basic_info.get((ticker, isu_cd), {})
        pit_rows = pit_by_identity.get((ticker, isu_cd), [])
        cause_counts = Counter(mark["cause"] for mark in marks)
        cause = next(iter(cause_counts)) if len(cause_counts) == 1 else "MIXED_OR_UNRESOLVED"
        identity_scope_rows.append({
            "scope": "OVERALL" if window == "ALL" else window.upper().replace("_", "-"),
            "window": "ALL" if window == "ALL" else window.upper().replace("_", "-"),
            "scenario": "ALL" if scenario == "ALL" else scenario,
            "ticker": ticker,
            "isu_cd": isu_cd,
            "company_name": str(meta_row.get("ISU_ABBRV") or ""),
            "market": str(meta_row.get("MKT_TP_NM") or first_mark.get("market") or ""),
            "root_cause": cause,
            "cause_mark_counts": json.dumps(dict(sorted(cause_counts.items())), ensure_ascii=False, sort_keys=True),
            "first_missing_date": dates[0],
            "last_missing_date": dates[-1],
            "missing_valuation_mark_count": len(marks),
            "unique_missing_dates": len(dates),
            "max_consecutive_missing_days": max_consecutive_dates(dates, sessions),
            "held_sessions_in_window": len(active_identity_dates),
            "missing_mark_pct_of_scope": (len(marks) / max(1, scope_metrics[scope]["missing_marks"]) * 100),
            "missing_mark_pct_overall": (len(marks) / max(1, total_all_marks) * 100),
            "affected_windows": window.upper().replace("_", "-"),
            "currently_permanently_excluded": (ticker, isu_cd) in exclusion_keys,
            "latest_krx_basic_info_asof": latest_basic_asof,
            "latest_krx_basic_info_present": (ticker, isu_cd) in basic_info,
            "current_common_pit_interval_count": sum(
                row.get("state") == "COMMON" and str(row.get("effective_to", ""))[:10] >= str(pit_payload.get("pit_frontier", ""))
                for row in pit_rows
            ),
            "raw_first_missing_o_h_l_c_vol_shares": "|".join(str(first_mark.get(field, "")) for field in ("raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_listed_shares")),
            "raw_last_missing_o_h_l_c_vol_shares": "|".join(str(last_mark.get(field, "")) for field in ("raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_listed_shares")),
            "current_permanent_exclusion_count": len(exclusion_keys),
        })

    # Add overall rows by exact identity.
    overall_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (_window, _scenario, ticker, isu_cd), marks in identity_grouped.items():
        overall_groups[(ticker, isu_cd)].extend(marks)
    for (ticker, isu_cd), marks in sorted(overall_groups.items()):
        dates = sorted({mark["date"] for mark in marks})
        causes = Counter(mark["cause"] for mark in marks)
        first_mark = min(marks, key=lambda mark: (mark["window"], mark["scenario"], mark["date"]))
        meta_row = basic_info.get((ticker, isu_cd), {})
        pit_rows = pit_by_identity.get((ticker, isu_cd), [])
        identity_scope_rows.append({
            "scope": "OVERALL", "window": "ALL", "scenario": "ALL",
            "ticker": ticker, "isu_cd": isu_cd,
            "company_name": str(meta_row.get("ISU_ABBRV") or first_mark.get("company_name") or ""),
            "market": str(meta_row.get("MKT_TP_NM") or first_mark.get("market") or ""),
            "root_cause": next(iter(causes)) if len(causes) == 1 else "MIXED_OR_UNRESOLVED",
            "cause_mark_counts": json.dumps(dict(sorted(causes.items())), ensure_ascii=False, sort_keys=True),
            "first_missing_date": dates[0], "last_missing_date": dates[-1],
            "missing_valuation_mark_count": len(marks), "unique_missing_dates": len(dates),
            "max_consecutive_missing_days": max(
                max_consecutive_dates({m["date"] for m in rows}, window_sessions[scope])
                for scope, rows in [
                    (scope, [m for m in marks if m["window"] == scope[0].upper().replace("_", "-") and m["scenario"] == scope[1]])
                    for scope in scope_metrics
                ]
                if rows
            ),
            "held_sessions_in_window": None,
            "missing_mark_pct_of_scope": None,
            "missing_mark_pct_overall": len(marks) / max(1, total_all_marks) * 100,
            "affected_windows": "|".join(sorted({m["window"] for m in marks})),
            "currently_permanently_excluded": (ticker, isu_cd) in exclusion_keys,
            "latest_krx_basic_info_asof": latest_basic_asof,
            "latest_krx_basic_info_present": (ticker, isu_cd) in basic_info,
            "current_common_pit_interval_count": sum(
                row.get("state") == "COMMON" and str(row.get("effective_to", ""))[:10] >= str(pit_payload.get("pit_frontier", ""))
                for row in pit_rows
            ),
            "raw_first_missing_o_h_l_c_vol_shares": "|".join(str(first_mark.get(field, "")) for field in ("raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_listed_shares")),
            "raw_last_missing_o_h_l_c_vol_shares": "|".join(str(marks[-1].get(field, "")) for field in ("raw_open", "raw_high", "raw_low", "raw_close", "raw_volume", "raw_listed_shares")),
            "current_permanent_exclusion_count": len(exclusion_keys),
        })

    # Root-cause days are intentionally non-additive: more than one identity
    # can prevent the same portfolio-day from being valued.
    cause_contribution_rows = []
    top_share_rows = []
    for scope, equity_rows in equity_rows_by_scope.items():
        marks_by_day = marks_by_scope_day[scope]
        total_days = len(equity_rows)
        missing_days = [row for row in equity_rows if numeric(row.get("equity")) is None]
        cause_day_map: dict[str, set[str]] = defaultdict(set)
        cause_mark_count: Counter[str] = Counter()
        cause_identity_map: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for day in missing_days:
            day_marks = marks_by_day.get(day["date"], [])
            for cause in {mark["cause"] for mark in day_marks}:
                cause_day_map[cause].add(day["date"])
            for mark in day_marks:
                cause_mark_count[mark["cause"]] += 1
                cause_identity_map[mark["cause"]].add((mark["identity_ticker"], mark["identity_isu_cd"]))
        for cause in sorted(set(cause_day_map) | set(cause_mark_count)):
            day_count = len(cause_day_map[cause])
            cause_contribution_rows.append({
                "window": scope[0].upper().replace("_", "-"),
                "scenario": scope[1],
                "cause": cause,
                "missing_day_count_non_additive": day_count,
                "total_trading_days": total_days,
                "pct_of_total_trading_days": day_count / max(1, total_days) * 100,
                "missing_valuation_mark_count": cause_mark_count[cause],
                "unique_identity_count": len(cause_identity_map[cause]),
            })
        identity_counts = Counter((m["identity_ticker"], m["identity_isu_cd"]) for m in skip_rows_by_scope[scope])
        ranked = sorted(identity_counts.items(), key=lambda item: (-item[1], item[0]))
        total_marks = sum(identity_counts.values())
        top_share_rows.append({
            "window": scope[0].upper().replace("_", "-"), "scenario": scope[1],
            "total_missing_marks": total_marks,
            "top1_identity": f"{ranked[0][0][0]}:{ranked[0][0][1]}" if ranked else "",
            "top1_share_pct": sum(value for _key, value in ranked[:1]) / max(1, total_marks) * 100,
            "top3_share_pct": sum(value for _key, value in ranked[:3]) / max(1, total_marks) * 100,
            "top5_share_pct": sum(value for _key, value in ranked[:5]) / max(1, total_marks) * 100,
        })
    overall_counts = Counter((m["identity_ticker"], m["identity_isu_cd"]) for rows in skip_rows_by_scope.values() for m in rows)
    overall_ranked = sorted(overall_counts.items(), key=lambda item: (-item[1], item[0]))
    overall_total_marks = sum(overall_counts.values())
    top_share_rows.append({
        "window": "ALL", "scenario": "ALL", "total_missing_marks": overall_total_marks,
        "top1_identity": f"{overall_ranked[0][0][0]}:{overall_ranked[0][0][1]}" if overall_ranked else "",
        "top1_share_pct": sum(value for _key, value in overall_ranked[:1]) / max(1, overall_total_marks) * 100,
        "top3_share_pct": sum(value for _key, value in overall_ranked[:3]) / max(1, overall_total_marks) * 100,
        "top5_share_pct": sum(value for _key, value in overall_ranked[:5]) / max(1, overall_total_marks) * 100,
    })

    # Summarize categories and assess all 10 MDD coverage cases.
    cause_mark_totals = Counter(mark["cause"] for rows in skip_rows_by_scope.values() for mark in rows)
    identity_count_by_cause = defaultdict(set)
    for rows in skip_rows_by_scope.values():
        for mark in rows:
            identity_count_by_cause[mark["cause"]].add((mark["identity_ticker"], mark["identity_isu_cd"]))
    scenario_coverage_rows = []
    for scope, metrics in sorted(scope_metrics.items()):
        replay_exclusion_hash = replay_metadata.get("source_hashes", {}).get(EXCLUSION_PATH.as_posix())
        current_exclusion_hash = source_hashes.get(EXCLUSION_PATH.as_posix())
        exclusion_policy_hash_matches = bool(replay_exclusion_hash and replay_exclusion_hash == current_exclusion_hash)
        scenario_coverage_rows.append({
            "window": scope[0].upper().replace("_", "-"),
            "scenario": scope[1],
            "total_trading_days": metrics["total_days"],
            "scenario_a_current_observed_days": metrics["observed_days"],
            "scenario_a_current_coverage_pct": metrics["scenario_a_coverage_pct"],
            "scenario_b_carry_recovered_days": metrics["scenario_b_recovered_days"],
            "scenario_b_unresolved_days": metrics["scenario_b_unresolved_days"],
            "scenario_b_expected_coverage_pct": metrics["scenario_b_coverage_pct"],
            "scenario_c_already_approved_exclusion_recovered_days": 0 if metrics["scenario_c_exclusion_leakage_marks"] == 0 else None,
            "scenario_c_expected_coverage_pct": metrics["scenario_c_coverage_pct"] if metrics["scenario_c_exclusion_leakage_marks"] == 0 and exclusion_policy_hash_matches else None,
            "scenario_c_leakage_mark_count": metrics["scenario_c_exclusion_leakage_marks"],
            "scenario_c_status": (
                "NO_EFFECT_NO_CURRENT_EXCLUSION_LEAKAGE"
                if metrics["scenario_c_exclusion_leakage_marks"] == 0 and exclusion_policy_hash_matches
                else "CHECK_REQUIRED_REPLAY_EXCLUSION_AUTHORITY_HASH_MISMATCH"
                if not exclusion_policy_hash_matches
                else "CHECK_REQUIRED_PORTFOLIO_REPLAY_NEEDED"
            ),
        })

    # A single identity-level root cause is only assigned when every audited
    # missing mark for that pair has the same evidence class.
    raw_rows_total = sum(len(rows) for rows in skip_rows_by_scope.values())
    raw_placeholder_marks = sum(1 for rows in skip_rows_by_scope.values() for mark in rows if mark["raw_placeholder_match"])
    carry_eligible_marks = sum(1 for rows in skip_rows_by_scope.values() for mark in rows if mark["valuation_carry_allowed"])
    exclusion_leak_marks = sum(1 for rows in skip_rows_by_scope.values() for mark in rows if mark["current_permanent_exclusion"])
    missing_identity_keys = set(overall_counts)
    exclusion_policies = dict(PERMANENT_IDENTITY_EXCLUSIONS)
    prior_gap_exclusion_keys = {
        key for key, policy in exclusion_policies.items()
        if "RAW_DATA_GAP" in str(policy.get("failure_class", "")).upper()
        or "RAW_DATA_GAP" in str(policy.get("reason", "")).upper()
    }
    prior_terminal_exclusion_keys = {
        key for key, policy in exclusion_policies.items()
        if any(token in str(policy.get("reason", "")).lower() for token in ("terminal pricing", "delisting"))
    }
    prior_successor_exclusion_keys = {
        key for key, policy in exclusion_policies.items()
        if "successor-resolution" in str(policy.get("reason", "")).lower()
        or "successor-resolution" in str(policy.get("approval_scope", "")).lower()
    }
    raw_partition_invalid_count = sum(not bool(row.get("valid")) for row in raw_partition_audit)
    replay_exclusion_hash = replay_metadata.get("source_hashes", {}).get(EXCLUSION_PATH.as_posix())
    current_exclusion_hash = source_hashes.get(EXCLUSION_PATH.as_posix())
    exclusion_policy_hash_matches = bool(replay_exclusion_hash and replay_exclusion_hash == current_exclusion_hash)
    total_mdd_days = sum(len(rows) for rows in equity_rows_by_scope.values())
    total_mdd_missing_days = sum(metrics["missing_days"] for metrics in scope_metrics.values())
    all_marks_known_nontrading = raw_rows_total > 0 and raw_placeholder_marks == raw_rows_total
    any_structural_bug = structural_day_class_fail or any(
        row["classification"] != "PASS" for row in day_class_rows
    )
    if any_structural_bug:
        verdict = "B_SELECT_MDD_COVERAGE_ENGINE_BUG_FOUND"
    elif raw_partition_invalid_count or any(mark["cause"] == "UNRESOLVED" for rows in skip_rows_by_scope.values() for mark in rows):
        verdict = "B_SELECT_MDD_COVERAGE_ROOT_CAUSE_CHECK_REQUIRED"
    elif all_marks_known_nontrading:
        verdict = "B_SELECT_MDD_COVERAGE_REMEDIATION_DECISION_REQUIRED"
    else:
        verdict = "B_SELECT_MDD_COVERAGE_ROOT_CAUSE_CHECK_REQUIRED"

    manifest_path = ROOT / RAW_ROOT / "manifest.sqlite3"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    origin = subprocess.run(["git", "rev-parse", "origin/main"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    raw_status = subprocess.run(["git", "status", "--short", "--branch"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    identity_tables = [row for row in identity_scope_rows if row["window"] == "ALL"]
    top_overall = sorted(identity_tables, key=lambda row: (-int(row["missing_valuation_mark_count"]), row["ticker"]))
    top1_share = sum(int(row["missing_valuation_mark_count"]) for row in top_overall[:1]) / max(1, raw_rows_total) * 100
    top3_share = sum(int(row["missing_valuation_mark_count"]) for row in top_overall[:3]) / max(1, raw_rows_total) * 100
    top5_share = sum(int(row["missing_valuation_mark_count"]) for row in top_overall[:5]) / max(1, raw_rows_total) * 100

    summary = {
        "study_id": "B_SELECT_MDD_COVERAGE_ROOT_CAUSE_AUDIT_V01",
        "verdict": verdict,
        "start_head": "c0840955d85d9641394367b02d8b6027944388d8",
        "audit_base_head": head,
        "audit_base_origin_main": origin,
        "start_worktree_status": raw_status,
        "total_scope_window_scenario_trading_days": total_mdd_days,
        "missing_equity_day_rows": total_mdd_missing_days,
        "missing_equity_day_row_pct": total_mdd_missing_days / max(1, total_mdd_days) * 100,
        "missing_valuation_mark_rows": raw_rows_total,
        "unique_exact_identities": len(overall_counts),
        "unique_missing_krx_dates": len({mark["date"] for rows in skip_rows_by_scope.values() for mark in rows}),
        "unique_krx_market_date_partitions_verified": len(raw_partition_audit),
        "missing_mark_market_date_partition_count": len(tickers_by_partition),
        "carry_anchor_partition_count": sum(row.get("partition_role") == "CARRY_ANCHOR" for row in raw_partition_audit),
        "raw_partition_invalid_count": raw_partition_invalid_count,
        "raw_nontrading_placeholder_marks": raw_placeholder_marks,
        "scenario_b_carry_eligible_marks": carry_eligible_marks,
        "scenario_b_carry_eligible_pct": carry_eligible_marks / max(1, raw_rows_total) * 100,
        "current_exclusion_identity_count": len(exclusion_keys),
        "replay_exclusion_policy_hash_matches_current": exclusion_policy_hash_matches,
        "replay_exclusion_policy_sha256": replay_exclusion_hash,
        "current_exclusion_policy_sha256": current_exclusion_hash,
        "current_exclusion_leak_mark_count": exclusion_leak_marks,
        "current_exclusion_leak_identity_count": len(missing_identity_keys & exclusion_keys),
        "prior_raw_data_gap_exclusion_identity_count": len(prior_gap_exclusion_keys),
        "prior_raw_data_gap_exclusion_recurrence_identity_count": len(missing_identity_keys & prior_gap_exclusion_keys),
        "prior_terminal_or_delisting_exclusion_identity_count": len(prior_terminal_exclusion_keys),
        "prior_terminal_or_delisting_exclusion_recurrence_identity_count": len(missing_identity_keys & prior_terminal_exclusion_keys),
        "prior_successor_resolution_exclusion_identity_count": len(prior_successor_exclusion_keys),
        "prior_successor_resolution_exclusion_recurrence_identity_count": len(missing_identity_keys & prior_successor_exclusion_keys),
        "cash_only_missing_equity_day_count": sum(row["cash_only_day_missing"] for row in day_class_rows),
        "position_missing_equity_without_missing_mark_count": sum(row["position_day_without_missing_mark"] for row in day_class_rows),
        "missing_day_classification_pass_count": sum(row["classification"] == "PASS" for row in day_class_rows),
        "missing_day_classification_scope_count": len(day_class_rows),
        "top1_identity_missing_mark_share_pct": top1_share,
        "top3_identity_missing_mark_share_pct": top3_share,
        "top5_identity_missing_mark_share_pct": top5_share,
        "cause_mark_counts": dict(sorted(cause_mark_totals.items())),
        "cause_unique_identity_counts": {cause: len(keys) for cause, keys in sorted(identity_count_by_cause.items())},
        "all_missing_marks_are_confirmed_krx_nontrading_placeholders": all_marks_known_nontrading,
        "portfolio_equity_generation_bug_found": bool(any_structural_bug),
        "latest_krx_basic_info_asof": latest_basic_asof,
        "pit_frontier": pit_payload.get("pit_frontier"),
        "krx_raw_manifest_sha256": source_hashes[(RAW_ROOT / "manifest.sqlite3").as_posix()],
        "replay_metadata_sha256": source_hashes[REPLAY_ROOT.joinpath("metadata.json").as_posix()],
        "production_changes": False,
        "official_history_modified": False,
        "permanent_exclusions_modified": False,
    }

    missing_identity_dates = []
    for scope, marks_by_day in marks_by_scope_day.items():
        for date, marks in sorted(marks_by_day.items()):
            for mark in marks:
                missing_identity_dates.append({
                    "window": scope[0].upper().replace("_", "-"),
                    "scenario": scope[1],
                    "date": date,
                    "ticker": mark["identity_ticker"],
                    "isu_cd": mark["identity_isu_cd"],
                    "company_name": mark["company_name"],
                    "market": mark["market"],
                    "pair_id": mark["pair_id"],
                    "cause": mark["cause"],
                    "raw_placeholder_match": mark["raw_placeholder_match"],
                    "raw_partition_valid": mark["raw_partition_valid"],
                    "valuation_carry_allowed": mark["valuation_carry_allowed"],
                    "carry_reference_date": mark.get("carry_reference_date"),
                    "carry_reference_adjusted_close": mark.get("carry_reference_adjusted_close"),
                    "current_permanent_exclusion": mark["current_permanent_exclusion"],
                })

    # Find the exact gap-days and contributor identities in each scope.
    longest_gaps = []
    for scope, equity_rows in equity_rows_by_scope.items():
        sessions = window_sessions[scope]
        missing_dates = [row["date"] for row in equity_rows if numeric(row.get("equity")) is None]
        positions = {date: idx for idx, date in enumerate(sessions)}
        indexes = sorted(positions[date] for date in missing_dates)
        runs: list[list[str]] = []
        current: list[str] = []
        prior_index = None
        for index in indexes:
            if prior_index is None or index != prior_index + 1:
                if current:
                    runs.append(current)
                current = [sessions[index]]
            else:
                current.append(sessions[index])
            prior_index = index
        if current:
            runs.append(current)
        if runs:
            longest = max(runs, key=len)
            contributor_counts = Counter(
                (mark["identity_ticker"], mark["identity_isu_cd"])
                for day in longest
                for mark in marks_by_scope_day[scope].get(day, [])
            )
            longest_gaps.append({
                "window": scope[0].upper().replace("_", "-"),
                "scenario": scope[1],
                "first_date": longest[0], "last_date": longest[-1],
                "consecutive_missing_trading_days": len(longest),
                "contributor_identities": "|".join(f"{k[0]}:{k[1]}({v})" for k, v in contributor_counts.most_common()),
                "distinct_contributor_identity_count": len(contributor_counts),
            })

    # Hash output inputs and build the explanatory report after all arithmetic.
    output = ROOT / output_relative
    output.mkdir(parents=True, exist_ok=True)
    output_files = {
        "missing_valuation_days.csv": missing_date_rows,
        "missing_identity_marks.csv": missing_identity_dates,
        "identity_impact.csv": identity_scope_rows,
        "cause_contribution.csv": cause_contribution_rows,
        "scenario_coverage.csv": scenario_coverage_rows,
        "day_classification.csv": day_class_rows,
        "top_identity_shares.csv": top_share_rows,
        "longest_missing_streaks.csv": longest_gaps,
        "raw_partition_audit.csv": raw_partition_audit,
    }
    for filename, rows in output_files.items():
        write_csv(output / filename, rows)
    write_json(output / "summary.json", summary)
    write_json(output / "input_verification.json", {
        "verified_replay_root_manifest": replay_manifest_checks,
        "verified_per_window_manifests": root_manifest_checks,
        "source_sha256": dict(sorted(source_hashes.items())),
        "adjusted_price_files": adjusted_file_metadata,
        "raw_partition_audit_count": len(raw_partition_audit),
        "raw_partition_invalid_count": summary["raw_partition_invalid_count"],
    })
    report = build_report(
        summary=summary,
        identity_rows=top_overall,
        identity_scope_rows=identity_scope_rows,
        cause_contribution_rows=cause_contribution_rows,
        scenario_rows=scenario_coverage_rows,
        day_class_rows=day_class_rows,
        longest_gaps=longest_gaps,
        top_share_rows=top_share_rows,
    )
    (output / "report.md").write_text(report, encoding="utf-8")

    generated = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "metadata.json"
    }
    metadata = {
        "study_id": summary["study_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_head": summary["start_head"],
        "audit_base_head": head,
        "audit_base_origin_main": origin,
        "start_worktree_status": raw_status,
        "replay_study_id": replay_metadata.get("study_id"),
        "replay_manifest_sha256": source_hashes[REPLAY_ROOT.joinpath("metadata.json").as_posix()],
        "raw_manifest_sha256": summary["krx_raw_manifest_sha256"],
        "verdict": verdict,
        "generated_files": generated,
        "production_changes": False,
        "official_history_modified": False,
        "permanent_exclusions_modified": False,
    }
    write_json(output / "metadata.json", metadata)
    print(json.dumps({
        "verdict": verdict,
        "output": output_relative.as_posix(),
        "missing_equity_day_rows": summary["missing_equity_day_rows"],
        "missing_valuation_mark_rows": summary["missing_valuation_mark_rows"],
        "exact_identities": summary["unique_exact_identities"],
        "raw_partitions_verified": summary["unique_krx_market_date_partitions_verified"],
        "placeholder_marks": summary["raw_nontrading_placeholder_marks"],
        "carry_eligible_marks": summary["scenario_b_carry_eligible_marks"],
        "cash_only_missing_days": summary["cash_only_missing_equity_day_count"],
        "equity_generation_bug_candidates": summary["position_missing_equity_without_missing_mark_count"],
    }, ensure_ascii=False))
    return output


def build_report(
    *,
    summary: Mapping[str, Any],
    identity_rows: Sequence[Mapping[str, Any]],
    identity_scope_rows: Sequence[Mapping[str, Any]],
    cause_contribution_rows: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    day_class_rows: Sequence[Mapping[str, Any]],
    longest_gaps: Sequence[Mapping[str, Any]],
    top_share_rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# B Select Daily Exit MDD Coverage 원인 감사 V01",
        "",
        f"- 판정: **`{summary['verdict']}`**",
        f"- 기준 HEAD / origin/main: `{summary['audit_base_head']}` / `{summary['audit_base_origin_main']}`",
        f"- MDD 원장 전체 {summary['total_scope_window_scenario_trading_days']:,} window×scenario 거래일 중 미확정 equity {summary['missing_equity_day_rows']:,}행 ({summary['missing_equity_day_row_pct']:.2f}%).",
        f"- missing mark {summary['missing_valuation_mark_rows']:,}행, exact identity {summary['unique_exact_identities']}개, KRX raw market/date partition {summary['unique_krx_market_date_partitions_verified']:,}개(결측 원장 {summary['missing_mark_market_date_partition_count']:,} + carry 기준일 {summary['carry_anchor_partition_count']:,})를 manifest로 검증했어.",
        f"- 비거래 placeholder: {summary['raw_nontrading_placeholder_marks']:,}/{summary['missing_valuation_mark_rows']:,}; valuation-only 직전 종가 적용 진단 가능: {summary['scenario_b_carry_eligible_marks']:,}/{summary['missing_valuation_mark_rows']:,} marks.",
        f"- 최신 rolling KRX basic-info: {summary['latest_krx_basic_info_asof']}; PIT frontier: {summary['pit_frontier']}.",
        "- 작업 범위는 원인 감사와 무변경 진단 계산이야. 전략, production, 공식 history, 중앙 영구 제외 authority와 기존 cadence 산출물은 고치지 않았어.",
        "- 이 분석은 봉인된 cadence replay의 missing marks를 사후 분해했어. 백테스트나 portfolio engine을 다시 실행하지 않았어.",
        "",
        "## 레벨",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        f"| CRITICAL | {1 if summary['portfolio_equity_generation_bug_found'] or summary['raw_partition_invalid_count'] else 0} |",
        f"| MAJOR | {1 if summary['missing_equity_day_rows'] and any(float(row['scenario_a_current_coverage_pct']) < 90 for row in scenario_rows) else 0} |",
        "| MINOR | 0 |",
        "",
        "## 1. Coverage gap 전체 요약",
        "",
        "각 기간의 missing day를 일별 equity 행, open-position 수, `MISSING_EXACT_DAILY_MARK` skip 원장으로 1:1 대조했어.",
        "",
        "| Window | 방식 | 전체 거래일 | 미확정 equity 일 | 현금-only 누락 | 보유+missing mark | 보유+skip 없는 누락 | 대조 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in day_class_rows:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['total_trading_days']} | {row['missing_equity_days']} | "
            f"{row['cash_only_day_missing']} | {row['position_day_with_missing_mark']} | {row['position_day_without_missing_mark']} | {row['classification']} |"
        )
    lines.extend([
        "",
        f"현금-only 누락은 {summary['cash_only_missing_equity_day_count']}일, missing mark 없이 equity만 빠진 날은 {summary['position_missing_equity_without_missing_mark_count']}일이야. 따라서 빈 포트폴리오의 cash valuation 누락이나 skip과 무관한 equity-row 생성 누락은 이 원장에서 발견되지 않았어.",
        "",
        "## 2. 원인별 기여도",
        "",
        "같은 날 여러 identity가 미평가일 수 있어 원인별 missing-day 수와 비율은 **비가산**이야. 표의 marks는 exact identity/date 행 수야.",
        "",
        "| Window | 방식 | 원인 | 영향 missing days | 전체 거래일 | 비율 | missing marks | identity 수 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in cause_contribution_rows:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['cause']} | {row['missing_day_count_non_additive']} | "
            f"{row['total_trading_days']} | {row['pct_of_total_trading_days']:.2f}% | {row['missing_valuation_mark_count']} | {row['unique_identity_count']} |"
        )
    lines.extend([
        "",
        "## 3. 영향도 상위 exact identity",
        "",
        "영향도는 5 window × 2 scenario에 반복해 기록된 exact missing mark 수 기준이야. window 간 중복을 포함하므로 독립 거래 수는 아니야.",
        "",
        "| ticker | ISU_CD | 최신 KRX 종목명 | 원인 | 최초/마지막 결측일 | missing marks | 전체 gap 비중 | 최대 연속 거래일 | 영향 window | exclusion |",
        "|---|---|---|---|---|---:|---:|---:|---|---|",
    ])
    for row in identity_rows:
        lines.append(
            f"| {row['ticker']} | {row['isu_cd']} | {row['company_name']} | {row['root_cause']} | "
            f"{row['first_missing_date']} / {row['last_missing_date']} | {row['missing_valuation_mark_count']} | "
            f"{row['missing_mark_pct_overall']:.2f}% | {row['max_consecutive_missing_days']} | {row['affected_windows']} | {'YES' if row['currently_permanently_excluded'] else 'NO'} |"
        )
    lines.extend([
        "",
        "아래는 전체 24 identity의 window/scenario별 세부값이야. 보유 거래일은 봉인 ENTRY/EXIT execution event 사이에서 exact identity 포지션이 열린 KRX 거래일 수로 계산했고, 전체 행은 `identity_impact.csv`에도 저장했어.",
        "",
        "| ticker | ISU_CD | Window | 방식 | 최초/마지막 결측일 | 고유 결측일 | 최대 연속 거래일 | 해당 범위 보유 거래일 | 범위 missing mark 비중 |",
        "|---|---|---|---|---|---:|---:|---:|---:|",
    ])
    for row in sorted(
        (item for item in identity_scope_rows if item["window"] != "ALL"),
        key=lambda item: (item["ticker"], item["window"], item["scenario"]),
    ):
        lines.append(
            f"| {row['ticker']} | {row['isu_cd']} | {row['window']} | {row['scenario']} | "
            f"{row['first_missing_date']} / {row['last_missing_date']} | {row['unique_missing_dates']} | "
            f"{row['max_consecutive_missing_days']} | {row['held_sessions_in_window']} | {row['missing_mark_pct_of_scope']:.2f}% |"
        )
    overall = next((row for row in top_share_rows if row["window"] == "ALL"), {})
    lines.extend([
        "",
        f"상위 1/3/5 identity가 전체 missing valuation marks의 {overall.get('top1_share_pct', 0):.2f}% / {overall.get('top3_share_pct', 0):.2f}% / {overall.get('top5_share_pct', 0):.2f}%를 차지해.",
        "",
        "## 4. P1 1,310일 연속 결측",
        "",
        "| 방식 | 시작 | 끝 | 최대 연속 거래일 | 구간 내 미평가 identity 기여 marks |",
        "|---|---|---|---:|---|",
    ])
    p1_long = [row for row in longest_gaps if row["window"] == "P1"]
    for row in p1_long:
        lines.append(f"| {row['scenario']} | {row['first_date']} | {row['last_date']} | {row['consecutive_missing_trading_days']} | {row['contributor_identities']} |")
    lines.extend([
        "",
        "이 구간은 단일 identity 1개가 1,310일 지속된 것이 아니라, 결측 기간이 겹치는 비거래 identity들이 구간을 이어 붙인 형태인지 표의 contributor를 기준으로 구분했어.",
        "",
        "## 5. P2/P3 394일 결측",
        "",
        "| Window | 방식 | 시작 | 끝 | 최대 연속 거래일 | 구간 내 기여 identity |",
        "|---|---|---|---|---:|---|",
    ])
    for row in longest_gaps:
        if row["window"] != "P1":
            lines.append(f"| {row['window']} | {row['scenario']} | {row['first_date']} | {row['last_date']} | {row['consecutive_missing_trading_days']} | {row['contributor_identities']} |")
    lines.extend([
        "",
        "## 6–8. 상장상태·제외정책·equity 생성",
        "",
        f"- missing mark exact identity는 {summary['unique_exact_identities']}개야. 각 identity의 같은 ticker·ISU COMMON PIT interval과 최신 KRX basic-info 등재 여부를 identity CSV에 저장했어. 상폐·successor는 PIT/기본정보가 뒷받침할 때만 분류했고, 이름이나 ticker만으로 추정하지 않았어.",
        f"- 중앙 영구 제외 authority는 {summary['current_exclusion_identity_count']}개 identity야. 봉인 replay의 exclusion authority SHA-256과 현재 파일은 {'일치해' if summary['replay_exclusion_policy_hash_matches_current'] else '불일치하거나 replay 기록이 없어'}. 감사 대상과 겹친 exact identity/mark는 {summary['current_exclusion_leak_identity_count']}개/{summary['current_exclusion_leak_mark_count']}건이야. 과거 RAW_DATA_GAP 제외 {summary['prior_raw_data_gap_exclusion_identity_count']}개, terminal/delisting 제외 {summary['prior_terminal_or_delisting_exclusion_identity_count']}개, successor-resolution 제외 {summary['prior_successor_resolution_exclusion_identity_count']}개 중 다시 나타난 identity는 각각 {summary['prior_raw_data_gap_exclusion_recurrence_identity_count']}/{summary['prior_terminal_or_delisting_exclusion_recurrence_identity_count']}/{summary['prior_successor_resolution_exclusion_recurrence_identity_count']}개야. 자동 exclusion은 하지 않았어.",
        f"- 빈 equity일 {summary['missing_equity_day_rows']:,}행은 모두 보유 포지션과 missing mark에 대응하고, cash-only 누락과 skip 없는 equity 누락은 0이야. portfolio equity 생성 버그는 발견되지 않았어.",
        "- KRX raw 행은 `KRX_RAW_STOCK_V01` manifest의 file/content SHA-256과 schema를 검증했어. 정확한 0-OHLC placeholder에 volume/trading value 0, close>0, listed shares>0이면 KRX 일별 원장상 비거래로만 분류했어. 공시 원인·법적 거래정지 사유는 별도 원문이 확인되지 않으면 추정하지 않았어.",
        "",
        "## 9. 변경 없는 coverage 시나리오",
        "",
        "시나리오 B는 모든 미평가 포지션이 exact KRX 비거래 placeholder이고, 같은 identity의 직전 exact KRX session에 거래된 정상 Repository V2 adjusted close가 있을 때만 valuation-only carry를 계산했어. 거래신호·체결·지표에는 적용하지 않았어.",
        "시나리오 C는 현재 산출물이 이미 174개 중앙 exclusion을 적용했고 missing mark leakage가 0이어서 현재 coverage와 같아. exclusion이 뒤늦게 필요한 행은 발견되지 않았어.",
        "",
        "| Window | 방식 | 총일수 | A 현재 coverage | B carry 회복일 | B 예상 coverage | C 제외 회복일 | C 예상 coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in scenario_rows:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['total_trading_days']} | {row['scenario_a_current_coverage_pct']:.2f}% | "
            f"{row['scenario_b_carry_recovered_days']} | {row['scenario_b_expected_coverage_pct']:.2f}% | "
            f"{row['scenario_c_already_approved_exclusion_recovered_days']} | "
            f"{row['scenario_c_expected_coverage_pct']:.2f}% |"
        )
    lines.extend([
        "",
        "## 10. 최소 remediation 제안",
        "",
        "전 기간 공통 forward-fill이나 새 permanent exclusion, lifecycle 엔진 수정을 제안하지 않아. KRX 원장에서 정밀하게 확인된 비거래 날짜에 한해서 동일 identity의 직전 정상 종가를 portfolio valuation에만 유지하는 좁은 규칙을 사용자 승인 후 진단 재구성에 적용하는 안이 최소 범위야. 승인 전에는 이번 보고의 시나리오 B가 진단치로만 남아.",
        "- 직전 정상 종가가 검증되지 않은 raw gap·identity gap은 `UNRESOLVED`로 유지해야 해.",
        "- 해당 identity 추가 영구 제외는 현재 자료로 지지되지 않아. 중앙 exclusion authority는 수정하지 않았어.",
        "- 기존 봉인 거래 이벤트를 사용해 valuation/equity만 재구성한 뒤 coverage/MDD gate를 재판정하면 돼. 전략은 재백테스트하지 않아.",
        "",
        "## Git / 검증",
        "",
        f"- 기준 저장소: `{summary['audit_base_head']}` / `origin/main` `{summary['audit_base_origin_main']}`.",
        f"- 유효 KRX raw partition 검증: {summary['unique_krx_market_date_partitions_verified']:,}개; 실패 {summary['raw_partition_invalid_count']}개.",
        f"- root/window replay manifest 및 adjusted file SHA-256 검증 결과는 `input_verification.json`에 있어.",
        "- 산출물: `missing_valuation_days.csv`, `missing_identity_marks.csv`, `identity_impact.csv`, `cause_contribution.csv`, `scenario_coverage.csv`, `day_classification.csv`, `top_identity_shares.csv`, `longest_missing_streaks.csv`, `raw_partition_audit.csv`, `summary.json`.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_RELATIVE)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
