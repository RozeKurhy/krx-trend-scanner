#!/usr/bin/env python3
"""Read-only persisted-output audit for the former P3-2-only 380440 exception."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
AUDIT_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_380440_single_period_exclusion_v01"
TARGET = ("380440", "KR7380440008")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def identity_columns(frame: pd.DataFrame) -> tuple[str | None, str | None]:
    ticker = next((name for name in ("ticker", "ticker_code") if name in frame.columns), None)
    isu = next((name for name in ("isu_cd", "standard_isu_cd") if name in frame.columns), None)
    return ticker, isu


def main() -> int:
    input_audit_path = AUDIT_DIR / "artifact_invariance_audit.csv"
    previous_gate_path = AUDIT_DIR / "gate_results.json"
    previous_scope_path = AUDIT_DIR / "scope_decision.json"
    input_audit = pd.read_csv(input_audit_path, keep_default_na=False)
    gate = json_read(previous_gate_path)
    scope = json_read(previous_scope_path)
    file_rows: list[dict] = []
    missing_files: list[str] = []
    target_transaction_rows = 0
    target_diagnostic_rows = 0
    event_artifact_rows = 0
    event_artifact_hash_mismatches: list[str] = []
    all_hash_mismatches: list[str] = []
    for row in input_audit.to_dict("records"):
        relative = str(row["source_file"])
        path = ROOT / relative
        expected_hash = str(row.get("sha256", ""))
        exists = path.is_file()
        actual_hash = sha(path) if exists else None
        hash_matches = bool(exists and actual_hash == expected_hash)
        if not exists:
            missing_files.append(relative)
        elif not hash_matches:
            all_hash_mismatches.append(relative)
        is_event = str(row.get("event_or_portfolio_artifact", "")).strip().lower() == "true"
        exact_rows = 0
        scanned_exact = False
        if exists and path.suffix.lower() == ".csv":
            try:
                frame = pd.read_csv(path, keep_default_na=False)
            except pd.errors.EmptyDataError:
                frame = pd.DataFrame()
            tcol, icol = identity_columns(frame)
            if tcol and icol:
                scanned_exact = True
                tickers = frame[tcol].astype(str).str.strip().str.zfill(6)
                isu_values = frame[icol].astype(str).str.strip().str.upper()
                exact_rows = int(((tickers == TARGET[0]) & (isu_values == TARGET[1])).sum())
                if is_event:
                    target_transaction_rows += exact_rows
                else:
                    target_diagnostic_rows += exact_rows
        if is_event:
            event_artifact_rows += 1
            if not hash_matches:
                event_artifact_hash_mismatches.append(relative)
        file_rows.append({
            "source_set": row.get("source_set"),
            "path": relative,
            "expected_sha256": expected_hash,
            "current_sha256": actual_hash,
            "hash_matches_prior_audit": hash_matches,
            "event_or_portfolio_artifact": is_event,
            "identity_columns_scanned": scanned_exact,
            "target_exact_pair_rows": exact_rows,
        })
    pd.DataFrame(file_rows).to_csv(OUT / "p3_2_policy_consistency_artifact_audit.csv", index=False)

    registry_path = ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"
    sys.path.insert(0, str(ROOT / "src"))
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

    policy_count = len(PERMANENT_IDENTITY_EXCLUSIONS)
    policy_contains_target = TARGET in PERMANENT_IDENTITY_EXCLUSIONS
    prior_gate_status = {
        "CONTROL_A": gate.get("CONTROL", {}).get("A_integrity"),
        "ALIGNMENT_MCAP_500B_A": gate.get("ALIGNMENT_MCAP_500B", {}).get("A_integrity"),
    }
    def status_value(value):
        return value.get("status") if isinstance(value, dict) else value
    result = {
        "schema": "fast_core_v2_alignment_500b_p3_1_p3_2_policy_consistency_audit_v01",
        "scope": "Read-only consistency check; no P3-2 signal generation, portfolio replay, or gate rewrite.",
        "target_identity": {"ticker": TARGET[0], "isu_cd": TARGET[1]},
        "global_policy": {
            "registry_path": str(registry_path.relative_to(ROOT)),
            "registry_source_sha256": sha(registry_path),
            "current_pair_count": policy_count,
            "target_registered_exactly": policy_contains_target,
            "P3_2_former_single_period_policy_conflict": scope.get("official_policy_compatibility", {}).get("status"),
            "future_common_policy_status": "SATISFIES_COMMON_PERMANENT_EXCLUSION_RULE" if policy_contains_target else "CHECK_REQUIRED",
        },
        "persisted_p3_2_outputs": {
            "artifact_rows_in_prior_invariance_audit": int(len(input_audit)),
            "artifact_hashes_rechecked": sum(bool(row["hash_matches_prior_audit"]) for row in file_rows),
            "artifact_hash_mismatches": all_hash_mismatches,
            "missing_artifacts": missing_files,
            "event_portfolio_artifacts_checked": event_artifact_rows,
            "event_portfolio_hash_mismatches": event_artifact_hash_mismatches,
            "target_exact_pair_transaction_or_portfolio_rows": int(target_transaction_rows),
            "target_exact_pair_diagnostic_rows": int(target_diagnostic_rows),
            "persisted_transaction_and_metric_delta_from_global_filter": 0 if target_transaction_rows == 0 else None,
            "hypothetical_complete_data_signal_effect": "UNKNOWN_NOT_EVALUATED",
        },
        "historical_p3_2_gate_record": {
            "file_sha256": sha(previous_gate_path),
            "scope_decision_sha256": sha(previous_scope_path),
            "prior_gate_status_unchanged": prior_gate_status,
            "prior_a_status_remains_check_required": all(
                status_value(value) == "CHECK_REQUIRED"
                for value in prior_gate_status.values()
            ),
            "prior_artifact_modified": False,
        },
        "decision": {
            "p3_2_rerun": False,
            "p3_2_prior_results_overwritten": False,
            "scope_exception_reconciled_for_future_runs": policy_contains_target,
            "p3_2_a_gate_automatically_promoted": False,
            "p3_2_persisted_outputs_unchanged": not all_hash_mismatches and not missing_files and target_transaction_rows == 0,
            "limitation": "The missing adjusted-price input prevents measuring what 380440 would have signaled; zero stored rows proves only persisted-output invariance, not zero hypothetical signal effect.",
        },
    }
    (OUT / "p3_2_policy_consistency_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "registry_count": policy_count,
        "registered": policy_contains_target,
        "audited_artifacts": len(file_rows),
        "event_artifacts": event_artifact_rows,
        "hash_mismatches": len(all_hash_mismatches),
        "target_transaction_rows": target_transaction_rows,
        "target_diagnostic_rows": target_diagnostic_rows,
        "P3_2_rerun": False,
        "P3_2_prior_A_status": prior_gate_status,
    }, ensure_ascii=False, indent=2))
    return 0 if not missing_files and not all_hash_mismatches and target_transaction_rows == 0 and policy_contains_target else 2


if __name__ == "__main__":
    raise SystemExit(main())
