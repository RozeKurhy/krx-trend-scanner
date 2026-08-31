from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_provider import validate_raw_snapshot_frame
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    ANCILLARY_COLUMNS,
    DAILY_COLUMNS,
    RAW_DAILY_COLUMNS,
    MarketDataRepositoryV2,
    validate_repository_v2_daily,
)


DATES = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])


def _adjusted_frame(index=DATES, base: float = 50.0) -> pd.DataFrame:
    values = [base + offset for offset in range(len(index))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 5 for value in values],
            "low": [value - 5 for value in values],
            "close": [value + 1 for value in values],
        },
        index=index,
    )


def _raw_frame(index=DATES, ticker: str = "005930", base: int = 100) -> pd.DataFrame:
    rows = []
    for offset, date in enumerate(index):
        open_value = base + offset
        rows.append(
            {
                "date": date,
                "ticker": ticker,
                "open": open_value,
                "high": open_value + 5,
                "low": open_value - 5,
                "close": open_value + 1,
                "volume": 123456 + offset,
                "trading_value": 987654321 + offset,
                "market_cap": 111111111 + offset,
                "listed_shares": 222222222 + offset,
            }
        )
    return pd.DataFrame(rows, columns=list(RAW_COLUMNS))


def _repo(
    tmp_path,
    *,
    adjusted_index=DATES,
    raw_index=DATES,
    ticker="005930",
    adjusted=True,
    raw=True,
):
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    raw_store = KrxRawStockStore(tmp_path / "raw")
    if adjusted and ticker.isdigit():
        adjusted_store.save_full(ticker, _adjusted_frame(adjusted_index))
    if raw:
        market = "KOSDAQ" if ticker == "08537M" else "KOSPI"
        for date in raw_index:
            raw_store.save_snapshot(market, date, _raw_frame(pd.DatetimeIndex([date]), ticker=ticker), "fixture")
    return MarketDataRepositoryV2(adjusted_store, raw_store), adjusted_store, raw_store


def test_get_daily_uses_adjusted_ohlc_and_raw_ancillary(tmp_path):
    repo, _, _ = _repo(tmp_path)
    result = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert tuple(result.columns) == DAILY_COLUMNS
    assert result.loc[pd.Timestamp("2024-01-02"), "open"] == 50
    assert result.loc[pd.Timestamp("2024-01-02"), "high"] == 55
    assert result.loc[pd.Timestamp("2024-01-02"), "low"] == 45
    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 51
    assert result.loc[pd.Timestamp("2024-01-02"), "volume"] == 123456
    assert result.loc[pd.Timestamp("2024-01-02"), "trading_value"] == 987654321
    assert "market_cap" not in result.columns
    assert "listed_shares" not in result.columns


def test_raw_ohlc_is_separate_from_composed_adjusted_ohlc(tmp_path):
    repo, _, _ = _repo(tmp_path)
    raw = repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    daily = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert tuple(raw.columns) == RAW_DAILY_COLUMNS
    assert raw.loc[pd.Timestamp("2024-01-02"), "open"] == 100
    assert daily.loc[pd.Timestamp("2024-01-02"), "open"] == 50


def test_ancillary_excludes_ohlc_and_preserves_raw_values(tmp_path):
    repo, _, _ = _repo(tmp_path)
    ancillary = repo.get_daily_ancillary("005930", "2024-01-02", "2024-01-04")
    assert tuple(ancillary.columns) == ANCILLARY_COLUMNS
    assert ancillary.loc[pd.Timestamp("2024-01-02"), "market_cap"] == 111111111
    assert ancillary.loc[pd.Timestamp("2024-01-02"), "listed_shares"] == 222222222
    assert not {"open", "high", "low", "close"}.intersection(ancillary.columns)


def test_stock_snapshot_is_exactly_one_raw_row(tmp_path):
    repo, _, _ = _repo(tmp_path)
    snapshot = repo.get_stock_snapshot("005930", "2024-01-03")
    assert len(snapshot) == 1
    assert tuple(snapshot.columns) == RAW_DAILY_COLUMNS
    assert snapshot.index[0] == pd.Timestamp("2024-01-03")


