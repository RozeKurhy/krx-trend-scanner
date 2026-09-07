from __future__ import annotations

from types import SimpleNamespace

import pytest

from trend_scanner.fundamentals.derived_metrics import (
    CURRENCY_MISMATCH,
    DATA_UNAVAILABLE,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    PERIOD_AMBIGUOUS,
    DerivedMetricObservation,
    DerivedMetricsResult,
)
from trend_scanner.fundamentals.fundamentals_filter import (
    FILTERED_ANNUAL_REVENUE,
    FILTERED_NET_LOSS,
    FILTERED_OPERATING_LOSS,
    FILTERED_QUARTERLY_REVENUE,
    PASS,
    FundamentalsFilter,
    FundamentalsFilterConfig,
)
from trend_scanner.fundamentals.period_models import BASIS_MISMATCH, PeriodizedFinancialObservation, READY


AS_OF = "2026-06-30"


def _period_obs(
    metric: str,
    year: int,
    period: str,
    value,
    *,
    status: str = READY,
    reason: str | None = None,
    receipt: str | None = "2026-07-20",
    basis: str = "CFS",
    currency: str = "KRW",
) -> PeriodizedFinancialObservation:
    semantics = "FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER"
    anchor = f"{year}{period}{metric}"
    return PeriodizedFinancialObservation(
        ticker="TEST", corp_code="00000001", company_family="NON_FINANCIAL",
        fiscal_year=str(year), fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics=semantics, period_start=f"{year}-01-01", period_end=f"{year}-12-31",
        metric=metric, value=value, currency=currency, method="TEST",
        anchor_report_type="ANNUAL" if period == "FY" else "QUARTER",
        anchor_reprt_code="11011", anchor_rcept_no=anchor,
        anchor_rcept_dt=receipt, source_rcept_nos=(anchor,), source_rcept_dts=(receipt,) if receipt else (),
        source_sha256s=(f"sha-{anchor}",), fs_div_used=basis,
        pit_available_from=receipt, resolution_status=status, reason=reason,
    )


def _ttm(metric: str, value, *, year: int = 2026, period: str = "Q2",
         status: str = READY, reason: str | None = None,
         requested_as_of: str | None = AS_OF) -> DerivedMetricObservation:
    return DerivedMetricObservation(
        "TEST", "00000001", "NON_FINANCIAL", str(year), period, metric, "TTM", value,
        resolution_status=status, reason=reason, period_end=f"{year}-06-30",
        source_rcept_nos=(f"{year}{period}{metric}",), requested_as_of=requested_as_of,
    )


def _f2(*, annual=60_000_000_000, quarters=(10_000_000_000,) * 4,
        latest_quarter: str | None = "2026Q2", latest_fy: str | None = "2025",
        annual_status: str = READY, quarter_periods=(
            (2025, "Q3"), (2025, "Q4"), (2026, "Q1"), (2026, "Q2"),
        ), quarter_statuses=None, requested_as_of: str = AS_OF,
        family: str = "NON_FINANCIAL"):
    if quarter_statuses is None:
        quarter_statuses = (READY,) * len(quarter_periods)
    quarter_rows = tuple(
        _period_obs("revenue", year, period, quarters[index], status=quarter_statuses[index])
        for index, (year, period) in enumerate(quarter_periods)
    )
    annual_rows = (_period_obs("revenue", 2025, "FY", annual, status=annual_status),)
    return SimpleNamespace(
        ticker="TEST", corp_code="00000001", company_family=family,
        requested_as_of=requested_as_of, quarters=quarter_rows, annuals=annual_rows,
        quarter_slots=(SimpleNamespace(identity=latest_quarter, status=READY),) if latest_quarter else (),
        annual_slots=(SimpleNamespace(identity=latest_fy, status=annual_status),) if latest_fy else (),
        latest_quarter=latest_quarter, latest_fy=latest_fy,
    )


