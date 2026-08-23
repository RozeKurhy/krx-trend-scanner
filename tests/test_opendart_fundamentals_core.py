from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from trend_scanner.fundamentals.corp_code_repository import (
    AmbiguousCorpCodeError,
    CorpCodeRepository,
    UnknownTickerError,
)
from trend_scanner.fundamentals.filing_registry import (
    FilingRegistry,
    infer_report_code,
    to_registered_filing,
)
from trend_scanner.fundamentals.financial_statement_provider import FinancialStatementProvider
from trend_scanner.fundamentals.models import CorpCodeRecord, RegisteredFiling
from trend_scanner.fundamentals.opendart_client import BinaryResponse, JsonResponse
from trend_scanner.fundamentals.pit_resolver import PITResolver
from trend_scanner.fundamentals.xbrl_repository import SourceMutationDetected, XbrlRepository


class FakeClient:
    def __init__(self, *, corp_raw: bytes | None = None, xbrl_raw: bytes | None = None):
        self.corp_raw = corp_raw
        self.xbrl_raw = xbrl_raw
        self.calls: list[tuple[str, object]] = []

    def corp_code(self):
        self.calls.append(("corp_code", None))
        return BinaryResponse(self.corp_raw or b"", 200, "application/zip", "https://example/corpCode.xml?crtfc_key=%3CREDACTED%3E")

    def xbrl(self, rcept_no, reprt_code):
        self.calls.append(("xbrl", (rcept_no, reprt_code)))
        return BinaryResponse(self.xbrl_raw or b"", 200, "application/zip", "https://example/fnlttXbrl.xml?crtfc_key=%3CREDACTED%3E")


