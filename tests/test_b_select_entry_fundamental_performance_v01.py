from scripts.research_b_select_entry_fundamental_performance_v01 import (
    RETURN_BANDS,
    closed_group_metrics,
    open_group_metrics,
    percentile,
)


def test_percentile_uses_linear_interpolation():
    assert percentile([1, 2, 3, 4, 5], 0.10) == 1.4
    assert percentile([], 0.5) is None


def test_return_band_boundaries_do_not_overlap():
    values = [-30, -15, 0, 10, 20, 50, 99.999, 100]
    assigned = [sum(predicate(value) for _, predicate in RETURN_BANDS) for value in values]
    assert assigned == [1] * len(values)


def test_closed_group_metrics_cover_requested_tails_and_profit_factor():
    returns = [-30, -15, 0, 10, 50, 100]
    rows = [
        {"return_pct": value, "holding_calendar_days": index, "holding_trading_sessions": index + 1}
        for index, value in enumerate(returns)
    ]

    metrics = closed_group_metrics("보통", rows, total_closed=10)

    assert metrics["closed_trade_count"] == 6
    assert metrics["closed_trade_share_pct"] == 60
    assert (metrics["win_count"], metrics["loss_count"], metrics["flat_count"]) == (3, 2, 1)
    assert metrics["ge_10_pct_count"] == 3
    assert metrics["ge_50_pct_count"] == 2
    assert metrics["ge_100_pct_count"] == 1
    assert metrics["le_neg15_pct_count"] == 2
    assert metrics["le_neg30_pct_count"] == 1
    assert metrics["return_band_le_neg30_count"] == 1
    assert metrics["return_band_neg30_to_neg15_count"] == 1
    assert metrics["return_band_neg15_to_zero_count"] == 1
    assert metrics["return_band_zero_to_20_count"] == 1
    assert metrics["return_band_20_to_50_count"] == 1
    assert metrics["return_band_50_to_100_count"] == 0
    assert metrics["return_band_ge_100_count"] == 1
    assert metrics["profit_factor"] == 160 / 45


def test_open_metrics_keep_open_sample_separate_and_count_thresholds():
    rows = [
        {"unrealized_return_pct": value, "holding_calendar_days": 10, "holding_trading_sessions": 7,
         "valuation_as_of": "2026-10-02"}
        for value in (10, -15, -30, 50)
    ]
    metrics = open_group_metrics("우수", rows, total_open=8)

    assert metrics["open_trade_count"] == 4
    assert metrics["open_trade_share_pct"] == 50
    assert metrics["ge_10_pct_count"] == 2
    assert metrics["ge_50_pct_count"] == 1
    assert metrics["le_neg15_pct_count"] == 2
    assert metrics["le_neg30_pct_count"] == 1
    assert metrics["valuation_as_of"] == "2026-10-02"
