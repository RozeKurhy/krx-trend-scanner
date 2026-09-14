from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_kodex200_four_strategy_reproduction_v01 import (
    DATA_PATH,
    NAME,
    ROOT,
    TICKER,
    _contracts,
    build_buy_hold_curve,
    build_equity_curve,
    curve_metrics,
    load_price_authority,
    scan_common_entries,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context


def test_price_authority_period_and_schema_are_frozen() -> None:
    frame, meta = load_price_authority()
    assert DATA_PATH.exists()
    assert TICKER == "069500"
    assert NAME == "KODEX 200"
    assert len(frame) == 3097
    assert meta["actual_start"] == "2014-01-02"
    assert meta["actual_end"] == "2026-08-14"
    assert set(("open", "high", "low", "close", "volume", "trading_value")).issubset(frame.columns)
    assert frame.index.is_unique


def test_common_entry_contract_reproduces_35_signals_without_network() -> None:
    frame, _meta = load_price_authority()
    context = build_precomputed_ticker_context(TICKER, NAME, frame)
    score, stage = _contracts()
    signals, states, scan_meta = scan_common_entries(frame, context, score, stage)
    assert len(signals) == 35
    assert len(states) > 0
    assert scan_meta["weekly_evaluation_error_count"] == 0
    assert all(pd.Timestamp(row["entry_execution_date"]) > pd.Timestamp(row["signal_date"]) for row in signals)


def test_buy_and_hold_starts_at_open_and_total_return_matches_curve() -> None:
    frame, _meta = load_price_authority()
    curve = build_buy_hold_curve(frame)
    assert curve.iloc[0]["equity"] == 1.0
    metrics = curve_metrics(curve)
    assert metrics["total_return_pct"] == pytest.approx(311.901198, abs=0.001)


def test_equity_curve_mdd_and_no_overlap_are_mechanical() -> None:
    frame, _meta = load_price_authority()
    trades = [
        {
            "strategy": "TEST",
            "entry_execution_date": "2017-01-09",
            "entry_price": 26700.0,
            "exit_execution_date": "2018-02-12",
            "exit_price": 31005.0,
        }
    ]
    curve = build_equity_curve("TEST", frame, trades)
    metrics = curve_metrics(curve)
    assert metrics["final_equity"] > 1.0
    assert metrics["mdd_pct"] <= 0.0
    with pytest.raises(AssertionError, match="overlapping"):
        build_equity_curve(
            "TEST",
            frame,
            trades + [{**trades[0], "entry_execution_date": "2017-01-10"}],
        )


def test_runner_uses_frozen_authority_and_writes_only_research_artifacts() -> None:
    runner = (ROOT / "scripts/run_kodex200_four_strategy_reproduction_v01.py").read_text(encoding="utf-8")
    assert "simulate_ticker_strategy_fundamentals_v01" in runner
    assert "simulate_ticker_strategy_2022" in runner
    assert "run_fastcore_v3_simple_v00" in runner
    assert "run_fastcore_v4_matched_ab_official_v01" in runner
    assert "production_strategy_modified" in runner
    assert "artifacts/research/kodex200_four_strategy_reproduction_v01" in runner
    assert "socket.socket.connect" in runner
