#!/usr/bin/env python3
"""Local-only FastCore V02 versus Julia V00 weekly portfolio comparison.

This runner creates a fresh Pattern A/FastCore signal authority from the
repository's frozen PIT identity authority and the existing Pattern A FAST
evaluator.  The experiment-specific investability override is market-cap-only
(``>= 100B KRW``); it does not change production investability defaults.

The existing corrected lifecycle evaluator is reused for both strategies.  The
only strategy delta is ``loss_guard_enabled``.  A separate weekly portfolio
event engine owns cash, active-position, ranking, and same-open semantics.
No network-backed source is imported or called.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import socket
import sys
from typing import Any, Callable, Iterator, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fastcore_control import (
    _authority_intervals,
    frozen_candidate_id,
)
from trend_scanner.backtest import fastcore_fundamentals_simple_v01 as lifecycle_engine
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    clip_to_identity_lifecycle,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver
from trend_scanner.validation.julia_strategy_v00 import HistoricalMarketCapRegistry
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast


OUT_DIR = ROOT / "artifacts/backtests/fastcore_vs_julia_portfolio_v01"
EFFECTIVE_AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
MARKET_CAP_MANIFEST_PATH = ROOT / "artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv"

START_DATE = pd.Timestamp("2021-04-01")
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
SUPPORT_END = pd.Timestamp("2026-08-21")
INITIAL_CAPITAL = 200_000_000.0
POSITION_CAP = 5_000_000.0
MARKET_CAP_THRESHOLD = 100_000_000_000.0

FASTCORE_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
JULIA_ID = "JULIA_STRATEGY_V00"


class NetworkRequestBlocked(RuntimeError):
    """Raised if the local-only run accidentally opens a socket."""


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline comparison guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline comparison guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _week_start(value: Any) -> pd.Timestamp:
    date = pd.Timestamp(value).normalize()
    return date - pd.to_timedelta(int(date.weekday()), unit="D")


def _identity_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("ticker") or "").zfill(6), str(row.get("isu_cd") or ""), str(row.get("market") or ""))


def _lookup_exact(daily: pd.DataFrame, date: Any, column: str) -> float:
    timestamp = pd.Timestamp(date).normalize()
    if timestamp not in daily.index:
        raise RuntimeError(f"missing {column} price for {timestamp.date()}")
    return float(daily.loc[timestamp, column])


def _price_asof(daily_by_ticker: Mapping[str, pd.DataFrame], ticker: str, date: Any, column: str) -> float:
    daily = daily_by_ticker[ticker]
    timestamp = pd.Timestamp(date).normalize()
    rows = daily.loc[daily.index <= timestamp, column]
    if rows.empty:
        raise RuntimeError(f"missing as-of {column} price for {ticker} at {timestamp.date()}")
    return float(rows.iloc[-1])


def evaluate_mcap_only_entry_filter(
    panel: pd.DataFrame | None,
    signal_date: pd.Timestamp,
    *,
    market_cap_threshold: float = MARKET_CAP_THRESHOLD,
    avg_trading_value_threshold: float | None = None,
    close_threshold: float | None = None,
) -> dict[str, Any]:
    """Comparison-only PIT gate: exact-date market cap, no other filter.

    The extra threshold parameters are accepted for drop-in compatibility
    with the existing lifecycle evaluator and are deliberately ignored.
    """
    del market_cap_threshold, avg_trading_value_threshold, close_threshold
    result: dict[str, Any] = {
        "entry_market_cap": None,
        "entry_avg_trading_value_20d": None,
        "entry_signal_close": None,
        "entry_filter_raw_date": None,
        "entry_market_cap_pass": False,
        "entry_trading_value_pass": True,
        "entry_close_pass": True,
        "entry_filter_pass": False,
        "liquidity_filter_applied": False,
        "price_filter_applied": False,
    }
    if panel is None or panel.empty:
        return result
    date = pd.Timestamp(signal_date).normalize()
    if date not in panel.index or panel.index.duplicated().any():
        return result
    row = panel.loc[date]
    if isinstance(row, pd.DataFrame):
        return result
    market_cap = pd.to_numeric(row.get("market_cap"), errors="coerce")
    if pd.isna(market_cap):
        return result
    result.update({
        "entry_market_cap": float(market_cap),
        "entry_filter_raw_date": date.strftime("%Y-%m-%d"),
        "entry_market_cap_pass": bool(float(market_cap) >= MARKET_CAP_THRESHOLD),
    })
    result["entry_filter_pass"] = bool(result["entry_market_cap_pass"])
    return result


@contextmanager
def comparison_filter_override() -> Iterator[None]:
    """Temporarily replace only the lifecycle module's entry filter lookup."""
    original = lifecycle_engine.evaluate_entry_filter
    lifecycle_engine.evaluate_entry_filter = evaluate_mcap_only_entry_filter  # type: ignore[assignment]
    try:
        yield
    finally:
        lifecycle_engine.evaluate_entry_filter = original  # type: ignore[assignment]


def _name_map() -> dict[str, str]:
    frame = InstrumentMetadataResolver.load_master_dataframe(ROOT)
    if frame.empty or "ticker" not in frame.columns:
        return {}
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    frame = frame.drop_duplicates("ticker", keep="last")
    return {
        str(row.ticker): str(row.name) if str(row.name) not in {"", "nan", "None"} else str(row.ticker)
        for row in frame.itertuples(index=False)
    }


