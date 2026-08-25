#!/usr/bin/env python3
"""Network-free FIX09 repair, resume, coverage, and closure validator."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
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


FIX_VERSION = "FIX09"
START_HEAD = "aeedb48b778ee022cf0771cfdb3fcb2432130de7"
PRODUCTION_RUNTIME_HEAD = "e508005c16e5fa3fa19c03b6568ba56ab9ac9294"
FIX07_LIVE_VALIDATION_HEAD = "0bee785d6e14ebefffb191c2913a18868bd4caf6"
FIX07_REPAIR_EXECUTION_HEAD = "5398d62761c80b9960cd61986a585a3b06a5b3e2"
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
REPAIR_DATE = "2023-12-21"
MARKETS = ("KOSPI", "KOSDAQ")
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
QUOTA_DB = ROOT / ".cache/krx_openapi/quota.sqlite3"
EXECUTABLE_PATHS = (
    "scripts/run_krx_historical_backfill_v01_fix09.py",
    "scripts/validate_krx_historical_backfill_v01_fix09.py",
    "tests/test_krx_historical_backfill_v01_fix09.py",
)
FROZEN_RUNTIME_PATHS = (
    "src/trend_scanner/data/krx_openapi_client.py",
    "src/trend_scanner/data/krx_openapi_quota.py",
    "src/trend_scanner/data/krx_raw_stock_provider.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "src/trend_scanner/data/krx_historical_backfill.py",
    "src/trend_scanner/data/source_contracts.py",
)
NUMERIC = re.compile(r"^[0-9]{6}$")
VALID = re.compile(r"^[0-9A-Z]{6}$")


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
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", *EXECUTABLE_PATHS],
        cwd=ROOT,
        text=True,
    ).strip()


def executable_source_changed_after_implementation() -> bool:
    if not implementation_head():
        return True
    paths = subprocess.check_output(
        ["git", "diff", "--name-only", implementation_head(), git_head()],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return any(path in EXECUTABLE_PATHS or path.startswith("src/") for path in paths)


def production_runtime_compatible() -> bool:
    return subprocess.run(
        ["git", "diff", "--quiet", PRODUCTION_RUNTIME_HEAD, git_head(), "--", *FROZEN_RUNTIME_PATHS],
        cwd=ROOT,
    ).returncode == 0


def diagnostic_gate(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        return False
    authority = payload.get("production_runtime_head") or payload.get("source_head")
    return authority == PRODUCTION_RUNTIME_HEAD and production_runtime_compatible()


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
        and payload.get("validation_source_head") == FIX07_LIVE_VALIDATION_HEAD
    )


def samsung_gate(payload: dict[str, Any] | None) -> bool:
    if not (
        isinstance(payload, dict)
        and payload.get("validation_generation") == "FIX07"
        and payload.get("mode") == "live-pilot"
        and payload.get("legacy") is False
        and payload.get("status") == "PASS"
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == FIX07_LIVE_VALIDATION_HEAD
    ):
        return False
    observations = {item.get("date"): item for item in payload.get("observations", [])}
    return all(
        observations.get(date, {}).get("match") is True
        and observations.get(date, {}).get("observed") == expected
        for date, expected in {"2018-04-27": 128386494, "2018-05-04": 6419324700}.items()
    )


def repair_2019_gate(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "PASS"
        and payload.get("date") == "2019-04-26"
        and payload.get("market") == "KOSDAQ"
        and payload.get("records_key_verified") == "OutBlock_1"
        and payload.get("repair_runner_implementation_head") == FIX07_LIVE_VALIDATION_HEAD
        and payload.get("repair_execution_head") == FIX07_REPAIR_EXECUTION_HEAD
    )


def repair_2023_gate(payload: dict[str, Any] | None, expected_head: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("validation_generation") == FIX_VERSION
        and payload.get("status") == "PASS"
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == expected_head
        and payload.get("date") == REPAIR_DATE
        and payload.get("market") == "KOSPI"
        and payload.get("previous_status") == "FAILED"
        and payload.get("paired_market") == "KOSDAQ"
        and payload.get("paired_market_status") == "COMPLETE"
        and payload.get("attempt_count") == 1
        and payload.get("retry_count") == 0
        and payload.get("http_status") == 200
        and int(payload.get("row_count", 0)) > 0
        and payload.get("new_status") == "COMPLETE"
        and payload.get("verification", {}).get("valid") is True
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
        and payload.get("max_transient_retries") == 0
        and payload.get("retry_count") == 0
        and all(int(payload.get("status_counts", {}).get(key, 0)) == 0 for key in ("401", "403", "429", "5xx", "transport_error"))
        and payload.get("final_failed_partition_count") == 0
        and payload.get("final_missing_partition_count") == 0
        and payload.get("final_nonterminal_partition_count") == 0
    )


def coverage_gate(coverage: dict[str, Any]) -> bool:
    return bool(
        coverage.get("candidate_date_count") == 4340
        and coverage.get("complete_date_count", 0) + coverage.get("finalized_no_data_date_count", 0) == 4340
        and coverage.get("complete_partition_count", 0) + coverage.get("no_data_partition_count", 0) == 8680
        and coverage.get("missing_date_count") == 0
        and coverage.get("failed_date_count") == 0
        and coverage.get("partial_date_count") == 0
        and coverage.get("missing_partition_count") == 0
        and coverage.get("failed_partition_count") == 0
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


def partition_counts(rows: list[dict[str, Any]], candidate_date_count: int) -> dict[str, int]:
    complete = sum(row.get("status") == "COMPLETE" for row in rows)
    no_data = sum(row.get("status") == "NO_DATA" for row in rows)
    failed = sum(row.get("status") == "FAILED" for row in rows)
    missing = candidate_date_count * len(MARKETS) - complete - no_data - failed
    return {
        "complete": complete,
        "no_data": no_data,
        "missing": missing,
        "failed": failed,
        "nonterminal": missing + failed,
        "physical_terminal": complete + no_data,
    }


def plan_idempotency(store: KrxRawStockStore, dates: list[str], actual_network_requests: int = 0) -> dict[str, Any]:
    date_set = set(dates)
    rows = [row for row in store.list_manifest() if row.get("date") in date_set and row.get("market") in MARKETS]
    counts = partition_counts(rows, len(dates))
    return {
        "validation_generation": FIX_VERSION,
        "candidate_partition_count": len(dates) * len(MARKETS),
        "terminal_partition_count": counts["physical_terminal"],
        "pending_partition_count": counts["nonterminal"],
        "would_fetch_partition_count": counts["nonterminal"],
        "actual_network_request_count": actual_network_requests,
        "status": "PASS" if counts["nonterminal"] == 0 and actual_network_requests == 0 else "INCOMPLETE",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def dedupe_failed_dates(by_date: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day in sorted(by_date):
        states = by_date[day]
        statuses = {market: (states.get(market) or {}).get("status") for market in MARKETS}
        if any(status in {"FAILED", "COMPLETE"} for status in statuses.values()) and (
            any(status == "FAILED" for status in statuses.values())
            or sum(status == "COMPLETE" for status in statuses.values()) == 1
        ):
            rows.append({
                "date": day,
                "classification": "FAILED_OR_PARTIAL",
                "markets": ";".join(f"{market}:{statuses[market]}" for market in MARKETS),
            })
    return rows


def evaluate_ready_gate(
    diagnostic: dict[str, Any] | None,
    pilot: dict[str, Any] | None,
    samsung: dict[str, Any] | None,
    repair_2019: dict[str, Any] | None,
    repair_2023: dict[str, Any] | None,
    resume: dict[str, Any] | None,
    idempotency: dict[str, Any] | None,
    coverage: dict[str, Any],
    integrity: dict[str, Any],
    cross_market: dict[str, Any],
    identifier: dict[str, Any],
    validation_head: str,
) -> dict[str, Any]:
    checks = {
        "diagnostic_ok": diagnostic_gate(diagnostic),
        "pilot_ok": pilot_gate(pilot),
        "samsung_ok": samsung_gate(samsung),
        "repair_2019_ok": repair_2019_gate(repair_2019),
        "repair_2023_ok": repair_2023_gate(repair_2023, validation_head),
        "resume_ok": resume_gate(resume, validation_head),
        "coverage_ok": coverage_gate(coverage),
        "integrity_ok": all(int(integrity.get(key, 0)) == 0 for key in (
            "integrity_error_count", "content_hash_mismatch_count", "content_hash_mismatch_count",
            "file_hash_mismatch_count", "row_count_mismatch_count", "physical_schema_error_count",
            "source_date_mismatch_count", "duplicate_ticker_count", "no_data_integrity_error_count",
        )),
        "cross_market_ok": int(cross_market.get("cross_market_ticker_conflict_count", 0)) == 0,
        "identifier_ok": int(identifier.get("invalid_short_code_count", 0)) == 0,
        "idempotency_ok": idempotency_gate(idempotency),
        "production_runtime_compatible": production_runtime_compatible(),
        "executable_source_frozen": not executable_source_changed_after_implementation(),
    }
    provenance_checks = ("diagnostic_ok", "pilot_ok", "samsung_ok", "repair_2019_ok", "repair_2023_ok", "production_runtime_compatible", "executable_source_frozen")
    provenance_status = "PASS" if all(checks[key] for key in provenance_checks) else "BLOCKED_PROVENANCE"
    coverage_status = "PASS" if checks["coverage_ok"] else "INCOMPLETE"
    blockers: list[str] = []
    repair_status = str((repair_2023 or {}).get("status", ""))
    resume_status = str((resume or {}).get("status", ""))
    if repair_status.startswith("BLOCKED_KRX_TRANSPORT") or resume_status.startswith("BLOCKED_KRX_TRANSPORT"):
        blockers.append("BLOCKED_KRX_TRANSPORT")
    if not checks["production_runtime_compatible"] and "BLOCKED_PROVENANCE" not in blockers:
        blockers.append("BLOCKED_PROVENANCE")
    if provenance_status != "PASS":
        blockers.append("BLOCKED_PROVENANCE")
    if not checks["coverage_ok"] or not checks["resume_ok"] or not checks["idempotency_ok"]:
        blockers.append("BLOCKED_COVERAGE")
    if not checks["integrity_ok"]:
        blockers.append("BLOCKED_RAW_STORE_INTEGRITY")
    if not checks["cross_market_ok"]:
        blockers.append("BLOCKED_CROSS_MARKET_TICKER_CONFLICT")
    if not checks["identifier_ok"]:
        blockers.append("BLOCKED_IDENTIFIER_DISTRIBUTION")
    blockers = list(dict.fromkeys(blockers))
    priority = (
        "BLOCKED_KRX_AUTH", "BACKFILL_PAUSED_QUOTA", "BLOCKED_KRX_TRANSPORT",
        "BLOCKED_KRX_SCHEMA", "BLOCKED_PROVENANCE", "BLOCKED_COVERAGE",
        "BLOCKED_RAW_STORE_INTEGRITY", "BLOCKED_CROSS_MARKET_TICKER_CONFLICT",
        "BLOCKED_IDENTIFIER_DISTRIBUTION",
    )
    primary = next((item for item in priority if item in blockers), None)
    return {
        "checks": checks,
        "provenance_status": provenance_status,
        "coverage_status": coverage_status,
        "blockers": blockers,
        "all_pass": not blockers and all(checks.values()),
        "status": "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX09_REVIEW" if not blockers else primary,
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


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
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
    repair_2019 = _load(OUTPUT / "FIX08_repair_acceptance_overlay.json", {}) or {}
    fix08_provenance = _load(OUTPUT / "FIX08_provenance_summary.json", {}) or {}
    repair_2023 = _load(OUTPUT / "FIX09_failed_partition_repair.json", {}) or {}
    resume = _load(OUTPUT / "FIX09_backfill_resume_summary.json", {}) or {}
    idempotency = plan_idempotency(store, dates, 0)
    checks_result = evaluate_ready_gate(
        diagnostic, pilot, samsung, repair_2019, repair_2023, resume, idempotency,
        coverage, integrity, cross_market, identifier, implementation,
    )
    current_evidence = {
        "diagnostic": {"current": checks_result["checks"]["diagnostic_ok"], "status": diagnostic.get("status")},
        "pilot": {"current": checks_result["checks"]["pilot_ok"], "status": pilot.get("status")},
        "samsung": {"current": checks_result["checks"]["samsung_ok"], "status": samsung.get("status")},
        "repair_2019": {"current": checks_result["checks"]["repair_2019_ok"], "status": repair_2019.get("status")},
        "repair_2023": {"current": checks_result["checks"]["repair_2023_ok"], "status": repair_2023.get("status")},
        "resume": {"current": checks_result["checks"]["resume_ok"], "status": resume.get("status")},
        "idempotency": {"current": checks_result["checks"]["idempotency_ok"], "status": idempotency.get("status")},
    }
    physical_complete = sum(
        row.get("status") == "COMPLETE"
        for row in store.list_manifest()
        if row.get("date") in set(dates) and row.get("market") in MARKETS
    )
    _dump(OUTPUT / "FIX09_provenance_summary.json", {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "fix07_live_validation_authority": FIX07_LIVE_VALIDATION_HEAD,
        "fix09_implementation_head": implementation,
        "fix08_provenance_compatibility": fix08_provenance.get("status") == "PASS",
        "provenance_status": checks_result["provenance_status"],
        "coverage_status": checks_result["coverage_status"],
        "current_evidence": current_evidence,
        "checks": {key: checks_result["checks"][key] for key in ("diagnostic_ok", "pilot_ok", "samsung_ok", "repair_2019_ok", "repair_2023_ok", "production_runtime_compatible", "executable_source_frozen")},
        "blockers": [item for item in checks_result["blockers"] if item == "BLOCKED_PROVENANCE"],
        "status": checks_result["provenance_status"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    _dump(OUTPUT / "FIX09_idempotency_summary.json", idempotency)
    _dump(OUTPUT / "coverage_summary.json", {"coverage": coverage, "status": checks_result["coverage_status"], "generated_at": started.isoformat()})
    _write_csv(OUTPUT / "coverage_by_year.csv", [{"year": year, **values} for year, values in sorted(coverage["coverage_by_year"].items())], ["year", "candidate_dates", "complete_dates", "finalized_no_data_dates", "missing_dates", "failed_dates", "partial_dates", "complete_partitions", "no_data_partitions", "raw_rows"])
    _dump(OUTPUT / "missing_coverage_evidence.json", {"candidate_date_count": len(dates), "missing_dates": coverage["missing_dates"], "failed_dates": coverage["failed_dates"], "partial_dates": coverage["partial_dates"], "missing_partition_count": coverage["missing_partition_count"], "failed_partition_count": coverage["failed_partition_count"]})
    _dump(OUTPUT / "partition_integrity_summary.json", {**integrity, "status": "PASS" if checks_result["checks"]["integrity_ok"] else "BLOCKED_RAW_STORE_INTEGRITY"})
    _dump(OUTPUT / "cross_market_conflict_evidence.json", {**cross_market, "status": "PASS" if checks_result["checks"]["cross_market_ok"] else "BLOCKED_CROSS_MARKET_TICKER_CONFLICT"})
    _dump(OUTPUT / "identifier_distribution_summary.json", {**identifier, "status": "PASS" if checks_result["checks"]["identifier_ok"] else "BLOCKED_IDENTIFIER_DISTRIBUTION"})
    quota = _quota()
    quota.update({
        "repair_request_count": int(repair_2023.get("attempt_count", 0) or 0),
        "resume_request_count": int(resume.get("request_count", 0) or 0),
        "total_fix09_request_count": int(repair_2023.get("attempt_count", 0) or 0) + int(resume.get("request_count", 0) or 0),
        "retry_count": int(repair_2023.get("retry_count", 0) or 0) + int(resume.get("retry_count", 0) or 0),
        "status_counts": resume.get("status_counts", {}),
    })
    _dump(OUTPUT / "quota_summary.json", quota)
    _write_csv(OUTPUT / "failed_dates.csv", dedupe_failed_dates(by_date), ["date", "classification", "markets"])
    _dump(OUTPUT / "FIX09_closure_validation_summary.json", {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "fix09_implementation_head": implementation,
        "artifact_generation_head": git_head(),
        "physical_complete_partition_count": physical_complete,
        "coverage": coverage,
        "integrity": integrity,
        "cross_market": cross_market,
        "identifier": identifier,
        "provenance_status": checks_result["provenance_status"],
        "coverage_status": checks_result["coverage_status"],
        "checks": checks_result["checks"],
        "current_evidence": current_evidence,
        "idempotency": idempotency,
        "blockers": checks_result["blockers"],
        "status": checks_result["status"],
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
        "status": checks_result["status"],
        "blockers": checks_result["blockers"],
    })
    _dump(OUTPUT / "krx_historical_backfill_v01_summary.json", {
        "fix_version": FIX_VERSION,
        "start_head": START_HEAD,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": implementation,
        "artifact_generation_head": git_head(),
        "physical_complete_partition_count": physical_complete,
        "coverage": coverage,
        "integrity": integrity,
        "cross_market": cross_market,
        "identifier": identifier,
        "provenance_status": checks_result["provenance_status"],
        "coverage_status": checks_result["coverage_status"],
        "checks": checks_result["checks"],
        "blockers": checks_result["blockers"],
        "status": checks_result["status"],
    })
    (OUTPUT / "krx_historical_backfill_v01_recommendation.md").write_text(
        "krx_historical_backfill_v01_recommendation.md\n"
        "================================================================================\n"
        f"FIX09 status: {checks_result['status']}\n"
        f"provenance_status: {checks_result['provenance_status']}\n"
        f"coverage_status: {checks_result['coverage_status']}\n"
        f"blockers: {', '.join(checks_result['blockers']) if checks_result['blockers'] else '[]'}\n"
        "FULL_REGRESSION_CLOSURE_DEFERRED remains a known phase limitation.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": checks_result["status"],
        "provenance_status": checks_result["provenance_status"],
        "coverage_status": checks_result["coverage_status"],
        "blockers": checks_result["blockers"],
        "terminal_partitions": coverage["terminal_partition_count"],
        "pending_partitions": idempotency["pending_partition_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if checks_result["status"] == "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX09_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
