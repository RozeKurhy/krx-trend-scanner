"""Repository V2 -> Market RS input boundary tests."""

from __future__ import annotations

import pandas as pd

from trend_scanner.relative_strength.repository_adapter import (
    benchmark_anchor_start,
    resolve_market_rs_repository_input,
)


def _benchmark() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=260, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "index_code": ["1001"] * len(dates),
            "close": [100.0] * len(dates),
        }
    )


class _FakeRepository:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self.frame = frame
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def get_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        if self.error is not None:
            raise self.error
        return self.frame.copy() if self.frame is not None else pd.DataFrame()


def test_benchmark_anchor_start_uses_252_session_index() -> None:
    benchmark = _benchmark()
    expected = benchmark.iloc[-253]["date"].strftime("%Y-%m-%d")
    assert benchmark_anchor_start(benchmark, market_code="1001", as_of="2024-12-30") == expected


def test_repository_input_is_exactly_one_shared_authority_call() -> None:
    benchmark = _benchmark()
    dates = pd.date_range("2024-01-01", periods=260, freq="B")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=dates)
    repository = _FakeRepository(frame)

    resolved = resolve_market_rs_repository_input(
        repository,
        ticker="005930",
        as_of="2024-12-30",
        market_code="1001",
        market_index_df=benchmark,
    )

    assert resolved.reason is None
    assert resolved.stock_df is not None
    assert resolved.stock_df.attrs["market_rs_input_authority"] == "MarketDataRepositoryV2"
    assert repository.calls == [("005930", benchmark.iloc[-253]["date"].strftime("%Y-%m-%d"), "2024-12-30")]


def test_repository_failure_is_fail_closed_without_legacy_fallback() -> None:
    benchmark = _benchmark()
    repository = _FakeRepository(error=RuntimeError("repository unavailable"))

    resolved = resolve_market_rs_repository_input(
        repository,
        ticker="005930",
        as_of="2024-12-30",
        market_code="1001",
        market_index_df=benchmark,
    )

    assert resolved.stock_df is None
    assert "repository unavailable" in (resolved.reason or "")


def test_missing_repository_is_not_replaced_by_legacy_cache() -> None:
    resolved = resolve_market_rs_repository_input(
        None,
        ticker="005930",
        as_of="2024-12-30",
        market_code="1001",
        market_index_df=_benchmark(),
    )
    assert resolved.stock_df is None
    assert resolved.reason == "REPOSITORY_V2_UNAVAILABLE"
