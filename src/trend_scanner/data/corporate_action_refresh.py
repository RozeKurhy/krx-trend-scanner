"""Dirty adjusted-history refresh service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    AdjustedPriceDataProvider,
    validate_adjusted_ohlc,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_detector import normalise_as_of
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.errors import MarketDataError


@dataclass(frozen=True)
class RefreshResult:
    ticker: str
    status: str
    reason: str | None
    rows: int
    before_content_sha256: str | None
    after_content_sha256: str | None
    requested_start: str | None
    requested_end: str | None


class CorporateActionRefreshService:
    """Refresh only dirty/failed tickers using the dedicated adjusted provider."""

    def __init__(
        self,
        state_store: CorporateActionStateStore,
        provider: AdjustedPriceDataProvider,
        adjusted_store: AdjustedPriceStore,
    ) -> None:
        self.state_store = state_store
        self.provider = provider
        self.adjusted_store = adjusted_store

    @staticmethod
    def _refresh_reason(error: Exception) -> str:
        message = str(error)
        for code in (
            "ADJUSTED_STORE_MISSING",
            "PARTIAL_REFRESH_RESPONSE",
            "EMPTY_REFRESH_RESPONSE",
            "REFRESH_END_BEFORE_EXISTING_COVERAGE",
            "OLD_STORE_LOAD_FAILED",
            "POST_REFRESH_INTEGRITY_FAILED",
        ):
            if code in message:
                return code
        return "REFRESH_FAILED"

    @staticmethod
    def _date_string(value: Any, field: str) -> str:
        try:
            return normalise_as_of(value).isoformat()
        except MarketDataError as exc:
            raise MarketDataError(f"{field}가 유효한 date-like 값이 아닙니다.") from exc

    def refresh_dirty(self, ticker: str, refresh_end: str | date) -> RefreshResult:
        state = self.state_store.get(ticker)
        normalized = state.ticker if state else str(ticker).zfill(6)
        if not self.state_store.claim_refresh(normalized):
            return RefreshResult(normalized, "NOOP", "NOT_CLAIMED", 0, None, None, None, None)

        before_hash: str | None = None
        requested_start: str | None = None
        requested_end: str | None = None
        try:
            if not self.adjusted_store.exists(normalized):
                raise MarketDataError("ADJUSTED_STORE_MISSING")
            try:
                old_frame = self.adjusted_store.load_daily(normalized)
                old_metadata = self.adjusted_store.load_metadata(normalized)
            except Exception as exc:
                raise MarketDataError(f"OLD_STORE_LOAD_FAILED: {exc}") from exc
            before_hash = old_metadata["content_sha256"]
            requested_start = old_metadata.get("requested_start") or old_metadata["actual_date_min"]
            requested_start = self._date_string(requested_start, "requested_start")
            requested_end = self._date_string(refresh_end, "refresh_end")
            old_actual_max = self._date_string(old_metadata["actual_date_max"], "actual_date_max")
            if requested_end < old_actual_max:
                raise MarketDataError("REFRESH_END_BEFORE_EXISTING_COVERAGE")

            new_frame = self.provider.load_daily(normalized, requested_start, requested_end)
            validate_adjusted_ohlc(new_frame)
            if new_frame.empty:
                raise MarketDataError("EMPTY_REFRESH_RESPONSE")
            if not old_frame.index.isin(new_frame.index).all():
                raise MarketDataError("PARTIAL_REFRESH_RESPONSE")
            if new_frame.index.min() > old_frame.index.min() or new_frame.index.max() < old_frame.index.max():
                raise MarketDataError("PARTIAL_REFRESH_RESPONSE")

            self.adjusted_store.save_full(
                normalized,
                new_frame,
                {"requested_start": requested_start, "requested_end": requested_end},
            )
            try:
                reloaded = self.adjusted_store.load_daily(normalized)
                after_metadata = self.adjusted_store.load_metadata(normalized)
                if not reloaded.index.equals(new_frame.index):
                    raise MarketDataError("POST_REFRESH_INTEGRITY_FAILED: date index changed")
                after_hash = after_metadata["content_sha256"]
            except Exception as exc:
                raise MarketDataError(f"POST_REFRESH_INTEGRITY_FAILED: {exc}") from exc
            self.state_store.mark_clean(normalized, after_hash)
            return RefreshResult(
                normalized,
                "CLEAN",
                "REFRESH_SUCCESS",
                len(reloaded),
                before_hash,
                after_hash,
                requested_start,
                requested_end,
            )
        except Exception as exc:
            reason = self._refresh_reason(exc)
            self.state_store.mark_failed(normalized, reason, str(exc))
            return RefreshResult(
                normalized,
                "FAILED",
                reason,
                0,
                before_hash,
                None,
                requested_start,
                requested_end,
            )


__all__ = ["CorporateActionRefreshService", "RefreshResult"]
