"""Cache-only PIT evaluation of the latest-quarter operating income for many signals.

This is the V03 FIX01 evaluation path (moved here unchanged so the research
runners and the display-only B Select fundamental status share one
implementation).  For each ``(ticker, isu_cd, entry_signal_date)`` it finds
the latest fiscal quarter filed by that date from the filing registry, reads
PIT-ready canonical periodization values, never falls back to an older
quarter, and keeps the existing fail-closed policy.  It never opens a network
connection: registry and XBRL caches are read with no OpenDART client.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.backtest.b_select_core_oi_1q_v03 import (
    OPERATING_INCOME_MIN_KRW,
    UNAVAILABLE,
    evaluate_signal,
)
from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import _as_date
from trend_scanner.fundamentals.corp_code_repository import ExactCorpCodeRepository
from trend_scanner.fundamentals.filing_registry import FilingRegistry
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family
from trend_scanner.fundamentals.period_models import READY
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


CACHE_RELATIVE = Path("data/cache/opendart")
FIRST_FISCAL_YEAR = 2013
REGULAR_CODES = ("11013", "11012", "11014", "11011")


def _company_payload(cache: Path, ticker: str) -> dict[str, Any] | None:
    path = cache / "company" / f"{ticker}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if str(payload.get("status") or "") == "000" else None


def _needed_years(dates: Iterable[str], first_fiscal_year: int) -> list[int]:
    years: set[int] = set()
    for value in dates:
        year = int(value[:4])
        years.update(y for y in (year - 2, year - 1, year) if y >= first_fiscal_year)
    return sorted(years)


def _blocking_detail(observations: list[Any], label: str | None, as_of: str, prior: bool) -> str:
    """Reasons carried by the latest PIT vintage that blocked a current/prior value."""

    if not label:
        return ""
    year = int(label[:4]) - (1 if prior else 0)
    quarter = label[4:]
    cutoff = _as_date(as_of)
    items = [item for item in observations
             if str(item.fiscal_year) == str(year) and str(item.fiscal_period) == quarter
             and str(item.metric) == "operating_income"
             and _as_date(item.pit_available_from or item.anchor_rcept_dt) is not None
             and _as_date(item.pit_available_from or item.anchor_rcept_dt) <= cutoff]
    if not items:
        return "NO_OBSERVATION"
    latest = max(_as_date(item.pit_available_from or item.anchor_rcept_dt) for item in items)
    blocking = sorted({f"{item.resolution_status}:{item.reason}" for item in items
                       if _as_date(item.pit_available_from or item.anchor_rcept_dt) == latest
                       and str(item.resolution_status) != READY})
    return "|".join(blocking) or "READY_SIBLINGS_ONLY"


def evaluate_pit_signals(
    candidates: Iterable[Mapping[str, Any]],
    *,
    repo_root: Path | str,
    min_operating_income_krw: int = OPERATING_INCOME_MIN_KRW,
    first_fiscal_year: int = FIRST_FISCAL_YEAR,
    build_as_of: str | None = None,
    network_errors: tuple[type[BaseException], ...] = (),
    progress: bool = False,
) -> pd.DataFrame:
    """Evaluate every candidate at its own ``entry_signal_date``.

    ``build_as_of`` fixes the periodization build date for every ticker (the
    research runners pass their execution-support date).  When omitted, each
    ticker is built at its latest candidate date so that no filing up to any
    candidate date is left out.  ``network_errors`` are re-raised instead of
    being recorded as a cache gap.
    """

    cache = Path(repo_root) / CACHE_RELATIVE
    corp = ExactCorpCodeRepository.from_cache(cache / "corp_code_cache.json")
    registry = FilingRegistry(None, cache_dir=cache / "filings")
    provider = PeriodizationProvider(corp, registry, XbrlRepository(None, cache_dir=cache / "xbrl"))
    by_ticker: dict[str, list[Mapping[str, Any]]] = {}
    for row in candidates:
        by_ticker.setdefault(str(row["ticker"]), []).append(row)
    rows: list[dict[str, Any]] = []
    for number, (ticker, group) in enumerate(sorted(by_ticker.items()), start=1):
        payload = _company_payload(cache, ticker)
        family = (str(classify_company_family(payload, ()).get("company_family") or CompanyFamily.UNKNOWN.value)
                  if payload else CompanyFamily.UNKNOWN.value)
        try:
            corp_code = corp.get_record(ticker).corp_code
        except Exception:  # noqa: BLE001
            corp_code = None
        observations: list[Any] = []
        build_failed: dict[int, str] = {}
        dates = [str(row["entry_signal_date"])[:10] for row in group]
        ticker_build_as_of = build_as_of or max(dates)
        if payload is not None and corp_code and family == CompanyFamily.NON_FINANCIAL.value:
            for year in _needed_years(dates, first_fiscal_year):
                try:
                    build = provider.build(ticker, str(year), ticker_build_as_of, company_metadata=payload)
                    observations.extend(build.result.observations)
                except network_errors:
                    raise
                except Exception as exc:  # noqa: BLE001 - bounded cache gap for one fiscal year
                    build_failed[year] = type(exc).__name__
        for row in group:
            as_of = str(row["entry_signal_date"])[:10]
            reason = None
            filings: list[dict[str, Any]] = []
            if payload is None:
                reason = "COMPANY_METADATA_UNAVAILABLE"
            elif corp_code is None:
                reason = "CORP_CODE_UNAVAILABLE"
            elif family == CompanyFamily.NON_FINANCIAL.value:
                year = int(as_of[:4])
                for fiscal_year in (year - 1, year):
                    for code in REGULAR_CODES:
                        try:
                            listed = registry.list_regular_filings(
                                ticker=ticker, corp_code=corp_code, bsns_year=str(fiscal_year),
                                reprt_code=code, as_of=as_of,
                            )
                        except network_errors:
                            raise
                        except Exception as exc:  # noqa: BLE001
                            reason = f"REGISTRY_CACHE_UNAVAILABLE_{type(exc).__name__}"
                            break
                        filings.extend(item.to_dict() for item in listed)
                    if reason:
                        break
            evaluation = evaluate_signal(company_family=family, filings=filings, observations=observations,
                                         as_of=as_of, unavailable_reason=reason,
                                         min_operating_income_krw=min_operating_income_krw)
            out = {
                "ticker": row["ticker"], "isu_cd": row["isu_cd"], "entry_signal_date": as_of,
                "market_at_signal": row.get("market_at_signal"), "corp_code": corp_code,
                **evaluation.to_row(), "blocking_detail": "",
            }
            latest = evaluation.latest_quarter
            if evaluation.status == UNAVAILABLE and latest and evaluation.reason.startswith(("CURRENT_", "PRIOR_")):
                is_prior = evaluation.reason.startswith("PRIOR_")
                failed_year = int(latest[:4]) - (1 if is_prior else 0)
                out["blocking_detail"] = _blocking_detail(observations, latest, as_of, is_prior)
                if failed_year in build_failed:
                    out["oi_reason"] = f"FISCAL_YEAR_BUILD_FAILED_{build_failed[failed_year]}"
            rows.append(out)
        if progress and number % 50 == 0:
            print(f"fundamentals {number}/{len(by_ticker)} tickers", flush=True)
    columns = None if rows else ["ticker", "isu_cd", "entry_signal_date"]
    frame = pd.DataFrame(rows, columns=columns)
    return frame.sort_values(["entry_signal_date", "ticker", "isu_cd"]).reset_index(drop=True) if rows else frame
