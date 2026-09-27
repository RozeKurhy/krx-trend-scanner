from __future__ import annotations

import pytest

from scripts.diagnose_pattern_b_state_forward_censoring_v01 import (
    classify_status,
    summarize_status_counts,
)


def test_status_classification_is_mutually_exclusive_and_frontier_is_separate():
    assert classify_status(
        outcome_present=False, endpoint_after_frontier=True, identity_status="OTHER",
    ) == "FRONTIER_INCOMPLETE"
    assert classify_status(
        outcome_present=True, endpoint_after_frontier=False, identity_status="NOT_ASSESSED",
    ) == "COMPLETED"
    assert classify_status(
        outcome_present=False, endpoint_after_frontier=False, identity_status="TERMINAL",
    ) == "TERMINAL_IDENTITY"
    assert classify_status(
        outcome_present=False, endpoint_after_frontier=False, identity_status="CONTINUOUS",
    ) == "ENDPOINT_PRICE_MISSING"
    assert classify_status(
        outcome_present=False, endpoint_after_frontier=False, identity_status="OTHER",
    ) == "OTHER_MISSING"


def test_frontier_cannot_be_marked_completed():
    with pytest.raises(ValueError, match="cannot exist beyond"):
        classify_status(
            outcome_present=True, endpoint_after_frontier=True, identity_status="CONTINUOUS",
        )


def test_summary_uses_mature_sample_denominator_and_checks_decomposition():
    row = summarize_status_counts(100, {
        "COMPLETED": 60,
        "FRONTIER_INCOMPLETE": 20,
        "TERMINAL_IDENTITY": 10,
        "ENDPOINT_PRICE_MISSING": 8,
        "OTHER_MISSING": 2,
    })
    assert row["mature_sample_n"] == 80
    assert row["raw_completion_rate_pct"] == 60.0
    assert row["mature_completion_rate_pct"] == 75.0
    assert row["terminal_identity_rate_pct"] == 12.5
    assert row["endpoint_price_missing_rate_pct"] == 10.0
    with pytest.raises(ValueError, match="decomposition mismatch"):
        summarize_status_counts(100, {
            "COMPLETED": 60,
            "FRONTIER_INCOMPLETE": 20,
            "TERMINAL_IDENTITY": 10,
            "ENDPOINT_PRICE_MISSING": 8,
            "OTHER_MISSING": 1,
        })
