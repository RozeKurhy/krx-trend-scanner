from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "cb56749f9f2e98dd67330e323c063451a1a6e694"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904/json"
WEB_DIR = ROOT / "web/data/stocks"
F7_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"


def _git_json(relative: str) -> dict:
    return json.loads(subprocess.check_output(["git", "show", f"{BASELINE}:{relative}"], cwd=ROOT, text=True))


def _without_fundamentals(value: dict) -> dict:
    result = copy.deepcopy(value)
    result.pop("fundamentals", None)
    summary = result.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("bullet_points"), list):
        summary["bullet_points"] = [
            item for item in summary["bullet_points"]
            if not str(item).startswith("펀더멘털:")
        ]
    return result


def test_all_source_reports_preserve_baseline_non_fundamentals_and_f7_fundamentals():
    paths = sorted(REPORT_DIR.glob("*.json"))
    assert len(paths) == 553
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        current = json.loads(path.read_text(encoding="utf-8"))
        baseline = _git_json(relative)
        ticker = current["ticker"]
        f7 = json.loads((F7_DIR / f"{ticker}.json").read_text(encoding="utf-8"))
        assert _without_fundamentals(current) == _without_fundamentals(baseline), ticker
        assert current["fundamentals"] == f7["f5_ready"], ticker


def test_all_web_reports_preserve_baseline_non_fundamentals():
    paths = sorted(WEB_DIR.glob("*.json"))
    assert len(paths) == 553
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        current = json.loads(path.read_text(encoding="utf-8"))
        baseline = _git_json(relative)
        assert _without_fundamentals(current) == _without_fundamentals(baseline), path.name
        f7 = json.loads((F7_DIR / f"{path.stem}.json").read_text(encoding="utf-8"))
        assert current["fundamentals"]["status"] == f7["f5_ready"]["data_status"]


def test_nhn_and_coway_preserve_baseline_operational_values():
    for ticker, expected in {
        "181710": {
            "report_status": "READY",
            "action": "WAIT",
            "strategy_state": "WAIT",
            "position": "FLAT",
            "trading_value": 230.08,
            "pattern_score": 0.0,
        },
        "021240": {
            "report_status": "READY",
            "action": "HOLD",
            "strategy_state": "HOLD_PRE_PROGRESSED",
            "position": "OPEN",
            "trading_value": 156.62,
            "pattern_score": 96.33,
        },
    }.items():
        path = next(REPORT_DIR.glob(f"{ticker}_*.json"))
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["header"]["effective_as_of"] == "2026-09-04"
        assert report["header"]["report_status"] == expected["report_status"]
        assert report["current_snapshot"]["avg_trading_value_20d_eok"] == expected["trading_value"]
        assert report["current_snapshot"]["pattern_a_score"] == expected["pattern_score"]
        assert report["current_snapshot"]["is_investable"] is True
        assert report["a_fast_core"]["action"] == expected["action"]
        assert report["a_fast_core"]["strategy_state"] == expected["strategy_state"]
        assert report["a_fast_core"]["canonical_position"] == expected["position"]
        assert report["fundamentals"]["data_status"] == "READY"
        assert report["fundamentals"]["filter_status"] == "PASS"
        assert len(report["fundamentals"]["quarterly"]) == 12
        assert len(report["fundamentals"]["annual"]) == 5


def test_v03_web_fundamentals_layout_and_formatting_contract():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert html.count("web-02d-window-8") == 2
    assert "fundamentals-summary-grid" not in html
    assert html.index('<div class="report-card-row">') < html.index(
        '<div class="report-card-row report-card-row--secondary">'
    )
    assert "fundamentals-detail-meta" not in html
    assert 'id="fundamentals-detail-heading">펀더멘탈</h3>' in html
    assert "Fundamentals 상세" not in html
    assert "fundamentals-unit-note" in html
    assert 'header: "TTM"' in js
    assert '"매출 YoY": "—"' in js
    assert '"영업이익 YoY": "—"' in js
    format_start = js.index("function formatFundamentalKrw")
    format_end = js.index("function formatFundamentalPercent", format_start)
    format_body = js[format_start:format_end]
    assert "천만" in format_body
    assert "억원" not in format_body
    assert 'const sign = number < 0 ? "-" : ""' in format_body
    assert ".fundamentals-table th { font-size: 10px; text-align: center; }" in css
    assert ".fundamentals-table td { text-align: right; }" in css
