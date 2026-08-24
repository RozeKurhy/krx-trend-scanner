from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded
from trend_scanner.data.krx_openapi_client import KrxOpenApiAuthorizationError
from trend_scanner.data.krx_raw_stock_provider import KrxRawStockSnapshotError, RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.krx_historical_backfill import BLOCKER_PRIORITY, KrxHistoricalBackfillRunner, candidate_dates
from scripts import validate_krx_historical_backfill_v01 as validation
from scripts.validate_krx_historical_backfill_v01 import FIX_START_HEAD, _coverage, _is_current_evidence, _load_legacy_live_evidence, _samsung_evidence, _schema_evidence_status, _validation_source_head, pilot_parameters, pilot_status


def _frame(day, ticker):
    return pd.DataFrame([{
        "date": pd.Timestamp(day), "ticker": ticker, "open": 100, "high": 110, "low": 90, "close": 105,
        "volume": 1000, "trading_value": 2000, "market_cap": 3000, "listed_shares": 4000,
    }], columns=list(RAW_COLUMNS))


class _Provider:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.calls = []

    def fetch_market_snapshot(self, market, day):
        self.calls.append((market, day))
        if self.mode == "both-empty":
            return _frame(day, "005930").iloc[0:0].copy()
        if self.mode == "asymmetric" and market == "KOSDAQ":
            return _frame(day, "005930").iloc[0:0].copy()
        return _frame(day, "005930" if market == "KOSPI" else "000660")


class _QuotaProvider(_Provider):
    def fetch_market_snapshot(self, market, day):
        raise KrxOpenApiQuotaExceeded(
            "quota",
            endpoint_key="stk_bydd_trd",
            usage_date_kst="2026-08-21",
            endpoint_before=1,
            global_before=1,
        )


class _ErrorProvider(_Provider):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def fetch_market_snapshot(self, market, day):
        self.calls.append((market, day))
        raise self.error


class _DiagnosticClient:
    def __init__(self, *args, **kwargs):
        self.request_count = 0
        self.retry_count = 0
        self.status_counts = {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0}
        self.audit = []


class _DiagnosticProvider:
    outcomes = {}
    client = None

    def __init__(self, client):
        type(self).client = client

    def fetch_market_snapshot(self, market, day):
        self.client.request_count += 1
        self.client.audit.append({"endpoint_key": validation.MARKET_ENDPOINTS[market].strip("/"), "http_status": 200, "record_count": 1, "top_level_keys": ["OutBlock_1"], "error_type": None})
        outcome = type(self).outcomes[market]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _run_diagnostic(monkeypatch, outcomes):
    _DiagnosticProvider.outcomes = outcomes
    monkeypatch.setattr(validation, "load_auth_key", lambda: "test-key")
    monkeypatch.setattr(validation, "KrxOpenApiClient", _DiagnosticClient)
    monkeypatch.setattr(validation, "KrxRawStockSnapshotProvider", _DiagnosticProvider)
    return validation._live_diagnostic(validation._base_counters())


class _EvidenceStore:
    def __init__(self, frames=None, missing=False):
        self.frames = frames or {}
        self.missing = missing

    def load_snapshot(self, market, day):
        if self.missing or day not in self.frames:
            raise FileNotFoundError(day)
        return self.frames[day]


def _runner(tmp_path, provider):
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
    return KrxHistoricalBackfillRunner(provider, KrxRawStockStore(tmp_path / "raw"), quota), quota


def test_candidate_dates_are_weekdays_only():
    assert candidate_dates("2026-08-21", "2026-08-24") == ["2026-08-21", "2026-08-24"]


def test_live_diagnostic_contract_is_one_date_two_requests_without_retry():
    parameters = pilot_parameters(diagnostic_only=True)
    assert parameters["dates"] == ("2018-04-27",)
    assert parameters["markets"] == ("KOSPI", "KOSDAQ")
    assert parameters["request_budget"] == 2
    assert parameters["max_transient_retries"] == 0


def test_live_pilot_contract_remains_three_dates_and_six_requests():
    parameters = pilot_parameters()
    assert parameters["dates"] == ("2018-04-27", "2018-05-04", "2026-08-21")
    assert parameters["request_budget"] == 6
    assert parameters["max_transient_retries"] == 0


def test_live_diagnostic_schema_failure_still_attempts_second_market(monkeypatch):
    first = KrxRawStockSnapshotError("RAW_SNAPSHOT_REQUIRED_FIELD_MISSING")
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": first, "KOSDAQ": _frame("2018-04-27", "000660")})
    assert summary["per_market"]["KOSPI"]["attempted"] is True
    assert summary["per_market"]["KOSDAQ"]["attempted"] is True
    assert summary["request_count"] == 2
    assert summary["status"] == "BLOCKED_KRX_SCHEMA"


