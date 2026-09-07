from __future__ import annotations

from trend_scanner.fundamentals.derived_metrics import (
    ANNUAL_ROE,
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    DATA_UNAVAILABLE,
    DEBT_RATIO,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    PERIOD_AMBIGUOUS,
    TTM_ROE,
    UNDEFINED_BASE,
    DerivedMetricsEngine,
)
from trend_scanner.fundamentals.multi_period import build_multi_period_result
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation


_CODE = {
    "Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011",
    "Q1_END": "11013", "H1_END": "11012", "Q3_END": "11014", "FY_END": "11011",
}


def _obs(
    metric: str, year: int | str, period: str, value,
    *, basis: str = "CFS", currency: str = "KRW", family: str = "NON_FINANCIAL",
    status: str = "READY", receipt: str | None = "AUTO", pit: str | None = "AUTO",
    anchor: str | None = None,
) -> PeriodizedFinancialObservation:
    year = str(year)
    anchor = anchor or f"{year}-{period}-{metric}"
    if receipt == "AUTO":
        receipt = f"{year}-12-31"
    if pit == "AUTO":
        pit = receipt
    semantics = "INSTANT" if period.endswith("_END") else "FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER"
    return PeriodizedFinancialObservation(
        ticker="CAPITAL", corp_code="00000003", company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics=semantics, period_start=f"{year}-01-01", period_end=f"{year}-12-31",
        metric=metric, value=value, currency=currency, method="F3_TEST",
        anchor_report_type="ANNUAL" if period in {"FY", "FY_END"} else "QUARTER",
        anchor_reprt_code=_CODE[period], anchor_rcept_no=anchor, anchor_rcept_dt=receipt,
        source_rcept_nos=(anchor,), source_rcept_dts=(receipt,) if receipt else (),
        source_sha256s=(f"sha-{anchor}",), fs_div_used=basis,
        pit_available_from=pit, resolution_status=status,
    )


def _derive(rows, *, as_of=None):
    return DerivedMetricsEngine().derive(rows, requested_as_of=as_of)


def _annual_rows(*, prior=1000, current=1400, ni=120, **kwargs):
    return [
        _obs("net_income", 2025, "FY", ni, **kwargs),
        _obs("equity", 2024, "FY_END", prior, **kwargs),
        _obs("equity", 2025, "FY_END", current, **kwargs),
    ]


def test_annual_roe_normal_uses_average_beginning_and_ending_equity():
    item = _derive(_annual_rows()).get("net_income", ANNUAL_ROE, "2025", "FY")
    assert item is not None and item.value == 10
    assert item.unit == "PERCENT"
    assert item.metadata["begin_equity_period"] == "2024FY_END"
    assert item.metadata["end_equity_period"] == "2025FY_END"
    assert len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s) == 3


def test_annual_roe_missing_prior_or_current_equity_fails_closed():
    missing_prior = _derive(_annual_rows()[:1] + _annual_rows()[2:]).get("net_income", ANNUAL_ROE, "2025", "FY")
    missing_current = _derive(_annual_rows()[:2]).get("net_income", ANNUAL_ROE, "2025", "FY")
    assert missing_prior is not None and missing_prior.value is None and missing_prior.resolution_status == DATA_UNAVAILABLE
    assert missing_current is not None and missing_current.value is None and missing_current.resolution_status == DATA_UNAVAILABLE


def test_annual_roe_ambiguous_or_non_ready_equity_fails_closed():
    ambiguous = _derive(_annual_rows(status=PERIOD_AMBIGUOUS)).get("net_income", ANNUAL_ROE, "2025", "FY")
    assert ambiguous is not None and ambiguous.value is None and ambiguous.resolution_status == PERIOD_AMBIGUOUS


def test_annual_roe_basis_currency_and_non_positive_average_are_explicit():
    basis_rows = _annual_rows()
    basis_rows[-1] = _obs("equity", 2025, "FY_END", 1400, basis="OFS")
    basis = _derive(basis_rows).get("net_income", ANNUAL_ROE, "2025", "FY")
    currency_rows = [
        _obs("net_income", 2025, "FY", 120),
        _obs("equity", 2024, "FY_END", 1000, currency="USD"),
        _obs("equity", 2025, "FY_END", 1400),
    ]
    currency = _derive(currency_rows).get("net_income", ANNUAL_ROE, "2025", "FY")
    undefined = _derive(_annual_rows(prior=-100, current=0)).get("net_income", ANNUAL_ROE, "2025", "FY")
    assert basis is not None and basis.resolution_status == BASIS_MISMATCH
    assert currency is not None and currency.resolution_status == CURRENCY_MISMATCH
    assert undefined is not None and undefined.resolution_status == UNDEFINED_BASE
    assert undefined.reason == "NON_POSITIVE_AVERAGE_EQUITY_BASE"