def _load_authority() -> tuple[Any, dict[tuple[str, str, str], list[tuple[str, str]]], list[dict[str, Any]]]:
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority)
    tasks: list[dict[str, Any]] = []
    for (ticker, isu_cd, market), ranges in sorted(intervals.items()):
        for effective_from, effective_to in ranges:
            if pd.Timestamp(effective_to) < START_DATE or pd.Timestamp(effective_from) > SUPPORT_END:
                continue
            tasks.append({
                "ticker": ticker,
                "isu_cd": isu_cd,
                "market": market,
                "effective_from": effective_from,
                "effective_to": effective_to,
            })
    return authority, intervals, tasks


def _valid_fast_signal(result: Mapping[str, Any]) -> bool:
    return bool(
        result.get("fast_machine_stage") == "TRIGGER"
        and result.get("fast_machine_stage_status") == "READY"
        and result.get("fast_monthly_permission_state") == "PERMITTED_REGIME"
        and result.get("fast_daily_risk_state") in {"NORMAL", "ELEVATED"}
        and result.get("fast_score_status") in {"READY", "PARTIAL"}
        and str(result.get("pattern_a_stage") or "").upper() in {"TRANSITION", "EARLY_TREND"}
    )


def _mcap_exact(registry: HistoricalMarketCapRegistry, ticker: str, date: pd.Timestamp) -> tuple[float | None, dict[str, Any] | None]:
    return registry.get_market_cap_at_reference(str(ticker).zfill(6), date.strftime("%Y-%m-%d"))


_SCAN_REGISTRY: HistoricalMarketCapRegistry | None = None
_SCAN_SCORE_CONTRACT: dict[str, Any] = {}
_SCAN_STAGE_CONTRACT: dict[str, Any] = {}
_SCAN_NAMES: dict[str, str] = {}
_SCAN_INTERVALS: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
_SCAN_AVAILABLE_MCAP_DATES: set[pd.Timestamp] = set()
_SCAN_LOADER: RepositoryV2DailyLoader | None = None