def test_live_diagnostic_transport_failure_still_attempts_second_market(monkeypatch):
    first = KrxRawStockSnapshotError("RAW_SNAPSHOT_HTTP_STATUS", diagnostic={"http_status": 503})
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": first, "KOSDAQ": _frame("2018-04-27", "000660")})
    assert summary["per_market"]["KOSPI"]["attempted"] is True
    assert summary["per_market"]["KOSDAQ"]["attempted"] is True
    assert summary["request_count"] == 2
    assert summary["status"] == "BLOCKED_KRX_TRANSPORT"


def test_live_diagnostic_second_market_schema_failure_is_blocker(monkeypatch):
    second = KrxRawStockSnapshotError("RAW_SNAPSHOT_REQUIRED_FIELD_MISSING")
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": _frame("2018-04-27", "005930"), "KOSDAQ": second})
    assert summary["request_count"] == 2
    assert summary["status"] == "BLOCKED_KRX_SCHEMA"


def test_live_diagnostic_auth_stops_second_market(monkeypatch):
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": KrxOpenApiAuthorizationError("401"), "KOSDAQ": _frame("2018-04-27", "000660")})
    assert summary["per_market"]["KOSPI"]["attempted"] is True
    assert summary["per_market"]["KOSDAQ"]["attempted"] is False
    assert summary["request_count"] == 1
    assert summary["status"] == "BLOCKED_KRX_AUTH"


def test_live_diagnostic_quota_stops_second_market(monkeypatch):
    quota_error = KrxOpenApiQuotaExceeded("quota", endpoint_key="stk_bydd_trd", usage_date_kst="2026-08-25", endpoint_before=1, global_before=1)
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": quota_error, "KOSDAQ": _frame("2018-04-27", "000660")})
    assert summary["per_market"]["KOSPI"]["attempted"] is True
    assert summary["per_market"]["KOSDAQ"]["attempted"] is False
    assert summary["request_count"] == 1
    assert summary["status"] == "BACKFILL_PAUSED_QUOTA"


def test_live_diagnostic_both_markets_pass(monkeypatch):
    summary, _ = _run_diagnostic(monkeypatch, {"KOSPI": _frame("2018-04-27", "005930"), "KOSDAQ": _frame("2018-04-27", "000660")})
    assert all(summary["per_market"][market]["attempted"] for market in ("KOSPI", "KOSDAQ"))
    assert summary["request_count"] == 2
    assert summary["retry_count"] == 0
    assert summary["status"] == "PASS"


def test_samsung_exact_evidence_passes_for_two_fixed_dates():
    frames = {
        "2018-04-27": _frame("2018-04-27", "005930").assign(listed_shares=128386494),
        "2018-05-04": _frame("2018-05-04", "005930").assign(listed_shares=6419324700),
    }
    evidence = _samsung_evidence(_EvidenceStore(frames), ("2018-04-27", "2018-05-04", "2026-08-21"))
    assert evidence["status"] == "PASS"
    assert all(item["match"] and item["ticker_found"] for item in evidence["observations"])


def test_samsung_mismatch_blocks_after_two_dates():
    frames = {
        "2018-04-27": _frame("2018-04-27", "005930").assign(listed_shares=1),
        "2018-05-04": _frame("2018-05-04", "005930").assign(listed_shares=6419324700),
    }
    evidence = _samsung_evidence(_EvidenceStore(frames), ("2018-04-27", "2018-05-04"))
    assert evidence["status"] == "MISMATCH"
    assert evidence["blockers"] == ["BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE"]


def test_samsung_missing_ticker_blocks_after_two_dates():
    frames = {
        "2018-04-27": _frame("2018-04-27", "005930").assign(listed_shares=128386494),
        "2018-05-04": _frame("2018-05-04", "000660"),
    }
    evidence = _samsung_evidence(_EvidenceStore(frames), ("2018-04-27", "2018-05-04"))
    assert evidence["status"] == "MISMATCH"
    assert evidence["observations"][1]["ticker_found"] is False


def test_samsung_missing_snapshot_blocks_after_two_dates():
    evidence = _samsung_evidence(_EvidenceStore(missing=True), ("2018-04-27", "2018-05-04"))
    assert evidence["status"] == "MISMATCH"
    assert all(item["snapshot_available"] is False for item in evidence["observations"])


