from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from trend_scanner.data.krx_historical_instrument_acquisition import (
    EXPECTED_PRIMARY_PAIRS,
    EXPECTED_TRADING_DATES,
    HISTORICAL_CALENDAR_DATE_SHA256,
    HISTORICAL_CALENDAR_PATH,
    HistoricalInstrumentAcquisitionRunner,
    InstrumentAcquisitionContractError,
    build_target_pairs,
    load_historical_trading_calendar,
    validate_historical_trading_dates,
    validate_basic_info_response,
)
from trend_scanner.data.krx_openapi_client import KrxOpenApiAuthorizationError, KrxOpenApiBudgetError, KrxOpenApiClient, KrxOpenApiRateLimitError
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_quota_reconciliation import (
    file_sha256,
    reconcile_historical_authority_discovery,
    reconcile_known_attempts,
    validate_historical_authority_discovery_evidence,
)


def _validated_weekdays(count: int) -> list[str]:
    values: list[str] = []
    current = date(2010, 1, 4)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def _payload(market: str = "KOSPI", *, ticker: str = "005930", sector: str = "전기전자") -> dict:
    return {
        "OutBlock_1": [{
            "ISU_CD": "KR7005930003",
            "ISU_SRT_CD": ticker,
            "MKT_TP_NM": market,
            "LIST_DD": "19750611",
            "SECUGRP_NM": "주권",
            "KIND_STKCERT_TP_NM": "보통주",
            "SECT_TP_NM": sector,
        }]
    }


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self.headers = {}
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def _client(tmp_path: Path, opener, *, reserve: int = 500, endpoint_limit: int = 1000, global_limit: int = 1000, max_requests: int = 80):
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=endpoint_limit, global_safety_limit=global_limit, reserve=reserve)
    client = KrxOpenApiClient("test-key", opener=opener, max_requests=max_requests, max_transient_retries=1, sleeper=lambda _seconds: None, quota=quota)
    return client, quota


def _internal_live_run(runner: HistoricalInstrumentAcquisitionRunner, dates: list[str]):
    return runner._execute_pairs(dates, execute_live=True, validated_full_scope=True)


def test_historical_calendar_artifact_is_exact_and_separate_from_3840_calendar():
    calendar = load_historical_trading_calendar(HISTORICAL_CALENDAR_PATH)
    assert calendar["trading_date_count"] == EXPECTED_TRADING_DATES
    assert calendar["trading_dates"][0] == "2010-01-04"
    assert calendar["trading_dates"][-1] == "2026-08-21"
    assert calendar["trading_dates_sha256"] == HISTORICAL_CALENDAR_DATE_SHA256
    assert calendar["generated_from_network"] is False


def test_historical_calendar_gate_rejects_count_boundary_and_order_mutations():
    calendar = load_historical_trading_calendar(HISTORICAL_CALENDAR_PATH)
    dates = calendar["trading_dates"]
    for mutated in (dates[:-1], dates + ["2026-08-24"]):
        with pytest.raises(InstrumentAcquisitionContractError, match="calendar"):
            validate_historical_trading_dates(mutated)
    wrong_first = list(dates); wrong_first[0] = "2010-01-05"
    wrong_last = list(dates); wrong_last[-1] = "2026-08-20"
    duplicate = list(dates); duplicate[10] = duplicate[9]
    unsorted = list(dates); unsorted[10], unsorted[11] = unsorted[11], unsorted[10]
    for mutated in (wrong_first, wrong_last, duplicate, unsorted):
        with pytest.raises(InstrumentAcquisitionContractError):
            validate_historical_trading_dates(mutated)


def test_public_live_run_cannot_bypass_full_scope(tmp_path):
    client, quota = _client(tmp_path, lambda *_args, **_kwargs: _Response(_payload()))
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    with pytest.raises(ValueError, match="run_full_historical"):
        runner.run(["2026-08-21"], execute_live=True)


