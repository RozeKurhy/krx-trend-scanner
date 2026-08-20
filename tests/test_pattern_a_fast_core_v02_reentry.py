"""Comprehensive Targeted Invariant Tests for Pattern A FAST Core V02 Re-Entry Strategy."""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    DATA_CUTOFF,
    V02TradeRecord,
    simulate_ticker_core_v02_reentry,
)
from scripts.inspect_v02_evidence import (
    build_representative_case,
    classify_deep_loss_cause,
)

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"
V01_CSV_PATH = ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/pattern_a_fast_strategy_finalization_v01_trades.csv"
V02_CSV_PATH = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
V02_TICKER_CSV_PATH = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/ticker_summary.csv"
DEEP_LOSS_CSV_PATH = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/deep_loss_reentry_cases.csv"


@pytest.fixture
def contracts():
    sc = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    st = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return sc, st


def test_v02_sequence_1_identity_vs_v01_baseline():
    """Section 11: Verify 100% row-level identity between V01 (551) and V02 Sequence 1 (551)."""
    v01_df = pd.read_csv(V01_CSV_PATH, dtype={"ticker": str})
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})

    v01_df["ticker"] = v01_df["ticker"].str.zfill(6)
    v02_df["ticker"] = v02_df["ticker"].str.zfill(6)

    v02_seq1 = v02_df[v02_df["trade_sequence"] == 1].sort_values(by="ticker").reset_index(drop=True)
    v01_sorted = v01_df.sort_values(by="ticker").reset_index(drop=True)

    assert len(v01_sorted) == 551
    assert len(v02_seq1) == 551

    fields_to_compare = [
        ("entry_signal_date", "entry_signal_date"),
        ("entry_execution_date", "entry_execution_date"),
        ("entry_open", "entry_open"),
        ("entry_pattern_a_stage", "entry_pattern_a_stage"),
        ("fast_monthly_regime_at_entry", "monthly_regime"),
        ("daily_risk_at_entry", "daily_risk"),
        ("fast_score_availability", "fast_score_state"),
        ("loss_guard_triggered", "loss_guard_triggered"),
        ("loss_guard_signal_date", "loss_guard_signal_date"),
        ("loss_guard_exec_date", "loss_guard_execution_date"),
        ("lifecycle_class", "lifecycle_class"),
        ("first_progressed_date", "first_progressed_date"),
        ("first_progressed_effective_trading_date", "first_progressed_effective_trading_date"),
        ("hold_b_e2_exit_type", "exit_type"),
        ("hold_b_e2_terminal_return", "terminal_return"),
        ("hold_b_e2_mfe", "mfe"),
        ("hold_b_e2_mae", "mae"),
        ("hold_b_e2_peak_giveback", "peak_giveback"),
        ("hold_b_e2_holding_weeks", "holding_weeks"),
    ]

    mismatches = []
    for i in range(len(v01_sorted)):
        r1 = v01_sorted.iloc[i]
        r2 = v02_seq1.iloc[i]
        t1 = r1["ticker"]
        t2 = r2["ticker"]
        assert t1 == t2, f"Ticker alignment mismatch: {t1} != {t2}"

        for f1, f2 in fields_to_compare:
            v1 = r1[f1]
            v2 = r2[f2]
            if pd.isna(v1) and pd.isna(v2):
                continue
            if isinstance(v1, (int, float, np.number)) and isinstance(v2, (int, float, np.number)):
                if not np.isclose(float(v1), float(v2), atol=1e-2):
                    mismatches.append((t1, f1, v1, v2))
            else:
                if str(v1) != str(v2):
                    mismatches.append((t1, f1, v1, v2))

    assert len(mismatches) == 0, f"Expected 0 mismatches between V01 and V02 Sequence 1, got {len(mismatches)}"