def test_samsung_2026_date_is_not_lookup_target():
    evidence = _samsung_evidence(_EvidenceStore(missing=True), ("2026-08-21",))
    assert evidence["status"] == "NOT_RUN"
    assert evidence["observations"] == []


def test_samsung_diagnostic_partial_evidence_is_allowed():
    frames = {"2018-04-27": _frame("2018-04-27", "005930").assign(listed_shares=128386494)}
    evidence = _samsung_evidence(_EvidenceStore(frames), ("2018-04-27",))
    assert evidence["status"] == "PARTIAL_EVIDENCE"
    assert evidence["blockers"] == []


def test_legacy_live_evidence_does_not_become_current_fix04(tmp_path):
    (tmp_path / "live_pilot_summary.json").write_text('{"mode":"live-pilot","status":"BLOCKED_KRX_SCHEMA"}\n', encoding="utf-8")
    legacy = _load_legacy_live_evidence(tmp_path)
    assert legacy["legacy"] is True
    assert _is_current_evidence(legacy, "live-pilot") is False


def test_current_diagnostic_metadata_is_generation_scoped():
    current = {"validation_generation": "FIX04", "mode": "live-diagnostic", "legacy": False}
    assert _is_current_evidence(current, "live-diagnostic") is True
    assert _is_current_evidence(current, "live-pilot") is False


def test_current_diagnostic_pass_overrides_legacy_schema_status():
    assert _schema_evidence_status({"status": "PASS", "diagnostics": []}) == "NO_SCHEMA_BLOCKER"


def test_current_diagnostic_transport_does_not_become_schema():
    assert _schema_evidence_status({"status": "BLOCKED_KRX_TRANSPORT", "diagnostics": []}) == "NO_SCHEMA_CONCLUSION_TRANSPORT_BLOCKED"


def test_current_live_pilot_not_run_is_not_satisfied_by_legacy_summary():
    legacy = {"mode": "live-pilot", "status": "BLOCKED_KRX_SCHEMA"}
    current = {"validation_generation": "FIX04", "mode": "live-pilot", "legacy": False, "status": "NOT_RUN"}
    assert _is_current_evidence(legacy, "live-pilot") is False
    assert _is_current_evidence(current, "live-pilot") is True
    assert current["status"] == "NOT_RUN"


def test_fix04_provenance_start_head_is_frozen():
    assert FIX_START_HEAD == "ca9b5e6eabbad693fb10a829a241b28b82de879b"


def test_artifact_only_dirty_state_preserves_source_provenance(monkeypatch):
    monkeypatch.setattr(
        "scripts.validate_krx_historical_backfill_v01.subprocess.check_output",
        lambda command, **kwargs: " M artifacts/data/krx_historical_backfill/v01/krx_historical_backfill_v01_summary.json" if command[1] == "status" else "",
    )
    assert _validation_source_head("abc123") == "abc123"


def test_http_503_is_transport_not_schema(tmp_path):
    provider = _ErrorProvider(KrxRawStockSnapshotError("RAW_SNAPSHOT_HTTP_STATUS", diagnostic={"http_status": 503}))
    runner, _ = _runner(tmp_path, provider)
    result = runner.run("2018-04-27", "2018-04-27", max_task_attempts=2)
    assert result["status"] == "BLOCKED_KRX_TRANSPORT"
    assert "BLOCKED_KRX_SCHEMA" not in result["blockers"]
    assert result["diagnostics"][0]["http_status"] == 503


def test_timeout_is_transport_not_schema(tmp_path):
    provider = _ErrorProvider(KrxRawStockSnapshotError("RAW_SNAPSHOT_HTTP_STATUS", diagnostic={"http_status": None, "transport_error_type": "TimeoutError"}))
    runner, _ = _runner(tmp_path, provider)
    result = runner.run("2018-04-27", "2018-04-27", max_task_attempts=2)
    assert result["status"] == "BLOCKED_KRX_TRANSPORT"
    assert "BLOCKED_KRX_SCHEMA" not in result["blockers"]


def test_auth_remains_auth(tmp_path):
    runner, _ = _runner(tmp_path, _ErrorProvider(KrxOpenApiAuthorizationError("401")))
    result = runner.run("2018-04-27", "2018-04-27", max_task_attempts=2)
    assert result["status"] == "BLOCKED_KRX_AUTH"


def test_actual_schema_error_remains_schema(tmp_path):
    runner, _ = _runner(tmp_path, _ErrorProvider(KrxRawStockSnapshotError("RAW_SNAPSHOT_REQUIRED_FIELD_MISSING")))
    result = runner.run("2018-04-27", "2018-04-27", max_task_attempts=2)
    assert result["status"] == "BLOCKED_KRX_SCHEMA"


