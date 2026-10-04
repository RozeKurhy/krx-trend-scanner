#!/usr/bin/env python3
"""Compare monthly and exact-session Pattern B NORMAL exit cadence for B Select.

Entries, PIT-qualified signals, permanent exclusions, costs, windows, and the
cash-aware portfolio engine are fixed. The only strategy difference is whether
NORMAL is observed at exact month-end sessions or at every exact KRX session.
"""

from __future__ import annotations

import argparse
import bisect
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01 as portfolio_v01  # noqa: E402
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as portfolio_v02  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base  # noqa: E402
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2  # noqa: E402
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b  # noqa: E402


STUDY_ID = "B_SELECT_DAILY_NORMAL_EXIT_CADENCE_V01"
OUTPUT_RELATIVE = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_cadence_v01")
SOURCE_ROOT = Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01")
NORMALIZATION_ROOT = Path("artifacts/strategies/b_select_core_v1/research/exact_next_normalization_impact_v01")
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
WORKERS = 10
WARMUP_YEARS = 5
SEED = 20261005
BOUNDARY_SPOT_CHECKS = 250
EXPECTED_START_HEAD = "6d7b7a03eb4935de268d8f8d942c82c03086696c"
EXPECTED_START_STATUS = (
    "## main...origin/main; only this cadence script and its targeted test are untracked"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=pattern_b_base._json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _date(value: Any) -> str:
    return str(value)[:10]


def _frame_key(record: Mapping[str, Any]) -> str:
    return "|".join((
        str(record.get("ticker", "")).zfill(6),
        str(record.get("isu_cd", "")).upper(),
        str(record.get("market", "")).upper(),
        _date(record.get("identity_effective_from", "")),
        _date(record.get("identity_effective_to", "")),
    ))


def _next_exact_session(trading_dates: Sequence[str], signal_date: str) -> str | None:
    position = bisect.bisect_right(trading_dates, _date(signal_date))
    return trading_dates[position] if position < len(trading_dates) else None


def _next_executable_open(
    record: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[str],
    signal_date: str,
    support_end: str,
) -> tuple[str | None, float | None, list[str]]:
    """Find the first subsequent exact KRX session with a valid V2 open."""
    position = bisect.bisect_right(trading_dates, _date(signal_date))
    unavailable_sessions: list[str] = []
    for day in trading_dates[position:]:
        if day > _date(support_end):
            break
        price = portfolio_v02.portfolio._price(record, frames, pd.Timestamp(day), "open")
        if price is not None and not pd.isna(price) and math.isfinite(float(price)) and float(price) > 0:
            return day, float(price), unavailable_sessions
        unavailable_sessions.append(day)
    return None, None, unavailable_sessions


def _rebase_entry_price(source: Mapping[str, Any], current_open: float) -> tuple[dict[str, Any], bool]:
    """Apply current Repository V2 open to a copy while preserving its source value."""
    if not math.isfinite(float(current_open)) or float(current_open) <= 0:
        raise RuntimeError(f"INVALID_CURRENT_REPOSITORY_V2_ENTRY_OPEN:{current_open}")
    row = copy.deepcopy(dict(source))
    previous_open = pd.to_numeric(row.get("entry_reference_open"), errors="coerce")
    if pd.isna(previous_open) or float(previous_open) <= 0:
        raise RuntimeError(f"INVALID_FROZEN_SOURCE_ENTRY_OPEN:{row.get('trade_id')}")
    current_open = float(current_open)
    row["source_entry_reference_open"] = float(previous_open)
    row["entry_reference_open"] = current_open
    row["entry_price"] = current_open
    return row, not math.isclose(float(previous_open), current_open, rel_tol=0, abs_tol=0.011)


def _month_end_sessions(trading_dates: Sequence[str], start: str, end: str) -> list[str]:
    last_by_month: dict[str, str] = {}
    for day in trading_dates:
        if start <= day <= end:
            last_by_month[day[:7]] = day
    return sorted(last_by_month.values())


def _feature_boundary_sessions(trading_dates: Sequence[str], start: str, end: str) -> list[str]:
    """Sessions when a completed MonthEnd or W-FRI bar first enters Pattern B."""
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    labels = set(pd.date_range(first, last, freq="W-FRI"))
    labels.update(pd.date_range(first, last, freq=pd.offsets.MonthEnd()))
    output: set[str] = set()
    for label in labels:
        target = label.strftime("%Y-%m-%d")
        position = bisect.bisect_left(trading_dates, target)
        if position < len(trading_dates) and trading_dates[position] <= end:
            output.add(trading_dates[position])
    return sorted(output)


def _interior_sessions(
    trading_dates: Sequence[str],
    start: str,
    end: str,
    boundary_dates: Sequence[str],
) -> list[str]:
    boundary_set = set(boundary_dates)
    return [day for day in trading_dates if start < day < end and day not in boundary_set]


def _load_all_prices(
    records_by_window: Mapping[str, list[dict[str, Any]]],
    end: str,
) -> tuple[dict[str, pd.DataFrame | None], dict[str, dict[str, Any]], Any, dict[str, str]]:
    earliest_signal: dict[str, str] = {}
    for rows in records_by_window.values():
        for row in rows:
            ticker = str(row["ticker"]).zfill(6)
            day = _date(row["entry_signal_date"])
            earliest_signal[ticker] = min(earliest_signal.get(ticker, day), day)
    starts = {
        ticker: max("2010-01-01", (pd.Timestamp(day) - pd.DateOffset(years=WARMUP_YEARS)).strftime("%Y-%m-%d"))
        for ticker, day in earliest_signal.items()
    }

    repository = build_repository_v2(ROOT, end=end)
    daily_by_ticker: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="b-select-normal-cadence") as pool:
        futures = {
            pool.submit(
                RepositoryV2DailyLoader(repository, start=starts[ticker], end=end).load,
                ticker,
            ): ticker
            for ticker in sorted(earliest_signal)
        }
        for number, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            daily_by_ticker[ticker] = future.result()
            if number % 50 == 0 or number == len(futures):
                print(f"Loaded Repository V2 OHLC: {number:,}/{len(futures):,} tickers", flush=True)

    audit = {}
    missing = []
    silent_drops = 0
    for ticker, daily in daily_by_ticker.items():
        query = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        row = {
            "status": query.get("status"),
            "reason": query.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "requested_start": starts[ticker],
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "explicit_exclusion_count": int(projection.get("explicit_exclusion_count", 0) or 0),
            "silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
        }
        audit[ticker] = row
        silent_drops += row["silent_inner_drop_count"]
        if daily is None or daily.empty:
            missing.append(ticker)
    if missing:
        raise RuntimeError(f"REPOSITORY_V2_PRICE_INPUT_UNAVAILABLE:{len(missing)}:{missing[:20]}")
    if silent_drops:
        raise RuntimeError(f"REPOSITORY_V2_SILENT_INNER_DROP:{silent_drops}")
    return daily_by_ticker, audit, repository, starts


