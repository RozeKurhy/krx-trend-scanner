from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_kodex200_v2_v3_same_window_v01 import (
    DATA_PATH,
    EQUITY_PATH,
    EVALUATION_START,
    MATCHED_PATH,
    NAME,
    ROOT,
    SIGNAL_CUTOFF,
    SEQUENTIAL_PATH,
    SUPPORT_END,
    TICKER,
    _contracts,
    build_equity_curve,
    curve_metrics,
    load_price_authority,
    scan_common_entries,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context


OUT_DIR = ROOT / "artifacts/research/kodex200_v2_v3_same_window_v01"
SUMMARY_PATH = OUT_DIR / "summary.json"


def test_raw_authority_and_window_contract() -> None:
    frame, meta = load_price_authority()
    assert DATA_PATH.exists()
    assert TICKER == "069500"
    assert NAME == "KODEX 200"
    assert len(frame) == 3101
    assert meta["actual_start"] == "2014-01-02"
    assert meta["actual_end"] == "2026-08-21"
    assert meta["evaluation_start"] == "2021-04-01"
    assert meta["signal_cutoff"] == "2026-08-14"
    assert meta["execution_support_end"] == "2026-08-21"
    assert frame.index.is_unique and frame.index.is_monotonic_increasing
    assert frame.index.min() < EVALUATION_START
    assert frame.index.max() == SUPPORT_END


def test_common_entries_and_matched_identity() -> None:
    frame, _meta = load_price_authority()
    context = build_precomputed_ticker_context(TICKER, NAME, frame)
    score, stage = _contracts()
    signals, _states, scan_meta = scan_common_entries(frame, context, score, stage)
    assert len(signals) == 16
    assert scan_meta["weekly_evaluation_error_count"] == 0
    assert len({row["signal_date"] for row in signals}) == len(signals)
    assert all(EVALUATION_START.strftime("%Y-%m-%d") <= row["signal_date"] <= SIGNAL_CUTOFF.strftime("%Y-%m-%d") for row in signals)
    matched = pd.read_csv(MATCHED_PATH)
    assert len(matched) == len(signals) * 2
    for signal in signals:
        group = matched[matched["entry_signal_date"] == signal["signal_date"]]
        assert len(group) == 2
        assert group["entry_execution_date"].nunique() == 1
        assert group["entry_price"].nunique() == 1


def test_execution_is_first_local_session_after_signal() -> None:
    frame, _meta = load_price_authority()
    matched = pd.read_csv(MATCHED_PATH)
    for _, row in matched.iterrows():
        signal = pd.Timestamp(row["entry_signal_date"])
        expected = frame.index[frame.index > signal][0]
        assert pd.Timestamp(row["entry_execution_date"]) == expected
        assert pd.Timestamp(row["entry_execution_date"]) > signal


def test_sequential_no_overlap_and_open_positions_use_support_close() -> None:
    frame, _meta = load_price_authority()
    sequential = pd.read_csv(SEQUENTIAL_PATH)
    for strategy, group in sequential.groupby("strategy"):
        group = group.sort_values("trade_no")
        previous_exit = None
        for _, row in group.iterrows():
            entry = pd.Timestamp(row["entry_execution_date"])
            assert previous_exit is None or entry > previous_exit
            if row["trade_status"] == "OPEN_AT_CUTOFF":
                assert row["final_valuation_date"] == SUPPORT_END.strftime("%Y-%m-%d")
                assert row["final_valuation_price"] == pytest.approx(float(frame.loc[SUPPORT_END, "close"]))
            elif pd.notna(row["exit_execution_date"]):
                previous_exit = pd.Timestamp(row["exit_execution_date"])

    short = frame.loc[frame.index >= EVALUATION_START].iloc[:5]
    open_trade = [{"entry_execution_date": short.index[0].strftime("%Y-%m-%d"), "entry_price": float(short.iloc[0]["open"])}]
    curve = build_equity_curve("OPEN_TEST", short, open_trade)
    assert curve.iloc[-1]["position_state"] == "HOLD"
    assert curve.iloc[-1]["equity"] == pytest.approx(float(short.iloc[-1]["close"]) / float(short.iloc[0]["open"]))


def test_daily_equity_metrics_match_summary() -> None:
    equity = pd.read_csv(EQUITY_PATH)
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    for strategy in ("V2", "V3", "Buy & Hold"):
        curve = equity[equity["strategy"] == strategy].reset_index(drop=True)
        actual = curve_metrics(curve)
        expected = summary["strategies"][strategy]
        for key in ("total_return_pct", "cagr_pct", "mdd_pct", "final_equity", "exposure_ratio_pct"):
            assert actual[key] == pytest.approx(expected[key])


def test_runner_is_v2_v3_only_and_network_guarded() -> None:
    runner = (ROOT / "scripts/run_kodex200_v2_v3_same_window_v01.py").read_text(encoding="utf-8")
    assert "simulate_ticker_strategy_fundamentals_v01" in runner
    assert "run_fastcore_v3_simple_v00" in runner
    assert "run_fastcore_v4" not in runner
    assert "julia_strategy" not in runner
    assert "socket.socket.connect" in runner
