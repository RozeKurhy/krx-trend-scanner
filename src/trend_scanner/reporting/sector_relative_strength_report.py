"""Stock Report v0.4 Sector Relative Strength consumer.

The report layer deliberately reuses the frozen relative-strength calculator.
It loads the exact membership snapshot for the requested local date and never
performs network I/O or cross-sectional ranking.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.sector_membership import (
    SectorMembershipSnapshotUnavailable,
    load_sector_mapping_exact_snapshot,
    sector_membership_path_for_date,
)
from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthDataStatus,
    compute_relative_strength_features,
)
from trend_scanner.universe.models import MarketType
from trend_scanner.universe.asset_classifier import AssetType
from trend_scanner.reporting.models import SectorRelativeStrengthSection


SECTOR_INDEX_SOURCE = ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet"
_EMPTY_MARKET_INDEX = pd.DataFrame(columns=["date", "index_code", "close"])


def _empty_section(
    *,
    applicability: str,
    data_status: str,
    input_reason: str | None = None,
    source_as_of: str | None = None,
    membership_snapshot_date: str | None = None,
    membership_source: str | None = None,
    sector_index_source: str | None = None,
    sector_name: str | None = None,
    sector_code: str | None = None,
    benchmark_code: str | None = None,
    explanation: str | None = None,
) -> SectorRelativeStrengthSection:
    if explanation is None:
        if data_status == RelativeStrengthDataStatus.NOT_EVALUATED.value:
            explanation = "Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다."
        elif input_reason == "SECTOR_MEMBERSHIP_UNMAPPED":
            explanation = "업종 매핑 정보가 없어 업종 상대강도를 계산할 수 없습니다."
        elif input_reason in {"STOCK_ASOF_UNAVAILABLE", "REPOSITORY_V2_UNAVAILABLE"}:
            explanation = "기준일 종목 가격이 없어 업종 상대강도를 계산할 수 없습니다."
        elif input_reason == "SECTOR_BENCHMARK_ASOF_UNAVAILABLE":
            explanation = "기준일 업종 벤치마크가 없어 업종 상대강도를 계산할 수 없습니다."
        elif data_status == RelativeStrengthDataStatus.PARTIAL.value:
            explanation = "일부 기간의 업종 상대강도 데이터가 부족하여 제한적으로 해석해야 합니다."
        else:
            explanation = "업종 상대강도 데이터를 사용할 수 없습니다."
    return SectorRelativeStrengthSection(
        applicability=applicability,
        data_status=data_status,
        input_reason=input_reason,
        sector_name=sector_name,
        sector_code=sector_code,
        benchmark_code=benchmark_code,
        benchmark_last_observation_date=None,
        sector_return_3m=None,
        sector_return_6m=None,
        sector_return_12m=None,
        sector_rs_3m=None,
        sector_rs_6m=None,
        sector_rs_12m=None,
        sector_anchor_date_3m=None,
        sector_anchor_date_6m=None,
        sector_anchor_date_12m=None,
        sector_return_2w=None,
        sector_return_1m=None,
        sector_rs_2w=None,
        sector_rs_1m=None,
        sector_anchor_date_2w=None,
        sector_anchor_date_1m=None,
        explanation=explanation,
        source_as_of=source_as_of,
        membership_snapshot_date=membership_snapshot_date,
        membership_source=membership_source,
        sector_index_source=sector_index_source,
    )


def _normalise_as_of(value: str | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _market_value(value: MarketType | str) -> str:
    return value.value if isinstance(value, MarketType) else str(value).upper()


def _is_common(value: AssetType | str) -> bool:
    return value.value == "COMMON" if isinstance(value, AssetType) else str(value).upper() == "COMMON"


def _ready_explanation(result: Any) -> str:
    values = [result.sector_rs_3m, result.sector_rs_6m, result.sector_rs_12m]
    if all(value is not None for value in values):
        if values[0] > values[1] > values[2]:
            return "최근 3개월·6개월의 업종 상대강도가 12개월 대비 개선되는 흐름입니다."
        if values[0] < values[1] < values[2]:
            return "최근 업종 상대강도가 장기 대비 약화되는 흐름입니다."
        return "최근 3개월·6개월·12개월의 업종 대비 상대강도를 확인할 수 있습니다."
    return "일부 기간의 업종 상대강도 데이터가 부족하여 제한적으로 해석해야 합니다."


def build_sector_relative_strength_section(
    *,
    ticker: str,
    requested_as_of: str | pd.Timestamp,
    asset_type: AssetType | str,
    market: MarketType | str,
    stock_df: pd.DataFrame | None,
    repo_root: Path,
    sector_index_df: pd.DataFrame | None = None,
    sector_mapping: dict[str, tuple[str | None, str | None, str, str]] | None = None,
) -> SectorRelativeStrengthSection:
    """Build one additive Sector RS report section from local authorities.

    ``stock_df`` must be a Repository V2 view in production.  The optional
    mapping/index parameters exist for tests and for a generator that already
    holds the run-scoped local inputs; no new repository is created here.
    """

    as_of = _normalise_as_of(requested_as_of)
    clean_ticker = str(ticker).strip().zfill(6)
    market_str = _market_value(market)
    if not _is_common(asset_type) or market_str not in {"KOSPI", "KOSDAQ"}:
        return _empty_section(
            applicability="NOT_APPLICABLE",
            data_status=RelativeStrengthDataStatus.NOT_EVALUATED.value,
        )

    membership_snapshot_date = as_of
    membership_source = str(sector_membership_path_for_date(as_of, repo_root).relative_to(repo_root))
    sector_index_source = SECTOR_INDEX_SOURCE

    # Production Stock Report input is explicitly the Repository V2 view.  A
    # legacy fixture without this provenance remains fail-closed rather than
    # silently promoting the old ParquetCache to a new authority.
    if stock_df is None or stock_df.empty or stock_df.attrs.get("data_authority") != "MarketDataRepositoryV2":
        return _empty_section(
            applicability="APPLICABLE",
            data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
            input_reason="REPOSITORY_V2_UNAVAILABLE",
            source_as_of=as_of,
            membership_snapshot_date=membership_snapshot_date,
            membership_source=membership_source,
            sector_index_source=sector_index_source,
        )

    if sector_mapping is None:
        try:
            sector_mapping = load_sector_mapping_exact_snapshot(
                as_of,
                repo_root=repo_root,
            )
        except SectorMembershipSnapshotUnavailable:
            return _empty_section(
                applicability="APPLICABLE",
                data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
                input_reason="SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE",
                source_as_of=as_of,
                membership_snapshot_date=membership_snapshot_date,
                membership_source=membership_source,
                sector_index_source=sector_index_source,
            )

    membership = sector_mapping.get(clean_ticker)
    if membership is None:
        return _empty_section(
            applicability="APPLICABLE",
            data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
            input_reason="SECTOR_MEMBERSHIP_UNMAPPED",
            source_as_of=as_of,
            membership_snapshot_date=membership_snapshot_date,
            membership_source=membership_source,
            sector_index_source=sector_index_source,
        )
    sector_code = membership[0]
    sector_name = membership[1]
    resolution = str(membership[3]).upper() if len(membership) >= 4 else "MAPPED"
    if resolution == "UNMAPPED" or sector_code is None:
        return _empty_section(
            applicability="APPLICABLE",
            data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
            input_reason="SECTOR_MEMBERSHIP_UNMAPPED",
            source_as_of=as_of,
            membership_snapshot_date=membership_snapshot_date,
            membership_source=membership_source,
            sector_index_source=sector_index_source,
            sector_name=sector_name,
            sector_code=None,
        )

    if sector_index_df is None:
        sector_path = repo_root / SECTOR_INDEX_SOURCE
        if not sector_path.exists():
            return _empty_section(
                applicability="APPLICABLE",
                data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
                input_reason="SECTOR_BENCHMARK_ASOF_UNAVAILABLE",
                source_as_of=as_of,
                membership_snapshot_date=membership_snapshot_date,
                membership_source=membership_source,
                sector_index_source=sector_index_source,
                sector_name=sector_name,
                sector_code=str(sector_code),
                benchmark_code=str(sector_code),
            )
        sector_index_df = pd.read_parquet(sector_path)

    # Keep the calculator's exact-as-of/fail-closed rule explicit at the
    # report boundary so the diagnostic reason is not confused with a missing
    # sector benchmark when the stock itself has no requested-date close.
    if "close" not in stock_df.columns:
        return _empty_section(
            applicability="APPLICABLE",
            data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
            input_reason="STOCK_ASOF_UNAVAILABLE",
            source_as_of=as_of,
            membership_snapshot_date=membership_snapshot_date,
            membership_source=membership_source,
            sector_index_source=sector_index_source,
            sector_name=str(sector_name),
            sector_code=str(sector_code),
            benchmark_code=str(sector_code),
        )
    stock_index = pd.to_datetime(stock_df.index, errors="coerce")
    stock_at_asof = stock_df.loc[stock_index == pd.Timestamp(as_of), "close"]
    if stock_at_asof.empty or stock_at_asof.isna().all() or (pd.to_numeric(stock_at_asof, errors="coerce") <= 0).all():
        return _empty_section(
            applicability="APPLICABLE",
            data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE.value,
            input_reason="STOCK_ASOF_UNAVAILABLE",
            source_as_of=as_of,
            membership_snapshot_date=membership_snapshot_date,
            membership_source=membership_source,
            sector_index_source=sector_index_source,
            sector_name=str(sector_name),
            sector_code=str(sector_code),
            benchmark_code=str(sector_code),
        )

    # The existing engine computes both axes, but this builder intentionally
    # supplies an empty market frame and exposes only the independent sector
    # fields.  Market RS remains the exact-date authority CSV consumer.
    result = compute_relative_strength_features(
        ticker=clean_ticker,
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=_EMPTY_MARKET_INDEX,
        market=market_str,
        sector_index_df=sector_index_df,
        sector_mapping=sector_mapping,
        require_exact_sector_snapshot=True,
        sector_snapshot_effective_date=as_of,
    )
    status = result.sector_rs_data_status.value
    reason = result.sector_rs_input_reason
    if status == RelativeStrengthDataStatus.DATA_UNAVAILABLE.value and reason is None:
        reason = "SECTOR_BENCHMARK_ASOF_UNAVAILABLE"

    explanation = _ready_explanation(result) if status == RelativeStrengthDataStatus.READY.value else None
    return SectorRelativeStrengthSection(
        applicability="APPLICABLE",
        data_status=status,
        input_reason=reason,
        sector_name=result.sector_name or str(sector_name),
        sector_code=result.sector_code or str(sector_code),
        benchmark_code=result.sector_benchmark_code or str(sector_code),
        benchmark_last_observation_date=result.sector_benchmark_last_observation_date,
        sector_return_3m=result.sector_return_3m,
        sector_return_6m=result.sector_return_6m,
        sector_return_12m=result.sector_return_12m,
        sector_return_2w=result.sector_return_2w,
        sector_return_1m=result.sector_return_1m,
        sector_rs_3m=result.sector_rs_3m,
        sector_rs_6m=result.sector_rs_6m,
        sector_rs_12m=result.sector_rs_12m,
        sector_rs_2w=result.sector_rs_2w,
        sector_rs_1m=result.sector_rs_1m,
        sector_anchor_date_3m=result.sector_anchor_date_3m,
        sector_anchor_date_6m=result.sector_anchor_date_6m,
        sector_anchor_date_12m=result.sector_anchor_date_12m,
        sector_anchor_date_2w=result.sector_anchor_date_2w,
        sector_anchor_date_1m=result.sector_anchor_date_1m,
        explanation=explanation or _empty_section(
            applicability="APPLICABLE",
            data_status=status,
            input_reason=reason,
        ).explanation,
        source_as_of=as_of,
        membership_snapshot_date=membership_snapshot_date,
        membership_source=membership_source,
        sector_index_source=sector_index_source,
    )


__all__ = ["build_sector_relative_strength_section", "SECTOR_INDEX_SOURCE"]
