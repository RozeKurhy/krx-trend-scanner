from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft7Validator

from trend_scanner.fundamentals.fundamentals_filter import FundamentalsFilterResult, PASS
from trend_scanner.fundamentals.derived_metrics import DerivedMetricObservation, DerivedMetricsResult
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation, READY
from trend_scanner.reporting.fundamentals_report import (
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    PARTIAL,
    READY as REPORT_READY,
    build_fundamentals_section,
    fundamentals_executive_bullet,
)
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report


AS_OF = "2026-06-30"
ROOT = Path(__file__).resolve().parents[1]


def _f2_observation(metric: str, year: int, period: str, value, *, semantics: str | None = None):
    return PeriodizedFinancialObservation(
        ticker="TEST", corp_code="00000001", company_family="NON_FINANCIAL",
        fiscal_year=str(year), fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics=semantics or ("FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER"),
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric,
        value=value, currency="KRW", method="TEST", anchor_report_type="ANNUAL" if period == "FY" else "QUARTER",
        anchor_reprt_code="11011", anchor_rcept_no=f"{year}{period}{metric}", anchor_rcept_dt="2026-07-20",
        source_rcept_nos=(f"{year}{period}{metric}",), source_rcept_dts=("2026-07-20",),
        source_sha256s=("sha",), fs_div_used="CFS", pit_available_from="2026-07-20",
    )


def _f3_observation(metric: str, metric_type: str, year: int, period: str, value, *, ticker="TEST", requested_as_of=AS_OF):
    return DerivedMetricObservation(
        ticker, "00000001", "NON_FINANCIAL", str(year), period, metric, metric_type, value,
        requested_as_of=requested_as_of, period_end="2026-06-30",
    )


def _inputs():
    quarter_periods = [(2022, "Q3"), (2022, "Q4")]
    quarter_periods.extend((year, f"Q{quarter}") for year in range(2023, 2026) for quarter in range(1, 5))
    quarter_periods.extend(((2026, "Q1"), (2026, "Q2")))
    quarters = tuple(
        item
        for year, period in quarter_periods
        for metric, value in (("revenue", 20_000_000_000), ("operating_income", 2_000_000_000),
                              ("net_income", 1_500_000_000), ("operating_cash_flow", 2_500_000_000))
        for item in (_f2_observation(metric, year, period, value),)
    )
    annuals = tuple(
        item
        for year in range(2020, 2026)
        for metric, value in (("revenue", 80_000_000_000), ("operating_income", 8_000_000_000),
                              ("net_income", 6_000_000_000), ("equity", 100_000_000_000),
                              ("liabilities", 40_000_000_000))
        for item in (_f2_observation(metric, year, "FY", value),)
    )
    f2 = SimpleNamespace(
        ticker="TEST", corp_code="00000001", company_family="NON_FINANCIAL", requested_as_of=AS_OF,
        quarters=quarters, annuals=annuals,
        quarter_slots=tuple(SimpleNamespace(identity=f"{year}Q{period[-1]}", status=READY) for year, period in quarter_periods),
        annual_slots=tuple(SimpleNamespace(identity=str(year), status=READY) for year in range(2020, 2026)),
        latest_quarter="2026Q2", latest_fy="2025",
    )
    derived = []
    for year, period in quarter_periods:
        derived.extend((
            _f3_observation("revenue", "QUARTERLY_YOY", year, period, 5.0),
            _f3_observation("operating_income", "QUARTERLY_YOY", year, period, 12.0),
            _f3_observation("operating_income", "OPERATING_MARGIN", year, period, 10.0),
            _f3_observation("net_income", "NET_MARGIN", year, period, 7.5),
        ))
    for year in range(2020, 2026):
        derived.extend((
            _f3_observation("revenue", "ANNUAL_YOY", year, "FY", 6.0),
            _f3_observation("operating_income", "ANNUAL_YOY", year, "FY", 14.0),
            _f3_observation("operating_income", "OPERATING_MARGIN", year, "FY", 10.0),
            _f3_observation("net_income", "NET_MARGIN", year, "FY", 7.5),
            _f3_observation("net_income", "ANNUAL_ROE", year, "FY", 8.0),
            _f3_observation("liabilities", "DEBT_RATIO", year, "FY_END", 40.0),
        ))
    derived.extend((
        _f3_observation("revenue", "TTM", 2026, "Q2", 80_000_000_000),
        _f3_observation("operating_income", "TTM", 2026, "Q2", 8_000_000_000),
        _f3_observation("net_income", "TTM", 2026, "Q2", 6_000_000_000),
        _f3_observation("operating_cash_flow", "TTM", 2026, "Q2", 10_000_000_000),
        _f3_observation("operating_income", "TTM_OPERATING_MARGIN", 2026, "Q2", 10.0),
        _f3_observation("net_income", "TTM_NET_MARGIN", 2026, "Q2", 7.5),
        _f3_observation("operating_cash_flow", "TTM_OPERATING_CASH_FLOW_MARGIN", 2026, "Q2", 12.5),
        _f3_observation("net_income", "TTM_ROE", 2026, "Q2", 8.5),
        _f3_observation("liabilities", "DEBT_RATIO", 2026, "H1_END", 40.0),
    ))
    f3 = DerivedMetricsResult(derived)
    f4 = FundamentalsFilterResult(
        ticker="TEST", requested_as_of=AS_OF, company_family="NON_FINANCIAL", status=PASS, passed=True,
        latest_fy="2025", latest_quarter="2026Q2", annual_revenue=80_000_000_000,
        quarterly_avg_revenue=20_000_000_000, ttm_operating_income=8_000_000_000,
        ttm_net_income=6_000_000_000, thresholds={}, reasons=(), diagnostics=(),
    )
    return f2, f3, f4


