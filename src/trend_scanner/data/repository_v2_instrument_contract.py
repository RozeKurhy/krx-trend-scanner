"""Repository V2 instrument contracts.

The repository composes the same adjusted/raw interface for every supported
instrument type.  This module records the authority semantics explicitly so
ETF support cannot be implemented as a consumer-specific legacy-cache path.
It does not acquire data and it never infers an instrument type from a ticker
shape or name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trend_scanner.data.errors import MarketDataError


SUPPORTED_INSTRUMENT_TYPES = ("COMMON", "ETF")


@dataclass(frozen=True)
class RepositoryV2InstrumentContract:
    """Authority and session semantics for one Repository V2 instrument type."""

    instrument_type: str
    adjusted_ohlc_authority: str
    raw_ohlc_authority: str
    volume_authority: str
    trading_value_authority: str
    date_range_policy: str
    session_policy: str
    lifecycle_policy: str


COMMON_CONTRACT = RepositoryV2InstrumentContract(
    instrument_type="COMMON",
    adjusted_ohlc_authority="AdjustedPriceStore/NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1",
    raw_ohlc_authority="KrxRawStockStore/KRX_OPEN_API_STOCK_DAILY",
    volume_authority="KrxRawStockStore/KRX_OPEN_API_STOCK_DAILY",
    trading_value_authority="KrxRawStockStore/KRX_OPEN_API_STOCK_DAILY",
    date_range_policy="exact source-authority range; no forward/backfill",
    session_policy="adjusted/raw exact session set after explicit placeholder projection",
    lifecycle_policy="PIT formal instrument identity; no ticker-specific override",
)


ETF_CONTRACT = RepositoryV2InstrumentContract(
    instrument_type="ETF",
    adjusted_ohlc_authority="AdjustedPriceStore/NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1",
    raw_ohlc_authority="KrxRawStockStore/KRX_OPEN_API_ETF_DAILY",
    volume_authority="KrxRawStockStore/KRX_OPEN_API_ETF_DAILY",
    trading_value_authority="KrxRawStockStore/KRX_OPEN_API_ETF_DAILY",
    date_range_policy="exact ETF source-authority range; no forward/backfill",
    session_policy="ETF adjusted/raw exact session set after explicit placeholder projection",
    lifecycle_policy="PIT formal ETF product-master identity; listing dates bound to source authority",
)


_CONTRACTS = {contract.instrument_type: contract for contract in (COMMON_CONTRACT, ETF_CONTRACT)}


def repository_v2_contract_for(instrument_type: str) -> RepositoryV2InstrumentContract:
    """Return a supported contract or fail closed for an unknown type."""

    key = str(instrument_type).strip().upper()
    try:
        return _CONTRACTS[key]
    except KeyError as exc:
        raise MarketDataError("UNSUPPORTED_INSTRUMENT_TYPE") from exc


def repository_v2_contract_for_metadata(metadata: Any) -> RepositoryV2InstrumentContract:
    """Resolve a contract only from an officially classified metadata record.

    The resolver intentionally accepts a metadata object rather than a ticker
    string.  Callers must provide the local PIT resolver's formal authority;
    heuristic/name-based ETF classification is rejected.
    """

    if metadata is None or not bool(getattr(metadata, "is_trusted_for_production", False)):
        raise MarketDataError("INSTRUMENT_CLASSIFICATION_UNTRUSTED")
    return repository_v2_contract_for(str(getattr(metadata, "asset_type", "")))


__all__ = [
    "COMMON_CONTRACT",
    "ETF_CONTRACT",
    "RepositoryV2InstrumentContract",
    "SUPPORTED_INSTRUMENT_TYPES",
    "repository_v2_contract_for",
    "repository_v2_contract_for_metadata",
]
