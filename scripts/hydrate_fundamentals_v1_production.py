#!/usr/bin/env python3
"""F7 production hydration for the frozen Fundamentals V1 boundaries.

The runner deliberately owns orchestration only.  F2 periodization, F3
derived metrics, F4 filtering, and the F5 report adapter remain the existing
production implementations.  Raw OpenDART filing/XBRL payloads stay in the
existing ignored caches; committed artifacts contain only redacted metadata,
canonical results, and coverage summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.fundamentals.corp_code_repository import (  # noqa: E402
    AmbiguousCorpCodeError,
    CorpCodeRepository,
    CorpCodeRecord,
    UnknownTickerError,
)
from trend_scanner.fundamentals.derived_metrics import (  # noqa: E402
    DerivedMetricsEngine,
    DerivedMetricsError,
    DerivedMetricsResult,
)
from trend_scanner.fundamentals.fundamentals_filter import (  # noqa: E402
    DATA_UNAVAILABLE as F4_DATA_UNAVAILABLE,
    FundamentalsFilter,
    FundamentalsFilterResult,
    NOT_APPLICABLE as F4_NOT_APPLICABLE,
)
from trend_scanner.fundamentals.multi_period import (  # noqa: E402
    MultiPeriodFundamentalsProvider,
    build_multi_period_result,
)
from trend_scanner.fundamentals.opendart_client import (  # noqa: E402
    OpenDartClient,
    OpenDartError,
)
from trend_scanner.fundamentals.opendart_contract import (  # noqa: E402
    CompanyFamily,
    classify_company_family,
)
from trend_scanner.fundamentals.period_models import (  # noqa: E402
    DATA_UNAVAILABLE as F2_DATA_UNAVAILABLE,
    PeriodizationResult,
)
from trend_scanner.fundamentals.periodization_provider import (  # noqa: E402
    PeriodizationProvider,
    PeriodizationProviderError,
)
from trend_scanner.fundamentals.filing_registry import (  # noqa: E402
    FilingRegistry,
    FilingRegistryConflictError,
    FilingRegistryError,
    REGULAR_REPORT_CODES,
    to_registered_filing,
)
from trend_scanner.fundamentals.opendart_client import JsonResponse  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import (  # noqa: E402
    XbrlRepository,
    XbrlRepositoryError,
)
from trend_scanner.reporting.fundamentals_report import (  # noqa: E402
    build_fundamentals_section,
)
from trend_scanner.universe.instrument_metadata import (  # noqa: E402
    InstrumentMetadataResolver,
)


SCAN_SUMMARY_PATH = ROOT / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260904_summary.json"
CORP_CACHE_PATH = ROOT / "data/cache/opendart/corp_code_cache.json"
COMPANY_CACHE_DIR = ROOT / "data/cache/opendart/company"
OUTPUT_ROOT = ROOT / "artifacts/fundamentals/production"
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.parquet"
VALID_TERMINAL_STATUSES = {
    "PASS",
    "FILTERED_ANNUAL_REVENUE",
    "FILTERED_QUARTERLY_REVENUE",
    "FILTERED_OPERATING_LOSS",
    "FILTERED_NET_LOSS",
    "DATA_UNAVAILABLE",
    "NOT_APPLICABLE",
}
NON_COMMON_ASSET_TYPES = {
    "ETF", "ETN", "PREFERRED", "SPAC", "REIT", "OTHER", "UNKNOWN",
}
RUNNER_VERSION = "F7-04-BOUNDED-FILING-PRELOAD-FINANCIAL-NA"
LEGACY_REUSABLE_NOT_APPLICABLE_RUNNER_VERSIONS = {
    "F7-03-BOUNDED-FILING-PRELOAD-IDENTITY",
}
INTERNAL_FY_LOOKBACK = 6
TODAY_QUOTA_DATE = "2026-09-08"
OFFICIAL_USAGE_BEFORE_PRIORITY = 11_000
MAX_ADDITIONAL_OPENDART_REQUESTS = 28_000
SAFETY_DAILY_CAP = 39_000
REMAINING_MAX_ADDITIONAL_OPENDART_REQUESTS = 8_000
REMAINING_SAFETY_DAILY_CAP = 39_000
PRIORITY_MARKET_DATE = "2026-09-04"
PRIORITY_MARKET_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260904.csv"
KNOWN_TICKER_DATA_ERRORS = (
    OpenDartError,
    FilingRegistryError,
    XbrlRepositoryError,
    PeriodizationProviderError,
    DerivedMetricsError,
)
INDEX_FIELDS = (
    "ticker", "name", "market", "asset_type", "company_family", "corp_code",
    "mapping_status", "company_api_status", "data_status", "f2_data_status",
    "f3_data_status", "f4_status", "f4_passed", "terminal_status",
    "terminal_reason", "requested_as_of", "f2_latest_quarter", "f2_latest_fy",
    "f4_reasons", "artifact_path", "api_request_count", "company_cache_hit",
)


class F7TerminalError(RuntimeError):
    """A bounded, category-preserving failure for one production ticker."""

    def __init__(
        self,
        reason: str,
        *,
        mapping_status: str = "MAPPED",
        company_api_status: str | None = None,
        corp_code: str | None = None,
        company_family: str | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.mapping_status = mapping_status
        self.company_api_status = company_api_status
        self.corp_code = corp_code
        self.company_family = company_family


class QuotaBudgetExceeded(RuntimeError):
    """Raised before an OpenDART request would exceed today's hard cap."""

    def __init__(self, reason: str, *, additional_requests: int, daily_total: int):
        super().__init__(reason)
        self.reason = reason
        self.additional_requests = additional_requests
        self.daily_total = daily_total


class QuotaBoundOpenDartClient(OpenDartClient):
    """Count and gate each actual OpenDART HTTP attempt for today's batch."""

    def __init__(
        self,
        api_key: str,
        *,
        prior_additional_requests: int = 0,
        max_additional_requests: int = MAX_ADDITIONAL_OPENDART_REQUESTS,
        official_usage_before: int = OFFICIAL_USAGE_BEFORE_PRIORITY,
        safety_daily_cap: int = SAFETY_DAILY_CAP,
    ):
        self.http_request_count = 0
        self.prior_additional_requests = int(prior_additional_requests)
        self.max_additional_requests = int(max_additional_requests)
        self.official_usage_before = int(official_usage_before)
        self.safety_daily_cap = int(safety_daily_cap)
        super().__init__(api_key=api_key)

    def _record(self, **fields: Any) -> None:
        self.http_request_count += 1
        super()._record(**fields)

    @property
    def current_additional_requests(self) -> int:
        if self.http_request_count != len(self.audit):
            raise RuntimeError("OpenDART request counter mismatch")
        return self.prior_additional_requests + self.http_request_count

    @property
    def estimated_daily_total(self) -> int:
        return self.official_usage_before + self.current_additional_requests

    def _ensure_budget(self) -> None:
        additional = self.current_additional_requests
        daily_total = self.estimated_daily_total
        if additional >= self.max_additional_requests:
            raise QuotaBudgetExceeded(
                "MAX_ADDITIONAL_OPENDART_REQUESTS_REACHED",
                additional_requests=additional,
                daily_total=daily_total,
            )
        if daily_total >= self.safety_daily_cap:
            raise QuotaBudgetExceeded(
                "SAFETY_DAILY_CAP_REACHED",
                additional_requests=additional,
                daily_total=daily_total,
            )

    def get_json(self, endpoint: str, params: Mapping[str, Any]):
        self._ensure_budget()
        return super().get_json(endpoint, params)

    def get_binary(self, endpoint: str, params: Mapping[str, Any]):
        self._ensure_budget()
        return super().get_binary(endpoint, params)