def test_complete_adapter_is_ready_with_exact_12q_and_5fy_windows():
    f2, f3, f4 = _inputs()
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.applicability == "APPLICABLE"
    assert section.data_status == REPORT_READY
    assert len(section.quarterly) == 12
    assert len(section.annual) == 5
    assert section.quarterly[0].quarter == "2023Q3"
    assert section.quarterly[-1].quarter == "2026Q2"
    assert section.annual[0].fiscal_year == "2021"
    assert section.annual[-1].fiscal_year == "2025"
    assert section.summary.ttm_revenue_krw == 80_000_000_000
    assert section.summary.ttm_operating_margin_pct == 10.0
    assert section.summary.ttm_roe_pct == 8.5
    assert section.summary.latest_debt_ratio_pct == 40.0
    assert section.quarterly[0].operating_income_yoy_pct == 12.0
    assert section.annual[0].operating_income_yoy_pct == 14.0


def test_adapter_preserves_f4_status_and_reasons_without_recomputation():
    f2, f3, f4 = _inputs()
    f4 = FundamentalsFilterResult(**{**f4.__dict__, "status": "FILTERED_NET_LOSS", "passed": False, "reasons": ("FILTERED_ANNUAL_REVENUE", "FILTERED_NET_LOSS")})
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.filter_status == "FILTERED_NET_LOSS"
    assert section.filter_passed is False
    assert section.filter_reasons == ["FILTERED_ANNUAL_REVENUE", "FILTERED_NET_LOSS"]


def test_quarter_gap_keeps_identity_and_nulls_values_without_pull_up():
    f2, f3, f4 = _inputs()
    gap = next(item for item in f2.quarters if item.metric == "revenue" and item.fiscal_year == "2025" and item.fiscal_period == "Q2")
    f2.quarters = tuple(item for item in f2.quarters if item is not gap)
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    row = next(item for item in section.quarterly if item.quarter == "2025Q2")
    assert len(section.quarterly) == 12
    assert row.revenue_krw is None
    assert row.status == DATA_UNAVAILABLE
    assert "2026Q2" == section.quarterly[-1].quarter


def test_annual_gap_keeps_five_display_identities():
    f2, f3, f4 = _inputs()
    f2.annuals = tuple(item for item in f2.annuals if not (item.metric == "revenue" and item.fiscal_year == "2023"))
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    row = next(item for item in section.annual if item.fiscal_year == "2023")
    assert len(section.annual) == 5
    assert row.revenue_krw is None
    assert row.status == DATA_UNAVAILABLE


def test_missing_fundamentals_input_and_non_common_are_safe_defaults():
    missing = build_fundamentals_section(None, None, None, AS_OF, "COMMON")
    assert missing.data_status == DATA_UNAVAILABLE
    assert missing.reason == "FUNDAMENTALS_INPUT_NOT_PROVIDED"
    assert missing.summary.filter_status == DATA_UNAVAILABLE
    etf = build_fundamentals_section(None, None, None, AS_OF, "ETF")
    assert etf.applicability == "NOT_APPLICABLE"
    assert etf.data_status == NOT_APPLICABLE
    assert etf.summary.filter_passed is False


