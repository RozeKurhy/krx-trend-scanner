from __future__ import annotations

from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, PERIOD_AMBIGUOUS, READY, PeriodizationFact
from trend_scanner.fundamentals.periodization import PeriodizationEngine


def _fact(code: str, no: str, value: int, *, dt: str = "2025-05-15",
          start: str = "2025-01-01", end: str = "2025-03-31",
          semantic: str = CUMULATIVE_YTD) -> PeriodizationFact:
    if code == "11012":
        start, end = ("2025-01-01", "2025-06-30") if semantic == CUMULATIVE_YTD else ("2025-04-01", "2025-06-30")
    return PeriodizationFact(
        ticker="237690", corp_code="00871833", company_family=CompanyFamily.NON_FINANCIAL.value,
        fiscal_year="2025", fiscal_year_start="2025-01-01", metric="revenue", value=value,
        currency="KRW", reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], rcept_no=no,
        rcept_dt=dt, period_start=start, period_end=end, fs_div_used="CFS",
        source_sha256=f"sha-{no}-{value}", period_semantics=semantic, pit_available_from=dt,
    )


def _obs(result, period: str):
    return next(item for item in result.observations if item.fiscal_period == period)


def test_same_filing_duplicate_cumulative_contexts_fail_closed_even_same_value():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1", 40), _fact("11013", "Q1", 40),
        _fact("11012", "H1", 100, dt="2025-08-14"),
    ])
    q1 = _obs(result, "Q1")
    q2 = _obs(result, "Q2")
    assert q1.resolution_status == PERIOD_AMBIGUOUS
    assert q2.value is None
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS"
    assert result.parity == ()


def test_same_filing_duplicate_cumulative_contexts_fail_closed_different_values():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1", 40), _fact("11013", "Q1", 41),
        _fact("11012", "H1", 100, dt="2025-08-14"),
    ])
    q2 = _obs(result, "Q2")
    assert q2.value is None
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS"
    assert result.parity == ()


def test_ambiguous_prior_preserves_unique_direct_standalone_without_parity():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1", 40), _fact("11013", "Q1", 40),
        _fact("11012", "H1", 100, dt="2025-08-14"),
        _fact("11012", "H1", 60, dt="2025-08-14", semantic="STANDALONE_QUARTER"),
    ])
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert q2.method == "DIRECT_ONLY"
    assert q2.resolution_status == READY
    assert q2.source_rcept_nos == ("H1",)
    assert result.parity == ()


def test_unique_prior_keeps_direct_derived_validation():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1", 40),
        _fact("11012", "H1", 100, dt="2025-08-14"),
        _fact("11012", "H1", 60, dt="2025-08-14", semantic="STANDALONE_QUARTER"),
    ])
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert q2.method == "DIRECT_VALIDATED_BY_DERIVATION"
    assert q2.resolution_status == READY
    assert len(result.parity) == 1
    assert result.parity[0].status == "MATCH"


def test_same_eod_multiple_filings_regression_remains_fail_closed():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1-A", 40), _fact("11013", "Q1-B", 41),
        _fact("11012", "H1", 100, dt="2025-08-14"),
    ])
    q2 = _obs(result, "Q2")
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD"
    assert result.parity == ()


def test_late_correction_does_not_resolve_earlier_ambiguity():
    result = PeriodizationEngine().periodize([
        _fact("11013", "Q1-A", 40), _fact("11013", "Q1-B", 41),
        _fact("11013", "Q1-C", 45, dt="2025-10-01"),
        _fact("11012", "H1", 100, dt="2025-08-14"),
    ], as_of="2025-11-01")
    q1_c = next(item for item in result.observations
                if item.fiscal_period == "Q1" and item.anchor_rcept_no == "Q1-C")
    q2 = _obs(result, "Q2")
    assert q1_c.value == 45
    assert q1_c.resolution_status == READY
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD"