def test_target_pairs_are_deterministic_4095_dates_and_8190_pairs():
    dates = _validated_weekdays(EXPECTED_TRADING_DATES)
    pairs = build_target_pairs(dates)
    assert len(pairs) == EXPECTED_PRIMARY_PAIRS
    assert pairs[:2] == [
        {"basDd": "20100104", "market": "KOSPI", "endpoint": "stk_isu_base_info"},
        {"basDd": "20100104", "market": "KOSDAQ", "endpoint": "ksq_isu_base_info"},
    ]
    assert pairs[-2]["basDd"] == dates[-1].replace("-", "")


def test_target_pair_count_is_fail_closed():
    with pytest.raises(ValueError, match="4095"):
        build_target_pairs(["2026-08-21"])
    with pytest.raises(ValueError, match="sorted"):
        build_target_pairs(["2026-08-22", "2026-08-21"], expected_count=None)


def test_schema_and_identity_validation_preserve_string_identifiers():
    result = validate_basic_info_response(_payload("KOSPI", ticker="000001"), bas_dd="20100104", market="KOSPI", endpoint="stk_isu_base_info")
    assert result["records"][0]["ISU_SRT_CD"] == "000001"
    assert "BAS_DD" not in result["records"][0]
    with pytest.raises(InstrumentAcquisitionContractError) as exc:
        validate_basic_info_response(_payload("KOSPI"), bas_dd="20100104", market="KOSPI", endpoint="ksq_isu_base_info")
    assert exc.value.status == "IDENTITY_INVALID"


def test_kospi_blank_sector_value_is_valid_and_preserved():
    result = validate_basic_info_response(_payload("KOSPI", sector=""), bas_dd="20260820", market="KOSPI", endpoint="stk_isu_base_info")
    assert result["schema_validation"] == "PASS"
    assert result["classification_completeness"] == "PARTIAL"
    assert result["records"][0]["SECT_TP_NM"] == ""


@pytest.mark.parametrize("field", ["ISU_CD", "ISU_SRT_CD", "MKT_TP_NM", "LIST_DD", "SECUGRP_NM", "KIND_STKCERT_TP_NM"])
def test_core_nonblank_fields_remain_required(field):
    payload = _payload()
    payload["OutBlock_1"][0][field] = ""
    with pytest.raises(InstrumentAcquisitionContractError) as exc:
        validate_basic_info_response(payload, bas_dd="20260820", market="KOSPI", endpoint="stk_isu_base_info")
    assert exc.value.status == "SCHEMA_INVALID"


def test_schema_missing_field_and_empty_response_fail_closed():
    bad = _payload()
    del bad["OutBlock_1"][0]["SECUGRP_NM"]
    with pytest.raises(InstrumentAcquisitionContractError) as exc:
        validate_basic_info_response(bad, bas_dd="20100104", market="KOSPI", endpoint="stk_isu_base_info")
    assert exc.value.status == "SCHEMA_INVALID"
    with pytest.raises(InstrumentAcquisitionContractError) as exc:
        validate_basic_info_response({"OutBlock_1": []}, bas_dd="20100104", market="KOSPI", endpoint="stk_isu_base_info")
    assert exc.value.status == "NO_DATA_UNEXPECTED"


def test_reconciliation_applies_positive_delta_and_is_idempotent(tmp_path):
    evidence = tmp_path / "diagnostic_request_ledger.json"
    evidence.write_text('{"request_count": 6}', encoding="utf-8")
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=10000, global_safety_limit=10000)
    # Seed the requested usage date explicitly so the test is independent of wall clock date.
    with sqlite3.connect(quota.db_path) as connection:
        connection.execute("INSERT INTO quota_usage VALUES (?, ?, ?, ?)", ("2026-08-26", "unrelated", 4, "2026-08-26T00:00:00+00:00"))
        connection.commit()
    digest = file_sha256(evidence)
    first = reconcile_known_attempts(
        quota,
        reconciliation_id="KRX_HISTORICAL_AUTHORITY_DISCOVERY_20260826_BASIC_INFO_6",
        usage_date_kst="2026-08-26",
        corrections={"stk_isu_base_info": 3, "ksq_isu_base_info": 3},
        evidence_path=evidence,
        evidence_sha256=digest,
        applied_at_utc="2026-08-26T13:00:00+00:00",
    )
    second = reconcile_known_attempts(
        quota,
        reconciliation_id="KRX_HISTORICAL_AUTHORITY_DISCOVERY_20260826_BASIC_INFO_6",
        usage_date_kst="2026-08-26",
        corrections={"stk_isu_base_info": 3, "ksq_isu_base_info": 3},
        evidence_path=evidence,
        evidence_sha256=digest,
    )
    assert first["status"] == "APPLIED"
    assert second["status"] == "ALREADY_RECONCILED"
    usage = quota.get_usage("2026-08-26")
    assert usage["endpoint_usage"]["stk_isu_base_info"] == 3
    assert usage["endpoint_usage"]["ksq_isu_base_info"] == 3
    assert usage["endpoint_usage"]["unrelated"] == 4
    assert usage["global_total"] == 10


