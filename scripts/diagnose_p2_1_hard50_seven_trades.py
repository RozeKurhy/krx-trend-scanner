#!/usr/bin/env python3
"""Run the fixed seven-trade, next-session-open HARD -50 diagnostic for P2-1."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fastcore_neg40_weak_protect_p2_1 import (
    CORRECTED_RUN_DIR,
    ROOT,
    _load_context,
    _next_local_session,
    _pct,
)


TARGET_TICKERS = ("007390", "033160", "034830", "036010", "043220", "048830", "139480")
RUN_DIR = ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260923"
DIAGNOSTIC_DIR = RUN_DIR / "diagnostics/hard50_seven_trade_v01"
LEDGER_PATH = CORRECTED_RUN_DIR / "p2_1_matched_trades.csv"
EVENTS_PATH = CORRECTED_RUN_DIR / "p2_1_soft_events.csv"
SOURCE_SUMMARY_PATH = CORRECTED_RUN_DIR / "p2_1_summary.json"
CSV_NAME = "hard50_seven_trade_diagnostic.csv"
SUMMARY_NAME = "hard50_seven_trade_summary.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _identity_segment(ticker: str, identity: str, run: Any) -> Any:
    parts = identity.split("|")
    _require(len(parts) == 4, f"invalid ledger identity for {ticker}: {identity}")
    isu_cd, market, effective_from, effective_to = parts
    matches = [
        segment
        for segment in run.segments_by_ticker.get(ticker, ())
        if segment.isu_cd == isu_cd
        and segment.market == market
        and segment.effective_from.strftime("%Y-%m-%d") == effective_from
        and segment.effective_to.strftime("%Y-%m-%d") == effective_to
    ]
    _require(len(matches) == 1, f"PIT identity segment mismatch for {ticker}: {identity}")
    return matches[0]


def _candidate_outcome(candidate_return: float) -> str:
    if candidate_return > 0:
        return "FINAL_POSITIVE"
    if candidate_return > -50.0:
        return "RECOVERED_ABOVE_NEG50"
    return "FINAL_LE_NEG50"


def _diagnose_trade(row: dict[str, Any], events: pd.DataFrame, run: Any) -> dict[str, Any]:
    ticker = str(row["ticker"]).zfill(6)
    trade_id = str(row["trade_id"])
    trade_events = events[events["trade_id"] == trade_id].copy()
    neg40 = trade_events[pd.to_numeric(trade_events["close_return"]) <= -40.0]
    weak_neg50 = trade_events[
        (trade_events["event_type"] == "WEAK_PROTECT")
        & (trade_events["pattern_a_stage"] == "WEAK")
        & (pd.to_numeric(trade_events["close_return"]) <= -50.0)
    ]
    _require(not neg40.empty, f"missing P2-1 NEG40 touch event for {trade_id}")
    _require(not weak_neg50.empty, f"missing P2-1 WEAK-protected NEG50 event for {trade_id}")

    first_neg40 = neg40.sort_values("date", kind="mergesort").iloc[0]
    first_neg50 = weak_neg50.sort_values("date", kind="mergesort").iloc[0]
    signal_date = pd.Timestamp(first_neg50["date"]).normalize()
    entry_date = pd.Timestamp(row["entry_date"]).normalize()
    segment = _identity_segment(ticker, str(row["identity"]), run)
    support_end = min(segment.effective_to, run.window.execution_support)
    loader = RepositoryV2DailyLoader(run.loader.repository, start=segment.effective_from, end=support_end)
    daily = loader.load(ticker)
    _require(daily is not None and not daily.empty, f"Repository V2 has no rows for {ticker}/{segment.key}")
    daily = daily.sort_index()
    daily.index = pd.DatetimeIndex(daily.index).normalize()
    _require(not daily.index.duplicated().any(), f"duplicate Repository V2 sessions for {ticker}/{segment.key}")
    _require({"open", "high", "low", "close"}.issubset(daily.columns), f"incomplete OHLC for {ticker}")

    _require(segment.effective_from <= entry_date <= segment.effective_to, f"entry crosses identity for {trade_id}")
    _require(segment.effective_from <= signal_date <= segment.effective_to, f"NEG50 signal crosses identity for {trade_id}")
    _require(signal_date in daily.index, f"NEG50 signal date has no actual OHLC row for {trade_id}")
    _require(run.calendar.is_trading_day(signal_date), f"NEG50 signal date is not a KRX trading day: {signal_date.date()}")
    _require(run.calendar.is_trading_day(entry_date), f"entry date is not a KRX trading day: {entry_date.date()}")

    entry_open = float(daily.loc[entry_date, "open"])
    _require(
        np.isclose(entry_open, float(row["entry_open"]), atol=0.005, rtol=0),
        f"entry OPEN differs from P2-1 ledger for {trade_id}",
    )
    first_neg40_date = pd.Timestamp(first_neg40["date"]).normalize()
    _require(first_neg40_date in daily.index, f"NEG40 touch date has no OHLC row for {trade_id}")
    calculated_neg50_return = _pct(float(daily.loc[signal_date, "close"]), entry_open)
    _require(
        np.isclose(calculated_neg50_return, float(first_neg50["close_return"]), atol=0.005, rtol=0),
        f"NEG50 close-return arithmetic differs from the event ledger for {trade_id}",
    )

    execution_date = _next_local_session(daily, signal_date, run.window.execution_support)
    _require(execution_date is not None, f"no next local-session OPEN support for {trade_id}")
    execution_date = pd.Timestamp(execution_date).normalize()
    _require(execution_date in daily.index, f"HARD execution uses a missing/non-session bar for {trade_id}")
    _require(run.calendar.is_trading_day(execution_date), f"HARD execution date is not a KRX session for {trade_id}")
    _require(execution_date > signal_date, f"same-day/future HARD execution date for {trade_id}")
    _require(execution_date <= run.window.execution_support, f"HARD execution exceeds P2-1 support for {trade_id}")
    _require(execution_date <= segment.effective_to, f"HARD execution crosses identity boundary for {trade_id}")

    signal_close = float(daily.loc[signal_date, "close"])
    execution_open = float(daily.loc[execution_date, "open"])
    hard_terminal = _pct(execution_open, entry_open)
    candidate_return = float(row["candidate_terminal_return"])
    control_return = float(row["control_terminal_return"])
    hard_vs_candidate = round(hard_terminal - candidate_return, 2)
    hard_vs_control = round(hard_terminal - control_return, 2)

    candidate_open = bool(row["candidate_open_at_cutoff"])
    candidate_end = (
        pd.Timestamp(run.window.effective_end).normalize()
        if candidate_open
        else pd.Timestamp(row["candidate_exit_or_cutoff_date"]).normalize()
    )
    _require(candidate_end >= signal_date, f"candidate ended before its WEAK-protected NEG50 event: {trade_id}")
    sessions_after_signal = daily.index[(daily.index > signal_date) & (daily.index <= candidate_end)]
    if candidate_open:
        held_eod = daily[(daily.index > signal_date) & (daily.index <= run.window.effective_end)]
    else:
        # Candidate exits at OPEN; that date's later close is outside its held path.
        held_eod = daily[(daily.index > signal_date) & (daily.index < candidate_end)]
    post_signal_close_returns = [_pct(float(value), entry_open) for value in held_eod["close"].tolist()]
    highest_after_signal = max(post_signal_close_returns) if post_signal_close_returns else None
    lowest_after_signal = min(post_signal_close_returns) if post_signal_close_returns else None

    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "identity": str(row["identity"]),
        "entry_date": entry_date.strftime("%Y-%m-%d"),
        "entry_open": round(entry_open, 4),
        "first_neg40_touch_date": first_neg40_date.strftime("%Y-%m-%d"),
        "first_neg40_touch_close_return": round(float(first_neg40["close_return"]), 2),
        "first_neg50_touch_date": signal_date.strftime("%Y-%m-%d"),
        "neg50_signal_close_return": calculated_neg50_return,
        "pattern_a_stage_at_neg50": str(first_neg50["pattern_a_stage"]),
        "hard_execution_date": execution_date.strftime("%Y-%m-%d"),
        "hard_execution_open": round(execution_open, 4),
        "hard_terminal_return": hard_terminal,
        "current_candidate_exit_or_cutoff_date": str(row["candidate_exit_or_cutoff_date"]),
        "current_candidate_terminal_return": round(candidate_return, 2),
        "control_terminal_return": round(control_return, 2),
        "hard_vs_candidate_delta": hard_vs_candidate,
        "hard_vs_control_delta": hard_vs_control,
        "candidate_final_outcome": _candidate_outcome(candidate_return),
        "candidate_sessions_after_neg50_signal_until_endpoint": int(len(sessions_after_signal)),
        "candidate_held_eod_sessions_after_neg50_signal": int(len(held_eod)),
        "highest_close_return_after_neg50_while_held": (
            round(float(highest_after_signal), 2) if highest_after_signal is not None else None
        ),
        "lowest_close_return_after_neg50_while_held": (
            round(float(lowest_after_signal), 2) if lowest_after_signal is not None else None
        ),
        "signal_close_to_hard_open_gap_pct": round((execution_open / signal_close - 1.0) * 100.0, 2),
        "hard_vs_neg50_signal_close_delta": round(hard_terminal - calculated_neg50_return, 2),
    }


def _verdict(summary: dict[str, Any]) -> tuple[str, str]:
    improved = summary["hard_improved_trade_count"]
    worsened = summary["hard_worsened_trade_count"]
    delta_sum = summary["hard_vs_candidate_delta_sum"]
    deep_tail_improvements = summary["deep_tail_improved_trade_count"]
    recovery_clipped = summary["positive_recovery_clipped_trade_count"]
    if delta_sum > 0 and improved > worsened and deep_tail_improvements > 0 and recovery_clipped == 0:
        return "HARD50_PROMISING", "7건 합산 개선, 개선 거래 우세, deep-tail 개선, 양수 회복 훼손 없음."
    if delta_sum < 0 and deep_tail_improvements == 0:
        return "HARD50_NOT_PROMISING", "7건 합산 손익이 악화되고 deep-tail 개선 거래가 없음."
    if deep_tail_improvements > 0 and recovery_clipped > 0:
        return "HARD50_MIXED", "deep-tail 손실 감소와 양수 회복 훼손이 동시에 있어 교환 관계가 큼."
    return "HARD50_MIXED", "7건 합계·거래별 개선 및 악화가 엇갈려 추가 판단이 필요함."


def run() -> dict[str, Any]:
    _require(not DIAGNOSTIC_DIR.exists(), f"refusing to overwrite diagnostic directory: {DIAGNOSTIC_DIR}")
    _require(LEDGER_PATH.exists() and EVENTS_PATH.exists() and SOURCE_SUMMARY_PATH.exists(), "missing final P2-1 fix02 input")
    source_summary = json.loads(SOURCE_SUMMARY_PATH.read_text(encoding="utf-8"))
    _require(source_summary.get("status") == "COMPLETE" and source_summary.get("window_id") == "P2-1", "fix02 source is not the completed P2-1 result")

    ledger = pd.read_csv(LEDGER_PATH, dtype={"ticker": str, "trade_id": str})
    events = pd.read_csv(EVENTS_PATH, dtype={"ticker": str, "trade_id": str})
    targets = set(TARGET_TICKERS)
    target_ledger = ledger[ledger["ticker"].isin(targets)].copy()
    _require(len(target_ledger) == 7, f"expected exactly seven matched trades, found {len(target_ledger)}")
    _require(set(target_ledger["ticker"]) == targets, "target ticker set differs from the P2-1 matched ledger")
    _require(not target_ledger["ticker"].duplicated().any(), "more than one matched trade found for a target ticker")
    _require(not target_ledger["trade_id"].duplicated().any(), "duplicate target trade_id in matched ledger")

    target_trade_ids = set(target_ledger["trade_id"])
    weak_neg50 = events[
        events["event_type"].eq("WEAK_PROTECT")
        & events["pattern_a_stage"].eq("WEAK")
        & (pd.to_numeric(events["close_return"]) <= -50.0)
    ]
    target_weak_neg50 = weak_neg50[weak_neg50["ticker"].isin(targets)]
    _require(set(target_weak_neg50["ticker"]) == targets, "target set does not match WEAK-protected NEG50 event tickers")
    _require(set(target_weak_neg50["trade_id"]) == target_trade_ids, "target trade IDs do not match WEAK-protected NEG50 event IDs")
    _require(
        set(weak_neg50["ticker"]) == targets,
        "the full fix02 WEAK-protected NEG50 event ticker set differs from the specified seven; CHECK_REQUIRED",
    )
    _require(
        set(weak_neg50["trade_id"]) == target_trade_ids,
        "the full fix02 WEAK-protected NEG50 event trade set differs from the specified seven; CHECK_REQUIRED",
    )

    run_context = _load_context()
    _require(run_context.window.window.window_id == "P2-1", "diagnostic window is not P2-1")
    records = [
        _diagnose_trade(row, events, run_context)
        for row in target_ledger.sort_values("ticker", kind="mergesort").to_dict(orient="records")
    ]
    detail = pd.DataFrame(records)
    _require(len(detail) == 7 and detail["trade_id"].nunique() == 7, "diagnostic did not produce seven unique trades")
    _require(detail["trade_id"].nunique() == 7, "duplicate HARD overlay row; each trade must trigger at most once")

    delta = pd.to_numeric(detail["hard_vs_candidate_delta"])
    candidate_returns = pd.to_numeric(detail["current_candidate_terminal_return"])
    hard_returns = pd.to_numeric(detail["hard_terminal_return"])
    control_returns = pd.to_numeric(detail["control_terminal_return"])
    deep_tail = (candidate_returns <= -50.0) & (hard_returns > candidate_returns)
    deep_tail_crossed = (candidate_returns <= -50.0) & (hard_returns > -50.0)
    positive_recovery_clipped = (candidate_returns > 0.0) & (hard_returns < candidate_returns)
    improved_ids = detail.loc[delta > 0, "trade_id"].tolist()
    worsened_ids = detail.loc[delta < 0, "trade_id"].tolist()
    same_ids = detail.loc[delta == 0, "trade_id"].tolist()
    deep_tail_ids = detail.loc[deep_tail, "trade_id"].tolist()
    clipped_ids = detail.loc[positive_recovery_clipped, "trade_id"].tolist()

    aggregate = {
        "trade_count": int(len(detail)),
        "current_candidate_terminal_return_sum": round(float(candidate_returns.sum()), 2),
        "hard_terminal_return_sum": round(float(hard_returns.sum()), 2),
        "hard_vs_candidate_delta_sum": round(float(delta.sum()), 2),
        "current_candidate_terminal_return_mean": round(float(candidate_returns.mean()), 4),
        "hard_terminal_return_mean": round(float(hard_returns.mean()), 4),
        "hard_vs_candidate_delta_mean": round(float(delta.mean()), 4),
        "hard_vs_control_delta_sum": round(float((hard_returns - control_returns).sum()), 2),
        "hard_improved_trade_count": int((delta > 0).sum()),
        "hard_worsened_trade_count": int((delta < 0).sum()),
        "hard_same_trade_count": int((delta == 0).sum()),
        "hard_improved_trade_ids": improved_ids,
        "hard_worsened_trade_ids": worsened_ids,
        "hard_same_trade_ids": same_ids,
        "positive_recovery_clipped_trade_count": int(positive_recovery_clipped.sum()),
        "positive_recovery_clipped_trade_ids": clipped_ids,
        "deep_tail_improved_trade_count": int(deep_tail.sum()),
        "deep_tail_improved_trade_ids": deep_tail_ids,
        "deep_tail_crossed_above_neg50_count": int(deep_tail_crossed.sum()),
        "deep_tail_crossed_above_neg50_trade_ids": detail.loc[deep_tail_crossed, "trade_id"].tolist(),
        "deep_tail_improvement_sum_pct_points": round(float(delta[deep_tail].sum()), 2),
        "signal_close_to_hard_open_gap_mean_pct": round(float(detail["signal_close_to_hard_open_gap_pct"].mean()), 2),
        "signal_close_to_hard_open_gap_min_pct": round(float(detail["signal_close_to_hard_open_gap_pct"].min()), 2),
        "signal_close_to_hard_open_gap_max_pct": round(float(detail["signal_close_to_hard_open_gap_pct"].max()), 2),
    }
    verdict, verdict_reason = _verdict(aggregate)
    row_007390 = detail.loc[detail["ticker"] == "007390"].iloc[0]
    aggregate["007390_recovery_clipped_from_pct"] = float(row_007390["current_candidate_terminal_return"])
    aggregate["007390_hard_terminal_return_pct"] = float(row_007390["hard_terminal_return"])
    aggregate["007390_hard_vs_candidate_delta_pct_points"] = float(row_007390["hard_vs_candidate_delta"])

    summary = {
        "status": "COMPLETE",
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "diagnostic_scope": "Only the seven P2-1 fix02 WEAK-protected trades that first touched -50%; no full backtest and no other windows.",
        "source": {
            "matched_ledger": str(LEDGER_PATH.relative_to(ROOT)),
            "soft_events": str(EVENTS_PATH.relative_to(ROOT)),
            "fix02_summary": str(SOURCE_SUMMARY_PATH.relative_to(ROOT)),
            "head": source_summary["head"],
            "window": source_summary["window"],
            "candidate_strategy_id": source_summary["strategy_ids"]["candidate"],
        },
        "target_validation": {
            "specified_tickers": list(TARGET_TICKERS),
            "matched_ledger_trade_count": int(len(target_ledger)),
            "matched_ledger_tickers_equal_target": True,
            "weak_protected_neg50_ticker_set_equal_target": True,
            "weak_protected_neg50_trade_id_set_equal_ledger": True,
            "trade_ids": detail[["ticker", "trade_id"]].to_dict(orient="records"),
        },
        "hard50_overlay": {
            "signal": "After PROGRESSED, while held, first EOD close return <= -50%; Pattern A stage is ignored for the virtual HARD overlay.",
            "execution": "Next actual ticker-local Repository V2 session OPEN, bounded by the COMMON PIT identity interval and P2-1 execution support.",
            "same_day_close_execution": False,
            "official_candidate_rule_changed": False,
            "cost_basis": "Same gross price-return basis as the P2-1 matched ledger; no additional fees/slippage overlay.",
            "hard_terminal_return_formula": "round(((next_session_open - entry_open) / entry_open) * 100, 2)",
        },
        "aggregate": aggregate,
        "diagnostic_limits": {
            "sample_size": 7,
            "not_a_full_strategy_backtest": True,
            "not_a_threshold_sweep": True,
            "no_strategy_adoption_decision": True,
            "candidate_path_high_low_window": "EODs after first -50 signal while the current Candidate position remains held; candidate exit OPEN date excluded, cutoff included for open positions.",
            "sessions_to_endpoint_window": "Actual ticker sessions after the -50 signal through the current Candidate exit/cutoff endpoint, endpoint included.",
        },
        "validation": {
            "target_set_exact": True,
            "first_neg50_is_weak_protected_eod": True,
            "hard_signal_uses_first_neg50_touch_only": True,
            "duplicate_hard_signals": 0,
            "next_local_session_open_used": True,
            "execution_date_is_krx_trading_day": True,
            "identity_boundaries_respected": True,
            "future_prices_used_for_signal_or_execution": False,
            "support_boundary_respected": True,
            "terminal_return_matches_v2_arithmetic": True,
        },
    }

    _require(not DIAGNOSTIC_DIR.exists(), f"refusing to overwrite diagnostic directory: {DIAGNOSTIC_DIR}")
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=False)
    detail.to_csv(DIAGNOSTIC_DIR / CSV_NAME, index=False, float_format="%.2f")
    (DIAGNOSTIC_DIR / SUMMARY_NAME).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
