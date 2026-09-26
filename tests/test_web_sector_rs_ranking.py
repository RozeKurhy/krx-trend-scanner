"""Focused validation for the static Sector RS web payload projection."""

from __future__ import annotations

import importlib.util
import json
import math
import re
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_sector_rs_ranking_web.py"
PAYLOAD_PATH = ROOT / "web/data/sector-rs-ranking.json"
TARGET = "2026-09-21"
RANKING_PATH = ROOT / "data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260921.parquet"
HORIZONS = ("2w", "1m", "3m", "6m", "12m")
PARITY_FIELDS = (
    *(f"sector_rs_{horizon}" for horizon in HORIZONS),
    *(f"within_sector_rs_rank_{horizon}" for horizon in HORIZONS),
    *(f"within_sector_rs_percentile_{horizon}" for horizon in HORIZONS),
    "sector_member_count",
    *(f"sector_eligible_count_{horizon}" for horizon in HORIZONS),
    "latest_close",
    "latest_close_as_of",
    *(f"sector_anchor_date_{horizon}" for horizon in HORIZONS),
    *(f"sector_stock_return_{horizon}" for horizon in HORIZONS),
)


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_sector_rs_ranking_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_payload() -> dict:
    return json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))


def _scalar(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _basic_info() -> dict[str, dict[str, str]]:
    result = {}
    base = ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info/2026/20260921"
    for market in ("KOSPI", "KOSDAQ"):
        rows = json.loads((base / f"{market}.json").read_text(encoding="utf-8"))["OutBlock_1"]
        for row in rows:
            ticker = str(row["ISU_SRT_CD"]).strip().upper()
            result[ticker] = {"name": row["ISU_ABBRV"].strip(), "market": row["MKT_TP_NM"].strip()}
    return result


def test_standalone_source_resolver_uses_latest_basic_info_snapshot_on_or_before_target():
    exporter = _load_exporter()
    _ranking, _meta, basic_info_dir = exporter._resolve_source_paths(
        "2026-09-19", ranking_path=None, meta_path=None, basic_info_dir=None
    )
    assert basic_info_dir.name == "20260918"


def test_sector_rs_mixed_expected_and_reference_dates_fail_closed():
    exporter = _load_exporter()
    with pytest.raises(ValueError, match="SECTOR_RS_EXPECTED_REFERENCE_DATE_MISMATCH"):
        exporter.build_sector_rs_web_payload(
            expected_as_of="2026-09-17",
            reference_market_date="2026-09-18",
        )


def test_sector_rs_missing_expected_and_reference_dates_fail_closed():
    exporter = _load_exporter()
    with pytest.raises(ValueError, match="SECTOR_RS_EXPECTED_AS_OF_REQUIRED"):
        exporter.build_sector_rs_web_payload()


def test_payload_equals_deterministic_exporter_projection():
    exporter = _load_exporter()
    assert _load_payload() == exporter.build_sector_rs_web_payload(
        ranking_path=RANKING_PATH,
        meta_path=RANKING_PATH.with_name("sector_rs_ranking_20260921_meta.json"),
        basic_info_dir=ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info/2026/20260921",
        stocks_dir=ROOT / "web/data/stocks",
        requested_as_of=TARGET,
        reference_market_date=TARGET,
    )


def test_population_scope_and_horizon_counts_are_conserved():
    payload = _load_payload()
    assert payload["schema_version"] == 1
    assert payload["as_of"] == TARGET
    assert payload["horizons"] == ["2w", "1m", "3m", "6m", "12m"]
    assert payload["scope"] == {
        "type": "EXACT_SECTOR_MEMBERSHIP_POPULATION",
        "population_count": 2558,
        "mapped_count": 2435,
        "aggregate_only_count": 88,
        "unmapped_count": 35,
        "sector_group_count": 45,
    }
    assert payload["metric_scope"] == {
        "type": "WITHIN_SECTOR",
        "group_key": ["market", "sector_code"],
        "label": "섹터 RS는 같은 섹터 구성종목끼리 비교",
    }
    assert payload["eligible_counts"] == {
        horizon: sum(item[f"within_sector_rs_rank_{horizon}"] is not None for item in payload["items"])
        for horizon in HORIZONS
    }
    assert len(payload["items"]) == payload["scope"]["population_count"]
    assert len(payload["sectors"]) == 45
    assert sum(item["membership_status"] == "MAPPED" for item in payload["items"]) == payload["scope"]["mapped_count"]
    assert sum(item["membership_status"] == "AGGREGATE_ONLY" for item in payload["items"]) == 88
    assert sum(item["membership_status"] == "UNMAPPED" for item in payload["items"]) == payload["scope"]["unmapped_count"]
    assert sum(sector["member_count"] for sector in payload["sectors"]) == (
        payload["scope"]["mapped_count"] + payload["scope"]["aggregate_only_count"]
    )


def test_exact_name_authority_resolves_every_item_without_stock_index_fallback():
    payload = _load_payload()
    names = _basic_info()
    assert all(item["ticker"] in names for item in payload["items"])
    assert all(
        (item["name"], item["market"]) == (names[item["ticker"]]["name"], names[item["ticker"]]["market"])
        for item in payload["items"]
    )
    assert payload["source"] == {
        "ranking_schema": "SECTOR_RS_RANKING_V01",
        "ranking_as_of": TARGET,
        "name_source_date": "2026-09-21",
    }


def test_all_ranking_values_have_exact_authority_parity():
    payload = _load_payload()
    authority = pd.read_parquet(RANKING_PATH)
    authority["ticker"] = authority["ticker"].astype(str).str.strip().str.upper()
    source_by_ticker = authority.set_index("ticker").to_dict(orient="index")
    assert {item["ticker"] for item in payload["items"]} == set(source_by_ticker)
    for item in payload["items"]:
        source = source_by_ticker[item["ticker"]]
        for field in PARITY_FIELDS:
            assert item[field] == _scalar(source[field]), (item["ticker"], field)


def test_sector_metadata_and_isolation_are_derived_from_items():
    payload = _load_payload()
    by_key = {sector["sector_key"]: sector for sector in payload["sectors"]}
    assert {sector["sector_key"] for sector in payload["sectors"]} == {
        f"{sector['market']}:{sector['sector_code']}" for sector in payload["sectors"]
    }
    for key, group in pd.DataFrame(payload["items"]).groupby("sector_key", dropna=True):
        sector = by_key[key]
        assert sector["member_count"] == len(group)
        assert sector["market"] == group["market"].iloc[0]
        assert sector["sector_code"] == group["sector_code"].iloc[0]
        assert group["sector_name"].nunique() == 1
        for horizon in HORIZONS:
            assert sector[f"eligible_count_{horizon}"] == int(group[f"within_sector_rs_rank_{horizon}"].notna().sum())
    same_name = [sector["sector_key"] for sector in payload["sectors"] if sector["sector_name"] == "제약"]
    assert {"KOSPI:1009", "KOSDAQ:2066"}.issubset(same_name)


def test_unmapped_and_report_availability_preserve_separate_concerns():
    payload = _load_payload()
    unmapped = [item for item in payload["items"] if item["membership_status"] == "UNMAPPED"]
    assert len(unmapped) == payload["scope"]["unmapped_count"]
    for item in unmapped:
        assert item["sector_key"] is None
        assert item["sector_code"] is None
        assert item["sector_name"] is None
        assert all(item[f"within_sector_rs_rank_{horizon}"] is None for horizon in HORIZONS)
        assert all(item[f"within_sector_rs_percentile_{horizon}"] is None for horizon in HORIZONS)

    report_tickers = {path.stem.upper() for path in (ROOT / "web/data/stocks").glob("*.json")}
    ranking_tickers = {item["ticker"] for item in payload["items"]}
    assert {item["ticker"] for item in payload["items"] if item["report_available"]} == ranking_tickers & report_tickers
    assert sum(item["report_available"] for item in payload["items"]) == len(report_tickers & ranking_tickers)
    assert payload["scope"]["population_count"] == len(payload["items"])
    assert payload["eligible_counts"] == {
        horizon: sum(item[f"within_sector_rs_rank_{horizon}"] is not None for item in payload["items"])
        for horizon in HORIZONS
    }


def test_price_and_sector_return_fields_are_exact_or_fail_closed():
    payload = _load_payload()
    assert sum(item["latest_close"] is not None for item in payload["items"]) == 2448
    assert sum(item["latest_close"] is None for item in payload["items"]) == payload["scope"]["population_count"] - 2448
    for item in payload["items"]:
        if item["latest_close"] is None:
            assert item["latest_close_as_of"] is None
        else:
            assert item["latest_close"] > 0
            assert item["latest_close_as_of"] == TARGET
        for horizon in HORIZONS:
            anchor = item[f"sector_anchor_date_{horizon}"]
            stock_return = item[f"sector_stock_return_{horizon}"]
            if stock_return is not None:
                assert anchor is not None
                assert math.isfinite(stock_return)
            if anchor is not None:
                assert anchor <= TARGET

    assert all(
        sum(item[f"sector_stock_return_{horizon}"] is not None for item in payload["items"])
        == payload["eligible_counts"][horizon]
        for horizon in HORIZONS
    )


def test_representative_sector_returns_match_repository_v2_anchor_closes():
    payload = _load_payload()
    by_ticker = {item["ticker"]: item for item in payload["items"]}
    repo = build_repository_v2(ROOT, end=TARGET)
    loader = RepositoryV2DailyLoader(repo, start="2025-01-01", end=TARGET)

    for ticker in ("005930", "000660", "035420", "025980", "0007J0"):
        item = by_ticker[ticker]
        frame = loader.load(ticker)
        assert frame is not None and not frame.empty
        close_by_date = {index.strftime("%Y-%m-%d"): float(value) for index, value in frame["close"].items()}
        end_close = close_by_date[TARGET]
        for horizon in HORIZONS:
            anchor = item[f"sector_anchor_date_{horizon}"]
            expected = None if anchor is None or anchor not in close_by_date else (end_close / close_by_date[anchor]) - 1.0
            actual = item[f"sector_stock_return_{horizon}"]
            if expected is None:
                assert actual is None
            else:
                assert actual == pytest.approx(expected)


def test_payload_has_strict_json_numbers_only():
    raw = PAYLOAD_PATH.read_text(encoding="utf-8")
    assert not re.search(r"(?i)(?<![A-Za-z])[+-]?(?:NaN|Infinity)(?![A-Za-z])", raw)
    json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))
