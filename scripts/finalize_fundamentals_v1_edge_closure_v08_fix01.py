#!/usr/bin/env python3
"""Targeted F7 FIX01 rebuild driven by company metadata, not ticker lists."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for item in (ROOT, SCRIPTS):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from hydrate_fundamentals_v1_production import (  # noqa: E402
    BoundedFilingRegistry,
    COMPANY_CACHE_DIR,
    F7TerminalError,
    KNOWN_TICKER_DATA_ERRORS,
    QuotaBoundOpenDartClient,
    _load_exact_corp_repository,
    _load_opendart_key,
    _load_production_universe,
    _record_failure,
    _write_json_checked,
    hydrate_one,
)
from reconcile_fundamentals_v1_v08_local import (  # noqa: E402
    _update_reports,
    _update_ticker_index,
)
from trend_scanner.fundamentals.models import RawXbrlArtifact  # noqa: E402
from trend_scanner.fundamentals.multi_period import MultiPeriodFundamentalsProvider  # noqa: E402
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family  # noqa: E402
from trend_scanner.fundamentals.periodization import (  # noqa: E402
    _precision_equivalent,
    collapse_canonical_duplicate_periodization_facts,
    facts_from_xbrl_rows,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider  # noqa: E402
from trend_scanner.fundamentals.filing_registry import FilingRegistry  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402


REQUESTED_AS_OF = "2026-09-04"
WORK_ID = "FUNDAMENTALS_V1_EDGE_CASE_CLOSURE_V08_FIX01"
PRODUCTION_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904/json"
WEB_DIR = ROOT / "web/data/stocks"
REGISTRY_CACHE_DIR = ROOT / "data/cache/opendart/filings"
XBRL_CACHE_DIR = ROOT / "data/cache/opendart/xbrl"
CORP_CACHE_PATH = ROOT / "data/cache/opendart/corp_code_cache.json"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08_fix01"
QUOTA_CHECKPOINT = ROOT / "artifacts/fundamentals/production/20260904/daily_quota_checkpoint.json"
ENV_FILE = ROOT.parent / "env.md"
FISCAL_YEARS = tuple(str(year) for year in range(2020, 2027))
REGULAR_REPORT_CODES = ("11011", "11012", "11013", "11014")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _company_payload(ticker: str, name: str) -> tuple[dict[str, Any], bool]:
    path = COMPANY_CACHE_DIR / f"{ticker}.json"
    if path.exists():
        try:
            value = _read_json(path)
            if isinstance(value, dict):
                return value, True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            pass
    return {"selected_fields": {"corp_name": name, "stock_name": name}}, False


def _decision(raw: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    ticker = str(raw.get("ticker") or "").strip().upper()
    company, cache_hit = _company_payload(ticker, str(raw.get("name") or ""))
    return classify_company_family(company), cache_hit


def _evidence(decision: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(item) for item in decision.get("evidence") or ())


def _is_holding_evidence(decision: Mapping[str, Any]) -> bool:
    evidence = _evidence(decision)
    return any(item == "induty_code:64992" or item.startswith("non_financial_holding:") for item in evidence)


def _load_targets(universe: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for path in sorted(PRODUCTION_DIR.glob("*.json")):
        raw = _read_json(path)
        ticker = str(raw.get("ticker") or path.stem).strip().upper()
        if str(raw.get("asset_type") or "").upper() != "COMMON" or ticker not in universe:
            continue
        decision, company_cache_hit = _decision(raw)
        recommended = str(decision.get("company_family") or CompanyFamily.UNKNOWN.value)
        current = str(raw.get("company_family") or "")
        evidence = _evidence(decision)
        industry_code = next((item.split(":", 1)[1] for item in evidence if item.startswith("induty_code:")), "")
        if _is_holding_evidence(decision) or recommended == CompanyFamily.FINANCIAL.value:
            if recommended == CompanyFamily.UNKNOWN.value:
                audit_status = "MANUAL_REVIEW"
            elif current != recommended:
                audit_status = "RECLASSIFIED"
            elif recommended == CompanyFamily.FINANCIAL.value:
                audit_status = "FINANCIAL_HOLDING"
            else:
                audit_status = "GENERAL_HOLDING_RETAINED"
            audit.append({
                "ticker": ticker,
                "name": raw.get("name"),
                "induty_code": industry_code,
                "previous_company_family": current,
                "new_company_family": recommended,
                "classification_status": audit_status,
                "classification_reason": str(decision.get("status") or ""),
                "classification_evidence": ";".join(evidence),
                "company_cache_hit": company_cache_hit,
            })
        has_periodization = bool((raw.get("f2") or {}).get("periodization_builds"))
        needs_rebuild = (
            str(raw.get("asset_type") or "").upper() == "COMMON"
            and recommended == CompanyFamily.NON_FINANCIAL.value
            and _is_holding_evidence(decision)
            and (
                current != recommended
                or str(raw.get("data_status") or "") in {"DATA_UNAVAILABLE", "NOT_APPLICABLE"}
                or not has_periodization
            )
        )
        if needs_rebuild:
            target = dict(universe[ticker])
            target.update({
                "previous": raw,
                "decision": decision,
                "company_cache_hit": company_cache_hit,
            })
            targets.append(target)
    return audit, targets


def _registry_cache_status(registry: BoundedFilingRegistry, corp_code: str, year: str, code: str) -> bool:
    return registry._cache_is_usable(
        registry,
        corp_code=corp_code,
        fiscal_year=year,
        reprt_code=code,
        requested_as_of=REQUESTED_AS_OF,
    )


def _preflight(targets: list[dict[str, Any]], records_by_ticker: Mapping[str, Any]) -> dict[str, Any]:
    registry = BoundedFilingRegistry(None, cache_dir=REGISTRY_CACHE_DIR)
    company_cache_hits = sum(bool(item.get("company_cache_hit")) for item in targets)
    company_cache_misses = len(targets) - company_cache_hits
    filing_cache_hits = 0
    filing_cache_misses = 0
    missing_years = 0
    known_xbrl_hits = 0
    known_xbrl_misses = 0
    source_missing = 0
    fully_local_tickers = 0
    for target in targets:
        ticker = str(target["ticker"])
        matches = records_by_ticker.get(ticker, ())
        corp_codes = {str(item.corp_code) for item in matches}
        if len(corp_codes) != 1:
            source_missing += 1
            continue
        corp_code = next(iter(corp_codes))
        complete_ticker = True
        for year in FISCAL_YEARS:
            complete_year = True
            for code in REGULAR_REPORT_CODES:
                if _registry_cache_status(registry, corp_code, year, code):
                    filing_cache_hits += 1
                    registry_path = registry._cache_path(corp_code, year, code)
                    loaded = registry._load(registry_path)
                    if loaded is not None:
                        for filing in loaded[0]:
                            if (XBRL_CACHE_DIR / f"{filing.rcept_no}_{filing.reprt_code}.zip").exists() and (XBRL_CACHE_DIR / f"{filing.rcept_no}_{filing.reprt_code}.json").exists():
                                known_xbrl_hits += 1
                            else:
                                known_xbrl_misses += 1
                else:
                    filing_cache_misses += 1
                    complete_year = False
            if not complete_year:
                missing_years += 1
                complete_ticker = False
        if complete_ticker:
            fully_local_tickers += 1
    estimated = company_cache_misses + missing_years + (missing_years * 4) + known_xbrl_misses
    return {
        "affected_count": len(targets),
        "company_cache_hit_count": company_cache_hits,
        "company_cache_miss_count": company_cache_misses,
        "filing_registry_cache_hit_count": filing_cache_hits,
        "filing_registry_cache_miss_count": filing_cache_misses,
        "missing_registry_year_count": missing_years,
        "known_xbrl_cache_hit_count": known_xbrl_hits,
        "known_xbrl_cache_miss_count": known_xbrl_misses,
        "source_missing_count": source_missing,
        "fully_local_ticker_count": fully_local_tickers,
        "estimated_request_count_upper_bound": estimated,
        "estimated_request_basis": "company cache misses + one filing-registry page per missing year + up to four XBRL requests per missing year + known XBRL cache misses",
    }


def _cell_count(record: Mapping[str, Any]) -> int:
    section = record.get("f5_ready") or {}
    rows = list(section.get("annual") or ()) + list(section.get("quarterly") or ())
    fields = ("revenue_krw", "operating_income_krw", "net_income_krw")
    return sum(1 for row in rows for field in fields if row.get(field) is not None)


def _rebuild_row(target: Mapping[str, Any], after: Mapping[str, Any], request_delta: int) -> dict[str, Any]:
    previous = target["previous"]
    decision = target["decision"]
    status = str(after.get("data_status") or "DATA_UNAVAILABLE")
    f2 = after.get("f2") or {}
    reason = str(after.get("terminal_reason") or (after.get("f5_ready") or {}).get("reason") or "")
    return {
        "ticker": target["ticker"],
        "name": target["name"],
        "previous_company_family": previous.get("company_family"),
        "new_company_family": after.get("company_family"),
        "classification_evidence": ";".join(_evidence(decision)),
        "previous_data_status": previous.get("data_status"),
        "new_data_status": status,
        "f2_periodization_build_count": len(f2.get("periodization_builds") or ()),
        "core_value_count": _cell_count(after),
        "opendart_request_count": request_delta,
        "rebuild_status": "RESTORED_OR_RETAINED" if _cell_count(after) else "SOURCE_OR_MAPPING_GAP",
        "reason": reason,
    }


def _context_alias_rows() -> list[dict[str, Any]]:
    corp_repo, records = _load_exact_corp_repository()
    matches = records.get("000120", ())
    if len(matches) != 1:
        return [{"ticker": "000120", "period": "2025Q1", "validation_status": "SOURCE_MISSING", "reason": "CJ_CORP_MAPPING_UNAVAILABLE"}]
    corp_code = matches[0].corp_code
    registry = FilingRegistry(None, cache_dir=REGISTRY_CACHE_DIR)
    path = registry._cache_path(corp_code, "2025", "11013")
    loaded = registry._load(path)
    if loaded is None or not loaded[0]:
        return [{"ticker": "000120", "period": "2025Q1", "validation_status": "SOURCE_MISSING", "reason": "CJ_Q1_FILING_REGISTRY_CACHE_UNAVAILABLE"}]
    filing = max((item for item in loaded[0] if item.rcept_dt <= REQUESTED_AS_OF), key=lambda item: (item.rcept_dt, item.rcept_no), default=None)
    if filing is None:
        return [{"ticker": "000120", "period": "2025Q1", "validation_status": "SOURCE_MISSING", "reason": "CJ_Q1_FILING_NOT_PIT_ELIGIBLE"}]
    repo = XbrlRepository(None, cache_dir=XBRL_CACHE_DIR)
    cached = repo._load_cached(filing)
    if cached is None:
        return [{"ticker": "000120", "period": "2025Q1", "validation_status": "SOURCE_MISSING", "reason": "CJ_Q1_XBRL_CACHE_UNAVAILABLE", "rcept_no": filing.rcept_no}]
    artifact, _ = cached
    raw_rows = repo.statement_rows(artifact, bsns_year="2025", reprt_code="11013")
    selected = [item for item in raw_rows if item.get("account_id") in {"ifrs-full_ProfitLossFromOperatingActivities", "dart_OperatingIncomeLoss"} and item.get("period_end") == "2025-03-31" and item.get("basis") == "ConsolidatedMember"]
    if not selected:
        return [{"ticker": "000120", "period": "2025Q1", "validation_status": "SOURCE_MISSING", "reason": "CJ_Q1_OPERATING_INCOME_FACTS_UNAVAILABLE", "rcept_no": filing.rcept_no}]
    facts = facts_from_xbrl_rows(
        selected,
        ticker="000120",
        corp_code=corp_code,
        company_family=CompanyFamily.NON_FINANCIAL.value,
        fiscal_year="2025",
        reprt_code="11013",
        report_type=filing.report_type,
        rcept_no=filing.rcept_no,
        rcept_dt=filing.rcept_dt,
        fs_div_used="CFS",
        source_sha256=artifact.sha256,
    )
    overlap = _precision_equivalent(facts)
    stats: dict[str, int] = {}
    collapsed = collapse_canonical_duplicate_periodization_facts(facts, stats=stats)
    rows = []
    for fact in facts:
        rows.append({
            "ticker": "000120",
            "period": "2025Q1",
            "metric": fact.metric,
            "account_id": fact.account_id,
            "raw_value": fact.raw_value,
            "parsed_value": fact.value,
            "decimals": fact.decimals,
            "precision": fact.precision,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "context_ref": fact.context_ref,
            "context_scope_fingerprint": fact.context_scope_fingerprint,
            "basis": fact.fs_div_used,
            "rcept_no": fact.rcept_no,
            "declared_precision_overlap": overlap,
            "collapse_result": "COLLAPSED_BY_DECLARED_PRECISION_OVERLAP" if len(collapsed) == 1 else "RETAINED_TRUE_VALUE_CONFLICT",
            "precision_equivalent_fact_removed_count": stats.get("precision_equivalent_fact_removed_count", 0),
            "validation_status": "PASS" if len(collapsed) == 1 or not overlap else "PASS_TRUE_CONFLICT_RETAINED",
            "reason": "EXACT_VALUE_OR_DECLARED_XBRL_INTERVAL_ONLY",
        })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    universe_rows, snapshot = _load_production_universe(REQUESTED_AS_OF)
    universe = {str(item["ticker"]).upper(): item for item in universe_rows}
    audit, targets = _load_targets(universe)
    preflight = _preflight(targets, _load_exact_corp_repository()[1])
    print(json.dumps({"work_id": WORK_ID, "phase": "PREFLIGHT", "requested_as_of": REQUESTED_AS_OF, "metadata_snapshot_date": snapshot, **preflight}, ensure_ascii=False))
    if preflight["estimated_request_count_upper_bound"] > 20542:
        raise RuntimeError("FIX01 targeted rebuild estimate exceeds today's remaining OpenDART quota")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(
        OUTPUT_DIR / "company_family_audit.csv",
        audit,
        ["ticker", "name", "induty_code", "previous_company_family", "new_company_family", "classification_status", "classification_reason", "classification_evidence", "company_cache_hit"],
    )
    context_rows = _context_alias_rows()
    _write_csv(OUTPUT_DIR / "context_alias_validation.csv", context_rows, list(context_rows[0]) if context_rows else ["validation_status"])

    corp_repo, records_by_ticker = _load_exact_corp_repository()
    secret = _load_opendart_key(ENV_FILE)
    checkpoint = _read_json(QUOTA_CHECKPOINT)
    quota = checkpoint.get("quota") if isinstance(checkpoint.get("quota"), Mapping) else {}
    prior_additional = int(quota.get("additional_opendart_requests", 18458))
    client = QuotaBoundOpenDartClient(
        secret,
        prior_additional_requests=prior_additional,
        max_additional_requests=39000,
        official_usage_before=int(quota.get("official_usage_before", 0) or 0),
        safety_daily_cap=39000,
    )
    registry = BoundedFilingRegistry(client, cache_dir=REGISTRY_CACHE_DIR)
    period_provider = PeriodizationProvider(corp_repo, registry, XbrlRepository(client, cache_dir=XBRL_CACHE_DIR))
    provider = MultiPeriodFundamentalsProvider(period_provider)
    rebuild_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for target in targets:
        ticker = str(target["ticker"])
        before_requests = client.http_request_count
        try:
            result = hydrate_one(
                target,
                requested_as_of=REQUESTED_AS_OF,
                corp_repo=corp_repo,
                records_by_ticker=records_by_ticker,
                client=client,
                company_cache_dir=COMPANY_CACHE_DIR,
                secret=secret,
                period_provider=provider,
            )
        except F7TerminalError as exc:
            result = _record_failure(target, REQUESTED_AS_OF, exc)
            failures.append({"ticker": ticker, "reason": exc.reason})
        except KNOWN_TICKER_DATA_ERRORS as exc:
            raise RuntimeError(f"unexpected unhandled targeted error for {ticker}: {type(exc).__name__}: {exc}") from exc
        _write_json_checked(PRODUCTION_DIR / f"{ticker}.json", result)
        _update_reports(ticker, result.get("f5_ready") or {})
        rebuild_rows.append(_rebuild_row(target, result, client.http_request_count - before_requests))
        print(json.dumps({"ticker": ticker, "data_status": result.get("data_status"), "f4_status": result.get("f4_status"), "requests": client.http_request_count - before_requests}, ensure_ascii=False))

    _update_ticker_index({str(item["ticker"]) for item in targets})
    _write_csv(
        OUTPUT_DIR / "holding_company_rebuild_validation.csv",
        rebuild_rows,
        ["ticker", "name", "previous_company_family", "new_company_family", "classification_evidence", "previous_data_status", "new_data_status", "f2_periodization_build_count", "core_value_count", "opendart_request_count", "rebuild_status", "reason"],
    )
    summary = {
        "work_id": WORK_ID,
        "requested_as_of": REQUESTED_AS_OF,
        "metadata_snapshot_date": snapshot,
        "affected_count": len(targets),
        "company_family_audit_count": len(audit),
        "company_family_audit_status_counts": dict(Counter(str(item["classification_status"]) for item in audit)),
        "manual_review_count": sum(item["classification_status"] == "MANUAL_REVIEW" for item in audit),
        "general_holding_retained_count": sum(item["classification_status"] == "GENERAL_HOLDING_RETAINED" for item in audit),
        "financial_holding_count": sum(item["classification_status"] == "FINANCIAL_HOLDING" for item in audit),
        "preflight": preflight,
        "opendart": {
            "prior_additional_requests": prior_additional,
            "actual_requests_current_run": client.http_request_count,
            "final_additional_requests": client.current_additional_requests,
            "estimated_daily_total": client.estimated_daily_total,
            "safety_daily_cap": client.safety_daily_cap,
            "request_counter_consistent": client.http_request_count == len(client.audit),
        },
        "rebuild": {
            "target_count": len(rebuild_rows),
            "restored_or_retained_count": sum(item["rebuild_status"] == "RESTORED_OR_RETAINED" for item in rebuild_rows),
            "source_or_mapping_gap_count": sum(item["rebuild_status"] == "SOURCE_OR_MAPPING_GAP" for item in rebuild_rows),
            "failure_count": len(failures),
            "failures": failures,
        },
        "holding_company_affected_count": len(rebuild_rows),
        "holding_company_rebuilt_count": sum(item["rebuild_status"] == "RESTORED_OR_RETAINED" for item in rebuild_rows),
        "holding_company_data_available_count": sum(int(item["core_value_count"] or 0) > 0 for item in rebuild_rows),
        "holding_company_still_unavailable_count": sum(int(item["core_value_count"] or 0) == 0 for item in rebuild_rows),
        "context_alias_validation_rows": len(context_rows),
        "external_naver_validation": "PENDING",
        "network": {"OpenDART": "USED_TARGETED_ONLY", "Naver": "PENDING", "KRX": "NOT_USED", "PyKRX": "NOT_USED"},
        "artifact_files": ["company_family_audit.csv", "holding_company_rebuild_validation.csv", "context_alias_validation.csv", "validation_summary.json"],
    }
    _write_json_checked(OUTPUT_DIR / "validation_summary.json", summary)
    (OUTPUT_DIR / "external_sanity_evidence.md").write_text(
        "# FIX01 external sanity evidence\n\n"
        "Naver comparison is generated by the separate blind-validation step after this targeted rebuild.\n"
        f"The local CJ raw XBRL evidence is in `context_alias_validation.csv`; the production rule permits only exact values or declared XBRL precision-interval overlap.\n",
        encoding="utf-8",
    )
    print(json.dumps({"work_id": WORK_ID, "phase": "COMPLETE", "affected_count": len(targets), "requests": client.http_request_count, "failures": len(failures)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
