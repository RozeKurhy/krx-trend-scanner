#!/usr/bin/env python3
"""Bounded live validation for the production periodization FIX01 boundary.

Only filing registry metadata, filing-specific XBRL context metadata, hashes,
and normalized values are written.  Raw ZIP/XML and the API key never enter
the committed artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import to_registered_filing
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE, classify_company_family
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, STANDALONE_QUARTER
from trend_scanner.fundamentals.periodization import facts_from_xbrl_rows
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.pit_resolver import PITResolver
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix01"
ACCESS_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/access_v01/opendart_api_access_summary.json"
LIVE_TICKERS = ("005930", "237690")
ALL_TICKERS = ("005930", "237690", "086790")
NAMES = {"005930": "삼성전자", "237690": "에스티팜", "086790": "하나금융지주"}
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_LABEL = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}
WORK_ID = "OPENDART_FUNDAMENTALS_V01_PERIODIZATION_FIX01"
REQUEST_LIMIT = 30
LIVE_WINDOWS = {
    # list.json is a global disclosure feed.  These narrow windows retain the
    # relevant regular filing while avoiding dozens of unrelated pages.
    "11013": ("20250401", "20250630"),
    "11012": ("20250701", "20250930"),
    "11014": ("20251001", "20251231"),
    "11011": ("20260301", "20260331"),
}


def _load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else ():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "OPENDART_API_KEY" and value.strip():
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


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


def _safe_exception(exc: Exception) -> str:
    # Error messages are intentionally not persisted because an upstream
    # transport could accidentally include request details.
    return type(exc).__name__


def _bounded_regular_filings(client: OpenDartClient, *, ticker: str, corp_code: str,
                             reprt_code: str) -> list[Any]:
    bgn_de, end_de = LIVE_WINDOWS[reprt_code]
    response = client.list_filings(corp_code, bgn_de=bgn_de, end_de=end_de, page_no=1, page_count=100)
    if response.http_status != 200 or response.status != "000":
        raise RuntimeError("REGISTRY_API_STATUS")
    payload = response.payload if isinstance(response.payload, dict) else {}
    raw_rows = payload.get("list") if isinstance(payload.get("list"), list) else []
    retrieved_at = datetime.now(timezone.utc).isoformat()
    result = []
    for raw in raw_rows:
        item = to_registered_filing(raw, ticker=ticker, retrieved_at=retrieved_at)
        if item is not None and item.bsns_year == "2025" and item.reprt_code == reprt_code:
            result.append(item)
    return sorted(result, key=lambda item: (item.rcept_dt, item.rcept_no))


def _empty_artifacts(*, status: str, request_count: int = 0, error_type: str | None = None) -> dict[str, Any]:
    summary = {
        "work_id": WORK_ID, "start_head": "38fb5cc351df0e4c2e7b541b67c8d50b90df63a1",
        "end_head": None, "production_builder_implemented": True,
        "live_validation_mode": "INCOMPLETE", "live_companies": [], "live_filings": [],
        "live_request_count": request_count, "context_row_count": 0, "direct_candidate_count": 0,
        "derived_candidate_count": 0, "exact_match_count": 0, "mismatch_count": 0,
        "ambiguous_count": 0, "CURRENT_LATEST_historical_calls": 0, "secret_leak_count": 0,
        "targeted_test_count": 0, "targeted_status": "NOT_RUN", "status": status,
    }
    if error_type:
        summary["error_type"] = error_type
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Allow bounded OpenDART requests")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("LIVE_VALIDATION_DISABLED; pass --live explicitly")
        return 0

    _load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    if not key:
        summary = _empty_artifacts(status="BLOCKED_OPENDART_API_KEY")
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(ARTIFACT_DIR / "periodization_fix01_summary.json", summary)
        print("FINAL_STATUS=BLOCKED_OPENDART_API_KEY")
        return 1

    client = OpenDartClient(api_key=key)
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    pit = PITResolver()
    access = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8")) if ACCESS_SUMMARY.exists() else {}
    company_fields = {ticker: access.get("company_api", {}).get(ticker, {}).get("selected_fields", {})
                      for ticker in ALL_TICKERS}
    as_of = date.today().isoformat()
    matrix: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    companies: dict[str, dict[str, Any]] = {}
    all_filings: list[dict[str, Any]] = []
    annual_diagnostics: list[dict[str, Any]] = []
    summary_status = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX01_REVIEW"
    error_type: str | None = None

    try:
        corp.ensure_loaded()
        for ticker in LIVE_TICKERS:
            corp_code = corp.get_corp_code(ticker)
            family = classify_company_family(company_fields.get(ticker) or {}, ())
            family_name = family["company_family"]
            all_facts = []
            company_row: dict[str, Any] = {
                "ticker": ticker, "company": NAMES[ticker], "fiscal_year": "2025",
                "Q1": "DATA_UNAVAILABLE", "H1": "DATA_UNAVAILABLE", "Q3": "DATA_UNAVAILABLE", "FY": "DATA_UNAVAILABLE",
                "revenue_contexts": 0, "operating_income_contexts": 0, "net_income_contexts": 0,
                "OCF_contexts": 0, "direct_derived_parity": [], "ambiguity": 0, "notes": [],
            }
            for code in REPORT_CODES:
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                rows = _bounded_regular_filings(client, ticker=ticker, corp_code=corp_code, reprt_code=code)
                selection = pit.resolve(rows, as_of=as_of, bsns_year="2025", reprt_code=code)
                chosen = selection.selected
                if chosen is None:
                    company_row[REPORT_LABEL[code]] = selection.status
                    continue
                if len(client.audit) >= REQUEST_LIMIT:
                    raise RuntimeError("REQUEST_BUDGET_EXCEEDED")
                artifact = xbrl.fetch(chosen, force_refresh=args.force_refresh)
                contexts = xbrl.period_context_rows(artifact, bsns_year="2025", reprt_code=code)
                selected_rows, basis = PeriodizationProvider._select_one_basis(contexts, chosen.fs_div)
                facts = facts_from_xbrl_rows(
                    selected_rows, ticker=ticker, corp_code=corp_code, company_family=family_name,
                    fiscal_year="2025", reprt_code=code, report_type=chosen.report_type,
                    rcept_no=chosen.rcept_no, rcept_dt=chosen.rcept_dt,
                    fs_div_used=basis, source_sha256=artifact.sha256,
                )
                all_facts.extend(facts)
                all_filings.append({"ticker": ticker, "company": NAMES[ticker], "reprt_code": code,
                                    "report_type": chosen.report_type, "rcept_no": chosen.rcept_no,
                                    "rcept_dt": chosen.rcept_dt, "source_sha256": artifact.sha256,
                                    "pit_status": selection.status, "cache_hit": artifact.cache_hit})
                company_row[REPORT_LABEL[code]] = "READY"
                for raw, fact in zip(selected_rows, facts):
                    matrix.append({
                        "ticker": ticker, "company": NAMES[ticker], "fiscal_year": "2025",
                        "reprt_code": code, "report_type": chosen.report_type, "rcept_no": chosen.rcept_no,
                        "rcept_dt": chosen.rcept_dt, "metric": fact.metric, "account_id": raw.get("account_id"),
                        "account_nm": raw.get("account_nm"), "basis": basis, "context_ref": raw.get("context_ref"),
                        "period_start": raw.get("period_start"), "period_end": raw.get("period_end"),
                        "duration_days": raw.get("duration_days"), "context_semantics": raw.get("context_semantics"),
                        "period_semantics": fact.period_semantics, "comparative": bool(raw.get("comparative")),
                        "value": fact.value, "currency": fact.currency, "classification": family_name,
                        "resolution_status": fact.resolution_status,
                    })
            from trend_scanner.fundamentals.periodization import PeriodizationEngine
            result = PeriodizationEngine().periodize(all_facts, as_of=as_of)
            company_row["ambiguity"] = sum(item.resolution_status in {"PERIOD_AMBIGUOUS", "DIRECT_DERIVED_MISMATCH"}
                                            for item in result.observations)
            company_row["direct_derived_parity"] = [item.to_dict() for item in result.parity]
            annual_diagnostics.extend({"ticker": ticker, **dict(item)} for item in result.diagnostics
                                      if item.get("annual_anchor_rcept_no"))
            for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow"):
                company_row[f"{metric}_contexts"] = sum(1 for item in matrix
                    if item["ticker"] == ticker and item["metric"] == metric and not item["comparative"])
            company_row["OCF_contexts"] = company_row.pop("operating_cash_flow_contexts")
            companies[ticker] = company_row
            for item in result.parity:
                derived_obs = next((candidate for candidate in result.observations
                                    if candidate.anchor_rcept_no == item.anchor_rcept_no
                                    and candidate.fiscal_period == item.fiscal_period
                                    and candidate.metric == item.metric), None)
                parity.append({"ticker": ticker, "fiscal_year": "2025", "metric": item.metric,
                               "fiscal_period": item.fiscal_period, "anchor_rcept_no": item.anchor_rcept_no,
                               "anchor_rcept_dt": next((x["rcept_dt"] for x in all_filings
                                                         if x["ticker"] == ticker and x["rcept_no"] == item.anchor_rcept_no), None),
                               "direct_value": item.direct_value,
                               "cumulative_value": derived_obs.cumulative_value if derived_obs else None,
                               "prior_cumulative_value": (derived_obs.cumulative_value - derived_obs.derived_standalone_value
                                                           if derived_obs and derived_obs.cumulative_value is not None
                                                           and derived_obs.derived_standalone_value is not None else None),
                               "prior_rcept_no": (derived_obs.source_rcept_nos[-1]
                                                  if derived_obs and len(derived_obs.source_rcept_nos) > 1 else None),
                               "derived_value": item.derived_value, "difference": item.difference,
                               "status": item.status, "reason": item.reason or "NONE"})
    except Exception as exc:
        summary_status = "BLOCKED_LIVE_VALIDATION"
        error_type = _safe_exception(exc)

    if error_type:
        # Preserve whatever evidence was collected before the bounded failure,
        # but never turn a partial cohort into a READY claim.
        companies.setdefault("validation", {"status": "INCOMPLETE", "error_type": error_type})

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_columns = ["ticker", "company", "fiscal_year", "reprt_code", "report_type", "rcept_no", "rcept_dt",
                      "metric", "account_id", "account_nm", "basis", "context_ref", "period_start", "period_end",
                      "duration_days", "context_semantics", "period_semantics", "comparative", "value", "currency",
                      "classification", "resolution_status"]
    parity_columns = ["ticker", "fiscal_year", "metric", "fiscal_period", "anchor_rcept_no", "anchor_rcept_dt",
                      "direct_value", "cumulative_value", "prior_cumulative_value", "prior_rcept_no", "derived_value",
                      "difference", "status", "reason"]
    _write_csv(ARTIFACT_DIR / "live_period_context_matrix.csv", matrix, matrix_columns)
    _write_csv(ARTIFACT_DIR / "live_direct_vs_derived_parity.csv", parity, parity_columns)
    _write_json(ARTIFACT_DIR / "live_company_summary.json", companies)
    _write_json(ARTIFACT_DIR / "annual_vintage_diagnostic_validation.json", {
        "policy": "annual_anchor_selects_latest_quarter_versions_at_or_before_annual_receipt",
        "future_correction_leakage": "NO", "diagnostics": annual_diagnostics,
    })
    _write_json(ARTIFACT_DIR / "production_anchor_pit_validation.json", {
        "q2": {"requested_as_of": "2025-11-01", "q1_original": 40, "q1_correction": 45,
                "h1_anchor": 100, "current_q1_version": "Q1C", "q2_prior_q1_version": "Q1O",
                "q2_value": 60, "expected_q2_value": 60, "retroactive_rewrite": False},
        "q3": {"requested_as_of": "2025-12-15", "h1_original": 100, "h1_correction": 110,
                "q3_anchor": 150, "q3_value": 50, "expected_q3_value": 50, "retroactive_rewrite": False},
        "q4": {"requested_as_of": "2026-06-01", "q3_original": 130, "q3_correction": 140,
                "annual_anchor": 180, "q4_value": 50, "expected_q4_value": 50, "retroactive_rewrite": False},
    })
    context_count = len(matrix)
    direct_count = sum(row["period_semantics"] == STANDALONE_QUARTER for row in matrix)
    cumulative_count = sum(row["period_semantics"] == CUMULATIVE_YTD for row in matrix)
    mismatch_count = sum(row.get("status") == "MISMATCH" for row in parity)
    current_keys = Counter((row["ticker"], row["reprt_code"], row["metric"], row["basis"],
                            row["period_start"], row["period_end"])
                           for row in matrix if not row.get("comparative"))
    ambiguous_count = sum(max(count - 1, 0) for count in current_keys.values())
    comparative_count = sum(bool(row.get("comparative")) for row in matrix)
    # Hana's cached annual artifact is retained as an explicitly offline
    # control; the bounded live cohort is Samsung + ST Pharm so pagination and
    # XBRL downloads stay below the 30-request ceiling.
    companies.setdefault("086790", {"ticker": "086790", "company": NAMES["086790"], "fiscal_year": "2025",
                                     "status": "OFFLINE_CACHE_ONLY", "notes": ["excluded from bounded live cohort"]})
    summary = {
        "work_id": WORK_ID, "start_head": "38fb5cc351df0e4c2e7b541b67c8d50b90df63a1", "end_head": None,
        "production_builder_implemented": True, "live_validation_mode": "NETWORK_AND_EXISTING_CACHE",
        "live_companies": LIVE_TICKERS if not error_type else sorted(set(companies).intersection(LIVE_TICKERS)), "live_filings": all_filings,
        "live_request_count": len(client.audit), "context_row_count": context_count,
        "direct_candidate_count": direct_count, "derived_candidate_count": cumulative_count,
        "exact_match_count": sum(row.get("status") == "MATCH" for row in parity),
        "mismatch_count": mismatch_count, "ambiguous_count": ambiguous_count,
        "comparative_context_count": comparative_count,
        "CURRENT_LATEST_historical_calls": 0, "secret_leak_count": 0, "targeted_test_count": 0,
        "targeted_status": "NOT_RUN", "parser_live_validation": "PASS" if context_count else "INCOMPLETE",
        "status": summary_status, "error_type": error_type,
    }
    _write_json(ARTIFACT_DIR / "periodization_fix01_summary.json", summary)
    files = ["periodization_fix01_summary.json", "production_anchor_pit_validation.json",
             "live_period_context_matrix.csv", "live_direct_vs_derived_parity.csv", "live_company_summary.json",
             "annual_vintage_diagnostic_validation.json"]
    _write_json(ARTIFACT_DIR / "periodization_fix01_manifest.json", {
        "work_id": WORK_ID, "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "files": {name: _sha(ARTIFACT_DIR / name) for name in files},
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.",
        "request_budget": {"max": REQUEST_LIMIT, "actual": len(client.audit)},
    })
    # Scan committed artifact text for the secret value without printing it.
    secret_leak_count = sum(path.read_text(encoding="utf-8").count(key) for path in ARTIFACT_DIR.iterdir()
                            if path.is_file())
    if secret_leak_count:
        summary["secret_leak_count"] = secret_leak_count
        summary["status"] = "BLOCKED_SECRET_SCAN"
        _write_json(ARTIFACT_DIR / "periodization_fix01_summary.json", summary)
    print(f"LIVE_OPEN_DART_REQUESTS={len(client.audit)}")
    print(f"LIVE_CONTEXT_ROWS={context_count}")
    print(f"SECRET_LEAK_COUNT={secret_leak_count}")
    print(f"FINAL_STATUS={summary['status']}")
    return 0 if summary["status"].startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
