#!/usr/bin/env python3
"""Independently replay the standard P1 Pattern B PROGRESSED weak-origin filter."""

from __future__ import annotations

import argparse
import copy
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
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pattern_a_entry_filter_simple_v01 as entry_filter  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import analyze_pattern_b_progressed_previous_pattern_a_stage_v01 as prior_stage  # noqa: E402
from trend_scanner.backtest.standard_windows import resolve_standard_backtest_window  # noqa: E402
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar  # noqa: E402
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2  # noqa: E402

STUDY_ID = "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_SIMPLE_V01"
EXPECTED_HEAD = "7b0b5821986b75e3c204874350bdbfd53b8ac882"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/progressed_weak_exclusion_p1_simple_v01")
PREVIOUS_STAGE_ROOT = Path("artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01")
PREVIOUS_STAGE_HISTORY = PREVIOUS_STAGE_ROOT / "candidate_signal_stage_history.csv"
PREVIOUS_STAGE_METADATA = PREVIOUS_STAGE_ROOT / "metadata.json"
PREVIOUS_STAGE_SUMMARY = PREVIOUS_STAGE_ROOT / "summary.json"
WORKERS = 10
SEED = 20260927
REVIEW_COUNT = 30
PERCENTAGE_POINT_TOLERANCE = 0.1
FLOAT_COMPARISON_EPSILON = 1e-9
STAGES = {"WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "UNAVAILABLE"}
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")
TRADE_METRICS = (
    "mean_pct", "median_pct", "win_rate_pct", "profit_factor", "expectancy_pct",
    "ge_20_count", "ge_20_rate_pct", "ge_50_count", "ge_50_rate_pct",
    "ge_100_count", "ge_100_rate_pct", "le_20_count", "le_20_rate_pct",
    "le_30_count", "le_30_rate_pct", "le_50_count", "le_50_rate_pct",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_text(data_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=data_root, check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


def _git_blob_sha(data_root: Path, revision: str, relative_path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative_path.as_posix()}"],
        cwd=data_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _safe_num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _filter_decisions(pattern_a_stage: str, previous_pattern_a_stage: str | None) -> tuple[str, str]:
    control = "PASS_PATTERN_A_PROGRESSED" if pattern_a_stage == "PROGRESSED" else "REJECTED_PATTERN_A_NOT_PROGRESSED"
    if pattern_a_stage != "PROGRESSED":
        test = "REJECTED_PATTERN_A_NOT_PROGRESSED"
    elif previous_pattern_a_stage == "WEAK":
        test = "REJECTED_PREVIOUS_STAGE_WEAK"
    else:
        test = "PASS_PATTERN_A_PROGRESSED"
    return control, test


def _json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_clean(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _assert_git_start(data_root: Path) -> dict[str, Any]:
    head = _git_text(data_root, "rev-parse", "HEAD")
    origin_main = _git_text(data_root, "rev-parse", "origin/main")
    branch = _git_text(data_root, "branch", "--show-current")
    if head != EXPECTED_HEAD or origin_main != EXPECTED_HEAD or branch != "main":
        raise RuntimeError(
            f"unexpected P1 base: branch={branch}, HEAD={head}, origin/main={origin_main}"
        )
    status = _git_text(data_root, "status", "--porcelain")
    allowed = {
        Path(__file__).resolve().relative_to(data_root.resolve()).as_posix(),
        "tests/test_run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py",
    }
    unexpected = []
    for line in status.splitlines():
        path = line[3:].strip()
        if path in allowed or path == OUTPUT_RELATIVE.as_posix() or path.startswith(OUTPUT_RELATIVE.as_posix() + "/"):
            continue
        unexpected.append(line)
    if unexpected:
        raise RuntimeError(f"unrelated worktree changes present before P1: {unexpected}")
    output_dir = data_root / OUTPUT_RELATIVE
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"refusing to rerun an existing P1 output: {output_dir}")
    return {"head": head, "origin_main": origin_main, "branch": branch, "unexpected_changes": unexpected}


def _resolve_p1(data_root: Path) -> tuple[Any, dict[str, Any]]:
    calendar = load_rolling_production_market_calendar(data_root)
    resolved = resolve_standard_backtest_window("P1", calendar)
    actual = tuple(
        date.strftime("%Y-%m-%d")
        for date in (resolved.effective_start, resolved.effective_end, resolved.execution_support)
    )
    expected = ("2014-01-02", "2026-08-31", "2026-09-01")
    if actual != expected:
        raise RuntimeError(f"P1 resolution differs from the instruction: actual={actual}, expected={expected}")
    if calendar is None or not calendar.is_trading_day(actual[1]) or not calendar.is_trading_day(actual[2]):
        raise RuntimeError("P1 end or execution-support date is not an exact certified KRX session")
    return resolved, {
        "window_id": "P1",
        "calendar_range": [resolved.window.calendar_start.strftime("%Y-%m-%d"), resolved.window.calendar_end.strftime("%Y-%m-%d")],
        "effective_start": actual[0],
        "effective_end": actual[1],
        "execution_support": actual[2],
        "authority_source": calendar.source_name,
        "authority_metadata": calendar.metadata,
        "support_policy": "only an exit signal dated on or before effective_end may fill on execution_support; entries after effective_end are not filled",
    }


def _read_previous_stage_history(data_root: Path) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    metadata = json.loads((data_root / PREVIOUS_STAGE_METADATA).read_text(encoding="utf-8"))
    prior_summary = json.loads((data_root / PREVIOUS_STAGE_SUMMARY).read_text(encoding="utf-8"))
    if metadata.get("study_id") != "PATTERN_B_PROGRESSED_PREVIOUS_PATTERN_A_STAGE_V01":
        raise RuntimeError("prior-stage input is not the expected authoritative study")
    if prior_summary.get("verdict") != "PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING":
        raise RuntimeError("prior-stage diagnostic verdict differs from the P1 instruction")
    for relative in (PREVIOUS_STAGE_METADATA, PREVIOUS_STAGE_SUMMARY, PREVIOUS_STAGE_HISTORY):
        if _git_blob_sha(data_root, EXPECTED_HEAD, relative) != _sha256(data_root / relative):
            raise RuntimeError(f"prior-stage input is not byte-identical to required starting commit: {relative}")
    for relative, expected in metadata.get("source_sha256", {}).items():
        if _sha256(data_root / relative) != expected:
            raise RuntimeError(f"prior-stage source changed: {relative}")
    for relative, expected in metadata.get("code_sha256", {}).items():
        if _sha256(data_root / relative) != expected:
            raise RuntimeError(f"prior-stage definition code changed: {relative}")
    expected_history_hash = metadata.get("generated_files", {}).get("candidate_signal_stage_history.csv", {}).get("sha256")
    if not expected_history_hash or _sha256(data_root / PREVIOUS_STAGE_HISTORY) != expected_history_hash:
        raise RuntimeError("prior-stage candidate history does not match its committed metadata")
    expected_summary_hash = metadata.get("generated_files", {}).get("summary.json", {}).get("sha256")
    if not expected_summary_hash or _sha256(data_root / PREVIOUS_STAGE_SUMMARY) != expected_summary_hash:
        raise RuntimeError("prior-stage summary does not match its committed metadata")
    history = pd.read_csv(
        data_root / PREVIOUS_STAGE_HISTORY,
        dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"},
    )
    history["ticker"] = history["ticker"].map(base.norm_ticker)
    history["isu_cd"] = history["isu_cd"].map(base.norm_isu)
    history["entry_signal_date"] = history["entry_signal_date"].astype(str).str[:10]
    if history.duplicated(list(SIGNAL_KEY)).any():
        raise RuntimeError("prior-stage candidate history has duplicate entry keys")
    if not history["previous_pattern_a_stage"].astype(str).isin(STAGES).all():
        raise RuntimeError("prior-stage candidate history has an unknown previous Stage")
    if not history["entry_pattern_a_stage_recomputed"].astype(str).eq("PROGRESSED").all():
        raise RuntimeError("prior-stage candidate history contains a non-PROGRESSED entry")
    if not history["entry_pattern_a_lookahead_free"].map(entry_filter._bool).all():
        raise RuntimeError("prior-stage candidate history failed its PIT lookahead check")
    records = {}
    for row in history.to_dict("records"):
        records[_key(row)] = row
    return records, metadata


def _prepare_inputs(data_root: Path, resolved: Any) -> tuple[
    list[dict[str, Any]], pd.DataFrame, dict[tuple[str, str, str], dict[str, Any]],
    list[dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]],
    list[dict[str, Any]], dict[str, Any]
]:
    intervals, trading_dates, authority_provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusion_count = base._read_monthly_samples(data_root, intervals, interval_to_component)
    events_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for group in events_by_identity.values() for event in group]
    all_keys = [_key(event) for event in all_events]
    if len(all_keys) != len(set(all_keys)):
        raise RuntimeError("Pattern B source contains duplicate raw signal keys")

    linkage, linkage_metadata = entry_filter._read_stage_linkage(data_root, set(all_keys))
    entry_filter._attach_stages(all_events, linkage)
    linked_stage_by_key = {_key(row): row for row in linkage.to_dict("records")}
    if len(linked_stage_by_key) != len(linkage):
        raise RuntimeError("Pattern A linkage has duplicate candidate keys")
    if set(linked_stage_by_key) != set(all_keys):
        raise RuntimeError("fresh Pattern B event keys do not exactly match the authoritative Stage linkage")

    previous_rows, previous_metadata = _read_previous_stage_history(data_root)
    progressed_linkage_keys = {
        key for key, row in linked_stage_by_key.items()
        if str(row.get("pattern_a_stage")) == "PROGRESSED"
    }
    if progressed_linkage_keys != set(previous_rows):
        raise RuntimeError(
            "prior-stage history keys do not exactly cover every authoritative PROGRESSED candidate: "
            f"missing={len(progressed_linkage_keys - set(previous_rows))}, extra={len(set(previous_rows) - progressed_linkage_keys)}"
        )

    start = resolved.effective_start.strftime("%Y-%m-%d")
    end = resolved.effective_end.strftime("%Y-%m-%d")
    p1_events = []
    for event in all_events:
        if not (start <= event["entry_signal_date"] <= end):
            continue
        row = copy.deepcopy(event)
        key = _key(row)
        stage_row = linked_stage_by_key[key]
        row["pattern_a_stage"] = str(stage_row["pattern_a_stage"])
        row["pattern_a_stage_reason"] = stage_row.get("pattern_a_stage_reason")
        row["pattern_a_requested_asof"] = str(stage_row["pattern_a_requested_asof"])[:10]
        row["pattern_a_lookahead_free"] = entry_filter._bool(stage_row["pattern_a_lookahead_free"])
        row["pattern_a_last_daily_date"] = stage_row.get("pattern_a_last_daily_date")
        row["pattern_a_last_monthly_bar_date"] = stage_row.get("pattern_a_last_monthly_bar_date")
        row["pattern_a_last_weekly_bar_date"] = stage_row.get("pattern_a_last_weekly_bar_date")
        if row["pattern_a_stage"] not in STAGES:
            raise RuntimeError(f"unknown authoritative Pattern A stage for {key}")
        if row["pattern_a_requested_asof"] != row["entry_signal_date"] or not row["pattern_a_lookahead_free"]:
            raise RuntimeError(f"Pattern A entry stage is not exact-date PIT for {key}")
        if row["pattern_a_stage"] == "PROGRESSED":
            previous = previous_rows[key]
            row["previous_pattern_a_stage"] = str(previous["previous_pattern_a_stage"])
            row["previous_pattern_a_stage_date"] = str(previous["previous_pattern_a_stage_date"])
            row["progressed_segment_start_date"] = str(previous["progressed_segment_start_date"])
            row["progressed_segment_krx_sessions"] = int(previous["progressed_segment_krx_sessions"])
            row["previous_stage_definition_source"] = "committed progressed_previous_pattern_a_stage_v01 exact candidate history"
        else:
            row["previous_pattern_a_stage"] = None
            row["previous_pattern_a_stage_date"] = None
            row["progressed_segment_start_date"] = None
            row["progressed_segment_krx_sessions"] = None
            row["previous_stage_definition_source"] = None
        row["control_filter_status"], row["test_filter_status"] = _filter_decisions(
            row["pattern_a_stage"], row["previous_pattern_a_stage"]
        )
        p1_events.append(row)

    p1_keys = [_key(event) for event in p1_events]
    if len(p1_keys) != len(set(p1_keys)):
        raise RuntimeError("P1 candidate events contain duplicate keys")
    if any(event["previous_pattern_a_stage"] == "WEAK" for event in p1_events if event["test_filter_status"] == "PASS_PATTERN_A_PROGRESSED"):
        raise RuntimeError("TEST filter incorrectly admits a WEAK-origin signal")
    provenance = {
        "pattern_b_authorized_event_count": len(all_events),
        "pattern_b_authority_discontinuity_count": len(blocked),
        "p1_pattern_b_raw_event_count": len(p1_events),
        "p1_pattern_a_stage_counts": dict(sorted(Counter(event["pattern_a_stage"] for event in p1_events).items())),
        "p1_control_filter_pass_count": sum(event["control_filter_status"] == "PASS_PATTERN_A_PROGRESSED" for event in p1_events),
        "p1_test_weak_reject_count": sum(event["test_filter_status"] == "REJECTED_PREVIOUS_STAGE_WEAK" for event in p1_events),
        "p1_test_filter_pass_count": sum(event["test_filter_status"] == "PASS_PATTERN_A_PROGRESSED" for event in p1_events),
        "p1_progressed_previous_stage_counts": dict(sorted(Counter(event["previous_pattern_a_stage"] for event in p1_events if event["pattern_a_stage"] == "PROGRESSED").items())),
        "raw_candidate_key_mismatch_count": 0,
        "permanent_exclusion_identity_count": permanent_exclusion_count,
        "pattern_a_linkage_source_study_id": linkage_metadata.get("study_id"),
        "pattern_a_linkage_source_sha256": _sha256(data_root / entry_filter.STAGE_LINKAGE),
        "previous_stage_diagnostic_verdict": previous_metadata.get("verdict"),
        "previous_stage_history_sha256": _sha256(data_root / PREVIOUS_STAGE_HISTORY),
        "market_authority": authority_provenance,
        "interval_to_component": interval_to_component,
        "intervals_by_component": intervals_by_component,
    }
    return p1_events, samples, linked_stage_by_key, all_events, previous_rows, blocked, provenance


def _reset_candidate(event: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(event)
    result["entry_signal_status"] = "PENDING"
    result["trade_id"] = None
    result["entry_execution_date"] = None
    result["entry_reference_open"] = None
    result["status_reason"] = None
    return result


def _load_prices(
    data_root: Path,
    active_tickers: list[str],
    start: str,
    execution_support: str,
) -> tuple[dict[str, pd.DataFrame | None], dict[str, dict[str, Any]], Any]:
    repository = build_repository_v2(data_root, end=execution_support)
    loaded: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(
                RepositoryV2DailyLoader(repository, start=start, end=execution_support).load,
                ticker,
            ): ticker
            for ticker in active_tickers
        }
        for number, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            loaded[ticker] = future.result()
            if number % 100 == 0 or number == len(active_tickers):
                print(f"Loaded P1 authoritative OHLC: {number:,}/{len(active_tickers):,} tickers", flush=True)
    audit: dict[str, dict[str, Any]] = {}
    for ticker, daily in loaded.items():
        query = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        audit[ticker] = {
            "status": query.get("status"),
            "reason": query.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "projection": projection,
            "silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
        }
    return loaded, audit, repository


def _finish_exit_on_support(
    trades: list[dict[str, Any]],
    state: dict[str, Any],
    daily_by_component: dict[str, pd.DataFrame],
    period_end: str,
    execution_support: str,
) -> dict[str, Any]:
    pending = state.get("pending")
    position = state.get("position")
    if not pending or pending.get("kind") != "EXIT":
        return state
    if str(pending.get("signal_date")) > period_end or pending.get("fill_date") != execution_support:
        return state
    trade = pending["trade"]
    daily = daily_by_component.get(trade["component_id"], pd.DataFrame())
    if execution_support not in daily.index:
        return state
    closed_position, pending_after = base._apply_pending_fill(pending, position, trades, daily)
    if closed_position is not None or pending_after is not None:
        raise RuntimeError("P1 execution-support exit did not complete cleanly")
    for field in (
        "latest_state_date", "current_pattern_b_state", "cutoff_close", "valuation_status",
        "valuation_reason", "cutoff_valuation_date", "mark_to_cutoff_gross_return_pct",
    ):
        trade.pop(field, None)
    trade["p1_execution_support_exit_fill"] = True
    return {"position": None, "pending": None}


def _normalize_unfilled_p1_end_entries(events: list[dict[str, Any]], period_end: str) -> None:
    for event in events:
        if event.get("entry_signal_status") != "ENTRY_UNFILLED_AFTER_CUTOFF":
            continue
        if event.get("entry_signal_date") != period_end:
            raise RuntimeError("an in-window pre-end entry unexpectedly lacks an execution open")
        event["p1_entry_support_not_allowed_date"] = event.get("entry_execution_date")
        event["entry_signal_status"] = "ENTRY_NOT_FILLED_AFTER_P1_END"
        event["status_reason"] = "P1 execution support is reserved for exits; no new entry is filled after effective_end"
        event["entry_execution_date"] = None
        event["entry_reference_open"] = None
        event["trade_id"] = None


def _simulate_scenario(
    name: str,
    candidates: list[dict[str, Any]],
    samples: pd.DataFrame,
    daily_by_ticker: dict[str, pd.DataFrame | None],
    intervals_by_component: Mapping[tuple[str, str, str], list[dict[str, Any]]],
    trading_dates: list[str],
    period_start: str,
    period_end: str,
    execution_support: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str, str], pd.DataFrame]]:
    events = [_reset_candidate(event) for event in candidates]
    events_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_identity[(event["ticker"], event["isu_cd"])].append(event)
    active_identities = set(events_by_identity)
    active_samples = samples.loc[
        samples.apply(lambda row: (row["ticker"], row["isu_cd"]) in active_identities, axis=1)
        & samples["snapshot_date"].astype(str).le(period_end)
    ].copy()
    component_prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        ticker, isu = str(identity[0]), str(identity[1])
        daily = daily_by_ticker.get(ticker)
        for component in sorted(group["component_id"].unique()):
            authorized_intervals = intervals_by_component.get((ticker, isu, str(component)), [])
            component_prices[(ticker, isu, str(component))] = base._component_price_rows(
                daily, authorized_intervals, str(component)
            )

    trades: list[dict[str, Any]] = []
    original_strategy_id = base.STRATEGY_ID
    base.STRATEGY_ID = f"{STUDY_ID}_{name}"
    try:
        for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=True):
            normalized = (str(identity[0]), str(identity[1]))
            identity_events = events_by_identity.get(normalized, [])
            if not identity_events:
                continue
            observations = group.sort_values("snapshot_date").to_dict("records")
            daily_by_component = {
                str(component): component_prices.get((*normalized, str(component)), pd.DataFrame())
                for component in group["component_id"].dropna().astype(str).unique()
            }
            identity_trades, state = base._simulate_identity(
                observations, identity_events, daily_by_component, period_end
            )
            state = _finish_exit_on_support(identity_trades, state, daily_by_component, period_end, execution_support)
            if state.get("position") is not None and state["position"].get("cutoff_close") is None:
                state["position"]["valuation_reason"] = f"no exact adjusted close on P1 effective_end={period_end}"
            trades.extend(identity_trades)
    finally:
        base.STRATEGY_ID = original_strategy_id

    event_by_key = {_key(event): event for event in events}
    for event in events:
        if event.get("entry_signal_status") == "ENTRY_UNFILLED_AFTER_CUTOFF":
            event["p1_entry_support_not_allowed_date"] = event.get("entry_execution_date")
    _normalize_unfilled_p1_end_entries(events, period_end)
    for trade in trades:
        event = event_by_key[_key(trade)]
        for field in (
            "pattern_a_stage", "pattern_a_stage_reason", "pattern_a_requested_asof", "pattern_a_lookahead_free",
            "pattern_a_last_daily_date", "pattern_a_last_monthly_bar_date", "pattern_a_last_weekly_bar_date",
            "previous_pattern_a_stage", "previous_pattern_a_stage_date", "progressed_segment_start_date",
            "progressed_segment_krx_sessions",
        ):
            trade[field] = event.get(field)
        daily = component_prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        base._path_metrics(trade, daily, trading_dates, period_end)
        base._calculate_returns(trade)

    status_counts = Counter(event.get("entry_signal_status") for event in events)
    filled = len(trades)
    realized = sum(trade.get("trade_status") == "REALIZED" for trade in trades)
    opened = sum(trade.get("trade_status") == "OPEN_AT_CUTOFF" for trade in trades)
    if filled != realized + opened:
        raise RuntimeError(f"{name}: P1 filled trades do not reconcile to realized plus open")
    if filled != status_counts["FILLED"]:
        raise RuntimeError(f"{name}: P1 FILLED statuses do not reconcile to the trade ledger")
    if any(event["pattern_a_stage"] != "PROGRESSED" for event in events):
        raise RuntimeError(f"{name}: a non-PROGRESSED entry passed the exact Pattern A filter")
    if name == "TEST" and any(event["previous_pattern_a_stage"] == "WEAK" for event in events):
        raise RuntimeError("TEST admitted a WEAK-origin P1 entry")
    trading_set = set(trading_dates)
    for trade in trades:
        if not (period_start <= trade["entry_signal_date"] <= period_end):
            raise RuntimeError(f"{name}: entry signal falls outside P1")
        if not (trade["entry_signal_date"] < trade["entry_execution_date"] <= period_end):
            raise RuntimeError(f"{name}: new entry executed outside the P1 period")
        if trade["entry_execution_date"] not in trading_set:
            raise RuntimeError(f"{name}: entry execution is not an exact KRX session")
        if trade.get("exit_execution_date"):
            if trade["exit_execution_date"] not in trading_set or trade["exit_execution_date"] <= trade["exit_signal_date"]:
                raise RuntimeError(f"{name}: exit execution is not a later exact KRX session")
            if trade["exit_execution_date"] > execution_support:
                raise RuntimeError(f"{name}: exit execution is later than P1 support")
            if trade["exit_execution_date"] > period_end and trade.get("p1_execution_support_exit_fill") is not True:
                raise RuntimeError(f"{name}: post-P1 exit fill lacks execution-support provenance")
    if len({trade["trade_id"] for trade in trades}) != len(trades):
        raise RuntimeError(f"{name}: duplicate trade identifiers")
    for identity, group in pd.DataFrame(trades).groupby(["ticker", "isu_cd"], sort=False) if trades else []:
        ordered = sorted(group.to_dict("records"), key=lambda row: row["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = previous.get("exit_execution_date") or period_end
            if current["entry_execution_date"] <= previous_end:
                raise RuntimeError(f"{name}: overlapping positions for ISU {identity}")
    return trades, events, component_prices


def _trade_group_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked_open = [trade for trade in opened if _safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
    open_returns = [trade.get("mark_to_cutoff_gross_return_pct") for trade in marked_open]
    gross = base._metric_summary(trade.get("gross_return_pct") for trade in realized)
    pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in realized)
    net = base._metric_summary(trade.get("full_standard_net_return_pct") for trade in realized)
    path = base._path_summary(trades)
    marked = base._metric_summary(open_returns)
    return {
        "filled_count": len(trades),
        "realized_count": len(realized),
        "open_count": len(opened),
        "open_rate_pct": 100.0 * len(opened) / len(trades) if trades else None,
        "realized_gross": gross,
        "realized_costed_pre_tax": pre_tax,
        "realized_full_standard_net": net,
        "mfe_mae_holding": path,
        "open_exact_mark_count": len(marked_open),
        "open_unresolved_count": len(opened) - len(marked_open),
        "open_marked_gross": marked,
        "open_cutoff_state_counts": dict(sorted(Counter(
            str(trade.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE") for trade in opened
        ).items())),
    }


def _scenario_summary(
    name: str,
    raw_events: list[dict[str, Any]],
    passed_events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    samples: pd.DataFrame,
) -> dict[str, Any]:
    trade_stats = _trade_group_summary(trades)
    deep_keys = prior_stage._deep_trade_keys(trades, samples)
    deep_trades = [trade for trade in trades if _key(trade) in deep_keys]
    deep_realized = [trade for trade in deep_trades if trade.get("trade_status") == "REALIZED"]
    deep_stats = base._metric_summary(trade.get("gross_return_pct") for trade in deep_realized)
    open_deep = sum(trade.get("trade_status") == "OPEN_AT_CUTOFF" for trade in deep_trades)
    statuses = Counter(event.get("entry_signal_status") for event in passed_events)
    return {
        "scenario": name,
        "pattern_b_raw_entry_candidates": len(raw_events),
        "pattern_a_progressed_candidate_count": sum(event["pattern_a_stage"] == "PROGRESSED" for event in raw_events),
        "filter_pass_count": len(passed_events),
        "filter_reject_count": len(raw_events) - len(passed_events),
        "entry_signal_status_counts": dict(sorted(statuses.items())),
        **trade_stats,
        "deep_cohort": {
            "deep_arrival_count": len(deep_trades),
            "deep_arrival_rate_of_filled_pct": 100.0 * len(deep_trades) / len(trades) if trades else None,
            "deep_realized_count": len(deep_realized),
            "deep_realized_win_rate_pct": deep_stats["win_rate_pct"],
            "deep_realized_mean_gross_pct": deep_stats["mean_pct"],
            "deep_realized_median_gross_pct": deep_stats["median_pct"],
            "deep_mean_mae_pct": base._metric_summary(trade.get("mae_pct") for trade in deep_trades)["mean_pct"],
            "deep_median_mae_pct": base._metric_summary(trade.get("mae_pct") for trade in deep_trades)["median_pct"],
            "deep_open_count": open_deep,
        },
    }


def _comparison_frame(summaries: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for summary in summaries:
        gross = summary["realized_gross"]
        path = summary["mfe_mae_holding"]
        open_gross = summary["open_marked_gross"]
        deep = summary["deep_cohort"]
        row = {
            "scenario": summary["scenario"],
            "pattern_b_raw_entry_candidates": summary["pattern_b_raw_entry_candidates"],
            "pattern_a_progressed_candidate_count": summary["pattern_a_progressed_candidate_count"],
            "filter_pass_count": summary["filter_pass_count"],
            "filter_reject_count": summary["filter_reject_count"],
            "filled_trades": summary["filled_count"],
            "realized_trades": summary["realized_count"],
            "open_trades": summary["open_count"],
            "open_rate_pct": summary["open_rate_pct"],
        }
        row.update({f"gross_{key}": gross[key] for key in TRADE_METRICS})
        row.update({
            "costed_pre_tax_mean_pct": summary["realized_costed_pre_tax"]["mean_pct"],
            "costed_pre_tax_median_pct": summary["realized_costed_pre_tax"]["median_pct"],
            "full_standard_net_mean_pct": summary["realized_full_standard_net"]["mean_pct"],
            "full_standard_net_median_pct": summary["realized_full_standard_net"]["median_pct"],
            "mean_mfe_pct": path["mean_mfe_pct"],
            "median_mfe_pct": path["median_mfe_pct"],
            "mean_mae_pct": path["mean_mae_pct"],
            "median_mae_pct": path["median_mae_pct"],
            "mean_holding_sessions": path["mean_holding_krx_sessions"],
            "median_holding_sessions": path["median_holding_krx_sessions"],
            "p90_holding_sessions": path["p90_holding_krx_sessions"],
            "open_exact_mark_count": summary["open_exact_mark_count"],
            "open_unresolved_count": summary["open_unresolved_count"],
            "open_marked_mean_gross_pct": open_gross["mean_pct"],
            "open_marked_median_gross_pct": open_gross["median_pct"],
            "open_marked_le_30_count": open_gross["le_30_count"],
            "open_marked_le_30_rate_pct": open_gross["le_30_rate_pct"],
            "open_marked_le_50_count": open_gross["le_50_count"],
            "open_marked_le_50_rate_pct": open_gross["le_50_rate_pct"],
            "open_cutoff_state_counts": json.dumps(summary["open_cutoff_state_counts"], ensure_ascii=False, sort_keys=True),
            **deep,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _deep_frame(summaries: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{"scenario": row["scenario"], **row["deep_cohort"]} for row in summaries])


def _open_frame(summaries: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for summary in summaries:
        stats = summary["open_marked_gross"]
        rows.append({
            "scenario": summary["scenario"],
            "open_count": summary["open_count"],
            "exact_cutoff_marked_count": summary["open_exact_mark_count"],
            "unresolved_count": summary["open_unresolved_count"],
            "marked_mean_gross_pct": stats["mean_pct"],
            "marked_median_gross_pct": stats["median_pct"],
            "marked_le_30_count": stats["le_30_count"],
            "marked_le_30_rate_pct": stats["le_30_rate_pct"],
            "marked_le_50_count": stats["le_50_count"],
            "marked_le_50_rate_pct": stats["le_50_rate_pct"],
            "cutoff_pattern_b_state_counts": json.dumps(summary["open_cutoff_state_counts"], ensure_ascii=False, sort_keys=True),
        })
    return pd.DataFrame(rows)


def _annual_comparison(
    raw_events: list[dict[str, Any]],
    control_events: list[dict[str, Any]],
    test_events: list[dict[str, Any]],
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
) -> pd.DataFrame:
    years = sorted({str(event["entry_signal_date"])[:4] for event in raw_events})
    result = []
    scenarios = (
        ("CONTROL", control_events, control_trades),
        ("TEST", test_events, test_trades),
    )
    for year in years:
        for name, events, trades in scenarios:
            raw_year = [event for event in raw_events if str(event["entry_signal_date"])[:4] == year]
            candidate_year = [event for event in events if str(event["entry_signal_date"])[:4] == year]
            trade_year = [trade for trade in trades if str(trade["entry_signal_date"])[:4] == year]
            realized = [trade for trade in trade_year if trade.get("trade_status") == "REALIZED"]
            opened = [trade for trade in trade_year if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
            gross = base._metric_summary(trade.get("gross_return_pct") for trade in realized)
            result.append({
                "scenario": name,
                "entry_year": int(year),
                "pattern_b_raw_candidates": len(raw_year),
                "pattern_a_filter_pass": len(candidate_year),
                "filled": len(trade_year),
                "realized": len(realized),
                "open": len(opened),
                "open_rate_pct": 100.0 * len(opened) / len(trade_year) if trade_year else None,
                "realized_median_gross_pct": gross["median_pct"],
                "realized_win_rate_pct": gross["win_rate_pct"],
                "realized_ge_50_count": gross["ge_50_count"],
                "realized_ge_50_rate_pct": gross["ge_50_rate_pct"],
                "realized_le_30_count": gross["le_30_count"],
                "realized_le_30_rate_pct": gross["le_30_rate_pct"],
                "realized_le_50_count": gross["le_50_count"],
                "realized_le_50_rate_pct": gross["le_50_rate_pct"],
                "right_censored_recent_year": year == "2026",
            })
    return pd.DataFrame(result)


def _direct_effect(
    raw_events: list[dict[str, Any]],
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
) -> pd.DataFrame:
    control_by_key = {_key(trade): trade for trade in control_trades}
    test_by_key = {_key(trade): trade for trade in test_trades}
    weak_keys = {
        _key(event) for event in raw_events
        if event["pattern_a_stage"] == "PROGRESSED" and event["previous_pattern_a_stage"] == "WEAK"
    }
    weak_control_trades = [control_by_key[key] for key in sorted(weak_keys) if key in control_by_key]
    control_without_weak = [trade for trade in control_trades if trade.get("previous_pattern_a_stage") != "WEAK"]
    test_new = [trade for key, trade in test_by_key.items() if key not in control_by_key]
    groups = [
        ("CONTROL_WEAK_ORIGIN_FILLED", len(weak_keys), weak_control_trades),
        ("CONTROL_SIMPLE_AFTER_THE_FACT_WEAK_DELETION", sum(event["control_filter_status"] == "PASS_PATTERN_A_PROGRESSED" for event in raw_events) - len(weak_keys), control_without_weak),
        ("TEST_INDEPENDENT_REPLAY", sum(event["test_filter_status"] == "PASS_PATTERN_A_PROGRESSED" for event in raw_events), test_trades),
        ("TEST_NEW_ENTRY_KEYS_VS_CONTROL", len(test_new), test_new),
    ]
    rows = []
    for group_name, signal_count, trades in groups:
        summary = _trade_group_summary(trades)
        gross = summary["realized_gross"]
        realized_returns = [
            _safe_num(trade.get("gross_return_pct"))
            for trade in trades
            if trade.get("trade_status") == "REALIZED"
        ]
        realized_returns = [value for value in realized_returns if value is not None]
        rows.append({
            "group": group_name,
            "signal_or_key_count": signal_count,
            "filled": summary["filled_count"],
            "realized": summary["realized_count"],
            "open": summary["open_count"],
            "winner_count": sum(value > 0 for value in realized_returns),
            "loser_count": sum(value < 0 for value in realized_returns),
            "median_gross_pct": gross["median_pct"],
            "win_rate_pct": gross["win_rate_pct"],
            "ge_50_count": gross["ge_50_count"],
            "ge_50_rate_pct": gross["ge_50_rate_pct"],
            "le_30_count": gross["le_30_count"],
            "le_30_rate_pct": gross["le_30_rate_pct"],
            "le_50_count": gross["le_50_count"],
            "le_50_rate_pct": gross["le_50_rate_pct"],
        })
    posthoc = next(row for row in rows if row["group"] == "CONTROL_SIMPLE_AFTER_THE_FACT_WEAK_DELETION")
    independent = next(row for row in rows if row["group"] == "TEST_INDEPENDENT_REPLAY")
    delta_fields = (
        "signal_or_key_count", "filled", "realized", "open", "winner_count", "loser_count",
        "median_gross_pct", "win_rate_pct", "ge_50_count", "ge_50_rate_pct",
        "le_30_count", "le_30_rate_pct", "le_50_count", "le_50_rate_pct",
    )
    difference = {"group": "TEST_INDEPENDENT_MINUS_CONTROL_POSTHOC"}
    for field in delta_fields:
        posthoc_value = _safe_num(posthoc.get(field))
        independent_value = _safe_num(independent.get(field))
        difference[field] = (
            independent_value - posthoc_value
            if posthoc_value is not None and independent_value is not None else None
        )
    rows.append(difference)
    return pd.DataFrame(rows)


def _annual_risk_improved_years(annual: pd.DataFrame) -> list[int]:
    control = annual.loc[annual["scenario"] == "CONTROL"].set_index("entry_year")
    test = annual.loc[annual["scenario"] == "TEST"].set_index("entry_year")
    improved = []
    for year in control.index.intersection(test.index):
        c = control.loc[year]
        t = test.loc[year]
        metrics = (
            (c["realized_le_30_rate_pct"], t["realized_le_30_rate_pct"]),
            (c["realized_le_50_rate_pct"], t["realized_le_50_rate_pct"]),
        )
        if any(
            _safe_num(c_value) is not None and _safe_num(t_value) is not None
            and float(c_value) - float(t_value) >= PERCENTAGE_POINT_TOLERANCE - FLOAT_COMPARISON_EPSILON
            for c_value, t_value in metrics
        ):
            improved.append(int(year))
    return improved


def _verdict(control: Mapping[str, Any], test: Mapping[str, Any], annual: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    c = control["realized_gross"]
    t = test["realized_gross"]
    quality_deltas = {
        "median_gross_pct": (t["median_pct"] - c["median_pct"]) if c["median_pct"] is not None and t["median_pct"] is not None else None,
        "win_rate_pct": (t["win_rate_pct"] - c["win_rate_pct"]) if c["win_rate_pct"] is not None and t["win_rate_pct"] is not None else None,
        "ge_50_rate_pct": (t["ge_50_rate_pct"] - c["ge_50_rate_pct"]) if c["ge_50_rate_pct"] is not None and t["ge_50_rate_pct"] is not None else None,
    }
    cdeep = control["deep_cohort"]["deep_arrival_rate_of_filled_pct"]
    tdeep = test["deep_cohort"]["deep_arrival_rate_of_filled_pct"]
    risk_deltas = {
        "le_30_rate_pct": (c["le_30_rate_pct"] - t["le_30_rate_pct"]) if c["le_30_rate_pct"] is not None and t["le_30_rate_pct"] is not None else None,
        "le_50_rate_pct": (c["le_50_rate_pct"] - t["le_50_rate_pct"]) if c["le_50_rate_pct"] is not None and t["le_50_rate_pct"] is not None else None,
        "deep_arrival_rate_pct": (cdeep - tdeep) if cdeep is not None and tdeep is not None else None,
    }
    quality_nonworse = all(
        value is not None and value >= -PERCENTAGE_POINT_TOLERANCE - FLOAT_COMPARISON_EPSILON
        for value in quality_deltas.values()
    )
    quality_materially_worse_count = sum(
        value is not None and value < -PERCENTAGE_POINT_TOLERANCE - FLOAT_COMPARISON_EPSILON
        for value in quality_deltas.values()
    )
    risk_improvement_count = sum(
        value is not None and value >= PERCENTAGE_POINT_TOLERANCE - FLOAT_COMPARISON_EPSILON
        for value in risk_deltas.values()
    )
    risk_improved_years = _annual_risk_improved_years(annual)
    if quality_nonworse and risk_improvement_count >= 2 and len(risk_improved_years) >= 3:
        verdict = "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED"
    elif risk_improvement_count == 0 or quality_materially_worse_count >= 2:
        verdict = "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_NO_BENEFIT"
    else:
        verdict = "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_MIXED"
    return verdict, {
        "percentage_point_tolerance": PERCENTAGE_POINT_TOLERANCE,
        "quality_deltas_test_minus_control": quality_deltas,
        "risk_deltas_control_minus_test": risk_deltas,
        "quality_all_nonworse": quality_nonworse,
        "quality_metrics_materially_worse_count": quality_materially_worse_count,
        "risk_metrics_improved_count": risk_improvement_count,
        "risk_improved_entry_years": risk_improved_years,
        "risk_improvement_spans_at_least_three_years": len(risk_improved_years) >= 3,
    }


def _lifecycle_spot_checks(
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
    control_events: list[dict[str, Any]],
    test_events: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    trading_dates: list[str],
    period_start: str,
    period_end: str,
    execution_support: str,
) -> pd.DataFrame:
    randomizer = random.Random(SEED)
    available = {
        "CONTROL": sorted(control_trades, key=lambda row: _key(row)),
        "TEST": sorted(test_trades, key=lambda row: _key(row)),
    }
    selected = []
    for name in ("CONTROL", "TEST"):
        pool = available[name]
        count = min(REVIEW_COUNT // 2, len(pool))
        selected.extend((name, row) for row in randomizer.sample(pool, count))
    if len(selected) < REVIEW_COUNT:
        remaining = [
            (name, row) for name, pool in available.items() for row in pool
            if (name, _key(row)) not in {(s_name, _key(s_trade)) for s_name, s_trade in selected}
        ]
        selected.extend((name, row) for name, row in randomizer.sample(remaining, REVIEW_COUNT - len(selected)))
    if len(selected) != REVIEW_COUNT:
        raise RuntimeError(f"cannot make {REVIEW_COUNT} lifecycle spot checks from P1 trades")
    control_by_key = {_key(event): event for event in control_events}
    test_by_key = {_key(event): event for event in test_events}
    raw_by_key = {_key(event): event for event in all_events}
    trading_set = set(trading_dates)
    rows = []
    for scenario, trade in selected:
        key = _key(trade)
        event = control_by_key.get(key) if scenario == "CONTROL" else test_by_key.get(key)
        raw = raw_by_key[key]
        if event is None:
            raise RuntimeError(f"spot-check trade has no same-scenario entry event: {scenario} {key}")
        checks = {
            "exact_p1_entry_date": period_start <= trade["entry_signal_date"] <= period_end,
            "next_exact_session_entry": trade["entry_execution_date"] in trading_set and trade["entry_execution_date"] > trade["entry_signal_date"],
            "no_entry_after_p1_end": trade["entry_execution_date"] <= period_end,
            "entry_pattern_b_transition": base.is_entry_transition(event["previous_state"], event["entry_signal_state"], base.month_is_adjacent(event["previous_state_date"], event["entry_signal_date"])),
            "entry_pattern_a_stage_exact": raw["pattern_a_stage"] == "PROGRESSED" and raw["pattern_a_requested_asof"] == raw["entry_signal_date"] and raw["pattern_a_lookahead_free"],
            "test_does_not_admit_weak": scenario != "TEST" or raw["previous_pattern_a_stage"] != "WEAK",
            "component_key_exact": trade["component_id"] == event["component_id"],
        }
        if trade.get("trade_status") == "REALIZED":
            checks["normal_exit_state"] = trade.get("exit_signal_state") == "NORMAL"
            checks["exact_later_exit_session"] = trade.get("exit_execution_date") in trading_set and trade.get("exit_execution_date") > trade.get("exit_signal_date")
            checks["exit_no_later_than_support"] = trade.get("exit_execution_date") <= execution_support
            checks["gross_return_reconciles"] = math.isclose(
                (float(trade["exit_reference_open"]) / float(trade["entry_reference_open"]) - 1.0) * 100.0,
                float(trade["gross_return_pct"]), rel_tol=1e-10, abs_tol=1e-9,
            )
        else:
            checks["exact_cutoff_or_unresolved"] = (
                trade.get("valuation_status") == "UNRESOLVED" and trade.get("cutoff_close") is None
            ) or (
                trade.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE"
                and trade.get("cutoff_valuation_date") == period_end
                and trade.get("cutoff_close") is not None
            )
            checks["open_has_no_exit_execution"] = trade.get("exit_execution_date") is None
        rows.append({
            "review_id": f"{scenario}_{len(rows) + 1:02d}",
            "scenario": scenario,
            "ticker": trade["ticker"],
            "isu_cd": trade["isu_cd"],
            "entry_signal_date": trade["entry_signal_date"],
            "previous_pattern_a_stage": raw["previous_pattern_a_stage"],
            "entry_execution_date": trade["entry_execution_date"],
            "trade_status": trade["trade_status"],
            "exit_signal_date": trade.get("exit_signal_date"),
            "exit_execution_date": trade.get("exit_execution_date"),
            **{f"check_{name}": bool(value) for name, value in checks.items()},
            "all_checks_pass": all(checks.values()),
        })
    result = pd.DataFrame(rows)
    if not result["all_checks_pass"].all():
        raise RuntimeError("P1 lifecycle spot check failed")
    return result


def _records_by_key(events: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    result = {_key(event): event for event in events}
    if len(result) != len(events):
        raise RuntimeError("duplicate event key in scenario simulation")
    return result


def _filter_audit(
    raw_events: list[dict[str, Any]],
    control_events: list[dict[str, Any]],
    test_events: list[dict[str, Any]],
) -> pd.DataFrame:
    control_by_key = _records_by_key(control_events)
    test_by_key = _records_by_key(test_events)
    rows = []
    for raw in raw_events:
        key = _key(raw)
        control = control_by_key.get(key)
        test = test_by_key.get(key)
        rows.append({
            "ticker": key[0], "isu_cd": key[1], "entry_signal_date": key[2],
            "previous_state_date": raw["previous_state_date"],
            "previous_pattern_b_state": raw["previous_state"],
            "entry_pattern_b_state": raw["entry_signal_state"],
            "component_id": raw["component_id"],
            "pattern_a_stage": raw["pattern_a_stage"],
            "pattern_a_stage_reason": raw.get("pattern_a_stage_reason"),
            "pattern_a_requested_asof": raw["pattern_a_requested_asof"],
            "pattern_a_lookahead_free": raw["pattern_a_lookahead_free"],
            "previous_pattern_a_stage": raw.get("previous_pattern_a_stage"),
            "previous_pattern_a_stage_date": raw.get("previous_pattern_a_stage_date"),
            "progressed_segment_start_date": raw.get("progressed_segment_start_date"),
            "progressed_segment_krx_sessions": raw.get("progressed_segment_krx_sessions"),
            "control_filter_status": raw["control_filter_status"],
            "control_lifecycle_status": control.get("entry_signal_status") if control else "REJECTED_PATTERN_A_NOT_PROGRESSED",
            "control_trade_id": control.get("trade_id") if control else None,
            "control_execution_date": control.get("entry_execution_date") if control else None,
            "test_filter_status": raw["test_filter_status"],
            "test_lifecycle_status": test.get("entry_signal_status") if test else raw["test_filter_status"],
            "test_trade_id": test.get("trade_id") if test else None,
            "test_execution_date": test.get("entry_execution_date") if test else None,
            "test_p1_support_not_allowed_date": test.get("p1_entry_support_not_allowed_date") if test else None,
        })
    return pd.DataFrame(rows)


def _format_pct(value: Any) -> str:
    number = _safe_num(value)
    return "—" if number is None else f"{number:.2f}%"


def _format_number(value: Any, places: int = 2) -> str:
    number = _safe_num(value)
    return "—" if number is None else f"{number:,.{places}f}"


def _report(
    window: Mapping[str, Any],
    summaries: list[dict[str, Any]],
    comparison: pd.DataFrame,
    deep: pd.DataFrame,
    opened: pd.DataFrame,
    annual: pd.DataFrame,
    direct: pd.DataFrame,
    verdict: str,
    rubric: Mapping[str, Any],
    validations: Mapping[str, Any],
) -> str:
    by_name = {row["scenario"]: row for row in summaries}
    direct_by_group = {row["group"]: row for row in direct.to_dict("records")}
    lines = [
        "# Pattern B + PROGRESSED 이전 WEAK 제외 P1 단순 백테스트 V01",
        "",
        f"판정: `{verdict}`",
        "",
        "## 기간 및 계약",
        "",
        f"- Window `P1`; calendar range {window['calendar_range'][0]}~{window['calendar_range'][1]}; resolver 결과 {window['effective_start']}~{window['effective_end']}; execution support {window['execution_support']}.",
        "- CONTROL은 `Pattern B DEPRESSED 신규 진입 + 진입일 Pattern A exact PROGRESSED`; TEST는 동일 조건에서 이전 authoritative Stage가 `WEAK`인 신규 진입만 제외했어. `UNAVAILABLE`은 허용했어.",
        "- CONTROL/TEST를 P1 시작부터 각각 독립 replay했어. P1 시작 전 포지션 carry-in은 없고, TEST를 CONTROL 원장에서 사후 삭제해 만들지 않았어.",
        "- P1 종료일 이후 신규 진입 체결은 막았어. 2026-09-01 support는 2026-08-31까지 확정된 exit 신호의 체결에만 썼어. 미청산은 2026-08-31 exact adjusted close로 평가했어.",
        f"- 비용: 매수/매도 수수료 {base.COMMISSION_RATE * 100:.3f}%, 매수/매도 슬리피지 {base.SLIPPAGE_RATE * 100:.2f}%, 실제 매도일·시장별 역사적 세금표. 핵심 성과 비교는 기존 simple strategy 계약대로 gross야.",
        "- 동일 ISU 동시 보유 0, 부분체결은 사용하지 않았어. PIT universe·identity·permanent exclusion 및 completed monthly Pattern B 입력은 기존 계약을 유지했어.",
        "",
        "## CONTROL / TEST 비교",
        "",
        "| 시나리오 | P1 raw B 진입 | A PROGRESSED 통과 | WEAK 제외 | 체결/실현/미청산 | 미청산률 | 평균/중앙 gross | 승률 | PF | 기대값 | +20 / +50 / +100 | -20 / -30 / -50 | Deep 도달 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        gross = summary["realized_gross"]
        lines.append(
            f"| {summary['scenario']} | {summary['pattern_b_raw_entry_candidates']:,} | {summary['pattern_a_progressed_candidate_count']:,} | "
            f"{summary['pattern_a_progressed_candidate_count'] - summary['filter_pass_count']:,} | "
            f"{summary['filled_count']:,}/{summary['realized_count']:,}/{summary['open_count']:,} | {_format_pct(summary['open_rate_pct'])} | "
            f"{_format_pct(gross['mean_pct'])}/{_format_pct(gross['median_pct'])} | {_format_pct(gross['win_rate_pct'])} | "
            f"{_format_number(gross['profit_factor'])} | {_format_pct(gross['expectancy_pct'])} | "
            f"{_format_pct(gross['ge_20_rate_pct'])}/{_format_pct(gross['ge_50_rate_pct'])}/{_format_pct(gross['ge_100_rate_pct'])} | "
            f"{_format_pct(gross['le_20_rate_pct'])}/{_format_pct(gross['le_30_rate_pct'])}/{_format_pct(gross['le_50_rate_pct'])} | "
            f"{summary['deep_cohort']['deep_arrival_count']:,} ({_format_pct(summary['deep_cohort']['deep_arrival_rate_of_filled_pct'])}) |"
        )
    lines += [
        "",
        "평균·중앙 수익률은 실현 거래 gross 기준이야. MFE/MAE와 보유기간은 realized/open 체결 원장의 P1 경로 지표고, 비용 반영 전후 수익률은 `control_vs_test.csv`에 같이 있어.",
        "",
        "## Pattern B DEEP 도달 cohort",
        "",
        "| 시나리오 | 체결 | DEEP 도달 | 도달률 | DEEP 실현 승률 | 평균/중앙 gross | 평균/중앙 MAE | DEEP open |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in deep.to_dict("records"):
        lines.append(
            f"| {row['scenario']} | {by_name[row['scenario']]['filled_count']:,} | {row['deep_arrival_count']:,} | {_format_pct(row['deep_arrival_rate_of_filled_pct'])} | "
            f"{_format_pct(row['deep_realized_win_rate_pct'])} | {_format_pct(row['deep_realized_mean_gross_pct'])}/{_format_pct(row['deep_realized_median_gross_pct'])} | "
            f"{_format_pct(row['deep_mean_mae_pct'])}/{_format_pct(row['deep_median_mae_pct'])} | {row['deep_open_count']:,} |"
        )
    lines += [
        "",
        "## 미청산 P1 cutoff 평가",
        "",
        "| 시나리오 | 미청산 | exact 평가 | 미해결 | 평가 평균/중앙 gross | -30 이하 | -50 이하 | cutoff Pattern B 상태 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in opened.to_dict("records"):
        lines.append(
            f"| {row['scenario']} | {row['open_count']:,} | {row['exact_cutoff_marked_count']:,} | {row['unresolved_count']:,} | "
            f"{_format_pct(row['marked_mean_gross_pct'])}/{_format_pct(row['marked_median_gross_pct'])} | "
            f"{row['marked_le_30_count']:,} ({_format_pct(row['marked_le_30_rate_pct'])}) | "
            f"{row['marked_le_50_count']:,} ({_format_pct(row['marked_le_50_rate_pct'])}) | {row['cutoff_pattern_b_state_counts']} |"
        )
    lines += [
        "",
        "## WEAK 제외 직접 효과",
        "",
        "`weak_exclusion_direct_effect.csv`는 CONTROL에서 WEAK-origin으로 실제 체결된 거래, CONTROL 원장의 사후 삭제 참고값, 독립 TEST, TEST에서만 새로 생긴 entry key를 비교해. 승·패는 실현 gross 수익률 기준이고, 사후 삭제와 독립 TEST 차이를 마지막 행에 따로 계산했어.",
        "",
        "| 비교군 | 후보/key | 체결/실현/open | 승/패 | 중앙 gross | 승률 | +50% | -30% | -50% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in direct.to_dict("records"):
        lines.append(
            f"| {row['group']} | {_format_number(row.get('signal_or_key_count'), 0)} | "
            f"{_format_number(row.get('filled'), 0)}/{_format_number(row.get('realized'), 0)}/{_format_number(row.get('open'), 0)} | "
            f"{_format_number(row.get('winner_count'), 0)}/{_format_number(row.get('loser_count'), 0)} | "
            f"{_format_pct(row.get('median_gross_pct'))} | {_format_pct(row.get('win_rate_pct'))} | "
            f"{_format_number(row.get('ge_50_count'), 0)} ({_format_pct(row.get('ge_50_rate_pct'))}) | "
            f"{_format_number(row.get('le_30_count'), 0)} ({_format_pct(row.get('le_30_rate_pct'))}) | "
            f"{_format_number(row.get('le_50_count'), 0)} ({_format_pct(row.get('le_50_rate_pct'))}) |"
        )
    lines += [
        "",
        "## P1 진입연도 비교",
        "",
        "연도별 filled/realized/open과 중앙수익·승률·+50·-30·미청산률은 `annual_comparison.csv`에 기록했어. 2026년 진입은 기간 종료로 오른쪽 검열 영향이 있어.",
        "",
        "## 사전 판정 규칙 적용",
        "",
        f"- float 비교 허용오차는 절대 {PERCENTAGE_POINT_TOLERANCE:.1f} percentage point야. TEST 품질 지표의 CONTROL 대비 변화(중앙 gross/승률/+50)는 {json.dumps(rubric['quality_deltas_test_minus_control'], ensure_ascii=False)}.",
        f"- 핵심 위험 개선(control minus test: -30/-50/DEEP)은 {json.dumps(rubric['risk_deltas_control_minus_test'], ensure_ascii=False)}. 개선 지표 {rubric['risk_metrics_improved_count']}/3; 연도별 손실률 개선 관측 {rubric['risk_improved_entry_years']}.",
        f"- `IMPROVED` 조건의 품질 비악화={rubric['quality_all_nonworse']}, 위험 2개 이상 개선={rubric['risk_metrics_improved_count'] >= 2}, 개선 분포 3개 이상 연도={rubric['risk_improvement_spans_at_least_three_years']}.",
        f"- 최종 판정 `{verdict}`. cutoff open tail은 보조 지표로만 봤어.",
        "",
        "## 검증",
        "",
        f"- P1 resolver exact: {window['effective_start']}~{window['effective_end']}, support {window['execution_support']}; raw linkage mismatch {validations['raw_candidate_key_mismatch_count']}; 미래 Pattern A 입력 {validations['future_pattern_a_input_count']}.",
        f"- TEST WEAK-origin 진입 통과 {validations['test_weak_origin_pass_count']}; entry after P1 end {validations['entry_after_p1_end_count']}; exact P1 cutoff/open evaluations {validations['open_exact_mark_count']}/{validations['open_unresolved_count']}; 동일 ISU overlap CONTROL/TEST {validations['control_overlap_count']}/{validations['test_overlap_count']}.",
        f"- Repository V2 tickers {validations['price_ticker_count']:,}; adjusted OHLC rows {validations['price_rows_loaded']:,}; silent inner drops {validations['repository_v2_silent_inner_drop_count']}; workers {WORKERS}.",
        f"- lifecycle spot checks {validations['lifecycle_spot_check_pass_count']}/{validations['lifecycle_spot_check_count']}; focused tests, py_compile, git diff --check 실행. 전체 pytest는 실행하지 않았어.",
        "",
        "## 최종 질문",
        "",
        f"1. tail risk: realized -30/-50 개선(control-test)은 `{json.dumps({'le_30': rubric['risk_deltas_control_minus_test']['le_30_rate_pct'], 'le_50': rubric['risk_deltas_control_minus_test']['le_50_rate_pct']}, ensure_ascii=False)}` pp, DEEP 도달률 개선은 `{_format_number(rubric['risk_deltas_control_minus_test']['deep_arrival_rate_pct'])}` pp야. 사전 기준상 3개 중 {rubric['risk_metrics_improved_count']}개가 0.1pp 이상 개선됐어.",
        f"2. median/win/+50 의미 있는 훼손 여부: `{rubric['quality_metrics_materially_worse_count'] > 0}` ({rubric['quality_metrics_materially_worse_count']}/3 지표가 0.1pp 초과 악화). TEST−CONTROL 변화는 `{json.dumps(rubric['quality_deltas_test_minus_control'], ensure_ascii=False)}` pp야.",
        f"3. 독립 재생 뒤의 변화: TEST weak-origin 통과 `{validations['test_weak_origin_pass_count']}`건, CONTROL weak-origin 실제 체결 `{_format_number(direct_by_group['CONTROL_WEAK_ORIGIN_FILLED']['filled'], 0)}`건. 사후 삭제 대비 TEST 독립 replay의 체결 수 차이는 `{_format_number(direct_by_group['TEST_INDEPENDENT_MINUS_CONTROL_POSTHOC']['filled'], 0)}`건이야. CONTROL weak-origin과 비-WEAK 사후삭제군의 손실률을 위 표에서 직접 비교했어.",
        f"4. 정식 개선안으로 다음 단계에 넘길 근거: `{'있어' if verdict == 'PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED' else '아직 충분하지 않아'}`. 이 결론은 사전 판정 규칙을 그대로 적용했어.",
        f"5. 판정: `{verdict}`.",
        "",
        "## 산출물",
        "",
        "`control_vs_test.csv`, CONTROL/TEST trade·open ledger, `entry_filter_audit.csv`, `weak_exclusion_direct_effect.csv`, `deep_cohort_comparison.csv`, `annual_comparison.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: Path, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
    if isinstance(frame, pd.DataFrame):
        frame.to_csv(path, index=False, encoding="utf-8")
    else:
        pd.DataFrame(frame).to_csv(path, index=False, encoding="utf-8")


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root).resolve()
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE).resolve()
    git_start = _assert_git_start(data_root)
    resolved, window = _resolve_p1(data_root)
    p1_events, samples, stage_by_key, all_source_events, previous_rows, blocked, source_provenance = _prepare_inputs(data_root, resolved)
    start, end, support = window["effective_start"], window["effective_end"], window["execution_support"]

    control_candidates = [
        _reset_candidate(event) for event in p1_events
        if event["control_filter_status"] == "PASS_PATTERN_A_PROGRESSED"
    ]
    test_candidates = [
        _reset_candidate(event) for event in p1_events
        if event["test_filter_status"] == "PASS_PATTERN_A_PROGRESSED"
    ]
    active_tickers = sorted({event["ticker"] for event in control_candidates})
    daily_by_ticker, ticker_audit, repository = _load_prices(data_root, active_tickers, start, support)
    intervals_by_component = source_provenance.pop("intervals_by_component")
    source_provenance.pop("interval_to_component")
    all_events = p1_events
    _, trading_dates, _ = base._load_authorities(data_root)
    control_trades, control_events, control_component_prices = _simulate_scenario(
        "CONTROL", control_candidates, samples, daily_by_ticker, intervals_by_component,
        trading_dates,
        start, end, support,
    )
    if not control_events and control_candidates:
        raise RuntimeError("CONTROL P1 candidate events disappeared during independent replay")
    test_trades, test_events, test_component_prices = _simulate_scenario(
        "TEST", test_candidates, samples, daily_by_ticker, intervals_by_component,
        trading_dates, start, end, support,
    )

    control_summary = _scenario_summary("CONTROL", all_events, control_events, control_trades, samples)
    test_summary = _scenario_summary("TEST", all_events, test_events, test_trades, samples)
    annual = _annual_comparison(all_events, control_events, test_events, control_trades, test_trades)
    verdict, rubric = _verdict(control_summary, test_summary, annual)
    comparison = _comparison_frame([control_summary, test_summary])
    deep = _deep_frame([control_summary, test_summary])
    opened = _open_frame([control_summary, test_summary])
    direct = _direct_effect(all_events, control_trades, test_trades)
    control_open = [row for row in control_trades if row.get("trade_status") == "OPEN_AT_CUTOFF"]
    test_open = [row for row in test_trades if row.get("trade_status") == "OPEN_AT_CUTOFF"]
    spot = _lifecycle_spot_checks(
        control_trades, test_trades, control_events, test_events, all_events,
        trading_dates, start, end, support,
    )

    raw_by_key = {_key(event): event for event in all_events}
    control_by_key = _records_by_key(control_events)
    test_by_key = _records_by_key(test_events)
    audit = _filter_audit(all_events, control_events, test_events)
    weak_keys = {
        _key(event) for event in all_events
        if event["pattern_a_stage"] == "PROGRESSED" and event["previous_pattern_a_stage"] == "WEAK"
    }
    test_weak_pass = sum(
        event["previous_pattern_a_stage"] == "WEAK" for event in test_events
    )
    if test_weak_pass != 0:
        raise RuntimeError("TEST includes a WEAK-origin entry after replay")
    for event in all_events:
        key = _key(event)
        if event["pattern_a_stage"] == "PROGRESSED" and key not in previous_rows:
            raise RuntimeError(f"P1 PROGRESSED entry has no previous-stage history: {key}")
    if len(control_by_key) != len(control_events) or len(test_by_key) != len(test_events):
        raise RuntimeError("duplicate signal key in independent scenario signal ledgers")
    support_entry_count = sum(
        event.get("p1_entry_support_not_allowed_date") == support
        for event in (*control_events, *test_events)
    )
    entry_after_end_count = sum(
        trade["entry_execution_date"] > end for trade in (*control_trades, *test_trades)
    )
    if entry_after_end_count:
        raise RuntimeError("a new entry was filled after the P1 effective end")
    if any(trade.get("exit_execution_date") == support and trade.get("p1_execution_support_exit_fill") is not True for trade in (*control_trades, *test_trades)):
        raise RuntimeError("execution-support exit lacks explicit P1 support provenance")
    control_overlap = entry_filter._overlap_count(control_trades) if hasattr(entry_filter, "_overlap_count") else 0
    test_overlap = entry_filter._overlap_count(test_trades) if hasattr(entry_filter, "_overlap_count") else 0
    if not hasattr(entry_filter, "_overlap_count"):
        control_overlap = _overlap_count(control_trades, end)
        test_overlap = _overlap_count(test_trades, end)
    if control_overlap or test_overlap:
        raise RuntimeError(f"same-ISU position overlap: CONTROL={control_overlap}, TEST={test_overlap}")

    projection_drops = sum(int(row.get("silent_inner_drop_count", 0)) for row in ticker_audit.values())
    validations = {
        "raw_candidate_key_mismatch_count": 0,
        "p1_raw_pattern_b_candidate_count": len(all_events),
        "p1_control_pattern_a_pass_count": len(control_candidates),
        "p1_test_pattern_a_pass_count": len(test_candidates),
        "p1_weak_origin_exclusion_count": len(weak_keys),
        "test_weak_origin_pass_count": test_weak_pass,
        "future_pattern_a_input_count": sum(not event["pattern_a_lookahead_free"] for event in all_events),
        "entry_after_p1_end_count": entry_after_end_count,
        "p1_end_entry_support_blocked_count": support_entry_count,
        "execution_support_exit_fill_count": sum(trade.get("p1_execution_support_exit_fill") is True for trade in (*control_trades, *test_trades)),
        "control_filled_trade_count": len(control_trades),
        "test_filled_trade_count": len(test_trades),
        "control_realized_trade_count": sum(trade.get("trade_status") == "REALIZED" for trade in control_trades),
        "test_realized_trade_count": sum(trade.get("trade_status") == "REALIZED" for trade in test_trades),
        "control_open_trade_count": len(control_open),
        "test_open_trade_count": len(test_open),
        "control_overlap_count": control_overlap,
        "test_overlap_count": test_overlap,
        "open_exact_mark_count": len([trade for trade in (*control_open, *test_open) if trade.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE"]),
        "open_unresolved_count": len([trade for trade in (*control_open, *test_open) if trade.get("valuation_status") == "UNRESOLVED"]),
        "price_ticker_count": len(ticker_audit),
        "price_rows_loaded": sum(int(row.get("rows", 0)) for row in ticker_audit.values()),
        "repository_v2_silent_inner_drop_count": projection_drops,
        "lifecycle_spot_check_count": len(spot),
        "lifecycle_spot_check_pass_count": int(spot["all_checks_pass"].sum()),
        "workers": WORKERS,
        "blocked_authority_discontinuity_count": len(blocked),
        "cutoff_entry_support_blocked_count": support_entry_count,
    }
    zero_checks = (
        "raw_candidate_key_mismatch_count", "future_pattern_a_input_count",
        "entry_after_p1_end_count", "test_weak_origin_pass_count", "control_overlap_count",
        "test_overlap_count", "repository_v2_silent_inner_drop_count",
    )
    if any(validations[key] != 0 for key in zero_checks):
        raise RuntimeError(f"P1 validation failed: {validations}")
    if validations["lifecycle_spot_check_pass_count"] != REVIEW_COUNT:
        raise RuntimeError(f"P1 lifecycle review did not fully pass: {validations}")
    if validations["control_filled_trade_count"] != validations["control_realized_trade_count"] + validations["control_open_trade_count"]:
        raise RuntimeError("CONTROL realized plus open does not reconcile")
    if validations["test_filled_trade_count"] != validations["test_realized_trade_count"] + validations["test_open_trade_count"]:
        raise RuntimeError("TEST realized plus open does not reconcile")

    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, pd.DataFrame | list[dict[str, Any]]] = {
        "control_vs_test.csv": comparison,
        "control_trade_ledger.csv": control_trades,
        "test_trade_ledger.csv": test_trades,
        "control_open_positions.csv": control_open,
        "test_open_positions.csv": test_open,
        "entry_filter_audit.csv": audit,
        "weak_exclusion_direct_effect.csv": direct,
        "deep_cohort_comparison.csv": deep,
        "annual_comparison.csv": annual,
        "lifecycle_spot_checks.csv": spot,
    }
    for filename, frame in generated.items():
        _write_csv(output_dir / filename, frame)

    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "window": window,
        "starting_git": git_start,
        "control_definition": "P1 independent replay: Pattern B DEPRESSED new entry and exact entry-date Pattern A PROGRESSED",
        "test_definition": "P1 independent replay with only previous authoritative Pattern A WEAK -> current PROGRESSED new entries rejected",
        "control_summary": control_summary,
        "test_summary": test_summary,
        "direct_effect_records": direct.to_dict("records"),
        "annual_records": annual.to_dict("records"),
        "rubric": rubric,
        "validations": validations,
        "cost_contract": {
            "primary_comparison": "gross",
            "buy_commission_rate": base.COMMISSION_RATE,
            "sell_commission_rate": base.COMMISSION_RATE,
            "buy_slippage_rate": base.SLIPPAGE_RATE,
            "sell_slippage_rate": base.SLIPPAGE_RATE,
            "sell_tax_schedule": list(base.HISTORICAL_SELL_TAX_SCHEDULE),
            "cutoff_open_mark_includes_exit_cost": False,
        },
        "source_provenance": {key: value for key, value in source_provenance.items() if key not in {"market_authority"}},
        "elapsed_seconds": round(time.time() - started, 2),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(_json_clean(summary), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report = _report(window, [control_summary, test_summary], comparison, deep, opened, annual, direct, verdict, rubric, validations)
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    source_paths = [
        base.SAMPLE_PATH, base.PIT_PATH, base.CALENDAR_PATH,
        entry_filter.STAGE_LINKAGE, entry_filter.STAGE_METADATA,
        PREVIOUS_STAGE_HISTORY, PREVIOUS_STAGE_METADATA,
        PREVIOUS_STAGE_SUMMARY,
        Path("scripts/run_pattern_b_pure_simple_backtest_v01.py"),
        Path("scripts/run_pattern_b_pattern_a_entry_filter_simple_v01.py"),
        Path("scripts/analyze_pattern_b_progressed_previous_pattern_a_stage_v01.py"),
    ]
    metadata = {
        "study_id": STUDY_ID,
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d"),
        "starting_git": git_start,
        "window": window,
        "pattern_a_authority": "trend_scanner.patterns.pattern_a_stage.classify_pattern_a_stage; prior-stage exact segment semantics reused from committed candidate history",
        "pattern_b_entry_source": "committed monthly snapshot sample + run_pattern_b_pure_simple_backtest_v01._make_entry_signals",
        "previous_stage_semantics_source": str(PREVIOUS_STAGE_HISTORY),
        "previous_stage_definition": "immediately preceding different authoritative Pattern A classifier stage before the contiguous monthly PROGRESSED segment; UNAVAILABLE remains separate",
        "control_and_test_independent_replays": True,
        "no_control_trade_ledger_posthoc_filter_for_test": True,
        "trade_cost_contract": summary["cost_contract"],
        "source_sha256": {path.as_posix(): _sha256(data_root / path) for path in source_paths},
        "code_sha256": {
            "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py": _sha256(Path(__file__).resolve()),
            "tests/test_run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py": _sha256(data_root / "tests/test_run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py"),
        },
        "price_load_audit": ticker_audit,
        "validations": validations,
        "generated_files": {
            filename: {"sha256": _sha256(output_dir / filename), "bytes": (output_dir / filename).stat().st_size}
            for filename in [*generated, "summary.json", "report.md"]
        },
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(_json_clean(metadata), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_json_clean({
        "verdict": verdict,
        "p1_window": window,
        "control": control_summary,
        "test": test_summary,
        "rubric": rubric,
        "validations": validations,
        "output": str(output_dir),
    }), ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    return summary


def _overlap_count(trades: list[dict[str, Any]], cutoff: str) -> int:
    overlaps = 0
    for _identity, group in pd.DataFrame(trades).groupby(["ticker", "isu_cd"], sort=False) if trades else []:
        ordered = sorted(group.to_dict("records"), key=lambda row: row["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["entry_execution_date"] <= (previous.get("exit_execution_date") or cutoff):
                overlaps += 1
    return overlaps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
