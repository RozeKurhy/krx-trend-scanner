"""Phase 12 market-relative-strength improvement and cross-section layer.

이 모듈은 이미 계산된 Market RS 값만 받아 순수하게 파생 피처와 전체 시장
cross-sectional rank/percentile을 계산한다. Pattern A Candidate, Investability,
Foreign Flow 같은 downstream 개념을 알지 않으며, 입력 subset으로 percentile을
계산하는 실수를 방지하기 위해 caller가 공식 COMMON universe 전체를 전달해야 한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


IMPROVEMENT_COLUMNS = (
    "market_rs_delta_3m_vs_6m",
    "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
)
RANK_COLUMNS = (
    "all_market_rs_rank_3m",
    "all_market_rs_rank_6m",
    "all_market_rs_rank_12m",
)
PERCENTILE_COLUMNS = (
    "all_market_rs_percentile_3m",
    "all_market_rs_percentile_6m",
    "all_market_rs_percentile_12m",
)
CROSS_SECTION_COLUMNS = IMPROVEMENT_COLUMNS + RANK_COLUMNS + PERCENTILE_COLUMNS

SECTOR_RANK_COLUMNS = (
    "all_sector_rs_rank_3m",
    "all_sector_rs_rank_6m",
    "all_sector_rs_rank_12m",
)
SECTOR_PERCENTILE_COLUMNS = (
    "all_sector_rs_percentile_3m",
    "all_sector_rs_percentile_6m",
    "all_sector_rs_percentile_12m",
)
SECTOR_CROSS_SECTION_COLUMNS = SECTOR_RANK_COLUMNS + SECTOR_PERCENTILE_COLUMNS


def _rows_to_frame(rows: pd.DataFrame | Iterable[Any]) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    records: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            records.append(dict(row))
        elif hasattr(row, "to_dict"):
            records.append(dict(row.to_dict()))
        else:
            raise TypeError(f"Unsupported RS row type: {type(row).__name__}")
    return pd.DataFrame(records)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _safe_difference(left: pd.Series, right: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=left.index, dtype="float64")
    valid = left.notna() & right.notna() & np.isfinite(left) & np.isfinite(right)
    result.loc[valid] = left.loc[valid] - right.loc[valid]
    return result

def _rank_and_percentile(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return descending average rank and the canonical 0..100 percentile."""

    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna() & np.isfinite(numeric)
    ranks = pd.Series(np.nan, index=values.index, dtype="float64")
    percentiles = pd.Series(np.nan, index=values.index, dtype="float64")
    n = int(valid.sum())
    if n == 0:
        return ranks, percentiles

    valid_values = numeric.loc[valid]
    rank_values = valid_values.rank(method="average", ascending=False)
    ranks.loc[valid] = rank_values.astype(float)
    if n == 1:
        percentiles.loc[valid] = 100.0
    else:
        percentiles.loc[valid] = ((n - rank_values) / (n - 1) * 100.0).astype(float)
    return ranks, percentiles


