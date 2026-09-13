#!/usr/bin/env python3
"""Diagnostic study of pre-winner hard-failure thresholds.

This script is deliberately not a V1 implementation.  It reads the
authoritative FIX01 matched-entry artifact, reconstructs only the local daily
OHLC path needed for retrospective diagnostics, and leaves all existing V0,
V3, CONTROL, and production artifacts untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections import defaultdict
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
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader


V00_OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_hard_failure_diagnostic_v00"
FIX01_OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix01"
FIX02_OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix02"
# Keep the public output constant pointed at the new FIX02 destination so a
# normal runner invocation cannot overwrite the completed V00/FIX01 diagnostics.
OUT_DIR = FIX02_OUT_DIR

MATCHED_PATH = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0.csv"
MATCHED_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0_summary.json"
V3_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_v3_simple_v00/fastcore_v3_trades.csv"

THRESHOLDS = (-15, -20, -25, -30, -35, -40, -45, -50, -55, -60)
LOSS_GUARD_REASON = "LOSS_GUARD_CLOSE_LE_NEG_15"


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise RuntimeError(f"offline pre-winner diagnostic guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise RuntimeError(f"offline pre-winner diagnostic guard blocked socket connect_ex: {address!r}")

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


def _lifecycle(row: Mapping[str, Any]) -> IdentityLifecycle:
    return IdentityLifecycle(
        ticker=str(row["ticker"]).zfill(6),
        isu_cd=str(row["isu_cd"]),
        market=str(row["market"]),
        effective_from=_date(row["identity_effective_from"]),
        effective_to=min(_date(row["identity_effective_to"]), v3.SUPPORT_END),
    )


def _identity_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        str(row[field])
        for field in ("ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to")
    )


class _TargetedRawStore:
    """Read-only raw-store view containing only the requested tickers.

    The canonical KRX partitions are still read and verified through
    ``KrxRawStockStore`` exactly once.  This wrapper avoids the repository
    reader's repeated per-ticker partition-position loop during a large
    offline diagnostic, while leaving the production Repository V2 code
    untouched.
    """

    def __init__(self, frames_by_ticker: Mapping[str, pd.DataFrame]) -> None:
        self._frames_by_ticker = {
            str(ticker).zfill(6): frame.sort_values("date", kind="mergesort").reset_index(drop=True)
            for ticker, frame in frames_by_ticker.items()
        }

    def load_ticker(
        self,
        ticker: str,
        start: Any | None = None,
        end: Any | None = None,
    ) -> pd.DataFrame:
        key = str(ticker).zfill(6)
        frame = self._frames_by_ticker.get(key)
        if frame is None:
            return pd.DataFrame(columns=list(RAW_COLUMNS))
        result = frame
        if start is not None:
            result = result.loc[result["date"] >= pd.Timestamp(start).normalize()]
        if end is not None:
            result = result.loc[result["date"] <= pd.Timestamp(end).normalize()]
        result = result.copy()
        result.attrs["ticker"] = key
        return result


def _load_target_raw_frames(root: Path, tickers: set[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Validate canonical raw partitions once and retain only target tickers."""

    store = KrxRawStockStore(root / "data/market/raw/krx_stocks/v01")
    by_ticker: dict[str, list[pd.DataFrame]] = defaultdict(list)
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    for manifest in store.list_manifest():
        if manifest.get("status") != "COMPLETE":
            continue
        day = pd.Timestamp(manifest["date"]).normalize()
        if day < start_ts or day > end_ts:
            continue
        frame = store.load_snapshot(str(manifest["market"]), manifest["date"])
        normalized_tickers = frame["ticker"].astype(str).str.zfill(6)
        relevant = frame.loc[normalized_tickers.isin(tickers), list(RAW_COLUMNS)].copy()
        if relevant.empty:
            continue
        relevant["ticker"] = normalized_tickers.loc[relevant.index]
        for ticker, group in relevant.groupby("ticker", sort=False):
            by_ticker[str(ticker)].append(group.reset_index(drop=True))
    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        groups = by_ticker.get(ticker, [])
        if groups:
            combined = pd.concat(groups, ignore_index=True).sort_values("date", kind="mergesort")
            if combined["date"].duplicated().any():
                raise RuntimeError(f"duplicate raw dates for {ticker}")
            result[ticker] = combined.reset_index(drop=True)
    return result


def _prewinner_path(row: Mapping[str, Any], daily_full: pd.DataFrame) -> dict[str, Any]:
    daily = clip_to_identity_lifecycle(daily_full, _lifecycle(row))
    if daily is None or daily.empty:
        raise RuntimeError(f"empty daily path for {row['control_trade_id']}")
    entry_date = _date(row["entry_execution_date"])
    if entry_date not in daily.index:
        raise RuntimeError(f"entry date missing for {row['control_trade_id']}: {entry_date.date()}")
    entry_open = float(row["entry_open"])
    if abs(float(daily.loc[entry_date, "open"]) - entry_open) > 1e-8:
        raise AssertionError(f"entry OPEN mismatch for {row['control_trade_id']}")

    hwm = entry_open
    first_mfe20_date: pd.Timestamp | None = None
    prewinner: list[dict[str, Any]] = []
    observation_window = daily.loc[(daily.index >= entry_date) & (daily.index <= v3.SUPPORT_END)]
    for date, bar in observation_window.iterrows():
        date = _date(date)
        hwm = max(hwm, float(bar["high"]))
        running_mfe = (hwm / entry_open - 1.0) * 100.0
        # Same-day ordering: update HIGH/HWM first, then exclude the first
        # +20% day from the pre-winner diagnostic population.
        if running_mfe >= 20.0:
            first_mfe20_date = date
            break
        prewinner.append({
            "date": date,
            "close_return": (float(bar["close"]) / entry_open - 1.0) * 100.0,
            "low_return": (float(bar["low"]) / entry_open - 1.0) * 100.0,
        })

    recovery_class = "RECOVERY" if first_mfe20_date is not None else "NEVER_WINNER"
    if prewinner:
        min_close = min(prewinner, key=lambda item: (item["close_return"], item["date"]))
        min_low = min(prewinner, key=lambda item: (item["low_return"], item["date"]))
        prewinner_end = prewinner[-1]["date"]
    else:
        min_close = {"date": None, "close_return": None}
        min_low = {"date": None, "low_return": None}
        prewinner_end = None

    first_days = None
    if first_mfe20_date is not None:
        first_days = int((daily.index <= first_mfe20_date).sum() - (daily.index < entry_date).sum() - 1)

    return {
        "ticker": str(row["ticker"]).zfill(6),
        "name": str(row["name"]),
        "control_trade_id": str(row["control_trade_id"]),
        "control_trade_sequence": int(row["control_trade_sequence"]),
        "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "entry_open": entry_open,
        "v0_mfe": float(row["v0_mfe"]),
        "recovery_class": recovery_class,
        "first_mfe20_date": first_mfe20_date.strftime("%Y-%m-%d") if first_mfe20_date is not None else None,
        "days_to_first_mfe20": first_days,
        "prewinner_start_date": entry_date.strftime("%Y-%m-%d"),
        "prewinner_end_date": prewinner_end.strftime("%Y-%m-%d") if prewinner_end is not None else None,
        "prewinner_min_close_return_pct": round(float(min_close["close_return"]), 6) if min_close["close_return"] is not None else None,
        "prewinner_min_close_date": min_close["date"].strftime("%Y-%m-%d") if min_close["date"] is not None else None,
        "prewinner_min_low_return_pct": round(float(min_low["low_return"]), 6) if min_low["low_return"] is not None else None,
        "prewinner_min_low_date": min_low["date"].strftime("%Y-%m-%d") if min_low["date"] is not None else None,
        "_prewinner_observations": prewinner,
        "_identity_key": _identity_key(row),
    }


