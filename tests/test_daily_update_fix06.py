"""Focused offline contracts for COMMON adjusted production-coverage alignment."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    RollingAdjustedPriceUpdater,
    load_effective_common_adjusted_population,
)


BOUNDARY = "2026-08-21"
TRADING_DATES = [BOUNDARY, "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"]


def _frame(days: list[str], base: float = 10.0) -> pd.DataFrame:
    values = [base + index for index in range(len(days))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 2 for value in values],
            "low": [value - 1 for value in values],
            "close": [value + 1 for value in values],
        },
        index=pd.DatetimeIndex(days),
    )


class _RawAuthority:
    def __init__(self, observed_by_day: dict[str, list[str]]) -> None:
        self.observed_by_day = observed_by_day

    def list_manifest(self, market: str | None = None) -> list[dict[str, str]]:
        if market != "KOSPI":
            return []
        return [
            {"market": market, "date": day, "status": "COMPLETE"}
            for day in TRADING_DATES[1:]
        ]

    def load_snapshot(self, market: str, day: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "volume": 100,
                    "trading_value": 1000,
                }
                for ticker in self.observed_by_day.get(day, [])
            ]
        )


def _authority_paths(tmp_path: Path) -> tuple[Path, Path]:
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
                        "effective_to": "2026-08-27",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calendar.write_text(json.dumps({"trading_dates": TRADING_DATES}), encoding="utf-8")
    return pit, calendar


def _updater(tmp_path: Path, raw: _RawAuthority, existing: list[str]) -> RollingAdjustedPriceUpdater:
    pit, calendar = _authority_paths(tmp_path)
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame(existing), {"requested_start": existing[0], "requested_end": existing[-1]})
    return RollingAdjustedPriceUpdater(
        None,
        store,
        pit_path=pit,
        historical_calendar_path=calendar,
        production_raw_store=raw,
    )


def test_target_population_excludes_lifecycle_zero_store_and_etf(tmp_path):
    pit = tmp_path / "pit.json"
    pit.write_text(
        json.dumps(
            {
                "intervals": [
                    {"ticker": "000001", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-20"},
                    {"ticker": "000002", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-27"},
                    {"ticker": ETF_VALIDATED_ACCEPTANCE_TICKERS[0], "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-27"},
                    {"ticker": "000003", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-27"},
                    {"ticker": "000004", "isu_cd": "KR7000000004", "market": "KOSPI", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-27"},
                ]
            }
        ),
        encoding="utf-8",
    )
    zero_store = tmp_path / "zero_store.json"
    zero_store.write_text(json.dumps({"tickers": ["000003"]}), encoding="utf-8")
    removed = tmp_path / "removed.json"
    removed.write_text(
        json.dumps({"removed_identities": [{
            "ticker": "000004",
            "isu_cd": "KR7000000004",
            "market": "KOSPI",
            "effective_from": "2020-01-01",
        }]}),
        encoding="utf-8",
    )

    assert load_effective_common_adjusted_population(
        pit,
        etf_acceptance_tickers=ETF_VALIDATED_ACCEPTANCE_TICKERS,
        removed_identity_audit_path=removed,
        zero_store_contract_path=zero_store,
        effective_population_path=None,
        identity_as_of="2026-08-27",
    ) == ["000002"]


def test_production_raw_presence_is_required_and_absent_ticker_session_is_not(tmp_path):
    raw = _RawAuthority(
        {
            "2026-08-24": ["000001"],
            "2026-08-25": ["000001"],
            "2026-08-26": [],
            "2026-08-27": ["000001"],
        }
    )
    updater = _updater(tmp_path, raw, ["2026-08-24", "2026-08-27"])

    plan = updater.plan(["000001"], BOUNDARY, "2026-08-27")
    record = plan["ticker_records"][0]
    assert record["required_start"] == "2026-08-24"
    assert record["required_end"] == "2026-08-27"
    assert record["required_date_count"] == 3
    assert record["missing_dates"] == ["2026-08-25"]
    assert "2026-08-26" not in record["missing_dates"]


def test_production_raw_middle_gap_and_current_tail_are_detected_by_refresh(tmp_path):
    raw = _RawAuthority(
        {
            "2026-08-24": ["000001"],
            "2026-08-25": ["000001"],
            "2026-08-26": ["000001"],
            "2026-08-27": ["000001"],
        }
    )
    pit, calendar = _authority_paths(tmp_path)
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame(["2026-08-24", "2026-08-26"]), {
        "requested_start": "2026-08-24",
        "requested_end": "2026-08-26",
    })

    class Provider:
        calls: list[tuple[str, str, str]] = []

        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            self.calls.append((ticker, start, end))
            return _frame([start] if start == end else ["2026-08-25", "2026-08-27"], base=20)

    provider = Provider()
    updater = RollingAdjustedPriceUpdater(
        provider,
        store,
        pit_path=pit,
        historical_calendar_path=calendar,
        production_raw_store=raw,
    )
    result = updater.refresh(["000001"], BOUNDARY, "2026-08-27")

    assert provider.calls == [
        ("000001", "2026-08-25", "2026-08-25"),
        ("000001", "2026-08-27", "2026-08-27"),
    ]
    assert result["updated"] == ["000001"]


def test_daily_update_population_loader_uses_target_active_common(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    import run_daily_update_v01

    pit = tmp_path / "pit.json"
    pit.write_text(
        json.dumps(
            {
                "intervals": [
                    {"ticker": "000001", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-20"},
                    {"ticker": "000002", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-08-27"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert run_daily_update_v01._load_common_tickers(pit, "2026-08-27") == ["000002"]