class ExactCorpCodeRepository(CorpCodeRepository):
    """Use the existing exact cache while accepting KRX alpha tickers.

    The frozen mapping cache contains a small set of six-character
    alphanumeric COMMON tickers.  The base repository's legacy input guard
    only accepts digits, so this adapter changes validation—not mapping
    semantics—and still rejects missing or duplicate exact matches.
    """

    def get_corp_code(self, ticker: str) -> str:
        self.ensure_loaded()
        clean = str(ticker).strip().upper()
        matches = [row.corp_code for row in self.records if str(row.stock_code).strip().upper() == clean]
        if len(matches) == 0:
            raise UnknownTickerError(f"Unknown or invalid ticker: {ticker}")
        if len(set(matches)) != 1:
            raise AmbiguousCorpCodeError(f"Ticker maps to multiple corp_codes: {ticker}")
        return matches[0]

    def get_record(self, ticker: str) -> CorpCodeRecord:
        corp_code = self.get_corp_code(ticker)
        clean = str(ticker).strip().upper()
        return next(
            item for item in self.records
            if item.corp_code == corp_code and str(item.stock_code).strip().upper() == clean
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: BaseException, secret: str) -> str:
    message = str(exc).replace(secret, "<REDACTED>") if secret else str(exc)
    return message[:500]


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        return dict(result) if isinstance(result, Mapping) else {"value": result}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def _write_text_checked(path: Path, text: str) -> None:
    """Write atomically after the required write/read/delete preflight."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        probe = path.with_name(f".{path.name}.write-preflight")
        probe.write_text(text, encoding="utf-8")
        if probe.read_text(encoding="utf-8") != text:
            probe.unlink(missing_ok=True)
            raise OSError(f"write preflight read-back mismatch: {path}")
        probe.unlink()
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    if temporary.read_text(encoding="utf-8") != text:
        temporary.unlink(missing_ok=True)
        raise OSError(f"write read-back mismatch: {path}")
    temporary.replace(path)


def _write_json_checked(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    _write_text_checked(path, text)


def _preflight_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".f7-write-preflight"
    probe.write_text("F7_WRITE_PREFLIGHT\n", encoding="utf-8")
    if probe.read_text(encoding="utf-8") != "F7_WRITE_PREFLIGHT\n":
        probe.unlink(missing_ok=True)
        raise OSError(f"directory write preflight read-back mismatch: {path}")
    probe.unlink()


class BoundedFilingRegistry(FilingRegistry):
    """Preload each missing fiscal-year filing window once per ticker.

    The production ``FilingRegistry`` contract remains the reader and cache
    authority.  This runner-level orchestration avoids asking the same
    ``list.json`` pagination window once for each of four report codes.  A
    completed year window is materialized into the registry's ordinary
    per-year/per-report cache shape, so the existing provider continues to
    consume the standard cache without a parallel HTTP implementation.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.preload_year_fetches = 0
        self.preload_pages_fetched = 0

    @staticmethod
    def _cache_is_usable(
        registry: FilingRegistry,
        *,
        corp_code: str,
        fiscal_year: str,
        reprt_code: str,
        requested_as_of: str,
    ) -> bool:
        cached = registry._load(registry._cache_path(corp_code, fiscal_year, reprt_code))
        return bool(
            cached is not None
            and registry._cache_covers(
                cached[1],
                required_start=f"{int(fiscal_year):04d}-01-01",
                requested_as_of=requested_as_of,
            )
        )

    def preload_ticker(
        self,
        *,
        ticker: str,
        corp_code: str,
        requested_as_of: str,
        fiscal_years: Iterable[str] | None = None,
    ) -> None:
        """Ensure the requested years are represented in ordinary registry caches."""

        if self.client is None:
            raise RuntimeError("OpenDART client is required for filing registry preload")
        cutoff = str(requested_as_of)[:10]
        cutoff_year = int(cutoff[:4])
        years = tuple(
            dict.fromkeys(
                str(int(item))
                for item in (
                    fiscal_years
                    if fiscal_years is not None
                    else range(cutoff_year - INTERNAL_FY_LOOKBACK, cutoff_year + 1)
                )
            )
        )
        missing_years = [
            year for year in years
            if not all(
                self._cache_is_usable(
                    self,
                    corp_code=corp_code,
                    fiscal_year=year,
                    reprt_code=reprt_code,
                    requested_as_of=cutoff,
                )
                for reprt_code in REGULAR_REPORT_CODES
            )
        ]
        for fiscal_year in missing_years:
            coverage_start = f"{int(fiscal_year):04d}-01-01"
            raw_rows, responses, total_count, total_page = self._fetch_pages(
                corp_code=corp_code,
                bgn_de=coverage_start.replace("-", ""),
                end_de=max(cutoff, coverage_start).replace("-", ""),
            )
            self.preload_year_fetches += 1
            self.preload_pages_fetched += len(responses)
            retrieved_at = _now()
            grouped: dict[str, dict[str, Any]] = {
                reprt_code: {} for reprt_code in REGULAR_REPORT_CODES
            }
            raw_by_rcept: dict[str, str] = {}
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    continue
                rcept_no = str(raw.get("rcept_no") or "")
                raw_digest = json.dumps(
                    raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                if rcept_no and rcept_no in raw_by_rcept and raw_by_rcept[rcept_no] != raw_digest:
                    raise FilingRegistryConflictError(
                        f"Conflicting payloads for rcept_no={rcept_no}"
                    )
                if rcept_no:
                    raw_by_rcept[rcept_no] = raw_digest
                filing = to_registered_filing(raw, ticker=ticker, retrieved_at=retrieved_at)
                if filing is None or filing.bsns_year != fiscal_year:
                    continue
                grouped[filing.reprt_code][filing.rcept_no] = filing

            source_hash = hashlib.sha256(b"".join(response.raw for response in responses)).hexdigest()
            for reprt_code in REGULAR_REPORT_CODES:
                rows = sorted(
                    grouped[reprt_code].values(),
                    key=lambda item: (item.rcept_dt, item.rcept_no),
                )
                metadata = {
                    "corp_code": corp_code,
                    "ticker": ticker,
                    "bsns_year": fiscal_year,
                    "reprt_code": reprt_code,
                    "request_parameters": {
                        "corp_code": corp_code,
                        "bsns_year": fiscal_year,
                        "reprt_code": reprt_code,
                    },
                    "request_window": {
                        "bgn_de": coverage_start.replace("-", ""),
                        "end_de": max(cutoff, coverage_start).replace("-", ""),
                    },
                    "request_windows": [{
                        "bgn_de": coverage_start.replace("-", ""),
                        "end_de": max(cutoff, coverage_start).replace("-", ""),
                    }],
                    "requested_as_of": cutoff,
                    "coverage_start": coverage_start,
                    "coverage_end": cutoff,
                    "retrieved_at": retrieved_at,
                    "page_count_requested": 100,
                    "pages_fetched": len(responses),
                    "window_count": 1,
                    "total_count": total_count if total_count is not None else len(raw_rows),
                    "total_page": total_page if total_page is not None else len(responses),
                    "http_status": 200,
                    "api_status": "000",
                    "source_sha256": source_hash,
                    "record_count": len(rows),
                    "cache_complete": True,
                    "cache_hit": False,
                    "preloaded_by": RUNNER_VERSION,
                }
                _write_json_checked(
                    self._cache_path(corp_code, fiscal_year, reprt_code),
                    {"metadata": metadata, "filings": [item.to_dict() for item in rows]},
                )


def _load_opendart_key(env_file: Path) -> str:
    """Load only OPENDART_API_KEY from env.md without printing any value."""

    key = os.getenv("OPENDART_API_KEY", "").strip()
    if key:
        return key
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if not line.startswith("OPENDART_API_KEY="):
                continue
            candidate = line.split("=", 1)[1].strip().strip("\"'")
            if candidate:
                return candidate
    raise F7TerminalError("OPENDART_API_KEY_MISSING", mapping_status="NOT_APPLICABLE")


def _load_requested_as_of() -> tuple[str, str]:
    if not SCAN_SUMMARY_PATH.exists():
        raise RuntimeError(f"production authority summary missing: {SCAN_SUMMARY_PATH}")
    summary = json.loads(SCAN_SUMMARY_PATH.read_text(encoding="utf-8"))
    requested = str(summary.get("requested_as_of") or "")[:10]
    reference = str(summary.get("reference_market_date") or "")[:10]
    if not requested or requested != reference:
        raise RuntimeError("production authority has no single exact requested_as_of")
    return requested, reference


def _load_production_universe(requested_as_of: str) -> tuple[list[dict[str, Any]], str]:
    if not METADATA_PATH.exists():
        raise RuntimeError(f"instrument metadata authority missing: {METADATA_PATH}")
    frame = InstrumentMetadataResolver.load_master_dataframe(ROOT).copy()
    if frame.empty or "ticker" not in frame.columns or "effective_date" not in frame.columns:
        raise RuntimeError("instrument metadata authority is empty or incomplete")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="coerce")
    cutoff = pd.Timestamp(requested_as_of)
    eligible = frame[frame["effective_date"].notna() & (frame["effective_date"] <= cutoff)]
    if eligible.empty:
        raise RuntimeError("instrument metadata has no PIT-eligible rows")
    snapshot_date = str(eligible["effective_date"].max().date())
    current = eligible[eligible["effective_date"] == pd.Timestamp(snapshot_date)].copy()
    current = current.sort_values("ticker")
    if current["ticker"].duplicated().any():
        duplicates = current.loc[current["ticker"].duplicated(), "ticker"].tolist()
        raise RuntimeError(f"duplicate production universe tickers: {duplicates[:5]}")
    rows = []
    for item in current.to_dict(orient="records"):
        asset_type = str(item.get("asset_type") or "UNKNOWN").strip().upper()
        rows.append({
            "ticker": str(item.get("ticker") or "").strip().upper(),
            "name": str(item.get("name") or item.get("ticker") or "").strip(),
            "market": str(item.get("market") or "UNKNOWN").strip().upper(),
            "asset_type": asset_type,
            "effective_date": snapshot_date,
            "classification_authority": str(item.get("classification_authority") or "UNKNOWN"),
            "asset_type_source": str(item.get("asset_type_source") or "UNKNOWN"),
        })
    if not rows or any(not row["ticker"] for row in rows):
        raise RuntimeError("production universe contains an empty ticker")
    return rows, snapshot_date


