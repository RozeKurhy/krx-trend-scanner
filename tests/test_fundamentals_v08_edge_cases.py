from __future__ import annotations

from trend_scanner.fundamentals.multi_period import build_multi_period_result
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family
from trend_scanner.fundamentals.period_models import PeriodizationFact, PeriodizedFinancialObservation, READY
from trend_scanner.fundamentals.periodization import (
    PeriodizationEngine,
    collapse_canonical_duplicate_periodization_facts,
    facts_from_xbrl_rows,
)


def test_general_holding_company_does_not_inherit_financial_industry_code():
    result = classify_company_family({
        "selected_fields": {
            "corp_code": "001040",
            "induty_code": "64992",
            "corp_name": "CJ",
            "stock_name": "CJ",
        }
    })
    assert result["company_family"] == CompanyFamily.NON_FINANCIAL.value


def test_general_holding_name_is_non_financial_but_financial_holding_is_financial():
    assert classify_company_family({"induty_code": "64992", "corp_name": "동아쏘시오홀딩스"})[
        "company_family"
    ] == CompanyFamily.NON_FINANCIAL.value
    assert classify_company_family({"induty_code": "64992", "corp_name": "하나금융지주"})[
        "company_family"
    ] == CompanyFamily.FINANCIAL.value


def _fact(account_id: str, value: int, *, comparative: bool = False, fiscal_year: str = "2025", **changes):
    values = dict(
        ticker="000120", corp_code="001040", company_family="NON_FINANCIAL",
        fiscal_year=fiscal_year, fiscal_year_start=f"{fiscal_year}-01-01",
        metric="operating_income", value=value, currency="KRW", reprt_code="11013",
        report_type="Q1", rcept_no="20250515000001", rcept_dt="2025-05-15",
        period_start=f"{fiscal_year}-01-01", period_end=f"{fiscal_year}-03-31",
        fs_div_used="CFS", source_sha256="source", period_semantics="CUMULATIVE_YTD",
        context_semantics="CURRENT", duration_days=90, comparative=comparative,
        pit_available_from="2025-05-15", context_scope_fingerprint="scope",
        account_id=account_id, raw_value=str(value), decimals="0", precision="0",
    )
    values.update(changes)
    return PeriodizationFact(**values)


def test_same_scope_operating_income_aliases_collapse_with_declared_precision_overlap():
    stats: dict[str, int] = {}
    facts = collapse_canonical_duplicate_periodization_facts(
        (_fact("ifrs-full_ProfitLossFromOperatingActivities", 85366748000, decimals="-3", precision=None),
         _fact("dart_OperatingIncomeLoss", 85366748157, decimals="-1", precision=None)),
        stats=stats,
    )
    assert len(facts) == 1
    assert facts[0].account_id == "dart_OperatingIncomeLoss"
    assert stats["precision_equivalent_fact_removed_count"] == 1


def test_declared_precision_non_overlap_does_not_collapse():
    facts = collapse_canonical_duplicate_periodization_facts(
        (_fact("ifrs-full_ProfitLossFromOperatingActivities", 100, decimals="0", precision=None),
         _fact("dart_OperatingIncomeLoss", 101, decimals="0", precision=None)),
    )
    assert len(facts) == 2


def test_comparative_rows_are_rekeyed_only_in_opt_in_provider_mode():
    rows = [{
        "account_id": "ifrs-full_Revenue", "value": 100,
        "period_start": "2024-01-01", "period_end": "2024-12-31",
        "comparative": True, "context_semantics": "COMPARATIVE",
        "context_scope_fingerprint": "scope", "duration_days": 366,
    }]
    facts = facts_from_xbrl_rows(
        rows, ticker="000700", corp_code="000700", company_family="NON_FINANCIAL",
        fiscal_year="2025", reprt_code="11011", report_type="ANNUAL",
        rcept_no="20260321000001", rcept_dt="2026-03-21", fs_div_used="CFS",
        source_sha256="source",
    )
    assert facts[0].fiscal_year == "2024"
    assert len(PeriodizationEngine().periodize(facts)) == 0
    result = PeriodizationEngine().periodize(facts, include_comparative_presentations=True)
    assert any(item.fiscal_period == "FY" and item.value == 100 for item in result.observations)


def _observation(value: int, available: str) -> PeriodizedFinancialObservation:
    return PeriodizedFinancialObservation(
        ticker="000700", corp_code="000700", company_family="NON_FINANCIAL",
        fiscal_year="2023", fiscal_year_start="2023-01-01", fiscal_period="FY",
        period_semantics="CUMULATIVE_YTD", period_start="2023-01-01", period_end="2023-12-31",
        metric="operating_income", value=value, currency="KRW", method="DIRECT_FULL_YEAR",
        anchor_report_type="ANNUAL", anchor_reprt_code="11011", anchor_rcept_no=available + "01",
        anchor_rcept_dt=available, pit_available_from=available, resolution_status=READY,
    )


def test_current_snapshot_uses_eligible_represented_comparative_but_historical_snapshot_does_not_leak():
    old = _observation(21005544102, "2024-03-20")
    restated = _observation(21985188591, "2025-03-21")
    current = build_multi_period_result(
        ticker="000700", requested_as_of="2026-09-04",
        observations=(old, restated), company_family="NON_FINANCIAL", corp_code="000700",
    )
    historical = build_multi_period_result(
        ticker="000700", requested_as_of="2024-12-31",
        observations=(old, restated), company_family="NON_FINANCIAL", corp_code="000700",
    )
    assert [item.value for item in current.annuals if item.metric == "operating_income"] == [21985188591]
    assert [item.value for item in historical.annuals if item.metric == "operating_income"] == [21005544102]
