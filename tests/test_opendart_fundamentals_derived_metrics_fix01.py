from __future__ import annotations

from dataclasses import dataclass

import pytest

from trend_scanner.fundamentals.derived_metrics import (
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    DATA_UNAVAILABLE,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
)
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider
from trend_scanner.fundamentals.models import RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import (
    PeriodizationFact,
    PeriodizationResult,
    PeriodizedFinancialObservation,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild


def _obs(metric: str, year: str, period: str, value, *, basis: str = "CFS",
         currency: str = "KRW", family: str = "NON_FINANCIAL",
         status: str = "READY", no: str | None = None,
         available: str | None = None, semantics: str | None = None):
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    anchor = no or f"{year}-{period}-{metric}"
    date = available or f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker="FIX01", corp_code="00000001", company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics=semantics or ("CUMULATIVE_YTD" if period == "FY" else "STANDALONE_QUARTER"),
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric, value=value,
        currency=currency, method="FIX01_TEST", anchor_report_type=REPORT_TYPE_BY_CODE[code],
        anchor_reprt_code=code, anchor_rcept_no=anchor, anchor_rcept_dt=date,
        source_rcept_nos=(anchor,), source_rcept_dts=(date,), source_sha256s=(f"sha-{anchor}",),
        fs_div_used=basis, pit_available_from=available or date, resolution_status=status,
    )


def _result(rows):
    return DerivedMetricsEngine().derive(PeriodizationResult(tuple(rows)))


@pytest.mark.parametrize(
    ("prior", "current", "transition"),
    [(-100, 50, "LOSS_TO_PROFIT"), (100, -50, "PROFIT_TO_LOSS"),
     (-100, -30, "LOSS_NARROWING"), (-30, -100, "LOSS_WIDENING")],
)
def test_sign_transitions_never_emit_percentage_growth(prior, current, transition):
    result = _result([
        _obs("net_income", "2023", "Q1", prior),
        _obs("net_income", "2024", "Q1", current),
    ])
    classification = result.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1")
    growth = result.get("net_income", "QUARTERLY_YOY", "2024", "Q1")
    alias = result.get("net_income", "NET_INCOME_GROWTH", "2024", "Q1")
    assert classification.value == transition
    assert growth.value is None and growth.resolution_status != "READY"
    assert alias.value is None and alias.resolution_status == UNDEFINED_BASE


def test_zero_transition_states_are_explicit():
    result = _result([
        _obs("net_income", "2023", "Q1", 0),
        _obs("net_income", "2024", "Q1", 50),
        _obs("operating_income", "2023", "Q1", 100),
        _obs("operating_income", "2024", "Q1", 0),
    ])
    assert result.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1").value == "ZERO_BASE"
    assert result.get("operating_income", "EARNINGS_TRANSITION", "2024", "Q1").value == "ZERO_CURRENT"


def test_positive_growth_uses_signed_positive_base_formula():
    result = _result([
        _obs("revenue", "2023", "Q1", 100),
        _obs("revenue", "2024", "Q1", 120),
    ])
    assert result.get("revenue", "QUARTERLY_YOY", "2024", "Q1").value == 20


def test_zero_growth_base_is_undefined():
    result = _result([
        _obs("revenue", "2023", "Q1", 0),
        _obs("revenue", "2024", "Q1", 50),
    ])
    item = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    assert item.value is None and item.resolution_status == UNDEFINED_BASE


def test_ttm_requires_four_contiguous_quarters_and_keeps_four_sources():
    rows = [_obs("revenue", "2024", p, v) for p, v in zip(("Q1", "Q2", "Q3", "Q4"), (100, 110, 120, 130))]
    item = _result(rows).get("revenue", "TTM", "2024", "Q4")
    assert item.value == 460
    assert item.resolution_status == "READY"
    assert len(item.source_rcept_nos) == 4


def test_ttm_missing_quarter_is_unavailable():
    rows = [_obs("revenue", "2024", p, 100) for p in ("Q1", "Q3", "Q4")]
    item = _result(rows).get("revenue", "TTM", "2024", "Q4")
    assert item.value is None and item.resolution_status == DATA_UNAVAILABLE


def test_ttm_basis_mismatch_is_not_calculated():
    rows = [_obs("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS")
            for p in ("Q1", "Q2", "Q3", "Q4")]
    item = _result(rows).get("revenue", "TTM", "2024", "Q4")
    assert item.value is None and item.resolution_status == BASIS_MISMATCH


def test_ttm_currency_mismatch_is_not_calculated():
    rows = [_obs("revenue", "2024", p, 100, currency="USD" if p == "Q4" else "KRW")
            for p in ("Q1", "Q2", "Q3", "Q4")]
    item = _result(rows).get("revenue", "TTM", "2024", "Q4")
    assert item.value is None and item.resolution_status == CURRENCY_MISMATCH


def test_ttm_yoy_tracks_all_eight_quarters():
    rows = []
    for year, values in (("2023", (100, 110, 120, 130)), ("2024", (120, 132, 144, 156))):
        rows.extend(_obs("revenue", year, p, v)
                    for p, v in zip(("Q1", "Q2", "Q3", "Q4"), values))
    item = _result(rows).get("revenue", "TTM_YOY", "2024", "Q4")
    assert item.value == 20
    assert len(item.source_rcept_nos) == 8
    assert len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)


