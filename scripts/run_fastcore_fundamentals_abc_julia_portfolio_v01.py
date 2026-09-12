#!/usr/bin/env python3
"""Cache-only weekly portfolio backtest for the frozen ABC No-Loss-Guard strategy.

The strategy signal authority is frozen. This runner derives the ABC-passing
FastCore signal set and its full-exit signal path from the local repository,
then applies a separate weekly cash-constrained portfolio event engine.
No source refresh or network access is permitted.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_fundamentals_abc_julia_no_loss_guard_v01 as frozen_runner
from scripts import run_fastcore_fundamentals_abc_return_v01 as abc_return
from scripts import run_fastcore_fundamentals_abc_v01 as abc_base
from scripts.run_fastcore_control import (
    COMMON_START_DATE,
    EFFECTIVE_AUTHORITY_DIR,
    EXECUTION_SUPPORT_END_DATE,
    SCORE_CONTRACT_PATH,
    SIGNAL_END_DATE,
    STAGE_CONTRACT_PATH,
    _authority_intervals,
    _tasks_by_ticker,
    frozen_candidate_id,
    sha256_file,
    validate_frozen_inputs,
)
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    build_precomputed_ticker_context,
    clip_to_identity_lifecycle,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader


OUT_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_abc_julia_portfolio_v01"
RAW_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/raw_candidates/fastcore_raw_candidates.csv"
ENTRY_AUTHORITY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_return/abc_entry_candidate_audit.csv"
FUNDAMENTAL_EVENT_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_return/abc_fundamental_exit_events.csv"
ABC_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_return/abc_trades.csv"
FROZEN_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_julia_no_loss_guard/abc_julia_no_loss_guard_trades.csv"

INITIAL_CAPITAL = 200_000_000
POSITION_CAP = 5_000_000
SIGNAL_END = SIGNAL_END_DATE
SUPPORT_END = EXECUTION_SUPPORT_END_DATE
FROZEN_TRADES_SHA = "2e295ac3b64b1c227a43852a929f0dfa368755aa1dc0b3eec0d6b06a950ed8ec"
ABC_TRADES_SHA = "fed6f87c8f77bab4a3fa60062af4177b00d6d1705036777cb81331c796f9a8d4"
RAW_SHA = "6f79fdaf7a341ec81c1fff4f2034b29f690651c7a08f1569c8cda82367114591"
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_FUNDAMENTALS_ABC_JULIA_NO_LOSS_GUARD_V01"
PORTFOLIO_A = "PORTFOLIO_A_NO_PARTIAL_PROFIT"
PORTFOLIO_B = "PORTFOLIO_B_HALF_PROFIT_AT_50"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _week_start(value: Any) -> pd.Timestamp:
    date = pd.Timestamp(value).normalize()
    return date - pd.to_timedelta(int(date.weekday()), unit="D")


def _truth(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _identity_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("ticker") or "").zfill(6), str(row.get("isu_cd") or ""), str(row.get("market") or ""))


def _lookup_exact(daily: pd.DataFrame, date: Any, column: str) -> float:
    timestamp = pd.Timestamp(date).normalize()
    if timestamp not in daily.index:
        raise RuntimeError(f"BLOCKED_DATA_GAP: missing {column} price for {timestamp.date()}")
    return float(daily.loc[timestamp, column])


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _hash_authorities() -> dict[str, str]:
    paths = {
        "no_loss_guard_trades": FROZEN_TRADES_PATH,
        "abc_trades": ABC_TRADES_PATH,
        "raw_candidates": RAW_PATH,
        "abc_entry_authority": ENTRY_AUTHORITY_PATH,
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def _validate_frozen_authorities() -> None:
    if sha256_file(FROZEN_TRADES_PATH) != FROZEN_TRADES_SHA:
        raise RuntimeError("BLOCKED_FROZEN_STRATEGY_MUTATION")
    if sha256_file(ABC_TRADES_PATH) != ABC_TRADES_SHA:
        raise RuntimeError("BLOCKED_FROZEN_ABC_TRADES_MUTATION")
    if sha256_file(RAW_PATH) != RAW_SHA:
        raise RuntimeError("BLOCKED_FROZEN_RAW_MUTATION")
    validate_frozen_inputs()


def _load_signal_authority(raw: pd.DataFrame, authority: pd.DataFrame) -> pd.DataFrame:
    pass_ids = set(authority.loc[authority["classification"].eq("ABC_ENTRY_PASS"), "candidate_id"].astype(str))
    result = raw[raw["candidate_id"].astype(str).isin(pass_ids)].copy()
    result["candidate_signal_date"] = pd.to_datetime(result["candidate_signal_date"], errors="raise").dt.normalize()
    result = result[
        (result["candidate_signal_date"] >= COMMON_START_DATE)
        & (result["candidate_signal_date"] <= SIGNAL_END)
    ].copy()
    if result.empty or result["candidate_id"].duplicated().any():
        raise RuntimeError("BLOCKED_SIGNAL_AUTHORITY_INVALID")
    result["fast_score"] = pd.to_numeric(result["fast_score"], errors="coerce")
    if result["fast_score"].isna().any():
        raise RuntimeError("BLOCKED_SIGNAL_AUTHORITY_SCORE_GAP")
    return result.sort_values(["candidate_signal_date", "candidate_id"], kind="mergesort").reset_index(drop=True)


def _load_fundamental_events() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    events = pd.read_csv(FUNDAMENTAL_EVENT_PATH, dtype={"ticker": str, "isu_cd": str, "market": str})
    for column in ("source_readiness", "evaluation_error", "future_filing_used"):
        if column not in events.columns:
            raise RuntimeError(f"BLOCKED_FUNDAMENTAL_AUTHORITY_SCHEMA: {column}")
    if events["source_readiness"].astype(str).ne("READY").any():
        raise RuntimeError("BLOCKED_FUNDAMENTAL_AUTHORITY_READINESS")
    if events["evaluation_error"].map(_truth).any() or events["future_filing_used"].map(_truth).any():
        raise RuntimeError("BLOCKED_FUNDAMENTAL_AUTHORITY_INTEGRITY")
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in events.to_dict(orient="records"):
        key = (str(row.get("ticker") or "").zfill(6), str(row.get("isu_cd") or ""), str(row.get("market") or ""))
        grouped[key].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (str(row.get("fundamental_information_date") or ""), str(row.get("quarter") or "")))
    return dict(grouped)


def _build_raw_task_map(raw: pd.DataFrame) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    tasks = _tasks_by_ticker(raw)
    result: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for ticker_tasks in tasks.values():
        for task in ticker_tasks:
            key = (
                str(task["ticker"]), str(task["isu_cd"]), str(task["market"]),
                str(task["effective_from"]), str(task["effective_to"]),
            )
            result[key] = task
    return result


def build_signal_exit_authority() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Generate one frozen-strategy exit path for each ABC-passing signal.

    This is a signal-authority build only. It is intentionally separate from
    the portfolio engine, which owns cash, weekly batching, and skips.
    """
    _validate_frozen_authorities()
    raw = pd.read_csv(RAW_PATH, dtype={"candidate_id": str, "ticker": str, "isu_cd": str, "market": str})
    authority, _ = frozen_runner.load_entry_authority(raw)
    signals = _load_signal_authority(raw, authority)
    event_map = _load_fundamental_events()
    raw_tasks = _build_raw_task_map(raw)
    authority_payload = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority_payload)
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    repository = abc_return._candidate_repository(ROOT, raw, SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT_END)
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    context_by_identity: dict[tuple[str, str, str, str, str], Any] = {}
    rows: list[dict[str, Any]] = []

    for index, candidate in enumerate(signals.to_dict(orient="records"), 1):
        ticker = str(candidate["ticker"]).zfill(6)
        identity = _identity_key(candidate)
        task_key = (identity[0], identity[1], identity[2], str(candidate["identity_effective_from"]), str(candidate["identity_effective_to"]))
        task = raw_tasks.get(task_key)
        if task is None:
            raise RuntimeError(f"BLOCKED_SIGNAL_AUTHORITY_TASK_GAP: {task_key}")
        daily = daily_by_ticker.get(ticker)
        if daily is None:
            daily = loader.load(ticker)
            if daily is None or daily.empty:
                raise RuntimeError(f"BLOCKED_DATA_GAP: {ticker}")
            daily_by_ticker[ticker] = daily
        lifecycle = IdentityLifecycle(
            ticker=identity[0], isu_cd=identity[1], market=identity[2],
            effective_from=pd.Timestamp(task["effective_from"]), effective_to=pd.Timestamp(task["effective_to"]),
        )
        context_key = task_key
        context = context_by_identity.get(context_key)
        if context is None:
            clipped = clip_to_identity_lifecycle(daily, lifecycle)
            context = build_precomputed_ticker_context(ticker, str(candidate.get("name") or ticker), clipped)
            context_by_identity[context_key] = context
        candidate_id = str(candidate["candidate_id"])

        def gate(_as_of: pd.Timestamp, context_values: dict[str, Any], *, candidate_id: str = candidate_id) -> dict[str, Any]:
            signal_date = pd.Timestamp(context_values["signal_date"]).normalize()
            return {
                "gate_pass": frozen_candidate_id(identity[0], identity[1], identity[2], signal_date) == candidate_id,
                "gate_id": "FROZEN_ABC_ENTRY_AUTHORITY",
            }

        def fundamental_callback(
            _signal: pd.Timestamp,
            _entry_exec: pd.Timestamp,
            _identity_daily: pd.DataFrame,
            *,
            key: tuple[str, str, str] = identity,
        ) -> list[Mapping[str, Any]]:
            return event_map.get(key, [])

        records = simulate_ticker_strategy_fundamentals_v01(
            strategy_id=STRATEGY_ID,
            ticker=identity[0], isu_cd=identity[1], name=str(candidate.get("name") or ticker), market=identity[2],
            daily=daily, raw_panel=task["raw_panel"], score_contract=score_contract, stage_contract=stage_contract,
            loss_guard_enabled=False, backtest_end=SUPPORT_END, entry_eligible_from=COMMON_START_DATE,
            allowed_signal_dates={pd.Timestamp(candidate["candidate_signal_date"]).normalize()},
            snapshot_context=context, identity_lifecycle=lifecycle,
            pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                intervals, ticker_value, isu_value, market_value, value
            ),
            entry_gate=gate, fundamental_exit_callback=fundamental_callback,
        )
        if len(records) != 1:
            raise RuntimeError(f"BLOCKED_SIGNAL_EXIT_AUTHORITY_GAP: {candidate_id}: {len(records)}")
        record = records[0].to_dict()
        if str(record["entry_signal_date"]) != pd.Timestamp(candidate["candidate_signal_date"]).strftime("%Y-%m-%d"):
            raise RuntimeError(f"BLOCKED_SIGNAL_DATE_DRIFT: {candidate_id}")
        rows.append({
            "signal_id": candidate_id,
            "ticker": identity[0], "isu_cd": identity[1], "market": identity[2],
            "name": str(candidate.get("name") or ticker),
            "signal_date": pd.Timestamp(candidate["candidate_signal_date"]).strftime("%Y-%m-%d"),
            "signal_information_date": str(candidate["candidate_signal_information_date"]),
            "fast_score": round(float(candidate["fast_score"]), 2),
            "pattern_score": candidate.get("pattern_a_score"),
            "entry_open": record["entry_open"],
            "exit_signal_date": record.get("exit_signal_date"),
            "exit_type": record.get("exit_type"),
            "strategy_record": record,
        })
        if index % 100 == 0 or index == len(signals):
            print(f"signal exit authority: {index}/{len(signals)}", flush=True)

    result = pd.DataFrame(rows).sort_values(["signal_date", "signal_id"], kind="mergesort").reset_index(drop=True)
    return result, {
        "raw_candidate_rows": int(len(raw)),
        "abc_entry_pass_signal_rows": int(len(signals)),
        "signal_exit_authority_rows": int(len(result)),
        "signal_exit_authority_tickers": int(result["ticker"].nunique()),
        "repository_v2_local_loads": int(loader.load_count),
        "authority_hashes": _hash_authorities(),
        "daily_by_ticker": daily_by_ticker,
    }


