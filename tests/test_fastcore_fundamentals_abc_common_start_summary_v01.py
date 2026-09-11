"""Regression test for the exact ABC common-start quarter metadata."""

import pandas as pd

from scripts.recover_fastcore_fundamentals_abc_opendart_pending_v01 import _summary


def test_summary_keeps_full_first_qualifying_quarter_label():
    state = pd.DataFrame({"future_filing_used": [False, False, False, False]})
    quarter = pd.DataFrame([
        {
            "quarter": label,
            "nonfinancial_candidate_count": 10,
            "initial_evaluable_count": 10,
            "initial_unavailable_count": 0,
            "recovered_from_existing_cache_count": 0,
            "recovered_from_opendart_count": 0,
            "final_evaluable_count": 10,
            "true_data_unavailable_count": 0,
            "evaluation_error_count": 0,
            "final_evaluable_rate": 100.0,
            "qualifying_90pct": True,
        }
        for label in ("2021Q2", "2021Q3", "2021Q4", "2022Q1")
    ])

    summary = _summary(
        state,
        quarter,
        attempted=0,
        recovered=0,
        unavailable=0,
        unresolved_not_needed=0,
        evaluation_errors=0,
        opendart_call_count=0,
        status="COMPLETE",
    )

    assert summary["first_qualifying_4_quarter_window"] == "2021Q2"
    assert summary["ABC_COMMON_START_QUARTER"] == "2021Q2"
    assert summary["selected_abc_common_start_quarter"] == "2021Q2"
    assert summary["ABC_COMMON_START_DATE"] == "2021-04-01"
    assert summary["selected_abc_common_start_date"] == "2021-04-01"
