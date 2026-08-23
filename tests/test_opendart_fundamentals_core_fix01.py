from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import (
    FilingRegistry,
    FilingRegistryApiError,
    IncompleteRegistryError,
)
from trend_scanner.fundamentals.financial_statement_provider import FinancialStatementProvider
from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_client import JsonResponse


def _response(rows, *, status="000", page=1, total_page=None, total_count=None, http_status=200):
    payload = {"status": status, "list": rows}
    if total_page is not None:
        payload["total_page"] = total_page
    if total_count is not None:
        payload["total_count"] = total_count
    raw = json.dumps(payload, sort_keys=True).encode()
    return JsonResponse(payload, raw, http_status, "application/json", "https://example/list.json?crtfc_key=%3CREDACTED%3E", status, None)


def _row(code: str, rcept_no: str, *, correction: bool = False, year: str = "2025") -> dict[str, str]:
    names = {"11013": f"분기보고서 ({year}.03)", "11012": f"반기보고서 ({year}.06)",
             "11014": f"분기보고서 ({year}.09)", "11011": f"사업보고서 ({year}.12)"}
    name = ("[기재정정]" if correction else "") + names[code]
    date = "20260602" if correction else {"11013": "20250515", "11012": "20250814", "11014": "20251114", "11011": "20260318"}[code]
    return {"corp_code": "00871833", "corp_name": "테스트", "report_nm": name,
            "rcept_no": rcept_no, "rcept_dt": date}


class PaginatedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def list_filings(self, corp_code, *, bgn_de, end_de, page_no, page_count):
        self.calls.append((bgn_de, end_de, page_no, page_count))
        if not self.responses:
            raise AssertionError("unexpected list.json request")
        return self.responses.pop(0)


def test_registry_requires_http_and_api_success_without_writing_failure_cache(tmp_path: Path):
    for status, http_status in (("020", 200), ("010", 200), ("000", 500)):
        client = PaginatedClient([_response([], status=status, http_status=http_status)])
        registry = FilingRegistry(client, cache_dir=tmp_path / status)
        with pytest.raises(FilingRegistryApiError):
            registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                          force_refresh=True)
        assert not list((tmp_path / status).glob("*.json"))


@pytest.mark.parametrize("reprt_code", ["11013", "11012", "11014", "11011"])
def test_registry_fetches_all_pages_for_every_regular_report_type(tmp_path: Path, reprt_code: str):
    client = PaginatedClient([
        _response([_row(reprt_code, "100")], page=1, total_page=2, total_count=2),
        _response([_row(reprt_code, "200", correction=True)], page=2, total_page=2, total_count=2),
    ])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    rows = registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025",
                                         reprt_code=reprt_code, force_refresh=True)
    assert [row.rcept_no for row in rows] == ["100", "200"]
    assert registry.last_metadata["cache_complete"] is True
    assert registry.last_metadata["pages_fetched"] == 2
    assert registry.last_metadata["page_count_requested"] == 100
    assert len(client.calls) == 2


def test_registry_page_two_correction_is_available_to_pit_resolver(tmp_path: Path):
    client = PaginatedClient([
        _response([_row("11011", "100")], total_page=2, total_count=2),
        _response([_row("11011", "200", correction=True)], total_page=2, total_count=2),
    ])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    rows = registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                         force_refresh=True)
    from trend_scanner.fundamentals.pit_resolver import PITResolver
    result = PITResolver().resolve(rows, as_of="2026-06-02", bsns_year="2025", reprt_code="11011")
    assert result.selected_rcept_no == "200"


def test_registry_page_two_failure_never_writes_partial_cache(tmp_path: Path):
    client = PaginatedClient([
        _response([_row("11011", "100")], total_page=2, total_count=2),
        _response([], status="020"),
    ])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    with pytest.raises(FilingRegistryApiError):
        registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                      force_refresh=True)
    assert not list(tmp_path.glob("*.json"))


def test_valid_cache_survives_failed_force_refresh(tmp_path: Path):
    path_client = PaginatedClient([_response([_row("11011", "100")], total_page=1, total_count=1)])
    registry = FilingRegistry(path_client, cache_dir=tmp_path)
    first = registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                          force_refresh=True)
    cache_path = next(tmp_path.glob("*.json"))
    before = cache_path.read_bytes()
    failing = FilingRegistry(PaginatedClient([_response([], status="020")]), cache_dir=tmp_path)
    with pytest.raises(FilingRegistryApiError):
        failing.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                     force_refresh=True)
    assert cache_path.read_bytes() == before
    cached = failing.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011")
    assert [item.rcept_no for item in cached] == [item.rcept_no for item in first]
    assert failing.last_metadata["cache_hit"] is True


def test_registry_max_pages_guard_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import trend_scanner.fundamentals.filing_registry as module
    monkeypatch.setattr(module, "MAX_PAGES", 2)
    full_page = [_row("11011", str(index)) for index in range(100)]
    client = PaginatedClient([_response(full_page), _response(full_page), _response(full_page)])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    with pytest.raises(IncompleteRegistryError):
        registry.list_regular_filings(ticker="237690", corp_code="00871833", bsns_year="2025", reprt_code="11011",
                                      force_refresh=True)
    assert not list(tmp_path.glob("*.json"))


