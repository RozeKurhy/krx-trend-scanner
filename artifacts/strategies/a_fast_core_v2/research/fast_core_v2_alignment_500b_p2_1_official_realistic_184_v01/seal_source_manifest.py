#!/usr/bin/env python3
"""Seal P2-1 source references and input hashes before each execution phase."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
W_PATH = Path("/Users/june/Documents/projects/w.md")
REF_ARTIFACT_DIRS = [
    ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01",
    ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01",
    ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01",
    ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01",
    ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01",
]
RAW_PARTITION_ROOT = ROOT / "data/market/raw/krx_stocks/v01"

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def file_row(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"FROZEN_SOURCE_MISSING:{path}")
    try:
        rel = path.relative_to(ROOT).as_posix()
        return {"path": rel, "label": label, "sha256": sha(path), "bytes": path.stat().st_size}
    except ValueError:
        return {"absolute_path": str(path), "path": str(path), "label": label, "sha256": sha(path), "bytes": path.stat().st_size}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("sample", "full"), required=True)
    args = parser.parse_args()

    preflight_path = OUT / "preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("preflight_status") != "PASS":
        raise RuntimeError(f"P2_PREFLIGHT_NOT_PASS:{preflight.get('preflight_status')}")
    if preflight["baseline"].get("head") != preflight["baseline"].get("origin_main"):
        raise RuntimeError("P2_HEAD_NOT_ORIGIN_MAIN_IN_PREFLIGHT")
    if preflight["universe"].get("current_exclusion_pair_count") != 184 or preflight["universe"].get("permanent_exclusion_canonical_sha256") != "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e":
        raise RuntimeError("P2_EXACT_184_EXCLUSION_MISMATCH")

    files: dict[str, dict[str, Any]] = {}
    def add(path: Path, label: str) -> None:
        item = file_row(path, label)
        key = item.get("absolute_path", item["path"])
        old = files.get(key)
        if old and old["sha256"] != item["sha256"]:
            raise RuntimeError(f"FROZEN_SOURCE_HASH_CHANGED_DURING_SEAL:{key}")
        files[key] = item

    # Directive, frozen plan/contract, required source docs/code, preflight inventories and this execution package.
    add(W_PATH, "user_work_directive")
    for path in (
        OUT / "plan.md",
        OUT / "execution_contract.json",
        OUT / "preflight.json",
        OUT / "identity_price_preflight.csv",
        OUT / "active_pit_missing_sessions.csv",
        OUT / "raw_partition_preflight.csv",
        OUT / "permanent_exclusion_pairs.csv",
        OUT / "sample_tickers.json",
        OUT / "seal_preflight.py",
        OUT / "run_p2_1_replay.py",
        OUT / "validate_sample_p2_1.py",
        OUT / "finalize_p2_1.py",
        OUT / "seal_source_manifest.py",
    ):
        add(path, "p2_1_execution_input_or_code")

    for row in preflight.get("source_references", []):
        path = ROOT / row["path"]
        if not path.is_file() or sha(path) != row.get("sha256") or path.stat().st_size != int(row.get("bytes", -1)):
            raise RuntimeError(f"P2_PREFLIGHT_REFERENCE_CHANGED:{row.get('path')}")
        add(path, "required_source_or_prior_artifact_reference")

    # Check every prior official artifact hash bundle; preserve and pin its files by reference only.
    reference_checks = []
    for directory in REF_ARTIFACT_DIRS:
        manifest_path = directory / "artifact_hashes.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"REFERENCE_ARTIFACT_HASH_MANIFEST_MISSING:{manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checked, failures = 0, []
        for item in manifest.get("files", []):
            target = directory / item["path"]
            if not target.is_file() or target.stat().st_size != int(item.get("bytes", -1)) or sha(target) != item.get("sha256"):
                failures.append(item["path"])
            else:
                checked += 1
                add(target, "prior_official_artifact_hash_verified")
        if failures:
            raise RuntimeError(f"REFERENCE_ARTIFACT_HASH_MISMATCH:{directory.name}:{','.join(failures[:8])}")
        add(manifest_path, "prior_official_artifact_hash_manifest")
        reference_checks.append({"directory": directory.relative_to(ROOT).as_posix(), "manifest_sha256": sha(manifest_path), "checked_file_count": checked, "mismatch_count": 0})

    rolling_paths = [
        ROOT / "data/market/rolling_authority/manifest.json",
        ROOT / "data/market/rolling_authority/merged_pit_intervals.json",
        ROOT / "data/market/rolling_authority/merged_trading_calendar.json",
    ]
    for path in rolling_paths:
        add(path, "rolling_authority_data")

    prices = pd.read_csv(OUT / "identity_price_preflight.csv", dtype=str, keep_default_na=False)
    adjusted = []
    for row in prices.to_dict("records"):
        ticker = str(row["ticker"]).zfill(6)
        path = ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet"
        expected = str(row.get("adjusted_file_sha256", "")).strip()
        if not path.is_file() or not expected:
            raise RuntimeError(f"ADJUSTED_PRICE_HASH_INPUT_MISSING:{ticker}")
        adjusted.append({"ticker": ticker, "path": path.relative_to(ROOT).as_posix(), "sha256": expected, "bytes": path.stat().st_size})
    if len(adjusted) != int(preflight["repository_v2_input_preflight"]["unique_tickers_checked"]):
        raise RuntimeError("ADJUSTED_PRICE_HASH_INVENTORY_COUNT_MISMATCH")

    raw = pd.read_csv(OUT / "raw_partition_preflight.csv", dtype=str, keep_default_na=False)
    raw_inventory = []
    for row in raw.to_dict("records"):
        path_text = str(row.get("file_path", "")).strip()
        if not path_text or not row.get("file_sha256"):
            raise RuntimeError(f"RAW_PARTITION_HASH_INPUT_MISSING:{row.get('market')}:{row.get('partition_date')}")
        path = Path(path_text)
        if not path.is_absolute():
            candidates = (ROOT / path, RAW_PARTITION_ROOT / path)
            path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        if not path.is_file():
            raise RuntimeError(f"RAW_PARTITION_FILE_MISSING:{row.get('market')}:{row.get('partition_date')}")
        raw_inventory.append({
            "market": row["market"],
            "partition_date": row["partition_date"],
            "path": path.relative_to(ROOT).as_posix(),
            "file_sha256": row["file_sha256"],
            "content_sha256": row.get("content_sha256"),
            "bytes": path.stat().st_size,
            "status": row.get("status"),
        })

    sample_files = []
    revision_provenance: dict[str, Any] = {}
    if args.phase == "full":
        sample_manifest_path = OUT / "source_manifest_pre_sample.json"
        current_manifest_path = OUT / "source_manifest.json"
        if not current_manifest_path.is_file():
            raise RuntimeError("P2_SAMPLE_SOURCE_MANIFEST_MISSING")
        prior_manifest = json.loads(current_manifest_path.read_text(encoding="utf-8"))
        if prior_manifest.get("status") != "FROZEN_BEFORE_SAMPLE":
            raise RuntimeError("P2_PRE_SAMPLE_SOURCE_MANIFEST_STATUS_INVALID")
        for key in ("post_sample_validation_revision", "post_sample_manifest_sealer_revision"):
            if key in prior_manifest:
                revision_provenance[key] = prior_manifest[key]
        prior_hash = sha(current_manifest_path)
        if not sample_manifest_path.exists():
            shutil.copy2(current_manifest_path, sample_manifest_path)
        pre_sample_hash = sha(sample_manifest_path)
        revision = prior_manifest.get("post_sample_validation_revision", {})
        expected_pre_sample_hash = revision.get("original_pre_sample_manifest_sha256")
        if expected_pre_sample_hash and pre_sample_hash != expected_pre_sample_hash:
            raise RuntimeError("P2_PRE_SAMPLE_MANIFEST_HASH_MISMATCH")
        for path in sorted(OUT.iterdir()):
            if path.is_file() and (path.name.startswith("sample_") or path.name == "sample_validation.json"):
                add(path, "completed_p2_1_sample_evidence")
                sample_files.append({"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
        sample_validation = json.loads((OUT / "sample_validation.json").read_text(encoding="utf-8"))
        if sample_validation.get("full_run_allowed") is not True:
            raise RuntimeError("P2_SAMPLE_STRUCTURAL_VALIDATION_NOT_PASS")
        if len(adjusted) > 0:
            # Recheck every adjusted file against the preflight hash before full signal evaluation.
            def check_adjusted(item: dict[str, Any]) -> dict[str, Any]:
                actual = sha(ROOT / item["path"])
                return {"ticker": item["ticker"], "expected": item["sha256"], "actual": actual, "matches": actual == item["sha256"]}
            with ThreadPoolExecutor(max_workers=10, thread_name_prefix="p2-1-adjusted-hash") as pool:
                checked = list(pool.map(check_adjusted, adjusted))
            bad = [row for row in checked if not row["matches"]]
            if bad:
                raise RuntimeError(f"ADJUSTED_PRICE_INPUT_HASH_CHANGED:{len(bad)}:{bad[:5]}")
            adjusted_hash_status = {"status": "PASS", "checked": len(checked), "mismatch_count": 0}
        else:
            adjusted_hash_status = {"status": "FAIL", "checked": 0, "mismatch_count": 0}
        def check_raw(item: dict[str, Any]) -> dict[str, Any]:
            actual = sha(ROOT / item["path"])
            return {"path": item["path"], "expected": item["file_sha256"], "actual": actual, "matches": actual == item["file_sha256"]}
        with ThreadPoolExecutor(max_workers=10, thread_name_prefix="p2-1-raw-hash") as pool:
            checked_raw = list(pool.map(check_raw, raw_inventory))
        bad_raw = [row for row in checked_raw if not row["matches"]]
        if bad_raw:
            raise RuntimeError(f"RAW_PARTITION_INPUT_HASH_CHANGED:{len(bad_raw)}:{bad_raw[:5]}")
        raw_hash_status = {"status": "PASS", "checked": len(checked_raw), "mismatch_count": 0}
        add(sample_manifest_path, "sealed_pre_sample_manifest")
    else:
        adjusted_hash_status = {"status": "RECORDED_FROM_PRE_SAMPLE_PREFLIGHT", "checked": len(adjusted), "mismatch_count": 0}
        raw_hash_status = {"status": "RECORDED_FROM_EXACT_PARTITION_MANIFESTS", "checked": len(raw_inventory), "mismatch_count": 0}
        pre_sample_hash = None

    ordered_files = sorted(files.values(), key=lambda row: row.get("absolute_path", row["path"]))
    directive_row = next(row for row in ordered_files if row.get("label") == "user_work_directive")
    manifest = {
        "schema": "fast_core_v2_alignment_500b_p2_1_source_manifest_v01",
        "task_id": "FAST_CORE_V2_ALIGNMENT_500B_P2_1_OFFICIAL_REALISTIC_184_V01",
        "status": "FROZEN_BEFORE_SAMPLE" if args.phase == "sample" else "FROZEN_BEFORE_FULL",
        "phase": args.phase,
        "created_before_execution": True,
        "baseline": {
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "origin_main": subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
            "tracked_tree_clean": not bool(subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True).strip()),
        },
        "directive": {"path": directive_row.get("absolute_path"), "sha256": directive_row["sha256"], "bytes": directive_row["bytes"]},
        "execution_contract_sha256": sha(OUT / "execution_contract.json"),
        "plan_sha256": sha(OUT / "plan.md"),
        "preflight_sha256": sha(preflight_path),
        "p2_1_window": preflight["date_authorities"],
        "universe": preflight["universe"],
        "permanent_exclusions": {
            "pair_count": 184,
            "canonical_hash_scheme": "sorted_exact_pair_json_v01",
            "canonical_sha256": "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e",
            "source_sha256": next(row["sha256"] for row in ordered_files if row.get("path") == "src/trend_scanner/universe/permanent_identity_exclusions.py"),
        },
        "reference_artifact_hash_checks": reference_checks,
        "adjusted_price_inputs": {"ticker_count": len(adjusted), "files": adjusted, "hash_check": adjusted_hash_status},
        "krx_raw_market_date_partitions": {"partition_count": len(raw_inventory), "files": raw_inventory, "hash_check": raw_hash_status},
        "sample_evidence": {"manifest_sha256": pre_sample_hash, "files": sample_files},
        **revision_provenance,
        "external_api_requests": 0,
        "signal_evaluation_workers": 10,
        "prior_p2_1_trade_ledger_reused": False,
        "p2_2_signal_ledger_reused": False,
        "files": ordered_files,
    }
    (OUT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "source_file_count": len(ordered_files), "reference_bundle_count": len(reference_checks), "adjusted_price_ticker_count": len(adjusted), "krx_raw_partition_count": len(raw_inventory), "adjusted_hash_check": adjusted_hash_status, "raw_hash_check": raw_hash_status, "pre_sample_manifest_sha256": pre_sample_hash}, ensure_ascii=False, indent=2), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
