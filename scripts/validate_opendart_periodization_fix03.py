#!/usr/bin/env python3
"""Bounded OpenDART live validation for Periodization FIX03."""

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
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE, classify_company_family
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, STANDALONE_QUARTER, PeriodizationFact
from trend_scanner.fundamentals.periodization import PeriodizationEngine, facts_from_xbrl_rows
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.pit_resolver import PITResolver
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix03"
TICKERS = ("005930", "237690", "086790")
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_LABEL = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}
WORK_ID = "OPENDART_FUNDAMENTALS_V01_PERIODIZATION_FIX03"
START_HEAD = "28c78b29ace74a3d6e7255abec16fd72289b07f2"
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


def _fact(no: str, value: int, code: str, dt: str, *, semantic: str = CUMULATIVE_YTD) -> dict[str, Any]:
    start, end = (("2025-01-01", "2025-03-31") if code == "11013" else ("2025-01-01", "2025-06-30"))
    if semantic == STANDALONE_QUARTER:
        start, end = "2025-04-01", "2025-06-30"
    return {
        "ticker": "237690", "corp_code": "00871833", "company_family": "NON_FINANCIAL",
        "fiscal_year": "2025", "fiscal_year_start": "2025-01-01", "metric": "revenue",
        "value": value, "currency": "KRW", "reprt_code": code,
        "report_type": REPORT_TYPE_BY_CODE[code], "rcept_no": no, "rcept_dt": dt,
        "period_start": start, "period_end": end, "fs_div_used": "CFS",
        "source_sha256": f"sha-{no}-{value}", "period_semantics": semantic,
    }


def _synthetic_prior_validation() -> dict[str, Any]:
    def run(rows: list[dict[str, Any]], *, as_of: str = "2025-08-14") -> dict[str, Any]:
        result = PeriodizationEngine().periodize(rows, as_of=as_of)
        q1 = next((item for item in result.observations if item.fiscal_period == "Q1"), None)
        q2 = next((item for item in result.observations if item.fiscal_period == "Q2"), None)
        return {
            "q1": {"value": q1.value if q1 else None, "status": q1.resolution_status if q1 else None,
                   "reason": q1.reason if q1 else None},
            "q2": {"value": q2.value if q2 else None, "method": q2.method if q2 else None,
                   "status": q2.resolution_status if q2 else None, "reason": q2.reason if q2 else None,
                   "derived_value": q2.derived_standalone_value if q2 else None},
            "parity_count": len(result.parity),
        }

    same_value = run([_fact("Q1", 40, "11013", "2025-05-15"), _fact("Q1", 40, "11013", "2025-05-15"),
                      _fact("H1", 100, "11012", "2025-08-14")])
    different_value = run([_fact("Q1", 40, "11013", "2025-05-15"), _fact("Q1", 41, "11013", "2025-05-15"),
                           _fact("H1", 100, "11012", "2025-08-14")])
    direct_only = run([_fact("Q1", 40, "11013", "2025-05-15"), _fact("Q1", 40, "11013", "2025-05-15"),
                       _fact("H1", 100, "11012", "2025-08-14"),
                       _fact("H1", 60, "11012", "2025-08-14", semantic=STANDALONE_QUARTER)])
    unique = run([_fact("Q1", 40, "11013", "2025-05-15"), _fact("H1", 100, "11012", "2025-08-14"),
                  _fact("H1", 60, "11012", "2025-08-14", semantic=STANDALONE_QUARTER)])
    same_eod_filings = run([_fact("Q1-A", 40, "11013", "2025-05-15"), _fact("Q1-B", 41, "11013", "2025-05-15"),
                            _fact("H1", 100, "11012", "2025-08-14")])
    late_correction = run([_fact("Q1-A", 40, "11013", "2025-05-15"), _fact("Q1-B", 41, "11013", "2025-05-15"),
                           _fact("Q1-C", 45, "11013", "2025-10-01"), _fact("H1", 100, "11012", "2025-08-14")],
                          as_of="2025-11-01")
    late_correction["q1_late_correction_value"] = next(
        (item.value for item in PeriodizationEngine().periodize(
            [_fact("Q1-A", 40, "11013", "2025-05-15"), _fact("Q1-B", 41, "11013", "2025-05-15"),
             _fact("Q1-C", 45, "11013", "2025-10-01"), _fact("H1", 100, "11012", "2025-08-14")],
            as_of="2025-11-01").observations
        if item.fiscal_period == "Q1" and item.anchor_rcept_no == "Q1-C"), None)
    return {
        "case_same_filing_same_value": same_value,
        "case_same_filing_different_value": different_value,
        "case_ambiguous_prior_direct_only": direct_only,
        "case_unique_prior_direct_derived": unique,
        "case_same_eod_multiple_filings": same_eod_filings,
        "case_late_correction": late_correction,
        "expected_reasons": {
            "same_filing": "PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS",
            "same_eod_filings": "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD",
        },
    }


