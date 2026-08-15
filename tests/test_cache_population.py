"""KRX Official Common Stock Cache Population Service Tests.

포괄적 테스트 스위트 (20개 테스트):
1. test_missing_cache_create
2. test_existing_cache_incremental_update
3. test_fresh_cache_skip
4. test_idempotency
5. test_provider_failure_isolation
6. test_empty_response
7. test_invalid_schema
8. test_future_date
9. test_duplicate_merge
10. test_sorted_output
11. test_resume
12. test_short_history_new_listing
13. test_orphan_cache_preservation
14. test_dry_run
15. test_atomic_write_success (신규)
16. test_atomic_write_failure_preserves_existing_cache (신규)
17. test_temp_cleanup_on_failure (신규)
18. test_common_coverage_denominator (신규)
19. test_local_official_common_provenance_scope (신규)
20. test_subset_target_coverage_vs_global_coverage (신규)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.provider import MarketDataProvider
from trend_scanner.universe.cache_population import (
    CachePopulationRecord,
    CachePopulationStatus,
    populate_common_stock_cache,
    populate_single_ticker,
)
from trend_scanner.universe.models import AssetType, MarketType, UniverseSecurity


def _make_mock_daily(
    dates: pd.DatetimeIndex,
    start_val: float = 10000.0,
    step: float = 10.0,
) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "open": [start_val + i * step for i in range(n)],
            "high": [start_val + 500.0 + i * step for i in range(n)],
            "low": [start_val - 500.0 + i * step for i in range(n)],
            "close": [start_val + 200.0 + i * step for i in range(n)],
            "volume": [100000 for _ in range(n)],
            "trading_value": [1000000000.0 for _ in range(n)],
        },
        index=dates,
    )


class FakeProvider(MarketDataProvider):
    """결정론적 테스트용 Fake MarketDataProvider."""

    def __init__(self, data_map: dict[str, pd.DataFrame] | None = None, ignore_range: bool = False):
        self._data_map = data_map or {}
        self.ignore_range = ignore_range
        self.call_count: dict[str, int] = {}

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.call_count[ticker] = self.call_count.get(ticker, 0) + 1
        if ticker in self._data_map:
            df = self._data_map[ticker]
            if df.empty:
                return pd.DataFrame()
            if self.ignore_range:
                return df.copy()
            return df.loc[(df.index >= start) & (df.index <= end)].copy()
        # 기본 5년 일봉 생성 (2021-08 ~ 2026-08)
        dates = pd.date_range(start=start, end=end, freq="B")
        return _make_mock_daily(dates)


def test_missing_cache_create(tmp_path: Path):
    """1. 캐시가 없을 때 valid data fetch 시 CREATED 생성 및 unique/sorted 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-08-14", "2026-08-14", freq="B")
    provider = FakeProvider({"005930": _make_mock_daily(dates)})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.CREATED
    assert rec.cache_existed_before is False
    assert cache.load("005930") is not None
    loaded = cache.load("005930")
    assert loaded.index.is_monotonic_increasing
    assert loaded.index.is_unique
    assert len(loaded) == len(dates)


def test_existing_cache_incremental_update(tmp_path: Path):
    """2. 기존 캐시 존재 시 신규 row append 및 UPDATED 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    old_dates = pd.date_range("2021-08-14", "2026-08-01", freq="B")
    cache.save("005930", _make_mock_daily(old_dates))

    all_dates = pd.date_range("2021-08-14", "2026-08-14", freq="B")
    provider = FakeProvider({"005930": _make_mock_daily(all_dates)})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.UPDATED
    assert rec.cache_existed_before is True
    loaded = cache.load("005930")
    assert loaded.index.max() == pd.Timestamp("2026-08-14")
    assert len(loaded) == len(all_dates)


def test_fresh_cache_skip(tmp_path: Path):
    """3. 캐시가 이미 최신이고 충분한 히스토리가 있을 때 SKIPPED_FRESH 및 fetch 호출 생략 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2020-01-01", "2026-08-14", freq="B")
    cache.save("005930", _make_mock_daily(dates))

    provider = FakeProvider({"005930": _make_mock_daily(dates)})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.SKIPPED_FRESH
    assert provider.call_count.get("005930", 0) == 0


