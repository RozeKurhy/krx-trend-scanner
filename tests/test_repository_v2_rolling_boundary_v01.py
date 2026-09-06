"""BLOCKER C tests (directive ROLLING_MARKET_DATA_AUTHORITY_FIX_V01 sections 21-28):
MarketDataRepositoryV2's rolling-authority certified-boundary clamp.

Core gate: a partial refresh that has already physically written rows past the last certified
boundary into the raw/adjusted stores must still be invisible to a Repository V2 consumer reading
in rolling mode, until the rolling authority manifest is atomically promoted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.rolling_market_data_refresh import (
    MERGED_CALENDAR_SCHEMA_VERSION,
    MERGED_PIT_SCHEMA_VERSION,
    _content_digest,
    RollingAuthorityManifest,
    RollingAuthorityError,
    write_rolling_authority,
)


def _manifest(certified_through: str, merged: dict | None = None) -> RollingAuthorityManifest:
    leg_boundaries = {leg: certified_through for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")}
    merged = merged or {
        "merged_pit_digest": "PLACEHOLDER_NO_FILE_PUBLISHED",
        "merged_pit_frontier": certified_through,
        "merged_pit_schema_version": MERGED_PIT_SCHEMA_VERSION,
        "merged_calendar_digest": "PLACEHOLDER_NO_FILE_PUBLISHED",
        "merged_calendar_frontier": certified_through,
        "merged_calendar_schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
    }
    return RollingAuthorityManifest(
        authority_version="ROLLING_MARKET_DATA_V01",
        certified_through=certified_through,
        leg_boundaries=leg_boundaries,
        previous_boundary=None,
        raw_store_version="KRX_RAW_STOCK_V01",
        adjusted_store_version="ADJUSTED_PRICE_STORE_V02",
        instrument_contract_version="REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
        bootstrap_source=None,
        generated_at="2026-09-05T00:00:00+00:00",
        **merged,
    ).with_digest()


def _adjusted_frame(dates: list[str], base: float = 50.0) -> pd.DataFrame:
    index = pd.DatetimeIndex(dates)
    values = [base + i for i in range(len(index))]
    return pd.DataFrame(
        {"open": values, "high": [v + 5 for v in values], "low": [v - 5 for v in values], "close": [v + 1 for v in values]},
        index=index,
    )


def _raw_frame(date: str, ticker: str = "005930", base: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date, "ticker": ticker,
                "open": base, "high": base + 5, "low": base - 5, "close": base + 1,
                "volume": 1000, "trading_value": 100000, "market_cap": 1_000_000, "listed_shares": 10_000,
            }
        ],
        columns=list(RAW_COLUMNS),
    )


def _write_empty_merged_pit(authority_dir: Path, certified_through: str = "2026-08-21") -> dict:
    """These tests predate the identity lower-bound guard (directive
    COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01 section 8-13) and exercise only the upper-bound
    certified-boundary clamp with a ticker ("005930") this fixture never registers a PIT identity
    for. An empty merged PIT means that ticker is simply absent from ``intervals_by_ticker``, so the
    identity clamp is a no-op here -- exactly the pre-existing behavior these tests assert on.

    Directive ROLLING_AUTHORITY_HARDENING_V01 section 9-13: now publishes the coherence-contract
    schema (empty payload lists still digest/frontier normally) and returns the refs the paired
    ``_manifest(...)`` call must carry."""
    authority_dir.mkdir(parents=True, exist_ok=True)
    empty_digest = _content_digest([])
    (authority_dir / "merged_pit_intervals.json").write_text(
        json.dumps(
            {
                "schema_version": MERGED_PIT_SCHEMA_VERSION,
                "authority_version": "ROLLING_MARKET_DATA_V01",
                "built_at_utc": "2026-09-05T00:00:00+00:00",
                "target_as_of": certified_through,
                "pit_frontier": "",
                "built_against_certified_through": certified_through,
                "source_basic_info_frontier": None,
                "content_digest": empty_digest,
                "intervals": [],
            }
        ),
        encoding="utf-8",
    )
    (authority_dir / "merged_trading_calendar.json").write_text(
        json.dumps(
            {
                "schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
                "authority_version": "ROLLING_MARKET_DATA_V01",
                "built_at_utc": "2026-09-05T00:00:00+00:00",
                "calendar_frontier": "",
                "built_against_certified_through": certified_through,
                "content_digest": empty_digest,
                "trading_dates": [],
            }
        ),
        encoding="utf-8",
    )
    return {
        "merged_pit_digest": empty_digest,
        "merged_pit_frontier": "",
        "merged_pit_schema_version": MERGED_PIT_SCHEMA_VERSION,
        "merged_calendar_digest": empty_digest,
        "merged_calendar_frontier": "",
        "merged_calendar_schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
    }


def _build_stores(tmp_path, *, adjusted_dates: list[str], raw_dates: list[str]):
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted_store.save_full("005930", _adjusted_frame(adjusted_dates), {"requested_start": adjusted_dates[0], "requested_end": adjusted_dates[-1]})
    raw_store = KrxRawStockStore(tmp_path / "raw")
    for day in raw_dates:
        raw_store.save_snapshot("KOSPI", day, _raw_frame(day), "/KOSPI")
    return adjusted_store, raw_store


ALL_DATES = ["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"]  # 3 pre-boundary + 2 post-boundary


def test_repository_v2_without_rolling_dir_is_unaffected_by_any_manifest(tmp_path) -> None:
    """directive section 26: E2E_FROZEN_READ_REGRESSION_COUNT=0 -- omitting rolling_authority_dir
    (every existing call site) must behave identically no matter what a rolling manifest says."""
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    write_rolling_authority(_manifest("2026-08-21"), tmp_path / "authority")

    repo = MarketDataRepositoryV2(adjusted_store, raw_store)  # no rolling_authority_dir
    frame = repo.get_daily("005930", "2026-08-19", "2026-08-25")
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-25"  # sees everything, unclamped


def test_partial_leg_write_not_visible_above_certified_boundary(tmp_path) -> None:
    """The core gate (directive section 27): stores already physically contain rows through
    2026-08-25 (simulating common_raw/etf_raw/etf_adjusted having succeeded while common_adjusted
    failed and the coordinator correctly left the manifest at 2026-08-21) -- a rolling-mode
    Repository V2 read must never expose anything past the certified boundary."""
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    authority_dir = tmp_path / "authority"
    merged = _write_empty_merged_pit(authority_dir, certified_through="2026-08-21")
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("005930", "2026-08-19", "2026-08-25")
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-21"
    assert "2026-08-24" not in frame.index.strftime("%Y-%m-%d")
    assert "2026-08-25" not in frame.index.strftime("%Y-%m-%d")

    raw = repo.get_raw_daily("005930", "2026-08-19", "2026-08-25")
    assert raw.index.max().strftime("%Y-%m-%d") == "2026-08-21"


def test_successful_promotion_advances_visible_boundary(tmp_path) -> None:
    """directive section 28: once the manifest is promoted, the same physically-present rows
    become visible -- no re-fetch/re-write needed, only the authority boundary changed."""
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    authority_dir = tmp_path / "authority"
    merged = _write_empty_merged_pit(authority_dir, certified_through="2026-08-25")
    write_rolling_authority(_manifest("2026-08-25", merged), authority_dir)  # simulates a completed promotion

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("005930", "2026-08-19", "2026-08-25")
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-25"


def test_manifest_failure_fails_closed_not_open(tmp_path) -> None:
    """directive section 25: missing/invalid/tampered manifest must fail closed -- never silently
    fall back to the caller's requested end date (which would defeat the whole guarantee)."""
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    authority_dir = tmp_path / "authority_missing"  # never written

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    with pytest.raises(RollingAuthorityError):
        repo.get_daily("005930", "2026-08-19", "2026-08-25")