def build_trade_diagnostics(matched: pd.DataFrame, daily_by_ticker: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in matched.to_dict("records"):
        record = _prewinner_path(row, daily_by_ticker[str(row["ticker"])])
        record.pop("_prewinner_observations", None)
        record.pop("_identity_key", None)
        record["v2_exit_reason"] = str(row["v2_exit_reason"])
        record["v0_terminal_return"] = float(row["v0_terminal_return"])
        record["v0_holding_days"] = int(row["v0_holding_days"])
        records.append(record)
    return pd.DataFrame(records).sort_values(["ticker", "entry_execution_date", "control_trade_sequence"], kind="mergesort").reset_index(drop=True)


def build_paths(matched: pd.DataFrame, daily_by_ticker: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}
    for row in matched.to_dict("records"):
        path = _prewinner_path(row, daily_by_ticker[str(row["ticker"])])
        paths[str(row["control_trade_id"])] = path
    return paths


def _population(row: Mapping[str, Any], population: str) -> bool:
    if population == "ALL_973":
        return True
    if population == "LOSS_GUARD_590":
        return str(row["v2_exit_reason"]) == LOSS_GUARD_REASON
    raise ValueError(population)


def _percentile_stats(values: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {key: None for key in ["minimum", "p05", "p10", "p25", "median", "p75", "p90", "p95", "maximum", "mean"]}
    return {
        "minimum": round(float(values.min()), 6),
        "p05": round(float(values.quantile(0.05)), 6),
        "p10": round(float(values.quantile(0.10)), 6),
        "p25": round(float(values.quantile(0.25)), 6),
        "median": round(float(values.median()), 6),
        "p75": round(float(values.quantile(0.75)), 6),
        "p90": round(float(values.quantile(0.90)), 6),
        "p95": round(float(values.quantile(0.95)), 6),
        "maximum": round(float(values.max()), 6),
        "mean": round(float(values.mean()), 6),
    }


BIN_LABELS = (
    "> -10%", "-10% to > -15%", "-15% to > -20%", "-20% to > -25%",
    "-25% to > -30%", "-30% to > -35%", "-35% to > -40%", "-40% to > -45%",
    "-45% to > -50%", "-50% to > -55%", "-55% to > -60%", "<= -60%",
)


def _bin_label(value: float) -> str:
    if value > -10:
        return BIN_LABELS[0]
    lower = -10
    for index in range(1, 11):
        upper = lower - 5
        if value <= lower and value > upper:
            return BIN_LABELS[index]
        lower = upper
    return BIN_LABELS[-1]


def build_distribution(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for population in ("ALL_973", "LOSS_GUARD_590"):
        population_frame = trades[trades.apply(lambda row: _population(row, population), axis=1)]
        for recovery_class in ("RECOVERY", "NEVER_WINNER"):
            cohort = population_frame[population_frame["recovery_class"] == recovery_class]
            for metric, column in (("prewinner_min_close_return_pct", "prewinner_min_close_return_pct"), ("prewinner_min_low_return_pct", "prewinner_min_low_return_pct")):
                for stat, value in _percentile_stats(cohort[column]).items():
                    rows.append({
                        "population": population,
                        "recovery_class": recovery_class,
                        "metric": metric,
                        "stat": stat,
                        "value": value,
                    })
        for metric in ("prewinner_min_close_return_pct", "prewinner_min_low_return_pct"):
            population_frame = population_frame.copy()
            population_frame["bin"] = population_frame[metric].map(lambda value: _bin_label(float(value)) if pd.notna(value) else "NO_PREWINNER_OBSERVATION")
            total = len(population_frame)
            for label in BIN_LABELS:
                bucket = population_frame[population_frame["bin"] == label]
                recovery_count = int((bucket["recovery_class"] == "RECOVERY").sum())
                never_count = int((bucket["recovery_class"] == "NEVER_WINNER").sum())
                rows.append({
                    "population": population,
                    "recovery_class": "ALL_CLASSES",
                    "metric": f"{metric}_5pct_bin",
                    "stat": label,
                    "value": int(len(bucket)),
                    "total_count": int(len(bucket)),
                    "total_rate_pct": round(len(bucket) / total * 100.0, 6) if total else 0.0,
                    "recovery_count": recovery_count,
                    "recovery_rate_pct": round(recovery_count / total * 100.0, 6) if total else 0.0,
                    "never_winner_count": never_count,
                    "never_winner_rate_pct": round(never_count / total * 100.0, 6) if total else 0.0,
                    "recovery_within_bin_rate_pct": round(recovery_count / len(bucket) * 100.0, 6) if len(bucket) else 0.0,
                })
    return pd.DataFrame(rows)


def _count_rate(count: int, total: int) -> tuple[int, float]:
    return count, round(count / total * 100.0, 6) if total else 0.0


def _metric(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _aggregate_returns(frame: pd.DataFrame, returns: pd.Series, holding: pd.Series) -> dict[str, Any]:
    total = len(frame)
    positive = int((returns > 0).sum())
    result: dict[str, Any] = {
        "trades": total,
        "positive_count": positive,
        "positive_rate_pct": _count_rate(positive, total)[1],
        "mean_terminal_return_pct": round(float(returns.mean()), 6) if total else None,
        "median_terminal_return_pct": round(float(returns.median()), 6) if total else None,
        "mean_holding_days": round(float(holding.mean()), 6) if total else None,
        "median_holding_days": round(float(holding.median()), 6) if total else None,
    }
    for threshold in [20, 30, 50, 100]:
        count, rate = _count_rate(int((returns >= threshold).sum()), total)
        result[f"ge_{threshold}_count"] = count
        result[f"ge_{threshold}_rate_pct"] = rate
    for threshold in [20, 30, 40, 50, 60]:
        count, rate = _count_rate(int((returns <= -threshold).sum()), total)
        result[f"le_-{threshold}_count"] = count
        result[f"le_-{threshold}_rate_pct"] = rate
    return result


def _threshold_impact(row: Mapping[str, Any], path: Mapping[str, Any], threshold: int, daily: pd.DataFrame) -> dict[str, Any]:
    observations = path["_prewinner_observations"]
    breach = next((item for item in observations if float(item["close_return"]) <= threshold), None)
    next_date = None
    hard_failure_return = None
    hard_failure_holding = None
    if breach is not None:
        next_date = v3._next_session(daily, breach["date"])
        if next_date is not None:
            hard_failure_return = round((float(daily.loc[next_date, "open"]) / float(row["entry_open"]) - 1.0) * 100.0, 2)
            entry_date = _date(row["entry_execution_date"])
            hard_failure_holding = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= next_date)]))
    recovery = path["recovery_class"] == "RECOVERY"
    executable = breach is not None and next_date is not None
    return {
        "threshold_pct": threshold,
        "ticker": str(row["ticker"]).zfill(6),
        "name": str(row["name"]),
        "control_trade_id": str(row["control_trade_id"]),
        "entry_execution_date": str(row["entry_execution_date"]),
        "entry_open": float(row["entry_open"]),
        "recovery_class": path["recovery_class"],
        "v2_exit_reason": str(row["v2_exit_reason"]),
        "prewinner_breach": breach is not None,
        "prewinner_breach_date": breach["date"].strftime("%Y-%m-%d") if breach is not None else None,
        "next_local_open_available": next_date is not None,
        "hard_failure_exit_date": next_date.strftime("%Y-%m-%d") if next_date is not None else None,
        "hard_failure_exit_return": hard_failure_return,
        "original_v0_terminal_return": float(row["v0_terminal_return"]),
        "return_delta_hard_failure_minus_v0": round(hard_failure_return - float(row["v0_terminal_return"]), 2) if hard_failure_return is not None else None,
        "original_v0_mfe": float(row["v0_mfe"]),
        "hard_failure_holding_days": hard_failure_holding,
        "original_v0_holding_days": int(row["v0_holding_days"]),
        "recovery_killed": bool(recovery and executable),
        "failed_trade_captured": bool((not recovery) and executable),
    }


