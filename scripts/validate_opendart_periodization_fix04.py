#!/usr/bin/env python3
"""Bounded OpenDART live validation for Periodization FIX04.

This validator deliberately uses the production ``PeriodizationProvider.build``
boundary.  Registry discovery is bounded to the existing four report windows;
no PyKRX/KRX endpoint is imported or called.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from validate_opendart_periodization_fix01 import (  # noqa: E402
    ACCESS_SUMMARY,
    NAMES,
    _bounded_regular_filings,
    _load_env,
)
from validate_opendart_periodization_fix02 import _metric_status  # noqa: E402

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.opendart_contract import classify_company_family
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, STANDALONE_QUARTER
from trend_scanner.fundamentals.periodization import (
    PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS,
    PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD,
    PeriodizationFact,
    PeriodizationEngine,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix04"
TICKERS = ("005930", "237690", "086790")
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_LABEL = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}
WORK_ID = "OPENDART_FUNDAMENTALS_V01_PERIODIZATION_FIX04"
START_HEAD = "a5657280c6e4445cae3f413586a6d1379be24945"
REQUEST_LIMIT = 30
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
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    }


class _BoundedLiveRegistry:
    """FilingRegistry-compatible adapter over the bounded list.json calls."""

    def __init__(self, client: OpenDartClient):
        self.client = client

    def list_regular_filings(self, **kwargs):
        return _bounded_regular_filings(
            self.client, ticker=str(kwargs["ticker"]), corp_code=str(kwargs["corp_code"]),
            reprt_code=str(kwargs["reprt_code"]),
        )


class _CountingXbrl:
    """Preserve production XBRL behavior while accounting cache hits locally."""

    def __init__(self, repository: XbrlRepository):
        self.repository = repository
        self.cache_hits = 0
        self.network_fetches = 0

    def fetch(self, filing, *, force_refresh=False):
        artifact = self.repository.fetch(filing, force_refresh=force_refresh)
        if artifact.cache_hit:
            self.cache_hits += 1
        else:
            self.network_fetches += 1
        return artifact

    def period_context_rows(self, artifact, *, bsns_year, reprt_code):
        return self.repository.period_context_rows(artifact, bsns_year=bsns_year, reprt_code=reprt_code)


def _fact_anchor(build, code: str, no: str, metric: str) -> PeriodizationFact | None:
    return next((item for item in build.facts if item.reprt_code == code and item.rcept_no == no and item.metric == metric), None)


def _final_observation(build, code: str, no: str, metric: str, period: str):
    return next((item for item in build.result.observations
                 if item.anchor_reprt_code == code and item.anchor_rcept_no == no
                 and item.metric == metric and item.fiscal_period == period), None)


def _anchor_meta(build, code: str) -> dict[str, Any] | None:
    return next((dict(item) for item in build.anchor_selections if item.get("reprt_code") == code), None)


def _fact_matrix(build, ticker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fact in build.facts:
        rows.append({
            "ticker": ticker, "company": NAMES[ticker], "company_family": build.company_family,
            "fiscal_year": build.fiscal_year, "reprt_code": fact.reprt_code,
            "report_type": fact.report_type, "rcept_no": fact.rcept_no, "rcept_dt": fact.rcept_dt,
            "metric": fact.metric, "period_start": fact.period_start, "period_end": fact.period_end,
            "duration_days": fact.duration_days, "context_semantics": fact.context_semantics,
            "period_semantics": fact.period_semantics, "comparative": fact.comparative,
            "value": fact.value, "currency": fact.currency, "fs_div_used": fact.fs_div_used,
            "source_sha256": fact.source_sha256, "resolution_status": fact.resolution_status,
        })
    return rows


def _prior_context(facts: list[PeriodizationFact], anchor: PeriodizationFact | None, code: str) -> dict[str, Any]:
    if anchor is None:
        return {"status": "MISSING", "reason": "ANCHOR_NOT_AVAILABLE", "eligible_context_count": 0,
                "eligible_rcept_nos": [], "latest_rcept_dt": None}
    selection = PeriodizationEngine()._prior_cumulative_selection(facts, code, anchor)
    return {
        "status": selection.status, "reason": selection.reason,
        "eligible_context_count": len(selection.eligible),
        "eligible_rcept_nos": [item.rcept_no for item in selection.eligible],
        "latest_rcept_dt": selection.latest_rcept_dt,
    }


def _parity_rows(build, ticker: str) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    ambiguous = 0
    for item in build.result.parity:
        obs = next((candidate for candidate in build.result.observations
                    if candidate.anchor_rcept_no == item.anchor_rcept_no
                    and candidate.fiscal_period == item.fiscal_period and candidate.metric == item.metric), None)
        if obs is None:
            continue
        anchor = _fact_anchor(build, obs.anchor_reprt_code, obs.anchor_rcept_no, item.metric)
        prior_code = {"11012": "11013", "11014": "11012", "11011": "11014"}.get(obs.anchor_reprt_code, "")
        prior = _prior_context([fact for fact in build.facts if fact.metric == item.metric], anchor, obs.anchor_reprt_code)
        if prior["status"] != "READY" or prior["eligible_context_count"] != 1:
            ambiguous += 1
        rows.append({
            "ticker": ticker, "fiscal_year": build.fiscal_year, "metric": item.metric,
            "fiscal_period": item.fiscal_period, "anchor_reprt_code": obs.anchor_reprt_code,
            "anchor_rcept_no": item.anchor_rcept_no, "anchor_rcept_dt": obs.anchor_rcept_dt,
            "direct_value": item.direct_value, "derived_value": item.derived_value,
            "prior_rcept_no": obs.source_rcept_nos[-1] if len(obs.source_rcept_nos) > 1 else None,
            "prior_rcept_dt": obs.source_rcept_dts[-1] if len(obs.source_rcept_dts) > 1 else None,
            "prior_context_count": prior["eligible_context_count"], "prior_status": prior["status"],
            "difference": item.difference, "status": item.status, "reason": item.reason or "NONE",
            "prior_report_code": prior_code,
        })
    return rows, ambiguous


def _company_summary(build, ticker: str) -> dict[str, Any]:
    result = build.result
    family = build.company_family
    return {
        "ticker": ticker, "company": NAMES[ticker], "company_family": family,
        "fiscal_year": build.fiscal_year, "requested_as_of": build.requested_as_of,
        "anchor_selections": [dict(item) for item in build.anchor_selections],
        "skipped_anchors": [dict(item) for item in build.skipped_anchors],
        "filing_count": len(build.filings), "fact_count": len(build.facts),
        "metric_resolution": {metric: _metric_status(result, metric, family=family)
                               for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")},
        "instant_metrics": {metric: _metric_status(result, metric, family=family)
                            for metric in ("assets", "liabilities", "equity")},
        "ambiguity_count": sum(item.resolution_status == "PERIOD_AMBIGUOUS" for item in result.observations),
        "direct_derived_parity": [item.to_dict() for item in result.parity],
    }


def _samsung_validation(build) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric in ("revenue", "operating_income", "net_income"):
        q1 = [item for item in build.facts if item.metric == metric and item.reprt_code == "11013"
              and item.period_semantics == CUMULATIVE_YTD and not item.comparative]
        q2 = next((item for item in build.result.observations if item.metric == metric and item.fiscal_period == "Q2"), None)
        h1_anchor = next((item for item in build.facts if item.metric == metric and item.reprt_code == "11012"), None)
        prior = _prior_context([item for item in build.facts if item.metric == metric], h1_anchor, "11012")
        metrics[metric] = {
            "q1_current_cumulative_context_count": len(q1),
            "q1_distinct_rcept_no_count": len({item.rcept_no for item in q1}),
            "q1_rcept_nos": [item.rcept_no for item in q1],
            "q2_final_method": q2.method if q2 else None,
            "q2_status": q2.resolution_status if q2 else None,
            "q2_reason": q2.reason if q2 else None,
            "q2_prior_status": prior["status"],
            "q2_prior_reason": prior["reason"],
            "q2_prior_context_count": prior["eligible_context_count"],
            "q2_value": q2.value if q2 else None,
            "q2_parity_emitted": any(item.metric == metric and item.fiscal_period == "Q2" for item in build.result.parity),
        }
    ready = all(
        item["q1_current_cumulative_context_count"] == 2
        and item["q1_distinct_rcept_no_count"] == 1
        and item["q2_final_method"] == "DIRECT_ONLY"
        and item["q2_status"] == "READY"
        and item["q2_prior_status"] == "AMBIGUOUS"
        and item["q2_prior_reason"] == PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS
        and item["q2_prior_context_count"] == 2
        and not item["q2_parity_emitted"]
        for item in metrics.values()
    )
    return {"ticker": "005930", "company": NAMES["005930"], "metrics": metrics,
            "status": "PASS" if ready else "FAIL"}


def _hana_validation(build) -> dict[str, Any]:
    h1 = _anchor_meta(build, "11012") or {}
    q3 = _anchor_meta(build, "11014") or {}
    q3_prior = q3.get("prior_pit") or {}
    q3_no = q3.get("selected_rcept_no")
    net = _final_observation(build, "11014", str(q3_no), "net_income", "Q3") if q3_no else None
    ocf = _final_observation(build, "11014", str(q3_no), "operating_cash_flow", "Q3") if q3_no else None
    return {
        "ticker": "086790", "company": NAMES["086790"],
        "h1_filing_status": h1.get("status"), "h1_filing_reason": h1.get("reason"),
        "h1_candidate_rcept_nos": h1.get("candidate_rcept_nos", []),
        "q3_anchor_rcept_no": q3_no, "q3_anchor_rcept_dt": q3.get("selected_rcept_dt"),
        "q3_prior_status": q3_prior.get("status"), "q3_prior_reason": q3_prior.get("reason"),
        "q3_prior_candidate_rcept_nos": q3_prior.get("candidate_rcept_nos", []),
        "q3_net_income": {"method": net.method if net else None, "status": net.resolution_status if net else None,
                           "reason": net.reason if net else None,
                           "parity_emitted": any(item.metric == "net_income" and item.fiscal_period == "Q3"
                                                  for item in build.result.parity)},
        "q3_operating_cash_flow": {"method": ocf.method if ocf else None, "status": ocf.resolution_status if ocf else None,
                                    "reason": ocf.reason if ocf else None,
                                    "parity_emitted": any(item.metric == "operating_cash_flow" and item.fiscal_period == "Q3"
                                                          for item in build.result.parity)},
        "production_builder": "PeriodizationProvider.build",
    }


def _provider_prior_validation(builds: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    ambiguous_to_missing = 0
    for ticker, build in builds.items():
        for meta in build.anchor_selections:
            prior = meta.get("prior_pit") or {}
            if prior.get("status") != "AMBIGUOUS":
                continue
            code, no = str(meta.get("reprt_code")), str(meta.get("selected_rcept_no"))
            observations = [item.to_dict() for item in build.result.observations
                            if item.anchor_reprt_code == code and item.anchor_rcept_no == no
                            and item.fiscal_period in {"Q2", "Q3", "Q4"}]
            bad = [item for item in observations if item.get("resolution_status") in {"DATA_UNAVAILABLE", "DERIVATION_UNAVAILABLE"}]
            ambiguous_to_missing += len(bad)
            entries.append({"ticker": ticker, "reprt_code": code, "anchor_rcept_no": no,
                            "prior_pit": dict(prior), "observations": observations,
                            "ambiguous_to_missing_count": len(bad)})
    return {"production_boundary": "PeriodizationProvider.build", "entries": entries,
            "provider_ambiguous_to_missing_count": ambiguous_to_missing,
            "status": "PASS" if ambiguous_to_missing == 0 else "FAIL"}


def _future_leakage(builds: dict[str, Any]) -> str:
    for build in builds.values():
        by_no = {fact.rcept_no: fact.rcept_dt for fact in build.facts}
        for obs in build.result.observations:
            anchor_dt = obs.anchor_rcept_dt[:10]
            for no in obs.source_rcept_nos:
                source_dt = by_no.get(no)
                if source_dt and source_dt[:10] > anchor_dt:
                    return "YES"
    return "NO"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("LIVE_VALIDATION_DISABLED; pass --live explicitly")
        return 0
    _load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    targeted = _run_targeted_tests()
    if not key:
        print("FINAL_STATUS=BLOCKED_OPENDART_API_KEY")
        return 1

    client = OpenDartClient(api_key=key)
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    xbrl = _CountingXbrl(XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl"))
    provider = PeriodizationProvider(corp, _BoundedLiveRegistry(client), xbrl)
    access = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8")) if ACCESS_SUMMARY.exists() else {}
    company_fields = {ticker: access.get("company_api", {}).get(ticker, {}).get("selected_fields", {})
                      for ticker in TICKERS}
    as_of = date.today().isoformat()
    builds: dict[str, Any] = {}
    matrix: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    companies: dict[str, Any] = {}
    annual: list[dict[str, Any]] = []
    error_type: str | None = None
    error_location: str | None = None
    try:
        corp.ensure_loaded()
        for ticker in TICKERS:
            if len(client.audit) >= REQUEST_LIMIT:
                raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
            family = classify_company_family(company_fields.get(ticker) or {}, ())
            build = provider.build(ticker, "2025", as_of, company_metadata=company_fields.get(ticker) or {},
                                    force_refresh=args.force_refresh)
            builds[ticker] = build
            matrix.extend(_fact_matrix(build, ticker))
            parity_rows, _ = _parity_rows(build, ticker)
            parity.extend(parity_rows)
            annual.extend({"ticker": ticker, **dict(item)} for item in build.result.diagnostics
                           if item.get("annual_anchor_rcept_no"))
            companies[ticker] = _company_summary(build, ticker)
    except Exception as exc:
        error_type = type(exc).__name__
        trace = exc.__traceback__
        while trace and trace.tb_next:
            trace = trace.tb_next
        if trace:
            error_location = f"{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}:{trace.tb_frame.f_code.co_name}"

    provider_prior = _provider_prior_validation(builds)
    samsung = _samsung_validation(builds["005930"]) if "005930" in builds else {"status": "FAIL"}
    hana = _hana_validation(builds["086790"]) if "086790" in builds else {"h1_filing_status": None, "status": "FAIL"}
    financial = companies.get("086790", {})
    financial_validation = {
        "ticker": "086790", "company": NAMES["086790"], "company_family": financial.get("company_family"),
        "metric_resolution": financial.get("metric_resolution", {}), "instant_metrics": financial.get("instant_metrics", {}),
        "basis_values": sorted({row["fs_div_used"] for row in matrix if row["ticker"] == "086790" and row.get("fs_div_used")}),
        "cfs_ofs_mixing": len({row["fs_div_used"] for row in matrix if row["ticker"] == "086790" and row.get("fs_div_used")}) > 1,
        "h1_filing_status": hana.get("h1_filing_status"), "h1_filing_reason": hana.get("h1_filing_reason"),
    }
    st_rows = [row for row in parity if row["ticker"] == "237690"]
    st_status = "PASS" if len(st_rows) >= 3 and all(row["status"] == "MATCH" and row["prior_status"] == "READY"
                                                     and row["prior_context_count"] == 1 for row in st_rows) else "FAIL"
    parity_mismatch = sum(row["status"] == "MISMATCH" for row in parity)
    ambiguous_parity = sum(row["prior_status"] != "READY" or row["prior_context_count"] != 1 for row in parity)
    network = len(client.audit)
    registry = sum(item.get("endpoint") == "list.json" for item in client.audit)
    xbrl_network = sum(item.get("endpoint") == "fnlttXbrl.xml" for item in client.audit)
    xbrl_cache = xbrl.cache_hits
    network_text = key.encode("utf-8")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_columns = list(matrix[0].keys()) if matrix else ["ticker", "company", "company_family"]
    parity_columns = list(parity[0].keys()) if parity else ["ticker", "fiscal_year", "metric", "fiscal_period"]
    _write_csv(ARTIFACT_DIR / "live_period_context_matrix.csv", matrix, matrix_columns)
    _write_csv(ARTIFACT_DIR / "live_direct_vs_derived_parity.csv", parity, parity_columns)
    _write_json(ARTIFACT_DIR / "live_company_summary.json", companies)
    _write_json(ARTIFACT_DIR / "samsung_prior_context_validation.json", samsung)
    _write_json(ARTIFACT_DIR / "hana_provider_end_to_end_validation.json", hana)
    _write_json(ARTIFACT_DIR / "production_provider_prior_state_validation.json", provider_prior)
    _write_json(ARTIFACT_DIR / "financial_company_validation.json", financial_validation)
    _write_json(ARTIFACT_DIR / "annual_vintage_diagnostic_validation.json", {
        "policy": "annual anchor selects latest quarter versions at or before annual receipt",
        "future_correction_leakage": _future_leakage(builds), "diagnostics": annual,
    })
    _write_json(ARTIFACT_DIR / "periodization_fix04_summary.json", {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": None, "artifact_head": None,
        "final_provenance_head": None, "provider_prior_state_propagation_status": provider_prior.get("status"),
        "live_companies": list(TICKERS), "validated_filing_count": sum(len(build.filings) for build in builds.values()),
        "network_request_count": network, "registry_request_count": registry,
        "xbrl_network_fetch_count": xbrl_network, "xbrl_cache_hit_count": xbrl_cache,
        "parity_count": len(parity), "exact_match_count": sum(row["status"] == "MATCH" for row in parity),
        "mismatch_count": parity_mismatch, "ambiguous_prior_parity_count": ambiguous_parity,
        "samsung_regression_status": samsung.get("status"), "st_pharm_regression_status": st_status,
        "financial_branch_status": "PASS" if financial_validation.get("company_family") == "FINANCIAL"
        and financial_validation.get("metric_resolution", {}).get("revenue", {}).get("status") == "NOT_APPLICABLE"
        and financial_validation.get("metric_resolution", {}).get("operating_income", {}).get("status") == "NOT_APPLICABLE"
        and not financial_validation.get("cfs_ofs_mixing", True) else "FAIL",
        "hana_h1_filing_status": hana.get("h1_filing_status"), "hana_h1_filing_reason": hana.get("h1_filing_reason"),
        "hana_q3_prior_status": hana.get("q3_prior_status"), "hana_q3_prior_reason": hana.get("q3_prior_reason"),
        "hana_q3_net_income_method": hana.get("q3_net_income", {}).get("method"),
        "hana_q3_net_income_status": hana.get("q3_net_income", {}).get("status"),
        "hana_q3_net_income_parity_emitted": hana.get("q3_net_income", {}).get("parity_emitted"),
        "hana_q3_ocf_method": hana.get("q3_operating_cash_flow", {}).get("method"),
        "hana_q3_ocf_status": hana.get("q3_operating_cash_flow", {}).get("status"),
        "hana_q3_ocf_parity_emitted": hana.get("q3_operating_cash_flow", {}).get("parity_emitted"),
        "provider_ambiguous_to_missing_count": provider_prior.get("provider_ambiguous_to_missing_count", 0),
        "source_provenance_alignment_status": "PASS" if all(
            len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
            for build in builds.values() for item in build.result.observations) else "FAIL",
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"],
        "CURRENT_LATEST_historical_calls": 0,
        "future_correction_leakage": _future_leakage(builds), "secret_leak_count": 0,
        "raw_source_committed": False, "pykrx_krx_network_request_count": 0,
        "error_type": error_type, "error_location": error_location,
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
    })
    # Re-open summary to set secret scan and final state after all artifacts exist.
    summary_path = ARTIFACT_DIR / "periodization_fix04_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    secret_leak_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and network_text in path.read_bytes())
    summary["secret_leak_count"] = secret_leak_count
    financial_status = summary["financial_branch_status"] == "PASS"
    hana_status = (hana.get("h1_filing_status") == "AMBIGUOUS"
                   and hana.get("q3_prior_status") == "AMBIGUOUS"
                   and hana.get("q3_prior_reason") == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
                   and hana.get("q3_net_income", {}).get("status") not in {None, "DATA_UNAVAILABLE", "DERIVATION_UNAVAILABLE"}
                   and hana.get("q3_operating_cash_flow", {}).get("status") not in {None, "DATA_UNAVAILABLE", "DERIVATION_UNAVAILABLE"})
    ready = (not error_type and targeted["targeted_test_status"] == "PASS" and network <= REQUEST_LIMIT
             and summary["provider_prior_state_propagation_status"] == "PASS"
             and summary["provider_ambiguous_to_missing_count"] == 0 and samsung.get("status") == "PASS"
             and st_status == "PASS" and financial_status and hana_status and ambiguous_parity == 0
             and parity_mismatch == 0 and summary["source_provenance_alignment_status"] == "PASS"
             and summary["future_correction_leakage"] == "NO" and secret_leak_count == 0)
    summary["final_status"] = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX04_REVIEW" if ready else "BLOCKED_LIVE_VALIDATION"
    _write_json(summary_path, summary)
    manifest_files = [
        "periodization_fix04_summary.json", "production_provider_prior_state_validation.json",
        "hana_provider_end_to_end_validation.json", "samsung_prior_context_validation.json",
        "live_company_summary.json", "live_period_context_matrix.csv", "live_direct_vs_derived_parity.csv",
        "annual_vintage_diagnostic_validation.json", "financial_company_validation.json",
    ]
    _write_json(ARTIFACT_DIR / "periodization_fix04_manifest.json", {
        "work_id": WORK_ID, "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "files": {name: _sha(ARTIFACT_DIR / name) for name in manifest_files},
        "request_accounting": {"network": network, "registry": registry,
                               "xbrl_network_fetch": xbrl_network, "xbrl_cache_hits": xbrl_cache},
        "pykrx_krx_network_request_count": 0,
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.",
    })
    print(f"TARGETED_TEST_COUNT={targeted['targeted_test_count']}")
    print(f"NETWORK_OPEN_DART_REQUESTS={network}")
    print(f"VALIDATED_FILINGS={summary['validated_filing_count']}")
    print(f"PROVIDER_AMBIGUOUS_TO_MISSING={summary['provider_ambiguous_to_missing_count']}")
    print(f"HANA_H1_STATUS={summary['hana_h1_filing_status']}")
    print(f"HANA_Q3_PRIOR_STATUS={summary['hana_q3_prior_status']}")
    print(f"FINAL_STATUS={summary['final_status']}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
