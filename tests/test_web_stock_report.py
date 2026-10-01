"""Focused WEB-02C validation for the local Stock Report web foundation."""

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


def test_payload_covers_pit_universe_and_existing_reports(payload, exporter):
    index, reports, stats = payload
    report_dir, requested_as_of = exporter._resolve_report_directory()
    universe, snapshot_date = exporter._load_universe(requested_as_of)
    source_reports = sorted((report_dir / "json").glob("*.json"))

    assert index["count"] == len(universe)
    assert index["available_report_count"] == len(source_reports)
    assert len(index["items"]) == len(universe)
    assert len(reports) == len(source_reports)
    assert stats["unavailable_report_count"] == len(universe) - len(source_reports)
    assert sum(item["report_available"] for item in index["items"]) == len(source_reports)
    assert index["requested_as_of"] == requested_as_of
    assert index["reference_market_date"] == stats["reference_market_date"]
    assert index["reference_market_date"] <= requested_as_of
    assert index["universe_snapshot_date"] == snapshot_date


def test_compact_report_preserves_authority_values_without_raw_markdown(payload, exporter):
    index, reports, _ = payload
    report = reports["005930"]
    item = next(candidate for candidate in index["items"] if candidate["ticker"] == "005930")

    assert item["report_available"] is True
    assert report["identity"]["ticker"] == "005930"
    assert report["identity"]["name"] == item["name"]
    assert report["decision"]["action"] in {"HOLD", "WAIT", "ENTER_NEXT_OPEN", "NONE", "WATCH", "ENTRY", "EXIT"}
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source = json.loads(next((report_dir / "json").glob("005930_*.json")).read_text(encoding="utf-8"))
    assert report["fundamentals"]["status"] == source["fundamentals"]["data_status"]
    assert report["fundamentals"]["summary"] == source["fundamentals"]["summary"]
    assert report["fundamentals"]["quarterly"] == source["fundamentals"]["quarterly"]
    assert report["fundamentals"]["annual"] == source["fundamentals"]["annual"]
    assert "diagnostics" not in report["fundamentals"]
    assert report["external_links"]["naver_finance"] == "https://finance.naver.com/item/main.naver?code=005930"
    assert report["external_links"]["naver_chart"] == "https://stock.naver.com/fchart/domestic/stock/005930"
    assert "toss_chart" not in report["external_links"]
    assert "summary_text" not in report
    assert "body" not in report
    assert "market_strength_state" not in report["summary"]
    assert "state" not in report["market_strength"]
    assert "/Users/" not in json.dumps(report, ensure_ascii=False)


def test_all_published_compact_reports_have_ticker_bound_naver_chart(payload):
    _index, reports, stats = payload
    source_count = len(list((ROOT / stats["source_report_directory"] / "json").glob("*.json")))

    assert len(reports) == source_count
    for ticker, report in reports.items():
        links = report["external_links"]
        assert links["naver_finance"] == f"https://finance.naver.com/item/main.naver?code={ticker}"
        assert links["naver_chart"] == f"https://stock.naver.com/fchart/domestic/stock/{ticker}"
        assert "toss_chart" not in links


