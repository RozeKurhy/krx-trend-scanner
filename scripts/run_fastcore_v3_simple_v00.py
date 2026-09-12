#!/usr/bin/env python3
"""Run the local-only FastCore V3 V0 trade-level backtest.

FastCore V3 keeps the frozen FastCore entry contract, removes the legacy
20-day trading-value and price filters, and replaces the V2 loss guard /
score exits with the preregistered price HWM/MFE V0 exits.  This script is a
research runner only; it does not modify production strategy code and does
not run Julia or a portfolio simulation.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
import argparse
import json
import multiprocessing as mp
import socket
import sys
import time
from typing import Any, Iterator, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fastcore_control import _authority_intervals
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    clip_to_identity_lifecycle,
    pit_common_for_identity,
)
from trend_scanner.backtest.raw_investability_panel import iter_raw_investability_panels
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver


OUT_DIR = ROOT / "artifacts/backtests/fastcore_v3_simple_v00"
TRADES_PATH = OUT_DIR / "fastcore_v3_trades.csv"
SUMMARY_PATH = OUT_DIR / "fastcore_v3_summary.json"
COMPARISON_PATH = OUT_DIR / "fastcore_v3_vs_existing_fastcore_comparison.json"

EFFECTIVE_AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
RAW_MARKET_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
BASELINE_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
BASELINE_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"

START_DATE = pd.Timestamp("2021-04-01")
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
SUPPORT_END = pd.Timestamp("2026-08-21")
MARKET_CAP_THRESHOLD = 100_000_000_000.0
WORK_ID = "FASTCORE_V3_SIMPLE_BACKTEST_V00"
STRATEGY_ID = "FASTCORE_V3_SIMPLE_V00"
LOSS_GUARD_ENABLED = False
EXIT3_ENABLED = False
EXIT4_ENABLED = False

WEAK_FAST_STATES = frozenset({"SETUP", "WATCH"})

# Inclusive lower bound, exclusive upper bound, soft drawdown, hard drawdown.
MFE_TIERS: tuple[tuple[float, float | None, float, float, str], ...] = (
    (20.0, 50.0, -10.0, -20.0, "MFE_20_TO_50"),
    (50.0, 100.0, -15.0, -25.0, "MFE_50_TO_100"),
    (100.0, 200.0, -20.0, -30.0, "MFE_100_TO_200"),
    (200.0, 400.0, -25.0, -35.0, "MFE_200_TO_400"),
    (400.0, None, -30.0, -40.0, "MFE_400_PLUS"),
)


class NetworkRequestBlocked(RuntimeError):
    """Raised if the offline runner attempts a socket connection."""


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline FastCore V3 guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline FastCore V3 guard blocked socket connect_ex: {address!r}")

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


def _tasks(intervals: Mapping[tuple[str, str, str], list[tuple[str, str]]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for (ticker, isu_cd, market), ranges in sorted(intervals.items()):
        for effective_from, effective_to in ranges:
            if pd.Timestamp(effective_to) < START_DATE or pd.Timestamp(effective_from) > SUPPORT_END:
                continue
            result.append({
                "ticker": str(ticker).zfill(6),
                "isu_cd": str(isu_cd),
                "market": str(market),
                "effective_from": str(effective_from),
                "effective_to": str(effective_to),
            })
    return result


def valid_fast_signal(result: Mapping[str, Any]) -> bool:
    return bool(
        result.get("fast_machine_stage") == "TRIGGER"
        and result.get("fast_machine_stage_status") == "READY"
        and result.get("fast_monthly_permission_state") == "PERMITTED_REGIME"
        and result.get("fast_daily_risk_state") in {"NORMAL", "ELEVATED"}
        and result.get("fast_score_status") in {"READY", "PARTIAL"}
        and str(result.get("pattern_a_stage") or "").upper() in {"TRANSITION", "EARLY_TREND"}
    )


def market_cap_pass(value: float | None) -> bool:
    return value is not None and float(value) >= MARKET_CAP_THRESHOLD


def mfe_tier(mfe_pct: float) -> tuple[float, float, str] | None:
    """Return exact V0 soft/hard thresholds for the current MFE tier."""
    for lower, upper, soft, hard, label in MFE_TIERS:
        if mfe_pct >= lower and (upper is None or mfe_pct < upper):
            return soft, hard, label
    return None


def exit_decision(*, mfe_pct: float, hwm_price: float, current_close: float, fast_state: str | None) -> tuple[str | None, float | None, float | None, str | None]:
    """Evaluate one end-of-day price observation without looking ahead."""
    tier = mfe_tier(mfe_pct)
    if tier is None:
        return None, None, None, None
    soft, hard, label = tier
    # Round only the comparison value so an exact -10%/-20% boundary is not
    # lost to binary floating-point representation.
    drawdown_pct = round((current_close / hwm_price - 1.0) * 100.0, 10)
    if drawdown_pct <= hard:
        return "HARD_EXIT", soft, hard, label
    if drawdown_pct <= soft and fast_state in WEAK_FAST_STATES:
        return "SOFT_EXIT", soft, hard, label
    return None, soft, hard, label


def latest_fast_state(state_rows: list[tuple[pd.Timestamp, str]], date: pd.Timestamp) -> str | None:
    """Use only the latest completed weekly observation at or before date."""
    if not state_rows:
        return None
    dates = [item[0] for item in state_rows]
    index = bisect_right(dates, pd.Timestamp(date).normalize()) - 1
    return state_rows[index][1] if index >= 0 else None


def _mcap_at(panel: pd.DataFrame | None, signal_date: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None]:
    if panel is None or panel.empty or panel.index.duplicated().any():
        return None, None
    rows = panel.loc[panel.index <= signal_date]
    if rows.empty:
        return None, None
    raw_date = pd.Timestamp(rows.index[-1]).normalize()
    value = pd.to_numeric(rows.iloc[-1].get("market_cap"), errors="coerce")
    if pd.isna(value):
        return None, raw_date
    return float(value), raw_date


def _raw_signal_row(*, task: Mapping[str, str], name: str, week: pd.Timestamp, result: Mapping[str, Any], market_cap: float | None, raw_date: pd.Timestamp | None, status: str) -> dict[str, Any]:
    source = "ACTUAL_KRX_LOCAL_RAW_SNAPSHOT" if market_cap is not None else "MCAP_UNAVAILABLE"
    return {
        "audit_type": "RAW_FAST_SIGNAL",
        "candidate_id": f"{task['ticker']}|{task['isu_cd']}|{task['market']}|{week.strftime('%Y-%m-%d')}",
        "ticker": task["ticker"],
        "isu_cd": task["isu_cd"],
        "market": task["market"],
        "name": name,
        "signal_date": week.strftime("%Y-%m-%d"),
        "fast_score": result.get("fast_score"),
        "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
        "fast_machine_stage": result.get("fast_machine_stage"),
        "fast_machine_stage_status": result.get("fast_machine_stage_status"),
        "raw_fast_signal_status": "RAW_FAST_SIGNAL",
        "market_cap_source": source,
        "market_cap_anchor_date": raw_date.strftime("%Y-%m-%d") if raw_date is not None else None,
        "mcap_status": status,
        "status": status,
        "final_status": "FRESH_SIGNAL_MCAP_PASS" if status == "PASS" else status,
    }


_V3_RAW_PANELS: dict[str, pd.DataFrame] = {}
_V3_LOADER: RepositoryV2DailyLoader | None = None
_V3_SCORE_CONTRACT: dict[str, Any] = {}
_V3_STAGE_CONTRACT: dict[str, Any] = {}
_V3_NAMES: dict[str, str] = {}
_V3_INTERVALS: dict[tuple[str, str, str], list[tuple[str, str]]] = {}


def _scan_ticker_group(item: tuple[str, list[dict[str, str]]]) -> dict[str, Any]:
    ticker, tasks = item
    if _V3_LOADER is None:
        raise RuntimeError("V3 scanner worker is not initialized")
    daily_full = _V3_LOADER.load(ticker)
    raw_full = _V3_RAW_PANELS.get(ticker)
    if daily_full is None or daily_full.empty or raw_full is None or raw_full.empty:
        return {"signals": [], "raw_audit": [], "states": [], "identity_count": 0, "evaluation_dates": [], "evaluation_errors": 0}

    name = _V3_NAMES.get(ticker, ticker)
    signals: list[dict[str, Any]] = []
    raw_audit: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    evaluation_dates: set[str] = set()
    evaluation_errors = 0
    identity_count = 0

    for task in tasks:
        lifecycle = IdentityLifecycle(
            ticker=ticker,
            isu_cd=task["isu_cd"],
            market=task["market"],
            effective_from=pd.Timestamp(task["effective_from"]),
            effective_to=min(pd.Timestamp(task["effective_to"]), SUPPORT_END),
        )
        daily = clip_to_identity_lifecycle(daily_full, lifecycle)
        raw_panel = clip_to_identity_lifecycle(raw_full, lifecycle)
        if daily is None or daily.empty or len(daily) < 60 or not {"open", "high", "low", "close"}.issubset(daily.columns):
            continue
        if raw_panel is None or raw_panel.empty or raw_panel.index.duplicated().any():
            continue

        context = build_precomputed_ticker_context(ticker, name, daily)
        daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
        valid_weeks = [
            pd.Timestamp(value).normalize()
            for value in context.weekly_up_to(SUPPORT_END).index
            if pd.Timestamp(value).normalize() in daily_dates
            and START_DATE <= pd.Timestamp(value).normalize() <= SIGNAL_CUTOFF
        ]
        identity_count += 1
        state_key = "|".join((task["ticker"], task["isu_cd"], task["market"], task["effective_from"], task["effective_to"]))
        for week in valid_weeks:
            week_text = week.strftime("%Y-%m-%d")
            evaluation_dates.add(week_text)
            try:
                result = evaluate_pattern_a_fast(
                    ticker, name, daily, week, _V3_SCORE_CONTRACT, _V3_STAGE_CONTRACT, context=context,
                )
            except Exception:
                evaluation_errors += 1
                continue
            fast_state = str(result.get("fast_machine_stage") or "UNAVAILABLE").upper()
            if result.get("fast_machine_stage_status") != "READY":
                fast_state = "UNAVAILABLE"
            states.append({"identity_key": state_key, "date": week_text, "fast_state": fast_state})
            if not valid_fast_signal(result):
                continue

            info_dates = daily.index[daily.index <= week]
            raw_cap, raw_date = _mcap_at(raw_panel, week)
            mcap_valid = (
                raw_cap is not None
                and raw_date is not None
                and not info_dates.empty
                and raw_date <= pd.Timestamp(info_dates[-1]).normalize()
                and pit_common_for_identity(_V3_INTERVALS, ticker, task["isu_cd"], task["market"], raw_date)
                and pit_common_for_identity(_V3_INTERVALS, ticker, task["isu_cd"], task["market"], pd.Timestamp(info_dates[-1]))
            )
            if not mcap_valid:
                raw_cap = None
                status = "MCAP_UNAVAILABLE"
            elif not market_cap_pass(raw_cap):
                status = "REJECT_MCAP_BELOW_100B"
            else:
                status = "PASS"
            raw_audit.append(_raw_signal_row(task=task, name=name, week=week, result=result, market_cap=raw_cap, raw_date=raw_date, status=status))
            if status != "PASS":
                continue

            future = daily[(daily.index > week) & (daily.index <= SUPPORT_END)]
            if future.empty or not pit_common_for_identity(_V3_INTERVALS, ticker, task["isu_cd"], task["market"], future.index[0]):
                continue
            signal_id = f"{ticker}|{task['isu_cd']}|{task['market']}|{week_text}"
            signals.append({
                "signal_id": signal_id,
                "candidate_id": signal_id,
                "identity_key": state_key,
                "ticker": ticker,
                "isu_cd": task["isu_cd"],
                "market": task["market"],
                "name": name,
                "signal_date": week_text,
                "signal_information_date": pd.Timestamp(info_dates[-1]).strftime("%Y-%m-%d"),
                "fast_score": result.get("fast_score"),
                "fast_score_status": result.get("fast_score_status"),
                "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
                "fast_machine_stage": result.get("fast_machine_stage"),
                "fast_machine_stage_status": result.get("fast_machine_stage_status"),
                "monthly_permission_state": result.get("fast_monthly_permission_state"),
                "daily_risk_state": result.get("fast_daily_risk_state"),
                "market_cap": raw_cap,
                "market_cap_source": "ACTUAL_KRX_LOCAL_RAW_SNAPSHOT",
                "market_cap_anchor_date": raw_date.strftime("%Y-%m-%d") if raw_date is not None else None,
                "identity_effective_from": task["effective_from"],
                "identity_effective_to": task["effective_to"],
            })
        del daily, raw_panel, context

    return {
        "signals": signals,
        "raw_audit": raw_audit,
        "states": states,
        "identity_count": identity_count,
        "evaluation_dates": sorted(evaluation_dates),
        "evaluation_errors": evaluation_errors,
    }


def scan_signals() -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, list[tuple[pd.Timestamp, str]]], dict[str, Any]]:
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority)
    tasks = _tasks(intervals)
    names = _name_map()
    tickers = sorted({task["ticker"] for task in tasks})

    print(f"building local raw market-cap panels: tickers={len(tickers)}", flush=True)
    raw_panels = dict(iter_raw_investability_panels(tickers, end=SUPPORT_END, raw_root=RAW_MARKET_ROOT, identity_intervals=intervals))
    repository = build_repository_v2(ROOT, end=SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT_END)

    tasks_by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for task in tasks:
        tasks_by_ticker[task["ticker"]].append(task)
    global _V3_RAW_PANELS, _V3_LOADER, _V3_SCORE_CONTRACT, _V3_STAGE_CONTRACT, _V3_NAMES, _V3_INTERVALS
    _V3_RAW_PANELS = raw_panels
    _V3_LOADER = loader
    _V3_SCORE_CONTRACT = _json_read(SCORE_CONTRACT_PATH)
    _V3_STAGE_CONTRACT = _json_read(STAGE_CONTRACT_PATH)
    _V3_NAMES = names
    _V3_INTERVALS = intervals

    started = time.monotonic()
    results: list[dict[str, Any]] = []
    worker_count = min(4, max(1, len(tasks_by_ticker)))
    context = mp.get_context("fork")
    with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as pool:
        futures = [pool.submit(_scan_ticker_group, item) for item in sorted(tasks_by_ticker.items())]
        for completed, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if completed % 100 == 0 or completed == len(futures):
                print(f"V3 signal scan: {completed}/{len(futures)} ticker groups, elapsed={time.monotonic() - started:.1f}s", flush=True)
    _V3_LOADER = None

    signal_rows = [row for result in results for row in result["signals"]]
    raw_audit = [row for result in results for row in result["raw_audit"]]
    state_rows = [row for result in results for row in result["states"]]
    signals = pd.DataFrame(signal_rows)
    if not signals.empty:
        signals = signals.drop_duplicates("signal_id", keep="first").sort_values(["signal_date", "signal_id"], kind="mergesort").reset_index(drop=True)
    state_index: dict[str, list[tuple[pd.Timestamp, str]]] = defaultdict(list)
    for row in state_rows:
        state_index[str(row["identity_key"])].append((pd.Timestamp(row["date"]), str(row["fast_state"])))
    for key in state_index:
        state_index[key].sort(key=lambda item: item[0])

    evaluation_dates = {date for result in results for date in result["evaluation_dates"]}
    meta = {
        "work_id": WORK_ID,
        "evaluation_start": START_DATE.strftime("%Y-%m-%d"),
        "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
        "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
        "final_valuation": "2026-08-21 CLOSE",
        "strategy_valid_weekly_reference_date_count": len(evaluation_dates),
        "first_evaluated_weekly_date": min(evaluation_dates) if evaluation_dates else None,
        "last_evaluated_weekly_date": max(evaluation_dates) if evaluation_dates else None,
        "weekly_evaluation_error_count": sum(int(result["evaluation_errors"]) for result in results),
        "identity_intervals_processed": sum(int(result["identity_count"]) for result in results),
        "authority_interval_count": len(tasks),
        "authority_pit_sha256": authority.pit_sha256,
        "authority_pit_interval_count": authority.pit_count,
        "raw_market_cap_source": str(RAW_MARKET_ROOT.relative_to(ROOT)),
        "raw_fast_signal_candidates_before_mcap_gate": len(raw_audit),
        "mcap_pass_count": sum(row["mcap_status"] == "PASS" for row in raw_audit),
        "mcap_below_100b_count": sum(row["mcap_status"] == "REJECT_MCAP_BELOW_100B" for row in raw_audit),
        "mcap_unavailable_count": sum(row["mcap_status"] == "MCAP_UNAVAILABLE" for row in raw_audit),
        "network_requests": 0,
    }
    print(f"V3 signal scan complete: raw={len(raw_audit)}, mcap_pass={len(signals)}, elapsed={time.monotonic() - started:.1f}s", flush=True)
    # Workers inherit the panels through fork; release the parent reference as
    # soon as the scan is complete so the simulation does not retain this
    # potentially large local snapshot collection.
    _V3_RAW_PANELS = {}
    return signals, raw_audit, dict(state_index), meta


def _next_session(daily: pd.DataFrame, date: pd.Timestamp) -> pd.Timestamp | None:
    future = daily[(daily.index > pd.Timestamp(date).normalize()) & (daily.index <= SUPPORT_END)]
    return pd.Timestamp(future.index[0]).normalize() if not future.empty else None


def _path_metrics(daily: pd.DataFrame, entry_date: pd.Timestamp, end_date: pd.Timestamp, entry_open: float, extra_price: float | None = None) -> tuple[float, float, float, float]:
    held = daily.loc[(daily.index >= entry_date) & (daily.index <= end_date)]
    if held.empty:
        highs = [entry_open]
        lows = [entry_open]
    else:
        highs = [float(value) for value in held["high"].tolist()]
        lows = [float(value) for value in held["low"].tolist()]
    if extra_price is not None:
        highs.append(float(extra_price))
        lows.append(float(extra_price))
    hwm = max([entry_open, *highs])
    trough = min([entry_open, *lows])
    mfe = round((hwm / entry_open - 1.0) * 100.0, 2)
    mae = round((trough / entry_open - 1.0) * 100.0, 2)
    return hwm, trough, mfe, mae


def simulate_trade(row: Mapping[str, Any], daily_full: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], sequence: int) -> dict[str, Any] | None:
    lifecycle = IdentityLifecycle(
        ticker=str(row["ticker"]),
        isu_cd=str(row["isu_cd"]),
        market=str(row["market"]),
        effective_from=pd.Timestamp(row["identity_effective_from"]),
        effective_to=min(pd.Timestamp(row["identity_effective_to"]), SUPPORT_END),
    )
    daily = clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        return None
    signal_date = pd.Timestamp(row["signal_date"]).normalize()
    entry_date = _next_session(daily, signal_date)
    if entry_date is None:
        return None
    entry_open = float(daily.loc[entry_date, "open"])
    valuation_date = pd.Timestamp(daily.index[-1]).normalize()
    hwm = entry_open
    max_drawdown = 0.0
    exit_signal_date: pd.Timestamp | None = None
    exit_reason: str | None = None
    exit_fast_state: str | None = None
    soft_threshold: float | None = None
    hard_threshold: float | None = None
    exit_mfe_tier: str | None = None
    unexecuted_exit_signal_date: pd.Timestamp | None = None
    unexecuted_exit_reason: str | None = None

    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        high = float(bar["high"])
        close = float(bar["close"])
        hwm = max(hwm, high)
        mfe_pct = (hwm / entry_open - 1.0) * 100.0
        drawdown_pct = (close / hwm - 1.0) * 100.0
        max_drawdown = min(max_drawdown, drawdown_pct)
        fast_state = latest_fast_state(states, pd.Timestamp(date))
        decision, soft, hard, tier = exit_decision(
            mfe_pct=mfe_pct,
            hwm_price=hwm,
            current_close=close,
            fast_state=fast_state,
        )
        if decision is not None:
            exit_signal_date = pd.Timestamp(date).normalize()
            exit_reason = decision
            exit_fast_state = fast_state
            soft_threshold = soft
            hard_threshold = hard
            exit_mfe_tier = tier
            break

    exit_execution_date: pd.Timestamp | None = None
    exit_price: float | None = None
    trade_status = "OPEN_AT_CUTOFF"
    if exit_signal_date is not None:
        exit_execution_date = _next_session(daily, exit_signal_date)
        if exit_execution_date is not None:
            exit_price = float(daily.loc[exit_execution_date, "open"])
            trade_status = "REALIZED"
        else:
            unexecuted_exit_signal_date = exit_signal_date
            unexecuted_exit_reason = exit_reason
            exit_signal_date = None
            exit_reason = None
            exit_fast_state = None
            soft_threshold = None
            hard_threshold = None
            exit_mfe_tier = None

    if trade_status == "REALIZED" and exit_execution_date is not None and exit_price is not None:
        metric_end = exit_signal_date if exit_signal_date is not None else exit_execution_date
        hwm, trough, mfe, mae = _path_metrics(daily, entry_date, metric_end, entry_open, exit_price)
        terminal_return = round((exit_price / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= exit_execution_date)]))
        final_valuation_date = exit_execution_date
        final_valuation_price = exit_price
    else:
        final_close = float(daily.loc[valuation_date, "close"])
        hwm, trough, mfe, mae = _path_metrics(daily, entry_date, valuation_date, entry_open)
        terminal_return = round((final_close / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= valuation_date)]))
        final_valuation_date = SUPPORT_END
        final_valuation_price = final_close
        exit_reason = "OPEN_AT_CUTOFF"

    terminal_tier = mfe_tier(mfe)
    return {
        "strategy_id": STRATEGY_ID,
        "ticker": str(row["ticker"]),
        "isu_cd": str(row["isu_cd"]),
        "name": str(row["name"]),
        "market": str(row["market"]),
        "trade_id": f"{STRATEGY_ID}_{row['ticker']}_{sequence:03d}",
        "trade_sequence": sequence,
        "entry_signal_date": signal_date.strftime("%Y-%m-%d"),
        "entry_signal_information_date": str(row["signal_information_date"]),
        "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "entry_open": round(entry_open, 2),
        "entry_market_cap": float(row["market_cap"]),
        "market_cap_source": str(row["market_cap_source"]),
        "market_cap_anchor_date": row.get("market_cap_anchor_date"),
        "entry_pattern_a_stage": str(row["pattern_a_stage"]),
        "fast_stage": str(row["fast_machine_stage"]),
        "fast_status": str(row["fast_machine_stage_status"]),
        "monthly_permission_state": str(row["monthly_permission_state"]),
        "daily_risk": str(row["daily_risk_state"]),
        "fast_score": None if pd.isna(row.get("fast_score")) else float(row["fast_score"]),
        "fast_score_status": str(row["fast_score_status"]),
        "hwm_price": round(hwm, 2),
        "mfe": mfe,
        "mae": mae,
        "mfe_tier": terminal_tier[2] if terminal_tier else "BELOW_WINNER_MODE",
        "max_hwm_drawdown_pct": round(max_drawdown, 2),
        "soft_threshold_pct": soft_threshold,
        "hard_threshold_pct": hard_threshold,
        "fast_state_at_exit": exit_fast_state,
        "exit_mfe_tier": exit_mfe_tier,
        "exit_signal_date": exit_signal_date.strftime("%Y-%m-%d") if exit_signal_date is not None else None,
        "exit_execution_date": exit_execution_date.strftime("%Y-%m-%d") if exit_execution_date is not None else None,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "trade_status": trade_status,
        "final_valuation_date": final_valuation_date.strftime("%Y-%m-%d"),
        "final_valuation_price": round(final_valuation_price, 2),
        "unexecuted_exit_signal_date": unexecuted_exit_signal_date.strftime("%Y-%m-%d") if unexecuted_exit_signal_date is not None else None,
        "unexecuted_exit_reason": unexecuted_exit_reason,
        "terminal_return": terminal_return,
        "holding_trading_days": holding_days,
        "identity_effective_from": str(row["identity_effective_from"]),
        "identity_effective_to": str(row["identity_effective_to"]),
        # Required Korean-facing trade columns are emitted alongside the
        # audit fields below, using actual per-share execution prices.
        "종목명": str(row["name"]),
        "매수일자": entry_date.strftime("%Y-%m-%d"),
        "매수금액": round(entry_open, 2),
        "매도일자": exit_execution_date.strftime("%Y-%m-%d") if exit_execution_date is not None else None,
        "매도금액": exit_price,
        "수익률": terminal_return,
        "보유일수": holding_days,
        "MFE": mfe,
        "MAE": mae,
        "매도 사유": exit_reason,
    }


def simulate_all(signals: pd.DataFrame, states: Mapping[str, list[tuple[pd.Timestamp, str]]], daily_by_ticker: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, int]]:
    trades: list[dict[str, Any]] = []
    skipped_overlap = 0
    skipped_no_execution = 0
    for ticker, group in signals.groupby("ticker", sort=True):
        current_exit: pd.Timestamp | None = None
        sequence = 0
        ordered = group.sort_values(["signal_date", "signal_id"], kind="mergesort")
        for row in ordered.to_dict("records"):
            signal_date = pd.Timestamp(row["signal_date"]).normalize()
            if current_exit is not None and signal_date <= current_exit:
                skipped_overlap += 1
                continue
            sequence += 1
            trade = simulate_trade(row, daily_by_ticker[str(ticker)], states.get(str(row["identity_key"]), []), sequence)
            if trade is None:
                sequence -= 1
                skipped_no_execution += 1
                continue
            trades.append(trade)
            if trade["trade_status"] == "REALIZED":
                current_exit = pd.Timestamp(trade["exit_execution_date"])
            else:
                break
    frame = pd.DataFrame(trades)
    if not frame.empty:
        frame = frame.sort_values(["ticker", "entry_signal_date", "trade_sequence", "trade_id"], kind="mergesort").reset_index(drop=True)
    return frame, {"overlap_skips": skipped_overlap, "no_execution_skips": skipped_no_execution}


def _distribution(frame: pd.DataFrame, column: str) -> dict[str, float | int | None]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
    if values.empty:
        return {"count": 0, "mean": None, "median": None}
    return {"count": int(len(values)), "mean": round(float(values.mean()), 6), "median": round(float(values.median()), 6)}


def _summary(frame: pd.DataFrame, *, scan_meta: Mapping[str, Any], sim_meta: Mapping[str, int], network_requests: int) -> dict[str, Any]:
    total = len(frame)
    returns = pd.to_numeric(frame["terminal_return"], errors="coerce") if total else pd.Series(dtype=float)
    sequence = pd.to_numeric(frame["trade_sequence"], errors="coerce") if total else pd.Series(dtype=float)
    positive = int((returns > 0).sum()) if total else 0
    summary = {
        "work_id": WORK_ID,
        "status": "COMPLETE" if network_requests == 0 and int(scan_meta["weekly_evaluation_error_count"]) == 0 else "BLOCKED",
        "strategy_id": STRATEGY_ID,
        "evaluation_start": START_DATE.strftime("%Y-%m-%d"),
        "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
        "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
        "final_valuation": "2026-08-21 CLOSE",
        "entry_contract": {
            "pattern_a_stage": ["TRANSITION", "EARLY_TREND"],
            "weekly_fast_machine": "TRIGGER / READY",
            "monthly_regime": "PERMITTED_REGIME",
            "daily_risk": ["NORMAL", "ELEVATED"],
            "fast_score_status": ["READY", "PARTIAL"],
            "market_cap_min_krw": MARKET_CAP_THRESHOLD,
            "liquidity_filter_applied": False,
            "price_filter_applied": False,
            "fundamentals_filter_applied": False,
            "pyramiding": "FORBIDDEN",
            "cooldown": "NONE",
        },
        "exit_contract": {
            "loss_guard": LOSS_GUARD_ENABLED,
            "exit3": EXIT3_ENABLED,
            "exit4": EXIT4_ENABLED,
            "winner_mode_activation_mfe_pct": 20.0,
            "soft_exit": "HWM drawdown reaches tier soft threshold AND FAST state SETUP/WATCH",
            "hard_exit": "HWM drawdown reaches tier hard threshold regardless of FAST state",
            "mfe_tiers": [
                {"label": label, "lower_pct": lower, "upper_exclusive_pct": upper, "soft_drawdown_pct": soft, "hard_drawdown_pct": hard}
                for lower, upper, soft, hard, label in MFE_TIERS
            ],
            "same_open_exit_reentry": False,
        },
        "observation_semantics": {
            "hwm_price": "daily HIGH, updated after entry and before threshold check",
            "mfe": "(running daily HIGH HWM / entry OPEN - 1) * 100",
            "mae": "minimum daily LOW relative to entry OPEN through exit signal / cutoff",
            "current_price_for_breach": "daily CLOSE",
            "fast_observation": "latest completed weekly fast_machine_stage at or before the daily CLOSE",
            "exit_signal": "end-of-day observation; no look-ahead",
            "exit_execution": "next local trading day OPEN",
            "open_at_cutoff": "mark to 2026-08-21 CLOSE without forced liquidation",
        },
        "total_trades": total,
        "unique_tickers": int(frame["ticker"].nunique()) if total else 0,
        "first_entries": int((sequence == 1).sum()) if total else 0,
        "reentries": int((sequence > 1).sum()) if total else 0,
        "closed_trades": int((frame["trade_status"] == "REALIZED").sum()) if total else 0,
        "open_at_cutoff": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()) if total else 0,
        "positive_trades": positive,
        "positive_rate": round(positive / total * 100.0, 6) if total else None,
        "return": {"mean_terminal_return": _distribution(frame, "terminal_return")["mean"], "median_terminal_return": _distribution(frame, "terminal_return")["median"]},
        "mfe": _distribution(frame, "mfe"),
        "mae": _distribution(frame, "mae"),
        "holding": _distribution(frame, "holding_trading_days"),
        "exit_reason_counts": {key: int((frame["exit_reason"] == key).sum()) if total else 0 for key in ["SOFT_EXIT", "HARD_EXIT", "OPEN_AT_CUTOFF"]},
        "tail_counts": {f"return_le_{threshold:+g}%": int((returns <= threshold).sum()) if total else 0 for threshold in [-15, -20, -30, -40, -50, -60]},
        "winner_counts": {f"return_ge_{threshold:+g}%": int((returns >= threshold).sum()) if total else 0 for threshold in [20, 30, 50, 100, 200, 400]},
        "scan": dict(scan_meta),
        "simulation": dict(sim_meta),
        "network_requests": network_requests,
        "production_strategy_modified": False,
        "julia_executed": False,
    }
    return summary


def _baseline_metrics() -> dict[str, Any]:
    baseline = pd.read_csv(BASELINE_TRADES_PATH)
    returns = pd.to_numeric(baseline["terminal_return"], errors="coerce")
    return {
        "artifact": str(BASELINE_TRADES_PATH.relative_to(ROOT)),
        "summary_artifact": str(BASELINE_SUMMARY_PATH.relative_to(ROOT)),
        "work_id": _json_read(BASELINE_SUMMARY_PATH).get("work_id"),
        "evaluation_start": _json_read(BASELINE_SUMMARY_PATH).get("common_start_date"),
        "signal_cutoff": _json_read(BASELINE_SUMMARY_PATH).get("signal_end_date"),
        "execution_support_end": _json_read(BASELINE_SUMMARY_PATH).get("execution_support_end_date"),
        "mcap_min_krw": _json_read(BASELINE_SUMMARY_PATH).get("experimental_investability_conditions", {}).get("market_cap_min_krw"),
        "liquidity_min_krw": _json_read(BASELINE_SUMMARY_PATH).get("experimental_investability_conditions", {}).get("avg_trading_value_20d_min_krw"),
        "price_min_krw": _json_read(BASELINE_SUMMARY_PATH).get("experimental_investability_conditions", {}).get("close_min_krw"),
        "metrics": {
            "total_trades": len(baseline),
            "positive_rate": round(float((returns > 0).mean() * 100.0), 6),
            "mean_return": round(float(returns.mean()), 6),
            "median_return": round(float(returns.median()), 6),
            "mean_mfe": round(float(pd.to_numeric(baseline["mfe"], errors="coerce").mean()), 6),
            "median_mfe": round(float(pd.to_numeric(baseline["mfe"], errors="coerce").median()), 6),
            "mean_mae": round(float(pd.to_numeric(baseline["mae"], errors="coerce").mean()), 6),
            "median_mae": round(float(pd.to_numeric(baseline["mae"], errors="coerce").median()), 6),
            "mean_holding_days": round(float(pd.to_numeric(baseline["holding_trading_days"], errors="coerce").mean()), 6),
            "median_holding_days": round(float(pd.to_numeric(baseline["holding_trading_days"], errors="coerce").median()), 6),
            "winner_ge_50": int((returns >= 50).sum()),
            "winner_ge_100": int((returns >= 100).sum()),
            "tail_le_20": int((returns <= -20).sum()),
            "tail_le_30": int((returns <= -30).sum()),
            "tail_le_40": int((returns <= -40).sum()),
        },
    }


def _comparison(v3_summary: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    v3 = {
        "total_trades": v3_summary["total_trades"],
        "positive_rate": v3_summary["positive_rate"],
        "mean_return": v3_summary["return"]["mean_terminal_return"],
        "median_return": v3_summary["return"]["median_terminal_return"],
        "mean_mfe": v3_summary["mfe"]["mean"],
        "median_mfe": v3_summary["mfe"]["median"],
        "mean_mae": v3_summary["mae"]["mean"],
        "median_mae": v3_summary["mae"]["median"],
        "mean_holding_days": v3_summary["holding"]["mean"],
        "median_holding_days": v3_summary["holding"]["median"],
        "winner_ge_50": v3_summary["winner_counts"]["return_ge_+50%"],
        "winner_ge_100": v3_summary["winner_counts"]["return_ge_+100%"],
        "tail_le_20": v3_summary["tail_counts"]["return_le_-20%"],
        "tail_le_30": v3_summary["tail_counts"]["return_le_-30%"],
        "tail_le_40": v3_summary["tail_counts"]["return_le_-40%"],
    }
    base = dict(baseline["metrics"])
    keys = list(v3)
    return {
        "work_id": WORK_ID,
        "comparison": "FastCore V3 minus existing FastCore CONTROL",
        "evaluation_contract": {
            "evaluation_start": START_DATE.strftime("%Y-%m-%d"),
            "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
            "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
            "final_valuation": "2026-08-21 CLOSE",
            "baseline_artifact": baseline["artifact"],
            "baseline_period_recorded_as": [baseline["evaluation_start"], baseline["signal_cutoff"], baseline["execution_support_end"]],
            "baseline_contract_match": True,
        },
        "existing_fastcore_baseline": baseline,
        "fastcore_v3": v3,
        "delta_v3_minus_baseline": {key: None if v3[key] is None or base[key] is None else round(float(v3[key]) - float(base[key]), 6) for key in keys},
        "interpretation_boundary": [
            "V3 delta includes liquidity-filter removal and V0 exit replacement.",
            "The existing CONTROL also records a 300B market-cap and 5,000 KRW price threshold; V3 uses the instructed 100B market-cap-only entry filter, so entry-population differences include that threshold change.",
            "No separate A/B decomposition was run.",
        ],
    }


def write_outputs(frame: pd.DataFrame, summary: Mapping[str, Any], comparison: Mapping[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(TRADES_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    _json_write(COMPARISON_PATH, comparison)


def run_backtest() -> dict[str, Any]:
    signals, raw_audit, states, scan_meta = scan_signals()
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    repository = build_repository_v2(ROOT, end=SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT_END)
    for ticker in sorted(signals["ticker"].astype(str).unique() if not signals.empty else []):
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"missing local Repository V2 prices for {ticker}")
        daily_by_ticker[ticker] = daily
    frame, sim_meta = simulate_all(signals, states, daily_by_ticker)
    scan_meta = dict(scan_meta)
    scan_meta["raw_fast_signal_candidates_before_mcap_gate"] = len(raw_audit)
    summary = _summary(frame, scan_meta=scan_meta, sim_meta=sim_meta, network_requests=0)
    baseline = _baseline_metrics()
    comparison = _comparison(summary, baseline)
    comparison["source_audit"] = {
        "raw_fast_signal_candidates_before_mcap_gate": len(raw_audit),
        "mcap_pass_count": sum(row["mcap_status"] == "PASS" for row in raw_audit),
        "mcap_below_100b_count": sum(row["mcap_status"] == "REJECT_MCAP_BELOW_100B" for row in raw_audit),
        "mcap_unavailable_count": sum(row["mcap_status"] == "MCAP_UNAVAILABLE" for row in raw_audit),
    }
    write_outputs(frame, summary, comparison)
    return {"summary": summary, "comparison": comparison, "raw_audit": raw_audit, "signals": signals}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the offline FastCore V3 simple backtest")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_backtest()
        result["summary"]["network_requests"] = audit.request_count
        result["summary"]["status"] = "COMPLETE" if audit.request_count == 0 else "BLOCKED"
        result["comparison"]["network_requests"] = audit.request_count
        _json_write(SUMMARY_PATH, result["summary"])
        _json_write(COMPARISON_PATH, result["comparison"])
        print(json.dumps({
            "status": result["summary"]["status"],
            "total_trades": result["summary"]["total_trades"],
            "network_requests": audit.request_count,
            "soft_exit": result["summary"]["exit_reason_counts"]["SOFT_EXIT"],
            "hard_exit": result["summary"]["exit_reason_counts"]["HARD_EXIT"],
            "open_at_cutoff": result["summary"]["exit_reason_counts"]["OPEN_AT_CUTOFF"],
        }, ensure_ascii=False), flush=True)
        return 0 if result["summary"]["status"] == "COMPLETE" else 1
    except Exception as exc:
        print(f"FASTCORE V3 BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
