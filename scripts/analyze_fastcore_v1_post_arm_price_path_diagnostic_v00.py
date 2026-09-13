#!/usr/bin/env python3
"""Diagnose price paths after the first V1 FAILURE ARMED event.

This is a path-distribution diagnostic, not a backtest.  It reads the
completed W25/W30 matched-entry artifact, reconstructs the same local V0
weekly FAST index and identity-scoped daily OHLC path, and measures what
happened after each observed ARM.  It never creates an exit signal or
chooses a deterioration threshold.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
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


WORK_ID = "FASTCORE_V1_POST_ARM_PRICE_PATH_DIAGNOSTIC_V00"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_post_arm_price_path_diagnostic_v00"
TRADE_PATH = OUT_DIR / "first_arm_trade_diagnostics.csv"
NEXT_DIST_PATH = OUT_DIR / "first_arm_next_fast_distribution.csv"
LONG_DIST_PATH = OUT_DIR / "first_arm_long_horizon_distribution.csv"
BINS_PATH = OUT_DIR / "first_arm_descriptive_bins.csv"
STATE_DIST_PATH = OUT_DIR / "first_arm_next_fast_state_distribution.csv"
CYCLE_PATH = OUT_DIR / "all_observed_arm_cycle_diagnostics.csv"
SUMMARY_PATH = OUT_DIR / "fastcore_v1_post_arm_price_path_diagnostic_v00_summary.json"
REPORT_PATH = OUT_DIR / "fastcore_v1_post_arm_price_path_diagnostic_v00_report.md"

ARMED_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_failure_armed_ab_v00"
ARMED_MATCHED_PATH = ARMED_DIR / "matched_v0_vs_v1w25_vs_v1w30.csv"
ARMED_EVENT_PATH = ARMED_DIR / "failure_armed_event_log.csv"
ARMED_SUMMARY_PATH = ARMED_DIR / "fastcore_v1_prewinner_failure_armed_ab_v00_summary.json"
CONTROL_PATH = ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0.csv"

WEAK_STATES = frozenset({"WATCH", "SETUP"})
STRONG_STATES = frozenset({"TRIGGER", "TREND", "EXTENDED"})
UNAVAILABLE_STATES = frozenset({"UNAVAILABLE"})
USABLE_STATES = WEAK_STATES | STRONG_STATES
ALLOWED_STATES = USABLE_STATES | UNAVAILABLE_STATES
EXPECTED_STATE_COUNTS = {
    "EXTENDED": 13858,
    "SETUP": 61410,
    "TREND": 11190,
    "TRIGGER": 12637,
    "UNAVAILABLE": 1348,
    "WATCH": 41247,
}
EXPECTED_FIRST_ARM_COUNTS = {"FASTCORE_V1_W25_PREWINNER_ARMED_V00": 351, "FASTCORE_V1_W30_PREWINNER_ARMED_V00": 297}


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise RuntimeError(f"offline post-arm diagnostic guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise RuntimeError(f"offline post-arm diagnostic guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _text(value: pd.Timestamp | None) -> str | None:
    return value.strftime("%Y-%m-%d") if value is not None else None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _state_domain(state_counts: Mapping[str, int]) -> dict[str, Any]:
    observed = dict(sorted(state_counts.items()))
    if set(observed) != set(EXPECTED_STATE_COUNTS) or observed != EXPECTED_STATE_COUNTS:
        raise RuntimeError(f"FAST state domain/count mismatch; expected={EXPECTED_STATE_COUNTS}, actual={observed}")
    return {"observed_states": sorted(observed), "observed_counts": observed, "unknown_states": []}


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _min_path_metrics(
    daily: pd.DataFrame, entry_open: float, start_exclusive: pd.Timestamp,
    end_inclusive: pd.Timestamp | None,
) -> dict[str, Any]:
    mask = daily.index > start_exclusive
    if end_inclusive is not None:
        mask &= daily.index <= end_inclusive
    path = daily.loc[mask]
    if path.empty:
        return {
            "min_close_return_pct": None, "min_close_date": None,
            "min_close_delta_pp": None, "additional_close_deterioration_pp": None,
            "min_low_return_pct": None, "additional_low_deterioration_pp": None,
        }
    close_returns = (path["close"].astype(float) / entry_open - 1.0) * 100.0
    low_returns = (path["low"].astype(float) / entry_open - 1.0) * 100.0
    min_close_date = _date(close_returns.idxmin())
    min_close = float(close_returns.loc[min_close_date])
    min_low = float(low_returns.min())
    return {
        "min_close_return_pct": round(min_close, 6),
        "min_close_date": _text(min_close_date),
        "min_close_delta_pp": None,
        "additional_close_deterioration_pp": None,
        "min_low_return_pct": round(min_low, 6),
        "additional_low_deterioration_pp": None,
    }


def _with_arm_deltas(metrics: dict[str, Any], arm_return: float) -> dict[str, Any]:
    if metrics["min_close_return_pct"] is None:
        return metrics
    metrics["min_close_delta_pp"] = round(metrics["min_close_return_pct"] - arm_return, 6)
    metrics["additional_close_deterioration_pp"] = round(max(0.0, arm_return - metrics["min_close_return_pct"]), 6)
    metrics["additional_low_deterioration_pp"] = round(max(0.0, arm_return - metrics["min_low_return_pct"]), 6)
    return metrics


def _first_mfe20_date(daily: pd.DataFrame, entry_date: pd.Timestamp, entry_open: float) -> pd.Timestamp | None:
    hwm = entry_open
    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        hwm = max(hwm, float(bar["high"]))
        # V0's stored MFE/tier contract rounds the percentage to two decimal
        # places before applying the +20% boundary.
        if round((hwm / entry_open - 1.0) * 100.0, 2) >= 20.0:
            return _date(date)
    return None


def _long_horizon(
    daily: pd.DataFrame, entry_date: pd.Timestamp, arm_date: pd.Timestamp,
    entry_open: float, arm_return: float, recovery_class: str, identity_end: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    identity_end = min(_date(identity_end), v3.SUPPORT_END)
    first_mfe20 = _first_mfe20_date(daily, entry_date, entry_open)
    if recovery_class == "RECOVERY":
        if first_mfe20 is None:
            raise AssertionError("RECOVERY label has no first MFE20 in the underlying path")
        horizon_end = _date(daily.index[daily.index < first_mfe20][-1]) if (daily.index < first_mfe20).any() else None
        end_reason = "BEFORE_FIRST_MFE20"
    else:
        horizon_end = identity_end
        end_reason = "IDENTITY_END" if identity_end < v3.SUPPORT_END else "SUPPORT_END"
    if horizon_end is None or horizon_end <= arm_date:
        metrics = {
            "post_arm_long_min_close_return_pct": None,
            "post_arm_long_min_close_date": None,
            "post_arm_long_min_close_delta_pp": None,
            "post_arm_long_additional_close_deterioration_pp": None,
            "post_arm_long_min_low_return_pct": None,
            "post_arm_long_additional_low_deterioration_pp": None,
            "days_arm_to_long_min_close_trading": None,
            "days_arm_to_long_min_close_calendar": None,
            "long_horizon_last_close_return_pct": None,
            "arm_to_long_horizon_last_close_delta_pp": None,
        }
        return {"first_mfe20_date": _text(first_mfe20), "long_horizon_end_date": _text(horizon_end), "long_horizon_end_reason": end_reason, **metrics}, daily.iloc[0:0]
    path = daily.loc[(daily.index > arm_date) & (daily.index <= horizon_end)]
    metrics = _min_path_metrics(daily, entry_open, arm_date, horizon_end)
    if not path.empty:
        close_returns = (path["close"].astype(float) / entry_open - 1.0) * 100.0
        min_close = _to_float(metrics["min_close_return_pct"])
        metrics["post_arm_long_min_close_return_pct"] = metrics.pop("min_close_return_pct")
        metrics["post_arm_long_min_close_date"] = metrics.pop("min_close_date")
        metrics["post_arm_long_min_close_delta_pp"] = round(min_close - arm_return, 6) if min_close is not None else None
        metrics["post_arm_long_additional_close_deterioration_pp"] = round(max(0.0, arm_return - min_close), 6) if min_close is not None else None
        metrics["post_arm_long_min_low_return_pct"] = metrics.pop("min_low_return_pct")
        metrics["post_arm_long_additional_low_deterioration_pp"] = round(max(0.0, arm_return - float(metrics["post_arm_long_min_low_return_pct"])), 6)
        min_date = _date(metrics["post_arm_long_min_close_date"])
        metrics["days_arm_to_long_min_close_trading"] = int(len(daily.loc[(daily.index > arm_date) & (daily.index <= min_date)]))
        metrics["days_arm_to_long_min_close_calendar"] = int((min_date - arm_date).days)
        last_return = float(close_returns.iloc[-1])
        metrics["long_horizon_last_close_return_pct"] = round(last_return, 6)
        metrics["arm_to_long_horizon_last_close_delta_pp"] = round(last_return - arm_return, 6)
    else:
        metrics.update({
            "post_arm_long_min_close_return_pct": None, "post_arm_long_min_close_date": None,
            "post_arm_long_min_close_delta_pp": None, "post_arm_long_additional_close_deterioration_pp": None,
            "post_arm_long_min_low_return_pct": None, "post_arm_long_additional_low_deterioration_pp": None,
            "days_arm_to_long_min_close_trading": None, "days_arm_to_long_min_close_calendar": None,
            "long_horizon_last_close_return_pct": None, "arm_to_long_horizon_last_close_delta_pp": None,
        })
    metrics.pop("min_close_delta_pp", None)
    metrics.pop("additional_close_deterioration_pp", None)
    metrics.pop("additional_low_deterioration_pp", None)
    return {"first_mfe20_date": _text(first_mfe20), "long_horizon_end_date": _text(horizon_end), "long_horizon_end_reason": end_reason, **metrics}, path


def _next_usable(
    states: Sequence[tuple[pd.Timestamp, str]], arm_fast_date: pd.Timestamp,
) -> tuple[pd.Timestamp | None, str | None, int]:
    unavailable = 0
    for fast_date, state in states:
        if fast_date <= arm_fast_date:
            continue
        if state in UNAVAILABLE_STATES:
            unavailable += 1
            continue
        if state in USABLE_STATES:
            return fast_date, state, unavailable
        raise RuntimeError(f"unexpected FAST state {state!r}")
    return None, None, unavailable


def _anchor_rows(matched: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    anchors: list[dict[str, Any]] = []
    for strategy_id, group in matched.groupby("strategy_id", sort=True):
        expected_count = EXPECTED_FIRST_ARM_COUNTS.get(strategy_id)
        if expected_count is None:
            raise AssertionError(f"unexpected strategy in existing A/B artifact: {strategy_id}")
        first = group.loc[group["first_armed_date"].notna()].copy()
        first_events = events.loc[(events["strategy_id"] == strategy_id) & (events["event_type"] == "ARMED")].sort_values(["control_trade_id", "date"], kind="mergesort")
        event_first = first_events.drop_duplicates("control_trade_id", keep="first").set_index("control_trade_id")
        if len(first) != expected_count or len(event_first) != expected_count:
            raise AssertionError(f"{strategy_id} first ARM count mismatch")
        if set(first["control_trade_id"]) != set(event_first.index):
            raise AssertionError(f"{strategy_id} first ARM trade ids do not match event log")
        for row in first.to_dict("records"):
            event = event_first.loc[str(row["control_trade_id"])]
            if str(row["first_armed_date"]) != str(event["date"]):
                raise AssertionError(f"first ARM anchor mismatch for {row['control_trade_id']}")
            if str(event["fast_state"]) not in WEAK_STATES:
                raise AssertionError(f"first ARM FAST state is not weak for {row['control_trade_id']}")
            row["first_arm_event_fast_date"] = event["fast_date"]
            row["first_arm_event_fast_state"] = event["fast_state"]
            row["first_arm_event_close_return_pct"] = float(event["close_return_pct"])
            row["first_arm_event_running_mfe_pct"] = float(event["running_mfe_pct"])
            anchors.append(row)
    return pd.DataFrame(anchors)


def _diagnose_cycle(
    row: Mapping[str, Any], arm_date: pd.Timestamp, arm_fast_date: pd.Timestamp,
    arm_fast_state: str, arm_return: float, arm_mfe: float,
    daily_by_ticker: Mapping[str, pd.DataFrame], states_by_identity: Mapping[str, Sequence[tuple[pd.Timestamp, str]]],
    scope: str, arm_event_type: str, arm_cycle_number: int,
) -> dict[str, Any]:
    daily = clip_to_identity_lifecycle(daily_by_ticker[str(row["ticker"])], v0_ab._lifecycle(row))
    if daily is None or daily.empty:
        raise RuntimeError(f"empty daily path for {row['control_trade_id']}")
    arm_date = _date(arm_date)
    arm_fast_date = _date(arm_fast_date)
    entry_date = _date(row["entry_execution_date"])
    entry_open = float(row["entry_open"])
    if arm_date not in daily.index or arm_fast_date not in daily.index:
        raise RuntimeError(f"ARM/FAST date missing from identity path for {row['control_trade_id']}")
    next_date, next_state, unavailable_count = _next_usable(states_by_identity[v0_ab._identity_key(row)], arm_fast_date)
    if next_date is not None and next_date not in daily.index:
        raise RuntimeError(f"next FAST date missing from identity path for {row['control_trade_id']}")
    next_close = float(daily.loc[next_date, "close"]) if next_date is not None else None
    next_return = (next_close / entry_open - 1.0) * 100.0 if next_close is not None else None
    if next_date is None:
        short = {
            "min_close_return_pct": None, "min_close_date": None,
            "min_close_delta_pp": None, "additional_close_deterioration_pp": None,
            "min_low_return_pct": None, "additional_low_deterioration_pp": None,
        }
    else:
        short = _with_arm_deltas(_min_path_metrics(daily, entry_open, arm_date, next_date), arm_return)
    long, _long_path = _long_horizon(
        daily, entry_date, arm_date, entry_open, arm_return, str(row["recovery_class"]),
        v0_ab._lifecycle(row).effective_to,
    )
    result: dict[str, Any] = {
        "analysis_scope": scope,
        "arm_event_type": arm_event_type,
        "arm_cycle_number": arm_cycle_number,
        "variant": str(row["strategy_id"]),
        "price_damage_threshold_pct": float(row["price_damage_threshold_pct"]),
        "control_trade_id": str(row["control_trade_id"]),
        "ticker": str(row["ticker"]).zfill(6),
        "name": str(row["name"]),
        "recovery_class": str(row["recovery_class"]),
        "v2_loss_guard_triggered": bool(row["v2_loss_guard_triggered"]),
        "entry_date": str(row["entry_execution_date"]),
        "entry_open": entry_open,
        "first_arm_date": _text(arm_date),
        "first_arm_close": float(daily.loc[arm_date, "close"]),
        "first_arm_close_return_pct": round(arm_return, 6),
        "first_arm_running_mfe_pct": round(arm_mfe, 6),
        "first_arm_fast_date": _text(arm_fast_date),
        "first_arm_fast_state": arm_fast_state,
        "next_usable_fast_date": _text(next_date),
        "next_usable_fast_state": next_state,
        "unavailable_before_next_usable_count": unavailable_count,
        "next_fast_close": next_close,
        "next_fast_close_return_pct": round(next_return, 6) if next_return is not None else None,
        "arm_to_next_fast_delta_pp": round(next_return - arm_return, 6) if next_return is not None else None,
        "min_close_return_after_arm_to_next_fast_pct": short["min_close_return_pct"],
        "min_close_date_after_arm_to_next_fast": short["min_close_date"],
        "min_close_delta_vs_arm_pp": short["min_close_delta_pp"],
        "additional_close_deterioration_pp": short["additional_close_deterioration_pp"],
        "min_low_return_after_arm_to_next_fast_pct": short["min_low_return_pct"],
        "additional_low_deterioration_pp": short["additional_low_deterioration_pp"],
        **long,
    }
    # Keep generic ARM aliases so secondary rows are not mislabeled as a
    # first-ARM observation.  The first_arm_* columns remain for the primary
    # artifact's explicit first-ARM contract and backward-readable output.
    result.update({
        "arm_date": _text(arm_date),
        "arm_close": float(daily.loc[arm_date, "close"]),
        "arm_close_return_pct": round(arm_return, 6),
        "arm_running_mfe_pct": round(arm_mfe, 6),
        "arm_fast_date": _text(arm_fast_date),
        "arm_fast_state": arm_fast_state,
    })
    return result


def _percentile(values: pd.Series, percentile: float) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return round(float(values.quantile(percentile)), 6) if not values.empty else None


def _distribution_rows(
    frame: pd.DataFrame, value_column: str, name: str,
    extra_cohorts: Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    cohorts = {
        "ALL_FIRST_ARM": frame,
        "RECOVERY_FIRST_ARM": frame.loc[frame["recovery_class"] == "RECOVERY"],
        "NEVER_WINNER_FIRST_ARM": frame.loc[frame["recovery_class"] == "NEVER_WINNER"],
        "LOSS_GUARD_RECOVERY_FIRST_ARM": frame.loc[(frame["v2_loss_guard_triggered"]) & (frame["recovery_class"] == "RECOVERY")],
        "LOSS_GUARD_NEVER_WINNER_FIRST_ARM": frame.loc[(frame["v2_loss_guard_triggered"]) & (frame["recovery_class"] == "NEVER_WINNER")],
    }
    if extra_cohorts:
        cohorts.update(extra_cohorts)
    rows: list[dict[str, Any]] = []
    for variant, variant_frame in frame.groupby("variant", sort=True):
        for cohort, cohort_frame in cohorts.items():
            subset = variant_frame.loc[variant_frame["control_trade_id"].isin(cohort_frame["control_trade_id"])]
            values = pd.to_numeric(subset[value_column], errors="coerce").dropna()
            total = len(subset)
            count = len(values)
            row = {
                "variant": variant, "cohort": cohort, "metric": name,
                "trade_count": total, "count_with_value": count,
                "missing_count": total - count, "missing_rate_pct": round((total - count) / total * 100.0, 6) if total else 0.0,
                "mean": round(float(values.mean()), 6) if count else None,
                "minimum": round(float(values.min()), 6) if count else None,
                "p05": _percentile(values, 0.05), "p10": _percentile(values, 0.10),
                "p25": _percentile(values, 0.25), "median": _percentile(values, 0.50),
                "p75": _percentile(values, 0.75), "p90": _percentile(values, 0.90),
                "p95": _percentile(values, 0.95), "maximum": round(float(values.max()), 6) if count else None,
            }
            if name == "arm_to_next_fast_delta_pp":
                row.update({
                    "positive_count": int((values > 0).sum()), "positive_rate_pct": round(float((values > 0).mean() * 100.0), 6) if count else 0.0,
                    "zero_count": int((values.abs() <= 1e-9).sum()), "zero_rate_pct": round(float((values.abs() <= 1e-9).mean() * 100.0), 6) if count else 0.0,
                    "negative_count": int((values < 0).sum()), "negative_rate_pct": round(float((values < 0).mean() * 100.0), 6) if count else 0.0,
                })
            rows.append(row)
    return pd.DataFrame(rows)


def _bin_rows(frame: pd.DataFrame) -> pd.DataFrame:
    definitions = {
        "arm_to_next_fast_delta_pp": [
            ("<= -20", lambda x: x <= -20), ("-20 to -15", lambda x: -20 < x <= -15), ("-15 to -10", lambda x: -15 < x <= -10),
            ("-10 to -5", lambda x: -10 < x <= -5), ("-5 to 0", lambda x: -5 < x <= 0), ("0 to +5", lambda x: 0 < x <= 5),
            ("+5 to +10", lambda x: 5 < x <= 10), ("> +10", lambda x: x > 10),
        ],
        "post_arm_long_additional_close_deterioration_pp": [
            ("0", lambda x: abs(x) <= 1e-9), (">0 to 5", lambda x: 0 < x <= 5), (">5 to 10", lambda x: 5 < x <= 10),
            (">10 to 15", lambda x: 10 < x <= 15), (">15 to 20", lambda x: 15 < x <= 20), (">20 to 30", lambda x: 20 < x <= 30), (">30", lambda x: x > 30),
        ],
    }
    rows: list[dict[str, Any]] = []
    for metric, bins in definitions.items():
        for variant, group in frame.groupby("variant", sort=True):
            for cohort, cohort_group in {
                "ALL_FIRST_ARM": group,
                "RECOVERY_FIRST_ARM": group.loc[group["recovery_class"] == "RECOVERY"],
                "NEVER_WINNER_FIRST_ARM": group.loc[group["recovery_class"] == "NEVER_WINNER"],
            }.items():
                values = pd.to_numeric(cohort_group[metric], errors="coerce").dropna()
                for label, predicate in bins:
                    count = int(sum(bool(predicate(value)) for value in values))
                    rows.append({"variant": variant, "cohort": cohort, "metric": metric, "bin": label, "count": count, "rate_pct": round(count / len(values) * 100.0, 6) if len(values) else 0.0, "distribution_count": len(values)})
    return pd.DataFrame(rows)


def _state_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant, group in frame.groupby("variant", sort=True):
        for cohort, cohort_group in {
            "ALL_FIRST_ARM": group,
            "RECOVERY_FIRST_ARM": group.loc[group["recovery_class"] == "RECOVERY"],
            "NEVER_WINNER_FIRST_ARM": group.loc[group["recovery_class"] == "NEVER_WINNER"],
        }.items():
            states = cohort_group["next_usable_fast_state"].fillna("NO_NEXT_USABLE_FAST")
            for state in ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED", "NO_NEXT_USABLE_FAST"]:
                count = int((states == state).sum())
                rows.append({"variant": variant, "cohort": cohort, "next_usable_fast_state": state, "count": count, "rate_pct": round(count / len(cohort_group) * 100.0, 6) if len(cohort_group) else 0.0})
    return pd.DataFrame(rows)


def _build_report(summary: Mapping[str, Any], next_dist: pd.DataFrame, long_dist: pd.DataFrame, states: pd.DataFrame, cycles: pd.DataFrame) -> str:
    def rows(metric: str, cohorts: Sequence[str]) -> list[dict[str, Any]]:
        return next_dist.loc[(next_dist["metric"] == metric) & (next_dist["cohort"].isin(cohorts))].to_dict("records")

    lines = [
        "# FASTCORE V1 POST-ARM PRICE PATH DIAGNOSTIC V00 결과 보고서",
        "",
        "## 결론",
        "",
        "이번 작업은 새 backtest나 exit rule이 아니다. 기존 W25/W30에서 실제 발생한 FIRST ARM 이후 underlying identity-scoped V0 price path의 분포만 진단했다. `SECONDARY / TRADE-WEIGHTED BIAS POSSIBLE`인 전체 cycle 분석은 보조 결과이며, primary 결론은 trade당 first ARM 하나만 사용한다.",
        "",
        f"최종 분류: `{summary['separation_conclusion']}`. 새 deterioration threshold나 strategy parameter는 선택하지 않았다.",
        "",
        "## Q1–Q3. FIRST ARM → next usable FAST",
        "",
    ]
    for record in rows("arm_to_next_fast_delta_pp", ["RECOVERY_FIRST_ARM", "NEVER_WINNER_FIRST_ARM", "LOSS_GUARD_RECOVERY_FIRST_ARM", "LOSS_GUARD_NEVER_WINNER_FIRST_ARM"]):
        lines.append(f"- {record['variant']} / {record['cohort']}: n={int(record['trade_count'])}, value n={int(record['count_with_value'])}, mean/median/p25/p75={record['mean']}/{record['median']}/{record['p25']}/{record['p75']}pp, improved/flat/worsened={record.get('positive_rate_pct', 0):.6f}%/{record.get('zero_rate_pct', 0):.6f}%/{record.get('negative_rate_pct', 0):.6f}%.")
    lines.extend([
        "",
        "## Q4–Q8. Additional deterioration, long horizon, and weak-only subset",
        "",
    ])
    for metric, label in [("additional_close_deterioration_pp", "short additional CLOSE deterioration"), ("post_arm_long_additional_close_deterioration_pp", "long-horizon additional CLOSE deterioration")]:
        source = next_dist if metric == "additional_close_deterioration_pp" else long_dist
        selected = source.loc[
            (source["metric"] == metric)
            & source["cohort"].isin([
                "RECOVERY_FIRST_ARM", "NEVER_WINNER_FIRST_ARM",
                "LOSS_GUARD_RECOVERY_FIRST_ARM", "LOSS_GUARD_NEVER_WINNER_FIRST_ARM",
            ])
        ]
        for record in selected.to_dict("records"):
            lines.append(f"- {label} / {record['variant']} / {record['cohort']}: n={int(record['count_with_value'])}/{int(record['trade_count'])}, mean/median/p25/p75={record['mean']}/{record['median']}/{record['p25']}/{record['p75']}pp.")
    weak = next_dist.loc[next_dist["cohort"].isin(["NEXT_FAST_WEAK_RECOVERY", "NEXT_FAST_WEAK_NEVER_WINNER"])]
    for record in weak.to_dict("records"):
        if record["metric"] == "arm_to_next_fast_delta_pp":
            lines.append(f"- weak-only {record['variant']} / {record['cohort']}: n={int(record['count_with_value'])}, delta mean/median={record['mean']}/{record['median']}pp, improved/worsened={record.get('positive_rate_pct', 0):.6f}%/{record.get('negative_rate_pct', 0):.6f}%.")
    lines.extend([
        "",
        "UNAVAILABLE은 usable next FAST에서 제외하고 count만 저장했다. next usable FAST가 없는 trade는 삭제하지 않고 missing count/rate로 남겼다.",
        "",
        "## Q9. Next usable FAST state",
        "",
    ])
    for record in states.loc[states["cohort"].isin(["RECOVERY_FIRST_ARM", "NEVER_WINNER_FIRST_ARM"])].to_dict("records"):
        if record["count"]:
            lines.append(f"- {record['variant']} / {record['cohort']} / {record['next_usable_fast_state']}: {int(record['count'])} ({record['rate_pct']:.6f}%).")
    lines.extend([
        "",
        "## Q10. Secondary all observed ARM cycles",
        "",
        f"secondary cycle rows: {len(cycles)}. 이 결과는 동일 trade의 re-arm이 반복 포함될 수 있어 `SECONDARY / TRADE-WEIGHTED BIAS POSSIBLE`로만 해석한다.",
        "",
        "## 경계와 재현성",
        "",
        "RECOVERY horizon은 first MFE +20% 도달일 직전까지, NEVER_WINNER horizon은 identity lifecycle ∩ SUPPORT_END까지다. 기존 W25/W30 hypothetical exit로 underlying path를 truncate하지 않았다. 기존 artifact는 read-only이며 신규 산출물은 이 진단의 8개 파일이다.",
        "",
        "DESCRIPTIVE ONLY / NOT A STRATEGY PARAMETER: bins are fixed-width descriptive bins and do not select a rule.",
        "",
        "Network requests: 0. Production untouched. No new backtest, Julia, portfolio, daily FAST, optimization, or threshold selection.",
        "",
    ])
    return "\n".join(lines)


def run_analysis() -> dict[str, Any]:
    matched = pd.read_csv(ARMED_MATCHED_PATH)
    events = pd.read_csv(ARMED_EVENT_PATH)
    armed_summary = json.loads(ARMED_SUMMARY_PATH.read_text(encoding="utf-8"))
    control = pd.read_csv(CONTROL_PATH)
    if len(control) != 973 or len(matched) != 1946 or matched["control_trade_id"].nunique() != 973:
        raise AssertionError("existing A/B authority counts are not frozen")
    if armed_summary.get("matched_control_rows") != 973 or armed_summary.get("v0_disabled_parity", {}).get("passed") is not True:
        raise AssertionError("existing A/B summary is not complete and parity-passed")
    if Counter(matched["recovery_class"].drop_duplicates().tolist()) != Counter({"RECOVERY": 1, "NEVER_WINNER": 1}):
        raise AssertionError("unexpected retrospective labels")
    anchors = _anchor_rows(matched, events)
    if Counter(anchors["variant"]) != Counter(EXPECTED_FIRST_ARM_COUNTS):
        raise AssertionError("first ARM cohort count mismatch")

    repository = build_repository_v2(ROOT, end=v3.SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=v3.SUPPORT_END)
    states, daily_by_ticker, state_errors = v0_ab._state_index(control, loader)
    state_counts = Counter(state for values in states.values() for _, state in values)
    domain = _state_domain(state_counts)
    if state_errors != 0:
        raise AssertionError(f"weekly state evaluation errors: {state_errors}")

    primary_rows: list[dict[str, Any]] = []
    for row in anchors.to_dict("records"):
        key = v0_ab._identity_key(row)
        primary_rows.append(_diagnose_cycle(
            row, _date(row["first_armed_date"]), _date(row["first_arm_event_fast_date"]),
            str(row["first_arm_event_fast_state"]), float(row["first_arm_event_close_return_pct"]), float(row["first_arm_event_running_mfe_pct"]),
            daily_by_ticker, states, "PRIMARY_FIRST_ARM", "ARMED", 1,
        ))
    primary = pd.DataFrame(primary_rows)
    primary["first_arm_anchor_parity"] = True

    # Secondary analysis uses only actual ARMED/REARM events already present
    # in the old A/B event log; it never creates cycles after a virtual exit.
    cycle_rows: list[dict[str, Any]] = []
    for event in events.loc[events["event_type"].isin(["ARMED", "REARM"])].to_dict("records"):
        match = matched.loc[(matched["strategy_id"] == event["strategy_id"]) & (matched["control_trade_id"] == event["control_trade_id"])].iloc[0].to_dict()
        cycle_rows.append(_diagnose_cycle(
            match, _date(event["date"]), _date(event["fast_date"]), str(event["fast_state"]), float(event["close_return_pct"]), float(event["running_mfe_pct"]),
            daily_by_ticker, states, "SECONDARY_ALL_ARM_CYCLES", str(event["event_type"]), int(event["arm_cycle"]),
        ))
    cycles = pd.DataFrame(cycle_rows)

    # Add the weak-next-FAST cohorts to the distribution artifact without
    # changing the primary rows or weighting.
    next_dist = pd.concat([
        _distribution_rows(primary, "arm_to_next_fast_delta_pp", "arm_to_next_fast_delta_pp"),
        _distribution_rows(primary, "additional_close_deterioration_pp", "additional_close_deterioration_pp"),
    ], ignore_index=True)
    weak_cohorts: dict[str, pd.DataFrame] = {}
    for variant, group in primary.groupby("variant", sort=True):
        for cohort_name, class_name in [("NEXT_FAST_WEAK_RECOVERY", "RECOVERY"), ("NEXT_FAST_WEAK_NEVER_WINNER", "NEVER_WINNER")]:
            subset = group.loc[(group["recovery_class"] == class_name) & (group["next_usable_fast_state"].isin(WEAK_STATES))].copy()
            weak_cohorts[cohort_name] = pd.concat([weak_cohorts.get(cohort_name, primary.iloc[0:0]), subset], ignore_index=True)
    if weak_cohorts:
        weak_dist_delta = _distribution_rows(primary, "arm_to_next_fast_delta_pp", "arm_to_next_fast_delta_pp", weak_cohorts)
        weak_dist_delta = weak_dist_delta.loc[weak_dist_delta["cohort"].isin(weak_cohorts)]
        weak_dist_det = _distribution_rows(primary, "additional_close_deterioration_pp", "additional_close_deterioration_pp", weak_cohorts)
        weak_dist_det = weak_dist_det.loc[weak_dist_det["cohort"].isin(weak_cohorts)]
        next_dist = pd.concat([next_dist, weak_dist_delta, weak_dist_det], ignore_index=True)

    long_dist = _distribution_rows(primary, "post_arm_long_additional_close_deterioration_pp", "post_arm_long_additional_close_deterioration_pp")
    bins = _bin_rows(primary)
    state_dist = _state_rows(primary)
    summary: dict[str, Any] = {
        "work_id": WORK_ID,
        "status": "COMPLETE",
        "evaluation_start": "2021-04-01",
        "signal_cutoff": "2026-08-14",
        "execution_support_end": "2026-08-21",
        "final_valuation": "2026-08-21 CLOSE",
        "primary_analysis": "FIRST_ARM_ONLY",
        "secondary_analysis": "ALL_OBSERVED_ARM_CYCLES",
        "secondary_warning": "SECONDARY / TRADE-WEIGHTED BIAS POSSIBLE",
        "first_arm_counts": EXPECTED_FIRST_ARM_COUNTS,
        "first_arm_recovery_counts": {variant: {"RECOVERY": int((group["recovery_class"] == "RECOVERY").sum()), "NEVER_WINNER": int((group["recovery_class"] == "NEVER_WINNER").sum())} for variant, group in primary.groupby("variant")},
        "state_domain": {**domain, "weekly_evaluation_error_count": state_errors},
        "state_classification": {"weak": sorted(WEAK_STATES), "strong_recovered": sorted(STRONG_STATES), "unavailable": sorted(UNAVAILABLE_STATES)},
        "next_usable_fast_missing_count": int(primary["next_usable_fast_date"].isna().sum()),
        "next_usable_fast_missing_rate_pct": round(float(primary["next_usable_fast_date"].isna().mean() * 100.0), 6),
        "unavailable_before_next_usable_total": int(primary["unavailable_before_next_usable_count"].sum()),
        "unavailable_before_next_usable_max": int(primary["unavailable_before_next_usable_count"].max()),
        "secondary_cycle_rows": len(cycles),
        "retrospective_labels_analysis_only": True,
        "new_backtest": False,
        "new_exit_simulation": False,
        "threshold_selected": False,
        "daily_fast_created": False,
        "network_requests": 0,
        "production_strategy_modified": False,
        "existing_artifacts_modified": False,
        "source_artifacts": {
            "matched_v0_vs_v1w25_vs_v1w30": str(ARMED_MATCHED_PATH.relative_to(ROOT)),
            "failure_armed_event_log": str(ARMED_EVENT_PATH.relative_to(ROOT)),
            "failure_armed_summary": str(ARMED_SUMMARY_PATH.relative_to(ROOT)),
        },
    }
    # A rule-free descriptive classification: compare central tendency and
    # overlap, without searching for a cutoff or selecting a strategy.
    medians = next_dist.loc[(next_dist["metric"] == "arm_to_next_fast_delta_pp") & (next_dist["cohort"].isin(["RECOVERY_FIRST_ARM", "NEVER_WINNER_FIRST_ARM"]))]
    meaningful = False
    if not medians.empty:
        for variant in medians["variant"].unique():
            pair = medians.loc[medians["variant"] == variant].set_index("cohort")
            if set(["RECOVERY_FIRST_ARM", "NEVER_WINNER_FIRST_ARM"]).issubset(pair.index):
                meaningful |= abs(float(pair.loc["RECOVERY_FIRST_ARM", "median"]) - float(pair.loc["NEVER_WINNER_FIRST_ARM", "median"])) >= 5.0
    summary["separation_conclusion"] = "POST_ARM_DETERIORATION_SHOWS_MEANINGFUL_SEPARATION" if meaningful else "POST_ARM_DETERIORATION_SHOWS_WEAK_SEPARATION"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    primary.to_csv(TRADE_PATH, index=False, lineterminator="\n")
    next_dist.to_csv(NEXT_DIST_PATH, index=False, lineterminator="\n")
    long_dist.to_csv(LONG_DIST_PATH, index=False, lineterminator="\n")
    bins.to_csv(BINS_PATH, index=False, lineterminator="\n")
    state_dist.to_csv(STATE_DIST_PATH, index=False, lineterminator="\n")
    cycles.to_csv(CYCLE_PATH, index=False, lineterminator="\n")
    _write_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, next_dist, long_dist, state_dist, cycles), encoding="utf-8")
    return {"summary": summary, "primary": primary, "next_dist": next_dist, "long_dist": long_dist, "bins": bins, "state_dist": state_dist, "cycles": cycles}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the offline post-arm path diagnostic")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_analysis()
        result["summary"]["network_requests"] = audit.request_count
        _write_json(SUMMARY_PATH, result["summary"])
        print(json.dumps({"status": result["summary"]["status"], "primary_rows": len(result["primary"]), "secondary_rows": len(result["cycles"])}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{WORK_ID} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
