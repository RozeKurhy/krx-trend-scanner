from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v07_fundamentals_negative_values_use_red_without_semantic_bold():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    helper_start = js.index("function fundamentalCell")
    helper_end = js.index("function fundamentalLossCell", helper_start)
    helper = js[helper_start:helper_end]

    assert "Number(value) < 0" in helper
    assert '(isNegative ? "fundamental-loss" : "")' in helper
    assert 'negativeClass: isLoss ? "fundamental-loss" : ""' in js
    assert 'negativeClass: isNegative ? "fundamental-loss" : ""' in js
    assert "fundamentalCell(row.revenue_krw, formatFundamentalTableKrw)" in js
    assert "fundamentalCell(row.operating_cash_flow_krw, formatFundamentalTableKrw)" in js
    assert "fundamentalCell(row.roe_pct, formatFundamentalPercent)" in js
    assert "fundamentalCell(row.debt_ratio_pct, formatFundamentalPercent)" in js
    assert 'status === "TURNED_TO_PROFIT" ? "fundamental-profit-transition"' in js

    loss_rule = css[css.index(".fundamental-loss"):css.index(".fundamental-profit-transition")]
    transition_rule = css[css.index(".fundamental-profit-transition"):css.index(".fundamentals-detail-panel")]
    assert "var(--market-up-red)" in loss_rule
    assert "var(--market-down-blue)" in transition_rule
    assert "font-weight" not in loss_rule
    assert "font-weight" not in transition_rule


def test_v07_fundamentals_trend_markup_and_data_contract():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    assert 'src="./js/report.js?v=web-02d-window-10"' in html
    assert 'id="fundamentals-trend"' in html
    assert 'id="fundamentals-trend-heading">실적 추세</h4>' in html
    assert 'id="fundamentals-trend-quarterly"' in html
    assert 'id="fundamentals-trend-annual"' in html
    assert 'data-mode="quarterly"' in html
    assert 'aria-pressed="true"' in html
    assert 'data-mode="annual"' in html
    assert 'aria-pressed="false"' in html

    trend_start = js.index("function renderFundamentalBarChart")
    trend_end = js.index("function setFundamentalTrendButtons", trend_start)
    trend = js[trend_start:trend_end]
    render_start = js.index("function renderFundamentalTrend")
    render_end = js.index("function setFundamentalTrendMode", render_start)
    render = js[render_start:render_end]

    assert 'id: `fundamental-${metricKey.replace("_krw", "")}-chart`' in trend
    assert 'role: "img"' in trend
    assert '"aria-label": `${modeLabel} ${titleText} 실적 추세`' in trend
    assert 'class: "fundamental-chart-zero-line"' in trend
    assert 'metricKey === "operating_income" && numericValue < 0 ? "fundamental-chart-bar-negative"' in trend
    assert 'value == null || value === "" || !Number.isFinite(Number(value))' in trend
    assert 'textContent = "—"' in trend
    assert '<title>' not in trend
    assert 'fundamentalTrendMode === "annual" ? "fiscal_year" : "quarter"' in render
    assert 'fundamentalTrendMode === "annual" ? 5 : 12' in render
    assert '[[' in render and '["revenue_krw", "매출"]' in render and '["operating_income_krw", "영업이익"]' in render
    assert "fundamentals.summary" not in render
    assert "ttm" not in render.lower()
    assert "|| 0" not in trend
    assert "fundamental-chart-bar-negative" in css
    assert "fundamental-chart-zero-line" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css[css.index(".fundamentals-trend-charts"):css.index(".fundamentals-chart-card")]
    assert ".fundamentals-trend-charts { grid-template-columns: 1fr; }" in css
    assert ".fundamental-chart-axis-label-secondary { display: none; }" in css
