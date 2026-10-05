"""Current-state rules for the adopted B Select Core V2 strategy.

V2 inherits V1's exact month-end entry qualification and changes only exit
observation cadence: an open position exits on any exact KRX session observed
as Pattern B NORMAL, filled at the next exact session's valid open.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trend_scanner.strategies.b_select_core_v1 import (
    ALLOWED_PREVIOUS_STAGES,
    exact_month_end_sessions,
    is_entry_signal,
    next_exact_session,
    resolve_progressed_episode,
)


STRATEGY_ID = "PATTERN_B_SELECT_CORE_V02"
STRATEGY_NAME = "B Select Core V2"
V1_STRATEGY_ID = "PATTERN_B_SELECT_CORE_V01"


class BSelectLifecycleError(ValueError):
    """An exact lifecycle input is missing, inconsistent, or future-dated."""


def is_exit_signal(*, is_open: bool, pattern_b_state: str | None) -> bool:
    """Return whether an open position has the V2 daily NORMAL exit signal."""
    return is_open and pattern_b_state == "NORMAL"


def replay_lifecycle(
    observations: Sequence[Mapping[str, Any]],
    entry_signals: Sequence[Mapping[str, Any]],
    *,
    trading_dates: Sequence[str],
    exact_opens: Mapping[str, float],
    reference_market_date: str,
    initial_position: Mapping[str, Any] | None = None,
    initial_pending: Mapping[str, Any] | None = None,
    initial_trade_sequence: int = 0,
    execution_by_signal_date: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Replay one identity's exact-session lifecycle through the reference.

    Entry signals remain month-end-only and stage-qualified. A position that
    is open at an eligible observation exits on the first NORMAL observation;
    fills use the first exact KRX session after a signal with a valid supplied
    open. When ``execution_by_signal_date`` is present, it is the authoritative
    first-valid-open schedule built from the bounded Repository V2 price frame.
    ``strategy_id`` on a position records the entry lineage. The pending exit
    records the strategy that generated that exit signal.
    """
    reference = str(reference_market_date)[:10]
    calendar = sorted({str(day)[:10] for day in trading_dates})
    calendar_set = set(calendar)
    month_end_sessions = exact_month_end_sessions(calendar)
    if reference not in calendar_set:
        raise BSelectLifecycleError("REFERENCE_NOT_EXACT_KRX_SESSION")
    if any(str(row.get("date", ""))[:10] > reference for row in observations):
        raise BSelectLifecycleError("FUTURE_OBSERVATION")

    by_date: dict[str, Mapping[str, Any]] = {}
    for row in observations:
        day = str(row.get("date", ""))[:10]
        if not day or day not in calendar_set or day in by_date:
            raise BSelectLifecycleError("INVALID_OR_DUPLICATE_OBSERVATION_DATE")
        by_date[day] = row

    signal_by_date: dict[str, Mapping[str, Any]] = {}
    for row in entry_signals:
        day = str(row.get("date", ""))[:10]
        if not day or day in signal_by_date:
            raise BSelectLifecycleError("INVALID_OR_DUPLICATE_ENTRY_SIGNAL_DATE")
        if day not in month_end_sessions:
            raise BSelectLifecycleError("ENTRY_SIGNAL_NOT_MONTH_END_EXACT_KRX_SESSION")
        if day not in by_date or by_date[day].get("state") != "DEPRESSED":
            raise BSelectLifecycleError("ENTRY_SIGNAL_NOT_BACKED_BY_DEPRESSED_OBSERVATION")
        if not is_entry_signal(
            "DEPRESSED",
            str(row.get("pattern_a_stage") or ""),
            str(row.get("previous_pattern_a_stage") or ""),
        ):
            raise BSelectLifecycleError("ENTRY_SIGNAL_STAGE_AUTHORITY_MISMATCH")
        signal_by_date[day] = row

    position = dict(initial_position) if initial_position else None
    pending = dict(initial_pending) if initial_pending else None
    if pending is not None:
        pending_day = str(pending.get("signal_date") or "")[:10]
        pending_kind = str(pending.get("kind") or "")
        pending_execution = str(pending.get("execution_date") or "")[:10]
        if pending_day not in calendar_set:
            raise BSelectLifecycleError("PENDING_SIGNAL_NOT_EXACT_KRX_SESSION")
        if pending_kind == "ENTRY" and pending_day not in month_end_sessions:
            raise BSelectLifecycleError("PENDING_ENTRY_SIGNAL_NOT_MONTH_END_EXACT_KRX_SESSION")
        if pending_kind not in {"ENTRY", "EXIT"}:
            raise BSelectLifecycleError("PENDING_EVENT_KIND_INVALID")
        if pending_execution and (
            pending_execution not in calendar_set
            or pending_execution <= pending_day
        ):
            raise BSelectLifecycleError("PENDING_EXECUTION_NOT_FIRST_VALID_EXACT_KRX_SESSION")

    completed_trades: list[dict[str, Any]] = []
    suppressed_entry_count = 0
    sequence = max(
        int(initial_trade_sequence or 0),
        int(position.get("trade_sequence") or 0) if position else 0,
        int(pending.get("sequence") or 0) if pending else 0,
    )

    def execution_after(signal_day: str) -> str | None:
        scheduled = (execution_by_signal_date or {}).get(signal_day)
        if scheduled:
            scheduled = str(scheduled)[:10]
            if scheduled not in calendar_set or scheduled <= signal_day:
                raise BSelectLifecycleError("EXECUTION_SCHEDULE_NOT_AFTER_SIGNAL")
            if scheduled <= reference:
                price = exact_opens.get(scheduled)
                if price is None or float(price) <= 0:
                    raise BSelectLifecycleError(f"MISSING_EXACT_SCHEDULED_OPEN:{scheduled}")
            return scheduled
        return next_exact_session(signal_day, calendar)

    def fill_pending(day: str) -> None:
        nonlocal position, pending
        if pending is None or pending.get("execution_date") != day:
            return
        if day > reference:
            return
        if day not in calendar_set:
            raise BSelectLifecycleError(f"EXECUTION_NOT_EXACT_KRX_SESSION:{day}")
        price = exact_opens.get(day)
        if price is None or float(price) <= 0:
            raise BSelectLifecycleError(f"MISSING_EXACT_NEXT_OPEN:{day}")
        if pending["kind"] == "ENTRY":
            sequence_number = pending["sequence"]
            position = {
                "trade_sequence": sequence_number,
                "entry_signal_date": pending["signal_date"],
                "entry_execution_date": day,
                "entry_open": float(price),
                "exit_signal_date": None,
                "exit_execution_date": None,
                "strategy_id": pending.get("strategy_id") or STRATEGY_ID,
            }
        else:
            if position is not None:
                exit_price = float(price)
                entry_price = float(position["entry_open"])
                completed_trade = {
                    "trade_sequence": position.get("trade_sequence"),
                    "entry_signal_date": position.get("entry_signal_date"),
                    "entry_execution_date": position.get("entry_execution_date"),
                    "entry_open": entry_price,
                    "exit_signal_date": pending.get("signal_date") or position.get("exit_signal_date"),
                    "exit_execution_date": day,
                    "exit_price": exit_price,
                    "exit_reason": "PATTERN_B_NORMAL_NEXT_OPEN",
                    "trade_status": "REALIZED",
                    "return_pct": (exit_price / entry_price - 1.0) * 100.0,
                    "strategy_id": position.get("strategy_id") or STRATEGY_ID,
                    "exit_strategy_id": pending.get("strategy_id") or STRATEGY_ID,
                }
                for quantity_key in ("quantity", "shares", "entry_quantity"):
                    if position.get(quantity_key) is not None:
                        completed_trade[quantity_key] = position[quantity_key]
                completed_trades.append(completed_trade)
            position = None
        pending = None

    event_days = set(by_date) | set(signal_by_date)
    if pending and pending.get("execution_date") and str(pending["execution_date"])[:10] <= reference:
        event_days.add(str(pending["execution_date"])[:10])
    for day in sorted(event_days):
        fill_pending(day)
        observation = by_date.get(day)
        if observation is None:
            continue
        state = observation.get("state")
        if position is not None:
            if day in signal_by_date:
                suppressed_entry_count += 1
            # A migration baseline can be retained as context while explicitly
            # disallowing retroactive V2 exit evaluation on that date.
            eligible = observation.get("exit_signal_eligible") is not False
            if (
                pending is None
                and eligible
                and is_exit_signal(is_open=True, pattern_b_state=state)
            ):
                execution = execution_after(day)
                position["exit_signal_date"] = day
                position["exit_execution_date"] = execution
                pending = {
                    "kind": "EXIT",
                    "signal_date": day,
                    "execution_date": execution,
                    "strategy_id": STRATEGY_ID,
                }
                if execution is not None and execution <= reference:
                    fill_pending(execution)
            continue
        if pending is not None:
            if (
                pending["kind"] == "ENTRY"
                and pending.get("execution_date")
                and str(pending["execution_date"])[:10] > day
                and state != "DEPRESSED"
            ):
                pending = None
            continue
        signal = signal_by_date.get(day)
        if signal is None:
            continue
        sequence += 1
        execution = execution_after(day)
        pending = {
            "kind": "ENTRY",
            "signal_date": day,
            "execution_date": execution,
            "sequence": sequence,
            "strategy_id": STRATEGY_ID,
        }
        if execution is not None and execution <= reference:
            fill_pending(execution)

    if pending and pending.get("execution_date") and str(pending["execution_date"])[:10] <= reference:
        fill_pending(str(pending["execution_date"])[:10])
    last_day = max(by_date) if by_date else None
    return {
        "position": position,
        "pending": pending,
        "completed_trades": completed_trades,
        "suppressed_entry_count": suppressed_entry_count,
        "last_observation_date": last_day,
        "last_pattern_b_state": by_date[last_day].get("state") if last_day else None,
    }


__all__ = [
    "ALLOWED_PREVIOUS_STAGES",
    "BSelectLifecycleError",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "V1_STRATEGY_ID",
    "is_entry_signal",
    "is_exit_signal",
    "exact_month_end_sessions",
    "next_exact_session",
    "resolve_progressed_episode",
    "replay_lifecycle",
]
