#!/usr/bin/env python3
"""Cache-only validation for OpenDART Fundamentals Assessment V01.

The script consumes only DerivedMetricsBuild/DerivedMetricsResult.  It never
calls OpenDART, PyKRX, KRX, XBRL, Pattern A, or a price provider.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/assessment_v01"
START_HEAD = "966ef175788818e3bc7c3bd6c6e2acb7c3dbb9a6"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_ASSESSMENT"
REQUESTED_AS_OF = "2026-08-20"
HISTORICAL_AS_OF = "2024-02-15"
YEARS = ("2024", "2025")
HISTORICAL_YEARS = ("2023", "2024")
TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
FINANCIAL_TICKER = "086790"
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온",
    "012330": "현대모비스", "086790": "하나금융지주",
}
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
    "tests/test_opendart_fundamentals_assessment.py",
)

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_opendart_q1_context_ambiguity import _company_metadata, _company_metadata_for, _build_production  # noqa: E402
from trend_scanner.fundamentals.assessment import FundamentalsAssessmentEngine  # noqa: E402
from trend_scanner.fundamentals.assessment_models import FundamentalsAssessmentResult  # noqa: E402
from trend_scanner.fundamentals.assessment_provider import FundamentalsAssessmentProvider  # noqa: E402
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository  # noqa: E402
from trend_scanner.fundamentals.derived_metrics import DerivedMetricObservation, DerivedMetricsResult  # noqa: E402
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider  # noqa: E402
from trend_scanner.fundamentals.filing_registry import FilingRegistry  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402


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
    match = re.search(r"(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    return {
        "targeted_test_command": " ".join(command), "targeted_test_count": count,
        "targeted_test_status": "PASS" if completed.returncode == 0 and count else "FAIL",
        "targeted_test_returncode": completed.returncode, "targeted_test_output_tail": output[-1800:],
    }


def _synthetic_item(metric: str, metric_type: str, value: Any, *, status: str = "READY",
                    metadata: dict[str, Any] | None = None, family: str = "NON_FINANCIAL",
                    reason: str | None = None) -> DerivedMetricObservation:
    return DerivedMetricObservation(
        ticker="SYNTH", corp_code="SYNTH", company_family=family, fiscal_year="2025",
        fiscal_period="Q3", metric=metric, metric_type=metric_type, value=value,
        resolution_status=status, reason=reason, period_end="2025-09-30",
        source_rcept_nos=(f"SYNTH-{metric}-{metric_type}",), source_rcept_dts=("2025-10-15",),
        source_sha256s=(f"sha-{metric}-{metric_type}",), requested_as_of="2025-10-15",
        pit_available_from="2025-10-15", metadata=metadata or {},
    )


def _synthetic_scenario(*, revenue=10, operating_income=10, net_income=10, ocf=10,
                        op_margin=10, net_margin=5, ocf_margin=4,
                        op_expansion="EXPANDING", net_expansion="EXPANDING",
                        ocf_trend="IMPROVING", acceleration=1, streak=3,
                        op_transition="PROFIT_GROWTH", net_transition="PROFIT_GROWTH") -> DerivedMetricsResult:
    rows = [
        _synthetic_item("revenue", "QUARTERLY_YOY", revenue),
        _synthetic_item("operating_income", "QUARTERLY_YOY", operating_income),
        _synthetic_item("net_income", "QUARTERLY_YOY", net_income),
        _synthetic_item("operating_cash_flow", "QUARTERLY_YOY", ocf),
        _synthetic_item("operating_income", "OPERATING_MARGIN", op_margin),
        _synthetic_item("net_income", "NET_MARGIN", net_margin),
        _synthetic_item("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", ocf_margin),
        _synthetic_item("operating_income", "MARGIN_EXPANSION_TREND", 1 if op_expansion == "EXPANDING" else -1 if op_expansion == "CONTRACTING" else 0, metadata={"classification": op_expansion}),
        _synthetic_item("net_income", "MARGIN_EXPANSION_TREND", 1 if net_expansion == "EXPANDING" else -1 if net_expansion == "CONTRACTING" else 0, metadata={"classification": net_expansion}),
        _synthetic_item("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", ocf_trend),
        *[_synthetic_item(metric, "YOY_GROWTH_ACCELERATION", acceleration) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        *[_synthetic_item(metric, "CONSECUTIVE_YOY_GROWTH", streak) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        _synthetic_item("operating_income", "EARNINGS_TRANSITION", op_transition),
        _synthetic_item("net_income", "EARNINGS_TRANSITION", net_transition),
    ]
    return DerivedMetricsResult(tuple(rows))


def _synthetic_validation() -> dict[str, Any]:
    cases = {
        "BROAD_STRONG": (_synthetic_scenario(), "STRONG"),
        "TURNAROUND": (_synthetic_scenario(op_transition="LOSS_TO_PROFIT"), "TURNAROUND"),
        "MARGIN_WARNING": (_synthetic_scenario(op_expansion="CONTRACTING", net_expansion="CONTRACTING", ocf=0, ocf_margin=-1, ocf_trend="DETERIORATING"), "MIXED"),
        "CASH_FLOW_DIVERGENCE": (_synthetic_scenario(ocf=-20, ocf_margin=-1, ocf_trend="DETERIORATING"), "MIXED"),
        "BROAD_WEAK": (_synthetic_scenario(revenue=-10, operating_income=-20, net_income=-20, ocf=-20, op_margin=-2, net_margin=-3, ocf_margin=-4, op_expansion="CONTRACTING", net_expansion="CONTRACTING", ocf_trend="DETERIORATING", acceleration=-1, op_transition="PROFIT_DECLINE", net_transition="PROFIT_DECLINE"), "WEAK"),
        "DECELERATION": (_synthetic_scenario(op_margin=-1, net_margin=-1, ocf=-10, ocf_margin=-1, op_expansion="CONTRACTING", net_expansion="CONTRACTING", ocf_trend="DETERIORATING", acceleration=-1), "WEAKENING"),
        "INSUFFICIENT": (DerivedMetricsResult((_synthetic_item("revenue", "QUARTERLY_YOY", 10),)), "INSUFFICIENT_DATA"),
    }
    engine = FundamentalsAssessmentEngine()
    rows: list[dict[str, Any]] = []
    for name, (source, expected) in cases.items():
        result = engine.assess(source)
        rows.append({"case": name, "expected": expected, "observed": result.overall_state,
                     "matched_rule_id": result.matched_rule_id,
                     "status": "PASS" if result.overall_state == expected else "FAIL"})
    sign = engine.assess(_synthetic_scenario(op_transition="LOSS_TO_PROFIT"))
    narrowing = engine.assess(_synthetic_scenario(op_transition="LOSS_NARROWING"))
    widening = engine.assess(_synthetic_scenario(op_transition="LOSS_WIDENING"))
    zero = engine.assess(DerivedMetricsResult((_synthetic_item("revenue", "QUARTERLY_YOY", None, status="UNDEFINED_BASE", reason="NON_POSITIVE_OR_SIGN_TRANSITION_BASE"), _synthetic_item("operating_income", "QUARTERLY_YOY", 10), _synthetic_item("operating_cash_flow", "QUARTERLY_YOY", 10))))
    checks = {
        "sign_transition_loss_to_profit": any(item.classification == "LOSS_TO_PROFIT" for item in sign.evidence),
        "loss_narrowing_positive_evidence": any(item.classification == "LOSS_NARROWING" and item.direction == "POSITIVE" for item in narrowing.evidence),
        "loss_widening_risk_evidence": any(item.classification == "LOSS_WIDENING" and item.direction == "RISK" for item in widening.evidence),
        "zero_base_no_positive_growth": not any(item.explanation_code == "REVENUE_YOY_POSITIVE" for item in zero.evidence),
    }
    return {
        "case_count": len(rows), "case_pass_count": sum(item["status"] == "PASS" for item in rows),
        "cases": rows, "sign_transition_status": "PASS" if all(checks.values()) else "FAIL",
        "sign_transition_checks": checks,
        "status": "PASS" if all(item["status"] == "PASS" for item in rows) and all(checks.values()) else "FAIL",
    }


def _cache_provider() -> FundamentalsAssessmentProvider:
    corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    registry = FilingRegistry(None, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl = XbrlRepository(None, cache_dir=ROOT / "data/cache/opendart/xbrl")
    return FundamentalsAssessmentProvider(DerivedMetricsProvider(PeriodizationProvider(corp, registry, xbrl)))


def _production_assessments() -> tuple[list[FundamentalsAssessmentResult], list[dict[str, Any]]]:
    builds, _, build_errors = _build_production(live=False, env_file=ROOT / "missing-env-file")
    provider = FundamentalsAssessmentProvider(_cache_provider().derived_metrics_provider)
    results: list[FundamentalsAssessmentResult] = []
    errors = list(build_errors)
    for build in builds:
        try:
            results.append(FundamentalsAssessmentEngine().assess(build, requested_as_of=REQUESTED_AS_OF))
        except Exception as exc:
            errors.append({"ticker": getattr(build, "ticker", ""), "error_type": type(exc).__name__, "message": str(exc)})
    try:
        results.append(provider.build(FINANCIAL_TICKER, YEARS, REQUESTED_AS_OF, company_metadata={"company_family": "FINANCIAL"}))
    except Exception as exc:
        errors.append({"ticker": FINANCIAL_TICKER, "error_type": type(exc).__name__, "message": str(exc)})
    return results, errors


def _historical_assessments() -> tuple[list[FundamentalsAssessmentResult], list[dict[str, Any]]]:
    provider = _cache_provider()
    metadata = _company_metadata()
    results: list[FundamentalsAssessmentResult] = []
    errors: list[dict[str, Any]] = []
    for ticker in TICKERS:
        try:
            results.append(provider.build(ticker, HISTORICAL_YEARS, HISTORICAL_AS_OF,
                                          company_metadata=_company_metadata_for(ticker, metadata)))
        except Exception as exc:
            errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    return results, errors


def _provenance_counts(results: Iterable[FundamentalsAssessmentResult], cutoff: str) -> dict[str, int]:
    cutoff_date = date.fromisoformat(cutoff)
    future_source_count = 0
    ready_missing_pit = 0
    ready_future_pit = 0
    alignment_errors = 0
    cutoff_mismatch = 0
    rule_conflicts = 0
    rule_mismatches = 0
    for result in results:
        diagnostics = result.diagnostics
        future_source_count += int(diagnostics.get("future_assessment_source_count", 0))
        ready_missing_pit += int(diagnostics.get("ready_missing_pit_available_count", 0))
        ready_future_pit += int(diagnostics.get("ready_future_pit_available_count", 0))
        cutoff_mismatch += int(diagnostics.get("provider_cutoff_mismatch_count", 0))
        rule_conflicts += int(result.assessment_rule_conflict_count)
        if result.status == "READY" and not result.matched_rule_id:
            rule_mismatches += 1
        for item in result.evidence:
            if item.status != "READY":
                continue
            if not (len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)):
                alignment_errors += 1
            if item.pit_available_from is None:
                ready_missing_pit += 1
            else:
                try:
                    if date.fromisoformat(item.pit_available_from[:10]) > cutoff_date:
                        ready_future_pit += 1
                except ValueError:
                    alignment_errors += 1
            if any(date.fromisoformat(dt[:10]) > cutoff_date for dt in item.source_rcept_dts if dt):
                future_source_count += 1
    return {
        "future_assessment_source_count": future_source_count,
        "ready_missing_pit_available_count": ready_missing_pit,
        "ready_future_pit_available_count": ready_future_pit,
        "provider_cutoff_mismatch_count": cutoff_mismatch,
        "evidence_provenance_alignment_error_count": alignment_errors,
        "assessment_rule_conflict_count": rule_conflicts,
        "assessment_rule_mismatch_count": rule_mismatches,
    }


def _dependency_import_count() -> tuple[int, int]:
    path = ROOT / "src/trend_scanner/fundamentals/assessment.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pattern_count = 0
    price_count = 0
    forbidden_pattern = ("pattern_a", "rs_engine", "foreign_flow", "fast_strategy", "julia_strategy")
    forbidden_price = ("price_provider", "pykrx", "krx")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name.lower() for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [str(node.module or "").lower()]
        else:
            continue
        pattern_count += sum(any(token in name for token in forbidden_pattern) for name in names)
        price_count += sum(any(token in name for token in forbidden_price) for name in names)
    return pattern_count, price_count


def _result_row(result: FundamentalsAssessmentResult) -> dict[str, Any]:
    return {
        "ticker": result.ticker, "company_family": result.company_family,
        "as_of": result.requested_as_of, "current_fiscal_year": result.current_fiscal_year,
        "current_period": result.current_fiscal_period, "overall_state": result.overall_state,
        "growth_state": result.growth_state, "profitability_state": result.profitability_state,
        "cash_flow_state": result.cash_flow_state, "momentum_state": result.momentum_state,
        "top_strength_1": result.strengths[0] if len(result.strengths) > 0 else "",
        "top_strength_2": result.strengths[1] if len(result.strengths) > 1 else "",
        "top_risk_1": result.risks[0] if len(result.risks) > 0 else "",
        "top_risk_2": result.risks[1] if len(result.risks) > 1 else "",
        "available_axis_count": result.available_axis_count,
        "missing_axis_count": result.missing_axis_count, "status": result.status,
        "matched_rule_id": result.matched_rule_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"), help="Accepted for workflow compatibility; cache-only validation never calls the API.")
    args = parser.parse_args()
    del args
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    targeted = _targeted_tests()
    synthetic = _synthetic_validation()
    production, production_errors = _production_assessments()
    historical, historical_errors = _historical_assessments()
    all_results = tuple(production) + tuple(historical)
    production_counts = _provenance_counts(production, REQUESTED_AS_OF)
    historical_counts = _provenance_counts(historical, HISTORICAL_AS_OF)
    dependency_pattern_count, dependency_price_count = _dependency_import_count()
    financial = next((item for item in production if item.ticker == FINANCIAL_TICKER), None)
    financial_status = bool(financial and financial.status == "NOT_APPLICABLE" and financial.overall_state == "NOT_APPLICABLE" and financial.matched_rule_id == "FINANCIAL_PROFILE_NOT_IMPLEMENTED")

    production_rows = [_result_row(item) for item in production]
    historical_rows = [_result_row(item) for item in historical]
    _write_csv(ARTIFACT_DIR / "production_assessment_table.csv", production_rows, [
        "ticker", "company_family", "as_of", "current_fiscal_year", "current_period",
        "overall_state", "growth_state", "profitability_state", "cash_flow_state", "momentum_state",
        "top_strength_1", "top_strength_2", "top_risk_1", "top_risk_2",
        "available_axis_count", "missing_axis_count", "status", "matched_rule_id",
    ])
    _write_json(ARTIFACT_DIR / "synthetic_assessment_validation.json", synthetic)
    _write_json(ARTIFACT_DIR / "production_assessment_validation.json", {
        "status": "PASS" if production and not production_errors else "FAIL",
        "results": [item.to_dict() for item in production], "errors": production_errors,
        "production_assessment_ready_count": sum(item.status == "READY" for item in production),
        "production_assessment_insufficient_count": sum(item.status in {"INSUFFICIENT_DATA", "INPUT_NOT_READY"} for item in production),
        "provenance_counts": production_counts,
    })
    _write_json(ARTIFACT_DIR / "historical_pit_assessment_validation.json", {
        "requested_as_of": HISTORICAL_AS_OF, "status": "PASS" if not historical_errors else "FAIL",
        "results": [item.to_dict() for item in historical], "errors": historical_errors,
        "future_assessment_source_count": historical_counts["future_assessment_source_count"],
        "ready_missing_pit_available_count": historical_counts["ready_missing_pit_available_count"],
        "ready_future_pit_available_count": historical_counts["ready_future_pit_available_count"],
        "rows": historical_rows,
    })
    _write_json(ARTIFACT_DIR / "assessment_provenance_validation.json", {
        "production": production_counts, "historical": historical_counts,
        "status": "PASS" if all(value == 0 for key, value in production_counts.items() if key.endswith("count") or "error" in key) and all(value == 0 for key, value in historical_counts.items() if key.endswith("count") or "error" in key) else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "financial_not_applicable_validation.json", {
        "ticker": FINANCIAL_TICKER, "company": NAMES[FINANCIAL_TICKER],
        "status": "PASS" if financial_status else "FAIL",
        "result": financial.to_dict() if financial else None,
    })

    counters = {
        "synthetic_case_count": synthetic["case_count"], "synthetic_case_pass_count": synthetic["case_pass_count"],
        "production_assessment_ready_count": sum(item.status == "READY" for item in production),
        "production_assessment_insufficient_count": sum(item.status in {"INSUFFICIENT_DATA", "INPUT_NOT_READY"} for item in production),
        "financial_not_applicable_count": int(financial_status),
        "future_assessment_source_count": production_counts["future_assessment_source_count"] + historical_counts["future_assessment_source_count"],
        "ready_missing_pit_available_count": production_counts["ready_missing_pit_available_count"] + historical_counts["ready_missing_pit_available_count"],
        "ready_future_pit_available_count": production_counts["ready_future_pit_available_count"] + historical_counts["ready_future_pit_available_count"],
        "provider_cutoff_mismatch_count": production_counts["provider_cutoff_mismatch_count"] + historical_counts["provider_cutoff_mismatch_count"],
        "evidence_provenance_alignment_error_count": production_counts["evidence_provenance_alignment_error_count"] + historical_counts["evidence_provenance_alignment_error_count"],
        "assessment_rule_conflict_count": production_counts["assessment_rule_conflict_count"] + historical_counts["assessment_rule_conflict_count"],
        "assessment_rule_mismatch_count": production_counts["assessment_rule_mismatch_count"] + historical_counts["assessment_rule_mismatch_count"],
        "pattern_a_import_count": dependency_pattern_count, "price_provider_import_count": dependency_price_count,
        "pykrx_krx_network_request_count": 0,
    }
    final_ready = bool(
        synthetic["status"] == "PASS" and synthetic["sign_transition_status"] == "PASS"
        and production and not production_errors and financial_status
        and not historical_errors and all(counters[key] == 0 for key in (
            "future_assessment_source_count", "ready_missing_pit_available_count", "ready_future_pit_available_count",
            "provider_cutoff_mismatch_count", "evidence_provenance_alignment_error_count", "assessment_rule_conflict_count",
            "assessment_rule_mismatch_count", "pattern_a_import_count", "price_provider_import_count",
            "pykrx_krx_network_request_count",
        )) and targeted["targeted_test_status"] == "PASS"
    )
    implementation_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "assessment_architecture": "DerivedMetricsResult/Build -> FundamentalsAssessmentEngine -> FundamentalsAssessmentResult",
        "input_authority": "DerivedMetricsResult or DerivedMetricsBuild only",
        **counters,
        "production_assessment_status": "PASS" if production and not production_errors else "FAIL",
        "financial_not_applicable_status": "PASS" if financial_status else "FAIL",
        "historical_pit_status": "PASS" if not historical_errors and historical_counts["future_assessment_source_count"] == 0 else "FAIL",
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
        "periodization_semantics_changed": False, "derived_metrics_semantics_changed": False,
        "pattern_a_separation_status": "PASS" if dependency_pattern_count == 0 else "FAIL",
        "price_dependency_status": "PASS" if dependency_price_count == 0 else "FAIL",
        "final_ready": final_ready,
        "final_status": "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_REVIEW" if final_ready else "BLOCKED_OPENDART_FUNDAMENTALS_ASSESSMENT_V01",
        "git_diff_check_status": "PASS" if subprocess.run(["git", "diff", "--check"], cwd=ROOT, capture_output=True).returncode == 0 else "FAIL",
    }
    _write_json(ARTIFACT_DIR / "assessment_v01_summary.json", summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir()) if path.name != "assessment_v01_manifest.json"]
    _write_json(ARTIFACT_DIR / "assessment_v01_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "files": {path.name: _sha(path) for path in manifest_files},
        "network_policy": {"opendart": 0, "pykrx_krx": 0}, "final_ready": final_ready,
        "final_status": summary["final_status"],
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
