from __future__ import annotations

from dataclasses import replace

from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE
from trend_scanner.fundamentals.period_models import CUMULATIVE_YTD, PERIOD_AMBIGUOUS, READY
from trend_scanner.fundamentals.periodization import PeriodizationEngine
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.periodization import facts_from_xbrl_rows
from trend_scanner.fundamentals.period_models import PeriodizationFact


def filing(code: str, no: str, dt: str, *, chain: str | None = None, fs: str = "CFS") -> RegisteredFiling:
    names = {"11013": "2025 1분기보고서", "11012": "2025 반기보고서", "11014": "2025 3분기보고서", "11011": "2025 사업보고서"}
    return RegisteredFiling(
        ticker="237690", corp_code="00871833", corp_name="ST Pharm", bsns_year="2025",
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], report_nm=names[code],
        rcept_no=no, rcept_dt=dt, filing_chain_key=chain or f"chain-{code}",
        correction_flag=no.endswith("C"), source_retrieved_at="test", fs_div=fs,
    )


def row(value: int, start: str, end: str, *, basis: str = "ConsolidatedMember") -> dict:
    return {
        "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "value": value,
        "currency": "KRW", "period_start": start, "period_end": end, "instant": None,
        "duration_days": (int(end[8:10]) - int(start[8:10]) + 1) if start[:7] == end[:7] else None,
        "context_semantics": "DURATION", "comparative": False, "basis": basis,
    }


class FakeCorpCodes:
    def get_record(self, ticker: str) -> CorpCodeRecord:
        assert ticker == "237690"
        return CorpCodeRecord("00871833", "ST Pharm", ticker, "20260101")


class FakeRegistry:
    def __init__(self, rows: list[RegisteredFiling]):
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    def list_regular_filings(self, **kwargs):
        self.calls.append((kwargs["reprt_code"], str(kwargs["as_of"])))
        return [item for item in self.rows if item.reprt_code == kwargs["reprt_code"]]


class FakeXbrl:
    def __init__(self, contexts: dict[str, list[dict]]):
        self.contexts = contexts
        self.fetch_calls: list[str] = []

    def fetch(self, filing: RegisteredFiling, *, force_refresh: bool = False):
        self.fetch_calls.append(filing.rcept_no)
        return RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at="test",
            http_status=200, content_type="application/zip", byte_length=1,
            sha256=f"sha-{filing.rcept_no}", member_count=1, member_names=("test.xbrl",),
            source_url_redacted="https://example.invalid", cache_hit=True,
        )

    def period_context_rows(self, artifact, *, bsns_year: str, reprt_code: str):
        return self.contexts.get(artifact.rcept_no, [])


def provider(rows: list[RegisteredFiling], contexts: dict[str, list[dict]]) -> tuple[PeriodizationProvider, FakeRegistry, FakeXbrl]:
    registry, xbrl = FakeRegistry(rows), FakeXbrl(contexts)
    return PeriodizationProvider(FakeCorpCodes(), registry, xbrl), registry, xbrl


def obs(result, period: str, no: str | None = None):
    values = [item for item in result.observations if item.fiscal_period == period]
    if no is not None:
        return next(item for item in values if item.anchor_rcept_no == no)
    return next(item for item in values if item.resolution_status == READY)


def build_rows(*items):
    rows, contexts = [], {}
    for code, no, dt, value, start, end in items:
        rows.append(filing(code, no, dt, chain=f"chain-{code}"))
        contexts[no] = [row(value, start, end)]
    return rows, contexts


