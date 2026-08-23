"""Regular filing registry and correction-chain normalization."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import RegisteredFiling
from .opendart_client import JsonResponse, OpenDartClient
from .opendart_contract import REPORT_TYPE_BY_CODE, FilingRecord


REPORT_NAME_MARKERS = re.compile(r"(?:\[(?:기재정정|첨부정정|첨부추가|정정|자진공시)\]|\((?:기재정정|첨부정정|첨부추가|정정)\))")
REGULAR_REPORT_CODES = frozenset(REPORT_TYPE_BY_CODE)
PAGE_COUNT = 100
MAX_PAGES = 50


class FilingRegistryError(RuntimeError):
    """A filing registry refresh was not a complete, valid OpenDART result."""


class FilingRegistryApiError(FilingRegistryError):
    def __init__(self, message: str, *, status: str | None, classification: str | None,
                 http_status: int | None):
        super().__init__(message)
        self.status = status
        self.classification = classification
        self.http_status = http_status


class IncompleteRegistryError(FilingRegistryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_report_name(value: Any) -> str:
    return re.sub(r"\s+", "", REPORT_NAME_MARKERS.sub("", str(value or ""))).strip()


def _correction_flag(value: Any) -> bool:
    return bool(REPORT_NAME_MARKERS.search(str(value or "")))


def infer_report_code(report_nm: str) -> str | None:
    name = str(report_nm or "")
    if "사업보고서" in name:
        return "11011"
    if "반기보고서" in name:
        return "11012"
    if "분기보고서" in name and ("3분기" in name or ".09" in name or "09" in name):
        return "11014"
    if "분기보고서" in name:
        return "11013"
    return None


def infer_business_year(report_nm: str, rcept_dt: str) -> str:
    match = re.search(r"(20\d{2})\s*[.]\s*(?:03|06|09|12)", str(report_nm or ""))
    if match:
        return match.group(1)
    return str(rcept_dt or "")[:4]


def filing_chain_key(corp_code: str, bsns_year: str, reprt_code: str, report_nm: str) -> str:
    base = _normalise_report_name(report_nm)
    return f"{corp_code}:{bsns_year}:{reprt_code}:{base}"


def to_registered_filing(row: dict[str, Any], *, ticker: str, retrieved_at: str) -> RegisteredFiling | None:
    report_nm = str(row.get("report_nm") or "")
    reprt_code = infer_report_code(report_nm)
    rcept_no = str(row.get("rcept_no") or "")
    rcept_dt = str(row.get("rcept_dt") or "")
    if reprt_code not in REGULAR_REPORT_CODES or not rcept_no or not rcept_dt:
        return None
    corp_code = str(row.get("corp_code") or "")
    year = infer_business_year(report_nm, rcept_dt)
    return RegisteredFiling(
        ticker=ticker,
        corp_code=corp_code,
        corp_name=str(row.get("corp_name") or ""),
        bsns_year=year,
        reprt_code=reprt_code,
        report_type=REPORT_TYPE_BY_CODE[reprt_code],
        report_nm=report_nm,
        rcept_no=rcept_no,
        rcept_dt=rcept_dt,
        filing_chain_key=filing_chain_key(corp_code, year, reprt_code, report_nm),
        correction_flag=_correction_flag(report_nm),
        source_retrieved_at=retrieved_at,
        fs_div=str(row.get("fs_div")) if row.get("fs_div") else None,
    )


def _to_contract(item: RegisteredFiling) -> FilingRecord:
    return FilingRecord(
        ticker=item.ticker,
        corp_code=item.corp_code,
        bsns_year=item.bsns_year,
        reprt_code=item.reprt_code,
        report_nm=item.report_nm,
        rcept_no=item.rcept_no,
        rcept_dt=item.rcept_dt,
        fs_div=item.fs_div,
        filing_chain_key=item.filing_chain_key,
    )


class FilingRegistry:
    def __init__(self, client: OpenDartClient | None = None, *, cache_dir: Path | str = "data/cache/opendart/filings"):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.last_metadata: dict[str, Any] = {}

    def _cache_path(self, corp_code: str, bsns_year: str, reprt_code: str) -> Path:
        return self.cache_dir / f"{corp_code}_{bsns_year}_{reprt_code}.json"

    def _load(self, path: Path) -> tuple[list[RegisteredFiling], dict[str, Any]] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        metadata = dict(payload.get("metadata", {}))
        # A pre-Fix01 or interrupted cache is never a successful registry.
        # Treat it as a miss so a refresh can replace it atomically after a
        # complete response; callers must not consume partial data.
        if metadata.get("cache_complete") is not True or metadata.get("api_status") != "000" \
                or metadata.get("http_status") != 200:
            return None
        try:
            rows = [RegisteredFiling(**item) for item in payload.get("filings", [])]
        except (TypeError, KeyError):
            return None
        metadata["cache_hit"] = True
        return rows, metadata

    @staticmethod
    def _success(response: JsonResponse) -> bool:
        return response.http_status == 200 and response.status == "000"

    @staticmethod
    def _payload_int(payload: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _fetch_pages(self, *, corp_code: str, bgn_de: str, end_de: str,
                     page_count: int = PAGE_COUNT) -> tuple[list[dict[str, Any]], list[JsonResponse], int | None, int | None]:
        """Fetch a deterministic, complete page sequence or fail closed."""
        raw_rows: list[dict[str, Any]] = []
        responses: list[JsonResponse] = []
        page_no = 1
        total_page: int | None = None
        total_count: int | None = None
        while True:
            if page_no > MAX_PAGES:
                raise IncompleteRegistryError(f"MAX_PAGES exceeded while fetching {bgn_de}-{end_de}")
            response = self.client.list_filings(corp_code, bgn_de=bgn_de, end_de=end_de,
                                                 page_no=page_no, page_count=page_count)
            responses.append(response)
            if not self._success(response):
                raise FilingRegistryApiError(
                    f"OpenDART filing registry failed: HTTP {response.http_status}, status {response.status}",
                    status=response.status, classification=response.classification,
                    http_status=response.http_status,
                )
            payload = response.payload if isinstance(response.payload, dict) else {}
            page_rows = payload.get("list") if isinstance(payload.get("list"), list) else []
            raw_rows.extend(item for item in page_rows if isinstance(item, dict))
            observed_total_page = self._payload_int(payload, "total_page", "totalPage")
            observed_total_count = self._payload_int(payload, "total_count", "totalCount")
            if observed_total_page is not None:
                total_page = observed_total_page
            if observed_total_count is not None:
                total_count = observed_total_count
            if total_page is None and total_count is not None:
                total_page = max(1, (total_count + page_count - 1) // page_count)
            if total_page is not None and total_page > MAX_PAGES:
                raise IncompleteRegistryError(f"OpenDART registry total_page={total_page} exceeds MAX_PAGES")
            if total_page is not None:
                if page_no >= total_page:
                    break
            elif len(page_rows) < page_count:
                break
            page_no += 1
        pages_fetched = len(responses)
        if total_page is not None and pages_fetched != total_page:
            raise IncompleteRegistryError(
                f"OpenDART registry pagination incomplete: fetched {pages_fetched}/{total_page} pages"
            )
        if total_count is not None and len(raw_rows) < total_count:
            raise IncompleteRegistryError(
                f"OpenDART registry record count incomplete: fetched {len(raw_rows)}/{total_count} rows"
            )
        return raw_rows, responses, total_count, total_page

    def list_regular_filings(self, *, ticker: str, corp_code: str, bsns_year: str, reprt_code: str,
                             force_refresh: bool = False) -> list[RegisteredFiling]:
        if reprt_code not in REGULAR_REPORT_CODES:
            raise ValueError(f"Unsupported regular report code: {reprt_code}")
        path = self._cache_path(corp_code, str(bsns_year), reprt_code)
        if not force_refresh:
            loaded = self._load(path)
            if loaded is not None:
                rows, self.last_metadata = loaded
                return rows
        if self.client is None:
            raise RuntimeError("OpenDART client is required for filing registry refresh")
        year = int(bsns_year)
        retrieved_at = _now()
        request_windows = [{
            "bgn_de": f"{year:04d}0101",
            "end_de": f"{min(year + 2, date.today().year + 1):04d}1231",
        }]
        raw_rows, responses, total_count, total_page = self._fetch_pages(
            corp_code=corp_code, **request_windows[0])
        targeted_responses: list[JsonResponse] = []
        targeted_total_count: int | None = None
        targeted_total_page: int | None = None
        # Keep the bounded annual recovery window, but subject it to the same
        # status gate and full pagination as every other report type.
        if reprt_code == "11011" and not any(
            isinstance(raw, dict)
            and infer_report_code(str(raw.get("report_nm") or "")) == reprt_code
            and infer_business_year(str(raw.get("report_nm") or ""), str(raw.get("rcept_dt") or "")) == str(bsns_year)
            for raw in raw_rows
        ):
            annual_window = {"bgn_de": f"{year + 1:04d}0301", "end_de": f"{year + 1:04d}0430"}
            request_windows.append(annual_window)
            extra, targeted_responses, targeted_total_count, targeted_total_page = self._fetch_pages(
                corp_code=corp_code, **annual_window
            )
            raw_rows = [*raw_rows, *extra]
        dedupe: dict[str, RegisteredFiling] = {}
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            item = to_registered_filing(raw, ticker=ticker, retrieved_at=retrieved_at)
            if item is not None and item.bsns_year == str(bsns_year) and item.reprt_code == reprt_code:
                dedupe[item.rcept_no] = item
        rows = sorted(dedupe.values(), key=lambda item: (item.rcept_dt, item.rcept_no))
        all_responses = [*responses, *targeted_responses]
        source_hash = hashlib.sha256(b"".join(response.raw for response in all_responses)).hexdigest()
        total_counts = [item for item in (total_count, targeted_total_count) if item is not None]
        total_pages = [item for item in (total_page, targeted_total_page) if item is not None]
        self.last_metadata = {
            "corp_code": corp_code,
            "ticker": ticker,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
            "request_parameters": {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code},
            "request_window": request_windows[0],
            "request_windows": request_windows,
            "retrieved_at": retrieved_at,
            "page_count_requested": PAGE_COUNT,
            "pages_fetched": len(all_responses),
            "total_count": sum(total_counts) if total_counts else len(raw_rows),
            "total_page": sum(total_pages) if total_pages else len(all_responses),
            "http_status": 200,
            "api_status": "000",
            "source_sha256": source_hash,
            "record_count": len(rows),
            "cache_complete": True,
            "targeted_annual_window": bool(targeted_responses),
            "cache_hit": False,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        payload_text = json.dumps({"metadata": self.last_metadata, "filings": [item.to_dict() for item in rows]},
                                  ensure_ascii=False, indent=2) + "\n"
        # Replace only after the complete payload has been serialized.  A
        # failed refresh therefore cannot truncate an existing valid cache.
        temporary_path = path.with_name(f".{path.name}.tmp")
        temporary_path.write_text(payload_text, encoding="utf-8")
        temporary_path.replace(path)
        return rows

    def get_filings(self, ticker: str, bsns_year: str, reprt_code: str, *, corp_code: str | None = None,
                    force_refresh: bool = False) -> list[RegisteredFiling]:
        if corp_code is None:
            raise ValueError("corp_code is required; resolve it through CorpCodeRepository first")
        return self.list_regular_filings(ticker=ticker, corp_code=corp_code, bsns_year=bsns_year,
                                         reprt_code=reprt_code, force_refresh=force_refresh)

    def to_contract_records(self, rows: Iterable[RegisteredFiling]) -> list[FilingRecord]:
        return [_to_contract(item) for item in rows]
