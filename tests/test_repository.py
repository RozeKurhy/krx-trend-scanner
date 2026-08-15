import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository import DEFAULT_OVERLAP_DAYS, MarketDataRepository


class FakeProvider:
    """실제 PyKRX를 호출하지 않는 테스트용 Provider. 호출 인자를 기록한다."""

    def __init__(self, response_fn):
        self.calls: list[tuple[str, str, str]] = []
        self._response_fn = response_fn

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        return self._response_fn(ticker, start, end)


def _make_df(start: str, periods: int, base_price: float) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="D")
    prices = [base_price + i for i in range(periods)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 5 for p in prices],
            "low": [p - 5 for p in prices],
            "close": [p + 1 for p in prices],
            "volume": [1000 + i for i in range(periods)],
            "trading_value": [1.0e8 + i for i in range(periods)],
        },
        index=index,
    )


def test_cache_miss_triggers_full_fetch(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    df = _make_df("2024-01-01", 10, base_price=100.0)
    provider = FakeProvider(lambda ticker, start, end: df.loc[start:end])
    repo = MarketDataRepository(provider, cache)

    result = repo.get_daily("005930", "2024-01-01", "2024-01-10")

    assert provider.calls == [("005930", "2024-01-01", "2024-01-10")]
    # Parquet은 DatetimeIndex의 freq 메타데이터를 보존하지 않는다(값 자체는 동일).
    pd.testing.assert_frame_equal(result, df, check_freq=False)
    pd.testing.assert_frame_equal(cache.load("005930"), df, check_freq=False)


def test_cache_hit_within_stable_range_skips_provider(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    seed = _make_df("2024-01-01", 90, base_price=100.0)  # 2024-01-01 ~ 2024-03-30
    cache.save("005930", seed)

    provider = FakeProvider(lambda ticker, start, end: pd.DataFrame())
    repo = MarketDataRepository(provider, cache)

    result = repo.get_daily("005930", "2024-01-10", "2024-01-20")

    assert provider.calls == []
    pd.testing.assert_frame_equal(
        result, seed.loc["2024-01-10":"2024-01-20"], check_freq=False
    )


def test_incremental_update_fetches_overlap_window_only(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    seed = _make_df("2024-01-01", 10, base_price=100.0)  # ~ 2024-01-10
    cache.save("005930", seed)

    fresh = _make_df("2024-01-06", 10, base_price=900.0)  # 2024-01-06 ~ 2024-01-15
    provider = FakeProvider(lambda ticker, start, end: fresh.loc[start:end])
    repo = MarketDataRepository(provider, cache)

    result = repo.get_daily("005930", "2024-01-01", "2024-01-15")

    expected_overlap_start = (
        seed.index.max() - pd.Timedelta(days=DEFAULT_OVERLAP_DAYS)
    ).strftime("%Y-%m-%d")
    assert provider.calls == [("005930", expected_overlap_start, "2024-01-15")]

    # 2024-01-06 이전(overlap 범위 밖)은 기존 캐시 값이 그대로 유지된다.
    assert result.loc["2024-01-01", "open"] == 100.0
    # overlap 범위(2024-01-06 이후)는 새 API 값으로 덮어써진다.
    assert result.loc["2024-01-06", "open"] == 900.0
    assert result.loc["2024-01-15", "open"] == 909.0
    assert not result.index.duplicated().any()


def test_new_api_value_overrides_cached_value_on_same_date(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    seed = _make_df("2024-01-01", 10, base_price=100.0)
    cache.save("005930", seed)

    overlap_date = seed.index.max() - pd.Timedelta(days=DEFAULT_OVERLAP_DAYS)
    fresh = _make_df(overlap_date.strftime("%Y-%m-%d"), 6, base_price=999.0)
    provider = FakeProvider(lambda ticker, start, end: fresh.loc[start:end])
    repo = MarketDataRepository(provider, cache)

    repo.get_daily("005930", "2024-01-01", "2024-01-10")
    updated_cache = cache.load("005930")

    assert updated_cache.loc[overlap_date, "open"] == 999.0
    assert len(updated_cache) == len(updated_cache.index.unique())


def test_requested_period_is_sliced_from_wider_cache(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    seed = _make_df("2024-01-01", 30, base_price=100.0)
    cache.save("005930", seed)

    provider = FakeProvider(lambda ticker, start, end: pd.DataFrame())
    repo = MarketDataRepository(provider, cache)

    result = repo.get_daily("005930", "2024-01-05", "2024-01-08")

    assert list(result.index) == list(pd.date_range("2024-01-05", "2024-01-08"))


def test_validator_error_propagates_and_cache_untouched(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    invalid_df = _make_df("2024-01-01", 3, base_price=100.0)
    invalid_df.loc[invalid_df.index[0], "open"] = -1.0  # 음수 가격 -> validator 실패

    provider = FakeProvider(lambda ticker, start, end: invalid_df)
    repo = MarketDataRepository(provider, cache)

    with pytest.raises(MarketDataError):
        repo.get_daily("005930", "2024-01-01", "2024-01-03")

    assert cache.load("005930") is None


def test_invalid_cached_data_raises_on_stable_cache_hit(tmp_path):
    cache = ParquetCache(base_dir=tmp_path)
    invalid_cached = _make_df("2024-01-01", 90, base_price=100.0)
    invalid_cached.loc[invalid_cached.index[0], "open"] = -1.0  # 음수 가격, 이미 저장된 상태

    # 검증 없이 직접 캐시에 심어서 "깨진 Parquet"를 재현한다.
    invalid_cached.to_parquet(tmp_path / "005930.parquet")

    provider = FakeProvider(lambda ticker, start, end: pd.DataFrame())
    repo = MarketDataRepository(provider, cache)

    # 요청 구간이 안정된 과거 캐시(overlap 범위 밖) 안에 있어 provider는 호출되지
    # 않는 stable cache hit 경로인데도, 캐시 자체가 깨져 있으면 실패해야 한다.
    with pytest.raises(MarketDataError):
        repo.get_daily("005930", "2024-01-10", "2024-01-20")

    assert provider.calls == []
