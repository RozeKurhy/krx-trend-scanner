#!/usr/bin/env python3
"""Independently reproduce four frozen strategies on KODEX 200.

This is a research-only runner.  It reads the explicitly non-canonical ETF
price-return parquet, calls the repository's frozen strategy engines/contracts,
and writes auditable matched, sequential, and daily equity artifacts.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import argparse
import json
import math
import socket
import sys
from typing import Any, Iterator, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_v3_simple_v00 as v3
from scripts import run_fastcore_v4_matched_ab_official_v01 as v4
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.backtest.raw_investability_panel import (
    evaluate_entry_filter,
    recompute_identity_scoped_avg_trading_value_20d,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022


TICKER = "069500"
NAME = "KODEX 200"
MARKET = "ETF"
DATA_PATH = ROOT / "data/raw/stocks/069500.parquet"
OUT_DIR = ROOT / "artifacts/research/kodex200_four_strategy_reproduction_v01"
MATCHED_PATH = OUT_DIR / "matched_trades.csv"
SEQUENTIAL_PATH = OUT_DIR / "sequential_trades.csv"
EQUITY_PATH = OUT_DIR / "daily_equity.csv"
SUMMARY_PATH = OUT_DIR / "summary.json"
REPORT_PATH = OUT_DIR / "report.md"

REQUESTED_START = pd.Timestamp("2014-01-02")
REQUESTED_SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
REQUESTED_SUPPORT_END = pd.Timestamp("2026-08-14")
MARKET_CAP_BYPASS_VALUE = 1_000_000_000_000.0
MIN_AVG_TRADING_VALUE = 300_000_000.0
MIN_CLOSE = 5_000.0
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

STRATEGY_IDS = {
    "V2": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    "V3": "PATTERN_A_FAST_FINAL_STRATEGY_V03",
    "V4": "PATTERN_A_FAST_FINAL_STRATEGY_V04",
    "Julia": "JULIA_STRATEGY_V00",
}

REFERENCE = {
    "common_entry_count": 35,
    "sequential_trade_count": {"V2": 4, "V3": 3, "V4": 4, "Julia": 2},
    "cagr_pct": {"V2": 8.08, "V3": 11.76, "V4": 7.72, "Julia": 11.55, "Buy & Hold": 11.88},
    "total_return_pct": {"V2": 166.54, "V3": 306.33, "V4": 155.35, "Julia": 296.86, "Buy & Hold": 311.90},
    "mdd_pct": {"V2": -40.65, "V3": -39.60, "V4": -39.60, "Julia": -40.65, "Buy & Hold": -40.93},
}


class NetworkRequestBlocked(RuntimeError):
    """Raised if the offline reproduction attempts a socket connection."""


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline KODEX200 guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline KODEX200 guard blocked socket connect_ex: {address!r}")

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


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def load_price_authority() -> tuple[pd.DataFrame, dict[str, Any]]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"ETF price authority is missing: {DATA_PATH}")
    frame = pd.read_parquet(DATA_PATH).sort_index()
    required = {"open", "high", "low", "close", "volume", "trading_value"}
    if not required.issubset(frame.columns):
        raise AssertionError(f"ETF parquet columns are incomplete: {sorted(frame.columns)}")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise AssertionError("ETF parquet index must be a unique DatetimeIndex")
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index()
    numeric = frame.loc[:, sorted(required)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(math.isfinite).all().all():
        raise AssertionError("ETF parquet contains non-finite required values")
    actual_start = _date(frame.index.min())
    actual_end = _date(frame.index.max())
    evaluation_start = max(REQUESTED_START, actual_start)
    final_date = min(REQUESTED_SUPPORT_END, REQUESTED_SIGNAL_CUTOFF, actual_end)
    if evaluation_start > final_date:
        raise AssertionError("ETF parquet has no usable evaluation range")
    clipped = frame.loc[(frame.index >= actual_start) & (frame.index <= final_date)].copy()
    meta = {
        "path": str(DATA_PATH.relative_to(ROOT)),
        "classification": "NON_CANONICAL",
        "return_basis": "PRICE_RETURN_ONLY",
        "distribution_reinvestment": False,
        "rows": len(frame),
        "actual_start": actual_start.strftime("%Y-%m-%d"),
        "actual_end": actual_end.strftime("%Y-%m-%d"),
        "evaluation_start": evaluation_start.strftime("%Y-%m-%d"),
        "signal_cutoff": final_date.strftime("%Y-%m-%d"),
        "execution_support_end": final_date.strftime("%Y-%m-%d"),
        "final_valuation": f"{final_date.strftime('%Y-%m-%d')} CLOSE",
    }
    return clipped, meta


def _contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    return _json_read(SCORE_CONTRACT_PATH), _json_read(STAGE_CONTRACT_PATH)


def _raw_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """Build the research-only panel used by frozen engines.

    The ETF parquet has no historical market-cap authority.  Market cap is
    therefore a sentinel only to exercise the existing engine entry path; it
    is never reported as an observed ETF market-cap value.  Close and
    trading_value remain the actual price-file observations.
    """
    panel = daily.loc[:, ["close", "trading_value"]].copy()
    panel["market_cap"] = MARKET_CAP_BYPASS_VALUE
    return recompute_identity_scoped_avg_trading_value_20d(panel)


def _valid_fast(result: Mapping[str, Any]) -> bool:
    return bool(
        result.get("fast_machine_stage") == "TRIGGER"
        and result.get("fast_machine_stage_status") == "READY"
        and result.get("fast_monthly_permission_state") == "PERMITTED_REGIME"
        and result.get("fast_daily_risk_state") in {"NORMAL", "ELEVATED"}
        and result.get("fast_score_status") in {"READY", "PARTIAL"}
        and str(result.get("pattern_a_stage") or "").upper() in {"TRANSITION", "EARLY_TREND"}
    )


def scan_common_entries(
    daily: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[tuple[pd.Timestamp, str]], dict[str, Any]]:
    end = _date(daily.index.max())
    daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
    weekly = context.weekly_up_to(end)
    valid_weeks = [
        _date(value)
        for value in weekly.index
        if _date(value) in daily_dates and _date(value) >= _date(daily.index.min()) and _date(value) <= end
    ]
    panel = _raw_panel(daily)
    states: list[tuple[pd.Timestamp, str]] = []
    signals: list[dict[str, Any]] = []
    evaluation_errors = 0
    filtered_candidates = 0
    for week in valid_weeks:
        try:
            result = evaluate_pattern_a_fast(
                TICKER, NAME, daily, week, score_contract, stage_contract, context=context,
            )
        except Exception:
            evaluation_errors += 1
            continue
        fast_state = str(result.get("fast_machine_stage") or "UNAVAILABLE").upper()
        if result.get("fast_machine_stage_status") != "READY":
            fast_state = "UNAVAILABLE"
        states.append((week, fast_state))
        if not _valid_fast(result):
            continue
        filtered_candidates += 1
        filt = evaluate_entry_filter(
            panel,
            week,
            market_cap_threshold=0.0,
            avg_trading_value_threshold=MIN_AVG_TRADING_VALUE,
            close_threshold=MIN_CLOSE,
        )
        if not bool(filt["entry_filter_pass"]):
            raise AssertionError(f"unexpected ETF price/liquidity rejection at {week.date()}: {filt}")
        future = daily.loc[daily.index > week]
        if future.empty:
            continue
        info_date = daily.index[daily.index <= week][-1]
        entry_date = _date(future.index[0])
        signals.append({
            "signal_id": f"{TICKER}|{week.strftime('%Y-%m-%d')}",
            "identity_key": f"{TICKER}|ETF_PRICE_ONLY|{MARKET}",
            "ticker": TICKER,
            "name": NAME,
            "market": MARKET,
            "isu_cd": "ETF_PRICE_ONLY",
            "signal_date": week.strftime("%Y-%m-%d"),
            "signal_information_date": _date(info_date).strftime("%Y-%m-%d"),
            "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
            "entry_open": float(daily.loc[entry_date, "open"]),
            "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
            "fast_machine_stage": result.get("fast_machine_stage"),
            "fast_machine_stage_status": result.get("fast_machine_stage_status"),
            "monthly_permission_state": result.get("fast_monthly_permission_state"),
            "daily_risk_state": result.get("fast_daily_risk_state"),
            "fast_score": result.get("fast_score"),
            "fast_score_status": result.get("fast_score_status"),
            "market_cap": MARKET_CAP_BYPASS_VALUE,
            "market_cap_source": "ETF_PRICE_ONLY_MARKET_CAP_BYPASS",
            "identity_effective_from": _date(daily.index.min()).strftime("%Y-%m-%d"),
            "identity_effective_to": end.strftime("%Y-%m-%d"),
        })
    signals.sort(key=lambda row: (row["signal_date"], row["signal_id"]))
    meta = {
        "weekly_reference_date_count": len(valid_weeks),
        "weekly_evaluation_error_count": evaluation_errors,
        "raw_fast_signal_candidates": filtered_candidates,
        "common_entry_count": len(signals),
        "market_cap_gate": "BYPASSED_ETF_NO_HISTORICAL_MARKET_CAP_AUTHORITY",
        "price_filter_applied": True,
        "liquidity_filter_applied": True,
    }
    if evaluation_errors:
        raise AssertionError(f"weekly FAST evaluation errors: {evaluation_errors}")
    return signals, states, meta


class _EtfMarketCapBypassRegistry:
    """Adapter for the frozen Julia engine's existing registry extension point."""

    def get_market_cap_at_reference(self, ticker: str, reference_date: str, sensitivity_mode: bool = False) -> tuple[float, dict[str, Any]]:
        return MARKET_CAP_BYPASS_VALUE, {
            "source_role": "ETF_PRICE_ONLY_MARKET_CAP_BYPASS",
            "authority_status": "NON_CANONICAL_RESEARCH_EXCEPTION",
            "reference_date": str(reference_date),
        }


