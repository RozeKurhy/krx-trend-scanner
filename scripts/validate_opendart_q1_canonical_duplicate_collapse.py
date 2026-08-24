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
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/final_closure_gate_fix"
START_HEAD = "f3aab12c4c698ff96025bf85b97d3beffad57fb8"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_FINAL_CLOSURE_GATE_FIX"
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
    "tests/test_opendart_context_scope_hardening.py",
    "tests/test_opendart_final_validation_gate.py",
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
    canonical_duplicate_identity,
    collapse_canonical_duplicate_periodization_facts,
)
from trend_scanner.fundamentals.xbrl_repository import _context_info  # noqa: E402
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
        controls.append({"case": name, "target_present": True, "input_count": 2, "retained_count": len(retained), "status": "PASS" if len(retained) == 2 else "FAIL"})
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


def evaluate_periodization_readiness(values: Mapping[str, Any]) -> bool:
    """Pure acceptance gate for Periodization closure."""

    required_zero = (
        "production_missing_context_scope_count", "production_primary_with_typed_dimension_count",
        "production_primary_with_additional_dimension_count", "different_scope_wrongly_collapsed_count",
        "different_value_wrongly_collapsed_count", "different_currency_wrongly_collapsed_count",
        "different_basis_wrongly_collapsed_count", "different_period_wrongly_collapsed_count",
        "different_receipt_wrongly_collapsed_count", "different_source_wrongly_collapsed_count",
        "genuine_ambiguity_wrongly_ready_count", "historical_production_violation_count",
        "production_build_error_count", "known_duplicate_regression_count",
        "ready_future_source_count",
    )
    return bool(
        values.get("targeted_test_status") == "PASS"
        and values.get("canonical_duplicate_collapse_status") == "PASS"
        and values.get("context_scope_validation_status") == "PASS"
        and all(values.get(key) == 0 for key in required_zero)
        and values.get("historical_detector_status") == "PASS"
        and values.get("future_correction_leakage") == "NO"
        and values.get("source_provenance_alignment_status") == "PASS"
        and values.get("summary_consistency_status") == "PASS"
        and values.get("validator_negative_control_status") == "PASS"
        and values.get("q1_production_regression_status") == "PASS"
        and values.get("secret_leak_count") == 0
        and values.get("raw_source_committed") is False
        and values.get("pykrx_krx_network_request_count") == 0
    )


def evaluate_derived_readiness(values: Mapping[str, Any], *, periodization_ready: bool) -> bool:
    """Pure acceptance gate for Derived Metrics final-review readiness."""

    return bool(
        periodization_ready
        and values.get("production_ttm_ready_count", 0) >= 1
        and values.get("production_ttm_yoy_ready_count", 0) >= 1
        and values.get("production_ttm_margin_ready_count", 0) >= 1
        and values.get("production_ttm_margin_recalc_mismatch_count") == 0
        and values.get("source_provenance_alignment_status") == "PASS"
        and values.get("future_correction_leakage") == "NO"
        and values.get("production_build_error_count") == 0
    )


def evaluate_final_readiness(*, periodization_ready: bool, derived_ready: bool) -> bool:
    return bool(periodization_ready and derived_ready)


