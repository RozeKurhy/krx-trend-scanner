"""Focused contract checks for the pre-winner FAILURE ARMED matched A/B."""

from __future__ import annotations

import inspect
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from scripts import analyze_fastcore_v1_prewinner_failure_armed_ab_v00 as analysis


ROOT = Path(__file__).resolve().parents[1]


def _row(entry_date: str = "2021-01-04", effective_to: str = "2021-01-20") -> dict[str, object]:
    return {
        "ticker": "000001",
        "name": "TEST",
        "market": "KOSPI",
        "isu_cd": "KR7000000001",
        "control_trade_id": "TEST_CONTROL_01",
        "control_trade_sequence": 1,
        "entry_execution_date": entry_date,
        "entry_open": 100.0,
        "identity_effective_from": entry_date,
        "identity_effective_to": effective_to,
    }


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).assign(
        date=lambda frame: pd.to_datetime(frame["date"])
    ).set_index("date")


def _run(
    rows: list[tuple[str, float, float, float, float]],
    states: list[tuple[str, str]], config: analysis.VariantConfig = analysis.V1_W25,
    row: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    return analysis.simulate_failure_armed(
        row or _row(), _daily(rows), [(pd.Timestamp(date), state) for date, state in states], config,
    )


def test_w25_arm_is_not_an_exit_and_same_week_cannot_confirm() -> None:
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 75),
            ("2021-01-06", 74, 100, 70, 74),
        ], [("2021-01-04", "WATCH")],
    )
    assert [event["event_type"] for event in events] == ["ARMED"]
    assert result["v1_trade_status"] == "OPEN_AT_CUTOFF"
    assert result["prewinner_failure_confirmed_date"] is None


def test_w30_boundary_is_inclusive_and_w25_w30_only_differ_by_threshold() -> None:
    rows = [
        ("2021-01-04", 100, 100, 100, 100),
        ("2021-01-05", 100, 100, 70, 70),
    ]
    exact_result, exact_events = _run(rows, [("2021-01-04", "WATCH")], analysis.V1_W30)
    assert exact_result["prewinner_arm_cycles"] == 1
    assert exact_events[0]["event_type"] == "ARMED"
    near_rows = rows[:-1] + [("2021-01-05", 100, 100, 70, 70.01)]
    near_result, near_events = _run(near_rows, [("2021-01-04", "WATCH")], analysis.V1_W30)
    assert near_result["prewinner_arm_cycles"] == 0
    assert near_events == []
    w25, w30 = asdict(analysis.V1_W25), asdict(analysis.V1_W30)
    assert {key: value for key, value in w25.items() if key not in {"strategy_id", "price_damage_threshold_pct"}} == {
        key: value for key, value in w30.items() if key not in {"strategy_id", "price_damage_threshold_pct"}
    }
    assert w25["strategy_id"] != w30["strategy_id"]
    assert w25["price_damage_threshold_pct"] == -25.0
    assert w30["price_damage_threshold_pct"] == -30.0


def test_new_weak_fast_and_damaged_price_confirms_then_uses_next_open() -> None:
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 69, 90, 65, 70),
            ("2021-01-11", 60, 70, 55, 65),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")],
    )
    assert result["prewinner_failure_confirmed_date"] == "2021-01-08"
    assert result["v1_exit_reason"] == "PREWINNER_FAILURE_CONFIRMED"
    assert result["v1_exit_execution_date"] == "2021-01-11"
    assert [event["event_type"] for event in events] == ["ARMED", "FAILURE_CONFIRMED", "EXIT_EXECUTED"]


def test_price_fast_and_both_recovery_disarm_without_exit() -> None:
    base = [
        ("2021-01-04", 100, 100, 100, 100),
        ("2021-01-05", 100, 100, 70, 70),
        ("2021-01-08", 100, 100, 70, 80),
    ]
    _, price_events = _run(base, [("2021-01-04", "WATCH"), ("2021-01-08", "WATCH")])
    assert price_events[-1]["event_type"] == "DISARM_PRICE"
    fast_rows = base[:-1] + [("2021-01-08", 70, 100, 65, 70)]
    _, fast_events = _run(fast_rows, [("2021-01-04", "WATCH"), ("2021-01-08", "TREND")])
    assert fast_events[-1]["event_type"] == "DISARM_FAST"
    _, both_events = _run(base, [("2021-01-04", "WATCH"), ("2021-01-08", "TREND")])
    assert both_events[-1]["event_type"] == "DISARM_BOTH"


def test_trigger_is_strong_cannot_arm_and_disarms_new_week_without_confirming() -> None:
    no_arm_result, no_arm_events = _run(
        [
            ("2021-01-04", 100, 100, 70, 70),
            ("2021-01-05", 70, 90, 65, 70),
        ], [("2021-01-04", "TRIGGER")],
    )
    assert no_arm_result["prewinner_arm_cycles"] == 0
    assert no_arm_events == []

    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 70, 90, 65, 70),
            ("2021-01-11", 70, 90, 65, 70),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "TRIGGER")],
    )
    assert result["prewinner_failure_confirmed_date"] is None
    assert result["v1_exit_reason"] == "OPEN_AT_CUTOFF"
    assert result["prewinner_disarm_by_fast_count"] == 1
    assert [event["event_type"] for event in events] == ["ARMED", "DISARM_FAST"]


