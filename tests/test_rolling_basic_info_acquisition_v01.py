"""ROLLING_BASIC_INFO_ACQUISITION_V01 focused tests: authorized-date derivation, shared
fetch/validation reuse, historical-contract isolation, idempotency, and frontier accounting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_scanner.data.krx_historical_instrument_acquisition import (
    EXPECTED_TRADING_DATES,
    HISTORICAL_CALENDAR_DATE_SHA256,
    HISTORICAL_CALENDAR_PATH,
    HistoricalInstrumentAcquisitionRunner,
    load_historical_trading_calendar,
    validate_historical_trading_dates,
)
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import RAW_COLUMNS, KrxRawStockStore
from trend_scanner.data.rolling_basic_info_acquisition import (
    RollingBasicInfoAcquisitionRunner,
    current_basic_info_frontier,
    derive_authorized_dates,
)


# ---------------------------------------------------------------------------
# Fixtures shared with the historical acquisition test suite's proven pattern
# ---------------------------------------------------------------------------


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


def _client(tmp_path: Path, opener, *, reserve: int = 500, max_requests: int = 80):
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", reserve=reserve)
    client = KrxOpenApiClient("test-key", opener=opener, max_requests=max_requests, max_transient_retries=1, sleeper=lambda _s: None, quota=quota)
    return client, quota


def _raw_row(date: str, ticker: str = "005930") -> "object":
    import pandas as pd

    return pd.DataFrame(
        [{
            "date": date, "ticker": ticker,
            "open": 100, "high": 105, "low": 95, "close": 101,
            "volume": 1000, "trading_value": 100000, "market_cap": 1_000_000, "listed_shares": 10_000,
        }],
        columns=list(RAW_COLUMNS),
    )


def _raw_store_with_sessions(tmp_path: Path, *, complete_dates: list[str], no_data_dates: list[str] | None = None) -> KrxRawStockStore:
    store = KrxRawStockStore(tmp_path / "raw")
    for day in complete_dates:
        for market in ("KOSPI", "KOSDAQ"):
            store.save_snapshot(market, day, _raw_row(day), f"/{market}")
    for day in no_data_dates or ():
        for market in ("KOSPI", "KOSDAQ"):
            store.save_snapshot(market, day, _raw_row(day).iloc[0:0], f"/{market}")
    return store


# ---------------------------------------------------------------------------
# Authorized-date derivation (directive sections 4/7)
# ---------------------------------------------------------------------------


def test_rolling_runner_derives_dates_from_raw_complete_manifest(tmp_path) -> None:
    store = _raw_store_with_sessions(tmp_path, complete_dates=["2026-08-24", "2026-08-25", "2026-08-26"])
    dates = derive_authorized_dates(store, current_frontier="2026-08-21", target_as_of="2026-08-26")
    assert dates == ["2026-08-24", "2026-08-25", "2026-08-26"]


def test_no_data_dates_excluded(tmp_path) -> None:
    store = _raw_store_with_sessions(tmp_path, complete_dates=["2026-08-24", "2026-08-26"], no_data_dates=["2026-08-25"])
    dates = derive_authorized_dates(store, current_frontier="2026-08-21", target_as_of="2026-08-26")
    assert dates == ["2026-08-24", "2026-08-26"]
    assert "2026-08-25" not in dates


def test_dates_at_or_before_frontier_excluded(tmp_path) -> None:
    store = _raw_store_with_sessions(tmp_path, complete_dates=["2026-08-20", "2026-08-21", "2026-08-24"])
    dates = derive_authorized_dates(store, current_frontier="2026-08-21", target_as_of="2026-08-24")
    assert dates == ["2026-08-24"]  # 8/20 and 8/21 (== frontier) excluded


def test_dates_after_target_excluded(tmp_path) -> None:
    store = _raw_store_with_sessions(tmp_path, complete_dates=["2026-08-24", "2026-08-25", "2026-08-26"])
    dates = derive_authorized_dates(store, current_frontier="2026-08-21", target_as_of="2026-08-25")
    assert dates == ["2026-08-24", "2026-08-25"]
    assert "2026-08-26" not in dates


def test_manual_trading_date_injection_not_used() -> None:
    """derive_authorized_dates has no parameter accepting a caller-supplied date list -- the only
    inputs are the raw store, frontier, and target_as_of (directive section 7)."""
    import inspect

    params = set(inspect.signature(derive_authorized_dates).parameters)
    assert params == {"raw_store", "current_frontier", "target_as_of"}


# ---------------------------------------------------------------------------
# Historical frozen contract isolation (directive sections 5/31)
# ---------------------------------------------------------------------------


def test_historical_frozen_runner_unchanged() -> None:
    calendar = load_historical_trading_calendar(HISTORICAL_CALENDAR_PATH)
    assert calendar["trading_date_count"] == EXPECTED_TRADING_DATES
    assert calendar["trading_dates"][0] == "2010-01-04"
    assert calendar["trading_dates"][-1] == "2026-08-21"
    assert calendar["trading_dates_sha256"] == HISTORICAL_CALENDAR_DATE_SHA256


def test_historical_date_sha_contract_unchanged() -> None:
    calendar = load_historical_trading_calendar(HISTORICAL_CALENDAR_PATH)
    validated = validate_historical_trading_dates(calendar["trading_dates"])
    assert validated["trading_dates_sha256"] == HISTORICAL_CALENDAR_DATE_SHA256


def test_rolling_runner_never_writes_into_historical_raw_root_or_checkpoint(tmp_path) -> None:
    """The rolling runner's default raw_root/checkpoint_path are structurally distinct paths from
    the historical runner's -- confirmed by construction, not just convention."""
    from trend_scanner.data.rolling_basic_info_acquisition import (
        DEFAULT_ROLLING_CHECKPOINT_PATH,
        DEFAULT_ROLLING_RAW_ROOT,
    )

    historical_runner = HistoricalInstrumentAcquisitionRunner(None, LocalKrxOpenApiQuota(tmp_path / "q.sqlite3", reserve=500))
    assert str(DEFAULT_ROLLING_RAW_ROOT) != str(historical_runner.raw_root)
    assert str(DEFAULT_ROLLING_CHECKPOINT_PATH) != str(historical_runner.checkpoint_path)
    assert not str(DEFAULT_ROLLING_RAW_ROOT).startswith(str(historical_runner.raw_root))