def test_exact_etf36_v06_projection_preserves_julia_and_common_sets(exporter):
    target_as_of = "2026-09-25"
    reference_market_date = "2026-09-23"
    index, reports, stats = exporter.build_web_payload(
        target_as_of=target_as_of,
        reference_market_date=reference_market_date,
        include_etf=True,
    )
    _etf_dir, etf_sources, _source_paths = exporter.validate_exact_etf_report_corpus(
        target_as_of, reference_market_date,
    )
    common_dir = ROOT / "artifacts/reporting/stock_reports/20260925/json"
    common_sources = [json.loads(path.read_text(encoding="utf-8")) for path in common_dir.glob("*.json")]
    common_tickers = {source["ticker"] for source in common_sources}
    expected_etf_tickers = set(etf_sources)
    available = {item["ticker"] for item in index["items"] if item["report_available"] is True}

    assert stats["common_report_count"] == 1451 == len(common_tickers)
    assert stats["etf_report_count"] == 36 == len(expected_etf_tickers)
    assert stats["available_report_count"] == 1487 == len(reports)
    assert available == common_tickers | expected_etf_tickers
    assert {ticker for ticker in reports if reports[ticker]["identity"]["asset_type"] == "COMMON"} == common_tickers
    assert {ticker for ticker in reports if reports[ticker]["identity"]["asset_type"] == "ETF"} == expected_etf_tickers

    for ticker, source in etf_sources.items():
        compact = reports[ticker]
        strategy = source["official_strategy"]
        eligibility = source["current_snapshot"]["etf_eligibility"]
        assert compact["identity"]["asset_type"] == "ETF"
        assert compact["technical_details"]["report_version"] == "0.6"
        assert compact["technical_details"]["requested_as_of"] == source["requested_as_of"] == target_as_of
        assert compact["technical_details"]["reference_market_date"] == source["reference_market_date"] == reference_market_date
        assert compact["pattern_b"] is None
        assert compact["strategy"]["source"] == "official_strategy"
        assert compact["strategy"]["strategy_id"] == strategy["strategy_id"] == "JULIA_ETF_STRATEGY_V01"
        assert compact["strategy"]["strategy_name"] == strategy["strategy_name"] == "Julia V1"
        assert compact["strategy"]["action"] == strategy["action"]
        assert compact["strategy"]["state"] == strategy["strategy_state"]
        assert compact["strategy"]["position"] == strategy["canonical_position"]
        assert compact["strategy"]["action_reason"] == strategy["action_reason"]
        assert compact["strategy"]["interpretation"] == strategy["interpretation"]
        assert compact["strategy"]["eligibility"] == eligibility
        assert compact["pattern"]["official_stage"] == source["current_snapshot"]["official_stage"]
        assert compact["pattern"]["score"] == source["current_snapshot"]["pattern_a_score"]
        assert compact["pattern"]["history_12m"] == exporter._compact_monthly_history(source["monthly_history"])
        assert compact["flow"]["data_status"] == source["foreign_flow"]["data_status"]
        assert compact["market_strength"]["applicability"] == source["relative_strength"]["applicability"]
        assert compact["market_strength"]["data_status"] == source["relative_strength"]["data_status"]
        assert compact["fundamentals"]["status"] == source["fundamentals"]["data_status"]

    report = reports["069500"]
    assert report["identity"]["name"] == "KODEX 200"
    assert report["strategy"]["action"] == "WAIT"
    assert report["price_trend"]["latest_close"] == 113145.0
    assert report["price_trend"]["latest_close_as_of"] == reference_market_date


def test_fundamentals_projection_preserves_source_status_and_applicability(payload, exporter):
    _index, reports, _stats = payload
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source_reports = [json.loads(path.read_text(encoding="utf-8")) for path in (report_dir / "json").glob("*.json")]
    assert source_reports
    assert all(source["asset_type"] == "COMMON" for source in source_reports)
    for source in source_reports:
        compact = reports[source["ticker"]]
        assert compact["fundamentals"]["status"] == source["fundamentals"]["data_status"]
        assert compact["fundamentals"]["applicability"] == source["fundamentals"]["applicability"]
    assert all("diagnostics" not in report["fundamentals"] for report in reports.values())


def test_daily_price_uses_exact_local_authority_date_and_not_monthly_history(payload, exporter):
    _index, reports, _stats = payload
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (report_dir / "json").glob("005930_*.json")
    )
    expected = exporter._load_exact_daily_close("005930", source["reference_market_date"])
    compact = reports["005930"]

    assert expected is not None
    assert compact["price_trend"]["latest_close"] == expected["value"]
    assert compact["price_trend"]["latest_close_as_of"] == source["reference_market_date"]
    assert compact["price_trend"]["price_source"] == expected["source"]
    assert compact["technical_details"]["price_source"] == expected["source"]
    assert "monthly" not in compact["price_trend"]["price_source"]
    assert "_latest_monthly_observation" not in exporter.__dict__


