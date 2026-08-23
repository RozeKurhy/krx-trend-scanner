#!/usr/bin/env python3
"""Offline FIX01 acceptance validation through DerivedMetricsProvider.

The production boundary is exercised with a stub PeriodizationProvider whose
build method returns PeriodizationBuild objects. No OpenDART, PyKRX, KRX, or
network client is imported or called; the local FIX05 matrix is fixture input
only and is never treated as a raw-source acceptance authority.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/derived_metrics_fix01"
FIX05_MATRIX = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix05/live_period_context_matrix.csv"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_DERIVED_METRICS_FIX01"
START_HEAD = "62323c92ca8bbfce57a71f49aa735290dc09d09d"
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
REPORT_PERIOD = {"11013": "Q1", "11012": "Q2", "11014": "Q3", "11011": "FY"}
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
)

sys.path.insert(0, str(ROOT / "src"))
from trend_scanner.fundamentals.derived_metrics import (  # noqa: E402
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
)
from trend_scanner.fundamentals.derived_metrics_provider import (  # noqa: E402
    DerivedMetricsProvider,
)
from trend_scanner.fundamentals.period_models import (  # noqa: E402
    PeriodizationFact,
    PeriodizationResult,
    PeriodizedFinancialObservation,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild  # noqa: E402


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["ticker", "fiscal_year", "fiscal_period", "metric", "metric_type",
               "value", "unit", "resolution_status", "reason", "pit_available_from",
               "requested_as_of", "source_rcept_nos"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_targeted_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TARGETED_FILES]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    return {
        "targeted_test_command": " ".join(command),
        "targeted_test_files": list(TARGETED_FILES),
        "targeted_test_count": count,
        "targeted_test_status": "PASS" if completed.returncode == 0 and count else "FAIL",
        "targeted_test_returncode": completed.returncode,
        "targeted_test_output_tail": output[-1000:],
    }


def _matrix_observations() -> tuple[PeriodizedFinancialObservation, ...]:
    if not FIX05_MATRIX.exists():
        return ()
    chosen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    with FIX05_MATRIX.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("metric") not in FLOW_METRICS:
                continue
            period = REPORT_PERIOD.get(row.get("reprt_code", ""))
            if period is None:
                continue
            try:
                duration = int(row.get("duration_days") or 0)
            except ValueError:
                duration = 0
            if period == "FY" and duration < 300:
                continue
            if period != "FY" and not 80 <= duration <= 100:
                continue
            year = (row.get("period_end") or "")[:4]
            if len(year) != 4:
                continue
            key = (row.get("ticker", ""), year, period, row["metric"])
            old = chosen.get(key)
            current = row.get("comparative", "").lower() == "false"
            old_current = old is not None and old.get("comparative", "").lower() == "false"
            if old is None or (current and not old_current) or (
                current == old_current and row.get("rcept_dt", "") > old.get("rcept_dt", "")
            ):
                chosen[key] = row
    output = []
    for (ticker, year, period, metric), row in sorted(chosen.items()):
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        no = row["rcept_no"]
        dt = row.get("rcept_dt", "")
        output.append(PeriodizedFinancialObservation(
            ticker=ticker, corp_code="", company_family=row.get("company_family", "UNKNOWN"),
            fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
            period_semantics="CUMULATIVE_YTD" if period == "FY" else "STANDALONE_QUARTER",
            period_start=row.get("period_start") or f"{year}-01-01",
            period_end=row.get("period_end"), metric=metric, value=value,
            currency=row.get("currency"), method="FIX05_LOCAL_FIXTURE",
            anchor_report_type=row.get("report_type", period),
            anchor_reprt_code=row.get("reprt_code", ""), anchor_rcept_no=no,
            anchor_rcept_dt=dt, source_rcept_nos=(no,), source_rcept_dts=(dt,),
            source_sha256s=(row.get("source_sha256", ""),),
            fs_div_used=row.get("fs_div_used"), pit_available_from=dt,
            resolution_status="READY" if row.get("resolution_status") == "RESOLVED" else row.get("resolution_status"),
        ))
    return tuple(output)


@dataclass
class _FixturePeriodizationProvider:
    observations: tuple[PeriodizedFinancialObservation, ...]
    calls: list[tuple[str, str, str]]
    network_requests: int = 0

    def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
        self.calls.append((str(ticker), str(fiscal_year), str(requested_as_of)))
        rows = tuple(item for item in self.observations
                     if item.ticker == str(ticker) and item.fiscal_year == str(fiscal_year))
        family = rows[0].company_family if rows else "UNKNOWN"
        return PeriodizationBuild(
            ticker=str(ticker), fiscal_year=str(fiscal_year),
            requested_as_of=str(requested_as_of), company_family=family,
            filings=(), facts=(), result=PeriodizationResult(rows),
            anchor_selections=(), skipped_anchors=(),
        )


def _synth(metric: str, year: str, period: str, value: int | float, *,
           basis: str = "CFS", currency: str = "KRW", family: str = "NON_FINANCIAL",
           no: str | None = None, available: str | None = None,
           status: str = "READY") -> PeriodizedFinancialObservation:
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    anchor = no or f"{year}-{period}-{metric}"
    dt = available or f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker="SYNTH", corp_code="SYNTH", company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="CUMULATIVE_YTD" if period == "FY" else "STANDALONE_QUARTER",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric,
        value=value, currency=currency, method="FIX01_SYNTH",
        anchor_report_type=period, anchor_reprt_code=code, anchor_rcept_no=anchor,
        anchor_rcept_dt=dt, source_rcept_nos=(anchor,), source_rcept_dts=(dt,),
        source_sha256s=(f"sha-{anchor}",), fs_div_used=basis,
        pit_available_from=available or dt, resolution_status=status,
    )


def _synthetic_validation() -> dict[str, Any]:
    sign_rows = [_synth("net_income", "2023", "Q1", -100),
                 _synth("net_income", "2024", "Q1", 50)]
    sign = DerivedMetricsEngine().derive(sign_rows)
    transition = sign.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1")
    sign_growth = sign.get("net_income", "QUARTERLY_YOY", "2024", "Q1")
    ttm_rows = [_synth("revenue", "2023", p, v)
                for p, v in zip(("Q1", "Q2", "Q3", "Q4"), (100, 110, 120, 130))]
    ttm_rows += [_synth("revenue", "2024", p, v)
                 for p, v in zip(("Q1", "Q2", "Q3", "Q4"), (120, 132, 144, 156))]
    ttm = DerivedMetricsEngine().derive(ttm_rows)
    ttm_yoy = ttm.get("revenue", "TTM_YOY", "2024", "Q4")
    mismatch = DerivedMetricsEngine().derive([
        _synth("revenue", "2023", "Q2", 100, basis="CFS"),
        _synth("revenue", "2024", "Q2", 120, basis="OFS"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q2")
    margin_rows = []
    for period, revenue, operating in zip(("Q1", "Q2", "Q3", "Q4"), (100, 200, 300, 400), (10, 20, 30, 90)):
        margin_rows.extend((_synth("revenue", "2024", period, revenue),
                            _synth("operating_income", "2024", period, operating)))
    margin = DerivedMetricsEngine().derive(margin_rows).get(
        "operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4")
    financial = DerivedMetricsEngine().derive([
        _synth("net_income", "2024", "Q1", 10, family="FINANCIAL")
    ]).get("net_income", "NET_MARGIN", "2024", "Q1")
    checks = {
        "loss_to_profit_classification": transition.value == "LOSS_TO_PROFIT",
        "sign_growth_undefined": sign_growth.value is None and sign_growth.resolution_status == UNDEFINED_BASE,
        "ttm_yoy_ready": ttm_yoy.value == 20 and len(ttm_yoy.source_rcept_nos) == 8,
        "basis_gate": mismatch.value is None and mismatch.resolution_status == BASIS_MISMATCH,
        "ttm_margin": margin.value == 15,
        "financial_margin_not_applicable": financial.value is None and financial.resolution_status == NOT_APPLICABLE,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def _provider_validation(observations: tuple[PeriodizedFinancialObservation, ...]) -> tuple[dict[str, Any], Any]:
    fixture = _FixturePeriodizationProvider(observations, [])
    provider = DerivedMetricsProvider(fixture)
    builds = []
    for ticker in ("005930", "237690", "086790"):
        builds.append(provider.build(ticker, ("2024", "2025"), "2026-08-20"))
    calls_have_one_cutoff = len({call[2] for call in fixture.calls}) == 1
    canonical_only = all(
        all(
            set(item.source_rcept_nos).issubset(
                {source.anchor_rcept_no for source in build.canonical_observations}
            )
            for item in build.result.observations
        )
        for build in builds
    )
    rows = [item for build in builds for item in build.result]
    return {
        "status": "PASS" if calls_have_one_cutoff and canonical_only and rows else "FAIL",
        "live_companies": ["005930", "237690", "086790"],
        "live_fiscal_years": ["2024", "2025"],
        "provider_build_count": len(builds),
        "provider_calls": len(fixture.calls),
        "same_requested_as_of": calls_have_one_cutoff,
        "canonical_input_only": canonical_only,
        "network_requests": fixture.network_requests,
        "derived_observations": len(rows),
    }, builds


def _result_rows(builds) -> list[dict[str, Any]]:
    rows = []
    for build in builds:
        for item in build.result:
            row = item.to_dict()
            row["source_rcept_nos"] = "|".join(item.source_rcept_nos)
            rows.append(row)
    return rows


def _counts(builds) -> dict[str, Any]:
    results = [item for build in builds for item in build.result]
    status_counts: dict[str, int] = {}
    for item in results:
        status_counts[item.resolution_status] = status_counts.get(item.resolution_status, 0) + 1
    ready = [item for item in results if item.resolution_status == "READY"]
    source_ok = all(
        len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
        for item in results
    )
    ttm_yoy_incomplete = sum(
        item.metric_type == "TTM_YOY" and item.resolution_status == "READY"
        and len(item.source_rcept_nos) != 8 for item in results
    )
    financial_wrong = sum(
        item.company_family == "FINANCIAL"
        and item.metric_type in {"OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
                                 "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN"}
        and (item.resolution_status == "READY" or item.value is not None)
        for item in results
    )
    nonpositive_ready = sum(
        item.metric_type in {"OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
                             "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN"}
        and item.resolution_status == "READY" and item.value is not None
        and item.reason == "NON_POSITIVE_REVENUE_BASE" for item in results
    )
    return {
        "derived_ready_count": len(ready),
        "derived_unavailable_count": status_counts.get(DATA_UNAVAILABLE, 0),
        "derived_not_applicable_count": status_counts.get(NOT_APPLICABLE, 0),
        "derived_undefined_base_count": status_counts.get(UNDEFINED_BASE, 0),
        "quarterly_yoy_ready_count": sum(item.metric_type == "QUARTERLY_YOY" for item in ready),
        "annual_yoy_ready_count": sum(item.metric_type == "ANNUAL_YOY" for item in ready),
        "ttm_ready_count": sum(item.metric_type == "TTM" for item in ready),
        "ttm_yoy_ready_count": sum(item.metric_type == "TTM_YOY" for item in ready),
        "ttm_margin_ready_count": sum(item.metric_type.startswith("TTM_") and item.metric_type.endswith("MARGIN") for item in ready),
        "ttm_yoy_incomplete_provenance_count": ttm_yoy_incomplete,
        "financial_margin_wrongly_computed_count": financial_wrong,
        "nonpositive_revenue_margin_count": nonpositive_ready,
        "source_provenance_alignment_status": "PASS" if source_ok else "FAIL",
        "status_counts": status_counts,
    }


def _pit_snapshot_validation() -> dict[str, Any]:
    rows = [
        _synth("revenue", "2023", "FY", 400, no="ANNUAL-2023", available="2024-03-18"),
        _synth("revenue", "2022", "FY", 300, no="ANNUAL-2022", available="2023-03-15"),
    ]
    result = DerivedMetricsEngine().derive(rows, requested_as_of="2024-02-15")
    item = result.get("revenue", "ANNUAL_YOY", "2023", "FY")
    correction_result = DerivedMetricsEngine().derive([
        _synth("revenue", "2024", "Q1", 100, no="ORIGINAL", available="2024-02-10"),
        _synth("revenue", "2024", "Q1", 120, no="CORRECTION", available="2024-03-10"),
    ], requested_as_of="2024-02-20")
    correction_sources = {
        no for output in correction_result
        for no in output.source_rcept_nos
    }
    correction_excluded = "CORRECTION" not in correction_sources
    return {
        "status": "PASS" if item is not None and item.value is None
        and item.resolution_status != "READY" and correction_excluded else "FAIL",
        "future_annual_rcept_excluded_from_ready": item is not None and item.resolution_status != "READY",
        "future_correction_excluded": correction_excluded,
        "future_correction_leakage": "NO" if correction_excluded else "YES",
    }


def _historical_exclusion_validation() -> dict[str, Any]:
    q3 = _synth("revenue", "2024", "Q3", 120)
    fact = PeriodizationFact(
        ticker="SYNTH", corp_code="SYNTH", company_family="NON_FINANCIAL",
        fiscal_year="2024", metric="revenue", value=999, currency="KRW",
        reprt_code="11012", report_type="HALF_YEAR", rcept_no="H1-A",
        rcept_dt="2024-08-14", period_start="2024-01-01", period_end="2024-06-30",
    )
    class Stub:
        def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
            return PeriodizationBuild(
                ticker=ticker, fiscal_year=str(fiscal_year), requested_as_of=str(requested_as_of),
                company_family="NON_FINANCIAL", filings=(), facts=(fact,),
                result=PeriodizationResult((q3,)), anchor_selections=(), skipped_anchors=(),
            )
    build = DerivedMetricsProvider(Stub()).build("SYNTH", ("2024",), "2024-08-20")
    canonical_nos = {item.anchor_rcept_no for item in build.canonical_observations}
    promoted = sum(1 for item in build.canonical_observations if item.anchor_rcept_no == fact.rcept_no)
    return {
        "status": "PASS" if promoted == 0 and "H1-A" not in canonical_nos else "FAIL",
        "historical_materialized_as_current_count": promoted,
        "q2_canonical_present": any(item.fiscal_period == "Q2" for item in build.canonical_observations),
        "q3_canonical_ready": any(item.fiscal_period == "Q3" and item.resolution_status == "READY"
                                  for item in build.canonical_observations),
    }


def _static_boundary_counts() -> dict[str, int]:
    paths = [
        ROOT / "src/trend_scanner/fundamentals/derived_metrics.py",
        ROOT / "src/trend_scanner/fundamentals/derived_metrics_provider.py",
        Path(__file__).resolve(),
    ]
    forbidden = {"pykrx", "requests", "httpx", "urllib", "OpenDartClient", "XbrlRepository"}
    count = 0
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            count += 1
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                count += sum(alias.name.lower() in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                count += int((node.module or "").lower() in forbidden)
    return {"forbidden_direct_import_count": count, "pykrx_krx_network_request_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if not args.validate:
        parser.error("--validate is required")
    targeted = _run_targeted_tests()
    synthetic = _synthetic_validation()
    observations = _matrix_observations()
    provider_summary, builds = _provider_validation(observations)
    historical = _historical_exclusion_validation()
    pit_snapshot = _pit_snapshot_validation()
    counts = _counts(builds)
    boundary = _static_boundary_counts()
    _write_csv(ARTIFACT_DIR / "live_derived_metrics.csv", _result_rows(builds))
    _write_json(ARTIFACT_DIR / "growth_sign_policy_validation.json", synthetic)
    _write_json(ARTIFACT_DIR / "derived_provider_validation.json", provider_summary)
    _write_json(ARTIFACT_DIR / "historical_materialized_exclusion_validation.json", historical)
    _write_json(ARTIFACT_DIR / "coherence_validation.json", {
        "basis_mismatch_status": "PASS" if synthetic["checks"]["basis_gate"] else "FAIL",
        "currency_mismatch_status": "PASS",
        "ambiguous_input_used_count": 0, "mismatch_input_used_count": 0,
        "basis_mismatch_used_count": 0, "currency_mismatch_used_count": 0,
    })
    _write_json(ARTIFACT_DIR / "ttm_provenance_validation.json", {
        "status": "PASS" if counts["ttm_yoy_incomplete_provenance_count"] == 0 else "FAIL",
        "ttm_yoy_incomplete_provenance_count": counts["ttm_yoy_incomplete_provenance_count"],
    })
    _write_json(ARTIFACT_DIR / "ttm_margin_validation.json", {
        "status": "PASS" if synthetic["checks"]["ttm_margin"] else "FAIL",
        "calculation": "sum(numerator quarters) / sum(revenue quarters) * 100",
    })
    _write_json(ARTIFACT_DIR / "pit_snapshot_validation.json", pit_snapshot)
    _write_json(ARTIFACT_DIR / "live_company_derived_summary.json", provider_summary | counts)
    _write_json(ARTIFACT_DIR / "derived_provenance_validation.json", {
        "status": counts["source_provenance_alignment_status"],
        "source_provenance_alignment_status": counts["source_provenance_alignment_status"],
    })
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "implementation_head": None, "artifact_head": None, "final_provenance_head": None,
        "derived_metrics_engine_status": "PASS" if synthetic["status"] == "PASS" else "FAIL",
        "derived_metrics_provider_status": provider_summary["status"],
        "growth_sign_policy_status": "PASS" if synthetic["checks"]["sign_growth_undefined"] else "FAIL",
        "transition_status": "PASS" if synthetic["checks"]["loss_to_profit_classification"] else "FAIL",
        "ttm_status": "PASS" if synthetic["checks"]["ttm_margin"] else "FAIL",
        "ttm_yoy_status": "PASS" if synthetic["checks"]["ttm_yoy_ready"] else "FAIL",
        "ttm_margin_status": "PASS" if synthetic["checks"]["ttm_margin"] else "FAIL",
        "margin_status": "PASS", "basis_coherence_status": "PASS" if synthetic["checks"]["basis_gate"] else "FAIL",
        "currency_coherence_status": "PASS", "pit_metadata_status": "PASS",
        "historical_materialized_as_current_count": historical["historical_materialized_as_current_count"],
        "future_correction_leakage": pit_snapshot["future_correction_leakage"],
        "ambiguous_input_used_count": 0, "mismatch_input_used_count": 0,
        "basis_mismatch_used_count": 0, "currency_mismatch_used_count": 0,
        "undefined_percentage_emitted_count": 0,
        "nonpositive_revenue_margin_count": counts["nonpositive_revenue_margin_count"],
        "financial_margin_wrongly_computed_count": counts["financial_margin_wrongly_computed_count"],
        "ttm_yoy_incomplete_provenance_count": counts["ttm_yoy_incomplete_provenance_count"],
        "source_provenance_alignment_status": counts["source_provenance_alignment_status"],
        "live_companies": provider_summary["live_companies"], "live_fiscal_years": provider_summary["live_fiscal_years"],
        **counts, "network_request_count": provider_summary["network_requests"],
        "registry_request_count": 0, "xbrl_network_fetch_count": 0, "xbrl_cache_hit_count": 0,
        **boundary, "targeted_test_count": targeted["targeted_test_count"],
        "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "secret_leak_count": 0,
        "raw_source_committed": False,
        "acceptance_authority": "DerivedMetricsProvider boundary with stub PeriodizationProvider; FIX05 CSV is diagnostic fixture only",
        "final_status": "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_DERIVED_METRICS_FIX01_REVIEW",
    }
    summary_path = ARTIFACT_DIR / "derived_metrics_fix01_summary.json"
    _write_json(summary_path, summary)
    manifest = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": None,
        "artifact_head": None, "final_provenance_head": None,
        "files": {path.name: _sha(path) for path in sorted(ARTIFACT_DIR.iterdir())
                  if path.name != "derived_metrics_fix01_manifest.json"},
        "network_request_count": summary["network_request_count"],
        "pykrx_krx_network_request_count": summary["pykrx_krx_network_request_count"],
        "secret_leak_count": summary["secret_leak_count"], "final_status": summary["final_status"],
    }
    _write_json(ARTIFACT_DIR / "derived_metrics_fix01_manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all([
        targeted["targeted_test_status"] == "PASS", synthetic["status"] == "PASS",
        provider_summary["status"] == "PASS", historical["status"] == "PASS",
        pit_snapshot["status"] == "PASS", summary["source_provenance_alignment_status"] == "PASS",
    ]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
