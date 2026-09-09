"""Focused WEB-03A validation for the read-only strategy operations viewer."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_strategy_monitor_web.py"
MONITOR_PATH = ROOT / "web/data/strategy-monitor.json"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_strategy_monitor_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_monitor() -> dict:
    return json.loads(MONITOR_PATH.read_text(encoding="utf-8"))


def test_strategy_monitor_schema_and_source_count_are_consistent():
    monitor = _load_monitor()
    index = json.loads((ROOT / "web/data/stock-index.json").read_text(encoding="utf-8"))
    items = monitor["items"]

    assert monitor["schema_version"] == 1
    assert monitor["strategy"] == {
        "id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "label": "A FAST Core",
    }
    assert monitor["source"]["type"] == "PUBLISHED_STOCK_REPORTS"
    assert monitor["scope"] == {
        "type": "PUBLISHED_REPORTS",
        "label": "현재 공개 리포트 기준",
        "report_count": 276,
    }
    assert monitor["as_of"] == "2026-09-04"
    assert monitor["scope"]["report_count"] == index["available_report_count"] == len(items)
    bucket_counts = Counter(item["bucket"] for item in items)
    assert all(monitor["counts"][key] == bucket_counts.get(key, 0) for key in ("entry", "hold", "exit", "watch", "unavailable"))
    assert sum(monitor["counts"].values()) == len(items)
    assert {item["ticker"] for item in items} == {
        item["ticker"] for item in index["items"] if item["report_available"] is True
    }
    for item in items:
        assert {
            "ticker", "name", "market", "asset_type", "sector_name", "action",
            "strategy_state", "canonical_position", "pattern_stage", "pattern_score",
            "latest_close", "latest_close_as_of", "report_status", "data_status",
            "current_trade", "bucket",
        } <= item.keys()


def test_representative_common_open_trade_is_projected_without_recalculation():
    monitor = _load_monitor()
    item = next(item for item in monitor["items"] if item["ticker"] == "005930")

    assert item["action"] == "HOLD"
    assert item["strategy_state"] == "HOLD_PROGRESSED"
    assert item["canonical_position"] == "OPEN"
    assert item["bucket"] == "hold"
    assert item["current_trade"] == {
        "trade_sequence": 6,
        "entry_execution_date": "2025-09-01",
        "entry_open": 68400.0,
        "return_pct": 273.54,
        "trade_status": "OPEN_AT_CUTOFF",
    }


def test_etf_is_not_in_action_counts_and_has_no_fake_trade():
    monitor = _load_monitor()
    item = next(item for item in monitor["items"] if item["ticker"] == "069500")

    assert item["asset_type"] == "ETF"
    assert item["canonical_position"] == "NOT_APPLICABLE"
    assert item["action"] == "NONE"
    assert item["data_status"] == "NOT_APPLICABLE"
    assert item["bucket"] == "unavailable"
    assert item["current_trade"] is None
    assert monitor["counts"]["unavailable"] == 28
    assert sum(monitor["counts"][key] for key in ("entry", "hold", "exit")) == 109


def test_strategy_page_is_connected_and_uses_page_specific_cache_version():
    strategy_html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    index_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    report_html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'href="./css/app.css?v=web-strategy-summary-3col-1"' in strategy_html
    assert 'href="./css/app.css?v=web-fear-fix02-1"' in index_html
    assert 'href="./css/app.css?v=web-02d-window-1"' in report_html
    for html in (index_html, report_html):
        assert "web-02a-final-2" not in html
        assert "web-03a-final-1" not in html
    assert 'src="./js/strategy.js?v=web-02c-toss-1"' in strategy_html
    assert 'src="./js/app.js?v=web-fear-fix02-1"' in index_html
    assert 'src="./js/report.js?v=web-02d-window-1"' in report_html
    assert 'href="./strategy.html"' in index_html
    assert 'href="./strategy.html"' in report_html
    assert 'class="nav-item is-active" href="./strategy.html"' in strategy_html

    assert '<h1 id="page-title">전략 운용</h1>' in strategy_html
    assert "전략 신호와 보유 상태를 한눈에!" in strategy_html
    assert "A FAST Core" in strategy_html
    assert "Julia" in strategy_html and 'id="julia-option"' in strategy_html and "disabled" in strategy_html
    assert "현재 공개 리포트 기준" in strategy_html
    assert 'id="strategy-search"' in strategy_html
    assert 'data-filter="hold"' in strategy_html
    assert 'data-filter="entry"' in strategy_html
    assert 'data-filter="exit"' in strategy_html
    assert 'data-filter="watch"' in strategy_html
    assert 'data-filter="unavailable"' in strategy_html
    assert 'id="summary-watch-count"' in strategy_html
    assert 'id="summary-unavailable-count"' in strategy_html
    assert '<h2 id="unavailable-heading">기타</h2>' in strategy_html
    assert 'setText("summary-watch-count", counts.watch)' in strategy_js
    assert 'setText("summary-unavailable-count", counts.unavailable)' in strategy_js
    assert 'const FILTERS = new Set(["all", ...Object.keys(SECTION_IDS)]);' in strategy_js
    assert 'link.href = `./report.html?ticker=' in strategy_js
    assert 'const MONITOR_URL = "./data/strategy-monitor.json";' in strategy_js
    assert "function createPriceDateField" in strategy_js
    assert "function createPositionField" in strategy_js
    assert '"strategy-item-position"' in strategy_js
    assert '"strategy-item-position-main"' in strategy_js
    assert '"strategy-item-position-sub"' in strategy_js
    assert 'createField("현재 상태", "해당 없음", "strategy-item-position")' in strategy_js
    assert 'createField("현재 상태", "확인 필요", "strategy-item-position")' in strategy_js
    assert "positionLabel(item.canonical_position)} · ${stateLabel" not in strategy_js
    assert 'actionLabel(item.action, item.data_status)' in strategy_js
    assert "dataStatus === \"NOT_APPLICABLE\"" in strategy_js
    assert "dataStatus === \"CHECK_REQUIRED\"" in strategy_js
    assert "window.matchMedia" in strategy_js
    assert ".strategy-item" in css and ".strategy-summary-card" in css
    assert ".strategy-summary-grid" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert ".strategy-item-field.detail-value-positive .strategy-item-value" in css
    assert ".strategy-item-field.detail-value-negative .strategy-item-value" in css
    assert ".strategy-item-position .strategy-item-value" in css
    assert ".strategy-item-position-value" in css
    assert ".strategy-item-price-date" in css
    assert "min-height: 108px" in css
    for raw in ("OPEN_AT_CUTOFF", "HOLD_PROGRESSED", "NOT_APPLICABLE", "ENTER_NEXT_OPEN", "TOP PICK", "AI 추천"):
        assert raw not in strategy_html


def test_strategy_ui_polish_uses_representative_source_returns_and_split_dates():
    monitor = _load_monitor()
    positive = next(item for item in monitor["items"] if item["ticker"] == "005930")
    negative = next(item for item in monitor["items"] if item["ticker"] == "027410")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert positive["current_trade"]["return_pct"] == 273.54
    assert negative["current_trade"]["return_pct"] == -6.39
    assert 'const returnClass = trade && Number(trade.return_pct) > 0 ? "detail-value-positive"' in strategy_js
    assert 'Number(trade.return_pct) < 0 ? "detail-value-negative"' in strategy_js
    assert 'createPriceDateField("현재가"' in strategy_js
    assert 'createPriceDateField("진입가"' in strategy_js
    assert 'createField("진입가", "—")' in strategy_js
    assert "white-space: normal" in css
    assert "text-overflow: clip" in css


def test_strategy_position_examples_keep_meaningful_two_line_values():
    monitor = _load_monitor()
    items = {item["ticker"]: item for item in monitor["items"]}

    assert items["005930"]["canonical_position"] == "OPEN"
    assert items["005930"]["strategy_state"] == "HOLD_PROGRESSED"
    assert items["027410"]["canonical_position"] == "OPEN"
    assert items["027410"]["strategy_state"] == "HOLD_PRE_PROGRESSED"
    wait_item = next(item for item in monitor["items"] if item["strategy_state"] == "WAIT")
    assert wait_item["canonical_position"] == "FLAT"
    assert items["069500"]["canonical_position"] == "NOT_APPLICABLE"


def test_strategy_monitor_json_matches_clean_exporter_projection():
    exporter = _load_exporter()
    assert _load_monitor() == exporter.build_strategy_monitor()
