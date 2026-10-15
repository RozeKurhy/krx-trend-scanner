"""Fail-closed V13 eligibility gate for the saved A FAST Alignment candidate.

This module only validates the single V05 candidate bound below and its V12
independent evidence. It does not replay strategy logic or publish files.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


class AlignmentEligibilityGateError(RuntimeError):
    """A saved candidate or its independent eligibility evidence failed closed."""


EXPECTED = {
    "candidate_digest": "3993cc22f55f52b169736159637662e93ebac3c0f4edac4fe0946f2fd933733c",
    "current_public_digest": "e3c6ecc19187eb8951c1c9ef1626a2b54a9cffe1f6d415721b75a0cca8e89b61",
    "requested_as_of": "2026-10-11",
    "reference_market_date": "2026-10-08",
    "common_count": 1459,
    "trade_count": 423,
    "realized_count": 398,
    "open_count": 25,
    "gate_count": 20012,
    "blocker_event_count": 204,
    "blocker_identity_count": 54,
    "permanent_exclusion_count": 185,
    "etf_count": 36,
}

EXPECTED_HASHES = {
    "v05_source_manifest": "7acc71a0577f3989ced17c88e027039bc09d138bb7c59c3791d06777bf022964",
    "v05_stage_manifest": "7748b26386c3bbcc98c0b9643c5b8a0a4e3844a97de5cb7d7ccc6145409e65df",
    "v12_validation": "b5f4f455f182a5fa213572b3c6f7c517dd038a571da18dde321000ea52112891",
    "v12_source_manifest": "640c4a349bdf9bffb27db1b364aa9e32c1882b5439c70e83d77bd533065a2ad8",
    "v09_stage_manifest": "7b0dd1bf03bd96a3bbeda20c0336d3648594b6e0fb20cbe2aa6266297b08097b",
    # V12 recorded this exact source version before the V13 boundary change.
    "phase4d_source_at_v12": "c1695cf267eb8a87b4ff475eb3c6a770246b32a80023f2ec14191920dc399873",
}

EXPECTED_BLOCKER_COUNTS = {
    "ADJUSTED_PRICE_HISTORY_TOO_SHORT": 1,
    "REPLAY_STATE_UNAVAILABLE": 19,
    "REFERENCE_MARKET_DATE_PRICE_GAP": 18,
    "COMPLETED_MONTH_MA_HISTORY_GAP": 166,
}

KEY_FIELDS = (
    "blocker_code",
    "ticker",
    "isu_cd",
    "event_date",
    "reference_market_date",
    "reason_code",
    "root_cause_type",
)

V05_RUN_REL = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "fast_core_v2_alignment_500b_production_guard_v05/run_20261015"
)
V05_STAGE_REL = V05_RUN_REL / "staging/staging_20261015T082200Z"
V06_RUN_REL = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "fast_core_v2_alignment_500b_v05_baseline_blocker_closure_v06/run_20261015"
)
V07_RUN_REL = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "fast_core_v2_v06_closure_signoff_and_ci_preflight_v07/run_20261015"
)
V09_RUN_REL = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "a_fast_alignment_500b_v09_strict_baseline_approval_and_phase4d_preflight/run_20261015"
)
V09_STAGE_REL = V09_RUN_REL / "phase4d_stage"
V12_RUN_REL = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "a_fast_alignment_500b_v12_independent_publication_eligibility/run_20261016"
)

V08_WORK_ORDER_PATH = "/Users/june/Documents/projects/w.md"
V12_PHASE4D_SOURCE_PATH = "scripts/run_daily_update_phase4d_v01.py"
PERMITTED_V12_SOURCE_DRIFTS = {
    V08_WORK_ORDER_PATH,
    V12_PHASE4D_SOURCE_PATH,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AlignmentEligibilityGateError(code)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlignmentEligibilityGateError(f"EVIDENCE_JSON_INVALID:{path}") from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except OSError as exc:
        raise AlignmentEligibilityGateError(f"EVIDENCE_CSV_MISSING:{path}") from exc


def _normalize(field: str, value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if field in {
        "allowed",
        "entry_created",
        "v05_blocker_in_scope",
        "baseline_exact_match",
        "phase10_baseline_match",
    }:
        return text.strip().lower()
    if field == "evidence_paths" or field.endswith("_json") or field == "price_session_evidence":
        try:
            return json.dumps(
                json.loads(text),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, json.JSONDecodeError):
            return text.strip()
    return text.strip()


def _event_key(row: dict[str, Any]) -> tuple[str, ...]:
    key = tuple(_normalize(field, row.get(field)) for field in KEY_FIELDS)
    if not all(key):
        raise AlignmentEligibilityGateError("BLOCKER_EVENT_KEY_MISSING")
    code, ticker, isu_cd, event_date, reference_date, _reason, _cause = key
    _require(code in EXPECTED_BLOCKER_COUNTS, "BLOCKER_CODE_UNREGISTERED")
    _require(len(ticker) == 6 and ticker.isdigit(), "BLOCKER_TICKER_INVALID")
    _require(
        len(isu_cd) == 12 and isu_cd[:2] in {"KR", "HK"} and isu_cd[2:].isdigit(),
        "BLOCKER_ISU_INVALID",
    )
    _require(event_date <= reference_date == EXPECTED["reference_market_date"], "BLOCKER_DATE_BINDING_INVALID")
    return key


def _index_unique(rows: Iterable[dict[str, Any]], label: str) -> dict[tuple[str, ...], dict[str, Any]]:
    indexed: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = _event_key(row)
        if key in indexed:
            raise AlignmentEligibilityGateError(f"BLOCKER_EVENT_DUPLICATE:{label}")
        indexed[key] = row
    return indexed


def reconcile_blocker_events(
    v06_rows: list[dict[str, Any]],
    v07_rows: list[dict[str, Any]],
    v12_event_rows: list[dict[str, Any]],
    common_identity_by_ticker: dict[str, str],
    *,
    expected_event_count: int = EXPECTED["blocker_event_count"],
    expected_code_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Re-derive V12's 204-row event set without consuming V08 event rows."""
    expected_code_counts = expected_code_counts or EXPECTED_BLOCKER_COUNTS
    scoped_v06 = [
        row for row in v06_rows
        if _normalize("v05_blocker_in_scope", row.get("v05_blocker_in_scope")) == "true"
        and row.get("classification") == "BASELINE_DATA_LIMITATION"
    ]
    v06 = _index_unique(scoped_v06, "V06")
    v07 = _index_unique(v07_rows, "V07")
    _require(len(v06) == expected_event_count, "BLOCKER_V06_EVENT_COUNT_MISMATCH")
    _require(len(v07) == expected_event_count, "BLOCKER_V07_EVENT_COUNT_MISMATCH")
    _require(set(v06) == set(v07), "BLOCKER_V06_V07_EVENT_SET_MISMATCH")

    counts = Counter(key[0] for key in v06)
    _require(dict(counts) == expected_code_counts, "BLOCKER_CODE_COUNTS_MISMATCH")
    identities = {(key[1], key[2]) for key in v06}
    _require(
        len({key[1] for key in v06}) == EXPECTED["blocker_identity_count"]
        if expected_event_count == EXPECTED["blocker_event_count"]
        else len({key[1] for key in v06}) == len(identities),
        "BLOCKER_TICKER_IDENTITY_COUNT_MISMATCH",
    )
    _require(
        len(identities) == EXPECTED["blocker_identity_count"]
        if expected_event_count == EXPECTED["blocker_event_count"]
        else True,
        "BLOCKER_TICKER_ISU_IDENTITY_COUNT_MISMATCH",
    )

    common_fields = set(v06[next(iter(v06))]) & set(v07[next(iter(v07))])
    allowed_true_count = 0
    entry_created_true_count = 0
    for key in sorted(v06):
        before, after = v06[key], v07[key]
        for field in common_fields:
            _require(
                _normalize(field, before.get(field)) == _normalize(field, after.get(field)),
                f"BLOCKER_COMMON_FIELD_MISMATCH:{field}",
            )
        _require(before.get("classification") == "BASELINE_DATA_LIMITATION", "BLOCKER_CLASSIFICATION_INVALID")
        _require(after.get("classification") == "BASELINE_DATA_LIMITATION", "BLOCKER_DISPOSITION_INVALID")
        if _normalize("allowed", before.get("allowed")) in {"true", "1"}:
            allowed_true_count += 1
        if _normalize("allowed", after.get("allowed")) in {"true", "1"}:
            allowed_true_count += 1
        if _normalize("entry_created", before.get("entry_created")) in {"true", "1"}:
            entry_created_true_count += 1
        if _normalize("entry_created", after.get("entry_created")) in {"true", "1"}:
            entry_created_true_count += 1
        _require(_normalize("allowed", before.get("allowed")) in {"false", "0"}, "BLOCKER_V06_ALLOWED_TRUE")
        _require(_normalize("allowed", after.get("allowed")) in {"false", "0"}, "BLOCKER_V07_ALLOWED_TRUE")
        _require(_normalize("entry_created", before.get("entry_created")) in {"false", "0", ""}, "BLOCKER_V06_ENTRY_CREATED")
        _require(_normalize("entry_created", after.get("entry_created")) in {"false", "0", ""}, "BLOCKER_V07_ENTRY_CREATED")
        _require(common_identity_by_ticker.get(key[1]) == key[2], "BLOCKER_CANDIDATE_IDENTITY_MISMATCH")

    v12_by_key = {
        tuple(_normalize(field, event.get("event_key", {}).get(field)) for field in KEY_FIELDS): event
        for event in v12_event_rows
    }
    _require(len(v12_by_key) == len(v12_event_rows), "BLOCKER_V12_EVENT_DUPLICATE")
    _require(set(v12_by_key) == set(v06), "BLOCKER_V12_EVENT_SET_MISMATCH")
    source_evidence_hashes: dict[str, str] = {}
    for key in sorted(v06):
        before, after, saved = v06[key], v07[key], v12_by_key[key]
        key_payload = dict(zip(KEY_FIELDS, key, strict=True))
        event_id = sha256_bytes(canonical_json(key_payload))
        _require(saved.get("event_id") == event_id, "BLOCKER_V12_EVENT_ID_MISMATCH")
        _require(saved.get("eligibility_class") == "VERIFIED_BASELINE_DATA_LIMITATION", "BLOCKER_V12_ELIGIBILITY_CLASS_INVALID")
        _require(
            sha256_bytes(canonical_json(before)) == saved.get("v06_source_row_sha256"),
            "BLOCKER_V12_V06_ROW_HASH_MISMATCH",
        )
        _require(
            sha256_bytes(canonical_json(after)) == saved.get("v07_source_row_sha256"),
            "BLOCKER_V12_V07_ROW_HASH_MISMATCH",
        )
        _require(_normalize("allowed", saved.get("allowed")) in {"false", "0"}, "BLOCKER_V12_ALLOWED_TRUE")
        _require(_normalize("entry_created", saved.get("entry_created")) in {"false", "0", ""}, "BLOCKER_V12_ENTRY_CREATED")
        v06_refs = json.loads(str(before.get("evidence_paths") or "[]"))
        v12_refs = saved.get("source_evidence_paths")
        _require(isinstance(v12_refs, list) and set(v06_refs) == set(v12_refs), "BLOCKER_V12_EVIDENCE_PATH_SET_MISMATCH")
        declared_hashes = saved.get("source_evidence_sha256")
        _require(isinstance(declared_hashes, dict) and set(declared_hashes) == set(v06_refs), "BLOCKER_V12_EVIDENCE_HASH_SET_MISMATCH")
        for rel in v06_refs:
            _require("v08" not in rel.lower(), "BLOCKER_V08_EVIDENCE_USED")
            previous = source_evidence_hashes.setdefault(rel, str(declared_hashes[rel]))
            _require(previous == str(declared_hashes[rel]), "BLOCKER_EVIDENCE_HASH_CONFLICT")

    _require(allowed_true_count == 0, "BLOCKER_ALLOWED_TRUE_COUNT_NONZERO")
    _require(entry_created_true_count == 0, "BLOCKER_ENTRY_CREATED_COUNT_NONZERO")
    _require(not any("v08" in path.lower() for path in source_evidence_hashes), "BLOCKER_V08_SOURCE_REFERENCE_PRESENT")
    return {
        "event_count": len(v06),
        "v06_event_count": len(v06),
        "v07_event_count": len(v07),
        "v12_event_count": len(v12_by_key),
        "unique_ticker_count": len({key[1] for key in v06}),
        "unique_ticker_isu_count": len(identities),
        "counts_by_blocker_code": dict(sorted(counts.items())),
        "common_field_mismatch_count": 0,
        "duplicate_count": 0,
        "allowed_true_count": allowed_true_count,
        "entry_created_true_count": entry_created_true_count,
        "source_evidence_file_count": len(source_evidence_hashes),
        "source_evidence_sha256": dict(sorted(source_evidence_hashes.items())),
        "v08_event_rows_used": False,
    }


