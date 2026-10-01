"""Focused checks for the cross-sector return ranking view."""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
HORIZONS = ("2w", "1m", "3m", "6m", "12m")
PAYLOAD_PATH = ROOT / "web/data/sector-rs-ranking.json"
RANKING_DIR = ROOT / "data/analytics/sector_rs_ranking/v01"
EXPORTER_PATH = ROOT / "scripts/export_sector_rs_ranking_web.py"
PAGE_PATH = ROOT / "web/sector-ranking.html"
SCRIPT_PATH = ROOT / "web/js/sector-ranking.js"
CSS_PATH = ROOT / "web/css/app.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _payload() -> dict:
    return json.loads(_read(PAYLOAD_PATH))


def _source_paths(payload: dict) -> tuple[Path, Path]:
    matches = []
    for meta_path in RANKING_DIR.glob("sector_rs_ranking_*_meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("as_of") == payload["as_of"]
            and meta.get("requested_as_of") == payload.get("requested_as_of")
        ):
            ranking_path = meta_path.with_name(meta_path.name.removesuffix("_meta.json") + ".parquet")
            if ranking_path.is_file():
                matches.append((ranking_path, meta_path))
    assert len(matches) == 1, f"expected one exact Sector RS artifact, found {len(matches)}"
    return matches[0]


