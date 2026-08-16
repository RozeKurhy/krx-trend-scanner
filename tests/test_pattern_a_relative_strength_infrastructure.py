"""Integration and Dynamic Hard Gate Negative Tests for Phase 12 Relative Strength Infrastructure."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

import pandas as pd
import pytest

from trend_scanner.validation.pattern_a_relative_strength_infrastructure import (
    run_relative_strength_validation,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_relative_strength_infrastructure_all_gates_pass(repo_root: Path):
    """Verify that all 10 Dynamic Hard Gates pass on canonical Phase 12 artifacts."""
    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=repo_root)

    assert result["verdict"] == "RELATIVE_STRENGTH_INFRA_READY"
    assert result["all_gates_passed"] is True

    gates = result["gates"]
    assert gates["gate_01_frozen_identity_parity"]["passed"] is True
    assert gates["gate_02_market_benchmark_source_identity"]["passed"] is True
    assert gates["gate_03_pit_no_lookahead_contract"]["passed"] is True
    assert gates["gate_04_exact_freshness_anchor_contract"]["passed"] is True
    assert gates["gate_05_market_benchmark_selection_contract"]["passed"] is True
    assert gates["gate_06_market_rs_arithmetic_parity"]["passed"] is True
    assert gates["gate_07_sector_mapping_contract"]["passed"] is True
    assert gates["gate_08_sector_rs_arithmetic_parity"]["passed"] is True
    assert gates["gate_09_fail_closed_schema_compatibility"]["passed"] is True
    assert gates["gate_10_production_test_suite_pass"]["passed"] is True


def test_gate1_negative_missing_oracle(tmp_path: Path):
    """Gate 1 Negative: Missing canonical oracle fails closed (Gate 1 FAIL)."""
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["verdict"] == "RELATIVE_STRENGTH_INFRA_BLOCKED"
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False


def test_gate2_negative_hash_mismatch(tmp_path: Path, repo_root: Path):
    """Gate 2 Negative: Tampered market benchmark parquet file triggers hash mismatch (Gate 2 FAIL)."""
    dest_dir = tmp_path / "artifacts/relative_strength/source"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Symlink large directories for instant test setup
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/investability", tmp_path / "artifacts/investability")

    src_dir = repo_root / "artifacts/relative_strength/source"
    shutil.copy(src_dir / "market_index_daily_20260814.parquet", dest_dir / "market_index_daily_20260814.parquet")
    shutil.copy(src_dir / "market_index_daily_20260814_meta.json", dest_dir / "market_index_daily_20260814_meta.json")
    shutil.copy(src_dir / "sector_mapping_20260814.csv", dest_dir / "sector_mapping_20260814.csv")
    shutil.copy(src_dir / "sector_mapping_20260814_meta.json", dest_dir / "sector_mapping_20260814_meta.json")
    shutil.copy(src_dir / "sector_index_daily_20260814.parquet", dest_dir / "sector_index_daily_20260814.parquet")
    shutil.copy(src_dir / "sector_index_daily_20260814_meta.json", dest_dir / "sector_index_daily_20260814_meta.json")

    # Tamper parquet content (corrupt trailing bytes)
    with open(dest_dir / "market_index_daily_20260814.parquet", "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_02_market_benchmark_source_identity"]["passed"] is False


def test_gate4_negative_stale_market_date(tmp_path: Path, repo_root: Path):
    """Gate 4 Negative: Benchmark missing exact requested as_of observation date (Gate 4 FAIL)."""
    dest_dir = tmp_path / "artifacts/relative_strength/source"
    dest_dir.mkdir(parents=True, exist_ok=True)

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/investability", tmp_path / "artifacts/investability")

    src_dir = repo_root / "artifacts/relative_strength/source"
    # Load and drop the last row (2026-08-14)
    df_mkt = pd.read_parquet(src_dir / "market_index_daily_20260814.parquet")
    df_stale = df_mkt[df_mkt["date"] < "2026-08-14"].copy()
    dest_p = dest_dir / "market_index_daily_20260814.parquet"
    df_stale.to_parquet(dest_p, index=False)

    meta_dict = json.loads((src_dir / "market_index_daily_20260814_meta.json").read_text(encoding="utf-8"))
    h = hashlib.sha256(dest_p.read_bytes()).hexdigest()
    meta_dict["parquet_sha256"] = h
    meta_dict["row_count"] = len(df_stale)
    meta_dict["date_max"] = str(df_stale["date"].max())
    (dest_dir / "market_index_daily_20260814_meta.json").write_text(json.dumps(meta_dict), encoding="utf-8")

    shutil.copy(src_dir / "sector_mapping_20260814.csv", dest_dir / "sector_mapping_20260814.csv")
    shutil.copy(src_dir / "sector_mapping_20260814_meta.json", dest_dir / "sector_mapping_20260814_meta.json")
    shutil.copy(src_dir / "sector_index_daily_20260814.parquet", dest_dir / "sector_index_daily_20260814.parquet")
    shutil.copy(src_dir / "sector_index_daily_20260814_meta.json", dest_dir / "sector_index_daily_20260814_meta.json")

    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_04_exact_freshness_anchor_contract"]["passed"] is False


def test_gate7_negative_sector_mapping_hash_mismatch(tmp_path: Path, repo_root: Path):
    """Gate 7 Negative: Tampered sector mapping CSV triggers hash mismatch (Gate 7 FAIL)."""
    dest_dir = tmp_path / "artifacts/relative_strength/source"
    dest_dir.mkdir(parents=True, exist_ok=True)

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/investability", tmp_path / "artifacts/investability")

    src_dir = repo_root / "artifacts/relative_strength/source"
    shutil.copy(src_dir / "market_index_daily_20260814.parquet", dest_dir / "market_index_daily_20260814.parquet")
    shutil.copy(src_dir / "market_index_daily_20260814_meta.json", dest_dir / "market_index_daily_20260814_meta.json")
    shutil.copy(src_dir / "sector_mapping_20260814.csv", dest_dir / "sector_mapping_20260814.csv")
    shutil.copy(src_dir / "sector_mapping_20260814_meta.json", dest_dir / "sector_mapping_20260814_meta.json")
    shutil.copy(src_dir / "sector_index_daily_20260814.parquet", dest_dir / "sector_index_daily_20260814.parquet")
    shutil.copy(src_dir / "sector_index_daily_20260814_meta.json", dest_dir / "sector_index_daily_20260814_meta.json")

    # Corrupt sector mapping csv
    with open(dest_dir / "sector_mapping_20260814.csv", "a", encoding="utf-8") as f:
        f.write("\n999999,KOSPI,9999,임의업종,2026-08-14\n")

    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_07_sector_mapping_contract"]["passed"] is False
