"""Stage v0.2 Candidate Analysis and Validation Package."""

from __future__ import annotations

from trend_scanner.validation.stage_v02.allowlist import (
    CANDIDATE_RAW_FEATURE_ALLOWLIST,
    CANDIDATE_RULE_SPEC_VERSION,
    canonicalize_for_hash,
    compute_canonical_sha256,
)
from trend_scanner.validation.stage_v02.comparator import (
    StageMatchClass,
    classify_stage_match,
)
from trend_scanner.validation.stage_v02.candidate_classifier import (
    CandidateDiagnostics,
    CandidateStageResult,
    classify_pattern_a_stage_v02_candidate,
)
from trend_scanner.validation.stage_v02.lifecycle_stream import (
    CanonicalLifecycleEventResult,
    CandidateRequestEvaluation,
    LifecycleStreamEngine,
)

__all__ = [
    "CANDIDATE_RAW_FEATURE_ALLOWLIST",
    "CANDIDATE_RULE_SPEC_VERSION",
    "canonicalize_for_hash",
    "compute_canonical_sha256",
    "StageMatchClass",
    "classify_stage_match",
    "CandidateDiagnostics",
    "CandidateStageResult",
    "classify_pattern_a_stage_v02_candidate",
    "CanonicalLifecycleEventResult",
    "CandidateRequestEvaluation",
    "LifecycleStreamEngine",
]