def verify_pinned_file(path: Path, expected_sha256: str, label: str) -> str:
    _require(path.is_file(), f"PINNED_FILE_MISSING:{label}")
    actual = sha256_file(path)
    _require(actual == expected_sha256, f"PINNED_FILE_SHA256_MISMATCH:{label}")
    return actual


def candidate_noop_decision(
    candidate_digest: str,
    published_digest: str | None,
    published_payload_valid: bool,
) -> str:
    """Only a fully validated identical publication can use the NOOP branch."""
    if candidate_digest == published_digest and published_payload_valid:
        return "NOOP_ALREADY_COMPLETE"
    return "VALIDATE_NEW_CANDIDATE"


def verify_candidate_binding(binding: dict[str, Any]) -> dict[str, Any]:
    """Reject a date, digest, or COMMON-universe binding outside this V13 work order."""
    _require(binding.get("requested_as_of") == EXPECTED["requested_as_of"], "V12_REQUESTED_AS_OF_MISMATCH")
    _require(binding.get("reference_market_date") == EXPECTED["reference_market_date"], "V12_REFERENCE_DATE_MISMATCH")
    _require(binding.get("strategy_replay_digest") == EXPECTED["candidate_digest"], "V12_CANDIDATE_DIGEST_MISMATCH")
    _require(binding.get("common_ticker_count") == EXPECTED["common_count"], "V12_COMMON_COUNT_MISMATCH")
    _require(binding.get("v05_source_manifest_sha256") == EXPECTED_HASHES["v05_source_manifest"], "V12_V05_SOURCE_MANIFEST_BINDING_MISMATCH")
    _require(binding.get("v05_stage_manifest_sha256") == EXPECTED_HASHES["v05_stage_manifest"], "V12_V05_STAGE_MANIFEST_BINDING_MISMATCH")
    return {
        "requested_as_of": binding["requested_as_of"],
        "reference_market_date": binding["reference_market_date"],
        "candidate_digest": binding["strategy_replay_digest"],
        "common_ticker_count": binding["common_ticker_count"],
        "common_ticker_set_sha256": binding.get("common_ticker_set_sha256"),
    }


