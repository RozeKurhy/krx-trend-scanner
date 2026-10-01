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
    strategies = {strategy["id"]: strategy for strategy in monitor["strategies"]}
    common = strategies["PATTERN_A_FAST_FINAL_STRATEGY_V02"]
    b_select = strategies["PATTERN_B_SELECT_CORE_V01"]
    julia = strategies["JULIA_ETF_STRATEGY_V01"]
    items = common["items"]

    assert monitor["schema_version"] == 2
    assert monitor["default_strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert [strategy["id"] for strategy in monitor["strategies"]] == [
        "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "PATTERN_B_SELECT_CORE_V01",
        "JULIA_ETF_STRATEGY_V01",
    ]
    assert monitor["source"]["type"] == "PUBLISHED_STOCK_REPORTS"
    assert common["scope"] == {
        "type": "PUBLISHED_COMMON_REPORTS",
        "label": "현재 공개 COMMON 리포트 기준",
        "report_count": sum(
            item["report_available"] is True and item.get("asset_type") == "COMMON"
            for item in index["items"]
        ),
    }
    assert monitor["requested_as_of"] == index["requested_as_of"]
    assert monitor["reference_market_date"] == index["reference_market_date"]
    assert common["scope"]["report_count"] == len(items)
    bucket_counts = Counter(item["bucket"] for item in items)
    assert all(common["counts"][key] == bucket_counts.get(key, 0) for key in ("entry", "hold", "exit", "watch", "unavailable"))
    assert sum(common["counts"].values()) == len(items)
    assert {item["ticker"] for item in items} == {
        item["ticker"] for item in index["items"]
        if item["report_available"] is True and item.get("asset_type") == "COMMON"
    }
    for item in items:
        assert {
            "ticker", "name", "market", "asset_type", "sector_name", "action",
            "strategy_state", "canonical_position", "pattern_stage", "pattern_score",
            "latest_close", "latest_close_as_of", "report_status", "data_status",
            "current_trade", "bucket",
        } <= item.keys()
        assert "trade_history" not in item
    assert {item["ticker"] for item in b_select["items"]} == {item["ticker"] for item in items}
    assert b_select["scope"]["type"] == "PUBLISHED_COMMON_REPORTS"
    assert sum(b_select["counts"].values()) == b_select["scope"]["report_count"]
    assert julia["scope"]["type"] == "OFFICIAL_ETF_36"
    assert julia["scope"]["report_count"] == 36
    assert len(julia["items"]) == 36


def test_representative_common_open_trade_is_projected_without_recalculation():
    exporter = _load_exporter()
    monitor = _load_monitor()
    item = next(
        item for item in monitor["strategies"][0]["items"]
        if item["asset_type"] == "COMMON" and item["current_trade"] is not None
    )
    source = _source_projection(item["ticker"], exporter)

    assert item["canonical_position"] == "OPEN"
    assert item["bucket"] == "hold"
    assert item["current_trade"] == source["current_trade"]


def test_b_select_open_entry_pattern_a_context_matches_exact_authority():
    exporter = _load_exporter()
    monitor = _load_monitor()
    b_select = next(
        strategy for strategy in monitor["strategies"]
        if strategy["id"] == "PATTERN_B_SELECT_CORE_V01"
    )
    authority = exporter._read_entry_stage_authority(ROOT)
    exporter._validate_b_select_entry_contexts(b_select["items"], authority)
    open_items = [item for item in b_select["items"] if item["canonical_position"] == "OPEN"]

    assert len(open_items) == 24
    assert all(item["entry_pattern_a_stage"] == "PROGRESSED" for item in open_items)
    assert all(item["entry_previous_pattern_a_stage"] in {"EARLY_TREND", "TRANSITION"} for item in open_items)


def test_b_select_entry_pattern_a_validator_fails_closed_on_ambiguous_source():
    exporter = _load_exporter()
    source = {
        "entry_pattern_a_stage_recomputed": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
        "previous_pattern_a_stage_date": "2024-07-31",
    }
    key = ("001380", "KR7001380005", "001380:KR7001380005:000", "2025-04-30")
    item = {
        "ticker": key[0],
        "isu_cd": key[1],
        "component_id": key[2],
        "canonical_position": "OPEN",
        "action": "HOLD",
        "current_trade": {"entry_signal_date": key[3]},
        "pending_event": None,
        "entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "EARLY_TREND",
        "entry_previous_pattern_a_stage_date": "2024-07-31",
    }
    import pytest

    with pytest.raises(ValueError, match="match count is not one"):
        exporter._validate_b_select_entry_contexts([item], {key: [source, source]})