def test_strict_session_mismatch_fails_instead_of_dropping_date(tmp_path):
    repo, _, _ = _repo(tmp_path, raw_index=pd.DatetimeIndex(["2024-01-02", "2024-01-04"]))
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_missing_raw_date_does_not_forward_fill(tmp_path):
    repo, _, _ = _repo(tmp_path, raw_index=pd.DatetimeIndex(["2024-01-02", "2024-01-04"]))
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_missing_adjusted_fails_but_raw_apis_work(tmp_path):
    repo, _, _ = _repo(tmp_path, adjusted=False)
    with pytest.raises(MarketDataError, match="ADJUSTED_MISSING"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert not repo.get_raw_daily("005930", "2024-01-02", "2024-01-04").empty


def test_missing_raw_fails(tmp_path):
    repo, _, _ = _repo(tmp_path, raw=False)
    with pytest.raises(MarketDataError, match="RAW_MISSING"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_both_empty_range_returns_typed_empty_daily_frame(tmp_path):
    repo, _, _ = _repo(tmp_path)
    result = repo.get_daily("005930", "2025-01-01", "2025-01-03")
    assert result.empty
    assert tuple(result.columns) == DAILY_COLUMNS
    assert isinstance(result.index, pd.DatetimeIndex)


def test_alphanumeric_raw_domain_is_preserved_and_adjusted_domain_is_closed(tmp_path):
    repo, _, _ = _repo(tmp_path, ticker="03473K")
    assert not repo.get_raw_daily("03473K", "2024-01-02", "2024-01-04").empty
    assert not repo.get_daily_ancillary("03473K", "2024-01-02", "2024-01-04").empty
    assert len(repo.get_stock_snapshot("03473K", "2024-01-02")) == 1
    with pytest.raises(MarketDataError, match="UNSUPPORTED_ADJUSTED_TICKER|DATA_UNAVAILABLE: ADJUSTED_MISSING"):
        repo.get_daily("03473K", "2024-01-02", "2024-01-04")


def test_invalid_raw_ticker_is_not_repaired(tmp_path):
    repo, _, _ = _repo(tmp_path)
    with pytest.raises(MarketDataError, match="RAW_TICKER_FORMAT_ERROR"):
        repo.get_raw_daily(" 005930", "2024-01-02", "2024-01-04")


def test_invalid_range_fails_closed(tmp_path):
    repo, _, _ = _repo(tmp_path)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_INVALID_RANGE"):
        repo.get_daily("005930", "2024-01-04", "2024-01-02")


def test_duplicate_date_from_raw_source_fails(tmp_path):
    repo, _, raw_store = _repo(tmp_path)
    original = raw_store.load_snapshot("KOSPI", "2024-01-02")
    duplicate = pd.concat([original, original.iloc[[0]]], ignore_index=True)
    # The immutable raw store rejects duplicates while saving, so inject a
    # source double to verify repository-level fail-closed behavior.
    class DuplicateRawStore:
        def load_ticker(self, ticker, start, end):
            frame = raw_store.load_ticker(ticker, start, end)
            return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)

    duplicate_repo = MarketDataRepositoryV2(repo._adjusted_price_store, DuplicateRawStore())
    with pytest.raises(MarketDataError, match="INVALID_REPOSITORY_V2_OUTPUT"):
        duplicate_repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")


def test_cross_market_conflict_is_not_silently_resolved(tmp_path):
    repo, _, _ = _repo(tmp_path)

    class ConflictRawStore:
        def load_ticker(self, ticker, start, end):
            raise MarketDataError("CROSS_MARKET_TICKER_CONFLICT")

    conflict_repo = MarketDataRepositoryV2(repo._adjusted_price_store, ConflictRawStore())
    with pytest.raises(MarketDataError, match="CROSS_MARKET_TICKER_CONFLICT"):
        conflict_repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")


def test_read_only_calls_do_not_change_store_files(tmp_path):
    repo, adjusted_store, raw_store = _repo(tmp_path)
    adjusted_files = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "adjusted").iterdir()
    }
    manifest = raw_store.manifest_path
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    repo.get_daily("005930", "2024-01-02", "2024-01-04")
    repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    repo.get_daily_ancillary("005930", "2024-01-02", "2024-01-04")
    repo.get_stock_snapshot("005930", "2024-01-02")
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "adjusted").iterdir()
    } == adjusted_files
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == manifest_hash


def test_timezone_naive_sorted_unique_output(tmp_path):
    repo, _, _ = _repo(tmp_path)
    result = repo.get_daily("005930", "2024-01-02T00:00:00+09:00", "2024-01-04T23:00:00+09:00")
    assert result.index.tz is None
    assert result.index.is_monotonic_increasing
    assert result.index.is_unique


