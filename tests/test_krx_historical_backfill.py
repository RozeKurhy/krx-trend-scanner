from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner, candidate_dates
from scripts.validate_krx_historical_backfill_v01 import _coverage


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


def test_recent_empty_is_not_checkpointed_and_general_resume_retries(tmp_path):
    provider = _Provider("both-empty")
    runner, _ = _runner(tmp_path, provider)
    first = runner.run("2026-08-24", "2026-08-24", max_task_attempts=2)
    assert first["recent_empty_unfinalized_count"] == 1
    assert runner.store.get_manifest("KOSPI", "2026-08-24") is None
    assert runner.store.get_manifest("KOSDAQ", "2026-08-24") is None
    provider.calls.clear()
    runner.run("2026-08-24", "2026-08-24", resume=True, max_task_attempts=2)
    assert provider.calls == [("KOSPI", "2026-08-24"), ("KOSDAQ", "2026-08-24")]


def test_partial_resume_fetches_only_missing_market(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    runner.store.save_snapshot("KOSPI", "2020-01-03", _frame("2020-01-03", "005930"), "/sto/stk_bydd_trd")
    provider.calls.clear()
    result = runner.run("2020-01-03", "2020-01-03", resume=True, max_task_attempts=1)
    assert provider.calls == [("KOSDAQ", "2020-01-03")]
    assert result["aggregate"]["complete_date_count"] == 1


def test_cross_market_conflict_is_counted(tmp_path):
    class _ConflictProvider(_Provider):
        def fetch_market_snapshot(self, market, day):
            self.calls.append((market, day))
            return _frame(day, "005930")

    runner, _ = _runner(tmp_path, _ConflictProvider())
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["aggregate"]["cross_market_ticker_conflict_count"] == 1


def test_coverage_gate_does_not_accept_one_complete_date(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_snapshot("KOSPI", "2026-08-21", _frame("2026-08-21", "005930"), "/sto/stk_bydd_trd")
    store.save_snapshot("KOSDAQ", "2026-08-21", _frame("2026-08-21", "000660"), "/sto/ksq_bydd_trd")
    coverage = _coverage(store, "2026-08-17", "2026-08-21")
    assert coverage["candidate_date_count"] == 5
    assert coverage["complete_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 4


def test_coverage_gate_accepts_complete_and_finalized_no_data_pairs(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    for day in ("2020-01-02", "2020-01-03", "2020-01-06"):
        if day == "2020-01-03":
            empty = _frame(day, "005930").iloc[0:0].copy()
            store.save_snapshot("KOSPI", day, empty, "/sto/stk_bydd_trd")
            store.save_snapshot("KOSDAQ", day, empty, "/sto/ksq_bydd_trd")
        else:
            store.save_snapshot("KOSPI", day, _frame(day, "005930"), "/sto/stk_bydd_trd")
            store.save_snapshot("KOSDAQ", day, _frame(day, "000660"), "/sto/ksq_bydd_trd")
    coverage = _coverage(store, "2020-01-02", "2020-01-06")
    assert coverage["candidate_date_count"] == 3
    assert coverage["complete_date_count"] == 2
    assert coverage["finalized_no_data_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 0


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