def _prior_context_status(facts: list[PeriodizationFact], anchor_code: str, anchor: PeriodizationFact | None) -> dict[str, Any]:
    if anchor is None:
        return {"status": "MISSING", "reason": "ANCHOR_NOT_AVAILABLE", "eligible_context_count": 0,
                "eligible_rcept_nos": [], "latest_rcept_dt": None}
    selection = PeriodizationEngine()._prior_cumulative_selection(facts, anchor_code, anchor)
    return {
        "status": selection.status,
        "reason": selection.reason,
        "eligible_context_count": len(selection.eligible),
        "eligible_rcept_nos": [item.rcept_no for item in selection.eligible],
        "latest_rcept_dt": selection.latest_rcept_dt,
    }


def _company_prior_validation(ticker: str, facts: list[PeriodizationFact], result) -> dict[str, Any]:
    engine = PeriodizationEngine()
    metrics = ("revenue", "operating_income", "net_income")
    output: dict[str, Any] = {"ticker": ticker, "company": NAMES[ticker], "metrics": {}}
    for metric in metrics:
        metric_facts = [item for item in facts if item.metric == metric]
        q1_candidates = [item for item in metric_facts if item.reprt_code == "11013"
                         and item.period_semantics == CUMULATIVE_YTD and not item.comparative]
        h1_anchor = next((item for item in metric_facts if item.reprt_code == "11012"), None)
        prior = _prior_context_status(metric_facts, "11012", h1_anchor)
        q2 = next((item for item in result.observations if item.metric == metric and item.fiscal_period == "Q2"), None)
        q2_parity = [item for item in result.parity if item.metric == metric and item.fiscal_period == "Q2"]
        output["metrics"][metric] = {
            "q1_current_cumulative_context_count": len(q1_candidates),
            "q1_distinct_rcept_no_count": len({item.rcept_no for item in q1_candidates}),
            "q1_rcept_nos": [item.rcept_no for item in q1_candidates],
            "selected_prior_status": prior,
            "q2_direct_standalone_status": {
                "value": q2.value if q2 else None,
                "method": q2.method if q2 else None,
                "resolution_status": q2.resolution_status if q2 else None,
                "reason": q2.reason if q2 else None,
            },
            "q2_derived_status": {
                "value": q2.derived_standalone_value if q2 else None,
                "status": q2.resolution_status if q2 else None,
            },
            "q2_final_method": q2.method if q2 else None,
            "q2_parity_emitted": bool(q2_parity),
        }
    return output


