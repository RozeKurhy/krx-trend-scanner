"""ROLLING_MARKET_DATA_AUTHORITY_FINALIZATION_V01 BLOCKER-1 tests: the rolling certified boundary
must actually be wired into the real production Repository V2 construction path
(build_production_repository_v2 / RepositoryV2DailyLoader), not merely available as an opt-in
constructor kwarg that no production caller uses.
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
from trend_scanner.data.repository_v2_loader import (
    RepositoryV2DailyLoader,
    build_production_repository_v2,
    build_repository_v2,
)
from trend_scanner.data.rolling_market_data_refresh import (
    MERGED_CALENDAR_SCHEMA_VERSION,
    MERGED_PIT_SCHEMA_VERSION,
    _content_digest,
    RollingAuthorityManifest,
    RollingAuthorityError,
    write_rolling_authority,
)

TICKER = "005930"
ALL_DATES = ["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-09-04"]


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


def _raw_frame(date: str, base: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date, "ticker": TICKER,
                "open": base, "high": base + 5, "low": base - 5, "close": base + 1,
                "volume": 1000, "trading_value": 100000, "market_cap": 1_000_000, "listed_shares": 10_000,
            }
        ],
        columns=list(RAW_COLUMNS),
    )


def _write_empty_merged_pit(authority_dir: Path, certified_through: str = "2026-08-21") -> dict:
    """These tests predate the identity lower-bound guard (directive
    COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01 section 8-13) and exercise only the upper-bound
    certified-boundary clamp for a ticker this fixture never registers a PIT identity for. An empty
    merged PIT means the identity clamp is a no-op here -- exactly the pre-existing behavior these
    tests assert on.

    Directive ROLLING_AUTHORITY_HARDENING_V01 section 9-13: now publishes the coherence-contract
    schema and returns the refs the paired ``_manifest(...)`` call must carry."""
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


def _build_production_repo_root(tmp_path: Path, *, dates: list[str]) -> Path:
    """Lay out a fake repo root with the exact directory convention
    build_production_repository_v2 expects: data/market/adjusted/stocks, data/market/raw/krx_stocks/v01,
    data/market/rolling_authority."""
    root = tmp_path / "repo_root"
    adjusted_store = AdjustedPriceStore(root / "data/market/adjusted/stocks")
    adjusted_store.save_full(TICKER, _adjusted_frame(dates), {"requested_start": dates[0], "requested_end": dates[-1]})
    raw_store = KrxRawStockStore(root / "data/market/raw/krx_stocks/v01")
    for day in dates:
        raw_store.save_snapshot("KOSPI", day, _raw_frame(day), "/KOSPI")
    return root


def test_production_loader_enforces_certified_boundary(tmp_path) -> None:
    """directive section 11 (PRODUCTION_READ_PATH_BOUNDARY_ENFORCED=true): a production loader built
    through build_production_repository_v2, reading via the same RepositoryV2DailyLoader production
    consumers use, must clamp to certified_through even though the underlying stores physically
    contain rows well past it."""
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    authority_dir = root / "data/market/rolling_authority"
    merged = _write_empty_merged_pit(authority_dir, certified_through="2026-08-21")
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repository = build_production_repository_v2(root, end="2026-09-04")
    loader = RepositoryV2DailyLoader(repository, end="2026-09-04")
    frame = loader.load(TICKER)

    assert frame is not None
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-08-21"
    assert "2026-09-04" not in frame.index.strftime("%Y-%m-%d")


def test_partial_future_rows_invisible_through_production_loader(tmp_path) -> None:
    """directive section 12: PARTIAL_FUTURE_ROWS_VISIBLE_TO_PRODUCTION_CONSUMER=0. Simulates
    common_raw/etf_raw/etf_adjusted having advanced through 2026-09-04 while common_adjusted failed
    and the manifest correctly stayed at 2026-08-21 -- reading through the real production loader path
    must show zero rows past the certified boundary."""
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    authority_dir = root / "data/market/rolling_authority"
    merged = _write_empty_merged_pit(authority_dir, certified_through="2026-08-21")
    write_rolling_authority(_manifest("2026-08-21", merged), authority_dir)

    repository = build_production_repository_v2(root, end="2026-09-04")
    loader = RepositoryV2DailyLoader(repository, end="2026-09-04")
    frame = loader.load(TICKER)

    future_rows = frame.index[frame.index > pd.Timestamp("2026-08-21")]
    assert len(future_rows) == 0


def test_successful_promotion_visible_through_production_loader(tmp_path) -> None:
    """directive section 13: once certified_through is legitimately promoted to 2026-09-04, the same
    physically-present rows become visible through the production loader -- no re-fetch needed."""
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    authority_dir = root / "data/market/rolling_authority"
    merged = _write_empty_merged_pit(authority_dir, certified_through="2026-09-04")
    write_rolling_authority(_manifest("2026-09-04", merged), authority_dir)

    repository = build_production_repository_v2(root, end="2026-09-04")
    loader = RepositoryV2DailyLoader(repository, end="2026-09-04")
    frame = loader.load(TICKER)

    assert frame.index.max().strftime("%Y-%m-%d") == "2026-09-04"


def test_missing_manifest_fails_closed_through_production_loader(tmp_path) -> None:
    """directive section 10: missing manifest must fail closed, never silently fall back to a full,
    unclamped store read."""
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    # no write_rolling_authority call -- manifest is absent

    repository = build_production_repository_v2(root, end="2026-09-04")
    with pytest.raises(RollingAuthorityError):
        repository.get_daily(TICKER, "2026-08-19", "2026-09-04")


def test_tampered_manifest_fails_closed_through_production_loader(tmp_path) -> None:
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    authority_dir = root / "data/market/rolling_authority"
    write_rolling_authority(_manifest("2026-08-21"), authority_dir)
    path = authority_dir / "manifest.json"
    payload = json.loads(path.read_text())
    payload["certified_through"] = "2026-09-04"  # tamper without recomputing digest
    path.write_text(json.dumps(payload))

    repository = build_production_repository_v2(root, end="2026-09-04")
    with pytest.raises(RollingAuthorityError, match="CHECKSUM_MISMATCH"):
        repository.get_daily(TICKER, "2026-08-19", "2026-09-04")


def test_historical_frozen_mode_unaffected_by_production_manifest(tmp_path) -> None:
    """directive section 8: build_repository_v2 (HISTORICAL_FROZEN_MODE, used by E2E/closure/
    evaluation scripts) must keep behaving exactly as before -- unaffected by a rolling manifest
    existing on disk, since it never wires rolling_authority_dir."""
    root = _build_production_repo_root(tmp_path, dates=ALL_DATES)
    write_rolling_authority(_manifest("2026-08-21"), root / "data/market/rolling_authority")

    repository = build_repository_v2(root, end="2026-09-04")
    frame = repository.get_daily(TICKER, "2026-08-19", "2026-09-04")
    assert frame.index.max().strftime("%Y-%m-%d") == "2026-09-04"  # sees everything, unclamped


def test_pykrx_zero_use_guard_on_production_wiring_changes() -> None:
    """directive section 33: PyKRX zero-use guard, extended to every file this BLOCKER-1 wiring
    change touched."""
    changed_files = (
        Path("src/trend_scanner/data/repository_v2_loader.py"),
        Path("src/trend_scanner/scanner/full_universe_scanner.py"),
        Path("scripts/run_pattern_a_universe_scanner.py"),
        Path("src/trend_scanner/reporting/stock_report.py"),
    )
    for path in changed_files:
        source = path.read_text(encoding="utf-8").lower()
        assert "pykrx" not in source, f"{path} must not reference pykrx"
