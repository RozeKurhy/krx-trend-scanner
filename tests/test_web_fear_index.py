"""Focused validation for the Fear Index Web V01 projection and UI shell."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_fear_index_web.py"
VALID_REGIMES = {"OVERHEATED", "NORMAL", "ANXIOUS", "PANIC", "APATHY"}


@pytest.fixture(scope="session")
def exporter():
    spec = importlib.util.spec_from_file_location("export_fear_index_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def payload(exporter):
    return exporter.build_web_payload()


def test_payload_projects_approved_authority(payload, exporter):
    summary = json.loads(exporter.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "FEAR_INDEX_WEB_V01"
    assert payload["model"]["study"] == summary["study"]
    assert payload["model"]["candidate"] == "downside_heavy_v01"
    assert payload["model"]["hysteresis"] is True
    assert payload["as_of"] == "2026-09-04"
    assert payload["available_from"] == payload["items"][0]["date"]
    assert payload["items"][-1]["date"] == payload["as_of"]
    assert payload["current"] == payload["items"][-1]
    assert payload["current"]["regime"] == summary["current"]["regime"]
    assert payload["current"]["fear_score"] == summary["current"]["fear_score"]
    assert payload["current"]["kospi_close"] == summary["current"]["kospi_close"]
    assert payload["current"]["v_kospi200_close"] == summary["current"]["v_kospi200_close"]
    assert payload["current"]["trading_value"] == summary["current"]["trading_value"]


def test_payload_rows_are_valid_ascending_and_compact(payload):
    dates = [item["date"] for item in payload["items"]]
    assert len(dates) == 3980
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    assert all(item["regime"] in VALID_REGIMES for item in payload["items"])
    assert all(set(item) == {"date", "kospi_close", "v_kospi200_close", "trading_value", "fear_score", "regime"} for item in payload["items"])
    assert all(isinstance(item["fear_score"], float) for item in payload["items"])
    serialized = json.dumps(payload, ensure_ascii=False)
    for diagnostic in ("future_return", "future_min_return", "future_risk_event", "raw_regime", "stabilized_regime", "Brier", "Spearman"):
        assert diagnostic not in serialized


def test_historical_anchor_states_are_preserved(payload):
    by_date = {item["date"]: item for item in payload["items"]}
    assert by_date["2020-03-19"]["regime"] == "PANIC"
    assert by_date["2024-08-05"]["regime"] == "PANIC"
    assert by_date["2022-07-04"]["regime"] == "ANXIOUS"
    assert by_date["2026-06-18"]["regime"] == "OVERHEATED"
    assert by_date["2026-06-29"]["regime"] == "ANXIOUS"
    assert by_date["2026-09-04"]["regime"] == "ANXIOUS"
    assert by_date["2026-09-04"]["fear_score"] == pytest.approx(30.1802365595)


def test_exporter_writes_payload_without_manual_json(tmp_path, exporter, payload):
    output = tmp_path / "data" / "fear-index.json"
    written = exporter.export_fear_index(output)
    assert written == payload
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_main_card_is_full_width_between_overall_and_metric_grid():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert '<a id="fear-index-card" class="fear-index-card" href="./fear.html"' in html
    assert html.index('class="overall-card"') < html.index('id="fear-index-card"') < html.index('class="metric-grid"')
    assert "지금 시장은 어떤 상태일까?" in html
    for label in ("과열·흥분", "정상·안정", "불안", "공포·패닉", "침체·무관심"):
        assert label in html
    assert 'id="fear-card-score"' in html
    assert 'id="fear-card-regime"' in html
    assert 'id="fear-card-date"' in html


def test_detail_page_has_required_summary_chart_and_accessibility_contract():
    html = (ROOT / "web/fear.html").read_text(encoding="utf-8")
    assert "<title>공포 지수 · KRX Trend Scanner</title>" in html
    assert '<h1 id="page-title">공포 지수</h1>' in html
    assert "시장 심리의 흐름을 한눈에!" in html
    assert 'id="fear-chart"' in html and 'role="img"' in html
    assert 'id="fear-tooltip"' in html
    assert 'data-fear-range="all"' in html
    assert all(f'data-fear-range="{value}"' in html for value in ("5y", "3y", "1y", "6m"))
    assert "KOSPI와 공포 지수" in html
    assert "거래대금 · 조원" in html
    assert "KOSPI 방향·V-KOSPI·거래대금을 함께 반영합니다" in html
    for field in ("fear-current-score", "fear-current-regime", "fear-current-vkospi", "fear-current-kospi", "fear-current-trading-value", "fear-current-as-of"):
        assert f'id="{field}"' in html
    assert html.count("과열·흥분") == 1
    assert html.count("정상·안정") == 1
    assert html.count("불안") == 1
    assert html.count("공포·패닉") == 1
    assert html.count("침체·무관심") == 1


def test_fear_js_keeps_final_regime_authority_and_safe_interactions():
    js = (ROOT / "web/js/fear.js").read_text(encoding="utf-8")
    assert 'const PAYLOAD_URL = "./data/fear-index.json";' in js
    assert "function isFiniteNumber(value)" in js
    assert "value !== null && value !== undefined && value !== \"\"" in js
    assert "function buildRegimeBands(rows)" in js
    assert "function filterRange(rows, range)" in js
    assert "RANGE_SESSION_COUNTS" in js
    assert "aria-pressed" in js
    assert "pointermove" in js and "pointerdown" in js
    assert "ResizeObserver" in js
    assert "safeRegime(item.regime)" in js
    assert "raw_regime" not in js
    assert "stabilized_regime" not in js
    assert "rolling" not in js.lower()
    assert "hysteresis" not in js.lower()


def test_css_defines_regime_palette_and_mobile_layout():
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    for variable in (
        "--regime-overheated-bg",
        "--regime-normal-bg",
        "--regime-anxious-bg",
        "--regime-panic-bg",
        "--regime-apathy-bg",
    ):
        assert variable in css
    assert ".fear-index-card" in css
    assert ".fear-chart-canvas" in css
    assert ".fear-regime-chip.is-current" in css
    assert re.search(r"@media \(max-width: 560px\).*?\.fear-regime-strip \{ grid-template-columns: repeat\(2", css, re.DOTALL)