def _hypothetical_summary(impacts: pd.DataFrame, matched: pd.DataFrame, threshold: int) -> dict[str, Any]:
    executable = impacts["hard_failure_exit_return"].notna()
    replacement = pd.to_numeric(impacts["hard_failure_exit_return"], errors="coerce")
    baseline_return = pd.to_numeric(impacts["original_v0_terminal_return"], errors="coerce")
    hypothetical_return = baseline_return.where(~executable, replacement)
    baseline_holding = pd.to_numeric(impacts["original_v0_holding_days"], errors="coerce")
    hypothetical_holding = baseline_holding.where(~executable, pd.to_numeric(impacts["hard_failure_holding_days"], errors="coerce"))
    total = len(impacts)
    recovery = impacts[impacts["recovery_class"] == "RECOVERY"]
    never = impacts[impacts["recovery_class"] == "NEVER_WINNER"]
    recovery_breach = int(recovery["prewinner_breach"].sum())
    recovery_killed = int(recovery["recovery_killed"].sum())
    never_breach = int(never["prewinner_breach"].sum())
    never_captured = int(never["failed_trade_captured"].sum())
    row: dict[str, Any] = {
        "threshold_pct": threshold,
        "recovery_breach_count": recovery_breach,
        "recovery_breach_rate_pct": _count_rate(recovery_breach, len(recovery))[1],
        "recovery_killed_count": recovery_killed,
        "recovery_killed_rate_pct": _count_rate(recovery_killed, len(recovery))[1],
        "recovery_survived_without_breach_count": len(recovery) - recovery_breach,
        "recovery_survived_without_breach_rate_pct": _count_rate(len(recovery) - recovery_breach, len(recovery))[1],
        "recovery_breach_without_next_open_count": recovery_breach - recovery_killed,
        "never_winner_breach_count": never_breach,
        "never_winner_breach_rate_pct": _count_rate(never_breach, len(never))[1],
        "failed_trade_captured_count": never_captured,
        "failed_trade_captured_rate_pct": _count_rate(never_captured, len(never))[1],
        "failed_trade_missed_count": len(never) - never_captured,
        "failed_trade_missed_rate_pct": _count_rate(len(never) - never_captured, len(never))[1],
        "never_winner_breach_without_next_open_count": never_breach - never_captured,
        "failure_captures_per_recovery_killed": round(never_captured / recovery_killed, 6) if recovery_killed else None,
    }
    baseline = _aggregate_returns(matched, pd.to_numeric(matched["v0_terminal_return"]), pd.to_numeric(matched["v0_holding_days"]))
    hypothetical = _aggregate_returns(matched, hypothetical_return, hypothetical_holding)
    for key, value in hypothetical.items():
        row[f"hypothetical_{key}"] = value
    for key, value in baseline.items():
        row[f"baseline_v0_{key}"] = value
    for key in ["positive_rate_pct", "mean_terminal_return_pct", "median_terminal_return_pct", "mean_holding_days", "median_holding_days"]:
        row[f"delta_{key}"] = round(
            float(row[f"hypothetical_{key}"]) - float(row[f"baseline_v0_{key}"]),
            6,
        )
    for threshold_key in ["ge_20", "ge_30", "ge_50", "ge_100", "le_-20", "le_-30", "le_-40", "le_-50", "le_-60"]:
        row[f"delta_{threshold_key}_count"] = row[f"hypothetical_{threshold_key}_count"] - row[f"baseline_v0_{threshold_key}_count"]
        row[f"delta_{threshold_key}_rate_pct"] = round(row[f"hypothetical_{threshold_key}_rate_pct"] - row[f"baseline_v0_{threshold_key}_rate_pct"], 6)
    return row


def build_sweep_and_impacts(matched: pd.DataFrame, paths: Mapping[str, Mapping[str, Any]], daily_by_ticker: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    impact_rows: list[dict[str, Any]] = []
    sweep_rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        threshold_impacts = []
        for row in matched.to_dict("records"):
            impact = _threshold_impact(row, paths[str(row["control_trade_id"])], threshold, daily_by_ticker[str(row["ticker"])])
            impact_rows.append(impact)
            threshold_impacts.append(impact)
        sweep_rows.append(_hypothetical_summary(pd.DataFrame(threshold_impacts), matched, threshold))
    return pd.DataFrame(sweep_rows), pd.DataFrame(impact_rows)


def _fmt(value: Any, suffix: str = "%") -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.6f}{suffix}"


def _row(sweep: pd.DataFrame, threshold: int) -> pd.Series:
    return sweep[sweep["threshold_pct"] == threshold].iloc[0]


