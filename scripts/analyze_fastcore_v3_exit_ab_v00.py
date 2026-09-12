#!/usr/bin/env python3
"""Analyze FastCore V0 exits on the fixed CONTROL entry cohort.

This is a diagnostic-only runner.  It does not scan new entries, alter the
FastCore V2/V3 runners, execute Julia, or rerun the existing V3 backtest.
Each CONTROL entry is replayed independently under the already-frozen V0
price HWM/MFE exit contract so exit effects can be compared at matched entry
points.  The V3 market-cap analysis reads the existing V3 trade artifact.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
import argparse
import json
import socket
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_v3_simple_v00 as v3
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    clip_to_identity_lifecycle,
)
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context


SOURCE_OUT_DIR = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01"
MATCHED_PATH = OUT_DIR / "matched_control_entries_v2_vs_v0.csv"
SUMMARY_PATH = OUT_DIR / "matched_control_entries_v2_vs_v0_summary.json"
MFE_PATH = OUT_DIR / "v0_mfe_tier_diagnostics.csv"
LOSS_GUARD_PATH = OUT_DIR / "v2_loss_guard_subset_diagnostics.csv"
EXIT_PATH = OUT_DIR / "v0_exit_reason_diagnostics.csv"
BUCKET_PATH = OUT_DIR / "v3_market_cap_bucket_diagnostics.csv"
REPORT_PATH = OUT_DIR / "fastcore_v3_exit_ab_v00_fix01_report.md"

CONTROL_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"
V3_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_v3_simple_v00/fastcore_v3_trades.csv"
V3_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_v3_simple_v00/fastcore_v3_summary.json"


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise RuntimeError(f"offline exit A/B guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise RuntimeError(f"offline exit A/B guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _identity_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        str(row[field])
        for field in ("ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to")
    )


def _lifecycle(row: Mapping[str, Any]) -> IdentityLifecycle:
    return IdentityLifecycle(
        ticker=str(row["ticker"]).zfill(6),
        isu_cd=str(row["isu_cd"]),
        market=str(row["market"]),
        effective_from=_date(row["identity_effective_from"]),
        effective_to=min(_date(row["identity_effective_to"]), v3.SUPPORT_END),
    )


def _state_index(control: pd.DataFrame, loader: RepositoryV2DailyLoader) -> tuple[dict[str, list[tuple[pd.Timestamp, str]]], dict[str, pd.DataFrame], int]:
    contracts = (_read_json(v3.SCORE_CONTRACT_PATH), _read_json(v3.STAGE_CONTRACT_PATH))
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    state_index: dict[str, list[tuple[pd.Timestamp, str]]] = defaultdict(list)
    error_count = 0
    identity_rows = control.drop_duplicates(
        ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    )
    for ticker, ticker_rows in identity_rows.groupby("ticker", sort=True):
        daily = loader.load(str(ticker))
        if daily is None or daily.empty:
            raise RuntimeError(f"missing local Repository V2 prices for CONTROL ticker {ticker}")
        daily_by_ticker[str(ticker)] = daily
        for row in ticker_rows.to_dict("records"):
            key = _identity_key(row)
            lifecycle = _lifecycle(row)
            clipped = clip_to_identity_lifecycle(daily, lifecycle)
            if clipped is None or clipped.empty:
                raise RuntimeError(f"empty identity-scoped daily data for {key}")
            context = build_precomputed_ticker_context(str(ticker), str(row["name"]), clipped)
            daily_dates = set(pd.DatetimeIndex(clipped.index).normalize())
            weeks = [
                _date(value)
                for value in context.weekly_up_to(v3.SUPPORT_END).index
                if _date(value) in daily_dates and v3.START_DATE <= _date(value) <= v3.SIGNAL_CUTOFF
            ]
            for week in weeks:
                try:
                    result = evaluate_pattern_a_fast(
                        str(ticker), str(row["name"]), clipped, week,
                        contracts[0], contracts[1], context=context,
                    )
                except Exception:
                    error_count += 1
                    continue
                fast_state = str(result.get("fast_machine_stage") or "UNAVAILABLE").upper()
                if result.get("fast_machine_stage_status") != "READY":
                    fast_state = "UNAVAILABLE"
                state_index[key].append((week, fast_state))
            state_index[key].sort(key=lambda item: item[0])
    return dict(state_index), daily_by_ticker, error_count


def replay_v0_entry(row: Mapping[str, Any], daily_full: pd.DataFrame, states: list[tuple[pd.Timestamp, str]]) -> dict[str, Any]:
    """Replay exactly one fixed CONTROL entry without entry filtering or overlap removal."""
    lifecycle = _lifecycle(row)
    daily = clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        raise RuntimeError(f"missing identity-scoped data for CONTROL trade {row['trade_id']}")

    entry_date = _date(row["entry_execution_date"])
    if entry_date not in daily.index:
        raise RuntimeError(f"CONTROL entry date unavailable for {row['trade_id']}: {entry_date.date()}")
    entry_open = float(row["entry_open"])
    observed_open = float(daily.loc[entry_date, "open"])
    if abs(observed_open - entry_open) > 1e-8:
        raise AssertionError(f"entry OPEN mismatch for {row['trade_id']}: {observed_open} != {entry_open}")

    valuation_date = _date(daily.index[-1])
    hwm = entry_open
    max_hwm_drawdown = 0.0
    exit_signal_date: pd.Timestamp | None = None
    exit_execution_date: pd.Timestamp | None = None
    exit_price: float | None = None
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
        mfe_pct = (hwm / entry_open - 1.0) * 100.0
        drawdown_pct = round((close / hwm - 1.0) * 100.0, 10)
        max_hwm_drawdown = min(max_hwm_drawdown, drawdown_pct)
        fast_state = v3.latest_fast_state(states, date)
        decision, soft, hard, tier = v3.exit_decision(
            mfe_pct=mfe_pct, hwm_price=hwm, current_close=close, fast_state=fast_state,
        )
        if decision is not None:
            exit_signal_date = date
            exit_reason = decision
            fast_state_at_exit = fast_state
            soft_threshold = soft
            hard_threshold = hard
            exit_mfe_tier = tier
            break

    trade_status = "OPEN_AT_CUTOFF"
    if exit_signal_date is not None:
        exit_execution_date = v3._next_session(daily, exit_signal_date)
        if exit_execution_date is not None:
            exit_price = float(daily.loc[exit_execution_date, "open"])
            trade_status = "REALIZED"
        else:
            unexecuted_exit_signal_date = exit_signal_date
            exit_signal_date = None
            exit_reason = None
            fast_state_at_exit = None
            soft_threshold = None
            hard_threshold = None
            exit_mfe_tier = None

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
    return {
        "v0_entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "v0_entry_open": entry_open,
        "v0_exit_reason": exit_reason,
        "v0_exit_signal_date": exit_signal_date.strftime("%Y-%m-%d") if exit_signal_date is not None else None,
        "v0_exit_execution_date": exit_execution_date.strftime("%Y-%m-%d") if exit_execution_date is not None else None,
        "v0_exit_price": exit_price,
        "v0_terminal_return": terminal_return,
        "v0_mfe": mfe,
        "v0_mae": mae,
        "v0_holding_days": holding_days,
        "v0_trade_status": trade_status,
        "v0_mfe_tier": terminal_tier[2] if terminal_tier else "BELOW_WINNER_MODE",
        "v0_hwm": round(hwm, 2),
        "v0_max_hwm_drawdown": round(max_hwm_drawdown, 2),
        "v0_fast_state_at_exit": fast_state_at_exit,
        "v0_soft_threshold": soft_threshold,
        "v0_hard_threshold": hard_threshold,
        "v0_unexecuted_exit_signal_date": unexecuted_exit_signal_date.strftime("%Y-%m-%d") if unexecuted_exit_signal_date is not None else None,
    }


def _round(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def build_matched(control: pd.DataFrame, daily_by_ticker: Mapping[str, pd.DataFrame], states: Mapping[str, list[tuple[pd.Timestamp, str]]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in control.sort_values(["ticker", "entry_signal_date", "trade_sequence", "trade_id"], kind="mergesort").to_dict("records"):
        v0 = replay_v0_entry(row, daily_by_ticker[str(row["ticker"])], states.get(_identity_key(row), []))
        v2_return = float(row["terminal_return"])
        v0_return = float(v0["v0_terminal_return"])
        delta = round(v0_return - v2_return, 2)
        comparison = "improved" if delta > 0 else "worsened" if delta < 0 else "same"
        rows.append({
            "ticker": str(row["ticker"]).zfill(6),
            "name": str(row["name"]),
            "market": str(row["market"]),
            "isu_cd": str(row["isu_cd"]),
            "control_trade_id": str(row["trade_id"]),
            "control_trade_sequence": int(row["trade_sequence"]),
            "entry_signal_date": str(row["entry_signal_date"]),
            "entry_signal_information_date": str(row["entry_signal_information_date"]),
            "entry_execution_date": str(row["entry_execution_date"]),
            "entry_open": float(row["entry_open"]),
            "identity_effective_from": str(row["identity_effective_from"]),
            "identity_effective_to": str(row["identity_effective_to"]),
            "v2_exit_reason": str(row["exit_type"]),
            "v2_exit_signal_date": row["exit_signal_date"] if pd.notna(row["exit_signal_date"]) else None,
            "v2_exit_execution_date": row["exit_execution_date"] if pd.notna(row["exit_execution_date"]) else None,
            "v2_exit_price": _round(row["exit_price"], 2),
            "v2_terminal_return": _round(row["terminal_return"], 2),
            "v2_mfe": _round(row["mfe"], 2),
            "v2_mae": _round(row["mae"], 2),
            "v2_holding_days": int(row["holding_trading_days"]),
            "v2_trade_status": str(row["trade_status"]),
            "v2_loss_guard_triggered": bool(row["loss_guard_triggered"]),
            **v0,
            "v0_entry_date_match_control": v0["v0_entry_execution_date"] == str(row["entry_execution_date"]),
            "v0_entry_open_match_control": abs(float(v0["v0_entry_open"]) - float(row["entry_open"])) <= 1e-8,
            "return_delta_v0_minus_v2": delta,
            "improved_worsened_same": comparison,
            "v2_giveback_pp": round(float(row["mfe"]) - v2_return, 2),
            "v0_giveback_pp": round(float(v0["v0_mfe"]) - v0_return, 2),
        })
    return pd.DataFrame(rows)


def _count_rate(count: int, total: int) -> tuple[int, float]:
    return count, round(count / total * 100.0, 6) if total else 0.0


def _mean_median(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _pair_stats(frame: pd.DataFrame, side: str) -> dict[str, Any]:
    return_mean, return_median = _mean_median(frame, f"{side}_terminal_return")
    mfe_mean, mfe_median = _mean_median(frame, f"{side}_mfe")
    mae_mean, mae_median = _mean_median(frame, f"{side}_mae")
    hold_mean, hold_median = _mean_median(frame, f"{side}_holding_days")
    total = len(frame)
    positive = int((pd.to_numeric(frame[f"{side}_terminal_return"], errors="coerce") > 0).sum()) if total else 0
    output: dict[str, Any] = {
        "trades": total,
        "positive_count": positive,
        "positive_rate_pct": _count_rate(positive, total)[1],
        "mean_terminal_return_pct": return_mean,
        "median_terminal_return_pct": return_median,
        "mean_mfe_pct": mfe_mean,
        "median_mfe_pct": mfe_median,
        "mean_mae_pct": mae_mean,
        "median_mae_pct": mae_median,
        "mean_holding_days": hold_mean,
        "median_holding_days": hold_median,
    }
    returns = pd.to_numeric(frame[f"{side}_terminal_return"], errors="coerce")
    for threshold in [20, 30, 50, 100, 200, 400]:
        count, rate = _count_rate(int((returns >= threshold).sum()), total)
        output[f"winner_ge_{threshold}_count"] = count
        output[f"winner_ge_{threshold}_rate_pct"] = rate
    for threshold in [15, 20, 30, 40, 50, 60]:
        count, rate = _count_rate(int((returns <= -threshold).sum()), total)
        output[f"tail_le_-{threshold}_count"] = count
        output[f"tail_le_-{threshold}_rate_pct"] = rate
    return output


def _comparison_stats(frame: pd.DataFrame) -> dict[str, Any]:
    output = {"v2": _pair_stats(frame, "v2"), "v0": _pair_stats(frame, "v0")}
    delta_mean, delta_median = _mean_median(frame, "return_delta_v0_minus_v2")
    mean_terminal_difference = round(
        float(output["v0"]["mean_terminal_return_pct"] - output["v2"]["mean_terminal_return_pct"]), 6
    )
    median_terminal_difference = round(
        float(output["v0"]["median_terminal_return_pct"] - output["v2"]["median_terminal_return_pct"]), 6
    )
    improved = int((frame["improved_worsened_same"] == "improved").sum())
    worsened = int((frame["improved_worsened_same"] == "worsened").sum())
    same = int((frame["improved_worsened_same"] == "same").sum())
    total = len(frame)
    output["delta_mean_pct"] = delta_mean
    output["delta_median_pct"] = delta_median
    output["mean_terminal_return_difference_pp"] = mean_terminal_difference
    output["median_terminal_return_difference_pp"] = median_terminal_difference
    output["mean_paired_return_delta_pp"] = delta_mean
    output["median_paired_return_delta_pp"] = delta_median
    output["improved_count"], output["improved_rate_pct"] = _count_rate(improved, total)
    output["worsened_count"], output["worsened_rate_pct"] = _count_rate(worsened, total)
    output["same_count"], output["same_rate_pct"] = _count_rate(same, total)
    return output


def _diagnostic_row(frame: pd.DataFrame, label: str, *, denominator: int | None = None, v0_exit_reason: str | None = None) -> dict[str, Any]:
    total = len(frame)
    denom = total if denominator is None else denominator
    v2 = _pair_stats(frame, "v2")
    v0 = _pair_stats(frame, "v0")
    delta_mean, delta_median = _mean_median(frame, "return_delta_v0_minus_v2")
    improved = int((frame["improved_worsened_same"] == "improved").sum())
    worsened = int((frame["improved_worsened_same"] == "worsened").sum())
    same = int((frame["improved_worsened_same"] == "same").sum())
    row: dict[str, Any] = {"group": label, "trade_count": total, "trade_rate_pct": _count_rate(total, denom)[1]}
    for prefix, stats in (("v2", v2), ("v0", v0)):
        for key in ["mean_terminal_return_pct", "median_terminal_return_pct", "positive_count", "positive_rate_pct"]:
            row[f"{prefix}_{key}"] = stats[key]
    row.update({
        "mean_return_delta_pct": delta_mean,
        "median_return_delta_pct": delta_median,
        "improved_count": improved,
        "improved_rate_pct": _count_rate(improved, total)[1],
        "worsened_count": worsened,
        "worsened_rate_pct": _count_rate(worsened, total)[1],
        "same_count": same,
        "same_rate_pct": _count_rate(same, total)[1],
        "v2_mean_giveback_pp": _mean_median(frame, "v2_giveback_pp")[0],
        "v2_median_giveback_pp": _mean_median(frame, "v2_giveback_pp")[1],
        "v0_mean_giveback_pp": _mean_median(frame, "v0_giveback_pp")[0],
        "v0_median_giveback_pp": _mean_median(frame, "v0_giveback_pp")[1],
    })
    for threshold in [50, 100]:
        for prefix in ["v2", "v0"]:
            row[f"{prefix}_ge_{threshold}_count"] = v2[f"winner_ge_{threshold}_count"] if prefix == "v2" else v0[f"winner_ge_{threshold}_count"]
            row[f"{prefix}_ge_{threshold}_rate_pct"] = v2[f"winner_ge_{threshold}_rate_pct"] if prefix == "v2" else v0[f"winner_ge_{threshold}_rate_pct"]
    for threshold in [20, 30, 40, 50, 60]:
        for prefix in ["v2", "v0"]:
            stats = v2 if prefix == "v2" else v0
            row[f"{prefix}_le_-{threshold}_count"] = stats[f"tail_le_-{threshold}_count"]
            row[f"{prefix}_le_-{threshold}_rate_pct"] = stats[f"tail_le_-{threshold}_rate_pct"]
    if v0_exit_reason is not None:
        row["v0_exit_reason"] = v0_exit_reason
        row["v0_mean_mfe_pct"], row["v0_median_mfe_pct"] = _mean_median(frame, "v0_mfe")
        row["v0_mean_mae_pct"], row["v0_median_mae_pct"] = _mean_median(frame, "v0_mae")
        row["v0_mean_holding_days"], row["v0_median_holding_days"] = _mean_median(frame, "v0_holding_days")
        row["v0_mean_giveback_pp"] = _mean_median(frame, "v0_giveback_pp")[0]
        row["v0_median_giveback_pp"] = _mean_median(frame, "v0_giveback_pp")[1]
    return row


def _mfe_group(value: float) -> str:
    if value < 20:
        return "MFE_LT_20"
    if value < 50:
        return "MFE_20_TO_50"
    if value < 100:
        return "MFE_50_TO_100"
    if value < 200:
        return "MFE_100_TO_200"
    if value < 400:
        return "MFE_200_TO_400"
    return "MFE_400_PLUS"


def build_mfe_diagnostics(matched: pd.DataFrame) -> pd.DataFrame:
    order = ["MFE_LT_20", "MFE_20_TO_50", "MFE_50_TO_100", "MFE_100_TO_200", "MFE_200_TO_400", "MFE_400_PLUS"]
    groups = matched.assign(mfe_group=matched["v0_mfe"].map(_mfe_group))
    return pd.DataFrame([
        _diagnostic_row(groups[groups["mfe_group"] == label], label, denominator=len(matched))
        for label in order
    ])


def build_loss_guard_diagnostics(matched: pd.DataFrame) -> pd.DataFrame:
    subset = matched[matched["v2_exit_reason"] == "LOSS_GUARD_CLOSE_LE_NEG_15"]
    rows = [_diagnostic_row(subset, "LOSS_GUARD_ALL", denominator=len(matched))]
    rows.append(_diagnostic_row(subset[subset["v0_mfe"] < 20], "LOSS_GUARD_V0_MFE_LT_20", denominator=len(subset)))
    rows.append(_diagnostic_row(subset[subset["v0_mfe"] >= 20], "LOSS_GUARD_V0_MFE_GE_20", denominator=len(subset)))
    for row in rows:
        frame = subset if row["group"] == "LOSS_GUARD_ALL" else subset[subset["v0_mfe"] < 20] if row["group"].endswith("LT_20") else subset[subset["v0_mfe"] >= 20]
        total = len(frame)
        for threshold in [20, 30, 40, 50, 60]:
            count, rate = _count_rate(int((frame["v0_terminal_return"] <= -threshold).sum()), total)
            row[f"v0_le_-{threshold}_count"] = count
            row[f"v0_le_-{threshold}_rate_pct"] = rate
        conversion = int(((frame["v2_terminal_return"] <= 0) & (frame["v0_terminal_return"] > 0)).sum())
        row["v0_profit_conversion_count"], row["v0_profit_conversion_rate_pct"] = _count_rate(conversion, total)
    return pd.DataFrame(rows)


def build_exit_diagnostics(matched: pd.DataFrame) -> pd.DataFrame:
    order = ["SOFT_EXIT", "HARD_EXIT", "OPEN_AT_CUTOFF"]
    return pd.DataFrame([
        _diagnostic_row(matched[matched["v0_exit_reason"] == reason], reason, denominator=len(matched), v0_exit_reason=reason)
        for reason in order
    ])


def _v3_bucket_row(frame: pd.DataFrame, label: str, total: int) -> dict[str, Any]:
    returns = pd.to_numeric(frame["terminal_return"], errors="coerce")
    n = len(frame)
    row: dict[str, Any] = {
        "bucket": label,
        "total_trades": n,
        "trade_rate_pct": _count_rate(n, total)[1],
        "unique_tickers": int(frame["ticker"].nunique()),
        "positive_count": int((returns > 0).sum()),
        "positive_rate_pct": _count_rate(int((returns > 0).sum()), n)[1],
    }
    for column, name in [("terminal_return", "return"), ("mfe", "mfe"), ("mae", "mae"), ("holding_trading_days", "holding_days")]:
        row[f"mean_{name}"] , row[f"median_{name}"] = _mean_median(frame, column)
    for reason in ["SOFT_EXIT", "HARD_EXIT", "OPEN_AT_CUTOFF"]:
        count, rate = _count_rate(int((frame["exit_reason"] == reason).sum()), n)
        row[f"{reason.lower()}_count"] = count
        row[f"{reason.lower()}_rate_pct"] = rate
    for threshold in [20, 30, 50, 100, 200]:
        count, rate = _count_rate(int((returns >= threshold).sum()), n)
        row[f"winner_ge_{threshold}_count"] = count
        row[f"winner_ge_{threshold}_rate_pct"] = rate
    for threshold in [15, 20, 30, 40, 50, 60]:
        count, rate = _count_rate(int((returns <= -threshold).sum()), n)
        row[f"tail_le_-{threshold}_count"] = count
        row[f"tail_le_-{threshold}_rate_pct"] = rate
    return row


def build_bucket_diagnostics(v3_trades: pd.DataFrame) -> pd.DataFrame:
    mcap = pd.to_numeric(v3_trades["entry_market_cap"], errors="coerce")
    assert bool((mcap >= v3.MARKET_CAP_THRESHOLD).all())
    total = len(v3_trades)
    bucket_a = v3_trades[(mcap >= 100_000_000_000) & (mcap < 300_000_000_000)]
    bucket_b = v3_trades[mcap >= 300_000_000_000]
    result = pd.DataFrame([
        _v3_bucket_row(bucket_a, "A_100B_TO_LT_300B", total),
        _v3_bucket_row(bucket_b, "B_GE_300B", total),
    ])
    assert int(result["total_trades"].sum()) == total == 1578
    return result


def _report_pct(value: Any) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{float(value):.6f}%"


def build_report(summary: Mapping[str, Any], mfe: pd.DataFrame, loss_guard: pd.DataFrame, exits: pd.DataFrame, buckets: pd.DataFrame) -> str:
    overall = summary["matched_entry_summary"]
    v2 = overall["v2"]
    v0 = overall["v0"]
    delta = overall["delta_mean_pct"]
    soft = exits[exits["group"] == "SOFT_EXIT"].iloc[0]
    hard = exits[exits["group"] == "HARD_EXIT"].iloc[0]
    lg = loss_guard[loss_guard["group"] == "LOSS_GUARD_ALL"].iloc[0]
    below20 = loss_guard[loss_guard["group"] == "LOSS_GUARD_V0_MFE_LT_20"].iloc[0]
    ge20 = loss_guard[loss_guard["group"] == "LOSS_GUARD_V0_MFE_GE_20"].iloc[0]
    bucket_a = buckets[buckets["bucket"] == "A_100B_TO_LT_300B"].iloc[0]
    bucket_b = buckets[buckets["bucket"] == "B_GE_300B"].iloc[0]
    winner_lines = []
    for threshold in [50, 100, 200]:
        winner_lines.append(
            f"- +{threshold}%: V2 {int(v2[f'winner_ge_{threshold}_count'])} ({_report_pct(v2[f'winner_ge_{threshold}_rate_pct'])}), "
            f"V0 {int(v0[f'winner_ge_{threshold}_count'])} ({_report_pct(v0[f'winner_ge_{threshold}_rate_pct'])})"
        )
    return f"""# FastCore V3 Exit A/B Diagnostic FIX01

