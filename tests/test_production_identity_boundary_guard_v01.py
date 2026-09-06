"""Directive COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01 sections 8-13/16-17/49-51: read-side
identity lower-bound (+ upper-bound) guard in MarketDataRepositoryV2.

Core regression fixture (section 50): a physical adjusted file spanning 2023-05-17..2026-09-04 while
the current certified (ticker, isu_cd, market) identity is only valid from 2025-08-14 onward -- this
is the exact real shape of the 446840 phantom-row defect. A production-rolling-mode read must never
expose a row dated before the identity's own effective_from, exactly mirroring the existing
upper-bound (certified_through) guard this repository already enforces.

Directive ROLLING_AUTHORITY_HARDENING_V01 section 9-13/14: every fixture here now publishes the
merged PIT/calendar authority in the coherence-contract schema (schema_version/content_digest/
frontier/built_against_certified_through) and threads the matching digests into the paired manifest,
since MarketDataRepositoryV2._clamp_to_identity_bounds now validates that coherence on every read.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.rolling_market_data_refresh import (
    MERGED_CALENDAR_SCHEMA_VERSION,
    MERGED_PIT_SCHEMA_VERSION,
    RollingAuthorityError,
    RollingAuthorityManifest,
    write_rolling_authority,
)


def _digest(items: list) -> str:
    blob = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_merged_pit(authority_dir: Path, intervals: list[dict], certified_through: str = "2026-08-21") -> dict:
    """Publish both merged authority files in the coherence-contract schema and return the
    digest/frontier refs the paired ``_manifest(...)`` call must carry."""
    authority_dir.mkdir(parents=True, exist_ok=True)
    pit_digest = _digest(intervals)
    pit_frontier = max((str(iv.get("effective_to")) for iv in intervals), default="")
    (authority_dir / "merged_pit_intervals.json").write_text(
        json.dumps(
            {
                "schema_version": MERGED_PIT_SCHEMA_VERSION,
                "authority_version": "ROLLING_MARKET_DATA_V01",
                "built_at_utc": "2026-09-05T00:00:00+00:00",
                "target_as_of": certified_through,
                "pit_frontier": pit_frontier,
                "built_against_certified_through": certified_through,
                "source_basic_info_frontier": None,
                "content_digest": pit_digest,
                "intervals": intervals,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cal_dates: list[str] = []
    cal_digest = _digest(cal_dates)
    (authority_dir / "merged_trading_calendar.json").write_text(
        json.dumps(
            {
                "schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
                "authority_version": "ROLLING_MARKET_DATA_V01",
                "built_at_utc": "2026-09-05T00:00:00+00:00",
                "calendar_frontier": max(cal_dates, default=""),
                "built_against_certified_through": certified_through,
                "content_digest": cal_digest,
                "trading_dates": cal_dates,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "merged_pit_digest": pit_digest,
        "merged_pit_frontier": pit_frontier,
        "merged_pit_schema_version": MERGED_PIT_SCHEMA_VERSION,
        "merged_calendar_digest": cal_digest,
        "merged_calendar_frontier": max(cal_dates, default=""),
        "merged_calendar_schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
    }


def _manifest(certified_through: str, merged: dict | None = None) -> RollingAuthorityManifest:
    leg_boundaries = {leg: certified_through for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")}
    # A caller that never published a merged PIT/calendar (the missing-artifact test) still gets a
    # manifest referencing SOME digest, so the coherence check fails on "file missing", not on
    # "manifest not migrated" -- exercising the intended failure mode for that test.
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


def _raw_frame(date: str, ticker: str, base: int = 100) -> pd.DataFrame:
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


def _build_stores(tmp_path, *, ticker: str, dates: list[str]):
    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted_store.save_full(ticker, _adjusted_frame(dates), {"requested_start": dates[0], "requested_end": dates[-1]})
    raw_store = KrxRawStockStore(tmp_path / "raw")
    for day in dates:
        raw_store.save_snapshot("KOSDAQ", day, _raw_frame(day, ticker), "/KOSDAQ")
    return adjusted_store, raw_store


def test_446840_regression_fixture_pre_identity_rows_invisible(tmp_path) -> None:
    """Section 50/11: physical 2023-05-17..2026-09-04 vs identity effective_from=2025-08-14 ->
    VISIBLE_MIN_DATE >= 2025-08-14, exactly the real 446840 shape."""
    all_dates = ["2023-05-17", "2024-01-10", "2025-08-14", "2025-12-01", "2026-08-21", "2026-09-04"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="446840", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2025-08-14", "effective_to": "2026-09-04"}],
        certified_through="2026-09-04",
    )
    write_rolling_authority(_manifest("2026-09-04", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("446840", "2010-01-04", "2026-09-04")

    assert frame.index.min().strftime("%Y-%m-%d") >= "2025-08-14"
    assert "2023-05-17" not in frame.index.strftime("%Y-%m-%d")
    assert "2024-01-10" not in frame.index.strftime("%Y-%m-%d")
    assert frame.index.min().strftime("%Y-%m-%d") == "2025-08-14"


def test_upper_and_lower_bound_both_enforced_simultaneously(tmp_path) -> None:
    """Section 12: identity_effective_from <= visible row.date <= min(identity_effective_to,
    certified_through) -- both guards active at once."""
    all_dates = ["2023-05-17", "2025-08-14", "2026-08-21", "2026-09-04"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="446840", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2025-08-14", "effective_to": "2026-09-04"}],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)  # certified boundary BELOW target

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("446840", "2010-01-04", "2026-09-04")

    assert frame.index.min().strftime("%Y-%m-%d") == "2025-08-14"
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-21"  # certified_through, not identity effective_to


def test_current_identity_effective_from_clamp_normal_case(tmp_path) -> None:
    """Section 15/50: a normal (non-corrupted) single-interval ticker is clamped to its own real
    effective_from, not truncated below it."""
    all_dates = ["2010-01-04", "2015-06-01", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="005930", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI", "state": "COMMON",
          "effective_from": "2010-01-04", "effective_to": "2026-08-21"}],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("005930", "2010-01-04", "2026-08-21")

    assert frame.index.min().strftime("%Y-%m-%d") == "2010-01-04"
    assert len(frame) == 3


def test_effective_to_clamp_when_identity_ends_before_certified_through(tmp_path) -> None:
    """Section 12/15: an identity that ended (delisted) before certified_through must not show rows
    past its own effective_to, even though the manifest allows a later date."""
    all_dates = ["2015-01-05", "2018-06-01", "2020-03-15", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="099999", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "099999", "isu_cd": "KR7099999009", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2015-01-05", "effective_to": "2020-03-15"}],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("099999", "2010-01-04", "2026-08-21")

    assert frame.index.max().strftime("%Y-%m-%d") == "2020-03-15"
    assert "2026-08-21" not in frame.index.strftime("%Y-%m-%d")


def test_market_transfer_same_isu_cd_not_treated_as_ambiguous(tmp_path) -> None:
    """Section 16: a market transfer (KOSDAQ -> KOSPI, SAME isu_cd) is one identity, not a reuse
    ambiguity -- its full real history (both market-tagged interval rows) must remain visible."""
    all_dates = ["2010-01-04", "2015-06-01", "2019-05-29", "2022-01-10", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="003670", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [
            {"ticker": "003670", "isu_cd": "KR7003670007", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2010-01-04", "effective_to": "2019-05-28"},
            {"ticker": "003670", "isu_cd": "KR7003670007", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2019-05-29", "effective_to": "2026-08-21"},
        ],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("003670", "2010-01-04", "2026-08-21")

    assert frame.index.min().strftime("%Y-%m-%d") == "2010-01-04"
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-21"
    assert len(frame) == 5


def test_genuine_ticker_code_reuse_two_distinct_isu_cd_resolves_current(tmp_path) -> None:
    """Section 16/17: a ticker code with TWO DISTINCT isu_cd (genuine reuse, unlike a market
    transfer) must resolve to whichever identity covers the query's as_of date, never a blended
    earliest-to-latest span across both securities."""
    all_dates = ["2012-01-10", "2014-06-01", "2018-01-05", "2020-06-01", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="077700", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [
            {"ticker": "077700", "isu_cd": "KR7077700001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2012-01-10", "effective_to": "2016-12-31"},
            {"ticker": "077700", "isu_cd": "KR7077700099", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2018-01-05", "effective_to": "2026-08-21"},
        ],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("077700", "2010-01-04", "2026-08-21")

    # as_of (clamped end) = 2026-08-21 covers only the SECOND isu_cd's interval.
    assert frame.index.min().strftime("%Y-%m-%d") == "2018-01-05"
    assert "2012-01-10" not in frame.index.strftime("%Y-%m-%d")
    assert "2014-06-01" not in frame.index.strftime("%Y-%m-%d")


def test_identity_ambiguity_fails_closed(tmp_path) -> None:
    """Section 10/17: two candidate identities both claiming to cover as_of is a genuine, unexpected
    ambiguity -- must fail closed with RollingAuthorityError, never pick one arbitrarily."""
    all_dates = ["2015-01-05", "2020-06-01"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="088800", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [
            {"ticker": "088800", "isu_cd": "KR7088800001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2015-01-05", "effective_to": "2026-08-21"},
            {"ticker": "088800", "isu_cd": "KR7088800099", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2018-01-01", "effective_to": "2026-08-21"},
        ],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    with pytest.raises(RollingAuthorityError, match="IDENTITY_AMBIGUITY_FAIL_CLOSED"):
        repo.get_daily("088800", "2010-01-04", "2026-08-21")


def test_no_open_identity_fails_closed_when_ticker_has_records_but_no_coverage(tmp_path) -> None:
    """Section 17: a reused code with a genuine GAP between two occupants (neither covers as_of) must
    fail closed, not silently fall through to an unclamped read."""
    all_dates = ["2015-01-05", "2020-06-01"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="099100", dates=all_dates)
    authority_dir = tmp_path / "authority"
    # note: certified_through=2026-08-21 but a SOLE isu_cd's interval ending 2012-06-01 would resolve
    # via the "single identity" branch regardless of coverage (matches a normal already-delisted
    # ticker) -- use two isu_cd with a genuine gap to exercise the true
    # NO_OPEN_IDENTITY-with-records path instead.
    merged = _write_merged_pit(
        authority_dir,
        [
            {"ticker": "099100", "isu_cd": "KR7099100001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2010-01-04", "effective_to": "2012-06-01"},
            {"ticker": "099100", "isu_cd": "KR7099100088", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2013-01-01", "effective_to": "2014-12-31"},
        ],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    with pytest.raises(RollingAuthorityError, match="IDENTITY_MISSING_AUTHORITY_FAIL_CLOSED"):
        repo.get_daily("099100", "2010-01-04", "2026-08-21")


def test_already_delisted_single_identity_ticker_not_treated_as_ambiguous(tmp_path) -> None:
    """A normal, single-identity ticker delisted long before the query's as_of date is NOT ambiguous
    and is NOT a missing-authority case -- its own bounds are used directly (this is the
    already-delisted-ticker case that a naive 'must cover as_of' rule would have wrongly broken)."""
    all_dates = ["2015-01-05", "2018-06-01", "2020-03-15"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="011100", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "011100", "isu_cd": "KR7011100001", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2015-01-05", "effective_to": "2020-03-15"}],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("011100", "2010-01-04", "2026-08-21")

    assert len(frame) == 3
    assert frame.index.max().strftime("%Y-%m-%d") == "2020-03-15"


def test_ticker_not_in_pit_is_unaffected_by_identity_clamp(tmp_path) -> None:
    """Section 23: an instrument type this PIT does not classify at all (e.g. ETF) must be a
    complete no-op for the identity clamp -- only the pre-existing upper-bound guard applies."""
    all_dates = ["2023-01-02", "2026-08-21", "2026-09-04"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="069500", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(authority_dir, [], certified_through="2026-08-21")  # ETF never appears in the COMMON PIT
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    frame = repo.get_daily("069500", "2010-01-04", "2026-09-04")

    assert frame.index.min().strftime("%Y-%m-%d") == "2023-01-02"
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-21"


def test_missing_merged_pit_artifact_fails_closed_in_production_rolling_mode(tmp_path) -> None:
    """A rolling-mode caller with a manifest but no merged_pit_intervals.json artifact must fail
    closed, not silently skip the identity guard."""
    all_dates = ["2015-01-05", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="005930", dates=all_dates)
    authority_dir = tmp_path / "authority"
    write_rolling_authority(_manifest("2026-08-21"), authority_dir)
    # no merged_pit_intervals.json written -- manifest still references a (placeholder) digest, so
    # this exercises "reference present but file missing", not "manifest not migrated".

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_ARTIFACT_MISSING"):
        repo.get_daily("005930", "2010-01-04", "2026-08-21")


def test_e2e_frozen_historical_path_unaffected_by_identity_guard(tmp_path) -> None:
    """Section 9: omitting rolling_authority_dir (every E2E/historical call site) must be a complete
    no-op for the identity guard, even when a phantom-shaped physical file exists."""
    all_dates = ["2023-05-17", "2025-08-14", "2026-08-21"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="446840", dates=all_dates)

    repo = MarketDataRepositoryV2(adjusted_store, raw_store)  # no rolling_authority_dir
    frame = repo.get_daily("446840", "2010-01-04", "2026-08-21")

    assert frame.index.min().strftime("%Y-%m-%d") == "2023-05-17"  # unclamped, exactly pre-existing behavior
    assert len(frame) == 3


def test_new_listing_not_yet_certified_returns_none_not_a_crash(tmp_path) -> None:
    """Real edge case found during this remediation's post-repair exposure re-audit: a genuine new
    listing whose PIT effective_from (2026-08-24) is already later than the currently certified
    boundary (2026-08-21, not yet promoted). clamped_start > clamped_end must surface as a graceful
    DATA_UNAVAILABLE (RepositoryV2DailyLoader.load returns None), never a raw
    REPOSITORY_V2_INVALID_RANGE crash."""
    from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader

    all_dates = ["2026-08-24", "2026-08-25", "2026-09-04"]
    adjusted_store, raw_store = _build_stores(tmp_path, ticker="465320", dates=all_dates)
    authority_dir = tmp_path / "authority"
    merged = _write_merged_pit(
        authority_dir,
        [{"ticker": "465320", "isu_cd": "KR7465320001", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2026-08-24", "effective_to": "2026-09-04"}],
        certified_through="2026-08-21",
    )
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)  # certified boundary NOT yet advanced

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    loader = RepositoryV2DailyLoader(repo, start="2010-01-04", end="2026-09-04")
    result = loader.load("465320")

    assert result is None


def test_pykrx_zero_use_guard(tmp_path) -> None:
    repository_v2_path = Path("src/trend_scanner/data/repository_v2.py")
    source = repository_v2_path.read_text(encoding="utf-8").lower()
    assert "pykrx" not in source, f"{repository_v2_path} must not reference pykrx"
