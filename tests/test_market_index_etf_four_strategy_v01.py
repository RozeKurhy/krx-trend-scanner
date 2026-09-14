from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts/research/market_index_etf_four_strategy_v01"
DATA_ROOT = ROOT / "data/raw/stocks"
TICKERS = ("229200", "292190", "226490", "156080", "226980")
RUNS = ("long_range", "same_window")
STRATEGIES = ("V2", "V3", "V4", "Julia", "Buy & Hold")
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")


def _aggregate() -> dict:
    return json.loads((ARTIFACT_ROOT / "aggregate_summary.json").read_text(encoding="utf-8"))


def _summary(ticker: str, run: str) -> dict:
    return json.loads((ARTIFACT_ROOT / ticker / run / "summary.json").read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, *, label: str) -> None:
    assert actual == pytest.approx(expected, abs=1e-5), label


def test_raw_authority_and_run_periods_are_complete() -> None:
    aggregate = _aggregate()
    assert aggregate["status"] == "COMPLETE"
    assert aggregate["network_requests"] == 0

    for ticker in TICKERS:
        data = aggregate["etfs"][ticker]["data"]
        frame = pd.read_parquet(DATA_ROOT / f"{ticker}.parquet").sort_index()
        assert tuple(frame.columns) == REQUIRED_COLUMNS
        assert frame.index.is_unique
        assert frame.index.is_monotonic_increasing
        assert data["used_end"] == "2026-08-21"
        assert data["rows_used_to_support"] == len(frame.loc[frame.index <= pd.Timestamp("2026-08-21")])
        assert (pd.Timestamp(data["used_end"]) - pd.Timestamp(data["used_start"])).days >= int(365.25 * 5)
        assert pd.Timestamp(data["used_start"]) < pd.Timestamp("2021-04-01")
        for run in RUNS:
            summary = _summary(ticker, run)
            assert summary["status"] == "COMPLETE"
            assert summary["execution_support_end"] == "2026-08-21"
            assert summary["final_valuation"] == "2026-08-21 CLOSE"


def test_matched_entry_identity_and_counts() -> None:
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
def test_v2_comparison_win_counts_are_present(run: str) -> None:
    wins = _aggregate()["wins"][run]
    for metric in ("sequential_total", "sequential_cagr", "sequential_mdd", "matched_mean", "matched_median", "matched_win_rate"):
        assert set(wins[metric]) == {"V3", "V4", "Julia"}
        assert all(isinstance(wins[metric][strategy], int) for strategy in ("V3", "V4", "Julia"))
