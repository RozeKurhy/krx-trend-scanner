from __future__ import annotations

from dataclasses import dataclass

from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE
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
        rcept_no=no, rcept_dt=dt, filing_chain_key=chain, correction_flag=False,
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


def _context(code: str, value: int, *, semantic: str = "CUMULATIVE_YTD") -> dict:
    if code == "11012":
        start, end, days = ("2025-01-01", "2025-06-30", 181) if semantic == "CUMULATIVE_YTD" else ("2025-04-01", "2025-06-30", 91)
    else:
        start, end, days = ("2025-01-01", "2025-09-30", 273) if semantic == "CUMULATIVE_YTD" else ("2025-07-01", "2025-09-30", 92)
    return {
        "account_id": "ifrs-full_Revenue", "value": value, "currency": "KRW",
        "period_start": start, "period_end": end, "duration_days": days,
        "context_semantics": "DURATION", "period_semantics": semantic,
        "comparative": False, "basis": "CFS",
    }


class _CountingXbrl:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture
        self.fetch_calls: list[tuple[str, str]] = []

    def fetch(self, filing, *, force_refresh=False):
        self.fetch_calls.append((filing.reprt_code, filing.rcept_no))
        return RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at="test",
            http_status=200, content_type="application/zip", byte_length=1,
            sha256=f"sha-{filing.rcept_no}", member_count=1, member_names=("test.xbrl",),
            source_url_redacted="https://example.invalid", cache_hit=True,
        )

    def period_context_rows(self, artifact, *, bsns_year, reprt_code):
        return self.fixture.contexts.get(artifact.rcept_no, [])


def _provider(filings, contexts):
    fixture = _Fixture(filings, contexts)
    xbrl = _CountingXbrl(fixture)
    return PeriodizationProvider(_Corp(), _Registry(fixture), xbrl), xbrl


def _historical_ready_fixture(*, direct: bool = False, duplicate_h1: bool = False):
    h1_a = _filing("11012", "H1-A", "2025-08-14")
    q3 = _filing("11014", "Q3", "2025-11-14")
    filings = [h1_a, q3]
    if duplicate_h1:
        filings.extend([_filing("11012", "H1-B", "2025-08-14"), _filing("11012", "H1-C", "2025-08-14")])
    else:
        filings.extend([_filing("11012", "H1-B", "2025-12-01"), _filing("11012", "H1-C", "2025-12-01")])
    q3_contexts = [_context("11014", 150)]
    if direct:
        q3_contexts.append(_context("11014", 50, semantic="STANDALONE_QUARTER"))
    contexts = {"H1-A": [_context("11012", 100)], "Q3": q3_contexts}
    return filings, contexts


def _q3(build):
    return next(item for item in build.result.observations if item.fiscal_period == "Q3")


def test_case_a_current_ambiguous_historical_ready_materializes_and_derives():
    filings, contexts = _historical_ready_fixture()
    provider, xbrl = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    current_h1 = next(item for item in build.anchor_selections if item["reprt_code"] == "11012")
    q3_meta = next(item for item in build.anchor_selections if item["reprt_code"] == "11014")
    q3 = _q3(build)
    assert current_h1["status"] == "AMBIGUOUS"
    assert q3_meta["prior_pit"]["status"] == "READY"
    assert q3_meta["prior_pit"]["selected_rcept_no"] == "H1-A"
    assert q3_meta["prior_pit"]["historical_source_materialized"] is True
    assert any(item.rcept_no == "H1-A" for item in build.facts)
    assert q3.value == 50
    assert q3.method == "DERIVED_DIFFERENCE"
    assert q3.resolution_status == READY
    assert build.result.parity == ()
    assert xbrl.fetch_calls.count(("11012", "H1-A")) == 1


def test_case_b_historical_ready_direct_q3_is_validated_by_derivation():
    filings, contexts = _historical_ready_fixture(direct=True)
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q3 = _q3(build)
    assert q3.value == 50
    assert q3.method == "DIRECT_VALIDATED_BY_DERIVATION"
    assert q3.resolution_status == READY
    assert len(build.result.parity) == 1
    assert build.result.parity[0].status == "MATCH"


def test_case_c_historical_source_provenance_excludes_current_corrections():
    filings, contexts = _historical_ready_fixture()
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q3 = _q3(build)
    assert q3.source_rcept_nos == ("Q3", "H1-A")
    assert q3.source_rcept_dts == ("2025-11-14", "2025-08-14")
    assert q3.source_sha256s == ("sha-Q3", "sha-H1-A")
    assert len(q3.source_rcept_nos) == len(q3.source_rcept_dts) == len(q3.source_sha256s)
    assert "H1-B" not in q3.source_rcept_nos
    assert "H1-C" not in q3.source_rcept_nos


def test_case_d_current_h1_ambiguity_is_not_overwritten_by_historical_source():
    filings, contexts = _historical_ready_fixture()
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    current_h1 = next(item for item in build.anchor_selections if item["reprt_code"] == "11012")
    assert current_h1["status"] == "AMBIGUOUS"
    assert not any(item.anchor_reprt_code == "11012" for item in build.result.observations)
    assert {item.rcept_no for item in build.facts if item.reprt_code == "11012"} == {"H1-A"}


def test_case_e_historical_prior_ambiguity_still_blocks_derivation():
    filings, contexts = _historical_ready_fixture(duplicate_h1=True)
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q3_meta = next(item for item in build.anchor_selections if item["reprt_code"] == "11014")
    q3 = _q3(build)
    assert q3_meta["prior_pit"]["status"] == "AMBIGUOUS"
    assert q3_meta["prior_pit"]["reason"] == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
    assert q3.value is None
    assert q3.resolution_status == PERIOD_AMBIGUOUS
    assert build.result.parity == ()


def test_case_f_historical_selected_filing_context_ambiguity_is_preserved():
    filings, contexts = _historical_ready_fixture()
    contexts["H1-A"] = [_context("11012", 100), _context("11012", 101)]
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q3 = _q3(build)
    assert q3.resolution_status == PERIOD_AMBIGUOUS
    assert q3.reason == PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS
    assert build.result.parity == ()


def test_case_g_late_correction_does_not_enter_past_q3_provenance():
    filings, contexts = _historical_ready_fixture()
    provider, _ = _provider(filings, contexts)
    build = provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"})
    q3 = _q3(build)
    assert q3.value == 50
    assert q3.source_rcept_nos[-1] == "H1-A"
    assert all(no not in q3.source_rcept_nos for no in ("H1-B", "H1-C"))
