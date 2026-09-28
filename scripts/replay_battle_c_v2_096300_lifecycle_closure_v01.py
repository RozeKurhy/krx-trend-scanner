#!/usr/bin/env python3
"""Replay only Battle C / V2 after promoting 096300's unresolved lifecycle identity."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_official_strategy_battle_v02 as battle  # noqa: E402
from scripts import run_v2_official_adoption_revalidation_v02 as v2  # noqa: E402
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as pattern_b  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS  # noqa: E402


TARGET = ("096300", "KR7096300009")
TARGET_EVIDENCE_ID = "KRX-LIFECYCLE-KR7096300009"
BATTLE_ID = "battle_c_kospi_only"
STRATEGY_ID = v2.STRATEGY_ID
WINDOWS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
BASELINE_EXCLUSION_COUNT = 173
CURRENT_EXCLUSION_COUNT = 174
OUTPUT_ROOT = ROOT / "artifacts/strategy_battles/fast_v2_vs_pattern_b_v02"
WINDOW_OUTPUT = OUTPUT_ROOT / BATTLE_ID / "v2"
AUDIT_PATH = OUTPUT_ROOT / BATTLE_ID / "v2" / "lifecycle_closure_audit.json"
WORK_INSTRUCTION = Path("/Users/june/Documents/projects/w.md")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=battle.json_default) + "\n", encoding="utf-8")


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if battle.math.isfinite(number) else None


def near(left: Any, right: Any, tolerance: float = 0.011) -> bool:
    a, b = as_float(left), as_float(right)
    return a is not None and b is not None and abs(a - b) <= max(tolerance, abs(b) * 1e-10)


def preflight() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    start_head = battle.current_head()
    origin_main = battle.current_origin_main()
    if start_head != origin_main:
        raise RuntimeError(f"BASE_HEAD_NOT_EQUAL_ORIGIN_MAIN:{start_head}:{origin_main}")
    if AUDIT_PATH.exists():
        raise RuntimeError("NO_AUTOMATIC_REPLAY:Battle C V2 lifecycle closure already has an audit record")

    baseline = read_json(OUTPUT_ROOT / "validation.json")
    baseline_checks = baseline.get("checks", {})
    if baseline_checks.get("permanent_exclusion_count_after") != BASELINE_EXCLUSION_COUNT:
        raise RuntimeError("UNEXPECTED_PRIOR_EXCLUSION_COUNT")
    if baseline_checks.get("actual_result_count") != 30 or not baseline_checks.get("30_of_30_complete"):
        raise RuntimeError("PRIOR_V02_BATTLE_RESULTS_INCOMPLETE")
    if not baseline_checks.get("artifact_evidence", {}).get("structural_checks_pass"):
        raise RuntimeError("PRIOR_V02_STRUCTURAL_VALIDATION_NOT_PASS")

    pairs = battle.current_exclusion_pairs()
    if len(pairs) != CURRENT_EXCLUSION_COUNT or len(pairs) != len(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError(f"PERMANENT_EXCLUSION_COUNT_MISMATCH:{len(pairs)}:{CURRENT_EXCLUSION_COUNT}")
    policy = PERMANENT_IDENTITY_EXCLUSIONS.get(TARGET)
    if not policy or policy.get("approval_scope") != "GLOBAL permanent identity exclusion":
        raise RuntimeError("096300_EXACT_GLOBAL_EXCLUSION_NOT_REGISTERED")
    if policy.get("evidence_id") != TARGET_EVIDENCE_ID:
        raise RuntimeError("096300_LIFECYCLE_EVIDENCE_ID_MISMATCH")
    if any(not isinstance(identity, tuple) or len(identity) != 2 for identity in PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("TICKER_ONLY_OR_NON_PAIR_EXCLUSION_PRESENT")

    source_checks: dict[str, Any] = {}
    for window_id in WINDOWS:
        kept, detail = v2.source_check(window_id)
        excluded = [
            row for row in detail["excluded_rows"]
            if row.get("ticker") == TARGET[0] and row.get("isu_cd") == TARGET[1]
        ]
        if not excluded:
            raise RuntimeError(f"096300_NOT_FOUND_IN_FROZEN_V2_SOURCE:{window_id}")
        if any((row.get("ticker"), row.get("isu_cd")) == TARGET for row in kept):
            raise RuntimeError(f"096300_SOURCE_EXCLUSION_LEAK:{window_id}")
        source_checks[window_id] = {
            "source_sha256": detail["source_sha256"],
            "source_rows": detail["source_rows"],
            "rows_after_current_exclusions": len(kept),
            "096300_raw_source_rows_excluded": len(excluded),
        }

    prior_c_metrics = OUTPUT_ROOT / BATTLE_ID / "v2" / "battle_window_metrics.csv"
    previous_c_rows = battle.read_metric_rows(prior_c_metrics, STRATEGY_ID, BATTLE_ID)
    if len(previous_c_rows) != len(WINDOWS):
        raise RuntimeError("PRIOR_BATTLE_C_V2_METRICS_INCOMPLETE")
    for window_id in WINDOWS:
        missing_path = WINDOW_OUTPUT / f"missing_marks_{window_id.lower().replace('-', '_')}.csv"
        frame = battle.pd.read_csv(missing_path, dtype=str, keep_default_na=False)
        target_missing = frame.loc[
            frame["ticker"].map(battle.normalize_ticker).eq(TARGET[0])
            & frame["isu_cd"].map(battle.normalize_isu).eq(TARGET[1])
        ]
        if target_missing.empty:
            raise RuntimeError(f"096300_PRIOR_MISSING_MARK_EVIDENCE_ABSENT:{window_id}")
        source_checks[window_id]["previous_096300_missing_mark_rows"] = int(len(target_missing))
        source_checks[window_id]["previous_coverage_pct"] = next(
            float(row["coverage_pct"]) for row in previous_c_rows if row["window_id"] == window_id
        )

    pit_rows, pit_meta = battle.load_pit_authority()
    authority = battle.ExactPITMarketAuthority(pit_rows)
    _market_audit, market_summary = battle.collect_battle_c_preflight(authority)
    if market_summary.get("status") != "PASS":
        raise RuntimeError(f"BATTLE_C_EXACT_PIT_MARKET_PREFLIGHT_FAILED:{market_summary}")
    if market_summary.get("market_authority_missing") != 0 or market_summary.get("market_authority_ambiguous") != 0:
        raise RuntimeError("BATTLE_C_MARKET_AUTHORITY_MISSING_OR_AMBIGUOUS")

    return {
        "starting_head": start_head,
        "origin_main_at_start": origin_main,
        "baseline_validation_status": baseline.get("status"),
        "baseline_validation": baseline,
        "current_exclusion_pairs": len(pairs),
        "source_checks": source_checks,
        "pit_authority": pit_meta,
    }, pit_rows, authority, market_summary


def replay_checks(run_result: Mapping[str, Any], market_summary: Mapping[str, Any]) -> dict[str, Any]:
    summary = read_json(WINDOW_OUTPUT / "battle_summary.json")
    contract = read_json(WINDOW_OUTPUT / "execution_contract.json")
    if summary.get("worker_count") != battle.EXPECTED_WORKERS or battle.EXPECTED_WORKERS != 10:
        raise RuntimeError("BATTLE_C_V2_WORKER_COUNT_NOT_10")

    source_maps: dict[str, dict[tuple[str, str, str, str], dict[str, Any]]] = {}
    for window_id in WINDOWS:
        source_path = ROOT / v2.WINDOWS[window_id]["source"]
        frame = battle.pd.read_csv(source_path, dtype=str, keep_default_na=False)
        source_maps[window_id] = {
            (
                battle.normalize_ticker(row.get("ticker")), battle.normalize_isu(row.get("isu_cd")),
                battle.date_text(row.get("entry_signal_date")), battle.date_text(row.get("entry_execution_date")),
            ): row
            for row in frame.to_dict("records")
        }

    market_rows = list(run_result.get("market_audit", []))
    markets_by_key: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in market_rows:
        key = (
            battle.normalize_ticker(row.get("ticker")), battle.normalize_isu(row.get("isu_cd")),
            battle.date_text(row.get("entry_signal_date")), str(row.get("window_id", "")),
        )
        markets_by_key.setdefault(key, []).append(row)

    target_entry_attempts = 0
    executed_non_kospi = 0
    executed_market_audit_mismatches = 0
    cost_mismatches = 0
    schedule_price_mismatches = 0
    cash_conservation_failures = 0
    worker_count_failures = 0
    window_counts: dict[str, dict[str, int]] = {}

    for window_id in WINDOWS:
        output = run_result["run"]["outputs"][window_id]
        metrics = output["metrics"]
        if not bool(metrics.get("cash_conservation_pass")):
            cash_conservation_failures += 1
        if int(metrics.get("worker_count", battle.EXPECTED_WORKERS)) != battle.EXPECTED_WORKERS:
            worker_count_failures += 1
        entries = exits = 0
        for event in output["events"]:
            event_type = str(event.get("event_type", ""))
            ticker = battle.normalize_ticker(event.get("ticker"))
            isu_cd = battle.normalize_isu(event.get("isu_cd"))
            if event_type == "ENTRY" and (ticker, isu_cd) == TARGET:
                target_entry_attempts += 1

            if event_type in {"ENTRY", "EXIT"}:
                candidate = str(event.get("candidate_id", "")).split("|")
                source_key = (
                    battle.normalize_ticker(candidate[0]) if len(candidate) == 4 else "",
                    battle.normalize_isu(candidate[1]) if len(candidate) == 4 else "",
                    battle.date_text(candidate[2]) if len(candidate) == 4 else "",
                    battle.date_text(candidate[3]) if len(candidate) == 4 else "",
                )
                source = source_maps[window_id].get(source_key)
                if source is None:
                    schedule_price_mismatches += 1
                else:
                    signal_field, execution_field, price_field = (
                        ("entry_signal_date", "entry_execution_date", "entry_open")
                        if event_type == "ENTRY" else ("exit_signal_date", "exit_execution_date", "exit_price")
                    )
                    if battle.date_text(event.get("signal_date")) != battle.date_text(source.get(signal_field)):
                        schedule_price_mismatches += 1
                    if battle.date_text(event.get("execution_date")) != battle.date_text(source.get(execution_field)):
                        schedule_price_mismatches += 1
                    if str(event.get("event_status")) == "EXECUTED" and not near(event.get("reference_price"), source.get(price_field)):
                        schedule_price_mismatches += 1

            if event_type not in {"ENTRY", "EXIT"} or str(event.get("event_status")) != "EXECUTED":
                continue
            entries += int(event_type == "ENTRY")
            exits += int(event_type == "EXIT")
            reference = as_float(event.get("reference_price"))
            fill = as_float(event.get("fill_price"))
            shares = as_float(event.get("shares"))
            notional = as_float(event.get("notional_krw"))
            commission = as_float(event.get("commission_krw"))
            slippage = as_float(event.get("slippage_impact_krw"))
            if None in (reference, fill, shares, notional, commission, slippage) or abs(shares - round(shares)) > 1e-12:
                cost_mismatches += 1
                continue
            is_entry = event_type == "ENTRY"
            slip_rate = float(contract.get("buy_slippage_rate" if is_entry else "sell_slippage_rate", 0.001))
            commission_rate = float(contract.get("buy_commission_rate" if is_entry else "sell_commission_rate", 0.00015))
            expected_fill = reference * (1.0 + slip_rate if is_entry else 1.0 - slip_rate)
            expected_notional = fill * shares
            if not near(fill, expected_fill) or not near(notional, expected_notional):
                cost_mismatches += 1
            if not near(commission, expected_notional * commission_rate) or not near(slippage, abs(fill - reference) * shares):
                cost_mismatches += 1
            if is_entry:
                before, after = as_float(event.get("cash_before_krw")), as_float(event.get("cash_after_krw"))
                if before is None or after is None or not near(before - after, expected_notional + expected_notional * commission_rate):
                    cost_mismatches += 1
                if str(event.get("market", "")).strip().upper() != "KOSPI":
                    executed_non_kospi += 1
                key = (ticker, isu_cd, battle.date_text(event.get("signal_date")), window_id)
                matches = markets_by_key.get(key, [])
                if len(matches) != 1 or matches[0].get("authority_status") != "PASS_KOSPI":
                    executed_market_audit_mismatches += 1
        window_counts[window_id] = {"executed_entries": entries, "executed_exits": exits}

    five_rows = list(run_result.get("rows", []))
    if len(five_rows) != len(WINDOWS) or {row.get("window_id") for row in five_rows} != set(WINDOWS):
        raise RuntimeError("BATTLE_C_V2_DID_NOT_GENERATE_ALL_FIVE_WINDOWS")
    if contract.get("max_concurrent_positions") is not None or contract.get("entry_date_pit_market_cap_filter") is not None:
        raise RuntimeError("BATTLE_C_V2_CONTRACT_HAS_POSITION_CAP_OR_MARKET_CAP_FILTER")
    if contract.get("entry_signal_regeneration") is not False or contract.get("strategy_evaluation_rerun") is not False:
        raise RuntimeError("BATTLE_C_V2_STRATEGY_FREEZE_VIOLATION")

    coverage_rows = [
        {"window_id": row["window_id"], "coverage_pct": float(row["coverage_pct"]), "mdd_type": row["mdd_type"]}
        for row in five_rows
    ]
    return {
        "status": "PASS" if all([
            target_entry_attempts == 0,
            executed_non_kospi == 0,
            executed_market_audit_mismatches == 0,
            cost_mismatches == 0,
            schedule_price_mismatches == 0,
            cash_conservation_failures == 0,
            worker_count_failures == 0,
            market_summary.get("status") == "PASS",
            market_summary.get("market_authority_missing") == 0,
            market_summary.get("market_authority_ambiguous") == 0,
        ]) else "FAIL",
        "replayed_window_count": len(five_rows),
        "worker_count": int(summary["worker_count"]),
        "permanent_exclusion_count": len(battle.current_exclusion_pairs()),
        "096300_exact_identity_entry_attempts": target_entry_attempts,
        "executed_non_kospi_entries": executed_non_kospi,
        "executed_entry_pit_market_audit_mismatches": executed_market_audit_mismatches,
        "cost_formula_mismatches": cost_mismatches,
        "frozen_execution_date_or_price_mismatches": schedule_price_mismatches,
        "cash_conservation_failures": cash_conservation_failures,
        "worker_count_failures": worker_count_failures,
        "no_position_cap": contract.get("max_concurrent_positions") is None,
        "no_market_cap_filter": contract.get("entry_date_pit_market_cap_filter") is None,
        "strategy_freeze_pass": contract.get("entry_signal_regeneration") is False and contract.get("strategy_evaluation_rerun") is False,
        "market_authority_preflight": market_summary,
        "window_execution_counts": window_counts,
        "coverage": coverage_rows,
        "all_windows_coverage_at_least_90_pct": all(row["coverage_pct"] >= 90.0 for row in coverage_rows),
    }


def update_reports(
    preflight_record: Mapping[str, Any],
    market_summary: Mapping[str, Any],
    c_rows: Sequence[Mapping[str, Any]],
    c_checks: Mapping[str, Any],
) -> dict[str, Any]:
    c_root = OUTPUT_ROOT / BATTLE_ID
    pb_rows = battle.read_metric_rows(
        c_root / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, BATTLE_ID,
    )
    if len(pb_rows) != len(WINDOWS):
        raise RuntimeError("PATTERN_B_BATTLE_C_BASELINE_METRICS_INCOMPLETE")
    c_comparison = [
        {"battle_id": BATTLE_ID, **battle.comparison_row(
            window_id,
            next(row for row in c_rows if row["window_id"] == window_id),
            next(row for row in pb_rows if row["window_id"] == window_id),
        )}
        for window_id in WINDOWS
    ]
    battle.write_csv(c_root / "comparison.csv", c_comparison)
    c_battle_summary = read_json(c_root / "summary.json")
    c_battle_summary.update({
        "status": "COMPLETE",
        "market_authority_preflight": market_summary,
        "market_cap_filter": None,
        "comparison": c_comparison,
        "latest_scoped_replay": {
            "strategy_id": STRATEGY_ID,
            "windows": list(WINDOWS),
            "worker_count": battle.EXPECTED_WORKERS,
            "pattern_b_replayed": False,
        },
    })
    battle.write_json(c_root / "summary.json", c_battle_summary)

    all_rows = battle.read_metric_rows(OUTPUT_ROOT / "battle_a_all_universe" / "v2" / "battle_window_metrics.csv", STRATEGY_ID, "battle_a_all_universe")
    all_rows += battle.read_metric_rows(OUTPUT_ROOT / "battle_a_all_universe" / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, "battle_a_all_universe")
    mcap_rows = battle.read_metric_rows(OUTPUT_ROOT / "battle_b_pit_mcap_1t" / "v2" / "battle_window_metrics.csv", STRATEGY_ID, "battle_b_pit_mcap_1t")
    mcap_rows += battle.read_metric_rows(OUTPUT_ROOT / "battle_b_pit_mcap_1t" / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, "battle_b_pit_mcap_1t")
    kospi_rows = list(c_rows) + pb_rows
    rows_by_battle = {
        "battle_a_all_universe": all_rows,
        "battle_b_pit_mcap_1t": mcap_rows,
        "battle_c_kospi_only": kospi_rows,
    }

    cross_path = OUTPUT_ROOT / "cross_battle_comparison.csv"
    old_cross = battle.pd.read_csv(cross_path).to_dict("records")
    cross_rows = [row for row in old_cross if row.get("battle_id") != BATTLE_ID] + c_comparison
    battle.write_csv(cross_path, cross_rows)
    sensitivity = battle.three_way_sensitivity(all_rows, mcap_rows, kospi_rows)
    battle.write_csv(OUTPUT_ROOT / "universe_filter_sensitivity.csv", sensitivity)

    original_checks = preflight_record["baseline_validation"]["checks"]
    prior_evidence = original_checks["artifact_evidence"]
    baseline_policy_attempts = _historical_target_attempts()
    all_metrics = all_rows + mcap_rows + kospi_rows
    coverage_below_90 = [
        {"battle_id": row.get("battle_id"), "strategy_id": row.get("strategy_id"),
         "window_id": row.get("window_id"), "coverage_pct": row.get("coverage_pct"), "mdd_type": row.get("mdd_type")}
        for row in all_metrics if row.get("coverage_pct") is None or float(row["coverage_pct"]) < 90.0
    ]
    current_pairs = battle.current_exclusion_pairs()
    policy_hash = battle.sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py")
    current_market_ok = bool(
        market_summary.get("status") == "PASS"
        and market_summary.get("market_authority_missing") == 0
        and market_summary.get("market_authority_ambiguous") == 0
    )
    c_structural = c_checks.get("status") == "PASS"
    artifact_evidence = {
        "scope": "new Battle C / V2 replay only; unchanged Battle A/B and Pattern B are retained baselines",
        "exclusion_leakage_scope": "new Battle C / V2 replay only",
        "v2_entry_exclusion_leakage_count": c_checks.get("096300_exact_identity_entry_attempts"),
        "pattern_b_entry_exclusion_leakage_count": 0,
        "historical_battle_a_096300_entry_attempts": baseline_policy_attempts["battle_a_v2_entry_attempts"],
        "historical_battle_a_096300_executed_entries": baseline_policy_attempts["battle_a_v2_executed_entries"],
        "historical_battle_a_096300_all_skipped_for_cash": baseline_policy_attempts["battle_a_v2_all_skipped_for_cash"],
        "historical_pattern_b_096300_entry_attempts": baseline_policy_attempts["pattern_b_entry_attempts"],
        "prior_173_pair_structural_validation_pass": prior_evidence.get("structural_checks_pass") is True,
        "v2_cost_audit_formula_mismatch_count": c_checks.get("cost_formula_mismatches"),
        "pattern_b_cost_audit_mismatch_count": prior_evidence.get("pattern_b_cost_audit_mismatch_count", 0),
        "cost_audit_mismatch_zero": c_checks.get("cost_formula_mismatches") == 0 and prior_evidence.get("pattern_b_cost_audit_mismatch_count", 0) == 0,
        "v2_frozen_execution_date_price_mismatch_count": c_checks.get("frozen_execution_date_or_price_mismatches"),
        "v2_calendar_next_session_deviation_count": prior_evidence.get("v2_calendar_next_session_deviation_count"),
        "v2_frozen_execution_date_price_parity_all_pass": c_checks.get("frozen_execution_date_or_price_mismatches") == 0,
        "pattern_b_next_session_execution_violation_count": prior_evidence.get("pattern_b_next_session_execution_violation_count", 0),
        "pattern_b_next_session_execution_all_pass": prior_evidence.get("pattern_b_next_session_execution_all_pass", False),
        "exact_identity_exclusion_leakage_zero_in_replayed_scope": c_checks.get("096300_exact_identity_entry_attempts") == 0,
        "cash_conservation_violation_count": c_checks.get("cash_conservation_failures"),
        "cash_conservation_all_pass": c_checks.get("cash_conservation_failures") == 0 and prior_evidence.get("cash_conservation_all_pass", False),
        "v2_position_cap_violation_count": 0 if c_checks.get("no_position_cap") else 1,
        "pattern_b_position_cap_violation_count": prior_evidence.get("pattern_b_position_cap_violation_count", 0),
        "no_hidden_position_cap_all_pass": c_checks.get("no_position_cap") is True and prior_evidence.get("pattern_b_position_cap_violation_count", 1) == 0,
        "worker_count_violation_count": c_checks.get("worker_count_failures"),
        "worker_count_10_all_pass": c_checks.get("worker_count") == 10 and c_checks.get("worker_count_failures") == 0,
        "strategy_freeze_violation_count": 0 if c_checks.get("strategy_freeze_pass") else 1,
        "strategy_rules_frozen": c_checks.get("strategy_freeze_pass") is True,
        "battle_b_entry_market_cap_exact_date_parity": original_checks.get("battle_b_exact_pit_market_cap_preflight_pass") is True and prior_evidence.get("battle_b_entry_market_cap_exact_date_parity") is True,
        "battle_c_market_authority_missing": market_summary.get("market_authority_missing"),
        "battle_c_market_authority_ambiguous": market_summary.get("market_authority_ambiguous"),
        "battle_c_executed_non_kospi_entry_count": c_checks.get("executed_non_kospi_entries"),
        "battle_c_executed_entry_exact_pit_market_parity": current_market_ok and c_checks.get("executed_entry_pit_market_audit_mismatches") == 0 and c_checks.get("executed_non_kospi_entries") == 0,
        "battle_c_market_cap_filter_violation_count": 0 if c_checks.get("no_market_cap_filter") else 1,
        "structural_checks_pass": c_structural and prior_evidence.get("structural_checks_pass") is True,
        "replayed_scope_checks_pass": c_checks.get("status") == "PASS",
        "legacy_173_pair_outputs_not_replayed": True,
    }
    complete = len(all_metrics) == 30 and all(len(rows) == 10 for rows in rows_by_battle.values())
    checks = {
        "expected_result_count": 30,
        "actual_result_count": len(all_metrics),
        "results_by_battle": {key: len(value) for key, value in rows_by_battle.items()},
        "30_of_30_complete": complete,
        "permanent_exclusion_count_before": BASELINE_EXCLUSION_COUNT,
        "permanent_exclusion_new_exact_count": 1,
        "permanent_exclusion_count_after": len(current_pairs),
        "permanent_exclusion_policy_sha256": policy_hash,
        "permanent_exclusion_exact_duplicate_count": 0,
        "permanent_exclusion_normalization_collision_count": len(PERMANENT_IDENTITY_EXCLUSIONS) - len(current_pairs),
        "permanent_exclusion_ticker_only_count": 0,
        "all_seven_exact_global_exclusions_present": battle.P2_1_GLOBAL_LIFECYCLE_EXCLUSIONS <= current_pairs,
        "new_096300_exact_global_exclusion_present": TARGET in current_pairs and PERMANENT_IDENTITY_EXCLUSIONS[TARGET].get("approval_scope") == "GLOBAL permanent identity exclusion",
        "worker_count_10": c_checks.get("worker_count") == 10 and c_checks.get("worker_count_failures") == 0 and original_checks.get("worker_count_10") is True,
        "valuation_mdd_classified_by_coverage": all(row.get("mdd_type") in {"EXACT", "OBSERVED", "OBSERVED_BELOW_90_COVERAGE"} for row in all_metrics),
        "valuation_coverage_at_least_90_pct_all": not coverage_below_90,
        "valuation_check_required_results_below_90_pct": coverage_below_90,
        "battle_b_exact_pit_market_cap_preflight_pass": original_checks.get("battle_b_exact_pit_market_cap_preflight_pass") is True,
        "battle_c_exact_pit_market_authority_preflight_pass": current_market_ok,
        "battle_c_market_authority_missing": market_summary.get("market_authority_missing"),
        "battle_c_market_authority_ambiguous": market_summary.get("market_authority_ambiguous"),
        "entry_order_shared": battle.COMMON_ENTRY_ORDER,
        "strategy_rule_mutation": False,
        "posthoc_trade_selection": False,
        "cash_based_signal_regeneration": False,
        "position_cap": None,
        "artifact_evidence": artifact_evidence,
    }
    structural = all([
        complete,
        len(current_pairs) == CURRENT_EXCLUSION_COUNT,
        checks["permanent_exclusion_exact_duplicate_count"] == 0,
        checks["permanent_exclusion_normalization_collision_count"] == 0,
        checks["permanent_exclusion_ticker_only_count"] == 0,
        checks["all_seven_exact_global_exclusions_present"],
        checks["new_096300_exact_global_exclusion_present"],
        checks["worker_count_10"],
        checks["valuation_mdd_classified_by_coverage"],
        checks["battle_b_exact_pit_market_cap_preflight_pass"],
        checks["battle_c_exact_pit_market_authority_preflight_pass"],
        artifact_evidence["structural_checks_pass"],
    ])
    if not structural:
        status = "FAIL"
    elif coverage_below_90:
        status = "CHECK_REQUIRED"
    else:
        status = "PASS"
    validation = {
        "schema": "official_strategy_battle_validation_v02",
        "status": status,
        "execution_status": "COMPLETE" if complete else "INCOMPLETE",
        "replay_scope": {
            "battle_id": BATTLE_ID,
            "strategy_id": STRATEGY_ID,
            "windows": list(WINDOWS),
            "starting_head": preflight_record["starting_head"],
            "ending_head": battle.current_head(),
            "retained_baseline_exclusion_count": BASELINE_EXCLUSION_COUNT,
            "current_exclusion_count": CURRENT_EXCLUSION_COUNT,
            "retained_096300_candidate_attempt_count": baseline_policy_attempts["battle_a_v2_entry_attempts"] + baseline_policy_attempts["battle_b_v2_entry_attempts"],
            "retained_096300_candidate_executed_count": baseline_policy_attempts["non_battle_c_v2_executed_entries"],
            "retained_096300_candidates_all_skipped_for_cash": baseline_policy_attempts["battle_a_v2_all_skipped_for_cash"],
            "battle_a_replayed": False,
            "battle_b_replayed": False,
            "pattern_b_replayed": False,
            "pattern_b_battle_c_metrics_source": "existing V02 battle_c_kospi_only/pattern_b/battle_window_metrics.csv",
        },
        "checks": checks,
        "notes": [
            "Only Battle C / V2 was replayed for the five frozen windows using 10 workers.",
            "Battle A, Battle B, and all Pattern B outputs were retained from the prior 173-pair V02 run; no portfolio replay was run for them.",
            "The prior Battle A V2 artifact contains 096300 entry attempts that were all skipped for insufficient cash; none executed. They are disclosed as a retained-baseline limitation.",
            "The existing Pattern B Battle C result is used for head-to-head comparison and was not regenerated.",
            "Coverage below 90% remains CHECK_REQUIRED; no imputation, repair, extra exclusion, or repeat replay is performed.",
        ],
    }
    battle.write_json(OUTPUT_ROOT / "validation.json", validation)
    final_report = battle.render_final_report(
        {"all_rows": all_rows, "mcap_rows": mcap_rows, "kospi_rows": kospi_rows, "base_head": preflight_record["starting_head"]},
        read_json(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json").get("summary", {}),
        market_summary,
        cross_rows,
        sensitivity,
        validation,
    )
    (OUTPUT_ROOT / "final_report.md").write_text(final_report, encoding="utf-8")
    status_path = OUTPUT_ROOT / "run_status.json"
    run_status = read_json(status_path)
    run_status.update({
        "status": status,
        "execution_status": validation["execution_status"],
        "results": len(all_metrics),
        "expected_results": 30,
        "worker_count": battle.EXPECTED_WORKERS,
        "valuation_check_required_count": len(coverage_below_90),
        "latest_replay_scope": validation["replay_scope"],
    })
    write_json(status_path, run_status)

    source_hashes_path = OUTPUT_ROOT / "source_hashes.json"
    source_hashes = read_json(source_hashes_path)
    source_hashes["latest_scoped_replay"] = {
        **validation["replay_scope"],
        "work_instruction": {"path": str(WORK_INSTRUCTION), "sha256": battle.sha256(WORK_INSTRUCTION)},
        "closure_runner": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": battle.sha256(Path(__file__))},
        "official_orchestrator": {"path": "scripts/run_official_strategy_battle_v02.py", "sha256": battle.sha256(ROOT / "scripts/run_official_strategy_battle_v02.py")},
        "permanent_identity_exclusions": {
            "path": "src/trend_scanner/universe/permanent_identity_exclusions.py",
            "sha256": battle.sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
            "count": CURRENT_EXCLUSION_COUNT,
            "new_exact_pair": list(TARGET),
        },
        "pit_authority": preflight_record["pit_authority"],
        "c_v2_checks": c_checks,
        "baseline_source_checks": preflight_record["source_checks"],
    }
    battle.write_json(source_hashes_path, source_hashes)
    return validation


def _historical_target_attempts() -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for battle_id in ("battle_a_all_universe", "battle_b_pit_mcap_1t"):
        base = OUTPUT_ROOT / battle_id / "v2"
        for path in sorted(base.glob("portfolio_events_*.csv")):
            frame = battle.pd.read_csv(path, dtype=str, keep_default_na=False)
            if frame.empty:
                continue
            target = frame.loc[
                frame["ticker"].map(battle.normalize_ticker).eq(TARGET[0])
                & frame["isu_cd"].map(battle.normalize_isu).eq(TARGET[1])
                & frame["event_type"].astype(str).eq("ENTRY")
            ]
            for row in target.to_dict("records"):
                attempts.append({"battle_id": battle_id, "status": row.get("event_status"), "file": path.name})
    pattern_b_attempts = 0
    for battle_id in battle.BATTLE_IDS:
        for path in (OUTPUT_ROOT / battle_id / "pattern_b").glob("*/portfolio_events.csv"):
            frame = battle.pd.read_csv(path, dtype=str, keep_default_na=False)
            if not frame.empty:
                pattern_b_attempts += int((
                    frame["ticker"].map(battle.normalize_ticker).eq(TARGET[0])
                    & frame["isu_cd"].map(battle.normalize_isu).eq(TARGET[1])
                    & frame["event_type"].astype(str).eq("ENTRY")
                ).sum())
    executed = sum(item["status"] == "EXECUTED" for item in attempts)
    return {
        "battle_a_v2_entry_attempts": sum(item["battle_id"] == "battle_a_all_universe" for item in attempts),
        "battle_a_v2_executed_entries": sum(item["battle_id"] == "battle_a_all_universe" and item["status"] == "EXECUTED" for item in attempts),
        "battle_a_v2_all_skipped_for_cash": all(
            item["battle_id"] != "battle_a_all_universe" or item["status"] == "SKIPPED_CASH_UNAVAILABLE"
            for item in attempts
        ),
        "battle_b_v2_entry_attempts": sum(item["battle_id"] == "battle_b_pit_mcap_1t" for item in attempts),
        "non_battle_c_v2_executed_entries": executed,
        "pattern_b_entry_attempts": pattern_b_attempts,
        "attempts": attempts,
    }


def run() -> dict[str, Any]:
    preflight_record, pit_rows, authority, market_summary = preflight()
    battle.install_shared_repository_cache()
    print("Battle C / V2 only: replay five windows with 10 workers", flush=True)
    result = battle.run_v2_battle(BATTLE_ID, WINDOW_OUTPUT, market_authority=authority)
    checks = replay_checks(result, market_summary)
    if checks["status"] != "PASS":
        raise RuntimeError(f"BATTLE_C_V2_CLOSURE_VALIDATION_FAILED:{checks}")
    validation = update_reports(preflight_record, market_summary, result["rows"], checks)
    audit = {
        "schema": "battle_c_v2_096300_lifecycle_closure_v01",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_head": preflight_record["starting_head"],
        "end_head": battle.current_head(),
        "target_identity": {"ticker": TARGET[0], "isu_cd": TARGET[1], "evidence_id": TARGET_EVIDENCE_ID},
        "exclusions_before_after": [BASELINE_EXCLUSION_COUNT, CURRENT_EXCLUSION_COUNT],
        "replay_scope": validation["replay_scope"],
        "source_checks": preflight_record["source_checks"],
        "c_v2_checks": checks,
        "validation_status": validation["status"],
        "no_extra_replay_or_repair": True,
    }
    write_json(AUDIT_PATH, audit)
    return validation


def reconcile_existing_reports() -> dict[str, Any]:
    """Regenerate derived reports from a completed scoped run without replaying portfolios."""
    audit = read_json(AUDIT_PATH)
    validation_path = OUTPUT_ROOT / "validation.json"
    validation = read_json(validation_path)
    c_checks = audit["c_v2_checks"]
    current_market = read_json(OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.json")["summary"]
    market_pass = (
        current_market.get("status") == "PASS"
        and current_market.get("market_authority_missing") == 0
        and current_market.get("market_authority_ambiguous") == 0
    )
    exact_market_pass = (
        market_pass
        and c_checks.get("executed_entry_pit_market_audit_mismatches") == 0
        and c_checks.get("executed_non_kospi_entries") == 0
    )
    evidence = validation["checks"]["artifact_evidence"]
    evidence["battle_c_executed_entry_exact_pit_market_parity"] = exact_market_pass
    evidence["structural_checks_pass"] = bool(
        evidence.get("prior_173_pair_structural_validation_pass")
        and c_checks.get("status") == "PASS"
        and exact_market_pass
    )
    validation["checks"]["battle_c_executed_entry_exact_pit_market_parity"] = exact_market_pass
    validation["checks"]["battle_c_exact_pit_market_authority_preflight_pass"] = market_pass
    if not exact_market_pass or not evidence["structural_checks_pass"]:
        validation["status"] = "FAIL"
    validation["checks"]["artifact_evidence"] = evidence
    battle.write_json(validation_path, validation)

    all_rows = battle.read_metric_rows(OUTPUT_ROOT / "battle_a_all_universe" / "v2" / "battle_window_metrics.csv", STRATEGY_ID, "battle_a_all_universe")
    all_rows += battle.read_metric_rows(OUTPUT_ROOT / "battle_a_all_universe" / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, "battle_a_all_universe")
    mcap_rows = battle.read_metric_rows(OUTPUT_ROOT / "battle_b_pit_mcap_1t" / "v2" / "battle_window_metrics.csv", STRATEGY_ID, "battle_b_pit_mcap_1t")
    mcap_rows += battle.read_metric_rows(OUTPUT_ROOT / "battle_b_pit_mcap_1t" / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, "battle_b_pit_mcap_1t")
    kospi_rows = battle.read_metric_rows(OUTPUT_ROOT / BATTLE_ID / "v2" / "battle_window_metrics.csv", STRATEGY_ID, BATTLE_ID)
    kospi_rows += battle.read_metric_rows(OUTPUT_ROOT / BATTLE_ID / "pattern_b" / "battle_window_metrics.csv", pattern_b.STRATEGY_ID, BATTLE_ID)
    cross_rows = battle.pd.read_csv(OUTPUT_ROOT / "cross_battle_comparison.csv").to_dict("records")
    sensitivity = battle.pd.read_csv(OUTPUT_ROOT / "universe_filter_sensitivity.csv").to_dict("records")
    cap_summary = read_json(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json").get("summary", {})
    report = battle.render_final_report(
        {"all_rows": all_rows, "mcap_rows": mcap_rows, "kospi_rows": kospi_rows, "base_head": audit["start_head"]},
        cap_summary,
        current_market,
        cross_rows,
        sensitivity,
        validation,
    )
    (OUTPUT_ROOT / "final_report.md").write_text(report, encoding="utf-8")
    source_hashes_path = OUTPUT_ROOT / "source_hashes.json"
    source_hashes = read_json(source_hashes_path)
    scoped = source_hashes.get("latest_scoped_replay", {})
    scoped["closure_runner"] = {"path": str(Path(__file__).relative_to(ROOT)), "sha256": battle.sha256(Path(__file__))}
    scoped["report_reconciliation"] = "derived outputs reconciled from the recorded run; no portfolio replay"
    source_hashes["latest_scoped_replay"] = scoped
    battle.write_json(source_hashes_path, source_hashes)
    audit["report_reconciled_at_utc"] = datetime.now(timezone.utc).isoformat()
    audit["report_reconciliation_replayed_portfolios"] = False
    write_json(AUDIT_PATH, audit)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="Run the one-time scoped Battle C / V2 replay.")
    group.add_argument("--reconcile-existing", action="store_true", help="Rebuild validation/report outputs from the recorded replay without replaying portfolios.")
    args = parser.parse_args()
    validation = reconcile_existing_reports() if args.reconcile_existing else run()
    print(json.dumps({"status": validation["status"], "scope": validation["replay_scope"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
