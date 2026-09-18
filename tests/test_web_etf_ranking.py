"""Focused validation for the fixed ETF ranking web projection."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_etf_ranking_web.py"
RANKING_PATH = ROOT / "web/data/etf-ranking.json"
ETF_TICKERS = {
    "069500", "226490", "229200", "091160", "091180", "091170", "102970", "140700",
    "117700", "117680", "117460", "139230", "139260", "157490", "143860", "102960",
    "140710", "266410", "266390", "266360", "133690", "360750", "241180", "192090",
}
HORIZONS = {"2w": 10, "1m": 21, "3m": 63, "6m": 126, "12m": 252}


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_etf_ranking_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_ranking() -> dict:
    return json.loads(RANKING_PATH.read_text(encoding="utf-8"))


def test_etf_ranking_has_exact_fixed_scope_and_complete_finite_values():
    ranking = _load_ranking()
    assert ranking["schema_version"] == 1
    assert ranking["as_of"] == "2026-09-04"
    assert ranking["scope"] == {"type": "FIXED_ETF_UNIVERSE", "count": 24}
    assert ranking["horizons"] == HORIZONS
    assert len(ranking["items"]) == 24
    assert {item["ticker"] for item in ranking["items"]} == ETF_TICKERS
    assert len({item["ticker"] for item in ranking["items"]}) == 24
    for item in ranking["items"]:
        assert item["latest_close_as_of"] == "2026-09-04"
        assert item["group"] in {"MARKET", "SECTOR", "OVERSEAS"}
        assert item["category"]
        for key in ("latest_close", "return_2w", "return_1m", "return_3m", "return_6m", "return_12m"):
            assert isinstance(item[key], (int, float)) and not isinstance(item[key], bool)
            assert math.isfinite(float(item[key]))
        assert item["latest_close"] > 0


def test_etf_exporter_contract_is_fixed_and_uses_repository_authority():
    exporter = _load_exporter()
    assert len(exporter.ETF_UNIVERSE) == 24
    assert len({ticker for ticker, _group, _category in exporter.ETF_UNIVERSE}) == 24
    assert {ticker for ticker, _group, _category in exporter.ETF_UNIVERSE} == ETF_TICKERS
    assert exporter.AS_OF == "2026-09-04"
    assert exporter.HORIZONS == HORIZONS
    source = EXPORTER_PATH.read_text(encoding="utf-8")
    assert "build_repository_v2" in source
    assert "InstrumentMetadataResolver" in source
    assert "repository_v2_contract_for_metadata" in source
    assert "requests" not in source
    assert "pykrx" not in source


def test_etf_page_has_required_tabs_controls_and_no_report_or_search_ui():
    html = (ROOT / "web/etf.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/etf.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    assert '<title>ETF 랭킹 · KRX Trend Scanner</title>' in html
    assert 'href="./css/app.css?v=web-ui-density-10"' in html
    assert 'src="./js/etf.js?v=web-etf-ranking-1"' in html
    assert '<a class="ranking-tab is-active" href="./etf.html" aria-current="page">ETF</a>' in html
    expected_tabs = ("마켓 RS", "섹터 RS", "섹터 랭킹", "외인 순매수", "매출액 성장률", "영업이익 성장률", "순이익 성장률")
    assert [text for text in expected_tabs if text in html] == list(expected_tabs)
    assert html.count('data-horizon=') == 5
    assert 'data-horizon="1m" aria-pressed="true"' in html
    assert '기준일 2026.09.04 · 24개 ETF' in html
    assert 'id="etf-ranking-list"' in html
    assert 'id="etf-search"' not in html and 'type="search"' not in html and '<select' not in html
    ranking_section = html.split('<section id="etf-ranking-list"', 1)[1].split('</section>', 1)[0]
    assert "report.html" not in ranking_section and "report.html" not in js
    assert 'const RANKING_URL = "./data/etf-ranking.json";' in js
    assert 'let activeHorizon = "1m";' in js
    assert 'Number(right[field]) - Number(left[field])' in js
    assert 'String(left.name || "").localeCompare(String(right.name || ""), "ko-KR")' in js
    assert 'String(left.ticker || "").localeCompare(String(right.ticker || ""))' in js
    assert "return-positive" in js and "return-negative" in js and "return-neutral" in js
    assert ".etf-ranking-row" in css


def test_all_ranking_pages_expose_etf_first_and_primary_ranking_link():
    for name in ("etf", "market", "sector", "foreign"):
        html = (ROOT / f"web/{name}.html").read_text(encoding="utf-8")
        assert 'href="./etf.html"' in html
        assert 'href="./css/app.css?v=web-ui-density-10"' in html
        tabs = html.split('<nav class="ranking-tabs"', 1)
        if len(tabs) == 2:
            assert tabs[1].index('href="./etf.html"') < tabs[1].index('마켓 RS') if name != "etf" else 'aria-current="page">ETF</a>' in tabs[1]
    for name in ("index", "fear", "market", "sector", "foreign", "report", "strategy", "etf"):
        html = (ROOT / f"web/{name}.html").read_text(encoding="utf-8")
        assert '<a class="nav-item' in html and 'href="./etf.html"' in html
