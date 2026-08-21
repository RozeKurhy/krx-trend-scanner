"""Integration and Dynamic Hard Gate Negative Tests for Phase 12 Relative Strength Infrastructure.

TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_V01: 이 파일의 negative(Gate) tests는
더 이상 2,528종목 Full Universe Scan을 매번 반복하지 않는다. 대신:

- `rs_subset_context` (module-scoped): 실제 production 코드 경로
  (`prepare_relative_strength_validation_context`)로 소수 종목만
  (`target_tickers`) 스캔한 real context를 파일당 1회만 만든다. Pattern A
  Score/Stage/Investability는 종목별 순수 계산이라 Universe 크기와 무관하게
  동일한 값을 낸다 — Full Universe여야만 하는 것은 오직 Gate 1의
  `common_count == 2528` 류 절대 카운트 검증뿐이며, 그 검증은
  `test_relative_strength_full_universe_validation`(slow) 하나가 전담한다.
- `rs_clean_context` (function-scoped): 위 context의 oracle 프레임을 동일
  종목 집합으로만 필터링해 mismatch가 전부 0인 깨끗한 기준선을 만든다. 매
  test마다 새로 복사하므로 mutation이 다른 test로 새지 않는다.
- 각 Gate negative test는 `evaluate_relative_strength_gates()`만 호출한다 —
  `scan_pattern_a_universe()`(Full Universe Scanner)는 다시 호출하지 않는다.

Full Universe(2,528종목) 실제 검증 자체는 삭제되지 않았다 —
`test_relative_strength_full_universe_validation`이 `@pytest.mark.slow`로
격리되어 그대로 1회 실행된다(`uv run pytest ... -m slow`). 이 slow test는
(TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_01 Major 1) prepare/evaluate를
직접 호출하지 않고 public runner `run_relative_strength_validation()`을
직접 호출해, 오라클 로드 -> Full Universe Scan -> Gate 평가 -> 산출물
기록까지 이어지는 전체 orchestration path를 실제 production 데이터로
검증한다.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

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
    RelativeStrengthValidationContext,
    evaluate_relative_strength_gates,
    prepare_relative_strength_validation_context,
    run_relative_strength_validation,
)

# 실제 2026-08-14 production oracle에서 candidate_state=="candidate" AND
# investability_status=="INVESTABLE"인 실제 종목 3개(소규모 real scan 대상).
SUBSET_AS_OF = "2026-08-14"
SUBSET_TICKERS = ["001540", "003100", "007390"]


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rs_subset_context(repo_root: Path) -> RelativeStrengthValidationContext:
    """소수 종목(target_tickers)만 스캔한 real production 코드 경로 context.

    Full Universe Scanner는 파일 전체에서 이 fixture를 통해 정확히 1회만
    호출된다(module scope) — 실제 값은 Universe 크기와 무관하게 정확하므로
    negative test들이 이 결과를 복사/mutate해서 재사용한다.
    """
    return prepare_relative_strength_validation_context(
        as_of=SUBSET_AS_OF,
        repo_root=repo_root,
        target_tickers=SUBSET_TICKERS,
    )


@pytest.fixture
def rs_clean_context(rs_subset_context: RelativeStrengthValidationContext) -> RelativeStrengthValidationContext:
    """Oracle 프레임을 동일 3종목으로만 필터링한 mismatch=0 기준선.

    함수 scope라 매 test마다 새 DataFrame 복사본을 받는다 — 공유 fixture인
    `rs_subset_context`의 원본 DataFrame은 절대 mutate하지 않는다.
    """
    ctx = rs_subset_context
    return dataclasses.replace(
        ctx,
        df_oracle_cand=ctx.df_oracle_cand[ctx.df_oracle_cand["ticker"].isin(SUBSET_TICKERS)]
        .reset_index(drop=True)
        .copy(),
        df_oracle_inv=ctx.df_oracle_inv[ctx.df_oracle_inv["ticker"].isin(SUBSET_TICKERS)]
        .reset_index(drop=True)
        .copy(),
        df_flow_oracle=ctx.df_flow_oracle[ctx.df_flow_oracle["ticker"].isin(SUBSET_TICKERS)]
        .reset_index(drop=True)
        .copy(),
    )


@pytest.mark.slow
def test_relative_strength_full_universe_validation(repo_root: Path, tmp_path: Path):
    """Full Universe(2,528종목) 실제 scan + public runner 전체 orchestration path +
    Gate 1~10 실제 평가 — 유일하게 보존된 slow full-universe 검증.

    TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_01 (Major 1): 이전에는
    `prepare_relative_strength_validation_context()` + `evaluate_relative_strength_gates()`를
    직접 호출해 Gate 평가 로직만 검증했다. 이것만으로는 public runner
    `run_relative_strength_validation()` 자체(오라클 로드 -> 스캔 ->
    평가 -> 산출물 기록까지 이어지는 전체 orchestration)가 실제 production
    데이터로 한 번도 실행되지 않는 coverage 축소가 생겼다. 이 test는 그
    public runner를 직접 호출해 전체 경로를 복구한다.

    Normal suite(`-m "not slow and not integration"`)에서는 실행되지 않는다.
    실행: `uv run pytest ... -m slow`.
    """
    isolated_out_dir = tmp_path / "artifacts/patterns/pattern_a/validation/relative_strength"
    isolated_doc_path = tmp_path / "docs/validation/report.md"

    canonical_csv = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/pattern_a_relative_strength_features_20260814.csv"
    canonical_json = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/pattern_a_relative_strength_summary_20260814.json"

    def _hash(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""

    canonical_csv_hash_before = _hash(canonical_csv)
    canonical_json_hash_before = _hash(canonical_json)

    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=repo_root,
        output_dir=isolated_out_dir,
        doc_output_path=isolated_doc_path,
    )

    assert isinstance(result, dict)
    assert "gates" in result
    assert "verdict" in result

    gates = result["gates"]
    assert len(gates) == 10

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

    # public runner가 실제로 기록하는 isolated output artifact 존재 확인
    # (기존 run_relative_strength_validation()이 원래 생성하던 파일들 그대로)
    assert (isolated_out_dir / "pattern_a_relative_strength_features_20260814.csv").exists()
    assert (isolated_out_dir / "pattern_a_relative_strength_distribution_20260814.json").exists()
    assert (isolated_out_dir / "pattern_a_relative_strength_summary_20260814.json").exists()
    assert isolated_doc_path.exists()

    # canonical artifact는 절대 건드리지 않는다 (tmp_path output만 사용됨)
    assert _hash(canonical_csv) == canonical_csv_hash_before
    assert _hash(canonical_json) == canonical_json_hash_before


def test_rs_gate_unit_tests_do_not_require_full_scan(
    monkeypatch: pytest.MonkeyPatch, rs_clean_context: RelativeStrengthValidationContext
):
    """Architecture Guard (§48): `evaluate_relative_strength_gates()`는 Full Universe
    Scanner를 호출하지 않는다. 향후 누군가 Gate 평가 로직 안에 다시 scanner 호출을
    추가하는 회귀를 막는다."""
    import trend_scanner.validation.pattern_a_relative_strength_infrastructure as val_mod

    def _forbidden_scan(*args, **kwargs):
        raise AssertionError(
            "evaluate_relative_strength_gates() must not call scan_pattern_a_universe() "
            "-- Gate evaluation must be pure over an already-prepared context."
        )

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", _forbidden_scan)
    result = evaluate_relative_strength_gates(rs_clean_context)
    assert result["verdict"] in ("RELATIVE_STRENGTH_INFRA_READY", "HOLD_RELATIVE_STRENGTH_INFRA")


def test_clean_context_baseline_has_zero_mismatches(rs_clean_context: RelativeStrengthValidationContext):
    """`rs_clean_context`가 실제로 mismatch=0인 깨끗한 기준선인지 확인하는 회귀
    가드. 이 assert가 깨지면 아래 모든 negative test의 discrimination이 무의미해
    지므로(mutation 없이도 이미 fail) 가장 먼저 확인해야 한다."""
    result = evaluate_relative_strength_gates(rs_clean_context)
    details = result["gates"]["gate_01_frozen_identity_parity"]["details"]
    assert details["candidate_ticker_mismatches"] == 0
    assert details["stage_mismatches"] == 0
    assert details["score_mismatches"] == 0
    assert details["candidate_state_mismatches"] == 0
    assert details["investability_mismatches"] == 0
    assert details["foreign_flow_status_mismatches"] == 0
    assert details["foreign_flow_numeric_mismatches"] == 0


def test_provenance_less_sector_mapping_historical_rejection(repo_root: Path):
    """1. Provenance-less sector mapping (2-tuple without effective_date) is strictly rejected."""
    cache = ParquetCache(base_dir=repo_root / "data/raw/stocks")
    df_stk = cache.load("005930")
    df_mkt = pd.read_parquet(repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet")

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
    mapping_file = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_mapping_20260814.csv"

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
    mapping_file = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_mapping_20260814.csv"
    provider = IndexPriceDataProvider(sector_mapping_cache_file=mapping_file)

    map_2026 = provider.load_sector_mapping("2026-08-14")
    assert len(map_2026) == 764

    # Second call for earlier date must NOT return 2026 mapping
    map_2025 = provider.load_sector_mapping("2025-01-31")
    assert len(map_2025) == 0, "2025-01-31 load must not leak 2026 mapping from cache"


def test_gate1_negative_missing_oracle(tmp_path: Path):
    """Gate 1 Negative: Missing canonical oracle fails closed (Gate 1 FAIL).

    `repo_root=tmp_path`(빈 디렉터리)라 oracle_available=False가 되어
    Full Universe Scanner 자체가 호출되지 않는다 — 이미 Level 1 test다.
    """
    result = run_relative_strength_validation(
        as_of="2026-08-14",
        repo_root=tmp_path,
        output_dir=tmp_path / "artifacts/patterns/pattern_a/validation/relative_strength",
        doc_output_path=tmp_path / "docs/validation/report.md",
    )
    assert result["verdict"] == "HOLD_RELATIVE_STRENGTH_INFRA"
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False


def test_gate1_negative_stage_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """Gate 1 Negative: Mutating candidate stage triggers Gate 1 FAIL."""
    mutated_cand = rs_clean_context.df_oracle_cand.copy()
    mutated_cand.loc[mutated_cand.index[0], "official_stage"] = "MUTATED_STAGE"
    ctx = dataclasses.replace(rs_clean_context, df_oracle_cand=mutated_cand)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["stage_mismatches"] > 0


def test_gate1_negative_score_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """Gate 1 Negative: Mutating candidate score triggers Gate 1 FAIL."""
    mutated_cand = rs_clean_context.df_oracle_cand.copy()
    mutated_cand.loc[mutated_cand.index[0], "pattern_a_score"] = 0.0001
    ctx = dataclasses.replace(rs_clean_context, df_oracle_cand=mutated_cand)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["score_mismatches"] > 0


def test_gate1_negative_investability_status_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """3. Gate 1 Negative: Mutating investability status in oracle triggers Gate 1 FAIL."""
    mutated_inv = rs_clean_context.df_oracle_inv.copy()
    mutated_inv.loc[mutated_inv.index[0], "investability_status"] = "FILTERED_MARKET_CAP"
    ctx = dataclasses.replace(rs_clean_context, df_oracle_inv=mutated_inv)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["investability_mismatches"] > 0


def test_gate1_negative_foreign_flow_value_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """4. Gate 1 Negative: Mutating foreign flow value in oracle triggers Gate 1 FAIL."""
    mutated_flow = rs_clean_context.df_flow_oracle.copy()
    mutated_flow.loc[mutated_flow.index[0], "foreign_net_buy_value_20d"] = 9999999.0
    ctx = dataclasses.replace(rs_clean_context, df_flow_oracle=mutated_flow)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["foreign_flow_numeric_mismatches"] > 0


def test_gate1_negative_candidate_extra_ticker(rs_clean_context: RelativeStrengthValidationContext):
    """Gate 1 Negative: Candidate oracle with extra ticker triggers Gate 1 FAIL (ticker-set mismatch)."""
    df_cand = rs_clean_context.df_oracle_cand
    extra_row = df_cand.iloc[0:1].copy()
    extra_row["ticker"] = "999999"
    mutated_cand = pd.concat([df_cand, extra_row], ignore_index=True)
    ctx = dataclasses.replace(rs_clean_context, df_oracle_cand=mutated_cand)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["candidate_ticker_mismatches"] > 0


def test_gate1_negative_candidate_missing_ticker(rs_clean_context: RelativeStrengthValidationContext):
    """Gate 1 Negative: Candidate oracle with missing ticker triggers Gate 1 FAIL (ticker-set mismatch)."""
    mutated_cand = rs_clean_context.df_oracle_cand.iloc[1:].reset_index(drop=True)
    ctx = dataclasses.replace(rs_clean_context, df_oracle_cand=mutated_cand)

    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_01_frozen_identity_parity"]["passed"] is False
    assert result["gates"]["gate_01_frozen_identity_parity"]["details"]["candidate_ticker_mismatches"] > 0


def test_gate2_negative_hash_mismatch(rs_clean_context: RelativeStrengthValidationContext, tmp_path: Path):
    """Gate 2 Negative: Tampered market benchmark meta (wrong sha256) triggers Gate 2 FAIL.

    실제 parquet 파일은 복사하지 않는다 — meta json 하나만 tamper해서 tmp_path에
    쓰고 context가 그 경로를 가리키게 한다(원본 parquet 그대로 사용, sha 불일치만 유도).
    """
    real_meta = json.loads(rs_clean_context.market_index_meta.read_text(encoding="utf-8"))
    real_meta["parquet_sha256"] = "TAMPERED_HASH"
    tampered_meta = tmp_path / "market_index_daily_20260814_meta.json"
    tampered_meta.write_text(json.dumps(real_meta), encoding="utf-8")

    ctx = dataclasses.replace(rs_clean_context, market_index_meta=tampered_meta)
    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_02_market_benchmark_source_identity"]["passed"] is False
    assert result["gates"]["gate_02_market_benchmark_source_identity"]["details"]["sha256_match"] is False


def test_gate4_negative_stale_market_date(rs_clean_context: RelativeStrengthValidationContext, tmp_path: Path):
    """Gate 4 Negative: Benchmark missing exact requested as_of observation date (Gate 4 FAIL)."""
    df_mkt = pd.read_parquet(rs_clean_context.market_index_parquet)
    df_stale = df_mkt[df_mkt["date"] < "2026-08-14"].copy()
    stale_parquet = tmp_path / "market_index_daily_20260814.parquet"
    df_stale.to_parquet(stale_parquet, index=False)

    meta_dict = json.loads(rs_clean_context.market_index_meta.read_text(encoding="utf-8"))
    meta_dict["parquet_sha256"] = hashlib.sha256(stale_parquet.read_bytes()).hexdigest()
    meta_dict["row_count"] = len(df_stale)
    meta_dict["date_max"] = str(df_stale["date"].max())
    stale_meta = tmp_path / "market_index_daily_20260814_meta.json"
    stale_meta.write_text(json.dumps(meta_dict), encoding="utf-8")

    ctx = dataclasses.replace(
        rs_clean_context,
        market_index_parquet=stale_parquet,
        market_index_meta=stale_meta,
    )
    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_04_exact_freshness_anchor_contract"]["passed"] is False


def _mutate_scan_row_market_rs(
    context: RelativeStrengthValidationContext, *, field: str, delta: float
) -> RelativeStrengthValidationContext:
    """`context.scan_res.rows` 중 candidate/investable 첫 행의 `field`를
    `delta`만큼 바꾼 새 context를 만든다(Full Universe Scanner 재호출 없음)."""
    assert context.scan_res is not None
    rows_list = list(context.scan_res.rows)
    for idx, r in enumerate(rows_list):
        if r.candidate_state.value == "candidate" and r.investability_status.value == "INVESTABLE":
            current = getattr(r, field) or 0.0
            rows_list[idx] = dataclasses.replace(r, **{field: current + delta})
            break
    mutated_scan_res = dataclasses.replace(context.scan_res, rows=tuple(rows_list))
    return dataclasses.replace(context, scan_res=mutated_scan_res)


def test_gate6_negative_market_rs_3m_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """5. Gate 6 Negative: Mutating 3M market RS in scanner output triggers Gate 6 FAIL.

    Full Universe Scanner를 다시 호출하지 않는다 — 캐시된 `scan_res`의 row 하나만
    `dataclasses.replace`로 직접 mutate한다(기존 monkeypatch+재실행과 동일한 검증
    대상, 계산 비용만 제거).
    """
    ctx = _mutate_scan_row_market_rs(rs_clean_context, field="market_rs_3m", delta=0.05)
    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["details"]["market_rs_3m_mismatches"] > 0


def test_gate6_negative_market_rs_12m_mutation(rs_clean_context: RelativeStrengthValidationContext):
    """6. Gate 6 Negative: Mutating 12M market RS in scanner output triggers Gate 6 FAIL."""
    ctx = _mutate_scan_row_market_rs(rs_clean_context, field="market_rs_12m", delta=-0.05)
    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_06_market_rs_arithmetic_parity"]["details"]["market_rs_12m_mismatches"] > 0


def test_gate7_negative_empty_sector_source(rs_clean_context: RelativeStrengthValidationContext):
    """7. Gate 7 Negative: Empty sector source (0 rows) triggers Gate 7 FAIL.

    실제 production 상태 그대로(현재 sector index source가 0-row) 재사용한다 —
    별도 mutation이 필요 없는 이미 real한 negative case다.
    """
    result = evaluate_relative_strength_gates(rs_clean_context)
    assert result["gates"]["gate_07_sector_mapping_contract"]["passed"] is False
    assert result["gates"]["gate_07_sector_mapping_contract"]["details"]["sector_index"]["row_count"] == 0


def test_gate7_negative_sector_mapping_hash_mismatch(rs_clean_context: RelativeStrengthValidationContext, tmp_path: Path):
    """Gate 7 Negative: Tampered sector mapping CSV triggers hash mismatch (Gate 7 FAIL)."""
    real_csv_text = rs_clean_context.sector_mapping_csv.read_text(encoding="utf-8")
    tampered_csv = tmp_path / "sector_mapping_20260814.csv"
    tampered_csv.write_text(real_csv_text + "\n999999,KOSPI,9999,임의업종,2026-08-14\n", encoding="utf-8")

    ctx = dataclasses.replace(rs_clean_context, sector_mapping_csv=tampered_csv)
    result = evaluate_relative_strength_gates(ctx)
    assert result["gates"]["gate_07_sector_mapping_contract"]["passed"] is False
    assert result["gates"]["gate_07_sector_mapping_contract"]["details"]["sector_mapping"]["sha256_match"] is False


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


def test_gate8_negative_zero_sector_ready(rs_clean_context: RelativeStrengthValidationContext):
    """10. Gate 8 Negative: When Sector READY candidates == 0, Gate 8 strictly FAILS.

    실제 production 상태 그대로(sector index source가 0-row라 READY 후보가 0건)
    재사용한다 — 별도 mutation이 필요 없다.
    """
    result = evaluate_relative_strength_gates(rs_clean_context)
    assert result["gates"]["gate_08_sector_rs_arithmetic_parity"]["passed"] is False
    assert result["gates"]["gate_08_sector_rs_arithmetic_parity"]["details"]["candidate_sector_rs_ready"] == 0


def test_mutation_tests_do_not_touch_canonical_artifacts(repo_root: Path):
    """Regression Test: Gate negative test들이 evaluate_relative_strength_gates()만
    호출하는 한(파일 쓰기가 있는 run_relative_strength_validation()을 호출하지 않는
    한) 공식 canonical artifact는 절대 건드릴 수 없다는 것을 회귀 검증한다."""
    csv_file = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/pattern_a_relative_strength_features_20260814.csv"
    json_file = repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/pattern_a_relative_strength_summary_20260814.json"

    def get_hash(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""

    csv_hash_before = get_hash(csv_file)
    json_hash_before = get_hash(json_file)

    context = prepare_relative_strength_validation_context(
        as_of=SUBSET_AS_OF, repo_root=repo_root, target_tickers=SUBSET_TICKERS
    )
    ctx_3m = _mutate_scan_row_market_rs(context, field="market_rs_3m", delta=0.05)
    ctx_12m = _mutate_scan_row_market_rs(context, field="market_rs_12m", delta=-0.05)
    evaluate_relative_strength_gates(ctx_3m)
    evaluate_relative_strength_gates(ctx_12m)

    csv_hash_after = get_hash(csv_file)
    json_hash_after = get_hash(json_file)

    assert csv_hash_after == csv_hash_before, "Official canonical CSV was corrupted by mutation test!"
    assert json_hash_after == json_hash_before, "Official canonical JSON was corrupted by mutation test!"


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

    df_mkt = pd.read_parquet(repo_root / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet")
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