def _context_scope_validation(builds: Iterable[Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for derived_build in builds:
        for period_build in derived_build.periodization_builds:
            for fact in period_build.facts:
                rows.append({
                    "ticker": period_build.ticker, "fiscal_year": period_build.fiscal_year,
                    "rcept_no": fact.rcept_no, "metric": fact.metric,
                    "context_scope_fingerprint": fact.context_scope_fingerprint,
                    "explicit_dimension_count": fact.explicit_dimension_count,
                    "typed_dimension_count": fact.typed_dimension_count,
                    "additional_explicit_dimension_count": fact.additional_explicit_dimension_count,
                    "primary": True,
                    "canonical_duplicate_group": period_build.canonical_duplicate_group_count,
                })
    missing = sum(not row["context_scope_fingerprint"] for row in rows)
    primary_typed = sum(row["typed_dimension_count"] > 0 for row in rows)
    primary_additional = sum(row["additional_explicit_dimension_count"] > 0 for row in rows)
    return {
        "production_context_fact_count": len(rows),
        "production_context_scope_fingerprint_count": len({row["context_scope_fingerprint"] for row in rows if row["context_scope_fingerprint"]}),
        "production_missing_context_scope_count": missing,
        "production_primary_with_typed_dimension_count": primary_typed,
        "production_primary_with_additional_dimension_count": primary_additional,
        "rows": rows,
        "status": "PASS" if rows and missing == 0 and primary_typed == 0 and primary_additional == 0 else "FAIL",
    }


def _context_scope_negative_controls() -> dict[str, Any]:
    def parse(body: str, context_id: str) -> dict[str, Any]:
        return _context_info(ET.fromstring(f'<context id="{context_id}">{body}</context>'))

    basis = '<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember></scenario>'
    dimension_a = basis.replace('</scenario>', '<explicitMember dimension="dart:OperatingSegmentsAxis">dart:SemiconductorMember</explicitMember></scenario>')
    typed_a = basis.replace('</scenario>', '<typedMember dimension="dart:CustomerAxis"><Customer>A</Customer></typedMember></scenario>')
    typed_b = basis.replace('</scenario>', '<typedMember dimension="dart:CustomerAxis"><Customer>B</Customer></typedMember></scenario>')
    entity_b = basis.replace('>001</identifier>', '>002</identifier>')
    parsed = [
        {"case": "same_semantics_different_context_id", "target_present": True,
         "status": "PASS" if parse(basis, "FQA")["context_scope_fingerprint"] == parse(basis, "FQQ")["context_scope_fingerprint"] else "FAIL"},
        {"case": "different_explicit_dimension", "target_present": True,
         "status": "PASS" if parse(basis, "A")["context_scope_fingerprint"] != parse(dimension_a, "B")["context_scope_fingerprint"] and not parse(dimension_a, "B")["primary"] else "FAIL"},
        {"case": "different_typed_dimension", "target_present": True,
         "status": "PASS" if parse(typed_a, "A")["context_scope_fingerprint"] != parse(typed_b, "B")["context_scope_fingerprint"] and not parse(typed_a, "A")["primary"] else "FAIL"},
        {"case": "different_entity", "target_present": True,
         "status": "PASS" if parse(basis, "A")["context_scope_fingerprint"] != parse(entity_b, "B")["context_scope_fingerprint"] else "FAIL"},
    ]
    scope_a = _fact(context_scope_fingerprint="scope-a")
    scope_b = _fact(context_scope_fingerprint="scope-b")
    retained = collapse_canonical_duplicate_periodization_facts((scope_a, scope_b))
    parsed.append({"case": "different_scope_same_value_not_collapsed", "target_present": True,
                   "status": "PASS" if len(retained) == 2 else "FAIL", "retained_count": len(retained)})
    return {"controls": parsed, "status": "PASS" if all(item["target_present"] and item["status"] == "PASS" for item in parsed) else "FAIL"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Allow bounded OpenDART cache misses (never PyKRX/KRX).")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    _load_env(args.env_file)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    targeted = _targeted_tests()
    builds, client, build_errors = _build_production(live=args.live, env_file=args.env_file)
    scope = _context_scope_validation(builds)
    scope_controls = _context_scope_negative_controls()
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
            q1_rows.append({
                "ticker": period_build.ticker, "company": NAMES.get(period_build.ticker),
                "fiscal_year": period_build.fiscal_year, "q1_ambiguous_before": before_ambiguous,
                "q1_ambiguous_after": after_ambiguous, "q1_ready_before": before_ready,
                "q1_ready_after": after_ready, "canonical_duplicate_group_count": period_build.canonical_duplicate_group_count,
                "canonical_duplicate_fact_removed_count": period_build.canonical_duplicate_fact_removed_count,
            })
            if period_build.canonical_duplicate_group_count:
                duplicate_groups.append({
                    "ticker": period_build.ticker, "fiscal_year": period_build.fiscal_year,
                    "group_count": period_build.canonical_duplicate_group_count,
                    "removed_fact_count": period_build.canonical_duplicate_fact_removed_count,
                })

    results = [item for build in builds for item in build.result]
    margins = [(build, item) for build in builds for item in _margin_samples(build)]
    rechecks = [_recompute_margin(build, item) for build, item in margins]
    historical_records, historical_count = _historical_detector(builds)
    historical_controls = _historical_controls()
    controls = _negative_controls()
    alias = _alias_validation()
    types = {name: sum(item.metric_type == name and item.resolution_status == "READY" for item in results)
             for name in ("TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN")}
    source_alignment = all(len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
                           for item in results)
    future_ready_sources = sum(
        item.resolution_status == "READY"
        and any(str(dt).replace("-", "")[:8] > "20260820" for dt in item.source_rcept_dts)
        for item in results
    )
    future_leakage = future_ready_sources > 0
    secret_count, raw_source = _security()
    margin_mismatch = sum(bool(item["recalc_violation"]) for item in rechecks)
    preserved = {
        name: sum(item.get("case") == name and item.get("status") == "PASS" for item in controls["controls"])
        for name in ("different_value", "different_currency", "different_basis", "different_period", "different_receipt", "different_source")
    }
    different_scope_wrongly_collapsed = sum(item.get("case") == "different_scope_same_value_not_collapsed" and item.get("status") != "PASS"
                                            for item in scope_controls["controls"])
    genuine_wrongly_ready = sum(item.get("case") == "different_value_periodization_status" and item.get("observed") != "PERIOD_AMBIGUOUS"
                                 for item in controls["controls"])
    duplicate_group_count = sum(item["group_count"] for item in duplicate_groups)
    duplicate_fact_removed_count = sum(item["removed_fact_count"] for item in duplicate_groups)
    # The production cohort is the authority for this regression gate.  Any
    # Q1 ambiguity that remains in a row known to contain a safe canonical
    # duplicate is specifically a duplicate-collapse regression.
    known_duplicate_regression_count = sum(
        row["q1_ambiguous_after"]
        for row in q1_rows
        if row["canonical_duplicate_group_count"] > 0
    )
    q1_production_regression_status = (
        "PASS"
        if q1_after_ambiguous == 0
        and q1_after_ready >= q1_before_ready
        and known_duplicate_regression_count == 0
        else "FAIL"
    )
    canonical_status = "PASS" if duplicate_group_count > 0 and alias["status"] == "PASS" and controls["status"] == "PASS" else "FAIL"
    historical_status = "PASS" if historical_count == 0 and historical_controls["status"] == "PASS" else "FAIL"
    context_status = scope["status"] if scope_controls["status"] == "PASS" else "FAIL"

    gate_values: dict[str, Any] = {
        "targeted_test_status": targeted["targeted_test_status"],
        "canonical_duplicate_collapse_status": canonical_status,
        "context_scope_validation_status": context_status,
        "production_missing_context_scope_count": scope["production_missing_context_scope_count"],
        "production_primary_with_typed_dimension_count": scope["production_primary_with_typed_dimension_count"],
        "production_primary_with_additional_dimension_count": scope["production_primary_with_additional_dimension_count"],
        "different_scope_wrongly_collapsed_count": different_scope_wrongly_collapsed,
        "different_value_wrongly_collapsed_count": 0 if preserved["different_value"] else 1,
        "different_currency_wrongly_collapsed_count": 0 if preserved["different_currency"] else 1,
        "different_basis_wrongly_collapsed_count": 0 if preserved["different_basis"] else 1,
        "different_period_wrongly_collapsed_count": 0 if preserved["different_period"] else 1,
        "different_receipt_wrongly_collapsed_count": 0 if preserved["different_receipt"] else 1,
        "different_source_wrongly_collapsed_count": 0 if preserved["different_source"] else 1,
        "genuine_ambiguity_wrongly_ready_count": genuine_wrongly_ready,
        "historical_detector_status": historical_status,
        "historical_production_violation_count": historical_count,
        "future_correction_leakage": "YES" if future_leakage else "NO",
        "ready_future_source_count": future_ready_sources,
        "q1_production_regression_status": q1_production_regression_status,
        "known_duplicate_regression_count": known_duplicate_regression_count,
        "q1_ambiguous_before": q1_before_ambiguous,
        "q1_ambiguous_after": q1_after_ambiguous,
        "q1_ready_before": q1_before_ready,
        "q1_ready_after": q1_after_ready,
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "production_build_error_count": len(build_errors),
        "production_ttm_ready_count": sum(item.metric_type == "TTM" and item.resolution_status == "READY" for item in results),
        "production_ttm_yoy_ready_count": sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY" for item in results),
        "production_ttm_margin_ready_count": len(margins),
        "production_ttm_operating_margin_ready_count": types["TTM_OPERATING_MARGIN"],
        "production_ttm_net_margin_ready_count": types["TTM_NET_MARGIN"],
        "production_ttm_ocf_margin_ready_count": types["TTM_OPERATING_CASH_FLOW_MARGIN"],
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch,
        "secret_leak_count": secret_count,
        "raw_source_committed": raw_source,
        # This validator is cache-first and never imports/calls PyKRX/KRX.
        "pykrx_krx_network_request_count": 0,
        "opendart_network_request_count": len(client.audit) if client is not None else 0,
    }
    # Compare the values that will be emitted into the source artifacts before
    # evaluating the final gate.  A mismatch itself must block readiness.
    consistency_pairs = {
        "production_ttm_margin_ready_count": len(margins),
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch,
        "historical_production_violation_count": historical_count,
        "production_missing_context_scope_count": scope["production_missing_context_scope_count"],
    }
    summary_consistency_mismatch = sum(gate_values[key] != value for key, value in consistency_pairs.items())
    gate_values["summary_consistency_status"] = "PASS" if summary_consistency_mismatch == 0 else "FAIL"
    periodization_ready = False
    derived_ready = False
    final_ready = False

    validator_negative_cases = []
    for name, key, value in (
        ("context_scope_fail", "context_scope_validation_status", "FAIL"),
        ("historical_violation", "historical_production_violation_count", 1),
        ("future_leakage", "future_correction_leakage", "YES"),
        ("provenance_fail", "source_provenance_alignment_status", "FAIL"),
        ("ttm_margin_zero", "production_ttm_margin_ready_count", 0),
        ("margin_recalc_mismatch", "production_ttm_margin_recalc_mismatch_count", 1),
        ("targeted_tests_fail", "targeted_test_status", "FAIL"),
        ("build_error", "production_build_error_count", 1),
        ("summary_inconsistency", "summary_consistency_status", "FAIL"),
        ("secret_leak", "secret_leak_count", 1),
        ("raw_source_committed", "raw_source_committed", True),
        ("pykrx_network", "pykrx_krx_network_request_count", 1),
        ("q1_production_regression_fail", "q1_production_regression_status", "FAIL"),
        ("known_duplicate_regression", "known_duplicate_regression_count", 1),
    ):
        mutated = dict(gate_values); mutated[key] = value
        validator_negative_cases.append({"case": name, "target_present": True,
                                         "expected_final_ready": False,
                                         "observed_final_ready": evaluate_final_readiness(
                                             periodization_ready=evaluate_periodization_readiness(mutated),
                                             derived_ready=evaluate_derived_readiness(mutated, periodization_ready=evaluate_periodization_readiness(mutated))),
                                         "status": "PASS" if not evaluate_final_readiness(
                                             periodization_ready=evaluate_periodization_readiness(mutated),
                                             derived_ready=evaluate_derived_readiness(mutated, periodization_ready=evaluate_periodization_readiness(mutated))) else "FAIL"})
    validator_negative_status = "PASS" if all(item["status"] == "PASS" for item in validator_negative_cases) else "FAIL"
    gate_values["validator_negative_control_status"] = validator_negative_status
    periodization_ready = evaluate_periodization_readiness(gate_values)
    derived_ready = evaluate_derived_readiness(gate_values, periodization_ready=periodization_ready)
    final_ready = evaluate_final_readiness(periodization_ready=periodization_ready, derived_ready=derived_ready)

    _write_csv(ARTIFACT_DIR / "production_context_scope_validation.csv", scope["rows"], [
        "ticker", "fiscal_year", "rcept_no", "metric", "context_scope_fingerprint",
        "explicit_dimension_count", "typed_dimension_count", "additional_explicit_dimension_count",
        "primary", "canonical_duplicate_group",
    ])
    _write_json(ARTIFACT_DIR / "production_context_scope_validation.json", {
        key: value for key, value in scope.items() if key != "rows"
    })
    _write_json(ARTIFACT_DIR / "context_scope_regression.json", {
        key: value for key, value in scope.items() if key != "rows"
    } | {"negative_control_status": scope_controls["status"]})
    _write_json(ARTIFACT_DIR / "context_scope_negative_controls.json", scope_controls)
    _write_json(ARTIFACT_DIR / "canonical_duplicate_regression.json", {
        "status": canonical_status, "duplicate_group_count": duplicate_group_count,
        "duplicate_fact_removed_count": duplicate_fact_removed_count,
        "different_scope_wrongly_collapsed_count": different_scope_wrongly_collapsed,
        "different_value_wrongly_collapsed_count": gate_values["different_value_wrongly_collapsed_count"],
        "different_currency_wrongly_collapsed_count": gate_values["different_currency_wrongly_collapsed_count"],
        "different_basis_wrongly_collapsed_count": gate_values["different_basis_wrongly_collapsed_count"],
        "different_period_wrongly_collapsed_count": gate_values["different_period_wrongly_collapsed_count"],
        "different_receipt_wrongly_collapsed_count": gate_values["different_receipt_wrongly_collapsed_count"],
        "different_source_wrongly_collapsed_count": gate_values["different_source_wrongly_collapsed_count"],
        "concept_alias_canonicalization_status": alias["status"],
    })
    _write_json(ARTIFACT_DIR / "q1_production_regression.json", {
        "q1_ambiguous_before": q1_before_ambiguous, "q1_ambiguous_after": q1_after_ambiguous,
        "q1_ready_before": q1_before_ready, "q1_ready_after": q1_after_ready,
        "known_duplicate_regression_count": known_duplicate_regression_count,
        "rows": q1_rows, "status": q1_production_regression_status,
        "q1_production_regression_status": q1_production_regression_status,
    })
    _write_json(ARTIFACT_DIR / "historical_detector_regression.json", {
        "positive_control_violation_count": historical_controls["positive_control_violation_count"],
        "negative_control_detected_count": historical_controls["negative_control_detected_count"],
        "production_violation_count": historical_count, "records": historical_records, "status": historical_status,
    })
    _write_json(ARTIFACT_DIR / "pit_validation.json", {
        "future_correction_leakage": "YES" if future_leakage else "NO",
        "ready_future_source_count": future_ready_sources, "historical_production_violation_count": historical_count,
        "requested_as_of": "2026-08-20", "status": "PASS" if not future_leakage and historical_count == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "security_validation.json", {
        "secret_leak_count": secret_count,
        "raw_source_committed": raw_source,
        "pykrx_krx_network_request_count": gate_values["pykrx_krx_network_request_count"],
        "opendart_network_request_count": gate_values["opendart_network_request_count"],
        "status": "PASS" if secret_count == 0 and raw_source is False and gate_values["pykrx_krx_network_request_count"] == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "production_derived_metrics_validation.json", {
        "build_count": len(builds), "production_build_error_count": len(build_errors), "build_errors": build_errors,
        "production_ttm_ready_count": gate_values["production_ttm_ready_count"],
        "production_ttm_yoy_ready_count": gate_values["production_ttm_yoy_ready_count"],
        "production_ttm_margin_ready_count": gate_values["production_ttm_margin_ready_count"],
        "status": "PASS" if not build_errors else "FAIL",
    })
    sample_rows = [_sample_row(build, item) for build, item in margins]
    _write_csv(ARTIFACT_DIR / "production_ttm_margin_samples.csv", sample_rows, list(sample_rows[0]) if sample_rows else ["ticker"])
    _write_json(ARTIFACT_DIR / "production_ttm_margin_validation.json", {
        "production_ttm_margin_ready_count": len(margins), "production_ttm_operating_margin_ready_count": types["TTM_OPERATING_MARGIN"],
        "production_ttm_net_margin_ready_count": types["TTM_NET_MARGIN"], "production_ttm_ocf_margin_ready_count": types["TTM_OPERATING_CASH_FLOW_MARGIN"],
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch, "selected_sample": rechecks[0] if rechecks else None,
        "status": "PASS" if margins and margin_mismatch == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "validator_gate_negative_controls.json", {
        "controls": validator_negative_cases, "status": validator_negative_status,
    })
    _write_json(ARTIFACT_DIR / "summary_consistency_validation.json", {
        "summary_consistency_mismatch_count": summary_consistency_mismatch,
        "summary_consistency_status": gate_values["summary_consistency_status"],
        "comparisons": consistency_pairs,
    })
    _write_json(ARTIFACT_DIR / "provenance_validation.json", {
        "source_provenance_alignment_status": gate_values["source_provenance_alignment_status"],
        "source_provenance_alignment_bad_count": 0 if source_alignment else 1,
        "status": gate_values["source_provenance_alignment_status"],
    })
    # Read the just-written source artifacts back and compare their authority
    # values with the gate inputs.  This prevents the summary from becoming a
    # second, independent source of truth.
    artifact_sources = {
        "context_scope_validation_status": json.loads((ARTIFACT_DIR / "context_scope_regression.json").read_text(encoding="utf-8"))["status"],
        "production_ttm_margin_ready_count": json.loads((ARTIFACT_DIR / "production_ttm_margin_validation.json").read_text(encoding="utf-8"))["production_ttm_margin_ready_count"],
        "production_ttm_margin_recalc_mismatch_count": json.loads((ARTIFACT_DIR / "production_ttm_margin_validation.json").read_text(encoding="utf-8"))["production_ttm_margin_recalc_mismatch_count"],
        "production_ttm_operating_margin_ready_count": json.loads((ARTIFACT_DIR / "production_ttm_margin_validation.json").read_text(encoding="utf-8"))["production_ttm_operating_margin_ready_count"],
        "production_ttm_net_margin_ready_count": json.loads((ARTIFACT_DIR / "production_ttm_margin_validation.json").read_text(encoding="utf-8"))["production_ttm_net_margin_ready_count"],
        "production_ttm_ocf_margin_ready_count": json.loads((ARTIFACT_DIR / "production_ttm_margin_validation.json").read_text(encoding="utf-8"))["production_ttm_ocf_margin_ready_count"],
        "production_ttm_ready_count": json.loads((ARTIFACT_DIR / "production_derived_metrics_validation.json").read_text(encoding="utf-8"))["production_ttm_ready_count"],
        "production_ttm_yoy_ready_count": json.loads((ARTIFACT_DIR / "production_derived_metrics_validation.json").read_text(encoding="utf-8"))["production_ttm_yoy_ready_count"],
        "historical_production_violation_count": json.loads((ARTIFACT_DIR / "historical_detector_regression.json").read_text(encoding="utf-8"))["production_violation_count"],
        "production_missing_context_scope_count": json.loads((ARTIFACT_DIR / "production_context_scope_validation.json").read_text(encoding="utf-8"))["production_missing_context_scope_count"],
        "production_primary_with_typed_dimension_count": json.loads((ARTIFACT_DIR / "context_scope_regression.json").read_text(encoding="utf-8"))["production_primary_with_typed_dimension_count"],
        "production_primary_with_additional_dimension_count": json.loads((ARTIFACT_DIR / "context_scope_regression.json").read_text(encoding="utf-8"))["production_primary_with_additional_dimension_count"],
        "q1_production_regression_status": json.loads((ARTIFACT_DIR / "q1_production_regression.json").read_text(encoding="utf-8"))["q1_production_regression_status"],
        "known_duplicate_regression_count": json.loads((ARTIFACT_DIR / "q1_production_regression.json").read_text(encoding="utf-8"))["known_duplicate_regression_count"],
        "q1_ambiguous_after": json.loads((ARTIFACT_DIR / "q1_production_regression.json").read_text(encoding="utf-8"))["q1_ambiguous_after"],
        "q1_ready_after": json.loads((ARTIFACT_DIR / "q1_production_regression.json").read_text(encoding="utf-8"))["q1_ready_after"],
        "future_correction_leakage": json.loads((ARTIFACT_DIR / "pit_validation.json").read_text(encoding="utf-8"))["future_correction_leakage"],
        "ready_future_source_count": json.loads((ARTIFACT_DIR / "pit_validation.json").read_text(encoding="utf-8"))["ready_future_source_count"],
        "source_provenance_alignment_status": json.loads((ARTIFACT_DIR / "provenance_validation.json").read_text(encoding="utf-8"))["source_provenance_alignment_status"],
        "production_build_error_count": json.loads((ARTIFACT_DIR / "production_derived_metrics_validation.json").read_text(encoding="utf-8"))["production_build_error_count"],
        "secret_leak_count": json.loads((ARTIFACT_DIR / "security_validation.json").read_text(encoding="utf-8"))["secret_leak_count"],
        "raw_source_committed": json.loads((ARTIFACT_DIR / "security_validation.json").read_text(encoding="utf-8"))["raw_source_committed"],
        "pykrx_krx_network_request_count": json.loads((ARTIFACT_DIR / "security_validation.json").read_text(encoding="utf-8"))["pykrx_krx_network_request_count"],
    }
    summary_consistency_mismatch = sum(gate_values[key] != value for key, value in artifact_sources.items())
    gate_values["summary_consistency_status"] = "PASS" if summary_consistency_mismatch == 0 else "FAIL"
    periodization_ready = evaluate_periodization_readiness(gate_values)
    derived_ready = evaluate_derived_readiness(gate_values, periodization_ready=periodization_ready)
    final_ready = evaluate_final_readiness(periodization_ready=periodization_ready, derived_ready=derived_ready)
    _write_json(ARTIFACT_DIR / "summary_consistency_validation.json", {
        "summary_consistency_mismatch_count": summary_consistency_mismatch,
        "summary_consistency_status": gate_values["summary_consistency_status"],
        "comparisons": {"summary": {key: gate_values[key] for key in artifact_sources}, "artifacts": artifact_sources},
    })

    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "implementation_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip(),
        **{key: value for key, value in scope.items() if key != "rows"}, **gate_values,
        "context_scope_validation_status": context_status,
        "production_context_fact_count": scope["production_context_fact_count"],
        "production_missing_context_scope_count": scope["production_missing_context_scope_count"],
        "production_primary_with_typed_dimension_count": scope["production_primary_with_typed_dimension_count"],
        "production_primary_with_additional_dimension_count": scope["production_primary_with_additional_dimension_count"],
        "different_scope_wrongly_collapsed_count": different_scope_wrongly_collapsed,
        "canonical_duplicate_collapse_status": canonical_status,
        "duplicate_group_count": duplicate_group_count, "duplicate_fact_removed_count": duplicate_fact_removed_count,
        "concept_alias_canonicalization_status": alias["status"],
        "q1_production_regression_status": q1_production_regression_status,
        "known_duplicate_regression_count": known_duplicate_regression_count,
        "q1_ambiguous_before": q1_before_ambiguous, "q1_ambiguous_after": q1_after_ambiguous,
        "q1_ready_before": q1_before_ready, "q1_ready_after": q1_after_ready,
        "historical_positive_control_violation_count": historical_controls["positive_control_violation_count"],
        "historical_negative_control_detected_count": historical_controls["negative_control_detected_count"],
        "historical_production_violation_count": historical_count,
        "production_ttm_operating_margin_ready_count": types["TTM_OPERATING_MARGIN"],
        "production_ttm_net_margin_ready_count": types["TTM_NET_MARGIN"],
        "production_ttm_ocf_margin_ready_count": types["TTM_OPERATING_CASH_FLOW_MARGIN"],
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch,
        "production_build_error_count": len(build_errors),
        "summary_consistency_mismatch_count": summary_consistency_mismatch,
        "summary_consistency_status": gate_values["summary_consistency_status"],
        "validator_negative_control_count": len(validator_negative_cases),
        "validator_negative_control_status": validator_negative_status,
        "periodization_ready": periodization_ready, "derived_ready": derived_ready, "final_ready": final_ready,
        "periodization_final_status": "CLOSED" if periodization_ready else "BLOCKED_OPENDART_V01_FINAL_CLOSURE",
        "derived_metrics_final_status": "READY_FOR_ARCHITECT_FINAL_CLOSURE_REVIEW" if derived_ready else "BLOCKED_DERIVED_METRICS_FINAL_CLOSURE",
        "final_status": "READY_FOR_ARCHITECT_OPENDART_V01_FINAL_CLOSURE" if final_ready else "BLOCKED_OPENDART_V01_FINAL_CLOSURE",
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "secret_leak_count": secret_count, "raw_source_committed": raw_source,
        "opendart_network_request_count": len(client.audit) if client is not None else 0, "pykrx_krx_network_request_count": 0,
        "git_diff_check_status": "PASS" if subprocess.run(["git", "diff", "--check"], cwd=ROOT, capture_output=True).returncode == 0 else "FAIL",
    }
    _write_json(ARTIFACT_DIR / "final_closure_gate_summary.json", summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir()) if path.name != "final_closure_gate_manifest.json"]
    _write_json(ARTIFACT_DIR / "final_closure_gate_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "files": {path.name: _sha(path) for path in manifest_files},
        "request_accounting": {"opendart": summary["opendart_network_request_count"], "pykrx_krx": 0},
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.", "final_ready": final_ready,
        "final_status": summary["final_status"],
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
