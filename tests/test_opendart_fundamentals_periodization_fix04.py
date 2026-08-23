from __future__ import annotations

from dataclasses import dataclass

from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import PERIOD_AMBIGUOUS, READY
from trend_scanner.fundamentals.periodization import (
    PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS,
    PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider


def _filing(code: str, no: str, dt: str, *, chain: str = "chain") -> RegisteredFiling:
    return RegisteredFiling(
        ticker="005930", corp_code="00126380", corp_name="Fixture", bsns_year="2025",
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], report_nm="fixture",
        rcept_no=no, rcept_dt=dt, filing_chain_key=chain, correction_flag=no.endswith("-C"),
        source_retrieved_at="test", fs_div="CFS",
    )


@dataclass
class _Fixture:
    filings: list[RegisteredFiling]
    contexts: dict[str, list[dict]]


class _Corp:
    def get_record(self, ticker: str) -> CorpCodeRecord:
        return CorpCodeRecord("00126380", "Fixture", ticker, "20260101")


class _Registry:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture

    def list_regular_filings(self, **kwargs):
        return [row for row in self.fixture.filings if row.reprt_code == kwargs["reprt_code"]]


class _Xbrl:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture

    def fetch(self, filing, *, force_refresh=False):
        return RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at="test",
            http_status=200, content_type="application/zip", byte_length=1,
            sha256=f"sha-{filing.rcept_no}", member_count=1, member_names=("test.xbrl",),
            source_url_redacted="https://example.invalid", cache_hit=True,
        )

    def period_context_rows(self, artifact, *, bsns_year, reprt_code):
        return self.fixture.contexts.get(artifact.rcept_no, [])


def _context(code: str, value: int, *, semantic: str = "CUMULATIVE_YTD") -> dict:
    if code == "11013":
        start, end, days = "2025-01-01", "2025-03-31", 90
    elif code == "11012":
        start, end, days = ("2025-01-01", "2025-06-30", 181) if semantic == "CUMULATIVE_YTD" else ("2025-04-01", "2025-06-30", 91)
    elif code == "11014":
        start, end, days = ("2025-01-01", "2025-09-30", 273) if semantic == "CUMULATIVE_YTD" else ("2025-07-01", "2025-09-30", 92)
    else:
        start, end, days = "2025-01-01", "2025-12-31", 365
    return {
        "account_id": "ifrs-full_Revenue", "value": value, "currency": "KRW",
        "period_start": start, "period_end": end, "duration_days": days,
        "context_semantics": "DURATION", "period_semantics": semantic,
        "comparative": False, "basis": "CFS",
    }


def _provider(filings: list[RegisteredFiling], contexts: dict[str, list[dict]]) -> PeriodizationProvider:
    fixture = _Fixture(filings, contexts)
    return PeriodizationProvider(_Corp(), _Registry(fixture), _Xbrl(fixture))


def _observation(build, period: str):
    return next(item for item in build.result.observations if item.fiscal_period == period)


def _q3_filing() -> RegisteredFiling:
    return _filing("11014", "Q3", "2025-11-14")


def test_case_a_provider_ambiguous_prior_propagates_to_q3_without_missing_downgrade():
    filings = [_filing("11012", "H1-A", "2025-08-14"), _filing("11012", "H1-B", "2025-08-14"), _q3_filing()]
    build = _provider(filings, {"Q3": [_context("11014", 150)]}).build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    h1 = next(item for item in build.anchor_selections if item["reprt_code"] == "11012")
    q3_anchor = next(item for item in build.anchor_selections if item["reprt_code"] == "11014")
    q3 = _observation(build, "Q3")
    assert h1["status"] == "AMBIGUOUS"
    assert h1["candidate_rcept_nos"] == ["H1-A", "H1-B"]
    assert q3_anchor["prior_pit"]["status"] == "AMBIGUOUS"
    assert q3_anchor["prior_pit"]["reason"] == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
    assert q3_anchor["prior_pit"]["selected_rcept_no"] is None
    assert q3.resolution_status == PERIOD_AMBIGUOUS
    assert q3.reason == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
    assert build.result.parity == ()


def test_case_b_ambiguous_prior_keeps_unique_direct_q3_without_parity():
    filings = [_filing("11012", "H1-A", "2025-08-14"), _filing("11012", "H1-B", "2025-08-14"), _q3_filing()]
    build = _provider(filings, {"Q3": [_context("11014", 150), _context("11014", 50, semantic="STANDALONE_QUARTER")]}).build(
        "005930", "2025", "2025-12-31", company={"induty_code": "26"}
    )
    q3 = _observation(build, "Q3")
    assert q3.value == 50
    assert q3.method == "DIRECT_ONLY"
    assert q3.resolution_status == READY
    assert q3.source_rcept_nos == ("Q3",)
    assert build.result.parity == ()


def test_case_c_ready_prior_allows_direct_derived_validation():
    filings = [_filing("11012", "H1", "2025-08-14"), _q3_filing()]
    build = _provider(filings, {"H1": [_context("11012", 100)], "Q3": [_context("11014", 150), _context("11014", 50, semantic="STANDALONE_QUARTER")] }).build(
        "005930", "2025", "2025-12-31", company={"induty_code": "26"}
    )
    q3 = _observation(build, "Q3")
    assert q3.method == "DIRECT_VALIDATED_BY_DERIVATION"
    assert q3.resolution_status == READY
    assert len(build.result.parity) == 1
    assert build.result.parity[0].status == "MATCH"


def test_case_d_provider_retains_same_filing_context_ambiguity():
    filings = [_filing("11013", "Q1", "2025-05-15"), _filing("11012", "H1", "2025-08-14")]
    build = _provider(filings, {"Q1": [_context("11013", 40), _context("11013", 40)], "H1": [_context("11012", 100)]}).build(
        "005930", "2025", "2025-12-31", company={"induty_code": "26"}
    )
    q2 = _observation(build, "Q2")
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS
    assert build.result.parity == ()


def test_case_e_provider_retains_same_eod_filing_ambiguity():
    filings = [_filing("11013", "Q1-A", "2025-05-15"), _filing("11013", "Q1-B", "2025-05-15"), _filing("11012", "H1", "2025-08-14")]
    build = _provider(filings, {"H1": [_context("11012", 100)]}).build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q2_anchor = next(item for item in build.anchor_selections if item["reprt_code"] == "11012")
    q2 = _observation(build, "Q2")
    assert q2_anchor["prior_pit"]["status"] == "AMBIGUOUS"
    assert q2.reason == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
    assert q2.resolution_status == PERIOD_AMBIGUOUS


def test_case_f_late_correction_does_not_retroactively_resolve_prior_ambiguity():
    filings = [
        _filing("11013", "Q1-A", "2025-05-15"), _filing("11013", "Q1-B", "2025-05-15"),
        _filing("11013", "Q1-C", "2025-10-01"), _filing("11012", "H1", "2025-08-14"),
    ]
    build = _provider(filings, {"Q1-A": [_context("11013", 40)], "Q1-B": [_context("11013", 41)],
                                "Q1-C": [_context("11013", 45)], "H1": [_context("11012", 100)]}).build(
        "005930", "2025", "2025-11-01", company={"induty_code": "26"}
    )
    q1_c = next(item for item in build.result.observations if item.fiscal_period == "Q1" and item.anchor_rcept_no == "Q1-C")
    q2 = _observation(build, "Q2")
    assert q1_c.value == 45
    assert q1_c.resolution_status == READY
    assert q2.resolution_status == PERIOD_AMBIGUOUS
    assert q2.reason == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
