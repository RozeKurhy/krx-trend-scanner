from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts.update_sector_membership_v01 import build_parser
from trend_scanner.data.krx_sector_index import (
    KOSDAQ_SECTOR_CODES,
    KOSPI_SECTOR_CODES,
    KRX_NATIVE_SECTOR_INDEX_MAP,
)
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    ROLLING_AUTHORITY_VERSION,
    RollingAuthorityManifest,
    write_rolling_authority,
)
from trend_scanner.data.sector_membership import (
    STORE_COLUMNS,
    load_sector_membership_meta,
    load_sector_membership_snapshot,
    sector_membership_meta_path_for_date,
    sector_membership_path_for_date,
)
from trend_scanner.data.sector_membership_exact_update import (
    BLOCKED,
    FAILED,
    NOOP_ALREADY_COMPLETE,
    PASS,
    REASON_BOUNDARY_EXCEEDED,
    REASON_EXISTING_INVALID,
    REASON_NOOP_COMPLETE,
    update_sector_membership_exact,
)
from trend_scanner.data.sector_membership_rolling import (
    MARKETPLACE_ROOT,
    RollingMembershipRun,
    load_local_target_universe,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_target(
    path: Path,
    rows: list[dict[str, str]],
    *,
    effective_from: str = "2026-01-01",
    effective_to: str = "2026-12-31",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "intervals": [
            {
                "ticker": row["ticker"],
                "market": row["market"],
                "state": "COMMON",
                "effective_from": effective_from,
                "effective_to": effective_to,
            }
            for row in rows
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _setup_authority(
    root: Path,
    *,
    certified_through: str = "2026-09-17",
    target_rows: list[dict[str, str]] | None = None,
) -> None:
    auth_dir = root / DEFAULT_ROLLING_AUTHORITY_DIR
    auth_dir.mkdir(parents=True, exist_ok=True)
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
    write_rolling_authority(manifest, auth_dir)

    rows = target_rows if target_rows is not None else [
        {"ticker": "000001", "market": "KOSPI"},
        {"ticker": "000002", "market": "KOSDAQ"},
    ]
    _write_target(auth_dir / "merged_pit_intervals.json", rows)


def _write_marketplace(
    root: Path,
    date_text: str,
    *,
    missing_code: str | None = None,
    rows_override: dict[str, list[dict[str, str]]] | None = None,
) -> Path:
    raw_root = root / MARKETPLACE_ROOT / date_text.replace("-", "")
    manifest: list[dict[str, object]] = []
    rows_override = rows_override or {}
    for index, (code, contract) in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.items(), start=1):
        if code == missing_code:
            continue
        path = raw_root / code / "original" / "source.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        default_ticker = str(index).zfill(6)
        rows = rows_override.get(code, [{"종목코드": default_ticker, "종목명": f"종목_{index}"}])
        with path.open("w", encoding="cp949", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["종목코드", "종목명"])
            writer.writeheader()
            writer.writerows(rows)
        manifest.append(
            {
                "sector_code": code,
                "sector_name": contract["idx_name"],
                "market": contract["market"],
                "effective_date": date_text,
                "file_path": str(path.relative_to(root)),
                "file_name": path.name,
                "encoding": "CP949",
                "row_count": len(rows),
                "ticker_column": "종목코드",
                "name_column": "종목명",
                "duplicate_ticker_count": 0,
                "blank_ticker_count": 0,
                "invalid_ticker_count": 0,
                "parse_status": "PASS",
            }
        )
    manifest_path = raw_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# T1 — explicit as-of
def test_t1_explicit_as_of_required() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


# T2 — Phase 1 boundary
def test_t2_phase1_boundary_exceeded(tmp_path: Path) -> None:
    _setup_authority(tmp_path, certified_through="2026-09-17")
    calls: list[str] = []

    def mock_builder(target: str, *, repo_root: Path) -> RollingMembershipRun:
        calls.append(target)
        raise RuntimeError("should not be called")

    result = update_sector_membership_exact(
        "2026-09-18",
        repo_root=tmp_path,
        builder=mock_builder,
    )
    assert result.status == BLOCKED
    assert result.reason == REASON_BOUNDARY_EXCEEDED
    assert result.builder_called is False
    assert result.published is False
    assert len(calls) == 0

    snapshot_path = sector_membership_path_for_date("2026-09-18", tmp_path)
    assert not snapshot_path.exists()


# T3 — exact-date existing snapshot NOOP
def test_t3_exact_date_existing_snapshot_noop() -> None:
    calls: list[str] = []

    def mock_builder(target: str, *, repo_root: Path) -> RollingMembershipRun:
        calls.append(target)
        raise RuntimeError("should not be called")

    # 2026-09-04 exists in production repo
    result = update_sector_membership_exact(
        "2026-09-04",
        repo_root=ROOT,
        builder=mock_builder,
    )
    assert result.status == NOOP_ALREADY_COMPLETE
    assert result.reason == REASON_NOOP_COMPLETE
    assert result.builder_called is False
    assert result.published is False
    assert result.target_population == 2562
    assert result.snapshot_population == 2562
    assert result.mapped == 2440
    assert result.aggregate_only == 88
    assert result.unmapped == 34
    assert len(calls) == 0


# T4 — reject fallback to previous date
def test_t4_reject_fallback_to_previous_date(tmp_path: Path) -> None:
    # Set up authority covering 2026-09-17
    _setup_authority(tmp_path, certified_through="2026-09-17")

    # Copy only 2026-09-04 existing snapshot
    prod_parquet = sector_membership_path_for_date("2026-09-04", ROOT)
    prod_meta = sector_membership_meta_path_for_date("2026-09-04", ROOT)
    dest_parquet = sector_membership_path_for_date("2026-09-04", tmp_path)
    dest_meta = sector_membership_meta_path_for_date("2026-09-04", tmp_path)
    dest_parquet.parent.mkdir(parents=True, exist_ok=True)
    dest_parquet.write_bytes(prod_parquet.read_bytes())
    dest_meta.write_bytes(prod_meta.read_bytes())

    # Request target 2026-09-17 with NO marketplace source for 2026-09-17
    result = update_sector_membership_exact("2026-09-17", repo_root=tmp_path)
    assert result.status == BLOCKED
    assert "MARKETPLACE_MANIFEST_MISSING" in result.reason
    assert result.published is False

    # 2026-09-17 snapshot must NOT exist
    assert not sector_membership_path_for_date("2026-09-17", tmp_path).exists()


# T5 — partial existing artifact
def test_t5_partial_existing_artifact_blocked(tmp_path: Path) -> None:
    _setup_authority(tmp_path, certified_through="2026-09-17")
    target = "2026-09-17"
    snap_path = sector_membership_path_for_date(target, tmp_path)
    meta_path = sector_membership_meta_path_for_date(target, tmp_path)
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    calls: list[str] = []

    def mock_builder(t: str, *, repo_root: Path) -> RollingMembershipRun:
        calls.append(t)
        raise RuntimeError("should not be called")

    # Case A: parquet only
    snap_path.write_bytes(b"dummy parquet")
    result_a = update_sector_membership_exact(target, repo_root=tmp_path, builder=mock_builder)
    assert result_a.status == BLOCKED
    assert result_a.reason == REASON_EXISTING_INVALID
    assert result_a.builder_called is False
    assert len(calls) == 0

    # Case B: meta only
    snap_path.unlink()
    meta_path.write_text("{}", encoding="utf-8")
    result_b = update_sector_membership_exact(target, repo_root=tmp_path, builder=mock_builder)
    assert result_b.status == BLOCKED
    assert result_b.reason == REASON_EXISTING_INVALID
    assert result_b.builder_called is False
    assert len(calls) == 0


# T6 — invalid existing snapshot
@pytest.mark.parametrize(
    "tamper_mode",
    [
        "duplicate_ticker",
        "wrong_effective_date",
        "invalid_resolution_status",
        "population_mismatch",
        "market_mismatch",
    ],
)
def test_t6_invalid_existing_snapshot_blocked(tmp_path: Path, tamper_mode: str) -> None:
    target = "2026-09-17"
    target_rows = [
        {"ticker": "000001", "market": "KOSPI"},
        {"ticker": "000002", "market": "KOSDAQ"},
    ]
    _setup_authority(tmp_path, certified_through="2026-09-17", target_rows=target_rows)

    snap_rows = [
        {
            "ticker": "000001",
            "market": "KOSPI",
            "effective_date": target,
            "sector_code": "1005",
            "sector_name": "음식료·담배",
            "resolution_status": "MAPPED",
            "policy_version": "V01",
            "source_authority": "TEST",
            "source_artifact_sha256": "sha",
        },
        {
            "ticker": "000002",
            "market": "KOSDAQ",
            "effective_date": target,
            "sector_code": "2026",
            "sector_name": "반도체",
            "resolution_status": "MAPPED",
            "policy_version": "V01",
            "source_authority": "TEST",
            "source_artifact_sha256": "sha",
        },
    ]

    if tamper_mode == "duplicate_ticker":
        snap_rows[1]["ticker"] = "000001"
    elif tamper_mode == "wrong_effective_date":
        snap_rows[0]["effective_date"] = "2026-09-16"
    elif tamper_mode == "invalid_resolution_status":
        snap_rows[0]["resolution_status"] = "INVALID_STATUS"
    elif tamper_mode == "population_mismatch":
        snap_rows = snap_rows[:1]
    elif tamper_mode == "market_mismatch":
        snap_rows[1]["market"] = "KOSPI"

    snap_path = sector_membership_path_for_date(target, tmp_path)
    meta_path = sector_membership_meta_path_for_date(target, tmp_path)
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(snap_rows, columns=list(STORE_COLUMNS)).to_parquet(snap_path, index=False)
    meta_path.write_text(
        json.dumps({
            "snapshot_effective_date": target,
            "sector_count": 46,
            "target_population": len(snap_rows),
        }),
        encoding="utf-8",
    )

    calls: list[str] = []

    def mock_builder(t: str, *, repo_root: Path) -> RollingMembershipRun:
        calls.append(t)
        raise RuntimeError("should not be called")

    mtime_before = snap_path.stat().st_mtime_ns
    result = update_sector_membership_exact(target, repo_root=tmp_path, builder=mock_builder)
    assert result.status == BLOCKED
    assert result.reason == REASON_EXISTING_INVALID
    assert result.builder_called is False
    assert len(calls) == 0
    # Artifact was not overwritten
    assert snap_path.stat().st_mtime_ns == mtime_before


# T7 — target source absent
def test_t7_target_source_absent(tmp_path: Path) -> None:
    _setup_authority(tmp_path, certified_through="2026-09-17")
    result = update_sector_membership_exact("2026-09-17", repo_root=tmp_path)
    assert result.status == BLOCKED
    assert "MARKETPLACE_MANIFEST_MISSING" in result.reason
    assert result.published is False
    assert not sector_membership_path_for_date("2026-09-17", tmp_path).exists()


# T8 — all 46 source success
def test_t8_all_46_source_success(tmp_path: Path) -> None:
    target = "2026-09-17"
    target_rows = [
        {"ticker": str(i).zfill(6), "market": "KOSPI" if str(code) in KOSPI_SECTOR_CODES else "KOSDAQ"}
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    ]
    _setup_authority(tmp_path, certified_through=target, target_rows=target_rows)

    # 46 sectors fixture, each containing its respective ticker
    rows_override = {
        code: [{"종목코드": str(i).zfill(6), "종목명": f"종목_{i}"}]
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    }
    _write_marketplace(tmp_path, target, rows_override=rows_override)

    result = update_sector_membership_exact(target, repo_root=tmp_path)
    assert result.status == PASS
    assert result.builder_called is True
    assert result.published is True
    assert result.reason == "ALL_GATES_PASS"
    assert result.target_population == 46
    assert result.snapshot_population == 46

    snap_path = sector_membership_path_for_date(target, tmp_path)
    meta_path = sector_membership_meta_path_for_date(target, tmp_path)
    assert snap_path.is_file()
    assert meta_path.is_file()


# T9 — 45/46 or manifest mismatch
def test_t9_missing_sector_blocks_publication(tmp_path: Path) -> None:
    target = "2026-09-17"
    target_rows = [{"ticker": "000001", "market": "KOSPI"}]
    _setup_authority(tmp_path, certified_through=target, target_rows=target_rows)

    # Missing sector 1005 (only 45 sectors)
    _write_marketplace(tmp_path, target, missing_code="1005")

    result = update_sector_membership_exact(target, repo_root=tmp_path)
    assert result.status == BLOCKED
    assert "SECTOR_CONTRACT_MISMATCH" in result.reason
    assert result.published is False
    assert not sector_membership_path_for_date(target, tmp_path).exists()


# T10 — final target population reconciliation
def test_t10_final_target_population_reconciliation(tmp_path: Path) -> None:
    target = "2026-09-17"
    target_rows = [
        {"ticker": str(i).zfill(6), "market": "KOSPI" if str(code) in KOSPI_SECTOR_CODES else "KOSDAQ"}
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    ]
    _setup_authority(tmp_path, certified_through=target, target_rows=target_rows)
    rows_override = {
        code: [{"종목코드": str(i).zfill(6), "종목명": f"종목_{i}"}]
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    }
    _write_marketplace(tmp_path, target, rows_override=rows_override)

    result = update_sector_membership_exact(target, repo_root=tmp_path)
    assert result.status == PASS

    snapshot = load_sector_membership_snapshot(target, repo_root=tmp_path)
    pit_universe = load_local_target_universe(target, repo_root=tmp_path)

    assert len(snapshot) == len(pit_universe)
    assert set(snapshot["ticker"]) == set(pit_universe["ticker"])
    snap_market = dict(zip(snapshot["ticker"], snapshot["market"]))
    pit_market = dict(zip(pit_universe["ticker"], pit_universe["market"]))
    assert snap_market == pit_market


# T11 — UNMAPPED preservation
def test_t11_unmapped_tickers_preserved(tmp_path: Path) -> None:
    target = "2026-09-17"
    # Target universe has an extra ticker 999999 that does not appear in any sector
    target_rows = [
        {"ticker": str(i).zfill(6), "market": "KOSPI" if str(code) in KOSPI_SECTOR_CODES else "KOSDAQ"}
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    ] + [{"ticker": "999999", "market": "KOSPI"}]
    _setup_authority(tmp_path, certified_through=target, target_rows=target_rows)

    rows_override = {
        code: [{"종목코드": str(i).zfill(6), "종목명": f"종목_{i}"}]
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    }
    _write_marketplace(tmp_path, target, rows_override=rows_override)

    result = update_sector_membership_exact(target, repo_root=tmp_path)
    assert result.status == PASS
    assert result.unmapped == 1

    snapshot = load_sector_membership_snapshot(target, repo_root=tmp_path)
    unmapped_row = snapshot[snapshot["ticker"] == "999999"].iloc[0]
    assert unmapped_row["resolution_status"] == "UNMAPPED"
    assert pd.isna(unmapped_row["sector_code"])
    assert pd.isna(unmapped_row["sector_name"])


# T12 — second run NOOP
def test_t12_second_run_is_noop(tmp_path: Path) -> None:
    target = "2026-09-17"
    target_rows = [
        {"ticker": str(i).zfill(6), "market": "KOSPI" if str(code) in KOSPI_SECTOR_CODES else "KOSDAQ"}
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    ]
    _setup_authority(tmp_path, certified_through=target, target_rows=target_rows)
    rows_override = {
        code: [{"종목코드": str(i).zfill(6), "종목명": f"종목_{i}"}]
        for i, code in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.keys(), start=1)
    }
    _write_marketplace(tmp_path, target, rows_override=rows_override)

    # First run publishes
    first = update_sector_membership_exact(target, repo_root=tmp_path)
    assert first.status == PASS
    assert first.builder_called is True
    assert first.published is True

    snap_path = sector_membership_path_for_date(target, tmp_path)
    meta_path = sector_membership_meta_path_for_date(target, tmp_path)
    mtime_parquet = snap_path.stat().st_mtime_ns
    size_parquet = snap_path.stat().st_size
    sha_parquet = _file_sha256(snap_path)
    mtime_meta = meta_path.stat().st_mtime_ns
    size_meta = meta_path.stat().st_size

    calls: list[str] = []

    def mock_builder(t: str, *, repo_root: Path) -> RollingMembershipRun:
        calls.append(t)
        raise RuntimeError("should not be called on second run")

    # Second run NOOP
    second = update_sector_membership_exact(target, repo_root=tmp_path, builder=mock_builder)
    assert second.status == NOOP_ALREADY_COMPLETE
    assert second.reason == REASON_NOOP_COMPLETE
    assert second.builder_called is False
    assert second.published is False
    assert len(calls) == 0

    assert snap_path.stat().st_mtime_ns == mtime_parquet
    assert snap_path.stat().st_size == size_parquet
    assert _file_sha256(snap_path) == sha_parquet
    assert meta_path.stat().st_mtime_ns == mtime_meta
    assert meta_path.stat().st_size == size_meta
