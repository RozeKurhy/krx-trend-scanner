"""Focused validation for the Sector RS web tab contract."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECTOR_PAGE = ROOT / "web/sector.html"
SECTOR_SCRIPT = ROOT / "web/js/sector.js"
SECTOR_CSS = ROOT / "web/css/app.css"
PAYLOAD = ROOT / "web/data/sector-rs-ranking.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_payload() -> dict:
    return json.loads(_read(PAYLOAD))


def test_sector_page_activates_only_sector_rs_and_exposes_accessible_controls():
    html = _read(SECTOR_PAGE)

    assert 'href="./css/app.css?v=web-sector-rs-1"' in html
    assert 'src="./js/sector.js?v=web-sector-rs-1"' in html
    assert '<a class="ranking-tab" href="./market.html">마켓 RS</a>' in html
    assert '<a class="ranking-tab is-active" href="./sector.html" aria-current="page">섹터 RS</a>' in html
    assert '<span class="ranking-tab" aria-disabled="true">섹터 랭킹 <small>준비 중</small></span>' in html
    assert 'id="sector-select"' in html
    assert 'for="sector-select"' in html
    assert 'id="sector-search"' in html
    assert 'id="sector-ranking-list"' in html
    assert 'aria-live="polite"' in html
    assert '섹터 RS 랭킹을 불러올 수 없습니다.' in html
    assert html.count('data-horizon=') == 5
    assert 'data-horizon="2w"' in html
    assert 'data-horizon="1m"' in html
    assert 'data-horizon="3m"' in html
    assert 'data-horizon="6m"' in html
    assert 'data-horizon="12m"' in html
    assert 'data-market=' not in html


def test_sector_script_uses_static_payload_and_payload_authority_for_rendering():
    script = _read(SECTOR_SCRIPT)

    assert 'const PAYLOAD_URL = "./data/sector-rs-ranking.json";' in script
    assert 'const HORIZONS = ["2w", "1m", "3m", "6m", "12m"];' in script
    assert 'let activeHorizon = "1m";' in script
    assert 'value.schema_version === 1' in script
    assert 'value.metric_scope.type === "WITHIN_SECTOR"' in script
    assert 'JSON.stringify(value.metric_scope.group_key) === JSON.stringify(["market", "sector_code"])' in script
    assert 'option.value = sector.sector_key' in script
    assert 'option.textContent = `${marketLabel(sector.market)} · ${sector.sector_name}`' in script
    assert 'new URLSearchParams(window.location.search).get("sector")' in script
    assert 'payload.sectors[0].sector_key' in script
    assert 'item.sector_key === activeSectorKey' in script
    assert 'Number.isFinite(Number(item[rankField]))' in script
    assert 'rankOrder = Number(left[rankField]) - Number(right[rankField])' in script
    assert 'const topPercent = 100 - percentile;' in script
    assert 'const rsField = `sector_rs_${activeHorizon}`' in script
    assert 'item.report_available' in script
    assert './report.html?ticker=' in script
    assert 'market-ranking.json' not in script
    assert 'data-market' not in script
    assert 'activeMarket' not in script


def test_payload_supports_canonical_selector_groups_and_within_sector_sorting():
    payload = _load_payload()
    sectors = payload["sectors"]

    assert payload["schema_version"] == 1
    assert payload["horizons"] == ["2w", "1m", "3m", "6m", "12m"]
    assert payload["metric_scope"]["type"] == "WITHIN_SECTOR"
    assert payload["metric_scope"]["group_key"] == ["market", "sector_code"]
    assert len(sectors) == 45
    assert len({sector["sector_key"] for sector in sectors}) == 45
    assert all(sector["market"] in {"KOSPI", "KOSDAQ"} for sector in sectors)
    assert all(sector["sector_key"].startswith(f'{sector["market"]}:') for sector in sectors)
    assert all(item["membership_status"] != "UNMAPPED" or item["sector_key"] is None for item in payload["items"])

    selected = sectors[0]
    rows = [
        item for item in payload["items"]
        if item["sector_key"] == selected["sector_key"]
        and item["within_sector_rs_rank_1m"] is not None
        and math.isfinite(float(item["within_sector_rs_rank_1m"]))
    ]
    expected = sorted(rows, key=lambda item: (float(item["within_sector_rs_rank_1m"]), item["name"], item["ticker"]))
    assert [item["ticker"] for item in expected[:3]] == ["050090", "397810", "025980"]
    assert selected["eligible_count_1m"] == len(rows)


def test_sector_payload_report_availability_has_a_safe_non_link_branch():
    payload = _load_payload()
    assert sum(bool(item["report_available"]) for item in payload["items"]) == 248
    assert sum(not item["report_available"] for item in payload["items"]) == 2314

    script = _read(SECTOR_SCRIPT)
    assert 'createElement("a", "sector-ranking-report", "리포트 보기 ›")' in script
    assert 'createElement("span", "sector-ranking-report is-disabled", "리포트 준비 중")' in script


def test_sector_css_has_desktop_mobile_dark_mode_and_focus_support():
    css = _read(SECTOR_CSS)
    assert ".sector-select" in css
    assert ".sector-ranking-row" in css
    assert ".sector-ranking-report.is-disabled" in css
    assert ".sector-select:focus-visible" in css
    assert "@media (max-width: 560px)" in css
    assert '[data-theme="dark"]' in css
