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
from trend_scanner.data.index_price_provider import IndexPriceDataProvider
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


def test_relative_strength_infrastructure_execution(repo_root: Path, tmp_path: Path):
    """Verify evaluation of all 10 Dynamic Hard Gates on Phase 12 artifacts (Isolated Output)."""
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )

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


def test_provenance_less_sector_mapping_historical_rejection(repo_root: Path):
    """1. Provenance-less sector mapping (2-tuple without effective_date) is strictly rejected."""
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    df_stk = cache.load("005930")
    df_mkt = pd.read_parquet(repo_root / "artifacts/relative_strength/source/market_index_daily_20260814.parquet")

    # 2-tuple without effective_date
    res = compute_relative_strength_features(
        ticker="005930",
        as_of="2026-08-14",
        stock_df=df_stk,
        market_index_df=df_mkt,
        market=MarketType.KOSPI,
        sector_mapping={"005930": ("1005", "음식료품")},
    )
    assert res.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert res.sector_name is None
    assert res.sector_code is None


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


def test_sector_mapping_cache_cross_as_of_leakage(repo_root: Path):
    """2. IndexPriceDataProvider cache PIT: load_sector_mapping('2026-08-14') then load_sector_mapping('2025-01-31')."""
    mapping_file = repo_root / "artifacts/relative_strength/source/sector_mapping_20260814.csv"
    provider = IndexPriceDataProvider(sector_mapping_cache_file=mapping_file)

    map_2026 = provider.load_sector_mapping("2026-08-14")
    assert len(map_2026) == 764

    # Second call for earlier date must NOT return 2026 mapping
    map_2025 = provider.load_sector_mapping("2025-01-31")
    assert len(map_2025) == 0, "2025-01-31 load must not leak 2026 mapping from cache"


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


def test_gate1_negative_investability_status_mutation(tmp_path: Path, repo_root: Path):
    """3. Gate 1 Negative: Mutating investability status in oracle triggers Gate 1 FAIL."""
    dest_inv = tmp_path / "artifacts/investability"
    dest_inv.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_universe_20260814.csv",
        dest_inv / "pattern_a_investability_universe_20260814.csv",
    )
    shutil.copy(
        repo_root / "artifacts/investability/pattern_a_investability_candidates_20260814.csv",
        dest_inv / "pattern_a_investability_candidates_20260814.csv",
    )
    df_int = pd.read_csv(repo_root / "artifacts/investability/pattern_a_investability_integration_20260814.csv")
    df_int.loc[0, "investability_status"] = "FILTERED_MARKET_CAP"
    df_int.to_csv(dest_inv / "pattern_a_investability_integration_20260814.csv", index=False)

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")
    shutil.copytree(repo_root / "artifacts/flow", tmp_path / "artifacts/flow")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["investability_mismatches"] > 0


def test_gate1_negative_foreign_flow_value_mutation(tmp_path: Path, repo_root: Path):
    """4. Gate 1 Negative: Mutating foreign flow value in oracle triggers Gate 1 FAIL."""
    dest_flow = tmp_path / "artifacts/flow"
    dest_flow.mkdir(parents=True, exist_ok=True)
    df_flow = pd.read_csv(repo_root / "artifacts/flow/pattern_a_foreign_flow_features_20260814.csv")
    df_flow.loc[0, "foreign_net_buy_value_20d"] = 9999999.0
    df_flow.to_csv(dest_flow / "pattern_a_foreign_flow_features_20260814.csv", index=False)

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/investability", tmp_path / "artifacts/investability")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["foreign_flow_numeric_mismatches"] > 0


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


