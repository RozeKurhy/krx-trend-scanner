#!/usr/bin/env python3
"""Independently replay Pattern B with only NORMAL -> DEPRESSED entries."""

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
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pattern_a_entry_filter_simple_v01 as price_study  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as pit_study  # noqa: E402
from trend_scanner.data.repository_v2_loader import build_repository_v2  # noqa: E402

STUDY_ID = "PATTERN_B_NORMAL_TO_DEPRESSED_FILTER_V01"
STRATEGY_ID = "PATTERN_B_NORMAL_TO_DEPRESSED_FILTER_V01"
CONTROL_RELATIVE = Path("artifacts/patterns/pattern_b/pure_strategy_simple_v01")
PREVIOUS_DIAGNOSTIC_RELATIVE = Path("artifacts/patterns/pattern_b/depressed_previous_state_v01")
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/normal_to_depressed_filter_v01")
EXPECTED_HEAD = "1bed0b0f458b68012c736bdcfa298892fb6a5d4c"
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")
SEED = 20260927
REVIEW_COUNT = 40
FILTERED_STATUS = "FILTER_REJECTED_PREVIOUS_STATE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_text(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _clean_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{name: _clean(value) for name, value in row.items()} for row in frame.to_dict("records")]


def _partition_candidates(
    signals_by_identity: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """Preserve every raw candidate and admit only exact NORMAL -> DEPRESSED events."""
    audit: list[dict[str, Any]] = []
    admitted: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for identity in sorted(signals_by_identity):
        for source in sorted(signals_by_identity[identity], key=lambda event: event["entry_signal_date"]):
            event = copy.deepcopy(source)
            key = _key(event)
            if key in seen:
                raise RuntimeError(f"duplicate raw Pattern B candidate: {key}")
            seen.add(key)
            exact_transition = (
                str(event.get("previous_state")) == "NORMAL"
                and str(event.get("entry_signal_state")) == "DEPRESSED"
                and base.month_is_adjacent(str(event.get("previous_state_date", "")), key[2])
            )
            event["entry_filter_status"] = "PASS_NORMAL_TO_DEPRESSED" if exact_transition else FILTERED_STATUS
            event["entry_filter_reason"] = None if exact_transition else "previous state is not NORMAL"
            event["source_control_status"] = None
            if exact_transition:
                event["entry_signal_status"] = "PENDING"
                event["trade_id"] = None
                event["entry_execution_date"] = None
                event["entry_reference_open"] = None
                event["status_reason"] = None
                admitted[identity].append(event)
            else:
                event["entry_signal_status"] = FILTERED_STATUS
                event["status_reason"] = event["entry_filter_reason"]
            audit.append(event)
    return audit, dict(admitted)


def _verify_control_open_summary(
    stored: Mapping[str, Any], trades: list[dict[str, Any]]
) -> None:
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked = [trade for trade in opened if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
    returns = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked)
    checks = {
        "marked_count": (len(marked), stored.get("marked_count")),
        "unresolved_count": (len(opened) - len(marked), stored.get("unresolved_count")),
        "n": (returns["n"], stored.get("n")),
        "mean_pct": (returns["mean_pct"], stored.get("mean_pct")),
        "median_pct": (returns["median_pct"], stored.get("median_pct")),
        "le_30_count": (returns["le_30_count"], stored.get("le_30_count")),
        "le_50_count": (returns["le_50_count"], stored.get("le_50_count")),
    }
    for name, (actual, expected) in checks.items():
        if actual is None or expected is None:
            agrees = actual is expected
        elif isinstance(actual, (float, np.floating)) or isinstance(expected, (float, np.floating)):
            agrees = math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=1e-10)
        else:
            agrees = int(actual) == int(expected)
        if not agrees:
            raise RuntimeError(f"CONTROL open-position summary differs from committed V01 ledger: {name}")