# ---------------------------------------------------------------------------
# Shared fetch/validation reuse + persistence (directive sections 10/29)
# ---------------------------------------------------------------------------


def test_rolling_incremental_snapshot_saves_correctly(tmp_path) -> None:
    calls = []

    def opener(request, **_kwargs):
        calls.append(request.full_url)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))

    client, quota = _client(tmp_path, opener)
    runner = RollingBasicInfoAcquisitionRunner(client, quota, raw_root=tmp_path / "rolling_basic_info", checkpoint_path=tmp_path / "rolling_checkpoint.json")
    result = runner.run(["2026-08-24"], execute_live=True)

    assert result["status"] == "COMPLETE"
    assert result["completed_count"] == 2  # KOSPI + KOSDAQ
    assert result["new_snapshot_count"] == 2
    assert len(calls) == 2
    raw = tmp_path / "rolling_basic_info" / "2026" / "20260824" / "KOSPI.json"
    assert raw.exists()


def test_existing_rolling_snapshots_not_overwritten_on_resume(tmp_path) -> None:
    call_count = [0]

    def opener(request, **_kwargs):
        call_count[0] += 1
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))

    client, quota = _client(tmp_path, opener)
    runner = RollingBasicInfoAcquisitionRunner(client, quota, raw_root=tmp_path / "rb", checkpoint_path=tmp_path / "rc.json")
    first = runner.run(["2026-08-24"], resume=True, execute_live=True)
    assert first["completed_count"] == 2
    calls_after_first = call_count[0]

    second = runner.run(["2026-08-24"], resume=True, execute_live=True)
    assert second["completed_count"] == 2
    assert second["new_snapshot_count"] == 0
    assert call_count[0] == calls_after_first  # no new network calls -- resume skipped verified-complete entries


