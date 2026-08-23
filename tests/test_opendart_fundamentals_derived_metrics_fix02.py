from __future__ import annotations

from dataclasses import dataclass

import pytest

from trend_scanner.fundamentals.derived_metrics import (
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
)
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider
from trend_scanner.fundamentals.period_models import (
    PeriodizationFact,
    PeriodizationResult,
    PeriodizedFinancialObservation,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild


def _obs(metric: str, year: str, period: str, value, *, basis: str = "CFS",
         currency: str = "KRW", family: str = "NON_FINANCIAL", status: str = "READY",
         available: str | None = None, no: str | None = None):
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    anchor = no or f"{year}-{period}-{metric}"
    receipt = available or f"{year}-12-31"
    return PeriodizedFinancialObservation(
        ticker="FIX02", corp_code="00000002", company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="CUMULATIVE_YTD" if period == "FY" else "STANDALONE_QUARTER",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31", metric=metric,
        value=value, currency=currency, method="FIX02_TEST", anchor_report_type=period,
        anchor_reprt_code=code, anchor_rcept_no=anchor, anchor_rcept_dt=receipt,
        source_rcept_nos=(anchor,), source_rcept_dts=(receipt,),
        source_sha256s=(f"sha-{anchor}",), fs_div_used=basis,
        pit_available_from=available, resolution_status=status,
    )


def _derive(rows, *, as_of=None):
    return DerivedMetricsEngine().derive(rows, requested_as_of=as_of)


@pytest.mark.parametrize("prior,current", [(-100, 50), (100, -50), (-100, -30), (-30, -100), (0, 50)])
def test_case_a_e_sign_transitions_never_emit_numeric_percentage(prior, current):
    result = _derive([_obs("net_income", "2023", "Q1", prior),
                      _obs("net_income", "2024", "Q1", current)])
    transition = result.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1")
    growth = result.get("net_income", "QUARTERLY_YOY", "2024", "Q1")
    alias = result.get("net_income", "NET_INCOME_GROWTH", "2024", "Q1")
    assert transition is not None and transition.value is not None
    assert growth is not None and growth.value is None
    assert alias is not None and alias.value is None and alias.resolution_status == UNDEFINED_BASE


def test_case_b_ambiguous_input_is_not_used_by_ready_output():
    result = _derive([_obs("revenue", "2023", "Q1", 100),
                      _obs("revenue", "2024", "Q1", 120, status="PERIOD_AMBIGUOUS")])
    item = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    assert item is not None and item.value is None and item.resolution_status == INPUT_NOT_READY


@pytest.mark.parametrize("metric_type", ["QUARTERLY_YOY", "ANNUAL_YOY"])
def test_case_c_basis_mismatch_is_fail_closed(metric_type):
    period = "Q2" if metric_type == "QUARTERLY_YOY" else "FY"
    result = _derive([_obs("revenue", "2023", period, 100, basis="CFS"),
                      _obs("revenue", "2024", period, 120, basis="OFS")])
    item = result.get("revenue", metric_type, "2024", period)
    assert item is not None and item.value is None and item.resolution_status == BASIS_MISMATCH


def test_case_c_basis_mismatch_blocks_ttm_and_margin():
    rows = []
    for period in ("Q1", "Q2", "Q3", "Q4"):
        rows.extend((_obs("revenue", "2024", period, 100, basis="OFS" if period == "Q4" else "CFS"),
                     _obs("operating_income", "2024", period, 10, basis="CFS")))
    result = _derive(rows)
    assert result.get("revenue", "TTM", "2024", "Q4").resolution_status == BASIS_MISMATCH
    assert result.get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4").resolution_status == BASIS_MISMATCH


def test_case_d_currency_mismatch_blocks_yoy_ttm_and_margin():
    yoy = _derive([_obs("revenue", "2023", "Q2", 100),
                   _obs("revenue", "2024", "Q2", 120, currency="USD")])
    assert yoy.get("revenue", "QUARTERLY_YOY", "2024", "Q2").resolution_status == CURRENCY_MISMATCH
    rows = []
    for period in ("Q1", "Q2", "Q3", "Q4"):
        currency = "USD" if period == "Q4" else "KRW"
        rows.extend((_obs("revenue", "2024", period, 100, currency=currency),
                     _obs("operating_income", "2024", period, 10)))
    result = _derive(rows)
    assert result.get("revenue", "TTM", "2024", "Q4").resolution_status == CURRENCY_MISMATCH
    assert result.get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4").resolution_status == CURRENCY_MISMATCH


def test_case_f_zero_and_negative_bases_never_emit_percentages():
    rows = [_obs("revenue", "2024", "Q1", 0), _obs("operating_income", "2024", "Q1", 10),
            _obs("revenue", "2024", "Q2", -100), _obs("operating_income", "2024", "Q2", 10)]
    result = _derive(rows)
    for period in ("Q1", "Q2"):
        item = result.get("operating_income", "OPERATING_MARGIN", "2024", period)
        assert item is not None and item.value is None and item.resolution_status == UNDEFINED_BASE
        assert item.reason == "NON_POSITIVE_REVENUE_BASE"


def test_case_g_financial_margin_and_ttm_margin_are_not_applicable():
    rows = []
    for period in ("Q1", "Q2", "Q3", "Q4"):
        rows.extend((_obs("revenue", "2024", period, 100, family="FINANCIAL"),
                     _obs("net_income", "2024", period, 10, family="FINANCIAL")))
    result = _derive(rows)
    assert result.get("net_income", "NET_MARGIN", "2024", "Q1").resolution_status == NOT_APPLICABLE
    assert result.get("net_income", "TTM_NET_MARGIN", "2024", "Q4").resolution_status == NOT_APPLICABLE


def test_case_h_ttm_yoy_requires_eight_aligned_sources():
    rows = []
    for year, values in (("2023", (100, 110, 120, 130)), ("2024", (120, 132, 144, 156))):
        rows.extend(_obs("revenue", year, p, value)
                    for p, value in zip(("Q1", "Q2", "Q3", "Q4"), values))
    item = _derive(rows).get("revenue", "TTM_YOY", "2024", "Q4")
    assert item is not None and item.resolution_status == "READY" and item.value == 20
    assert len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s) == 8


