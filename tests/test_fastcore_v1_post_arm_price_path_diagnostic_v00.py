"""Focused tests for the post-ARM price-path distribution diagnostic."""

from __future__ import annotations

import inspect
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from scripts import analyze_fastcore_v1_post_arm_price_path_diagnostic_v00 as diagnostic


ROOT = Path(__file__).resolve().parents[1]


def _row(recovery_class: str = "NEVER_WINNER", effective_to: str = "2021-01-20") -> dict[str, object]:
    return {
        "ticker": "000001",
        "name": "TEST",
        "market": "KOSPI",
        "isu_cd": "KR7000000001",
        "control_trade_id": "TEST_CONTROL_01",
        "control_trade_sequence": 1,
        "entry_execution_date": "2021-01-04",
        "entry_open": 100.0,
        "identity_effective_from": "2021-01-04",
        "identity_effective_to": effective_to,
        "strategy_id": "FASTCORE_V1_W25_PREWINNER_ARMED_V00",
        "price_damage_threshold_pct": -25.0,
        "recovery_class": recovery_class,
        "v2_loss_guard_triggered": False,
    }


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).assign(
        date=lambda frame: pd.to_datetime(frame["date"])
    ).set_index("date")


def _diagnose(
    rows: list[tuple[str, float, float, float, float]],
    states: list[tuple[str, str]],
    recovery_class: str = "NEVER_WINNER",
    effective_to: str = "2021-01-20",
):
    row = _row(recovery_class, effective_to)
    daily = _daily(rows)
    date_states = [(pd.Timestamp(date), state) for date, state in states]
    return diagnostic._diagnose_cycle(
        row, pd.Timestamp("2021-01-05"), pd.Timestamp("2021-01-04"), "WATCH", -27.0, 10.0,
        {"000001": daily}, {diagnostic.v0_ab._identity_key(row): date_states},
        "PRIMARY_FIRST_ARM", "ARMED", 1,
    )


def test_first_arm_only_and_anchor_parity_contract_from_existing_artifact() -> None:
    matched = pd.read_csv(diagnostic.ARMED_MATCHED_PATH)
    events = pd.read_csv(diagnostic.ARMED_EVENT_PATH)
    for strategy_id, expected in diagnostic.EXPECTED_FIRST_ARM_COUNTS.items():
        group = matched.loc[matched["strategy_id"] == strategy_id]
        first = group.loc[group["first_armed_date"].notna()]
        first_events = events.loc[(events["strategy_id"] == strategy_id) & (events["event_type"] == "ARMED")]
        assert len(first) == expected
        assert first_events["control_trade_id"].nunique() == expected
        expected_dates = first.set_index("control_trade_id")["first_armed_date"]
        actual_dates = first_events.sort_values("date").drop_duplicates("control_trade_id").set_index("control_trade_id")["date"]
        assert expected_dates.to_dict() == actual_dates.to_dict()


def test_next_usable_fast_skips_unavailable_and_missing_is_null() -> None:
    states = [(pd.Timestamp("2021-01-04"), "WATCH"), (pd.Timestamp("2021-01-08"), "UNAVAILABLE"), (pd.Timestamp("2021-01-15"), "TRIGGER")]
    assert diagnostic._next_usable(states, pd.Timestamp("2021-01-04")) == (pd.Timestamp("2021-01-15"), "TRIGGER", 1)
    assert diagnostic._next_usable([(pd.Timestamp("2021-01-04"), "WATCH"), (pd.Timestamp("2021-01-08"), "UNAVAILABLE")], pd.Timestamp("2021-01-04")) == (None, None, 1)


def test_next_fast_delta_sign_and_additional_deterioration() -> None:
    result = _diagnose(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 73),
            ("2021-01-08", 70, 90, 60, 76),
            ("2021-01-15", 76, 80, 65, 76),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")],
    )
    assert result["next_fast_close_return_pct"] == -24.0
    assert result["arm_to_next_fast_delta_pp"] == 3.0
    assert result["min_close_return_after_arm_to_next_fast_pct"] == -24.0
    assert result["additional_close_deterioration_pp"] == 0.0

    worse = _diagnose(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 73),
            ("2021-01-08", 70, 90, 65, 66),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")],
    )
    assert worse["arm_to_next_fast_delta_pp"] == -7.0
    assert worse["additional_close_deterioration_pp"] == 7.0


def test_short_interval_excludes_arm_day_and_low_is_secondary() -> None:
    result = _diagnose(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 73),
            ("2021-01-06", 73, 90, 50, 72),
            ("2021-01-08", 70, 90, 65, 76),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")],
    )
    assert result["min_close_return_after_arm_to_next_fast_pct"] == -28.0
    assert result["min_close_date_after_arm_to_next_fast"] == "2021-01-06"
    assert result["additional_close_deterioration_pp"] == 1.0
    assert result["min_low_return_after_arm_to_next_fast_pct"] == -50.0
    assert result["additional_low_deterioration_pp"] == 23.0