def _stage_file_map(stage_root: Path, *, omit_root_manifest: bool = False) -> dict[str, str]:
    if not stage_root.is_dir():
        raise AlignmentEligibilityGateError(f"STAGE_DIRECTORY_MISSING:{stage_root}")
    mapping: dict[str, str] = {}
    for path in sorted(stage_root.rglob("*")):
        if path.is_symlink():
            raise AlignmentEligibilityGateError(f"STAGE_SYMLINK_FORBIDDEN:{path}")
        if not path.is_file():
            continue
        relative = path.relative_to(stage_root).as_posix()
        if omit_root_manifest and relative == "manifest.json":
            continue
        mapping[relative] = sha256_file(path)
    return mapping


def verify_declared_stage_files(
    stage_root: Path,
    declared: dict[str, str],
    *,
    label: str,
    omit_root_manifest: bool = False,
) -> dict[str, Any]:
    actual = _stage_file_map(stage_root, omit_root_manifest=omit_root_manifest)
    missing = sorted(set(declared) - set(actual))
    extra = sorted(set(actual) - set(declared))
    mismatched = sorted(path for path in set(actual) & set(declared) if actual[path] != declared[path])
    _require(not missing and not extra and not mismatched, f"STAGE_FILE_SHA_MISMATCH:{label}")
    return {
        "path": str(stage_root),
        "declared_file_count": len(declared),
        "actual_file_count": len(actual),
        "matched_file_count": len(declared),
        "missing_count": 0,
        "extra_count": 0,
        "mismatch_count": 0,
        "fingerprint_sha256": sha256_bytes(canonical_json(actual)),
    }


