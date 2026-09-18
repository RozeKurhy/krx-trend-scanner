from __future__ import annotations

import pandas as pd

from scripts.backfill_etf_adjusted_scope_expansion_v01 import (
    EXISTING_ETF_TICKERS,
    NEW_ETF_TICKERS,
    REQUESTED_START,
    fetch_missing_adjusted,
    validate_adjusted_frame,
)
from trend_scanner.data.rolling_market_data_refresh import ETF_VALIDATED_ACCEPTANCE_TICKERS


def _frame(start: str = REQUESTED_START, end: str = "2026-09-11") -> pd.DataFrame:
    index = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {
            "open": [100.0] * len(index),
            "high": [101.0] * len(index),
            "low": [99.0] * len(index),
            "close": [100.0] * len(index),
        },
        index=index,
    )


def test_new_scope_is_exactly_the_fixed_11_and_preserves_existing_17() -> None:
    assert len(NEW_ETF_TICKERS) == 11
    assert len(set(NEW_ETF_TICKERS)) == 11
    assert len(EXISTING_ETF_TICKERS) == 17
    assert set(EXISTING_ETF_TICKERS).issubset(ETF_VALIDATED_ACCEPTANCE_TICKERS)
    assert set(NEW_ETF_TICKERS).isdisjoint(EXISTING_ETF_TICKERS)
    assert len(set(NEW_ETF_TICKERS) | set(EXISTING_ETF_TICKERS)) == 28
    assert set(ETF_VALIDATED_ACCEPTANCE_TICKERS) == set(NEW_ETF_TICKERS) | set(EXISTING_ETF_TICKERS)


def test_adjusted_frame_validation_requires_target_end_and_history() -> None:
    assert validate_adjusted_frame(
        "226490", _frame(), requested_start=REQUESTED_START, target_end="2026-09-11"
    ) == []
    errors = validate_adjusted_frame(
        "226490", _frame(end="2026-09-10"), requested_start=REQUESTED_START, target_end="2026-09-11"
    )
    assert "ADJUSTED_TARGET_END_MISMATCH" in errors


def test_fetch_missing_does_not_call_provider_for_existing_tickers() -> None:
    class Provider:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            self.calls.append(ticker)
            return _frame()

    class Store:
        def __init__(self) -> None:
            self.existing = {"226490"}
            self.saved: list[str] = []
            self.metadata = {"actual_date_max": "2026-09-11"}

        def exists(self, ticker: str) -> bool:
            return ticker in self.existing

        def save_full(self, ticker: str, frame: pd.DataFrame, metadata_context: dict[str, str]) -> None:
            self.existing.add(ticker)
            self.saved.append(ticker)

        def load_metadata(self, ticker: str) -> dict[str, str]:
            return self.metadata

    provider = Provider()
    store = Store()
    result = fetch_missing_adjusted(
        provider,
        store,
        ("226490", "139230"),
        requested_start=REQUESTED_START,
        target_end="2026-09-11",
    )
    assert result["existing"] == ["226490"]
    assert result["fetched"] == ["139230"]
    assert result["failures"] == []
    assert provider.calls == ["139230"]


def test_fetch_failure_does_not_report_complete_scope() -> None:
    class Provider:
        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            return pd.DataFrame()

    class Store:
        def exists(self, ticker: str) -> bool:
            return False

    result = fetch_missing_adjusted(
        Provider(), Store(), ("226490",), requested_start=REQUESTED_START, target_end="2026-09-11"
    )
    assert result["fetched"] == []
    assert result["failures"][0]["ticker"] == "226490"
