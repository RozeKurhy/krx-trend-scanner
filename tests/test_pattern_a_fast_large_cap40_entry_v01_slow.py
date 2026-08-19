"""SLOW Integration Test Suite for Pattern A FAST Trading Policy Entry v0.1 Large Cap 40 Diagnostic.

This suite performs full-scale re-evaluation across all 40 large-cap stocks over the
5-year observation window (2021-08-14 ~ 2026-08-14) to verify:
1. End-to-end reproducibility of evaluation results from scratch against committed artifacts.
2. Full PIT (Point-in-Time) input isolation on all 40 stocks and every eligible weekly bar.

Execution policy:
- Excluded from standard fast maintenance runs.
- Run only when evaluation logic, resampling, or trading contracts are modified, or for final re-sealing:
  `uv run pytest tests/test_pattern_a_fast_large_cap40_entry_v01_slow.py -v`
"""

import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.evaluate_pattern_a_fast_large_cap40_entry_v01 as eval_script
from scripts.evaluate_pattern_a_fast_large_cap40_entry_v01 import (
    DATA_CUTOFF,
    run_evaluation,
)

pytestmark = pytest.mark.slow


def test_slow_01_full_run_evaluation_reproduction():
    """Execute run_evaluation from scratch and assert complete reproduction of frozen research results."""
    df_samples, df_events, summary = run_evaluation()

    assert len(df_samples) == 40
    assert summary["coverage"]["entry_count"] == 40
    assert summary["coverage"]["grade_counts"]["Grade A"] == 37
    assert summary["coverage"]["grade_counts"]["Grade B"] == 3

    # Primary Forward Return Medians
    fwd = summary["primary_forward_returns"]
    assert fwd["4w"]["median"] == -1.51
    assert fwd["8w"]["median"] == -0.69
    assert fwd["12w"]["median"] == 0.90
    assert fwd["26w"]["median"] == -0.51

    # Early Variant & Control counts
    assert summary["experimental_early_variant"]["entry_count"] == 7
    assert summary["trigger_any_control"]["entry_count"] == 40

    # Pattern A Diagnostic breakdown
    pa = summary["pattern_a_diagnostic"]
    assert pa["candidate_state_distribution"]["candidate"] == 16
    assert pa["candidate_state_distribution"]["non_candidate"] == 24
    assert pa["stage_available_count"] == 30
    assert pa["stage_unavailable_count"] == 10
    assert pa["stage_distribution"]["transition"] == 14
    assert pa["stage_distribution"]["weak"] == 6
    assert pa["stage_distribution"]["progressed"] == 5
    assert pa["stage_distribution"]["base"] == 3
    assert pa["stage_distribution"]["early_trend"] == 2


def test_slow_02_full_pit_interception_all_40_stocks(monkeypatch):
    """Full-scale PIT interception on every single weekly bar evaluation across all 40 stocks."""
    original_fn = eval_script.evaluate_pattern_a_fast
    interceptions = []

    def wrapped_evaluate(ticker, name, daily, weekly_date, score, stage):
        w_norm = pd.Timestamp(weekly_date).normalize()
        # Ensure daily data fed into evaluator does not extend past weekly_date
        assert daily.index.max().normalize() <= w_norm, f"PIT lookahead violation on {ticker} at {weekly_date}"
        assert daily[daily.index > pd.Timestamp(weekly_date)].empty, f"Future bars present for {ticker} at {weekly_date}"
        assert daily.index.max().normalize() <= DATA_CUTOFF, f"Data cutoff exceeded for {ticker}"
        assert w_norm <= DATA_CUTOFF, f"Weekly date {weekly_date} exceeds data cutoff"

        interceptions.append((ticker, weekly_date))
        return original_fn(ticker, name, daily, weekly_date, score, stage)

    monkeypatch.setattr(eval_script, "evaluate_pattern_a_fast", wrapped_evaluate)
    df_samples, df_events, summary = eval_script.run_evaluation()

    assert len(interceptions) > 0
    assert len(interceptions) == len(df_events)
    assert len(df_samples) == 40