## 핵심 질문에 대한 숫자 답

### Q1. 동일한 973개 진입에서 V0가 V2보다 좋아졌는가?

혼합 결과야. V0는 중앙수익률과 승률은 높였지만 평균 terminal return은 낮아졌어. 평균 paired trade delta는 **{_report_pct(overall['mean_paired_return_delta_pp'])}**, 개선/악화/동일은 **{int(overall['improved_count'])}/{int(overall['worsened_count'])}/{int(overall['same_count'])}건**이야.

### Q2. 평균수익률 / 중앙수익률 / 승률 변화

- 평균 terminal return: V2 {_report_pct(v2['mean_terminal_return_pct'])} → V0 {_report_pct(v0['mean_terminal_return_pct'])} (terminal return difference {_report_pct(overall['mean_terminal_return_difference_pp'])}; paired mean delta {_report_pct(overall['mean_paired_return_delta_pp'])})
- 중앙 terminal return: V2 {_report_pct(v2['median_terminal_return_pct'])} → V0 {_report_pct(v0['median_terminal_return_pct'])} (terminal return difference {_report_pct(overall['median_terminal_return_difference_pp'])})
- 중앙 paired trade delta: {_report_pct(overall['median_paired_return_delta_pp'])}
- 승률: V2 {_report_pct(v2['positive_rate_pct'])} → V0 {_report_pct(v0['positive_rate_pct'])}