def _build_calendar(daily_by_ticker: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    dates: set[pd.Timestamp] = set()
    for daily in daily_by_ticker.values():
        dates.update(
            pd.Timestamp(value).normalize()
            for value in daily.index
            if COMMON_START_DATE <= pd.Timestamp(value).normalize() <= SUPPORT_END
        )
    ordered = sorted(dates)
    if not ordered:
        raise RuntimeError("BLOCKED_DATA_GAP: empty portfolio calendar")
    first_by_week: dict[pd.Timestamp, pd.Timestamp] = {}
    last_by_week: dict[pd.Timestamp, pd.Timestamp] = {}
    for date in ordered:
        week = _week_start(date)
        first_by_week.setdefault(week, date)
        last_by_week[week] = date
    next_week: dict[pd.Timestamp, pd.Timestamp] = {}
    for week in sorted(first_by_week):
        later = [value for value in sorted(first_by_week) if value > week]
        if later:
            next_week[week] = first_by_week[later[0]]
    return {
        "dates": ordered,
        "first_by_week": first_by_week,
        "last_by_week": last_by_week,
        "next_week": next_week,
        "batch_dates": sorted(first_by_week.values()),
    }


def load_fresh_signal_authority() -> tuple[pd.DataFrame, dict[str, Any], Callable[[Mapping[str, Any]], dict[str, Any]]]:
    """Load raw/ABC fresh signals and lazily build their exit lifecycles.

    The completed No-Loss trade artifact remains a checksum-protected
    reference, never an entry-candidate source. Every ABC-passing raw signal
    is retained through portfolio dedupe/ranking. The strategy exit path is
    calculated only when a candidate actually executes, which keeps the
    cache-only correction bounded without changing the frozen strategy rules.
    """
    _validate_frozen_authorities()
    raw = pd.read_csv(RAW_PATH, dtype={"candidate_id": str, "ticker": str, "isu_cd": str, "market": str})
    authority, _ = frozen_runner.load_entry_authority(raw)
    fresh = _load_signal_authority(raw, authority)
    rows: list[dict[str, Any]] = []
    for row in fresh.to_dict(orient="records"):
        item = dict(row)
        item.update({
            "signal_id": str(row["candidate_id"]),
            "signal_date": pd.Timestamp(row["candidate_signal_date"]).strftime("%Y-%m-%d"),
            "signal_information_date": str(row["candidate_signal_information_date"]),
            "pattern_score": row.get("pattern_a_score"),
        })
        rows.append(item)
    signals = pd.DataFrame(rows).sort_values(["signal_date", "signal_id"], kind="mergesort").reset_index(drop=True)

    event_map = _load_fundamental_events()
    raw_tasks = _build_raw_task_map(raw)
    authority_payload = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority_payload)
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    repository = abc_return._candidate_repository(ROOT, raw, SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT_END)
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in sorted(signals["ticker"].astype(str).str.zfill(6).unique()):
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"BLOCKED_DATA_GAP: {ticker}")
        daily_by_ticker[ticker] = daily

    context_by_identity: dict[tuple[str, str, str, str, str], Any] = {}
    record_cache: dict[str, dict[str, Any]] = {}

    def strategy_record_for(candidate: Mapping[str, Any]) -> dict[str, Any]:
        signal_id = str(candidate["signal_id"])
        if signal_id in record_cache:
            return record_cache[signal_id]
        identity = _identity_key(candidate)
        task_key = (
            identity[0], identity[1], identity[2],
            str(candidate["identity_effective_from"]), str(candidate["identity_effective_to"]),
        )
        task = raw_tasks.get(task_key)
        if task is None:
            raise RuntimeError(f"BLOCKED_SIGNAL_AUTHORITY_TASK_GAP: {task_key}")
        ticker = identity[0]
        daily = daily_by_ticker[ticker]
        context = context_by_identity.get(task_key)
        if context is None:
            lifecycle = IdentityLifecycle(
                ticker=identity[0], isu_cd=identity[1], market=identity[2],
                effective_from=pd.Timestamp(task["effective_from"]),
                effective_to=pd.Timestamp(task["effective_to"]),
            )
            clipped = clip_to_identity_lifecycle(daily, lifecycle)
            context = build_precomputed_ticker_context(ticker, str(candidate.get("name") or ticker), clipped)
            context_by_identity[task_key] = context
        lifecycle = IdentityLifecycle(
            ticker=identity[0], isu_cd=identity[1], market=identity[2],
            effective_from=pd.Timestamp(task["effective_from"]),
            effective_to=pd.Timestamp(task["effective_to"]),
        )
        candidate_id = str(candidate["candidate_id"])

        def gate(_as_of: pd.Timestamp, context_values: dict[str, Any], *, candidate_id: str = candidate_id) -> dict[str, Any]:
            signal_date = pd.Timestamp(context_values["signal_date"]).normalize()
            return {
                "gate_pass": frozen_candidate_id(identity[0], identity[1], identity[2], signal_date) == candidate_id,
                "gate_id": "FROZEN_ABC_ENTRY_AUTHORITY",
            }

        def fundamental_callback(
            _signal: pd.Timestamp,
            _entry_exec: pd.Timestamp,
            _identity_daily: pd.DataFrame,
            *,
            key: tuple[str, str, str] = identity,
        ) -> list[Mapping[str, Any]]:
            return event_map.get(key, [])

        records = simulate_ticker_strategy_fundamentals_v01(
            strategy_id=STRATEGY_ID,
            ticker=identity[0], isu_cd=identity[1], name=str(candidate.get("name") or ticker),
            market=identity[2], daily=daily, raw_panel=task["raw_panel"],
            score_contract=score_contract, stage_contract=stage_contract,
            loss_guard_enabled=False, backtest_end=SUPPORT_END,
            entry_eligible_from=COMMON_START_DATE,
            allowed_signal_dates={pd.Timestamp(candidate["candidate_signal_date"]).normalize()},
            snapshot_context=context, identity_lifecycle=lifecycle,
            pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                intervals, ticker_value, isu_value, market_value, value,
            ),
            entry_gate=gate, fundamental_exit_callback=fundamental_callback,
        )
        if len(records) != 1:
            raise RuntimeError(f"BLOCKED_SIGNAL_EXIT_AUTHORITY_GAP: {signal_id}: {len(records)}")
        record = records[0].to_dict()
        if str(record["entry_signal_date"]) != str(candidate["signal_date"]):
            raise RuntimeError(f"BLOCKED_SIGNAL_DATE_DRIFT: {signal_id}")
        record_cache[signal_id] = record
        return record

    return signals, {
        "signal_authority_source": (
            f"{RAW_PATH.relative_to(ROOT)} + {ENTRY_AUTHORITY_PATH.relative_to(ROOT)} "
            "(classification=ABC_ENTRY_PASS)"
        ),
        "raw_candidate_rows": int(len(raw)),
        "fresh_entry_signal_rows": int(len(signals)),
        "fresh_entry_signal_tickers": int(signals["ticker"].nunique()),
        "signal_authority_rows": int(len(signals)),
        "signal_authority_tickers": int(signals["ticker"].nunique()),
        "strategy_simulation": "EXIT_LIFECYCLE_LAZY_PER_EXECUTED_FRESH_SIGNAL",
        "repository_v2_local_loads": int(loader.load_count),
        "authority_hashes": _hash_authorities(),
        "daily_by_ticker": daily_by_ticker,
    }, strategy_record_for


