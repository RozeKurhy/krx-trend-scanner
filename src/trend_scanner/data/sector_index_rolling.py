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
        }


class _BlockedInput(Exception):
    """Internal marker for an expected unavailable or invalid input."""


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
        except (MarketDataError, *_KNOWN_KRX_OPERATIONAL_BLOCKERS):
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
            )
        except Exception:
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
