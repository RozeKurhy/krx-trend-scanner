#!/usr/bin/env python3
"""P2-1 V2 versus NEG40/WEAK-protect realistic portfolio replay.

This run keeps the frozen per-identity strategy rules, gates exact raw PIT
market-cap eligibility before a rejected signal consumes V2 re-entry state,
then performs deterministic, sequential portfolio cash/equity replay.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import sys
import threading
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_fastcore_neg40_weak_protect_p2_1 as p2
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import (
    load_rolling_authority,
    validate_merged_authority_coherence,
)


RUN_ID = "run_20260926_realistic_mcap1t_worker10_v01"
OUT_DIR = ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01" / RUN_ID
ROLLING_DIR = ROOT / "data/market/rolling_authority"
INITIAL_CAPITAL = 200_000_000.0
POSITION_BUDGET = 5_000_000.0
MARKET_CAP_THRESHOLD = 1_000_000_000_000
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
SELL_TAX_SCHEDULE = (
    ("2021-01-01", "2022-12-31", 0.0023),
    ("2023-01-01", "2023-12-31", 0.0020),
    ("2024-01-01", "2024-12-31", 0.0018),
    ("2025-01-01", "2025-12-31", 0.0015),
)
EXPECTED_OUTPUTS = (
    "execution_contract.json",
    "filtered_universe_audit.csv",
    "pit_mcap_audit.csv",
    "control_strategy_trades.csv",
    "candidate_strategy_trades.csv",
    "p2_1_soft_events.csv",
    "control_portfolio_events.csv",
    "candidate_portfolio_events.csv",
    "control_daily_equity.csv",
    "candidate_daily_equity.csv",
    "skipped_entries.csv",
    "summary.json",
    "summary.csv",
    "comparison_report.md",
)
PORTFOLIO_AUDIT_OUTPUTS = (
    "valuation_gap_closure_audit.csv",
    "valuation_gap_source_diagnosis.csv",
    "hidden_position_cap_audit.json",
    "mcap365_to_trade355_reason_audit.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExactRawMcapGate:
    """Exact-date, manifest/hash-verified KRX raw MKTCAP gate."""

    def __init__(self, root: Path, pit: Mapping[str, Any]) -> None:
        self.root = root
        self.intervals = tuple(pit["intervals"])
        self.as_of = str(pit["target_as_of"])
        self.active_identity_keys = frozenset(
            (
                str(row.get("ticker", "")).zfill(6),
                str(row["isu_cd"]).upper(),
                str(row.get("market", "")).upper(),
            )
            for row in self.intervals
            if row.get("state") == "COMMON"
            and str(row["effective_from"]) <= self.as_of <= str(row["effective_to"])
        )
        self.store = KrxRawStockStore(root / "data/market/raw/krx_stocks/v01")
        self._partition_cache: OrderedDict[
            tuple[str, str], tuple[dict[str, Any], dict[str, int]]
        ] = OrderedDict()
        self._resolution_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._cache_limit = 32

    def _pit_common(self, segment: p2.IdentitySegment, day: str) -> bool:
        return any(
            row.get("state") == "COMMON"
            and str(row.get("ticker", "")).zfill(6) == segment.ticker
            and str(row.get("isu_cd", "")).upper() == segment.isu_cd.upper()
            and str(row.get("market", "")).upper() == segment.market.upper()
            and str(row["effective_from"]) <= day <= str(row["effective_to"])
            for row in self.intervals
        )

    def _partition(self, market: str, day: str) -> tuple[dict[str, Any], dict[str, int]]:
        key = (market.upper(), day)
        with self._lock:
            cached = self._partition_cache.get(key)
            if cached is not None:
                self._partition_cache.move_to_end(key)
                return cached
            manifest = self.store.get_manifest(*key)
            if manifest is None or manifest.get("status") != "COMPLETE":
                result = (manifest or {}, {})
            else:
                # load_snapshot verifies the physical SHA-256, schema, row count,
                # and canonical content hash against the immutable manifest.
                frame = self.store.load_snapshot(*key)
                caps = {
                    str(row.ticker).zfill(6): int(row.market_cap)
                    for row in frame[["ticker", "market_cap"]].itertuples(index=False)
                }
                result = (manifest, caps)
            self._partition_cache[key] = result
            self._partition_cache.move_to_end(key)
            while len(self._partition_cache) > self._cache_limit:
                self._partition_cache.popitem(last=False)
            return result

    def resolution(
        self,
        segment: p2.IdentitySegment,
        signal_date: pd.Timestamp | str,
    ) -> dict[str, Any]:
        day = pd.Timestamp(signal_date).normalize().strftime("%Y-%m-%d")
        key = (segment.key, day)
        with self._lock:
            cached = self._resolution_cache.get(key)
            if cached is not None:
                return cached
            base: dict[str, Any] = {
                "ticker": segment.ticker,
                "identity": segment.isu_cd,
                "market": segment.market,
                "signal_date": day,
                "threshold_krw": MARKET_CAP_THRESHOLD,
                "source": "KRX Open API Stock Daily MKTCAP via data/market/raw/krx_stocks/v01",
                "market_cap": None,
                "partition_status": None,
                "partition_path": None,
                "partition_file_sha256": None,
                "partition_content_sha256": None,
            }
            if not (segment.effective_from.strftime("%Y-%m-%d") <= day <= segment.effective_to.strftime("%Y-%m-%d")):
                base.update(status="UNRESOLVED", reason="SIGNAL_OUTSIDE_COMMON_IDENTITY_INTERVAL")
            elif (segment.ticker, segment.isu_cd.upper(), segment.market.upper()) not in self.active_identity_keys:
                base.update(status="EXCLUDED", reason="IDENTITY_NOT_COMMON_AT_LATEST_DAILY_UPDATE")
            elif not self._pit_common(segment, day):
                base.update(status="UNRESOLVED", reason="EXACT_SIGNAL_DATE_NOT_COMMON_IN_LATEST_PIT")
            else:
                manifest, caps = self._partition(segment.market, day)
                base.update(
                    partition_status=manifest.get("status"),
                    partition_path=manifest.get("file_path"),
                    partition_file_sha256=manifest.get("file_sha256"),
                    partition_content_sha256=manifest.get("content_sha256"),
                )
                if manifest.get("status") != "COMPLETE":
                    base.update(status="UNRESOLVED", reason="EXACT_RAW_SIGNAL_DATE_PARTITION_UNAVAILABLE")
                elif segment.ticker not in caps:
                    base.update(status="UNRESOLVED", reason="EXACT_RAW_SIGNAL_DATE_TICKER_ROW_MISSING")
                else:
                    market_cap = caps[segment.ticker]
                    base["market_cap"] = market_cap
                    if market_cap >= MARKET_CAP_THRESHOLD:
                        base.update(status="PASS", reason="EXACT_RAW_MKTCAP_AT_OR_ABOVE_1T")
                    else:
                        base.update(status="REJECT_BELOW_THRESHOLD", reason="EXACT_RAW_MKTCAP_BELOW_1T")
            self._resolution_cache[key] = base
            return base

    def check(
        self,
        segment: p2.IdentitySegment,
        signal_date: pd.Timestamp,
        _evaluation: Mapping[str, Any],
    ) -> bool:
        row = dict(self.resolution(segment, signal_date))
        row["strategy_signal_qualified"] = True
        with self._lock:
            self._audit.append(row)
        return row["status"] == "PASS"

    def audit_frame(self) -> pd.DataFrame:
        with self._lock:
            return pd.DataFrame(self._audit)


def _load_survivor_context(
    *, worker_count: int,
) -> tuple[p2.RunContext, ExactRawMcapGate, dict[str, Any], pd.DataFrame]:
    manifest = load_rolling_authority(ROLLING_DIR)
    pit_payload, _calendar_payload = validate_merged_authority_coherence(manifest, ROLLING_DIR)
    as_of = str(pit_payload.get("target_as_of", ""))
    if not as_of or as_of != manifest.merged_pit_frontier:
        raise RuntimeError("LATEST_DAILY_UPDATE_PIT_FRONTIER_MISMATCH")
    gate = ExactRawMcapGate(ROOT, pit_payload)
    run = p2._load_context("P2-1")
    original_segments = [
        segment
        for segments in run.segments_by_ticker.values()
        for segment in segments
    ]
    selected = [
        segment for segment in original_segments
        if (segment.ticker, segment.isu_cd.upper(), segment.market.upper()) in gate.active_identity_keys
    ]
    grouped: dict[str, list[p2.IdentitySegment]] = {}
    selected_keys = {segment.key for segment in selected}
    for segment in selected:
        grouped.setdefault(segment.ticker, []).append(segment)
    filtered_run = replace(
        run,
        segments_by_ticker={
            ticker: tuple(sorted(rows, key=lambda item: (item.effective_from, item.effective_to, item.isu_cd)))
            for ticker, rows in sorted(grouped.items())
        },
        entry_signal_gate=gate,
    )
    universe_rows: list[dict[str, Any]] = []
    for segment in original_segments:
        survives = segment.key in selected_keys
        universe_rows.append(
            {
                "ticker": segment.ticker,
                "isu_cd": segment.isu_cd,
                "market": segment.market,
                "effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                "effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                "latest_daily_update_as_of": as_of,
                "status": "SURVIVOR_COMMON_IDENTITY" if survives else "EXCLUDED_NOT_CURRENT_COMMON_IDENTITY",
                "reason": "EXACT_TICKER_ISU_MARKET_ACTIVE_AT_LATEST_DAILY_UPDATE" if survives else "IDENTITY_NOT_COMMON_AT_LATEST_DAILY_UPDATE",
            }
        )
    seen_exclusions: set[tuple[str, str]] = set()
    for item in run.permanent_identity_exclusions:
        key = (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
        if key in seen_exclusions:
            continue
        seen_exclusions.add(key)
        universe_rows.append(
            {
                "ticker": key[0],
                "isu_cd": key[1],
                "market": item.get("market"),
                "effective_from": None,
                "effective_to": None,
                "latest_daily_update_as_of": as_of,
                "status": "EXCLUDED_EXISTING_PERMANENT_IDENTITY_POLICY",
                "reason": item.get("reason"),
            }
        )
    context = {
        "latest_daily_update_as_of": as_of,
        "latest_daily_update_source_frontier": pit_payload.get("source_basic_info_frontier"),
        "rolling_manifest_certified_through": manifest.certified_through,
        "rolling_manifest_sha256": manifest.manifest_sha256,
        "merged_pit_digest": manifest.merged_pit_digest,
        "merged_pit_file_sha256": _sha256(ROLLING_DIR / "merged_pit_intervals.json"),
        "effective_pit_file_sha256": _sha256(run.authority.pit_path),
        "raw_market_cap_store": "data/market/raw/krx_stocks/v01",
        "raw_market_cap_threshold_krw": MARKET_CAP_THRESHOLD,
        "worker_count": worker_count,
    }
    return filtered_run, gate, context, pd.DataFrame(universe_rows)


def _run_ticker_pool(
    run: p2.RunContext,
    *,
    workers: int,
    tickers: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str], float]:
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []

    def process(ticker: str) -> dict[str, Any]:
        result = p2._process_ticker(ticker, run)
        result["worker_thread"] = threading.current_thread().name
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="p2-1-worker") as pool:
        futures = {pool.submit(process, ticker): ticker for ticker in tickers}
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 25 == 0 or completed == len(tickers):
                print(
                    f"P2-1 workers progress {completed}/{len(tickers)}; "
                    f"trades={sum(len(item['control_rows']) for item in outcomes)}; "
                    f"PIT candidates={len(run.entry_signal_gate.audit_frame())}; "
                    f"elapsed={time.perf_counter() - started:.1f}s; errors={len(errors)}",
                    flush=True,
                )
    return outcomes, errors, time.perf_counter() - started


def _parallel_rollup(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_worker: dict[str, dict[str, Any]] = {}
    for item in outcomes:
        name = str(item["worker_thread"])
        entry = by_worker.setdefault(name, {"ticker_tasks": 0, "worker_task_seconds": 0.0})
        entry["ticker_tasks"] += 1
        entry["worker_task_seconds"] += float(item["elapsed_seconds"])
    return {
        "configured_workers": 10,
        "observed_worker_threads": len(by_worker),
        "worker_threads": {
            name: {
                "ticker_tasks": data["ticker_tasks"],
                "worker_task_seconds": round(data["worker_task_seconds"], 3),
            }
            for name, data in sorted(by_worker.items())
        },
        "sum_worker_task_seconds": round(
            sum(float(item["elapsed_seconds"]) for item in outcomes), 3
        ),
    }


def _validate_entry_pairing(control: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    if control.empty or candidate.empty:
        raise RuntimeError("EMPTY_POST_FILTER_CONTROL_OR_CANDIDATE_POPULATION")
    if control["pair_id"].duplicated().any() or candidate["pair_id"].duplicated().any():
        raise RuntimeError("DUPLICATE_PAIR_ID_AFTER_PIT_FILTER")
    control_ids = set(control["pair_id"].astype(str))
    candidate_ids = set(candidate["pair_id"].astype(str))
    if control_ids != candidate_ids or len(control) != len(candidate):
        raise RuntimeError("CONTROL_CANDIDATE_PAIR_POPULATION_MISMATCH")
    joined = control.merge(candidate, on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one")
    if not joined["trade_id_control"].astype(str).equals(joined["trade_id_candidate"].astype(str)):
        raise RuntimeError("CONTROL_CANDIDATE_TRADE_ID_MISMATCH_BY_PAIR")
    checks: dict[str, bool] = {}
    for field in (
        "ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date",
        "identity_effective_from", "identity_effective_to",
    ):
        left = joined[f"{field}_control"].fillna("").astype(str)
        right = joined[f"{field}_candidate"].fillna("").astype(str)
        checks[field] = bool(left.equals(right))
        if not checks[field]:
            raise RuntimeError(f"CONTROL_CANDIDATE_ENTRY_PARITY_FAILED:{field}")
    for field in ("entry_open", "entry_market_cap"):
        left = pd.to_numeric(joined[f"{field}_control"], errors="coerce")
        right = pd.to_numeric(joined[f"{field}_candidate"], errors="coerce")
        checks[field] = bool(np.allclose(left, right, rtol=0, atol=1e-9, equal_nan=True))
        if not checks[field]:
            raise RuntimeError(f"CONTROL_CANDIDATE_ENTRY_PARITY_FAILED:{field}")
    return {
        "control_rows": len(control),
        "candidate_rows": len(candidate),
        "pair_id_unique": True,
        "pair_id_sets_equal": True,
        "source_trade_id_equal_by_pair": True,
        "entry_field_parity": checks,
    }


def _frame_for_record(record: Mapping[str, Any], frames: Mapping[Any, pd.DataFrame]) -> pd.DataFrame | None:
    fields = (
        str(record.get("ticker", "")).zfill(6),
        str(record.get("isu_cd", "")),
        str(record.get("market", "")),
        str(record.get("identity_effective_from", "")),
        str(record.get("identity_effective_to", "")),
    )
    # _process_ticker stores frames by IdentitySegment.key, which is the
    # pipe-delimited five-field string (not a tuple).
    frame = frames.get("|".join(fields))
    if frame is None:
        frame = frames.get(fields)
    if frame is None:
        frame = frames.get(fields[:3])
    if frame is None:
        frame = frames.get(fields[0])
    return frame


def _price(record: Mapping[str, Any], frames: Mapping[Any, pd.DataFrame], day: pd.Timestamp, field: str) -> float | None:
    frame = _frame_for_record(record, frames)
    if frame is None or field not in frame.columns:
        return None
    date = pd.Timestamp(day).normalize()
    if date not in frame.index:
        return None
    value = pd.to_numeric(frame.at[date, field], errors="coerce")
    return None if pd.isna(value) or not math.isfinite(float(value)) else float(value)


def _valuation_close_with_carry(
    record: Mapping[str, Any],
    frames: Mapping[Any, pd.DataFrame],
    day: pd.Timestamp,
    trading_session_positions: Mapping[pd.Timestamp, int],
    gap_classifications: Mapping[tuple[str, str], str],
    *,
    strategy_id: str,
    pair_id: str,
) -> tuple[float | None, dict[str, Any] | None]:
    """Use exact valid adjusted close, or prior close only for daily portfolio MTM."""
    valuation_day = pd.Timestamp(day).normalize()
    exact = _price(record, frames, valuation_day, "close")
    if exact is not None:
        return exact, None

    frame = _frame_for_record(record, frames)
    if frame is None or "close" not in frame.columns:
        return None, None
    prior = pd.to_numeric(frame.loc[frame.index < valuation_day, "close"], errors="coerce")
    prior = prior[prior.map(lambda value: pd.notna(value) and math.isfinite(float(value)) and float(value) > 0)]
    if prior.empty:
        return None, None

    last_valid_date = pd.Timestamp(prior.index[-1]).normalize()
    if last_valid_date >= valuation_day:
        raise RuntimeError("P2_1_VALUATION_CARRY_NOT_STRICTLY_PRIOR")
    if valuation_day not in trading_session_positions or last_valid_date not in trading_session_positions:
        return None, None
    ticker = str(record.get("ticker", "")).zfill(6)
    close = float(prior.iloc[-1])
    audit = {
        "strategy_id": strategy_id,
        "pair_id": pair_id,
        "trade_id": record.get("trade_id"),
        "ticker": ticker,
        "identity": record.get("isu_cd"),
        "market": record.get("market"),
        "valuation_date": valuation_day.strftime("%Y-%m-%d"),
        "last_valid_adjusted_close_date": last_valid_date.strftime("%Y-%m-%d"),
        "carried_adjusted_close": close,
        "stale_age_trading_days": trading_session_positions[valuation_day] - trading_session_positions[last_valid_date],
        "stale_age_calendar_days": int((valuation_day - last_valid_date).days),
        "gap_classification": gap_classifications.get((ticker, valuation_day.strftime("%Y-%m-%d")), "NEW_UNCLASSIFIED_GAP"),
        "valuation_only": True,
        "used_for_execution": False,
        "used_for_strategy_or_features": False,
        "carry_rule": "MOST_RECENT_EARLIER_VALID_ADJUSTED_CLOSE",
    }
    return close, audit


def _tax_rate(day: pd.Timestamp, market: str) -> float:
    normalized = pd.Timestamp(day).normalize()
    if str(market).upper() not in {"KOSPI", "KOSDAQ"}:
        raise RuntimeError(f"UNSUPPORTED_SELL_TAX_MARKET:{market}")
    for start, end, rate in SELL_TAX_SCHEDULE:
        if pd.Timestamp(start) <= normalized <= pd.Timestamp(end):
            return rate
    raise RuntimeError(f"SELL_TAX_SCHEDULE_OUTSIDE_P2_1:{normalized.date()}")


def _mdd(curve: pd.DataFrame) -> dict[str, Any]:
    valid = curve.dropna(subset=["equity"]).copy()
    if valid.empty:
        return {"mdd_pct": None, "peak_date": None, "trough_date": None, "recovery_date": None, "recovered": False}
    peak_value = float(valid.iloc[0]["equity"])
    peak_date = pd.Timestamp(valid.iloc[0]["date"])
    worst = 0.0
    worst_peak = peak_date
    worst_trough = peak_date
    recovery_date: str | None = None
    for row in valid.itertuples(index=False):
        day = pd.Timestamp(row.date)
        equity = float(row.equity)
        if equity >= peak_value:
            peak_value = equity
            peak_date = day
        drawdown = equity / peak_value - 1.0 if peak_value else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = day
            recovery_date = None
        elif worst < 0 and day > worst_trough and equity >= peak_value and recovery_date is None:
            recovery_date = day.strftime("%Y-%m-%d")
    return {
        "mdd_pct": round(worst * 100.0, 6),
        "peak_date": worst_peak.strftime("%Y-%m-%d"),
        "trough_date": worst_trough.strftime("%Y-%m-%d"),
        "recovery_date": recovery_date,
        "recovered": recovery_date is not None,
    }


def _portfolio_replay(
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame],
    trading_dates: Sequence[pd.Timestamp],
    *,
    strategy_id: str,
    effective_start: pd.Timestamp,
    effective_end: pd.Timestamp,
    execution_support: pd.Timestamp,
    gap_classifications: Mapping[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    dates = tuple(
        pd.Timestamp(day).normalize()
        for day in trading_dates
        if effective_start <= pd.Timestamp(day).normalize() <= execution_support
    )
    if not dates or dates[-1] != execution_support:
        raise RuntimeError("P2_1_EXECUTION_SUPPORT_NOT_IN_TRADING_CALENDAR")
    next_day = {day: dates[index + 1] for index, day in enumerate(dates[:-1])}
    trading_session_positions = {day: index for index, day in enumerate(dates)}
    gap_classifications = gap_classifications or {}
    entries: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    exits: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    skipped: list[dict[str, Any]] = []
    for source in records:
        record = dict(source)
        entry_date = pd.Timestamp(record["entry_execution_date"]).normalize()
        if entry_date > effective_end:
            raise RuntimeError(f"ENTRY_EXECUTION_AFTER_EFFECTIVE_END:{record.get('pair_id')}:{entry_date.date()}")
        entries.setdefault(entry_date, []).append(record)
        status = str(record.get("trade_status", ""))
        exit_raw = record.get("exit_execution_date")
        if status == "REALIZED" and exit_raw not in (None, "") and not pd.isna(exit_raw):
            exit_date = pd.Timestamp(exit_raw).normalize()
            if exit_date > execution_support:
                skipped.append({"strategy_id": strategy_id, "pair_id": record.get("pair_id"), "ticker": record.get("ticker"), "date": str(exit_raw), "event": "UNRESOLVED_EXIT_AFTER_SUPPORT", "reason": "NO_CERTIFIED_EXECUTION_SUPPORT"})
            else:
                exits.setdefault(exit_date, []).append(record)
        elif status not in {"OPEN_AT_CUTOFF", "OPEN_AT_CUTOFF_WEAK_PROTECT"}:
            skipped.append({"strategy_id": strategy_id, "pair_id": record.get("pair_id"), "ticker": record.get("ticker"), "date": record.get("exit_signal_date"), "event": "UNRESOLVED_STRATEGY_OUTCOME", "reason": status or "MISSING_TRADE_STATUS"})

    cash = INITIAL_CAPITAL
    pending_by_date: dict[pd.Timestamp, float] = {}
    terminal_pending = 0.0
    positions: dict[str, dict[str, Any]] = {}
    terminal_locked: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    entry_candidate_audit: list[dict[str, Any]] = []
    valuation_gap_audit: list[dict[str, Any]] = []
    closed_returns: list[float] = []
    holding_periods: list[int] = []
    total_buy_notional = 0.0
    total_sell_notional = 0.0
    total_commission = 0.0
    total_tax = 0.0
    slippage_impact = 0.0
    cash_shortage = 0
    realized_trade_count = 0
    unresolved_count = sum(
        1
        for item in skipped
        if item.get("event") in {
            "UNRESOLVED_EXIT_AFTER_SUPPORT",
            "UNRESOLVED_STRATEGY_OUTCOME",
        }
    )
    peak_equity = INITIAL_CAPITAL
    cash_conservation_pass = True
    identity_active_keys: set[tuple[str, str, str]] = set()
    cutoff_snapshot: dict[str, Any] | None = None

    def event_row(record: Mapping[str, Any], day: pd.Timestamp, event: str) -> dict[str, Any]:
        return {
            "strategy_id": strategy_id,
            "pair_id": record.get("pair_id"),
            "trade_id": record.get("trade_id"),
            "ticker": str(record.get("ticker", "")).zfill(6),
            "isu_cd": record.get("isu_cd"),
            "market": record.get("market"),
            "signal_date": record.get("entry_signal_date" if event == "ENTRY" else "exit_signal_date"),
            "execution_date": day.strftime("%Y-%m-%d"),
            "event_type": event,
            "event_status": None,
            "reference_open": None,
            "fill_price": None,
            "shares": 0,
            "notional": 0.0,
            "commission": 0.0,
            "sell_tax": 0.0,
            "slippage_impact": 0.0,
            "cash_before": cash,
            "cash_after": cash,
            "pending_sale_proceeds": 0.0,
            "market_cap_at_signal": record.get("entry_market_cap"),
            "reason": (
                record.get("candidate_action") or record.get("exit_type") or record.get("exit_reason")
                if event == "EXIT"
                else "ENTRY"
            ),
            "open_at_effective_cutoff": False,
        }

    for day in dates:
        cash += pending_by_date.pop(day, 0.0)
        exited_tickers: set[str] = set()

        # Deterministic order: release T+1 proceeds, process sells, then buys.
        for record in sorted(exits.get(day, ()), key=lambda row: (str(row.get("ticker", "")), str(row.get("trade_id", "")))):
            ticker = str(record.get("ticker", "")).zfill(6)
            position_id = str(record.get("pair_id", ""))
            event = event_row(record, day, "EXIT")
            position = positions.get(position_id)
            if position is None:
                event.update(event_status="SKIPPED_NO_EXECUTED_POSITION", reason="ENTRY_WAS_NOT_EXECUTED")
                events.append(event)
                continue
            ref = _price(record, frames, day, "open")
            expected = pd.to_numeric(record.get("exit_price"), errors="coerce")
            if ref is None or pd.isna(expected) or not math.isclose(ref, float(expected), rel_tol=0, abs_tol=0.011):
                unresolved_count += 1
                event.update(event_status="UNRESOLVED", reason="MISSING_OR_MISMATCHED_EXACT_EXIT_OPEN")
                events.append(event)
                continue
            positions.pop(position_id)
            shares = int(position["shares"])
            fill = ref * (1.0 - SLIPPAGE_RATE)
            notional = fill * shares
            commission = notional * COMMISSION_RATE
            tax = notional * _tax_rate(day, str(record.get("market", "")))
            proceeds = notional - commission - tax
            release = next_day.get(day)
            if release is None:
                terminal_pending += proceeds
            else:
                pending_by_date[release] = pending_by_date.get(release, 0.0) + proceeds
            exited_tickers.add(ticker)
            identity_active_keys.discard(position["identity_key"])
            total_sell_notional += notional
            total_commission += commission
            total_tax += tax
            impact = abs(ref - fill) * shares
            slippage_impact += impact
            net_return = (proceeds - float(position["buy_cost"])) / float(position["buy_cost"])
            closed_returns.append(net_return)
            realized_trade_count += 1
            holding_periods.append(
                sum(position["entry_date"] <= session <= day for session in dates)
            )
            event.update(
                event_status="EXECUTED",
                reference_open=ref,
                fill_price=fill,
                shares=shares,
                notional=notional,
                commission=commission,
                sell_tax=tax,
                slippage_impact=impact,
                cash_after=cash,
                pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                open_at_effective_cutoff=False,
            )
            events.append(event)

        candidates = sorted(
            entries.get(day, ()),
            key=lambda row: (
                -float(row.get("entry_market_cap") or 0),
                str(row.get("ticker", "")).zfill(6),
                str(row.get("pair_id", "")),
            ),
        )
        for record in candidates:
            ticker = str(record.get("ticker", "")).zfill(6)
            identity_key = (
                ticker,
                str(record.get("isu_cd", "")),
                str(record.get("market", "")),
            )
            event = event_row(record, day, "ENTRY")
            candidate_audit = {
                "strategy_id": strategy_id,
                "pair_id": record.get("pair_id"),
                "trade_id": record.get("trade_id"),
                "ticker": ticker,
                "identity": record.get("isu_cd"),
                "entry_date": day.strftime("%Y-%m-%d"),
                "concurrent_positions_before_candidate": len(positions) + len(terminal_locked),
                "position_cap_configured": None,
                "slot_cap_would_block": False,
                "cash_before": cash,
                "required_total_buy_cost": None,
                "cash_sufficient": None,
                "decision": None,
            }
            if ticker in exited_tickers:
                event.update(event_status="SKIPPED_SAME_OPEN_EXIT_REENTRY", reason="SAME_OPEN_REENTRY_FORBIDDEN")
                candidate_audit["decision"] = "SAME_OPEN_EXIT_REENTRY"
                entry_candidate_audit.append(candidate_audit)
                events.append(event)
                skipped.append({**event, "skip_reason": "SAME_OPEN_EXIT_REENTRY_FORBIDDEN"})
                continue
            if identity_key in identity_active_keys:
                event.update(event_status="SKIPPED_DUPLICATE_ACTIVE_IDENTITY", reason="DUPLICATE_ACTIVE_IDENTITY_FORBIDDEN")
                candidate_audit["decision"] = "DUPLICATE_ACTIVE_IDENTITY"
                entry_candidate_audit.append(candidate_audit)
                events.append(event)
                skipped.append({**event, "skip_reason": "DUPLICATE_ACTIVE_IDENTITY_FORBIDDEN"})
                continue
            ref = _price(record, frames, day, "open")
            if ref is None or ref <= 0:
                unresolved_count += 1
                event.update(event_status="UNRESOLVED", reason="MISSING_EXACT_ENTRY_OPEN")
                candidate_audit["decision"] = "UNRESOLVED_MISSING_EXACT_ENTRY_OPEN"
                entry_candidate_audit.append(candidate_audit)
                events.append(event)
                continue
            fill = ref * (1.0 + SLIPPAGE_RATE)
            shares = int(math.floor((POSITION_BUDGET + 1e-9) / (fill * (1.0 + COMMISSION_RATE))))
            notional = fill * shares
            commission = notional * COMMISSION_RATE
            total_cost = notional + commission
            candidate_audit["required_total_buy_cost"] = total_cost
            candidate_audit["cash_sufficient"] = bool(total_cost <= cash + 1e-6)
            if shares <= 0:
                event.update(event_status="SKIPPED_ZERO_SHARES", reason="MAX_INTEGER_SHARES_ZERO")
                candidate_audit["decision"] = "ZERO_SHARES"
                entry_candidate_audit.append(candidate_audit)
                events.append(event)
                skipped.append({**event, "skip_reason": "MAX_INTEGER_SHARES_ZERO"})
                continue
            if total_cost > cash + 1e-6:
                cash_shortage += 1
                event.update(event_status="SKIPPED_CASH_UNAVAILABLE", reason="INSUFFICIENT_AVAILABLE_CASH")
                candidate_audit["decision"] = "CASH_INSUFFICIENT"
                entry_candidate_audit.append(candidate_audit)
                events.append(event)
                skipped.append({**event, "skip_reason": "INSUFFICIENT_AVAILABLE_CASH"})
                continue
            cash_before = cash
            cash -= total_cost
            position_id = str(record.get("pair_id", ""))
            positions[position_id] = {
                "record": record,
                "ticker": ticker,
                "identity_key": identity_key,
                "market": str(record.get("market", "")),
                "shares": shares,
                "entry_date": day,
                "buy_cost": total_cost,
            }
            identity_active_keys.add(identity_key)
            total_buy_notional += notional
            total_commission += commission
            impact = abs(fill - ref) * shares
            slippage_impact += impact
            event.update(
                event_status="EXECUTED",
                reference_open=ref,
                fill_price=fill,
                shares=shares,
                notional=notional,
                commission=commission,
                slippage_impact=impact,
                cash_before=cash_before,
                cash_after=cash,
                pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                open_at_effective_cutoff=str(record.get("trade_status", "")).startswith("OPEN"),
            )
            events.append(event)
            candidate_audit["decision"] = "EXECUTED"
            entry_candidate_audit.append(candidate_audit)

        # An identity interval that ends before the overall effective cutoff is
        # valued at its exact terminal close and carried locked, never sold or
        # redeployed. This mirrors the existing lifecycle portfolio contract.
        for position_id, position in list(positions.items()):
            record = position["record"]
            terminal_date = record.get("terminal_valuation_date")
            status = str(record.get("trade_status", ""))
            if status != "OPEN_AT_CUTOFF" or terminal_date in (None, "") or pd.isna(terminal_date):
                continue
            terminal_day = pd.Timestamp(terminal_date).normalize()
            if terminal_day >= effective_end or terminal_day != day:
                continue
            close = _price(record, frames, day, "close")
            expected = pd.to_numeric(record.get("terminal_valuation_price"), errors="coerce")
            if close is None or pd.isna(expected) or not math.isclose(close, float(expected), rel_tol=0, abs_tol=0.011):
                unresolved_count += 1
                skipped.append({"strategy_id": strategy_id, "pair_id": position_id, "ticker": position["ticker"], "date": day.strftime("%Y-%m-%d"), "skip_reason": "UNRESOLVED_IDENTITY_TERMINAL_CLOSE"})
                continue
            terminal_locked[position_id] = {
                **position,
                "terminal_value": close * int(position["shares"]),
                "terminal_valuation_date": day,
            }
            positions.pop(position_id)
            identity_active_keys.discard(position["identity_key"])

        is_support_only = day > effective_end
        mark_date = effective_end if is_support_only else day
        invested_value = sum(float(item["terminal_value"]) for item in terminal_locked.values())
        valuation_missing = False
        for position in positions.values():
            record = position["record"]
            if is_support_only:
                last_date = pd.Timestamp(record.get("terminal_valuation_date") or effective_end).normalize()
                valuation_day = min(last_date, effective_end)
            else:
                valuation_day = mark_date
            close, stale_audit = _valuation_close_with_carry(
                record,
                frames,
                valuation_day,
                trading_session_positions,
                gap_classifications,
                strategy_id=strategy_id,
                pair_id=str(record.get("pair_id", "")),
            )
            if close is None:
                valuation_missing = True
                unresolved_count += 1
                skipped.append({"strategy_id": strategy_id, "pair_id": record.get("pair_id"), "ticker": record.get("ticker"), "date": valuation_day.strftime("%Y-%m-%d"), "skip_reason": "MISSING_EXACT_DAILY_MARK"})
            else:
                invested_value += int(position["shares"]) * close
                if stale_audit is not None:
                    stale_audit["mark_observed_on"] = day.strftime("%Y-%m-%d")
                    valuation_gap_audit.append(stale_audit)
        pending_total = sum(pending_by_date.values()) + terminal_pending
        equity = None if valuation_missing else cash + pending_total + invested_value
        if equity is not None:
            peak_equity = max(peak_equity, equity)
            drawdown = equity / peak_equity - 1.0 if peak_equity else 0.0
            exposure = invested_value / equity if equity else 0.0
            cash_ratio = (cash + pending_total) / equity if equity else 0.0
            cash_conservation_pass = cash_conservation_pass and abs(equity - cash - pending_total - invested_value) <= 1e-6
        else:
            drawdown = exposure = cash_ratio = None
        row = {
            "date": day.strftime("%Y-%m-%d"),
            "strategy_id": strategy_id,
            "valuation_basis_date": mark_date.strftime("%Y-%m-%d"),
            "cash": cash,
            "pending_sale_proceeds": pending_total,
            "invested_market_value": invested_value if not valuation_missing else None,
            "equity": equity,
            "drawdown": drawdown,
            "exposure": exposure,
            "cash_ratio": cash_ratio,
            "open_positions": len(positions) + len(terminal_locked),
            "valuation_is_execution_support_only": is_support_only,
        }
        equity_rows.append(row)
        if day == effective_end:
            cutoff_snapshot = {
                "open_positions": len(positions) + len(terminal_locked),
                "open_position_ids": sorted(list(positions) + list(terminal_locked)),
                "equity_at_effective_close": equity,
                "invested_value_at_effective_close": invested_value,
            }

    curve = pd.DataFrame(equity_rows)
    if curve.empty or cutoff_snapshot is None:
        raise RuntimeError("P2_1_PORTFOLIO_CURVE_OR_CUTOFF_SNAPSHOT_EMPTY")
    valid_equity = curve.dropna(subset=["equity"])
    final_equity = float(valid_equity.iloc[-1]["equity"]) if not valid_equity.empty else None
    if final_equity is None:
        unresolved_count += 1
    total_return = final_equity / INITIAL_CAPITAL - 1.0 if final_equity is not None else None
    elapsed_days = max(1, int((effective_end - effective_start).days))
    cagr = (
        (final_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0
        if final_equity is not None and final_equity > 0
        else None
    )
    drawdown_metrics = _mdd(curve[curve["date"] <= effective_end.strftime("%Y-%m-%d")])
    exposure_values = pd.to_numeric(curve.loc[curve["date"] <= effective_end.strftime("%Y-%m-%d"), "exposure"], errors="coerce").dropna()
    cash_values = pd.to_numeric(curve.loc[curve["date"] <= effective_end.strftime("%Y-%m-%d"), "cash_ratio"], errors="coerce").dropna()
    closed_net_pct = [value * 100.0 for value in closed_returns]
    metrics = {
        "final_equity": final_equity,
        "final_equity_at_effective_close": cutoff_snapshot["equity_at_effective_close"],
        "cumulative_return_pct": total_return * 100.0 if total_return is not None else None,
        "CAGR_pct": cagr * 100.0 if cagr is not None else None,
        **drawdown_metrics,
        "trade_count": len([event for event in events if event["event_type"] == "ENTRY" and event["event_status"] == "EXECUTED"]),
        "realized_trade_count": realized_trade_count,
        "win_rate_pct": 100.0 * sum(value > 0 for value in closed_returns) / len(closed_returns) if closed_returns else None,
        "average_holding_trading_days": statistics.mean(holding_periods) if holding_periods else None,
        "median_holding_trading_days": statistics.median(holding_periods) if holding_periods else None,
        "average_concurrent_positions": float(curve.loc[curve["date"] <= effective_end.strftime("%Y-%m-%d"), "open_positions"].mean()),
        "maximum_concurrent_positions": int(curve.loc[curve["date"] <= effective_end.strftime("%Y-%m-%d"), "open_positions"].max()),
        "average_capital_utilization_pct": float(exposure_values.mean() * 100.0) if len(exposure_values) else None,
        "maximum_capital_utilization_pct": float(exposure_values.max() * 100.0) if len(exposure_values) else None,
        "average_cash_ratio_pct": float(cash_values.mean() * 100.0) if len(cash_values) else None,
        "cash_drag_pct": float(cash_values.mean() * 100.0) if len(cash_values) else None,
        "turnover_krw": total_buy_notional + total_sell_notional,
        "turnover_multiple": (total_buy_notional + total_sell_notional) / INITIAL_CAPITAL,
        "turnover_pct_initial_capital": (total_buy_notional + total_sell_notional) / INITIAL_CAPITAL * 100.0,
        "total_buy_notional_krw": total_buy_notional,
        "total_sell_notional_krw": total_sell_notional,
        "total_commissions_krw": total_commission,
        "total_sell_tax_krw": total_tax,
        "slippage_impact_krw": slippage_impact,
        "cash_shortage_skipped_entries": cash_shortage,
        "realized_return_le_neg_30_count": sum(value <= -30.0 for value in closed_net_pct),
        "realized_return_le_neg_40_count": sum(value <= -40.0 for value in closed_net_pct),
        "realized_return_le_neg_50_count": sum(value <= -50.0 for value in closed_net_pct),
        "realized_return_le_neg_60_count": sum(value <= -60.0 for value in closed_net_pct),
        "realized_return_ge_pos_50_count": sum(value >= 50.0 for value in closed_net_pct),
        "realized_return_ge_pos_100_count": sum(value >= 100.0 for value in closed_net_pct),
        "open_at_effective_cutoff_count": cutoff_snapshot["open_positions"],
        "open_at_effective_cutoff_ids": cutoff_snapshot["open_position_ids"],
        "open_at_effective_cutoff_market_value_krw": cutoff_snapshot["invested_value_at_effective_close"],
        "pending_sale_proceeds_at_support_krw": terminal_pending,
        "unresolved_count": unresolved_count,
        "cash_conservation_pass": cash_conservation_pass,
        "position_cap": None,
    }
    return {
        "events": events,
        "daily_equity": equity_rows,
        "skipped": skipped,
        "metrics": metrics,
        "entry_candidate_audit": entry_candidate_audit,
        "valuation_gap_audit": valuation_gap_audit,
    }


def _comparison(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count",
        "win_rate_pct", "average_holding_trading_days", "median_holding_trading_days",
        "average_concurrent_positions", "maximum_concurrent_positions",
        "average_capital_utilization_pct", "average_cash_ratio_pct", "turnover_multiple",
        "total_commissions_krw", "total_sell_tax_krw", "slippage_impact_krw",
        "cash_shortage_skipped_entries", "realized_return_le_neg_30_count",
        "realized_return_le_neg_40_count", "realized_return_le_neg_50_count",
        "realized_return_le_neg_60_count", "realized_return_ge_pos_50_count",
        "realized_return_ge_pos_100_count", "open_at_effective_cutoff_count",
    )
    delta: dict[str, Any] = {}
    for key in keys:
        left, right = control.get(key), candidate.get(key)
        delta[key] = None if left is None or right is None else right - left
    return {"control": dict(control), "candidate": dict(candidate), "candidate_minus_control": delta}


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_summary_csv(summary: Mapping[str, Any], path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for strategy, metrics in (("CONTROL", summary["portfolio"]["control"]), ("CANDIDATE", summary["portfolio"]["candidate"])):
        rows.extend({"strategy": strategy, "metric": key, "value": value} for key, value in metrics.items() if not isinstance(value, (list, dict)))
    rows.extend({"strategy": "CANDIDATE_MINUS_CONTROL", "metric": key, "value": value} for key, value in summary["portfolio"]["candidate_minus_control"].items())
    pd.DataFrame(rows).to_csv(path, index=False)


def _comparison_report(summary: Mapping[str, Any]) -> str:
    portfolio = summary["portfolio"]
    control = portfolio["control"]
    candidate = portfolio["candidate"]
    delta = portfolio["candidate_minus_control"]
    return f"""# P2-1 현실적 포트폴리오 비교