def test_financial_f4_not_applicable_is_preserved():
    f2, f3, f4 = _inputs()
    f4 = FundamentalsFilterResult(**{**f4.__dict__, "company_family": "FINANCIAL", "status": NOT_APPLICABLE, "passed": False})
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.applicability == NOT_APPLICABLE
    assert section.filter_status == NOT_APPLICABLE
    assert section.filter_passed is False


def test_summary_uses_target_endpoint_when_other_ticker_has_newer_metrics():
    f2, f3, f4 = _inputs()
    other = _f3_observation("revenue", "TTM", 2026, "Q3", 999, ticker="OTHER", requested_as_of="2027-01-01")
    f3.observations = f3.observations + (other,)
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.summary.ttm_revenue_krw == 80_000_000_000
    assert section.summary.latest_quarter == "2026Q2"


def test_executive_bullet_is_additive_context_only():
    f2, f3, f4 = _inputs()
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    bullet = fundamentals_executive_bullet(section)
    assert bullet is not None
    assert "Filter PASS" in bullet
    assert "800.0억원" in bullet


def test_as_of_mismatch_fails_closed_before_mixing_f2_f3_f4():
    f2, f3, f4 = _inputs()
    f3.observations = f3.observations + (
        _f3_observation("revenue", "TTM", 2026, "Q2", 81_000_000_000, requested_as_of="2026-03-31"),
    )
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.applicability == "APPLICABLE"
    assert section.data_status == DATA_UNAVAILABLE
    assert section.reason == "AS_OF_MISMATCH"
    assert section.filter_status == DATA_UNAVAILABLE
    assert section.filter_passed is False
    assert section.summary.filter_status == DATA_UNAVAILABLE
    mismatch = next(item for item in section.diagnostics if item["type"] == "AS_OF_MISMATCH")
    assert mismatch["f2_requested_as_of"] == AS_OF
    assert mismatch["f4_requested_as_of"] == AS_OF
    assert set(mismatch["f3_requested_as_of_values"]) == {AS_OF, "2026-03-31"}


def test_ttm_operating_income_and_net_income_use_f3_authority():
    f2, f3, f4 = _inputs()
    f4 = FundamentalsFilterResult(**{**f4.__dict__, "ttm_operating_income": 123, "ttm_net_income": 456})
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    assert section.summary.ttm_operating_income_krw == 8_000_000_000
    assert section.summary.ttm_net_income_krw == 6_000_000_000


def test_v05_generator_explicit_none_is_safe_and_schema_valid():
    report, _, _ = generate_stock_report(
        ticker="001540", as_of="2026-08-14", repo_root=ROOT,
        save_artifacts=False, fundamentals_section=None,
    )
    payload = report.to_dict()
    assert report.report_version == "0.5"
    assert payload["fundamentals"]["data_status"] == DATA_UNAVAILABLE
    assert payload["fundamentals"]["reason"] == "FUNDAMENTALS_INPUT_NOT_PROVIDED"
    schema = json.loads((ROOT / "docs/reporting/stock_report/schema_v05.json").read_text(encoding="utf-8"))
    assert list(Draft7Validator(schema).iter_errors(payload)) == []
    markdown = render_markdown_report(report)
    assert "## 1.5. 펀더멘털 (Fundamentals)" in markdown
    assert markdown.count("## 1.5. 펀더멘털 (Fundamentals)") == 1
    assert "Fundamentals Filter" in markdown
    assert "최근 12개 분기" in markdown
    assert "최근 5개년" in markdown
    assert markdown.index("## 1. 현재 기술적 국면") < markdown.index("## 1.5. 펀더멘털") < markdown.index("## 2. 패스트 코어")

    legacy, _, _ = generate_stock_report(
        ticker="001540", as_of="2026-08-14", repo_root=ROOT,
        save_artifacts=False,
    )
    for field in (
        "current_snapshot", "pattern_a_fast", "a_fast_core", "foreign_flow",
        "relative_strength", "sector_relative_strength", "trading_value_flow",
    ):
        assert getattr(legacy, field) == getattr(report, field)


def test_v05_generator_keeps_injected_section_identity():
    f2, f3, f4 = _inputs()
    section = build_fundamentals_section(f2, f3, f4, AS_OF, "COMMON")
    report, _, _ = generate_stock_report(
        ticker="001540", as_of="2026-08-14", repo_root=ROOT,
        save_artifacts=False, fundamentals_section=section,
    )
    assert report.report_version == "0.5"
    assert report.fundamentals is section
    assert "Filter PASS" in report.summary.bullet_points[1]