def _v2_kwargs(
    daily: pd.DataFrame,
    panel: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    allowed_signal_dates: set[pd.Timestamp] | None,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, Any]:
    return {
        "strategy_id": STRATEGY_IDS["V2"],
        "ticker": TICKER,
        "isu_cd": "ETF_PRICE_ONLY",
        "name": NAME,
        "market": MARKET,
        "daily": daily,
        "raw_panel": panel,
        "score_contract": score_contract,
        "stage_contract": stage_contract,
        "loss_guard_enabled": True,
        "backtest_end": end_date,
        "entry_eligible_from": start_date,
        "allowed_signal_dates": allowed_signal_dates,
        "snapshot_context": context,
    }


def _julia_kwargs(
    daily: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, Any]:
    return {
        "ticker": TICKER,
        "name": NAME,
        "market": MARKET,
        "daily": daily,
        "score_contract": score_contract,
        "stage_contract": stage_contract,
        "enable_loss_guard": False,
        "market_cap_registry": _EtfMarketCapBypassRegistry(),
        "start_date": start_date,
        "cutoff_date": end_date,
        "min_market_cap_krw": 100_000_000_000.0,
        "snapshot_context": context,
    }


def _date_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _date(value).strftime("%Y-%m-%d")


def _holding_days(daily: pd.DataFrame, entry: str, exit_date: str | None, final_date: pd.Timestamp) -> int:
    end = _date(exit_date) if exit_date else final_date
    return int(len(daily.loc[(daily.index >= _date(entry)) & (daily.index <= end)]))


