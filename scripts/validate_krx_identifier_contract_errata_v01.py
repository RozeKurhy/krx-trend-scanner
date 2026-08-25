#!/usr/bin/env python3
"""Network-free validator for KRX_IDENTIFIER_CONTRACT_ERRATA_V01."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ERRATA_ROOT = ROOT / "artifacts/data/architecture/krx_production_data/v01/errata"
CLOSED_ROOT = ROOT / "artifacts/data/architecture/krx_production_data/v01"
sys.path.insert(0, str(SRC))

from trend_scanner.data.source_contracts import (  # noqa: E402
    ARCHITECTURE_VERSION,
    ENDPOINT_IDENTIFIER_CONTRACT,
    STORE_FIELD_PROVENANCE,
)
from trend_scanner.data.krx_raw_stock_provider import (  # noqa: E402
    KRX_SHORT_CODE_PATTERN,
    is_valid_krx_short_code,
)


ERRATA_ID = "KRX_IDENTIFIER_CONTRACT_ERRATA_V01"
START_HEAD = "086eaa20edd19259b8c6ca38dd37cca406de32cd"
EXPECTED_VERSION = "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_ERRATA01"
EXPECTED_CANDIDATE_REGEX = "^[0-9A-Z]{6}$"
ALLOWED_PATHS = {
    "src/trend_scanner/data/source_contracts.py",
    "src/trend_scanner/data/krx_raw_stock_provider.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "scripts/validate_krx_identifier_contract_errata_v01.py",
    "tests/test_krx_identifier_contract_errata_v01.py",
    "tests/test_krx_raw_stock_provider.py",
    "tests/test_krx_raw_stock_store.py",
    "tests/test_krx_production_data_architecture_v01.py",
    "docs/architecture/errata/krx_identifier_contract_errata_v01.md",
}
ERRATA_PREFIX = "artifacts/data/architecture/krx_production_data/v01/errata/"
FIX06_PREFIX = "artifacts/data/krx_historical_backfill/v01/FIX06_"
SECRET_ASSIGNMENT = re.compile(r"\b(?:KRX_ID|KRX_PW|KRX_OPEN_API_AUTH_KEY)\s*=\s*(['\"])(?!<redacted>|your_|change_me|$)[^'\"]+\1")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _load(name: str) -> dict[str, Any]:
    path = ERRATA_ROOT / name
    return json.loads(path.read_text(encoding="utf-8"))


def _changed_paths() -> list[str]:
    output = _git("diff", "--name-only", f"{START_HEAD}..HEAD")
    return [item for item in output.splitlines() if item]


def _all_changed_paths_including_worktree() -> list[str]:
    paths = set(_changed_paths())
    for command in (("diff", "--name-only"), ("diff", "--cached", "--name-only")):
        paths.update(item for item in _git(*command).splitlines() if item)
    return sorted(paths)


def _secret_count() -> int:
    tracked = _git("ls-files").splitlines()
    count = 0
    for relative in tracked:
        path = ROOT / relative
        if not path.is_file() or relative.endswith((".parquet", ".db", ".sqlite3")):
            continue
        try:
            count += len(SECRET_ASSIGNMENT.findall(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return count


def _closed_history_overwrite_count(changed: list[str]) -> int:
    return sum(
        path.startswith("artifacts/data/architecture/krx_production_data/v01/")
        and not path.startswith(ERRATA_PREFIX)
        for path in changed
    )


def _validate_census() -> dict[str, int]:
    daily = _load("identifier_shape_census.json")
    basic = _load("basic_info_identifier_census.json")
    aggregate = daily["aggregate"]
    errors = 0
    errors += int(daily["candidate_regex"] != EXPECTED_CANDIDATE_REGEX)
    errors += int(daily["decision"] != "VALIDATED_KRX_SHORT_CODE")
    errors += int(aggregate["total_records"] != 2164)
    errors += int(aggregate["invalid_length_count"] != 0 or aggregate["invalid_charset_count"] != 0)
    errors += int(aggregate["all_match_candidate_regex"] is not True or aggregate["contains_letter_count"] <= 0)
    errors += int(daily["requests"] != 2 or daily["retries"] != 0)
    for market, expected_count in (("KOSPI", 892), ("KOSDAQ", 1272)):
        row = daily["per_market"][market]
        errors += int(row["record_count"] != expected_count or row["records_key"] != "OutBlock_1")
        errors += int(row["http_status"] != 200 or row["isu_cd_missing_count"] != 0 or row["empty_count"] != 0)
        errors += int(row["invalid_length_count"] != 0 or row["invalid_charset_count"] != 0)
    errors += int(basic["status"] != "VALIDATED_KRX_SHORT_CODE")
    errors += int(basic["primary_requests"] != 2 or basic["retries"] != 0)
    errors += int(basic["fallback"]["executed"] is not False or basic["fallback"]["requests"] != 0)
    for market, expected_count in (("KOSPI", 892), ("KOSDAQ", 1272)):
        row = basic["per_market"][market]
        errors += int(row["record_count"] != expected_count or row["records_key"] != "OutBlock_1" or row["http_status"] != 200)
        errors += int(row["missing_count"] != 0 or row["empty_count"] != 0 or row["invalid_count"] != 0)
    return {"census_contract_error_count": errors}


def _validate_runtime_contract() -> dict[str, int]:
    by_key = {(item.owner_store, item.target_field): item for item in STORE_FIELD_PROVENANCE}
    errors = 0
    errors += int(ARCHITECTURE_VERSION != EXPECTED_VERSION)
    errors += int(ENDPOINT_IDENTIFIER_CONTRACT["DAILY_TRADING"]["fields"]["ISU_CD"]["identifier_namespace"] != "KRX_SHORT_CODE")
    errors += int(ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["ISU_SRT_CD"]["identifier_namespace"] != "KRX_SHORT_CODE")
    for key in (("KRXRawStockStore", "ticker"), ("StockMasterStore", "ticker"), ("InstrumentClassificationStore", "ticker")):
        errors += int(by_key[key].source_semantics != "KRX_SHORT_CODE")
    errors += int(KRX_SHORT_CODE_PATTERN.pattern != EXPECTED_CANDIDATE_REGEX)
    errors += int(not all(is_valid_krx_short_code(value) for value in ("005930", "03473K", "08537M")))
    errors += int(any(is_valid_krx_short_code(value) for value in ("03473k", "03473-K", "KR7005930003", "3473K")))
    return {"runtime_contract_error_count": errors}


def _validate_impact_matrix() -> dict[str, int]:
    matrix = _load("identifier_impact_matrix.json")
    required = {"source_contracts", "krx_raw_stock_provider", "StockMaster provider", "InstrumentClassification", "instrument_metadata", "asset_classifier", "adjusted_price_provider", "PyKRX universe loader", "foreign flow provider", "MarketDataRepository", "Stock Report", "Pattern A", "FastCore", "Julia"}
    audited = set(matrix["required_concepts_audited"])
    return {
        "impact_audit_error_count": int(not required.issubset(audited) or matrix["consumer_auto_migration_count"] != 0 or matrix["total_hits"] != len(matrix["hits"])),
        "impact_total_hits": len(matrix["hits"]),
        "consumer_auto_migration_count": matrix["consumer_auto_migration_count"],
    }


def validate() -> dict[str, Any]:
    changed = _all_changed_paths_including_worktree()
    disallowed = [path for path in changed if path not in ALLOWED_PATHS and not path.startswith(ERRATA_PREFIX) and not path.startswith(FIX06_PREFIX)]
    census = _validate_census()
    runtime = _validate_runtime_contract()
    impact = _validate_impact_matrix()
    required_artifacts = ("krx_identifier_contract_errata_v01.json", "identifier_shape_census.json", "basic_info_identifier_census.json", "identifier_impact_matrix.json", "errata_validation_summary.json", "errata_manifest.json")
    missing_artifacts = [name for name in required_artifacts if not (ERRATA_ROOT / name).exists()]
    counters = {
        **census,
        **runtime,
        **impact,
        "missing_artifact_count": len(missing_artifacts),
        "historical_closed_artifact_overwrite_count": _closed_history_overwrite_count(changed),
        "secret_occurrence_count": _secret_count(),
        "git_diff_check_error_count": int(bool(_git("diff", "--check"))),
        "disallowed_path_count": len(disallowed),
        "short_code_sample_contract_error_count": int(not all(is_valid_krx_short_code(value) for value in ("005930", "005935", "03473K", "08537M"))),
    }
    required_zero = tuple(name for name in counters if name not in {"impact_total_hits"})
    blockers = [name for name in required_zero if counters[name] not in (0,)]
    status = "READY_FOR_ARCHITECT_KRX_IDENTIFIER_CONTRACT_ERRATA_V01_REVIEW" if not blockers else "BLOCKED_IDENTIFIER_CONTRACT_ERRATA"
    return {
        "errata_id": ERRATA_ID,
        "architecture_version": EXPECTED_VERSION,
        "start_head": START_HEAD,
        "implementation_head": _git("rev-parse", "HEAD"),
        "validation_source_head": _git("rev-parse", "HEAD"),
        "end_head": None,
        "branch": _git("branch", "--show-current"),
        "changed_paths": changed,
        "disallowed_paths": disallowed,
        "missing_artifacts": missing_artifacts,
        "counters": counters,
        "required_zero": list(required_zero),
        "blockers": blockers,
        "status": status,
        "recommendation": status,
        "network": {"daily_census": 2, "basic_info_primary": 2, "basic_info_fallback": 0, "corrected_diagnostic": 0, "retries": 0, "validator_network_requests": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ERRATA_ROOT)
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    result = validate()
    (output / "errata_validation_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = _load("errata_manifest.json") if (output / "errata_manifest.json").exists() else {}
    manifest.update({"implementation_head": result["implementation_head"], "validation_source_head": result["validation_source_head"], "end_head": None, "status": result["status"]})
    (output / "errata_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "blockers": result["blockers"], "network_requests": result["network"]["validator_network_requests"]}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
