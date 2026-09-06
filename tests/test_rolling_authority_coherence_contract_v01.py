"""Directive ROLLING_AUTHORITY_HARDENING_V01 section 5-17: coherence contract between
manifest.json and the merged PIT/calendar authority files it references.

Closes the MAJOR finding disclosed at the end of COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01:
merged_pit_intervals.json/merged_trading_calendar.json previously had no digest/version/consistency
check against manifest.json, creating the same class of latent risk as the phantom-row defect. Every
test here exercises validate_merged_authority_coherence's fail-closed behavior directly (unit level)
plus one full read-path test through MarketDataRepositoryV2.get_daily (section 14's required "correct
triple -> PASS" gate, exercised end to end).
"""

from __future__ import annotations

import json
from dataclasses import replace
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
    PitExtensionResult,
    RollingAuthorityError,
    RollingAuthorityManifest,
    validate_merged_authority_coherence,
    write_merged_pit_extension,
    write_rolling_authority,
)

CERTIFIED_THROUGH = "2026-09-04"

_EXTENSION = PitExtensionResult(
    merged_intervals=(
        {"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI", "state": "COMMON",
         "effective_from": "2010-01-04", "effective_to": CERTIFIED_THROUGH},
        {"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
         "effective_from": "2025-08-14", "effective_to": CERTIFIED_THROUGH},
    ),
    merged_calendar_dates=("2026-08-21", CERTIFIED_THROUGH),
    extension_start="2026-08-24",
    extension_end=CERTIFIED_THROUGH,
    frozen_interval_count=1,
    merged_interval_count=2,
    new_ticker_count=1,
)


