from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import (
    FilingRegistry,
    FilingRegistryApiError,
    FilingRegistryConflictError,
    InvalidAsOfError,
    RegistryCoverageInsufficientError,
)
from trend_scanner.fundamentals.financial_statement_provider import FinancialStatementProvider
from trend_scanner.fundamentals.models import CorpCodeRecord
from trend_scanner.fundamentals.opendart_client import JsonResponse
from trend_scanner.fundamentals.pit_resolver import PITResolver


def _response(rows, *, status="000", total_page=1, total_count=None):
    payload = {"status": status, "list": rows, "total_page": total_page}
    if total_count is not None:
        payload["total_count"] = total_count
    raw = json.dumps(payload, sort_keys=True).encode()
    return JsonResponse(payload, raw, 200, "application/json",
                        "https://example/list.json?crtfc_key=%3CREDACTED%3E", status, None)


def _late_row(rcept_no: str, rcept_dt: str, *, correction: bool = False) -> dict[str, str]:
    return {
        "corp_code": "00871833",
        "corp_name": "테스트",
        "report_nm": ("[기재정정]" if correction else "") + "사업보고서 (2020.12)",
        "rcept_no": rcept_no,
        "rcept_dt": rcept_dt.replace("-", ""),
    }


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def list_filings(self, corp_code, *, bgn_de, end_de, page_no, page_count):
        self.calls.append({"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de,
                           "page_no": page_no, "page_count": page_count})
        if not self.responses:
            raise AssertionError("unexpected list.json request")
        return self.responses.pop(0)


def _request(registry: FilingRegistry, *, as_of: str, force_refresh: bool = False):
    return registry.list_regular_filings(
        ticker="237690", corp_code="00871833", bsns_year="2020", reprt_code="11011",
        as_of=as_of, force_refresh=force_refresh,
    )


def _seed_cache(tmp_path: Path, *, as_of: str, rows):
    client = SequenceClient([_response(rows, total_count=len(rows))])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    _request(registry, as_of=as_of, force_refresh=True)
    cache_path = next(tmp_path.glob("*.json"))
    return cache_path, registry


def test_provider_passes_as_of_to_registry():
    class RecordingRegistry(FilingRegistry):
        def __init__(self):
            super().__init__(None)
            self.kwargs = {}

        def list_regular_filings(self, **kwargs):
            self.kwargs = kwargs
            return []

    corp = CorpCodeRepository(records=[CorpCodeRecord("00871833", "테스트", "237690", "")])
    registry = RecordingRegistry()
    provider = FinancialStatementProvider(corp, registry, object())
    result = provider.normalize(ticker="237690", bsns_year="2020", reprt_code="11011", as_of="2024-07-01")
    assert registry.kwargs["as_of"] == "2024-07-01"
    assert result.status == "DATA_UNAVAILABLE"


def test_future_as_of_fails_before_network_request(tmp_path: Path):
    client = SequenceClient([])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    with pytest.raises(InvalidAsOfError):
        _request(registry, as_of="2027-01-01")
    assert client.calls == []


def test_cache_metadata_has_requested_coverage_boundary(tmp_path: Path):
    _, registry = _seed_cache(tmp_path, as_of="2024-07-01",
                              rows=[_late_row("ORIGINAL", "2021-03-20")])
    metadata = registry.last_metadata
    assert metadata["coverage_start"] == "2020-01-01"
    assert metadata["coverage_end"] == "2024-07-01"
    assert metadata["requested_as_of"] == "2024-07-01"
    assert metadata["window_count"] == 1
    assert metadata["cache_complete"] is True


