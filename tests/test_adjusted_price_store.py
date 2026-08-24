from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_provider import ADJUSTED_OHLC_COLUMNS
from trend_scanner.data.adjusted_price_store import (
    PHYSICAL_COLUMNS,
    SCHEMA_VERSION,
    STORE_VERSION,
    AdjustedPriceStore,
)
from trend_scanner.data.errors import MarketDataError


def _frame(start: str = "2024-01-02", periods: int = 3, base: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="D")
    close = [base + i + 2 for i in range(periods)]
    return pd.DataFrame(
        {
            "open": [base + i for i in range(periods)],
            "high": [base + i + 5 for i in range(periods)],
            "low": [base + i - 1 for i in range(periods)],
            "close": close,
        },
        index=index,
    )


def test_store_roundtrip_exact(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    source = _frame()
    store.save_full("5930", source, {"requested_start": "2024-01-02", "requested_end": "2024-01-04"})
    loaded = store.load_daily("005930")
    pd.testing.assert_frame_equal(loaded, source.astype("float64"), check_freq=False)
    assert store.exists("005930")


def test_physical_schema_exact(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    physical = pd.read_parquet(tmp_path / "005930.parquet")
    assert tuple(physical.columns) == PHYSICAL_COLUMNS
    assert tuple(physical["ticker"].unique()) == ("005930",)


def test_store_contains_no_ancillary_columns(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    assert set(pd.read_parquet(tmp_path / "005930.parquet").columns) == set(PHYSICAL_COLUMNS)
    assert not {"volume", "trading_value", "market_cap", "listed_shares"}.intersection(PHYSICAL_COLUMNS)


def test_save_rejects_empty_frame(tmp_path):
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", _frame(periods=0))


def test_save_rejects_mixed_ticker(tmp_path):
    frame = _frame().assign(ticker=["005930", "000660", "005930"])
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_save_rejects_ticker_mismatch(tmp_path):
    frame = _frame().assign(ticker=["000660"] * 3)
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_save_rejects_duplicate_date(tmp_path):
    frame = _frame()
    frame.index = pd.DatetimeIndex(["2024-01-02", "2024-01-02", "2024-01-04"])
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_save_rejects_unsorted_date(tmp_path):
    frame = _frame().iloc[[1, 0, 2]]
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_save_rejects_nan(tmp_path):
    frame = _frame()
    frame.iloc[0, 0] = float("nan")
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_save_rejects_invalid_ohlc_relation(tmp_path):
    frame = _frame()
    frame.iloc[0, 1] = frame.iloc[0, 0] - 2
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path).save_full("005930", frame)


def test_metadata_written(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    metadata = json.loads((tmp_path / "005930.meta.json").read_text())
    assert set(
        (
            "schema_version", "store_version", "ticker", "source_name", "source_endpoint",
            "source_semantics", "authority_type", "requested_start", "requested_end",
            "actual_date_min", "actual_date_max", "row_count", "ticker_count", "generated_at",
            "last_success_at", "content_sha256",
        )
    ).issubset(metadata)
    assert metadata["ticker"] == "005930"


def test_metadata_schema_version(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    metadata = store.load_metadata("005930")
    assert metadata["schema_version"] == SCHEMA_VERSION
    assert metadata["store_version"] == STORE_VERSION


def test_metadata_hash_matches_parquet(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    metadata = store.load_metadata("005930")
    import hashlib

    digest = hashlib.sha256((tmp_path / "005930.parquet").read_bytes()).hexdigest()
    assert metadata["content_sha256"] == digest


def test_load_rejects_hash_mismatch(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    path = tmp_path / "005930.meta.json"
    metadata = json.loads(path.read_text())
    metadata["content_sha256"] = "0" * 64
    path.write_text(json.dumps(metadata))
    with pytest.raises(MarketDataError, match="hash"):
        store.load_daily("005930")


def test_load_rejects_missing_metadata(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    (tmp_path / "005930.meta.json").unlink()
    with pytest.raises(MarketDataError, match="metadata"):
        store.load_daily("005930")


def test_failed_save_preserves_previous_valid_file(tmp_path, monkeypatch):
    store = AdjustedPriceStore(tmp_path)
    original = _frame(base=100)
    store.save_full("005930", original)
    parquet_before = (tmp_path / "005930.parquet").read_bytes()
    metadata_before = (tmp_path / "005930.meta.json").read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("synthetic temp parquet failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_write)
    with pytest.raises(OSError, match="synthetic"):
        store.save_full("005930", _frame(base=900))
    assert (tmp_path / "005930.parquet").read_bytes() == parquet_before
    assert (tmp_path / "005930.meta.json").read_bytes() == metadata_before
    pd.testing.assert_frame_equal(store.load_daily("005930"), original.astype("float64"), check_freq=False)


def test_full_replace_changes_entire_ticker_snapshot(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    first = _frame(start="2024-01-02", periods=2, base=100)
    second = _frame(start="2024-02-01", periods=3, base=900)
    store.save_full("005930", first)
    store.save_full("005930", second)
    pd.testing.assert_frame_equal(store.load_daily("005930"), second.astype("float64"), check_freq=False)


def test_latest_date(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    source = _frame()
    store.save_full("005930", source)
    assert store.latest_date("005930") == source.index.max()
    assert AdjustedPriceStore(tmp_path / "missing").latest_date("005930") is None


def test_list_cached_tickers(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    store.save_full("000660", _frame(base=200))
    assert store.list_cached_tickers() == ["000660", "005930"]


def test_load_daily_range_slice(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    source = _frame()
    store.save_full("005930", source)
    result = store.load_daily("005930", "2024-01-03", "2024-01-03")
    assert list(result.index) == [pd.Timestamp("2024-01-03")]


def test_metadata_has_no_credential_markers(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    text = (tmp_path / "005930.meta.json").read_text()
    assert "KRX_OPEN_API_AUTH_KEY" not in text
    assert "KRX_ID" not in text
    assert "KRX_PW" not in text


def _assert_reserved_metadata_rejected(tmp_path, field: str):
    with pytest.raises(MarketDataError, match="metadata_context"):
        AdjustedPriceStore(tmp_path).save_full("005930", _frame(), {field: "caller-override"})


def test_metadata_context_cannot_override_schema_version(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "schema_version")


def test_metadata_context_cannot_override_store_version(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "store_version")


def test_metadata_context_cannot_override_ticker(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "ticker")


def test_metadata_context_cannot_override_source_name(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "source_name")


def test_metadata_context_cannot_override_source_endpoint(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "source_endpoint")


def test_metadata_context_cannot_override_source_semantics(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "source_semantics")


def test_metadata_context_cannot_override_authority_type(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "authority_type")


def test_metadata_context_cannot_override_actual_date_bounds(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "actual_date_min")
    _assert_reserved_metadata_rejected(tmp_path, "actual_date_max")


def test_metadata_context_cannot_override_row_count(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "row_count")


def test_metadata_context_cannot_override_ticker_count(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "ticker_count")


def test_metadata_context_cannot_override_generated_at(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "generated_at")


def test_metadata_context_cannot_override_last_success_at(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "last_success_at")


def test_metadata_context_cannot_override_content_sha256(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "content_sha256")


def test_metadata_context_allows_requested_bounds(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full(
        "005930",
        _frame(),
        {"requested_start": "2024-01-01", "requested_end": "2024-01-05"},
    )
    metadata = store.load_metadata("005930")
    assert metadata["requested_start"] == "2024-01-01"
    assert metadata["requested_end"] == "2024-01-05"


def test_metadata_context_rejects_unknown_field(tmp_path):
    _assert_reserved_metadata_rejected(tmp_path, "unregistered_context")


def test_metadata_context_rejects_reversed_requested_bounds(tmp_path):
    with pytest.raises(MarketDataError, match="requested_start"):
        AdjustedPriceStore(tmp_path).save_full(
            "005930",
            _frame(),
            {"requested_start": "2024-01-05", "requested_end": "2024-01-01"},
        )


def test_metadata_context_cannot_override_source_endpoint_after_save(tmp_path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    path = tmp_path / "005930.meta.json"
    metadata = json.loads(path.read_text())
    metadata["source_endpoint"] = "unexpected.endpoint"
    path.write_text(json.dumps(metadata))
    with pytest.raises(MarketDataError, match="source_endpoint"):
        store.load_daily("005930")