def _next_week_open(signal_date: Any, calendar: Mapping[str, Any]) -> pd.Timestamp | None:
    if signal_date is None or pd.isna(signal_date) or str(signal_date).strip() in {"", "NaT", "nan"}:
        return None
    return calendar["next_week"].get(_week_start(signal_date))


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
    original_shares: int
    cost_basis: float
    full_exit_signal_date: str | None
    full_exit_execution_date: str | None
    full_exit_type: str | None
    partial_profit_taken: bool = False
    partial_execution_date: str | None = None
    partial_sale_price: float | None = None
    partial_sold_shares: int = 0


def _event_row(
    *, portfolio: str, date: pd.Timestamp, event_type: str, ticker: str, name: str,
    signal_date: str | None, signal_type: str | None, open_price: float,
    shares_before: int, shares_delta: int, shares_after: int,
    cash_before: float, cash_delta: float, cash_after: float,
    position_cost_basis: float | None, realized_pnl: float | None,
    realized_return: float | None, partial_profit_taken: bool,
    portfolio_equity_after_execution: float,
) -> dict[str, Any]:
    return {
        "portfolio": portfolio, "execution_date": date.strftime("%Y-%m-%d"), "event_type": event_type,
        "ticker": ticker, "name": name, "signal_date": signal_date, "signal_type": signal_type,
        "open_price": round(open_price, 6), "shares_before": shares_before, "shares_delta": shares_delta,
        "shares_after": shares_after, "cash_before": round(cash_before, 6), "cash_delta": round(cash_delta, 6),
        "cash_after": round(cash_after, 6), "position_cost_basis": position_cost_basis,
        "realized_pnl": None if realized_pnl is None else round(realized_pnl, 6),
        "realized_return": None if realized_return is None else round(realized_return, 6),
        "partial_profit_taken": bool(partial_profit_taken),
        "portfolio_equity_after_execution": round(portfolio_equity_after_execution, 6),
    }


