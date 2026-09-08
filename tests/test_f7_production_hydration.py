from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from trend_scanner.fundamentals.models import CorpCodeRecord


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/hydrate_fundamentals_v1_production.py"
SPEC = importlib.util.spec_from_file_location("f7_production_hydration", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
f7 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f7)


class FakeBoundedRegistry(f7.BoundedFilingRegistry):
    def __init__(self, cache_dir: Path):
        super().__init__(object(), cache_dir=cache_dir)
        self.fetch_calls: list[dict[str, str]] = []

    def _fetch_pages(self, **kwargs):
        self.fetch_calls.append({key: str(value) for key, value in kwargs.items()})
        row = {
            "corp_code": "123456",
            "corp_name": "테스트",
            "report_nm": "사업보고서 (2025.12)",
            "rcept_no": "20260301000001",
            "rcept_dt": "20260301",
        }
        payload = {"status": "000", "list": [row], "total_page": 1, "total_count": 1}
        raw = json.dumps(payload, sort_keys=True).encode()
        response = f7.JsonResponse(
            payload, raw, 200, "application/json", "https://example/list.json", "000", "PASS",
        )
        return [row], [response], 1, 1


def test_filing_preload_fetches_one_window_per_missing_year(tmp_path: Path):
    registry = FakeBoundedRegistry(tmp_path)

    registry.preload_ticker(
        ticker="TEST01",
        corp_code="123456",
        requested_as_of="2026-09-04",
        fiscal_years=("2025",),
    )
    registry.preload_ticker(
        ticker="TEST01",
        corp_code="123456",
        requested_as_of="2026-09-04",
        fiscal_years=("2025",),
    )

    rows = registry.list_regular_filings(
        ticker="TEST01",
        corp_code="123456",
        bsns_year="2025",
        reprt_code="11011",
        as_of="2026-09-04",
    )
    assert len(registry.fetch_calls) == 1
    assert registry.fetch_calls[0]["bgn_de"] == "20250101"
    assert [item.rcept_no for item in rows] == ["20260301000001"]
    assert len(list(tmp_path.glob("*.json"))) == 4


def test_exact_mapping_accepts_alpha_ticker_without_fuzzy_lookup():
    repo = f7.ExactCorpCodeRepository(records=(
        CorpCodeRecord("123456", "테스트", "0001A0", "20260101"),
    ))
    assert repo.get_corp_code("0001a0") == "123456"


def test_quota_client_stops_before_hard_cap():
    client = f7.QuotaBoundOpenDartClient(
        "redacted-test-key",
        prior_additional_requests=1,
        max_additional_requests=2,
        official_usage_before=11_000,
        safety_daily_cap=39_000,
    )
    client.audit.append({"endpoint": "company.json"})
    client.http_request_count = 1
    with pytest.raises(f7.QuotaBudgetExceeded) as caught:
        client._ensure_budget()
    assert caught.value.reason == "MAX_ADDITIONAL_OPENDART_REQUESTS_REACHED"
    assert caught.value.additional_requests == 2


def test_non_common_asset_is_not_hydrated():
    row = {"ticker": "499660", "name": "테스트 ETF", "market": "KOSPI", "asset_type": "ETF"}
    result = f7.hydrate_one(
        row,
        requested_as_of="2026-09-04",
        corp_repo=None,
        records_by_ticker={},
        client=None,
        company_cache_dir=Path("/private/tmp"),
        secret="",
        period_provider=None,
    )
    assert result["terminal_status"] == "NOT_APPLICABLE"
    assert result["f5_ready"]["data_status"] == "NOT_APPLICABLE"
    assert result["api_request_count"] == 0


def test_financial_common_is_not_applicable_at_f4(tmp_path: Path):
    company_dir = tmp_path / "company"
    company_dir.mkdir()
    (company_dir / "086790.json").write_text(json.dumps({
        "status": "000",
        "selected_fields": {"corp_code": "123456", "stock_code": "086790", "induty_code": "641"},
    }), encoding="utf-8")
    row = {"ticker": "086790", "name": "테스트 금융", "market": "KOSPI", "asset_type": "COMMON"}
    repo = f7.ExactCorpCodeRepository(records=(
        CorpCodeRecord("123456", "테스트 금융", "086790", ""),
    ))

    result = f7.hydrate_one(
        row,
        requested_as_of="2026-09-04",
        corp_repo=repo,
        records_by_ticker={"086790": [CorpCodeRecord("123456", "테스트 금융", "086790", "")]},
        client=object(),
        company_cache_dir=company_dir,
        secret="",
        period_provider=None,
    )
    assert result["company_family"] == "FINANCIAL"
    assert result["f3_data_status"] == "NOT_APPLICABLE"
    assert result["f4_status"] == "NOT_APPLICABLE"
    assert result["terminal_status"] == "NOT_APPLICABLE"
    assert result["f4_passed"] is False