def test_idempotency(tmp_path: Path):
    """4. 동일 population 두 번 실행 시 두 번째는 모두 SKIPPED_FRESH 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2020-01-01", "2026-08-14", freq="B")
    provider = FakeProvider({"005930": _make_mock_daily(dates)})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec1 = populate_single_ticker(sec, provider, cache, "2026-08-14")
    assert rec1.status == CachePopulationStatus.CREATED

    rec2 = populate_single_ticker(sec, provider, cache, "2026-08-14")
    assert rec2.status == CachePopulationStatus.SKIPPED_FRESH
    assert rec2.total_row_count_after == rec1.total_row_count_after


def test_provider_failure_isolation(tmp_path: Path):
    """5. ticker B에서 provider exception 발생 시 A/C는 정상 처리되고 전체 loop 중단되지 않음."""
    cache = ParquetCache(base_dir=tmp_path)
    provider = FakeProvider()

    orig_load = provider.load_daily

    def _mock_load(t, s, e):
        if t == "000660":
            raise RuntimeError("KRX Network Error on 000660")
        return orig_load(t, s, e)

    provider.load_daily = _mock_load

    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
        UniverseSecurity(ticker="035420", name="NAVER", market=MarketType.KOSPI),
    ]

    summary = populate_common_stock_cache(
        cache=cache,
        provider=provider,
        reference_market_date="2026-08-14",
        universe_securities=univ,
    )

    assert summary.created_count == 2
    assert summary.failed_count == 1
    assert len(summary.failed_records) == 1
    assert summary.failed_records[0].ticker == "000660"
    assert "RuntimeError" in summary.failed_records[0].error_type
    assert cache.load("005930") is not None
    assert cache.load("035420") is not None


def test_empty_response(tmp_path: Path):
    """6. provider가 빈 DataFrame 반환 시 FAILED, 기존 캐시 보존 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    old_dates = pd.date_range("2021-01-01", "2026-08-01", freq="B")
    cache.save("005930", _make_mock_daily(old_dates))

    provider = FakeProvider({"005930": pd.DataFrame()})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.FAILED
    assert "EMPTY_RESPONSE" in rec.error_message
    loaded = cache.load("005930")
    assert len(loaded) == len(old_dates)


def test_invalid_schema(tmp_path: Path):
    """7. provider가 필수 column 누락 DataFrame 반환 시 write 금지 및 FAILED."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-01-01", "2026-08-14", freq="B")
    broken_df = pd.DataFrame({"close": [10000.0] * len(dates)}, index=dates)

    provider = FakeProvider({"005930": broken_df})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.FAILED
    assert cache.load("005930") is None


def test_future_date(tmp_path: Path):
    """8. reference_date보다 미래 row 포함 시 validation failure 및 write 금지."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-01-01", "2026-08-20", freq="B")
    provider = FakeProvider({"005930": _make_mock_daily(dates)}, ignore_range=True)

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.FAILED
    assert rec.error_type == "FutureDateError"
    assert cache.load("005930") is None


def test_duplicate_merge(tmp_path: Path):
    """9. overlap 데이터 merge 시 duplicate date 제거 및 신규 row 우선 적용."""
    cache = ParquetCache(base_dir=tmp_path)
    old_dates = pd.date_range("2026-08-01", "2026-08-10", freq="B")
    old_df = _make_mock_daily(old_dates, start_val=10000.0)
    cache.save("005930", old_df)

    new_dates = pd.date_range("2026-08-05", "2026-08-14", freq="B")
    new_df = _make_mock_daily(new_dates, start_val=20000.0)
    provider = FakeProvider({"005930": new_df})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.UPDATED
    loaded = cache.load("005930")
    assert loaded.index.is_unique
    assert loaded.loc["2026-08-05", "open"] >= 20000.0


