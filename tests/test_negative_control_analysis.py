import math
from types import SimpleNamespace

import pandas as pd

from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.negative_control_analysis import (
    CONDITIONS,
    condition_ratio,
    condition_table,
    group_stats,
    snapshot_csv_rows,
    stats_table,
)


def _daily_frame(n: int, start: str = "2015-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="D")
    close = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * n,
            "trading_value": [1.0e8] * n,
        },
        index=index,
    )


def _row(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def test_snapshot_csv_rows_tags_set_name():
    daily = _daily_frame(1200)
    snapshot_date = daily.index[900]
    snap = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )

    rows = snapshot_csv_rows([("failed_breakout", snap)], "negative_control")

    assert len(rows) == 1
    row = rows[0]
    assert row["set"] == "negative_control"
    assert row["label"] == "failed_breakout"
    assert row["ticker"] == "TEST"
    assert row["close"] == snap.features.close


def test_group_stats_computes_min_median_max_and_skips_nan():
    rows = [
        _row(ma24_slope=0.1),
        _row(ma24_slope=0.3),
        _row(ma24_slope=float("nan")),
        _row(ma24_slope=0.2),
    ]

    stats = group_stats(rows, "ma24_slope")

    assert stats.n == 3  # NaN 1개는 제외
    assert stats.min == 0.1
    assert stats.median == 0.2
    assert stats.max == 0.3


def test_group_stats_all_nan_returns_nan_with_zero_n():
    rows = [_row(ma24_slope=float("nan")), _row(ma24_slope=float("nan"))]

    stats = group_stats(rows, "ma24_slope")

    assert stats.n == 0
    assert math.isnan(stats.min)
    assert math.isnan(stats.median)
    assert math.isnan(stats.max)


def test_group_stats_empty_group_returns_nan_with_zero_n():
    stats = group_stats([], "ma24_slope")

    assert stats.n == 0
    assert math.isnan(stats.median)


def test_condition_ratio_counts_matches_and_treats_nan_as_no_match():
    rows = [
        _row(ma24_slope=0.1),
        _row(ma24_slope=-0.1),
        _row(ma24_slope=float("nan")),
        _row(ma24_slope=0.05),
    ]

    matched, total = condition_ratio(rows, CONDITIONS["ma24_slope>0"])

    assert total == 4
    assert matched == 2  # 0.1, 0.05만 매칭. NaN과 음수는 매칭 안 됨.


def test_condition_ratio_combination_requires_all_parts_and_nan_safe():
    rows = [
        _row(weekly_ma12_slope=0.1, ma24_slope=-0.1),  # A 조건(weekly>0 & ma24<=0) 매칭
        _row(weekly_ma12_slope=0.1, ma24_slope=0.2),  # 매칭 안 됨(ma24>0)
        _row(weekly_ma12_slope=float("nan"), ma24_slope=-0.1),  # weekly가 NaN -> 매칭 안 됨
    ]

    matched, total = condition_ratio(rows, CONDITIONS["A: weekly>0 & ma24<=0"])

    assert total == 3
    assert matched == 1


def test_condition_table_produces_kn_and_pct_per_group():
    groups = {
        "positive": [_row(ma24_slope=0.1), _row(ma24_slope=-0.1)],
        "negative": [_row(ma24_slope=0.1), _row(ma24_slope=0.2), _row(ma24_slope=-0.1)],
    }

    table = condition_table(groups, {"ma24_slope>0": CONDITIONS["ma24_slope>0"]})

    row = table.iloc[0]
    assert row["condition"] == "ma24_slope>0"
    assert row["positive_k/n"] == "1/2"
    assert row["positive_pct"] == 50.0
    assert row["negative_k/n"] == "2/3"
    assert math.isclose(row["negative_pct"], 200 / 3)


def test_stats_table_produces_rows_per_feature_and_group():
    groups = {
        "positive": [_row(ma24_slope=0.1, weekly_ma12_slope=0.2)],
        "negative": [_row(ma24_slope=-0.1, weekly_ma12_slope=float("nan"))],
    }

    table = stats_table(groups, ["ma24_slope", "weekly_ma12_slope"])

    assert set(table["feature"]) == {"ma24_slope", "weekly_ma12_slope"}
    assert set(table["group"]) == {"positive", "negative"}

    neg_weekly = table[(table["feature"] == "weekly_ma12_slope") & (table["group"] == "negative")].iloc[0]
    assert neg_weekly["n"] == 0
    assert math.isnan(neg_weekly["median"])
