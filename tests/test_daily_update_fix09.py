"""Focused offline contracts for COMMON raw fail-fast and required retry FIX09."""

from __future__ import annotations

import pandas as pd

from tests.test_daily_update_foundation_v01 import _foundation
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import RollingRawMarketUpdater


def _raw_frame(day: str, ticker: str) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "date": pd.Timestamp(day),
            "ticker": ticker,
            "open": 100,
            "high": 110,
            "low": 90,
            "close": 105,
            "volume": 1000,
            "trading_value": 2000,
            "market_cap": 3000,
            "listed_shares": 4000,
        }],
        columns=list(RAW_COLUMNS),
    )


def test_common_raw_blocker_fails_before_any_downstream_call(tmp_path):
    foundation, _raw, authority, _common_raw, etf_raw, common_adjusted, etf_adjusted = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01"],
        certified="2026-09-01",
    )

    class BlockedCommonRaw:
        def refresh(self, boundary, target, *, required_dates):
            return {
                "required_dates": list(required_dates),
                "new_boundary": boundary,
                "runner_result": {
                    "status": "BLOCKED_KRX_SCHEMA",
                    "blockers": ["BLOCKED_KRX_SCHEMA"],
                },
            }

    foundation.common_raw_updater = BlockedCommonRaw()
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["reason"] == "BLOCKED_COMMON_RAW:BLOCKED_KRX_SCHEMA"
    assert result["authority_promotion"] == 0
    assert result["production_write_count"] == 0
    assert not etf_raw.calls and not common_adjusted.calls and not etf_adjusted.calls
    assert (authority / "manifest.json").read_bytes() == before


def test_common_raw_incomplete_without_runner_blocker_fails_fast(tmp_path):
    foundation, _raw, _authority, _common_raw, etf_raw, common_adjusted, etf_adjusted = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01"],
        certified="2026-09-01",
    )

    class IncompleteCommonRaw:
        def refresh(self, boundary, target, *, required_dates):
            return {
                "required_dates": list(required_dates),
                "new_boundary": boundary,
                "runner_result": {"status": "READY"},
            }

    foundation.common_raw_updater = IncompleteCommonRaw()
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["reason"] == "BLOCKED_COMMON_RAW:BLOCKED_COVERAGE"
    assert result["authority_promotion"] == 0
    assert not etf_raw.calls and not common_adjusted.calls and not etf_adjusted.calls


def _retry_fixture(tmp_path, *, failed_day: str = "2026-09-14"):
    raw = KrxRawStockStore(tmp_path / "raw")
    raw.save_failure("KOSPI", failed_day, "/sto/stk_bydd_trd", "RAW_SNAPSHOT_HTTP_STATUS", "retry")
    raw.save_snapshot("KOSDAQ", failed_day, _raw_frame(failed_day, "000660"), "/sto/ksq_bydd_trd")
    return raw


def test_current_required_failed_partition_is_retried(tmp_path):
    day = "2026-09-14"
    raw = _retry_fixture(tmp_path, failed_day=day)

    class Provider:
        def __init__(self):
            self.calls = []

        def fetch_market_snapshot(self, market, requested_day):
            self.calls.append((market, requested_day))
            assert market == "KOSPI"
            return _raw_frame(requested_day, "005930")

    provider = Provider()
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    runner = KrxHistoricalBackfillRunner(provider, raw, quota)
    result = RollingRawMarketUpdater(runner, raw).refresh(
        "2026-09-11", day, required_dates=[day]
    )

    assert provider.calls == [("KOSPI", day)]
    assert result["retry_required_failed_dates"] == [day]
    assert result["repair_results"][0]["status"].startswith("READY_")
    assert raw.get_manifest("KOSPI", day)["status"] == "COMPLETE"


def test_required_retry_preserves_complete_paired_side(tmp_path):
    day = "2026-09-14"
    raw = _retry_fixture(tmp_path, failed_day=day)
    before = raw.get_manifest("KOSDAQ", day)

    class Provider:
        def fetch_market_snapshot(self, market, requested_day):
            assert (market, requested_day) == ("KOSPI", day)
            return _raw_frame(requested_day, "005930")

    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    runner = KrxHistoricalBackfillRunner(Provider(), raw, quota)
    RollingRawMarketUpdater(runner, raw).refresh("2026-09-11", day, required_dates=[day])

    after = raw.get_manifest("KOSDAQ", day)
    assert after["status"] == "COMPLETE"
    assert after["content_sha256"] == before["content_sha256"]
    assert after["file_sha256"] == before["file_sha256"]


def test_unrelated_historical_failed_partition_is_not_retried(tmp_path):
    unrelated = "2026-09-10"
    target = "2026-09-14"
    raw = _retry_fixture(tmp_path, failed_day=unrelated)

    class Provider:
        def __init__(self):
            self.calls = []

        def fetch_market_snapshot(self, market, requested_day):
            self.calls.append((market, requested_day))
            return _raw_frame(requested_day, "005930" if market == "KOSPI" else "000660")

    provider = Provider()
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    runner = KrxHistoricalBackfillRunner(provider, raw, quota)
    RollingRawMarketUpdater(runner, raw).refresh(
        "2026-09-11", target, required_dates=[target]
    )

    assert all(requested_day == target for _market, requested_day in provider.calls)
    assert raw.get_manifest("KOSPI", unrelated)["status"] == "FAILED"


def test_failed_retry_blocker_is_merged_and_remains_fail_fast(tmp_path):
    day = "2026-09-14"
    raw = _retry_fixture(tmp_path, failed_day=day)

    class Provider:
        def fetch_market_snapshot(self, market, requested_day):
            raise RuntimeError("still unavailable")

    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    runner = KrxHistoricalBackfillRunner(Provider(), raw, quota)
    result = RollingRawMarketUpdater(runner, raw).refresh(
        "2026-09-11", day, required_dates=[day]
    )

    assert "BLOCKED_MORE_EVIDENCE_REQUIRED" in result["runner_result"]["blockers"]
    assert raw.get_manifest("KOSPI", day)["status"] == "FAILED"
