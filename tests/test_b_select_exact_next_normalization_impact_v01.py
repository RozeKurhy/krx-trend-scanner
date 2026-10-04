from __future__ import annotations

import math

from scripts.replay_b_select_exact_next_normalization_impact_v01 import audit


EXPECTED = {
    "018680": ("ENTRY", "2016-02-29", "2016-03-02"),
    "072020": ("ENTRY", "2017-03-31", "2017-04-03"),
    "109820": ("ENTRY", "2017-03-31", "2017-04-03"),
    "001040": ("EXIT", "2017-05-31", "2017-06-01"),
    "005030": ("EXIT", "2016-05-31", "2016-06-01"),
    "014200": ("EXIT", "2022-03-31", "2022-04-01"),
    "078160": ("EXIT", "2018-11-30", "2018-12-03"),
}


def test_seven_source_trades_are_exact_next_and_one_sided() -> None:
    result = audit()

    assert result["verdict"] == "B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS"
    assert len(result["target_trades"]) == 7
    assert result["all_target_rows_excluded_from_current_policy"] is True
    assert result["all_target_exact_next_adjusted_opens_valid"] is True
    assert result["all_target_raw_next_sessions_traded"] is True
    assert result["all_target_share_counts_stable_across_stored_and_exact_next_dates"] is True

    observed = {row["ticker"]: row for row in result["target_trades"]}
    assert set(observed) == set(EXPECTED)
    for ticker, (side, signal_date, expected_date) in EXPECTED.items():
        row = observed[ticker]
        assert row["side_normalized"] == side
        assert row["signal_date"] == signal_date
        assert row["normalized_execution_date"] == expected_date
        assert row["normalized_current_adjusted_open"] > 0
        assert row["normalized_raw_volume"] > 0
        assert row["listed_shares_stored_date"] == row["listed_shares_normalized_date"]
        assert row["preserved_opposite_execution_date"] != expected_date

    assert math.isclose(
        observed["014200"]["costed_pre_tax_return_delta_pp"],
        -49.20241544053596,
        rel_tol=0.0,
        abs_tol=1e-8,
    )


def test_targets_have_no_official_portfolio_exposure() -> None:
    result = audit()

    assert result["source_ledger_target_exposure_by_window"] == {
        "P1": 7,
        "P2-1": 1,
        "P2-2": 1,
        "P3-1": 0,
        "P3-2": 0,
    }
    assert set(result["current_filtered_candidate_target_exposure_by_window"].values()) == {0}
    assert set(result["official_portfolio_event_target_exposure_by_window"].values()) == {0}
    assert result["official_v03_historical_exclusion_policy_proof"]["all_target_identities_present"] is True
    assert result["target_normalized_portfolio_replay_performed"] is False
    assert result["exploratory_current_authority_replay"]["status"] == "DISCARDED_OFFICIAL_BASELINE_PARITY_FAILURE"


def test_official_metrics_and_adoption_are_unchanged_by_zero_exposure() -> None:
    result = audit()

    assert result["official_adoption_status_before_after"]["before_normalization"] == "OFFICIAL_STRATEGY_ADOPTED"
    assert result["official_adoption_status_before_after"]["after_normalization"] == "OFFICIAL_STRATEGY_ADOPTED"
    for row in result["official_window_metrics_before_after"]:
        for field in (
            "ending_equity_krw",
            "total_return_pct",
            "CAGR_pct",
            "MDD_pct",
            "average_capital_utilization_pct",
            "cash_shortage_skipped_entries",
            "trade_count",
            "closed_trade_count",
            "win_rate_pct",
            "mean_net_return_pct",
            "median_net_return_pct",
            "mean_holding_krx_sessions",
            "median_holding_krx_sessions",
            "tail_le_15_count",
            "tail_le_30_count",
            "tail_ge_30_count",
            "tail_ge_50_count",
            "valuation_coverage_pct",
        ):
            assert row[f"before_{field}"] == row[f"after_{field}"]
            assert row[f"delta_{field}"] == 0
        assert row["gate_A_to_E_before"] == row["gate_A_to_E_after"] == "PASSPASSPASSPASSPASS"
    assert all(
        row["next_exact_krx_session_violation_count"] == 0
        for row in result["executed_official_event_schedule_audit"].values()
    )