def test_b_select_watch_item_does_not_receive_fake_entry_pattern_a_context():
    exporter = _load_exporter()
    item = {
        "ticker": "001380",
        "action": "WAIT",
        "canonical_position": "FLAT",
        "pending_event": None,
        "entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "EARLY_TREND",
        "entry_previous_pattern_a_stage_date": "2024-07-31",
    }
    import pytest

    with pytest.raises(ValueError, match="fake entry Pattern A context"):
        exporter._validate_b_select_entry_contexts([item], {})


def test_etf_is_not_in_action_counts_and_has_no_fake_trade():
    monitor = _load_monitor()
    strategies = {strategy["id"]: strategy for strategy in monitor["strategies"]}
    common = strategies["PATTERN_A_FAST_FINAL_STRATEGY_V02"]
    julia = strategies["JULIA_ETF_STRATEGY_V01"]
    assert "069500" not in {item["ticker"] for item in common["items"]}
    assert "069500" in {item["ticker"] for item in julia["items"]}
    assert sum(common["counts"].values()) == common["scope"]["report_count"]
    assert sum(julia["counts"].values()) == julia["scope"]["report_count"]


def test_exit_next_open_and_exit_actions_map_to_exit_bucket():
    exporter = _load_exporter()
    cases = (
        ("A FAST Core V2", "EXIT_NEXT_OPEN"),
        ("Julia V1", "EXIT_NEXT_OPEN"),
        ("B Select Core V1", "EXIT"),
    )
    for strategy_name, action in cases:
        item = {
            "data_status": "READY",
            "canonical_position": "OPEN",
            "action": action,
        }
        assert exporter._item_bucket(item) == "exit", (strategy_name, action)


