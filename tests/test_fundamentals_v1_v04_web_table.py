from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _fundamentals_render_body():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    start = js.index("function renderFundamentalsDetail")
    end = js.index("function renderPatternDetail", start)
    return js[start:end]


def test_v04_web_heading_reason_and_cache_contract():
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")

    assert html.count("web-02d-window-8") == 2
    assert 'id="fundamentals-detail-heading">펀더멘탈</h3>' in html
    assert 'id="fundamentals-detail-meta"' not in html
    assert "Fundamentals 상세" not in html
    assert 'id="fundamentals-detail-reason"' in html
    assert 'id="fundamentals-unit-note"' in html
    assert 'return "";' in js[js.index("function fundamentalDetail"):js.index("function validateIndex")]


def test_v04_web_financial_loss_color_is_selective():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    body = _fundamentals_render_body()

    assert ".fundamental-loss" in css
    assert "color: var(--market-up-red)" in css
    loss_start = js.index("function fundamentalLossCell")
    loss_end = js.index("function fundamentalYoyCell", loss_start)
    loss_body = js[loss_start:loss_end]
    assert "Number(value) < 0" in loss_body
    assert 'negativeClass: isLoss ? "fundamental-loss" : ""' in loss_body
    yoy_start = js.index("function fundamentalYoyPercentCell")
    yoy_end = js.index("function fundamentalYoyCell", yoy_start)
    yoy_body = js[yoy_start:yoy_end]
    assert "Number(value) < 0" in yoy_body
    assert 'negativeClass: isNegative ? "fundamental-loss" : ""' in yoy_body
    assert "fundamentalLossCell(row.operating_income_krw" in body
    assert "fundamentalLossCell(row.net_income_krw" in body
    assert "fundamentalLossCell(row.operating_margin_pct" in body
    assert "fundamentalLossCell(row.net_margin_pct" in body
    assert '"매출 YoY", (row) => fundamentalYoyPercentCell(row.revenue_yoy_pct)' in body
    assert '"영업현금흐름", (row) => fundamentalCell(row.operating_cash_flow_krw' in body
    assert '"TURNED_TO_LOSS", "LOSS_CONTINUED"' in js
    transition_start = js.index("function fundamentalYoyCell")
    transition_end = js.index("function sortedFundamentalRows")
    transition_body = js[transition_start:transition_end]
    assert 'status === "TURNED_TO_PROFIT"' in transition_body
    assert '"fundamental-profit-transition"' in transition_body
    assert ".fundamental-profit-transition" in css
    assert "var(--market-down-blue)" in css[css.index(".fundamental-profit-transition"):css.index(".fundamental-profit-transition") + 180]


def test_v04_web_table_structure_and_period_classes():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    body = _fundamentals_render_body()

    quarter_start = body.index('"최근 12개 분기"')
    quarter_end = body.index('const annual =', quarter_start)
    annual_start = quarter_end
    annual_end = body.index('panel.hidden = false;', annual_start)
    quarter = body[quarter_start:quarter_end]
    annual = body[annual_start:annual_end]

    assert '"영업현금흐름"' in quarter
    assert '"영업현금흐름"' not in annual
    assert 'header: "TTM"' in annual
    assert 'className: "fundamental-ttm"' in annual
    assert '"영업현금흐름"' not in annual[annual.index('valueForRow:'):]
    assert '"매출 YoY": "—"' in annual
    assert '"영업이익 YoY": "—"' in annual
    assert quarter.index('["매출"') < quarter.index('["영업이익"') < quarter.index('["영업이익률"') < quarter.index('["순이익"')
    assert quarter.index('["순이익률"') < quarter.index('["영업현금흐름"') < quarter.index('["매출 YoY"') < quarter.index('["영업이익 YoY"')
    assert annual.index('["매출"') < annual.index('["영업이익"') < annual.index('["영업이익률"') < annual.index('["순이익"')
    assert annual.index('["순이익률"') < annual.index('["ROE"') < annual.index('["부채비율"') < annual.index('["매출 YoY"') < annual.index('["영업이익 YoY"')
    assert "fundamental-quarter-q${match[1]}" in js
    assert "fundamental-year-boundary" in js
    assert "fundamental-ttm" in css
    for quarter_class in ("fundamental-quarter-q1", "fundamental-quarter-q2", "fundamental-quarter-q3", "fundamental-quarter-q4"):
        assert quarter_class in css
    assert ".fundamentals-table th, .fundamentals-table td { border-right" in css
    assert "position: sticky" in css
    assert ".fundamentals-table th { font-size: 10px; text-align: center; }" in css
    assert ".fundamentals-table td { text-align: right; }" in css


def test_v04_web_amount_format_preserves_ascii_negative_and_small_unit():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    start = js.index("function formatFundamentalKrw")
    end = js.index("function formatFundamentalPercent", start)
    body = js[start:end]

    assert "억원" not in body
    assert "천만" in body
    assert 'const sign = number < 0 ? "-" : ""' in body
    table_start = js.index("function formatFundamentalTableKrw")
    table_end = js.index("function formatFundamentalPercent", table_start)
    table_body = js[table_start:table_end]
    assert "formatNumber(absolute / 1e8)" in table_body
    assert "formatNumber(absolute / 1e7)}천만" in table_body