def test_ttm_margin_uses_summed_numerators_and_revenue():
    rows = []
    for p, revenue, operating in zip(("Q1", "Q2", "Q3", "Q4"), (100, 200, 300, 400), (10, 20, 30, 90)):
        rows.extend((_obs("revenue", "2024", p, revenue),
                     _obs("operating_income", "2024", p, operating)))
    item = _result(rows).get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4")
    assert item.value == 15
    assert len(item.source_rcept_nos) == 8


def test_negative_revenue_margin_is_undefined_base():
    item = _result([_obs("revenue", "2024", "Q1", -100),
                    _obs("operating_income", "2024", "Q1", 10)]).get(
                        "operating_income", "OPERATING_MARGIN", "2024", "Q1")
    assert item.value is None and item.resolution_status == UNDEFINED_BASE
    assert item.reason == "NON_POSITIVE_REVENUE_BASE"


def test_financial_margins_are_explicitly_not_applicable():
    rows = [_obs("net_income", "2024", p, 10, family="FINANCIAL") for p in ("Q1", "Q2", "Q3", "Q4")]
    result = _result(rows)
    margin = result.get("net_income", "NET_MARGIN", "2024", "Q1")
    ttm = result.get("net_income", "TTM_NET_MARGIN", "2024", "Q4")
    assert margin.value is None and margin.resolution_status == NOT_APPLICABLE
    assert ttm.value is None and ttm.resolution_status == NOT_APPLICABLE


def test_yoy_basis_and_currency_gates_are_explicit():
    basis = _result([_obs("revenue", "2023", "Q2", 100, basis="CFS"),
                    _obs("revenue", "2024", "Q2", 120, basis="OFS")]).get(
                        "revenue", "QUARTERLY_YOY", "2024", "Q2")
    currency = _result([_obs("revenue", "2023", "Q2", 100, currency="KRW"),
                        _obs("revenue", "2024", "Q2", 120, currency="USD")]).get(
                            "revenue", "QUARTERLY_YOY", "2024", "Q2")
    assert basis.value is None and basis.resolution_status == BASIS_MISMATCH
    assert currency.value is None and currency.resolution_status == CURRENCY_MISMATCH


def test_requested_as_of_excludes_future_correction_and_allows_it_after_cutoff():
    rows = [
        _obs("revenue", "2024", "Q1", 100, no="ORIGINAL", available="2024-02-10"),
        _obs("revenue", "2024", "Q1", 120, no="CORRECTION", available="2024-03-10"),
    ]
    before = DerivedMetricsEngine().derive(rows, requested_as_of="2024-02-20")
    after = DerivedMetricsEngine().derive(rows, requested_as_of="2024-03-20")
    assert before.get("revenue", "REVENUE_GROWTH", "2024", "Q1").value is None
    assert before.get("revenue", "REVENUE_GROWTH", "2024", "Q1").pit_available_from == "2024-02-10"
    assert after.get("revenue", "REVENUE_GROWTH", "2024", "Q1").value is None


def test_future_only_input_is_not_ready():
    item = DerivedMetricsEngine().derive(
        [_obs("revenue", "2024", "Q1", 100, available="2024-03-10")],
        requested_as_of="2024-02-20",
    ).get("revenue", "REVENUE_GROWTH", "2024", "Q1")
    assert item.value is None and item.resolution_status == INPUT_NOT_READY


def test_period_semantics_gate_excludes_cumulative_quarter():
    result = _result([
        _obs("revenue", "2023", "Q1", 100),
        _obs("revenue", "2024", "Q1", 120, semantics="CUMULATIVE_YTD"),
    ])
    assert result.get("revenue", "QUARTERLY_YOY", "2024", "Q1") is None


@dataclass
class _FakePeriodizationProvider:
    builds: list[tuple[str, str, str]]
    build_result: PeriodizationBuild

    def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
        self.builds.append((ticker, fiscal_year, str(requested_as_of)))
        return self.build_result


def _fake_build(rows, *, facts=()):
    return PeriodizationBuild(
        ticker="FIX01", fiscal_year="2024", requested_as_of="2024-08-20",
        company_family="NON_FINANCIAL", filings=(), facts=tuple(facts),
        result=PeriodizationResult(tuple(rows)), anchor_selections=(), skipped_anchors=(),
    )


def test_derived_provider_uses_same_cutoff_and_canonical_result_not_facts():
    q3 = _obs("revenue", "2024", "Q3", 120)
    historical_fact = PeriodizationFact(
        ticker="FIX01", corp_code="00000001", company_family="NON_FINANCIAL",
        fiscal_year="2024", metric="revenue", value=999, currency="KRW",
        reprt_code="11012", report_type="HALF_YEAR", rcept_no="H1-A",
        rcept_dt="2024-08-14", period_start="2024-01-01", period_end="2024-06-30",
    )
    fake = _FakePeriodizationProvider([], _fake_build([q3], facts=[historical_fact]))
    build = DerivedMetricsProvider(fake).build("FIX01", ("2023", "2024"), "2024-08-20")
    assert fake.builds == [("FIX01", "2023", "2024-08-20"), ("FIX01", "2024", "2024-08-20")]
    assert build.canonical_observations == (q3, q3)
    assert not any(item.fiscal_period == "Q2" for item in build.canonical_observations)
    assert build.result.get("revenue", "REVENUE_GROWTH", "2024", "Q3").value is None


def test_ambiguous_input_never_becomes_ready():
    item = _result([
        _obs("revenue", "2023", "Q1", 100),
        _obs("revenue", "2024", "Q1", 120, status="PERIOD_AMBIGUOUS"),
    ]).get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    assert item.value is None and item.resolution_status == INPUT_NOT_READY
