#!/usr/bin/env python3
"""Realistic portfolio review for the frozen Pattern B E/T-only candidate.

The run reuses the certified candidate signal/trade artifacts and the common
P2-1 realistic cash/settlement engine. It does not recompute strategy signals.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402
from scripts import run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01 as study  # noqa: E402
from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as candidate_runner  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base  # noqa: E402
from scripts import run_p2_1_realistic_portfolio_v01 as portfolio  # noqa: E402
from scripts import run_v2_julia_official_validation_v01 as official_cost_authority  # noqa: E402

OUTPUT_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v01"
)
PLAN_REL = Path(
    "docs/patterns/pattern_b/strategy/"
    "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_REALISTIC_VALIDATION_PLAN_V01.md"
)
SCRIPT_REL = Path(__file__).relative_to(ROOT)
SOURCE_ROOT = study.OUTPUT_ROOT
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
RUNNABLE_WINDOWS = ("P2-1", "P2-2", "P3-1", "P3-2")
ALLOWED_DECISION = "PASS_EARLY_TREND_OR_TRANSITION"
NOT_FILLED_AFTER_END = "ENTRY_NOT_FILLED_AFTER_WINDOW_END"
WORKERS = 10
INITIAL_CAPITAL = 200_000_000.0
POSITION_BUDGET = 5_000_000.0
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
TAX_SCHEDULE = (
    ("2021-01-01", "2022-12-31", 0.0023),
    ("2023-01-01", "2023-12-31", 0.0020),
    ("2024-01-01", "2024-12-31", 0.0018),
    ("2025-01-01", "2025-12-31", 0.0015),
    ("2026-01-01", "2026-12-31", 0.0020),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean_json(value), ensure_ascii=False, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def clean_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).upper(),
        str(row.get("entry_signal_date", ""))[:10],
    )


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def window_dir(window_id: str) -> Path:
    return ROOT / SOURCE_ROOT / window_id.lower().replace("-", "_")


def verify_generated_files(source_dir: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, info in metadata.get("generated_files", {}).items():
        path = source_dir / name
        if not path.is_file():
            checks[name] = {"status": "MISSING", "expected_sha256": info.get("sha256")}
            continue
        actual = sha256(path)
        checks[name] = {
            "status": "PASS" if actual == info.get("sha256") else "MISMATCH",
            "expected_sha256": info.get("sha256"),
            "actual_sha256": actual,
        }
    bad = {name: row for name, row in checks.items() if row["status"] != "PASS"}
    if bad:
        raise RuntimeError(f"SAVED_CANDIDATE_OUTPUT_HASH_MISMATCH:{bad}")
    return checks


def load_window_inputs(window_id: str) -> dict[str, Any]:
    source_dir = window_dir(window_id)
    summary_path = source_dir / "summary.json"
    metadata_path = source_dir / "metadata.json"
    audit_path = source_dir / "previous_stage_audit.csv"
    ledger_path = source_dir / "test_trade_ledger.csv"
    for path in (summary_path, metadata_path, audit_path, ledger_path):
        if not path.is_file():
            raise RuntimeError(f"MISSING_SAVED_CANDIDATE_INPUT:{path.relative_to(ROOT)}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    audit = pd.read_csv(audit_path, dtype={"ticker": str, "isu_cd": str})
    ledger = pd.read_csv(ledger_path, dtype={"ticker": str, "isu_cd": str})
    generated_checks = verify_generated_files(source_dir, metadata)

    window = dict(summary["window"])
    resolved, resolved_contract = candidate_runner._resolve_window(ROOT, window_id)
    for field in ("effective_start", "effective_end", "execution_support"):
        if str(window.get(field))[:10] != str(resolved_contract[field])[:10]:
            raise RuntimeError(f"SAVED_WINDOW_RESOLUTION_MISMATCH:{window_id}:{field}")
    if candidate_runner.WORKERS != WORKERS:
        raise RuntimeError(f"SIGNAL_OR_MARKET_DATA_WORKER_COUNT_NOT_10:{candidate_runner.WORKERS}")

    ledger_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in ledger.to_dict(orient="records"):
        key = row_key(row)
        if key in ledger_by_key:
            raise RuntimeError(f"DUPLICATE_SAVED_LEDGER_KEY:{window_id}:{key}")
        ledger_by_key[key] = row

    passed = audit.loc[audit["new_test_gate_decision"].astype(str).eq(ALLOWED_DECISION)].copy()
    pass_rows = passed.to_dict(orient="records")
    if len({row_key(row) for row in pass_rows}) != len(pass_rows):
        raise RuntimeError(f"DUPLICATE_ALLOWED_SIGNAL_KEY:{window_id}")

    after_end = []
    matched_keys: set[tuple[str, str, str]] = set()
    for row in pass_rows:
        key = row_key(row)
        if key[2] > str(window["effective_end"])[:10]:
            raise RuntimeError(f"POST_CUTOFF_ENTRY_SIGNAL:{window_id}:{key}")
        if not as_bool(row.get("pattern_a_lookahead_free")):
            raise RuntimeError(f"LOOKAHEAD_SIGNAL:{window_id}:{key}")
        if str(row.get("pattern_a_requested_asof", ""))[:10] != key[2]:
            raise RuntimeError(f"NON_EXACT_PIT_STAGE_ASOF:{window_id}:{key}")
        status = str(row.get("simulated_entry_status", ""))
        if status == NOT_FILLED_AFTER_END:
            after_end.append(key)
            continue
        if status != "FILLED":
            raise RuntimeError(f"ALLOWED_SIGNAL_NOT_RECONCILED_TO_LEDGER:{window_id}:{key}:{status}")
        trade = ledger_by_key.get(key)
        if trade is None:
            raise RuntimeError(f"ALLOWED_FILLED_SIGNAL_WITHOUT_TRADE:{window_id}:{key}")
        if str(trade.get("pattern_a_stage")) != "PROGRESSED":
            raise RuntimeError(f"TRADE_CURRENT_STAGE_MISMATCH:{window_id}:{key}")
        if str(trade.get("previous_pattern_a_stage")) not in {"EARLY_TREND", "TRANSITION"}:
            raise RuntimeError(f"TRADE_PREVIOUS_STAGE_MISMATCH:{window_id}:{key}")
        matched_keys.add(key)
    if matched_keys != set(ledger_by_key):
        raise RuntimeError(
            f"SAVED_LEDGER_HAS_UNMATCHED_TRADES:{window_id}:"
            f"{len(set(ledger_by_key) - matched_keys)}"
        )

    # This exact audit proves no allowed future entry was omitted by an active
    # position in the saved unconstrained replay. The source signal generator
    # creates every adjacent Pattern B transition independently of positions.
    suppressed_allowed = [
        row for row in pass_rows
        if str(row.get("simulated_entry_status", "")) == "SUPPRESSED_ALREADY_HOLDING"
    ]
    if suppressed_allowed:
        raise RuntimeError(f"ALLOWED_SIGNAL_SUPPRESSED_BY_BASELINE_POSITION:{window_id}:{len(suppressed_allowed)}")

    validations = summary.get("validations", {})
    provenance = summary.get("source_provenance", {})
    if int(provenance.get("permanent_exclusion_identity_count", -1)) != 43:
        raise RuntimeError(f"PERMANENT_EXCLUSION_COUNT_MISMATCH:{window_id}")
    if int(provenance.get("raw_candidate_key_mismatch_count", -1)) != 0:
        raise RuntimeError(f"RAW_CANDIDATE_LINKAGE_MISMATCH:{window_id}")
    if int(validations.get("future_pattern_a_input_count", -1)) != 0:
        raise RuntimeError(f"SAVED_VALIDATION_LOOKAHEAD_NOT_ZERO:{window_id}")
    if int(validations.get("same_isu_overlap_count", -1)) != 0:
        raise RuntimeError(f"SAVED_VALIDATION_OVERLAP_NOT_ZERO:{window_id}")

    code_checks = {}
    for rel, expected in metadata.get("code_sha256", {}).items():
        path = ROOT / rel
        actual = sha256(path) if path.is_file() else None
        was_untracked_at_start = any(
            str(item).strip() == f"?? {rel}"
            for item in metadata.get("starting_git", {}).get("start_status", [])
        )
        code_checks[rel] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else ("RUN_SOURCE_UNTRACKED_AT_START" if was_untracked_at_start else "MISMATCH"),
        }
    source_head = str(metadata.get("starting_git", {}).get("head", ""))
    bootstrap_checks = {}
    for rel in (
        "scripts/run_pattern_b_pure_simple_backtest_v01.py",
        "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py",
    ):
        current_path = ROOT / rel
        try:
            baseline_bytes = subprocess.check_output(["git", "show", f"{source_head}:{rel}"], cwd=ROOT)
            baseline_sha = hashlib.sha256(baseline_bytes).hexdigest()
        except (subprocess.CalledProcessError, OSError):
            baseline_sha = None
        current_sha = sha256(current_path) if current_path.is_file() else None
        bootstrap_checks[rel] = {
            "starting_head": source_head,
            "starting_head_sha256": baseline_sha,
            "current_sha256": current_sha,
            "status": "PASS" if baseline_sha is not None and baseline_sha == current_sha else "MISMATCH",
        }
    if any(row["status"] == "MISMATCH" for row in code_checks.values() if row["status"] != "RUN_SOURCE_UNTRACKED_AT_START"):
        raise RuntimeError(f"SAVED_CANDIDATE_CODE_HASH_MISMATCH:{window_id}:{code_checks}")
    if any(row["status"] != "PASS" for row in bootstrap_checks.values()):
        raise RuntimeError(f"CANDIDATE_SIGNAL_SOURCE_CHANGED_SINCE_START_HEAD:{window_id}:{bootstrap_checks}")

    records = []
    for key in sorted(matched_keys):
        original = dict(ledger_by_key[key])
        entry_market_value = original.get("entry_market")
        if entry_market_value is None or pd.isna(entry_market_value) or not str(entry_market_value).strip():
            entry_market_value = original.get("signal_market")
        entry_market = str(entry_market_value or "").upper()
        exit_market_value = original.get("exit_market")
        if exit_market_value is None or pd.isna(exit_market_value) or not str(exit_market_value).strip():
            exit_market_value = entry_market
        exit_market = str(exit_market_value).upper()
        if exit_market != entry_market:
            raise RuntimeError(f"MARKET_TRANSFER_TRADE_UNSUPPORTED_BY_CERTIFIED_ENGINE:{window_id}:{key}")
        if entry_market not in {"KOSPI", "KOSDAQ"}:
            raise RuntimeError(f"UNSUPPORTED_ENTRY_MARKET:{window_id}:{key}:{entry_market}")
        def nullable(value: Any) -> Any:
            return None if value is None or pd.isna(value) else value

        record = {
            **original,
            "ticker": str(original.get("ticker", "")).zfill(6),
            "isu_cd": str(original.get("isu_cd", "")).upper(),
            "market": entry_market,
            "pair_id": str(original.get("trade_id")),
            "entry_price": original.get("entry_reference_open"),
            "exit_price": nullable(original.get("exit_reference_open")),
            "terminal_valuation_date": nullable(original.get("cutoff_valuation_date")),
            "terminal_valuation_price": nullable(original.get("cutoff_close")),
        }
        records.append(record)

    return {
        "window_id": window_id,
        "window": window,
        "resolved": resolved,
        "resolved_contract": resolved_contract,
        "summary": summary,
        "metadata": metadata,
        "source_dir": source_dir,
        "audit": audit,
        "ledger": ledger,
        "records": records,
        "pass_rows": pass_rows,
        "after_end_keys": after_end,
        "source_hashes": {
            "summary.json": sha256(summary_path),
            "metadata.json": sha256(metadata_path),
            "previous_stage_audit.csv": sha256(audit_path),
            "test_trade_ledger.csv": sha256(ledger_path),
        },
        "generated_file_checks": generated_checks,
        "code_checks": code_checks,
        "bootstrap_source_checks": bootstrap_checks,
        "orchestration_source_sha_verified": all(row["status"] == "PASS" for row in code_checks.values()),
        "suppressed_allowed_signal_count": 0,
    }


class ExactMarketCapPriority:
    """Hash-verified exact-date raw KRX cap lookup for neutral order only."""

    def __init__(self) -> None:
        self.store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
        self.partitions: dict[tuple[str, str], dict[str, Any]] = {}
        self.provenance: dict[str, dict[str, Any]] = {}

    def _load_partition(self, key: tuple[str, str]) -> tuple[tuple[str, str], dict[str, Any]]:
        market, day = key
        manifest = self.store.get_manifest(market, day)
        if manifest is None or manifest.get("status") != "COMPLETE":
            raise RuntimeError(f"EXACT_SIGNAL_DATE_CAP_PARTITION_NOT_COMPLETE:{market}:{day}:{manifest}")
        frame = self.store.load_snapshot(market, day)
        caps = {
            str(row.ticker).zfill(6): int(row.market_cap)
            for row in frame[["ticker", "market_cap"]].itertuples(index=False)
        }
        meta = {
            "status": manifest.get("status"),
            "file_path": manifest.get("file_path"),
            "file_sha256": manifest.get("file_sha256"),
            "content_sha256": manifest.get("content_sha256"),
            "row_count": int(len(frame)),
        }
        return key, {"caps": caps, "meta": meta}

    def attach(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        required = sorted({
            (
                str(row.get("signal_market", row.get("entry_market", ""))).upper(),
                str(row.get("entry_signal_date", ""))[:10],
            )
            for row in records
        })
        missing = [key for key in required if key not in self.partitions]
        if missing:
            with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pattern-b-mcap") as pool:
                futures = {pool.submit(self._load_partition, key): key for key in missing}
                for future in as_completed(futures):
                    key, value = future.result()
                    self.partitions[key] = value
                    self.provenance[f"{key[0]}:{key[1]}"] = value["meta"]
        missing_tickers = []
        for row in records:
            key = (
                str(row.get("signal_market", row.get("entry_market", ""))).upper(),
                str(row.get("entry_signal_date", ""))[:10],
            )
            ticker = str(row.get("ticker", "")).zfill(6)
            caps = self.partitions[key]["caps"]
            if ticker not in caps:
                missing_tickers.append((key, ticker))
            else:
                row["entry_market_cap"] = caps[ticker]
        if missing_tickers:
            raise RuntimeError(f"EXACT_SIGNAL_DATE_CAP_TICKER_MISSING:{missing_tickers[:10]}")
        return {
            "partition_count": len(required),
            "partitions": {f"{market}:{day}": self.partitions[(market, day)]["meta"] for market, day in required},
        }


def verify_execution_prices(
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    window: Mapping[str, Any],
) -> dict[str, Any]:
    mismatches = []
    missing = []
    terminal_exact_checked = 0
    terminal_unresolved_source_count = 0
    for row in records:
        entry_date = pd.Timestamp(row["entry_execution_date"]).normalize()
        entry_actual = portfolio._price(row, frames, entry_date, "open")
        entry_expected = pd.to_numeric(row.get("entry_reference_open"), errors="coerce")
        if entry_actual is None or pd.isna(entry_expected):
            missing.append({"trade_id": row.get("trade_id"), "event": "ENTRY", "date": str(entry_date.date())})
        elif not math.isclose(entry_actual, float(entry_expected), rel_tol=0, abs_tol=0.011):
            mismatches.append({"trade_id": row.get("trade_id"), "event": "ENTRY", "actual": entry_actual, "expected": float(entry_expected)})
        exit_date_raw = row.get("exit_execution_date")
        if str(row.get("trade_status")) == "REALIZED" and exit_date_raw not in (None, "") and not pd.isna(exit_date_raw):
            exit_date = pd.Timestamp(exit_date_raw).normalize()
            exit_actual = portfolio._price(row, frames, exit_date, "open")
            exit_expected = pd.to_numeric(row.get("exit_reference_open"), errors="coerce")
            if exit_actual is None or pd.isna(exit_expected):
                missing.append({"trade_id": row.get("trade_id"), "event": "EXIT", "date": str(exit_date.date())})
            elif not math.isclose(exit_actual, float(exit_expected), rel_tol=0, abs_tol=0.011):
                mismatches.append({"trade_id": row.get("trade_id"), "event": "EXIT", "actual": exit_actual, "expected": float(exit_expected)})
        if str(row.get("trade_status")) == "OPEN_AT_CUTOFF":
            if str(row.get("valuation_status")) == "MARKED_EXACT_CUTOFF_CLOSE":
                terminal_exact_checked += 1
                day = pd.Timestamp(window["effective_end"]).normalize()
                actual_close = portfolio._price(row, frames, day, "close")
                expected_close = pd.to_numeric(row.get("cutoff_close"), errors="coerce")
                if actual_close is None or pd.isna(expected_close):
                    missing.append({"trade_id": row.get("trade_id"), "event": "TERMINAL_CLOSE", "date": str(day.date())})
                elif not math.isclose(actual_close, float(expected_close), rel_tol=0, abs_tol=0.011):
                    mismatches.append({"trade_id": row.get("trade_id"), "event": "TERMINAL_CLOSE", "actual": actual_close, "expected": float(expected_close)})
            else:
                terminal_unresolved_source_count += 1
    if missing or mismatches:
        raise RuntimeError(f"SAVED_LEDGER_EXECUTION_PRICE_MISMATCH:missing={missing[:5]} mismatches={mismatches[:5]}")
    return {
        "checked_entries_and_realized_exits": len(records),
        "missing_exact_opens": 0,
        "price_mismatch_count": 0,
        "terminal_exact_close_count": terminal_exact_checked,
        "terminal_unresolved_source_count": terminal_unresolved_source_count,
    }


def build_component_frames(
    records: list[dict[str, Any]],
    daily_by_ticker: Mapping[str, pd.DataFrame | None],
    intervals: list[dict[str, Any]],
    trading_dates: Sequence[str],
) -> dict[str, pd.DataFrame]:
    _interval_to_component, intervals_by_component = pattern_b_base._interval_components(intervals, list(trading_dates))
    component_cache: dict[tuple[str, str, str], tuple[pd.DataFrame, str, str]] = {}
    exact_frames: dict[str, pd.DataFrame] = {}
    for row in records:
        ticker = str(row.get("ticker", "")).zfill(6)
        isu_cd = str(row.get("isu_cd", "")).upper()
        component_id = str(row.get("component_id", ""))
        component_key = (ticker, isu_cd, component_id)
        cached = component_cache.get(component_key)
        if cached is None:
            authorized_intervals = intervals_by_component.get(component_key, [])
            if not authorized_intervals:
                raise RuntimeError(f"MISSING_PIT_COMMON_COMPONENT_INTERVALS:{component_key}")
            daily = daily_by_ticker.get(ticker)
            frame = pattern_b_base._component_price_rows(daily, authorized_intervals, component_id)
            if not frame.empty:
                frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
            start = min(str(item["effective_from"])[:10] for item in authorized_intervals)
            end = max(str(item["effective_to"])[:10] for item in authorized_intervals)
            cached = (frame, start, end)
            component_cache[component_key] = cached
        frame, start, end = cached
        if frame.empty:
            raise RuntimeError(f"EMPTY_PIT_COMPONENT_PRICE_FRAME:{component_key}")
        row["identity_effective_from"] = start
        row["identity_effective_to"] = end
        frame_key = "|".join((ticker, isu_cd, str(row.get("market", "")).upper(), start, end))
        prior = exact_frames.get(frame_key)
        if prior is not None and not prior.equals(frame):
            raise RuntimeError(f"NONDETERMINISTIC_PIT_COMPONENT_FRAME:{component_key}")
        exact_frames[frame_key] = frame
    return exact_frames


def exact_close_without_carry(
    record: Mapping[str, Any],
    frames: Mapping[Any, pd.DataFrame],
    day: pd.Timestamp,
    _trading_session_positions: Mapping[pd.Timestamp, int],
    _gap_classifications: Mapping[tuple[str, str], str],
    *,
    strategy_id: str,
    pair_id: str,
) -> tuple[float | None, dict[str, Any] | None]:
    if (
        str(record.get("trade_status")) == "OPEN_AT_CUTOFF"
        and str(record.get("valuation_status")) != "MARKED_EXACT_CUTOFF_CLOSE"
        and pd.Timestamp(day).normalize() == pd.Timestamp(record.get("cutoff_date")).normalize()
    ):
        return None, {
            "strategy_id": strategy_id,
            "pair_id": pair_id,
            "trade_id": record.get("trade_id"),
            "ticker": str(record.get("ticker", "")).zfill(6),
            "identity": record.get("isu_cd"),
            "valuation_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
            "status": "UNRESOLVED_IN_SOURCE_TERMINAL_VALUATION",
            "used_for_execution": False,
        }
    close = portfolio._price(record, frames, day, "close")
    if close is None:
        return None, {
            "strategy_id": strategy_id,
            "pair_id": pair_id,
            "trade_id": record.get("trade_id"),
            "ticker": str(record.get("ticker", "")).zfill(6),
            "identity": record.get("isu_cd"),
            "valuation_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
            "status": "UNRESOLVED_MISSING_EXACT_DAILY_CLOSE",
            "used_for_execution": False,
        }
    return close, None


def run_replay(
    records: list[dict[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    trading_dates: Sequence[str],
    window: Mapping[str, Any],
    strategy_id: str,
) -> dict[str, Any]:
    original_schedule = portfolio.SELL_TAX_SCHEDULE
    original_valuation = portfolio._valuation_close_with_carry
    original_capital = portfolio.INITIAL_CAPITAL
    original_budget = portfolio.POSITION_BUDGET
    portfolio.SELL_TAX_SCHEDULE = tuple((start, end, rate) for start, end, rate in TAX_SCHEDULE)
    portfolio.INITIAL_CAPITAL = INITIAL_CAPITAL
    portfolio.POSITION_BUDGET = POSITION_BUDGET
    portfolio._valuation_close_with_carry = exact_close_without_carry
    try:
        result = portfolio._portfolio_replay(
            records,
            frames,
            [pd.Timestamp(day).normalize() for day in trading_dates],
            strategy_id=strategy_id,
            effective_start=pd.Timestamp(window["effective_start"]).normalize(),
            effective_end=pd.Timestamp(window["effective_end"]).normalize(),
            execution_support=pd.Timestamp(window["execution_support"]).normalize(),
        )
    finally:
        portfolio.SELL_TAX_SCHEDULE = original_schedule
        portfolio.INITIAL_CAPITAL = original_capital
        portfolio.POSITION_BUDGET = original_budget
        portfolio._valuation_close_with_carry = original_valuation
    return result


def tax_rate(day: str, market: str) -> float:
    date = pd.Timestamp(day).normalize()
    if market not in {"KOSPI", "KOSDAQ"}:
        raise RuntimeError(f"UNSUPPORTED_SELL_TAX_MARKET:{market}")
    for start, end, rate in TAX_SCHEDULE:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return rate
    raise RuntimeError(f"NO_AUTHORITATIVE_SELL_TAX_RATE:{day}:{market}")


def attach_peak(equity_rows: list[dict[str, Any]]) -> None:
    peak = INITIAL_CAPITAL
    for row in equity_rows:
        value = row.get("equity")
        if value is None or pd.isna(value):
            row["peak_equity"] = None
            continue
        peak = max(peak, float(value))
        row["peak_equity"] = peak


def build_portfolio_diagnostics(
    replay: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    window: Mapping[str, Any],
    source_summary: Mapping[str, Any],
) -> dict[str, Any]:
    events = replay["events"]
    equity_rows = replay["daily_equity"]
    entry_by_id = {
        str(row["pair_id"]): row
        for row in events
        if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
    }
    exit_by_id = {
        str(row["pair_id"]): row
        for row in events
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
    }
    record_by_id = {str(row["pair_id"]): row for row in records}
    realized = []
    open_at_end = []
    ticker_net_pnl: dict[str, float] = {}
    unresolved_terminal = []
    for pair_id, buy in entry_by_id.items():
        record = record_by_id[pair_id]
        buy_cost = float(buy["notional"]) + float(buy["commission"])
        sell = exit_by_id.get(pair_id)
        if sell is not None:
            proceeds = float(sell["notional"]) - float(sell["commission"]) - float(sell["sell_tax"])
            pnl = proceeds - buy_cost
            trade_return = pnl / buy_cost * 100.0 if buy_cost else None
            realized.append({"pair_id": pair_id, "ticker": buy["ticker"], "net_pnl_krw": pnl, "net_return_pct": trade_return})
            ticker_net_pnl[buy["ticker"]] = ticker_net_pnl.get(buy["ticker"], 0.0) + pnl
        else:
            mark = portfolio._price(record, frames, pd.Timestamp(window["effective_end"]), "close")
            if mark is None:
                unresolved_terminal.append({
                    "pair_id": pair_id,
                    "ticker": buy["ticker"],
                    "entry_cost_krw": buy_cost,
                    "entry_cost_upper_bound_pct_initial_capital": buy_cost / INITIAL_CAPITAL * 100.0,
                })
                open_at_end.append({"pair_id": pair_id, "ticker": buy["ticker"], "net_return_pct": None, "status": "UNRESOLVED"})
            else:
                mark_value = float(mark) * int(buy["shares"])
                unrealized = (mark_value - buy_cost) / buy_cost * 100.0 if buy_cost else None
                open_at_end.append({"pair_id": pair_id, "ticker": buy["ticker"], "net_return_pct": unrealized, "status": "OPEN_AT_CUTOFF_EXACT_CLOSE"})

    returns = [float(row["net_return_pct"]) for row in realized if row["net_return_pct"] is not None]
    return_array = np.asarray(returns, dtype=float)
    holdings = [
        int(row["holding_trading_days"])
        for row in events
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED" and row.get("holding_trading_days") is not None
    ]
    # Certified engine's exit event rows do not carry holding days; derive exact
    # session-inclusive duration from execution dates and the certified calendar.
    dates = [pd.Timestamp(row["date"]).normalize() for row in equity_rows]
    date_positions = {day: index for index, day in enumerate(dates)}
    for row in realized:
        buy = entry_by_id[row["pair_id"]]
        sell = exit_by_id[row["pair_id"]]
        start = pd.Timestamp(buy["execution_date"]).normalize()
        end = pd.Timestamp(sell["execution_date"]).normalize()
        if start in date_positions and end in date_positions:
            holdings.append(date_positions[end] - date_positions[start] + 1)

    positive_pnl = sum(max(0.0, row["net_pnl_krw"]) for row in realized)
    negative_pnl = sum(abs(min(0.0, row["net_pnl_krw"])) for row in realized)
    ranked_tickers = sorted(ticker_net_pnl.items(), key=lambda item: item[1], reverse=True)
    winners = sorted((value for _ticker, value in ticker_net_pnl.items() if value > 0), reverse=True)
    losers = sorted((value for _ticker, value in ticker_net_pnl.items() if value < 0))
    winner_shares = [value / positive_pnl for value in winners if positive_pnl] if positive_pnl else []
    year_rows = []
    curve = pd.DataFrame(equity_rows)
    valid = curve.loc[
        curve["date"].astype(str).le(str(window["effective_end"])[:10])
        & curve["equity"].notna()
    ].copy()
    valid["year"] = valid["date"].astype(str).str[:4]
    year_end_equity = valid.groupby("year", sort=True).tail(1).set_index("year")["equity"].to_dict()
    prior = INITIAL_CAPITAL
    for year, ending in sorted(year_end_equity.items()):
        ending = float(ending)
        year_rows.append({"year": int(year), "ending_equity_krw": ending, "annual_return_pct": (ending / prior - 1.0) * 100.0 if prior else None})
        prior = ending

    diagnostics = {
        "realized_trade_count": len(realized),
        "positive_trade_rate_pct": float((return_array > 0).mean() * 100.0) if len(return_array) else None,
        "median_net_trade_return_pct": float(np.median(return_array)) if len(return_array) else None,
        "tail_counts": {
            "+30": int((return_array >= 30).sum()),
            "+50": int((return_array >= 50).sum()),
            "+100": int((return_array >= 100).sum()),
            "-30": int((return_array <= -30).sum()),
            "-40": int((return_array <= -40).sum()),
            "-50": int((return_array <= -50).sum()),
            "-60": int((return_array <= -60).sum()),
        },
        "mean_holding_krx_sessions": float(np.mean(holdings)) if holdings else None,
        "median_holding_krx_sessions": float(np.median(holdings)) if holdings else None,
        "p90_holding_krx_sessions": float(np.quantile(holdings, 0.9)) if holdings else None,
        "average_concurrent_positions": replay["metrics"].get("average_concurrent_positions"),
        "maximum_concurrent_positions": replay["metrics"].get("maximum_concurrent_positions"),
        "average_cash_utilization_pct": replay["metrics"].get("average_capital_utilization_pct"),
        "maximum_cash_utilization_pct": replay["metrics"].get("maximum_capital_utilization_pct"),
        "turnover_krw": replay["metrics"].get("turnover_krw"),
        "turnover_multiple_initial_capital": replay["metrics"].get("turnover_multiple"),
        "ticker_net_pnl_concentration": {
            "top_ticker_positive_pnl_share_pct": max(winner_shares) * 100.0 if winner_shares else None,
            "top5_winner_contribution_to_positive_pnl_pct": sum(winners[:5]) / positive_pnl * 100.0 if positive_pnl else None,
            "top5_loser_contribution_to_negative_pnl_pct": sum(abs(value) for value in losers[:5]) / negative_pnl * 100.0 if negative_pnl else None,
            "top5_tickers_by_net_pnl_krw": [{"ticker": ticker, "net_pnl_krw": pnl} for ticker, pnl in ranked_tickers[:5]],
        },
        "annual_performance": year_rows,
        "deep_arrival_candidate_diagnostic": source_summary.get("new_test_lifecycle_summary", {}).get("deep_cohort", {}),
        "deep_arrival_note": "Candidate-level stored diagnostic; exact portfolio-executed DEEP membership was not present in the frozen source ledger.",
        "open_at_cutoff_count": len(open_at_end),
        "open_at_cutoff_exact_mark_count": sum(row["status"] == "OPEN_AT_CUTOFF_EXACT_CLOSE" for row in open_at_end),
        "open_at_cutoff_unresolved_count": len(unresolved_terminal),
        "unresolved_terminal_max_initial_cost_exposure_krw": sum(row["entry_cost_krw"] for row in unresolved_terminal),
        "unresolved_terminal_max_initial_cost_exposure_pct": sum(row["entry_cost_upper_bound_pct_initial_capital"] for row in unresolved_terminal),
        "realized_trades": realized,
        "open_trades": open_at_end,
        "unresolved_terminal_positions": unresolved_terminal,
    }
    return diagnostics


def write_window_outputs(
    inputs: Mapping[str, Any],
    replay: Mapping[str, Any],
    frames: Mapping[Any, pd.DataFrame | None],
    loader_audit: Mapping[str, Any],
    cap_audit: Mapping[str, Any],
    price_audit: Mapping[str, Any],
) -> dict[str, Any]:
    window_id = str(inputs["window_id"])
    window = inputs["window"]
    out = ROOT / OUTPUT_ROOT / window_id.lower().replace("-", "_")
    out.mkdir(parents=True, exist_ok=False)
    equity_rows = [dict(row) for row in replay["daily_equity"]]
    attach_peak(equity_rows)
    events = [dict(row) for row in replay["events"]]
    skipped = [dict(row) for row in replay["skipped"]]
    candidate_audit = [dict(row) for row in replay["entry_candidate_audit"]]
    valuation_audit = [dict(row) for row in replay["valuation_gap_audit"]]
    for row in skipped:
        if row.get("skip_reason") == "MISSING_EXACT_DAILY_MARK":
            valuation_audit.append({
                "pair_id": row.get("pair_id"), "ticker": row.get("ticker"),
                "valuation_date": str(row.get("date", ""))[:10],
                "status": "UNRESOLVED_MISSING_EXACT_DAILY_CLOSE",
                "used_for_execution": False,
            })
    event_by_pair: dict[str, dict[str, dict[str, Any]]] = {}
    for row in events:
        event_by_pair.setdefault(str(row.get("pair_id", "")), {})[str(row.get("event_type", ""))] = row
    record_by_pair = {str(row["pair_id"]): row for row in inputs["records"]}
    cost_audit = []
    cash_audit = []
    for row in events:
        if row.get("event_status") != "EXECUTED":
            continue
        is_exit = row.get("event_type") == "EXIT"
        rate = tax_rate(str(row["execution_date"]), str(row.get("market", "")).upper()) if is_exit else 0.0
        cost_audit.append({
            **row,
            "commission_rate": COMMISSION_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "sell_tax_rate": rate,
            "sell_tax_authority_start": next((start for start, end, _rate in TAX_SCHEDULE if pd.Timestamp(start) <= pd.Timestamp(row["execution_date"]) <= pd.Timestamp(end)), None) if is_exit else None,
            "cost_coverage_status": "AUTHORITATIVE_COMPLETE",
        })
        cash_audit.append({
            "pair_id": row.get("pair_id"), "ticker": row.get("ticker"),
            "date": row.get("execution_date"), "event_type": row.get("event_type"),
            "event_status": row.get("event_status"), "cash_before": row.get("cash_before"),
            "cash_after": row.get("cash_after"), "pending_sale_proceeds": row.get("pending_sale_proceeds"),
            "notional": row.get("notional"), "commission": row.get("commission"), "sell_tax": row.get("sell_tax"),
        })

    pass_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in inputs["pass_rows"]:
        key = row_key(row)
        pass_by_identity.setdefault((key[0], key[1]), []).append(row)
    for rows in pass_by_identity.values():
        rows.sort(key=lambda item: str(item.get("entry_signal_date", ""))[:10])
    cash_skip_lifecycle = []
    for event in events:
        if event.get("event_type") != "ENTRY" or event.get("event_status") != "SKIPPED_CASH_UNAVAILABLE":
            continue
        identity = (str(event.get("ticker", "")).zfill(6), str(record_by_pair[str(event["pair_id"])].get("isu_cd", "")).upper())
        entry_signal = str(event.get("signal_date", ""))[:10]
        later = [
            row for row in pass_by_identity.get(identity, [])
            if str(row.get("entry_signal_date", ""))[:10] > entry_signal
        ]
        cash_skip_lifecycle.append({
            "ticker": identity[0], "isu_cd": identity[1], "cash_skipped_signal_date": entry_signal,
            "later_allowed_signal_count": len(later),
            "later_allowed_signal_dates": [str(row.get("entry_signal_date", ""))[:10] for row in later],
            "all_later_signals_in_saved_event_stream": True,
            "baseline_suppressed_allowed_signal_count": inputs["suppressed_allowed_signal_count"],
            "ledger_only_omission_count": 0,
            "audit_status": "PASS_EXACT_COMPLETE_ALLOWED_SIGNAL_STREAM",
        })

    diagnostics = build_portfolio_diagnostics(replay, inputs["records"], frames, window, inputs["summary"])
    attempts = len([
        row for row in candidate_audit
        if row.get("decision") in {"EXECUTED", "CASH_INSUFFICIENT"}
    ])
    cash_skips = int(replay["metrics"].get("cash_shortage_skipped_entries", 0) or 0)
    skip_rate = cash_skips / attempts * 100.0 if attempts else 0.0
    exact_gap_count = sum(row.get("status") == "UNRESOLVED_MISSING_EXACT_DAILY_CLOSE" for row in valuation_audit)
    cost_rows_missing = sum(row.get("cost_coverage_status") != "AUTHORITATIVE_COMPLETE" for row in cost_audit)
    realized_sell_events = [row for row in cost_audit if row.get("event_type") == "EXIT"]
    equity_gap_days = sum(
        row.get("equity") is None or pd.isna(row.get("equity"))
        for row in equity_rows
        if str(row.get("date", "")) <= str(window["effective_end"])[:10]
    )
    gate_a = "PASS"
    if replay["metrics"].get("cash_conservation_pass") is not True or exact_gap_count or not equity_rows or any(row.get("equity") is None for row in equity_rows if row["date"] <= window["effective_end"]):
        gate_a = "CHECK_REQUIRED"
    if not inputs["orchestration_source_sha_verified"]:
        gate_a = "CHECK_REQUIRED"
    gate_b = "PASS" if cost_rows_missing == 0 and len(realized_sell_events) == sum(row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED" for row in events) else "FAIL"
    net_return = replay["metrics"].get("cumulative_return_pct")
    cagr = replay["metrics"].get("CAGR_pct")
    gate_c = "PASS" if net_return is not None and cagr is not None and net_return > 0 and cagr > 0 else ("FAIL" if net_return is not None and cagr is not None else "CHECK_REQUIRED")
    mdd = replay["metrics"].get("mdd_pct")
    gate_d = "CHECK_REQUIRED" if equity_gap_days else ("PASS" if mdd is not None and mdd >= -35.0 else ("FAIL" if mdd is not None else "CHECK_REQUIRED"))
    gate_e = "PASS" if skip_rate < 10.0 else "FAIL"
    unresolved_count = int(replay["metrics"].get("unresolved_count", 0) or 0)
    gate_f = "PASS" if unresolved_count == 0 and exact_gap_count == 0 else "CHECK_REQUIRED"
    metrics = {
        "window_id": window_id,
        "effective_start": window["effective_start"],
        "effective_end": window["effective_end"],
        "execution_support": window["execution_support"],
        "portfolio_metrics": replay["metrics"],
        "cash_shortage_skip_attempt_denominator": attempts,
        "cash_shortage_skip_count": cash_skips,
        "cash_shortage_skip_rate_pct": skip_rate,
        "exact_daily_valuation_gap_count": exact_gap_count,
        "daily_equity_gap_day_count": equity_gap_days,
        "diagnostics": diagnostics,
        "gates": {"A": gate_a, "B": gate_b, "C": gate_c, "D": gate_d, "E": gate_e, "F": gate_f},
        "portfolio_replay_method": "ledger-only replay with exact all-allowed-signal-stream audit; no allowed signal was suppressed in the baseline lifecycle source",
        "source_window_candidate_count": len(inputs["pass_rows"]),
        "source_filled_trade_count": len(inputs["records"]),
        "source_after_end_unfilled_count": len(inputs["after_end_keys"]),
        "orchestration_source_sha_verified": inputs["orchestration_source_sha_verified"],
        "orchestration_code_checks": inputs["code_checks"],
        "bootstrap_signal_source_checks": inputs["bootstrap_source_checks"],
        "unresolved_source_ticker_count": sum(1 for row in loader_audit.values() if row.get("status") == "EXPLICIT_DATA_UNAVAILABLE"),
        "repository_v2_silent_inner_drop_count": sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values()),
    }

    execution_contract = {
        "window": window,
        "strategy_id": "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01",
        "portfolio": {
            "initial_capital_krw": INITIAL_CAPITAL,
            "per_position_total_buy_budget_krw": POSITION_BUDGET,
            "position_cap": None,
            "partial_fill": False,
            "cash_shortage_status": "SKIPPED_CASH_UNAVAILABLE",
            "same_open_exit_reentry": False,
            "same_ticker_pit_signal_market_cap_priority_only": True,
            "same_day_order": "release previously settled proceeds; exits sorted by ticker/trade_id; entries sorted PIT signal-date market_cap descending, ticker ascending, pair_id ascending",
            "sale_proceeds_settlement": "next exact KRX session; not available to same-open entries",
            "market_data_workers": WORKERS,
            "portfolio_replay": "sequential deterministic; scripts/run_p2_1_realistic_portfolio_v01.py::_portfolio_replay",
        },
        "costs": {
            "buy_commission_rate": COMMISSION_RATE,
            "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE,
            "sell_slippage_rate": SLIPPAGE_RATE,
            "sell_tax_schedule": [
                {"start": start, "end": end, "KOSPI": rate, "KOSDAQ": rate,
                 "source": "scripts/run_v2_julia_official_validation_v01.py::HISTORICAL_SELL_TAX_SCHEDULE"}
                for start, end, rate in TAX_SCHEDULE
            ],
            "sell_tax_authority_first_date": "2021-01-01",
            "P1_2014_2020_status": "CHECK_REQUIRED_NO_REPLAY_NO_RATE_INVENTION",
        },
        "valuation": {
            "daily_mark": "exact Repository V2 close only; missing value unresolved; no carry, proxy, nearest-day, or forward fill",
            "terminal_open": "exact effective-end close; no sell fee/tax/slippage or reinvestment",
            "drawdown": "daily equity / running peak - 1; MDD is the minimum",
            "turnover": "executed buy and sell notional before costs divided by initial capital",
        },
        "inputs": {
            "saved_candidate_source": str(inputs["source_dir"].relative_to(ROOT)),
            "saved_source_sha256": inputs["source_hashes"],
            "exact_cap_priority_partition_audit": cap_audit,
            "execution_price_parity_audit": price_audit,
        },
    }
    json_write(out / "execution_contract.json", execution_contract)
    pd.DataFrame(events).to_csv(out / "portfolio_events.csv", index=False, encoding="utf-8")
    pd.DataFrame(equity_rows).to_csv(out / "daily_equity.csv", index=False, encoding="utf-8")
    pd.DataFrame(skipped).to_csv(out / "skipped_entries.csv", index=False, encoding="utf-8")
    pd.DataFrame(cost_audit).to_csv(out / "cost_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(cash_audit).to_csv(out / "cash_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(valuation_audit).to_csv(out / "valuation_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(candidate_audit).to_csv(out / "entry_attempt_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(cash_skip_lifecycle).to_csv(out / "cash_skip_lifecycle_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(diagnostics["annual_performance"]).to_csv(out / "annual_performance.csv", index=False, encoding="utf-8")
    json_write(out / "hidden_position_cap_audit.json", {
        "configured_position_cap": None,
        "maximum_concurrent_positions": replay["metrics"].get("maximum_concurrent_positions"),
        "position_limit_skip_count": sum(str(row.get("event_status", "")).startswith("SKIPPED_POSITION") for row in events),
        "status": "PASS_NO_POSITION_CAP_OR_POSITION_LIMIT_SKIP",
    })
    json_write(out / "metrics.json", metrics)
    return metrics


def p1_cost_gap() -> dict[str, Any]:
    source_dir = window_dir("P1")
    ledger_path = source_dir / "test_trade_ledger.csv"
    ledger = pd.read_csv(ledger_path, dtype={"ticker": str, "isu_cd": str})
    realized = ledger.loc[ledger["trade_status"].astype(str).eq("REALIZED")].copy()
    pre_2021 = realized.loc[realized["exit_execution_date"].astype(str).str[:4].astype(int).lt(2021)]
    missing = pre_2021.loc[pre_2021["sell_tax_rate"].isna()]
    coverage_start = min(row["start"] for row in official_cost_authority.HISTORICAL_SELL_TAX_SCHEDULE)
    if coverage_start != "2021-01-01":
        raise RuntimeError(f"UNEXPECTED_TAX_AUTHORITY_START:{coverage_start}")
    return {
        "status": "CHECK_REQUIRED" if len(missing) else "PASS",
        "authoritative_schedule_start": coverage_start,
        "pre_2021_realized_exit_count_in_saved_P1_ledger": int(len(pre_2021)),
        "pre_2021_realized_exit_missing_tax_count": int(len(missing)),
        "p1_full_cost_portfolio_replay_performed": False,
        "reason": "Repository tax schedule has no verified 2014-2020 rates; no rate was inferred and missing taxes would alter cash availability and portfolio paths.",
        "source": {
            "schedule_code": "scripts/run_v2_julia_official_validation_v01.py::HISTORICAL_SELL_TAX_SCHEDULE",
            "existing_trade_ledger": str(ledger_path.relative_to(ROOT)),
            "trade_ledger_sha256": sha256(ledger_path),
        },
    }


def run_preflight() -> dict[str, Any]:
    out_root = ROOT / OUTPUT_ROOT
    out_root.mkdir(parents=True, exist_ok=True)
    preflight_path = out_root / "preflight.json"
    if preflight_path.exists():
        raise RuntimeError("PREFLIGHT_ALREADY_EXISTS_AUTOMATIC_RETRY_FORBIDDEN")
    inputs = load_window_inputs("P2-1")
    records = inputs["records"]
    if len(records) < 20:
        raise RuntimeError("PREFLIGHT_SAMPLE_TOO_SMALL")
    sample_n = min(30, len(records))
    indices = np.linspace(0, len(records) - 1, num=sample_n, dtype=int)
    sample_records = [dict(records[int(index)]) for index in sorted(set(indices.tolist()))]
    sample_tickers = sorted({str(row["ticker"]).zfill(6) for row in sample_records})
    started = time.perf_counter()
    cpu_started = time.process_time()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    load_started = time.perf_counter()
    daily_frames, loader_audit, repository = candidate_runner._load_prices(
        ROOT, sample_tickers, inputs["window"]["effective_start"], inputs["window"]["execution_support"],
    )
    price_load_seconds = time.perf_counter() - load_started
    _intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    component_started = time.perf_counter()
    frames = build_component_frames(sample_records, daily_frames, _intervals, trading_dates)
    component_frame_seconds = time.perf_counter() - component_started
    cap_started = time.perf_counter()
    cap_lookup = ExactMarketCapPriority()
    cap_audit = cap_lookup.attach(sample_records)
    cap_seconds = time.perf_counter() - cap_started
    price_audit = verify_execution_prices(sample_records, frames, inputs["window"])
    replay_started = time.perf_counter()
    replay = run_replay(
        sample_records, frames, trading_dates, inputs["window"],
        "PATTERN_B_ET_REALISTIC_PREFLIGHT_P2_1",
    )
    replay_seconds = time.perf_counter() - replay_started
    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_scale = 1 if sys.platform == "darwin" else 1024
    full_work = {}
    total_estimate = 0.0
    sample_days = sum(
        1 for day in trading_dates
        if inputs["window"]["effective_start"] <= day <= inputs["window"]["execution_support"]
    )
    avg_load_s_per_ticker = price_load_seconds / max(1, len(sample_tickers))
    avg_cap_s_per_partition = cap_seconds / max(1, int(cap_audit["partition_count"]))
    for window_id in RUNNABLE_WINDOWS:
        info = load_window_inputs(window_id)
        active_tickers = sorted({str(row["ticker"]).zfill(6) for row in info["records"]})
        _ints, dates, _auth = pattern_b_base._load_authorities(ROOT)
        day_count = sum(
            1 for day in dates
            if info["window"]["effective_start"] <= day <= info["window"]["execution_support"]
        )
        cap_keys = {
            (str(row.get("signal_market", row.get("entry_market", ""))).upper(), str(row.get("entry_signal_date", ""))[:10])
            for row in info["records"]
        }
        price_estimate = avg_load_s_per_ticker * len(active_tickers)
        cap_estimate = avg_cap_s_per_partition * len(cap_keys)
        replay_estimate = replay_seconds * (len(info["records"]) / max(1, sample_n)) * (day_count / max(1, sample_days))
        estimate = price_estimate + cap_estimate + replay_estimate + 3.0
        total_estimate += estimate
        full_work[window_id] = {
            "unique_ticker_count": len(active_tickers),
            "candidate_trade_count": len(info["records"]),
            "exact_mcap_partition_count": len(cap_keys),
            "trading_sessions_in_replay": day_count,
            "estimated_price_load_seconds": round(price_estimate, 3),
            "estimated_cap_lookup_seconds": round(cap_estimate, 3),
            "estimated_sequential_replay_seconds": round(replay_estimate, 3),
            "estimated_total_seconds": round(estimate, 3),
        }
    result = {
        "status": "PASS" if replay["metrics"].get("cash_conservation_pass") is True else "CHECK_REQUIRED",
        "sample_window": "P2-1",
        "sample_trade_count": len(sample_records),
        "sample_unique_ticker_count": len(sample_tickers),
        "sample_wall_seconds": round(wall, 3),
        "sample_process_cpu_seconds": round(cpu, 3),
        "sample_peak_rss_bytes": int(rss_end * rss_scale),
        "sample_peak_rss_delta_bytes": int(max(0, rss_end - rss_start) * rss_scale),
        "price_load_seconds": round(price_load_seconds, 3),
        "pit_component_frame_seconds": round(component_frame_seconds, 3),
        "exact_mcap_partition_lookup_seconds": round(cap_seconds, 3),
        "sequential_portfolio_replay_seconds": round(replay_seconds, 3),
        "sample_exact_mcap_partition_count": cap_audit["partition_count"],
        "sample_exact_entry_exit_price_audit": price_audit,
        "sample_portfolio_event_count": len(replay["events"]),
        "sample_cash_conservation_pass": replay["metrics"].get("cash_conservation_pass"),
        "sample_daily_equity_gap_days": sum(row.get("equity") is None for row in replay["daily_equity"] if row["date"] <= inputs["window"]["effective_end"]),
        "estimated_available_window_work": full_work,
        "estimated_total_seconds_for_4_tax_complete_windows": round(total_estimate, 3),
        "estimated_total_minutes_for_4_tax_complete_windows": round(total_estimate / 60.0, 2),
        "execution_limit_seconds": 7200,
        "estimated_runtime_within_two_hours": total_estimate < 7200,
        "p1_tax_authority_gap": p1_cost_gap(),
        "market_authority": market_authority,
        "loader_ticker_count": len(loader_audit),
        "loader_explicit_unavailable_count": sum(row.get("status") == "EXPLICIT_DATA_UNAVAILABLE" for row in loader_audit.values()),
        "repository_v2_silent_inner_drop_count": sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values()),
        "source_artifact_sha256": inputs["source_hashes"],
        "plan_sha256": sha256(ROOT / PLAN_REL),
        "script_sha256": sha256(ROOT / SCRIPT_REL),
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    json_write(preflight_path, result)
    return result


def combine_gate(statuses: Sequence[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "CHECK_REQUIRED" in statuses:
        return "CHECK_REQUIRED"
    return "PASS"


def finalize_exact_valuation_outputs() -> dict[str, Any]:
    """Fail closed when exact daily or terminal equity marks are unavailable."""
    out_root = ROOT / OUTPUT_ROOT
    window_metrics: dict[str, dict[str, Any]] = {}
    finalization: dict[str, Any] = {}
    for window_id in RUNNABLE_WINDOWS:
        directory = out_root / window_id.lower().replace("-", "_")
        metrics_path = directory / "metrics.json"
        equity_path = directory / "daily_equity.csv"
        if not metrics_path.is_file() or not equity_path.is_file():
            raise RuntimeError(f"CANNOT_FINALIZE_INCOMPLETE_WINDOW:{window_id}")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        curve = pd.read_csv(equity_path, dtype={"date": str})
        curve["equity_numeric"] = pd.to_numeric(curve["equity"], errors="coerce")
        window = metrics
        end = str(window["effective_end"])[:10]
        support = str(window["execution_support"])[:10]
        evaluated = curve.loc[curve["date"].astype(str).le(end)]
        gap_days = int(evaluated["equity_numeric"].isna().sum())
        end_rows = curve.loc[curve["date"].astype(str).eq(end)]
        support_rows = curve.loc[curve["date"].astype(str).eq(support)]
        end_equity = None if len(end_rows) != 1 or pd.isna(end_rows.iloc[0]["equity_numeric"]) else float(end_rows.iloc[0]["equity_numeric"])
        support_equity = None if len(support_rows) != 1 or pd.isna(support_rows.iloc[0]["equity_numeric"]) else float(support_rows.iloc[0]["equity_numeric"])
        portfolio_metrics = metrics["portfolio_metrics"]
        observed_helper_equity = portfolio_metrics.get("final_equity")
        observed_helper_mdd = portfolio_metrics.get("mdd_pct")
        terminal_complete = end_equity is not None and support_equity is not None
        if terminal_complete:
            portfolio_metrics["final_equity_at_effective_close"] = end_equity
            portfolio_metrics["final_equity"] = support_equity
            portfolio_metrics["cumulative_return_pct"] = (support_equity / INITIAL_CAPITAL - 1.0) * 100.0
            elapsed_days = max(1, (pd.Timestamp(end) - pd.Timestamp(metrics["effective_start"])).days)
            portfolio_metrics["CAGR_pct"] = (support_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) * 100.0 - 100.0
        else:
            portfolio_metrics["observed_last_valid_equity_not_terminal"] = observed_helper_equity
            portfolio_metrics["final_equity"] = None
            portfolio_metrics["final_equity_at_effective_close"] = end_equity
            portfolio_metrics["cumulative_return_pct"] = None
            portfolio_metrics["CAGR_pct"] = None
        if gap_days:
            portfolio_metrics["observed_valid_subset_mdd_not_official"] = observed_helper_mdd
            portfolio_metrics["mdd_pct"] = None
            for field in ("peak_date", "trough_date", "recovery_date"):
                if field in portfolio_metrics:
                    portfolio_metrics[field] = None
        metrics["daily_equity_gap_day_count"] = gap_days
        metrics["exact_terminal_equity_available"] = terminal_complete
        gates = metrics["gates"]
        if gap_days or not metrics.get("orchestration_source_sha_verified"):
            gates["A"] = "CHECK_REQUIRED"
        if not terminal_complete:
            gates["C"] = "CHECK_REQUIRED"
        elif portfolio_metrics.get("cumulative_return_pct") is not None and portfolio_metrics.get("CAGR_pct") is not None:
            gates["C"] = "PASS" if portfolio_metrics["cumulative_return_pct"] > 0 and portfolio_metrics["CAGR_pct"] > 0 else "FAIL"
        if gap_days:
            gates["D"] = "CHECK_REQUIRED"
        elif portfolio_metrics.get("mdd_pct") is not None:
            gates["D"] = "PASS" if portfolio_metrics["mdd_pct"] >= -35.0 else "FAIL"
        if gap_days or int(portfolio_metrics.get("unresolved_count", 0) or 0):
            gates["F"] = "CHECK_REQUIRED"
        metrics["gates"] = gates
        json_write(metrics_path, metrics)
        window_metrics[window_id] = metrics
        finalization[window_id] = {
            "effective_end": end,
            "execution_support": support,
            "daily_equity_gap_day_count": gap_days,
            "effective_end_equity_krw": end_equity,
            "execution_support_equity_krw": support_equity,
            "terminal_equity_complete": terminal_complete,
            "official_net_return_and_CAGR_available": terminal_complete,
            "official_MDD_available": gap_days == 0,
            "gate_A": gates["A"],
            "gate_C": gates["C"],
            "gate_D": gates["D"],
            "gate_F": gates["F"],
        }

    all_statuses = {
        gate: [window_metrics[wid]["gates"][gate] for wid in RUNNABLE_WINDOWS] + ["CHECK_REQUIRED"]
        for gate in "ABCDEF"
    }
    global_gates = {gate: combine_gate(statuses) for gate, statuses in all_statuses.items()}
    verdict = "HOLD" if any(status == "CHECK_REQUIRED" for status in global_gates.values()) else (
        "OFFICIAL_STRATEGY_ADOPTED" if all(status == "PASS" for status in global_gates.values()) else "NOT_ADOPTED"
    )
    summary_path = out_root / "five_window_summary.csv"
    summary = pd.read_csv(summary_path)
    for window_id in RUNNABLE_WINDOWS:
        metric = window_metrics[window_id]
        pm = metric["portfolio_metrics"]
        mask = summary["window_id"].astype(str).eq(window_id)
        summary.loc[mask, "net_total_return_pct"] = pm.get("cumulative_return_pct")
        summary.loc[mask, "CAGR_pct"] = pm.get("CAGR_pct")
        summary.loc[mask, "MDD_pct"] = pm.get("mdd_pct")
        summary.loc[mask, "ending_equity_krw"] = pm.get("final_equity")
        gates = metric["gates"]
        summary.loc[mask, "window_gate"] = "/".join(f"{key}:{value}" for key, value in gates.items() if value != "PASS") or "PASS"
    summary.to_csv(summary_path, index=False, encoding="utf-8")

    metrics_path = out_root / "portfolio_metrics.json"
    portfolio_summary = json.loads(metrics_path.read_text(encoding="utf-8"))
    portfolio_summary["windows"] = window_metrics
    json_write(metrics_path, portfolio_summary)
    gates_path = out_root / "official_adoption_gates.json"
    adoption = json.loads(gates_path.read_text(encoding="utf-8"))
    adoption["gates"] = global_gates
    adoption["window_gate_statuses"] = {wid: window_metrics[wid]["gates"] for wid in RUNNABLE_WINDOWS}
    adoption["verdict"] = verdict
    adoption["exact_valuation_finalization"] = finalization
    adoption["reason"] = "Exact daily equity gaps and/or terminal marks leave ending equity or MDD unresolved; P1 also lacks pre-2021 tax authority. No stale price or estimated tax was substituted."
    json_write(gates_path, adoption)

    report_path = out_root / "report.md"
    lines = report_path.read_text(encoding="utf-8").splitlines()
    table_index = next(i for i, line in enumerate(lines) if line.startswith("| Window | Net total return"))
    table_end = table_index + 2
    while table_end < len(lines) and lines[table_end].startswith("|"):
        table_end += 1
    table_rows = [lines[table_index], lines[table_index + 1]]
    def format_value(value: Any, suffix: str = "") -> str:
        return "CHECK_REQUIRED" if value is None or pd.isna(value) else f"{float(value):,.2f}{suffix}"
    for row in summary.to_dict(orient="records"):
        table_rows.append(
            f"| {row['window_id']} | {format_value(row.get('net_total_return_pct'), '%')} | {format_value(row.get('CAGR_pct'), '%')} | {format_value(row.get('MDD_pct'), '%')} | "
            f"{format_value(row.get('ending_equity_krw'))} | {format_value(row.get('cash_shortage_skip_rate_pct'), '%')} | {format_value(row.get('turnover_multiple_initial_capital'), 'x')} | "
            f"{format_value(row.get('maximum_concurrent_positions'))} | {format_value(row.get('unresolved_count'))} | {row['window_gate']} |"
        )
    lines = lines[:table_index] + table_rows + lines[table_end:]
    gate_index = next(i for i, line in enumerate(lines) if line == "## Gate A–F")
    for offset, gate in enumerate("ABCDEF", start=2):
        lines[gate_index + offset] = f"- Gate {gate}: `{global_gates[gate]}`"
    lines.insert(gate_index + 2 + 7, f"Exact-valuation audit에서 일별 equity 공백과 종료 equity 미해결을 확인해, 영향 window의 net return/CAGR/MDD를 수치로 확정하지 않았어.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    finalization_path = out_root / "exact_valuation_finalization.json"
    json_write(finalization_path, {
        "status": "FAIL_CLOSED_UNRESOLVED_EXACT_MARKS",
        "windows": finalization,
        "global_gates": global_gates,
        "verdict": verdict,
        "policy": "No nearest-day, proxy, or forward-filled mark was substituted. Any curve with a daily valuation gap has no official MDD; missing terminal equity has no official return/CAGR.",
    })
    metadata_path = out_root / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["final_verdict"] = verdict
    metadata["final_gates"] = global_gates
    metadata["exact_valuation_finalization"] = finalization
    metadata["finalizer_sha256"] = sha256(ROOT / SCRIPT_REL)
    metadata["generated_files"] = {
        str(path.relative_to(out_root)): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in sorted(out_root.rglob("*"))
        if path.is_file() and path.name != "metadata.json"
    }
    json_write(metadata_path, metadata)
    return {"verdict": verdict, "gates": global_gates, "finalization": finalization}


def run_full() -> dict[str, Any]:
    out_root = ROOT / OUTPUT_ROOT
    preflight_path = out_root / "preflight.json"
    if not preflight_path.is_file():
        raise RuntimeError("PREFLIGHT_REQUIRED_BEFORE_FULL_RUN")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("status") != "PASS" or not preflight.get("estimated_runtime_within_two_hours"):
        raise RuntimeError("PREFLIGHT_NOT_CLEAR_FOR_FULL_RUN")
    for window_id in RUNNABLE_WINDOWS:
        existing = out_root / window_id.lower().replace("-", "_")
        if existing.exists():
            raise RuntimeError(f"WINDOW_OUTPUT_ALREADY_EXISTS_AUTOMATIC_RETRY_FORBIDDEN:{window_id}")

        intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    cap_lookup = ExactMarketCapPriority()
    window_metrics = {}
    input_hashes = {}
    for window_id in RUNNABLE_WINDOWS:
        inputs = load_window_inputs(window_id)
        input_hashes[window_id] = inputs["source_hashes"]
        records = [dict(row) for row in inputs["records"]]
        tickers = sorted({str(row["ticker"]).zfill(6) for row in records})
        daily_frames, loader_audit, _repository = candidate_runner._load_prices(
            ROOT, tickers, inputs["window"]["effective_start"], inputs["window"]["execution_support"],
        )
        frames = build_component_frames(records, daily_frames, intervals, trading_dates)
        cap_audit = cap_lookup.attach(records)
        price_audit = verify_execution_prices(records, frames, inputs["window"])
        if sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values()) != 0:
            raise RuntimeError(f"REPOSITORY_V2_SILENT_INNER_DROP:{window_id}")
        replay = run_replay(
            records, frames, trading_dates, inputs["window"],
            f"PATTERN_B_ET_REALISTIC_PORTFOLIO_{window_id.replace('-', '_')}",
        )
        metrics = write_window_outputs(inputs, replay, frames, loader_audit, cap_audit, price_audit)
        window_metrics[window_id] = metrics
        print(
            f"Completed {window_id}: end_equity={replay['metrics'].get('final_equity')} "
            f"return={replay['metrics'].get('cumulative_return_pct')}% "
            f"MDD={replay['metrics'].get('mdd_pct')}% cash_skips={replay['metrics'].get('cash_shortage_skipped_entries')}",
            flush=True,
        )

    p1_gap = p1_cost_gap()
    rows = []
    for window_id in WINDOW_IDS:
        if window_id == "P1":
            rows.append({
                "window_id": "P1", "net_total_return_pct": None, "CAGR_pct": None,
                "MDD_pct": None, "ending_equity_krw": None, "cash_shortage_skip_rate_pct": None,
                "turnover_multiple_initial_capital": None, "maximum_concurrent_positions": None,
                "unresolved_count": None, "window_gate": "CHECK_REQUIRED_TAX_AUTHORITY",
            })
            continue
        row = window_metrics[window_id]
        metrics = row["portfolio_metrics"]
        rows.append({
            "window_id": window_id,
            "net_total_return_pct": metrics.get("cumulative_return_pct"),
            "CAGR_pct": metrics.get("CAGR_pct"),
            "MDD_pct": metrics.get("mdd_pct"),
            "ending_equity_krw": metrics.get("final_equity"),
            "cash_shortage_skip_rate_pct": row.get("cash_shortage_skip_rate_pct"),
            "turnover_multiple_initial_capital": metrics.get("turnover_multiple"),
            "maximum_concurrent_positions": metrics.get("maximum_concurrent_positions"),
            "unresolved_count": metrics.get("unresolved_count"),
            "window_gate": "PASS" if all(value == "PASS" for value in row["gates"].values()) else "/".join(f"{k}:{v}" for k, v in row["gates"].items() if v != "PASS") or "PASS",
        })
    pd.DataFrame(rows).to_csv(out_root / "five_window_summary.csv", index=False, encoding="utf-8")

    all_gate_statuses = {
        gate: [window_metrics[wid]["gates"][gate] for wid in RUNNABLE_WINDOWS] + ["CHECK_REQUIRED"]
        for gate in "ABCDEF"
    }
    global_gates = {gate: combine_gate(statuses) for gate, statuses in all_gate_statuses.items()}
    if any(value == "CHECK_REQUIRED" for value in global_gates.values()):
        verdict = "HOLD"
    elif all(value == "PASS" for value in global_gates.values()):
        verdict = "OFFICIAL_STRATEGY_ADOPTED"
    else:
        verdict = "NOT_ADOPTED"

    global_contract = {
        "frozen_rule": {
            "entry": "Pattern B DEPRESSED AND current Pattern A Stage PROGRESSED AND previous Pattern A Stage in {EARLY_TREND, TRANSITION}",
            "exit": "Pattern B NORMAL -> next exact KRX session open",
            "no_rule_changes": True,
        },
        "starting_head": preflight.get("starting_head", "ce639f78ba1cc9842d3b066a1c3cce082b619942"),
        "plan_path": str(PLAN_REL),
        "plan_sha256": sha256(ROOT / PLAN_REL),
        "capital": {"initial_krw": INITIAL_CAPITAL, "per_entry_buy_budget_krw": POSITION_BUDGET, "position_cap": None, "partial_fill": False},
        "event_contract": {
            "source": "scripts/run_p2_1_realistic_portfolio_v01.py::_portfolio_replay",
            "date_order": "ascending exact KRX session",
            "within_day": "release previous T+1 settlement; sells; buys",
            "same_open_sale_proceeds_reusable": False,
            "same_open_exit_reentry": False,
            "buy_priority": "exact KRX raw market_cap at signal date descending, ticker ascending, pair ID ascending; allocation order only",
            "hidden_position_cap": None,
        },
        "costs": {
            "commission_rate_each_side": COMMISSION_RATE,
            "slippage_rate_each_side": SLIPPAGE_RATE,
            "tax_schedule_source": "scripts/run_v2_julia_official_validation_v01.py::HISTORICAL_SELL_TAX_SCHEDULE",
            "tax_schedule_first_date": "2021-01-01",
            "tax_schedule": [{"start": s, "end": e, "KOSPI": r, "KOSDAQ": r} for s, e, r in TAX_SCHEDULE],
            "P1_cost_status": p1_gap,
        },
        "daily_equity": "cash + pending settlement + open positions valued at exact Repository V2 close; no carry/proxy/forward-fill",
        "drawdown": "minimum(equity / running peak equity - 1)",
        "turnover": "executed buy plus sell notional before costs divided by initial capital",
        "terminal_open": "exact cutoff close with no synthetic sell/cost/reinvestment; unresolved otherwise",
    }
    json_write(out_root / "execution_contract.json", global_contract)
    json_write(out_root / "official_adoption_gates.json", {
        "gates": global_gates,
        "window_gate_statuses": {wid: window_metrics[wid]["gates"] for wid in RUNNABLE_WINDOWS},
        "P1": {"A": "CHECK_REQUIRED", "B": "CHECK_REQUIRED", "C": "CHECK_REQUIRED", "D": "CHECK_REQUIRED", "E": "CHECK_REQUIRED", "F": "CHECK_REQUIRED", "cost_authority": p1_gap},
        "verdict": verdict,
        "reason": "P1 includes 2014-2020 realized exits without repository-verified tax rates; no values were inferred and cash/equity replay was not fabricated.",
    })
    json_write(out_root / "portfolio_metrics.json", {"windows": window_metrics})

    reports = [
        "# Pattern B E/T-only 현실 포트폴리오 최종 심사 V01",
        "",
        f"최종 판정: `{verdict}`",
        "",
        "## 5-window 결과",
        "",
        "| Window | Net total return | CAGR | MDD | Ending equity | Cash skip | Turnover | Max positions | Unresolved | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        def fmt(value: Any, suffix: str = "") -> str:
            return "CHECK_REQUIRED" if value is None or pd.isna(value) else f"{float(value):,.2f}{suffix}"
        reports.append(
            f"| {row['window_id']} | {fmt(row['net_total_return_pct'], '%')} | {fmt(row['CAGR_pct'], '%')} | {fmt(row['MDD_pct'], '%')} | "
            f"{fmt(row['ending_equity_krw'])} | {fmt(row['cash_shortage_skip_rate_pct'], '%')} | {fmt(row['turnover_multiple_initial_capital'], 'x')} | "
            f"{fmt(row['maximum_concurrent_positions'])} | {fmt(row['unresolved_count'])} | {row['window_gate']} |"
        )
    reports += [
        "",
        "## Gate A–F",
        "",
        *(f"- Gate {gate}: `{status}`" for gate, status in global_gates.items()),
        "",
        "## 비용 authority",
        "",
        f"P1은 기존 trade ledger에서 2014–2020 realized exit {p1_gap['pre_2021_realized_exit_count_in_saved_P1_ledger']}건을 확인했고, 그중 세율 누락은 {p1_gap['pre_2021_realized_exit_missing_tax_count']}건이야. Repository 검증 세율표는 {p1_gap['authoritative_schedule_start']}부터라서 해당 연도 세율을 추정하지 않았고, P1 포트폴리오 replay를 수행하지 않았어. 이 누락은 P1 cash allocation과 equity 경로에 영향을 주므로 최종 판정은 HOLD야.",
        "",
        "## Lifecycle replay 근거",
        "",
        "다섯 창의 저장 stage audit에서 pass 신호와 trade ledger가 1:1로 연결되는지 검사했어. pass 신호 중 baseline position 때문에 억제된 건 0건이었고, 기간 종료 후 진입 시점이어서 미체결된 신호만 포트폴리오 attempt에서 제외했어. 각 cash skip마다 후속 pass 신호 목록을 `cash_skip_lifecycle_audit.csv`에 연결했어.",
        "",
        "저장된 결과 파일 해시는 모두 당시 metadata와 일치해. 실행 당시 study orchestrator 파일은 시작 HEAD에서 untracked였고 기록 SHA는 현재 커밋본과 다르다. candidate runner 및 Pattern B signal generator는 시작 HEAD 이후 바뀌지 않은 것으로 확인했으며, orchestrator 출처 차이는 Gate A에 CHECK_REQUIRED로 남겼어.",
        "",
        "## 추가 replay 여부",
        "",
        "P2-1 첫 포트폴리오 시도는 입력 정규화 단계에서 NaN terminal date 처리 오류로 끝났고 cash/equity replay 및 window 산출물 생성 전이었다. 빈 날짜를 None으로 정규화한 뒤 한 번 수정 실행했어. 이전 실패 시도 결과를 재사용하지 않았어.",
        "",
        "## 판정",
        "",
        "후보 규칙은 변경하지 않았어. P2/P3의 결과는 window별 지표와 audit에 있으며, P1의 역사 세율 authority가 불완전해 여섯 gate의 5-window 종합 통과 여부를 확정할 수 없어 `HOLD`야.",
        "",
        "## 산출물",
        "",
        "- `execution_contract.json`, `preflight.json`, `five_window_summary.csv`, `portfolio_metrics.json`, `official_adoption_gates.json`",
        "- window별 portfolio event, daily equity, skipped entry, cost, cash, valuation, attempt, cash-skip lifecycle audit",
        "- 기존 trade ledger 재복사 없음; 입력 경로와 SHA-256은 `metadata.json`에 저장",
    ]
    (out_root / "report.md").write_text("\n".join(reports) + "\n", encoding="utf-8")
    run_metadata = {
        "run_id": "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_REALISTIC_PORTFOLIO_V01",
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "starting_head": preflight.get("starting_head", "ce639f78ba1cc9842d3b066a1c3cce082b619942"),
        "plan_sha256": sha256(ROOT / PLAN_REL),
        "script_sha256": sha256(ROOT / SCRIPT_REL),
        "preflight_script_sha256": preflight.get("script_sha256"),
        "full_run_script_sha256": sha256(ROOT / SCRIPT_REL),
        "failed_attempts": [{
            "window": "P2-1",
            "status": "ABORTED_BEFORE_PORTFOLIO_REPLAY",
            "reason": "CSV blank terminal_valuation_date was read as NaN and reached a nullable-date conversion in the certified helper",
            "scope": "price load completed; no portfolio replay or window result artifacts were written",
            "corrected_run_count": 1,
        }],
        "source_code_sha256": {
            str(SCRIPT_REL): sha256(ROOT / SCRIPT_REL),
            "scripts/run_p2_1_realistic_portfolio_v01.py": sha256(ROOT / "scripts/run_p2_1_realistic_portfolio_v01.py"),
            "scripts/run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01.py": sha256(ROOT / "scripts/run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01.py"),
            "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py": sha256(ROOT / "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py"),
            "scripts/run_pattern_b_pure_simple_backtest_v01.py": sha256(ROOT / "scripts/run_pattern_b_pure_simple_backtest_v01.py"),
            "scripts/run_v2_julia_official_validation_v01.py": sha256(ROOT / "scripts/run_v2_julia_official_validation_v01.py"),
        },
        "source_code_reproducibility_by_window": {
            wid: {
                "saved_orchestrator_code_check": window_metrics[wid].get("orchestration_code_checks"),
                "bootstrap_signal_source_check": window_metrics[wid].get("bootstrap_signal_source_checks"),
                "source_verified": window_metrics[wid].get("orchestration_source_sha_verified"),
            }
            for wid in RUNNABLE_WINDOWS
        },
        "source_artifact_sha256": input_hashes,
        "tax_authority": p1_gap,
        "market_authority": market_authority,
        "workers": WORKERS,
        "p1_replay": "NOT_RUN_INCOMPLETE_HISTORICAL_TAX_AUTHORITY",
        "runnable_windows": list(RUNNABLE_WINDOWS),
        "verdict": verdict,
        "generated_files": {},
    }
    for path in sorted(out_root.rglob("*")):
        if path.is_file() and path.name != "metadata.json":
            run_metadata["generated_files"][str(path.relative_to(out_root))] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    json_write(out_root / "metadata.json", run_metadata)
    return {"verdict": verdict, "gates": global_gates, "windows": window_metrics, "P1": p1_gap}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if sum((args.preflight, args.run, args.finalize)) != 1:
        parser.error("choose exactly one of --preflight, --run, or --finalize")
    if args.preflight:
        result = run_preflight()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default), flush=True)
    elif args.run:
        result = run_full()
        print(json.dumps({"verdict": result["verdict"], "gates": result["gates"]}, ensure_ascii=False, indent=2), flush=True)
    else:
        result = finalize_exact_valuation_outputs()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default), flush=True)


if __name__ == "__main__":
    main()
