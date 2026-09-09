"""Focused validation for the static foreign net-buy ranking projection."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_foreign_net_buy_ranking_web.py"
RANKING_PATH = ROOT / "web/data/foreign-net-buy-ranking.json"
FLOW_PATH = ROOT / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260904.parquet"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_foreign_net_buy_ranking_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_ranking() -> dict:
    return json.loads(RANKING_PATH.read_text(encoding="utf-8"))


def test_payload_has_exact_as_of_common_scope_and_reconciliation():
    ranking = _load_ranking()
    assert ranking["schema_version"] == 1
    assert ranking["as_of"] == "2026-09-04"
    assert ranking["scope"]["type"] == "KRX_COMMON_STOCKS"
    assert ranking["scope"]["markets"] == ["KOSPI", "KOSDAQ"]
    assert ranking["scope"]["asset_type"] == "COMMON"
    assert ranking["horizons"] == ["1d", "5d", "10d", "20d", "60d"]
    assert ranking["source"]["as_of"] == "2026-09-04"
    assert ranking["source"]["date_min"] == "2026-05-13"
    assert ranking["source"]["date_max"] == "2026-09-04"
    assert ranking["source"]["trading_session_count"] == 79
    assert ranking["source"]["ticker_count"] == 2715
    assert ranking["source"]["field"] == "foreign_net_buy_value"
    assert ranking["coverage"]["target_common_universe_count"] == 2557
    assert ranking["coverage"]["flow_covered_count"] == 2481
    assert ranking["coverage"]["missing_flow_count"] == 76
    assert ranking["coverage"]["source_extra_non_target_count"] == 234
    assert len(ranking["items"]) == 2557
    assert all(item["asset_type"] == "COMMON" for item in ranking["items"])
    assert {item["market"] for item in ranking["items"]} == {"KOSPI", "KOSDAQ"}


def test_horizon_aggregation_matches_raw_source_for_kospi_and_kosdaq_samples():
    ranking = _load_ranking()
    source = pd.read_parquet(FLOW_PATH)
    source["date"] = source["date"].astype(str)
    source["ticker"] = source["ticker"].astype(str)
    sessions = sorted(source.loc[source["date"] <= "2026-09-04", "date"].unique())
    samples = ["005930", "000660", "035720", "247540", "000020"]

    for ticker in samples:
        item = next(item for item in ranking["items"] if item["ticker"] == ticker)
        for horizon in (1, 5, 20, 60):
            dates = sessions[-horizon:]
            expected = source.loc[source["ticker"].eq(ticker) & source["date"].isin(dates), "foreign_net_buy_value"]
            if len(expected) == horizon:
                assert item[f"foreign_net_buy_{horizon}d"] == float(expected.sum())
            else:
                assert item[f"foreign_net_buy_{horizon}d"] is None


def test_each_horizon_uses_descending_flow_sort_and_keeps_reportless_rows():
    ranking = _load_ranking()
    expected_first = {"1d": "000660", "5d": "316140", "10d": "316140", "20d": "402340", "60d": "009150"}
    for horizon, expected_ticker in expected_first.items():
        rows = [item for item in ranking["items"] if item[f"foreign_net_buy_{horizon}"] is not None]
        ordered = sorted(rows, key=lambda item: (-item[f"foreign_net_buy_{horizon}"], item["name"], item["ticker"]))
        assert ordered[0]["ticker"] == expected_ticker
        assert all(
            ordered[index][f"foreign_net_buy_{horizon}"] >= ordered[index + 1][f"foreign_net_buy_{horizon}"]
            for index in range(len(ordered) - 1)
        )
    reportless = next(item for item in ranking["items"] if item["ticker"] == "000020")
    assert reportless["report_available"] is False
    assert reportless["foreign_net_buy_20d"] is not None


def test_exporter_marks_missing_flow_as_unavailable_not_zero_and_keeps_price_independent(tmp_path):
    exporter = _load_exporter()
    index_path = tmp_path / "index.json"
    sector_path = tmp_path / "sector.parquet"
    index_path.write_text(json.dumps({"schema_version": 1, "universe_snapshot_date": "2026-08-21", "items": [
        {"ticker": "AAA", "name": "Alpha", "market": "KOSPI", "asset_type": "COMMON", "report_available": False},
        {"ticker": "BBB", "name": "Beta", "market": "KOSDAQ", "asset_type": "COMMON", "report_available": False},
    ]}), encoding="utf-8")
    pd.DataFrame({"ticker": ["AAA", "BBB"], "sector_name": ["전기전자", "제약"]}).to_parquet(sector_path)
    dates = [date.strftime("%Y-%m-%d") for date in pd.bdate_range(end="2026-09-04", periods=61)]
    flow = pd.DataFrame(
        [{"date": date, "ticker": "AAA", "foreign_net_buy_value": 100.0} for date in dates]
        + [{"date": dates[-1], "ticker": "BBB", "foreign_net_buy_value": 200.0}]
    )
    flow_path = tmp_path / "foreign_flow_daily_20260904.parquet"
    flow.to_parquet(flow_path)
    (tmp_path / "foreign_flow_daily_20260904_meta.json").write_text(json.dumps({"requested_as_of": dates[-1]}), encoding="utf-8")

    class FakeRepository:
        def get_daily(self, ticker, start, end):
            if ticker == "BBB":
                return pd.DataFrame()
            return pd.DataFrame({"close": list(range(100, 161))}, index=pd.to_datetime(dates))

    result = exporter.build_foreign_net_buy_ranking(
        index_path=index_path,
        flow_path=flow_path,
        sector_path=sector_path,
        repository=FakeRepository(),
        as_of=dates[-1],
    )
    by_ticker = {item["ticker"]: item for item in result["items"]}
    assert by_ticker["AAA"]["foreign_net_buy_1d"] == 100.0
    assert by_ticker["BBB"]["foreign_net_buy_1d"] == 200.0
    assert by_ticker["BBB"]["foreign_net_buy_5d"] is None
    assert by_ticker["BBB"]["latest_close"] is None
    assert result["coverage"]["eligible_counts"]["5d"] == 1


def test_price_and_return_fields_are_exact_session_based():
    exporter = _load_exporter()
    dates = [date.strftime("%Y-%m-%d") for date in pd.date_range(end="2026-09-04", periods=61)]

    class FakeRepository:
        def get_daily(self, ticker, start, end):
            return pd.DataFrame({"close": list(range(100, 161))}, index=pd.to_datetime(dates))

    latest, latest_as_of, returns = exporter._price_fields(FakeRepository(), "AAA", dates, dates[-1])
    assert latest == 160.0
    assert latest_as_of == "2026-09-04"
    assert returns[1] == 160 / 159 - 1
    assert returns[5] == 160 / 155 - 1
    assert returns[60] == 160 / 100 - 1
