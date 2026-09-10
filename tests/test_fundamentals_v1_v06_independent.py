from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_independent_validation_v06"


def _csv(name: str) -> list[dict[str, str]]:
    with (OUTPUT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v06_independent_artifacts_have_required_dimensions_and_computed_statuses():
    regression = _csv("independent_regression_13_tickers.csv")
    blind = _csv("independent_blind_10_tickers.csv")
    summary = json.loads((OUTPUT / "validation_summary.json").read_text(encoding="utf-8"))

    assert len(regression) == 13 * 8 * 3 == 312
    assert len(blind) == 10 * 8 * 3 == 240
    assert Counter(row["comparison_status"] for row in regression) == Counter(summary["regression"]["status_counts"])
    assert Counter(row["comparison_status"] for row in blind) == Counter(summary["blind"]["status_counts"])
    assert summary["regression"]["wrong_sign_count"] == 0
    assert summary["regression"]["mismatch_count"] == 0
    assert summary["blind"]["wrong_sign_count"] == 0
    assert summary["blind"]["mismatch_count"] == 0
    assert summary["method"]["production_periodizer_imported"] is False
    assert summary["method"]["production_metric_resolver_imported"] is False
    assert summary["method"]["blind_pool_rule"].endswith("no completeness/value filter")


def test_v06_expected_side_is_raw_xbrl_evidence_not_a_copy_of_actual():
    rows = _csv("independent_regression_13_tickers.csv")
    assert all(row["independent_source_type"].startswith("RAW_XBRL_") for row in rows)
    assert all(row["independent_source_rcept_no"] for row in rows)
    assert all(row["independent_account_id"] for row in rows)
    assert all(row["independent_context"] for row in rows)
    assert all(row["independent_raw_value"] for row in rows)
    assert all(row["independent_value_krw"] for row in rows)
    assert all(row["actual_independent_difference_krw"] == "0" for row in rows)
    assert all(row["metric_semantics"] == "CONSOLIDATED_TOTAL_PROFIT_LOSS" for row in rows if row["metric"] == "net_income")
    assert any(row["direct_value_krw"] and row["derived_value_krw"] for row in rows if row["period"].endswith(("Q1", "Q2", "Q3", "Q4")))


def test_v06_blind_selection_is_fixed_and_not_completeness_filtered():
    rows = _csv("independent_blind_10_tickers.csv")
    summary = json.loads((OUTPUT / "validation_summary.json").read_text(encoding="utf-8"))
    selected = sorted({row["ticker"] for row in rows})
    assert selected == sorted(summary["blind"]["tickers"])
    assert summary["method"]["blind_seed"] == "20260910_03"
    assert summary["blind_pool_count"] >= 10
    assert all(row["independent_value_krw"] for row in rows)


def test_v06_web_polish_contract():
    report_html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    index_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    report_js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    app_js = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert report_html.count("web-02d-window-10") == 2
    assert "function formatFundamentalTableKrw" in report_js
    assert "formatKrwAsEok" in report_js
    quarter = report_js[report_js.index('renderFundamentalPeriodTable("최근 12개 분기"'):report_js.index('const annual =', report_js.index('renderFundamentalPeriodTable("최근 12개 분기"'))]
    annual = report_js[report_js.index('const annual ='):report_js.index('panel.hidden = false;', report_js.index('const annual ='))]
    assert quarter.index('["매출"') < quarter.index('["영업이익"') < quarter.index('["영업이익률"') < quarter.index('["순이익"') < quarter.index('["순이익률"') < quarter.index('["영업현금흐름"') < quarter.index('["매출 YoY"') < quarter.index('["영업이익 YoY"')
    assert annual.index('["매출"') < annual.index('["영업이익"') < annual.index('["영업이익률"') < annual.index('["순이익"') < annual.index('["순이익률"') < annual.index('["ROE"') < annual.index('["부채비율"') < annual.index('["매출 YoY"') < annual.index('["영업이익 YoY"')
    assert ".fundamental-loss { color: var(--market-up-red)" in css
    assert "var(--brand-red)" not in css[css.index(".fundamental-loss"):css.index(".fundamental-loss") + 120]
    assert "var(--market-down-blue)" in css
    assert 'setText("fundamentals-detail", "")' in app_js
    assert 'setText("market-detail", `기준일 ${formatDate(market.latest_trading_date)}`)' in app_js
    assert 'setText("universe-detail", `기준일 ${formatDate(universe.snapshot_date)}`)' in app_js
    assert 'setText("reports-detail", "")' in app_js
    assert "개 남음" not in app_js
    assert "Stock Report v0.5 and Web Fundamentals artifacts are complete." not in app_js
    assert 'id="market-status"' in index_html
    assert 'id="universe-status"' in index_html
    assert 'id="fundamentals-status"' in index_html
