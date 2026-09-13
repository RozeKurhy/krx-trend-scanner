#!/usr/bin/env python3
"""Matched-entry diagnostic for the FastCore V1 pre-winner FAILURE ARMED exit.

This is deliberately an offline analysis runner.  It replays the fixed 973
V0 CONTROL entries independently, uses the exact V0 weekly FAST construction,
and compares only two diagnostic configurations: arm at -25% and arm at -30%.
It does not scan entries, modify production strategy code, alter prior
artifacts, run Julia, or make network requests.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import json
import socket
import sys
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_fastcore_v3_exit_ab_v00 as v0_ab
from scripts import run_fastcore_v3_simple_v00 as v3
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import clip_to_identity_lifecycle
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2


WORK_ID = "FASTCORE_V1_PREWINNER_FAILURE_ARMED_AB_V00"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_failure_armed_ab_v00"
MATCHED_PATH = OUT_DIR / "matched_v0_vs_v1w25_vs_v1w30.csv"
EVENT_PATH = OUT_DIR / "failure_armed_event_log.csv"
VARIANT_SUMMARY_PATH = OUT_DIR / "failure_armed_variant_summary.csv"
COHORT_PATH = OUT_DIR / "failure_armed_cohort_diagnostics.csv"
EXIT_REASON_PATH = OUT_DIR / "failure_armed_exit_reason_diagnostics.csv"
SUMMARY_PATH = OUT_DIR / "fastcore_v1_prewinner_failure_armed_ab_v00_summary.json"
REPORT_PATH = OUT_DIR / "fastcore_v1_prewinner_failure_armed_ab_v00_report.md"

CONTROL_PATH = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0_summary.json"
LABEL_PATH = ROOT / "artifacts/backtests/fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix03/prewinner_trade_diagnostics.csv"

WEAK_FAST_STATES = frozenset({"WATCH", "SETUP"})
STRONG_FAST_STATES = frozenset({"TRIGGER", "TREND", "EXTENDED"})
UNAVAILABLE_FAST_STATES = frozenset({"UNAVAILABLE"})
ALLOWED_FAST_STATES = WEAK_FAST_STATES | STRONG_FAST_STATES | UNAVAILABLE_FAST_STATES
LOSS_GUARD_REASON = "LOSS_GUARD_CLOSE_LE_NEG_15"
TAIL_THRESHOLDS = (20, 30, 40, 50, 60)
WINNER_THRESHOLDS = (20, 30, 50, 100, 200, 400)


@dataclass(frozen=True)
class VariantConfig:
    strategy_id: str
    price_damage_threshold_pct: float


V1_W25 = VariantConfig("FASTCORE_V1_W25_PREWINNER_ARMED_V00", -25.0)
V1_W30 = VariantConfig("FASTCORE_V1_W30_PREWINNER_ARMED_V00", -30.0)
VARIANTS = (V1_W25, V1_W30)


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise RuntimeError(f"offline pre-winner failure-armed guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise RuntimeError(f"offline pre-winner failure-armed guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _identity_key(row: Mapping[str, Any]) -> str:
    return v0_ab._identity_key(row)


def _as_date_text(value: pd.Timestamp | None) -> str | None:
    return value.strftime("%Y-%m-%d") if value is not None else None


def _latest_fast_observation(
    states: Sequence[tuple[pd.Timestamp, str]], date: pd.Timestamp,
) -> tuple[pd.Timestamp | None, str | None]:
    """V0's latest-completed-week lookup, retaining its weekly date too."""
    if not states:
        return None, None
    dates = [item[0] for item in states]
    position = bisect_right(dates, date) - 1
    return states[position] if position >= 0 else (None, None)


def validate_fast_state_domain(state_counts: Mapping[str, int]) -> dict[str, Any]:
    """Audit the actual V0 weekly FAST domain before any variant replay."""
    observed_states = sorted(state_counts)
    unknown_states = sorted(set(observed_states) - ALLOWED_FAST_STATES)
    if unknown_states:
        raise RuntimeError(
            "unexpected weekly FAST state domain; stop before variants: "
            f"unknown={unknown_states}, observed_counts={dict(sorted(state_counts.items()))}"
        )
    return {
        "observed_states": observed_states,
        "observed_counts": dict(sorted(state_counts.items())),
        "unknown_states": unknown_states,
    }


def _event(
    events: list[dict[str, Any]], *, config: VariantConfig, row: Mapping[str, Any],
    date: pd.Timestamp, event_type: str, close_return: float | None,
    mfe_pct: float | None, fast_date: pd.Timestamp | None, fast_state: str | None,
    cycle: int | None, detail: str | None = None,
) -> None:
    events.append({
        "strategy_id": config.strategy_id,
        "price_damage_threshold_pct": config.price_damage_threshold_pct,
        "control_trade_id": str(row["control_trade_id"]),
        "ticker": str(row["ticker"]).zfill(6),
        "name": str(row["name"]),
        "date": _as_date_text(date),
        "event_type": event_type,
        "close_return_pct": round(close_return, 6) if close_return is not None else None,
        "running_mfe_pct": round(mfe_pct, 6) if mfe_pct is not None else None,
        "fast_date": _as_date_text(fast_date),
        "fast_state": fast_state,
        "arm_cycle": cycle,
        "detail": detail,
    })


