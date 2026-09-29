"""Phase 3D rolling orchestration for the native 46-sector index cache.

This module is deliberately a coordinator.  It uses the Phase 1 rolling
authority and trading calendar to find missing sessions, then delegates each
session to the existing KRX sector-index update path.  It does not implement a
new collector or a second cache format.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_price_provider import IndexPriceDataProvider
from trend_scanner.data.krx_sector_index import (
    KRX_NATIVE_SECTOR_INDEX_MAP,
    KrxSectorIndexCacheBuilder,
)
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    load_rolling_authority,
)


PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

SECTOR_INDEX_CACHE_PATH = Path(".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet")
SECTOR_INDEX_META_PATH = Path(".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily_meta.json")
SECTOR_CODE_COUNT = len(KRX_NATIVE_SECTOR_INDEX_MAP)
_KNOWN_KRX_OPERATIONAL_BLOCKERS = (
    KrxOpenApiAuthorizationError,
    KrxOpenApiRateLimitError,
    KrxOpenApiBudgetError,
    KrxOpenApiQuotaExceeded,
)
_MISSING_AUTH_KEY_MESSAGES = frozenset({
    "KRX Open API auth key is required",
    "KRX_OPEN_API_AUTH_KEY is required for sector cache build",
})


@dataclass
class SectorIndexRollingResult:
    """Structured result for the Phase 3D rolling coordinator."""

    target_as_of: str
    status: str
    reason: str
    cache_path: Path
    cache_date_min: str | None = None
    cache_date_max: str | None = None
    required_trading_dates: list[str] | None = None
    missing_trading_dates: list[str] | None = None
    updated_trading_dates: list[str] | None = None
    update_call_count: int = 0
    row_count: int = 0
    trading_date_count: int = 0
    sector_code_count: int = 0
    diagnostic: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.required_trading_dates = list(self.required_trading_dates or [])
        self.missing_trading_dates = list(self.missing_trading_dates or [])
        self.updated_trading_dates = list(self.updated_trading_dates or [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_as_of": self.target_as_of,
            "status": self.status,
            "reason": self.reason,
            "cache_path": str(self.cache_path),
            "cache_date_min": self.cache_date_min,
            "cache_date_max": self.cache_date_max,
            "required_trading_dates": list(self.required_trading_dates or []),
            "missing_trading_dates": list(self.missing_trading_dates or []),
            "updated_trading_dates": list(self.updated_trading_dates or []),
            "update_call_count": int(self.update_call_count),
            "row_count": int(self.row_count),
            "trading_date_count": int(self.trading_date_count),
            "sector_code_count": int(self.sector_code_count),
            "diagnostic": dict(self.diagnostic) if self.diagnostic is not None else None,
        }


class _BlockedInput(Exception):
    """Internal marker for an expected unavailable or invalid input."""


_DIAGNOSTIC_FAILURE_TYPES = frozenset({
    "AUTH_REJECTED",
    "AUTH_CONFIGURATION",
    "RATE_LIMIT",
    "REQUEST_BUDGET_EXHAUSTED",
    "QUOTA_EXCEEDED",
    "HTTP_ERROR",
    "TIMEOUT",
    "CONNECTION_ERROR",
    "EMPTY_RESULT",
    "PARSE_ERROR",
    "RESPONSE_FORMAT_ERROR",
    "PROVIDER_ERROR",
})


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        for linked in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
            getattr(current, "reason", None),
        ):
            if isinstance(linked, BaseException):
                pending.append(linked)
    return chain


def _safe_diagnostic(
    date: str,
    *,
    error: BaseException | None = None,
    candidate: Any = None,
) -> dict[str, Any]:
    if isinstance(candidate, dict):
        failure_type = candidate.get("failure_type")
        exception_class = candidate.get("exception_class")
        http_status = candidate.get("http_status")
        timeout = candidate.get("timeout")
        connection_failure = candidate.get("connection_failure")
        response_present = candidate.get("response_present")
        provider_error_code = candidate.get("provider_error_code")
        empty_result = candidate.get("empty_result")
        parsing_failure = candidate.get("parsing_failure")
    else:
        chain = _exception_chain(error) if error is not None else []
        class_names = [type(item).__name__ for item in chain]
        http_status = next(
            (
                value
                for item in chain
                for value in (
                    getattr(item, "http_status", None),
                    getattr(item, "code", None),
                    getattr(getattr(item, "response", None), "status_code", None),
                )
                if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599
            ),
            None,
        )
        timeout = any("timeout" in name.lower() for name in class_names)
        connection_failure = any(
            name in {"ConnectionError", "ConnectionResetError", "ConnectionAbortedError", "NewConnectionError", "URLError"}
            or "connectionerror" in name.lower()
            for name in class_names
        )
        response_present = True if http_status is not None else None
        empty_result = False
        parsing_failure = False
        if isinstance(error, ValueError) and _is_missing_auth_key_error(error):
            failure_type = "AUTH_CONFIGURATION"
        elif any(isinstance(item, KrxOpenApiAuthorizationError) for item in chain):
            failure_type = "AUTH_REJECTED"
        elif any(isinstance(item, KrxOpenApiRateLimitError) for item in chain):
            failure_type = "RATE_LIMIT"
        elif any(isinstance(item, KrxOpenApiBudgetError) for item in chain):
            failure_type = "REQUEST_BUDGET_EXHAUSTED"
        elif any(isinstance(item, KrxOpenApiQuotaExceeded) for item in chain):
            failure_type = "QUOTA_EXCEEDED"
        elif timeout:
            failure_type = "TIMEOUT"
        elif http_status is not None:
            failure_type = "HTTP_ERROR"
        elif connection_failure:
            failure_type = "CONNECTION_ERROR"
        elif any(name in {"JSONDecodeError", "UnicodeDecodeError"} for name in class_names):
            failure_type = "PARSE_ERROR"
            parsing_failure = True
            response_present = True
        else:
            failure_type = "PROVIDER_ERROR"
        exception_class = next(
            (
                name for name in class_names
                if "timeout" in name.lower()
                or name in {"HTTPError", "ConnectionError", "ConnectionResetError", "ConnectionAbortedError", "NewConnectionError", "URLError"}
            ),
            class_names[0] if class_names else None,
        )
        provider_error_code = None

    if failure_type not in _DIAGNOSTIC_FAILURE_TYPES:
        failure_type = "PROVIDER_ERROR"
    if not isinstance(exception_class, str) or not exception_class.isidentifier() or len(exception_class) > 80:
        exception_class = None
    if not isinstance(http_status, int) or isinstance(http_status, bool) or not 100 <= http_status <= 599:
        http_status = None
    if not isinstance(provider_error_code, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,32}", provider_error_code) is None:
        provider_error_code = None
    return {
        "component": "SECTOR_INDEX",
        "provider": "KRX_OPEN_API",
        "requested_date": date,
        "failure_type": failure_type,
        "exception_class": exception_class,
        "http_status": http_status,
        "timeout": timeout if isinstance(timeout, bool) else False,
        "connection_failure": connection_failure if isinstance(connection_failure, bool) else False,
        "response_present": response_present if isinstance(response_present, bool) else None,
        "provider_error_code": provider_error_code,
        "empty_result": empty_result if isinstance(empty_result, bool) else False,
        "parsing_failure": parsing_failure if isinstance(parsing_failure, bool) else False,
    }


def _diagnostic_from_report(report: Any, date: str) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    candidates = report.get("fetch_diagnostics")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("requested_date") == date:
            return _safe_diagnostic(date, candidate=candidate)
    return None


def _is_missing_auth_key_error(error: ValueError) -> bool:
    """Recognise only the two existing production auth-key validation messages."""

    return str(error).strip() in _MISSING_AUTH_KEY_MESSAGES


def _normalise_date(value: Any) -> str:
    try:
        return pd.Timestamp(value).normalize().strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise _BlockedInput("INVALID_TARGET_AS_OF") from exc


def _calendar_dates(calendar: Any) -> list[str]:
    values = getattr(calendar, "trading_dates", calendar)
    try:
        parsed = pd.to_datetime(list(values), errors="raise").normalize()
    except Exception as exc:  # noqa: BLE001 - invalid authority is blocked
        raise _BlockedInput("PHASE1_TRADING_CALENDAR_INVALID") from exc
    if len(parsed) == 0:
        raise _BlockedInput("PHASE1_TRADING_CALENDAR_EMPTY")
    return sorted({value.strftime("%Y-%m-%d") for value in parsed})


def _load_calendar(repo_root: Path, calendar: Any | None) -> Any:
    if calendar is not None:
        return calendar
    try:
        resolved = load_rolling_production_market_calendar(repo_root)
    except Exception as exc:  # noqa: BLE001 - authority reads fail closed
        raise _BlockedInput("PHASE1_TRADING_CALENDAR_UNAVAILABLE") from exc
    if resolved is None:
        raise _BlockedInput("PHASE1_TRADING_CALENDAR_UNAVAILABLE")
    return resolved


def _validate_existing_cache(parquet_path: Path, meta_path: Path) -> pd.DataFrame:
    if not parquet_path.is_file() or not meta_path.is_file():
        raise _BlockedInput("EXISTING_SECTOR_CACHE_MISSING")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - invalid seed is blocked
        raise _BlockedInput("EXISTING_SECTOR_CACHE_META_INVALID") from exc
    if not isinstance(metadata, dict):
        raise _BlockedInput("EXISTING_SECTOR_CACHE_META_INVALID")
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:  # noqa: BLE001 - unreadable seed is blocked
        raise _BlockedInput("EXISTING_SECTOR_CACHE_UNREADABLE") from exc
    try:
        validated, _ = KrxSectorIndexCacheBuilder._validate_dataframe(frame, minimum_sessions=1)
    except (MarketDataError, ValueError, TypeError) as exc:
        raise _BlockedInput("EXISTING_SECTOR_CACHE_INVALID") from exc
    if validated.empty:
        raise _BlockedInput("EXISTING_SECTOR_CACHE_EMPTY")
    if validated["index_code"].nunique() != SECTOR_CODE_COUNT:
        raise _BlockedInput("EXISTING_SECTOR_CACHE_SECTOR_CODE_COUNT_INVALID")
    return validated


def _frame_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "cache_date_min": None,
            "cache_date_max": None,
            "row_count": 0,
            "trading_date_count": 0,
            "sector_code_count": 0,
        }
    return {
        "cache_date_min": str(frame["date"].min()),
        "cache_date_max": str(frame["date"].max()),
        "row_count": int(len(frame)),
        "trading_date_count": int(frame["date"].nunique()),
        "sector_code_count": int(frame["index_code"].nunique()),
    }


def _result(
    *,
    target: str,
    status: str,
    reason: str,
    cache_path: Path,
    frame: pd.DataFrame | None = None,
    required: list[str] | None = None,
    missing: list[str] | None = None,
    updated: list[str] | None = None,
    update_calls: int = 0,
    diagnostic: dict[str, Any] | None = None,
) -> SectorIndexRollingResult:
    summary = _frame_summary(frame) if frame is not None else {}
    return SectorIndexRollingResult(
        target_as_of=target,
        status=status,
        reason=reason,
        cache_path=cache_path,
        cache_date_min=summary.get("cache_date_min"),
        cache_date_max=summary.get("cache_date_max"),
        required_trading_dates=required,
        missing_trading_dates=missing,
        updated_trading_dates=updated,
        update_call_count=update_calls,
        row_count=int(summary.get("row_count", 0)),
        trading_date_count=int(summary.get("trading_date_count", 0)),
        sector_code_count=int(summary.get("sector_code_count", 0)),
        diagnostic=diagnostic,
    )


def update_sector_index_rolling(
    target_as_of: str,
    *,
    repo_root: Path,
    provider: Any | None = None,
    calendar: Any | None = None,
) -> SectorIndexRollingResult:
    """Update only missing Phase 1 trading dates through the existing provider path."""

    repo_root = Path(repo_root)
    cache_path = repo_root / SECTOR_INDEX_CACHE_PATH
    meta_path = repo_root / SECTOR_INDEX_META_PATH
    try:
        target = _normalise_date(target_as_of)
    except _BlockedInput:
        return _result(
            target=str(target_as_of),
            status=FAILED,
            reason="INVALID_TARGET_AS_OF",
            cache_path=cache_path,
        )

    try:
        manifest = load_rolling_authority(repo_root / DEFAULT_ROLLING_AUTHORITY_DIR)
        certified_through = _normalise_date(manifest.certified_through)
    except Exception as exc:  # noqa: BLE001 - Phase 1 authority is mandatory
        return _result(
            target=target,
            status=BLOCKED,
            reason="PHASE1_ROLLING_AUTHORITY_UNAVAILABLE",
            cache_path=cache_path,
        )
    if target > certified_through:
        return _result(
            target=target,
            status=BLOCKED,
            reason="TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY",
            cache_path=cache_path,
        )

    try:
        resolved_calendar = _load_calendar(repo_root, calendar)
        calendar_dates = _calendar_dates(resolved_calendar)
        frame = _validate_existing_cache(cache_path, meta_path)
    except _BlockedInput as exc:
        return _result(
            target=target,
            status=BLOCKED,
            reason=str(exc),
            cache_path=cache_path,
        )

    cache_start = str(frame["date"].min())
    if target < cache_start:
        return _result(
            target=target,
            status=BLOCKED,
            reason="TARGET_BEFORE_CACHE_START",
            cache_path=cache_path,
            frame=frame,
        )

    required = [day for day in calendar_dates if cache_start <= day <= target]
    if not required:
        return _result(
            target=target,
            status=BLOCKED,
            reason="PHASE1_REQUIRED_TRADING_DATES_EMPTY",
            cache_path=cache_path,
            frame=frame,
        )

    complete_dates = set(frame["date"].astype(str).unique())
    missing = [day for day in required if day not in complete_dates]
    if not missing:
        return _result(
            target=target,
            status=NOOP_ALREADY_COMPLETE,
            reason="REQUIRED_TRADING_DATES_ALREADY_COMPLETE",
            cache_path=cache_path,
            frame=frame,
            required=required,
        )

    updater = provider if provider is not None else IndexPriceDataProvider()
    updated: list[str] = []
    update_calls = 0
    initial_dates = set(complete_dates)

    for day in missing:
        update_calls += 1
        try:
            updater.update_sector_index_cache(
                target_date=day,
                output_parquet=cache_path,
                output_meta=meta_path,
            )
        except (MarketDataError, *_KNOWN_KRX_OPERATIONAL_BLOCKERS) as exc:
            return _result(
                target=target,
                status=BLOCKED,
                reason=f"REQUIRED_TRADING_DATE_UPDATE_BLOCKED:{day}",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
                diagnostic=_safe_diagnostic(day, error=exc, candidate=getattr(exc, "diagnostic", None)),
            )
        except ValueError as exc:
            if _is_missing_auth_key_error(exc):
                return _result(
                    target=target,
                    status=BLOCKED,
                    reason=f"REQUIRED_TRADING_DATE_UPDATE_BLOCKED:{day}",
                    cache_path=cache_path,
                    frame=frame,
                    required=required,
                    missing=missing,
                    updated=updated,
                    update_calls=update_calls,
                    diagnostic=_safe_diagnostic(day, error=exc),
                )
            return _result(
                target=target,
                status=FAILED,
                reason=f"REQUIRED_TRADING_DATE_UPDATE_FAILED:{day}",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
                diagnostic=_safe_diagnostic(day, error=exc),
            )
        except Exception as exc:
            return _result(
                target=target,
                status=FAILED,
                reason=f"REQUIRED_TRADING_DATE_UPDATE_FAILED:{day}",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
                diagnostic=_safe_diagnostic(day, error=exc),
            )

        try:
            frame = _validate_existing_cache(cache_path, meta_path)
        except _BlockedInput as exc:
            return _result(
                target=target,
                status=BLOCKED,
                reason=f"UPDATED_SECTOR_CACHE_INVALID:{exc}",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
            )

        observed_dates = set(frame["date"].astype(str).unique())
        new_dates = observed_dates - initial_dates
        if any(day > target for day in new_dates):
            return _result(
                target=target,
                status=BLOCKED,
                reason="UPDATED_CACHE_DATE_AFTER_TARGET",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
            )
        if day not in observed_dates:
            diagnostic = _diagnostic_from_report(
                getattr(updater, "last_sector_index_update_report", None),
                day,
            ) or _safe_diagnostic(
                day,
                candidate={
                    "failure_type": "EMPTY_RESULT",
                    "response_present": None,
                    "empty_result": True,
                },
            )
            return _result(
                target=target,
                status=BLOCKED,
                reason="REQUIRED_TRADING_DATE_NOT_MATERIALIZED",
                cache_path=cache_path,
                frame=frame,
                required=required,
                missing=missing,
                updated=updated,
                update_calls=update_calls,
                diagnostic=diagnostic,
            )
        updated.append(day)

    final_missing = [day for day in required if day not in set(frame["date"].astype(str).unique())]
    if final_missing:
        return _result(
            target=target,
            status=BLOCKED,
            reason="REQUIRED_TRADING_DATE_GAP_REMAINS",
            cache_path=cache_path,
            frame=frame,
            required=required,
            missing=final_missing,
            updated=updated,
            update_calls=update_calls,
        )

    return _result(
        target=target,
        status=PASS,
        reason="REQUIRED_TRADING_DATES_UPDATED",
        cache_path=cache_path,
        frame=frame,
        required=required,
        missing=missing,
        updated=updated,
        update_calls=update_calls,
    )


__all__ = [
    "BLOCKED",
    "FAILED",
    "NOOP_ALREADY_COMPLETE",
    "PASS",
    "SECTOR_INDEX_CACHE_PATH",
    "SECTOR_INDEX_META_PATH",
    "SectorIndexRollingResult",
    "update_sector_index_rolling",
]
