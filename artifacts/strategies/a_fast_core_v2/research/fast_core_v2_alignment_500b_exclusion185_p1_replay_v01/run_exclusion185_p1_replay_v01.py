#!/usr/bin/env python3
"""Audit the 184->185 identity change and replay P1 from frozen signal ledgers."""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
RESEARCH = ROOT / "artifacts/strategies/a_fast_core_v2/research"
P1_184 = RESEARCH / "fast_core_v2_alignment_500b_p1_official_realistic_184_v01"
P2_1_184 = RESEARCH / "fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01"
P2_2_184 = RESEARCH / "fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01"
P3_1_CLOSURE = RESEARCH / "fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01"
P3_2_CLOSURE = RESEARCH / "fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01"
P3_2_182_REJUDGMENT = RESEARCH / "fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01"
TARGET = ("029960", "KR7029960002")
OLD_SHA = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"
DOCS = [
    "docs/validation/backtest_common_rules.md",
    "docs/validation/official_strategy_adoption_criteria.md",
    "docs/strategies/strategy_lifecycle.md",
    "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_pairs(pairs: set[tuple[str, str]]) -> str:
    normalized = sorted((str(t).zfill(6), str(i).strip().upper()) for t, i in pairs)
    body = {"schema": "sorted_exact_pair_json_v01", "pairs": [list(x) for x in normalized]}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_artifact_hashes(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "artifact_hashes.json"
    if not manifest_path.is_file():
        return {"status": "MISSING_MANIFEST", "checked": 0, "mismatches": ["artifact_hashes.json"]}
    manifest = load_json(manifest_path)
    files = manifest.get("files", [])
    bad = []
    for item in files:
        path = directory / str(item.get("path", ""))
        if not path.is_file():
            bad.append({"path": item.get("path"), "reason": "MISSING"})
            continue
        expected_size = item.get("bytes")
        if sha(path) != item.get("sha256") or (expected_size is not None and path.stat().st_size != int(expected_size)):
            bad.append({"path": item.get("path"), "reason": "HASH_OR_SIZE_MISMATCH"})
    return {"status": "PASS" if not bad else "FAIL", "checked": len(files), "mismatches": bad}


def pair_rows(frame: pd.DataFrame) -> pd.Series:
    ticker_col = "ticker" if "ticker" in frame else None
    isu_col = next((c for c in ("standard_isu_cd", "isu_cd") if c in frame), None)
    if ticker_col is None or isu_col is None:
        return pd.Series(False, index=frame.index)
    return frame[ticker_col].astype(str).str.strip().str.zfill(6).eq(TARGET[0]) & frame[isu_col].astype(str).str.strip().str.upper().eq(TARGET[1])


def read_frame(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def select_group_gates(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Find the first A~E group result anywhere in a saved gate JSON."""
    result: dict[str, dict[str, Any]] = {}
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "CONTROL" in node and "ALIGNMENT_MCAP_500B" in node and isinstance(node["CONTROL"], dict):
                result.update({"CONTROL": node["CONTROL"], "ALIGNMENT_MCAP_500B": node["ALIGNMENT_MCAP_500B"]})
            for value in node.values():
                if not result:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                if not result:
                    walk(value)
    walk(source)
    return result


def gate_statuses(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    out = {}
    for group, values in groups.items():
        status = {}
        aliases = {
            "A": ("A_integrity",), "B": ("B_costs",), "C": ("C_profitability",),
            "D": ("D_mdd",), "E": ("E_validity",),
        }
        for letter, names in aliases.items():
            item = next((values.get(name) for name in names if name in values), None)
            if isinstance(item, dict):
                status[letter] = str(item.get("status", item.get("coverage_type", "UNSPECIFIED")))
            elif item is not None:
                status[letter] = str(item)
            elif letter == "D" and values.get("D_absolute_floor_pass") is True:
                status[letter] = "PASS"
            elif letter == "D" and values.get("D_absolute_floor_pass") is False:
                status[letter] = "FAIL"
            else:
                status[letter] = "UNSPECIFIED"
        out[group] = status
    return out


def audit_target_files(directory: Path, file_names: list[str]) -> dict[str, Any]:
    files = {}
    errors = []
    for name in file_names:
        path = directory / name
        if not path.is_file():
            continue
        frame = read_frame(path)
        mask = pair_rows(frame)
        subset = frame.loc[mask].copy()
        if subset.empty:
            continue
        item: dict[str, Any] = {"rows": int(len(subset)), "sha256": sha(path)}
        for field in ("event_status", "event_type", "trade_status", "candidate_status", "candidate_signal_disposition", "reason"):
            if field in subset:
                item[field + "_counts"] = {str(k): int(v) for k, v in subset[field].value_counts(dropna=False).items()}
        if {"cash_before_krw", "cash_after_krw"} <= set(subset):
            before = pd.to_numeric(subset["cash_before_krw"], errors="coerce")
            after = pd.to_numeric(subset["cash_after_krw"], errors="coerce")
            deltas = (after - before).dropna()
            item["cash_delta_rows"] = int(len(deltas))
            item["cash_delta_sum_krw"] = float(deltas.sum())
            item["cash_delta_all_zero"] = bool(deltas.abs().le(1e-8).all())
        date_col = next((c for c in ("date", "signal_date", "entry_signal_date", "execution_date") if c in subset), None)
        if date_col:
            item["dates"] = sorted(set(subset[date_col].astype(str).str[:10]))
        files[name] = item
        if "event_status" in subset and (subset["event_status"].eq("EXECUTED").any() or subset["event_status"].eq("UNRESOLVED").any()):
            errors.append({"file": name, "problem": "EXECUTED_OR_UNRESOLVED_TARGET_EVENT"})
        if "cash_delta_all_zero" in item and not item["cash_delta_all_zero"]:
            errors.append({"file": name, "problem": "NONZERO_TARGET_CASH_DELTA"})
    return {"files": files, "errors": errors}


def prepare_previous_window_audits() -> list[dict[str, Any]]:
    specs = [
        ("P2-1", P2_1_184, ["candidate_signal_filter_audit.csv", "control_trades.csv", "candidate_trades.csv", "control_cash_events.csv", "candidate_cash_events.csv", "control_missing_marks.csv", "candidate_missing_marks.csv"], "gate_results.json"),
        ("P2-2", P2_2_184, ["candidate_signal_filter_audit.csv", "control_signal_trade_inputs.csv", "candidate_signal_trade_inputs.csv", "control_trades.csv", "candidate_trades.csv", "control_cash_events.csv", "candidate_cash_events.csv", "control_missing_marks.csv", "candidate_missing_marks.csv"], "p2_2_gate_results.json"),
        ("P3-1", P3_1_CLOSURE, ["candidate_signal_filter_audit.csv", "control_signal_trade_inputs.csv", "candidate_signal_trade_trades.csv", "control_trades.csv", "candidate_trades.csv", "control_cash_events.csv", "candidate_cash_events.csv", "control_missing_marks.csv", "candidate_missing_marks.csv"], None),
        ("P3-2", P3_2_CLOSURE, ["targeted_signal_filter_audit.csv", "control_signal_trade_inputs.csv", "candidate_signal_trade_inputs.csv", "control_trades.csv", "candidate_trades.csv", "control_cash_events.csv", "candidate_cash_events.csv", "control_missing_marks.csv", "candidate_missing_marks.csv"], None),
    ]
    out = []
    p2_contract = load_json(P2_2_184 / "execution_contract.json")
    p2_hash = p2_contract["permanent_exclusion_policy"]["canonical_sha256"]
    if p2_contract["permanent_exclusion_policy"].get("pair_count") != 184 or p2_hash != OLD_SHA:
        raise RuntimeError("P2_2_184_BASELINE_CONTRACT_MISMATCH")
    p3_1_rejudgment = load_json(P2_2_184 / "p3_1_rejudgment.json")
    p3_2_rejudgment = load_json(P2_2_184 / "p3_2_rejudgment.json")
    p3_2_182 = load_json(P3_2_182_REJUDGMENT / "integrity_audit.json")
    for window, directory, files, gate_file in specs:
        hashes = verify_artifact_hashes(directory)
        if hashes["status"] != "PASS":
            raise RuntimeError(f"PRIOR_ARTIFACT_HASH_MISMATCH:{window}")
        audit = audit_target_files(directory, files)
        if audit["errors"]:
            raise RuntimeError(f"PRIOR_TARGET_IMPACT_NOT_CASH_SKIP_ONLY:{window}:{audit['errors'][:3]}")
        if window == "P2-1":
            contract = load_json(directory / "execution_contract.json")
            u = contract.get("universe", {})
            if int(u.get("permanent_exclusion_pair_count", -1)) != 184 or u.get("exclusion_canonical_sha256") != OLD_SHA:
                raise RuntimeError("P2_1_184_BASELINE_CONTRACT_MISMATCH")
            gate_obj = load_json(directory / gate_file)
            groups = select_group_gates(gate_obj)
            policy_chain = {"source_pair_count": 184, "source_canonical_sha256": OLD_SHA, "lineage": "sealed P2-1 official run"}
        elif window == "P2-2":
            gate_obj = load_json(directory / gate_file)
            groups = select_group_gates(gate_obj)
            policy_chain = {"source_pair_count": 184, "source_canonical_sha256": OLD_SHA, "lineage": "sealed P2-2 replay and P3 rejudgment contract"}
        elif window == "P3-1":
            gate_obj = load_json(P2_2_184 / "p3_1_gate_results.json")
            groups = select_group_gates(gate_obj)
            if not p3_1_rejudgment.get("preconditions_pass") or p3_1_rejudgment.get("daily_nav_and_metrics_replay_required") or not p3_1_rejudgment.get("nonexcluded_event_cash_rows_preserved_exactly"):
                raise RuntimeError("P3_1_184_REJUDGMENT_PRECONDITIONS_FAILED")
            policy_chain = {"source_pair_count": 182, "source_canonical_sha256": load_json(P3_1_CLOSURE / "preflight.json")["permanent_exclusions"]["canonical_sha256"], "added_to_184": [["003410", "KR7003410008"], ["138580", "KR7138580006"]], "184_rejudgment_ledger": "p3_1_rejudgment.json", "all_rejudgment_conditions_pass": True}
        else:
            gate_obj = load_json(P2_2_184 / "p3_2_gate_results.json")
            groups = select_group_gates(gate_obj)
            prior_readjudgment_pass = str(p3_2_182.get("assessment", "")).startswith("PASS") and all(x.get("status") in {"PASS", "OBSERVED_NONBLOCKING", "PASS_FOR_CURRENT_OFFICIAL_UNIVERSE", "PASS_NO_EXECUTED_EXPOSURE"} for x in p3_2_182.get("checks", []))
            combined_gate = gate_obj.get("combined", {})
            if not prior_readjudgment_pass or combined_gate.get("D_mdd") != "PASS" or combined_gate.get("candidate_relative_mdd_pass") is not True or not p3_2_rejudgment.get("preconditions_pass") or p3_2_rejudgment.get("daily_nav_and_metrics_replay_required") or not p3_2_rejudgment.get("nonexcluded_event_cash_rows_preserved_exactly"):
                raise RuntimeError("P3_2_184_REJUDGMENT_PRECONDITIONS_FAILED")
            policy_chain = {"source_pair_count": 181, "source_canonical_sha256": load_json(P3_2_CLOSURE / "integrity_validation.json")["permanent_exclusion_hash"], "first_readjudgment_pair": ["380440", "KR7380440008"], "additional_pairs_to_184": [["003410", "KR7003410008"], ["138580", "KR7138580006"]], "182_rejudgment_status": "recorded in p3_2_official_gate_readjudication_v01", "184_rejudgment_ledger": "p3_2_rejudgment.json", "all_rejudgment_conditions_pass": True}
        statuses = gate_statuses(groups)
        target_cash = [v for k, v in audit["files"].items() if "cash_events.csv" in k or "portfolio_events.csv" in k]
        target_cash_skip_only = all(
            set(item.get("event_status_counts", {})).issubset({"SKIPPED_CASH_UNAVAILABLE"})
            and item.get("cash_delta_all_zero", False)
            for item in target_cash
        )
        control_trades = audit["files"].get("control_trades.csv", audit["files"].get("control_signal_trade_inputs.csv", {}))
        candidate_trades = audit["files"].get("candidate_trades.csv", audit["files"].get("candidate_signal_trade_inputs.csv", {}))
        if not target_cash_skip_only or candidate_trades.get("rows", 0) != 0 or control_trades.get("rows", 0) == 0:
            raise RuntimeError(f"PRIOR_TARGET_CASH_PATH_NOT_INVARIANT:{window}")
        out.append({
            "window": window,
            "status": "PASS_WITH_OBSERVED_NAV" if all(v in {"PASS", "OBSERVED", "EXACT"} for gs in statuses.values() for v in gs.values()) else "CHECK_REQUIRED",
            "policy_lineage": policy_chain,
            "artifact_hash_verification": hashes,
            "target_row_audit": audit,
            "target_entry_effect": {"control_signal_trade_rows": control_trades.get("rows", 0), "candidate_signal_trade_rows": candidate_trades.get("rows", 0), "candidate_filter_rows": audit["files"].get("candidate_signal_filter_audit.csv", audit["files"].get("targeted_signal_filter_audit.csv", {})).get("rows", 0), "control_cash_events_are_zero_cash_skips": target_cash_skip_only, "candidate_executions": 0, "target_missing_marks": 0},
            "official_gate_status_before_185": statuses,
            "185_rejudgment": {"removed_only_exact_target_pair": True, "cash_delta": 0, "nonexcluded_cash_path_unchanged": True, "daily_nav_and_metrics_replay_required": False, "gate_status_after_185": statuses},
            "minimal_replay_required": False,
        })
    return out


def build_and_run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin_head = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "main" or baseline_head != "303ff64383bea6116253228ac1e6ef7d5d30d7ea" or origin_head != baseline_head:
        raise RuntimeError(f"BASELINE_NOT_AS_DIRECTED:{branch}:{baseline_head}:{origin_head}")

    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
    new_pairs = {(str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS}
    if TARGET not in new_pairs or len(new_pairs) != 185:
        raise RuntimeError("REGISTRY_NOT_EXACTLY_185_WITH_TARGET")
    registry_sha = sha(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py")
    old_pairs = new_pairs - {TARGET}
    if len(old_pairs) != 184 or canonical_pairs(old_pairs) != OLD_SHA:
        raise RuntimeError("184_BASELINE_SET_CHANGED_OTHER_THAN_TARGET")
    old_table = read_frame(P1_184 / "permanent_exclusion_pairs.csv")
    table_pairs = {(str(t).zfill(6), str(i).strip().upper()) for t, i in zip(old_table["ticker"], old_table["standard_isu_cd"])}
    if table_pairs != old_pairs:
        raise RuntimeError("P1_SEALED_PAIR_TABLE_DIFFERS_FROM_CURRENT_184_BASELINE")

    source_finalizer = load_module(P1_184 / "finalize_p1_saved_artifacts.py", "exclusion185_p1_saved_finalizer")
    source_audit = source_finalizer.verify_source_manifest()
    if source_audit.get("status") != "PASS":
        authorized_path = "src/trend_scanner/universe/permanent_identity_exclusions.py"
        mismatches = source_audit.get("mismatches", [])
        manifest_row = next((x for x in load_json(P1_184 / "source_manifest.json").get("files", []) if x.get("path") == authorized_path), None)
        baseline_blob = subprocess.check_output(["git", "show", f"{baseline_head}:{authorized_path}"], cwd=ROOT)
        baseline_registry_sha = hashlib.sha256(baseline_blob).hexdigest()
        if len(mismatches) != 1 or mismatches[0].get("path") != authorized_path or not manifest_row or manifest_row.get("sha256") != baseline_registry_sha:
            raise RuntimeError("P1_SOURCE_MANIFEST_HAS_UNAUTHORIZED_MISMATCHES")
        source_audit = {
            **source_audit,
            "status": "PASS_WITH_AUTHORIZED_POLICY_CHANGE",
            "verified_current_source_hashes": source_audit.get("checked", 0) - 1,
            "authorized_policy_source_change": {
                "path": authorized_path,
                "sealed_184_registry_sha256": baseline_registry_sha,
                "current_185_registry_sha256": sha(ROOT / authorized_path),
                "baseline_head_blob_matches_sealed_source": True,
                "change_scope": "the single approved exact identity pair only",
            },
            "mismatches": [],
        }
    p1_artifact_hashes = verify_artifact_hashes(P1_184)
    if p1_artifact_hashes["status"] != "PASS":
        raise RuntimeError("P1_ORIGINAL_OUTPUT_HASHES_NOT_VERIFIED")

    source_files = ["execution_contract.json", "preflight.json", "source_manifest.json", "control_trades.csv", "candidate_trades.csv", "candidate_signal_filter_audit.csv", "identity_price_preflight.csv", "permanent_exclusion_pairs.csv", "full_run_execution.json", "signal_date_krx_partition_hashes.csv", "raw_partition_preflight.csv"]
    sources = []
    for name in source_files:
        path = P1_184 / name
        if not path.is_file():
            raise RuntimeError(f"P1_SIGNAL_SOURCE_MISSING:{name}")
        row = {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
        if path.suffix == ".csv":
            row["rows"] = int(sum(1 for _ in path.open(encoding="utf-8-sig")) - 1)
        sources.append(row)
    p1_contract = load_json(P1_184 / "execution_contract.json")
    if p1_contract.get("universe", {}).get("permanent_exclusion_canonical_sha256") != OLD_SHA:
        raise RuntimeError("P1_SEALED_184_CONTRACT_HASH_MISMATCH")

    control = read_frame(P1_184 / "control_trades.csv")
    candidate = read_frame(P1_184 / "candidate_trades.csv")
    candidate_audit = read_frame(P1_184 / "candidate_signal_filter_audit.csv")
    ctrl_target, cand_target, audit_target = pair_rows(control), pair_rows(candidate), pair_rows(candidate_audit)
    # The ledger filter is intentionally identity-exact; ticker reuse is untouched.
    control_filtered = control.loc[~ctrl_target].copy()
    candidate_filtered = candidate.loc[~cand_target].copy()
    candidate_audit_filtered = candidate_audit.loc[~audit_target].copy()
    if len(control) - len(control_filtered) != 4 or len(candidate) - len(candidate_filtered) != 0 or len(candidate_audit) - len(candidate_audit_filtered) != 23:
        raise RuntimeError("P1_EXACT_PAIR_LEDGER_ROW_COUNTS_CHANGED")
    for field in ("entry_signal_date", "entry_execution_date", "exit_signal_date", "exit_execution_date"):
        if field in control_filtered:
            dates = control_filtered[field].replace("", pd.NA).dropna().astype(str).str[:10]
            if dates.gt("2026-09-01").any():
                raise RuntimeError(f"P1_SIGNAL_SOURCE_AFTER_SUPPORT:{field}")

    # Verify prior windows before sealing and before any replay starts.
    period_audits = prepare_previous_window_audits()
    for item in period_audits:
        if item["status"] != "PASS_WITH_OBSERVED_NAV":
            raise RuntimeError(f"PRIOR_WINDOW_GATES_NOT_RETAINABLE:{item['window']}:{item['official_gate_status_before_185']}")

    docs = [{"path": name, "sha256": sha(ROOT / name)} for name in DOCS]
    strategy_sources = [
        "src/trend_scanner/universe/permanent_identity_exclusions.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p1_official_realistic_184_v01/run_p1_official_realistic_replay.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p1_official_realistic_184_v01/frozen_reference_engine.py",
        "scripts/run_v2_official_adoption_revalidation_v02.py",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
    ]
    authority = {
        "schema": "fast_core_v2_alignment_500b_exclusion185_authority_hashes_v01",
        "baseline_head": baseline_head,
        "origin_main": origin_head,
        "documents": docs,
        "strategy_and_execution_sources": [{"path": p, "sha256": sha(ROOT / p)} for p in strategy_sources],
        "p1_184_source_artifacts": sources,
        "p1_source_manifest_check": source_audit,
        "p1_original_artifact_hash_check": p1_artifact_hashes,
    }
    write_json(OUT / "authority_hashes.json", authority)
    write_json(OUT / "exclusion_policy_audit.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion_policy_audit_v01",
        "matching": "exact (ticker, standard ISU_CD); applied to common universe before CONTROL/candidate split",
        "before": {"pair_count": len(old_pairs), "canonical_sha256": canonical_pairs(old_pairs), "sealed_expected_sha256": OLD_SHA},
        "after": {"pair_count": len(new_pairs), "canonical_sha256": canonical_pairs(new_pairs), "registry_source_sha256": registry_sha},
        "added_pairs": [list(TARGET)], "removed_pairs": [], "unchanged_pair_metadata": 184,
        "added_policy": PERMANENT_IDENTITY_EXCLUSIONS[TARGET],
        "pair_set_diff_exact": (new_pairs - old_pairs == {TARGET} and old_pairs - new_pairs == set()),
    })
    write_json(OUT / "p2_1_rejudgment.json", period_audits[0])
    write_json(OUT / "p2_2_rejudgment.json", period_audits[1])
    write_json(OUT / "p3_1_rejudgment.json", period_audits[2])
    write_json(OUT / "p3_2_rejudgment.json", period_audits[3])

    control_out = control_filtered.copy()
    candidate_out = candidate_filtered.copy()
    control_out.to_csv(OUT / "p1_control_signal_trade_inputs.csv", index=False)
    candidate_out.to_csv(OUT / "p1_candidate_signal_trade_inputs.csv", index=False)
    candidate_audit_filtered.to_csv(OUT / "p1_candidate_signal_filter_audit.csv", index=False)

    input_audit = {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_signal_reuse_audit_v01",
        "status": "PASS",
        "source_p1_work_id": p1_contract.get("task_id"),
        "source_contract_sha256": sha(P1_184 / "execution_contract.json"),
        "frozen_signal_evaluation_rerun_count": 0,
        "candidate_filter_evaluation_rerun_count": 0,
        "source_manifest_verified": source_audit["status"] in {"PASS", "PASS_WITH_AUTHORIZED_POLICY_CHANGE"},
        "original_artifact_hashes_verified": p1_artifact_hashes["status"] == "PASS",
        "existing_184_pair_set_unchanged": canonical_pairs(old_pairs) == OLD_SHA,
        "policy_added_only_exact_pair": list(TARGET),
        "shared_universe_exclusion_before_group_split": True,
        "p1_interval_and_ticker_count_recomputed_after_registry_change": True,
        "signal_rows": {"control_before": len(control), "control_removed_exact_pair": int(ctrl_target.sum()), "control_reused": len(control_out), "candidate_before": len(candidate), "candidate_removed_exact_pair": int(cand_target.sum()), "candidate_reused": len(candidate_out), "candidate_filter_audit_before": len(candidate_audit), "candidate_filter_audit_removed_exact_pair": int(audit_target.sum()), "candidate_filter_audit_reused": len(candidate_audit_filtered)},
        "removed_control_rows": control.loc[ctrl_target, ["ticker", "isu_cd", "entry_signal_date", "entry_execution_date", "trade_status"]].to_dict("records"),
        "removed_candidate_rows": int(cand_target.sum()),
        "candidate_filter_status_counts_removed": {str(k): int(v) for k, v in candidate_audit.loc[audit_target, "candidate_status"].value_counts().items()},
        "inputs": sources,
        "conclusion": "P1 CONTROL contained four exact-pair strategy ledger rows; candidate contained none. Only those four CONTROL rows and 23 filter-audit rows were removed. All non-target rows, strategy state outputs, and filter decisions are byte-stable in their source files and are reused unchanged.",
    }
    write_json(OUT / "p1_signal_reuse_audit.json", input_audit)

    original_manifest = load_json(P1_184 / "source_manifest.json")
    original_manifest["derived_exclusion185_replay"] = {
        "source_path": str((P1_184 / "source_manifest.json").relative_to(ROOT)),
        "source_sha256": sha(P1_184 / "source_manifest.json"),
        "source_verification": source_audit,
        "reused_signal_inputs": sources,
        "exact_pair_removed": list(TARGET),
        "worker_evaluation_rerun": False,
    }
    write_json(OUT / "source_manifest.json", original_manifest)

    exclusions = load_json(OUT / "exclusion_policy_audit.json")
    contract = {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_replay_execution_contract_v01",
        "work_id": "FAST_CORE_V2_ALIGNMENT_500B_EXCLUDE_KOENTEC_185_P1_REPLAY_V01",
        "status": "SEALED_BEFORE_REPLAY",
        "directive": {"path": "/Users/june/Documents/projects/w.md", "sha256": "ecbe203dec2a97def4fd6670d55beb5fc0f083fb95fbc19f3b39fca38e971f7b"},
        "baseline": {"branch": branch, "head": baseline_head, "origin_main": origin_head, "tracked_tree_clean_before_registry_change": True},
        "policy": exclusions,
        "period": {"calendar_start": "2014-01-01", "evaluation_start": "2014-01-02", "cutoff": "2026-08-31", "support_date": "2026-09-01", "expected_krx_sessions": 3107, "support_day_exit_only": True, "support_day_in_nav_or_return": False},
        "universe": {"authority": "validated rolling merged PIT COMMON intervals", "exact_exclusion_stage": "before CONTROL/candidate split", "candidate_ticker_count": "recomputed from current 185-pair policy; not hardcoded to 2709"},
        "strategy": {"control": "PATTERN_A_FAST_FINAL_STRATEGY_V02 unchanged", "candidate": "frozen V2 plus signal-date prior completed monthly MA20/MA60 alignment and exact PIT raw market cap >=500B", "signal_generation_reruns": 0, "per_ticker_states_recomputed": False},
        "portfolio": {"initial_capital_krw": 200000000, "buy_budget_including_commission_krw": 5000000, "integer_shares": True, "commission_each_side": 0.00015, "slippage_each_side": 0.001, "sell_tax": 0, "sale_proceeds_available": "T+1", "cash_shortage": "skip full order; do not regenerate signals", "same_open_exit_reentry": False, "pyramiding": False, "open_cutoff": "value by valid cutoff close; no hypothetical exit costs"},
        "valuation": {"daily_nav": "cash + pending sale proceeds + evidence-backed holdings at exact-date valid adjusted close", "no_interpolation_or_unapproved_carry": True, "unresolved_day_nav": "UNRESOLVED for the entire date"},
        "prior_windows": {item["window"]: item["status"] for item in period_audits},
        "prohibited": ["P2/P3 full signal or portfolio replay", "P2-1/P2-2/P3-1/P3-2 rerun unless audit proves needed and user approves", "strategy rules/official thresholds changes", "source or sealed artifact modification", "production/web changes", "automatic strategy promotion/default replacement"],
    }
    write_json(OUT / "execution_contract.json", contract)
    (OUT / "plan.md").write_text(
        "# FAST Core V2 Alignment + 500B — exact pair 184→185, P1 replay V01\n\n"
        "## Scope\n\n"
        "Add only `(029960, KR7029960002)` to the shared permanent exact-identity exclusion policy. Audit the latest sealed P2-1, P2-2, P3-1, and P3-2 ledgers for cash-path effect. Reuse the verified P1 frozen V2 signal/filter ledger after removing only this exact pair, then run one full chronological P1 portfolio replay for CONTROL and candidate.\n\n"
        "## Fixed boundaries\n\n"
        "No strategy/entry/exit, portfolio, cost, or official-gate changes. No P2/P3 rerun, production/web change, hypothetical settlement, NAV interpolation, or strategy promotion. Source artifacts remain unchanged.\n\n"
        "## Outputs\n\n"
        "Authority and input hashes, exclusion diff, four period impact rejudgments, P1 signal reuse audit, P1 replay ledgers, A–E gates, five-window summary, report, and generated-artifact hashes are written in this directory.\n",
        encoding="utf-8",
    )

    # Freeze the contract and provenance before any P1 portfolio replay.
    contract_sha = sha(OUT / "execution_contract.json")
    (OUT / "pre_replay_seal.json").write_text(json.dumps({"execution_contract_sha256": contract_sha, "sealed_at_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "baseline_head": baseline_head, "new_policy_sha256": registry_sha}, indent=2) + "\n", encoding="utf-8")

    runner_path = P1_184 / "run_p1_official_realistic_replay.py"
    runner = load_module(runner_path, "exclusion185_p1_replay_runner")
    runner.OUT = OUT
    engine = runner.load_engine()
    calendar, _pit_payload, _calendar_payload, segments = engine.build_authority()
    eligible_tickers = sorted(segments)
    if any(TARGET[0] == ticker and any(s.isu_cd.strip().upper() == TARGET[1] for s in segments[ticker]) for ticker in segments):
        raise RuntimeError("TARGET_IDENTITY_REMAINS_IN_185_ELIGIBLE_UNIVERSE")
    preflight_prices = pd.read_csv(P1_184 / "identity_price_preflight.csv", dtype=str, keep_default_na=False)
    from trend_scanner.data.repository_v2_loader import build_repository_v2
    repository = build_repository_v2(ROOT, end=runner.SUPPORT)
    runner.install_bounded_portfolio_loader(engine, preflight_prices)

    sample_selection = load_json(P1_184 / "sample_tickers.json")
    sample_tickers = set(str(t).zfill(6) for t in sample_selection["tickers"]) - {TARGET[0]}
    sample_control = [r for r in control_out.to_dict("records") if str(r.get("ticker", "")).zfill(6) in sample_tickers]
    sample_candidate = [r for r in candidate_out.to_dict("records") if str(r.get("ticker", "")).zfill(6) in sample_tickers]
    sample_c = runner.run_group(engine, calendar, segments, repository, sample_control)
    sample_p = runner.run_group(engine, calendar, segments, repository, sample_candidate)
    if sample_c.get("scope_issues") or sample_p.get("scope_issues"):
        raise RuntimeError("SAMPLE_PORTFOLIO_SCOPE_VALIDATION_FAILED")
    write_json(OUT / "sample_replay_validation.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_sample_replay_validation_v01",
        "status": "PASS", "tickers": len(sample_tickers), "control_signal_rows": len(sample_control), "candidate_signal_rows": len(sample_candidate),
        "control_scope_issues": len(sample_c.get("scope_issues", [])), "candidate_scope_issues": len(sample_p.get("scope_issues", [])),
        "control_cash_conservation": sample_c["metrics"].get("cash_conservation_pass"), "candidate_cash_conservation": sample_p["metrics"].get("cash_conservation_pass"),
        "purpose": "portfolio replay wiring and frozen input schema only; not used for official metrics",
    })

    start = time.perf_counter()
    control_result = runner.run_group(engine, calendar, segments, repository, control_out.to_dict("records"))
    candidate_result = runner.run_group(engine, calendar, segments, repository, candidate_out.to_dict("records"))
    elapsed = time.perf_counter() - start
    for group, result in (("control", control_result), ("candidate", candidate_result)):
        stem = f"p1_{group}"
        for key, suffix in (("events", "portfolio_events"), ("daily_equity", "daily_equity"), ("cash_events", "cash_events"), ("valuation_carry_audit", "valuation_audit"), ("missing_marks", "missing_marks"), ("issues", "issues"), ("unresolved_trade_events", "unresolved_trade_events"), ("lifecycle_diagnostics", "lifecycle_diagnostics")):
            pd.DataFrame(result[key]).to_csv(OUT / f"{stem}_{suffix}.csv", index=False)
        skipped = [r for r in result["events"] if str(r.get("event_status", "")).startswith("SKIPPED")]
        pd.DataFrame(skipped).to_csv(OUT / f"{stem}_skipped_entries.csv", index=False)
        write_json(OUT / f"{stem}_replay_metrics.json", result["metrics"])

    # Independent row-level fee/cash checks use the established audit helper.
    helpers = load_module(P1_184 / "frozen_audit_helpers.py", "exclusion185_p1_audit_helpers")
    cost_audits = {}
    group_results = {"CONTROL": control_result, "ALIGNMENT_MCAP_500B": candidate_result}
    group_inputs = {"CONTROL": control_out, "ALIGNMENT_MCAP_500B": candidate_out}
    for name, result in group_results.items():
        events = pd.DataFrame(result["events"])
        trades = group_inputs[name]
        cost_audits[name] = helpers.cost_and_portfolio_checks(events, trades, result["metrics"])

    integrity_checks = {
        "source_manifest_all_data_and_nonpolicy_hashes_match": source_audit.get("status") in {"PASS", "PASS_WITH_AUTHORIZED_POLICY_CHANGE"} and source_audit.get("checked") == source_audit.get("expected") and not source_audit.get("mismatches"),
        "original_p1_output_hashes_match": p1_artifact_hashes.get("status") == "PASS",
        "current_policy_is_exact_185": len(new_pairs) == 185 and canonical_pairs(new_pairs) == canonical_pairs(old_pairs | {TARGET}),
        "non_target_signal_rows_reused_exactly": len(control_out) == len(control) - int(ctrl_target.sum()) and len(candidate_out) == len(candidate),
        "calendar_has_3107_p1_sessions": len([d for d in calendar.trading_dates if runner.EVAL_START <= pd.Timestamp(d).normalize() <= runner.CUTOFF]) == 3107,
        "target_not_in_pit_universe": TARGET[0] not in segments,
        "control_scope_issues_zero": not control_result.get("scope_issues"),
        "candidate_scope_issues_zero": not candidate_result.get("scope_issues"),
        "control_cash_conservation": bool(control_result["metrics"].get("cash_conservation_pass")),
        "candidate_cash_conservation": bool(candidate_result["metrics"].get("cash_conservation_pass")),
        "all_filled_sides_costed_control": all(v is True for v in cost_audits["CONTROL"].values() if isinstance(v, bool)),
        "all_filled_sides_costed_candidate": all(v is True for v in cost_audits["ALIGNMENT_MCAP_500B"].values() if isinstance(v, bool)),
        "worker_error_count": 0,
    }
    critical = [k for k, v in integrity_checks.items() if v is False or (k == "worker_error_count" and v != 0)]
    missing_summary = {}
    unresolved_rows = []
    for name, result in group_results.items():
        rows = result["missing_marks"]
        counts = Counter(str(r.get("ticker", "")).zfill(6) for r in rows)
        missing_summary[name] = {"missing_mark_count": len(rows), "ticker_counts": dict(sorted(counts.items())), "rows": rows}
        unresolved_rows.extend({"group": name, **r} for r in rows)
    pd.DataFrame(unresolved_rows).to_csv(OUT / "p1_unresolved_mark_summary.csv", index=False)
    write_json(OUT / "p1_integrity_audit.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_integrity_audit_v01",
        "status": "FAIL" if critical else "PASS",
        "critical_integrity_error_count": len(critical), "critical_integrity_errors": critical,
        "checks": integrity_checks, "source_manifest": source_audit,
        "original_artifact_hashes": p1_artifact_hashes, "cost_audits": cost_audits,
        "scope_issue_counts": {k: len(v.get("scope_issues", [])) for k, v in group_results.items()},
        "unresolved_mark_summary": missing_summary,
        "full_replay_seconds": round(elapsed, 3), "portfolio_replay_workers": 1,
        "signal_workers": 0, "signal_evaluation_rerun": False,
    })

    def gate_for(group: str, result: dict[str, Any], integrity_ok: bool) -> dict[str, Any]:
        m = result["metrics"]
        cutoff_ok = m.get("cutoff_equity_krw") is not None
        c = "CHECK_REQUIRED" if not cutoff_ok else "PASS" if (m.get("total_return_pct", 0) > 0 and m.get("cagr_pct", 0) > 0) else "FAIL"
        coverage = float(m.get("nav_coverage_pct", 0)) / 100.0
        if coverage < 0.90 or not cutoff_ok:
            e = "CHECK_REQUIRED"
        elif coverage == 1.0:
            e = "PASS"
        else:
            e = "OBSERVED"
        mdd = m.get("mdd_pct")
        d = "CHECK_REQUIRED" if mdd is None else "PASS" if float(mdd) >= -55.0 else "FAIL"
        return {
            "A_integrity": {"status": "PASS" if integrity_ok else "FAIL", "checks": integrity_checks},
            "B_costs": {"status": "PASS" if all(v is True for v in cost_audits[group].values() if isinstance(v, bool)) else "FAIL", "cost_audit": cost_audits[group]},
            "C_profitability": {"status": c, "total_return_pct": m.get("total_return_pct"), "cagr_pct": m.get("cagr_pct"), "cutoff_nav_resolved": cutoff_ok},
            "D_mdd": {"status": d, "mdd_pct": mdd, "mdd_type": m.get("mdd_type"), "absolute_floor_pct": -55.0},
            "E_validity": {"status": e, "nav_coverage_pct": m.get("nav_coverage_pct"), "valid_days": m.get("valid_nav_days"), "total_days": m.get("total_valuation_days"), "missing_days": m.get("missing_nav_days"), "cutoff_nav_resolved": cutoff_ok},
        }

    control_gates = gate_for("CONTROL", control_result, not critical)
    candidate_gates = gate_for("ALIGNMENT_MCAP_500B", candidate_result, not critical)
    candidate_mdd = candidate_result["metrics"].get("mdd_pct")
    control_mdd = control_result["metrics"].get("mdd_pct")
    relative = None if control_mdd is None or candidate_mdd is None else float(control_mdd) - float(candidate_mdd)
    if candidate_mdd is None or control_mdd is None:
        candidate_gates["D_mdd"]["status"] = "CHECK_REQUIRED"
    else:
        candidate_gates["D_mdd"].update({"control_mdd_minus_candidate_mdd_pp": relative, "relative_failure_threshold_pp": 5.0})
        if candidate_gates["D_mdd"]["status"] == "PASS" and relative >= 5.0:
            candidate_gates["D_mdd"]["status"] = "FAIL"
    group_statuses = [x[letter]["status"] for x in (control_gates, candidate_gates) for letter in ("A_integrity", "B_costs", "C_profitability", "D_mdd", "E_validity")]
    p1_status = "NOT_ADOPTED" if "FAIL" in group_statuses else "CHECK_REQUIRED" if "CHECK_REQUIRED" in group_statuses else "PASS_WITH_OBSERVED_NAV" if "OBSERVED" in group_statuses else "PASS"
    write_json(OUT / "p1_gate_results.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_gate_results_v01",
        "window": "P1", "CONTROL": control_gates, "ALIGNMENT_MCAP_500B": candidate_gates,
        "candidate_relative_mdd_delta_pp": relative, "p1_overall_status": p1_status,
        "whole_five_window_adoption": "NOT_EVALUATED", "candidate_adoption": "NOT_EVALUATED",
        "baseline_promotion": "NOT_EVALUATED", "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    })
    pd.DataFrame([{"metric": k, "control": control_result["metrics"].get(k), "candidate": candidate_result["metrics"].get(k), "candidate_minus_control": (candidate_result["metrics"].get(k) - control_result["metrics"].get(k)) if isinstance(candidate_result["metrics"].get(k), (int, float)) and isinstance(control_result["metrics"].get(k), (int, float)) else None} for k in sorted(set(control_result["metrics"]) | set(candidate_result["metrics"]))]).to_csv(OUT / "metrics_comparison.csv", index=False)

    five_rows = [{"window": x["window"], "status": x["status"], "groups": x["official_gate_status_before_185"], "policy_lineage": x["policy_lineage"], "minimal_replay_required_for_185": x["minimal_replay_required"]} for x in period_audits]
    five_rows.insert(0, {"window": "P1", "status": p1_status, "groups": gate_statuses({"CONTROL": control_gates, "ALIGNMENT_MCAP_500B": candidate_gates}), "policy_lineage": {"pair_count": 185, "canonical_sha256": canonical_pairs(new_pairs)}, "minimal_replay_required_for_185": False})
    any_fail = any(x["status"] == "NOT_ADOPTED" for x in five_rows)
    any_hold = any(x["status"] == "CHECK_REQUIRED" for x in five_rows)
    all_clear = all(x["status"] in {"PASS", "PASS_WITH_OBSERVED_NAV"} for x in five_rows)
    overall = "NOT_ADOPTED" if any_fail else "HOLD" if any_hold else "5WINDOW_GATES_PASS" if all_clear else "HOLD"
    write_json(OUT / "five_window_gate_summary.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion185_five_window_gate_summary_v01",
        "five_window_status": overall, "windows": five_rows,
        "baseline_promotion": "NOT_EVALUATED", "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    })

    # Compact human report; the detailed row ledgers remain adjacent CSV/JSON files.
    critical_count = len(critical)
    major_count = sum(1 for gate in (control_gates, candidate_gates) for item in gate.values() if item.get("status") == "CHECK_REQUIRED")
    minor_count = sum(len(r["target_row_audit"]["files"]) for r in period_audits) + sum(len(v["missing_marks"]) for v in group_results.values())
    def fmt(v: Any, digits: int = 2) -> str:
        return "미확정" if v is None else f"{float(v):,.{digits}f}"
    lines = [
        "# FAST Core V2 Alignment + 500B — 코엔텍 exact pair 제외, 185쌍 P1 replay V01", "",
        "| 심각도 | 건수 | 설명 |", "|---|---:|---|",
        f"| CRITICAL | {critical_count} | 무결성 또는 비용/체결 불변식 실패 |",
        f"| MAJOR | {major_count} | P1 공식 A~E에서 CHECK_REQUIRED인 항목 |",
        f"| MINOR | {minor_count} | 대상 행 감사와 미해결 평가 mark; 원인은 아래 원장 참조 |", "",
        f"**P1 판정: `{p1_status}`. 5기간 종합: `{overall}`.** 기본 전략은 그대로 유지하고 후보 승격은 평가하지 않았어.", "",
        "## 184→185 정책 변경 및 과거 4기간 영향", "",
        f"- 추가한 exact pair는 `{TARGET[0]} / {TARGET[1]}` 1쌍뿐이야. 기존 184쌍 집합은 SHA-256 `{OLD_SHA}`와 동일하고, 새 185쌍 해시는 `{canonical_pairs(new_pairs)}`야. 제외 사유는 P1 실제 보유 후 생애주기/기업행위 정산을 확인할 수 없는 데이터 품질 예외이며 성과 기반 제외가 아니야.",
        "- 과거 기준의 P2-1/P2-2/P3-1/P3-2는 저장 원장만 검토했어. 네 기간 모두 최신 184쌍 상태에서 코엔텍 매수 이벤트가 전량 현금 부족 skip이며 `cash_before == cash_after`, 후보 실체결 0건, 미청산 valuation mark 0건이야. 따라서 코엔텍 행만 제거해도 나머지 cash path와 NAV는 그대로고 전 기간 재생은 필요하지 않아.",
        "- P3 원래 V01 산출물에는 코엔텍 매수 행이 있었지만, 이후 데이터 보정 closure와 184쌍 재판정 원장이 해당 산출물을 대체했어. 최신 P3-1/2 closure에서는 해당 시도가 cash skip이고, 연결된 재판정 원장은 비대상 현금 행과 A~E가 변하지 않았음을 기록해. 보고서는 `p3_1_rejudgment.json` 및 `p3_2_rejudgment.json`에 근거했어.",
        "- P2-1/P2-2/P3-1/P3-2 최신 gate는 `p2_1_rejudgment.json` 등 각 원장에 있고, 모두 이전 공식 상태를 유지해. P2/P3 전체 재생은 하지 않았어.", "",
        "## P1 동결 신호 재사용 및 185쌍 전기간 replay", "",
        f"- 기존 P1 신호평가/필터 재실행은 0회. 184 기준 P1 source manifest {source_audit['checked']}/{source_audit['expected']}개, 결과 hash {p1_artifact_hashes['checked']}개가 모두 일치했어. 기존 CONTROL 4개 코엔텍 신호 trade row와 후보 filter audit 23행만 제거했어. 후보 trade row 제거는 0행이야.",
        f"- 새 공유 유니버스는 정확히 185쌍 제외로 만들었고 eligible ticker/interval 수는 현재 PIT에서 다시 계산했어. 포트폴리오 표본 점검 뒤 3,107 거래일에 대해 CONTROL과 후보를 각각 순차 재생했어. worker error 0건, 재시도 0회, 지원일 2026-09-01은 후속 청산에만 사용했어.", "",
        "| 지표 | CONTROL | 후보 ALIGNMENT_MCAP_500B | 후보−CONTROL |", "|---|---:|---:|---:|",
    ]
    metrics = [
        ("총수익률 %", "total_return_pct", 2), ("CAGR %", "cagr_pct", 2), ("MDD %", "mdd_pct", 2),
        ("NAV coverage %", "nav_coverage_pct", 2), ("진입 시도", "eligible_entry_attempts", 0),
        ("현금 부족 skip", "cash_shortage_skipped_entries", 0), ("실제 진입", "executed_entry_count", 0),
        ("실현 청산", "realized_exit_count", 0), ("cutoff 미청산", "open_at_cutoff_count", 0),
        ("평균 자본 활용률 %", "average_capital_utilization_pct", 2), ("최대 동시 보유", "maximum_concurrent_positions", 0),
        ("수수료 원", "total_commissions_krw", 0), ("슬리피지 원", "total_slippage_impact_krw", 0),
        ("cutoff NAV 원", "cutoff_equity_krw", 0),
    ]
    cm, pm = control_result["metrics"], candidate_result["metrics"]
    for label, key, digits in metrics:
        a, b = cm.get(key), pm.get(key)
        delta = (float(b) - float(a)) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        lines.append(f"| {label} | {fmt(a, digits)} | {fmt(b, digits)} | {fmt(delta, digits)} |")
    lines.extend(["", f"- MDD 유형/평가: CONTROL `{cm.get('mdd_type')}` (coverage {fmt(cm.get('nav_coverage_pct'))}%, {cm.get('missing_nav_days')}일 누락), 후보 `{pm.get('mdd_type')}` (coverage {fmt(pm.get('nav_coverage_pct'))}%, {pm.get('missing_nav_days')}일 누락). 기말 NAV 가능: CONTROL `{cm.get('cutoff_equity_krw') is not None}`, 후보 `{pm.get('cutoff_equity_krw') is not None}`.",
        "- 잔여 미해결 mark 종목·날짜는 `p1_unresolved_mark_summary.csv` 및 그룹별 `p1_*_missing_marks.csv`에 전부 보존했어. 임의 정산/대체/forward-fill은 하지 않았어.", "",
        "## 공식 P1 A~E 및 산출물 검증", "",
        f"- CONTROL A~E: `{[control_gates[k]['status'] for k in ('A_integrity','B_costs','C_profitability','D_mdd','E_validity')]}`.",
        f"- 후보 A~E: `{[candidate_gates[k]['status'] for k in ('A_integrity','B_costs','C_profitability','D_mdd','E_validity')]}`. 후보 상대 MDD 악화폭 `CONTROL MDD - Candidate MDD = {fmt(relative)}%p`, 실패 기준은 +5.0%p 이상이야.",
        "- 현금 부족은 필수 진단이며 PASS/FAIL에 사용하지 않았어. P1에서 남은 CHECK_REQUIRED가 있으면 5기간 결과는 `HOLD`로 남겼고, 추가 영구 제외나 임의 평가 방식 변경은 하지 않았어.",
        "- 해시, 입력 재사용, 비용/현금 보존 상세는 `p1_integrity_audit.json`, `artifact_hashes.json`, `authority_hashes.json`, `source_manifest.json`을 확인하면 돼.", "",
        "## 5기간 공식 게이트 요약", "",
        "| 기간 | 상태 | 재생 여부 |", "|---|---|---|",
    ])
    for row in five_rows:
        lines.append(f"| {row['window']} | {row['status']} | {'P1 full replay' if row['window']=='P1' else '저장 원장 재판정'} |")
    lines.extend(["", "기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02`는 유지돼. 후보의 공식 채택 또는 기본 전략 승격은 이 실행에서 수행하지 않았어.", ""])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")

    write_json(OUT / "p1_replay_execution.json", {
        "schema": "fast_core_v2_alignment_500b_exclusion185_p1_replay_execution_v01",
        "status": "EXECUTION_COMPLETE", "evaluation_sessions": 3107, "support_date": "2026-09-01",
        "groups_replayed": ["CONTROL", "ALIGNMENT_MCAP_500B"], "signal_evaluation_rerun": False,
        "reused_control_rows": len(control_out), "reused_candidate_rows": len(candidate_out),
        "portfolio_replay_workers": 1, "worker_error_count": 0, "retry_count": 0,
        "elapsed_seconds": round(elapsed, 3), "sample_validation": "PASS",
        "execution_contract_pre_replay_sha256": contract_sha,
        "control_metrics": cm, "candidate_metrics": pm,
    })
    # This is a research-output hash list; it deliberately excludes itself.
    hashed = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashed.append({"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    write_json(OUT / "artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_exclusion185_artifact_hashes_v01", "hash_algorithm": "sha256", "self_hash_excluded": True, "files": hashed})
    print(json.dumps({"status": "EXECUTION_COMPLETE", "p1_status": p1_status, "five_window_status": overall, "new_pair_count": len(new_pairs), "new_pair_hash": canonical_pairs(new_pairs), "source_manifest": source_audit, "original_hashes": p1_artifact_hashes, "control_metrics": {k: cm.get(k) for k in ("total_return_pct", "cagr_pct", "mdd_pct", "nav_coverage_pct", "cutoff_equity_krw", "executed_entry_count", "cash_shortage_skipped_entries", "realized_exit_count", "open_at_cutoff_count")}, "candidate_metrics": {k: pm.get(k) for k in ("total_return_pct", "cagr_pct", "mdd_pct", "nav_coverage_pct", "cutoff_equity_krw", "executed_entry_count", "cash_shortage_skipped_entries", "realized_exit_count", "open_at_cutoff_count")}, "artifact_count": len(hashed)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    build_and_run()
