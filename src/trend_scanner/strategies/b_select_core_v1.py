"""Current-state rules for the adopted B Select Core V1 strategy.

This module contains only the frozen signal/lifecycle rules.  It does not
calculate Pattern A or Pattern B, run a portfolio simulation, or fetch data.
Callers provide completed observations and exact KRX sessions/prices.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from typing import Any


STRATEGY_ID = "PATTERN_B_SELECT_CORE_V01"
STRATEGY_NAME = "B Select Core V1"
ALLOWED_PREVIOUS_STAGES = frozenset({"EARLY_TREND", "TRANSITION"})


class BSelectLifecycleError(ValueError):
    """An exact lifecycle input is missing, inconsistent, or future-dated."""


def is_entry_signal(
    pattern_b_state: str | None,
    pattern_a_stage: str | None,
    previous_pattern_a_stage: str | None,
) -> bool:
    """Return whether the official three-part entry rule is satisfied."""
    return (
        pattern_b_state == "DEPRESSED"
        and pattern_a_stage == "PROGRESSED"
        and previous_pattern_a_stage in ALLOWED_PREVIOUS_STAGES
    )


def is_exit_signal(*, is_open: bool, pattern_b_state: str | None) -> bool:
    """Only NORMAL exits an open position; DEEP_DEPRESSED is not a stop."""
    return is_open and pattern_b_state == "NORMAL"


def next_exact_session(signal_date: str, trading_dates: Sequence[str]) -> str | None:
    """Return the immediate next authorized KRX session, without price fallback."""
    days = [str(day)[:10] for day in trading_dates]
    position = bisect_right(days, str(signal_date)[:10])
    return days[position] if position < len(days) else None


def resolve_progressed_episode(
    active_dates: Sequence[str],
    stage_by_date: Mapping[str, str],
    entry_date: str,
    snapshot_positions: Mapping[str, int],
    trading_positions: Mapping[str, int],
) -> dict[str, Any]:
    """Resolve the contiguous PROGRESSED run and its previous authority stage.

    This is the shared resolver used by the prior Pattern B stage study and the
    production current-status evaluator. UNAVAILABLE observations and gaps in
    the active PIT identity chain break the run.
    """
    dates = [str(day)[:10] for day in active_dates]
    date = str(entry_date)[:10]
    try:
        index = dates.index(date)
    except ValueError as exc:
        raise ValueError(f"entry date is not an active Pattern A snapshot: {date}") from exc
    if stage_by_date.get(date) != "PROGRESSED":
        raise ValueError(f"entry-date Pattern A stage is not PROGRESSED: {date}")
    if date not in trading_positions:
        raise ValueError(f"entry date is not an exchange session: {date}")

    run_index = index
    previous_stage = "UNAVAILABLE"
    previous_date = None
    boundary_reason = "NO_PRIOR_DISTINCT_STAGE"
    while run_index > 0:
        prior_date = dates[run_index - 1]
        current_date = dates[run_index]
        if snapshot_positions[current_date] != snapshot_positions[prior_date] + 1:
            previous_stage = "UNAVAILABLE"
            previous_date = prior_date
            boundary_reason = "PIT_IDENTITY_ACTIVE_GAP"
            break
        prior_stage = stage_by_date[prior_date]
        if prior_stage != "PROGRESSED":
            previous_stage = prior_stage
            previous_date = prior_date
            boundary_reason = "PREVIOUS_DIFFERENT_OBSERVATION"
            break
        run_index -= 1

    start_date = dates[run_index]
    if start_date not in trading_positions:
        raise ValueError(f"progressed segment start is not an exchange session: {start_date}")
    elapsed = trading_positions[date] - trading_positions[start_date]
    if elapsed < 0:
        raise ValueError(f"negative PROGRESSED duration: {start_date} -> {date}")
    return {
        "previous_pattern_a_stage": previous_stage,
        "previous_pattern_a_stage_date": previous_date,
        "progressed_segment_start_date": start_date,
        "progressed_segment_krx_sessions": int(elapsed),
        "progressed_segment_month_observation_count": int(index - run_index + 1),
        "episode_boundary_reason": boundary_reason,
    }


def replay_lifecycle(
    observations: Sequence[Mapping[str, Any]],
    entry_signals: Sequence[Mapping[str, Any]],
    *,
    trading_dates: Sequence[str],
    exact_opens: Mapping[str, float],
    reference_market_date: str,
    initial_position: Mapping[str, Any] | None = None,
    initial_pending: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay one identity's completed Pattern B observations through reference.

    ``entry_signals`` contains only authoritative, stage-qualified historical
    candidate signals.  Each entry and exit is filled on the immediate next
    session only.  When the next session is after the reference date, the event
    remains pending and its future open is never read.
    """
    reference = str(reference_market_date)[:10]
    calendar = sorted({str(day)[:10] for day in trading_dates})
    if any(str(row.get("date", ""))[:10] > reference for row in observations):
        raise BSelectLifecycleError("FUTURE_OBSERVATION")
    by_date: dict[str, Mapping[str, Any]] = {}
    for row in observations:
        day = str(row.get("date", ""))[:10]
        if not day or day in by_date:
            raise BSelectLifecycleError("INVALID_OR_DUPLICATE_OBSERVATION_DATE")
        by_date[day] = row
    signal_by_date: dict[str, Mapping[str, Any]] = {}
    for row in entry_signals:
        day = str(row.get("date", ""))[:10]
        if not day or day in signal_by_date:
            raise BSelectLifecycleError("INVALID_OR_DUPLICATE_ENTRY_SIGNAL_DATE")
        if day not in by_date or by_date[day].get("state") != "DEPRESSED":
            raise BSelectLifecycleError("ENTRY_SIGNAL_NOT_BACKED_BY_DEPRESSED_OBSERVATION")
        if not is_entry_signal(
            "DEPRESSED",
            str(row.get("pattern_a_stage") or ""),
            str(row.get("previous_pattern_a_stage") or ""),
        ):
            raise BSelectLifecycleError("ENTRY_SIGNAL_STAGE_AUTHORITY_MISMATCH")
        signal_by_date[day] = row

    event_days = sorted(set(by_date) | set(signal_by_date))
    position: dict[str, Any] | None = dict(initial_position) if initial_position else None
    pending: dict[str, Any] | None = dict(initial_pending) if initial_pending else None
    suppressed_entry_count = 0
    sequence = max(
        int(position.get("trade_sequence") or 0) if position else 0,
        int(pending.get("sequence") or 0) if pending else 0,
    )

    def fill_pending(day: str) -> None:
        nonlocal position, pending
        if pending is None or pending.get("execution_date") != day:
            return
        if day > reference:
            return
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
            }
        else:
            position = None
        pending = None

    for day in event_days:
        # An exact next-session fill happens before any later completed state
        # observation, matching the adopted next-open lifecycle.
        fill_pending(day)
        observation = by_date.get(day)
        if observation is None:
            continue
        state = observation.get("state")
        if position is not None:
            if day in signal_by_date:
                suppressed_entry_count += 1
            if pending is None and is_exit_signal(is_open=True, pattern_b_state=state):
                execution = next_exact_session(day, calendar)
                position["exit_signal_date"] = day
                position["exit_execution_date"] = execution
                if execution is None:
                    pending = {"kind": "EXIT", "signal_date": day, "execution_date": None}
                else:
                    pending = {"kind": "EXIT", "signal_date": day, "execution_date": execution}
                    if execution <= reference:
                        fill_pending(execution)
            continue
        if pending is not None:
            # A pending entry can only be canceled by an observed state reversion
            # before its exact execution session.
            if pending["kind"] == "ENTRY" and pending.get("execution_date") and pending["execution_date"] > day and state != "DEPRESSED":
                pending = None
            continue
        signal = signal_by_date.get(day)
        if signal is None:
            continue
        sequence += 1
        execution = next_exact_session(day, calendar)
        if execution is None:
            pending = {
                "kind": "ENTRY",
                "signal_date": day,
                "execution_date": None,
                "sequence": sequence,
            }
        elif execution > reference:
            pending = {
                "kind": "ENTRY",
                "signal_date": day,
                "execution_date": execution,
                "sequence": sequence,
            }
        else:
            pending = {
                "kind": "ENTRY",
                "signal_date": day,
                "execution_date": execution,
                "sequence": sequence,
            }
            if execution <= reference:
                fill_pending(execution)
    # A next-session event after reference stays pending.  Do not inspect its
    # price, even when requested_as_of is later than reference_market_date.
    if pending and pending.get("execution_date") and pending["execution_date"] <= reference:
        fill_pending(str(pending["execution_date"]))
    return {
        "position": position,
        "pending": pending,
        "suppressed_entry_count": suppressed_entry_count,
        "last_observation_date": max(by_date) if by_date else None,
        "last_pattern_b_state": by_date[max(by_date)].get("state") if by_date else None,
    }


__all__ = [
    "ALLOWED_PREVIOUS_STAGES",
    "BSelectLifecycleError",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "is_entry_signal",
    "is_exit_signal",
    "next_exact_session",
    "resolve_progressed_episode",
    "replay_lifecycle",
]
