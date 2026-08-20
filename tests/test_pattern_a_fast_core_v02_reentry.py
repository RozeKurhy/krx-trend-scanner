"""Comprehensive Targeted Invariant Tests for Pattern A FAST Core V02 Re-Entry Strategy."""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly
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


def test_v02_loss_guard_basis_reset_exact():
    """Sections 8-10, 23: Verify exact Loss Guard recomputation from new trade's entry_open basis on DL (000210_02)."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    t2 = v02_df[v02_df["trade_id"] == "000210_02"].iloc[0]

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("000210").sort_index()

    entry_open = float(t2["entry_open"])
    e_exec = pd.Timestamp(t2["entry_execution_date"])
    f_eff = pd.Timestamp(t2["first_progressed_effective_trading_date"]) if pd.notna(t2["first_progressed_effective_trading_date"]) else DATA_CUTOFF
    pre_prog = daily[(daily.index >= e_exec) & (daily.index < f_eff)]

    recomp_sig_d = None
    recomp_exec_d = None
    recomp_exec_price = None

    for d, row in pre_prog.iterrows():
        c = float(row["close"])
        if (c / entry_open - 1.0) <= -0.15:
            recomp_sig_d = d
            fut = daily[(daily.index > d) & (daily.index <= DATA_CUTOFF)]
            if not fut.empty:
                recomp_exec_d = fut.index[0]
                recomp_exec_price = float(fut.iloc[0]["open"])
            break

    assert recomp_sig_d is not None
    assert recomp_sig_d.strftime("%Y-%m-%d") == t2["loss_guard_signal_date"]
    assert recomp_exec_d.strftime("%Y-%m-%d") == t2["loss_guard_execution_date"]
    assert np.isclose(recomp_exec_price, t2["loss_guard_execution_price"], atol=1e-2)


def test_v02_first_progressed_reset_exact():
    """Sections 11-13, 23: Verify exact monthly PROGRESSED recomputation for re-entry trade on SK Hynix (000660_04)."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    t4 = v02_df[v02_df["trade_id"] == "000660_04"].iloc[0]

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("000660").sort_index()
    monthly_bars = to_monthly(daily)
    m_dates = [m for m in monthly_bars.index if m >= pd.Timestamp(t4["entry_signal_date"]) and m <= DATA_CUTOFF]

    recomp_f_prog = None
    recomp_f_eff = None

    for m in m_dates:
        snap = build_historical_snapshot("000660", "SK하이닉스", daily[daily.index <= m], m, include_incomplete_periods=False)
        eval_res = evaluate_pattern_a(snap)
        st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
        if st == "PROGRESSED":
            recomp_f_prog = m
            m_daily = daily[daily.index <= m]
            if not m_daily.empty:
                recomp_f_eff = m_daily.index.max()
            break

    assert recomp_f_prog is not None
    assert recomp_f_prog.strftime("%Y-%m-%d") == t4["first_progressed_date"]
    assert recomp_f_eff.strftime("%Y-%m-%d") == t4["first_progressed_effective_trading_date"]


def test_v02_exit4_hwm_reset_exact():
    """Sections 14-16, 23: Verify exact Exit4 HWM recomputation initialized from new trade PROGRESSED score on Doosan (000150_03)."""
    v02_df = pd.read_csv(V02_CSV_PATH, dtype={"ticker": str})
    t3 = v02_df[v02_df["trade_id"] == "000150_03"].iloc[0]

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("000150").sort_index()
    monthly_bars = to_monthly(daily)
    m_dates = [m for m in monthly_bars.index if m >= pd.Timestamp(t3["entry_signal_date"]) and m <= DATA_CUTOFF]

    monthly_snaps = []
    for m in m_dates:
        snap = build_historical_snapshot("000150", "두산", daily[daily.index <= m], m, include_incomplete_periods=False)
        eval_res = evaluate_pattern_a(snap)
        st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
        sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
        monthly_snaps.append({"date": m, "stage": st, "score": sc})

    f_prog = pd.Timestamp(t3["first_progressed_date"])
    f_score = None
    for s in monthly_snaps:
        if s["date"] == f_prog and s["stage"] == "PROGRESSED":
            f_score = s["score"]
            break

    assert f_score is not None
    assert np.isclose(f_score, 67.52, atol=1e-2)

    hwm = f_score
    recomp_exit_sig = None
    for s in monthly_snaps:
        m = s["date"]
        st = s["stage"]
        sc = s["score"]
        if m <= f_prog:
            continue
        if st == "PROGRESSED":
            if sc is not None:
                hwm = max(hwm, sc)
                if hwm - sc >= 15.0:
                    recomp_exit_sig = m
                    break
        elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
            recomp_exit_sig = m
            break

    assert recomp_exit_sig is not None
    assert recomp_exit_sig.strftime("%Y-%m-%d") == t3["exit_signal_date"]


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
    """Sections 4-6, 22, 24: Verify deep loss cases cardinalities (14 <= -20% and 4 <= -30%) and classification hygiene."""
    deep_df = pd.read_csv(DEEP_LOSS_CSV_PATH, dtype={"ticker": str})
    assert len(deep_df) == 14
    assert (deep_df["terminal_return"] <= -30.0).sum() == 4

    forbidden_terms = ["gap caused", "갭하락으로 인해", "slippage caused", "GAP LOSS"]

    for _, r in deep_df.iterrows():
        assert pd.notna(r["primary_cause"])
        assert pd.notna(r["research_interpretation"])
        assert r["primary_cause"] in {
            "OPEN_AT_CUTOFF_STRUCTURAL_TAIL",
            "LOSS_GUARD_REALIZED_DEEP_LOSS",
            "POST_PROGRESSED_EXIT3_LAG",
            "POST_PROGRESSED_EXIT4_TAIL",
            "NEVER_PROGRESSED_DEEP_LOSS",
            "COVERAGE_STRUCTURAL_TAIL",
            "OTHER_DEEP_LOSS",
        }
        for term in forbidden_terms:
            assert term not in r["research_interpretation"], f"Forbidden speculative term '{term}' found in interpretation"