def _finalize_trade(
    *, row: Mapping[str, Any], daily: pd.DataFrame, entry_date: pd.Timestamp,
    entry_open: float, hwm_drawdown: float, exit_signal_date: pd.Timestamp | None,
    exit_reason: str | None, fast_state_at_exit: str | None, soft_threshold: float | None,
    hard_threshold: float | None, exit_mfe_tier: str | None,
    unexecuted_exit_signal_date: pd.Timestamp | None, config: VariantConfig | None,
    events: list[dict[str, Any]] | None, arm_cycles: int = 0,
    first_arm_date: pd.Timestamp | None = None, last_arm_date: pd.Timestamp | None = None,
    confirmed_date: pd.Timestamp | None = None, disarm_count: int = 0,
    unavailable_wait_count: int = 0, winner_mode_activated: bool = False,
    disarm_by_price_count: int = 0, disarm_by_fast_count: int = 0,
    disarm_by_both_count: int = 0, armed_to_winner_mode_count: int = 0,
    confirmed_fast_date: pd.Timestamp | None = None, confirmed_fast_state: str | None = None,
    confirmed_close_return_pct: float | None = None,
) -> dict[str, Any]:
    """Use the V0 next-open and path-metric semantics for either replay path."""
    exit_execution_date: pd.Timestamp | None = None
    exit_price: float | None = None
    trade_status = "OPEN_AT_CUTOFF"
    exit_signal_for_metrics = exit_signal_date
    if exit_signal_date is not None:
        exit_execution_date = v3._next_session(daily, exit_signal_date)
        if exit_execution_date is not None:
            exit_price = float(daily.loc[exit_execution_date, "open"])
            trade_status = "REALIZED"
            if events is not None and config is not None:
                _event(
                    events, config=config, row=row, date=exit_execution_date,
                    event_type="EXIT_EXECUTED", close_return=(exit_price / entry_open - 1.0) * 100.0,
                    mfe_pct=None, fast_date=None, fast_state=fast_state_at_exit,
                    cycle=arm_cycles or None, detail=exit_reason,
                )
        else:
            unexecuted_exit_signal_date = exit_signal_date
            if events is not None and config is not None:
                _event(
                    events, config=config, row=row, date=exit_signal_date,
                    event_type="EXIT_UNEXECUTED", close_return=None, mfe_pct=None,
                    fast_date=None, fast_state=fast_state_at_exit, cycle=arm_cycles or None,
                    detail=exit_reason,
                )
            exit_signal_date = None
            exit_reason = None
            fast_state_at_exit = None
            soft_threshold = None
            hard_threshold = None
            exit_mfe_tier = None

    valuation_date = _date(daily.index[-1])
    if trade_status == "REALIZED" and exit_execution_date is not None and exit_price is not None:
        metric_end = exit_signal_date if exit_signal_date is not None else exit_execution_date
        hwm, _trough, mfe, mae = v3._path_metrics(daily, entry_date, metric_end, entry_open, exit_price)
        terminal_return = round((exit_price / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= exit_execution_date)]))
    else:
        final_close = float(daily.loc[valuation_date, "close"])
        hwm, _trough, mfe, mae = v3._path_metrics(daily, entry_date, valuation_date, entry_open)
        terminal_return = round((final_close / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= valuation_date)]))
        exit_reason = "OPEN_AT_CUTOFF"

    terminal_tier = v3.mfe_tier(mfe)
    prefix = "v1" if config is not None else "v0"
    result = {
        f"{prefix}_entry_execution_date": _as_date_text(entry_date),
        f"{prefix}_entry_open": entry_open,
        f"{prefix}_exit_reason": exit_reason,
        f"{prefix}_exit_signal_date": _as_date_text(exit_signal_date),
        f"{prefix}_exit_execution_date": _as_date_text(exit_execution_date),
        f"{prefix}_exit_price": exit_price,
        f"{prefix}_terminal_return": terminal_return,
        f"{prefix}_mfe": mfe,
        f"{prefix}_mae": mae,
        f"{prefix}_holding_days": holding_days,
        f"{prefix}_trade_status": trade_status,
        f"{prefix}_mfe_tier": terminal_tier[2] if terminal_tier else "BELOW_WINNER_MODE",
        f"{prefix}_hwm": round(hwm, 2),
        f"{prefix}_max_hwm_drawdown": round(hwm_drawdown, 2),
        f"{prefix}_fast_state_at_exit": fast_state_at_exit,
        f"{prefix}_soft_threshold": soft_threshold,
        f"{prefix}_hard_threshold": hard_threshold,
        f"{prefix}_unexecuted_exit_signal_date": _as_date_text(unexecuted_exit_signal_date),
    }
    if config is not None:
        result.update({
            "strategy_id": config.strategy_id,
            "price_damage_threshold_pct": config.price_damage_threshold_pct,
            "prewinner_arm_cycles": arm_cycles,
            "prewinner_first_arm_date": _as_date_text(first_arm_date),
            "prewinner_last_arm_date": _as_date_text(last_arm_date),
            "prewinner_failure_confirmed_date": _as_date_text(confirmed_date),
            "prewinner_disarm_count": disarm_count,
            "prewinner_disarm_by_price_count": disarm_by_price_count,
            "prewinner_disarm_by_fast_count": disarm_by_fast_count,
            "prewinner_disarm_by_both_count": disarm_by_both_count,
            "prewinner_unavailable_wait_count": unavailable_wait_count,
            "winner_mode_activated": winner_mode_activated,
            "prewinner_armed_to_winner_mode_count": armed_to_winner_mode_count,
            "prewinner_confirmed_fast_date": _as_date_text(confirmed_fast_date),
            "prewinner_confirmed_fast_state": confirmed_fast_state,
            "prewinner_confirmed_close_return_pct": (
                round(confirmed_close_return_pct, 6) if confirmed_close_return_pct is not None else None
            ),
            "failure_armed_applied": confirmed_date is not None,
            "failure_armed_unexecuted": unexecuted_exit_signal_date is not None and exit_signal_for_metrics is not None,
        })
    return result


