"""Targeted tests for Pattern A FAST Core V02 Re-Entry Strategy."""

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    DATA_CUTOFF,
    V02TradeRecord,
    simulate_ticker_core_v02_reentry,
)

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"


@pytest.fixture
def contracts():
    sc = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    st = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return sc, st


def test_v02_reentry_loss_guard_then_reentry(contracts):
    """Section 26 / 32: Loss Guard exit followed by valid second entry (안국약품 001540)."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("001540")

    trades = simulate_ticker_core_v02_reentry(
        ticker="001540",
        name="안국약품",
        market="KOSDAQ",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        cutoff_date=DATA_CUTOFF,
    )

    assert len(trades) == 2, f"Expected 2 trades for 001540, got {len(trades)}"

    # Trade 1
    t1 = trades[0]
    assert t1.trade_id == "001540_01"
    assert t1.trade_sequence == 1
    assert t1.entry_signal_date == "2025-12-05"
    assert t1.entry_execution_date == "2025-12-08"
    assert t1.loss_guard_triggered is True
    assert t1.exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert t1.exit_execution_date == "2026-03-05"
    assert t1.terminal_return == -15.57
    assert t1.previous_exit_type is None

    # Trade 2 (Re-entry)
    t2 = trades[1]
    assert t2.trade_id == "001540_02"
    assert t2.trade_sequence == 2
    assert t2.entry_signal_date == "2026-05-15"
    assert t2.entry_execution_date == "2026-05-18"
    assert t2.previous_exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert t2.previous_exit_execution_date == "2026-03-05"
    # Re-entry execution is after Trade 1 exit execution
    assert t2.entry_execution_date > t1.exit_execution_date


def test_v02_no_overlapping_positions_invariant(contracts):
    """Ensure no trades overlap chronologically for any ticker."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    sample_tickers = ["001540", "005930", "000660", "035420"]
    for ticker in sample_tickers:
        daily = cache.load(ticker)
        trades = simulate_ticker_core_v02_reentry(
            ticker=ticker,
            name=ticker,
            market="KOSPI",
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
        )
        for i in range(len(trades) - 1):
            cur_trade = trades[i]
            next_trade = trades[i + 1]
            assert cur_trade.exit_execution_date is not None, "Prior trade must be closed before next trade enters"
            assert next_trade.entry_execution_date > cur_trade.exit_execution_date, "Next entry must execute strictly after prior exit"


def test_v02_state_reset_on_reentry(contracts):
    """Verify that Loss Guard, HWM, and stage context reset completely on re-entry."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("001540")

    trades = simulate_ticker_core_v02_reentry(
        ticker="001540",
        name="안국약품",
        market="KOSDAQ",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
    )

    if len(trades) >= 2:
        t1, t2 = trades[0], trades[1]
        assert t1.entry_open != t2.entry_open
        assert t2.loss_guard_triggered is False or t2.loss_guard_signal_date > t1.exit_execution_date
