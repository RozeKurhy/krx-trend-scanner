"""Focused WEB-03A validation for the read-only strategy operations viewer."""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


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


def _source_projection(ticker: str, exporter=None) -> dict:
    exporter = exporter or _load_exporter()
    index = json.loads((ROOT / "web/data/stock-index.json").read_text(encoding="utf-8"))
    index_item = next(
        item for item in index["items"]
        if item["ticker"] == ticker and item["report_available"] is True
    )
    report = json.loads((ROOT / "web/data/stocks" / f"{ticker}.json").read_text(encoding="utf-8"))
    return exporter._project_item(index_item, report)


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
        "report_count": index["available_report_count"],
    }
    assert monitor["as_of"] == index["requested_as_of"]
    assert monitor["reference_market_date"] == index["reference_market_date"]
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
    exporter = _load_exporter()
    monitor = _load_monitor()
    item = next(
        item for item in monitor["items"]
        if item["asset_type"] == "COMMON" and item["current_trade"] is not None
    )
    source = _source_projection(item["ticker"], exporter)

    assert item["canonical_position"] == "OPEN"
    assert item["bucket"] == "hold"
    assert item["current_trade"] == source["current_trade"]


def test_etf_is_not_in_action_counts_and_has_no_fake_trade():
    monitor = _load_monitor()
    assert "069500" not in {item["ticker"] for item in monitor["items"]}
    assert sum(monitor["counts"].values()) == monitor["scope"]["report_count"]


def test_strategy_page_is_connected_and_uses_page_specific_cache_version():
    strategy_html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    index_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    report_html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'href="./css/app.css?v=web-ui-density-11"' in index_html
    assert 'href="./css/app.css?v=web-ui-density-11"' in report_html
    for html in (index_html, report_html):
        assert "web-02a-final-2" not in html
        assert "web-03a-final-1" not in html
    strategy_scripts = [
        urlsplit(url)
        for url in re.findall(r'\bsrc="([^"]+)"', strategy_html)
        if urlsplit(url).path == "./js/strategy.js"
    ]
    assert len(strategy_scripts) == 1
    assert strategy_scripts[0].query.startswith("v=") and strategy_scripts[0].query.removeprefix("v=")
    assert (ROOT / "web" / strategy_scripts[0].path.removeprefix("./")).is_file()
    assert 'src="./js/app.js?v=web-fear-fix02-4"' in index_html
    assert 'src="./js/report.js?v=web-02d-window-13"' in report_html
    assert 'href="./strategy.html"' in index_html
    assert 'href="./strategy.html"' in report_html
    assert 'class="nav-item is-active" href="./strategy.html"' in strategy_html

    assert '<section class="page-intro"' not in strategy_html
    assert 'id="page-title"' not in strategy_html
    assert "A FAST Core" in strategy_html
    assert "Julia" in strategy_html and 'id="julia-option"' in strategy_html and "disabled" in strategy_html
    assert '<p class="eyebrow">전략</p>' not in strategy_html
    assert '<h2 id="strategy-overview-heading">현재 전략</h2>' in strategy_html
    assert 'id="strategy-scope" class="strategy-scope">기준일 —</p>' in strategy_html
    assert "현재 판단 요약" not in strategy_html
    assert "현재 공개 리포트 기준" not in strategy_html
    assert 'setText("strategy-scope", `기준일 ${formatDate(monitor.as_of)}`);' in strategy_js
    assert 'id="strategy-search"' in strategy_html
    assert 'data-filter="hold"' in strategy_html
    assert 'data-filter="entry"' in strategy_html
    assert 'data-filter="exit"' in strategy_html
    assert 'data-filter="watch"' in strategy_html
    assert 'data-filter="unavailable"' in strategy_html
    assert 'id="strategy-filter-count-all"' in strategy_html
    assert 'id="strategy-filter-count-hold"' in strategy_html
    assert 'id="strategy-filter-count-entry"' in strategy_html
    assert 'id="strategy-filter-count-exit"' in strategy_html
    assert 'id="strategy-filter-count-watch"' in strategy_html
    assert 'id="strategy-filter-count-unavailable"' in strategy_html
    assert 'class="strategy-summary-grid"' not in strategy_html
    assert 'class="strategy-summary-card"' not in strategy_html
    assert 'id="strategy-controls-heading"' not in strategy_html
    assert 'id="strategy-results-meta"' not in strategy_html
    assert "전략 현황" not in strategy_html
    for label in ("보유 종목", "진입 조건 충족", "매도 조건 충족", "관찰 종목", "기타"):
        assert f'aria-label="{label}"' in strategy_html
    for removed in ("strategy-section-heading", "strategy-section-count", "hold-heading", "entry-heading", "exit-heading", "watch-heading", "unavailable-heading", "hold-count", "entry-count", "exit-count", "watch-count", "unavailable-count"):
        assert removed not in strategy_html
    assert 'function renderFilterCounts()' in strategy_js
    assert 'setText(`strategy-filter-count-${category}`, counts[category])' in strategy_js
    assert 'counts.all = monitor.scope.report_count' in strategy_js
    assert 'counts[item.bucket] += 1' in strategy_js
    assert 'setText(`${category}-count`, items.length)' not in strategy_js
    assert 'strategy-results-meta' not in strategy_js
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
    assert ".strategy-item" in css
    assert ".strategy-summary-card" not in css
    assert ".strategy-summary-grid" not in css
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