### Q3. Winner 보존

"보존 능력"은 threshold 도달 건수 기준으로 판단했어.

{chr(10).join(winner_lines)}

### Q4. MFE <20%에서 Loss Guard 제거가 deep loss를 얼마나 증가시켰는가?

Loss Guard subset의 MFE<20% 구간은 **{int(below20['trade_count'])}건**이야. V2의 `<=-20/-30/-40/-50/-60%`는 **{int(below20['v2_le_-20_count'])}/{int(below20['v2_le_-30_count'])}/{int(below20['v2_le_-40_count'])}/{int(below20['v2_le_-50_count'])}/{int(below20['v2_le_-60_count'])}건**, V0는 **{int(below20['v0_le_-20_count'])}/{int(below20['v0_le_-30_count'])}/{int(below20['v0_le_-40_count'])}/{int(below20['v0_le_-50_count'])}/{int(below20['v0_le_-60_count'])}건**이야. 즉 V0 증가폭은 **{int(below20['v0_le_-20_count'] - below20['v2_le_-20_count'])}/{int(below20['v0_le_-30_count'] - below20['v2_le_-30_count'])}/{int(below20['v0_le_-40_count'] - below20['v2_le_-40_count'])}/{int(below20['v0_le_-50_count'] - below20['v2_le_-50_count'])}/{int(below20['v0_le_-60_count'] - below20['v2_le_-60_count'])}건**이야. 전체 Loss Guard subset V0는 **{int(lg['v0_le_-20_count'])}/{int(lg['v0_le_-30_count'])}/{int(lg['v0_le_-40_count'])}/{int(lg['v0_le_-50_count'])}/{int(lg['v0_le_-60_count'])}건**이야.

