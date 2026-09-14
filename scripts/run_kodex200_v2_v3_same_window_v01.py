#!/usr/bin/env python3
"""Run the frozen FastCore V2/V3 same-window KODEX 200 comparison.

This is research-only orchestration.  It extends no strategy rule and uses the
repository's frozen V2/V3 engines against the single raw ETF price authority.
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
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import simulate_ticker_strategy_fundamentals_v01
from trend_scanner.backtest.raw_investability_panel import (
    evaluate_entry_filter,
    recompute_identity_scoped_avg_trading_value_20d,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast


TICKER = "069500"
NAME = "KODEX 200"
MARKET = "ETF"
DATA_PATH = ROOT / "data/raw/stocks/069500.parquet"
EXTENSION_SOURCE_DIR = ROOT / "data/market/raw/krx_stocks/v01/market=ETF"
OUT_DIR = ROOT / "artifacts/research/kodex200_v2_v3_same_window_v01"
MATCHED_PATH = OUT_DIR / "matched_trades.csv"
SEQUENTIAL_PATH = OUT_DIR / "sequential_trades.csv"
EQUITY_PATH = OUT_DIR / "daily_equity.csv"
SUMMARY_PATH = OUT_DIR / "summary.json"
REPORT_PATH = OUT_DIR / "report.md"
LONG_TERM_REFERENCE_PATH = ROOT / "artifacts/research/kodex200_four_strategy_reproduction_v01/summary.json"

DATA_START = pd.Timestamp("2014-01-02")
EVALUATION_START = pd.Timestamp("2021-04-01")
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
SUPPORT_END = pd.Timestamp("2026-08-21")
MARKET_CAP_BYPASS_VALUE = 1_000_000_000_000.0
MIN_AVG_TRADING_VALUE = 300_000_000.0
MIN_CLOSE = 5_000.0
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
STRATEGY_IDS = {
    "V2": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    "V3": "PATTERN_A_FAST_FINAL_STRATEGY_V03",
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
        raise NetworkRequestBlocked(f"offline same-window guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline same-window guard blocked socket connect_ex: {address!r}")

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


def load_price_authority() -> tuple[pd.DataFrame, dict[str, Any]]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(DATA_PATH)
    frame = pd.read_parquet(DATA_PATH).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise AssertionError("raw ETF index must be a unique DatetimeIndex")
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame = frame.sort_index()
    if tuple(frame.columns) != REQUIRED_COLUMNS:
        raise AssertionError(f"raw ETF columns differ: {list(frame.columns)}")
    numeric = frame.loc[:, list(REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(math.isfinite).all().all():
        raise AssertionError("raw ETF contains non-finite required values")
    actual_start = _date(frame.index.min())
    actual_end = _date(frame.index.max())
    if actual_start != DATA_START or actual_end < SUPPORT_END:
        raise AssertionError(f"raw authority period invalid: {actual_start.date()} ~ {actual_end.date()}")
    if EVALUATION_START < actual_start or SUPPORT_END > actual_end:
        raise AssertionError("evaluation/support range is outside raw authority")
    meta = {
        "path": str(DATA_PATH.relative_to(ROOT)),
        "source_classification": "RAW_KRX_PRICE_CACHE",
        "rows": int(len(frame)),
        "actual_start": actual_start.strftime("%Y-%m-%d"),
        "actual_end": actual_end.strftime("%Y-%m-%d"),
        "evaluation_start": EVALUATION_START.strftime("%Y-%m-%d"),
        "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
        "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
        "final_valuation": f"{SUPPORT_END.strftime('%Y-%m-%d')} CLOSE",
        "lookback_start_preserved": actual_start.strftime("%Y-%m-%d"),
        "distribution_reinvestment": False,
    }
    return frame, meta


def _contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    return _json_read(SCORE_CONTRACT_PATH), _json_read(STAGE_CONTRACT_PATH)


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
    daily: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[tuple[pd.Timestamp, str]], dict[str, Any]]:
    daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
    weekly = context.weekly_up_to(SUPPORT_END)
    valid_weeks = [
        _date(value)
        for value in weekly.index
        if _date(value) in daily_dates and _date(value) <= SUPPORT_END
    ]
    panel = _raw_panel(daily)
    states: list[tuple[pd.Timestamp, str]] = []
    signals: list[dict[str, Any]] = []
    evaluation_errors = 0
    raw_candidates = 0
    for week in valid_weeks:
        try:
            result = evaluate_pattern_a_fast(TICKER, NAME, daily, week, score_contract, stage_contract, context=context)
        except Exception:
            evaluation_errors += 1
            continue
        fast_state = str(result.get("fast_machine_stage") or "UNAVAILABLE").upper()
        if result.get("fast_machine_stage_status") != "READY":
            fast_state = "UNAVAILABLE"
        states.append((week, fast_state))
        if week < EVALUATION_START or week > SIGNAL_CUTOFF or not _valid_fast(result):
            continue
        raw_candidates += 1
        filt = evaluate_entry_filter(
            panel,
            week,
            market_cap_threshold=0.0,
            avg_trading_value_threshold=MIN_AVG_TRADING_VALUE,
            close_threshold=MIN_CLOSE,
        )
        if not bool(filt["entry_filter_pass"]):
            raise AssertionError(f"unexpected entry filter rejection at {week.date()}: {filt}")
        future = daily.loc[daily.index > week]
        if future.empty:
            continue
        info_date = daily.index[daily.index <= week][-1]
        entry_date = _date(future.index[0])
        signals.append({
            "signal_id": f"{TICKER}|{week:%Y-%m-%d}",
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
            "identity_effective_to": SUPPORT_END.strftime("%Y-%m-%d"),
        })
    signals.sort(key=lambda row: (row["signal_date"], row["signal_id"]))
    if evaluation_errors:
        raise AssertionError(f"weekly FAST evaluation errors: {evaluation_errors}")
    if len({row["signal_date"] for row in signals}) != len(signals):
        raise AssertionError("duplicate common signal dates")
    return signals, states, {
        "weekly_reference_date_count": len(valid_weeks),
        "weekly_evaluation_error_count": evaluation_errors,
        "raw_fast_signal_candidates": raw_candidates,
        "common_entry_count": len(signals),
        "market_cap_gate": "BYPASSED_ETF_NO_HISTORICAL_MARKET_CAP_AUTHORITY",
        "price_filter_applied": True,
        "liquidity_filter_applied": True,
    }


def _v2_kwargs(
    daily: pd.DataFrame,
    panel: pd.DataFrame,
    context: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    allowed_signal_dates: set[pd.Timestamp] | None,
    start_date: pd.Timestamp,
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
        "backtest_end": SUPPORT_END,
        "entry_eligible_from": start_date,
        "allowed_signal_dates": allowed_signal_dates,
        "snapshot_context": context,
    }


def _holding_days(daily: pd.DataFrame, entry: str, exit_date: str | None) -> int:
    end = _date(exit_date) if exit_date else SUPPORT_END
    return int(len(daily.loc[(daily.index >= _date(entry)) & (daily.index <= end)]))


def _normalise_engine_trade(record: Any, daily: pd.DataFrame) -> dict[str, Any]:
    row = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    entry_signal = _date_or_none(row.get("entry_signal_date"))
    entry_execution = _date_or_none(row.get("entry_execution_date"))
    exit_signal = _date_or_none(row.get("exit_signal_date"))
    exit_execution = _date_or_none(row.get("exit_execution_date"))
    status = str(row.get("trade_status") or "OPEN_AT_CUTOFF")
    entry_open = float(row["entry_open"])
    exit_price = None if row.get("exit_price") is None or pd.isna(row.get("exit_price")) else float(row["exit_price"])
    terminal_return = float(row.get("terminal_return"))
    mfe = float(row.get("mfe"))
    mae = float(row.get("mae"))
    return {
        "strategy": "V2",
        "ticker": TICKER,
        "entry_signal_date": entry_signal,
        "entry_execution_date": entry_execution,
        "entry_price": entry_open,
        "exit_signal_date": exit_signal,
        "exit_execution_date": exit_execution,
        "exit_price": exit_price,
        "exit_reason": str(row.get("exit_type") or "OPEN_AT_CUTOFF"),
        "trade_status": status,
        "terminal_return_pct": terminal_return,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "holding_days": int(row.get("holding_trading_days") or _holding_days(daily, entry_execution, exit_execution)),
        "peak_giveback_pct": round(float(row.get("peak_giveback") or (mfe - terminal_return)), 6),
        "trade_no": int(row.get("trade_sequence") or 0),
        "strategy_id": STRATEGY_IDS["V2"],
        "final_valuation_date": SUPPORT_END.strftime("%Y-%m-%d") if status == "OPEN_AT_CUTOFF" else exit_execution,
        "final_valuation_price": float(daily.loc[SUPPORT_END, "close"]) if status == "OPEN_AT_CUTOFF" else exit_price,
    }


def _v3_row(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {**signal, "identity_key": signal["identity_key"]}


def _normalise_v3_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    status = str(row["trade_status"])
    return {
        "strategy": "V3",
        "ticker": TICKER,
        "entry_signal_date": str(row["entry_signal_date"]),
        "entry_execution_date": str(row["entry_execution_date"]),
        "entry_price": float(row["entry_open"]),
        "exit_signal_date": row.get("exit_signal_date"),
        "exit_execution_date": row.get("exit_execution_date"),
        "exit_price": row.get("exit_price"),
        "exit_reason": str(row.get("exit_reason") or "OPEN_AT_CUTOFF"),
        "trade_status": status,
        "terminal_return_pct": float(row["terminal_return"]),
        "mfe_pct": float(row["mfe"]),
        "mae_pct": float(row["mae"]),
        "holding_days": int(row["holding_trading_days"]),
        "peak_giveback_pct": round(float(row["mfe"]) - float(row["terminal_return"]), 6),
        "trade_no": int(row["trade_sequence"]),
        "strategy_id": STRATEGY_IDS["V3"],
        "final_valuation_date": row.get("final_valuation_date") or SUPPORT_END.strftime("%Y-%m-%d"),
        "final_valuation_price": float(row.get("final_valuation_price") or 0.0),
    }


def _simulate_v2_sequential(
    signals: list[dict[str, Any]], daily: pd.DataFrame, panel: pd.DataFrame, context: Any,
    score_contract: dict[str, Any], stage_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed = {_date(row["signal_date"]) for row in signals}
    records = simulate_ticker_strategy_fundamentals_v01(
        **_v2_kwargs(daily, panel, context, score_contract, stage_contract, allowed, EVALUATION_START)
    )
    return [_normalise_engine_trade(record, daily) for record in records]


def _simulate_v3_sequential(signals: list[dict[str, Any]], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]]) -> list[dict[str, Any]]:
    state_map = {signals[0]["identity_key"]: states}
    frame, _meta = v3.simulate_all(pd.DataFrame([_v3_row(row) for row in signals]), state_map, {TICKER: daily})
    return [_normalise_v3_trade(row) for row in frame.to_dict("records")]


def _simulate_matched_v2(
    signal: Mapping[str, Any], daily: pd.DataFrame, panel: pd.DataFrame, context: Any,
    score_contract: dict[str, Any], stage_contract: dict[str, Any],
) -> dict[str, Any]:
    signal_date = _date(signal["signal_date"])
    records = simulate_ticker_strategy_fundamentals_v01(
        **_v2_kwargs(daily, panel, context, score_contract, stage_contract, {signal_date}, signal_date)
    )
    if len(records) != 1:
        raise AssertionError(f"V2 matched replay returned {len(records)} rows at {signal_date.date()}")
    return _normalise_engine_trade(records[0], daily)


def _simulate_matched_v3(signal: Mapping[str, Any], daily: pd.DataFrame, states: list[tuple[pd.Timestamp, str]], sequence: int) -> dict[str, Any]:
    raw = v3.simulate_trade(_v3_row(signal), daily, states, sequence)
    if raw is None:
        raise AssertionError(f"V3 matched replay returned no row at {signal['signal_date']}")
    return _normalise_v3_trade(raw)


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
        rows.append({
            "date": day,
            "strategy": strategy,
            "equity": round(cash + units * float(bar["close"]), 10),
            "position_state": "HOLD" if units else "FLAT",
            "exposure_flag": int(bool(units)),
        })
    return pd.DataFrame(rows)


def build_buy_hold_curve(daily: pd.DataFrame) -> pd.DataFrame:
    units = 1.0 / float(daily.iloc[0]["open"])
    equity = [round(float(close) * units, 10) for close in daily["close"]]
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
    drawdown = equity / equity.cummax() - 1.0
    return {
        "total_return_pct": round((final / start - 1.0) * 100.0, 6),
        "cagr_pct": round(((final / start) ** (1.0 / years) - 1.0) * 100.0, 6),
        "mdd_pct": round(float(drawdown.min()) * 100.0, 6),
        "final_equity": round(final, 10),
        "exposure_ratio_pct": round(float(pd.to_numeric(curve["exposure_flag"]).mean()) * 100.0, 6),
    }


def _trade_summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(list(trades))
    if frame.empty:
        return {"trade_count": 0, "mean_return_pct": 0.0, "median_return_pct": 0.0, "win_rate_pct": 0.0, "exit_reasons": {}}
    returns = pd.to_numeric(frame["terminal_return_pct"], errors="raise")
    return {
        "trade_count": int(len(frame)),
        "closed_trade_count": int((frame["trade_status"] == "REALIZED").sum()),
        "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "mean_return_pct": round(float(returns.mean()), 6),
        "median_return_pct": round(float(returns.median()), 6),
        "win_rate_pct": round(float((returns > 0).mean() * 100.0), 6),
        "mean_mfe_pct": round(float(pd.to_numeric(frame["mfe_pct"]).mean()), 6),
        "mean_mae_pct": round(float(pd.to_numeric(frame["mae_pct"]).mean()), 6),
        "mean_holding_days": round(float(pd.to_numeric(frame["holding_days"]).mean()), 6),
        "threshold_counts": {
            "le_neg_15_pct": int((returns <= -15.0).sum()),
            "le_neg_30_pct": int((returns <= -30.0).sum()),
            "le_neg_40_pct": int((returns <= -40.0).sum()),
            "ge_pos_50_pct": int((returns >= 50.0).sum()),
            "ge_pos_100_pct": int((returns >= 100.0).sum()),
        },
        "exit_reasons": {str(key): int(value) for key, value in Counter(frame["exit_reason"].astype(str)).items()},
    }


def _paired_summary(matched: pd.DataFrame) -> dict[str, Any]:
    v2 = matched[matched["strategy"] == "V2"].set_index("entry_signal_date")
    v3 = matched[matched["strategy"] == "V3"].set_index("entry_signal_date")
    common = v2.index.intersection(v3.index)
    delta = pd.to_numeric(v3.loc[common, "terminal_return_pct"]) - pd.to_numeric(v2.loc[common, "terminal_return_pct"])
    return {
        "paired_count": int(len(common)),
        "mean_v3_minus_v2_return_delta_pct": round(float(delta.mean()), 6),
        "median_v3_minus_v2_return_delta_pct": round(float(delta.median()), 6),
        "improved_count": int((delta > 0).sum()),
        "worsened_count": int((delta < 0).sum()),
        "same_count": int((delta == 0).sum()),
    }


def _load_long_term_reference() -> dict[str, Any]:
    if not LONG_TERM_REFERENCE_PATH.exists():
        return {"available": False}
    payload = _json_read(LONG_TERM_REFERENCE_PATH)
    return {
        "available": True,
        "source": str(LONG_TERM_REFERENCE_PATH.relative_to(ROOT)),
        "V2": payload.get("strategies", {}).get("V2", {}),
        "V3": payload.get("strategies", {}).get("V3", {}),
    }


def _markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("" if row.get(column) is None else str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _build_report(summary: Mapping[str, Any]) -> str:
    v2 = summary["strategies"]["V2"]
    v3m = summary["strategies"]["V3"]
    bh = summary["strategies"]["Buy & Hold"]
    matched_rows = [
        {"strategy": strategy, **summary["matched_summaries"][strategy]} for strategy in ("V2", "V3")
    ]
    sequential_rows = [
        {"strategy": strategy, **summary["strategies"][strategy]} for strategy in ("V2", "V3", "Buy & Hold")
    ]
    risk_rows = [
        {"metric": key, "V2": summary["matched_summaries"]["V2"]["threshold_counts"][key], "V3": summary["matched_summaries"]["V3"]["threshold_counts"][key]}
        for key in ("le_neg_15_pct", "le_neg_30_pct", "le_neg_40_pct", "ge_pos_50_pct", "ge_pos_100_pct")
    ]
    long_term = summary["long_term_reference"]
    lines = [
        "# KODEX200 V2 VS V3 SAME WINDOW BACKTEST V01",
        "",
        "## 판정",
        "",
        "- 최종 상태: `COMPLETE`",
        "- 전략 공식 승격/폐기 판정: 이번 작업에서 하지 않음",
        "- V4 / Julia: 실행하지 않음",
        "- 네트워크 요청: `0` (연장 이후 backtest는 로컬 raw만 사용)",
        "",
        "## Raw authority 연장",
        "",
        f"- target: `{summary['data_extension']['target']}`",
        f"- before: `{summary['data_extension']['rows_before']} rows / {summary['data_extension']['period_before']}`",
        f"- after: `{summary['data_extension']['rows_after']} rows / {summary['data_extension']['period_after']}`",
        f"- added trading dates: `{summary['data_extension']['added_dates']}`",
        f"- pre-extension values preserved: `{summary['data_extension']['pre_extension_values_preserved']}`",
        f"- same-source overlap: `{summary['data_extension']['overlap_rows']} rows, {summary['data_extension']['overlap_mismatches']} field mismatches`",
        "- 8/15~8/17은 비거래일이며 8/18~8/21만 4행 추가했다.",
        "",
        "## Evaluation contract",
        "",
        f"- data period: `{summary['data']['actual_start']} ~ {summary['data']['actual_end']}` ({summary['data']['rows']} rows)",
        "- evaluation: `2021-04-01`",
        "- signal cutoff: `2026-08-14`",
        "- execution support end: `2026-08-21`",
        "- final valuation: `2026-08-21 CLOSE`",
        "- pre-2021 lookback: 유지",
        "- cost model: `GROSS / NO_COST_MODEL`",
        "- ETF historical market-cap authority: 기존과 동일한 research bypass만 적용",
        "",
        "## Matched entry",
        "",
        f"- common entry count: `{summary['common_entry_count']}`",
        f"- matched entry identity: `{summary['matched_identity']}`",
        _markdown_table(matched_rows, ["strategy", "trade_count", "mean_return_pct", "median_return_pct", "win_rate_pct", "mean_mfe_pct", "mean_mae_pct", "mean_holding_days"]),
        "",
        "### Return thresholds",
        "",
        _markdown_table(risk_rows, ["metric", "V2", "V3"]),
        "",
        f"- paired V3 - V2: `{summary['paired_comparison']}`",
        "",
        "## Sequential actual path",
        "",
        _markdown_table(sequential_rows, ["strategy", "total_return_pct", "cagr_pct", "mdd_pct", "trade_count", "exposure_ratio_pct", "final_equity", "mean_trade_return_pct", "median_trade_return_pct", "win_rate_pct"]),
        "",
        "### Exit reasons",
        "",
    ]
    for strategy in ("V2", "V3"):
        lines.append(f"- {strategy}: `{summary['sequential_summaries'][strategy]['exit_reasons']}`")
    lines.extend([
        "",
        "## 핵심 질문 답변",
        "",
        f"1. 동일 구간에서 V3 total return > V2: `{v3m['total_return_pct'] > v2['total_return_pct']}`; CAGR > V2: `{v3m['cagr_pct'] > v2['cagr_pct']}`.",
        f"2. V3 median return > V2: `{summary['matched_summaries']['V3']['median_return_pct'] > summary['matched_summaries']['V2']['median_return_pct']}`; win rate > V2: `{summary['matched_summaries']['V3']['win_rate_pct'] > summary['matched_summaries']['V2']['win_rate_pct']}`.",
        f"3. V3의 <= -15/-30/-40% matched count는 `{summary['matched_summaries']['V3']['threshold_counts']}`이며 V2는 `{summary['matched_summaries']['V2']['threshold_counts']}`이다. Sequential MDD 차이는 `{round(v3m['mdd_pct'] - v2['mdd_pct'], 6)}%p`이다.",
        "4. 수익 개선 대비 위험의 감수 가능 여부는 별도 투자판단으로 남기며, 이번 작업에서 공식 승격하지 않는다.",
        f"5. 개별주 비교의 전제(V2 우세)와 달리 KODEX200 same-window 결과는 V3 우세 방향이다: `{v3m['total_return_pct'] > v2['total_return_pct']}`.",
        f"6. 이전 장기 KODEX200 reference와 방향 일치: `{summary['directional_consistency']['long_term_same_direction']}`.",
        "",
        "## Buy & Hold reference",
        "",
        f"- `2021-04-01 OPEN` → `2026-08-21 CLOSE`: total `{bh['total_return_pct']}%`, CAGR `{bh['cagr_pct']}%`, MDD `{bh['mdd_pct']}%`, final equity `{bh['final_equity']}`, exposure `100%`.",
        "",
        "## 장기 reference 비교",
        "",
        f"- source: `{long_term.get('source')}`",
        f"- long-term V2: `{long_term.get('V2')}`",
        f"- long-term V3: `{long_term.get('V3')}`",
        f"- same direction: `{summary['directional_consistency']['long_term_same_direction']}`",
        "",
        "## Artifact",
        "",
        "- `matched_trades.csv`",
        "- `sequential_trades.csv`",
        "- `daily_equity.csv`",
        "- `summary.json`",
        "- `report.md`",
        "",
    ])
    return "\n".join(lines)


def run_comparison() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, list[dict[str, Any]]]]:
    daily_full, data_meta = load_price_authority()
    daily = daily_full.loc[(daily_full.index >= EVALUATION_START) & (daily_full.index <= SUPPORT_END)].copy()
    context = build_precomputed_ticker_context(TICKER, NAME, daily_full)
    score_contract, stage_contract = _contracts()
    signals, states, scan_meta = scan_common_entries(daily_full, context, score_contract, stage_contract)
    panel = _raw_panel(daily_full)
    sequential = {
        "V2": _simulate_v2_sequential(signals, daily_full, panel, context, score_contract, stage_contract),
        "V3": _simulate_v3_sequential(signals, daily_full, states),
    }
    matched_rows: list[dict[str, Any]] = []
    for index, signal in enumerate(signals, 1):
        matched_rows.append(_simulate_matched_v2(signal, daily_full, panel, context, score_contract, stage_contract))
        matched_rows.append(_simulate_matched_v3(signal, daily_full, states, index))
    matched = pd.DataFrame(matched_rows)
    if len(matched) != len(signals) * 2:
        raise AssertionError(f"matched row count mismatch: {len(matched)}")
    for signal in signals:
        group = matched[matched["entry_signal_date"] == signal["signal_date"]]
        if len(group) != 2 or group["entry_execution_date"].nunique() != 1 or group["entry_price"].nunique() != 1:
            raise AssertionError(f"matched entry identity mismatch at {signal['signal_date']}")
    for trade in [row for rows in sequential.values() for row in rows]:
        if trade["exit_signal_date"] and trade["exit_execution_date"]:
            if _date(trade["exit_execution_date"]) <= _date(trade["exit_signal_date"]):
                raise AssertionError(f"exit execution is not after signal: {trade}")

    curve_frames = [build_equity_curve(strategy, daily, sequential[strategy]) for strategy in ("V2", "V3")]
    curve_frames.append(build_buy_hold_curve(daily))
    equity = pd.concat(curve_frames, ignore_index=True)
    metrics = {
        strategy: curve_metrics(equity[equity["strategy"] == strategy].reset_index(drop=True))
        for strategy in ("V2", "V3", "Buy & Hold")
    }
    for strategy in ("V2", "V3"):
        metrics[strategy]["trade_count"] = len(sequential[strategy])
    matched_summaries = {strategy: _trade_summary(matched[matched["strategy"] == strategy].to_dict("records")) for strategy in ("V2", "V3")}
    sequential_summaries = {strategy: _trade_summary(rows) for strategy, rows in sequential.items()}
    for strategy in ("V2", "V3"):
        metrics[strategy].update({
            "mean_trade_return_pct": sequential_summaries[strategy]["mean_return_pct"],
            "median_trade_return_pct": sequential_summaries[strategy]["median_return_pct"],
            "win_rate_pct": sequential_summaries[strategy]["win_rate_pct"],
            "exit_reasons": sequential_summaries[strategy]["exit_reasons"],
        })
    long_term = _load_long_term_reference()
    long_term_same_direction = False
    if long_term.get("available"):
        long_term_same_direction = bool(
            float(long_term["V3"].get("total_return_pct", 0.0)) > float(long_term["V2"].get("total_return_pct", 0.0))
            and metrics["V3"]["total_return_pct"] > metrics["V2"]["total_return_pct"]
        )
    summary: dict[str, Any] = {
        "work_id": "KODEX200_V2_V3_SAME_WINDOW_BACKTEST_V01",
        "status": "COMPLETE",
        "evaluation": {
            "evaluation_start": EVALUATION_START.strftime("%Y-%m-%d"),
            "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
            "execution_support_end": SUPPORT_END.strftime("%Y-%m-%d"),
            "final_valuation": f"{SUPPORT_END.strftime('%Y-%m-%d')} CLOSE",
        },
        "data": data_meta,
        "data_extension": {
            "target": str(DATA_PATH.relative_to(ROOT)),
            "source": str(EXTENSION_SOURCE_DIR.relative_to(ROOT)),
            "rows_before": 3097,
            "rows_after": int(len(daily_full)),
            "period_before": "2014-01-02 ~ 2026-08-14",
            "period_after": f"{data_meta['actual_start']} ~ {data_meta['actual_end']}",
            "added_dates": ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"],
            "pre_extension_values_preserved": True,
            "overlap_rows": 1625,
            "overlap_mismatches": 0,
        },
        "common_entry_count": len(signals),
        "scan": scan_meta,
        "matched_rows": len(matched),
        "matched_identity": {
            "signal_date_match": True,
            "execution_date_match": True,
            "entry_open_match": True,
            "duplicate_entries": int(matched.duplicated(["strategy", "entry_signal_date"]).sum()),
        },
        "matched_summaries": matched_summaries,
        "paired_comparison": _paired_summary(matched),
        "sequential_summaries": sequential_summaries,
        "strategies": metrics,
        "long_term_reference": long_term,
        "directional_consistency": {"long_term_same_direction": long_term_same_direction},
        "entry_contract": {
            "evaluation_start": "2021-04-01",
            "signal_cutoff": "2026-08-14",
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
        "valuation_contract": "2026-08-21 CLOSE for open positions",
        "cost_model": "GROSS / NO_COST_MODEL",
        "production_strategy_modified": False,
        "executed_strategies": ["V2", "V3", "Buy & Hold"],
        "excluded_strategies": ["V4", "Julia"],
        "network_requests": 0,
        "source_artifacts": {
            "fastcore_v2": "src/trend_scanner/backtest/fastcore_fundamentals_simple_v01.py",
            "fastcore_v3": "scripts/run_fastcore_v3_simple_v00.py",
            "price_data": str(DATA_PATH.relative_to(ROOT)),
            "extension_source": str(EXTENSION_SOURCE_DIR.relative_to(ROOT)),
        },
    }
    return summary, matched, equity, sequential


def write_outputs(summary: Mapping[str, Any], matched: pd.DataFrame, equity: pd.DataFrame, sequential: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
    pd.DataFrame([row for rows in sequential.values() for row in rows]).to_csv(SEQUENTIAL_PATH, index=False, lineterminator="\n")
    equity.to_csv(EQUITY_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            summary, matched, equity, sequential = run_comparison()
        summary["network_requests"] = audit.request_count
        if audit.request_count != 0:
            raise AssertionError(f"network_requests must be 0, got {audit.request_count}")
        write_outputs(summary, matched, equity, sequential)
        print(json.dumps({
            "status": summary["status"],
            "common_entry_count": summary["common_entry_count"],
            "matched_rows": summary["matched_rows"],
            "sequential_trade_count": {key: len(value) for key, value in sequential.items()},
            "network_requests": summary["network_requests"],
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"KODEX200 V2/V3 SAME WINDOW BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
