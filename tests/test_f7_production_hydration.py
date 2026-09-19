from __future__ import annotations

import importlib.util
import inspect
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


@pytest.mark.parametrize(
    ("universe", "completed_rows", "start_completed", "expected_status"),
    [
        (
            [{"ticker": "000020", "asset_type": "ETF"}, {"ticker": "000040", "asset_type": "ETF"}],
            [{"ticker": "000020", "asset_type": "ETF", "terminal_status": "NOT_APPLICABLE"}],
            {"000020"},
            "IN_PROGRESS",
        ),
        (
            [{"ticker": "000020", "asset_type": "ETF"}],
            [{"ticker": "000020", "asset_type": "ETF", "terminal_status": "NOT_APPLICABLE"}],
            {"000020"},
            "COMPLETE",
        ),
    ],
)
def test_remaining_checkpoint_status_reflects_end_remaining(
    universe, completed_rows, start_completed, expected_status,
):
    client = SimpleNamespace(
        audit=[],
        http_request_count=0,
        current_additional_requests=0,
        estimated_daily_total=0,
    )
    checkpoint = f7._remaining_quota_checkpoint(
        completed_rows=completed_rows,
        universe=universe,
        start_completed_tickers=start_completed,
        run_date="2026-09-10",
        official_usage_before=0,
        max_additional_budget=39_000,
        requested_as_of="2026-09-04",
        metadata_snapshot_date="2026-09-04",
        started_at="2026-09-10T00:00:00+09:00",
        completed_at="2026-09-10T00:00:01+09:00",
        client=client,
        stop_reason="TARGET_SET_EXHAUSTED",
    )
    assert checkpoint["end_remaining"] == (0 if expected_status == "COMPLETE" else 1)
    assert checkpoint["status"] == expected_status


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


# --- Phase 3B: target_as_of generalization (w.md §15 T1~T7) ------------------


def test_t1_run_requires_explicit_requested_as_of_not_scanner_summary():
    """T1: run()이 requested_as_of를 명시적으로 받고, scanner summary에서 읽지 않는다."""
    assert not hasattr(f7, "_load_requested_as_of")
    assert not hasattr(f7, "SCAN_SUMMARY_PATH")
    parameters = inspect.signature(f7.run).parameters
    assert "requested_as_of" in parameters
    assert parameters["requested_as_of"].kind == inspect.Parameter.KEYWORD_ONLY
    assert parameters["requested_as_of"].default is inspect.Parameter.empty


def test_t2_missing_as_of_fails_argparse():
    """T2: --as-of 없이 실행하면 argparse가 즉시 실패한다(오늘 날짜 fallback 금지)."""
    with pytest.raises(SystemExit):
        f7._build_parser().parse_args(["--pilot"])


def test_t2_explicit_as_of_is_parsed():
    args = f7._build_parser().parse_args(["--pilot", "--as-of", "2026-09-17"])
    assert args.as_of == "2026-09-17"


def test_t2_invalid_as_of_format_fails_closed():
    with pytest.raises(RuntimeError, match="YYYY-MM-DD"):
        f7._resolve_requested_as_of("2026/09/17")
    with pytest.raises(RuntimeError, match="YYYY-MM-DD"):
        f7._resolve_requested_as_of("not-a-date")


def test_t3_dynamic_output_date_not_fixed_20260904():
    """T3: 출력 경로가 requested_as_of 기준으로 동적이며 20260904에 고정되지 않는다."""
    assert f7._output_dir("2026-09-17") == f7.OUTPUT_ROOT / "20260917"
    assert f7._output_dir("2026-09-17") != f7.OUTPUT_ROOT / "20260904"
    # 기존 2026-09-04 의미도 그대로 재현되어야 한다(특별 취급 상수 없이).
    assert f7._output_dir("2026-09-04") == f7.OUTPUT_ROOT / "20260904"