### Q5. 기존 Loss Guard 거래 중 V0에서 최종 수익 전환된 비율

전체 Loss Guard subset **{int(lg['trade_count'])}건 중 {int(lg['v0_profit_conversion_count'])}건 ({_report_pct(lg['v0_profit_conversion_rate_pct'])})**이 V2 비수익에서 V0 양의 수익으로 전환됐어. MFE<20% / MFE>=20%의 전환은 **{int(below20['v0_profit_conversion_count'])}건 ({_report_pct(below20['v0_profit_conversion_rate_pct'])}) / {int(ge20['v0_profit_conversion_count'])}건 ({_report_pct(ge20['v0_profit_conversion_rate_pct'])})**이야.

### Q6. Soft와 Hard winner clipping 진단

Soft와 Hard는 MFE 분포가 다른 cohort라 absolute giveback만으로 winner 훼손 우선순위를 결론내리지 않아.

- Soft: V2 mean/median return {_report_pct(soft['v2_mean_terminal_return_pct'])} / {_report_pct(soft['v2_median_terminal_return_pct'])} → V0 {_report_pct(soft['v0_mean_terminal_return_pct'])} / {_report_pct(soft['v0_median_terminal_return_pct'])}; paired mean/median delta {_report_pct(soft['mean_return_delta_pct'])} / {_report_pct(soft['median_return_delta_pct'])}; V2→V0 >=+50 **{int(soft['v2_ge_50_count'])}/{int(soft['v0_ge_50_count'])}건**, >=+100 **{int(soft['v2_ge_100_count'])}/{int(soft['v0_ge_100_count'])}건**.
- Hard: V2 mean/median return {_report_pct(hard['v2_mean_terminal_return_pct'])} / {_report_pct(hard['v2_median_terminal_return_pct'])} → V0 {_report_pct(hard['v0_mean_terminal_return_pct'])} / {_report_pct(hard['v0_median_terminal_return_pct'])}; paired mean/median delta {_report_pct(hard['mean_return_delta_pct'])} / {_report_pct(hard['median_return_delta_pct'])}; V2→V0 >=+50 **{int(hard['v2_ge_50_count'])}/{int(hard['v0_ge_50_count'])}건**, >=+100 **{int(hard['v2_ge_100_count'])}/{int(hard['v0_ge_100_count'])}건**.
- V0 mean/median MFE는 Soft {_report_pct(soft['v0_mean_mfe_pct'])} / {_report_pct(soft['v0_median_mfe_pct'])}, Hard {_report_pct(hard['v0_mean_mfe_pct'])} / {_report_pct(hard['v0_median_mfe_pct'])}; mean/median giveback은 Soft {_report_pct(soft['v0_mean_giveback_pp'])} / {_report_pct(soft['v0_median_giveback_pp'])}, Hard {_report_pct(hard['v0_mean_giveback_pp'])} / {_report_pct(hard['v0_median_giveback_pp'])}야.
- Hard는 absolute giveback이 크지만 MFE 자체가 훨씬 높은 cohort이고 matched outcome 기준 V2 대비 평균 terminal return이 크게 개선됐어. Soft는 평균 terminal return이 소폭 개선됐지만 V2에서 >=+50/+100으로 끝난 거래가 V0에서는 각각 **{int(soft['v0_ge_50_count'])}/{int(soft['v0_ge_100_count'])}건**으로 줄어 winner clipping의 우선 추가 연구 대상이야. 이것은 Soft rule 수정 지시가 아니야.

