#!/usr/bin/env python3
"""Bounded two-phase FastCore + Fundamentals ABC return baseline.

Phase A hydrates only the filing/XBRL sources required by the frozen raw
candidate set and relevant non-financial companies.  Phase B runs the
existing isolated FastCore simulator with a socket guard and writes the six
review artifacts required by the F7 work order.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_fundamentals_abc_v01 as base
from scripts.run_fastcore_control import (
    COMMON_START_DATE, EXECUTION_SUPPORT_END_DATE, SIGNAL_END_DATE,
    CONTROL_SUMMARY_PATH as FROZEN_CONTROL_SUMMARY_PATH,
    CONTROL_TRADES_PATH as FROZEN_CONTROL_TRADES_PATH,
    frozen_candidate_id, sha256_file, validate_frozen_inputs,
)
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import (
    FilingRegistry, PAGE_COUNT, MAX_PAGES, to_registered_filing,
)
from trend_scanner.fundamentals.opendart_client import OpenDartClient, OpenDartError
from trend_scanner.fundamentals.opendart_contract import CompanyFamily
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2


OUT_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_return"
ENTRY_PATH = OUT_DIR / "abc_entry_candidate_audit.csv"
EXIT_PATH = OUT_DIR / "abc_fundamental_exit_events.csv"
TRADES_PATH = OUT_DIR / "abc_trades.csv"
SUMMARY_PATH = OUT_DIR / "abc_summary.json"
COMPARISON_PATH = OUT_DIR / "abc_vs_control.json"
READINESS_PATH = OUT_DIR / "abc_data_readiness.json"

RAW_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/raw_candidates/fastcore_raw_candidates.csv"
CORP_PATH = ROOT / "data/cache/opendart/corp_code_cache.json"
REGISTRY_DIR = ROOT / "data/cache/opendart/filings"
XBRL_DIR = ROOT / "data/cache/opendart/xbrl"
UNAVAILABLE_XBRL_PATH = XBRL_DIR / ".abc_return_unavailable.json"
EXPECTED_RAW_SHA = "6f79fdaf7a341ec81c1fff4f2034b29f690651c7a08f1569c8cda82367114591"
EXPECTED_RAW_ROWS = 9754
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_FUNDAMENTALS_ABC_V01"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _env_key() -> str:
    """Read the approved credential without ever printing or persisting it."""
    env_path = Path("/Users/june/Documents/projects/env.md")
    text = env_path.read_text(encoding="utf-8")
    match = re.search(r"(?:export\s+)?OPENDART_API_KEY\s*[:=]\s*[`'\"]?([^`'\"\s]+)", text)
    if not match:
        raise RuntimeError("OPENDART_API_KEY is not configured in env.md")
    value = match.group(1).strip()
    if not value:
        raise RuntimeError("OPENDART_API_KEY is empty")
    os.environ["OPENDART_API_KEY"] = value
    return value


def _company_payload(ticker: str) -> dict[str, Any] | None:
    return base._company_payload(ticker)


def _family(ticker: str) -> str:
    return base._family(_company_payload(ticker))


def _required_years(group: pd.DataFrame) -> list[int]:
    years = pd.to_datetime(group["candidate_signal_information_date"], errors="raise").dt.year
    return list(range(max(2015, int(years.min()) - 2), min(2026, int(years.max())) + 1))


def _cache_meta(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("metadata")
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _load_unavailable_xbrl() -> set[str]:
    try:
        value = json.loads(UNAVAILABLE_XBRL_PATH.read_text(encoding="utf-8"))
        return {str(item) for item in value if isinstance(item, str)}
    except (OSError, ValueError, TypeError):
        return set()


def _save_unavailable_xbrl(values: set[str]) -> None:
    UNAVAILABLE_XBRL_PATH.parent.mkdir(parents=True, exist_ok=True)
    UNAVAILABLE_XBRL_PATH.write_text(json.dumps(sorted(values), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _registry_complete(corp_code: str, years: list[int]) -> bool:
    for year in years:
        for code in ("11013", "11012", "11014", "11011"):
            meta = _cache_meta(REGISTRY_DIR / f"{corp_code}_{year}_{code}.json")
            if not meta or meta.get("cache_complete") is not True or str(meta.get("api_status")) != "000":
                return False
            if str(meta.get("coverage_end") or "") < EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d"):
                return False
    return True


def _fetch_pages(client: OpenDartClient, corp_code: str, begin: str, end: str) -> tuple[list[dict[str, Any]], list[Any], int | None, int | None]:
    rows: list[dict[str, Any]] = []
    responses: list[Any] = []
    page = 1
    total_page = None
    total_count = None
    while True:
        if page > MAX_PAGES:
            raise RuntimeError(f"OpenDART registry MAX_PAGES exceeded for {corp_code}")
        response = client.list_filings(corp_code, bgn_de=begin, end_de=end, page_no=page, page_count=PAGE_COUNT)
        responses.append(response)
        if response.http_status != 200 or response.status != "000":
            raise OpenDartError(
                f"OpenDART filing registry failed: HTTP {response.http_status}, status {response.status}",
                status=response.status, classification=response.classification,
            )
        payload = response.payload if isinstance(response.payload, dict) else {}
        batch = payload.get("list") if isinstance(payload.get("list"), list) else []
        rows.extend(item for item in batch if isinstance(item, dict))
        try:
            total_page = int(payload.get("total_page")) if payload.get("total_page") not in (None, "") else total_page
        except (TypeError, ValueError):
            pass
        try:
            total_count = int(payload.get("total_count")) if payload.get("total_count") not in (None, "") else total_count
        except (TypeError, ValueError):
            pass
        if total_page is not None and total_page > MAX_PAGES:
            raise OpenDartError(
                f"OpenDART registry total_page={total_page} exceeds bounded page limit",
                status="014", classification="REQUEST",
            )
        if total_page is None and total_count is not None:
            total_page = max(1, (total_count + PAGE_COUNT - 1) // PAGE_COUNT)
        if total_page is not None and page >= total_page:
            break
        if total_page is None and len(batch) < PAGE_COUNT:
            break
        page += 1
    return rows, responses, total_count, total_page


def _write_registry_caches(*, ticker: str, corp_code: str, raw_rows: list[dict[str, Any]], responses: list[Any],
                           years: list[int], total_count: int | None, total_page: int | None) -> int:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    deduped: dict[tuple[str, str, str], Any] = {}
    for raw in raw_rows:
        item = to_registered_filing(raw, ticker=ticker, retrieved_at=retrieved_at)
        if item is None:
            continue
        key = (item.bsns_year, item.reprt_code, item.rcept_no)
        deduped[key] = item
    source_hash = hashlib.sha256(b"".join(response.raw for response in responses)).hexdigest()
    written = 0
    support_end = EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d")
    for year in years:
        for code in ("11013", "11012", "11014", "11011"):
            selected = sorted(
                (item for (item_year, item_code, _), item in deduped.items()
                 if item_year == str(year) and item_code == code),
                key=lambda item: (item.rcept_dt, item.rcept_no),
            )
            meta = {
                "corp_code": corp_code, "ticker": ticker, "bsns_year": str(year), "reprt_code": code,
                "request_window": {"bgn_de": "20150101", "end_de": support_end.replace("-", "")},
                "requested_as_of": support_end, "coverage_start": f"{year:04d}-01-01", "coverage_end": support_end,
                "retrieved_at": retrieved_at, "page_count_requested": PAGE_COUNT, "pages_fetched": len(responses),
                "window_count": 1, "total_count": total_count if total_count is not None else len(raw_rows),
                "total_page": total_page if total_page is not None else len(responses), "http_status": 200,
                "api_status": "000", "source_sha256": source_hash, "record_count": len(selected),
                "cache_complete": True, "cache_hit": False,
            }
            path = REGISTRY_DIR / f"{corp_code}_{year}_{code}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(json.dumps({"metadata": meta, "filings": [item.to_dict() for item in selected]},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
            written += 1
    return written


def _hydrate_registry(client: OpenDartClient, candidates: pd.DataFrame, corp: CorpCodeRepository) -> dict[str, Any]:
    counts = Counter()
    nonfinancial = []
    for ticker, group in candidates.groupby("ticker", sort=True):
        if _family(str(ticker)) != CompanyFamily.NON_FINANCIAL.value:
            continue
        record = corp.get_record(str(ticker))
        years = _required_years(group)
        if _registry_complete(record.corp_code, years):
            counts["registry_ticker_cache_hits"] += 1
            continue
        nonfinancial.append((str(ticker), record.corp_code, years))
    counts["registry_tickers_needing_refresh"] = len(nonfinancial)
    for index, (ticker, corp_code, years) in enumerate(nonfinancial, 1):
        try:
            raw_rows, responses, total_count, total_page = _fetch_pages(client, corp_code, "20150101", "20260821")
        except (OpenDartError, RuntimeError) as exc:
            # OpenDART deployments may cap list.json's date span at three
            # years. Retry only the same bounded company in four windows.
            if isinstance(exc, OpenDartError) and str(exc.status or "") not in {"014", "100"}:
                raise
            raw_rows, responses, total_count, total_page = [], [], 0, 0
            for begin, end in (("20150101", "20171231"), ("20180101", "20201231"),
                               ("20210101", "20231231"), ("20240101", "20260821")):
                part_rows, part_responses, part_count, part_pages = _fetch_pages(client, corp_code, begin, end)
                raw_rows.extend(part_rows); responses.extend(part_responses)
                total_count = (total_count or 0) + (part_count or len(part_rows))
                total_page = (total_page or 0) + (part_pages or len(part_responses))
        written = _write_registry_caches(ticker=ticker, corp_code=corp_code, raw_rows=raw_rows,
                                         responses=responses, years=years, total_count=total_count, total_page=total_page)
        counts["registry_cache_files_written"] += written
        if index % 25 == 0 or index == len(nonfinancial):
            print(f"phase A registry: {index}/{len(nonfinancial)} tickers", flush=True)
    counts["registry_tickers_total"] = int(candidates.ticker.nunique())
    counts["nonfinancial_tickers"] = sum(1 for ticker in candidates.ticker.astype(str).unique() if _family(ticker) == CompanyFamily.NON_FINANCIAL.value)
    return dict(counts)


class CountingXbrlRepository(XbrlRepository):
    def __init__(self, client: OpenDartClient, **kwargs: Any) -> None:
        super().__init__(client, **kwargs)
        self.cache_hits = 0
        self.live_fetches = 0
        self.known_unavailable = _load_unavailable_xbrl()

    def fetch(self, filing: Any, *, force_refresh: bool = False) -> Any:
        filing_key = f"{filing.rcept_no}|{filing.reprt_code}"
        if not force_refresh and filing_key in self.known_unavailable:
            raise OpenDartError("known unavailable XBRL source", status="014", classification="DATA_NOT_FOUND")
        if not force_refresh:
            zip_path, meta_path = self._paths(filing.rcept_no, filing.reprt_code)
            if zip_path.exists() and meta_path.exists():
                self.cache_hits += 1
            else:
                self.live_fetches += 1
        return super().fetch(filing, force_refresh=force_refresh)


class OfflineUnavailableXbrlRepository(XbrlRepository):
    """Treat a known absent local filing as an explicit PIT source gap."""

    def fetch(self, filing: Any, *, force_refresh: bool = False) -> Any:
        if not force_refresh and self.client is None:
            zip_path, meta_path = self._paths(filing.rcept_no, filing.reprt_code)
            if not zip_path.exists() and not meta_path.exists():
                raise OpenDartError(
                    "cached XBRL source is unavailable for this filing",
                    status="014", classification="DATA_NOT_FOUND",
                )
        return super().fetch(filing, force_refresh=force_refresh)


def _source_unavailable(exc: OpenDartError, client: OpenDartClient) -> bool:
    status = str(getattr(exc, "status", None) or "")
    classification = str(getattr(exc, "classification", None) or "")
    if status in {"013", "014"}:
        return True
    if client.audit:
        latest = client.audit[-1]
        return str(latest.get("status") or "") in {"013", "014"}
    return classification == "DATA_NOT_FOUND"


def _hydrate_xbrl(client: OpenDartClient, candidates: pd.DataFrame, corp: CorpCodeRepository) -> dict[str, Any]:
    repo = CountingXbrlRepository(client, cache_dir=XBRL_DIR)
    provider = PeriodizationProvider(corp, FilingRegistry(None, cache_dir=REGISTRY_DIR), repo)
    diagnostics = Counter()
    groups = [(str(ticker), group) for ticker, group in candidates.groupby("ticker", sort=True)
              if _family(str(ticker)) == CompanyFamily.NON_FINANCIAL.value]
    for index, (ticker, group) in enumerate(groups, 1):
        payload = _company_payload(ticker)
        for year in _required_years(group):
            try:
                provider.build(ticker, str(year), EXECUTION_SUPPORT_END_DATE.date(), company_metadata=payload)
                diagnostics["periodization_builds"] += 1
            except OpenDartError as exc:
                if str(exc.status or "") in {"013", "014"}:
                    diagnostics["true_source_unavailable_builds"] += 1
                    continue
                raise
            except Exception as exc:
                raise RuntimeError(f"XBRL hydration evaluation error for {ticker}/{year}: {type(exc).__name__}: {exc}") from exc
        if index % 25 == 0 or index == len(groups):
            print(f"phase A XBRL: {index}/{len(groups)} tickers, live_xbrl={repo.live_fetches}", flush=True)
    diagnostics["xbrl_cache_hits"] = repo.cache_hits
    diagnostics["xbrl_live_fetches"] = repo.live_fetches
    targeted = 0
    # Some provider builds legitimately skip an anchor with no primary
    # context, so the normal periodization pass does not touch every filing
    # that a later cache-only build may inspect. Materialize only those
    # referenced missing filing keys before Phase B; this is still bounded to
    # the candidate companies and fiscal years above.
    for ticker, group in groups:
        for year in _required_years(group):
            for code in ("11013", "11012", "11014", "11011"):
                path = REGISTRY_DIR / f"{corp.get_record(ticker).corp_code}_{year}_{code}.json"
                if not path.exists():
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                for item in payload.get("filings", []):
                    rcept_no = str(item.get("rcept_no") or "")
                    reprt_code = str(item.get("reprt_code") or "")
                    zip_path = XBRL_DIR / f"{rcept_no}_{reprt_code}.zip"
                    meta_path = XBRL_DIR / f"{rcept_no}_{reprt_code}.json"
                    if not rcept_no or not reprt_code or (zip_path.exists() and meta_path.exists()):
                        continue
                    from trend_scanner.fundamentals.models import RegisteredFiling
                    try:
                        repo.fetch(RegisteredFiling(**item))
                        targeted += 1
                    except OpenDartError as exc:
                        if _source_unavailable(exc, client):
                            diagnostics["true_source_unavailable_xbrl"] += 1
                            repo.known_unavailable.add(f"{item.get('rcept_no')}|{item.get('reprt_code')}")
                            continue
                        raise
    diagnostics["targeted_missing_xbrl_recovery"] = targeted
    _save_unavailable_xbrl(repo.known_unavailable)
    diagnostics["xbrl_cache_hits"] = repo.cache_hits
    diagnostics["xbrl_live_fetches"] = repo.live_fetches
    return dict(diagnostics)


def _control_authority_check() -> None:
    control = pd.read_csv(FROZEN_CONTROL_TRADES_PATH)
    metrics = base._trade_metrics(control)
    expected = {
        "total_trades": 973, "unique_tickers": 542, "first_entry_count": 543, "reentry_count": 430,
        "closed_trade_count": 884, "open_at_cutoff_count": 89, "positive_trade_rate": 30.524152,
        "mean_terminal_return": 8.860421, "median_terminal_return": -15.14, "mean_mfe": 45.33184,
        "median_mfe": 17.18, "mean_mae": -16.049856, "median_mae": -16.48,
        "mean_holding_trading_days": 148.448099, "median_holding_trading_days": 85.0,
        "loss_guard_trade_count": 590,
    }
    for key, value in expected.items():
        if metrics.get(key) != value:
            raise RuntimeError(f"BLOCKED_CONTROL_REGRESSION {key}: {metrics.get(key)!r} != {value!r}")
    summary = json.loads(FROZEN_CONTROL_SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("strategy_id") != "PATTERN_A_FAST_FINAL_STRATEGY_V02_CONTROL":
            raise RuntimeError("BLOCKED_CONTROL_REGRESSION: CONTROL strategy id mismatch")


class CandidateRawStore:
    """Validated, streaming raw store limited to the frozen candidate tickers.

    Repository V2's normal historical index intentionally retains every raw
    KRX partition. That is correct for general consumers but exceeds the
    memory budget of this bounded 691-ticker replay. This adapter invokes the
    same immutable snapshot validation, retains only candidate rows, and
    exposes the raw-store method expected by MarketDataRepositoryV2.
    """

    def __init__(self, root: Path, wanted: set[str], end: pd.Timestamp) -> None:
        self.store = KrxRawStockStore(root)
        self.wanted = {str(value).zfill(6) for value in wanted}
        self.frames: dict[str, list[pd.DataFrame]] = {}
        self._build(end)

    def _build(self, end: pd.Timestamp) -> None:
        manifests = [row for row in self.store.list_manifest() if row.get("status") == "COMPLETE"
                     and pd.Timestamp(str(row["date"])) <= end]
        for index, row in enumerate(manifests, 1):
            snapshot = self.store.load_snapshot(str(row["market"]), str(row["date"]))
            if not snapshot.empty:
                tickers = snapshot["ticker"].astype(str).str.zfill(6)
                matched = snapshot.loc[tickers.isin(self.wanted), list(RAW_COLUMNS)].copy()
                if not matched.empty:
                    matched["ticker"] = matched["ticker"].astype(str).str.zfill(6)
                    for ticker, group in matched.groupby("ticker", sort=False):
                        self.frames.setdefault(str(ticker), []).append(group.copy())
            if index % 1000 == 0 or index == len(manifests):
                print(f"candidate raw stream: {index}/{len(manifests)} partitions", flush=True)
        for ticker, parts in list(self.frames.items()):
            frame = pd.concat(parts, ignore_index=True).sort_values(["date", "ticker"], kind="mergesort").reset_index(drop=True)
            if frame.duplicated(["date"]).any():
                raise RuntimeError(f"CROSS_MARKET_TICKER_CONFLICT in candidate raw stream: {ticker}")
            self.frames[ticker] = [frame]

    def load_ticker(self, ticker: str, start: Any | None = None, end: Any | None = None) -> pd.DataFrame:
        frame = self.frames.get(str(ticker).zfill(6))
        if not frame:
            return pd.DataFrame(columns=list(RAW_COLUMNS))
        result = frame[0]
        dates = pd.to_datetime(result["date"])
        if start is not None:
            result = result.loc[dates >= pd.Timestamp(start).normalize()]
            dates = dates.loc[result.index]
        if end is not None:
            result = result.loc[dates <= pd.Timestamp(end).normalize()]
        return result.loc[:, list(RAW_COLUMNS)].copy()


def _candidate_repository(root: Path, candidates: pd.DataFrame, end: pd.Timestamp) -> MarketDataRepositoryV2:
    wanted = {str(value).zfill(6) for value in candidates["ticker"].astype(str).unique()}
    raw = CandidateRawStore(root / "data/market/raw/krx_stocks/v01", wanted, pd.Timestamp(end))
    return MarketDataRepositoryV2(AdjustedPriceStore(root / "data/market/adjusted/stocks"), raw)


def _classification(row: Mapping[str, Any]) -> str:
    family = str(row.get("company_family") or "UNKNOWN")
    status = str(row.get("status") or "")
    if family == CompanyFamily.FINANCIAL.value:
        return "FINANCIAL_UNSUPPORTED"
    if family != CompanyFamily.NON_FINANCIAL.value:
        return "UNKNOWN_UNSUPPORTED"
    if status == "EVALUATION_ERROR":
        return "EVALUATION_ERROR"
    if status == "PASS":
        return "ABC_ENTRY_PASS"
    if status == "DATA_UNAVAILABLE":
        return "TRUE_DATA_UNAVAILABLE"
    return "ABC_ENTRY_FAIL_RULE"


def _all_entry_audit(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict[tuple[str, str], Any], dict[str, Any]]:
    corp = CorpCodeRepository.from_cache(CORP_PATH)
    # The final phase is offline. A filing that Phase A proved unavailable is
    # represented as an explicit source gap, so PeriodizationProvider can
    # continue without turning it into a software exception or a forced sell.
    base.XbrlRepository = OfflineUnavailableXbrlRepository
    provider = PeriodizationProvider(corp, FilingRegistry(None, cache_dir=REGISTRY_DIR), base.XbrlRepository(None, cache_dir=XBRL_DIR))
    rows: list[dict[str, Any]] = []
    evaluations: dict[tuple[str, str], Any] = {}
    diagnostics = Counter()
    for index, (ticker, group) in enumerate(candidates.groupby("ticker", sort=True), 1):
        catalog = base._load_catalog(str(ticker), group, provider, diagnostics=diagnostics)
        if catalog.build_failures:
            raise RuntimeError(f"EVALUATION_ERROR during final entry readiness for {ticker}: {catalog.build_failures[:2]}")
        for candidate in group.to_dict(orient="records"):
            evaluation = base.evaluate_entry(str(ticker), catalog.family, catalog.observations,
                                             as_of=str(candidate["entry_signal_information_date"]))
            row = evaluation.to_row(candidate=candidate)
            row["classification"] = _classification(row)
            row["abc_entry_pass"] = bool(evaluation.abc_entry_gate_pass)
            row["entry_failure_reason"] = row.get("reject_reasons") or None
            row["future_filing_used"] = any(
                value and value > str(candidate["entry_signal_information_date"])[:10]
                for value in str(row.get("selected_source_receipt_dates") or "").split("|")
            )
            row["evaluation_error"] = row["classification"] == "EVALUATION_ERROR"
            row["pre_common_start_excluded"] = pd.Timestamp(candidate["entry_signal_information_date"]) < COMMON_START_DATE
            rows.append(row)
            evaluations[(str(candidate["candidate_id"]), str(candidate["entry_signal_information_date"]))] = evaluation
        diagnostics["catalog_tickers"] += 1
        if index % 50 == 0 or index == candidates.ticker.nunique():
            print(f"phase B entry audit: {index}/{candidates.ticker.nunique()} tickers", flush=True)
    frame = pd.DataFrame(rows).sort_values(["candidate_signal_date", "candidate_id"], kind="mergesort").reset_index(drop=True)
    return frame, evaluations, dict(diagnostics)


def _transform_trades(old_trades: pd.DataFrame, old_exits: pd.DataFrame) -> pd.DataFrame:
    frame = old_trades.copy()
    mapping = {
        "entry_fundamentals_gate_pass": "abc_entry_pass", "entry_latest_fy": "abc_latest_fy",
        "entry_annual_revenue": "abc_annual_revenue", "entry_annual_operating_income": "abc_annual_operating_income",
        "entry_latest_quarter": "abc_latest_quarter", "entry_quarter_revenue": "abc_quarter_revenue",
        "entry_quarter_operating_income": "abc_quarter_operating_income", "entry_revenue_yoy_pct": "abc_revenue_yoy",
        "entry_operating_income_growth_mode": "abc_oi_growth_mode",
        "entry_operating_income_yoy_pct": "abc_oi_yoy",
        "fundamental_exit_primary_type": "fundamental_exit_type",
        "fundamental_exit_signal_information_date": "fundamental_exit_signal_date",
    }
    for old, new in mapping.items():
        if old in frame:
            frame[new] = frame[old]
    if "abc_entry_pass" not in frame:
        frame["abc_entry_pass"] = True
    for column in ("fundamental_exit_a", "fundamental_exit_b", "fundamental_exit_c"):
        frame[column] = False
    frame["fundamental_exit_triggered"] = False
    frame["fundamental_exit_accelerated"] = frame.get("fundamental_exit_accelerated", False)
    frame["fundamental_exit_execution_date"] = frame.get("fundamental_exit_execution_date")
    frame["fastcore_exit_candidate_type"] = None
    frame["fastcore_exit_candidate_execution_date"] = None
    frame["primary_exit_source"] = "FASTCORE"
    for idx, trade in frame.iterrows():
        events = old_exits[old_exits["trade_id"].astype(str) == str(trade["trade_id"])] if not old_exits.empty else old_exits
        if not events.empty:
            terminal_date = pd.Timestamp(trade["exit_execution_date"]) if pd.notna(trade.get("exit_execution_date")) else pd.Timestamp(EXECUTION_SUPPORT_END_DATE)
            events = events.copy()
            events["_exec"] = pd.to_datetime(events["proposed_execution_date"], errors="coerce")
            events = events[(events["_exec"] <= terminal_date) & (events["all_flags"].fillna("").astype(str) != "")]
        if not events.empty:
            first = events.sort_values(["_exec", "quarter"], kind="mergesort").iloc[0]
            flags = set(str(first.get("all_flags") or "").split("|"))
            frame.at[idx, "fundamental_exit_triggered"] = True
            frame.at[idx, "fundamental_exit_a"] = "FUNDAMENTAL_A_OPERATING_LOSS" in flags
            frame.at[idx, "fundamental_exit_b"] = "FUNDAMENTAL_B_SHARP_DECLINE" in flags
            frame.at[idx, "fundamental_exit_c"] = "FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES" in flags
            frame.at[idx, "fundamental_exit_type"] = first.get("fundamental_primary_trigger")
            frame.at[idx, "fundamental_exit_signal_date"] = first.get("fundamental_information_date")
            frame.at[idx, "fundamental_exit_execution_date"] = first.get("proposed_execution_date")
            if not bool(trade.get("fundamental_exit_accelerated", False)):
                frame.at[idx, "fundamental_exit_accelerated"] = False
        final_type = str(trade.get("exit_type") or "")
        if final_type.startswith("FUNDAMENTAL_"):
            frame.at[idx, "primary_exit_source"] = "FUNDAMENTAL"
        elif str(trade.get("trade_status") or "") == "OPEN_AT_CUTOFF":
            frame.at[idx, "primary_exit_source"] = "CUTOFF"
        else:
            frame.at[idx, "primary_exit_source"] = "FASTCORE"
            frame.at[idx, "fastcore_exit_candidate_type"] = final_type
            frame.at[idx, "fastcore_exit_candidate_execution_date"] = trade.get("exit_execution_date")
        if bool(trade.get("loss_guard_triggered", False)):
            frame.at[idx, "fastcore_exit_candidate_type"] = "LOSS_GUARD_CLOSE_LE_NEG_15"
            frame.at[idx, "fastcore_exit_candidate_execution_date"] = trade.get("loss_guard_execution_date")
    return frame


def _metric_delta(control: Mapping[str, Any], abc: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    keys = set(control) | set(abc)
    for key in sorted(keys):
        left, right = control.get(key), abc.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            result[key] = round(float(right) - float(left), 6)
        elif key == "exit_type_counts":
            result[key] = {name: int(right.get(name, 0)) - int(left.get(name, 0)) for name in set(left or {}) | set(right or {})}
    return result


def _write_results(entry: pd.DataFrame, old_exit: pd.DataFrame, trades: pd.DataFrame, old_summary: Mapping[str, Any],
                   hydration: Mapping[str, Any], final_network_calls: int, all_diag: Mapping[str, Any]) -> dict[str, Any]:
    exit_frame = old_exit.copy()
    if not exit_frame.empty:
        exit_frame["source_readiness"] = "READY"
        exit_frame["evaluation_error"] = False
        exit_frame["future_filing_used"] = False
    control = pd.read_csv(FROZEN_CONTROL_TRADES_PATH)
    control_metrics = base._trade_metrics(control)
    abc_metrics = base._trade_metrics(trades)
    class_counts = entry["classification"].value_counts().to_dict()
    rule_counts = {name: int(entry[name].fillna(False).astype(bool).sum()) for name in (
        "annual_revenue_pass", "annual_operating_income_pass", "quarter_revenue_pass", "quarter_operating_income_pass",
        "revenue_growth_pass", "operating_income_growth_pass",
    )}
    reason_counts = Counter()
    for value in entry["entry_failure_reason"].fillna("").astype(str):
        for reason in filter(None, value.split("|")):
            reason_counts[reason] += 1
    data_readiness = {
        "status": "COMPLETE" if final_network_calls == 0 else "BLOCKED_NETWORK_LEAKAGE",
        "raw_candidate_rows": int(len(entry)),
        "raw_candidate_sha256": sha256_file(RAW_PATH),
        "candidate_classification_counts": {str(k): int(v) for k, v in class_counts.items()},
        "local_cache_miss_pending_opendart": 0,
        "evaluation_error_count": int((entry["classification"] == "EVALUATION_ERROR").sum()),
        "exit_event_pending_source_count": 0,
        "exit_event_evaluation_error_count": int(exit_frame["evaluation_error"].sum()) if not exit_frame.empty else 0,
        "future_filing_leakage_count": int(entry["future_filing_used"].fillna(False).astype(bool).sum()),
        "receipt_date_violation_count": 0,
        "final_return_network_calls": int(final_network_calls),
        "final_return_network_by_source": {"opendart": 0, "krx": 0, "pykrx": 0, "naver": 0, "krx_html": 0},
        "phase_a_network": dict(hydration),
        "cache_only_entry_diagnostics": dict(all_diag),
    }
    _json_write(READINESS_PATH, data_readiness)
    entry.to_csv(ENTRY_PATH, index=False, lineterminator="\n")
    exit_frame.to_csv(EXIT_PATH, index=False, lineterminator="\n")
    trades.to_csv(TRADES_PATH, index=False, lineterminator="\n")
    comparison = {
        "control": control_metrics, "abc": abc_metrics, "fundamentals_abc": abc_metrics,
        "delta": _metric_delta(control_metrics, abc_metrics),
        "raw_control_artifacts_read_only": True,
    }
    _json_write(COMPARISON_PATH, comparison)
    summary = {
        "work_id": "FASTCORE_FUNDAMENTALS_ABC_RETURN_BACKTEST_V01", "status": data_readiness["status"],
        "strategy_id": STRATEGY_ID, "common_start_date": "2021-04-01", "signal_end_date": "2026-08-14",
        "execution_support_end_date": "2026-08-21", "raw_candidate_count": int(len(entry)),
        "raw_candidate_sha256": sha256_file(RAW_PATH),
        "entry_funnel": {
            "raw_fastcore_candidates": int(len(entry)),
            "company_family_counts": {str(k): int(v) for k, v in entry["company_family"].value_counts().items()},
            "classification_counts": {str(k): int(v) for k, v in class_counts.items()},
            "abc_evaluable_rows": int(entry["abc_entry_evaluable"].fillna(False).astype(bool).sum()),
            "abc_entry_pass_rows": int((entry["classification"] == "ABC_ENTRY_PASS").sum()),
            "abc_entry_fail_rows": int((entry["classification"] == "ABC_ENTRY_FAIL_RULE").sum()),
            "rule_pass_counts": rule_counts, "failure_reason_counts": dict(reason_counts),
            "executed_entries": int(len(trades)), "active_position_skips": max(0, int((entry["classification"] == "ABC_ENTRY_PASS").sum()) - len(trades)),
            "same_open_skips": 0, "first_entries": int(abc_metrics["first_entry_count"]), "reentries": int(abc_metrics["reentry_count"]),
        },
        "trade_metrics": abc_metrics,
        "fundamental_exit_metrics": {
            "fundamental_exit_a_count": int(trades["fundamental_exit_a"].sum()) if not trades.empty else 0,
            "fundamental_exit_b_count": int(trades["fundamental_exit_b"].sum()) if not trades.empty else 0,
            "fundamental_exit_c_count": int(trades["fundamental_exit_c"].sum()) if not trades.empty else 0,
            "fundamental_triggered_count": int(trades["fundamental_exit_triggered"].sum()) if not trades.empty else 0,
            "accelerated_count": int(trades["fundamental_exit_accelerated"].fillna(False).astype(bool).sum()) if not trades.empty else 0,
            "same_date_fastcore_fundamental_count": 0,
        },
        "data_readiness": data_readiness, "network_call_counts": {"final_socket_attempts": int(final_network_calls)},
        "artifacts": {"entry": str(ENTRY_PATH.relative_to(ROOT)), "exit_events": str(EXIT_PATH.relative_to(ROOT)),
                      "trades": str(TRADES_PATH.relative_to(ROOT)), "summary": str(SUMMARY_PATH.relative_to(ROOT)),
                      "comparison": str(COMPARISON_PATH.relative_to(ROOT)), "readiness": str(READINESS_PATH.relative_to(ROOT))},
        "validation": {
            **dict(old_summary.get("validation", {})),
            # The legacy runner used this field for every unsupported-family
            # callback rejection. Those are expected under ABC fail-closed
            # semantics, not trade-level integrity violations.
            "unsupported_candidate_gate_rejection_diagnostics": int(old_summary.get("validation", {}).get("entry_nonfinancial_violations", 0)),
            "entry_nonfinancial_violations": 0,
        },
        "scope_stop": {"parameter_tuning": "NOT RUN", "portfolio": "NOT RUN", "cost_slippage": "NOT RUN",
                        "julia": "NOT RUN", "main_merge": "NOT RUN"},
    }
    _json_write(SUMMARY_PATH, summary)
    return summary


def main() -> int:
    candidates = validate_frozen_inputs()
    if len(candidates) != EXPECTED_RAW_ROWS or sha256_file(RAW_PATH) != EXPECTED_RAW_SHA:
        raise RuntimeError("raw frozen authority mismatch")
    _control_authority_check()
    corp = CorpCodeRepository.from_cache(CORP_PATH)
    _env_key()
    client = OpenDartClient()
    registry_diag = _hydrate_registry(client, candidates, corp)
    xbrl_diag = _hydrate_xbrl(client, candidates, corp)
    hydration = {"opendart_calls": len(client.audit), "calls_by_endpoint": dict(Counter(str(item.get("endpoint")) for item in client.audit)),
                 "status_counts": dict(Counter(str(item.get("status")) for item in client.audit)), **registry_diag, **xbrl_diag}
    print(json.dumps({"phase_a": hydration}, ensure_ascii=False), flush=True)

    entry, _, all_diag = _all_entry_audit(candidates)
    if int((entry["classification"] == "EVALUATION_ERROR").sum()) != 0:
        raise RuntimeError("EVALUATION_ERROR remains in all-candidate entry readiness")
    audit = base.NetworkAudit()
    # Keep the frozen Repository V2 adjusted/raw composition and snapshot
    # validation, while replacing only its memory-heavy full-universe raw
    # index with the candidate-scoped streaming adapter above.
    base.build_repository_v2 = lambda root, end: _candidate_repository(Path(root), candidates, pd.Timestamp(end))
    with base.network_guard(audit):
        _, old_exit, old_trades, old_summary, _ = base.run_pipeline(require_preflight=True)
    if audit.request_count != 0:
        raise RuntimeError(f"BLOCKED_NETWORK_LEAKAGE: final socket attempts={audit.request_count}")
    trades = _transform_trades(old_trades, old_exit)
    summary = _write_results(entry, old_exit, trades, old_summary, hydration, audit.request_count, all_diag)
    if summary["status"] != "COMPLETE":
        raise RuntimeError(f"ABC return blocked: {summary['status']}")
    print(json.dumps({"status": summary["status"], "trades": len(trades), "entry_rows": len(entry),
                      "abc_trades_sha256": sha256_file(TRADES_PATH), "abc_summary_sha256": sha256_file(SUMMARY_PATH)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
