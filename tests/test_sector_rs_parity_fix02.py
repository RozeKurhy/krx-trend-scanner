"""FIX02 frozen-only Sector RS contract tests (network-free)."""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.data.sector_membership import (
    SNAPSHOT_EFFECTIVE_DATE,
    SectorMembershipSnapshotUnavailable,
    load_sector_mapping_exact_snapshot,
)
from trend_scanner.relative_strength.cross_section import (
    SECTOR_CROSS_SECTION_COLUMNS,
    compute_sector_rs_cross_section,
)
from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthDataStatus,
    compute_relative_strength_features,
)


def _series(as_of: str = SNAPSHOT_EFFECTIVE_DATE, periods: int = 260) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range(end=as_of, periods=periods, freq="B").strftime("%Y-%m-%d").tolist()
    stock = pd.DataFrame({"close": [1000.0] * len(dates)}, index=pd.to_datetime(dates))
    benchmark = pd.DataFrame({
        "date": dates,
        "index_code": ["1001"] * len(dates),
        "close": [100.0] * len(dates),
    })
    return stock, benchmark


def _sector_mapping(ticker: str = "005930", code: str | None = "2074", status: str = "MAPPED"):
    return {ticker: (code, "의료·정밀기기" if code else None, SNAPSHOT_EFFECTIVE_DATE, status)}


def _compute(as_of: str, mapping, *, sector_index=None):
    stock, market = _series(as_of if as_of == SNAPSHOT_EFFECTIVE_DATE else SNAPSHOT_EFFECTIVE_DATE)
    sector = sector_index if sector_index is not None else market.copy()
    if sector_index is None:
        sector["index_code"] = "2074"
    return compute_relative_strength_features(
        "005930",
        as_of,
        stock,
        market,
        sector_index_df=sector,
        sector_mapping=mapping,
        require_exact_sector_snapshot=True,
        sector_snapshot_effective_date=SNAPSHOT_EFFECTIVE_DATE,
    )


def test_exact_snapshot_allows_20260814_and_loader_preserves_population():
    mapping = load_sector_mapping_exact_snapshot(SNAPSHOT_EFFECTIVE_DATE)
    assert len(mapping) == 2528
    assert sum(value[3] == "UNMAPPED" for value in mapping.values()) == 32
    result = _compute(SNAPSHOT_EFFECTIVE_DATE, _sector_mapping())
    assert result.sector_rs_data_status in {RelativeStrengthDataStatus.READY, RelativeStrengthDataStatus.PARTIAL}
    assert result.sector_rs_input_reason in {"READY_INPUT", "SECTOR_12M_ANCHOR_UNAVAILABLE"}


@pytest.mark.parametrize("as_of", ["2026-08-13", "2026-08-15"])
def test_historical_and_future_snapshot_are_not_evaluated(as_of: str):
    result = _compute(as_of, _sector_mapping())
    assert result.sector_rs_data_status == RelativeStrengthDataStatus.NOT_EVALUATED
    assert result.sector_rs_input_reason == "SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE"
    assert result.sector_rs_3m is None


def test_unmapped_is_retained_as_data_unavailable():
    result = _compute(SNAPSHOT_EFFECTIVE_DATE, _sector_mapping(code=None, status="UNMAPPED"))
    assert result.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert result.sector_rs_input_reason == "SECTOR_MEMBERSHIP_UNMAPPED"
    assert result.sector_code is None


def test_missing_exact_sector_benchmark_is_data_unavailable():
    stock, market = _series()
    empty = pd.DataFrame(columns=["date", "index_code", "close"])
    result = compute_relative_strength_features(
        "005930", SNAPSHOT_EFFECTIVE_DATE, stock, market,
        sector_index_df=empty, sector_mapping=_sector_mapping(),
        require_exact_sector_snapshot=True,
        sector_snapshot_effective_date=SNAPSHOT_EFFECTIVE_DATE,
    )
    assert result.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert result.sector_rs_input_reason == "SECTOR_BENCHMARK_ASOF_UNAVAILABLE"


def test_duplicate_sector_benchmark_date_fails_closed():
    stock, market = _series()
    duplicate = market.copy()
    duplicate["index_code"] = "2074"
    duplicate = pd.concat([duplicate, duplicate.iloc[[-1]]], ignore_index=True)
    with pytest.raises(Exception, match="Duplicate date"):
        compute_relative_strength_features(
            "005930", SNAPSHOT_EFFECTIVE_DATE, stock, market,
            sector_index_df=duplicate, sector_mapping=_sector_mapping(),
            require_exact_sector_snapshot=True,
            sector_snapshot_effective_date=SNAPSHOT_EFFECTIVE_DATE,
        )


def test_missing_stock_asof_is_data_unavailable_with_reason():
    stock, market = _series()
    stock = stock.iloc[:-1]
    result = compute_relative_strength_features(
        "005930", SNAPSHOT_EFFECTIVE_DATE, stock, market,
        sector_index_df=market, sector_mapping=_sector_mapping(),
        require_exact_sector_snapshot=True,
        sector_snapshot_effective_date=SNAPSHOT_EFFECTIVE_DATE,
    )
    assert result.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert result.sector_rs_input_reason == "STOCK_ASOF_UNAVAILABLE"


def test_sector_cross_section_ties_missing_and_n_one():
    rows = pd.DataFrame({
        "ticker": ["000001", "000002", "000003", "000004"],
        "market": ["KOSPI"] * 4,
        "sector_rs_3m": [0.3, 0.3, 0.1, None],
        "sector_rs_6m": [0.2, None, 0.1, None],
        "sector_rs_12m": [None, 0.2, 0.1, None],
    })
    result = compute_sector_rs_cross_section(rows).set_index("ticker")
    assert result.loc["000001", "all_sector_rs_rank_3m"] == pytest.approx(1.5)
    assert result.loc["000001", "all_sector_rs_percentile_3m"] == pytest.approx(75.0)
    assert pd.isna(result.loc["000004", "all_sector_rs_percentile_3m"])
    one = compute_sector_rs_cross_section(pd.DataFrame({"ticker": ["1"], "sector_rs_3m": [0.2]})).iloc[0]
    assert one["all_sector_rs_percentile_3m"] == 100.0
    assert set(SECTOR_CROSS_SECTION_COLUMNS).issubset(result.columns)


def test_sector_cross_section_is_full_reference_not_candidate_subset():
    all_rows = pd.DataFrame({
        "ticker": [f"{i:06d}" for i in range(1, 6)],
        "sector_rs_3m": [0.9, 0.8, 0.7, 0.6, 0.5],
        "sector_rs_6m": [0.0] * 5,
        "sector_rs_12m": [0.0] * 5,
    })
    full = compute_sector_rs_cross_section(all_rows).set_index("ticker")
    candidate = compute_sector_rs_cross_section(all_rows.iloc[:2]).set_index("ticker")
    assert full.loc["000002", "all_sector_rs_percentile_3m"] == pytest.approx(75.0)
    assert candidate.loc["000002", "all_sector_rs_percentile_3m"] == pytest.approx(0.0)


def test_snapshot_loader_rejects_non_exact_date():
    with pytest.raises(SectorMembershipSnapshotUnavailable, match="SNAPSHOT_UNAVAILABLE"):
        load_sector_mapping_exact_snapshot("2026-08-15")
