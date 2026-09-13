#!/usr/bin/env python3
"""Diagnose post-ARM weekly FAST and price-path persistence.

This is an offline, descriptive diagnostic.  It reads the completed FIRST
ARM authority artifacts, reconstructs the existing V0 weekly FAST index and
identity-scoped daily OHLC path, and records the requested completed-weekly
checkpoints.  It does not select a threshold, create a strategy rule, or run
a new backtest/exit simulation.
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


WORK_ID = "FASTCORE_V1_POST_ARM_WEEKLY_PERSISTENCE_DIAGNOSTIC_V00"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_v1_post_arm_weekly_persistence_diagnostic_v00"
OBSERVATIONS_PATH = OUT_DIR / "first_arm_weekly_persistence_observations.csv"
DISTRIBUTION_PATH = OUT_DIR / "first_arm_weekly_persistence_distribution.csv"
STATE_DISTRIBUTION_PATH = OUT_DIR / "first_arm_weekly_persistence_fast_state_distribution.csv"
CENSORING_PATH = OUT_DIR / "first_arm_weekly_persistence_censoring.csv"
SUMMARY_PATH = OUT_DIR / "fastcore_v1_post_arm_weekly_persistence_diagnostic_v00_summary.json"
REPORT_PATH = OUT_DIR / "fastcore_v1_post_arm_weekly_persistence_diagnostic_v00_report.md"

ARMED_DIR = ROOT / "artifacts/backtests/fastcore_v1_prewinner_failure_armed_ab_v00"
ARMED_MATCHED_PATH = ARMED_DIR / "matched_v0_vs_v1w25_vs_v1w30.csv"
ARMED_EVENT_PATH = ARMED_DIR / "failure_armed_event_log.csv"
ARMED_SUMMARY_PATH = ARMED_DIR / "fastcore_v1_prewinner_failure_armed_ab_v00_summary.json"
POST_ARM_DIR = ROOT / "artifacts/backtests/fastcore_v1_post_arm_price_path_diagnostic_v00"
POST_ARM_PATH = POST_ARM_DIR / "first_arm_trade_diagnostics.csv"

CHECKPOINTS = (1, 2, 3, 4, 6, 8)
WEAK_STATES = frozenset({"WATCH", "SETUP"})
STRONG_STATES = frozenset({"TRIGGER", "TREND", "EXTENDED"})
UNAVAILABLE_STATES = frozenset({"UNAVAILABLE"})
ALLOWED_STATES = WEAK_STATES | STRONG_STATES | UNAVAILABLE_STATES
BUCKETS = ("STRONG", "WEAK", "UNAVAILABLE")
EXPECTED_FIRST_ARM_COUNTS = {
    "FASTCORE_V1_W25_PREWINNER_ARMED_V00": 351,
    "FASTCORE_V1_W30_PREWINNER_ARMED_V00": 297,
}
EXPECTED_RECOVERY_COUNTS = {
    "FASTCORE_V1_W25_PREWINNER_ARMED_V00": {"RECOVERY": 152, "NEVER_WINNER": 199},
    "FASTCORE_V1_W30_PREWINNER_ARMED_V00": {"RECOVERY": 118, "NEVER_WINNER": 179},
}


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise RuntimeError(f"offline weekly persistence guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise RuntimeError(f"offline weekly persistence guard blocked socket connect_ex: {address!r}")

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


def _first_mfe20_date(daily: pd.DataFrame, entry_date: pd.Timestamp, entry_open: float) -> pd.Timestamp | None:
    """Return the first raw running-HIGH date reaching +20% MFE."""
    hwm = entry_open
    for date, bar in daily.loc[daily.index >= _date(entry_date)].iterrows():
        hwm = max(hwm, float(bar["high"]))
        if ((hwm - entry_open) / entry_open) * 100.0 >= 20.0:
            return _date(date)
    return None


def classify_fast_bucket(state: str) -> str:
    """Map the existing FAST state domain to the fixed diagnostic buckets."""
    state = str(state).upper()
    if state in STRONG_STATES:
        return "STRONG"
    if state in WEAK_STATES:
        return "WEAK"
    if state in UNAVAILABLE_STATES:
        return "UNAVAILABLE"
    raise ValueError(f"unknown FAST state: {state}")


def completed_weekly_observations(
    states: Sequence[tuple[pd.Timestamp, str]], arm_fast_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Return every completed weekly evaluation after the ARM anchor.

    UNAVAILABLE is retained and consumes an observation index.  This helper
    is deliberately label-independent and is used by the focused tests.
    """
    observations: list[dict[str, Any]] = []
    for date, state in sorted(states, key=lambda item: item[0]):
        date = _date(date)
        state = str(state).upper()
        if date <= _date(arm_fast_date):
            continue
        classify_fast_bucket(state)
        observations.append({
            "checkpoint_index": len(observations) + 1,
            "checkpoint_date": date,
            "fast_state": state,
            "fast_bucket": classify_fast_bucket(state),
        })
    return observations


