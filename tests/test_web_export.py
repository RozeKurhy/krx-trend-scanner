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


def test_health_uses_actual_current_authority_values(health):
    assert health["market_data"]["latest_trading_date"] == "2026-09-04"
    assert health["universe"]["count"] == 4407
    fundamentals = health["fundamentals"]
    assert fundamentals["completed"] == fundamentals["output_integrity"]["valid_output_count"]
    assert fundamentals["completed"] + fundamentals["remaining"] == fundamentals["total"]
    assert fundamentals["percentage"] == round(
        fundamentals["completed"] / fundamentals["total"] * 100, 1
    )
    assert fundamentals["status"] == "UPDATING"
    assert health["overall_status"] == "UPDATING"


def test_public_health_has_no_local_paths_or_secrets(health):
    serialized = json.dumps(health, ensure_ascii=False)
    for forbidden in ("/Users/", "/private/", ".env", "OPENDART_API_KEY", "crtfc_key", "api_key"):
        assert forbidden not in serialized
    assert "data/reference/krx_instrument_metadata.parquet" in serialized
    assert "/Users/june" not in serialized


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


def test_pages_workflow_is_official_static_deploy_only():
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v4" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "npm" not in workflow.lower()
    assert "third-party" not in workflow.lower()
