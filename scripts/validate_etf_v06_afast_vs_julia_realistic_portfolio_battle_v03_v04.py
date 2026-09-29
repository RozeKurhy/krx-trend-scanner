#!/usr/bin/env python3
"""Revalidate sealed V03 artifacts with the V04 Group B parity rules.

This validator reads existing ledgers and reports only. It must never invoke a
candidate, strategy, price, or portfolio replay.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03 as battle


OUTPUT_DIR = battle.OUTPUT_DIR
PORTFOLIO_CSVS = (
    "portfolio_trade_ledger.csv",
    "portfolio_metrics.csv",
    "execution_summary.csv",
    "equity_curve.csv",
    "annual_returns.csv",
    "category_contribution.csv",
)
PROTECTED_CSVS = ("candidate_trade_ledger.csv", *PORTFOLIO_CSVS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"EXPECTED_JSON_OBJECT:{path.name}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _normalize_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Decode ledger JSON details without changing the sealed CSV on disk."""
    normalized: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        details: Any = row.get("source_signal_details")
        for _ in range(3):
            if not isinstance(details, str):
                break
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
                break
        if not isinstance(details, Mapping):
            details = {}
        else:
            details = dict(details)
        canonical_id = row.get("canonical_trade_id")
        if canonical_id is not None and not pd.isna(canonical_id) and not details.get("canonical_trade_id"):
            details["canonical_trade_id"] = str(canonical_id)
        row["source_signal_details"] = details
        row["ticker"] = battle.v03._norm_ticker(row.get("ticker", ""))
        normalized.append(row)
    return normalized


def _compare_existing_paths(
    candidate_rows: Sequence[Mapping[str, Any]],
    baseline_rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], int]:
    group_a_mismatches: list[dict[str, Any]] = []
    group_b_details: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for ticker, item in plan.items():
        group = str(item["group"])
        if group not in {"A", "B"}:
            continue
        for strategy in battle.STRATEGIES:
            old_rows = battle._trade_group(baseline_rows, ticker, strategy)
            new_rows = battle._trade_group(candidate_rows, ticker, strategy)
            if group == "A":
                comparison = battle._path_comparison(old_rows, new_rows, exact=True)
                if not comparison["pass"]:
                    group_a_mismatches.append({"ticker": ticker, "strategy_id": strategy, "comparison": comparison})
                continue

            classification = battle._classify_group_b_divergence(
                old_rows, new_rows, item.get("common_start"), item.get("v06_common_start"),
            )
            divergence_class = str(classification["divergence_class"])
            counts[divergence_class] += 1
            if divergence_class != "NO_DIVERGENCE":
                group_b_details.append({
                    "ticker": ticker,
                    "group": "B",
                    "strategy_id": strategy,
                    **classification,
                    "divergence_reason": divergence_class,
                })

    class_counts = {
        "NO_DIVERGENCE": counts["NO_DIVERGENCE"],
        "PRE_V06_WINDOW_ONLY": counts["PRE_V06_WINDOW_ONLY"],
        "LIFECYCLE_CARRYOVER": counts["LIFECYCLE_CARRYOVER"],
        "POST_V06_UNEXPLAINED_DIVERGENCE": counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
    }
    parity = {
        "group_a_definition": "new_common_start == V06 common_evaluable_start; exact path parity required",
        "group_a_ticker_count": sum(item["group"] == "A" for item in plan.values()),
        "group_a_parity_mismatch_count": len(group_a_mismatches),
        "group_a_mismatches": group_a_mismatches,
        "group_b_definition": "new_common_start < V06 common_evaluable_start; only PRE_V06_WINDOW_ONLY and LIFECYCLE_CARRYOVER are allowed",
        "group_b_ticker_count": sum(item["group"] == "B" for item in plan.values()),
        "group_b_changed_trade_path_ticker_count": len({row["ticker"] for row in group_b_details}),
        "group_b_changed_ticker_details": group_b_details,
        "group_b_classification_counts": class_counts,
        "group_b_pre_v06_window_only_divergence_count": class_counts["PRE_V06_WINDOW_ONLY"],
        "group_b_lifecycle_carryover_divergence_count": class_counts["LIFECYCLE_CARRYOVER"],
        "group_b_post_v06_unexplained_divergence_count": class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
        "group_b_unexplained_divergence_count": class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
        "verdict": "PARITY_PASS" if not group_a_mismatches and not class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"] else "CHECK_REQUIRED",
    }
    old_starts = [
        (pd.Timestamp(item["v06_common_start"]) - pd.Timestamp(item["common_start"])).days
        for item in plan.values()
        if item["group"] == "B" and item.get("common_start") and item.get("v06_common_start")
    ]
    parity["group_b_earliest_start_delta_days"] = min(old_starts) if old_starts else None
    parity["group_b_max_start_delta_days"] = max(old_starts) if old_starts else None
    return parity, len(group_a_mismatches)


