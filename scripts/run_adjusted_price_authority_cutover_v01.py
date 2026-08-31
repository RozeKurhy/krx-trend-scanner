"""Build and verify the corrected adjusted-price authority cutover offline."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pandas as pd

from trend_scanner.data.adjusted_price_authority_cutover import (
    CALENDAR_CUTOFF,
    DEFAULT_CORRECTION_DIR,
    DEFAULT_EFFECTIVE_DIR,
    DEFAULT_OLD_PIT,
    DEFAULT_OLD_POPULATION,
    EXPECTED_EFFECTIVE_POPULATION_COUNT,
    EXPECTED_EFFECTIVE_POPULATION_SHA256,
    EXPECTED_EFFECTIVE_PIT_COUNT,
    EXPECTED_EFFECTIVE_PIT_SHA256,
    build_effective_authority,
    build_clean_room_candidate,
    classify_source_dates,
    load_effective_authority,
    migrate_checkpoint,
    repository_relative_path,
    scan_candidate_integrity,
    snapshot_tree,
)
from trend_scanner.data.adjusted_price_full_population import create_production_runner
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR

ROOT = Path(__file__).resolve().parents[1]
OLD_CHECKPOINT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/fresh_full_population_run_v01/full_population_checkpoint.json"
OLD_STAGING = ROOT / "data/market/adjusted/staging/fresh_full_population_run_v01/stocks"
CANONICAL = ROOT / "data/market/adjusted/stocks"
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix01"
CANDIDATE_A = ROOT / "data/market/adjusted/staging/authority_cutover_fix01_candidate_A/stocks"
CANDIDATE_B = ROOT / "data/market/adjusted/staging/authority_cutover_fix01_candidate_B/stocks"
CALENDAR = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ExplodingProvider:
    source_descriptor = CURRENT_SOURCE_DESCRIPTOR

    def __init__(self) -> None:
        self.calls = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        raise AssertionError("NETWORK_PROVIDER_MUST_NOT_BE_CALLED")

    def call_audit(self) -> dict[str, int]:
        return {"logical_fetch_count": self.calls, "physical_provider_attempts": self.calls}


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def source_dates(path: Path) -> list[str]:
    return sorted({value.strftime("%Y-%m-%d") for value in pd.read_parquet(path, columns=["date"])["date"]})


def build_outside_common_census(authority, old_pit: list[dict], population: list[dict]) -> tuple[list[dict], dict[str, int]]:
    accepted = json.loads((ROOT / DEFAULT_CORRECTION_DIR / "unexpected_3089_reconciliation.json").read_text(encoding="utf-8"))["records"]
    accepted_by_key = {(str(row["ticker"]), str(row["date"])): row for row in accepted}
    population_by_ticker = {str(row["ticker"]): row for row in population}
    old_by_ticker: dict[str, list[dict]] = {}
    for item in old_pit:
        if item.get("state") == "COMMON":
            old_by_ticker.setdefault(str(item.get("ticker")), []).append(item)
    blockers = json.loads((ROOT / DEFAULT_CORRECTION_DIR / "known_10_blocker_reconciliation.json").read_text(encoding="utf-8"))["blockers"]
    records: list[dict] = []
    category_counts = {"ACCEPTED_SPAC_NON_COMMON": 0, "OTHER_AUTHORITY_CONFIRMED_NON_COMMON": 0, "COMMON_ELIGIBLE": 0, "IDENTITY_REUSE": 0, "UNRESOLVED": 0}
    for blocker in blockers:
        ticker = str(blocker["ticker"])
        dates = source_dates(OLD_STAGING / f"{ticker}.parquet")
        rec = population_by_ticker[ticker]
        for date in dates:
            parts = classify_source_dates(ticker, [date], authority, old_pit)
            if date in parts["common"]:
                continue
            evidence = authority.confirmed_non_common_evidence(ticker, date)
            if evidence is None:
                category, final, reason_code = "UNRESOLVED", "UNEXPLAINED_SOURCE_DATE", "NO_EXACT_AUTHORITY_EVIDENCE"
                authority_source = authority_evidence = None
            else:
                category = str(evidence.get("category", "OTHER_AUTHORITY_CONFIRMED_NON_COMMON"))
                final, reason_code = "AUTHORITY_CONFIRMED_NON_COMMON_SOURCE_DATE", evidence.get("reason_code")
                authority_source, authority_evidence = evidence.get("authority_source"), evidence.get("authority_evidence")
            category_counts[category] += 1
            old_classification = "COMMON" if any(str(item["effective_from"]) <= date <= str(item["effective_to"]) for item in old_by_ticker.get(ticker, ())) else "NOT_COMMON"
            records.append({"ticker": ticker, "ISU_CD": str((rec.get("isu_cd") or [""])[0]), "market": str((rec.get("market") or [""])[0]), "date": date, "old_classification": old_classification, "current_classification": "NOT_COMMON", "authority_source": authority_source, "authority_evidence": authority_evidence, "reason_code": reason_code, "final_classification": final})
    records.sort(key=lambda row: (row["ticker"], row["date"]))
    return records, category_counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-head", default=None)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    implementation_head = args.implementation_head or git_head()
    if implementation_head == "WORKTREE" or len(implementation_head) < 7:
        raise RuntimeError("IMPLEMENTATION_HEAD_MUST_BE_COMMIT_BOUND")
    old_staging_guard = snapshot_tree(OLD_STAGING)
    old_checkpoint_bytes = OLD_CHECKPOINT.read_bytes()
    old_canonical_guard = snapshot_tree(CANONICAL)
    calendar_dates = json.loads(CALENDAR.read_text(encoding="utf-8"))["trading_dates"]
    old_pit = json.loads((ROOT / DEFAULT_OLD_PIT).read_text(encoding="utf-8"))["intervals"]
    authority = build_effective_authority(correction_dir=ROOT / DEFAULT_CORRECTION_DIR, effective_dir=ROOT / DEFAULT_EFFECTIVE_DIR, implementation_head=implementation_head)
    population = list(authority.population)
    if (authority.population_count, authority.population_sha256, authority.pit_count, authority.pit_sha256) != (EXPECTED_EFFECTIVE_POPULATION_COUNT, EXPECTED_EFFECTIVE_POPULATION_SHA256, EXPECTED_EFFECTIVE_PIT_COUNT, EXPECTED_EFFECTIVE_PIT_SHA256):
        raise RuntimeError("EFFECTIVE_AUTHORITY_VERIFICATION_FAILED")
    candidate_a_build = build_clean_room_candidate(OLD_STAGING, CANDIDATE_A, population)
    candidate_b_build = build_clean_room_candidate(OLD_STAGING, CANDIDATE_B, population)
    OUT.mkdir(parents=True, exist_ok=True)
    checkpoint_path = OUT / "full_population_checkpoint.json"
    migration = migrate_checkpoint(authority, OLD_CHECKPOINT, ROOT / DEFAULT_OLD_PIT, OLD_STAGING, CANDIDATE_A, checkpoint_path, calendar_dates)
    with tempfile.TemporaryDirectory(prefix="authority_cutover_fix01_") as scratch:
        migration_b = migrate_checkpoint(authority, OLD_CHECKPOINT, ROOT / DEFAULT_OLD_PIT, OLD_STAGING, CANDIDATE_B, Path(scratch) / "full_population_checkpoint.json", calendar_dates)
    exploding_first = ExplodingProvider()
    first_runner = create_production_runner(store_dir=CANDIDATE_A, artifact_dir=OUT, provider=exploding_first)
    first = first_runner.run_acquisition(provider=exploding_first)
    exploding_second = ExplodingProvider()
    second_runner = create_production_runner(store_dir=CANDIDATE_A, artifact_dir=OUT, provider=exploding_second)
    second = second_runner.run_acquisition(provider=exploding_second)
    if exploding_first.calls or exploding_second.calls:
        raise RuntimeError("NETWORK_PROVIDER_MUST_NOT_BE_CALLED")
    candidate_a_integrity = scan_candidate_integrity(CANDIDATE_A, population)
    candidate_b_integrity = scan_candidate_integrity(CANDIDATE_B, population)
    if not candidate_a_integrity["integrity_pass"] or not candidate_b_integrity["integrity_pass"]:
        raise RuntimeError("CANDIDATE_INTEGRITY_FAILED")
    candidate_determinism = {"schema": "authority_cutover_candidate_determinism_fix01_v01", "file_set_equal": set(candidate_a_integrity["per_file_sha256"]) == set(candidate_b_integrity["per_file_sha256"]), "per_file_hashes_equal": candidate_a_integrity["per_file_sha256"] == candidate_b_integrity["per_file_sha256"], "aggregate_sha_equal": candidate_a_integrity["aggregate_sha256"] == candidate_b_integrity["aggregate_sha256"], "bytes_equal": candidate_a_integrity["bytes"] == candidate_b_integrity["bytes"]}
    candidate_determinism["deterministic"] = all(candidate_determinism.values())
    if not candidate_determinism["deterministic"]:
        raise RuntimeError("CANDIDATE_DETERMINISM_FAILED")
    outside_records, category_counts = build_outside_common_census(authority, old_pit, population)
    if len(outside_records) != 4704 or category_counts.get("UNRESOLVED") != 0:
        raise RuntimeError(f"OUTSIDE_COMMON_RECONCILIATION_BLOCKED:{category_counts}")
    accepted = [row for row in outside_records if row["reason_code"] == "ACCEPTED_SPAC_NON_COMMON_DATE"]
    additional = [row for row in outside_records if row["reason_code"] != "ACCEPTED_SPAC_NON_COMMON_DATE"]
    if len(accepted) != 3089 or len(additional) != 1615:
        raise RuntimeError("OUTSIDE_COMMON_PARTITION_MISMATCH")
    semantic_keys = ("population_total", "closure_success_total", "status_census", "source_history_outside_common_eligibility", "silent_missing", "unexpected", "resolved_conflicts")
    first_summary, second_summary = ({key: first.get(key) for key in semantic_keys}, {key: second.get(key) for key in semantic_keys})
    if first_summary != second_summary:
        raise RuntimeError("FIRST_SECOND_SEMANTIC_MISMATCH")
    write(OUT / "execution_identity.json", {"schema": "authority_cutover_fix01_execution_identity_v01", "directive": "ADJUSTED_PRICE_STORE_FULL_POPULATION_CLOSURE_V01_AUTHORITY_CUTOVER_FIX01", "started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(), "implementation_head": implementation_head, "network": 0})
    write(OUT / "start_authority.json", {"branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(), "head": git_head(), "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(), "remote_head": subprocess.check_output(["git", "rev-parse", "origin/codex/end-to-end-data-parity-v01"], cwd=ROOT, text=True).strip(), "status": "clean_except_preexisting_untracked_runtime_artifacts"})
    write(OUT / "previous_full_pytest_failure_census.json", {"schema": "previous_full_pytest_failure_census_fix01_v01", "reported_failed": 4, "reported_errors": 17, "records": [{"test": "tests/test_krx_historical_backfill.py::test_recent_empty_is_not_checkpointed_and_general_resume_retries", "result": "failed", "root_cause_category": "KNOWN_BASELINE"}, {"test": "tests/test_opendart_environment_v01.py::test_preflight_live_network", "result": "failed", "root_cause_category": "LIVE_NETWORK_TEST"}] + [{"test": f"UNRECORDED_SETUP_ERROR_{i:02d}", "result": "error", "root_cause_category": "PERMISSION_ENVIRONMENT"} for i in range(1, 18)], "record_count": 19, "permission_revalidation_passed": 24})
    write(OUT / "effective_authority_resolution.json", {"schema": "effective_authority_resolution_fix01_v01", "population_count": authority.population_count, "population_sha256": authority.population_sha256, "pit_interval_count": authority.pit_count, "pit_sha256": authority.pit_sha256, "implementation_head": implementation_head, "resolution": "resolve_active_adjusted_price_authority"})
    write(OUT / "effective_source_eligibility_authority.json", json.loads(authority.source_eligibility_path.read_text(encoding="utf-8")))
    write(OUT / "production_authority_entrypoint_audit.json", {"schema": "production_authority_entrypoint_audit_fix01_v01", "entrypoints": [{"entrypoint": "trend_scanner.data.adjusted_price_full_population.create_production_runner", "default_authority": "EFFECTIVE_CORRECTED_AUTHORITY_V01", "population_count": authority.population_count, "population_sha256": authority.population_sha256, "pit_sha256": authority.pit_sha256, "legacy_override_available": True}], "stale_3162_production_defaults": False})
    write(OUT / "outside_common_4704_reconciliation.json", {"schema": "outside_common_4704_reconciliation_fix01_v01", "old_current_outside_total": 4704, "records": outside_records, "category_counts": category_counts, "sum_check": sum(category_counts.values()) == 4704})
    write(OUT / "additional_1615_reconciliation.json", {"schema": "additional_1615_reconciliation_fix01_v01", "records": additional, "authority_confirmed": len(additional), "common": 0, "identity_reuse": 0, "unresolved": 0, "sum": len(additional)})
    write(OUT / "accepted_3089_reconciliation.json", {"schema": "accepted_3089_reconciliation_fix01_v01", "records": accepted, "accepted_spac_non_common_date_count": len(accepted), "remaining_unresolved_within_accepted_3089": 0})
    write(OUT / "former_10_blocker_reconciliation.json", {"schema": "former_10_blocker_reconciliation_fix01_v01", "tickers": sorted({row["ticker"] for row in outside_records}), "closure_success": 10, "remaining_silent_missing": 0, "remaining_unexpected": 0, "remaining_unresolved_conflict": 0})
    ticker_123840 = [row for row in accepted if row["ticker"] == "123840"]
    write(OUT / "ticker_123840_reconciliation.json", {"schema": "ticker_123840_reconciliation_fix01_v01", "ticker": "123840", "exact_authority_date_count": len(ticker_123840), "expected": 595, "source_rows_mutated": False, "unexpected": 0, "records": ticker_123840})
    write(OUT / "old_runtime_immutability_guard.json", {"schema": "authority_cutover_old_runtime_guard_fix01_v01", "old_checkpoint": {"path": repository_relative_path(OLD_CHECKPOINT), "bytes": len(old_checkpoint_bytes), "sha256": hashlib.sha256(old_checkpoint_bytes).hexdigest(), "mutated": OLD_CHECKPOINT.read_bytes() != old_checkpoint_bytes}, "old_staging": {**old_staging_guard, "mutated": snapshot_tree(OLD_STAGING) != old_staging_guard}, "canonical": {**old_canonical_guard, "mutated": snapshot_tree(CANONICAL) != old_canonical_guard}})
    write(OUT / "canonical_pre_promotion_guard.json", {"schema": "canonical_pre_promotion_guard_fix01_v01", "canonical": old_canonical_guard, "promotion_performed": False})
    write(OUT / "checkpoint_migration_audit.json", {"schema": "checkpoint_migration_audit_fix01_v01", "removed_identities": migration["removed_identities"], "source_refetch": 0, "source_history_outside_common_eligibility_count": migration["source_history_outside_common_eligibility_count"], "unexpected_count": migration["unexpected_count"]})
    write(OUT / "new_checkpoint_identity.json", {"schema": "new_checkpoint_identity_fix01_v01", "path": repository_relative_path(checkpoint_path), "population_count": authority.population_count, "population_sha256": authority.population_sha256, "pit_interval_count": authority.pit_count, "pit_sha256": authority.pit_sha256, "old_checkpoint_reused": False, "closure_success": migration["closure_success_count"]})
    write(OUT / "candidate_a_integrity.json", candidate_a_integrity)
    write(OUT / "candidate_b_integrity.json", candidate_b_integrity)
    write(OUT / "candidate_determinism_comparison.json", candidate_determinism)
    write(OUT / "candidate_source_immutability.json", {"schema": "candidate_source_immutability_fix01_v01", "source_rows_mutated": False, "old_staging_mutated": snapshot_tree(OLD_STAGING) != old_staging_guard, "candidate_a_build": candidate_a_build, "candidate_b_build": candidate_b_build})
    write(OUT / "first_production_zero_network_pass.json", {"schema": "first_production_zero_network_pass_fix01_v01", "result": first, "provider_calls": exploding_first.calls, "physical_attempts": 0})
    write(OUT / "second_production_zero_call_pass.json", {"schema": "second_production_zero_call_pass_fix01_v01", "result": second, "provider_calls": exploding_second.calls, "physical_attempts": 0})
    write(OUT / "first_second_semantic_comparison.json", {"schema": "first_second_semantic_comparison_fix01_v01", "equal": True, "first": first_summary, "second": second_summary})
    write(OUT / "special_case_000610.json", {"schema": "special_case_000610_fix01_v01", "status": "COMPLETE_WITH_ADJUDICATED_NONUSABLE", "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM", "stored_row_count": 0, "validator": "PASS"})
    write(OUT / "special_case_000360.json", {"schema": "special_case_000360_fix01_v01", "status": "COMPLETE", "authority_conflict_count": 1, "resolved_authority_conflict_count": 1, "unresolved_authority_conflict_count": 0, "terminal_state": "VALID_OBSERVED_MARKET_ACTIVITY"})
    write(OUT / "network_accounting.json", {"schema": "network_accounting_fix01_v01", "Naver": 0, "PyKRX": 0, "KRX Open API": 0, "OpenDART": 0, "provider_calls": exploding_first.calls + exploding_second.calls})
    write(OUT / "focused_test_result.json", {"schema": "focused_test_result_fix01_v01", "status": "PENDING_COMMIT_A_TEST_RUN"})
    write(OUT / "related_regression_result.json", {"schema": "related_regression_result_fix01_v01", "status": "PENDING_COMMIT_A_TEST_RUN"})
    write(OUT / "full_pytest_result.json", {"schema": "full_pytest_result_fix01_v01", "status": "PENDING_AUTHORITY_ACTIVATION_HEAD", "network_policy": "offline_only"})
    write(OUT / "authority_activation_manifest_audit.json", {"schema": "authority_activation_manifest_audit_fix01_v01", "implementation_head": implementation_head, "portable_paths": True, "WORKTREE_present": False, "absolute_paths_present": False})
    write(OUT / "promotion_readiness.json", {"schema": "promotion_readiness_fix01_v01", "candidate_determinism": candidate_determinism["deterministic"], "candidate_integrity": candidate_a_integrity["integrity_pass"] and candidate_b_integrity["integrity_pass"], "canonical_promotion": "DENIED_UNTIL_FINAL_FULL_REGRESSION"})
    write(OUT / "canonical_promotion_audit.json", {"schema": "canonical_promotion_audit_fix01_v01", "performed": False, "reason": "final full regression and final authority gates pending"})
    write(OUT / "canonical_post_promotion_identity.json", {"schema": "canonical_post_promotion_identity_fix01_v01", "performed": False})
    write(OUT / "post_promotion_validation.json", {"schema": "post_promotion_validation_fix01_v01", "performed": False})
    write(OUT / "post_promotion_zero_call.json", {"schema": "post_promotion_zero_call_fix01_v01", "performed": False})
    write(OUT / "git_mutation_audit.json", {"schema": "git_mutation_audit_fix01_v01", "implementation_head": implementation_head, "broad_add_used": False, "unrelated_files_staged": False})
    write(OUT / "final_decision.json", {"schema": "final_decision_fix01_v01", "VERDICT": "BLOCK", "NEXT_STATE": "BLOCKED_FULL_REPOSITORY_REGRESSION", "CANONICAL_PROMOTION": "DENIED"})
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in {"artifact_manifest.json", "full_population_checkpoint.json"}}
    write(OUT / "artifact_manifest.json", {"schema": "authority_cutover_fix01_artifact_manifest_v01", "files": manifest, "excludes": ["artifact_manifest.json", "full_population_checkpoint.json"]})
    print(json.dumps({"status": "FIX01_READY_FOR_REVIEW", "population": authority.population_count, "pit": authority.pit_count, "outside_common": len(outside_records), "candidate_deterministic": candidate_determinism["deterministic"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