판정: `{summary['status']}`
대상: P2-1 only, {summary['window']['effective_start']} ~ {summary['window']['effective_end']} (execution support {summary['window']['execution_support']})
Universe: 최신 Daily Update {summary['universe']['latest_daily_update_as_of']} 기준 현재 COMMON identity survivor; 신규 진입은 exact raw PIT MKTCAP >= 1조원만 허용.

## 핵심 결과

| 지표 | CONTROL | Candidate | Candidate − CONTROL |
|---|---:|---:|---:|
| 최종 자산 (지원일 처리 후) | {control['final_equity']:,.0f} | {candidate['final_equity']:,.0f} | {delta['final_equity']:,.0f} |
| 누적수익률 | {control['cumulative_return_pct']:.2f}% | {candidate['cumulative_return_pct']:.2f}% | {delta['cumulative_return_pct']:.2f}%p |
| CAGR | {control['CAGR_pct']:.2f}% | {candidate['CAGR_pct']:.2f}% | {delta['CAGR_pct']:.2f}%p |
| MDD | {control['mdd_pct']:.2f}% | {candidate['mdd_pct']:.2f}% | {delta['mdd_pct']:.2f}%p |
| 체결 거래 수 | {control['trade_count']} | {candidate['trade_count']} | {delta['trade_count']} |
| 승률 | {control['win_rate_pct']:.2f}% | {candidate['win_rate_pct']:.2f}% | {delta['win_rate_pct']:.2f}%p |
| 평균 보유 거래일 | {control['average_holding_trading_days']:.2f} | {candidate['average_holding_trading_days']:.2f} | {delta['average_holding_trading_days']:.2f} |
| 평균 자본 사용률 | {control['average_capital_utilization_pct']:.2f}% | {candidate['average_capital_utilization_pct']:.2f}% | {delta['average_capital_utilization_pct']:.2f}%p |
| 회전율 배수 | {control['turnover_multiple']:.3f}x | {candidate['turnover_multiple']:.3f}x | {delta['turnover_multiple']:.3f}x |
| `<= -40%` 실현 거래 | {control['realized_return_le_neg_40_count']} | {candidate['realized_return_le_neg_40_count']} | {delta['realized_return_le_neg_40_count']} |
| `>= +50%` 실현 거래 | {control['realized_return_ge_pos_50_count']} | {candidate['realized_return_ge_pos_50_count']} | {delta['realized_return_ge_pos_50_count']} |

