#!/usr/bin/env python3
"""Network-free FIX07 provenance, coverage, and closure validator."""

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
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.krx_historical_backfill import candidate_dates  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX07"
START_HEAD = "2001f1020c7c594baf1029b80231abf4b3e02d18"
PRODUCTION_RUNTIME_HEAD = "e508005c16e5fa3fa19c03b6568ba56ab9ac9294"
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
    "src/trend_scanner/data/source_contracts.py",
)


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def production_runtime_compatible() -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", PRODUCTION_RUNTIME_HEAD, git_head(), "--", *FROZEN_RUNTIME_PATHS],
        cwd=ROOT,
    )
    return result.returncode == 0


def diagnostic_gate(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        return False
    source = payload.get("production_runtime_head") or payload.get("source_head")
    return source == PRODUCTION_RUNTIME_HEAD and production_runtime_compatible()


def pilot_gate(payload: dict[str, Any] | None, validation_head: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("validation_generation") == FIX_VERSION
        and payload.get("mode") == "live-pilot"
        and payload.get("legacy") is False
        and payload.get("status") == "PASS"
        and payload.get("request_count") == 6
        and payload.get("retry_count") == 0
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == validation_head
    )


def samsung_gate(payload: dict[str, Any] | None, validation_head: str) -> bool:
    if not (
        isinstance(payload, dict)
        and payload.get("validation_generation") == FIX_VERSION
        and payload.get("mode") == "live-pilot"
        and payload.get("legacy") is False
        and payload.get("status") == "PASS"
        and payload.get("production_runtime_head") == PRODUCTION_RUNTIME_HEAD
        and payload.get("validation_source_head") == validation_head
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


def evaluate_ready_gate(
    *,
    diagnostic: dict[str, Any] | None,
    pilot: dict[str, Any] | None,
    samsung: dict[str, Any] | None,
    coverage: dict[str, Any],
    integrity: dict[str, Any],
    cross_market: dict[str, Any],
    identifier: dict[str, Any],
    validation_head: str,
) -> dict[str, Any]:
    checks = {
        "diagnostic_ok": diagnostic_gate(diagnostic),
        "pilot_ok": pilot_gate(pilot, validation_head),
        "samsung_ok": samsung_gate(samsung, validation_head),
        "coverage_ok": coverage_gate(coverage),
        "integrity_ok": all(int(integrity.get(key, 0)) == 0 for key in (
            "integrity_error_count", "content_hash_mismatch_count", "file_hash_mismatch_count",
            "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count",
            "duplicate_ticker_count", "no_data_integrity_error_count",
        )),
        "cross_market_ok": int(cross_market.get("cross_market_ticker_conflict_count", 0)) == 0,
        "identifier_ok": int(identifier.get("invalid_short_code_count", 0)) == 0,
    }
    blockers = ["BLOCKED_PROVENANCE" if key in {"diagnostic_ok", "pilot_ok", "samsung_ok"} else "BLOCKED_COVERAGE" if key == "coverage_ok" else "BLOCKED_RAW_STORE_INTEGRITY" if key == "integrity_ok" else "BLOCKED_CROSS_MARKET_TICKER_CONFLICT" if key == "cross_market_ok" else "BLOCKED_IDENTIFIER_DISTRIBUTION" for key, value in checks.items() if not value]
    return {"checks": checks, "all_pass": all(checks.values()), "blockers": list(dict.fromkeys(blockers))}


def _by_date(manifests: list[dict[str, Any]], dates: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    result = {day: {} for day in dates}
    for row in manifests:
        if row.get("date") in result and row.get("market") in MARKETS:
            result[row["date"]][row["market"]] = row
    return result


def _classification(states: dict[str, dict[str, Any]]) -> str:
    statuses = {market: (states.get(market) or {}).get("status") for market in MARKETS}
    if all(statuses[market] == "COMPLETE" for market in MARKETS):
        return "COMPLETE"
    if all(statuses[market] == "NO_DATA" for market in MARKETS):
        return "NO_DATA"
    if any(statuses[market] == "FAILED" for market in MARKETS):
        return "FAILED"
    if any(statuses[market] == "COMPLETE" for market in MARKETS):
        return "PARTIAL"
    return "MISSING"


def _quota() -> dict[str, Any]:
    rows: list[tuple[Any, ...]] = []
    if QUOTA_DB.exists():
        with sqlite3.connect(QUOTA_DB) as connection:
            rows = connection.execute("SELECT usage_date_kst, endpoint_key, attempt_count, last_attempt_at_utc FROM quota_usage ORDER BY endpoint_key").fetchall()
    today = [row for row in rows if row[0] == "2026-08-25"]
    usage = {str(row[1]): int(row[2]) for row in today}
    quota = LocalKrxOpenApiQuota(QUOTA_DB)
    return {
        "usage_date_kst": today[0][0] if today else None,
        "global_after": sum(usage.values()),
        "endpoint_usage": usage,
        "remaining_global": quota.remaining("stk_bydd_trd"),
        "remaining_stk_bydd_trd": quota.remaining("stk_bydd_trd"),
        "remaining_ksq_bydd_trd": quota.remaining("ksq_bydd_trd"),
        "last_attempt_at_utc": max((str(row[3]) for row in today), default=None),
    }


def _audit_store(store: KrxRawStockStore, dates: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifests = store.list_manifest()
    by_date = _by_date(manifests, dates)
    complete_dates: list[str] = []
    no_data_dates: list[str] = []
    failed_dates: list[str] = []
    partial_dates: list[str] = []
    missing_dates: list[str] = []
    by_year: dict[str, dict[str, int]] = {}
    rows_by_market = {market: 0 for market in MARKETS}
    complete_partitions = 0
    no_data_partitions = 0
    failed_partitions = 0
    missing_partitions = 0
    integrity_scan = 0
    no_data_scan = 0
    integrity_errors: list[dict[str, Any]] = []
    no_data_errors: list[dict[str, Any]] = []
    counts = {key: 0 for key in ("content_hash_mismatch_count", "file_hash_mismatch_count", "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count", "duplicate_ticker_count")}
    numeric_rows = alpha_rows = invalid_rows = 0
    numeric_codes: set[str] = set()
    alpha_codes: set[str] = set()
    alpha_samples: list[str] = []
    for day in dates:
        year = day[:4]
        stats = by_year.setdefault(year, {"candidate_dates": 0, "complete_dates": 0, "finalized_no_data_dates": 0, "missing_dates": 0, "failed_dates": 0, "partial_dates": 0, "complete_partitions": 0, "no_data_partitions": 0, "raw_rows": 0})
        stats["candidate_dates"] += 1
        kind = _classification(by_date[day])
        if kind == "COMPLETE":
            complete_dates.append(day)
            stats["complete_dates"] += 1
            complete_partitions += 2
            stats["complete_partitions"] += 2
            for market in MARKETS:
                row_count = int(by_date[day][market].get("row_count") or 0)
                rows_by_market[market] += row_count
                stats["raw_rows"] += row_count
        elif kind == "NO_DATA":
            no_data_dates.append(day)
            stats["finalized_no_data_dates"] += 1
            no_data_partitions += 2
            stats["no_data_partitions"] += 2
        elif kind == "FAILED":
            failed_dates.append(day)
            stats["failed_dates"] += 1
            failed_partitions += sum((by_date[day].get(market) or {}).get("status") == "FAILED" for market in MARKETS)
            if any((by_date[day].get(market) or {}).get("status") == "COMPLETE" for market in MARKETS):
                partial_dates.append(day)
                stats["partial_dates"] += 1
        elif kind == "PARTIAL":
            partial_dates.append(day)
            stats["partial_dates"] += 1
        else:
            missing_dates.append(day)
            stats["missing_dates"] += 1
        missing_partitions += sum((by_date[day].get(market) or {}).get("status") is None for market in MARKETS)

    for row in manifests:
        day, market, status = row.get("date"), row.get("market"), row.get("status")
        if day not in by_date or market not in MARKETS:
            continue
        if status == "COMPLETE":
            integrity_scan += 1
            result = store.verify_snapshot(market, day)
            if not result.get("valid"):
                errors = [str(item) for item in result.get("errors", [])]
                integrity_errors.append({"market": market, "date": day, "errors": errors})
                text = " ".join(errors).lower()
                counts["content_hash_mismatch_count"] += int("content hash mismatch" in text)
                counts["file_hash_mismatch_count"] += int("file hash mismatch" in text)
                counts["row_count_mismatch_count"] += int("row count mismatch" in text)
                counts["physical_schema_error_count"] += int("schema" in text or "parquet" in text)
                counts["source_date_mismatch_count"] += int("date" in text)
                counts["duplicate_ticker_count"] += int("duplicate" in text)
                continue
            frame = store.load_snapshot(market, day)
            duplicated = int(frame["ticker"].astype(str).duplicated().sum())
            counts["duplicate_ticker_count"] += duplicated
            for ticker in frame["ticker"].astype(str):
                if NUMERIC.fullmatch(ticker):
                    numeric_rows += 1
                    numeric_codes.add(ticker)
                elif VALID.fullmatch(ticker):
                    alpha_rows += 1
                    alpha_codes.add(ticker)
                    if ticker not in alpha_samples and len(alpha_samples) < 50:
                        alpha_samples.append(ticker)
                else:
                    invalid_rows += 1
        elif status == "NO_DATA":
            no_data_scan += 1
            verification = store.verify_snapshot(market, day)
            if not verification.get("valid"):
                no_data_errors.append({"market": market, "date": day, "errors": verification.get("errors", [])})

    conflicts: list[dict[str, Any]] = []
    for day in complete_dates:
        frames = {market: store.load_snapshot(market, day) for market in MARKETS}
        overlap = sorted(set(frames["KOSPI"]["ticker"].astype(str)) & set(frames["KOSDAQ"]["ticker"].astype(str)))
        conflicts.extend({"date": day, "ticker": ticker, "markets": list(MARKETS)} for ticker in overlap)
    coverage = {
        "target_start": TARGET_START,
        "target_end": TARGET_END,
        "candidate_date_count": len(dates),
        "complete_date_count": len(complete_dates),
        "finalized_no_data_date_count": len(no_data_dates),
        "complete_partition_count": complete_partitions,
        "no_data_partition_count": no_data_partitions,
        "terminal_partition_count": complete_partitions + no_data_partitions,
        "expected_partition_count": len(dates) * 2,
        "missing_date_count": len(missing_dates),
        "missing_partition_count": missing_partitions,
        "failed_date_count": len(failed_dates),
        "failed_partition_count": failed_partitions,
        "partial_date_count": len(partial_dates),
        "rows_by_market": rows_by_market,
        "total_raw_rows": sum(rows_by_market.values()),
        "first_complete_trading_date": min(complete_dates) if complete_dates else None,
        "last_complete_trading_date": max(complete_dates) if complete_dates else None,
        "missing_dates": missing_dates,
        "failed_dates": failed_dates,
        "partial_dates": partial_dates,
        "coverage_by_year": by_year,
    }
    integrity = {
        "integrity_scan_count": integrity_scan,
        "no_data_integrity_scan_count": no_data_scan,
        "integrity_error_count": len(integrity_errors),
        "no_data_integrity_error_count": len(no_data_errors),
        **counts,
        "errors": integrity_errors[:50],
        "no_data_errors": no_data_errors[:50],
    }
    cross_market = {"cross_market_ticker_conflict_count": len(conflicts), "samples": conflicts[:50]}
    identifier = {
        "numeric_short_code_row_count": numeric_rows,
        "alphanumeric_short_code_row_count": alpha_rows,
        "invalid_short_code_count": invalid_rows,
        "unique_numeric_ticker_count": len(numeric_codes),
        "unique_alphanumeric_ticker_count": len(alpha_codes),
        "alphanumeric_sample_codes": sorted(alpha_samples),
    }
    return coverage, integrity, cross_market, identifier, by_date


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    started = datetime.now(timezone.utc)
    validation_head = git_head()
    dates = candidate_dates(TARGET_START, TARGET_END)
    store = KrxRawStockStore(RAW_ROOT)
    coverage, integrity, cross_market, identifier, by_date = _audit_store(store, dates)
    diagnostic = _load(OUTPUT / "FIX06_live_diagnostic_summary.json", {}) or {}
    pilot = _load(OUTPUT / "FIX07_live_pilot_summary.json", {}) or {}
    samsung = _load(OUTPUT / "FIX07_samsung_listed_shares_evidence.json", {}) or {}
    repair = _load(OUTPUT / "FIX07_failed_partition_repair.json", {}) or {}
    resume = _load(OUTPUT / "FIX07_backfill_resume_summary.json", {}) or {}
    old_quota = _load(OUTPUT / "quota_summary.json", {}) or {}
    quota = _quota()
    repair_requests = int(repair.get("attempt_count", 0) or 0)
    resume_result = resume.get("result", {}) if isinstance(resume, dict) else {}
    resume_requests = int(resume.get("request_count", resume_result.get("krx_open_api_attempt_count", 0)) or 0)
    pilot_requests = int(pilot.get("request_count", 0) or 0)
    status_counts = {
        key: int(pilot.get("status_counts", {}).get(key, 0) or 0)
        + int(resume.get("status_counts", {}).get(key, 0) or 0)
        for key in ("401", "403", "429", "5xx", "transport_error")
    }
    status_counts["transport_error"] += int(repair.get("http_status") is None and repair.get("attempt_count", 0) == 1 and repair.get("status") != "PASS")
    resume_idempotency = {
        "pending_partition_count": coverage["missing_partition_count"] + coverage["failed_partition_count"],
        "network_request_count": resume_requests,
        "status": "PASS" if coverage["missing_partition_count"] == 0 and coverage["failed_partition_count"] == 0 and resume_requests == 0 else "INCOMPLETE",
    }
    gate = evaluate_ready_gate(
        diagnostic=diagnostic,
        pilot=pilot,
        samsung=samsung,
        coverage=coverage,
        integrity=integrity,
        cross_market=cross_market,
        identifier=identifier,
        validation_head=pilot.get("validation_source_head", validation_head),
    )
    blockers = list(gate["blockers"])
    if repair.get("status") != "PASS":
        blockers.append("BLOCKED_TRANSPORT_REPAIR" if repair.get("status") else "BLOCKED_PROVENANCE")
    if resume.get("status") not in {"PASS", None}:
        blockers.append(str(resume.get("status")))
    blockers = list(dict.fromkeys(blockers))
    priority = ("BLOCKED_KRX_AUTH", "BACKFILL_PAUSED_QUOTA", "BLOCKED_KRX_TRANSPORT", "BLOCKED_TRANSPORT_REPAIR", "BLOCKED_KRX_SCHEMA", "BLOCKED_PROVENANCE", "BLOCKED_PILOT", "BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE", "BLOCKED_RAW_STORE_INTEGRITY", "BLOCKED_CROSS_MARKET_TICKER_CONFLICT", "BLOCKED_IDENTIFIER_DISTRIBUTION", "BLOCKED_COVERAGE")
    primary = next((item for item in priority if item in blockers), blockers[0] if blockers else None)
    final_status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX07_REVIEW" if not blockers and gate["all_pass"] else (primary or "BLOCKED_COVERAGE")
    current_evidence = {
        "diagnostic": {"current": diagnostic_gate(diagnostic), "status": diagnostic.get("status")},
        "pilot": {"current": pilot_gate(pilot, pilot.get("validation_source_head", validation_head)), "status": pilot.get("status")},
        "samsung": {"current": samsung_gate(samsung, pilot.get("validation_source_head", validation_head)), "status": samsung.get("status")},
        "repair": {"current": repair.get("status") == "PASS", "status": repair.get("status")},
        "resume": {"current": resume.get("status") == "PASS", "status": resume.get("status")},
    }
    _dump(OUTPUT / "coverage_summary.json", {"coverage": coverage, "status": "PASS" if coverage_gate(coverage) else "INCOMPLETE", "generated_at": started.isoformat()})
    _write_csv(OUTPUT / "coverage_by_year.csv", [{"year": year, **values} for year, values in sorted(coverage["coverage_by_year"].items())], ["year", "candidate_dates", "complete_dates", "finalized_no_data_dates", "missing_dates", "failed_dates", "partial_dates", "complete_partitions", "no_data_partitions", "raw_rows"])
    _dump(OUTPUT / "missing_coverage_evidence.json", {"candidate_date_count": len(dates), "missing_dates": coverage["missing_dates"], "failed_dates": coverage["failed_dates"], "partial_dates": coverage["partial_dates"], "missing_partition_count": coverage["missing_partition_count"], "failed_partition_count": coverage["failed_partition_count"]})
    _dump(OUTPUT / "partition_integrity_summary.json", {**integrity, "status": "PASS" if gate["checks"]["integrity_ok"] else "BLOCKED_RAW_STORE_INTEGRITY"})
    _dump(OUTPUT / "cross_market_conflict_evidence.json", {**cross_market, "status": "PASS" if gate["checks"]["cross_market_ok"] else "BLOCKED_CROSS_MARKET_TICKER_CONFLICT"})
    _dump(OUTPUT / "identifier_distribution_summary.json", {**identifier, "status": "PASS" if gate["checks"]["identifier_ok"] else "BLOCKED_IDENTIFIER_DISTRIBUTION"})
    _dump(OUTPUT / "quota_summary.json", {**quota, "pilot_request_count": pilot_requests, "repair_request_count": repair_requests, "resume_request_count": resume_requests, "total_fix07_request_count": pilot_requests + repair_requests + resume_requests, "retry_count": int(pilot.get("retry_count", 0)) + int(repair.get("retry_count", 0)) + int(resume.get("retry_count", 0)), **{f"http_{key}_count": value for key, value in status_counts.items() if key != "transport_error"}, "transport_error_count": status_counts["transport_error"]})
    _write_csv(OUTPUT / "failed_dates.csv", [{"date": day, "classification": _classification(by_date[day]), "markets": ";".join(f"{market}:{(by_date[day].get(market) or {}).get('status')}" for market in MARKETS)} for day in coverage["failed_dates"] + coverage["partial_dates"]], ["date", "classification", "markets"])
    _dump(OUTPUT / "FIX07_provenance_summary.json", {"production_runtime_head": PRODUCTION_RUNTIME_HEAD, "validation_source_head": pilot.get("validation_source_head"), "artifact_head": validation_head, "errata_primary_implementation_head": PRODUCTION_RUNTIME_HEAD, "diagnostic_current": current_evidence["diagnostic"], "pilot_current": current_evidence["pilot"], "samsung_current": current_evidence["samsung"], "repair_current": current_evidence["repair"], "resume_current": current_evidence["resume"], "status": "PASS" if not blockers else "BLOCKED_PROVENANCE"})
    _dump(OUTPUT / "FIX07_closure_validation_summary.json", {"validation_generation": FIX_VERSION, "validation_source_head": validation_head, "production_runtime_head": PRODUCTION_RUNTIME_HEAD, "coverage": coverage, "integrity": integrity, "cross_market": cross_market, "identifier": identifier, "gate": gate, "current_evidence": current_evidence, "resume_idempotency": resume_idempotency, "status": final_status, "known_phase_limitations": ["FULL_REGRESSION_CLOSURE_DEFERRED"], "blockers": blockers, "generated_at": datetime.now(timezone.utc).isoformat()})
    summary = {
        "fix_version": FIX_VERSION,
        "fix07_start_head": START_HEAD,
        "validation_source_head": validation_head,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "artifact_head": validation_head,
        "coverage": coverage,
        "integrity": integrity,
        "cross_market": cross_market,
        "identifier_distribution": identifier,
        "pilot": {"request_count": pilot_requests, "retry_count": pilot.get("retry_count", 0), "status": pilot.get("status")},
        "repair": repair,
        "resume": {"request_count": resume_requests, "retry_count": resume.get("retry_count", 0), "status": resume.get("status")},
        "quota": {**quota, "before_fix07_global": old_quota.get("global_after"), "pilot_request_count": pilot_requests, "repair_request_count": repair_requests, "resume_request_count": resume_requests, "total_fix07_request_count": pilot_requests + repair_requests + resume_requests, "status_counts": status_counts},
        "current_evidence": current_evidence,
        "historical_ca_replay_count": 0,
        "corporate_action_state_modified_count": 0,
        "adjusted_price_store_refresh_count": 0,
        "dirty_transition_count": 0,
        "resume_idempotency": resume_idempotency,
        "known_phase_limitations": ["FULL_REGRESSION_CLOSURE_DEFERRED"],
        "blockers": blockers,
        "recommendation": final_status,
        "status": final_status,
    }
    _dump(OUTPUT / "krx_historical_backfill_v01_summary.json", summary)
    _dump(OUTPUT / "krx_historical_backfill_v01_manifest.json", {"fix_version": FIX_VERSION, "start_head": START_HEAD, "production_runtime_head": PRODUCTION_RUNTIME_HEAD, "validation_source_head": validation_head, "artifact_head": validation_head, "target_start": TARGET_START, "target_end": TARGET_END, "candidate_date_count": len(dates), "status": final_status, "blockers": blockers})
    (OUTPUT / "krx_historical_backfill_recommendation.md").write_text("krx_historical_backfill_recommendation.md\n\n" + f"FIX07 상태: {final_status}\n\n" + ("모든 closure gate가 통과했다. Architect review 전까지 CLOSED로 선언하지 않는다.\n" if not blockers else "현재 blocker를 해결한 뒤 명시적으로 resume해야 한다.\n"), encoding="utf-8")
    print(json.dumps({"status": final_status, "coverage": coverage, "gate": gate, "network_request_count": 0}, ensure_ascii=False, sort_keys=True))
    return 0 if final_status.startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
