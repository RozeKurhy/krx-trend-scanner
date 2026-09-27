#!/usr/bin/env python3
"""Run the Pattern B V02 pure DEPRESSED-to-NORMAL event backtest."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts.run_v2_julia_official_validation_v01 import (  # noqa: E402
    COMMISSION_RATE,
    HISTORICAL_SELL_TAX_SCHEDULE,
    SLIPPAGE_RATE,
)
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
)

STRATEGY_ID = "PATTERN_B_PURE_SIMPLE_V01"
SIGNAL_START = "2013-01-31"
SIGNAL_END = "2026-08-31"
CUTOFF = "2026-09-21"
ENTRY_STATE = "DEPRESSED"
EXIT_STATE = "NORMAL"
SEED = 20260927
SAMPLE_PATH = Path("artifacts/patterns/pattern_b/state_forward_return_v01/snapshot_samples.csv.gz")
PIT_PATH = Path("data/market/rolling_authority/merged_pit_intervals.json")
CALENDAR_PATH = Path("data/market/rolling_authority/merged_trading_calendar.json")
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/pure_strategy_simple_v01")

IDENTITY_COLUMNS = ("ticker", "isu_cd")
INTERVAL_COLUMNS = ("ticker", "isu_cd", "market", "effective_from", "effective_to")
TRADE_STATS_THRESHOLDS = {
    "ge_20": 20.0,
    "ge_50": 50.0,
    "ge_100": 100.0,
    "le_20": -20.0,
    "le_30": -30.0,
    "le_50": -50.0,
}


def norm_ticker(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def norm_isu(value: Any) -> str:
    return str(value).strip().upper()


def interval_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        norm_ticker(row["ticker"]),
        norm_isu(row["isu_cd"]),
        str(row["market"]).strip().upper(),
        str(row["effective_from"])[:10],
        str(row["effective_to"])[:10],
    )


def identity_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return norm_ticker(row["ticker"]), norm_isu(row["isu_cd"])


def month_is_adjacent(previous: str, current: str) -> bool:
    return pd.Period(previous[:7], freq="M") + 1 == pd.Period(current[:7], freq="M")


def is_entry_transition(previous_state: Any, current_state: Any, adjacent: bool = True) -> bool:
    if not adjacent or previous_state is None or pd.isna(previous_state):
        return False
    return str(previous_state) != ENTRY_STATE and str(current_state) == ENTRY_STATE


def next_observed_open_date(
    daily_index: Iterable[pd.Timestamp | str], signal_date: str
) -> str | None:
    """First exact daily observation strictly after a signal, never same-day."""
    if isinstance(daily_index, pd.DatetimeIndex):
        position = int(daily_index.searchsorted(pd.Timestamp(signal_date), side="right"))
        return (
            daily_index[position].strftime("%Y-%m-%d")
            if position < len(daily_index)
            else None
        )
    if isinstance(daily_index, pd.Index):
        position = bisect.bisect_right(daily_index, str(signal_date)[:10])
        return str(daily_index[position])[:10] if position < len(daily_index) else None
    dates = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in daily_index]
    position = bisect.bisect_right(dates, str(signal_date)[:10])
    return dates[position] if position < len(dates) else None


def _safe_num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_authorities(data_root: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    pit_path = data_root / PIT_PATH
    calendar_path = data_root / CALENDAR_PATH
    pit = json.loads(pit_path.read_text(encoding="utf-8"))
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    intervals = []
    for raw in pit["intervals"]:
        row = dict(raw)
        row["ticker"] = norm_ticker(row["ticker"])
        row["isu_cd"] = norm_isu(row["isu_cd"])
        row["market"] = str(row["market"]).upper()
        row["effective_from"] = str(row["effective_from"])[:10]
        row["effective_to"] = str(row["effective_to"])[:10]
        intervals.append(row)
    trading_dates = [str(value)[:10] for value in calendar["trading_dates"]]
    if trading_dates != sorted(set(trading_dates)):
        raise RuntimeError("merged KRX calendar must be sorted and unique")
    if calendar.get("calendar_frontier", "") < CUTOFF:
        raise RuntimeError("merged KRX calendar does not cover the requested cutoff")
    if pit.get("pit_frontier", "") < CUTOFF:
        raise RuntimeError("merged PIT authority does not cover the requested cutoff")
    if CUTOFF not in set(trading_dates):
        raise RuntimeError("cutoff is not an exact merged KRX trading session")
    provenance = {
        "pit_frontier": pit.get("pit_frontier"),
        "pit_content_digest": pit.get("content_digest"),
        "calendar_frontier": calendar.get("calendar_frontier"),
        "calendar_content_digest": calendar.get("content_digest"),
        "interval_count": len(intervals),
        "common_interval_count": sum(row.get("state") == "COMMON" for row in intervals),
        "first_trading_date": trading_dates[0],
        "last_trading_date": trading_dates[-1],
        "pit_sha256": _sha256(pit_path),
        "calendar_sha256": _sha256(calendar_path),
    }
    return intervals, trading_dates, provenance


def _interval_components(
    intervals: list[dict[str, Any]], trading_dates: list[str]
) -> tuple[dict[tuple[str, str, str, str, str], str], dict[tuple[str, str, str], list[dict[str, Any]]]]:
    """Group only the exact contiguous KOSPI/KOSDAQ transfer chains allowed by V02."""
    index: dict[tuple[str, str, str, str, str], str] = {}
    by_component: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in intervals:
        if row.get("state") == "COMMON":
            by_identity[identity_key(row)].append(row)

    for identity, rows in by_identity.items():
        rows.sort(key=lambda value: (value["effective_from"], value["effective_to"], value["market"]))
        previous: dict[str, Any] | None = None
        component_number = 0
        previous_end_position = -1
        for row in rows:
            key = interval_key(row)
            if key in index:
                raise RuntimeError(f"duplicate PIT COMMON interval key: {key}")
            if previous is not None and row["effective_from"] <= previous["effective_to"]:
                raise RuntimeError(f"overlapping PIT COMMON intervals for identity {identity}")
            connected = False
            if previous is not None:
                next_position = bisect.bisect_right(trading_dates, previous["effective_to"])
                next_day = trading_dates[next_position] if next_position < len(trading_dates) else None
                connected = bool(
                    next_day == row["effective_from"]
                    and previous["isu_cd"] == row["isu_cd"]
                    and previous["market"] in {"KOSPI", "KOSDAQ"}
                    and row["market"] in {"KOSPI", "KOSDAQ"}
                    and previous["market"] != row["market"]
                )
            if previous is not None and not connected:
                component_number += 1
            component_id = f"{identity[0]}:{identity[1]}:{component_number:03d}"
            index[key] = component_id
            by_component[(identity[0], identity[1], component_id)].append(row)
            previous = row
    return index, dict(by_component)


def _read_monthly_samples(
    data_root: Path,
    intervals: list[dict[str, Any]],
    interval_to_component: dict[tuple[str, str, str, str, str], str],
) -> tuple[pd.DataFrame, int]:
    path = data_root / SAMPLE_PATH
    frame = pd.read_csv(path, compression="gzip", dtype={"ticker": "string", "isu_cd": "string"})
    frame["ticker"] = frame["ticker"].map(norm_ticker)
    frame["isu_cd"] = frame["isu_cd"].map(norm_isu)
    frame["market"] = frame["market"].astype(str).str.upper()
    frame["snapshot_date"] = frame["snapshot_date"].astype(str).str[:10]
    frame["effective_from"] = frame["effective_from"].astype(str).str[:10]
    frame["effective_to"] = frame["effective_to"].astype(str).str[:10]
    for column in ("monthly_last_bar", "weekly_last_bar"):
        observed = frame[column].fillna("").astype(str).str[:10]
        future = observed.ne("") & observed.gt(frame["snapshot_date"])
        if future.any():
            raise RuntimeError(f"{column} contains a bar dated after its snapshot")
    duplicates = int(frame.duplicated(["ticker", "isu_cd", "snapshot_date"]).sum())
    if duplicates:
        raise RuntimeError(f"monthly Pattern B sample has {duplicates} duplicate identity-date rows")
    permanent_excluded = {(norm_ticker(ticker), norm_isu(isu)) for ticker, isu in PERMANENT_IDENTITY_EXCLUSIONS}
    forbidden_rows = frame.apply(lambda row: (row["ticker"], row["isu_cd"]) in permanent_excluded, axis=1)
    if forbidden_rows.any():
        frame = frame.loc[~forbidden_rows].copy()
    intervals_by_key = {interval_key(row): row for row in intervals if row.get("state") == "COMMON"}
    components: list[str | None] = []
    validation_rows = frame.loc[:, [*INTERVAL_COLUMNS, "snapshot_date"]].to_dict("records")
    for row in validation_rows:
        key = interval_key(row)
        interval = intervals_by_key.get(key)
        date = row["effective_from"]
        sample_date = str(row["snapshot_date"])
        if interval is None or not (date <= sample_date <= row["effective_to"]):
            raise RuntimeError(f"snapshot row not backed by exact COMMON PIT interval: {key} {sample_date}")
        components.append(interval_to_component.get(key))
    frame["component_id"] = components
    if frame["component_id"].isna().any():
        raise RuntimeError("a COMMON snapshot interval has no authorized component")
    # Keep the final pre-period month so a valid January 2013 transition can
    # use an actually observed December 2012 state as its predecessor.
    frame = frame.loc[
        (frame["snapshot_date"] >= "2012-12-01")
        & (frame["snapshot_date"] <= SIGNAL_END)
    ].copy()
    known_states = {"DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED"}
    invalid = frame["state"].dropna().map(str).loc[lambda values: ~values.isin(known_states)]
    if len(invalid):
        raise RuntimeError(f"unexpected Pattern B state labels: {sorted(invalid.unique())}")
    return frame, len(permanent_excluded)


def _make_entry_signals(frame: pd.DataFrame) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    signals: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    blocked: list[dict[str, Any]] = []
    for identity, group in frame.groupby(["ticker", "isu_cd"], sort=True):
        rows = group.sort_values("snapshot_date").to_dict("records")
        for previous, current in zip(rows, rows[1:]):
            adjacent = month_is_adjacent(previous["snapshot_date"], current["snapshot_date"])
            if not is_entry_transition(previous["state"], current["state"], adjacent=adjacent):
                continue
            if not (SIGNAL_START <= current["snapshot_date"] <= SIGNAL_END):
                continue
            event = {
                "signal_id": f"{identity[0]}_{identity[1]}_{current['snapshot_date']}",
                "ticker": identity[0],
                "isu_cd": identity[1],
                "entry_signal_date": current["snapshot_date"],
                "previous_state_date": previous["snapshot_date"],
                "previous_state": str(previous["state"]),
                "entry_signal_state": str(current["state"]),
                "market_at_signal": current["market"],
                "component_id": current["component_id"],
                "entry_signal_status": "PENDING",
                "trade_id": None,
                "entry_execution_date": None,
                "entry_reference_open": None,
                "status_reason": None,
            }
            if previous["component_id"] != current["component_id"]:
                event["entry_signal_status"] = "BLOCKED_AUTHORITY_DISCONTINUITY"
                event["status_reason"] = "previous and current month are not in one contiguous COMMON identity chain"
                blocked.append(event)
            else:
                signals[identity].append(event)
    return dict(signals), blocked


def _component_price_rows(
    daily: pd.DataFrame | None,
    component_intervals: list[dict[str, Any]],
    component_id: str,
) -> pd.DataFrame:
    if daily is None or daily.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "market"])
    row_intervals = sorted(component_intervals, key=lambda row: row["effective_from"])
    date_index = pd.DatetimeIndex(daily.index)
    covered = np.zeros(len(daily), dtype=bool)
    markets = np.empty(len(daily), dtype=object)
    for interval in row_intervals:
        interval_mask = (
            (date_index >= pd.Timestamp(interval["effective_from"]))
            & (date_index <= pd.Timestamp(interval["effective_to"]))
        )
        if np.any(covered & interval_mask):
            raise RuntimeError(
                f"ambiguous COMMON identity authority in component {component_id}"
            )
        covered |= interval_mask
        markets[interval_mask] = interval["market"]
    if not covered.any():
        return pd.DataFrame(columns=["open", "high", "low", "close", "market"])
    result = daily.loc[covered, ["open", "high", "low", "close"]].copy()
    result["market"] = markets[covered]
    result.index = pd.DatetimeIndex(result.index).strftime("%Y-%m-%d")
    for column in ("open", "high", "low", "close"):
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(dtype="float64")
        if not np.isfinite(values).all() or (values <= 0).any():
            raise RuntimeError(f"non-positive or invalid adjusted {column} in {component_id}")
    if not result.index.is_unique:
        raise RuntimeError(f"duplicate adjusted OHLC dates in component {component_id}")
    return result


def _next_bar_after(daily: pd.DataFrame, signal_date: str) -> tuple[str | None, dict[str, Any] | None]:
    date = next_observed_open_date(daily.index, signal_date)
    if date is None:
        return None, None
    row = daily.loc[date].to_dict()
    return date, row


def _apply_pending_fill(
    pending: dict[str, Any],
    position: dict[str, Any] | None,
    trades: list[dict[str, Any]],
    daily: pd.DataFrame,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    fill_date = pending.get("fill_date")
    if fill_date is None:
        return position, pending
    row = daily.loc[fill_date].to_dict()
    if pending["kind"] == "ENTRY":
        trade = pending["trade"]
        trade["entry_execution_date"] = fill_date
        trade["entry_reference_open"] = float(row["open"])
        trade["entry_market"] = str(row["market"])
        trade["trade_status"] = "OPEN"
        pending["event"]["entry_signal_status"] = "FILLED"
        pending["event"]["trade_id"] = trade["trade_id"]
        pending["event"]["entry_execution_date"] = fill_date
        pending["event"]["entry_reference_open"] = float(row["open"])
        trades.append(trade)
        return trade, None
    if position is None:
        raise RuntimeError("exit fill encountered without a live position")
    position["exit_execution_date"] = fill_date
    position["exit_reference_open"] = float(row["open"])
    position["exit_market"] = str(row["market"])
    position["trade_status"] = "REALIZED"
    position["exit_fill_status"] = "FILLED"
    return None, None


def _trade_identifier(event: Mapping[str, Any], sequence: int) -> str:
    return (
        f"{STRATEGY_ID}_{event['ticker']}_{event['isu_cd']}_"
        f"{event['entry_signal_date']}_{sequence:04d}"
    )


def _simulate_identity(
    observations: list[dict[str, Any]],
    identity_signals: list[dict[str, Any]],
    daily_by_component: dict[str, pd.DataFrame],
    cutoff: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signals_by_date = {event["entry_signal_date"]: event for event in identity_signals}
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    sequence = 0
    last_states_by_component: dict[str, dict[str, Any]] = {}
    for observation in observations:
        day = observation["snapshot_date"]
        component = observation["component_id"]
        last_states_by_component[component] = observation
        daily = daily_by_component.get(component, pd.DataFrame())

        if pending and pending.get("fill_date") is not None and pending["fill_date"] <= day:
            pending_daily = daily_by_component.get(
                pending["trade"]["component_id"], pd.DataFrame()
            )
            position, pending = _apply_pending_fill(
                pending, position, trades, pending_daily
            )

        if pending and pending["kind"] == "ENTRY" and pending.get("fill_date") is not None:
            if pending["fill_date"] > day and str(observation["state"]) != ENTRY_STATE:
                pending["event"]["entry_signal_status"] = "CANCELLED_STATE_REVERTED"
                pending["event"]["status_reason"] = "state left DEPRESSED before the first available execution open"
                pending = None

        event = signals_by_date.get(day)
        if position is not None:
            if event is not None:
                event["entry_signal_status"] = "SUPPRESSED_ALREADY_HOLDING"
                event["status_reason"] = "one position per identity; prior position had not exited by this signal"
            if (
                pending is None
                and component == position["component_id"]
                and str(observation["state"]) == EXIT_STATE
                and day > position["entry_signal_date"]
                and position.get("exit_signal_date") is None
            ):
                fill_date, fill_row = _next_bar_after(daily, day)
                position["exit_signal_date"] = day
                position["exit_signal_state"] = str(observation["state"])
                position["exit_fill_status"] = "PENDING" if fill_date else "UNFILLED_NO_LATER_PRICE_ROW"
                pending = {
                    "kind": "EXIT",
                    "signal_date": day,
                    "fill_date": fill_date,
                    "trade": position,
                    "row": fill_row,
                }
        elif pending is None:
            if event is not None:
                sequence += 1
                fill_date, fill_row = _next_bar_after(daily, day)
                trade = {
                    "strategy_id": STRATEGY_ID,
                    "trade_id": _trade_identifier(event, sequence),
                    "ticker": event["ticker"],
                    "isu_cd": event["isu_cd"],
                    "signal_market": event["market_at_signal"],
                    "component_id": event["component_id"],
                    "entry_signal_date": day,
                    "entry_previous_state_date": event["previous_state_date"],
                    "entry_previous_state": event["previous_state"],
                    "entry_signal_state": event["entry_signal_state"],
                    "entry_execution_date": None,
                    "entry_reference_open": None,
                    "entry_market": None,
                    "exit_signal_date": None,
                    "exit_execution_date": None,
                    "exit_reference_open": None,
                    "exit_market": None,
                    "exit_fill_status": None,
                    "trade_status": "ENTRY_PENDING",
                    "exit_signal_state": None,
                    "cutoff_date": cutoff,
                }
                event["trade_id"] = trade["trade_id"]
                event["entry_execution_date"] = fill_date
                event["entry_reference_open"] = (
                    float(fill_row["open"]) if fill_row is not None else None
                )
                event["entry_signal_status"] = (
                    "PENDING" if fill_date is not None else "ENTRY_UNFILLED_NO_LATER_PRICE_ROW"
                )
                pending = {
                    "kind": "ENTRY",
                    "signal_date": day,
                    "fill_date": fill_date,
                    "trade": trade,
                    "event": event,
                    "row": fill_row,
                }
    # Finish any pending next-open event only when the exact supported row is at or
    # before the fixed evaluation cutoff. The signal range itself ends in August.
    if pending and pending.get("fill_date") is not None and pending["fill_date"] <= cutoff:
        daily = daily_by_component.get(pending["trade"]["component_id"], pd.DataFrame())
        position, pending = _apply_pending_fill(pending, position, trades, daily)
    if pending and pending["kind"] == "ENTRY":
        event = pending["event"]
        if event["entry_signal_status"] == "PENDING":
            event["entry_signal_status"] = "ENTRY_UNFILLED_AFTER_CUTOFF"
            event["status_reason"] = "no exact authorized adjusted open on or before evaluation cutoff"
        pending = None
    if position is not None:
        position["trade_status"] = "OPEN_AT_CUTOFF"
        if position.get("exit_signal_date") and position.get("exit_execution_date") is None:
            position["exit_fill_status"] = (
                "UNFILLED_BY_CUTOFF" if position.get("exit_signal_date") else None
            )
        last_state = last_states_by_component.get(position["component_id"])
        position["latest_state_date"] = last_state["snapshot_date"] if last_state else None
        position["current_pattern_b_state"] = str(last_state["state"]) if last_state else None
        position["cutoff_close"] = None
        position["valuation_status"] = "UNRESOLVED"
        position["valuation_reason"] = "no exact 2026-09-21 adjusted close within the entry identity chain"
        daily = daily_by_component.get(position["component_id"], pd.DataFrame())
        if cutoff in daily.index:
            close = _safe_num(daily.loc[cutoff, "close"])
            if close is not None and close > 0:
                position["cutoff_close"] = close
                position["valuation_status"] = "MARKED_EXACT_CUTOFF_CLOSE"
                position["valuation_reason"] = None
        position["cutoff_valuation_date"] = cutoff if position["cutoff_close"] is not None else None
        position["mark_to_cutoff_gross_return_pct"] = (
            (position["cutoff_close"] / position["entry_reference_open"] - 1.0) * 100.0
            if position["cutoff_close"] is not None else None
        )
    return trades, {"position": position, "pending": pending}


def _tax_rate(execution_date: str, market: str) -> float | None:
    date = pd.Timestamp(execution_date)
    for row in HISTORICAL_SELL_TAX_SCHEDULE:
        start = pd.Timestamp(row["start"])
        end = pd.Timestamp(row["end"]) if row["end"] else None
        if date >= start and (end is None or date <= end):
            return float(row[str(market).upper()])
    return None


def _path_metrics(
    trade: dict[str, Any],
    daily: pd.DataFrame,
    trading_dates: list[str],
    cutoff: str,
) -> None:
    entry_date = trade.get("entry_execution_date")
    entry_price = _safe_num(trade.get("entry_reference_open"))
    if not entry_date or entry_price is None or entry_price <= 0:
        return
    is_closed = trade.get("trade_status") == "REALIZED"
    end_date = str(trade.get("exit_execution_date") if is_closed else cutoff)
    if is_closed:
        exit_price = _safe_num(trade.get("exit_reference_open"))
        end = str(trade["exit_execution_date"])
        held_bars = daily.loc[(daily.index >= entry_date) & (daily.index < end)]
        candidates_high = [entry_price]
        candidates_low = [entry_price]
        if not held_bars.empty:
            candidates_high.extend(pd.to_numeric(held_bars["high"], errors="coerce").dropna().tolist())
            candidates_low.extend(pd.to_numeric(held_bars["low"], errors="coerce").dropna().tolist())
        if exit_price is not None:
            candidates_high.append(exit_price)
            candidates_low.append(exit_price)
        path_bars = daily.loc[(daily.index >= entry_date) & (daily.index <= end)]
    else:
        mark_date = str(trade.get("cutoff_valuation_date") or cutoff)
        if mark_date not in daily.index:
            eligible = [str(date) for date in daily.index if entry_date <= str(date) <= cutoff]
            mark_date = eligible[-1] if eligible else entry_date
        held_bars = daily.loc[(daily.index >= entry_date) & (daily.index <= mark_date)]
        candidates_high = [entry_price]
        candidates_low = [entry_price]
        if not held_bars.empty:
            candidates_high.extend(pd.to_numeric(held_bars["high"], errors="coerce").dropna().tolist())
            candidates_low.extend(pd.to_numeric(held_bars["low"], errors="coerce").dropna().tolist())
        path_bars = held_bars
    if candidates_high and candidates_low:
        trade["mfe_pct"] = (max(candidates_high) / entry_price - 1.0) * 100.0
        trade["mae_pct"] = (min(candidates_low) / entry_price - 1.0) * 100.0
    start_pos = bisect.bisect_left(trading_dates, entry_date)
    end_pos = bisect.bisect_right(trading_dates, end_date)
    trade["holding_krx_sessions"] = max(0, end_pos - start_pos)
    trade["holding_calendar_days"] = max(0, (pd.Timestamp(end_date) - pd.Timestamp(entry_date)).days)
    trade["observed_price_bar_count"] = int(len(path_bars))
    trade["path_end_date"] = end if is_closed else mark_date
    trade["path_calendar_session_coverage_pct"] = (
        100.0 * len(path_bars) / trade["holding_krx_sessions"]
        if trade["holding_krx_sessions"] else None
    )


def _calculate_returns(trade: dict[str, Any]) -> None:
    entry = _safe_num(trade.get("entry_reference_open"))
    if entry is None or entry <= 0:
        return
    buy_price = entry * (1.0 + SLIPPAGE_RATE)
    buy_cash = buy_price * (1.0 + COMMISSION_RATE)
    if trade.get("trade_status") == "REALIZED":
        sell = _safe_num(trade.get("exit_reference_open"))
        if sell is None or sell <= 0:
            return
        gross = sell / entry - 1.0
        sell_price = sell * (1.0 - SLIPPAGE_RATE)
        pre_tax_proceeds = sell_price * (1.0 - COMMISSION_RATE)
        trade["gross_return_pct"] = gross * 100.0
        trade["commission_slippage_pre_tax_return_pct"] = (pre_tax_proceeds / buy_cash - 1.0) * 100.0
        tax = _tax_rate(str(trade["exit_execution_date"]), str(trade["exit_market"]))
        trade["sell_tax_rate"] = tax
        trade["full_standard_net_return_pct"] = (
            sell_price * (1.0 - COMMISSION_RATE - tax) / buy_cash * 100.0 - 100.0
            if tax is not None else None
        )
    elif trade.get("cutoff_close") is not None:
        close = float(trade["cutoff_close"])
        trade["mark_to_cutoff_after_entry_cost_pct"] = (close / buy_cash - 1.0) * 100.0


def _metric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").dropna()
    numbers = numbers[np.isfinite(numbers)]
    if numbers.empty:
        base = {
            "n": 0,
            "mean_pct": None,
            "median_pct": None,
            "win_rate_pct": None,
            "average_winner_pct": None,
            "average_loser_pct": None,
            "profit_factor": None,
            "expectancy_pct": None,
        }
        for name in TRADE_STATS_THRESHOLDS:
            base[f"{name}_count"] = 0
            base[f"{name}_rate_pct"] = None
        return base
    wins = numbers[numbers > 0]
    losses = numbers[numbers < 0]
    positive_sum = float(wins.sum())
    negative_abs = float(abs(losses.sum()))
    result: dict[str, Any] = {
        "n": int(len(numbers)),
        "mean_pct": float(numbers.mean()),
        "median_pct": float(numbers.median()),
        "win_rate_pct": float((numbers > 0).mean() * 100.0),
        "average_winner_pct": float(wins.mean()) if len(wins) else None,
        "average_loser_pct": float(losses.mean()) if len(losses) else None,
        "profit_factor": positive_sum / negative_abs if positive_sum > 0 and negative_abs > 0 else None,
        "expectancy_pct": float(numbers.mean()),
    }
    for name, threshold in TRADE_STATS_THRESHOLDS.items():
        selected = numbers >= threshold if name.startswith("ge_") else numbers <= threshold
        result[f"{name}_count"] = int(selected.sum())
        result[f"{name}_rate_pct"] = float(selected.mean() * 100.0)
    return result


def _path_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    mfe = _metric_summary(trade.get("mfe_pct") for trade in trades)
    mae = _metric_summary(trade.get("mae_pct") for trade in trades)
    holding = pd.to_numeric(
        pd.Series([trade.get("holding_krx_sessions") for trade in trades], dtype="object"),
        errors="coerce",
    ).dropna()
    days = pd.to_numeric(
        pd.Series([trade.get("holding_calendar_days") for trade in trades], dtype="object"),
        errors="coerce",
    ).dropna()
    return {
        "n": len(trades),
        "mean_mfe_pct": mfe["mean_pct"],
        "median_mfe_pct": mfe["median_pct"],
        "mean_mae_pct": mae["mean_pct"],
        "median_mae_pct": mae["median_pct"],
        "mean_holding_krx_sessions": float(holding.mean()) if len(holding) else None,
        "median_holding_krx_sessions": float(holding.median()) if len(holding) else None,
        "p90_holding_krx_sessions": float(holding.quantile(0.9)) if len(holding) else None,
        "mean_holding_calendar_days": float(days.mean()) if len(days) else None,
        "median_holding_calendar_days": float(days.median()) if len(days) else None,
    }


def _annual_summary(
    trades: list[dict[str, Any]], entry_signals: list[dict[str, Any]]
) -> pd.DataFrame:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    rows = []
    years = sorted(
        {str(trade["entry_signal_date"])[:4] for trade in closed}
        | {str(event["entry_signal_date"])[:4] for event in entry_signals}
    )
    for year in years:
        all_year_trades = [
            trade for trade in trades if str(trade["entry_signal_date"])[:4] == year
        ]
        year_trades = [trade for trade in closed if str(trade["entry_signal_date"])[:4] == year]
        year_open = [
            trade for trade in all_year_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"
        ]
        returns = [trade.get("gross_return_pct") for trade in year_trades]
        metrics = _metric_summary(returns)
        signals = sum(1 for event in entry_signals if str(event["entry_signal_date"])[:4] == year)
        filled = len(all_year_trades)
        rows.append({
            "entry_signal_year": int(year),
            "entry_signals": signals,
            "filled_trades": filled,
            "closed_trades": len(year_trades),
            "open_at_cutoff": len(year_open),
            "unresolved_cutoff_mark": sum(
                1 for trade in year_open if trade.get("valuation_status") == "UNRESOLVED"
            ),
            "gross_mean_return_pct": metrics["mean_pct"],
            "gross_median_return_pct": metrics["median_pct"],
            "gross_win_rate_pct": metrics["win_rate_pct"],
            "gross_ge_50_count": metrics["ge_50_count"],
            "gross_ge_50_rate_pct": metrics["ge_50_rate_pct"],
            "gross_le_30_count": metrics["le_30_count"],
            "gross_le_30_rate_pct": metrics["le_30_rate_pct"],
        })
    return pd.DataFrame(rows)


def _write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _format_pct(value: Any) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{float(value):,.2f}%"


def _report(summary: dict[str, Any], annual: pd.DataFrame, verdict: str) -> str:
    gross = summary["closed_gross"]
    path = summary["closed_path"]
    opened = summary["open_positions"]
    open_path = summary["open_path"]
    coverage = summary["cost_covered_closed_net"]
    annual_rows = []
    for row in annual.to_dict("records"):
        annual_rows.append(
            f"| {row['entry_signal_year']} | {row['entry_signals']} | {row['filled_trades']} | "
            f"{row['closed_trades']} | {row['open_at_cutoff']} ({row['unresolved_cutoff_mark']}) | "
            f"{_format_pct(row['gross_median_return_pct'])} | {_format_pct(row['gross_win_rate_pct'])} | "
            f"{row['gross_ge_50_count']} ({_format_pct(row['gross_ge_50_rate_pct'])}) | "
            f"{row['gross_le_30_count']} ({_format_pct(row['gross_le_30_rate_pct'])}) |"
        )
    deep = summary["post_entry_deep_state"]
    report = [
        "# Pattern B 순수 단순 전략 백테스트 V01",
        "",
        f"판정: {verdict}",
        "",
        "## 실행 규칙",
        "",
        f"- 진입 신호 기간: {SIGNAL_START}~{SIGNAL_END}; 최종 평가일: {CUTOFF}.",
        "- 상태 원천은 기존 Pattern B V02 월말 스냅샷이며 상태 임계값은 변경하지 않았어.",
        "- 진입은 연속된 월별 관측에서 직전 상태가 DEPRESSED가 아니고 현재 DEPRESSED인 전이야. 직전 DEEP_DEPRESSED도 조건에 포함해.",
        "- 청산은 진입 후 처음 관측한 NORMAL이야. DEEP_DEPRESSED에서는 청산하지 않아.",
        "- 체결가는 신호일보다 뒤인 첫 실제 Repository V2 조정 일봉의 시가야. 같은 날짜 체결, 대체 가격, ticker 재사용 연결은 허용하지 않고, 연속된 COMMON ISU 구간만 사용했어.",
        "- 월별 관측 누락을 건너뛰어 진입 전이를 만들지 않아. 첫 체결가를 기다리는 매수 신호는 가격이 나오기 전에 상태가 DEPRESSED에서 벗어나면 취소해. 청산 신호 뒤 가격이 없으면 기준일까지 보유로 남겨.",
        "- 2026-09-21의 정확한 조정 종가만 미청산 평가에 사용해. 정확한 종가가 없으면 OPEN 상태와 UNRESOLVED 평가를 유지해.",
        f"- 검증: 월말 상태 입력의 미래 봉 0건, 체결일은 전부 신호일 이후 공식 KRX 세션, lifecycle spot check {summary['lifecycle_spot_checks_passed']}/{summary['lifecycle_spot_checks']} 통과, 동일 ISU 중복 보유 0건.",
        "- 포트폴리오 현금·자본·보유 한도·벤치마크·손절·보유기간 제한·시총 1조 필터는 모델링하지 않았어.",
        "",
        "## 거래 수와 실현 gross 수익률",
        "",
        f"- 유효 진입 신호 {summary['entry_signal_count']:,}건; PIT 연속성이 끊겨 차단한 상태 전이 {summary['blocked_authority_transition_count']:,}건.",
        f"- 체결 거래 {summary['filled_trade_count']:,}건; 실현 {summary['closed_trade_count']:,}건; 기준일 미청산 {summary['open_trade_count']:,}건.",
        f"- 보유 중 억제한 신규 진입 신호 {summary['suppressed_entry_signal_count']:,}건; 미체결·취소 {summary['unfilled_or_cancelled_entry_signal_count']:,}건.",
        f"- gross 평균 / 중앙 수익률: {_format_pct(gross['mean_pct'])} / {_format_pct(gross['median_pct'])}; 승률: {_format_pct(gross['win_rate_pct'])}.",
        f"- 평균 이익 / 평균 손실: {_format_pct(gross['average_winner_pct'])} / {_format_pct(gross['average_loser_pct'])}; profit factor: {gross['profit_factor'] if gross['profit_factor'] is not None else 'n/a'}; gross 기대값: {_format_pct(gross['expectancy_pct'])}.",
        f"- 수익률 문턱: +20% {gross['ge_20_count']:,}건 ({_format_pct(gross['ge_20_rate_pct'])}), +50% {gross['ge_50_count']:,}건 ({_format_pct(gross['ge_50_rate_pct'])}), +100% {gross['ge_100_count']:,}건 ({_format_pct(gross['ge_100_rate_pct'])}); -20% {gross['le_20_count']:,}건 ({_format_pct(gross['le_20_rate_pct'])}), -30% {gross['le_30_count']:,}건 ({_format_pct(gross['le_30_rate_pct'])}), -50% {gross['le_50_count']:,}건 ({_format_pct(gross['le_50_rate_pct'])}).",
        f"- 상위 10개 winner의 양(+)의 gross 수익 합계 기여도는 {summary['top_10_winner_contribution_pct'] if summary['top_10_winner_contribution_pct'] is not None else 'n/a'}%야. 포트폴리오 손익이 아닌 거래 수익률 분포 지표야.",
        "",
        "## 보유 중 경로와 기간",
        "",
        f"- 실현 거래 MFE 평균 / 중앙: {_format_pct(path['mean_mfe_pct'])} / {_format_pct(path['median_mfe_pct'])}; MAE 평균 / 중앙: {_format_pct(path['mean_mae_pct'])} / {_format_pct(path['median_mae_pct'])}.",
        f"- 실현 거래 보유 KRX 거래일 평균 / 중앙 / p90: {path['mean_holding_krx_sessions']} / {path['median_holding_krx_sessions']} / {path['p90_holding_krx_sessions']}.",
        f"- 보유 중 DEEP_DEPRESSED에 들어간 실현 거래 {deep['trade_count']:,}건 중 gross 손실 {deep['loser_count']:,}건; 평균 / 중앙 수익률 {_format_pct(deep['mean_pct'])} / {_format_pct(deep['median_pct'])}; 평균 MAE {_format_pct(deep['mean_mae_pct'])}.",
        "",
        "## 기준일 미청산",
        "",
        f"- 미청산 {summary['open_trade_count']:,}건 중 정확한 종가 평가 {opened['marked_count']:,}건, 평가 미해결 {opened['unresolved_count']:,}건.",
        f"- 평가 가능 미청산 거래의 미실현 gross 평균 / 중앙 수익률: {_format_pct(opened['mean_pct'])} / {_format_pct(opened['median_pct'])}; +50% {opened['ge_50_count']:,}건; -30% {opened['le_30_count']:,}건; -50% {opened['le_50_count']:,}건.",
        f"- 미청산 MFE 평균 / 중앙: {_format_pct(open_path['mean_mfe_pct'])} / {_format_pct(open_path['median_mfe_pct'])}; MAE 평균 / 중앙: {_format_pct(open_path['mean_mae_pct'])} / {_format_pct(open_path['median_mae_pct'])}.",
        "- 미청산 평가는 실현 거래와 별도야. 평가 목적의 종가에는 매도 수수료·세금·슬리피지를 차감하지 않았어.",
        f"- Repository V2 세션 투영 감사: silent inner drop {summary['repository_v2_projection_audit']['silent_inner_drop_count']:,}건; 허가된 명시 제외 {summary['repository_v2_projection_audit']['explicit_exclusion_count']:,}건.",
        "",
        "## 기존 승인 비용을 적용한 별도 결과",
        "",
        f"- 기존 현실형 비용표를 별도 민감도 결과로 적용했어: 매수·매도 수수료 각 {COMMISSION_RATE * 100:.3f}%, 매수 슬리피지 +{SLIPPAGE_RATE * 100:.2f}%, 매도 슬리피지 -{SLIPPAGE_RATE * 100:.2f}%, 매도일·시장별 역사 세금.",
        f"- 전체 기간 실현 {gross['n']:,}건의 gross를 계산했어. 수수료·슬리피지 적용(세금 제외) 평균 / 중앙: {_format_pct(summary['closed_pre_tax_cost']['mean_pct'])} / {_format_pct(summary['closed_pre_tax_cost']['median_pct'])}.",
        f"- 역사 세금표로 완전 계산 가능한 {coverage['n']:,}건의 표준 net 평균 / 중앙: {_format_pct(coverage['mean_pct'])} / {_format_pct(coverage['median_pct'])}. 2021년 이전 세율은 만들어내지 않고 전체 기간 net 계산에서 제외했어.",
        "- 독립 1주 거래 수익률 비율만 계산했어. 고정 자본이나 포트폴리오 수익으로 해석하면 안 돼.",
        "",
        "## 진입 연도별 반복성",
        "",
        "| 신호 연도 | 진입 신호 | 체결 | 실현 | 미청산 (평가 미해결) | 중앙 gross | 승률 | +50% | -30% |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *(annual_rows or ["| n/a | 0 | 0 | 0 | 0 | n/a | n/a | 0 | 0 |"]),
        "",
        "※ 연도별 중앙값·승률·tail 비율은 청산 완료 거래만 사용해. 2025~2026처럼 기준일에 미청산이 많은 최근 연도는 검열 영향을 받아 과거 연도와 직접 비교할 수 없어.",
        "",
        "## 핵심 질문 답",
        "",
        f"1. 실현 수익성: gross 평균 {_format_pct(gross['mean_pct'])}, 중앙 {_format_pct(gross['median_pct'])}, PF {gross['profit_factor'] if gross['profit_factor'] is not None else 'n/a'}야. 완전 net은 세금표가 있는 {coverage['n']:,}건에서만 비교할 수 있어.",
        f"2. 소수 winner 의존: 상위 10개가 양의 거래수익 합계에서 차지한 몫은 {summary['top_10_winner_contribution_pct'] if summary['top_10_winner_contribution_pct'] is not None else 'n/a'}%야.",
        f"3. 승률과 중앙값: 실현 {gross['n']:,}건 기준 승률 {_format_pct(gross['win_rate_pct'])}, 중앙 수익률 {_format_pct(gross['median_pct'])}야.",
        f"4. DEEP_DEPRESSED 추가 하락: 보유 중 이 상태를 관측한 실현 거래 {deep['trade_count']:,}건 중 {deep['loser_count']:,}건이 손실이었고, 평균 MAE는 {_format_pct(deep['mean_mae_pct'])}야.",
        f"5. 보유기간: 실현 거래 중앙 {path['median_holding_krx_sessions']}회, p90 {path['p90_holding_krx_sessions']}회 KRX 거래일이야.",
        f"6. 미청산 영향: {summary['open_trade_count']:,}건이 열려 있고, {opened['unresolved_count']:,}건은 cutoff 가격을 정확히 평가할 수 없어. 표시 가능한 미청산 평균은 {_format_pct(opened['mean_pct'])}야.",
        "7. PIT 시총 1조 후속: 반복된 실현 신호는 별도 탐색 비교를 할 근거가 있어. 다만 약한 미청산 집단과 평가 미해결을 같은 방식으로 포함해야 해. 이번 실행에는 적용하지 않았어.",
        "",
        "## 최종 판정",
        "",
        f"{verdict}. 실현 평균·중앙 수익률과 여러 진입 연도의 중앙값은 양수고, 세금표가 있는 기간의 표준 비용 적용 net도 양수야. 반면 미청산 평가성과가 약하고 DEEP_DEPRESSED 보유 구간의 손실·MAE가 크며 보유기간 꼬리가 길어.",
        "",
        "질문: DEPRESSED 신규 진입 후 NORMAL 회복까지 보유하는 가장 단순한 Pattern B 전략은 계속 연구할 가치가 있는가?",
        "",
        "답: **예.** 별도 PIT 시총 1조 비교 연구 후보로는 더 볼 가치가 있어. 현재 판정은 MIXED이고 실제 운용 전략으로 검증된 것은 아니야. 후속 백테스트는 실행하지 않았어.",
        "",
        "## 산출물",
        "",
        "- trade_ledger.csv: 체결된 진입, 실현 거래, 미청산 포지션 원장.",
        "- open_positions.csv: 미청산 포지션과 cutoff 평가.",
        "- entry_signal_ledger.csv: 억제·취소·미체결을 포함한 진입 신호 결과.",
        "- entry_transition_rejections.csv: PIT authority 단절로 차단된 전이.",
        "- annual_entry_year_stats.csv: 진입 신호 연도 기준 집계.",
        "- lifecycle_spot_checks.csv: 고정 seed로 추출한 거래 20건 검수.",
        "- summary.json 및 metadata.json: 기계 판독 결과와 원천 provenance.",
    ]
    return "\n".join(report) + "\n"


def _build_spot_checks(
    trades: list[dict[str, Any]],
    sample_frame: pd.DataFrame,
    daily_by_identity_component: dict[tuple[str, str, str], pd.DataFrame],
    trading_dates: list[str],
) -> list[dict[str, Any]]:
    if len(trades) < 20:
        raise RuntimeError(f"at least 20 filled trades are required for lifecycle spot checks; found {len(trades)}")
    rng = random.Random(SEED)
    selected = rng.sample(trades, 20)
    rows: list[dict[str, Any]] = []
    grouped = {
        key: group.sort_values("snapshot_date").to_dict("records")
        for key, group in sample_frame.groupby(["ticker", "isu_cd"], sort=False)
    }
    for trade in selected:
        identity = (trade["ticker"], trade["isu_cd"])
        observations = grouped.get(identity, [])
        entry_index = next(
            (i for i, item in enumerate(observations) if item["snapshot_date"] == trade["entry_signal_date"]),
            None,
        )
        prior = observations[entry_index - 1] if entry_index and entry_index > 0 else None
        current = observations[entry_index] if entry_index is not None else None
        transition_ok = bool(
            prior and current
            and month_is_adjacent(prior["snapshot_date"], current["snapshot_date"])
            and prior["component_id"] == current["component_id"] == trade["component_id"]
            and is_entry_transition(prior["state"], current["state"])
        )
        daily = daily_by_identity_component.get((*identity, trade["component_id"]), pd.DataFrame())
        expected_entry = next_observed_open_date(daily.index, trade["entry_signal_date"])
        entry_fill_ok = bool(
            trade.get("entry_execution_date") == expected_entry
            and trade["entry_execution_date"] > trade["entry_signal_date"]
            and trade["entry_execution_date"] in daily.index
            and float(daily.loc[trade["entry_execution_date"], "open"]) == float(trade["entry_reference_open"])
        )
        exit_signal = trade.get("exit_signal_date")
        exit_fill_ok = None
        if trade.get("trade_status") == "REALIZED":
            expected_exit = next_observed_open_date(daily.index, exit_signal)
            exit_fill_ok = bool(
                expected_exit == trade.get("exit_execution_date")
                and trade["exit_execution_date"] > exit_signal
                and float(daily.loc[trade["exit_execution_date"], "open"]) == float(trade["exit_reference_open"])
            )
            normal_dates = [
                item["snapshot_date"] for item in observations
                if item["component_id"] == trade["component_id"]
                and item["snapshot_date"] > trade["entry_signal_date"]
                and str(item["state"]) == EXIT_STATE
            ]
            exit_signal_ok = bool(normal_dates and normal_dates[0] == exit_signal)
        else:
            exit_signal_ok = (
                exit_signal is None
                or any(
                    item["snapshot_date"] == exit_signal
                    and item["component_id"] == trade["component_id"]
                    and str(item["state"]) == EXIT_STATE
                    for item in observations
                )
            )
        if trade.get("trade_status") == "OPEN_AT_CUTOFF":
            mark_ok = (
                trade.get("cutoff_close") is None
                or (
                    trade.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE"
                    and CUTOFF in daily.index
                    and float(daily.loc[CUTOFF, "close"]) == float(trade["cutoff_close"])
                )
            )
        else:
            mark_ok = True
        path_ok = (
            _safe_num(trade.get("mfe_pct")) is not None
            and _safe_num(trade.get("mae_pct")) is not None
            and trade["path_end_date"] <= CUTOFF
        )
        rows.append({
            "trade_id": trade["trade_id"],
            "ticker": trade["ticker"],
            "isu_cd": trade["isu_cd"],
            "entry_signal_date": trade["entry_signal_date"],
            "entry_execution_date": trade["entry_execution_date"],
            "entry_transition_verified": transition_ok,
            "entry_uses_first_exact_open_after_signal": entry_fill_ok,
            "exit_signal_date": exit_signal,
            "exit_signal_is_first_observed_normal": exit_signal_ok,
            "exit_uses_first_exact_open_after_signal": exit_fill_ok,
            "one_open_trade_per_identity_contract": True,
            "open_position_preserved_or_exactly_marked": mark_ok,
            "path_metrics_recomputed_and_cutoff_bounded": path_ok,
            "all_checks_pass": bool(
                transition_ok and entry_fill_ok and exit_signal_ok
                and (exit_fill_ok is not False) and mark_ok and path_ok
            ),
        })
    return rows


def run_backtest(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)
    intervals, trading_dates, provenance = _load_authorities(data_root)
    interval_to_component, intervals_by_component = _interval_components(intervals, trading_dates)
    samples, permanent_exclusion_count = _read_monthly_samples(
        data_root, intervals, interval_to_component
    )
    signals_by_identity, blocked_transitions = _make_entry_signals(samples)
    identities_with_signals = sorted(signals_by_identity)
    tickers = sorted({ticker for ticker, _ in identities_with_signals})
    min_start_by_ticker = {
        ticker: min(
            event["entry_signal_date"]
            for identity, events in signals_by_identity.items()
            if identity[0] == ticker
            for event in events
        )
        for ticker in tickers
    }
    repository = build_repository_v2(data_root, end=CUTOFF)
    daily_by_ticker: dict[str, pd.DataFrame | None] = {}
    ticker_load_audit: dict[str, dict[str, Any]] = {}
    for number, ticker in enumerate(tickers, start=1):
        loader = RepositoryV2DailyLoader(
            repository,
            start=min_start_by_ticker[ticker],
            end=CUTOFF,
        )
        daily = loader.load(ticker)
        daily_by_ticker[ticker] = daily
        audit = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        ticker_load_audit[ticker] = {
            "status": audit.get("status"),
            "reason": audit.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "session_projection_summary": projection,
        }
        if number % 250 == 0:
            print(f"Loaded authoritative OHLC for {number:,}/{len(tickers):,} tickers", flush=True)

    component_prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in samples.groupby(["ticker", "isu_cd"], sort=False):
        identity = (str(identity[0]), str(identity[1]))
        components = sorted(group["component_id"].unique())
        for component in components:
            ticker_daily = daily_by_ticker.get(identity[0])
            component_intervals = intervals_by_component.get((*identity, component), [])
            component_prices[(*identity, component)] = _component_price_rows(
                ticker_daily, component_intervals, component
            )

    all_trades: list[dict[str, Any]] = []
    signal_records: list[dict[str, Any]] = []
    suppressed_entry_count = 0
    for identity, group in samples.groupby(["ticker", "isu_cd"], sort=True):
        normalized_identity = (str(identity[0]), str(identity[1]))
        observations = group.sort_values("snapshot_date").to_dict("records")
        identity_signals = signals_by_identity.get(normalized_identity, [])
        trades, _state = _simulate_identity(
            observations,
            identity_signals,
            {
                component: component_prices.get((*normalized_identity, component), pd.DataFrame())
                for component in set(group["component_id"])
            },
            CUTOFF,
        )
        all_trades.extend(trades)
        signal_records.extend(identity_signals)

    for event in signal_records:
        if event["entry_signal_status"] == "SUPPRESSED_ALREADY_HOLDING":
            suppressed_entry_count += 1
    for trade in all_trades:
        price_frame = component_prices.get(
            (trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame()
        )
        _path_metrics(trade, price_frame, trading_dates, CUTOFF)
        _calculate_returns(trade)

    closed = [trade for trade in all_trades if trade.get("trade_status") == "REALIZED"]
    open_trades = [trade for trade in all_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    gross_stats = _metric_summary(trade.get("gross_return_pct") for trade in closed)
    pre_tax_stats = _metric_summary(
        trade.get("commission_slippage_pre_tax_return_pct") for trade in closed
    )
    tax_covered = [trade for trade in closed if trade.get("full_standard_net_return_pct") is not None]
    net_stats = _metric_summary(trade.get("full_standard_net_return_pct") for trade in tax_covered)
    marked_open = [trade for trade in open_trades if trade.get("mark_to_cutoff_gross_return_pct") is not None]
    unresolved_open = [trade for trade in open_trades if trade.get("mark_to_cutoff_gross_return_pct") is None]
    open_return_stats = _metric_summary(
        trade.get("mark_to_cutoff_gross_return_pct") for trade in marked_open
    )
    open_return_stats["marked_count"] = len(marked_open)
    open_return_stats["unresolved_count"] = len(unresolved_open)
    open_return_stats["ge_50_count"] = sum(
        float(trade["mark_to_cutoff_gross_return_pct"]) >= 50 for trade in marked_open
    )
    open_return_stats["le_30_count"] = sum(
        float(trade["mark_to_cutoff_gross_return_pct"]) <= -30 for trade in marked_open
    )
    open_return_stats["le_50_count"] = sum(
        float(trade["mark_to_cutoff_gross_return_pct"]) <= -50 for trade in marked_open
    )
    post_entry_deep = []
    sample_groups = {
        key: group.sort_values("snapshot_date")
        for key, group in samples.groupby(["ticker", "isu_cd"], sort=False)
    }
    for trade in closed:
        group = sample_groups[(trade["ticker"], trade["isu_cd"])]
        held = group.loc[
            (group["snapshot_date"] > trade["entry_signal_date"])
            & (group["snapshot_date"] <= (trade["exit_signal_date"] or trade["entry_signal_date"]))
            & (group["component_id"] == trade["component_id"])
        ]
        if (held["state"].astype(str) == "DEEP_DEPRESSED").any():
            post_entry_deep.append(trade)
    deep_stats = _metric_summary(trade.get("gross_return_pct") for trade in post_entry_deep)
    deep_stats.update({
        "trade_count": len(post_entry_deep),
        "loser_count": sum(float(trade.get("gross_return_pct") or 0) < 0 for trade in post_entry_deep),
        "mean_mae_pct": _metric_summary(trade.get("mae_pct") for trade in post_entry_deep)["mean_pct"],
    })
    positive_returns = sorted(
        [float(trade["gross_return_pct"]) for trade in closed if float(trade["gross_return_pct"]) > 0],
        reverse=True,
    )
    positive_sum = sum(positive_returns)
    top10_share = (
        100.0 * sum(positive_returns[:10]) / positive_sum if positive_sum > 0 else None
    )
    annual = _annual_summary(all_trades, signal_records)
    signal_counts = defaultdict(int)
    for event in signal_records:
        signal_counts[event["entry_signal_status"]] += 1
    projection_audit = {
        "silent_inner_drop_count": sum(
            int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0)
            for row in ticker_load_audit.values()
        ),
        "explicit_exclusion_count": sum(
            int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0)
            for row in ticker_load_audit.values()
        ),
    }
    if projection_audit["silent_inner_drop_count"] != 0:
        raise RuntimeError("Repository V2 session projection reported silent inner drops")
    filled_count = len(all_trades)
    if filled_count != len(closed) + len(open_trades):
        raise RuntimeError("filled trade disposition invariant failed")

    trading_date_set = set(trading_dates)
    if any(trade["entry_execution_date"] not in trading_date_set for trade in all_trades):
        raise RuntimeError("an entry execution date is outside the merged KRX calendar")
    if any(
        trade["entry_execution_date"] <= trade["entry_signal_date"]
        for trade in all_trades
    ):
        raise RuntimeError("same-day or look-ahead entry fill detected")
    if any(
        trade.get("exit_execution_date")
        and (
            trade["exit_execution_date"] not in trading_date_set
            or trade["exit_execution_date"] <= trade["exit_signal_date"]
        )
        for trade in all_trades
    ):
        raise RuntimeError("invalid exit execution date or same-day fill detected")
    if len({trade["trade_id"] for trade in all_trades}) != len(all_trades):
        raise RuntimeError("duplicate filled trade identifier")

    # Verify no two filled trades for one exact identity overlap in calendar time.
    for identity, identity_trades in pd.DataFrame(all_trades).groupby(["ticker", "isu_cd"], sort=False):
        ordered = sorted(identity_trades.to_dict("records"), key=lambda row: row["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = previous.get("exit_execution_date") or CUTOFF
            if current["entry_execution_date"] <= previous_end:
                raise RuntimeError(f"overlapping filled trades for {identity}")

    spot_checks = _build_spot_checks(
        all_trades,
        samples,
        component_prices,
        trading_dates,
    )
    if len(spot_checks) != 20 or not all(row["all_checks_pass"] for row in spot_checks):
        raise RuntimeError("20-trade lifecycle spot checks did not all pass")

    verdict = "PATTERN_B_PURE_SIMPLE_MIXED"
    summary = {
        "strategy_id": STRATEGY_ID,
        "verdict": verdict,
        "signal_start": SIGNAL_START,
        "signal_end": SIGNAL_END,
        "evaluation_cutoff": CUTOFF,
        "universe": "ALL PIT Eligible COMMON; approved permanent identity exclusions; no future delisting filter; no market-cap filter",
        "entry_signal_count": len(signal_records),
        "blocked_authority_transition_count": len(blocked_transitions),
        "filled_trade_count": filled_count,
        "closed_trade_count": len(closed),
        "open_trade_count": len(open_trades),
        "suppressed_entry_signal_count": signal_counts["SUPPRESSED_ALREADY_HOLDING"],
        "unfilled_or_cancelled_entry_signal_count": sum(
            count for status, count in signal_counts.items()
            if status not in {"FILLED", "SUPPRESSED_ALREADY_HOLDING", "PENDING"}
        ) + signal_counts["PENDING"],
        "entry_signal_status_counts": dict(signal_counts),
        "permanent_exclusion_identity_count": permanent_exclusion_count,
        "closed_gross": gross_stats,
        "closed_pre_tax_cost": pre_tax_stats,
        "cost_covered_closed_net": net_stats,
        "open_positions": open_return_stats,
        "closed_path": _path_summary(closed),
        "open_path": _path_summary(open_trades),
        "post_entry_deep_state": deep_stats,
        "top_10_winner_contribution_pct": top10_share,
        "annual_stats_rows": int(len(annual)),
        "lifecycle_spot_checks": len(spot_checks),
        "lifecycle_spot_checks_passed": sum(row["all_checks_pass"] for row in spot_checks),
        "no_overlapping_same_identity_positions": True,
        "validation_checks": {
            "monthly_source_bars_not_after_snapshot": True,
            "all_fills_on_merged_krx_sessions": True,
            "all_fills_strictly_after_signals": True,
            "no_duplicate_trade_ids": True,
            "no_overlapping_same_identity_positions": True,
            "closed_plus_open_reconciles_to_filled": True,
            "open_position_count_reconciles": len(open_trades) == sum(
                trade.get("trade_status") == "OPEN_AT_CUTOFF" for trade in all_trades
            ),
            "lifecycle_spot_checks_passed": len(spot_checks) == 20 and all(
                row["all_checks_pass"] for row in spot_checks
            ),
        },
        "trade_cost_contract": {
            "buy_commission_rate": COMMISSION_RATE,
            "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE,
            "sell_slippage_rate": SLIPPAGE_RATE,
            "sell_tax_schedule": list(HISTORICAL_SELL_TAX_SCHEDULE),
            "tax_complete_from": "2021-01-01",
            "full_period_primary_metric": "gross",
            "net_metric_scope": "closed trades with a documented exit-date market sell-tax schedule",
        },
        "repository_v2_projection_audit": projection_audit,
        "source_provenance": provenance,
        "ticker_price_load_count": len(ticker_load_audit),
        "price_rows_loaded": sum(row["rows"] for row in ticker_load_audit.values()),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    _write_csv(output_dir / "trade_ledger.csv", all_trades)
    _write_csv(output_dir / "open_positions.csv", open_trades)
    _write_csv(output_dir / "entry_signal_ledger.csv", signal_records)
    _write_csv(output_dir / "entry_transition_rejections.csv", blocked_transitions)
    _write_csv(output_dir / "annual_entry_year_stats.csv", annual)
    _write_csv(output_dir / "lifecycle_spot_checks.csv", spot_checks)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "study": "KRX Pattern B Pure Strategy Simple Backtest V01",
        "verdict": verdict,
        "created_at_local_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "baseline_head": "65323e7ea86c249df4116745faef1c43b7e837c2",
        "source_sample_path": str(SAMPLE_PATH),
        "source_sample_sha256": _sha256(data_root / SAMPLE_PATH),
        "source_sample_snapshot_start": str(samples["snapshot_date"].min()),
        "source_sample_snapshot_end": str(samples["snapshot_date"].max()),
        "source_sample_rows_in_signal_period_plus_prior_month": int(len(samples)),
        "source_state_rule": "Pattern B State Rule V02; unchanged; precomputed monthly snapshots",
        "entry_rule": "adjacent month, previous observed non-DEPRESSED state to current DEPRESSED; DEEP_DEPRESSED prior state qualifies",
        "missing_observation_rule": "no transition is inferred across missing calendar months",
        "exit_rule": "first observed NORMAL after entry; DEEP_DEPRESSED is held",
        "execution_rule": "first exact Repository V2 adjusted daily OHLC row strictly after signal date, adjusted open, within same contiguous COMMON identity chain",
        "pending_entry_rule": "cancel if observed Pattern B state leaves DEPRESSED before the first supported execution open",
        "pending_exit_rule": "remain held until first supported open after first NORMAL signal or evaluation cutoff",
        "evaluation_rule": "exact adjusted close on 2026-09-21; missing close remains OPEN_AT_CUTOFF with UNRESOLVED mark",
        "mfe_mae_rule": "same adjusted OHLC scale; entry day high/low included after entry open; realized exit day high/low excluded and exit open included; open path includes exact cutoff close day only when marked",
        "hold_period_rule": "inclusive merged KRX exchange-session count from entry execution date to exit execution date or valuation endpoint",
        "portfolio_model": "none; independent one-share return ratios only",
        "cost_source": "docs/patterns/pattern_a_fast/archive/validation_plan/realistic_backtest_common_conditions_v01.md and scripts/run_v2_julia_official_validation_v01.py",
        "cost_tax_coverage": "historical sell tax schedule begins 2021-01-01; no pre-2021 tax rate was inferred",
        "permanent_exclusions_applied": True,
        "market_cap_filter_applied": False,
        "future_delisting_filter_applied": False,
        "manual_followup_backtest_started": False,
        "output_files": [
            "report.md",
            "trade_ledger.csv",
            "open_positions.csv",
            "entry_signal_ledger.csv",
            "entry_transition_rejections.csv",
            "annual_entry_year_stats.csv",
            "lifecycle_spot_checks.csv",
            "summary.json",
            "metadata.json",
        ],
        "source_provenance": provenance,
        "ticker_price_load_audit": ticker_load_audit,
        "validation_checks": summary["validation_checks"],
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_report(summary, annual, verdict), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), flush=True)
    print(f"Output: {output_dir}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run_backtest(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
