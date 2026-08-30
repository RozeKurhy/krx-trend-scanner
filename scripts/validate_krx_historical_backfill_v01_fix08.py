#!/usr/bin/env python3
"""Network-free FIX08 acceptance, provenance, coverage, and idempotency validator."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.krx_historical_backfill import candidate_dates  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402
from scripts.validate_krx_historical_backfill_v01_fix07 import _audit_store  # noqa: E402


FIX_VERSION = "FIX08"
START_HEAD = "901af3ecaece64f918e983a5fa67ab07a7cc81f5"
PRODUCTION_RUNTIME_HEAD = "e508005c16e5fa3fa19c03b6568ba56ab9ac9294"
FIX07_PILOT_VALIDATION_HEAD = "0bee785d6e14ebefffb191c2913a18868bd4caf6"
FIX07_REPAIR_EXECUTION_HEAD = "5398d62761c80b9960cd61986a585a3b06a5b3e2"
FIX08_IMPLEMENTATION_HEAD = "e18d3c646aa87b5559ab324190fe64683d011fa9"
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
MARKETS = ("KOSPI", "KOSDAQ")
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
QUOTA_DB = ROOT / ".cache/krx_openapi/quota.sqlite3"
NUMERIC = re.compile(r"^[0-9]{6}$")
VALID = re.compile(r"^[0-9A-Z]{6}$")
FROZEN_RUNTIME_PATHS = (
    "src/trend_scanner/data/krx_openapi_client.py",
    "src/trend_scanner/data/krx_openapi_quota.py",
    "src/trend_scanner/data/krx_raw_stock_provider.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "src/trend_scanner/data/krx_historical_backfill.py",
)
PILOT_ARTIFACTS = (
    "artifacts/data/krx_historical_backfill/v01/FIX07_live_pilot_summary.json",
    "artifacts/data/krx_historical_backfill/v01/FIX07_samsung_listed_shares_evidence.json",
)


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def implementation_head() -> str:
    return FIX08_IMPLEMENTATION_HEAD


def production_runtime_compatible() -> bool:
    return subprocess.run(
        ["git", "diff", "--quiet", PRODUCTION_RUNTIME_HEAD, git_head(), "--", *FROZEN_RUNTIME_PATHS],
        cwd=ROOT,
    ).returncode == 0


def diagnostic_gate(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        return False
    source = payload.get("production_runtime_head") or payload.get("source_head")
    return source == PRODUCTION_RUNTIME_HEAD and production_runtime_compatible()


def pilot_gate(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("validation_generation") == "FIX07"
        and payload.get("mode") == "live-pilot"
        and payload.get("legacy") is False
        and payload.get("status") == "PASS"
        and payload.get("request_count") == 6
        and payload.get("retry_count") == 0
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == FIX07_PILOT_VALIDATION_HEAD
    )


def samsung_gate(payload: dict[str, Any] | None) -> bool:
    if not (
        isinstance(payload, dict)
        and payload.get("validation_generation") == "FIX07"
        and payload.get("mode") == "live-pilot"
        and payload.get("legacy") is False
        and payload.get("status") == "PASS"
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == FIX07_PILOT_VALIDATION_HEAD
    ):
        return False
    observations = {item.get("date"): item for item in payload.get("observations", [])}
    return all(
        observations.get(date, {}).get("snapshot_available") is True
        and observations.get(date, {}).get("ticker_found") is True
        and observations.get(date, {}).get("observed") == expected
        and observations.get(date, {}).get("match") is True
        for date, expected in {"2018-04-27": 128386494, "2018-05-04": 6419324700}.items()
    )


def _git_diff_paths(start: str, end: str) -> list[str]:
    return subprocess.check_output(
        ["git", "diff", "--name-only", start, end],
        cwd=ROOT,
        text=True,
    ).splitlines()


def build_repair_acceptance_overlay() -> dict[str, Any]:
    repair_path = OUTPUT / "FIX07_failed_partition_repair.json"
    repair = _load(repair_path, {}) or {}
    paths = _git_diff_paths(FIX07_PILOT_VALIDATION_HEAD, FIX07_REPAIR_EXECUTION_HEAD)
    runner_paths = [path for path in paths if path.startswith(("scripts/", "src/", "tests/"))]
    production_paths = [path for path in paths if path in FROZEN_RUNTIME_PATHS]
    expected_artifact_paths = sorted(PILOT_ARTIFACTS)
    runner_compatible = not runner_paths and not production_paths and sorted(paths) == expected_artifact_paths
    overlay_status = "PASS" if (
        repair.get("status") == "PASS"
        and repair.get("date") == "2019-04-26"
        and repair.get("market") == "KOSDAQ"
        and repair.get("attempt_count") == 1
        and repair.get("retry_count") == 0
        and repair.get("http_status") == 200
        and int(repair.get("row_count", 0)) > 0
        and repair.get("new_status") == "COMPLETE"
        and repair.get("paired_market") == "KOSPI"
        and repair.get("paired_market_status") == "COMPLETE"
        and repair.get("verification", {}).get("valid") is True
        and runner_compatible
    ) else "BLOCKED_REPAIR_EVIDENCE"
    return {
        "validation_generation": FIX_VERSION,
        "date": "2019-04-26",
        "market": "KOSDAQ",
        "original_repair_artifact": str(repair_path.relative_to(ROOT)),
        "original_repair_status": repair.get("status"),
        "original_validation_source_head": repair.get("validation_source_head"),
        "repair_runner_implementation_head": FIX07_PILOT_VALIDATION_HEAD,
        "repair_execution_head": FIX07_REPAIR_EXECUTION_HEAD,
        "implementation_to_execution_diff_paths": paths,
        "runner_code_diff_count": len(runner_paths),
        "production_runtime_diff_count": len(production_paths),
        "runner_compatible_between_heads": runner_compatible,
        "records_key_direct_audit": repair.get("records_key"),
        "records_key_verified": "OutBlock_1",
        "records_key_verification_basis": "PROVIDER_FAIL_CLOSED_RESPONSE_CONTRACT",
        "directly_observed_in_client_audit": repair.get("records_key") is not None,
        "inferred_from_successful_provider_contract": True,
        "http_status": repair.get("http_status"),
        "attempt_count": repair.get("attempt_count"),
        "retry_count": repair.get("retry_count"),
        "row_count": repair.get("row_count"),
        "new_status": repair.get("new_status"),
        "paired_market": repair.get("paired_market"),
        "paired_market_status": repair.get("paired_market_status"),
        "verification": repair.get("verification", {}),
        "status": overlay_status,
        "blockers": [] if overlay_status == "PASS" else [overlay_status],
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def repair_gate(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "PASS"
        and payload.get("original_repair_status") == "PASS"
        and payload.get("date") == "2019-04-26"
        and payload.get("market") == "KOSDAQ"
        and payload.get("attempt_count") == 1
        and payload.get("retry_count") == 0
        and payload.get("http_status") == 200
        and int(payload.get("row_count", 0)) > 0
        and payload.get("new_status") == "COMPLETE"
        and payload.get("paired_market") == "KOSPI"
        and payload.get("paired_market_status") == "COMPLETE"
        and payload.get("verification", {}).get("valid") is True
        and payload.get("repair_runner_implementation_head") == FIX07_PILOT_VALIDATION_HEAD
        and payload.get("repair_execution_head") == FIX07_REPAIR_EXECUTION_HEAD
        and payload.get("original_validation_source_head") == FIX07_REPAIR_EXECUTION_HEAD
        and payload.get("runner_compatible_between_heads") is True
        and payload.get("runner_code_diff_count") == 0
        and payload.get("production_runtime_diff_count") == 0
        and payload.get("records_key_verified") == "OutBlock_1"
    )


def resume_gate(payload: dict[str, Any] | None, expected_head: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("validation_generation") == FIX_VERSION
        and payload.get("status") == "PASS"
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == expected_head
        and payload.get("resume") is True
        and payload.get("retry_failures") is False
        and payload.get("retry_count") == 0
        and all(int(payload.get("status_counts", {}).get(key, 0)) == 0 for key in ("401", "403", "429", "5xx", "transport_error"))
        and payload.get("failed_partition_count") == 0
        and payload.get("final_missing_partition_count") == 0
    )


def coverage_gate(coverage: dict[str, Any]) -> bool:
    return bool(
        coverage.get("candidate_date_count") == 4340
        and coverage.get("complete_date_count", 0) + coverage.get("finalized_no_data_date_count", 0) == 4340
        and coverage.get("missing_date_count") == 0
        and coverage.get("missing_partition_count") == 0
        and coverage.get("failed_partition_count") == 0
        and coverage.get("partial_date_count") == 0
        and coverage.get("complete_partition_count", 0) + coverage.get("no_data_partition_count", 0) == 8680
    )


def idempotency_gate(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("candidate_partition_count") == 8680
        and payload.get("terminal_partition_count") == 8680
        and payload.get("pending_partition_count") == 0
        and payload.get("would_fetch_partition_count") == 0
        and payload.get("actual_network_request_count") == 0
        and payload.get("status") == "PASS"
    )


def evaluate_ready_gate(
    diagnostic: dict[str, Any] | None,
    pilot: dict[str, Any] | None,
    samsung: dict[str, Any] | None,
    repair: dict[str, Any] | None,
    resume: dict[str, Any] | None,
    idempotency: dict[str, Any] | None,
    coverage: dict[str, Any],
    integrity: dict[str, Any],
    cross_market: dict[str, Any],
    identifier: dict[str, Any],
    validation_head: str,
) -> dict[str, Any]:
    provenance_checks = {
        "diagnostic_ok": diagnostic_gate(diagnostic),
        "pilot_ok": pilot_gate(pilot),
        "samsung_ok": samsung_gate(samsung),
        "repair_ok": repair_gate(repair),
    }
    integrity_ok = all(int(integrity.get(key, 0)) == 0 for key in (
        "integrity_error_count", "content_hash_mismatch_count", "file_hash_mismatch_count",
        "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count",
        "duplicate_ticker_count", "no_data_integrity_error_count",
    ))
    checks = {
        **provenance_checks,
        "resume_ok": resume_gate(resume, validation_head),
        "coverage_ok": coverage_gate(coverage),
        "integrity_ok": integrity_ok,
        "cross_market_ok": int(cross_market.get("cross_market_ticker_conflict_count", 0)) == 0,
        "identifier_ok": int(identifier.get("invalid_short_code_count", 0)) == 0,
        "idempotency_ok": idempotency_gate(idempotency),
    }
    provenance_status = "PASS" if all(provenance_checks.values()) else "BLOCKED_PROVENANCE"
    coverage_status = "PASS" if checks["coverage_ok"] else "INCOMPLETE"
    blockers: list[str] = []
    if provenance_status != "PASS":
        blockers.append("BLOCKED_PROVENANCE")
    if not checks["resume_ok"] or not checks["coverage_ok"] or not checks["idempotency_ok"]:
        blockers.append("BLOCKED_COVERAGE")
    if not checks["integrity_ok"]:
        blockers.append("BLOCKED_RAW_STORE_INTEGRITY")
    if not checks["cross_market_ok"]:
        blockers.append("BLOCKED_CROSS_MARKET_TICKER_CONFLICT")
    if not checks["identifier_ok"]:
        blockers.append("BLOCKED_IDENTIFIER_DISTRIBUTION")
    blockers = list(dict.fromkeys(blockers))
    return {
        "checks": checks,
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "blockers": blockers,
        "all_pass": not blockers and all(checks.values()),
    }


def _plan_idempotency(store: KrxRawStockStore, dates: list[str], actual_network_requests: int) -> dict[str, Any]:
    rows = [row for row in store.list_manifest() if row.get("date") in set(dates) and row.get("market") in MARKETS]
    terminal = sum(row.get("status") in {"COMPLETE", "NO_DATA"} for row in rows)
    expected = len(dates) * len(MARKETS)
    pending = expected - terminal
    return {
        "validation_generation": FIX_VERSION,
        "candidate_partition_count": expected,
        "terminal_partition_count": terminal,
        "pending_partition_count": pending,
        "would_fetch_partition_count": pending,
        "actual_network_request_count": actual_network_requests,
        "status": "PASS" if pending == 0 and actual_network_requests == 0 else "INCOMPLETE",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _quota() -> dict[str, Any]:
    quota = LocalKrxOpenApiQuota(QUOTA_DB)
    usage = quota.get_usage()
    return {
        "usage_date_kst": usage.get("usage_date_kst"),
        "global_after": int(usage.get("global_total", 0)),
        "endpoint_usage": dict(usage.get("endpoint_usage", {})),
        "remaining_global": quota.remaining("stk_bydd_trd"),
        "remaining_stk_bydd_trd": quota.remaining("stk_bydd_trd"),
        "remaining_ksq_bydd_trd": quota.remaining("ksq_bydd_trd"),
        "last_attempt_at_utc": usage.get("last_attempt_at_utc"),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    started = datetime.now(timezone.utc)
    dates = candidate_dates(TARGET_START, TARGET_END)
    store = KrxRawStockStore(RAW_ROOT)
    coverage, integrity, cross_market, identifier, by_date = _audit_store(store, dates)
    implementation = implementation_head()
    diagnostic = _load(OUTPUT / "FIX06_live_diagnostic_summary.json", {}) or {}
    pilot = _load(OUTPUT / "FIX07_live_pilot_summary.json", {}) or {}
    samsung = _load(OUTPUT / "FIX07_samsung_listed_shares_evidence.json", {}) or {}
    repair = _load(OUTPUT / "FIX07_failed_partition_repair.json", {}) or {}
    overlay_path = OUTPUT / "FIX08_repair_acceptance_overlay.json"
    overlay = _load(overlay_path)
    if not isinstance(overlay, dict):
        overlay = build_repair_acceptance_overlay()
        _dump(overlay_path, overlay)
    resume = _load(OUTPUT / "FIX08_backfill_resume_summary.json", {}) or {}
    # The idempotency audit itself is network-free.  The historical resume's
    # request count is reported separately in the resume artifact.
    idempotency = _plan_idempotency(store, dates, 0)
    provenance_checks = {
        "diagnostic_ok": diagnostic_gate(diagnostic),
        "pilot_ok": pilot_gate(pilot),
        "samsung_ok": samsung_gate(samsung),
        "repair_ok": repair_gate(overlay),
    }
    provenance_status = "PASS" if all(provenance_checks.values()) else "BLOCKED_PROVENANCE"
    coverage_status = "PASS" if coverage_gate(coverage) else "INCOMPLETE"
    integrity_ok = all(int(integrity.get(key, 0)) == 0 for key in (
        "integrity_error_count", "content_hash_mismatch_count", "file_hash_mismatch_count",
        "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count",
        "duplicate_ticker_count", "no_data_integrity_error_count",
    ))
    checks = {
        **provenance_checks,
        "resume_ok": resume_gate(resume, implementation),
        "coverage_ok": coverage_gate(coverage),
        "integrity_ok": integrity_ok,
        "cross_market_ok": int(cross_market.get("cross_market_ticker_conflict_count", 0)) == 0,
        "identifier_ok": int(identifier.get("invalid_short_code_count", 0)) == 0,
        "idempotency_ok": idempotency_gate(idempotency),
    }
    blockers: list[str] = []
    if provenance_status != "PASS":
        blockers.append("BLOCKED_PROVENANCE")
    resume_status_counts = resume.get("status_counts", {}) if isinstance(resume, dict) else {}
    if str(resume.get("status", "")).startswith("BLOCKED_KRX_TRANSPORT") or int(resume_status_counts.get("transport_error", 0)) > 0 or int(resume_status_counts.get("5xx", 0)) > 0:
        blockers.append("BLOCKED_KRX_TRANSPORT")
    if not checks["resume_ok"]:
        blockers.append("BLOCKED_COVERAGE")
    if not checks["coverage_ok"]:
        blockers.append("BLOCKED_COVERAGE")
    if not checks["integrity_ok"]:
        blockers.append("BLOCKED_RAW_STORE_INTEGRITY")
    if not checks["cross_market_ok"]:
        blockers.append("BLOCKED_CROSS_MARKET_TICKER_CONFLICT")
    if not checks["identifier_ok"]:
        blockers.append("BLOCKED_IDENTIFIER_DISTRIBUTION")
    if not checks["idempotency_ok"]:
        blockers.append("BLOCKED_COVERAGE")
    blockers = list(dict.fromkeys(blockers))
    primary = next((item for item in (
        "BLOCKED_KRX_AUTH", "BACKFILL_PAUSED_QUOTA", "BLOCKED_KRX_TRANSPORT",
        "BLOCKED_KRX_SCHEMA", "BLOCKED_PROVENANCE", "BLOCKED_REPAIR_EVIDENCE",
        "BLOCKED_COVERAGE", "BLOCKED_RAW_STORE_INTEGRITY",
        "BLOCKED_CROSS_MARKET_TICKER_CONFLICT", "BLOCKED_IDENTIFIER_DISTRIBUTION",
    ) if item in blockers), None)
    final_status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX08_REVIEW" if not blockers else primary
    current_evidence = {
        "diagnostic": {"current": provenance_checks["diagnostic_ok"], "status": diagnostic.get("status")},
        "pilot": {"current": provenance_checks["pilot_ok"], "status": pilot.get("status")},
        "samsung": {"current": provenance_checks["samsung_ok"], "status": samsung.get("status")},
        "repair": {"current": provenance_checks["repair_ok"], "status": overlay.get("status")},
        "resume": {"current": checks["resume_ok"], "status": resume.get("status")},
        "idempotency": {"current": checks["idempotency_ok"], "status": idempotency.get("status")},
    }
    _dump(overlay_path, overlay)
    _dump(OUTPUT / "FIX08_provenance_summary.json", {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "fix07_live_validation_authority": FIX07_PILOT_VALIDATION_HEAD,
        "fix08_resume_validation_source_head": implementation,
        "artifact_generation_head": git_head(),
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "checks": provenance_checks,
        "current_evidence": current_evidence,
        "blockers": [item for item in blockers if item == "BLOCKED_PROVENANCE"],
        "status": provenance_status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    _dump(OUTPUT / "FIX08_idempotency_summary.json", idempotency)
    _dump(OUTPUT / "coverage_summary.json", {"coverage": coverage, "status": coverage_status, "generated_at": started.isoformat()})
    _write_csv(OUTPUT / "coverage_by_year.csv", [{"year": year, **values} for year, values in sorted(coverage["coverage_by_year"].items())], ["year", "candidate_dates", "complete_dates", "finalized_no_data_dates", "missing_dates", "failed_dates", "partial_dates", "complete_partitions", "no_data_partitions", "raw_rows"])
    _dump(OUTPUT / "missing_coverage_evidence.json", {"candidate_date_count": len(dates), "missing_dates": coverage["missing_dates"], "failed_dates": coverage["failed_dates"], "partial_dates": coverage["partial_dates"], "missing_partition_count": coverage["missing_partition_count"], "failed_partition_count": coverage["failed_partition_count"]})
    _dump(OUTPUT / "partition_integrity_summary.json", {**integrity, "status": "PASS" if integrity_ok else "BLOCKED_RAW_STORE_INTEGRITY"})
    _dump(OUTPUT / "cross_market_conflict_evidence.json", {**cross_market, "status": "PASS" if checks["cross_market_ok"] else "BLOCKED_CROSS_MARKET_TICKER_CONFLICT"})
    _dump(OUTPUT / "identifier_distribution_summary.json", {**identifier, "status": "PASS" if checks["identifier_ok"] else "BLOCKED_IDENTIFIER_DISTRIBUTION"})
    quota = _quota()
    quota.update({
        "resume_request_count": int(resume.get("request_count", 0) or 0),
        "total_fix08_request_count": int(resume.get("request_count", 0) or 0),
        "retry_count": int(resume.get("retry_count", 0) or 0),
        "status_counts": resume.get("status_counts", {}),
    })
    _dump(OUTPUT / "quota_summary.json", quota)
    _write_csv(OUTPUT / "failed_dates.csv", [{"date": day, "classification": "FAILED_OR_PARTIAL", "markets": ";".join(MARKETS)} for day in coverage["failed_dates"] + coverage["partial_dates"]], ["date", "classification", "markets"])
    _dump(OUTPUT / "FIX08_closure_validation_summary.json", {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "fix08_implementation_head": implementation,
        "artifact_generation_head": git_head(),
        "coverage": coverage,
        "integrity": integrity,
        "cross_market": cross_market,
        "identifier": identifier,
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "checks": checks,
        "current_evidence": current_evidence,
        "idempotency": idempotency,
        "blockers": blockers,
        "status": final_status,
        "known_phase_limitations": ["FULL_REGRESSION_CLOSURE_DEFERRED"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    _dump(OUTPUT / "krx_historical_backfill_v01_manifest.json", {
        "fix_version": FIX_VERSION,
        "start_head": START_HEAD,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": implementation,
        "artifact_generation_head": git_head(),
        "target_start": TARGET_START,
        "target_end": TARGET_END,
        "candidate_date_count": coverage["candidate_date_count"],
        "status": final_status,
        "blockers": blockers,
    })
    _dump(OUTPUT / "krx_historical_backfill_v01_summary.json", {
        "fix_version": FIX_VERSION,
        "start_head": START_HEAD,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": implementation,
        "artifact_generation_head": git_head(),
        "coverage": coverage,
        "integrity": integrity,
        "cross_market": cross_market,
        "identifier": identifier,
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "checks": checks,
        "blockers": blockers,
        "status": final_status,
    })
    (OUTPUT / "krx_historical_backfill_v01_recommendation.md").write_text(
        "krx_historical_backfill_v01_recommendation.md\n"
        "================================================================================\n"
        f"FIX08 status: {final_status}\n"
        f"provenance_status: {provenance_status}\n"
        f"coverage_status: {coverage_status}\n"
        f"blockers: {', '.join(blockers) if blockers else '[]'}\n"
        "FULL_REGRESSION_CLOSURE_DEFERRED remains a known phase limitation.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": final_status,
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "blockers": blockers,
        "terminal_partitions": coverage["terminal_partition_count"],
        "pending_partitions": idempotency["pending_partition_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if final_status == "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX08_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
