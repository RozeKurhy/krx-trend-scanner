from __future__ import annotations

from trend_scanner.fundamentals.periodization import (
    ACCOUNT_TO_METRIC,
    CUMULATIVE_YTD,
    PERIOD_AMBIGUOUS,
    READY,
    collapse_canonical_duplicate_periodization_facts,
    facts_from_xbrl_rows,
    periodize_facts,
)
from trend_scanner.fundamentals.period_models import PeriodizationFact


def _fact(**changes) -> PeriodizationFact:
    values = {
        "ticker": "005380", "corp_code": "00164779", "company_family": "NON_FINANCIAL",
        "fiscal_year": "2025", "fiscal_year_start": "2025-01-01", "metric": "operating_income",
        "value": 100, "currency": "KRW", "reprt_code": "11013", "report_type": "Q1",
        "rcept_no": "R-20250515", "rcept_dt": "2025-05-15", "period_start": "2025-01-01",
        "period_end": "2025-03-31", "fs_div_used": "CFS", "source_sha256": "sha-q1",
        "resolution_status": "RESOLVED", "period_semantics": CUMULATIVE_YTD,
        "context_semantics": "DURATION", "duration_days": 90, "instant": None,
        "comparative": False, "pit_available_from": "2025-05-15",
    }
    values.update(changes)
    return PeriodizationFact(**values)


def test_identical_canonical_facts_collapse_to_one():
    stats = {}
    result = collapse_canonical_duplicate_periodization_facts((_fact(), _fact()), stats=stats)
    assert len(result) == 1
    assert stats == {"input_fact_count": 2, "output_fact_count": 1, "group_count": 1, "removed_fact_count": 1}


def test_raw_concept_aliases_collapse_after_canonical_mapping():
    rows = [
        {"account_id": "dart_OperatingIncomeLoss", "value": 100, "currency": "KRW",
         "basis": "CFS", "period_start": "2025-01-01", "period_end": "2025-03-31",
         "duration_days": 90, "context_semantics": "DURATION", "comparative": False},
        {"account_id": "ifrs-full_ProfitLossFromOperatingActivities", "value": 100, "currency": "KRW",
         "basis": "CFS", "period_start": "2025-01-01", "period_end": "2025-03-31",
         "duration_days": 90, "context_semantics": "DURATION", "comparative": False},
    ]
    result = facts_from_xbrl_rows(
        rows, ticker="005380", corp_code="00164779", company_family="NON_FINANCIAL",
        fiscal_year="2025", reprt_code="11013", report_type="Q1", rcept_no="R-20250515",
        rcept_dt="2025-05-15", fs_div_used="CFS", source_sha256="sha-q1",
    )
    assert ACCOUNT_TO_METRIC["dart_OperatingIncomeLoss"] == ACCOUNT_TO_METRIC["ifrs-full_ProfitLossFromOperatingActivities"]
    assert len(result) == 1
    assert result[0].metric == "operating_income"


def test_different_values_remain_ambiguous():
    facts = (_fact(value=100), _fact(value=101))
    assert len(collapse_canonical_duplicate_periodization_facts(facts)) == 2
    result = periodize_facts(facts)
    assert any(item.resolution_status == PERIOD_AMBIGUOUS for item in result.observations)


def test_different_currency_period_basis_receipt_source_and_comparative_remain_separate():
    for changes in (
        {"currency": "USD"}, {"period_end": "2025-03-30"}, {"fs_div_used": "OFS"},
        {"rcept_no": "R-OTHER"}, {"source_sha256": "other-sha"}, {"comparative": True},
    ):
        assert len(collapse_canonical_duplicate_periodization_facts((_fact(), _fact(**changes)))) == 2


def test_canonical_duplicate_is_ready_after_collapse_but_value_conflict_is_not():
    ready = periodize_facts(collapse_canonical_duplicate_periodization_facts((_fact(), _fact())))
    assert any(item.resolution_status == READY and item.fiscal_period == "Q1" for item in ready.observations)
    blocked = periodize_facts((_fact(), _fact(value=101)))
    assert any(item.resolution_status == PERIOD_AMBIGUOUS and item.fiscal_period == "Q1" for item in blocked.observations)
