"""Canonical KRX Instrument Metadata Authority.

Provides pure local, zero-network resolution of security metadata (name, listing market, asset type)
from canonical local reference authorities:
  1. data/reference/krx_instrument_metadata.parquet (or .csv)
  2. data/processed/pattern_a_universe_quality.csv
  3. PIT-bounded investability universe snapshots

Explicitly distinguishes listing market (KOSPI/KOSDAQ/KONEX) from instrument asset type (COMMON/ETF/PREFERRED/etc.)
to prevent semantic confusion and ensure fail-closed applicability handling.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import ClassVar

import pandas as pd

from trend_scanner.universe.models import AssetType, MarketType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstrumentMetadata:
    """Formal instrument identification and classification record."""

    ticker: str
    name: str
    market: str
    asset_type: str
    metadata_source: str
    effective_date: str | None = None
    is_identified: bool = True
    classification_authority: str | None = None
    asset_type_source: str | None = None

    @property
    def is_common_stock(self) -> bool:
        return self.is_identified and self.asset_type == AssetType.COMMON.value

    @property
    def is_trusted_for_production(self) -> bool:
        """Production A FAST Core applicability에 asset_type을 신뢰해도 되는지.

        row가 존재하고 asset_type이 COMMON이더라도 provenance가 FORMAL_SECURITY_TYPE이
        아니면(UNKNOWN 또는 LEGACY_HEURISTIC) production에서는 신뢰하지 않는다
        (Fix Round 04 Critical 1: formal source를 증명하지 못하면 fail closed).
        """
        return (
            self.is_identified
            and self.classification_authority == "FORMAL_SECURITY_TYPE"
            and self.asset_type_source == "FORMAL_SECURITY_TYPE"
            and self.asset_type != AssetType.UNKNOWN.value
        )

    @property
    def is_common_stock_for_production(self) -> bool:
        return self.is_trusted_for_production and self.asset_type == AssetType.COMMON.value

    @property
    def is_eligible_for_historical_legacy_research(self) -> bool:
        """requested_as_of 시점이 production 신뢰 대상은 아니지만 retrospective
        연구용으로는 취급 가능한지 (Fix Round 06 Major 1, Fix Round 07 Major 1로 재정의).

        Fix Round 06은 이 판단에 "이 ticker가 requested_as_of *이후*에 실제로
        formal 재검증된 적이 있는가"(has_later_verified_snapshot)를 근거로
        사용했다. 이는 survivorship bias다 — 미래까지 살아남아 다시 검증된
        ticker만 retrospective 분석이 가능해지고, 상장폐지되어 다시 검증될
        기회가 없었던 ticker(예: 380440)는 동일한 품질의 historical metadata를
        가지고도 부당하게 배제된다. 또한 이 판단 자체가 미래 시점의 정보를
        과거 시점 조회의 eligibility 결정에 사용하는 것이라 Strict PIT 정신에도
        어긋난다.

        Fix Round 07부터 이 판단은 오직 **선택된(selected) PIT row 자체의 값**만
        본다 — 미래의 다른 row는 전혀 조회하지 않는다: classification_authority와
        asset_type_source가 둘 다 정확히 "LEGACY_UNVERIFIED"이고(다른 종류의
        untrusted provenance, 예: LEGACY_HEURISTIC/NAME_BASED_HEURISTIC은 여기
        해당하지 않는다 — 그런 row는 애초에 formal frozen PIT snapshot이 아니라
        신뢰도가 다른 heuristic 추정치이므로 승격 금지), asset_type이 UNKNOWN이
        아니면 historical retrospective 연구 대상으로 인정한다.
        """
        return (
            self.is_identified
            and self.classification_authority == "LEGACY_UNVERIFIED"
            and self.asset_type_source == "LEGACY_UNVERIFIED"
            and self.asset_type != AssetType.UNKNOWN.value
        )


class InstrumentMetadataResolver:
    """Memoized local instrument metadata resolver with Strict PIT guarantee."""

    _cached_df: ClassVar[pd.DataFrame | None] = None
    _cached_repo_root: ClassVar[Path | None] = None

    @classmethod
    def clear_cache(cls) -> None:
        """Clear memoized master dataframe (useful for testing fixture isolation)."""
        cls._cached_df = None
        cls._cached_repo_root = None

    @classmethod
    def load_master_dataframe(cls, repo_root: Path | None = None) -> pd.DataFrame:
        root = repo_root or Path.cwd()
        if cls._cached_df is not None and cls._cached_repo_root == root:
            return cls._cached_df

        # 1. Primary: data/reference/krx_instrument_metadata.parquet
        pq_path = root / "data/reference/krx_instrument_metadata.parquet"
        csv_ref_path = root / "data/reference/krx_instrument_metadata.csv"
        quality_csv = root / "data/processed/pattern_a_universe_quality.csv"

        df: pd.DataFrame | None = None
        if pq_path.exists():
            try:
                df = pd.read_parquet(pq_path)
            except Exception as exc:
                logger.warning("Failed reading %s: %s", pq_path, exc)

        if df is None and csv_ref_path.exists():
            try:
                df = pd.read_csv(csv_ref_path, dtype={"ticker": str})
            except Exception as exc:
                logger.warning("Failed reading %s: %s", csv_ref_path, exc)

        if df is None and quality_csv.exists():
            try:
                df = pd.read_csv(quality_csv, dtype={"ticker": str})
                if "classification_authority" not in df.columns:
                    df["classification_authority"] = "LEGACY_HEURISTIC"
                if "asset_type_source" not in df.columns:
                    df["asset_type_source"] = "NAME_BASED_HEURISTIC"
                if "metadata_source" not in df.columns:
                    df["metadata_source"] = "LEGACY_QUALITY_DIAGNOSTIC"
            except Exception as exc:
                logger.warning("Failed reading %s: %s", quality_csv, exc)

        if df is not None:
            df = df.copy()
            df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(6)
            if "effective_date" not in df.columns:
                df["effective_date"] = None
            cls._cached_df = df
            cls._cached_repo_root = root
            return df

        return pd.DataFrame(columns=["ticker", "name", "market", "asset_type", "metadata_source", "effective_date", "classification_authority", "asset_type_source"])

    @classmethod
    def resolve(
        cls,
        ticker: str,
        as_of: str | None = None,
        repo_root: Path | None = None,
    ) -> InstrumentMetadata:
        """Resolve instrument metadata ensuring Strict PIT (effective_date <= requested_as_of)."""
        clean_ticker = str(ticker).strip().zfill(6)
        as_of_str = str(as_of).strip()[:10] if as_of else None
        df_master = cls.load_master_dataframe(repo_root)

        if not df_master.empty:
            matches = df_master[df_master["ticker"] == clean_ticker]
            if not matches.empty:
                # Enforce Strict PIT on metadata effective date:
                # Reject future metadata if requested_as_of is specified.
                if as_of_str is not None and "effective_date" in matches.columns:
                    past_matches = matches[
                        matches["effective_date"].notna()
                        & (matches["effective_date"].astype(str).str[:10] <= as_of_str)
                    ]
                else:
                    past_matches = matches

                # Fix Round 07 Major 1: HISTORICAL_LEGACY_RESEARCH eligibility는 selected
                # row 자체의 provenance만으로 결정한다 (is_eligible_for_historical_legacy_research
                # 참고) — requested_as_of 이후의 다른 row를 조회하는 future lookup은 여기서도,
                # 다른 어디에서도 수행하지 않는다 (survivorship bias 제거, Strict PIT 유지).
                if not past_matches.empty:
                    # Select latest snapshot not after requested_as_of
                    row = past_matches.sort_values(by="effective_date", ascending=True).iloc[-1]
                    name = str(row["name"]).strip() if "name" in row and not pd.isna(row["name"]) else clean_ticker
                    market = str(row["market"]).strip().upper() if "market" in row and not pd.isna(row["market"]) else "UNKNOWN"
                    asset_type = str(row["asset_type"]).strip().upper() if "asset_type" in row and not pd.isna(row["asset_type"]) else "UNKNOWN"
                    source = str(row["metadata_source"]).strip() if "metadata_source" in row and not pd.isna(row["metadata_source"]) else "LOCAL_AUTHORITY"
                    eff_date = str(row["effective_date"]).strip() if "effective_date" in row and not pd.isna(row["effective_date"]) else as_of_str
                    auth = str(row["classification_authority"]).strip() if ("classification_authority" in row and not pd.isna(row["classification_authority"])) else "UNKNOWN"
                    asset_source = str(row["asset_type_source"]).strip() if ("asset_type_source" in row and not pd.isna(row["asset_type_source"])) else "UNKNOWN"

                    # Normalization
                    if market not in [m.value for m in MarketType]:
                        market = MarketType.UNKNOWN.value
                    if asset_type not in [a.value for a in AssetType]:
                        asset_type = AssetType.UNKNOWN.value

                    return InstrumentMetadata(
                        ticker=clean_ticker,
                        name=name,
                        market=market,
                        asset_type=asset_type,
                        metadata_source=source,
                        effective_date=eff_date,
                        is_identified=True,
                        classification_authority=auth,
                        asset_type_source=asset_source,
                    )

        # Fail closed: metadata unavailable or all available metadata is in the future
        return InstrumentMetadata(
            ticker=clean_ticker,
            name=clean_ticker,
            market=MarketType.UNKNOWN.value,
            asset_type=AssetType.UNKNOWN.value,
            metadata_source="METADATA_UNAVAILABLE",
            effective_date=None,
            is_identified=False,
            classification_authority="UNKNOWN",
            asset_type_source="UNKNOWN",
        )


def resolve_instrument_metadata(
    ticker: str,
    as_of: str | None = None,
    repo_root: Path | None = None,
) -> InstrumentMetadata:
    """Convenience helper to resolve instrument metadata."""
    return InstrumentMetadataResolver.resolve(ticker=ticker, as_of=as_of, repo_root=repo_root)