def test_annual_roe_future_source_is_input_not_ready():
    rows = [
        _obs("net_income", 2025, "FY", 120, receipt="2025-12-31"),
        _obs("equity", 2024, "FY_END", 1000, receipt="2024-12-31"),
        _obs("equity", 2025, "FY_END", 1400, receipt="2026-01-01"),
    ]
    item = _derive(rows, as_of="2025-12-31").get("net_income", ANNUAL_ROE, "2025", "FY")
    assert item is not None and item.value is None and item.resolution_status == INPUT_NOT_READY


def _ttm_rows(*, begin=800, end=1200, basis="CFS", currency="KRW"):
    rows = [_obs("net_income", 2024, period, 25, basis=basis, currency=currency)
            for period in ("Q2", "Q3", "Q4")]
    rows.append(_obs("net_income", 2025, "Q1", 25, basis=basis, currency=currency))
    rows.extend((_obs("equity", 2024, "Q1_END", begin, basis=basis, currency=currency),
                 _obs("equity", 2025, "Q1_END", end, basis=basis, currency=currency)))
    return rows


def test_ttm_roe_normal_reuses_four_quarter_ttm_and_equity_endpoints():
    item = _derive(_ttm_rows()).get("net_income", TTM_ROE, "2025", "Q1")
    assert item is not None and item.value == 10
    assert item.metadata["ttm_start"] == "2024Q2"
    assert item.metadata["ttm_end"] == "2025Q1"
    assert item.metadata["begin_equity_period"] == "2024Q1_END"
    assert item.metadata["end_equity_period"] == "2025Q1_END"
    assert len(item.source_rcept_nos) == 6


def test_ttm_roe_missing_or_non_contiguous_four_quarter_window_is_unavailable():
    rows = _ttm_rows()
    missing = [item for item in rows if not (item.metric == "net_income" and item.fiscal_period == "Q2")]
    non_contiguous = [item for item in rows if not (item.metric == "net_income" and item.fiscal_period == "Q3")]
    missing_item = _derive(missing).get("net_income", TTM_ROE, "2025", "Q1")
    non_contiguous_item = _derive(non_contiguous).get("net_income", TTM_ROE, "2025", "Q1")
    assert missing_item is not None and missing_item.resolution_status == DATA_UNAVAILABLE
    assert non_contiguous_item is not None and non_contiguous_item.resolution_status == DATA_UNAVAILABLE


def test_ttm_roe_missing_beginning_or_ending_equity_fails_closed():
    no_begin = [item for item in _ttm_rows() if not (item.metric == "equity" and item.fiscal_period == "Q1_END" and item.fiscal_year == "2024")]
    no_end = [item for item in _ttm_rows() if not (item.metric == "equity" and item.fiscal_period == "Q1_END" and item.fiscal_year == "2025")]
    begin_item = _derive(no_begin).get("net_income", TTM_ROE, "2025", "Q1")
    end_item = _derive(no_end).get("net_income", TTM_ROE, "2025", "Q1")
    assert begin_item is not None and begin_item.resolution_status == DATA_UNAVAILABLE
    assert end_item is not None and end_item.resolution_status == DATA_UNAVAILABLE


def test_ttm_roe_basis_currency_and_non_positive_average_are_explicit():
    basis_rows = _ttm_rows()
    basis_rows[2] = _obs("net_income", 2024, "Q4", 25, basis="OFS")
    currency_rows = _ttm_rows()
    currency_rows[2] = _obs("net_income", 2024, "Q4", 25, currency="USD")
    undefined = _derive(_ttm_rows(begin=-100, end=0)).get("net_income", TTM_ROE, "2025", "Q1")
    basis = _derive(basis_rows).get("net_income", TTM_ROE, "2025", "Q1")
    currency = _derive(currency_rows).get("net_income", TTM_ROE, "2025", "Q1")
    assert basis is not None and basis.resolution_status == BASIS_MISMATCH
    assert currency is not None and currency.resolution_status == CURRENCY_MISMATCH
    assert undefined is not None and undefined.resolution_status == UNDEFINED_BASE


def test_ttm_roe_future_equity_is_input_not_ready():
    rows = _ttm_rows()
    rows[-1] = _obs("equity", 2025, "Q1_END", 1200, receipt="2025-04-01")
    item = _derive(rows, as_of="2025-03-31").get("net_income", TTM_ROE, "2025", "Q1")
    assert item is not None and item.resolution_status == INPUT_NOT_READY