def _source_hash_for(root: Path, key: str) -> str | None:
    if key.startswith("origin/main:"):
        git_path = key.split(":", 1)[1]
        result = subprocess.run(
            ["git", "show", f"origin/main:{git_path}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return sha256_bytes(result.stdout) if result.returncode == 0 else None
    path = Path(key)
    if not path.is_absolute():
        path = root / path
    return sha256_file(path) if path.is_file() else None


def _verify_v12_source_manifest(root: Path, v12_validation: dict[str, Any], source_manifest: dict[str, Any]) -> dict[str, Any]:
    source_map = source_manifest.get("source_files_sha256")
    _require(isinstance(source_map, dict) and len(source_map) == 169, "V12_SOURCE_MAP_SCHEMA_INVALID")
    mismatches: list[str] = []
    missing: list[str] = []
    expected_runner_hash: str | None = None
    workorder_drift: list[str] = []
    implementation_drift: list[str] = []
    for key, record in source_map.items():
        expected_hash = record.get("sha256") if isinstance(record, dict) else record
        _require(isinstance(expected_hash, str) and len(expected_hash) == 64, "V12_SOURCE_HASH_RECORD_INVALID")
        if key == V12_PHASE4D_SOURCE_PATH:
            expected_runner_hash = expected_hash
            _require(expected_hash == EXPECTED_HASHES["phase4d_source_at_v12"], "V12_PHASE4D_SOURCE_BINDING_INVALID")
            current = _source_hash_for(root, key)
            if current != expected_hash:
                implementation_drift.append(key)
            continue
        current = _source_hash_for(root, key)
        if current is None:
            missing.append(key)
        elif current != expected_hash:
            if key == V08_WORK_ORDER_PATH:
                workorder_drift.append(key)
            else:
                mismatches.append(key)
    _require(not missing, "V12_REFERENCED_INPUT_MISSING")
    _require(not mismatches, "V12_REFERENCED_INPUT_HASH_MISMATCH")
    _require(workorder_drift in ([], [V08_WORK_ORDER_PATH]), "V12_WORK_ORDER_DRIFT_UNEXPECTED")
    _require(implementation_drift in ([], [V12_PHASE4D_SOURCE_PATH]), "V13_IMPLEMENTATION_DRIFT_UNEXPECTED")

    recorded_drift = source_manifest.get("V06_V07_input_hash_checks", {})
    for label, declared, matched in (("V06", 34, 33), ("V07", 35, 34)):
        check = recorded_drift.get(label, {})
        _require(check.get("declared_inputs") == declared, f"{label}_INPUT_PROVENANCE_COUNT_INVALID")
        _require(check.get("matched_current") == matched, f"{label}_INPUT_PROVENANCE_MATCH_COUNT_INVALID")
        _require(
            check.get("mismatches") == [{"path": V08_WORK_ORDER_PATH, "reason": "WORK_ORDER_REVISION_DRIFT"}],
            f"{label}_WORK_ORDER_DRIFT_RECORD_INVALID",
        )
        _require(not check.get("V08_direct_input_paths"), f"{label}_V08_DIRECT_INPUT_PRESENT")
        _require(check.get("output_hash_mismatch_count") == 0, f"{label}_OUTPUT_HASH_MISMATCH")
        _require("does not parse" in str(check.get("generator_inspection", "")), f"{label}_WORK_ORDER_PARSE_SCOPE_UNVERIFIED")

    output_hashes = source_manifest.get("output_sha256_excluding_this_manifest")
    _require(isinstance(output_hashes, dict) and len(output_hashes) == 4, "V12_OUTPUT_HASH_MAP_INVALID")
    v12_dir = root / V12_RUN_REL
    output_mismatches = []
    for relative, expected_hash in output_hashes.items():
        path = v12_dir / relative
        if not path.is_file() or sha256_file(path) != expected_hash:
            output_mismatches.append(relative)
    _require(not output_mismatches, "V12_OUTPUT_HASH_MISMATCH")
    return {
        "declared_source_file_count": len(source_map),
        "matched_source_file_count": len(source_map) - len(workorder_drift) - len(implementation_drift),
        "unexpected_mismatch_count": len(mismatches),
        "missing_count": len(missing),
        "expected_work_order_revision_drift": workorder_drift,
        "v13_implementation_source_drift": implementation_drift,
        "phase4d_source_hash_recorded_by_v12": expected_runner_hash,
        "v12_output_hash_mismatch_count": 0,
    }


def _verify_v06_v07_output_manifests(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, run_rel in (("V06", V06_RUN_REL), ("V07", V07_RUN_REL)):
        run_dir = root / run_rel
        manifest = _read_json(run_dir / "source_manifest.json")
        outputs = manifest.get("outputs_sha256_excluding_this_manifest")
        expected_count = 14 if label == "V06" else 12
        _require(isinstance(outputs, dict) and len(outputs) == expected_count, f"{label}_OUTPUT_MANIFEST_INVALID")
        mismatches = [
            name for name, expected in outputs.items()
            if not (run_dir / name).is_file() or sha256_file(run_dir / name) != expected
        ]
        _require(not mismatches, f"{label}_OUTPUT_MANIFEST_HASH_MISMATCH")
        result[label] = {"declared": expected_count, "matched": expected_count, "mismatch_count": 0}
    return result


def _verify_current_protected_trees(root: Path, v12_validation: dict[str, Any]) -> dict[str, Any]:
    from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import canonical_exclusion_sha256
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

    v05_run = root / V05_RUN_REL
    protected = _read_json(v05_run / "protected_sha256.json")
    expected_trees = v12_validation["candidate_trade_gate_and_protection"]["protected_trees"]
    tree_paths = {
        "b_select_status": Path("artifacts/strategies/b_select_core_v2/production/20261011"),
        "julia_reports": Path("artifacts/reporting/etf_stock_reports/20261011"),
        "official_stock_reports": Path("artifacts/reporting/stock_reports/20261011"),
        "web_data": Path("web/data"),
    }
    checked: dict[str, Any] = {}
    for name, relative in tree_paths.items():
        path = root / relative
        _require(path.is_dir(), f"PROTECTED_TREE_MISSING:{name}")
        files = sorted(item for item in path.rglob("*") if item.is_file())
        digest = hashlib.sha256()
        for file in files:
            rel = file.relative_to(path).as_posix()
            item_hash = sha256_file(file)
            digest.update(rel.encode("utf-8") + b"\0" + item_hash.encode("ascii") + b"\n")
        actual_tree_hash = digest.hexdigest()
        v05_expected = protected["protected_trees"][name]
        v12_expected = expected_trees[name]
        _require(actual_tree_hash == v05_expected["baseline_tree_sha256"], f"PROTECTED_TREE_BASELINE_MISMATCH:{name}")
        _require(actual_tree_hash == v12_expected["current_tree_sha256"], f"PROTECTED_TREE_V12_MISMATCH:{name}")
        _require(len(files) == v05_expected["file_count"] == v12_expected["file_count"], f"PROTECTED_TREE_FILE_COUNT_MISMATCH:{name}")
        _require(v05_expected["tree_matches_baseline"] is True, f"PROTECTED_TREE_V05_STATUS_INVALID:{name}")
        _require(v12_expected["match"] is True, f"PROTECTED_TREE_V12_STATUS_INVALID:{name}")
        checked[name] = {"path": relative.as_posix(), "file_count": len(files), "sha256": actual_tree_hash, "matches_v05_and_v12": True}

    exclusion_pairs = {(str(ticker).zfill(6), str(isu).strip().upper()) for ticker, isu in PERMANENT_IDENTITY_EXCLUSIONS}
    exclusion_hash = canonical_exclusion_sha256(exclusion_pairs)
    exclusion_expected = v12_validation["candidate_trade_gate_and_protection"]["exclusion_registry"]
    _require(len(exclusion_pairs) == EXPECTED["permanent_exclusion_count"], "PERMANENT_EXCLUSION_COUNT_MISMATCH")
    _require(exclusion_hash == exclusion_expected["canonical_sha256"], "PERMANENT_EXCLUSION_HASH_MISMATCH")
    _require(exclusion_expected["pair_count"] == EXPECTED["permanent_exclusion_count"], "PERMANENT_EXCLUSION_V12_COUNT_MISMATCH")

    return {
        "trees": checked,
        "permanent_exclusion_pair_count": len(exclusion_pairs),
        "permanent_exclusion_canonical_sha256": exclusion_hash,
    }


def _verify_saved_replay_outputs(root: Path, v12_validation: dict[str, Any], v05_manifest: dict[str, Any]) -> dict[str, Any]:
    v05_run = root / V05_RUN_REL
    saved_result = _read_json(v05_run / "full_replay_result.json")
    parity = _read_json(v05_run / "parity_and_protection.json")
    validation_summary = _read_json(v05_run / "validation_summary.json")
    v12_trade = v12_validation["candidate_trade_gate_and_protection"]["trade_gate"]

    summary_counts = saved_result.get("trade_counts", {})
    _require(summary_counts.get("total") == EXPECTED["trade_count"], "SAVED_TRADE_TOTAL_MISMATCH")
    _require(summary_counts.get("realized") == EXPECTED["realized_count"], "SAVED_TRADE_REALIZED_MISMATCH")
    _require(summary_counts.get("open") == EXPECTED["open_count"], "SAVED_TRADE_OPEN_MISMATCH")
    _require(saved_result.get("strategy_replay_digest") == EXPECTED["candidate_digest"], "SAVED_REPLAY_DIGEST_MISMATCH")
    _require(v05_manifest.get("trade_counts", {}).get("total") == EXPECTED["trade_count"], "V05_MANIFEST_TRADE_TOTAL_MISMATCH")

    trade_rows = _read_csv(v05_run / "trade_diff_423.csv")
    _require(len(trade_rows) == EXPECTED["trade_count"], "TRADE_LEDGER_ROW_COUNT_MISMATCH")
    _require(len({(row.get("ticker"), row.get("trade_id")) for row in trade_rows}) == EXPECTED["trade_count"], "TRADE_LEDGER_DUPLICATE_KEY")
    statuses = Counter(row.get("new_trade_status") for row in trade_rows)
    _require(statuses.get("REALIZED") == EXPECTED["realized_count"], "TRADE_LEDGER_REALIZED_COUNT_MISMATCH")
    _require(statuses.get("OPEN_AT_CUTOFF") == EXPECTED["open_count"], "TRADE_LEDGER_OPEN_COUNT_MISMATCH")
    change_classes = Counter(row.get("change_class") for row in trade_rows)
    _require(change_classes == {"CJ_CORRECTED": 1, "UNCHANGED": 422}, "TRADE_LEDGER_CHANGE_CLASS_MISMATCH")
    cj_rows = [row for row in trade_rows if row.get("trade_id") == "079160_01"]
    _require(len(cj_rows) == 1, "CJ_TRADE_ROW_MISSING_OR_DUPLICATE")
    cj = cj_rows[0]
    _require(
        cj.get("new_exit_signal_date") == "2016-09-30"
        and cj.get("new_exit_execution_date") == "2016-10-04"
        and float(cj.get("new_exit_price") or 0) == 52982.0
        and float(cj.get("new_return_pct") or 0) == 41.21
        and cj.get("new_trade_status") == "REALIZED",
        "CJ_EXECUTION_CONTRACT_MISMATCH",
    )

    gate_diff = _read_csv(v05_run / "gate_audit_diff.csv")
    _require(not gate_diff, "SAVED_GATE_DIFF_NOT_EMPTY")
    _require(parity.get("gate_baseline_rows") == EXPECTED["gate_count"], "GATE_BASELINE_ROW_COUNT_MISMATCH")
    _require(parity.get("gate_current_rows") == EXPECTED["gate_count"], "GATE_CURRENT_ROW_COUNT_MISMATCH")
    _require(parity.get("gate_diff_classes") == {}, "GATE_DIFF_CLASSES_NOT_EMPTY")
    _require(parity.get("strategy_evaluator_error_count") == 0, "STRATEGY_EVALUATOR_ERRORS_PRESENT")
    _require(v12_trade.get("gate_baseline_rows") == EXPECTED["gate_count"], "V12_GATE_BASELINE_ROW_COUNT_MISMATCH")
    _require(v12_trade.get("gate_current_rows") == EXPECTED["gate_count"], "V12_GATE_CURRENT_ROW_COUNT_MISMATCH")
    _require(v12_trade.get("gate_diff_classes") == {}, "V12_GATE_DIFF_CLASSES_NOT_EMPTY")

    etf_rows = _read_csv(v05_run / "etf_hash_comparison.csv")
    etf_matches = sum(row.get("matches", "").lower() == "true" for row in etf_rows)
    _require(len(etf_rows) == EXPECTED["etf_count"] and etf_matches == EXPECTED["etf_count"], "ETF36_HASH_PARITY_FAILED")
    _require(parity.get("etf_count") == EXPECTED["etf_count"], "V05_ETF36_COUNT_MISMATCH")
    _require(parity.get("etf_hash_match_count") == EXPECTED["etf_count"], "V05_ETF36_HASH_MATCH_COUNT_MISMATCH")

    summary_check_ids = {item.get("id"): item.get("status") for item in validation_summary.get("checks", [])}
    _require(summary_check_ids.get("single_full_replay_1459") == "PASS", "V05_REPLAY_CHECK_NOT_PASS")
    _require(summary_check_ids.get("trade_ledger_contract") == "PASS", "V05_TRADE_CONTRACT_NOT_PASS")
    _require(summary_check_ids.get("gate_audit_exact_identity_date_reason_allowed") == "PASS", "V05_GATE_PARITY_CHECK_NOT_PASS")

    # V05 did not persist a worker-error aggregate in these saved files. Preserve that
    # limitation explicitly instead of inferring zero or starting another replay.
    worker_error_recorded = "worker_error_count" in parity and parity.get("worker_error_count") is not None
    worker_error_count = parity.get("worker_error_count") if worker_error_recorded else None
    if worker_error_recorded:
        _require(worker_error_count == 0, "V05_WORKER_ERRORS_PRESENT")
    _require(v12_trade.get("worker_error_field_present") is False, "V12_WORKER_ERROR_FIELD_EXPECTATION_MISMATCH")

    return {
        "trade_count": len(trade_rows),
        "trade_status_counts": dict(sorted(statuses.items())),
        "trade_change_classes": dict(sorted(change_classes.items())),
        "gate_baseline_rows": parity.get("gate_baseline_rows"),
        "gate_current_rows": parity.get("gate_current_rows"),
        "gate_diff_count": len(gate_diff),
        "strategy_evaluator_error_count": parity.get("strategy_evaluator_error_count"),
        "worker_error_count": worker_error_count,
        "worker_error_recorded": worker_error_recorded,
        "etf_count": len(etf_rows),
        "etf_hash_match_count": etf_matches,
        "cj_trade": {
            "trade_id": "079160_01",
            "exit_signal_date": cj["new_exit_signal_date"],
            "exit_execution_date": cj["new_exit_execution_date"],
            "exit_price": cj["new_exit_price"],
            "return_pct": cj["new_return_pct"],
        },
    }


def validate_alignment_candidate_evidence(
    root: Path | None = None,
    stage_root: Path | None = None,
    *,
    require_designated_stage_path: bool = True,
) -> dict[str, Any]:
    """Revalidate pinned V05/V12 inputs and the complete saved Phase4D shadow stage."""
    root = Path(root or Path(__file__).resolve().parents[3]).resolve()
    stage_root = Path(stage_root or (root / V09_STAGE_REL)).resolve()
    designated_stage_root = (root / V09_STAGE_REL).resolve()
    if require_designated_stage_path:
        _require(stage_root == designated_stage_root, "ALIGNMENT_STAGE_PATH_NOT_DESIGNATED")

    v05_run = root / V05_RUN_REL
    v05_stage = root / V05_STAGE_REL
    v06_run = root / V06_RUN_REL
    v07_run = root / V07_RUN_REL
    v09_run = root / V09_RUN_REL
    v12_run = root / V12_RUN_REL

    pinned = {
        "V05 source manifest": (v05_run / "source_manifest.json", EXPECTED_HASHES["v05_source_manifest"]),
        "V05 stage manifest": (v05_stage / "manifest.json", EXPECTED_HASHES["v05_stage_manifest"]),
        "V12 independent validation": (v12_run / "independent_eligibility_validation.json", EXPECTED_HASHES["v12_validation"]),
        "V12 source manifest": (v12_run / "source_manifest.json", EXPECTED_HASHES["v12_source_manifest"]),
        "V09 Phase4D stage manifest": (v09_run / "phase4d_stage_manifest.json", EXPECTED_HASHES["v09_stage_manifest"]),
    }
    pinned_checks = {label: verify_pinned_file(path, expected, label) for label, (path, expected) in pinned.items()}

    v05_source_manifest = _read_json(v05_run / "source_manifest.json")
    v05_manifest = _read_json(v05_stage / "manifest.json")
    v12_validation = _read_json(v12_run / "independent_eligibility_validation.json")
    v12_source_manifest = _read_json(v12_run / "source_manifest.json")
    v09_stage_manifest = _read_json(v09_run / "phase4d_stage_manifest.json")

    _require(v12_validation.get("schema") == "a_fast_alignment_500b_v12_independent_eligibility_validation", "V12_SCHEMA_INVALID")
    _require(v12_validation.get("decision") == "V12_INDEPENDENT_ELIGIBILITY_READY_FOR_USER_REVIEW", "V12_DECISION_NOT_REVIEW_READY")
    _require(v12_validation.get("V05_status_preserved", {}).get("candidate_status") == "CHECK_REQUIRED", "V05_STATUS_WAS_NOT_PRESERVED")
    _require(v12_validation.get("V05_status_preserved", {}).get("mutated") is False, "V05_STATUS_MUTATION_RECORDED")
    _require(v12_validation.get("V08_historical_provenance", {}).get("producer_execution_provenance") == "UNVERIFIED", "V08_PROVENANCE_WAS_PROMOTED")
    _require(v12_validation.get("V08_historical_provenance", {}).get("v08_event_rows_used_for_v12_derivation") is False, "V08_EVENT_ROWS_USED")
    _require(v12_validation.get("reused_V09_evidence", {}).get("formal_publication_approval") is False, "V09_APPROVAL_TREATED_AS_FORMAL")

    binding = v12_validation.get("candidate_binding", {})
    verify_candidate_binding(binding)
    _require(v05_manifest.get("status") == "CHECK_REQUIRED", "V05_CHECK_REQUIRED_STATUS_CHANGED")
    _require(v05_manifest.get("completion_token") == "A_FAST_CORE_V2_ALIGNMENT_500B_WEB_CANONICAL_FULL_HISTORY_REBUILD_V01_CHECK_REQUIRED", "V05_COMPLETION_TOKEN_CHANGED")
    _require(v05_manifest.get("requested_as_of") == EXPECTED["requested_as_of"], "V05_REQUESTED_AS_OF_MISMATCH")
    _require(v05_manifest.get("reference_market_date") == EXPECTED["reference_market_date"], "V05_REFERENCE_DATE_MISMATCH")
    _require(v05_manifest.get("strategy_replay_digest") == EXPECTED["candidate_digest"], "V05_CANDIDATE_DIGEST_MISMATCH")
    _require(v05_manifest.get("source_report_count") == EXPECTED["common_count"], "V05_COMMON_SCOPE_COUNT_MISMATCH")
    _require(v05_manifest.get("staging_output_only") is True, "V05_STAGE_NOT_OUTPUT_ONLY")
    _require(v05_manifest.get("operational_config_enabled") is False, "V05_OPERATIONAL_CONFIG_ENABLED")
    _require(v05_manifest.get("operational_config_active") is False, "V05_OPERATIONAL_CONFIG_ACTIVE")
    _require(v05_manifest.get("operational_effective_signal_date") == "PENDING_USER_APPROVAL", "V05_EFFECTIVE_SIGNAL_DATE_CHANGED")
    _require(v05_manifest.get("operational_activation_interval_count") == 0, "V05_ACTIVATION_INTERVAL_COUNT_CHANGED")
    _require(v05_source_manifest.get("stage", {}).get("status") == "CHECK_REQUIRED", "V05_SOURCE_STATUS_CHANGED")
    _require(v05_source_manifest.get("stage", {}).get("manifest_sha256") == EXPECTED_HASHES["v05_stage_manifest"], "V05_SOURCE_STAGE_MANIFEST_BINDING_MISMATCH")

    source_hash_check = _verify_v12_source_manifest(root, v12_validation, v12_source_manifest)
    v06_v07_outputs = _verify_v06_v07_output_manifests(root)

    v05_declared = v05_manifest.get("staging_file_sha256")
    _require(isinstance(v05_declared, dict) and len(v05_declared) == 4420, "V05_STAGE_FILE_MANIFEST_INVALID")
    v05_stage_check = verify_declared_stage_files(v05_stage, v05_declared, label="V05", omit_root_manifest=True)

    _require(v09_stage_manifest.get("target_as_of") == EXPECTED["requested_as_of"], "V09_STAGE_TARGET_DATE_MISMATCH")
    _require(v09_stage_manifest.get("reference_market_date") == EXPECTED["reference_market_date"], "V09_STAGE_REFERENCE_DATE_MISMATCH")
    _require(v09_stage_manifest.get("common_report_count") == EXPECTED["common_count"], "V09_STAGE_COMMON_COUNT_MISMATCH")
    _require(v09_stage_manifest.get("etf_report_count") == EXPECTED["etf_count"], "V09_STAGE_ETF_COUNT_MISMATCH")
    v09_declared = v09_stage_manifest.get("stage_file_sha256")
    _require(isinstance(v09_declared, dict) and len(v09_declared) == 1502, "V09_STAGE_FILE_MANIFEST_INVALID")
    b_select_status_sha256 = v09_declared.get("b-select-status.json")
    _require(
        isinstance(b_select_status_sha256, str) and len(b_select_status_sha256) == 64,
        "V09_B_SELECT_STATUS_HASH_MISSING",
    )
    v09_stage_check = verify_declared_stage_files(stage_root, v09_declared, label="V09 Phase4D stage")

    v05_stage_map = v05_declared
    v09_web_map = {key: value for key, value in v09_declared.items() if key.startswith("web/")}
    matched_v05_web = sorted(set(v09_web_map) & set(v05_stage_map))
    missing_v05_web = sorted(set(v09_web_map) - set(v05_stage_map))
    expected_phase4d_payloads = {
        "web/foreign-net-buy-ranking.json",
        "web/health.json",
        "web/market-ranking.json",
        "web/sector-rs-ranking.json",
    }
    _require(len(matched_v05_web) == 1497, "V05_V09_SHARED_WEB_FILE_COUNT_MISMATCH")
    _require(set(missing_v05_web) == expected_phase4d_payloads, "V05_V09_PHASE4D_PAYLOAD_SET_MISMATCH")
    _require(all(v05_stage_map[path] == v09_web_map[path] for path in matched_v05_web), "V05_V09_SHARED_WEB_FILE_HASH_MISMATCH")

    stage_data = stage_root / "web"
    index = _read_json(stage_data / "stock-index.json")
    common_rows = [
        item for item in index.get("items", [])
        if isinstance(item, dict) and item.get("report_available") is True and item.get("asset_type", "COMMON") == "COMMON"
    ]
    common_tickers = sorted(str(item.get("ticker") or "").zfill(6) for item in common_rows)
    common_set_hash = sha256_bytes(json.dumps(common_tickers, separators=(",", ":")).encode("utf-8"))
    _require(len(common_rows) == EXPECTED["common_count"], "CANDIDATE_COMMON_REPORT_COUNT_MISMATCH")
    _require(len(set(common_tickers)) == EXPECTED["common_count"], "CANDIDATE_COMMON_TICKER_DUPLICATE")
    _require(common_set_hash == binding.get("common_ticker_set_sha256"), "CANDIDATE_COMMON_TICKER_SET_HASH_MISMATCH")
    common_identity_by_ticker = {
        str(item.get("ticker") or "").zfill(6): str(item.get("isu_cd") or "").upper()
        for item in common_rows
    }
    _require(len(common_identity_by_ticker) == EXPECTED["common_count"], "CANDIDATE_COMMON_IDENTITY_COUNT_MISMATCH")

    v06_rows = _read_csv(v06_run / "baseline_blocker_classification.csv")
    v07_rows = _read_csv(v07_run / "baseline_disposition.csv")
    independent = v12_validation.get("independent_event_reconciliation", {})
    v12_events = independent.get("event_keys")
    _require(isinstance(v12_events, list), "V12_EVENT_ROWS_MISSING")
    blocker_result = reconcile_blocker_events(v06_rows, v07_rows, v12_events, common_identity_by_ticker)
    for key, expected in (
        ("event_count", EXPECTED["blocker_event_count"]),
        ("V07_event_count", EXPECTED["blocker_event_count"]),
        ("V09_comparison_target_count", EXPECTED["blocker_event_count"]),
        ("unique_ticker_count", EXPECTED["blocker_identity_count"]),
        ("unique_ticker_isu_identity_count", EXPECTED["blocker_identity_count"]),
        ("duplicate_V06", 0), ("duplicate_V07", 0), ("missing_V07", 0), ("extra_V07", 0),
        ("common_field_mismatches_V06_V07", 0), ("allowed_true_count", 0),
        ("entry_created_true_count", 0), ("candidate_scope_ticker_missing_count", 0),
        ("candidate_ISU_mismatch_count", 0), ("independent_source_V08_path_count", 0),
    ):
        _require(independent.get(key) == expected, f"V12_EVENT_SUMMARY_MISMATCH:{key}")
    _require(independent.get("counts_by_blocker_code") == EXPECTED_BLOCKER_COUNTS, "V12_BLOCKER_CODE_SUMMARY_MISMATCH")
    evidence_hash_mismatches = []
    for relative, expected_hash in blocker_result["source_evidence_sha256"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected_hash:
            evidence_hash_mismatches.append(relative)
    _require(not evidence_hash_mismatches, "BLOCKER_SOURCE_EVIDENCE_HASH_MISMATCH")
    blocker_result["source_evidence_hash_mismatch_count"] = 0
    blocker_result.pop("source_evidence_sha256", None)

    replay_checks = _verify_saved_replay_outputs(root, v12_validation, v05_manifest)
    protected_checks = _verify_current_protected_trees(root, v12_validation)

    monitor = _read_json(stage_data / "strategy-monitor.json")
    _require(monitor.get("requested_as_of") == EXPECTED["requested_as_of"], "CANDIDATE_MONITOR_TARGET_DATE_MISMATCH")
    _require(monitor.get("reference_market_date") == EXPECTED["reference_market_date"], "CANDIDATE_MONITOR_REFERENCE_DATE_MISMATCH")
    _require(monitor.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB", "CANDIDATE_MONITOR_REPLAY_MODE_MISMATCH")
    _require(monitor.get("strategy_replay_digest") == EXPECTED["candidate_digest"], "CANDIDATE_MONITOR_DIGEST_MISMATCH")
    _require(monitor.get("default_strategy_id") == "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B", "CANDIDATE_DEFAULT_STRATEGY_MISMATCH")
    fast_row = next(
        (
            row for row in monitor.get("strategies", [])
            if isinstance(row, dict) and row.get("id") == "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
        ),
        None,
    )
    _require(isinstance(fast_row, dict), "CANDIDATE_ALIGNMENT_STRATEGY_ROW_MISSING")
    scope = monitor.get("strategy_replay_scope", {})
    _require(scope.get("report_count") == EXPECTED["common_count"], "CANDIDATE_MONITOR_SCOPE_COUNT_MISMATCH")
    _require(scope.get("base_candidate_signal_count") == EXPECTED["gate_count"], "CANDIDATE_MONITOR_GATE_COUNT_MISMATCH")
    _require(scope.get("alignment_gate_pass_count") == EXPECTED["trade_count"], "CANDIDATE_MONITOR_TRADE_COUNT_MISMATCH")
    _require((fast_row.get("counts") or {}).get("entry") == 0, "CANDIDATE_CURRENT_ENTRY_COUNT_NONZERO")

    v09_validation = _read_json(v09_run / "phase4d_preflight_validation.json")
    _require(v09_validation.get("status") == "PASS", "V09_SAVED_PREFLIGHT_STATUS_INVALID")
    _require(v09_validation.get("promotion_called") is False, "V09_PROMOTION_WAS_CALLED")
    _require(v09_validation.get("execute_live") is False, "V09_EXECUTE_LIVE_TRUE")
    _require(v09_validation.get("canonical_web_data_writes") == 0, "V09_CANONICAL_WEB_DATA_WRITE_RECORDED")
    _require(v09_validation.get("b_select_status_writes") == 0, "V09_B_SELECT_STATUS_WRITE_RECORDED")

    current_monitor = _read_json(root / "web/data/strategy-monitor.json")
    current_digest = str(current_monitor.get("strategy_replay_digest") or "")
    _require(current_digest == EXPECTED["current_public_digest"], "CURRENT_PUBLIC_DIGEST_CHANGED")
    noop = candidate_noop_decision(EXPECTED["candidate_digest"], current_digest, published_payload_valid=False)
    _require(noop == "VALIDATE_NEW_CANDIDATE", "NEW_CANDIDATE_WAS_MISCLASSIFIED_AS_NOOP")

    return {
        "status": "PASS",
        "candidate_binding": {
            "requested_as_of": EXPECTED["requested_as_of"],
            "reference_market_date": EXPECTED["reference_market_date"],
            "candidate_digest": EXPECTED["candidate_digest"],
            "current_public_digest": current_digest,
            "current_digest_is_new_candidate": False,
            "no_op_decision": noop,
            "common_count": len(common_rows),
            "common_ticker_set_sha256": common_set_hash,
        },
        "pinned_evidence_sha256": pinned_checks,
        "source_manifest_validation": source_hash_check,
        "V06_V07_output_hashes": v06_v07_outputs,
        "V05_stage_integrity": v05_stage_check,
        "V09_phase4d_stage_integrity": v09_stage_check,
        "V05_to_V09_candidate_connection": {
            "shared_web_file_count": len(matched_v05_web),
            "shared_web_file_mismatch_count": 0,
            "Phase4D_exporter_payload_file_count": len(missing_v05_web),
            "Phase4D_exporter_payloads": sorted(missing_v05_web),
        },
        "independent_blocker_reconciliation": blocker_result,
        "saved_replay_and_trade_gate_checks": replay_checks,
        "protected_tree_checks": protected_checks,
        "V05_status": "CHECK_REQUIRED_PRESERVED",
        "V08_execution_provenance": "UNVERIFIED_PRESERVED",
        "V09_allowlist_used_as_approval": False,
        "formal_publication_approval": False,
        "stage_fingerprint_sha256": v09_stage_check["fingerprint_sha256"],
        "b_select_status_sha256": b_select_status_sha256,
    }


def preflight_alignment_candidate(root: Path | None = None) -> dict[str, Any]:
    """Run the normal Phase4D validators against the pinned stage without publishing."""
    root = Path(root or Path(__file__).resolve().parents[3]).resolve()
    from scripts import run_daily_update_phase4d_v01 as phase4d

    stage_root = root / V09_STAGE_REL
    stage_data = stage_root / "web"
    status_path = stage_root / "b-select-status.json"
    web_data = root / "web/data"

    initial_public_tree = phase4d._tree_manifest(web_data)
    current_monitor = _read_json(web_data / "strategy-monitor.json")
    current_digest = str(current_monitor.get("strategy_replay_digest") or "")
    if current_digest == EXPECTED["candidate_digest"]:
        published = phase4d.inspect_published_payload(
            root,
            EXPECTED["requested_as_of"],
            require_etf_source=True,
        )
        noop = candidate_noop_decision(
            EXPECTED["candidate_digest"],
            current_digest,
            published_payload_valid=published is not None,
        )
        if noop == "NOOP_ALREADY_COMPLETE":
            return {
                "status": "NOOP_ALREADY_COMPLETE",
                "candidate_digest": EXPECTED["candidate_digest"],
                "promotion_called": False,
                "web_data_writes": 0,
            }

    before = validate_alignment_candidate_evidence(root, stage_root)

    staging_validation = phase4d.validate_staging(
        stage_data,
        EXPECTED["requested_as_of"],
        EXPECTED["reference_market_date"],
        require_etf36=True,
        b_select_status_path=status_path,
    )
    snapshot_validation = phase4d._inspect_final_promotion_snapshot(stage_data, web_data)
    after = validate_alignment_candidate_evidence(root, stage_root)
    _require(before["stage_fingerprint_sha256"] == after["stage_fingerprint_sha256"], "FINAL_STAGE_FINGERPRINT_CHANGED")
    _require(initial_public_tree == phase4d._tree_manifest(web_data), "PREFLIGHT_CHANGED_CANONICAL_WEB_DATA")

    return {
        "status": "V13_LOCAL_DRYRUN_READY_FOR_EXPLICIT_PUBLISH_APPROVAL_REVIEW",
        "candidate_digest": EXPECTED["candidate_digest"],
        "requested_as_of": EXPECTED["requested_as_of"],
        "reference_market_date": EXPECTED["reference_market_date"],
        "eligibility_before_and_after_final_hash": "PASS",
        "stage_fingerprint_sha256": after["stage_fingerprint_sha256"],
        "phase4d_validate_staging": staging_validation,
        "phase4d_final_snapshot": snapshot_validation,
        "candidate_eligibility": after,
        "promotion_called": False,
        "canonical_web_data_writes": 0,
        "b_select_status_writes": 0,
        "commit_or_push": False,
        "pages_deployment": False,
    }
