"""Phase 12 improvement and all-market cross-sectional validation tests."""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.relative_strength.cross_section import (
    CROSS_SECTION_COLUMNS,
    attach_cross_sectional_rs,
    compute_market_rs_cross_section,
)


def _rows(values: list[float | None], *, market: str = "KOSPI") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [f"{i + 1:06d}" for i in range(len(values))],
            "name": [f"T{i + 1}" for i in range(len(values))],
            "market": [market] * len(values),
            "market_rs_3m": values,
            "market_rs_6m": values,
            "market_rs_12m": values,
        }
    )


def test_improvement_and_acceleration_formula() -> None:
    result = compute_market_rs_cross_section(
        pd.DataFrame(
            {
                "ticker": ["000001"],
                "market_rs_3m": [0.30],
                "market_rs_6m": [0.20],
                "market_rs_12m": [0.10],
            }
        )
    ).iloc[0]
    assert result["market_rs_delta_3m_vs_6m"] == pytest.approx(0.10)
    assert result["market_rs_delta_6m_vs_12m"] == pytest.approx(0.10)
    assert result["market_rs_acceleration_3_6_12m"] == pytest.approx(0.0)


def test_missing_propagates_without_zero_fill() -> None:
    result = compute_market_rs_cross_section(
        pd.DataFrame(
            {
                "ticker": ["000001", "000002"],
                "market_rs_3m": [0.30, 0.20],
                "market_rs_6m": [0.10, None],
                "market_rs_12m": [None, None],
            }
        )
    ).set_index("ticker")
    assert result.loc["000001", "market_rs_delta_3m_vs_6m"] == pytest.approx(0.20)
    assert pd.isna(result.loc["000001", "market_rs_delta_6m_vs_12m"])
    assert pd.isna(result.loc["000001", "market_rs_acceleration_3_6_12m"])
    assert pd.isna(result.loc["000002", "market_rs_delta_3m_vs_6m"])


def test_rank_and_percentile_strongest_to_weakest() -> None:
    result = compute_market_rs_cross_section(_rows([0.30, 0.20, 0.10])).set_index("ticker")
    assert list(result["all_market_rs_rank_3m"]) == [1.0, 2.0, 3.0]
    assert list(result["all_market_rs_percentile_3m"]) == [100.0, 50.0, 0.0]


def test_tie_uses_average_rank_and_equal_percentile() -> None:
    result = compute_market_rs_cross_section(_rows([0.30, 0.30, 0.10])).set_index("ticker")
    assert result.loc["000001", "all_market_rs_rank_3m"] == pytest.approx(1.5)
    assert result.loc["000002", "all_market_rs_rank_3m"] == pytest.approx(1.5)
    assert result.loc["000001", "all_market_rs_percentile_3m"] == pytest.approx(75.0)
    assert result.loc["000002", "all_market_rs_percentile_3m"] == pytest.approx(75.0)


def test_missing_excluded_from_horizon_population() -> None:
    result = compute_market_rs_cross_section(
        pd.DataFrame(
            {
                "ticker": ["000001", "000002", "000003"],
                "market_rs_3m": [0.30, None, 0.10],
                "market_rs_6m": [0.30, 0.20, None],
                "market_rs_12m": [None, 0.20, 0.10],
            }
        )
    ).set_index("ticker")
    assert result.loc["000001", "all_market_rs_percentile_3m"] == 100.0
    assert pd.isna(result.loc["000002", "all_market_rs_percentile_3m"])
    assert result.loc["000002", "all_market_rs_percentile_6m"] == 0.0
    assert pd.isna(result.loc["000003", "all_market_rs_percentile_6m"])
    assert result.loc["000003", "all_market_rs_percentile_12m"] == 0.0


def test_row_order_shuffle_is_deterministic() -> None:
    frame = _rows([0.30, 0.20, 0.10])
    expected = compute_market_rs_cross_section(frame).set_index("ticker")[list(CROSS_SECTION_COLUMNS)]
    shuffled = compute_market_rs_cross_section(frame.sample(frac=1.0, random_state=7)).set_index("ticker")
    pd.testing.assert_frame_equal(expected, shuffled[list(CROSS_SECTION_COLUMNS)])


def test_kospi_and_kosdaq_share_one_population() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["000001", "000002"],
            "market": ["KOSPI", "KOSDAQ"],
            "market_rs_3m": [0.30, 0.10],
            "market_rs_6m": [0.30, 0.10],
            "market_rs_12m": [0.30, 0.10],
        }
    )
    result = compute_market_rs_cross_section(frame).set_index("ticker")
    assert result.loc["000001", "all_market_rs_rank_3m"] == 1.0
    assert result.loc["000002", "all_market_rs_rank_3m"] == 2.0


def test_candidate_lookup_uses_all_market_not_candidate_only() -> None:
    all_rows = pd.DataFrame(
        {
            "ticker": [f"{i:06d}" for i in range(1, 11)],
            "market": ["KOSPI"] * 5 + ["KOSDAQ"] * 5,
            "market_rs_3m": [0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00],
            "market_rs_6m": [0.90] * 10,
            "market_rs_12m": [0.90] * 10,
        }
    )
    reference = compute_market_rs_cross_section(all_rows)
    candidates = all_rows[all_rows["ticker"].isin(["000001", "000002", "000003"])].copy()
    attached = attach_cross_sectional_rs(candidates, reference).set_index("ticker")
    assert attached.loc["000003", "all_market_rs_percentile_3m"] == pytest.approx(77.7777777778)
    candidate_only = compute_market_rs_cross_section(candidates)
    assert candidate_only.set_index("ticker").loc["000003", "all_market_rs_percentile_3m"] == 0.0
    assert attached.loc["000003", "all_market_rs_percentile_3m"] != candidate_only.set_index("ticker").loc[
        "000003", "all_market_rs_percentile_3m"
    ]


def test_n_one_and_empty_population_edges() -> None:
    one = compute_market_rs_cross_section(_rows([0.3])).iloc[0]
    assert one["all_market_rs_rank_3m"] == 1.0
    assert one["all_market_rs_percentile_3m"] == 100.0
    empty = compute_market_rs_cross_section(pd.DataFrame(columns=["ticker", "market_rs_3m"]))
    assert all(column in empty.columns for column in CROSS_SECTION_COLUMNS)
    assert empty.empty


def test_no_arbitrary_rounding_before_rank() -> None:
    result = compute_market_rs_cross_section(_rows([0.3000001, 0.3])).set_index("ticker")
    assert result.loc["000001", "all_market_rs_rank_3m"] == 1.0
    assert result.loc["000002", "all_market_rs_rank_3m"] == 2.0