def _all_equal_zero(validation: Mapping[str, Any], names: Sequence[str]) -> bool:
    try:
        return all(float(validation.get(name, float("nan"))) == 0.0 for name in names)
    except (TypeError, ValueError):
        return False


def revalidate_existing_v03(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Update only validation/report documents from sealed V03 inputs."""
    required_files = (
        "candidate_trade_ledger.csv", "candidate_summary.json", "full_run_attempted.json",
        "validation.json", "parity_report.json", "preflight_sample.json",
        "source_authorities.json", "portfolio_metrics.csv", "execution_summary.csv",
        *PORTFOLIO_CSVS,
    )
    missing = [name for name in required_files if not (output_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"V03_REVALIDATION_INPUT_MISSING:{','.join(missing)}")

    protected_hashes_before = {
        name: _sha256(output_dir / name)
        for name in PROTECTED_CSVS
        if (output_dir / name).is_file()
    }
    candidate_path = output_dir / "candidate_trade_ledger.csv"
    candidate_summary = _read_json(output_dir / "candidate_summary.json")
    marker = _read_json(output_dir / "full_run_attempted.json")
    validation = _read_json(output_dir / "validation.json")
    source_authorities = _read_json(output_dir / "source_authorities.json")
    sample = _read_json(output_dir / "preflight_sample.json")

    universe, _, baseline_rows, current_authority_hashes = battle._load_authorities()
    plan = battle._readiness_plan(universe)
    candidate_rows = _normalize_candidate_rows(
        pd.read_csv(candidate_path, dtype={"ticker": "string", "canonical_trade_id": "string"}).to_dict(orient="records")
    )
    parity, group_a_mismatch_count = _compare_existing_paths(candidate_rows, baseline_rows, plan)
    old_parity = _read_json(output_dir / "parity_report.json")
    stored_details = old_parity.get("group_b_changed_ticker_details", [])
    stored_map = {(str(row.get("ticker")), str(row.get("strategy_id"))): row for row in stored_details}
    recomputed_map = {(str(row.get("ticker")), str(row.get("strategy_id"))): row for row in parity["group_b_changed_ticker_details"]}
    stored_path_count = int(old_parity.get("group_b_divergent_strategy_path_count", len(stored_details)))

    actual_candidate_hash = _sha256(candidate_path)
    coverage = candidate_summary.get("portfolio_price_coverage", {})
    metrics = pd.read_csv(output_dir / "portfolio_metrics.csv").to_dict(orient="records")
    completed_metrics = [row for row in metrics if row.get("run_status") == "COMPLETED"]
    authority_hashes_match = all(
        source_authorities.get(key) == current_authority_hashes.get(key)
        for key in (
            "v06_universe_sha256", "v06_permanent_exclusions_sha256", "v06_readiness_sha256",
            "v06_trade_ledger_sha256", "v06_full_summary_sha256",
        )
    )
    comparisons_match_v03 = (
        len(stored_map) == len(recomputed_map) == stored_path_count
        and all(
            (key in stored_map)
            and all(
                stored_map[key].get("comparison", {}).get(field) == row.get("comparison", {}).get(field)
                for field in ("old_trade_count", "new_trade_count", "old_only_count", "new_only_count")
            )
            for key, row in recomputed_map.items()
        )
    )
    ledger_hash_matches = (
        candidate_summary.get("sealed") is True
        and candidate_summary.get("candidate_trade_ledger_sha256") == actual_candidate_hash
    )
    protected_hashes_after = {
        name: _sha256(output_dir / name)
        for name in protected_hashes_before
    }
    protected_csvs_unchanged = protected_hashes_before == protected_hashes_after

    class_counts = parity["group_b_classification_counts"]
    zero_fields = (
        "negative_cash_count", "post_cutoff_new_entry_count", "unauthorized_etf_count",
        "unauthorized_exclusion_count", "future_fallback_count", "nearest_date_fallback_count",
        "same_day_ordering_mismatch_count", "common_eligibility_mismatch_count",
        "execution_timing_mismatch_count", "execution_price_mismatch_count",
        "terminal_contract_mismatch_count", "cash_conservation_error_count",
        "position_notional_over_5m_count", "common_start_formula_mismatch_count",
        "expected_comparable_not_evaluable_count", "duplicate_canonical_trade_id_count",
        "unknown_category_count", "process_error_count", "no_trade_session_contract_mismatch_count",
        "raw_invalid_ohlc_count",
    )
    zero_checks = {field: _all_equal_zero(validation, (field,)) for field in zero_fields}
    checks = {
        "candidate_replay_completed_once": marker.get("candidate_lifecycle_attempt_count") == 1 and marker.get("full_run_attempt_count") == 1,
        "portfolio_replay_completed_once": marker.get("portfolio_run_attempt_count") == 1 and len(completed_metrics) == len(battle.STRATEGIES),
        "candidate_replay_worker_errors_zero": candidate_summary.get("candidate_worker_error_count") == 0,
        "candidate_lifecycle_count_matches_universe": candidate_summary.get("lifecycle_result_count") == len(universe) == 427,
        "candidate_ledger_sealed_hash_matches": ledger_hash_matches,
        "candidate_ledger_hash_unchanged": ledger_hash_matches,
        "portfolio_and_candidate_csvs_unchanged": protected_csvs_unchanged,
        "authority_hashes_match": authority_hashes_match,
        "stored_v03_group_b_comparisons_match": comparisons_match_v03,
        "sample_pass": sample.get("verdict") == "SAMPLE_PASS" and sample.get("validation_passed") is True,
        "group_a_exact_parity_zero": group_a_mismatch_count == 0,
        "pre_v06_window_only_at_least_two": class_counts["PRE_V06_WINDOW_ONLY"] >= 2,
        "lifecycle_carryover_allowed": class_counts["LIFECYCLE_CARRYOVER"] >= 0,
        "post_v06_unexplained_zero": class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"] == 0,
        "candidate_price_coverage_checked": coverage.get("checked") is True,
        "candidate_required_price_missing_zero": coverage.get("candidate_required_price_coverage_missing_count") == 0,
        "zero_candidate_price_requests_zero": coverage.get("price_requested_for_zero_candidate_etf_count") == 0,
        "portfolio_metrics_completed": len(completed_metrics) == len(battle.STRATEGIES),
        "zero_validation_counts": all(zero_checks.values()),
    }
    checks.update({f"zero:{key}": value for key, value in zero_checks.items()})
    passed = all(checks.values())
    reasons = [key for key, ok in checks.items() if not ok]

    validation.update({
        "verdict": "ETF_V06_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_BATTLE_V03_COMPLETE" if passed else "CHECK_REQUIRED",
        "passed": passed,
        "group_a_ticker_count": parity["group_a_ticker_count"],
        "group_a_v06_parity_mismatch_count": group_a_mismatch_count,
        "group_b_ticker_count": parity["group_b_ticker_count"],
        "group_b_classification_counts": class_counts,
        "group_b_pre_v06_window_only_divergence_count": class_counts["PRE_V06_WINDOW_ONLY"],
        "group_b_lifecycle_carryover_divergence_count": class_counts["LIFECYCLE_CARRYOVER"],
        "group_b_post_v06_unexplained_divergence_count": class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
        "group_b_unexplained_divergence_count": class_counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
        "portfolio_price_coverage_checked": bool(coverage.get("checked")),
        "portfolio_price_requested_ticker_count": int(coverage.get("portfolio_price_requested_ticker_count", 0)),
        "candidate_trade_ticker_count": int(coverage.get("candidate_trade_ticker_count", 0)),
        "zero_candidate_etf_count": int(coverage.get("zero_candidate_etf_count", 0)),
        "price_requested_for_zero_candidate_etf_count": int(coverage.get("price_requested_for_zero_candidate_etf_count", 0)),
        "candidate_required_price_coverage_missing_count": int(coverage.get("candidate_required_price_coverage_missing_count", 0)),
        "candidate_required_price_coverage_missing": list(coverage.get("candidate_required_price_coverage_missing", [])),
        "candidate_required_raw_session_gap_count": int(coverage.get("candidate_required_raw_session_gap_count", 0)),
        "candidate_replay_rerun_count": 0,
        "portfolio_replay_rerun_count": 0,
        "strategy_replay_rerun_count": 0,
        "candidate_trade_ledger_sha256": actual_candidate_hash,
        "candidate_ledger_hash_unchanged": ledger_hash_matches,
        "protected_csvs_unchanged": protected_csvs_unchanged,
        "v04_revalidation_checks": checks,
        "check_required_reasons": reasons,
    })
    source_authorities["pre_v04_validation_verdict"] = source_authorities.get(
        "pre_v04_validation_verdict", source_authorities.get("verdict"),
    )
    source_authorities["verdict"] = validation["verdict"]
    source_authorities["validation_correction"] = "V04 Group B divergence reclassification; no candidate or portfolio replay"
    source_authorities["candidate_replay_rerun_count"] = 0
    source_authorities["portfolio_replay_rerun_count"] = 0
    parity["candidate_trade_ledger_sha256"] = actual_candidate_hash
    parity["candidate_ledger_hash_unchanged"] = ledger_hash_matches
    parity["portfolio_replay_rerun_count"] = 0
    parity["candidate_replay_rerun_count"] = 0
    parity["stored_v03_comparisons_match"] = comparisons_match_v03

    _write_json(output_dir / "parity_report.json", parity)
    _write_json(output_dir / "validation.json", validation)
    _write_json(output_dir / "source_authorities.json", source_authorities)
    runtime = source_authorities.get("runtime", {})
    summary_text = battle._render_summary(
        validation,
        parity,
        pd.read_csv(output_dir / "portfolio_metrics.csv").to_dict(orient="records"),
        pd.read_csv(output_dir / "execution_summary.csv").to_dict(orient="records"),
        pd.read_csv(output_dir / "category_contribution.csv").to_dict(orient="records"),
        pd.read_csv(output_dir / "annual_returns.csv").to_dict(orient="records"),
        sample,
        runtime,
    )
    (output_dir / "summary.md").write_text(summary_text, encoding="utf-8")

    if protected_hashes_before != {
        name: _sha256(output_dir / name)
        for name in protected_hashes_before
    }:
        raise RuntimeError("REVALIDATION_MODIFIED_PROTECTED_CSV")
    return {"validation": validation, "parity": parity}


def main() -> int:
    result = revalidate_existing_v03()
    print(json.dumps({
        "verdict": result["validation"]["verdict"],
        "passed": result["validation"]["passed"],
        "group_b_classification_counts": result["parity"]["group_b_classification_counts"],
        "check_required_reasons": result["validation"].get("check_required_reasons", []),
        "candidate_replay_rerun_count": result["validation"]["candidate_replay_rerun_count"],
        "portfolio_replay_rerun_count": result["validation"]["portfolio_replay_rerun_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
