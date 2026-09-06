"""Directive ROLLING_AUTHORITY_HARDENING_V01 section 18-26: removal of the dangerous blanket
``requested_start="2010-01-04"`` default from ``RollingAdjustedPriceUpdater.refresh()`` /
``.refresh_with_extension()`` -- the confirmed root cause of the 202-ticker phantom-row defect
(COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01).

``requested_start=None`` (the new default) resolves EACH ticker's own fetch lower bound
independently from its current certified (ticker, isu_cd, market) identity via
``resolve_current_identity`` -- never a single literal applied uniformly across a heterogeneous
population. An explicit ``requested_start`` string is still honored verbatim for genuinely
historical callers (section 21).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater


def _adjusted_frame(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {"open": [100.0] * len(index), "high": [105.0] * len(index), "low": [95.0] * len(index), "close": [102.0] * len(index)},
        index=index,
    )


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        return _adjusted_frame(start, end)


def _write_pit(pit_path: Path, intervals: list[dict], calendar_path: Path, dates: list[str]) -> None:
    pit_path.write_text(json.dumps({"intervals": intervals}), encoding="utf-8")
    calendar_path.write_text(json.dumps({"trading_dates": dates}), encoding="utf-8")


def _updater(tmp_path: Path, provider: _RecordingProvider, pit_path: Path, calendar_path: Path) -> RollingAdjustedPriceUpdater:
    store = AdjustedPriceStore(tmp_path / "adjusted")
    return RollingAdjustedPriceUpdater(provider, store, pit_path=pit_path, historical_calendar_path=calendar_path)


def test_production_refresh_without_requested_start_resolves_per_identity(tmp_path) -> None:
    """Section 20: two tickers with DIFFERENT identity effective_from must each be fetched from
    THEIR OWN bound, never a single shared value."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [
            {"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2010-01-04", "effective_to": "2026-08-24"},
            {"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2025-08-14", "effective_to": "2026-08-24"},
        ],
        calendar_path,
        ["2026-08-20", "2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    result = updater.refresh(["005930", "446840"], "2026-08-21", "2026-08-24")

    assert set(result["updated"]) == {"005930", "446840"}
    calls_by_ticker = {ticker: (start, end) for ticker, start, end in provider.calls}
    assert calls_by_ticker["005930"] == ("2010-01-04", "2026-08-24")
    assert calls_by_ticker["446840"] == ("2025-08-14", "2026-08-24")  # NEVER 2010-01-04


def test_historical_explicit_requested_start_still_works_unchanged(tmp_path) -> None:
    """Section 21: a genuinely historical caller passing an explicit requested_start still applies
    it verbatim to every ticker in the batch, exactly as before this hardening."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [
            {"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2010-01-04", "effective_to": "2026-08-24"},
            {"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2025-08-14", "effective_to": "2026-08-24"},
        ],
        calendar_path,
        ["2026-08-20", "2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    result = updater.refresh(["005930", "446840"], "2026-08-21", "2026-08-24", requested_start="2010-01-04")

    assert set(result["updated"]) == {"005930", "446840"}
    calls_by_ticker = {ticker: (start, end) for ticker, start, end in provider.calls}
    assert calls_by_ticker["005930"] == ("2010-01-04", "2026-08-24")
    assert calls_by_ticker["446840"] == ("2010-01-04", "2026-08-24")  # explicit override, applied verbatim


def test_446840_regression_resolved_requested_start_never_predates_identity(tmp_path) -> None:
    """Section 23: the real 446840 shape -- with requested_start=None, the fetch lower bound used
    must be >= the identity's own effective_from (2025-08-14), never the old blanket 2010-01-04."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [{"ticker": "446840", "isu_cd": "KR7446840001", "market": "KOSDAQ", "state": "COMMON",
          "effective_from": "2025-08-14", "effective_to": "2026-09-04"}],
        calendar_path,
        ["2026-08-21", "2026-09-04"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    updater.refresh(["446840"], "2026-08-21", "2026-09-04")

    (_ticker, resolved_start, _end) = provider.calls[0]
    assert resolved_start >= "2025-08-14"


def test_ticker_with_no_open_identity_is_skipped_not_blanket_fetched(tmp_path) -> None:
    """A ticker absent from the PIT entirely must be SKIPPED, never silently fetched from an
    arbitrary blanket start -- fail-closed on the write side too, mirroring the read-side guard."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [{"ticker": "005930", "isu_cd": "KR7005930003", "market": "KOSPI", "state": "COMMON",
          "effective_from": "2010-01-04", "effective_to": "2026-08-24"}],
        calendar_path,
        ["2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    result = updater.refresh(["999999"], "2026-08-21", "2026-08-24")

    assert result["updated"] == []
    assert provider.calls == []
    assert result["skipped"] == [{"ticker": "999999", "reason": "IDENTITY_NO_OPEN_IDENTITY"}]


def test_ambiguous_identity_ticker_is_skipped_not_blanket_fetched(tmp_path) -> None:
    """Two candidate identities both covering as_of must be SKIPPED (fail closed), never fetched
    against an arbitrarily-chosen one."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [
            {"ticker": "088800", "isu_cd": "KR7088800001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2015-01-05", "effective_to": "2026-08-24"},
            {"ticker": "088800", "isu_cd": "KR7088800099", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2018-01-01", "effective_to": "2026-08-24"},
        ],
        calendar_path,
        ["2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    result = updater.refresh(["088800"], "2026-08-21", "2026-08-24")

    assert result["updated"] == []
    assert provider.calls == []
    assert result["skipped"] == [{"ticker": "088800", "reason": "IDENTITY_AMBIGUOUS"}]


def test_market_transfer_uses_earliest_combined_effective_from(tmp_path) -> None:
    """Section 24-26: a market transfer (same isu_cd) is ONE identity spanning the union of both
    market-tagged rows -- the fetch lower bound must be the EARLIEST of the combined range, not the
    most recent leg's own effective_from, so the full real history is fetched."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [
            {"ticker": "003670", "isu_cd": "KR7003670007", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2010-01-04", "effective_to": "2019-05-28"},
            {"ticker": "003670", "isu_cd": "KR7003670007", "market": "KOSPI", "state": "COMMON",
             "effective_from": "2019-05-29", "effective_to": "2026-08-24"},
        ],
        calendar_path,
        ["2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    updater.refresh(["003670"], "2026-08-21", "2026-08-24")

    (_ticker, resolved_start, _end) = provider.calls[0]
    assert resolved_start == "2010-01-04"  # the union's earliest bound, not 2019-05-29


def test_recycled_ticker_uses_current_occupants_effective_from_never_predecessor(tmp_path) -> None:
    """Section 24-26: a genuinely reused ticker code (distinct isu_cd) must fetch only the CURRENT
    occupant's own range -- never reaching back into a prior, unrelated security's history."""
    pit_path, calendar_path = tmp_path / "pit.json", tmp_path / "calendar.json"
    _write_pit(
        pit_path,
        [
            {"ticker": "077700", "isu_cd": "KR7077700001", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2012-01-10", "effective_to": "2016-12-31"},
            {"ticker": "077700", "isu_cd": "KR7077700099", "market": "KOSDAQ", "state": "COMMON",
             "effective_from": "2018-01-05", "effective_to": "2026-08-24"},
        ],
        calendar_path,
        ["2026-08-21", "2026-08-24"],
    )
    provider = _RecordingProvider()
    updater = _updater(tmp_path, provider, pit_path, calendar_path)

    updater.refresh(["077700"], "2026-08-21", "2026-08-24")

    (_ticker, resolved_start, _end) = provider.calls[0]
    assert resolved_start == "2018-01-05"  # current occupant only, never 2012-01-10