def test_debt_ratio_is_instant_and_supports_fy_and_quarter_end_snapshots():
    rows = [
        _obs("liabilities", 2025, "FY_END", 600), _obs("equity", 2025, "FY_END", 1200),
        _obs("liabilities", 2025, "Q3_END", 400), _obs("equity", 2025, "Q3_END", 1000),
    ]
    result = _derive(rows)
    fy = result.get("liabilities", DEBT_RATIO, "2025", "FY_END")
    quarter = result.get("liabilities", DEBT_RATIO, "2025", "Q3_END")
    assert fy is not None and fy.value == 50 and fy.unit == "PERCENT"
    assert quarter is not None and quarter.value == 40
    assert fy.metadata["snapshot_period"] == "2025FY_END"


def test_debt_ratio_missing_input_and_non_positive_equity_fail_closed():
    missing_liabilities = _derive([_obs("equity", 2025, "FY_END", 1200)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    missing_equity = _derive([_obs("liabilities", 2025, "FY_END", 600)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    zero = _derive([_obs("liabilities", 2025, "FY_END", 600), _obs("equity", 2025, "FY_END", 0)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    negative = _derive([_obs("liabilities", 2025, "FY_END", 600), _obs("equity", 2025, "FY_END", -1)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    assert missing_liabilities is not None and missing_liabilities.resolution_status == DATA_UNAVAILABLE
    assert missing_equity is not None and missing_equity.resolution_status == DATA_UNAVAILABLE
    assert zero is not None and zero.resolution_status == UNDEFINED_BASE
    assert negative is not None and negative.resolution_status == UNDEFINED_BASE
    assert zero.reason == "NON_POSITIVE_EQUITY_BASE"


def test_debt_ratio_basis_currency_ambiguous_and_future_are_fail_closed():
    basis = _derive([_obs("liabilities", 2025, "FY_END", 600, basis="OFS"), _obs("equity", 2025, "FY_END", 1200)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    currency = _derive([_obs("liabilities", 2025, "FY_END", 600, currency="USD"), _obs("equity", 2025, "FY_END", 1200)]).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    ambiguous_rows = [_obs("liabilities", 2025, "FY_END", 600), _obs("equity", 2025, "FY_END", 1200, anchor="A"), _obs("equity", 2025, "FY_END", 1300, anchor="A")]
    ambiguous = _derive(ambiguous_rows).get("liabilities", DEBT_RATIO, "2025", "FY_END")
    future = _derive([_obs("liabilities", 2025, "FY_END", 600, receipt="2026-01-01"), _obs("equity", 2025, "FY_END", 1200, receipt="2026-01-01")], as_of="2025-12-31").get("liabilities", DEBT_RATIO, "2025", "FY_END")
    assert basis is not None and basis.resolution_status == BASIS_MISMATCH
    assert currency is not None and currency.resolution_status == CURRENCY_MISMATCH
    assert ambiguous is not None and ambiguous.resolution_status == PERIOD_AMBIGUOUS
    assert future is not None and future.resolution_status == INPUT_NOT_READY


def test_financial_family_capital_metrics_are_not_applicable():
    rows = _annual_rows(family="FINANCIAL") + _ttm_rows()
    rows = [
        _obs(item.metric, item.fiscal_year, item.fiscal_period, item.value, family="FINANCIAL",
             basis=item.fs_div_used, currency=item.currency, receipt=item.anchor_rcept_dt)
        for item in rows
    ]
    result = _derive(rows)
    assert all(item.resolution_status == NOT_APPLICABLE for item in result.filter(metric_type=ANNUAL_ROE))
    assert all(item.resolution_status == NOT_APPLICABLE for item in result.filter(metric_type=TTM_ROE))
    assert all(item.resolution_status == NOT_APPLICABLE for item in result.filter(metric_type=DEBT_RATIO))


def test_f2_multi_period_result_is_directly_consumable():
    rows = _ttm_rows() + _annual_rows()
    f2 = build_multi_period_result(ticker="CAPITAL", requested_as_of="2025-12-31", observations=rows)
    result = DerivedMetricsEngine().derive(f2, requested_as_of="2025-12-31")
    assert result.get("net_income", TTM_ROE, "2025", "Q1").value == 10
    assert result.get("net_income", ANNUAL_ROE, "2025", "FY").value == 10
    assert result.get("liabilities", DEBT_RATIO, "2025", "FY_END") is not None