def _manifest_for(certified_through: str, merged: dict) -> RollingAuthorityManifest:
    leg_boundaries = {leg: certified_through for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")}
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


def _publish_valid_authority(tmp_path: Path, *, certified_through: str = CERTIFIED_THROUGH):
    """A correct, coherent manifest + merged PIT/calendar triple (section 14's PASS baseline)."""
    authority_dir = tmp_path / "authority"
    result = write_merged_pit_extension(_EXTENSION, authority_dir, built_against_certified_through=certified_through)
    merged = {
        "merged_pit_digest": result.merged_pit_digest,
        "merged_pit_frontier": result.merged_pit_frontier,
        "merged_pit_schema_version": result.merged_pit_schema_version,
        "merged_calendar_digest": result.merged_calendar_digest,
        "merged_calendar_frontier": result.merged_calendar_frontier,
        "merged_calendar_schema_version": result.merged_calendar_schema_version,
    }
    manifest = _manifest_for(certified_through, merged)
    write_rolling_authority(manifest, authority_dir)
    return authority_dir, manifest, merged


def test_correct_triple_passes(tmp_path) -> None:
    """Section 14 gate 6: a correctly-published manifest + merged PIT + merged calendar validates
    with no error and returns the parsed payloads."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    pit_payload, cal_payload = validate_merged_authority_coherence(manifest, authority_dir)
    assert pit_payload["schema_version"] == MERGED_PIT_SCHEMA_VERSION
    assert cal_payload["schema_version"] == MERGED_CALENDAR_SCHEMA_VERSION
    assert len(pit_payload["intervals"]) == 2


def test_manifest_pit_digest_mismatch_fails_closed(tmp_path) -> None:
    """Section 14 gate 1: manifest references a digest that does not match the real, self-consistent
    file on disk (e.g. the file was republished without updating the manifest, or vice versa)."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    tampered = replace(manifest, merged_pit_digest="0" * 64).with_digest()
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_DIGEST_MISMATCH_WITH_MANIFEST"):
        validate_merged_authority_coherence(tampered, authority_dir)


def test_manifest_pit_frontier_mismatch_fails_closed(tmp_path) -> None:
    """Section 14 gate 2: manifest's recorded frontier disagrees with the file's own frontier."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    tampered = replace(manifest, merged_pit_frontier="1999-01-01").with_digest()
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_FRONTIER_MISMATCH_WITH_MANIFEST"):
        validate_merged_authority_coherence(tampered, authority_dir)


def test_merged_pit_built_against_future_certified_through_fails_closed(tmp_path) -> None:
    """Section 14 gate 3: a merged PIT built against a LATER certified_through than the manifest
    currently carries is a structural impossibility (the file would be from the future relative to
    the manifest) and must fail closed."""
    authority_dir = tmp_path / "authority"
    result = write_merged_pit_extension(
        _EXTENSION, authority_dir, built_against_certified_through="2026-09-10"
    )
    merged = {
        "merged_pit_digest": result.merged_pit_digest,
        "merged_pit_frontier": result.merged_pit_frontier,
        "merged_pit_schema_version": result.merged_pit_schema_version,
        "merged_calendar_digest": result.merged_calendar_digest,
        "merged_calendar_frontier": result.merged_calendar_frontier,
        "merged_calendar_schema_version": result.merged_calendar_schema_version,
    }
    # Manifest's own certified_through (2026-09-04) is EARLIER than what the file claims it was
    # built against (2026-09-10) -- digests/frontiers all still match; only the ordering is wrong.
    manifest = _manifest_for(CERTIFIED_THROUGH, merged)
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_BUILT_AGAINST_FUTURE_CERTIFIED_THROUGH"):
        validate_merged_authority_coherence(manifest, authority_dir)


def test_manifest_calendar_digest_mismatch_fails_closed(tmp_path) -> None:
    """Section 14 gate 4: the calendar side of the contract is enforced independently of the PIT
    side -- a tampered/mismatched calendar digest fails closed even when the PIT side is fine."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    tampered = replace(manifest, merged_calendar_digest="f" * 64).with_digest()
    with pytest.raises(RollingAuthorityError, match="MERGED_CALENDAR_DIGEST_MISMATCH_WITH_MANIFEST"):
        validate_merged_authority_coherence(tampered, authority_dir)


def test_missing_merged_pit_file_fails_closed(tmp_path) -> None:
    """Section 14 gate 5: a manifest that references a (migrated) merged PIT, but the file itself is
    absent from disk, must fail closed rather than silently skipping the identity guard."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    (authority_dir / "merged_pit_intervals.json").unlink()
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_ARTIFACT_MISSING_FOR_PRODUCTION_ROLLING_MODE"):
        validate_merged_authority_coherence(manifest, authority_dir)


def test_missing_merged_calendar_file_fails_closed(tmp_path) -> None:
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    (authority_dir / "merged_trading_calendar.json").unlink()
    with pytest.raises(RollingAuthorityError, match="MERGED_CALENDAR_ARTIFACT_MISSING_FOR_PRODUCTION_ROLLING_MODE"):
        validate_merged_authority_coherence(manifest, authority_dir)


def test_merged_pit_content_tampered_on_disk_fails_self_check(tmp_path) -> None:
    """A file tampered directly on disk (content changed, stored content_digest left stale) fails
    its OWN self-consistency check before ever reaching the manifest cross-check."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    pit_path = authority_dir / "merged_pit_intervals.json"
    payload = json.loads(pit_path.read_text(encoding="utf-8"))
    payload["intervals"].append(
        {"ticker": "999999", "isu_cd": "KR7999999009", "market": "KOSDAQ", "state": "COMMON",
         "effective_from": "2020-01-01", "effective_to": "2026-09-04"}
    )
    pit_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_CONTENT_DIGEST_SELF_MISMATCH"):
        validate_merged_authority_coherence(manifest, authority_dir)


def test_merged_pit_schema_version_mismatch_fails_closed(tmp_path) -> None:
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    pit_path = authority_dir / "merged_pit_intervals.json"
    payload = json.loads(pit_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "MERGED_PIT_V99_UNKNOWN"
    pit_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RollingAuthorityError, match="MERGED_PIT_SCHEMA_VERSION_MISMATCH"):
        validate_merged_authority_coherence(manifest, authority_dir)


def test_unmigrated_manifest_fails_closed_even_with_valid_files_present(tmp_path) -> None:
    """A pre-hardening manifest (no merged_pit_digest/frontier/schema_version references at all)
    must fail closed in production rolling mode until migrated -- even if a real, valid merged PIT
    file happens to be sitting on disk. No implicit trust of an unreferenced file."""
    authority_dir = tmp_path / "authority"
    write_merged_pit_extension(_EXTENSION, authority_dir, built_against_certified_through=CERTIFIED_THROUGH)
    unmigrated = RollingAuthorityManifest(
        authority_version="ROLLING_MARKET_DATA_V01",
        certified_through=CERTIFIED_THROUGH,
        leg_boundaries={leg: CERTIFIED_THROUGH for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")},
        previous_boundary=None,
        raw_store_version="KRX_RAW_STOCK_V01",
        adjusted_store_version="ADJUSTED_PRICE_STORE_V02",
        instrument_contract_version="REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
        bootstrap_source=None,
        generated_at="2026-09-05T00:00:00+00:00",
    ).with_digest()
    with pytest.raises(RollingAuthorityError, match="ROLLING_MANIFEST_MISSING_MERGED_PIT_REFERENCE"):
        validate_merged_authority_coherence(unmigrated, authority_dir)


def test_full_read_path_pass_through_get_daily(tmp_path) -> None:
    """Section 14 gate 6, exercised end to end: a correctly-published coherence triple lets a real
    MarketDataRepositoryV2.get_daily read through normally, still enforcing the pre-existing identity
    lower-bound clamp on top of the now-validated authority."""
    authority_dir, _manifest, _merged = _publish_valid_authority(tmp_path)

    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    dates = ["2023-05-17", "2025-08-14", "2026-09-04"]
    index = pd.DatetimeIndex(dates)
    frame = pd.DataFrame({"open": [1, 2, 3], "high": [2, 3, 4], "low": [0.5, 1, 2], "close": [1, 2, 3]}, index=index)
    adjusted_store.save_full("446840", frame, {"requested_start": dates[0], "requested_end": dates[-1]})

    raw_store = KrxRawStockStore(tmp_path / "raw")
    for day in dates:
        raw_store.save_snapshot(
            "KOSDAQ", day,
            pd.DataFrame(
                [{"date": day, "ticker": "446840", "open": 1, "high": 2, "low": 0, "close": 1,
                  "volume": 100, "trading_value": 100, "market_cap": 1000, "listed_shares": 100}],
                columns=list(RAW_COLUMNS),
            ),
            "/KOSDAQ",
        )

    repo = MarketDataRepositoryV2(adjusted_store, raw_store, rolling_authority_dir=authority_dir)
    result = repo.get_daily("446840", "2010-01-04", CERTIFIED_THROUGH)

    assert result.index.min().strftime("%Y-%m-%d") == "2025-08-14"  # identity clamp still applies
    assert "2023-05-17" not in result.index.strftime("%Y-%m-%d")


def test_e2e_frozen_mode_never_calls_coherence_check(tmp_path) -> None:
    """Section 9: omitting rolling_authority_dir is a complete no-op -- no coherence validation runs
    at all, even when a tampered/incoherent authority happens to exist on disk somewhere."""
    authority_dir, manifest, _merged = _publish_valid_authority(tmp_path)
    tampered = replace(manifest, merged_pit_digest="BOGUS").with_digest()
    write_rolling_authority(tampered, authority_dir)  # authority on disk is now incoherent

    adjusted_store = AdjustedPriceStore(tmp_path / "adjusted")
    dates = ["2023-05-17", "2026-09-04"]
    index = pd.DatetimeIndex(dates)
    frame = pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [0.5, 1], "close": [1, 2]}, index=index)
    adjusted_store.save_full("446840", frame, {"requested_start": dates[0], "requested_end": dates[-1]})
    raw_store = KrxRawStockStore(tmp_path / "raw")
    for day in dates:
        raw_store.save_snapshot(
            "KOSDAQ", day,
            pd.DataFrame(
                [{"date": day, "ticker": "446840", "open": 1, "high": 2, "low": 0, "close": 1,
                  "volume": 100, "trading_value": 100, "market_cap": 1000, "listed_shares": 100}],
                columns=list(RAW_COLUMNS),
            ),
            "/KOSDAQ",
        )

    repo = MarketDataRepositoryV2(adjusted_store, raw_store)  # no rolling_authority_dir at all
    result = repo.get_daily("446840", "2010-01-04", "2026-09-04")
    assert result.index.min().strftime("%Y-%m-%d") == "2023-05-17"  # unclamped -- coherence check never ran


def test_pykrx_zero_use_guard() -> None:
    for path in (
        Path("src/trend_scanner/data/rolling_market_data_refresh.py"),
        Path("src/trend_scanner/data/repository_v2.py"),
    ):
        source = path.read_text(encoding="utf-8").lower()
        assert "pykrx" not in source, f"{path} must not reference pykrx"
