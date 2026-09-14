#!/usr/bin/env python3
"""Run the frozen four-strategy comparison across five market-index ETFs."""

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
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import simulate_ticker_strategy_fundamentals_v01
from trend_scanner.backtest.raw_investability_panel import (
    evaluate_entry_filter,
    recompute_identity_scoped_avg_trading_value_20d,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022


ETF_UNIVERSE = {
    "229200": "KODEX 코스닥150",
    "292190": "KODEX KRX300",
    "226490": "KODEX 코스피",
    "156080": "KODEX MSCI KOREA",
    "226980": "KODEX 200중소형",
}
STRATEGIES = ("V2", "V3", "V4", "Julia")
RUNS = ("long_range", "same_window")
DATA_DIR = ROOT / "data/raw/stocks"
OUT_ROOT = ROOT / "artifacts/research/market_index_etf_four_strategy_v01"
AGGREGATE_SUMMARY_PATH = OUT_ROOT / "aggregate_summary.json"
AGGREGATE_REPORT_PATH = OUT_ROOT / "aggregate_report.md"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
REFERENCE_LONG_TERM_PATH = ROOT / "artifacts/research/kodex200_four_strategy_reproduction_v01/summary.json"
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
SUPPORT_END = pd.Timestamp("2026-08-21")
SAME_WINDOW_START = pd.Timestamp("2021-04-01")
MARKET_CAP_BYPASS_VALUE = 1_000_000_000_000.0
MIN_AVG_TRADING_VALUE = 300_000_000.0
MIN_CLOSE = 5_000.0
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")
TRADE_COLUMNS = (
    "strategy", "ticker", "entry_signal_date", "entry_execution_date", "entry_price",
    "exit_signal_date", "exit_execution_date", "exit_price", "exit_reason", "trade_status",
    "terminal_return_pct", "mfe_pct", "mae_pct", "holding_days", "peak_giveback_pct",
    "trade_no", "strategy_id", "final_valuation_date", "final_valuation_price",
)
STRATEGY_IDS = {
    "V2": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    "V3": "PATTERN_A_FAST_FINAL_STRATEGY_V03",
    "V4": "PATTERN_A_FAST_FINAL_STRATEGY_V04",
    "Julia": "JULIA_STRATEGY_V00",
}
EXTENSION_RECORDS = {
    "229200": {"action": "EXTENDED", "rows_added": 4, "added_dates": ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"], "phantom_rows_filtered": 0, "source_overlap_rows": 1625, "source_overlap_field_mismatches": 0},
    "292190": {"action": "UNCHANGED_SUPPORT_ALREADY_PRESENT", "rows_added": 0, "added_dates": [], "phantom_rows_filtered": 0, "source_overlap_rows": 1639, "source_overlap_field_mismatches": 0},
    "226490": {"action": "UNCHANGED_SUPPORT_ALREADY_PRESENT", "rows_added": 0, "added_dates": [], "phantom_rows_filtered": 0, "source_overlap_rows": 1639, "source_overlap_field_mismatches": 0},
    "156080": {"action": "CREATED_FROM_LOCAL_KRX_RAW_SOURCE", "rows_added": 1594, "added_dates": [], "phantom_rows_filtered": 35, "source_overlap_rows": 0, "source_overlap_field_mismatches": 0},
    "226980": {"action": "CREATED_FROM_LOCAL_KRX_RAW_SOURCE", "rows_added": 1628, "added_dates": [], "phantom_rows_filtered": 1, "source_overlap_rows": 0, "source_overlap_field_mismatches": 0},
}


class NetworkRequestBlocked(RuntimeError):
    pass


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline ETF backtest guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline ETF backtest guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _date_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _date(value).strftime("%Y-%m-%d")


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    return _json_read(SCORE_CONTRACT_PATH), _json_read(STAGE_CONTRACT_PATH)


def load_price_authority(ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = DATA_DIR / f"{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise AssertionError(f"{ticker}: index must be unique DatetimeIndex")
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame = frame.sort_index()
    if tuple(frame.columns) != REQUIRED_COLUMNS:
        raise AssertionError(f"{ticker}: columns differ: {list(frame.columns)}")
    numeric = frame.loc[:, list(REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(math.isfinite).all().all():
        raise AssertionError(f"{ticker}: non-finite raw values")
    actual_start = _date(frame.index.min())
    actual_end = _date(frame.index.max())
    if actual_end < SUPPORT_END:
        raise AssertionError(f"{ticker}: support end unavailable ({actual_end.date()})")
    if (SUPPORT_END - actual_start).days < int(365.25 * 5):
        raise AssertionError(f"{ticker}: less than five years of history")
    used = frame.loc[frame.index <= SUPPORT_END].copy()
    return used, {
        "ticker": ticker,
        "name": ETF_UNIVERSE[ticker],
        "path": str(path.relative_to(ROOT)),
        "rows_actual": int(len(frame)),
        "rows_used_to_support": int(len(used)),
        "authority_actual_start": actual_start.strftime("%Y-%m-%d"),
        "authority_actual_end": actual_end.strftime("%Y-%m-%d"),
        "used_start": _date(used.index.min()).strftime("%Y-%m-%d"),
        "used_end": _date(used.index.max()).strftime("%Y-%m-%d"),
        "columns": list(used.columns),
        "minimum_five_year_history": True,
        "source_classification": "RAW_KRX_PRICE_CACHE",
        "distribution_reinvestment": False,
    }


def _raw_panel(daily: pd.DataFrame) -> pd.DataFrame:
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
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    run_start: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[tuple[pd.Timestamp, str]], dict[str, Any]]:
    daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
    weekly = context.weekly_up_to(SUPPORT_END)
    valid_weeks = [_date(value) for value in weekly.index if _date(value) in daily_dates and _date(value) <= SUPPORT_END]
    panel = _raw_panel(daily)
    states: list[tuple[pd.Timestamp, str]] = []
    signals: list[dict[str, Any]] = []
    errors = 0
    raw_candidates = 0
    entry_filter_rejections: list[dict[str, Any]] = []
    for week in valid_weeks:
        try:
            result = evaluate_pattern_a_fast(ticker, name, daily, week, score_contract, stage_contract, context=context)
        except Exception:
            errors += 1
            continue
        fast_state = str(result.get("fast_machine_stage") or "UNAVAILABLE").upper()
        if result.get("fast_machine_stage_status") != "READY":
            fast_state = "UNAVAILABLE"
        states.append((week, fast_state))
        if week < run_start or week > SIGNAL_CUTOFF or not _valid_fast(result):
            continue
        raw_candidates += 1
        filt = evaluate_entry_filter(panel, week, market_cap_threshold=0.0, avg_trading_value_threshold=MIN_AVG_TRADING_VALUE, close_threshold=MIN_CLOSE)
        if not bool(filt["entry_filter_pass"]):
            entry_filter_rejections.append({
                "signal_date": week.strftime("%Y-%m-%d"),
                "entry_avg_trading_value_20d": filt.get("entry_avg_trading_value_20d"),
                "entry_signal_close": filt.get("entry_signal_close"),
                "failed_conditions": [
                    key.removesuffix("_pass")
                    for key in ("entry_market_cap_pass", "entry_trading_value_pass", "entry_close_pass")
                    if not bool(filt.get(key))
                ],
            })
            continue
        future = daily.loc[daily.index > week]
        if future.empty:
            continue
        info_date = daily.index[daily.index <= week][-1]
        entry_date = _date(future.index[0])
        signals.append({
            "signal_id": f"{ticker}|{week:%Y-%m-%d}",
            "identity_key": f"{ticker}|ETF_PRICE_ONLY|ETF",
            "ticker": ticker,
            "name": name,
            "market": "ETF",
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
            "identity_effective_to": SUPPORT_END.strftime("%Y-%m-%d"),
        })
    if errors:
        raise AssertionError(f"{ticker}: weekly FAST evaluation errors={errors}")
    signals.sort(key=lambda row: (row["signal_date"], row["signal_id"]))
    if len({row["signal_date"] for row in signals}) != len(signals):
        raise AssertionError(f"{ticker}: duplicate common signal dates")
    return signals, states, {
        "weekly_reference_date_count": len(valid_weeks),
        "weekly_evaluation_error_count": errors,
        "raw_fast_signal_candidates": raw_candidates,
        "common_entry_count": len(signals),
        "entry_filter_rejection_count": len(entry_filter_rejections),
        "entry_filter_rejections": entry_filter_rejections,
        "market_cap_gate": "BYPASSED_ETF_NO_HISTORICAL_MARKET_CAP_AUTHORITY",
        "price_filter_applied": True,
        "liquidity_filter_applied": True,
    }


def _v2_kwargs(ticker: str, name: str, daily: pd.DataFrame, panel: pd.DataFrame, context: Any, score: dict[str, Any], stage: dict[str, Any], allowed: set[pd.Timestamp] | None, start: pd.Timestamp) -> dict[str, Any]:
    return {
        "strategy_id": STRATEGY_IDS["V2"], "ticker": ticker, "isu_cd": "ETF_PRICE_ONLY", "name": name, "market": "ETF",
        "daily": daily, "raw_panel": panel, "score_contract": score, "stage_contract": stage,
        "loss_guard_enabled": True, "backtest_end": SUPPORT_END, "entry_eligible_from": start,
        "allowed_signal_dates": allowed, "snapshot_context": context,
    }


class _EtfMarketCapBypassRegistry:
    def get_market_cap_at_reference(self, ticker: str, reference_date: str, sensitivity_mode: bool = False) -> tuple[float, dict[str, Any]]:
        return MARKET_CAP_BYPASS_VALUE, {"source_role": "ETF_PRICE_ONLY_MARKET_CAP_BYPASS", "authority_status": "NON_CANONICAL_RESEARCH_EXCEPTION", "reference_date": str(reference_date)}


def _julia_kwargs(ticker: str, name: str, daily: pd.DataFrame, context: Any, score: dict[str, Any], stage: dict[str, Any], start: pd.Timestamp) -> dict[str, Any]:
    return {
        "ticker": ticker, "name": name, "market": "ETF", "daily": daily, "score_contract": score, "stage_contract": stage,
        "enable_loss_guard": False, "market_cap_registry": _EtfMarketCapBypassRegistry(),
        "start_date": start, "cutoff_date": SUPPORT_END, "min_market_cap_krw": 100_000_000_000.0,
        "snapshot_context": context,
    }


def _holding_days(daily: pd.DataFrame, entry: str, exit_date: str | None) -> int:
    end = _date(exit_date) if exit_date else SUPPORT_END
    return int(len(daily.loc[(daily.index >= _date(entry)) & (daily.index <= end)]))


def _normalise_engine_trade(record: Any, strategy: str, ticker: str, daily: pd.DataFrame) -> dict[str, Any]:
    row = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    entry_signal = _date_or_none(row.get("entry_signal_date"))
    entry_execution = _date_or_none(row.get("entry_execution_date"))
    exit_signal = _date_or_none(row.get("exit_signal_date"))
    exit_execution = _date_or_none(row.get("exit_execution_date"))
    status = str(row.get("trade_status") or "OPEN_AT_CUTOFF")
    entry_open = float(row["entry_open"])
    exit_price = None if row.get("exit_price") is None or pd.isna(row.get("exit_price")) else float(row["exit_price"])
    mfe = float(row.get("mfe"))
    terminal_return = float(row.get("terminal_return"))
    return {
        "strategy": strategy, "ticker": ticker, "entry_signal_date": entry_signal, "entry_execution_date": entry_execution,
        "entry_price": entry_open, "exit_signal_date": exit_signal, "exit_execution_date": exit_execution, "exit_price": exit_price,
        "exit_reason": str(row.get("exit_type") or "OPEN_AT_CUTOFF"), "trade_status": status,
        "terminal_return_pct": terminal_return, "mfe_pct": float(row.get("mfe")), "mae_pct": float(row.get("mae")),
        "holding_days": int(row.get("holding_trading_days") or _holding_days(daily, entry_execution, exit_execution)),
        "peak_giveback_pct": round(float(row.get("peak_giveback") or (mfe - terminal_return)), 6),
        "trade_no": int(row.get("trade_sequence") or 0), "strategy_id": STRATEGY_IDS[strategy],
        "final_valuation_date": SUPPORT_END.strftime("%Y-%m-%d") if status == "OPEN_AT_CUTOFF" else exit_execution,
        "final_valuation_price": float(daily.loc[SUPPORT_END, "close"]) if status == "OPEN_AT_CUTOFF" else exit_price,
    }


def _normalise_v3_trade(row: Mapping[str, Any], ticker: str) -> dict[str, Any]:
    return {
        "strategy": "V3", "ticker": ticker, "entry_signal_date": str(row["entry_signal_date"]), "entry_execution_date": str(row["entry_execution_date"]),
        "entry_price": float(row["entry_open"]), "exit_signal_date": row.get("exit_signal_date"), "exit_execution_date": row.get("exit_execution_date"),
        "exit_price": row.get("exit_price"), "exit_reason": str(row.get("exit_reason") or "OPEN_AT_CUTOFF"), "trade_status": str(row["trade_status"]),
        "terminal_return_pct": float(row["terminal_return"]), "mfe_pct": float(row["mfe"]), "mae_pct": float(row["mae"]),
        "holding_days": int(row["holding_trading_days"]), "peak_giveback_pct": round(float(row["mfe"]) - float(row["terminal_return"]), 6),
        "trade_no": int(row["trade_sequence"]), "strategy_id": STRATEGY_IDS["V3"],
        "final_valuation_date": row.get("final_valuation_date") or SUPPORT_END.strftime("%Y-%m-%d"),
        "final_valuation_price": float(row.get("final_valuation_price") or 0.0),
    }


def _path_metrics(daily: pd.DataFrame, entry_date: pd.Timestamp, end_date: pd.Timestamp, entry_open: float, extra_price: float | None = None) -> tuple[float, float, float, float]:
    held = daily.loc[(daily.index >= entry_date) & (daily.index <= end_date)]
    highs = [entry_open, *[float(x) for x in held["high"].tolist()]]
    lows = [entry_open, *[float(x) for x in held["low"].tolist()]]
    if extra_price is not None:
        highs.append(float(extra_price)); lows.append(float(extra_price))
    hwm = max(highs); trough = min(lows)
    return hwm, trough, round((hwm / entry_open - 1.0) * 100.0, 2), round((trough / entry_open - 1.0) * 100.0, 2)


def _replay_v4(ticker: str, signal: Mapping[str, Any], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], sequence: int) -> dict[str, Any]:
    entry_date = _date(signal["entry_execution_date"]); entry_open = float(signal["entry_open"])
    hwm = entry_open; exit_signal = None; exit_reason = None
    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        date = _date(date); hwm = max(hwm, float(bar["high"]))
        decision, _soft, _hard, _tier = v4.v4_exit_decision(
            mfe_pct=(hwm / entry_open - 1.0) * 100.0, hwm_price=hwm, current_close=float(bar["close"]),
            entry_open=entry_open, fast_state=v3.latest_fast_state(states, date),
        )
        if decision is not None:
            exit_signal = date; exit_reason = decision; break
    exit_execution = v3._next_session(daily, exit_signal) if exit_signal is not None else None
    status = "REALIZED" if exit_execution is not None else "OPEN_AT_CUTOFF"
    exit_price = float(daily.loc[exit_execution, "open"]) if exit_execution is not None else None
    valuation_date = exit_execution if status == "REALIZED" else SUPPORT_END
    metric_end = exit_signal if status == "REALIZED" and exit_signal is not None else valuation_date
    hwm_price, _trough, mfe, mae = _path_metrics(daily, entry_date, metric_end, entry_open, exit_price)
    terminal_return = round((exit_price / entry_open - 1.0) * 100.0, 2) if status == "REALIZED" else round((float(daily.loc[SUPPORT_END, "close"]) / entry_open - 1.0) * 100.0, 2)
    if status != "REALIZED": exit_reason = "OPEN_AT_CUTOFF"
    return {
        "strategy": "V4", "ticker": ticker, "entry_signal_date": str(signal["signal_date"]), "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "entry_price": entry_open, "exit_signal_date": _date_or_none(exit_signal), "exit_execution_date": _date_or_none(exit_execution), "exit_price": exit_price,
        "exit_reason": exit_reason, "trade_status": status, "terminal_return_pct": terminal_return, "mfe_pct": mfe, "mae_pct": mae,
        "holding_days": _holding_days(daily, entry_date.strftime("%Y-%m-%d"), _date_or_none(exit_execution)), "peak_giveback_pct": round(mfe - terminal_return, 6),
        "trade_no": sequence, "strategy_id": STRATEGY_IDS["V4"], "final_valuation_date": _date_or_none(valuation_date),
        "final_valuation_price": exit_price if status == "REALIZED" else float(daily.loc[SUPPORT_END, "close"]), "hwm_price": hwm_price,
    }


def simulate_sequential(ticker: str, name: str, run_start: pd.Timestamp, signals: list[dict[str, Any]], states: list[tuple[pd.Timestamp, str]], daily: pd.DataFrame, context: Any, panel: pd.DataFrame, score: dict[str, Any], stage: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    allowed = {_date(row["signal_date"]) for row in signals}
    v2_records = simulate_ticker_strategy_fundamentals_v01(**_v2_kwargs(ticker, name, daily, panel, context, score, stage, allowed, run_start))
    v2 = [_normalise_engine_trade(row, "V2", ticker, daily) for row in v2_records]
    julia_records = simulate_ticker_strategy_2022(**_julia_kwargs(ticker, name, daily, context, score, stage, run_start))
    julia = [_normalise_engine_trade(row, "Julia", ticker, daily) for row in julia_records]
    if signals:
        frame, _meta = v3.simulate_all(pd.DataFrame([dict(row) for row in signals]), {signals[0]["identity_key"]: states}, {ticker: daily})
    else:
        frame = pd.DataFrame()
    v3_rows = [_normalise_v3_trade(row, ticker) for row in frame.to_dict("records")]
    v4_rows: list[dict[str, Any]] = []
    current_exit: pd.Timestamp | None = None
    for signal in signals:
        signal_date = _date(signal["signal_date"])
        if current_exit is not None and signal_date <= current_exit:
            continue
        trade = _replay_v4(ticker, signal, daily, states, len(v4_rows) + 1)
        v4_rows.append(trade)
        if trade["trade_status"] == "REALIZED": current_exit = _date(trade["exit_execution_date"])
        else: break
    return {"V2": v2, "V3": v3_rows, "V4": v4_rows, "Julia": julia}


def simulate_matched(ticker: str, name: str, signals: list[dict[str, Any]], states: list[tuple[pd.Timestamp, str]], daily: pd.DataFrame, context: Any, panel: pd.DataFrame, score: dict[str, Any], stage: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sequence, signal in enumerate(signals, 1):
        signal_date = _date(signal["signal_date"])
        v2_records = simulate_ticker_strategy_fundamentals_v01(**_v2_kwargs(ticker, name, daily, panel, context, score, stage, {signal_date}, signal_date))
        if len(v2_records) != 1: raise AssertionError(f"{ticker}: V2 matched rows={len(v2_records)} at {signal_date.date()}")
        rows.append(_normalise_engine_trade(v2_records[0], "V2", ticker, daily))
        julia_records = simulate_ticker_strategy_2022(**_julia_kwargs(ticker, name, daily, context, score, stage, signal_date))
        if not julia_records: raise AssertionError(f"{ticker}: Julia matched row missing at {signal_date.date()}")
        julia_row = _normalise_engine_trade(julia_records[0], "Julia", ticker, daily)
        if julia_row["entry_signal_date"] != signal["signal_date"]: raise AssertionError(f"{ticker}: Julia entry mismatch at {signal_date.date()}")
        rows.append(julia_row)
        v3_raw = v3.simulate_trade(dict(signal), daily, states, sequence)
        if v3_raw is None: raise AssertionError(f"{ticker}: V3 matched row missing at {signal_date.date()}")
        rows.append(_normalise_v3_trade(v3_raw, ticker))
        rows.append(_replay_v4(ticker, signal, daily, states, sequence))
    matched = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    if len(matched) != len(signals) * 4: raise AssertionError(f"{ticker}: matched row count mismatch")
    for signal in signals:
        group = matched[matched["entry_signal_date"] == signal["signal_date"]]
        if len(group) != 4 or group["entry_execution_date"].nunique() != 1 or group["entry_price"].nunique() != 1: raise AssertionError(f"{ticker}: entry identity mismatch at {signal['signal_date']}")
    return matched


def build_equity_curve(strategy: str, daily: pd.DataFrame, trades: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    cash = 1.0; units = 0.0; rows: list[dict[str, Any]] = []
    by_entry = {str(row["entry_execution_date"]): row for row in trades}
    by_exit = {str(row["exit_execution_date"]): row for row in trades if row.get("exit_execution_date")}
    for date, bar in daily.iterrows():
        day = _date(date).strftime("%Y-%m-%d")
        entry = by_entry.get(day)
        if entry is not None:
            if units != 0.0: raise AssertionError(f"{strategy}: overlapping entry on {day}")
            units = cash / float(entry["entry_price"]); cash = 0.0
        exit_row = by_exit.get(day)
        if exit_row is not None:
            if units == 0.0: raise AssertionError(f"{strategy}: exit without position on {day}")
            cash = units * float(exit_row["exit_price"]); units = 0.0
        rows.append({"date": day, "strategy": strategy, "equity": round(cash + units * float(bar["close"]), 10), "position_state": "HOLD" if units else "FLAT", "exposure_flag": int(bool(units))})
    return pd.DataFrame(rows)


def build_buy_hold_curve(daily: pd.DataFrame) -> pd.DataFrame:
    units = 1.0 / float(daily.iloc[0]["open"])
    equity = [round(float(close) * units, 10) for close in daily["close"]]; equity[0] = 1.0
    return pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in daily.index], "strategy": "Buy & Hold", "equity": equity, "position_state": "HOLD", "exposure_flag": 1})


def curve_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    equity = pd.to_numeric(curve["equity"], errors="raise"); dates = pd.to_datetime(curve["date"], errors="raise")
    start = float(equity.iloc[0]); final = float(equity.iloc[-1]); years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1e-12)
    return {"total_return_pct": round((final / start - 1.0) * 100.0, 6), "cagr_pct": round(((final / start) ** (1.0 / years) - 1.0) * 100.0, 6), "mdd_pct": round(float((equity / equity.cummax() - 1.0).min()) * 100.0, 6), "final_equity": round(final, 10), "exposure_ratio_pct": round(float(pd.to_numeric(curve["exposure_flag"]).mean()) * 100.0, 6)}


def trade_summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(list(trades))
    if frame.empty: return {"trade_count": 0, "mean_return_pct": 0.0, "median_return_pct": 0.0, "win_rate_pct": 0.0, "mean_mfe_pct": 0.0, "mean_mae_pct": 0.0, "mean_holding_days": 0.0, "threshold_counts": {}, "exit_reasons": {}}
    ret = pd.to_numeric(frame["terminal_return_pct"], errors="raise")
    return {
        "trade_count": int(len(frame)), "closed_trade_count": int((frame["trade_status"] == "REALIZED").sum()), "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "mean_return_pct": round(float(ret.mean()), 6), "median_return_pct": round(float(ret.median()), 6), "win_rate_pct": round(float((ret > 0).mean() * 100.0), 6),
        "mean_mfe_pct": round(float(pd.to_numeric(frame["mfe_pct"]).mean()), 6), "mean_mae_pct": round(float(pd.to_numeric(frame["mae_pct"]).mean()), 6), "mean_holding_days": round(float(pd.to_numeric(frame["holding_days"]).mean()), 6),
        "threshold_counts": {"le_neg_15_pct": int((ret <= -15).sum()), "le_neg_30_pct": int((ret <= -30).sum()), "le_neg_40_pct": int((ret <= -40).sum()), "ge_pos_50_pct": int((ret >= 50).sum()), "ge_pos_100_pct": int((ret >= 100).sum())},
        "exit_reasons": {str(k): int(v) for k, v in Counter(frame["exit_reason"].astype(str)).items()},
    }


def paired_vs_v2(matched: pd.DataFrame) -> dict[str, dict[str, Any]]:
    base = matched[matched.strategy == "V2"].set_index("entry_signal_date")
    out: dict[str, dict[str, Any]] = {}
    for strategy in ("V3", "V4", "Julia"):
        other = matched[matched.strategy == strategy].set_index("entry_signal_date")
        common = base.index.intersection(other.index)
        delta = pd.to_numeric(other.loc[common, "terminal_return_pct"]) - pd.to_numeric(base.loc[common, "terminal_return_pct"])
        out[strategy] = {"paired_count": int(len(common)), "mean_delta_pct": round(float(delta.mean()), 6) if len(delta) else None, "median_delta_pct": round(float(delta.median()), 6) if len(delta) else None, "improved_count": int((delta > 0).sum()), "worsened_count": int((delta < 0).sum()), "same_count": int((delta == 0).sum())}
    return out


def _markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows: lines.append("| " + " | ".join("" if row.get(c) is None else str(row.get(c)) for c in columns) + " |")
    return "\n".join(lines)


def _run_report(summary: Mapping[str, Any]) -> str:
    lines = [f"# {summary['ticker']} {summary['name']} Four Strategy Backtest", "", f"- status: `{summary['status']}`", f"- authority: `{summary['data']['path']}`", f"- actual authority period: `{summary['data']['authority_actual_start']} ~ {summary['data']['authority_actual_end']}` / `{summary['data']['rows_actual']}` rows", f"- used through support end: `{summary['data']['used_start']} ~ {summary['data']['used_end']}` / `{summary['data']['rows_used_to_support']}` rows", "- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`", "- cost model: `GROSS / NO_COST_MODEL`", "", "## Run summary", ""]
    rows=[]
    for run in RUNS:
        if summary["runs"][run]["status"] != "COMPLETE": rows.append({"run":run,"status":summary["runs"][run]["status"],"reason":summary["runs"][run].get("reason")}); continue
        for s in STRATEGIES + ("Buy & Hold",):
            m=summary["runs"][run]["strategies"][s]; rows.append({"run":run,"strategy":s,"total":m.get("total_return_pct"),"cagr":m.get("cagr_pct"),"mdd":m.get("mdd_pct"),"exposure":m.get("exposure_ratio_pct"),"trades":m.get("trade_count")})
    lines.append(_markdown_table(rows, ["run","strategy","total","cagr","mdd","exposure","trades"]))
    for run in RUNS:
        r=summary["runs"][run]
        if r["status"] != "COMPLETE": continue
        lines.extend(["", f"## {run}", "", f"- common entry: `{r['common_entry_count']}`", f"- matched identity: `{r['matched_identity']}`", f"- paired vs V2: `{r['paired_vs_v2']}`", "", "### Matched", ""])
        lines.append(_markdown_table([{"strategy":s,**r["matched_summaries"][s]} for s in STRATEGIES], ["strategy","trade_count","mean_return_pct","median_return_pct","win_rate_pct","mean_mfe_pct","mean_mae_pct","mean_holding_days"]))
        lines.extend(["", "### Sequential exit reasons", ""])
        for s in STRATEGIES: lines.append(f"- {s}: `{r['sequential_summaries'][s]['exit_reasons']}`")
    return "\n".join(lines) + "\n"


def run_one(ticker: str, name: str, daily: pd.DataFrame, data_meta: dict[str, Any], run: str, run_start: pd.Timestamp, score: dict[str, Any], stage: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, list[dict[str, Any]]]]:
    context = build_precomputed_ticker_context(ticker, name, daily)
    signals, states, scan_meta = scan_common_entries(ticker, name, daily, context, score, stage, run_start)
    panel = _raw_panel(daily)
    sequential = simulate_sequential(ticker, name, run_start, signals, states, daily, context, panel, score, stage)
    matched = simulate_matched(ticker, name, signals, states, daily, context, panel, score, stage)
    for trade in [row for rows in sequential.values() for row in rows]:
        if trade.get("exit_signal_date") and trade.get("exit_execution_date") and _date(trade["exit_execution_date"]) <= _date(trade["exit_signal_date"]): raise AssertionError(f"{ticker}: exit execution ordering")
    curve_daily = daily.loc[daily.index >= run_start].copy()
    curves=[build_equity_curve(s, curve_daily, sequential[s]) for s in STRATEGIES]; curves.append(build_buy_hold_curve(curve_daily)); equity=pd.concat(curves,ignore_index=True)
    metrics={s:curve_metrics(equity[equity.strategy==s].reset_index(drop=True)) for s in STRATEGIES+("Buy & Hold",)}
    for s in STRATEGIES: metrics[s]["trade_count"]=len(sequential[s]); metrics[s]["mean_trade_return_pct"]=trade_summary(sequential[s])["mean_return_pct"]; metrics[s]["median_trade_return_pct"]=trade_summary(sequential[s])["median_return_pct"]; metrics[s]["win_rate_pct"]=trade_summary(sequential[s])["win_rate_pct"]; metrics[s]["exit_reasons"]=trade_summary(sequential[s])["exit_reasons"]
    matched_summaries={s:trade_summary(matched[matched.strategy==s].to_dict("records")) for s in STRATEGIES}; sequential_summaries={s:trade_summary(sequential[s]) for s in STRATEGIES}
    result={"status":"COMPLETE","run":run,"evaluation_start":run_start.strftime("%Y-%m-%d"),"signal_cutoff":SIGNAL_CUTOFF.strftime("%Y-%m-%d"),"execution_support_end":SUPPORT_END.strftime("%Y-%m-%d"),"final_valuation":"2026-08-21 CLOSE","common_entry_count":len(signals),"scan":scan_meta,"matched_rows":len(matched),"matched_identity":{"signal_date_match":True,"execution_date_match":True,"entry_open_match":True,"duplicate_entries":int(matched.duplicated(["strategy","entry_signal_date"]).sum())},"matched_summaries":matched_summaries,"paired_vs_v2":paired_vs_v2(matched),"sequential_summaries":sequential_summaries,"strategies":metrics,"cost_model":"GROSS / NO_COST_MODEL","network_requests":0,"executed_strategies":list(STRATEGIES)+["Buy & Hold"],"market_cap_gate":"BYPASSED_ETF_NO_HISTORICAL_MARKET_CAP_AUTHORITY"}
    return result, matched, equity, sequential


def write_run_outputs(ticker: str, run: str, summary: Mapping[str, Any], matched: pd.DataFrame | None, equity: pd.DataFrame | None, sequential: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> None:
    out=OUT_ROOT/ticker/run; out.mkdir(parents=True,exist_ok=True); _json_write(out/"summary.json",summary)
    if matched is not None and equity is not None and sequential is not None:
        matched.to_csv(out/"matched_trades.csv",index=False,lineterminator="\n"); pd.DataFrame([row for rows in sequential.values() for row in rows], columns=TRADE_COLUMNS).to_csv(out/"sequential_trades.csv",index=False,lineterminator="\n"); equity.to_csv(out/"daily_equity.csv",index=False,lineterminator="\n")


def _aggregate_report(aggregate: Mapping[str, Any]) -> str:
    lines=["# MARKET INDEX ETF FIVE UNIVERSE FOUR STRATEGY BACKTEST V01","",f"- overall status: `{aggregate['status']}`","- V2/V3/V4/Julia rules unchanged","- backtest network requests: `0`","", "## ETF status", ""]
    status_rows = []
    for t in ETF_UNIVERSE:
        item = aggregate["etfs"][t]
        data = item.get("data") or {}
        period = f"{data['used_start']} ~ {data['used_end']}" if data.get("used_start") and data.get("used_end") else ""
        status_rows.append({"ticker": t, "name": item["name"], "long_range": item["runs"]["long_range"]["status"], "same_window": item["runs"]["same_window"]["status"], "period": period})
    lines.append(_markdown_table(status_rows, ["ticker","name","long_range","same_window","period"]))
    for run in RUNS:
        lines.extend(["", f"## {run} sequential comparison", ""])
        rows=[]
        for t in ETF_UNIVERSE:
            r=aggregate["etfs"][t]["runs"][run]
            for s in STRATEGIES+("Buy & Hold",):
                if r["status"]=="COMPLETE":
                    m=r["strategies"][s]; rows.append({"ticker":t,"strategy":s,"total":m.get("total_return_pct"),"cagr":m.get("cagr_pct"),"mdd":m.get("mdd_pct"),"exposure":m.get("exposure_ratio_pct"),"trades":m.get("trade_count")})
        lines.append(_markdown_table(rows,["ticker","strategy","total","cagr","mdd","exposure","trades"]))
        lines.extend(["", "### V2 대비 우위 횟수", "", str(aggregate["wins"][run])])
    lines.extend(["", "## 핵심 질문", "", f"- V3가 V2를 이긴 ETF 수(total/CAGR): `{aggregate['wins']['long_range']['sequential_total']['V3']} / {aggregate['wins']['long_range']['sequential_cagr']['V3']}` long range, `{aggregate['wins']['same_window']['sequential_total']['V3']} / {aggregate['wins']['same_window']['sequential_cagr']['V3']}` same window.", "- V3/V4/Julia의 시장지수 ETF 전반 반복 여부는 위 ETF별 표와 우위 횟수로 제한적으로 확인하며, 공식 승격/폐기 결론은 내리지 않는다.", "- V3 MDD가 V2보다 개선인지 악화인지는 ETF별 결과를 기준으로 판단해야 하며, aggregate는 방향만 기록한다.", ""])
    return "\n".join(lines)


def _compute_wins(aggregate: Mapping[str, Any], run: str) -> dict[str, Any]:
    out={"sequential_total":{s:0 for s in ("V3","V4","Julia")},"sequential_cagr":{s:0 for s in ("V3","V4","Julia")},"sequential_mdd":{s:0 for s in ("V3","V4","Julia")},"matched_mean":{s:0 for s in ("V3","V4","Julia")},"matched_median":{s:0 for s in ("V3","V4","Julia")},"matched_win_rate":{s:0 for s in ("V3","V4","Julia")}}
    for t in ETF_UNIVERSE:
        r=aggregate["etfs"][t]["runs"][run]
        if r["status"]!="COMPLETE": continue
        base=r["strategies"]["V2"]; base_match=r["matched_summaries"]["V2"]
        for s in ("V3","V4","Julia"):
            m=r["strategies"][s]; mm=r["matched_summaries"][s]
            out["sequential_total"][s]+=int(m["total_return_pct"]>base["total_return_pct"]); out["sequential_cagr"][s]+=int(m["cagr_pct"]>base["cagr_pct"]); out["sequential_mdd"][s]+=int(m["mdd_pct"]>base["mdd_pct"]); out["matched_mean"][s]+=int(mm["mean_return_pct"]>base_match["mean_return_pct"]); out["matched_median"][s]+=int(mm["median_return_pct"]>base_match["median_return_pct"]); out["matched_win_rate"][s]+=int(mm["win_rate_pct"]>base_match["win_rate_pct"])
    return out


def run_all() -> dict[str, Any]:
    score,stage=_contracts(); aggregate={"work_id":"MARKET_INDEX_ETF_FIVE_UNIVERSE_FOUR_STRATEGY_BACKTEST_V01","status":"COMPLETE","starting_head":"ee94fa58c2d3d294d8cd5096c195f43502a15d8c","branch":"codex/fastcore-fundamentals-simple-backtest-v01","etfs":{},"wins":{}}
    for ticker,name in ETF_UNIVERSE.items():
        try:
            daily,data_meta=load_price_authority(ticker); item={"status":"COMPLETE","ticker":ticker,"name":name,"data":data_meta,"extension":EXTENSION_RECORDS[ticker],"runs":{}}
            context=build_precomputed_ticker_context(ticker,name,daily)
            for run in RUNS:
                start=_date(daily.index.min()) if run=="long_range" else SAME_WINDOW_START
                summary,matched,equity,sequential=run_one(ticker,name,daily,data_meta,run,start,score,stage); summary["ticker"]=ticker; summary["name"]=name; summary["data"]=data_meta; summary["extension"]=EXTENSION_RECORDS[ticker]; item["runs"][run]=summary; write_run_outputs(ticker,run,summary,matched,equity,sequential)
            item["report"]=_run_report(item); (OUT_ROOT/ticker).mkdir(parents=True,exist_ok=True); (OUT_ROOT/ticker/"report.md").write_text(item["report"],encoding="utf-8"); aggregate["etfs"][ticker]=item
        except Exception as exc:
            aggregate["status"]="PARTIAL_DATA_GAP"; item={"status":"BLOCKED_DATA_GAP","ticker":ticker,"name":name,"data":None,"extension":EXTENSION_RECORDS.get(ticker,{}),"runs":{run:{"status":"BLOCKED_DATA_GAP","reason":f"{type(exc).__name__}: {exc}"} for run in RUNS}}; aggregate["etfs"][ticker]=item; (OUT_ROOT/ticker).mkdir(parents=True,exist_ok=True); _json_write(OUT_ROOT/ticker/"long_range/summary.json",item["runs"]["long_range"]); _json_write(OUT_ROOT/ticker/"same_window/summary.json",item["runs"]["same_window"]); (OUT_ROOT/ticker/"report.md").write_text(f"# {ticker} {name}\n\n- status: `BLOCKED_DATA_GAP`\n- reason: `{item['runs']['long_range']['reason']}`\n",encoding="utf-8")
    for run in RUNS: aggregate["wins"][run]=_compute_wins(aggregate,run)
    aggregate["network_requests"]=0; aggregate["excluded_etfs"]=[x for x in []]; _json_write(AGGREGATE_SUMMARY_PATH,aggregate); AGGREGATE_REPORT_PATH.write_text(_aggregate_report(aggregate),encoding="utf-8"); return aggregate


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--run",action="store_true"); args=parser.parse_args()
    if not args.run: parser.error("use --run")
    audit=NetworkAudit()
    try:
        with network_guard(audit): result=run_all()
        result["network_requests"]=audit.request_count; _json_write(AGGREGATE_SUMMARY_PATH,result)
        if audit.request_count!=0: raise AssertionError(f"network requests={audit.request_count}")
        print(json.dumps({"status":result["status"],"etf_status":{t:{r:result["etfs"][t]["runs"][r]["status"] for r in RUNS} for t in ETF_UNIVERSE},"network_requests":audit.request_count},ensure_ascii=False),flush=True); return 0
    except Exception as exc: print(f"MARKET INDEX ETF BACKTEST BLOCKED: {type(exc).__name__}: {exc}",flush=True); return 1


if __name__=="__main__": raise SystemExit(main())