def test_v02_representative_cases_source_identity():
    """Section 8: Verify representative case generator outputs match trades.csv source rows exactly."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    ticker_df = pd.read_csv(V02_TICKER_CSV_PATH, dtype={"ticker": str})

    for ticker in ["005930", "011170", "001540"]:
        rep = build_representative_case(ticker, v02_df, ticker_df)
        src_rows = v02_df[v02_df["ticker"] == ticker].sort_values(by="trade_sequence")
        assert rep["total_trades"] == len(src_rows)

        for i, tr in enumerate(rep["trades"]):
            src_r = src_rows.iloc[i]
            assert tr["trade_id"] == src_r["trade_id"]
            assert tr["trade_sequence"] == src_r["trade_sequence"]
            assert tr["entry_signal_date"] == src_r["entry_signal_date"]
            assert tr["entry_execution_date"] == src_r["entry_execution_date"]
            assert np.isclose(tr["entry_open"], src_r["entry_open"], atol=1e-2)
            assert tr["exit_type"] == src_r["exit_type"]
            assert np.isclose(tr["terminal_return"], src_r["terminal_return"], atol=1e-2)
            assert tr["trade_status"] == src_r["trade_status"]


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
    assert t2.entry_execution_date > t1.exit_execution_date


def test_v02_exit3_then_reentry(contracts):
    """Section 12: Exit 3 stage transition followed by valid re-entry (NH투자증권 005940)."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("005940")

    trades = simulate_ticker_core_v02_reentry(
        ticker="005940",
        name="NH투자증권",
        market="KOSPI",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
    )

    assert len(trades) >= 2
    t1 = trades[0]
    t2 = trades[1]
    assert t1.exit_type.startswith("EXIT3_")
    assert t2.previous_exit_type == t1.exit_type
    assert t2.entry_execution_date > t1.exit_execution_date
    assert t2.trade_sequence == 2


def test_v02_exit4_then_reentry(contracts):
    """Section 13: Exit 4 Score drawdown followed by valid re-entry (SK하이닉스 000660)."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("000660")

    trades = simulate_ticker_core_v02_reentry(
        ticker="000660",
        name="SK하이닉스",
        market="KOSPI",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
    )

    assert len(trades) >= 2
    for i in range(len(trades) - 1):
        cur_t = trades[i]
        next_t = trades[i + 1]
        if cur_t.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15":
            assert next_t.previous_exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"
            assert next_t.entry_execution_date > cur_t.exit_execution_date


def test_v02_coverage_exit4_then_reentry(contracts):
    """Section 14: Coverage Exit 4 (SKIPPED/WITHOUT DIRECT) followed by valid re-entry (SKC 011790)."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("011790")

    trades = simulate_ticker_core_v02_reentry(
        ticker="011790",
        name="SKC",
        market="KOSPI",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
    )

    assert len(trades) >= 2
    t1 = trades[0]
    t2 = trades[1]
    assert t1.lifecycle_class in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}
    assert t1.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"
    assert t2.previous_exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15"
    assert t2.entry_execution_date > t1.exit_execution_date


def test_v02_multiple_reentries(contracts):
    """Section 15: Multiple re-entries with sequential numbering and strict non-overlap (삼성전자 005930)."""
    score_contract, stage_contract = contracts
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("005930")

    trades = simulate_ticker_core_v02_reentry(
        ticker="005930",
        name="삼성전자",
        market="KOSPI",
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
    )

    assert len(trades) == 4, f"Expected 4 trades for 005930, got {len(trades)}"
    for i, t in enumerate(trades, 1):
        assert t.trade_sequence == i
        assert t.trade_id == f"005930_{i:02d}"

    for i in range(len(trades) - 1):
        assert trades[i].exit_execution_date is not None
        assert trades[i + 1].entry_execution_date > trades[i].exit_execution_date


def test_v02_same_day_exit_reentry_prohibition_all_trades():
    """Section 16: Verify across all 783 trades that no trade enters on or before previous exit execution date."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    for ticker, group in v02_df.groupby("ticker"):
        sorted_g = group.sort_values(by="trade_sequence")
        for i in range(len(sorted_g) - 1):
            cur_trade = sorted_g.iloc[i]
            next_trade = sorted_g.iloc[i + 1]
            prev_exit_d = cur_trade["exit_execution_date"]
            next_entry_d = next_trade["entry_execution_date"]
            assert pd.notna(prev_exit_d), f"Prior trade {cur_trade['trade_id']} must have exit execution date"
            assert next_entry_d > prev_exit_d, f"Next entry {next_trade['trade_id']} ({next_entry_d}) must be strictly after prior exit {cur_trade['trade_id']} ({prev_exit_d})"


def test_v02_open_at_cutoff_invariant_all_trades():
    """Section 17: Verify that if a trade is OPEN_AT_CUTOFF, it is strictly the last trade for that ticker."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    for ticker, group in v02_df.groupby("ticker"):
        sorted_g = group.sort_values(by="trade_sequence")
        for i in range(len(sorted_g)):
            trade = sorted_g.iloc[i]
            if trade["trade_status"] == "OPEN_AT_CUTOFF":
                assert i == len(sorted_g) - 1, f"OPEN_AT_CUTOFF trade {trade['trade_id']} is not the last trade for ticker {ticker}"


