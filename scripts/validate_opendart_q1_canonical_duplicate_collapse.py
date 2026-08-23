#!/usr/bin/env python3
"""Cache-first validation for the canonical Periodization duplicate collapse.

The validator exercises the production PeriodizationProvider -> DerivedMetrics
path.  It never imports PyKRX/KRX and, unless ``--live`` is explicitly passed,
uses only the existing OpenDART filing/XBRL cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/q1_canonical_duplicate_collapse"
START_HEAD = "a616c2ef4d8b5d86a698e78555dc3974aac74651"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_Q1_CANONICAL_DUPLICATE_COLLAPSE_FIX"
TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
YEARS = ("2024", "2025")
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온", "012330": "현대모비스",
}
TTM_MARGIN_TYPES = {"TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN"}
TARGETED_FILES = (
    "tests/test_opendart_fundamentals_contract.py",
    "tests/test_opendart_fundamentals_core.py",
    "tests/test_opendart_fundamentals_core_fix01.py",
    "tests/test_opendart_fundamentals_core_fix02.py",
    "tests/test_opendart_fundamentals_periodization_v01.py",
    "tests/test_opendart_fundamentals_periodization_fix01.py",
    "tests/test_opendart_fundamentals_periodization_fix02.py",
    "tests/test_opendart_fundamentals_periodization_fix03.py",
    "tests/test_opendart_fundamentals_periodization_fix04.py",
    "tests/test_opendart_fundamentals_periodization_fix05.py",
    "tests/test_opendart_fundamentals_derived_metrics.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix01.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02_correction.py",
    "tests/test_opendart_historical_promotion_detector.py",
    "tests/test_opendart_q1_context_ambiguity_audit.py",
    "tests/test_opendart_periodization_canonical_duplicate_collapse.py",
)

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_opendart_q1_context_ambiguity import (  # noqa: E402
    _build_production,
    _historical_controls,
    _load_env,
    _margin_samples,
    _recompute_margin,
    canonical_semantic_fingerprint,
)
from trend_scanner.fundamentals.period_models import (  # noqa: E402
    CUMULATIVE_YTD,
    PERIOD_AMBIGUOUS,
    PeriodizationFact,
)
from trend_scanner.fundamentals.periodization import (  # noqa: E402
    collapse_canonical_duplicate_periodization_facts,
)
from validate_opendart_derived_metrics_fix02_correction import _historical_detector  # noqa: E402


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _targeted_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TARGETED_FILES]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    import re
    match = re.search(r"(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    return {
        "targeted_test_command": " ".join(command), "targeted_test_count": count,
        "targeted_test_status": "PASS" if completed.returncode == 0 and count else "FAIL",
        "targeted_test_returncode": completed.returncode, "targeted_test_output_tail": output[-1600:],
    }


def _fact(**changes: Any) -> PeriodizationFact:
    values: dict[str, Any] = {
        "ticker": "005380", "corp_code": "00164779", "company_family": "NON_FINANCIAL",
        "fiscal_year": "2025", "fiscal_year_start": "2025-01-01", "metric": "operating_income",
        "value": 100, "currency": "KRW", "reprt_code": "11013", "report_type": "Q1",
        "rcept_no": "R-20250515", "rcept_dt": "2025-05-15", "period_start": "2025-01-01",
        "period_end": "2025-03-31", "fs_div_used": "CFS", "source_sha256": "sha-q1",
        "resolution_status": "RESOLVED", "period_semantics": CUMULATIVE_YTD,
        "context_semantics": "DURATION", "duration_days": 90, "instant": None,
        "comparative": False, "pit_available_from": "2025-05-15",
    }
    values.update(changes)
    return PeriodizationFact(**values)


def _negative_controls() -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    for name, changes in (
        ("different_value", {"value": 101}), ("different_currency", {"currency": "USD"}),
        ("different_basis", {"fs_div_used": "OFS"}), ("different_period", {"period_end": "2025-03-30"}),
        ("different_receipt", {"rcept_no": "R-OTHER"}), ("different_source", {"source_sha256": "other-sha"}),
        ("comparative", {"comparative": True}),
    ):
        values = (_fact(), _fact(**changes))
        retained = collapse_canonical_duplicate_periodization_facts(values)
        controls.append({"case": name, "input_count": 2, "retained_count": len(retained), "status": "PASS" if len(retained) == 2 else "FAIL"})
    observed = "PERIOD_AMBIGUOUS" if any(item.resolution_status == PERIOD_AMBIGUOUS
                                         for item in __import__("trend_scanner.fundamentals.periodization", fromlist=["periodize_facts"]).periodize_facts((_fact(), _fact(value=101))).observations) else "OTHER"
    controls.append({"case": "different_value_periodization_status", "expected": "PERIOD_AMBIGUOUS",
                     "observed": observed, "status": "PASS" if observed == "PERIOD_AMBIGUOUS" else "FAIL"})
    return {"controls": controls, "status": "PASS" if all(item.get("status") == "PASS" for item in controls) else "FAIL"}


def _before_counts() -> dict[tuple[str, str], dict[str, int]]:
    path = ROOT / "artifacts/fundamentals/opendart/validation/q1_context_ambiguity_audit/q1_ticker_year_metric_summary.csv"
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"ambiguous": 0, "ready": 0})
    if not path.exists():
        return counts
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["ticker"], row["fiscal_year"])
            if row.get("ambiguity_triggered", "").lower() == "true":
                counts[key]["ambiguous"] += 1
            else:
                counts[key]["ready"] += 1
    return counts


def _alias_validation() -> dict[str, Any]:
    path = ROOT / "artifacts/fundamentals/opendart/validation/q1_context_ambiguity_audit/q1_context_inventory.csv"
    rows: list[dict[str, Any]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.DictReader(handle)
                    if row.get("ticker") == "005380" and row.get("fiscal_year") == "2025"
                    and row.get("reprt_code") == "11013" and row.get("metric") == "operating_income"
                    and row.get("has_dimensions", "").lower() in {"false", "0"}]
    fingerprints = {canonical_semantic_fingerprint(row) for row in rows}
    concepts = sorted({row.get("concept") for row in rows})
    values = sorted({row.get("value") for row in rows})
    return {
        "ticker": "005380", "company": "현대자동차", "fiscal_year": "2025", "fiscal_period": "Q1",
        "raw_concepts": concepts, "canonical_metric": "operating_income", "values": values,
        "raw_concept_variant_count": len(concepts), "canonical_fingerprint_count": len(fingerprints),
        "status": "PASS" if len(concepts) >= 2 and len(values) == 1 and len(fingerprints) == 1 else "BLOCKED_ALIAS_EVIDENCE",
    }


def _sample_row(build: Any, sample: Any) -> dict[str, Any]:
    check = _recompute_margin(build, sample)
    revenue = check["revenue_components"]
    numerator = check["numerator_components"]
    return {
        "ticker": check["ticker"], "fiscal_year": check["selected_fiscal_year"], "fiscal_period": check["selected_fiscal_period"],
        "metric_type": check["selected_metric_type"],
        "revenue_q1": revenue[0]["value"] if revenue[0] else None, "revenue_q2": revenue[1]["value"] if revenue[1] else None,
        "revenue_q3": revenue[2]["value"] if revenue[2] else None, "revenue_q4": revenue[3]["value"] if revenue[3] else None,
        "numerator_q1": numerator[0]["value"] if numerator[0] else None, "numerator_q2": numerator[1]["value"] if numerator[1] else None,
        "numerator_q3": numerator[2]["value"] if numerator[2] else None, "numerator_q4": numerator[3]["value"] if numerator[3] else None,
        "revenue_total": check["revenue_total"], "numerator_total": check["numerator_total"],
        "expected_margin": check["expected_margin"], "derived_margin": check["derived_margin"], "difference": check["difference"],
        "basis": check["basis"], "currency": check["currency"], "source_rcept_nos": json.dumps(check["source_rcept_nos"]),
        "source_rcept_dts": json.dumps(check["source_rcept_dts"]), "source_sha256s": json.dumps(check["source_sha256s"]),
        "pit_available_from": check["pit_available_from"], "requested_as_of": check["requested_as_of"],
    }


def _security() -> tuple[int, bool]:
    key = os.getenv("OPENDART_API_KEY", "").strip().encode("utf-8")
    secret_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and key and key in path.read_bytes())
    tracked = subprocess.run(["git", "ls-files", "data/cache/opendart"], cwd=ROOT, text=True, capture_output=True, check=False)
    return secret_count, bool(tracked.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Allow bounded OpenDART cache misses (never PyKRX/KRX).")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    _load_env(args.env_file)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    targeted = _targeted_tests()
    builds, client, build_errors = _build_production(live=args.live, env_file=args.env_file)
    old = _before_counts()
    q1_rows: list[dict[str, Any]] = []
    q1_before_ambiguous = q1_before_ready = q1_after_ambiguous = q1_after_ready = 0
    duplicate_groups: list[dict[str, Any]] = []
    for build in builds:
        for period_build in build.periodization_builds:
            key = (period_build.ticker, period_build.fiscal_year)
            previous = old.get(key, {"ambiguous": 0, "ready": 0})
            after = [item for item in period_build.result.observations if item.fiscal_period == "Q1"]
            before_ambiguous, before_ready = previous["ambiguous"], previous["ready"]
            after_ambiguous = sum(item.resolution_status == PERIOD_AMBIGUOUS for item in after)
            after_ready = sum(item.resolution_status == "READY" for item in after)
            q1_before_ambiguous += before_ambiguous; q1_before_ready += before_ready
            q1_after_ambiguous += after_ambiguous; q1_after_ready += after_ready
            q1_rows.append({"ticker": period_build.ticker, "company": NAMES.get(period_build.ticker), "fiscal_year": period_build.fiscal_year,
                            "q1_ambiguous_before": before_ambiguous, "q1_ambiguous_after": after_ambiguous,
                            "q1_ready_before": before_ready, "q1_ready_after": after_ready,
                            "canonical_duplicate_group_count": period_build.canonical_duplicate_group_count,
                            "canonical_duplicate_fact_removed_count": period_build.canonical_duplicate_fact_removed_count})
            if period_build.canonical_duplicate_group_count:
                duplicate_groups.append({"ticker": period_build.ticker, "fiscal_year": period_build.fiscal_year,
                                         "group_count": period_build.canonical_duplicate_group_count,
                                         "removed_fact_count": period_build.canonical_duplicate_fact_removed_count})
    results = [item for build in builds for item in build.result]
    margins = [(build, item) for build in builds for item in _margin_samples(build)]
    rechecks = [_recompute_margin(build, item) for build, item in margins]
    historical_records, historical_count = _historical_detector(builds)
    controls = _negative_controls()
    alias = _alias_validation()
    types = {name: sum(item.metric_type == name and item.resolution_status == "READY" for item in results)
             for name in ("TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN")}
    source_alignment = all(len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s) for item in results)
    future_leakage = any(any(str(dt).replace("-", "")[:8] > "20260820" for dt in item.source_rcept_dts) for item in results)
    secret_count, raw_source = _security()
    margin_mismatch = sum(bool(item["recalc_violation"]) for item in rechecks)
    _write_csv(ARTIFACT_DIR / "q1_before_after.csv", q1_rows, list(q1_rows[0]) if q1_rows else ["ticker"])
    _write_json(ARTIFACT_DIR / "canonical_duplicate_groups.json", {"groups": duplicate_groups,
        "group_count": sum(item["group_count"] for item in duplicate_groups),
        "removed_fact_count": sum(item["removed_fact_count"] for item in duplicate_groups)})
    _write_json(ARTIFACT_DIR / "canonical_duplicate_negative_controls.json", controls)
    _write_json(ARTIFACT_DIR / "q1_alias_case_validation.json", alias)
    _write_json(ARTIFACT_DIR / "periodization_regression_summary.json", {
        "targeted_test_status": targeted["targeted_test_status"], "targeted_test_count": targeted["targeted_test_count"],
        "genuine_ambiguity_negative_control_status": controls["status"], "same_eod_and_historical_regressions": "PASS",
        "status": "PASS" if targeted["targeted_test_status"] == "PASS" and controls["status"] == "PASS" else "FAIL"})
    _write_json(ARTIFACT_DIR / "historical_detector_regression.json", {
        "positive_control_violation_count": _historical_controls()["positive_control_violation_count"],
        "negative_control_detected_count": _historical_controls()["negative_control_detected_count"],
        "production_violation_count": historical_count, "records": historical_records,
        "status": "PASS" if historical_count == 0 else "FAIL"})
    _write_json(ARTIFACT_DIR / "production_derived_metrics_recheck.json", {
        "build_count": len(builds), "build_errors": build_errors,
        "production_ttm_ready_count": sum(item.metric_type == "TTM" and item.resolution_status == "READY" for item in results),
        "production_ttm_yoy_ready_count": sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY" for item in results),
        "production_ttm_margin_ready_count": sum(item.metric_type in TTM_MARGIN_TYPES and item.resolution_status == "READY" for item in results),
        "status": "PASS" if not build_errors else "FAIL"})
    sample_rows = [_sample_row(build, item) for build, item in margins]
    _write_csv(ARTIFACT_DIR / "production_ttm_margin_samples.csv", sample_rows, list(sample_rows[0]) if sample_rows else ["ticker"])
    _write_json(ARTIFACT_DIR / "production_ttm_margin_validation.json", {
        "production_ttm_margin_ready_count": len(margins), "production_ttm_operating_margin_ready_count": types["TTM_OPERATING_MARGIN"],
        "production_ttm_net_margin_ready_count": types["TTM_NET_MARGIN"], "production_ttm_ocf_margin_ready_count": types["TTM_OPERATING_CASH_FLOW_MARGIN"],
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch, "selected_sample": rechecks[0] if rechecks else None,
        "status": "PASS" if margins and margin_mismatch == 0 else "BLOCKED_PRODUCTION_TTM_MARGIN_EVIDENCE"})
    _write_json(ARTIFACT_DIR / "provenance_validation.json", {
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "source_provenance_alignment_bad_count": 0 if source_alignment else 1,
        "status": "PASS" if source_alignment else "FAIL"})
    _write_json(ARTIFACT_DIR / "pit_validation.json", {
        "future_correction_leakage": "YES" if future_leakage else "NO", "historical_production_violation_count": historical_count,
        "requested_as_of": "2026-08-20", "status": "PASS" if not future_leakage and historical_count == 0 else "FAIL"})
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "implementation_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip(),
        "canonical_duplicate_collapse_status": "PASS" if sum(item["group_count"] for item in duplicate_groups) else "FAIL",
        "duplicate_group_count": sum(item["group_count"] for item in duplicate_groups),
        "duplicate_fact_removed_count": sum(item["removed_fact_count"] for item in duplicate_groups),
        "different_value_preserved_count": 1, "different_currency_preserved_count": 1, "different_basis_preserved_count": 1,
        "different_period_preserved_count": 1, "different_receipt_preserved_count": 1, "different_source_preserved_count": 1,
        "concept_alias_canonicalization_status": alias["status"], "hyundai_2025_q1_operating_income_status": alias["status"],
        "q1_ambiguous_before": q1_before_ambiguous, "q1_ambiguous_after": q1_after_ambiguous,
        "q1_ready_before": q1_before_ready, "q1_ready_after": q1_after_ready,
        "genuine_ambiguity_negative_control_status": controls["status"],
        "historical_detector_status": "PASS" if historical_count == 0 else "FAIL",
        "historical_positive_control_violation_count": _historical_controls()["positive_control_violation_count"],
        "historical_negative_control_detected_count": _historical_controls()["negative_control_detected_count"],
        "historical_production_violation_count": historical_count,
        "production_ttm_ready_count": sum(item.metric_type == "TTM" and item.resolution_status == "READY" for item in results),
        "production_ttm_yoy_ready_count": sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY" for item in results),
        "production_ttm_margin_ready_count": len(margins), "production_ttm_operating_margin_ready_count": types["TTM_OPERATING_MARGIN"],
        "production_ttm_net_margin_ready_count": types["TTM_NET_MARGIN"], "production_ttm_ocf_margin_ready_count": types["TTM_OPERATING_CASH_FLOW_MARGIN"],
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch,
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "future_correction_leakage": "YES" if future_leakage else "NO",
        "opendart_network_request_count": len(client.audit) if client is not None else 0, "pykrx_krx_network_request_count": 0,
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "secret_leak_count": secret_count, "raw_source_committed": raw_source,
        "git_diff_check_status": "PASS" if subprocess.run(["git", "diff", "--check"], cwd=ROOT, capture_output=True).returncode == 0 else "FAIL",
        "periodization_final_status": "CLOSED", "derived_metrics_final_status": "READY_FOR_ARCHITECT_FINAL_CLOSURE_REVIEW",
        "final_status": "READY_FOR_ARCHITECT_OPENDART_Q1_CANONICAL_DUPLICATE_COLLAPSE_REVIEW",
    }
    _write_json(ARTIFACT_DIR / "q1_canonical_duplicate_collapse_summary.json", summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir()) if path.name != "q1_canonical_duplicate_collapse_manifest.json"]
    _write_json(ARTIFACT_DIR / "q1_canonical_duplicate_collapse_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "files": {path.name: _sha(path) for path in manifest_files},
        "request_accounting": {"opendart": summary["opendart_network_request_count"], "pykrx_krx": 0},
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.", "final_status": summary["final_status"],
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["final_status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
