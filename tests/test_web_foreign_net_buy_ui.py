"""Focused validation for the Foreign Net Buy ranking web tab."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_foreign_tab_is_after_disabled_sector_ranking_on_all_ranking_pages():
    for path in (ROOT / "web/market.html", ROOT / "web/sector.html", ROOT / "web/foreign.html"):
        html = _read(path)
        disabled = '<span class="ranking-tab" aria-disabled="true">섹터 랭킹 <small>준비 중</small></span>'
        foreign = '<a class="ranking-tab" href="./foreign.html">외인 순매수</a>'
        active_foreign = '<a class="ranking-tab is-active" href="./foreign.html" aria-current="page">외인 순매수</a>'
        assert disabled in html
        assert foreign in html or active_foreign in html
        assert html.index(disabled) < html.index(foreign if foreign in html else active_foreign)


def test_foreign_page_exposes_default_20d_filters_search_and_report_contract():
    html = _read(ROOT / "web/foreign.html")
    script = _read(ROOT / "web/js/foreign.js")
    css = _read(ROOT / "web/css/app.css")

    assert '<title>외인 순매수 · KRX Trend Scanner</title>' in html
    assert '<h1 id="page-title">외인 순매수</h1>' in html
    assert '<p class="lede">외국인 사랑을 받는 종목은?</p>' in html
    assert '외국인 누적 순매수대금으로 보는 종목 흐름' not in html
    assert 'href="./css/app.css?v=web-foreign-net-buy-1"' in html
    assert 'src="./js/foreign.js?v=web-foreign-net-buy-2"' in html
    assert 'data-horizon="1d"' in html and 'data-horizon="5d"' in html
    assert 'data-horizon="10d"' in html and 'data-horizon="20d"' in html and 'data-horizon="60d"' in html
    assert 'data-horizon="20d" aria-pressed="true"' in html
    assert 'data-market="ALL"' in html and 'data-market="KOSPI"' in html and 'data-market="KOSDAQ"' in html
    assert 'id="foreign-search"' in html
    assert 'id="foreign-ranking-list"' in html
    assert 'const PAYLOAD_URL = "./data/foreign-net-buy-ranking.json";' in script
    assert 'const HORIZONS = ["1d", "5d", "10d", "20d", "60d"];' in script
    assert 'let activeHorizon = "20d";' in script
    assert 'foreign_net_buy_${activeHorizon}' in script
    assert 'function validFlow(value)' in script
    assert '.filter((item) => validFlow(item[field]))' in script
    assert 'item.sector_name' in script
    assert 'item.report_available' in script
    assert '리포트 준비 중' in script
    assert 'foreign-ranking-row' in css
    assert '.foreign-ranking-report.is-disabled' in css
    assert '@media (max-width: 560px)' in css


def test_foreign_page_does_not_introduce_top_n_clipping_and_keeps_mobile_layout():
    script = _read(ROOT / "web/js/foreign.js")
    css = _read(ROOT / "web/css/app.css")
    assert "slice(0, 50)" not in script
    assert "slice(0, 100)" not in script
    assert ".foreign-ranking-row { grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".foreign-ranking-identity, .foreign-ranking-report { grid-column: 1 / -1; }" in css
