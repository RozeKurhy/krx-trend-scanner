from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.backfill_krx_etf_repository_v2_v01 import ACCEPTANCE_TICKERS
from scripts.export_etf_ranking_web import ETF_UNIVERSE
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    RollingEtfAdjustedUpdater,
)


ROOT = Path(__file__).resolve().parents[1]

OFFICIAL_GROUP_TICKERS = {
    "MARKET": {
        "069500", "229200", "133690", "360750", "241180", "283580", "453810", "245710",
        "256440", "195980", "379790", "251350",
    },
    "SECTOR": {
        "091160", "091180", "091170", "102970", "140700", "117700", "117680", "117460",
        "139230", "157490", "143860", "266410", "228790", "228810", "228800", "300950",
        "305720", "449450", "367760",
    },
    "COMMODITY": {"411060", "144600", "160580", "261220", "271060"},
}
OFFICIAL_36 = set().union(*OFFICIAL_GROUP_TICKERS.values())
NEW_17 = {
    "283580", "453810", "245710", "256440", "195980", "379790", "251350", "228790",
    "228810", "228800", "449450", "367760", "411060", "144600", "160580", "261220",
    "271060",
}


def test_official_universe_matches_rolling_repository_and_ranking_exactly():
    rolling = tuple(ETF_VALIDATED_ACCEPTANCE_TICKERS)
    repository = tuple(ACCEPTANCE_TICKERS)
    ranking = tuple(ticker for ticker, _group, _category in ETF_UNIVERSE)

    assert len(rolling) == len(set(rolling)) == 36
    assert len(repository) == len(set(repository)) == 36
    assert len(ranking) == len(set(ranking)) == 36
    assert set(rolling) == set(repository) == set(ranking) == OFFICIAL_36
    assert NEW_17 <= set(rolling)
    assert "474800" not in set(rolling)
    assert {group: len(tickers) for group, tickers in OFFICIAL_GROUP_TICKERS.items()} == {
        "MARKET": 12, "SECTOR": 19, "COMMODITY": 5,
    }
    ranked_by_group = {
        group: {ticker for ticker, value, _category in ETF_UNIVERSE if value == group}
        for group in OFFICIAL_GROUP_TICKERS
    }
    assert ranked_by_group == OFFICIAL_GROUP_TICKERS


def test_daily_update_and_market_refresh_use_the_live_etf_acceptance_scope():
    for relative_path in ("scripts/run_daily_update_v01.py", "scripts/refresh_market_data_v01.py"):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "ETF_VALIDATED_ACCEPTANCE_TICKERS" in source
        assert "RollingEtfAdjustedUpdater" in source


def test_rolling_dry_run_reuses_current_history_and_only_plans_next_session():
    sessions = (
        "2023-01-03", "2023-01-05", "2023-04-21", "2026-09-23", "2026-09-24",
    )

    class RawStore:
        def list_manifest(self, market):
            if market in {"KOSPI", "ETF"}:
                return [{"date": day, "status": "COMPLETE"} for day in sessions]
            return []

        def load_snapshot(self, market, day):
            tickers = set(OFFICIAL_36)
            if day < "2023-04-21":
                tickers.discard("453810")
            if day < "2023-01-05":
                tickers.discard("449450")
            return pd.DataFrame({"ticker": sorted(tickers)})

    class AdjustedStore:
        writes = 0

        def exists(self, ticker):
            return ticker in OFFICIAL_36

        def load_daily(self, ticker):
            first = (
                "2023-04-21" if ticker == "453810"
                else "2023-01-05" if ticker == "449450"
                else "2023-01-03"
            )
            existing = [day for day in sessions[:-1] if day >= first]
            return pd.DataFrame(index=pd.to_datetime(existing))

    adjusted_store = AdjustedStore()
    updater = RollingEtfAdjustedUpdater(None, adjusted_store, raw_store=RawStore())

    current_plan = updater.plan("2026-09-23", "2026-09-23")
    next_session_plan = updater.plan("2026-09-23", "2026-09-24")

    current_records = {row["ticker"]: row for row in current_plan["ticker_records"]}
    next_records = {row["ticker"]: row for row in next_session_plan["ticker_records"]}
    assert set(current_records) == set(next_records) == OFFICIAL_36
    assert current_plan["missing_date_count"] == 0
    assert next_session_plan["missing_dates"] == ["2026-09-24"]
    assert all(row["missing_dates"] == [] for row in current_records.values())
    assert all(row["missing_dates"] == ["2026-09-24"] for row in next_records.values())
    assert current_records["453810"]["required_start"] == "2023-04-21"
    assert current_records["449450"]["required_start"] == "2023-01-05"
    assert adjusted_store.writes == 0
