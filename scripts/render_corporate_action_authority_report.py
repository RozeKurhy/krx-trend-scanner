"""Render human-readable Markdown review report strictly from END_HEAD Git objects.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9 (Section 6-13)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from trend_scanner.data.corporate_action_authority import (
    audit_c13_metric_provenance,
    validate_canonical_run_identity_correction13,
    validate_full_regression_evidence,
    validate_live_evidence_linkage,
    validate_persisted_price_parity_evidence,
)


def read_git_blob(repo_root: Path, commit_head: str, relative_path: str) -> bytes:
    """Strictly read binary bytes of a blob at commit_head via git show."""
    git_spec = f"{commit_head}:{relative_path}"
    proc = subprocess.run(
        ["git", "show", git_spec],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return b""
    return proc.stdout


def read_git_json(repo_root: Path, commit_head: str, relative_path: str) -> dict[str, Any]:
    raw = read_git_blob(repo_root, commit_head, relative_path)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def read_git_csv(repo_root: Path, commit_head: str, relative_path: str) -> list[dict[str, str]]:
    raw = read_git_blob(repo_root, commit_head, relative_path)
    if not raw:
        return []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    return list(reader)


def verify_code_equivalence_between_commits(repo_root: Path, fix_head: str, end_head: str) -> tuple[bool, list[str]]:
    """Strictly execute git diff between FIX_HEAD and END_HEAD on code/test directories (Section 9)."""
    if not fix_head or not end_head:
        return False, ["MISSING_COMMIT_HEADS"]

    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{fix_head}..{end_head}", "--", "src", "scripts", "tests"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return False, [f"GIT_DIFF_ERROR: {proc.stderr.strip()}"]

    diff_files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return len(diff_files) == 0, diff_files


def _git_exists(repo_root: Path, revision: str, kind: str = "commit") -> bool:
    if not revision:
        return False
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{{kind}}}"],
        cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    return proc.returncode == 0


def _git_tree_sha(repo_root: Path, revision: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", f"{revision}^{{tree}}"],
        cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def evaluate_report_truth_sync(
    repo_root: Path,
    source_head: str,
    manifest: dict[str, Any],
    decision: dict[str, Any],
    binding: dict[str, Any],
    pytest_evidence: Mapping[str, Any] | Any | None = None,
) -> dict[str, Any]:
    """Fail closed unless the report source, code binding, and decision all agree."""
    blockers: list[str] = []
    fix_head = str(binding.get("fix_head", ""))
    binding_schema = str(binding.get("schema", ""))
    correction11_binding = binding_schema.endswith("correction_11")
    correction12_binding = binding_schema.endswith("correction_12")
    correction13_binding = binding_schema.endswith("correction_13")
    current_binding = correction11_binding or correction12_binding or correction13_binding
    end_head = str(binding.get("end_head", ""))
    if not manifest:
        blockers.append("MANIFEST_MISSING")
    if not decision:
        blockers.append("DECISION_MISSING")
    if not _git_exists(repo_root, fix_head):
        blockers.append("FIX_HEAD_MISSING")
    if not _git_exists(repo_root, source_head):
        blockers.append("END_HEAD_MISSING")
    if not current_binding and end_head != source_head:
        blockers.append("BINDING_END_HEAD_MISMATCH")
    if current_binding and ("end_head" in binding or "end_tree_sha" in binding):
        blockers.append("END_HEAD_SELF_REFERENCE_FORBIDDEN")
    actual_fix_tree = _git_tree_sha(repo_root, fix_head)
    actual_end_tree = _git_tree_sha(repo_root, source_head)
    if str(binding.get("fix_tree_sha", "")) != actual_fix_tree:
        blockers.append("FIX_TREE_SHA_MISMATCH")
    if not current_binding and str(binding.get("end_tree_sha", "")) != actual_end_tree:
        blockers.append("END_TREE_SHA_MISMATCH")
    if current_binding:
        tested_code_head = str(binding.get("tested_code_head", ""))
        tested_code_tree_sha = str(binding.get("tested_code_tree_sha", ""))
        if tested_code_head != fix_head:
            blockers.append("TESTED_CODE_HEAD_MISMATCH")
        if tested_code_tree_sha != actual_fix_tree:
            blockers.append("TESTED_CODE_TREE_SHA_MISMATCH")
    if binding.get("code_scope") != ["src", "scripts", "tests"]:
        blockers.append("CODE_SCOPE_MISMATCH")
    if not current_binding and binding.get("code_diff_paths") != []:
        blockers.append("CODE_DIFF_NOT_EMPTY")
    if not current_binding and binding.get("production_code_equivalent") is not True:
        blockers.append("CODE_TEST_BINDING_FAILURE")
    if current_binding and "production_code_equivalent" in binding:
        blockers.append("SELF_DECLARED_CODE_EQUIVALENCE_FORBIDDEN")
    if fix_head and source_head and _git_exists(repo_root, fix_head) and _git_exists(repo_root, source_head):
        equiv, diff_paths = verify_code_equivalence_between_commits(repo_root, fix_head, source_head)
        if not equiv or diff_paths:
            blockers.append("CODE_DIFF_DETECTED")
    required_decision = (
        isinstance(decision.get("all_gates_passed"), bool)
        and isinstance(decision.get("gate_06_result"), bool)
        and isinstance(decision.get("gate_15_result"), bool)
        and isinstance(decision.get("production_integration_authorized"), bool)
        and isinstance(decision.get("review_decision"), str)
    )
    if not required_decision:
        blockers.append("DECISION_FIELDS_INCOMPLETE")
    if correction11_binding and decision.get("full_suite_completion") is not True:
        blockers.append("FULL_PYTEST_INCOMPLETE")

    if correction12_binding:
        # The immutable pytest artifact, not the decision claim, is the
        # certification source.  Bind it to the exact FIX commit and tree.
        regression_certification = validate_full_regression_evidence(
            pytest_evidence,
            expected_fix_head=fix_head,
            expected_fix_tree_sha=str(binding.get("fix_tree_sha", "")),
        )
        blockers.extend(regression_certification.blockers)

        if isinstance(pytest_evidence, Mapping):
            pytest_raw = dict(pytest_evidence)
        elif hasattr(pytest_evidence, "to_dict"):
            pytest_raw = pytest_evidence.to_dict()
        else:
            pytest_raw = {}
        if "full_suite_completion" not in decision or decision.get("full_suite_completion") != pytest_raw.get("full_suite_completion"):
            blockers.append("DECISION_PYTEST_COMPLETION_MISMATCH")
        if "new_regression_count" not in decision or decision.get("new_regression_count") != pytest_raw.get("new_regression_count"):
            blockers.append("DECISION_PYTEST_REGRESSION_COUNT_MISMATCH")

        source_prerequisites = bool(
            decision.get("all_gates_passed") is True
            and decision.get("gate_06_result") is True
            and decision.get("gate_15_result") is True
            and regression_certification.certification_valid
        )
        review_decision = decision.get("review_decision")
        production_authorized = decision.get("production_integration_authorized")
        approved_shape = bool(
            review_decision == "APPROVED_FOR_PRODUCTION_INTEGRATION"
            and production_authorized is True
            and decision.get("recommended_next_state") == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
        )
        if source_prerequisites and not approved_shape:
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        elif not source_prerequisites and (
            approved_shape
            or (review_decision == "APPROVED_FOR_PRODUCTION_INTEGRATION" and production_authorized is not True)
            or production_authorized is True
            or (review_decision == "REJECTED_AS_PRODUCTION_AUTHORITY" and production_authorized is True)
            or (review_decision == "CONDITIONAL_REVIEW_REQUIRED" and production_authorized is not False)
        ):
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        if decision.get("all_gates_passed") is True and not (
            decision.get("gate_06_result") is True and decision.get("gate_15_result") is True
        ):
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        terminal_next_states = {
            "APPROVED_FOR_PRODUCTION_INTEGRATION": "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01",
            "CONDITIONAL_REVIEW_REQUIRED": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
            "REJECTED_AS_PRODUCTION_AUTHORITY": "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01",
        }
        if not isinstance(review_decision, str) or review_decision not in terminal_next_states:
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        elif decision.get("recommended_next_state") != terminal_next_states[review_decision]:
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        if isinstance(review_decision, str) and review_decision in {
            "CONDITIONAL_REVIEW_REQUIRED",
            "REJECTED_AS_PRODUCTION_AUTHORITY",
        } and production_authorized is not False:
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        all_15 = decision.get("all_15_gate_results")
        if isinstance(all_15, dict):
            if "gate_06_corporate_action_parity" in all_15 and all_15.get("gate_06_corporate_action_parity") is not decision.get("gate_06_result"):
                blockers.append("DECISION_INTERNAL_INCONSISTENCY")
            if "gate_15_no_unresolved_conditions" in all_15 and all_15.get("gate_15_no_unresolved_conditions") is not decision.get("gate_15_result"):
                blockers.append("DECISION_INTERNAL_INCONSISTENCY")
            if "all_gates_passed" in decision and decision.get("all_gates_passed") is not all(
                value is True for value in all_15.values()
            ):
                blockers.append("DECISION_INTERNAL_INCONSISTENCY")

    if correction13_binding:
        regression_certification = validate_full_regression_evidence(
            pytest_evidence,
            expected_fix_head=fix_head,
            expected_fix_tree_sha=str(binding.get("fix_tree_sha", "")),
        )
        blockers.extend(regression_certification.blockers)
        if decision.get("full_suite_completion") != regression_certification.full_suite_completion:
            blockers.append("DECISION_PYTEST_COMPLETION_MISMATCH")
        if decision.get("new_regression_count") != regression_certification.new_regression_count:
            blockers.append("DECISION_PYTEST_REGRESSION_COUNT_MISMATCH")
        c13_root = "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_13"
        cohort_rows = read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_review_cohort_v01_fix03_correction_13.csv")
        price_rows = read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_event_price_rows_v01_fix03_correction_13.csv")
        parity_rows = read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_event_sensitive_parity_v01_fix03_correction_13.csv")
        reconciliation_rows = read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_date_reconciliation_v01_fix03_correction_13.csv")
        c13_gate = read_git_json(repo_root, source_head, f"{c13_root}/gate06_corporate_action_reassessment_v01_fix03_correction_13.json")
        c13_audit = read_git_json(repo_root, source_head, f"{c13_root}/gate06_metric_provenance_audit_v01_fix03_correction_13.json")
        c13_link = read_git_json(repo_root, source_head, f"{c13_root}/live_evidence_linkage_validation_v01_fix03_correction_13.json")
        c13_identity = read_git_json(repo_root, source_head, f"{c13_root}/canonical_run_identity_validation_v01_fix03_correction_13.json")
        c13_certification = read_git_json(repo_root, source_head, f"{c13_root}/full_pytest_certification_v01_fix03_correction_13.json")
        c13_raw_manifest = read_git_json(repo_root, source_head, f"{c13_root}/corporate_action_raw_evidence_manifest_v01_fix03_correction_13.json")
        c13_authority = read_git_json(repo_root, source_head, f"{c13_root}/corporate_action_authority_records_v01_fix03_correction_13.json")
        request_logs = c13_gate.get("request_logs") or decision.get("network_accounting", {}).get("request_logs", [])
        persisted = validate_persisted_price_parity_evidence(
            price_rows, parity_rows, reconciliation_rows, cohort_rows,
            request_logs=request_logs, gate06_payload=c13_gate, decision_payload=decision,
        )
        blockers.extend(persisted.blockers)
        if persisted.evaluation_status != "EVALUATED":
            blockers.append("PRICE_EVIDENCE_NOT_EVALUATED")
        if str(manifest.get("schema", "")).endswith("correction_13"):
            expected_run_id = str(decision.get("canonical_run_id", "")).strip()
            run_id_values: list[tuple[str, str]] = []

            def collect_run_ids(value: Any, label: str) -> None:
                if isinstance(value, Mapping):
                    for key, child in value.items():
                        if str(key) == "canonical_run_id":
                            run_id_values.append((label, str(child or "").strip()))
                        collect_run_ids(child, f"{label}.{key}")
                elif isinstance(value, list):
                    for index, child in enumerate(value):
                        collect_run_ids(child, f"{label}[{index}]")

            collect_run_ids(manifest, "artifact_manifest")
            for label, payload in (("decision", decision), ("gate06", c13_gate), ("linkage", c13_link), ("identity", c13_identity), ("network", read_git_json(repo_root, source_head, f"{c13_root}/corporate_action_evidence_network_accounting_v01_fix03_correction_13.json")), ("raw_manifest", c13_raw_manifest), ("authority", c13_authority)):
                collect_run_ids(payload, label)
            for label, rows in (("cohort", cohort_rows), ("price", price_rows), ("parity", parity_rows), ("reconciliation", reconciliation_rows), ("discovery", read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_official_discovery_v01_fix03_correction_13.csv")), ("documents", read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_official_document_validation_v01_fix03_correction_13.csv"))):
                collect_run_ids(rows, label)
            if not expected_run_id:
                blockers.append("CANONICAL_RUN_IDENTITY_MISMATCH")
            for label, observed in run_id_values:
                if not observed:
                    blockers.append("CANONICAL_RUN_ID_MISSING")
                elif observed != expected_run_id:
                    blockers.append("CANONICAL_RUN_IDENTITY_MISMATCH")
            if c13_identity.get("all_identity_valid") is not True or c13_identity.get("expected_run_id") != expected_run_id:
                blockers.append("CANONICAL_RUN_IDENTITY_MISMATCH")

            manifest_entries = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
            for relative, metadata in manifest_entries.items():
                if not isinstance(metadata, Mapping):
                    blockers.append("ARTIFACT_MANIFEST_ENTRY_INVALID")
                    continue
                blob = read_git_blob(repo_root, source_head, f"{c13_root}/{relative}")
                if not blob:
                    blockers.append("ARTIFACT_MANIFEST_FILE_MISSING")
                    continue
                if metadata.get("sha256") != hashlib.sha256(blob).hexdigest() or metadata.get("size_bytes") != len(blob):
                    blockers.append("ARTIFACT_MANIFEST_HASH_MISMATCH")

            summary_bytes = read_git_blob(repo_root, source_head, f"{c13_root}/full_pytest_summary_v01_fix03_correction_13.json")
            source_sha = hashlib.sha256(summary_bytes).hexdigest() if summary_bytes else ""
            if not c13_certification:
                blockers.append("PYTEST_CERTIFICATION_ARTIFACT_MISSING")
            elif c13_certification.get("source_summary_sha256") != source_sha:
                blockers.append("PYTEST_SUMMARY_SHA_MISMATCH")
            elif c13_certification.get("certification_valid") is not True:
                blockers.append("FULL_PYTEST_CERTIFICATION_INVALID")
            elif (
                c13_certification.get("expected_fix_head") != fix_head
                or c13_certification.get("expected_fix_tree_sha") != str(binding.get("fix_tree_sha", ""))
                or c13_certification.get("observed_test_head") != regression_certification.code_head_under_test
                or c13_certification.get("observed_test_tree") != regression_certification.code_tree_sha_under_test
            ):
                blockers.append("PYTEST_CERTIFICATION_BINDING_MISMATCH")

            # Re-run linkage against the final C13 rows/logs rather than
            # accepting a stage validation result copied into Gate06.
            raw_entries = list(c13_raw_manifest.get("artifacts", {}).values()) if isinstance(c13_raw_manifest.get("artifacts"), dict) else []
            with tempfile.TemporaryDirectory(prefix="c13-render-linkage-") as linkage_dir_name:
                linkage_dir = Path(linkage_dir_name)
                raw_dir = linkage_dir / "raw"
                raw_dir.mkdir()
                for entry in raw_entries:
                    raw_path = str(entry.get("path", entry.get("raw_path", ""))) if isinstance(entry, Mapping) else ""
                    raw_name = Path(raw_path).name
                    if raw_name:
                        blob = read_git_blob(repo_root, source_head, f"{c13_root}/raw/{raw_name}")
                        if blob:
                            (raw_dir / raw_name).write_bytes(blob)
                final_linkage = validate_live_evidence_linkage(
                    canonical_run_id=expected_run_id,
                    discovery_records=read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_official_discovery_v01_fix03_correction_13.csv"),
                    document_records=read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_official_document_validation_v01_fix03_correction_13.csv"),
                    raw_manifest_entries=raw_entries,
                    authority_rows=c13_authority.get("records", []) if isinstance(c13_authority.get("records"), list) else [],
                    request_logs=request_logs,
                    price_request_logs=[row for row in request_logs if row.get("source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}],
                    artifact_paths={"raw": raw_dir},
                    current_output_dir=linkage_dir,
                    accounting_cross_invariant_pass=bool(read_git_json(repo_root, source_head, f"{c13_root}/corporate_action_evidence_network_accounting_v01_fix03_correction_13.json").get("accounting_cross_invariant_pass", False)),
                    schema_suffix="13",
                )
            final_link_metrics = final_linkage.to_metrics()
            for key in ("linkage_evaluation_status", "all_linkage_valid", "producing_request_failure_count", "cross_run_request_linkage_failure_count", "invalid_retrieval_mode_count", "record_identity_failure_count", "issuer_identity_failure_count", "candidate_linkage_failure_count", "pykrx_linkage_failure_count", "historical_raw_reuse_count", "physical_request_mutation_failure_count", "live_lineage_failure_count", "raw_orphan_file_count", "total_provenance_failure_count"):
                if c13_link.get(key) != final_link_metrics.get(key):
                    blockers.append("FINAL_LINKAGE_RECOMPUTATION_MISMATCH")
            if not final_linkage.all_linkage_valid:
                blockers.append("FINAL_C13_LINKAGE_INVALID")

            # Materialize Git blobs in a temporary directory solely for an
            # independent metric recomputation; no repository files are changed.
            with tempfile.TemporaryDirectory(prefix="c13-render-audit-") as audit_dir_name:
                audit_dir = Path(audit_dir_name)
                known_files = {
                    "corporate_action_review_cohort_v01_fix03_correction_13.csv": cohort_rows,
                    "corporate_action_event_price_rows_v01_fix03_correction_13.csv": price_rows,
                    "corporate_action_event_sensitive_parity_v01_fix03_correction_13.csv": parity_rows,
                    "corporate_action_date_reconciliation_v01_fix03_correction_13.csv": reconciliation_rows,
                    "corporate_action_document_probe_audit_v01_fix03_correction_13.csv": read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_document_probe_audit_v01_fix03_correction_13.csv"),
                    "corporate_action_discovery_candidate_audit_v01_fix03_correction_13.csv": read_git_csv(repo_root, source_head, f"{c13_root}/corporate_action_discovery_candidate_audit_v01_fix03_correction_13.csv"),
                }
                for name, rows in known_files.items():
                    target = audit_dir / name
                    with target.open("w", encoding="utf-8", newline="") as handle:
                        if rows:
                            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                            writer.writeheader(); writer.writerows(rows)
                audit_result = audit_c13_metric_provenance(
                    audit_dir,
                    gate_payload=c13_gate,
                    decision_payload=decision,
                    validation=persisted,
                    linkage=final_linkage,
                    accounting=read_git_json(repo_root, source_head, f"{c13_root}/corporate_action_evidence_network_accounting_v01_fix03_correction_13.json"),
                )
                if audit_result.get("verdict") != "COMPLETE" or c13_audit.get("verdict") != "COMPLETE":
                    blockers.append("METRIC_AUDIT_INCOMPLETE")
                if c13_audit.get("recomputed_metrics") != audit_result.get("recomputed_metrics"):
                    blockers.append("METRIC_PROVENANCE_RECOMPUTATION_MISMATCH")
        review_decision = decision.get("review_decision")
        authorized = decision.get("production_integration_authorized")
        terminal_next_states = {
            "APPROVED_FOR_PRODUCTION_INTEGRATION": "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01",
            "CONDITIONAL_REVIEW_REQUIRED": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_13",
            "REJECTED_AS_PRODUCTION_AUTHORITY": "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01",
        }
        if review_decision not in terminal_next_states or decision.get("recommended_next_state") != terminal_next_states.get(review_decision):
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        if review_decision == "APPROVED_FOR_PRODUCTION_INTEGRATION":
            if authorized is not True or decision.get("all_gates_passed") is not True or decision.get("gate_06_result") is not True or decision.get("gate_15_result") is not True:
                blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        elif authorized is not False or decision.get("all_gates_passed") is not False or decision.get("gate_06_result") is not False or decision.get("gate_15_result") is not False:
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        if decision.get("gate_06_result") is not c13_gate.get("gate_06_pass"):
            blockers.append("DECISION_INTERNAL_INCONSISTENCY")
        if c13_audit.get("verdict") != "COMPLETE" or c13_audit.get("all_metrics_audited") is not True:
            blockers.append("METRIC_AUDIT_INCOMPLETE")
        if regression_certification.certification_valid is not True:
            blockers.append("FULL_PYTEST_CERTIFICATION_INVALID")
        rows_loaded = c13_audit.get("rows_loaded") if isinstance(c13_audit.get("rows_loaded"), dict) else {}
        if rows_loaded.get("parity") != len(parity_rows) or rows_loaded.get("reconciliation") != len(reconciliation_rows):
            blockers.append("METRIC_AUDIT_INCOMPLETE")
    return {
        "report_truth_sync": "PASS" if not blockers else "FAIL",
        "production_certification_valid": not blockers,
        "code_equiv_self_verified": not any(
            b in blockers
            for b in (
                "FIX_HEAD_MISSING", "END_HEAD_MISSING", "BINDING_END_HEAD_MISMATCH",
                "END_HEAD_SELF_REFERENCE_FORBIDDEN", "FIX_TREE_SHA_MISMATCH", "END_TREE_SHA_MISMATCH",
                "TESTED_CODE_HEAD_MISMATCH", "TESTED_CODE_TREE_SHA_MISMATCH", "CODE_SCOPE_MISMATCH",
                "CODE_DIFF_NOT_EMPTY", "CODE_TEST_BINDING_FAILURE", "SELF_DECLARED_CODE_EQUIVALENCE_FORBIDDEN", "CODE_DIFF_DETECTED",
            )
        ),
        "blockers": blockers,
        "fix_head": fix_head,
        "end_head": source_head,
        "fix_tree_sha": actual_fix_tree,
        "end_tree_sha": actual_end_tree,
    }


def derive_authority_closed(decision: dict[str, Any], truth_sync: dict[str, Any]) -> bool:
    """Derive closure solely from explicit approval gates and truth-sync evidence."""
    schema = str(decision.get("schema", ""))
    regression_required = schema.endswith("correction_12") or schema.endswith("correction_13")
    return bool(
        truth_sync.get("report_truth_sync") == "PASS"
        and decision.get("all_gates_passed") is True
        and decision.get("gate_06_result") is True
        and decision.get("gate_15_result") is True
        and decision.get("production_integration_authorized") is True
        and decision.get("review_decision") == "APPROVED_FOR_PRODUCTION_INTEGRATION"
        and (
            not regression_required
            or (
                decision.get("full_suite_completion") is True
                and decision.get("new_regression_count") == 0
            )
        )
    )


def render_report(repo_root: Path, commit_head: str, output_file: Path) -> None:
    root = "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence"
    fix13_rel = f"{root}/v01_fix03_correction_13"
    fix12_rel = f"{root}/v01_fix03_correction_12"
    fix11_rel = f"{root}/v01_fix03_correction_11"
    fix10_rel = f"{root}/v01_fix03_correction_10"
    fix9_rel = f"{root}/v01_fix03_correction_9"
    if read_git_blob(repo_root, commit_head, f"{fix13_rel}/artifact_manifest.json"):
        base_rel, suffix = fix13_rel, "13"
    elif read_git_blob(repo_root, commit_head, f"{fix12_rel}/artifact_manifest.json"):
        base_rel, suffix = fix12_rel, "12"
    elif read_git_blob(repo_root, commit_head, f"{fix11_rel}/artifact_manifest.json"):
        base_rel, suffix = fix11_rel, "11"
    elif read_git_blob(repo_root, commit_head, f"{fix10_rel}/artifact_manifest.json"):
        base_rel, suffix = fix10_rel, "10"
    else:
        base_rel, suffix = fix9_rel, "9"
    file_for = lambda stem: f"{base_rel}/{stem}_v01_fix03_correction_{suffix}.json"

    manifest_bytes = read_git_blob(repo_root, commit_head, f"{base_rel}/artifact_manifest.json")
    manifest = json.loads(manifest_bytes.decode("utf-8")) if manifest_bytes else {}
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest() if manifest_bytes else ""
    dec_bytes = read_git_blob(repo_root, commit_head, file_for("adjusted_price_source_authority_corporate_action_evidence"))
    decision = json.loads(dec_bytes.decode("utf-8")) if dec_bytes else {}
    dec_sha = hashlib.sha256(dec_bytes).hexdigest() if dec_bytes else ""
    binding = read_git_json(repo_root, commit_head, file_for("code_test_binding_evidence"))
    pytest_json = read_git_json(repo_root, commit_head, file_for("full_pytest_summary"))
    truth = evaluate_report_truth_sync(repo_root, commit_head, manifest, decision, binding, pytest_json)
    freeze_json = read_git_json(repo_root, commit_head, file_for("parent_authority_freeze_validation"))
    net_json = read_git_json(repo_root, commit_head, file_for("corporate_action_evidence_network_accounting"))
    link_json = read_git_json(repo_root, commit_head, file_for("live_evidence_linkage_validation"))
    gate06_json = read_git_json(repo_root, commit_head, file_for("gate06_corporate_action_reassessment"))
    preflight_json = read_git_json(repo_root, commit_head, file_for("opendart_preflight"))
    doc_ready_json = read_git_json(repo_root, commit_head, file_for("opendart_document_readiness"))
    metric_audit = read_git_json(repo_root, commit_head, f"{base_rel}/gate06_metric_provenance_audit_v01_fix03_correction_{suffix}.json")
    mocked_success = read_git_json(repo_root, commit_head, f"{base_rel}/mocked_full_success_orchestration_v01_fix03_correction_{suffix}.json")
    truth["blockers"] = list(dict.fromkeys(truth["blockers"]))

    all_15_gates = decision.get("all_15_gate_results", {})
    passed_gates = sum(1 for value in all_15_gates.values() if value is True)
    total_gates = len(all_15_gates) if all_15_gates else 15
    authority_closed = derive_authority_closed(decision, truth)
    reason_codes = decision.get("reason_codes") if isinstance(decision.get("reason_codes"), list) else truth["blockers"]

    lines = [
        f"# Corporate Action Authority Evidence & Gate 06/15 Report (v01_fix03_correction_{suffix})\n",
        "## 1. Directive / Binding\n",
        f"- Directive: `{decision.get('directive_id', '')}`",
        f"- Parent: `{decision.get('parent_directive', '')}`",
        f"- START_HEAD: `{decision.get('start_head', '')}`",
        f"- FIX_HEAD: `{truth['fix_head']}`",
        f"- FIX_TREE_SHA: `{truth['fix_tree_sha']}`",
        f"- END_HEAD: `{commit_head}`",
        f"- END_TREE_SHA: `{truth['end_tree_sha']}`",
        "- Working Branch: `codex/end-to-end-data-parity-v01`",
        f"- Canonical Run ID: `{decision.get('canonical_run_id', '')}`",
        f"- Artifact Manifest SHA256: `{manifest_sha}`",
        f"- Canonical Decision SHA256: `{dec_sha}`",
        f"- Report Truth Sync: `{truth['report_truth_sync']}`",
        f"- Production Certification Valid: `{truth['production_certification_valid']}`",
        f"- Code Equivalence Self-Verified: `{truth['code_equiv_self_verified']}`",
        "\n---\n",
        "## 2. Implementation / Test Verdict\n",
        f"- Full pytest completion: `{pytest_json.get('full_suite_completion')}`; passed/failed/skipped: `{pytest_json.get('passed')}` / `{pytest_json.get('failed')}` / `{pytest_json.get('skipped')}`",
        f"- Known baseline failures: `{len(pytest_json.get('known_baseline_failures', []))}`",
        f"- New regressions: `{pytest_json.get('new_regression_count')}`",
        f"- Mocked full-success orchestration: `{mocked_success.get('verdict', 'NOT_RECORDED')}`",
        f"- Gate06 metric audit: `{metric_audit.get('verdict', metric_audit.get('all_metrics_audited', 'NOT_RECORDED'))}`",
        "\n---\n",
        "## 3. Preflight / Readiness / Accounting\n",
        f"- OpenDART preflight: `{preflight_json.get('verdict', 'NOT_EXECUTED')}`",
        f"- Document readiness: `{doc_ready_json.get('verdict', 'NOT_EXECUTED')}`",
        f"- Physical calls preflight/readiness/downstream/grand total: `{net_json.get('preflight_physical_calls')}` / `{net_json.get('readiness_physical_calls')}` / `{net_json.get('downstream_logged_physical_calls')}` / `{net_json.get('grand_total_physical_external_calls')}`",
        f"- Accounting cross-invariant: `{net_json.get('accounting_cross_invariant_pass')}`",
        f"- Parent freeze: `{freeze_json.get('all_parent_inputs_unchanged')}`",
        "\n---\n",
        "## 4. Evidence / Cohort / Linkage\n",
        f"- Official documents manifest/success/authority-valid: `{decision.get('official_document_manifest_entry_count')}` / `{decision.get('official_document_success_count')}` / `{decision.get('authority_valid_control_count')}`",
        f"- Frozen cohort size: `{decision.get('final_cohort_size')}`",
        f"- Linkage evaluation: `{link_json.get('linkage_evaluation_status')}`; all valid: `{link_json.get('all_linkage_valid')}`; total failures: `{link_json.get('total_linkage_failures')}`",
        f"- Linkage counters: producing `{link_json.get('producing_request_failure_count')}`, cross-run `{link_json.get('cross_run_request_linkage_failure_count')}`, retrieval `{link_json.get('invalid_retrieval_mode_count')}`, identity `{link_json.get('record_identity_failure_count')}`, issuer `{link_json.get('issuer_identity_failure_count')}`, candidate `{link_json.get('candidate_linkage_failure_count')}`, PyKRX `{link_json.get('pykrx_linkage_failure_count')}`, historical `{link_json.get('historical_raw_reuse_count')}`, mutation `{link_json.get('physical_request_mutation_failure_count')}`, lineage `{link_json.get('live_lineage_failure_count')}`, orphan `{link_json.get('raw_orphan_file_count')}`",
        f"- Naver / PyKRX requests: `{decision.get('naver_actual_requests')}` / `{decision.get('raw_pykrx_actual_queries')}`",
        f"- Exact parity / date mismatch / OHLC mismatch: `{decision.get('exact_date_match_controls')}` / `{decision.get('date_mismatch_controls')}` / `{decision.get('ohlc_mismatch_controls')}`",
        "\n---\n",
        "## 5. Gates / Decision\n",
        f"- Gate summary: `{passed_gates}/{total_gates}`; Gate06 `{decision.get('gate_06_result')}`; Gate15 `{decision.get('gate_15_result')}`",
        f"- Gate06 payload: `{gate06_json.get('gate_06_pass')}`",
        f"- Review decision: `{decision.get('review_decision')}`",
        f"- Production integration authorized: `{decision.get('production_integration_authorized')}`",
        f"- Active production authority changed: `{decision.get('active_production_authority_changed')}`",
        f"- Recommended next state: `{decision.get('recommended_next_state')}`",
    ]
    if suffix == "13":
        lines.extend([
            "- Full Repository Pytest: `NOT EXECUTED` (forbidden during C13 review-candidate development)",
            "- Live external calls: `0`; C13 canonical live artifacts: `NOT CREATED`",
            "- FINAL_FIX_HEAD: `NOT DESIGNATED`; C13 END_HEAD: `NOT CREATED`",
            f"- Persisted price evidence status: `{decision.get('persisted_price_evidence_status', 'NOT_RECORDED')}`",
            f"- Persisted price rows Naver/PyKRX: `{decision.get('actual_candidate_price_row_count')}` / `{decision.get('actual_pykrx_price_row_count')}`",
        ])
    if "CODE_TEST_BINDING_FAILURE" in truth["blockers"] or truth["report_truth_sync"] == "FAIL":
        lines.extend(["\n**CODE/TEST BINDING FAILURE — REPORT IS FAIL-CLOSED**\n", f"- Truth-sync blockers: `{truth['blockers']}`"])
    lines.extend([
        f"- Authority Closure Status: `{'CLOSED' if authority_closed else 'NOT CLOSED'}` (Reason: `{', '.join(str(x) for x in reason_codes)}`)",
        "\n---\n",
        "## 6. Offline / Live Boundary\n",
        "- This report is derived from immutable END_HEAD Git objects.",
        "- Live external acquisition is not inferred from mocked evidence; any maintenance-window run remains explicitly NOT EXECUTED.",
    ])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report successfully rendered to {output_file} from HEAD {commit_head}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True, help="Git commit head")
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    parser.add_argument("--output", default="artifacts/data/r.md", help="Output path")
    args = parser.parse_args()
    render_report(Path(args.repo_root), args.head, Path(args.output))