### Q7. 현재 V3 내부 MCAP bucket 비교

- Bucket A (100B~<300B): {int(bucket_a['total_trades'])}건, 승률 {_report_pct(bucket_a['positive_rate_pct'])}, 평균수익률 {_report_pct(bucket_a['mean_return'])}, <=-40% {int(bucket_a['tail_le_-40_count'])}건 ({_report_pct(bucket_a['tail_le_-40_rate_pct'])})
- Bucket B (>=300B): {int(bucket_b['total_trades'])}건, 승률 {_report_pct(bucket_b['positive_rate_pct'])}, 평균수익률 {_report_pct(bucket_b['mean_return'])}, <=-40% {int(bucket_b['tail_le_-40_count'])}건 ({_report_pct(bucket_b['tail_le_-40_rate_pct'])})

이 bucket 결과만으로 V3와 기존 CONTROL의 차이를 small-cap 원인으로 단정하지 않아. 두 bucket 모두 V3의 유동성·가격 필터 제거와 V0 exit가 적용되어 있고, 이는 현재 V3 내부 비교용 diagnostic이야.

### Q8. 다음 V1 연구의 우선 문제 분류

데이터상 다음 연구/진단 우선순위는 **1) MFE<20% loss control 문제, 2) Soft Exit winner clipping 문제, 3) small-cap universe 문제, 4) Hard Exit 추가 검토, 5) 복합 interaction 문제**로 분류해. 이는 전략 수정 우선순위가 아니야. Hard를 문제가 없다고 확정하지 않지만 현재 matched 결과에서 Soft보다 우선적인 문제라는 근거는 없어.

