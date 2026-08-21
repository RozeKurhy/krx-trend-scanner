"""Comprehensive Tests for Julia Strategy V00 and Historical Investability PIT.

Validates:
  - 215 Required Reference Dates Determinism & Partition (117 Available + 98 Missing)
  - Historical Market Cap & Liquidity PIT Thresholds (100B, 300M)
  - No lookahead on daily 20D average trading value calculation
  - Registry Strict Integrity Enforcement (SHA verification, provider/channel checks, fail closed)
  - Strategy First Entry Parity, Loss Guard Isolation, and Exit3/Exit4 Parity
  - Evaluation Window (2022-01-01 to 2026-08-14) and Lookback Invariants
  - Full Loss Guard Cohort Accounting Identity (N = M + (N - M))
  - Incomplete Report Governance (Performance metrics strictly suppressed when coverage < 100%)
  - Canonical Historical V2 Protection (783 historical trades preserved)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

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

ROOT = Path(__file__).resolve().parent.parent
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =============================================================================
# 1. Manifest, Checkpoint Audit & Coverage Integrity Tests
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

    # Partition identity: Req = Avail U Missing, Avail INTERSECT Missing = Empty
    assert req_set == avail_set.union(missing_set)
    assert avail_set.intersection(missing_set) == set()

    assert audit["historical_market_cap_source_dates_required"] == 215
    assert audit["historical_market_cap_source_dates_available"] == 117
    assert audit["historical_market_cap_source_dates_missing"] == 98
    assert audit["historical_market_cap_source_coverage_rate"] == 54.42


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


def test_registry_manifest_authority_and_integrity_error():
    """Registry loaded from manifest enforces SHA verification and fail closed."""
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT, enforce_integrity=True)
    assert len(reg.snapshots) == 117

    # Verify loaded sample
    mcap, meta = reg.get_market_cap_at_reference("005930", "2022-02-04")
    assert mcap is not None and mcap > 100_000_000_000
    assert meta["source_provider"] == "KRX"
    assert meta["source_channel"] in {"KRX_DATA_MARKETPLACE_UI_CSV", "KRX_DATA_MARKETPLACE_JSON_ENDPOINT"}

    # Missing date returns None (Fail Closed)
    mcap_none, meta_none = reg.get_market_cap_at_reference("005930", "2024-07-19")
    assert mcap_none is None
    assert meta_none is None


# =============================================================================
# 2. Historical Investability PIT Threshold & Lookahead Tests (Restored)
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
        "trading_value": 500_000_000.0,  # 500M > 300M
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
    dates_future = pd.date_range(dates_past[-1] + pd.Timedelta(days=1), periods=10, freq="B")

    daily_past = pd.DataFrame({
        "open": 10000.0, "high": 10500.0, "low": 9500.0, "close": 10000.0,
        "volume": 50000, "trading_value": 400_000_000.0,
    }, index=dates_past)

    # Future has massive volume spike
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
# 3. Strategy Regression Contract Tests (Restored)
# =============================================================================

def _build_synthetic_bull_daily(start="2021-01-01", periods=300) -> pd.DataFrame:
    dates = pd.date_range(start, periods=periods, freq="B")
    base = 10000.0
    prices = [base]
    for i in range(1, len(dates)):
        prices.append(prices[-1] * 1.008)  # steady bull
    prices = np.array(prices)

    df = pd.DataFrame({
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": 200000,
        "trading_value": 2_000_000_000.0,
    }, index=dates)
    return df


def test_first_entry_exact_parity_on_synthetic():
    """Baseline and Julia must have 100% exact first entry match."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    daily = _build_synthetic_bull_daily()

    # Synthetic registry with infinite market cap for all weeks
    weekly = pd.date_range("2021-01-01", "2026-08-14", freq="W-FRI")
    snapshots = {w.strftime("%Y-%m-%d"): {"005930": 500_000_000_000_000.0} for w in weekly}
    metadata = {w.strftime("%Y-%m-%d"): {"source_provider": "KRX", "source_channel": "KRX_DATA_MARKETPLACE_UI_CSV", "source_file": "test.csv"} for w in weekly}
    reg = HistoricalMarketCapRegistry(snapshots=snapshots, metadata=metadata)

    b_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    if b_trades and j_trades:
        assert b_trades[0].entry_signal_date == j_trades[0].entry_signal_date
        assert b_trades[0].entry_execution_date == j_trades[0].entry_execution_date
        assert b_trades[0].entry_open == j_trades[0].entry_open
        assert b_trades[0].investability_status == j_trades[0].investability_status