def _normalise_engine_trade(record: Any, strategy: str, daily: pd.DataFrame, final_date: pd.Timestamp) -> dict[str, Any]:
    row = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    entry_signal = _date_or_none(row.get("entry_signal_date"))
    entry_execution = _date_or_none(row.get("entry_execution_date"))
    exit_signal = _date_or_none(row.get("exit_signal_date"))
    exit_execution = _date_or_none(row.get("exit_execution_date"))
    status = str(row.get("trade_status") or "OPEN_AT_CUTOFF")
    terminal_return = float(row.get("terminal_return"))
    mfe = float(row.get("mfe"))
    mae = float(row.get("mae"))
    return {
        "strategy": strategy,
        "ticker": TICKER,
        "entry_signal_date": entry_signal,
        "entry_execution_date": entry_execution,
        "entry_price": float(row["entry_open"]),
        "exit_signal_date": exit_signal,
        "exit_execution_date": exit_execution,
        "exit_price": None if row.get("exit_price") is None or pd.isna(row.get("exit_price")) else float(row["exit_price"]),
        "exit_reason": str(row.get("exit_type") or "OPEN_AT_CUTOFF"),
        "trade_status": status,
        "terminal_return_pct": terminal_return,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "holding_days": int(row.get("holding_trading_days") or _holding_days(daily, entry_execution, exit_execution, final_date)),
        "peak_giveback_pct": round(float(row.get("peak_giveback") or (mfe - terminal_return)), 6),
        "trade_no": int(row.get("trade_sequence") or 0),
        "strategy_id": str(row.get("strategy_id") or STRATEGY_IDS[strategy]),
    }


def _v3_row(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **signal,
        "signal_date": signal["signal_date"],
        "identity_key": signal["identity_key"],
    }


def _normalise_v3_trade(row: Mapping[str, Any], strategy: str, final_date: pd.Timestamp) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "ticker": TICKER,
        "entry_signal_date": str(row["entry_signal_date"]),
        "entry_execution_date": str(row["entry_execution_date"]),
        "entry_price": float(row["entry_open"]),
        "exit_signal_date": row.get("exit_signal_date"),
        "exit_execution_date": row.get("exit_execution_date"),
        "exit_price": row.get("exit_price"),
        "exit_reason": str(row.get("exit_reason") or "OPEN_AT_CUTOFF"),
        "trade_status": str(row["trade_status"]),
        "terminal_return_pct": float(row["terminal_return"]),
        "mfe_pct": float(row["mfe"]),
        "mae_pct": float(row["mae"]),
        "holding_days": int(row["holding_trading_days"]),
        "peak_giveback_pct": round(float(row["mfe"]) - float(row["terminal_return"]), 6),
        "trade_no": int(row["trade_sequence"]),
        "strategy_id": STRATEGY_IDS[strategy],
        "final_valuation_date": row.get("final_valuation_date") or final_date.strftime("%Y-%m-%d"),
    }


