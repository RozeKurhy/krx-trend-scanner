from __future__ import annotations

from dataclasses import replace

from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, PERIOD_AMBIGUOUS, READY, PeriodizationFact
from trend_scanner.fundamentals.periodization import PeriodizationEngine
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider


def fact(code: str, no: str, dt: str, value: int) -> PeriodizationFact:
    ends = {"11013": "2025-03-31", "11012": "2025-06-30"}
    return PeriodizationFact(
        ticker="237690", corp_code="00871833", company_family=CompanyFamily.NON_FINANCIAL.value,
        fiscal_year="2025", fiscal_year_start="2025-01-01", metric="revenue", value=value,
        currency="KRW", reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], rcept_no=no,
        rcept_dt=dt, period_start="2025-01-01", period_end=ends[code], fs_div_used="CFS",
        source_sha256=f"sha-{no}", period_semantics=CUMULATIVE_YTD, pit_available_from=dt,
    )


def test_prior_same_eod_ambiguity_fails_closed_without_lexical_winner():
    result = PeriodizationEngine().periodize([
        fact("11013", "Q1-A", "2025-05-15", 40),
        fact("11013", "Q1-B", "2025-05-15", 41),
        fact("11012", "H1", "2025-08-14", 100),
    ], as_of="2025-08-14")
    q2 = next(item for item in result.observations if item.fiscal_period == "Q2")
    assert q2.value is None
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD"
    assert q2.source_rcept_nos == ("H1",)
    assert q2.source_rcept_dts == ("2025-08-14",)


def test_late_correction_does_not_resolve_an_earlier_same_eod_ambiguity():
    result = PeriodizationEngine().periodize([
        fact("11013", "Q1-A", "2025-05-15", 40),
        fact("11013", "Q1-B", "2025-05-15", 41),
        fact("11013", "Q1-C", "2025-10-01", 45),
        fact("11012", "H1", "2025-08-14", 100),
    ], as_of="2025-11-01")
    q1_c = next(item for item in result.observations
                if item.fiscal_period == "Q1" and item.anchor_rcept_no == "Q1-C")
    q2 = next(item for item in result.observations if item.fiscal_period == "Q2")
    assert q1_c.value == 45
    assert q2.value is None
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD"


def test_derived_source_receipt_dates_align_with_rcept_numbers_and_hashes():
    result = PeriodizationEngine().periodize([
        fact("11013", "Q1", "2025-05-15", 40),
        fact("11012", "H1", "2025-08-14", 100),
    ])
    q2 = next(item for item in result.observations if item.fiscal_period == "Q2")
    assert q2.resolution_status == READY
    assert q2.source_rcept_nos == ("H1", "Q1")
    assert q2.source_rcept_dts == ("2025-08-14", "2025-05-15")
    assert q2.source_sha256s == ("sha-H1", "sha-Q1")
    assert len(q2.source_rcept_nos) == len(q2.source_rcept_dts) == len(q2.source_sha256s)


class _Corp:
    def get_record(self, ticker: str) -> CorpCodeRecord:
        return CorpCodeRecord("00871833", "ST Pharm", ticker, "20260101")


class _Registry:
    def __init__(self, rows):
        self.rows = rows

    def list_regular_filings(self, **kwargs):
        return [item for item in self.rows if item.reprt_code == kwargs["reprt_code"]]


class _Xbrl:
    def fetch(self, filing, *, force_refresh=False):
        return RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at="test",
            http_status=200, content_type="application/zip", byte_length=1,
            sha256=f"sha-{filing.rcept_no}", member_count=1, member_names=("test.xbrl",),
            source_url_redacted="https://example.invalid", cache_hit=True,
        )

    def period_context_rows(self, artifact, *, bsns_year, reprt_code):
        start, end = (("2025-01-01", "2025-03-31") if reprt_code == "11013"
                      else ("2025-01-01", "2025-06-30"))
        value = {"Q1-A": 40, "Q1-B": 41, "Q1-C": 45, "H1": 100}[artifact.rcept_no]
        return [{"account_id": "ifrs-full_Revenue", "value": value, "currency": "KRW",
                 "period_start": start, "period_end": end, "duration_days": 90 if reprt_code == "11013" else 181,
                 "context_semantics": "DURATION", "comparative": False, "basis": "ConsolidatedMember"}]


def _filing(code, no, dt, chain):
    return RegisteredFiling(
        ticker="237690", corp_code="00871833", corp_name="ST Pharm", bsns_year="2025",
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], report_nm="2025 보고서",
        rcept_no=no, rcept_dt=dt, filing_chain_key=chain, correction_flag=no == "Q1-C",
        source_retrieved_at="test", fs_div="CFS",
    )


def test_provider_prior_pit_ambiguity_matches_engine_result():
    rows = [
        _filing("11013", "Q1-A", "2025-05-15", "q1-chain"),
        _filing("11013", "Q1-B", "2025-05-15", "q1-chain"),
        _filing("11013", "Q1-C", "2025-10-01", "q1-chain"),
        _filing("11012", "H1", "2025-08-14", "h1-chain"),
    ]
    provider = PeriodizationProvider(_Corp(), _Registry(rows), _Xbrl())
    built = provider.build("237690", "2025", "2025-11-01", company={"induty_code": "30"})
    h1 = next(item for item in built.anchor_selections if item["reprt_code"] == "11012")
    q2 = next(item for item in built.result.observations if item.fiscal_period == "Q2")
    assert h1["prior_pit"]["status"] == "AMBIGUOUS"
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.value is None