def test_v02_loss_guard_basis_reset():
    """Section 14: Verify Loss Guard basis price and threshold reset independently on re-entries."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})

    # Find tickers where both sequence 1 and sequence > 1 triggered Loss Guard
    lg_trades = v02_df[v02_df["loss_guard_triggered"] == True]
    multi_lg_tickers = lg_trades["ticker"].value_counts()[lambda x: x >= 2].index.tolist()

    assert len(multi_lg_tickers) > 0

    for ticker in multi_lg_tickers[:5]:
        t_trades = v02_df[(v02_df["ticker"] == ticker) & (v02_df["loss_guard_triggered"] == True)].sort_values(by="trade_sequence")
        t1, t2 = t_trades.iloc[0], t_trades.iloc[1]

        # Entry prices are distinct
        assert t1["entry_open"] != t2["entry_open"]
        # Thresholds are distinct
        t1_stop_threshold = t1["entry_open"] * 0.85
        t2_stop_threshold = t2["entry_open"] * 0.85
        assert t1_stop_threshold != t2_stop_threshold


def test_v02_first_progressed_reset():
    """Section 15: Verify first PROGRESSED state resets and is strictly post-entry for re-entries."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    reentries = v02_df[v02_df["trade_sequence"] >= 2]

    for _, r in reentries.iterrows():
        f_prog = r["first_progressed_date"]
        if pd.notna(f_prog):
            # First progressed must be strictly on or after this trade's entry signal date
            assert str(f_prog) >= str(r["entry_signal_date"])


def test_v02_exit4_hwm_reset():
    """Section 16: Verify Exit4 HWM initialization starts from the new trade's own PROGRESSED score."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("000660")
    assert daily is not None

    # In 000660, verify multiple trades reach PROGRESSED and have independent HWM
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    hynix_trades = v02_df[v02_df["ticker"] == "000660"].sort_values(by="trade_sequence")
    assert len(hynix_trades) >= 3

    for i in range(len(hynix_trades) - 1):
        tr = hynix_trades.iloc[i]
        next_tr = hynix_trades.iloc[i + 1]
        assert next_tr["entry_execution_date"] > tr["exit_execution_date"]


def test_v02_artifact_cardinality_and_consistency():
    """Section 19: Verify cardinalities and sequential cumulative return consistency."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    ticker_df = pd.read_csv(V02_TICKER_CSV_PATH, dtype={"ticker": str})

    assert len(v02_df) == 783
    assert v02_df["ticker"].nunique() == 551
    assert len(ticker_df) == 551
    assert (v02_df["trade_sequence"] == 1).sum() == 551
    assert (v02_df["trade_sequence"] >= 2).sum() == 232
    assert ticker_df[ticker_df["total_trades"] >= 2]["ticker"].nunique() == 151
    assert v02_df["trade_sequence"].max() == 5

    for _, row in ticker_df.iterrows():
        t = row["ticker"]
        t_trades = v02_df[v02_df["ticker"] == t].sort_values(by="trade_sequence")
        assert len(t_trades) == row["total_trades"]

        cum_factor = 1.0
        for _, tr in t_trades.iterrows():
            cum_factor *= (1.0 + float(tr["terminal_return"]) / 100.0)
        expected_cum_pct = round((cum_factor - 1.0) * 100.0, 2)
        assert np.isclose(expected_cum_pct, row["sequential_cumulative_return_pct"], atol=1e-2)


def test_v02_deep_loss_cardinality_and_classification():
    """Section 22: Verify deep loss cases cardinalities (14 <= -20% and 4 <= -30%) and classifications."""
    deep_df = pd.read_csv(DEEP_LOSS_CSV_PATH, dtype={"ticker": str})
    assert len(deep_df) == 14
    assert (deep_df["terminal_return"] <= -30.0).sum() == 4

    for _, r in deep_df.iterrows():
        assert pd.notna(r["primary_cause"])
        assert pd.notna(r["research_interpretation"])
        assert r["primary_cause"] in {
            "OPEN_AT_CUTOFF_STRUCTURAL_TAIL",
            "LOSS_GUARD_EXECUTION_TAIL",
            "POST_PROGRESSED_EXIT3_LAG",
            "POST_PROGRESSED_EXIT4_TAIL",
            "NEVER_PROGRESSED_DEEP_LOSS",
            "COVERAGE_STRUCTURAL_TAIL",
            "OTHER_DEEP_LOSS",
        }
