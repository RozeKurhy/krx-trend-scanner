"""Focused Stock Report v0.4 / Sector RS tests.

These tests use only local fixtures and the existing relative-strength engine;
they do not invoke a scanner or any network source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft7Validator

from trend_scanner.reporting.models import SectorRelativeStrengthSection
from trend_scanner.reporting.sector_relative_strength_report import (
    build_sector_relative_strength_section,
)
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, tuple[str, str, str, str]]]:
    dates = pd.date_range("2025-07-14", periods=300, freq="B")
    stock = pd.DataFrame({"close": 100.0 + pd.Series(range(len(dates)), index=dates, dtype=float)}, index=dates)
    stock.attrs["data_authority"] = "MarketDataRepositoryV2"
    sector = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "index_code": "2066",
            "close": 200.0 + pd.Series(range(len(dates)), dtype=float).to_numpy() * 0.5,
        }
    )
    mapping = {"001540": ("2066", "제약", "2026-09-04", "MAPPED")}
    return stock, sector, mapping


def test_sector_builder_reuses_engine_and_requested_snapshot_provenance(synthetic_inputs):
    stock, sector, mapping = synthetic_inputs
    section = build_sector_relative_strength_section(
        ticker="001540",
        requested_as_of=sector["date"].iloc[-1],
        asset_type="COMMON",
        market="KOSDAQ",
        stock_df=stock,
        repo_root=ROOT,
        sector_index_df=sector,
        sector_mapping=mapping,
    )
    assert isinstance(section, SectorRelativeStrengthSection)
    assert section.applicability == "APPLICABLE"
    assert section.data_status == "READY"
    assert section.sector_name == "제약"
    assert section.sector_code == "2066"
    assert section.benchmark_code == "2066"
    assert section.benchmark_last_observation_date == sector["date"].iloc[-1]
    assert all(
        getattr(section, field) is not None
        for field in ("sector_rs_2w", "sector_rs_1m", "sector_rs_3m", "sector_rs_6m", "sector_rs_12m")
    )
    assert all(
        getattr(section, field) is not None
        for field in (
            "sector_return_2w", "sector_return_1m", "sector_return_3m",
            "sector_return_6m", "sector_return_12m",
            "sector_anchor_date_2w", "sector_anchor_date_1m", "sector_anchor_date_3m",
            "sector_anchor_date_6m", "sector_anchor_date_12m",
        )
    )
    assert section.membership_snapshot_date == "2026-09-04"
    assert section.membership_source == "data/market/sector_membership/v01/sector_membership_20260904.parquet"
    assert section.sector_index_source.endswith("sector_index_daily.parquet")


def test_sector_builder_unmapped_and_etf_fail_closed(synthetic_inputs):
    stock, sector, mapping = synthetic_inputs
    unmapped = build_sector_relative_strength_section(
        ticker="066670",
        requested_as_of=sector["date"].iloc[-1],
        asset_type="COMMON",
        market="KOSDAQ",
        stock_df=stock,
        repo_root=ROOT,
        sector_index_df=sector,
        sector_mapping=mapping,
    )
    assert unmapped.applicability == "APPLICABLE"
    assert unmapped.data_status == "DATA_UNAVAILABLE"
    assert unmapped.input_reason == "SECTOR_MEMBERSHIP_UNMAPPED"
    assert unmapped.sector_rs_3m is None

    etf = build_sector_relative_strength_section(
        ticker="069500",
        requested_as_of=sector["date"].iloc[-1],
        asset_type="ETF",
        market="KOSPI",
        stock_df=None,
        repo_root=ROOT,
        sector_index_df=sector,
        sector_mapping=mapping,
    )
    assert etf.applicability == "NOT_APPLICABLE"
    assert etf.data_status == "NOT_EVALUATED"
    assert all(
        getattr(etf, field) is None
        for field in ("sector_rs_2w", "sector_rs_1m", "sector_rs_3m", "sector_rs_6m", "sector_rs_12m")
    )


def test_v04_generator_schema_and_markdown_additive_contract():
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=ROOT,
        save_artifacts=False,
    )
    payload = report.to_dict()
    assert report.report_version == "0.4"
    assert "relative_strength" in payload
    assert "sector_relative_strength" in payload
    schema = json.loads((ROOT / "docs/reporting/stock_report/schema_v04.json").read_text(encoding="utf-8"))
    assert list(Draft7Validator(schema).iter_errors(payload)) == []
    markdown = render_markdown_report(report)
    assert "종목 리포트 v0.4" in markdown
    assert "## 7.5. 시장 상대강도 (RS)" in markdown
    assert "## 7.6. 업종 상대강도 (Sector RS)" in markdown
    assert markdown.index("## 7.5. 시장 상대강도 (RS)") < markdown.index("## 7.6. 업종 상대강도 (Sector RS)") < markdown.index("## 8. 거래대금")
