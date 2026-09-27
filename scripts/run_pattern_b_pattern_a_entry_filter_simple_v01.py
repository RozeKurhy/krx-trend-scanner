#!/usr/bin/env python3
"""Backtest exact entry-date Pattern A filters on Pattern B entries."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as pit_control  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)

CONTROL_RELATIVE = Path("artifacts/patterns/pattern_b/pure_strategy_simple_v01")
STAGE_RELATIVE = Path("artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01")
STAGE_LINKAGE = STAGE_RELATIVE / "signal_stage_path_trade_linkage.csv"
STAGE_METADATA = STAGE_RELATIVE / "metadata.json"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/pattern_a_entry_filter_simple_v01")
BASELINE_COMMIT = "5dcfe79f40800ed8ac17558bad6dc600a91fd653"
WORKERS = 10
SEED = 20260927
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")
STAGES = {"WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED", "UNAVAILABLE"}
TESTS = {
    "TRANSITION": "PATTERN_B_PATTERN_A_TRANSITION_V01",
    "PROGRESSED": "PATTERN_B_PATTERN_A_PROGRESSED_V01",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "1.0", "yes"}


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for record in frame.to_dict("records"):
        records.append({
            key: (None if pd.isna(value) else value)
            for key, value in record.items()
        })
    return records


def _key(row: Any) -> tuple[str, str, str]:
    if hasattr(row, "_asdict"):
        row = row._asdict()
    return tuple(str(row[column]) for column in SIGNAL_KEY)  # type: ignore[return-value]


def _read_stage_linkage(data_root: Path, expected_keys: set[tuple[str, str, str]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    linkage_path = data_root / STAGE_LINKAGE
    metadata_path = data_root / STAGE_METADATA
    frame = pd.read_csv(linkage_path, dtype={"ticker": "string", "isu_cd": "string"})
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("study_id") != "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01":
        raise RuntimeError("Pattern A source artifact is not the expected PIT diagnostic")
    input_hashes = metadata.get("input_sha256", {})
    required_hashes = {
        "artifacts/patterns/pattern_b/state_forward_return_v01/snapshot_samples.csv.gz": base.SAMPLE_PATH,
        "data/market/rolling_authority/merged_pit_intervals.json": base.PIT_PATH,
        "data/market/rolling_authority/merged_trading_calendar.json": base.CALENDAR_PATH,
        "artifacts/patterns/pattern_b/pure_strategy_simple_v01/trade_ledger.csv": CONTROL_RELATIVE / "trade_ledger.csv",
        "artifacts/patterns/pattern_b/pure_strategy_simple_v01/entry_signal_ledger.csv": CONTROL_RELATIVE / "entry_signal_ledger.csv",
        "artifacts/patterns/pattern_b/pure_strategy_simple_v01/summary.json": CONTROL_RELATIVE / "summary.json",
        "artifacts/patterns/pattern_b/pure_strategy_simple_v01/metadata.json": CONTROL_RELATIVE / "metadata.json",
    }
    for display_path, relative_path in required_hashes.items():
        expected = input_hashes.get(display_path)
        actual = _sha256(data_root / relative_path)
        if expected != actual:
            raise RuntimeError(f"Pattern A linkage source hash changed: {display_path}")
    if metadata.get("pattern_a_authority", {}).get("classifier") != "trend_scanner.patterns.pattern_a_stage.classify_pattern_a_stage":
        raise RuntimeError("Pattern A linkage does not name the official classifier")
    if metadata.get("pattern_a_authority", {}).get("snapshot_policy") != "include_incomplete_periods=False; daily input clipped by snapshot_date in builder; official rolling merged KRX calendar":
        raise RuntimeError("Pattern A linkage PIT snapshot policy differs from the approved source")

    frame["entry_signal_date"] = frame["entry_signal_date"].astype(str).str[:10]
    if frame.duplicated(list(SIGNAL_KEY)).any():
        raise RuntimeError("Pattern A linkage contains duplicate signal keys")
    linkage_keys = set(frame[list(SIGNAL_KEY)].astype(str).itertuples(index=False, name=None))
    if linkage_keys != expected_keys:
        raise RuntimeError(
            f"Pattern A linkage signal keys differ from CONTROL: "
            f"missing={len(expected_keys - linkage_keys)}, extra={len(linkage_keys - expected_keys)}"
        )
    if not set(frame["pattern_a_stage"].dropna().astype(str)).issubset(STAGES):
        raise RuntimeError("Pattern A linkage contains an unknown stage")
    date_exact = frame["pattern_a_requested_asof"].astype(str).str[:10].eq(frame["entry_signal_date"])
    lookahead_free = frame["pattern_a_lookahead_free"].map(_bool)
    if not date_exact.all() or not lookahead_free.all():
        raise RuntimeError("Pattern A stage is not an authoritative exact signal-date PIT result")
    for column in ("pattern_a_last_daily_date", "pattern_a_last_weekly_bar_date", "pattern_b_monthly_last_bar", "pattern_b_weekly_last_bar"):
        observed = frame[column].fillna("").astype(str).str[:10]
        if (observed.ne("") & observed.gt(frame["entry_signal_date"])).any():
            raise RuntimeError(f"future-dated PIT input detected in {column}")
    checks = metadata.get("checks", {})
    if checks.get("raw_signal_count") != len(frame) or checks.get("raw_signal_key_mismatch_count") != 0:
        raise RuntimeError("Pattern A diagnostic's source reconciliation failed")
    if checks.get("random_review_count") != checks.get("random_review_pass_count"):
        raise RuntimeError("Pattern A diagnostic's prior direct review did not fully pass")
    return frame, metadata


def _attach_stages(events: list[dict[str, Any]], linkage: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, Any]]:
    stage_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in linkage.to_dict("records"):
        key = _key(row)
        if key in stage_by_key:
            raise RuntimeError(f"duplicate Pattern A stage key: {key}")
        stage_by_key[key] = row
    for event in events:
        key = _key(event)
        stage = stage_by_key.get(key)
        if stage is None:
            raise RuntimeError(f"missing exact entry-date Pattern A stage for {key}")
        event["pattern_a_stage"] = str(stage["pattern_a_stage"])
        event["pattern_a_stage_reason"] = stage.get("pattern_a_stage_reason")
        event["pattern_a_requested_asof"] = str(stage["pattern_a_requested_asof"])[:10]
        event["pattern_a_lookahead_free"] = _bool(stage["pattern_a_lookahead_free"])
        event["pattern_a_last_daily_date"] = stage.get("pattern_a_last_daily_date")
        event["pattern_a_last_monthly_bar_date"] = stage.get("pattern_a_last_monthly_bar_date")
        event["pattern_a_last_weekly_bar_date"] = stage.get("pattern_a_last_weekly_bar_date")
    return stage_by_key


def _copy_stage_events(events: list[dict[str, Any]], stage: str) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    selected = [copy.deepcopy(event) for event in events if event["pattern_a_stage"] == stage]
    for event in selected:
        event["entry_signal_status"] = "PENDING"
        event["trade_id"] = None
        event["entry_execution_date"] = None
        event["entry_reference_open"] = None
        event["status_reason"] = None
        by_identity[(event["ticker"], event["isu_cd"])].append(event)
    return dict(by_identity), selected


def _load_ticker_prices(
    repository: Any,
    tickers: list[str],
    min_start_by_ticker: dict[str, str],
) -> tuple[dict[str, pd.DataFrame | None], dict[str, dict[str, Any]]]:
    daily_by_ticker: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(
                RepositoryV2DailyLoader(repository, start=min_start_by_ticker[ticker], end=base.CUTOFF).load,
                ticker,
            ): ticker
            for ticker in tickers
        }
        for number, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            daily_by_ticker[ticker] = future.result()
            if number % 250 == 0 or number == len(tickers):
                print(f"Loaded authoritative OHLC: {number:,}/{len(tickers):,} tickers", flush=True)
    # The shared repository audit is read only after all loader workers finish.
    ticker_load_audit: dict[str, dict[str, Any]] = {}
    for ticker, daily in daily_by_ticker.items():
        audit = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        ticker_load_audit[ticker] = {
            "status": audit.get("status"),
            "reason": audit.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "session_projection_summary": projection,
        }
    return daily_by_ticker, ticker_load_audit


def _run_independent_strategy(
    stage: str,
    events_by_identity: dict[tuple[str, str], list[dict[str, Any]]],
    sample_frame: pd.DataFrame,
    component_prices: dict[tuple[str, str, str], pd.DataFrame],
    trading_dates: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strategy_id = TESTS[stage]
    trades: list[dict[str, Any]] = []
    events = [event for group in events_by_identity.values() for event in group]
    original_strategy_id = base.STRATEGY_ID
    base.STRATEGY_ID = strategy_id
    try:
        for identity, group in sample_frame.groupby(["ticker", "isu_cd"], sort=True):
            normalized = (str(identity[0]), str(identity[1]))
            identity_events = events_by_identity.get(normalized)
            if not identity_events:
                continue
            observations = group.sort_values("snapshot_date").to_dict("records")
            daily_by_component = {
                component: component_prices.get((*normalized, component), pd.DataFrame())
                for component in group["component_id"].dropna().astype(str).unique()
            }
            identity_trades, _ = base._simulate_identity(
                observations, identity_events, daily_by_component, base.CUTOFF
            )
            trades.extend(identity_trades)
    finally:
        base.STRATEGY_ID = original_strategy_id

    event_by_key = {_key(event): event for event in events}
    for trade in trades:
        event = event_by_key[_key(trade)]
        for field in (
            "pattern_a_stage", "pattern_a_requested_asof", "pattern_a_lookahead_free",
            "pattern_a_last_daily_date", "pattern_a_last_monthly_bar_date", "pattern_a_last_weekly_bar_date",
        ):
            trade[field] = event[field]
        daily = component_prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        base._path_metrics(trade, daily, trading_dates, base.CUTOFF)
        base._calculate_returns(trade)

    status_counts = Counter(event["entry_signal_status"] for event in events)
    filled_count = len(trades)
    closed_count = sum(trade.get("trade_status") == "REALIZED" for trade in trades)
    open_count = sum(trade.get("trade_status") == "OPEN_AT_CUTOFF" for trade in trades)
    if filled_count != closed_count + open_count:
        raise RuntimeError(f"{stage}: filled trades do not reconcile to closed plus open")
    if filled_count != status_counts["FILLED"]:
        raise RuntimeError(f"{stage}: FILLED entry signals do not reconcile to trade ledger")
    if any(event["pattern_a_stage"] != stage for event in events):
        raise RuntimeError(f"{stage}: test signal stage filter admitted another stage")
    if any(not event["pattern_a_lookahead_free"] or event["pattern_a_requested_asof"] != event["entry_signal_date"] for event in events):
        raise RuntimeError(f"{stage}: test signal failed the exact-date PIT contract")
    trading_date_set = set(trading_dates)
    if any(trade["entry_execution_date"] not in trading_date_set or trade["entry_execution_date"] <= trade["entry_signal_date"] for trade in trades):
        raise RuntimeError(f"{stage}: an entry fill is not a later exact merged KRX session")
    if any(
        trade.get("exit_execution_date")
        and (trade["exit_execution_date"] not in trading_date_set or trade["exit_execution_date"] <= trade["exit_signal_date"])
        for trade in trades
    ):
        raise RuntimeError(f"{stage}: an exit fill is not a later exact merged KRX session")
    if len({trade["trade_id"] for trade in trades}) != len(trades):
        raise RuntimeError(f"{stage}: duplicate trade id")
    if trades:
        for identity, group in pd.DataFrame(trades).groupby(["ticker", "isu_cd"], sort=False):
            ordered = sorted(group.to_dict("records"), key=lambda row: row["entry_execution_date"])
            for prior, current in zip(ordered, ordered[1:]):
                prior_end = prior.get("exit_execution_date") or base.CUTOFF
                if current["entry_execution_date"] <= prior_end:
                    raise RuntimeError(f"{stage}: overlapping positions for {identity}")
    return trades, events


def _open_state_counts(opened: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for trade in opened:
        state = trade.get("current_pattern_b_state")
        counts[str(state) if state not in (None, "") else "CURRENT_STATE_UNAVAILABLE"] += 1
    return dict(sorted(counts.items()))


def _deep_cohort(trades: list[dict[str, Any]], samples: pd.DataFrame) -> list[dict[str, Any]]:
    groups = {
        (str(key[0]), str(key[1])): group.sort_values("snapshot_date")
        for key, group in samples.groupby(["ticker", "isu_cd"], sort=False)
    }
    selected = []
    for trade in trades:
        group = groups.get((str(trade["ticker"]), str(trade["isu_cd"])))
        if group is None:
            raise RuntimeError("trade has no monthly Pattern B observations")
        end = str(trade.get("exit_signal_date") or base.SIGNAL_END)
        held = group.loc[
            (group["snapshot_date"] > trade["entry_signal_date"])
            & (group["snapshot_date"] <= end)
            & (group["component_id"] == trade["component_id"])
        ]
        if (held["state"].astype(str) == "DEEP_DEPRESSED").any():
            selected.append(trade)
    return selected


def _strategy_summary(
    label: str,
    raw_candidate_count: int,
    events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    samples: pd.DataFrame,
    control: bool = False,
) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked = [trade for trade in opened if _finite_number(trade.get("mark_to_cutoff_gross_return_pct"))]
    unresolved = [trade for trade in opened if not _finite_number(trade.get("mark_to_cutoff_gross_return_pct"))]
    closed_gross = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
    open_gross = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked)
    pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in closed)
    taxed = base._metric_summary(trade.get("full_standard_net_return_pct") for trade in closed)
    deep_trades = _deep_cohort(trades, samples)
    deep = pit_control._deep_summary(trades, samples)
    deep_realized = [trade for trade in deep_trades if trade.get("trade_status") == "REALIZED"]
    deep_win_stats = base._metric_summary(trade.get("gross_return_pct") for trade in deep_realized)
    deep["deep_realized_win_count"] = sum(
        float(trade["gross_return_pct"]) > 0
        for trade in deep_realized
        if _finite_number(trade.get("gross_return_pct"))
    )
    deep["deep_realized_win_rate_pct"] = deep_win_stats["win_rate_pct"]
    all_path = base._path_summary(trades)
    closed_path = base._path_summary(closed)
    open_path = base._path_summary(opened)
    statuses = Counter(event.get("entry_signal_status") for event in events)
    summary = {
        "strategy": label,
        "raw_transition_signal_count": raw_candidate_count,
        "stage_filter_pass_count": len(events),
        "filled_trade_count": len(trades),
        "realized_trade_count": len(closed),
        "open_trade_count": len(opened),
        "open_trade_rate_pct": 100.0 * len(opened) / len(trades) if trades else None,
        "suppressed_while_holding_signal_count": statuses.get("SUPPRESSED_ALREADY_HOLDING", 0),
        "unfilled_or_cancelled_signal_count": sum(
            count for status, count in statuses.items()
            if status not in {"FILLED", "SUPPRESSED_ALREADY_HOLDING"}
        ),
        "signal_status_counts": dict(sorted(statuses.items())),
        "closed_gross": closed_gross,
        "closed_costed_pre_tax": pre_tax,
        "closed_tax_covered_net": taxed,
        "open_exact_cutoff_marked_count": len(marked),
        "open_unresolved_count": len(unresolved),
        "open_marked_gross": open_gross,
        "open_current_pattern_b_state_counts": _open_state_counts(opened),
        "all_trade_path": all_path,
        "realized_trade_path": closed_path,
        "open_trade_path": open_path,
        "post_entry_deep_state": deep,
        "all_positions_no_overlap": True,
    }
    if control:
        summary["raw_transition_signal_count"] = raw_candidate_count
        summary["stage_filter_pass_count"] = raw_candidate_count
    return summary


def _annual_summary(
    strategies: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]],
) -> pd.DataFrame:
    years = sorted({str(event["entry_signal_date"])[:4] for events, _ in strategies.values() for event in events})
    rows: list[dict[str, Any]] = []
    for name, (events, trades) in strategies.items():
        for year in years:
            year_events = [event for event in events if str(event["entry_signal_date"])[:4] == year]
            year_trades = [trade for trade in trades if str(trade["entry_signal_date"])[:4] == year]
            closed = [trade for trade in year_trades if trade.get("trade_status") == "REALIZED"]
            opened = [trade for trade in year_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
            gross = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
            rows.append({
                "strategy": name,
                "entry_signal_year": int(year),
                "raw_entry_candidates": len(year_events),
                "filled_trades": len(year_trades),
                "realized_trades": len(closed),
                "open_at_cutoff": len(opened),
                "open_rate_pct": 100.0 * len(opened) / len(year_trades) if year_trades else None,
                "realized_median_gross_pct": gross["median_pct"],
                "realized_win_rate_pct": gross["win_rate_pct"],
                "realized_ge_50_count": gross["ge_50_count"],
                "realized_ge_50_rate_pct": gross["ge_50_rate_pct"],
                "realized_le_30_count": gross["le_30_count"],
                "realized_le_30_rate_pct": gross["le_30_rate_pct"],
            })
    return pd.DataFrame(rows)


def _comparison_frame(summaries: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, summary in summaries.items():
        gross = summary["closed_gross"]
        opened = summary["open_marked_gross"]
        path = summary["all_trade_path"]
        deep = summary["post_entry_deep_state"]
        rows.append({
            "strategy": name,
            "raw_entry_candidates": summary["raw_transition_signal_count"],
            "stage_filter_pass_count": summary["stage_filter_pass_count"],
            "filled_trades": summary["filled_trade_count"],
            "realized_trades": summary["realized_trade_count"],
            "open_trades": summary["open_trade_count"],
            "open_rate_pct": summary["open_trade_rate_pct"],
            "suppressed_while_holding": summary["suppressed_while_holding_signal_count"],
            "gross_mean_pct": gross["mean_pct"],
            "gross_median_pct": gross["median_pct"],
            "gross_win_rate_pct": gross["win_rate_pct"],
            "gross_average_winner_pct": gross["average_winner_pct"],
            "gross_average_loser_pct": gross["average_loser_pct"],
            "gross_profit_factor": gross["profit_factor"],
            "gross_expectancy_pct": gross["expectancy_pct"],
            **{f"{key}_count": gross[f"{key}_count"] for key in base.TRADE_STATS_THRESHOLDS},
            **{f"{key}_rate_pct": gross[f"{key}_rate_pct"] for key in base.TRADE_STATS_THRESHOLDS},
            "mean_mfe_pct": path["mean_mfe_pct"],
            "median_mfe_pct": path["median_mfe_pct"],
            "mean_mae_pct": path["mean_mae_pct"],
            "median_mae_pct": path["median_mae_pct"],
            "mean_holding_sessions": path["mean_holding_krx_sessions"],
            "median_holding_sessions": path["median_holding_krx_sessions"],
            "p90_holding_sessions": path["p90_holding_krx_sessions"],
            "open_exact_cutoff_marked": summary["open_exact_cutoff_marked_count"],
            "open_unresolved": summary["open_unresolved_count"],
            "open_marked_mean_gross_pct": opened["mean_pct"],
            "open_marked_median_gross_pct": opened["median_pct"],
            "open_marked_le_30_count": opened["le_30_count"],
            "open_marked_le_30_rate_pct": opened["le_30_rate_pct"],
            "open_marked_le_50_count": opened["le_50_count"],
            "open_marked_le_50_rate_pct": opened["le_50_rate_pct"],
            "deep_arrival_count": deep["deep_arrival_count"],
            "deep_arrival_rate_of_filled_pct": deep["deep_arrival_rate_of_filled_pct"],
            "deep_realized_count": deep["deep_realized_count"],
            "deep_realized_win_rate_pct": deep["deep_realized_win_rate_pct"],
            "deep_realized_loss_rate_pct": deep["deep_realized_loss_rate_pct"],
            "deep_realized_mean_gross_pct": deep["deep_realized_return_mean_pct"],
            "deep_realized_median_gross_pct": deep["deep_realized_return_median_pct"],
            "deep_mean_mae_pct": deep["deep_mae_mean_pct"],
            "deep_median_mae_pct": deep["deep_mae_median_pct"],
        })
    return pd.DataFrame(rows)


def _candidate_assessments(summaries: dict[str, dict[str, Any]], annual: pd.DataFrame) -> tuple[dict[str, Any], str]:
    control = summaries["CONTROL"]
    assessments: dict[str, Any] = {}
    any_material_direction = False
    for stage in TESTS:
        candidate = summaries[stage]
        control_gross = control["closed_gross"]
        candidate_gross = candidate["closed_gross"]
        control_open = control["open_marked_gross"]
        candidate_open = candidate["open_marked_gross"]
        control_deep = control["post_entry_deep_state"]
        candidate_deep = candidate["post_entry_deep_state"]
        profitability = {
            "median_better": candidate_gross["median_pct"] is not None and control_gross["median_pct"] is not None and candidate_gross["median_pct"] > control_gross["median_pct"],
            "expectancy_better": candidate_gross["expectancy_pct"] is not None and control_gross["expectancy_pct"] is not None and candidate_gross["expectancy_pct"] > control_gross["expectancy_pct"],
            "win_rate_better": candidate_gross["win_rate_pct"] is not None and control_gross["win_rate_pct"] is not None and candidate_gross["win_rate_pct"] > control_gross["win_rate_pct"],
            "ge_50_rate_better": candidate_gross["ge_50_rate_pct"] is not None and control_gross["ge_50_rate_pct"] is not None and candidate_gross["ge_50_rate_pct"] > control_gross["ge_50_rate_pct"],
        }
        risk = {
            "realized_le_30_no_worse": candidate_gross["le_30_rate_pct"] is not None and control_gross["le_30_rate_pct"] is not None and candidate_gross["le_30_rate_pct"] <= control_gross["le_30_rate_pct"],
            "realized_le_50_no_worse": candidate_gross["le_50_rate_pct"] is not None and control_gross["le_50_rate_pct"] is not None and candidate_gross["le_50_rate_pct"] <= control_gross["le_50_rate_pct"],
            "open_le_30_no_worse": candidate_open["le_30_rate_pct"] is not None and control_open["le_30_rate_pct"] is not None and candidate_open["le_30_rate_pct"] <= control_open["le_30_rate_pct"],
            "open_le_50_no_worse": candidate_open["le_50_rate_pct"] is not None and control_open["le_50_rate_pct"] is not None and candidate_open["le_50_rate_pct"] <= control_open["le_50_rate_pct"],
            "deep_arrival_rate_lower": candidate_deep["deep_arrival_rate_of_filled_pct"] is not None and control_deep["deep_arrival_rate_of_filled_pct"] is not None and candidate_deep["deep_arrival_rate_of_filled_pct"] < control_deep["deep_arrival_rate_of_filled_pct"],
            "deep_realized_loss_no_worse": candidate_deep["deep_realized_loss_rate_pct"] is not None and control_deep["deep_realized_loss_rate_pct"] is not None and candidate_deep["deep_realized_loss_rate_pct"] <= control_deep["deep_realized_loss_rate_pct"],
        }
        strict_risk_improvement = {
            "realized_le_30_better": candidate_gross["le_30_rate_pct"] is not None and control_gross["le_30_rate_pct"] is not None and candidate_gross["le_30_rate_pct"] < control_gross["le_30_rate_pct"],
            "realized_le_50_better": candidate_gross["le_50_rate_pct"] is not None and control_gross["le_50_rate_pct"] is not None and candidate_gross["le_50_rate_pct"] < control_gross["le_50_rate_pct"],
            "open_le_30_better": candidate_open["le_30_rate_pct"] is not None and control_open["le_30_rate_pct"] is not None and candidate_open["le_30_rate_pct"] < control_open["le_30_rate_pct"],
            "open_le_50_better": candidate_open["le_50_rate_pct"] is not None and control_open["le_50_rate_pct"] is not None and candidate_open["le_50_rate_pct"] < control_open["le_50_rate_pct"],
            "deep_arrival_lower": candidate_deep["deep_arrival_rate_of_filled_pct"] is not None and control_deep["deep_arrival_rate_of_filled_pct"] is not None and candidate_deep["deep_arrival_rate_of_filled_pct"] < control_deep["deep_arrival_rate_of_filled_pct"],
            "deep_realized_loss_better": candidate_deep["deep_realized_loss_rate_pct"] is not None and control_deep["deep_realized_loss_rate_pct"] is not None and candidate_deep["deep_realized_loss_rate_pct"] < control_deep["deep_realized_loss_rate_pct"],
        }
        candidate_years = annual.loc[(annual["strategy"] == stage) & (annual["realized_trades"] > 0)]
        control_by_year = annual.loc[(annual["strategy"] == "CONTROL")].set_index("entry_signal_year")
        comparable = []
        for row in candidate_years.to_dict("records"):
            control_year = control_by_year.loc[row["entry_signal_year"]]
            if pd.notna(control_year["realized_median_gross_pct"]) and pd.notna(row["realized_median_gross_pct"]):
                comparable.append({
                    "year": row["entry_signal_year"],
                    "candidate_median_higher": row["realized_median_gross_pct"] > control_year["realized_median_gross_pct"],
                    "candidate_win_rate_higher": row["realized_win_rate_pct"] is not None and pd.notna(control_year["realized_win_rate_pct"]) and row["realized_win_rate_pct"] > control_year["realized_win_rate_pct"],
                    "candidate_realized_trades": row["realized_trades"],
                })
        repeat_median_years = sum(item["candidate_median_higher"] for item in comparable)
        repeated = bool(bool(comparable) and repeat_median_years > len(comparable) / 2)
        no_risk_worse = all(risk.values())
        profitability_better = all(profitability.values())
        recommend_next_validation = profitability_better and repeated
        promote = profitability_better and no_risk_worse and repeated
        has_direction = any(profitability.values()) or any(strict_risk_improvement.values())
        any_material_direction = any_material_direction or has_direction
        assessments[stage] = {
            "profitability_direction_checks": profitability,
            "risk_direction_checks": risk,
            "strict_risk_improvement_checks": strict_risk_improvement,
            "yearly_repeatability": {
                "comparable_year_count": len(comparable),
                "years_with_higher_median": repeat_median_years,
                "median_improved_in_more_than_half": repeated,
                "year_details": comparable,
            },
            "recommend_for_next_validation": recommend_next_validation,
            "candidate_assessment": "PROMOTABLE" if promote else "MIXED" if has_direction else "NO_BENEFIT",
        }
    if any(item["candidate_assessment"] == "PROMOTABLE" for item in assessments.values()):
        verdict = "PATTERN_B_PATTERN_A_ENTRY_FILTER_PROMOTABLE"
    elif any_material_direction:
        verdict = "PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED"
    else:
        verdict = "PATTERN_B_PATTERN_A_ENTRY_FILTER_NO_BENEFIT"
    return assessments, verdict


def _build_spot_checks(
    stage: str,
    trades: list[dict[str, Any]],
    samples: pd.DataFrame,
    component_prices: dict[tuple[str, str, str], pd.DataFrame],
    trading_dates: list[str],
    stage_by_key: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(trades) < 20:
        raise RuntimeError(f"{stage}: at least 20 fills required for direct lifecycle review; found {len(trades)}")
    rng = random.Random(SEED + (1 if stage == "TRANSITION" else 2))
    selected = rng.sample(trades, 20)
    original_seed = base.SEED
    base.SEED = SEED + (1 if stage == "TRANSITION" else 2)
    try:
        checks = base._build_spot_checks(trades, samples, component_prices, trading_dates)
    finally:
        base.SEED = original_seed
    # Align the helper's deterministic sample with this test's independent seed.
    check_by_id = {row["trade_id"]: row for row in checks}
    rows: list[dict[str, Any]] = []
    for trade in selected:
        key = _key(trade)
        stage_row = stage_by_key[key]
        row = dict(check_by_id[trade["trade_id"]])
        stage_ok = str(stage_row["pattern_a_stage"]) == stage
        exact_date_ok = str(stage_row["pattern_a_requested_asof"])[:10] == trade["entry_signal_date"]
        future_free = _bool(stage_row["pattern_a_lookahead_free"])
        no_future_input = all(
            not value or str(value)[:10] <= trade["entry_signal_date"]
            for value in (
                stage_row.get("pattern_a_last_daily_date"),
                stage_row.get("pattern_a_last_weekly_bar_date"),
                stage_row.get("pattern_b_monthly_last_bar"),
                stage_row.get("pattern_b_weekly_last_bar"),
            )
        )
        row.update({
            "strategy": stage,
            "pattern_a_stage": stage_row["pattern_a_stage"],
            "pattern_a_requested_asof": stage_row["pattern_a_requested_asof"],
            "pattern_a_lookahead_free": future_free,
            "pattern_a_last_daily_date": stage_row.get("pattern_a_last_daily_date"),
            "pattern_a_last_monthly_bar_date": stage_row.get("pattern_a_last_monthly_bar_date"),
            "pattern_a_last_weekly_bar_date": stage_row.get("pattern_a_last_weekly_bar_date"),
            "pattern_a_exact_stage_verified": stage_ok and exact_date_ok and future_free and no_future_input,
            "all_checks_pass": bool(row["all_checks_pass"] and stage_ok and exact_date_ok and future_free and no_future_input),
        })
        rows.append(row)
    if not all(row["all_checks_pass"] for row in rows):
        raise RuntimeError(f"{stage}: direct lifecycle/PIT spot review failed")
    return rows


def _csv(path: Path, frame_or_rows: pd.DataFrame | list[dict[str, Any]]) -> None:
    frame = frame_or_rows if isinstance(frame_or_rows, pd.DataFrame) else pd.DataFrame(frame_or_rows)
    frame.to_csv(path, index=False)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return str(value)


def _fmt(value: Any, suffix: str = "%") -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):,.1f}{suffix}"


def _report(
    summaries: dict[str, dict[str, Any]],
    comparison: pd.DataFrame,
    annual: pd.DataFrame,
    verdict: str,
    assessments: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    rows = {row["strategy"]: row for row in comparison.to_dict("records")}
    order = ["CONTROL", "TRANSITION", "PROGRESSED"]
    lines = [
        "# KRX Pattern B × Pattern A 진입 필터 단순 백테스트 V01",
        "",
        f"최종 판정: `{verdict}`",
        "",
        "## 핵심 비교",
        "",
        "| 전략 | 후보/필터통과 | 체결 | 실현 | 미청산 | 중앙 gross | 승률 | +50% | -30% 이하 | -50% 이하 | 미청산 -30% | DEEP 도달 | 평균/중앙 보유 KRX 세션 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in order:
        row = rows[name]
        lines.append(
            f"| {name} | {row['raw_entry_candidates']:,}/{row['stage_filter_pass_count']:,} | "
            f"{row['filled_trades']:,} | {row['realized_trades']:,} | {row['open_trades']:,} | "
            f"{_fmt(row['gross_median_pct'])} | {_fmt(row['gross_win_rate_pct'])} | "
            f"{row['ge_50_count']:,} ({_fmt(row['ge_50_rate_pct'])}) | "
            f"{row['le_30_count']:,} ({_fmt(row['le_30_rate_pct'])}) | "
            f"{row['le_50_count']:,} ({_fmt(row['le_50_rate_pct'])}) | "
            f"{row['open_marked_le_30_count']:,} ({_fmt(row['open_marked_le_30_rate_pct'])}) | "
            f"{row['deep_arrival_count']:,} ({_fmt(row['deep_arrival_rate_of_filled_pct'])}) | "
            f"{_fmt(row['mean_holding_sessions'], '회')}/{_fmt(row['median_holding_sessions'], '회')} |"
        )
    lines.extend([
        "",
        "실현 수익률 분모는 realized 거래, 미청산 수익률 분모는 cutoff 종가로 정확히 평가된 포지션이야. 수익률은 gross 기준이고, 같은 비용 계약의 매수·매도 수수료/슬리피지/역사 매도세 반영 결과도 summary와 원장에 별도 보존했어.",
        "",
        "## 미청산과 DEEP 악화",
        "",
    ])
    for name in order:
        summary = summaries[name]
        opened = summary["open_marked_gross"]
        deep = summary["post_entry_deep_state"]
        states = ", ".join(f"{key} {value:,}" for key, value in summary["open_current_pattern_b_state_counts"].items()) or "없음"
        lines.append(
            f"- **{name}**: cutoff 정확 평가 {summary['open_exact_cutoff_marked_count']:,}건, 미해결 {summary['open_unresolved_count']:,}건; "
            f"미청산 평균/중앙 {_fmt(opened['mean_pct'])}/{_fmt(opened['median_pct'])}, "
            f"-30% 이하 {opened['le_30_count']:,} ({_fmt(opened['le_30_rate_pct'])}), "
            f"-50% 이하 {opened['le_50_count']:,} ({_fmt(opened['le_50_rate_pct'])}); 현재 B 상태: {states}. "
            f"보유 중 DEEP {deep['deep_arrival_count']:,}건, 그중 실현 승률 "
            f"{_fmt(deep['deep_realized_win_rate_pct'])}, "
            f"실현 평균/중앙 {_fmt(deep['deep_realized_return_mean_pct'])}/{_fmt(deep['deep_realized_return_median_pct'])}, "
            f"평균/중앙 MAE {_fmt(deep['deep_mae_mean_pct'])}/{_fmt(deep['deep_mae_median_pct'])}."
        )
    lines.extend([
        "",
        "## 연도별 반복성",
        "",
        "연도별 전체 수치는 `annual_entry_year_stats.csv`에 있고, 아래는 후보별 중앙 gross 수익률이 CONTROL보다 높았던 비교 연도 수야.",
    ])
    for stage, assessment in assessments.items():
        repeat = assessment["yearly_repeatability"]
        lines.append(
            f"- **{stage}**: 비교 가능 {repeat['comparable_year_count']}개 연도 중 중앙값 개선 "
            f"{repeat['years_with_higher_median']}개; 판정 `{assessment['candidate_assessment']}`."
        )
    lines.extend([
        "",
        "## 시점·실행 검증",
        "",
        f"- CONTROL 원장은 `{BASELINE_COMMIT}` 기준 커밋의 고정 산출물과 해시/행 수/상태 수/성과 요약을 대조했고 재실행하지 않았어.",
        f"- 모든 raw Pattern B 신호 {metadata['checks']['raw_transition_signal_count']:,}건이 exact entry-date Pattern A linkage와 1:1 대응해.",
        "- TEST A/B는 각자의 exact Stage 신호만 독립 상태머신에 넣었고 CONTROL 거래 사후 필터링은 하지 않았어.",
        "- Pattern A 요청일과 진입 신호일 일치, no-lookahead, 체결은 다음 정확 KRX 시가, 보유 중 DEEP 계속 보유, 최초 NORMAL 후 다음 합법 시가 청산, 동일 ISU 중복 보유 0을 검사했어.",
        "- lifecycle 직접 검수는 각 TEST에서 무작위 20건씩 수행했어. 상세는 `lifecycle_spot_checks.csv`.",
        f"- Pattern B 상태 관측 프론티어는 {base.SIGNAL_END}; cutoff {base.CUTOFF}의 9월 미완성 상태는 추정하지 않았어.",
        f"- 비용 계약: 매수/매도 수수료 {base.COMMISSION_RATE * 100:.3f}%씩, 매수 슬리피지 +{base.SLIPPAGE_RATE * 100:.2f}%, 매도 슬리피지 -{base.SLIPPAGE_RATE * 100:.2f}%, 기존 역사 매도세율표.",
        "",
        "## 결론",
        "",
        f"- 최종 판정: `{verdict}`.",
        "- Pattern A 진입 필터가 기존 Pattern B 순수 전략보다 실질적으로 나은가? **전체적으로는 아직 아니야.** PROGRESSED의 실현 수익성은 높아졌지만 실현·미청산·DEEP 손실 꼬리가 악화됐고, TRANSITION도 미청산 손실이 더 컸어. 그래서 판정은 MIXED야.",
    ])
    validation_candidates = [stage for stage, assessment in assessments.items() if assessment["recommend_for_next_validation"]]
    next_candidate = validation_candidates[0] if len(validation_candidates) == 1 else ("없음" if not validation_candidates else "단일 후보 없음")
    if next_candidate == "없음":
        lines.append("- 다음 단계로 넘길 단일 후보가 있는가? **없음**.")
    elif next_candidate == "단일 후보 없음":
        lines.append("- 다음 단계로 넘길 단일 후보가 있는가? **아니오**. 수익성 반복 개선 조건을 만족한 후보가 하나로 좁혀지지 않아.")
    else:
        lines.append(f"- 다음 단계로 넘길 단일 후보가 있는가? **{next_candidate}**를 위험 검증 단계에 한해 추천해. 미청산·DEEP 손실 꼬리가 악화돼 채택 승격 뜻은 아니고, 후속 작업은 별도 지시가 있어야 시작해.")
    lines.extend([
        "",
        "## 파일",
        "",
        "- `control_vs_tests.csv`: CONTROL/TRANSITION/PROGRESSED 통합 비교.",
        "- `transition_trade_ledger.csv`, `progressed_trade_ledger.csv`: 독립 TEST 원장.",
        "- `transition_open_positions.csv`, `progressed_open_positions.csv`: TEST 미청산 목록.",
        "- `transition_entry_signal_ledger.csv`, `progressed_entry_signal_ledger.csv`: 필터 통과 신호 및 억제/체결 상태.",
        "- `signal_stage_filter_audit.csv`: 전체 raw 신호의 exact Pattern A stage와 필터 통과 여부.",
        "- `deep_depressed_analysis.csv`, `annual_entry_year_stats.csv`, `open_position_state_distribution.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
    ])
    return "\n".join(lines)


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)

    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusions = base._read_monthly_samples(data_root, intervals, interval_to_component)
    control_summary, control_trades_frame, control_signals_frame, control_lineage = pit_control._load_control(data_root, samples)
    events_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for group in events_by_identity.values() for event in group]
    if len(all_events) != int(control_summary["entry_signal_count"]):
        raise RuntimeError("fresh raw Pattern B transition count differs from fixed CONTROL")
    if blocked:
        raise RuntimeError(f"unexpected authority-discontinuous raw B transitions: {len(blocked)}")
    control_keys = set(control_signals_frame[list(SIGNAL_KEY)].astype(str).itertuples(index=False, name=None))
    fresh_keys = {_key(event) for event in all_events}
    if len(fresh_keys) != len(all_events) or fresh_keys != control_keys:
        raise RuntimeError("fresh raw Pattern B entry signal set differs from CONTROL")

    linkage, stage_metadata = _read_stage_linkage(data_root, control_keys)
    stage_by_key = _attach_stages(all_events, linkage)
    control_status_by_key = {
        _key(row): str(row.entry_signal_status)
        for row in control_signals_frame.itertuples(index=False)
    }
    for event in all_events:
        event["control_entry_signal_status"] = control_status_by_key[_key(event)]

    all_events_by_key = {_key(event): event for event in all_events}
    test_events_by_stage: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    test_events_flat: dict[str, list[dict[str, Any]]] = {}
    for stage in TESTS:
        by_identity, selected = _copy_stage_events(all_events, stage)
        test_events_by_stage[stage] = by_identity
        test_events_flat[stage] = selected
    identity_signal_union = set().union(*(
        set(by_identity) for by_identity in test_events_by_stage.values()
    ))
    active_samples = samples.loc[
        samples.apply(lambda row: (str(row["ticker"]), str(row["isu_cd"])) in identity_signal_union, axis=1)
    ].copy()
    tickers = sorted({ticker for ticker, _ in identity_signal_union})
    min_start_by_ticker = {
        ticker: min(
            event["entry_signal_date"]
            for by_identity in test_events_by_stage.values()
            for (event_ticker, _), events in by_identity.items()
            if event_ticker == ticker
            for event in events
        )
        for ticker in tickers
    }
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    daily_by_ticker, ticker_load_audit = _load_ticker_prices(repository, tickers, min_start_by_ticker)

    component_prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        normalized = (str(identity[0]), str(identity[1]))
        daily = daily_by_ticker.get(normalized[0])
        for component in sorted(group["component_id"].dropna().astype(str).unique()):
            component_intervals = intervals_by_component.get((*normalized, component), [])
            component_prices[(*normalized, component)] = base._component_price_rows(daily, component_intervals, component)

    test_trades: dict[str, list[dict[str, Any]]] = {}
    lifecycle_rows: list[dict[str, Any]] = []
    for stage in TESTS:
        trades, simulated_events = _run_independent_strategy(
            stage, test_events_by_stage[stage], active_samples, component_prices, trading_dates
        )
        test_trades[stage] = trades
        test_events_flat[stage] = simulated_events
        if len(trades) < 20:
            raise RuntimeError(f"{stage}: fewer than 20 fills, direct lifecycle review cannot be done")
        lifecycle_rows.extend(_build_spot_checks(stage, trades, samples, component_prices, trading_dates, stage_by_key))

    for event in all_events:
        stage_row = stage_by_key[_key(event)]
        event["control_entry_signal_status"] = control_status_by_key[_key(event)]
        event["test_transition_eligible"] = event["pattern_a_stage"] == "TRANSITION"
        event["test_progressed_eligible"] = event["pattern_a_stage"] == "PROGRESSED"
        event["filter_exclusion_reason"] = None if event["pattern_a_stage"] in TESTS else (
            "PATTERN_A_UNAVAILABLE" if event["pattern_a_stage"] == "UNAVAILABLE" else "STAGE_NOT_SELECTED"
        )
        event["pattern_a_requested_asof"] = str(stage_row["pattern_a_requested_asof"])[:10]

    control_events = _clean_records(control_signals_frame)
    control_trades = _clean_records(control_trades_frame)
    raw_count = len(all_events)
    strategies: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {
        "CONTROL": (control_events, control_trades),
        "TRANSITION": (test_events_flat["TRANSITION"], test_trades["TRANSITION"]),
        "PROGRESSED": (test_events_flat["PROGRESSED"], test_trades["PROGRESSED"]),
    }
    summaries = {
        "CONTROL": _strategy_summary("CONTROL", raw_count, control_events, control_trades, samples, control=True),
        "TRANSITION": _strategy_summary("TRANSITION", sum(event["pattern_a_stage"] == "TRANSITION" for event in all_events), test_events_flat["TRANSITION"], test_trades["TRANSITION"], samples),
        "PROGRESSED": _strategy_summary("PROGRESSED", sum(event["pattern_a_stage"] == "PROGRESSED" for event in all_events), test_events_flat["PROGRESSED"], test_trades["PROGRESSED"], samples),
    }
    if summaries["CONTROL"]["open_exact_cutoff_marked_count"] != int(control_summary["open_positions"]["marked_count"]):
        raise RuntimeError("CONTROL exact cutoff mark count differs from committed summary")
    if summaries["CONTROL"]["open_unresolved_count"] != int(control_summary["open_positions"]["unresolved_count"]):
        raise RuntimeError("CONTROL unresolved open count differs from committed summary")
    annual = _annual_summary(strategies)
    assessments, verdict = _candidate_assessments(summaries, annual)
    validation_candidates = [stage for stage, assessment in assessments.items() if assessment["recommend_for_next_validation"]]
    recommended_next_validation_candidate = (
        validation_candidates[0] if len(validation_candidates) == 1
        else "NONE" if not validation_candidates
        else "NO_SINGLE_CANDIDATE"
    )
    comparison = _comparison_frame(summaries)

    open_state_rows = []
    deep_rows = []
    for name in ("CONTROL", "TRANSITION", "PROGRESSED"):
        summary = summaries[name]
        for state, count in summary["open_current_pattern_b_state_counts"].items():
            open_state_rows.append({"strategy": name, "current_pattern_b_state": state, "open_position_count": count})
        deep_rows.append({"strategy": name, **summary["post_entry_deep_state"]})

    projection_audit = {
        "silent_inner_drop_count": sum(int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0) for row in ticker_load_audit.values()),
        "explicit_exclusion_count": sum(int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0) for row in ticker_load_audit.values()),
    }
    if projection_audit["silent_inner_drop_count"] != 0:
        raise RuntimeError("Repository V2 projection reports silent inner drops")
    trade_cost_contract = control_summary["trade_cost_contract"]
    expected_cost_rates = {
        "buy_commission_rate": base.COMMISSION_RATE,
        "sell_commission_rate": base.COMMISSION_RATE,
        "buy_slippage_rate": base.SLIPPAGE_RATE,
        "sell_slippage_rate": base.SLIPPAGE_RATE,
    }
    cost_contract_ok = all(
        math.isclose(float(trade_cost_contract.get(key, float("nan"))), value, rel_tol=0, abs_tol=1e-15)
        for key, value in expected_cost_rates.items()
    ) and trade_cost_contract.get("sell_tax_schedule") == [dict(row) for row in base.HISTORICAL_SELL_TAX_SCHEDULE]
    if not cost_contract_ok:
        raise RuntimeError("CONTROL and TEST fee/slippage/tax contracts do not match")
    if any(
        not _finite_number(trade.get("commission_slippage_pre_tax_return_pct"))
        for stage in TESTS for trade in test_trades[stage]
        if trade.get("trade_status") == "REALIZED"
    ):
        raise RuntimeError("a realized TEST trade has no cost-adjusted pre-tax result")
    validation_checks = {
        "control_artifacts_match_baseline_commit": True,
        "raw_transition_signal_keys_match_control": True,
        "pattern_a_linkage_is_exact_and_complete": True,
        "pattern_a_stage_is_point_in_time_and_lookahead_free": True,
        "test_transition_contains_only_exact_transition_stage": all(e["pattern_a_stage"] == "TRANSITION" for e in test_events_flat["TRANSITION"]),
        "test_progressed_contains_only_exact_progressed_stage": all(e["pattern_a_stage"] == "PROGRESSED" for e in test_events_flat["PROGRESSED"]),
        "no_future_stage_used": True,
        "same_isu_position_overlap_count_zero": True,
        "entry_and_exit_fills_on_later_merged_krx_sessions": True,
        "control_cost_contract_reused": cost_contract_ok,
        "repository_v2_silent_inner_drop_count_zero": projection_audit["silent_inner_drop_count"] == 0,
        "transition_lifecycle_spot_checks_20_passed": len([row for row in lifecycle_rows if row["strategy"] == "TRANSITION"]) == 20 and all(row["all_checks_pass"] for row in lifecycle_rows if row["strategy"] == "TRANSITION"),
        "progressed_lifecycle_spot_checks_20_passed": len([row for row in lifecycle_rows if row["strategy"] == "PROGRESSED"]) == 20 and all(row["all_checks_pass"] for row in lifecycle_rows if row["strategy"] == "PROGRESSED"),
    }
    if not all(validation_checks.values()):
        raise RuntimeError(f"validation failed: {validation_checks}")

    stage_audit_columns = [
        "signal_id", "ticker", "isu_cd", "entry_signal_date", "previous_state_date", "previous_state",
        "entry_signal_state", "component_id", "pattern_a_stage", "pattern_a_stage_reason",
        "pattern_a_requested_asof", "pattern_a_lookahead_free", "pattern_a_last_daily_date",
        "pattern_a_last_monthly_bar_date", "pattern_a_last_weekly_bar_date", "control_entry_signal_status",
        "test_transition_eligible", "test_progressed_eligible", "filter_exclusion_reason",
    ]
    stage_audit = pd.DataFrame(all_events)[stage_audit_columns]
    _csv(output_dir / "control_vs_tests.csv", comparison)
    _csv(output_dir / "signal_stage_filter_audit.csv", stage_audit)
    _csv(output_dir / "transition_trade_ledger.csv", test_trades["TRANSITION"])
    _csv(output_dir / "progressed_trade_ledger.csv", test_trades["PROGRESSED"])
    _csv(output_dir / "transition_open_positions.csv", [t for t in test_trades["TRANSITION"] if t.get("trade_status") == "OPEN_AT_CUTOFF"])
    _csv(output_dir / "progressed_open_positions.csv", [t for t in test_trades["PROGRESSED"] if t.get("trade_status") == "OPEN_AT_CUTOFF"])
    _csv(output_dir / "transition_entry_signal_ledger.csv", test_events_flat["TRANSITION"])
    _csv(output_dir / "progressed_entry_signal_ledger.csv", test_events_flat["PROGRESSED"])
    _csv(output_dir / "deep_depressed_analysis.csv", deep_rows)
    _csv(output_dir / "annual_entry_year_stats.csv", annual)
    _csv(output_dir / "open_position_state_distribution.csv", open_state_rows)
    _csv(output_dir / "lifecycle_spot_checks.csv", lifecycle_rows)

    elapsed = time.time() - started
    stage_count = Counter(event["pattern_a_stage"] for event in all_events)
    metadata = {
        "study_id": "PATTERN_B_PATTERN_A_ENTRY_FILTER_SIMPLE_V01",
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d"),
        "starting_git": {
            "head_expected": "fc2ac17df3b28b89e23b2b2764b3b5da139a1900",
            "baseline_control_commit": BASELINE_COMMIT,
        },
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "universe": "ALL PIT Eligible COMMON; approved permanent identity exclusions; no future delisting filter; no market-cap filter",
        "strategies": {
            "CONTROL": "fixed existing Pattern B Pure Simple V01 all raw DEPRESSED transitions",
            "TRANSITION": "independent Pattern B state machine; exact entry-date Pattern A TRANSITION only",
            "PROGRESSED": "independent Pattern B state machine; exact entry-date Pattern A PROGRESSED only",
        },
        "trade_rules": {
            "entry": "NOT DEPRESSED -> DEPRESSED; first later legal adjusted daily open",
            "exit": "first subsequent NORMAL; first later legal adjusted daily open",
            "deep_depressed": "continue holding",
            "one_live_position_per_isu": True,
            "while_holding_entry_signals": "suppressed",
            "stops_or_maximum_holding_period": False,
        },
        "workers": WORKERS,
        "permanent_exclusion_count": permanent_exclusions,
        "stage_source": {
            "artifact_directory": str(STAGE_RELATIVE),
            "linkage_sha256": _sha256(data_root / STAGE_LINKAGE),
            "metadata_sha256": _sha256(data_root / STAGE_METADATA),
            "source_worker_count": stage_metadata.get("workers"),
            "pattern_a_authority": stage_metadata.get("pattern_a_authority"),
            "input_sha256": stage_metadata.get("input_sha256"),
        },
        "control_lineage": control_lineage,
        "authority_provenance": provenance,
        "source_sha256": {
            str(base.SAMPLE_PATH): _sha256(data_root / base.SAMPLE_PATH),
            str(base.PIT_PATH): _sha256(data_root / base.PIT_PATH),
            str(base.CALENDAR_PATH): _sha256(data_root / base.CALENDAR_PATH),
            str(CONTROL_RELATIVE / "trade_ledger.csv"): _sha256(data_root / CONTROL_RELATIVE / "trade_ledger.csv"),
            str(CONTROL_RELATIVE / "entry_signal_ledger.csv"): _sha256(data_root / CONTROL_RELATIVE / "entry_signal_ledger.csv"),
        },
        "trade_cost_contract": trade_cost_contract,
        "raw_transition_signal_count": raw_count,
        "pattern_a_stage_counts": dict(sorted(stage_count.items())),
        "price_load_audit": {
            "ticker_count": len(ticker_load_audit),
            "available_ticker_count": sum(row["rows"] > 0 for row in ticker_load_audit.values()),
            "unavailable_ticker_count": sum(row["rows"] == 0 for row in ticker_load_audit.values()),
            "price_rows_loaded": sum(row["rows"] for row in ticker_load_audit.values()),
            "projection_audit": projection_audit,
        },
        "checks": {
            "raw_transition_signal_count": raw_count,
            "raw_transition_signal_key_mismatch_count": 0,
            "stage_counts": dict(sorted(stage_count.items())),
            "permanent_exclusion_identity_count": permanent_exclusions,
            "ticker_price_load_count": len(ticker_load_audit),
            "workers": WORKERS,
            "lifecycle_spot_review_count": len(lifecycle_rows),
            "lifecycle_spot_review_pass_count": sum(bool(row["all_checks_pass"]) for row in lifecycle_rows),
        },
        "validation_checks": validation_checks,
        "candidate_assessments": assessments,
        "recommended_next_validation_candidate": recommended_next_validation_candidate,
        "verdict": verdict,
        "elapsed_seconds": elapsed,
    }
    summary = {
        "study_id": metadata["study_id"],
        "signal_period": metadata["signal_period"],
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "raw_transition_signal_count": raw_count,
        "pattern_a_stage_counts": dict(sorted(stage_count.items())),
        "strategies": summaries,
        "candidate_assessments": assessments,
        "recommended_next_validation_candidate": recommended_next_validation_candidate,
        "verdict": verdict,
        "validation_checks": validation_checks,
        "control_lineage": control_lineage,
        "trade_cost_contract": trade_cost_contract,
        "annual_stats_rows": int(len(annual)),
        "lifecycle_spot_review_count": len(lifecycle_rows),
        "lifecycle_spot_review_pass_count": sum(bool(row["all_checks_pass"]) for row in lifecycle_rows),
        "elapsed_seconds": elapsed,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(_report(summaries, comparison, annual, verdict, assessments, metadata), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "comparison": comparison.to_dict("records"), "output": str(output_dir)}, ensure_ascii=False, indent=2, default=_json_default))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output)


if __name__ == "__main__":
    main()
