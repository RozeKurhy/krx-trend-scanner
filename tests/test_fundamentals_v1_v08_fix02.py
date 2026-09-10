from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08_fix02"


def _rows():
    with (OUTPUT / "restated_comparative_26_cells.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_fix02_closes_the_fixed_26_cell_population():
    rows = _rows()
    summary = json.loads((OUTPUT / "validation_summary.json").read_text(encoding="utf-8"))

    assert len(rows) == summary["cell_count"] == 26
    assert summary["status_counts"] == {
        "EXTERNAL_SOURCE_STALE": 15,
        "PRODUCTION_CORRECTED": 11,
    }
    assert summary["mismatch_count"] == 0
    assert summary["wrong_sign_count"] == 0
    assert summary["source_missing_count"] == 0
    assert summary["source_ambiguous_count"] == 0
    assert summary["affected_ticker_count"] == 4
    assert summary["annual_affected_count"] == 7
    assert summary["quarterly_affected_count"] == 4


def test_fix02_reproduction_cases_and_pit_provenance_are_recorded():
    rows = {(row["ticker"], row["period"], row["metric"]): row for row in _rows()}

    kakao = rows[("035720", "2024FY", "operating_income")]
    assert kakao["production_after"] == "495277757353"
    assert kakao["selected_authoritative_rcept"] == "20260318001423"

    hanwha = rows[("272210", "2023FY", "operating_income")]
    assert hanwha["production_after"] == "122575141004"
    assert hanwha["selected_authoritative_rcept"] == "20260513000644"

    chabio = rows[("085660", "2024FY", "net_income")]
    assert chabio["production_after"] == "-11259855670"
    assert chabio["selected_authoritative_rcept"] == "20260609000370"

    for row in _rows():
        assert row["old_production_rcept"]
        assert row["selected_authoritative_rcept"]
        assert "latest eligible" in row["reason"] or "NO_ELIGIBLE" not in row["reason"]


def test_fix02_keeps_raw_flow_and_uses_the_new_chart_contract():
    payload = json.loads((ROOT / "web/data/stocks/004000.json").read_text(encoding="utf-8"))
    html = (ROOT / "web/report.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")

    assert payload["flow"]["net_buy_value_10d_krw"] == 23829500.0
    assert payload["external_links"] == {
        "naver_finance": "https://finance.naver.com/item/main.naver?code=004000",
        "naver_chart": "https://stock.naver.com/fchart/domestic/stock/004000",
    }
    assert "Npay 증권" in html
    assert "차트</a>" in html
    assert "전자공시</a>" in html
    assert "web-02d-window-10" in html
    assert "Math.floor(absolute / 1e7)" in js
    assert "return `${sign}${formatNumber(absolute)}원`;" not in js
    assert "naver_chart" in js and "toss_chart" not in js


def test_fix02_amount_boundaries_are_integer_safe():
    js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    start = js.index("function formatKrwAsEok")
    end = js.index("function formatKrwCompact", start)
    helper = js[start:end]

    assert "const truncatedTenths = Math.floor(absolute / 1e7);" in helper
    assert "if (absolute === 0) return withUnit ? \"0억\" : \"0\";" in helper
    assert "if (absolute >= 1e8) return `${sign}${formatNumber(absolute / 1e8)}${withUnit ? \"억\" : \"\"}`;" in helper
    assert "formatKrwAsEok(value, { signed: true })" in js