def test_second_identical_run_is_idempotent(tmp_path) -> None:
    def opener(request, **_kwargs):
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))

    client, quota = _client(tmp_path, opener)
    runner = RollingBasicInfoAcquisitionRunner(client, quota, raw_root=tmp_path / "rb", checkpoint_path=tmp_path / "rc.json")
    dates = ["2026-08-24", "2026-08-25"]
    runner.run(dates, execute_live=True)
    second = runner.run(dates, execute_live=True)
    assert second["new_snapshot_count"] == 0
    assert second["network_attempts"] == 0


# ---------------------------------------------------------------------------
# Frontier accounting / partial acquisition (directive sections 19/20/21)
# ---------------------------------------------------------------------------


def test_partial_acquisition_does_not_declare_target_frontier(tmp_path) -> None:
    def opener(request, **_kwargs):
        if "20260825" in request.full_url:
            return _Response({}, status=500)
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))

    client, quota = _client(tmp_path, opener)
    runner = RollingBasicInfoAcquisitionRunner(client, quota, raw_root=tmp_path / "rb", checkpoint_path=tmp_path / "rc.json")
    result = runner.run(["2026-08-24", "2026-08-25"], execute_live=True)
    assert result["status"] == "PARTIAL"
    summary = runner.write_final_summary(["2026-08-24", "2026-08-25"], final_summary_path=tmp_path / "final.json")
    assert summary["status"] != "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
    assert summary["runner_status"] != "COMPLETE"


def test_successful_acquisition_declares_expected_frontier(tmp_path) -> None:
    def opener(request, **_kwargs):
        market = "KOSDAQ" if "ksq_isu_base_info" in request.full_url else "KOSPI"
        return _Response(_payload(market))

    client, quota = _client(tmp_path, opener)
    runner = RollingBasicInfoAcquisitionRunner(client, quota, raw_root=tmp_path / "rb", checkpoint_path=tmp_path / "rc.json")
    dates = ["2026-08-24", "2026-08-25"]
    result = runner.run(dates, execute_live=True)
    assert result["status"] == "COMPLETE"
    summary = runner.write_final_summary(dates, final_summary_path=tmp_path / "final.json")
    assert summary["status"] == "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
    assert summary["runner_status"] == "COMPLETE"
    assert summary["target_count"] == 4
    assert summary["completed_count"] == 4
    assert summary["pending_count"] == 0


def test_dry_run_never_writes(tmp_path) -> None:
    quota = LocalKrxOpenApiQuota(tmp_path / "q.sqlite3", reserve=500)
    runner = RollingBasicInfoAcquisitionRunner(None, quota, raw_root=tmp_path / "rb", checkpoint_path=tmp_path / "rc.json")
    result = runner.run(["2026-08-24"], execute_live=False)
    assert result["status"] == "DRY_RUN"
    assert not (tmp_path / "rc.json").exists()
    assert not (tmp_path / "rb").exists()


# ---------------------------------------------------------------------------
# Authority source / PyKRX guard (directive sections 9/32)
# ---------------------------------------------------------------------------


def test_pykrx_zero_use_guard() -> None:
    for path in (
        Path("src/trend_scanner/data/rolling_basic_info_acquisition.py"),
        Path("scripts/refresh_krx_basic_info_v01.py"),
    ):
        source = path.read_text(encoding="utf-8").lower()
        assert "pykrx" not in source, f"{path} must not reference pykrx"


def test_rolling_runner_only_imports_approved_basic_info_source() -> None:
    source = Path("src/trend_scanner/data/rolling_basic_info_acquisition.py").read_text(encoding="utf-8")
    for forbidden in ("naver", "requests_html", "BeautifulSoup", "selenium"):
        assert forbidden.lower() not in source.lower()
