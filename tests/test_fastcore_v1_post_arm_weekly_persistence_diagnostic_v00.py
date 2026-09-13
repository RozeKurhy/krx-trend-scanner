from __future__ import annotations

import inspect
import json

import pandas as pd

from scripts import analyze_fastcore_v1_post_arm_weekly_persistence_diagnostic_v00 as diagnostic


def test_completed_weekly_indexing_includes_unavailable() -> None:
    states = [
        (pd.Timestamp("2024-01-05"), "WATCH"),
        (pd.Timestamp("2024-01-12"), "UNAVAILABLE"),
        (pd.Timestamp("2024-01-19"), "SETUP"),
    ]
    observations = diagnostic.completed_weekly_observations(states, pd.Timestamp("2023-12-29"))
    assert [(item["checkpoint_index"], item["fast_state"]) for item in observations] == [
        (1, "WATCH"), (2, "UNAVAILABLE"), (3, "SETUP")
    ]


def test_recovery_censoring_is_at_or_after_first_mfe20() -> None:
    kwargs = {
        "recovery_class": "RECOVERY",
        "first_mfe20_date": pd.Timestamp("2024-02-02"),
        "identity_end": pd.Timestamp("2024-12-31"),
        "available_observations": [],
    }
    assert diagnostic._censor_status(checkpoint_date=pd.Timestamp("2024-02-01"), **kwargs) == (True, "NONE")
    assert diagnostic._censor_status(checkpoint_date=pd.Timestamp("2024-02-02"), **kwargs) == (
        False, "RECOVERY_ALREADY_REACHED_MFE20"
    )


def test_never_winner_censoring_after_identity_support_end() -> None:
    result = diagnostic._censor_status(
        recovery_class="NEVER_WINNER",
        checkpoint_date=pd.Timestamp("2025-01-01"),
        first_mfe20_date=None,
        identity_end=pd.Timestamp("2024-12-31"),
        available_observations=[],
    )
    assert result == (False, "IDENTITY_OR_SUPPORT_END")


def test_weak_streak_resets_on_unavailable_and_strong() -> None:
    observations = [
        {"fast_state": "WATCH", "fast_bucket": "WEAK"},
        {"fast_state": "SETUP", "fast_bucket": "WEAK"},
    ]
    assert diagnostic._persistence_metrics(observations)["consecutive_weak_streak"] == 2
    observations = [
        {"fast_state": "WATCH", "fast_bucket": "WEAK"},
        {"fast_state": "UNAVAILABLE", "fast_bucket": "UNAVAILABLE"},
        {"fast_state": "SETUP", "fast_bucket": "WEAK"},
    ]
    assert diagnostic._persistence_metrics(observations)["consecutive_weak_streak"] == 1
    observations = [
        {"fast_state": "WATCH", "fast_bucket": "WEAK"},
        {"fast_state": "TREND", "fast_bucket": "STRONG"},
    ]
    assert diagnostic._persistence_metrics(observations)["consecutive_weak_streak"] == 0


def test_weak_share_excludes_unavailable() -> None:
    observations = [
        {"fast_state": "WATCH", "fast_bucket": "WEAK"},
        {"fast_state": "UNAVAILABLE", "fast_bucket": "UNAVAILABLE"},
        {"fast_state": "TREND", "fast_bucket": "STRONG"},
    ]
    values = diagnostic._persistence_metrics(observations)
    assert values["weak_observation_count"] == 1
    assert values["strong_observation_count"] == 1
    assert values["unavailable_observation_count"] == 1
    assert values["weak_share_usable"] == 0.5


def test_metric_helpers_are_label_independent() -> None:
    daily = pd.DataFrame(
        {
            "close": [100.0, 90.0, 95.0],
            "low": [99.0, 85.0, 91.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-05"]),
    )
    price_signature = inspect.signature(diagnostic._price_metrics)
    assert "recovery_class" not in price_signature.parameters
    first = diagnostic._price_metrics(daily, 100.0, pd.Timestamp("2024-01-01"), 0.0, pd.Timestamp("2024-01-05"))
    second = diagnostic._price_metrics(daily, 100.0, pd.Timestamp("2024-01-01"), 0.0, pd.Timestamp("2024-01-05"))
    assert first == second
    fast_signature = inspect.signature(diagnostic._persistence_metrics)
    assert "recovery_class" not in fast_signature.parameters


def test_completed_artifact_contract_when_present() -> None:
    if not diagnostic.SUMMARY_PATH.exists():
        return
    summary = json.loads(diagnostic.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["primary_trade_count"] == 648
    assert summary["variant_counts"] == diagnostic.EXPECTED_FIRST_ARM_COUNTS
    assert summary["recovery_counts"] == diagnostic.EXPECTED_RECOVERY_COUNTS
    assert summary["checkpoints"] == [1, 2, 3, 4, 6, 8]
    assert summary["unknown_fast_state_count"] == 0
    assert summary["weekly_evaluation_error_count"] == 0
    assert summary["network_requests"] == 0
    assert summary["threshold_selected"] is False
    assert summary["strategy_rule_selected"] is False
    assert summary["first_mfe20_boundary_parity_compared_count"] == 648
    assert summary["first_mfe20_boundary_parity_match_count"] == 648
    assert summary["first_mfe20_boundary_parity_mismatch_count"] == 0
