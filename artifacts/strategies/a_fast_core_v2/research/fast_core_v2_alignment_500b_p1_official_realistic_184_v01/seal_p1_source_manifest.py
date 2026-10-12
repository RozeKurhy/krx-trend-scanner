#!/usr/bin/env python3
"""Seal P1 runtime inputs and independent prior-result hash evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
W_PATH = Path("/Users/june/Documents/projects/w.md")
REFERENCE_DIRS = (
    "fast_core_v2_alignment_500b_p3_1_official_realistic_v01",
    "fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01",
    "fast_core_v2_alignment_500b_p3_2_official_realistic_v01",
    "fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01",
    "fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01",
    "fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01",
)
RESEARCH = ROOT / "artifacts/strategies/a_fast_core_v2/research"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def record(path: Path, *, kind: str = "runtime_input") -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "kind": kind,
    }


def verify_prior_artifacts() -> list[dict[str, object]]:
    rows = []
    for name in REFERENCE_DIRS:
        folder = RESEARCH / name
        manifest_path = folder / "artifact_hashes.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing, mismatches = [], []
        for item in manifest.get("files", []):
            target = folder / item["path"]
            if not target.is_file():
                missing.append(item["path"])
                continue
            actual = sha(target)
            if actual != item.get("sha256") or target.stat().st_size != int(item.get("bytes", -1)):
                mismatches.append(item["path"])
        rows.append({
            "directory": str(folder.relative_to(ROOT)),
            "manifest_sha256": sha(manifest_path),
            "checked_file_count": len(manifest.get("files", [])) - len(missing),
            "expected_file_count": len(manifest.get("files", [])),
            "missing_count": len(missing),
            "mismatch_count": len(mismatches),
            "missing_examples": missing[:5],
            "mismatch_examples": mismatches[:5],
            "status": "PASS" if not missing and not mismatches else "FAIL",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="seal sample outputs before the authorized full replay")
    args = parser.parse_args()
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    contract = json.loads((OUT / "execution_contract.json").read_text(encoding="utf-8"))
    if preflight.get("preflight_status") != "PASS":
        raise RuntimeError(f"P1_PREFLIGHT_NOT_PASS:{preflight.get('preflight_status')}")
    if not W_PATH.is_file() or sha(W_PATH) != contract["directive"]["sha256"]:
        raise RuntimeError("P1_DIRECTIVE_HASH_MISMATCH")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    tracked_status = subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True)
    if branch != "main" or head != origin or head != contract["baseline"]["head"] or tracked_status.strip():
        raise RuntimeError(f"P1_BASELINE_CHANGED:{branch}:{head}:{origin}")

    runtime_paths = [
        ROOT / "docs/validation/backtest_common_rules.md",
        ROOT / "docs/validation/official_strategy_adoption_criteria.md",
        ROOT / "docs/strategies/strategy_lifecycle.md",
        ROOT / "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py",
        ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        ROOT / "scripts/run_v2_official_adoption_revalidation_v02.py",
        ROOT / "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        ROOT / "src/trend_scanner/data/repository_v2.py",
        ROOT / "src/trend_scanner/data/repository_v2_loader.py",
        ROOT / "src/trend_scanner/data/repository_v2_session_authority.py",
        ROOT / "src/trend_scanner/data/market_calendar.py",
        ROOT / "src/trend_scanner/data/rolling_market_data_refresh.py",
        ROOT / "src/trend_scanner/data/krx_raw_stock_store.py",
        ROOT / "src/trend_scanner/backtest/snapshot_context.py",
        ROOT / "src/trend_scanner/patterns/pattern_a_stage.py",
        ROOT / "src/trend_scanner/validation/feature_report.py",
        ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
        ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
        ROOT / "data/market/rolling_authority/manifest.json",
        ROOT / "data/market/rolling_authority/merged_pit_intervals.json",
        ROOT / "data/market/rolling_authority/merged_trading_calendar.json",
        ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json",
        OUT / "plan.md",
        OUT / "execution_contract.json",
        OUT / "preflight.json",
        OUT / "identity_price_preflight.csv",
        OUT / "active_pit_missing_sessions.csv",
        OUT / "raw_partition_preflight.csv",
        OUT / "permanent_exclusion_pairs.csv",
        OUT / "sample_tickers.json",
        OUT / "frozen_reference_engine.py",
        OUT / "frozen_audit_helpers.py",
        OUT / "run_p1_official_realistic_replay.py",
        OUT / "seal_p1_preflight.py",
        OUT / "seal_p1_source_manifest.py",
        OUT / "validate_p1_sample.py",
        OUT / "finalize_p1_official.py",
        OUT / "preoptimization_source_manifest.json",
        OUT / "preoptimization_sample_benchmark.json",
        OUT / "preoptimization_sample_validation.json",
        OUT / "preoptimization_sample_reference.json",
        OUT / "memoization_sample_benchmark.json",
        OUT / "memoization_sample_validation.json",
        OUT / "memoization_sample_reference.json",
    ]
    files = {str(p.relative_to(ROOT)): record(p) for p in runtime_paths}
    prices = pd.read_csv(OUT / "identity_price_preflight.csv", dtype=str, keep_default_na=False)
    price_records = []
    price_mismatches = []
    for row in prices.to_dict("records"):
        ticker = str(row["ticker"]).zfill(6)
        path = ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet"
        if not path.is_file():
            price_mismatches.append({"ticker": ticker, "reason": "MISSING_FILE"})
            continue
        actual = sha(path)
        expected = str(row.get("adjusted_file_sha256", ""))
        if actual != expected:
            price_mismatches.append({"ticker": ticker, "reason": "SHA256_MISMATCH", "expected": expected, "actual": actual})
        price_records.append({"ticker": ticker, "path": str(path.relative_to(ROOT)), "sha256": actual, "bytes": path.stat().st_size, "first_date": row.get("adjusted_first_date"), "last_date": row.get("adjusted_last_date")})
    raw = pd.read_csv(OUT / "raw_partition_preflight.csv", dtype=str, keep_default_na=False)
    raw_records = raw[["market", "partition_date", "status", "file_path", "file_sha256", "content_sha256", "row_count"]].to_dict("records")
    if not raw.empty and not raw["status"].eq("COMPLETE").all():
        raise RuntimeError("P1_RAW_PARTITION_PREFLIGHT_INCOMPLETE")

    sample_outputs = []
    if args.full:
        sample_validation = json.loads((OUT / "sample_validation.json").read_text(encoding="utf-8"))
        benchmark = json.loads((OUT / "sample_benchmark.json").read_text(encoding="utf-8"))
        if sample_validation.get("full_run_allowed") is not True or sample_validation.get("status") != "PASS":
            raise RuntimeError("P1_SAMPLE_STRUCTURAL_VALIDATION_NOT_PASS")
        if benchmark.get("worker_error_count") != 0:
            raise RuntimeError("P1_SAMPLE_WORKER_ERRORS")
        sample_names = [p.name for p in OUT.iterdir() if p.is_file() and p.name.startswith("sample_")]
        for name in sorted(sample_names):
            sample_outputs.append(record(OUT / name, kind="validated_sample_output"))
            files[str((OUT / name).relative_to(ROOT))] = sample_outputs[-1]
    reference_checks = verify_prior_artifacts()
    if any(item["status"] != "PASS" for item in reference_checks):
        raise RuntimeError("P1_PRIOR_ARTIFACT_HASH_AUDIT_FAILED")
    reference_sources = preflight.get("source_references", [])
    missing_reference_sources = [item for item in reference_sources if not item.get("exists")]
    if missing_reference_sources:
        raise RuntimeError(f"P1_REQUIRED_REFERENCE_MISSING:{len(missing_reference_sources)}")

    status = "FROZEN_BEFORE_FULL" if args.full else "FROZEN_BEFORE_SAMPLE"
    payload = {
        "schema": "fast_core_v2_alignment_500b_p1_source_manifest_v01",
        "task_id": contract["task_id"],
        "status": status,
        "created_before_full_execution": True,
        "baseline": {"branch": branch, "head": head, "origin_main": origin, "tracked_tree_clean": True},
        "directive": {"path": str(W_PATH), "sha256": sha(W_PATH), "bytes": W_PATH.stat().st_size},
        "execution_contract_sha256": sha(OUT / "execution_contract.json"),
        "plan_sha256": sha(OUT / "plan.md"),
        "preflight_sha256": sha(OUT / "preflight.json"),
        "p1_window": preflight["date_authorities"],
        "p1_universe": preflight["universe"],
        "permanent_exclusions": {"pair_count": preflight["universe"]["current_exclusion_pair_count"], "canonical_sha256": preflight["universe"]["permanent_exclusion_canonical_sha256"], "source_sha256": preflight["universe"]["permanent_exclusion_file_sha256"]},
        "repository_v2_input_preflight": preflight["repository_v2_input_preflight"],
        "adjusted_price_inputs": {"ticker_count": len(price_records), "hash_check": {"checked": len(price_records), "mismatch_count": len(price_mismatches), "status": "PASS" if not price_mismatches else "FAIL"}, "mismatches": price_mismatches, "files": price_records},
        "krx_raw_market_date_partitions": {"partition_count": len(raw_records), "status_counts": {str(key): int(value) for key, value in raw["status"].value_counts().sort_index().items()}, "hash_source": "immutable partition manifest file_sha256/content_sha256; signal-date files are independently physical-hash and canonical-content verified when loaded", "partitions": raw_records},
        "prior_official_artifact_hash_checks": reference_checks,
        "required_reference_source_hashes": reference_sources,
        "sample_validation": None if not args.full else json.loads((OUT / "sample_validation.json").read_text(encoding="utf-8")),
        "files": [files[key] for key in sorted(files)],
        "sample_output_hashes": sample_outputs,
        "external_api_requests": 0,
    }
    if price_mismatches:
        raise RuntimeError(f"P1_ADJUSTED_PRICE_HASH_MISMATCHES:{len(price_mismatches)}")
    (OUT / "source_manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "runtime_files": len(files), "adjusted_price_files": len(price_records), "raw_partitions": len(raw_records), "prior_artifact_hash_checks": reference_checks}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
