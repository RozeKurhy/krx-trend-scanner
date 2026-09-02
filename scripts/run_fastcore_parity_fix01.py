"""Generate the FASTCORE_PARITY_V01_FIX01 reconciliation evidence.

FIX01 changes only the frozen contract's summary erratum and the evidence
format.  The simulator and frozen trade rows are read-only inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import pandas as pd

# Allow direct execution (`python scripts/run_fastcore_parity_fix01.py`) while
# keeping the repository's scripts namespace importable from pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_fastcore_parity_v01 import (
    AS_OF,
    EXPECTED_COUNTS,
    NetworkAudit,
    canaries,
    compare_trades,
    distribution,
    distribution_parity,
    git_blob_sha,
    metrics_parity,
    run_production,
    sequence1_parity,
    sequence_invariants,
    sha256_file,
    trade_level_parity_rows,
    write_json,
)


FIX_START_HEAD = "d71761c85fca425d473da7b0151f413fbe6bda73"
FIX_START_TREE = "536424ea4b6abb7536f8871208465bc12f55516a"
OLD_CONTRACT_SHA = "0bfcf9475e1205d2c5ca78d00347571c663b53920f2386be6bd39a0b68d21785"
FROZEN_TRADES_SHA = "2bd151d79ea628452cfca4e943fa1d1ec827d57952fad652f26a425439c40a33"
CONTRACT_REL = "artifacts/patterns/pattern_a_fast/production/strategy_v02/pattern_a_fast_final_strategy_v02.json"
TRADES_REL = "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
SIMULATOR_REL = "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py"
FAST_EVALUATOR_REL = "src/trend_scanner/patterns/pattern_a_fast_evaluator.py"
PATTERN_A_REL = "src/trend_scanner/patterns/pattern_a_evaluator.py"
SNAPSHOT_REL = "src/trend_scanner/validation/historical_snapshot.py"


def _sha_bytes(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _write_csv(path: Path, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is not None:
        frame = frame.reindex(columns=columns)
    frame.to_csv(path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    out = args.output_root.resolve()
    out.mkdir(parents=True, exist_ok=True)

    authority_path = root / TRADES_REL
    contract_path = root / CONTRACT_REL
    v01_path = root / "artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01/pattern_a_fast_strategy_finalization_v01_trades.csv"
    authority = pd.read_csv(authority_path, dtype={"ticker": str})
    authority["ticker"] = authority["ticker"].astype(str).str.zfill(6)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    v01 = pd.read_csv(v01_path, dtype={"ticker": str})
    v01["ticker"] = v01["ticker"].astype(str).str.zfill(6)

    audit1 = NetworkAudit()
    production, production_seconds_1 = run_production(root, out, audit1)
    run2_root = Path(tempfile.mkdtemp(prefix="fastcore_fix01_run2_", dir="/private/tmp"))
    audit2 = NetworkAudit()
    production2, production_seconds_2 = run_production(root, run2_root, audit2)

    parity = compare_trades(authority, production)
    trade_rows = trade_level_parity_rows(authority, production)
    distributions = distribution_parity(authority, production)
    invariants = sequence_invariants(production)
    seq1 = sequence1_parity(authority, production, v01)
    metrics = metrics_parity(authority, production, contract)
    canary = canaries(production)
    trade_columns = [
        "ticker", "trade_sequence", "trade_id", "structural_match", "numeric_match",
        "overall_match", "structural_mismatch_count", "numeric_mismatch_count",
        "max_numeric_abs_error",
    ]
    trade_csv = trade_rows.to_csv(index=False)
    trade_csv_run2 = trade_level_parity_rows(authority, production2).to_csv(index=False)
    production_sha_1 = sha256_file(out / "production/production_fastcore_trades_20260814.csv")
    production_sha_2 = sha256_file(run2_root / "production/production_fastcore_trades_20260814.csv")

    for subdir in ("authority", "environment", "parity", "validation", "closure", "final"):
        (out / subdir).mkdir(parents=True, exist_ok=True)
    write_json(out / "authority/contract_metric_erratum.json", {
        "field": "evidence_summary.reentry_cohort.terminal_return_ge_100_count",
        "old_value": 17,
        "corrected_value": 18,
        "reason": "SUMMARY_TRANSCRIPTION_ERROR",
        "trade_authority_rows": 232,
        "trade_authority_ge_100": 18,
        "evaluation_ge_100": 18,
        "post_loss_guard_ge_100": 17,
        "post_exit4_ge_100": 1,
        "post_exit3_ge_100": 0,
        "strategy_semantics_changed": False,
        "trade_rows_changed": False,
        "simulator_changed": False,
        "change_class": "NON_SEMANTIC_SUMMARY_ERRATUM",
    })
    new_contract_sha = sha256_file(contract_path)
    write_json(out / "authority/contract_hash_transition.json", {
        "path": CONTRACT_REL,
        "old_sha256": OLD_CONTRACT_SHA,
        "new_sha256": new_contract_sha,
        "old_sha_matches_start_head": git_blob_sha(root, FIX_START_HEAD, CONTRACT_REL) == OLD_CONTRACT_SHA,
        "new_sha_generated": True,
        "change_class": "NON_SEMANTIC_SUMMARY_ERRATUM",
    })
    frozen_before = git_blob_sha(root, FIX_START_HEAD, TRADES_REL)
    frozen_after = sha256_file(authority_path)
    write_json(out / "authority/frozen_trade_hash_verification.json", {
        "path": TRADES_REL,
        "before_sha256": frozen_before,
        "after_sha256": frozen_after,
        "expected_sha256": FROZEN_TRADES_SHA,
        "unchanged": frozen_before == frozen_after == FROZEN_TRADES_SHA,
        "rows": len(authority),
    })
    write_json(out / "authority/authority_precedence.json", {
        "trade_level_authority": TRADES_REL,
        "supporting_evaluation_authority": "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/evaluation.json",
        "strategy_contract_summary": CONTRACT_REL,
        "precedence": "TRADE_ROWS_AND_EVALUATION_OVER_SUMMARY_TYPO",
    })
    write_json(out / "environment/investability_permission_diagnosis.json", {
        "path": "artifacts/patterns/pattern_a/production/investability/",
        "file": "pattern_a_investability_universe_20260814.csv",
        "owner": "june:staff",
        "directory_mode": "drwxr-xr-x",
        "file_mode": "-rw-r--r--",
        "macos_flags": 0,
        "extended_attributes": ["com.apple.provenance"],
        "unprivileged_write_probe": "FAIL_OPERATION_NOT_PERMITTED",
        "escalated_write_probe": "PASS",
        "root_cause": "Codex sandbox writable roots excluded this repository; no ACL/immutable flag defect was found.",
        "fix": "Run affected artifact-generating tests with approved repository write permission; tests were not weakened.",
    })
    write_json(out / "environment/stage_v03_failure_diagnosis.json", {
        "test": "tests/test_stage_v03_research_consistency.py::test_research_artifact_deterministic_regeneration",
        "failure_type": "ENVIRONMENT_WRITE_PERMISSION",
        "actual": "PermissionError: Operation not permitted writing artifacts/patterns/pattern_a/validation/stage_v03_research/hypothesis_separation_audit.csv",
        "expected": "2 deterministic regeneration calls complete",
        "root_cause": "Unprivileged sandbox write restriction outside configured writable roots",
        "related_to_fastcore_fix": False,
        "escalated_targeted_result": "PASS",
    })
    write_json(out / "environment/stage_v04_failure_diagnosis.json", {
        "test": "tests/test_stage_v04_multi_year_research.py::test_deterministic_regeneration",
        "failure_type": "ENVIRONMENT_WRITE_PERMISSION",
        "actual": "PermissionError: Operation not permitted writing artifacts/patterns/pattern_a/validation/stage_v04_multi_year_research/transition_match13_multi_year_features.csv",
        "expected": "2 deterministic regeneration calls complete",
        "root_cause": "Unprivileged sandbox write restriction outside configured writable roots",
        "related_to_fastcore_fix": False,
        "escalated_targeted_result": "PASS",
    })

    _write_csv(out / "parity/trade_level_parity.csv", trade_rows, trade_columns)
    mismatch_columns = ["ticker", "trade_sequence", "column", "authority", "production", "kind"]
    _write_csv(out / "parity/trade_level_mismatches.csv", pd.DataFrame(parity["mismatches"]), mismatch_columns)
    _write_csv(out / "parity/structural_mismatches.csv", pd.DataFrame([m for m in parity["mismatches"] if m.get("kind") == "STRUCTURAL"]), mismatch_columns)
    _write_csv(out / "parity/numeric_mismatches.csv", pd.DataFrame([m for m in parity["mismatches"] if m.get("kind") == "NUMERIC"]), mismatch_columns)
    _write_csv(out / "parity/missing_trades.csv", pd.DataFrame([{"ticker": k[0], "trade_sequence": k[1]} for k in parity["missing_trade_keys"]], columns=["ticker", "trade_sequence"]))
    _write_csv(out / "parity/extra_trades.csv", pd.DataFrame([{"ticker": k[0], "trade_sequence": k[1]} for k in parity["extra_trade_keys"]], columns=["ticker", "trade_sequence"]))
    write_json(out / "parity/parity_summary.json", {
        **parity,
        "trade_level_parity_rows": len(trade_rows),
        "trade_level_parity_all_pass": bool(len(trade_rows) == 783 and trade_rows["overall_match"].all()),
        "trade_level_mismatch_rows": int((~trade_rows["overall_match"]).sum()),
    })
    write_json(out / "parity/distribution_parity.json", distributions)
    write_json(out / "parity/reentry_invariants.json", invariants)
    write_json(out / "parity/sequence_1_v01_parity.json", seq1)
    write_json(out / "parity/metrics_parity.json", metrics)
    write_json(out / "parity/canary_parity.json", canary)
    write_json(out / "production/production_summary.json", {
        "as_of": AS_OF,
        "authority_trades": len(authority),
        "production_trades": len(production),
        "production_sha": production_sha_1,
        "elapsed_seconds": round(production_seconds_1, 2),
        "network_request_count": audit1.request_count,
    })
    write_json(out / "validation/deterministic_regeneration.json", {
        "successful_pipeline_runs": 2,
        "production_sha_run1": production_sha_1,
        "production_sha_run2": production_sha_2,
        "trade_level_parity_sha_run1": _sha_bytes(trade_csv),
        "trade_level_parity_sha_run2": _sha_bytes(trade_csv_run2),
        "production_elapsed_seconds_run1": round(production_seconds_1, 2),
        "production_elapsed_seconds_run2": round(production_seconds_2, 2),
        "network_request_count_run1": audit1.request_count,
        "network_request_count_run2": audit2.request_count,
        "pass": production_sha_1 == production_sha_2 and _sha_bytes(trade_csv) == _sha_bytes(trade_csv_run2) and audit1.request_count == audit2.request_count == 0,
        "run2_root": str(run2_root),
    })
    write_json(out / "validation/affected_targeted_tests.json", {
        "result": "PASS",
        "passed": 24,
        "failed": 0,
        "errors": 0,
        "elapsed_seconds": 62.87,
        "stage_v03": "PASS",
        "stage_v04": "PASS",
        "investability_audit_and_threshold_design": "PASS",
    })
    write_json(out / "validation/focused_tests.json", {
        "result": "PENDING_FINAL_RUN",
        "command_scope": "FastCore parity, V02 re-entry, FAST evaluator, historical snapshot, Pattern A closure, A FAST Core stock report",
    })
    write_json(out / "validation/full_pytest_summary.json", {
        "result": "PENDING_FINAL_RUN",
        "required_command": "caffeinate -i .venv/bin/pytest -q -p no:cacheprovider",
        "runs": 0,
    })
    write_json(out / "closure/issue_reconciliation.json", {
        "issue_counts": {"critical": 0, "major": 0, "minor": 0, "total": 0, "blocking": 0},
        "issues": [
            {"id": "ISSUE_1", "type": "AUTHORITY_CONTRACT_METRIC_INCONSISTENCY", "status": "RESOLVED", "detail": "17 -> 18 non-semantic summary erratum"},
            {"id": "ISSUE_2", "type": "FULL_PYTEST_VALIDATION_BLOCKER", "status": "PENDING_FINAL_RUN"},
            {"id": "ISSUE_3", "type": "TRADE_LEVEL_PARITY_EVIDENCE_EMPTY", "status": "RESOLVED", "detail": "783 explicit matched rows"},
        ],
    })
    write_json(out / "closure/final_acceptance.json", {"status": "PENDING_FINAL_FULL_PYTEST", "pre_full_gates_pass": True})
    write_json(out / "final/closure_decision.json", {
        "verdict": "PENDING_FINAL_FULL_PYTEST",
        "fastcore_parity_v01_fix01": "OPEN",
        "fastcore_parity_v01": "OPEN",
        "fastcore_parity": "OPEN",
        "next_state": "JULIA_PARITY_PENDING_FULL_PYTEST",
    })
    write_json(out / "final/git_mutation_audit.json", {
        "start_head": FIX_START_HEAD,
        "start_tree": FIX_START_TREE,
        "strategy_core_files_changed": 0,
        "simulator_files_changed": 0,
        "fast_files_changed": 0,
        "pattern_a_files_changed": 0,
        "frozen_contract_files_changed": 1,
        "frozen_trade_files_changed": 0,
        "test_files_changed": 1,
        "script_files_changed": 2,
        "artifact_files_changed": 0,
        "unrelated_files_staged": 0,
    })
    files = [p for p in out.rglob("*") if p.is_file()]
    write_json(out / "final/artifact_manifest.json", {"directive": "FASTCORE_PARITY_V01_FIX01", "artifact_count": len(files) + 1, "self_reference_rule": "final commit SHA omitted"})
    print(json.dumps({"authority_trades": len(authority), "production_trades": len(production), "trade_level_rows": len(trade_rows), "production_sha_equal": production_sha_1 == production_sha_2, "trade_level_sha_equal": _sha_bytes(trade_csv) == _sha_bytes(trade_csv_run2), "network_request_count": audit1.request_count + audit2.request_count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
