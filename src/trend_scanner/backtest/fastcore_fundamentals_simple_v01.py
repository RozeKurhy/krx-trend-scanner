"""FastCore V2 corrected simple backtest engine with an optional PIT Fundamentals gate.

The strategy mechanics are copied from the corrected reference implementation:
historical identity lifecycle clipping, identity-scoped investability, completed
weekly/monthly snapshots, next-open execution, loss guard, Exit 3/4, and re-entry.
This module does not modify the frozen production FastCore implementation. The
only optional behavior is an entry-time callback used by the Fundamentals variant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from trend_scanner.backtest.raw_investability_panel import evaluate_entry_filter
from trend_scanner.backtest.snapshot_context import (
    PrecomputedTickerContext,
    build_historical_snapshot_from_context,
    build_precomputed_ticker_context,
)
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

MARKET_CAP_THRESHOLD = 300_000_000_000.0
AVG_TRADING_VALUE_20D_THRESHOLD = 300_000_000.0
CLOSE_THRESHOLD = 5_000.0

LOSS_GUARD_THRESHOLD = -0.15
EXIT4_DRAWDOWN_POINTS = 15.0


@dataclass(frozen=True)
class IdentityLifecycle:
    """One non-overlapping COMMON lifecycle segment for one KRX identity."""

    ticker: str
    isu_cd: str
    market: str
    effective_from: pd.Timestamp
    effective_to: pd.Timestamp

    def contains(self, value: pd.Timestamp | str) -> bool:
        try:
            day = pd.Timestamp(value).normalize()
        except (TypeError, ValueError, OverflowError):
            return False
        return self.effective_from <= day <= self.effective_to


def clip_to_identity_lifecycle(
    frame: pd.DataFrame | None,
    lifecycle: IdentityLifecycle,
) -> pd.DataFrame | None:
    """Clip a daily/raw frame to one identity segment, fail-closed on bad data."""
    if frame is None:
        return None
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(result.index, errors="coerce")).normalize()
    if dates.isna().any():
        return result.iloc[0:0].copy()
    result.index = dates
    return result.loc[(dates >= lifecycle.effective_from) & (dates <= lifecycle.effective_to)].copy()


def pit_common_for_identity(
    intervals: Mapping[tuple[str, str, str], Sequence[tuple[str, str]]],
    ticker: str,
    isu_cd: str | None,
    market: str,
    value: pd.Timestamp | str,
) -> bool:
    """Exact date membership; ticker-only or nearest-date fallback is forbidden."""
    if not isu_cd:
        return False
    try:
        day = pd.Timestamp(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return False
    matches = [
        str(start) <= day <= str(end)
        for start, end in intervals.get((str(ticker), str(isu_cd), str(market)), ())
    ]
    # Overlapping lifecycle segments are ambiguous even when the key matches;
    # callers must fail closed rather than choose whichever interval appears
    # first in the authority payload.
    return sum(matches) == 1


@dataclass
class StrategyTradeRecord:
    strategy_id: str
    ticker: str
    isu_cd: str | None
    name: str
    market: str
    trade_id: str
    trade_sequence: int

    entry_signal_date: str
    entry_execution_date: str
    entry_open: float

    entry_market_cap: float | None
    entry_avg_trading_value_20d: float | None
    entry_signal_close: float | None
    entry_market_cap_pass: bool
    entry_trading_value_pass: bool
    entry_close_pass: bool

    entry_pattern_a_stage: str
    fast_stage: str
    fast_status: str
    monthly_permission_state: str
    daily_risk: str
    fast_score: float | None
    fast_score_state: str

    first_progressed_date: str | None
    first_progressed_effective_trading_date: str | None
    lifecycle_class: str

    loss_guard_triggered: bool
    loss_guard_signal_date: str | None
    loss_guard_signal_close: float | None
    loss_guard_return_at_signal: float | None
    loss_guard_execution_date: str | None
    loss_guard_execution_price: float | None
    loss_guard_realized_return: float | None

    exit_type: str
    exit_signal_date: str | None
    exit_execution_date: str | None
    exit_price: float | None

    terminal_return: float
    mfe: float
    mae: float
    peak_giveback: float
    holding_trading_days: int
    holding_weeks: float
    trade_status: str

    cutoff_date: str | None = None
    cutoff_valuation_price: float | None = None
    mark_to_cutoff_return: float | None = None

    # Phase 2 PIT/date-semantics metadata.  Kept optional for compatibility
    # with existing callers that construct/read the V01 record directly.
    entry_signal_information_date: str | None = None
    entry_filter_raw_date: str | None = None
    identity_effective_from: str | None = None
    identity_effective_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_ticker_strategy_fundamentals_v01(
    *,
    strategy_id: str,
    ticker: str,
    isu_cd: str | None,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    raw_panel: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    loss_guard_enabled: bool,
    backtest_end: pd.Timestamp,
    entry_eligible_from: pd.Timestamp | None = None,
    allowed_signal_dates: set[pd.Timestamp] | frozenset[pd.Timestamp] | None = None,
    snapshot_context: PrecomputedTickerContext | None = None,
    identity_lifecycle: IdentityLifecycle | None = None,
    pit_membership: Callable[[str, str | None, str, pd.Timestamp], bool] | None = None,
    entry_gate: Callable[[pd.Timestamp, dict[str, Any]], Mapping[str, Any] | None] | None = None,
) -> list[StrategyTradeRecord]:
    """Run one corrected FastCore variant for one ticker through
    ``backtest_end``. ``loss_guard_enabled`` is retained as an explicit
    strategy parameter for the frozen FastCore mechanics. PIT-safe: every
    entry/exit decision at date ``t`` only reads ``daily``/``raw_panel``
    rows with index ``<= t``.
    """
    if daily is None or daily.empty:
        return []

    daily = daily.sort_index()
    if identity_lifecycle is not None:
        if (
            str(ticker) != identity_lifecycle.ticker
            or str(isu_cd or "") != identity_lifecycle.isu_cd
            or str(market) != identity_lifecycle.market
        ):
            return []
        daily = clip_to_identity_lifecycle(daily, identity_lifecycle)
        raw_panel = clip_to_identity_lifecycle(raw_panel, identity_lifecycle)
    daily = daily[daily.index <= backtest_end]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns) or len(daily) < 60:
        return []

    if snapshot_context is None or not snapshot_context.daily.index.equals(daily.index):
        # A context built from a broader ticker history would reintroduce a
        # reused-ticker lifecycle leak even when ``daily`` itself is clipped.
        snapshot_context = build_precomputed_ticker_context(ticker, name, daily)
    weekly_bars = snapshot_context.weekly_up_to(backtest_end)
    daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
    valid_weeks = [
        w for w in weekly_bars.index
        if pd.Timestamp(w).normalize() in daily_dates
    ]
    monthly_bars = snapshot_context.monthly_up_to(backtest_end)

    if not valid_weeks:
        return []

    def _pit_ok(value: pd.Timestamp | str) -> bool:
        if pit_membership is not None:
            return bool(pit_membership(ticker, isu_cd, market, pd.Timestamp(value).normalize()))
        if identity_lifecycle is not None:
            return identity_lifecycle.contains(value)
        return True

    trades: list[StrategyTradeRecord] = []
    trade_seq = 0
    allowed_signals = None
    if allowed_signal_dates is not None:
        allowed_signals = {pd.Timestamp(value).normalize() for value in allowed_signal_dates}
    eligible_from = None
    if entry_eligible_from is not None:
        eligible_from = pd.Timestamp(entry_eligible_from).normalize()
    # Keep the complete historical ``daily`` frame above for indicator and
    # Pattern A lookback, but begin the trade search at the common boundary so
    # no pre-boundary position can be carried into the CONTROL run.
    cur_search_date: pd.Timestamp | None = next(
        (week for week in valid_weeks if eligible_from is None or week >= eligible_from),
        None,
    )
    monthly_snapshot_cache: dict[pd.Timestamp, dict[str, Any]] = {}

    while cur_search_date is not None and cur_search_date <= backtest_end:
        found_signal_w: pd.Timestamp | None = None
        found_signal_res: dict | None = None
        found_filter: dict[str, Any] | None = None

        candidate_weeks = [
            w for w in valid_weeks
            if w >= cur_search_date and (allowed_signals is None or w.normalize() in allowed_signals)
        ]
        for w in candidate_weeks:
            try:
                res = evaluate_pattern_a_fast(
                    ticker, name, daily, w, score_contract, stage_contract, context=snapshot_context,
                )
                is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
                is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
                is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
                is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
                is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)

                raw_stage = res.get("pattern_a_stage")
                pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

                if not (is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"}):
                    continue

                # Entry-only investability filter -- evaluated fresh at this
                # candidate signal date. A week that fails the filter is
                # simply not a valid entry; the search continues to later
                # weeks (this is never treated as an exit trigger).
                info_pos = daily.index.searchsorted(w, side="right") - 1
                entry_signal_information_date = daily.index[info_pos] if info_pos >= 0 else None
                if entry_signal_information_date is None or not _pit_ok(entry_signal_information_date):
                    continue
                filt = evaluate_entry_filter(
                    raw_panel, w,
                    market_cap_threshold=MARKET_CAP_THRESHOLD,
                    avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
                    close_threshold=CLOSE_THRESHOLD,
                )
                if not filt["entry_filter_pass"]:
                    continue

                entry_filter_raw_date = filt.get("entry_filter_raw_date")
                if (
                    entry_filter_raw_date is None
                    or pd.Timestamp(entry_filter_raw_date) > pd.Timestamp(entry_signal_information_date)
                    or not _pit_ok(entry_filter_raw_date)
                ):
                    continue

                entry_pos = daily.index.searchsorted(w, side="right")
                fut_daily = daily.iloc[entry_pos:]
                if fut_daily.empty:
                    continue
                entry_exec_candidate = fut_daily.index[0]
                if not _pit_ok(entry_exec_candidate):
                    continue

                candidate_as_of = pd.Timestamp(entry_signal_information_date).normalize()
                gate_result = None
                if entry_gate is not None:
                    gate_result = entry_gate(
                        candidate_as_of,
                        {
                            **res,
                            **filt,
                            "signal_date": pd.Timestamp(w).normalize(),
                            "signal_information_date": candidate_as_of,
                        },
                    )
                    if not gate_result or not bool(gate_result.get("gate_pass", False)):
                        continue
                    filt["entry_gate_result"] = gate_result
                found_signal_w = w
                found_signal_res = res
                found_filter = filt
                found_filter["entry_signal_information_date"] = candidate_as_of.strftime("%Y-%m-%d")
                break
            except Exception:
                continue

        if found_signal_w is None or found_signal_res is None or found_filter is None:
            break

        entry_pos = daily.index.searchsorted(found_signal_w, side="right")
        fut_daily = daily.iloc[entry_pos:]
        if fut_daily.empty:
            break

        entry_exec_date = fut_daily.index[0]
        entry_open_price = float(fut_daily.iloc[0]["open"])
        if not _pit_ok(entry_exec_date):
            # This is defensive because the candidate loop already checked it;
            # never create an entry outside its exact identity lifecycle.
            cur_search_date = entry_exec_date
            continue

        trade_seq += 1
        identity_token = str(isu_cd or "UNKNOWN")
        trade_id = f"{strategy_id}_{ticker}_{identity_token}_{market}_{trade_seq:02d}"

        pa_stage_at_entry = (found_signal_res["pattern_a_stage"] or "").upper()
        fast_score = found_signal_res.get("fast_score")
        fast_score_avail = found_signal_res.get("fast_score_status", "UNKNOWN")
        daily_risk = found_signal_res.get("fast_daily_risk_state", "UNKNOWN")
        monthly_regime = found_signal_res.get("fast_monthly_permission_state", "UNKNOWN")

        m_dates = [m for m in monthly_bars.index if found_signal_w <= m <= backtest_end]
        monthly_snapshots: list[dict[str, Any]] = []
        for m in m_dates:
            cached_snapshot = monthly_snapshot_cache.get(pd.Timestamp(m))
            if cached_snapshot is not None:
                monthly_snapshots.append(cached_snapshot)
                continue
            try:
                snap = build_historical_snapshot_from_context(snapshot_context, m, include_incomplete_periods=False)
                eval_res = evaluate_pattern_a(snap)
                st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
                sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
                cached_snapshot = {"date": m, "stage": st, "score": sc}
            except Exception:
                cached_snapshot = {"date": m, "stage": "UNAVAILABLE", "score": None}
            monthly_snapshot_cache[pd.Timestamp(m)] = cached_snapshot
            monthly_snapshots.append(cached_snapshot)

        first_early_trend_d = found_signal_w if pa_stage_at_entry == "EARLY_TREND" else None
        direct_handoff_observed = False
        early_trend_to_prog_d: pd.Timestamp | None = None
        first_progressed_d: pd.Timestamp | None = None
        first_prog_score: float | None = None
        skipped_handoff = False
        progressed_observed = False
        prev_valid_stage = pa_stage_at_entry
        had_early_trend = (pa_stage_at_entry == "EARLY_TREND")

        for row in monthly_snapshots:
            m, st, sc = row["date"], row["stage"], row["score"]
            if st == "UNAVAILABLE":
                continue
            if st == "EARLY_TREND":
                had_early_trend = True
                if first_early_trend_d is None:
                    first_early_trend_d = m
            if st == "PROGRESSED":
                progressed_observed = True
                if first_progressed_d is None:
                    first_progressed_d = m
                    first_prog_score = sc
                if prev_valid_stage == "EARLY_TREND" and not direct_handoff_observed:
                    direct_handoff_observed = True
                    early_trend_to_prog_d = m
                elif prev_valid_stage == "TRANSITION" and not had_early_trend and not direct_handoff_observed and not skipped_handoff:
                    skipped_handoff = True
            prev_valid_stage = st

        if direct_handoff_observed and early_trend_to_prog_d is not None:
            coverage_path = "NORMAL_EARLY_TREND_HANDOFF"
        elif skipped_handoff:
            coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"
        elif progressed_observed:
            coverage_path = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
        else:
            coverage_path = "NEVER_PROGRESSED"

        first_prog_eff_trading_d: pd.Timestamp | None = None
        if first_progressed_d is not None:
            month_daily = daily[daily.index <= first_progressed_d]
            if not month_daily.empty:
                first_prog_eff_trading_d = month_daily.index.max()
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index < first_prog_eff_trading_d)]
        else:
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index <= backtest_end)]

        loss_guard_triggered = False
        loss_guard_sig_d: pd.Timestamp | None = None
        loss_guard_sig_close: float | None = None
        loss_guard_ret_at_sig: float | None = None
        loss_guard_exec_d: pd.Timestamp | None = None
        loss_guard_exec_price: float | None = None

        if loss_guard_enabled:
            for d, row in pre_prog_daily.iterrows():
                c_price = float(row["close"])
                ret_at_sig = c_price / entry_open_price - 1.0
                if ret_at_sig <= LOSS_GUARD_THRESHOLD:
                    loss_guard_triggered = True
                    loss_guard_sig_d = d
                    loss_guard_sig_close = c_price
                    loss_guard_ret_at_sig = round(ret_at_sig * 100, 2)
                    fut_after_stop = daily[(daily.index > d) & (daily.index <= backtest_end)]
                    if not fut_after_stop.empty:
                        loss_guard_exec_d = fut_after_stop.index[0]
                        loss_guard_exec_price = float(fut_after_stop.iloc[0]["open"])
                    break
        # When disabled, the loss guard is completely disabled; no
        # supplementary stop of any kind is applied.

        e2_sig_d: pd.Timestamp | None = None
        e2_exit_type: str | None = None

        if coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
            in_p, hwm_1 = False, None
            for row in monthly_snapshots:
                m, st, sc = row["date"], row["stage"], row["score"]
                if m < early_trend_to_prog_d:
                    continue
                if m == early_trend_to_prog_d:
                    in_p, hwm_1 = True, (sc if sc is not None else 0.0)
                    continue
                if in_p:
                    if st == "PROGRESSED":
                        if sc is not None and hwm_1 is not None:
                            hwm_1 = max(hwm_1, sc)
                            if hwm_1 - sc >= EXIT4_DRAWDOWN_POINTS:
                                e2_sig_d, e2_exit_type = m, "EXIT4_SCORE_DRAWDOWN_GE_15"
                                break
                    elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                        e2_sig_d, e2_exit_type = m, f"EXIT3_PROGRESSED_TO_{st}"
                        break
            if e2_sig_d is None:
                e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"
        elif coverage_path in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
            if first_progressed_d is not None:
                hwm_2 = first_prog_score if first_prog_score is not None else 0.0
                in_p = True
                for row in monthly_snapshots:
                    m, st, sc = row["date"], row["stage"], row["score"]
                    if m <= first_progressed_d:
                        continue
                    if in_p:
                        if st == "PROGRESSED":
                            if sc is not None:
                                hwm_2 = max(hwm_2, sc)
                                if hwm_2 - sc >= EXIT4_DRAWDOWN_POINTS:
                                    e2_sig_d, e2_exit_type = m, "EXIT4_SCORE_DRAWDOWN_GE_15"
                                    break
                        else:
                            in_p = False
                            break
                if e2_sig_d is None:
                    e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"
            else:
                e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"
        else:
            e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"

        if loss_guard_triggered and loss_guard_sig_d is not None:
            final_sig_d = loss_guard_sig_d
            final_exit_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
        else:
            final_sig_d = e2_sig_d
            final_exit_type = e2_exit_type or "NO_EXIT"

        outcome = _calc_trade_outcome(entry_exec_date, entry_open_price, final_sig_d, daily, backtest_end)

        loss_guard_realized_return = None
        if loss_guard_triggered and loss_guard_exec_price is not None:
            loss_guard_realized_return = round(((loss_guard_exec_price - entry_open_price) / entry_open_price) * 100, 2)

        record = StrategyTradeRecord(
            strategy_id=strategy_id,
            ticker=ticker,
            isu_cd=isu_cd,
            name=name,
            market=market,
            trade_id=trade_id,
            trade_sequence=trade_seq,
            entry_signal_date=found_signal_w.strftime("%Y-%m-%d"),
            entry_execution_date=entry_exec_date.strftime("%Y-%m-%d"),
            entry_open=round(entry_open_price, 2),
            entry_market_cap=found_filter["entry_market_cap"],
            entry_avg_trading_value_20d=found_filter["entry_avg_trading_value_20d"],
            entry_signal_close=found_filter["entry_signal_close"],
            entry_market_cap_pass=found_filter["entry_market_cap_pass"],
            entry_trading_value_pass=found_filter["entry_trading_value_pass"],
            entry_close_pass=found_filter["entry_close_pass"],
            entry_pattern_a_stage=pa_stage_at_entry,
            fast_stage="TRIGGER",
            fast_status="READY",
            monthly_permission_state=monthly_regime,
            daily_risk=daily_risk,
            fast_score=round(fast_score, 2) if fast_score is not None else None,
            fast_score_state=fast_score_avail,
            first_progressed_date=first_progressed_d.strftime("%Y-%m-%d") if first_progressed_d else None,
            first_progressed_effective_trading_date=first_prog_eff_trading_d.strftime("%Y-%m-%d") if first_prog_eff_trading_d else None,
            lifecycle_class=coverage_path,
            loss_guard_triggered=loss_guard_triggered,
            loss_guard_signal_date=loss_guard_sig_d.strftime("%Y-%m-%d") if loss_guard_sig_d else None,
            loss_guard_signal_close=round(loss_guard_sig_close, 2) if loss_guard_sig_close is not None else None,
            loss_guard_return_at_signal=loss_guard_ret_at_sig,
            loss_guard_execution_date=loss_guard_exec_d.strftime("%Y-%m-%d") if loss_guard_exec_d else None,
            loss_guard_execution_price=round(loss_guard_exec_price, 2) if loss_guard_exec_price is not None else None,
            loss_guard_realized_return=loss_guard_realized_return,
            exit_type=final_exit_type,
            exit_signal_date=final_sig_d.strftime("%Y-%m-%d") if final_sig_d else None,
            exit_execution_date=outcome["exit_exec_d"].strftime("%Y-%m-%d") if outcome["exit_exec_d"] else None,
            exit_price=round(outcome["exit_open"], 2) if outcome["exit_open"] is not None else None,
            terminal_return=outcome["terminal_ret"],
            mfe=outcome["mfe"],
            mae=outcome["mae"],
            peak_giveback=outcome["terminal_giveback"],
            holding_trading_days=outcome["holding_days"],
            holding_weeks=outcome["holding_weeks"],
            trade_status=outcome["trade_status"],
            cutoff_date=(
                min(pd.Timestamp(backtest_end), identity_lifecycle.effective_to).strftime("%Y-%m-%d")
                if outcome["trade_status"] == "OPEN_AT_CUTOFF"
                else None
            ),
            cutoff_valuation_price=outcome.get("cutoff_close"),
            mark_to_cutoff_return=outcome.get("mark_to_cutoff_ret"),
            entry_signal_information_date=found_filter.get("entry_signal_information_date"),
            entry_filter_raw_date=found_filter.get("entry_filter_raw_date"),
            identity_effective_from=(identity_lifecycle.effective_from.strftime("%Y-%m-%d") if identity_lifecycle else None),
            identity_effective_to=(identity_lifecycle.effective_to.strftime("%Y-%m-%d") if identity_lifecycle else None),
        )
        trades.append(record)

        if outcome["trade_status"] == "REALIZED" and outcome["exit_exec_d"] is not None:
            cur_search_date = outcome["exit_exec_d"]
        else:
            cur_search_date = None
            break

    return trades


def _calc_trade_outcome(
    entry_exec_d: pd.Timestamp,
    entry_open: float,
    exit_sig_d: pd.Timestamp | None,
    daily: pd.DataFrame,
    cutoff_date: pd.Timestamp,
) -> dict[str, Any]:
    exit_exec_d: pd.Timestamp | None = None
    exit_open: float | None = None
    trade_status = "OPEN_AT_CUTOFF"
    realized_ret: float | None = None
    cutoff_close: float | None = None
    mark_to_cutoff_ret: float | None = None

    if exit_sig_d is not None:
        fut_after_exit = daily[(daily.index > exit_sig_d) & (daily.index <= cutoff_date)]
        if not fut_after_exit.empty:
            exit_exec_d = fut_after_exit.index[0]
            exit_open = float(fut_after_exit.iloc[0]["open"])
            trade_status = "REALIZED"
            realized_ret = round(((exit_open - entry_open) / entry_open) * 100, 2)

    if trade_status == "REALIZED" and exit_exec_d is not None and exit_open is not None:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index < exit_exec_d)]
        holding_days = len(daily[(daily.index >= entry_exec_d) & (daily.index <= exit_exec_d)])
        holding_weeks = round(holding_days / 5.0, 1)
        if not holding_daily.empty:
            peak_price = float(max(holding_daily["high"].tolist() + [exit_open]))
            min_price = float(min(holding_daily["low"].tolist() + [exit_open]))
        else:
            peak_price = float(max(entry_open, exit_open))
            min_price = float(min(entry_open, exit_open))
        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = realized_ret
    else:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
        holding_days = len(holding_daily)
        holding_weeks = round(holding_days / 5.0, 1)
        cutoff_close = float(holding_daily.iloc[-1]["close"]) if not holding_daily.empty else entry_open
        mark_to_cutoff_ret = round(((cutoff_close - entry_open) / entry_open) * 100, 2)
        peak_price = float(holding_daily["high"].max()) if not holding_daily.empty else entry_open
        min_price = float(holding_daily["low"].min()) if not holding_daily.empty else entry_open
        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = mark_to_cutoff_ret

    terminal_gb = round(mfe - terminal_ret, 2)

    return {
        "exit_exec_d": exit_exec_d,
        "exit_open": exit_open,
        "trade_status": trade_status,
        "terminal_ret": terminal_ret,
        "mfe": mfe,
        "mae": mae,
        "terminal_giveback": terminal_gb,
        "holding_days": holding_days,
        "holding_weeks": holding_weeks,
        "cutoff_close": cutoff_close,
        "mark_to_cutoff_ret": mark_to_cutoff_ret,
    }