def _f3(operating_income=1, net_income=1, *, oi_period="Q2", ni_period="Q2",
        oi_status=READY, ni_status=READY, oi_reason=None, ni_reason=None,
        requested_as_of: str | None = AS_OF):
    return DerivedMetricsResult((
        _ttm("operating_income", operating_income, period=oi_period,
             status=oi_status, reason=oi_reason, requested_as_of=requested_as_of),
        _ttm("net_income", net_income, period=ni_period,
             status=ni_status, reason=ni_reason, requested_as_of=requested_as_of),
    ))


def evaluate(*, f2=None, f3=None, config=None):
    return FundamentalsFilter(config).evaluate(f2 or _f2(), f3 or _f3())


def test_passes_when_all_four_frozen_conditions_are_met():
    result = evaluate()
    assert result.status == PASS
    assert result.passed is True
    assert result.annual_revenue == 60_000_000_000
    assert result.quarterly_avg_revenue == 10_000_000_000
    assert result.ttm_operating_income == 1
    assert result.ttm_net_income == 1
    assert result.reasons == ()


@pytest.mark.parametrize("annual, expected", [
    (49_999_999_999, FILTERED_ANNUAL_REVENUE),
    (50_000_000_000, PASS),
    (50_000_000_001, PASS),
])
def test_annual_revenue_boundary_is_inclusive(annual, expected):
    result = evaluate(f2=_f2(annual=annual))
    assert result.status == expected
    assert (FILTERED_ANNUAL_REVENUE in result.reasons) is (annual < 50_000_000_000)


@pytest.mark.parametrize("quarters, expected", [
    ((9_999_999_999,) * 4, FILTERED_QUARTERLY_REVENUE),
    ((10_000_000_000,) * 4, PASS),
    ((10_000_000_001,) * 4, PASS),
])
def test_quarterly_average_boundary_is_inclusive(quarters, expected):
    result = evaluate(f2=_f2(quarters=quarters))
    assert result.status == expected
    assert (FILTERED_QUARTERLY_REVENUE in result.reasons) is (quarters[0] < 10_000_000_000)


@pytest.mark.parametrize("oi, expected", [(-1, FILTERED_OPERATING_LOSS), (0, FILTERED_OPERATING_LOSS), (1, PASS)])
def test_operating_income_requires_strictly_positive_ttm(oi, expected):
    assert evaluate(f3=_f3(operating_income=oi)).status == expected


@pytest.mark.parametrize("ni, expected", [(-1, FILTERED_NET_LOSS), (0, FILTERED_NET_LOSS), (1, PASS)])
def test_net_income_requires_strictly_positive_ttm(ni, expected):
    assert evaluate(f3=_f3(net_income=ni)).status == expected


def test_multi_failure_preserves_all_reasons_and_uses_priority_order():
    result = evaluate(f2=_f2(annual=1, quarters=(1,) * 4), f3=_f3(operating_income=0, net_income=0))
    assert result.status == FILTERED_ANNUAL_REVENUE
    assert result.passed is False
    assert result.reasons == (
        FILTERED_ANNUAL_REVENUE, FILTERED_QUARTERLY_REVENUE,
        FILTERED_OPERATING_LOSS, FILTERED_NET_LOSS,
    )


def test_missing_quarter_fails_closed_instead_of_compressing_to_three_quarters():
    f2 = _f2(quarter_periods=((2025, "Q3"), (2025, "Q4"), (2026, "Q2")), quarters=(10, 10, 10))
    result = evaluate(f2=f2)
    assert result.status == DATA_UNAVAILABLE
    assert result.quarterly_avg_revenue is None
    assert any(item.get("endpoint") == "2026Q1" for item in result.diagnostics)


def test_latest_quarter_missing_does_not_fallback_to_an_older_four_quarter_window():
    periods = ((2025, "Q2"), (2025, "Q3"), (2025, "Q4"), (2026, "Q1"))
    result = evaluate(f2=_f2(quarters=(10,) * 4, quarter_periods=periods, latest_quarter="2026Q2"))
    assert result.status == DATA_UNAVAILABLE
    assert result.quarterly_avg_revenue is None


