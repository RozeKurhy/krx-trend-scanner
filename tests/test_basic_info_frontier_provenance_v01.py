"""Directive ROLLING_AUTHORITY_FINAL_CLOSURE_V01 section 20-24: source_basic_info_frontier must be
the rolling Basic Info authority's own DATE frontier, never an ISO-8601 acquisition completed_at_utc
timestamp -- that is a structurally different concept and belongs in the separate
source_basic_info_acquired_at_utc field instead.
"""

from __future__ import annotations

import pytest

from trend_scanner.data.rolling_market_data_refresh import (
    RollingAuthorityError,
    validate_basic_info_frontier_field,
)


def test_valid_date_frontier_passes():
    validate_basic_info_frontier_field("2026-09-04", "2026-09-04")


def test_iso_timestamp_used_as_frontier_fails_closed():
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_INVALID_TYPE"):
        validate_basic_info_frontier_field("2026-08-26T22:11:36Z", "2026-09-04")


def test_iso_timestamp_with_microseconds_and_offset_also_fails_closed():
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_INVALID_TYPE"):
        validate_basic_info_frontier_field("2026-08-26T22:11:36.145506+00:00", "2026-09-04")


def test_frontier_exceeding_target_as_of_fails_closed():
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_EXCEEDS_TARGET_AS_OF"):
        validate_basic_info_frontier_field("2026-09-10", "2026-09-04")


def test_frontier_below_required_authority_fails_closed():
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_INSUFFICIENT_AUTHORITY"):
        validate_basic_info_frontier_field(
            "2026-08-20", "2026-09-04", required_authority_frontier="2026-09-04"
        )


def test_frontier_meeting_required_authority_passes():
    validate_basic_info_frontier_field(
        "2026-09-04", "2026-09-04", required_authority_frontier="2026-09-04"
    )


def test_non_string_frontier_fails_closed():
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_INVALID_TYPE"):
        validate_basic_info_frontier_field(None, "2026-09-04")  # type: ignore[arg-type]


def test_write_merged_pit_extension_rejects_timestamp_frontier(tmp_path):
    from trend_scanner.data.rolling_market_data_refresh import PitExtensionResult, write_merged_pit_extension

    extension = PitExtensionResult(
        merged_intervals=({"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI",
                            "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-09-04"},),
        merged_calendar_dates=("2026-09-04",),
        extension_start="2026-08-24",
        extension_end="2026-09-04",
        frozen_interval_count=1,
        merged_interval_count=1,
        new_ticker_count=0,
    )
    with pytest.raises(RollingAuthorityError, match="SOURCE_BASIC_INFO_FRONTIER_INVALID_TYPE"):
        write_merged_pit_extension(
            extension, tmp_path / "authority",
            built_against_certified_through="2026-09-04",
            source_basic_info_frontier="2026-08-26T22:11:36.145506+00:00",
        )
    # Fail-closed BEFORE any file is written -- no partial/tampered publish.
    assert not (tmp_path / "authority" / "merged_pit_intervals.json").exists()


def test_write_merged_pit_extension_accepts_valid_frontier_and_separate_acquired_at(tmp_path):
    from trend_scanner.data.rolling_market_data_refresh import PitExtensionResult, write_merged_pit_extension
    import json

    extension = PitExtensionResult(
        merged_intervals=({"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI",
                            "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-09-04"},),
        merged_calendar_dates=("2026-09-04",),
        extension_start="2026-08-24",
        extension_end="2026-09-04",
        frozen_interval_count=1,
        merged_interval_count=1,
        new_ticker_count=0,
    )
    authority_dir = tmp_path / "authority"
    write_merged_pit_extension(
        extension, authority_dir,
        built_against_certified_through="2026-09-04",
        source_basic_info_frontier="2026-09-04",
        source_basic_info_acquired_at_utc="2026-09-05T07:22:12.185416+00:00",
    )
    payload = json.loads((authority_dir / "merged_pit_intervals.json").read_text())
    assert payload["source_basic_info_frontier"] == "2026-09-04"
    assert payload["source_basic_info_acquired_at_utc"] == "2026-09-05T07:22:12.185416+00:00"