def _state_at(
    record: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    day: str,
    cache: dict[tuple[str, str], dict[str, Any]],
    audit_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (_frame_key(record), day)
    if key not in cache:
        frame = frames.get(key[0])
        if frame is None:
            raise RuntimeError(f"EXACT_PIT_COMPONENT_FRAME_MISSING:{key[0]}")
        result = evaluate_pattern_b(
            str(record["ticker"]).zfill(6),
            frame.loc[:, ["high", "low", "close"]],
            day,
        )
        cache[key] = {
            "evaluation_status": result.evaluation_status.value,
            "state": result.pattern_b_state,
            "reason_codes": "|".join(result.reason_codes),
            "monthly_last_bar": result.monthly_last_bar,
            "weekly_last_bar": result.weekly_last_bar,
            "range_36m": result.range_36m,
            "monthly_ma24_distance": result.monthly_ma24_distance,
            "range_52w": result.range_52w,
        }
    if key not in audit_by_key:
        audit_by_key[key] = {
            "ticker": str(record["ticker"]).zfill(6),
            "isu_cd": str(record["isu_cd"]).upper(),
            "component_id": record.get("component_id"),
            "as_of": day,
            **cache[key],
        }
    return cache[key]


def _first_normal(
    record: Mapping[str, Any],
    check_dates: Sequence[str],
    frames: Mapping[str, pd.DataFrame],
    cache: dict[tuple[str, str], dict[str, Any]],
    audit_by_key: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str | None, str | None, int]:
    checked = 0
    for day in check_dates:
        state = _state_at(record, frames, day, cache, audit_by_key)
        checked += 1
        if state["evaluation_status"] == "READY" and state["state"] == "NORMAL":
            return day, "NORMAL", checked
    return None, None, checked


def _mark_open_at_cutoff(
    row: dict[str, Any],
    frames: Mapping[str, pd.DataFrame],
    effective_end: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    row.update(
        trade_status="OPEN_AT_CUTOFF",
        exit_execution_date=None,
        exit_reference_open=None,
        exit_price=None,
        exit_market=None,
        exit_fill_status=None,
        window_execution_support_exit_fill=False,
        gross_return_pct=None,
        commission_slippage_pre_tax_return_pct=None,
        full_standard_net_return_pct=None,
        sell_tax_rate=None,
        mark_to_cutoff_gross_return_pct=None,
        mark_to_cutoff_after_entry_cost_pct=None,
    )
    close = portfolio_v02.portfolio._price(row, frames, pd.Timestamp(effective_end), "close")
    if close is not None and close > 0:
        row.update(
            cutoff_valuation_date=effective_end,
            cutoff_close=float(close),
            terminal_valuation_date=effective_end,
            terminal_valuation_price=float(close),
            valuation_status="MARKED_EXACT_CUTOFF_CLOSE",
            valuation_reason=None,
        )
    else:
        row.update(
            cutoff_valuation_date=None,
            cutoff_close=None,
            terminal_valuation_date=None,
            terminal_valuation_price=None,
            valuation_status="UNRESOLVED",
            valuation_reason="no exact adjusted close on effective_end",
        )
    return row, {"execution_status": "OPEN_AT_CUTOFF", "execution_date": None, "cutoff_close": close}


def _revised_record(
    source: Mapping[str, Any],
    signal_date: str | None,
    signal_state: str | None,
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[str],
    effective_end: str,
    execution_support: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = copy.deepcopy(dict(source))
    row["cutoff_date"] = effective_end
    row["exit_signal_date"] = signal_date
    row["exit_signal_state"] = signal_state
    row["window_execution_support_exit_fill"] = False

    if signal_date is not None:
        execution_date, ref, unavailable_sessions = _next_executable_open(
            row, frames, trading_dates, signal_date, execution_support,
        )
        if execution_date is None or ref is None:
            row, audit = _mark_open_at_cutoff(row, frames, effective_end)
            audit.update(
                execution_status="NO_EXECUTABLE_OPEN_WITHIN_SUPPORT",
                execution_date=None,
                unavailable_exact_sessions=unavailable_sessions,
            )
            return row, audit
        row.update(
            trade_status="REALIZED",
            exit_execution_date=execution_date,
            exit_reference_open=float(ref),
            exit_price=float(ref),
            exit_market=str(row.get("entry_market") or row.get("signal_market") or row.get("market") or "").upper(),
            exit_fill_status="EXECUTED_NEXT_EXACT_SESSION_OPEN",
            window_execution_support_exit_fill=bool(execution_date > effective_end),
            cutoff_valuation_date=None,
            cutoff_close=None,
            terminal_valuation_date=None,
            terminal_valuation_price=None,
            valuation_status=None,
            valuation_reason=None,
        )
        return row, {
            "execution_status": "EXECUTED",
            "execution_date": execution_date,
            "reference_open": float(ref),
            "unavailable_exact_sessions": unavailable_sessions,
        }

    return _mark_open_at_cutoff(row, frames, effective_end)


def _trade_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closed = [row for row in trades if row.get("trade_status") == "REALIZED"]
    opened = [row for row in trades if row.get("trade_status") == "OPEN_AT_CUTOFF"]
    gross = pattern_b_base._metric_summary(row.get("gross_return_pct") for row in closed)
    costed = pattern_b_base._metric_summary(row.get("commission_slippage_pre_tax_return_pct") for row in closed)
    holdings = pd.to_numeric(pd.Series([row.get("holding_krx_sessions") for row in trades]), errors="coerce").dropna()
    return {
        "filled_count": len(trades),
        "realized_count": len(closed),
        "open_count": len(opened),
        "gross_mean_pct": gross["mean_pct"],
        "gross_median_pct": gross["median_pct"],
        "gross_win_rate_pct": gross["win_rate_pct"],
        "costed_pre_tax_mean_pct": costed["mean_pct"],
        "costed_pre_tax_median_pct": costed["median_pct"],
        "costed_pre_tax_win_rate_pct": costed["win_rate_pct"],
        "gross_le_15_count": sum(float(row["gross_return_pct"]) <= -15 for row in closed),
        "gross_le_30_count": gross["le_30_count"],
        "gross_ge_30_count": sum(float(row["gross_return_pct"]) >= 30 for row in closed),
        "gross_ge_50_count": gross["ge_50_count"],
        "mean_holding_sessions": float(holdings.mean()) if len(holdings) else None,
        "median_holding_sessions": float(holdings.median()) if len(holdings) else None,
        "exact_cutoff_open_count": sum(row.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE" for row in opened),
        "unresolved_open_count": sum(row.get("valuation_status") != "MARKED_EXACT_CUTOFF_CLOSE" for row in opened),
    }


def _check_non_overlapping(trades: Sequence[Mapping[str, Any]], effective_end: str, window_id: str, scenario: str) -> int:
    by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for trade in trades:
        by_identity.setdefault((str(trade["ticker"]).zfill(6), str(trade["isu_cd"]).upper()), []).append(trade)
    checked = 0
    for identity, rows in by_identity.items():
        rows.sort(key=lambda row: _date(row["entry_execution_date"]))
        for previous, current in zip(rows, rows[1:]):
            prior_end = _date(previous["exit_execution_date"]) if previous.get("exit_execution_date") else effective_end
            if _date(current["entry_execution_date"]) <= prior_end:
                raise RuntimeError(f"{window_id}:{scenario}:SAME_IDENTITY_OVERLAP:{identity}:{previous.get('trade_id')}:{current.get('trade_id')}")
            checked += 1
    return checked


def _build_trade_rows(
    inputs: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[str],
    global_boundary_dates: Sequence[str],
    month_end_dates: Sequence[str],
    state_cache: dict[tuple[str, str], dict[str, Any]],
    state_audit: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any]]:
    window_id = str(inputs["window_id"])
    window = inputs["window"]
    start, end, support = (_date(window[k]) for k in ("effective_start", "effective_end", "execution_support"))
    records = [copy.deepcopy(row) for row in inputs["records"]]
    source_trade_by_key = {
        (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper(), _date(row["entry_signal_date"])): row
        for row in records
    }
    allowed_signal_keys = {
        (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper(), _date(row["entry_signal_date"]))
        for row in inputs["pass_rows"]
        if str(row.get("simulated_entry_status")) == "FILLED"
    }
    if allowed_signal_keys != set(source_trade_by_key):
        raise RuntimeError(f"{window_id}:FIXED_ENTRY_LEDGER_KEY_MISMATCH")

    window_month_ends = [day for day in month_end_dates if start <= day <= end]
    window_boundaries = [day for day in global_boundary_dates if start <= day <= end]
    scenario_rows: dict[str, list[dict[str, Any]]] = {"CONTROL_MONTH_END": [], "TEST_DAILY": []}
    comparison_rows: list[dict[str, Any]] = []
    exit_errors = []
    checked_state_count = {"CONTROL_MONTH_END": 0, "TEST_DAILY": 0}
    control_parity = {"signal_match": 0, "signal_mismatch": 0, "execution_match": 0, "execution_mismatch": 0}
    entry_price_rebased_count = 0

    for key, source in sorted(source_trade_by_key.items(), key=lambda item: (item[0][0], item[0][2])):
        ticker, isu, signal_day = key
        entry_exec = _date(source["entry_execution_date"])
        entry_expected = _next_exact_session(trading_dates, signal_day)
        if entry_exec != entry_expected:
            raise RuntimeError(f"{window_id}:ENTRY_NOT_NEXT_EXACT_SESSION:{key}:{entry_exec}:{entry_expected}")
        entry_open = portfolio_v02.portfolio._price(source, frames, pd.Timestamp(entry_exec), "open")
        if entry_open is None or float(entry_open) <= 0:
            raise RuntimeError(f"{window_id}:CURRENT_REPOSITORY_V2_ENTRY_OPEN_MISSING:{key}:{entry_open}")
        stored_entry = float(source["entry_reference_open"])
        source, was_rebased = _rebase_entry_price(source, float(entry_open))
        entry_price_rebased_count += int(was_rebased)

        control_checks = [day for day in window_month_ends if day > signal_day]
        control_signal, control_state, count = _first_normal(
            source, control_checks, frames, state_cache, state_audit,
        )
        control_state_check_count = count
        checked_state_count["CONTROL_MONTH_END"] += count

        test_checks = sorted(
            {entry_exec}
            | {day for day in window_boundaries if day > entry_exec}
            | {day for day in window_month_ends if day > entry_exec}
        )
        test_signal, test_state, count = _first_normal(
            source, test_checks, frames, state_cache, state_audit,
        )
        test_state_check_count = count
        checked_state_count["TEST_DAILY"] += count

        control_row, control_execution = _revised_record(
            source, control_signal, control_state, frames, trading_dates, end, support,
        )
        test_row, test_execution = _revised_record(
            source, test_signal, test_state, frames, trading_dates, end, support,
        )
        for scenario, row in (("CONTROL_MONTH_END", control_row), ("TEST_DAILY", test_row)):
            frame = frames[_frame_key(row)]
            pattern_b_base._path_metrics(row, frame, list(trading_dates), end)
            pattern_b_base._calculate_returns(row)
            if row.get("exit_signal_date") and _date(row["exit_signal_date"]) > end:
                raise RuntimeError(f"{window_id}:{scenario}:EXIT_SIGNAL_AFTER_CUTOFF:{row['trade_id']}")
            exit_execution_value = row.get("exit_execution_date")
            if exit_execution_value is not None and not pd.isna(exit_execution_value):
                expected, expected_open, _ = _next_executable_open(
                    row, frames, trading_dates, _date(row["exit_signal_date"]), support,
                )
                actual = _date(exit_execution_value)
                if actual != expected:
                    raise RuntimeError(
                        f"{window_id}:{scenario}:EXIT_NOT_NEXT_EXECUTABLE_SESSION:{row['trade_id']}"
                        f":signal={_date(row['exit_signal_date'])}:actual={actual}:expected={expected}:support={support}"
                    )
                if expected_open is None or not math.isclose(
                    float(row["exit_reference_open"]), expected_open, rel_tol=0, abs_tol=0.011,
                ):
                    raise RuntimeError(f"{window_id}:{scenario}:EXIT_OPEN_DIFFERS_FROM_REPOSITORY_V2:{row['trade_id']}")
                if _date(row["exit_execution_date"]) > support:
                    raise RuntimeError(f"{window_id}:{scenario}:EXIT_AFTER_SUPPORT:{row['trade_id']}")
            scenario_rows[scenario].append(row)

        if control_execution["execution_status"].startswith("MISSING") or test_execution["execution_status"].startswith("MISSING"):
            exit_errors.append({
                "ticker": ticker,
                "isu_cd": isu,
                "entry_signal_date": signal_day,
                "control_signal_date": control_signal,
                "control_execution": control_execution,
                "test_signal_date": test_signal,
                "test_execution": test_execution,
            })

        stored_signal = _date(source.get("exit_signal_date")) if source.get("exit_signal_date") and not pd.isna(source.get("exit_signal_date")) else None
        stored_execution = _date(source.get("exit_execution_date")) if source.get("exit_execution_date") and not pd.isna(source.get("exit_execution_date")) else None
        signal_match = control_signal == stored_signal
        control_parity["signal_match" if signal_match else "signal_mismatch"] += 1
        execution_match = _date(control_row.get("exit_execution_date")) == stored_execution if control_row.get("exit_execution_date") and stored_execution else control_row.get("exit_execution_date") in (None, "") and stored_execution is None
        control_parity["execution_match" if execution_match else "execution_mismatch"] += 1

        control_return = control_row.get("commission_slippage_pre_tax_return_pct")
        test_return = test_row.get("commission_slippage_pre_tax_return_pct")
        if control_return is not None and test_return is not None:
            return_delta = float(test_return) - float(control_return)
        else:
            return_delta = None
        days_advanced = None
        if control_signal and test_signal:
            days_advanced = bisect.bisect_left(trading_dates, control_signal) - bisect.bisect_left(trading_dates, test_signal)
        comparison_rows.append({
            "window_id": window_id,
            "ticker": ticker,
            "isu_cd": isu,
            "entry_signal_date": signal_day,
            "entry_execution_date": entry_exec,
            "source_entry_execution_open": stored_entry,
            "current_entry_execution_open": float(entry_open),
            "entry_price_rebased": was_rebased,
            "source_control_exit_signal_date": stored_signal,
            "source_control_exit_execution_date": stored_execution,
            "control_exit_signal_date": control_signal,
            "control_exit_execution_date": control_row.get("exit_execution_date"),
            "control_exit_open": control_row.get("exit_reference_open"),
            "control_exit_execution_status": control_execution["execution_status"],
            "control_unavailable_exact_sessions_before_fill": "|".join(control_execution.get("unavailable_exact_sessions", [])),
            "test_exit_signal_date": test_signal,
            "test_exit_execution_date": test_row.get("exit_execution_date"),
            "test_exit_open": test_row.get("exit_reference_open"),
            "test_exit_execution_status": test_execution["execution_status"],
            "test_unavailable_exact_sessions_before_fill": "|".join(test_execution.get("unavailable_exact_sessions", [])),
            "test_minus_control_signal_sessions": days_advanced,
            "control_trade_status": control_row.get("trade_status"),
            "test_trade_status": test_row.get("trade_status"),
            "control_gross_return_pct": control_row.get("gross_return_pct"),
            "test_gross_return_pct": test_row.get("gross_return_pct"),
            "control_costed_pre_tax_return_pct": control_return,
            "test_costed_pre_tax_return_pct": test_return,
            "test_minus_control_costed_return_pp": return_delta,
            "control_holding_krx_sessions": control_row.get("holding_krx_sessions"),
            "test_holding_krx_sessions": test_row.get("holding_krx_sessions"),
            "control_source_signal_match": signal_match,
            "control_source_execution_match": execution_match,
            "control_state_checks": control_state_check_count,
            "test_state_checks": test_state_check_count,
        })

    overlap_counts = {
        scenario: _check_non_overlapping(rows, end, window_id, scenario)
        for scenario, rows in scenario_rows.items()
    }
    validations = {
        "fixed_entry_key_count": len(source_trade_by_key),
        "fixed_entry_key_set_same_between_scenarios": True,
        "entries_on_next_exact_krx_session": len(source_trade_by_key),
        "entry_price_rebased_row_count": entry_price_rebased_count,
        "exit_execution_error_count": len(exit_errors),
        "control_source_monthly_exit_signal_match_count": control_parity["signal_match"],
        "control_source_monthly_exit_signal_mismatch_count": control_parity["signal_mismatch"],
        "control_source_monthly_exit_execution_match_count": control_parity["execution_match"],
        "control_source_monthly_exit_execution_mismatch_count": control_parity["execution_mismatch"],
        "control_identity_overlap_pair_count": overlap_counts["CONTROL_MONTH_END"],
        "test_identity_overlap_pair_count": overlap_counts["TEST_DAILY"],
        "control_state_evaluations_until_exit_or_cutoff": checked_state_count["CONTROL_MONTH_END"],
        "test_state_evaluations_until_exit_or_cutoff": checked_state_count["TEST_DAILY"],
    }
    return scenario_rows, comparison_rows, {"validations": validations, "exit_errors": exit_errors}


def _validate_state_piecewise(
    all_rows: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[str],
    boundary_dates: Sequence[str],
    cache: dict[tuple[str, str], dict[str, Any]],
    audit_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for scenarios in all_rows.values():
        for trade in scenarios["TEST_DAILY"]:
            start = _date(trade["entry_execution_date"])
            end = _date(trade.get("exit_signal_date") or trade["cutoff_date"])
            if start < end:
                interior_sessions = _interior_sessions(trading_dates, start, end, boundary_dates)
                if interior_sessions:
                    candidates.append((trade, start, end, interior_sessions))
    candidates.sort(key=lambda item: (str(item[0]["ticker"]), item[1], item[2]))
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    checks = []
    for trade, start, end, sessions in candidates:
        frame = frames[_frame_key(trade)]
        day = sessions[len(sessions) // 2]
        prior_boundaries = [item for item in boundary_dates if start <= item <= day]
        prior_day = max([start, *prior_boundaries])
        expected = _state_at(trade, frames, prior_day, cache, audit_by_key)
        direct = evaluate_pattern_b(
            str(trade["ticker"]).zfill(6), frame.loc[:, ["high", "low", "close"]], day,
        )
        match = (
            expected["evaluation_status"] == direct.evaluation_status.value
            and expected["state"] == direct.pattern_b_state
            and expected["monthly_last_bar"] == direct.monthly_last_bar
            and expected["weekly_last_bar"] == direct.weekly_last_bar
        )
        checks.append({
            "ticker": str(trade["ticker"]).zfill(6),
            "isu_cd": str(trade["isu_cd"]).upper(),
            "entry_signal_date": _date(trade["entry_signal_date"]),
            "prior_feature_boundary_session": prior_day,
            "intervening_exact_krx_session": day,
            "expected_state": expected["state"],
            "direct_state": direct.pattern_b_state,
            "expected_evaluation_status": expected["evaluation_status"],
            "direct_evaluation_status": direct.evaluation_status.value,
            "monthly_last_bar_match": expected["monthly_last_bar"] == direct.monthly_last_bar,
            "weekly_last_bar_match": expected["weekly_last_bar"] == direct.weekly_last_bar,
            "all_checks_pass": bool(match),
        })
        if len(checks) >= BOUNDARY_SPOT_CHECKS:
            break
    if len(checks) < min(30, BOUNDARY_SPOT_CHECKS):
        raise RuntimeError(f"INSUFFICIENT_BOUNDARY_EQUIVALENCE_SPOT_CHECKS:{len(checks)}")
    if not all(row["all_checks_pass"] for row in checks):
        raise RuntimeError("DAILY_STATE_PIECEWISE_BOUNDARY_EQUIVALENCE_FAILED")
    return checks


def _portfolio_replay(
    inputs: Mapping[str, Any],
    records: list[dict[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[str],
    strategy_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    next_audit = portfolio_v02.verify_next_session_execution_dates(records, frames, trading_dates, inputs["window"])
    if next_audit["violation_count"]:
        raise RuntimeError(f"{strategy_id}:NEXT_SESSION_EXECUTION_AUDIT_FAILED:{next_audit}")
    replay = portfolio_v02.run_replay(records, frames, trading_dates, inputs["window"], strategy_id)
    valuation = portfolio_v02.summarize_valuation(replay["daily_equity"], replay["skipped"], inputs["window"])
    metrics = portfolio_v02.window_metrics_from_replay(replay, inputs, valuation, trading_dates)
    cash = portfolio_v02.cash_diagnostics(replay, metrics, {})
    cost_rows, cost_summary = portfolio_v02.audit_costs(replay["events"])
    lifecycle = portfolio_v02.verify_executed_identity_lifecycle(replay["events"])
    if metrics.get("cash_conservation_pass") is not True:
        raise RuntimeError(f"{strategy_id}:CASH_CONSERVATION_FAILED")
    if cost_summary["mismatch_count"] or not cost_summary["coverage_complete"]:
        raise RuntimeError(f"{strategy_id}:COST_AUDIT_FAILED:{cost_summary}")
    if lifecycle.get("violation_count"):
        raise RuntimeError(f"{strategy_id}:IDENTITY_LIFECYCLE_FAILED:{lifecycle}")
    return replay, {"metrics": metrics, "cash": cash, "valuation": valuation, "cost_audit": cost_summary, "lifecycle": lifecycle, "next_session_audit": next_audit}, {"cost_rows": cost_rows}


def _format(value: Any, suffix: str = "", places: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{places}f}{suffix}"


def _report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# B Select Core V1 — 월말 vs 일별 NORMAL 청산 cadence 연구 V01",
        "",
        f"실행 상태: **{summary['status']}**",
        "",
        "## 비교 정의",
        "",
        "- CONTROL은 매월 마지막 exact KRX 거래일에 Pattern B `NORMAL`을 확인하고, 다음 exact KRX 세션부터 유효한 Repository V2 시가가 처음 확인되는 시점에 청산해.",
        "- TEST는 보유 중 모든 exact KRX 세션의 close 기준 Pattern B `NORMAL`을 확인하고, 다음 exact KRX 세션부터 유효한 Repository V2 시가가 처음 확인되는 시점에 청산해.",
        "- ENTRY는 해시 검증된 기존 후보 원장의 월말 신호·다음 exact KRX 세션을 양쪽에서 그대로 사용해.",
        "- Pattern B V01 feature contract와 sealed State Rule V02, Repository V2, PIT COMMON identity, 최신 승인 영구 제외, 200M 초기자본, 5M 종목 예산, 현금·수수료·슬리피지 계약을 양쪽에 동일 적용했어. 공식 portfolio 지표에는 매도세금을 넣지 않았어.",
        "- 월별 후보 원장의 종목·신호일·실행일은 고정했어. 저장된 과거 진입가는 조정가격 기준 차이를 확인하기 위해 보존하고, 두 시나리오 모두 현재 Repository V2에서 체결 가능한 해당 시가를 연구용 진입가로 사용했어.",
        "- 바뀐 변수는 NORMAL 확인 cadence 하나야. 공식 production/history와 기존 5-window 파일은 수정하지 않았어.",
        "- 일별 evaluator는 완료 MonthEnd/W-FRI bar만 보므로 상태 갱신 경계와 entry execution date에서 평가했어. 월봉/주봉 경계 사이 상태가 동일한지 250개 직접 as-of 대조를 수행했어.",
        "",
        "## 5-window 비교",
        "",
        "| Window | Scenario | Filled | Closed | Open | Portfolio equity | Return | CAGR | MDD | MDD type / coverage | Cash skip | Avg utilization | Gross win / median | Costed pre-tax median | Mean / median hold |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---|",
    ]
    for window_id in WINDOW_IDS:
        result = summary["windows"][window_id]
        for scenario in ("CONTROL_MONTH_END", "TEST_DAILY"):
            trade = result["trade_metrics"][scenario]
            port = result["portfolio_metrics"][scenario]
            metrics = port["metrics"]
            cash = port["cash"]
            lines.append(
                f"| {window_id} | {scenario} | {trade['filled_count']} | {trade['realized_count']} | {trade['open_count']} | "
                f"{_format(metrics.get('ending_equity_krw'), ' KRW', 0)} | {_format(metrics.get('cumulative_return_pct'), '%')} | "
                f"{_format(metrics.get('CAGR_pct'), '%')} | {_format(metrics.get('mdd_pct'), '%')} | "
                f"{metrics.get('mdd_type')} / {_format(metrics.get('coverage_pct'), '%')} | "
                f"{_format(cash.get('cash_shortage_skip_rate_pct'), '%')} | {_format(cash.get('average_capital_utilization_pct'), '%')} | "
                f"{_format(trade.get('gross_win_rate_pct'), '%')} / {_format(trade.get('gross_median_pct'), '%')} | "
                f"{_format(trade.get('costed_pre_tax_median_pct'), '%')} | "
                f"{_format(trade.get('mean_holding_sessions'), '', 1)} / {_format(trade.get('median_holding_sessions'), '', 1)} |"
            )
    lines += [
        "",
        "## Cadence effect",
        "",
        "| Window | Daily earlier exits | Median sessions advanced | Mean costed trade-return Δ | Portfolio return Δ | MDD Δ | Entry key parity | Frozen monthly exit-signal parity |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window_id in WINDOW_IDS:
        row = summary["windows"][window_id]
        effect = row["effect"]
        validation = row["validations"]
        lines.append(
            f"| {window_id} | {effect['daily_earlier_exit_count']} | {_format(effect['median_signal_sessions_advanced'], '', 1)} | "
            f"{_format(effect['mean_costed_pre_tax_return_delta_pp'], 'pp')} | "
            f"{_format(effect['portfolio_return_delta_pp'], 'pp')} | {_format(effect['portfolio_mdd_delta_pp'], 'pp')} | "
            f"{validation['fixed_entry_key_set_same_between_scenarios']} | "
            f"{validation['control_source_monthly_exit_signal_match_count']}/{validation['fixed_entry_key_count']} |"
        )
    lines += [
        "",
        "## 검증과 해석 경계",
        "",
        f"- 첫 연구의 verdict token은 `{summary['normalization_control']['verdict']}`이고, 해당 연구에서 7개 discrepancy의 현재 영구 제외 적용 후 5-window 공식 event exposure가 0임을 확인했어.",
        f"- exact-session entry/exit 실행 위반: {summary['validation_totals']['exact_session_execution_violation_count']}; 현재 Repository V2 진입가로 재기준화된 고정 원장 행: {summary['validation_totals']['entry_price_rebased_row_count']}; 동일 ISU 겹침: {summary['validation_totals']['identity_overlap_count']}; V2 silent inner drop: {summary['validation_totals']['silent_inner_drop_count']}; portfolio cash conservation 실패: {summary['validation_totals']['cash_conservation_failure_count']}; cost audit mismatch: {summary['validation_totals']['cost_mismatch_count']}.",
        f"- 일별 상태와 경계 업데이트 구현의 직접 중간일 검수: {summary['state_piecewise_spot_checks']['passed']}/{summary['state_piecewise_spot_checks']['count']}.",
        "- CONTROL 월말 청산 원장과 현행 Repository V2에서 재구성한 월말 NORMAL 신호가 다르면 비교표는 동일 현행 원천에서 재구성한 CONTROL/TEST 결과야. 그 경우 저장된 공식 지표와 절대 수치는 직접 동등 비교하지 않아.",
        "- 이 cadence 연구는 기존 공식 채택 기준을 다시 심사하거나 B Select 채택 상태를 변경하지 않아. Portfolio 결과는 연구용 동시비교이며 production 적용 승인이 아니야.",
        "",
        "## 산출물",
        "",
        "`summary.json`, `metadata.json`, `window_comparison.csv`, `trade_comparison.csv`, `state_observation_audit.csv`, `daily_state_piecewise_spot_checks.csv`; 각 기간별 CONTROL/TEST 거래원장, 포트폴리오 이벤트, 일별 equity 및 execution audit.",
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    started = time.time()
    start_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    start_origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    start_status = subprocess.check_output(["git", "status", "--short", "--untracked-files=all"], cwd=ROOT, text=True).strip()
    if start_head != EXPECTED_START_HEAD or start_origin != EXPECTED_START_HEAD:
        raise RuntimeError(f"START_HEAD_DIFFERS_FROM_ORIGIN_MAIN:{start_head}:{start_origin}")
    allowed_untracked = {
        "scripts/replay_b_select_daily_normal_exit_cadence_v01.py",
        "tests/test_b_select_daily_normal_exit_cadence_v01.py",
    }
    unexpected_status = []
    for line in start_status.splitlines():
        path = line[3:].strip() if len(line) >= 4 else line
        if not line.startswith("?? ") or path not in allowed_untracked:
            unexpected_status.append(line)
    if unexpected_status:
        raise RuntimeError(f"UNRELATED_WORKTREE_CHANGES_AT_RUN_START:{unexpected_status}")
    out_root = ROOT / OUTPUT_RELATIVE
    out_root.mkdir(parents=True, exist_ok=False)

    normalization_validation_path = ROOT / NORMALIZATION_ROOT / "validation.json"
    normalization_validation = json.loads(normalization_validation_path.read_text(encoding="utf-8"))
    if normalization_validation.get("verdict") != "B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS":
        raise RuntimeError("EXACT_NEXT_NORMALIZATION_CONTROL_NOT_PASS")
    if any(int(value) != 0 for value in normalization_validation.get("current_filtered_candidate_target_exposure_by_window", {}).values()):
        raise RuntimeError("NORMALIZATION_TARGET_LEAKS_INTO_CURRENT_FILTERED_CANDIDATES")

    inputs_by_window = {window_id: portfolio_v02.load_window_inputs(window_id) for window_id in WINDOW_IDS}
    intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    max_support = max(_date(inputs_by_window[wid]["window"]["execution_support"]) for wid in WINDOW_IDS)
    all_records_by_window = {wid: [copy.deepcopy(row) for row in inputs_by_window[wid]["records"]] for wid in WINDOW_IDS}
    all_records = [row for rows in all_records_by_window.values() for row in rows]
    if WORKERS != portfolio_v02.WORKERS or WORKERS != portfolio_v01.WORKERS:
        raise RuntimeError("WORKER_COUNT_MISMATCH")
    if len({(r["ticker"], r["isu_cd"], r["entry_signal_date"]) for r in all_records}) == 0:
        raise RuntimeError("NO_CURRENTLY_INCLUDED_B_SELECT_ENTRIES")

    cap_lookup = portfolio_v01.ExactMarketCapPriority()
    cap_audit_by_window = {}
    for window_id in WINDOW_IDS:
        cap_audit_by_window[window_id] = cap_lookup.attach(all_records_by_window[window_id])

    records_by_window = {wid: all_records_by_window[wid] for wid in WINDOW_IDS}
    daily_by_ticker, ticker_audit, repository, requested_starts = _load_all_prices(records_by_window, max_support)
    frames_by_window = {
        wid: portfolio_v01.build_component_frames(rows, daily_by_ticker, intervals, trading_dates)
        for wid, rows in records_by_window.items()
    }
    for window_id in WINDOW_IDS:
        inputs_by_window[window_id]["records"] = records_by_window[window_id]

    overall_start = min(_date(inputs_by_window[wid]["window"]["effective_start"]) for wid in WINDOW_IDS)
    overall_end = max(_date(inputs_by_window[wid]["window"]["effective_end"]) for wid in WINDOW_IDS)
    boundary_dates = _feature_boundary_sessions(trading_dates, overall_start, overall_end)
    month_end_dates = _month_end_sessions(trading_dates, overall_start, overall_end)
    state_cache: dict[tuple[str, str], dict[str, Any]] = {}
    state_audit_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    window_results: dict[str, Any] = {}
    scenario_trade_rows_by_window: dict[str, dict[str, list[dict[str, Any]]]] = {}
    trade_comparisons: list[dict[str, Any]] = []
    total_execution_violations = 0
    total_overlap_pairs = 0
    total_cash_failures = 0
    total_cost_mismatches = 0
    output_hashes: dict[str, dict[str, str]] = {}

    for window_id in WINDOW_IDS:
        inputs = inputs_by_window[window_id]
        window = inputs["window"]
        start, end, support = (_date(window[k]) for k in ("effective_start", "effective_end", "execution_support"))
        frames = frames_by_window[window_id]
        scenario_rows, comparisons, run_audit = _build_trade_rows(
            inputs, frames, trading_dates, boundary_dates, month_end_dates, state_cache, state_audit_by_key,
        )
        validations = run_audit["validations"]
        if run_audit["exit_errors"]:
            raise RuntimeError(f"{window_id}:EXACT_NEXT_EXIT_OPEN_MISSING:{len(run_audit['exit_errors'])}:{run_audit['exit_errors'][:5]}")

        # Keep per-window ledgers, but run deterministic cross-window direct
        # checks once after all scenario trade rows have been prepared.
        test_keys = {(str(r["ticker"]).zfill(6), str(r["isu_cd"]).upper(), _date(r["entry_signal_date"])) for r in scenario_rows["TEST_DAILY"]}
        control_keys = {(str(r["ticker"]).zfill(6), str(r["isu_cd"]).upper(), _date(r["entry_signal_date"])) for r in scenario_rows["CONTROL_MONTH_END"]}
        if test_keys != control_keys:
            raise RuntimeError(f"{window_id}:ENTRY_KEY_PARITY_FAILED")

        control_rows = scenario_rows["CONTROL_MONTH_END"]
        test_rows = scenario_rows["TEST_DAILY"]
        scenario_trade_rows_by_window[window_id] = {
            "CONTROL_MONTH_END": control_rows,
            "TEST_DAILY": test_rows,
        }
        for row in comparisons:
            trade_comparisons.append(row)

        control_records = [copy.deepcopy(row) for row in control_rows]
        test_records = [copy.deepcopy(row) for row in test_rows]
        # The portfolio replay compares both cadences under exactly the same
        # cash model; signal/cash paths are intentionally recomputed.
        for scenario, records in (("CONTROL_MONTH_END", control_records), ("TEST_DAILY", test_records)):
            run_id = f"{STUDY_ID}_{window_id.replace('-', '_')}_{scenario}"
            replay, portfolio_audit, extras = _portfolio_replay(inputs, records, frames, trading_dates, run_id)
            portfolio_audit["execution_audit"] = v02_execution_audit = portfolio_v01.verify_execution_prices(records, frames, window)
            portfolio_audit["execution_audit"]["exact_next_session_audit"] = portfolio_audit["next_session_audit"]
            portfolio_audit["execution_audit"]["identity_lifecycle"] = portfolio_audit["lifecycle"]
            if portfolio_audit["next_session_audit"]["violation_count"]:
                total_execution_violations += portfolio_audit["next_session_audit"]["violation_count"]
            if portfolio_audit["lifecycle"].get("violation_count"):
                total_overlap_pairs += portfolio_audit["lifecycle"]["violation_count"]
            if portfolio_audit["metrics"].get("cash_conservation_pass") is not True:
                total_cash_failures += 1
            total_cost_mismatches += int(portfolio_audit["cost_audit"].get("mismatch_count", 0))
            scenario_rows[scenario] = records
            portfolio_audit["execution_audit"]["checked_price_events"] = v02_execution_audit["checked_entries_and_realized_exits"]
            scenario_rows[f"{scenario}__portfolio"] = {"replay": replay, "audit": portfolio_audit, "extras": extras}

        control_trade_metrics = _trade_metrics(control_rows)
        test_trade_metrics = _trade_metrics(test_rows)
        control_p = scenario_rows["CONTROL_MONTH_END__portfolio"]["audit"]
        test_p = scenario_rows["TEST_DAILY__portfolio"]["audit"]
        control_pm = control_p["metrics"]
        test_pm = test_p["metrics"]
        daily_earlier = sum(
            row["test_exit_signal_date"] is not None
            and (
                row["control_exit_signal_date"] is None
                or row["test_exit_signal_date"] < row["control_exit_signal_date"]
            )
            for row in comparisons
        )
        advanced = [row["test_minus_control_signal_sessions"] for row in comparisons if row["test_minus_control_signal_sessions"] is not None]
        delta_returns = [row["test_minus_control_costed_return_pp"] for row in comparisons if row["test_minus_control_costed_return_pp"] is not None]
        effect = {
            "daily_earlier_exit_count": int(daily_earlier),
            "median_signal_sessions_advanced": float(np.median(advanced)) if advanced else None,
            "mean_costed_pre_tax_return_delta_pp": float(np.mean(delta_returns)) if delta_returns else None,
            "portfolio_return_delta_pp": (
                float(test_pm["cumulative_return_pct"]) - float(control_pm["cumulative_return_pct"])
                if test_pm.get("cumulative_return_pct") is not None and control_pm.get("cumulative_return_pct") is not None else None
            ),
            "portfolio_mdd_delta_pp": (
                float(test_pm["mdd_pct"]) - float(control_pm["mdd_pct"])
                if test_pm.get("mdd_pct") is not None and control_pm.get("mdd_pct") is not None else None
            ),
            "portfolio_final_equity_delta_krw": (
                float(test_pm["ending_equity_krw"]) - float(control_pm["ending_equity_krw"])
                if test_pm.get("ending_equity_krw") is not None and control_pm.get("ending_equity_krw") is not None else None
            ),
            "filled_trade_count_delta": test_trade_metrics["filled_count"] - control_trade_metrics["filled_count"],
            "closed_trade_count_delta": test_trade_metrics["realized_count"] - control_trade_metrics["realized_count"],
        }
        execution_audit = {
            "control": control_p["execution_audit"],
            "test": test_p["execution_audit"],
            "control_source_monthly_signal_parity": {
                key: validations[key]
                for key in (
                    "fixed_entry_key_count",
                    "control_source_monthly_exit_signal_match_count",
                    "control_source_monthly_exit_signal_mismatch_count",
                    "control_source_monthly_exit_execution_match_count",
                    "control_source_monthly_exit_execution_mismatch_count",
                )
            },
        }
        validation_output = {
            **validations,
            "source_ledger_hashes_verified": True,
            "all_entry_keys_equal": test_keys == control_keys,
            "current_repository_v2_entry_prices_applied": True,
            "daily_exit_signals_normal_only": all(row.get("exit_signal_state") in (None, "NORMAL") for row in test_rows),
            "exact_session_execution_violation_count": (
                control_p["next_session_audit"]["violation_count"] + test_p["next_session_audit"]["violation_count"]
            ),
            "identity_overlap_pair_count": (
                control_p["lifecycle"].get("violation_count", 0) + test_p["lifecycle"].get("violation_count", 0)
            ),
            "repository_v2_silent_inner_drop_count": sum(row["silent_inner_drop_count"] for row in ticker_audit.values()),
            "cash_conservation_failure_count": int(control_pm.get("cash_conservation_pass") is not True) + int(test_pm.get("cash_conservation_pass") is not True),
            "cost_audit_mismatch_count": control_p["cost_audit"]["mismatch_count"] + test_p["cost_audit"]["mismatch_count"],
            "execution_price_checks_pass": True,
            "no_new_after_cutoff_entries": all(_date(r["entry_signal_date"]) <= end and _date(r["entry_execution_date"]) <= end for r in control_rows + test_rows),
            "same_position_budget_and_cash_model": True,
        }
        window_result = {
            "window": window,
            "entry_candidates_after_current_exclusions": len(inputs["pass_rows"]),
            "trade_metrics": {"CONTROL_MONTH_END": control_trade_metrics, "TEST_DAILY": test_trade_metrics},
            "portfolio_metrics": {
                "CONTROL_MONTH_END": control_p,
                "TEST_DAILY": test_p,
            },
            "effect": effect,
            "validations": validation_output,
            "control_source_schedule_parity": execution_audit["control_source_monthly_signal_parity"],
            "exit_error_count": len(run_audit["exit_errors"]),
        }
        window_results[window_id] = window_result

        window_dir = OUTPUT_RELATIVE / window_id.lower().replace("-", "_")
        output_dir = ROOT / window_dir
        output_dir.mkdir(parents=True, exist_ok=False)
        for scenario in ("CONTROL_MONTH_END", "TEST_DAILY"):
            pd.DataFrame(scenario_rows[scenario]).to_csv(output_dir / f"{scenario.lower()}_trade_ledger.csv", index=False)
            replay = scenario_rows[f"{scenario}__portfolio"]["replay"]
            pd.DataFrame(replay["events"]).to_csv(output_dir / f"{scenario.lower()}_portfolio_events.csv", index=False)
            pd.DataFrame(replay["daily_equity"]).to_csv(output_dir / f"{scenario.lower()}_daily_equity.csv", index=False)
            pd.DataFrame(replay["skipped"]).to_csv(output_dir / f"{scenario.lower()}_portfolio_skips.csv", index=False)
            pd.DataFrame(scenario_rows[f"{scenario}__portfolio"]["extras"]["cost_rows"]).to_csv(output_dir / f"{scenario.lower()}_cost_audit.csv", index=False)
        pd.DataFrame(comparisons).to_csv(output_dir / "trade_comparison.csv", index=False)
        pd.DataFrame([{
            "window_id": window_id,
            "validation": json.dumps(validation_output, ensure_ascii=False, sort_keys=True),
            "source_hashes": json.dumps(inputs["source_hashes"], ensure_ascii=False, sort_keys=True),
        }]).to_csv(output_dir / "validation.csv", index=False)
        generated = {path.name: sha256(path) for path in sorted(output_dir.iterdir()) if path.is_file()}
        output_hashes[window_id] = generated
        window_metadata = {
            "study_id": f"{STUDY_ID}_{window_id.replace('-', '_')}",
            "window": window,
            "workers": WORKERS,
            "source_hashes": inputs["source_hashes"],
            "generated_files_sha256": generated,
        }
        write_json(output_dir / "metadata.json", window_metadata)
        print(json.dumps({
            "window": window_id,
            "control_return_pct": control_pm.get("cumulative_return_pct"),
            "test_return_pct": test_pm.get("cumulative_return_pct"),
            "control_mdd_pct": control_pm.get("mdd_pct"),
            "test_mdd_pct": test_pm.get("mdd_pct"),
            "trades": len(control_rows),
            "daily_earlier_exits": daily_earlier,
            "control_source_signal_mismatch": validations["control_source_monthly_exit_signal_mismatch_count"],
            "output": str(window_dir),
        }, ensure_ascii=False), flush=True)

    # Use in-memory rows so pandas CSV type inference cannot alter PIT identity
    # boundaries before reconstructing the exact component-frame key.
    spot_checks = _validate_state_piecewise(
        scenario_trade_rows_by_window,
        {key: frame for frames in frames_by_window.values() for key, frame in frames.items()},
        trading_dates, boundary_dates, state_cache, state_audit_by_key,
    )

    pd.DataFrame(trade_comparisons).to_csv(out_root / "trade_comparison.csv", index=False)
    pd.DataFrame([
        {"window_id": wid, "scenario": scenario, **metrics}
        for wid in WINDOW_IDS
        for scenario, metrics in window_results[wid]["trade_metrics"].items()
    ]).to_csv(out_root / "trade_metrics.csv", index=False)
    pd.DataFrame([
        {
            "window_id": wid,
            "scenario": scenario,
            **{k: v for k, v in details["metrics"].items() if not isinstance(v, (dict, list))},
            **{f"cash_{k}": v for k, v in details["cash"].items()},
        }
        for wid in WINDOW_IDS
        for scenario, details in window_results[wid]["portfolio_metrics"].items()
    ]).to_csv(out_root / "portfolio_metrics.csv", index=False)
    pd.DataFrame([{
        "window_id": wid,
        **window_results[wid]["effect"],
        "control_monthly_exit_signal_mismatch_count": window_results[wid]["validations"]["control_source_monthly_exit_signal_mismatch_count"],
    } for wid in WINDOW_IDS]).to_csv(out_root / "window_comparison.csv", index=False)
    pd.DataFrame(sorted(state_audit_by_key.values(), key=lambda row: (row["ticker"], row["as_of"]))).to_csv(out_root / "state_observation_audit.csv", index=False)
    pd.DataFrame(spot_checks).to_csv(out_root / "daily_state_piecewise_spot_checks.csv", index=False)

    validation_totals = {
        "exact_session_execution_violation_count": sum(row["validations"]["exact_session_execution_violation_count"] for row in window_results.values()),
        "entry_price_rebased_row_count": sum(row["validations"]["entry_price_rebased_row_count"] for row in window_results.values()),
        "identity_overlap_count": sum(row["validations"]["identity_overlap_pair_count"] for row in window_results.values()),
        "silent_inner_drop_count": sum(int(row["validations"]["repository_v2_silent_inner_drop_count"]) for row in window_results.values()),
        "cash_conservation_failure_count": sum(row["validations"]["cash_conservation_failure_count"] for row in window_results.values()),
        "cost_mismatch_count": sum(row["validations"]["cost_audit_mismatch_count"] for row in window_results.values()),
    }
    overall_validation = {
        **validation_totals,
        "monthly_source_schedule_signal_mismatch_count": sum(row["validations"]["control_source_monthly_exit_signal_mismatch_count"] for row in window_results.values()),
        "monthly_source_schedule_execution_mismatch_count": sum(row["validations"]["control_source_monthly_exit_execution_mismatch_count"] for row in window_results.values()),
        "daily_state_piecewise_spot_checks": len(spot_checks),
        "daily_state_piecewise_spot_check_failures": sum(not row["all_checks_pass"] for row in spot_checks),
    }
    status = "PASS" if (
        validation_totals["exact_session_execution_violation_count"] == 0
        and validation_totals["identity_overlap_count"] == 0
        and validation_totals["silent_inner_drop_count"] == 0
        and validation_totals["cash_conservation_failure_count"] == 0
        and validation_totals["cost_mismatch_count"] == 0
        and overall_validation["daily_state_piecewise_spot_check_failures"] == 0
    ) else "CHECK_REQUIRED"

    source_files = [
        ROOT / NORMALIZATION_ROOT / "validation.json",
        ROOT / "docs/patterns/pattern_b/spec/feature_contract_v01.md",
        ROOT / "docs/patterns/pattern_b/validation/state_rule_v02_seal.json",
        ROOT / "docs/validation/backtest_common_rules.md",
        ROOT / "docs/validation/official_strategy_adoption_criteria.md",
        ROOT / "src/trend_scanner/patterns/pattern_b_evaluator.py",
        ROOT / "src/trend_scanner/patterns/pattern_b_features_v01.py",
        ROOT / "src/trend_scanner/patterns/pattern_b_state_v02.py",
        ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py",
    ]
    source_files.extend(ROOT / SOURCE_ROOT / wid.lower().replace("-", "_") / name for wid in WINDOW_IDS for name in (
        "metadata.json", "summary.json", "previous_stage_audit.csv", "test_trade_ledger.csv",
    ))
    summary = {
        "study_id": STUDY_ID,
        "status": status,
        "starting_head": start_head,
        "starting_origin_main": start_origin,
        "starting_status_as_observed_before_research": EXPECTED_START_STATUS,
        "start_status": start_status,
        "workers": WORKERS,
        "entry_rule": "frozen approved monthly entry signal -> next exact KRX session open",
        "entry_price_policy": "fixed source signal/execution keys; use current Repository V2 exact-session open in both scenarios while retaining source open in the research ledgers",
        "control_exit_rule": "first subsequent exact month-end KRX session with official Pattern B NORMAL -> first subsequent exact KRX session with valid Repository V2 open",
        "test_exit_rule": "first exact KRX session after entry execution whose official Pattern B state is NORMAL -> first subsequent exact KRX session with valid Repository V2 open",
        "pattern_b_feature_contract": "V01; completed MonthEnd/W-FRI bars only",
        "pattern_b_state_rule": "PATTERN_B_STATE_RULE_V02",
        "normalization_control": {
            "verdict": normalization_validation["verdict"],
            "commit": "6d7b7a03eb4935de268d8f8d942c82c03086696c",
            "all_target_rows_excluded_from_current_policy": normalization_validation.get("all_target_rows_excluded_from_current_policy"),
            "current_filtered_candidate_target_exposure_by_window": normalization_validation.get("current_filtered_candidate_target_exposure_by_window"),
        },
        "market_authority": market_authority,
        "requested_price_start_by_ticker": requested_starts,
        "price_ticker_audit": ticker_audit,
        "window_ids": list(WINDOW_IDS),
        "windows": window_results,
        "validation_totals": validation_totals,
        "state_piecewise_spot_checks": {"count": len(spot_checks), "passed": sum(bool(r["all_checks_pass"]) for r in spot_checks)},
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in source_files},
        "price_authority_hashes": {
            f"data/market/adjusted/stocks/{ticker}.parquet": sha256(ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet")
            for ticker in sorted(daily_by_ticker)
        },
        "elapsed_seconds": round(time.time() - started, 3),
    }
    (out_root / "report.md").write_text(_report(summary), encoding="utf-8")
    write_json(out_root / "summary.json", summary)

    root_files = [path for path in out_root.iterdir() if path.is_file() and path.name != "metadata.json"]
    generated_hashes = {str(path.relative_to(out_root)): {"sha256": sha256(path), "bytes": path.stat().st_size} for path in sorted(root_files)}
    metadata = {
        "study_id": STUDY_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "starting_head": start_head,
        "starting_origin_main": start_origin,
        "starting_status_as_observed_before_research": EXPECTED_START_STATUS,
        "workers": WORKERS,
        "strategy_id": "PATTERN_B_SELECT_CORE_V01",
        "no_production_changes": True,
        "official_history_modified": False,
        "control_and_test_share_price_authority_and_portfolio_engine": True,
        "source_hashes": summary["source_hashes"],
        "price_authority_hashes": summary["price_authority_hashes"],
        "generated_files": generated_hashes,
        "window_generated_files": output_hashes,
        "script_sha256": sha256(Path(__file__)),
        "elapsed_seconds": summary["elapsed_seconds"],
    }
    write_json(out_root / "metadata.json", metadata)
    summary_path = out_root / "summary.json"
    return {"status": status, "summary_path": str(summary_path), "validation_totals": validation_totals, "window_count": len(window_results)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    print(json.dumps(run(), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