def test_case_i_all_derived_sources_are_aligned():
    rows = [_obs("revenue", "2023", "Q1", 100), _obs("revenue", "2024", "Q1", 120)]
    result = _derive(rows)
    assert all(len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
               for item in result)


def test_case_j_pit_metadata_blocks_future_and_records_cutoff():
    result = _derive([_obs("revenue", "2024", "Q1", 100, available="2024-03-01"),
                      _obs("revenue", "2023", "Q1", 80, available="2023-03-01")],
                     as_of="2024-02-15")
    item = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    assert item is not None and item.value is None and item.resolution_status == INPUT_NOT_READY
    assert item.requested_as_of == "2024-02-15"


def test_case_k_unknown_pit_availability_fails_closed():
    result = _derive([_obs("revenue", "2024", "Q1", 100, available=None)], as_of="2024-02-15")
    # There is no comparable period, but the canonical context must remain
    # explicitly unavailable rather than exposing a READY value.
    assert all(item.resolution_status != "READY" for item in result)


@dataclass
class _Provider:
    rows: tuple[PeriodizedFinancialObservation, ...]
    calls: list[tuple[str, str, str]]

    def build(self, ticker, fiscal_year, requested_as_of, **kwargs):
        self.calls.append((str(ticker), str(fiscal_year), str(requested_as_of)))
        rows = tuple(item for item in self.rows if item.fiscal_year == str(fiscal_year))
        return PeriodizationBuild(
            ticker=str(ticker), fiscal_year=str(fiscal_year), requested_as_of=str(requested_as_of),
            company_family="NON_FINANCIAL", filings=(), facts=(), result=PeriodizationResult(rows),
            anchor_selections=(), skipped_anchors=(),
        )


def test_case_l_derived_provider_uses_only_canonical_result_and_one_cutoff():
    current = _obs("revenue", "2024", "Q3", 120)
    historical = PeriodizationFact(
        ticker="FIX02", corp_code="00000002", company_family="NON_FINANCIAL", fiscal_year="2024",
        metric="revenue", value=999, currency="KRW", reprt_code="11012", report_type="HALF_YEAR",
        rcept_no="HISTORICAL", rcept_dt="2024-08-14", period_start="2024-01-01", period_end="2024-06-30",
    )
    provider = _Provider((current,), [])
    build = DerivedMetricsProvider(provider).build("FIX02", ("2023", "2024"), "2024-08-20")
    assert provider.calls == [("FIX02", "2023", "2024-08-20"), ("FIX02", "2024", "2024-08-20")]
    assert all(item.anchor_rcept_no != "HISTORICAL" for item in build.canonical_observations)


def test_case_m_provider_output_provenance_is_subset_of_canonical_inputs():
    rows = (_obs("revenue", "2023", "Q1", 100), _obs("revenue", "2024", "Q1", 120))
    provider = _Provider(rows, [])
    build = DerivedMetricsProvider(provider).build("FIX02", ("2023", "2024"), "2024-08-20")
    canonical = {item.anchor_rcept_no for item in build.canonical_observations}
    assert all(set(item.source_rcept_nos).issubset(canonical) for item in build.result)