def test_extended_recovery_disarms_and_fast_domain_is_exact() -> None:
    rows = [
        ("2021-01-04", 100, 100, 100, 100),
        ("2021-01-05", 100, 100, 70, 70),
        ("2021-01-08", 70, 90, 65, 70),
    ]
    result, events = _run(rows, [("2021-01-04", "WATCH"), ("2021-01-08", "EXTENDED")])
    assert result["prewinner_disarm_by_fast_count"] == 1
    assert events[-1]["event_type"] == "DISARM_FAST"
    accepted = analysis.validate_fast_state_domain(Counter({state: 1 for state in analysis.ALLOWED_FAST_STATES}))
    assert set(accepted["observed_states"]) == analysis.ALLOWED_FAST_STATES
    with pytest.raises(RuntimeError, match="UNKNOWN_TEST_STATE"):
        analysis.validate_fast_state_domain(Counter({"UNKNOWN_TEST_STATE": 1}))


def test_unavailable_wait_does_not_confirm_or_advance_arm_fast_date() -> None:
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 70, 90, 65, 70),
            ("2021-01-11", 70, 90, 65, 70),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "UNAVAILABLE")],
    )
    assert result["prewinner_failure_confirmed_date"] is None
    assert result["prewinner_unavailable_wait_count"] == 1
    assert [event["event_type"] for event in events] == ["ARMED", "UNAVAILABLE_WAIT"]


def test_mfe20_precedence_clears_armed_state_and_uses_v0_winner_exit() -> None:
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 70, 121, 60, 60),
            ("2021-01-11", 60, 70, 55, 65),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "SETUP")],
    )
    assert result["winner_mode_activated"] is True
    assert result["prewinner_failure_confirmed_date"] is None
    assert result["v1_exit_reason"] == "HARD_EXIT"
    assert "WINNER_MODE_ACTIVATED" in [event["event_type"] for event in events]


def test_rearm_is_allowed_after_disarm_with_no_cooldown() -> None:
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 70, 90, 65, 70),
            ("2021-01-11", 70, 90, 65, 70),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "TREND"), ("2021-01-11", "WATCH")],
    )
    assert result["prewinner_arm_cycles"] == 2
    assert [event["event_type"] for event in events] == ["ARMED", "DISARM_FAST", "REARM"]


def test_identity_boundary_and_support_end_confirmations_are_unexecuted() -> None:
    bounded_row = _row(effective_to="2021-01-08")
    result, events = _run(
        [
            ("2021-01-04", 100, 100, 100, 100),
            ("2021-01-05", 100, 100, 70, 70),
            ("2021-01-08", 70, 90, 65, 70),
            ("2021-01-11", 60, 70, 55, 65),
        ], [("2021-01-04", "WATCH"), ("2021-01-08", "WATCH")], row=bounded_row,
    )
    assert result["v1_trade_status"] == "OPEN_AT_CUTOFF"
    assert result["v1_unexecuted_exit_signal_date"] == "2021-01-08"
    assert events[-1]["event_type"] == "EXIT_UNEXECUTED"

    late_row = _row(entry_date="2026-08-20", effective_to="2026-08-21")
    late_result, late_events = _run(
        [
            ("2026-08-20", 100, 100, 70, 70),
            ("2026-08-21", 100, 100, 70, 70),
        ], [("2026-08-20", "WATCH"), ("2026-08-21", "WATCH")], row=late_row,
    )
    assert late_result["v1_unexecuted_exit_signal_date"] == "2026-08-21"
    assert late_events[-1]["event_type"] == "EXIT_UNEXECUTED"


def test_retrospective_labels_cannot_be_signal_inputs() -> None:
    parameters = inspect.signature(analysis.simulate_failure_armed).parameters
    assert "recovery_class" not in parameters
    assert "never_winner" not in parameters
    assert "prewinner_trade_diagnostics" not in inspect.getsource(analysis.simulate_failure_armed)


def test_completed_artifact_has_required_outputs_and_parity() -> None:
    expected = {
        "matched_v0_vs_v1w25_vs_v1w30.csv",
        "failure_armed_event_log.csv",
        "failure_armed_variant_summary.csv",
        "failure_armed_cohort_diagnostics.csv",
        "failure_armed_exit_reason_diagnostics.csv",
        "fastcore_v1_prewinner_failure_armed_ab_v00_summary.json",
        "fastcore_v1_prewinner_failure_armed_ab_v00_report.md",
    }
    assert analysis.OUT_DIR.exists()
    assert {path.name for path in analysis.OUT_DIR.iterdir()} == expected
    summary = json.loads(analysis.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["matched_control_rows"] == 973
    assert summary["loss_guard_subset_count"] == 590
    assert summary["v0_disabled_parity"]["passed"] is True
    assert summary["variant_entry_parity"]["passed"] is True
    assert summary["retrospective_labels_analysis_only"] is True
    assert summary["network_requests"] == 0
    assert set(summary["fast_state_domain"]["observed_states"]) <= analysis.ALLOWED_FAST_STATES
    matched = pd.read_csv(analysis.MATCHED_PATH)
    assert len(matched) == 1946
    assert matched["v1_entry_date_match_v0"].eq(True).all()
    assert matched["v1_entry_open_match_v0"].eq(True).all()
