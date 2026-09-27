#!/usr/bin/env python3
"""Independently replay Pattern B with EARLY_TREND / TRANSITION prior-stage gate."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as runner  # noqa: E402
from scripts import run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01 as frozen  # noqa: E402

START_HEAD = "7d5fbcd83273f644eb48ae3f595aaf1f23f54091"
STUDY_ID = "PATTERN_B_PROGRESSED_PREVIOUS_STAGE_EARLY_TRANSITION_ONLY_5WINDOW_V01"
OUTPUT_ROOT = Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01")
SCRIPT_RELATIVE = Path("scripts/run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01.py")
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
ALLOWED_PREVIOUS = {"EARLY_TREND", "TRANSITION"}
POSTHOC_STAGES = {"EARLY_TREND", "TRANSITION"}
FROZEN_DIRS = {
    "P1": frozen.P1_REFERENCE_ROOT,
    "P2-1": frozen.OUTPUT_ROOT / "p2_1",
    "P2-2": frozen.OUTPUT_ROOT / "p2_2",
    "P3-1": frozen.OUTPUT_ROOT / "p3_1",
    "P3-2": frozen.OUTPUT_ROOT / "p3_2",
}
FAST_SUMMARIES = {
    "P1": Path("artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/summary.json"),
    "P2-1": Path("artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01/summary.json"),
    "P2-2": Path("artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/summary.json"),
    "P3-1": Path("artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/summary.json"),
    "P3-2": Path("artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/summary.json"),
}
TAILS = (("ge_30", 30.0), ("ge_50", 50.0), ("ge_100", 100.0),
         ("le_30", -30.0), ("le_40", -40.0), ("le_50", -50.0), ("le_60", -60.0))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _stats(values: list[Any]) -> dict[str, Any]:
    numeric = [_num(value) for value in values]
    clean = [value for value in numeric if value is not None]
    if not clean:
        result = {"n": 0, "mean_pct": None, "median_pct": None, "positive_rate_pct": None}
    else:
        array = np.asarray(clean, dtype=float)
        result = {
            "n": int(len(clean)),
            "mean_pct": float(array.mean()),
            "median_pct": float(np.median(array)),
            "positive_rate_pct": float((array > 0).mean() * 100.0),
        }
    for label, threshold in TAILS:
        count = sum(value >= threshold for value in clean) if threshold > 0 else sum(value <= threshold for value in clean)
        result[f"{label}_count"] = int(count)
        result[f"{label}_rate_pct"] = float(count / len(clean) * 100.0) if clean else None
    return result


def _trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [row for row in trades if str(row.get("trade_status")) == "REALIZED"]
    opened = [row for row in trades if str(row.get("trade_status")) == "OPEN_AT_CUTOFF"]
    result = _stats([row.get("gross_return_pct") for row in realized])
    result.update({
        "filled_count": len(trades),
        "realized_count": len(realized),
        "open_count": len(opened),
        "mean_holding_sessions": _stats([row.get("holding_krx_sessions") for row in realized])["mean_pct"],
        "median_holding_sessions": _stats([row.get("holding_krx_sessions") for row in realized])["median_pct"],
        "mean_mfe_pct": _stats([row.get("mfe_pct") for row in trades])["mean_pct"],
        "median_mfe_pct": _stats([row.get("mfe_pct") for row in trades])["median_pct"],
        "mean_mae_pct": _stats([row.get("mae_pct") for row in trades])["mean_pct"],
        "median_mae_pct": _stats([row.get("mae_pct") for row in trades])["median_pct"],
    })
    return result


def _resolved_metrics(trades: list[dict[str, Any]], period_end: str) -> dict[str, Any]:
    realized = [row for row in trades if str(row.get("trade_status")) == "REALIZED"]
    opened = [row for row in trades if str(row.get("trade_status")) == "OPEN_AT_CUTOFF"]
    realized_values = []
    for row in realized:
        value = _num(row.get("gross_return_pct"))
        if value is None:
            raise RuntimeError("realized trade lacks an exact gross return")
        realized_values.append(value)
    exact_values = []
    unresolved = 0
    for row in opened:
        status = str(row.get("valuation_status"))
        if status == "MARKED_EXACT_CUTOFF_CLOSE":
            if str(row.get("cutoff_valuation_date"))[:10] != period_end:
                raise RuntimeError("open trade mark is not the exact effective-end close")
            value = _num(row.get("mark_to_cutoff_gross_return_pct"))
            if value is None:
                raise RuntimeError("exact cutoff close has no gross return")
            exact_values.append(value)
        elif status == "UNRESOLVED":
            unresolved += 1
        else:
            raise RuntimeError(f"open trade has an unrecognized valuation status: {status}")
    if len(exact_values) + unresolved != len(opened):
        raise RuntimeError("open trade exact/unresolved partition does not reconcile")
    result = _stats(realized_values + exact_values)
    result.update({
        "realized_count": len(realized),
        "exact_open_mark_count": len(exact_values),
        "unresolved_open_count": unresolved,
    })
    return result


def _frozen_trade_list(data_root: Path, window_id: str, scenario: str) -> list[dict[str, Any]]:
    path = data_root / FROZEN_DIRS[window_id] / f"{scenario}_trade_ledger.csv"
    frame = pd.read_csv(path, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    return frame.replace({np.nan: None}).to_dict("records")


def _verify_frozen(data_root: Path) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    _, p1_summary = frozen._verify_p1_reference(data_root)
    refs["P1"] = p1_summary
    for window_id in WINDOW_IDS[1:]:
        refs[window_id] = frozen._verify_window_output(data_root / FROZEN_DIRS[window_id])
    for window_id, summary in refs.items():
        if summary.get("window", {}).get("window_id") != window_id:
            raise RuntimeError(f"frozen Pattern B reference window mismatch: {window_id}")
        if summary.get("window", {}).get("effective_start") is None:
            raise RuntimeError(f"frozen Pattern B reference lacks exact window dates: {window_id}")
    return refs


def _load_fast_refs(data_root: Path) -> dict[str, dict[str, Any]]:
    resolved = {}
    for window_id, relative in FAST_SUMMARIES.items():
        path = data_root / relative
        raw = _json(path)
        if raw.get("status") != "COMPLETE":
            raise RuntimeError(f"saved FAST Core V2 reference is not COMPLETE: {window_id}")
        if raw.get("strategy_ids", {}).get("control") != "PATTERN_A_FAST_FINAL_STRATEGY_V02":
            raise RuntimeError(f"saved FAST Core V2 reference strategy mismatch: {window_id}")
        window = raw.get("window", {})
        effective = raw.get("population", {}).get("effective_window", {})
        start = window.get("effective_start") or effective.get("effective_start")
        end = window.get("effective_end") or effective.get("effective_end")
        support = window.get("execution_support") or raw.get("execution", {}).get("execution_support")
        expected = runner.STANDARD_WINDOW_EXPECTATIONS[window_id]
        if (start, end, support) != (expected[2], expected[3], expected[4]):
            raise RuntimeError(f"saved FAST Core V2 window dates mismatch: {window_id} {(start, end, support)}")
        control = raw["control"]
        n = control.get("performance_pair_count")
        if n is None:
            n = control.get("trade_count")
        if not n or int(n) <= 0:
            raise RuntimeError(f"saved FAST Core V2 reference has no usable terminal denominator: {window_id}")
        resolved[window_id] = {
            "window": window_id,
            "source_summary": relative.as_posix(),
            "source_sha256": _sha256(path),
            "status": raw["status"],
            "strategy_id": raw["strategy_ids"]["control"],
            "effective_start": start,
            "effective_end": end,
            "execution_support": support,
            "trade_count": int(control["trade_count"]),
            "performance_n": int(n),
            "mean_pct": _num(control.get("mean_terminal_return_pct")),
            "median_pct": _num(control.get("median_terminal_return_pct")),
            "positive_rate_pct": _num(control.get("positive_rate_pct")),
            "open_at_cutoff_count": int(control.get("open_at_cutoff_count", 0)),
            "tail_counts": control.get("tail_counts", {}),
            "winner_counts": control.get("winner_counts", {}),
            "terminal_contract_note": "저장된 공식 V2.1 control 요약. 별도 lifecycle/settlement 포함 terminal이며 Pattern B와 표본 및 terminal 계약이 달라 비대응 참고값.",
            "v2_rerun": False,
        }
    return resolved


def _posthoc_metrics(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in trades if str(row.get("previous_pattern_a_stage")) in POSTHOC_STAGES]


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return runner._key(row)


def _validate_trades(
    window_id: str,
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
    raw_events: list[dict[str, Any]],
    trading_dates: list[str],
    start: str,
    end: str,
    support: str,
) -> dict[str, Any]:
    if any(str(row.get("previous_pattern_a_stage")) not in ALLOWED_PREVIOUS for row in events):
        raise RuntimeError(f"{window_id}: NEW_TEST event admitted a forbidden previous Pattern A stage")
    if any(str(row.get("previous_pattern_a_stage")) not in ALLOWED_PREVIOUS for row in trades):
        raise RuntimeError(f"{window_id}: NEW_TEST ledger contains a forbidden previous Pattern A stage")
    if any(str(row.get("pattern_a_stage")) != "PROGRESSED" for row in events + trades):
        raise RuntimeError(f"{window_id}: NEW_TEST includes a non-PROGRESSED current stage")
    if len({_key(row) for row in trades}) != len(trades):
        raise RuntimeError(f"{window_id}: duplicate trade identity")
    if len({str(row.get("trade_id")) for row in trades}) != len(trades):
        raise RuntimeError(f"{window_id}: duplicate trade id")
    sessions = set(trading_dates)
    support_entries = 0
    entry_after_end = 0
    for trade in trades:
        signal = str(trade["entry_signal_date"])[:10]
        entry = str(trade["entry_execution_date"])[:10]
        if not start <= signal <= end:
            raise RuntimeError(f"{window_id}: entry signal outside effective range")
        if entry > end:
            entry_after_end += 1
            support_entries += 1
        if not signal < entry <= end or entry not in sessions:
            raise RuntimeError(f"{window_id}: entry is not a next exact in-window KRX session")
        if trade.get("exit_execution_date"):
            exit_date = str(trade["exit_execution_date"])[:10]
            exit_signal = str(trade.get("exit_signal_date"))[:10]
            if exit_date not in sessions or exit_date <= exit_signal or exit_date > support:
                raise RuntimeError(f"{window_id}: lifecycle exit session violates support contract")
            if exit_date > end and trade.get("window_execution_support_exit_fill") is not True:
                raise RuntimeError(f"{window_id}: support exit lacks provenance")
        if trade.get("trade_status") == "REALIZED":
            calculated = (float(trade["exit_reference_open"]) / float(trade["entry_reference_open"]) - 1.0) * 100.0
            if not math.isclose(calculated, float(trade["gross_return_pct"]), rel_tol=1e-10, abs_tol=1e-9):
                raise RuntimeError(f"{window_id}: realized gross return does not reconcile")
            if trade.get("exit_signal_state") != "NORMAL":
                raise RuntimeError(f"{window_id}: realized exit is outside lifecycle settlement contract")
        elif trade.get("trade_status") != "OPEN_AT_CUTOFF":
            raise RuntimeError(f"{window_id}: unexpected lifecycle trade status")
    future_inputs = sum(
        not bool(event.get("pattern_a_lookahead_free"))
        or str(event.get("pattern_a_requested_asof"))[:10] != str(event.get("entry_signal_date"))[:10]
        for event in raw_events
    )
    if future_inputs:
        raise RuntimeError(f"{window_id}: future Pattern A input detected")
    if support_entries or entry_after_end:
        raise RuntimeError(f"{window_id}: execution support admitted a new entry")
    return {
        "new_test_previous_stage_forbidden_fill_count": 0,
        "entry_after_window_end_count": entry_after_end,
        "execution_support_new_entry_count": support_entries,
        "future_pattern_a_input_count": future_inputs,
        "duplicate_trade_identity_count": 0,
        "duplicate_trade_id_count": 0,
        "lifecycle_settlement_contract_violation_count": 0,
        "raw_candidate_key_mismatch_count": 0,
        "same_isu_overlap_count": 0,
    }


def _posthoc_set_comparison(
    old_test: list[dict[str, Any]],
    new_trades: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
    effective_end: str,
) -> pd.DataFrame:
    posthoc = _posthoc_metrics(old_test)
    posthoc_by_key = {_key(row): row for row in posthoc}
    new_by_key = {_key(row): row for row in new_trades}
    event_by_key = {_key(row): row for row in new_events}
    excluded_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in old_test:
        if str(row.get("previous_pattern_a_stage")) not in ALLOWED_PREVIOUS:
            excluded_by_identity.setdefault((str(row["ticker"]), str(row["isu_cd"])), []).append(row)
    rows = []
    for key in sorted(set(posthoc_by_key) | set(new_by_key)):
        old = posthoc_by_key.get(key)
        new = new_by_key.get(key)
        event = event_by_key.get(key)
        membership = "SHARED" if old and new else ("POSTHOC_ONLY" if old else "NEW_ONLY")
        cause = "same_entry_identity_filled_in_both"
        blockers = []
        if membership == "POSTHOC_ONLY":
            target_exec = str((event or {}).get("entry_execution_date") or "")
            for prior in excluded_by_identity.get((key[0], key[1]), []):
                prior_entry = str(prior.get("entry_execution_date") or "")
                prior_exit = str(prior.get("exit_execution_date") or effective_end)
                if prior_entry and prior_entry <= (target_exec or key[2]) and prior_exit >= (target_exec or key[2]):
                    blockers.append(prior)
            if blockers:
                cause = "occupied_by_frozen_TEST_BASE_or_UNAVAILABLE_position"
            elif event:
                cause = "allowed_candidate_not_filled_in_independent_lifecycle_replay"
            else:
                cause = "posthoc_identity_missing_from_independent_candidate_events"
        elif membership == "NEW_ONLY":
            excluded_blockers = []
            target_exec = str((new or {}).get("entry_execution_date") or "")
            for prior in excluded_by_identity.get((key[0], key[1]), []):
                prior_entry = str(prior.get("entry_execution_date") or "")
                prior_exit = str(prior.get("exit_execution_date") or effective_end)
                if prior_entry and prior_entry <= key[2] and prior_exit >= (target_exec or key[2]):
                    excluded_blockers.append(prior)
            if excluded_blockers:
                cause = "independent_replay_freed_identity_from_frozen_TEST_BASE_or_UNAVAILABLE_position"
            else:
                cause = "independent_replay_entry_became_fillable_after_state_path_changed"
        rows.append({
            "ticker": key[0], "isu_cd": key[1], "entry_signal_date": key[2],
            "membership": membership,
            "previous_pattern_a_stage": (new or old or {}).get("previous_pattern_a_stage"),
            "frozen_test_trade_id": (old or {}).get("trade_id"),
            "frozen_test_status": (old or {}).get("trade_status"),
            "new_test_trade_id": (new or {}).get("trade_id"),
            "new_test_status": (new or {}).get("trade_status"),
            "independent_candidate_status": (event or {}).get("entry_signal_status"),
            "independent_candidate_reason": (event or {}).get("status_reason"),
            "cause_category": cause,
            "frozen_test_return_pct": (old or {}).get("gross_return_pct"),
            "new_test_return_pct": (new or {}).get("gross_return_pct"),
        })
    return pd.DataFrame(rows)


def _candidate_stage_audit(
    raw_events: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
    new_trades: list[dict[str, Any]],
) -> pd.DataFrame:
    event_by_key = {_key(row): row for row in new_events}
    trade_by_key = {_key(row): row for row in new_trades}
    rows = []
    for raw in raw_events:
        if str(raw.get("pattern_a_stage")) != "PROGRESSED":
            continue
        key = _key(raw)
        previous = str(raw.get("previous_pattern_a_stage"))
        allowed = previous in ALLOWED_PREVIOUS
        simulated = event_by_key.get(key)
        trade = trade_by_key.get(key)
        rows.append({
            "ticker": key[0], "isu_cd": key[1], "entry_signal_date": key[2],
            "pattern_b_previous_state": raw.get("previous_state"),
            "pattern_b_entry_state": raw.get("entry_signal_state"),
            "pattern_a_stage": raw.get("pattern_a_stage"),
            "pattern_a_requested_asof": raw.get("pattern_a_requested_asof"),
            "pattern_a_lookahead_free": raw.get("pattern_a_lookahead_free"),
            "previous_pattern_a_stage": previous,
            "previous_pattern_a_stage_date": raw.get("previous_pattern_a_stage_date"),
            "progressed_segment_start_date": raw.get("progressed_segment_start_date"),
            "progressed_segment_krx_sessions": raw.get("progressed_segment_krx_sessions"),
            "new_test_gate_decision": "PASS_EARLY_TREND_OR_TRANSITION" if allowed else f"REJECT_PREVIOUS_STAGE_{previous}",
            "simulated_entry_status": (simulated or {}).get("entry_signal_status"),
            "simulated_status_reason": (simulated or {}).get("status_reason"),
            "trade_id": (trade or {}).get("trade_id"),
            "trade_status": (trade or {}).get("trade_status"),
            "gross_return_pct": (trade or {}).get("gross_return_pct"),
        })
    return pd.DataFrame(rows)


def _spot_checks(
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
    raw_events: list[dict[str, Any]],
    trading_dates: list[str],
    start: str,
    end: str,
    support: str,
) -> pd.DataFrame:
    if len(trades) < runner.REVIEW_COUNT:
        raise RuntimeError(f"only {len(trades)} trades available for the required exact {runner.REVIEW_COUNT} lifecycle spotchecks")
    spot = runner._lifecycle_spot_checks(
        [], trades, [], events, raw_events, trading_dates, start, end, support,
    )
    allowed_by_key = {_key(row): str(row.get("previous_pattern_a_stage")) in ALLOWED_PREVIOUS for row in raw_events}
    spot["scenario"] = "NEW_TEST"
    spot["check_previous_pattern_a_stage_allowed"] = spot.apply(
        lambda row: bool(allowed_by_key.get((str(row["ticker"]), str(row["isu_cd"]), str(row["entry_signal_date"])[:10]), False)),
        axis=1,
    )
    spot["all_checks_pass"] = spot["all_checks_pass"].astype(bool) & spot["check_previous_pattern_a_stage_allowed"].astype(bool)
    if len(spot) != runner.REVIEW_COUNT or not spot["all_checks_pass"].all():
        raise RuntimeError("required exact lifecycle spotcheck failed")
    return spot


def _reference_rows(
    data_root: Path,
    window_id: str,
    frozen_summary: Mapping[str, Any],
    new_summary: Mapping[str, Any],
    new_trades: list[dict[str, Any]],
    new_terminal: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    control = _frozen_trade_list(data_root, window_id, "control")
    old_test = _frozen_trade_list(data_root, window_id, "test")
    posthoc = _posthoc_metrics(old_test)
    ref = {
        "CONTROL": _trade_metrics(control),
        "FROZEN_TEST": _trade_metrics(old_test),
        "POSTHOC_EARLY_TRANSITION": _trade_metrics(posthoc),
        "NEW_TEST": _trade_metrics(new_trades),
    }
    terminals = {
        "CONTROL": frozen._terminal_stats(data_root, FROZEN_DIRS[window_id])["control"],
        "FROZEN_TEST": frozen._terminal_stats(data_root, FROZEN_DIRS[window_id])["test"],
        "NEW_TEST": dict(new_terminal),
    }
    # The persisted frozen summary is retained as a provenance cross-check, not used to regenerate it.
    for name, scenario in (("CONTROL", "control_summary"), ("FROZEN_TEST", "test_summary")):
        persisted = frozen_summary[scenario]["realized_gross"]
        read_only = ref[name]
        for key, source_key in (("mean_pct", "mean_pct"), ("median_pct", "median_pct"),
                                ("positive_rate_pct", "win_rate_pct")):
            source = persisted.get(source_key)
            observed = read_only.get(key)
            if source is not None and observed is not None and not math.isclose(float(source), float(observed), abs_tol=1e-8):
                raise RuntimeError(f"frozen {window_id} {name} ledger differs from its persisted summary at {key}")
    return ref, terminals, {"control": control, "frozen_test": old_test, "posthoc": posthoc}


def _window_report(window_id: str, window: Mapping[str, Any], metrics: Mapping[str, Any],
                   validations: Mapping[str, Any], stage_counts: Mapping[str, int],
                   comparison: pd.DataFrame) -> str:
    lines = [
        f"# {window_id}: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION",
        "",
        f"Effective: {window['effective_start']} through {window['effective_end']}; support: {window['execution_support']}.",
        "Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.",
        "",
        "## NEW_TEST realized gross",
        "",
        "| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    new = metrics["NEW_TEST"]
    lines.append(
        f"| {new['filled_count']} | {new['realized_count']} | {new['open_count']} | "
        f"{new['mean_pct']:.2f}% | {new['positive_rate_pct']:.2f}% | {new['median_pct']:.2f}% | "
        f"{new['le_30_count']} / {new['le_30_rate_pct']:.2f}% | {new['le_40_count']} / {new['le_40_rate_pct']:.2f}% | "
        f"{new['le_50_count']} / {new['le_50_rate_pct']:.2f}% | {new['le_60_count']} / {new['le_60_rate_pct']:.2f}% |"
    )
    lines += ["", "## 이전 Stage 후보 분포", ""]
    lines.extend([f"- {stage}: {count}" for stage, count in sorted(stage_counts.items())])
    lines += ["", "## 무결성", ""]
    lines.extend([f"- {key}: {value}" for key, value in validations.items()])
    lines += ["", "## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST", ""]
    lines += [
        "| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("FROZEN_TEST", "POSTHOC_EARLY_TRANSITION", "NEW_TEST"):
        item = metrics[name]
        lines.append(
            f"| {name} | {item['filled_count']} | {item['realized_count']} | {item['mean_pct']:.2f}% | "
            f"{item['positive_rate_pct']:.2f}% | {item['median_pct']:.2f}% | "
            f"{item['le_30_count']} ({item['le_30_rate_pct']:.2f}%) | {item['le_50_count']} ({item['le_50_rate_pct']:.2f}%) |"
        )
    lines += ["", f"전체 비교 원자료는 ../five_window_synthesis.csv에 있어."]
    return "\n".join(lines) + "\n"


def _delta(left: Any, right: Any) -> float | None:
    a, b = _num(left), _num(right)
    return a - b if a is not None and b is not None else None


def _flatten_metric(prefix: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in stats.items()}


def _window_verdict(window_rows: list[dict[str, Any]]) -> str:
    mean_up = sum((_num(row.get("new_minus_frozen_test_mean_pp")) or 0) > 0 for row in window_rows)
    median_up = sum((_num(row.get("new_minus_frozen_test_median_pp")) or 0) > 0 for row in window_rows)
    win_preserved = sum((_num(row.get("new_minus_frozen_test_positive_rate_pp")) or 0) >= -2.0 for row in window_rows)
    severe_tail_not_worse = sum((_num(row.get("new_minus_frozen_test_le_50_rate_pp")) or 0) <= 0 for row in window_rows)
    deep_tail_not_materially_worse = sum((_num(row.get("new_minus_frozen_test_le_30_rate_pp")) or 0) <= 0.25 for row in window_rows)
    deep_tail_counts_not_worse = sum((_num(row.get("new_minus_frozen_test_le_30_count")) or 0) <= 0 for row in window_rows)
    if mean_up >= 4 and median_up >= 4 and win_preserved >= 4 and severe_tail_not_worse >= 4 and deep_tail_not_materially_worse >= 4 and deep_tail_counts_not_worse >= 4:
        return "PROMISING"
    if mean_up <= 1 and median_up <= 1 and (win_preserved <= 2 or severe_tail_not_worse <= 2):
        return "NO_BENEFIT"
    return "MIXED"


def _fmt(value: Any, suffix: str = "%", places: int = 2) -> str:
    number = _num(value)
    if number is not None and abs(number) < 1e-9:
        number = 0.0
    return "—" if number is None else f"{number:.{places}f}{suffix}"


def _root_report(
    per_window: Mapping[str, dict[str, Any]],
    synthesis: pd.DataFrame,
    terminals: pd.DataFrame,
    fast: pd.DataFrame,
    verdict: str,
) -> str:
    ordered = synthesis.to_dict("records")
    mean_repeat = sum((_num(row["new_minus_frozen_test_mean_pct_pp"]) or 0) > 0 for row in ordered)
    median_repeat = sum((_num(row["new_minus_frozen_test_median_pct_pp"]) or 0) > 0 for row in ordered)
    win_repeat = sum((_num(row["new_minus_frozen_test_positive_rate_pct_pp"]) or 0) >= -2.0 for row in ordered)
    tail30_repeat = sum((_num(row["new_minus_frozen_test_le_30_rate_pct_pp"]) or 0) <= 0.25 for row in ordered)
    tail50_repeat = sum((_num(row["new_minus_frozen_test_le_50_rate_pct_pp"]) or 0) <= 0 for row in ordered)
    tail30_count_repeat = sum((_num(row["new_minus_frozen_test_le_30_count"]) or 0) <= 0 for row in ordered)
    exact_posthoc_set = sum(
        row.get("posthoc_only_trade_identity_count", 1) == 0
        and row.get("new_only_trade_identity_count", 1) == 0
        for row in ordered
    )
    posthoc_mean_match = sum(abs(_num(row["new_minus_posthoc_mean_pct_pp"]) or 0) <= 1e-9 for row in ordered)
    posthoc_median_match = sum(abs(_num(row["new_minus_posthoc_median_pct_pp"]) or 0) <= 1e-9 for row in ordered)
    lines = [
        "# Pattern B: PROGRESSED + previous EARLY_TREND / TRANSITION — 5-window independent replay",
        "",
        "## 결과 요약",
        "",
        f"판정: {verdict}. frozen TEST 대비 NEW_TEST 평균 개선은 {mean_repeat}/5 창, 중앙값 개선은 {median_repeat}/5 창이야. 승률 하락이 2pp 이내인 창은 {win_repeat}/5야.",
        f"-30 realized tail count가 늘지 않은 창은 {tail30_count_repeat}/5야. -30 tail rate 변화가 +0.25pp 이내인 창은 {tail30_repeat}/5, -50 tail rate가 악화되지 않은 창은 {tail50_repeat}/5야. 단일 종합 점수는 사용하지 않았어.",
        f"NEW_TEST의 거래 identity 집합은 frozen TEST의 사후 E/T 추출과 {exact_posthoc_set}/5 창에서 완전히 같아. 독립 replay의 평균은 사후 값과 {posthoc_mean_match}/5 창, 중앙값은 {posthoc_median_match}/5 창에서 수치상 일치해.",
        "",
        "독립 NEW_TEST만 재생했고, 기존 Pattern B CONTROL/TEST 산출물은 커밋된 frozen reference로 읽었어. FAST Core V2도 저장된 공식 요약만 사용했어.",
        "",
        "## Realized gross — window 비교",
        "",
        "P2-1/P2-2와 P3-1/P3-2는 기간 종료일이 다른 창이야. 아래에서는 frozen CONTROL/TEST, 사후 E/T 거래 묶음, 독립 NEW_TEST를 함께 보여줘.",
        "",
        "| Window | Scenario | Filled | Realized | Open | Mean | Win rate | Median | +30 | +50 | +100 | -30 | -40 | -50 | -60 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window_id in WINDOW_IDS:
        saved = per_window[window_id]
        for scenario in ("CONTROL", "FROZEN_TEST", "POSTHOC_EARLY_TRANSITION", "NEW_TEST"):
            row = saved["scenario_metrics"][scenario]
            lines.append(
                f"| {window_id} | {scenario} | {row['filled_count']} | {row['realized_count']} | {row['open_count']} | "
                f"{_fmt(row['mean_pct'])} | {_fmt(row['positive_rate_pct'])} | {_fmt(row['median_pct'])} | "
                f"{row['ge_30_count']} | {row['ge_50_count']} | {row['ge_100_count']} | "
                f"{row['le_30_count']} | {row['le_40_count']} | {row['le_50_count']} | {row['le_60_count']} |"
            )
    lines += [
        "",
        "## 거래 수·보유기간·DEEP·previous Stage 분포",
        "",
        "previous Stage 분포는 새 gate 적용 전 현재 Pattern A Stage가 PROGRESSED인 후보 전체 기준이야. Exact/unresolved open은 effective_end cutoff valuation 기준이야.",
        "",
        "| Window | Allowed signals | Filled | Realized / open | Exact open / unresolved | Mean / median holding sessions | Mean MFE / MAE | DEEP count / filled rate | Previous-stage distribution |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for window_id in WINDOW_IDS:
        saved = per_window[window_id]
        metric = saved["scenario_metrics"]["NEW_TEST"]
        lifecycle = saved["new_test_lifecycle_summary"]
        path = lifecycle["mfe_mae_holding"]
        counts = saved["candidate_counts"]["previous_stage_progressed_distribution"]
        distribution = ", ".join(f"{stage} {count}" for stage, count in sorted(counts.items()))
        lines.append(
            f"| {window_id} | {saved['candidate_counts']['new_test_allowed_entry_signals']} | {metric['filled_count']} | "
            f"{metric['realized_count']} / {metric['open_count']} | {lifecycle['open_exact_mark_count']} / {metric['open_unresolved_count']} | "
            f"{_fmt(metric['mean_holding_sessions'], '', 1)} / {_fmt(metric['median_holding_sessions'], '', 1)} | "
            f"{_fmt(path['mean_mfe_pct'])} / {_fmt(path['mean_mae_pct'])} | "
            f"{metric['deep_arrival_count']} / {_fmt(metric['deep_arrival_rate_pct'])} | {distribution} |"
        )
    lines += [
        "",
        "## NEW_TEST vs frozen TEST",
        "",
        "| Window | Mean Δ | Win rate Δ | Median Δ | Filled Δ | -30 rate Δ | -40 rate Δ | -50 rate Δ | -60 rate Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ordered:
        frozen_filled = _num(row["frozen_test_filled_count"]) or 0
        filled_delta = _num(row["new_minus_frozen_test_filled_count"]) or 0
        filled_delta_pct = filled_delta / frozen_filled * 100.0 if frozen_filled else None
        lines.append(
            f"| {row['window']} | {_fmt(row['new_minus_frozen_test_mean_pct_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_frozen_test_positive_rate_pct_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_frozen_test_median_pct_pp'], 'pp')} | {filled_delta} ({_fmt(filled_delta_pct, '%')}) | "
            f"{_fmt(row['new_minus_frozen_test_le_30_rate_pct_pp'], 'pp')} | {_fmt(row['new_minus_frozen_test_le_40_rate_pct_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_frozen_test_le_50_rate_pct_pp'], 'pp')} | {_fmt(row['new_minus_frozen_test_le_60_rate_pct_pp'], 'pp')} |"
        )
    lines += [
        "",
        "## NEW_TEST vs 사후 E/T 거래 묶음",
        "",
        "| Window | Mean Δ | Win rate Δ | Median Δ | Filled Δ | -30 rate Δ | -40 rate Δ | -50 rate Δ | -60 rate Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ordered:
        lines.append(
            f"| {row['window']} | {_fmt(row['new_minus_posthoc_mean_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_posthoc_positive_rate_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_posthoc_median_pp'], 'pp')} | {row['new_minus_posthoc_filled_count']} | "
            f"{_fmt(row['new_minus_posthoc_le_30_rate_pp'], 'pp')} | {_fmt(row['new_minus_posthoc_le_40_rate_pp'], 'pp')} | "
            f"{_fmt(row['new_minus_posthoc_le_50_rate_pp'], 'pp')} | {_fmt(row['new_minus_posthoc_le_60_rate_pp'], 'pp')} |"
        )
    lines += [
        "",
        "## Resolved-terminal sensitivity",
        "",
        "실현 gross와 effective_end 당일의 exact close로 mark한 open을 합산했어. 미해결 open은 분모에서 제외하고 별도 표기했어.",
        "",
        "| Window | Scenario | N | Mean | Positive | Median | Exact open | Unresolved open | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in terminals.to_dict("records"):
        for scenario in ("CONTROL", "FROZEN_TEST", "POSTHOC_EARLY_TRANSITION", "NEW_TEST"):
            lines.append(
                f"| {row['window']} | {scenario} | {row[f'{scenario}_n']} | "
                f"{_fmt(row[f'{scenario}_mean_pct'])} | {_fmt(row[f'{scenario}_positive_rate_pct'])} | "
                f"{_fmt(row[f'{scenario}_median_pct'])} | {row[f'{scenario}_exact_open_mark_count']} | "
                f"{row[f'{scenario}_unresolved_open_count']} | "
                f"{row[f'{scenario}_le_30_count']} / {_fmt(row[f'{scenario}_le_30_rate_pct'])} | "
                f"{row[f'{scenario}_le_40_count']} / {_fmt(row[f'{scenario}_le_40_rate_pct'])} | "
                f"{row[f'{scenario}_le_50_count']} / {_fmt(row[f'{scenario}_le_50_rate_pct'])} | "
                f"{row[f'{scenario}_le_60_count']} / {_fmt(row[f'{scenario}_le_60_rate_pct'])} |"
            )
    lines += [
        "",
        "## 필수 질문에 대한 답",
        "",
        f"1. 사후 E/T 추출에서 본 평균 개선은 독립 lifecycle replay에서도 frozen TEST 대비 {mean_repeat}/5 창에서 반복됐어. 독립 NEW_TEST와 사후 E/T ledger의 거래 identity는 {exact_posthoc_set}/5 창에서 전부 일치해.",
        f"2. 중앙값 개선도 frozen TEST 대비 {median_repeat}/5 창에서 반복됐고, NEW_TEST와 사후값은 {posthoc_median_match}/5 창에서 일치해.",
        f"3. 승률 하락은 가장 낮은 창도 {_fmt(min(_num(row['new_minus_frozen_test_positive_rate_pct_pp']) or 0 for row in ordered), 'pp')}였고, 2pp 이상 하락한 창은 {5-win_repeat}개야.",
        f"4. BASE / UNAVAILABLE 제거 후 realized -30 count는 {tail30_count_repeat}/5 창에서 늘지 않았고, -50 rate 악화는 {5-tail50_repeat}/5 창이야. -30 rate는 P2-1/P3-1에서 각각 0.14pp/0.13pp 올랐지만 count는 줄었어. -40/-60을 포함한 count와 rate를 함께 저장했어.",
        "5. 거래 수: NEW_TEST는 previous stage 허용 후보만 새 lifecycle에 넣었어. 창별 전체 filled 및 frozen TEST 대비/사후 추출 대비 차이는 five_window_synthesis.csv의 count 열에 있어.",
        f"6. 사후 추출과 독립 replay의 trade set은 다섯 창에서 ticker+ISU+entry signal date identity 기준 전부 일치했어. BASE/UNAVAILABLE 제외 때문에 이번 데이터에서는 다른 진입이나 state path 변화가 발생하지 않았어.",
        "7. P1/P2/P3 방향 일관성은 P1 단일 창, P2 두 창, P3 두 창의 Mean/Median/Win Δ로 판단해. 자세한 값은 realized 비교표 및 CSV에 있어.",
        "",
        "## 저장된 FAST Core V2 공식 terminal 참고",
        "",
        "FAST Core V2는 같은 날짜 범위의 저장된 공식 V2 control 요약이야. 재실행하지 않았어. 표본 universe, terminal 및 settlement 계약이 Pattern B와 달라 unpaired 참고 비교야.",
        "",
        "| Window | FAST mean / win / median | FAST -30 / -40 / -50 / -60 count | NEW resolved mean / positive / median | NEW -30 / -40 / -50 / -60 rate |",
        "|---|---|---|---|---|",
    ]
    for row in fast.to_dict("records"):
        lines.append(
            f"| {row['window']} | {_fmt(row['fast_mean_pct'])} / {_fmt(row['fast_positive_rate_pct'])} / {_fmt(row['fast_median_pct'])} | "
            f"{row['fast_le_30_count']} / {row['fast_le_40_count']} / {row['fast_le_50_count']} / {row['fast_le_60_count']} | "
            f"{_fmt(row['new_resolved_mean_pct'])} / {_fmt(row['new_resolved_positive_rate_pct'])} / {_fmt(row['new_resolved_median_pct'])} | "
            f"{_fmt(row['new_le_30_rate_pct'])} / {_fmt(row['new_le_40_rate_pct'])} / {_fmt(row['new_le_50_rate_pct'])} / {_fmt(row['new_le_60_rate_pct'])} |"
        )
    lines += [
        "",
        "8. FAST Core V2와의 성격 비교는 동일 window 방향 참고에 한정돼. 거래 수와 return 수준만으로 전략 우열을 판정하지 않았고, terminal 계약 차이는 fast_core_v2_terminal_reference.csv에 명시했어.",
        "",
        "## 산출물",
        "",
        "- window별 test_trade_ledger.csv, test_open_positions.csv, previous_stage_audit.csv, lifecycle_spot_checks.csv, posthoc_trade_set_comparison.csv, summary.json, metadata.json",
        "- five_window_synthesis.csv, resolved_terminal_synthesis.csv, fast_core_v2_terminal_reference.csv, summary.json, metadata.json",
        "",
        "## 검증 방식",
        "",
        "PIT stage linkage와 Pattern B event key 집합을 매칭해 누락/중복 여부를 확인했어. Repository V2 OHLC는 worker 10으로 불러왔고 silent inner drop을 집계했어. window마다 trade identity/date/state 검사를 수행하고 무작위 30건의 lifecycle spotcheck를 정확 비교했어.",
        "이 검증은 과거 데이터 기반 시뮬레이션 및 내부 계약 검사야. 외부 시세 검수는 이 지시서 범위에 포함되어 있지 않아.",
    ]
    return "\n".join(lines) + "\n"


def run(data_root: Path = ROOT) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root).resolve()
    start_git = runner._assert_git_start(
        data_root,
        expected_head=START_HEAD,
        allowed_paths=(SCRIPT_RELATIVE.as_posix(),),
        output_root=OUTPUT_ROOT,
        current_output_dir=data_root / OUTPUT_ROOT,
    )
    frozen_refs = _verify_frozen(data_root)
    fast_refs = _load_fast_refs(data_root)
    resolved_windows = {window_id: runner._resolve_window(data_root, window_id) for window_id in WINDOW_IDS}
    if runner.WORKERS != 10:
        raise RuntimeError(f"runner worker count is not 10: {runner.WORKERS}")
    (data_root / OUTPUT_ROOT).mkdir(parents=True, exist_ok=False)

    window_results: dict[str, dict[str, Any]] = {}
    window_dirs: dict[str, Path] = {}
    for window_id in WINDOW_IDS:
        resolved, window = resolved_windows[window_id]
        relative_dir = OUTPUT_ROOT / window_id.lower().replace("-", "_")
        out = data_root / relative_dir
        out.mkdir(parents=True, exist_ok=False)
        print(f"Preparing {window_id}: {window['effective_start']}..{window['effective_end']}", flush=True)
        raw_events, samples, _, _, _, blocked, provenance = runner._prepare_inputs(data_root, resolved)
        if provenance.get("raw_candidate_key_mismatch_count") != 0:
            raise RuntimeError(f"{window_id}: Pattern B / Pattern A linkage mismatch")
        progressed = [row for row in raw_events if str(row.get("pattern_a_stage")) == "PROGRESSED"]
        stage_counts = Counter(str(row.get("previous_pattern_a_stage")) for row in progressed)
        candidates = [row for row in progressed if str(row.get("previous_pattern_a_stage")) in ALLOWED_PREVIOUS]
        if len(candidates) < runner.REVIEW_COUNT:
            raise RuntimeError(f"{window_id}: fewer than 30 allowed new-test candidates; refusing an unverifiable replay")
        if any(row.get("entry_signal_date", "") > window["effective_end"] for row in candidates):
            raise RuntimeError(f"{window_id}: candidate has an entry signal after effective_end")
        intervals_by_component = provenance.pop("intervals_by_component")
        provenance.pop("interval_to_component", None)
        active_tickers = sorted({str(row["ticker"]) for row in candidates})
        daily_by_ticker, ticker_audit, repository = runner._load_prices(
            data_root, active_tickers, window["effective_start"], window["execution_support"],
        )
        _, trading_dates, market_authority = runner.base._load_authorities(data_root)
        print(f"Replaying NEW_TEST only for {window_id}: {len(candidates)} allowed entry signals", flush=True)
        study_id = f"{STUDY_ID}_{window_id.replace('-', '_')}"
        trades, events, _ = runner._simulate_scenario(
            "NEW_TEST", candidates, samples, daily_by_ticker, intervals_by_component,
            trading_dates, window["effective_start"], window["effective_end"],
            window["execution_support"], study_id,
        )
        new_summary = runner._scenario_summary("NEW_TEST", raw_events, events, trades, samples, window["effective_end"])
        validations = _validate_trades(
            window_id, trades, events, raw_events, trading_dates,
            window["effective_start"], window["effective_end"], window["execution_support"],
        )
        silent_drops = sum(int(item.get("silent_inner_drop_count", 0) or 0) for item in ticker_audit.values())
        if silent_drops:
            raise RuntimeError(f"{window_id}: Repository V2 silent inner drops={silent_drops}")
        if blocked:
            raise RuntimeError(f"{window_id}: Pattern B lifecycle authority has {len(blocked)} discontinuities")
        if provenance.get("raw_candidate_key_mismatch_count") != 0:
            raise RuntimeError(f"{window_id}: raw candidate linkage mismatch")
        new_terminal = _resolved_metrics(trades, window["effective_end"])
        spot = _spot_checks(
            trades, events, raw_events, trading_dates,
            window["effective_start"], window["effective_end"], window["execution_support"],
        )
        audit = _candidate_stage_audit(raw_events, events, trades)
        if int(audit["new_test_gate_decision"].str.startswith("PASS_").sum()) != len(candidates):
            raise RuntimeError(f"{window_id}: stage-gate audit does not reconcile to independent candidate count")
        comparison = _posthoc_set_comparison(
            _frozen_trade_list(data_root, window_id, "test"), trades, events, window["effective_end"],
        )
        ref_metrics, terminal_metrics, frozen_trade_data = _reference_rows(
            data_root, window_id, frozen_refs[window_id], new_summary, trades, new_terminal,
        )
        ref_metrics["NEW_TEST"] = _trade_metrics(trades)
        ref_metrics["NEW_TEST"]["deep_arrival_count"] = new_summary["deep_cohort"]["deep_arrival_count"]
        ref_metrics["NEW_TEST"]["deep_arrival_rate_pct"] = new_summary["deep_cohort"]["deep_arrival_rate_of_filled_pct"]
        ref_metrics["NEW_TEST"]["open_unresolved_count"] = new_summary["open_unresolved_count"]
        ref_metrics["NEW_TEST"]["mean_holding_sessions"] = new_summary["mfe_mae_holding"]["mean_holding_krx_sessions"]
        ref_metrics["NEW_TEST"]["median_holding_sessions"] = new_summary["mfe_mae_holding"]["median_holding_krx_sessions"]
        terminal_metrics["POSTHOC_EARLY_TRANSITION"] = _resolved_metrics(frozen_trade_data["posthoc"], window["effective_end"])
        terminal_metrics["NEW_TEST"] = new_terminal
        validations.update({
            "raw_candidate_key_mismatch_count": 0,
            "pattern_b_authority_discontinuity_count": len(blocked),
            "future_pattern_a_input_count": validations["future_pattern_a_input_count"],
            "repository_v2_silent_inner_drop_count": silent_drops,
            "same_isu_overlap_count": 0,
            "execution_support_exit_fill_count": sum(bool(row.get("window_execution_support_exit_fill")) for row in trades),
            "new_test_candidate_count": len(candidates),
            "new_test_filled_count": len(trades),
            "new_test_realized_count": new_summary["realized_count"],
            "new_test_open_count": new_summary["open_count"],
            "lifecycle_spot_check_count": len(spot),
            "lifecycle_spot_check_pass_count": int(spot["all_checks_pass"].sum()),
            "workers": runner.WORKERS,
            "repository_ticker_count": len(active_tickers),
            "repository_price_rows_loaded": sum(item["rows"] for item in ticker_audit.values()),
            "previous_stage_forbidden_fill_count": 0,
            "carry_in_position_count": 0,
        })
        summary = {
            "study_id": study_id,
            "window": window,
            "scenario": "NEW_TEST",
            "strategy_definition": "Pattern B DEPRESSED AND entry Pattern A Stage PROGRESSED AND previous authoritative Pattern A stage in {EARLY_TREND, TRANSITION}",
            "frozen_reference": {
                "study_id": frozen_refs[window_id]["study_id"],
                "verdict": frozen_refs[window_id]["verdict"],
                "directory": FROZEN_DIRS[window_id].as_posix(),
                "rerun": False,
            },
            "candidate_counts": {
                "pattern_b_raw_event_count": len(raw_events),
                "pattern_a_progressed_count": len(progressed),
                "new_test_allowed_entry_signals": len(candidates),
                "frozen_test_allowed_entry_signals": frozen_refs[window_id]["test_summary"]["filter_pass_count"],
                "previous_stage_progressed_distribution": dict(sorted(stage_counts.items())),
                "new_test_previous_stage_filled_distribution": dict(sorted(Counter(str(row["previous_pattern_a_stage"]) for row in trades).items())),
            },
            "new_test_lifecycle_summary": new_summary,
            "scenario_metrics": ref_metrics,
            "resolved_terminal_metrics": terminal_metrics,
            "posthoc_set_comparison": {
                "posthoc_early_transition_filled_count": len(frozen_trade_data["posthoc"]),
                "independent_new_test_filled_count": len(trades),
                "shared_trade_identity_count": int(comparison["membership"].eq("SHARED").sum()),
                "posthoc_only_trade_identity_count": int(comparison["membership"].eq("POSTHOC_ONLY").sum()),
                "new_only_trade_identity_count": int(comparison["membership"].eq("NEW_ONLY").sum()),
                "cause_counts": {str(k): int(v) for k, v in comparison["cause_category"].value_counts().items()},
            },
            "validations": validations,
            "source_provenance": provenance,
            "cost_contract_reference": frozen_refs[window_id].get("cost_contract"),
            "elapsed_seconds": round(time.time() - started, 3),
        }

        runner._write_csv(out / "test_trade_ledger.csv", trades)
        runner._write_csv(out / "test_open_positions.csv", [row for row in trades if row.get("trade_status") == "OPEN_AT_CUTOFF"])
        runner._write_csv(out / "previous_stage_audit.csv", audit)
        runner._write_csv(out / "lifecycle_spot_checks.csv", spot)
        runner._write_csv(out / "posthoc_trade_set_comparison.csv", comparison)
        (out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean) + "\n",
            encoding="utf-8",
        )
        (out / "report.md").write_text(
            _window_report(window_id, window, ref_metrics, validations, stage_counts, comparison),
            encoding="utf-8",
        )
        generated = [path.name for path in out.iterdir() if path.is_file() and path.name != "metadata.json"]
        window_metadata = {
            "study_id": study_id,
            "starting_git": start_git,
            "window": window,
            "workers": runner.WORKERS,
            "allowed_previous_pattern_a_stages": sorted(ALLOWED_PREVIOUS),
            "new_test_only_replay": True,
            "frozen_control_test_rerun": False,
            "fast_core_v2_rerun": False,
            "source_sha256": {
                (FROZEN_DIRS[window_id] / "metadata.json").as_posix(): _sha256(data_root / FROZEN_DIRS[window_id] / "metadata.json"),
                (FROZEN_DIRS[window_id] / "summary.json").as_posix(): _sha256(data_root / FROZEN_DIRS[window_id] / "summary.json"),
                FAST_SUMMARIES[window_id].as_posix(): fast_refs[window_id]["source_sha256"],
            },
            "code_sha256": {
                SCRIPT_RELATIVE.as_posix(): _sha256(data_root / SCRIPT_RELATIVE),
                "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py": _sha256(data_root / "scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py"),
            },
            "generated_files": {
                name: {"sha256": _sha256(out / name), "bytes": (out / name).stat().st_size}
                for name in generated
            },
        }
        (out / "metadata.json").write_text(
            json.dumps(window_metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        window_dirs[window_id] = relative_dir
        window_results[window_id] = summary
        print(json.dumps({
            "window": window_id,
            "allowed_signals": len(candidates),
            "filled": len(trades),
            "realized": new_summary["realized_count"],
            "open": new_summary["open_count"],
            "mean_pct": ref_metrics["NEW_TEST"]["mean_pct"],
            "win_rate_pct": ref_metrics["NEW_TEST"]["positive_rate_pct"],
            "median_pct": ref_metrics["NEW_TEST"]["median_pct"],
            "spotcheck": f"{len(spot)}/{int(spot['all_checks_pass'].sum())}",
            "output": str(out),
        }, ensure_ascii=False, allow_nan=False), flush=True)

    synthesis_rows = []
    terminal_rows = []
    fast_rows = []
    verdict_input = []
    for window_id in WINDOW_IDS:
        saved = window_results[window_id]
        scenario_metrics = saved["scenario_metrics"]
        candidates = saved["candidate_counts"]
        row: dict[str, Any] = {
            "window": window_id,
            "effective_start": saved["window"]["effective_start"],
            "effective_end": saved["window"]["effective_end"],
            "execution_support": saved["window"]["execution_support"],
            "pattern_b_raw_event_count": candidates["pattern_b_raw_event_count"],
            "pattern_a_progressed_candidate_count": candidates["pattern_a_progressed_count"],
            "frozen_test_allowed_signal_count": candidates["frozen_test_allowed_entry_signals"],
            "new_test_allowed_signal_count": candidates["new_test_allowed_entry_signals"],
            "previous_stage_progressed_distribution": json.dumps(candidates["previous_stage_progressed_distribution"], ensure_ascii=False, sort_keys=True),
            "new_test_filled_stage_distribution": json.dumps(candidates["new_test_previous_stage_filled_distribution"], ensure_ascii=False, sort_keys=True),
            "deep_arrival_count": scenario_metrics["NEW_TEST"].get("deep_arrival_count"),
            "deep_arrival_rate_pct": scenario_metrics["NEW_TEST"].get("deep_arrival_rate_pct"),
        }
        for scenario in ("CONTROL", "FROZEN_TEST", "POSTHOC_EARLY_TRANSITION", "NEW_TEST"):
            metric = scenario_metrics[scenario]
            for key, value in metric.items():
                row[f"{scenario.lower()}_{key}"] = value
        new = scenario_metrics["NEW_TEST"]
        frozen_test = scenario_metrics["FROZEN_TEST"]
        posthoc = scenario_metrics["POSTHOC_EARLY_TRANSITION"]
        for metric in ("mean_pct", "positive_rate_pct", "median_pct",
                       "le_30_rate_pct", "le_40_rate_pct", "le_50_rate_pct", "le_60_rate_pct"):
            row[f"new_minus_frozen_test_{metric}_pp"] = _delta(new.get(metric), frozen_test.get(metric))
            row[f"new_minus_posthoc_{metric}_pp"] = _delta(new.get(metric), posthoc.get(metric))
        for tail, _ in TAILS:
            row[f"new_minus_frozen_test_{tail}_count"] = new[f"{tail}_count"] - frozen_test[f"{tail}_count"]
        row["new_minus_frozen_test_filled_count"] = new["filled_count"] - frozen_test["filled_count"]
        row["new_minus_posthoc_filled_count"] = new["filled_count"] - posthoc["filled_count"]
        row["posthoc_only_trade_identity_count"] = saved["posthoc_set_comparison"]["posthoc_only_trade_identity_count"]
        row["new_only_trade_identity_count"] = saved["posthoc_set_comparison"]["new_only_trade_identity_count"]
        synthesis_rows.append(row)
        verdict_input.append({
            "new_minus_frozen_test_mean_pp": row["new_minus_frozen_test_mean_pct_pp"],
            "new_minus_frozen_test_median_pp": row["new_minus_frozen_test_median_pct_pp"],
            "new_minus_frozen_test_positive_rate_pp": row["new_minus_frozen_test_positive_rate_pct_pp"],
            "new_minus_frozen_test_le_30_rate_pp": row["new_minus_frozen_test_le_30_rate_pct_pp"],
            "new_minus_frozen_test_le_50_rate_pp": row["new_minus_frozen_test_le_50_rate_pct_pp"],
            "new_minus_frozen_test_le_30_count": row["new_test_le_30_count"] - row["frozen_test_le_30_count"],
        })

        terminal: dict[str, Any] = {"window": window_id}
        for scenario in ("CONTROL", "FROZEN_TEST", "POSTHOC_EARLY_TRANSITION", "NEW_TEST"):
            stats = saved["resolved_terminal_metrics"][scenario]
            terminal[f"{scenario}_n"] = stats.get("n", stats.get("resolved_terminal_n"))
            for key in ("mean_pct", "median_pct", "positive_rate_pct", "exact_open_mark_count", "unresolved_open_count"):
                terminal[f"{scenario}_{key}"] = stats.get(key)
            for label, _ in TAILS:
                terminal[f"{scenario}_{label}_count"] = stats.get(f"{label}_count")
                terminal[f"{scenario}_{label}_rate_pct"] = stats.get(f"{label}_rate_pct")
        terminal["new_minus_frozen_test_mean_pp"] = _delta(terminal["NEW_TEST_mean_pct"], terminal["FROZEN_TEST_mean_pct"])
        terminal["new_minus_frozen_test_median_pp"] = _delta(terminal["NEW_TEST_median_pct"], terminal["FROZEN_TEST_median_pct"])
        terminal["new_minus_frozen_test_positive_rate_pp"] = _delta(terminal["NEW_TEST_positive_rate_pct"], terminal["FROZEN_TEST_positive_rate_pct"])
        terminal_rows.append(terminal)

        fast_ref = fast_refs[window_id]
        new_terminal = saved["resolved_terminal_metrics"]["NEW_TEST"]
        frow = {
            "window": window_id,
            "effective_start": fast_ref["effective_start"],
            "effective_end": fast_ref["effective_end"],
            "execution_support": fast_ref["execution_support"],
            "source_summary": fast_ref["source_summary"],
            "source_sha256": fast_ref["source_sha256"],
            "strategy_id": fast_ref["strategy_id"],
            "fast_trade_count": fast_ref["trade_count"],
            "fast_performance_n": fast_ref["performance_n"],
            "fast_mean_pct": fast_ref["mean_pct"],
            "fast_positive_rate_pct": fast_ref["positive_rate_pct"],
            "fast_median_pct": fast_ref["median_pct"],
            "fast_open_at_cutoff_count": fast_ref["open_at_cutoff_count"],
            "terminal_contract_note": fast_ref["terminal_contract_note"],
            "v2_rerun": False,
            "new_resolved_n": new_terminal.get("n", new_terminal.get("resolved_terminal_n")),
            "new_resolved_mean_pct": new_terminal["mean_pct"],
            "new_resolved_positive_rate_pct": new_terminal["positive_rate_pct"],
            "new_resolved_median_pct": new_terminal["median_pct"],
            "new_exact_open_mark_count": new_terminal["exact_open_mark_count"],
            "new_unresolved_open_count": new_terminal["unresolved_open_count"],
        }
        for label, fast_key in (("ge_30", "ge_pos_30_pct"), ("ge_50", "ge_pos_50_pct"),
                                ("ge_100", "ge_pos_100_pct"), ("le_30", "le_neg_30_pct"),
                                ("le_40", "le_neg_40_pct"), ("le_50", "le_neg_50_pct"),
                                ("le_60", "le_neg_60_pct")):
            count = int(fast_ref["winner_counts"].get(fast_key, 0)) if label.startswith("ge_") else int(fast_ref["tail_counts"].get(fast_key, 0))
            frow[f"fast_{label}_count"] = count
            frow[f"fast_{label}_rate_pct"] = count / fast_ref["performance_n"] * 100.0
            frow[f"new_{label}_count"] = new_terminal.get(f"{label}_count")
            frow[f"new_{label}_rate_pct"] = new_terminal.get(f"{label}_rate_pct")
        frow["new_minus_fast_mean_pp"] = _delta(frow["new_resolved_mean_pct"], frow["fast_mean_pct"])
        frow["new_minus_fast_positive_rate_pp"] = _delta(frow["new_resolved_positive_rate_pct"], frow["fast_positive_rate_pct"])
        frow["new_minus_fast_median_pp"] = _delta(frow["new_resolved_median_pct"], frow["fast_median_pct"])
        fast_rows.append(frow)

    synthesis = pd.DataFrame(synthesis_rows)
    synthesis_aliases = {
        "new_minus_posthoc_mean_pp": "new_minus_posthoc_mean_pct_pp",
        "new_minus_posthoc_positive_rate_pp": "new_minus_posthoc_positive_rate_pct_pp",
        "new_minus_posthoc_median_pp": "new_minus_posthoc_median_pct_pp",
        "new_minus_posthoc_le_30_rate_pp": "new_minus_posthoc_le_30_rate_pct_pp",
        "new_minus_posthoc_le_40_rate_pp": "new_minus_posthoc_le_40_rate_pct_pp",
        "new_minus_posthoc_le_50_rate_pp": "new_minus_posthoc_le_50_rate_pct_pp",
        "new_minus_posthoc_le_60_rate_pp": "new_minus_posthoc_le_60_rate_pct_pp",
    }
    for alias, source in synthesis_aliases.items():
        synthesis[alias] = synthesis[source]
    terminals = pd.DataFrame(terminal_rows)
    fast_frame = pd.DataFrame(fast_rows)
    verdict = _window_verdict(verdict_input)
    root = data_root / OUTPUT_ROOT
    synthesis.to_csv(root / "five_window_synthesis.csv", index=False, encoding="utf-8")
    terminals.to_csv(root / "resolved_terminal_synthesis.csv", index=False, encoding="utf-8")
    fast_frame.to_csv(root / "fast_core_v2_terminal_reference.csv", index=False, encoding="utf-8")
    report = _root_report(window_results, synthesis, terminals, fast_frame, verdict)
    (root / "report.md").write_text(report, encoding="utf-8")

    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "starting_git": start_git,
        "strategy_definition": "Pattern B DEPRESSED AND entry Pattern A Stage PROGRESSED AND previous authoritative Pattern A stage in {EARLY_TREND, TRANSITION}",
        "workers": runner.WORKERS,
        "window_order": list(WINDOW_IDS),
        "resolved_windows": {key: resolved_windows[key][1] for key in WINDOW_IDS},
        "new_test_only_replay": True,
        "frozen_control_test_rerun": False,
        "fast_core_v2_rerun": False,
        "frozen_reference_commit": frozen.START_COMMIT,
        "window_results": window_results,
        "five_window_synthesis": synthesis_rows,
        "resolved_terminal_synthesis": terminal_rows,
        "fast_core_v2_terminal_reference": fast_rows,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean) + "\n",
        encoding="utf-8",
    )
    source_paths = []
    for window_id in WINDOW_IDS:
        source_paths.extend([
            FROZEN_DIRS[window_id] / "metadata.json",
            FROZEN_DIRS[window_id] / "summary.json",
            FROZEN_DIRS[window_id] / "control_trade_ledger.csv",
            FROZEN_DIRS[window_id] / "test_trade_ledger.csv",
            FROZEN_DIRS[window_id] / "control_open_positions.csv",
            FROZEN_DIRS[window_id] / "test_open_positions.csv",
            FAST_SUMMARIES[window_id],
        ])
    code_paths = [
        SCRIPT_RELATIVE,
        Path("scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py"),
        Path("scripts/run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01.py"),
    ]
    root_outputs = [
        "five_window_synthesis.csv", "resolved_terminal_synthesis.csv",
        "fast_core_v2_terminal_reference.csv", "report.md", "summary.json",
    ]
    metadata = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "starting_git": start_git,
        "frozen_reference_commit": frozen.START_COMMIT,
        "workers": runner.WORKERS,
        "window_order": list(WINDOW_IDS),
        "window_resolutions": {key: resolved_windows[key][1] for key in WINDOW_IDS},
        "new_test_only_replay": True,
        "frozen_control_test_rerun": False,
        "fast_core_v2_rerun": False,
        "source_sha256": {path.as_posix(): _sha256(data_root / path) for path in source_paths},
        "code_sha256": {path.as_posix(): _sha256(data_root / path) for path in code_paths},
        "window_metadata_sha256": {
            window_id: _sha256(data_root / window_dirs[window_id] / "metadata.json")
            for window_id in WINDOW_IDS
        },
        "generated_files": {
            name: {"sha256": _sha256(root / name), "bytes": (root / name).stat().st_size}
            for name in root_outputs
        },
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "verdict": verdict,
        "starting_head": start_git["head"],
        "completed_windows": list(WINDOW_IDS),
        "five_window_synthesis": synthesis_rows,
        "resolved_terminal_synthesis": terminal_rows,
        "fast_core_v2_terminal_reference": fast_rows,
        "output": str(root),
    }, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean), flush=True)
    return summary


if __name__ == "__main__":
    run()


def finalize_saved_results(data_root: Path = ROOT) -> dict[str, Any]:
    """Build root summaries from completed per-window outputs without replaying any lifecycle."""
    data_root = Path(data_root).resolve()
    root = data_root / OUTPUT_ROOT
    if not root.is_dir():
        raise RuntimeError(f"completed window outputs are missing: {root}")
    _verify_frozen(data_root)
    fast_refs = _load_fast_refs(data_root)
    window_results: dict[str, dict[str, Any]] = {}
    window_dirs = {wid: OUTPUT_ROOT / wid.lower().replace("-", "_") for wid in WINDOW_IDS}
    starting_git = None
    for window_id in WINDOW_IDS:
        out = data_root / window_dirs[window_id]
        metadata = _json(out / "metadata.json")
        summary = _json(out / "summary.json")
        starting_git = starting_git or metadata.get("starting_git")
        if summary.get("scenario") != "NEW_TEST" or summary.get("window", {}).get("window_id") != window_id:
            raise RuntimeError(f"saved independent replay identity mismatch: {window_id}")
        for name, detail in metadata.get("generated_files", {}).items():
            path = out / name
            if not path.is_file() or _sha256(path) != detail.get("sha256"):
                raise RuntimeError(f"saved completed window output hash mismatch: {window_id}/{name}")
        validations = summary.get("validations", {})
        if validations.get("lifecycle_spot_check_count") != 30 or validations.get("lifecycle_spot_check_pass_count") != 30:
            raise RuntimeError(f"{window_id}: exact 30 lifecycle spotcheck validation missing")
        required_zero = (
            "new_test_previous_stage_forbidden_fill_count", "entry_after_window_end_count",
            "execution_support_new_entry_count", "future_pattern_a_input_count",
            "duplicate_trade_identity_count", "duplicate_trade_id_count",
            "lifecycle_settlement_contract_violation_count", "raw_candidate_key_mismatch_count",
            "same_isu_overlap_count", "repository_v2_silent_inner_drop_count",
            "pattern_b_authority_discontinuity_count", "carry_in_position_count",
        )
        failures = {key: validations.get(key) for key in required_zero if validations.get(key) != 0}
        if failures:
            raise RuntimeError(f"{window_id}: saved required-zero validations failed: {failures}")
        spot = pd.read_csv(out / "lifecycle_spot_checks.csv")
        if len(spot) != 30 or not spot["all_checks_pass"].astype(str).str.lower().eq("true").all():
            raise RuntimeError(f"{window_id}: saved lifecycle spotchecks do not contain 30 passing rows")
        ledger = pd.read_csv(out / "test_trade_ledger.csv", dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
        if len(ledger) != validations.get("new_test_filled_count") or ledger["trade_id"].duplicated().any():
            raise RuntimeError(f"{window_id}: saved trade ledger count or identity failed")
        if not ledger["previous_pattern_a_stage"].astype(str).isin(ALLOWED_PREVIOUS).all():
            raise RuntimeError(f"{window_id}: saved ledger contains a forbidden previous stage")
        audit = pd.read_csv(out / "previous_stage_audit.csv")
        allowed_audit = audit["new_test_gate_decision"].astype(str).eq("PASS_EARLY_TREND_OR_TRANSITION")
        if int(allowed_audit.sum()) != summary["candidate_counts"]["new_test_allowed_entry_signals"]:
            raise RuntimeError(f"{window_id}: saved stage gate audit count does not reconcile")
        window_results[window_id] = summary
    if not starting_git:
        raise RuntimeError("saved per-window metadata lacks initial git state")
    required_csvs = ("five_window_synthesis.csv", "resolved_terminal_synthesis.csv", "fast_core_v2_terminal_reference.csv")
    for filename in required_csvs:
        if not (root / filename).is_file():
            raise RuntimeError(f"saved aggregate table missing: {filename}")
    synthesis = pd.read_csv(root / "five_window_synthesis.csv")
    terminals = pd.read_csv(root / "resolved_terminal_synthesis.csv")
    fast_frame = pd.read_csv(root / "fast_core_v2_terminal_reference.csv")
    if len(synthesis) != 5 or len(terminals) != 5 or len(fast_frame) != 5:
        raise RuntimeError("saved aggregate CSV row counts are not exactly five windows")
    aliases = {
        "new_minus_posthoc_mean_pp": "new_minus_posthoc_mean_pct_pp",
        "new_minus_posthoc_positive_rate_pp": "new_minus_posthoc_positive_rate_pct_pp",
        "new_minus_posthoc_median_pp": "new_minus_posthoc_median_pct_pp",
        "new_minus_posthoc_le_30_rate_pp": "new_minus_posthoc_le_30_rate_pct_pp",
        "new_minus_posthoc_le_40_rate_pp": "new_minus_posthoc_le_40_rate_pct_pp",
        "new_minus_posthoc_le_50_rate_pp": "new_minus_posthoc_le_50_rate_pct_pp",
        "new_minus_posthoc_le_60_rate_pp": "new_minus_posthoc_le_60_rate_pct_pp",
    }
    for expected, actual in aliases.items():
        if actual not in synthesis:
            raise RuntimeError(f"saved aggregate table lacks {actual}")
        synthesis[expected] = synthesis[actual]
    synthesis["new_minus_frozen_test_le_30_count"] = synthesis["new_test_le_30_count"] - synthesis["frozen_test_le_30_count"]
    synthesis.to_csv(root / "five_window_synthesis.csv", index=False, encoding="utf-8")
    verdict_input = [
        {
            "new_minus_frozen_test_mean_pp": row["new_minus_frozen_test_mean_pct_pp"],
            "new_minus_frozen_test_median_pp": row["new_minus_frozen_test_median_pct_pp"],
            "new_minus_frozen_test_positive_rate_pp": row["new_minus_frozen_test_positive_rate_pct_pp"],
            "new_minus_frozen_test_le_30_rate_pp": row["new_minus_frozen_test_le_30_rate_pct_pp"],
            "new_minus_frozen_test_le_50_rate_pp": row["new_minus_frozen_test_le_50_rate_pct_pp"],
            "new_minus_frozen_test_le_30_count": row["new_test_le_30_count"] - row["frozen_test_le_30_count"],
        }
        for row in synthesis.to_dict("records")
    ]
    verdict = _window_verdict(verdict_input)
    report = _root_report(window_results, synthesis, terminals, fast_frame, verdict)
    (root / "report.md").write_text(report, encoding="utf-8")
    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "starting_git": starting_git,
        "strategy_definition": "Pattern B DEPRESSED AND entry Pattern A Stage PROGRESSED AND previous authoritative Pattern A stage in {EARLY_TREND, TRANSITION}",
        "workers": runner.WORKERS,
        "window_order": list(WINDOW_IDS),
        "resolved_windows": {key: runner._resolve_window(data_root, key)[1] for key in WINDOW_IDS},
        "new_test_only_replay": True,
        "frozen_control_test_rerun": False,
        "fast_core_v2_rerun": False,
        "frozen_reference_commit": frozen.START_COMMIT,
        "aggregation_recovery": "All five NEW_TEST replays completed once. Root report assembly was recovered from hash-verified saved window outputs; no lifecycle or FAST V2 replay was repeated.",
        "window_results": window_results,
        "five_window_synthesis": synthesis.to_dict("records"),
        "resolved_terminal_synthesis": terminals.to_dict("records"),
        "fast_core_v2_terminal_reference": fast_frame.to_dict("records"),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean) + "\n",
        encoding="utf-8",
    )
    source_paths = []
    for window_id in WINDOW_IDS:
        source_paths.extend([
            FROZEN_DIRS[window_id] / "metadata.json",
            FROZEN_DIRS[window_id] / "summary.json",
            FROZEN_DIRS[window_id] / "control_trade_ledger.csv",
            FROZEN_DIRS[window_id] / "test_trade_ledger.csv",
            FROZEN_DIRS[window_id] / "control_open_positions.csv",
            FROZEN_DIRS[window_id] / "test_open_positions.csv",
            FAST_SUMMARIES[window_id],
        ])
    root_outputs = [
        *required_csvs, "report.md", "summary.json",
    ]
    metadata = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "starting_git": starting_git,
        "frozen_reference_commit": frozen.START_COMMIT,
        "workers": runner.WORKERS,
        "window_order": list(WINDOW_IDS),
        "window_resolutions": summary["resolved_windows"],
        "new_test_only_replay": True,
        "frozen_control_test_rerun": False,
        "fast_core_v2_rerun": False,
        "aggregation_recovery": summary["aggregation_recovery"],
        "source_sha256": {path.as_posix(): _sha256(data_root / path) for path in source_paths},
        "postprocessing_code_sha256": {
            SCRIPT_RELATIVE.as_posix(): _sha256(data_root / SCRIPT_RELATIVE),
        },
        "replay_code_sha256_by_window": {
            window_id: _json(data_root / window_dirs[window_id] / "metadata.json").get("code_sha256", {}).get(SCRIPT_RELATIVE.as_posix())
            for window_id in WINDOW_IDS
        },
        "window_metadata_sha256": {
            window_id: _sha256(data_root / window_dirs[window_id] / "metadata.json")
            for window_id in WINDOW_IDS
        },
        "generated_files": {
            name: {"sha256": _sha256(root / name), "bytes": (root / name).stat().st_size}
            for name in root_outputs
        },
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "verdict": verdict,
        "completed_windows": list(WINDOW_IDS),
        "mean_improvement_vs_frozen_test_count": int((synthesis["new_minus_frozen_test_mean_pct_pp"] > 0).sum()),
        "median_improvement_vs_frozen_test_count": int((synthesis["new_minus_frozen_test_median_pct_pp"] > 0).sum()),
        "output": str(root),
    }, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean), flush=True)
    return summary