def _replay_v4(signal: Mapping[str, Any], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], sequence: int, final_date: pd.Timestamp) -> dict[str, Any]:
    entry_date = _date(signal["entry_execution_date"])
    entry_open = float(signal["entry_open"])
    hwm = entry_open
    exit_signal: pd.Timestamp | None = None
    exit_reason: str | None = None
    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        date = _date(date)
        hwm = max(hwm, float(bar["high"]))
        decision, _soft, _hard, _tier = v4.v4_exit_decision(
            mfe_pct=round((hwm / entry_open - 1.0) * 100.0, 10),
            hwm_price=hwm,
            current_close=float(bar["close"]),
            entry_open=entry_open,
            fast_state=v3.latest_fast_state(states, date),
        )
        if decision is not None:
            exit_signal = date
            exit_reason = decision
            break
    exit_execution = v3._next_session(daily, exit_signal) if exit_signal is not None else None
    status = "REALIZED" if exit_execution is not None else "OPEN_AT_CUTOFF"
    exit_price = float(daily.loc[exit_execution, "open"]) if exit_execution is not None else None
    if status == "REALIZED":
        metric_end = exit_signal if exit_signal is not None else exit_execution
        hwm_metric, _trough, mfe, mae = v3._path_metrics(daily, entry_date, metric_end, entry_open, exit_price)
        terminal_return = round((exit_price / entry_open - 1.0) * 100.0, 2)
        valuation_date = exit_execution
    else:
        valuation_date = final_date
        hwm_metric, _trough, mfe, mae = v3._path_metrics(daily, entry_date, valuation_date, entry_open)
        terminal_return = round((float(daily.loc[valuation_date, "close"]) / entry_open - 1.0) * 100.0, 2)
        exit_reason = "OPEN_AT_CUTOFF"
    return {
        "strategy": "V4",
        "ticker": TICKER,
        "entry_signal_date": str(signal["signal_date"]),
        "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "entry_price": entry_open,
        "exit_signal_date": _date_or_none(exit_signal),
        "exit_execution_date": _date_or_none(exit_execution),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "trade_status": status,
        "terminal_return_pct": terminal_return,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "holding_days": _holding_days(daily, entry_date, _date_or_none(exit_execution), final_date),
        "peak_giveback_pct": round(float(mfe) - terminal_return, 6),
        "trade_no": sequence,
        "strategy_id": STRATEGY_IDS["V4"],
        "final_valuation_date": _date_or_none(valuation_date),
        "final_valuation_price": exit_price if status == "REALIZED" else float(daily.loc[final_date, "close"]),
        "hwm_price": hwm_metric,
    }


def _simulate_engine_sequential(
    strategy: str,
    signals: list[dict[str, Any]],
    daily: pd.DataFrame,
    panel: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    start_date: pd.Timestamp,
    final_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    allowed = {_date(row["signal_date"]) for row in signals}
    if strategy == "V2":
        records = simulate_ticker_strategy_fundamentals_v01(**_v2_kwargs(daily, panel, context, score_contract, stage_contract, allowed, start_date, final_date))
        return [_normalise_engine_trade(record, strategy, daily, final_date) for record in records]
    if strategy == "Julia":
        records = simulate_ticker_strategy_2022(**_julia_kwargs(daily, context, score_contract, stage_contract, start_date, final_date))
        return [_normalise_engine_trade(record, strategy, daily, final_date) for record in records]
    raise AssertionError(f"unsupported frozen engine: {strategy}")


def _simulate_v3_sequential(signals: list[dict[str, Any]], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], final_date: pd.Timestamp) -> list[dict[str, Any]]:
    state_map = {signals[0]["identity_key"]: states}
    frame, _meta = v3.simulate_all(pd.DataFrame([_v3_row(row) for row in signals]), state_map, {TICKER: daily})
    return [_normalise_v3_trade(row, "V3", final_date) for row in frame.to_dict("records")]


def _simulate_v4_sequential(signals: list[dict[str, Any]], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], final_date: pd.Timestamp) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_exit: pd.Timestamp | None = None
    for signal in signals:
        signal_date = _date(signal["signal_date"])
        if current_exit is not None and signal_date <= current_exit:
            continue
        trade = _replay_v4(signal, daily, states, len(rows) + 1, final_date)
        rows.append(trade)
        if trade["trade_status"] == "REALIZED":
            current_exit = _date(trade["exit_execution_date"])
        else:
            break
    return rows