def test_production_q2_anchor_keeps_prior_q1_vintage_and_current_correction():
    rows, contexts = build_rows(
        ("11013", "Q1O", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        ("11013", "Q1C", "2025-10-01", 45, "2025-01-01", "2025-03-31"),
        ("11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
    )
    rows[1] = replace(rows[1], filing_chain_key=rows[0].filing_chain_key)
    p, registry, _ = provider(rows, contexts)
    built = p.build("237690", "2025", "2025-11-01", company={"induty_code": "30"})
    assert obs(built.result, "Q1", "Q1C").value == 45
    q2 = obs(built.result, "Q2", "H1")
    assert q2.value == 60
    assert q2.source_rcept_nos == ("H1", "Q1O")
    assert q2.source_sha256s == ("sha-H1", "sha-Q1O")
    h1_selection = next(item for item in built.anchor_selections if item["reprt_code"] == "11012")
    assert h1_selection["prior_pit"]["selected_rcept_no"] == "Q1O"
    assert all(as_of == "2025-11-01" for _, as_of in registry.calls)


def test_q3_anchor_uses_h1_available_at_q3_receipt_not_late_correction():
    rows, contexts = build_rows(
        ("11013", "Q1", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        ("11012", "H1O", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
        ("11012", "H1C", "2025-12-01", 110, "2025-01-01", "2025-06-30"),
        ("11014", "Q3", "2025-11-14", 150, "2025-01-01", "2025-09-30"),
    )
    rows[2] = replace(rows[2], filing_chain_key=rows[1].filing_chain_key)
    p, _, _ = provider(rows, contexts)
    result = p.periodize("237690", "2025", "2025-12-15", company={"induty_code": "30"})
    q3 = obs(result, "Q3", "Q3")
    assert q3.value == 50
    assert q3.source_rcept_nos == ("Q3", "H1O")


def test_q4_anchor_uses_q3_available_at_annual_receipt_not_late_correction():
    rows, contexts = build_rows(
        ("11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
        ("11014", "Q3O", "2025-11-14", 130, "2025-01-01", "2025-09-30"),
        ("11014", "Q3C", "2026-05-01", 140, "2025-01-01", "2025-09-30"),
        ("11011", "FY", "2026-03-18", 180, "2025-01-01", "2025-12-31"),
    )
    rows[2] = replace(rows[2], filing_chain_key=rows[1].filing_chain_key)
    p, _, _ = provider(rows, contexts)
    result = p.periodize("237690", "2025", "2026-06-01", company={"induty_code": "30"})
    q4 = obs(result, "Q4", "FY")
    assert q4.value == 50
    assert q4.source_rcept_nos == ("FY", "Q3O")


def test_anchor_correction_creates_new_q2_version_without_rewriting_original():
    rows, contexts = build_rows(
        ("11013", "Q1", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        ("11012", "H1O", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
        ("11012", "H1C", "2025-09-01", 105, "2025-01-01", "2025-06-30"),
    )
    rows[2] = replace(rows[2], filing_chain_key=rows[1].filing_chain_key)
    p, _, _ = provider(rows, contexts)
    result = p.periodize("237690", "2025", "2025-10-01", company={"induty_code": "30"})
    assert obs(result, "Q2", "H1O").value == 60
    assert obs(result, "Q2", "H1C").value == 65


def test_requested_as_of_excludes_future_anchor_and_same_day_is_eod_available():
    rows, contexts = build_rows(
        ("11013", "Q1", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        ("11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
    )
    p, _, xbrl = provider(rows, contexts)
    result = p.periodize("237690", "2025", "2025-08-14", company={"induty_code": "30"})
    assert obs(result, "Q2", "H1").value == 60
    assert "H1" in xbrl.fetch_calls
    result_before = p.periodize("237690", "2025", "2025-08-13", company={"induty_code": "30"})
    assert not any(item.anchor_rcept_no == "H1" for item in result_before.observations)


def _fact(metric, code, no, dt, value, start, end):
    return PeriodizationFact(
        ticker="237690", corp_code="00871833", company_family=CompanyFamily.NON_FINANCIAL.value,
        fiscal_year="2025", fiscal_year_start="2025-01-01", metric=metric, value=value, currency="KRW",
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], rcept_no=no, rcept_dt=dt,
        period_start=start, period_end=end, fs_div_used="CFS", source_sha256=f"sha-{no}",
        period_semantics=CUMULATIVE_YTD, pit_available_from=dt,
    )


def test_annual_diagnostic_uses_aligned_single_vintage_and_keeps_annual_corrections():
    values = [
        _fact("revenue", "11013", "Q1", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        _fact("revenue", "11013", "Q1C", "2026-03-01", 45, "2025-01-01", "2025-03-31"),
        _fact("revenue", "11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
        _fact("revenue", "11014", "Q3", "2025-11-14", 130, "2025-01-01", "2025-09-30"),
        _fact("revenue", "11011", "FY", "2026-03-18", 180, "2025-01-01", "2025-12-31"),
        _fact("revenue", "11011", "FYC", "2026-04-01", 185, "2025-01-01", "2025-12-31"),
    ]
    result = PeriodizationEngine().periodize(values)
    diagnostics = [item for item in result.diagnostics if item.get("metric") == "revenue"]
    assert len(diagnostics) == 2
    assert diagnostics[0]["annual_anchor_rcept_no"] == "FY"
    assert diagnostics[0]["quarter_anchor_rcept_nos"]["Q1"] == "Q1C"
    assert diagnostics[1]["annual_anchor_rcept_no"] == "FYC"
    assert diagnostics[1]["quarter_anchor_rcept_nos"]["Q1"] == "Q1C"


def test_annual_diagnostic_does_not_use_future_q3_correction_and_fails_closed_on_same_eod_ambiguity():
    base = [
        _fact("revenue", "11013", "Q1", "2025-05-15", 40, "2025-01-01", "2025-03-31"),
        _fact("revenue", "11012", "H1", "2025-08-14", 100, "2025-01-01", "2025-06-30"),
        _fact("revenue", "11014", "Q3", "2025-11-14", 130, "2025-01-01", "2025-09-30"),
        _fact("revenue", "11011", "FY", "2026-03-18", 180, "2025-01-01", "2025-12-31"),
        _fact("revenue", "11014", "Q3C1", "2026-05-01", 140, "2025-01-01", "2025-09-30"),
        _fact("revenue", "11014", "Q3C2", "2026-05-01", 141, "2025-01-01", "2025-09-30"),
    ]
    result = PeriodizationEngine().periodize(base)
    original = next(item for item in result.diagnostics if item.get("annual_anchor_rcept_no") == "FY")
    assert original["quarter_anchor_rcept_nos"]["Q3"] == "Q3"
    assert not any(item.get("status") == PERIOD_AMBIGUOUS for item in result.diagnostics)
    ambiguous = PeriodizationEngine().periodize([
        item if item.rcept_no not in {"Q3C1", "Q3C2"}
        else replace(item, rcept_dt="2026-03-10")
        for item in base
    ])
    assert any(item.get("status") == PERIOD_AMBIGUOUS for item in ambiguous.diagnostics)


def test_realistic_adapter_preserves_context_semantics_and_comparative_exclusion():
    rows = [
        {"account_id": "ifrs-full_Revenue", "value": 100, "currency": "KRW", "period_start": "2025-01-01",
         "period_end": "2025-06-30", "duration_days": 181, "context_semantics": "DURATION",
         "basis": "ConsolidatedMember", "comparative": False},
        {"account_id": "ifrs-full_Revenue", "value": 80, "currency": "KRW", "period_start": "2024-01-01",
         "period_end": "2024-06-30", "duration_days": 182, "context_semantics": "DURATION",
         "basis": "ConsolidatedMember", "comparative": True},
    ]
    facts = facts_from_xbrl_rows(rows, ticker="237690", corp_code="00871833",
                                 company_family=CompanyFamily.NON_FINANCIAL.value, fiscal_year="2025",
                                 reprt_code="11012", rcept_no="H1", rcept_dt="2025-08-14",
                                 fs_div_used="CFS", source_sha256="sha-H1")
    assert len(facts) == 2
    result = PeriodizationEngine().periodize(facts)
    assert all(item.value != 80 for item in result.observations)