def test_expected_filing_failure_becomes_one_terminal_result(tmp_path: Path):
    class FailingRegistry(FakeBoundedRegistry):
        def preload_ticker(self, **kwargs):
            raise f7.FilingRegistryError("FILING_NOT_AVAILABLE")

    registry = FailingRegistry(tmp_path / "filings")
    company_dir = tmp_path / "company"
    company_dir.mkdir()
    (company_dir / "000020.json").write_text(json.dumps({
        "status": "000",
        "selected_fields": {"corp_code": "123456", "stock_code": "000020", "induty_code": "261"},
    }), encoding="utf-8")
    provider = SimpleNamespace(periodization_provider=SimpleNamespace(filings=registry))
    row = {"ticker": "000020", "name": "테스트", "market": "KOSPI", "asset_type": "COMMON"}
    repo = f7.ExactCorpCodeRepository(records=(
        CorpCodeRecord("123456", "테스트", "000020", ""),
    ))

    with pytest.raises(f7.F7TerminalError) as caught:
        f7.hydrate_one(
            row,
            requested_as_of="2026-09-04",
            corp_repo=repo,
            records_by_ticker={"000020": [CorpCodeRecord("123456", "테스트", "000020", "")]},
            client=object(),
            company_cache_dir=company_dir,
            secret="",
            period_provider=provider,
        )
    recorded = f7._record_failure(row, "2026-09-04", caught.value)
    assert recorded["terminal_status"] == "DATA_UNAVAILABLE"
    assert recorded["f4_passed"] is False
    assert recorded["f5_ready"]["data_status"] == "DATA_UNAVAILABLE"


def test_remaining_selection_skips_completed_without_market_filters():
    universe = [
        {"ticker": "000020", "market_cap": 1, "close": 1},
        {"ticker": "000040", "market_cap": 999_000_000_000, "close": 99_000},
        {"ticker": "000050", "market_cap": 2, "close": 2},
    ]
    selected = f7._select_remaining_rows(universe, {"000040"})
    assert [row["ticker"] for row in selected] == ["000020", "000050"]


def test_legacy_not_applicable_output_is_reusable(tmp_path: Path):
    path = tmp_path / "499660.json"
    path.write_text(json.dumps({
        "runner_version": "F7-03-BOUNDED-FILING-PRELOAD-IDENTITY",
        "ticker": "499660",
        "requested_as_of": "2026-09-04",
        "asset_type": "ETF",
        "terminal_status": "NOT_APPLICABLE",
        "f4_passed": False,
        "api_request_count": 0,
        "f5_ready": {"data_status": "NOT_APPLICABLE"},
    }), encoding="utf-8")
    value = f7._load_existing(path, ticker="499660", requested_as_of="2026-09-04")
    assert value is not None
    assert value["terminal_status"] == "NOT_APPLICABLE"


def test_quota_stop_does_not_create_data_unavailable():
    client = f7.QuotaBoundOpenDartClient(
        "redacted-test-key",
        max_additional_requests=1,
        official_usage_before=11_000,
        safety_daily_cap=39_000,
    )
    client.audit.append({"endpoint": "company.json"})
    client.http_request_count = 1
    with pytest.raises(f7.QuotaBudgetExceeded):
        client._ensure_budget()
    assert not issubclass(f7.QuotaBudgetExceeded, f7.F7TerminalError)


def _write_quota_checkpoint(path: Path, *, date: str, official: int, additional: int):
    path.write_text(json.dumps({
        "date": date,
        "quota": {
            "official_usage_before": official,
            "additional_opendart_requests": additional,
            "max_additional_requests_today": 39_000,
        },
        "request_accounting": {"counter_consistent": True},
    }), encoding="utf-8")


def test_same_day_quota_resume_preserves_prior_additional(tmp_path: Path):
    checkpoint = tmp_path / "daily_quota_checkpoint.json"
    _write_quota_checkpoint(checkpoint, date="2026-09-09", official=0, additional=12_000)
    context = f7._load_remaining_quota_context(
        checkpoint,
        run_date="2026-09-09",
        daily_usage_before_run=None,
    )
    assert context == {
        "official_usage_before": 0,
        "prior_additional_requests": 12_000,
        "max_additional_requests": 39_000,
    }


def test_next_day_quota_reset_drops_previous_additional(tmp_path: Path):
    checkpoint = tmp_path / "daily_quota_checkpoint.json"
    _write_quota_checkpoint(checkpoint, date="2026-09-08", official=0, additional=8_000)
    context = f7._load_remaining_quota_context(
        checkpoint,
        run_date="2026-09-09",
        daily_usage_before_run=0,
    )
    assert context == {
        "official_usage_before": 0,
        "prior_additional_requests": 0,
        "max_additional_requests": 39_000,
    }


def test_date_rollover_keeps_completed_output_reusable(tmp_path: Path):
    output = tmp_path / "000020.json"
    payload = {
        "runner_version": f7.RUNNER_VERSION,
        "ticker": "000020",
        "requested_as_of": "2026-09-04",
        "asset_type": "ETF",
        "terminal_status": "NOT_APPLICABLE",
    }
    serialized = json.dumps(payload)
    output.write_text(serialized, encoding="utf-8")
    value = f7._load_existing(output, ticker="000020", requested_as_of="2026-09-04")
    assert value == payload
    assert output.read_text(encoding="utf-8") == serialized


def test_dynamic_daily_baseline_calculates_available_budget(tmp_path: Path):
    context = f7._load_remaining_quota_context(
        tmp_path / "missing.json",
        run_date="2026-09-09",
        daily_usage_before_run=2_000,
    )
    assert context["official_usage_before"] == 2_000
    assert context["prior_additional_requests"] == 0
    assert context["max_additional_requests"] == 37_000


def test_new_day_without_daily_usage_is_blocked_before_hydration(tmp_path: Path):
    with pytest.raises(RuntimeError, match="daily_usage_before_run"):
        f7._load_remaining_quota_context(
            tmp_path / "missing.json",
            run_date="2026-09-09",
            daily_usage_before_run=None,
        )