def _simulate_engine_matched(
    strategy: str,
    signals: list[dict[str, Any]],
    daily: pd.DataFrame,
    panel: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    final_date: pd.Timestamp,
    states: list[tuple[pd.Timestamp, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, signal in enumerate(signals, 1):
        signal_date = _date(signal["signal_date"])
        if strategy == "V2":
            records = simulate_ticker_strategy_fundamentals_v01(**_v2_kwargs(daily, panel, context, score_contract, stage_contract, {signal_date}, signal_date, final_date))
            if len(records) != 1:
                raise AssertionError(f"V2 common-entry replay failed at {signal_date.date()}: {len(records)} records")
            row = _normalise_engine_trade(records[0], strategy, daily, final_date)
        elif strategy == "Julia":
            records = simulate_ticker_strategy_2022(**_julia_kwargs(daily, context, score_contract, stage_contract, signal_date, final_date))
            if not records:
                raise AssertionError(f"Julia common-entry replay failed at {signal_date.date()}: no records")
            first = _normalise_engine_trade(records[0], strategy, daily, final_date)
            if first["entry_signal_date"] != signal["signal_date"]:
                raise AssertionError(
                    f"Julia common-entry replay diverged at {signal_date.date()}: first entry={first['entry_signal_date']}"
                )
            row = first
        elif strategy == "V3":
            raw = v3.simulate_trade(_v3_row(signal), daily, states, index)
            if raw is None:
                raise AssertionError(f"V3 common-entry replay failed at {signal_date.date()}")
            row = _normalise_v3_trade(raw, strategy, final_date)
        elif strategy == "V4":
            row = _replay_v4(signal, daily, states, index, final_date)
        else:
            raise AssertionError(f"unsupported strategy: {strategy}")
        if row["entry_signal_date"] != signal["signal_date"] or row["entry_execution_date"] != signal["entry_execution_date"]:
            raise AssertionError(f"{strategy} entry identity diverged at {signal_date.date()}: {row}")
        if abs(float(row["entry_price"]) - float(signal["entry_open"])) > 1e-8:
            raise AssertionError(f"{strategy} entry OPEN diverged at {signal_date.date()}")
        rows.append(row)
    return rows


def build_equity_curve(strategy: str, daily: pd.DataFrame, trades: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    cash = 1.0
    units = 0.0
    rows: list[dict[str, Any]] = []
    by_entry = {str(row["entry_execution_date"]): row for row in trades}
    by_exit = {str(row["exit_execution_date"]): row for row in trades if row.get("exit_execution_date")}
    for date, bar in daily.iterrows():
        day = _date(date).strftime("%Y-%m-%d")
        entry = by_entry.get(day)
        if entry is not None:
            if units != 0.0:
                raise AssertionError(f"overlapping {strategy} entry on {day}")
            units = cash / float(entry["entry_price"])
            cash = 0.0
        exit_row = by_exit.get(day)
        if exit_row is not None:
            if units == 0.0:
                raise AssertionError(f"exit without position for {strategy} on {day}")
            cash = units * float(exit_row["exit_price"])
            units = 0.0
        equity = cash + units * float(bar["close"])
        rows.append({
            "date": day,
            "strategy": strategy,
            "equity": round(equity, 10),
            "position_state": "HOLD" if units else "FLAT",
            "exposure_flag": int(bool(units)),
        })
    return pd.DataFrame(rows)


def build_buy_hold_curve(daily: pd.DataFrame) -> pd.DataFrame:
    start_open = float(daily.iloc[0]["open"])
    units = 1.0 / start_open
    equity = [round(float(close) * units, 10) for close in daily["close"]]
    # The position is entered at the first day's OPEN.  The first daily
    # valuation therefore starts at exactly 1.0 rather than at that day's
    # CLOSE-to-OPEN return.
    equity[0] = 1.0
    return pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in daily.index],
        "strategy": "Buy & Hold",
        "equity": equity,
        "position_state": "HOLD",
        "exposure_flag": 1,
    })


def curve_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    equity = pd.to_numeric(curve["equity"], errors="raise")
    start = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    dates = pd.to_datetime(curve["date"], errors="raise")
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1e-12)
    cagr = (final / start) ** (1.0 / years) - 1.0
    drawdown = equity / equity.cummax() - 1.0
    return {
        "total_return_pct": round((final / start - 1.0) * 100.0, 6),
        "cagr_pct": round(cagr * 100.0, 6),
        "mdd_pct": round(float(drawdown.min()) * 100.0, 6),
        "final_equity": round(final, 10),
        "exposure_ratio_pct": round(float(pd.to_numeric(curve["exposure_flag"]).mean()) * 100.0, 6),
    }