## 실험 계약

- 기간: `2021-04-01` evaluation start, `2026-08-14` signal cutoff, `2026-08-21` execution support end, final valuation `2026-08-21 CLOSE`.
- CONTROL 973개 진입을 각각 독립 replay했어. V0에서 앞선 거래가 이후 CONTROL entry와 겹쳐도 entry를 삭제·이동하지 않았어. 따라서 실제 실행 sequence가 아닌 matched-entry exit experiment이야.
- V0는 기존 V3 V0 함수/계약을 그대로 재사용했어: daily HIGH HWM/MFE, daily LOW MAE, daily CLOSE breach, latest completed weekly FAST, next local trading day OPEN, no look-ahead, cutoff 강제매도 없음.
- 이번 작업에서 새 entry scan, threshold tuning, Loss Guard 재도입, V1 구현, portfolio/Julia 실행은 하지 않았어.

## 파일

- `matched_control_entries_v2_vs_v0.csv`: 973개 matched row
- `matched_control_entries_v2_vs_v0_summary.json`: A/B 전체 summary와 계약
- `v0_mfe_tier_diagnostics.csv`
- `v2_loss_guard_subset_diagnostics.csv`
- `v0_exit_reason_diagnostics.csv`
- `v3_market_cap_bucket_diagnostics.csv`