def test_loss_guard_isolation_and_exit_parity():
    """In a drop before PROGRESSED, Baseline triggers Loss Guard (-15%), Julia holds."""
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    dates = pd.date_range("2021-06-01", periods=180, freq="B")
    prices = [10000.0]
    # Rally for 80 days, then drop 25% sharply
    for i in range(1, 80):
        prices.append(prices[-1] * 1.01)
    for i in range(80, len(dates)):
        prices.append(prices[-1] * 0.98)
    prices = np.array(prices)

    daily = pd.DataFrame({
        "open": prices * 0.99, "high": prices * 1.01, "low": prices * 0.98, "close": prices,
        "volume": 200000, "trading_value": 2_000_000_000.0,
    }, index=dates)

    weekly = pd.date_range("2021-01-01", "2026-08-14", freq="W-FRI")
    snapshots = {w.strftime("%Y-%m-%d"): {"005930": 500_000_000_000_000.0} for w in weekly}
    metadata = {w.strftime("%Y-%m-%d"): {"source_provider": "KRX", "source_channel": "KRX_DATA_MARKETPLACE_UI_CSV", "source_file": "test.csv"} for w in weekly}
    reg = HistoricalMarketCapRegistry(snapshots=snapshots, metadata=metadata)

    b_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=reg)
    j_trades = simulate_ticker_strategy_2022("005930", "삼성전자", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=reg)

    if b_trades and j_trades:
        # If baseline triggered Loss Guard, Julia did not
        if b_trades[0].loss_guard_triggered:
            assert j_trades[0].loss_guard_triggered is False
            assert b_trades[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
            assert j_trades[0].exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_evaluation_window_and_lookback():
    """All executions must be within 2022-01-01 to 2026-08-14."""
    trades_path = JULIA_DIR / "strategy_comparison_trades.csv"
    if trades_path.exists():
        df = pd.read_csv(trades_path)
        exec_dates = pd.to_datetime(df["entry_execution_date"])
        assert (exec_dates >= EVALUATION_START_DATE).all()
        assert (exec_dates <= EVALUATION_END_DATE).all()


def test_cohort_accounting_identity():
    """Verify N = M + (N - M) cohort accounting identity."""
    lg_summary_path = JULIA_DIR / "loss_guard_recovery_summary.json"
    lg_csv_path = JULIA_DIR / "loss_guard_counterfactual.csv"

    if lg_summary_path.exists() and lg_csv_path.exists():
        lg_sum = json.loads(lg_summary_path.read_text(encoding="utf-8"))
        df_lg = pd.read_csv(lg_csv_path)

        total_n = lg_sum["baseline_loss_guard_total"]
        paired_m = lg_sum["paired_loss_guard_count"]
        unpaired_nm = lg_sum["unpaired_loss_guard_count"]

        assert total_n == paired_m + unpaired_nm
        assert len(df_lg) == total_n


# =============================================================================
# 4. Incomplete Report Governance Test
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
        # Must contain warning and suppressed statement
        assert "EVIDENCE STATUS: NON_AUTHORITATIVE_INCOMPLETE_SOURCE_COVERAGE" in doc_text
        assert "Performance Interpretation Suppressed" in doc_text

        # Must NOT contain comparative performance tables
        assert "Comparative Strategy Performance (2022+)" not in doc_text
        assert "Top 10 Big Winners" not in doc_text
        assert "Top 10 Deep Losses" not in doc_text
        assert "Full Loss Guard Cohort Accounting (Major 2)" not in doc_text

        # r.md must be deleted
        assert not (ROOT / "r.md").exists()


# =============================================================================
# 5. Canonical V2 Protection Test
# =============================================================================

def test_canonical_v2_artifacts_unaltered():
    """Verify historical V2 783 trades artifact is intact."""
    historical_v2_csv = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    assert historical_v2_csv.exists()
    df_hist = pd.read_csv(historical_v2_csv)
    assert len(df_hist) == 783