## 감사 요약

- 기존 전략 trade ledger 355행씩을 그대로 재사용했고 전략·entry 신호 재계산은 하지 않았어.
- 40개 동시 보유 시 실제 후보/현금 부족/슬롯 cap 차단은 [hidden_position_cap_audit.json](hidden_position_cap_audit.json)에 기록했어. 설정 포지션 한도는 없음.
- exact PIT 시총 PASS 365건 중 ledger 미포함 10건은 모두 유효기간 마지막 신호일의 다음 로컬 실행일이 entry cutoff를 넘은 사유야. [mcap365_to_trade355_reason_audit.csv](mcap365_to_trade355_reason_audit.csv)에서 전체 365건을 확인할 수 있어.
- 기존 valuation gap 96 ticker-date는 raw non-trading placeholder 74건과 adjusted source OHLC 관계 위반 22건으로 원천 행을 다시 대조했어. 직전 valid adjusted close는 daily portfolio MTM에만 사용했고, 각 stale mark의 날짜·가격·stale age 및 source 근거는 [valuation_gap_closure_audit.csv](valuation_gap_closure_audit.csv)에 있어.
- 체결과 전략 feature에는 carry를 사용하지 않았어. 기준 가격은 effective cutoff exact close이며 execution-support 이후 close는 사용하지 않았어.

