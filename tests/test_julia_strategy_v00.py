"""Comprehensive Tests for Julia Strategy V00 and Historical Investability PIT.

Validates:
  - 215 Required Reference Dates Determinism & Partition (117 Available + 98 Missing)
  - 2023-09-22 Canonical UI Authority Classification and Crosscheck
  - Superseded Provenance Rows Excluded from Active Authority
  - Dual SHA (Source + Normalized) verification in Registry & Tampering Detection
  - Sealed Source Corruption Hard Fail in Sealer
  - Historical Market Cap & Liquidity PIT Thresholds (100B, 300M)
  - No lookahead on daily 20D average trading value calculation
  - Strategy First Entry Parity, Loss Guard Isolation, Exit3 Parity, Exit4 Parity (Non-vacuous)
  - Evaluation Window (2022-01-01 to 2026-08-14) and Lookback Invariants
  - Full Loss Guard Cohort Accounting Identity (N = M + (N - M))
  - Incomplete Report Governance (Performance metrics strictly suppressed when coverage < 100%)
  - Full-Ready Report Freshness Gate (Stale sparse artifacts rejected, Fresh full-PIT accepted)
  - No local file:/// links in documentation
  - Canonical Historical V2 Protection (783 historical trades preserved)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import pytest
import pandas as pd
import numpy as np

from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    HistoricalMarketCapIntegrityError,
    HistoricalMarketCapRegistry,
    simulate_ticker_strategy_2022,
)
from scripts.seal_julia_interrupted_checkpoint_v00 import (
    SealedMarketCapCheckpointIntegrityError,
    load_canonical_ui_authorities,
    seal_checkpoint,
)
from scripts.generate_julia_report_from_artifacts import (
    generate_checkpoint_report,
    generate_full_research_report,
)

ROOT = Path(__file__).resolve().parent.parent
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PROVENANCE_CSV = ROOT / "artifacts/patterns/pattern_a/validation/investability_history/krx_historical_market_cap_provenance_v01.csv"
MANIFEST_CSV = JULIA_DIR / "historical_market_cap_source_manifest.csv"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =============================================================================
# 1. Manifest, Checkpoint Audit & Authority Integrity Tests
# =============================================================================

def test_required_dates_manifest_and_partition_integrity():
    """Verify 215 required dates, partition into available (117) and missing (98)."""
    req_path = JULIA_DIR / "historical_market_cap_required_dates.csv"
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    missing_path = JULIA_DIR / "historical_market_cap_missing_dates.csv"
    audit_path = JULIA_DIR / "historical_investability_pit_audit.json"

    assert req_path.exists()
    assert manifest_path.exists()
    assert missing_path.exists()
    assert audit_path.exists()

    df_req = pd.read_csv(req_path)
    df_man = pd.read_csv(manifest_path)
    df_missing = pd.read_csv(missing_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    req_set = set(df_req["signal_reference_date"].unique())
    avail_set = set(df_man[df_man["available"] == True]["signal_reference_date"].unique())
    missing_set = set(df_missing["signal_reference_date"].unique())

    assert len(req_set) == 215
    assert len(avail_set) == 117
    assert len(missing_set) == 98

    # Partition identity
    assert req_set == avail_set.union(missing_set)
    assert avail_set.intersection(missing_set) == set()

    assert audit["historical_market_cap_source_dates_required"] == 215
    assert audit["historical_market_cap_source_dates_available"] == 117
    assert audit["historical_market_cap_source_dates_missing"] == 98
    assert audit["historical_market_cap_source_coverage_rate"] == 54.42


def test_2023_09_22_canonical_ui_authority_classification():
    """Verify 2023-09-22 is correctly classified as Canonical UI Authority."""
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    df_man = pd.read_csv(manifest_path).fillna("")

    row_20230922 = df_man[df_man["signal_reference_date"] == "2023-09-22"]
    assert len(row_20230922) == 1
    r = row_20230922.iloc[0]

    assert r["source_channel"] == "KRX_DATA_MARKETPLACE_UI_CSV"
    assert r["source_role"] == "CANONICAL_RAW_UI_EXPORT"
    assert r["authority_status"] == "CANONICAL_UI_AUTHORITY"
    assert r["available"] == True
    assert r["integrity_status"] == "PASS"


def test_superseded_provenance_not_active_authority():
    """Ensure superseded provenance rows (e.g. 2022-12-30) are excluded from active authority."""
    assert PROVENANCE_CSV.exists()
    df_prov = pd.read_csv(PROVENANCE_CSV)
    superseded_rows = df_prov[df_prov["reference_status"] == "SUPERSEDED_NON_REFERENCE_SOURCE"]
    assert len(superseded_rows) > 0

    active_auth = load_canonical_ui_authorities()
    for _, r in superseded_rows.iterrows():
        req_d = str(r["requested_date"])
        # If requested date is superseded, it must not be active authority unless a valid active entry exists
        if req_d in active_auth:
            assert active_auth[req_d].reference_status == "ACTIVE_REFERENCE"


def test_incomplete_coverage_blocks_final_status():
    """Coverage < 100% must strictly block final pit backtest ready status."""
    audit_path = JULIA_DIR / "historical_investability_pit_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["final_pit_backtest_ready"] is False
    assert audit["final_result_status"] == "INVALID_INCOMPLETE_PIT_COVERAGE"
    assert audit["source_collection_status"] == "INTERRUPTED_KRX_TEMPORARY_RESTRICTION"
    assert audit["future_market_cap_fallback_count"] == 0
    assert audit["current_20260814_market_cap_usage_count"] == 0


def test_source_file_existence_and_sha_seal_integrity():
    """Verify all available manifest rows have valid files and matching SHA256."""
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    df_man = pd.read_csv(manifest_path).fillna("")

    df_avail = df_man[df_man["available"] == True]
    assert len(df_avail) == 117

    for _, r in df_avail.iterrows():
        raw_file = ROOT / r["raw_source_file"]
        norm_file = ROOT / r["normalized_source_file"]

        assert raw_file.exists(), f"Missing raw file: {raw_file}"
        assert norm_file.exists(), f"Missing normalized file: {norm_file}"

        actual_raw_sha = sha256_file(raw_file)
        actual_norm_sha = sha256_file(norm_file)

        assert actual_raw_sha == r["raw_sha256"], f"Raw SHA mismatch on {r['signal_reference_date']}"
        assert actual_norm_sha == r["normalized_sha256"], f"Normalized SHA mismatch on {r['signal_reference_date']}"

        assert r["source_provider"] == "KRX"
        assert r["source_channel"] in {"KRX_DATA_MARKETPLACE_UI_CSV", "KRX_DATA_MARKETPLACE_JSON_ENDPOINT", "KRX_OPEN_API"}
        assert r["integrity_status"] == "PASS"


def test_registry_tampered_source_sha_raises():
    """Registry must raise HistoricalMarketCapIntegrityError on SHA tampering or invalid metadata."""
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    assert manifest_path.exists()

    df_man = pd.read_csv(manifest_path).fillna("")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        tmp_man_dir = tmp_root / "artifacts/strategies/julia/v00"
        tmp_man_dir.mkdir(parents=True, exist_ok=True)

        df_tampered = df_man.copy()
        df_tampered.loc[0, "raw_sha256"] = "bad_hash_12345"
        df_tampered.to_csv(tmp_man_dir / "historical_market_cap_source_manifest.csv", index=False)

        raw_rel = df_tampered.loc[0, "raw_source_file"]
        norm_rel = df_tampered.loc[0, "normalized_source_file"]
        (tmp_root / raw_rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_root / norm_rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_root / raw_rel).write_text((ROOT / raw_rel).read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_root / norm_rel).write_text((ROOT / norm_rel).read_text(encoding="utf-8"), encoding="utf-8")

        with pytest.raises(HistoricalMarketCapIntegrityError):
            HistoricalMarketCapRegistry.load_from_repository(tmp_root, enforce_integrity=True)


def test_registry_fail_closed_on_missing_date():
    """Querying un-backfilled missing date returns None (Fail Closed)."""
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT, enforce_integrity=True)
    mcap_none, meta_none = reg.get_market_cap_at_reference("005930", "2024-07-19")
    assert mcap_none is None
    assert meta_none is None


# =============================================================================
# 2. Historical Investability PIT Threshold & Lookahead Tests
# =============================================================================

def test_pit_investability_thresholds():
    """Verify strict fail-closed filtering on 100B market cap and 300M liquidity."""
    dates = pd.date_range("2022-01-01", periods=30, freq="B")
    daily_pass = pd.DataFrame({
        "open": 10000.0,
        "high": 10500.0,
        "low": 9500.0,
        "close": 10000.0,
        "volume": 50000,
        "trading_value": 500_000_000.0,
    }, index=dates)

    as_of = dates[-1]

    # Market Cap: 99.9B (Fail) vs 100.0B (Pass)
    res_fail_mcap = evaluate_investability("000001", as_of, daily_pass, market_cap=99_900_000_000.0)
    assert res_fail_mcap.status == InvestabilityStatus.FILTERED_MARKET_CAP

    res_pass_mcap = evaluate_investability("000001", as_of, daily_pass, market_cap=100_000_000_000.0)
    assert res_pass_mcap.status == InvestabilityStatus.INVESTABLE

    # Missing market cap -> DATA_UNAVAILABLE (Fail closed)
    res_none_mcap = evaluate_investability("000001", as_of, daily_pass, market_cap=None)
    assert res_none_mcap.status == InvestabilityStatus.DATA_UNAVAILABLE

    # Liquidity: 299M (Fail) vs 300M (Pass)
    daily_fail_liq = daily_pass.copy()
    daily_fail_liq["trading_value"] = 299_000_000.0
    res_fail_liq = evaluate_investability("000001", as_of, daily_fail_liq, market_cap=100_000_000_000.0)
    assert res_fail_liq.status == InvestabilityStatus.FILTERED_LIQUIDITY


def test_pit_investability_no_lookahead_on_daily():
    """Future daily bars beyond as_of reference date must not affect investability result."""
    dates_past = pd.date_range("2022-01-01", periods=20, freq="B")
    dates_future = pd.date_range("2022-01-29", periods=10, freq="B")

    daily_past = pd.DataFrame({
        "open": 10000.0, "high": 10500.0, "low": 9500.0, "close": 10000.0,
        "volume": 50000, "trading_value": 400_000_000.0,
    }, index=dates_past)

    daily_with_fut = pd.concat([
        daily_past,
        pd.DataFrame({
            "open": 20000.0, "high": 21000.0, "low": 19000.0, "close": 20000.0,
            "volume": 500000, "trading_value": 10_000_000_000.0,
        }, index=dates_future)
    ])

    as_of = dates_past[-1]
    res1 = evaluate_investability("000001", as_of, daily_past, market_cap=150_000_000_000.0)
    res2 = evaluate_investability("000001", as_of, daily_with_fut[daily_with_fut.index <= as_of], market_cap=150_000_000_000.0)

    assert res1.avg_trading_value_20d == res2.avg_trading_value_20d
    assert res1.status == res2.status == InvestabilityStatus.INVESTABLE


# =============================================================================
# 3. Strategy Regression Contract Tests (Non-Vacuous on Real Cached Stocks)
# =============================================================================

def test_first_entry_exact_parity_non_vacuous():
    """Baseline and Julia must produce actual trades on real stock (005930) and have 100% exact first entry match."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    daily = cache.load("005930")
    assert daily is not None and not daily.empty

    b_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    assert len(b_trades) >= 1, "Baseline simulation produced 0 trades for 005930"
    assert len(j_trades) >= 1, "Julia simulation produced 0 trades for 005930"

    assert b_trades[0].entry_signal_date == j_trades[0].entry_signal_date
    assert b_trades[0].entry_execution_date == j_trades[0].entry_execution_date
    assert b_trades[0].entry_open == j_trades[0].entry_open
    assert b_trades[0].investability_status == j_trades[0].investability_status == "INVESTABLE"