def test_complete_date_fetches_both_markets_sequentially(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    result = runner.run("2026-08-21", "2026-08-21", max_task_attempts=2)
    assert result["status"].startswith("READY_")
    assert provider.calls == [("KOSPI", "2026-08-21"), ("KOSDAQ", "2026-08-21")]
    assert result["aggregate"]["complete_date_count"] == 1


def test_both_empty_becomes_no_data(tmp_path):
    runner, _ = _runner(tmp_path, _Provider("both-empty"))
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["aggregate"]["no_data_date_count"] == 1
    assert result["aggregate"]["failed_date_count"] == 0


def test_asymmetric_empty_is_failed_and_partial(tmp_path):
    runner, _ = _runner(tmp_path, _Provider("asymmetric"))
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert "BLOCKED_COVERAGE" in result["blockers"]
    assert result["aggregate"]["partial_date_count"] == 1


def test_resume_skips_complete_and_no_data(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    provider.calls.clear()
    result = runner.run("2020-01-03", "2020-01-03", resume=True, max_task_attempts=2)
    assert provider.calls == []
    assert result["aggregate"]["complete_date_count"] == 1


def test_recent_empty_is_not_checkpointed_and_general_resume_retries(tmp_path):
    provider = _Provider("both-empty")
    runner, _ = _runner(tmp_path, provider)
    first = runner.run("2026-08-24", "2026-08-24", max_task_attempts=2)
    assert first["recent_empty_unfinalized_count"] == 1
    assert runner.store.get_manifest("KOSPI", "2026-08-24") is None
    assert runner.store.get_manifest("KOSDAQ", "2026-08-24") is None
    provider.calls.clear()
    runner.run("2026-08-24", "2026-08-24", resume=True, max_task_attempts=2)
    assert provider.calls == [("KOSPI", "2026-08-24"), ("KOSDAQ", "2026-08-24")]


def test_partial_resume_fetches_only_missing_market(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    runner.store.save_snapshot("KOSPI", "2020-01-03", _frame("2020-01-03", "005930"), "/sto/stk_bydd_trd")
    provider.calls.clear()
    result = runner.run("2020-01-03", "2020-01-03", resume=True, max_task_attempts=1)
    assert provider.calls == [("KOSDAQ", "2020-01-03")]
    assert result["aggregate"]["complete_date_count"] == 1


def test_cross_market_conflict_is_counted(tmp_path):
    class _ConflictProvider(_Provider):
        def fetch_market_snapshot(self, market, day):
            self.calls.append((market, day))
            return _frame(day, "005930")

    runner, _ = _runner(tmp_path, _ConflictProvider())
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["aggregate"]["cross_market_ticker_conflict_count"] == 1
    assert not result["status"].startswith("READY_")
    assert "BLOCKED_CROSS_MARKET_TICKER_CONFLICT" in result["blockers"]


def test_integrity_error_cannot_ready(tmp_path):
    provider = _Provider()
    runner, _ = _runner(tmp_path, provider)
    runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    path = tmp_path / "raw" / "market=KOSPI" / "year=2020" / "2020-01-03.parquet"
    path.write_bytes(path.read_bytes() + b"corrupt")
    result = runner.run("2020-01-03", "2020-01-03", resume=True, max_task_attempts=2)
    assert result["aggregate"]["integrity_error_count"] > 0
    assert result["status"] == "BLOCKED_RAW_STORE_INTEGRITY"
    assert "BLOCKED_RAW_STORE_INTEGRITY" in result["blockers"]


@pytest.mark.parametrize(
    ("runner_blocker", "expected_status"),
    [
        ("BLOCKED_KRX_AUTH", "BLOCKED_KRX_AUTH"),
        ("BACKFILL_PAUSED_QUOTA", "BACKFILL_PAUSED_QUOTA"),
        ("BLOCKED_KRX_SCHEMA", "BLOCKED_KRX_SCHEMA"),
        ("BLOCKED_COVERAGE", "BLOCKED_COVERAGE"),
        ("BLOCKED_RAW_STORE_INTEGRITY", "BLOCKED_RAW_STORE_INTEGRITY"),
        ("BLOCKED_CROSS_MARKET_TICKER_CONFLICT", "BLOCKED_CROSS_MARKET_TICKER_CONFLICT"),
    ],
)
def test_pilot_preserves_actual_blocker(runner_blocker, expected_status):
    status, blockers = pilot_status([{"blockers": [runner_blocker]}])
    assert status == expected_status
    assert blockers == [expected_status]


def test_blocker_priority_includes_provenance_and_production_regression():
    assert "BLOCKED_PROVENANCE" in BLOCKER_PRIORITY
    assert "BLOCKED_PRODUCTION_REGRESSION" in BLOCKER_PRIORITY
    assert pilot_status([{"blockers": ["BLOCKED_PRODUCTION_REGRESSION", "BLOCKED_PROVENANCE"]}])[0] == "BLOCKED_PROVENANCE"


def test_validation_source_head_detects_dirty_source(monkeypatch):
    def fake_check_output(command, **kwargs):
        return " M src/trend_scanner/data/krx_historical_backfill.py" if command[1] == "status" else ""

    monkeypatch.setattr(
        "scripts.validate_krx_historical_backfill_v01.subprocess.check_output",
        fake_check_output,
    )
    assert _validation_source_head("abc123") == "WORKTREE_DIRTY"
    monkeypatch.setattr(
        "scripts.validate_krx_historical_backfill_v01.subprocess.check_output",
        lambda command, **kwargs: "" if command[1] == "status" else "",
    )
    assert _validation_source_head("abc123") == "abc123"


def test_coverage_gate_does_not_accept_one_complete_date(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_snapshot("KOSPI", "2026-08-21", _frame("2026-08-21", "005930"), "/sto/stk_bydd_trd")
    store.save_snapshot("KOSDAQ", "2026-08-21", _frame("2026-08-21", "000660"), "/sto/ksq_bydd_trd")
    coverage = _coverage(store, "2026-08-17", "2026-08-21")
    assert coverage["candidate_date_count"] == 5
    assert coverage["complete_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 4


def test_coverage_separates_failed_from_missing(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_failure("KOSPI", "2020-01-02", "/sto/stk_bydd_trd", "TEMPORARY", "retry")
    store.save_failure("KOSDAQ", "2020-01-02", "/sto/ksq_bydd_trd", "TEMPORARY", "retry")
    coverage = _coverage(store, "2020-01-02", "2020-01-02")
    assert coverage["failed_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 0
    assert coverage["unexplained_missing_partition_count"] == 0


def test_coverage_partial_and_missing_are_distinct(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    store.save_snapshot("KOSPI", "2020-01-02", _frame("2020-01-02", "005930"), "/sto/stk_bydd_trd")
    store.save_failure("KOSPI", "2020-01-03", "/sto/stk_bydd_trd", "TEMPORARY", "retry")
    coverage = _coverage(store, "2020-01-02", "2020-01-03")
    assert coverage["partial_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 2
    assert coverage["unexplained_missing_partition_count"] == 2


def test_coverage_gate_accepts_complete_and_finalized_no_data_pairs(tmp_path):
    store = KrxRawStockStore(tmp_path / "raw")
    for day in ("2020-01-02", "2020-01-03", "2020-01-06"):
        if day == "2020-01-03":
            empty = _frame(day, "005930").iloc[0:0].copy()
            store.save_snapshot("KOSPI", day, empty, "/sto/stk_bydd_trd")
            store.save_snapshot("KOSDAQ", day, empty, "/sto/ksq_bydd_trd")
        else:
            store.save_snapshot("KOSPI", day, _frame(day, "005930"), "/sto/stk_bydd_trd")
            store.save_snapshot("KOSDAQ", day, _frame(day, "000660"), "/sto/ksq_bydd_trd")
    coverage = _coverage(store, "2020-01-02", "2020-01-06")
    assert coverage["candidate_date_count"] == 3
    assert coverage["complete_date_count"] == 2
    assert coverage["finalized_no_data_date_count"] == 1
    assert coverage["unexplained_missing_date_count"] == 0


def test_task_budget_pauses_without_crashing(tmp_path):
    runner, _ = _runner(tmp_path, _Provider())
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=1)
    assert result["status"] == "BACKFILL_PAUSED_TASK_BUDGET"


def test_quota_pause_preserves_existing_partitions(tmp_path):
    provider = _QuotaProvider()
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=1, global_safety_limit=1)
    store = KrxRawStockStore(tmp_path / "raw")
    runner = KrxHistoricalBackfillRunner(provider, store, quota)
    result = runner.run("2020-01-03", "2020-01-03", max_task_attempts=2)
    assert result["status"] == "BACKFILL_PAUSED_QUOTA"
    assert store.get_manifest("KOSPI", "2020-01-03")["status"] == "FAILED"
