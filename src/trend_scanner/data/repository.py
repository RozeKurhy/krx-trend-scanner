"""Provider와 Cache를 조합하는 상위 데이터 조회 인터페이스."""

from __future__ import annotations

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.provider import MarketDataProvider
from trend_scanner.data.validator import validate_ohlcv

# 매번 마지막 저장일 이후만 요청하면, 그사이 정정된 API 값을 놓칠 수 있다.
# 최근 며칠을 겹쳐 다시 요청해서 새 API 값이 캐시를 덮어쓰도록 한다.
DEFAULT_OVERLAP_DAYS = 5


class MarketDataRepository:
    def __init__(
        self,
        provider: MarketDataProvider,
        cache: ParquetCache,
        overlap_days: int = DEFAULT_OVERLAP_DAYS,
    ):
        self._provider = provider
        self._cache = cache
        self._overlap_days = overlap_days

    def get_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        cached = self._cache.load(ticker)
        if cached is not None and not cached.empty:
            # 깨진 Parquet, 예전 schema, 중복 index 등이 stable cache hit 경로를
            # 통해 검증 없이 그대로 반환되지 않도록 읽을 때도 검증한다.
            validate_ohlcv(cached)
        merged = cached

        fetch_range = self._missing_range(cached, start_ts, end_ts)
        if fetch_range is not None:
            fetch_start, fetch_end = fetch_range
            fetched = self._fetch_and_validate(
                ticker, fetch_start.strftime("%Y-%m-%d"), fetch_end.strftime("%Y-%m-%d")
            )
            merged = fetched if cached is None or cached.empty else self._merge(cached, fetched)
            validate_ohlcv(merged)
            self._cache.save(ticker, merged)

        # fetch_range가 None이면 _missing_range 규칙상 cached는 항상 non-empty이므로
        # merged(=cached)도 항상 값이 있다.
        return merged.loc[start_ts:end_ts]

    def _missing_range(
        self, cached: pd.DataFrame | None, start_ts: pd.Timestamp, end_ts: pd.Timestamp
    ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        if cached is None or cached.empty:
            return start_ts, end_ts

        cached_min = cached.index.min()
        cached_max = cached.index.max()
        refresh_from = cached_max - pd.Timedelta(days=self._overlap_days)

        # 요청 시작일이 캐시 최소일보다 이전: 앞쪽이 비어 있으므로 전체 구간을
        # 다시 받는다(과거 구간 일부만 정교하게 채우는 최적화는 하지 않는다).
        if start_ts < cached_min:
            return start_ts, end_ts

        # 요청이 "최근 갱신 구간(overlap)"에 걸쳐 있으면 그 구간부터 다시 받는다.
        if end_ts > refresh_from:
            return max(start_ts, refresh_from), end_ts

        # 요청 구간이 이미 안정된 과거 캐시 안에 완전히 들어있으면 호출하지 않는다.
        return None

    def _merge(self, cached: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
        if fetched.empty:
            return cached

        combined = pd.concat([cached, fetched])
        # 동일 거래일이 양쪽에 있으면 새 API 결과(뒤에 붙인 fetched)를 우선한다.
        combined = combined[~combined.index.duplicated(keep="last")]
        return combined.sort_index()

    def _fetch_and_validate(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        df = self._provider.load_daily(ticker, start, end)
        validate_ohlcv(df)
        return df
