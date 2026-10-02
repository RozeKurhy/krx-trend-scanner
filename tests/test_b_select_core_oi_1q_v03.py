"""Network-free tests for the B Select Core V03 latest-quarter operating-income gate."""

from trend_scanner.backtest.b_select_core_oi_1q_v03 import (
    BASIS_OR_CURRENCY_MISMATCH,
    FAIL,
    PASS,
    UNAVAILABLE,
    evaluate_signal,
    latest_disclosed_quarter,
    operating_income_rule,
)
from trend_scanner.fundamentals.period_models import (
    DATA_UNAVAILABLE,
    STANDALONE_QUARTER,
    PeriodizedFinancialObservation,
    READY,
)

B = 1_000_000_000


def obs(year, period, value, *, available, status=READY, basis="CFS", currency="KRW", rcept=None):
    return PeriodizedFinancialObservation(
        ticker="000001", corp_code="00000000", company_family="NON_FINANCIAL", fiscal_year=str(year),
        fiscal_year_start=f"{year}-01-01", fiscal_period=period, period_semantics=STANDALONE_QUARTER,
        period_start=None, period_end=None, metric="operating_income", value=value, currency=currency,
        method="TEST", anchor_report_type="Q", anchor_reprt_code="11013",
        anchor_rcept_no=rcept or f"{year}{period}{available}", anchor_rcept_dt=available,
        fs_div_used=basis, pit_available_from=available, resolution_status=status,
    )


def filing(year, code, rcept_dt):
    return {"bsns_year": str(year), "reprt_code": code, "rcept_dt": rcept_dt}


FILINGS = [
    filing(2021, "11013", "2021-05-14"), filing(2021, "11012", "2021-08-13"),
    filing(2021, "11014", "2021-11-12"), filing(2021, "11011", "2022-03-18"),
    filing(2022, "11013", "2022-05-13"),
]


def run(current, prior, *, as_of="2022-05-31", filings=FILINGS, extra=()):
    observations = [obs(2022, "Q1", current, available="2022-05-13"),
                    obs(2021, "Q1", prior, available="2021-05-14"), *extra]
    return evaluate_signal(company_family="NON_FINANCIAL", filings=filings, observations=observations, as_of=as_of)


def test_latest_quarter_is_by_fiscal_period_not_receipt():
    rows = FILINGS + [filing(2021, "11013", "2022-05-20")]  # late correction of an old quarter
    latest = latest_disclosed_quarter(rows, as_of="2022-05-31")
    assert latest.label == "2022Q1"
    assert latest_disclosed_quarter(rows, as_of="2022-05-12").label == "2021Q4"


def test_boundary_two_billion_and_one_percent_pass():
    result = run(2 * B, 2 * B * 100 // 101)
    assert result.status == PASS and result.rule_branch == "A_PRIOR_POSITIVE_YOY"


def test_below_one_percent_fails():
    result = run(2 * B, 2 * B - 1)
    assert result.status == FAIL and "YOY_BELOW_1PCT" in result.fail_reasons


def test_below_two_billion_fails_even_with_growth():
    result = run(2 * B - 1, B)
    assert result.status == FAIL and result.reason == "CURRENT_BELOW_2B"


def test_prior_loss_uses_turnaround_branch_without_yoy():
    result = run(2 * B, -5 * B)
    assert result.status == PASS and result.rule_branch == "B_PRIOR_ZERO_OR_LOSS" and result.yoy_pct is None
    assert run(2 * B, 0).status == PASS


def test_current_loss_fails():
    result = run(-B, -5 * B)
    assert result.status == FAIL and "CURRENT_OPERATING_LOSS" in result.fail_reasons


def test_no_fallback_to_older_quarter_when_latest_missing():
    observations = [obs(2021, "Q4", 9 * B, available="2022-03-18"), obs(2020, "Q4", B, available="2021-03-18")]
    result = evaluate_signal(company_family="NON_FINANCIAL", filings=FILINGS, observations=observations, as_of="2022-05-31")
    assert result.status == UNAVAILABLE and result.latest_quarter == "2022Q1"
    assert result.reason.startswith("CURRENT_QUARTER_")


def test_latest_non_ready_vintage_is_not_looked_through():
    extra = [obs(2022, "Q1", None, available="2022-05-20", status=DATA_UNAVAILABLE, rcept="fix")]
    result = run(5 * B, B, extra=extra)
    assert result.status == UNAVAILABLE and result.reason == f"CURRENT_QUARTER_{DATA_UNAVAILABLE}"


def test_future_disclosure_is_invisible():
    result = run(5 * B, B, as_of="2022-05-12")
    assert result.latest_quarter == "2021Q4" and result.status == UNAVAILABLE


def test_basis_mismatch_is_separate_bucket():
    observations = [obs(2022, "Q1", 5 * B, available="2022-05-13", basis="CFS"),
                    obs(2021, "Q1", B, available="2021-05-14", basis="OFS")]
    result = evaluate_signal(company_family="NON_FINANCIAL", filings=FILINGS, observations=observations, as_of="2022-05-31")
    assert result.status == BASIS_OR_CURRENCY_MISMATCH


def test_financial_and_known_gap_are_unavailable():
    assert evaluate_signal(company_family="FINANCIAL", filings=FILINGS, observations=[], as_of="2022-05-31").reason == "FINANCIAL_NOT_APPLICABLE"
    gap = evaluate_signal(company_family="NON_FINANCIAL", filings=None, observations=[], as_of="2022-05-31",
                          unavailable_reason="REGISTRY_CACHE_UNAVAILABLE_X")
    assert gap.status == UNAVAILABLE and gap.reason == "REGISTRY_CACHE_UNAVAILABLE_X"


def test_rule_function_exact_integer_boundary():
    assert operating_income_rule(2_020_000_000, 2_000_000_000)[0]
    assert not operating_income_rule(2_019_999_999, 2_000_000_000)[0]
