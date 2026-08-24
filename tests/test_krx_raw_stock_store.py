from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


def _frame(date="2026-08-21", ticker="005930", close=105):
    return pd.DataFrame(
        [{"date": pd.Timestamp(date), "ticker": ticker, "open": 100, "high": 110, "low": 90, "close": close, "volume": 1000, "trading_value": 2000, "market_cap": 3000, "listed_shares": 4000}],
        columns=["date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"],
    )


def test_save_load_schema_partition_and_manifest(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    result = store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")
    assert result.status == "COMPLETE"
    assert result.operation == "SAVED"
    path = tmp_path / "raw" / "market=KOSPI" / "year=2026" / "2026-08-21.parquet"
    assert path.exists()
    physical = pd.read_parquet(path)
    assert tuple(physical.columns) == ("date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares")
    loaded = store.load_snapshot("KOSPI", "2026-08-21")
    pd.testing.assert_frame_equal(loaded, _frame(), check_dtype=False)
    manifest = store.get_manifest("KOSPI", "2026-08-21")
    assert manifest["status"] == "COMPLETE"
    assert manifest["content_sha256"] == result.content_sha256
    assert manifest["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert store.verify_snapshot("KOSPI", "2026-08-21")["valid"] is True


def test_same_content_is_idempotent_and_different_content_conflicts(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    first = store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")
    second = store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")
    assert first.file_sha256 == second.file_sha256
    assert second.operation == "IDEMPOTENT_NOOP"
    with pytest.raises(MarketDataError, match="RAW_PARTITION_CONFLICT"):
        store.save_snapshot("KOSPI", "2026-08-21", _frame(close=106), "/sto/stk_bydd_trd")


def test_no_data_partition_is_manifest_only_and_idempotent(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    empty = _frame().iloc[0:0].copy()
    result = store.save_snapshot("KOSPI", "2026-08-21", empty, "/sto/stk_bydd_trd")
    assert result.status == "NO_DATA"
    assert store.exists("KOSPI", "2026-08-21")
    assert store.load_snapshot("KOSPI", "2026-08-21").empty
    assert store.save_snapshot("KOSPI", "2026-08-21", empty, "/sto/stk_bydd_trd").operation == "IDEMPOTENT_NOOP"
    with pytest.raises(MarketDataError, match="RAW_PARTITION_CONFLICT"):
        store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")


def test_missing_file_and_hash_corruption_are_detected(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")
    path = tmp_path / "raw" / "market=KOSPI" / "year=2026" / "2026-08-21.parquet"
    path.write_bytes(path.read_bytes() + b"corrupt")
    assert store.verify_snapshot("KOSPI", "2026-08-21")["valid"] is False
    with pytest.raises(MarketDataError, match="RAW_PARTITION_INTEGRITY"):
        store.load_snapshot("KOSPI", "2026-08-21")


def test_load_ticker_sorts_dates_and_detects_cross_market_conflict(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_snapshot("KOSPI", "2026-08-21", _frame(date="2026-08-21"), "/sto/stk_bydd_trd")
    store.save_snapshot("KOSPI", "2026-08-20", _frame(date="2026-08-20"), "/sto/stk_bydd_trd")
    result = store.load_ticker("005930", "2026-08-20", "2026-08-21")
    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-08-20", "2026-08-21"]
    store.save_snapshot("KOSDAQ", "2026-08-20", _frame(date="2026-08-20"), "/sto/ksq_bydd_trd")
    with pytest.raises(MarketDataError, match="CROSS_MARKET_TICKER_CONFLICT"):
        store.load_ticker("005930", "2026-08-20", "2026-08-20")


def test_failed_manifest_can_be_retried_without_overwriting_complete(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_failure("KOSPI", "2026-08-21", "/sto/stk_bydd_trd", "TEMPORARY", "retry")
    assert store.get_manifest("KOSPI", "2026-08-21")["status"] == "FAILED"
    store.save_snapshot("KOSPI", "2026-08-21", _frame(), "/sto/stk_bydd_trd")
    assert store.get_manifest("KOSPI", "2026-08-21")["status"] == "COMPLETE"