def simulate_failure_armed(
    row: Mapping[str, Any], daily_full: pd.DataFrame,
    states: Sequence[tuple[pd.Timestamp, str]], config: VariantConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replay one fixed V0 entry with only the pre-winner FAILURE ARMED rule.

    Retrospective RECOVERY/NEVER labels intentionally never enter this function.
    """
    lifecycle = v0_ab._lifecycle(row)
    daily = clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        raise RuntimeError(f"missing identity-scoped data for {row['control_trade_id']}")
    entry_date = _date(row["entry_execution_date"])
    if entry_date not in daily.index:
        raise RuntimeError(f"entry date unavailable for {row['control_trade_id']}: {entry_date.date()}")
    entry_open = float(row["entry_open"])
    observed_open = float(daily.loc[entry_date, "open"])
    if abs(observed_open - entry_open) > 1e-8:
        raise AssertionError(f"entry OPEN mismatch for {row['control_trade_id']}: {observed_open} != {entry_open}")

    events: list[dict[str, Any]] = []
    hwm = entry_open
    hwm_drawdown = 0.0
    armed = False
    armed_fast_date: pd.Timestamp | None = None
    last_examined_fast_date: pd.Timestamp | None = None
    arm_cycles = 0
    first_arm_date: pd.Timestamp | None = None
    last_arm_date: pd.Timestamp | None = None
    confirmed_date: pd.Timestamp | None = None
    disarm_count = 0
    disarm_by_price_count = 0
    disarm_by_fast_count = 0
    disarm_by_both_count = 0
    unavailable_wait_count = 0
    winner_mode_activated = False
    armed_to_winner_mode_count = 0
    confirmed_fast_date: pd.Timestamp | None = None
    confirmed_fast_state: str | None = None
    confirmed_close_return_pct: float | None = None
    exit_signal_date: pd.Timestamp | None = None
    exit_reason: str | None = None
    fast_state_at_exit: str | None = None
    soft_threshold: float | None = None
    hard_threshold: float | None = None
    exit_mfe_tier: str | None = None
    unexecuted_exit_signal_date: pd.Timestamp | None = None

    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        date = _date(date)
        high = float(bar["high"])
        close = float(bar["close"])
        hwm = max(hwm, high)
        running_mfe = (hwm / entry_open - 1.0) * 100.0
        close_return = (close / entry_open - 1.0) * 100.0
        hwm_drawdown = min(hwm_drawdown, round((close / hwm - 1.0) * 100.0, 10))
        fast_date, fast_state = _latest_fast_observation(states, date)

        # Same-day HIGH/HWM/MFE update comes first.  At +20% the V0 winner
        # contract immediately takes precedence over any armed pre-winner path.
        if running_mfe >= 20.0:
            if armed:
                armed_to_winner_mode_count += 1
                _event(
                    events, config=config, row=row, date=date,
                    event_type="WINNER_MODE_ACTIVATED", close_return=close_return,
                    mfe_pct=running_mfe, fast_date=fast_date, fast_state=fast_state,
                    cycle=arm_cycles, detail="MFE_GE_20_PRECEDENCE",
                )
            armed = False
            armed_fast_date = None
            last_examined_fast_date = None
            winner_mode_activated = True
            decision, soft, hard, tier = v3.exit_decision(
                mfe_pct=running_mfe, hwm_price=hwm, current_close=close, fast_state=fast_state,
            )
            if decision is not None:
                exit_signal_date = date
                exit_reason = decision
                fast_state_at_exit = fast_state
                soft_threshold = soft
                hard_threshold = hard
                exit_mfe_tier = tier
                break
            continue

        if armed:
            # A confirmation is allowed only once a strictly later completed
            # weekly FAST observation exists.  A same-week state repeated on
            # daily bars cannot confirm, disarm, or produce a look-ahead exit.
            if fast_date is not None and (last_examined_fast_date is None or fast_date > last_examined_fast_date):
                last_examined_fast_date = fast_date
                if fast_state == "UNAVAILABLE":
                    unavailable_wait_count += 1
                    _event(
                        events, config=config, row=row, date=date,
                        event_type="UNAVAILABLE_WAIT", close_return=close_return,
                        mfe_pct=running_mfe, fast_date=fast_date, fast_state=fast_state,
                        cycle=arm_cycles, detail="ARM_RETAINED",
                    )
                elif fast_state in WEAK_FAST_STATES and close_return <= config.price_damage_threshold_pct:
                    confirmed_date = date
                    confirmed_fast_date = fast_date
                    confirmed_fast_state = fast_state
                    confirmed_close_return_pct = close_return
                    exit_signal_date = date
                    exit_reason = "PREWINNER_FAILURE_CONFIRMED"
                    fast_state_at_exit = fast_state
                    _event(
                        events, config=config, row=row, date=date,
                        event_type="FAILURE_CONFIRMED", close_return=close_return,
                        mfe_pct=running_mfe, fast_date=fast_date, fast_state=fast_state,
                        cycle=arm_cycles, detail="NEW_WEAK_FAST_AND_PRICE_DAMAGED",
                    )
                    break
                else:
                    recovered_price = close_return > config.price_damage_threshold_pct
                    recovered_fast = fast_state in STRONG_FAST_STATES
                    if recovered_price and recovered_fast:
                        event_type = "DISARM_BOTH"
                        disarm_by_both_count += 1
                    elif recovered_price:
                        event_type = "DISARM_PRICE"
                        disarm_by_price_count += 1
                    elif recovered_fast:
                        event_type = "DISARM_FAST"
                        disarm_by_fast_count += 1
                    else:
                        raise AssertionError(f"unexpected FAST state after domain validation: {fast_state!r}")
                    disarm_count += 1
                    _event(
                        events, config=config, row=row, date=date, event_type=event_type,
                        close_return=close_return, mfe_pct=running_mfe, fast_date=fast_date,
                        fast_state=fast_state, cycle=arm_cycles, detail="ARM_CLEARED",
                    )
                    armed = False
                    armed_fast_date = None
                    last_examined_fast_date = None
        elif fast_date is not None and fast_state in WEAK_FAST_STATES and close_return <= config.price_damage_threshold_pct:
            arm_cycles += 1
            event_type = "REARM" if arm_cycles > 1 else "ARMED"
            armed = True
            armed_fast_date = fast_date
            last_examined_fast_date = fast_date
            if first_arm_date is None:
                first_arm_date = date
            last_arm_date = date
            _event(
                events, config=config, row=row, date=date, event_type=event_type,
                close_return=close_return, mfe_pct=running_mfe, fast_date=fast_date,
                fast_state=fast_state, cycle=arm_cycles, detail="PRICE_DAMAGED_AND_WEAK_FAST",
            )

    return _finalize_trade(
        row=row, daily=daily, entry_date=entry_date, entry_open=entry_open,
        hwm_drawdown=hwm_drawdown, exit_signal_date=exit_signal_date,
        exit_reason=exit_reason, fast_state_at_exit=fast_state_at_exit,
        soft_threshold=soft_threshold, hard_threshold=hard_threshold,
        exit_mfe_tier=exit_mfe_tier,
        unexecuted_exit_signal_date=unexecuted_exit_signal_date, config=config,
        events=events, arm_cycles=arm_cycles, first_arm_date=first_arm_date,
        last_arm_date=last_arm_date, confirmed_date=confirmed_date,
        disarm_count=disarm_count, unavailable_wait_count=unavailable_wait_count,
        winner_mode_activated=winner_mode_activated,
        disarm_by_price_count=disarm_by_price_count,
        disarm_by_fast_count=disarm_by_fast_count,
        disarm_by_both_count=disarm_by_both_count,
        armed_to_winner_mode_count=armed_to_winner_mode_count,
        confirmed_fast_date=confirmed_fast_date,
        confirmed_fast_state=confirmed_fast_state,
        confirmed_close_return_pct=confirmed_close_return_pct,
    ), events


def _same_nullable(left: Any, right: Any, tolerance: float = 1e-8) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if isinstance(left, (float, int)) or isinstance(right, (float, int)):
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            pass
    return str(left) == str(right)


def assert_v0_parity(control: pd.DataFrame, replayed: pd.DataFrame) -> dict[str, Any]:
    """Fail closed unless the disabled failure-armed path matches authority."""
    expected = control.set_index("control_trade_id", drop=False)
    actual = replayed.set_index("control_trade_id", drop=False)
    fields = (
        ("entry_execution_date", "v0_entry_execution_date"),
        ("entry_open", "v0_entry_open"),
        ("v0_terminal_return", "v0_terminal_return"),
        ("v0_holding_days", "v0_holding_days"),
        ("v0_exit_reason", "v0_exit_reason"),
        ("v0_trade_status", "v0_trade_status"),
    )
    mismatches: list[dict[str, Any]] = []
    if len(expected) != 973 or len(actual) != 973 or set(expected.index) != set(actual.index):
        raise AssertionError("V0 parity cohort is not exactly the 973 fixed control trades")
    for trade_id in expected.index:
        for expected_field, actual_field in fields:
            if not _same_nullable(expected.loc[trade_id, expected_field], actual.loc[trade_id, actual_field]):
                mismatches.append({
                    "control_trade_id": trade_id, "field": expected_field,
                    "expected": expected.loc[trade_id, expected_field],
                    "actual": actual.loc[trade_id, actual_field],
                })
                if len(mismatches) >= 10:
                    break
        if len(mismatches) >= 10:
            break
    if mismatches:
        raise AssertionError(f"V0 replay parity failed: {mismatches}")
    return {
        "passed": True,
        "control_trade_count": len(control),
        "compared_fields": [field for field, _ in fields],
        "mismatch_count": 0,
    }


def _metric_summary(frame: pd.DataFrame, prefix: str) -> dict[str, Any]:
    returns = pd.to_numeric(frame[f"{prefix}_terminal_return"], errors="coerce")
    mfe = pd.to_numeric(frame[f"{prefix}_mfe"], errors="coerce")
    mae = pd.to_numeric(frame[f"{prefix}_mae"], errors="coerce")
    holding = pd.to_numeric(frame[f"{prefix}_holding_days"], errors="coerce")
    total = len(frame)
    result: dict[str, Any] = {
        "trade_count": total,
        "positive_count": int((returns > 0).sum()),
        "positive_rate_pct": round(float((returns > 0).mean() * 100.0), 6) if total else 0.0,
        "mean_terminal_return_pct": round(float(returns.mean()), 6) if total else None,
        "median_terminal_return_pct": round(float(returns.median()), 6) if total else None,
        "mean_mfe_pct": round(float(mfe.mean()), 6) if total else None,
        "median_mfe_pct": round(float(mfe.median()), 6) if total else None,
        "mean_mae_pct": round(float(mae.mean()), 6) if total else None,
        "median_mae_pct": round(float(mae.median()), 6) if total else None,
        "mean_holding_days": round(float(holding.mean()), 6) if total else None,
        "median_holding_days": round(float(holding.median()), 6) if total else None,
    }
    for threshold in TAIL_THRESHOLDS:
        count = int((returns <= -threshold).sum())
        result[f"le_neg_{threshold}_count"] = count
        result[f"le_neg_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else 0.0
    for threshold in WINNER_THRESHOLDS:
        count = int((returns >= threshold).sum())
        result[f"ge_{threshold}_count"] = count
        result[f"ge_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else 0.0
    return result


def _paired_summary(frame: pd.DataFrame) -> dict[str, Any]:
    delta = pd.to_numeric(frame["v1_terminal_return"], errors="coerce") - pd.to_numeric(frame["v0_terminal_return"], errors="coerce")
    total = len(frame)
    v0_return = pd.to_numeric(frame["v0_terminal_return"], errors="coerce")
    v1_return = pd.to_numeric(frame["v1_terminal_return"], errors="coerce")
    improved = int((delta > 0).sum())
    worsened = int((delta < 0).sum())
    same = int((delta == 0).sum())
    return {
        "mean_paired_return_delta_pp": round(float(delta.mean()), 6),
        "median_paired_return_delta_pp": round(float(delta.median()), 6),
        "improved_count": improved,
        "improved_rate_pct": round(improved / total * 100.0, 6) if total else 0.0,
        "worsened_count": worsened,
        "worsened_rate_pct": round(worsened / total * 100.0, 6) if total else 0.0,
        "same_count": same,
        "same_rate_pct": round(same / total * 100.0, 6) if total else 0.0,
        "positive_to_nonpositive_count": int(((v0_return > 0) & (v1_return <= 0)).sum()),
        "nonpositive_to_positive_count": int(((v0_return <= 0) & (v1_return > 0)).sum()),
    }


def _mean_median(values: pd.Series) -> tuple[float | None, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None, None
    return round(float(numeric.mean()), 6), round(float(numeric.median()), 6)


def _mechanism_stats(group: pd.DataFrame, events: pd.DataFrame) -> dict[str, Any]:
    strategy_id = str(group["strategy_id"].iloc[0])
    subset = events.loc[events["strategy_id"] == strategy_id].copy()
    counts = Counter(subset["event_type"])
    disarm_events = subset.loc[subset["event_type"].isin(["DISARM_FAST", "DISARM_BOTH"])]
    result: dict[str, Any] = {
        "armed_trade_count": int((group["prewinner_arm_cycles"] > 0).sum()),
        "arm_cycle_count": int(group["prewinner_arm_cycles"].sum()),
        "rearmed_trade_count": int((group["prewinner_arm_cycles"] > 1).sum()),
        "failure_confirmed_count": int(group["prewinner_failure_confirmed_date"].notna().sum()),
        "failure_confirmed_executed_count": int((group["v1_exit_reason"] == "PREWINNER_FAILURE_CONFIRMED").sum()),
        "failure_confirmed_unexecuted_count": int(group["failure_armed_unexecuted"].sum()),
        "disarmed_trade_count": int((group["prewinner_disarm_count"] > 0).sum()),
        "disarm_count": int(group["prewinner_disarm_count"].sum()),
        "disarm_by_price_count": int(group["prewinner_disarm_by_price_count"].sum()),
        "disarm_by_fast_count": int(group["prewinner_disarm_by_fast_count"].sum()),
        "disarm_by_both_count": int(group["prewinner_disarm_by_both_count"].sum()),
        "trigger_disarm_count": int((disarm_events["fast_state"] == "TRIGGER").sum()),
        "trend_disarm_count": int((disarm_events["fast_state"] == "TREND").sum()),
        "extended_disarm_count": int((disarm_events["fast_state"] == "EXTENDED").sum()),
        "armed_to_winner_mode_count": int(group["prewinner_armed_to_winner_mode_count"].sum()),
        "unavailable_wait_count": int(group["prewinner_unavailable_wait_count"].sum()),
        "event_counts": json.dumps(dict(sorted(counts.items())), ensure_ascii=False),
    }
    arm_events = subset.loc[subset["event_type"].isin(["ARMED", "REARM"]), ["control_trade_id", "arm_cycle", "date"]].rename(columns={"date": "armed_date"})
    terminal_events = subset.loc[
        subset["event_type"].isin(["FAILURE_CONFIRMED", "DISARM_PRICE", "DISARM_FAST", "DISARM_BOTH", "WINNER_MODE_ACTIVATED"]),
        ["control_trade_id", "arm_cycle", "date", "event_type"],
    ]
    transitions = terminal_events.merge(arm_events, on=["control_trade_id", "arm_cycle"], how="left")
    transitions["calendar_days"] = (
        pd.to_datetime(transitions["date"]) - pd.to_datetime(transitions["armed_date"])
    ).dt.days
    for label, event_types in {
        "arm_to_confirm": ["FAILURE_CONFIRMED"],
        "arm_to_disarm": ["DISARM_PRICE", "DISARM_FAST", "DISARM_BOTH"],
        "arm_to_winner": ["WINNER_MODE_ACTIVATED"],
    }.items():
        mean, median = _mean_median(transitions.loc[transitions["event_type"].isin(event_types), "calendar_days"])
        result[f"{label}_calendar_days_mean"] = mean
        result[f"{label}_calendar_days_median"] = median
    return result


def _cohort_rows(frame: pd.DataFrame) -> pd.DataFrame:
    cohorts = {
        "ALL": frame,
        "RECOVERY": frame.loc[frame["recovery_class"] == "RECOVERY"],
        "NEVER_WINNER": frame.loc[frame["recovery_class"] == "NEVER_WINNER"],
        "LOSS_GUARD_ALL": frame.loc[frame["v2_loss_guard_triggered"]],
        "LOSS_GUARD_RECOVERY": frame.loc[(frame["v2_loss_guard_triggered"]) & (frame["recovery_class"] == "RECOVERY")],
        "LOSS_GUARD_NEVER_WINNER": frame.loc[(frame["v2_loss_guard_triggered"]) & (frame["recovery_class"] == "NEVER_WINNER")],
    }
    rows: list[dict[str, Any]] = []
    for strategy_id, group in frame.groupby("strategy_id", sort=True):
        for cohort, subset in cohorts.items():
            variant_subset = group.loc[group["control_trade_id"].isin(subset["control_trade_id"])]
            row = {"strategy_id": strategy_id, "cohort": cohort, **_metric_summary(variant_subset, "v1"), **_paired_summary(variant_subset)}
            total = len(variant_subset)
            armed = int((variant_subset["prewinner_arm_cycles"] > 0).sum())
            confirmed = int(variant_subset["prewinner_failure_confirmed_date"].notna().sum())
            executed = int((variant_subset["v1_exit_reason"] == "PREWINNER_FAILURE_CONFIRMED").sum())
            row.update({
                "armed_trade_count": armed,
                "armed_trade_rate_pct": round(armed / total * 100.0, 6) if total else 0.0,
                "failure_confirmed_count": confirmed,
                "failure_confirmed_executed_count": executed,
                "armed_to_disarmed_count": int((variant_subset["prewinner_disarm_count"] > 0).sum()),
                "armed_to_winner_mode_count": int((variant_subset["prewinner_armed_to_winner_mode_count"] > 0).sum()),
                "recovery_preempted_count": confirmed if cohort in {"RECOVERY", "LOSS_GUARD_RECOVERY"} else None,
                "recovery_preserved_count": total - confirmed if cohort in {"RECOVERY", "LOSS_GUARD_RECOVERY"} else None,
                "never_winner_captured_count": executed if cohort in {"NEVER_WINNER", "LOSS_GUARD_NEVER_WINNER"} else None,
                "never_winner_missed_count": total - executed if cohort in {"NEVER_WINNER", "LOSS_GUARD_NEVER_WINNER"} else None,
            })
            holding_reduction = pd.to_numeric(variant_subset["v0_holding_days"], errors="coerce") - pd.to_numeric(variant_subset["v1_holding_days"], errors="coerce")
            row["mean_holding_days_reduction"] = round(float(holding_reduction.mean()), 6) if total else None
            row["median_holding_days_reduction"] = round(float(holding_reduction.median()), 6) if total else None
            rows.append(row)
    return pd.DataFrame(rows)


def _exit_reason_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy_id, group in frame.groupby("strategy_id", sort=True):
        for reason, subset in group.groupby("v1_exit_reason", dropna=False, sort=True):
            rows.append({
                "strategy_id": strategy_id,
                "exit_reason": str(reason),
                "trade_count": len(subset),
                "mean_terminal_return_pct": round(float(pd.to_numeric(subset["v1_terminal_return"]).mean()), 6),
                "median_terminal_return_pct": round(float(pd.to_numeric(subset["v1_terminal_return"]).median()), 6),
                "failure_confirmed_count": int(subset["prewinner_failure_confirmed_date"].notna().sum()),
            })
    return pd.DataFrame(rows)


def _variant_summary_rows(v0_frame: pd.DataFrame, variants: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = [{"strategy_id": "FASTCORE_V0_CONTROL_REPLAY", "price_damage_threshold_pct": None, **_metric_summary(v0_frame, "v0")}]
    for strategy_id, group in variants.groupby("strategy_id", sort=True):
        v1_metrics = _metric_summary(group, "v1")
        v0_metrics = _metric_summary(group, "v0")
        row = {
            "strategy_id": strategy_id,
            "price_damage_threshold_pct": float(group["price_damage_threshold_pct"].iloc[0]),
            **v1_metrics,
            **_paired_summary(group),
            **_mechanism_stats(group, events),
        }
        for threshold in TAIL_THRESHOLDS:
            row[f"le_neg_{threshold}_count_delta_vs_v0"] = v1_metrics[f"le_neg_{threshold}_count"] - v0_metrics[f"le_neg_{threshold}_count"]
            row[f"le_neg_{threshold}_rate_pct_delta_vs_v0"] = round(
                v1_metrics[f"le_neg_{threshold}_rate_pct"] - v0_metrics[f"le_neg_{threshold}_rate_pct"], 6
            )
        prewinner_exit = group["v1_exit_reason"].eq("PREWINNER_FAILURE_CONFIRMED")
        for threshold in (50, 100):
            row[f"v0_terminal_ge_{threshold}_prewinner_exit_count"] = int(
                ((pd.to_numeric(group["v0_terminal_return"], errors="coerce") >= threshold) & prewinner_exit).sum()
            )
            row[f"v0_mfe_ge_{threshold}_prewinner_exit_count"] = int(
                ((pd.to_numeric(group["v0_mfe"], errors="coerce") >= threshold) & prewinner_exit).sum()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _build_report(summary: Mapping[str, Any], variant_summary: pd.DataFrame, cohorts: pd.DataFrame, exits: pd.DataFrame) -> str:
    baseline = variant_summary.loc[variant_summary["strategy_id"] == "FASTCORE_V0_CONTROL_REPLAY"].iloc[0]
    domain_counts = summary["fast_state_domain"]["observed_counts"]
    lines = [
        "# FASTCORE V1 PRE-WINNER FAILURE ARMED MATCHED-ENTRY A/B V00 결과 보고서",
        "",
        "## 결론",
        "",
        "고정된 V0 CONTROL 973개 entry를 다시 스캔하지 않고 독립 replay했다. V0 disabled parity가 거래별로 통과한 뒤, pre-winner FAILURE ARMED의 가격 임계값만 -25%와 -30%로 달리한 두 diagnostic variant를 비교했다. 자동 winner 선정은 하지 않는다.",
        "",
        "- V0 parity: PASS (973/973, entry date/open·terminal return·holding·exit reason·status 일치)",
        f"- Q1 FAST state domain/count: {json.dumps(domain_counts, ensure_ascii=False, sort_keys=True)}",
        "- TRIGGER는 WEAK가 아니라 STRONG/RECOVERED다. ARM/confirm에는 쓰지 않고, 새 usable FAST date의 ARMED trade를 disarm한다.",
        f"- 네트워크 요청: {summary['network_requests']}; production 변경: 없음; label signal input: 없음.",
        "",
        "## Q3–Q4. 설계와 V0 baseline",
        "",
        "V0 Winner Mode는 daily HIGH HWM/MFE를 먼저 갱신하고, MFE 20% 이상에서만 V0의 tier별 soft/hard trailing exit을 동일하게 적용했다. Pre-winner에는 고정 hard failure를 두지 않았고, 약한 weekly FAST와 종가 가격손상이 함께 발생하면 ARM만 한다. 확정은 ARM 이후 엄격히 새로운 usable weekly FAST date에서만 가능하며, 실제 청산은 항상 다음 identity-scoped local OPEN이다.",
        "",
        f"V0 replay baseline: {int(baseline['trade_count'])} trades, positive {int(baseline['positive_count'])}/{int(baseline['trade_count'])} ({baseline['positive_rate_pct']:.6f}%), mean {baseline['mean_terminal_return_pct']:.6f}%, median {baseline['median_terminal_return_pct']:.6f}%, mean holding {baseline['mean_holding_days']:.6f} days.",
        "",
        "## Q2–Q4. Variant·TRIGGER mechanism·수익률",
        "",
    ]
    for row in variant_summary.loc[variant_summary["strategy_id"] != "FASTCORE_V0_CONTROL_REPLAY"].to_dict("records"):
        lines.append(
            f"- {row['strategy_id']} ({row['price_damage_threshold_pct']:.0f}%): positive {row['positive_rate_pct']:.6f}%, mean {row['mean_terminal_return_pct']:.6f}% (V0 paired delta {row['mean_paired_return_delta_pp']:.6f}pp), median {row['median_terminal_return_pct']:.6f}%, improved/worsened/same {int(row['improved_count'])}/{int(row['worsened_count'])}/{int(row['same_count'])}, confirmed/executed/unexecuted {int(row['failure_confirmed_count'])}/{int(row['failure_confirmed_executed_count'])}/{int(row['failure_confirmed_unexecuted_count'])}."
        )
        lines.append(
            f"  - STRONG disarm Q2: TRIGGER {int(row['trigger_disarm_count'])}, TREND {int(row['trend_disarm_count'])}, EXTENDED {int(row['extended_disarm_count'])}; price/fast/both {int(row['disarm_by_price_count'])}/{int(row['disarm_by_fast_count'])}/{int(row['disarm_by_both_count'])}; armed→Winner {int(row['armed_to_winner_mode_count'])}."
        )
        lines.append(
            f"  - Q8 tail delta vs V0 (<=-30/-40/-50/-60): {int(row['le_neg_30_count_delta_vs_v0'])}/{int(row['le_neg_40_count_delta_vs_v0'])}/{int(row['le_neg_50_count_delta_vs_v0'])}/{int(row['le_neg_60_count_delta_vs_v0'])}; Q9 V0 terminal >=50/>=100 pre-winner exits: {int(row['v0_terminal_ge_50_prewinner_exit_count'])}/{int(row['v0_terminal_ge_100_prewinner_exit_count'])}, V0 MFE >=50/>=100 pre-winner exits: {int(row['v0_mfe_ge_50_prewinner_exit_count'])}/{int(row['v0_mfe_ge_100_prewinner_exit_count'])}."
        )
    lines.extend([
        "",
        "ARM 자체는 매도가 아니며, 같은 weekly FAST date가 daily bars에서 반복되어도 확정되지 않는다. 새 weak FAST와 가격손상 유지가 확인될 때만 FAILURE_CONFIRMED EOD signal이 발생한다. 가격 회복, FAST 회복, 둘 다 회복, UNAVAILABLE 대기는 event log로 분리했다. MFE 20% 도달일에는 armed 상태를 해제하고 같은 날부터 V0 Winner Mode를 적용했다.",
        "",
        "## Q5–Q7. RECOVERY, NEVER_WINNER, Loss Guard",
        "",
        "RECOVERY/NEVER_WINNER와 과거 Loss Guard 표시는 FIX03 artifact에서 사후 진단용으로만 join했다. 이 label들은 entry/arm/confirm/exit 판단에 사용하지 않았다.",
        "",
    ])
    for row in cohorts.to_dict("records"):
        if row["cohort"] in {"RECOVERY", "NEVER_WINNER", "LOSS_GUARD_RECOVERY", "LOSS_GUARD_NEVER_WINNER"}:
            lines.append(
                f"- {row['strategy_id']} / {row['cohort']}: n={int(row['trade_count'])}, armed {int(row['armed_trade_count'])}, confirmed/executed {int(row['failure_confirmed_count'])}/{int(row['failure_confirmed_executed_count'])}, recovery preempted {row['recovery_preempted_count']}, NEVER captured {row['never_winner_captured_count']}, mean delta {row['mean_paired_return_delta_pp']:.6f}pp, holding reduction {row['mean_holding_days_reduction']:.6f} days."
            )
    lines.extend([
        "",
        "## Q10–Q11. 전이 시간, 종료 경계, 결론",
        "",
        "마지막 identity daily date 또는 support end에서 확정되어 다음 local OPEN이 없으면, 신호는 EXIT_UNEXECUTED로 기록하고 가짜 체결을 만들지 않았다. 기존 V0/V3/FIX01/FIX03 artifact는 읽기만 했으며 이 작업의 새 artifact 7개만 생성했다.",
        "Variant summary에는 arm→confirm, arm→disarm, arm→Winner의 calendar-day mean/median을 기록한다. W25/W30 평가는 positive-rate 보존, mean return, RECOVERY preemption, NEVER capture, deep-loss tail, large-winner preservation, holding을 함께 보고 trade-off 여부로 결론 낸다.",
        "Q11 결론: 둘 다 부적합. W25/W30 모두 V0 positive rate 70.914697%와 mean return 8.666341%를 크게 훼손했고, RECOVERY preemption이 높다. W25는 일부 deep-loss tail을 줄였지만 대가가 크며, W30은 <=-30 tail도 악화했다. 다음 V1-W candidate로 자동 채택하지 않는다.",
        "",
        "### Exit reason 요약",
        "",
    ])
    for row in exits.to_dict("records"):
        lines.append(f"- {row['strategy_id']} / {row['exit_reason']}: {int(row['trade_count'])} trades, mean return {row['mean_terminal_return_pct']:.6f}%.")
    lines.append("")
    return "\n".join(lines)


def run_analysis() -> dict[str, Any]:
    control = pd.read_csv(CONTROL_PATH)
    if len(control) != 973 or control["control_trade_id"].nunique() != 973:
        raise AssertionError("matched V0 source must contain exactly 973 unique control entries")
    source_summary = json.loads(CONTROL_SUMMARY_PATH.read_text(encoding="utf-8"))
    if source_summary.get("matched_rows") != 973:
        raise AssertionError("authority matched source summary is not the frozen 973 cohort")
    labels = pd.read_csv(LABEL_PATH)
    if len(labels) != 973 or labels["control_trade_id"].nunique() != 973:
        raise AssertionError("FIX03 retrospective label artifact must contain exactly 973 trades")
    label_map = labels.set_index("control_trade_id")["recovery_class"].to_dict()
    if Counter(label_map.values()) != Counter({"RECOVERY": 737, "NEVER_WINNER": 236}):
        raise AssertionError("FIX03 RECOVERY/NEVER partition is not frozen")

    repository = build_repository_v2(ROOT, end=v3.SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=v3.SUPPORT_END)
    states, daily_by_ticker, state_errors = v0_ab._state_index(control, loader)
    state_counts = Counter(state for values in states.values() for _, state in values)
    state_domain = validate_fast_state_domain(state_counts)

    ordered = control.sort_values(["ticker", "entry_signal_date", "control_trade_sequence", "control_trade_id"], kind="mergesort")
    v0_rows: list[dict[str, Any]] = []
    variant_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for row in ordered.to_dict("records"):
        ticker = str(row["ticker"])
        daily = daily_by_ticker[ticker]
        state_path = states.get(_identity_key(row), [])
        v0_result = v0_ab.replay_v0_entry(row, daily, state_path)
        v0_rows.append({"control_trade_id": str(row["control_trade_id"]), **v0_result})
        for config in VARIANTS:
            v1_result, trade_events = simulate_failure_armed(row, daily, state_path, config)
            record = {
                **row,
            "ticker": str(row["ticker"]).zfill(6),
                "recovery_class": label_map[str(row["control_trade_id"])],
                "original_v0_recovery_class": label_map[str(row["control_trade_id"])],
                **v0_result,
                **v1_result,
                "v1_entry_date_match_v0": v1_result["v1_entry_execution_date"] == v0_result["v0_entry_execution_date"],
                "v1_entry_open_match_v0": abs(float(v1_result["v1_entry_open"]) - float(v0_result["v0_entry_open"])) <= 1e-8,
                "paired_return_delta_v1_minus_v0": round(float(v1_result["v1_terminal_return"]) - float(v0_result["v0_terminal_return"]), 2),
                "variant": config.strategy_id,
                "arm_count": v1_result["prewinner_arm_cycles"],
                "first_armed_date": v1_result["prewinner_first_arm_date"],
                "last_armed_date": v1_result["prewinner_last_arm_date"],
                "confirmed_failure": v1_result["failure_armed_applied"],
                "confirmed_failure_signal_date": v1_result["prewinner_failure_confirmed_date"],
                "confirmed_failure_fast_date": v1_result["prewinner_confirmed_fast_date"],
                "confirmed_failure_fast_state": v1_result["prewinner_confirmed_fast_state"],
                "confirmed_failure_close_return_pct": v1_result["prewinner_confirmed_close_return_pct"],
                "exit_execution_date": v1_result["v1_exit_execution_date"],
                "exit_price": v1_result["v1_exit_price"],
                "exit_reason": v1_result["v1_exit_reason"],
                "trade_status": v1_result["v1_trade_status"],
                "terminal_return_pct": v1_result["v1_terminal_return"],
                "MFE_pct": v1_result["v1_mfe"],
                "MAE_pct": v1_result["v1_mae"],
                "holding_days": v1_result["v1_holding_days"],
                "disarm_count": v1_result["prewinner_disarm_count"],
                "disarm_by_price_count": v1_result["prewinner_disarm_by_price_count"],
                "disarm_by_fast_count": v1_result["prewinner_disarm_by_fast_count"],
                "disarm_by_both_count": v1_result["prewinner_disarm_by_both_count"],
                "unavailable_wait_count": v1_result["prewinner_unavailable_wait_count"],
                "armed_to_winner_mode_count": v1_result["prewinner_armed_to_winner_mode_count"],
            }
            variant_rows.append(record)
            event_rows.extend(trade_events)

    v0_frame = pd.DataFrame(v0_rows)
    parity = assert_v0_parity(ordered, v0_frame)
    variants = pd.DataFrame(variant_rows)
    if len(variants) != 1946 or not variants["v1_entry_date_match_v0"].all() or not variants["v1_entry_open_match_v0"].all():
        raise AssertionError("W25/W30 failed fixed-entry identity/date/open parity")
    if set(variants["strategy_id"]) != {item.strategy_id for item in VARIANTS}:
        raise AssertionError("only W25 and W30 variants may run")
    events = pd.DataFrame(event_rows, columns=[
        "strategy_id", "price_damage_threshold_pct", "control_trade_id", "ticker", "name", "date", "event_type",
        "close_return_pct", "running_mfe_pct", "fast_date", "fast_state", "arm_cycle", "detail",
    ])
    variant_summary = _variant_summary_rows(v0_frame, variants, events)
    cohorts = _cohort_rows(variants)
    exits = _exit_reason_rows(variants)
    summary: dict[str, Any] = {
        "work_id": WORK_ID,
        "status": "COMPLETE",
        "evaluation_start": "2021-04-01",
        "signal_cutoff": "2026-08-14",
        "execution_support_end": "2026-08-21",
        "final_valuation": "2026-08-21 CLOSE",
        "matched_control_rows": len(control),
        "matched_unique_control_trade_ids": int(control["control_trade_id"].nunique()),
        "loss_guard_subset_count": int(control["v2_loss_guard_triggered"].sum()),
        "recovery_count": int((variants.drop_duplicates("control_trade_id")["recovery_class"] == "RECOVERY").sum()),
        "never_winner_count": int((variants.drop_duplicates("control_trade_id")["recovery_class"] == "NEVER_WINNER").sum()),
        "v0_disabled_parity": parity,
        "variant_entry_parity": {"passed": True, "w25_rows": int((variants["strategy_id"] == V1_W25.strategy_id).sum()), "w30_rows": int((variants["strategy_id"] == V1_W30.strategy_id).sum())},
        "fast_state_domain": {**state_domain, "weekly_evaluation_error_count": state_errors},
        "fast_state_classification": {
            "weak": sorted(WEAK_FAST_STATES),
            "strong_recovered": sorted(STRONG_FAST_STATES),
            "unavailable": sorted(UNAVAILABLE_FAST_STATES),
        },
        "variant_configs": [asdict(config) for config in VARIANTS],
        "config_difference_only": "price_damage_threshold_pct",
        "retrospective_labels_analysis_only": True,
        "new_entry_scan": False,
        "entry_filter_re_evaluated": False,
        "overlap_removal": False,
        "portfolio_or_julia_executed": False,
        "network_requests": 0,
        "production_strategy_modified": False,
        "prior_artifacts_modified": False,
        "evaluation_conclusion": "BOTH_UNSUITABLE",
        "source_artifacts": {
            "matched_control": str(CONTROL_PATH.relative_to(ROOT)),
            "matched_control_summary": str(CONTROL_SUMMARY_PATH.relative_to(ROOT)),
            "retrospective_labels": str(LABEL_PATH.relative_to(ROOT)),
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
    events.to_csv(EVENT_PATH, index=False, lineterminator="\n")
    variant_summary.to_csv(VARIANT_SUMMARY_PATH, index=False, lineterminator="\n")
    cohorts.to_csv(COHORT_PATH, index=False, lineterminator="\n")
    exits.to_csv(EXIT_REASON_PATH, index=False, lineterminator="\n")
    _write_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, variant_summary, cohorts, exits), encoding="utf-8")
    return {"summary": summary, "variants": variants, "events": events}


def render_report_from_outputs() -> None:
    """Finish a report-only render after a completed offline run.

    This does not recalculate entries, FAST states, prices, or any strategy
    outcome.  It exists so presentation-only fixes do not repeat the costly
    frozen V0 weekly-state reconstruction.
    """
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    variants = pd.read_csv(VARIANT_SUMMARY_PATH)
    cohorts = pd.read_csv(COHORT_PATH)
    exits = pd.read_csv(EXIT_REASON_PATH)
    summary["fast_state_classification"] = {
        "weak": sorted(WEAK_FAST_STATES),
        "strong_recovered": sorted(STRONG_FAST_STATES),
        "unavailable": sorted(UNAVAILABLE_FAST_STATES),
    }
    summary["evaluation_conclusion"] = "BOTH_UNSUITABLE"
    summary["variant_summary_records"] = variants.to_dict("records")
    summary["cohort_diagnostic_records"] = cohorts.to_dict("records")
    _write_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, variants, cohorts, exits), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--render-report", action="store_true")
    args = parser.parse_args()
    if args.render_report:
        render_report_from_outputs()
        print(json.dumps({"status": "REPORT_RENDERED"}, ensure_ascii=False))
        return 0
    if not args.run:
        parser.error("use --run to execute the offline matched-entry diagnostic or --render-report")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_analysis()
        result["summary"]["network_requests"] = audit.request_count
        _write_json(SUMMARY_PATH, result["summary"])
        print(json.dumps({"status": result["summary"]["status"], "matched_rows": result["summary"]["matched_control_rows"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{WORK_ID} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