def test_reconciliation_rejects_bad_evidence_hash(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3")
    with pytest.raises(ValueError, match="SHA"):
        reconcile_known_attempts(
            quota,
            reconciliation_id="r1",
            usage_date_kst="2026-08-26",
            corrections={"stk_isu_base_info": 1},
            evidence_path=evidence,
            evidence_sha256="0" * 64,
        )


def test_specialized_reconciliation_semantic_gate_accepts_real_evidence_and_idempotency(tmp_path):
    # The discovery ledger is the canonical semantic evidence for the actual +3/+3 correction.
    evidence = Path("artifacts/data/end_to_end_data_parity/v01/historical_instrument_authority_acquisition/v01/diagnostic_request_ledger.json")
    result = validate_historical_authority_discovery_evidence(evidence, usage_date_kst="2026-08-26", corrections={"stk_isu_base_info": 3, "ksq_isu_base_info": 3})
    assert result["status"] == "PASS"
    quota = LocalKrxOpenApiQuota(tmp_path / "semantic.sqlite3", endpoint_limit=10000, global_safety_limit=10000)
    applied = reconcile_historical_authority_discovery(quota, reconciliation_id="semantic-test", usage_date_kst="2026-08-26", corrections={"stk_isu_base_info": 3, "ksq_isu_base_info": 3}, evidence_path=evidence)
    repeated = reconcile_historical_authority_discovery(quota, reconciliation_id="semantic-test", usage_date_kst="2026-08-26", corrections={"stk_isu_base_info": 3, "ksq_isu_base_info": 3}, evidence_path=evidence)
    assert applied["status"] == "APPLIED"
    assert repeated["status"] == "ALREADY_RECONCILED"
    assert quota.get_global_usage("2026-08-26") == 6


@pytest.mark.parametrize(
    ("usage_date", "delta"),
    [("2026-08-25", {"stk_isu_base_info": 3, "ksq_isu_base_info": 3}),
     ("2026-08-26", {"stk_isu_base_info": 4, "ksq_isu_base_info": 2}),
     ("2026-08-26", {"stk_bydd_trd": 6})],
)
def test_specialized_reconciliation_rejects_wrong_date_delta_or_endpoint(usage_date, delta):
    evidence = Path("artifacts/data/end_to_end_data_parity/v01/historical_instrument_authority_acquisition/v01/diagnostic_request_ledger.json")
    with pytest.raises(ValueError):
        validate_historical_authority_discovery_evidence(evidence, usage_date_kst=usage_date, corrections=delta)


def test_quota_reserve_500_enforces_9500_and_10000_boundaries(tmp_path):
    # Deterministic: the fixture's seeded usage_date_kst and the `now` passed
    # to reserve_attempt must be the same KST day regardless of when this
    # test actually runs — using now=None here would silently fall back to
    # the real current date and stop exercising the boundary the day the
    # calendar rolls over past the hardcoded fixture date.
    fixture_now = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=10000, global_safety_limit=10000, reserve=500)
    with sqlite3.connect(quota.db_path) as connection:
        connection.execute("INSERT INTO quota_usage VALUES (?, ?, ?, ?)", ("2026-08-26", "stk_isu_base_info", 9499, "2026-08-26T00:00:00+00:00"))
        connection.commit()
    quota.reserve_attempt("stk_isu_base_info", now=fixture_now)
    with pytest.raises(KrxOpenApiQuotaExceeded):
        quota.reserve_attempt("stk_isu_base_info", now=fixture_now)
    assert quota.remaining("stk_isu_base_info", "2026-08-26")["endpoint"] == 0


