"""Resumable, sequential KRX raw stock historical backfill runner."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_provider import (
    MARKET_ENDPOINTS,
    MARKETS,
    KrxRawStockSnapshotError,
    KrxRawStockSnapshotProvider,
    normalize_bas_dd,
    normalize_market,
)
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


KST = ZoneInfo("Asia/Seoul")
NO_DATA_FINALIZATION_LAG_DAYS = 2
BLOCKER_PRIORITY = (
    "BLOCKED_KRX_AUTH",
    "BACKFILL_PAUSED_QUOTA",
    "BACKFILL_PAUSED_TASK_BUDGET",
    "BLOCKED_KRX_SCHEMA",
    "BLOCKED_RAW_STORE_INTEGRITY",
    "BLOCKED_CROSS_MARKET_TICKER_CONFLICT",
    "BLOCKED_COVERAGE",
    "BLOCKED_MORE_EVIDENCE_REQUIRED",
)


def prioritize_blockers(blockers: Iterable[str]) -> list[str]:
    """Deduplicate blockers while preserving the declared status precedence."""

    unique = list(dict.fromkeys(str(item) for item in blockers if item))
    rank = {name: index for index, name in enumerate(BLOCKER_PRIORITY)}
    return sorted(unique, key=lambda item: (rank.get(item, len(rank)), item))


def candidate_dates(start: Any, end: Any) -> list[str]:
    start_day = pd.Timestamp(normalize_bas_dd(start))
    end_day = pd.Timestamp(normalize_bas_dd(end))
    if start_day > end_day:
        raise MarketDataError("BACKFILL_INVALID_DATE_RANGE")
    return [item.date().isoformat() for item in pd.bdate_range(start_day, end_day)]


class KrxHistoricalBackfillRunner:
    """Coordinate market/date snapshots without mutating consumer state."""

    def __init__(
        self,
        provider: KrxRawStockSnapshotProvider,
        store: KrxRawStockStore,
        quota: LocalKrxOpenApiQuota,
        *,
        request_interval_ms: int = 0,
    ) -> None:
        if quota is None:
            raise MarketDataError("BACKFILL_QUOTA_REQUIRED")
        if request_interval_ms < 0:
            raise ValueError("request_interval_ms must be non-negative")
        client = getattr(provider, "client", None)
        if client is not None and getattr(client, "quota", None) is None:
            raise MarketDataError("BACKFILL_QUOTA_REQUIRED")
        if client is not None and getattr(client, "quota", quota) is not quota:
            raise MarketDataError("BACKFILL_QUOTA_MISMATCH")
        self.provider = provider
        self.store = store
        self.quota = quota
        self.request_interval_ms = request_interval_ms

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if getattr(exc, "error_code", None):
            return str(exc.error_code)
        text = str(exc)
        if text.startswith("RAW_"):
            return text.split(":", 1)[0]
        return type(exc).__name__.upper()

    def _snapshot_state(self, day: str) -> dict[str, dict[str, Any] | None]:
        return {market: self.store.get_manifest(market, day) for market in MARKETS}

    def _aggregate(self, dates: list[str]) -> dict[str, Any]:
        rows_by_market = {market: 0 for market in MARKETS}
        tickers_by_market = {market: set() for market in MARKETS}
        complete_dates: list[str] = []
        no_data_dates: list[str] = []
        failed_dates: list[str] = []
        partial_dates: list[str] = []
        integrity_error_count = 0
        cross_market_conflicts: list[dict[str, Any]] = []
        for day in dates:
            states = self._snapshot_state(day)
            statuses = {market: (states[market] or {}).get("status") for market in MARKETS}
            if all(statuses[market] == "COMPLETE" for market in MARKETS):
                complete_dates.append(day)
                seen: dict[str, str] = {}
                for market in MARKETS:
                    row = states[market] or {}
                    rows_by_market[market] += int(row.get("row_count") or 0)
                    try:
                        frame = self.store.load_snapshot(market, day)
                    except Exception:
                        integrity_error_count += 1
                        continue
                    tickers = frame["ticker"].astype(str).tolist()
                    tickers_by_market[market].update(tickers)
                    for ticker in tickers:
                        previous = seen.get(ticker)
                        if previous is not None and previous != market:
                            cross_market_conflicts.append({"date": day, "ticker": ticker, "markets": [previous, market]})
                        else:
                            seen[ticker] = market
            elif all(statuses[market] == "NO_DATA" for market in MARKETS):
                no_data_dates.append(day)
            else:
                if any(status == "FAILED" for status in statuses.values() if status is not None):
                    failed_dates.append(day)
                if sum(status == "COMPLETE" for status in statuses.values()) == 1:
                    partial_dates.append(day)
        return {
            "complete_date_count": len(complete_dates),
            "no_data_date_count": len(no_data_dates),
            "failed_date_count": len(failed_dates),
            "partial_date_count": len(partial_dates),
            "complete_dates": complete_dates,
            "no_data_dates": no_data_dates,
            "failed_dates": failed_dates,
            "partial_dates": partial_dates,
            "total_rows": sum(rows_by_market.values()),
            "rows_by_market": rows_by_market,
            "unique_tickers_by_market": {market: len(values) for market, values in tickers_by_market.items()},
            "integrity_error_count": integrity_error_count,
            "cross_market_ticker_conflict_count": len(cross_market_conflicts),
            "cross_market_conflict_samples": cross_market_conflicts[:20],
        }

    def run(
        self,
        start: Any,
        end: Any,
        *,
        resume: bool = False,
        max_task_attempts: int = 10_000,
        retry_failures: bool = False,
        markets: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if max_task_attempts < 1:
            raise ValueError("max_task_attempts must be positive")
        requested_markets = tuple(dict.fromkeys(normalize_market(value) for value in (markets or MARKETS)))
        if set(requested_markets) != set(MARKETS):
            raise MarketDataError("BACKFILL_REQUIRES_BOTH_MARKETS")
        dates = candidate_dates(start, end)
        usage_date = self.quota.usage_date_kst()
        quota_before = self.quota.get_usage(usage_date)
        task_attempts = 0
        quota_pause = False
        task_pause = False
        blockers: list[str] = []
        recent_empty_unfinalized_count = 0
        retry_attempt_count = 0
        market_attempts = {market: 0 for market in MARKETS}
        status_counts = {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0}
        diagnostics: list[dict[str, Any]] = []
        failure_observations: list[dict[str, Any]] = []

        for day in dates:
            states = self._snapshot_state(day)
            pending: list[str] = []
            for market in MARKETS:
                state = states[market]
                if resume and state is not None and state.get("status") in {"COMPLETE", "NO_DATA"}:
                    integrity = self.store.verify_snapshot(market, day)
                    if not integrity.get("valid"):
                        blockers.append("BLOCKED_RAW_STORE_INTEGRITY")
                        break
                    continue
                if state is not None and state.get("status") == "FAILED" and not retry_failures and resume:
                    continue
                pending.append(market)
            if blockers:
                break
            fetched: dict[str, pd.DataFrame] = {}
            failures: dict[str, Exception] = {}
            for market in pending:
                if task_attempts >= max_task_attempts:
                    task_pause = True
                    blockers.append("BACKFILL_PAUSED_TASK_BUDGET")
                    break
                if task_attempts and self.request_interval_ms:
                    time.sleep(self.request_interval_ms / 1000)
                task_attempts += 1
                market_attempts[market] += 1
                try:
                    fetched[market] = self.provider.fetch_market_snapshot(market, day)
                except KrxOpenApiQuotaExceeded as exc:
                    failures[market] = exc
                    quota_pause = True
                    blockers.append("BACKFILL_PAUSED_QUOTA")
                    self.store.save_failure(market, day, MARKET_ENDPOINTS[market], "BACKFILL_PAUSED_QUOTA", str(exc))
                    break
                except KrxOpenApiBudgetError as exc:
                    failures[market] = exc
                    task_pause = True
                    blockers.append("BACKFILL_PAUSED_TASK_BUDGET")
                    self.store.save_failure(market, day, MARKET_ENDPOINTS[market], "BACKFILL_PAUSED_TASK_BUDGET", str(exc))
                    break
                except (KrxOpenApiAuthorizationError, KrxOpenApiRateLimitError) as exc:
                    failures[market] = exc
                    blockers.append("BLOCKED_KRX_AUTH" if isinstance(exc, KrxOpenApiAuthorizationError) else "BACKFILL_PAUSED_QUOTA")
                    self.store.save_failure(market, day, MARKET_ENDPOINTS[market], self._error_code(exc), str(exc))
                    quota_pause = isinstance(exc, KrxOpenApiRateLimitError)
                    break
                except Exception as exc:  # schema/transport failures are recorded and the run remains resumable
                    failures[market] = exc
                    error_code = self._error_code(exc)
                    self.store.save_failure(market, day, MARKET_ENDPOINTS[market], error_code, str(exc))
                    observation = {
                        "date": day,
                        "market": market,
                        "endpoint": MARKET_ENDPOINTS[market],
                        "error_code": error_code,
                    }
                    diagnostic = getattr(exc, "diagnostic", None)
                    if diagnostic:
                        observation.update(diagnostic)
                    diagnostics.append(observation)
                    failure_observations.append({"date": day, "market": market, "status": "FAILED", "error_code": error_code})
                    if isinstance(exc, KrxRawStockSnapshotError) or str(exc).startswith("RAW_"):
                        blockers.append("BLOCKED_KRX_SCHEMA")
                    else:
                        blockers.append("BLOCKED_MORE_EVIDENCE_REQUIRED")
            if quota_pause or task_pause or blockers and not fetched:
                if quota_pause or task_pause or any(item.startswith("BLOCKED_KRX_") for item in blockers):
                    break

            # Save non-empty/empty responses only after both sides are available,
            # so a pair-empty decision is atomic at the date-coordination level.
            if len(fetched) == len(pending) and len(pending) == 2:
                empty = {market: fetched[market].empty for market in MARKETS}
                if all(empty.values()):
                    today = datetime.now(KST).date()
                    if date.fromisoformat(day) > today - timedelta(days=NO_DATA_FINALIZATION_LAG_DAYS):
                        recent_empty_unfinalized_count += 1
                        diagnostics.append({
                            "date": day,
                            "market": "BOTH",
                            "endpoint": "KOSPI+KOSDAQ",
                            "error_code": "RECENT_EMPTY_NOT_FINAL",
                            "record_count": 0,
                        })
                    else:
                        for market in MARKETS:
                            self.store.save_snapshot(market, day, fetched[market], MARKET_ENDPOINTS[market])
                elif any(empty.values()):
                    for market in MARKETS:
                        if not empty[market]:
                            self.store.save_snapshot(market, day, fetched[market], MARKET_ENDPOINTS[market])
                        else:
                            self.store.save_failure(market, day, MARKET_ENDPOINTS[market], "ASYMMETRIC_EMPTY_SNAPSHOT", "one market returned rows while the other was empty")
                    blockers.append("BLOCKED_COVERAGE")
                else:
                    for market in MARKETS:
                        self.store.save_snapshot(market, day, fetched[market], MARKET_ENDPOINTS[market])
            elif fetched and not (quota_pause or task_pause):
                # A previously COMPLETE side remains untouched; any newly
                # fetched side is safe to commit independently for resume.
                for market, frame in fetched.items():
                    if frame.empty:
                        self.store.save_failure(market, day, MARKET_ENDPOINTS[market], "ASYMMETRIC_EMPTY_SNAPSHOT", "paired market was not fetched")
                    else:
                        self.store.save_snapshot(market, day, frame, MARKET_ENDPOINTS[market])
                if failures:
                    blockers.append("BLOCKED_COVERAGE")
            if retry_failures:
                retry_attempt_count = max(0, task_attempts - len(dates) * 2)
            if quota_pause or task_pause:
                break

        aggregate = self._aggregate(dates)
        quota_after = self.quota.get_usage(usage_date)
        client = getattr(self.provider, "client", None)
        if client is not None:
            status_counts.update({str(key): int(value) for key, value in getattr(client, "status_counts", {}).items()})
        if aggregate["integrity_error_count"] > 0:
            blockers.append("BLOCKED_RAW_STORE_INTEGRITY")
        if aggregate["cross_market_ticker_conflict_count"] > 0:
            blockers.append("BLOCKED_CROSS_MARKET_TICKER_CONFLICT")
        if (
            aggregate["complete_date_count"] + aggregate["no_data_date_count"] != len(dates)
            or aggregate["failed_date_count"] > 0
            or aggregate["partial_date_count"] > 0
        ):
            blockers.append("BLOCKED_COVERAGE")
        blockers = prioritize_blockers(blockers)
        status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX02_REVIEW" if not blockers else blockers[0]
        return {
            "status": status,
            "recommendation": "RECOMMEND_PROCEED_TO_MARKET_DATA_REPOSITORY_V02" if status.startswith("READY_") else status,
            "candidate_date_count": len(dates),
            "dates": dates,
            "task_attempt_count": task_attempts,
            "retry_attempt_count": retry_attempt_count + int(getattr(client, "retry_count", 0) if client else 0),
            "market_attempts": market_attempts,
            "recent_empty_unfinalized_count": recent_empty_unfinalized_count,
            "quota_usage_date_kst": usage_date,
            "quota_global_before": int(quota_before.get("global_total", 0)),
            "quota_global_after": int(quota_after.get("global_total", 0)),
            "quota_remaining_after": self.quota.remaining("stk_bydd_trd"),
            "krx_open_api_attempt_count": int(getattr(client, "request_count", task_attempts) if client else task_attempts),
            "kospi_daily_attempt_count": market_attempts["KOSPI"],
            "kosdaq_daily_attempt_count": market_attempts["KOSDAQ"],
            "status_counts": status_counts,
            "aggregate": aggregate,
            "blockers": blockers,
            "diagnostics": diagnostics,
            "failure_observations": failure_observations,
        }


__all__ = [
    "NO_DATA_FINALIZATION_LAG_DAYS",
    "BLOCKER_PRIORITY",
    "KrxHistoricalBackfillRunner",
    "candidate_dates",
    "prioritize_blockers",
]