def test_strategy_hold_sort_contract_is_hold_only_and_session_scoped():
    strategy_html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert '<div id="strategy-hold-sort-row" class="strategy-sort-row" hidden>' in strategy_html
    assert '<div class="strategy-filter-toolbar">' in strategy_html
    assert strategy_html.index('<div class="strategy-filter-toolbar">') < strategy_html.index('id="strategy-filters"') < strategy_html.index('id="strategy-hold-sort-row"')
    assert '<label for="strategy-hold-sort">정렬</label>' in strategy_html
    assert '<select id="strategy-hold-sort" class="strategy-sort-select">' in strategy_html
    assert '<option value="entry-date" selected>진입 일자 순</option>' in strategy_html
    assert '<option value="return">수익률 순</option>' in strategy_html
    assert '<option value="name">이름 순</option>' in strategy_html
    assert 'let holdSort = "entry-date";' in strategy_js
    assert 'activeFilter === "hold"' in strategy_js
    assert 'entry_execution_date' in strategy_js
    assert 'return_pct' in strategy_js
    assert 'localeCompare(String(b.name || ""), "ko")' in strategy_js
    assert 'addEventListener("change"' in strategy_js
    assert 'monitor.items.sort' not in strategy_js
    assert ".strategy-sort-row" in css
    assert ".strategy-sort-row label" in css
    assert ".strategy-sort-select" in css
    assert ".strategy-filter-toolbar { display: flex;" in css
    assert "flex: 1 1 auto" in css
    assert "margin-left: auto" in css


def test_strategy_ui_polish_uses_representative_source_returns_and_split_dates():
    exporter = _load_exporter()
    monitor = _load_monitor()
    positive = next(
        item for item in monitor["items"]
        if item["current_trade"] is not None and item["current_trade"]["return_pct"] > 0
    )
    negative = next(
        item for item in monitor["items"]
        if item["current_trade"] is not None and item["current_trade"]["return_pct"] < 0
    )
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert positive["current_trade"]["return_pct"] == _source_projection(positive["ticker"], exporter)["current_trade"]["return_pct"]
    assert negative["current_trade"]["return_pct"] == _source_projection(negative["ticker"], exporter)["current_trade"]["return_pct"]
    assert 'const returnClass = trade && Number(trade.return_pct) > 0 ? "detail-value-positive"' in strategy_js
    assert 'Number(trade.return_pct) < 0 ? "detail-value-negative"' in strategy_js
    assert 'createPriceDateField("현재가"' in strategy_js
    assert 'createPriceDateField("진입가"' in strategy_js
    assert 'createField("진입가", "—")' in strategy_js
    assert "white-space: normal" in css
    assert "text-overflow: clip" in css


def test_strategy_position_examples_keep_meaningful_two_line_values():
    monitor = _load_monitor()
    items_by_state = {item["strategy_state"]: item for item in monitor["items"]}
    assert items_by_state["HOLD_PROGRESSED"]["canonical_position"] == "OPEN"
    assert items_by_state["HOLD_PRE_PROGRESSED"]["canonical_position"] == "OPEN"
    wait_item = next(item for item in monitor["items"] if item["strategy_state"] == "WAIT")
    assert wait_item["canonical_position"] == "FLAT"


def test_strategy_monitor_json_matches_clean_exporter_projection():
    exporter = _load_exporter()
    assert _load_monitor() == exporter.build_strategy_monitor()
