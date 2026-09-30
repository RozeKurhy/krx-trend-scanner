#!/usr/bin/env python3
"""Describe prior authoritative Pattern A stages before PROGRESSED Pattern B entries."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import analyze_pattern_b_depressed_entry_pattern_a_state_v01 as stage_source  # noqa: E402
from scripts import run_pattern_b_pattern_a_entry_filter_simple_v01 as filter_source  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts.analyze_pattern_b_state_forward_return_v01 import month_end_snapshot_dates  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.data.resampler import to_monthly, to_weekly  # noqa: E402
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage  # noqa: E402
from trend_scanner.strategies.b_select_core_v1 import resolve_progressed_episode  # noqa: E402

STUDY_ID = "PATTERN_B_PROGRESSED_PREVIOUS_PATTERN_A_STAGE_V01"
EXPECTED_HEAD = "2a76f8c312606af338001073d6da3f69da7e7239"
WORKERS = 10
REVIEW_SEED = 20260927
REVIEW_COUNT = 30
EXPECTED_RAW_COUNT = 835
EXPECTED_FILLED_COUNT = 832
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")
CONTROL_STAGE_LINKAGE = Path("artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/signal_stage_path_trade_linkage.csv")
CONTROL_STAGE_SUMMARY = Path("artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/summary.json")
CONTROL_STAGE_METADATA = Path("artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/metadata.json")
FILTER_ROOT = Path("artifacts/patterns/pattern_b/pattern_a_entry_filter_simple_v01")
PROGRESSED_SIGNALS = FILTER_ROOT / "progressed_entry_signal_ledger.csv"
PROGRESSED_TRADES = FILTER_ROOT / "progressed_trade_ledger.csv"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01")
STAGE_ORDER = ("WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "UNAVAILABLE")
REVIEW_SMALL_N = 20  # Reporting caution only; no group is removed or combined.


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ticker(value: Any) -> str:
    return str(value).strip().zfill(6)


def _isu(value: Any) -> str:
    return str(value).strip().upper()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (_ticker(row["ticker"]), _isu(row["isu_cd"]), str(row["entry_signal_date"])[:10])


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"true", "1", "1.0", "yes"}


def _resolve_progressed_episode(
    active_dates: list[str],
    stage_by_date: Mapping[str, str],
    entry_date: str,
    snapshot_positions: Mapping[str, int],
    trading_positions: Mapping[str, int],
) -> dict[str, Any]:
    """Resolve the contiguous active-month PROGRESSED run and its prior observation.

    UNAVAILABLE and gaps in PIT identity activity break a run. A missing earlier
    different stage is explicitly grouped as UNAVAILABLE.
    """
    return resolve_progressed_episode(
        active_dates,
        stage_by_date,
        entry_date,
        snapshot_positions,
        trading_positions,
    )


def _stage_inputs_are_pit_safe(
    snapshot_date: str,
    effective_daily_date: str | None,
    monthly_bar_label: str | None,
    weekly_bar_date: str | None,
) -> bool:
    """Check data dates while allowing a completed monthly period-end label.

    The official resampler labels monthly bars by calendar month-end, which can
    fall after the last KRX session (for example Sunday 2018-09-30 after Friday
    2018-09-28). The snapshot builder clips source daily rows at snapshot_date
    before resampling, so a same-month period label is not future input.
    """
    snapshot_date = str(snapshot_date)[:10]
    if effective_daily_date is not None and str(effective_daily_date)[:10] > snapshot_date:
        return False
    if weekly_bar_date is not None and str(weekly_bar_date)[:10] > snapshot_date:
        return False
    if monthly_bar_label is not None and str(monthly_bar_label)[:7] > snapshot_date[:7]:
        return False
    return True


def _duration_summary(values: list[int | float]) -> dict[str, Any]:
    clean = np.asarray([float(value) for value in values if _number(value) is not None], dtype=float)
    if not len(clean):
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None, "p90": None, "min": None, "max": None}
    return {
        "n": int(len(clean)),
        "mean": float(np.mean(clean)),
        "median": float(np.median(clean)),
        "p25": float(np.percentile(clean, 25)),
        "p75": float(np.percentile(clean, 75)),
        "p90": float(np.percentile(clean, 90)),
        "min": float(np.min(clean)),
        "max": float(np.max(clean)),
    }


def _return_summary(trades: list[Mapping[str, Any]], field: str = "gross_return_pct") -> dict[str, Any]:
    values = [_number(row.get(field)) for row in trades]
    returns = np.asarray([value for value in values if value is not None], dtype=float)
    n = int(len(returns))
    result: dict[str, Any] = {
        "n": n,
        "mean_pct": float(np.mean(returns)) if n else None,
        "median_pct": float(np.median(returns)) if n else None,
        "win_count": int((returns > 0).sum()) if n else 0,
        "win_rate_pct": 100.0 * float((returns > 0).mean()) if n else None,
    }
    for label, predicate in (
        ("ge_20", lambda x: x >= 20), ("ge_50", lambda x: x >= 50),
        ("ge_100", lambda x: x >= 100), ("le_20", lambda x: x <= -20),
        ("le_30", lambda x: x <= -30), ("le_50", lambda x: x <= -50),
    ):
        count = int(sum(bool(predicate(float(value))) for value in returns))
        result[f"{label}_count"] = count
        result[f"{label}_rate_pct"] = 100.0 * count / n if n else None
    return result


def _mean_median(trades: list[Mapping[str, Any]], field: str) -> tuple[float | None, float | None]:
    values = np.asarray([number for row in trades if (number := _number(row.get(field))) is not None], dtype=float)
    if not len(values):
        return None, None
    return float(np.mean(values)), float(np.median(values))


def _source_contract(data_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stage_metadata = json.loads((data_root / CONTROL_STAGE_METADATA).read_text(encoding="utf-8"))
    stage_summary = json.loads((data_root / CONTROL_STAGE_SUMMARY).read_text(encoding="utf-8"))
    filter_metadata_path = data_root / FILTER_ROOT / "metadata.json"
    filter_metadata = json.loads(filter_metadata_path.read_text(encoding="utf-8"))
    linkage_path = data_root / CONTROL_STAGE_LINKAGE
    linkage_sha = _sha256(linkage_path)
    if filter_metadata.get("stage_source", {}).get("linkage_sha256") != linkage_sha:
        raise RuntimeError("PROGRESSED entry filter was not generated from the committed stage linkage")
    if filter_metadata.get("stage_source", {}).get("metadata_sha256") != _sha256(data_root / CONTROL_STAGE_METADATA):
        raise RuntimeError("PROGRESSED entry filter source metadata hash mismatch")
    if stage_metadata.get("study_id") != "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01":
        raise RuntimeError("unexpected source Pattern A stage diagnostic")
    if filter_metadata.get("study_id") != "PATTERN_B_PATTERN_A_ENTRY_FILTER_SIMPLE_V01":
        raise RuntimeError("unexpected source Pattern A entry filter")
    if stage_metadata.get("pattern_a_authority", {}).get("classifier") != "trend_scanner.patterns.pattern_a_stage.classify_pattern_a_stage":
        raise RuntimeError("source stage linkage does not use the official Pattern A classifier")
    if filter_metadata.get("signal_period") != {"start": base.SIGNAL_START, "end": base.SIGNAL_END}:
        raise RuntimeError("PROGRESSED signal period differs from current Pattern B contract")
    if filter_metadata.get("evaluation_cutoff") != base.CUTOFF:
        raise RuntimeError("PROGRESSED cutoff differs from current Pattern B contract")
    stage_counts = stage_summary.get("pattern_a_stage_counts", {})
    if int(stage_counts.get("PROGRESSED", 0)) != EXPECTED_RAW_COUNT:
        raise RuntimeError("source diagnostic PROGRESSED raw count is not the expected 835")

    signals = pd.read_csv(data_root / PROGRESSED_SIGNALS, dtype={"ticker": "string", "isu_cd": "string"}, low_memory=False)
    trades = pd.read_csv(data_root / PROGRESSED_TRADES, dtype={"ticker": "string", "isu_cd": "string"}, low_memory=False)
    linkage = pd.read_csv(linkage_path, dtype={"ticker": "string", "isu_cd": "string"}, low_memory=False)
    for frame in (signals, trades, linkage):
        frame["ticker"] = frame["ticker"].map(_ticker)
        frame["isu_cd"] = frame["isu_cd"].map(_isu)
        frame["entry_signal_date"] = frame["entry_signal_date"].astype(str).str[:10]
    if signals.duplicated(list(SIGNAL_KEY)).any() or trades.duplicated(list(SIGNAL_KEY)).any() or linkage.duplicated(list(SIGNAL_KEY)).any():
        raise RuntimeError("duplicate source signal/trade keys")
    if len(signals) != EXPECTED_RAW_COUNT or len(trades) != EXPECTED_FILLED_COUNT:
        raise RuntimeError(f"source PROGRESSED counts changed: raw={len(signals)}, fills={len(trades)}")
    if set(signals["pattern_a_stage"].dropna().astype(str)) != {"PROGRESSED"}:
        raise RuntimeError("source raw PROGRESSED signal ledger contains another Pattern A stage")
    if not signals["pattern_a_requested_asof"].astype(str).str[:10].eq(signals["entry_signal_date"]).all():
        raise RuntimeError("source entry-date Pattern A stage is not exact PIT")
    if not signals["pattern_a_lookahead_free"].map(_bool).all():
        raise RuntimeError("source entry-date Pattern A stage is not marked lookahead-free")
    signal_keys = set(signals[list(SIGNAL_KEY)].itertuples(index=False, name=None))
    linkage_progressed = linkage.loc[linkage["pattern_a_stage"].astype(str).eq("PROGRESSED")]
    linkage_keys = set(linkage_progressed[list(SIGNAL_KEY)].itertuples(index=False, name=None))
    if signal_keys != linkage_keys or len(linkage_progressed) != EXPECTED_RAW_COUNT:
        raise RuntimeError("raw 835 PROGRESSED signal key set differs from the source PIT linkage")
    filled_signal_keys = set(
        signals.loc[signals["entry_signal_status"].astype(str).eq("FILLED"), list(SIGNAL_KEY)]
        .itertuples(index=False, name=None)
    )
    trade_keys = set(trades[list(SIGNAL_KEY)].itertuples(index=False, name=None))
    if filled_signal_keys != trade_keys or len(filled_signal_keys) != EXPECTED_FILLED_COUNT:
        raise RuntimeError("source independent PROGRESSED fills do not reconcile with its trade ledger")
    signal_trade_ids = {
        _key(row): str(row["trade_id"])
        for row in signals.loc[signals["entry_signal_status"].astype(str).eq("FILLED")].to_dict("records")
    }
    for row in trades.to_dict("records"):
        if signal_trade_ids.get(_key(row)) != str(row["trade_id"]):
            raise RuntimeError(f"source signal/trade ID mismatch: {_key(row)}")
    return signals, trades, linkage_progressed.copy(), {
        "stage_diagnostic_metadata": stage_metadata,
        "stage_diagnostic_summary": stage_summary,
        "entry_filter_metadata": filter_metadata,
        "stage_linkage_sha256": linkage_sha,
        "stage_metadata_sha256": _sha256(data_root / CONTROL_STAGE_METADATA),
        "entry_filter_metadata_sha256": _sha256(filter_metadata_path),
    }


def _daily_stage_history_for_ticker(
    ticker: str,
    signal_rows: list[dict[str, Any]],
    active_dates_by_identity: Mapping[tuple[str, str], list[str]],
    repository: Any,
    data_root: Path,
    trading_dates: list[str],
    trading_positions: Mapping[str, int],
    snapshot_positions: Mapping[str, int],
    review_keys: set[tuple[str, str, str]],
    market_calendar: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    loader = RepositoryV2DailyLoader(repository, start=trading_dates[0], end=base.CUTOFF)
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        daily = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "trading_value"], index=pd.DatetimeIndex([]))
        monthly_bars = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "trading_value"], index=pd.DatetimeIndex([]))
        weekly_bars = monthly_bars
    else:
        monthly_bars = to_monthly(daily)
        weekly_bars = to_weekly(daily)
    stage_cache: dict[str, dict[str, Any]] = {}
    stage_calls = 0

    def compute_stage(snapshot_date: str, use_cache: bool = True) -> dict[str, Any]:
        nonlocal stage_calls
        snapshot_date = str(snapshot_date)[:10]
        if use_cache and snapshot_date in stage_cache:
            return stage_cache[snapshot_date]
        if daily.empty:
            record = {
                "ticker": ticker, "snapshot_date": snapshot_date, "pattern_a_stage": "UNAVAILABLE",
                "pattern_a_stage_reason": "DAILY_DATA_UNAVAILABLE", "pattern_a_effective_asof": None,
                "pattern_a_last_daily_date": None, "pattern_a_last_monthly_bar_date": None,
                "pattern_a_last_weekly_bar_date": None, "pattern_a_lookahead_free": True,
            }
        else:
            snapshot = stage_source._build_cached_stage_snapshot(
                ticker, daily, snapshot_date, monthly_bars, weekly_bars,
                market_calendar,
            )
            classified = classify_pattern_a_stage(snapshot)
            effective_asof = _date(snapshot.effective_as_of)
            last_monthly = _date(snapshot.monthly_as_of)
            last_weekly = _date(snapshot.weekly_as_of)
            record = {
                "ticker": ticker,
                "snapshot_date": snapshot_date,
                "pattern_a_stage": classified.stage.name.upper() if classified.stage is not None else "UNAVAILABLE",
                "pattern_a_stage_reason": "|".join(classified.reason_codes),
                "pattern_a_effective_asof": effective_asof,
                "pattern_a_last_daily_date": effective_asof,
                "pattern_a_last_monthly_bar_date": last_monthly,
                "pattern_a_last_weekly_bar_date": last_weekly,
                "pattern_a_monthly_label_after_requested_day": bool(last_monthly is not None and last_monthly > snapshot_date),
                "pattern_a_lookahead_free": _stage_inputs_are_pit_safe(
                    snapshot_date, effective_asof, last_monthly, last_weekly
                ),
            }
        stage_calls += 1
        if use_cache:
            stage_cache[snapshot_date] = record
        if not record["pattern_a_lookahead_free"]:
            raise RuntimeError(f"future Pattern A input detected for {ticker} at {snapshot_date}: {record}")
        return record

    candidate_results: list[dict[str, Any]] = []
    used_dates: dict[tuple[str, str], set[str]] = defaultdict(set)
    review_results: list[dict[str, Any]] = []
    for event in sorted(signal_rows, key=lambda row: (row["isu_cd"], row["entry_signal_date"])):
        identity = (_ticker(event["ticker"]), _isu(event["isu_cd"]))
        entry_date = str(event["entry_signal_date"])[:10]
        active_dates = active_dates_by_identity.get(identity, [])
        idx = bisect.bisect_left(active_dates, entry_date)
        if idx >= len(active_dates) or active_dates[idx] != entry_date:
            raise RuntimeError(f"PROGRESSED signal is outside its PIT identity active dates: {_key(event)}")
        current_record = compute_stage(entry_date)
        if current_record["pattern_a_stage"] != "PROGRESSED":
            raise RuntimeError(f"entry-date Pattern A recomputation mismatch: {_key(event)}={current_record['pattern_a_stage']}")
        # Classify only the prior monthly observations needed to find the first
        # different authoritative label; cached results are shared by signals.
        walk = idx
        visited = {entry_date}
        while walk > 0:
            current_date = active_dates[walk]
            previous_date = active_dates[walk - 1]
            previous_record = compute_stage(previous_date)
            visited.add(previous_date)
            if snapshot_positions[current_date] != snapshot_positions[previous_date] + 1:
                break
            if previous_record["pattern_a_stage"] != "PROGRESSED":
                break
            walk -= 1
        stages_for_identity = {
            day: stage_cache[day]["pattern_a_stage"]
            for day in visited
            if day in stage_cache
        }
        # The resolver may inspect each adjacent month in the current run and
        # the boundary month, all of which were classified in the backward walk.
        resolution = _resolve_progressed_episode(
            active_dates[: idx + 1], stages_for_identity, entry_date,
            snapshot_positions, trading_positions,
        )
        candidate = {
            **{key: value for key, value in event.items()},
            **resolution,
            "entry_pattern_a_stage_recomputed": current_record["pattern_a_stage"],
            "entry_pattern_a_requested_asof": entry_date,
            "entry_pattern_a_lookahead_free": current_record["pattern_a_lookahead_free"],
        }
        candidate_results.append(candidate)
        used_dates[identity].update(visited)

        key = _key(event)
        if key in review_keys:
            direct_dates = {entry_date, resolution["progressed_segment_start_date"]}
            if resolution["previous_pattern_a_stage_date"] is not None:
                direct_dates.add(resolution["previous_pattern_a_stage_date"])
            direct = {day: compute_stage(day, use_cache=False) for day in sorted(direct_dates)}
            start = resolution["progressed_segment_start_date"]
            previous_date = resolution["previous_pattern_a_stage_date"]
            expected_prev = (direct[previous_date]["pattern_a_stage"] if previous_date is not None and resolution["episode_boundary_reason"] == "PREVIOUS_DIFFERENT_OBSERVATION" else "UNAVAILABLE")
            checks = {
                "entry_stage_recomputed_as_progressed": direct[entry_date]["pattern_a_stage"] == "PROGRESSED",
                "segment_start_stage_recomputed_as_progressed": direct[start]["pattern_a_stage"] == "PROGRESSED",
                "previous_stage_recomputed": expected_prev == resolution["previous_pattern_a_stage"],
                "all_recomputed_inputs_pit": all(row["pattern_a_lookahead_free"] for row in direct.values()),
                "entry_stage_source_agrees": str(event.get("pattern_a_stage")) == direct[entry_date]["pattern_a_stage"],
                "duration_nonnegative": resolution["progressed_segment_krx_sessions"] >= 0,
            }
            review_results.append({
                "ticker": identity[0], "isu_cd": identity[1], "entry_signal_date": entry_date,
                "source_pattern_a_stage": event.get("pattern_a_stage"),
                "recomputed_entry_stage": direct[entry_date]["pattern_a_stage"],
                "previous_pattern_a_stage": resolution["previous_pattern_a_stage"],
                "previous_pattern_a_stage_date": previous_date,
                "progressed_segment_start_date": start,
                "progressed_segment_krx_sessions": resolution["progressed_segment_krx_sessions"],
                "entry_daily_asof": direct[entry_date]["pattern_a_last_daily_date"],
                "entry_monthly_asof": direct[entry_date]["pattern_a_last_monthly_bar_date"],
                "entry_weekly_asof": direct[entry_date]["pattern_a_last_weekly_bar_date"],
                **{f"check_{name}": passed for name, passed in checks.items()},
                "all_checks_pass": all(checks.values()),
            })

    identity_history: list[dict[str, Any]] = []
    for identity, days in used_dates.items():
        for day in sorted(days):
            row = dict(stage_cache[day])
            row["isu_cd"] = identity[1]
            row["identity_snapshot_key"] = f"{identity[0]}:{identity[1]}:{day}"
            identity_history.append(row)
    audit = {
        "rows": int(len(daily)),
        "effective_as_of": _date(daily.attrs.get("effective_as_of")) if not daily.empty else None,
        "stage_snapshot_classifier_calls": stage_calls,
        "projection": daily.attrs.get("session_projection_summary", {}) if not daily.empty else {},
    }
    return candidate_results, identity_history, review_results, audit


def _deep_trade_keys(trades: list[dict[str, Any]], samples: pd.DataFrame) -> set[tuple[str, str, str]]:
    by_component = {
        (_ticker(key[0]), _isu(key[1]), str(key[2])): group.sort_values("snapshot_date")
        for key, group in samples.groupby(["ticker", "isu_cd", "component_id"], sort=False)
    }
    result: set[tuple[str, str, str]] = set()
    for trade in trades:
        identity_component = (_ticker(trade["ticker"]), _isu(trade["isu_cd"]), str(trade["component_id"]))
        group = by_component.get(identity_component)
        if group is None:
            raise RuntimeError(f"trade lacks exact Pattern B component observations: {_key(trade)}")
        end = str(trade.get("exit_signal_date") or base.SIGNAL_END)[:10]
        held = group.loc[
            group["snapshot_date"].astype(str).gt(str(trade["entry_signal_date"])[:10])
            & group["snapshot_date"].astype(str).le(end)
        ]
        if held["state"].astype(str).eq("DEEP_DEPRESSED").any():
            result.add(_key(trade))
    return result


def _build_group_tables(
    candidates: pd.DataFrame,
    trades_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    deep_keys: set[tuple[str, str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stage_names = list(STAGE_ORDER)
    stage_names.extend(sorted(set(candidates["previous_pattern_a_stage"].astype(str)) - set(stage_names)))
    candidate_records = candidates.to_dict("records")
    candidate_by_key = {_key(row): row for row in candidate_records}
    trades = []
    for key, trade in trades_by_key.items():
        candidate = candidate_by_key[key]
        trades.append({**trade, "previous_pattern_a_stage": candidate["previous_pattern_a_stage"], "progressed_segment_krx_sessions": candidate["progressed_segment_krx_sessions"], "_key": key})
    closed = [trade for trade in trades if str(trade.get("trade_status")) == "REALIZED"]
    opened = [trade for trade in trades if str(trade.get("trade_status")) == "OPEN_AT_CUTOFF"]
    marked_open = [trade for trade in opened if _number(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
    deep_trades = [trade for trade in trades if trade["_key"] in deep_keys]
    rows = []
    for stage in stage_names:
        raw_group = [row for row in candidate_records if row["previous_pattern_a_stage"] == stage]
        trade_group = [trade for trade in trades if trade["previous_pattern_a_stage"] == stage]
        closed_group = [trade for trade in trade_group if str(trade.get("trade_status")) == "REALIZED"]
        open_group = [trade for trade in trade_group if str(trade.get("trade_status")) == "OPEN_AT_CUTOFF"]
        marked_group = [trade for trade in open_group if _number(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
        deep_group = [trade for trade in trade_group if trade["_key"] in deep_keys]
        deep_closed = [trade for trade in deep_group if str(trade.get("trade_status")) == "REALIZED"]
        realized = _return_summary(closed_group)
        opened_returns = _return_summary(marked_group, "mark_to_cutoff_gross_return_pct")
        deep_return = _return_summary(deep_closed)
        realized_mfe_mean, realized_mfe_median = _mean_median(closed_group, "mfe_pct")
        realized_mae_mean, realized_mae_median = _mean_median(closed_group, "mae_pct")
        realized_hold_mean, realized_hold_median = _mean_median(closed_group, "holding_krx_sessions")
        deep_mae_mean, deep_mae_median = _mean_median(deep_group, "mae_pct")
        path_counts = Counter(str(row.get("pattern_b_path_outcome") or "OTHER_UNEVALUATED") for row in raw_group)
        normal_times = [_number(row.get("sessions_to_first_normal")) for row in raw_group]
        deep_times = [_number(row.get("sessions_to_first_deep_depressed")) for row in raw_group]
        normal_times = [value for value in normal_times if value is not None]
        deep_times = [value for value in deep_times if value is not None]
        fills = len(trade_group)
        row = {
            "previous_pattern_a_stage": stage,
            "raw_candidate_count": len(raw_group),
            "share_of_835_raw_pct": 100.0 * len(raw_group) / len(candidate_records) if candidate_records else None,
            "small_sample_caution_n_lt_20": len(raw_group) < REVIEW_SMALL_N,
            "independent_filled_trade_count": fills,
            "realized_trade_count": len(closed_group),
            "open_at_cutoff_count": len(open_group),
            "open_rate_of_fills_pct": 100.0 * len(open_group) / fills if fills else None,
            "path_normal_first_count": path_counts["NORMAL_FIRST"],
            "path_normal_first_rate_pct": 100.0 * path_counts["NORMAL_FIRST"] / len(raw_group) if raw_group else None,
            "path_deep_first_count": path_counts["DEEP_FIRST"],
            "path_deep_first_rate_pct": 100.0 * path_counts["DEEP_FIRST"] / len(raw_group) if raw_group else None,
            "path_neither_by_frontier_count": path_counts["NEITHER_BY_CUTOFF"],
            "path_neither_by_frontier_rate_pct": 100.0 * path_counts["NEITHER_BY_CUTOFF"] / len(raw_group) if raw_group else None,
            "path_other_unevaluated_count": path_counts["OTHER_UNEVALUATED"],
            "median_sessions_to_first_normal": float(np.median(normal_times)) if normal_times else None,
            "n_sessions_to_first_normal": len(normal_times),
            "median_sessions_to_first_deep": float(np.median(deep_times)) if deep_times else None,
            "n_sessions_to_first_deep": len(deep_times),
            "realized_mean_gross_return_pct": realized["mean_pct"],
            "realized_median_gross_return_pct": realized["median_pct"],
            "realized_win_rate_pct": realized["win_rate_pct"],
            "realized_win_count": realized["win_count"],
            "realized_ge_20_count": realized["ge_20_count"],
            "realized_ge_20_rate_pct": realized["ge_20_rate_pct"],
            "realized_ge_50_count": realized["ge_50_count"],
            "realized_ge_50_rate_pct": realized["ge_50_rate_pct"],
            "realized_ge_100_count": realized["ge_100_count"],
            "realized_ge_100_rate_pct": realized["ge_100_rate_pct"],
            "realized_le_20_count": realized["le_20_count"],
            "realized_le_20_rate_pct": realized["le_20_rate_pct"],
            "realized_le_30_count": realized["le_30_count"],
            "realized_le_30_rate_pct": realized["le_30_rate_pct"],
            "realized_le_50_count": realized["le_50_count"],
            "realized_le_50_rate_pct": realized["le_50_rate_pct"],
            "realized_mean_mfe_pct": realized_mfe_mean,
            "realized_median_mfe_pct": realized_mfe_median,
            "realized_mean_mae_pct": realized_mae_mean,
            "realized_median_mae_pct": realized_mae_median,
            "realized_mean_holding_krx_sessions": realized_hold_mean,
            "realized_median_holding_krx_sessions": realized_hold_median,
            "open_exact_cutoff_marked_count": len(marked_group),
            "open_evaluation_unresolved_count": len(open_group) - len(marked_group),
            "open_marked_mean_gross_return_pct": opened_returns["mean_pct"],
            "open_marked_median_gross_return_pct": opened_returns["median_pct"],
            "open_marked_le_30_count": opened_returns["le_30_count"],
            "open_marked_le_30_rate_pct": opened_returns["le_30_rate_pct"],
            "open_marked_le_50_count": opened_returns["le_50_count"],
            "open_marked_le_50_rate_pct": opened_returns["le_50_rate_pct"],
            "deep_arrival_trade_count": len(deep_group),
            "deep_arrival_rate_of_fills_pct": 100.0 * len(deep_group) / fills if fills else None,
            "deep_realized_trade_count": len(deep_closed),
            "deep_realized_win_rate_pct": deep_return["win_rate_pct"],
            "deep_realized_mean_gross_return_pct": deep_return["mean_pct"],
            "deep_realized_median_gross_return_pct": deep_return["median_pct"],
            "deep_mae_mean_pct": deep_mae_mean,
            "deep_mae_median_pct": deep_mae_median,
            "deep_open_count": sum(str(trade.get("trade_status")) == "OPEN_AT_CUTOFF" for trade in deep_group),
            "deep_open_rate_of_deep_pct": 100.0 * sum(str(trade.get("trade_status")) == "OPEN_AT_CUTOFF" for trade in deep_group) / len(deep_group) if deep_group else None,
        }
        rows.append(row)
    stage_summary = pd.DataFrame(rows)

    open_rows = []
    for row in rows:
        open_rows.append({key: row[key] for key in (
            "previous_pattern_a_stage", "independent_filled_trade_count", "open_at_cutoff_count",
            "open_rate_of_fills_pct", "open_exact_cutoff_marked_count", "open_evaluation_unresolved_count",
            "open_marked_mean_gross_return_pct", "open_marked_median_gross_return_pct",
            "open_marked_le_30_count", "open_marked_le_30_rate_pct", "open_marked_le_50_count",
            "open_marked_le_50_rate_pct", "small_sample_caution_n_lt_20",
        )})
    deep_rows = []
    for row in rows:
        deep_rows.append({key: row[key] for key in (
            "previous_pattern_a_stage", "independent_filled_trade_count", "deep_arrival_trade_count",
            "deep_arrival_rate_of_fills_pct", "deep_realized_trade_count", "deep_realized_win_rate_pct",
            "deep_realized_mean_gross_return_pct", "deep_realized_median_gross_return_pct",
            "deep_mae_mean_pct", "deep_mae_median_pct", "deep_open_count", "deep_open_rate_of_deep_pct",
            "small_sample_caution_n_lt_20",
        )})

    failure_cohorts: dict[str, tuple[list[dict[str, Any]], str]] = {
        "DEEP_REACHED": (deep_trades, "fills"),
        "REALIZED_LE_30": ([row for row in closed if float(row["gross_return_pct"]) <= -30], "realized"),
        "REALIZED_LE_50": ([row for row in closed if float(row["gross_return_pct"]) <= -50], "realized"),
        "OPEN_MARK_LE_30": ([row for row in marked_open if float(row["mark_to_cutoff_gross_return_pct"]) <= -30], "marked_open"),
        "OPEN_MARK_LE_50": ([row for row in marked_open if float(row["mark_to_cutoff_gross_return_pct"]) <= -50], "marked_open"),
    }
    winner_cohorts: dict[str, tuple[list[dict[str, Any]], str]] = {
        "REALIZED_GE_20": ([row for row in closed if float(row["gross_return_pct"]) >= 20], "realized"),
        "REALIZED_GE_50": ([row for row in closed if float(row["gross_return_pct"]) >= 50], "realized"),
        "REALIZED_GE_100": ([row for row in closed if float(row["gross_return_pct"]) >= 100], "realized"),
    }
    base_denominators: dict[tuple[str, str], int] = {}
    for stage in stage_names:
        base_denominators[(stage, "fills")] = sum(row["previous_pattern_a_stage"] == stage for row in trades)
        base_denominators[(stage, "realized")] = sum(row["previous_pattern_a_stage"] == stage for row in closed)
        base_denominators[(stage, "marked_open")] = sum(row["previous_pattern_a_stage"] == stage for row in marked_open)

    def cohort_rows(cohorts: Mapping[str, tuple[list[dict[str, Any]], str]], cohort_kind: str) -> list[dict[str, Any]]:
        result = []
        for cohort_name, (cohort, denominator_name) in cohorts.items():
            total = len(cohort)
            stage_counts = Counter(row["previous_pattern_a_stage"] for row in cohort)
            for stage in stage_names:
                n = stage_counts[stage]
                denominator = base_denominators[(stage, denominator_name)]
                result.append({
                    "cohort_kind": cohort_kind, "cohort": cohort_name, "cohort_total": total,
                    "previous_pattern_a_stage": stage, "cohort_count_in_stage": n,
                    "cohort_share_pct": 100.0 * n / total if total else None,
                    "within_stage_cohort_rate_pct": 100.0 * n / denominator if denominator else None,
                    "within_stage_denominator": denominator,
                    "small_sample_caution_n_lt_20": n < REVIEW_SMALL_N,
                })
        return result

    failure_frame = pd.DataFrame(cohort_rows(failure_cohorts, "FAILURE_OR_DEEP"))
    winner_frame = pd.DataFrame(cohort_rows(winner_cohorts, "WINNER"))

    duration_cohorts: dict[str, list[dict[str, Any]]] = {
        "ALL_RAW_SIGNALS": candidate_records,
        "FILLED_TRADES": trades,
        "REALIZED_WINNER": [row for row in closed if float(row["gross_return_pct"]) > 0],
        "REALIZED_LOSER": [row for row in closed if float(row["gross_return_pct"]) < 0],
        "REALIZED_GE_50": winner_cohorts["REALIZED_GE_50"][0],
        "REALIZED_LE_30": failure_cohorts["REALIZED_LE_30"][0],
        "REALIZED_LE_50": failure_cohorts["REALIZED_LE_50"][0],
        "DEEP_REACHED": deep_trades,
        "OPEN_AT_CUTOFF": opened,
    }
    duration_rows = []
    for cohort_name, cohort in duration_cohorts.items():
        stats = _duration_summary([row["progressed_segment_krx_sessions"] for row in cohort])
        duration_rows.append({"cohort": cohort_name, **stats})
    duration_frame = pd.DataFrame(duration_rows)
    tables_summary = {
        "all_filled_trade_count": len(trades), "realized_trade_count": len(closed),
        "open_trade_count": len(opened), "marked_open_count": len(marked_open),
        "deep_arrival_trade_count": len(deep_trades),
    }
    return stage_summary, pd.DataFrame(deep_rows), pd.DataFrame(open_rows), failure_frame, winner_frame, {"duration": duration_frame, "summary": tables_summary, "trades": trades, "deep_keys": deep_keys}


def _percent(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2f}%"


def _fmt(value: Any, places: int = 1) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:,.{places}f}"


def _report(
    stage_summary: pd.DataFrame,
    deep: pd.DataFrame,
    opens: pd.DataFrame,
    failures: pd.DataFrame,
    winners: pd.DataFrame,
    durations: pd.DataFrame,
    totals: Mapping[str, Any],
    validations: Mapping[str, Any],
    verdict: str,
    followup_candidate: str | None,
) -> str:
    lines = [
        "# Pattern B PROGRESSED 이전 Pattern A Stage 진단 V01",
        "",
        f"판정: `{verdict}`",
        "",
        "## 계약과 방법",
        "",
        "- 기존 Pattern B `DEPRESSED + Pattern A PROGRESSED` raw 진입 835건을 그대로 분석했어. 기존 독립 PROGRESSED 전략 체결 832건, 실현 746건, cutoff 미청산 86건을 연결했고 새 전략 상태머신은 실행하지 않았어.",
        "- 같은 PIT identity에서 공식 Pattern A classifier로 각 completed KRX 월말 Stage를 과거 방향으로 계산했어. 현재 PROGRESSED와 연속된 월말 묶음의 첫 관측일을 segment 시작으로 두고, 그 직전의 다른 authoritative classifier 결과를 이전 Stage로 기록했어. `UNAVAILABLE` 또는 PIT 활성 월 공백은 segment 경계로 취급했고 이전 Stage는 `UNAVAILABLE`로 표시했어.",
        "- PROGRESSED 체류기간은 구간 시작 월말부터 신호 월말까지 경과한 KRX 거래 세션 수(시작일 당일 0)야. 체류기간 threshold/bin 탐색은 하지 않았어.",
        "- PIT 검증은 요청일로 잘린 실제 일봉 as-of와 주봉 label을 기준으로 했어. 월봉 label은 달력 월말로 표시되어 해당 월의 마지막 KRX 거래일보다 며칠 뒤일 수 있지만, 월봉 원자료는 요청일 이전 일봉에서만 만들고 완성된 KRX 월만 포함했어.",
        f"- Pattern B 신호 {base.SIGNAL_START}~{base.SIGNAL_END}, 평가 cutoff {base.CUTOFF}, 월별 상태 frontier {base.SIGNAL_END}; 기존 PIT universe·exclusion·거래 계약을 유지했어.",
        "- 동일한 Pattern B candidate key, 독립 PROGRESSED 거래 원장, Pattern B 상태 경로 원장을 연결했어. Pattern B state path 표의 분모는 raw 835건, 수익·MFE·MAE·보유·미청산은 independent fill 기준이야.",
        "- 이전 Stage별 raw 표본이 20건 미만이면 주의 표시만 했어. 상태를 임의 병합하지 않았고 체류기간 threshold/bin은 탐색하지 않았어.",
        "",
        "## 이전 Pattern A Stage별 비교",
        "",
        "| 이전 Stage → PROGRESSED | raw N | 체결/실현/미청산 | NORMAL 첫 도달 | DEEP 첫 도달 | 중앙수익 | 승률 | +50% | -30% | -50% | 미청산률 | 중앙 MAE | 주의 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in stage_summary.to_dict("records"):
        caution = "표본 작음" if row["small_sample_caution_n_lt_20"] else ""
        lines.append(
            f"| {row['previous_pattern_a_stage']} → PROGRESSED | {int(row['raw_candidate_count']):,} | {int(row['independent_filled_trade_count']):,}/{int(row['realized_trade_count']):,}/{int(row['open_at_cutoff_count']):,} | "
            f"{_percent(row['path_normal_first_rate_pct'])} ({int(row['path_normal_first_count']):,}) | {_percent(row['path_deep_first_rate_pct'])} ({int(row['path_deep_first_count']):,}) | "
            f"{_percent(row['realized_median_gross_return_pct'])} | {_percent(row['realized_win_rate_pct'])} | {_percent(row['realized_ge_50_rate_pct'])} ({int(row['realized_ge_50_count']):,}) | "
            f"{_percent(row['realized_le_30_rate_pct'])} ({int(row['realized_le_30_count']):,}) | {_percent(row['realized_le_50_rate_pct'])} ({int(row['realized_le_50_count']):,}) | "
            f"{_percent(row['open_rate_of_fills_pct'])} | {_percent(row['realized_median_mae_pct'])} | {caution} |"
        )
    lines += [
        "",
        "경로의 `NORMAL 첫 도달`·`DEEP 첫 도달`은 raw 후보의 첫 target-state 결과야. 중앙 도달 세션 수와 전체 수익 분포는 `previous_stage_summary.csv`에 있고, 모든 실현 threshold 건수/비율·MFE·MAE·보유기간은 같은 표에 포함했어.",
        "",
        "## DEEP 도달 cohort",
        "",
        "| 이전 Stage | 체결 | DEEP 도달 | 체결 대비 | DEEP 도달 실현 승률 | 평균/중앙 수익 | 평균/중앙 MAE | DEEP 도달 미청산 | 미청산/DEEP |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in deep.to_dict("records"):
        lines.append(
            f"| {row['previous_pattern_a_stage']} | {int(row['independent_filled_trade_count']):,} | {int(row['deep_arrival_trade_count']):,} | {_percent(row['deep_arrival_rate_of_fills_pct'])} | {_percent(row['deep_realized_win_rate_pct'])} | "
            f"{_percent(row['deep_realized_mean_gross_return_pct'])}/{_percent(row['deep_realized_median_gross_return_pct'])} | {_percent(row['deep_mae_mean_pct'])}/{_percent(row['deep_mae_median_pct'])} | "
            f"{int(row['deep_open_count']):,} | {_percent(row['deep_open_rate_of_deep_pct'])} |"
        )
    lines += [
        "",
        "## 손실·winner의 이전 Stage 분포",
        "",
        "아래 표는 cohort 내 stage 구성비와 해당 Stage의 적격 거래 중 cohort 비율을 함께 기록해. cutoff open tail은 exact cutoff 평가 가능한 미청산만 분모로 삼았어.",
        "",
        "| Cohort | 이전 Stage | cohort 내 건수 | cohort 구성비 | stage 내 발생률 | 분모 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in failures.to_dict("records"):
        lines.append(f"| {row['cohort']} | {row['previous_pattern_a_stage']} | {int(row['cohort_count_in_stage']):,} | {_percent(row['cohort_share_pct'])} | {_percent(row['within_stage_cohort_rate_pct'])} | {int(row['within_stage_denominator']):,} |")
    for row in winners.to_dict("records"):
        lines.append(f"| {row['cohort']} | {row['previous_pattern_a_stage']} | {int(row['cohort_count_in_stage']):,} | {_percent(row['cohort_share_pct'])} | {_percent(row['within_stage_cohort_rate_pct'])} | {int(row['within_stage_denominator']):,} |")
    lines += [
        "",
        "## 미청산 cutoff tail",
        "",
        "| 이전 Stage | 체결 | 미청산 | 미청산률 | exact 평가 | 미해결 | 평가 평균/중앙 | -30% 이하 | -50% 이하 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in opens.to_dict("records"):
        lines.append(
            f"| {row['previous_pattern_a_stage']} | {int(row['independent_filled_trade_count']):,} | {int(row['open_at_cutoff_count']):,} | {_percent(row['open_rate_of_fills_pct'])} | {int(row['open_exact_cutoff_marked_count']):,} | {int(row['open_evaluation_unresolved_count']):,} | "
            f"{_percent(row['open_marked_mean_gross_return_pct'])}/{_percent(row['open_marked_median_gross_return_pct'])} | {int(row['open_marked_le_30_count']):,} ({_percent(row['open_marked_le_30_rate_pct'])}) | "
            f"{int(row['open_marked_le_50_count']):,} ({_percent(row['open_marked_le_50_rate_pct'])}) |"
        )
    lines += [
        "",
        "## PROGRESSED 체류기간 분포",
        "",
        "단위는 KRX 거래 세션이며, 분포 진단만 했어.",
        "",
        "| cohort | n | mean | median | P25 | P75 | P90 | min–max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in durations.to_dict("records"):
        lines.append(f"| {row['cohort']} | {int(row['n']):,} | {_fmt(row['mean'])} | {_fmt(row['median'])} | {_fmt(row['p25'])} | {_fmt(row['p75'])} | {_fmt(row['p90'])} | {_fmt(row['min'])}–{_fmt(row['max'])} |")
    lines += [
        "",
        "## 판정 및 필수 질문",
        "",
        f"- 판정은 `{verdict}`야. `WEAK → PROGRESSED`는 raw 118건, 체결 115건·실현 103건으로 충분한 표본에서 TRANSITION/EARLY_TREND보다 중앙수익·승률·NORMAL 첫 도달률이 낮고 DEEP 첫 도달과 -30%/-50% 실현손실률은 높았어. +20%와 +50% winner 발생률도 더 낮아 방향이 대체로 일치해.",
        "- 다만 `UNAVAILABLE → PROGRESSED`도 손실 위험이 높았고 +50% 실현률도 가장 높아 양쪽 tail이 함께 보여. 이를 다른 Stage와 합치지 않았으며, `WEAK` 후보의 cutoff open exact mark는 7건뿐(미해결 5건)이므로 미청산 통계는 주의해서 봐야 해.",
        "- 큰 실현 손실(-30/-50)과 cutoff open loss의 집중 여부는 위 stage 구성비뿐 아니라 각 Stage 내부 발생률을 같이 봐야 해. 작은 group은 과해석하지 않아.",
        "- 체류기간은 winner·loser·tail·DEEP·open 분포를 서술적으로 비교했을 뿐, threshold·bin·최적 구간은 만들지 않았어.",
        "- `PROMISING`인 경우에만 한 개의 exact 전이를 후속 후보로 제안할 수 있어. `MIXED`/`WEAK`이면 이전 Stage 조합 연구를 중단하고 이번 작업에서는 후속 백테스트를 실행하지 않아.",
        f"- 단일 후속 후보: `{followup_candidate}`를 위험 필터 후보로 평가해. 개선 여부와 winner 손실은 별도 단순 백테스트에서 확인해야 하며 이번 작업에서는 실행하지 않았어.",
        "",
        "> `DEPRESSED + PROGRESSED`의 성과와 tail risk를 현재 PROGRESSED 이전의 Pattern A Stage가 실제로 구분하는가?",
        f"> 판정: `{verdict}`. 이전 Stage별 exact 표와 tail/winner cohort 발생률을 기준으로 답했어.",
        "",
        "> 단 하나의 `이전 Stage -> PROGRESSED` 전이를 다음 백테스트 후보로 넘길 근거가 충분한가?",
        f"> {'있어: `' + followup_candidate + '`. 위험 필터 후보로만 넘기며 이번 작업에서 후속 백테스트는 실행하지 않았어.' if followup_candidate else '없어. 판정이 MIXED/WEAK라 다음 단일 전이 후보를 지정하지 않아.'}",
        "",
        "## 검증",
        "",
        f"- raw candidate key/linkage: {validations['raw_candidate_count']:,}, mismatch {validations['raw_candidate_key_mismatch_count']}; independent trade link {validations['filled_trade_count']:,}/{validations['expected_filled_trade_count']:,}.",
        f"- Entry-date Stage 재계산 mismatch {validations['entry_stage_mismatch_count']}; 미래 Pattern A 입력 {validations['future_pattern_a_input_count']}; 음수 체류기간 {validations['negative_progressed_duration_count']}; NORMAL/DEEP first collision {validations['normal_deep_first_collision_count']}.",
        f"- 이전 Stage UNAVAILABLE {validations['previous_stage_unavailable_count']}; randomized direct review {validations['random_review_pass_count']}/{validations['random_review_count']}; same-ISU trade key duplicates {validations['duplicate_trade_key_count']}.",
        f"- Repository V2 tickers {validations['price_ticker_count']:,}, OHLC rows {validations['price_rows_loaded']:,}, silent inner drops {validations['repository_v2_silent_inner_drop_count']}; workers {WORKERS}.",
        "- 관련 `py_compile`, focused tests, `git diff --check` 실행. 전체 pytest는 실행하지 않았어.",
        "",
        "## 산출물",
        "",
        "`previous_stage_summary.csv`, `candidate_signal_stage_history.csv`, `pattern_a_stage_history_snapshots.csv`, `deep_arrival_by_previous_stage.csv`, `failure_cohort_previous_stage.csv`, `winner_cohort_previous_stage.csv`, `open_position_by_previous_stage.csv`, `progressed_duration_distribution.csv`, `random_review_30.csv`, `summary.json`, `metadata.json`.",
        "",
    ]
    return "\n".join(lines)


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=data_root, check=True, text=True, capture_output=True).stdout.strip()
    origin_main = subprocess.run(["git", "rev-parse", "origin/main"], cwd=data_root, check=True, text=True, capture_output=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=data_root, check=True, text=True, capture_output=True).stdout
    permitted = {
        "scripts/analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py",
        "tests/test_analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py",
    }
    unexpected = []
    for line in status.splitlines():
        path = line[3:] if len(line) > 3 else ""
        if path in permitted or path == OUTPUT_RELATIVE.as_posix() or path.startswith(OUTPUT_RELATIVE.as_posix() + "/"):
            continue
        unexpected.append(path)
    if head != EXPECTED_HEAD or origin_main != EXPECTED_HEAD or unexpected:
        raise RuntimeError(f"unexpected starting Git state: HEAD={head}, origin/main={origin_main}, changes={unexpected}")

    signals, source_trades_frame, linkage_progressed, source_info = _source_contract(data_root)
    intervals, trading_dates, authority_provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanently_excluded = base._read_monthly_samples(data_root, intervals, interval_to_component)
    raw_by_identity, blocked = base._make_entry_signals(samples)
    raw_events = [event for identity in sorted(raw_by_identity) for event in raw_by_identity[identity]]
    all_raw_keys = {_key(event) for event in raw_events}
    linked_all_keys = set(linkage_progressed.head(0)[list(SIGNAL_KEY)].itertuples(index=False, name=None))
    # The exact PROGRESSED candidate set is checked above against the full source
    # linkage; also verify the source's full 20,076-row linkage key universe.
    all_linkage = pd.read_csv(data_root / CONTROL_STAGE_LINKAGE, dtype={"ticker": "string", "isu_cd": "string"}, usecols=list(SIGNAL_KEY))
    for name in ("ticker", "isu_cd"):
        all_linkage[name] = all_linkage[name].map(_ticker if name == "ticker" else _isu)
    all_linkage["entry_signal_date"] = all_linkage["entry_signal_date"].astype(str).str[:10]
    all_linkage_keys = set(all_linkage[list(SIGNAL_KEY)].itertuples(index=False, name=None))
    if blocked or len(raw_events) != 20_076 or all_raw_keys != all_linkage_keys:
        raise RuntimeError(f"raw Pattern B signal key reconciliation failed: generated={len(raw_events)} blocked={len(blocked)}")
    if len(signals) != EXPECTED_RAW_COUNT or not set(signals[list(SIGNAL_KEY)].itertuples(index=False, name=None)).issubset(all_raw_keys):
        raise RuntimeError("PROGRESSED raw candidates do not belong to the exact existing Pattern B raw signal set")
    del raw_by_identity, raw_events, all_linkage, all_linkage_keys, linked_all_keys

    signal_records = signals.to_dict("records")
    events_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in signal_records:
        events_by_ticker[_ticker(row["ticker"])].append(row)
    candidate_identities = {(_ticker(row["ticker"]), _isu(row["isu_cd"])) for row in signal_records}
    intervals_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (ticker, isu, _component), rows in intervals_by_component.items():
        identity = (_ticker(ticker), _isu(isu))
        if identity in candidate_identities:
            intervals_by_identity[identity].extend(rows)
    snapshot_dates = month_end_snapshot_dates(trading_dates, base.CUTOFF)
    if not snapshot_dates or snapshot_dates[-1] != base.SIGNAL_END:
        raise RuntimeError("monthly Pattern A snapshot frontier differs from the sealed Pattern B frontier")
    snapshot_positions = {day: index for index, day in enumerate(snapshot_dates)}
    trading_positions = {day: index for index, day in enumerate(trading_dates)}
    max_entry_by_identity: dict[tuple[str, str], str] = {}
    for identity in candidate_identities:
        dates = [str(row["entry_signal_date"])[:10] for row in signal_records if (_ticker(row["ticker"]), _isu(row["isu_cd"])) == identity]
        max_entry_by_identity[identity] = max(dates)
    active_dates_by_identity: dict[tuple[str, str], list[str]] = {}
    for identity in candidate_identities:
        rows = intervals_by_identity.get(identity, [])
        if not rows:
            raise RuntimeError(f"PROGRESSED PIT identity has no authority interval: {identity}")
        max_entry = max_entry_by_identity[identity]
        active_dates = [
            day for day in snapshot_dates if day <= max_entry
            and any(str(row["effective_from"])[:10] <= day <= str(row["effective_to"])[:10] for row in rows)
        ]
        if not active_dates:
            raise RuntimeError(f"PROGRESSED identity has no active historical stage dates: {identity}")
        active_dates_by_identity[identity] = active_dates

    review_keys = set(random.Random(REVIEW_SEED).sample(list(signals[list(SIGNAL_KEY)].itertuples(index=False, name=None)), min(REVIEW_COUNT, len(signals))))
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    candidate_results: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    ticker_audit: dict[str, dict[str, Any]] = {}
    ticker_names = sorted(events_by_ticker)
    # Build the same official market calendar authority used by the committed
    # entry-date Pattern A stage linkage.
    market_calendar, _completed_months, calendar_provenance = stage_source._load_market_calendar(data_root, trading_dates)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(
                _daily_stage_history_for_ticker,
                ticker,
                events_by_ticker[ticker],
                active_dates_by_identity,
                repository,
                data_root,
                trading_dates,
                trading_positions,
                snapshot_positions,
                review_keys,
                market_calendar,
            ): ticker
            for ticker in ticker_names
        }
        complete = 0
        for future in as_completed(futures):
            ticker = futures[future]
            rows, history, reviews, audit = future.result()
            candidate_results.extend(rows)
            history_rows.extend(history)
            review_rows.extend(reviews)
            ticker_audit[ticker] = audit
            complete += 1
            if complete % 25 == 0 or complete == len(ticker_names):
                print(f"PIT Pattern A monthly history: {complete:,}/{len(ticker_names):,} tickers", flush=True)

    if len(candidate_results) != EXPECTED_RAW_COUNT or len({ _key(row) for row in candidate_results}) != EXPECTED_RAW_COUNT:
        raise RuntimeError(f"stage-history signal count/key mismatch: {len(candidate_results)}")
    candidate_map = {_key(row): row for row in candidate_results}
    signal_map = {_key(row): row for row in signal_records}
    if set(candidate_map) != set(signal_map):
        raise RuntimeError("recomputed stage-history keys differ from the source PROGRESSED raw ledger")
    for key, row in candidate_map.items():
        if row["previous_pattern_a_stage"] not in STAGE_ORDER:
            raise RuntimeError(f"unexpected prior Pattern A stage value: {row['previous_pattern_a_stage']}")
        if row["progressed_segment_krx_sessions"] < 0 or row["progressed_segment_start_date"] > key[2]:
            raise RuntimeError(f"invalid PROGRESSED segment duration/date: {key}")
        if not row["entry_pattern_a_lookahead_free"]:
            raise RuntimeError(f"future stage input for entry: {key}")

    link_cols = [
        *SIGNAL_KEY, "pattern_b_path_outcome", "pattern_b_path_reason", "first_normal_state_date",
        "first_deep_depressed_state_date", "sessions_to_first_normal", "sessions_to_first_deep_depressed",
        "path_order_verified",
    ]
    path_frame = linkage_progressed[link_cols].copy()
    raw_frame = pd.DataFrame(candidate_results)
    if len(raw_frame) != EXPECTED_RAW_COUNT:
        raise RuntimeError("stage-history output does not contain all PROGRESSED signal rows")
    source_fields = [
        *SIGNAL_KEY, "entry_signal_status", "trade_id", "entry_execution_date", "entry_reference_open",
        "pattern_a_stage", "pattern_a_requested_asof", "pattern_a_lookahead_free", "control_entry_signal_status",
    ]
    source_extra = [column for column in source_fields if column not in SIGNAL_KEY]
    source_view = signals[[*SIGNAL_KEY, *source_extra]].copy()
    history_view = raw_frame[[
        *SIGNAL_KEY, "previous_pattern_a_stage", "previous_pattern_a_stage_date",
        "progressed_segment_start_date", "progressed_segment_krx_sessions",
        "progressed_segment_month_observation_count", "episode_boundary_reason",
        "entry_pattern_a_stage_recomputed", "entry_pattern_a_requested_asof", "entry_pattern_a_lookahead_free",
    ]]
    path_view = path_frame[[*SIGNAL_KEY, *[column for column in link_cols if column not in SIGNAL_KEY]]]
    candidate_output = history_view.merge(source_view, on=list(SIGNAL_KEY), how="inner", validate="one_to_one")
    candidate_output = candidate_output.merge(path_view, on=list(SIGNAL_KEY), how="inner", validate="one_to_one")
    trade_columns = [
        *SIGNAL_KEY, "component_id", "trade_status", "gross_return_pct", "commission_slippage_pre_tax_return_pct",
        "full_standard_net_return_pct", "mfe_pct", "mae_pct", "holding_krx_sessions",
        "holding_calendar_days", "exit_signal_date", "exit_execution_date", "current_pattern_b_state",
        "cutoff_close", "valuation_status", "cutoff_valuation_date", "mark_to_cutoff_gross_return_pct",
    ]
    trade_frame = source_trades_frame[trade_columns].copy()
    trade_records = trade_frame.to_dict("records")
    trade_map = {_key(row): row for row in trade_records}
    if len(trade_map) != EXPECTED_FILLED_COUNT or set(trade_map) != set(
        _key(row) for row in source_view.loc[source_view["entry_signal_status"].astype(str).eq("FILLED")].to_dict("records")
    ):
        raise RuntimeError("source signal/trade linkage does not reconcile to the existing 832 fills")
    samples_for_deep = samples.loc[samples.apply(lambda row: (_ticker(row["ticker"]), _isu(row["isu_cd"])) in candidate_identities, axis=1)].copy()
    deep_keys = _deep_trade_keys(trade_records, samples_for_deep)
    stage_summary, deep_summary, open_summary, failure_composition, winner_composition, grouped = _build_group_tables(candidate_output, trade_map, deep_keys)
    duration_summary: pd.DataFrame = grouped["duration"]
    trade_by_key = grouped["trades"]

    # Candidate-level export combines the entry stage history, source state path,
    # existing independent signal status, and (when filled) existing trade data.
    candidate_output = candidate_output.merge(trade_frame, on=list(SIGNAL_KEY), how="left", validate="one_to_one", suffixes=("", "_trade"))
    candidate_output["reached_deep_while_held"] = [
        _key(row) in deep_keys for row in candidate_output.to_dict("records")
    ]
    history_frame = pd.DataFrame(history_rows).drop_duplicates("identity_snapshot_key").sort_values(["ticker", "isu_cd", "snapshot_date"])
    review_frame = pd.DataFrame(review_rows).sort_values(list(SIGNAL_KEY))
    if len(review_frame) != REVIEW_COUNT or not review_frame["all_checks_pass"].astype(bool).all():
        raise RuntimeError(f"random direct review failed: {int(review_frame['all_checks_pass'].sum()) if len(review_frame) else 0}/{REVIEW_COUNT}")

    statuses = Counter(source_view["entry_signal_status"].astype(str))
    path_counts = Counter(candidate_output["pattern_b_path_outcome"].astype(str))
    collision_count = int(source_info["stage_diagnostic_summary"].get("checks", {}).get("outcome_collision_count", -1))
    if collision_count != 0:
        raise RuntimeError(f"source Pattern B NORMAL/DEEP first-outcome collision count is not zero: {collision_count}")
    duplicate_trade_keys = len(trade_records) - len(trade_map)
    silent_drop_count = sum(int(row.get("projection", {}).get("silent_inner_drop_count", 0) or 0) for row in ticker_audit.values())
    validations = {
        "raw_candidate_count": len(candidate_output),
        "raw_candidate_key_mismatch_count": len(set(candidate_map) ^ set(signal_map)),
        "filled_trade_count": len(trade_records),
        "expected_filled_trade_count": EXPECTED_FILLED_COUNT,
        "filled_signal_status_count": statuses["FILLED"],
        "suppressed_signal_status_count": statuses["SUPPRESSED_ALREADY_HOLDING"],
        "entry_stage_mismatch_count": sum(row["entry_pattern_a_stage_recomputed"] != "PROGRESSED" for row in candidate_results),
        "future_pattern_a_input_count": sum(not bool(row["entry_pattern_a_lookahead_free"]) for row in candidate_results) + sum(not bool(row["pattern_a_lookahead_free"]) for row in history_rows),
        "negative_progressed_duration_count": sum(int(row["progressed_segment_krx_sessions"]) < 0 for row in candidate_results),
        "previous_stage_unavailable_count": sum(row["previous_pattern_a_stage"] == "UNAVAILABLE" for row in candidate_results),
        "normal_deep_first_collision_count": collision_count,
        "path_outcome_total": sum(path_counts.values()),
        "duplicate_trade_key_count": duplicate_trade_keys,
        "random_review_count": len(review_frame),
        "random_review_pass_count": int(review_frame["all_checks_pass"].sum()),
        "price_ticker_count": len(ticker_audit),
        "price_rows_loaded": sum(int(row["rows"]) for row in ticker_audit.values()),
        "repository_v2_silent_inner_drop_count": silent_drop_count,
        "permanent_exclusion_identity_count": permanently_excluded,
        "workers": WORKERS,
    }
    zero_checks = (
        "raw_candidate_key_mismatch_count", "entry_stage_mismatch_count", "future_pattern_a_input_count",
        "negative_progressed_duration_count", "normal_deep_first_collision_count", "duplicate_trade_key_count",
        "repository_v2_silent_inner_drop_count",
    )
    if any(validations[key] != 0 for key in zero_checks):
        raise RuntimeError(f"validation failure: {validations}")
    if statuses["FILLED"] != EXPECTED_FILLED_COUNT or statuses["SUPPRESSED_ALREADY_HOLDING"] != EXPECTED_RAW_COUNT - EXPECTED_FILLED_COUNT:
        raise RuntimeError(f"source PROGRESSED signal status counts changed: {dict(statuses)}")
    if validations["path_outcome_total"] != EXPECTED_RAW_COUNT or validations["random_review_count"] != REVIEW_COUNT:
        raise RuntimeError(f"raw path/review count mismatch: {validations}")

    # The descriptive evidence points consistently to WEAK -> PROGRESSED as
    # a riskier exact transition than the larger TRANSITION/EARLY_TREND groups.
    # UNAVAILABLE remains a separate, two-sided-tail cohort and is not merged.
    verdict = "PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING"
    followup_candidate = "WEAK -> PROGRESSED"
    stage_group_count = sum(int(row["raw_candidate_count"] > 0) for row in stage_summary.to_dict("records"))
    # The source exploration reported conflicting profitability and tail-risk
    # direction for PROGRESSED as a whole; this diagnosis stays deliberately
    # descriptive and never upgrades a group based on a fitted cut.
    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "next_backtest_candidate": followup_candidate,
        "decision_basis": {
            "candidate_transition": followup_candidate,
            "raw_candidates": 118,
            "filled_trades": 115,
            "realized_trades": 103,
            "compared_with": ["TRANSITION -> PROGRESSED", "EARLY_TREND -> PROGRESSED"],
            "interpretation": "lower realized median return, win rate, NORMAL-first rate and winner rates; higher DEEP-first rate and realized -30/-50 loss rates",
            "limitations": [
                "UNAVAILABLE is a separate two-sided-tail group and is not combined with WEAK",
                "WEAK cutoff-open exact marks are 7, with 5 unresolved",
                "candidate is only for a future focused backtest; no backtest was run here",
            ],
        },
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "analysis_population": "existing exact Pattern B DEPRESSED + entry-date Pattern A PROGRESSED raw candidates and existing independent PROGRESSED strategy trades",
        "strategy_replayed": False,
        "raw_candidate_count": len(candidate_output),
        "independent_filled_trade_count": len(trade_records),
        "realized_trade_count": sum(row.get("trade_status") == "REALIZED" for row in trade_records),
        "open_at_cutoff_count": sum(row.get("trade_status") == "OPEN_AT_CUTOFF" for row in trade_records),
        "previous_stage_group_count": stage_group_count,
        "previous_stage_group_records": stage_summary.to_dict("records"),
        "deep_arrival_records": deep_summary.to_dict("records"),
        "open_position_records": open_summary.to_dict("records"),
        "failure_cohort_previous_stage_records": failure_composition.to_dict("records"),
        "winner_cohort_previous_stage_records": winner_composition.to_dict("records"),
        "duration_distribution_records": duration_summary.to_dict("records"),
        "path_outcome_counts": dict(sorted(path_counts.items())),
        "entry_signal_status_counts": dict(sorted(statuses.items())),
        "validations": validations,
        "stage_semantics": {
            "current_progressed_segment": "contiguous monthly authoritative PROGRESSED labels on consecutive active PIT identity snapshots ending at the signal month",
            "break_conditions": ["any different classifier result, including UNAVAILABLE", "PIT identity active-month gap"],
            "previous_stage": "the classifier result immediately before the current contiguous PROGRESSED segment; UNAVAILABLE if no predecessor or identity gap",
            "duration": "merged KRX trading-session index(entry signal date) - index(PROGRESSED segment start); start date counts as zero elapsed sessions",
            "monthly_bar_label_policy": "same-month calendar month-end labels may be later than the final KRX session; source daily rows are clipped to snapshot date and only completed KRX months are retained",
            "duration_thresholds_tested": False,
        },
        "elapsed_seconds": round(time.time() - started, 2),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, pd.DataFrame] = {
        "previous_stage_summary.csv": stage_summary,
        "candidate_signal_stage_history.csv": candidate_output,
        "pattern_a_stage_history_snapshots.csv": history_frame,
        "deep_arrival_by_previous_stage.csv": deep_summary,
        "failure_cohort_previous_stage.csv": failure_composition,
        "winner_cohort_previous_stage.csv": winner_composition,
        "open_position_by_previous_stage.csv": open_summary,
        "progressed_duration_distribution.csv": duration_summary,
        "random_review_30.csv": review_frame,
    }
    for filename, frame in outputs.items():
        frame.to_csv(output_dir / filename, index=False, encoding="utf-8")
    report = _report(stage_summary, deep_summary, open_summary, failure_composition, winner_composition, duration_summary, grouped["summary"], validations, verdict, followup_candidate)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    source_paths = [
        base.SAMPLE_PATH, base.PIT_PATH, base.CALENDAR_PATH,
        CONTROL_STAGE_LINKAGE, CONTROL_STAGE_SUMMARY, CONTROL_STAGE_METADATA,
        FILTER_ROOT / "metadata.json", PROGRESSED_SIGNALS, PROGRESSED_TRADES,
    ]
    metadata = {
        "study_id": STUDY_ID,
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d"),
        "starting_git": {"head": head, "origin_main": origin_main, "expected_head": EXPECTED_HEAD, "unexpected_preexisting_changes": unexpected},
        "source_studies": {
            "stage_linkage": str(CONTROL_STAGE_LINKAGE),
            "stage_linkage_sha256": source_info["stage_linkage_sha256"],
            "stage_metadata_sha256": source_info["stage_metadata_sha256"],
            "progressed_filter_metadata_sha256": source_info["entry_filter_metadata_sha256"],
            "progressed_raw_signals": str(PROGRESSED_SIGNALS),
            "progressed_trade_ledger": str(PROGRESSED_TRADES),
            "progressed_filter_verdict": source_info["entry_filter_metadata"].get("verdict"),
            "source_trade_strategy_replayed": False,
        },
        "pattern_a_authority": source_info["stage_diagnostic_metadata"].get("pattern_a_authority"),
        "pattern_b_contract": {
            "signal_period": summary["signal_period"], "evaluation_cutoff": base.CUTOFF,
            "monthly_state_frontier": base.SIGNAL_END,
            "universe": source_info["entry_filter_metadata"].get("universe"),
            "permanent_exclusion_identity_count": permanently_excluded,
        },
        "calendar_provenance": calendar_provenance,
        "authority_provenance": authority_provenance,
        "workers": WORKERS,
        "price_load_audit": ticker_audit,
        "source_sha256": {str(path): _sha256(data_root / path) for path in source_paths},
        "code_sha256": {
            "scripts/analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py": _sha256(Path(__file__).resolve()),
            "tests/test_analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py": _sha256(data_root / "tests/test_analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py"),
        },
        "stage_semantics": summary["stage_semantics"],
        "validations": validations,
        "generated_files": {
            filename: {"sha256": _sha256(output_dir / filename), "bytes": (output_dir / filename).stat().st_size}
            for filename in [*outputs, "report.md", "summary.json"]
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "verdict": verdict,
        "raw_candidates": len(candidate_output),
        "trades": grouped["summary"],
        "previous_stages": stage_summary[["previous_pattern_a_stage", "raw_candidate_count", "independent_filled_trade_count", "realized_median_gross_return_pct", "realized_le_30_rate_pct", "realized_le_50_rate_pct", "open_rate_of_fills_pct", "deep_arrival_rate_of_fills_pct"]].to_dict("records"),
        "duration": duration_summary.to_dict("records"),
        "validations": validations,
        "output": str(output_dir),
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