def test_recovery_horizon_excludes_first_mfe20_day_but_keeps_prior_path() -> None:
    result = _diagnose(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 73),
            ("2021-01-06", 73, 90, 60, 65),
            ("2021-01-07", 65, 80, 55, 60),
            ("2021-01-08", 60, 120, 40, 50),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")], "RECOVERY",
    )
    assert result["first_mfe20_date"] == "2021-01-08"
    assert result["long_horizon_end_date"] == "2021-01-07"
    assert result["long_horizon_end_reason"] == "BEFORE_FIRST_MFE20"
    assert result["post_arm_long_min_close_return_pct"] == -40.0
    assert result["post_arm_long_min_close_date"] == "2021-01-07"
    assert result["post_arm_long_additional_close_deterioration_pp"] == 13.0


def test_first_mfe20_uses_raw_boundary_not_display_rounding() -> None:
    below = _daily([
        ("2021-01-04", 100, 119.996, 100, 100),
    ])
    exact = _daily([
        ("2021-01-04", 100, 120.0, 100, 100),
    ])
    assert diagnostic._first_mfe20_date(below, pd.Timestamp("2021-01-04"), 100.0) is None
    assert diagnostic._first_mfe20_date(exact, pd.Timestamp("2021-01-04"), 100.0) == pd.Timestamp("2021-01-04")
    assert "round(" not in inspect.getsource(diagnostic._first_mfe20_date)


def test_never_winner_uses_identity_end_and_does_not_truncate_after_virtual_exit() -> None:
    result = _diagnose(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 73),
            ("2021-01-08", 70, 80, 40, 50),
            ("2021-01-11", 50, 60, 30, 40),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")], "NEVER_WINNER", "2021-01-11",
    )
    assert result["long_horizon_end_date"] == "2021-01-11"
    assert result["long_horizon_end_reason"] == "IDENTITY_END"
    assert result["post_arm_long_min_close_return_pct"] == -60.0
    assert result["post_arm_long_min_close_date"] == "2021-01-11"


def test_no_label_leakage_and_exact_fast_domain() -> None:
    assert "recovery_class" not in inspect.signature(diagnostic._min_path_metrics).parameters
    assert "recovery_class" not in inspect.getsource(diagnostic._min_path_metrics)
    accepted = diagnostic._state_domain(Counter(diagnostic.EXPECTED_STATE_COUNTS))
    assert set(accepted["observed_states"]) == diagnostic.ALLOWED_STATES
    with pytest.raises(RuntimeError):
        diagnostic._state_domain(Counter({**diagnostic.EXPECTED_STATE_COUNTS, "UNKNOWN_TEST_STATE": 1}))


def test_primary_artifact_contract_if_present() -> None:
    if not diagnostic.OUT_DIR.exists():
        pytest.skip("runner artifact is created by the integration execution")
    expected = {
        "first_arm_trade_diagnostics.csv",
        "first_arm_next_fast_distribution.csv",
        "first_arm_long_horizon_distribution.csv",
        "first_arm_descriptive_bins.csv",
        "first_arm_next_fast_state_distribution.csv",
        "all_observed_arm_cycle_diagnostics.csv",
        "fastcore_v1_post_arm_price_path_diagnostic_v00_summary.json",
        "fastcore_v1_post_arm_price_path_diagnostic_v00_report.md",
    }
    assert {path.name for path in diagnostic.OUT_DIR.iterdir()} == expected
    summary = json.loads(diagnostic.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETE"
    assert summary["first_arm_counts"] == diagnostic.EXPECTED_FIRST_ARM_COUNTS
    assert summary["state_domain"]["observed_counts"] == diagnostic.EXPECTED_STATE_COUNTS
    assert summary["state_domain"]["weekly_evaluation_error_count"] == 0
    assert summary["network_requests"] == 0
    assert summary["next_usable_fast_missing_count"] == 1
    assert summary["secondary_cycle_rows"] == 1012
    assert summary["short_horizon_separation_conclusion"] == "POST_ARM_SHORT_HORIZON_SHOWS_NO_USEFUL_SEPARATION"
    assert summary["long_horizon_separation_conclusion"] == "POST_ARM_LONG_HORIZON_SHOWS_RETROSPECTIVE_SEPARATION"
    assert summary["separation_conclusion"] == "POST_ARM_IMMEDIATE_DETERIORATION_NOT_USEFUL_FOR_FAILURE_CONFIRM"
    assert summary["first_mfe20_boundary_semantics"] == "RAW_RUNNING_MFE_GE_20"
    assert summary["first_mfe20_boundary_parity_compared_count"] == 648
    assert summary["first_mfe20_boundary_parity_match_count"] == 648
    assert summary["first_mfe20_boundary_parity_mismatch_count"] == 0
    assert summary["first_mfe20_boundary_parity_mismatches"] == []
    assert summary["threshold_selected"] is False
    assert summary["new_backtest"] is False
    assert ">= 5.0" not in inspect.getsource(diagnostic)
    assert len(pd.read_csv(diagnostic.TRADE_PATH)) == 648
    assert len(pd.read_csv(diagnostic.CYCLE_PATH)) == 1012