def _scan_ticker_group(item: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Scan one ticker's identity groups in a forked local worker."""
    ticker, tasks = item
    registry = _SCAN_REGISTRY
    loader = _SCAN_LOADER
    if registry is None or loader is None:
        raise RuntimeError("BLOCKED_SCAN_WORKER_NOT_INITIALIZED")
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        return {"rows": [], "audit": [], "identity_count": 0, "load_count": 1}
    name = _SCAN_NAMES.get(ticker, ticker)
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    identity_count = 0
    for task in tasks:
        lifecycle = IdentityLifecycle(
            ticker=ticker,
            isu_cd=str(task["isu_cd"]),
            market=str(task["market"]),
            effective_from=pd.Timestamp(task["effective_from"]),
            effective_to=min(pd.Timestamp(task["effective_to"]), SUPPORT_END),
        )
        clipped = clip_to_identity_lifecycle(daily, lifecycle)
        if clipped is None or clipped.empty or len(clipped) < 60:
            continue
        context = build_precomputed_ticker_context(ticker, name, clipped)
        clipped_dates = set(pd.DatetimeIndex(clipped.index).normalize())
        valid_weeks = [
            pd.Timestamp(value).normalize()
            for value in context.weekly_up_to(SUPPORT_END).index
            if pd.Timestamp(value).normalize() in clipped_dates
            and START_DATE <= pd.Timestamp(value).normalize() <= SIGNAL_CUTOFF
            and pd.Timestamp(value).normalize() in _SCAN_AVAILABLE_MCAP_DATES
        ]
        identity_count += 1
        for week in valid_weeks:
            try:
                result = evaluate_pattern_a_fast(
                    ticker, name, clipped, week, _SCAN_SCORE_CONTRACT, _SCAN_STAGE_CONTRACT, context=context,
                )
            except Exception:
                continue
            if not _valid_fast_signal(result):
                continue
            mcap, metadata = _mcap_exact(registry, ticker, week)
            mcap_status = "PASS"
            if mcap is None:
                mcap_status = "REJECT_MCAP_UNAVAILABLE"
            elif float(mcap) < MARKET_CAP_THRESHOLD:
                mcap_status = "REJECT_MCAP_BELOW_100B"
            candidate_id = frozen_candidate_id(ticker, lifecycle.isu_cd, lifecycle.market, week)
            audit_rows.append({
                "audit_type": "FRESH_FAST_SIGNAL",
                "candidate_id": candidate_id,
                "ticker": ticker,
                "isu_cd": lifecycle.isu_cd,
                "market": lifecycle.market,
                "name": name,
                "signal_date": week.strftime("%Y-%m-%d"),
                "signal_information_date": week.strftime("%Y-%m-%d"),
                "fast_score": result.get("fast_score"),
                "fast_score_status": result.get("fast_score_status"),
                "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
                "fast_machine_stage": result.get("fast_machine_stage"),
                "mcap": mcap,
                "mcap_threshold": MARKET_CAP_THRESHOLD,
                "mcap_status": mcap_status,
                "mcap_source_file": metadata.get("source_file") if metadata else None,
                "liquidity_filter_applied": False,
                "price_filter_applied": False,
                "fresh_signal_status": "FRESH_SIGNAL_MCAP_PASS" if mcap_status == "PASS" else mcap_status,
            })
            if mcap_status != "PASS":
                continue
            fast_score = result.get("fast_score")
            fast_score_value = None if fast_score is None or pd.isna(fast_score) else float(fast_score)
            rows.append({
                "signal_id": candidate_id,
                "candidate_id": candidate_id,
                "ticker": ticker,
                "isu_cd": lifecycle.isu_cd,
                "market": lifecycle.market,
                "name": name,
                "signal_date": week.strftime("%Y-%m-%d"),
                "signal_information_date": week.strftime("%Y-%m-%d"),
                "fast_score": fast_score_value,
                "fast_score_status": result.get("fast_score_status"),
                "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
                "fast_machine_stage": result.get("fast_machine_stage"),
                "monthly_permission_state": result.get("fast_monthly_permission_state"),
                "daily_risk_state": result.get("fast_daily_risk_state"),
                "market_cap": float(mcap),
                "market_cap_source_file": metadata.get("source_file") if metadata else None,
                "entry_signal_information_date": week.strftime("%Y-%m-%d"),
                "entry_filter_raw_date": week.strftime("%Y-%m-%d"),
                "identity_effective_from": lifecycle.effective_from.strftime("%Y-%m-%d"),
                "identity_effective_to": lifecycle.effective_to.strftime("%Y-%m-%d"),
                "liquidity_filter_applied": False,
                "price_filter_applied": False,
            })
        del clipped, context
    return {"rows": rows, "audit": audit_rows, "identity_count": identity_count, "load_count": 1}


def load_fresh_signal_authority() -> tuple[pd.DataFrame, dict[str, Any], Callable[[str, Mapping[str, Any]], dict[str, Any]]]:
    """Build fresh signals from the frozen evaluator and PIT mcap authority."""
    authority, intervals, tasks = _load_authority()
    registry = HistoricalMarketCapRegistry.load_from_repository(ROOT, enforce_integrity=True)
    available_mcap_dates = {pd.Timestamp(value).normalize() for value in registry.available_dates}
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    names = _name_map()
    repository = build_repository_v2(ROOT, end=SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT_END)
    global _SCAN_REGISTRY, _SCAN_SCORE_CONTRACT, _SCAN_STAGE_CONTRACT, _SCAN_NAMES
    global _SCAN_INTERVALS, _SCAN_AVAILABLE_MCAP_DATES, _SCAN_LOADER
    _SCAN_REGISTRY = registry
    _SCAN_SCORE_CONTRACT = score_contract
    _SCAN_STAGE_CONTRACT = stage_contract
    _SCAN_NAMES = names
    _SCAN_INTERVALS = intervals
    _SCAN_AVAILABLE_MCAP_DATES = available_mcap_dates
    _SCAN_LOADER = loader

    tasks_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        tasks_by_ticker[str(task["ticker"]).zfill(6)].append(task)
    groups = sorted(tasks_by_ticker.items())
    rows: list[dict[str, Any]] = []
    fast_signal_audit: list[dict[str, Any]] = []
    identity_count = 0
    worker_load_count = 0
    worker_count = min(4, max(1, len(groups)))
    try:
        multiprocessing_context = mp.get_context("fork")
        with ProcessPoolExecutor(max_workers=worker_count, mp_context=multiprocessing_context) as pool:
            futures = [pool.submit(_scan_ticker_group, group) for group in groups]
            for completed, future in enumerate(as_completed(futures), 1):
                result = future.result()
                rows.extend(result["rows"])
                fast_signal_audit.extend(result["audit"])
                identity_count += int(result["identity_count"])
                worker_load_count += int(result["load_count"])
                if completed % 100 == 0 or completed == len(futures):
                    print(f"fresh signal scan: {completed}/{len(futures)} ticker groups", flush=True)
    finally:
        _SCAN_LOADER = None

    signals = pd.DataFrame(rows)
    if not signals.empty:
        signals = signals.drop_duplicates("signal_id", keep="first")
        signals = signals.sort_values(["signal_date", "signal_id"], kind="mergesort").reset_index(drop=True)
    else:
        signals = pd.DataFrame(columns=[
            "signal_id", "candidate_id", "ticker", "isu_cd", "market", "name", "signal_date",
            "signal_information_date", "fast_score", "fast_score_status", "pattern_a_stage",
            "fast_machine_stage", "monthly_permission_state", "daily_risk_state", "market_cap",
            "market_cap_source_file", "entry_signal_information_date", "entry_filter_raw_date",
            "identity_effective_from", "identity_effective_to", "liquidity_filter_applied", "price_filter_applied",
        ])

    # Workers intentionally return only compact signal rows.  Load daily
    # prices for the surviving signal tickers once in the parent for the
    # portfolio calendar and lifecycle factory.
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in sorted(signals["ticker"].astype(str).str.zfill(6).unique() if not signals.empty else []):
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"BLOCKED_DATA_GAP: {ticker}")
        daily_by_ticker[ticker] = daily

    task_map = {
        (str(item["ticker"]), str(item["isu_cd"]), str(item["market"]), str(item["effective_from"]), str(item["effective_to"])): item
        for item in tasks
    }
    record_cache: dict[tuple[str, str], dict[str, Any]] = {}
    context_cache: dict[tuple[str, str, str, str, str], Any] = {}

    def strategy_record_for(strategy_id: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
        cache_key = (strategy_id, str(candidate["signal_id"]))
        if cache_key in record_cache:
            return record_cache[cache_key]
        identity = _identity_key(candidate)
        task_key = (
            identity[0], identity[1], identity[2],
            str(candidate["identity_effective_from"]), str(candidate["identity_effective_to"]),
        )
        task = task_map.get(task_key)
        if task is None:
            raise RuntimeError(f"BLOCKED_SIGNAL_AUTHORITY_TASK_GAP: {task_key}")
        daily = daily_by_ticker[identity[0]]
        lifecycle = IdentityLifecycle(
            ticker=identity[0], isu_cd=identity[1], market=identity[2],
            effective_from=pd.Timestamp(task["effective_from"]),
            effective_to=min(pd.Timestamp(task["effective_to"]), SUPPORT_END),
        )
        context = context_cache.get(task_key)
        if context is None:
            context = build_precomputed_ticker_context(
                identity[0], str(candidate.get("name") or identity[0]),
                clip_to_identity_lifecycle(daily, lifecycle),
            )
            context_cache[task_key] = context
        signal_date = pd.Timestamp(candidate["signal_date"]).normalize()
        raw_panel = pd.DataFrame(
            {
                "market_cap": [float(candidate["market_cap"])],
                "close": [_price_asof(daily_by_ticker, identity[0], signal_date, "close")],
                "trading_value": [float("nan")],
                "avg_trading_value_20d": [float("nan")],
            },
            index=pd.DatetimeIndex([signal_date]),
        )
        candidate_id = str(candidate["signal_id"])

        def gate(_as_of: pd.Timestamp, values: dict[str, Any]) -> dict[str, Any]:
            signal = pd.Timestamp(values["signal_date"]).normalize()
            mcap, _meta = _mcap_exact(registry, identity[0], signal)
            return {
                "gate_pass": (
                    frozen_candidate_id(identity[0], identity[1], identity[2], signal) == candidate_id
                    and mcap is not None
                    and float(mcap) >= MARKET_CAP_THRESHOLD
                ),
                "gate_id": "FRESH_MCAP_ONLY_PIT_AUTHORITY",
                "market_cap": mcap,
                "liquidity_filter_applied": False,
                "price_filter_applied": False,
            }

        records = simulate_ticker_strategy_fundamentals_v01(
            strategy_id=strategy_id,
            ticker=identity[0],
            isu_cd=identity[1],
            name=str(candidate.get("name") or identity[0]),
            market=identity[2],
            daily=daily,
            raw_panel=raw_panel,
            score_contract=score_contract,
            stage_contract=stage_contract,
            loss_guard_enabled=(strategy_id == FASTCORE_ID),
            backtest_end=SUPPORT_END,
            entry_eligible_from=START_DATE,
            allowed_signal_dates={signal_date},
            snapshot_context=context,
            identity_lifecycle=lifecycle,
            pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                intervals, ticker_value, isu_value, market_value, value,
            ),
            entry_gate=gate,
            fundamental_exit_callback=None,
        )
        if len(records) != 1:
            raise RuntimeError(f"BLOCKED_SIGNAL_EXIT_AUTHORITY_GAP: {candidate_id}: {len(records)}")
        record = records[0].to_dict()
        if str(record["entry_signal_date"]) != signal_date.strftime("%Y-%m-%d"):
            raise RuntimeError(f"BLOCKED_SIGNAL_DATE_DRIFT: {candidate_id}")
        record["comparison_market_cap_threshold"] = MARKET_CAP_THRESHOLD
        record["liquidity_filter_applied"] = False
        record["price_filter_applied"] = False
        record_cache[cache_key] = record
        return record

    meta = {
        "work_id": "FASTCORE_VS_JULIA_200M_PORTFOLIO_COMPARISON_V01",
        "fresh_signal_count": int(len(signals)),
        "fresh_signal_ticker_count": int(signals["ticker"].nunique()) if not signals.empty else 0,
        "fast_signal_candidates_before_mcap_gate": int(len(fast_signal_audit)),
        "mcap_pass_count": int(sum(row["mcap_status"] == "PASS" for row in fast_signal_audit)),
        "mcap_below_threshold_count": int(sum(row["mcap_status"] == "REJECT_MCAP_BELOW_100B" for row in fast_signal_audit)),
        "mcap_unavailable_count": int(sum(row["mcap_status"] == "REJECT_MCAP_UNAVAILABLE" for row in fast_signal_audit)),
        "identity_intervals_processed": identity_count,
        "authority_interval_count": len(tasks),
        "repository_v2_local_loads": int(worker_load_count + len(daily_by_ticker)),
        "market_cap_manifest_sha256": _sha256(MARKET_CAP_MANIFEST_PATH),
        "market_cap_available_dates": sorted(registry.available_dates),
        "mcap_authority_missing_week_evaluation": "FAIL_CLOSED_AND_NOT_EVALUATED",
        "daily_by_ticker": daily_by_ticker,
        "strategy_record_factory": strategy_record_for,
        "fresh_signal_audit": fast_signal_audit,
        "authority": authority,
    }
    return signals, meta, strategy_record_for