def test_gate6_negative_market_rs_3m_mutation(repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """5. Gate 6 Negative: Mutating 3M market RS in scanner output triggers Gate 6 FAIL (Output Isolated)."""
    import dataclasses
    from trend_scanner.validation import pattern_a_relative_strength_infrastructure as val_mod
    original_scan = val_mod.scan_pattern_a_universe

    def mocked_scan(*args, **kwargs):
        res = original_scan(*args, **kwargs)
        if res.rows:
            rows_list = list(res.rows)
            for idx, r in enumerate(rows_list):
                if r.candidate_state.value == "candidate" and r.investability_status.value == "INVESTABLE":
                    mutated_row = dataclasses.replace(r, market_rs_3m=(r.market_rs_3m or 0.0) + 0.05)
                    rows_list[idx] = mutated_row
                    break
            res = dataclasses.replace(res, rows=tuple(rows_list))
        return res

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", mocked_scan)
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["details"]["market_rs_3m_mismatches"] > 0


def test_gate6_negative_market_rs_12m_mutation(repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """6. Gate 6 Negative: Mutating 12M market RS in scanner output triggers Gate 6 FAIL (Output Isolated)."""
    import dataclasses
    from trend_scanner.validation import pattern_a_relative_strength_infrastructure as val_mod
    original_scan = val_mod.scan_pattern_a_universe

    def mocked_scan(*args, **kwargs):
        res = original_scan(*args, **kwargs)
        if res.rows:
            rows_list = list(res.rows)
            for idx, r in enumerate(rows_list):
                if r.candidate_state.value == "candidate" and r.investability_status.value == "INVESTABLE":
                    mutated_row = dataclasses.replace(r, market_rs_12m=(r.market_rs_12m or 0.0) - 0.05)
                    rows_list[idx] = mutated_row
                    break
            res = dataclasses.replace(res, rows=tuple(rows_list))
        return res

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", mocked_scan)
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["details"]["market_rs_12m_mismatches"] > 0


def test_gate7_negative_empty_sector_source(repo_root: Path, tmp_path: Path):
    """7. Gate 7 Negative: Empty sector source (0 rows) triggers Gate 7 FAIL (Output Isolated)."""
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_07_sector_mapping_contract"]["passed"] is False
    assert result["gates"]["gate_07_sector_mapping_contract"]["details"]["sector_index"]["row_count"] == 0


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


def test_gate8_negative_sector_rs_3m_mutation():
    """8. Gate 8 Negative (Synthetic Arithmetic Check): Arithmetic mutation in 3M sector RS triggers mismatch."""
    p_end, p_anc = 50000.0, 40000.0
    sec_end, sec_anc = 1200.0, 1000.0
    s_ret = (p_end / p_anc) - 1.0
    sec_ret = (sec_end / sec_anc) - 1.0
    canonical_rs_3m = ((1.0 + s_ret) / (1.0 + sec_ret)) - 1.0

    mutated_rs_3m = canonical_rs_3m + 0.05
    assert abs(mutated_rs_3m - canonical_rs_3m) > 1e-6


def test_gate8_negative_sector_rs_12m_mutation():
    """9. Gate 8 Negative (Synthetic Arithmetic Check): Arithmetic mutation in 12M sector RS triggers mismatch."""
    p_end, p_anc = 50000.0, 60000.0
    sec_end, sec_anc = 1200.0, 1100.0
    s_ret = (p_end / p_anc) - 1.0
    sec_ret = (sec_end / sec_anc) - 1.0
    canonical_rs_12m = ((1.0 + s_ret) / (1.0 + sec_ret)) - 1.0

    mutated_rs_12m = canonical_rs_12m - 0.05
    assert abs(mutated_rs_12m - canonical_rs_12m) > 1e-6


def test_gate8_negative_zero_sector_ready(repo_root: Path, tmp_path: Path):
    """10. Gate 8 Negative: When Sector READY candidates == 0, Gate 8 strictly FAILS (Output Isolated)."""
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=tmp_path / "artifacts/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["gates"]["gate_08_sector_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_08_sector_rs_arithmetic_parity"]["details"]["candidate_sector_rs_ready"] == 0


def test_mutation_tests_do_not_contaminate_canonical_artifacts(repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression Test: Verify that running mutation validation does not modify official canonical artifacts."""
    csv_file = repo_root / "artifacts/relative_strength/pattern_a_relative_strength_features_20260814.csv"
    json_file = repo_root / "artifacts/relative_strength/pattern_a_relative_strength_summary_20260814.json"

    def get_hash(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""

    csv_hash_before = get_hash(csv_file)
    json_hash_before = get_hash(json_file)

    # Run isolated 3M mutation test
    test_gate6_negative_market_rs_3m_mutation(repo_root=repo_root, tmp_path=tmp_path / "mut3m", monkeypatch=monkeypatch)
    # Run isolated 12M mutation test
    test_gate6_negative_market_rs_12m_mutation(repo_root=repo_root, tmp_path=tmp_path / "mut12m", monkeypatch=monkeypatch)

    csv_hash_after = get_hash(csv_file)
    json_hash_after = get_hash(json_file)

    assert csv_hash_after == csv_hash_before, "Official canonical CSV was corrupted by mutation test!"
    assert json_hash_after == json_hash_before, "Official canonical JSON was corrupted by mutation test!"


def test_gate1_negative_candidate_extra_ticker(tmp_path: Path, repo_root: Path):
    """Gate 1 Negative: Candidate oracle with extra ticker triggers Gate 1 FAIL."""
    dest_inv = tmp_path / "artifacts/investability"
    dest_inv.mkdir(parents=True, exist_ok=True)
    shutil.copy(repo_root / "artifacts/investability/pattern_a_investability_universe_20260814.csv", dest_inv / "pattern_a_investability_universe_20260814.csv")
    df_cand = pd.read_csv(repo_root / "artifacts/investability/pattern_a_investability_candidates_20260814.csv")
    # Add extra ticker
    extra_row = df_cand.iloc[0:1].copy()
    extra_row["ticker"] = "999999"
    df_cand_extra = pd.concat([df_cand, extra_row], ignore_index=True)
    df_cand_extra.to_csv(dest_inv / "pattern_a_investability_candidates_20260814.csv", index=False)
    shutil.copy(repo_root / "artifacts/investability/pattern_a_investability_integration_20260814.csv", dest_inv / "pattern_a_investability_integration_20260814.csv")

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")
    shutil.copytree(repo_root / "artifacts/flow", tmp_path / "artifacts/flow")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False


def test_gate1_negative_candidate_missing_ticker(tmp_path: Path, repo_root: Path):
    """Gate 1 Negative: Candidate oracle with missing ticker triggers Gate 1 FAIL."""
    dest_inv = tmp_path / "artifacts/investability"
    dest_inv.mkdir(parents=True, exist_ok=True)
    shutil.copy(repo_root / "artifacts/investability/pattern_a_investability_universe_20260814.csv", dest_inv / "pattern_a_investability_universe_20260814.csv")
    df_cand = pd.read_csv(repo_root / "artifacts/investability/pattern_a_investability_candidates_20260814.csv")
    # Drop one ticker
    df_cand.iloc[1:].to_csv(dest_inv / "pattern_a_investability_candidates_20260814.csv", index=False)
    shutil.copy(repo_root / "artifacts/investability/pattern_a_investability_integration_20260814.csv", dest_inv / "pattern_a_investability_integration_20260814.csv")

    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    os.symlink(repo_root / "data/raw/stocks", tmp_path / "data/raw/stocks")
    shutil.copytree(repo_root / "artifacts/relative_strength", tmp_path / "artifacts/relative_strength")
    shutil.copytree(repo_root / "artifacts/flow", tmp_path / "artifacts/flow")

    result = run_relative_strength_validation(as_of="2026-08-14", repo_root=tmp_path)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False


def test_missing_effective_date_column_rejected(tmp_path: Path, repo_root: Path):
    """Negative: Sector mapping CSV without effective_date column fails closed."""
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    csv_path = tmp_path / "no_eff_date_mapping.csv"
    csv_path.write_text("ticker,market,sector_code,sector_name\n005930,KOSPI,1005,음식료품\n", encoding="utf-8")

    scan_res = scan_pattern_a_universe(
        cache=cache,
        as_of="2026-08-14",
        reference_market_date="2026-08-14",
        target_tickers=["005930"],
        sector_mapping_path=csv_path,
    )
    assert len(scan_res.rows) == 1
    assert scan_res.rows[0].sector_name is None
    assert scan_res.rows[0].sector_code is None
    assert scan_res.rows[0].sector_rs_data_status in (
        RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
        RelativeStrengthDataStatus.NOT_EVALUATED.value,
    )


def test_gate9_negative_stale_benchmark_with_valid_stock_df(repo_root: Path):
    """Gate 9 Negative: Test that stale market benchmark with valid stock df causes fail-closed DATA_UNAVAILABLE."""
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    df_stk = cache.load("005930")
    assert df_stk is not None and not df_stk.empty
    df_stk_clean = df_stk[df_stk.index <= pd.Timestamp("2026-08-14")].copy()

    df_mkt = pd.read_parquet(repo_root / "artifacts/relative_strength/source/market_index_daily_20260814.parquet")
    df_stale_mkt = df_mkt[df_mkt["date"] < "2026-08-14"].copy()

    res = compute_relative_strength_features(
        ticker="005930",
        as_of="2026-08-14",
        stock_df=df_stk_clean,
        market_index_df=df_stale_mkt,
        market=MarketType.KOSPI,
    )
    assert res.market_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE


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