def test_manifest_tampering_fails_closed(tmp_path) -> None:
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    authority_dir = tmp_path / "authority"
    write_rolling_authority(_manifest("2026-08-21"), authority_dir)
    path = authority_dir / "manifest.json"
    payload = json.loads(path.read_text())
    payload["certified_through"] = "2026-08-25"  # tamper without recomputing the digest
    path.write_text(json.dumps(payload))

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    with pytest.raises(RollingAuthorityError, match="CHECKSUM_MISMATCH"):
        repo.get_daily("005930", "2026-08-19", "2026-08-25")


def test_rolling_authority_error_is_not_a_market_data_error(tmp_path) -> None:
    """A consumer's `except MarketDataError` handler (RepositoryV2DailyLoader.load) must never
    mistake an authority failure for an ordinary DATA_UNAVAILABLE case."""
    assert not issubclass(RollingAuthorityError, MarketDataError)


def test_e2e_frozen_as_of_unaffected(tmp_path) -> None:
    """directive section 32: E2E frozen evidence (FROZEN_AS_OF=2026-08-14) must never be affected by
    the rolling-authority clamp -- the E2E harness never passes rolling_authority_dir, so it must see
    exactly the same rows with or without a rolling manifest present anywhere on disk, at any
    boundary, even one drawn from before the E2E freeze date itself."""
    adjusted_store, raw_store = _build_stores(tmp_path, adjusted_dates=ALL_DATES, raw_dates=ALL_DATES)
    unclamped = MarketDataRepositoryV2(adjusted_store, raw_store)
    baseline = unclamped.get_daily("005930", "2026-08-19", "2026-08-25")

    authority_dir = tmp_path / "authority"
    write_rolling_authority(_manifest("2026-08-21"), authority_dir)
    still_unclamped = MarketDataRepositoryV2(adjusted_store, raw_store)  # E2E call sites never pass the kwarg
    after_manifest_exists = still_unclamped.get_daily("005930", "2026-08-19", "2026-08-25")

    pd.testing.assert_frame_equal(baseline, after_manifest_exists)
    assert after_manifest_exists.index.max().strftime("%Y-%m-%d") == "2026-08-25"


def test_pykrx_zero_use_guard(tmp_path) -> None:
    """directive section 35, extended to the file this BLOCKER actually modified: repository_v2.py
    must remain as pykrx-free as the rolling module itself."""
    repository_v2_path = Path("src/trend_scanner/data/repository_v2.py")
    source = repository_v2_path.read_text(encoding="utf-8").lower()
    assert "pykrx" not in source, f"{repository_v2_path} must not reference pykrx"
