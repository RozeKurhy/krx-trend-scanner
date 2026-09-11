"""Focused FIX04 tests for PIT coverage aggregation and artifact rows."""

from __future__ import annotations

import pandas as pd

from scripts import run_fastcore_fundamentals_simple_v01 as runner


def _decision_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "candidate_id": "A", "entry_signal_information_date": "2017-01-10",
            "fundamentals_as_of": "2017-01-10", "company_family": "NON_FINANCIAL",
            "fundamentals_status": "PASS", "evaluable": True,
        },
        {
            "candidate_id": "B", "entry_signal_information_date": "2017-02-10",
            "fundamentals_as_of": "2017-02-10", "company_family": "NON_FINANCIAL",
            "fundamentals_status": "FILTERED_NET_LOSS", "evaluable": True,
        },
        {
            "candidate_id": "C", "entry_signal_information_date": "2017-03-10",
            "fundamentals_as_of": "2017-03-10", "company_family": "FINANCIAL",
            "fundamentals_status": "NOT_APPLICABLE", "evaluable": False,
        },
        {
            "candidate_id": "D", "entry_signal_information_date": "2017-04-10",
            "fundamentals_as_of": "2017-04-10", "company_family": "NON_FINANCIAL",
            "fundamentals_status": "DATA_UNAVAILABLE", "evaluable": False,
        },
    ])


def test_coverage_aggregation_keeps_financial_out_of_denominator():
    coverage = runner._coverage_rows(_decision_rows())

    q1 = coverage.loc[coverage["quarter"] == "2017Q1"].iloc[0]
    q2 = coverage.loc[coverage["quarter"] == "2017Q2"].iloc[0]
    assert int(q1["total_raw_candidates"]) == 3
    assert int(q1["financial_candidates"]) == 1
    assert int(q1["nonfinancial_candidates"]) == 2
    assert int(q1["evaluable_nonfinancial_candidates"]) == 2
    assert float(q1["evaluable_rate"]) == 100.0
    assert bool(q1["qualifies_90_percent"])
    assert int(q2["nonfinancial_candidates"]) == 1
    assert int(q2["unavailable_nonfinancial_candidates"]) == 1
    assert float(q2["evaluable_rate"]) == 0.0
    assert not bool(q2["qualifies_90_percent"])


def test_coverage_candidate_row_uses_signal_information_as_of_and_quarter():
    row = runner._coverage_candidate_row({
        "candidate_id": "A", "ticker": "000001", "isu_cd": "KR7000000001",
        "market": "KOSPI", "name": "Example", "candidate_signal_date": "2017-01-13",
        "entry_signal_information_date": "2017-01-10", "fundamentals_as_of": "2017-01-10",
        "company_family": "NON_FINANCIAL", "fundamentals_status": "PASS",
        "evaluable": True, "reject_reason": None, "latest_fy": "2016",
        "latest_quarter": "2016Q4", "selected_filing_receipt_dates": ["2017-01-09"],
        "company_cache_hit": True, "evaluation_source": "NETWORK",
    })

    assert row["quarter"] == "2017Q1"
    assert row["fundamentals_as_of"] == "2017-01-10"
    assert row["entry_signal_information_date"] == "2017-01-10"
    assert row["evaluable"] is True
    assert row["filing_references"] == '["2017-01-09"]'