def test_dry_run_makes_zero_network_calls_and_does_not_require_client(tmp_path):
    calls = []
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", reserve=500)
    runner = HistoricalInstrumentAcquisitionRunner(None, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    summary = runner.run(["2026-08-21"], execute_live=False)
    assert summary["status"] == "DRY_RUN"
    assert summary["network_attempts"] == 0
    assert calls == []
    assert not (tmp_path / "manifest.json").exists()


def test_live_reserve_must_be_500_and_direct_bypass_is_rejected(tmp_path):
    calls = []
    def opener(*_args, **_kwargs):
        calls.append(True)
        return _Response(_payload())
    client, quota = _client(tmp_path, opener, reserve=0)
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    with pytest.raises(ValueError, match="reserve=500"):
        runner._execute_pairs(["2026-08-21"], execute_live=True, validated_full_scope=True)
    assert calls == []
    bypass = KrxOpenApiClient("test-key", opener=opener, quota=None)
    with pytest.raises(ValueError, match="canonical quota"):
        HistoricalInstrumentAcquisitionRunner(bypass, LocalKrxOpenApiQuota(tmp_path / "bypass.sqlite3", reserve=500))._execute_pairs(["2026-08-21"], execute_live=True, validated_full_scope=True)


def test_live_success_writes_atomic_raw_and_checkpoint(tmp_path):
    calls = []
    def opener(request, **_kwargs):
        calls.append(request.full_url)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))
    client, quota = _client(tmp_path, opener)
    raw_root = tmp_path / "data/reference/source/history/krx_instrument_master/v01/basic_info"
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=raw_root, checkpoint_path=tmp_path / "manifest.json")
    summary = _internal_live_run(runner, ["2026-08-21"])
    assert summary["status"] == "COMPLETE"
    assert summary["network_attempts"] == 2
    assert len(calls) == 2
    assert quota.get_global_usage() == len(calls)
    raw = raw_root / "2026" / "20260821" / "KOSPI.json"
    assert raw.exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["entries"]["20260821|KOSPI|stk_isu_base_info"]
    assert entry["status"] == "COMPLETE"
    assert entry["raw_content_sha256"] == file_sha256(raw)
    assert "BAS_DD" not in json.loads(raw.read_text(encoding="utf-8"))["OutBlock_1"][0]


def test_retry_attempts_consume_quota_and_are_counted(tmp_path):
    calls = []
    def opener(request, **_kwargs):
        calls.append(request.full_url)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        if len(calls) == 1:
            return _Response({}, status=503)
        return _Response(_payload(market))
    client, quota = _client(tmp_path, opener)
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    summary = _internal_live_run(runner, ["2026-08-21"])
    assert summary["status"] == "COMPLETE"
    assert summary["network_attempts"] == 3
    assert summary["retry_attempts"] == 1
    assert quota.get_global_usage() == 3


def test_retry_then_quota_pause_preserves_first_attempt_and_retry_schedule(tmp_path):
    calls = []
    def opener(*_args, **_kwargs):
        calls.append(True)
        return _Response({}, status=503)
    client, quota = _client(tmp_path, opener, endpoint_limit=501, global_limit=501)
    summary = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json"), ["2026-08-21"])
    assert summary["status"] == "PAUSED_QUOTA"
    assert calls == [True]
    assert summary["network_attempts"] == 1
    assert summary["retry_attempts"] == 1
    entry = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["entries"]["20260821|KOSPI|stk_isu_base_info"]
    assert entry["status"] == "PAUSED_QUOTA"
    assert entry["attempt_count_total"] == 1
    assert entry["pair_attempt_count_current_quota_day"] == 1
    assert entry["retry_count"] == 1


@pytest.mark.parametrize(
    ("status", "expected_status"),
    [(401, "FAILED_PERMANENT"), (403, "FAILED_PERMANENT"), (429, "PAUSED_QUOTA")],
)
def test_client_auth_and_rate_limit_exceptions_persist_checkpoint_and_stop(status, expected_status, tmp_path):
    calls = []
    def opener(*_args, **_kwargs):
        calls.append(True)
        return _Response({}, status=status)
    client, quota = _client(tmp_path, opener)
    summary = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json"), ["2026-08-21"])
    assert calls == [True]
    assert summary["network_attempts"] == 1
    assert summary["retry_attempts"] == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["entries"]["20260821|KOSPI|stk_isu_base_info"]
    assert entry["status"] == expected_status
    assert entry["attempt_count_total"] == 1
    assert len(manifest["entries"]) == 1