def test_rs_is_display_mapping_only_and_not_recomputed(payload, exporter):
    _index, reports, _stats = payload
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (report_dir / "json").glob("005930_*.json")
    )
    compact = reports["005930"]
    source_rs = source["relative_strength"]

    assert not hasattr(exporter, "_market_strength_state")
    assert compact["market_strength"]["applicability"] == source_rs["applicability"]
    assert compact["market_strength"]["data_status"] == source_rs["data_status"]
    assert compact["market_strength"]["percentile_3m"] == source_rs["all_market_rs_percentile_3m"]
    assert compact["market_strength"]["market_rs_2w"] == source_rs["market_rs_2w"]
    assert compact["market_strength"]["market_rs_1m"] == source_rs["market_rs_1m"]
    assert compact["market_strength"]["percentile_2w"] == source_rs["all_market_rs_percentile_2w"]
    assert compact["market_strength"]["percentile_1m"] == source_rs["all_market_rs_percentile_1m"]
    for horizon in ("2w", "1m", "3m", "6m", "12m"):
        field = f"stock_return_{horizon}"
        assert compact["market_strength"][field] == source_rs[field]


def test_interaction_detail_payload_preserves_authority_history(payload, exporter):
    _index, reports, _stats = payload
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (report_dir / "json").glob("005930_*.json")
    )
    compact = reports["005930"]

    expected_pattern = [
        {
            "as_of": item["as_of"],
            "close": item["close"],
            "score": item["score"],
            "stage": item["stage"],
            "candidate_state": item["candidate_state"],
            "data_available": item["data_available"],
        }
        for item in source["monthly_history"]["recent_12m_history"]
    ]
    assert compact["pattern"]["history_12m"] == expected_pattern
    assert len(compact["pattern"]["history_12m"]) == source["monthly_history"]["recent_12m_observation_count"]
    assert compact["pattern"]["history_12m"][0] == {
        "as_of": "2025-08-29",
        "close": 69700.0,
        "score": 61.93,
        "stage": "TRANSITION",
        "candidate_state": "candidate",
        "data_available": True,
    }
    assert compact["pattern"]["history_12m"][-1]["as_of"] == "2026-08-31"

    source_rs = source["relative_strength"]
    assert compact["market_strength"]["market_rs_3m"] == source_rs["market_rs_3m"]
    assert compact["market_strength"]["market_rs_2w"] == source_rs["market_rs_2w"]
    assert compact["market_strength"]["market_rs_1m"] == source_rs["market_rs_1m"]
    assert compact["market_strength"]["market_rs_6m"] == source_rs["market_rs_6m"]
    assert compact["market_strength"]["market_rs_12m"] == source_rs["market_rs_12m"]
    assert compact["market_strength"]["percentile_3m"] == source_rs["all_market_rs_percentile_3m"]
    assert compact["market_strength"]["percentile_6m"] == source_rs["all_market_rs_percentile_6m"]
    assert compact["market_strength"]["percentile_12m"] == source_rs["all_market_rs_percentile_12m"]
    for horizon in ("2w", "1m", "3m", "6m", "12m"):
        field = f"stock_return_{horizon}"
        assert compact["market_strength"][field] == source_rs[field]

    source_flow = source["foreign_flow"]
    assert compact["flow"]["net_buy_value_1d_krw"] == source_flow["foreign_net_buy_value_1d_krw"]
    assert compact["flow"]["net_buy_value_5d_krw"] == source_flow["foreign_net_buy_value_5d_krw"]
    assert compact["flow"]["net_buy_value_10d_krw"] == source_flow["foreign_net_buy_value_10d_krw"]
    assert compact["flow"]["net_buy_value_20d_krw"] == source_flow["foreign_net_buy_value_20d_krw"]
    assert compact["flow"]["net_buy_value_60d_krw"] == source_flow["foreign_net_buy_value_60d_krw"]
    assert compact["flow"]["positive_days_1d"] == source_flow["foreign_positive_days_1d"]
    assert compact["flow"]["positive_days_10d"] == source_flow["foreign_positive_days_10d"]
    assert compact["flow"]["positive_days_20d"] == source_flow["foreign_positive_days_20d"]
    assert compact["flow"]["intensity_1d"] == source_flow["foreign_flow_intensity_1d"]
    assert compact["flow"]["intensity_5d"] == source_flow["foreign_flow_intensity_5d"]
    assert compact["flow"]["intensity_10d"] == source_flow["foreign_flow_intensity_10d"]

    source_tv = source["trading_value_flow"]
    for window in (1, 5, 10, 20, 60):
        field = f"avg_trading_value_{window}d_eok"
        assert compact["price_trend"][field] == source_tv[field]

    source_strategy = source["a_fast_core"]
    history = compact["strategy"]["history"]
    assert len(history) == len(source_strategy["trade_history"]) == 6
    assert history[-1]["trade_status"] == "OPEN_AT_CUTOFF"
    assert history[-1]["trade_id"] == source_strategy["trade_history"][-1]["trade_id"]