def _load_exporter():
    spec = importlib.util.spec_from_file_location("sector_ranking_exporter_test", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_source(script: str, name: str) -> str:
    match = re.search(rf"^  function {re.escape(name)}\([^\n]*\) \{{[\s\S]*?^  \}}", script, re.M)
    assert match is not None, f"missing {name} function"
    return match.group(0)


def test_sector_ranking_page_and_all_ranking_tabs_are_connected():
    pages = ("etf.html", "market.html", "sector.html", "foreign.html")
    link = '<a class="ranking-tab" href="./sector-ranking.html">섹터 랭킹</a>'
    for filename in pages:
        html = _read(ROOT / "web" / filename)
        assert link in html
        assert html.count("<span class=\"ranking-tab\" aria-disabled=\"true\">") == 3

    html = _read(PAGE_PATH)
    active = '<a class="ranking-tab is-active" href="./sector-ranking.html" aria-current="page">섹터 랭킹</a>'
    assert active in html
    assert html.count('class="ranking-tab is-active"') == 1
    assert html.count('aria-current="page"') == 2  # primary menu and the single active ranking tab
    assert 'id="market-select"' not in html
    assert 'type="search"' not in html
    assert 'href="./css/app.css?v=web-sector-ranking-v1"' in html
    assert 'src="./js/sector-ranking.js?v=web-sector-ranking-v1"' in html


def test_page_exposes_five_horizons_with_two_weeks_as_default():
    html = _read(PAGE_PATH)
    assert 'id="cross-sector-horizon-controls"' in html
    assert html.count("data-horizon=") == 5
    assert 'data-horizon="2w" aria-pressed="true"' in html
    for horizon in ("1m", "3m", "6m", "12m"):
        assert f'data-horizon="{horizon}" aria-pressed="false"' in html
    assert 'id="cross-sector-as-of"' in html
    assert 'id="cross-sector-ranking-meta"' in html
    assert 'aria-label="섹터 랭킹"' in html


def test_existing_payload_has_canonical_sector_returns_and_authority_parity():
    payload = _payload()
    ranking_path, _meta_path = _source_paths(payload)
    ranking = pd.read_parquet(ranking_path).set_index("ticker")
    sectors = {sector["sector_key"]: sector for sector in payload["sectors"]}
    assert len(sectors) == len(payload["sectors"])
    assert len(payload["items"]) == len(ranking)

    for horizon in HORIZONS:
        field = f"sector_return_{horizon}"
        assert all(field in sector for sector in payload["sectors"])
        assert all(field in item for item in payload["items"])

    grouped: dict[str, list[dict]] = {}
    for item in payload["items"]:
        authority = ranking.loc[item["ticker"]]
        assert item["sector_key"] is None or item["sector_key"] == f'{item["market"]}:{item["sector_code"]}'
        for horizon in HORIZONS:
            field = f"sector_return_{horizon}"
            raw = authority[field]
            expected = None if pd.isna(raw) else float(raw)
            assert item[field] == expected
        if item["sector_key"] is not None:
            grouped.setdefault(item["sector_key"], []).append(item)

    assert set(grouped) == set(sectors)
    for sector_key, items in grouped.items():
        sector = sectors[sector_key]
        assert sector_key == f'{sector["market"]}:{sector["sector_code"]}'
        for horizon in HORIZONS:
            field = f"sector_return_{horizon}"
            finite = {
                float(item[field]) for item in items
                if item[field] is not None and math.isfinite(float(item[field]))
            }
            assert len(finite) <= 1
            assert sector[field] == (next(iter(finite)) if finite else None)

    by_name: dict[str, set[str]] = {}
    for sector in payload["sectors"]:
        by_name.setdefault(sector["sector_name"], set()).add(sector["sector_key"])
    assert any(len(keys) > 1 for keys in by_name.values())


def test_exporter_rejects_disagreeing_sector_benchmark_returns():
    exporter = _load_exporter()
    with pytest.raises(ValueError, match="sector benchmark return is not canonical"):
        exporter._canonical_sector_return(
            pd.DataFrame({"sector_return_2w": [0.05, 0.06, None]}), "2w"
        )
    assert exporter._canonical_sector_return(
        pd.DataFrame({"sector_return_2w": [None, 0.05]}), "2w"
    ) == 0.05
    assert exporter._canonical_sector_return(
        pd.DataFrame({"sector_return_2w": [None, None]}), "2w"
    ) is None


def test_browser_sort_excludes_null_and_uses_the_required_tie_breaks_and_breadth():
    script = _read(SCRIPT_PATH)
    sources = "\n".join(
        _function_source(script, name)
        for name in ("isFiniteNumber", "rankedSectors", "countBreadth")
    )
    sample = {
        "sectors": [
            {"sector_key": "KOSPI:01", "market": "KOSPI", "sector_code": "01", "sector_name": "제약", "sector_return_2w": 0.1},
            {"sector_key": "KOSDAQ:02", "market": "KOSDAQ", "sector_code": "02", "sector_name": "제약", "sector_return_2w": 0.1},
            {"sector_key": "KOSDAQ:01", "market": "KOSDAQ", "sector_code": "01", "sector_name": "제약", "sector_return_2w": 0.1},
            {"sector_key": "KOSPI:03", "market": "KOSPI", "sector_code": "03", "sector_name": "반도체", "sector_return_2w": 0.2},
            {"sector_key": "KOSDAQ:04", "market": "KOSDAQ", "sector_code": "04", "sector_name": "미분류", "sector_return_2w": None},
        ],
        "items": [
            {"sector_key": "KOSDAQ:01", "sector_stock_return_2w": 0.2},
            {"sector_key": "KOSDAQ:01", "sector_stock_return_2w": 0.0},
            {"sector_key": "KOSDAQ:01", "sector_stock_return_2w": -0.1},
            {"sector_key": "KOSDAQ:01", "sector_stock_return_2w": None},
            {"sector_key": "KOSDAQ:01", "sector_stock_return_2w": "Infinity"},
            {"sector_key": "KOSDAQ:02", "sector_stock_return_2w": 0.9},
        ],
    }
    encoded_sample = json.dumps(json.dumps(sample, ensure_ascii=False))
    node = f"""
{sources}
const sample = JSON.parse({encoded_sample});
const ordered = rankedSectors(sample.sectors, "2w").map((sector) => sector.sector_key);
if (JSON.stringify(ordered) !== JSON.stringify(["KOSPI:03", "KOSDAQ:01", "KOSDAQ:02", "KOSPI:01"])) process.exit(1);
const breadth = countBreadth(sample.items, "KOSDAQ:01", "2w");
if (breadth.positive !== 1 || breadth.resolved !== 3) process.exit(2);
"""
    result = subprocess.run(["node", "-e", node], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "rankedSectors(payload.sectors, activeHorizon)" in script
    assert "sector[`sector_return_${activeHorizon}`]" in script
    assert "positive: resolved.filter((value) => Number(value) > 0).length" in script


def test_cta_uses_encoded_canonical_key_and_page_uses_text_safe_dom_apis():
    script = _read(SCRIPT_PATH)
    assert 'link.href = `./sector.html?sector=${encodeURIComponent(sector.sector_key)}`;' in script
    assert 'link.setAttribute("aria-label"' in script
    assert "innerHTML" not in script
    assert "textContent = text" in script
    result = subprocess.run(
        ["node", "-e", 'if (encodeURIComponent("KOSDAQ:2066") !== "KOSDAQ%3A2066") process.exit(1);'],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_payload_is_shared_and_cross_sector_view_does_not_recompute_returns():
    script = _read(SCRIPT_PATH)
    sector_script = _read(ROOT / "web/js/sector.js")
    assert 'const PAYLOAD_URL = "./data/sector-rs-ranking.json";' in script
    assert 'const PAYLOAD_URL = "./data/sector-rs-ranking.json";' in sector_script
    assert 'const returnValue = sector[`sector_return_${activeHorizon}`];' in script
    assert 'const field = `sector_stock_return_${horizon}`;' in script
    assert "fetch(PAYLOAD_URL" in script
    assert "compute_relative_strength_features" not in script
    assert "sector_index" not in script


def test_css_contract_covers_desktop_mobile_focus_and_shared_dark_theme_tokens():
    css = _read(CSS_PATH)
    assert ".cross-sector-ranking-row" in css
    assert ".cross-sector-ranking-row:focus-within" in css
    assert "@media (max-width: 960px)" in css
    assert "@media (max-width: 560px)" in css
    assert ".cross-sector-ranking-link" in css
    assert '[data-theme="dark"]' in css
    assert "var(--market-up-red)" in css
    assert "var(--market-down-blue)" in css
    assert "min-height: 44px" in css
