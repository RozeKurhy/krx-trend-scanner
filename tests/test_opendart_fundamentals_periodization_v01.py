from __future__ import annotations

import io
import zipfile

from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.models import RawXbrlArtifact
from trend_scanner.fundamentals.period_models import (
    BASIS_MISMATCH,
    CUMULATIVE_YTD,
    DATA_UNAVAILABLE,
    DERIVATION_UNAVAILABLE,
    DIRECT_DERIVED_MISMATCH,
    INSTANT,
    PERIOD_AMBIGUOUS,
    PERIODIZATION_UNSUPPORTED,
    STANDALONE_QUARTER,
    PeriodizationFact,
)
from trend_scanner.fundamentals.periodization import PeriodizationEngine, facts_from_xbrl_rows
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


def fact(metric, code, rcept_no, rcept_dt, value, start, end, *, semantic=CUMULATIVE_YTD,
         fiscal_year="2025", fiscal_start="2025-01-01", currency="KRW", fs="CFS",
         family=CompanyFamily.NON_FINANCIAL.value, duration_days=None, comparative=False,
         resolution_status="RESOLVED"):
    return PeriodizationFact(
        ticker="237690", corp_code="00871833", company_family=family, fiscal_year=fiscal_year,
        fiscal_year_start=fiscal_start, metric=metric, value=value, currency=currency,
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], rcept_no=rcept_no,
        rcept_dt=rcept_dt, period_start=start, period_end=end, fs_div_used=fs,
        source_sha256=f"sha-{rcept_no}", resolution_status=resolution_status,
        period_semantics=semantic, duration_days=duration_days,
        comparative=comparative, pit_available_from=rcept_dt,
    )


def q1(metric="revenue", value=40, *, receipt="2025-05-15", **kwargs):
    return fact(metric, "11013", kwargs.pop("rcept_no", "Q1"), receipt, value,
                "2025-01-01", "2025-03-31", **kwargs)


def h1(metric="revenue", value=100, *, receipt="2025-08-14", **kwargs):
    return fact(metric, "11012", kwargs.pop("rcept_no", "H1"), receipt, value,
                "2025-01-01", "2025-06-30", **kwargs)


def h1_direct(metric="revenue", value=60, *, receipt="2025-08-14", **kwargs):
    return fact(metric, "11012", kwargs.pop("rcept_no", "H1"), receipt, value,
                "2025-04-01", "2025-06-30", semantic=STANDALONE_QUARTER, **kwargs)


def q3(metric="revenue", value=130, *, receipt="2025-11-14", **kwargs):
    return fact(metric, "11014", kwargs.pop("rcept_no", "Q3"), receipt, value,
                "2025-01-01", "2025-09-30", **kwargs)


def q3_direct(metric="revenue", value=30, *, receipt="2025-11-14", **kwargs):
    return fact(metric, "11014", kwargs.pop("rcept_no", "Q3"), receipt, value,
                "2025-07-01", "2025-09-30", semantic=STANDALONE_QUARTER, **kwargs)


def annual(metric="revenue", value=180, *, receipt="2026-03-18", **kwargs):
    return fact(metric, "11011", kwargs.pop("rcept_no", "FY"), receipt, value,
                "2025-01-01", "2025-12-31", **kwargs)


def _obs(result, period, metric="revenue"):
    return next(item for item in result.observations if item.fiscal_period == period and item.metric == metric)


def test_q1_cumulative_has_equivalent_standalone_without_fabrication():
    result = PeriodizationEngine().periodize([q1()])
    assert _obs(result, "Q1_YTD").period_semantics == CUMULATIVE_YTD
    q1_standalone = _obs(result, "Q1")
    assert q1_standalone.value == 40
    assert q1_standalone.method == "DIRECT_EQUIVALENT_YTD"


def test_h1_direct_q2_is_validated_by_cumulative_difference():
    result = PeriodizationEngine().periodize([q1(), h1(), h1_direct()])
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert q2.method == "DIRECT_VALIDATED_BY_DERIVATION"
    assert result.parity[0].status == "MATCH"


