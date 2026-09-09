"""Focused validation for the static foreign net-buy ranking projection."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import subprocess

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_foreign_net_buy_ranking_web.py"
RANKING_PATH = ROOT / "web/data/foreign-net-buy-ranking.json"
FLOW_PATH = ROOT / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260904.parquet"
COMMON_AUTHORITY_PATH = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_20260904.csv"


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
    assert ranking["scope"]["universe_snapshot_date"] == "2026-09-04"
    assert ranking["scope"]["universe_authority_path"].endswith(
        "market_rs_universe_20260904.csv"
    )
    assert ranking["horizons"] == ["1d", "5d", "10d", "20d", "60d"]
    assert ranking["source"]["as_of"] == "2026-09-04"
    assert ranking["source"]["date_min"] == "2026-05-13"
    assert ranking["source"]["date_max"] == "2026-09-04"
    assert ranking["source"]["trading_session_count"] == 79
    assert ranking["source"]["ticker_count"] == 2715
    assert ranking["source"]["field"] == "foreign_net_buy_value"
    assert ranking["coverage"]["target_common_universe_count"] == 2555
    assert ranking["coverage"]["target_market_counts"] == {"KOSPI": 809, "KOSDAQ": 1746}
    assert ranking["coverage"]["flow_covered_count"] == 2480
    assert ranking["coverage"]["missing_flow_count"] == 75
    assert ranking["coverage"]["source_extra_non_target_count"] == 235
    assert len(ranking["items"]) == 2555
    assert all(item["asset_type"] == "COMMON" for item in ranking["items"])
    assert {item["market"] for item in ranking["items"]} == {"KOSPI", "KOSDAQ"}


def test_payload_items_match_exact_20260904_common_authority():
    ranking = _load_ranking()
    authority = pd.read_csv(COMMON_AUTHORITY_PATH, dtype=str)
    expected = {
        (row.ticker, row.name, row.market)
        for row in authority.itertuples(index=False)
        if row.market in {"KOSPI", "KOSDAQ"}
    }
    actual = {(item["ticker"], item["name"], item["market"]) for item in ranking["items"]}
    assert actual == expected


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


def test_each_horizon_eligible_count_matches_valid_numeric_payload_values():
    ranking = _load_ranking()

    def valid_flow(value):
        return value is not None and value != "" and math.isfinite(float(value))

    for horizon in ranking["horizons"]:
        field = f"foreign_net_buy_{horizon}"
        count = sum(valid_flow(item[field]) for item in ranking["items"])
        assert count == ranking["coverage"]["eligible_counts"][horizon]


def test_foreign_js_flow_validator_distinguishes_null_zero_and_negative():
    result = subprocess.run(
        ["node", "-e", r'''
const fs = require("fs");
const source = fs.readFileSync("web/js/foreign.js", "utf8");
const match = source.match(/function validFlow\(value\) \{[\s\S]*?\n  \}/);
if (!match) process.exit(1);
const validFlow = Function(`return (${match[0]});`)();
if (validFlow(null) || validFlow("") || validFlow(undefined) || validFlow(NaN) || validFlow(Infinity)) process.exit(2);
if (!validFlow(0) || !validFlow(-1) || !validFlow(1)) process.exit(3);
if (!source.includes(".filter((item) => validFlow(item[field]))")) process.exit(4);
'''],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_exporter_marks_missing_flow_as_unavailable_not_zero_and_keeps_price_independent(tmp_path):
    exporter = _load_exporter()
    index_path = tmp_path / "index.json"
    sector_path = tmp_path / "sector.parquet"
    authority_path = tmp_path / "market_rs_universe_20260904.csv"
    index_path.write_text(json.dumps({"schema_version": 1, "universe_snapshot_date": "2026-08-21", "items": [
        {"ticker": "AAA", "name": "Alpha", "market": "KOSPI", "asset_type": "COMMON", "report_available": False},
        {"ticker": "BBB", "name": "Beta", "market": "KOSDAQ", "asset_type": "COMMON", "report_available": False},
    ]}), encoding="utf-8")
    pd.DataFrame({"ticker": ["AAA", "BBB"], "sector_name": ["전기전자", "제약"]}).to_parquet(sector_path)
    pd.DataFrame(
        {"ticker": ["AAA", "BBB"], "name": ["Alpha", "Beta"], "market": ["KOSPI", "KOSDAQ"]}
    ).to_csv(authority_path, index=False)
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
        common_authority_path=authority_path,
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
