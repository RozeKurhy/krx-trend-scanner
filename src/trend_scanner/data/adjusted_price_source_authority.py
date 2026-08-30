"""Durable authority binding for the adjusted-price production source."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from trend_scanner.data.errors import MarketDataError


SOURCE_AUTHORITY_ID = "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1"
SOURCE_NAME = "NAVER_DIRECT_DATE_RANGE_ADJUSTED"
SOURCE_ENDPOINT = "https://fchart.stock.naver.com/sise.nhn"
SOURCE_REQUEST_TYPE = 1
SOURCE_TIMEFRAME = "day"
SOURCE_SEMANTICS = "ADJUSTED_OHLC_ONLY"
AUTHORITY_TYPE = "AUTHORITATIVE"
CLOSURE_VERSION = "V02"
CLOSURE_ARTIFACT_HEAD = "b5e785d92db7b24fadef21fd36602d305dd092de"
CLOSURE_ARTIFACT_TREE = "65e6bb999f0fc83f1477912a127d53ed82cc7f77"
FIX02_HEAD = "99ce7d0b8127f48af3b8b002c246a6c4b0a4395d"
FIX02_TREE = "4dfacef5ffe750675f5fc224003c64504f620603"
AUTHORITY_DECISION_SHA256 = "07d191f5e7cbf73a090945cd1751145bd131ca89e6e4d2cc948e2969fd943eba"
DEFAULT_AUTHORITY_DECISION_PATH = Path(
    "artifacts/data/end_to_end_data_parity/v01/"
    "adjusted_price_source_authority_review/authority_closure/v02/"
    "authority_closure_decision_v02.json"
)


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_path() -> Path:
    candidates = [Path.cwd() / DEFAULT_AUTHORITY_DECISION_PATH]
    # src/trend_scanner/data/<module> -> repository root
    candidates.append(Path(__file__).resolve().parents[3] / DEFAULT_AUTHORITY_DECISION_PATH)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _fail(reason: str) -> MarketDataError:
    return MarketDataError(f"SOURCE_AUTHORITY_INVALID: {reason}")


def load_adjusted_price_source_authority(
    decision_path: Path | str | None = None,
    expected_sha256: str = AUTHORITY_DECISION_SHA256,
) -> AdjustedPriceSourceDescriptor:
    """Load and validate the immutable Closure V02 authority decision."""

    path = Path(decision_path) if decision_path is not None else _default_path()
    if not path.exists():
        raise _fail(f"decision file missing: {path}")
    try:
        actual_sha = _sha256(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _fail(f"decision file unreadable: {path}") from exc
    if actual_sha != expected_sha256:
        raise _fail(f"decision SHA mismatch: {actual_sha}")
    if not isinstance(payload, dict):
        raise _fail("decision is not a JSON object")
    required = {
        "schema": "authority_closure_decision_v02",
        "authority_closure": "CLOSED",
        "review_decision": "APPROVED_FOR_PRODUCTION_INTEGRATION",
        "production_integration_authorized": True,
        "all_gates_passed": True,
        "fix02_head": FIX02_HEAD,
        "fix02_tree": FIX02_TREE,
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise _fail(f"decision field {key!r} is not bound to Closure V02")
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
    "DEFAULT_AUTHORITY_DECISION_PATH",
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
