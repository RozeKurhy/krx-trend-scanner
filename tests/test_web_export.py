"""Focused WEB-01 validation for the local health exporter and static shell."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = ROOT / "scripts/export_web_data.py"


@pytest.fixture(scope="session")
def exporter():
    spec = importlib.util.spec_from_file_location("export_web_data", EXPORTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def health(exporter):
    return exporter.build_health()


def test_exporter_writes_valid_compact_public_health_json(tmp_path, exporter, health):
    output_path = tmp_path / "data" / "health.json"
    exporter._write_checked(output_path, health)
    loaded = json.loads(output_path.read_text(encoding="utf-8"))

    assert loaded == health
    assert loaded["schema_version"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*Z", loaded["generated_at"])
    assert loaded["overall_status"] in exporter.VALID_STATUSES
    for section in ("market_data", "universe", "fundamentals", "stock_reports"):
        assert isinstance(loaded[section], dict)


def test_health_uses_actual_resolved_authority_values(health, exporter):
    requested_as_of, reference_market_date = exporter._load_as_of()
    resolved_tickers, _, _ = exporter._load_universe(requested_as_of)
    market_manifest = exporter._read_json(exporter.MARKET_AUTHORITY_MANIFEST_PATH)
    certified_through = str(market_manifest["certified_through"])[:10]

    assert health["market_data"]["latest_trading_date"] == certified_through
    assert health["market_data"]["latest_trading_date"] == reference_market_date
    assert health["universe"]["count"] == len(resolved_tickers)
    assert health["fundamentals"]["requested_as_of"] == requested_as_of
    fundamentals = health["fundamentals"]
    assert fundamentals["completed"] == fundamentals["output_integrity"]["valid_output_count"]
    assert fundamentals["completed"] + fundamentals["remaining"] == fundamentals["total"]
    assert fundamentals["percentage"] == round(
        fundamentals["completed"] / fundamentals["total"] * 100, 1
    )
    expected_status = exporter._fundamentals_status(
        completed=fundamentals["completed"],
        total=fundamentals["total"],
        integrity_ok=(
            fundamentals["output_integrity"]["invalid_output_count"] == 0
            and fundamentals["output_integrity"]["outside_universe_count"] == 0
            and fundamentals["output_integrity"]["duplicate_payload_count"] == 0
        ),
    )
    assert fundamentals["status"] == expected_status
    expected_overall = exporter._overall_status(
        {
            key: health[key]
            for key in ("market_data", "universe", "fundamentals", "stock_reports", "analysis", "backtest")
        }
    )
    assert health["overall_status"] == expected_overall


def test_date_key_drives_fundamentals_and_stock_report_paths(exporter, health):
    requested_as_of, _ = exporter._load_as_of()
    date_key = requested_as_of.replace("-", "")
    paths = exporter._production_paths(requested_as_of)
    summary_path = exporter._resolve_scanner_summary()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_as_of)
    assert summary_path.name.endswith(f"{date_key}_summary.json")
    assert paths["fundamentals_root"].name == date_key
    assert paths["fundamentals_tickers"] == paths["fundamentals_root"] / "tickers"
    assert paths["fundamentals_checkpoint"] == paths["fundamentals_root"] / "daily_quota_checkpoint.json"
    assert paths["stock_reports"].name == date_key
    assert health["fundamentals"]["source"]["production_directory"] == paths["fundamentals_root"].relative_to(exporter.ROOT).as_posix()
    assert health["stock_reports"]["artifact_source"]["path"] == paths["stock_reports"].relative_to(exporter.ROOT).as_posix()
    assert health["stock_reports"]["artifact_source"]["as_of"] == requested_as_of


def test_fundamentals_status_rule_is_invariant(exporter):
    assert exporter._fundamentals_status(completed=0, total=1, integrity_ok=False) == "CHECK_REQUIRED"
    assert exporter._fundamentals_status(completed=0, total=1, integrity_ok=True) == "UPDATING"
    assert exporter._fundamentals_status(completed=1, total=1, integrity_ok=True) == "NORMAL"


def test_overall_status_uses_declared_priority(exporter):
    priority = ["CHECK_REQUIRED", "UPDATING", "WAITING", "UNKNOWN", "NORMAL"]
    for index, expected in enumerate(priority):
        sections = {f"section_{n}": {"status": status} for n, status in enumerate(priority[index:])}
        assert exporter._overall_status(sections) == expected


def test_public_health_has_no_local_paths_or_secrets(health):
    serialized = json.dumps(health, ensure_ascii=False)
    for forbidden in ("/Users/", "/private/", ".env", "OPENDART_API_KEY", "crtfc_key", "api_key"):
        assert forbidden not in serialized
    assert "data/reference/krx_instrument_metadata.parquet" in serialized
    assert "/Users/june" not in serialized
    assert isinstance(health["fundamentals"]["source"]["production_directory"], str)


def test_static_frontend_uses_relative_assets_and_required_dom():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'href="./css/app.css"' in html
    assert 'src="./js/app.js"' in html
    assert 'const HEALTH_URL = "./data/health.json";' in js
    assert 'href="/css/app.css"' not in html
    assert 'src="/js/app.js"' not in html
    assert '"/data/health.json"' not in js
    assert 'if (typeof source === "string") return source;' in js
    assert 'id="theme-toggle"' in html
    assert 'id="theme-toggle" class="theme-toggle" type="button"' in html
    assert 'aria-label="어둡게 보기"' in html
    assert 'localStorage' in js
    assert 'krx-theme' in html and 'krx-theme' in js
    assert 'prefers-color-scheme: dark' in html and 'prefers-color-scheme: dark' in js
    assert 'matchMedia' in js
    assert "데이터 상태를 불러올 수 없습니다." in html
    assert 'data-status="CHECK_REQUIRED"' in html
    for element_id in (
        "overall-status",
        "market-date",
        "universe-count",
        "fundamentals-count",
        "fundamentals-progress",
        "readiness-list",
        "load-error",
    ):
        assert f'id="{element_id}"' in html
    assert "innerHTML" not in js
    assert "fetch(HEALTH_URL" in js
    assert "@media (max-width: 560px)" in css
    assert '[data-theme="dark"]' in css
    assert "color-scheme: dark" in css
    assert "--brand-red" in css and "--market-up-red" in css
    for old_label in (
        "SYSTEM OVERVIEW",
        "CURRENT STATE",
        "Downstream readiness",
        "Research workspace",
        "Read-only static view",
        "DATA LOAD ERROR",
        "JAVASCRIPT REQUIRED",
    ):
        assert old_label not in html
    nav = re.search(r"<nav class=\"primary-nav\".*?</nav>", html, flags=re.DOTALL)
    assert nav is not None
    nav_text = nav.group(0)
    labels = ["데이터 상태", "시장 랭킹", "종목 리포트", "전략 운용", "전략 설명"]
    assert [nav_text.index(label) for label in labels] == sorted(nav_text.index(label) for label in labels)
    assert "분석" not in nav_text
    assert "백테스트" not in nav_text


def test_theme_contract_supports_system_detection_manual_toggle_and_persistence():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'document.documentElement.dataset.theme = saved || system;' in html
    assert 'localStorage.setItem(THEME_STORAGE_KEY, next)' in js
    assert 'button.addEventListener("click"' in js
    assert 'const next = resolved === "dark" ? "light" : "dark";' in js
    assert 'const label = next === "dark" ? "어둡게 보기" : "밝게 보기";' in js
    assert 'aria-pressed' in js
    assert 'media.addEventListener("change", syncWithSystem)' in js
    assert 'media.addListener(syncWithSystem)' in js
    assert 'color-scheme: light' in css
    assert 'color-scheme: dark' in css
    assert "--primary-soft" in css
    assert "--focus-ring" in css


def test_pages_workflow_is_official_static_deploy_only():
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v4" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "npm" not in workflow.lower()
    assert "third-party" not in workflow.lower()