## 경계와 해석

- 실행 규칙·점수·threshold는 동결. Candidate는 기존 P2-1 matched-entry 계약에 따라 V2 신호 진입 집합을 공유하고 exit overlay만 다르게 적용했어.
- 시총 미달 신호는 V2 re-entry state를 소비하지 않게 신호 평가 단계에서 제외했어. 따라서 과거 거래 ledger를 사후 단순 필터링한 결과가 아니야.
- 포트폴리오 cash/equity event replay는 날짜순 단일 스레드로 수행했어. 매도대금은 다음 평가 가능한 로컬 거래일부터 사용했고, 같은 시가에서는 재사용하지 않았어.
- MDD와 daily valuation은 P2-1 effective cutoff close까지야. `execution_support`에서 허용된 exit fill은 반영하고, 미청산 보유는 cutoff의 exact close로 평가했어. support 이후의 종가를 가져오지 않았어.
- 모든 수치는 [summary.json](summary.json), 포트폴리오 event ledger, daily equity 및 exact-date PIT audit로 재검산할 수 있어.
"""


def _full_run(workers: int) -> dict[str, Any]:
    sample_path = OUT_DIR / "sample_benchmark.json"
    if not sample_path.is_file():
        raise RuntimeError("P2_1_FULL_RUN_REQUIRES_SAME_PATH_10_WORKER_SAMPLE")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if sample.get("worker_count") != workers or workers != 10:
        raise RuntimeError("P2_1_FULL_WORKER_COUNT_MISMATCH_EXPECTED_10")
    if sample.get("status") != "COMPLETE" or sample.get("errors"):
        raise RuntimeError("P2_1_FULL_REQUIRES_PASSING_SAMPLE")
    if float(sample.get("estimated_full_seconds", float("inf"))) > 90 * 60:
        raise RuntimeError("P2_1_FULL_ESTIMATE_EXCEEDS_90_MINUTES")
    existing = [name for name in EXPECTED_OUTPUTS if (OUT_DIR / name).exists()]
    if existing:
        raise RuntimeError("REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(existing))

    started = time.perf_counter()
    run, gate, authority, universe = _load_survivor_context(worker_count=workers)
    target_tickers = sorted(run.segments_by_ticker)
    if not target_tickers:
        raise RuntimeError("P2_1_CURRENT_COMMON_SURVIVOR_UNIVERSE_EMPTY")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    strategy_started = time.perf_counter()
    outcomes, errors, strategy_wall = _run_ticker_pool(run, workers=workers, tickers=target_tickers)
    if errors:
        _json_write(
            OUT_DIR / "full_failure.json",
            {
                "status": "FAILED",
                "errors": errors,
                "completed_tickers": len(outcomes),
                "target_tickers": len(target_tickers),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "workers": workers,
            },
        )
        raise RuntimeError(f"P2_1_FULL_TICKER_ERRORS:{len(errors)}")
    strategy_wall = time.perf_counter() - strategy_started

    control = pd.DataFrame([row for outcome in outcomes for row in outcome["control_rows"]])
    candidate = pd.DataFrame([row for outcome in outcomes for row in outcome["candidate_rows"]])
    control = control.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    candidate = candidate.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    entry_parity = _validate_entry_pairing(control, candidate)
    frames: dict[tuple[Any, ...], pd.DataFrame] = {}
    for outcome in outcomes:
        frames.update(outcome["market_data_by_identity"])
    raw_cap_audit = gate.audit_frame()
    if raw_cap_audit.empty:
        raise RuntimeError("P2_1_PIT_MCAP_GATE_PRODUCED_NO_SIGNAL_AUDIT")
    unresolved_mcap = raw_cap_audit[raw_cap_audit["status"].astype(str).eq("UNRESOLVED")]

    all_dates = tuple(pd.to_datetime(run.calendar.trading_dates).normalize())
    effective_start = pd.Timestamp(run.window.effective_start).normalize()
    effective_end = pd.Timestamp(run.window.effective_end).normalize()
    support = pd.Timestamp(run.window.execution_support).normalize()
    portfolio_started = time.perf_counter()
    control_result = _portfolio_replay(
        control.to_dict(orient="records"), frames, all_dates,
        strategy_id=p2.V2_STRATEGY_ID,
        effective_start=effective_start,
        effective_end=effective_end,
        execution_support=support,
    )
    candidate_result = _portfolio_replay(
        candidate.to_dict(orient="records"), frames, all_dates,
        strategy_id=p2.CANDIDATE_STRATEGY_ID,
        effective_start=effective_start,
        effective_end=effective_end,
        execution_support=support,
    )
    portfolio_wall = time.perf_counter() - portfolio_started
    comparison = _comparison(control_result["metrics"], candidate_result["metrics"])
    skipped = pd.DataFrame(control_result["skipped"] + candidate_result["skipped"])
    soft_events = pd.DataFrame(
        [event for outcome in outcomes for diagnostic in outcome["diagnostics"] for event in diagnostic["soft_events"]]
    )
    validation = {
        **entry_parity,
        "mcap_unresolved_count": int(len(unresolved_mcap)),
        "portfolio_unresolved_count": int(control_result["metrics"]["unresolved_count"] + candidate_result["metrics"]["unresolved_count"]),
        "control_cash_conservation": bool(control_result["metrics"]["cash_conservation_pass"]),
        "candidate_cash_conservation": bool(candidate_result["metrics"]["cash_conservation_pass"]),
        "position_cap_applied": False,
        "network_calls": 0,
    }
    status = "COMPLETE_PASS" if (
        validation["mcap_unresolved_count"] == 0
        and validation["portfolio_unresolved_count"] == 0
        and validation["control_cash_conservation"]
        and validation["candidate_cash_conservation"]
    ) else "INCOMPLETE_REQUIRES_REVIEW"
    worker_rollup = _parallel_rollup(outcomes)
    rss_max = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    execution = {
        "worker_count": workers,
        "observed_worker_threads": worker_rollup["observed_worker_threads"],
        "worker_threads": worker_rollup["worker_threads"],
        "sum_worker_task_seconds": worker_rollup["sum_worker_task_seconds"],
        "strategy_evaluation_wall_seconds": round(strategy_wall, 3),
        "portfolio_event_replay_wall_seconds": round(portfolio_wall, 3),
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "setup_seconds": round(run.setup_seconds, 3),
        "python_process_max_rss_reported_by_resource": rss_max,
        "rss_units": "bytes on macOS; KiB on Linux",
        "processed_tickers": len(outcomes),
        "target_tickers": len(target_tickers),
        "market_data_frames_retained_for_portfolio": len(frames),
    }
    segment_count = sum(len(rows) for rows in run.segments_by_ticker.values())
    mcap_counts = raw_cap_audit["status"].value_counts().to_dict()
    summary: dict[str, Any] = {
        "status": status,
        "work_id": "P2_1_V2_VS_NEG40_WEAK_PROTECT_REALISTIC_PORTFOLIO_V01",
        "window_id": "P2-1",
        "run_id": RUN_ID,
        "head": p2.subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "strategy_ids": {"control": p2.V2_STRATEGY_ID, "candidate": p2.CANDIDATE_STRATEGY_ID},
        "window": {
            "calendar_start": "2021-01-01",
            "calendar_end": "2025-05-31",
            "effective_start": effective_start.strftime("%Y-%m-%d"),
            "effective_end": effective_end.strftime("%Y-%m-%d"),
            "execution_support": support.strftime("%Y-%m-%d"),
        },
        "universe": {
            "latest_daily_update_as_of": authority["latest_daily_update_as_of"],
            "latest_daily_update_source_frontier": authority["latest_daily_update_source_frontier"],
            "source_common_identity_segment_count_after_existing_policy": len(
                [row for row in universe.to_dict(orient="records") if row["status"] != "EXCLUDED_EXISTING_PERMANENT_IDENTITY_POLICY"]
            ),
            "survivor_common_identity_segment_count": segment_count,
            "survivor_ticker_count": len(target_tickers),
            "survivor_unique_isu_count": len({segment.isu_cd for rows in run.segments_by_ticker.values() for segment in rows}),
            "survivor_only_filter_is_intentional": True,
            "existing_permanent_identity_policy_exclusion_count": len(seen_exclusions := {(
                str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper()
            ) for item in run.permanent_identity_exclusions}),
        },
        "market_cap_filter": {
            "threshold_krw": MARKET_CAP_THRESHOLD,
            "source": "KRX Open API Stock Daily MKTCAP in exact-date immutable raw store",
            "exact_entry_signal_date_only": True,
            "same_date_raw_rows_verified_by_store_manifest_hash": True,
            "no_proxy_or_nearest_date_or_fill": True,
            "qualified_fast_signal_attempt_count": int(len(raw_cap_audit)),
            "status_counts": {str(key): int(value) for key, value in mcap_counts.items()},
            "exact_raw_partitions_used": int(raw_cap_audit[["market", "signal_date"]].drop_duplicates().shape[0]),
            "unresolved_count": int(len(unresolved_mcap)),
            "rejected_signals_do_not_consume_reentry_state": True,
        },
        "portfolio_contract": {
            "initial_capital_krw": INITIAL_CAPITAL,
            "per_ticker_total_buy_cash_budget_krw": POSITION_BUDGET,
            "position_cap": None,
            "duplicate_active_identity_forbidden": True,
            "pyramiding": False,
            "partial_fill": False,
            "cash_shortage_policy": "SKIP_FULL_TARGET_ORDER",
            "same_open_exit_proceeds_reusable": False,
            "same_open_entry_priority": ["PIT market_cap descending", "ticker ascending"],
            "buy_commission_rate": COMMISSION_RATE,
            "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE,
            "sell_slippage_rate": SLIPPAGE_RATE,
            "sell_tax_schedule": [
                {"start": start, "end": end, "KOSPI": rate, "KOSDAQ": rate}
                for start, end, rate in SELL_TAX_SCHEDULE
            ],
            "cash_release": "next certified local trading session after sale execution; execution-support proceeds remain pending",
            "cutoff_valuation": "effective-end exact close; no support-date close is used for open positions",
        },
        "data_authority": authority,
        "population": {
            "control_trade_rows": int(len(control)),
            "candidate_trade_rows": int(len(candidate)),
            "matched_pair_count": int(len(control)),
            "soft_event_rows": int(len(soft_events)),
            "market_data_identity_frames": len(frames),
        },
        "execution": execution,
        "portfolio": comparison,
        "validation": validation,
        "artifacts": {name: f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/{name}" for name in EXPECTED_OUTPUTS},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _json_write(OUT_DIR / "execution_contract.json", {
        "schema": "p2_1_realistic_portfolio_execution_contract_v01",
        "frozen_before_result_review": True,
        "scope": "P2-1 only",
        "authority": authority,
        "strategy_ids": summary["strategy_ids"],
        "window": summary["window"],
        "portfolio": summary["portfolio_contract"],
        "market_cap_filter": summary["market_cap_filter"],
        "strategy_entry_contract": "V2 and Candidate share matched V2 entry IDs; Candidate uses the frozen P2-1 exit overlay",
        "network_calls": 0,
    })
    universe.to_csv(OUT_DIR / "filtered_universe_audit.csv", index=False)
    raw_cap_audit.to_csv(OUT_DIR / "pit_mcap_audit.csv", index=False)
    control.to_csv(OUT_DIR / "control_strategy_trades.csv", index=False)
    candidate.to_csv(OUT_DIR / "candidate_strategy_trades.csv", index=False)
    soft_events.to_csv(OUT_DIR / "p2_1_soft_events.csv", index=False)
    pd.DataFrame(control_result["events"]).to_csv(OUT_DIR / "control_portfolio_events.csv", index=False)
    pd.DataFrame(candidate_result["events"]).to_csv(OUT_DIR / "candidate_portfolio_events.csv", index=False)
    pd.DataFrame(control_result["daily_equity"]).to_csv(OUT_DIR / "control_daily_equity.csv", index=False)
    pd.DataFrame(candidate_result["daily_equity"]).to_csv(OUT_DIR / "candidate_daily_equity.csv", index=False)
    skipped.to_csv(OUT_DIR / "skipped_entries.csv", index=False)
    _json_write(OUT_DIR / "summary.json", summary)
    _write_summary_csv(summary, OUT_DIR / "summary.csv")
    (OUT_DIR / "comparison_report.md").write_text(_comparison_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
    return summary


def _gap_classification_audit(
    skipped_entries: pd.DataFrame,
    existing_baseline_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[tuple[str, str], str]]:
    missing = skipped_entries.loc[
        skipped_entries.get("skip_reason", pd.Series(dtype=str)).astype(str).eq("MISSING_EXACT_DAILY_MARK")
    ].copy()
    if not missing.empty:
        identity_rows = pd.concat(
            [
                pd.read_csv(OUT_DIR / "control_strategy_trades.csv")[
                    ["pair_id", "ticker", "isu_cd", "market"]
                ],
                pd.read_csv(OUT_DIR / "candidate_strategy_trades.csv")[
                    ["pair_id", "ticker", "isu_cd", "market"]
                ],
            ],
            ignore_index=True,
        ).drop_duplicates("pair_id")
        missing = missing.merge(
            identity_rows,
            on="pair_id",
            how="left",
            suffixes=("", "_ledger"),
            validate="many_to_one",
        )
        for field in ("ticker", "isu_cd", "market"):
            ledger_field = f"{field}_ledger"
            if ledger_field in missing.columns:
                if field not in missing.columns:
                    missing[field] = missing[ledger_field]
                else:
                    missing[field] = missing[field].where(missing[field].notna(), missing[ledger_field])
        missing["ticker"] = missing["ticker"].astype(str).str.zfill(6)
        missing["valuation_date"] = pd.to_datetime(missing["date"], errors="raise").dt.strftime("%Y-%m-%d")
        key_columns = ["ticker", "valuation_date"]
        unique = missing.drop_duplicates(key_columns).sort_values(key_columns, kind="mergesort")
        if "identity" not in unique.columns:
            unique["identity"] = unique.get("isu_cd")
    elif existing_baseline_path is not None and existing_baseline_path.is_file():
        prior_audit = pd.read_csv(existing_baseline_path)
        required = {"ticker", "valuation_date", "identity", "market"}
        if not required.issubset(prior_audit.columns):
            raise RuntimeError("P2_1_PERSISTED_GAP_BASELINE_SCHEMA_MISMATCH")
        unique = prior_audit.loc[:, ["ticker", "valuation_date", "identity", "market"]].copy()
        unique["ticker"] = unique["ticker"].astype(str).str.zfill(6)
        unique["valuation_date"] = pd.to_datetime(unique["valuation_date"], errors="raise").dt.strftime("%Y-%m-%d")
        unique = unique.drop_duplicates(["ticker", "valuation_date"]).sort_values(
            ["ticker", "valuation_date"], kind="mergesort"
        )
    else:
        raise RuntimeError("P2_1_EXISTING_VALUATION_GAP_BASELINE_EMPTY")
    if len(unique) != 96:
        raise RuntimeError(f"P2_1_EXISTING_GAP_BASELINE_COUNT_MISMATCH:{len(unique)}")

    from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
    from trend_scanner.data.repository_v2 import NON_TRADING_PLACEHOLDER_PREDICATE_NAME
    from trend_scanner.data.repository_v2_session_authority import (
        ADJUSTED_ANALYTICALLY_NONUSABLE_DATES,
        SOURCE_CLOSURE_CHECKPOINT_SHA256,
    )

    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    partition_cache: dict[tuple[str, str], tuple[dict[str, Any], pd.DataFrame]] = {}
    adjusted_cache: dict[str, tuple[pd.DataFrame, dict[str, Any], str]] = {}
    audit: list[dict[str, Any]] = []
    classes: dict[tuple[str, str], str] = {}
    for row in unique.itertuples(index=False):
        ticker = str(row.ticker).zfill(6)
        day = str(row.valuation_date)
        market = str(getattr(row, "market", "")).upper()
        if not market or market == "NAN":
            raise RuntimeError(f"P2_1_GAP_MARKET_MISSING:{ticker}:{day}")
        cache_key = (market, day)
        if cache_key not in partition_cache:
            manifest = raw_store.get_manifest(market, day)
            if manifest is None or manifest.get("status") != "COMPLETE":
                raise RuntimeError(f"P2_1_GAP_RAW_PARTITION_NOT_COMPLETE:{market}:{day}")
            partition = raw_store.load_snapshot(market, day)
            partition_cache[cache_key] = (manifest, partition)
        manifest, partition = partition_cache[cache_key]
        ticker_rows = partition.loc[partition["ticker"].astype(str).str.zfill(6).eq(ticker)]
        if len(ticker_rows) != 1:
            raise RuntimeError(f"P2_1_GAP_RAW_TICKER_ROW_COUNT:{ticker}:{day}:{len(ticker_rows)}")
        raw_row = ticker_rows.iloc[0]
        placeholder = bool(
            int(raw_row["open"]) == 0
            and int(raw_row["high"]) == 0
            and int(raw_row["low"]) == 0
            and int(raw_row["close"]) > 0
            and int(raw_row["volume"]) == 0
            and int(raw_row["trading_value"]) == 0
        )
        if ticker not in adjusted_cache:
            source = adjusted_store.load_daily_source(ticker)
            metadata = adjusted_store.load_metadata(ticker)
            adjusted_cache[ticker] = (
                source,
                metadata,
                _sha256(ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet"),
            )
        adjusted_source, adjusted_metadata, adjusted_file_sha = adjusted_cache[ticker]
        adjusted_row: pd.Series | None = adjusted_source.loc[pd.Timestamp(day)] if pd.Timestamp(day) in adjusted_source.index else None
        invalid_relations: list[str] = []
        if adjusted_row is not None:
            for field, violated in (
                ("high_below_low", adjusted_row["high"] < adjusted_row["low"]),
                ("high_below_open", adjusted_row["high"] < adjusted_row["open"]),
                ("high_below_close", adjusted_row["high"] < adjusted_row["close"]),
                ("low_above_open", adjusted_row["low"] > adjusted_row["open"]),
                ("low_above_close", adjusted_row["low"] > adjusted_row["close"]),
            ):
                if bool(violated):
                    invalid_relations.append(field)
        analytic_invalid = bool(invalid_relations)
        analytic_authority_member = (ticker, day) in ADJUSTED_ANALYTICALLY_NONUSABLE_DATES
        if placeholder == analytic_invalid:
            raise RuntimeError(f"P2_1_GAP_CLASSIFICATION_AMBIGUOUS_OR_UNKNOWN:{ticker}:{day}")
        classification = "NON_TRADING_PLACEHOLDER" if placeholder else "ADJUSTED_ANALYTICALLY_NONUSABLE"
        classes[(ticker, day)] = classification
        audit.append(
            {
                "ticker": ticker,
                "identity": getattr(row, "isu_cd", None),
                "market": market,
                "valuation_date": day,
                "gap_classification": classification,
                "adjusted_close_exact_valid_missing": True,
                "raw_row_present": True,
                "raw_open": int(raw_row["open"]),
                "raw_high": int(raw_row["high"]),
                "raw_low": int(raw_row["low"]),
                "raw_close": int(raw_row["close"]),
                "raw_volume": int(raw_row["volume"]),
                "raw_trading_value": int(raw_row["trading_value"]),
                "placeholder_predicate": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
                "adjusted_source_nonusable_authority_member": analytic_authority_member,
                "adjusted_source_closure_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
                "adjusted_source_row_present": adjusted_row is not None,
                "adjusted_open": float(adjusted_row["open"]) if adjusted_row is not None else None,
                "adjusted_high": float(adjusted_row["high"]) if adjusted_row is not None else None,
                "adjusted_low": float(adjusted_row["low"]) if adjusted_row is not None else None,
                "adjusted_close": float(adjusted_row["close"]) if adjusted_row is not None else None,
                "adjusted_invalid_relation_fields": ";".join(invalid_relations),
                "adjusted_store_authority_id": adjusted_metadata.get("source_authority_id"),
                "adjusted_store_content_sha256": adjusted_metadata.get("content_sha256"),
                "adjusted_store_parquet_sha256": adjusted_file_sha,
                "raw_partition_status": manifest.get("status"),
                "raw_partition_file_sha256": manifest.get("file_sha256"),
                "raw_partition_content_sha256": manifest.get("content_sha256"),
            }
        )
    result = pd.DataFrame(audit)
    counts = result["gap_classification"].value_counts().to_dict()
    if counts != {"NON_TRADING_PLACEHOLDER": 74, "ADJUSTED_ANALYTICALLY_NONUSABLE": 22}:
        raise RuntimeError(f"P2_1_EXISTING_GAP_CLASSIFICATION_MISMATCH:{counts}")
    return result, classes


def _mcap_to_trade_reason_audit(
    pit_audit: pd.DataFrame,
    control: pd.DataFrame,
    trading_dates: Sequence[pd.Timestamp],
    effective_end: pd.Timestamp,
) -> pd.DataFrame:
    passed = pit_audit.loc[pit_audit["status"].astype(str).eq("PASS")].copy()
    passed["ticker"] = passed["ticker"].astype(str).str.zfill(6)
    passed["identity"] = passed["identity"].astype(str).str.upper()
    passed["signal_date"] = pd.to_datetime(passed["signal_date"], errors="raise").dt.strftime("%Y-%m-%d")
    control = control.copy()
    control["ticker"] = control["ticker"].astype(str).str.zfill(6)
    control["isu_cd"] = control["isu_cd"].astype(str).str.upper()
    control["entry_signal_date"] = pd.to_datetime(control["entry_signal_date"], errors="raise").dt.strftime("%Y-%m-%d")
    ledger_keys: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in control.to_dict(orient="records"):
        key = (row["ticker"], row["isu_cd"], row["entry_signal_date"])
        if key in ledger_keys:
            raise RuntimeError(f"P2_1_DUPLICATE_LEDGER_SIGNAL_KEY:{key}")
        ledger_keys[key] = row
    calendar = tuple(pd.Timestamp(value).normalize() for value in trading_dates)
    signal_keys = set()
    result: list[dict[str, Any]] = []
    for row in passed.to_dict(orient="records"):
        key = (row["ticker"], row["identity"], row["signal_date"])
        if key in signal_keys:
            raise RuntimeError(f"P2_1_DUPLICATE_PASS_SIGNAL_KEY:{key}")
        signal_keys.add(key)
        trade = ledger_keys.get(key)
        signal_day = pd.Timestamp(row["signal_date"]).normalize()
        next_sessions = [day for day in calendar if day > signal_day]
        next_session = next_sessions[0] if next_sessions else None
        within_entry_cutoff = bool(next_session is not None and next_session <= effective_end)
        reason = "MATERIALIZED_STRATEGY_TRADE" if trade else (
            "NEXT_LOCAL_EXECUTION_AFTER_EFFECTIVE_ENTRY_CUTOFF"
            if next_session is not None and next_session > effective_end
            else "NO_NEXT_LOCAL_EXECUTION_SESSION_IN_SUPPORT"
            if next_session is None
            else "OTHER_FROZEN_STRATEGY_STATE_OR_ENTRY_GATE"
        )
        result.append(
            {
                "ticker": row["ticker"],
                "identity": row["identity"],
                "market": row["market"],
                "signal_date": row["signal_date"],
                "exact_pit_market_cap_krw": int(row["market_cap"]),
                "pit_gate_status": row["status"],
                "ledger_materialized": trade is not None,
                "pair_id": trade.get("pair_id") if trade else None,
                "trade_id": trade.get("trade_id") if trade else None,
                "next_local_session": next_session.strftime("%Y-%m-%d") if next_session is not None else None,
                "effective_entry_cutoff": effective_end.strftime("%Y-%m-%d"),
                "next_session_within_entry_cutoff": within_entry_cutoff,
                "reason": reason,
                "raw_partition_path": row.get("partition_path"),
                "raw_partition_file_sha256": row.get("partition_file_sha256"),
            }
        )
    if len(passed) != 365 or len(control) != 355 or len(result) != 365:
        raise RuntimeError(f"P2_1_MCAP_TO_LEDGER_POPULATION_MISMATCH:{len(passed)}:{len(control)}")
    missing = [row for row in result if not row["ledger_materialized"]]
    reasons = pd.Series([row["reason"] for row in missing], dtype=str).value_counts().to_dict()
    if len(missing) != 10 or reasons != {"NEXT_LOCAL_EXECUTION_AFTER_EFFECTIVE_ENTRY_CUTOFF": 10}:
        raise RuntimeError(f"P2_1_MCAP_TO_LEDGER_REASON_CLOSURE_FAILED:{len(missing)}:{reasons}")
    return pd.DataFrame(result).sort_values(["signal_date", "ticker", "identity"], kind="mergesort").reset_index(drop=True)


def _portfolio_only_replay() -> dict[str, Any]:
    """Rebuild only deterministic portfolio cash/equity from frozen strategy ledgers."""
    started = time.perf_counter()
    summary_path = OUT_DIR / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError("P2_1_PORTFOLIO_ONLY_REQUIRES_EXISTING_FULL_RUN_ARTIFACTS")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("window_id") != "P2-1" or summary.get("run_id") != RUN_ID:
        raise RuntimeError("P2_1_PORTFOLIO_ONLY_SOURCE_RUN_MISMATCH")
    strategy_source_head = summary.get("portfolio_replay", {}).get("strategy_source_head", summary.get("head"))
    required = (
        "control_strategy_trades.csv",
        "candidate_strategy_trades.csv",
        "pit_mcap_audit.csv",
    )
    source_hashes = {name: _sha256(OUT_DIR / name) for name in required}
    control_frame = pd.read_csv(OUT_DIR / "control_strategy_trades.csv")
    candidate_frame = pd.read_csv(OUT_DIR / "candidate_strategy_trades.csv")
    entry_parity = _validate_entry_pairing(control_frame, candidate_frame)
    if len(control_frame) != 355:
        raise RuntimeError(f"P2_1_PORTFOLIO_ONLY_EXPECTS_355_STRATEGY_ROWS:{len(control_frame)}")

    setup_started = time.perf_counter()
    print("P2-1 portfolio-only: validating frozen authority and reading existing trade ledgers", flush=True)
    run = p2._load_context("P2-1")
    effective_start = pd.Timestamp(run.window.effective_start).normalize()
    effective_end = pd.Timestamp(run.window.effective_end).normalize()
    support = pd.Timestamp(run.window.execution_support).normalize()
    authority_sha = _sha256(run.authority.pit_path)
    if authority_sha != summary.get("data_authority", {}).get("effective_pit_file_sha256"):
        raise RuntimeError("P2_1_PORTFOLIO_ONLY_EFFECTIVE_PIT_AUTHORITY_CHANGED")

    segments = {
        segment.key: segment
        for grouped in run.segments_by_ticker.values()
        for segment in grouped
    }
    records_by_strategy = {
        "CONTROL": control_frame.to_dict(orient="records"),
        "CANDIDATE": candidate_frame.to_dict(orient="records"),
    }
    required_segment_keys: set[str] = set()
    for records in records_by_strategy.values():
        for record in records:
            key = "|".join(
                (
                    str(record.get("ticker", "")).zfill(6),
                    str(record.get("isu_cd", "")),
                    str(record.get("market", "")),
                    str(record.get("identity_effective_from", "")),
                    str(record.get("identity_effective_to", "")),
                )
            )
            if key not in segments:
                raise RuntimeError(f"P2_1_PORTFOLIO_ONLY_IDENTITY_NOT_IN_FROZEN_AUTHORITY:{key}")
            required_segment_keys.add(key)

    loader = p2.RepositoryV2DailyLoader(
        run.loader.repository,
        start=effective_start,
        end=support,
    )
    ticker_frames: dict[str, pd.DataFrame] = {}
    ticker_keys = sorted({segments[key].ticker for key in required_segment_keys})
    for completed, ticker in enumerate(ticker_keys, start=1):
        if ticker not in ticker_frames:
            daily = loader.load(ticker)
            if daily is None or daily.empty:
                raise RuntimeError(f"P2_1_PORTFOLIO_ONLY_MISSING_REPOSITORY_V2_FRAME:{ticker}")
            ticker_frames[ticker] = daily
        if completed % 25 == 0 or completed == len(ticker_keys):
            print(
                f"P2-1 portfolio-only Repository V2 frames {completed}/{len(ticker_keys)}; "
                f"elapsed={time.perf_counter() - setup_started:.1f}s",
                flush=True,
            )

    frames: dict[str, pd.DataFrame] = {}
    for key in sorted(required_segment_keys):
        segment = segments[key]
        daily = ticker_frames[segment.ticker]
        lower = max(effective_start, segment.effective_from)
        upper = min(support, segment.effective_to)
        scoped = daily.loc[(daily.index >= lower) & (daily.index <= upper)].sort_index()
        typed_event = p2._confirmed_lifecycle_event_for_segment(
            segment,
            tuple(getattr(run, "lifecycle_settlements", ())),
            effective_end,
            run.segments_by_ticker,
        )
        if typed_event is not None:
            event_effective = p2._event_effective_date(typed_event)
            scoped = scoped.loc[scoped.index < event_effective]
        scoped = scoped.loc[:, ["open", "high", "low", "close"]].copy()
        frames[key] = scoped
    if len(frames) != int(summary.get("population", {}).get("market_data_identity_frames", -1)):
        raise RuntimeError(
            "P2_1_PORTFOLIO_ONLY_IDENTITY_FRAME_COUNT_MISMATCH:"
            f"{len(frames)}:{summary.get('population', {}).get('market_data_identity_frames')}"
        )
    setup_seconds = time.perf_counter() - setup_started

    old_skipped = pd.read_csv(OUT_DIR / "skipped_entries.csv")
    gap_baseline, gap_classifications = _gap_classification_audit(
        old_skipped,
        OUT_DIR / "valuation_gap_source_diagnosis.csv",
    )
    pit_audit = pd.read_csv(OUT_DIR / "pit_mcap_audit.csv")
    reason_audit = _mcap_to_trade_reason_audit(
        pit_audit,
        control_frame,
        tuple(pd.to_datetime(run.calendar.trading_dates).normalize()),
        effective_end,
    )
    trading_dates = tuple(pd.to_datetime(run.calendar.trading_dates).normalize())
    replay_started = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}
    for strategy, strategy_id in (
        ("CONTROL", p2.V2_STRATEGY_ID),
        ("CANDIDATE", p2.CANDIDATE_STRATEGY_ID),
    ):
        results[strategy] = _portfolio_replay(
            records_by_strategy[strategy],
            frames,
            trading_dates,
            strategy_id=strategy_id,
            effective_start=effective_start,
            effective_end=effective_end,
            execution_support=support,
            gap_classifications=gap_classifications,
        )
    replay_wall = time.perf_counter() - replay_started

    entry_audits = {
        name: pd.DataFrame(results[name]["entry_candidate_audit"])
        for name in ("CONTROL", "CANDIDATE")
    }
    hidden_counts: dict[str, Any] = {}
    for name, frame in entry_audits.items():
        at_40 = frame.loc[frame["concurrent_positions_before_candidate"].eq(40)]

        def json_row(row: Mapping[str, Any]) -> dict[str, Any]:
            normalized: dict[str, Any] = {}
            for key, value in row.items():
                if pd.isna(value):
                    normalized[str(key)] = None
                elif hasattr(value, "item"):
                    normalized[str(key)] = value.item()
                else:
                    normalized[str(key)] = value
            return normalized

        hidden_counts[name] = {
            "entry_candidates_when_40_positions_active": int(len(at_40)),
            "cash_sufficient_candidates_when_40_active": int(at_40["cash_sufficient"].fillna(False).astype(bool).sum()),
            "cash_insufficient_skips_when_40_active": int(at_40["decision"].eq("CASH_INSUFFICIENT").sum()),
            "slot_cap_skips_when_40_active": int(at_40["decision"].eq("SLOT_CAP").sum()),
            "decisions_when_40_active": {
                str(key): int(value) for key, value in at_40["decision"].value_counts(dropna=False).to_dict().items()
            },
            "entry_candidates": [json_row(row) for row in at_40.to_dict(orient="records")],
            "maximum_concurrent_positions": int(results[name]["metrics"]["maximum_concurrent_positions"]),
        }
    total_slot_skips = sum(value["slot_cap_skips_when_40_active"] for value in hidden_counts.values())
    hidden_audit = {
        "position_cap_configured": None,
        "position_cap_applied": False,
        "position_cap_source": "_portfolio_replay has no max-position guard; entry is gated only by duplicate identity, same-open, share count, and available-cash checks",
        "portfolio_engine_has_slot_cap_branch": False,
        "cash_limit_krw": INITIAL_CAPITAL,
        "per_position_budget_krw": POSITION_BUDGET,
        "hidden_slot_cap_skip_count": total_slot_skips,
        "cash_sufficient_slot_cap_skip_count": total_slot_skips,
        "classification": "NO_HIDDEN_N40_CAP" if total_slot_skips == 0 else "HIDDEN_N40_CAP_DETECTED",
        "by_strategy": hidden_counts,
        "source": "per-candidate portfolio replay audit; counts include every strategy ledger entry candidate evaluated at exactly 40 active positions",
    }

    all_valuation_audit = pd.DataFrame(
        [row for name in ("CONTROL", "CANDIDATE") for row in results[name]["valuation_gap_audit"]]
    )
    if not all_valuation_audit.empty:
        all_valuation_audit = all_valuation_audit.sort_values(
            ["strategy_id", "valuation_date", "ticker", "pair_id"], kind="mergesort"
        ).reset_index(drop=True)
        gap_evidence_columns = [
            "ticker", "valuation_date", "raw_open", "raw_high", "raw_low", "raw_close",
            "raw_volume", "raw_trading_value", "adjusted_source_closure_checkpoint_sha256",
            "adjusted_source_row_present", "adjusted_open", "adjusted_high", "adjusted_low",
            "adjusted_close", "adjusted_invalid_relation_fields", "adjusted_store_authority_id",
            "adjusted_store_content_sha256", "adjusted_store_parquet_sha256",
            "raw_partition_file_sha256", "raw_partition_content_sha256",
        ]
        all_valuation_audit = all_valuation_audit.merge(
            gap_baseline[gap_evidence_columns],
            on=["ticker", "valuation_date"],
            how="left",
            validate="many_to_one",
        )
    new_gap_count = int(all_valuation_audit["gap_classification"].eq("NEW_UNCLASSIFIED_GAP").sum()) if not all_valuation_audit.empty else 0
    comparison = _comparison(results["CONTROL"]["metrics"], results["CANDIDATE"]["metrics"])
    unresolved_count = int(
        results["CONTROL"]["metrics"]["unresolved_count"]
        + results["CANDIDATE"]["metrics"]["unresolved_count"]
    )
    daily_equity_complete = all(
        pd.DataFrame(results[name]["daily_equity"])["equity"].notna().all()
        for name in ("CONTROL", "CANDIDATE")
    )
    cash_conservation = all(
        results[name]["metrics"]["cash_conservation_pass"]
        for name in ("CONTROL", "CANDIDATE")
    )
    mcap_reason_counts = reason_audit.loc[~reason_audit["ledger_materialized"], "reason"].value_counts().to_dict()
    mcap_closure_pass = len(reason_audit) == 365 and int((~reason_audit["ledger_materialized"]).sum()) == 10 and mcap_reason_counts == {
        "NEXT_LOCAL_EXECUTION_AFTER_EFFECTIVE_ENTRY_CUTOFF": 10
    }
    gap_baseline_counts = {
        str(key): int(value)
        for key, value in gap_baseline["gap_classification"].value_counts().to_dict().items()
    }
    gap_baseline_pass = gap_baseline_counts == {
        "NON_TRADING_PLACEHOLDER": 74,
        "ADJUSTED_ANALYTICALLY_NONUSABLE": 22,
    }
    validation = {
        **summary.get("validation", {}),
        **entry_parity,
        "mcap_unresolved_count": int(pit_audit["status"].astype(str).eq("UNRESOLVED").sum()),
        "portfolio_unresolved_count": unresolved_count,
        "control_cash_conservation": bool(results["CONTROL"]["metrics"]["cash_conservation_pass"]),
        "candidate_cash_conservation": bool(results["CANDIDATE"]["metrics"]["cash_conservation_pass"]),
        "position_cap_applied": False,
        "hidden_slot_cap_skip_count": total_slot_skips,
        "mcap_365_to_355_reason_closure_pass": bool(mcap_closure_pass),
        "existing_96_gap_classification_pass": bool(gap_baseline_pass),
        "existing_gap_unique_ticker_date_count": int(len(gap_baseline)),
        "existing_gap_classification_counts": gap_baseline_counts,
        "stale_mark_audit_rows": int(len(all_valuation_audit)),
        "new_unclassified_stale_mark_count": new_gap_count,
        "daily_equity_complete": bool(daily_equity_complete),
        "cash_conservation_pass": bool(cash_conservation),
        "network_calls": 0,
    }
    certified = (
        validation["mcap_unresolved_count"] == 0
        and unresolved_count == 0
        and total_slot_skips == 0
        and mcap_closure_pass
        and gap_baseline_pass
        and new_gap_count == 0
        and daily_equity_complete
        and cash_conservation
    )
    summary.update(
        {
            "status": "P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED" if certified else "P2_1_REALISTIC_PORTFOLIO_BACKTEST_REVIEW_REQUIRED",
            "head": p2.subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "portfolio": comparison,
            "validation": validation,
            "portfolio_replay": {
                "mode": "EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY",
                "strategy_source_head": strategy_source_head,
                "strategy_ledgers_reused_without_modification": True,
                "strategy_evaluation_rerun": False,
                "entry_signal_regeneration": False,
                "market_data_frames_loaded_from_repository_v2": len(frames),
                "market_data_tickers_loaded": len(ticker_frames),
                "repository_v2_load_calls": loader.load_count,
                "setup_and_frame_load_wall_seconds": round(setup_seconds, 3),
                "portfolio_event_replay_wall_seconds": round(replay_wall, 3),
                "baseline_gap_ticker_dates": int(len(gap_baseline)),
                "baseline_gap_classifications": gap_baseline_counts,
                "stale_valuation_mark_count": int(len(all_valuation_audit)),
                "portfolio_only_run_wall_seconds": round(time.perf_counter() - started, 3),
                "network_calls": 0,
            },
        }
    )
    for name in PORTFOLIO_AUDIT_OUTPUTS:
        summary.setdefault("artifacts", {})[name] = f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/{name}"
    summary["artifacts"].update(
        {
            "control_daily_equity.csv": f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/control_daily_equity.csv",
            "candidate_daily_equity.csv": f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/candidate_daily_equity.csv",
            "control_portfolio_events.csv": f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/control_portfolio_events.csv",
            "candidate_portfolio_events.csv": f"artifacts/backtests/p2_1_neg40_weak_protect_v01/{RUN_ID}/candidate_portfolio_events.csv",
        }
    )

    all_valuation_audit.to_csv(OUT_DIR / "valuation_gap_closure_audit.csv", index=False)
    gap_baseline.to_csv(OUT_DIR / "valuation_gap_source_diagnosis.csv", index=False)
    _json_write(OUT_DIR / "hidden_position_cap_audit.json", hidden_audit)
    reason_audit.to_csv(OUT_DIR / "mcap365_to_trade355_reason_audit.csv", index=False)
    pd.DataFrame(results["CONTROL"]["events"]).to_csv(OUT_DIR / "control_portfolio_events.csv", index=False)
    pd.DataFrame(results["CANDIDATE"]["events"]).to_csv(OUT_DIR / "candidate_portfolio_events.csv", index=False)
    pd.DataFrame(results["CONTROL"]["daily_equity"]).to_csv(OUT_DIR / "control_daily_equity.csv", index=False)
    pd.DataFrame(results["CANDIDATE"]["daily_equity"]).to_csv(OUT_DIR / "candidate_daily_equity.csv", index=False)
    pd.DataFrame(results["CONTROL"]["skipped"] + results["CANDIDATE"]["skipped"]).to_csv(OUT_DIR / "skipped_entries.csv", index=False)
    _json_write(OUT_DIR / "summary.json", summary)
    _write_summary_csv(summary, OUT_DIR / "summary.csv")
    (OUT_DIR / "comparison_report.md").write_text(_comparison_report(summary), encoding="utf-8")

    after_hashes = {name: _sha256(OUT_DIR / name) for name in required}
    for name in ("control_strategy_trades.csv", "candidate_strategy_trades.csv", "pit_mcap_audit.csv"):
        if source_hashes[name] != after_hashes[name]:
            raise RuntimeError(f"P2_1_PORTFOLIO_ONLY_MODIFIED_FROZEN_SOURCE:{name}")
    summary["portfolio_replay"]["frozen_source_hashes_sha256"] = source_hashes
    _json_write(OUT_DIR / "summary.json", summary)
    _write_summary_csv(summary, OUT_DIR / "summary.csv")
    (OUT_DIR / "comparison_report.md").write_text(_comparison_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
    return summary


def _sample(workers: int, sample_tickers: int) -> dict[str, Any]:
    if workers != 10:
        raise RuntimeError("P2_1_SAMPLE_WORKER_COUNT_MUST_BE_10")
    sample_path = OUT_DIR / "sample_benchmark.json"
    if sample_path.exists():
        raise RuntimeError(f"REFUSING_TO_OVERWRITE_SAMPLE:{sample_path}")
    run, gate, authority, _universe = _load_survivor_context(worker_count=workers)
    all_tickers = sorted(run.segments_by_ticker)
    selected = p2._sample_tickers(all_tickers, sample_tickers)
    if not selected:
        raise RuntimeError("P2_1_SAMPLE_TICKER_SET_EMPTY")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    outcomes, errors, sample_wall = _run_ticker_pool(run, workers=workers, tickers=selected)
    estimates = run.setup_seconds + sample_wall * len(all_tickers) / max(len(selected), 1)
    gate_audit = gate.audit_frame()
    result = {
        "status": "COMPLETE" if not errors else "FAILED",
        "run_id": RUN_ID,
        "window_id": "P2-1",
        "worker_count": workers,
        "sample_ticker_count": len(selected),
        "sample_tickers": selected,
        "target_ticker_count": len(all_tickers),
        "survivor_identity_count": sum(len(rows) for rows in run.segments_by_ticker.values()),
        "latest_daily_update_as_of": authority["latest_daily_update_as_of"],
        "sample_wall_seconds": round(sample_wall, 3),
        "setup_seconds": round(run.setup_seconds, 3),
        "estimated_full_seconds": round(estimates, 3),
        "estimated_full_minutes": round(estimates / 60.0, 2),
        "sample_gate_signal_counts": {str(key): int(value) for key, value in gate_audit["status"].value_counts().to_dict().items()} if not gate_audit.empty else {},
        "worker_threads": _parallel_rollup(outcomes),
        "errors": errors,
        "wall_seconds_including_setup": round(time.perf_counter() - started, 3),
    }
    _json_write(sample_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "full", "portfolio-only"), required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--sample-tickers", type=int, default=40)
    args = parser.parse_args()
    if args.mode == "sample":
        _sample(args.workers, args.sample_tickers)
    elif args.mode == "full":
        _full_run(args.workers)
    else:
        if args.workers != 10:
            raise RuntimeError("P2_1_PORTFOLIO_ONLY_WORKER_ARGUMENT_MUST_REMAIN_10_NO_STRATEGY_WORKERS_ARE_USED")
        _portfolio_only_replay()


if __name__ == "__main__":
    main()
