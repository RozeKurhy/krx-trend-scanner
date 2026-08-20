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

        return pd.DataFrame(columns=["ticker", "name", "market", "asset_type", "metadata_source", "effective_date"])

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

                if not past_matches.empty:
                    # Select latest snapshot not after requested_as_of
                    row = past_matches.sort_values(by="effective_date", ascending=True).iloc[-1]
                    name = str(row["name"]).strip() if "name" in row and not pd.isna(row["name"]) else clean_ticker
                    market = str(row["market"]).strip().upper() if "market" in row and not pd.isna(row["market"]) else "UNKNOWN"
                    asset_type = str(row["asset_type"]).strip().upper() if "asset_type" in row and not pd.isna(row["asset_type"]) else "UNKNOWN"
                    source = str(row["metadata_source"]).strip() if "metadata_source" in row and not pd.isna(row["metadata_source"]) else "LOCAL_AUTHORITY"
                    eff_date = str(row["effective_date"]).strip() if "effective_date" in row and not pd.isna(row["effective_date"]) else as_of_str
                    auth = str(row["classification_authority"]).strip() if "classification_authority" in row and not pd.isna(row["classification_authority"]) else "FORMAL_SECURITY_TYPE"
                    asset_source = str(row["asset_type_source"]).strip() if "asset_type_source" in row and not pd.isna(row["asset_type_source"]) else "FORMAL_SECURITY_TYPE"

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
            classification_authority=None,
            asset_type_source=None,
        )


def resolve_instrument_metadata(
    ticker: str,
    as_of: str | None = None,
    repo_root: Path | None = None,
) -> InstrumentMetadata:
    """Convenience helper to resolve instrument metadata."""
    return InstrumentMetadataResolver.resolve(ticker=ticker, as_of=as_of, repo_root=repo_root)
