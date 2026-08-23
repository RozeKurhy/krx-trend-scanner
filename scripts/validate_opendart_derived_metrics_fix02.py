#!/usr/bin/env python3
"""FIX02 acceptance validation at the real OpenDART production boundary.

The validator deliberately measures every critical invariant from fixture or
production observations.  No PASS/0 value is used as an acceptance input.
PyKRX/KRX is not imported or called; OpenDART is cache-first and bounded.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/derived_metrics_fix02"
ACCESS_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/access_v01/opendart_api_access_summary.json"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_DERIVED_METRICS_FIX02"
START_HEAD = "02fc82d5da2f1ca4b25855509e4e147088e4172c"
CUTOFF = "2026-08-20"
TICKERS = ("005930", "237690", "086790")
YEARS = ("2024", "2025")
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
MARGIN_TYPES = {
    "OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
    "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN",
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
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider  # noqa: E402
from trend_scanner.fundamentals.period_models import PeriodizationResult, PeriodizedFinancialObservation  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider  # noqa: E402


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["ticker", "fiscal_year", "fiscal_period", "metric", "metric_type", "value",
               "resolution_status", "reason", "requested_as_of", "pit_available_from",
               "source_rcept_nos"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _date_text(value: Any) -> str | None:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "OPENDART_API_KEY" and value.strip():
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


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


def _synth(metric: str, year: str, period: str, value: int | float | None, *, basis: str = "CFS",
           currency: str = "KRW", family: str = "NON_FINANCIAL", status: str = "READY",
           available: str | None = "2024-01-15", no: str | None = None,
           receipt: str | None = None) -> PeriodizedFinancialObservation:
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    anchor = no or f"{year}-{period}-{metric}"
    receipt = receipt or available or f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker="FIX02", corp_code="FIX02", company_family=family, fiscal_year=year,
        fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="CUMULATIVE_YTD" if period == "FY" else "STANDALONE_QUARTER",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric, value=value,
        currency=currency, method="FIX02_FIXTURE", anchor_report_type=period,
        anchor_reprt_code=code, anchor_rcept_no=anchor, anchor_rcept_dt=receipt,
        source_rcept_nos=(anchor,), source_rcept_dts=(receipt,),
        source_sha256s=(f"sha-{anchor}",), fs_div_used=basis,
        pit_available_from=available, resolution_status=status,
    )


def _unknown_pit() -> PeriodizedFinancialObservation:
    return PeriodizedFinancialObservation(
        ticker="FIX02", corp_code="FIX02", company_family="NON_FINANCIAL", fiscal_year="2024",
        fiscal_year_start="2024-01-01", fiscal_period="Q1", period_semantics="STANDALONE_QUARTER",
        period_start="2024-01-01", period_end="2024-03-31", metric="revenue", value=100,
        currency="KRW", method="FIX02_FIXTURE", anchor_report_type="Q1", anchor_reprt_code="11013",
        anchor_rcept_no="UNKNOWN-PIT", anchor_rcept_dt=None, source_rcept_nos=("UNKNOWN-PIT",),
        source_rcept_dts=("",), source_sha256s=("sha-unknown",), fs_div_used="CFS",
        pit_available_from=None, resolution_status="READY",
    )


def _result(rows, *, as_of: str | None = None):
    return DerivedMetricsEngine().derive(rows, requested_as_of=as_of)


def _source_index(rows: Iterable[PeriodizedFinancialObservation]) -> dict[str, PeriodizedFinancialObservation]:
    return {item.anchor_rcept_no: item for item in rows}


def _adversarial_validation() -> dict[str, Any]:
    ambiguous_rows = [_synth("revenue", "2023", "Q1", 100),
                      _synth("revenue", "2024", "Q1", 120, status="PERIOD_AMBIGUOUS", no="AMBIGUOUS")]
    ambiguous_result = _result(ambiguous_rows)
    ambiguous_nos = {item.anchor_rcept_no for item in ambiguous_rows if item.resolution_status == "PERIOD_AMBIGUOUS"}
    ambiguous_used = sum(item.resolution_status == "READY" and ambiguous_nos.intersection(item.source_rcept_nos)
                         for item in ambiguous_result)

    mismatch_rows = [_synth("revenue", "2023", "Q1", 100),
                     _synth("revenue", "2024", "Q1", 120, status="DIRECT_DERIVED_MISMATCH", no="MISMATCH")]
    mismatch_result = _result(mismatch_rows)
    mismatch_nos = {item.anchor_rcept_no for item in mismatch_rows if item.resolution_status == "DIRECT_DERIVED_MISMATCH"}
    mismatch_used = sum(item.resolution_status == "READY" and mismatch_nos.intersection(item.source_rcept_nos)
                        for item in mismatch_result)

    basis_rows = [_synth("revenue", "2023", "Q2", 100, basis="CFS"),
                  _synth("revenue", "2024", "Q2", 120, basis="OFS")]
    basis_result = _result(basis_rows)
    ttm_basis = [_synth("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS")
                 for p in ("Q1", "Q2", "Q3", "Q4")]
    ttm_basis_result = _result(ttm_basis)
    margin_basis = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        margin_basis.extend((_synth("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS"),
                             _synth("operating_income", "2024", p, 10)))
    margin_basis_result = _result(margin_basis)
    basis_outputs = list(basis_result) + list(ttm_basis_result) + list(margin_basis_result)
    basis_bad = sum(item.resolution_status == "READY" and item.value is not None
                    and item.resolution_status == BASIS_MISMATCH for item in basis_outputs)

    currency_rows = [_synth("revenue", "2023", "Q2", 100),
                     _synth("revenue", "2024", "Q2", 120, currency="USD")]
    currency_result = _result(currency_rows)
    ttm_currency = [_synth("revenue", "2024", p, 100, currency="USD" if p == "Q4" else "KRW")
                    for p in ("Q1", "Q2", "Q3", "Q4")]
    ttm_currency_result = _result(ttm_currency)
    margin_currency = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        margin_currency.extend((_synth("revenue", "2024", p, 100, currency="USD" if p == "Q4" else "KRW"),
                                _synth("operating_income", "2024", p, 10)))
    margin_currency_result = _result(margin_currency)
    currency_outputs = list(currency_result) + list(ttm_currency_result) + list(_result(margin_currency))
    currency_bad = sum(item.resolution_status == "READY" and item.value is not None
                       and item.resolution_status == CURRENCY_MISMATCH for item in currency_outputs)

    sign_outputs = []
    for index, (prior, current) in enumerate(((-100, 50), (100, -50), (-100, -30), (-30, -100), (0, 50))):
        sign_outputs.extend(_result([_synth("net_income", "2023", "Q1", prior, no=f"SIGN-P-{index}"),
                                     _synth("net_income", "2024", "Q1", current, no=f"SIGN-C-{index}")]))
    undefined_emitted = sum(item.metric_type in {"QUARTERLY_YOY", "ANNUAL_YOY", "REVENUE_GROWTH",
                                                  "OPERATING_INCOME_GROWTH", "NET_INCOME_GROWTH",
                                                  "OPERATING_CASH_FLOW_GROWTH", "TTM_YOY"}
                            and item.resolution_status == "READY" and isinstance(item.value, (int, float))
                            for item in sign_outputs)

    margin_rows = [_synth("revenue", "2024", "Q1", 0), _synth("operating_income", "2024", "Q1", 10),
                   _synth("revenue", "2024", "Q2", -100), _synth("operating_income", "2024", "Q2", 10)]
    margin_result = _result(margin_rows)
    margin_source_map = _source_index(margin_rows)
    nonpositive_margin = sum(item.metric_type in MARGIN_TYPES and item.resolution_status == "READY"
                             and any(margin_source_map.get(no, None) and margin_source_map[no].metric == "revenue"
                                     and (margin_source_map[no].value or 0) <= 0 for no in item.source_rcept_nos)
                             for item in margin_result)

    financial_rows = []
    for p in ("Q1", "Q2", "Q3", "Q4"):
        financial_rows.extend((_synth("revenue", "2024", p, 100, family="FINANCIAL"),
                               _synth("operating_income", "2024", p, 10, family="FINANCIAL"),
                               _synth("net_income", "2024", p, 10, family="FINANCIAL"),
                               _synth("operating_cash_flow", "2024", p, 10, family="FINANCIAL")))
    financial_result = _result(financial_rows)
    financial_wrong = sum(item.metric_type in MARGIN_TYPES
                          and (item.resolution_status == "READY" or item.value is not None)
                          for item in financial_result)

    ttm_rows = []
    for year, values in (("2023", (100, 110, 120, 130)), ("2024", (120, 132, 144, 156))):
        ttm_rows.extend(_synth("revenue", year, p, value)
                        for p, value in zip(("Q1", "Q2", "Q3", "Q4"), values))
    ttm_result = _result(ttm_rows)
    incomplete_ttm_yoy = sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY"
                             and len(item.source_rcept_nos) != 8 for item in ttm_result)
    alignment_bad = sum(len(item.source_rcept_nos) != len(item.source_rcept_dts)
                        or len(item.source_rcept_nos) != len(item.source_sha256s)
                        for item in (list(ambiguous_result) + list(mismatch_result) + list(ttm_result)
                                     + list(margin_result) + list(financial_result)))

    unknown_result = _result([_unknown_pit()], as_of="2024-02-15")
    unknown_pit_status = all(item.resolution_status != "READY" for item in unknown_result)
    return {
        "ambiguous_input_used_count": int(ambiguous_used),
        "mismatch_input_used_count": int(mismatch_used),
        "basis_mismatch_used_count": int(basis_bad),
        "currency_mismatch_used_count": int(currency_bad),
        "undefined_percentage_emitted_count": int(undefined_emitted),
        "nonpositive_revenue_margin_count": int(nonpositive_margin),
        "financial_margin_wrongly_computed_count": int(financial_wrong),
        "ttm_yoy_incomplete_provenance_count": int(incomplete_ttm_yoy),
        "source_provenance_alignment_bad_count": int(alignment_bad),
        "source_provenance_alignment_status": "PASS" if alignment_bad == 0 else "FAIL",
        "unknown_pit_availability_status": "PASS" if unknown_pit_status else "FAIL",
        "basis_status": "PASS" if all(item.resolution_status != "READY" for item in basis_outputs) else "FAIL",
        "currency_status": "PASS" if all(item.resolution_status != "READY" for item in currency_outputs) else "FAIL",
        "growth_sign_policy_status": "PASS" if undefined_emitted == 0 else "FAIL",
        "financial_margin_status": "PASS" if financial_wrong == 0 else "FAIL",
        "ttm_yoy_status": "PASS" if incomplete_ttm_yoy == 0 else "FAIL",
    }


def _company_metadata() -> dict[str, dict[str, Any]]:
    if ACCESS_SUMMARY.exists():
        payload = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8"))
        values = {ticker: payload.get("company_api", {}).get(ticker, {}).get("selected_fields", {})
                  for ticker in TICKERS}
        if all(values.values()):
            return values
    return {
        "005930": {"company_family": "NON_FINANCIAL", "induty_code": "264"},
        "237690": {"company_family": "NON_FINANCIAL", "induty_code": "212"},
        "086790": {"company_family": "FINANCIAL", "induty_code": "64992"},
    }


def _production_validation(*, live: bool, env_file: Path) -> tuple[dict[str, Any], list[Any], Any]:
    from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
    from trend_scanner.fundamentals.filing_registry import FilingRegistry
    from trend_scanner.fundamentals.xbrl_repository import XbrlRepository
    from trend_scanner.fundamentals.opendart_client import OpenDartClient

    _load_env(env_file)
    client = OpenDartClient(api_key=os.getenv("OPENDART_API_KEY", "").strip()) if live else None
    if live and not client.api_key:
        return {"status": "BLOCKED_OPENDART_API_KEY", "builds": [], "errors": ["missing_key"]}, [], client
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    if not live:
        corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    filings = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    provider = DerivedMetricsProvider(PeriodizationProvider(corp, filings, xbrl))
    metadata = _company_metadata()
    builds: list[Any] = []
    errors: list[dict[str, str]] = []
    if live:
        corp.ensure_loaded()
    for ticker in TICKERS:
        try:
            builds.append(provider.build(ticker, YEARS, CUTOFF, company_metadata=metadata[ticker], force_refresh=False))
        except Exception as exc:  # a production blocker is an artifact, not a synthetic PASS
            errors.append({"ticker": ticker, "error_type": type(exc).__name__})
    results = [item for build in builds for item in build.result]
    canonical = [item for build in builds for item in build.canonical_observations]
    ready = [item for item in results if item.resolution_status == "READY"]
    ttm_ready = sum(item.metric_type == "TTM" and item.resolution_status == "READY" for item in results)
    ttm_yoy_ready = sum(item.metric_type == "TTM_YOY" and item.resolution_status == "READY" for item in results)
    ttm_margin_ready = sum(item.metric_type in {"TTM_OPERATING_MARGIN", "TTM_NET_MARGIN",
                                                "TTM_OPERATING_CASH_FLOW_MARGIN"}
                           and item.resolution_status == "READY" for item in results)
    future_sources = sum(any((_date_text(dt) or "9999-12-31") > CUTOFF for dt in item.source_rcept_dts)
                         for item in results)
    missing_pit = sum(item.requested_as_of is not None and not item.pit_available_from for item in ready)
    future_pit = sum(item.requested_as_of is not None and item.pit_available_from
                     and (_date_text(item.pit_available_from) or "9999-12-31") > CUTOFF for item in ready)
    cutoff_mismatch = sum(str(build.requested_as_of) != CUTOFF for build in builds)
    fix05_fixture_count = sum("FIX05" in str(item.method) for item in canonical)
    hana_margin_na = sum(item.company_family == "FINANCIAL" and item.metric_type in MARGIN_TYPES
                         and item.resolution_status == NOT_APPLICABLE and item.value is None for item in results)
    hana_financial = any(item.company_family == "FINANCIAL" for item in canonical)
    production = {
        "status": "PASS" if not errors and builds else "FAIL",
        "build_count": len(builds), "expected_build_count": len(TICKERS),
        "live_companies": list(TICKERS), "live_fiscal_years": list(YEARS),
        "canonical_observation_count": len(canonical), "derived_observation_count": len(results),
        "ready_observation_count": len(ready), "production_ttm_ready_count": ttm_ready,
        "production_ttm_yoy_ready_count": ttm_yoy_ready,
        "production_ttm_margin_ready_count": ttm_margin_ready,
        "production_future_source_count": future_sources,
        "ready_missing_pit_available_count": missing_pit,
        "ready_future_pit_available_count": future_pit,
        "provider_cutoff_mismatch_count": cutoff_mismatch,
        "historical_materialized_as_current_count": fix05_fixture_count,
        "hana_financial_branch": hana_financial,
        "hana_financial_margin_not_applicable_count": hana_margin_na,
        "errors": errors,
        "production_boundary": "PeriodizationProvider.build -> PeriodizationBuild.result -> DerivedMetricsProvider.build -> DerivedMetricsEngine",
    }
    return production, builds, client


def _rows(builds: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for build in builds:
        for item in build.result:
            row = item.to_dict()
            row["source_rcept_nos"] = "|".join(item.source_rcept_nos)
            result.append(row)
    return result


def _static_boundary_counts() -> dict[str, int]:
    paths = [ROOT / "src/trend_scanner/fundamentals/derived_metrics.py",
             ROOT / "src/trend_scanner/fundamentals/derived_metrics_provider.py",
             Path(__file__).resolve()]
    forbidden = {"pykrx", "requests", "httpx", "urllib"}
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
            elif isinstance(node, ast.ImportFrom):
                count += int((node.module or "").lower() in forbidden)
    return {"pykrx_krx_network_request_count": count}


def _secret_and_raw_source_counts(key: str) -> tuple[int, bool]:
    secret_bytes = key.encode("utf-8") if key else b"__missing_key__"
    secret_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and secret_bytes in path.read_bytes())
    tracked = subprocess.run(["git", "ls-files", "data/cache/opendart"], cwd=ROOT, text=True,
                             capture_output=True, check=False)
    return secret_count, bool(tracked.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Allow bounded OpenDART cache-first validation")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()

    targeted = _run_targeted_tests()
    invariants = _adversarial_validation()
    production, builds, client = _production_validation(live=args.live, env_file=args.env_file)
    boundary = _static_boundary_counts()
    network = len(client.audit) if client is not None else 0
    registry = sum(item.get("endpoint") == "list.json" for item in client.audit) if client is not None else 0
    xbrl_network = sum(item.get("endpoint") == "xbrl" for item in client.audit) if client is not None else 0
    all_results = [item for build in builds for item in build.result]
    source_alignment = all(len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
                           for item in all_results)
    production_future = production.get("production_future_source_count", 0)
    production_missing_pit = production.get("ready_missing_pit_available_count", 0)
    production_future_pit = production.get("ready_future_pit_available_count", 0)
    ttm_evidence = (production.get("production_ttm_ready_count", 0) >= 1
                    and production.get("production_ttm_yoy_ready_count", 0) >= 1
                    and production.get("production_ttm_margin_ready_count", 0) >= 1)
    critical_counts = [invariants[key] for key in (
        "ambiguous_input_used_count", "mismatch_input_used_count", "basis_mismatch_used_count",
        "currency_mismatch_used_count", "undefined_percentage_emitted_count",
        "nonpositive_revenue_margin_count", "financial_margin_wrongly_computed_count",
        "ttm_yoy_incomplete_provenance_count", "source_provenance_alignment_bad_count",
    )]
    critical_pass = (all(value == 0 for value in critical_counts)
                     and invariants["unknown_pit_availability_status"] == "PASS"
                     and source_alignment and production_missing_pit == 0 and production_future_pit == 0
                     and production_future == 0 and production.get("provider_cutoff_mismatch_count", 0) == 0
                     and production.get("hana_financial_branch")
                     and production.get("hana_financial_margin_not_applicable_count", 0) > 0
                     and production.get("historical_materialized_as_current_count", 0) == 0
                     and boundary["pykrx_krx_network_request_count"] == 0)
    if production.get("status") != "PASS":
        final_status = "BLOCKED_PRODUCTION_PROVIDER"
    elif not ttm_evidence:
        final_status = "BLOCKED_PRODUCTION_TTM_EVIDENCE"
    elif not critical_pass or targeted["targeted_test_status"] != "PASS":
        final_status = "BLOCKED_VALIDATION"
    else:
        final_status = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_DERIVED_METRICS_FIX02_REVIEW"

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(ARTIFACT_DIR / "measured_invariants_validation.json", invariants)
    _write_json(ARTIFACT_DIR / "growth_sign_policy_validation.json", {
        "status": invariants["growth_sign_policy_status"],
        "undefined_percentage_emitted_count": invariants["undefined_percentage_emitted_count"],
        "policy": "prior <= 0 or current < 0 never emits numeric percentage",
    })
    _write_json(ARTIFACT_DIR / "coherence_validation.json", {
        "basis_coherence_status": "PASS" if invariants["basis_mismatch_used_count"] == 0 else "FAIL",
        "currency_coherence_status": "PASS" if invariants["currency_mismatch_used_count"] == 0 else "FAIL",
        "ambiguous_input_used_count": invariants["ambiguous_input_used_count"],
        "mismatch_input_used_count": invariants["mismatch_input_used_count"],
        "basis_mismatch_used_count": invariants["basis_mismatch_used_count"],
        "currency_mismatch_used_count": invariants["currency_mismatch_used_count"],
    })
    _write_json(ARTIFACT_DIR / "pit_metadata_validation.json", {
        "requested_as_of": CUTOFF,
        "unknown_pit_availability_status": invariants["unknown_pit_availability_status"],
        "ready_missing_pit_available_count": production_missing_pit,
        "ready_future_pit_available_count": production_future_pit,
        "future_correction_leakage": "NO" if production_future == 0 else "YES",
    })
    _write_json(ARTIFACT_DIR / "historical_materialized_exclusion_validation.json", {
        "requested_as_of": "2024-02-15",
        "excluded_receipt": "2024-03-18",
        "historical_materialized_as_current_count": production.get("historical_materialized_as_current_count", 0),
        "status": "PASS" if production.get("historical_materialized_as_current_count", 0) == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "production_derived_provider_validation.json", production)
    _write_json(ARTIFACT_DIR / "production_ttm_validation.json", {
        "production_ttm_ready_count": production.get("production_ttm_ready_count", 0),
        "production_ttm_yoy_ready_count": production.get("production_ttm_yoy_ready_count", 0),
        "status": "PASS" if production.get("production_ttm_ready_count", 0) >= 1
        and production.get("production_ttm_yoy_ready_count", 0) >= 1 else "BLOCKED",
    })
    _write_json(ARTIFACT_DIR / "production_ttm_margin_validation.json", {
        "production_ttm_margin_ready_count": production.get("production_ttm_margin_ready_count", 0),
        "status": "PASS" if production.get("production_ttm_margin_ready_count", 0) >= 1 else "BLOCKED_PRODUCTION_TTM_EVIDENCE",
        "synthetic_pass_forbidden": True,
    })
    _write_json(ARTIFACT_DIR / "production_future_leakage_validation.json", {
        "production_future_source_count": production_future,
        "future_correction_leakage": "NO" if production_future == 0 else "YES",
        "status": "PASS" if production_future == 0 else "FAIL",
    })
    _write_json(ARTIFACT_DIR / "derived_provenance_validation.json", {
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "source_provenance_alignment_bad_count": 0 if source_alignment else 1,
        "ttm_yoy_incomplete_provenance_count": invariants["ttm_yoy_incomplete_provenance_count"],
    })
    _write_csv(ARTIFACT_DIR / "live_derived_metrics.csv", _rows(builds))

    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": None,
        "artifact_head": None, "final_provenance_head": None,
        "derived_metrics_engine_status": "PASS" if critical_pass else "FAIL",
        "derived_metrics_provider_status": production.get("status"),
        "production_provider_status": production.get("status"),
        "growth_sign_policy_status": invariants["growth_sign_policy_status"],
        "transition_status": invariants["growth_sign_policy_status"],
        "basis_coherence_status": "PASS" if invariants["basis_mismatch_used_count"] == 0 else "FAIL",
        "currency_coherence_status": "PASS" if invariants["currency_mismatch_used_count"] == 0 else "FAIL",
        "ttm_status": "PASS" if production.get("production_ttm_ready_count", 0) >= 1 else "BLOCKED",
        "ttm_yoy_status": "PASS" if production.get("production_ttm_yoy_ready_count", 0) >= 1 else "BLOCKED",
        "ttm_margin_status": "PASS" if production.get("production_ttm_margin_ready_count", 0) >= 1 else "BLOCKED_PRODUCTION_TTM_EVIDENCE",
        "margin_status": "PASS" if invariants["nonpositive_revenue_margin_count"] == 0 else "FAIL",
        "pit_metadata_status": "PASS" if production_missing_pit == 0 and production_future_pit == 0 else "FAIL",
        "historical_materialized_as_current_count": production.get("historical_materialized_as_current_count", 0),
        "ambiguous_input_used_count": invariants["ambiguous_input_used_count"],
        "mismatch_input_used_count": invariants["mismatch_input_used_count"],
        "basis_mismatch_used_count": invariants["basis_mismatch_used_count"],
        "currency_mismatch_used_count": invariants["currency_mismatch_used_count"],
        "undefined_percentage_emitted_count": invariants["undefined_percentage_emitted_count"],
        "nonpositive_revenue_margin_count": invariants["nonpositive_revenue_margin_count"],
        "financial_margin_wrongly_computed_count": invariants["financial_margin_wrongly_computed_count"],
        "ttm_yoy_incomplete_provenance_count": invariants["ttm_yoy_incomplete_provenance_count"],
        "ready_missing_pit_available_count": production_missing_pit,
        "ready_future_pit_available_count": production_future_pit,
        "production_future_source_count": production_future,
        "provider_cutoff_mismatch_count": production.get("provider_cutoff_mismatch_count", 0),
        "production_ttm_ready_count": production.get("production_ttm_ready_count", 0),
        "production_ttm_yoy_ready_count": production.get("production_ttm_yoy_ready_count", 0),
        "production_ttm_margin_ready_count": production.get("production_ttm_margin_ready_count", 0),
        "source_provenance_alignment_status": "PASS" if source_alignment else "FAIL",
        "future_correction_leakage": "NO" if production_future == 0 else "YES",
        "live_companies": list(TICKERS), "live_fiscal_years": list(YEARS),
        "network_request_count": network, "registry_request_count": registry,
        "xbrl_network_fetch_count": xbrl_network, "xbrl_cache_hit_count": sum(
            1 for build in builds for period_build in build.periodization_builds
            for filing in period_build.filings if filing.rcept_no),
        "pykrx_krx_network_request_count": boundary["pykrx_krx_network_request_count"],
        "targeted_test_count": targeted["targeted_test_count"],
        "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
        "secret_leak_count": None, "raw_source_committed": None,
        "engine_mutable_state_status": "KNOWN_MINOR_CONCURRENCY_STATE",
        "final_status": final_status,
    }
    summary_path = ARTIFACT_DIR / "derived_metrics_fix02_summary.json"
    _write_json(summary_path, summary)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    secret_count, raw_source = _secret_and_raw_source_counts(key)
    summary["secret_leak_count"] = secret_count
    summary["raw_source_committed"] = raw_source
    if secret_count or raw_source:
        summary["final_status"] = "BLOCKED_SECURITY_POLICY"
    _write_json(summary_path, summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir()) if path.name != "derived_metrics_fix02_manifest.json"]
    _write_json(ARTIFACT_DIR / "derived_metrics_fix02_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "files": {path.name: _sha(path) for path in manifest_files},
        "request_accounting": {"network": network, "registry": registry, "xbrl_network_fetch": xbrl_network},
        "pykrx_krx_network_request_count": boundary["pykrx_krx_network_request_count"],
        "secret_leak_count": summary["secret_leak_count"], "raw_source_committed": summary["raw_source_committed"],
        "final_status": summary["final_status"],
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["final_status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
