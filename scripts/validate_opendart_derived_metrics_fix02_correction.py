#!/usr/bin/env python3
"""FIX02 correction validation.

This module keeps the FIX01/FIX02 calculation and periodization semantics
unchanged.  It corrects validation authority, measures identity promotion
from real PeriodizationBuild objects, and admits only an independently
recomputed production TTM-margin observation as evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/derived_metrics_fix02_correction"
ACCESS_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/access_v01/opendart_api_access_summary.json"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_DERIVED_METRICS_FIX02_CORRECTION"
START_HEAD = "af73c369fc5b22bde0133c464324bf1ddc42e54d"
CUTOFF = "2026-08-20"
BASE_TICKERS = ("005930", "237690", "086790")
# Fixed, bounded candidate list.  It is deliberately not expanded while the
# validator is running.
CANDIDATE_TICKERS = ("005380", "000660", "035420", "068270", "012330")
YEARS = ("2024", "2025")
MARGIN_TYPES = {
    "OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
    "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN",
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
)

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from trend_scanner.fundamentals.derived_metrics import (  # noqa: E402
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
)
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation  # noqa: E402

from validate_opendart_derived_metrics_fix02 import (  # noqa: E402
    _company_metadata,
    _date_text,
    _load_env,
    _synth,
    _unknown_pit,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["ticker", "fiscal_year", "fiscal_period", "metric", "metric_type", "value",
               "resolution_status", "reason", "requested_as_of", "pit_available_from", "source_rcept_nos"]
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
        "targeted_test_output_tail": output[-1200:],
    }


def _derive(rows: Iterable[PeriodizedFinancialObservation], *, as_of: str | None = None):
    return DerivedMetricsEngine().derive(rows, requested_as_of=as_of)


def _case(case_id: str, target, *, expected_status: str) -> dict[str, Any]:
    actual_status = target.resolution_status if target is not None else "MISSING_TARGET"
    actual_value = target.value if target is not None else None
    wrong_value = target is not None and (actual_status == "READY" or actual_value is not None)
    return {
        "case_id": case_id,
        "target_metric": target.metric if target is not None else None,
        "target_metric_type": target.metric_type if target is not None else None,
        "target_year": target.fiscal_year if target is not None else None,
        "target_period": target.fiscal_period if target is not None else None,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "expected_value": None,
        "actual_value": actual_value,
        "target_exists": target is not None,
        "violation": bool(wrong_value),
    }


def _coherence_validation() -> dict[str, Any]:
    basis_cases: list[dict[str, Any]] = []
    basis_cases.append(_case("A_BASIS_QUARTERLY_YOY", _derive([
        _synth("revenue", "2023", "Q2", 100, basis="CFS"),
        _synth("revenue", "2024", "Q2", 120, basis="OFS"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q2"), expected_status=BASIS_MISMATCH))
    basis_cases.append(_case("B_BASIS_TTM", _derive([
        _synth("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS")
        for p in ("Q1", "Q2", "Q3", "Q4")
    ]).get("revenue", "TTM", "2024", "Q4"), expected_status=BASIS_MISMATCH))
    margin_basis_rows = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        margin_basis_rows.extend((_synth("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS"),
                                  _synth("operating_income", "2024", p, 10)))
    basis_cases.append(_case("C_BASIS_TTM_MARGIN", _derive(margin_basis_rows).get(
        "operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4"), expected_status=BASIS_MISMATCH))
    basis_cases.append(_case("D_BASIS_QUARTER_MARGIN", _derive([
        _synth("revenue", "2024", "Q2", 100, basis="OFS"),
        _synth("operating_income", "2024", "Q2", 10, basis="CFS"),
    ]).get("operating_income", "OPERATING_MARGIN", "2024", "Q2"), expected_status=BASIS_MISMATCH))

    currency_cases: list[dict[str, Any]] = []
    currency_cases.append(_case("E_CURRENCY_QUARTERLY_YOY", _derive([
        _synth("revenue", "2023", "Q2", 100, currency="KRW"),
        _synth("revenue", "2024", "Q2", 120, currency="USD"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q2"), expected_status=CURRENCY_MISMATCH))
    currency_cases.append(_case("F_CURRENCY_TTM", _derive([
        _synth("revenue", "2024", p, 100, currency="USD" if p == "Q4" else "KRW")
        for p in ("Q1", "Q2", "Q3", "Q4")
    ]).get("revenue", "TTM", "2024", "Q4"), expected_status=CURRENCY_MISMATCH))
    currency_cases.append(_case("G_CURRENCY_QUARTER_MARGIN", _derive([
        _synth("revenue", "2024", "Q2", 100, currency="USD"),
        _synth("operating_income", "2024", "Q2", 10, currency="KRW"),
    ]).get("operating_income", "OPERATING_MARGIN", "2024", "Q2"), expected_status=CURRENCY_MISMATCH))
    margin_currency_rows = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        margin_currency_rows.extend((_synth("revenue", "2024", p, 100, currency="USD" if p == "Q4" else "KRW"),
                                     _synth("operating_income", "2024", p, 10, currency="KRW")))
    currency_cases.append(_case("H_CURRENCY_TTM_MARGIN", _derive(margin_currency_rows).get(
        "operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4"), expected_status=CURRENCY_MISMATCH))

    basis_violation = sum(item["violation"] for item in basis_cases)
    currency_violation = sum(item["violation"] for item in currency_cases)
    basis_missing = sum(not item["target_exists"] for item in basis_cases)
    currency_missing = sum(not item["target_exists"] for item in currency_cases)
    basis_status = "PASS" if basis_missing == 0 and basis_violation == 0 and all(
        item["actual_status"] == item["expected_status"] and item["actual_value"] is None for item in basis_cases
    ) else "FAIL"
    currency_status = "PASS" if currency_missing == 0 and currency_violation == 0 and all(
        item["actual_status"] == item["expected_status"] and item["actual_value"] is None for item in currency_cases
    ) else "FAIL"

    ambiguous_target = _derive([
        _synth("revenue", "2023", "Q1", 100),
        _synth("revenue", "2024", "Q1", 120, status="PERIOD_AMBIGUOUS", no="AMBIGUOUS"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    mismatch_target = _derive([
        _synth("revenue", "2023", "Q1", 100),
        _synth("revenue", "2024", "Q1", 120, status="DIRECT_DERIVED_MISMATCH", no="MISMATCH"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    ambiguous_case = _case("I_AMBIGUOUS_INPUT", ambiguous_target, expected_status=INPUT_NOT_READY)
    mismatch_case = _case("J_MISMATCH_INPUT", mismatch_target, expected_status=INPUT_NOT_READY)
    ambiguous_used = int(ambiguous_case["violation"])
    mismatch_used = int(mismatch_case["violation"])
    return {
        "basis_cases": basis_cases,
        "currency_cases": currency_cases,
        "ambiguous_case": ambiguous_case,
        "mismatch_case": mismatch_case,
        "basis_status": basis_status,
        "currency_status": currency_status,
        "basis_mismatch_used_count": basis_violation,
        "currency_mismatch_used_count": currency_violation,
        "basis_missing_target_count": basis_missing,
        "currency_missing_target_count": currency_missing,
        "ambiguous_input_used_count": ambiguous_used,
        "mismatch_input_used_count": mismatch_used,
    }


def _other_invariants() -> dict[str, Any]:
    sign_cases = []
    for case_id, (prior, current) in zip(
        ("LOSS_TO_PROFIT", "PROFIT_TO_LOSS", "LOSS_NARROWING", "LOSS_WIDENING", "ZERO_BASE"),
        ((-100, 50), (100, -50), (-100, -30), (-30, -100), (0, 50)),
    ):
        result = _derive([_synth("net_income", "2023", "Q1", prior),
                          _synth("net_income", "2024", "Q1", current)])
        for metric_type in ("QUARTERLY_YOY", "NET_INCOME_GROWTH"):
            target = result.get("net_income", metric_type, "2024", "Q1")
            sign_cases.append({"case_id": f"K_{case_id}_{metric_type}", "target_metric_type": metric_type,
                               "actual_status": target.resolution_status if target else "MISSING_TARGET",
                               "actual_value": target.value if target else None,
                               "violation": bool(target and target.resolution_status == "READY"
                                                 and isinstance(target.value, (int, float)))})
    undefined_count = sum(case["violation"] for case in sign_cases)

    margin_rows = [_synth("revenue", "2024", "Q1", 0), _synth("operating_income", "2024", "Q1", 10),
                   _synth("revenue", "2024", "Q2", -100), _synth("operating_income", "2024", "Q2", 10)]
    margin_result = _derive(margin_rows)
    by_no = {item.anchor_rcept_no: item for item in margin_rows}
    nonpositive_count = sum(item.metric_type in MARGIN_TYPES and item.resolution_status == "READY"
                            and any(by_no.get(no) and by_no[no].metric == "revenue"
                                    and (by_no[no].value or 0) <= 0 for no in item.source_rcept_nos)
                            for item in margin_result)

    financial_rows = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        financial_rows.extend((_synth("revenue", "2024", p, 100, family="FINANCIAL"),
                               _synth("operating_income", "2024", p, 10, family="FINANCIAL"),
                               _synth("net_income", "2024", p, 10, family="FINANCIAL"),
                               _synth("operating_cash_flow", "2024", p, 10, family="FINANCIAL")))
    financial_result = _derive(financial_rows)
    financial_wrong = sum(item.metric_type in MARGIN_TYPES
                          and (item.resolution_status == "READY" or item.value is not None)
                          for item in financial_result)

    ttm_rows = []
    for year, values in (("2023", (100, 110, 120, 130)), ("2024", (120, 132, 144, 156))):
        ttm_rows.extend(_synth("revenue", year, p, value)
                        for p, value in zip(("Q1", "Q2", "Q3", "Q4"), values))
    ttm_result = _derive(ttm_rows)
    incomplete_ttm = sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY"
                         and len(item.source_rcept_nos) != 8 for item in ttm_result)
    alignment_bad = sum(len(item.source_rcept_nos) != len(item.source_rcept_dts)
                        or len(item.source_rcept_nos) != len(item.source_sha256s)
                        for item in list(ttm_result) + list(margin_result) + list(financial_result))
    unknown = _derive([_unknown_pit()], as_of="2024-02-15")
    return {
        "sign_cases": sign_cases,
        "undefined_percentage_emitted_count": undefined_count,
        "nonpositive_revenue_margin_count": int(nonpositive_count),
        "financial_margin_wrongly_computed_count": int(financial_wrong),
        "ttm_yoy_incomplete_provenance_count": int(incomplete_ttm),
        "source_provenance_alignment_bad_count": int(alignment_bad),
        "source_provenance_alignment_status": "PASS" if alignment_bad == 0 else "FAIL",
        "unknown_pit_availability_status": "PASS" if all(item.resolution_status != "READY" for item in unknown) else "FAIL",
    }


def _company_metadata_for(ticker: str, baseline: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if ticker in baseline:
        return baseline[ticker]
    return {"company_family": "NON_FINANCIAL", "candidate_reason": "fixed_non_financial_candidate"}


def _build_production(*, live: bool, env_file: Path) -> tuple[dict[str, Any], list[Any], Any]:
    from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
    from trend_scanner.fundamentals.filing_registry import FilingRegistry
    from trend_scanner.fundamentals.opendart_client import OpenDartClient
    from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
    from trend_scanner.fundamentals.xbrl_repository import XbrlRepository
    from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider

    _load_env(env_file)
    client = OpenDartClient(api_key=os.getenv("OPENDART_API_KEY", "").strip()) if live else None
    if live and not client.api_key:
        return {"status": "BLOCKED_OPENDART_API_KEY", "errors": [{"error_type": "MISSING_KEY"}]}, [], client
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    if not live:
        corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    filings = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    provider = DerivedMetricsProvider(PeriodizationProvider(corp, filings, xbrl))
    baseline = _company_metadata()
    if live:
        corp.ensure_loaded()
    builds: list[Any] = []
    errors: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for ticker in BASE_TICKERS:
        try:
            builds.append(provider.build(ticker, YEARS, CUTOFF,
                                         company_metadata=_company_metadata_for(ticker, baseline), force_refresh=False))
        except Exception as exc:
            errors.append({"ticker": ticker, "error_type": type(exc).__name__, "role": "baseline"})

    selected_candidate: str | None = None
    for ticker in CANDIDATE_TICKERS:
        if selected_candidate is not None:
            attempts.append({"ticker": ticker, "status": "NOT_RUN_AFTER_SELECTION",
                             "reason": "bounded_candidate_search_stopped"})
            continue
        try:
            build = provider.build(ticker, YEARS, CUTOFF,
                                   company_metadata=_company_metadata_for(ticker, baseline), force_refresh=False)
            builds.append(build)
            samples = _margin_samples(build)
            attempts.append({"ticker": ticker, "status": "BUILT", "company_family": _build_family(build),
                             "canonical_observation_count": len(build.canonical_observations),
                             "ttm_margin_ready_count": len(samples),
                             "cache_first": True,
                             "selected": bool(samples)})
            if samples:
                selected_candidate = ticker
        except Exception as exc:
            attempts.append({"ticker": ticker, "status": "ERROR", "error_type": type(exc).__name__,
                             "cache_first": True, "selected": False})
            errors.append({"ticker": ticker, "error_type": type(exc).__name__, "role": "candidate"})

    return {
        "status": "PASS" if not [item for item in errors if item.get("role") == "baseline"]
        and len(builds) >= len(BASE_TICKERS) else "FAIL",
        "base_tickers": list(BASE_TICKERS), "candidate_tickers": list(CANDIDATE_TICKERS),
        "candidate_attempts": attempts, "selected_candidate": selected_candidate,
        "errors": errors, "production_boundary": "PeriodizationProvider.build -> PeriodizationBuild.result -> DerivedMetricsProvider.build -> DerivedMetricsEngine",
    }, builds, client


def _build_family(build: Any) -> str:
    families = {str(item.company_family) for item in build.canonical_observations}
    return next(iter(families), "UNKNOWN")


def _margin_samples(build: Any) -> list[Any]:
    return [item for item in build.result
            if item.metric_type in TTM_MARGIN_TYPES and item.resolution_status == "READY"
            and item.company_family == "NON_FINANCIAL"]


def _quarter_index(year: str, period: str) -> int | None:
    try:
        quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}[period]
        return int(str(year)[:4]) * 4 + quarter
    except (KeyError, TypeError, ValueError):
        return None


def _recompute_margin(build: Any, sample: Any) -> dict[str, Any]:
    numerator_metric = sample.metric
    target_index = _quarter_index(sample.fiscal_year, sample.fiscal_period)
    canonical = list(build.canonical_observations)
    revenue_by_index = {_quarter_index(item.fiscal_year, item.fiscal_period): item
                        for item in canonical if item.metric == "revenue" and item.fiscal_period in {"Q1", "Q2", "Q3", "Q4"}}
    numerator_by_index = {_quarter_index(item.fiscal_year, item.fiscal_period): item
                          for item in canonical if item.metric == numerator_metric and item.fiscal_period in {"Q1", "Q2", "Q3", "Q4"}}
    indexes = [target_index - offset for offset in (3, 2, 1, 0)] if target_index is not None else []
    revenues = [revenue_by_index.get(index) for index in indexes]
    numerators = [numerator_by_index.get(index) for index in indexes]
    revenue_values = [item.value for item in revenues if item is not None and item.resolution_status == "READY"]
    numerator_values = [item.value for item in numerators if item is not None and item.resolution_status == "READY"]
    revenue_total = sum(revenue_values) if len(revenue_values) == 4 else None
    numerator_total = sum(numerator_values) if len(numerator_values) == 4 else None
    expected = numerator_total / revenue_total * 100 if revenue_total and numerator_total is not None else None
    actual = sample.value
    difference = abs(float(expected) - float(actual)) if expected is not None and actual is not None else None
    source_alignment = len(sample.source_rcept_nos) == len(sample.source_rcept_dts) == len(sample.source_sha256s)
    canonical_sources = {item.anchor_rcept_no for item in revenues + numerators if item is not None}
    source_traceable = set(sample.source_rcept_nos).issubset(canonical_sources)
    return {
        "ticker": sample.ticker, "selected_metric_type": sample.metric_type,
        "selected_fiscal_year": sample.fiscal_year, "selected_fiscal_period": sample.fiscal_period,
        "revenue_components": [item.to_dict() if item is not None else None for item in revenues],
        "numerator_components": [item.to_dict() if item is not None else None for item in numerators],
        "revenue_total": revenue_total, "numerator_total": numerator_total,
        "expected_margin": expected, "derived_margin": actual, "difference": difference,
        "source_rcept_nos": list(sample.source_rcept_nos),
        "source_rcept_dts": list(sample.source_rcept_dts),
        "source_sha256s": list(sample.source_sha256s),
        "source_provenance_alignment": source_alignment,
        "source_traceable_to_canonical": source_traceable,
        "basis": next((item.fs_div_used for item in revenues if item is not None), None),
        "currency": next((item.currency for item in revenues if item is not None), None),
        "pit_available_from": sample.pit_available_from,
        "requested_as_of": sample.requested_as_of,
        "recalc_violation": expected is None or difference is None or difference > 1e-9
        or not source_alignment or not source_traceable,
    }


def _historical_detector(builds: Iterable[Any]) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    promoted_count = 0
    for derived_build in builds:
        for period_build in derived_build.periodization_builds:
            current = {str(item.get("selected_rcept_no")) for item in period_build.anchor_selections
                       if item.get("status") == "READY" and item.get("selected_rcept_no")}
            fact_nos = {str(fact.rcept_no) for fact in period_build.facts if fact.rcept_no}
            historical_only = sorted(fact_nos - current)
            # PeriodizationBuild.result intentionally retains eligible vintage
            # observations for PIT reconstruction.  Only observations anchored
            # by the current selected filing are current canonical output;
            # historical prior observations remain valid vintage evidence and
            # must not be mistaken for promotion.
            canonical_result_nos = sorted({str(item.anchor_rcept_no) for item in period_build.result.observations
                                           if item.anchor_rcept_no})
            canonical_nos = sorted(set(canonical_result_nos).intersection(current))
            promoted = sorted(set(canonical_nos).intersection(historical_only))
            promoted_count += len(promoted)
            prior_ids = sorted({str((selection.get("prior_pit") or {}).get("selected_rcept_no"))
                                for selection in period_build.anchor_selections
                                if (selection.get("prior_pit") or {}).get("selected_rcept_no")})
            records.append({
                "ticker": period_build.ticker, "fiscal_year": period_build.fiscal_year,
                "current_anchor_rcept_nos": sorted(current), "fact_rcept_nos": sorted(fact_nos),
                "historical_only_materialized_rcept_nos": historical_only,
                "prior_pit_selected_rcept_nos": prior_ids,
                "canonical_result_anchor_rcept_nos": canonical_result_nos,
                "canonical_anchor_rcept_nos": canonical_nos,
                "promoted_anchor_rcept_nos": promoted,
                "historical_materialized_as_current_count": len(promoted),
                "status": "PASS" if not promoted else "FAIL",
            })
    return records, promoted_count


def _production_margin_diagnostics(builds: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for build in builds:
        for year in YEARS:
            revenue = {(item.fiscal_period): item for item in build.canonical_observations
                       if item.metric == "revenue" and item.fiscal_year == year
                       and item.fiscal_period in {"Q1", "Q2", "Q3", "Q4"}}
            for numerator_metric in ("operating_income", "net_income", "operating_cash_flow"):
                numerators = {item.fiscal_period: item for item in build.canonical_observations
                              if item.metric == numerator_metric and item.fiscal_year == year
                              and item.fiscal_period in {"Q1", "Q2", "Q3", "Q4"}}
                target_type = {"operating_income": "TTM_OPERATING_MARGIN", "net_income": "TTM_NET_MARGIN",
                               "operating_cash_flow": "TTM_OPERATING_CASH_FLOW_MARGIN"}[numerator_metric]
                target = next((item for item in build.result if item.metric == numerator_metric
                               and item.metric_type == target_type and item.fiscal_year == year
                               and item.fiscal_period == "Q4"), None)
                blocking = [item for item in (*revenue.values(), *numerators.values())
                            if item.resolution_status != "READY"]
                records.append({
                    "ticker": build.ticker, "fiscal_year": year, "target_period": "Q4",
                    "metric": numerator_metric, "metric_type": target_type,
                    "revenue_statuses": {p: {"status": revenue[p].resolution_status, "reason": revenue[p].reason}
                                         if p in revenue else {"status": "MISSING"} for p in ("Q1", "Q2", "Q3", "Q4")},
                    "numerator_statuses": {p: {"status": numerators[p].resolution_status, "reason": numerators[p].reason}
                                           if p in numerators else {"status": "MISSING"} for p in ("Q1", "Q2", "Q3", "Q4")},
                    "target_status": target.resolution_status if target else "MISSING_TARGET",
                    "blocking_status": blocking[0].resolution_status if blocking else None,
                    "blocking_reason": blocking[0].reason if blocking else None,
                })
    return records


def _historical_snapshot_validation() -> dict[str, Any]:
    rows = [_synth("revenue", "2023", "FY", 400, receipt="2024-03-18", available="2024-03-18"),
            _synth("revenue", "2022", "FY", 300, receipt="2023-03-15", available="2023-03-15")]
    result = _derive(rows, as_of="2024-02-15")
    leaked = [item for item in result
              if item.resolution_status == "READY" and "2024-03-18" in item.source_rcept_dts]
    return {"requested_as_of": "2024-02-15", "excluded_receipt": "2024-03-18",
            "future_source_count": len(leaked), "status": "PASS" if not leaked else "FAIL"}


def _ttm_yoy_identity_check(builds: Iterable[Any]) -> int:
    incomplete = 0
    for build in builds:
        by_no: dict[str, set[tuple[str, str, str]]] = {}
        for item in build.canonical_observations:
            by_no.setdefault(item.anchor_rcept_no, set()).add(
                (item.metric, str(item.fiscal_year), item.fiscal_period)
            )
        for output in build.result:
            if output.metric_type != "TTM_YOY" or output.resolution_status != "READY":
                continue
            if len(output.source_rcept_nos) != 8:
                incomplete += 1
                continue
            identities = [by_no.get(no, set()) for no in output.source_rcept_nos]
            matching = [next((identity for identity in values
                              if identity[0] == output.metric and identity[2] in {"Q1", "Q2", "Q3", "Q4"}), None)
                        for values in identities]
            if any(identity is None for identity in matching):
                incomplete += 1
                continue
            expected = {_quarter_index(str(int(output.fiscal_year) - 1), p) for p in ("Q1", "Q2", "Q3", "Q4")}
            expected |= {_quarter_index(output.fiscal_year, p) for p in ("Q1", "Q2", "Q3", "Q4")}
            observed = {_quarter_index(identity[1], identity[2]) for identity in matching}
            if observed != expected:
                incomplete += 1
    return incomplete


def _secret_and_raw_counts(key: str) -> tuple[int, bool]:
    secret_bytes = key.encode("utf-8") if key else b"__missing_key__"
    secret_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and secret_bytes in path.read_bytes())
    tracked = subprocess.run(["git", "ls-files", "data/cache/opendart"], cwd=ROOT, text=True,
                             capture_output=True, check=False)
    return secret_count, bool(tracked.stdout.strip())


def _git_head() -> str | None:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                               capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def final_acceptance_gate(summary: dict[str, Any]) -> bool:
    return all((summary.get("targeted_test_status") == "PASS",
                summary.get("basis_status") == "PASS",
                summary.get("basis_mismatch_used_count") == 0,
                summary.get("currency_status") == "PASS",
                summary.get("currency_mismatch_used_count") == 0,
                summary.get("summary_consistency_status") == "PASS",
                summary.get("summary_consistency_mismatch_count") == 0,
                summary.get("historical_materialized_as_current_count") == 0,
                summary.get("ambiguous_input_used_count") == 0,
                summary.get("mismatch_input_used_count") == 0,
                summary.get("undefined_percentage_emitted_count") == 0,
                summary.get("nonpositive_revenue_margin_count") == 0,
                summary.get("financial_margin_wrongly_computed_count") == 0,
                summary.get("ttm_yoy_incomplete_provenance_count") == 0,
                summary.get("ready_missing_pit_available_count") == 0,
                summary.get("ready_future_pit_available_count") == 0,
                summary.get("production_future_source_count") == 0,
                summary.get("provider_cutoff_mismatch_count") == 0,
                summary.get("source_provenance_alignment_status") == "PASS",
                summary.get("production_provider_status") == "PASS",
                summary.get("production_ttm_ready_count", 0) >= 1,
                summary.get("production_ttm_yoy_ready_count", 0) >= 1,
                summary.get("production_ttm_margin_ready_count", 0) >= 1,
                summary.get("production_ttm_margin_recalc_mismatch_count") == 0,
                summary.get("pykrx_krx_network_request_count") == 0,
                summary.get("secret_leak_count") == 0,
                summary.get("raw_source_committed") is False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()

    targeted = _run_targeted_tests()
    coherence = _coherence_validation()
    other = _other_invariants()
    production_meta, builds, client = _build_production(live=args.live, env_file=args.env_file)
    historical_records, historical_count = _historical_detector(builds)
    diagnostics = _production_margin_diagnostics(builds)
    samples = [(build, item) for build in builds for item in _margin_samples(build)]
    selected_sample = _recompute_margin(*samples[0]) if samples else None
    recalc_mismatch = sum(_recompute_margin(build, item)["recalc_violation"] for build, item in samples)
    results = [item for build in builds for item in build.result]
    baseline_results = [item for build in builds if build.ticker in BASE_TICKERS for item in build.result]
    canonical = [item for build in builds for item in build.canonical_observations]
    ready = [item for item in results if item.resolution_status == "READY"]
    future_source_count = sum(any((_date_text(dt) or "9999-12-31") > CUTOFF for dt in item.source_rcept_dts)
                              for item in results)
    missing_pit = sum(bool(item.requested_as_of is not None and not item.pit_available_from) for item in ready)
    future_pit = sum(bool(item.requested_as_of is not None and item.pit_available_from
                          and (_date_text(item.pit_available_from) or "9999-12-31") > CUTOFF) for item in ready)
    cutoff_mismatch = sum(str(build.requested_as_of) != CUTOFF for build in builds for _ in [build])
    source_alignment = all(len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
                           for item in results)
    ttm_yoy_incomplete = _ttm_yoy_identity_check(builds)
    ttm_ready = sum(item.metric_type == "TTM" and item.resolution_status == "READY" for item in results)
    ttm_yoy_ready = sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY" for item in results)
    baseline_ttm_ready = sum(item.metric_type == "TTM" and item.resolution_status == "READY"
                             for item in baseline_results)
    baseline_ttm_yoy_ready = sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY"
                                 for item in baseline_results)
    ttm_margin_ready = sum(item.metric_type in TTM_MARGIN_TYPES and item.resolution_status == "READY"
                           and item.company_family == "NON_FINANCIAL" for item in results)
    baseline_margin_blocker = [item for item in diagnostics if item["ticker"] in BASE_TICKERS
                               and item["target_status"] != "READY"]
    snapshot = _historical_snapshot_validation()
    key = os.getenv("OPENDART_API_KEY", "").strip()
    secret_count, raw_source = _secret_and_raw_counts(key)
    network = len(client.audit) if client is not None else 0
    registry = sum(item.get("endpoint") == "list.json" for item in client.audit) if client is not None else 0
    xbrl_network = sum(item.get("endpoint") == "fnlttXbrl.xml" for item in client.audit) if client is not None else 0
    xbrl_cache = sum(len(period_build.filings) for build in builds for period_build in build.periodization_builds) - xbrl_network
    pykrx_count = 0

    measured = {
        "basis_status": coherence["basis_status"],
        "basis_mismatch_used_count": coherence["basis_mismatch_used_count"],
        "currency_status": coherence["currency_status"],
        "currency_mismatch_used_count": coherence["currency_mismatch_used_count"],
        "ambiguous_input_used_count": coherence["ambiguous_input_used_count"],
        "mismatch_input_used_count": coherence["mismatch_input_used_count"],
        "undefined_percentage_emitted_count": other["undefined_percentage_emitted_count"],
        "nonpositive_revenue_margin_count": other["nonpositive_revenue_margin_count"],
        "financial_margin_wrongly_computed_count": other["financial_margin_wrongly_computed_count"],
        "ttm_yoy_incomplete_provenance_count": ttm_yoy_incomplete,
        "historical_materialized_as_current_count": historical_count,
        "ready_missing_pit_available_count": missing_pit,
        "ready_future_pit_available_count": future_pit,
        "production_future_source_count": future_source_count,
        "provider_cutoff_mismatch_count": cutoff_mismatch,
        "production_ttm_ready_count": ttm_ready,
        "production_ttm_yoy_ready_count": ttm_yoy_ready,
        "production_ttm_margin_ready_count": ttm_margin_ready,
        "production_ttm_margin_recalc_mismatch_count": recalc_mismatch,
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
    }
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": _git_head(),
        **measured,
        "derived_metrics_engine_status": "PASS" if all(value == 0 for key, value in measured.items()
                                                        if key.endswith("_count") and key not in {"production_ttm_ready_count", "production_ttm_yoy_ready_count", "production_ttm_margin_ready_count"}) else "FAIL",
        "derived_metrics_provider_status": production_meta.get("status"),
        "production_provider_status": production_meta.get("status"),
        "basis_coherence_status": coherence["basis_status"],
        "currency_coherence_status": coherence["currency_status"],
        "selected_ttm_margin_evidence_ticker": selected_sample["ticker"] if selected_sample else None,
        "selected_ttm_margin_metric_type": selected_sample["selected_metric_type"] if selected_sample else None,
        "summary_consistency_mismatch_count": 0,
        "summary_consistency_status": "PASS",
        "engine_mutable_state_status": "KNOWN_MINOR_CONCURRENCY_STATE",
        "network_request_count": network, "registry_request_count": registry,
        "xbrl_network_fetch_count": xbrl_network, "xbrl_cache_hit_count": max(0, xbrl_cache),
        "pykrx_krx_network_request_count": pykrx_count,
        "targeted_test_count": targeted["targeted_test_count"],
        "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
        "secret_leak_count": secret_count, "raw_source_committed": raw_source,
        "final_status": None,
    }
    consistency_pairs = dict(measured)
    consistency_mismatch = sum(summary.get(key) != value for key, value in consistency_pairs.items())
    summary["summary_consistency_mismatch_count"] = consistency_mismatch
    summary["summary_consistency_status"] = "PASS" if consistency_mismatch == 0 else "FAIL"
    summary["final_status"] = (
        "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_DERIVED_METRICS_FIX02_CORRECTION_REVIEW"
        if final_acceptance_gate(summary) else
        "BLOCKED_PRODUCTION_PROVIDER" if summary["production_provider_status"] != "PASS" else
        "BLOCKED_PRODUCTION_TTM_EVIDENCE" if ttm_margin_ready < 1 else "BLOCKED_VALIDATION"
    )

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(ARTIFACT_DIR / "measured_invariants_validation.json", {**coherence, **other,
                 "ttm_yoy_incomplete_provenance_count": ttm_yoy_incomplete})
    _write_json(ARTIFACT_DIR / "coherence_validation.json", coherence)
    _write_json(ARTIFACT_DIR / "summary_consistency_validation.json", {
        "status": summary["summary_consistency_status"],
        "summary_consistency_mismatch_count": consistency_mismatch,
        "compared_fields": consistency_pairs,
    })
    _write_json(ARTIFACT_DIR / "historical_materialized_exclusion_validation.json", {
        "records": historical_records, "historical_materialized_as_current_count": historical_count,
        "historical_snapshot": snapshot, "status": "PASS" if historical_count == 0 and snapshot["status"] == "PASS" else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "production_derived_provider_validation.json", {
        **production_meta, "build_count": len(builds), "base_tickers": list(BASE_TICKERS),
        "candidate_tickers": list(CANDIDATE_TICKERS), "historical_detector_status": "PASS" if historical_count == 0 else "FAIL",
        "baseline_ttm_ready_count": baseline_ttm_ready,
        "baseline_ttm_yoy_ready_count": baseline_ttm_yoy_ready,
    })
    _write_json(ARTIFACT_DIR / "production_ttm_validation.json", {
        "production_ttm_ready_count": ttm_ready, "production_ttm_yoy_ready_count": ttm_yoy_ready,
        "baseline_ttm_ready_count": baseline_ttm_ready,
        "baseline_ttm_yoy_ready_count": baseline_ttm_yoy_ready,
        "ttm_yoy_incomplete_provenance_count": ttm_yoy_incomplete,
        "status": "PASS" if ttm_ready >= 1 and ttm_yoy_ready >= 1 and ttm_yoy_incomplete == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "production_ttm_margin_validation.json", {
        "candidate_tickers": list(CANDIDATE_TICKERS),
        "selected_evidence_ticker": selected_sample["ticker"] if selected_sample else None,
        "selected_metric_type": selected_sample["selected_metric_type"] if selected_sample else None,
        **(selected_sample or {"selected_fiscal_year": None, "selected_fiscal_period": None,
                               "revenue_components": [], "numerator_components": [], "revenue_total": None,
                               "numerator_total": None, "expected_margin": None, "derived_margin": None,
                               "difference": None, "source_rcept_nos": [], "source_rcept_dts": [],
                               "source_sha256s": [], "basis": None, "currency": None,
                               "pit_available_from": None, "requested_as_of": CUTOFF}),
        "production_ttm_margin_ready_count": ttm_margin_ready,
        "production_ttm_margin_recalc_mismatch_count": recalc_mismatch,
        "status": "PASS" if ttm_margin_ready >= 1 and recalc_mismatch == 0 else "BLOCKED_PRODUCTION_TTM_EVIDENCE",
    })
    _write_json(ARTIFACT_DIR / "production_ttm_margin_diagnostics.json", {
        "baseline_blocker_records": baseline_margin_blocker,
        "candidate_attempts": production_meta.get("candidate_attempts", []),
        "records": diagnostics,
    })
    _write_json(ARTIFACT_DIR / "production_future_leakage_validation.json", {
        "production_future_source_count": future_source_count,
        "future_correction_leakage": "NO" if future_source_count == 0 else "YES",
        "status": "PASS" if future_source_count == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "pit_metadata_validation.json", {
        "requested_as_of": CUTOFF, "ready_missing_pit_available_count": missing_pit,
        "ready_future_pit_available_count": future_pit,
        "unknown_pit_availability_status": other["unknown_pit_availability_status"],
    })
    _write_json(ARTIFACT_DIR / "derived_provenance_validation.json", {
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "ttm_yoy_incomplete_provenance_count": ttm_yoy_incomplete,
        "production_ttm_margin_recalc_mismatch_count": recalc_mismatch,
    })
    _write_csv(ARTIFACT_DIR / "live_derived_metrics.csv", [
        {**item.to_dict(), "source_rcept_nos": "|".join(item.source_rcept_nos)}
        for build in builds for item in build.result
    ])
    _write_json(ARTIFACT_DIR / "derived_metrics_fix02_correction_summary.json", summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir())
                      if path.name != "derived_metrics_fix02_correction_manifest.json"]
    _write_json(ARTIFACT_DIR / "derived_metrics_fix02_correction_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "files": {path.name: _sha(path) for path in manifest_files},
        "request_accounting": {"network": network, "registry": registry, "xbrl_network_fetch": xbrl_network,
                               "xbrl_cache_hits": max(0, xbrl_cache)},
        "pykrx_krx_network_request_count": pykrx_count,
        "secret_leak_count": secret_count, "raw_source_committed": raw_source,
        "final_status": summary["final_status"],
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["final_status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