def test_adjusted_store_is_not_widened_for_numeric_only_contract(tmp_path):
    repo, _, _ = _repo(tmp_path)
    with pytest.raises(MarketDataError, match="UNSUPPORTED_ADJUSTED_TICKER|DATA_UNAVAILABLE: ADJUSTED_MISSING"):
        repo.get_daily("08537M", "2024-01-02", "2024-01-04")


def _source_valid_zero_price_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"),
                "ticker": "005930",
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 10,
                "volume": 0,
                "trading_value": 25,
                "market_cap": 100,
                "listed_shares": 200,
            }
        ],
        columns=list(RAW_COLUMNS),
    )


def test_source_valid_zero_price_raw_row_is_repository_valid(tmp_path):
    source = _source_valid_zero_price_raw_frame()
    normalized = validate_raw_snapshot_frame(source, "2024-01-02")
    assert len(normalized) == 1

    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted_store.save_full(
        "005930",
        pd.DataFrame(
            {"open": [20.0], "high": [22.0], "low": [19.0], "close": [21.0]},
            index=pd.DatetimeIndex(["2024-01-02"]),
        ),
    )
    raw_store = KrxRawStockStore(tmp_path / "raw")
    raw_store.save_snapshot("KOSPI", "2024-01-02", source, "fixture")
    repo = MarketDataRepositoryV2(adjusted_store, raw_store)

    raw = repo.get_raw_daily("005930", "2024-01-02", "2024-01-02")
    ancillary = repo.get_daily_ancillary("005930", "2024-01-02", "2024-01-02")
    assert len(raw) == 1
    assert len(ancillary) == 1
    assert raw.loc[pd.Timestamp("2024-01-02"), "open"] == 0


def test_zero_price_raw_row_composes_with_adjusted_ohlc(tmp_path):
    source = _source_valid_zero_price_raw_frame()
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted_store.save_full(
        "005930",
        pd.DataFrame(
            {"open": [20.0], "high": [22.0], "low": [19.0], "close": [21.0]},
            index=pd.DatetimeIndex(["2024-01-02"]),
        ),
    )
    raw_store = KrxRawStockStore(tmp_path / "raw")
    raw_store.save_snapshot("KOSPI", "2024-01-02", source, "fixture")
    result = MarketDataRepositoryV2(adjusted_store, raw_store).get_daily(
        "005930", "2024-01-02", "2024-01-02"
    )
    assert result.loc[pd.Timestamp("2024-01-02"), "open"] == 20.0
    assert result.loc[pd.Timestamp("2024-01-02"), "close"] == 21.0
    assert result.loc[pd.Timestamp("2024-01-02"), "volume"] == 0
    assert result.loc[pd.Timestamp("2024-01-02"), "trading_value"] == 25


def test_source_native_adjusted_relation_anomaly_is_preserved_in_v2_history_view(tmp_path):
    adjusted = _adjusted_frame(pd.DatetimeIndex(["2024-01-02"]))
    adjusted.loc[pd.Timestamp("2024-01-02"), "high"] = 1.0
    adjusted.attrs.update(source_native_adjusted=True, analytic_invalid_ohlc_count=1)
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted_store.save_full("005930", adjusted)

    raw_store = KrxRawStockStore(tmp_path / "raw")
    raw_store.save_snapshot(
        "KOSPI",
        "2024-01-02",
        _raw_frame(pd.DatetimeIndex(["2024-01-02"])),
        "fixture",
    )
    repo = MarketDataRepositoryV2(adjusted_store, raw_store)

    result = repo.get_daily("005930", "2024-01-02", "2024-01-02")
    # No unapproved clamp is applied: the source-native anomaly is explicitly
    # nonusable for analytics and is excluded from the composed view.
    assert result.empty
    validate_repository_v2_daily(result)
    source = repo._adjusted_price_store.load_daily_source("005930", "2024-01-02", "2024-01-02")
    assert source.loc[pd.Timestamp("2024-01-02"), "high"] == 1.0
    validate_repository_v2_daily(
        pd.concat([source, raw_store.load_ticker("005930", "2024-01-02", "2024-01-02").set_index("date").loc[:, ["volume", "trading_value"]]], axis=1).loc[:, list(DAILY_COLUMNS)],
        source_history=True,
    )


