import pandas as pd

from trend_scanner.data.cache import ParquetCache


def _sample_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [1000, 1100, 1200],
            "trading_value": [1.0e8, 1.1e8, 1.2e8],
        },
        index=index,
    )


def test_load_missing_ticker_returns_none(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    assert cache.load("005930") is None


def test_save_then_load_roundtrip(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    df = _sample_df()

    cache.save("005930", df)
    loaded = cache.load("005930")

    # Parquet은 DatetimeIndex의 freq 메타데이터를 보존하지 않는다(값 자체는 동일).
    pd.testing.assert_frame_equal(loaded, df, check_freq=False)


def test_save_creates_parquet_file_per_ticker(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    cache.save("005930", _sample_df())

    assert (tmp_path / "005930.parquet").exists()


def test_latest_date_missing_ticker_returns_none(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    assert cache.latest_date("005930") is None


def test_latest_date_returns_max_index(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    df = _sample_df()
    cache.save("005930", df)

    assert cache.latest_date("005930") == df.index.max()