def test_request_budget_error_persists_checkpoint_and_stops_before_next_opener(tmp_path):
    calls = []
    def opener(request, **_kwargs):
        calls.append(request.full_url)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))
    client, quota = _client(tmp_path, opener, max_requests=1)
    summary = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json"), ["2026-08-21"])
    assert summary["status"] == "PARTIAL"
    assert len(calls) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"]["20260821|KOSDAQ|ksq_isu_base_info"]["status"] == "FAILED_PERMANENT"
    assert manifest["entries"]["20260821|KOSDAQ|ksq_isu_base_info"]["attempt_count_total"] == 0


def test_schema_and_identity_failures_are_terminal_checkpoint_states(tmp_path):
    def opener(request, **_kwargs):
        if "ksq_isu_base_info" in request.full_url:
            return _Response(_payload("KOSPI"))
        bad = _payload(); del bad["OutBlock_1"][0]["SECT_TP_NM"]
        return _Response(bad)
    client, quota = _client(tmp_path, opener)
    summary = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json"), ["2026-08-21"])
    assert summary["status"] == "PARTIAL"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    schema_entry = manifest["entries"]["20260821|KOSPI|stk_isu_base_info"]
    assert schema_entry["status"] == "SCHEMA_INVALID"
    assert schema_entry["schema_validation"] == "FAIL"
    identity_entry = manifest["entries"]["20260821|KOSDAQ|ksq_isu_base_info"]
    assert identity_entry["status"] == "IDENTITY_INVALID"
    assert identity_entry["identity_validation"] == "FAIL"


def test_quota_pause_happens_before_opener_and_preserves_pending(tmp_path):
    calls = []
    def opener(*_args, **_kwargs):
        calls.append(True)
        return _Response(_payload())
    client, quota = _client(tmp_path, opener, endpoint_limit=501, global_limit=501)
    quota.reserve_attempt("stk_isu_base_info")
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    summary = _internal_live_run(runner, ["2026-08-21"])
    assert summary["status"] == "PAUSED_QUOTA"
    assert summary["quota_pause"] is True
    assert summary["network_attempts"] == 0
    assert calls == []
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert next(iter(manifest["entries"].values()))["status"] == "PAUSED_QUOTA"


def test_resume_skips_verified_complete_and_repairs_broken_complete(tmp_path):
    calls = []
    def opener(request, **_kwargs):
        calls.append(request.full_url)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))
    client, quota = _client(tmp_path, opener)
    runner = HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json")
    _internal_live_run(runner, ["2026-08-21"])
    first_call_count = len(calls)
    summary = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=tmp_path / "manifest.json"), ["2026-08-21"])
    assert summary["network_attempts"] == 0
    assert len(calls) == first_call_count
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"]["20260821|KOSPI|stk_isu_base_info"]["raw_content_sha256"] = "broken"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    raw = tmp_path / "raw/2026/20260821/KOSPI.json"
    raw.write_text("{}", encoding="utf-8")
    repaired = _internal_live_run(HistoricalInstrumentAcquisitionRunner(client, quota, raw_root=tmp_path / "raw", checkpoint_path=manifest_path), ["2026-08-21"])
    assert repaired["network_attempts"] == 1


def test_cross_day_quota_resets_by_kst_date(tmp_path):
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=2, global_safety_limit=2, reserve=0)
    quota.reserve_attempt("stk_isu_base_info", now=datetime(2026, 8, 26, 14, 59, tzinfo=timezone.utc))
    quota.reserve_attempt("stk_isu_base_info", now=datetime(2026, 8, 26, 15, 1, tzinfo=timezone.utc))
    assert quota.get_endpoint_usage("stk_isu_base_info", "2026-08-27") == 1
    assert quota.get_endpoint_usage("stk_isu_base_info", "2026-08-26") == 1
