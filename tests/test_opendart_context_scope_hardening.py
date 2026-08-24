from __future__ import annotations

from xml.etree import ElementTree as ET

from trend_scanner.fundamentals.periodization import collapse_canonical_duplicate_periodization_facts, facts_from_xbrl_rows
from trend_scanner.fundamentals.period_models import PeriodizationFact
from trend_scanner.fundamentals.xbrl_repository import _context_info


def _context(body: str, *, context_id: str = "A") -> dict:
    return _context_info(ET.fromstring(f'<context id="{context_id}">{body}</context>'))


def _fact(**changes) -> PeriodizationFact:
    values = {
        "ticker": "005930", "corp_code": "00126380", "company_family": "NON_FINANCIAL",
        "fiscal_year": "2025", "fiscal_year_start": "2025-01-01", "metric": "revenue", "value": 100,
        "currency": "KRW", "reprt_code": "11013", "report_type": "Q1", "rcept_no": "R1",
        "rcept_dt": "2025-05-15", "period_start": "2025-01-01", "period_end": "2025-03-31",
        "fs_div_used": "CFS", "source_sha256": "sha", "period_semantics": "CUMULATIVE_YTD",
        "context_semantics": "DURATION", "duration_days": 90, "pit_available_from": "2025-05-15",
        "context_scope_fingerprint": "scope-a",
    }
    values.update(changes)
    return PeriodizationFact(**values)


def test_context_id_is_not_fingerprint_authority():
    left = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember></scenario>', context_id="FQA")
    right = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember></scenario>', context_id="FQQ")
    assert left["context_scope_fingerprint"] == right["context_scope_fingerprint"]


def test_non_basis_explicit_dimension_changes_scope_and_primary():
    plain = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember></scenario>')
    segment = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember><explicitMember dimension="dart:OperatingSegmentsAxis">dart:SemiconductorMember</explicitMember></scenario>')
    assert plain["context_scope_fingerprint"] != segment["context_scope_fingerprint"]
    assert plain["primary"] is True
    assert segment["primary"] is False
    assert segment["context_has_additional_dimensions"] is True


def test_typed_dimension_changes_scope_and_is_not_primary():
    left = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember><typedMember dimension="dart:CustomerAxis"><Customer>A</Customer></typedMember></scenario>')
    right = _context('<entity><identifier scheme="dart">001</identifier></entity><period><startDate>2025-01-01</startDate><endDate>2025-03-31</endDate></period><scenario><explicitMember dimension="dart:ConsolidatedAndSeparateFinancialStatementsAxis">dart:ConsolidatedMember</explicitMember><typedMember dimension="dart:CustomerAxis"><Customer>B</Customer></typedMember></scenario>')
    assert left["context_scope_fingerprint"] != right["context_scope_fingerprint"]
    assert left["primary"] is False and right["primary"] is False
    assert left["context_has_typed_dimensions"] is True


def test_entity_identity_changes_scope():
    left = _context('<entity><identifier scheme="dart">001</identifier></entity><period><instant>2025-03-31</instant></period>')
    right = _context('<entity><identifier scheme="dart">002</identifier></entity><period><instant>2025-03-31</instant></period>')
    assert left["context_scope_fingerprint"] != right["context_scope_fingerprint"]


def test_basis_only_context_is_primary():
    info = _context('<entity><identifier scheme="dart">001</identifier></entity><period><instant>2025-03-31</instant></period><scenario><explicitMember dimension="dart:StatementInformationAxis">dart:ConsolidatedMember</explicitMember></scenario>')
    assert info["basis"] == "ConsolidatedMember"
    assert info["primary"] is True


def test_different_scope_same_value_is_not_collapsed():
    assert len(collapse_canonical_duplicate_periodization_facts((_fact(), _fact(context_scope_fingerprint="scope-b")))) == 2


def test_production_adapter_preserves_scope_fingerprint_and_flags():
    rows = [{
        "account_id": "ifrs-full_Revenue", "value": 100, "currency": "KRW", "period_start": "2025-01-01",
        "period_end": "2025-03-31", "duration_days": 90, "context_semantics": "DURATION",
        "context_scope_fingerprint": "scope-a", "context_has_additional_dimensions": False,
        "context_has_typed_dimensions": False, "comparative": False,
    }]
    facts = facts_from_xbrl_rows(rows, ticker="005930", corp_code="00126380", company_family="NON_FINANCIAL",
                                 fiscal_year="2025", reprt_code="11013", rcept_no="R1", rcept_dt="2025-05-15",
                                 fs_div_used="CFS", source_sha256="sha")
    assert facts[0].context_scope_fingerprint == "scope-a"
    assert facts[0].context_has_additional_dimensions is False
    assert facts[0].context_has_typed_dimensions is False
