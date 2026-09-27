#!/usr/bin/env python3
"""Compare Pattern B simple strategy with first-DEEP_DEPRESSED exit."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as pit_study  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)

STRATEGY_ID = "PATTERN_B_DEEP_EXIT_SIMPLE_V01"
START_HEAD = "2d3b43666d9163beba064deef2cd91f6368def8c"
CONTROL_COMMIT = "5dcfe79f40800ed8ac17558bad6dc600a91fd653"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/deep_exit_simple_v01")
EXIT_STATES = {"NORMAL", "DEEP_DEPRESSED"}
SEED = 20260927


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _close_exit_state(state: Any) -> str | None:
    value = str(state)
    return value if value in EXIT_STATES else None


def _simulate_identity_deep_exit(
    observations: list[dict[str, Any]],
    identity_signals: list[dict[str, Any]],
    daily_by_component: dict[str, pd.DataFrame],
    cutoff: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """V01 state machine, with first NORMAL or DEEP state as an exit signal."""
    signals_by_date = {event["entry_signal_date"]: event for event in identity_signals}
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    sequence = 0
    last_states_by_component: dict[str, dict[str, Any]] = {}
    for observation in observations:
        day = str(observation["snapshot_date"])
        component = str(observation["component_id"])
        last_states_by_component[component] = observation
        daily = daily_by_component.get(component, pd.DataFrame())

        if pending and pending.get("fill_date") is not None and pending["fill_date"] <= day:
            pending_daily = daily_by_component.get(pending["trade"]["component_id"], pd.DataFrame())
            position, pending = base._apply_pending_fill(pending, position, trades, pending_daily)

        if pending and pending["kind"] == "ENTRY" and pending.get("fill_date") is not None:
            if pending["fill_date"] > day and str(observation["state"]) != base.ENTRY_STATE:
                pending["event"]["entry_signal_status"] = "CANCELLED_STATE_REVERTED"
                pending["event"]["status_reason"] = (
                    "state left DEPRESSED before the first available execution open"
                )
                pending = None

        event = signals_by_date.get(day)
        if position is not None:
            if event is not None:
                event["entry_signal_status"] = "SUPPRESSED_ALREADY_HOLDING"
                event["status_reason"] = "one position per identity; prior position had not exited by this signal"
            trigger_state = _close_exit_state(observation["state"])
            if (
                pending is None
                and component == position["component_id"]
                and trigger_state is not None
                and day > position["entry_signal_date"]
                and position.get("exit_signal_date") is None
            ):
                fill_date, fill_row = base._next_bar_after(daily, day)
                position["exit_signal_date"] = day
                position["exit_signal_state"] = trigger_state
                position["exit_reason"] = (
                    "DEEP_DEPRESSED_STOP" if trigger_state == "DEEP_DEPRESSED" else "NORMAL_RECOVERY"
                )
                position["exit_fill_status"] = "PENDING" if fill_date else "UNFILLED_NO_LATER_PRICE_ROW"
                pending = {
                    "kind": "EXIT",
                    "signal_date": day,
                    "fill_date": fill_date,
                    "trade": position,
                    "row": fill_row,
                }
        elif pending is None and event is not None:
            sequence += 1
            fill_date, fill_row = base._next_bar_after(daily, day)
            trade = {
                "strategy_id": STRATEGY_ID,
                "trade_id": base._trade_identifier(event, sequence),
                "signal_id": event["signal_id"],
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
                "exit_signal_state": None,
                "exit_reason": None,
                "exit_execution_date": None,
                "exit_reference_open": None,
                "exit_market": None,
                "exit_fill_status": None,
                "trade_status": "ENTRY_PENDING",
                "cutoff_date": cutoff,
            }
            event["trade_id"] = trade["trade_id"]
            event["entry_execution_date"] = fill_date
            event["entry_reference_open"] = float(fill_row["open"]) if fill_row is not None else None
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

    if pending and pending.get("fill_date") is not None and pending["fill_date"] <= cutoff:
        pending_daily = daily_by_component.get(pending["trade"]["component_id"], pd.DataFrame())
        position, pending = base._apply_pending_fill(pending, position, trades, pending_daily)
    if pending and pending["kind"] == "ENTRY":
        event = pending["event"]
        if event["entry_signal_status"] == "PENDING":
            event["entry_signal_status"] = "ENTRY_UNFILLED_AFTER_CUTOFF"
            event["status_reason"] = "no exact authorized adjusted open on or before evaluation cutoff"
        pending = None
    if position is not None:
        position["trade_status"] = "OPEN_AT_CUTOFF"
        if position.get("exit_signal_date") and position.get("exit_execution_date") is None:
            position["exit_fill_status"] = "UNFILLED_BY_CUTOFF"
        last_state = last_states_by_component.get(position["component_id"])
        position["latest_state_date"] = last_state["snapshot_date"] if last_state else None
        position["current_pattern_b_state"] = str(last_state["state"]) if last_state else None
        position["cutoff_close"] = None
        position["valuation_status"] = "UNRESOLVED"
        position["valuation_reason"] = "no exact 2026-09-21 adjusted close within the entry identity chain"
        daily = daily_by_component.get(position["component_id"], pd.DataFrame())
        if cutoff in daily.index:
            close = base._safe_num(daily.loc[cutoff, "close"])
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


def _trade_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked = [
        trade for trade in opened
        if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None
    ]
    unresolved = [
        trade for trade in opened
        if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is None
    ]
    gross = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
    pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in closed)
    covered = [trade for trade in closed if trade.get("full_standard_net_return_pct") is not None]
    net = base._metric_summary(trade.get("full_standard_net_return_pct") for trade in covered)
    open_stats = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked)
    open_stats.update({
        "marked_count": len(marked),
        "unresolved_count": len(unresolved),
        "le_30_count": sum(float(trade["mark_to_cutoff_gross_return_pct"]) <= -30 for trade in marked),
        "le_30_rate_pct": 100 * sum(float(trade["mark_to_cutoff_gross_return_pct"]) <= -30 for trade in marked) / len(marked) if marked else None,
        "le_50_count": sum(float(trade["mark_to_cutoff_gross_return_pct"]) <= -50 for trade in marked),
        "le_50_rate_pct": 100 * sum(float(trade["mark_to_cutoff_gross_return_pct"]) <= -50 for trade in marked) / len(marked) if marked else None,
    })
    return {
        "filled_count": len(trades),
        "closed_count": len(closed),
        "open_count": len(opened),
        "open_ratio_pct": 100 * len(opened) / len(trades) if trades else None,
        "closed_gross": gross,
        "closed_pre_tax_cost": pre_tax,
        "cost_covered_closed_net": net,
        "open_positions": open_stats,
        "all_path": base._path_summary(trades),
        "closed_path": base._path_summary(closed),
        "open_path": base._path_summary(opened),
    }


def _state_groups(samples: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    return {
        (str(key[0]), str(key[1])): group.sort_values("snapshot_date").reset_index(drop=True)
        for key, group in samples.groupby(["ticker", "isu_cd"], sort=False)
    }


def _first_exit_observation(group: pd.DataFrame, trade: Mapping[str, Any]) -> tuple[str | None, str | None]:
    held = group.loc[
        (group["snapshot_date"] > str(trade["entry_signal_date"]))
        & (group["snapshot_date"] <= base.SIGNAL_END)
        & (group["component_id"] == trade["component_id"])
        & (group["state"].astype(str).isin(EXIT_STATES))
    ]
    if held.empty:
        return None, None
    row = held.iloc[0]
    return str(row["snapshot_date"]), str(row["state"])


def _validate_exit_signals(trades: list[dict[str, Any]], samples: pd.DataFrame) -> dict[str, Any]:
    groups = _state_groups(samples)
    exit_observations = samples.loc[samples["state"].astype(str).isin(EXIT_STATES)]
    collision_count = int(
        exit_observations.groupby(["ticker", "isu_cd", "snapshot_date"])["state"]
        .nunique().gt(1).sum()
    )
    if collision_count:
        raise RuntimeError(f"NORMAL/DEEP same-observation collisions: {collision_count}")
    mismatches = []
    for trade in trades:
        group = groups[(trade["ticker"], trade["isu_cd"])]
        expected_date, expected_state = _first_exit_observation(group, trade)
        actual_date = trade.get("exit_signal_date")
        actual_state = trade.get("exit_signal_state")
        if actual_date != expected_date or actual_state != expected_state:
            mismatches.append({
                "trade_id": trade["trade_id"],
                "expected_date": expected_date,
                "expected_state": expected_state,
                "actual_date": actual_date,
                "actual_state": actual_state,
            })
    if mismatches:
        raise RuntimeError(f"first NORMAL/DEEP exit signal mismatch: {mismatches[:3]}")
    return {
        "first_exit_signal_mismatches": 0,
        "normal_deep_same_observation_collision_count": collision_count,
    }


def _pre_exit_mae_pct(trade: Mapping[str, Any], daily: pd.DataFrame) -> float | None:
    """Measure drawdown through the exit signal close, excluding post-exit-session lows."""
    entry = base._safe_num(trade.get("entry_reference_open"))
    entry_date = trade.get("entry_execution_date")
    signal_date = trade.get("exit_signal_date")
    if entry is None or entry <= 0 or not entry_date or not signal_date:
        return None
    path = daily.loc[(daily.index >= str(entry_date)) & (daily.index <= str(signal_date))]
    lows = pd.to_numeric(path.get("low", pd.Series(dtype="float64")), errors="coerce").dropna()
    if lows.empty:
        return None
    return (min(entry, float(lows.min())) / entry - 1.0) * 100.0


def _deep_exit_spot_checks(
    trades: list[dict[str, Any]],
    samples: pd.DataFrame,
    price_by_identity_component: dict[tuple[str, str, str], pd.DataFrame],
    trading_dates: list[str],
) -> list[dict[str, Any]]:
    executed_deep = [
        trade for trade in trades
        if trade.get("exit_signal_state") == "DEEP_DEPRESSED"
        and trade.get("exit_execution_date") is not None
    ]
    if len(executed_deep) < 20:
        raise RuntimeError(f"20 executed DEEP exit trades required for lifecycle review; found {len(executed_deep)}")
    selected = random.Random(SEED).sample(executed_deep, 20)
    groups = _state_groups(samples)
    checks = []
    for trade in selected:
        group = groups[(trade["ticker"], trade["isu_cd"])]
        pos = group.index[group["snapshot_date"] == trade["entry_signal_date"]]
        entry_i = int(pos[0]) if len(pos) else -1
        prior = group.iloc[entry_i - 1] if entry_i > 0 else None
        current = group.iloc[entry_i] if entry_i >= 0 else None
        entry_transition_ok = bool(
            prior is not None and current is not None
            and base.month_is_adjacent(str(prior["snapshot_date"]), str(current["snapshot_date"]))
            and prior["component_id"] == current["component_id"] == trade["component_id"]
            and base.is_entry_transition(prior["state"], current["state"])
        )
        daily = price_by_identity_component.get(
            (trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame()
        )
        expected_entry = base.next_observed_open_date(daily.index, trade["entry_signal_date"])
        expected_exit_signal, expected_exit_state = _first_exit_observation(group, trade)
        expected_exit = base.next_observed_open_date(daily.index, trade["exit_signal_date"])
        entry_fill_ok = bool(
            trade["entry_execution_date"] == expected_entry
            and expected_entry is not None
            and expected_entry > trade["entry_signal_date"]
            and float(daily.loc[expected_entry, "open"]) == float(trade["entry_reference_open"])
        )
        deep_first_ok = bool(
            expected_exit_signal == trade["exit_signal_date"]
            and expected_exit_state == "DEEP_DEPRESSED"
            and trade["exit_reason"] == "DEEP_DEPRESSED_STOP"
        )
        exit_fill_ok = bool(
            trade["exit_execution_date"] == expected_exit
            and expected_exit is not None
            and expected_exit > trade["exit_signal_date"]
            and float(daily.loc[expected_exit, "open"]) == float(trade["exit_reference_open"])
        )
        cost_copy = dict(trade)
        base._calculate_returns(cost_copy)
        return_ok = all(
            math.isclose(float(cost_copy.get(column)), float(trade.get(column)), rel_tol=1e-12, abs_tol=1e-12)
            for column in ("gross_return_pct", "commission_slippage_pre_tax_return_pct")
        )
        path_ok = (
            base._safe_num(trade.get("mfe_pct")) is not None
            and base._safe_num(trade.get("mae_pct")) is not None
            and str(trade["path_end_date"]) <= base.CUTOFF
        )
        pre_exit_mae = _pre_exit_mae_pct(trade, daily)
        pre_exit_mae_ok = (
            pre_exit_mae is not None
            and math.isclose(
                pre_exit_mae,
                float(trade.get("pre_exit_mae_pct")),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        )
        checks.append({
            "trade_id": trade["trade_id"],
            "ticker": trade["ticker"],
            "isu_cd": trade["isu_cd"],
            "entry_signal_date": trade["entry_signal_date"],
            "entry_execution_date": trade["entry_execution_date"],
            "entry_transition_verified": entry_transition_ok,
            "entry_uses_first_exact_open_after_signal": entry_fill_ok,
            "exit_signal_date": trade["exit_signal_date"],
            "first_normal_or_deep_trigger_is_deep": deep_first_ok,
            "deep_exit_uses_first_exact_open_after_signal": exit_fill_ok,
            "fees_and_slippage_recalculated": return_ok,
            "pre_exit_mae_stops_at_signal_close": pre_exit_mae_ok,
            "path_ends_by_cutoff": path_ok,
            "all_checks_pass": bool(entry_transition_ok and entry_fill_ok and deep_first_ok and exit_fill_ok and return_ok and pre_exit_mae_ok and path_ok),
        })
    if not all(row["all_checks_pass"] for row in checks):
        raise RuntimeError("DEEP exit lifecycle spot check failed")
    return checks


def _paired_deep_exit_comparison(
    test_trades: list[dict[str, Any]],
    control_trades: list[dict[str, Any]],
    control_status_by_key: dict[tuple[str, str, str], str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    control_by_key = {_key(trade): trade for trade in control_trades}
    if len(control_by_key) != len(control_trades):
        raise RuntimeError("CONTROL has duplicate trade entries for one signal key")
    executed_deep = [
        trade for trade in test_trades
        if trade.get("exit_signal_state") == "DEEP_DEPRESSED"
        and trade.get("exit_execution_date") is not None
    ]
    rows = []
    for test in executed_deep:
        key = _key(test)
        control = control_by_key.get(key)
        status = control_status_by_key.get(key, "MISSING_CONTROL_SIGNAL")
        control_return = None
        outcome_basis = "NO_CONTROL_FILLED_TRADE"
        if control is not None and control.get("trade_status") == "REALIZED":
            control_return = base._safe_num(control.get("gross_return_pct"))
            outcome_basis = "CONTROL_REALIZED_GROSS"
        elif control is not None and control.get("trade_status") == "OPEN_AT_CUTOFF":
            control_return = base._safe_num(control.get("mark_to_cutoff_gross_return_pct"))
            outcome_basis = "CONTROL_CUTOFF_MARK" if control_return is not None else "CONTROL_OPEN_UNRESOLVED"
        test_return = base._safe_num(test.get("gross_return_pct"))
        comparable = control_return is not None and test_return is not None
        rows.append({
            "entry_signal_id": test.get("signal_id"),
            "ticker": test["ticker"],
            "isu_cd": test["isu_cd"],
            "entry_signal_date": test["entry_signal_date"],
            "test_trade_id": test["trade_id"],
            "test_deep_exit_signal_date": test["exit_signal_date"],
            "test_deep_exit_execution_date": test["exit_execution_date"],
            "test_deep_exit_gross_return_pct": test_return,
            "test_deep_exit_pre_tax_return_pct": test.get("commission_slippage_pre_tax_return_pct"),
            "test_pre_exit_mae_pct": test.get("pre_exit_mae_pct"),
            "control_signal_status": status,
            "control_trade_id": control.get("trade_id") if control else None,
            "control_trade_status": control.get("trade_status") if control else None,
            "control_outcome_basis": outcome_basis,
            "control_final_or_marked_return_pct": control_return,
            "test_minus_control_return_pct": test_return - control_return if comparable else None,
            "is_primary_closed_to_closed_pair": bool(
                control is not None and control.get("trade_status") == "REALIZED" and test.get("trade_status") == "REALIZED"
            ),
        })
    pairs = pd.DataFrame(rows)
    primary = pairs.loc[pairs["is_primary_closed_to_closed_pair"]].copy() if not pairs.empty else pd.DataFrame()
    rescues = []
    damages = []
    if not primary.empty:
        for row in primary.to_dict("records"):
            control_return = float(row["control_final_or_marked_return_pct"])
            test_return = float(row["test_deep_exit_gross_return_pct"])
            if (control_return <= -30 and test_return > -30) or (control_return <= -50 and test_return > -50):
                rescues.append({
                    **row,
                    "rescued_from_le_30": bool(control_return <= -30 and test_return > -30),
                    "rescued_from_le_50": bool(control_return <= -50 and test_return > -50),
                })
            if control_return > 0 and test_return < control_return:
                damages.append({
                    **row,
                    "control_winner_cut_below_20": bool(control_return >= 20 and test_return < 20),
                    "control_winner_cut_below_50": bool(control_return >= 50 and test_return < 50),
                    "control_winner_cut_below_100": bool(control_return >= 100 and test_return < 100),
                    "control_winner_turned_loss": bool(test_return <= 0),
                })
    rescue_frame = pd.DataFrame(rescues)
    damage_frame = pd.DataFrame(damages)
    primary_rows = primary.to_dict("records") if not primary.empty else []
    deltas = [float(row["test_minus_control_return_pct"]) for row in primary_rows]
    control_le_30 = [row for row in primary_rows if float(row["control_final_or_marked_return_pct"]) <= -30]
    control_le_50 = [row for row in primary_rows if float(row["control_final_or_marked_return_pct"]) <= -50]
    control_winners = [row for row in primary_rows if float(row["control_final_or_marked_return_pct"]) > 0]
    stats = {
        "test_executed_deep_exit_count": len(executed_deep),
        "matched_control_trade_count": int(pairs["control_trade_id"].notna().sum()) if not pairs.empty else 0,
        "control_realized_matched_count": int((pairs["control_outcome_basis"] == "CONTROL_REALIZED_GROSS").sum()) if not pairs.empty else 0,
        "control_marked_open_matched_count": int((pairs["control_outcome_basis"] == "CONTROL_CUTOFF_MARK").sum()) if not pairs.empty else 0,
        "control_unresolved_open_matched_count": int((pairs["control_outcome_basis"] == "CONTROL_OPEN_UNRESOLVED").sum()) if not pairs.empty else 0,
        "no_control_filled_trade_count": int((pairs["control_outcome_basis"] == "NO_CONTROL_FILLED_TRADE").sum()) if not pairs.empty else 0,
        "primary_closed_to_closed_pair_count": len(primary_rows),
        "primary_pair_improved_count": sum(value > 1e-12 for value in deltas),
        "primary_pair_worsened_count": sum(value < -1e-12 for value in deltas),
        "primary_pair_unchanged_count": sum(abs(value) <= 1e-12 for value in deltas),
        "control_le_30_primary_pair_count": len(control_le_30),
        "control_le_30_rescued_count": sum(float(row["test_deep_exit_gross_return_pct"]) > -30 for row in control_le_30),
        "control_le_50_primary_pair_count": len(control_le_50),
        "control_le_50_rescued_count": sum(float(row["test_deep_exit_gross_return_pct"]) > -50 for row in control_le_50),
        "control_winner_primary_pair_count": len(control_winners),
        "control_winner_lower_return_count": len(damages),
        "control_winner_to_loss_count": sum(bool(row["control_winner_turned_loss"]) for row in damages),
        "control_ge_20_winner_damaged_below_20_count": sum(bool(row["control_winner_cut_below_20"]) for row in damages),
        "control_ge_50_winner_damaged_below_50_count": sum(bool(row["control_winner_cut_below_50"]) for row in damages),
        "control_ge_100_winner_damaged_below_100_count": sum(bool(row["control_winner_cut_below_100"]) for row in damages),
    }
    return pairs, rescue_frame, damage_frame, stats


def _annual_comparison(
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> pd.DataFrame:
    years = sorted(
        {str(row["entry_signal_date"])[:4] for row in control_trades}
        | {str(row["entry_signal_date"])[:4] for row in test_trades}
        | {str(row["entry_signal_date"])[:4] for row in signals}
    )
    rows = []
    for year in years:
        control = [row for row in control_trades if str(row["entry_signal_date"])[:4] == year]
        test = [row for row in test_trades if str(row["entry_signal_date"])[:4] == year]
        signal_count = sum(str(row["entry_signal_date"])[:4] == year for row in signals)
        c_closed = [row for row in control if row.get("trade_status") == "REALIZED"]
        t_closed = [row for row in test if row.get("trade_status") == "REALIZED"]
        c_stats = base._metric_summary(row.get("gross_return_pct") for row in c_closed)
        t_stats = base._metric_summary(row.get("gross_return_pct") for row in t_closed)
        c_open = [row for row in control if row.get("trade_status") == "OPEN_AT_CUTOFF"]
        t_open = [row for row in test if row.get("trade_status") == "OPEN_AT_CUTOFF"]
        t_deep_exits = sum(
            row.get("exit_signal_state") == "DEEP_DEPRESSED"
            and row.get("exit_execution_date") is not None
            for row in test
        )
        rows.append({
            "entry_signal_year": int(year),
            "raw_transition_signals": signal_count,
            "control_filled": len(control),
            "test_filled": len(test),
            "control_realized": len(c_closed),
            "test_realized": len(t_closed),
            "control_open": len(c_open),
            "test_open": len(t_open),
            "test_deep_exit_executed": int(t_deep_exits),
            "control_closed_mean_gross_pct": c_stats["mean_pct"],
            "test_closed_mean_gross_pct": t_stats["mean_pct"],
            "control_closed_median_gross_pct": c_stats["median_pct"],
            "test_closed_median_gross_pct": t_stats["median_pct"],
            "control_closed_win_rate_pct": c_stats["win_rate_pct"],
            "test_closed_win_rate_pct": t_stats["win_rate_pct"],
        })
    return pd.DataFrame(rows)


def _metrics_for_table(summary: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    metrics = _trade_summary(trades)
    gross = metrics["closed_gross"]
    opened_stats = metrics["open_positions"]
    closed_path = metrics["closed_path"]
    all_path = metrics["all_path"]
    return {
        "filled_count": len(trades),
        "realized_count": len(closed),
        "open_count": len(opened),
        "open_ratio_pct": metrics["open_ratio_pct"],
        "mean_gross_pct": gross["mean_pct"],
        "median_gross_pct": gross["median_pct"],
        "win_rate_pct": gross["win_rate_pct"],
        "average_winner_pct": gross["average_winner_pct"],
        "average_loser_pct": gross["average_loser_pct"],
        "profit_factor": gross["profit_factor"],
        "expectancy_pct": gross["expectancy_pct"],
        **{key: gross.get(key) for key in (
            "ge_20_count", "ge_20_rate_pct", "ge_50_count", "ge_50_rate_pct", "ge_100_count", "ge_100_rate_pct",
            "le_20_count", "le_20_rate_pct", "le_30_count", "le_30_rate_pct", "le_50_count", "le_50_rate_pct",
        )},
        "closed_mean_mfe_pct": closed_path["mean_mfe_pct"],
        "closed_median_mfe_pct": closed_path["median_mfe_pct"],
        "closed_mean_mae_pct": closed_path["mean_mae_pct"],
        "closed_median_mae_pct": closed_path["median_mae_pct"],
        "closed_mean_holding_sessions": closed_path["mean_holding_krx_sessions"],
        "closed_median_holding_sessions": closed_path["median_holding_krx_sessions"],
        "closed_p90_holding_sessions": closed_path["p90_holding_krx_sessions"],
        "all_mean_holding_sessions": all_path["mean_holding_krx_sessions"],
        "all_median_holding_sessions": all_path["median_holding_krx_sessions"],
        "all_p90_holding_sessions": all_path["p90_holding_krx_sessions"],
        "open_marked_count": opened_stats["marked_count"],
        "open_unresolved_count": opened_stats["unresolved_count"],
        "open_mark_coverage_pct": 100.0 * opened_stats["marked_count"] / len(opened) if opened else None,
        "open_mean_gross_pct": opened_stats["mean_pct"],
        "open_median_gross_pct": opened_stats["median_pct"],
        "open_le_30_count": opened_stats["le_30_count"],
        "open_le_30_rate_pct": opened_stats["le_30_rate_pct"],
        "open_le_50_count": opened_stats["le_50_count"],
        "open_le_50_rate_pct": opened_stats["le_50_rate_pct"],
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _fmt(value: Any, suffix: str = "%") -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.2f}{suffix}"


def _comparison_table(control: dict[str, Any], test: dict[str, Any]) -> pd.DataFrame:
    labels = {
        "filled_count": "체결 거래 수",
        "realized_count": "실현 거래 수",
        "open_count": "미청산 수",
        "open_ratio_pct": "미청산 비율",
        "mean_gross_pct": "평균 gross",
        "median_gross_pct": "중앙 gross",
        "win_rate_pct": "승률",
        "average_winner_pct": "평균 이익",
        "average_loser_pct": "평균 손실",
        "profit_factor": "수익계수",
        "expectancy_pct": "기대값",
        "ge_20_rate_pct": "+20% 비율",
        "ge_50_rate_pct": "+50% 비율",
        "ge_100_rate_pct": "+100% 비율",
        "le_20_rate_pct": "-20% 비율",
        "le_30_rate_pct": "-30% 비율",
        "le_50_rate_pct": "-50% 비율",
        "closed_mean_mfe_pct": "실현 평균 MFE",
        "closed_median_mfe_pct": "실현 중앙 MFE",
        "closed_mean_mae_pct": "실현 평균 MAE",
        "closed_median_mae_pct": "실현 중앙 MAE",
        "closed_mean_holding_sessions": "실현 평균 보유 세션",
        "closed_median_holding_sessions": "실현 중앙 보유 세션",
        "closed_p90_holding_sessions": "실현 p90 보유 세션",
        "all_mean_holding_sessions": "전체 평균 보유 세션",
        "all_median_holding_sessions": "전체 중앙 보유 세션",
        "all_p90_holding_sessions": "전체 p90 보유 세션",
        "open_marked_count": "미청산 exact 평가 수",
        "open_unresolved_count": "미청산 평가 미해결 수",
        "open_mark_coverage_pct": "미청산 exact 평가 커버리지",
        "open_mean_gross_pct": "미청산 평균 평가수익",
        "open_median_gross_pct": "미청산 중앙 평가수익",
        "open_le_30_count": "미청산 -30% 이하 수",
        "open_le_30_rate_pct": "미청산 -30% 비율",
        "open_le_50_count": "미청산 -50% 이하 수",
        "open_le_50_rate_pct": "미청산 -50% 비율",
    }
    rows = []
    for key, label in labels.items():
        cv, tv = control.get(key), test.get(key)
        if key.endswith("_count") or key in {"filled_count", "realized_count", "open_count"}:
            unit = "count"
        elif key == "profit_factor":
            unit = "ratio"
        elif key.endswith("sessions"):
            unit = "sessions"
        else:
            unit = "pct"
        rows.append({
            "metric": key,
            "label_ko": label,
            "control": cv,
            "test": tv,
            "test_minus_control": float(tv) - float(cv) if cv is not None and tv is not None else None,
            "unit": unit,
        })
    return pd.DataFrame(rows)


def _report(
    control: dict[str, Any],
    test: dict[str, Any],
    c_metrics: dict[str, Any],
    t_metrics: dict[str, Any],
    signal_counts: dict[str, Any],
    paired: dict[str, Any],
    deep_exit_summary: dict[str, Any],
    verdict: str,
    annual: pd.DataFrame,
    validation: dict[str, Any],
) -> str:
    primary_rows = [
        ("실현 평균 / 중앙 수익률", "mean_gross_pct", "median_gross_pct", None),
        ("실현 승률", "win_rate_pct", None, None),
        ("평균 이익 / 손실", "average_winner_pct", "average_loser_pct", None),
        ("PF / 기대값", "profit_factor", "expectancy_pct", None),
        ("+20% 이상 비율", "ge_20_rate_pct", None, None),
        ("+50% 이상 비율", "ge_50_rate_pct", None, None),
        ("+100% 이상 비율", "ge_100_rate_pct", None, None),
        ("-20% 이하 비율", "le_20_rate_pct", None, None),
        ("-30% 이하 비율", "le_30_rate_pct", None, None),
        ("-50% 이하 비율", "le_50_rate_pct", None, None),
        ("미청산 수 / exact평가 / unresolved", "open_count", "open_marked_count", "open_unresolved_count"),
        ("미청산 exact 평가 커버리지", "open_mark_coverage_pct", None, None),
        ("미청산 평균 / 중앙 평가수익", "open_mean_gross_pct", "open_median_gross_pct", None),
        ("미청산 -30% / -50% 건수", "open_le_30_count", "open_le_50_count", None),
        ("미청산 -30% / -50% 비율", "open_le_30_rate_pct", "open_le_50_rate_pct", None),
        ("실현 MFE 평균 / 중앙", "closed_mean_mfe_pct", "closed_median_mfe_pct", None),
        ("실현 MAE 평균 / 중앙", "closed_mean_mae_pct", "closed_median_mae_pct", None),
        ("실현 보유 평균 / 중앙 / p90 세션", "closed_mean_holding_sessions", "closed_median_holding_sessions", "closed_p90_holding_sessions"),
        ("전체 보유 평균 / 중앙 / p90 세션", "all_mean_holding_sessions", "all_median_holding_sessions", "all_p90_holding_sessions"),
    ]
    table = ["| 지표 | CONTROL | TEST: 첫 DEEP 청산 |", "|---|---:|---:|"]
    for label, k1, k2, k3 in primary_rows:
        def fmt_for(key: str, value: Any) -> str:
            if key.endswith("count") or key in {"open_count", "open_marked_count"}:
                return "n/a" if value is None else f"{int(value):,}"
            return _fmt(value, "x" if key == "profit_factor" else "%" if "pct" in key else " 세션")
        if k2 is None:
            text_c, text_t = fmt_for(k1, c_metrics.get(k1)), fmt_for(k1, t_metrics.get(k1))
        else:
            text_c = f"{fmt_for(k1, c_metrics.get(k1))} / {fmt_for(k2, c_metrics.get(k2))}"
            text_t = f"{fmt_for(k1, t_metrics.get(k1))} / {fmt_for(k2, t_metrics.get(k2))}"
            if k3 is not None:
                text_c += f" / {fmt_for(k3, c_metrics.get(k3))}"
                text_t += f" / {fmt_for(k3, t_metrics.get(k3))}"
        table.append(f"| {label} | {text_c} | {text_t} |")
    annual_lines = [
        "| 연도 | 신호 | CONTROL 체결 | TEST 체결 | CONTROL 실현 | TEST 실현 | CONTROL 미청산 | TEST 미청산 | TEST DEEP 청산 | CONTROL 중앙 | TEST 중앙 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in annual.to_dict("records"):
        annual_lines.append(
            f"| {row['entry_signal_year']} | {row['raw_transition_signals']:,} | {row['control_filled']:,} | {row['test_filled']:,} | "
            f"{row['control_realized']:,} | {row['test_realized']:,} | {row['control_open']:,} | {row['test_open']:,} | "
            f"{row['test_deep_exit_executed']:,} | {_fmt(row['control_closed_median_gross_pct'])} | {_fmt(row['test_closed_median_gross_pct'])} |"
        )
    rescue30 = paired.get("control_le_30_primary_pair_count", 0)
    rescued30 = paired.get("control_le_30_rescued_count", 0)
    rescue50 = paired.get("control_le_50_primary_pair_count", 0)
    rescued50 = paired.get("control_le_50_rescued_count", 0)
    damage = paired.get("control_winner_lower_return_count", 0)
    report = [
        "# Pattern B DEEP_DEPRESSED 첫 진입 청산 단순 백테스트 V01",
        "",
        f"판정: **{verdict}**",
        "",
        "## 규칙 / 비교 조건",
        "",
        f"- 신호 기간 {base.SIGNAL_START}~{base.SIGNAL_END}; 평가 cutoff {base.CUTOFF}.",
        "- CONTROL은 기존 V01 원장을 기준 커밋의 바이트 단위 산출물 그대로 재사용했어.",
        "- TEST는 월별 상태 전이와 신호일 이후 첫 exact adjusted Open 진입, 수수료·슬리피지·역사 매도세율표를 유지해. 보유 후 처음 관측하는 NORMAL 또는 DEEP_DEPRESSED 중 먼저 발생한 신호 이후 첫 합법 Open에서 전량 청산해.",
        "- DEEP 청산 뒤에는 같은 ISU의 포지션이 닫혀 다음 신호가 새 진입을 만들 수 있어. 그래서 CONTROL 체결 원장에서 손실 거래를 삭제하는 방식이 아니라 전체 신호를 TEST 상태머신으로 재생했어. raw transition 키 집합은 CONTROL과 같아.",
        "- 동일 월말 상태에서 NORMAL과 DEEP_DEPRESSED가 동시에 발생할 수 없으므로 우선순위 충돌은 0건. 먼저 나온 exit signal이 pending이면 뒤의 신호가 이를 대체하지 않아.",
        "- 미청산은 2026-09-21 exact adjusted close가 있는 거래만 평가하고, unresolved는 수익 통계 분모에서 제외했어.",
        "",
        "## CONTROL vs TEST",
        "",
        f"- 전이 후보 {signal_counts['raw_transition_signals']:,}; CONTROL / TEST 체결 {c_metrics['filled_count']:,} / {t_metrics['filled_count']:,}; CONTROL / TEST 실현 {c_metrics['realized_count']:,} / {t_metrics['realized_count']:,}.",
        *table,
        "",
        "승률·수익률 분포는 실현 gross 기준이고, 미청산 tail 비율은 exact cutoff 종가로 평가한 미청산만 분모로 사용해.",
        "",
        "## DEEP 청산 실행 및 paired outcome",
        "",
        f"- TEST에서 DEEP 청산 신호 {deep_exit_summary['deep_exit_signal_count']:,}건, cutoff 전 체결 완료 {deep_exit_summary['deep_exit_executed_count']:,}건({deep_exit_summary['deep_exit_rate_of_filled_pct']:.2f}% of TEST filled). 미체결 DEEP 청산 신호 {deep_exit_summary['deep_exit_unfilled_signal_count']:,}건.",
        f"- DEEP 청산 실현 gross 평균 / 중앙 {_fmt(deep_exit_summary['exit_return_mean_pct'])} / {_fmt(deep_exit_summary['exit_return_median_pct'])}; 청산 전 MAE 평균 / 중앙 {_fmt(deep_exit_summary['pre_exit_mae_mean_pct'])} / {_fmt(deep_exit_summary['pre_exit_mae_median_pct'])}.",
        f"- TEST DEEP 청산 체결 중 CONTROL에 같은 신호일 체결 원장이 있는 거래 {paired['matched_control_trade_count']:,}; CONTROL 실현 결과와 TEST 실현 Deep exit를 직접 비교한 표본 {paired['primary_closed_to_closed_pair_count']:,}. 비교 결과 TEST가 개선 {paired['primary_pair_improved_count']:,}, 악화 {paired['primary_pair_worsened_count']:,}, 동일 {paired['primary_pair_unchanged_count']:,}.",
        f"- CONTROL의 -30% 이하 matched 실현 거래 {rescue30:,}건 중 TEST DEEP 청산 후 -30% 위로 구제 {rescued30:,}건. -50% 이하 {rescue50:,}건 중 -50% 위로 구제 {rescued50:,}건.",
        f"- CONTROL 수익 winner 중 TEST DEEP 청산 결과가 더 낮아진 거래 {damage:,}건; CONTROL winner가 TEST에서 손실로 뒤집힌 수 {paired['control_winner_to_loss_count']:,}. CONTROL +20/+50/+100% 이상 winner가 각 threshold 아래로 내려온 수: {paired['control_ge_20_winner_damaged_below_20_count']:,} / {paired['control_ge_50_winner_damaged_below_50_count']:,} / {paired['control_ge_100_winner_damaged_below_100_count']:,}.",
        "- paired 효과는 같은 `(ticker, ISU, entry_signal_date)`의 CONTROL 실현 거래와 TEST DEEP exit 실현 거래를 비교해. CONTROL에서 해당 신호가 포지션 보유 중 억제됐으면 같은 거래의 실제 CONTROL 결과가 없으므로 paired 개선/손상 분모에서는 제외하고 별도 집계해.",
        "",
        "## 비용 및 평가",
        "",
        f"- 매수/매도 수수료 각 {base.COMMISSION_RATE*100:.3f}%; 매수 슬리피지 +{base.SLIPPAGE_RATE*100:.2f}%, 매도 -{base.SLIPPAGE_RATE*100:.2f}%; 기존 역사 매도세율표를 재사용했어. 새 비용 가정은 없어.",
        f"- TEST 세금표 적용 가능 실현 거래 {test['test_trade_metrics']['cost_covered_closed_net']['n']:,}; 수수료·슬리피지 적용 평균 {_fmt(test['test_trade_metrics']['closed_pre_tax_cost']['mean_pct'])}, 완전 net 평균 {_fmt(test['test_trade_metrics']['cost_covered_closed_net']['mean_pct'])}. 전체 기간 기본 비교지표는 gross야.",
        "",
        "## 연도별 비교",
        "",
        *annual_lines,
        "",
        "최근 진입 연도는 cutoff에 열려 있는 거래가 많을 수 있어 실현 수익 통계에 검열이 있어.",
        "",
        "## 판정과 답",
        "",
        f"- 전체 판정은 `{verdict}`야. 수익률 손실구제 수와 winner 손상 수, 실현 승률·중앙값·+50% 비율, 미청산 평가를 함께 고려했어.",
        "- 손실 구제만 보면 효과가 있지만, matched winner 손상과 전체 realized 수익성 변화까지 함께 봐야 해. 본 비교는 독립 trade return이며 포트폴리오 성과가 아니야.",
        "",
        "## 검증과 산출물",
        "",
        f"- 첫 NORMAL/DEEP exit signal 불일치 {validation['first_exit_signal_mismatches']}; NORMAL/DEEP 같은 관측 충돌 {validation['normal_deep_same_observation_collision_count']}.",
        f"- TEST 동일 ISU 중복 보유 {validation['overlapping_position_count']}; DEEP lifecycle 직접 검수 {validation['deep_exit_spot_checks_passed']}/{validation['deep_exit_spot_checks']} 통과.",
        f"- CONTROL 기준 원장 계보는 metadata의 기준 커밋 `{CONTROL_COMMIT}` 및 파일 SHA-256으로 기록했어.",
        "- 산출물: `control_vs_test.csv`, `test_trade_ledger.csv`, `test_deep_exit_trades.csv`, `deep_exit_matched_comparison.csv`, `winner_damage_trades.csv`, `loss_rescued_trades.csv`, `test_open_positions.csv`, `open_position_comparison.csv`, `annual_comparison.csv`, `deep_exit_lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
        "질문: `DEEP_DEPRESSED` 최초 진입 청산은 Pattern B 순수 전략의 실패 거래를 줄이는 데 실질적으로 도움이 되는가?",
        f"답: {verdict} — 구제 거래와 winner 손상, 전체 핵심 지표를 함께 보면 돼.",
        "",
    ]
    return "\n".join(report)


def run_backtest(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)
    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusions = base._read_monthly_samples(data_root, intervals, interval_to_component)
    control_summary, control_frame, control_signal_frame, control_lineage = pit_study._load_control(data_root, samples)
    control_trades = control_frame.to_dict("records")
    control_signals = control_signal_frame.to_dict("records")
    if control_summary["evaluation_cutoff"] != base.CUTOFF:
        raise RuntimeError("CONTROL cutoff differs from this task")
    costs = {
        "buy_commission_rate": base.COMMISSION_RATE,
        "sell_commission_rate": base.COMMISSION_RATE,
        "buy_slippage_rate": base.SLIPPAGE_RATE,
        "sell_slippage_rate": base.SLIPPAGE_RATE,
        "sell_tax_schedule": list(base.HISTORICAL_SELL_TAX_SCHEDULE),
        "tax_complete_from": "2021-01-01",
        "full_period_primary_metric": "gross",
        "net_metric_scope": "closed trades with a documented exit-date market sell-tax schedule",
    }
    if costs != control_summary["trade_cost_contract"]:
        raise RuntimeError("TEST cost contract differs from CONTROL")

    signals_by_identity, blocked_transitions = base._make_entry_signals(samples)
    all_events = [event for identity in sorted(signals_by_identity) for event in signals_by_identity[identity]]
    control_keys = [_key(row) for row in control_signals]
    event_keys = [_key(row) for row in all_events]
    if len(set(control_keys)) != len(control_keys) or set(control_keys) != set(event_keys):
        raise RuntimeError("TEST raw transition keys differ from CONTROL")
    if len(blocked_transitions) != int(control_summary["blocked_authority_transition_count"]):
        raise RuntimeError("TEST blocked authority-transition count differs from CONTROL")
    control_status_by_key = {_key(row): str(row["entry_signal_status"]) for row in control_signals}
    if len(control_status_by_key) != len(control_signals):
        raise RuntimeError("CONTROL has duplicate transition signal keys")
    for event in all_events:
        event["control_entry_signal_status"] = control_status_by_key[_key(event)]

    identities = sorted(signals_by_identity)
    tickers = sorted({ticker for ticker, _isu in identities})
    min_start_by_ticker = {
        ticker: min(
            event["entry_signal_date"]
            for identity, events in signals_by_identity.items()
            if identity[0] == ticker
            for event in events
        )
        for ticker in tickers
    }
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    daily_by_ticker: dict[str, pd.DataFrame | None] = {}
    ticker_load_audit: dict[str, dict[str, Any]] = {}
    for number, ticker in enumerate(tickers, start=1):
        loader = RepositoryV2DailyLoader(repository, start=min_start_by_ticker[ticker], end=base.CUTOFF)
        daily = loader.load(ticker)
        daily_by_ticker[ticker] = daily
        query_audit = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        ticker_load_audit[ticker] = {
            "status": query_audit.get("status"),
            "reason": query_audit.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "session_projection_summary": projection,
        }
        if number % 250 == 0:
            print(f"Loaded authoritative OHLC for {number:,}/{len(tickers):,} tickers", flush=True)

    active_identity_set = set(identities)
    active_samples = samples.loc[
        samples.apply(lambda row: (row["ticker"], row["isu_cd"]) in active_identity_set, axis=1)
    ].copy()
    prices_by_identity_component: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        normalized = (str(identity[0]), str(identity[1]))
        ticker_daily = daily_by_ticker.get(normalized[0])
        for component in sorted(group["component_id"].unique()):
            component_intervals = intervals_by_component.get((*normalized, component), [])
            prices_by_identity_component[(*normalized, component)] = base._component_price_rows(
                ticker_daily, component_intervals, component
            )

    test_trades: list[dict[str, Any]] = []
    original_id = base.STRATEGY_ID
    base.STRATEGY_ID = STRATEGY_ID
    try:
        for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=True):
            normalized = (str(identity[0]), str(identity[1]))
            observations = group.sort_values("snapshot_date").to_dict("records")
            daily_by_component = {
                component: prices_by_identity_component.get((*normalized, component), pd.DataFrame())
                for component in set(group["component_id"])
            }
            trades, _state = _simulate_identity_deep_exit(
                observations,
                signals_by_identity.get(normalized, []),
                daily_by_component,
                base.CUTOFF,
            )
            test_trades.extend(trades)
    finally:
        base.STRATEGY_ID = original_id

    for trade in test_trades:
        daily = prices_by_identity_component.get(
            (trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame()
        )
        base._path_metrics(trade, daily, trading_dates, base.CUTOFF)
        base._calculate_returns(trade)
        if trade.get("exit_signal_state") == "DEEP_DEPRESSED":
            trade["pre_exit_mae_pct"] = _pre_exit_mae_pct(trade, daily)
    test_metrics = _trade_summary(test_trades)
    control_trade_records = control_trades
    control_metrics = _trade_summary(control_trade_records)
    for label, metrics in (("CONTROL", control_metrics), ("TEST", test_metrics)):
        if metrics["filled_count"] != metrics["closed_count"] + metrics["open_count"]:
            raise RuntimeError(f"{label} close/open count reconciliation failed")
    for key in ("filled_count", "closed_count", "open_count"):
        expected = {
            "filled_count": control_summary["filled_trade_count"],
            "closed_count": control_summary["closed_trade_count"],
            "open_count": control_summary["open_trade_count"],
        }[key]
        if control_metrics[key] != expected:
            raise RuntimeError(f"CONTROL {key} fails original V01 reconciliation")
    if not math.isclose(control_metrics["closed_gross"]["mean_pct"], control_summary["closed_gross"]["mean_pct"], rel_tol=1e-11, abs_tol=1e-10):
        raise RuntimeError("CONTROL closed gross differs from original V01 summary")

    status_counts = Counter(event["entry_signal_status"] for event in all_events)
    if sum(status_counts.values()) != len(all_events):
        raise RuntimeError("TEST entry signal status counts do not reconcile with raw transitions")
    if len(test_trades) != status_counts["FILLED"]:
        raise RuntimeError("TEST filled signal count does not reconcile with trade ledger")
    if any(trade["entry_execution_date"] <= trade["entry_signal_date"] for trade in test_trades):
        raise RuntimeError("TEST contains same-day or look-ahead entry fill")
    if any(trade["entry_execution_date"] not in set(trading_dates) for trade in test_trades):
        raise RuntimeError("TEST entry execution is outside merged KRX sessions")
    if any(
        trade.get("exit_execution_date")
        and (trade["exit_execution_date"] <= trade["exit_signal_date"] or trade["exit_execution_date"] not in set(trading_dates))
        for trade in test_trades
    ):
        raise RuntimeError("TEST exit execution is not a later official KRX session")
    if len({trade["trade_id"] for trade in test_trades}) != len(test_trades):
        raise RuntimeError("TEST trade identifiers are not unique")
    overlapping = 0
    for identity, group in pd.DataFrame(test_trades).groupby(["ticker", "isu_cd"], sort=False):
        ordered = sorted(group.to_dict("records"), key=lambda row: row["entry_execution_date"])
        for prev, cur in zip(ordered, ordered[1:]):
            if cur["entry_execution_date"] <= (prev.get("exit_execution_date") or base.CUTOFF):
                overlapping += 1
                raise RuntimeError(f"overlapping TEST positions for {identity}")

    exit_validation = _validate_exit_signals(test_trades, samples)
    deep_exit_signals = [trade for trade in test_trades if trade.get("exit_signal_state") == "DEEP_DEPRESSED"]
    deep_exit_executed = [trade for trade in deep_exit_signals if trade.get("exit_execution_date") is not None]
    deep_exit_unfilled = [trade for trade in deep_exit_signals if trade.get("exit_execution_date") is None]
    normal_exit_count = sum(trade.get("exit_signal_state") == "NORMAL" and trade.get("exit_execution_date") is not None for trade in test_trades)
    deep_exit_gross = base._metric_summary(trade.get("gross_return_pct") for trade in deep_exit_executed)
    deep_exit_pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in deep_exit_executed)
    deep_exit_mae = base._metric_summary(trade.get("pre_exit_mae_pct") for trade in deep_exit_executed)
    deep_exit_summary = {
        "deep_exit_signal_count": len(deep_exit_signals),
        "deep_exit_executed_count": len(deep_exit_executed),
        "deep_exit_unfilled_signal_count": len(deep_exit_unfilled),
        "deep_exit_rate_of_filled_pct": 100.0 * len(deep_exit_executed) / len(test_trades) if test_trades else None,
        "normal_exit_executed_count": int(normal_exit_count),
        "exit_return_mean_pct": deep_exit_gross["mean_pct"],
        "exit_return_median_pct": deep_exit_gross["median_pct"],
        "exit_pre_tax_mean_pct": deep_exit_pre_tax["mean_pct"],
        "pre_exit_mae_mean_pct": deep_exit_mae["mean_pct"],
        "pre_exit_mae_median_pct": deep_exit_mae["median_pct"],
        "exit_gross_summary": deep_exit_gross,
    }
    spot_checks = _deep_exit_spot_checks(test_trades, samples, prices_by_identity_component, trading_dates)
    pair_frame, rescue_frame, damage_frame, paired = _paired_deep_exit_comparison(
        test_trades, control_trade_records, control_status_by_key
    )
    c_metrics = _metrics_for_table(control_summary, control_trade_records)
    t_metrics = _metrics_for_table(test_metrics, test_trades)
    comparison = _comparison_table(c_metrics, t_metrics)
    signals_frame = pd.DataFrame(all_events)
    signal_cross = (
        signals_frame.groupby(["control_entry_signal_status", "entry_signal_status"], dropna=False)
        .size().reset_index(name="count")
        .rename(columns={"control_entry_signal_status": "control_status", "entry_signal_status": "test_status"})
    )
    control_open = [trade for trade in control_trade_records if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    test_open = [trade for trade in test_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    open_compare = pd.DataFrame([
        {"cohort": "CONTROL_ALL", **control_metrics["open_positions"]},
        {"cohort": "TEST_DEEP_EXIT", **test_metrics["open_positions"]},
    ])
    annual = _annual_comparison(control_trade_records, test_trades, all_events)
    projection_audit = {
        "silent_inner_drop_count": sum(int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0) for row in ticker_load_audit.values()),
        "explicit_exclusion_count": sum(int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0) for row in ticker_load_audit.values()),
    }
    if projection_audit["silent_inner_drop_count"] != 0:
        raise RuntimeError("Repository V2 reports silent inner drops")

    verdict = "PATTERN_B_DEEP_EXIT_MIXED"
    # Conservative and fixed, explicit tradeoff rule (defined before using the result):
    # IMPROVED needs lower realized -30/-50 tails and open -30/-50 tails, no lower median/win/+50,
    # plus more paired deep exits that improve than worsen. NO_BENEFIT if tails do not improve,
    # quality is lower, and paired deep exits improve no more often than they worsen.
    risk_keys = ("le_30_rate_pct", "le_50_rate_pct", "open_le_30_rate_pct", "open_le_50_rate_pct")
    risk_improved = all(
        c_metrics[key] is not None and t_metrics[key] is not None
        for key in risk_keys
    ) and all(t_metrics[key] < c_metrics[key] for key in risk_keys)
    quality_retained = (
        t_metrics["median_gross_pct"] >= c_metrics["median_gross_pct"]
        and t_metrics["win_rate_pct"] >= c_metrics["win_rate_pct"]
        and t_metrics["ge_50_rate_pct"] >= c_metrics["ge_50_rate_pct"]
    )
    if risk_improved and quality_retained and paired["primary_pair_improved_count"] > paired["primary_pair_worsened_count"]:
        verdict = "PATTERN_B_DEEP_EXIT_IMPROVED"
    elif (
        not risk_improved
        and not quality_retained
        and paired["primary_pair_improved_count"] <= paired["primary_pair_worsened_count"]
    ):
        verdict = "PATTERN_B_DEEP_EXIT_NO_BENEFIT"

    validation = {
        **exit_validation,
        "overlapping_position_count": overlapping,
        "deep_exit_spot_checks": len(spot_checks),
        "deep_exit_spot_checks_passed": sum(row["all_checks_pass"] for row in spot_checks),
        "same_raw_transition_keys_as_control": True,
        "same_cost_contract_as_control": costs == control_summary["trade_cost_contract"],
        "closed_plus_open_reconciles_to_filled": len(test_trades) == len(test_open) + sum(t.get("trade_status") == "REALIZED" for t in test_trades),
        "repository_v2_silent_inner_drop_count_zero": projection_audit["silent_inner_drop_count"] == 0,
    }
    test_summary = {
        "strategy_id": STRATEGY_ID,
        "verdict": verdict,
        "signal_start": base.SIGNAL_START,
        "signal_end": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "raw_transition_signal_count": len(all_events),
        "blocked_authority_transition_count": len(blocked_transitions),
        "control_signal_status_counts": dict(Counter(control_status_by_key.values())),
        "test_signal_status_counts": dict(status_counts),
        "control_trade_metrics": control_metrics,
        "test_trade_metrics": test_metrics,
        "deep_exit": deep_exit_summary,
        "paired_deep_exit_comparison": paired,
        "cost_contract": costs,
        "control_lineage": control_lineage,
        "control_deep_exit_stop_was_not_applied": True,
        "permanent_exclusion_identity_count": permanent_exclusions,
        "repository_v2_projection_audit": projection_audit,
        "ticker_price_load_count": len(ticker_load_audit),
        "price_rows_loaded": sum(row["rows"] for row in ticker_load_audit.values()),
        "deep_exit_lifecycle_spot_checks": len(spot_checks),
        "deep_exit_lifecycle_spot_checks_passed": validation["deep_exit_spot_checks_passed"],
        "validation_checks": validation,
        "source_provenance": provenance,
        "elapsed_seconds": round(time.time() - started, 2),
    }

    test_deep_ledger = [trade for trade in test_trades if trade.get("exit_signal_state") == "DEEP_DEPRESSED"]
    _write_csv(output_dir / "control_vs_test.csv", comparison)
    _write_csv(output_dir / "test_trade_ledger.csv", test_trades)
    _write_csv(output_dir / "test_deep_exit_trades.csv", test_deep_ledger)
    _write_csv(output_dir / "deep_exit_matched_comparison.csv", pair_frame)
    _write_csv(output_dir / "winner_damage_trades.csv", damage_frame)
    _write_csv(output_dir / "loss_rescued_trades.csv", rescue_frame)
    _write_csv(output_dir / "test_open_positions.csv", test_open)
    _write_csv(output_dir / "control_vs_test_signal_status.csv", signal_cross)
    _write_csv(output_dir / "open_position_comparison.csv", open_compare)
    _write_csv(output_dir / "annual_comparison.csv", annual)
    _write_csv(output_dir / "deep_exit_lifecycle_spot_checks.csv", spot_checks)
    (output_dir / "summary.json").write_text(json.dumps(test_summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    metadata = {
        "study": "KRX Pattern B DEEP exit simple backtest V01",
        "created_at_local_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "start_head": START_HEAD,
        "control_commit": CONTROL_COMMIT,
        "control_artifact": control_lineage,
        "strategy_id": STRATEGY_ID,
        "verdict": verdict,
        "signal_start": base.SIGNAL_START,
        "signal_end": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "entry_rule": "unchanged adjacent month previous non-DEPRESSED to current DEPRESSED",
        "exit_rule": "first observed NORMAL or DEEP_DEPRESSED while held; execute at first exact supported adjusted Open afterward; first trigger remains pending until fill",
        "deep_exit_reason": "DEEP_DEPRESSED_STOP",
        "normal_exit_reason": "NORMAL_RECOVERY",
        "portfolio_model": "none; independent trade return ratios",
        "market_cap_filter": False,
        "future_delisting_filter": False,
        "cost_contract": costs,
        "verdict_rule": {
            "improved": "closed -30/-50 and open exact-mark -30/-50 rates all strictly lower; realized median, win rate, and +50% rate no lower; matched paired improvements exceed worsened outcomes",
            "no_benefit": "the improved risk condition fails, realized median or win rate or +50% rate is lower, and matched paired improvements do not exceed worsened outcomes",
            "otherwise": "mixed",
            "open_tail_denominator": "positions with an exact adjusted close on the evaluation cutoff",
        },
        "annual_and_pairing_definitions": {
            "deep_exit_rate_denominator": "TEST filled trades",
            "primary_pairing": "same ticker+ISU+entry_signal_date; both CONTROL and TEST realized; test exit reason DEEP_DEPRESSED_STOP",
            "loss_rescued_threshold": "CONTROL gross return <= -30/-50 and TEST deep-exit gross return > same threshold",
            "winner_damage": "CONTROL realized gross > 0 and TEST deep-exit gross is lower; +20/+50/+100 tier damage listed separately",
            "open_control_marks": "shown in paired comparison as cutoff marks; excluded from primary final-outcome rescue/winner counts",
        },
        "output_files": [
            "report.md", "control_vs_test.csv", "test_trade_ledger.csv", "test_deep_exit_trades.csv",
            "deep_exit_matched_comparison.csv", "winner_damage_trades.csv", "loss_rescued_trades.csv",
            "test_open_positions.csv", "control_vs_test_signal_status.csv", "open_position_comparison.csv",
            "annual_comparison.csv", "deep_exit_lifecycle_spot_checks.csv", "summary.json", "metadata.json",
        ],
        "source_provenance": provenance,
        "ticker_price_load_audit": ticker_load_audit,
        "validation_checks": validation,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    report = _report(
        control_summary, test_summary, c_metrics, t_metrics,
        {"raw_transition_signals": len(all_events)}, paired, deep_exit_summary,
        verdict, annual, validation,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(test_summary, ensure_ascii=False, indent=2, default=_json_default), flush=True)
    print(f"Output: {output_dir}", flush=True)
    return test_summary


def _write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run_backtest(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
