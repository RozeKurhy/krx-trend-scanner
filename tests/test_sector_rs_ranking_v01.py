"""Focused tests for the within-sector Sector RS ranking authority."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trend_scanner.relative_strength.sector_ranking import compute_within_sector_rs_ranking


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "as_of": "2026-09-04",
            "ticker": ["000001", "000002", "000003", "000004"],
            "market": ["KOSPI", "KOSPI", "KOSDAQ", "KOSDAQ"],
            "membership_status": ["MAPPED", "MAPPED", "MAPPED", "MAPPED"],
            "sector_code": ["1009", "1009", "2066", "2066"],
            "sector_name": ["제약", "제약", "제약", "제약"],
            "sector_rs_data_status": "READY",
            "sector_rs_input_reason": "READY_INPUT",
            "sector_rs_3m": [0.50, 0.10, 0.90, 0.20],
            "sector_rs_6m": [0.50, 0.10, 0.90, 0.20],
            "sector_rs_12m": [0.50, 0.10, 0.90, 0.20],
        }
    )


def test_ranking_isolated_by_market_and_canonical_sector() -> None:
    result = compute_within_sector_rs_ranking(_rows()).set_index("ticker")
    assert result.loc["000001", "within_sector_rs_rank_3m"] == 1.0
    assert result.loc["000002", "within_sector_rs_rank_3m"] == 2.0
    assert result.loc["000003", "within_sector_rs_rank_3m"] == 1.0
    assert result.loc["000004", "within_sector_rs_rank_3m"] == 2.0
    assert result.loc["000001", "within_sector_rs_percentile_3m"] == 100.0
    assert result.loc["000002", "within_sector_rs_percentile_3m"] == 0.0


def test_horizon_eligibility_is_independent_and_invalid_values_are_excluded() -> None:
    rows = _rows()
    rows.loc[1, "sector_rs_6m"] = np.nan
    rows.loc[0, "sector_rs_12m"] = np.inf
    result = compute_within_sector_rs_ranking(rows).set_index("ticker")
    assert result.loc["000001", "sector_eligible_count_3m"] == 2
    assert result.loc["000001", "sector_eligible_count_6m"] == 1
    assert pd.isna(result.loc["000002", "within_sector_rs_rank_6m"])
    assert result.loc["000001", "sector_eligible_count_12m"] == 1
    assert pd.isna(result.loc["000001", "within_sector_rs_percentile_12m"])


def test_tie_and_single_member_rules() -> None:
    rows = _rows().iloc[:2].copy()
    rows.loc[1, "sector_rs_3m"] = rows.loc[0, "sector_rs_3m"]
    result = compute_within_sector_rs_ranking(rows).set_index("ticker")
    assert result.loc["000001", "within_sector_rs_rank_3m"] == 1.5
    assert result.loc["000002", "within_sector_rs_rank_3m"] == 1.5
    assert result.loc["000001", "within_sector_rs_percentile_3m"] == 50.0

    one = compute_within_sector_rs_ranking(rows.iloc[:1]).iloc[0]
    assert one["sector_member_count"] == 1
    assert one["sector_eligible_count_3m"] == 1
    assert one["within_sector_rs_rank_3m"] == 1.0
    assert one["within_sector_rs_percentile_3m"] == 100.0


def test_unmapped_is_preserved_but_not_ranked_and_aggregate_only_is_ranked() -> None:
    rows = _rows().iloc[:2].copy()
    rows.loc[0, ["membership_status", "sector_code", "sector_name"]] = ["UNMAPPED", None, None]
    rows.loc[1, "membership_status"] = "AGGREGATE_ONLY"
    result = compute_within_sector_rs_ranking(rows).set_index("ticker")
    assert len(result) == 2
    assert pd.isna(result.loc["000001", "within_sector_rs_rank_3m"])
    assert pd.isna(result.loc["000001", "sector_member_count"])
    assert result.loc["000002", "within_sector_rs_rank_3m"] == 1.0
    assert result.loc["000002", "sector_member_count"] == 1


def test_deterministic_order_and_duplicate_ticker_rejection() -> None:
    expected = compute_within_sector_rs_ranking(_rows())
    shuffled = compute_within_sector_rs_ranking(_rows().sample(frac=1.0, random_state=17))
    pd.testing.assert_frame_equal(expected, shuffled)
    with pytest.raises(ValueError, match="duplicate ticker"):
        compute_within_sector_rs_ranking(pd.concat([_rows(), _rows().iloc[[0]]], ignore_index=True))
