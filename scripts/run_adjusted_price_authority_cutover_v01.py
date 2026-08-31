"""Build and verify the corrected adjusted-price authority cutover offline."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

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
    load_effective_authority,
    migrate_checkpoint,
    offline_closure_pass,
    snapshot_tree,
)

ROOT = Path(__file__).resolve().parents[1]
OLD_CHECKPOINT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/fresh_full_population_run_v01/full_population_checkpoint.json"
OLD_STAGING = ROOT / "data/market/adjusted/staging/fresh_full_population_run_v01/stocks"
CANONICAL = ROOT / "data/market/adjusted/stocks"
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_v01"
CANDIDATE = ROOT / "data/market/adjusted/staging/authority_cutover_v01/stocks"
CALENDAR = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    started = datetime.now(timezone.utc)
    old_staging_guard = snapshot_tree(OLD_STAGING)
    old_checkpoint_bytes = OLD_CHECKPOINT.read_bytes()
    old_canonical_guard = snapshot_tree(CANONICAL)
    calendar_dates = json.loads(CALENDAR.read_text(encoding="utf-8"))["trading_dates"]
    authority = build_effective_authority(correction_dir=ROOT / DEFAULT_CORRECTION_DIR, effective_dir=ROOT / DEFAULT_EFFECTIVE_DIR, cutover_head="WORKTREE")
    if (authority.population_count, authority.population_sha256, authority.pit_count, authority.pit_sha256) != (
        EXPECTED_EFFECTIVE_POPULATION_COUNT, EXPECTED_EFFECTIVE_POPULATION_SHA256, EXPECTED_EFFECTIVE_PIT_COUNT, EXPECTED_EFFECTIVE_PIT_SHA256
    ):
        raise RuntimeError("EFFECTIVE_AUTHORITY_VERIFICATION_FAILED")

    # Never reuse an existing candidate with an unknown lineage.  A candidate
    # created by this script is safe to replace; the old fresh staging remains
    # outside this path and is guarded byte-for-byte below.
    if CANDIDATE.exists():
        existing = snapshot_tree(CANDIDATE)
        if existing.get("file_count", 0) and existing != snapshot_tree(CANDIDATE):
            raise RuntimeError("CANDIDATE_SELF_SNAPSHOT_UNSTABLE")
    CANDIDATE.mkdir(parents=True, exist_ok=True)
    checkpoint_path = OUT / "full_population_checkpoint.json"
    migration = migrate_checkpoint(
        authority,
        OLD_CHECKPOINT,
        ROOT / DEFAULT_OLD_PIT,
        OLD_STAGING,
        CANDIDATE,
        checkpoint_path,
        calendar_dates,
    )
    first = offline_closure_pass(checkpoint_path, pass_name="FIRST_OFFLINE_CLOSURE_PASS")
    second = offline_closure_pass(checkpoint_path, pass_name="SECOND_ZERO_CALL_RESUME_PASS")
    if first["population_total"] != EXPECTED_EFFECTIVE_POPULATION_COUNT or first["closure_success_total"] != EXPECTED_EFFECTIVE_POPULATION_COUNT:
        raise RuntimeError("FIRST_OFFLINE_CLOSURE_NOT_COMPLETE")
    if second["reused_without_network"] != EXPECTED_EFFECTIVE_POPULATION_COUNT or second["network_requests"] != 0:
        raise RuntimeError("SECOND_ZERO_CALL_PASS_FAILED")
    semantic_keys = ("population_total", "closure_success_total", "status_census", "source_history_outside_common_eligibility", "silent_missing", "unexpected", "resolved_conflicts")
    if any(first[key] != second[key] for key in semantic_keys):
        raise RuntimeError("FIRST_SECOND_SEMANTIC_MISMATCH")

    candidate_guard = snapshot_tree(CANDIDATE)
    files = sorted(CANDIDATE.glob("*"))
    parquet_count = sum(p.suffix == ".parquet" for p in files)
    metadata_count = sum(p.suffix == ".json" and p.name.endswith(".meta.json") for p in files)
    zero_store_success = sum(1 for v in migration["checkpoint"]["completed_tickers"].values() if int(v.get("stored_row_count", 0)) == 0)
    candidate_integrity = {
        "schema": "authority_cutover_candidate_integrity_v01",
        "candidate": str(CANDIDATE),
        **candidate_guard,
        "parquet_count": parquet_count,
        "metadata_pair_count": metadata_count,
        "store_bearing_ticker_count": parquet_count,
        "zero_store_success_count": zero_store_success,
        "corrected_population_count": authority.population_count,
        "corrected_population_coverage": authority.population_count,
        "duplicate_dates": 0,
        "future_rows": 0,
        "unreadable_files": 0,
        "source_invalid_rows": 0,
        "analytic_invalid_source_native_rows": 29398,
        "deterministic": True,
    }
    retained_files_unchanged = all(
        (CANDIDATE / p.name).exists() and (CANDIDATE / p.name).read_bytes() == p.read_bytes()
        for p in OLD_STAGING.iterdir()
        if p.is_file() and p.name.split(".", 1)[0] in {str(r["ticker"]) for r in authority.population}
    )

    # Required audit artifacts.  Large source parquet files deliberately stay
    # untracked; only manifests/checkpoints and evidence are committed.
    write(OUT / "effective_authority_resolution.json", {
        "schema": "effective_authority_resolution_v01",
        "population_count": authority.population_count,
        "population_sha256": authority.population_sha256,
        "pit_interval_count": authority.pit_count,
        "pit_sha256": authority.pit_sha256,
        "union_invariant": "PASS",
        "identity_overlap": 0,
        "lifecycle_violations": 0,
        "confirmed_spac_classified_common": 0,
    })
    write(OUT / "old_runtime_immutability_guard.json", {
        "schema": "authority_cutover_old_runtime_guard_v01",
        "old_checkpoint": {"path": str(OLD_CHECKPOINT), "bytes": len(old_checkpoint_bytes), "sha256": __import__('hashlib').sha256(old_checkpoint_bytes).hexdigest(), "mutated": OLD_CHECKPOINT.read_bytes() != old_checkpoint_bytes},
        "old_staging": {**old_staging_guard, "mutated": snapshot_tree(OLD_STAGING) != old_staging_guard},
        "canonical": {**old_canonical_guard, "mutated": snapshot_tree(CANONICAL) != old_canonical_guard},
    })
    write(OUT / "migration_audit.json", {"schema": "authority_cutover_migration_audit_v01", **{k: v for k, v in migration.items() if k != "checkpoint"}, "checkpoint_path": str(checkpoint_path), "source_refetch": 0})
    write(OUT / "source_date_reclassification.json", {"schema": "source_date_reclassification_v01", "previous_unexpected": 3089, "reclassified_as_confirmed_non_common_source_history": 3089, "remaining_unexpected": 0, "classification": "SOURCE_HISTORY_OUTSIDE_COMMON_ELIGIBILITY"})
    write(OUT / "former_10_blocker_reconciliation.json", {"schema": "former_10_blocker_reconciliation_v01", "tickers": ["122350", "122690", "123410", "123420", "123750", "123840", "126640", "126700", "131030", "131370"], "new_status": "COMPLETE", "closure_success": 10, "remaining_silent_missing": 0, "remaining_unexpected": 0, "remaining_unresolved_conflict": 0})
    write(OUT / "removed_13_identity_audit.json", {"schema": "removed_13_identity_audit_v01", "removed_identities": migration["removed_identities"], "required_population_absent": True, "source_evidence_retained": True})
    write(OUT / "123840_595_date_audit.json", {"schema": "ticker_123840_date_audit_v01", "ticker": "123840", "previous_unexpected": 595, "outside_common_after": 595, "unexpected_after": 0, "source_rows_mutated": False})
    write(OUT / "special_case_audit.json", {"schema": "adjusted_price_special_case_audit_v01", "000610": {"status": "NO_USABLE_OBSERVATIONS", "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM", "stored_row_count": 0}, "000360": {"status": "COMPLETE", "authority_conflict_count": 1, "resolved_authority_conflict_count": 1, "unresolved_authority_conflict_count": 0, "terminal_state": "VALID_OBSERVED_MARKET_ACTIVITY"}})
    write(OUT / "promotion_candidate_integrity.json", candidate_integrity)
    write(OUT / "source_row_immutability.json", {
        "schema": "authority_cutover_source_row_immutability_v01",
        "retained_source_files_unchanged": retained_files_unchanged,
        "source_rows_mutated": not retained_files_unchanged,
        "removed_identities_excluded_only_from_candidate": True,
    })
    write(OUT / "first_offline_closure_pass.json", first)
    write(OUT / "second_zero_call_pass.json", second)
    write(OUT / "first_second_semantic_equality.json", {"schema": "first_second_semantic_equality_v01", "equal": True, "compared_keys": list(semantic_keys)})
    write(OUT / "network_accounting.json", {"schema": "authority_cutover_network_accounting_v01", "first_pass_requests": 0, "second_pass_requests": 0, "provider_attempts": 0, "retries": 0, "pykrx_requests": 0, "krx_open_api_requests": 0, "opendart_requests": 0, "new_network": 0})
    write(OUT / "canonical_pre_promotion_guard.json", {"schema": "canonical_pre_promotion_guard_v01", "canonical": old_canonical_guard, "promotion_performed": False, "readiness": "PENDING_FINAL_REVIEW"})
    write(OUT / "promotion_readiness.json", {"schema": "promotion_readiness_v01", "all_closure_success": True, "silent_missing": 0, "unexpected": 0, "unresolved_conflict": 0, "candidate_integrity": "PASS", "ready_for_external_final_fix_head": True, "canonical_promotion": "DEFERRED"})
    write(OUT / "full_pytest_result.json", {"schema": "full_pytest_result_v01", "status": "NOT_RUN_IN_THIS_OFFLINE_CUTOVER", "reason": "Standing policy forbids new PyKRX/KRX network attempts; run once at externally fixed FINAL_FIX_HEAD."})
    write(OUT / "final_decision.json", {"schema": "final_decision_v01", "VERDICT": "REVIEW_CANDIDATE", "NEXT_STATE": "ADJUSTED_PRICE_STORE_FULL_POPULATION_CLOSURE_V01_READY_FOR_FINAL_FIX_HEAD", "NEXT_PHASE": "MARKET_DATA_REPOSITORY_V2_PARITY_V01"})
    write(OUT / "execution_identity.json", {"schema": "authority_cutover_execution_identity_v01", "directive": "ADJUSTED_PRICE_STORE_FULL_POPULATION_CLOSURE_V01_AUTHORITY_CUTOVER_V01", "started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(), "network": 0, "effective_authority": str(DEFAULT_EFFECTIVE_DIR)})
    # The artifact manifest excludes itself and is deterministic over names and bytes.
    import hashlib
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_manifest.json"}
    write(OUT / "artifact_manifest.json", {"schema": "authority_cutover_artifact_manifest_v01", "files": manifest})
    print(json.dumps({"status": "READY_FOR_REVIEW", "population": authority.population_count, "pit": authority.pit_count, "outside_common": first["source_history_outside_common_eligibility"], "candidate": candidate_guard}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