def _trade_summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(list(trades))
    if frame.empty:
        return {"trade_count": 0, "exit_reasons": {}, "best_trade": None, "worst_trade": None}
    returns = pd.to_numeric(frame["terminal_return_pct"], errors="raise")
    best = frame.loc[returns.idxmax()].to_dict()
    worst = frame.loc[returns.idxmin()].to_dict()
    return {
        "trade_count": int(len(frame)),
        "closed_trade_count": int((frame["trade_status"] == "REALIZED").sum()),
        "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "mean_return_pct": round(float(returns.mean()), 6),
        "median_return_pct": round(float(returns.median()), 6),
        "exit_reasons": {str(key): int(value) for key, value in Counter(frame["exit_reason"].astype(str)).items()},
        "best_trade": {"entry_signal_date": best["entry_signal_date"], "terminal_return_pct": best["terminal_return_pct"], "exit_reason": best["exit_reason"]},
        "worst_trade": {"entry_signal_date": worst["entry_signal_date"], "terminal_return_pct": worst["terminal_return_pct"], "exit_reason": worst["exit_reason"]},
    }


def _reference_comparison(
    common_entries: list[dict[str, Any]],
    sequential: Mapping[str, Sequence[Mapping[str, Any]]],
    curves: Mapping[str, pd.DataFrame],
    metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(label: str, actual: Any, expected: Any, tolerance: float = 0.0) -> None:
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            passed = abs(float(actual) - float(expected)) <= tolerance
        else:
            passed = actual == expected
        checks.append({"label": label, "actual": actual, "expected": expected, "pass": passed, "tolerance": tolerance})

    check("common_entry_count", len(common_entries), REFERENCE["common_entry_count"])
    for strategy, expected in REFERENCE["sequential_trade_count"].items():
        check(f"{strategy}.sequential_trade_count", len(sequential[strategy]), expected)
    for strategy, expected in REFERENCE["cagr_pct"].items():
        check(f"{strategy}.cagr_pct", metrics[strategy]["cagr_pct"], expected, 0.05)
    for strategy, expected in REFERENCE["total_return_pct"].items():
        check(f"{strategy}.total_return_pct", metrics[strategy]["total_return_pct"], expected, 0.5)
    for strategy, expected in REFERENCE["mdd_pct"].items():
        check(f"{strategy}.mdd_pct", metrics[strategy]["mdd_pct"], expected, 0.5)
    passed = all(bool(item["pass"]) for item in checks)
    first_failed = next((item for item in checks if not item["pass"]), None)
    cause = None
    if first_failed:
        if ".mdd_pct" in first_failed["label"]:
            cause = "EQUITY_CURVE_MARKING_CONVENTION"
        elif ".cagr_pct" in first_failed["label"]:
            cause = "CAGR_DAY_COUNT_OR_EQUITY_CURVE"
        elif ".total_return_pct" in first_failed["label"]:
            cause = "PRICE_LOOKUP_OR_EQUITY_COMPOUNDING"
        else:
            cause = "ENTRY_OR_EXIT_PATH_DIFFERENCE"
    return {
        "reference": REFERENCE,
        "checks": checks,
        "all_reference_metrics_match": passed,
        "first_divergence": {
            "label": first_failed["label"],
            "cause": cause,
        } if first_failed else None,
    }


def _markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("" if row.get(column) is None else str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _build_report(summary: Mapping[str, Any], sequential: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    strategy_rows = []
    for strategy in ("V2", "V3", "V4", "Julia", "Buy & Hold"):
        item = summary["strategies"][strategy]
        strategy_rows.append({
            "strategy": strategy,
            "total_return_pct": item.get("total_return_pct"),
            "cagr_pct": item.get("cagr_pct"),
            "mdd_pct": item.get("mdd_pct"),
            "trade_count": item.get("trade_count", "N/A"),
            "exposure_ratio_pct": item.get("exposure_ratio_pct"),
        })
    exit_rows = []
    for strategy in ("V2", "V3", "V4", "Julia"):
        for reason, count in summary["sequential_trade_summaries"][strategy]["exit_reasons"].items():
            exit_rows.append({"strategy": strategy, "exit_reason": reason, "count": count})
    lines = [
        "# KODEX 200 Four Strategy Independent Reproduction V01",
        "",
        "## 판정",
        "",
        f"- 최종 판정: `{summary['verdict']}`",
        f"- 상태: `{summary['status']}`",
        f"- 네트워크 요청: `{summary['network_requests']}`",
        "",
        "## 데이터 계약",
        "",
        f"- source: `{summary['data']['path']}`",
        f"- actual rows / period: `{summary['data']['rows']}` / `{summary['data']['actual_start']} ~ {summary['data']['actual_end']}`",
        f"- classification: `{summary['data']['classification']}` / `{summary['data']['return_basis']}`",
        "- 분배금·배당 재투자: `미반영`",
        "- 2014년 이전 lookback: `없음`",
        "- evaluation: `2014-01-02`부터 실제 파일 범위, signal/execution support/final valuation은 `2026-08-14`",
        "- 거래비용/세금/슬리피지: `GROSS / NO_COST_MODEL`",
        "",
        "## ETF investability 예외",
        "",
        "- historical market-cap authority가 없어 market-cap gate만 research bypass했다.",
        "- 실제 parquet의 close와 trading_value로 price/20D liquidity 조건은 적용했다.",
        "- synthetic market-cap 값은 output metric으로 보고하지 않았고, production 코드·applicability는 수정하지 않았다.",
        "",
        "## Common entry",
        "",
        f"- common entry count: `{summary['common_entry_count']}`",
        f"- weekly FAST evaluation errors: `{summary['scan']['weekly_evaluation_error_count']}`",
        "- entry identity: 4전략 matched replay에서 signal date / execution date / OPEN 모두 동일해야 통과한다.",
        "",
        "## Matched 결과",
        "",
        _markdown_table(
            [
                {
                    "strategy": strategy,
                    "trade_count": summary["matched_strategy_summaries"][strategy]["trade_count"],
                    "mean_return_pct": summary["matched_strategy_summaries"][strategy]["mean_return_pct"],
                    "median_return_pct": summary["matched_strategy_summaries"][strategy]["median_return_pct"],
                    "exit_reasons": summary["matched_strategy_summaries"][strategy]["exit_reasons"],
                }
                for strategy in ("V2", "V3", "V4", "Julia")
            ],
            ["strategy", "trade_count", "mean_return_pct", "median_return_pct", "exit_reasons"],
        ),
        "",
        "## Sequential 결과",
        "",
        _markdown_table(strategy_rows, ["strategy", "total_return_pct", "cagr_pct", "mdd_pct", "trade_count", "exposure_ratio_pct"]),
        "",
        "## Exit reason",
        "",
        _markdown_table(exit_rows, ["strategy", "exit_reason", "count"]) if exit_rows else "_No sequential trades._",
        "",
        "## 대표 best / worst trade",
        "",
    ]
    for strategy in ("V2", "V3", "V4", "Julia"):
        item = summary["sequential_trade_summaries"][strategy]
        lines.append(f"- {strategy} best: `{item['best_trade']}`")
        lines.append(f"- {strategy} worst: `{item['worst_trade']}`")
    lines.extend([
        "",
        "## 이전 로컬 reference 비교",
        "",
        f"- reference metrics match: `{summary['reference_comparison']['all_reference_metrics_match']}`",
        f"- first divergence: `{summary['reference_comparison']['first_divergence']}`",
        "- reference 값은 맞추기 위한 목표가 아니라 독립 재현 후 비교 기준으로만 사용했다.",
        "",
        "## 산출물",
        "",
        "- `matched_trades.csv`: 35 common entries × 4 strategies",
        "- `sequential_trades.csv`: 전략별 실제 순차 거래 경로",
        "- `daily_equity.csv`: 전략별 및 Buy & Hold 일별 equity curve",
        "- `summary.json`: 기간·계약·수치·reference 비교",
        "- `report.md`: 감사용 요약",
        "",
    ])
    return "\n".join(lines)


def run_reproduction() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, list[dict[str, Any]]]]:
    daily, data_meta = load_price_authority()
    final_date = _date(daily.index.max())
    context = build_precomputed_ticker_context(TICKER, NAME, daily)
    score_contract, stage_contract = _contracts()
    signals, states, scan_meta = scan_common_entries(daily, context, score_contract, stage_contract)
    if len(signals) != REFERENCE["common_entry_count"]:
        raise AssertionError(f"common entry count differs from frozen reference: {len(signals)}")
    panel = _raw_panel(daily)
    sequential: dict[str, list[dict[str, Any]]] = {}
    sequential["V2"] = _simulate_engine_sequential("V2", signals, daily, panel, context, score_contract, stage_contract, _date(data_meta["evaluation_start"]), final_date)
    sequential["Julia"] = _simulate_engine_sequential("Julia", signals, daily, panel, context, score_contract, stage_contract, _date(data_meta["evaluation_start"]), final_date)
    sequential["V3"] = _simulate_v3_sequential(signals, daily, states, final_date)
    sequential["V4"] = _simulate_v4_sequential(signals, daily, states, final_date)

    matched_rows: list[dict[str, Any]] = []
    for strategy in ("V2", "V3", "V4", "Julia"):
        matched_rows.extend(_simulate_engine_matched(strategy, signals, daily, panel, context, score_contract, stage_contract, final_date, states))
    matched = pd.DataFrame(matched_rows)
    if len(matched) != len(signals) * 4:
        raise AssertionError(f"matched row count mismatch: {len(matched)}")
    for signal in signals:
        group = matched[matched["entry_signal_date"] == signal["signal_date"]]
        if len(group) != 4 or group["entry_execution_date"].nunique() != 1 or group["entry_price"].nunique() != 1:
            raise AssertionError(f"matched entry identity mismatch at {signal['signal_date']}")

    curve_frames = [build_equity_curve(strategy, daily, sequential[strategy]) for strategy in ("V2", "V3", "V4", "Julia")]
    curve_frames.append(build_buy_hold_curve(daily))
    equity = pd.concat(curve_frames, ignore_index=True)
    metrics = {strategy: curve_metrics(equity[equity["strategy"] == strategy].reset_index(drop=True)) for strategy in ("V2", "V3", "V4", "Julia", "Buy & Hold")}
    for strategy in ("V2", "V3", "V4", "Julia"):
        metrics[strategy]["trade_count"] = len(sequential[strategy])
    reference_comparison = _reference_comparison(signals, sequential, {key: equity[equity["strategy"] == key] for key in metrics}, metrics)
    sequential_summaries = {strategy: _trade_summary(rows) for strategy, rows in sequential.items()}
    matched_summaries = {
        strategy: _trade_summary(matched[matched["strategy"] == strategy].to_dict("records"))
        for strategy in ("V2", "V3", "V4", "Julia")
    }
    summary: dict[str, Any] = {
        "work_id": "KODEX200_FOUR_STRATEGY_INDEPENDENT_REPRODUCTION_V01",
        "status": "COMPLETE",
        "verdict": "REPRODUCED" if reference_comparison["all_reference_metrics_match"] else "PARTIALLY_REPRODUCED",
        "evaluation": data_meta,
        "data": data_meta,
        "common_entry_count": len(signals),
        "scan": scan_meta,
        "strategies": metrics,
        "matched_strategy_summaries": matched_summaries,
        "sequential_trade_summaries": sequential_summaries,
        "reference_comparison": reference_comparison,
        "matched_rows": len(matched),
        "matched_identity": {
            "signal_date_match": True,
            "execution_date_match": True,
            "entry_open_match": True,
            "duplicate_entries": int(matched.duplicated(["strategy", "entry_signal_date"]).sum()),
        },
        "entry_contract": {
            "pattern_a_stage": ["TRANSITION", "EARLY_TREND"],
            "weekly_fast_machine": "TRIGGER / READY",
            "monthly_regime": "PERMITTED_REGIME",
            "daily_risk": ["NORMAL", "ELEVATED"],
            "fast_score_status": ["READY", "PARTIAL"],
            "market_cap_gate": "BYPASSED_ETF_NO_HISTORICAL_MARKET_CAP_AUTHORITY",
            "price_filter": ">= 5,000 KRW",
            "avg_trading_value_20d_filter": ">= 300,000,000 KRW",
        },
        "execution_contract": "next local trading day OPEN",
        "valuation_contract": f"{final_date.strftime('%Y-%m-%d')} CLOSE for open positions",
        "cost_model": "GROSS / NO_COST_MODEL",
        "production_strategy_modified": False,
        "network_requests": 0,
        "source_artifacts": {
            "fastcore_v2": "src/trend_scanner/backtest/fastcore_fundamentals_simple_v01.py",
            "fastcore_v3": "scripts/run_fastcore_v3_simple_v00.py",
            "fastcore_v4": "scripts/run_fastcore_v4_matched_ab_official_v01.py",
            "julia": "src/trend_scanner/validation/julia_strategy_v00.py",
            "price_data": str(DATA_PATH.relative_to(ROOT)),
        },
    }
    return summary, matched, equity, sequential


def write_outputs(summary: Mapping[str, Any], matched: pd.DataFrame, equity: pd.DataFrame, sequential: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
    pd.DataFrame([row for rows in sequential.values() for row in rows]).to_csv(SEQUENTIAL_PATH, index=False, lineterminator="\n")
    equity.to_csv(EQUITY_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, sequential), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the offline KODEX200 reproduction")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            summary, matched, equity, sequential = run_reproduction()
        summary["network_requests"] = audit.request_count
        if audit.request_count != 0:
            raise AssertionError(f"network_requests must be 0, got {audit.request_count}")
        write_outputs(summary, matched, equity, sequential)
        print(json.dumps({
            "status": summary["status"],
            "verdict": summary["verdict"],
            "common_entry_count": summary["common_entry_count"],
            "sequential_trade_count": {key: len(value) for key, value in sequential.items()},
            "network_requests": summary["network_requests"],
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"KODEX200 FOUR STRATEGY REPRODUCTION BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
