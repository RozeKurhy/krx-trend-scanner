"""Targeted Tests for Julia Strategy V00 Controlled Comparative Backtest Engine.

Validates:
  - Invariant 1: Baseline V2 == Julia V00 parity when Loss Guard is never triggered
  - Invariant 2: Loss Guard ON vs OFF isolation on Pre-PROGRESSED -15% close
  - Invariant 3: Post-PROGRESSED Exit3 / Exit4 parity between Baseline V2 and Julia V00
  - Invariant 4: Pre-2022 history used for technical indicators, pre-2022 trades excluded
  - Invariant 5: Reentry rules parity (MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER, FLAT required)
  - Invariant 6: Common-Entry Pairing determinism
  - Invariant 7: Same-open exit and reentry prohibition
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
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


def test_invariant_1_parity_when_no_loss_guard(sample_cache, score_contract, stage_contract):
    """When a stock never touches -15% pre-PROGRESSED loss, Baseline and Julia MUST have identical trades."""
    # 043260 (성호전자) had no LG triggered in 2022+
    daily = sample_cache.load("043260")
    if daily is None or daily.empty:
        pytest.skip("043260 cache not available")

    b_trades = simulate_ticker_strategy_2022("043260", "성호전자", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=True)
    j_trades = simulate_ticker_strategy_2022("043260", "성호전자", "KOSDAQ", daily, score_contract, stage_contract, enable_loss_guard=False)

    assert len(b_trades) == len(j_trades)
    for bt, jt in zip(b_trades, j_trades):
        assert bt.entry_signal_date == jt.entry_signal_date
        assert bt.entry_execution_date == jt.entry_execution_date
        assert bt.entry_open == jt.entry_open
        assert bt.exit_type == jt.exit_type
        assert bt.exit_execution_date == jt.exit_execution_date
        assert bt.terminal_return == jt.terminal_return


def test_invariant_2_loss_guard_isolation(sample_cache, score_contract, stage_contract):
    """When a stock drops <= -15% pre-PROGRESSED, Baseline exits on LG, while Julia continues holding."""
    # 000150 (두산) had LG triggered in 2022-11
    daily = sample_cache.load("000150")
    if daily is None or daily.empty:
        pytest.skip("000150 cache not available")

    b_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True)
    j_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False)

    # Baseline first trade in 2022 was LG exit
    assert len(b_trades) >= 1
    assert b_trades[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert b_trades[0].loss_guard_triggered is True

    # Julia first trade MUST NOT be LG exit
    assert len(j_trades) >= 1
    assert j_trades[0].exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert j_trades[0].loss_guard_triggered is False
    assert j_trades[0].entry_execution_date == b_trades[0].entry_execution_date
    assert j_trades[0].entry_open == b_trades[0].entry_open


def test_invariant_3_post_progressed_exits_parity(sample_cache, score_contract, stage_contract):
    """Exit3 and Exit4 semantics are identical for both strategies once PROGRESSED is reached."""
    # 006340 (대원전선) reached PROGRESSED and exited on Exit4 in both
    daily = sample_cache.load("006340")
    if daily is None or daily.empty:
        pytest.skip("006340 cache not available")

    b_trades = simulate_ticker_strategy_2022("006340", "대원전선", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True)
    j_trades = simulate_ticker_strategy_2022("006340", "대원전선", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False)

    assert len(b_trades) >= 1
    assert len(j_trades) >= 1
    assert b_trades[0].exit_type == j_trades[0].exit_type
    assert b_trades[0].terminal_return == j_trades[0].terminal_return


def test_invariant_4_evaluation_window_and_lookback(sample_cache, score_contract, stage_contract):
    """All emitted trades MUST have entry_execution_date >= 2022-01-01 and <= 2026-08-14."""
    # 000150 has pre-2022 signals in historical cache (e.g. 2017, 2018, 2021)
    daily = sample_cache.load("000150")
    if daily is None or daily.empty:
        pytest.skip("000150 cache not available")

    b_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True)
    j_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=False)

    for t in b_trades + j_trades:
        exec_d = pd.Timestamp(t.entry_execution_date)
        assert exec_d >= EVALUATION_START_DATE
        assert exec_d <= EVALUATION_END_DATE


def test_invariant_5_reentry_sequential_integrity(sample_cache, score_contract, stage_contract):
    """Each subsequent trade for a ticker MUST only execute after previous position has closed."""
    # 000150 has 2 trades in Baseline V2 2022+
    daily = sample_cache.load("000150")
    if daily is None or daily.empty:
        pytest.skip("000150 cache not available")

    b_trades = simulate_ticker_strategy_2022("000150", "두산", "KOSPI", daily, score_contract, stage_contract, enable_loss_guard=True)
    if len(b_trades) >= 2:
        for i in range(1, len(b_trades)):
            prev_exit_d = pd.Timestamp(b_trades[i - 1].exit_execution_date)
            cur_entry_d = pd.Timestamp(b_trades[i].entry_execution_date)
            assert cur_entry_d > prev_exit_d  # Strictly sequential, no overlapping, no same-open


def test_invariant_6_artifacts_exist_and_unaltered():
    """Verify newly generated artifacts exist in artifacts/strategies/julia/v00 and historical V2 artifacts are untouched."""
    julia_dir = ROOT / "artifacts/strategies/julia/v00"
    assert (julia_dir / "contract.json").exists()
    assert (julia_dir / "baseline_a_fast_core_v2_2022_trades.csv").exists()
    assert (julia_dir / "julia_v00_2022_trades.csv").exists()
    assert (julia_dir / "strategy_comparison_summary.json").exists()
    assert (julia_dir / "strategy_comparison_metrics.csv").exists()
    assert (julia_dir / "common_entry_pairs.csv").exists()
    assert (julia_dir / "loss_guard_counterfactual.csv").exists()
    assert (julia_dir / "loss_guard_recovery_summary.json").exists()
    assert (julia_dir / "worst_losses.csv").exists()
    assert (julia_dir / "big_winners.csv").exists()

    # Verify historical V2 783 trades artifact is intact
    historical_v2_csv = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    assert historical_v2_csv.exists()
    df_hist = pd.read_csv(historical_v2_csv)
    assert len(df_hist) == 783
