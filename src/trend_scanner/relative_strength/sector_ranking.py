"""Within-sector Sector RS ranking authority.

This module is deliberately separate from ``cross_section.py``.  The legacy
cross-section computes one global COMMON population; this authority ranks each
``(market, sector_code)`` group independently and preserves every membership
row, including rows that cannot be ranked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd


HORIZONS = ("3m", "6m", "12m")
WITHIN_SECTOR_RANK_COLUMNS = tuple(f"within_sector_rs_rank_{horizon}" for horizon in HORIZONS)
WITHIN_SECTOR_PERCENTILE_COLUMNS = tuple(
    f"within_sector_rs_percentile_{horizon}" for horizon in HORIZONS
)
WITHIN_SECTOR_RANKING_COLUMNS = (
    *WITHIN_SECTOR_RANK_COLUMNS,
    *WITHIN_SECTOR_PERCENTILE_COLUMNS,
    "sector_member_count",
    *(f"sector_eligible_count_{horizon}" for horizon in HORIZONS),
)
ELIGIBLE_MEMBERSHIP_STATUSES = frozenset({"MAPPED", "AGGREGATE_ONLY"})


def _rows_to_frame(rows: pd.DataFrame | Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    return pd.DataFrame([dict(row) for row in rows])


def _finite_numeric(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna() & np.isfinite(numeric)
    return numeric, valid


def _rank_and_percentile(values: pd.Series) -> tuple[pd.Series, pd.Series, int]:
    numeric, valid = _finite_numeric(values)
    ranks = pd.Series(np.nan, index=values.index, dtype="float64")
    percentiles = pd.Series(np.nan, index=values.index, dtype="float64")
    count = int(valid.sum())
    if count == 0:
        return ranks, percentiles, count

    rank_values = numeric.loc[valid].rank(method="average", ascending=False)
    ranks.loc[valid] = rank_values.astype(float)
    if count == 1:
        percentiles.loc[valid] = 100.0
    else:
        percentiles.loc[valid] = ((count - rank_values) / (count - 1) * 100.0).astype(float)
    return ranks, percentiles, count


def compute_within_sector_rs_ranking(
    rows: pd.DataFrame | Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Rank Sector RS values independently inside each canonical sector group.

    The input must contain one row per exact membership population member and
    the three ``sector_rs_*`` values.  Membership rows with ``MAPPED`` or
    ``AGGREGATE_ONLY`` status and a complete ``(market, sector_code,
    sector_name)`` identity participate in their own group.  ``UNMAPPED`` rows
    remain in the returned frame with null ranking fields.

    Eligibility is independent for each horizon.  Ranking values are finite
    numeric values only; missing, NaN, and infinite values are never filled.
    """

    result = _rows_to_frame(rows).reset_index(drop=True)
    required = {
        "ticker",
        "market",
        "membership_status",
        "sector_code",
        "sector_name",
        *(f"sector_rs_{horizon}" for horizon in HORIZONS),
    }
    missing = sorted(required.difference(result.columns))
    if missing:
        raise ValueError(f"within-sector ranking input missing columns: {','.join(missing)}")
    if result.empty:
        for column in WITHIN_SECTOR_RANK_COLUMNS + WITHIN_SECTOR_PERCENTILE_COLUMNS:
            result[column] = pd.Series(index=result.index, dtype="float64")
        result["sector_member_count"] = pd.Series(index=result.index, dtype="Int64")
        for horizon in HORIZONS:
            result[f"sector_eligible_count_{horizon}"] = pd.Series(index=result.index, dtype="Int64")
        return result

    result["ticker"] = result["ticker"].astype(str).str.strip().str.zfill(6)
    result["market"] = result["market"].astype(str).str.strip().str.upper()
    result["membership_status"] = result["membership_status"].astype(str).str.strip().str.upper()
    result["sector_code"] = result["sector_code"].where(result["sector_code"].notna(), pd.NA)
    result["sector_code"] = result["sector_code"].map(
        lambda value: None if pd.isna(value) else str(value).strip()
    )
    result["sector_name"] = result["sector_name"].where(result["sector_name"].notna(), pd.NA)
    if result["ticker"].duplicated().any():
        raise ValueError("within-sector ranking input has duplicate ticker")

    for horizon in HORIZONS:
        values, valid = _finite_numeric(result[f"sector_rs_{horizon}"])
        result[f"sector_rs_{horizon}"] = values.where(valid, np.nan)
        result[f"within_sector_rs_rank_{horizon}"] = pd.Series(
            np.nan, index=result.index, dtype="float64"
        )
        result[f"within_sector_rs_percentile_{horizon}"] = pd.Series(
            np.nan, index=result.index, dtype="float64"
        )
        result[f"sector_eligible_count_{horizon}"] = pd.Series(
            pd.NA, index=result.index, dtype="Int64"
        )
    result["sector_member_count"] = pd.Series(pd.NA, index=result.index, dtype="Int64")

    has_sector_identity = (
        result["market"].ne("")
        & result["sector_code"].notna()
        & result["sector_code"].ne("")
        & result["sector_name"].notna()
        & result["sector_name"].astype(str).str.strip().ne("")
    )
    eligible_membership = has_sector_identity & result["membership_status"].isin(
        ELIGIBLE_MEMBERSHIP_STATUSES
    )
    if eligible_membership.any():
        eligible = result.loc[eligible_membership]
        for (market, sector_code), group in eligible.groupby(
            ["market", "sector_code"], sort=True, dropna=False
        ):
            indexes = group.index
            result.loc[indexes, "sector_member_count"] = int(len(group))
            for horizon in HORIZONS:
                ranks, percentiles, count = _rank_and_percentile(
                    result.loc[indexes, f"sector_rs_{horizon}"]
                )
                result.loc[indexes, f"sector_eligible_count_{horizon}"] = count
                result.loc[indexes, f"within_sector_rs_rank_{horizon}"] = ranks
                result.loc[indexes, f"within_sector_rs_percentile_{horizon}"] = percentiles

    return result.sort_values(
        ["market", "sector_code", "ticker"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


__all__ = [
    "ELIGIBLE_MEMBERSHIP_STATUSES",
    "HORIZONS",
    "WITHIN_SECTOR_PERCENTILE_COLUMNS",
    "WITHIN_SECTOR_RANK_COLUMNS",
    "WITHIN_SECTOR_RANKING_COLUMNS",
    "compute_within_sector_rs_ranking",
]