def test_sorted_output(tmp_path: Path):
    """10. provider가 unsorted rows 반환해도 최종 cache가 date ascending으로 정렬됨."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-01-01", "2026-08-14", freq="B")
    df = _make_mock_daily(dates)
    unsorted_df = df.sample(frac=1.0, random_state=42)

    provider = FakeProvider({"005930": unsorted_df})

    sec = UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.CREATED
    loaded = cache.load("005930")
    assert loaded.index.is_monotonic_increasing


def test_resume(tmp_path: Path):
    """11. 1차 실행에서 일부 실패 후 2차 실행 시 fresh skip & 실패 ticker 재시도."""
    cache = ParquetCache(base_dir=tmp_path)
    provider = FakeProvider()

    provider.load_daily = lambda t, s, e: (_make_mock_daily(pd.date_range(s, e, freq="B")) if t != "000660" else (_ for _ in ()).throw(RuntimeError("Network Err")))

    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
    ]

    s1 = populate_common_stock_cache(cache, provider, "2026-08-14", universe_securities=univ)
    assert s1.created_count == 1
    assert s1.failed_count == 1

    provider2 = FakeProvider()
    s2 = populate_common_stock_cache(cache, provider2, "2026-08-14", universe_securities=univ)
    assert s2.skipped_fresh_count == 1
    assert s2.created_count == 1
    assert s2.failed_count == 0


def test_short_history_new_listing(tmp_path: Path):
    """12. 42개월 미만 신규 상장주여도 population success 및 6M momentum history 미충족 정상 처리."""
    cache = ParquetCache(base_dir=tmp_path)
    short_dates = pd.date_range("2025-01-01", "2026-08-14", freq="B")
    provider = FakeProvider({"123456": _make_mock_daily(short_dates)})

    sec = UniverseSecurity(ticker="123456", name="신규상장기업", market=MarketType.KOSPI)
    rec = populate_single_ticker(sec, provider, cache, "2026-08-14")

    assert rec.status == CachePopulationStatus.CREATED
    assert rec.completed_month_count_after < 42
    assert cache.load("123456") is not None


def test_orphan_cache_preservation(tmp_path: Path):
    """13. official universe 밖 orphan 캐시 파일이 삭제되지 않고 보존됨."""
    cache = ParquetCache(base_dir=tmp_path)
    cache.save("999999", _make_mock_daily(pd.date_range("2021-01-01", "2026-08-14", freq="B")))

    univ = [UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI)]
    provider = FakeProvider()

    summary = populate_common_stock_cache(cache, provider, "2026-08-14", universe_securities=univ)
    assert summary.orphan_cache_count_after == 1
    assert cache.load("999999") is not None


def test_dry_run(tmp_path: Path):
    """14. dry-run 실행 시 network fetch/cache write 없이 plan summary 생성."""
    cache = ParquetCache(base_dir=tmp_path)
    provider = FakeProvider()

    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
    ]

    summary = populate_common_stock_cache(cache, provider, "2026-08-14", universe_securities=univ, dry_run=True)
    assert summary.population_target_count == 2
    assert summary.created_count == 2
    assert cache.load("005930") is None
    assert cache.load("000660") is None
    assert provider.call_count.get("005930", 0) == 0


def test_atomic_write_success(tmp_path: Path):
    """15. 정상 저장 시 임시 파일 삭제 및 final parquet atomic replace 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-08-14", "2026-08-14", freq="B")
    df = _make_mock_daily(dates)

    cache.save("005930", df)

    # 1. final parquet 정상 존재
    final_path = tmp_path / "005930.parquet"
    assert final_path.exists()

    # 2. 임시 파일(.tmp) 잔재 없음 확인
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_files) == 0

    # 3. read back 검증
    loaded = cache.load("005930")
    assert loaded is not None
    assert len(loaded) == len(df)