def test_pattern_b_compact_projection_is_verbatim_and_does_not_recalculate(exporter, monkeypatch):
    report_dir, _requested_as_of = exporter._resolve_report_directory()
    source_path = next((report_dir / "json").glob("005930_*.json"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["report_version"] = "0.7"
    source["asset_type"] = "COMMON"
    source["pattern_b"] = {
        "applicability": "APPLICABLE",
        "evaluation_status": "READY",
        "pattern_b_state": "NORMAL",
        "as_of": source["reference_market_date"],
        "monthly_history": [{"as_of": source["reference_market_date"], "pattern_b_state": "NORMAL"}],
        "provenance": {"market_data_authority": "MarketDataRepositoryV2"},
    }
    exporter._validate_report_contract(source, source_path)
    monkeypatch.setattr(exporter, "_load_exact_daily_close", lambda *_args: None)

    compact = exporter._compact_report(source, source_path)

    assert compact["pattern_b"] == source["pattern_b"]
    assert not hasattr(exporter, "evaluate_pattern_b")
    assert all(row["as_of"] <= source["reference_market_date"] for row in compact["pattern_b"]["monthly_history"])


def test_v07_export_contract_fails_closed_without_common_pattern_b(exporter, tmp_path):
    source_path = tmp_path / "005930.json"

    with pytest.raises(ValueError, match="v0.7 COMMON Pattern B contract missing"):
        exporter._validate_report_contract(
            {"report_version": "0.7", "asset_type": "COMMON"}, source_path,
        )


def test_exporter_writes_index_and_one_json_per_available_report(tmp_path, exporter):
    report_dir, requested_as_of = exporter._resolve_report_directory()
    universe, _snapshot_date = exporter._load_universe(requested_as_of)
    source_report_count = len(list((report_dir / "json").glob("*.json")))
    stats = exporter.export_stock_reports(tmp_path)
    index_path = tmp_path / "stock-index.json"
    stock_dir = tmp_path / "stocks"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    assert stats["universe_count"] == len(universe)
    assert index["count"] == len(universe)
    assert len(list(stock_dir.glob("*.json"))) == source_report_count
    sample_ticker = next(path.stem for path in stock_dir.glob("*.json"))
    sample = json.loads((stock_dir / f"{sample_ticker}.json").read_text(encoding="utf-8"))
    assert sample["schema_version"] == 1
    assert sample["identity"]["ticker"] == sample_ticker
    assert sample["external_links"]["naver_chart"] == f"https://stock.naver.com/fchart/domestic/stock/{sample_ticker}"
    assert "toss_chart" not in sample["external_links"]
    assert sample["technical_details"]["source_report"].startswith("artifacts/reporting/stock_reports/")


def test_report_frontend_has_safe_states_and_relative_assets():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    index_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    favicon = (ROOT / "web/favicon.svg").read_text(encoding="utf-8")

    assert 'href="./css/app.css?v=web-ranking-report-link-v1"' in html
    assert 'href="./css/app.css?v=web-ranking-report-link-v1"' in index_html
    assert 'href="./favicon.svg"' in html
    assert 'href="./favicon.svg"' in index_html
    assert (ROOT / "web/favicon.svg").exists()
    assert '#9f1d2f' in favicon
    assert 'src="./js/report.js?v=web-julia-report-polish-v1"' in html
    assert 'src="./js/app.js?v=web-fear-fix02-4"' in index_html
    assert html.count("web-ranking-report-link-v1") == 1
    assert html.count("web-julia-report-polish-v1") == 1
    assert index_html.count("web-ranking-report-link-v1") == 1
    assert "web-03a-final-1" not in html
    assert "web-03a-final-1" not in index_html
    assert "web-02a-final-2" not in html
    assert "web-02a-final-2" not in index_html
    assert 'placeholder="종목명 또는 종목코드 검색"' in html
    assert 'id="report-empty"' in html
    assert 'id="recommendations"' in html
    assert "둘러보기" in html
    assert "추천 종목" not in html
    assert 'id="search-no-results"' in html
    assert 'id="report-pending"' in html
    assert 'id="report-error"' in html
    assert 'id="naver-link"' in html
    assert 'id="naver-chart-link"' in html
    assert 'id="dart-link"' in html
    assert '전자공시' in html
    assert 'target="_blank" rel="noopener"' in html
    assert "차트" in html
    assert "차트 바로가기" not in html
    assert "naver_chart" in js
    assert "toss_chart" not in js


    assert html.count('id="naver-link"') == 1
    assert html.count('id="naver-chart-link"') == 1
    assert html.count('id="dart-link"') == 1
    assert '<section class="panel report-search-panel" aria-label="종목 검색">' in html
    assert "class=\"report-search-label\"" not in html
    assert "검색하여 쉽게 핵심 판단" not in html
    assert 'class="page-intro"' not in html
    assert "검색 안내" not in html
    assert 'id="report-request-button"' in html
    assert "reportRequest" in js
    assert "요청 연결은 아직 준비되지 않았습니다." in js
    assert "요청 완료" not in js
    assert "전송되었습니다" not in js
    assert "종목명 또는 종목코드</label>" not in html
    assert "종목 리포트</p>\n        <h1" not in html
    assert 'const INDEX_URL = "./data/stock-index.json";' in js
    assert 'const STOCKS_PATH = "./data/stocks/";' in js
    assert "localStorage" in js and "krx-theme" in js
    assert "리포트 준비 중" in js
    assert "종목 정보를 찾을 수 없습니다." in js
    assert "일치하는 종목이 없습니다." in html
    assert "Math.random" in js
    assert "report_available === true" in js
    assert "randomSample(available, 20)" in js
    assert 'setHidden("search-no-results", true);' in js
    assert "PATTERN_STEPS" in js
    assert 'id="pattern-card"' in html
    assert 'id="pattern-b-card"' in html
    assert 'id="price-card"' in html
    assert 'id="market-card"' in html
    assert 'id="flow-card"' in html
    assert 'id="strategy-card"' in html
    assert html.count("상세 보기 ›") == 6
    card_order = [
        html.index('id="price-card"'), html.index('id="flow-card"'), html.index('id="market-card"'),
        html.index('id="pattern-card"'), html.index('id="pattern-b-card"'), html.index('id="strategy-card"'),
    ]
    assert card_order == sorted(card_order)
    assert "avg_trading_value_1d_eok" in js
    assert "avg_trading_value_10d_eok" in js
    assert "net_buy_value_10d_krw" in js
    assert "report-card-affordance" in js and "상세 닫기 ×" in js
    assert '.report-card-button { appearance: none; width: 100%; border-color: var(--line-strong); background: var(--surface);' in css
    assert 'const REPORT_MOBILE_QUERY = "(max-width: 560px)";' in js
    assert 'selectedCard.insertAdjacentElement("afterend", panel)' in js
    assert "window.addEventListener(\"resize\", repositionActiveDetail);" in js
    assert 'id="report-detail-panel"' in html
    assert 'class="report-summary-layout"' in html
    assert '<article class="panel decision-card"' in html
    assert '<aside class="panel report-context"' in html
    assert html.index('<article class="panel decision-card"') < html.index('<aside class="panel report-context"')
    assert html.index('id="report-actions"') < html.index('id="report-identity"')
    assert 'class="report-identity"' not in html
    assert 'class="visually-hidden">—</h2>' in html
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr))' in css
    assert '.report-summary-layout .decision-card { grid-column: span 2;' in css
    assert '.report-context { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: 14px; }' in css
    assert '.report-summary-layout, .report-card-row, .report-detail-grid { grid-template-columns: 1fr; }' in css
    assert '.report-summary-layout .decision-card { grid-column: auto; }' in css
    assert 'class="signal-grid"' not in html
    assert 'signal-trend' not in html and 'signal-market' not in html
    assert 'signal-flow' not in html and 'signal-fundamentals' not in html
    assert 'signal-grid' not in js and 'signal-trend' not in js
    assert 'signal-market' not in js and 'signal-flow' not in js and 'signal-fundamentals' not in js
    assert '.signal-grid' not in css and '.signal-card' not in css
    assert 'id="fundamentals-detail-panel"' in html
    assert 'id="fundamentals-summary"' not in html
    assert 'id="fundamentals-detail-meta"' not in html
    assert 'id="fundamentals-detail-heading">펀더멘탈</h3>' in html
    assert "Fundamentals 상세" not in html
    assert 'id="fundamentals-unit-note"' not in html
    assert 'fundamentals-unit-note' not in js
    assert 'fundamentals-unit-note' not in css
    assert '단위: 억원' in html
    assert 'id="fundamentals-periods"' in html
    assert 'id="top-detail-slot"' in html
    assert 'id="bottom-detail-slot"' in html
    assert 'aria-expanded="false"' in html
    assert "history_12m" in js
    assert "pattern-score-chart" in js
    assert "pattern-b-state-chart" in js
    assert 'id="pattern-b-stepper"' in html
    assert 'id="pattern-value"' not in html
    assert 'id="pattern-b-value"' not in html
    assert 'setText("pattern-value"' not in js
    assert 'setText("pattern-b-value"' not in js
    assert '["DEEP_DEPRESSED", "깊은 침체"]' in js
    assert '["DEPRESSED", "침체"]' in js
    assert '["NORMAL", "정상"]' in js
    assert '["EXTREME_OVERHEATED", "극단 과열"]' in js
    assert 'renderStatusStepper(' in js and '"pattern-b-stepper"' in js
    assert 'createDetailTable(["기준일", "종가", "상태", "36M 범위", "24M선 이격", "52W 범위"]' in js
    assert 'patternACloses.get(monthlyLastBar)' in js
    pattern_b_detail = js[js.index("function renderPatternBDetail"):js.index("function renderMarketDetail")]
    assert 'createDetailTable(["현재 지표", "값"]' not in pattern_b_detail
    assert '"현재 상태"' not in pattern_b_detail
    card_render = js[js.index('renderPatternStepper(report.pattern.official_stage)'):js.index('setText("market-value"')]
    assert 'setText("pattern-value"' not in card_render
    assert 'patternBStateLabel(patternB.pattern_b_state)' not in card_render
    assert '36M ${formatPatternBRange(patternB.range_36m)} · 24M ${formatSignedRate(patternB.monthly_ma24_distance)} · 52W ${formatPatternBRange(patternB.range_52w)}' in card_render
    assert "해당 없음 · ETF v0.6에는 Pattern B를 적용하지 않습니다." in card_render
    assert "정보 없음 · Pattern B 상태 데이터 없음" in card_render
    for removed in (
        "가격 권위 ",
        "Pattern B는 정보성 상태 분석이며 B Select Core V1의 매수·매도 전략 실행과 별개입니다.",
        "마지막 월봉 ",
    ):
        assert removed not in js
    assert "renderPatternBDetail" in js
    assert 'id: "pattern-score-chart"' in js
    assert 'role: "img"' in js
    assert "최근 패턴 점수 추이" in js
    assert "sector_name" in js
    assert "percentile_6m" in js and "percentile_12m" in js
    assert "formatKrwCompact" in js
    assert "renderFundamentalsDetail" in js
    assert "ttm_operating_cash_flow_krw" not in js
    assert "fundamentals-summary-grid" not in css
    assert "operating_income_yoy_pct" in js
    assert "fundamentals-table" in js and "fundamentals-table" in css
    assert "fundamental-loss" in js and "fundamental-loss" in css
    assert 'header: "TTM"' in js
    assert "formatKrwAsEok" in js
    assert "formatEokAmount" in js
    assert "${formatNumber(absolute)}억원" in js
    assert "조원" not in js
    assert "펀더멘털 V1 적용 대상 아님" in js
    assert "filter_status" in js
    assert "position: sticky" in css
    assert "strategy.history" in js
    assert "100 - Number(value)" in js
    for percentile, expected in ((92.51, 7.5), (76.6, 23.4), (99.20, 0.8)):
        assert round(100 - percentile, 1) == expected
    assert "Npay 증권" in html
    assert "차트</a>" in html
    assert "전자공시</a>" in html
    assert "DART_SEARCH_URL" in js
    assert "dart-link" in js
    assert "report.identity.ticker" in js
    assert "https://dart.fss.or.kr/html/search/SearchCompanyIR3_M.html" in js
    assert "textCrpNM=" in js
    assert "encodeURIComponent(ticker)" in js
    assert "F8" not in html and "WEB-02A" not in html
    assert "_market_strength_state" not in js
    assert "innerHTML" not in js
    assert "href=\"./report.html\"" in html
    assert ".report-card-grid" in css
    assert ".report-card-row" in css
    assert ".pattern-arrow" in css
    assert ".pattern-stepper" in css
    assert "flex-wrap: nowrap" in css
    assert "column-gap: 0" in css
    assert "margin-inline: 3px" in css
    assert ".pattern-step { padding: 4px 5px;" in css
    assert ".pattern-step, .pattern-arrow" in css
    assert ".report-card-affordance" in css
    assert ".report-summary-layout { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".report-context { display: flex;" in css
    assert "@media (max-width: 560px)" in css
    assert html.count('<p class="eyebrow">검색 안내</p>') == 0
    assert "가격 출처" in js
    assert "가격 authority" not in js
    assert "report-detail-subtitle" not in html
    assert "선택 상세" not in html
    assert "canonical" not in js
    assert "과거 전략 이력은 과거 데이터에 전략 규칙을 적용한 결과이며 미래 수익을 의미하지 않습니다." in js
    assert "과거 Julia V1 거래 이력은" not in js
    strategy_detail = js[js.index("function renderStrategyDetail"):js.index("function isMobileLayout")]
    etf_detail = strategy_detail[strategy_detail.index("if (isEtf)"):strategy_detail.index("if (strategy.strategy_name)")]
    assert 'report.identity.asset_type === "ETF"' in strategy_detail
    assert 'appendStrategyHistory(history, container)' in etf_detail
    history_renderer = js[js.index("function appendStrategyHistory"):js.index("function renderStrategyDetail")]
    assert 'createDetailTable(["회차"' in history_renderer
    assert '"strategy-history-table"' in history_renderer
    assert '표시할 전략 이력이 없습니다.' in history_renderer
    assert 'appendDetailNote' not in etf_detail
    assert 'etf-eligibility-table' not in strategy_detail
    assert "signedValueClass" in js
    assert "--market-down-blue" in css
    assert "history[-12:]" not in (ROOT / "scripts/export_stock_report_web.py").read_text(encoding="utf-8")


def test_report_cards_share_three_column_desktop_rows():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert html.count('class="report-card-row"') == 2
    assert "report-card-row--secondary" not in html
    assert ".report-card-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }" in css
    assert "report-card-row--secondary" not in css
    assert ".report-card-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in css
    assert ".report-summary-layout, .report-card-row, .report-detail-grid { grid-template-columns: 1fr; }" in css


def test_report_request_state_is_distinct_from_available_reports(payload):
    index, _reports, _stats = payload
    available = next(item for item in index["items"] if item["ticker"] == "005930")
    unavailable = next(item for item in index["items"] if item["report_available"] is False)

    assert available["report_available"] is True
    assert unavailable["report_available"] is False


def test_index_navigation_keeps_health_and_report_pages_connected():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    assert 'href="./index.html"' in html
    assert 'href="./report.html"' in html
    assert '종목 리포트 <small>준비 중</small>' not in html