기존 V3 거래 artifact는 읽기만 했고 재생성하지 않았어.
"""


def run_analysis() -> dict[str, Any]:
    control = pd.read_csv(CONTROL_TRADES_PATH)
    if len(control) != 973:
        raise AssertionError(f"expected 973 CONTROL rows, got {len(control)}")
    v3_trades = pd.read_csv(V3_TRADES_PATH)
    if len(v3_trades) != 1578:
        raise AssertionError(f"expected 1578 V3 trades, got {len(v3_trades)}")
    control_summary = _read_json(CONTROL_SUMMARY_PATH)
    v3_summary = _read_json(V3_SUMMARY_PATH)
    if [control_summary.get("common_start_date"), control_summary.get("signal_end_date"), control_summary.get("execution_support_end_date")] != ["2021-04-01", "2026-08-14", "2026-08-21"]:
        raise AssertionError("CONTROL period does not match frozen period")
    if [v3_summary.get("evaluation_start"), v3_summary.get("signal_cutoff"), v3_summary.get("execution_support_end")] != ["2021-04-01", "2026-08-14", "2026-08-21"]:
        raise AssertionError("V3 period does not match frozen period")

    repository = build_repository_v2(ROOT, end=v3.SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=v3.SUPPORT_END)
    states, daily_by_ticker, state_errors = _state_index(control, loader)
    matched = build_matched(control, daily_by_ticker, states)
    if len(matched) != 973:
        raise AssertionError(f"expected 973 matched rows, got {len(matched)}")
    ordered_control = control.sort_values(["ticker", "entry_signal_date", "trade_sequence", "trade_id"], kind="mergesort")
    if not (matched["entry_execution_date"].astype(str) == ordered_control["entry_execution_date"].astype(str).to_numpy()).all():
        raise AssertionError("matched entry dates do not preserve CONTROL entries")
    if not (pd.to_numeric(matched["entry_open"]) == pd.to_numeric(ordered_control["entry_open"]).to_numpy()).all():
        raise AssertionError("matched entry prices do not preserve CONTROL entries")

    overall = _comparison_stats(matched)
    mfe = build_mfe_diagnostics(matched)
    loss_guard = build_loss_guard_diagnostics(matched)
    exits = build_exit_diagnostics(matched)
    buckets = build_bucket_diagnostics(v3_trades)
    summary: dict[str, Any] = {
        "work_id": "FASTCORE_V3_EXIT_AB_V00_FIX01",
        "status": "COMPLETE",
        "evaluation_start": "2021-04-01",
        "signal_cutoff": "2026-08-14",
        "execution_support_end": "2026-08-21",
        "final_valuation": "2026-08-21 CLOSE",
        "matched_entry_summary": overall,
        "matched_control_rows": len(control),
        "matched_rows": len(matched),
        "control_work_id": control_summary.get("work_id"),
        "current_v3_work_id": v3_summary.get("work_id"),
        "control_entry_filter_re_evaluated": False,
        "independent_trade_replay": True,
        "overlap_removal": False,
        "state_weekly_evaluation_error_count": state_errors,
        "v3_bucket_total_trades": len(v3_trades),
        "v3_bucket_sum_total_trades": int(buckets["total_trades"].sum()),
        "network_requests": 0,
        "production_strategy_modified": False,
        "existing_v3_artifact_modified": False,
        "julia_executed": False,
        "source_artifacts": {
            "control_trades": str(CONTROL_TRADES_PATH.relative_to(ROOT)),
            "control_summary": str(CONTROL_SUMMARY_PATH.relative_to(ROOT)),
            "v3_trades": str(V3_TRADES_PATH.relative_to(ROOT)),
            "v3_summary": str(V3_SUMMARY_PATH.relative_to(ROOT)),
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
    mfe.to_csv(MFE_PATH, index=False, lineterminator="\n")
    loss_guard.to_csv(LOSS_GUARD_PATH, index=False, lineterminator="\n")
    exits.to_csv(EXIT_PATH, index=False, lineterminator="\n")
    buckets.to_csv(BUCKET_PATH, index=False, lineterminator="\n")
    _write_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(build_report(summary, mfe, loss_guard, exits, buckets), encoding="utf-8")
    return {"summary": summary, "matched": matched, "mfe": mfe, "loss_guard": loss_guard, "exits": exits, "buckets": buckets}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the offline exit A/B diagnostic")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_analysis()
        result["summary"]["network_requests"] = audit.request_count
        _write_json(SUMMARY_PATH, result["summary"])
        print(json.dumps({
            "status": result["summary"]["status"],
            "matched_rows": result["summary"]["matched_rows"],
            "v3_bucket_total_trades": result["summary"]["v3_bucket_total_trades"],
            "network_requests": audit.request_count,
        }, ensure_ascii=False), flush=True)
        return 0 if audit.request_count == 0 else 1
    except Exception as exc:
        print(f"FASTCORE V3 EXIT A/B BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