def test_atomic_write_failure_preserves_existing_cache(tmp_path: Path):
    """16. 저장 중 read-back 검증 실패 시 기존 final cache 100% 보존 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    old_dates = pd.date_range("2021-08-14", "2026-08-01", freq="B")
    old_df = _make_mock_daily(old_dates, start_val=10000.0)
    cache.save("005930", old_df)

    # 손상된 DataFrame 저장 시도 (컬럼 누락)
    broken_df = pd.DataFrame({"close": [99999.0]}, index=pd.date_range("2026-08-14", "2026-08-14"))

    with pytest.raises(Exception):
        cache.save("005930", broken_df)

    # 기존 final parquet이 손상되지 않고 유지되었는지 확인
    loaded = cache.load("005930")
    assert loaded is not None
    assert len(loaded) == len(old_dates)
    assert loaded.loc[old_dates[0], "open"] == 10000.0


def test_temp_cleanup_on_failure(tmp_path: Path):
    """17. 예외 발생 시 .tmp 임시 파일 잔재가 깔끔하게 정리되는지 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    broken_df = pd.DataFrame({"dummy": [1]}, index=pd.date_range("2026-08-14", "2026-08-14"))

    with pytest.raises(Exception):
        cache.save("005930", broken_df)

    # 임시 파일이 남아있지 않아야 함
    all_files = list(tmp_path.iterdir())
    assert len(all_files) == 0


def test_common_coverage_denominator(tmp_path: Path):
    """18. COMMON coverage 계산 분모가 official COMMON total인지 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-08-14", "2026-08-14", freq="B")
    provider = FakeProvider({"005930": _make_mock_daily(dates)})

    # 전체 universe 3개 중 COMMON은 2개, PREFERRED 1개
    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="005935", name="삼성전자우", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
    ]

    summary = populate_common_stock_cache(
        cache=cache,
        provider=provider,
        reference_market_date="2026-08-14",
        universe_securities=univ,
        tickers=["005930"],  # 삼성전자 1개만 실행
    )

    assert summary.official_universe_total == 3
    assert summary.official_common_total == 2
    assert summary.population_target_count == 1
    assert summary.official_common_cache_present_after == 1
    # Global COMMON coverage는 1 / 2 = 50.0% (전체 universe 분모인 1/3=33.3%가 아님)
    assert summary.official_common_coverage_pct_after == 50.0
    # Run Target Coverage는 1 / 1 = 100.0%
    assert summary.target_coverage_pct_after == 100.0


def test_local_official_common_provenance_scope(tmp_path: Path):
    """19. Local Cache Total / Official Universe Intersection / Official COMMON Present / Orphan 분리 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    dates = pd.date_range("2021-08-14", "2026-08-14", freq="B")
    # 1) COMMON 캐시
    cache.save("005930", _make_mock_daily(dates))
    # 2) PREFERRED 캐시
    cache.save("005935", _make_mock_daily(dates))
    # 3) ORPHAN 캐시 (상장폐지/공식 목록 밖)
    cache.save("999999", _make_mock_daily(dates))

    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="005935", name="삼성전자우", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
    ]
    provider = FakeProvider()

    summary = populate_common_stock_cache(
        cache=cache,
        provider=provider,
        reference_market_date="2026-08-14",
        universe_securities=univ,
        dry_run=True,
    )

    assert summary.local_cache_file_count_before == 3
    assert summary.official_universe_cache_present_before == 2  # 005930, 005935
    assert summary.official_common_cache_present_before == 1    # 005930
    assert summary.orphan_cache_count_before == 1               # 999999


def test_subset_target_coverage_vs_global_coverage(tmp_path: Path):
    """20. subset 실행 시 Run Target Coverage와 Global COMMON Coverage 구분 검증."""
    cache = ParquetCache(base_dir=tmp_path)
    provider = FakeProvider()

    univ = [
        UniverseSecurity(ticker="005930", name="삼성전자", market=MarketType.KOSPI),
        UniverseSecurity(ticker="000660", name="SK하이닉스", market=MarketType.KOSPI),
        UniverseSecurity(ticker="035420", name="NAVER", market=MarketType.KOSPI),
        UniverseSecurity(ticker="035900", name="JYP Ent.", market=MarketType.KOSDAQ),
    ]

    summary = populate_common_stock_cache(
        cache=cache,
        provider=provider,
        reference_market_date="2026-08-14",
        universe_securities=univ,
        limit=2,  # 4개 중 2개만 실행
    )

    assert summary.official_common_total == 4
    assert summary.population_target_count == 2
    assert summary.created_count == 2
    assert summary.target_coverage_pct_after == 100.0          # 2 / 2
    assert summary.official_common_coverage_pct_after == 50.0  # 2 / 4