def compute_market_rs_cross_section(rows: pd.DataFrame | Iterable[Any]) -> pd.DataFrame:
    """Add improvement, acceleration, all-market rank, and percentile fields.

    Each horizon has an independent population consisting only of finite
    ``market_rs_{horizon}`` values. Missing values are never filled and receive
    ``None``/``NaN`` for every corresponding derived field. Ties use pandas'
    average rank and therefore share one percentile. No input rounding occurs.
    """

    result = _rows_to_frame(rows)
    if result.empty:
        for column in CROSS_SECTION_COLUMNS:
            result[column] = pd.Series(index=result.index, dtype="float64")
        return result

    rs_3m = _numeric(result, "market_rs_3m")
    rs_6m = _numeric(result, "market_rs_6m")
    rs_12m = _numeric(result, "market_rs_12m")

    result["market_rs_delta_3m_vs_6m"] = _safe_difference(rs_3m, rs_6m)
    result["market_rs_delta_6m_vs_12m"] = _safe_difference(rs_6m, rs_12m)
    acceleration = pd.Series(np.nan, index=result.index, dtype="float64")
    valid_acceleration = (
        rs_3m.notna()
        & rs_6m.notna()
        & rs_12m.notna()
        & np.isfinite(rs_3m)
        & np.isfinite(rs_6m)
        & np.isfinite(rs_12m)
    )
    acceleration.loc[valid_acceleration] = (
        rs_3m.loc[valid_acceleration]
        - 2.0 * rs_6m.loc[valid_acceleration]
        + rs_12m.loc[valid_acceleration]
    )
    result["market_rs_acceleration_3_6_12m"] = acceleration

    for horizon, values in (("3m", rs_3m), ("6m", rs_6m), ("12m", rs_12m)):
        ranks, percentiles = _rank_and_percentile(values)
        result[f"all_market_rs_rank_{horizon}"] = ranks
        result[f"all_market_rs_percentile_{horizon}"] = percentiles

    if {"market", "ticker"}.issubset(result.columns):
        result = result.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    elif "ticker" in result.columns:
        result = result.sort_values(["ticker"], kind="mergesort").reset_index(drop=True)
    return result


def attach_cross_sectional_rs(
    scan_rows: pd.DataFrame,
    all_market_reference: pd.DataFrame,
) -> pd.DataFrame:
    """Lookup all-market values onto scanner rows without recomputing a subset.

    ``all_market_reference`` must already be produced from the complete COMMON
    universe by :func:`compute_market_rs_cross_section`.
    """

    if "ticker" not in scan_rows.columns or "ticker" not in all_market_reference.columns:
        raise ValueError("Both scanner rows and reference rows require a ticker column")
    reference = all_market_reference.drop_duplicates("ticker").set_index("ticker")
    result = scan_rows.copy()
    for column in CROSS_SECTION_COLUMNS:
        if column not in reference.columns:
            raise ValueError(f"Reference is missing cross-sectional column: {column}")
        result[column] = result["ticker"].map(reference[column])
    return result


def compute_sector_rs_cross_section(rows: pd.DataFrame | Iterable[Any]) -> pd.DataFrame:
    """Compute all-COMMON Sector RS ranks and percentiles.

    Sector RS is already normalized against each security's native sector
    benchmark, so this final cross-section is over the complete COMMON input,
    not within-sector or candidate subsets.  Missing and non-finite values are
    excluded independently for each horizon.
    """

    result = _rows_to_frame(rows)
    if result.empty:
        for column in SECTOR_CROSS_SECTION_COLUMNS:
            result[column] = pd.Series(index=result.index, dtype="float64")
        return result
    for horizon in ("3m", "6m", "12m"):
        ranks, percentiles = _rank_and_percentile(_numeric(result, f"sector_rs_{horizon}"))
        result[f"all_sector_rs_rank_{horizon}"] = ranks
        result[f"all_sector_rs_percentile_{horizon}"] = percentiles
    if {"market", "ticker"}.issubset(result.columns):
        result = result.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    elif "ticker" in result.columns:
        result = result.sort_values(["ticker"], kind="mergesort").reset_index(drop=True)
    return result


def attach_sector_cross_sectional_rs(
    scan_rows: pd.DataFrame,
    all_sector_reference: pd.DataFrame,
) -> pd.DataFrame:
    """Attach a full-COMMON Sector RS reference to scanner rows by ticker."""

    if "ticker" not in scan_rows.columns or "ticker" not in all_sector_reference.columns:
        raise ValueError("Both scanner rows and reference rows require a ticker column")
    reference = all_sector_reference.drop_duplicates("ticker").set_index("ticker")
    result = scan_rows.copy()
    for column in SECTOR_CROSS_SECTION_COLUMNS:
        if column not in reference.columns:
            raise ValueError(f"Reference is missing cross-sectional column: {column}")
        result[column] = result["ticker"].map(reference[column])
    return result