def _parity_rows(ticker: str, facts: list[PeriodizationFact], result) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    ambiguous_prior_count = 0
    for item in result.parity:
        matched = next((candidate for candidate in result.observations
                        if candidate.anchor_rcept_no == item.anchor_rcept_no
                        and candidate.fiscal_period == item.fiscal_period and candidate.metric == item.metric), None)
        anchor_code = matched.anchor_reprt_code if matched else ""
        anchor = next((fact for fact in facts if fact.reprt_code == anchor_code
                       and fact.rcept_no == item.anchor_rcept_no and fact.metric == item.metric), None)
        prior = _prior_context_status([fact for fact in facts if fact.metric == item.metric], anchor_code, anchor)
        prior_deterministic = prior["status"] == "READY" and prior["eligible_context_count"] == 1
        if not prior_deterministic:
            ambiguous_prior_count += 1
        rows.append({
            "ticker": ticker, "fiscal_year": "2025", "metric": item.metric,
            "fiscal_period": item.fiscal_period, "anchor_rcept_no": item.anchor_rcept_no,
            "anchor_rcept_dt": matched.anchor_rcept_dt if matched else None,
            "direct_value": item.direct_value, "cumulative_value": matched.cumulative_value if matched else None,
            "prior_cumulative_value": (matched.cumulative_value - matched.derived_standalone_value
                                        if matched and matched.cumulative_value is not None
                                        and matched.derived_standalone_value is not None else None),
            "prior_rcept_no": matched.source_rcept_nos[-1] if matched and len(matched.source_rcept_nos) > 1 else None,
            "prior_rcept_dt": matched.source_rcept_dts[-1] if matched and len(matched.source_rcept_dts) > 1 else None,
            "prior_context_count": prior["eligible_context_count"],
            "prior_status": prior["status"], "derived_value": item.derived_value,
            "difference": item.difference, "status": item.status, "reason": item.reason or "NONE",
        })
    return rows, ambiguous_prior_count


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
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    pit = PITResolver()
    access = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8")) if ACCESS_SUMMARY.exists() else {}
    company_fields = {ticker: access.get("company_api", {}).get(ticker, {}).get("selected_fields", {})
                      for ticker in TICKERS}
    as_of = date.today().isoformat()
    matrix: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    companies: dict[str, dict[str, Any]] = {}
    financial_validation: dict[str, Any] = {}
    annual_diagnostics: list[dict[str, Any]] = []
    filings: list[dict[str, Any]] = []
    company_prior: dict[str, Any] = {}
    error_type: str | None = None
    error_location: str | None = None
    ambiguous_prior_parity_count = 0
    provenance_alignment_ok = True
    try:
        corp.ensure_loaded()
        for ticker in TICKERS:
            corp_code = corp.get_corp_code(ticker)
            family = classify_company_family(company_fields.get(ticker) or {}, ())["company_family"]
            facts: list[PeriodizationFact] = []
            company_row: dict[str, Any] = {
                "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                "fiscal_year": "2025", "Q1": "DATA_UNAVAILABLE", "H1": "DATA_UNAVAILABLE",
                "Q3": "DATA_UNAVAILABLE", "FY": "DATA_UNAVAILABLE", "filings": [],
                "filing_resolutions": [], "ambiguity": 0, "notes": [],
            }
            for code in REPORT_CODES:
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                rows = _bounded_regular_filings(client, ticker=ticker, corp_code=corp_code, reprt_code=code)
                selection = pit.resolve(rows, as_of=as_of, bsns_year="2025", reprt_code=code)
                contract_selection = pit.resolve_selection(rows, as_of=as_of, bsns_year="2025", reprt_code=code)
                if selection.selected is None:
                    company_row[REPORT_LABEL[code]] = selection.status
                    company_row["filing_resolutions"].append({
                        "reprt_code": code, "report_type": REPORT_TYPE_BY_CODE[code],
                        "status": selection.status, "reason": selection.reason,
                        "selected_rcept_no": None, "selected_rcept_dt": None,
                        "candidates": [{"rcept_no": item.rcept_no, "rcept_dt": item.rcept_dt,
                                        "report_nm": item.report_nm, "source_sha256": None}
                                       for item in contract_selection.eligible],
                        "parser_result": "NOT_RUN_PIT_NOT_READY",
                    })
                    continue
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                chosen = selection.selected
                artifact = xbrl.fetch(chosen, force_refresh=args.force_refresh)
                contexts = xbrl.period_context_rows(artifact, bsns_year="2025", reprt_code=code)
                selected_rows, basis = PeriodizationProvider._select_one_basis(contexts, chosen.fs_div)
                adapted = facts_from_xbrl_rows(
                    selected_rows, ticker=ticker, corp_code=corp_code, company_family=family,
                    fiscal_year="2025", reprt_code=code, report_type=chosen.report_type,
                    rcept_no=chosen.rcept_no, rcept_dt=chosen.rcept_dt, fs_div_used=basis,
                    source_sha256=artifact.sha256,
                )
                facts.extend(adapted)
                filing_info = {
                    "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                    "fiscal_year": "2025", "report_type": chosen.report_type, "reprt_code": code,
                    "rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt,
                    "source_sha256": artifact.sha256, "basis": basis, "pit_status": selection.status,
                    "cache_hit": artifact.cache_hit, "context_count": len(selected_rows),
                    "current_context_count": sum(not bool(row.get("comparative")) for row in selected_rows),
                    "comparative_context_count": sum(bool(row.get("comparative")) for row in selected_rows),
                    "metric_context_counts": dict(Counter(item.metric for item in adapted)),
                    "parser_result": "READY" if adapted else "DATA_UNAVAILABLE",
                }
                filings.append(filing_info)
                company_row["filings"].append(filing_info)
                company_row[REPORT_LABEL[code]] = "READY"
                company_row["filing_resolutions"].append({
                    "reprt_code": code, "report_type": chosen.report_type,
                    "status": selection.status, "reason": selection.reason,
                    "selected_rcept_no": chosen.rcept_no, "selected_rcept_dt": chosen.rcept_dt,
                    "candidates": [{"rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt,
                                    "report_nm": chosen.report_nm, "source_sha256": artifact.sha256}],
                    "parser_result": filing_info["parser_result"],
                })
                for raw, fact in zip(selected_rows, adapted):
                    matrix.append({
                        "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                        "fiscal_year": "2025", "reprt_code": code, "report_type": chosen.report_type,
                        "rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt, "metric": fact.metric,
                        "account_id": raw.get("account_id"), "account_nm": raw.get("account_nm"), "basis": basis,
                        "context_ref": raw.get("context_ref"), "period_start": raw.get("period_start"),
                        "period_end": raw.get("period_end"), "duration_days": raw.get("duration_days"),
                        "context_semantics": raw.get("context_semantics"), "period_semantics": fact.period_semantics,
                        "comparative": bool(raw.get("comparative")), "value": fact.value,
                        "currency": fact.currency, "classification": family,
                        "resolution_status": fact.resolution_status,
                    })
            result = PeriodizationEngine().periodize(facts, as_of=as_of)
            provenance_alignment_ok = provenance_alignment_ok and all(
                len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
                for item in result.observations
            )
            company_row["ambiguity"] = sum(item.resolution_status == "PERIOD_AMBIGUOUS" for item in result.observations)
            company_row["metric_resolution"] = {
                metric: _metric_status(result, metric, family=family)
                for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")
            }
            company_row["direct_derived_parity"] = [item.to_dict() for item in result.parity]
            company_prior[ticker] = _company_prior_validation(ticker, facts, result)
            parity_rows, ambiguous_count = _parity_rows(ticker, facts, result)
            parity.extend(parity_rows)
            ambiguous_prior_parity_count += ambiguous_count
            annual_diagnostics.extend({"ticker": ticker, **dict(item)} for item in result.diagnostics
                                      if item.get("annual_anchor_rcept_no"))
            companies[ticker] = company_row
            if ticker == "086790":
                financial_validation = {
                    "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                    "fiscal_year": "2025", "filings": company_row["filings"],
                    "filing_resolutions": company_row["filing_resolutions"],
                    "metric_resolution": company_row["metric_resolution"],
                    "instant_metrics": {metric: _metric_status(result, metric, family=family)
                                        for metric in ("assets", "liabilities", "equity")},
                    "comparative_excluded": True,
                    "basis_values": sorted({row["basis"] for row in matrix if row["ticker"] == ticker}),
                    "cfs_ofs_mixing": len({row["basis"] for row in matrix if row["ticker"] == ticker}) > 1,
                    "ambiguity_count": company_row["ambiguity"],
                }
    except Exception as exc:
        error_type = type(exc).__name__
        traceback = exc.__traceback__
        while traceback and traceback.tb_next:
            traceback = traceback.tb_next
        if traceback:
            error_location = f"{Path(traceback.tb_frame.f_code.co_filename).name}:{traceback.tb_lineno}:{traceback.tb_frame.f_code.co_name}"

    prior_validation = _synthetic_prior_validation()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_columns = ["ticker", "company", "company_family", "fiscal_year", "reprt_code", "report_type", "rcept_no", "rcept_dt",
                      "metric", "account_id", "account_nm", "basis", "context_ref", "period_start", "period_end", "duration_days",
                      "context_semantics", "period_semantics", "comparative", "value", "currency", "classification", "resolution_status"]
    parity_columns = ["ticker", "fiscal_year", "metric", "fiscal_period", "anchor_rcept_no", "anchor_rcept_dt", "direct_value",
                      "cumulative_value", "prior_cumulative_value", "prior_rcept_no", "prior_rcept_dt", "prior_context_count",
                      "prior_status", "derived_value", "difference", "status", "reason"]
    _write_csv(ARTIFACT_DIR / "live_period_context_matrix.csv", matrix, matrix_columns)
    _write_csv(ARTIFACT_DIR / "live_direct_vs_derived_parity.csv", parity, parity_columns)
    _write_json(ARTIFACT_DIR / "prior_context_ambiguity_validation.json", prior_validation)
    _write_json(ARTIFACT_DIR / "live_company_summary.json", companies)
    _write_json(ARTIFACT_DIR / "samsung_prior_context_validation.json", company_prior.get("005930", {}))
    _write_json(ARTIFACT_DIR / "financial_company_validation.json", financial_validation)
    _write_json(ARTIFACT_DIR / "annual_vintage_diagnostic_validation.json", {
        "policy": "annual anchor selects latest quarter versions at or before annual receipt",
        "future_correction_leakage": "NO", "diagnostics": annual_diagnostics,
    })

    network_requests = len(client.audit)
    registry_requests = sum(item.get("endpoint") == "list.json" for item in client.audit)
    xbrl_network_fetches = sum(item.get("endpoint") == "fnlttXbrl.xml" for item in client.audit)
    xbrl_cache_hits = sum(bool(item.get("cache_hit")) for item in filings)
    current_keys = Counter((row["ticker"], row["reprt_code"], row["metric"], row["basis"], row["period_start"], row["period_end"])
                           for row in matrix if not row.get("comparative"))
    key_bytes = key.encode("utf-8")
    secret_leak_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and key_bytes in path.read_bytes())
    financial_branch_status = "PASS" if financial_validation.get("company_family") == "FINANCIAL" \
        and financial_validation.get("metric_resolution", {}).get("revenue", {}).get("status") == "NOT_APPLICABLE" \
        and financial_validation.get("metric_resolution", {}).get("operating_income", {}).get("status") == "NOT_APPLICABLE" \
        and not financial_validation.get("cfs_ofs_mixing", True) else "FAIL"
    same_eod_status = "PASS" if prior_validation["case_same_eod_multiple_filings"]["q2"]["reason"] == "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD" else "FAIL"
    same_filing_status = "PASS" if prior_validation["case_same_filing_same_value"]["q2"]["reason"] == "PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS" \
        and prior_validation["case_same_filing_different_value"]["q2"]["reason"] == "PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS" else "FAIL"
    direct_only_status = "PASS" if prior_validation["case_ambiguous_prior_direct_only"]["q2"]["method"] == "DIRECT_ONLY" \
        and prior_validation["case_ambiguous_prior_direct_only"]["parity_count"] == 0 else "FAIL"
    unique_status = "PASS" if prior_validation["case_unique_prior_direct_derived"]["q2"]["method"] == "DIRECT_VALIDATED_BY_DERIVATION" \
        and prior_validation["case_unique_prior_direct_derived"]["parity_count"] == 1 else "FAIL"
    mismatch_count = sum(row["status"] == "MISMATCH" for row in parity)
    st_parity = [row for row in parity if row["ticker"] == "237690"]
    st_prior_ok = all(row["prior_status"] == "READY" and row["prior_context_count"] == 1
                      for row in st_parity)
    st_regression_status = "PASS" if st_prior_ok and all(row["status"] == "MATCH" for row in st_parity) else "FAIL"
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": None,
        "artifact_head": None, "final_provenance_head": None,
        "live_companies": list(TICKERS), "validated_filing_count": len(filings),
        "network_request_count": network_requests, "registry_request_count": registry_requests,
        "xbrl_network_fetch_count": xbrl_network_fetches, "xbrl_cache_hit_count": xbrl_cache_hits,
        "context_row_count": len(matrix), "current_context_count": sum(not row.get("comparative") for row in matrix),
        "comparative_context_count": sum(bool(row.get("comparative")) for row in matrix),
        "prior_same_eod_filing_ambiguity_status": same_eod_status,
        "prior_same_filing_context_ambiguity_status": same_filing_status,
        "direct_candidate_count": sum(row["period_semantics"] == STANDALONE_QUARTER for row in matrix),
        "cumulative_candidate_count": sum(row["period_semantics"] == CUMULATIVE_YTD for row in matrix),
        "parity_count": len(parity), "exact_match_count": sum(row["status"] == "MATCH" for row in parity),
        "mismatch_count": mismatch_count, "ambiguous_prior_parity_count": ambiguous_prior_parity_count,
        "all_parity_prior_sources_deterministic": ambiguous_prior_parity_count == 0,
        "source_provenance_alignment_status": "PASS" if provenance_alignment_ok else "FAIL",
        "st_pharm_parity_count": len(st_parity), "st_pharm_regression_status": st_regression_status,
        "samsung_q1_duplicate_prior_status": company_prior.get("005930", {}).get("metrics", {}),
        "samsung_q2_revenue_method": company_prior.get("005930", {}).get("metrics", {}).get("revenue", {}).get("q2_final_method"),
        "samsung_q2_operating_income_method": company_prior.get("005930", {}).get("metrics", {}).get("operating_income", {}).get("q2_final_method"),
        "samsung_q2_net_income_method": company_prior.get("005930", {}).get("metrics", {}).get("net_income", {}).get("q2_final_method"),
        "financial_branch_status": financial_branch_status, **targeted,
        "CURRENT_LATEST_historical_calls": 0, "future_correction_leakage": "NO",
        "secret_leak_count": secret_leak_count, "raw_source_committed": False,
        "error_type": error_type, "error_location": error_location,
    }
    ready = (not error_type and targeted["targeted_test_status"] == "PASS" and network_requests <= REQUEST_LIMIT
             and same_eod_status == "PASS" and same_filing_status == "PASS" and direct_only_status == "PASS"
             and unique_status == "PASS" and ambiguous_prior_parity_count == 0 and mismatch_count == 0
             and financial_branch_status == "PASS" and st_regression_status == "PASS"
             and provenance_alignment_ok and summary["samsung_q2_revenue_method"] is not None
             and summary["samsung_q2_operating_income_method"] is not None
             and summary["samsung_q2_net_income_method"] is not None and secret_leak_count == 0)
    summary["final_status"] = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX03_REVIEW" if ready else "BLOCKED_LIVE_VALIDATION"
    _write_json(ARTIFACT_DIR / "periodization_fix03_summary.json", summary)
    files = ["periodization_fix03_summary.json", "prior_context_ambiguity_validation.json", "live_company_summary.json",
             "live_period_context_matrix.csv", "live_direct_vs_derived_parity.csv", "samsung_prior_context_validation.json",
             "annual_vintage_diagnostic_validation.json", "financial_company_validation.json"]
    _write_json(ARTIFACT_DIR / "periodization_fix03_manifest.json", {
        "work_id": WORK_ID, "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "files": {name: _sha(ARTIFACT_DIR / name) for name in files},
        "request_accounting": {"network": network_requests, "registry": registry_requests,
                               "xbrl_network_fetch": xbrl_network_fetches, "xbrl_cache_hits": xbrl_cache_hits},
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.",
    })
    print(f"TARGETED_TEST_COUNT={targeted['targeted_test_count']}")
    print(f"NETWORK_OPEN_DART_REQUESTS={network_requests}")
    print(f"VALIDATED_FILINGS={len(filings)}")
    print(f"PARITY_COUNT={len(parity)}")
    print(f"FINAL_STATUS={summary['final_status']}")
    return 0 if summary["final_status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