def _price(daily_by_ticker: Mapping[str, pd.DataFrame], ticker: str, date: pd.Timestamp, column: str) -> float:
    try:
        return _lookup_exact(daily_by_ticker[ticker], date, column)
    except RuntimeError as exc:
        raise RuntimeError(f"{ticker}: {exc}") from exc


def _price_asof(daily_by_ticker: Mapping[str, pd.DataFrame], ticker: str, date: pd.Timestamp, column: str) -> float:
    daily = daily_by_ticker[ticker]
    timestamp = pd.Timestamp(date).normalize()
    if timestamp in daily.index:
        return float(daily.loc[timestamp, column])
    prior = daily.loc[daily.index <= timestamp, column]
    if prior.empty:
        raise RuntimeError(f"BLOCKED_DATA_GAP: no as-of {column} price for {ticker} at {timestamp.date()}")
    return float(prior.iloc[-1])


def _portfolio_equity_at_open(
    cash: float, positions: Mapping[tuple[str, str, str], Position],
    daily_by_ticker: Mapping[str, pd.DataFrame], date: pd.Timestamp,
) -> float:
    value = cash
    for position in positions.values():
        value += position.shares * _price_asof(daily_by_ticker, position.ticker, date, "open")
    return value


def _dedupe_and_rank_candidates(
    signals: pd.DataFrame, calendar: Mapping[str, Any]
) -> tuple[dict[pd.Timestamp, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_batch: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for row in signals.to_dict(orient="records"):
        batch = _next_week_open(row["signal_date"], calendar)
        if batch is None or batch > SUPPORT_END:
            continue
        item = dict(row)
        item["scheduled_execution_date"] = batch
        by_batch[batch].append(item)
    selected: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    duplicate_audit: list[dict[str, Any]] = []
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
                duplicate_audit.append({**duplicate, "ranking": None, "precheck_result": "SKIP_DUPLICATE_WEEKLY_CANDIDATE"})
        # Apply the specified deterministic ranking without inventing a new score.
        winners.sort(key=lambda row: (-float(row["fast_score"]), -pd.Timestamp(row["signal_date"]).value, str(row["ticker"])))
        for ranking, row in enumerate(winners, 1):
            row["ranking"] = ranking
        selected[batch].extend(winners)
    return dict(selected), duplicate_audit


def _entry_audit_row(row: Mapping[str, Any], portfolio: str, ranking: int | None, result: str) -> dict[str, Any]:
    return {
        "portfolio": portfolio,
        "signal_id": row.get("signal_id"),
        "ticker": row.get("ticker"),
        "isu_cd": row.get("isu_cd"),
        "market": row.get("market"),
        "name": row.get("name"),
        "signal_date": row.get("signal_date"),
        "scheduled_execution_date": _iso(row.get("scheduled_execution_date")),
        "fast_score": row.get("fast_score"),
        "pattern_score": row.get("pattern_score"),
        "ranking": ranking,
        "execution_result": result,
    }


def _daily_curve(
    portfolio: str, calendar: Mapping[str, Any], cash_by_date: Mapping[pd.Timestamp, float],
    positions_by_date: Mapping[pd.Timestamp, Mapping[tuple[str, str, str], Position]],
    daily_by_ticker: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for date in calendar["dates"]:
        positions = positions_by_date.get(date, {})
        cash = float(cash_by_date.get(date, INITIAL_CAPITAL))
        invested = sum(
            position.shares * _price_asof(daily_by_ticker, position.ticker, date, "close")
            for position in positions.values()
        )
        equity = cash + invested
        rows.append({
            "portfolio": portfolio, "date": date.strftime("%Y-%m-%d"), "cash": round(cash, 6),
            "invested_market_value": round(invested, 6), "equity": round(equity, 6),
            "position_count": len(positions),
        })
    curve = pd.DataFrame(rows)
    curve["cash_ratio"] = curve["cash"] / curve["equity"]
    curve["invested_ratio"] = curve["invested_market_value"] / curve["equity"]
    curve["high_water_mark"] = curve["equity"].cummax()
    curve["drawdown_pct"] = (curve["equity"] / curve["high_water_mark"] - 1.0) * 100.0
    return curve


def _risk_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    trough_index = curve["drawdown_pct"].idxmin()
    trough = curve.loc[trough_index]
    prior = curve.loc[:trough_index]
    peak_index = prior["equity"].idxmax()
    peak_equity = float(prior.loc[peak_index, "equity"])
    recovery = curve.iloc[trough_index + 1 :]
    recovery_rows = recovery[recovery["equity"] >= peak_equity]
    recovery_date = recovery_rows.iloc[0]["date"] if not recovery_rows.empty else None
    return {
        "mdd_pct": round(abs(float(trough["drawdown_pct"])), 6),
        "mdd_start_date": str(curve.loc[peak_index, "date"]),
        "mdd_trough_date": str(trough["date"]),
        "mdd_recovery_date": recovery_date,
        "max_drawdown_duration_trading_days": int(trough_index - peak_index),
        "worst_drawdown_period": {
            "start": str(curve.loc[peak_index, "date"]),
            "trough": str(trough["date"]),
            "recovery": recovery_date,
        },
    }


def _annual_returns(curve: pd.DataFrame) -> dict[str, float | None]:
    frame = curve.copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    result: dict[str, float | None] = {}
    previous = float(INITIAL_CAPITAL)
    for year in range(2021, 2027):
        group = frame[frame["year"].eq(year)]
        if group.empty:
            result[str(year) if year < 2026 else "2026_YTD"] = None
            continue
        ending = float(group.iloc[-1]["equity"])
        key = str(year) if year < 2026 else "2026_YTD"
        result[key] = round((ending / previous - 1.0) * 100.0, 6)
        previous = ending
    return result


def _partial_effect(position_records: list[dict[str, Any]], daily_by_ticker: Mapping[str, pd.DataFrame], support_end: pd.Timestamp) -> dict[str, Any]:
    partials = [row for row in position_records if row.get("partial_execution_date")]
    residual_100 = 0
    residual_200 = 0
    drag = 0.0
    additional_returns: list[float] = []
    cash_realized = 0.0
    for row in partials:
        ticker = str(row["ticker"])
        entry = float(row["entry_open"])
        partial_price = float(row["partial_sale_price"])
        shares_sold = int(row["partial_sold_shares"])
        cash_realized += partial_price * shares_sold
        daily = daily_by_ticker[ticker]
        after = daily.loc[pd.Timestamp(row["partial_execution_date"]):pd.Timestamp(support_end)]
        max_return = float((after["high"].max() / entry - 1.0) * 100.0) if not after.empty else 0.0
        residual_100 += int(max_return >= 100.0)
        residual_200 += int(max_return >= 200.0)
        terminal_price = float(row.get("final_valuation_price") or partial_price)
        drag += shares_sold * (terminal_price - partial_price)
        additional_returns.append(round((terminal_price / partial_price - 1.0) * 100.0, 6))
    return {
        "partial_profit_positions_count": len(partials),
        "partial_profit_transactions_count": len(partials),
        "cash_realized_by_partial_profits": round(cash_realized, 6),
        "residual_positions_reaching_ge_100_pct": residual_100,
        "residual_positions_reaching_ge_200_pct": residual_200,
        "partial_sold_before_final_valuation_pnl_drag_estimate": round(drag, 6),
        "residual_additional_return_mean_pct": round(sum(additional_returns) / len(additional_returns), 6) if additional_returns else None,
        "causal_reinvestment_split": "NOT_ISOLATED; A/B entry paths are cash-dependent",
    }


def _portfolio_summary(
    portfolio: str, curve: pd.DataFrame, events: pd.DataFrame, audits: pd.DataFrame,
    position_records: list[dict[str, Any]], daily_by_ticker: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    final_equity = float(curve.iloc[-1]["equity"])
    elapsed_days = (pd.Timestamp(curve.iloc[-1]["date"]) - pd.Timestamp(curve.iloc[0]["date"])).days
    total_return = final_equity / INITIAL_CAPITAL - 1.0
    cagr = (final_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0 if elapsed_days > 0 else 0.0
    event_types = events.get("event_type", pd.Series(dtype=str))
    full_exits = events[event_types.eq("FULL_EXIT")] if not events.empty else events
    partials = events[event_types.eq("PARTIAL_PROFIT")] if not events.empty else events
    entries = events[event_types.eq("ENTRY")] if not events.empty else events
    cash_blocked = audits[audits["execution_result"].eq("SKIP_INSUFFICIENT_CASH")]
    active_skips = audits[audits["execution_result"].eq("SKIP_ACTIVE_POSITION")]
    same_open_skips = audits[audits["execution_result"].eq("SKIP_SAME_OPEN_REENTRY")]
    transaction_value = float(events["cash_delta"].abs().sum()) if not events.empty else 0.0
    return {
        "portfolio": portfolio,
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(final_equity, 6),
        "final_cash": round(float(curve.iloc[-1]["cash"]), 6),
        "final_invested_market_value": round(float(curve.iloc[-1]["invested_market_value"]), 6),
        "final_position_count": int(curve.iloc[-1]["position_count"]),
        "net_profit": round(final_equity - INITIAL_CAPITAL, 6),
        "total_return_pct": round(total_return * 100.0, 6),
        "CAGR_pct": round(cagr * 100.0, 6),
        **_risk_metrics(curve),
        "annual_returns_pct": _annual_returns(curve),
        "max_simultaneous_positions": int(curve["position_count"].max()),
        "average_positions": round(float(curve["position_count"].mean()), 6),
        "median_positions": round(float(curve["position_count"].median()), 6),
        "max_invested_capital": round(float(curve["invested_market_value"].max()), 6),
        "average_invested_capital": round(float(curve["invested_market_value"].mean()), 6),
        "capital_measure_definition": "invested capital is daily close market value of open shares",
        "average_cash": round(float(curve["cash"].mean()), 6),
        "average_cash_ratio": round(float(curve["cash_ratio"].mean()), 6),
        "minimum_cash": round(float(curve["cash"].min()), 6),
        "average_invested_ratio": round(float(curve["invested_ratio"].mean()), 6),
        "total_entries": int(len(entries)),
        "total_full_exits": int(len(full_exits)),
        "total_partial_exits": int(len(partials)),
        "total_fresh_entry_candidates": int(len(audits)),
        "cash_blocked_entry_count": int(len(cash_blocked)),
        "active_position_skipped_entry_count": int(len(active_skips)),
        "same_open_reentry_skipped_count": int(len(same_open_skips)),
        "duplicate_weekly_candidate_skipped_count": int(
            audits["execution_result"].eq("SKIP_DUPLICATE_WEEKLY_CANDIDATE").sum()
        ),
        "missing_execution_price_skipped_count": int(
            audits["execution_result"].eq("SKIP_MISSING_EXECUTION_PRICE").sum()
        ),
        "portfolio_turnover_krw": round(transaction_value, 6),
        "portfolio_turnover_ratio": round(transaction_value / INITIAL_CAPITAL, 6),
        "partial_profit_effect": _partial_effect(position_records, daily_by_ticker, SUPPORT_END),
        "execution_contract": {
            "commission": 0, "tax": 0, "slippage": 0,
            "initial_capital": INITIAL_CAPITAL, "position_cap": POSITION_CAP,
            "negative_cash": False, "fractional_shares": False,
        },
    }


def run_portfolio(
    signals: pd.DataFrame,
    calendar: Mapping[str, Any],
    daily_by_ticker: Mapping[str, pd.DataFrame],
    portfolio: str,
    strategy_record_factory: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected, duplicates = _dedupe_and_rank_candidates(signals, calendar)
    positions: dict[tuple[str, str, str], Position] = {}
    cash = float(INITIAL_CAPITAL)
    events: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    positions_by_date: dict[pd.Timestamp, dict[tuple[str, str, str], Position]] = {}
    cash_by_date: dict[pd.Timestamp, float] = {}
    position_records: list[dict[str, Any]] = []

    for duplicate in duplicates:
        audits.append(_entry_audit_row(duplicate, portfolio, None, "SKIP_DUPLICATE_WEEKLY_CANDIDATE"))

    for batch in calendar["batch_dates"]:
        if batch < COMMON_START_DATE or batch > SUPPORT_END:
            continue
        exited_tickers: set[tuple[str, str, str]] = set()
        open_prices: dict[str, float] = {}
        for identity, position in list(positions.items()):
            if position.full_exit_execution_date == batch.strftime("%Y-%m-%d"):
                price = _price(daily_by_ticker, position.ticker, batch, "open")
                cash_before = cash
                shares_before = position.shares
                proceeds = shares_before * price
                realized_pnl = shares_before * (price - position.cost_basis)
                realized_return = (price / position.cost_basis - 1.0) * 100.0
                cash += proceeds
                positions.pop(identity)
                exited_tickers.add(identity)
                open_prices[position.ticker] = price
                events.append(_event_row(
                    portfolio=portfolio, date=batch, event_type="FULL_EXIT", ticker=position.ticker, name=position.name,
                    signal_date=position.full_exit_signal_date, signal_type=position.full_exit_type, open_price=price,
                    shares_before=shares_before, shares_delta=-shares_before, shares_after=0,
                    cash_before=cash_before, cash_delta=proceeds, cash_after=cash,
                    position_cost_basis=position.cost_basis, realized_pnl=realized_pnl,
                    realized_return=realized_return, partial_profit_taken=position.partial_profit_taken,
                    portfolio_equity_after_execution=0.0,
                ))
                position_records.append({
                    **asdict(position), "final_valuation_price": price, "final_valuation_date": batch.strftime("%Y-%m-%d"),
                })

        if portfolio == PORTFOLIO_B:
            week = _week_start(batch)
            previous_last = calendar["last_by_week"].get(week - pd.to_timedelta(7, unit="D"))
            if previous_last is not None:
                for identity, position in list(positions.items()):
                    if position.partial_profit_taken or identity in exited_tickers:
                        continue
                    previous_close = _price_asof(daily_by_ticker, position.ticker, previous_last, "close")
                    if previous_close / position.cost_basis - 1.0 < 0.50:
                        continue
                    current_open = _price(daily_by_ticker, position.ticker, batch, "open")
                    qty = math.floor(position.shares * 0.5)
                    if qty <= 0:
                        continue
                    cash_before = cash
                    proceeds = qty * current_open
                    pnl = qty * (current_open - position.cost_basis)
                    cash += proceeds
                    shares_before = position.shares
                    position.shares -= qty
                    position.partial_profit_taken = True
                    position.partial_execution_date = batch.strftime("%Y-%m-%d")
                    position.partial_sale_price = current_open
                    position.partial_sold_shares = qty
                    open_prices[position.ticker] = current_open
                    events.append(_event_row(
                        portfolio=portfolio, date=batch, event_type="PARTIAL_PROFIT", ticker=position.ticker, name=position.name,
                        signal_date=position.entry_signal_date, signal_type="PROFIT_50_TRIGGER", open_price=current_open,
                        shares_before=shares_before, shares_delta=-qty, shares_after=position.shares,
                        cash_before=cash_before, cash_delta=proceeds, cash_after=cash,
                        position_cost_basis=position.cost_basis, realized_pnl=pnl,
                        realized_return=(current_open / position.cost_basis - 1.0) * 100.0,
                        partial_profit_taken=True, portfolio_equity_after_execution=0.0,
                    ))

        batch_candidates = selected.get(batch, [])
        for candidate in batch_candidates:
            identity = _identity_key(candidate)
            result = "EXECUTED"
            if identity in exited_tickers:
                result = "SKIP_SAME_OPEN_REENTRY"
            elif identity in positions:
                result = "SKIP_ACTIVE_POSITION"
            else:
                try:
                    price = _price(daily_by_ticker, identity[0], batch, "open")
                except RuntimeError:
                    result = "SKIP_MISSING_EXECUTION_PRICE"
                else:
                    requested_cash = min(float(POSITION_CAP), cash)
                    shares = math.floor(requested_cash / price)
                    if shares <= 0:
                        result = "SKIP_INSUFFICIENT_CASH"
                    else:
                        cash_before = cash
                        cost = shares * price
                        cash -= cost
                        strategy_record = candidate.get("strategy_record")
                        if strategy_record is None:
                            if strategy_record_factory is None:
                                raise RuntimeError(f"BLOCKED_SIGNAL_EXIT_AUTHORITY_GAP: {candidate.get('signal_id')}")
                            strategy_record = strategy_record_factory(candidate)
                        exit_signal = strategy_record.get("exit_signal_date")
                        exit_exec = _next_week_open(exit_signal, calendar) if exit_signal else None
                        if exit_exec is not None and exit_exec <= batch:
                            exit_exec = None
                        position = Position(
                            signal_id=str(candidate["signal_id"]), ticker=identity[0], isu_cd=identity[1], market=identity[2],
                            name=str(candidate["name"]), entry_signal_date=str(candidate["signal_date"]),
                            entry_execution_date=batch.strftime("%Y-%m-%d"), entry_open=price, shares=shares,
                            original_shares=shares, cost_basis=price, full_exit_signal_date=exit_signal,
                            full_exit_execution_date=exit_exec.strftime("%Y-%m-%d") if exit_exec is not None else None,
                            full_exit_type=str(strategy_record.get("exit_type") or "") or None,
                        )
                        positions[identity] = position
                        open_prices[identity[0]] = price
                        events.append(_event_row(
                            portfolio=portfolio, date=batch, event_type="ENTRY", ticker=identity[0], name=position.name,
                            signal_date=position.entry_signal_date, signal_type="ABC_FASTCORE_ENTRY", open_price=price,
                            shares_before=0, shares_delta=shares, shares_after=shares,
                            cash_before=cash_before, cash_delta=-cost, cash_after=cash,
                            position_cost_basis=price, realized_pnl=0.0, realized_return=0.0,
                            partial_profit_taken=False, portfolio_equity_after_execution=0.0,
                        ))
            audits.append(_entry_audit_row(candidate, portfolio, candidate.get("ranking"), result))

        equity_after = _portfolio_equity_at_open(cash, positions, daily_by_ticker, batch)
        for event in events:
            if event["execution_date"] == batch.strftime("%Y-%m-%d") and event["portfolio_equity_after_execution"] == 0.0:
                event["portfolio_equity_after_execution"] = round(equity_after, 6)
        positions_by_date[batch] = {key: Position(**asdict(value)) for key, value in positions.items()}
        cash_by_date[batch] = cash

    # Carry the post-execution state forward to every KRX trading day so the
    # equity curve is genuinely daily rather than weekly-point sampled.
    latest_positions: dict[tuple[str, str, str], Position] = {}
    latest_cash = float(INITIAL_CAPITAL)
    for date in calendar["dates"]:
        if date in positions_by_date:
            latest_positions = positions_by_date[date]
            latest_cash = cash_by_date[date]
        else:
            positions_by_date[date] = {
                key: Position(**asdict(value)) for key, value in latest_positions.items()
            }
            cash_by_date[date] = latest_cash

    final_date = pd.Timestamp(SUPPORT_END)
    if final_date not in positions_by_date:
        positions_by_date[final_date] = {
            key: Position(**asdict(value)) for key, value in latest_positions.items()
        }
        cash_by_date[final_date] = latest_cash
    for identity, position in positions.items():
        # A suspended/delisted holding may not print a new session exactly on
        # the global support date; mark it at the latest local close as of the
        # required 2026-08-21 valuation boundary.
        final_price = _price_asof(daily_by_ticker, position.ticker, final_date, "close")
        position_records.append({
            **asdict(position), "final_valuation_price": final_price, "final_valuation_date": final_date.strftime("%Y-%m-%d"),
        })

    curve = _daily_curve(portfolio, calendar, cash_by_date, positions_by_date, daily_by_ticker)
    event_frame = pd.DataFrame(events)
    audit_frame = pd.DataFrame(audits)
    summary = _portfolio_summary(portfolio, curve, event_frame, audit_frame, position_records, daily_by_ticker)
    return {
        "events": event_frame,
        "entry_audit": audit_frame,
        "equity_curve": curve,
        "summary": summary,
        "position_records": position_records,
    }


def _comparison(a: Mapping[str, Any], b: Mapping[str, Any], signal_meta: Mapping[str, Any]) -> dict[str, Any]:
    a_summary = a["summary"]
    b_summary = b["summary"]
    keys = ["final_equity", "net_profit", "total_return_pct", "CAGR_pct", "mdd_pct", "average_cash_ratio", "average_positions", "max_simultaneous_positions", "portfolio_turnover_ratio", "total_partial_exits"]
    delta = {key: round(float(b_summary[key]) - float(a_summary[key]), 6) for key in keys}
    return {
        "work_id": "FASTCORE_FUNDAMENTALS_ABC_JULIA_PORTFOLIO_BACKTEST_V01",
        "strategy_id": STRATEGY_ID,
        "signal_authority": signal_meta,
        "contract": {
            "initial_capital": INITIAL_CAPITAL, "position_cap": POSITION_CAP,
            "execution": "first KRX trading day of next calendar week at OPEN",
            "sell_before_buy": True, "no_signal_carry": True, "leverage": False,
            "commission": 0, "tax": 0, "slippage": 0,
        },
        "PORTFOLIO_A": a_summary,
        "PORTFOLIO_B": b_summary,
        "B_MINUS_A_DELTA": delta,
        "partial_profit_effect": b_summary["partial_profit_effect"],
        "causal_reinvestment_effect": "NOT_ISOLATED; A/B entry paths are cash-dependent",
    }


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def run_backtest() -> dict[str, Any]:
    signal_authority, signal_meta, strategy_record_factory = load_fresh_signal_authority()
    daily_by_ticker = signal_meta.pop("daily_by_ticker")
    calendar = _build_calendar(daily_by_ticker)
    portfolio_a = run_portfolio(
        signal_authority, calendar, daily_by_ticker, PORTFOLIO_A,
        strategy_record_factory=strategy_record_factory,
    )
    portfolio_b = run_portfolio(
        signal_authority, calendar, daily_by_ticker, PORTFOLIO_B,
        strategy_record_factory=strategy_record_factory,
    )
    comparison = _comparison(portfolio_a, portfolio_b, signal_meta)
    return {
        "signal_authority": signal_authority,
        "portfolio_a": portfolio_a,
        "portfolio_b": portfolio_b,
        "comparison": comparison,
        "daily_by_ticker": daily_by_ticker,
        "calendar": calendar,
    }


def write_outputs(result: Mapping[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a = result["portfolio_a"]
    b = result["portfolio_b"]
    _write_frame(OUT_DIR / "portfolio_a_events.csv", a["events"])
    _write_frame(OUT_DIR / "portfolio_a_equity_curve.csv", a["equity_curve"])
    _json_write(OUT_DIR / "portfolio_a_summary.json", a["summary"])
    _write_frame(OUT_DIR / "portfolio_b_events.csv", b["events"])
    _write_frame(OUT_DIR / "portfolio_b_equity_curve.csv", b["equity_curve"])
    _json_write(OUT_DIR / "portfolio_b_summary.json", b["summary"])
    _write_frame(OUT_DIR / "portfolio_entry_audit.csv", pd.concat([a["entry_audit"], b["entry_audit"],], ignore_index=True))
    partial_rows = [row for row in b["position_records"] if row.get("partial_execution_date")]
    _write_frame(OUT_DIR / "portfolio_b_partial_profit_audit.csv", pd.DataFrame(partial_rows))
    _json_write(OUT_DIR / "portfolio_ab_comparison.json", result["comparison"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run the cache-only portfolio backtest.")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    audit = abc_base.NetworkAudit()
    try:
        with abc_base.network_guard(audit):
            result = run_backtest()
        if audit.request_count != 0:
            raise RuntimeError(f"BLOCKED_NETWORK_LEAKAGE: {audit.request_count}")
        write_outputs(result)
        print(json.dumps({
            "status": "COMPLETE",
            "signal_authority_rows": len(result["signal_authority"]),
            "portfolio_a_final_equity": result["portfolio_a"]["summary"]["final_equity"],
            "portfolio_b_final_equity": result["portfolio_b"]["summary"]["final_equity"],
            "network_calls": audit.request_count,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"PORTFOLIO BACKTEST BLOCKED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