def test_h1_cumulative_difference_creates_q2_when_direct_missing():
    result = PeriodizationEngine().periodize([q1(), h1()])
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert q2.method == "DERIVED_DIFFERENCE"
    assert q2.source_rcept_nos == ("H1", "Q1")


def test_q3_direct_and_cumulative_are_separated_and_validated():
    result = PeriodizationEngine().periodize([q1(), h1(), q3(), q3_direct()])
    q3_value = _obs(result, "Q3")
    assert q3_value.value == 30
    assert q3_value.method == "DIRECT_VALIDATED_BY_DERIVATION"


def test_q3_derived_difference_is_supported():
    result = PeriodizationEngine().periodize([q1(), h1(), q3()])
    assert _obs(result, "Q3").value == 30
    assert _obs(result, "Q3").method == "DERIVED_DIFFERENCE"


def test_q4_is_annual_minus_9m_and_fy_authority_stays_direct():
    result = PeriodizationEngine().periodize([q1(), h1(), q3(), annual()])
    assert _obs(result, "Q4").value == 50
    assert _obs(result, "Q4").method == "DERIVED_DIFFERENCE"
    assert _obs(result, "FY").value == 180
    assert _obs(result, "FY").method == "DIRECT_FULL_YEAR"


def test_ocf_cumulative_only_is_normal():
    result = PeriodizationEngine().periodize([
        q1("operating_cash_flow", 50), h1("operating_cash_flow", 120)
    ])
    q2 = _obs(result, "Q2", "operating_cash_flow")
    assert q2.value == 70
    assert q2.method == "DERIVED_DIFFERENCE"
    assert not any(item.fiscal_period == "Q2" and item.method == "DIRECT_ONLY"
                   for item in result.observations)


def test_instant_metrics_are_snapshots_not_subtractions():
    result = PeriodizationEngine().periodize([
        fact("assets", "11013", "Q1", "2025-05-15", 100, None, "2025-03-31", semantic=INSTANT, fiscal_start="2025-01-01"),
        fact("assets", "11012", "H1", "2025-08-14", 110, None, "2025-06-30", semantic=INSTANT, fiscal_start="2025-01-01"),
    ])
    assert {item.fiscal_period for item in result.observations} == {"Q1_END", "H1_END"}
    assert all(item.period_semantics == INSTANT for item in result.observations)
    assert all(item.value in {100, 110} for item in result.observations)


def test_currency_mismatch_blocks_derivation():
    result = PeriodizationEngine().periodize([q1(currency="KRW"), h1(currency="USD")])
    q2 = _obs(result, "Q2")
    assert q2.resolution_status == DERIVATION_UNAVAILABLE
    assert q2.reason == "CURRENCY_MISMATCH"


def test_basis_mismatch_blocks_derivation():
    result = PeriodizationEngine().periodize([q1(fs="CFS"), h1(fs="OFS")])
    q2 = _obs(result, "Q2")
    assert q2.resolution_status == DERIVATION_UNAVAILABLE
    assert q2.reason == BASIS_MISMATCH


def test_fiscal_start_mismatch_blocks_derivation():
    result = PeriodizationEngine().periodize([
        q1(fiscal_start="2025-01-01"), h1(fiscal_start="2025-02-01")
    ])
    assert _obs(result, "Q2").resolution_status == DERIVATION_UNAVAILABLE


def test_missing_source_is_not_converted_to_zero():
    result = PeriodizationEngine().periodize([q1(value=None), h1(value=100)])
    q1_ytd = _obs(result, "Q1_YTD")
    q2 = _obs(result, "Q2")
    assert q1_ytd.value is None and q1_ytd.resolution_status == DATA_UNAVAILABLE
    assert q2.value is None


def test_direct_derived_mismatch_fails_closed_without_silent_selection():
    result = PeriodizationEngine().periodize([q1(), h1(), h1_direct(value=61)])
    q2 = _obs(result, "Q2")
    assert q2.value is None
    assert q2.resolution_status == DIRECT_DERIVED_MISMATCH
    assert result.parity[0].difference == 1


def test_comparative_context_is_excluded():
    result = PeriodizationEngine().periodize([q1(), h1(), q3(comparative=True)])
    assert not any(item.anchor_reprt_code == "11014" for item in result.observations)


