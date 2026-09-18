"""Focused offline contracts for COMMON RAW session classification guard FIX07."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.rolling_market_data_refresh import (
    RollingAdjustedPriceUpdater,
    _load_production_raw_coverage_authority,
)


BOUNDARY = "2026-08-21"
TARGET = "2026-08-24"


def _frame(days: list[str]) -> pd.DataFrame:
    values = [10.0 + index for index in range(len(days))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 2 for value in values],
            "low": [value - 1 for value in values],
            "close": [value + 1 for value in values],
        },
        index=pd.DatetimeIndex(days),
    )


def _row(ticker: str, state: str) -> dict[str, object]:
    if state == "USABLE":
        return {
            "ticker": ticker,
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 100,
            "trading_value": 1000,
        }
    if state == "CONFIRMED_NONTRADING":
        return {
            "ticker": ticker,
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 11,
            "volume": 0,
            "trading_value": 0,
        }
    return {
        "ticker": ticker,
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 11,
        "volume": 100,
        "trading_value": 1000,
    }


class _RawAuthority:
    def __init__(self, rows_by_day: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_day = rows_by_day

    def list_manifest(self, market: str | None = None) -> list[dict[str, str]]:
        if market != "KOSPI":
            return []
        return [
            {"market": market, "date": day, "status": "COMPLETE"}
            for day in sorted(self.rows_by_day)
        ]

    def load_snapshot(self, market: str, day: str) -> pd.DataFrame:
        return pd.DataFrame(self.rows_by_day.get(day, []))


def _authority_paths(tmp_path: Path, target: str = TARGET) -> tuple[Path, Path]:
    pit = tmp_path / "pit.json"
    calendar = tmp_path / "calendar.json"
    pit.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "ticker": "000001",
                        "isu_cd": "KR7000000001",
                        "market": "KOSPI",
                        "state": "COMMON",
                        "effective_from": "2020-01-01",
                        "effective_to": target,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calendar.write_text(json.dumps({"trading_dates": [BOUNDARY, target]}), encoding="utf-8")
    return pit, calendar


def _updater(tmp_path: Path, raw: _RawAuthority, provider=None) -> tuple[RollingAdjustedPriceUpdater, AdjustedPriceStore]:
    pit, calendar = _authority_paths(tmp_path)
    store = AdjustedPriceStore(tmp_path / "adjusted")
    return (
        RollingAdjustedPriceUpdater(
            provider,
            store,
            pit_path=pit,
            historical_calendar_path=calendar,
            production_raw_store=raw,
        ),
        store,
    )


def test_raw_authority_separates_usable_confirmed_nontrading_and_unresolved(tmp_path):
    raw = _RawAuthority(
        {
            "2026-08-22": [_row("000001", "USABLE")],
            "2026-08-23": [_row("000001", "CONFIRMED_NONTRADING")],
            "2026-08-24": [_row("000001", "NONUSABLE")],
        }
    )

    authority = _load_production_raw_coverage_authority(
        raw,
        start_date="2026-08-22",
        end_date=TARGET,
    )

    key = ("KOSPI", "000001")
    assert authority.observed_dates_by_market_ticker[key] == frozenset({"2026-08-22"})
    assert authority.confirmed_nontrading_dates_by_market_ticker[key] == frozenset({"2026-08-23"})
    assert authority.unresolved_dates_by_market_ticker[key] == {
        "2026-08-24": "ADJUDICATED_SOURCE_NONUSABLE"
    }


def test_confirmed_nontrading_is_excluded_without_blocking_or_fetch(tmp_path):
    raw = _RawAuthority({TARGET: [_row("000001", "CONFIRMED_NONTRADING")]})
    updater, store = _updater(tmp_path, raw)

    plan = updater.plan(["000001"], BOUNDARY, TARGET)

    assert plan["blocked"] == []
    record = plan["ticker_records"][0]
    assert record["status"] == "ZERO_COVERAGE"
    assert record["reason"] == "NO_PRODUCTION_RAW_OBSERVATIONS"

    result = updater.refresh(["000001"], BOUNDARY, TARGET)

    assert result["blocked"] == []
    assert result["failures"] == []
    assert result["skipped"][0]["reason"] == "NO_PRODUCTION_RAW_OBSERVATIONS"
    assert result["new_boundary"] == BOUNDARY
    assert not store.exists("000001")


def test_unresolved_raw_row_blocks_plan_and_refresh_without_provider_or_write(tmp_path):
    raw = _RawAuthority({TARGET: [_row("000001", "NONUSABLE")]})

    class Provider:
        calls: list[tuple[str, str, str]] = []

        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            self.calls.append((ticker, start, end))
            raise AssertionError("unresolved RAW row must block before provider call")

    provider = Provider()
    updater, store = _updater(tmp_path, raw, provider)

    plan = updater.plan(["000001"], BOUNDARY, TARGET)
    plan_record = plan["blocked"][0]
    assert plan_record["status"] == "BLOCKED"
    assert plan_record["reason"] == "UNRESOLVED_PRODUCTION_RAW_OBSERVATION"
    assert plan_record["unresolved_raw_observations"] == [
        {
            "ticker": "000001",
            "date": TARGET,
            "classification": "ADJUDICATED_SOURCE_NONUSABLE",
            "reason": "PRODUCTION_RAW_OBSERVATION_NOT_USABLE_OR_UNRESOLVED",
        }
    ]

    result = updater.refresh(["000001"], BOUNDARY, TARGET)

    assert result["blocked"] == [plan_record]
    assert result["failures"] == []
    assert result["updated"] == []
    assert result["new_boundary"] == BOUNDARY
    assert provider.calls == []
    assert not store.exists("000001")