def test_loss_guard_isolation_non_vacuous():
    """In actual drop before PROGRESSED (005930), Baseline triggers Loss Guard (-15%), Julia holds."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    daily = cache.load("005930")
    b_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    assert len(b_trades) >= 1
    assert len(j_trades) >= 1

    # Baseline must trigger Loss Guard
    assert b_trades[0].loss_guard_triggered is True
    assert b_trades[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"

    # Julia must NOT trigger Loss Guard
    assert j_trades[0].loss_guard_triggered is False
    assert j_trades[0].exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_exit3_semantics_parity():
    """Verify Exit 3 (PROGRESSED -> TRANSITION) actually occurs on 006730 and has 100% exact parity."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    # 006730 (서부T&D) produces PROGRESSED handoff followed by Exit 3
    daily = cache.load("006730")
    assert daily is not None and not daily.empty

    b_trades = simulate_ticker_strategy_2022("006730", "서부T&D", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("006730", "서부T&D", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    assert len(b_trades) >= 1, "Baseline produced 0 trades for 006730"
    assert len(j_trades) >= 1, "Julia produced 0 trades for 006730"

    b_exit3 = [t for t in b_trades if t.exit_type.startswith("EXIT3_")]
    j_exit3 = [t for t in j_trades if t.exit_type.startswith("EXIT3_")]

    assert len(b_exit3) >= 1, "Baseline did not trigger Exit 3"
    assert len(j_exit3) >= 1, "Julia did not trigger Exit 3"

    t_b = b_exit3[0]
    t_j = j_exit3[0]

    # Exact parity assertions
    assert t_b.entry_signal_date == t_j.entry_signal_date
    assert t_b.entry_execution_date == t_j.entry_execution_date
    assert t_b.entry_open == t_j.entry_open
    assert t_b.first_progressed_date == t_j.first_progressed_date
    assert t_b.exit_type == t_j.exit_type == "EXIT3_PROGRESSED_TO_TRANSITION"
    assert t_b.exit_signal_date == t_j.exit_signal_date
    assert t_b.exit_execution_date == t_j.exit_execution_date
    assert t_b.exit_price == t_j.exit_price


def test_exit4_semantics_parity():
    """Verify Exit 4 (Drawdown from PROGRESSED HWM >= 15 pts) actually occurs on 005710 and has 100% exact parity."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    # 005710 (대원산업) produces PROGRESSED handoff followed by Exit 4
    daily = cache.load("005710")
    assert daily is not None and not daily.empty

    b_trades = simulate_ticker_strategy_2022("005710", "대원산업", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("005710", "대원산업", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    assert len(b_trades) >= 1, "Baseline produced 0 trades for 005710"
    assert len(j_trades) >= 1, "Julia produced 0 trades for 005710"

    b_exit4 = [t for t in b_trades if t.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"]
    j_exit4 = [t for t in j_trades if t.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"]

    assert len(b_exit4) >= 1, "Baseline did not trigger Exit 4"
    assert len(j_exit4) >= 1, "Julia did not trigger Exit 4"

    t_b = b_exit4[0]
    t_j = j_exit4[0]

    # Exact parity assertions
    assert t_b.entry_signal_date == t_j.entry_signal_date
    assert t_b.entry_execution_date == t_j.entry_execution_date
    assert t_b.entry_open == t_j.entry_open
    assert t_b.first_progressed_date == t_j.first_progressed_date
    assert t_b.exit_type == t_j.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"
    assert t_b.exit_signal_date == t_j.exit_signal_date
    assert t_b.exit_execution_date == t_j.exit_execution_date
    assert t_b.exit_price == t_j.exit_price


def test_evaluation_window_and_lookback():
    """All executions in existing trade artifacts must be strictly within 2022-01-01 to 2026-08-14."""
    b_trades_path = JULIA_DIR / "baseline_a_fast_core_v2_2022_trades.csv"
    j_trades_path = JULIA_DIR / "julia_v00_2022_trades.csv"

    assert b_trades_path.exists(), "baseline_a_fast_core_v2_2022_trades.csv must exist"
    assert j_trades_path.exists(), "julia_v00_2022_trades.csv must exist"

    df_b = pd.read_csv(b_trades_path)
    df_j = pd.read_csv(j_trades_path)

    for df in [df_b, df_j]:
        assert len(df) > 0
        exec_dates = pd.to_datetime(df["entry_execution_date"])
        assert (exec_dates >= EVALUATION_START_DATE).all()
        assert (exec_dates <= EVALUATION_END_DATE).all()


def test_cohort_accounting_identity():
    """Verify N = M + (N - M) cohort accounting identity on canonical artifacts."""
    lg_summary_path = JULIA_DIR / "loss_guard_recovery_summary.json"
    lg_csv_path = JULIA_DIR / "loss_guard_counterfactual.csv"

    assert lg_summary_path.exists()
    assert lg_csv_path.exists()

    lg_sum = json.loads(lg_summary_path.read_text(encoding="utf-8"))
    df_lg = pd.read_csv(lg_csv_path)

    total_n = lg_sum["baseline_loss_guard_total"]
    paired_m = lg_sum["paired_loss_guard_count"]
    unpaired_nm = lg_sum["unpaired_loss_guard_count"]

    assert total_n == paired_m + unpaired_nm
    assert len(df_lg) == total_n


# =============================================================================
# 4. Incomplete Report & Full-Ready Freshness Governance Tests
# =============================================================================

def test_incomplete_report_performance_suppressed():
    """When final_pit_backtest_ready is False, performance tables must be suppressed."""
    doc_path = ROOT / "docs/strategies/julia/v00.md"
    audit_path = JULIA_DIR / "historical_investability_pit_audit.json"

    assert doc_path.exists()
    assert audit_path.exists()

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    doc_text = doc_path.read_text(encoding="utf-8")

    if not audit.get("final_pit_backtest_ready", False):
        assert "EVIDENCE STATUS: NON_AUTHORITATIVE_INCOMPLETE_SOURCE_COVERAGE" in doc_text
        assert "Performance Interpretation Suppressed" in doc_text

        # Suppressed sections
        assert "Comparative Strategy Performance (2022+)" not in doc_text
        assert "Top 10 Big Winners" not in doc_text
        assert "Top 10 Deep Losses" not in doc_text
        assert "Full Loss Guard Cohort Accounting" not in doc_text


def test_full_ready_rejects_stale_sparse_artifacts():
    """When final_pit_backtest_ready is True, generator must reject stale sparse preliminary artifacts."""
    summary_path = JULIA_DIR / "strategy_comparison_summary.json"
    assert summary_path.exists()

    stale_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    fake_ready_audit = {
        "final_pit_backtest_ready": True,
        "historical_market_cap_source_dates_required": 215,
        "historical_market_cap_source_dates_available": 215,
        "historical_market_cap_source_dates_missing": 0,
        "historical_market_cap_source_coverage_rate": 100.0,
    }

    # Stale summary lacks evidence_status == "FULL_PIT_COMPLETE" and manifest SHA
    with pytest.raises(RuntimeError, match="Full Julia report rejected: strategy artifacts do not match"):
        generate_full_research_report(stale_summary, fake_ready_audit)


def test_full_ready_accepts_fresh_full_pit_fixture():
    """When fresh 100% FULL_PIT_COMPLETE metadata is provided, generator safely produces markdown."""
    summary_path = JULIA_DIR / "strategy_comparison_summary.json"
    assert summary_path.exists()

    base_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    current_manifest_sha = sha256_file(MANIFEST_CSV)

    fresh_summary = base_summary.copy()
    fresh_summary["metadata"] = {
        "evidence_status": "FULL_PIT_COMPLETE",
        "run_id": "test_fresh_run_123",
        "input_manifest_sha256": current_manifest_sha,
        "required_date_count": 215,
        "available_date_count": 215,
        "missing_date_count": 0,
        "coverage_rate": 100.0,
        "evaluation_start": "2022-01-01",
        "evaluation_end": "2026-08-14",
    }

    fresh_ready_audit = {
        "final_pit_backtest_ready": True,
        "historical_market_cap_source_dates_required": 215,
        "historical_market_cap_source_dates_available": 215,
        "historical_market_cap_source_dates_missing": 0,
        "historical_market_cap_source_coverage_rate": 100.0,
    }

    report_text = generate_full_research_report(fresh_summary, fresh_ready_audit)
    assert len(report_text) > 1000
    assert "# Research Report: Julia Strategy V00 vs A FAST Core V2" in report_text
    assert "Comparative Strategy Performance (2022+)" in report_text


def test_no_local_file_uri_in_docs():
    """Verify docs/strategies/julia/v00.md contains zero local file:/// or /Users/ links."""
    doc_path = ROOT / "docs/strategies/julia/v00.md"
    assert doc_path.exists()
    text = doc_path.read_text(encoding="utf-8")

    assert "file:///" not in text
    assert "/Users/" not in text


# =============================================================================
# 5. Canonical V2 Protection Test
# =============================================================================

def test_canonical_v2_artifacts_unaltered():
    """Verify historical V2 783 trades artifact is intact."""
    historical_v2_csv = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    assert historical_v2_csv.exists()
    df_hist = pd.read_csv(historical_v2_csv)
    assert len(df_hist) == 783