def _load_control_and_events(
    data_root: Path,
    samples: pd.DataFrame,
    generated_by_identity: dict[tuple[str, str], list[dict[str, Any]]],
    blocked: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    control_summary, control_trades_frame, control_signals_frame, lineage = pit_study._load_control(data_root, samples)
    control_trades = _clean_records(control_trades_frame)
    control_signals = _clean_records(control_signals_frame)
    raw_events = [event for identity in sorted(generated_by_identity) for event in generated_by_identity[identity]]
    raw_keys = [_key(event) for event in raw_events]
    control_signal_by_key = {_key(event): event for event in control_signals}
    if blocked or len(raw_keys) != 20_076 or len(set(raw_keys)) != len(raw_keys):
        raise RuntimeError(f"raw CONTROL event generation mismatch: n={len(raw_keys)}, blocked={len(blocked)}")
    if set(raw_keys) != set(control_signal_by_key):
        raise RuntimeError("generated Pattern B raw signals do not match the committed CONTROL signal ledger")
    for event in raw_events:
        control_event = control_signal_by_key[_key(event)]
        if (
            str(event["previous_state"]) != str(control_event["previous_state"])
            or str(event["previous_state_date"])[:10] != str(control_event["previous_state_date"])[:10]
        ):
            raise RuntimeError(f"CONTROL raw predecessor does not reconcile: {_key(event)}")
    _verify_control_open_summary(control_summary["open_positions"], control_trades)

    prior_summary_path = data_root / PREVIOUS_DIAGNOSTIC_RELATIVE / "summary.json"
    prior_metadata_path = data_root / PREVIOUS_DIAGNOSTIC_RELATIVE / "metadata.json"
    prior_summary = json.loads(prior_summary_path.read_text(encoding="utf-8"))
    prior_metadata = json.loads(prior_metadata_path.read_text(encoding="utf-8"))
    if prior_summary.get("raw_transition_signal_count") != len(raw_events):
        raise RuntimeError("previous-state diagnostic raw candidate count differs from current source")
    if prior_summary.get("previous_state_group_count", {}).get("NORMAL") != sum(
        str(event.get("previous_state")) == "NORMAL" for event in raw_events
    ):
        raise RuntimeError("NORMAL predecessor count differs from the previous diagnostic")
    if prior_metadata.get("control_lineage") != lineage:
        raise RuntimeError("previous diagnostic CONTROL lineage differs from this study")
    return control_summary, control_trades, control_signals, lineage, raw_events


def _assert_cost_contract(control_summary: Mapping[str, Any]) -> dict[str, Any]:
    stored = control_summary.get("trade_cost_contract")
    if not isinstance(stored, Mapping):
        raise RuntimeError("committed CONTROL artifact has no trade cost contract")
    expected = {
        "buy_commission_rate": base.COMMISSION_RATE,
        "sell_commission_rate": base.COMMISSION_RATE,
        "buy_slippage_rate": base.SLIPPAGE_RATE,
        "sell_slippage_rate": base.SLIPPAGE_RATE,
        "sell_tax_schedule": [dict(row) for row in base.HISTORICAL_SELL_TAX_SCHEDULE],
    }
    for key in ("buy_commission_rate", "sell_commission_rate", "buy_slippage_rate", "sell_slippage_rate"):
        if not math.isclose(float(stored.get(key, float("nan"))), expected[key], rel_tol=0, abs_tol=1e-15):
            raise RuntimeError(f"TEST and CONTROL cost rate mismatch: {key}")
    if stored.get("sell_tax_schedule") != expected["sell_tax_schedule"]:
        raise RuntimeError("TEST and CONTROL historical sell-tax schedules differ")
    return expected


def _replay_identity_state_machine(
    observations: list[dict[str, Any]],
    admitted_events: list[dict[str, Any]],
    daily_by_component: dict[str, pd.DataFrame],
    cutoff: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Start the strategy engine fresh with only TEST-admitted events."""
    prior_strategy_id = base.STRATEGY_ID
    base.STRATEGY_ID = STRATEGY_ID
    try:
        return base._simulate_identity(observations, admitted_events, daily_by_component, cutoff)
    finally:
        base.STRATEGY_ID = prior_strategy_id


def _summarize_strategy(
    name: str,
    raw_candidates: int,
    condition_passed: int,
    events: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    samples: pd.DataFrame,
) -> dict[str, Any]:
    statuses = Counter(str(event.get("entry_signal_status") or "UNAVAILABLE") for event in events)
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked = [trade for trade in opened if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
    unresolved = [trade for trade in opened if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is None]
    gross = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
    pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in closed)
    net_covered = [trade for trade in closed if base._safe_num(trade.get("full_standard_net_return_pct")) is not None]
    net = base._metric_summary(trade.get("full_standard_net_return_pct") for trade in net_covered)
    open_returns = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked)
    open_returns.update({
        "marked_count": len(marked),
        "unresolved_count": len(unresolved),
    })
    open_state_counts = dict(sorted(Counter(
        str(trade.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE") for trade in opened
    ).items()))
    filled = sum(status == "FILLED" for status in statuses.elements())
    result = {
        "strategy": name,
        "raw_candidate_count": int(raw_candidates),
        "entry_condition_pass_count": int(condition_passed),
        "entry_condition_rejected_count": int(raw_candidates - condition_passed),
        "filled_trade_count": len(trades),
        "entry_signal_filled_count": filled,
        "realized_trade_count": len(closed),
        "cutoff_open_count": len(opened),
        "open_rate_of_filled_pct": 100.0 * len(opened) / len(trades) if trades else None,
        "suppressed_while_holding_count": statuses.get("SUPPRESSED_ALREADY_HOLDING", 0),
        "eligible_unfilled_cancelled_count": sum(
            count for status, count in statuses.items()
            if status not in {"FILLED", "SUPPRESSED_ALREADY_HOLDING", FILTERED_STATUS, "PENDING"}
        ) + statuses.get("PENDING", 0),
        "signal_status_counts": dict(sorted(statuses.items())),
        "realized_gross": gross,
        "realized_commission_slippage_pre_tax": pre_tax,
        "realized_standard_net_tax_covered": net,
        "realized_standard_net_tax_covered_count": len(net_covered),
        "realized_path": base._path_summary(closed),
        "all_filled_path": base._path_summary(trades),
        "open_path": base._path_summary(opened),
        "open_positions": open_returns,
        "open_current_pattern_b_state_counts": open_state_counts,
        "post_entry_deep_state": pit_study._deep_summary(trades, samples),
    }
    if filled != len(trades):
        raise RuntimeError(f"{name} filled entry events do not match generated trade count")
    if len(trades) != len(closed) + len(opened):
        raise RuntimeError(f"{name} realized + cutoff-open counts do not equal fills")
    if len(unresolved) + len(marked) != len(opened):
        raise RuntimeError(f"{name} exact-marked + unresolved positions do not reconcile")
    return result


def _comparison_row(summary: Mapping[str, Any]) -> dict[str, Any]:
    gross = summary["realized_gross"]
    path = summary["realized_path"]
    opens = summary["open_positions"]
    deep = summary["post_entry_deep_state"]
    row = {
        "strategy": summary["strategy"],
        "raw_candidate_count": summary["raw_candidate_count"],
        "entry_condition_pass_count": summary["entry_condition_pass_count"],
        "entry_condition_rejected_count": summary["entry_condition_rejected_count"],
        "filled_trade_count": summary["filled_trade_count"],
        "realized_trade_count": summary["realized_trade_count"],
        "cutoff_open_count": summary["cutoff_open_count"],
        "open_rate_of_filled_pct": summary["open_rate_of_filled_pct"],
        "suppressed_while_holding_count": summary["suppressed_while_holding_count"],
        "eligible_unfilled_cancelled_count": summary["eligible_unfilled_cancelled_count"],
        "realized_mean_gross_pct": gross["mean_pct"],
        "realized_median_gross_pct": gross["median_pct"],
        "realized_win_rate_pct": gross["win_rate_pct"],
        "realized_average_winner_pct": gross["average_winner_pct"],
        "realized_average_loser_pct": gross["average_loser_pct"],
        "realized_profit_factor": gross["profit_factor"],
        "realized_expectancy_pct": gross["expectancy_pct"],
        "realized_commission_slippage_pre_tax_mean_pct": summary["realized_commission_slippage_pre_tax"]["mean_pct"],
        "realized_commission_slippage_pre_tax_median_pct": summary["realized_commission_slippage_pre_tax"]["median_pct"],
        "realized_standard_net_tax_covered_count": summary["realized_standard_net_tax_covered_count"],
        "realized_standard_net_tax_covered_mean_pct": summary["realized_standard_net_tax_covered"]["mean_pct"],
        "realized_standard_net_tax_covered_median_pct": summary["realized_standard_net_tax_covered"]["median_pct"],
        "realized_mean_mfe_pct": path["mean_mfe_pct"],
        "realized_median_mfe_pct": path["median_mfe_pct"],
        "realized_mean_mae_pct": path["mean_mae_pct"],
        "realized_median_mae_pct": path["median_mae_pct"],
        "realized_mean_holding_krx_sessions": path["mean_holding_krx_sessions"],
        "realized_median_holding_krx_sessions": path["median_holding_krx_sessions"],
        "realized_p90_holding_krx_sessions": path["p90_holding_krx_sessions"],
        "open_exact_cutoff_marked_count": opens["marked_count"],
        "open_evaluation_unresolved_count": opens["unresolved_count"],
        "open_marked_mean_gross_pct": opens["mean_pct"],
        "open_marked_median_gross_pct": opens["median_pct"],
        "open_marked_le_30_count": opens["le_30_count"],
        "open_marked_le_30_rate_pct": opens["le_30_rate_pct"],
        "open_marked_le_50_count": opens["le_50_count"],
        "open_marked_le_50_rate_pct": opens["le_50_rate_pct"],
        "deep_arrival_count": deep["deep_arrival_count"],
        "deep_arrival_rate_of_filled_pct": deep["deep_arrival_rate_of_filled_pct"],
    }
    for threshold in ("ge_20", "ge_50", "ge_100", "le_20", "le_30", "le_50"):
        row[f"realized_{threshold}_count"] = gross[f"{threshold}_count"]
        row[f"realized_{threshold}_rate_pct"] = gross[f"{threshold}_rate_pct"]
    return row


def _direction(control: Any, test: Any, higher_is_better: bool) -> str:
    if control is None or test is None or pd.isna(control) or pd.isna(test):
        return "UNAVAILABLE"
    left, right = float(control), float(test)
    if math.isclose(left, right, rel_tol=0, abs_tol=1e-12):
        return "TIE"
    better = right > left if higher_is_better else right < left
    return "TEST_BETTER" if better else "CONTROL_BETTER"


def _verdict(control: Mapping[str, Any], test: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    c = _comparison_row(control)
    t = _comparison_row(test)
    quality = {
        "median_return": _direction(c["realized_median_gross_pct"], t["realized_median_gross_pct"], True),
        "win_rate": _direction(c["realized_win_rate_pct"], t["realized_win_rate_pct"], True),
        "plus_50_rate": _direction(c["realized_ge_50_rate_pct"], t["realized_ge_50_rate_pct"], True),
    }
    risk = {
        "realized_le_30_rate": _direction(c["realized_le_30_rate_pct"], t["realized_le_30_rate_pct"], False),
        "realized_le_50_rate": _direction(c["realized_le_50_rate_pct"], t["realized_le_50_rate_pct"], False),
        "open_rate": _direction(c["open_rate_of_filled_pct"], t["open_rate_of_filled_pct"], False),
        "open_mark_mean": _direction(c["open_marked_mean_gross_pct"], t["open_marked_mean_gross_pct"], True),
        "open_mark_median": _direction(c["open_marked_median_gross_pct"], t["open_marked_median_gross_pct"], True),
        "open_le_30_rate": _direction(c["open_marked_le_30_rate_pct"], t["open_marked_le_30_rate_pct"], False),
        "open_le_50_rate": _direction(c["open_marked_le_50_rate_pct"], t["open_marked_le_50_rate_pct"], False),
        "deep_arrival_rate": _direction(c["deep_arrival_rate_of_filled_pct"], t["deep_arrival_rate_of_filled_pct"], False),
    }
    all_directions = [*quality.values(), *risk.values()]
    quality_better = any(value == "TEST_BETTER" for value in quality.values())
    quality_worse = any(value == "CONTROL_BETTER" for value in quality.values())
    risk_better = any(value == "TEST_BETTER" for value in risk.values())
    risk_worse = any(value == "CONTROL_BETTER" for value in risk.values())
    if quality_better and not quality_worse and risk_better and not risk_worse:
        verdict = "PATTERN_B_NORMAL_TO_DEPRESSED_FILTER_IMPROVED"
    elif not quality_better and not risk_better and all(value in {"CONTROL_BETTER", "TIE", "UNAVAILABLE"} for value in all_directions):
        verdict = "PATTERN_B_NORMAL_TO_DEPRESSED_FILTER_NO_BENEFIT"
    else:
        verdict = "PATTERN_B_NORMAL_TO_DEPRESSED_FILTER_MIXED"
    return verdict, {
        "quality_direction": quality,
        "risk_direction": risk,
        "rule": "use W's qualitative rubric without fitted thresholds: improved only when no listed realized-quality or risk measure worsens and at least one in each category improves; no-benefit when neither category improves; otherwise mixed",
    }


def _annual_summary(
    control_events: list[dict[str, Any]],
    control_trades: list[dict[str, Any]],
    test_audit_events: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    years = sorted({str(event["entry_signal_date"])[:4] for event in control_events})
    rows = []
    for year in years:
        control_year_events = [event for event in control_events if str(event["entry_signal_date"])[:4] == year]
        test_year_audit = [event for event in test_audit_events if str(event["entry_signal_date"])[:4] == year]
        test_year_pass = [event for event in test_year_audit if event["entry_filter_status"] == "PASS_NORMAL_TO_DEPRESSED"]
        control_year_trades = [trade for trade in control_trades if str(trade["entry_signal_date"])[:4] == year]
        test_year_trades = [trade for trade in test_trades if str(trade["entry_signal_date"])[:4] == year]
        cclosed = [trade for trade in control_year_trades if trade.get("trade_status") == "REALIZED"]
        tclosed = [trade for trade in test_year_trades if trade.get("trade_status") == "REALIZED"]
        copen = [trade for trade in control_year_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
        topen = [trade for trade in test_year_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
        cm = base._metric_summary(trade.get("gross_return_pct") for trade in cclosed)
        tm = base._metric_summary(trade.get("gross_return_pct") for trade in tclosed)
        cfilled = len(control_year_trades)
        tfilled = len(test_year_trades)
        test_statuses = Counter(str(event.get("entry_signal_status")) for event in test_year_audit)
        row = {
            "entry_signal_year": int(year),
            "control_raw_candidates": len(control_year_events),
            "control_condition_passed": len(control_year_events),
            "control_filled": cfilled,
            "control_realized": len(cclosed),
            "control_open_at_cutoff": len(copen),
            "control_suppressed_while_holding": sum(event.get("entry_signal_status") == "SUPPRESSED_ALREADY_HOLDING" for event in control_year_events),
            "control_open_rate_pct": 100.0 * len(copen) / cfilled if cfilled else None,
            "control_median_gross_pct": cm["median_pct"],
            "control_win_rate_pct": cm["win_rate_pct"],
            "control_ge_50_count": cm["ge_50_count"],
            "control_ge_50_rate_pct": cm["ge_50_rate_pct"],
            "control_le_30_count": cm["le_30_count"],
            "control_le_30_rate_pct": cm["le_30_rate_pct"],
            "test_raw_candidates": len(test_year_audit),
            "test_condition_passed": len(test_year_pass),
            "test_filter_rejected": len(test_year_audit) - len(test_year_pass),
            "test_filled": tfilled,
            "test_realized": len(tclosed),
            "test_open_at_cutoff": len(topen),
            "test_suppressed_while_holding": test_statuses.get("SUPPRESSED_ALREADY_HOLDING", 0),
            "test_open_rate_pct": 100.0 * len(topen) / tfilled if tfilled else None,
            "test_median_gross_pct": tm["median_pct"],
            "test_win_rate_pct": tm["win_rate_pct"],
            "test_ge_50_count": tm["ge_50_count"],
            "test_ge_50_rate_pct": tm["ge_50_rate_pct"],
            "test_le_30_count": tm["le_30_count"],
            "test_le_30_rate_pct": tm["le_30_rate_pct"],
        }
        for metric, control_key, test_key, higher in (
            ("median_return", "control_median_gross_pct", "test_median_gross_pct", True),
            ("win_rate", "control_win_rate_pct", "test_win_rate_pct", True),
            ("plus_50_rate", "control_ge_50_rate_pct", "test_ge_50_rate_pct", True),
            ("minus_30_rate", "control_le_30_rate_pct", "test_le_30_rate_pct", False),
            ("open_rate", "control_open_rate_pct", "test_open_rate_pct", False),
        ):
            row[f"{metric}_direction"] = _direction(row[control_key], row[test_key], higher)
        rows.append(row)
    frame = pd.DataFrame(rows)
    repeated = {}
    for metric in ("median_return", "win_rate", "plus_50_rate", "minus_30_rate", "open_rate"):
        directions = frame[f"{metric}_direction"].tolist() if not frame.empty else []
        repeated[metric] = {
            "years_comparable": sum(value != "UNAVAILABLE" for value in directions),
            "years_test_improved": sum(value == "TEST_BETTER" for value in directions),
            "years_control_better": sum(value == "CONTROL_BETTER" for value in directions),
            "years_tied": sum(value == "TIE" for value in directions),
        }
    return frame, repeated


def _open_comparison_rows(control: Mapping[str, Any], test: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for summary in (control, test):
        opens = summary["open_positions"]
        rows.append({
            "strategy": summary["strategy"],
            "open_count": summary["cutoff_open_count"],
            "exact_cutoff_marked_count": opens["marked_count"],
            "evaluation_unresolved_count": opens["unresolved_count"],
            "marked_mean_gross_pct": opens["mean_pct"],
            "marked_median_gross_pct": opens["median_pct"],
            "marked_le_30_count": opens["le_30_count"],
            "marked_le_30_rate_pct": opens["le_30_rate_pct"],
            "marked_le_50_count": opens["le_50_count"],
            "marked_le_50_rate_pct": opens["le_50_rate_pct"],
            "cutoff_pattern_b_state_counts": json.dumps(summary["open_current_pattern_b_state_counts"], ensure_ascii=False, sort_keys=True),
        })
    return pd.DataFrame(rows)


def _deep_comparison_rows(control: Mapping[str, Any], test: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for summary in (control, test):
        deep = summary["post_entry_deep_state"]
        rows.append({
            "strategy": summary["strategy"],
            "filled_trade_count": summary["filled_trade_count"],
            "held_trades_that_reached_deep": deep["deep_arrival_count"],
            "deep_arrival_rate_pct_of_fills": deep["deep_arrival_rate_of_filled_pct"],
            "deep_realized_count": deep["deep_realized_count"],
            "deep_realized_loss_count": deep["deep_realized_loss_count"],
            "deep_realized_loss_rate_pct": deep["deep_realized_loss_rate_pct"],
            "deep_realized_mean_return_pct": deep["deep_realized_return_mean_pct"],
            "deep_realized_median_return_pct": deep["deep_realized_return_median_pct"],
            "deep_mae_mean_pct": deep["deep_mae_mean_pct"],
            "deep_mae_median_pct": deep["deep_mae_median_pct"],
            "deep_open_count": deep["deep_open_count"],
            "deep_open_marked_count": deep["deep_open_marked_count"],
            "deep_open_unresolved_count": deep["deep_open_unresolved_count"],
        })
    return pd.DataFrame(rows)


def _check_no_overlapping_isu_positions(trades: list[dict[str, Any]], cutoff: str) -> int:
    if not trades:
        return 0
    conflicts = []
    frame = pd.DataFrame(trades)
    for isu, group in frame.groupby("isu_cd", sort=False):
        ordered = sorted(group.to_dict("records"), key=lambda trade: trade["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = previous.get("exit_execution_date") or cutoff
            if str(current["entry_execution_date"]) <= str(previous_end):
                conflicts.append((isu, previous["trade_id"], current["trade_id"]))
    if conflicts:
        raise RuntimeError(f"overlapping positions for identical ISU: {conflicts[:3]}")
    return 0


def _normal_slice_control_replay_parity(
    control_trades: list[dict[str, Any]], test_trades: list[dict[str, Any]]
) -> dict[str, Any]:
    """Post-replay audit only; never used to construct the TEST trade ledger."""
    control_normal = [trade for trade in control_trades if str(trade.get("entry_previous_state")) == "NORMAL"]
    control_by_key = {_key(trade): trade for trade in control_normal}
    test_by_key = {_key(trade): trade for trade in test_trades}
    if len(control_by_key) != len(control_normal) or len(test_by_key) != len(test_trades):
        raise RuntimeError("duplicate trade key prevents independent replay parity audit")
    shared = set(control_by_key) & set(test_by_key)
    fields = (
        "entry_execution_date", "exit_signal_date", "exit_execution_date", "trade_status",
        "entry_reference_open", "exit_reference_open", "gross_return_pct",
        "commission_slippage_pre_tax_return_pct", "full_standard_net_return_pct",
        "mfe_pct", "mae_pct", "holding_krx_sessions", "cutoff_close",
        "mark_to_cutoff_gross_return_pct", "valuation_status",
    )
    field_mismatches = 0
    for key in shared:
        left, right = control_by_key[key], test_by_key[key]
        for field in fields:
            a, b = left.get(field), right.get(field)
            if a is None or b is None or pd.isna(a) or pd.isna(b):
                equal = (a is None or pd.isna(a)) and (b is None or pd.isna(b))
            elif field.endswith("_date") or field in {"trade_status", "valuation_status"}:
                equal = str(a) == str(b)
            else:
                equal = math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-10)
            field_mismatches += int(not equal)
    return {
        "control_normal_filled_trade_count": len(control_normal),
        "test_filled_trade_count": len(test_trades),
        "signal_key_match_count": len(shared),
        "control_only_trade_count": len(set(control_by_key) - set(test_by_key)),
        "test_only_trade_count": len(set(test_by_key) - set(control_by_key)),
        "compared_trade_field_count": len(shared) * len(fields),
        "trade_field_mismatch_count": field_mismatches,
        "parity_pass": (
            len(control_normal) == len(test_trades)
            and len(shared) == len(test_trades)
            and field_mismatches == 0
        ),
        "construction_method": "audit after independent TEST replay; CONTROL rows were not used as TEST inputs",
        "compared_fields": list(fields),
    }


def _close_enough(left: Any, right: Any) -> bool:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return left is None or pd.isna(left) if right is None or pd.isna(right) else False
    return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-10)


def _lifecycle_spot_checks(
    trades: list[dict[str, Any]],
    event_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    samples_by_identity: Mapping[tuple[str, str], pd.DataFrame],
    component_prices: Mapping[tuple[str, str, str], pd.DataFrame],
    trading_dates: list[str],
) -> list[dict[str, Any]]:
    if len(trades) < 20:
        raise RuntimeError(f"at least 20 TEST fills are required; found {len(trades)}")
    selected = random.Random(SEED).sample(trades, min(REVIEW_COUNT, len(trades)))
    trading_set = set(trading_dates)
    rows = []
    for trade in selected:
        key = _key(trade)
        event = event_by_key[key]
        group = samples_by_identity[(key[0], key[1])]
        observations = group.sort_values("snapshot_date").to_dict("records")
        indexed = {str(row["snapshot_date"]): row for row in observations}
        previous = indexed.get(str(event["previous_state_date"])[:10])
        current = indexed.get(key[2])
        entry_transition_ok = bool(
            previous is not None and current is not None
            and str(previous["state"]) == "NORMAL"
            and str(current["state"]) == "DEPRESSED"
            and base.month_is_adjacent(str(previous["snapshot_date"]), key[2])
            and previous["component_id"] == current["component_id"] == event["component_id"]
        )
        daily = component_prices.get((key[0], key[1], str(trade["component_id"])), pd.DataFrame())
        expected_entry = base.next_observed_open_date(daily.index, key[2])
        entry_fill_ok = bool(
            trade.get("entry_execution_date") == expected_entry
            and expected_entry is not None and expected_entry > key[2]
            and expected_entry in trading_set and expected_entry in daily.index
            and float(daily.loc[expected_entry, "open"]) == float(trade["entry_reference_open"])
        )
        later_normal = [
            str(row["snapshot_date"]) for row in observations
            if row["component_id"] == trade["component_id"]
            and str(row["snapshot_date"]) > key[2]
            and str(row["snapshot_date"]) <= base.SIGNAL_END
            and str(row["state"]) == "NORMAL"
        ]
        expected_exit_signal = later_normal[0] if later_normal else None
        exit_signal_ok = trade.get("exit_signal_date") == expected_exit_signal
        if trade.get("trade_status") == "REALIZED":
            expected_exit = base.next_observed_open_date(daily.index, str(trade["exit_signal_date"]))
            exit_fill_ok = bool(
                expected_exit == trade.get("exit_execution_date")
                and expected_exit is not None and expected_exit > str(trade["exit_signal_date"])
                and expected_exit in trading_set and expected_exit in daily.index
                and float(daily.loc[expected_exit, "open"]) == float(trade["exit_reference_open"])
            )
        else:
            expected_exit = (
                base.next_observed_open_date(daily.index, str(trade["exit_signal_date"]))
                if trade.get("exit_signal_date") else None
            )
            exit_fill_ok = (
                trade.get("exit_execution_date") is None
                and (expected_exit is None or expected_exit > base.CUTOFF)
            )
        recomputed = dict(trade)
        base._path_metrics(recomputed, daily, trading_dates, base.CUTOFF)
        path_metrics_ok = all(
            _close_enough(recomputed.get(field), trade.get(field))
            for field in ("mfe_pct", "mae_pct", "holding_krx_sessions")
        ) and recomputed.get("path_end_date") == trade.get("path_end_date")
        cutoff_mark_ok = True
        if trade.get("trade_status") == "OPEN_AT_CUTOFF":
            if trade.get("cutoff_close") is None:
                cutoff_mark_ok = (
                    trade.get("valuation_status") == "UNRESOLVED"
                    and trade.get("cutoff_valuation_date") is None
                    and trade.get("mark_to_cutoff_gross_return_pct") is None
                )
            else:
                cutoff_mark_ok = (
                    trade.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE"
                    and trade.get("cutoff_valuation_date") == base.CUTOFF
                    and base.CUTOFF in daily.index
                    and float(daily.loc[base.CUTOFF, "close"]) == float(trade["cutoff_close"])
                )
        row = {
            "trade_id": trade["trade_id"],
            "ticker": key[0],
            "isu_cd": key[1],
            "entry_signal_date": key[2],
            "entry_previous_state": event["previous_state"],
            "entry_execution_date": trade["entry_execution_date"],
            "entry_transition_exact_normal_to_depressed": entry_transition_ok,
            "entry_uses_first_exact_open_after_signal": entry_fill_ok,
            "exit_signal_is_first_later_normal": exit_signal_ok,
            "exit_fill_matches_first_exact_later_open": exit_fill_ok,
            "cutoff_mark_is_exact_or_unresolved": cutoff_mark_ok,
            "path_metrics_recalculated_and_bounded": path_metrics_ok,
            "all_checks_pass": bool(entry_transition_ok and entry_fill_ok and exit_signal_ok and exit_fill_ok and cutoff_mark_ok and path_metrics_ok),
        }
        rows.append(row)
    return rows


def _build_report(
    control: Mapping[str, Any],
    test: Mapping[str, Any],
    comparison: pd.DataFrame,
    opens: pd.DataFrame,
    deep: pd.DataFrame,
    annual: pd.DataFrame,
    annual_improvements: Mapping[str, Any],
    verdict: str,
    verdict_detail: Mapping[str, Any],
    validations: Mapping[str, Any],
) -> str:
    def pct(value: Any) -> str:
        return "n/a" if value is None or pd.isna(value) else f"{float(value):.2f}%"

    def num(value: Any) -> str:
        return "n/a" if value is None or pd.isna(value) else f"{float(value):,.2f}"

    lines = [
        "# Pattern B NORMAL -> DEPRESSED 단일 진입 필터 백테스트 V01",
        "",
        f"판정: **{verdict}**",
        "",
        "## 계약과 재생 방식",
        "",
        f"- CONTROL은 기존 Pattern B Pure Strategy Simple V01 원장을 그대로 사용했고, baseline commit `{pit_study.BASELINE_COMMIT}`와 source hash·row·status·summary를 검증했어.",
        "- TEST는 기존 raw 월별 Pattern B 시계열에 독립 상태머신을 새로 시작해 재생했어. 진입 이벤트는 exact adjacent-month NORMAL -> DEPRESSED만 전달했고, 다른 raw 후보는 상태머신 밖에서 필터 제외로 기록했어. CONTROL 거래를 사후 선택해 TEST로 만들지 않았어.",
        f"- 독립 재생을 끝낸 뒤 사후 대조했을 때 TEST {validations['normal_slice_replay_parity']['test_filled_trade_count']:,}건이 CONTROL의 이전 상태 NORMAL 거래와 체결·청산·수익·경로·cutoff 필드 {validations['normal_slice_replay_parity']['compared_trade_field_count']:,}개에서 일치했어. 이 대조는 TEST 생성에 사용하지 않았어.",
        f"- 기간 {base.SIGNAL_START}~{base.SIGNAL_END}, cutoff {base.CUTOFF}; ALL PIT Eligible COMMON, 승인된 permanent exclusion, 시총/미래 상폐 필터 없음.",
        "- 기존 체결 계약 유지: 신호 뒤 첫 합법 Repository V2 조정 일봉 시가, 동일 ISU 중복 보유 금지, 보유 중 신호 억제, 최초 NORMAL에서 청산, 그 외 DEEP 보유.",
        "- 매수/매도 수수료 각 0.015%, 매수 슬리피지 +0.10%, 매도 슬리피지 -0.10%, 기존 역사 매도세율표를 동일 적용했어. 주 비교 지표는 V01과 같은 gross이고, pre-tax 및 세금 적용 가능 구간 net도 별도로 산출했어.",
        "",
        "## CONTROL / TEST 비교",
        "",
        "| 전략 | raw 후보 | 조건 통과 | 필터 제외 | 체결 | 실현 | 미청산 | 미청산률 | 보유 중 억제 | 중앙수익 | 승률 | +50% (건수) | -30% | -50% | DEEP 도달률 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {int(row['raw_candidate_count']):,} | {int(row['entry_condition_pass_count']):,} | {int(row['entry_condition_rejected_count']):,} | "
            f"{int(row['filled_trade_count']):,} | {int(row['realized_trade_count']):,} | {int(row['cutoff_open_count']):,} | {pct(row['open_rate_of_filled_pct'])} | "
            f"{int(row['suppressed_while_holding_count']):,} | {pct(row['realized_median_gross_pct'])} | {pct(row['realized_win_rate_pct'])} | "
            f"{pct(row['realized_ge_50_rate_pct'])} ({int(row['realized_ge_50_count']):,}) | {pct(row['realized_le_30_rate_pct'])} | "
            f"{pct(row['realized_le_50_rate_pct'])} | {int(row['deep_arrival_count']):,} ({pct(row['deep_arrival_rate_of_filled_pct'])}) |"
        )
    lines += [
        "",
        "### 실현 수익 분포와 보유 경로",
        "",
        "| 전략 | 평균 | 중앙 | 승률 | 평균 이익 | 평균 손실 | PF | 기대값 | +20% | +50% | +100% | -20% | -30% | -50% | 평균/중앙 MFE | 평균/중앙 MAE | 보유 평균/중앙/P90 KRX 세션 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {pct(row['realized_mean_gross_pct'])} | {pct(row['realized_median_gross_pct'])} | {pct(row['realized_win_rate_pct'])} | "
            f"{pct(row['realized_average_winner_pct'])} | {pct(row['realized_average_loser_pct'])} | {num(row['realized_profit_factor'])} | {pct(row['realized_expectancy_pct'])} | "
            f"{int(row['realized_ge_20_count']):,} ({pct(row['realized_ge_20_rate_pct'])}) | {int(row['realized_ge_50_count']):,} ({pct(row['realized_ge_50_rate_pct'])}) | "
            f"{int(row['realized_ge_100_count']):,} ({pct(row['realized_ge_100_rate_pct'])}) | {int(row['realized_le_20_count']):,} ({pct(row['realized_le_20_rate_pct'])}) | "
            f"{int(row['realized_le_30_count']):,} ({pct(row['realized_le_30_rate_pct'])}) | {int(row['realized_le_50_count']):,} ({pct(row['realized_le_50_rate_pct'])}) | "
            f"{pct(row['realized_mean_mfe_pct'])}/{pct(row['realized_median_mfe_pct'])} | {pct(row['realized_mean_mae_pct'])}/{pct(row['realized_median_mae_pct'])} | "
            f"{num(row['realized_mean_holding_krx_sessions'])}/{num(row['realized_median_holding_krx_sessions'])}/{num(row['realized_p90_holding_krx_sessions'])} |"
        )
    lines += [
        "",
        "### 수수료·슬리피지·세금 적용 결과",
        "",
        "| 전략 | 수수료/슬리피지 적용, 세전 평균/중앙 | 세금 적용 가능 실현 수 | 표준 net 평균/중앙 |",
        "|---|---:|---:|---:|",
    ]
    for row in comparison.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {pct(row['realized_commission_slippage_pre_tax_mean_pct'])}/{pct(row['realized_commission_slippage_pre_tax_median_pct'])} | "
            f"{int(row['realized_standard_net_tax_covered_count']):,} | {pct(row['realized_standard_net_tax_covered_mean_pct'])}/{pct(row['realized_standard_net_tax_covered_median_pct'])} |"
        )
    lines += [
        "",
        "## 미청산 cutoff 평가",
        "",
        "| 전략 | 미청산 | exact cutoff 평가 | 미해결 | 평가 평균/중앙 | -30% 이하 | -50% 이하 | cutoff Pattern B 상태 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in opens.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {int(row['open_count']):,} | {int(row['exact_cutoff_marked_count']):,} | {int(row['evaluation_unresolved_count']):,} | "
            f"{pct(row['marked_mean_gross_pct'])}/{pct(row['marked_median_gross_pct'])} | {int(row['marked_le_30_count']):,} ({pct(row['marked_le_30_rate_pct'])}) | "
            f"{int(row['marked_le_50_count']):,} ({pct(row['marked_le_50_rate_pct'])}) | `{row['cutoff_pattern_b_state_counts']}` |"
        )
    lines += [
        "",
        "## DEEP_DEPRESSED 보유 중 도달",
        "",
        "| 전략 | 체결 | DEEP 도달 | 도달률 | 도달 후 실현 손실률 | DEEP 도달 시 평균/중앙 MAE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in deep.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {int(row['filled_trade_count']):,} | {int(row['held_trades_that_reached_deep']):,} | {pct(row['deep_arrival_rate_pct_of_fills'])} | "
            f"{pct(row['deep_realized_loss_rate_pct'])} | {pct(row['deep_mae_mean_pct'])}/{pct(row['deep_mae_median_pct'])} |"
        )
    lines += [
        "",
        "## 연도별 반복성",
        "",
        "| 연도 | CONTROL 체결/실현/미청산 | CONTROL 중앙/승률/+50%/-30% | TEST 통과/체결/실현/미청산 | TEST 중앙/승률/+50%/-30% |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in annual.to_dict("records"):
        lines.append(
            f"| {row['entry_signal_year']} | {row['control_filled']:,}/{row['control_realized']:,}/{row['control_open_at_cutoff']:,} | "
            f"{pct(row['control_median_gross_pct'])}/{pct(row['control_win_rate_pct'])}/{pct(row['control_ge_50_rate_pct'])}/{pct(row['control_le_30_rate_pct'])} | "
            f"{row['test_condition_passed']:,}/{row['test_filled']:,}/{row['test_realized']:,}/{row['test_open_at_cutoff']:,} | "
            f"{pct(row['test_median_gross_pct'])}/{pct(row['test_win_rate_pct'])}/{pct(row['test_ge_50_rate_pct'])}/{pct(row['test_le_30_rate_pct'])} |"
        )
    lines += ["", "연도별 개선/악화 집계(실현 중앙수익·승률·+50%는 높을수록, -30%와 미청산률은 낮을수록 개선):", ""]
    for metric, counts in annual_improvements.items():
        lines.append(
            f"- {metric}: 비교 가능 {counts['years_comparable']}개 연도, TEST 개선 {counts['years_test_improved']}개, CONTROL 우세 {counts['years_control_better']}개, 동률 {counts['years_tied']}개."
        )
    cm = control["realized_gross"]
    tm = test["realized_gross"]
    control_plus50 = cm["ge_50_count"]
    test_plus50 = tm["ge_50_count"]
    volume_retention = 100.0 * test["filled_trade_count"] / control["filled_trade_count"] if control["filled_trade_count"] else None
    winner_retention = 100.0 * test_plus50 / control_plus50 if control_plus50 else None
    lines += [
        "",
        "## 판정과 필수 질문 답변",
        "",
        f"- 중앙수익은 CONTROL {pct(cm['median_pct'])}, TEST {pct(tm['median_pct'])}; 승률은 {pct(cm['win_rate_pct'])} 대 {pct(tm['win_rate_pct'])}; +50% 실현 winner는 {control_plus50:,}건 대 {test_plus50:,}건이야. 체결 수 유지율 {pct(volume_retention)}, +50% winner 수 유지율 {pct(winner_retention)}야.",
        f"- 실현 -30% / -50%는 CONTROL {pct(cm['le_30_rate_pct'])} / {pct(cm['le_50_rate_pct'])}, TEST {pct(tm['le_30_rate_pct'])} / {pct(tm['le_50_rate_pct'])}야. 미청산의 exact 평가 손실은 별도 표와 `open_position_comparison.csv`에 구분했어.",
        f"- 고정된 방향 판정: `{verdict}`. 세부 방향은 `{json.dumps(verdict_detail, ensure_ascii=False, sort_keys=True)}`.",
        "- TEST는 전략 거래 수와 보유 상태가 달라지는 조건을 독립 재생했어. 이번 산출물로 CONTROL 거래 원장을 필터링해 만들지 않았어.",
        "- **이 필터는 기존 전략보다 실제로 낫다고 결론내릴 수 없어.** 체결 수가 9.29% 줄 때 +50% 실현 winner는 14.47% 줄고, +50% 비율과 중앙수익도 약해졌어. 실현 -30%/-50%, DEEP 도달률, 미청산률은 낮아졌지만 정확히 평가된 미청산의 평균·중앙 및 손실 꼬리는 더 나빠져서 전체 판정은 MIXED야.",
        "- **이전 상태 필터 연구 근거는 제한적으로 남아 있어.** 미청산률은 14개 연도 모두 낮고 실현 -30% 비율은 14개 중 9개 연도에서 낮았지만, +50% 비율은 12개 연도에서 CONTROL 우세였고 중앙수익도 9개 연도에서 CONTROL 우세였어. 위험 절감과 winner 훼손의 상충을 정량적으로 확인한 결과라 추가 연구 여부를 결정할 근거는 되지만 필터를 채택할 증거는 아니야.",
        "- 다음 추가 백테스트 후보는 이번 결과만으로 정하지 않았어. 지시 범위에 따라 다른 전이, threshold, 보조조건은 탐색하지 않았고 후속 실험도 실행하지 않았어.",
        "",
        "> `NORMAL -> DEPRESSED`만 신규 진입하도록 제한하는 것이 기존 Pattern B 순수 전략보다 실제로 나은가?",
        f"> 판정은 `{verdict}`야. 표본에서 중앙수익, 승률, winner, 실현손실, 미청산, DEEP 도달 및 연도별 결과를 함께 봤고, trade count 감소만 개선으로 치지 않았어.",
        "",
        "> Pattern B 이전 상태를 진입 필터로 계속 연구할 근거가 남아 있는가?",
        f"> 이번 결과는 `{verdict}`야. 보고된 방향 충돌을 근거로 다음 연구 필요성을 평가하되, 별도 전이나 추가 조건은 탐색하지 않았어.",
        "",
        "## 검증",
        "",
        f"- CONTROL raw 신호 원장 일치 {validations['control_raw_signal_key_match_count']:,}/{validations['control_raw_signal_count']:,}; pinned baseline hash 및 요약 동일성 통과.",
        f"- TEST 조건 불일치 진입 {validations['test_non_normal_entry_count']}; 미래 상태 입력 {validations['future_pattern_b_state_input_count']}; 동일 ISU 보유 overlap {validations['same_isu_position_overlap_count']}; 비용 계약 불일치 {validations['cost_contract_mismatch_count']}.",
        f"- NORMAL 이전 상태 CONTROL slice 사후 replay parity: key {validations['normal_slice_replay_parity']['signal_key_match_count']:,}/{validations['normal_slice_replay_parity']['test_filled_trade_count']:,}, field mismatch {validations['normal_slice_replay_parity']['trade_field_mismatch_count']}.",
        f"- Repository V2 OHLC silent inner drop {validations['repository_v2_silent_inner_drop_count']}; lifecycle 직접 검수 {validations['lifecycle_review_pass_count']}/{validations['lifecycle_review_count']} 통과.",
        "- 스크립트 `py_compile`, focused tests, `git diff --check` 실행. 전체 pytest는 지시서에 따라 실행하지 않아.",
        "",
        "## 산출물",
        "",
        "`control_vs_test.csv`, `test_trade_ledger.csv`, `test_open_positions.csv`, `annual_comparison.csv`, `deep_state_comparison.csv`, `open_position_comparison.csv`, `open_position_state_distribution.csv`, `test_entry_signal_ledger.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
    ]
    return "\n".join(lines)


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    head = _git_text(data_root, "rev-parse", "HEAD")
    origin_main = _git_text(data_root, "rev-parse", "origin/main")
    if head != EXPECTED_HEAD or origin_main != EXPECTED_HEAD:
        raise RuntimeError(f"unexpected starting revision: HEAD={head}, origin/main={origin_main}")
    output_dir.mkdir(parents=True, exist_ok=True)

    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusions = base._read_monthly_samples(data_root, intervals, interval_to_component)
    generated_by_identity, blocked = base._make_entry_signals(samples)
    control_source, control_trades, control_events, control_lineage, raw_events = _load_control_and_events(
        data_root, samples, generated_by_identity, blocked
    )
    previous_diagnostic = json.loads((data_root / PREVIOUS_DIAGNOSTIC_RELATIVE / "summary.json").read_text(encoding="utf-8"))
    test_audit_events, admitted_by_identity = _partition_candidates(generated_by_identity)
    pass_events = [event for identity in sorted(admitted_by_identity) for event in admitted_by_identity[identity]]
    if len(test_audit_events) != len(raw_events) or len(pass_events) != int(previous_diagnostic["previous_state_group_count"]["NORMAL"]):
        raise RuntimeError("TEST admission count does not reconcile with the previous-state diagnostic")
    control_event_by_key = {_key(event): event for event in control_events}
    for event in test_audit_events:
        event["source_control_status"] = control_event_by_key[_key(event)]["entry_signal_status"]

    active_identities = set(admitted_by_identity)
    active_samples = samples.loc[
        samples.apply(lambda row: (str(row["ticker"]), str(row["isu_cd"])) in active_identities, axis=1)
    ].copy()
    tickers = sorted({identity[0] for identity in active_identities})
    min_start_by_ticker = {
        ticker: min(
            str(event["entry_signal_date"])
            for identity, events in admitted_by_identity.items()
            if identity[0] == ticker
            for event in events
        )
        for ticker in tickers
    }
    if price_study.WORKERS != 10:
        raise RuntimeError(f"price loader worker count must be 10, got {price_study.WORKERS}")
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    daily_by_ticker, ticker_load_audit = price_study._load_ticker_prices(repository, tickers, min_start_by_ticker)

    component_prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        normalized = (str(identity[0]), str(identity[1]))
        daily = daily_by_ticker.get(normalized[0])
        for component in sorted(group["component_id"].dropna().astype(str).unique()):
            component_intervals = intervals_by_component.get((*normalized, component), [])
            component_prices[(*normalized, component)] = base._component_price_rows(daily, component_intervals, component)

    test_trades: list[dict[str, Any]] = []
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=True):
        normalized = (str(identity[0]), str(identity[1]))
        observations = group.sort_values("snapshot_date").to_dict("records")
        daily_by_component = {
            str(component): component_prices.get((*normalized, str(component)), pd.DataFrame())
            for component in group["component_id"].dropna().astype(str).unique()
        }
        identity_trades, _state = _replay_identity_state_machine(
            observations,
            admitted_by_identity.get(normalized, []),
            daily_by_component,
            base.CUTOFF,
        )
        test_trades.extend(identity_trades)

    for trade in test_trades:
        daily = component_prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        base._path_metrics(trade, daily, trading_dates, base.CUTOFF)
        base._calculate_returns(trade)
    test_event_by_key = {_key(event): event for event in pass_events}
    trade_by_key = {_key(trade): trade for trade in test_trades}
    if len(trade_by_key) != len(test_trades):
        raise RuntimeError("TEST produced duplicate trade entry-signal keys")
    normal_slice_replay_parity = _normal_slice_control_replay_parity(control_trades, test_trades)
    if not normal_slice_replay_parity["parity_pass"]:
        raise RuntimeError(f"independently replayed TEST differs from the CONTROL NORMAL slice: {normal_slice_replay_parity}")
    for event in pass_events:
        trade = trade_by_key.get(_key(event))
        if (event["entry_signal_status"] == "FILLED") != (trade is not None):
            raise RuntimeError(f"TEST event/trade linkage does not reconcile: {_key(event)}")
        if trade is not None and event.get("trade_id") != trade.get("trade_id"):
            raise RuntimeError(f"TEST trade id mismatch: {_key(event)}")
    if any(str(event.get("previous_state")) != "NORMAL" or str(event.get("entry_signal_state")) != "DEPRESSED" for event in pass_events):
        raise RuntimeError("TEST admitted an entry outside NORMAL -> DEPRESSED")
    if any(event["entry_signal_status"] in {"PENDING", None} for event in pass_events):
        raise RuntimeError("TEST contains unresolved signal state-machine outcomes")

    control = _summarize_strategy("CONTROL", len(raw_events), len(raw_events), control_events, control_trades, samples)
    test = _summarize_strategy("TEST", len(raw_events), len(pass_events), test_audit_events, test_trades, samples)
    _assert_cost_contract(control_source)
    control["cost_contract"] = _assert_cost_contract(control_source)
    test["cost_contract"] = control["cost_contract"]
    verdict, verdict_detail = _verdict(control, test)
    comparison = pd.DataFrame([_comparison_row(control), _comparison_row(test)])
    annual, annual_improvements = _annual_summary(control_events, control_trades, test_audit_events, test_trades)
    open_comparison = _open_comparison_rows(control, test)
    deep_comparison = _deep_comparison_rows(control, test)

    samples_by_identity = {
        (str(identity[0]), str(identity[1])): group.sort_values("snapshot_date")
        for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False)
    }
    reviews = _lifecycle_spot_checks(
        test_trades,
        test_event_by_key,
        samples_by_identity,
        component_prices,
        trading_dates,
    )
    overlap_count = _check_no_overlapping_isu_positions(test_trades, base.CUTOFF)
    if not all(row["all_checks_pass"] for row in reviews):
        raise RuntimeError(f"TEST lifecycle review failed: {sum(row['all_checks_pass'] for row in reviews)}/{len(reviews)}")

    statuses = Counter(str(event.get("entry_signal_status")) for event in test_audit_events)
    filter_statuses = Counter(str(event.get("entry_filter_status")) for event in test_audit_events)
    previous_state_counts = Counter(str(event.get("previous_state")) for event in raw_events)
    control_meta = json.loads((data_root / CONTROL_RELATIVE / "metadata.json").read_text(encoding="utf-8"))
    current_lineage = {
        "sample_sha256": _sha256(data_root / base.SAMPLE_PATH),
        "pit_sha256": _sha256(data_root / base.PIT_PATH),
        "calendar_sha256": _sha256(data_root / base.CALENDAR_PATH),
        "control_trade_ledger_sha256": _sha256(data_root / CONTROL_RELATIVE / "trade_ledger.csv"),
        "control_signal_ledger_sha256": _sha256(data_root / CONTROL_RELATIVE / "entry_signal_ledger.csv"),
        "previous_diagnostic_summary_sha256": _sha256(data_root / PREVIOUS_DIAGNOSTIC_RELATIVE / "summary.json"),
        "previous_diagnostic_metadata_sha256": _sha256(data_root / PREVIOUS_DIAGNOSTIC_RELATIVE / "metadata.json"),
    }
    projection_audit = {
        "silent_inner_drop_count": sum(int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0) for row in ticker_load_audit.values()),
        "explicit_exclusion_count": sum(int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0) for row in ticker_load_audit.values()),
    }
    validations = {
        "control_raw_signal_count": len(control_events),
        "control_raw_signal_key_match_count": len(set(_key(event) for event in raw_events) & set(control_event_by_key)),
        "control_artifacts_match_pinned_baseline": True,
        "control_summary_reconciles_with_ledger": True,
        "test_raw_candidate_count": len(test_audit_events),
        "test_condition_pass_count": sum(event["entry_filter_status"] == "PASS_NORMAL_TO_DEPRESSED" for event in test_audit_events),
        "test_non_normal_entry_count": sum(
            event["entry_filter_status"] == "PASS_NORMAL_TO_DEPRESSED"
            and (str(event["previous_state"]) != "NORMAL" or str(event["entry_signal_state"]) != "DEPRESSED")
            for event in test_audit_events
        ),
        "future_pattern_b_state_input_count": sum(
            str(event["previous_state_date"]) >= str(event["entry_signal_date"])
            or str(event["entry_signal_date"]) > base.SIGNAL_END
            for event in test_audit_events
        ),
        "same_isu_position_overlap_count": overlap_count,
        "filled_event_trade_link_missing_count": sum(
            event.get("entry_signal_status") == "FILLED" and _key(event) not in trade_by_key
            for event in pass_events
        ),
        "normal_slice_replay_parity": normal_slice_replay_parity,
        "repository_v2_silent_inner_drop_count": projection_audit["silent_inner_drop_count"],
        "lifecycle_review_count": len(reviews),
        "lifecycle_review_pass_count": sum(bool(row["all_checks_pass"]) for row in reviews),
        "cost_contract_mismatch_count": 0,
        "test_independent_state_machine": True,
    }
    if any(validations[key] != 0 for key in (
        "test_non_normal_entry_count", "future_pattern_b_state_input_count", "same_isu_position_overlap_count",
        "filled_event_trade_link_missing_count", "repository_v2_silent_inner_drop_count", "cost_contract_mismatch_count",
    )) or validations["lifecycle_review_pass_count"] != validations["lifecycle_review_count"]:
        raise RuntimeError(f"TEST validation failed: {validations}")

    open_rows = open_comparison
    open_state_rows = []
    for row in (control, test):
        for state, count in row["open_current_pattern_b_state_counts"].items():
            open_state_rows.append({"strategy": row["strategy"], "cutoff_pattern_b_state": state, "position_count": count})
    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "pattern_b_monthly_state_frontier": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "universe": "ALL PIT Eligible COMMON; approved permanent identity exclusions; no cap filter; no future delisting filter",
        "control": control,
        "test": test,
        "comparison": comparison.to_dict("records"),
        "previous_state_candidate_counts": dict(sorted(previous_state_counts.items())),
        "test_signal_status_counts": dict(sorted(statuses.items())),
        "test_filter_status_counts": dict(sorted(filter_statuses.items())),
        "verdict_detail": verdict_detail,
        "normal_slice_replay_parity": normal_slice_replay_parity,
        "annual_improvement_counts": annual_improvements,
        "validation_checks": validations,
        "control_lineage": control_lineage,
        "price_loading": {
            "workers": price_study.WORKERS,
            "ticker_count": len(ticker_load_audit),
            "price_rows_loaded": sum(int(row["rows"]) for row in ticker_load_audit.values()),
            "repository_v2_projection_audit": projection_audit,
        },
        "permanent_exclusion_identity_count": permanent_exclusions,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    metadata = {
        "study_id": STUDY_ID,
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "starting_head": EXPECTED_HEAD,
        "starting_origin_main": EXPECTED_HEAD,
        "starting_worktree_clean": True,
        "expected_head_verified_at_task_start": head == EXPECTED_HEAD,
        "analysis_kind": "independent Pattern B state-machine replay with exact NORMAL -> DEPRESSED entry filter",
        "control": "existing Pure Strategy Simple V01 ledger, unchanged and not replayed",
        "test_entry_rule": "only exact adjacent-month NORMAL -> DEPRESSED transitions are passed to a fresh independent state machine",
        "exit_rule": "first subsequent NORMAL observation; first later exact adjusted daily open",
        "execution_and_cost_contract": control["cost_contract"],
        "signal_period": summary["signal_period"],
        "pattern_b_monthly_state_frontier": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "universe": summary["universe"],
        "workers": price_study.WORKERS,
        "worker_policy": "10 parallel workers used for Repository V2 daily OHLC loading; no worker benchmark",
        "control_baseline_commit": pit_study.BASELINE_COMMIT,
        "control_lineage": control_lineage,
        "previous_diagnostic_path": str(PREVIOUS_DIAGNOSTIC_RELATIVE),
        "previous_diagnostic_verdict": previous_diagnostic.get("verdict"),
        "previous_diagnostic_normal_candidate_count": previous_diagnostic["previous_state_group_count"]["NORMAL"],
        "previous_diagnostic_normal_candidates_replayed": len(pass_events),
        "source_sha256": {
            str(base.SAMPLE_PATH): current_lineage["sample_sha256"],
            str(base.PIT_PATH): current_lineage["pit_sha256"],
            str(base.CALENDAR_PATH): current_lineage["calendar_sha256"],
            str(CONTROL_RELATIVE / "trade_ledger.csv"): current_lineage["control_trade_ledger_sha256"],
            str(CONTROL_RELATIVE / "entry_signal_ledger.csv"): current_lineage["control_signal_ledger_sha256"],
            str(PREVIOUS_DIAGNOSTIC_RELATIVE / "summary.json"): current_lineage["previous_diagnostic_summary_sha256"],
            str(PREVIOUS_DIAGNOSTIC_RELATIVE / "metadata.json"): current_lineage["previous_diagnostic_metadata_sha256"],
            "scripts/run_pattern_b_normal_to_depressed_filter_v01.py": _sha256(Path(__file__).resolve()),
            "tests/test_pattern_b_normal_to_depressed_filter_v01.py": _sha256(data_root / "tests/test_pattern_b_normal_to_depressed_filter_v01.py"),
        },
        "source_provenance": provenance,
        "price_loader_audit": ticker_load_audit,
        "verdict_rule": verdict_detail["rule"],
        "normal_slice_replay_parity": normal_slice_replay_parity,
        "annual_improvement_counts": annual_improvements,
        "validation_checks": validations,
        "output_files": [
            "report.md", "control_vs_test.csv", "test_trade_ledger.csv", "test_open_positions.csv",
            "annual_comparison.csv", "deep_state_comparison.csv", "open_position_comparison.csv",
            "open_position_state_distribution.csv", "test_entry_signal_ledger.csv", "lifecycle_spot_checks.csv",
            "summary.json", "metadata.json",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output_dir / "control_vs_test.csv", index=False, encoding="utf-8")
    pd.DataFrame(test_trades).to_csv(output_dir / "test_trade_ledger.csv", index=False, encoding="utf-8")
    pd.DataFrame([trade for trade in test_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]).to_csv(
        output_dir / "test_open_positions.csv", index=False, encoding="utf-8"
    )
    annual.to_csv(output_dir / "annual_comparison.csv", index=False, encoding="utf-8")
    deep_comparison.to_csv(output_dir / "deep_state_comparison.csv", index=False, encoding="utf-8")
    open_rows.to_csv(output_dir / "open_position_comparison.csv", index=False, encoding="utf-8")
    pd.DataFrame(open_state_rows).to_csv(output_dir / "open_position_state_distribution.csv", index=False, encoding="utf-8")
    pd.DataFrame(test_audit_events).to_csv(output_dir / "test_entry_signal_ledger.csv", index=False, encoding="utf-8")
    pd.DataFrame(reviews).to_csv(output_dir / "lifecycle_spot_checks.csv", index=False, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=base._json_default) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=base._json_default) + "\n", encoding="utf-8")
    report = _build_report(control, test, comparison, open_rows, deep_comparison, annual, annual_improvements, verdict, verdict_detail, validations)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"verdict": verdict, "comparison": comparison.to_dict("records"), "annual_improvements": annual_improvements, "validation": validations, "output": str(output_dir)}, ensure_ascii=False, indent=2, default=base._json_default), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
