#!/usr/bin/env python3
"""Exploratory current-survivor ETF comparison using exact KRX raw prices."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.backtest.snapshot_context import (  # noqa: E402
    build_historical_snapshot_from_context,
    build_precomputed_ticker_context,
)
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402
from trend_scanner.data.market_calendar import MarketCalendarAuthority  # noqa: E402
from trend_scanner.filters.investability import (  # noqa: E402
    InvestabilityEvaluationResult,
    InvestabilityStatus,
)
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a  # noqa: E402
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast  # noqa: E402
from trend_scanner.patterns.pattern_b_evaluator import (  # noqa: E402
    PatternBEvaluationStatus,
    evaluate_pattern_b,
)
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (  # noqa: E402
    simulate_ticker_core_v02_reentry,
)

STRATEGY_A_FAST = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
STRATEGY_SELECT = "PATTERN_B_SELECT_CORE_V01"
STRATEGY_JULIA = "JULIA_STRATEGY_V00"
STRATEGY_IDS = (STRATEGY_A_FAST, STRATEGY_SELECT, STRATEGY_JULIA)
DATA_SOURCE = "KRX_RAW_ETF_OHLCV"
ELIGIBILITY_POLICY_ID = "ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01"
CUTOFF = pd.Timestamp("2026-08-31")
EXECUTION_SUPPORT = pd.Timestamp("2026-09-01")
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
UNIVERSE_REL = Path(
    "artifacts/research/etf_current_survivors_raw_price_three_strategy_simple_backtest_v03/"
    "current_etf_universe_2026-09-29.csv"
)
OUTPUT_REL = UNIVERSE_REL.parent
SCORE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/"
    "pattern_a_fast_score_prototype_v01.json"
)
STAGE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/"
    "pattern_a_fast_stage_prototype_v01.json"
)
RAW_STORE_REL = Path("data/market/raw/krx_stocks/v01")
SAMPLE_TICKERS = ("069500", "451060", "0000D0", "122630", "114800")
SAMPLE_LABELS = {
    "069500": "old",
    "451060": "medium",
    "0000D0": "recent",
    "122630": "leverage",
    "114800": "inverse",
}
_WORKER: dict[str, Any] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _norm_ticker(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _load_universe(path: Path) -> list[dict[str, str]]:
    frame = pd.read_csv(path, dtype={"ticker": "string", "ISU_CD": "string"})
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = {"ticker", "isu_cd", "name", "listing_date"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"ETF_UNIVERSE_REQUIRED_COLUMNS_MISSING:{sorted(required - set(frame.columns))}")
    frame["ticker"] = frame["ticker"].map(_norm_ticker)
    frame["isu_cd"] = frame["isu_cd"].astype(str).str.strip().str.upper()
    frame["name"] = frame["name"].astype(str).str.strip()
    frame["listing_date"] = pd.to_datetime(frame["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if frame["ticker"].duplicated().any() or frame["isu_cd"].duplicated().any():
        raise RuntimeError("ETF_UNIVERSE_DUPLICATE_IDENTITY")
    if frame[list(required)].isna().any().any() or frame["listing_date"].eq("NaT").any():
        raise RuntimeError("ETF_UNIVERSE_IDENTITY_OR_LISTING_DATE_MISSING")
    if len(frame) != 1171:
        raise RuntimeError(f"ETF_UNIVERSE_COUNT_CHANGED:{len(frame)}")
    frame = frame.rename(columns={"isu_cd": "ISU_CD"})
    return frame.sort_values("ticker").to_dict("records")


def _calendar_from_dates(dates: list[str]) -> tuple[MarketCalendarAuthority, list[str]]:
    cutoff = _iso(CUTOFF)
    support = _iso(EXECUTION_SUPPORT)
    if cutoff not in dates or support not in dates:
        raise RuntimeError("KRX_CALENDAR_MISSING_CUTOFF_OR_EXECUTION_SUPPORT")
    date_index = pd.DatetimeIndex(pd.to_datetime(dates))
    by_month = pd.Series(date_index, index=date_index).groupby([date_index.year, date_index.month]).max()
    month_ends = sorted(
        date.strftime("%Y-%m-%d")
        for date in by_month.tolist()
        if date.normalize() <= CUTOFF
    )
    calendar = MarketCalendarAuthority(
        trading_dates=date_index,
        completed_month_ends=pd.DatetimeIndex(pd.to_datetime(month_ends)),
        source_name="KRX_RAW_KOSPI_EXCHANGE_SESSION_CALENDAR",
        metadata={"source": "KrxRawStockStore market=KOSPI"},
    )
    return calendar, month_ends


def _build_price_database(
    db_path: Path,
    store_root: Path,
    universe: list[dict[str, str]],
) -> dict[str, Any]:
    started = time.perf_counter()
    store = KrxRawStockStore(store_root)
    ticker_set = {row["ticker"] for row in universe}
    support = _iso(EXECUTION_SUPPORT)
    etf_manifest = store.list_manifest("ETF")
    calendar_manifest = store.list_manifest("KOSPI")
    failed_calendar_dates = [
        row["date"] for row in calendar_manifest
        if row["date"] <= support and row["status"] == "FAILED"
    ]
    if failed_calendar_dates:
        raise RuntimeError(f"KRX_CALENDAR_PARTITION_FAILED:{len(failed_calendar_dates)}")
    etf_dates = sorted(
        row["date"] for row in etf_manifest
        if row["date"] <= support and row["status"] == "COMPLETE"
    )
    calendar_dates = sorted(
        row["date"] for row in calendar_manifest
        if row["date"] <= support and row["status"] == "COMPLETE"
    )
    if not etf_dates or not calendar_dates:
        raise RuntimeError("KRX_RAW_DATE_MANIFEST_EMPTY")
    if _iso(CUTOFF) not in etf_dates or _iso(EXECUTION_SUPPORT) not in etf_dates:
        raise RuntimeError("KRX_RAW_ETF_MISSING_CUTOFF_OR_SUPPORT_PARTITION")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute(
            "CREATE TABLE bars (ticker TEXT NOT NULL, date TEXT NOT NULL, "
            "open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, "
            "volume REAL NOT NULL, trading_value REAL NOT NULL)"
        )
        connection.execute("BEGIN")
        row_count = 0
        cutoff_intersection: set[str] = set()
        support_intersection: set[str] = set()
        raw_only_at_cutoff: set[str] = set()
        for index, day in enumerate(etf_dates, start=1):
            snapshot = store.load_snapshot("ETF", day)
            if snapshot.empty:
                continue
            snapshot["ticker"] = snapshot["ticker"].map(_norm_ticker)
            if day == _iso(CUTOFF):
                present = set(snapshot["ticker"].astype(str))
                cutoff_intersection = present & ticker_set
                raw_only_at_cutoff = present - ticker_set
            elif day == _iso(EXECUTION_SUPPORT):
                support_intersection = set(snapshot["ticker"].astype(str)) & ticker_set
            selected = snapshot.loc[snapshot["ticker"].isin(ticker_set), [
                "ticker", "date", "open", "high", "low", "close", "volume", "trading_value"
            ]]
            if not selected.empty:
                rows = [
                    (
                        str(row.ticker), pd.Timestamp(row.date).strftime("%Y-%m-%d"),
                        float(row.open), float(row.high), float(row.low), float(row.close),
                        float(row.volume), float(row.trading_value),
                    )
                    for row in selected.itertuples(index=False)
                ]
                connection.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)", rows)
                row_count += len(rows)
            if index % 500 == 0:
                connection.commit()
                connection.execute("BEGIN")
        connection.commit()
        connection.execute("CREATE UNIQUE INDEX bars_by_ticker_date ON bars(ticker,date)")
        connection.commit()
    finally:
        connection.close()

    _calendar, month_ends = _calendar_from_dates(calendar_dates)
    return {
        "raw_etf_partition_count_through_support": len(etf_dates),
        "raw_etf_partition_first_date": etf_dates[0],
        "raw_etf_partition_last_date": etf_dates[-1],
        "krx_calendar_session_count_through_support": len(calendar_dates),
        "krx_calendar_first_date": calendar_dates[0],
        "krx_calendar_last_date": calendar_dates[-1],
        "krx_calendar_sha256": hashlib.sha256("\n".join(calendar_dates).encode()).hexdigest(),
        "completed_month_end_count_through_cutoff": len(month_ends),
        "current_universe_raw_ticker_date_row_count": row_count,
        "current_universe_tickers_with_cutoff_prices": len(cutoff_intersection),
        "current_universe_tickers_with_support_prices": len(support_intersection),
        "cutoff_raw_tickers_not_in_current_universe_count": len(raw_only_at_cutoff),
        "cutoff_raw_tickers_not_in_current_universe": sorted(raw_only_at_cutoff),
        "source_store_manifest_sha256": _sha256(store.manifest_path),
        "sqlite_database_bytes": db_path.stat().st_size,
        "database_build_seconds": round(time.perf_counter() - started, 3),
        "calendar_dates_internal": calendar_dates,
        "month_ends_internal": month_ends,
    }


def _read_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    score = json.loads((ROOT / SCORE_CONTRACT_REL).read_text(encoding="utf-8"))
    stage = json.loads((ROOT / STAGE_CONTRACT_REL).read_text(encoding="utf-8"))
    if not score or not stage:
        raise RuntimeError("PATTERN_A_FAST_CONTRACT_EMPTY")
    return score, stage


def _init_worker(
    db_path: str,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    calendar_dates: list[str],
    month_ends: list[str],
) -> None:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    calendar = MarketCalendarAuthority(
        trading_dates=pd.DatetimeIndex(pd.to_datetime(calendar_dates)),
        completed_month_ends=pd.DatetimeIndex(pd.to_datetime(month_ends)),
        source_name="KRX_RAW_KOSPI_EXCHANGE_SESSION_CALENDAR",
        metadata={"source": "KrxRawStockStore market=KOSPI"},
    )
    _WORKER.clear()
    _WORKER.update({
        "connection": connection, "score_contract": score_contract,
        "stage_contract": stage_contract, "calendar": calendar,
        "calendar_dates": calendar_dates,
        "calendar_positions": {date: index for index, date in enumerate(calendar_dates)},
        "month_ends": month_ends,
    })


def _load_ticker_daily(ticker: str) -> pd.DataFrame:
    frame = pd.read_sql_query(
        "SELECT date,open,high,low,close,volume,trading_value FROM bars WHERE ticker=? ORDER BY date",
        _WORKER["connection"], params=(ticker,),
    )
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "trading_value"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def _first_session_after(signal_date: str) -> str | None:
    dates = _WORKER["calendar_dates"]
    position = bisect_right(dates, str(signal_date)[:10])
    return dates[position] if position < len(dates) else None


def _raw_eligibility(
    daily: pd.DataFrame,
    listing_date: str,
    common_start: str | None,
) -> tuple[set[str], dict[str, dict[str, Any]], str | None, dict[str, Any]]:
    sessions = pd.DatetimeIndex(pd.to_datetime([
        day for day in _WORKER["calendar_dates"] if day <= _iso(CUTOFF)
    ]))
    aligned = daily.reindex(sessions)
    volumes = pd.to_numeric(aligned["volume"], errors="coerce")
    closes = pd.to_numeric(aligned["close"], errors="coerce")
    counts = volumes.rolling(window=20, min_periods=20).count()
    average_volume = volumes.rolling(window=20, min_periods=20).mean()
    listing = pd.Timestamp(listing_date)
    eligible: set[str] = set()
    metrics: dict[str, dict[str, Any]] = {}
    volume_ready_date = None
    for date in sessions:
        key = date.strftime("%Y-%m-%d")
        if counts.loc[date] == 20 and volume_ready_date is None:
            volume_ready_date = key
        if date < listing or date < listing + pd.DateOffset(years=2):
            continue
        avg = average_volume.loc[date]
        close = closes.loc[date]
        if not np.isfinite(avg) or not np.isfinite(close):
            continue
        metrics[key] = {"close": float(close), "avg_volume_20d": float(avg)}
        if common_start is not None and date >= pd.Timestamp(common_start) and close >= 1000 and avg >= 10000:
            eligible.add(key)
    audit = {
        "pit_volume_window": 20,
        "pit_volume_window_includes_signal_session": True,
        "pit_min_avg_volume_shares": 10000,
        "pit_min_close_krw": 1000,
        "listing_age_years": 2,
        "volume_ready_date": volume_ready_date,
        "eligible_signal_date_count": len(eligible),
    }
    return eligible, metrics, volume_ready_date, audit


def _fast_snapshot_ready(result: Mapping[str, Any]) -> bool:
    return bool(
        result.get("fast_machine_stage_status") == "READY"
        and result.get("fast_monthly_permission_state") not in (None, "UNAVAILABLE")
        and result.get("fast_daily_risk_state") not in (None, "UNAVAILABLE")
        and result.get("fast_score_status") in {"READY", "PARTIAL"}
        and result.get("pattern_a_evaluation_status") == "READY"
        and result.get("pattern_a_stage") not in (None, "", "UNAVAILABLE")
    )


def _find_fast_ready_date(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    context: Any,
    listing_date: str,
) -> tuple[str | None, int]:
    dates = set(daily.index)
    valid_weeks = [week for week in context.full_weekly.index if week in dates and week <= CUTOFF]
    evaluations = 0
    for week in valid_weeks:
        if week < pd.Timestamp(listing_date):
            continue
        result = evaluate_pattern_a_fast(
            ticker, name, daily, week,
            _WORKER["score_contract"], _WORKER["stage_contract"],
            context=context, market_calendar=_WORKER["calendar"],
        )
        evaluations += 1
        if _fast_snapshot_ready(result):
            return week.strftime("%Y-%m-%d"), evaluations
    return None, evaluations


def _market_month_observations(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    context: Any,
    listing_date: str,
) -> tuple[list[dict[str, Any]], str | None, int]:
    observations: list[dict[str, Any]] = []
    ready_date = None
    evaluations = 0
    for date in _WORKER["month_ends"]:
        if (
            date < listing_date
            or pd.Timestamp(date) < daily.index.min()
            or pd.Timestamp(date) > CUTOFF
        ):
            continue
        if pd.Timestamp(date) not in daily.index:
            raise RuntimeError(f"ETF_MISSING_EXACT_MONTH_END_ROW:{ticker}:{date}")
        b_result = evaluate_pattern_b(ticker, daily, date, name=name)
        snapshot = build_historical_snapshot_from_context(
            context, date, include_incomplete_periods=False,
            market_calendar=_WORKER["calendar"],
        )
        a_result = evaluate_pattern_a(snapshot)
        a_stage = a_result.stage.value.upper() if a_result.stage is not None else "UNAVAILABLE"
        a_score = float(a_result.score) if a_result.score is not None and math.isfinite(float(a_result.score)) else None
        b_state = (
            b_result.pattern_b_state
            if b_result.evaluation_status == PatternBEvaluationStatus.READY
            else None
        )
        observations.append({
            "date": date,
            "pattern_b_state": b_state,
            "pattern_b_status": b_result.evaluation_status.value,
            "pattern_a_stage": a_stage,
            "pattern_a_score": a_score,
            "pattern_b_monthly_last_bar": b_result.monthly_last_bar,
            "pattern_b_weekly_last_bar": b_result.weekly_last_bar,
        })
        evaluations += 1
        if ready_date is None and b_result.evaluation_status == PatternBEvaluationStatus.READY and a_stage != "UNAVAILABLE":
            ready_date = date
    return observations, ready_date, evaluations


def _resolve_previous_stage(
    observations: list[dict[str, Any]],
    trading_positions: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    from scripts.analyze_pattern_b_progressed_previous_pattern_a_stage_v01 import (
        _resolve_progressed_episode,
    )

    active_dates = [row["date"] for row in observations]
    stage_by_date = {row["date"]: row["pattern_a_stage"] for row in observations}
    snapshot_positions = {date: index for index, date in enumerate(active_dates)}
    result: dict[str, dict[str, Any]] = {}
    for observation in observations:
        if observation["pattern_a_stage"] == "PROGRESSED":
            result[observation["date"]] = _resolve_progressed_episode(
                active_dates, stage_by_date, observation["date"],
                snapshot_positions, trading_positions,
            )
    return result


def _trade_row(
    *,
    strategy_id: str,
    ticker: str,
    name: str,
    isu_cd: str,
    signal_date: str,
    entry_execution_date: str,
    entry_price: float,
    exit_signal_date: str | None,
    exit_execution_date: str | None,
    exit_price: float | None,
    terminal_date: str,
    terminal_price: float,
    exit_reason: str,
    trade_status: str,
    daily: pd.DataFrame,
    common_start: str,
    source_signal_details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if entry_price <= 0 or terminal_price <= 0:
        raise RuntimeError(f"NONPOSITIVE_TRADE_PRICE:{ticker}:{strategy_id}")
    expected_entry = _first_session_after(signal_date)
    if expected_entry != entry_execution_date:
        raise RuntimeError(
            f"ENTRY_NOT_FIRST_EXACT_KRX_SESSION:{ticker}:{strategy_id}:{signal_date}:{entry_execution_date}:{expected_entry}"
        )
    if pd.Timestamp(entry_execution_date) not in daily.index:
        raise RuntimeError(f"ENTRY_EXECUTION_ROW_MISSING:{ticker}:{strategy_id}:{entry_execution_date}")
    observed_entry = float(daily.loc[pd.Timestamp(entry_execution_date), "open"])
    if not math.isclose(entry_price, observed_entry, rel_tol=0, abs_tol=0.011):
        raise RuntimeError(f"ENTRY_OPEN_MISMATCH:{ticker}:{strategy_id}:{entry_execution_date}")
    if exit_signal_date is not None:
        expected_exit = _first_session_after(exit_signal_date)
        if exit_execution_date != expected_exit:
            raise RuntimeError(
                f"EXIT_NOT_FIRST_EXACT_KRX_SESSION:{ticker}:{strategy_id}:{exit_signal_date}:{exit_execution_date}:{expected_exit}"
            )
        if exit_execution_date is None or pd.Timestamp(exit_execution_date) not in daily.index:
            raise RuntimeError(f"EXIT_EXECUTION_ROW_MISSING:{ticker}:{strategy_id}:{exit_execution_date}")
        observed_exit = float(daily.loc[pd.Timestamp(exit_execution_date), "open"])
        if exit_price is None or not math.isclose(exit_price, observed_exit, rel_tol=0, abs_tol=0.011):
            raise RuntimeError(f"EXIT_OPEN_MISMATCH:{ticker}:{strategy_id}:{exit_execution_date}")

    gross_return = (terminal_price / entry_price - 1.0) * 100.0
    buy_cash = entry_price * (1.0 + SLIPPAGE_RATE) * (1.0 + COMMISSION_RATE)
    if trade_status == "REALIZED":
        sell_proceeds = float(exit_price) * (1.0 - SLIPPAGE_RATE) * (1.0 - COMMISSION_RATE)
        after_cost_return = (sell_proceeds / buy_cash - 1.0) * 100.0
    else:
        after_cost_return = (terminal_price / buy_cash - 1.0) * 100.0
    start_pos = _WORKER["calendar_positions"].get(entry_execution_date)
    end_pos = _WORKER["calendar_positions"].get(terminal_date)
    if start_pos is None or end_pos is None or end_pos < start_pos:
        raise RuntimeError(f"INVALID_HOLDING_SESSION_RANGE:{ticker}:{entry_execution_date}:{terminal_date}")
    return {
        "strategy_id": strategy_id, "ticker": ticker, "name": name, "ISU_CD": isu_cd,
        "signal_date": signal_date, "entry_execution_date": entry_execution_date,
        "entry_price_raw_open": entry_price, "exit_signal_date": exit_signal_date,
        "exit_execution_date": exit_execution_date, "exit_or_terminal_date": terminal_date,
        "exit_price_raw_open": exit_price, "terminal_price_raw": terminal_price,
        "gross_return_pct": gross_return,
        "commission_slippage_pre_tax_return_pct": after_cost_return,
        "commission_rate_each_side": COMMISSION_RATE,
        "slippage_rate_each_side": SLIPPAGE_RATE, "ETF_sell_tax_rate": 0.0,
        "trade_status": trade_status, "exit_reason": exit_reason,
        "holding_krx_sessions_inclusive": end_pos - start_pos + 1,
        "common_evaluable_start": common_start, "cutoff_date": _iso(CUTOFF),
        "price_source": DATA_SOURCE, "eligibility_policy_id": ELIGIBILITY_POLICY_ID,
        "source_signal_details": json.dumps(source_signal_details or {}, ensure_ascii=False, sort_keys=True),
    }


def _run_select_core(
    ticker: str,
    name: str,
    isu_cd: str,
    daily: pd.DataFrame,
    observations: list[dict[str, Any]],
    common_start: str,
    eligible_dates: set[str],
    prior_stage_by_date: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cutoff, support = _iso(CUTOFF), _iso(EXECUTION_SUPPORT)
    by_date = {row["date"]: row for row in observations}
    candidates: set[str] = set()
    for observation in observations:
        date = observation["date"]
        previous_stage = prior_stage_by_date.get(date, {}).get("previous_pattern_a_stage")
        if (
            common_start <= date <= cutoff
            and date in eligible_dates
            and observation["pattern_b_state"] == "DEPRESSED"
            and observation["pattern_a_stage"] == "PROGRESSED"
            and previous_stage in {"EARLY_TREND", "TRANSITION"}
        ):
            execution = _first_session_after(date)
            if execution is not None and execution <= cutoff:
                candidates.add(date)

    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    for observation in observations:
        date = observation["date"]
        if position is not None and observation["pattern_b_state"] == "NORMAL":
            exit_execution = _first_session_after(date)
            if exit_execution is not None and exit_execution <= support:
                if pd.Timestamp(exit_execution) not in daily.index:
                    raise RuntimeError(f"SELECT_EXIT_MISSING_EXACT_OPEN:{ticker}:{date}:{exit_execution}")
                exit_price = float(daily.loc[pd.Timestamp(exit_execution), "open"])
                trades.append(_trade_row(
                    strategy_id=STRATEGY_SELECT, ticker=ticker, name=name, isu_cd=isu_cd,
                    signal_date=position["entry_signal_date"],
                    entry_execution_date=position["entry_execution_date"],
                    entry_price=position["entry_price"], exit_signal_date=date,
                    exit_execution_date=exit_execution, exit_price=exit_price,
                    terminal_date=exit_execution, terminal_price=exit_price,
                    exit_reason="PATTERN_B_NORMAL", trade_status="REALIZED", daily=daily,
                    common_start=common_start, source_signal_details=position["signal_details"],
                ))
                position = None
        if position is None and date in candidates:
            entry_execution = _first_session_after(date)
            if entry_execution is None or entry_execution > cutoff:
                continue
            if pd.Timestamp(entry_execution) not in daily.index:
                raise RuntimeError(f"SELECT_ENTRY_MISSING_EXACT_OPEN:{ticker}:{date}:{entry_execution}")
            position = {
                "entry_signal_date": date,
                "entry_execution_date": entry_execution,
                "entry_price": float(daily.loc[pd.Timestamp(entry_execution), "open"]),
                "signal_details": {
                    "previous_pattern_a_stage": prior_stage_by_date[date]["previous_pattern_a_stage"],
                    "previous_pattern_a_stage_date": prior_stage_by_date[date]["previous_pattern_a_stage_date"],
                    "pattern_b_state": by_date[date]["pattern_b_state"],
                    "pattern_a_stage": by_date[date]["pattern_a_stage"],
                },
            }
    if position is not None:
        if CUTOFF not in daily.index:
            raise RuntimeError(f"SELECT_OPEN_MISSING_EXACT_CUTOFF_CLOSE:{ticker}")
        close = float(daily.loc[CUTOFF, "close"])
        trades.append(_trade_row(
            strategy_id=STRATEGY_SELECT, ticker=ticker, name=name, isu_cd=isu_cd,
            signal_date=position["entry_signal_date"],
            entry_execution_date=position["entry_execution_date"],
            entry_price=position["entry_price"], exit_signal_date=None,
            exit_execution_date=None, exit_price=None, terminal_date=cutoff,
            terminal_price=close, exit_reason="OPEN_AT_CUTOFF_MARK",
            trade_status="OPEN_AT_CUTOFF", daily=daily, common_start=common_start,
            source_signal_details=position["signal_details"],
        ))
    return trades


def _normalize_strategy_trade(
    record: Any,
    strategy_id: str,
    ticker: str,
    name: str,
    isu_cd: str,
    daily: pd.DataFrame,
    common_start: str,
) -> dict[str, Any]:
    entry_signal = _iso(record.entry_signal_date)
    entry_date = _iso(record.entry_execution_date)
    entry_price = float(record.entry_open)
    status = str(record.trade_status)
    exit_signal = _iso(record.exit_signal_date) if record.exit_signal_date else None
    exit_date = _iso(record.exit_execution_date) if record.exit_execution_date else None
    exit_price = float(record.exit_price) if record.exit_price is not None else None
    support_fill = False

    # Julia V00 uses one date for valuation and execution support. Run at the
    # exact 8/31 valuation cutoff, then settle only an existing exit on 9/1.
    if strategy_id == STRATEGY_JULIA and status == "OPEN_AT_CUTOFF" and exit_signal:
        expected = _first_session_after(exit_signal)
        if expected is not None and expected <= _iso(EXECUTION_SUPPORT):
            if pd.Timestamp(expected) not in daily.index:
                raise RuntimeError(f"JULIA_EXIT_SUPPORT_OPEN_MISSING:{ticker}:{exit_signal}:{expected}")
            exit_date = expected
            exit_price = float(daily.loc[pd.Timestamp(expected), "open"])
            status = "REALIZED"
            support_fill = expected > _iso(CUTOFF)

    if status == "REALIZED":
        if exit_signal is None or exit_date is None or exit_price is None:
            raise RuntimeError(f"REALIZED_TRADE_MISSING_EXIT:{ticker}:{strategy_id}")
        terminal_date, terminal_price = exit_date, exit_price
    else:
        if CUTOFF not in daily.index:
            raise RuntimeError(f"OPEN_TRADE_MISSING_CUTOFF_CLOSE:{ticker}:{strategy_id}")
        terminal_date, terminal_price = _iso(CUTOFF), float(daily.loc[CUTOFF, "close"])

    row = _trade_row(
        strategy_id=strategy_id, ticker=ticker, name=name, isu_cd=isu_cd,
        signal_date=entry_signal, entry_execution_date=entry_date,
        entry_price=entry_price,
        exit_signal_date=exit_signal if status == "REALIZED" else None,
        exit_execution_date=exit_date if status == "REALIZED" else None,
        exit_price=exit_price if status == "REALIZED" else None,
        terminal_date=terminal_date, terminal_price=terminal_price,
        exit_reason=str(record.exit_type or "OPEN_AT_CUTOFF_MARK"),
        trade_status=status, daily=daily, common_start=common_start,
        source_signal_details={
            "canonical_trade_id": getattr(record, "trade_id", None),
            "canonical_entry_stage": getattr(record, "entry_pattern_a_stage", None),
            "canonical_exit_type": getattr(record, "exit_type", None),
            "julia_support_fill_adapter": support_fill,
        },
    )
    if entry_signal < common_start:
        raise RuntimeError(f"TRADE_BEFORE_COMMON_EVALUABLE_START:{ticker}:{strategy_id}:{entry_signal}:{common_start}")
    if entry_date > _iso(CUTOFF):
        raise RuntimeError(f"POST_CUTOFF_NEW_ENTRY:{ticker}:{strategy_id}:{entry_date}")
    return row


def _metric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").dropna()
    numbers = numbers[np.isfinite(numbers)]
    if numbers.empty:
        return {
            "n": 0, "positive_rate_pct": None, "mean_pct": None, "median_pct": None,
            "p10_pct": None, "p25_pct": None, "p50_pct": None,
            "p75_pct": None, "p90_pct": None,
        }
    return {
        "n": int(len(numbers)),
        "positive_rate_pct": float((numbers > 0).mean() * 100),
        "mean_pct": float(numbers.mean()), "median_pct": float(numbers.median()),
        "p10_pct": float(np.percentile(numbers, 10)),
        "p25_pct": float(np.percentile(numbers, 25)),
        "p50_pct": float(np.percentile(numbers, 50)),
        "p75_pct": float(np.percentile(numbers, 75)),
        "p90_pct": float(np.percentile(numbers, 90)),
    }


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    numbers = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").dropna()
    numbers = numbers[np.isfinite(numbers)]
    if numbers.empty:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "p90": None, "max": None}
    return {
        "n": int(len(numbers)), "min": float(numbers.min()),
        "p25": float(np.percentile(numbers, 25)), "median": float(numbers.median()),
        "p75": float(np.percentile(numbers, 75)), "p90": float(np.percentile(numbers, 90)),
        "max": float(numbers.max()),
    }


RETURN_THRESHOLDS = {
    "ge_20_pct": ("ge", 20.0), "ge_50_pct": ("ge", 50.0), "ge_100_pct": ("ge", 100.0),
    "le_15_pct": ("le", -15.0), "le_30_pct": ("le", -30.0),
    "le_40_pct": ("le", -40.0), "le_50_pct": ("le", -50.0),
}


def _strategy_summary(
    strategy_id: str,
    trades: list[dict[str, Any]],
    evaluable_instruments: list[dict[str, Any]],
) -> dict[str, Any]:
    returns = [row["gross_return_pct"] for row in trades]
    cost_returns = [row["commission_slippage_pre_tax_return_pct"] for row in trades]
    closed = [row for row in trades if row["trade_status"] == "REALIZED"]
    opened = [row for row in trades if row["trade_status"] == "OPEN_AT_CUTOFF"]
    per_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in trades:
        per_ticker.setdefault(row["ticker"], []).append(row)
    per_etf_means = [
        float(np.mean([trade["gross_return_pct"] for trade in rows]))
        for rows in per_ticker.values()
    ]
    per_etf_positive = [
        float(np.mean([trade["gross_return_pct"] > 0 for trade in rows]) * 100)
        for rows in per_ticker.values()
    ]
    trade_counts = [len(per_ticker.get(row["ticker"], [])) for row in evaluable_instruments]
    years = [float(row["evaluable_years"]) for row in evaluable_instruments]
    summary = {
        "strategy_id": strategy_id,
        "trade_count": len(trades), "unique_etf_count": len(per_ticker),
        "closed_trade_count": len(closed), "open_at_cutoff_count": len(opened),
        "trade_weighted_all_positions_gross": _metric_summary(returns),
        "trade_weighted_closed_only_gross": _metric_summary(row["gross_return_pct"] for row in closed),
        "trade_weighted_all_positions_after_cost": _metric_summary(cost_returns),
        "average_holding_krx_sessions": (
            float(np.mean([row["holding_krx_sessions_inclusive"] for row in trades])) if trades else None
        ),
        "median_holding_krx_sessions": (
            float(np.median([row["holding_krx_sessions_inclusive"] for row in trades])) if trades else None
        ),
        "average_realized_holding_krx_sessions": (
            float(np.mean([row["holding_krx_sessions_inclusive"] for row in closed])) if closed else None
        ),
        "median_realized_holding_krx_sessions": (
            float(np.median([row["holding_krx_sessions_inclusive"] for row in closed])) if closed else None
        ),
        "winner_tail": {},
        "etf_weighted": {
            "etf_count_with_trades": len(per_ticker),
            "median_etf_mean_trade_return_pct": float(np.median(per_etf_means)) if per_etf_means else None,
            "median_etf_positive_rate_pct": float(np.median(per_etf_positive)) if per_etf_positive else None,
            "trade_count_distribution_all_evaluable_etfs_including_zero_trade": _distribution(trade_counts),
            "evaluable_years_distribution": _distribution(years),
        },
    }
    for key, (direction, threshold) in RETURN_THRESHOLDS.items():
        count = sum(
            value >= threshold if direction == "ge" else value <= threshold
            for value in returns
        )
        summary["winner_tail"][key] = {
            "count": int(count), "rate_pct": float(count / len(returns) * 100) if returns else None,
        }
    return summary


def _serialize_instrument(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ticker": row["ticker"], "ISU_CD": row["ISU_CD"], "name": row["name"],
        "listing_date": row["listing_date"], "status": row.get("status"),
        "reason": row.get("reason"), "common_evaluable_start": row.get("common_evaluable_start"),
        "evaluable_end": row.get("evaluable_end"), "evaluable_years": row.get("evaluable_years"),
        "listing_age_at_cutoff_years": row.get("listing_age_at_cutoff_years"),
        "a_fast_ready_date": row.get("a_fast_ready_date"),
        "select_core_ready_date": row.get("select_core_ready_date"),
        "julia_ready_date": row.get("julia_ready_date"),
        "volume_20d_ready_date": row.get("volume_20d_ready_date"),
        "eligible_signal_date_count": row.get("eligible_signal_date_count"),
        "pattern_b_state_counts": row.get("pattern_b_state_counts"),
        "pattern_a_stage_counts": row.get("pattern_a_stage_counts"),
        "select_raw_candidate_count": row.get("select_raw_candidate_count"),
        "select_pit_eligible_candidate_count": row.get("select_pit_eligible_candidate_count"),
        "price_first_date": row.get("price_first_date"), "price_last_date": row.get("price_last_date"),
        "has_exact_cutoff_close": row.get("has_exact_cutoff_close"),
        "missing_session_count": row.get("missing_session_count"),
        "price_source": row.get("price_source", DATA_SOURCE),
        "eligibility_policy_id": row.get("eligibility_policy_id", ELIGIBILITY_POLICY_ID),
    }


def _validate_results(results: list[dict[str, Any]], universe: list[dict[str, str]]) -> dict[str, Any]:
    result_map = {row["ticker"]: row for row in results}
    universe_tickers = {row["ticker"] for row in universe}
    trades = [
        trade for result in results
        for strategy_trades in result.get("trades", {}).values()
        for trade in strategy_trades
    ]
    errors = [
        f"{row['ticker']}:{error}" for row in results
        for error in row.get("errors", [])
    ]
    process_error_tickers = sorted(
        row["ticker"] for row in results if row.get("status") == "PROCESS_ERROR"
    )
    error_patterns = Counter()
    for error in errors:
        body = error.split(":", 1)[1] if ":" in error else error
        first, separator, remainder = body.partition(":")
        pattern = remainder.partition(":")[0] if first == "WORKER_FAILURE" and separator else first
        error_patterns[pattern] += 1
    missing_tickers = sorted(universe_tickers - set(result_map))
    duplicate_results = len(results) - len(result_map)
    period_mismatches = []
    for result in results:
        if result.get("status") == "EVALUABLE":
            if result.get("common_evaluable_start") is None or result.get("evaluable_end") != _iso(CUTOFF):
                period_mismatches.append(result["ticker"])
        for strategy in STRATEGY_IDS:
            for trade in result.get("trades", {}).get(strategy, []):
                if trade["common_evaluable_start"] != result.get("common_evaluable_start"):
                    period_mismatches.append(f"{result['ticker']}:{strategy}:start")
                if trade["price_source"] != DATA_SOURCE:
                    period_mismatches.append(f"{result['ticker']}:{strategy}:source")
                if trade["eligibility_policy_id"] != ELIGIBILITY_POLICY_ID:
                    period_mismatches.append(f"{result['ticker']}:{strategy}:eligibility")
                if trade["signal_date"] > _iso(CUTOFF) or trade["entry_execution_date"] > _iso(CUTOFF):
                    errors.append(f"{result['ticker']}:{strategy}:POST_CUTOFF_NEW_ENTRY")
                if trade["signal_date"] < trade["common_evaluable_start"]:
                    errors.append(f"{result['ticker']}:{strategy}:ENTRY_BEFORE_COMMON_START")
                if trade["exit_execution_date"] and trade["exit_execution_date"] > _iso(EXECUTION_SUPPORT):
                    errors.append(f"{result['ticker']}:{strategy}:EXIT_AFTER_SUPPORT")
    gap_count = sum(int(row.get("missing_session_count", 0)) for row in results)
    all_preserved = len(result_map) == len(universe_tickers) and not missing_tickers
    return {
        "future_fallback_count": 0, "nearest_date_fallback_count": 0,
        "post_cutoff_new_entry_count": sum(
            1 for row in trades
            if row["signal_date"] > _iso(CUTOFF) or row["entry_execution_date"] > _iso(CUTOFF)
        ),
        "unauthorized_exclusion_count": len(missing_tickers),
        "current_universe_record_count": len(universe),
        "result_instrument_record_count": len(results),
        "duplicate_result_instrument_count": duplicate_results,
        "current_universe_all_records_preserved": all_preserved,
        "common_period_mismatch_count": len(set(period_mismatches)),
        "price_source_mismatch_count": sum(row["price_source"] != DATA_SOURCE for row in trades),
        "eligibility_policy_mismatch_count": sum(
            row["eligibility_policy_id"] != ELIGIBILITY_POLICY_ID for row in trades
        ),
        "raw_session_gap_count": gap_count, "trade_count": len(trades),
        "evaluable_instrument_count": sum(row.get("status") == "EVALUABLE" for row in results),
        "not_evaluable_instrument_count": sum(row.get("status") != "EVALUABLE" for row in results),
        "process_error_instrument_count": len(process_error_tickers),
        "process_error_tickers": process_error_tickers,
        "evaluator_error_pattern_counts": dict(sorted(error_patterns.items())),
        "evaluator_or_execution_errors": errors,
        "common_period_mismatch_instruments": sorted(set(period_mismatches)),
        "missing_result_tickers": missing_tickers,
        "passed": bool(
            all_preserved and duplicate_results == 0 and gap_count == 0
            and not errors and not period_mismatches
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _preflight_sample(
    output_dir: Path,
    db_path: Path,
    universe: list[dict[str, str]],
    data_info: dict[str, Any],
) -> dict[str, Any]:
    universe_by_ticker = {row["ticker"]: row for row in universe}
    selected = [universe_by_ticker[ticker] for ticker in SAMPLE_TICKERS if ticker in universe_by_ticker]
    if len(selected) != len(SAMPLE_TICKERS):
        missing = sorted(set(SAMPLE_TICKERS) - set(universe_by_ticker))
        raise RuntimeError(f"ETF_REPRESENTATIVE_SAMPLE_MISSING:{missing}")
    score, stage = _read_contracts()
    _init_worker(
        str(db_path), score, stage,
        data_info["calendar_dates_internal"], data_info["month_ends_internal"],
    )
    started = time.perf_counter()
    results = [_process_ticker(instrument) for instrument in selected]
    validation = _validate_results(results, selected)
    sample = {
        "verdict": "SAMPLE_PASS" if validation["passed"] else "CHECK_REQUIRED",
        "sample_basis": "five representative current ETFs: old, medium, recent, leverage, inverse",
        "sample_labels": SAMPLE_LABELS, "workers": 1,
        "cutoff_date": _iso(CUTOFF), "execution_support_date": _iso(EXECUTION_SUPPORT),
        "sample_count": len(results),
        "sample_rows": [
            {
                **_serialize_instrument(row),
                "sample_label": SAMPLE_LABELS[row["ticker"]],
                "evaluator_calls": {
                    "fast_readiness": row.get("fast_evaluator_calls_for_readiness"),
                    "pattern_b_monthly": row.get("pattern_b_evaluator_calls"),
                },
                "pattern_b_state_counts": row.get("pattern_b_state_counts"),
                "pattern_a_stage_counts": row.get("pattern_a_stage_counts"),
                "select_candidate_counts": {
                    "raw": row.get("select_raw_candidate_count"),
                    "pit_eligible": row.get("select_pit_eligible_candidate_count"),
                },
                "trade_counts": {strategy: len(row["trades"][strategy]) for strategy in STRATEGY_IDS},
                "timings": row.get("timings"), "errors": row.get("errors"),
            }
            for row in results
        ],
        "validation": validation,
        "data_source_preflight": {
            key: value for key, value in data_info.items() if not key.endswith("_internal")
        },
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(output_dir / "preflight_sample.json", sample)
    return sample


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    return f"{float(value):+,.{digits}f}%"


def _render_report(summary: Mapping[str, Any], top_bottom_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 현재 생존 KRX ETF raw 가격 3전략 단순 백테스트 V03", "",
        f"- 판정: {summary['verdict']}",
        f"- 범위: {summary['analysis_scope']}",
        f"- 현재 universe 기준일: {summary['snapshot_date']}",
        f"- 공통 종료일: {summary['cutoff_date']}; 청산 체결 지원일: {summary['execution_support_date']}",
        "- SURVIVORSHIP_BIAS = TRUE", "- RAW_PRICE_LIMITATION = TRUE", "",
    ]
    if summary.get("performance_metrics_status") == "PARTIAL_DIAGNOSTIC_ONLY":
        lines.extend([
            "> CHECK_REQUIRED: Pattern B input validation rejected raw OHLC rows for some ETFs. "
            "The aggregate metrics and top/bottom tables cover only successfully processed ETFs; "
            "do not interpret them as a full-universe comparison.", "",
        ])
    lines.extend(["## Universe", "",
        f"- 현재 ETF {summary['universe']['current_etf_count']:,}개. 상장일 포함률 100%.",
        f"- 공통 기간 계산 가능 ETF {summary['universe']['evaluable_etf_count']:,}개; 미평가 {summary['universe']['not_evaluable_etf_count']:,}개.",
        f"- 처리 오류 ETF {summary['validation'].get('process_error_instrument_count', 0):,}개.",
        "- 최근 상장으로 2년 요건을 채우지 못했거나 전략 evaluator 준비일이 cutoff를 넘은 ETF도 원장에 유지했어.", "",
        "## 방법 및 비용", "",
        "- ETF별 시작일은 상장 2년 경과, A FAST/Select/Julia ready, 20D 거래량 ready 중 가장 늦은 날이야. 세 전략은 같은 시작일~cutoff를 써.",
        "- 세 전략 모두 KRX raw ETF OHLCV를 사용했어. 신호일 다음 첫 exact KRX session 시가에 진입했고, cutoff 뒤 신규 진입은 금지했어.",
        "- 각 진입일에 raw 종가 1,000원 이상, 직전 20 KRX 세션 평균 raw 거래량 10,000주 이상, 상장 2년 이상을 검사했어.",
        "- 수수료는 매수·매도 각각 0.015%, 슬리피지는 매수 +0.1%·매도 -0.1%야. ETF 매도에 보통주 전용 세금은 적용하지 않았어.",
        "- 미청산 포지션은 8/31 raw 종가로 평가하고 진입 비용을 반영했어. gross와 비용 반영 수익률을 분리했어.",
        "- Pattern B에는 W의 raw-price override에 따라 raw OHLCV를 줬고, 기존 evaluator 공식과 state rule은 유지했어.", "",
        "## 3전략 비교", "",
        "| 전략 | 거래 수 | 거래 ETF | 미청산 | 승률 | 평균 gross | 중앙 gross | P10 | P25 | P75 | P90 | 보유 중앙 KRX 세션 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for strategy_id in STRATEGY_IDS:
        item = summary["strategies"][strategy_id]
        gross = item["trade_weighted_all_positions_gross"]
        lines.append(
            f"| {strategy_id} | {item['trade_count']:,} | {item['unique_etf_count']:,} | "
            f"{item['open_at_cutoff_count']:,} | {_fmt(gross['positive_rate_pct'])} | "
            f"{_fmt(gross['mean_pct'])} | {_fmt(gross['median_pct'])} | "
            f"{_fmt(gross['p10_pct'])} | {_fmt(gross['p25_pct'])} | "
            f"{_fmt(gross['p75_pct'])} | {_fmt(gross['p90_pct'])} | "
            f"{item['median_holding_krx_sessions'] or 'n/a'} |"
        )
    lines.extend(["", "## Winner / Tail", "",
                  "| 전략 | +20% | +50% | +100% | -15% | -30% | -40% | -50% |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for strategy_id in STRATEGY_IDS:
        tail = summary["strategies"][strategy_id]["winner_tail"]
        cells = [tail[key]["count"] for key in RETURN_THRESHOLDS]
        lines.append(f"| {strategy_id} | " + " | ".join(f"{count:,}" for count in cells) + " |")
    lines.extend(["", "## Top 10 / Bottom 10", ""])
    for strategy_id in STRATEGY_IDS:
        lines.extend([
            f"### {strategy_id}", "",
            "| 구분 | 순위 | 종목 | ETF | 신호일 | 진입일 | 종료/평가일 | gross | 종료 사유 |",
            "|---|---:|---|---|---|---|---|---:|---|",
        ])
        for row in (item for item in top_bottom_rows if item["strategy_id"] == strategy_id):
            lines.append(
                f"| {row['ranking']} | {row['rank']} | {row['ticker']} | {row['name']} | "
                f"{row['signal_date']} | {row['entry_execution_date']} | {row['exit_or_terminal_date']} | "
                f"{_fmt(row['gross_return_pct'])} | {row['exit_reason']} |"
            )
        lines.append("")
    validation = summary["validation"]
    lines.extend([
        "## Validation", "",
        f"- 전체 current ETF 원장 유지: {validation['current_universe_all_records_preserved']}",
        f"- 공통 기간 불일치: {validation['common_period_mismatch_count']}",
        f"- raw session 누락: {validation['raw_session_gap_count']}",
        f"- future / nearest-date fallback: {validation['future_fallback_count']} / {validation['nearest_date_fallback_count']}",
        f"- cutoff 이후 신규 진입: {validation['post_cutoff_new_entry_count']}",
        f"- 허용되지 않은 ETF 제외: {validation['unauthorized_exclusion_count']}",
        f"- evaluator/체결 오류: {len(validation['evaluator_or_execution_errors'])}",
        f"- 통과: {validation['passed']}", "",
        "## Runtime", "",
        f"- wall clock: {summary['runtime']['wall_clock_seconds']:.1f}초",
        f"- worker 10 stage time 합계: {json.dumps(summary['runtime'], ensure_ascii=False)}", "",
        "## 산출물", "",
        "- etf_readiness.csv: 전체 current ETF와 공통 기간/준비 상태",
        "- trade_ledger.csv: 세 전략의 독립 체결 및 terminal mark",
        "- top_bottom_trades.csv: 전략별 상·하위 10건",
        "- preflight_sample.json: 대표 ETF 5종 표본 및 체결 경계 확인",
        "- validation_report.json: 기계 검증 결과",
    ])
    return "\n".join(lines) + "\n"


def _run_full(
    output_dir: Path,
    db_path: Path,
    universe: list[dict[str, str]],
    data_info: dict[str, Any],
    workers: int,
) -> dict[str, Any]:
    if workers != 10:
        raise RuntimeError(f"FULL_RUN_REQUIRES_EXACTLY_10_WORKERS:{workers}")
    score, stage = _read_contracts()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    universe_by_ticker = {row["ticker"]: row for row in universe}
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker,
        initargs=(
            str(db_path), score, stage,
            data_info["calendar_dates_internal"], data_info["month_ends_internal"],
        ),
    ) as pool:
        futures = {pool.submit(_process_ticker, item): item["ticker"] for item in universe}
        for number, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                base = universe_by_ticker[ticker]
                results.append({
                    **base, "ticker": ticker, "status": "PROCESS_ERROR",
                    "reason": f"{type(exc).__name__}:{str(exc)[:500]}",
                    "trades": {strategy: [] for strategy in STRATEGY_IDS},
                    "errors": [f"WORKER_FAILURE:{type(exc).__name__}:{str(exc)[:500]}"],
                    "missing_session_count": 0,
                })
            if number % 50 == 0 or number == len(universe):
                print(f"Processed {number}/{len(universe)} current ETFs", flush=True)
    results.sort(key=lambda row: row["ticker"])
    validation = _validate_results(results, universe)
    all_trades = [
        trade for result in results
        for strategy_trades in result.get("trades", {}).values()
        for trade in strategy_trades
    ]
    trade_frame = pd.DataFrame(all_trades)
    if not trade_frame.empty:
        trade_frame.sort_values(
            ["strategy_id", "signal_date", "ticker", "entry_execution_date"],
            kind="mergesort",
        ).to_csv(output_dir / "trade_ledger.csv", index=False)
    pd.DataFrame([_serialize_instrument(row) for row in results]).sort_values(
        "ticker", kind="mergesort"
    ).to_csv(output_dir / "etf_readiness.csv", index=False)

    evaluable = [row for row in results if row.get("status") == "EVALUABLE"]
    strategy_summaries: dict[str, Any] = {}
    top_bottom_rows: list[dict[str, Any]] = []
    for strategy in STRATEGY_IDS:
        strategy_trades = [
            trade for result in results
            for trade in result.get("trades", {}).get(strategy, [])
        ]
        strategy_summaries[strategy] = _strategy_summary(strategy, strategy_trades, evaluable)
        ordered = sorted(
            strategy_trades,
            key=lambda row: (row["gross_return_pct"], row["ticker"], row["signal_date"]),
        )
        top_bottom_rows.extend(
            {"ranking": "BOTTOM_10", "rank": rank, **row}
            for rank, row in enumerate(ordered[:10], start=1)
        )
        top_bottom_rows.extend(
            {"ranking": "TOP_10", "rank": rank, **row}
            for rank, row in enumerate(reversed(ordered[-10:]), start=1)
        )
    pd.DataFrame(top_bottom_rows).to_csv(output_dir / "top_bottom_trades.csv", index=False)

    timing_rows = [row.get("timings", {}) for row in results]
    runtime = {
        stage_name: round(sum(float(item.get(stage_name, 0)) for item in timing_rows), 3)
        for stage_name in (
            "context_seconds", "readiness_seconds", "stage_history_seconds",
            "a_fast_seconds", "select_core_seconds", "julia_seconds",
        )
    }
    runtime["wall_clock_seconds"] = round(time.perf_counter() - started, 3)
    summary = {
        "verdict": (
            "ETF_CURRENT_SURVIVORS_RAW_PRICE_THREE_STRATEGY_SIMPLE_BACKTEST_COMPLETE"
            if validation["passed"] else "CHECK_REQUIRED"
        ),
        "analysis_scope": "EXPLORATORY / CURRENT_SURVIVORS / RAW_ETF_PRICE",
        "snapshot_date": "2026-09-29", "cutoff_date": _iso(CUTOFF),
        "execution_support_date": _iso(EXECUTION_SUPPORT),
        "SURVIVORSHIP_BIAS": True, "RAW_PRICE_LIMITATION": True,
        "adjusted_price_used": False,
        "performance_metrics_status": (
            "VALIDATED" if validation["passed"] else "PARTIAL_DIAGNOSTIC_ONLY"
        ),
        "aggregate_metrics_are_complete": bool(validation["passed"]),
        "blocked_reason": (
            None if validation["passed"] else
            "Pattern B rejected raw ETF OHLC rows with non-positive values for some current ETFs. "
            "Those symbols have PROCESS_ERROR rows, so the aggregate metrics cover only successfully "
            "processed ETFs and are not a complete universe comparison."
        ),
        "universe": {
            "current_etf_count": len(universe),
            "evaluable_etf_count": len(evaluable),
            "not_evaluable_etf_count": len(universe) - len(evaluable),
            "listing_date_coverage_count": sum(bool(row["listing_date"]) for row in universe),
            "listing_date_coverage_pct": 100.0,
            "all_current_etfs_retained_in_readiness_output": len(results) == len(universe),
        },
        "method": {
            "common_evaluable_start": "max(listing date + 2 years, A FAST ready date, Select Core ready date, Julia ready date, 20D volume ready date)",
            "common_evaluable_end": _iso(CUTOFF),
            "entry_eligibility": "Exact historical raw close >= 1000 KRW; trailing 20 KRX sessions average raw volume >= 10000 shares; listing age >= 2 years.",
            "entry_execution": "Signal EOD then the first exact KRX session open; entry execution no later than 2026-08-31.",
            "exit_execution_support": "An exit signaled on or before cutoff may fill through the first exact KRX session on 2026-09-01.",
            "strategy_rule_changes": "None. ETF admission and KRX calendar/cutoff adapters only.",
            "pattern_b_raw_input_override": "Pattern B V01 evaluator consumes raw ETF OHLCV as explicitly authorized; formulas and state rule are unchanged.",
            "period_exactness": "One per-ETF common start and cutoff shared by all three strategy replays.",
        },
        "cost_contract": {
            "buy_commission_rate": COMMISSION_RATE, "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE, "sell_slippage_rate": SLIPPAGE_RATE,
            "ETF_sell_tax_rate": 0.0, "equity_only_sell_tax_applied": False,
            "open_position_cost_treatment": "Exact cutoff raw close after entry cost; no hypothetical exit fee.",
            "return_contract": "Gross raw-price return and commission/slippage pre-tax return separately.",
        },
        "strategies": strategy_summaries, "validation": validation,
        "runtime": runtime,
        "data_source_preflight": {
            key: value for key, value in data_info.items() if not key.endswith("_internal")
        },
        "sample_preflight_verdict": (
            json.loads((output_dir / "preflight_sample.json").read_text(encoding="utf-8")).get("verdict")
            if (output_dir / "preflight_sample.json").exists() else None
        ),
        "artifact_files": [
            "current_etf_universe_2026-09-29.csv", "preflight_sample.json",
            "etf_readiness.csv", "trade_ledger.csv", "top_bottom_trades.csv",
            "full_summary.json", "validation_report.json", "full_report.md",
        ],
    }
    _write_json(output_dir / "full_summary.json", summary)
    _write_json(output_dir / "validation_report.json", validation)
    (output_dir / "full_report.md").write_text(
        _render_report(summary, top_bottom_rows), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true", help="run only the five-ETF preflight sample")
    mode.add_argument("--full", action="store_true", help="run the one complete 10-worker backtest")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=ROOT / OUTPUT_REL)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    universe_path = output_dir / UNIVERSE_REL.name
    if not universe_path.exists():
        raise RuntimeError(f"CURRENT_ETF_UNIVERSE_SNAPSHOT_MISSING:{universe_path}")
    universe = _load_universe(universe_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="etf_backtest_v03_") as temp_dir:
        db_path = Path(temp_dir) / "raw_etf_prices.sqlite3"
        data_info = _build_price_database(db_path, ROOT / RAW_STORE_REL, universe)
        if args.sample:
            sample = _preflight_sample(output_dir, db_path, universe, data_info)
            print(json.dumps({
                "verdict": sample["verdict"], "sample_count": sample["sample_count"],
                "runtime_seconds": sample["runtime_seconds"],
                "validation_passed": sample["validation"]["passed"],
            }, ensure_ascii=False))
            return 0 if sample["verdict"] == "SAMPLE_PASS" else 2
        if args.workers != 10:
            raise RuntimeError("FULL_RUN_REQUIRES_10_WORKERS")
        sample_path = output_dir / "preflight_sample.json"
        if not sample_path.exists():
            raise RuntimeError("FULL_RUN_BLOCKED_PREFLIGHT_SAMPLE_MISSING")
        sample_result = json.loads(sample_path.read_text(encoding="utf-8"))
        if sample_result.get("verdict") != "SAMPLE_PASS":
            raise RuntimeError("FULL_RUN_BLOCKED_PREFLIGHT_SAMPLE_NOT_PASS")
        summary = _run_full(output_dir, db_path, universe, data_info, workers=10)
        print(json.dumps({
            "verdict": summary["verdict"],
            "evaluable_etf_count": summary["universe"]["evaluable_etf_count"],
            "trade_counts": {
                key: value["trade_count"] for key, value in summary["strategies"].items()
            },
            "runtime_seconds": summary["runtime"]["wall_clock_seconds"],
            "validation_passed": summary["validation"]["passed"],
        }, ensure_ascii=False))
        return 0 if summary["verdict"] == "ETF_CURRENT_SURVIVORS_RAW_PRICE_THREE_STRATEGY_SIMPLE_BACKTEST_COMPLETE" else 2



def _run_julia(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    context: Any,
    common_start: str,
    eligible_dates: set[str],
    support_evaluator_errors: list[str],
) -> list[Any]:
    import trend_scanner.validation.julia_strategy_v00 as julia_module

    original_fast = julia_module.evaluate_pattern_a_fast
    original_snapshot = julia_module.build_historical_snapshot_from_context
    original_pattern_a = julia_module.evaluate_pattern_a
    original_investability = julia_module.evaluate_investability
    calendar = _WORKER["calendar"]
    ticker_dates = set(daily.index)

    def fast_with_calendar(*args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs["market_calendar"] = calendar
        try:
            return original_fast(*args, **kwargs)
        except Exception as exc:
            support_evaluator_errors.append(f"JULIA_FAST:{type(exc).__name__}:{str(exc)[:240]}")
            raise

    def snapshot_with_calendar(*args: Any, **kwargs: Any) -> Any:
        kwargs["market_calendar"] = calendar
        try:
            return original_snapshot(*args, **kwargs)
        except Exception as exc:
            support_evaluator_errors.append(f"JULIA_SNAPSHOT:{type(exc).__name__}:{str(exc)[:240]}")
            raise

    def pattern_a_with_audit(snapshot: Any) -> Any:
        try:
            return original_pattern_a(snapshot)
        except Exception as exc:
            support_evaluator_errors.append(f"JULIA_PATTERN_A:{type(exc).__name__}:{str(exc)[:240]}")
            raise

    def etf_investability(
        ticker: str, as_of: Any, daily: pd.DataFrame, **_kwargs: Any
    ) -> InvestabilityEvaluationResult:
        date = _iso(as_of)
        next_date = _first_session_after(date)
        exact_close = (
            float(daily.loc[pd.Timestamp(date), "close"])
            if pd.Timestamp(date) in ticker_dates else None
        )
        allowed = bool(
            date in eligible_dates and date >= common_start
            and next_date is not None and next_date <= _iso(CUTOFF)
            and pd.Timestamp(next_date) in ticker_dates
        )
        return InvestabilityEvaluationResult(
            ticker=ticker,
            as_of=date,
            status=InvestabilityStatus.INVESTABLE if allowed else InvestabilityStatus.DATA_UNAVAILABLE,
            reason="ETF_PIT_ELIGIBILITY_PASS" if allowed else "ETF_PIT_ELIGIBILITY_OR_NEXT_SESSION_FAIL",
            market_cap=None, market_cap_eok=None,
            avg_trading_value_20d=None, avg_trading_value_20d_eok=None,
            avg_trading_value_60d=None, avg_trading_value_60d_eok=None,
            close=exact_close, close_ready=exact_close is not None,
            market_cap_ready=False, trading_value_20d_ready=False,
            trading_value_60d_ready=False, data_ready=allowed,
            market_cap_effective_date=None,
            close_effective_date=date if exact_close is not None else None,
            tv20_last_observation_date=date if date in _WORKER["eligibility_metrics"] else None,
        )

    julia_module.evaluate_pattern_a_fast = fast_with_calendar
    julia_module.build_historical_snapshot_from_context = snapshot_with_calendar
    julia_module.evaluate_pattern_a = pattern_a_with_audit
    julia_module.evaluate_investability = etf_investability
    try:
        return julia_module.simulate_ticker_strategy_2022(
            ticker=ticker, name=name, market="ETF", daily=daily,
            score_contract=_WORKER["score_contract"],
            stage_contract=_WORKER["stage_contract"],
            enable_loss_guard=False, start_date=pd.Timestamp(common_start),
            cutoff_date=CUTOFF, snapshot_context=context,
            enable_pre_window_pruning=True,
        )
    finally:
        julia_module.evaluate_pattern_a_fast = original_fast
        julia_module.build_historical_snapshot_from_context = original_snapshot
        julia_module.evaluate_pattern_a = original_pattern_a
        julia_module.evaluate_investability = original_investability


def _process_ticker(instrument: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    ticker = _norm_ticker(instrument["ticker"])
    name, isu_cd = str(instrument["name"]), str(instrument["ISU_CD"])
    listing_date = _iso(instrument["listing_date"])
    errors: list[str] = []
    timings: dict[str, float] = {}
    daily = _load_ticker_daily(ticker)
    empty_trades = {strategy: [] for strategy in STRATEGY_IDS}
    if daily.empty:
        return {
            **instrument, "ticker": ticker, "status": "NOT_EVALUABLE",
            "reason": "NO_RAW_ETF_PRICE_HISTORY_THROUGH_CUTOFF",
            "common_evaluable_start": None, "evaluable_years": 0.0,
            "missing_session_count": 0, "trades": empty_trades, "errors": [], "timings": {},
        }
    daily = daily.loc[daily.index >= pd.Timestamp(listing_date)].copy()
    if daily.empty:
        return {
            **instrument, "ticker": ticker, "status": "NOT_EVALUABLE",
            "reason": "RAW_ROWS_PRECEDE_CURRENT_LISTING_DATE",
            "common_evaluable_start": None, "evaluable_years": 0.0,
            "missing_session_count": 0, "trades": empty_trades, "errors": [], "timings": {},
        }
    observed_dates = set(daily.index)
    cutoff_missing = CUTOFF not in daily.index
    raw_start = max(pd.Timestamp(daily.index.min()), pd.Timestamp(listing_date))
    expected_sessions = [
        pd.Timestamp(date) for date in _WORKER["calendar_dates"]
        if raw_start <= pd.Timestamp(date) <= EXECUTION_SUPPORT
    ]
    missing_dates = [
        date.strftime("%Y-%m-%d") for date in expected_sessions if date not in observed_dates
    ]
    cutoff_gaps = sum(pd.Timestamp(date) <= CUTOFF for date in missing_dates)
    if cutoff_gaps:
        errors.append(f"RAW_SESSION_GAP_THROUGH_CUTOFF:{cutoff_gaps}")
    if not cutoff_missing and EXECUTION_SUPPORT not in daily.index:
        errors.append("RAW_EXECUTION_SUPPORT_SESSION_MISSING")

    phase = time.perf_counter()
    context = build_precomputed_ticker_context(ticker, name, daily)
    timings["context_seconds"] = round(time.perf_counter() - phase, 4)

    readiness_start = time.perf_counter()
    fast_ready, fast_evaluations = _find_fast_ready_date(
        ticker, name, daily, context, listing_date
    )
    observations, select_ready, monthly_evaluations = _market_month_observations(
        ticker, name, daily, context, listing_date
    )
    _eligible, _eligibility_metrics, volume_ready, _eligibility_audit = _raw_eligibility(
        daily, listing_date, None
    )
    julia_ready = fast_ready
    listing_anniversary = (
        pd.Timestamp(listing_date) + pd.DateOffset(years=2)
    ).strftime("%Y-%m-%d")
    ready_dates = [fast_ready, select_ready, julia_ready, volume_ready, listing_anniversary]
    common_start = max(ready_dates) if all(ready_dates) else None
    timings["readiness_seconds"] = round(time.perf_counter() - readiness_start, 4)
    evaluable = bool(common_start and pd.Timestamp(common_start) <= CUTOFF and not cutoff_missing)
    reasons = []
    if pd.Timestamp(listing_date) + pd.DateOffset(years=2) > CUTOFF:
        reasons.append("LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF")
    if fast_ready is None:
        reasons.append("A_FAST_OR_JULIA_NOT_READY_BY_CUTOFF")
    if select_ready is None:
        reasons.append("SELECT_CORE_NOT_READY_BY_CUTOFF")
    if volume_ready is None:
        reasons.append("20D_VOLUME_WINDOW_NOT_READY_BY_CUTOFF")
    if cutoff_missing:
        reasons.append("MISSING_EXACT_CUTOFF_CLOSE")
    if common_start and pd.Timestamp(common_start) > CUTOFF:
        reasons.append("COMMON_START_AFTER_CUTOFF")
    status = "EVALUABLE" if evaluable else "NOT_EVALUABLE"
    eligible_dates: set[str] = set()
    eligibility_metrics: dict[str, dict[str, Any]] = {}
    eligibility_audit: dict[str, Any] = {}
    if common_start is not None:
        eligible_dates, eligibility_metrics, _, eligibility_audit = _raw_eligibility(
            daily, listing_date, common_start
        )
    _WORKER["eligibility_metrics"] = eligibility_metrics
    previous_stage = _resolve_previous_stage(
        observations, _WORKER["calendar_positions"]
    ) if observations else {}
    pattern_b_state_counts = dict(Counter(
        row["pattern_b_state"] or "UNAVAILABLE" for row in observations
    ))
    pattern_a_stage_counts = dict(Counter(
        row["pattern_a_stage"] for row in observations
    ))
    select_raw_candidate_count = 0
    select_pit_candidate_count = 0
    if common_start is not None:
        for observation in observations:
            date = observation["date"]
            prior = previous_stage.get(date, {}).get("previous_pattern_a_stage")
            if (
                date >= common_start and date <= _iso(CUTOFF)
                and observation["pattern_b_state"] == "DEPRESSED"
                and observation["pattern_a_stage"] == "PROGRESSED"
                and prior in {"EARLY_TREND", "TRANSITION"}
            ):
                select_raw_candidate_count += 1
                next_date = _first_session_after(date)
                if date in eligible_dates and next_date is not None and next_date <= _iso(CUTOFF):
                    select_pit_candidate_count += 1
    timings["stage_history_seconds"] = round(
        time.perf_counter() - readiness_start - timings["readiness_seconds"], 4
    )
    trades = empty_trades

    if evaluable:
        phase = time.perf_counter()
        core_result = simulate_ticker_core_v02_reentry(
            ticker=ticker, name=name, market="ETF", daily=daily,
            score_contract=_WORKER["score_contract"],
            stage_contract=_WORKER["stage_contract"],
            cutoff_date=CUTOFF, snapshot_context=context,
            market_calendar=_WORKER["calendar"],
            entry_search_start=pd.Timestamp(common_start),
            signal_cutoff_date=CUTOFF, execution_support_date=EXECUTION_SUPPORT,
            strict_errors=True, entry_execution_cutoff_date=CUTOFF,
            entry_signal_cutoff_date=CUTOFF,
            entry_signal_filter=lambda signal_date, _result: (
                signal_date.strftime("%Y-%m-%d") in eligible_dates
            ),
        )
        trades[STRATEGY_A_FAST] = [
            _normalize_strategy_trade(record, STRATEGY_A_FAST, ticker, name, isu_cd, daily, common_start)
            for record in core_result
        ]
        timings["a_fast_seconds"] = round(time.perf_counter() - phase, 4)
        phase = time.perf_counter()
        trades[STRATEGY_SELECT] = _run_select_core(
            ticker, name, isu_cd, daily, observations, common_start,
            eligible_dates, previous_stage,
        )
        timings["select_core_seconds"] = round(time.perf_counter() - phase, 4)
        julia_errors: list[str] = []
        phase = time.perf_counter()
        julia_result = _run_julia(
            ticker, name, daily, context, common_start,
            eligible_dates, julia_errors,
        )
        errors.extend(julia_errors)
        trades[STRATEGY_JULIA] = [
            _normalize_strategy_trade(record, STRATEGY_JULIA, ticker, name, isu_cd, daily, common_start)
            for record in julia_result
        ]
        timings["julia_seconds"] = round(time.perf_counter() - phase, 4)
    else:
        timings.update({"a_fast_seconds": 0.0, "select_core_seconds": 0.0, "julia_seconds": 0.0})

    for strategy_id, strategy_trades in trades.items():
        for trade in strategy_trades:
            if trade["signal_date"] not in eligible_dates:
                errors.append(f"TRADE_SIGNAL_FAILED_SHARED_PIT_ELIGIBILITY:{strategy_id}:{trade['signal_date']}")
            if trade["price_source"] != DATA_SOURCE or trade["eligibility_policy_id"] != ELIGIBILITY_POLICY_ID:
                errors.append(f"TRADE_CONTRACT_MISMATCH:{strategy_id}")
    for missing_date in missing_dates:
        if missing_date == _iso(EXECUTION_SUPPORT):
            errors.append("RAW_EXECUTION_SUPPORT_SESSION_MISSING")

    return {
        **instrument, "ticker": ticker, "status": status,
        "reason": ";".join(reasons) if reasons else None,
        "common_evaluable_start": common_start,
        "evaluable_end": _iso(CUTOFF) if evaluable else None,
        "evaluable_years": (
            (CUTOFF - pd.Timestamp(common_start)).days / 365.2425
            if evaluable and common_start else 0.0
        ),
        "listing_age_at_cutoff_years": (CUTOFF - pd.Timestamp(listing_date)).days / 365.2425,
        "a_fast_ready_date": fast_ready, "select_core_ready_date": select_ready,
        "julia_ready_date": julia_ready, "volume_20d_ready_date": volume_ready,
        "eligible_signal_date_count": len(eligible_dates),
        "eligibility_audit": eligibility_audit,
        "pattern_b_month_observation_count": len(observations),
        "pattern_b_state_counts": pattern_b_state_counts,
        "pattern_a_stage_counts": pattern_a_stage_counts,
        "select_raw_candidate_count": select_raw_candidate_count,
        "select_pit_eligible_candidate_count": select_pit_candidate_count,
        "pattern_b_evaluator_calls": monthly_evaluations,
        "fast_evaluator_calls_for_readiness": fast_evaluations,
        "price_first_date": _iso(daily.index.min()), "price_last_date": _iso(daily.index.max()),
        "has_exact_cutoff_close": not cutoff_missing,
        "missing_session_count": len(missing_dates), "missing_session_dates": missing_dates[:20],
        "trades": trades, "errors": errors,
        "timings": {**timings, "ticker_total_seconds": round(time.perf_counter() - started, 4)},
        "price_source": DATA_SOURCE, "eligibility_policy_id": ELIGIBILITY_POLICY_ID,
    }

if __name__ == "__main__":
    raise SystemExit(main())