def build_report(
    summary: Mapping[str, Any],
    distribution: pd.DataFrame,
    sweep: pd.DataFrame,
    output_dir: Path,
) -> str:
    trades = pd.read_csv(output_dir / "prewinner_trade_diagnostics.csv")
    impacts = pd.read_csv(output_dir / "prewinner_threshold_trade_impacts.csv")
    loss_guard = trades[trades["v2_exit_reason"] == LOSS_GUARD_REASON]
    recovery = trades[trades["recovery_class"] == "RECOVERY"]
    never = trades[trades["recovery_class"] == "NEVER_WINNER"]

    def stats(population: str, recovery_class: str, metric: str) -> dict[str, Any]:
        selected = distribution[
            (distribution["population"] == population)
            & (distribution["recovery_class"] == recovery_class)
            & (distribution["metric"] == metric)
        ]
        return {str(row["stat"]): row["value"] for row in selected.to_dict("records")}

    def stats_line(population: str, recovery_class: str, metric: str) -> str:
        values = stats(population, recovery_class, metric)
        return (
            f"{population} {recovery_class}: p10 {_fmt(values['p10'])}, "
            f"p25 {_fmt(values['p25'])}, median {_fmt(values['median'])}, "
            f"p75 {_fmt(values['p75'])}, p90 {_fmt(values['p90'])}, "
            f"worst {_fmt(values['minimum'])}, mean {_fmt(values['mean'])}"
        )

    def close_bin_lines(population: str) -> list[str]:
        selected = distribution[
            (distribution["population"] == population)
            & (distribution["metric"] == "prewinner_min_close_return_pct_5pct_bin")
        ]
        return [
            "| "
            f"{row['stat']} | {int(row['total_count'])}/{_fmt(row['total_rate_pct'])} | "
            f"{int(row['recovery_count'])}/{_fmt(row['recovery_rate_pct'])} | "
            f"{int(row['never_winner_count'])}/{_fmt(row['never_winner_rate_pct'])} | "
            f"{_fmt(row['recovery_within_bin_rate_pct'])} |"
            for row in selected.to_dict("records")
        ]

    def close_bin_counts(population: str, label: str) -> str:
        selected = distribution[
            (distribution["population"] == population)
            & (distribution["metric"] == "prewinner_min_close_return_pct_5pct_bin")
            & (distribution["stat"] == label)
        ]
        row = selected.iloc[0]
        return f"{int(row['recovery_count'])}/{int(row['never_winner_count'])}"

    def impact_group_line(threshold: int, cohort: str) -> str:
        selected = impacts[
            (impacts["threshold_pct"] == threshold)
            & (impacts["recovery_class"] == cohort)
        ]
        executable = selected[selected["hard_failure_exit_return"].notna()]
        if executable.empty:
            return f"| {threshold}% | {cohort} | 0 | n/a | n/a | n/a | n/a |"
        return (
            f"| {threshold}% | {cohort} | {len(executable)} | "
            f"{_fmt(executable['hard_failure_exit_return'].mean())} | "
            f"{_fmt(executable['hard_failure_exit_return'].median())} | "
            f"{_fmt(executable['return_delta_hard_failure_minus_v0'].mean())} | "
            f"{_fmt(executable['original_v0_mfe'].mean())} |"
        )

    q4_lines = []
    for threshold in [-15, -20, -25, -30, -35, -40]:
        item = _row(sweep, threshold)
        lg = impacts[
            (impacts["threshold_pct"] == threshold)
            & (impacts["v2_exit_reason"] == LOSS_GUARD_REASON)
        ]
        lg_rec = lg[lg["recovery_class"] == "RECOVERY"]
        lg_nev = lg[lg["recovery_class"] == "NEVER_WINNER"]
        q4_lines.append(
            f"- {threshold}%: ALL RECOVERY kill "
            f"{int(item['recovery_killed_count'])}/{_fmt(item['recovery_killed_rate_pct'])}, "
            f"ALL NEVER_WINNER capture "
            f"{int(item['failed_trade_captured_count'])}/{_fmt(item['failed_trade_captured_rate_pct'])}; "
            f"Loss Guard RECOVERY "
            f"{int(lg_rec['recovery_killed'].sum())}/{_fmt(lg_rec['recovery_killed'].mean() * 100.0)}, "
            f"Loss Guard NEVER_WINNER "
            f"{int(lg_nev['failed_trade_captured'].sum())}/{_fmt(lg_nev['failed_trade_captured'].mean() * 100.0)}"
        )
    q5_lines = []
    for threshold in THRESHOLDS:
        item = _row(sweep, threshold)
        q5_lines.append(
            f"| {threshold}% | {int(item['recovery_killed_count'])}/{_fmt(item['recovery_killed_rate_pct'])} | "
            f"{int(item['failed_trade_captured_count'])}/{_fmt(item['failed_trade_captured_rate_pct'])} | "
            f"{int(item['hypothetical_positive_count'])}/{_fmt(item['hypothetical_positive_rate_pct'])} | "
            f"{_fmt(item['hypothetical_mean_terminal_return_pct'])} | "
            f"{_fmt(item['hypothetical_median_terminal_return_pct'])} | "
            f"{int(item['hypothetical_ge_20_count'])}/{int(item['hypothetical_ge_30_count'])}/"
            f"{int(item['hypothetical_ge_50_count'])}/{int(item['hypothetical_ge_100_count'])} | "
            f"{int(item['hypothetical_le_-20_count'])}/{int(item['hypothetical_le_-30_count'])}/"
            f"{int(item['hypothetical_le_-40_count'])}/{int(item['hypothetical_le_-50_count'])}/"
            f"{int(item['hypothetical_le_-60_count'])} | "
            f"{_fmt(item['hypothetical_mean_holding_days'], suffix='d')} | "
            f"{_fmt(item['delta_mean_terminal_return_pct'])} |"
        )

    baseline = _row(sweep, -15)
    threshold_30 = _row(sweep, -30)
    lg30 = impacts[
        (impacts["threshold_pct"] == -30)
        & (impacts["v2_exit_reason"] == LOSS_GUARD_REASON)
    ]
    lg30_recovery = lg30[lg30["recovery_class"] == "RECOVERY"]
    tested_threshold_count = len(THRESHOLDS)
    baseline_mean = float(baseline["baseline_v0_mean_terminal_return_pct"])
    fixed_threshold_mean_improvement_count = int(
        (pd.to_numeric(sweep["hypothetical_mean_terminal_return_pct"]) > baseline_mean).sum()
    )
    q6 = (
        "**현재 데이터만으로는 NO.** 단일 고정 Pre-Winner Hard Failure 기준선은 아직 확인되지 않았다. "
        f"-30%는 전체 RECOVERY {int(threshold_30['recovery_killed_count'])}건/{_fmt(threshold_30['recovery_killed_rate_pct'])}를 제거하고, "
        f"Loss Guard RECOVERY에서는 {int(lg30_recovery['recovery_killed'].sum())}건/"
        f"{_fmt(lg30_recovery['recovery_killed'].mean() * 100.0)}를 제거한다. "
        f"-30% hypothetical positive rate는 {_fmt(threshold_30['hypothetical_positive_rate_pct'])}, "
        f"mean return은 {_fmt(threshold_30['hypothetical_mean_terminal_return_pct'])}이고, "
        f"V0는 positive rate {_fmt(baseline['baseline_v0_positive_rate_pct'])}, "
        f"mean {_fmt(baseline['baseline_v0_mean_terminal_return_pct'])}다. "
        f"테스트한 fixed threshold {tested_threshold_count}개 중 V0 mean을 개선한 것은 "
        f"{fixed_threshold_mean_improvement_count}개다. 따라서 -30%를 Hard Failure candidate로 채택하지 않는다. "
        "-25~-30%는 즉시 Hard Exit 기준이 아니라 향후 FAILURE ARMED 설계에서 가격 훼손 영역으로 참고할 가치가 있을 뿐이며, "
        "이번 FIX에서는 어떤 신규 threshold도 전략 parameter로 확정하지 않는다."
    )

    fix01_summary = _read_json(FIX01_OUT_DIR / "prewinner_hard_failure_summary.json")
    fix01_sweep = pd.read_csv(FIX01_OUT_DIR / "prewinner_threshold_sweep.csv")
    fix01_30 = _row(fix01_sweep, -30)
    fix01_improvement_count = int(fix01_summary["fixed_threshold_mean_improvement_count"])
    horizon_impact = (
        f"- RECOVERY: {fix01_summary['recovery_count']} → {len(recovery)} "
        f"(delta {len(recovery) - int(fix01_summary['recovery_count']):+d})\n"
        f"- NEVER_WINNER: {fix01_summary['never_winner_count']} → {len(never)} "
        f"(delta {len(never) - int(fix01_summary['never_winner_count']):+d})\n"
        f"- Loss Guard RECOVERY: {fix01_summary['loss_guard_recovery_count']} → "
        f"{len(loss_guard[loss_guard['recovery_class'] == 'RECOVERY'])} "
        f"(delta {len(loss_guard[loss_guard['recovery_class'] == 'RECOVERY']) - int(fix01_summary['loss_guard_recovery_count']):+d})\n"
        f"- Loss Guard NEVER_WINNER: {fix01_summary['loss_guard_never_winner_count']} → "
        f"{len(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER'])} "
        f"(delta {len(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER']) - int(fix01_summary['loss_guard_never_winner_count']):+d})\n"
        f"- -30% RECOVERY kill rate: {_fmt(fix01_30['recovery_killed_rate_pct'])} → "
        f"{_fmt(threshold_30['recovery_killed_rate_pct'])} "
        f"(delta {_fmt(threshold_30['recovery_killed_rate_pct'] - fix01_30['recovery_killed_rate_pct'])})\n"
        f"- -30% failure capture rate: {_fmt(fix01_30['failed_trade_captured_rate_pct'])} → "
        f"{_fmt(threshold_30['failed_trade_captured_rate_pct'])} "
        f"(delta {_fmt(threshold_30['failed_trade_captured_rate_pct'] - fix01_30['failed_trade_captured_rate_pct'])})\n"
        f"- -30% mean return: {_fmt(fix01_30['hypothetical_mean_terminal_return_pct'])} → "
        f"{_fmt(threshold_30['hypothetical_mean_terminal_return_pct'])} "
        f"(delta {_fmt(threshold_30['hypothetical_mean_terminal_return_pct'] - fix01_30['hypothetical_mean_terminal_return_pct'])})\n"
        f"- fixed threshold mean improvement count: {fix01_improvement_count} → "
        f"{fixed_threshold_mean_improvement_count} "
        f"(delta {fixed_threshold_mean_improvement_count - fix01_improvement_count:+d})"
    )
    sweep_comparison_lines = []
    for threshold in THRESHOLDS:
        current = _row(sweep, threshold)
        previous = _row(fix01_sweep, threshold)
        sweep_comparison_lines.append(
            f"| {threshold}% | {int(previous['recovery_killed_count'])} → {int(current['recovery_killed_count'])} | "
            f"{int(previous['failed_trade_captured_count'])} → {int(current['failed_trade_captured_count'])} | "
            f"{_fmt(previous['hypothetical_positive_rate_pct'])} → {_fmt(current['hypothetical_positive_rate_pct'])} | "
            f"{_fmt(previous['hypothetical_mean_terminal_return_pct'])} → {_fmt(current['hypothetical_mean_terminal_return_pct'])} | "
            f"{_fmt(previous['hypothetical_median_terminal_return_pct'])} → {_fmt(current['hypothetical_median_terminal_return_pct'])} | "
            f"{_fmt(current['hypothetical_mean_holding_days'] - previous['hypothetical_mean_holding_days'], suffix='d')} |"
        )

    sweep_deltas = [
        item for item in summary["fix01_comparison"]["threshold_sweep_deltas"]
        if any(
            item[field] != 0
            for field in (
                "recovery_breach_count_delta",
                "recovery_killed_count_delta",
                "failed_trade_captured_count_delta",
                "hypothetical_positive_rate_delta_pp",
                "hypothetical_mean_return_delta_pp",
                "hypothetical_median_return_delta_pp",
                "hypothetical_mean_holding_days_delta",
            )
        )
    ]
    changed_thresholds = ", ".join(f"{item['threshold_pct']}%" for item in sweep_deltas) or "없음"
    fix02_core_questions = (
        "### Q1. SIGNAL_CUTOFF → SUPPORT_END horizon 수정으로 분류가 몇 건 바뀌었는가?\n\n"
        f"- RECOVERY: {fix01_summary['recovery_count']} → {len(recovery)}건 "
        f"(delta {len(recovery) - int(fix01_summary['recovery_count']):+d}), "
        f"NEVER_WINNER: {fix01_summary['never_winner_count']} → {len(never)}건 "
        f"(delta {len(never) - int(fix01_summary['never_winner_count']):+d})야. "
        f"Loss Guard는 RECOVERY {len(loss_guard[loss_guard['recovery_class'] == 'RECOVERY']) - int(fix01_summary['loss_guard_recovery_count']):+d}, "
        f"NEVER_WINNER {len(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER']) - int(fix01_summary['loss_guard_never_winner_count']):+d}건 변했어.\n\n"
        "### Q2. threshold sweep 결과가 얼마나 변했는가?\n\n"
        f"- {len(sweep_deltas)}/{len(THRESHOLDS)}개 threshold 행에서 변화가 있었어: "
        f"{changed_thresholds}. "
        "전체 threshold별 FIX01 → FIX02 수치는 아래 비교표와 CSV에 기록했어.\n\n"
        "### Q3. 특히 -30%는 어떻게 변했는가?\n\n"
        f"- recovery kill rate: {_fmt(fix01_30['recovery_killed_rate_pct'])} → {_fmt(threshold_30['recovery_killed_rate_pct'])} "
        f"(delta {_fmt(threshold_30['recovery_killed_rate_pct'] - fix01_30['recovery_killed_rate_pct'])}), "
        f"failure capture rate: {_fmt(fix01_30['failed_trade_captured_rate_pct'])} → {_fmt(threshold_30['failed_trade_captured_rate_pct'])} "
        f"(delta {_fmt(threshold_30['failed_trade_captured_rate_pct'] - fix01_30['failed_trade_captured_rate_pct'])}), "
        f"positive rate: {_fmt(fix01_30['hypothetical_positive_rate_pct'])} → {_fmt(threshold_30['hypothetical_positive_rate_pct'])} "
        f"(delta {_fmt(threshold_30['hypothetical_positive_rate_pct'] - fix01_30['hypothetical_positive_rate_pct'])}), "
        f"mean return: {_fmt(fix01_30['hypothetical_mean_terminal_return_pct'])} → {_fmt(threshold_30['hypothetical_mean_terminal_return_pct'])} "
        f"(delta {_fmt(threshold_30['hypothetical_mean_terminal_return_pct'] - fix01_30['hypothetical_mean_terminal_return_pct'])})야.\n\n"
        "### Q4. horizon correction 이후에도 fixed Hard Failure threshold를 식별할 수 없는가?\n\n"
        f"- **{'아니오' if summary['hard_failure_threshold_identified'] else '예'}**. `hard_failure_threshold_identified={str(summary['hard_failure_threshold_identified']).lower()}`, "
        f"candidate는 `{summary['hard_failure_candidate_threshold_pct']}`로 유지해.\n\n"
        "### Q5. `fixed_threshold_mean_improvement_count`는 몇 개인가?\n\n"
        f"- FIX01 {fix01_improvement_count}개 → FIX02 {fixed_threshold_mean_improvement_count}개 "
        f"(delta {fixed_threshold_mean_improvement_count - fix01_improvement_count:+d})야.\n\n"
        "### Q6. `-25~-30%`를 FAILURE ARMED 연구 참고 영역으로 유지할 수 있는가?\n\n"
        f"- **{'유지할 수 있어' if fixed_threshold_mean_improvement_count == 0 else '자동으로 확정하지 않아'}**. "
        "이번 horizon correction에서도 해당 구간을 Hard Exit나 strategy parameter로 확정하지 않고, "
        "향후 FAILURE ARMED price-damage 연구 참고 영역으로만 유지해.\n\n"
    )

    all_rec_close = stats("ALL_973", "RECOVERY", "prewinner_min_close_return_pct")
    all_nev_close = stats("ALL_973", "NEVER_WINNER", "prewinner_min_close_return_pct")
    lg_rec_close = stats("LOSS_GUARD_590", "RECOVERY", "prewinner_min_close_return_pct")
    lg_nev_close = stats("LOSS_GUARD_590", "NEVER_WINNER", "prewinner_min_close_return_pct")
    q3_lines = [
        "- 전체 close bin에서 `-20% to > -25%`는 RECOVERY/NEVER_WINNER "
        f"{close_bin_counts('ALL_973', '-20% to > -25%')}, `-25% to > -30%`는 "
        f"{close_bin_counts('ALL_973', '-25% to > -30%')}, `-30% to > -35%`는 "
        f"{close_bin_counts('ALL_973', '-30% to > -35%')}건이야.",
        "- Loss Guard close bin에서는 같은 구간이 각각 "
        f"{close_bin_counts('LOSS_GUARD_590', '-20% to > -25%')}, "
        f"{close_bin_counts('LOSS_GUARD_590', '-25% to > -30%')}, "
        f"{close_bin_counts('LOSS_GUARD_590', '-30% to > -35%')}건이야.",
        "- 따라서 분포 분리는 -20%~-30%부터 눈에 띄게 커지고, -60% 이하에서는 NEVER_WINNER가 지배적이지만 "
        "그 깊은 threshold는 recovery 보호와 failure capture를 함께 크게 잃어 고정 기준선 확정에는 부적합해."
    ]
    return f"""# FASTCORE V1 PRE-WINNER HARD FAILURE DIAGNOSTIC V00 FIX02

## FIX02 핵심 질문에 대한 숫자 답

{fix02_core_questions}

## 보조 분포 및 threshold 진단

### Q1. RECOVERY는 +20% 전 어디까지 하락했는가?

- 전체 973건 중 RECOVERY는 **{len(recovery)}건**이야.
- CLOSE — {stats_line('ALL_973', 'RECOVERY', 'prewinner_min_close_return_pct')}.
- LOW — {stats_line('ALL_973', 'RECOVERY', 'prewinner_min_low_return_pct')}.
- Loss Guard 590건 중 RECOVERY {len(loss_guard[loss_guard['recovery_class'] == 'RECOVERY'])}건: CLOSE — {stats_line('LOSS_GUARD_590', 'RECOVERY', 'prewinner_min_close_return_pct')}.
- Loss Guard RECOVERY LOW — {stats_line('LOSS_GUARD_590', 'RECOVERY', 'prewinner_min_low_return_pct')}.

### Q2. NEVER_WINNER는 어디까지 하락했는가?

- 전체 973건 중 NEVER_WINNER는 **{len(never)}건**이야.
- CLOSE — {stats_line('ALL_973', 'NEVER_WINNER', 'prewinner_min_close_return_pct')}.
- LOW — {stats_line('ALL_973', 'NEVER_WINNER', 'prewinner_min_low_return_pct')}.
- Loss Guard 590건 중 NEVER_WINNER {len(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER'])}건: CLOSE — {stats_line('LOSS_GUARD_590', 'NEVER_WINNER', 'prewinner_min_close_return_pct')}.
- Loss Guard NEVER_WINNER LOW — {stats_line('LOSS_GUARD_590', 'NEVER_WINNER', 'prewinner_min_low_return_pct')}.

### Q3. 두 분포가 가장 크게 갈라지는 구간

{chr(10).join(q3_lines)}

분포 percentile 요약은 아래 CSV에 전체 stat(min/p05/p10/p25/median/p75/p90/p95/max/mean)으로 저장했어. 대표적으로 전체 CLOSE median은 RECOVERY **{_fmt(all_rec_close['median'])}**, NEVER_WINNER **{_fmt(all_nev_close['median'])}**이고, Loss Guard CLOSE median은 각각 **{_fmt(lg_rec_close['median'])}**, **{_fmt(lg_nev_close['median'])}**야.

#### 5% CLOSE bins — ALL_973

| bin | total n/rate | recovery n/rate | never n/rate | recovery within bin |
|---|---:|---:|---:|---:|
{chr(10).join(close_bin_lines('ALL_973'))}

#### 5% CLOSE bins — LOSS_GUARD_590

| bin | total n/rate | recovery n/rate | never n/rate | recovery within bin |
|---|---:|---:|---:|---:|
{chr(10).join(close_bin_lines('LOSS_GUARD_590'))}

### Q4. threshold별 recovery kill / failure capture

{chr(10).join(q4_lines)}

### Q5. threshold 적용 시 원래 V0 대비 aggregate

V0 baseline: positive rate **{_fmt(baseline['baseline_v0_positive_rate_pct'])}**, mean **{_fmt(baseline['baseline_v0_mean_terminal_return_pct'])}**, median **{_fmt(baseline['baseline_v0_median_terminal_return_pct'])}**, mean holding **{_fmt(baseline['baseline_v0_mean_holding_days'], suffix='d')}**.

| threshold | recovery killed | failed captured | positive n/rate | mean | median | +20/+30/+50/+100 n | -20/-30/-40/-50/-60 n | mean hold | Δ mean vs V0 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(q5_lines)}

### Q6. 단일 Pre-Winner Hard Failure 기준선을 정할 수 있는가?

{q6}

### 실제 next local OPEN impact

아래는 breach 후 next local trading day OPEN이 실제로 존재한 행만 집계한 값이야. `Δ mean`은 해당 next OPEN exit return에서 원래 V0 terminal return을 뺀 평균이고, V0 MFE도 함께 표시했어.

| threshold | cohort | executable n | next OPEN return mean | median | Δ mean vs V0 | original V0 MFE mean |
|---:|---|---:|---:|---:|---:|---:|
{chr(10).join(impact_group_line(threshold, cohort) for threshold in THRESHOLDS for cohort in ('RECOVERY', 'NEVER_WINNER'))}

## FIX01 → FIX02 horizon correction impact

관측 종료를 `SIGNAL_CUTOFF=2026-08-14`에서 실제 V0 exit observation과 같은 `SUPPORT_END=2026-08-21`로 확장했어. 신규 entry signal cutoff은 그대로야.

{horizon_impact}

| threshold | recovery killed FIX01 → FIX02 | failure captured FIX01 → FIX02 | positive rate FIX01 → FIX02 | mean FIX01 → FIX02 | median FIX01 → FIX02 | mean holding delta |
|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(sweep_comparison_lines)}

Threshold별 전체 sweep과 trade-level impact의 FIX01 대비 상세값은 새 CSV에 기록했어. 이번 horizon correction은 계산 결과를 바꿀 수 있으므로 V00/FIX01 artifact를 덮어쓰지 않고 별도 경로에 저장했어.

## 정의 및 look-ahead 제한

- 권위 source는 FIX01 matched-entry artifact의 973건이야. 기존 V0/FIX01 결과를 전략적으로 변경하지 않았어.
- RECOVERY/NEVER_WINNER는 V0 path의 미래 MFE를 사용한 retrospective label이야. signal logic이나 진입 logic에 사용하지 않았어.
- running MFE는 daily HIGH로 갱신하고, 첫 HIGH가 entry OPEN 대비 +20% 이상이 된 당일은 Pre-Winner 관측에서 제외했어. same-day ordering을 지켰어.
- Hard Failure 후보 기준은 HWM drawdown이 아니라 `entry execution OPEN 대비 daily CLOSE return`이야.
- threshold breach는 EOD signal 후보, 체결은 next local trading day OPEN이야. daily LOW는 보조 분포일 뿐 trigger 기준이 아니야. 관측과 execution support는 `SUPPORT_END=2026-08-21`에서 닫고 그 이후 session은 사용하지 않았어.
- daily FAST 생성, 주간 FAST→일간 전환, V1 rule 구현은 하지 않았어.

## Loss Guard 590 subset

- 전체 Loss Guard: `{len(loss_guard)}건`
- RECOVERY: `{len(loss_guard[loss_guard['recovery_class'] == 'RECOVERY'])}건`, NEVER_WINNER: `{len(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER'])}건`
- RECOVERY V0 mean return: `{_fmt(loss_guard[loss_guard['recovery_class'] == 'RECOVERY']['v0_terminal_return'].mean())}`
- NEVER_WINNER V0 mean return: `{_fmt(loss_guard[loss_guard['recovery_class'] == 'NEVER_WINNER']['v0_terminal_return'].mean())}`
- Loss Guard subset의 상세 percentile, 5% bins, threshold별 impact는 각 CSV와 JSON에 기록했어.

## 산출물

- `prewinner_trade_diagnostics.csv`
- `prewinner_drawdown_distribution.csv`
- `prewinner_threshold_sweep.csv`
- `prewinner_threshold_trade_impacts.csv`
- `prewinner_hard_failure_summary.json`
- `fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix02_report.md`

상세 산출물 절대 경로: `{output_dir}`

## 실행 및 보호 범위

- 실행 명령: `./.venv/bin/python scripts/analyze_fastcore_v1_prewinner_hard_failure_diagnostic_v00.py --run-fix02`
- 기존 V0/FIX01 artifact overwrite: 없음
- 기존 V3 1,578 trade 재생성: 없음
- Production strategy 수정: 없음
- Julia/portfolio: 실행하지 않음
- 외부 API/network: `0`
- 전체 repository pytest: 실행하지 않음
"""