def test_positive_invalid_raw_ohlc_still_fails(tmp_path):
    repo, _, raw_store = _repo(tmp_path)
    invalid = raw_store.load_ticker("005930", "2024-01-02", "2024-01-02").copy()
    invalid.loc[invalid.index[0], "high"] = 1

    class InvalidRawStore:
        def load_ticker(self, ticker, start, end):
            return invalid

    invalid_repo = MarketDataRepositoryV2(repo._adjusted_price_store, InvalidRawStore())
    with pytest.raises(MarketDataError, match="INVALID_REPOSITORY_V2_OUTPUT"):
        invalid_repo.get_raw_daily("005930", "2024-01-02", "2024-01-02")


def test_negative_raw_numeric_fails(tmp_path):
    repo, _, raw_store = _repo(tmp_path)
    invalid = raw_store.load_ticker("005930", "2024-01-02", "2024-01-02").copy()
    invalid.loc[invalid.index[0], "volume"] = -1

    class InvalidRawStore:
        def load_ticker(self, ticker, start, end):
            return invalid

    invalid_repo = MarketDataRepositoryV2(repo._adjusted_price_store, InvalidRawStore())
    with pytest.raises(MarketDataError, match="INVALID_REPOSITORY_V2_OUTPUT"):
        invalid_repo.get_raw_daily("005930", "2024-01-02", "2024-01-02")


def _projection_raw_row(date: str, *, placeholder: bool = False, **overrides) -> dict:
    if placeholder:
        values = {
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 100,
            "volume": 0,
            "trading_value": 0,
        }
    else:
        values = {
            "open": 100,
            "high": 105,
            "low": 95,
            "close": 101,
            "volume": 10,
            "trading_value": 1000,
        }
    values.update(overrides)
    return {
        "date": pd.Timestamp(date),
        "ticker": "005930",
        **values,
        "market_cap": 10000,
        "listed_shares": 20000,
    }


def _projection_repo(tmp_path, adjusted_dates: list[str], raw_rows: list[dict]):
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    raw_store = KrxRawStockStore(tmp_path / "raw")
    adjusted_index = pd.DatetimeIndex(adjusted_dates)
    adjusted_store.save_full("005930", _adjusted_frame(adjusted_index))
    for row in raw_rows:
        raw_store.save_snapshot(
            "KOSPI",
            row["date"].strftime("%Y-%m-%d"),
            pd.DataFrame([row], columns=list(RAW_COLUMNS)),
            "fixture",
        )
    return MarketDataRepositoryV2(adjusted_store, raw_store)


def test_strict_placeholder_projects_only_from_composed_daily_and_raw_apis_preserve_it(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", placeholder=True),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-04"], rows)

    daily = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert list(daily.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-04")]
    raw = repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    ancillary = repo.get_daily_ancillary("005930", "2024-01-02", "2024-01-04")
    snapshot = repo.get_stock_snapshot("005930", "2024-01-03")
    assert pd.Timestamp("2024-01-03") in raw.index
    assert raw.loc[pd.Timestamp("2024-01-03"), "close"] == 100
    assert ancillary.loc[pd.Timestamp("2024-01-03"), "market_cap"] == 10000
    assert snapshot.loc[pd.Timestamp("2024-01-03"), "volume"] == 0


def test_active_raw_only_session_fails_closed(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", volume=0),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-04"], rows)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_volume_zero_only_raw_only_session_is_not_removed(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row(
            "2024-01-03", open=100, high=105, low=95, close=101, volume=0, trading_value=0
        ),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-04"], rows)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_trading_value_positive_raw_only_session_is_not_removed(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", placeholder=True, trading_value=1),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-04"], rows)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_adjusted_only_session_fails_closed(tmp_path):
    rows = [_projection_raw_row("2024-01-02"), _projection_raw_row("2024-01-04")]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-04"], rows)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-04")


def test_exact_session_sets_project_without_drops(tmp_path):
    rows = [_projection_raw_row("2024-01-02"), _projection_raw_row("2024-01-04")]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-04"], rows)
    result = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert len(result) == 2