def test_t4_dynamic_priority_path_matches_requested_as_of(tmp_path: Path, monkeypatch):
    """T4: priority 파일 경로와 내부 effective_date가 requested_as_of와 정확히 일치해야 한다."""
    monkeypatch.setattr(f7, "PRIORITY_MARKET_DIR", tmp_path)
    (tmp_path / "krx_market_cap_20260917.csv").write_text(
        "ticker,close,market_cap,effective_date\n"
        "005930,80000,500000000000,2026-09-17\n",
        encoding="utf-8",
    )
    universe = [{"ticker": "005930", "asset_type": "COMMON"}]

    priority, info = f7._load_priority_tickers(universe, "2026-09-17")

    assert priority == {"005930"}
    assert info["market_date"] == "2026-09-17"
    assert info["market_file"].endswith("krx_market_cap_20260917.csv")


def test_t4_only_exact_requested_date_file_is_consulted(tmp_path: Path, monkeypatch):
    """T4: 다른 날짜(예: 20260904)의 기존 파일이 있어도 fallback으로 쓰지 않는다."""
    monkeypatch.setattr(f7, "PRIORITY_MARKET_DIR", tmp_path)
    (tmp_path / "krx_market_cap_20260904.csv").write_text(
        "ticker,close,market_cap,effective_date\n"
        "005930,80000,500000000000,2026-09-04\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing"):
        f7._load_priority_tickers([{"ticker": "005930", "asset_type": "COMMON"}], "2026-09-17")