def run_analysis(output_dir: Path = FIX02_OUT_DIR) -> dict[str, Any]:
    matched = pd.read_csv(MATCHED_PATH)
    if len(matched) != 973:
        raise AssertionError(f"expected 973 matched source rows, got {len(matched)}")
    matched_summary = _read_json(MATCHED_SUMMARY_PATH)
    if matched_summary.get("matched_rows") != 973:
        raise AssertionError("FIX01 matched summary row count mismatch")
    v3_trades = pd.read_csv(V3_TRADES_PATH)
    if len(v3_trades) != 1578:
        raise AssertionError(f"expected 1578 existing V3 trades, got {len(v3_trades)}")
    tickers = {str(ticker).zfill(6) for ticker in matched["ticker"].astype(str)}
    raw_frames = _load_target_raw_frames(
        ROOT,
        tickers,
        v3.START_DATE.strftime("%Y-%m-%d"),
        v3.SUPPORT_END.strftime("%Y-%m-%d"),
    )
    repository = MarketDataRepositoryV2(
        AdjustedPriceStore(ROOT / "data/market/adjusted/stocks"),
        _TargetedRawStore(raw_frames),
    )
    loader = RepositoryV2DailyLoader(
        repository,
        start=v3.START_DATE,
        end=v3.SUPPORT_END,
    )
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in sorted(matched["ticker"].astype(str).unique()):
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"missing local daily OHLC for {ticker}")
        daily_by_ticker[ticker] = daily
    paths = build_paths(matched, daily_by_ticker)
    trade_diagnostics = build_trade_diagnostics(matched, daily_by_ticker)
    if len(trade_diagnostics) != 973:
        raise AssertionError("trade diagnostic row count mismatch")
    recovery_count = int((trade_diagnostics["recovery_class"] == "RECOVERY").sum())
    never_winner_count = int((trade_diagnostics["recovery_class"] == "NEVER_WINNER").sum())
    if recovery_count + never_winner_count != 973:
        raise AssertionError("recovery class partition changed")
    loss_guard = trade_diagnostics[trade_diagnostics["v2_exit_reason"] == LOSS_GUARD_REASON]
    if len(loss_guard) != 590:
        raise AssertionError("Loss Guard count changed")
    loss_guard_recovery_count = int((loss_guard["recovery_class"] == "RECOVERY").sum())
    loss_guard_never_winner_count = int((loss_guard["recovery_class"] == "NEVER_WINNER").sum())
    if loss_guard_recovery_count + loss_guard_never_winner_count != 590:
        raise AssertionError("Loss Guard recovery class partition changed")
    distribution = build_distribution(trade_diagnostics)
    sweep, impacts = build_sweep_and_impacts(matched, paths, daily_by_ticker)
    baseline_mean = float(sweep["baseline_v0_mean_terminal_return_pct"].iloc[0])
    fixed_threshold_mean_improvement_count = int(
        (pd.to_numeric(sweep["hypothetical_mean_terminal_return_pct"]) > baseline_mean).sum()
    )
    fix01_summary = _read_json(FIX01_OUT_DIR / "prewinner_hard_failure_summary.json")
    fix01_sweep = pd.read_csv(FIX01_OUT_DIR / "prewinner_threshold_sweep.csv")
    current_30 = _row(sweep, -30)
    fix01_30 = _row(fix01_sweep, -30)
    fix01_comparison = {
        "recovery_count_delta": recovery_count - int(fix01_summary["recovery_count"]),
        "never_winner_count_delta": never_winner_count - int(fix01_summary["never_winner_count"]),
        "loss_guard_recovery_count_delta": loss_guard_recovery_count - int(fix01_summary["loss_guard_recovery_count"]),
        "loss_guard_never_winner_count_delta": loss_guard_never_winner_count - int(fix01_summary["loss_guard_never_winner_count"]),
        "minus_30_recovery_kill_rate_delta_pp": round(float(current_30["recovery_killed_rate_pct"] - fix01_30["recovery_killed_rate_pct"]), 6),
        "minus_30_failure_capture_rate_delta_pp": round(float(current_30["failed_trade_captured_rate_pct"] - fix01_30["failed_trade_captured_rate_pct"]), 6),
        "minus_30_mean_return_delta_pp": round(float(current_30["hypothetical_mean_terminal_return_pct"] - fix01_30["hypothetical_mean_terminal_return_pct"]), 6),
        "fixed_threshold_mean_improvement_count_fix01": int(fix01_summary["fixed_threshold_mean_improvement_count"]),
        "fixed_threshold_mean_improvement_count_fix02": fixed_threshold_mean_improvement_count,
        "fixed_threshold_mean_improvement_count_delta": fixed_threshold_mean_improvement_count - int(fix01_summary["fixed_threshold_mean_improvement_count"]),
        "threshold_sweep_deltas": [
            {
                "threshold_pct": threshold,
                "recovery_breach_count_delta": int(_row(sweep, threshold)["recovery_breach_count"] - _row(fix01_sweep, threshold)["recovery_breach_count"]),
                "recovery_killed_count_delta": int(_row(sweep, threshold)["recovery_killed_count"] - _row(fix01_sweep, threshold)["recovery_killed_count"]),
                "failed_trade_captured_count_delta": int(_row(sweep, threshold)["failed_trade_captured_count"] - _row(fix01_sweep, threshold)["failed_trade_captured_count"]),
                "hypothetical_positive_rate_delta_pp": round(float(_row(sweep, threshold)["hypothetical_positive_rate_pct"] - _row(fix01_sweep, threshold)["hypothetical_positive_rate_pct"]), 6),
                "hypothetical_mean_return_delta_pp": round(float(_row(sweep, threshold)["hypothetical_mean_terminal_return_pct"] - _row(fix01_sweep, threshold)["hypothetical_mean_terminal_return_pct"]), 6),
                "hypothetical_median_return_delta_pp": round(float(_row(sweep, threshold)["hypothetical_median_terminal_return_pct"] - _row(fix01_sweep, threshold)["hypothetical_median_terminal_return_pct"]), 6),
                "hypothetical_mean_holding_days_delta": round(float(_row(sweep, threshold)["hypothetical_mean_holding_days"] - _row(fix01_sweep, threshold)["hypothetical_mean_holding_days"]), 6),
            }
            for threshold in THRESHOLDS
        ],
    }
    summary: dict[str, Any] = {
        "work_id": "FASTCORE_V1_PREWINNER_HARD_FAILURE_DIAGNOSTIC_V00_FIX02",
        "status": "COMPLETE",
        "evaluation_start": "2021-04-01",
        "signal_cutoff": "2026-08-14",
        "execution_support_end": "2026-08-21",
        "prewinner_observation_end": "2026-08-21",
        "final_valuation": "2026-08-21 CLOSE",
        "source_matched_rows": len(matched),
        "source_loss_guard_rows": int((matched["v2_exit_reason"] == LOSS_GUARD_REASON).sum()),
        "recovery_count": recovery_count,
        "never_winner_count": never_winner_count,
        "loss_guard_recovery_count": loss_guard_recovery_count,
        "loss_guard_never_winner_count": loss_guard_never_winner_count,
        "thresholds_pct": list(THRESHOLDS),
        "prewinner_definition": "entry execution date through the day before the first running daily-HIGH MFE >=20%; first +20% day excluded after HIGH/HWM update; all matched V0 trades are observed through SUPPORT_END / the available identity-scoped V0 observation path",
        "trigger_definition": "entry execution OPEN-relative daily CLOSE return <= threshold",
        "execution_definition": "next local trading day OPEN",
        "retrospective_label_only": True,
        "future_label_used_in_signal_logic": False,
        "daily_fast_created": False,
        "existing_v3_trades_recreated": False,
        "network_requests": 0,
        "production_strategy_modified": False,
        "existing_v0_fix01_artifact_modified": False,
        "julia_executed": False,
        "hard_failure_threshold_identified": False,
        "hard_failure_candidate_threshold_pct": None,
        "fixed_threshold_mean_improvement_count": fixed_threshold_mean_improvement_count,
        "failure_armed_price_damage_research_region_pct": [-25, -30],
        "failure_armed_region_is_strategy_parameter": False,
        "hard_failure_conclusion": (
            "No tested fixed pre-winner CLOSE-loss threshold improved the V0 mean terminal return while preserving enough recovery trades. A fixed Hard Failure threshold is therefore not identified by this diagnostic."
            if fixed_threshold_mean_improvement_count == 0
            else "At least one tested fixed pre-winner CLOSE-loss threshold improved the V0 mean terminal return in this horizon replay, but no automatic Hard Failure candidate is selected by this diagnostic."
        ),
        "fix01_comparison": fix01_comparison,
        "matched_v0_aggregate_invariant": {
            "trades": 973,
            "v0_positive_rate_pct": 70.914697,
            "v0_mean_terminal_return_pct": 8.666341,
            "v0_mfe_lt_20_count": int((pd.to_numeric(matched["v0_mfe"]) < 20.0).sum()),
            "loss_guard_recovery_count": loss_guard_recovery_count,
            "loss_guard_never_winner_count": loss_guard_never_winner_count,
        },
        "source_artifacts": {
            "matched": str(MATCHED_PATH.relative_to(ROOT)),
            "matched_summary": str(MATCHED_SUMMARY_PATH.relative_to(ROOT)),
            "v3_trades": str(V3_TRADES_PATH.relative_to(ROOT)),
        },
    }
    summary["distribution_records"] = json.loads(distribution.to_json(orient="records"))
    summary["threshold_sweep_records"] = json.loads(sweep.to_json(orient="records"))
    trade_path = output_dir / "prewinner_trade_diagnostics.csv"
    distribution_path = output_dir / "prewinner_drawdown_distribution.csv"
    sweep_path = output_dir / "prewinner_threshold_sweep.csv"
    impact_path = output_dir / "prewinner_threshold_trade_impacts.csv"
    summary_path = output_dir / "prewinner_hard_failure_summary.json"
    report_path = output_dir / "fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix02_report.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    trade_diagnostics.to_csv(trade_path, index=False, lineterminator="\n")
    distribution.to_csv(distribution_path, index=False, lineterminator="\n")
    sweep.to_csv(sweep_path, index=False, lineterminator="\n")
    impacts.to_csv(impact_path, index=False, lineterminator="\n")
    _write_json(summary_path, summary)
    report_path.write_text(build_report(summary, distribution, sweep, output_dir), encoding="utf-8")
    return {"summary": summary, "trades": trade_diagnostics, "distribution": distribution, "sweep": sweep, "impacts": impacts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-fix02", action="store_true")
    args = parser.parse_args()
    if not args.run_fix02:
        parser.error("use --run-fix02 to execute the offline V00 FIX02 diagnostic")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_analysis(FIX02_OUT_DIR)
        result["summary"]["network_requests"] = audit.request_count
        _write_json(FIX02_OUT_DIR / "prewinner_hard_failure_summary.json", result["summary"])
        print(json.dumps({
            "status": result["summary"]["status"],
            "source_matched_rows": result["summary"]["source_matched_rows"],
            "recovery_count": result["summary"]["recovery_count"],
            "never_winner_count": result["summary"]["never_winner_count"],
            "network_requests": audit.request_count,
        }, ensure_ascii=False), flush=True)
        return 0 if audit.request_count == 0 else 1
    except Exception as exc:
        print(f"PRE-WINNER DIAGNOSTIC BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
