from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts/research/sector_index_etf_four_strategy_v01"
DATA_ROOT = ROOT / "data/raw/stocks"
TICKERS = ("091160", "102970", "091170", "091180", "266420", "140700", "117700", "266370", "363580", "266360", "117460", "117680", "102960", "266410", "140710", "266390")
RUNS = ("long_range", "same_window")
STRATEGIES = ("V2", "V3", "V4", "Julia", "Buy & Hold")
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")


def _aggregate() -> dict:
    return json.loads((ARTIFACT_ROOT / "aggregate_summary.json").read_text(encoding="utf-8"))


def _summary(ticker: str, run: str) -> dict:
    return json.loads((ARTIFACT_ROOT / ticker / run / "summary.json").read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, *, label: str) -> None:
    assert actual == pytest.approx(expected, abs=1e-5), label


def test_all_sector_runs_are_complete_and_no_liquidity_filter() -> None:
    aggregate = _aggregate()
    assert aggregate["status"] == "COMPLETE"
    assert aggregate["network_requests"] == 0
    assert aggregate["liquidity_filter_applied"] is False
    assert set(aggregate["etfs"]) == set(TICKERS)

    for ticker in TICKERS:
        data = aggregate["etfs"][ticker]["data"]
        frame = pd.read_parquet(DATA_ROOT / f"{ticker}.parquet").sort_index()
        assert tuple(frame.columns) == REQUIRED_COLUMNS
        assert frame.index.is_unique
        assert frame.index.is_monotonic_increasing
        assert data["used_end"] == "2026-08-21"
        assert (pd.Timestamp(data["used_end"]) - pd.Timestamp(data["used_start"])).days >= int(365.25 * 5)
        for run in RUNS:
            summary = _summary(ticker, run)
            assert summary["status"] == "COMPLETE"
            assert summary["scan"]["liquidity_filter_applied"] is False
            assert summary["scan"]["liquidity_filter_threshold_krw"] == 0.0
            assert summary["execution_support_end"] == "2026-08-21"
            assert summary["final_valuation"] == "2026-08-21 CLOSE"


def test_matched_identity_and_v3_julia_comparison() -> None:
    for ticker in TICKERS:
        for run in RUNS:
            summary = _summary(ticker, run)
            matched = pd.read_csv(ARTIFACT_ROOT / ticker / run / "matched_trades.csv")
            assert len(matched) == summary["common_entry_count"] * 4
            assert matched.duplicated(["strategy", "entry_signal_date"]).sum() == 0
            for _, group in matched.groupby("entry_signal_date", sort=False):
                assert set(group["strategy"]) == {"V2", "V3", "V4", "Julia"}
                assert group["entry_execution_date"].nunique() == 1
                assert group["entry_price"].nunique() == 1
            assert summary["matched_identity"]["signal_date_match"] is True
            assert summary["matched_identity"]["execution_date_match"] is True
            assert summary["matched_identity"]["entry_open_match"] is True
            assert summary["matched_identity"]["duplicate_entries"] == 0
            direct = summary["v3_vs_julia"]
            assert direct["paired_count"] == summary["common_entry_count"]
            assert direct["julia_better_count"] + direct["v3_better_count"] + direct["same_count"] == direct["paired_count"]
            assert set(direct["metric_comparison"]) == {"mean_return_pct", "median_return_pct", "win_rate_pct", "mean_mae_pct"}


def test_sequential_paths_have_no_overlap_and_valid_exit_support() -> None:
    for ticker in TICKERS:
        for run in RUNS:
            sequential = pd.read_csv(ARTIFACT_ROOT / ticker / run / "sequential_trades.csv")
            raw = pd.read_parquet(DATA_ROOT / f"{ticker}.parquet")
            support_close = float(raw.loc[pd.Timestamp("2026-08-21"), "close"])
            for strategy in ("V2", "V3", "V4", "Julia"):
                trades = sequential.loc[sequential["strategy"] == strategy].copy()
                trades["entry_execution_date"] = pd.to_datetime(trades["entry_execution_date"])
                trades["exit_signal_date"] = pd.to_datetime(trades["exit_signal_date"], errors="coerce")
                trades["exit_execution_date"] = pd.to_datetime(trades["exit_execution_date"], errors="coerce")
                trades = trades.sort_values("entry_execution_date")
                for previous, current in zip(trades.iloc[:-1].itertuples(), trades.iloc[1:].itertuples()):
                    assert pd.isna(previous.exit_execution_date) or current.entry_execution_date > previous.exit_execution_date
                realized = trades.loc[trades["trade_status"] == "REALIZED"]
                assert (realized["exit_execution_date"] > realized["exit_signal_date"]).all()
                open_trades = trades.loc[trades["trade_status"] == "OPEN_AT_CUTOFF"]
                assert set(open_trades["final_valuation_date"].dropna()) <= {"2026-08-21"}
                if not open_trades.empty:
                    _assert_close(float(open_trades.iloc[-1]["final_valuation_price"]), support_close, label=f"{ticker}/{run}/{strategy} final mark")


def test_daily_equity_reproduces_summary_metrics() -> None:
    for ticker in TICKERS:
        for run in RUNS:
            summary = _summary(ticker, run)
            equity = pd.read_csv(ARTIFACT_ROOT / ticker / run / "daily_equity.csv")
            equity["date"] = pd.to_datetime(equity["date"])
            for strategy in STRATEGIES:
                curve = equity.loc[equity["strategy"] == strategy].sort_values("date")
                values = pd.to_numeric(curve["equity"], errors="raise")
                years = max((curve["date"].iloc[-1] - curve["date"].iloc[0]).days / 365.25, 1e-12)
                total = (float(values.iloc[-1]) / float(values.iloc[0]) - 1.0) * 100.0
                cagr = ((float(values.iloc[-1]) / float(values.iloc[0])) ** (1.0 / years) - 1.0) * 100.0
                mdd = float((values / values.cummax() - 1.0).min()) * 100.0
                expected = summary["strategies"][strategy]
                _assert_close(total, expected["total_return_pct"], label=f"{ticker}/{run}/{strategy} total")
                _assert_close(cagr, expected["cagr_pct"], label=f"{ticker}/{run}/{strategy} CAGR")
                _assert_close(mdd, expected["mdd_pct"], label=f"{ticker}/{run}/{strategy} MDD")


@pytest.mark.parametrize("run", RUNS)
def test_head_to_head_counts_cover_all_sector_etfs(run: str) -> None:
    head_to_head = _aggregate()["head_to_head"][run]
    expected_metrics = {"sequential_total_return", "sequential_cagr", "sequential_mdd", "matched_mean_return", "matched_median_return", "matched_win_rate", "matched_mean_mae"}
    assert set(head_to_head) == expected_metrics
    for counts in head_to_head.values():
        assert counts["V3_win"] + counts["Julia_win"] + counts["tie"] == len(TICKERS)
