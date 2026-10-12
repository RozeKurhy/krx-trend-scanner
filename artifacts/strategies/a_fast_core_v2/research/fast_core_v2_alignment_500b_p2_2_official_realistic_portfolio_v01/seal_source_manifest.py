#!/usr/bin/env python3
"""Freeze P2-2 source, authority, execution, and preflight hashes before sample."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    before_full = "--before-full" in sys.argv
    post_sample_gate = "--post-sample-gate" in sys.argv
    if before_full and post_sample_gate:
        raise RuntimeError("P2_MANIFEST_MODE_CONFLICT")
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    if preflight.get("preflight_status") != "PASS":
        raise RuntimeError(f"P2_PREFLIGHT_NOT_PASS:{preflight.get('preflight_status')}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if head != origin or branch != "main" or head != preflight["baseline"]["head"]:
        raise RuntimeError(f"P2_BASELINE_CHANGED_BEFORE_SEAL:{branch}:{head}:{origin}")
    prior_manifest = OUT / "source_manifest_pre_sample.json"
    sample_validation = OUT / "sample_validation.json"
    if before_full or post_sample_gate:
        if not prior_manifest.is_file() or not sample_validation.is_file():
            raise RuntimeError("P2_PRE_SAMPLE_MANIFEST_OR_SAMPLE_VALIDATION_MISSING")
        validation = json.loads(sample_validation.read_text(encoding="utf-8"))
        if before_full and validation.get("status") != "PASS":
            raise RuntimeError(f"P2_SAMPLE_VALIDATION_NOT_PASS:{validation.get('status')}")
        if post_sample_gate and validation.get("status") not in {"PASS", "CHECK_REQUIRED"}:
            raise RuntimeError(f"P2_SAMPLE_VALIDATION_STATUS_INVALID:{validation.get('status')}")

    paths = {
        "docs/validation/backtest_common_rules.md",
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md",
        "src/trend_scanner/universe/permanent_identity_exclusions.py",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "scripts/run_v2_official_adoption_revalidation_v02.py",
        "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        "src/trend_scanner/data/repository_v2.py",
        "src/trend_scanner/data/repository_v2_loader.py",
        "src/trend_scanner/data/repository_v2_session_authority.py",
        "src/trend_scanner/data/market_calendar.py",
        "src/trend_scanner/data/rolling_market_data_refresh.py",
        "src/trend_scanner/data/krx_raw_stock_store.py",
        "src/trend_scanner/backtest/snapshot_context.py",
        "src/trend_scanner/patterns/pattern_a_stage.py",
        "src/trend_scanner/validation/feature_report.py",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
        "data/market/rolling_authority/manifest.json",
        "data/market/rolling_authority/merged_pit_intervals.json",
        "data/market/rolling_authority/merged_trading_calendar.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/plan.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/execution_contract.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/seal_preflight.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_targeted_evaluation.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_portfolio_replay.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/price_input_124_audit.csv",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/integrity_validation.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/identity_policy_transition.csv",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/nav_missing_marks.csv",
    }
    paths.update(row["path"] for row in preflight.get("source_references", []) if row.get("exists"))
    task_files = ["plan.md", "execution_contract.json", "preflight.json", "identity_price_preflight.csv", "active_pit_missing_sessions.csv", "raw_partition_preflight.csv", "permanent_exclusion_pairs.csv", "sample_tickers.json", "seal_preflight.py", "run_p2_2_replay.py", "validate_sample_p2_2.py", "finalize_p2_2.py", "seal_source_manifest.py"]
    entries = []
    for rel in sorted(paths):
        path = ROOT / rel
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append({"path": rel, "sha256": sha(path), "bytes": path.stat().st_size})
    for name in task_files:
        path = OUT / name
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size})
    sample_evidence = []
    if before_full or post_sample_gate:
        evidence_paths = [prior_manifest, sample_validation, OUT / "sample_benchmark.json", OUT / "sample_attempt_01_failure.json", OUT / "sample_validation_compatibility_fix.json"]
        evidence_paths.extend(sorted(OUT.glob("sample_*.csv")))
        for path in evidence_paths:
            if path.is_file():
                item = {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
                sample_evidence.append(item)
                entries.append(item)
    directive = Path("/Users/june/Documents/projects/w.md")
    directive_entry = {"path": str(directive), "absolute_path": str(directive), "sha256": sha(directive), "bytes": directive.stat().st_size} if directive.is_file() else {"path": str(directive), "absolute_path": str(directive), "missing": True}
    manifest = {
        "schema": "fast_core_v2_alignment_500b_p2_2_source_manifest_v01",
        "task_id": preflight["task_id"],
        "status": "SAMPLE_GATE_CHECK_REQUIRED" if post_sample_gate and json.loads(sample_validation.read_text(encoding="utf-8")).get("status") != "PASS" else "SAMPLE_GATE_PASS" if post_sample_gate else "FROZEN_BEFORE_FULL" if before_full else "FROZEN_BEFORE_SAMPLE",
        "created_before_sample_or_full_run": not before_full and not post_sample_gate,
        "created_before_full_run": before_full or post_sample_gate,
        "created_after_sample_gate": post_sample_gate,
        "baseline": {"branch": branch, "head": head, "origin_main": origin, "matches_origin_main": head == origin},
        "directive": directive_entry,
        "p2_2_execution": {"plan_sha256": sha(OUT / "plan.md"), "execution_contract_sha256": sha(OUT / "execution_contract.json"), "preflight_sha256": sha(OUT / "preflight.json"), "signal_evaluation_workers": 10, "external_api_requests": 0},
        "sample_evidence": {"prior_pre_sample_manifest_sha256": sha(prior_manifest) if before_full or post_sample_gate else None, "validation_status": json.loads(sample_validation.read_text(encoding="utf-8")).get("status") if before_full or post_sample_gate else None, "files": sample_evidence},
        "rolling_authority": {"manifest_sha256": preflight["date_authorities"]["calendar_manifest_sha256"], "evaluation_start": preflight["date_authorities"]["evaluation_start"], "evaluation_end": preflight["date_authorities"]["evaluation_end"], "evaluation_sessions": preflight["date_authorities"]["evaluation_sessions"]},
        "price_input_inventory": {"path": "identity_price_preflight.csv", "adjusted_files_hashed": int(preflight["repository_v2_input_preflight"]["adjusted_file_hash_inventory_count"]), "all_adjusted_files_hashed": preflight["repository_v2_input_preflight"]["all_adjusted_files_hashed"]},
        "krx_raw_partition_inventory": {"path": "raw_partition_preflight.csv", "partition_rows": int(preflight["krx_raw_signal_partition_preflight"]["market_partition_count"])},
        "source_references": entries,
        "files": entries + ([directive_entry] if not directive_entry.get("missing") else []),
    }
    (OUT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "reference_file_count": len(entries), "baseline_head": head, "plan_sha256": manifest["p2_2_execution"]["plan_sha256"], "preflight_sha256": manifest["p2_2_execution"]["preflight_sha256"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