def test_sufficient_coverage_cache_is_reused_without_network(tmp_path: Path):
    _, seeded = _seed_cache(tmp_path, as_of="2024-07-01",
                            rows=[_late_row("ORIGINAL", "2021-03-20"),
                                  _late_row("CORRECTION", "2024-06-10", correction=True)])

    class NoCallClient:
        def list_filings(self, *args, **kwargs):
            raise AssertionError("sufficient coverage must be a cache hit")

    registry = FilingRegistry(NoCallClient(), cache_dir=tmp_path)
    rows = _request(registry, as_of="2023-12-31")
    assert [row.rcept_no for row in rows] == ["ORIGINAL", "CORRECTION"]
    assert registry.last_metadata["cache_hit"] is True
    assert seeded.last_metadata["coverage_end"] == "2024-07-01"


def test_insufficient_coverage_refreshes_and_advances_coverage(tmp_path: Path):
    _seed_cache(tmp_path, as_of="2023-12-31", rows=[_late_row("ORIGINAL", "2021-03-20")])
    client = SequenceClient([_response([
        _late_row("ORIGINAL", "2021-03-20"),
        _late_row("CORRECTION", "2024-06-10", correction=True),
    ], total_count=2)])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    rows = _request(registry, as_of="2024-07-01")
    assert [row.rcept_no for row in rows] == ["ORIGINAL", "CORRECTION"]
    assert len(client.calls) == 1
    assert registry.last_metadata["cache_hit"] is False
    assert registry.last_metadata["coverage_end"] == "2024-07-01"


def test_offline_insufficient_coverage_fails_closed(tmp_path: Path):
    _seed_cache(tmp_path, as_of="2023-12-31", rows=[_late_row("ORIGINAL", "2021-03-20")])
    registry = FilingRegistry(None, cache_dir=tmp_path)
    with pytest.raises(RegistryCoverageInsufficientError):
        _request(registry, as_of="2024-07-01")


def test_failed_coverage_refresh_preserves_old_cache_and_fails_current_request(tmp_path: Path):
    cache_path, _ = _seed_cache(tmp_path, as_of="2023-12-31", rows=[_late_row("ORIGINAL", "2021-03-20")])
    before = cache_path.read_bytes()
    failing = FilingRegistry(SequenceClient([_response([], status="020")]), cache_dir=tmp_path)
    with pytest.raises(FilingRegistryApiError):
        _request(failing, as_of="2024-07-01")
    assert cache_path.read_bytes() == before
    assert failing.last_metadata == {}


def test_late_correction_is_covered_and_pit_boundaries_remain_strict(tmp_path: Path):
    rows = [_late_row("ORIGINAL", "2021-03-20"), _late_row("CORRECTION", "2024-06-10", correction=True)]
    registry = FilingRegistry(SequenceClient([_response(rows, total_count=2)]), cache_dir=tmp_path)
    registry_rows = _request(registry, as_of="2024-07-01", force_refresh=True)
    assert {row.rcept_no for row in registry_rows} == {"ORIGINAL", "CORRECTION"}

    resolver = PITResolver()
    before = resolver.resolve(registry_rows, as_of="2023-12-31", bsns_year="2020", reprt_code="11011")
    same_day = resolver.resolve(registry_rows, as_of="2024-06-10", bsns_year="2020", reprt_code="11011")
    after = resolver.resolve(registry_rows, as_of="2024-07-01", bsns_year="2020", reprt_code="11011")
    assert before.selected_rcept_no == "ORIGINAL"
    assert same_day.selected_rcept_no == "CORRECTION"
    assert same_day.availability == "AVAILABLE_AT_EOD"
    assert after.selected_rcept_no == "CORRECTION"


def test_conflicting_duplicate_rcept_payload_fails_without_cache(tmp_path: Path):
    first = _late_row("DUPLICATE", "2021-03-20")
    second = {**first, "corp_name": "충돌한 이름"}
    client = SequenceClient([_response([first], total_page=2, total_count=2),
                             _response([second], total_page=2, total_count=2)])
    registry = FilingRegistry(client, cache_dir=tmp_path)
    with pytest.raises(FilingRegistryConflictError):
        _request(registry, as_of="2024-07-01", force_refresh=True)
    assert not list(tmp_path.glob("*.json"))
