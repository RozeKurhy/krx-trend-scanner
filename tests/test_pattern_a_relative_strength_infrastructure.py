"""Integration and Dynamic Hard Gate Negative Tests for Phase 12 Relative Strength Infrastructure."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthDataStatus,
    compute_relative_strength_features,
)
from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe
from trend_scanner.universe.models import MarketType
from trend_scanner.validation.pattern_a_relative_strength_infrastructure import (
    run_relative_strength_validation,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_relative_strength_infrastructure_execution(repo_root: Path):
    """Verify evaluation of all 10 Dynamic Hard Gates on Phase 12 artifacts."""
    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=repo_root)

    gates = result["gates"]
    assert gates["gate_01_frozen_identity_parity"]["passed"] is True
    assert gates["gate_02_market_benchmark_source_identity"]["passed"] is True
    assert gates["gate_03_pit_no_lookahead_contract"]["passed"] is True
    assert gates["gate_04_exact_freshness_anchor_contract"]["passed"] is True
    assert gates["gate_05_market_benchmark_selection_contract"]["passed"] is True
    assert gates["gate_06_market_rs_arithmetic_parity"]["passed"] is True
    assert gates["gate_09_fail_closed_schema_compatibility"]["passed"] is True
    assert gates["gate_10_production_test_suite_pass"]["passed"] is True

    # Sector source is currently empty/isolated -> Gate 7 & 8 fail-closed
    assert gates["gate_07_sector_mapping_contract"]["passed"] is False
    assert gates["gate_08_sector_rs_arithmetic_parity"]["passed"] is False
    assert result["verdict"] == "HOLD_RELATIVE_STRENGTH_INFRA"


def test_future_sector_mapping_leakage_negative_test(repo_root: Path):
    """Verify that historical scan (2025-01-31) strictly rejects future sector mapping (2026-08-14)."""
    # 1. Direct function call test with future effective_date
    res_direct = compute_relative_strength_features(
        ticker="005930",
        as_of="2025-01-31",
        stock_df=None,
        market_index_df=None,
        market=MarketType.KOSPI,
        sector_mapping={"005930": ("1005", "음식료품", "2026-08-14")},
    )
    assert res_direct.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert res_direct.sector_name is None
    assert res_direct.sector_code is None

    # 2. Scanner-level PIT enforcement test
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    mapping_file = repo_root / "artifacts/relative_strength/source/sector_mapping_20260814.csv"

    scan_res = scan_pattern_a_universe(
        cache=cache,
        as_of="2025-01-31",
        reference_market_date="2026-08-14",
        target_tickers=["005930"],
        sector_mapping_path=mapping_file,
    )
    assert len(scan_res.rows) == 1
    row = scan_res.rows[0]
    # Future mapping must be rejected -> sector_name and sector_code remain None
    assert row.sector_name is None
    assert row.sector_code is None
    assert row.sector_rs_data_status in (
        RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
        RelativeStrengthDataStatus.NOT_EVALUATED.value,
    )


def test_gate1_negative_missing_oracle(tmp_path: Path):
    """Gate 1 Negative: Missing canonical oracle fails closed (Gate 1 FAIL)."""
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["verdict"] == "HOLD_RELATIVE_STRENGTH_INFRA"
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False


def test_gate1_negative_stage_mutation(tmp_path: Path, repo_root: Path):
    """Gate 1 Negative: Mutating candidate stage triggers Gate 1 FAIL."""
    dest_inv = tmp_path / "artifacts/investability"
    dest_inv.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_universe_20260814.csv",
        dest_inv / "pattern_a_investability_universe_20260814.csv",
    )
    df_cand = pd.read_csv(repo_root / "artifacts/investability/pattern_a_investability_candidates_20260814.csv")
    df_cand.loc[0, "official_stage"] = "MUTATED_STAGE"
    df_cand.to_csv(dest_inv / "pattern_a_investability_candidates_20260814.csv", index=False)
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_integration_20260814.csv",
        dest_inv / "pattern_a_investability_integration_20260814.csv",
    )

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")
    shutil.copytree(repo_root / "artifacts/flow", tmp_path / "artifacts/flow")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["stage_mismatches"] > 0


def test_gate1_negative_score_mutation(tmp_path: Path, repo_root: Path):
    """Gate 1 Negative: Mutating candidate score triggers Gate 1 FAIL."""
    dest_inv = tmp_path / "artifacts/investability"
    dest_inv.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_universe_20260814.csv",
        dest_inv / "pattern_a_investability_universe_20260814.csv",
    )
    df_cand = pd.read_csv(repo_root / "artifacts/investability/pattern_a_investability_candidates_20260814.csv")
    df_cand.loc[0, "pattern_a_score"] = 0.0001
    df_cand.to_csv(dest_inv / "pattern_a_investability_candidates_20260814.csv", index=False)
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_integration_20260814.csv",
        dest_inv / "pattern_a_investability_integration_20260814.csv",
    )

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")
    shutil.copytree(repo_root / "artifacts/flow", tmp_path / "artifacts/flow")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["score_mismatches"] > 0


def test_gate2_negative_hash_mismatch(tmp_path: Path, repo_root: Path):
    """Gate 2 Negative: Tampered market benchmark parquet file triggers hash mismatch (Gate 2 FAIL)."""
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

    # Corrupt meta sha
    meta = json.loads((dest_dir / "market_index_daily_20260814_meta.json").read_text(encoding="utf-8"))
    meta["parquet_sha256"] = "TAMPERED_HASH"
    (dest_dir / "market_index_daily_20260814_meta.json").write_text(json.dumps(meta), encoding="utf-8")

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


def test_gate10_negative_missing_report(tmp_path: Path):
    """Gate 10 Negative: Missing pytest report fails Gate 10."""
    from trend_scanner.validation.pattern_a_relative_strength_infrastructure import _read_pytest_report
    exit_code, passed, failed, blocking_failed, _, _, _ = _read_pytest_report(tmp_path)
    assert exit_code == -1
    assert failed == -1
    assert blocking_failed == -1
    assert passed == 0


def test_gate10_negative_corrupted_report(tmp_path: Path):
    """Gate 10 Negative: Corrupted report.json fails Gate 10."""
    from trend_scanner.validation.pattern_a_relative_strength_infrastructure import _read_pytest_report
    res_dir = tmp_path / ".pytest_results"
    res_dir.mkdir(parents=True)
    (res_dir / "report.json").write_text("INVALID_JSON", encoding="utf-8")

    exit_code, passed, failed, blocking_failed, _, _, _ = _read_pytest_report(tmp_path)
    assert exit_code == -1
    assert failed == -1
    assert blocking_failed == -1
    assert passed == 0