def test_non_ready_quarter_slot_is_preserved_and_blocks_revenue_average():
    f2 = _f2()
    f2.quarter_slots = (
        SimpleNamespace(identity="2026Q2", status=BASIS_MISMATCH, reason="BASIS_CONFLICT", missing_metrics=("revenue",)),
    )
    result = evaluate(f2=f2)
    assert result.status == DATA_UNAVAILABLE
    diagnostic = next(item for item in result.diagnostics if item.get("endpoint") == "2026Q2")
    assert diagnostic["status"] == BASIS_MISMATCH
    assert diagnostic["reason"] == "BASIS_CONFLICT"


def test_ttm_endpoint_must_match_latest_quarter_revenue_endpoint():
    result = evaluate(f3=_f3(oi_period="Q1"))
    assert result.status == DATA_UNAVAILABLE
    mismatch = next(item for item in result.diagnostics if item.get("type") == "ENDPOINT_MISMATCH")
    assert mismatch["endpoints"]["quarter_revenue"] == "2026Q2"
    assert mismatch["endpoints"]["ttm_operating_income"] == "2026Q1"


@pytest.mark.parametrize("status", [PERIOD_AMBIGUOUS, BASIS_MISMATCH, CURRENCY_MISMATCH, INPUT_NOT_READY])
def test_non_ready_ttm_status_is_preserved_in_diagnostics(status):
    result = evaluate(f3=_f3(oi_status=status, oi_reason="SOURCE_DIAGNOSTIC"))
    assert result.status == DATA_UNAVAILABLE
    diagnostic = next(item for item in result.diagnostics if item.get("type") == "TTM_INPUT_UNAVAILABLE")
    assert diagnostic["status"] == status
    assert diagnostic["reason"] == "SOURCE_DIAGNOSTIC"


def test_non_ready_latest_annual_slot_is_not_replaced_by_older_fy():
    result = evaluate(f2=_f2(annual_status=INPUT_NOT_READY))
    assert result.status == DATA_UNAVAILABLE
    diagnostic = next(item for item in result.diagnostics if item.get("type") == "ANNUAL_REVENUE_UNAVAILABLE")
    assert diagnostic["reason"] == "LATEST_FY_NOT_READY"


def test_future_pit_ttm_input_is_unavailable():
    result = evaluate(f3=_f3(oi_status=INPUT_NOT_READY, oi_reason="FUTURE_PIT_SOURCE"))
    assert result.status == DATA_UNAVAILABLE
    assert any(item.get("reason") == "FUTURE_PIT_SOURCE" for item in result.diagnostics)


def test_as_of_mismatch_fails_closed():
    result = evaluate(f3=_f3(requested_as_of="2026-06-29"))
    assert result.status == DATA_UNAVAILABLE
    assert "AS_OF_MISMATCH" in result.reasons
    assert any(item.get("type") == "AS_OF_MISMATCH" for item in result.diagnostics)


def test_financial_company_is_not_applicable_and_never_passes():
    result = evaluate(f2=_f2(family="FINANCIAL"))
    assert result.status == NOT_APPLICABLE
    assert result.passed is False
    assert result.annual_revenue is None


def test_config_controls_thresholds_and_positive_income_requirements():
    config = FundamentalsFilterConfig(
        annual_revenue_min=100, quarterly_avg_revenue_min=20,
        require_positive_ttm_operating_income=False, require_positive_ttm_net_income=False,
    )
    result = evaluate(f2=_f2(annual=100, quarters=(20,) * 4), f3=_f3(operating_income=-1, net_income=-1), config=config)
    assert result.status == PASS
    assert result.thresholds == config.to_dict()
    assert result.ttm_operating_income is None
    assert result.ttm_net_income is None


def test_result_serialization_is_json_friendly():
    payload = evaluate().to_dict()
    assert payload["status"] == PASS
    assert payload["passed"] is True
    assert isinstance(payload["reasons"], list)
    assert isinstance(payload["diagnostics"], list)
