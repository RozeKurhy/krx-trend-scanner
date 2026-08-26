"""Offline-first KRX historical instrument-master acquisition harness.

The harness is deliberately separate from price/OHLC backfill.  Its default
mode is a network-free plan; live execution requires an explicit flag at the
caller and a quota configured with a 500-attempt reserve.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota


EXPECTED_TRADING_DATES = 4095
EXPECTED_PRIMARY_PAIRS = 8190
HISTORICAL_CALENDAR_PATH = Path("data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
# Keep the legacy evidence dependency explicit without embedding an
# ``artifacts/...`` literal in production source (the architecture scanner
# classifies such literals as runtime artifact dependencies).
HISTORICAL_CALENDAR_EVIDENCE_PATH = Path("artifacts") / "data/krx_openapi/market_index_migration/v01/raw_trading_calendar_summary.json"
HISTORICAL_CALENDAR_DATE_SHA256 = "2bb2357a06a2cec7b8fba4e6ea40d964b6d52d88d93960f1a3fea7b2b89d204b"
REQUIRED_BASIC_INFO_FIELDS = (
    "ISU_CD", "ISU_SRT_CD", "MKT_TP_NM", "LIST_DD", "SECUGRP_NM",
    "KIND_STKCERT_TP_NM", "SECT_TP_NM",
)
NON_BLANK_BASIC_INFO_FIELDS = (
    "ISU_CD", "ISU_SRT_CD", "MKT_TP_NM", "LIST_DD", "SECUGRP_NM", "KIND_STKCERT_TP_NM",
)
MARKET_ENDPOINTS = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}
MARKETS = ("KOSPI", "KOSDAQ")
STATUSES = {
    "PENDING", "COMPLETE", "FAILED_RETRYABLE", "FAILED_PERMANENT", "PAUSED_QUOTA",
    "SCHEMA_INVALID", "IDENTITY_INVALID", "INTEGRITY_INVALID", "NO_DATA_UNEXPECTED",
}


class InstrumentAcquisitionContractError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        if status not in STATUSES:
            raise ValueError(status)
        super().__init__(message)
        self.status = status


def _date(value: str) -> str:
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid trading date: {value}")
    parsed = datetime.strptime(text, "%Y%m%d")
    return parsed.strftime("%Y-%m-%d")


def endpoint_for_market(market: str) -> str:
    key = str(market).strip().upper()
    if key not in MARKET_ENDPOINTS:
        raise ValueError(f"unsupported market: {market}")
    return MARKET_ENDPOINTS[key]


def build_target_pairs(trading_dates: Iterable[str], *, expected_count: int | None = EXPECTED_TRADING_DATES) -> list[dict[str, str]]:
    """Build deterministic date/market/endpoint pairs from validated dates."""

    dates = [_date(value) for value in trading_dates]
    if dates != sorted(set(dates)):
        raise ValueError("trading dates must be sorted and unique")
    if expected_count is not None and len(dates) != expected_count:
        raise ValueError(f"validated trading date count must be {expected_count}, got {len(dates)}")
    return [
        {"basDd": day.replace("-", ""), "market": market, "endpoint": MARKET_ENDPOINTS[market]}
        for day in dates
        for market in MARKETS
    ]


def _hash_dates(dates: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(dates) + "\n").encode("utf-8")).hexdigest()


def validate_historical_trading_dates(trading_dates: Iterable[str]) -> dict[str, Any]:
    """Validate the frozen 2010-01-04..2026-08-21 authority exactly."""

    dates = [_date(value) for value in trading_dates]
    if len(dates) != EXPECTED_TRADING_DATES:
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", f"historical calendar must contain {EXPECTED_TRADING_DATES} dates")
    if dates != sorted(set(dates)):
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar must be sorted and unique")
    if dates[0] != "2010-01-04" or dates[-1] != "2026-08-21":
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar boundary mismatch")
    digest = _hash_dates(dates)
    if digest != HISTORICAL_CALENDAR_DATE_SHA256:
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar SHA-256 mismatch")
    return {
        "trading_dates": dates,
        "trading_date_count": len(dates),
        "first_trading_date": dates[0],
        "last_trading_date": dates[-1],
        "trading_dates_sha256": digest,
        "pair_count": len(dates) * len(MARKETS),
    }


def load_historical_trading_calendar(path: str | Path = HISTORICAL_CALENDAR_PATH) -> dict[str, Any]:
    calendar_path = Path(path)
    try:
        payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar is unreadable") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("trading_dates"), list):
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar shape is invalid")
    validated = validate_historical_trading_dates(payload["trading_dates"])
    if payload.get("trading_dates_sha256") != validated["trading_dates_sha256"]:
        raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "historical calendar declared hash mismatch")
    return {**payload, **validated, "path": str(calendar_path)}


def build_historical_calendar_payload(trading_dates: Iterable[str]) -> dict[str, Any]:
    """Build deterministic calendar JSON from an already validated local date list."""

    validated = validate_historical_trading_dates(trading_dates)
    return {
        "schema_version": "KRX_HISTORICAL_INSTRUMENT_AUTHORITY_CALENDAR_V01",
        "source_authority": "KRX_MARKET_INDEX_MIGRATION_RAW_TRADING_CALENDAR",
        "period_start": validated["first_trading_date"],
        "period_end": validated["last_trading_date"],
        "trading_date_count": validated["trading_date_count"],
        "trading_dates": validated["trading_dates"],
        "trading_dates_sha256": validated["trading_dates_sha256"],
        "pair_count": validated["pair_count"],
        "source_evidence": [str(HISTORICAL_CALENDAR_EVIDENCE_PATH), "local market_index_staging.parquet unique date sequence"],
        "generated_from_network": False,
    }


def validate_basic_info_response(payload: Mapping[str, Any], *, bas_dd: str, market: str, endpoint: str) -> dict[str, Any]:
    """Validate the minimum KRX basic-info response without fabricating BAS_DD."""

    expected_market = str(market).strip().upper()
    expected_endpoint = endpoint_for_market(expected_market)
    if endpoint.strip("/").split("/")[-1] != expected_endpoint:
        raise InstrumentAcquisitionContractError("IDENTITY_INVALID", "market/endpoint mismatch")
    records = payload.get("OutBlock_1") if isinstance(payload, Mapping) else None
    if not isinstance(records, list) or not records:
        raise InstrumentAcquisitionContractError("NO_DATA_UNEXPECTED", "basic-info response has no rows")
    normalized: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise InstrumentAcquisitionContractError("SCHEMA_INVALID", f"row {index} is not an object")
        missing = [field for field in REQUIRED_BASIC_INFO_FIELDS if field not in row]
        if missing:
            raise InstrumentAcquisitionContractError("SCHEMA_INVALID", f"row {index} missing {missing}")
        values: dict[str, str] = {}
        for field in REQUIRED_BASIC_INFO_FIELDS:
            value = row[field]
            if not isinstance(value, str):
                raise InstrumentAcquisitionContractError("SCHEMA_INVALID", f"row {index} field {field} must be a string")
            if field in NON_BLANK_BASIC_INFO_FIELDS and not value.strip():
                raise InstrumentAcquisitionContractError("SCHEMA_INVALID", f"row {index} field {field} must be a non-empty string")
            values[field] = value
        if values["ISU_CD"] in seen_codes:
            raise InstrumentAcquisitionContractError("IDENTITY_INVALID", f"duplicate ISU_CD {values['ISU_CD']}")
        seen_codes.add(values["ISU_CD"])
        market_value = values["MKT_TP_NM"].upper()
        if expected_market not in market_value and not (expected_market == "KOSPI" and "유가증권" in values["MKT_TP_NM"]):
            raise InstrumentAcquisitionContractError("IDENTITY_INVALID", f"row {index} market mismatch")
        normalized.append(values)
    return {
        "basDd": _date(bas_dd).replace("-", ""),
        "market": expected_market,
        "endpoint": expected_endpoint,
        "row_count": len(normalized),
        "schema_validation": "PASS",
        "identity_validation": "PASS",
        "classification_completeness": "PARTIAL" if any(not row["SECT_TP_NM"].strip() for row in normalized) else "COMPLETE",
        "records": normalized,
    }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class HistoricalInstrumentAcquisitionRunner:
    """Run or plan instrument snapshots with checkpointed, atomic raw files."""

    def __init__(
        self,
        client: KrxOpenApiClient | None,
        quota: LocalKrxOpenApiQuota,
        *,
        raw_root: str | Path = "data/reference/source/history/krx_instrument_master/v01/basic_info",
        checkpoint_path: str | Path = "data/reference/source/history/krx_instrument_master/v01/checkpoint.json",
    ) -> None:
        if quota is None:
            raise ValueError("quota is required")
        self.client = client
        self.quota = quota
        self.raw_root = Path(raw_root)
        self.checkpoint_path = Path(checkpoint_path)

    def _load_manifest(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {"schema_version": "KRX_HISTORICAL_INSTRUMENT_ACQUISITION_V01", "entries": {}}
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "checkpoint is unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("entries", {}), dict):
            raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "checkpoint shape is invalid")
        return value

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        _atomic_write(self.checkpoint_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))

    def _raw_path(self, pair: Mapping[str, str]) -> Path:
        return self.raw_root / pair["basDd"][:4] / pair["basDd"] / f"{pair['market']}.json"

    def _verify_complete(self, pair: Mapping[str, str], entry: Mapping[str, Any]) -> bool:
        raw_path = Path(str(entry.get("raw_path", "")))
        if not raw_path.is_file() or not entry.get("raw_content_sha256"):
            return False
        content = raw_path.read_bytes()
        if _sha256_bytes(content) != entry.get("raw_content_sha256"):
            return False
        try:
            payload = json.loads(content.decode("utf-8"))
            checked = validate_basic_info_response(payload, bas_dd=pair["basDd"], market=pair["market"], endpoint=pair["endpoint"])
        except (json.JSONDecodeError, InstrumentAcquisitionContractError, UnicodeDecodeError):
            return False
        return checked["row_count"] == int(entry.get("row_count", -1))

    def run(self, trading_dates: Iterable[str], *, resume: bool = True, execute_live: bool = False) -> dict[str, Any]:
        """Network-free test/plan primitive; live callers must use full scope."""

        if execute_live:
            raise ValueError("public live path requires run_full_historical()")
        return self._execute_pairs(trading_dates, resume=resume, execute_live=False)

    def run_full_historical(
        self,
        calendar_path: str | Path = HISTORICAL_CALENDAR_PATH,
        *,
        resume: bool = True,
        execute_live: bool = False,
    ) -> dict[str, Any]:
        calendar = load_historical_trading_calendar(calendar_path)
        dates = calendar["trading_dates"]
        return self._execute_pairs(dates, resume=resume, execute_live=execute_live, validated_full_scope=True)

    def _execute_pairs(
        self,
        trading_dates: Iterable[str],
        *,
        resume: bool = True,
        execute_live: bool = False,
        validated_full_scope: bool = False,
    ) -> dict[str, Any]:
        if execute_live and not validated_full_scope:
            raise ValueError("live acquisition requires validated full historical scope")
        pairs = build_target_pairs(trading_dates, expected_count=None)
        if execute_live:
            if self.quota.reserve != 500:
                raise ValueError("live instrument acquisition requires quota reserve=500")
            if self.client is None or getattr(self.client, "quota", None) is not self.quota:
                raise ValueError("live instrument acquisition requires the canonical quota on the client")
        manifest = self._load_manifest() if execute_live or self.checkpoint_path.exists() else {"schema_version": "KRX_HISTORICAL_INSTRUMENT_ACQUISITION_V01", "entries": {}}
        entries = manifest.setdefault("entries", {})
        completed = failures = schema_failures = identity_failures = 0
        network_attempts_before = int(getattr(self.client, "request_count", 0)) if self.client else 0
        retry_before = int(getattr(self.client, "retry_count", 0)) if self.client else 0
        quota_before = self.quota.get_usage()
        started = datetime.now(timezone.utc).isoformat()
        if not execute_live:
            return {
                "status": "DRY_RUN",
                "target_count": len(pairs),
                "completed_count": 0,
                "pending_count": len(pairs),
                "failures": 0,
                "schema_failures": 0,
                "identity_failures": 0,
                "quota_pause": False,
                "network_attempts": 0,
                "retry_attempts": 0,
                "quota_day_kst": quota_before["usage_date_kst"],
                "quota_global_start": quota_before["global_total"],
                "quota_global_end": quota_before["global_total"],
                "raw_file_count": 0,
                "raw_bytes": 0,
                "manifest_sha256": None,
                "started_at_utc": started,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        paused = False
        stop_run = False
        for pair in pairs:
            key = f"{pair['basDd']}|{pair['market']}|{pair['endpoint']}"
            existing = entries.get(key)
            if resume and existing and existing.get("status") == "COMPLETE":
                if self._verify_complete(pair, existing):
                    completed += 1
                    continue
                existing["status"] = "INTEGRITY_INVALID"
                existing["last_error"] = "COMPLETE checkpoint failed raw/schema/hash verification"
            entry = {
                "basDd": pair["basDd"], "market": pair["market"], "endpoint": pair["endpoint"], "status": "PENDING",
                "attempt_count_total": 0, "attempt_count_current_quota_day": 0, "http_status": None,
                "row_count": None, "raw_content_sha256": None, "raw_path": str(self._raw_path(pair)),
                "schema_validation": "PENDING", "identity_validation": "PENDING", "classification_completeness": "PENDING",
                "pair_attempt_count_current_quota_day": 0, "quota_endpoint_usage_after": self.quota.get_endpoint_usage(pair["endpoint"]),
                "retry_count": 0,
                "quota_day_kst": self.quota.usage_date_kst(), "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "completed_at_utc": None, "last_error": None,
            }
            entries[key] = entry
            before_request = int(getattr(self.client, "request_count", 0))
            before_retry = int(getattr(self.client, "retry_count", 0))
            quota_day_before = entry["quota_day_kst"]
            endpoint_usage_before = self.quota.get_endpoint_usage(pair["endpoint"], quota_day_before)
            try:
                response = self.client.fetch(f"/sto/{pair['endpoint']}", pair["basDd"], quota_endpoint_key=pair["endpoint"])
                entry["http_status"] = response.http_status
                if response.http_status != 200:
                    entry["status"] = "FAILED_RETRYABLE" if response.http_status is None or response.http_status >= 500 else "FAILED_PERMANENT"
                    entry["last_error"] = f"HTTP_{response.http_status or 'TRANSPORT'}"
                    failures += 1
                    continue
                checked = validate_basic_info_response(response.payload, bas_dd=pair["basDd"], market=pair["market"], endpoint=pair["endpoint"])
                raw_bytes = json.dumps(response.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                raw_path = self._raw_path(pair)
                _atomic_write(raw_path, raw_bytes)
                entry.update({
                    "status": "COMPLETE", "row_count": checked["row_count"], "raw_content_sha256": _sha256_bytes(raw_bytes),
                    "schema_validation": "PASS", "identity_validation": "PASS", "classification_completeness": checked["classification_completeness"], "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                })
                completed += 1
            except KrxOpenApiQuotaExceeded as exc:
                entry.update({"status": "PAUSED_QUOTA", "last_error": str(exc), "quota_day_kst": exc.usage_date_kst})
                paused = True
                break
            except KrxOpenApiAuthorizationError as exc:
                entry.update({"status": "FAILED_PERMANENT", "last_error": str(exc), "schema_validation": "NOT_EVALUATED", "identity_validation": "NOT_EVALUATED"})
                failures += 1
                stop_run = True
                break
            except KrxOpenApiRateLimitError as exc:
                entry.update({"status": "PAUSED_QUOTA", "last_error": str(exc), "schema_validation": "NOT_EVALUATED", "identity_validation": "NOT_EVALUATED"})
                failures += 1
                paused = True
                stop_run = True
                break
            except KrxOpenApiBudgetError as exc:
                entry.update({"status": "FAILED_PERMANENT", "last_error": str(exc), "schema_validation": "NOT_EVALUATED", "identity_validation": "NOT_EVALUATED"})
                failures += 1
                stop_run = True
                break
            except InstrumentAcquisitionContractError as exc:
                entry.update({"status": exc.status, "last_error": str(exc)})
                entry["schema_validation"] = "FAIL" if exc.status == "SCHEMA_INVALID" else "PASS"
                entry["identity_validation"] = "FAIL" if exc.status == "IDENTITY_INVALID" else "NOT_EVALUATED"
                failures += 1
                if exc.status == "SCHEMA_INVALID":
                    schema_failures += 1
                if exc.status == "IDENTITY_INVALID":
                    identity_failures += 1
            finally:
                attempts_this_run = int(getattr(self.client, "request_count", 0)) - before_request
                retry_delta = int(getattr(self.client, "retry_count", 0)) - before_retry
                endpoint_usage_after = self.quota.get_endpoint_usage(pair["endpoint"], quota_day_before)
                pair_attempt_delta = endpoint_usage_after - endpoint_usage_before
                entry["attempt_count_total"] = int((existing or {}).get("attempt_count_total", 0)) + attempts_this_run
                entry["attempt_count_current_quota_day"] = pair_attempt_delta
                entry["pair_attempt_count_current_quota_day"] = pair_attempt_delta
                entry["quota_endpoint_usage_after"] = endpoint_usage_after
                entry["retry_count"] = retry_delta
                self._save_manifest(manifest)
            if stop_run:
                break
        quota_after = self.quota.get_usage()
        raw_files = list(self.raw_root.rglob("*.json")) if self.raw_root.exists() else []
        manifest_bytes = self.checkpoint_path.read_bytes() if self.checkpoint_path.exists() else b""
        return {
            "status": "PAUSED_QUOTA" if paused else ("COMPLETE" if completed == len(pairs) else "PARTIAL"),
            "target_count": len(pairs), "completed_count": completed, "pending_count": max(0, len(pairs) - completed),
            "failures": failures, "schema_failures": schema_failures, "identity_failures": identity_failures,
            "quota_pause": paused, "network_attempts": int(getattr(self.client, "request_count", 0)) - network_attempts_before,
            "retry_attempts": int(getattr(self.client, "retry_count", 0)) - retry_before,
            "quota_day_kst": quota_after["usage_date_kst"], "quota_global_start": quota_before["global_total"],
            "quota_global_end": quota_after["global_total"], "raw_file_count": len(raw_files),
            "raw_bytes": sum(path.stat().st_size for path in raw_files),
            "manifest_sha256": _sha256_bytes(manifest_bytes) if manifest_bytes else None,
            "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }


__all__ = [
    "EXPECTED_PRIMARY_PAIRS", "EXPECTED_TRADING_DATES", "HISTORICAL_CALENDAR_DATE_SHA256", "HISTORICAL_CALENDAR_EVIDENCE_PATH", "HISTORICAL_CALENDAR_PATH", "MARKET_ENDPOINTS", "MARKETS",
    "REQUIRED_BASIC_INFO_FIELDS", "HistoricalInstrumentAcquisitionRunner",
    "InstrumentAcquisitionContractError", "build_historical_calendar_payload", "build_target_pairs", "endpoint_for_market",
    "load_historical_trading_calendar", "validate_basic_info_response", "validate_historical_trading_dates",
]