def test_ambiguous_duplicate_current_context_fails_closed():
    result = PeriodizationEngine().periodize([q1(), h1(), h1(value=101, rcept_no="H1")])
    q2 = _obs(result, "Q2")
    assert q2.resolution_status == PERIOD_AMBIGUOUS


def test_non_calendar_fiscal_year_uses_actual_context_dates():
    rows = [
        fact("revenue", "11013", "Q1", "2025-02-15", 40, "2024-10-01", "2024-12-31",
             fiscal_year="2024", fiscal_start="2024-10-01"),
        fact("revenue", "11012", "H1", "2025-05-15", 100, "2024-10-01", "2025-03-31",
             fiscal_year="2024", fiscal_start="2024-10-01"),
    ]
    result = PeriodizationEngine().periodize(rows)
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert q2.period_end == "2025-03-31"
    assert q2.fiscal_year == "2024"


def test_stub_fiscal_period_fails_closed():
    result = PeriodizationEngine().periodize([
        fact("revenue", "11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-04-30",
             duration_days=120)
    ])
    assert any(item.resolution_status == PERIODIZATION_UNSUPPORTED for item in result.observations)


def test_q2_missing_before_h1_filing_is_unavailable():
    result = PeriodizationEngine().periodize([q1(), h1()], as_of="2025-08-13")
    assert not any(item.fiscal_period == "Q2" for item in result.observations)


def test_q2_same_day_h1_filing_is_available():
    result = PeriodizationEngine().periodize([q1(), h1()], as_of="2025-08-14")
    assert _obs(result, "Q2").value == 60


def test_q3_same_day_filing_is_available():
    result = PeriodizationEngine().periodize([q1(), h1(), q3()], as_of="2025-11-14")
    assert _obs(result, "Q3").value == 30


def test_annual_same_day_filing_is_available():
    result = PeriodizationEngine().periodize([q1(), h1(), q3(), annual()], as_of="2026-03-18")
    assert _obs(result, "Q4").value == 50


def test_future_q1_correction_does_not_leak_into_h1_anchor():
    rows = [q1(value=40, rcept_no="Q1_ORIGINAL"),
            q1(value=45, receipt="2025-10-01", rcept_no="Q1_CORRECTION"), h1()]
    result = PeriodizationEngine().periodize(rows)
    q2 = _obs(result, "Q2")
    assert q2.value == 60
    assert "Q1_ORIGINAL" in q2.source_rcept_nos
    assert "Q1_CORRECTION" not in q2.source_rcept_nos


def test_late_q3_correction_does_not_rewrite_old_annual_q4():
    rows = [q1(), h1(), q3(value=130, rcept_no="Q3_ORIGINAL"),
            q3(value=140, receipt="2026-05-01", rcept_no="Q3_CORRECTION"), annual()]
    result = PeriodizationEngine().periodize(rows)
    q4 = _obs(result, "Q4")
    assert q4.value == 50
    assert q4.source_rcept_nos[1] == "Q3_ORIGINAL"


def test_anchor_correction_creates_new_periodized_version():
    rows = [q1(), h1(value=100, rcept_no="H1_ORIGINAL"),
            h1(value=105, receipt="2025-10-01", rcept_no="H1_CORRECTION")]
    result = PeriodizationEngine().periodize(rows)
    q2 = [item for item in result.observations if item.fiscal_period == "Q2"]
    assert {item.anchor_rcept_no for item in q2} == {"H1_ORIGINAL", "H1_CORRECTION"}
    assert {item.value for item in q2} == {60, 65}


def test_negative_standalone_value_is_valid():
    result = PeriodizationEngine().periodize([q1(value=50), h1(value=20)])
    assert _obs(result, "Q2").value == -30
    assert _obs(result, "Q2").resolution_status == "READY"


def test_partial_year_allows_direct_q2_without_q1():
    result = PeriodizationEngine().periodize([h1_direct(value=60)])
    q2 = _obs(result, "Q2")
    assert q2.value == 60 and q2.method == "DIRECT_ONLY"


