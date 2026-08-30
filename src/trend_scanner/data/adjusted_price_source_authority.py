"""Package-owned adjusted-price authority contract adapter.

Closure evidence is audited by offline tests and is never read by production
runtime initialization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.source_contracts import ADJUSTED_PRICE_AUTHORITY_CONTRACT


SOURCE_AUTHORITY_ID = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["authority_id"])
SOURCE_NAME = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["source_name"])
SOURCE_ENDPOINT = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["source_endpoint"])
SOURCE_REQUEST_TYPE = int(ADJUSTED_PRICE_AUTHORITY_CONTRACT["request_type"])
SOURCE_TIMEFRAME = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["timeframe"])
SOURCE_SEMANTICS = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["source_semantics"])
AUTHORITY_TYPE = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["authority_type"])
CLOSURE_VERSION = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["closure_version"])
CLOSURE_ARTIFACT_HEAD = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["closure_artifact_head"])
CLOSURE_ARTIFACT_TREE = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["closure_artifact_tree"])
FIX02_HEAD = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["fix02_head"])
FIX02_TREE = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["fix02_tree"])
AUTHORITY_DECISION_SHA256 = str(ADJUSTED_PRICE_AUTHORITY_CONTRACT["authority_decision_sha256"])


@dataclass(frozen=True)
class AdjustedPriceSourceDescriptor:
    source_authority_id: str = SOURCE_AUTHORITY_ID
    source_name: str = SOURCE_NAME
    source_endpoint: str = SOURCE_ENDPOINT
    source_request_type: int = SOURCE_REQUEST_TYPE
    source_semantics: str = SOURCE_SEMANTICS
    authority_type: str = AUTHORITY_TYPE
    closure_version: str = CLOSURE_VERSION
    closure_artifact_head: str = CLOSURE_ARTIFACT_HEAD
    closure_artifact_tree: str = CLOSURE_ARTIFACT_TREE
    authority_decision_sha256: str = AUTHORITY_DECISION_SHA256

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CURRENT_SOURCE_DESCRIPTOR = AdjustedPriceSourceDescriptor()


def load_adjusted_price_source_authority(
    decision_path: Any = None, expected_sha256: str | None = None
) -> AdjustedPriceSourceDescriptor:
    """Return the immutable package contract without filesystem IO."""

    if decision_path is not None or (
        expected_sha256 is not None and expected_sha256 != AUTHORITY_DECISION_SHA256
    ):
        raise MarketDataError(
            "SOURCE_AUTHORITY_INVALID: runtime authority is package-owned; "
            "validate Closure evidence in an offline audit"
        )
    return CURRENT_SOURCE_DESCRIPTOR


def descriptor_from(value: Any) -> AdjustedPriceSourceDescriptor:
    """Convert a descriptor-like object without accepting partial provenance."""

    if isinstance(value, AdjustedPriceSourceDescriptor):
        return value
    if isinstance(value, Mapping):
        fields = set(CURRENT_SOURCE_DESCRIPTOR.as_dict())
        if set(value) != fields:
            raise MarketDataError("PROVIDER_AUTHORITY_MISMATCH: source descriptor fields are incomplete")
        try:
            return AdjustedPriceSourceDescriptor(**dict(value))
        except (TypeError, ValueError) as exc:
            raise MarketDataError("PROVIDER_AUTHORITY_MISMATCH: invalid source descriptor") from exc
    raise MarketDataError("PROVIDER_AUTHORITY_MISMATCH: provider has no valid source descriptor")


def assert_current_descriptor(value: Any) -> AdjustedPriceSourceDescriptor:
    descriptor = descriptor_from(value)
    if descriptor != CURRENT_SOURCE_DESCRIPTOR:
        raise MarketDataError("PROVIDER_AUTHORITY_MISMATCH: source descriptor is not current Closure V02 authority")
    return descriptor


__all__ = [
    "AUTHORITY_DECISION_SHA256",
    "AUTHORITY_TYPE",
    "AdjustedPriceSourceDescriptor",
    "CURRENT_SOURCE_DESCRIPTOR",
    "CLOSURE_ARTIFACT_HEAD",
    "CLOSURE_ARTIFACT_TREE",
    "CLOSURE_VERSION",
    "SOURCE_AUTHORITY_ID",
    "SOURCE_ENDPOINT",
    "SOURCE_NAME",
    "SOURCE_REQUEST_TYPE",
    "SOURCE_SEMANTICS",
    "FIX02_HEAD",
    "FIX02_TREE",
    "assert_current_descriptor",
    "descriptor_from",
    "load_adjusted_price_source_authority",
]
