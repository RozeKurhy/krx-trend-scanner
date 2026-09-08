"""Focused WEB-02A validation for the local Stock Report web foundation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_stock_report_web.py"


@pytest.fixture(scope="session")
def exporter():
    spec = importlib.util.spec_from_file_location("export_stock_report_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def payload(exporter):
    return exporter.build_web_payload()


def test_payload_covers_pit_universe_and_existing_reports(payload):
    index, reports, stats = payload

    assert index["count"] == 4407
    assert index["available_report_count"] == 158
    assert len(index["items"]) == 4407
    assert len(reports) == 158
    assert stats["unavailable_report_count"] == 4249
    assert sum(item["report_available"] for item in index["items"]) == 158
    assert index["requested_as_of"] == "2026-09-04"
    assert index["universe_snapshot_date"] == "2026-08-21"


def test_compact_report_preserves_authority_values_without_raw_markdown(payload):
    index, reports, _ = payload
    report = reports["005930"]
    item = next(candidate for candidate in index["items"] if candidate["ticker"] == "005930")

    assert item["report_available"] is True
    assert report["identity"]["ticker"] == "005930"
    assert report["identity"]["name"] == item["name"]
    assert report["decision"]["action"] in {"HOLD", "WAIT", "ENTER_NEXT_OPEN", "NONE", "WATCH", "ENTRY", "EXIT"}
    assert report["fundamentals"]["status"] == "NOT_AVAILABLE"
    assert report["external_links"]["naver_finance"] == "https://finance.naver.com/item/main.naver?code=005930"
    assert "summary_text" not in report
    assert "body" not in report
    assert "/Users/" not in json.dumps(report, ensure_ascii=False)


def test_exporter_writes_index_and_one_json_per_available_report(tmp_path, exporter):
    stats = exporter.export_stock_reports(tmp_path)
    index_path = tmp_path / "stock-index.json"
    stock_dir = tmp_path / "stocks"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    assert stats["universe_count"] == 4407
    assert index["count"] == 4407
    assert len(list(stock_dir.glob("*.json"))) == 158
    sample = json.loads((stock_dir / "005930.json").read_text(encoding="utf-8"))
    assert sample["schema_version"] == 1
    assert sample["identity"]["ticker"] == "005930"
    assert sample["technical_details"]["source_report"].startswith("artifacts/reporting/stock_reports/")


def test_report_frontend_has_safe_states_and_relative_assets():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'href="./css/app.css"' in html
    assert 'src="./js/report.js"' in html
    assert 'placeholder="종목명 또는 종목코드 검색"' in html
    assert 'id="report-empty"' in html
    assert 'id="report-pending"' in html
    assert 'id="report-error"' in html
    assert 'id="naver-link"' in html
    assert 'const INDEX_URL = "./data/stock-index.json";' in js
    assert 'const STOCKS_PATH = "./data/stocks/";' in js
    assert "localStorage" in js and "krx-theme" in js
    assert "리포트 준비 중" in js
    assert "종목 정보를 찾을 수 없습니다." in js
    assert "innerHTML" not in js
    assert "href=\"./report.html\"" in html
    assert ".report-card-grid" in css
    assert "@media (max-width: 560px)" in css


def test_index_navigation_keeps_health_and_report_pages_connected():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    assert 'href="./index.html"' in html
    assert 'href="./report.html"' in html
    assert '종목 리포트 <small>준비 중</small>' not in html