def test_strategy_page_is_connected_and_uses_page_specific_cache_version():
    strategy_html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    index_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    report_html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'href="./css/app.css?v=web-dual-strategy-report-v1"' in index_html
    assert 'href="./css/app.css?v=web-dual-strategy-report-v1"' in report_html
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
    assert 'EXIT: "다음 시가 청산 대기"' in strategy_js
    assert 'src="./js/report.js?v=web-stock-report-ui-refine-v1"' in report_html
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
    assert 'formatDate(monitor.requested_as_of || monitor.as_of)' in strategy_js
    assert 'selected.scope.label' not in strategy_js
    assert '`기준일 ${formatDate(monitor.requested_as_of || monitor.as_of)} · ${formatNumber(selected.scope.report_count)}개`' in strategy_js
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
    assert 'counts.all = selected.scope.report_count' in strategy_js
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
    assert 'createField("전략 판단"' not in strategy_js
    assert 'createField("전략 상태"' not in strategy_js
    assert 'createField("이전 Stage"' not in strategy_js
    assert 'item.asset_type !== "COMMON"' in strategy_js
    assert 'meta.join(" · ")' in strategy_js
    assert "item.entry_pattern_a_stage != null || item.entry_previous_pattern_a_stage != null" in strategy_js
    assert "item.entry_previous_pattern_a_stage" in strategy_js
    assert "item.entry_pattern_a_stage" in strategy_js
    assert 'createField("Pattern A", `${stageLabel(previousPatternAStage)} → ${stageLabel(currentPatternAStage)}`)' in strategy_js
    assert 'createField("Pattern B", patternBLabel(item.pattern_b_state))' in strategy_js
    assert 'function stageLabel(value) { return STAGE_LABELS[value] || "확인 필요"; }' in strategy_js
    assert 'function patternBLabel(value) { return PATTERN_B_LABELS[value] || (value ? "확인 필요" : "확인 필요"); }' in strategy_js
    b_select_fields = strategy_js[strategy_js.index('if (strategyId === "PATTERN_B_SELECT_CORE_V01")'):strategy_js.index('} else if (strategyId === "JULIA_ETF_STRATEGY_V01")')]
    assert "previous_pattern_a_stage" in b_select_fields
    assert "pattern_a_stage" in b_select_fields
    assert "entry_previous_pattern_a_stage" in b_select_fields
    assert "entry_pattern_a_stage" in b_select_fields
    assert "pattern_b_state" in b_select_fields
    assert "progressed_segment_start_date" not in b_select_fields
    assert 'detailFields = [];' in strategy_js
    assert 'item.data_status === "NOT_APPLICABLE"' in strategy_js
    assert 'item.data_status === "CHECK_REQUIRED"' in strategy_js
    assert "window.matchMedia" in strategy_js
    assert ".strategy-item" in css
    assert ".strategy-item-a-fast { grid-template-columns: minmax(190px, 1.55fr) repeat(5, minmax(80px, 1fr)) auto; }" in css
    assert ".strategy-item-b-select { grid-template-columns: minmax(190px, 1.55fr) repeat(6, minmax(80px, 1fr)) auto; }" in css
    assert ".strategy-item-julia { grid-template-columns: minmax(190px, 1.55fr) repeat(4, minmax(80px, 1fr)) auto; }" in css
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
        item for item in monitor["strategies"][0]["items"]
        if item["current_trade"] is not None and item["current_trade"]["return_pct"] > 0
    )
    negative = next(
        item for item in monitor["strategies"][0]["items"]
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
    items_by_state = {item["strategy_state"]: item for item in monitor["strategies"][0]["items"]}
    assert items_by_state["HOLD_PROGRESSED"]["canonical_position"] == "OPEN"
    assert items_by_state["HOLD_PRE_PROGRESSED"]["canonical_position"] == "OPEN"
    neutral_items = [item for item in monitor["strategies"][0]["items"] if item["strategy_state"] == "WAIT"]
    if neutral_items:
        assert all(item["canonical_position"] == "FLAT" for item in neutral_items)
    else:
        unavailable = next(item for item in monitor["strategies"][0]["items"] if item["strategy_state"] == "DATA_UNAVAILABLE")
        assert unavailable["canonical_position"] == "DATA_UNAVAILABLE"


def test_strategy_monitor_json_matches_clean_exporter_projection():
    exporter = _load_exporter()
    assert _load_monitor() == exporter.build_strategy_monitor()


def test_three_strategy_trade_history_counts_identity_and_source_parity():
    exporter = _load_exporter()
    monitor = _load_monitor()
    strategies = {strategy["id"]: strategy for strategy in monitor["strategies"]}
    index = json.loads((ROOT / "web/data/stock-index.json").read_text(encoding="utf-8"))

    fast_source_count = 0
    julia_source_count = 0
    for item in index["items"]:
        if item.get("report_available") is not True:
            continue
        report = json.loads((ROOT / "web/data/stocks" / f"{item['ticker']}.json").read_text(encoding="utf-8"))
        history = (report.get("strategy") or {}).get("history") or []
        if item.get("asset_type") == "COMMON":
            fast_source_count += len(history)
        elif item.get("asset_type") == "ETF":
            julia_source_count += len(history)

    fast = strategies["PATTERN_A_FAST_FINAL_STRATEGY_V02"]["trade_history"]
    b_select = strategies["PATTERN_B_SELECT_CORE_V01"]["trade_history"]
    julia = strategies["JULIA_ETF_STRATEGY_V01"]["trade_history"]
    assert strategies["PATTERN_A_FAST_FINAL_STRATEGY_V02"]["counts"] == {
        "entry": 0, "hold": 241, "exit": 0, "watch": 0, "unavailable": 1210,
    }
    assert strategies["PATTERN_A_FAST_FINAL_STRATEGY_V02"]["scope"]["report_count"] == 1451
    assert strategies["PATTERN_B_SELECT_CORE_V01"]["counts"] == {
        "entry": 0, "hold": 23, "exit": 1, "watch": 1275, "unavailable": 152,
    }
    assert strategies["PATTERN_B_SELECT_CORE_V01"]["scope"]["report_count"] == 1451
    assert strategies["JULIA_ETF_STRATEGY_V01"]["counts"] == {
        "entry": 0, "hold": 18, "exit": 0, "watch": 18, "unavailable": 0,
    }
    assert strategies["JULIA_ETF_STRATEGY_V01"]["scope"]["report_count"] == 36
    assert len(fast) == fast_source_count
    assert len(julia) == julia_source_count
    assert len(fast) == 3797
    assert len(b_select) == 312
    assert len(julia) == 52
    assert len(fast) + len(b_select) + len(julia) == 4161

    b_status_path = ROOT / "artifacts/strategies/b_select_core_v1/production/20260925/status.json"
    b_status = json.loads(b_status_path.read_text(encoding="utf-8"))
    b_status_trades = [trade for item in b_status["items"] for trade in item.get("trade_history", [])]
    assert len(b_select) == len(b_status_trades)
    assert b_status["counts"] == {"entry": 0, "hold": 23, "exit": 1, "watch": 1275, "unavailable": 152}

    for strategy_id, trades in (
        ("PATTERN_A_FAST_FINAL_STRATEGY_V02", fast),
        ("PATTERN_B_SELECT_CORE_V01", b_select),
        ("JULIA_ETF_STRATEGY_V01", julia),
    ):
        identities = [
            (strategy_id, trade["ticker"], trade["trade_sequence"], trade["entry_execution_date"])
            for trade in trades
        ]
        assert len(identities) == len(set(identities))

    source_report = json.loads((ROOT / "web/data/stocks/005930.json").read_text(encoding="utf-8"))
    source_trade = source_report["strategy"]["history"][0]
    projected = next(
        trade for trade in fast
        if trade["ticker"] == "005930" and trade["trade_sequence"] == source_trade["trade_sequence"]
    )
    assert projected["entry_execution_date"] == source_trade["entry_execution_date"]
    assert projected["entry_price"] == source_trade["entry_open"]
    assert projected["exit_execution_date"] == source_trade["exit_execution_date"]
    assert projected["exit_price"] == source_trade["exit_price"]
    assert projected["return_pct"] == source_trade["return_pct"]
    assert projected["trade_status"] == source_trade["trade_status"]
    source_open = next(trade for trade in source_report["strategy"]["history"] if trade["trade_status"].startswith("OPEN"))
    projected_open = next(
        trade for trade in fast
        if trade["ticker"] == "005930" and trade["trade_sequence"] == source_open["trade_sequence"]
    )
    assert projected_open["entry_execution_date"] == source_open["entry_execution_date"]
    assert projected_open["entry_price"] == source_open["entry_open"]
    assert projected_open["return_pct"] == source_open["return_pct"]
    assert projected_open["trade_status"] == source_open["trade_status"]

    julia_report = json.loads((ROOT / "web/data/stocks/069500.json").read_text(encoding="utf-8"))
    julia_source = julia_report["strategy"]["history"][0]
    julia_projected = next(
        trade for trade in julia
        if trade["ticker"] == "069500" and trade["trade_sequence"] == julia_source["trade_sequence"]
    )
    assert julia_projected["entry_execution_date"] == julia_source["entry_execution_date"]
    assert julia_projected["entry_price"] == julia_source["entry_open"]
    assert julia_projected["exit_execution_date"] == julia_source["exit_execution_date"]
    assert julia_projected["exit_price"] == julia_source["exit_price"]
    assert julia_projected["return_pct"] == julia_source["return_pct"]
    assert julia_projected["trade_status"] == julia_source["trade_status"]
    julia_open_ticker = None
    julia_open_source = None
    for item in index["items"]:
        if item.get("report_available") is not True or item.get("asset_type") != "ETF":
            continue
        candidate = json.loads((ROOT / "web/data/stocks" / f"{item['ticker']}.json").read_text(encoding="utf-8"))
        candidate_trade = next(
            (trade for trade in (candidate.get("strategy") or {}).get("history", [])
             if trade.get("trade_status", "").startswith("OPEN")),
            None,
        )
        if candidate_trade:
            julia_open_ticker = item["ticker"]
            julia_open_source = candidate_trade
            break
    assert julia_open_source is not None and julia_open_ticker is not None
    julia_open_projected = next(
        trade for trade in julia
        if trade["ticker"] == julia_open_ticker and trade["trade_sequence"] == julia_open_source["trade_sequence"]
    )
    assert julia_open_projected["entry_execution_date"] == julia_open_source["entry_execution_date"]
    assert julia_open_projected["entry_price"] == julia_open_source["entry_open"]
    assert julia_open_projected["return_pct"] == julia_open_source["return_pct"]
    assert julia_open_projected["trade_status"] == julia_open_source["trade_status"]

    realized_b = next(trade for trade in b_status_trades if trade["trade_status"] == "REALIZED")
    realized_b_projected = next(
        trade for trade in b_select
        if trade["ticker"] == next(
            item["ticker"] for item in b_status["items"]
            if realized_b in item.get("trade_history", [])
        ) and trade["trade_sequence"] == realized_b["trade_sequence"]
    )
    assert realized_b_projected["entry_execution_date"] == realized_b["entry_execution_date"]
    assert realized_b_projected["entry_price"] == realized_b["entry_open"]
    assert realized_b_projected["exit_execution_date"] == realized_b["exit_execution_date"]
    assert realized_b_projected["exit_price"] == realized_b["exit_price"]
    assert realized_b_projected["return_pct"] == realized_b["return_pct"]
    assert realized_b_projected["trade_status"] == "REALIZED"
    open_b_item = next(item for item in b_status["items"] if item.get("canonical_position") == "OPEN")
    open_b = next(trade for trade in open_b_item["trade_history"] if trade["trade_status"] == "OPEN_AT_REFERENCE")
    open_b_projected = next(
        trade for trade in b_select
        if trade["ticker"] == open_b_item["ticker"] and trade["trade_sequence"] == open_b["trade_sequence"]
    )
    assert open_b_projected["entry_execution_date"] == open_b["entry_execution_date"]
    assert open_b_projected["entry_price"] == open_b["entry_open"]
    assert open_b_projected["return_pct"] == open_b_item["current_trade"]["return_pct"]
    assert open_b_projected["trade_status"] == "OPEN_AT_REFERENCE"


def test_trade_history_views_map_execution_dates_to_monthly_events():
    strategy_html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")

    for label in ("현재 상태", "거래 이력", "전체 거래", "월별", "전체", "완료", "보유"):
        assert label in strategy_html
    assert 'data-history-filter="completed"' in strategy_html
    assert 'data-history-filter="open"' in strategy_html
    assert '[["all", "전체"], ["completed", "완료"], ["open", "보유"]]' in strategy_js
    assert '[["all", "전체"], ["buy", "매수"], ["sell", "매도"]]' in strategy_js
    assert 'date: trade.entry_execution_date' in strategy_js
    assert 'type: "buy"' in strategy_js
    assert 'date: trade.exit_execution_date' in strategy_js
    assert 'type: "sell"' in strategy_js
    assert 'String(event.date || "").slice(0, 7)' in strategy_js
    assert 'b.localeCompare(a)' in strategy_js
    assert '표시할 거래 이력이 없습니다.' in strategy_js


def test_trade_history_filter_contract_and_korean_exit_reasons():
    strategy_js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    report_js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")

    assert 'if (historyFilter === "completed") return trade.trade_status === "REALIZED";' in strategy_js
    assert 'if (historyFilter === "open") return isOpenTrade(trade);' in strategy_js
    assert 'String(trade.trade_status || "").startsWith("OPEN")' in strategy_js
    assert 'if (historySubView !== "trades") return true;' in strategy_js
    assert 'makeTradeEvents(trades).filter((event) => historyFilter === "all" || event.type === historyFilter)' in strategy_js
    assert 'const allowedFilters = historySubView === "trades" ? ["all", "completed", "open"] : ["all", "buy", "sell"];' in strategy_js
    for code, label in (
        ("LOSS_GUARD_CLOSE_LE_NEG_15", "손실 제한"),
        ("EXIT3_PROGRESSED_TO_TRANSITION", "추세 전환"),
        ("EXIT4_SCORE_DRAWDOWN_GE_15", "점수 하락"),
        ("PATTERN_B_NORMAL_NEXT_OPEN", "Pattern B 정상 전환"),
    ):
        assert f'{code}: "{label}"' in strategy_js
        assert f'{code}: "{label}"' in report_js
    assert 'EXIT_REASON_LABELS[value] || value || "—"' in strategy_js
    assert 'label(EXIT_TYPE_LABELS, value, value || "종료 기준 확인 필요")' in report_js
