from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/integrate_fundamentals_v1_f8.py"
SPEC = importlib.util.spec_from_file_location("integrate_fundamentals_v1_f8", SCRIPT_PATH)
assert SPEC and SPEC.loader
F8 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = F8
SPEC.loader.exec_module(F8)


AS_OF = "2026-09-04"


def _f5_ready(*, requested_as_of: str = AS_OF, **overrides):
    value = {
        "applicability": "APPLICABLE",
        "data_status": "PARTIAL",
        "reason": None,
        "requested_as_of": requested_as_of,
        "company_family": "NON_FINANCIAL",
        "currency": "KRW",
        "filter_status": "PASS",
        "filter_passed": True,
        "filter_reasons": [],
        "summary": {
            "latest_fy": "2025",
            "latest_quarter": "2026Q2",
            "latest_fy_revenue_krw": None,
            "latest_4q_avg_revenue_krw": None,
            "ttm_revenue_krw": None,
            "ttm_operating_income_krw": None,
            "ttm_net_income_krw": None,
            "ttm_operating_cash_flow_krw": None,
            "ttm_operating_margin_pct": None,
            "ttm_net_margin_pct": None,
            "ttm_operating_cash_flow_margin_pct": None,
            "ttm_roe_pct": None,
            "latest_debt_ratio_pct": None,
            "filter_status": "PASS",
            "filter_passed": True,
            "filter_reasons": [],
        },
        "quarterly": [],
        "annual": [],
        "diagnostics": [],
    }
    value.update(overrides)
    return value


def _fixture(tmp_path: Path, *, f7: dict | None = None, baseline_overrides: dict | None = None):
    report_dir = tmp_path / "reports" / "20260904"
    json_dir = report_dir / "json"
    fundamentals_dir = tmp_path / "fundamentals"
    json_dir.mkdir(parents=True)
    fundamentals_dir.mkdir(parents=True)
    baseline = {
        "ticker": "000001",
        "name": "테스트",
        "report_version": "0.4",
        "requested_as_of": AS_OF,
        "reference_market_date": AS_OF,
        "asset_type": "COMMON",
    }
    baseline.update(baseline_overrides or {})
    stem = "000001_test"
    (json_dir / f"{stem}.json").write_text(json.dumps(baseline), encoding="utf-8")
    (report_dir / f"{stem}.md").write_text("# 테스트 종목 리포트 v0.4\n", encoding="utf-8")
    if f7 is not None:
        (fundamentals_dir / "000001.json").write_text(json.dumps(f7), encoding="utf-8")
    return report_dir, fundamentals_dir


def _f7(*, asset_type: str = "COMMON", requested_as_of: str = AS_OF, f5_ready=None):
    return {
        "ticker": "000001",
        "requested_as_of": requested_as_of,
        "terminal_status": "PASS",
        "asset_type": asset_type,
        "f5_ready": _f5_ready(requested_as_of=requested_as_of) if f5_ready is None else f5_ready,
    }


def _current_integrated_record():
    json_path = sorted((ROOT / "artifacts/reporting/stock_reports/20260904/json").glob("*.json"))[0]
    markdown_path = json_path.parent.parent / f"{json_path.stem}.md"
    integrated = json.loads(json_path.read_text(encoding="utf-8"))
    f7_path = ROOT / "artifacts/fundamentals/production/20260904/tickers" / f"{integrated['ticker']}.json"
    f7 = json.loads(f7_path.read_text(encoding="utf-8"))
    bullet = F8.fundamentals_executive_bullet(F8._section_from_f5(f7["f5_ready"]))
    baseline = copy.deepcopy(integrated)
    baseline.pop("fundamentals", None)
    baseline["report_version"] = "0.4"
    if isinstance(baseline.get("technical_details"), dict):
        baseline["technical_details"]["report_version"] = "0.4"
    baseline["summary"]["bullet_points"].remove(bullet)
    baseline_markdown = F8._markdown_without_allowed_changes(
        markdown_path.read_text(encoding="utf-8"), bullet
    )
    return F8.IntegrationRecord(
        ticker=integrated["ticker"],
        stem=json_path.stem,
        baseline_json=baseline,
        baseline_markdown=baseline_markdown,
        f7_json=f7,
        fundamentals=F8._section_from_f5(f7["f5_ready"]),
    )


def test_current_target_discovers_exact_553_reports_and_f7_joins():
    report_dir = ROOT / "artifacts/reporting/stock_reports/20260904"
    fundamentals_dir = ROOT / "artifacts/fundamentals/production/20260904/tickers"
    report_paths = sorted((report_dir / "json").glob("*.json"))
    markdown_paths = sorted(report_dir.glob("*.md"))

    assert len(report_paths) == 553
    assert len(markdown_paths) == 553
    assert len({path.stem for path in report_paths}) == 553
    for path in report_paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        f7 = json.loads((fundamentals_dir / f"{report['ticker']}.json").read_text(encoding="utf-8"))
        assert report["report_version"] == "0.5"
        assert report["fundamentals"] == f7["f5_ready"]


def test_missing_f7_output_fails_closed(tmp_path):
    report_dir, fundamentals_dir = _fixture(tmp_path)

    with pytest.raises(F8.F8IntegrationError, match="missing F7 output"):
        F8.load_integration_records(report_dir, fundamentals_dir, expected_count=1)


def test_as_of_mismatch_fails_closed(tmp_path):
    report_dir, fundamentals_dir = _fixture(
        tmp_path,
        f7=_f7(requested_as_of="2026-09-03"),
    )

    with pytest.raises(F8.F8IntegrationError, match="F7 requested_as_of mismatch"):
        F8.load_integration_records(report_dir, fundamentals_dir, expected_count=1)


def test_identity_mismatch_fails_closed(tmp_path):
    report_dir, fundamentals_dir = _fixture(tmp_path, f7=_f7(asset_type="ETF"))

    with pytest.raises(F8.F8IntegrationError, match="asset_type identity mismatch"):
        F8.load_integration_records(report_dir, fundamentals_dir, expected_count=1)


def test_invalid_f5_ready_fails_closed(tmp_path):
    report_dir, fundamentals_dir = _fixture(
        tmp_path,
        f7=_f7(f5_ready={"requested_as_of": AS_OF, "data_status": "PARTIAL"}),
    )

    with pytest.raises(F8.F8IntegrationError, match="f5_ready missing fields"):
        F8.load_integration_records(report_dir, fundamentals_dir, expected_count=1)


def test_baseline_nonfundamental_drift_fails_closed():
    record = _current_integrated_record()
    integrated = F8._integrated_json(record)
    integrated["name"] = f"{integrated['name']} drift"
    markdown = F8._integrated_markdown(record)

    with pytest.raises(F8.F8IntegrationError, match="NON_FUNDAMENTALS_REPORT_DRIFT"):
        F8.validate_integrated_record(record, integrated, markdown)


def test_staging_write_does_not_replace_canonical_report():
    record = _current_integrated_record()
    canonical_path = ROOT / "artifacts/reporting/stock_reports/20260904/json" / f"{record.stem}.json"
    before = json.loads(canonical_path.read_text(encoding="utf-8"))
    staging_dir = ROOT / "artifacts/reporting/stock_reports/.f8-test-staging"
    if staging_dir.exists():
        raise AssertionError(f"unexpected pre-existing staging directory: {staging_dir}")

    try:
        F8._write_record(staging_dir, record)
        after = json.loads(canonical_path.read_text(encoding="utf-8"))
        assert after == before
        assert after["report_version"] == "0.5"
        assert "fundamentals" in after
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
