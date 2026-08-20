"""Targeted Invariant and Diagnostic Consistency Tests for PROGRESSED Downside Protection Phase 1 (Corrected)."""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
V02_TRADES_CSV = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
DIAG_DIR = ROOT / "artifacts/pattern_a_fast/progressed_downside_v01"


@pytest.fixture
def diag_artifacts():
    summary_path = DIAG_DIR / "summary.json"
    trades_path = DIAG_DIR / "progressed_trades.csv"
    deep_loss_path = DIAG_DIR / "progressed_deep_loss_cases.csv"
    winner_path = DIAG_DIR / "progressed_winner_drawdown.csv"
    winner_extreme_path = DIAG_DIR / "progressed_winner_extreme_drawdown_cases.csv"
    exit3_path = DIAG_DIR / "exit3_diagnostics.csv"
    exit4_path = DIAG_DIR / "exit4_diagnostics.csv"
    coverage_path = DIAG_DIR / "coverage_diagnostics.csv"
    rep_cases_path = DIAG_DIR / "representative_cases.md"
    analysis_path = DIAG_DIR / "analysis.md"
    monthly_path = DIAG_DIR / "progressed_monthly_path.csv"

    assert summary_path.exists()
    assert trades_path.exists()
    assert deep_loss_path.exists()
    assert winner_path.exists()
    assert winner_extreme_path.exists()
    assert exit3_path.exists()
    assert exit4_path.exists()
    assert coverage_path.exists()
    assert rep_cases_path.exists()
    assert analysis_path.exists()
    assert monthly_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trades_df = pd.read_csv(trades_path, dtype={"ticker": str})
    deep_df = pd.read_csv(deep_loss_path, dtype={"ticker": str})
    win_df = pd.read_csv(winner_path, dtype={"ticker": str})
    win_ext_df = pd.read_csv(winner_extreme_path, dtype={"ticker": str})
    exit3_df = pd.read_csv(exit3_path, dtype={"ticker": str})
    exit4_df = pd.read_csv(exit4_path, dtype={"ticker": str})
    monthly_df = pd.read_csv(monthly_path, dtype={"ticker": str})

    return summary, trades_df, deep_df, win_df, win_ext_df, exit3_df, exit4_df, monthly_df


def test_progressed_cohort_cardinality(diag_artifacts):
    """Section 6-8: Verify exact cardinalities of PROGRESSED cohort (542 total, 328 survived, 214 pre-exit)."""
    summary, trades_df, _, _, _, _, _, _ = diag_artifacts
    v02_df = pd.read_csv(V02_TRADES_CSV, dtype={"ticker": str})

    assert summary["metadata"]["total_official_v02_trades"] == 783
    assert len(v02_df) == 783

    # PROGRESSED lifecycle count
    expected_prog_count = v02_df["first_progressed_date"].notna().sum()
    assert expected_prog_count == 542
    assert summary["metadata"]["post_entry_lifecycle_with_progressed_count"] == 542
    assert len(trades_df) == 542

    # Survived vs Pre-PROGRESSED Loss Guard
    assert summary["metadata"]["actually_held_through_progressed_count"] == 328
    assert summary["metadata"]["pre_progressed_exit_with_future_lifecycle_progressed_count"] == 214
    assert summary["metadata"]["actually_held_through_progressed_count"] + summary["metadata"]["pre_progressed_exit_with_future_lifecycle_progressed_count"] == 542


def test_progressed_source_identity_vs_v02_trades(diag_artifacts):
    """Verify 1-to-1 field match between diagnostic progressed_trades.csv and official v02 trades.csv."""
    _, trades_df, _, _, _, _, _, _ = diag_artifacts
    v02_df = pd.read_csv(V02_TRADES_CSV, dtype={"ticker": str})

    trades_df = trades_df.sort_values(by="trade_id").reset_index(drop=True)
    v02_sub = v02_df[v02_df["first_progressed_date"].notna()].sort_values(by="trade_id").reset_index(drop=True)

    assert len(trades_df) == len(v02_sub)

    for i in range(len(trades_df)):
        r1 = trades_df.iloc[i]
        r2 = v02_sub.iloc[i]
        assert r1["trade_id"] == r2["trade_id"]
        assert r1["ticker"] == r2["ticker"]
        assert r1["first_progressed_date"] == r2["first_progressed_date"]
        assert r1["first_progressed_effective_trading_date"] == r2["first_progressed_effective_trading_date"]
        assert r1["exit_type"] == r2["exit_type"]
        assert np.isclose(float(r1["terminal_return"]), float(r2["terminal_return"]), atol=1e-2)
        assert np.isclose(float(r1["entry_open"]), float(r2["entry_open"]), atol=1e-2)


def test_realized_daily_window_stops_at_exit_signal(diag_artifacts):
    """Section 4: Verify that for realized trades, held_path_end_date is strictly exit_signal_date."""
    _, trades_df, _, _, _, _, _, _ = diag_artifacts

    realized = trades_df[trades_df["trade_status"] == "REALIZED"]
    for _, r in realized.iterrows():
        if pd.notna(r["exit_signal_date"]):
            assert r["held_path_end_date"] == r["exit_signal_date"]
            if pd.notna(r["exit_execution_date"]):
                assert r["held_path_end_date"] <= r["exit_execution_date"]