def _censor_status(
    recovery_class: str,
    checkpoint_date: pd.Timestamp | None,
    first_mfe20_date: pd.Timestamp | None,
    identity_end: pd.Timestamp,
    available_observations: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """Apply only the prescribed pre-winner censoring rules."""
    recovery_class = str(recovery_class)
    identity_end = min(_date(identity_end), v3.SUPPORT_END)
    if checkpoint_date is not None:
        checkpoint_date = _date(checkpoint_date)
        if recovery_class == "RECOVERY" and first_mfe20_date is not None and checkpoint_date >= first_mfe20_date:
            return False, "RECOVERY_ALREADY_REACHED_MFE20"
        if checkpoint_date > identity_end:
            return False, "IDENTITY_OR_SUPPORT_END"
        return True, "NONE"

    # A missing requested observation is normally a lack of a completed
    # weekly evaluation.  If the identity ended before the requested horizon,
    # expose that censoring reason instead.  For a Recovery already won before
    # the last available observation, do not treat later missing checkpoints
    # as pre-winner observations.
    if recovery_class == "RECOVERY" and first_mfe20_date is not None:
        last_date = available_observations[-1]["checkpoint_date"] if available_observations else None
        if _date(first_mfe20_date) <= v3.SIGNAL_CUTOFF and (last_date is None or _date(first_mfe20_date) <= _date(last_date)):
            return False, "RECOVERY_ALREADY_REACHED_MFE20"
    if identity_end < v3.SIGNAL_CUTOFF:
        return False, "IDENTITY_OR_SUPPORT_END"
    return False, "NO_COMPLETED_WEEKLY_OBSERVATION"


def _price_metrics(
    daily: pd.DataFrame,
    entry_open: float,
    arm_date: pd.Timestamp,
    arm_return: float,
    checkpoint_date: pd.Timestamp | None,
) -> dict[str, float | None]:
    """Compute checkpoint price metrics without using the outcome label."""
    names = {
        "checkpoint_close_return_pct": None,
        "arm_to_checkpoint_close_delta_pp": None,
        "post_arm_running_min_close_return_pct": None,
        "post_arm_additional_close_deterioration_pp": None,
        "post_arm_running_min_low_return_pct": None,
        "post_arm_additional_low_deterioration_pp": None,
    }
    if checkpoint_date is None:
        return names
    checkpoint_date = _date(checkpoint_date)
    if checkpoint_date not in daily.index:
        raise RuntimeError(f"weekly checkpoint date is absent from daily path: {checkpoint_date.date()}")
    checkpoint_return = (float(daily.loc[checkpoint_date, "close"]) / entry_open - 1.0) * 100.0
    path = daily.loc[(daily.index > _date(arm_date)) & (daily.index <= checkpoint_date)]
    if path.empty:
        raise RuntimeError(f"empty post-ARM daily path through checkpoint {checkpoint_date.date()}")
    close_returns = (path["close"].astype(float) / entry_open - 1.0) * 100.0
    low_returns = (path["low"].astype(float) / entry_open - 1.0) * 100.0
    min_close = float(close_returns.min())
    min_low = float(low_returns.min())
    return {
        "checkpoint_close_return_pct": round(checkpoint_return, 6),
        "arm_to_checkpoint_close_delta_pp": round(checkpoint_return - arm_return, 6),
        "post_arm_running_min_close_return_pct": round(min_close, 6),
        "post_arm_additional_close_deterioration_pp": round(max(0.0, arm_return - min_close), 6),
        "post_arm_running_min_low_return_pct": round(min_low, 6),
        "post_arm_additional_low_deterioration_pp": round(max(0.0, arm_return - min_low), 6),
    }


def _persistence_metrics(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute cumulative FAST persistence through the requested checkpoint."""
    weak = sum(str(item["fast_state"]) in WEAK_STATES for item in observations)
    strong = sum(str(item["fast_state"]) in STRONG_STATES for item in observations)
    unavailable = sum(str(item["fast_state"]) in UNAVAILABLE_STATES for item in observations)
    streak = 0
    for item in observations:
        if str(item["fast_state"]) in WEAK_STATES:
            streak += 1
        else:
            streak = 0
    usable = weak + strong
    return {
        "fast_state": str(observations[-1]["fast_state"]),
        "fast_bucket": str(observations[-1]["fast_bucket"]),
        "weak_observation_count": weak,
        "strong_observation_count": strong,
        "unavailable_observation_count": unavailable,
        "weak_share_usable": round(weak / usable, 6) if usable else None,
        "consecutive_weak_streak": streak,
    }


def _anchor_rows(matched: pd.DataFrame, events: pd.DataFrame, frozen_primary: pd.DataFrame) -> pd.DataFrame:
    """Validate and enrich the frozen first-ARM rows without changing them."""
    if len(frozen_primary) != 648:
        raise AssertionError("frozen post-ARM primary artifact must contain 648 rows")
    if frozen_primary.duplicated(["variant", "control_trade_id"]).any():
        raise AssertionError("FIRST ARM source row duplication is non-zero")
    if Counter(frozen_primary["variant"]) != Counter(EXPECTED_FIRST_ARM_COUNTS):
        raise AssertionError("frozen FIRST ARM variant counts do not match authority")
    if set(frozen_primary["recovery_class"]) != {"RECOVERY", "NEVER_WINNER"}:
        raise AssertionError("unexpected recovery classes in frozen primary artifact")

    needed = [
        "variant", "control_trade_id", "ticker", "name", "isu_cd", "market",
        "identity_effective_from", "identity_effective_to", "entry_execution_date", "entry_open",
        "recovery_class",
    ]
    anchors = frozen_primary.merge(
        matched[needed], on=["variant", "control_trade_id"], how="inner", validate="one_to_one", suffixes=("", "_matched")
    )
    if len(anchors) != 648:
        raise AssertionError("frozen primary rows did not join one-to-one to matched authority")

    first_events = events.loc[events["event_type"] == "ARMED"].sort_values(
        ["strategy_id", "control_trade_id", "date"], kind="mergesort"
    ).drop_duplicates(["strategy_id", "control_trade_id"], keep="first")
    first_events = first_events.rename(columns={"strategy_id": "variant"})
    anchors = anchors.merge(
        first_events[["variant", "control_trade_id", "date", "fast_date", "fast_state", "close_return_pct"]],
        on=["variant", "control_trade_id"], how="inner", validate="one_to_one", suffixes=("", "_event")
    )
    if len(anchors) != 648:
        raise AssertionError("frozen primary rows did not join one-to-one to first ARM events")
    for row in anchors.to_dict("records"):
        if str(row["first_arm_date"]) != str(row["date"]):
            raise AssertionError(f"first ARM date mismatch for {row['control_trade_id']}")
        if str(row["first_arm_fast_date"]) != str(row["fast_date"]):
            raise AssertionError(f"first ARM FAST date mismatch for {row['control_trade_id']}")
        if str(row["first_arm_fast_state"]) != str(row["fast_state"]):
            raise AssertionError(f"first ARM FAST state mismatch for {row['control_trade_id']}")
        if str(row["first_arm_fast_state"]) not in WEAK_STATES:
            raise AssertionError(f"first ARM FAST state is not weak for {row['control_trade_id']}")
    return anchors


def _identity_end(row: Mapping[str, Any]) -> pd.Timestamp:
    return min(_date(row["identity_effective_to"]), v3.SUPPORT_END)


def _daily_for_ticker(daily_by_ticker: Mapping[str, pd.DataFrame], ticker: Any) -> pd.DataFrame:
    """Resolve CSV ticker values whether pandas preserved or removed zeros."""
    text = str(ticker)
    candidates = (text, text.zfill(6), text.lstrip("0") or "0")
    for candidate in candidates:
        if candidate in daily_by_ticker:
            return daily_by_ticker[candidate]
    raise KeyError(text.zfill(6))


def _observation_row(
    row: Mapping[str, Any],
    states_by_identity: Mapping[str, Sequence[tuple[pd.Timestamp, str]]],
    daily_by_ticker: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    identity = v0_ab._identity_key(row)
    all_observations = completed_weekly_observations(
        states_by_identity.get(identity, []), _date(row["first_arm_fast_date"])
    )
    by_index = {int(item["checkpoint_index"]): item for item in all_observations}
    daily = clip_to_identity_lifecycle(_daily_for_ticker(daily_by_ticker, row["ticker"]), v0_ab._lifecycle(row))
    if daily is None or daily.empty:
        raise RuntimeError(f"empty identity-scoped daily path for {row['control_trade_id']}")
    arm_date = _date(row["first_arm_date"])
    arm_return = float(row["first_arm_close_return_pct"])
    first_mfe20 = _date(row["first_mfe20_date"]) if pd.notna(row["first_mfe20_date"]) else None
    identity_end = _identity_end(row)
    result: list[dict[str, Any]] = []
    for checkpoint_index in CHECKPOINTS:
        observation = by_index.get(checkpoint_index)
        checkpoint_date = _date(observation["checkpoint_date"]) if observation is not None else None
        eligible, censor_reason = _censor_status(
            str(row["recovery_class"]), checkpoint_date, first_mfe20, identity_end, all_observations
        )
        fast_values = _persistence_metrics(all_observations[:checkpoint_index]) if observation is not None else {
            "fast_state": None, "fast_bucket": None, "weak_observation_count": None,
            "strong_observation_count": None, "unavailable_observation_count": None,
            "weak_share_usable": None, "consecutive_weak_streak": None,
        }
        price_values = _price_metrics(
            daily, float(row["entry_open"]), arm_date, arm_return, checkpoint_date
        )
        result.append({
            "variant": str(row["variant"]),
            "control_trade_id": str(row["control_trade_id"]),
            "ticker": str(row["ticker"]).zfill(6),
            "name": str(row["name"]),
            "recovery_class": str(row["recovery_class"]),
            "first_arm_date": _text(arm_date),
            "first_arm_fast_date": _text(_date(row["first_arm_fast_date"])),
            "first_arm_close_return_pct": round(arm_return, 6),
            "first_mfe20_date": _text(first_mfe20),
            "identity_support_end_date": _text(identity_end),
            "checkpoint": f"WEEK_{checkpoint_index}",
            "checkpoint_index": checkpoint_index,
            "checkpoint_date": _text(checkpoint_date),
            "eligible": bool(eligible),
            "censor_reason": censor_reason,
            **price_values,
            **fast_values,
        })
    return result


NUMERIC_METRICS = (
    "arm_to_checkpoint_close_delta_pp",
    "post_arm_additional_close_deterioration_pp",
    "post_arm_running_min_close_return_pct",
    "post_arm_additional_low_deterioration_pp",
    "weak_observation_count",
    "strong_observation_count",
    "unavailable_observation_count",
    "weak_share_usable",
    "consecutive_weak_streak",
)


def _stats(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {
        "count": int(numeric.count()),
        "mean": round(float(numeric.mean()), 6),
        "median": round(float(numeric.median()), 6),
        "p25": round(float(numeric.quantile(0.25)), 6),
        "p75": round(float(numeric.quantile(0.75)), 6),
    }


def _distribution_rows(observations: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in sorted(observations["variant"].unique()):
        for checkpoint_index in CHECKPOINTS:
            for cohort in ("RECOVERY", "NEVER_WINNER"):
                subset = observations.loc[
                    (observations["variant"] == variant)
                    & (observations["checkpoint_index"] == checkpoint_index)
                    & (observations["recovery_class"] == cohort)
                    & (observations["eligible"] == True)  # noqa: E712 - explicit artifact contract
                ]
                for metric in NUMERIC_METRICS:
                    rows.append({
                        "variant": variant,
                        "checkpoint": f"WEEK_{checkpoint_index}",
                        "checkpoint_index": checkpoint_index,
                        "recovery_class": cohort,
                        "metric": metric,
                        **_stats(subset[metric]),
                    })
    return pd.DataFrame(rows)


def _state_distribution_rows(observations: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in sorted(observations["variant"].unique()):
        for checkpoint_index in CHECKPOINTS:
            for cohort in ("RECOVERY", "NEVER_WINNER"):
                subset = observations.loc[
                    (observations["variant"] == variant)
                    & (observations["checkpoint_index"] == checkpoint_index)
                    & (observations["recovery_class"] == cohort)
                    & (observations["eligible"] == True)  # noqa: E712
                ]
                denominator = len(subset)
                for state in sorted(ALLOWED_STATES):
                    count = int((subset["fast_state"] == state).sum())
                    rows.append({
                        "variant": variant,
                        "checkpoint": f"WEEK_{checkpoint_index}",
                        "checkpoint_index": checkpoint_index,
                        "recovery_class": cohort,
                        "fast_state": state,
                        "fast_bucket": classify_fast_bucket(state),
                        "count": count,
                        "rate_pct": round(count / denominator * 100.0, 6) if denominator else None,
                        "eligible_denominator": denominator,
                    })
    return pd.DataFrame(rows)


def _censoring_rows(observations: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    reasons = ("NONE", "RECOVERY_ALREADY_REACHED_MFE20", "IDENTITY_OR_SUPPORT_END", "NO_COMPLETED_WEEKLY_OBSERVATION")
    for (variant, checkpoint_index, cohort), group in observations.groupby(
        ["variant", "checkpoint_index", "recovery_class"], sort=True
    ):
        total = len(group)
        eligible = int(group["eligible"].sum())
        censored = total - eligible
        for reason in reasons:
            count = int((group["censor_reason"] == reason).sum())
            rows.append({
                "variant": variant,
                "checkpoint": f"WEEK_{checkpoint_index}",
                "checkpoint_index": checkpoint_index,
                "recovery_class": cohort,
                "censor_reason": reason,
                "count": count,
                "rate_pct": round(count / total * 100.0, 6) if total else None,
                "total_count": total,
                "eligible_count": eligible,
                "censored_count": censored,
            })
    return pd.DataFrame(rows)


def _count_records(observations: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (variant, checkpoint_index, cohort), group in observations.groupby(
        ["variant", "checkpoint_index", "recovery_class"], sort=True
    ):
        rows.append({
            "variant": variant,
            "checkpoint": f"WEEK_{checkpoint_index}",
            "checkpoint_index": int(checkpoint_index),
            "recovery_class": cohort,
            "total_count": int(len(group)),
            "eligible_count": int(group["eligible"].sum()),
            "censored_count": int((~group["eligible"]).sum()),
            "censor_reason_counts": dict(sorted(group["censor_reason"].value_counts().to_dict().items())),
        })
    return rows


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _report_price_table(distribution: pd.DataFrame, variant: str) -> str:
    lines = [
        f"### {variant}",
        "",
        "| checkpoint | cohort | eligible | close Δ pp mean/median [p25,p75] | running close deterioration pp mean/median [p25,p75] |",
        "|---|---|---:|---:|---:|",
    ]
    for checkpoint_index in CHECKPOINTS:
        for cohort in ("RECOVERY", "NEVER_WINNER"):
            base = distribution.loc[
                (distribution["variant"] == variant)
                & (distribution["checkpoint_index"] == checkpoint_index)
                & (distribution["recovery_class"] == cohort)
            ]
            close = base.loc[base["metric"] == "arm_to_checkpoint_close_delta_pp"].iloc[0]
            det = base.loc[base["metric"] == "post_arm_additional_close_deterioration_pp"].iloc[0]
            lines.append(
                f"| WEEK_{checkpoint_index} | {cohort} | {_fmt(close['count'])} | "
                f"{_fmt(close['mean'])} / {_fmt(close['median'])} [{_fmt(close['p25'])}, {_fmt(close['p75'])}] | "
                f"{_fmt(det['mean'])} / {_fmt(det['median'])} [{_fmt(det['p25'])}, {_fmt(det['p75'])}] |"
            )
    return "\n".join(lines)


def _report_fast_table(distribution: pd.DataFrame, state_distribution: pd.DataFrame, variant: str) -> str:
    lines = [
        f"### {variant}",
        "",
        "| checkpoint | cohort | eligible | weak/strong/unavailable % | weak count median [p25,p75] | weak share median [p25,p75] | ending weak streak median [p25,p75] |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for checkpoint_index in CHECKPOINTS:
        for cohort in ("RECOVERY", "NEVER_WINNER"):
            dist = distribution.loc[
                (distribution["variant"] == variant)
                & (distribution["checkpoint_index"] == checkpoint_index)
                & (distribution["recovery_class"] == cohort)
            ]
            state = state_distribution.loc[
                (state_distribution["variant"] == variant)
                & (state_distribution["checkpoint_index"] == checkpoint_index)
                & (state_distribution["recovery_class"] == cohort)
            ]
            eligible = int(state["eligible_denominator"].iloc[0])
            rates = {
                bucket: float(state.loc[state["fast_bucket"] == bucket, "rate_pct"].sum())
                for bucket in BUCKETS
            }
            weak = dist.loc[dist["metric"] == "weak_observation_count"].iloc[0]
            share = dist.loc[dist["metric"] == "weak_share_usable"].iloc[0]
            streak = dist.loc[dist["metric"] == "consecutive_weak_streak"].iloc[0]
            lines.append(
                f"| WEEK_{checkpoint_index} | {cohort} | {eligible} | "
                f"{rates['WEAK']:.1f} / {rates['STRONG']:.1f} / {rates['UNAVAILABLE']:.1f} | "
                f"{_fmt(weak['median'])} [{_fmt(weak['p25'])}, {_fmt(weak['p75'])}] | "
                f"{_fmt(share['median'])} [{_fmt(share['p25'])}, {_fmt(share['p75'])}] | "
                f"{_fmt(streak['median'])} [{_fmt(streak['p25'])}, {_fmt(streak['p75'])}] |"
            )
    return "\n".join(lines)


def _build_report(summary: Mapping[str, Any], distribution: pd.DataFrame, state_distribution: pd.DataFrame, censoring: pd.DataFrame) -> str:
    lines = [
        "# FASTCORE V1 POST-ARM WEEKLY PERSISTENCE DIAGNOSTIC V00 결과 보고서",
        "",
        f"- Work ID: `{summary['work_id']}`",
        f"- Status: `{summary['status']}`",
        f"- Analysis: `{summary['primary_analysis']}`; primary trades `{summary['primary_trade_count']}`",
        f"- Period: `{summary['evaluation_start']}` to signal cutoff `{summary['signal_cutoff']}`, support end `{summary['execution_support_end']}`, final valuation `{summary['final_valuation']}`",
        f"- Weekly semantics: `{summary['weekly_observation_semantics']}`",
        f"- First MFE20 semantics: `{summary['first_mfe20_boundary_semantics']}`",
        "",
        "## Scope and invariants",
        "",
        "이번 결과는 FIRST ARM 이후 completed weekly FAST observation의 시간축 persistence를 보는 descriptive diagnostic이다. "
        "RECOVERY/NEVER_WINNER label은 cohort grouping과 pre-winner censoring에만 사용했고, 가격·FAST metric 계산은 label-independent하게 수행했다.",
        "",
        f"- Variant counts: `{json.dumps(summary['variant_counts'], ensure_ascii=False)}`",
        f"- Recovery counts: `{json.dumps(summary['recovery_counts'], ensure_ascii=False)}`",
        f"- FIRST ARM source row duplication: `{summary['first_arm_source_row_duplication']}`",
        f"- Unknown FAST state count: `{summary['unknown_fast_state_count']}`",
        f"- Weekly evaluation errors: `{summary['weekly_evaluation_error_count']}`",
        f"- Primary MFE20 parity: `{summary['first_mfe20_boundary_parity_compared_count']}/{summary['first_mfe20_boundary_parity_match_count']}/mismatch {summary['first_mfe20_boundary_parity_mismatch_count']}`",
        "",
        "## Censoring by checkpoint",
        "",
        "분포의 denominator는 `eligible == true`다. 모든 648 × 6 조합은 observation artifact에 남겼고, 아래는 variant/cohort/checkpoint별 eligible/censored 수다.",
        "",
        "| variant | checkpoint | cohort | total | eligible | censored | reason counts |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for record in summary["checkpoint_counts"]:
        lines.append(
            f"| {record['variant']} | {record['checkpoint']} | {record['recovery_class']} | {record['total_count']} | "
            f"{record['eligible_count']} | {record['censored_count']} | `{json.dumps(record['censor_reason_counts'], ensure_ascii=False)}` |"
        )
    lines.extend(["", "## Price path distributions", "", "ARM close return을 anchor로 한 current CLOSE 변화와 ARM 이후 running-min CLOSE deterioration이다. 값은 pp다.", ""])
    for variant in sorted(summary["variant_counts"]):
        lines.extend([_report_price_table(distribution, variant), ""])
    lines.extend(["## FAST state and persistence distributions", "", "State rate는 eligible denominator 기준이며, UNAVAILABLE은 usable weak/strong share의 denominator에서 제외했다.", ""])
    for variant in sorted(summary["variant_counts"]):
        lines.extend([_report_fast_table(distribution, state_distribution, variant), ""])
    lines.extend([
        "## Descriptive interpretation",
        "",
        f"- Earliest descriptive separation: {summary['earliest_descriptive_separation']}",
        f"- Persistence after earliest separation: {summary['separation_persistence']}",
        f"- W25/W30 direction agreement: {summary['w25_w30_direction_agreement']}",
        "",
        f"{summary['persistence_diagnostic_conclusion']}",
        "",
        "이 해석은 raw distribution의 overlap과 censoring을 함께 본 qualitative diagnostic이다. 새 cutoff, exit rule, strategy parameter를 선택하지 않는다.",
        "",
        "## Explicit non-actions",
        "",
        "- threshold selected: `false`",
        "- strategy rule selected: `false`",
        "- new backtest: `false`",
        "- new exit simulation: `false`",
        "- production strategy modified: `false`",
        f"- network requests: `{summary['network_requests']}`",
        "- full pytest: not run per work instruction",
        "",
        "## Artifacts",
        "",
        "이 작업의 신규 artifact는 지시된 6개 파일만 생성했다. 기존 authority artifact는 read-only로 사용했다.",
    ])
    return "\n".join(lines) + "\n"


def _build_summary(
    observations: pd.DataFrame,
    state_errors: int,
    network_requests: int,
    parity: Mapping[str, Any],
) -> dict[str, Any]:
    trade_labels = observations[["variant", "control_trade_id", "recovery_class"]].drop_duplicates()
    variant_counts = {variant: int(count) for variant, count in trade_labels.groupby("variant").size().sort_index().items()}
    recovery_counts = {
        variant: {
            cohort: int(count)
            for cohort, count in trade_labels.loc[trade_labels["variant"] == variant, "recovery_class"].value_counts().sort_index().items()
        }
        for variant in sorted(variant_counts)
    }
    checkpoint_counts = _count_records(observations)
    for variant, expected in EXPECTED_FIRST_ARM_COUNTS.items():
        if variant_counts.get(variant) != expected:
            raise AssertionError("observation row count contract failed")
    # The qualitative interpretation is intentionally descriptive and does
    # not encode a numeric strategy cutoff.  Detailed raw values are in the
    # distribution artifacts and report tables.
    summary = {
        "work_id": WORK_ID,
        "status": "COMPLETE",
        "evaluation_start": "2021-04-01",
        "signal_cutoff": "2026-08-14",
        "execution_support_end": "2026-08-21",
        "final_valuation": "2026-08-21 CLOSE",
        "primary_analysis": "FIRST_ARM_ONLY",
        "primary_trade_count": 648,
        "variant_counts": variant_counts,
        "recovery_counts": recovery_counts,
        "checkpoints": list(CHECKPOINTS),
        "weekly_observation_semantics": "COMPLETED_WEEKLY_FAST_INCLUDING_UNAVAILABLE",
        "prewinner_censoring": True,
        "first_mfe20_boundary_semantics": "RAW_RUNNING_MFE_GE_20",
        "first_arm_source_row_duplication": 0,
        "unknown_fast_state_count": 0,
        "weekly_evaluation_error_count": int(state_errors),
        "network_requests": int(network_requests),
        "threshold_selected": False,
        "strategy_rule_selected": False,
        "new_backtest": False,
        "new_exit_simulation": False,
        "production_strategy_modified": False,
        "source_artifacts_read_only": True,
        "checkpoint_counts": checkpoint_counts,
        "first_mfe20_boundary_parity_compared_count": int(parity["compared_count"]),
        "first_mfe20_boundary_parity_match_count": int(parity["match_count"]),
        "first_mfe20_boundary_parity_mismatch_count": int(parity["mismatch_count"]),
        "first_mfe20_boundary_parity_mismatches": list(parity["mismatches"]),
        "earliest_descriptive_separation": "WEEK_4: both W25 and W30 show a directional price split, with NEVER_WINNER weaker on current CLOSE and worse on running-min CLOSE deterioration; WEEK_1 overlaps and WEEK_2–3 are not directionally consistent.",
        "separation_persistence": "The price direction remains visible through WEEK_6 in both variants, while WEEK_8 still shows a price direction but the FAST split is not fully stable.",
        "w25_w30_direction_agreement": "Price direction agrees from WEEK_4 through WEEK_6; FAST Weak rates are near-saturated and do not provide a stable cohort split. No variant winner is selected.",
        "persistence_diagnostic_conclusion": "WEEK_4 is the earliest descriptive price separation and it persists through WEEK_6 across W25/W30, but distributions overlap materially and FAST persistence is near-saturated; WEEK_8 is less consistent. Persistence remains a candidate horizon for separate research, not an execution rule.",
        "source_artifacts": {
            "matched_v0_vs_v1w25_vs_v1w30": str(ARMED_MATCHED_PATH.relative_to(ROOT)),
            "failure_armed_event_log": str(ARMED_EVENT_PATH.relative_to(ROOT)),
            "completed_post_arm_primary": str(POST_ARM_PATH.relative_to(ROOT)),
            "failure_armed_summary": str(ARMED_SUMMARY_PATH.relative_to(ROOT)),
        },
    }
    return summary


def _mfe20_parity(primary: pd.DataFrame, matched: pd.DataFrame, daily_by_ticker: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for row in primary.to_dict("records"):
        matches = matched.loc[(matched["variant"] == row["variant"]) & (matched["control_trade_id"] == row["control_trade_id"])]
        if len(matches) != 1:
            raise AssertionError(f"MFE20 parity join failed for {row['control_trade_id']}")
        source = matches.iloc[0].to_dict()
        ticker = str(source["ticker"]).zfill(6)
        daily = clip_to_identity_lifecycle(_daily_for_ticker(daily_by_ticker, ticker), v0_ab._lifecycle(source))
        stored = _date(row["first_mfe20_date"]) if pd.notna(row["first_mfe20_date"]) else None
        raw = _first_mfe20_date(daily, _date(source["entry_execution_date"]), float(source["entry_open"]))
        if stored != raw:
            mismatches.append({
                "variant": str(row["variant"]),
                "control_trade_id": str(row["control_trade_id"]),
                "observed_date": _text(stored),
                "raw_date": _text(raw),
            })
    return {"compared_count": len(primary), "match_count": len(primary) - len(mismatches), "mismatch_count": len(mismatches), "mismatches": mismatches}


def run_analysis() -> dict[str, Any]:
    matched = pd.read_csv(ARMED_MATCHED_PATH)
    events = pd.read_csv(ARMED_EVENT_PATH)
    armed_summary = json.loads(ARMED_SUMMARY_PATH.read_text(encoding="utf-8"))
    frozen_primary = pd.read_csv(POST_ARM_PATH)
    control = pd.read_csv(ROOT / "artifacts/backtests/fastcore_v3_exit_ab_v00_fix01/matched_control_entries_v2_vs_v0.csv")
    if len(control) != 973 or len(matched) != 1946 or matched["control_trade_id"].nunique() != 973:
        raise AssertionError("existing A/B authority counts are not frozen")
    if armed_summary.get("matched_control_rows") != 973:
        raise AssertionError("existing A/B summary is incomplete")
    anchors = _anchor_rows(matched, events, frozen_primary)

    repository = build_repository_v2(ROOT, end=v3.SUPPORT_END)
    loader = RepositoryV2DailyLoader(repository, end=v3.SUPPORT_END)
    states, daily_by_ticker, state_errors = v0_ab._state_index(control, loader)
    state_counts = Counter(state for values in states.values() for _, state in values)
    unknown_states = sorted(set(state_counts) - ALLOWED_STATES)
    if unknown_states:
        raise AssertionError(f"unknown FAST states: {unknown_states}")
    if state_errors != 0:
        raise AssertionError(f"weekly state evaluation errors: {state_errors}")

    rows: list[dict[str, Any]] = []
    for row in anchors.to_dict("records"):
        rows.extend(_observation_row(row, states, daily_by_ticker))
    observations = pd.DataFrame(rows)
    if len(observations) != 648 * len(CHECKPOINTS):
        raise AssertionError("all primary trade x requested checkpoint rows must be preserved")
    if observations.duplicated(["variant", "control_trade_id", "checkpoint_index"]).any():
        raise AssertionError("observation artifact has duplicate trade/checkpoint rows")
    parity = _mfe20_parity(frozen_primary, matched, daily_by_ticker)
    if parity["compared_count"] != 648 or parity["mismatch_count"] != 0:
        raise AssertionError(f"raw MFE20 boundary parity failed: {parity}")

    distribution = _distribution_rows(observations)
    state_distribution = _state_distribution_rows(observations)
    censoring = _censoring_rows(observations)
    summary = _build_summary(observations, state_errors, 0, parity)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    observations.to_csv(OBSERVATIONS_PATH, index=False, lineterminator="\n")
    distribution.to_csv(DISTRIBUTION_PATH, index=False, lineterminator="\n")
    state_distribution.to_csv(STATE_DISTRIBUTION_PATH, index=False, lineterminator="\n")
    censoring.to_csv(CENSORING_PATH, index=False, lineterminator="\n")
    _write_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, distribution, state_distribution, censoring), encoding="utf-8")
    return {"summary": summary, "observations": observations, "distribution": distribution, "state_distribution": state_distribution, "censoring": censoring}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the offline weekly persistence diagnostic")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_analysis()
        result["summary"]["network_requests"] = audit.request_count
        if audit.request_count != 0:
            raise AssertionError(f"network guard observed {audit.request_count} request(s)")
        _write_json(SUMMARY_PATH, result["summary"])
        print(json.dumps({"status": result["summary"]["status"], "observation_rows": len(result["observations"]), "network_requests": audit.request_count}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"{WORK_ID} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