def _load_priority_tickers(universe: Iterable[Mapping[str, Any]]) -> tuple[set[str], dict[str, Any]]:
    """Resolve today's temporary priority from the existing local market file."""

    if not PRIORITY_MARKET_PATH.exists():
        raise RuntimeError(f"priority market authority missing: {PRIORITY_MARKET_PATH}")
    frame = pd.read_csv(PRIORITY_MARKET_PATH, dtype={"ticker": str})
    required = {"ticker", "close", "market_cap", "effective_date"}
    if not required.issubset(frame.columns):
        raise RuntimeError("priority market authority is missing required columns")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper().str.zfill(6)
    if frame["ticker"].duplicated().any():
        raise RuntimeError("priority market authority contains duplicate tickers")
    dates = set(frame["effective_date"].astype(str).str[:10])
    if dates != {PRIORITY_MARKET_DATE}:
        raise RuntimeError("priority market authority is not the exact 2026-09-04 snapshot")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
    if frame[["close", "market_cap"]].isna().any().any():
        raise RuntimeError("priority market authority contains non-numeric price or market cap")
    market_priority = set(
        frame.loc[
            (frame["market_cap"] >= 300_000_000_000)
            & (frame["close"] >= 5_000),
            "ticker",
        ]
    )
    universe_rows = list(universe)
    common = {str(row["ticker"]).strip().upper() for row in universe_rows if row["asset_type"] == "COMMON"}
    priority = common & market_priority
    return priority, {
        "market_file": str(PRIORITY_MARKET_PATH.relative_to(ROOT)),
        "market_date": PRIORITY_MARKET_DATE,
        "market_universe_count": len(frame),
        "market_condition_count": len(market_priority),
        "common_universe_count": len(common),
        "priority_common_candidate_count": len(priority),
        "market_cap_floor_krw": 300_000_000_000,
        "close_floor_krw": 5_000,
    }


def _load_prior_quota_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("date") != TODAY_QUOTA_DATE:
        return {}
    return value


def _load_remaining_quota_budget(path: Path) -> tuple[int, int]:
    """Load today's baseline and aggregate remaining-run request count."""

    checkpoint = _load_prior_quota_checkpoint(path)
    quota = checkpoint.get("quota")
    try:
        if isinstance(quota, Mapping):
            baseline = int(quota["baseline_daily_total_estimate"])
            prior_additional = int(quota["additional_opendart_requests"])
        else:
            baseline = int(checkpoint["estimated_daily_total_after_run"])
            prior_additional = 0
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("today's priority quota checkpoint has no usable daily baseline") from exc
    if baseline < 0 or baseline >= REMAINING_SAFETY_DAILY_CAP:
        raise RuntimeError("today's priority quota checkpoint exceeds the remaining-run safety boundary")
    accounting = checkpoint.get("request_accounting")
    if not isinstance(accounting, Mapping) or accounting.get("counter_consistent") is not True:
        raise RuntimeError("today's priority quota checkpoint has inconsistent request accounting")
    if prior_additional < 0 or prior_additional > REMAINING_MAX_ADDITIONAL_OPENDART_REQUESTS:
        raise RuntimeError("today's remaining-run request count is outside the quota boundary")
    return baseline, prior_additional


def _load_completed_rows(universe: Iterable[Mapping[str, Any]], tickers_dir: Path, requested_as_of: str) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for universe_row in universe:
        ticker = str(universe_row["ticker"])
        existing = _load_existing(
            tickers_dir / f"{ticker}.json",
            ticker=ticker,
            requested_as_of=requested_as_of,
        )
        if existing is not None:
            completed.append(existing)
    return completed


def _load_exact_corp_repository() -> tuple[ExactCorpCodeRepository, dict[str, list[CorpCodeRecord]]]:
    if not CORP_CACHE_PATH.exists():
        raise RuntimeError(f"existing OpenDART corp mapping cache missing: {CORP_CACHE_PATH}")
    source = CorpCodeRepository.from_cache(CORP_CACHE_PATH)
    by_ticker: dict[str, list[CorpCodeRecord]] = {}
    for item in source.records:
        ticker = str(item.stock_code or "").strip().upper()
        if ticker:
            by_ticker.setdefault(ticker, []).append(item)
    return ExactCorpCodeRepository(records=source.records), by_ticker


def _company_cache_payload(payload: Mapping[str, Any], *, ticker: str, corp_code: str) -> dict[str, Any]:
    selected_keys = (
        "corp_code", "corp_name", "corp_name_eng", "stock_name", "stock_code",
        "corp_cls", "induty_code", "est_dt", "acc_mt",
    )
    selected = {key: payload.get(key) for key in selected_keys}
    return {
        "status": str(payload.get("status") or ""),
        "message": payload.get("message"),
        "classification": "PASS" if str(payload.get("status") or "") == "000" else "DATA_UNAVAILABLE",
        "ticker": ticker,
        "corp_code": corp_code,
        "selected_fields": selected,
        "identity": {
            "corp_code": str(payload.get("corp_code") or ""),
            "stock_code": str(payload.get("stock_code") or ""),
            "corp_name": str(payload.get("corp_name") or ""),
            "stock_name": str(payload.get("stock_name") or ""),
        },
        "retrieved_at": _now(),
    }


