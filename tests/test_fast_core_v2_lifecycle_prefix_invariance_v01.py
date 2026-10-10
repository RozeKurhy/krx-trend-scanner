import pandas as pd

from trend_scanner.validation.pattern_a_fast_core_v02_reentry import _simulate_causal_lifecycle


def _snapshot(date: str, stage: str, score: float | None = None) -> dict:
    value = pd.Timestamp(date)
    return {
        "date": value,
        "effective_trading_date": value,
        "stage": stage,
        "score": score,
    }


def test_later_direct_handoff_cannot_revise_an_earlier_coverage_exit():
    short = [
        _snapshot("2023-01-31", "TRANSITION", 72.0),
        _snapshot("2023-02-28", "PROGRESSED", 80.0),
        _snapshot("2023-03-31", "PROGRESSED", 72.0),
        _snapshot("2023-04-30", "PROGRESSED", 64.0),
    ]
    long = short + [
        _snapshot("2023-05-31", "EARLY_TREND", 72.0),
        _snapshot("2023-06-30", "PROGRESSED", 75.0),
        _snapshot("2023-07-31", "BASE", 55.0),
    ]

    short_result = _simulate_causal_lifecycle(short, "EARLY_TREND")
    long_result = _simulate_causal_lifecycle(long, "EARLY_TREND")

    assert short_result["coverage_path"] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
    assert short_result["exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15"
    assert short_result["exit_signal_date"] == pd.Timestamp("2023-04-30")
    assert long_result["exit_signal_date"] == short_result["exit_signal_date"]
    assert long_result["exit_type"] == short_result["exit_type"]
    assert long_result["coverage_path"] == short_result["coverage_path"]
    assert long_result["first_progressed_date"] == short_result["first_progressed_date"]


def test_loss_guard_stop_excludes_lifecycle_events_observed_after_its_signal():
    snapshots = [
        _snapshot("2024-01-31", "EARLY_TREND", 60.0),
        _snapshot("2024-02-29", "PROGRESSED", 70.0),
        _snapshot("2024-03-31", "BASE", 50.0),
    ]

    result = _simulate_causal_lifecycle(
        snapshots,
        "EARLY_TREND",
        stop_date=pd.Timestamp("2024-01-30"),
    )

    assert result["coverage_path"] == "NEVER_PROGRESSED"
    assert result["first_progressed_date"] is None
    assert result["exit_signal_date"] is None
    assert result["exit_type"] == "NO_PROGRESSED_BEFORE_CUTOFF"