def test_t5_priority_wrong_internal_date_fails_closed(tmp_path: Path, monkeypatch):
    """T5: 파일명은 20260917인데 내부 effective_date가 2026-09-04면 fail closed."""
    monkeypatch.setattr(f7, "PRIORITY_MARKET_DIR", tmp_path)
    (tmp_path / "krx_market_cap_20260917.csv").write_text(
        "ticker,close,market_cap,effective_date\n"
        "005930,80000,500000000000,2026-09-04\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="2026-09-17 snapshot"):
        f7._load_priority_tickers([{"ticker": "005930", "asset_type": "COMMON"}], "2026-09-17")


def test_t6_cross_target_output_is_not_reused(tmp_path: Path):
    """T6: 다른 requested_as_of의 기존 ticker 결과는 새 target에서 재사용되지 않는다."""
    path = tmp_path / "000020.json"
    path.write_text(json.dumps({
        "runner_version": f7.RUNNER_VERSION,
        "ticker": "000020",
        "requested_as_of": "2026-09-04",
        "asset_type": "COMMON",
        "terminal_status": "PASS",
    }), encoding="utf-8")

    same_target = f7._load_existing(path, ticker="000020", requested_as_of="2026-09-04")
    other_target = f7._load_existing(path, ticker="000020", requested_as_of="2026-09-17")

    assert same_target is not None
    assert other_target is None


# --- FilingRegistry incremental window fix (w.md T1~T7) ---------------------


def _filing_row(
    *, ticker: str, corp_code: str, corp_name: str, bsns_year: str, reprt_code: str,
    rcept_no: str, rcept_dt: str, report_nm: str = "사업보고서", report_type: str = "PERIODIC",
    correction_flag: bool = False, fs_div: str | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker, "corp_code": corp_code, "corp_name": corp_name,
        "bsns_year": bsns_year, "reprt_code": reprt_code, "report_type": report_type,
        "report_nm": report_nm, "rcept_no": rcept_no, "rcept_dt": rcept_dt,
        "filing_chain_key": f"{corp_code}:{bsns_year}:{reprt_code}:{report_nm}",
        "correction_flag": correction_flag, "source_retrieved_at": "2026-01-01T00:00:00+00:00",
        "fs_div": fs_div,
    }


def _seed_cache(
    cache_dir: Path, *, corp_code: str, fiscal_year: str, reprt_code: str,
    coverage_end: str, rows: list[dict] | None = None,
) -> None:
    """Write a valid FilingRegistry cache file directly (no bootstrap needed to create it)."""
    payload = {
        "metadata": {
            "corp_code": corp_code, "bsns_year": fiscal_year, "reprt_code": reprt_code,
            "requested_as_of": coverage_end,
            "coverage_start": f"{int(fiscal_year):04d}-01-01",
            "coverage_end": coverage_end,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "page_count_requested": 100, "pages_fetched": 1, "window_count": 1,
            "total_count": len(rows or []), "total_page": 1,
            "http_status": 200, "api_status": "000", "source_sha256": "seed",
            "record_count": len(rows or []), "cache_complete": True, "cache_hit": False,
        },
        "filings": list(rows or []),
    }
    (cache_dir / f"{corp_code}_{fiscal_year}_{reprt_code}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )


def _seed_year(
    cache_dir: Path, *, corp_code: str, fiscal_year: str, coverage_end: str,
    rows_by_code: dict[str, list[dict]] | None = None,
) -> None:
    """Seed all four report-code caches for one fiscal year so the year is not a bootstrap target."""
    rows_by_code = rows_by_code or {}
    for reprt_code in f7.REGULAR_REPORT_CODES:
        _seed_cache(
            cache_dir, corp_code=corp_code, fiscal_year=fiscal_year, reprt_code=reprt_code,
            coverage_end=coverage_end, rows=rows_by_code.get(reprt_code, []),
        )


def _raw_row(*, report_nm: str, rcept_no: str, rcept_dt: str, corp_code: str = "123456",
             corp_name: str = "테스트") -> dict[str, str]:
    return {"corp_code": corp_code, "corp_name": corp_name, "report_nm": report_nm,
            "rcept_no": rcept_no, "rcept_dt": rcept_dt}


class ScriptedBoundedRegistry(f7.BoundedFilingRegistry):
    """A BoundedFilingRegistry whose ``_fetch_pages`` returns scripted rows per exact window."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        window_rows: dict[tuple[str, str], list[dict]] | None = None,
        window_errors: dict[tuple[str, str], tuple[str, str, int]] | None = None,
    ):
        super().__init__(object(), cache_dir=cache_dir)
        self.fetch_calls: list[dict[str, str]] = []
        self._window_rows = window_rows or {}
        self._window_errors = window_errors or {}

    def _fetch_pages(self, *, corp_code: str, bgn_de: str, end_de: str, page_count: int = 100):
        self.fetch_calls.append({"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de})
        error = self._window_errors.get((bgn_de, end_de))
        if error is not None:
            status, classification, http_status = error
            raise f7.FilingRegistryApiError(
                f"scripted OpenDART error status={status}",
                status=status, classification=classification, http_status=http_status,
            )
        rows = self._window_rows.get((bgn_de, end_de), [])
        payload = {"status": "000", "list": rows, "total_page": 1, "total_count": len(rows)}
        raw = json.dumps(payload, sort_keys=True).encode()
        response = f7.JsonResponse(
            payload, raw, 200, "application/json", "https://example/list.json", "000", "PASS",
        )
        return list(rows), [response], len(rows), 1


def test_filing_delta_t1_stale_valid_cache_uses_one_delta_window(tmp_path: Path):
    """T1: 여러 회계연도 캐시가 모두 유효하면 전체 재조회 없이 ticker당 delta 1회만 조회한다."""
    for fiscal_year in ("2024", "2025"):
        _seed_year(tmp_path, corp_code="123456", fiscal_year=fiscal_year, coverage_end="2026-09-04")
    registry = ScriptedBoundedRegistry(tmp_path)

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17",
        fiscal_years=("2024", "2025"),
    )

    assert registry.preload_year_fetches == 0
    assert registry.preload_delta_fetches == 1
    assert registry.fetch_calls == [{"corp_code": "123456", "bgn_de": "20260905", "end_de": "20260917"}]
    for fiscal_year in ("2024", "2025"):
        for reprt_code in f7.REGULAR_REPORT_CODES:
            cache = json.loads((tmp_path / f"123456_{fiscal_year}_{reprt_code}.json").read_text())
            assert cache["metadata"]["coverage_end"] == "2026-09-17"


def test_filing_delta_t2_distributes_by_bsns_year_and_reprt_code(tmp_path: Path):
    """T2: delta 응답의 신규/정정 filing이 각자의 (bsns_year, reprt_code) 버킷에 정확히 merge된다."""
    existing_2023 = _filing_row(
        ticker="TEST01", corp_code="123456", corp_name="테스트", bsns_year="2023", reprt_code="11011",
        report_nm="사업보고서 (2023.12)", rcept_no="20230301000000", rcept_dt="20230301",
    )
    _seed_year(
        tmp_path, corp_code="123456", fiscal_year="2023", coverage_end="2026-09-04",
        rows_by_code={"11011": [existing_2023]},
    )
    _seed_year(tmp_path, corp_code="123456", fiscal_year="2026", coverage_end="2026-09-04")

    new_2026_filing = _raw_row(report_nm="사업보고서", rcept_no="20260910000001", rcept_dt="20260910")
    correction_2023_filing = _raw_row(
        report_nm="사업보고서 (2023.12 기재정정)", rcept_no="20260912000002", rcept_dt="20260912",
    )
    registry = ScriptedBoundedRegistry(
        tmp_path, window_rows={("20260905", "20260917"): [new_2026_filing, correction_2023_filing]},
    )

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17",
        fiscal_years=("2023", "2026"),
    )

    cache_2023 = json.loads((tmp_path / "123456_2023_11011.json").read_text())
    cache_2026 = json.loads((tmp_path / "123456_2026_11011.json").read_text())
    assert {row["rcept_no"] for row in cache_2023["filings"]} == {"20230301000000", "20260912000002"}
    assert {row["rcept_no"] for row in cache_2026["filings"]} == {"20260910000001"}
    assert cache_2023["metadata"]["coverage_end"] == "2026-09-17"
    assert cache_2026["metadata"]["coverage_end"] == "2026-09-17"


def test_filing_delta_t3_empty_delta_advances_coverage_without_failure(tmp_path: Path):
    """T3: delta에 신규 filing이 없어도 실패가 아니며 rows는 보존되고 coverage_end만 전진한다."""
    existing = _filing_row(
        ticker="TEST01", corp_code="123456", corp_name="테스트", bsns_year="2025", reprt_code="11011",
        report_nm="사업보고서 (2025.12)", rcept_no="20250301000000", rcept_dt="20250301",
    )
    _seed_year(
        tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04",
        rows_by_code={"11011": [existing]},
    )
    registry = ScriptedBoundedRegistry(tmp_path, window_rows={("20260905", "20260917"): []})

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )

    cache = json.loads((tmp_path / "123456_2025_11011.json").read_text())
    assert [row["rcept_no"] for row in cache["filings"]] == ["20250301000000"]
    assert cache["metadata"]["coverage_end"] == "2026-09-17"
    assert len(registry.fetch_calls) == 1

    # Same target again: every required cache now has coverage_end == target, so network 0.
    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )
    assert len(registry.fetch_calls) == 1


def test_filing_delta_t4_conflicting_rcept_no_is_fail_closed(tmp_path: Path):
    """T4: 같은 rcept_no가 기존 캐시와 의미 충돌하면 fail closed되고 기존 캐시는 손상되지 않는다."""
    existing = _filing_row(
        ticker="TEST01", corp_code="123456", corp_name="테스트", bsns_year="2025", reprt_code="11011",
        report_nm="사업보고서 (2025.12)", rcept_no="20250301000000", rcept_dt="20250301",
    )
    _seed_year(
        tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04",
        rows_by_code={"11011": [existing]},
    )
    before = (tmp_path / "123456_2025_11011.json").read_text()
    conflicting = _raw_row(
        report_nm="사업보고서 (2025.12)", rcept_no="20250301000000", rcept_dt="20250302",
    )
    registry = ScriptedBoundedRegistry(
        tmp_path, window_rows={("20260905", "20260917"): [conflicting]},
    )

    with pytest.raises(f7.FilingRegistryConflictError):
        registry.preload_ticker(
            ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
        )

    assert (tmp_path / "123456_2025_11011.json").read_text() == before
    for reprt_code in f7.REGULAR_REPORT_CODES:
        cache = json.loads((tmp_path / f"123456_2025_{reprt_code}.json").read_text())
        assert cache["metadata"]["coverage_end"] == "2026-09-04"


def test_filing_delta_t5_uneven_frontier_uses_earliest_safe_start(tmp_path: Path):
    """T5: 캐시별 coverage_end가 달라도 전체 재조회 없이 가장 이른 frontier 이후만 조회한다."""
    rows_by_code = {}
    for reprt_code in f7.REGULAR_REPORT_CODES:
        coverage_end = "2026-09-03" if reprt_code == "11011" else "2026-09-04"
        _seed_cache(
            tmp_path, corp_code="123456", fiscal_year="2025", reprt_code=reprt_code,
            coverage_end=coverage_end, rows=rows_by_code.get(reprt_code, []),
        )
    registry = ScriptedBoundedRegistry(tmp_path)

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )

    assert registry.fetch_calls == [{"corp_code": "123456", "bgn_de": "20260904", "end_de": "20260917"}]
    for reprt_code in f7.REGULAR_REPORT_CODES:
        cache = json.loads((tmp_path / f"123456_2025_{reprt_code}.json").read_text())
        assert cache["metadata"]["coverage_end"] == "2026-09-17"


def test_filing_delta_t6_missing_year_still_bootstraps_others_use_delta(tmp_path: Path):
    """T6: 일부 회계연도 캐시가 없으면 그 연도만 기존 bootstrap 의미를 유지하고, 나머지 유효 연도는 delta로 처리한다."""
    _seed_year(tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04")
    # 2024: only three of the four report codes exist; the missing one forces a full bootstrap for 2024.
    codes = list(f7.REGULAR_REPORT_CODES)
    for reprt_code in codes[:-1]:
        _seed_cache(
            tmp_path, corp_code="123456", fiscal_year="2024", reprt_code=reprt_code,
            coverage_end="2026-09-04",
        )
    bootstrap_row = _raw_row(report_nm="사업보고서 (2024.12)", rcept_no="20240301000000", rcept_dt="20240301")
    registry = ScriptedBoundedRegistry(
        tmp_path,
        window_rows={
            ("20240101", "20260917"): [bootstrap_row],
            ("20260905", "20260917"): [],
        },
    )

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17",
        fiscal_years=("2024", "2025"),
    )

    assert registry.preload_year_fetches == 1
    assert registry.preload_delta_fetches == 1
    for reprt_code in f7.REGULAR_REPORT_CODES:
        cache_2024 = json.loads((tmp_path / f"123456_2024_{reprt_code}.json").read_text())
        cache_2025 = json.loads((tmp_path / f"123456_2025_{reprt_code}.json").read_text())
        assert cache_2024["metadata"]["coverage_end"] == "2026-09-17"
        assert cache_2025["metadata"]["coverage_end"] == "2026-09-17"


def test_filing_delta_t7_same_target_fetches_and_writes_nothing(tmp_path: Path):
    """T7: 모든 필요 캐시의 coverage_end가 이미 target이면 fetch 0, write 0이다."""
    _seed_year(tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-17")
    registry = ScriptedBoundedRegistry(tmp_path)
    before = {
        reprt_code: (tmp_path / f"123456_2025_{reprt_code}.json").stat().st_mtime_ns
        for reprt_code in f7.REGULAR_REPORT_CODES
    }

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )

    assert registry.fetch_calls == []
    assert registry.preload_year_fetches == 0
    assert registry.preload_delta_fetches == 0
    for reprt_code in f7.REGULAR_REPORT_CODES:
        assert (tmp_path / f"123456_2025_{reprt_code}.json").stat().st_mtime_ns == before[reprt_code]


def test_filing_delta_013_empty_delta_advances_coverage_without_error(tmp_path: Path):
    """013 Fix T1: 실제 OpenDART 013(DATA_NOT_FOUND)도 정상 empty delta로 처리된다."""
    existing = _filing_row(
        ticker="TEST01", corp_code="123456", corp_name="테스트", bsns_year="2025", reprt_code="11011",
        report_nm="사업보고서 (2025.12)", rcept_no="20250301000000", rcept_dt="20250301",
    )
    _seed_year(
        tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04",
        rows_by_code={"11011": [existing]},
    )
    registry = ScriptedBoundedRegistry(
        tmp_path, window_errors={("20260905", "20260917"): ("013", "DATA_NOT_FOUND", 200)},
    )

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )

    for reprt_code in f7.REGULAR_REPORT_CODES:
        cache = json.loads((tmp_path / f"123456_2025_{reprt_code}.json").read_text())
        assert cache["metadata"]["coverage_end"] == "2026-09-17"
        assert cache["metadata"]["requested_as_of"] == "2026-09-17"
    cache_11011 = json.loads((tmp_path / "123456_2025_11011.json").read_text())
    assert [row["rcept_no"] for row in cache_11011["filings"]] == ["20250301000000"]


def test_filing_delta_013_then_same_target_is_idempotent(tmp_path: Path):
    """013 Fix T2: 013 empty delta로 coverage가 전진한 뒤 같은 target 재실행은 network/write 0이다."""
    _seed_year(tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04")
    registry = ScriptedBoundedRegistry(
        tmp_path, window_errors={("20260905", "20260917"): ("013", "DATA_NOT_FOUND", 200)},
    )

    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )
    assert len(registry.fetch_calls) == 1

    before = {
        reprt_code: (tmp_path / f"123456_2025_{reprt_code}.json").stat().st_mtime_ns
        for reprt_code in f7.REGULAR_REPORT_CODES
    }
    registry.preload_ticker(
        ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
    )

    assert len(registry.fetch_calls) == 1  # no additional fetch
    for reprt_code in f7.REGULAR_REPORT_CODES:
        assert (tmp_path / f"123456_2025_{reprt_code}.json").stat().st_mtime_ns == before[reprt_code]


@pytest.mark.parametrize(
    "status, classification, http_status",
    [
        ("020", "RATE_LIMIT", 200),
        ("800", "SERVICE", 200),
        ("014", "REQUEST", 200),
    ],
)
def test_filing_delta_non_013_errors_fail_closed(
    tmp_path: Path, status: str, classification: str, http_status: int,
):
    """013 Fix T3: 013 이외의 상태(RATE_LIMIT/SERVICE/REQUEST 등)는 여전히 fail closed다."""
    _seed_year(tmp_path, corp_code="123456", fiscal_year="2025", coverage_end="2026-09-04")
    before = (tmp_path / "123456_2025_11011.json").read_text()
    registry = ScriptedBoundedRegistry(
        tmp_path, window_errors={("20260905", "20260917"): (status, classification, http_status)},
    )

    with pytest.raises(f7.FilingRegistryApiError):
        registry.preload_ticker(
            ticker="TEST01", corp_code="123456", requested_as_of="2026-09-17", fiscal_years=("2025",),
        )

    assert (tmp_path / "123456_2025_11011.json").read_text() == before
    for reprt_code in f7.REGULAR_REPORT_CODES:
        cache = json.loads((tmp_path / f"123456_2025_{reprt_code}.json").read_text())
        assert cache["metadata"]["coverage_end"] == "2026-09-04"
