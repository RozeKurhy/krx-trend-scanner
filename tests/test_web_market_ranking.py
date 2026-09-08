"""Focused WEB-04C validation for the static market-strength ranking projection."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_market_ranking_web.py"
RANKING_PATH = ROOT / "web/data/market-ranking.json"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_market_ranking_web", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_ranking() -> dict:
    return json.loads(RANKING_PATH.read_text(encoding="utf-8"))


def test_market_ranking_schema_scope_and_generated_projection_match():
    exporter = _load_exporter()
    ranking = _load_ranking()

    assert ranking == exporter.build_market_ranking()
    assert ranking["schema_version"] == 1
    assert ranking["scope"] == {
        "type": "PUBLISHED_REPORTS",
        "label": "현재 공개 리포트 기준",
        "report_count": 158,
    }
    assert ranking["metric_scope"] == {"label": "마켓 RS는 전체 보통주 기준"}
    assert ranking["as_of"] == "2026-09-04"
    assert ranking["eligible_counts"] == {"2w": 141, "1m": 141, "3m": 141, "6m": 141, "12m": 141}
    assert len(ranking["items"]) == ranking["scope"]["report_count"]


def test_market_ranking_uses_published_reports_and_preserves_identity():
    ranking = _load_ranking()
    index = json.loads((ROOT / "web/data/stock-index.json").read_text(encoding="utf-8"))
    published = {item["ticker"]: item for item in index["items"] if item["report_available"] is True}

    assert {item["ticker"] for item in ranking["items"]} == set(published)
    for item in ranking["items"]:
        source = published[item["ticker"]]
        assert {key: item[key] for key in ("ticker", "name", "market", "asset_type")} == {
            key: source[key] for key in ("ticker", "name", "market", "asset_type")
        }
        assert {
            "ticker", "name", "market", "asset_type", "sector_name", "latest_close", "latest_close_as_of",
            "stock_return_2w", "stock_return_1m", "stock_return_3m", "stock_return_6m", "stock_return_12m",
            "percentile_2w", "percentile_1m", "percentile_3m", "percentile_6m", "percentile_12m", "market_strength_applicability",
            "market_strength_status", "pattern_stage", "pattern_score", "flow_state", "flow_data_status",
            "strategy_action",
        } <= item.keys()


def test_market_strength_percentiles_are_canonical_and_raw_rs_is_not_projected():
    ranking = _load_ranking()
    source = json.loads((ROOT / "web/data/stocks/005930.json").read_text(encoding="utf-8"))
    item = next(item for item in ranking["items"] if item["ticker"] == "005930")

    for horizon in ("2w", "1m", "3m", "6m", "12m"):
        assert item[f"percentile_{horizon}"] == source["market_strength"][f"percentile_{horizon}"]
        assert 0 <= item[f"percentile_{horizon}"] <= 100
    assert item["market_strength_applicability"] == "APPLICABLE"
    assert item["market_strength_status"] == "READY"
    assert "market_rs_3m" not in json.dumps(ranking, ensure_ascii=False)
    assert "market_rs_6m" not in json.dumps(ranking, ensure_ascii=False)
    assert "market_rs_12m" not in json.dumps(ranking, ensure_ascii=False)


def test_market_strength_returns_project_from_compact_stock_report_without_recalculation():
    ranking = _load_ranking()
    source = json.loads((ROOT / "web/data/stocks/005930.json").read_text(encoding="utf-8"))
    item = next(item for item in ranking["items"] if item["ticker"] == "005930")

    for horizon in ("2w", "1m", "3m", "6m", "12m"):
        field = f"stock_return_{horizon}"
        assert item[field] == source["market_strength"][field]


def test_eligibility_is_independent_per_horizon_and_excludes_etf():
    ranking = _load_ranking()
    etf = next(item for item in ranking["items"] if item["ticker"] == "069500")

    assert etf["asset_type"] == "ETF"
    assert etf["market_strength_applicability"] == "NOT_APPLICABLE"
    assert etf["market_strength_status"] == "NOT_EVALUATED"
    for horizon in ("2w", "1m", "3m", "6m", "12m"):
        eligible = [
            item for item in ranking["items"]
            if item["asset_type"] == "COMMON"
            and item["market_strength_applicability"] == "APPLICABLE"
            and item["market_strength_status"] == "READY"
            and isinstance(item[f"percentile_{horizon}"], (int, float))
            and 0 <= item[f"percentile_{horizon}"] <= 100
        ]
        assert len(eligible) == ranking["eligible_counts"][horizon]


def test_market_page_has_accessible_controls_and_release_contract():
    html = (ROOT / "web/market.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/market.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert '<title>랭킹 · KRX Trend Scanner</title>' in html
    assert '<a class="nav-item is-active" href="./market.html" aria-current="page">랭킹</a>' in html
    assert 'href="./css/app.css?v=web-02c-toss-1"' in html
    assert 'src="./js/market.js?v=web-02c-toss-1"' in html
    assert '<nav class="ranking-tabs" aria-label="랭킹 종류">' in html
    assert '<a class="ranking-tab is-active" href="./market.html" aria-current="page">마켓 RS</a>' in html
    for label in ("섹터 RS", "섹터 랭킹", "매출액 성장률", "영업이익 성장률", "순이익 성장률"):
        assert f'<span class="ranking-tab" aria-disabled="true">{label} <small>준비 중</small></span>' in html
    assert 'data-horizon="2w"' in html and 'data-horizon="1m"' in html
    assert 'data-horizon="3m"' in html and 'data-horizon="6m"' in html and 'data-horizon="12m"' in html
    assert 'data-market="ALL"' in html and 'data-market="KOSPI"' in html and 'data-market="KOSDAQ"' in html
    assert 'id="market-search"' in html
    assert 'id="market-ranking-list"' in html
    assert 'link.href = `./report.html?ticker=' in js
    assert 'const RANKING_URL = "./data/market-ranking.json";' in js
    assert 'right[field] - left[field]' in js
    assert 'String(left.name || "").localeCompare(String(right.name || ""), "ko-KR")' in js
    assert 'String(left.ticker || "").localeCompare(String(right.ticker || ""))' in js
    assert '100 - percentile' in js
    assert "function formatReturn(value)" in js
    assert 'return "—";' in js
    assert "return-positive" in js and "return-negative" in js and "return-neutral" in js
    assert 'createField("기간 등락"' in js
    assert "const periodReturn = item[stockReturnField(activeHorizon)];" in js
    assert 'if (percent === 0) return "0.0%";' in js
    assert 'percent > 0 ? "+" : ""' in js
    assert 'activeMarket === "ALL" || item.market === activeMarket' in js
    assert '.market-ranking-row' in css
    assert '.ranking-tabs' in css and '.ranking-tab[aria-disabled="true"]' in css
    assert '.market-control:focus-visible' in css
    assert '@media (max-width: 560px)' in css


def test_market_page_keeps_navigation_and_old_release_cache_out_of_all_pages():
    pages = [ROOT / "web/index.html", ROOT / "web/report.html", ROOT / "web/strategy.html", ROOT / "web/market.html"]
    for path in pages:
        html = path.read_text(encoding="utf-8")
        assert "web-02c-toss-1" in html
        assert "web-03a-final-1" not in html
        assert 'href="./market.html"' in html
        assert "랭킹" in html
        assert "시장 랭킹" not in html
    assert "시장 강도" not in "\n".join(path.read_text(encoding="utf-8") for path in pages)


def test_public_ranking_labels_use_market_rs_without_renaming_internal_fields():
    public_paths = [
        ROOT / "web/index.html", ROOT / "web/report.html", ROOT / "web/strategy.html", ROOT / "web/market.html",
        ROOT / "web/js/app.js", ROOT / "web/js/report.js", ROOT / "web/js/strategy.js", ROOT / "web/js/market.js",
    ]
    public = "\n".join(path.read_text(encoding="utf-8") for path in public_paths)

    for old_label in ("시장 랭킹", "시장 강도", "시장 대비", "시장 내 위치"):
        assert old_label not in public
    assert "마켓 RS" in public
    assert "market_strength" in public


def test_market_ranking_sort_and_filter_keep_canonical_percentiles():
    ranking = _load_ranking()
    js = (ROOT / "web/js/market.js").read_text(encoding="utf-8")
    eligible = [item for item in ranking["items"] if item["asset_type"] == "COMMON"]

    expected = sorted(eligible, key=lambda item: (-item["percentile_1m"], item["name"], item["ticker"]))
    assert expected[0]["percentile_1m"] >= expected[-1]["percentile_1m"]
    assert 'activeHorizon = "1m"' in js
    assert "activeMarket === \"ALL\" || item.market === activeMarket" in js
    assert ".filter((item) => isEligible(item, activeHorizon))" in js
    assert ".sort((left, right) =>" in js
    assert "pattern_score" in js
    assert "market_rs" not in js
    assert "returnOrder" not in js
    assert "stock_return_" in js