def _valid_company_cache(value: Any, *, ticker: str, corp_code: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    fields = value.get("selected_fields") if isinstance(value.get("selected_fields"), Mapping) else {}
    return (
        str(value.get("status") or "") == "000"
        and str(fields.get("corp_code") or "") == corp_code
        and str(fields.get("stock_code") or "").strip().upper() == ticker
    )


def _load_company_metadata(
    client: OpenDartClient,
    ticker: str,
    corp_code: str,
    secret: str,
    company_cache_dir: Path,
) -> tuple[dict[str, Any], bool]:
    path = company_cache_dir / f"{ticker}.json"
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            cached = None
        if _valid_company_cache(cached, ticker=ticker, corp_code=corp_code):
            return dict(cached), True

    response = client.get_json("company.json", {"corp_code": corp_code})
    payload = response.payload if isinstance(response.payload, Mapping) else {}
    status = str(payload.get("status") or "")
    if response.http_status != 200 or status != "000":
        raise F7TerminalError(
            f"COMPANY_API_{response.classification or 'STATUS_' + status}",
            company_api_status=status or response.classification,
        )
    response_corp = str(payload.get("corp_code") or "").strip()
    response_ticker = str(payload.get("stock_code") or "").strip().upper()
    if response_corp != corp_code or response_ticker != ticker:
        raise F7TerminalError(
            "IDENTITY_MISMATCH",
            mapping_status="IDENTITY_MISMATCH",
            company_api_status=status,
        )
    value = _company_cache_payload(payload, ticker=ticker, corp_code=corp_code)
    _write_json_checked(path, value)
    # Secret safety guard: the cached payload must not contain the key.
    if secret and secret in path.read_text(encoding="utf-8"):
        raise RuntimeError("secret leaked into company metadata cache")
    return value, False


def _family_from_company(company: Mapping[str, Any]) -> str:
    result = classify_company_family(company, ())
    return str(result.get("company_family") or CompanyFamily.UNKNOWN.value)


def _f2_status(result: Any) -> str:
    family = str(getattr(result, "company_family", "") or "")
    if family == CompanyFamily.FINANCIAL.value:
        return "NOT_APPLICABLE"
    quarter = getattr(result, "quarter_coverage", {}) or {}
    annual = getattr(result, "annual_coverage", {}) or {}
    if quarter.get("has_comparison_window") and annual.get("has_comparison_window"):
        return "READY"
    if (
        int(quarter.get("ready_count", 0) or 0)
        + int(annual.get("ready_count", 0) or 0)
        or getattr(result, "canonical_observations", ())
    ):
        return "PARTIAL"
    return "DATA_UNAVAILABLE"


def _f3_status(result: Any, *, company_family: str | None = None) -> str:
    if company_family == CompanyFamily.FINANCIAL.value:
        return "NOT_APPLICABLE"
    if result is None:
        return "DATA_UNAVAILABLE"
    observations = tuple(getattr(result, "observations", ()) or ())
    if not observations:
        return "DATA_UNAVAILABLE"
    statuses = {str(getattr(item, "resolution_status", F2_DATA_UNAVAILABLE)) for item in observations}
    if statuses == {"READY"}:
        return "READY"
    if "READY" in statuses:
        return "PARTIAL"
    return "DATA_UNAVAILABLE"


def _empty_financial_f2(ticker: str, corp_code: str, requested_as_of: str) -> Any:
    return build_multi_period_result(
        ticker=ticker,
        corp_code=corp_code,
        company_family=CompanyFamily.FINANCIAL.value,
        requested_as_of=requested_as_of,
        observations=(),
    )


def _empty_unknown_f2(ticker: str, corp_code: str, requested_as_of: str) -> Any:
    return build_multi_period_result(
        ticker=ticker,
        corp_code=corp_code,
        company_family=CompanyFamily.UNKNOWN.value,
        requested_as_of=requested_as_of,
        observations=(),
    )


class _AsOfOnlyDerivedResult:
    """F4 input adapter for a financial N/A decision.

    Financial companies do not have general-company F3 observations, but F4
    still validates that all inputs share the production cutoff before it
    applies its existing FINANCIAL -> NOT_APPLICABLE branch.
    """

    def __init__(self, requested_as_of: str):
        self.requested_as_of = requested_as_of
        self.observations: tuple[Any, ...] = ()


def _base_record(row: Mapping[str, Any], requested_as_of: str, artifact_path: str) -> dict[str, Any]:
    return {
        "runner_version": RUNNER_VERSION,
        "ticker": row["ticker"],
        "name": row["name"],
        "market": row["market"],
        "asset_type": row["asset_type"],
        "company_family": None,
        "corp_code": None,
        "mapping_status": "NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else "MAPPED",
        "company_api_status": None,
        "data_status": "NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else "DATA_UNAVAILABLE",
        "f2_data_status": "NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else "DATA_UNAVAILABLE",
        "f3_data_status": "NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else "DATA_UNAVAILABLE",
        "f4_status": F4_NOT_APPLICABLE if row["asset_type"] in NON_COMMON_ASSET_TYPES else F4_DATA_UNAVAILABLE,
        "f4_passed": False,
        "terminal_status": "NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else "DATA_UNAVAILABLE",
        "terminal_reason": "ASSET_TYPE_NOT_APPLICABLE" if row["asset_type"] in NON_COMMON_ASSET_TYPES else None,
        "requested_as_of": requested_as_of,
        "f2_latest_quarter": None,
        "f2_latest_fy": None,
        "f4_reasons": [],
        "artifact_path": artifact_path,
        "api_request_count": 0,
        "company_cache_hit": False,
    }


def hydrate_one(
    row: Mapping[str, Any],
    *,
    requested_as_of: str,
    corp_repo: ExactCorpCodeRepository,
    records_by_ticker: Mapping[str, list[CorpCodeRecord]],
    client: OpenDartClient,
    company_cache_dir: Path,
    secret: str,
    period_provider: MultiPeriodFundamentalsProvider,
) -> dict[str, Any]:
    ticker = str(row["ticker"]).strip().upper()
    asset_type = str(row["asset_type"]).strip().upper()
    artifact_path = str(Path("tickers") / f"{ticker}.json")
    record = _base_record(row, requested_as_of, artifact_path)
    if asset_type in NON_COMMON_ASSET_TYPES:
        section = build_fundamentals_section(None, None, None, requested_as_of, asset_type)
        record["f5_ready"] = asdict(section)
        return record

    matches = records_by_ticker.get(ticker, ())
    if len(matches) == 0:
        record.update({"mapping_status": "CORP_CODE_MISSING", "terminal_reason": "CORP_CODE_MISSING"})
        section = build_fundamentals_section(None, None, None, requested_as_of, asset_type)
        record["f5_ready"] = asdict(section)
        return record
    if len({item.corp_code for item in matches}) != 1:
        record.update({"mapping_status": "IDENTITY_MISMATCH", "terminal_reason": "AMBIGUOUS_CORP_CODE"})
        section = build_fundamentals_section(None, None, None, requested_as_of, asset_type)
        record["f5_ready"] = asdict(section)
        return record

    corp_code = matches[0].corp_code
    record["corp_code"] = corp_code
    try:
        # Exercise the same exact mapping boundary used by the production provider.
        mapped = corp_repo.get_record(ticker)
        if mapped.corp_code != corp_code:
            raise F7TerminalError("IDENTITY_MISMATCH", mapping_status="IDENTITY_MISMATCH")
        company, cache_hit = _load_company_metadata(
            client, ticker, corp_code, secret, company_cache_dir,
        )
        record["company_cache_hit"] = cache_hit
        record["company_api_status"] = company.get("status")
        family = _family_from_company(company)
        record["company_family"] = family
        company_fields = company.get("selected_fields", {})

        if family == CompanyFamily.FINANCIAL.value:
            f2 = _empty_financial_f2(ticker, corp_code, requested_as_of)
            f3 = DerivedMetricsResult(())
            f4_input = _AsOfOnlyDerivedResult(requested_as_of)
        elif family == CompanyFamily.NON_FINANCIAL.value:
            registry = getattr(period_provider.periodization_provider, "filings", None)
            if not isinstance(registry, BoundedFilingRegistry):
                raise RuntimeError("F7 requires the bounded filing registry orchestration")
            registry.preload_ticker(
                ticker=ticker,
                corp_code=corp_code,
                requested_as_of=requested_as_of,
            )
            f2 = period_provider.build(
                ticker,
                requested_as_of,
                company_metadata=company_fields,
                force_refresh=False,
            )
            f3 = DerivedMetricsEngine().derive(
                f2.canonical_observations,
                requested_as_of=requested_as_of,
            )
            f4_input = f3
        else:
            f2 = _empty_unknown_f2(ticker, corp_code, requested_as_of)
            f3 = DerivedMetricsResult(())
            f4_input = f3

        f4: FundamentalsFilterResult = FundamentalsFilter().evaluate(
            f2, f4_input, requested_as_of=requested_as_of,
        )
        section = build_fundamentals_section(
            f2, f3, f4, requested_as_of, asset_type,
        )
        record.update({
            "data_status": section.data_status,
            "f2_data_status": _f2_status(f2),
            "f3_data_status": _f3_status(f3, company_family=family),
            "f4_status": f4.status,
            "f4_passed": bool(f4.passed),
            "terminal_status": f4.status,
            "terminal_reason": section.reason,
            "f2_latest_quarter": f2.latest_quarter,
            "f2_latest_fy": f2.latest_fy,
            "f4_reasons": list(f4.reasons),
            "f5_ready": asdict(section),
            "f2": _as_dict(f2),
            "f3": _as_dict(f3),
            "f4": _as_dict(f4),
        })
        return record
    except F7TerminalError as exc:
        if exc.corp_code is None:
            exc.corp_code = record.get("corp_code")
        if exc.company_family is None:
            exc.company_family = record.get("company_family")
        raise
    except KNOWN_TICKER_DATA_ERRORS as exc:
        raise F7TerminalError(
            f"{type(exc).__name__}:{_safe_error(exc, secret)}",
            company_api_status=record.get("company_api_status"),
            corp_code=record.get("corp_code"),
            company_family=record.get("company_family"),
        ) from exc


def _record_failure(row: Mapping[str, Any], requested_as_of: str, error: F7TerminalError) -> dict[str, Any]:
    record = _base_record(row, requested_as_of, str(Path("tickers") / f"{row['ticker']}.json"))
    record.update({
        "corp_code": error.corp_code,
        "company_family": error.company_family,
        "mapping_status": error.mapping_status,
        "company_api_status": error.company_api_status,
        "terminal_status": "DATA_UNAVAILABLE",
        "data_status": "DATA_UNAVAILABLE",
        "f2_data_status": "DATA_UNAVAILABLE",
        "f3_data_status": "DATA_UNAVAILABLE",
        "f4_status": F4_DATA_UNAVAILABLE,
        "f4_passed": False,
        "terminal_reason": error.reason,
        "f4_reasons": [error.reason or "DATA_UNAVAILABLE"],
        "f5_ready": asdict(build_fundamentals_section(None, None, None, requested_as_of, row["asset_type"])),
    })
    return record


def _is_systematic_transport_failure(error: F7TerminalError) -> bool:
    """Identify transport failures that must stop remaining hydration."""

    return str(error.reason or "").startswith(
        "OpenDartError:OpenDART JSON request failed:"
    )


def _load_existing(path: Path, *, ticker: str, requested_as_of: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("ticker") != ticker or value.get("requested_as_of") != requested_as_of:
        return None
    if value.get("runner_version") == RUNNER_VERSION:
        return value if value.get("terminal_status") in VALID_TERMINAL_STATUSES else None
    legacy_not_applicable = (
        value.get("runner_version") in LEGACY_REUSABLE_NOT_APPLICABLE_RUNNER_VERSIONS
        and value.get("asset_type") in NON_COMMON_ASSET_TYPES
        and value.get("terminal_status") == "NOT_APPLICABLE"
        and value.get("f4_passed") is False
        and int(value.get("api_request_count", 0) or 0) == 0
        and isinstance(value.get("f5_ready"), Mapping)
        and value["f5_ready"].get("data_status") == "NOT_APPLICABLE"
    )
    return value if legacy_not_applicable else None


def _select_remaining_rows(
    universe: Iterable[Mapping[str, Any]],
    completed_tickers: Iterable[str],
) -> list[dict[str, Any]]:
    """Keep the authority's deterministic order while excluding valid outputs."""

    completed = {str(ticker).strip().upper() for ticker in completed_tickers}
    return [
        dict(row) for row in universe
        if str(row.get("ticker") or "").strip().upper() not in completed
    ]


def _write_index(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    output: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row.get(key) for key in INDEX_FIELDS}
        item["f4_reasons"] = json.dumps(item["f4_reasons"] or [], ensure_ascii=False, separators=(",", ":"))
        output.append(item)
    output.sort(key=lambda item: str(item.get("ticker") or ""))
    fieldnames = list(INDEX_FIELDS)
    lines: list[str] = []
    from io import StringIO
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(output)
    _write_text_checked(path, buffer.getvalue())


def _category_reason(row: Mapping[str, Any]) -> str:
    if row.get("terminal_status") == "DATA_UNAVAILABLE":
        reasons = row.get("f4_reasons") or []
        if reasons:
            return str(reasons[0])
        return str(row.get("terminal_reason") or "OTHER_EXISTING_REASON").split(":", 1)[0]
    return "NONE"


def _summary(
    rows: list[dict[str, Any]],
    *,
    requested_as_of: str,
    metadata_snapshot_date: str,
    started_at: str,
    completed_at: str,
    client: OpenDartClient,
    pilot_count: int | None,
) -> dict[str, Any]:
    asset_counts = Counter(str(row.get("asset_type") or "UNKNOWN") for row in rows)
    terminal_counts = Counter(str(row.get("terminal_status") or "DATA_UNAVAILABLE") for row in rows)
    data_counts = Counter(str(row.get("data_status") or "DATA_UNAVAILABLE") for row in rows)
    mapping_counts = Counter(str(row.get("mapping_status") or "MAPPED") for row in rows)
    reasons = Counter(_category_reason(row) for row in rows if row.get("terminal_status") == "DATA_UNAVAILABLE")
    applicable = sum(1 for row in rows if row.get("asset_type") == "COMMON")
    filtered = sum(value for key, value in terminal_counts.items() if key.startswith("FILTERED_"))
    api_counts = Counter(str(item.get("endpoint") or "UNKNOWN") for item in client.audit)
    cache_hits = sum(1 for row in rows if bool(row.get("company_cache_hit")))
    duplicate_count = len(rows) - len({str(row.get("ticker")) for row in rows})
    valid_terminal_count = sum(
        1 for row in rows if row.get("terminal_status") in VALID_TERMINAL_STATUSES
    )
    terminal_invariant = (
        valid_terminal_count == len(rows)
        and len(rows) == terminal_counts.get("PASS", 0) + filtered
        + terminal_counts.get("DATA_UNAVAILABLE", 0)
        + terminal_counts.get("NOT_APPLICABLE", 0)
    )
    applicable_non_financial = sum(
        1 for row in rows
        if row.get("asset_type") == "COMMON"
        and row.get("company_family") == CompanyFamily.NON_FINANCIAL.value
    )
    applicable_non_financial_terminal_count = sum(
        1 for row in rows
        if row.get("asset_type") == "COMMON"
        and row.get("company_family") == CompanyFamily.NON_FINANCIAL.value
        and row.get("terminal_status") in {
            "PASS", "FILTERED_ANNUAL_REVENUE", "FILTERED_QUARTERLY_REVENUE",
            "FILTERED_OPERATING_LOSS", "FILTERED_NET_LOSS", "DATA_UNAVAILABLE",
        }
    )
    applicable_non_financial_terminal_invariant = (
        applicable_non_financial == applicable_non_financial_terminal_count
    )
    return {
        "runner_version": RUNNER_VERSION,
        "work_id": "F7_PRODUCTION_COVERAGE_FULL_HYDRATION",
        "final_status": "PASS" if len(rows) > 0 and duplicate_count == 0
        and terminal_invariant and applicable_non_financial_terminal_invariant else "CHANGES_REQUESTED",
        "requested_as_of": requested_as_of,
        "metadata_snapshot_date": metadata_snapshot_date,
        "total_universe": len(rows),
        "universe_counts": {
            "COMMON": asset_counts.get("COMMON", 0),
            "FINANCIAL": sum(1 for row in rows if row.get("company_family") == CompanyFamily.FINANCIAL.value),
            "ETF": asset_counts.get("ETF", 0),
            "ETN": asset_counts.get("ETN", 0),
            "OTHER": sum(value for key, value in asset_counts.items() if key not in {"COMMON", "ETF", "ETN"}),
        },
        "applicable_non_financial_common": sum(
            1 for row in rows
            if row.get("asset_type") == "COMMON" and row.get("company_family") == CompanyFamily.NON_FINANCIAL.value
        ),
        "not_applicable": terminal_counts.get("NOT_APPLICABLE", 0),
        "fundamentals_coverage": {
            "PASS": terminal_counts.get("PASS", 0),
            "FILTERED_ANNUAL_REVENUE": terminal_counts.get("FILTERED_ANNUAL_REVENUE", 0),
            "FILTERED_QUARTERLY_REVENUE": terminal_counts.get("FILTERED_QUARTERLY_REVENUE", 0),
            "FILTERED_OPERATING_LOSS": terminal_counts.get("FILTERED_OPERATING_LOSS", 0),
            "FILTERED_NET_LOSS": terminal_counts.get("FILTERED_NET_LOSS", 0),
            "DATA_UNAVAILABLE": terminal_counts.get("DATA_UNAVAILABLE", 0),
            "NOT_APPLICABLE": terminal_counts.get("NOT_APPLICABLE", 0),
        },
        "data_coverage": {
            "READY": data_counts.get("READY", 0),
            "PARTIAL": data_counts.get("PARTIAL", 0),
            "DATA_UNAVAILABLE": data_counts.get("DATA_UNAVAILABLE", 0),
            "NOT_APPLICABLE": data_counts.get("NOT_APPLICABLE", 0),
        },
        "mapping_coverage": dict(mapping_counts),
        "data_unavailable_top_reasons": dict(reasons.most_common()),
        "accounting": {
            "terminal_result_count_equals_total": terminal_invariant,
            "applicable_non_financial_terminal_result_count_equals_applicable": (
                applicable_non_financial_terminal_invariant
            ),
            "applicable_terminal_result_count_equals_applicable": (
                applicable == sum(
                    1 for row in rows
                    if row.get("asset_type") == "COMMON"
                    and row.get("terminal_status") in VALID_TERMINAL_STATUSES
                )
            ),
            "duplicate_ticker_count": duplicate_count,
            "missing_ticker_count": 0,
        },
        "opendart": {
            "live": "USED",
            "api_request_count": sum(int(item.get("api_request_count", 0) or 0) for item in rows),
            "current_invocation_api_request_count": len(client.audit),
            "endpoint_request_counts": dict(api_counts),
            "company_cache_hits": cache_hits,
            "transient_failures": sum(1 for item in client.audit if item.get("classification") in {"SERVICE", "RATE_LIMIT"}),
            "retry_count": 0,
        },
        "network": {"PyKRX": 0, "KRX Open API": 0, "OpenDART live": "USED", "Scraping": 0},
        "pilot_ticker_count": pilot_count,
        "run_started_at": started_at,
        "run_completed_at": completed_at,
        "processed_ticker_count": len(rows),
        "filtered_count": filtered,
        "mapping_source": str(CORP_CACHE_PATH.relative_to(ROOT)),
        "universe_source": str(METADATA_PATH.relative_to(ROOT)),
    }


def _daily_quota_checkpoint(
    *,
    completed_rows: list[dict[str, Any]],
    universe: list[dict[str, Any]],
    priority_tickers: set[str],
    priority_info: Mapping[str, Any],
    preexisting_completed_tickers: set[str],
    preexisting_priority_tickers: set[str],
    requested_as_of: str,
    metadata_snapshot_date: str,
    started_at: str,
    completed_at: str,
    client: QuotaBoundOpenDartClient,
    stop_reason: str,
) -> dict[str, Any]:
    completed_by_ticker = {str(row.get("ticker")): row for row in completed_rows}
    newly_processed = [
        ticker for ticker in priority_tickers
        if ticker in completed_by_ticker and ticker not in preexisting_priority_tickers
    ]
    remaining_priority = sorted(
        ticker for ticker in priority_tickers if ticker not in completed_by_ticker
    )

    def known_family(ticker: str) -> str | None:
        existing = completed_by_ticker.get(ticker)
        if existing is not None:
            return str(existing.get("company_family") or "") or None
        path = COMPANY_CACHE_DIR / f"{ticker}.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, Mapping):
            return None
        family = _family_from_company(value)
        return family if family != CompanyFamily.UNKNOWN.value else None

    remaining_applicable_outside_priority = sum(
        1 for row in universe
        if row["asset_type"] == "COMMON"
        and str(row["ticker"]) not in priority_tickers
        and str(row["ticker"]) not in completed_by_ticker
        and known_family(str(row["ticker"])) == CompanyFamily.NON_FINANCIAL.value
    )
    all_remaining_applicable = sum(
        1 for row in universe
        if row["asset_type"] == "COMMON"
        and str(row["ticker"]) not in completed_by_ticker
        and known_family(str(row["ticker"])) == CompanyFamily.NON_FINANCIAL.value
    )
    completed_summary = _summary(
        completed_rows,
        requested_as_of=requested_as_of,
        metadata_snapshot_date=metadata_snapshot_date,
        started_at=started_at,
        completed_at=completed_at,
        client=client,
        pilot_count=None,
    )
    actual_additional = client.current_additional_requests
    counter_consistent = client.http_request_count == len(client.audit)
    return {
        "work_id": "F7_DAILY_QUOTA_CONTROL_CHECKPOINT",
        "runner_version": RUNNER_VERSION,
        "date": TODAY_QUOTA_DATE,
        "status": "IN_PROGRESS",
        "requested_as_of": requested_as_of,
        "metadata_snapshot_date": metadata_snapshot_date,
        "stop_reason": stop_reason,
        "official_usage_before_priority": OFFICIAL_USAGE_BEFORE_PRIORITY,
        "max_additional_budget": MAX_ADDITIONAL_OPENDART_REQUESTS,
        "safety_daily_cap": SAFETY_DAILY_CAP,
        "actual_additional_requests": actual_additional,
        "estimated_daily_total_after_run": client.estimated_daily_total,
        "quota_remaining_to_safety_cap": max(0, SAFETY_DAILY_CAP - client.estimated_daily_total),
        "universe": {
            "total_universe": len(universe),
            "already_completed_before_priority_run": len(preexisting_completed_tickers),
            "priority": dict(priority_info),
            "priority_already_completed": len(preexisting_priority_tickers),
            "priority_newly_processed": len(newly_processed),
            "priority_remaining": len(remaining_priority),
            "priority_remaining_tickers": remaining_priority,
            "remaining_applicable_outside_priority_known": remaining_applicable_outside_priority,
            "all_remaining_applicable_known": all_remaining_applicable,
        },
        "terminal_status_summary_completed_only": completed_summary["fundamentals_coverage"],
        "data_coverage_completed_only": completed_summary["data_coverage"],
        "mapping_coverage_completed_only": completed_summary["mapping_coverage"],
        "result_counts": {
            "mapping_failures": sum(
                1 for row in completed_rows
                if row.get("mapping_status") in {"CORP_CODE_MISSING", "IDENTITY_MISMATCH"}
            ),
            "transient_failures_current_invocation": sum(
                1 for item in client.audit
                if item.get("classification") in {"SERVICE", "RATE_LIMIT"}
            ),
        },
        "request_accounting": {
            "actual_http_request_count_current_invocation": client.http_request_count,
            "audit_entry_count_current_invocation": len(client.audit),
            "counter_consistent": counter_consistent,
            "basis": "QuotaBoundOpenDartClient audit entry per OpenDART get_json/get_binary attempt",
        },
        "resume": {
            "checkpoint_safe": all(
                row.get("terminal_status") in VALID_TERMINAL_STATUSES
                for row in completed_rows
            ) and len(completed_rows) == len(completed_by_ticker),
            "completed_tickers_reusable": len(completed_rows) == len(completed_by_ticker),
            "tomorrow_remaining_only_resume_possible": True,
        },
        "run_started_at": started_at,
        "run_completed_at": completed_at,
    }


def _remaining_quota_checkpoint(
    *,
    completed_rows: list[dict[str, Any]],
    universe: list[dict[str, Any]],
    start_completed_tickers: set[str],
    requested_as_of: str,
    metadata_snapshot_date: str,
    started_at: str,
    completed_at: str,
    client: QuotaBoundOpenDartClient,
    stop_reason: str,
    baseline_daily_total: int,
) -> dict[str, Any]:
    completed_tickers = {str(row.get("ticker")) for row in completed_rows}
    newly_completed = sorted(completed_tickers - start_completed_tickers)
    remaining_tickers = sorted(
        str(row["ticker"]) for row in universe
        if str(row["ticker"]) not in completed_tickers
    )
    summary = _summary(
        completed_rows,
        requested_as_of=requested_as_of,
        metadata_snapshot_date=metadata_snapshot_date,
        started_at=started_at,
        completed_at=completed_at,
        client=client,
        pilot_count=None,
    )
    actual_additional = client.current_additional_requests
    counter_consistent = client.http_request_count == len(client.audit)
    return {
        "work_id": "F7_REMAINING_DAILY_QUOTA_CONTROL_CHECKPOINT",
        "runner_version": RUNNER_VERSION,
        "date": TODAY_QUOTA_DATE,
        "status": "IN_PROGRESS",
        "requested_as_of": requested_as_of,
        "metadata_snapshot_date": metadata_snapshot_date,
        "stop_reason": stop_reason,
        "start_completed": len(start_completed_tickers),
        "start_remaining": len(universe) - len(start_completed_tickers),
        "newly_completed_today": len(newly_completed),
        "newly_completed_tickers": newly_completed,
        "end_completed": len(completed_tickers),
        "end_remaining": len(remaining_tickers),
        "remaining_tickers": remaining_tickers,
        "quota": {
            "baseline_daily_total_estimate": baseline_daily_total,
            "additional_opendart_requests": actual_additional,
            "max_additional_requests_this_run": REMAINING_MAX_ADDITIONAL_OPENDART_REQUESTS,
            "estimated_daily_total_after_run": client.estimated_daily_total,
            "safety_daily_cap": REMAINING_SAFETY_DAILY_CAP,
            "safety_margin": max(0, REMAINING_SAFETY_DAILY_CAP - client.estimated_daily_total),
            "basis": "2026-09-08 priority checkpoint estimate plus this remaining invocation",
        },
        "terminal_status_summary_completed": summary["fundamentals_coverage"],
        "data_coverage_completed": summary["data_coverage"],
        "mapping_coverage_completed": summary["mapping_coverage"],
        "result_counts": {
            "mapping_failures": sum(
                1 for row in completed_rows
                if row.get("mapping_status") in {"CORP_CODE_MISSING", "IDENTITY_MISMATCH"}
            ),
            "transient_failures_current_invocation": sum(
                1 for item in client.audit
                if item.get("classification") in {"SERVICE", "RATE_LIMIT"}
            ),
        },
        "request_accounting": {
            "actual_http_request_count_current_invocation": client.http_request_count,
            "audit_entry_count_current_invocation": len(client.audit),
            "counter_consistent": counter_consistent,
            "basis": "QuotaBoundOpenDartClient audit entry per OpenDART get_json/get_binary attempt",
        },
        "resume": {
            "checkpoint_safe": (
                len(completed_tickers) == len(completed_rows)
                and all(row.get("terminal_status") in VALID_TERMINAL_STATUSES for row in completed_rows)
                and counter_consistent
            ),
            "completed_tickers_reusable": len(completed_tickers) == len(completed_rows),
            "remaining_only_resume_possible": True,
        },
        "run_started_at": started_at,
        "run_completed_at": completed_at,
    }


def _choose_pilot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_asset = {str(row["asset_type"]): row for row in rows if row["asset_type"] != "COMMON"}
    selected: list[dict[str, Any]] = []
    common = [row for row in rows if row["asset_type"] == "COMMON"]
    preferred = ("005930", "237690", "086790", "0001A0", "000440")
    by_ticker = {row["ticker"]: row for row in common}
    for ticker in preferred:
        if ticker in by_ticker:
            selected.append(by_ticker[ticker])
    for row in common:
        if len(selected) >= 8:
            break
        if row not in selected:
            selected.append(row)
    for asset_type in ("ETF", "ETN"):
        if asset_type in by_asset:
            selected.append(by_asset[asset_type])
    return selected[:10]


def run(mode: str, *, env_file: Path) -> int:
    requested_as_of, _reference_market_date = _load_requested_as_of()
    universe, metadata_snapshot_date = _load_production_universe(requested_as_of)
    priority_tickers: set[str] = set()
    priority_info: dict[str, Any] = {}
    if mode == "pilot":
        target_rows = _choose_pilot(universe)
    elif mode == "priority":
        priority_tickers, priority_info = _load_priority_tickers(universe)
        target_rows = [row for row in universe if row["ticker"] in priority_tickers]
    elif mode == "remaining":
        # The completed-output exclusion is applied after the real artifact
        # recount below.  No market-cap or price authority is consulted here.
        target_rows = universe
    else:
        target_rows = universe
    output_dir = OUTPUT_ROOT / requested_as_of.replace("-", "")
    tickers_dir = output_dir / "tickers"
    _preflight_directory(OUTPUT_ROOT)
    _preflight_directory(output_dir)
    _preflight_directory(tickers_dir)
    _preflight_directory(COMPANY_CACHE_DIR)

    secret = _load_opendart_key(env_file)
    quota_checkpoint_path = output_dir / "daily_quota_checkpoint.json"
    prior_quota_checkpoint = _load_prior_quota_checkpoint(quota_checkpoint_path) if mode == "priority" else {}
    prior_additional = int(prior_quota_checkpoint.get("actual_additional_requests", 0) or 0)
    remaining_baseline: int | None = None
    remaining_prior_additional = 0
    if mode == "priority":
        client: OpenDartClient = QuotaBoundOpenDartClient(
            api_key=secret,
            prior_additional_requests=prior_additional,
        )
    elif mode == "remaining":
        remaining_baseline, remaining_prior_additional = _load_remaining_quota_budget(
            quota_checkpoint_path
        )
        client = QuotaBoundOpenDartClient(
            api_key=secret,
            prior_additional_requests=remaining_prior_additional,
            max_additional_requests=REMAINING_MAX_ADDITIONAL_OPENDART_REQUESTS,
            official_usage_before=remaining_baseline,
            safety_daily_cap=REMAINING_SAFETY_DAILY_CAP,
        )
    else:
        client = OpenDartClient(api_key=secret)
    full_corp_repo, records_by_ticker = _load_exact_corp_repository()
    # Bound the provider's lookup repository to the exact mapping cache rows;
    # this avoids repeated scans of the 118k-record source cache without
    # changing the mapping authority or its exact-match semantics.
    target_records = tuple(item for rows in records_by_ticker.values() for item in rows)
    corp_repo = ExactCorpCodeRepository(records=target_records)
    _ = full_corp_repo  # Keep the source repository alive for audit/debugging.
    filing_registry = BoundedFilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl_repository = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    periodization_provider = PeriodizationProvider(corp_repo, filing_registry, xbrl_repository)
    multi_period_provider = MultiPeriodFundamentalsProvider(periodization_provider)

    started = _now()
    started_monotonic = time.monotonic()
    rows: list[dict[str, Any]] = []
    preexisting_priority_tickers = {
        str(row["ticker"]) for row in target_rows
        if _load_existing(
            tickers_dir / f"{row['ticker']}.json",
            ticker=str(row["ticker"]),
            requested_as_of=requested_as_of,
        ) is not None
    }
    preexisting_completed_tickers = {
        str(row.get("ticker"))
        for row in _load_completed_rows(universe, tickers_dir, requested_as_of)
    }
    if mode == "remaining":
        target_rows = _select_remaining_rows(universe, preexisting_completed_tickers)
        print(json.dumps({
            "mode": mode,
            "total_universe": len(universe),
            "start_completed": len(preexisting_completed_tickers),
            "start_remaining": len(target_rows),
            "market_cap_filter": None,
            "price_filter": None,
            "quota_baseline_daily_total_estimate": remaining_baseline,
            "max_additional_requests": REMAINING_MAX_ADDITIONAL_OPENDART_REQUESTS,
        }, ensure_ascii=False), flush=True)
    stop_reason = "TARGET_SET_EXHAUSTED"
    for index, universe_row in enumerate(target_rows, start=1):
        ticker = str(universe_row["ticker"])
        path = tickers_dir / f"{ticker}.json"
        existing = _load_existing(path, ticker=ticker, requested_as_of=requested_as_of)
        if existing is not None:
            rows.append(existing)
            continue
        before_requests = len(client.audit)
        try:
            result = hydrate_one(
                universe_row,
                requested_as_of=requested_as_of,
                corp_repo=corp_repo,
                records_by_ticker=records_by_ticker,
                client=client,
                company_cache_dir=COMPANY_CACHE_DIR,
                secret=secret,
                period_provider=multi_period_provider,
            )
        except QuotaBudgetExceeded as exc:
            stop_reason = exc.reason
            print(json.dumps({
                "stop": stop_reason,
                "processed": len(rows),
                "target_total": len(target_rows),
                "actual_additional_requests": exc.additional_requests,
                "estimated_daily_total": exc.daily_total,
            }, ensure_ascii=False), flush=True)
            break
        except KeyboardInterrupt:
            stop_reason = "INTERRUPTED"
            break
        except F7TerminalError as exc:
            if mode == "remaining" and _is_systematic_transport_failure(exc):
                stop_reason = "REPEATED_HTTP_FAILURE"
                print(json.dumps({
                    "stop": stop_reason,
                    "processed": len(rows),
                    "target_total": len(target_rows),
                    "actual_additional_requests": client.current_additional_requests,
                    "estimated_daily_total": client.estimated_daily_total,
                }, ensure_ascii=False), flush=True)
                break
            result = _record_failure(universe_row, requested_as_of, exc)
        result["api_request_count"] = len(client.audit) - before_requests
        result["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 3)
        _write_json_checked(path, result)
        rows.append(result)
        if index == 1 or index % 10 == 0 or index == len(target_rows):
            counts = Counter(str(item.get("terminal_status")) for item in rows)
            print(json.dumps({
                "processed": index,
                "total": len(target_rows),
                "PASS": counts.get("PASS", 0),
                "FILTERED": sum(value for key, value in counts.items() if key.startswith("FILTERED_")),
                "DATA_UNAVAILABLE": counts.get("DATA_UNAVAILABLE", 0),
                "NOT_APPLICABLE": counts.get("NOT_APPLICABLE", 0),
                "api_requests": len(client.audit),
                "elapsed_seconds": round(time.monotonic() - started_monotonic, 1),
            }, ensure_ascii=False), flush=True)

    if mode == "priority":
        completed_rows = _load_completed_rows(universe, tickers_dir, requested_as_of)
        _write_index(output_dir / "ticker_index.csv", completed_rows)
        completed_at = _now()
        assert isinstance(client, QuotaBoundOpenDartClient)
        checkpoint = _daily_quota_checkpoint(
            completed_rows=completed_rows,
            universe=universe,
            priority_tickers=priority_tickers,
            priority_info=priority_info,
            preexisting_completed_tickers=preexisting_completed_tickers,
            preexisting_priority_tickers=preexisting_priority_tickers,
            requested_as_of=requested_as_of,
            metadata_snapshot_date=metadata_snapshot_date,
            started_at=started,
            completed_at=completed_at,
            client=client,
            stop_reason=stop_reason,
        )
        _write_json_checked(quota_checkpoint_path, checkpoint)
        print(json.dumps({
            "status": checkpoint["status"],
            "mode": mode,
            "stop_reason": stop_reason,
            "requested_as_of": requested_as_of,
            "priority_candidates": priority_info["priority_common_candidate_count"],
            "newly_processed": checkpoint["universe"]["priority_newly_processed"],
            "priority_remaining": checkpoint["universe"]["priority_remaining"],
            "actual_additional_requests": checkpoint["actual_additional_requests"],
            "estimated_daily_total": checkpoint["estimated_daily_total_after_run"],
            "checkpoint": str(quota_checkpoint_path.relative_to(ROOT)),
        }, ensure_ascii=False))
        return 0

    if mode == "remaining":
        completed_rows = _load_completed_rows(universe, tickers_dir, requested_as_of)
        _write_index(output_dir / "ticker_index.csv", completed_rows)
        completed_at = _now()
        assert isinstance(client, QuotaBoundOpenDartClient)
        assert remaining_baseline is not None
        checkpoint = _remaining_quota_checkpoint(
            completed_rows=completed_rows,
            universe=universe,
            start_completed_tickers=preexisting_completed_tickers,
            requested_as_of=requested_as_of,
            metadata_snapshot_date=metadata_snapshot_date,
            started_at=started,
            completed_at=completed_at,
            client=client,
            stop_reason=stop_reason,
            baseline_daily_total=remaining_baseline,
        )
        _write_json_checked(quota_checkpoint_path, checkpoint)
        print(json.dumps({
            "status": checkpoint["status"],
            "mode": mode,
            "stop_reason": stop_reason,
            "requested_as_of": requested_as_of,
            "start_completed": checkpoint["start_completed"],
            "newly_completed": checkpoint["newly_completed_today"],
            "end_completed": checkpoint["end_completed"],
            "end_remaining": checkpoint["end_remaining"],
            "additional_opendart_requests": checkpoint["quota"]["additional_opendart_requests"],
            "estimated_daily_total": checkpoint["quota"]["estimated_daily_total_after_run"],
            "checkpoint": str(quota_checkpoint_path.relative_to(ROOT)),
        }, ensure_ascii=False))
        return 0

    # Full mode must account for every authority row.  Pilot mode is bounded
    # by design and is validated separately before the full run.
    if mode == "full":
        target_tickers = {str(row["ticker"]) for row in universe}
        observed_tickers = {str(row.get("ticker")) for row in rows}
        missing = sorted(target_tickers - observed_tickers)
        if missing:
            raise RuntimeError(f"missing production ticker outputs: {missing[:10]}")

    _write_index(output_dir / "ticker_index.csv", rows)
    completed = _now()
    manifest = _summary(
        rows,
        requested_as_of=requested_as_of,
        metadata_snapshot_date=metadata_snapshot_date,
        started_at=started,
        completed_at=completed,
        client=client,
        pilot_count=len(target_rows) if mode == "pilot" else None,
    )
    manifest["mode"] = mode
    manifest["total_runtime_seconds"] = round(time.monotonic() - started_monotonic, 3)
    manifest["filing_registry_preload"] = {
        "year_fetches": filing_registry.preload_year_fetches,
        "pages_fetched": filing_registry.preload_pages_fetched,
        "strategy": "one_complete_list_json_window_per_missing_ticker_year",
    }
    _write_json_checked(output_dir / "manifest.json", manifest)
    print(json.dumps({
        "final_status": manifest["final_status"],
        "mode": mode,
        "requested_as_of": requested_as_of,
        "processed": len(rows),
        "api_requests": len(client.audit),
        "runtime_seconds": manifest["total_runtime_seconds"],
        "output": str(output_dir.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pilot", action="store_true", help="Run the bounded 5-10 ticker pilot")
    group.add_argument("--full", action="store_true", help="Run/resume the complete production universe")
    group.add_argument(
        "--priority",
        action="store_true",
        help="Run today's 2026-09-04 market-cap/close priority batch with quota cap",
    )
    group.add_argument(
        "--remaining",
        action="store_true",
        help="Resume only unfinished production tickers with today's remaining quota cap",
    )
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    try:
        mode = (
            "pilot" if args.pilot else "priority" if args.priority
            else "remaining" if args.remaining else "full"
        )
        return run(mode, env_file=args.env_file)
    except Exception as exc:
        # Never echo exception text here: a transport-layer failure must not
        # accidentally reveal credentials or a URL carrying credentials.
        print(f"FINAL_STATUS=CHANGES_REQUESTED:{type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
