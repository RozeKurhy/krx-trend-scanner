#!/usr/bin/env python3
"""Local-first authority/cache audit for Fundamentals V1 V02.

The audit reads only the frozen local universe, filing registry, XBRL cache,
and the freshly recomputed F7 outputs.  It never creates an OpenDART client or
performs network I/O.  The resulting ``needs_live_fetch.json`` is the only
input accepted by the targeted source-completion step.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.fundamentals.opendart_contract import FilingRecord, select_pit_filing  # noqa: E402

REQUESTED_AS_OF = "2026-09-04"
PRODUCTION_DIR = ROOT / "artifacts/fundamentals/production/20260904"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_full_authority_audit_v02"
START_STATE_PATH = OUTPUT_DIR / "start_state.json"
REGISTRY_DIR = ROOT / "data/cache/opendart/filings"
XBRL_DIR = ROOT / "data/cache/opendart/xbrl"
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_NAMES = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _cache_present(rcept_no: str, reprt_code: str) -> bool:
    stem = f"{rcept_no}_{reprt_code}"
    return (XBRL_DIR / f"{stem}.zip").is_file() and (XBRL_DIR / f"{stem}.json").is_file()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _version_bucket(items: list[FilingRecord], *, registry_valid: bool) -> str:
    if not items:
        return "NO_FILING_IN_VALID_WINDOW" if registry_valid else "REGISTRY_MISSING"
    correction_count = sum(item.correction_flag for item in items)
    if correction_count == 0:
        return "ORIGINAL_ONLY"
    if correction_count == 1:
        return "ORIGINAL_PLUS_CORRECTION"
    return "MULTIPLE_CORRECTION"


def main() -> int:
    index_path = PRODUCTION_DIR / "ticker_index.csv"
    index_rows = list(csv.DictReader(index_path.open(encoding="utf-8")))
    applicable = [
        row for row in index_rows
        if row.get("asset_type") == "COMMON" and row.get("company_family") == "NON_FINANCIAL"
    ]
    selected_rows: list[dict[str, Any]] = []
    needs: list[dict[str, Any]] = []
    authority_changes: list[dict[str, Any]] = []
    registry_missing: list[dict[str, Any]] = []
    selection_status = Counter()
    chain_buckets = Counter()
    future_rejected = 0
    for row in applicable:
        ticker = str(row["ticker"])
        corp_code = str(row["corp_code"])
        for year in range(2021, 2027):
            for reprt_code in REPORT_CODES:
                registry_path = REGISTRY_DIR / f"{corp_code}_{year}_{reprt_code}.json"
                payload = _load_json(registry_path) if registry_path.is_file() else None
                raw_items = payload.get("filings", []) if isinstance(payload, dict) else []
                records = [FilingRecord.from_mapping(item) for item in raw_items if isinstance(item, dict)]
                metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
                registry_valid = bool(
                    isinstance(payload, dict)
                    and metadata.get("cache_complete") is True
                    and metadata.get("api_status") == "000"
                    and metadata.get("http_status") == 200
                )
                if not registry_valid:
                    registry_missing.append({
                        "ticker": ticker, "corp_code": corp_code, "bsns_year": str(year),
                        "reprt_code": reprt_code, "reason": "REGISTRY_CACHE_MISSING_OR_INVALID",
                    })
                chain_buckets[_version_bucket(records, registry_valid=registry_valid)] += 1
                selection = select_pit_filing(records, REQUESTED_AS_OF, str(year), reprt_code)
                selection_status[selection.status] += 1
                future_rejected += len(selection.future)
                if selection.selected is None:
                    continue
                filing = selection.selected
                present = _cache_present(filing.rcept_no, filing.reprt_code)
                item = {
                    "ticker": ticker, "corp_code": corp_code, "bsns_year": str(year),
                    "reprt_code": reprt_code, "report_type": REPORT_NAMES[reprt_code],
                    "rcept_no": filing.rcept_no, "rcept_dt": filing.rcept_dt,
                    "report_nm": filing.report_nm, "correction_flag": filing.correction_flag,
                    "filing_chain_key": filing.derived_chain_key,
                    "authority_reason": selection.reason, "cache_present": present,
                }
                selected_rows.append(item)
                if filing.correction_flag:
                    authority_changes.append({
                        **item, "change_type": "CORRECTION_AUTHORITY_SELECTED",
                    })
                if not present:
                    needs.append({
                        "ticker": ticker, "corp_code": corp_code, "year": str(year),
                        "reprt_code": reprt_code, "rcept_no": filing.rcept_no,
                        "rcept_dt": filing.rcept_dt, "report_nm": filing.report_nm,
                        "correction_flag": filing.correction_flag,
                        "reason": "SELECTED_FILING_XBRL_CACHE_MISS",
                    })

    # Recompute source-quality diagnostics from every local F7 JSON.  These
    # are intentionally read from artifacts rather than hard-coded counts.
    data_status = Counter(row.get("data_status") or "DATA_UNAVAILABLE" for row in index_rows)
    f4_status = Counter(row.get("f4_status") or "DATA_UNAVAILABLE" for row in index_rows)
    f3_status = Counter(row.get("f3_data_status") or "DATA_UNAVAILABLE" for row in index_rows)
    precision_stats = Counter()
    ambiguity_stats = Counter()
    precision_rows: list[dict[str, Any]] = []
    for row in applicable:
        payload = _load_json(PRODUCTION_DIR / str(row["artifact_path"]))
        f2 = payload.get("f2", {}) if isinstance(payload, dict) else {}
        for build in f2.get("periodization_builds", []) if isinstance(f2, dict) else []:
            for key in (
                "canonical_duplicate_group_count", "canonical_duplicate_fact_removed_count",
                "precision_equivalent_group_count", "precision_equivalent_fact_removed_count",
                "true_value_conflict_group_count",
            ):
                precision_stats[key] += int(build.get(key, 0) or 0)
            if any(int(build.get(key, 0) or 0) for key in (
                "precision_equivalent_group_count", "true_value_conflict_group_count",
            )):
                precision_rows.append({
                    "ticker": row["ticker"], "fiscal_year": build.get("fiscal_year"),
                    "precision_equivalent_groups": build.get("precision_equivalent_group_count", 0),
                    "precision_equivalent_facts_removed": build.get("precision_equivalent_fact_removed_count", 0),
                    "true_value_conflict_groups": build.get("true_value_conflict_group_count", 0),
                })
        for slot in f2.get("quarter_slots", []) if isinstance(f2, dict) else []:
            if slot.get("status") == "PERIOD_AMBIGUOUS":
                ambiguity_stats["current_quarter"] += 1
        for slot in f2.get("annual_slots", []) if isinstance(f2, dict) else []:
            if slot.get("status") == "PERIOD_AMBIGUOUS":
                ambiguity_stats["current_annual"] += 1
        for diagnostic in f2.get("diagnostics", []) if isinstance(f2, dict) else []:
            if "PRIOR" in str(diagnostic.get("reason") or "").upper():
                ambiguity_stats["prior"] += 1

    source_cache_rows = [
        {**item, "cache_state": "PRESENT" if item["cache_present"] else "MISSING"}
        for item in selected_rows
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "needs_live_fetch.json").write_text(
        json.dumps({
            "requested_as_of": REQUESTED_AS_OF,
            "network_allowed_after_local_audit": True,
            "expected_xbrl_requests": len(needs),
            "needs": needs,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(OUTPUT_DIR / "filing_authority_changes.csv", authority_changes, [
        "ticker", "corp_code", "bsns_year", "reprt_code", "report_type", "rcept_no",
        "rcept_dt", "report_nm", "correction_flag", "filing_chain_key", "authority_reason", "change_type",
    ])
    _write_csv(OUTPUT_DIR / "source_cache_completion.csv", source_cache_rows, [
        "ticker", "corp_code", "bsns_year", "reprt_code", "report_type", "rcept_no",
        "rcept_dt", "report_nm", "correction_flag", "filing_chain_key", "authority_reason",
        "cache_present", "cache_state",
    ])
    _write_csv(OUTPUT_DIR / "precision_resolution_changes.csv", precision_rows, [
        "ticker", "fiscal_year", "precision_equivalent_groups",
        "precision_equivalent_facts_removed", "true_value_conflict_groups",
    ])
    output_paths = sorted((PRODUCTION_DIR / "tickers").glob("*.json"))
    output_tickers = [path.stem.upper() for path in output_paths]
    expected_tickers = {str(row["ticker"]).upper() for row in index_rows}
    output_ticker_set = set(output_tickers)
    valid_output_count = 0
    for path in output_paths:
        payload = _load_json(path)
        if (
            isinstance(payload, dict)
            and str(payload.get("ticker") or "").upper() == path.stem.upper()
            and payload.get("requested_as_of") == REQUESTED_AS_OF
            and payload.get("terminal_status")
        ):
            valid_output_count += 1
    sample_path = OUTPUT_DIR / "external_sample_validation.csv"
    sample_rows = list(csv.DictReader(sample_path.open(encoding="utf-8"))) if sample_path.is_file() else []
    representative_checks: dict[str, Any] = {}
    for ticker in ("021240", "181710"):
        payload = _load_json(PRODUCTION_DIR / "tickers" / f"{ticker}.json") or {}
        f5 = payload.get("f5_ready") if isinstance(payload, dict) else {}
        representative_checks[ticker] = {
            "data_status": payload.get("data_status"),
            "f4_status": payload.get("f4_status"),
            "quarter_count": len(f5.get("quarterly", [])) if isinstance(f5, dict) else 0,
            "annual_count": len(f5.get("annual", [])) if isinstance(f5, dict) else 0,
            "optional_debt_ratio_missing": bool(isinstance(f5, dict) and f5.get("summary", {}).get("latest_debt_ratio_pct") is None),
            "optional_roe_missing": bool(isinstance(f5, dict) and f5.get("summary", {}).get("ttm_roe_pct") is None),
        }
    summary = {
        "work_id": "FUNDAMENTALS_V1_DATA_AUTHORITY_FULL_AUDIT_V02",
        "requested_as_of": REQUESTED_AS_OF,
        "local_audit": {
            "total_universe": len(index_rows),
            "applicable_non_financial_common": len(applicable),
            "non_applicable_or_excluded": len(index_rows) - len(applicable),
            "required_years": [str(year) for year in range(2021, 2027)],
            "required_filing_slots": len(applicable) * 6 * 4,
            "registry_cache_missing": len(registry_missing),
            "selected_filing_count": len(selected_rows),
            "selected_xbrl_cache_present": sum(item["cache_present"] for item in selected_rows),
            "selected_xbrl_cache_missing": len(needs),
            "filing_chain_buckets": dict(chain_buckets),
            "selection_status": dict(selection_status),
            "future_correction_or_filing_rejected": future_rejected,
            "ambiguity": dict(ambiguity_stats),
            "precision": dict(precision_stats),
        },
        "final_state": {
            "data_status": dict(data_status),
            "f3_status": dict(f3_status),
            "f4_status": dict(f4_status),
        },
        "f7_invariants": {
            "total": len(index_rows),
            "completed": valid_output_count,
            "remaining": max(len(index_rows) - valid_output_count, 0),
            "invalid": len(output_paths) - valid_output_count,
            "outside_universe": len(output_ticker_set - expected_tickers),
            "duplicate": len(output_tickers) - len(output_ticker_set),
        },
        "opendart_quota": {
            "official_usage_before": 18458,
            "safety_daily_cap": 39000,
            "max_additional_requests": 20542,
            "expected_targeted_requests": len(needs),
            "projected_daily_total": 18458 + len(needs),
            "within_safety_cap": 18458 + len(needs) <= 39000,
            "scope": "selected_filing_xbrl_cache_misses_only",
        },
        "network": {"local_audit_requests": 0},
        "representative_checks": representative_checks,
        "external_sample_validation": {
            "sample_count": len(sample_rows),
            "pass_count": sum(row.get("result") == "PASS" for row in sample_rows),
            "fail_count": sum(row.get("result") != "PASS" for row in sample_rows),
            "path": str(sample_path.relative_to(ROOT)) if sample_rows else None,
        },
    }
    start_state = _load_json(START_STATE_PATH)
    if isinstance(start_state, dict):
        summary["start_state"] = start_state
        summary["recovery_delta"] = {
            "data_unavailable": int(start_state.get("data_status", {}).get("DATA_UNAVAILABLE", 0))
            - int(data_status.get("DATA_UNAVAILABLE", 0)),
            "ready": int(data_status.get("READY", 0))
            - int(start_state.get("data_status", {}).get("READY", 0)),
        }
    fetch_manifest = _load_json(OUTPUT_DIR / "source_fetch_manifest.json")
    if isinstance(fetch_manifest, dict):
        quota = fetch_manifest.get("quota") if isinstance(fetch_manifest.get("quota"), dict) else {}
        failures = fetch_manifest.get("failures", []) if isinstance(fetch_manifest.get("failures"), list) else []
        failure_statuses = Counter(str(item.get("status") or "UNKNOWN") for item in failures if isinstance(item, dict))
        remaining_misses = int(fetch_manifest.get("remaining_cache_misses", len(needs)) or 0)
        source_unavailable = (
            remaining_misses > 0
            and len(failures) == remaining_misses
            and failure_statuses == Counter({"014": len(failures)})
            and all(str(item.get("error_type") or "") == "BinaryResponseInvalid" for item in failures if isinstance(item, dict))
        )
        summary["source_fetch"] = {
            "actual_http_requests_current_manifest": fetch_manifest.get("actual_http_requests", 0),
            "fetched_current_manifest": fetch_manifest.get("fetched", 0),
            "remaining_cache_misses": remaining_misses,
            "failure_count_current_manifest": len(failures),
            "failure_status_counts": dict(failure_statuses),
            "remaining_miss_classification": "DART_SOURCE_UNAVAILABLE_STATUS_014" if source_unavailable else "UNRESOLVED",
            "historical_attempts_total": int(quota.get("estimated_daily_total", 18458)) - 18458,
            "historical_attempt_breakdown": {
                "initial_invalid_zip_attempt": 1,
                "initial_escalated_retry_attempts": 3,
                "bulk_targeted_attempts": 4537,
                "remaining_miss_retry_attempts": 492,
            },
            "scope": fetch_manifest.get("scope"),
            "quota": quota,
        }
        summary["opendart_quota"]["actual_estimated_daily_total"] = quota.get("estimated_daily_total")
        summary["opendart_quota"]["actual_historical_attempts_total"] = (
            int(quota.get("estimated_daily_total", 18458)) - 18458
        )
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    md = [
        "# Fundamentals V1 full authority audit V02",
        "",
        f"- requested_as_of: `{REQUESTED_AS_OF}`",
        f"- universe: `{len(index_rows)}`; applicable common/non-financial: `{len(applicable)}`",
        f"- selected filings: `{len(selected_rows)}`; selected XBRL cache miss: `{len(needs)}`",
        f"- hypothetical remaining-miss projection: `18458 + {len(needs)} = {18458 + len(needs)}` / `39000` (no further fetch requested)",
        f"- registry cache missing: `{len(registry_missing)}`; future filing rejected: `{future_rejected}`",
        "- local audit network requests: `0`",
        "",
        "## Source completion",
        "",
        "- scope: selected filing XBRL cache misses only",
        f"- current manifest attempts/fetched/failures/remaining: `{summary.get('source_fetch', {}).get('actual_http_requests_current_manifest', 0)}`/`{summary.get('source_fetch', {}).get('fetched_current_manifest', 0)}`/`{summary.get('source_fetch', {}).get('failure_count_current_manifest', 0)}`/`{summary.get('source_fetch', {}).get('remaining_cache_misses', len(needs))}`",
        f"- unresolved classification: `{summary.get('source_fetch', {}).get('remaining_miss_classification', 'NOT_RECORDED')}`; status counts: `{summary.get('source_fetch', {}).get('failure_status_counts', {})}`",
        f"- historical targeted attempts: `{summary.get('source_fetch', {}).get('historical_attempts_total', 0)}`; actual estimated daily total: `{summary.get('opendart_quota', {}).get('actual_estimated_daily_total', 'NOT_RECORDED')}` / `39000`",
        "- unresolved source failures were retained in the audit manifest and were not retried beyond the quota-controlled retry.",
        "",
        "## F7 invariants",
        "",
        "```json",
        json.dumps(summary["f7_invariants"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Representative checks",
        "",
        "```json",
        json.dumps(summary["representative_checks"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## External sample validation",
        "",
        f"- samples/pass/fail: `{summary['external_sample_validation']['sample_count']}`/`{summary['external_sample_validation']['pass_count']}`/`{summary['external_sample_validation']['fail_count']}`",
        f"- artifact: `{summary['external_sample_validation']['path'] or 'NOT_RECORDED'}`",
        "",
        "## Final local state",
        "",
        "```json",
        json.dumps(summary["final_state"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    (OUTPUT_DIR / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected": len(selected_rows), "needs_live_fetch": len(needs),
        "projected_daily_total": 18458 + len(needs), "output": str(OUTPUT_DIR.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
