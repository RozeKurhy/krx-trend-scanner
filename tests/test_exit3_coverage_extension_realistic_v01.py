from __future__ import annotations

import pandas as pd
import pytest

import scripts.run_exit3_coverage_extension_realistic_v01 as runner
import scripts.analyze_fastcore_v2_a_vs_c1_divergence_v01 as avc
import scripts.analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01 as lc


def test_c1_first_departure_is_scheduled_for_next_local_open() -> None:
    departure = pd.Timestamp("2021-01-05")
    assert runner.extension_decision(
        lc.HOLDING_C1, departure, "BASE", None
    ) == "APPLY_EXIT3_COVERAGE_EXTENSION"
    daily = pd.DataFrame(
        {"open": [100.0, 101.0, 103.0]},
        index=pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
    )
    day, price = runner.next_session_open(daily, departure, pd.Timestamp("2021-01-06"))
    assert day == pd.Timestamp("2021-01-06")
    assert price == 103.0


def test_no_departure_or_non_c1_path_does_not_apply_exit3() -> None:
    assert runner.extension_decision(lc.HOLDING_C1, None, None, None) == "NO_HELD_PROGRESSED_DEPARTURE"
    assert runner.extension_decision("FIRST_PROGRESSED_NORMAL", pd.Timestamp("2021-01-05"), "BASE", None) == "NO_HELD_PROGRESSED_DEPARTURE"


@pytest.mark.parametrize("exit_signal", ["2021-01-04", "2021-01-05"])
def test_control_exit_before_or_tied_with_departure_keeps_v2_priority(exit_signal: str) -> None:
    decision = runner.extension_decision(
        lc.HOLDING_C1,
        pd.Timestamp("2021-01-05"),
        "TRANSITION",
        pd.Timestamp(exit_signal),
    )
    assert decision == "KEEP_CONTROL_EXIT_ON_OR_BEFORE_DEPARTURE_V2_PRIORITY"


def test_unavailable_post_holding_stage_is_never_used() -> None:
    cache = pd.DataFrame(
        {
            "label": pd.to_datetime(["2021-01-31", "2021-02-28", "2021-03-31"]),
            "effective": pd.to_datetime(["2021-01-29", "2021-02-26", "2021-03-31"]),
            "stage": ["PROGRESSED", "BASE", "WEAK"],
            "score": [50.0, 45.0, 30.0],
        }
    )
    held = avc.held_labels(
        cache,
        pd.Timestamp("2021-01-01"),
        pd.Timestamp("2021-03-31"),
        pd.Timestamp("2021-02-26"),
    )
    events = avc.stage_events("TRANSITION", held)
    assert events["first_departure_stage"] == "BASE"
    assert events["first_departure_effective"] == pd.Timestamp("2021-02-26")


def _control_record() -> dict[str, object]:
    return {
        "ticker": "000001",
        "name": "TEST",
        "market": "KOSPI",
        "trade_id": "000001_01",
        "trade_sequence": 1,
        "entry_signal_date": "2021-01-01",
        "entry_execution_date": "2021-01-04",
        "entry_open": 100.0,
        "entry_pattern_a_stage": "TRANSITION",
        "fast_stage": "TRIGGER",
        "monthly_regime": "PERMITTED_REGIME",
        "daily_risk": "NORMAL",
        "fast_score": 75.0,
        "fast_score_state": "READY",
        "previous_exit_type": None,
        "previous_exit_execution_date": None,
        "loss_guard_triggered": False,
        "loss_guard_signal_date": None,
        "loss_guard_execution_date": None,
        "loss_guard_execution_price": None,
        "first_progressed_date": "2021-01-31",
        "first_progressed_effective_trading_date": "2021-01-29",
        "lifecycle_class": "PROGRESSED_WITHOUT_DIRECT_HANDOFF",
        "exit_type": "NO_EXIT_BEFORE_CUTOFF",
        "exit_signal_date": None,
        "exit_execution_date": None,
        "exit_price": None,
        "terminal_return": 2.0,
        "mfe": 5.0,
        "mae": -1.0,
        "peak_giveback": 3.0,
        "profit_capture": 0.4,
        "holding_weeks": 1.0,
        "trade_status": "OPEN_AT_CUTOFF",
        "entry_market_cap": 2_000_000_000_000,
        "entry_market_cap_source": "CERTIFIED",
        "pair_id": "000001|KR7000000001|KOSPI|2020-01-01|2029-12-31|000001_01",
        "isu_cd": "KR7000000001",
        "identity_effective_from": "2020-01-01",
        "identity_effective_to": "2029-12-31",
        "strategy_id": runner.SOURCE_STRATEGY_ID,
        "holding_days": 2,
        "terminal_valuation_date": "2021-01-05",
        "terminal_valuation_price": 102.0,
        "terminal_valuation_source": "EXACT_CLOSE",
        "terminal_valuation_at_cutoff": True,
    }


def test_apply_exit3_changes_only_outcome_fields_at_next_open() -> None:
    control = pd.DataFrame([_control_record()])
    pair_id = str(control.iloc[0]["pair_id"])
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    daily = pd.DataFrame(
        {
            "open": [100.0, 101.0, 103.0],
            "high": [102.0, 103.0, 108.0],
            "low": [99.0, 100.0, 102.0],
            "close": [101.0, 102.0, 107.0],
        },
        index=dates,
    )
    frame_key = "000001|KR7000000001|KOSPI|2020-01-01|2029-12-31"
    event = pd.DataFrame(
        [
            {
                "pair_id": pair_id,
                "first_departure_effective_date": "2021-01-05",
                "first_departure_stage": "BASE",
                "execution_date": "2021-01-06",
                "execution_open": 103.0,
            }
        ]
    )
    test = runner._apply_exit3(
        control,
        event,
        {frame_key: daily},
        pd.Timestamp("2021-01-05"),
        pd.Timestamp("2021-01-06"),
    )
    assert test.iloc[0]["exit_type"] == "EXIT3_PROGRESSED_TO_BASE"
    assert test.iloc[0]["exit_signal_date"] == "2021-01-05"
    assert test.iloc[0]["exit_execution_date"] == "2021-01-06"
    assert test.iloc[0]["exit_price"] == 103.0
    assert test.iloc[0]["terminal_return"] == 3.0
    assert test.iloc[0]["market"] == control.iloc[0]["market"]
    assert runner._compare_entry_parity(control, test)["status"] == "PASS"
    assert runner._compare_exit_only_parity(control, test, {pair_id})["status"] == "PASS"


def test_exit_only_gate_rejects_an_unrelated_change() -> None:
    control = pd.DataFrame([_control_record()])
    test = control.copy()
    test["strategy_id"] = runner.TEST_STRATEGY_ID
    test.loc[0, "market"] = "KOSDAQ"
    with pytest.raises(RuntimeError, match="NON_EXIT_FIELD_CHANGED:market"):
        runner._compare_exit_only_parity(control, test, set())