def _zip(**members: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return out.getvalue()


def _filing(rcept_no: str, rcept_dt: str, report_nm: str = "사업보고서 (2025.12)", correction: bool = False) -> RegisteredFiling:
    return RegisteredFiling(
        ticker="237690", corp_code="00871833", corp_name="에스티팜", bsns_year="2025", reprt_code="11011",
        report_type="ANNUAL", report_nm=("[기재정정]" if correction else "") + report_nm,
        rcept_no=rcept_no, rcept_dt=rcept_dt, filing_chain_key="00871833:2025:11011:사업보고서(2025.12)",
        correction_flag=correction, source_retrieved_at="2026-08-23T00:00:00+00:00",
    )


def test_corp_code_repository_round_trip_and_valid_ticker(tmp_path: Path):
    raw = _zip(**{"CORPCODE.xml": """<?xml version='1.0'?><result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20251201</modify_date></list><list><corp_code>00871833</corp_code><corp_name>에스티팜</corp_name><stock_code>237690</stock_code><modify_date>20240625</modify_date></list></result>"""})
    client = FakeClient(corp_raw=raw)
    repo = CorpCodeRepository(client, cache_path=tmp_path / "corp.json")
    metadata = repo.refresh()
    assert repo.get_corp_code("005930") == "00126380"
    assert repo.get_ticker("00871833") == "237690"
    assert metadata["record_count"] == 2
    second = CorpCodeRepository(client, cache_path=tmp_path / "corp.json")
    assert second.refresh()["cache_hit"] is True
    assert len(client.calls) == 1


def test_corp_code_duplicate_ticker_fails_closed():
    repo = CorpCodeRepository(records=[
        CorpCodeRecord("1", "A", "123456", ""), CorpCodeRecord("2", "B", "123456", "")
    ])
    with pytest.raises(AmbiguousCorpCodeError):
        repo.get_corp_code("123456")
    with pytest.raises(UnknownTickerError):
        repo.get_corp_code("bad")


def test_filing_registry_normalizes_regular_and_correction_chain():
    original = to_registered_filing({
        "corp_code": "00871833", "corp_name": "에스티팜", "report_nm": "사업보고서 (2025.12)",
        "rcept_no": "20260318001605", "rcept_dt": "20260318",
    }, ticker="237690", retrieved_at="now")
    correction = to_registered_filing({
        "corp_code": "00871833", "corp_name": "에스티팜", "report_nm": "[기재정정]사업보고서 (2025.12)",
        "rcept_no": "20260602000343", "rcept_dt": "20260602",
    }, ticker="237690", retrieved_at="now")
    assert original and correction
    assert original.filing_chain_key == correction.filing_chain_key
    assert original.correction_flag is False and correction.correction_flag is True
    assert infer_report_code("분기보고서 (2025.09)") == "11014"
    assert infer_report_code("잠정실적") is None


def test_pit_original_correction_same_day_and_future_boundaries():
    filings = [_filing("20260318001605", "20260318"), _filing("20260602000343", "20260602", correction=True)]
    resolver = PITResolver()
    before = resolver.resolve(filings, as_of="2026-04-01", bsns_year="2025", reprt_code="11011")
    same_day = resolver.resolve(filings, as_of="2026-06-02", bsns_year="2025", reprt_code="11011")
    future = resolver.resolve(filings, as_of="2026-03-17", bsns_year="2025", reprt_code="11011")
    assert before.selected_rcept_no == "20260318001605"
    assert same_day.selected_rcept_no == "20260602000343" and same_day.availability == "AVAILABLE_AT_EOD"
    assert future.status == "FUTURE_FORBIDDEN" and future.selected is None


XBRL = """<?xml version='1.0' encoding='utf-8'?>
<xbrl xmlns='http://www.xbrl.org/2003/instance'
 xmlns:ifrs-full='http://xbrl.ifrs.org/taxonomy/2021-03-24/ifrs-full'
 xmlns:dart='http://dart.fss.or.kr/taxonomy/2024-06-30/ifrs/dart'
 xmlns:xbrldi='http://xbrl.org/2006/xbrldi'>
<context id='instant'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:ConsolidatedMember</xbrldi:explicitMember></segment></entity><period><instant>2025-12-31</instant></period></context>
<context id='duration'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:ConsolidatedMember</xbrldi:explicitMember></segment></entity><period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>
<context id='separate'><entity><identifier>00871833</identifier><segment><xbrldi:explicitMember dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis'>ifrs-full:SeparateMember</xbrldi:explicitMember></segment></entity><period><instant>2025-12-31</instant></period></context>
<ifrs-full:Assets contextRef='instant' unitRef='KRW'>782</ifrs-full:Assets><ifrs-full:Liabilities contextRef='instant' unitRef='KRW'>189</ifrs-full:Liabilities><ifrs-full:Equity contextRef='instant' unitRef='KRW'>593</ifrs-full:Equity>
<ifrs-full:Revenue contextRef='duration' unitRef='KRW'>331</ifrs-full:Revenue><dart:OperatingIncomeLoss contextRef='duration' unitRef='KRW'>54</dart:OperatingIncomeLoss><ifrs-full:ProfitLoss contextRef='duration' unitRef='KRW'>53</ifrs-full:ProfitLoss><ifrs-full:CashFlowsFromUsedInOperatingActivities contextRef='duration' unitRef='KRW'>13</ifrs-full:CashFlowsFromUsedInOperatingActivities>
<ifrs-full:Assets contextRef='separate' unitRef='KRW'>700</ifrs-full:Assets>
</xbrl>"""


def test_xbrl_cache_reuse_parser_and_source_hash(tmp_path: Path):
    raw = _zip(**{"entity.xbrl": XBRL})
    client = FakeClient(xbrl_raw=raw)
    repo = XbrlRepository(client, cache_dir=tmp_path)
    filing = _filing("20260318001605", "20260318")
    artifact = repo.fetch(filing)
    rows = repo.statement_rows(artifact, bsns_year="2025", reprt_code="11011")
    basis, selected = repo.basis_rows(rows)
    assert basis == "CFS" and len(selected) == 7
    assert {row["account_id"] for row in selected} >= {"ifrs-full_Assets", "ifrs-full_Revenue", "dart_OperatingIncomeLoss"}
    again = repo.fetch(filing)
    assert again.cache_hit is True and again.sha256 == hashlib.sha256(raw).hexdigest()
    assert len(client.calls) == 1


def test_xbrl_source_mutation_is_not_silently_overwritten(tmp_path: Path):
    filing = _filing("20260318001605", "20260318")
    client = FakeClient(xbrl_raw=_zip(**{"entity.xbrl": XBRL}))
    repo = XbrlRepository(client, cache_dir=tmp_path)
    repo.fetch(filing)
    client.xbrl_raw = _zip(**{"entity.xbrl": XBRL + " "})
    with pytest.raises(SourceMutationDetected):
        repo.fetch(filing, force_refresh=True)


def test_xbrl_basis_requires_explicit_cfs_013_before_ofs_fallback(tmp_path: Path):
    repo = XbrlRepository(cache_dir=tmp_path)
    separate = [{"basis": "SeparateMember", "account_id": "ifrs-full_Assets"}]
    assert repo.basis_rows(separate) == ("", [])
    assert repo.basis_rows(separate, cfs_status="013", ofs_status="000") == ("OFS", separate)


class FixtureRegistry(FilingRegistry):
    def __init__(self, rows):
        super().__init__(None)
        self.rows = rows

    def list_regular_filings(self, **kwargs):
        return self.rows


def test_provider_keeps_selected_rcept_and_filing_specific_values(tmp_path: Path):
    raw = _zip(**{"entity.xbrl": XBRL})
    client = FakeClient(xbrl_raw=raw)
    corp = CorpCodeRepository(records=[CorpCodeRecord("00871833", "에스티팜", "237690", "")])
    filing = _filing("20260318001605", "20260318")
    provider = FinancialStatementProvider(corp, FixtureRegistry([filing]), XbrlRepository(client, cache_dir=tmp_path))
    result = provider.normalize(ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01",
                                company={"induty_code": "264"})
    values = {item.metric: item for item in result.observations}
    assert result.rcept_no == filing.rcept_no and result.fs_div_used == "CFS"
    assert values["revenue"].value == 331 and values["operating_income"].value == 54
    assert all(item.rcept_no == filing.rcept_no for item in result.observations)
    assert all(item.source_role == "FILING_SPECIFIC_RAW" for item in result.observations)


def test_provider_financial_family_marks_nonfinancial_metrics_not_applicable(tmp_path: Path):
    raw = _zip(**{"entity.xbrl": XBRL})
    corp = CorpCodeRepository(records=[CorpCodeRecord("00547583", "하나금융지주", "086790", "")])
    filing = _filing("20260316001292", "20260316")
    filing = RegisteredFiling(**{**filing.to_dict(), "ticker": "086790", "corp_code": "00547583"})
    provider = FinancialStatementProvider(corp, FixtureRegistry([filing]), XbrlRepository(FakeClient(xbrl_raw=raw), cache_dir=tmp_path))
    result = provider.normalize(ticker="086790", bsns_year="2025", reprt_code="11011", as_of="2026-04-01",
                                company={"induty_code": "64992"})
    by_metric = {item.metric: item for item in result.observations}
    assert by_metric["revenue"].resolution_status == "NOT_APPLICABLE"
    assert by_metric["operating_income"].resolution_status == "NOT_APPLICABLE"


def test_no_unit_test_client_network_methods_are_called():
    client = FakeClient()
    assert client.calls == []