def test_multiple_raw_only_placeholders_are_projected_explicitly(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", placeholder=True),
        _projection_raw_row("2024-01-04", placeholder=True),
        _projection_raw_row("2024-01-05"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-05"], rows)
    result = repo.get_daily("005930", "2024-01-02", "2024-01-05")
    assert len(result) == 2


def test_mixed_placeholder_and_active_raw_only_sessions_fail_closed(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", placeholder=True),
        _projection_raw_row("2024-01-04", close=101, volume=1, trading_value=1000),
        _projection_raw_row("2024-01-05"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-05"], rows)
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        repo.get_daily("005930", "2024-01-02", "2024-01-05")


def test_shared_date_placeholder_is_explicitly_excluded_from_analytic_view(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row("2024-01-03", placeholder=True),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-04"], rows)
    daily = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert list(daily.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-04")]
    raw = repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    assert pd.Timestamp("2024-01-03") in raw.index
    assert raw.loc[pd.Timestamp("2024-01-03"), "open"] == 0


def test_known_adjusted_gap_is_explicitly_excluded(tmp_path):
    row = _projection_raw_row("2012-07-16", open=100, high=105, low=95, close=101, volume=41680, trading_value=138215850)
    # The fixture ticker is changed to the adjudicated 000360 identity.
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted_000360")
    adjusted_store.save_full("000360", _adjusted_frame(pd.DatetimeIndex(["2012-07-15"])))
    raw_store = KrxRawStockStore(tmp_path / "raw_000360")
    row["ticker"] = "000360"
    prior = _projection_raw_row("2012-07-15")
    prior["ticker"] = "000360"
    raw_store.save_snapshot("KOSPI", "2012-07-15", pd.DataFrame([prior], columns=list(RAW_COLUMNS)), "fixture")
    raw_store.save_snapshot("KOSPI", "2012-07-16", pd.DataFrame([row], columns=list(RAW_COLUMNS)), "fixture")
    daily = MarketDataRepositoryV2(adjusted_store, raw_store).get_daily("000360", "2012-07-15", "2012-07-16")
    assert list(daily.index) == [pd.Timestamp("2012-07-15")]
    raw = MarketDataRepositoryV2(adjusted_store, raw_store).get_raw_daily("000360", "2012-07-16", "2012-07-16")
    assert len(raw) == 1


def test_shared_date_normal_zero_volume_row_is_not_a_placeholder_conflict(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row(
            "2024-01-03",
            open=100,
            high=105,
            low=95,
            close=101,
            volume=0,
            trading_value=0,
        ),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-04"], rows)
    daily = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert len(daily) == 3
    assert daily.loc[pd.Timestamp("2024-01-03"), "volume"] == 0


def test_shared_date_partial_phantom_is_not_placeholder_conflict(tmp_path):
    rows = [
        _projection_raw_row("2024-01-02"),
        _projection_raw_row(
            "2024-01-03",
            open=0,
            high=0,
            low=0,
            close=101,
            volume=0,
            trading_value=1,
        ),
        _projection_raw_row("2024-01-04"),
    ]
    repo = _projection_repo(tmp_path, ["2024-01-02", "2024-01-03", "2024-01-04"], rows)
    daily = repo.get_daily("005930", "2024-01-02", "2024-01-04")
    assert len(daily) == 3


def test_indexed_raw_reader_validates_once_and_reuses_ticker_locations(tmp_path):
    repo, _, raw_store = _repo(tmp_path)
    expected = raw_store.load_ticker("005930", "2024-01-02", "2024-01-04")
    # The first repository read builds one authority-validating index.  It
    # does not perform a full partition scan for each subsequent ticker read.
    actual = repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    stats_after_first = repo.raw_reader_stats
    again = repo.get_raw_daily("005930", "2024-01-02", "2024-01-04")
    stats_after_second = repo.raw_reader_stats
    assert list(actual.index) == list(pd.to_datetime(expected["date"]))
    assert actual["close"].tolist() == expected["close"].tolist()
    assert again.equals(actual)
    assert stats_after_first["full_store_scans"] == 1
    assert stats_after_first["full_store_scans_per_ticker"] == 0
    assert stats_after_second["full_store_scans"] == 1
    assert stats_after_second["index_lookups"] == 2


def test_analytic_view_is_distinct_from_lossless_source_history(tmp_path):
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    source = _adjusted_frame(pd.DatetimeIndex(["2024-01-02"]))
    source.loc[pd.Timestamp("2024-01-02"), "high"] = 1.0
    source.attrs["source_native_adjusted"] = True
    adjusted_store.save_full("005930", source)
    raw_store = KrxRawStockStore(tmp_path / "raw")
    raw_store.save_snapshot("KOSPI", "2024-01-02", _raw_frame(pd.DatetimeIndex(["2024-01-02"])), "fixture")
    repo = MarketDataRepositoryV2(adjusted_store, raw_store)
    assert repo.get_daily("005930", "2024-01-02", "2024-01-02").empty
    assert repo._adjusted_price_store.load_daily_source("005930", "2024-01-02", "2024-01-02").loc[pd.Timestamp("2024-01-02"), "high"] == 1.0