def test_financial_family_nonfinancial_metrics_not_applicable():
    result = PeriodizationEngine().periodize([
        q1(family=CompanyFamily.FINANCIAL.value), h1(family=CompanyFamily.FINANCIAL.value)
    ])
    assert all(item.resolution_status == "NOT_APPLICABLE" for item in result.observations)


def test_unknown_family_fails_closed():
    result = PeriodizationEngine().periodize([q1(family=CompanyFamily.UNKNOWN.value)])
    assert result.observations == ()
    assert result.diagnostics[0]["reason"] == "COMPANY_FAMILY_UNKNOWN"


def test_annual_quarter_sum_diagnostic_is_separate_from_authority():
    result = PeriodizationEngine().periodize([
        q1(value=40), h1(value=100), q3(value=130), annual(value=180)
    ])
    diagnostic = next(item for item in result.diagnostics if item.get("metric") == "revenue"
                      and "quarter_sum" in item)
    assert diagnostic["quarter_sum"] == 180
    assert diagnostic["annual_value"] == 180
    assert diagnostic["status"] == "MATCH"


def test_xbrl_context_extraction_keeps_actual_non_calendar_period_and_comparative_flag(tmp_path):
    xbrl = """<?xml version='1.0'?>
<xbrl xmlns='http://www.xbrl.org/2003/instance'
 xmlns:ifrs-full='http://xbrl.ifrs.org/taxonomy/2021-03-24/ifrs-full'
 xmlns:xbrldi='http://xbrl.org/2006/xbrldi'>
<context id='current'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:ConsolidatedMember</xbrldi:explicitMember></segment></entity><period><startDate>2024-10-01</startDate><endDate>2024-12-31</endDate></period></context>
<context id='comparative'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:ConsolidatedMember</xbrldi:explicitMember></segment></entity><period><startDate>2023-10-01</startDate><endDate>2023-12-31</endDate></period></context>
<context id='instant'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:ConsolidatedMember</xbrldi:explicitMember></segment></entity><period><instant>2024-12-31</instant></period></context>
<ifrs-full:Revenue contextRef='current' unitRef='KRW'>40</ifrs-full:Revenue>
<ifrs-full:Revenue contextRef='comparative' unitRef='KRW'>35</ifrs-full:Revenue>
<ifrs-full:Assets contextRef='instant' unitRef='KRW'>100</ifrs-full:Assets>
</xbrl>"""
    raw_buffer = io.BytesIO()
    with zipfile.ZipFile(raw_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("entity.xbrl", xbrl)
    raw = raw_buffer.getvalue()
    repo = XbrlRepository(cache_dir=tmp_path)
    filing = type("Filing", (), {"rcept_no": "Q1", "reprt_code": "11013"})()
    zip_path, _ = repo._paths(filing.rcept_no, filing.reprt_code)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(raw)
    artifact = RawXbrlArtifact(
        corp_code="00871833", ticker="237690", rcept_no="Q1", reprt_code="11013", rcept_dt="20250215",
        retrieved_at="fixed", http_status=200, content_type="application/zip", byte_length=len(raw),
        sha256="fixture", member_count=1, member_names=("entity.xbrl",), source_url_redacted="redacted",
    )
    current = repo.statement_rows(artifact, bsns_year="2025", reprt_code="11013")
    assert {row["value"] for row in current} == {40, 100}
    contexts = repo.period_context_rows(artifact, bsns_year="2025", reprt_code="11013")
    revenue = [row for row in contexts if row["account_id"] == "ifrs-full_Revenue"]
    assert any(row["period_end"] == "2024-12-31" and not row["comparative"] for row in revenue)
    assert any(row["period_end"] == "2023-12-31" and row["comparative"] for row in revenue)
    assert all(row["duration_days"] == 92 for row in revenue)
    facts = facts_from_xbrl_rows(contexts, ticker="237690", corp_code="00871833",
                                 company_family=CompanyFamily.NON_FINANCIAL.value, fiscal_year="2024",
                                 reprt_code="11013", rcept_no="Q1", rcept_dt="2025-02-15",
                                 fs_div_used="CFS", source_sha256="fixture", fiscal_year_start="2024-10-01")
    periodized = PeriodizationEngine().periodize(facts)
    assert _obs(periodized, "Q1").value == 40
