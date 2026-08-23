"""Targeted tests for the Stock Report v0.3 Phase 12 RS integration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from trend_scanner.reporting.relative_strength_report import (
    PHASE12_CLOSURE_SHA,
    RS_ARTIFACT_TEMPLATE,
    load_relative_strength_section,
)
from trend_scanner.reporting.stock_report import render_markdown_report


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO_ROOT / "artifacts/reporting/stock_reports/20260814"
RS_RELATIVE_PATH = RS_ARTIFACT_TEMPLATE.format(date="20260814")


def _load_report(stem: str) -> dict:
    return json.loads((REPORT_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def test_report_v03_has_exact_rs_values_and_provenance_for_005930():
    report = _load_report("005930_삼성전자")
    rs = report["relative_strength"]
    assert report["report_version"] == "0.3"
    assert rs["applicability"] == "APPLICABLE"
    assert rs["data_status"] == "READY"
    assert rs["market_rs_3m"] == 0.06072554451329215
    assert rs["market_rs_6m"] == 0.26228183720079623
    assert rs["market_rs_12m"] == 0.7810181942942702
    assert rs["all_market_rs_percentile_3m"] == 59.89826197541331
    assert rs["source_as_of"] == "2026-08-14"
    assert rs["source_artifact"] == RS_RELATIVE_PATH
    source = REPO_ROOT / rs["source_artifact"]
    assert rs["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert rs["phase12_closure_sha"] == PHASE12_CLOSURE_SHA


def test_celltrion_exact_phase12_regression():
    rs = load_relative_strength_section("068270", "2026-08-14", "COMMON", "KOSPI", REPO_ROOT)
    assert rs.market_rs_12m == -0.4496787607127102
    assert rs.market_rs_6m == -0.3009261151369007
    assert rs.market_rs_3m == 0.2363010527967675
    assert rs.market_rs_delta_6m_vs_12m == 0.14875264557580947
    assert rs.market_rs_delta_3m_vs_6m == 0.5372271679336682
    assert rs.market_rs_acceleration_3_6_12m == 0.38847452235785873
    assert rs.all_market_rs_percentile_12m == 42.51290877796902
    assert rs.all_market_rs_percentile_6m == 31.887755102040817
    assert rs.all_market_rs_percentile_3m == 81.72954641797372
    assert "회복" in rs.explanation


def test_rs_narrative_rules_cover_recovery_and_weakening():
    naver = load_relative_strength_section("035420", "2026-08-14", "COMMON", "KOSPI", REPO_ROOT)
    assert "회복" in naver.explanation
    assert "약화" in _load_report("005930_삼성전자")["relative_strength"]["explanation"]


def test_noncommon_report_is_not_applicable_with_null_numeric_fields():
    rs = _load_report("069500_KODEX 200")["relative_strength"]
    assert rs["applicability"] == "NOT_APPLICABLE"
    assert rs["data_status"] == "NOT_EVALUATED"
    assert all(rs[name] is None for name in (
        "market_rs_3m", "market_rs_6m", "market_rs_12m",
        "market_rs_delta_3m_vs_6m", "market_rs_delta_6m_vs_12m",
        "market_rs_acceleration_3_6_12m", "all_market_rs_rank_3m",
        "all_market_rs_percentile_3m",
    ))


def test_missing_snapshot_and_ticker_fail_closed(tmp_path):
    missing = load_relative_strength_section("005930", "2026-08-14", "COMMON", "KOSPI", tmp_path)
    assert missing.applicability == "DATA_UNAVAILABLE"
    assert missing.data_status == "DATA_UNAVAILABLE"
    assert missing.market_rs_3m is None

    artifact = tmp_path / RS_RELATIVE_PATH
    artifact.parent.mkdir(parents=True)
    pd.DataFrame([{
        "ticker": "999999",
        "market_rs_data_status": "READY",
        "market_benchmark_name": "코스피",
        "market_benchmark_code": 1001,
        "market_benchmark_last_observation_date": "2026-08-14",
        "market_rs_3m": 0.1,
        "market_rs_6m": 0.2,
        "market_rs_12m": 0.3,
        "market_rs_delta_3m_vs_6m": -0.1,
        "market_rs_delta_6m_vs_12m": -0.1,
        "market_rs_acceleration_3_6_12m": 0.0,
        "all_market_rs_rank_3m": 1,
        "all_market_rs_rank_6m": 2,
        "all_market_rs_rank_12m": 3,
        "all_market_rs_percentile_3m": 99.0,
        "all_market_rs_percentile_6m": 98.0,
        "all_market_rs_percentile_12m": 97.0,
        "market_anchor_date_3m": "2026-05-14",
        "market_anchor_date_6m": "2026-02-06",
        "market_anchor_date_12m": "2025-08-01",
    }]).to_csv(artifact, index=False)
    absent_row = load_relative_strength_section("005930", "2026-08-14", "COMMON", "KOSPI", tmp_path)
    assert absent_row.applicability == "DATA_UNAVAILABLE"
    assert absent_row.data_status == "DATA_UNAVAILABLE"
    assert absent_row.source_as_of == "2026-08-14"


def test_partial_snapshot_preserves_present_values_and_nulls_missing_horizon(tmp_path):
    artifact = tmp_path / RS_RELATIVE_PATH
    artifact.parent.mkdir(parents=True)
    pd.DataFrame([{
        "ticker": "005930", "market_rs_data_status": "PARTIAL",
        "market_benchmark_name": "코스피", "market_benchmark_code": 1001,
        "market_benchmark_last_observation_date": "2026-08-14",
        "market_rs_3m": 0.2, "market_rs_6m": 0.1, "market_rs_12m": None,
        "market_rs_delta_3m_vs_6m": 0.1, "market_rs_delta_6m_vs_12m": None,
        "market_rs_acceleration_3_6_12m": None,
        "all_market_rs_rank_3m": 10, "all_market_rs_rank_6m": 20, "all_market_rs_rank_12m": None,
        "all_market_rs_percentile_3m": 95, "all_market_rs_percentile_6m": 90, "all_market_rs_percentile_12m": None,
        "market_anchor_date_3m": "2026-05-14", "market_anchor_date_6m": "2026-02-06", "market_anchor_date_12m": None,
    }]).to_csv(artifact, index=False)
    rs = load_relative_strength_section("005930", "2026-08-14", "COMMON", "KOSPI", tmp_path)
    assert rs.applicability == "APPLICABLE"
    assert rs.data_status == "PARTIAL"
    assert rs.market_rs_3m == 0.2
    assert rs.market_rs_delta_3m_vs_6m == 0.1
    assert rs.market_rs_12m is None
    assert rs.market_rs_delta_6m_vs_12m is None
    assert rs.market_rs_acceleration_3_6_12m is None
    assert "제한적" in rs.explanation


def test_markdown_rs_section_is_between_foreign_flow_and_trading_value():
    md = (REPORT_DIR / "005930_삼성전자.md").read_text(encoding="utf-8")
    assert "## 7.5. 시장 상대강도 (RS)" in md
    assert md.index("## 7. 외국인") < md.index("## 7.5. 시장 상대강도 (RS)") < md.index("## 8. 거래대금")
    rs_text = md[md.index("## 7.5. 시장 상대강도 (RS)"):md.index("## 8. 거래대금")]
    assert "매수 추천" not in rs_text
    assert "매도 추천" not in rs_text


def test_loader_has_no_scanner_hook(monkeypatch, tmp_path):
    import trend_scanner.reporting.relative_strength_report as module

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Full Universe Scanner must not be called by the RS consumer")

    monkeypatch.setattr(module, "scan_pattern_a_universe", fail_if_called, raising=False)
    section = load_relative_strength_section("005930", "2026-08-14", "COMMON", "KOSPI", REPO_ROOT)
    assert section.source_as_of == "2026-08-14"
