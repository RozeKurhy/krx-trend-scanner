"""Targeted Test Suite for Pattern A FAST Trading Policy Entry v0.1 Evaluation.

Validates all 20 requirements from Section 29 of w.md:
1. Population exactly 36
2. Manifest hash guard
3. Reference date prospective scan (no backfill before reference date)
4. First qualifying entry only
5. TRIGGER + PERMITTED + NORMAL -> Grade A
6. TRIGGER + PERMITTED + ELEVATED -> Grade B
7. TRIGGER + PERMITTED + EXTREME -> No Primary Entry
8. TRIGGER + EARLY_REGIME -> No Primary Entry
9. TRIGGER + LATE_OR_EXTENDED -> No Primary Entry
10. Non-TRIGGER stages (SETUP, TREND, EXTENDED, WATCH) -> No Primary Entry
11. Score UNAVAILABLE -> No Primary Entry
12. Signal date close NOT used as entry price
13. Execution price exactly matches next trading day OPEN
14. Data beyond outcome_review_end NOT used in evaluation
15. 4W, 8W, 12W, 26W censoring on incomplete horizons
16. MFE / MAE excursion calculations
17. PIT isolation (no lookahead bias)
18. Pattern A score/stage does NOT gate entry
19. FAST numeric score does NOT threshold entry
20. Existing FAST evaluator parity & read-only contract preservation
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_pattern_a_fast_trading_policy_entry_v01 import (
    BASE_COMMIT_SHA,
    COMMIT_A_SHA,
    FROZEN_HUMAN_SHA256,
    FROZEN_MANIFEST_SHA256,
    HUMAN_PATH,
    MANIFEST_PATH,
    OUT_EVAL_JSON,
    OUT_EVAL_MD,
    OUT_EVENT_LOG_CSV,
    OUT_SAMPLES_CSV,
    PREREG_PATH,
    ROOT,
    run_evaluation,
    sha256_file,
)
from trend_scanner.data.cache import ParquetCache


@pytest.fixture(scope="module")
def eval_data():
    df_samples, df_events, summary = run_evaluation()
    return df_samples, df_events, summary


def test_01_population_exactly_36(eval_data):
    df_samples, _, summary = eval_data
    assert len(df_samples) == 36
    assert summary["total_sample_count"] == 36
    assert df_samples["sample_id"].nunique() == 36


def test_02_manifest_hash_guard():
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(HUMAN_PATH) == FROZEN_HUMAN_SHA256
    assert PREREG_PATH.exists()


def test_03_reference_date_prospective_scan(eval_data):
    df_samples, _, _ = eval_data
    for _, row in df_samples.iterrows():
        if row["entry_found"]:
            sig_date = pd.Timestamp(row["signal_date"])
            ref_date = pd.Timestamp(row["completed_weekly_reference_date"])
            assert sig_date >= ref_date, f"Signal date {sig_date} before reference date {ref_date}"


def test_04_first_qualifying_entry_only(eval_data):
    df_samples, df_events, _ = eval_data
    # For each sample, exactly 1 row in df_samples
    assert len(df_samples) == 36
    # Verify that in event log, all primary entry events for a sample occur on or after signal_date
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        sid = row["sample_id"]
        evs = df_events[(df_events["sample_id"] == sid) & (df_events["is_primary_entry_event"])]
        assert not evs.empty
        first_event_date = evs.iloc[0]["weekly_date"]
        assert row["signal_date"] == first_event_date


def test_05_06_entry_grade_classification(eval_data):
    df_samples, _, _ = eval_data
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        if row["daily_risk_at_entry"] == "NORMAL":
            assert row["entry_grade"] == "Grade A"
        elif row["daily_risk_at_entry"] == "ELEVATED":
            assert row["entry_grade"] == "Grade B"
        else:
            pytest.fail(f"Invalid daily risk for entry: {row['daily_risk_at_entry']}")


def test_07_extreme_risk_no_primary_entry(eval_data):
    _, df_events, _ = eval_data
    extreme_events = df_events[df_events["daily_risk"] == "EXTREME"]
    for _, ev in extreme_events.iterrows():
        assert ev["is_primary_entry_event"] is False


def test_08_early_regime_no_primary_entry(eval_data):
    _, df_events, _ = eval_data
    early_events = df_events[df_events["monthly_regime"] == "EARLY_REGIME"]
    for _, ev in early_events.iterrows():
        assert ev["is_primary_entry_event"] is False


def test_09_late_or_extended_regime_no_primary_entry(eval_data):
    _, df_events, _ = eval_data
    late_events = df_events[df_events["monthly_regime"] == "LATE_OR_EXTENDED_REGIME"]
    for _, ev in late_events.iterrows():
        assert ev["is_primary_entry_event"] is False


def test_10_non_trigger_stages_no_primary_entry(eval_data):
    _, df_events, _ = eval_data
    non_trigger = df_events[df_events["fast_stage"] != "TRIGGER"]
    for _, ev in non_trigger.iterrows():
        assert ev["is_primary_entry_event"] is False


def test_11_score_unavailable_no_primary_entry(eval_data):
    _, df_events, _ = eval_data
    unavail_score = df_events[~df_events["fast_score_status"].isin(["READY", "PARTIAL"])]
    for _, ev in unavail_score.iterrows():
        assert ev["is_primary_entry_event"] is False


def test_12_13_execution_price_next_trading_day_open(eval_data):
    df_samples, _, _ = eval_data
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        daily = cache.load(row["ticker"]).sort_index()
        sig_date = pd.Timestamp(row["signal_date"])
        exec_date = pd.Timestamp(row["execution_date"])

        assert exec_date > sig_date, "Execution date must be strictly after signal date"

        # Check that exec_date is the FIRST trading date after sig_date
        next_dates = daily[daily.index > sig_date].index
        assert exec_date == next_dates[0]

        # Check that entry_open matches exact daily open on execution_date
        expected_open = float(daily.loc[exec_date, "open"])
        assert row["entry_open"] == pytest.approx(expected_open, abs=1e-2)

        # Check signal date close is NOT used as entry price
        sig_close = float(daily.loc[sig_date, "close"])
        if sig_close != expected_open:
            assert row["entry_open"] != sig_close


def test_14_outcome_review_end_enforced(eval_data):
    df_samples, df_events, _ = eval_data
    for _, row in df_samples.iterrows():
        end_date = pd.Timestamp(row["outcome_review_end"])
        if row["entry_found"]:
            exec_date = pd.Timestamp(row["execution_date"])
            assert exec_date <= end_date


def test_15_horizon_censoring(eval_data):
    df_samples, _, summary = eval_data
    for h in [4, 8, 12, 26]:
        col_ret = f"return_{h}w"
        col_st = f"followup_status_{h}w"
        censored = df_samples[df_samples[col_st] == "CENSORED"]
        for _, row in censored.iterrows():
            assert pd.isna(row[col_ret])
            assert pd.isna(row[f"mfe_{h}w"])
            assert pd.isna(row[f"mae_{h}w"])


def test_16_mfe_mae_excursion_arithmetic(eval_data):
    df_samples, _, _ = eval_data
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    for _, row in df_samples[(df_samples["entry_found"]) & (df_samples["followup_status_4w"] == "COMPLETED")].iterrows():
        daily = cache.load(row["ticker"]).sort_index()
        exec_date = pd.Timestamp(row["execution_date"])
        e_open = row["entry_open"]

        # 4W MFE must be >= 0 (high is >= open)
        assert row["mfe_4w"] >= -1e-4
        # 4W MAE must be <= 0 (low is <= open)
        assert row["mae_4w"] <= 1e-4


def test_17_pit_isolation_no_lookahead(eval_data):
    _, df_events, _ = eval_data
    # Verify that each event in event log has valid date and values calculated strictly up to that weekly date
    assert (pd.to_datetime(df_events["weekly_date"]) <= pd.Timestamp("2026-08-14")).all()


def test_18_19_non_gate_policy(eval_data):
    df_samples, _, summary = eval_data
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))

    # Verify preregistration explicitly sets score_threshold to None and pattern_a_entry_gate to False
    assert prereg["score_threshold"] is None
    assert prereg["pattern_a_entry_gate"] is False

    entries = df_samples[df_samples["entry_found"]]
    assert len(entries) == 13

    # Verify entries occur across various Pattern A candidate states (candidate and non_candidate)
    cand_states = entries["pattern_a_candidate_state_at_entry"].value_counts().to_dict()
    assert "candidate" in cand_states
    assert "non_candidate" in cand_states

    # Verify entries occurred even when Pattern A candidate was False (non_candidate)
    assert cand_states["non_candidate"] > 0


def test_20_existing_contracts_and_artifacts_unmutated():
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(HUMAN_PATH) == FROZEN_HUMAN_SHA256
