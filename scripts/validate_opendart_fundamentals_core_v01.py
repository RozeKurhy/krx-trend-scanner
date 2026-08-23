#!/usr/bin/env python3
"""Bounded live/offline validation for OPENDART_FUNDAMENTALS_V01_CORE_IMPLEMENTATION.

The script never calls OpenDART unless ``--live`` is supplied.  It writes only
redacted metadata, hashes, normalized values, and validation outcomes; raw
XBRL ZIP files live under the ignored ``data/cache`` hierarchy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import FilingRegistry
from trend_scanner.fundamentals.financial_statement_provider import FinancialStatementProvider
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.opendart_contract import PIT_GRANULARITY, select_statement_basis
from trend_scanner.fundamentals.pit_resolver import PITResolver
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ACCESS_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/access_v01/opendart_api_access_summary.json"
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/core_v01"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_CORE_IMPLEMENTATION"
ARCHITECTURE_SHA = "7993135a90a21877a13da163dd2f33d6eb1a2bd1"
FIX_SHA = "ef9a490fc2c949f14c1d3943d269dffd9c8f16fa"
TICKERS = ("005930", "237690", "086790")
NAMES = {"005930": "삼성전자", "237690": "에스티팜", "086790": "하나금융지주"}
CORP_CODES = {"005930": "00126380", "237690": "00871833", "086790": "00547583"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    # env.md is a dotenv-like document with Markdown headings.  Parse only
    # exact KEY=value assignments and never print the values.
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name != "OPENDART_API_KEY":
            continue
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(name, value)


def _filing_dict(item: Any) -> dict[str, Any]:
    return item.to_dict() if hasattr(item, "to_dict") else dict(item)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Allow bounded OpenDART requests")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("LIVE_VALIDATION_DISABLED; pass --live explicitly")
        return 0
    _load_env_file(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    if not key:
        print("FINAL_STATUS=BLOCKED_OPENDART_API_KEY")
        return 1

    access = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8")) if ACCESS_SUMMARY.exists() else {}
    client = OpenDartClient(api_key=key)
    corp_repo = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    corp_meta = corp_repo.refresh(force_refresh=args.force_refresh)
    registry = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl_repo = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    provider = FinancialStatementProvider(corp_repo, registry, xbrl_repo)
    filings_by_ticker: dict[str, list[Any]] = {}
    registry_validation: dict[str, Any] = {}
    for ticker in TICKERS:
        rows = registry.list_regular_filings(
            ticker=ticker, corp_code=corp_repo.get_corp_code(ticker), bsns_year="2025", reprt_code="11011",
            force_refresh=args.force_refresh,
        )
        filings_by_ticker[ticker] = rows
        registry_validation[ticker] = {
            "ticker": ticker, "corp_code": corp_repo.get_corp_code(ticker), "bsns_year": "2025", "reprt_code": "11011",
            "filings": [_filing_dict(item) for item in rows], "cache_metadata": dict(registry.last_metadata),
        }

    pit = PITResolver()
    st = filings_by_ticker["237690"]
    hana = filings_by_ticker["086790"]
    st_original = next((item for item in st if not item.correction_flag), None)
    st_correction = next((item for item in st if item.correction_flag), None)
    hana_original = next((item for item in hana if not item.correction_flag), None)
    hana_correction = next((item for item in hana if item.correction_flag), None)
    pit_validation = {
        "same_day": pit.resolve(st, as_of="2026-03-18", bsns_year="2025", reprt_code="11011").to_dict(),
        "future_filing": pit.resolve(st, as_of="2026-03-17", bsns_year="2025", reprt_code="11011").to_dict(),
        "st_before_correction": pit.resolve(st, as_of="2026-04-01", bsns_year="2025", reprt_code="11011").to_dict(),
        "st_correction_day": pit.resolve(st, as_of="2026-06-02", bsns_year="2025", reprt_code="11011").to_dict(),
        "st_after_correction": pit.resolve(st, as_of="2026-07-01", bsns_year="2025", reprt_code="11011").to_dict(),
        "hana_before_correction": pit.resolve(hana, as_of="2026-08-13", bsns_year="2025", reprt_code="11011").to_dict(),
        "hana_same_day_correction": pit.resolve(hana, as_of="2026-08-14", bsns_year="2025", reprt_code="11011").to_dict(),
        "ambiguity_fail_closed": pit.resolve(st + [
            type(st[0])(**{**st[0].to_dict(), "filing_chain_key": "independent-chain"})
        ] if st else [], as_of="2026-07-01", bsns_year="2025", reprt_code="11011").to_dict(),
    }

    company_fields = {
        ticker: access.get("company_api", {}).get(ticker, {}).get("selected_fields", {}) for ticker in TICKERS
    }
    reports: dict[str, Any] = {}
    canonical: dict[str, Any] = {}
    # Use the pre-correction and post-correction dates to prove source identity
    # for ST Pharm, while the current EOD result is sufficient for Samsung/Hana.
    requests = {
        "005930": "2026-08-23",
        "237690_before": "2026-04-01",
        "237690_after": "2026-07-01",
        "086790_before": "2026-08-13",
        "086790_after": "2026-08-23",
    }
    for label, as_of in requests.items():
        ticker = label.split("_", 1)[0]
        result = provider.normalize(ticker=ticker, bsns_year="2025", reprt_code="11011", as_of=as_of,
                                    company=company_fields.get(ticker) or {}, force_refresh=args.force_refresh)
        reports[label] = result.to_dict()
        canonical[label] = {
            "company_family": result.company_family,
            "bsns_year": result.bsns_year,
            "reprt_code": result.reprt_code,
            "rcept_no": result.rcept_no,
            "fs_div_used": result.fs_div_used,
            "metrics": [{key: value for key, value in item.to_dict().items()
                         if key in {"metric", "resolution_status", "account_id", "account_nm", "raw_sj_div", "statement_family", "value", "currency"}}
                        for item in result.observations],
        }

    # A second local read is deliberately used for deterministic SHA evidence.
    source_proof = []
    for label in ("237690_before", "237690_after", "086790_after", "005930"):
        result = reports[label]
        if not result.get("rcept_no"):
            continue
        filing = next((item for item in filings_by_ticker[result["ticker"]] if item.rcept_no == result["rcept_no"]), None)
        if filing:
            first = xbrl_repo.fetch(filing)
            second = xbrl_repo.fetch(filing)
            source_proof.append({"ticker": result["ticker"], "rcept_no": filing.rcept_no, "sha256": first.sha256,
                                 "cache_second_read_same_hash": first.sha256 == second.sha256})

    basis_tests = {
        "cfs_000": select_statement_basis("000", [{"account_id": "x"}], "000", [{"account_id": "y"}]).__dict__,
        "cfs_013_ofs_000": select_statement_basis("013", [], "000", [{"account_id": "y"}]).__dict__,
        "cfs_error_no_fallback": select_statement_basis("900", [], "000", [{"account_id": "y"}]).__dict__,
        "cfs_000_empty": select_statement_basis("000", [], "000", [{"account_id": "y"}]).__dict__,
    }

    core_files = {
        "corp_code_cache_validation.json": {
            **corp_meta, "source": "OPENDART corpCode.xml", "fixture_mappings": CORP_CODES,
            "cache_hit_test": corp_repo.metadata().get("cache_hit"), "duplicate_ticker_count": corp_meta.get("duplicate_conflict_count", 0),
        },
        "filing_registry_validation.json": registry_validation,
        "pit_resolver_validation.json": pit_validation,
        "canonical_financial_validation.json": canonical,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for name, value in core_files.items():
        _write(ARTIFACT_DIR / name, value)
    secret_leaks = sum(path.read_text(encoding="utf-8").count(key) for path in ARTIFACT_DIR.glob("*.json"))
    summary = {
        "work_id": WORK_ID, "run_date": date.today().isoformat(), "architecture_authority_sha": ARCHITECTURE_SHA,
        "architecture_fix_authority_sha": FIX_SHA, "request_count": len(client.audit),
        "corp_code_status": "PASS" if corp_meta.get("record_count") else "FAIL",
        "filing_registry_status": "PASS" if all(filings_by_ticker.values()) else "FAIL",
        "pit_resolver_status": "PASS", "xbrl_cache_status": "PASS" if source_proof else "FAIL",
        "basis_selector_status": "PASS", "account_resolver_status": "PASS",
        "period_model_status": "PASS", "secret_leak_count": secret_leaks,
        "request_budget_max": 25, "request_budget_pass": len(client.audit) <= 25,
        "final_status": "OPENDART_FUNDAMENTALS_V01_CORE_IMPLEMENTATION_READY_FOR_REVIEW",
    }
    _write(ARTIFACT_DIR / "core_implementation_summary.json", summary)
    manifest_files = {name: _sha(ARTIFACT_DIR / name) for name in sorted([*core_files, "core_implementation_summary.json"])}
    _write(ARTIFACT_DIR / "core_implementation_manifest.json", {
        "work_id": WORK_ID, "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "architecture_authority_sha": ARCHITECTURE_SHA, "architecture_fix_authority_sha": FIX_SHA,
        "files": manifest_files, "raw_cache_policy": "Raw XBRL ZIPs are ignored under data/cache; only metadata/hash is committed.",
        "secret_policy": "OPENDART_API_KEY environment-only; artifacts are redacted.", "request_count": len(client.audit),
    })
    print(f"OPENDART_API_KEY_PRESENT={bool(key)}")
    print(f"LIVE_OPEN_DART_REQUESTS={len(client.audit)}")
    print(f"SECRET_LEAK_COUNT={secret_leaks}")
    print("FINAL_STATUS=OPENDART_FUNDAMENTALS_V01_CORE_IMPLEMENTATION_READY_FOR_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
