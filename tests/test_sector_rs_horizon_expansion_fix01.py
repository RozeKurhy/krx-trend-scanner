"""Focused tests for additive 2W/1M Sector RS horizons."""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthDataStatus,
    compute_relative_strength_features,
)


AS_OF = "2026-09-04"


def _inputs(periods: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range(end=AS_OF, periods=periods, freq="B")
    stock = pd.DataFrame(
        {"close": [100.0 + float(index) for index in range(periods)]},
        index=dates,
    )
    sector = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "index_code": ["2066"] * periods,
            "close": [200.0 + float(index) * 0.5 for index in range(periods)],
        }
    )
    return stock, sector


def _compute(stock: pd.DataFrame, sector: pd.DataFrame, effective_date: str = AS_OF):
    return compute_relative_strength_features(
        ticker="001540",
        as_of=AS_OF,
        stock_df=stock,
        market_index_df=pd.DataFrame(columns=["date", "index_code", "close"]),
        market="KOSDAQ",
        sector_index_df=sector,
        sector_mapping={"001540": ("2066", "제약", effective_date, "MAPPED")},
        require_exact_sector_snapshot=True,
        sector_snapshot_effective_date=AS_OF,
    )


def test_short_horizons_use_exact_session_anchors_and_existing_formula():
    stock, sector = _inputs()
    result = _compute(stock, sector)

    assert result.sector_rs_data_status == RelativeStrengthDataStatus.READY
    for horizon, sessions in (("2w", 10), ("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)):
        anchor_index = len(sector) - 1 - sessions
        anchor_date = sector["date"].iloc[anchor_index]
        sector_return = sector["close"].iloc[-1] / sector["close"].iloc[anchor_index] - 1.0
        stock_return = stock["close"].iloc[-1] / stock["close"].iloc[anchor_index] - 1.0
        expected_rs = (1.0 + stock_return) / (1.0 + sector_return) - 1.0
        assert getattr(result, f"sector_anchor_date_{horizon}") == anchor_date
        assert getattr(result, f"sector_return_{horizon}") == pytest.approx(sector_return)
        assert getattr(result, f"sector_rs_{horizon}") == pytest.approx(expected_rs)


def test_short_horizons_keep_exact_benchmark_and_membership_fail_closed_rules():
    stock, sector = _inputs()
    stale_sector = sector.iloc[:-1].copy()
    stale = _compute(stock, stale_sector)
    assert stale.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert stale.sector_rs_input_reason == "SECTOR_BENCHMARK_ASOF_UNAVAILABLE"
    assert stale.sector_rs_2w is None
    assert stale.sector_rs_1m is None
    assert stale.sector_benchmark_last_observation_date == "2026-09-03"

    wrong_snapshot = _compute(stock, sector, effective_date="2026-09-03")
    assert wrong_snapshot.sector_rs_data_status == RelativeStrengthDataStatus.NOT_EVALUATED
    assert wrong_snapshot.sector_rs_input_reason == "SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE"
    assert wrong_snapshot.sector_rs_2w is None
    assert wrong_snapshot.sector_rs_1m is None
