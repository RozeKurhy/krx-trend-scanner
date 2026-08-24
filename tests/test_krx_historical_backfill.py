from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner, candidate_dates


def _frame(day, ticker):
    return pd.DataFrame([{
        "date": pd.Timestamp(day), "ticker": ticker, "open": 100, "high": 110, "low": 90, "close": 105,
        "volume": 1000, "trading_value": 2000, "market_cap": 3000, "listed_shares": 4000,
    }], columns=list(RAW_COLUMNS))


class _Provider:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.calls = []

    def fetch_market_snapshot(self, market, day):
        self.calls.append((market, day))
        if self.mode == "both-empty":
            return _frame(day, "005930").iloc[0:0].copy()
        if self.mode == "asymmetric" and market == "KOSDAQ":
            return _frame(day, "005930").iloc[0:0].copy()
        return _frame(day, "005930" if market == "KOSPI" else "000660")


class _QuotaProvider(_Provider):
    def fetch_market_snapshot(self, market, day):
        raise KrxOpenApiQuotaExceeded(
            "quota",
            endpoint_key="stk_bydd_trd",
            usage_date_kst="2026-08-21",
            endpoint_before=1,
            global_before=1,
        )


def _runner(tmp_path, provider):
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    return KrxHistoricalBackfillRunner(provider, KrxRawStockStore(tmp_path / "raw"), quota), quota


def test_candidate_dates_are_weekdays_only():
    assert candidate_dates("2026-08-21", "2026-08-24") == ["2026-08-21", "2026-08-24"]


def test_complete_date_fetches_both_markets_sequentially(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    result = runner.run("2026-08-21", "2026-08-21", max_task_attempts=2)
    assert result["status"].startswith("READY_")
    assert provider.calls == [("KOSPI", "2026-08-21"), ("KOSDAQ", "2026-08-21")]
    assert result["aggregate"]["complete_date_count"] == 1


def test_both_empty_becomes_no_data(tmp_path):
    runner, _ = _runner(tmp_path, _Provider("both-empty"))
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["aggregate"]["no_data_date_count"] == 1
    assert result["aggregate"]["failed_date_count"] == 0


def test_asymmetric_empty_is_failed_and_partial(tmp_path):
    runner, _ = _runner(tmp_path, _Provider("asymmetric"))
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert "BLOCKED_COVERAGE" in result["blockers"]
    assert result["aggregate"]["partial_date_count"] == 1


def test_resume_skips_complete_and_no_data(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    provider.calls.clear()
    result = runner.run("2020-01-03", "2020-01-03", resume=True, max_task_attempts=2)
    assert provider.calls == []
    assert result["aggregate"]["complete_date_count"] == 1


def test_task_budget_pauses_without_crashing(tmp_path):
    runner, _ = _runner(tmp_path, _Provider())
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=1)
    assert result["status"] == "BACKFILL_PAUSED_TASK_BUDGET"


def test_quota_pause_preserves_existing_partitions(tmp_path):
    provider = _QuotaProvider()
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=1, global_safety_limit=1)
    store = KrxRawStockStore(tmp_path / "raw")
    runner = KrxHistoricalBackfillRunner(provider, store, quota)
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["status"] == "BACKFILL_PAUSED_QUOTA"
    assert store.get_manifest("KOSPI", "2020-01-03")["status"] == "FAILED"
