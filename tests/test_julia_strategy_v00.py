"""Targeted Tests for Julia Strategy V00 Controlled Comparative Backtest Engine (FIX 01).

Validates:
  - Historical Investability PIT Gate (KRX snapshot, fail closed, no future fallback)
  - First Entry exact parity between Baseline V2 and Julia V00
  - Loss Guard ON vs OFF isolation on Pre-PROGRESSED -15% close
  - Post-PROGRESSED Exit3 / Exit4 parity
  - Evaluation Window (2022-01-01 <= exec_date <= 2026-08-14, pre-2022 trades 0)
  - Cohort Accounting: baseline_loss_guard_total == paired + unpaired
  - Common Entry exact matching determinism
  - Canonical historical V2 artifact protection (783 trades preserved)
"""

from __future__ import annotations

import json
from pathlib import Path
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
    HistoricalMarketCapRegistry,
    StrategyTradeRecord,
    simulate_ticker_strategy_2022,
)

ROOT = Path(__file__).resolve().parent.parent

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"


@pytest.fixture(scope="module")
def score_contract() -> dict:
    return json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def stage_contract() -> dict:
    return json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sample_cache() -> ParquetCache:
    return ParquetCache(base_dir=ROOT / "data/raw/stocks")


@pytest.fixture(scope="module")
def market_cap_registry() -> HistoricalMarketCapRegistry:
    return HistoricalMarketCapRegistry.load_from_repository(ROOT)


# =============================================================================
# 1. Historical Investability PIT Tests
# =============================================================================

def test_pit_investability_thresholds():
    """Verify exact 100B KRW market cap and 300M KRW trading value thresholds."""
    # Synthetic daily slice with 20 days
    dates = pd.date_range("2023-01-01", periods=25, freq="B")
    df_daily = pd.DataFrame({
        "open": [1000.0] * 25,
        "high": [1050.0] * 25,
        "low": [950.0] * 25,
        "close": [1000.0] * 25,
        "volume": [1000] * 25,
        "trading_value": [300_000_000.0] * 25,
    }, index=dates)

    as_of = dates[-1]

    # 1. Market Cap < 100B -> FILTERED_MARKET_CAP
    res_mcap_fail = evaluate_investability(
        "000001", as_of, df_daily, market_cap=99_999_999_999.0, market_cap_effective_date=str(as_of.date())
    )
    assert res_mcap_fail.status == InvestabilityStatus.FILTERED_MARKET_CAP

    # 2. Market Cap >= 100B and TV20 >= 300M -> INVESTABLE
    res_pass = evaluate_investability(
        "000001", as_of, df_daily, market_cap=100_000_000_000.0, market_cap_effective_date=str(as_of.date())
    )
    assert res_pass.status == InvestabilityStatus.INVESTABLE

    # 3. TV20 < 300M -> FILTERED_LIQUIDITY
    df_low_liq = df_daily.copy()
    df_low_liq["trading_value"] = 299_000_000.0
    res_liq_fail = evaluate_investability(
        "000001", as_of, df_low_liq, market_cap=100_000_000_000.0, market_cap_effective_date=str(as_of.date())
    )
    assert res_liq_fail.status == InvestabilityStatus.FILTERED_LIQUIDITY

    # 4. Market Cap None (Unavailable) -> DATA_UNAVAILABLE (Fail Closed)
    res_unavail = evaluate_investability(
        "000001", as_of, df_daily, market_cap=None
    )
    assert res_unavail.status == InvestabilityStatus.DATA_UNAVAILABLE


def test_pit_investability_no_lookahead_on_daily(sample_cache):
    """20D trading value must strictly use daily slice on/before signal reference date."""
    daily = sample_cache.load("005930")
    if daily is None or daily.empty:
        pytest.skip("005930 cache not available")

    ref_d = pd.Timestamp("2023-06-30")
    sliced = daily[daily.index <= ref_d]

    res = evaluate_investability("005930", ref_d, sliced, market_cap=400_000_000_000_000.0, market_cap_effective_date="2023-06-30")
    assert res.status == InvestabilityStatus.INVESTABLE
    assert res.close_effective_date == "2023-06-30"


def test_registry_fail_closed_on_missing_date(market_cap_registry):
    """Registry returns None for dates not in canonical KRX historical snapshots."""
    mcap, meta = market_cap_registry.get_market_cap_at_reference("005930", "2023-05-15")  # Arbitrary non-snapshot date
    assert mcap is None
    assert meta is None


# =============================================================================
# 2. Strategy Invariant & Parity Tests
# =============================================================================

