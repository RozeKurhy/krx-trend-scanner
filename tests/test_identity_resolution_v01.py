"""Directive COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01 sections 5/16/17: unit-level coverage of
``resolve_current_identity`` and ``write_merged_pit_extension`` independent of the repository/read
path (see test_production_identity_boundary_guard_v01.py for the read-path integration tests)."""

from __future__ import annotations

import json

from trend_scanner.data.rolling_market_data_refresh import (
    IdentityResolution,
    PitExtensionResult,
    resolve_current_identity,
    write_merged_pit_extension,
)


def _iv(ticker, isu_cd, market, eff_from, eff_to):
    return {"ticker": ticker, "isu_cd": isu_cd, "market": market, "state": "COMMON",
            "effective_from": eff_from, "effective_to": eff_to}


def test_single_interval_always_resolved_regardless_of_as_of():
    mapping = {"005930": [_iv("005930", "KR7005930003", "KOSPI", "2010-01-04", "2026-08-21")]}
    res = resolve_current_identity("005930", "2026-08-21", mapping)
    assert res.status == "RESOLVED"
    assert res.interval["effective_from"] == "2010-01-04"

    # even queried well after its own effective_to (a normal already-delisted ticker) -- not ambiguous.
    res2 = resolve_current_identity("005930", "2030-01-01", mapping)
    assert res2.status == "RESOLVED"
    assert res2.interval["effective_from"] == "2010-01-04"


def test_no_intervals_at_all_is_no_open_identity():
    res = resolve_current_identity("999999", "2026-09-04", {})
    assert res.status == "NO_OPEN_IDENTITY"
    assert res.interval is None
    assert res.candidate_intervals == ()


def test_market_transfer_same_isu_cd_combines_into_one_identity():
    mapping = {
        "003670": [
            _iv("003670", "KR7003670007", "KOSDAQ", "2010-01-04", "2019-05-28"),
            _iv("003670", "KR7003670007", "KOSPI", "2019-05-29", "2026-09-04"),
        ]
    }
    res = resolve_current_identity("003670", "2026-09-04", mapping)
    assert res.status == "RESOLVED"
    assert res.interval["effective_from"] == "2010-01-04"
    assert res.interval["effective_to"] == "2026-09-04"
    assert len(res.interval["component_intervals"]) == 2


def test_two_distinct_isu_cd_reuse_resolves_the_one_covering_as_of():
    mapping = {
        "077700": [
            _iv("077700", "KR7077700001", "KOSDAQ", "2012-01-10", "2016-12-31"),
            _iv("077700", "KR7077700099", "KOSDAQ", "2018-01-05", "2026-09-04"),
        ]
    }
    res_current = resolve_current_identity("077700", "2026-09-04", mapping)
    assert res_current.status == "RESOLVED"
    assert res_current.interval["isu_cd"] == "KR7077700099"
    assert res_current.interval["effective_from"] == "2018-01-05"

    res_old = resolve_current_identity("077700", "2015-01-01", mapping)
    assert res_old.status == "RESOLVED"
    assert res_old.interval["isu_cd"] == "KR7077700001"


def test_two_distinct_isu_cd_gap_is_no_open_identity_not_ambiguous():
    mapping = {
        "099100": [
            _iv("099100", "KR7099100001", "KOSDAQ", "2010-01-04", "2012-06-01"),
            _iv("099100", "KR7099100088", "KOSDAQ", "2013-01-01", "2014-12-31"),
        ]
    }
    res = resolve_current_identity("099100", "2026-08-21", mapping)  # after both, in the "gap" beyond both
    assert res.status == "NO_OPEN_IDENTITY"
    assert res.interval is None
    assert len(res.candidate_intervals) == 2


def test_two_distinct_isu_cd_both_covering_as_of_is_ambiguous():
    mapping = {
        "088800": [
            _iv("088800", "KR7088800001", "KOSDAQ", "2015-01-05", "2026-08-21"),
            _iv("088800", "KR7088800099", "KOSPI", "2018-01-01", "2026-08-21"),
        ]
    }
    res = resolve_current_identity("088800", "2020-01-01", mapping)
    assert res.status == "AMBIGUOUS"
    assert res.interval is None
    assert len(res.candidate_intervals) == 2


def test_446840_real_shape_resolves_to_true_identity_not_earliest():
    """The exact real regression: PIT only ever recorded the CURRENT identity (no record of the
    prior, unrelated occupant of the same numeric code) -- resolve_current_identity must never
    invent an earlier effective_from than what the PIT actually certifies."""
    mapping = {"446840": [_iv("446840", "KR7446840001", "KOSDAQ", "2025-08-14", "2026-09-04")]}
    res = resolve_current_identity("446840", "2026-09-04", mapping)
    assert res.status == "RESOLVED"
    assert res.interval["effective_from"] == "2025-08-14"


def test_write_merged_pit_extension_round_trips(tmp_path):
    from trend_scanner.data.adjusted_price_pilot import _load_cached_pit_intervals_by_ticker

    extension = PitExtensionResult(
        merged_intervals=(
            _iv("005930", "KR7005930003", "KOSPI", "2010-01-04", "2026-09-04"),
            _iv("446840", "KR7446840001", "KOSDAQ", "2025-08-14", "2026-09-04"),
        ),
        merged_calendar_dates=("2026-08-21", "2026-09-04"),
        extension_start="2026-08-24",
        extension_end="2026-09-04",
        frozen_interval_count=1,
        merged_interval_count=2,
        new_ticker_count=1,
    )
    directory = tmp_path / "authority"
    result = write_merged_pit_extension(extension, directory, built_against_certified_through="2026-08-21")

    assert (directory / "merged_pit_intervals.json").exists()
    assert (directory / "merged_trading_calendar.json").exists()
    assert result.built_against_certified_through == "2026-08-21"
    assert result.merged_pit_frontier == "2026-09-04"
    assert result.merged_calendar_frontier == "2026-09-04"

    # unique path per test (tmp_path) avoids the lru_cache colliding with another test's fixture
    mapping = _load_cached_pit_intervals_by_ticker(str(directory / "merged_pit_intervals.json"))
    assert mapping["446840"][0]["effective_from"] == "2025-08-14"

    pit_payload = json.loads((directory / "merged_pit_intervals.json").read_text())
    assert pit_payload["schema_version"] == "MERGED_PIT_V01"
    assert pit_payload["content_digest"] == result.merged_pit_digest

    calendar = json.loads((directory / "merged_trading_calendar.json").read_text())
    assert calendar["trading_dates"] == ["2026-08-21", "2026-09-04"]
    assert calendar["schema_version"] == "MERGED_CALENDAR_V01"
    assert calendar["content_digest"] == result.merged_calendar_digest


def test_pykrx_zero_use_guard():
    from pathlib import Path

    source_path = Path("src/trend_scanner/data/rolling_market_data_refresh.py")
    source = source_path.read_text(encoding="utf-8").lower()
    assert "pykrx" not in source, f"{source_path} must not reference pykrx"
