from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.update_sector_index_v01 import build_parser
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_sector_index import KRX_NATIVE_SECTOR_INDEX_MAP, STANDARD_INDEX_COLUMNS
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded
from trend_scanner.data.rolling_market_data_refresh import (
    ROLLING_AUTHORITY_VERSION,
    RollingAuthorityManifest,
    write_rolling_authority,
)
from trend_scanner.data.sector_index_rolling import (
    BLOCKED,
    FAILED,
    NOOP_ALREADY_COMPLETE,
    PASS,
    SECTOR_INDEX_CACHE_PATH,
    SECTOR_INDEX_META_PATH,
    update_sector_index_rolling,
)


class FakeCalendar:
    def __init__(self, dates: list[str]):
        self.trading_dates = pd.DatetimeIndex(dates)


class FakeUpdater:
    def __init__(self, *, materialize: set[str] | None = None, errors: dict[str, Exception] | None = None):
        self.materialize = materialize
        self.errors = errors or {}
        self.calls: list[str] = []

    def update_sector_index_cache(self, *, target_date: str, output_parquet: Path, output_meta: Path):
        self.calls.append(target_date)
        if target_date in self.errors:
            raise self.errors[target_date]
        if self.materialize is not None and target_date not in self.materialize:
            return pd.read_parquet(output_parquet)
        current = pd.read_parquet(output_parquet)
        increment = _sector_frame([target_date])
        merged = pd.concat([current, increment], ignore_index=True)
        merged.to_parquet(output_parquet, index=False)
        output_meta.write_text(
            json.dumps({"requested_as_of": target_date, "row_count": len(merged)}) + "\n",
            encoding="utf-8",
        )
        return merged


def _sector_frame(dates: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in dates:
        for code, contract in KRX_NATIVE_SECTOR_INDEX_MAP.items():
            rows.append(
                {
                    "date": day,
                    "index_code": code,
                    "index_name": contract["idx_name"],
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000,
                    "trading_value": 2000.0,
                }
            )
    return pd.DataFrame(rows, columns=list(STANDARD_INDEX_COLUMNS))


def _prepare(tmp_path: Path, dates: list[str], *, certified_through: str = "2026-09-17") -> None:
    authority_dir = tmp_path / "data/market/rolling_authority"
    manifest = RollingAuthorityManifest(
        authority_version=ROLLING_AUTHORITY_VERSION,
        certified_through=certified_through,
        leg_boundaries={
            "common_raw": certified_through,
            "common_adjusted": certified_through,
            "etf_raw": certified_through,
            "etf_adjusted": certified_through,
        },
        previous_boundary=None,
        raw_store_version="TEST_RAW",
        adjusted_store_version="TEST_ADJUSTED",
        instrument_contract_version="TEST_INSTRUMENT",
        bootstrap_source={"test": True},
        generated_at="2026-09-18T00:00:00+00:00",
    )
    write_rolling_authority(manifest, authority_dir)
    cache_path = tmp_path / SECTOR_INDEX_CACHE_PATH
    meta_path = tmp_path / SECTOR_INDEX_META_PATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frame = _sector_frame(dates)
    frame.to_parquet(cache_path, index=False)
    meta_path.write_text(
        json.dumps(
            {
                "requested_as_of": max(dates),
                "date_min": min(dates),
                "date_max": max(dates),
                "index_count": 46,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_explicit_as_of_is_required() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([])
    assert exc_info.value.code == 2


def test_phase1_boundary_blocks_before_cache_or_update(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-17"])
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-18",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-17"]),
    )
    assert result.status == BLOCKED
    assert result.reason == "TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY"
    assert result.update_call_count == 0
    assert updater.calls == []


def test_phase1_calendar_excludes_weekend(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-04"])
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-07",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-04", "2026-09-07"]),
    )
    assert result.status == PASS
    assert updater.calls == ["2026-09-07"]
    assert "2026-09-05" not in result.required_trading_dates
    assert "2026-09-06" not in result.required_trading_dates


