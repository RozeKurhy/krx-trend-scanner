"""Production KRX Open API source for the native 46-sector index cache.

The mapping in this module is intentionally static.  Validation artifacts prove
where it came from, but production code never reads those artifacts at runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota


STANDARD_INDEX_COLUMNS = (
    "date", "index_code", "index_name", "open", "high", "low", "close", "volume", "trading_value",
)
MAPPING_CONTRACT_VERSION = "KRX_NATIVE_SECTOR_INDEX_MAP_V01"
KRX_SECTOR_SOURCE_NAME = "KRX_OPEN_API_SECTOR_INDEX"
KRX_SECTOR_FETCH_MODE = "DAILY_MARKET_SNAPSHOT_KRX_OPEN_API"
KOSPI_SECTOR_API = "kospi_dd_trd"
KOSDAQ_SECTOR_API = "kosdaq_dd_trd"
_OHLC_FIELDS = ("open", "high", "low", "close")
_RAW_FIELDS = {
    "open": "OPNPRC_IDX",
    "high": "HGPRC_IDX",
    "low": "LWPRC_IDX",
    "close": "CLSPRC_IDX",
}


def _immutable_contract(entries: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType({code: MappingProxyType(dict(values)) for code, values in entries.items()})


KRX_NATIVE_SECTOR_INDEX_MAP = _immutable_contract({
    "1005": {"sector_code": "1005", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "음식료·담배"},
    "1006": {"sector_code": "1006", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "섬유·의류"},
    "1007": {"sector_code": "1007", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "종이·목재"},
    "1008": {"sector_code": "1008", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "화학"},
    "1009": {"sector_code": "1009", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "제약"},
    "1010": {"sector_code": "1010", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "비금속"},
    "1011": {"sector_code": "1011", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "금속"},
    "1012": {"sector_code": "1012", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "기계·장비"},
    "1013": {"sector_code": "1013", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "전기전자"},
    "1014": {"sector_code": "1014", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "의료·정밀기기"},
    "1015": {"sector_code": "1015", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "운송장비·부품"},
    "1016": {"sector_code": "1016", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "유통"},
    "1017": {"sector_code": "1017", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "전기·가스"},
    "1018": {"sector_code": "1018", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "건설"},
    "1019": {"sector_code": "1019", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "운송·창고"},
    "1020": {"sector_code": "1020", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "통신"},
    "1021": {"sector_code": "1021", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "금융"},
    "1024": {"sector_code": "1024", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "증권"},
    "1025": {"sector_code": "1025", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "보험"},
    "1026": {"sector_code": "1026", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "일반서비스"},
    "1027": {"sector_code": "1027", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "제조"},
    "1045": {"sector_code": "1045", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "부동산"},
    "1046": {"sector_code": "1046", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "IT 서비스"},
    "1047": {"sector_code": "1047", "market": "KOSPI", "source_api": "kospi_dd_trd", "idx_class": "KOSPI", "idx_name": "오락·문화"},
    "2012": {"sector_code": "2012", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "일반서비스"},
    "2024": {"sector_code": "2024", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "제조"},
    "2026": {"sector_code": "2026", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "건설"},
    "2027": {"sector_code": "2027", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "유통"},
    "2029": {"sector_code": "2029", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "운송·창고"},
    "2031": {"sector_code": "2031", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "금융"},
    "2037": {"sector_code": "2037", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "오락·문화"},
    "2056": {"sector_code": "2056", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "음식료·담배"},
    "2058": {"sector_code": "2058", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "섬유·의류"},
    "2062": {"sector_code": "2062", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "종이·목재"},
    "2063": {"sector_code": "2063", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "출판·매체복제"},
    "2065": {"sector_code": "2065", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "화학"},
    "2066": {"sector_code": "2066", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "제약"},
    "2067": {"sector_code": "2067", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "비금속"},
    "2068": {"sector_code": "2068", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "금속"},
    "2070": {"sector_code": "2070", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "기계·장비"},
    "2072": {"sector_code": "2072", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "전기전자"},
    "2074": {"sector_code": "2074", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "의료·정밀기기"},
    "2075": {"sector_code": "2075", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "운송장비·부품"},
    "2077": {"sector_code": "2077", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "기타제조"},
    "2114": {"sector_code": "2114", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "통신"},
    "2118": {"sector_code": "2118", "market": "KOSDAQ", "source_api": "kosdaq_dd_trd", "idx_class": "KOSDAQ", "idx_name": "IT 서비스"},
})

KOSPI_SECTOR_CODES = tuple(code for code, item in KRX_NATIVE_SECTOR_INDEX_MAP.items() if item["market"] == "KOSPI")
KOSDAQ_SECTOR_CODES = tuple(code for code, item in KRX_NATIVE_SECTOR_INDEX_MAP.items() if item["market"] == "KOSDAQ")


class SnapshotClient(Protocol):
    request_count: int
    retry_count: int
    audit: list[dict[str, Any]]
    status_counts: dict[str, int]

    def fetch(self, endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None) -> Any:
        ...


@dataclass(frozen=True)
class SectorCacheBuildResult:
    dataframe: pd.DataFrame
    trading_dates: tuple[str, ...]
    request_dates: tuple[str, ...]
    report: dict[str, Any]


def mapping_contract_as_dict() -> dict[str, dict[str, str]]:
    return {code: dict(values) for code, values in KRX_NATIVE_SECTOR_INDEX_MAP.items()}


def mapping_contract_sha256() -> str:
    payload = json.dumps(mapping_contract_as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_number(value: Any, *, field: str, code: str, date_text: str, positive: bool = True) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MarketDataError(f"missing numeric field: {field} ({code}, {date_text})")
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"invalid numeric field: {field} ({code}, {date_text})") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise MarketDataError(f"non-positive numeric field: {field} ({code}, {date_text})")
    return number


def _parse_nonnegative(value: Any, *, field: str, code: str, date_text: str, integer: bool = False) -> float | int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0 if integer else 0.0
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"invalid ancillary field: {field} ({code}, {date_text})") from exc
    if not math.isfinite(number) or number < 0:
        raise MarketDataError(f"invalid ancillary field: {field} ({code}, {date_text})")
    return int(number) if integer else number


def _format_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    parsed = pd.Timestamp(text)
    return parsed.strftime("%Y-%m-%d")


def _request_dates(start_date: str, end_date: str) -> tuple[str, ...]:
    start = _format_date(start_date)
    end = _format_date(end_date)
    if start > end:
        raise ValueError("start_date must not be after end_date")
    return tuple(item.strftime("%Y-%m-%d") for item in pd.date_range(start, end, freq="B"))


class KrxSectorIndexCacheBuilder:
    """Build and incrementally update the normalized native sector cache."""

    def __init__(
        self,
        *,
        client: SnapshotClient | None = None,
        auth_key: str | None = None,
        quota: LocalKrxOpenApiQuota | None = None,
        max_requests: int = 800,
        throttle_seconds: float = 0.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._quota = quota
        self._throttle_seconds = max(0.0, float(throttle_seconds))
        self._sleeper = sleeper
        if client is not None:
            self.client = client
        else:
            key = (auth_key or os.getenv("KRX_OPEN_API_AUTH_KEY", "")).strip()
            if not key:
                raise ValueError("KRX_OPEN_API_AUTH_KEY is required for sector cache build")
            self.client = KrxOpenApiClient(
                key,
                max_requests=max_requests,
                max_transient_retries=2,
                quota=quota or LocalKrxOpenApiQuota(),
            )

    @staticmethod
    def _records(response: Any) -> list[Mapping[str, Any]]:
        return [row for row in getattr(response, "records", ()) if isinstance(row, Mapping)]

    def _fetch_api(self, api_id: str, date_text: str) -> tuple[list[Mapping[str, Any]], bool]:
        if self._throttle_seconds:
            self._sleeper(self._throttle_seconds)
        response = self.client.fetch(f"/idx/{api_id}", date_text, quota_endpoint_key=api_id)
        status = getattr(response, "http_status", 200)
        if status != 200:
            raise MarketDataError(f"KRX sector endpoint failed: {api_id} {date_text} HTTP_{status}")
        rows = self._records(response)
        return rows, not rows

    @staticmethod
    def _normalize_snapshot(rows: Iterable[Mapping[str, Any]], *, date_text: str, api_id: str) -> list[dict[str, Any]]:
        expected = [item for item in KRX_NATIVE_SECTOR_INDEX_MAP.values() if item["source_api"] == api_id]
        normalized: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for contract in expected:
            matches = [row for row in rows if str(row.get("IDX_CLSS", "")).strip() == contract["idx_class"] and str(row.get("IDX_NM", "")).strip() == contract["idx_name"]]
            if len(matches) == 0:
                raise MarketDataError(f"expected sector row missing: {api_id} {date_text} {contract['sector_code']} {contract['idx_name']}")
            if len(matches) > 1:
                raise MarketDataError(f"duplicate sector row: {api_id} {date_text} {contract['sector_code']}")
            row = matches[0]
            bas_dd = str(row.get("BAS_DD", "")).replace("-", "").replace("/", "")
            if bas_dd != date_text.replace("-", ""):
                raise MarketDataError(f"wrong BAS_DD: requested={date_text} actual={bas_dd} code={contract['sector_code']}")
            values = {field: _parse_number(row.get(raw_field), field=field, code=contract["sector_code"], date_text=date_text) for field, raw_field in _RAW_FIELDS.items()}
            normalized.append({
                "date": date_text,
                "index_code": contract["sector_code"],
                "index_name": contract["idx_name"],
                **values,
                "volume": _parse_nonnegative(row.get("ACC_TRDVOL"), field="volume", code=contract["sector_code"], date_text=date_text, integer=True),
                "trading_value": _parse_nonnegative(row.get("ACC_TRDVAL"), field="trading_value", code=contract["sector_code"], date_text=date_text),
            })
            seen_codes.add(contract["sector_code"])
        if len(seen_codes) != len(expected):
            raise MarketDataError(f"sector coverage mismatch: {api_id} {date_text}")
        return normalized

    def _collect(self, request_dates: Iterable[str]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        request_dates_tuple = tuple(request_dates)
        rows: list[dict[str, Any]] = []
        trading_dates: list[str] = []
        non_trading_dates: list[str] = []
        for date_text in request_dates_tuple:
            kospi_rows, kospi_empty = self._fetch_api(KOSPI_SECTOR_API, date_text)
            kosdaq_rows, kosdaq_empty = self._fetch_api(KOSDAQ_SECTOR_API, date_text)
            if kospi_empty and kosdaq_empty:
                non_trading_dates.append(date_text)
                continue
            if kospi_empty != kosdaq_empty:
                raise MarketDataError(f"partial API snapshot for date {date_text}")
            date_rows = self._normalize_snapshot(kospi_rows, date_text=date_text, api_id=KOSPI_SECTOR_API)
            date_rows.extend(self._normalize_snapshot(kosdaq_rows, date_text=date_text, api_id=KOSDAQ_SECTOR_API))
            if len(date_rows) != len(KRX_NATIVE_SECTOR_INDEX_MAP):
                raise MarketDataError(f"expected 46 sector rows, got {len(date_rows)} ({date_text})")
            rows.extend(date_rows)
            trading_dates.append(date_text)
        report = {
            "request_date_count": len(request_dates_tuple),
            "trading_date_count": len(trading_dates),
            "non_trading_date_count": len(non_trading_dates),
            "non_trading_dates": non_trading_dates,
            "cache_missing_sector_count": 0,
            "cache_duplicate_count": 0,
            "cache_invalid_numeric_count": 0,
            "cache_wrong_date_count": 0,
        }
        return rows, trading_dates, report

    @staticmethod
    def _validate_dataframe(df: pd.DataFrame, *, minimum_sessions: int = 1) -> tuple[pd.DataFrame, dict[str, int]]:
        if list(df.columns) != list(STANDARD_INDEX_COLUMNS):
            raise MarketDataError("sector cache schema mismatch")
        result = df.copy()
        result["date"] = result["date"].astype(str)
        result["index_code"] = result["index_code"].astype(str)
        expected_codes = set(KRX_NATIVE_SECTOR_INDEX_MAP)
        if set(result["index_code"]) - expected_codes:
            raise MarketDataError("unknown sector code in cache")
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        for field in _OHLC_FIELDS:
            result[field] = pd.to_numeric(result[field], errors="coerce")
        result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
        result["trading_value"] = pd.to_numeric(result["trading_value"], errors="coerce")
        missing = int(result[list(_OHLC_FIELDS)].isna().any(axis=1).sum())
        finite = result[list(_OHLC_FIELDS)].apply(lambda column: column.map(math.isfinite))
        invalid = int(((result[list(_OHLC_FIELDS)] <= 0) | ~finite).any(axis=1).sum())
        duplicate = int(result.duplicated(subset=["date", "index_code"]).sum())
        if result["date"].isna().any() or missing or invalid or duplicate:
            raise MarketDataError(f"invalid sector cache rows: missing={missing} invalid={invalid} duplicate={duplicate}")
        counts = result.groupby("date")["index_code"].nunique()
        missing_sector = int(sum(max(0, len(expected_codes) - int(value)) for value in counts))
        if missing_sector or (len(counts) < minimum_sessions and len(result) > 0):
            raise MarketDataError(f"sector cache coverage insufficient: dates={len(counts)} missing={missing_sector}")
        for date_text, group in result.groupby("date"):
            if len(group) != len(expected_codes):
                raise MarketDataError(f"sector cache date coverage is not 46: {date_text}")
        result["index_name"] = result["index_code"].map(lambda code: KRX_NATIVE_SECTOR_INDEX_MAP[code]["idx_name"])
        result = result.sort_values(["index_code", "date"]).reset_index(drop=True)
        result["volume"] = result["volume"].astype("int64")
        result["trading_value"] = result["trading_value"].astype("float64")
        return result, {"cache_missing_sector_count": missing_sector, "cache_duplicate_count": duplicate, "cache_invalid_numeric_count": invalid}

    @staticmethod
    def _atomic_write(df: pd.DataFrame, output_parquet: Path, output_meta: Path, metadata: Mapping[str, Any]) -> None:
        output_parquet.parent.mkdir(parents=True, exist_ok=True)
        output_meta.parent.mkdir(parents=True, exist_ok=True)
        parquet_tmp = Path(tempfile.mkstemp(prefix=f".{output_parquet.name}.", suffix=".tmp", dir=output_parquet.parent)[1])
        meta_tmp = Path(tempfile.mkstemp(prefix=f".{output_meta.name}.", suffix=".tmp", dir=output_meta.parent)[1])
        try:
            df.to_parquet(parquet_tmp, index=False)
            parquet_sha = hashlib.sha256(parquet_tmp.read_bytes()).hexdigest()
            meta_payload = dict(metadata)
            meta_payload["parquet_sha256"] = parquet_sha
            meta_tmp.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(parquet_tmp, output_parquet)
            os.replace(meta_tmp, output_meta)
        finally:
            parquet_tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)

    def _metadata(self, df: pd.DataFrame, *, requested_as_of: str, report: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_name": KRX_SECTOR_SOURCE_NAME,
            "requested_as_of": requested_as_of,
            "date_min": str(df["date"].min()) if not df.empty else "",
            "date_max": str(df["date"].max()) if not df.empty else "",
            "index_codes": sorted(KRX_NATIVE_SECTOR_INDEX_MAP),
            "index_count": len(KRX_NATIVE_SECTOR_INDEX_MAP),
            "row_count": int(len(df)),
            "source_apis": [KOSPI_SECTOR_API, KOSDAQ_SECTOR_API],
            "mapping_contract_version": MAPPING_CONTRACT_VERSION,
            "mapping_contract_sha256": mapping_contract_sha256(),
            "fetch_mode": KRX_SECTOR_FETCH_MODE,
            "generation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "trading_date_count": int(df["date"].nunique()) if not df.empty else 0,
            "build_report": dict(report),
        }

    def build(
        self,
        *,
        start_date: str,
        end_date: str,
        output_parquet: Path,
        output_meta: Path,
        minimum_sessions: int = 270,
    ) -> SectorCacheBuildResult:
        request_dates = _request_dates(start_date, end_date)
        rows, trading_dates, report = self._collect(request_dates)
        if len(trading_dates) < minimum_sessions:
            raise MarketDataError(f"sector cache requires at least {minimum_sessions} sessions, got {len(trading_dates)}")
        df, validation = self._validate_dataframe(pd.DataFrame(rows, columns=list(STANDARD_INDEX_COLUMNS)), minimum_sessions=minimum_sessions)
        report = {**report, **validation, "cache_sector_code_count": int(df["index_code"].nunique()), "cache_row_count": int(len(df))}
        self._atomic_write(df, output_parquet, output_meta, self._metadata(df, requested_as_of=_format_date(end_date), report=report))
        return SectorCacheBuildResult(df, tuple(trading_dates), request_dates, {**report, "request_count": int(getattr(self.client, "request_count", 0))})

    def update(
        self,
        *,
        target_date: str,
        output_parquet: Path,
        output_meta: Path,
        minimum_sessions: int = 1,
    ) -> SectorCacheBuildResult:
        target = _format_date(target_date)
        rows, trading_dates, report = self._collect((target,))
        if not rows:
            existing = pd.read_parquet(output_parquet) if output_parquet.exists() else pd.DataFrame(columns=list(STANDARD_INDEX_COLUMNS))
            return SectorCacheBuildResult(existing, tuple(), (target,), {**report, "idempotent_noop": True, "request_count": int(getattr(self.client, "request_count", 0))})
        new_rows = pd.DataFrame(rows, columns=list(STANDARD_INDEX_COLUMNS))
        existing = pd.read_parquet(output_parquet) if output_parquet.exists() else pd.DataFrame(columns=list(STANDARD_INDEX_COLUMNS))
        if not existing.empty:
            existing = existing[existing["date"].astype(str) != target].copy()
        combined, validation = self._validate_dataframe(pd.concat([existing, new_rows], ignore_index=True), minimum_sessions=minimum_sessions)
        report = {**report, **validation, "cache_sector_code_count": int(combined["index_code"].nunique()), "cache_row_count": int(len(combined)), "idempotent_noop": False}
        self._atomic_write(combined, output_parquet, output_meta, self._metadata(combined, requested_as_of=target, report=report))
        return SectorCacheBuildResult(combined, tuple(trading_dates), (target,), {**report, "request_count": int(getattr(self.client, "request_count", 0))})
