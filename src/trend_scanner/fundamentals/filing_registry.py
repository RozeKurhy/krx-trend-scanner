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
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = [RegisteredFiling(**item) for item in payload.get("filings", [])]
        metadata = dict(payload.get("metadata", {})); metadata["cache_hit"] = True
        return rows, metadata

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
        response: JsonResponse = self.client.list_filings(
            corp_code,
            bgn_de=f"{year:04d}0101",
            end_de=f"{min(year + 2, date.today().year + 1):04d}1231",
            page_no=1,
            page_count=100,
        )
        retrieved_at = _now()
        raw_rows = response.payload.get("list") if isinstance(response.payload.get("list"), list) else []
        # Samsung and other high-volume issuers can push the annual filing
        # past the first bounded page.  A narrow annual window is deterministic
        # and avoids an unbounded disclosure crawl.
        targeted_response: JsonResponse | None = None
        if reprt_code == "11011" and not any(
            isinstance(raw, dict)
            and infer_report_code(str(raw.get("report_nm") or "")) == reprt_code
            and infer_business_year(str(raw.get("report_nm") or ""), str(raw.get("rcept_dt") or "")) == str(bsns_year)
            for raw in raw_rows
        ):
            targeted_response = self.client.list_filings(
                corp_code,
                bgn_de=f"{year + 1:04d}0301",
                end_de=f"{year + 1:04d}0430",
                page_no=1,
                page_count=100,
            )
            extra = targeted_response.payload.get("list") if isinstance(targeted_response.payload.get("list"), list) else []
            raw_rows = [*raw_rows, *extra]
        dedupe: dict[str, RegisteredFiling] = {}
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            item = to_registered_filing(raw, ticker=ticker, retrieved_at=retrieved_at)
            if item is not None and item.bsns_year == str(bsns_year) and item.reprt_code == reprt_code:
                dedupe[item.rcept_no] = item
        rows = sorted(dedupe.values(), key=lambda item: (item.rcept_dt, item.rcept_no))
        source_hash = hashlib.sha256(response.raw + (targeted_response.raw if targeted_response else b"")).hexdigest()
        self.last_metadata = {
            "request_parameters": {"corp_code": corp_code, "bsns_year": str(bsns_year), "reprt_code": reprt_code},
            "retrieved_at": retrieved_at,
            "http_status": response.http_status,
            "api_status": response.status,
            "source_sha256": source_hash,
            "record_count": len(rows),
            "targeted_annual_window": bool(targeted_response),
            "cache_hit": False,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"metadata": self.last_metadata, "filings": [item.to_dict() for item in rows]},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return rows

    def get_filings(self, ticker: str, bsns_year: str, reprt_code: str, *, corp_code: str | None = None,
                    force_refresh: bool = False) -> list[RegisteredFiling]:
        if corp_code is None:
            raise ValueError("corp_code is required; resolve it through CorpCodeRepository first")
        return self.list_regular_filings(ticker=ticker, corp_code=corp_code, bsns_year=bsns_year,
                                         reprt_code=reprt_code, force_refresh=force_refresh)

    def to_contract_records(self, rows: Iterable[RegisteredFiling]) -> list[FilingRecord]:
        return [_to_contract(item) for item in rows]
