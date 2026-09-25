"""User-approved permanent identity exclusions for research universes.

Keep this policy outside the frozen PIT authority: it is an explicit,
downstream universe rule and must not rewrite authoritative source records.
Callers should apply it once while constructing the shared universe, before
splitting observations into strategy/control populations.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


PERMANENT_IDENTITY_EXCLUSIONS: dict[tuple[str, str], dict[str, str]] = {
    ("010420", "KR7010420008"): {
        "reason": "user-approved permanent exclusion for the 2025-09-25 delisting / wholly owned subsidiary lifecycle",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("005390", "KR7005390000"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("006390", "KR7006390009"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("031440", "KR7031440001"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("049770", "KR7049770001"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("057050", "KR7057050007"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("138490", "KR7138490008"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("335890", "KR7335890000"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("950110", "KR8392070007"): {
        "reason": "user-approved permanent exclusion for a rare lifecycle identity in the P3-2 audit roster",
        "approval_scope": "P3-2 recertification V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
}


def apply_permanent_identity_exclusions(
    segments: Iterable[Any],
) -> tuple[list[Any], list[dict[str, str]]]:
    """Return kept segments and an auditable record for each removed interval.

    Matching requires both ticker and stable ISU code, so a later ticker reuse
    for a different security identity is not excluded by this policy.
    """
    kept: list[Any] = []
    excluded: list[dict[str, str]] = []
    for segment in segments:
        ticker = str(getattr(segment, "ticker", "")).strip().zfill(6)
        isu_cd = str(getattr(segment, "isu_cd", "")).strip().upper()
        policy = PERMANENT_IDENTITY_EXCLUSIONS.get((ticker, isu_cd))
        if policy is None:
            kept.append(segment)
            continue
        excluded.append(
            {
                "ticker": ticker,
                "isu_cd": isu_cd,
                "market": str(getattr(segment, "market", "")),
                "effective_from": str(getattr(segment, "effective_from", ""))[:10],
                "effective_to": str(getattr(segment, "effective_to", ""))[:10],
                **policy,
            }
        )
    return kept, excluded
