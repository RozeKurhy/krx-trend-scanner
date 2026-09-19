"""Focused tests for approved periodic Sector Membership authority selection."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.sector_membership import (
    STORE_COLUMNS,
    SectorMembershipSnapshotUnavailable,
    resolve_sector_membership_snapshot_for_target,
    sector_membership_meta_path_for_date,
    sector_membership_path_for_date,
)
from trend_scanner.relative_strength.sector_ranking import HORIZONS


ROOT = Path(__file__).resolve().parents[1]


def _snapshot_frame(effective_date: str) -> pd.DataFrame:
    rows = [
        {
            "ticker": "005930",
            "market": "KOSPI",
            "effective_date": effective_date,
            "sector_code": "1001",
            "sector_name": "테스트업종",
            "resolution_status": "MAPPED",
            "policy_version": "MOST_SPECIFIC_NATIVE_SECTOR_V01",
            "source_authority": "KRX_FROZEN_CANONICAL_SECTOR_MEMBERSHIP",
            "source_artifact_sha256": "a" * 64,
        },
        {
            "ticker": "000001",
            "market": "KOSPI",
            "effective_date": effective_date,
            "sector_code": "1001",
            "sector_name": "테스트업종",
            "resolution_status": "MAPPED",
            "policy_version": "MOST_SPECIFIC_NATIVE_SECTOR_V01",
            "source_authority": "KRX_FROZEN_CANONICAL_SECTOR_MEMBERSHIP",
            "source_artifact_sha256": "b" * 64,
        },
    ]
    return pd.DataFrame(rows, columns=list(STORE_COLUMNS))


def _write_snapshot(
    root: Path,
    effective_date: str,
    *,
    frame: pd.DataFrame | None = None,
    write_parquet: bool = True,
    write_meta: bool = True,
) -> tuple[Path, Path]:
    snapshot = frame if frame is not None else _snapshot_frame(effective_date)
    parquet_path = sector_membership_path_for_date(effective_date, root)
    meta_path = sector_membership_meta_path_for_date(effective_date, root)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if write_parquet:
        snapshot.to_parquet(parquet_path, index=False)
    if write_meta:
        meta_path.write_text(
            json.dumps(
                {
                    "schema_version": "SECTOR_MEMBERSHIP_STORE_V01",
                    "snapshot_effective_date": effective_date,
                    "target_population": len(snapshot),
                }
            ),
            encoding="utf-8",
        )
    return parquet_path, meta_path


def test_resolver_uses_latest_approved_snapshot_not_after_target(tmp_path: Path) -> None:
    _write_snapshot(tmp_path, "2026-09-04")
    latest_path, _ = _write_snapshot(tmp_path, "2026-09-17")

    _, effective_date, selected_path, meta = resolve_sector_membership_snapshot_for_target(
        "2026-09-18", repo_root=tmp_path
    )
    assert effective_date == "2026-09-17"
    assert selected_path == latest_path
    assert meta["snapshot_effective_date"] == "2026-09-17"

    _, effective_date, selected_path, _ = resolve_sector_membership_snapshot_for_target(
        "2026-09-10", repo_root=tmp_path
    )
    assert effective_date == "2026-09-04"
    assert selected_path == sector_membership_path_for_date("2026-09-04", tmp_path)


def test_resolver_blocks_when_only_future_snapshot_exists(tmp_path: Path) -> None:
    _write_snapshot(tmp_path, "2026-09-17")
    with pytest.raises(SectorMembershipSnapshotUnavailable, match="NO_APPROVED_SNAPSHOT"):
        resolve_sector_membership_snapshot_for_target("2026-09-16", repo_root=tmp_path)


def test_resolver_does_not_fallback_from_partial_latest_candidate(tmp_path: Path) -> None:
    _write_snapshot(tmp_path, "2026-09-04")
    _write_snapshot(tmp_path, "2026-09-17", write_meta=False)

    with pytest.raises(SectorMembershipSnapshotUnavailable, match="INCOMPLETE:2026-09-17"):
        resolve_sector_membership_snapshot_for_target("2026-09-18", repo_root=tmp_path)


def test_resolver_does_not_fallback_from_invalid_latest_candidate(tmp_path: Path) -> None:
    _write_snapshot(tmp_path, "2026-09-04")
    invalid = _snapshot_frame("2026-09-16")
    _write_snapshot(tmp_path, "2026-09-17", frame=invalid)

    with pytest.raises(SectorMembershipSnapshotUnavailable, match="EFFECTIVE_DATE_INVALID"):
        resolve_sector_membership_snapshot_for_target("2026-09-18", repo_root=tmp_path)


def _load_builder_module():
    script_path = ROOT / "scripts/build_sector_rs_ranking_v01.py"
    spec = importlib.util.spec_from_file_location("build_sector_rs_ranking_v01_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_3f_consumer_records_selected_prior_membership_snapshot(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, "2026-09-17")
    sector_index_path = tmp_path / "sector_index_daily.parquet"
    pd.DataFrame(
        {
            "date": ["2026-09-18"] * 46,
            "index_code": [f"S{index:03d}" for index in range(46)],
            "close": [100.0] * 46,
        }
    ).to_parquet(sector_index_path, index=False)

    builder = _load_builder_module()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "SECTOR_INDEX_PATH", sector_index_path)
    monkeypatch.setattr(builder, "SECTOR_INDEX_SOURCE", str(sector_index_path.relative_to(tmp_path)))
    monkeypatch.setattr(builder, "_install_network_guard", lambda: None)
    captured: dict[str, object] = {}

    def fake_compute_rows(
        as_of: str,
        membership: pd.DataFrame,
        sector_index: pd.DataFrame,
        membership_effective_date: str,
    ) -> pd.DataFrame:
        captured["as_of"] = as_of
        captured["membership_effective_date"] = membership_effective_date
        captured["sector_index_rows"] = len(sector_index)
        rows: list[dict[str, object]] = []
        for offset, member in enumerate(membership.itertuples(index=False)):
            row: dict[str, object] = {
                "as_of": as_of,
                "ticker": str(member.ticker),
                "market": str(member.market),
                "membership_status": str(member.resolution_status),
                "sector_code": str(member.sector_code),
                "sector_name": str(member.sector_name),
                "sector_rs_data_status": "READY",
                "sector_rs_input_reason": "READY_INPUT",
                "sector_benchmark_last_observation_date": as_of,
                "latest_close": 100.0 + offset,
                "latest_close_as_of": as_of,
            }
            for horizon in HORIZONS:
                row[f"sector_rs_{horizon}"] = float(offset + 1)
                row[f"sector_anchor_date_{horizon}"] = None
                row[f"sector_stock_return_{horizon}"] = None
            rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(builder, "_compute_rows", fake_compute_rows)
    output_dir = tmp_path / "output"
    builder.build_sector_rs_ranking(as_of="2026-09-18", output_dir=output_dir)

    assert captured == {
        "as_of": "2026-09-18",
        "membership_effective_date": "2026-09-17",
        "sector_index_rows": 46,
    }
    meta = json.loads(
        (output_dir / "sector_rs_ranking_20260918_meta.json").read_text(encoding="utf-8")
    )
    assert meta["membership_effective_date"] == "2026-09-17"
    assert meta["scope"]["type"] == "APPROVED_SECTOR_MEMBERSHIP_POPULATION"
    assert meta["source"]["membership"].endswith("sector_membership_20260917.parquet")