def _build_calendar(daily_by_ticker: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    dates: set[pd.Timestamp] = {START_DATE, SUPPORT_END}
    for daily in daily_by_ticker.values():
        dates.update(
            pd.Timestamp(value).normalize()
            for value in daily.index
            if START_DATE <= pd.Timestamp(value).normalize() <= SUPPORT_END
        )
    ordered = sorted(dates)
    first_by_week: dict[pd.Timestamp, pd.Timestamp] = {}
    last_by_week: dict[pd.Timestamp, pd.Timestamp] = {}
    for date in ordered:
        week = _week_start(date)
        first_by_week.setdefault(week, date)
        last_by_week[week] = date
    next_week: dict[pd.Timestamp, pd.Timestamp] = {}
    ordered_weeks = sorted(first_by_week)
    for index, week in enumerate(ordered_weeks[:-1]):
        next_week[week] = first_by_week[ordered_weeks[index + 1]]
    return {"dates": ordered, "first_by_week": first_by_week, "last_by_week": last_by_week, "next_week": next_week, "batch_dates": sorted(first_by_week.values())}


def _next_week_open(signal_date: Any, calendar: Mapping[str, Any]) -> pd.Timestamp | None:
    if signal_date is None or pd.isna(signal_date):
        return None
    return calendar["next_week"].get(_week_start(signal_date))


def _score_sort_value(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return float("inf")
        return -float(value)
    except (TypeError, ValueError):
        return float("inf")


def _dedupe_and_rank_candidates(signals: pd.DataFrame, calendar: Mapping[str, Any]) -> tuple[dict[pd.Timestamp, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_batch: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    pre_audit: list[dict[str, Any]] = []
    for row in signals.to_dict(orient="records"):
        batch = _next_week_open(row["signal_date"], calendar)
        if batch is None or batch > SUPPORT_END:
            pre_audit.append({**row, "scheduled_execution_date": _iso(batch), "ranking": None, "execution_result": "SKIP_NO_EXECUTION_SUPPORT"})
            continue
        item = dict(row)
        item["scheduled_execution_date"] = batch
        by_batch[batch].append(item)
    selected: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for batch, rows in by_batch.items():
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_identity_key(row)].append(row)
        winners: list[dict[str, Any]] = []
        for identity, values in grouped.items():
            values.sort(key=lambda row: (pd.Timestamp(row["signal_date"]), str(row["signal_id"])), reverse=True)
            winner = values[0]
            winners.append(winner)
            for duplicate in values[1:]:
                pre_audit.append({**duplicate, "scheduled_execution_date": batch, "ranking": None, "execution_result": "SKIP_DUPLICATE_WEEKLY_CANDIDATE"})
        winners.sort(key=lambda row: (_score_sort_value(row.get("fast_score")), -pd.Timestamp(row["signal_date"]).value, str(row["ticker"])))
        for ranking, row in enumerate(winners, 1):
            row["ranking"] = ranking
        selected[batch].extend(winners)
    return dict(selected), pre_audit


def _portfolio_audit_row(row: Mapping[str, Any], strategy_id: str, result: str, ranking: Any = None) -> dict[str, Any]:
    return {
        "audit_type": "PORTFOLIO_EXECUTION",
        "strategy_id": strategy_id,
        "signal_id": row.get("signal_id"),
        "ticker": row.get("ticker"),
        "isu_cd": row.get("isu_cd"),
        "market": row.get("market"),
        "name": row.get("name"),
        "signal_date": _iso(row.get("signal_date")),
        "scheduled_execution_date": _iso(row.get("scheduled_execution_date")),
        "fast_score": row.get("fast_score"),
        "ranking": ranking if ranking is not None else row.get("ranking"),
        "execution_result": result,
    }


@dataclass
class Position:
    signal_id: str
    ticker: str
    isu_cd: str
    market: str
    name: str
    entry_signal_date: str
    entry_execution_date: str
    entry_open: float
    shares: int
    cost_basis: float
    full_exit_signal_date: str | None
    full_exit_execution_date: str | None
    full_exit_type: str | None


def _event_row(*, strategy_id: str, date: pd.Timestamp, event_type: str, ticker: str, name: str, signal_date: str | None, signal_type: str | None, open_price: float, shares_before: int, shares_delta: int, shares_after: int, cash_before: float, cash_delta: float, cash_after: float, position_cost_basis: float | None, realized_pnl: float | None, realized_return: float | None, portfolio_equity_after_execution: float) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "execution_date": date.strftime("%Y-%m-%d"),
        "event_type": event_type,
        "ticker": ticker,
        "name": name,
        "signal_date": signal_date,
        "signal_type": signal_type,
        "open_price": round(open_price, 6),
        "shares_before": shares_before,
        "shares_delta": shares_delta,
        "shares_after": shares_after,
        "cash_before": round(cash_before, 6),
        "cash_delta": round(cash_delta, 6),
        "cash_after": round(cash_after, 6),
        "position_cost_basis": position_cost_basis,
        "realized_pnl": None if realized_pnl is None else round(realized_pnl, 6),
        "realized_return": None if realized_return is None else round(realized_return, 6),
        "portfolio_equity_after_execution": round(portfolio_equity_after_execution, 6),
    }


def _portfolio_equity_at_open(cash: float, positions: Mapping[tuple[str, str, str], Position], daily_by_ticker: Mapping[str, pd.DataFrame], date: pd.Timestamp) -> float:
    return cash + sum(position.shares * _price_asof(daily_by_ticker, position.ticker, date, "open") for position in positions.values())


def _daily_curve(calendar: Mapping[str, Any], cash_by_date: Mapping[pd.Timestamp, float], positions_by_date: Mapping[pd.Timestamp, Mapping[tuple[str, str, str], Position]], daily_by_ticker: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for date in calendar["dates"]:
        positions = positions_by_date.get(date, {})
        cash = float(cash_by_date.get(date, INITIAL_CAPITAL))
        invested = sum(position.shares * _price_asof(daily_by_ticker, position.ticker, date, "close") for position in positions.values())
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "cash": round(cash, 6),
            "invested_market_value": round(invested, 6),
            "equity": round(cash + invested, 6),
            "position_count": len(positions),
        })
    curve = pd.DataFrame(rows)
    curve["cash_ratio"] = curve["cash"] / curve["equity"]
    curve["invested_ratio"] = curve["invested_market_value"] / curve["equity"]
    curve["high_water_mark"] = curve["equity"].cummax()
    curve["drawdown_pct"] = (curve["equity"] / curve["high_water_mark"] - 1.0) * 100.0
    return curve


def _risk_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    trough_index = int(curve["drawdown_pct"].idxmin())
    trough = curve.iloc[trough_index]
    prior = curve.iloc[: trough_index + 1]
    peak_index = int(prior["equity"].idxmax())
    peak_equity = float(prior.iloc[peak_index]["equity"])
    recovery = curve.iloc[trough_index + 1 :]
    recovered = recovery[recovery["equity"] >= peak_equity]
    recovery_date = str(recovered.iloc[0]["date"]) if not recovered.empty else None
    return {
        "mdd_pct": round(abs(float(trough["drawdown_pct"])), 6),
        "mdd_peak_date": str(prior.iloc[peak_index]["date"]),
        "mdd_trough_date": str(trough["date"]),
        "mdd_recovery_date": recovery_date,
        "max_drawdown_duration_trading_days": int(trough_index - peak_index),
    }


def _annual_returns(curve: pd.DataFrame) -> dict[str, float | None]:
    frame = curve.copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    result: dict[str, float | None] = {}
    previous = INITIAL_CAPITAL
    for year in range(2021, 2027):
        group = frame[frame["year"].eq(year)]
        key = str(year) if year < 2026 else "2026_YTD"
        if group.empty:
            result[key] = None
            continue
        ending = float(group.iloc[-1]["equity"])
        result[key] = round((ending / previous - 1.0) * 100.0, 6)
        previous = ending
    return result


def _summary(strategy_id: str, signals: pd.DataFrame, curve: pd.DataFrame, events: pd.DataFrame, audits: pd.DataFrame) -> dict[str, Any]:
    final_equity = float(curve.iloc[-1]["equity"])
    elapsed_days = max(1, (pd.Timestamp(curve.iloc[-1]["date"]) - pd.Timestamp(curve.iloc[0]["date"])).days)
    total_return = final_equity / INITIAL_CAPITAL - 1.0
    cagr = (final_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0
    event_type = events.get("event_type", pd.Series(dtype=str))
    entries = events[event_type.eq("ENTRY")] if not events.empty else events
    exits = events[event_type.eq("FULL_EXIT")] if not events.empty else events
    result_counts = audits.get("execution_result", pd.Series(dtype=str))
    transaction_value = float(events["cash_delta"].abs().sum()) if not events.empty else 0.0
    return {
        "strategy_id": strategy_id,
        "initial_equity": round(INITIAL_CAPITAL, 6),
        "final_equity": round(final_equity, 6),
        "final_cash": round(float(curve.iloc[-1]["cash"]), 6),
        "final_invested_market_value": round(float(curve.iloc[-1]["invested_market_value"]), 6),
        "open_positions_at_final_valuation": int(curve.iloc[-1]["position_count"]),
        "net_profit": round(final_equity - INITIAL_CAPITAL, 6),
        "total_return_pct": round(total_return * 100.0, 6),
        "CAGR_pct": round(cagr * 100.0, 6),
        **_risk_metrics(curve),
        "annual_returns_pct": _annual_returns(curve),
        "fresh_signal_count": int(len(signals)),
        "executed_entry_count": int(len(entries)),
        "full_exit_count": int(len(exits)),
        "cash_blocked_count": int(result_counts.eq("SKIP_CASH_BLOCKED").sum()),
        "active_position_skip_count": int(result_counts.eq("SKIP_ACTIVE_POSITION").sum()),
        "same_open_reentry_skip_count": int(result_counts.eq("SKIP_SAME_OPEN_REENTRY").sum()),
        "missing_execution_price_count": int(result_counts.eq("SKIP_MISSING_EXECUTION_PRICE").sum()),
        "duplicate_weekly_candidate_skip_count": int(result_counts.eq("SKIP_DUPLICATE_WEEKLY_CANDIDATE").sum()),
        "max_concurrent_positions": int(curve["position_count"].max()),
        "average_concurrent_positions": round(float(curve["position_count"].mean()), 6),
        "median_concurrent_positions": round(float(curve["position_count"].median()), 6),
        "average_cash_ratio": round(float(curve["cash_ratio"].mean()), 6),
        "minimum_cash": round(float(curve["cash"].min()), 6),
        "maximum_invested_market_value": round(float(curve["invested_market_value"].max()), 6),
        "average_invested_market_value": round(float(curve["invested_market_value"].mean()), 6),
        "portfolio_turnover": round(transaction_value, 6),
        "portfolio_turnover_ratio": round(transaction_value / INITIAL_CAPITAL, 6),
        "execution_contract": {
            "initial_capital": INITIAL_CAPITAL,
            "per_lifecycle_position_cap": POSITION_CAP,
            "integer_shares": True,
            "leverage": False,
            "pyramiding": False,
            "commission": 0,
            "tax": 0,
            "slippage": 0,
            "signal_to_execution": "next calendar week first KRX trading session OPEN",
            "full_exits_before_entries": True,
            "same_open_reentry": False,
            "cash_block_no_carry": True,
        },
    }


def run_portfolio(signals: pd.DataFrame, calendar: Mapping[str, Any], daily_by_ticker: Mapping[str, pd.DataFrame], strategy_id: str, strategy_record_factory: Callable[[str, Mapping[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    selected, pre_audit = _dedupe_and_rank_candidates(signals, calendar)
    positions: dict[tuple[str, str, str], Position] = {}
    cash = INITIAL_CAPITAL
    events: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = [_portfolio_audit_row(row, strategy_id, row["execution_result"], row.get("ranking")) for row in pre_audit]
    positions_by_date: dict[pd.Timestamp, dict[tuple[str, str, str], Position]] = {}
    cash_by_date: dict[pd.Timestamp, float] = {}

    for batch in calendar["batch_dates"]:
        if batch < START_DATE or batch > SUPPORT_END:
            continue
        exited_identities: set[tuple[str, str, str]] = set()
        for identity, position in list(positions.items()):
            if position.full_exit_execution_date != batch.strftime("%Y-%m-%d"):
                continue
            try:
                price = _lookup_exact(daily_by_ticker[position.ticker], batch, "open")
            except RuntimeError:
                # The signal's mandated execution session is authoritative.  A
                # ticker-specific price gap must not be silently substituted
                # with a later session or a portfolio-level as-of price.  Keep
                # the position open under no-forced-liquidation semantics and
                # record the failed exit execution in the audit.
                audits.append(_portfolio_audit_row(
                    {
                        "signal_id": position.signal_id,
                        "ticker": position.ticker,
                        "isu_cd": position.isu_cd,
                        "market": position.market,
                        "name": position.name,
                        "signal_date": position.full_exit_signal_date,
                        "scheduled_execution_date": batch,
                        "fast_score": None,
                        "ranking": None,
                    },
                    strategy_id,
                    "SKIP_MISSING_EXECUTION_PRICE",
                ))
                continue
            cash_before = cash
            shares_before = position.shares
            proceeds = shares_before * price
            realized_pnl = shares_before * (price - position.cost_basis)
            realized_return = (price / position.cost_basis - 1.0) * 100.0
            cash += proceeds
            positions.pop(identity)
            exited_identities.add(identity)
            events.append(_event_row(
                strategy_id=strategy_id,
                date=batch,
                event_type="FULL_EXIT",
                ticker=position.ticker,
                name=position.name,
                signal_date=position.full_exit_signal_date,
                signal_type=position.full_exit_type,
                open_price=price,
                shares_before=shares_before,
                shares_delta=-shares_before,
                shares_after=0,
                cash_before=cash_before,
                cash_delta=proceeds,
                cash_after=cash,
                position_cost_basis=position.cost_basis,
                realized_pnl=realized_pnl,
                realized_return=realized_return,
                portfolio_equity_after_execution=0.0,
            ))

        for candidate in selected.get(batch, []):
            identity = _identity_key(candidate)
            result = "EXECUTED"
            if identity in exited_identities:
                result = "SKIP_SAME_OPEN_REENTRY"
            elif identity in positions:
                result = "SKIP_ACTIVE_POSITION"
            else:
                try:
                    price = _lookup_exact(daily_by_ticker[identity[0]], batch, "open")
                except RuntimeError:
                    result = "SKIP_MISSING_EXECUTION_PRICE"
                else:
                    shares = math.floor(min(POSITION_CAP, cash) / price)
                    if shares <= 0:
                        result = "SKIP_CASH_BLOCKED"
                    else:
                        cash_before = cash
                        cost = shares * price
                        cash -= cost
                        record = strategy_record_factory(strategy_id, candidate)
                        exit_signal = record.get("exit_signal_date")
                        exit_execution = _next_week_open(exit_signal, calendar) if exit_signal else None
                        if exit_execution is not None and exit_execution <= batch:
                            exit_execution = None
                        position = Position(
                            signal_id=str(candidate["signal_id"]),
                            ticker=identity[0],
                            isu_cd=identity[1],
                            market=identity[2],
                            name=str(candidate["name"]),
                            entry_signal_date=str(candidate["signal_date"]),
                            entry_execution_date=batch.strftime("%Y-%m-%d"),
                            entry_open=price,
                            shares=shares,
                            cost_basis=price,
                            full_exit_signal_date=_iso(exit_signal),
                            full_exit_execution_date=_iso(exit_execution),
                            full_exit_type=str(record.get("exit_type") or "") or None,
                        )
                        positions[identity] = position
                        events.append(_event_row(
                            strategy_id=strategy_id,
                            date=batch,
                            event_type="ENTRY",
                            ticker=identity[0],
                            name=position.name,
                            signal_date=position.entry_signal_date,
                            signal_type="FASTCORE_FRESH_ENTRY",
                            open_price=price,
                            shares_before=0,
                            shares_delta=shares,
                            shares_after=shares,
                            cash_before=cash_before,
                            cash_delta=-cost,
                            cash_after=cash,
                            position_cost_basis=price,
                            realized_pnl=0.0,
                            realized_return=0.0,
                            portfolio_equity_after_execution=0.0,
                        ))
            audits.append(_portfolio_audit_row(candidate, strategy_id, result, candidate.get("ranking")))

        if cash < -1e-6:
            raise RuntimeError("BLOCKED_NEGATIVE_CASH")
        equity_after = _portfolio_equity_at_open(cash, positions, daily_by_ticker, batch)
        batch_text = batch.strftime("%Y-%m-%d")
        for event in events:
            if event["execution_date"] == batch_text and event["portfolio_equity_after_execution"] == 0.0:
                event["portfolio_equity_after_execution"] = round(equity_after, 6)
        positions_by_date[batch] = {key: Position(**asdict(value)) for key, value in positions.items()}
        cash_by_date[batch] = cash

    latest_positions: dict[tuple[str, str, str], Position] = {}
    latest_cash = INITIAL_CAPITAL
    for date in calendar["dates"]:
        if date in positions_by_date:
            latest_positions = positions_by_date[date]
            latest_cash = cash_by_date[date]
        else:
            positions_by_date[date] = {key: Position(**asdict(value)) for key, value in latest_positions.items()}
            cash_by_date[date] = latest_cash
    curve = _daily_curve(calendar, cash_by_date, positions_by_date, daily_by_ticker)
    event_frame = pd.DataFrame(events)
    audit_frame = pd.DataFrame(audits)
    summary = _summary(strategy_id, signals, curve, event_frame, audit_frame)
    return {"events": event_frame, "entry_audit": audit_frame, "equity_curve": curve, "summary": summary}


def _comparison(fast: Mapping[str, Any], julia: Mapping[str, Any], meta: Mapping[str, Any]) -> dict[str, Any]:
    f = fast["summary"]
    j = julia["summary"]
    fields = {
        "initial_equity": "initial_equity",
        "final_equity": "final_equity",
        "net_profit": "net_profit",
        "total_return_pct": "total_return_pct",
        "CAGR_pct": "CAGR_pct",
        "mdd_pct": "mdd_pct",
        "average_cash_ratio": "average_cash_ratio",
        "average_concurrent_positions": "average_concurrent_positions",
        "max_concurrent_positions": "max_concurrent_positions",
        "executed_entry_count": "executed_entry_count",
        "cash_blocked_count": "cash_blocked_count",
    }
    delta = {key: round(float(j[source]) - float(f[source]), 6) for key, source in fields.items()}
    return {
        "work_id": "FASTCORE_VS_JULIA_200M_PORTFOLIO_COMPARISON_V01",
        "comparison": "JULIA_MINUS_FASTCORE",
        "fresh_signal_candidate_invariant": True,
        "strategy_delta": "PRE_PROGRESSED_LOSS_GUARD_ON_VS_OFF",
        "contract": {
            "period_start": START_DATE.strftime("%Y-%m-%d"),
            "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
            "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
            "final_valuation": f"{SUPPORT_END.strftime('%Y-%m-%d')} CLOSE",
            "market_cap_threshold": MARKET_CAP_THRESHOLD,
            "liquidity_filter_applied": False,
            "price_threshold_applied": False,
            "fundamentals_applied": False,
            "partial_profit_applied": False,
            "initial_capital": INITIAL_CAPITAL,
            "per_lifecycle_position_cap": POSITION_CAP,
            "commission": 0,
            "tax": 0,
            "slippage": 0,
            "network_requests": 0,
        },
        "signal_authority": {key: value for key, value in meta.items() if key not in {"daily_by_ticker", "strategy_record_factory", "fresh_signal_audit", "authority"}},
        "fastcore": fast["summary"],
        "julia": julia["summary"],
        "julia_minus_fastcore": delta,
    }


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def run_backtest() -> dict[str, Any]:
    signals, meta, factory = load_fresh_signal_authority()
    daily_by_ticker = meta["daily_by_ticker"]
    calendar = _build_calendar(daily_by_ticker)
    with comparison_filter_override():
        fastcore = run_portfolio(signals, calendar, daily_by_ticker, FASTCORE_ID, factory)
        julia = run_portfolio(signals, calendar, daily_by_ticker, JULIA_ID, factory)
    comparison = _comparison(fastcore, julia, meta)
    candidate_frame = pd.DataFrame(meta["fresh_signal_audit"])
    audit = pd.concat(
        [candidate_frame, fastcore["entry_audit"], julia["entry_audit"]],
        ignore_index=True,
        sort=False,
    )
    return {"signals": signals, "meta": meta, "fastcore": fastcore, "julia": julia, "comparison": comparison, "candidate_audit": audit}


def write_outputs(result: Mapping[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_frame(OUT_DIR / "fastcore_events.csv", result["fastcore"]["events"])
    _write_frame(OUT_DIR / "fastcore_equity_curve.csv", result["fastcore"]["equity_curve"])
    _json_write(OUT_DIR / "fastcore_summary.json", result["fastcore"]["summary"])
    _write_frame(OUT_DIR / "julia_events.csv", result["julia"]["events"])
    _write_frame(OUT_DIR / "julia_equity_curve.csv", result["julia"]["equity_curve"])
    _json_write(OUT_DIR / "julia_summary.json", result["julia"]["summary"])
    _json_write(OUT_DIR / "fastcore_vs_julia_comparison.json", result["comparison"])
    _write_frame(OUT_DIR / "candidate_audit.csv", result["candidate_audit"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run the local-only comparison.")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_backtest()
        if audit.request_count != 0:
            raise RuntimeError(f"BLOCKED_NETWORK_LEAKAGE: {audit.request_count}")
        result["comparison"]["contract"]["network_requests"] = audit.request_count
        write_outputs(result)
        print(json.dumps({
            "status": "COMPLETE",
            "fresh_signal_count": int(len(result["signals"])),
            "fastcore_final_equity": result["fastcore"]["summary"]["final_equity"],
            "julia_final_equity": result["julia"]["summary"]["final_equity"],
            "network_requests": audit.request_count,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"COMPARISON BACKTEST BLOCKED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
