from __future__ import annotations

from trend_scanner.fundamentals.derived_metrics import (
    DATA_UNAVAILABLE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
    derive_metrics,
)
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import PeriodizationResult, PeriodizedFinancialObservation


def _obs(metric: str, year: str, period: str, value, *, status: str = "READY", anchor: str | None = None,
         family: str = CompanyFamily.NON_FINANCIAL.value):
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    no = anchor or f"{year}-{period}"
    return PeriodizedFinancialObservation(
        ticker="TEST", corp_code="00000001", company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="STANDALONE_QUARTER" if period != "FY" else "CUMULATIVE_YTD",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric, value=value,
        currency="KRW", method="DIRECT_ONLY", anchor_report_type=REPORT_TYPE_BY_CODE[code],
        anchor_reprt_code=code, anchor_rcept_no=no, anchor_rcept_dt=f"{year}-12-31",
        source_rcept_nos=(no,), source_rcept_dts=(f"{year}-12-31",), source_sha256s=(f"sha-{no}",),
        resolution_status=status,
    )


def _series():
    rows = []
    values = {
        "revenue": {"2023": (100, 110, 120, 130, 460), "2024": (120, 132, 144, 156, 552)},
        "operating_income": {"2023": (10, 11, 12, 13, 46), "2024": (12, 14, 16, 18, 60)},
        "net_income": {"2023": (-10, 11, 12, 13, 26), "2024": (5, 14, 16, 18, 53)},
        "operating_cash_flow": {"2023": (20, 21, 22, 23, 86), "2024": (24, 28, 32, 36, 120)},
    }
    for metric, years in values.items():
        for year, amounts in years.items():
            for period, value in zip(("Q1", "Q2", "Q3", "Q4", "FY"), amounts):
                rows.append(_obs(metric, year, period, value))
    return rows


def test_quarterly_and_annual_yoy_are_calculated_from_canonical_observations():
    result = derive_metrics(PeriodizationResult(tuple(_series())))
    quarterly = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    annual = result.get("revenue", "ANNUAL_YOY", "2024", "FY")
    assert quarterly is not None and quarterly.value == 20
    assert annual is not None and annual.value == 20
    assert quarterly.source_rcept_nos == ("2024-Q1", "2023-Q1")


def test_ttm_and_ttm_yoy_use_four_adjacent_quarters():
    result = DerivedMetricsEngine().derive(_series())
    ttm = result.get("revenue", "TTM", "2024", "Q4")
    yoy = result.get("revenue", "TTM_YOY", "2024", "Q4")
    assert ttm is not None and ttm.value == 552
    assert yoy is not None and yoy.value == 20
    assert ttm.source_rcept_nos == ("2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4")


def test_growth_aliases_margins_and_ocf_metrics_are_emitted():
    result = derive_metrics(_series())
    assert result.get("revenue", "REVENUE_GROWTH", "2024", "Q1").value == 20
    assert result.get("operating_income", "OPERATING_MARGIN", "2024", "Q1").value == 10
    assert result.get("net_income", "NET_MARGIN", "2024", "Q1").value == 5 / 120 * 100
    assert result.get("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", "2024", "Q1").value == 20
    assert result.get("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", "2024", "Q2").value == "IMPROVING"
    expansion = result.get("operating_income", "MARGIN_EXPANSION_TREND", "2024", "Q1")
    assert expansion is not None and expansion.value == 0
    assert expansion.metadata["classification"] == "FLAT"


def test_transitions_consecutive_growth_and_acceleration_are_explicit():
    result = derive_metrics(_series())
    transition = result.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1")
    consecutive = result.get("revenue", "CONSECUTIVE_YOY_GROWTH", "2024", "Q4")
    acceleration = result.get("revenue", "YOY_GROWTH_ACCELERATION", "2024", "Q2")
    assert transition.value == "LOSS_TO_PROFIT"
    assert consecutive.value == 4
    assert acceleration.value == 0


def test_unavailable_and_zero_prior_values_fail_closed_without_zero_imputation():
    rows = [_obs("revenue", "2023", "Q1", 0), _obs("revenue", "2024", "Q1", 100),
            _obs("operating_income", "2024", "Q1", 10, status="PERIOD_AMBIGUOUS")]
    result = derive_metrics(rows)
    revenue_yoy = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    op_margin = result.get("operating_income", "OPERATING_MARGIN", "2024", "Q1")
    assert revenue_yoy.resolution_status == UNDEFINED_BASE
    assert revenue_yoy.reason == "NON_POSITIVE_OR_SIGN_TRANSITION_BASE"
    assert op_margin.resolution_status == "INPUT_NOT_READY"
    assert op_margin.value is None


def test_financial_non_applicable_revenue_does_not_create_margin_or_api_dependency():
    row = _obs("net_income", "2024", "Q1", 10, family=CompanyFamily.FINANCIAL.value)
    result = derive_metrics([row])
    margin = result.get("net_income", "NET_MARGIN", "2024", "Q1")
    assert margin is not None and margin.resolution_status == "NOT_APPLICABLE"
    assert not any(item.metric == "revenue" for item in result)
