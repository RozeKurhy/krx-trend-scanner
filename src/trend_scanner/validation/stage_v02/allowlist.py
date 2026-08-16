"""Stage v0.2 Candidate Raw Feature Allowlist and Canonical Hash Serialization."""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Any

# Candidate stage classifier & lifecycle reducer가 실제로 읽는 FeatureRow raw fields
CANDIDATE_RAW_FEATURE_ALLOWLIST: tuple[str, ...] = (
    "ma6",
    "ma12",
    "ma24",
    "ma24_slope",
    "weekly_ma12_slope",
    "ma24_slope_acceleration",
    "avg_price_change_12m",
    "ma_spread",
    "ma_spread_ratio",
    "range_position",
    "distance_to_resistance",
)

CANDIDATE_RULE_SPEC_VERSION: str = "v0.2-candidate-freeze-1"
HASH_SERIALIZER_CONTRACT_VERSION: str = "1.0.0"


def canonicalize_for_hash(value: Any) -> Any:
    """Deterministic JSON-serializable canonical data structure for SHA256 hashing.

    Rules:
    - None -> None (serialized to null)
    - NaN -> "__NaN__"
    - +Inf -> "__POS_INF__"
    - -Inf -> "__NEG_INF__"
    - -0.0 -> 0.0
    - Enum -> enum.value
    - tuple / list -> list of canonicalized items
    - dict -> dict with sorted keys and canonicalized values
    - float -> normalized finite float (or int if integer)
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "__NaN__"
        if math.isinf(value):
            return "__POS_INF__" if value > 0 else "__NEG_INF__"
        if value == 0.0:
            return 0.0
        return value
    if isinstance(value, (list, tuple)):
        return [canonicalize_for_hash(item) for item in value]
    if isinstance(value, dict):
        return {str(k): canonicalize_for_hash(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if hasattr(value, "__dataclass_fields__"):
        # Dataclass conversion
        d = {k: getattr(value, k) for k in value.__dataclass_fields__}
        return canonicalize_for_hash(d)
    return str(value)


def compute_canonical_sha256(payload: Any) -> str:
    """Compute deterministic SHA256 hash from canonicalized payload."""
    canonical_data = canonicalize_for_hash(payload)
    serialized = json.dumps(
        canonical_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