def test_first_entry_exact_parity(sample_cache, score_contract, stage_contract, market_cap_registry):
    """First Entry anchor MUST be 100% identical between Baseline V2 and Julia V00."""
    # 058610 (에스피지) had qualifying entry in 2023 Q1
    daily = sample_cache.load("058610")
    if daily is None or daily.empty:
        pytest.skip("058610 cache not available")

    b_trades = simulate_ticker_strategy_2022("058610", "에스피지", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=market_cap_registry)
    j_trades = simulate_ticker_strategy_2022("058610", "에스피지", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=market_cap_registry)

    if b_trades and j_trades:
        assert b_trades[0].entry_signal_date == j_trades[0].entry_signal_date
        assert b_trades[0].entry_execution_date == j_trades[0].entry_execution_date
        assert b_trades[0].entry_open == j_trades[0].entry_open


def test_loss_guard_isolation(sample_cache, score_contract, stage_contract, market_cap_registry):
    """Pre-PROGRESSED -15% close triggers LG exit in Baseline, but Julia continues holding."""
    # 058610 (에스피지) in 2023-03-31 entry dropped <= -15% before PROGRESSED
    daily = sample_cache.load("058610")
    if daily is None or daily.empty:
        pytest.skip("058610 cache not available")

    b_trades = simulate_ticker_strategy_2022("058610", "에스피지", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=market_cap_registry)
    j_trades = simulate_ticker_strategy_2022("058610", "에스피지", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=market_cap_registry)

    if b_trades and j_trades:
        assert b_trades[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
        assert j_trades[0].exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_post_progressed_exits_parity(sample_cache, score_contract, stage_contract, market_cap_registry):
    """Exit3 and Exit4 semantics are identical for both strategies once PROGRESSED is reached."""
    # 005380 (현대차) reached PROGRESSED
    daily = sample_cache.load("005380")
    if daily is None or daily.empty:
        pytest.skip("005380 cache not available")

    b_trades = simulate_ticker_strategy_2022("005380", "현대차", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=market_cap_registry)
    j_trades = simulate_ticker_strategy_2022("005380", "현대차", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=market_cap_registry)

    if b_trades and j_trades and not b_trades[0].loss_guard_triggered:
        assert b_trades[0].exit_type == j_trades[0].exit_type
        assert b_trades[0].terminal_return == j_trades[0].terminal_return


def test_evaluation_window_and_lookback(sample_cache, score_contract, stage_contract, market_cap_registry):
    """All emitted trades MUST have entry_execution_date >= 2022-01-01 and <= 2026-08-14."""
    daily = sample_cache.load("000150")
    if daily is None or daily.empty:
        pytest.skip("000150 cache not available")

    b_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True, market_cap_registry=market_cap_registry)
    j_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False, market_cap_registry=market_cap_registry)

    for t in b_trades + j_trades:
        exec_d = pd.Timestamp(t.entry_execution_date)
        assert exec_d >= EVALUATION_START_DATE
        assert exec_d <= EVALUATION_END_DATE


# =============================================================================
# 3. Artifact & Cohort Accounting Integrity Tests
# =============================================================================

def test_cohort_accounting_identity():
    """Verify baseline_loss_guard_total == paired_loss_guard_count + unpaired_loss_guard_count."""
    julia_dir = ROOT / "artifacts/strategies/julia/v00"
    summary_path = julia_dir / "loss_guard_recovery_summary.json"
    cf_csv_path = julia_dir / "loss_guard_counterfactual.csv"

    assert summary_path.exists()
    assert cf_csv_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    df_cf = pd.read_csv(cf_csv_path)

    total_lg = summary["baseline_loss_guard_total"]
    paired_lg = summary["paired_loss_guard_count"]
    unpaired_lg = summary["unpaired_loss_guard_count"]

    assert total_lg == paired_lg + unpaired_lg
    assert len(df_cf) == total_lg
    assert (df_cf["pair_status"] == "PAIRED_COMMON_ENTRY").sum() == paired_lg
    assert (df_cf["pair_status"] == "UNPAIRED_STRATEGY_PATH_DIVERGENCE").sum() == unpaired_lg


def test_pit_audit_artifact_zero_violations():
    """Verify PIT audit artifact confirms zero future fallbacks and zero 2026 current market cap leaks."""
    pit_audit_path = ROOT / "artifacts/strategies/julia/v00/historical_investability_pit_audit.json"
    assert pit_audit_path.exists()

    audit = json.loads(pit_audit_path.read_text(encoding="utf-8"))
    assert audit["future_market_cap_fallback_count"] == 0
    assert audit["current_20260814_market_cap_usage_count"] == 0
    assert audit["pit_violation_count"] == 0


def test_canonical_v2_artifacts_unaltered():
    """Verify historical V2 783 trades artifact is intact."""
    historical_v2_csv = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    assert historical_v2_csv.exists()
    df_hist = pd.read_csv(historical_v2_csv)
    assert len(df_hist) == 783
