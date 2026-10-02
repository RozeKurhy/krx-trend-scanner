#!/usr/bin/env python3
"""Bounded OpenDART cache hydration for the B Select Core OI 1Q V03 study.

Only the company, filing-registry and XBRL caches needed to read the latest
quarter (and its prior-year same quarter) for every B Select Core CONTROL
entry signal are filled.  Existing complete caches are reused untouched.
The backtest itself runs later, cache-only, behind a socket guard.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.hydrate_fundamentals_v1_production import _load_company_metadata  # noqa: E402
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository  # noqa: E402
from trend_scanner.fundamentals.filing_registry import FilingRegistry, FilingRegistryApiError  # noqa: E402
from trend_scanner.fundamentals.opendart_client import OpenDartClient, OpenDartError  # noqa: E402
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402

CACHE = ROOT / "data/cache/opendart"
HYDRATION_AS_OF = "2026-08-31"
XBRL_FIRST_YEAR = 2015
REQUEST_BUDGET = 15_000


def _load_key() -> str:
    key = os.getenv("OPENDART_API_KEY", "").strip()
    if key:
        return key
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENDART_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENDART_API_KEY_MISSING")


def needed_years(signal_dates: pd.Series, first_year: int = XBRL_FIRST_YEAR) -> list[int]:
    years: set[int] = set()
    for value in signal_dates:
        year = int(str(value)[:4])
        years.update(y for y in (year - 2, year - 1, year) if y >= first_year)
    return sorted(years)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals", required=True, help="CSV with ticker, entry_signal_date")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--first-year", type=int, default=XBRL_FIRST_YEAR,
                        help="earliest fiscal year whose registry/XBRL cache is filled")
    args = parser.parse_args()

    signals = pd.read_csv(args.signals, dtype=str)
    key = _load_key()
    client = OpenDartClient(key)
    corp = CorpCodeRepository.from_cache(CACHE / "corp_code_cache.json")
    provider = PeriodizationProvider(
        corp,
        FilingRegistry(client, cache_dir=CACHE / "filings"),
        XbrlRepository(client, cache_dir=CACHE / "xbrl"),
    )
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    started = time.time()
    aborted = None
    for number, (ticker, group) in enumerate(signals.groupby("ticker", sort=True), start=1):
        if len(client.audit) >= REQUEST_BUDGET:
            aborted = "REQUEST_BUDGET_REACHED"
            break
        try:
            record = corp.get_record(ticker)
        except Exception as exc:  # noqa: BLE001 - recorded as an identity gap
            rows.append({"ticker": ticker, "year": None, "status": "NO_CORP_CODE", "detail": type(exc).__name__})
            continue
        try:
            payload, cache_hit = _load_company_metadata(client, ticker, record.corp_code, key, CACHE / "company")
            counts["company_cache_hit" if cache_hit else "company_fetched"] += 1
        except Exception as exc:  # noqa: BLE001 - recorded as a company gap
            text = str(exc).replace(key, "***")
            rows.append({"ticker": ticker, "year": None, "status": "COMPANY_UNAVAILABLE", "detail": text[:200]})
            continue
        family = str(classify_company_family(payload, ()).get("company_family") or CompanyFamily.UNKNOWN.value)
        if family != CompanyFamily.NON_FINANCIAL.value:
            rows.append({"ticker": ticker, "year": None, "status": f"SKIP_{family}", "detail": ""})
            continue
        for year in needed_years(group["entry_signal_date"], args.first_year):
            before = len(client.audit)
            try:
                build = provider.build(ticker, str(year), HYDRATION_AS_OF, company_metadata=payload)
                status = "BUILT"
                detail = f"observations={len(build.result.observations)}"
            except FilingRegistryApiError as exc:
                status = f"REGISTRY_API_{exc.status or exc.classification}"
                detail = str(exc).replace(key, "***")[:200]
                if str(exc.status) == "020":
                    aborted = "RATE_LIMIT"
            except OpenDartError as exc:
                status = f"OPENDART_{getattr(exc, 'status', None) or getattr(exc, 'classification', None)}"
                detail = str(exc).replace(key, "***")[:200]
                if str(getattr(exc, "status", "")) == "020":
                    aborted = "RATE_LIMIT"
            except Exception as exc:  # noqa: BLE001 - kept visible in the ledger
                status = f"ERROR_{type(exc).__name__}"
                detail = str(exc).replace(key, "***")[:200]
            counts[status] += 1
            rows.append({
                "ticker": ticker, "corp_code": record.corp_code, "year": year, "status": status,
                "detail": detail, "api_requests": len(client.audit) - before,
            })
            if aborted:
                break
        if aborted:
            break
        if number % 25 == 0:
            print(f"hydrate {number} tickers, requests={len(client.audit)}, {dict(counts)}", flush=True)
    ledger = pd.DataFrame(rows)
    Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(args.ledger, index=False)
    summary = {
        "hydration_as_of": HYDRATION_AS_OF,
        "tickers": int(signals["ticker"].nunique()),
        "api_requests": len(client.audit),
        "status_counts": dict(counts),
        "aborted": aborted,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    Path(args.ledger).with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