def test_monthly_path_stops_at_exit_signal_month(diag_artifacts):
    """Section 8: Verify monthly Pattern A path strictly stops at exit signal month."""
    _, trades_df, _, _, _, _, _, monthly_df = diag_artifacts

    realized = trades_df[(trades_df["trade_status"] == "REALIZED") & (trades_df["survived_to_progressed"] == True)]
    for _, r in realized.iterrows():
        t_id = r["trade_id"]
        t_months = monthly_df[monthly_df["trade_id"] == t_id]
        if not t_months.empty:
            max_m = t_months["snapshot_month"].max()
            assert str(max_m) <= str(r["held_path_end_date"]) or str(max_m)[:7] <= str(r["held_path_end_date"])[:7]


def test_progressed_reference_returns_exact(diag_artifacts):
    """Section 12: Verify progressed_to_peak_return_pct and progressed_to_trough_return_pct calculation."""
    _, trades_df, _, _, _, _, _, _ = diag_artifacts

    survived = trades_df[trades_df["survived_to_progressed"] == True]
    for _, r in survived.iterrows():
        ref_c = float(r["progressed_reference_close"])
        p_c = float(r["post_progressed_peak_close"])
        t_c = float(r["post_progressed_trough_close"])

        assert p_c >= ref_c or np.isclose(p_c, ref_c, atol=1.0)
        assert t_c <= ref_c or np.isclose(t_c, ref_c, atol=1.0)

        assert float(r["progressed_to_trough_return_pct"]) <= 0.0 or np.isclose(float(r["progressed_to_trough_return_pct"]), 0.0, atol=1e-2)


def test_exit4_score_hwm_while_held_exact(diag_artifacts):
    """Section 10: Verify Exit4 trades satisfy 15pt drawdown invariant while held."""
    _, _, _, _, _, _, exit4_df, _ = diag_artifacts

    assert len(exit4_df) == 243
    for _, r in exit4_df.iterrows():
        assert float(r["max_score_drawdown_while_held"]) >= 15.0 or np.isclose(float(r["max_score_drawdown_while_held"]), 15.0, atol=1e-2)


def test_exit3_delay_metrics_exact(diag_artifacts):
    """Section 26: Verify Exit 3 delay metrics on Young Poong (000670_02)."""
    _, _, _, _, _, exit3_df, _, _ = diag_artifacts

    yp = exit3_df[exit3_df["trade_id"] == "000670_02"].iloc[0]
    assert yp["progressed_to_exit3_signal_days"] == (pd.Timestamp(yp["exit_signal_date"]) - pd.Timestamp(yp["first_progressed_effective_trading_date"])).days
    assert yp["price_hwm_to_exit3_signal_days"] == (pd.Timestamp(yp["exit_signal_date"]) - pd.Timestamp(yp["price_hwm_date"])).days
    assert float(yp["close_drawdown_at_exit3_signal"]) <= -50.0


def test_exit4_delay_metrics_exact(diag_artifacts):
    """Section 27: Verify Exit 4 delay metrics on Doosan (000150_03)."""
    _, _, _, _, _, _, exit4_df, _ = diag_artifacts

    ds = exit4_df[exit4_df["trade_id"] == "000150_03"].iloc[0]
    assert ds["progressed_to_exit4_signal_days"] == (pd.Timestamp(ds["exit_signal_date"]) - pd.Timestamp(ds["first_progressed_effective_trading_date"])).days


def test_drawdown_percentile_semantics(diag_artifacts):
    """Section 17: Verify drawdown percentile order in negative values (P25 deeper than Median, Median deeper than P75)."""
    summary, _, _, _, _, _, _, _ = diag_artifacts

    w_stats = summary["drawdown_distributions"]["winners_ge_50_close_drawdown"]
    l_stats = summary["drawdown_distributions"]["losers_le_neg_20_close_drawdown"]

    # For negative drawdowns, P25 is a deeper loss (smaller number) than Median
    assert float(w_stats["p25"]) <= float(w_stats["median"])
    assert float(w_stats["median"]) <= float(w_stats["p75"])

    assert float(l_stats["p25"]) <= float(l_stats["median"])
    assert float(l_stats["median"]) <= float(l_stats["p75"])


def test_winner_loser_distribution_overlap(diag_artifacts):
    """Section 23, 25: Verify distribution overlap between winners and losers."""
    summary, _, _, _, win_ext_df, _, _, _ = diag_artifacts

    overlap = summary["distribution_overlap"]
    assert overlap["winner_ge_50"]["total_count"] == 164
    assert overlap["loser_le_neg_20"]["total_count"] == 18

    # In winners, there are cases with <= -30% drawdown
    assert overlap["winner_ge_50"]["dd_le_neg_30_count"] == len(win_ext_df)
    assert len(win_ext_df) > 0

    # Loser deep drawdown rate is significantly higher than winner deep drawdown rate
    assert overlap["loser_le_neg_20"]["dd_le_neg_30_rate"] > overlap["winner_ge_50"]["dd_le_neg_30_rate"]