class FixtureRegistry(FilingRegistry):
    def __init__(self, filing: RegisteredFiling):
        super().__init__(None)
        self.filing = filing

    def list_regular_filings(self, **kwargs):
        return [self.filing]


class NoCurrentEndpointClient:
    def __init__(self, current_status: str):
        self.current_status = current_status
        self.financial_statements_calls = 0

    def financial_statements(self, *args, **kwargs):
        self.financial_statements_calls += 1
        raise AssertionError("historical PIT must not call fnlttSinglAcntAll")


class StubXbrl:
    def __init__(self, client):
        self.client = client
        self.artifact = RawXbrlArtifact(
            corp_code="00871833", ticker="237690", rcept_no="20260318001605", reprt_code="11011",
            rcept_dt="20260318", retrieved_at="fixed", http_status=200, content_type="application/zip",
            byte_length=1, sha256=hashlib.sha256(b"fixture").hexdigest(), member_count=1,
            member_names=("entity.xbrl",), source_url_redacted="https://example/xbrl?crtfc_key=%3CREDACTED%3E",
        )

    def fetch(self, filing, *, force_refresh=False):
        return self.artifact

    def statement_rows(self, artifact, *, bsns_year, reprt_code):
        return [
            {"account_id": "ifrs-full_Assets", "account_nm": "자산총계", "sj_div": "BS", "statement_family": "BALANCE_SHEET", "thstrm_amount": "10", "value": 10, "period_start": None, "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "ifrs-full_Liabilities", "account_nm": "부채총계", "sj_div": "BS", "statement_family": "BALANCE_SHEET", "thstrm_amount": "3", "value": 3, "period_start": None, "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "ifrs-full_Equity", "account_nm": "자본총계", "sj_div": "BS", "statement_family": "BALANCE_SHEET", "thstrm_amount": "7", "value": 7, "period_start": None, "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "ifrs-full_Revenue", "account_nm": "매출액", "sj_div": "CIS", "statement_family": "INCOME_STATEMENT", "thstrm_amount": "20", "value": 20, "period_start": "2025-01-01", "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "sj_div": "CIS", "statement_family": "INCOME_STATEMENT", "thstrm_amount": "2", "value": 2, "period_start": "2025-01-01", "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "sj_div": "CIS", "statement_family": "INCOME_STATEMENT", "thstrm_amount": "1", "value": 1, "period_start": "2025-01-01", "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
            {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "account_nm": "영업활동현금흐름", "sj_div": "CF", "statement_family": "CASH_FLOW", "thstrm_amount": "4", "value": 4, "period_start": "2025-01-01", "period_end": "2025-12-31", "basis": "ConsolidatedMember"},
        ]

    def basis_rows(self, rows, preferred_basis="CFS"):
        return "CFS", list(rows)


def _provider() -> tuple[FinancialStatementProvider, NoCurrentEndpointClient]:
    corp = CorpCodeRepository(records=[CorpCodeRecord("00871833", "테스트", "237690", "")])
    filing = RegisteredFiling(
        ticker="237690", corp_code="00871833", corp_name="테스트", bsns_year="2025", reprt_code="11011",
        report_type="ANNUAL", report_nm="사업보고서 (2025.12)", rcept_no="20260318001605", rcept_dt="20260318",
        filing_chain_key="00871833:2025:11011:사업보고서(2025.12)", correction_flag=False,
        source_retrieved_at="fixed",
    )
    client = NoCurrentEndpointClient("000")
    return FinancialStatementProvider(corp, FixtureRegistry(filing), StubXbrl(client)), client


def test_historical_normalize_never_calls_current_latest_endpoint():
    provider, client = _provider()
    result = provider.normalize(ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01",
                                company={"induty_code": "264"})
    assert result.status == "READY"
    assert client.financial_statements_calls == 0


def test_historical_result_is_independent_of_current_latest_status():
    first, first_client = _provider()
    second, second_client = _provider()
    first.xbrl.client.current_status = "000"
    second.xbrl.client.current_status = "013"
    result_first = first.normalize(ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01",
                                   company={"induty_code": "264"})
    result_second = second.normalize(ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01",
                                    company={"induty_code": "264"})
    assert result_first.to_dict() == result_second.to_dict()
    assert first_client.financial_statements_calls == second_client.financial_statements_calls == 0


def test_unknown_company_family_fails_closed_without_nonfinancial_resolution():
    provider, _ = _provider()
    result = provider.normalize(ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01")
    assert result.company_family == "UNKNOWN"
    assert result.status == "COMPANY_FAMILY_UNRESOLVED"
    assert result.reason == "COMPANY_FAMILY_UNKNOWN"
    assert result.observations == ()

    no_industry_metadata = provider.normalize(
        ticker="237690", bsns_year="2025", reprt_code="11011", as_of="2026-04-01", company={}
    )
    assert no_industry_metadata.status == "COMPANY_FAMILY_UNRESOLVED"
    assert no_industry_metadata.company_family == "UNKNOWN"