def test_only_missing_dates_are_updated_in_ascending_order(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01", "2026-09-03"])
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-04",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    )
    assert result.status == PASS
    assert result.missing_trading_dates == ["2026-09-02", "2026-09-04"]
    assert result.updated_trading_dates == updater.calls == ["2026-09-02", "2026-09-04"]


def test_internal_gap_is_detected_before_tail_update(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01", "2026-09-03", "2026-09-04"])
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-04",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    )
    assert result.status == PASS
    assert updater.calls == ["2026-09-02"]


def test_same_target_complete_is_zero_call_and_zero_write_noop(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01", "2026-09-02"])
    cache_path = tmp_path / SECTOR_INDEX_CACHE_PATH
    meta_path = tmp_path / SECTOR_INDEX_META_PATH
    before_cache = cache_path.read_bytes()
    before_meta = meta_path.read_bytes()
    before_cache_mtime = cache_path.stat().st_mtime_ns
    before_meta_mtime = meta_path.stat().st_mtime_ns
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == NOOP_ALREADY_COMPLETE
    assert result.update_call_count == 0
    assert updater.calls == []
    assert cache_path.read_bytes() == before_cache
    assert meta_path.read_bytes() == before_meta
    assert cache_path.stat().st_mtime_ns == before_cache_mtime
    assert meta_path.stat().st_mtime_ns == before_meta_mtime


def test_confirmed_trading_date_empty_response_is_not_silent_noop(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater(materialize=set())
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == BLOCKED
    assert result.reason == "REQUIRED_TRADING_DATE_NOT_MATERIALIZED"
    assert result.update_call_count == 1


def test_market_data_error_is_blocked(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater(errors={"2026-09-02": MarketDataError("source failure")})
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == BLOCKED
    assert result.reason == "REQUIRED_TRADING_DATE_UPDATE_BLOCKED:2026-09-02"
    assert result.update_call_count == 1


def test_unexpected_exception_is_failed(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater(errors={"2026-09-02": RuntimeError("unexpected")})
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == FAILED
    assert result.reason == "REQUIRED_TRADING_DATE_UPDATE_FAILED:2026-09-02"


@pytest.mark.parametrize(
    "error",
    [
        KrxOpenApiAuthorizationError("unauthorized"),
        KrxOpenApiRateLimitError("rate limited"),
        KrxOpenApiBudgetError("budget exhausted"),
        KrxOpenApiQuotaExceeded(
            "quota exhausted",
            endpoint_key="kospi_dd_trd",
            usage_date_kst="2026-09-19",
            endpoint_before=10,
            global_before=20,
        ),
    ],
    ids=["authorization", "rate_limit", "budget", "quota"],
)
def test_known_krx_operational_blockers_are_blocked(tmp_path: Path, error: Exception) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater(errors={"2026-09-02": error})
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == BLOCKED
    assert result.update_call_count == 1


@pytest.mark.parametrize(
    "message",
    [
        "KRX Open API auth key is required",
        "KRX_OPEN_API_AUTH_KEY is required for sector cache build",
    ],
    ids=["client_auth_key", "sector_builder_auth_key"],
)
def test_missing_auth_key_is_blocked_without_broad_value_error_catch(tmp_path: Path, message: str) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater(errors={"2026-09-02": ValueError(message)})
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == BLOCKED
    assert result.update_call_count == 1


def test_final_completeness_has_46_codes_per_required_date(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-03",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02", "2026-09-03"]),
    )
    assert result.status == PASS
    assert result.trading_date_count == 3
    assert result.sector_code_count == 46
    final = pd.read_parquet(tmp_path / SECTOR_INDEX_CACHE_PATH)
    assert not final.duplicated(["date", "index_code"]).any()
    assert final.groupby("date")["index_code"].nunique().eq(46).all()


def test_invalid_existing_cache_blocks_without_rebuild_or_update(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01"])
    cache_path = tmp_path / SECTOR_INDEX_CACHE_PATH
    frame = pd.read_parquet(cache_path)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    frame.to_parquet(cache_path, index=False)
    updater = FakeUpdater()
    result = update_sector_index_rolling(
        "2026-09-02",
        repo_root=tmp_path,
        provider=updater,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02"]),
    )
    assert result.status == BLOCKED
    assert result.update_call_count == 0
    assert updater.calls == []


def test_missing_date_order_is_deterministic(tmp_path: Path) -> None:
    _prepare(tmp_path, ["2026-09-01", "2026-09-04"])
    updater = FakeUpdater()
    calendar = FakeCalendar(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"])
    first = update_sector_index_rolling("2026-09-04", repo_root=tmp_path, provider=updater, calendar=calendar)
    assert first.missing_trading_dates == ["2026-09-02", "2026-09-03"]
    assert first.updated_trading_dates == ["2026-09-02", "2026-09-03"]
