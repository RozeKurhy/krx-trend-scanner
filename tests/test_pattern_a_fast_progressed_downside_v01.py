"""Targeted Invariant and Diagnostic Consistency Tests for PROGRESSED Downside Protection Phase 1."""

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
    exit3_path = DIAG_DIR / "exit3_diagnostics.csv"
    exit4_path = DIAG_DIR / "exit4_diagnostics.csv"
    coverage_path = DIAG_DIR / "coverage_diagnostics.csv"
    rep_cases_path = DIAG_DIR / "representative_cases.md"
    analysis_path = DIAG_DIR / "analysis.md"

    assert summary_path.exists()
    assert trades_path.exists()
    assert deep_loss_path.exists()
    assert winner_path.exists()
    assert exit3_path.exists()
    assert exit4_path.exists()
    assert coverage_path.exists()
    assert rep_cases_path.exists()
    assert analysis_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trades_df = pd.read_csv(trades_path, dtype={"ticker": str})
    deep_df = pd.read_csv(deep_loss_path, dtype={"ticker": str})
    win_df = pd.read_csv(winner_path, dtype={"ticker": str})

    return summary, trades_df, deep_df, win_df


def test_progressed_cohort_cardinality(diag_artifacts):
    """Verify exact cardinalities of PROGRESSED reached cohort."""
    summary, trades_df, deep_df, win_df = diag_artifacts
    v02_df = pd.read_csv(V02_TRADES_CSV, dtype={"ticker": str})

    assert summary["metadata"]["total_official_v02_trades"] == 783
    assert len(v02_df) == 783

    # PROGRESSED reached count
    expected_prog_count = v02_df["first_progressed_date"].notna().sum()
    assert expected_prog_count == 542
    assert summary["metadata"]["progressed_reached_trades"] == 542
    assert len(trades_df) == 542

    # Unique tickers
    assert summary["metadata"]["progressed_unique_tickers"] == 373

    # Survived vs Pre-PROGRESSED Loss Guard
    assert summary["metadata"]["survived_active_holding_trades"] == 328
    assert summary["metadata"]["pre_progressed_loss_guard_trades"] == 214
    assert summary["metadata"]["survived_active_holding_trades"] + summary["metadata"]["pre_progressed_loss_guard_trades"] == 542


def test_progressed_source_identity_vs_v02_trades(diag_artifacts):
    """Verify 1-to-1 field match between diagnostic progressed_trades.csv and official v02 trades.csv."""
    _, trades_df, _, _ = diag_artifacts
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


def test_winner_vs_loser_separation_invariant(diag_artifacts):
    """Verify that big winners and deep losers exhibit statistically meaningful drawdown separation."""
    summary, trades_df, _, _ = diag_artifacts

    dd = summary["drawdown_distributions"]
    w50_med = dd["winners_ge_50_close_drawdown"]["median"]
    l20_med = dd["losers_le_neg_20_close_drawdown"]["median"]

    assert w50_med is not None
    assert l20_med is not None

    # Big winners suffer far smaller drawdowns than deep losers
    assert abs(w50_med) < abs(l20_med)
    assert abs(w50_med) < 25.0  # Median drawdown of winners is around -17%
    assert abs(l20_med) > 40.0  # Median drawdown of losers is around -44.6%

    assert summary["diagnostic_conclusion"] == "PROGRESSED_DOWNSIDE_SEPARATION_OBSERVED"
    assert summary["price_based_protection_worth_phase2"] == "YES"


def test_representative_cases_drawdown_exactness(diag_artifacts):
    """Verify exact post-PROGRESSED drawdown values on representative losing cases."""
    _, trades_df, _, _ = diag_artifacts

    # 1. 011170_02 (Lotte Chemical)
    lotte = trades_df[trades_df["trade_id"] == "011170_02"].iloc[0]
    assert lotte["terminal_return"] == -77.72
    assert lotte["max_close_hwm_drawdown"] <= -80.0
    assert lotte["trade_status"] == "OPEN_AT_CUTOFF"

    # 2. 000670_02 (Young Poong)
    yp = trades_df[trades_df["trade_id"] == "000670_02"].iloc[0]
    assert yp["terminal_return"] == -45.64
    assert yp["exit_type"] == "EXIT3_PROGRESSED_TO_WEAK"
    assert yp["max_close_hwm_drawdown"] <= -45.0

    # 3. 200670_03 (Humedix)
    humedix = trades_df[trades_df["trade_id"] == "200670_03"].iloc[0]
    assert humedix["terminal_return"] == -36.51
    assert humedix["exit_type"] == "EXIT3_PROGRESSED_TO_WEAK"

    # 4. 298380_02 (ABL Bio)
    abl = trades_df[trades_df["trade_id"] == "298380_02"].iloc[0]
    assert abl["terminal_return"] == -31.34
    assert abl["exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15"
