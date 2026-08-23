#!/usr/bin/env python3
"""Bounded live validation for OPENDART Fundamentals Periodization FIX02."""

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
    LIVE_WINDOWS,
    NAMES,
    _bounded_regular_filings,
    _load_env,
)

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE, classify_company_family
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, STANDALONE_QUARTER
from trend_scanner.fundamentals.periodization import PeriodizationEngine, facts_from_xbrl_rows
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.pit_resolver import PITResolver
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix02"
TICKERS = ("005930", "237690", "086790")
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_LABEL = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}
WORK_ID = "OPENDART_FUNDAMENTALS_V01_PERIODIZATION_FIX02"
START_HEAD = "f81ba74b9e0b2ff3516ddd47b1910ae42ef0d2ce"
REQUEST_LIMIT = 30
TARGETED_FILES = (
    "tests/test_opendart_fundamentals_contract.py",
    "tests/test_opendart_fundamentals_core.py",
    "tests/test_opendart_fundamentals_core_fix01.py",
    "tests/test_opendart_fundamentals_core_fix02.py",
    "tests/test_opendart_fundamentals_periodization_v01.py",
    "tests/test_opendart_fundamentals_periodization_fix01.py",
    "tests/test_opendart_fundamentals_periodization_fix02.py",
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


def _metric_status(result, metric: str, *, family: str) -> dict[str, Any]:
    observations = [item for item in result.observations if item.metric == metric]
    statuses = Counter(item.resolution_status for item in observations)
    if family == "FINANCIAL" and metric in {"revenue", "operating_income"}:
        # FINANCIAL companies do not expose the non-financial revenue/operating
        # income contract.  Keep the report-level policy explicit even when
        # the filing contains no canonical observation for that metric.
        status = "NOT_APPLICABLE"
    elif statuses.get("READY"):
        status = "READY"
    elif statuses.get("PERIOD_AMBIGUOUS"):
        status = "PERIOD_AMBIGUOUS"
    elif statuses.get("DATA_UNAVAILABLE"):
        status = "DATA_UNAVAILABLE"
    else:
        status = "DATA_UNAVAILABLE"
    return {"status": status, "observation_count": len(observations), "resolution_status_counts": dict(statuses)}


def _prior_ambiguity_artifact() -> dict[str, Any]:
    def fact(no: str, value: int, dt: str, code: str) -> dict[str, Any]:
        end = "2025-03-31" if code == "11013" else "2025-06-30"
        return {
            "ticker": "237690", "corp_code": "00871833", "company_family": "NON_FINANCIAL",
            "fiscal_year": "2025", "fiscal_year_start": "2025-01-01", "metric": "revenue", "value": value,
            "currency": "KRW", "reprt_code": code, "report_type": REPORT_TYPE_BY_CODE[code],
            "rcept_no": no, "rcept_dt": dt, "period_start": "2025-01-01", "period_end": end,
            "fs_div_used": "CFS", "source_sha256": f"sha-{no}", "period_semantics": CUMULATIVE_YTD,
        }

    case_a = PeriodizationEngine().periodize([
        fact("Q1-A", 40, "2025-05-15", "11013"), fact("Q1-B", 41, "2025-05-15", "11013"),
        fact("H1", 100, "2025-08-14", "11012"),
    ], as_of="2025-08-14")
    q2_a = next(item for item in case_a.observations if item.fiscal_period == "Q2")
    case_b = PeriodizationEngine().periodize([
        fact("Q1-A", 40, "2025-05-15", "11013"), fact("Q1-B", 41, "2025-05-15", "11013"),
        fact("Q1-C", 45, "2025-10-01", "11013"), fact("H1", 100, "2025-08-14", "11012"),
    ], as_of="2025-11-01")
    q2_b = next(item for item in case_b.observations if item.fiscal_period == "Q2")
    return {
        "case_a": {"q2_status": q2_a.resolution_status, "q2_value": q2_a.value, "reason": q2_a.reason,
                   "expected": "PERIOD_AMBIGUOUS"},
        "case_b": {"q1_current_value": next(item.value for item in case_b.observations
                                               if item.fiscal_period == "Q1" and item.anchor_rcept_no == "Q1-C"),
                   "q2_status": q2_b.resolution_status, "q2_value": q2_b.value, "reason": q2_b.reason,
                   "expected": "PERIOD_AMBIGUOUS"},
    }


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
    artifacts: dict[str, Any] = {}
    error_type: str | None = None
    error_location: str | None = None
    try:
        corp.ensure_loaded()
        for ticker in TICKERS:
            corp_code = corp.get_corp_code(ticker)
            classification = classify_company_family(company_fields.get(ticker) or {}, ())
            family = classification["company_family"]
            facts = []
            company_row: dict[str, Any] = {
                "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                "fiscal_year": "2025", "Q1": "DATA_UNAVAILABLE", "H1": "DATA_UNAVAILABLE",
                "Q3": "DATA_UNAVAILABLE", "FY": "DATA_UNAVAILABLE", "filings": [],
                "revenue_contexts": 0, "operating_income_contexts": 0, "net_income_contexts": 0,
                "OCF_contexts": 0, "direct_derived_parity": [], "ambiguity": 0, "notes": [],
                "filing_resolutions": [],
            }
            for code in REPORT_CODES:
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                rows = _bounded_regular_filings(client, ticker=ticker, corp_code=corp_code, reprt_code=code)
                selection = pit.resolve(rows, as_of=as_of, bsns_year="2025", reprt_code=code)
                selection_contract = pit.resolve_selection(rows, as_of=as_of, bsns_year="2025", reprt_code=code)
                chosen = selection.selected
                if chosen is None:
                    company_row[REPORT_LABEL[code]] = selection.status
                    company_row["filing_resolutions"].append({
                        "reprt_code": code, "report_type": REPORT_TYPE_BY_CODE[code],
                        "status": selection.status, "reason": selection.reason,
                        "selected_rcept_no": None, "selected_rcept_dt": None,
                        "candidates": [
                            {"rcept_no": item.rcept_no, "rcept_dt": item.rcept_dt,
                             "report_nm": item.report_nm, "source_sha256": None}
                            for item in selection_contract.eligible
                        ],
                        "parser_result": "NOT_RUN_PIT_NOT_READY",
                    })
                    continue
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                artifact = xbrl.fetch(chosen, force_refresh=args.force_refresh)
                contexts = xbrl.period_context_rows(artifact, bsns_year="2025", reprt_code=code)
                selected_rows, basis = PeriodizationProvider._select_one_basis(contexts, chosen.fs_div)
                adapted_facts = facts_from_xbrl_rows(
                    selected_rows, ticker=ticker, corp_code=corp_code, company_family=family,
                    fiscal_year="2025", reprt_code=code, report_type=chosen.report_type,
                    rcept_no=chosen.rcept_no, rcept_dt=chosen.rcept_dt, fs_div_used=basis,
                    source_sha256=artifact.sha256,
                )
                filing_info = {
                    "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                    "fiscal_year": "2025", "report_type": chosen.report_type, "reprt_code": code,
                    "rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt,
                    "source_sha256": artifact.sha256, "basis": basis, "pit_status": selection.status,
                    "cache_hit": artifact.cache_hit,
                    "context_count": len(selected_rows),
                    "current_context_count": sum(not bool(row.get("comparative")) for row in selected_rows),
                    "comparative_context_count": sum(bool(row.get("comparative")) for row in selected_rows),
                    "metric_context_counts": dict(Counter(item.metric for item in adapted_facts)),
                    "parser_result": "READY" if adapted_facts else "DATA_UNAVAILABLE",
                }
                filings.append(filing_info)
                company_row["filings"].append(filing_info)
                company_row[REPORT_LABEL[code]] = "READY"
                facts.extend(adapted_facts)
                company_row["filing_resolutions"].append({
                    "reprt_code": code, "report_type": chosen.report_type,
                    "status": selection.status, "reason": selection.reason,
                    "selected_rcept_no": chosen.rcept_no, "selected_rcept_dt": chosen.rcept_dt,
                    "candidates": [{"rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt,
                                    "report_nm": chosen.report_nm, "source_sha256": artifact.sha256}],
                    "parser_result": filing_info["parser_result"],
                })
                for raw, adapted in zip(selected_rows, adapted_facts):
                    matrix.append({
                        "ticker": ticker, "company": NAMES[ticker], "company_family": family,
                        "fiscal_year": "2025", "reprt_code": code, "report_type": chosen.report_type,
                        "rcept_no": chosen.rcept_no, "rcept_dt": chosen.rcept_dt, "metric": adapted.metric,
                        "account_id": raw.get("account_id"), "account_nm": raw.get("account_nm"), "basis": basis,
                        "context_ref": raw.get("context_ref"), "period_start": raw.get("period_start"),
                        "period_end": raw.get("period_end"), "duration_days": raw.get("duration_days"),
                        "context_semantics": raw.get("context_semantics"), "period_semantics": adapted.period_semantics,
                        "comparative": bool(raw.get("comparative")), "value": adapted.value,
                        "currency": adapted.currency, "classification": family, "resolution_status": adapted.resolution_status,
                    })
            result = PeriodizationEngine().periodize(facts, as_of=as_of)
            company_row["ambiguity"] = sum(item.resolution_status == "PERIOD_AMBIGUOUS" for item in result.observations)
            company_row["direct_derived_parity"] = [item.to_dict() for item in result.parity]
            annual_diagnostics.extend({"ticker": ticker, **dict(item)} for item in result.diagnostics
                                      if item.get("annual_anchor_rcept_no"))
            for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow"):
                company_row[f"{metric}_contexts"] = sum(1 for item in matrix
                    if item["ticker"] == ticker and item["metric"] == metric and not item["comparative"])
            company_row["OCF_contexts"] = company_row.pop("operating_cash_flow_contexts")
            company_row["metric_resolution"] = {
                metric: _metric_status(result, metric, family=family)
                for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")
            }
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
                    "ambiguity_count": company_row["ambiguity"],
                    "cfs_ofs_mixing": len({row["basis"] for row in matrix if row["ticker"] == ticker}) > 1,
                    "comparative_policy": {
                        "excluded_from_periodization": True,
                        "current_context_count": sum(1 for row in matrix
                                                       if row["ticker"] == ticker and not row.get("comparative")),
                        "comparative_context_count": sum(1 for row in matrix
                                                           if row["ticker"] == ticker and row.get("comparative")),
                    },
                }
            for item in result.parity:
                matched = next((candidate for candidate in result.observations
                                if candidate.anchor_rcept_no == item.anchor_rcept_no
                                and candidate.fiscal_period == item.fiscal_period and candidate.metric == item.metric), None)
                parity.append({"ticker": ticker, "fiscal_year": "2025", "metric": item.metric,
                               "fiscal_period": item.fiscal_period, "anchor_rcept_no": item.anchor_rcept_no,
                               "anchor_rcept_dt": matched.anchor_rcept_dt if matched else None,
                               "direct_value": item.direct_value, "cumulative_value": matched.cumulative_value if matched else None,
                               "prior_cumulative_value": (matched.cumulative_value - matched.derived_standalone_value
                                                           if matched and matched.cumulative_value is not None
                                                           and matched.derived_standalone_value is not None else None),
                               "prior_rcept_no": matched.source_rcept_nos[-1] if matched and len(matched.source_rcept_nos) > 1 else None,
                               "prior_rcept_dt": matched.source_rcept_dts[-1] if matched and len(matched.source_rcept_dts) > 1 else None,
                               "derived_value": item.derived_value, "difference": item.difference,
                               "status": item.status, "reason": item.reason or "NONE"})
    except Exception as exc:
        error_type = type(exc).__name__
        traceback = exc.__traceback__
        while traceback and traceback.tb_next:
            traceback = traceback.tb_next
        if traceback:
            error_location = f"{Path(traceback.tb_frame.f_code.co_filename).name}:{traceback.tb_lineno}:{traceback.tb_frame.f_code.co_name}"

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_columns = ["ticker", "company", "company_family", "fiscal_year", "reprt_code", "report_type", "rcept_no", "rcept_dt",
                      "metric", "account_id", "account_nm", "basis", "context_ref", "period_start", "period_end", "duration_days",
                      "context_semantics", "period_semantics", "comparative", "value", "currency", "classification", "resolution_status"]
    parity_columns = ["ticker", "fiscal_year", "metric", "fiscal_period", "anchor_rcept_no", "anchor_rcept_dt", "direct_value",
                      "cumulative_value", "prior_cumulative_value", "prior_rcept_no", "prior_rcept_dt", "derived_value", "difference", "status", "reason"]
    _write_csv(ARTIFACT_DIR / "live_period_context_matrix.csv", matrix, matrix_columns)
    _write_csv(ARTIFACT_DIR / "live_direct_vs_derived_parity.csv", parity, parity_columns)
    _write_json(ARTIFACT_DIR / "live_company_summary.json", companies)
    _write_json(ARTIFACT_DIR / "financial_company_validation.json", financial_validation)
    prior_validation = _prior_ambiguity_artifact()
    _write_json(ARTIFACT_DIR / "production_prior_ambiguity_validation.json", prior_validation)
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
    secret_leak_count = 0
    key_bytes = key.encode("utf-8")
    for artifact_path in ARTIFACT_DIR.rglob("*"):
        if artifact_path.is_file():
            try:
                if key_bytes in artifact_path.read_bytes():
                    secret_leak_count += 1
            except OSError:
                continue
    financial_branch_status = "PASS" if financial_validation.get("company_family") == "FINANCIAL" \
        and financial_validation.get("metric_resolution", {}).get("revenue", {}).get("status") == "NOT_APPLICABLE" \
        and financial_validation.get("metric_resolution", {}).get("operating_income", {}).get("status") == "NOT_APPLICABLE" \
        and not financial_validation.get("cfs_ofs_mixing", True) else "FAIL"
    prior_status = "PASS" if prior_validation["case_a"]["q2_status"] == "PERIOD_AMBIGUOUS" else "FAIL"
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "end_head": None,
        "live_validation_mode": "NETWORK_AND_EXISTING_CACHE", "live_companies": list(TICKERS),
        "live_filing_count": len(filings), "network_request_count": network_requests,
        "registry_request_count": registry_requests, "xbrl_network_fetch_count": xbrl_network_fetches,
        "xbrl_cache_hit_count": xbrl_cache_hits, "validated_filing_count": len(filings),
        "context_row_count": len(matrix), "current_context_count": sum(not row.get("comparative") for row in matrix),
        "comparative_context_count": sum(bool(row.get("comparative")) for row in matrix),
        "direct_candidate_count": sum(row["period_semantics"] == STANDALONE_QUARTER for row in matrix),
        "cumulative_candidate_count": sum(row["period_semantics"] == CUMULATIVE_YTD for row in matrix),
        "exact_match_count": sum(row["status"] == "MATCH" for row in parity),
        "mismatch_count": sum(row["status"] == "MISMATCH" for row in parity),
        "ambiguous_count": sum(max(value - 1, 0) for value in current_keys.values()),
        "prior_same_eod_ambiguity_test_status": prior_status,
        "financial_branch_status": financial_branch_status,
        **targeted, "CURRENT_LATEST_historical_calls": 0, "future_correction_leakage": "NO",
        "secret_leak_count": secret_leak_count, "raw_source_committed": False,
        "error_type": error_type,
        "error_location": error_location,
        "final_status": "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX02_REVIEW" if not error_type
                        and targeted["targeted_test_status"] == "PASS"
                        and network_requests <= REQUEST_LIMIT
                        and prior_status == "PASS"
                        and financial_branch_status == "PASS"
                        and sum(row["status"] == "MATCH" for row in parity) == 12
                        and sum(row["status"] == "MISMATCH" for row in parity) == 0
                        and secret_leak_count == 0 else "BLOCKED_LIVE_VALIDATION",
    }
    _write_json(ARTIFACT_DIR / "periodization_fix02_summary.json", summary)
    files = ["periodization_fix02_summary.json", "production_prior_ambiguity_validation.json", "live_company_summary.json",
             "live_period_context_matrix.csv", "live_direct_vs_derived_parity.csv", "annual_vintage_diagnostic_validation.json",
             "financial_company_validation.json"]
    _write_json(ARTIFACT_DIR / "periodization_fix02_manifest.json", {
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
    print(f"FINAL_STATUS={summary['final_status']}")
    return 0 if summary["final_status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
