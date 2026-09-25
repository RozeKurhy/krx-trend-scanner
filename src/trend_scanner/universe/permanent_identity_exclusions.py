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
    ("069460", "KR7069460004"): {
        "reason": "user-approved permanent exclusion because authoritative terminal pricing is unavailable through the P3-2 cutoff",
        "approval_scope": "P3-2 final closure V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("246720", "KR7246720007"): {
        "reason": "user-approved permanent exclusion because authoritative terminal pricing is unavailable through the P3-2 cutoff",
        "approval_scope": "P3-2 final closure V01",
        "approved_date": "2026-09-25",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("001140", "KR7001140003"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("009730", "KR7009730003"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by an empty resampler week bucket",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "A_PIPELINE_BUG",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("031980", "KR7031980006"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("035290", "KR7035290006"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("036260", "KR7036260008"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("036620", "KR7036620003"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by an empty resampler week bucket",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "A_PIPELINE_BUG",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("043710", "KR7043710003"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("044060", "KR7044060002"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("052300", "KR7052300001"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by an empty resampler week bucket",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "A_PIPELINE_BUG",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("052400", "KR7052400009"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("068150", "KR7068150002"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("130660", "KR7130660004"): {
        "reason": "user-approved permanent exclusion for P1 Pattern A stage UNAVAILABLE caused by Repository V2 source gaps",
        "approval_scope": "P1 UNAVAILABLE 12 permanent exclusion V01",
        "failure_class": "C_SOURCE_OR_AUTHORITY_GAP",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("005950", "KR7005950001"): {
        "reason": "user-approved permanent exclusion after a P1 soft-exit next-session execution contract mismatch",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_EXECUTION_ANOMALY",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("002250", "KR7002250009"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("002270", "KR7002270007"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("002550", "KR7002550002"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("003450", "KR7003450004"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("003600", "KR7003600004"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("005190", "KR7005190004"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("008020", "KR7008020000"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("008720", "KR7008720005"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("013450", "KR7013450002"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("016170", "KR7016170003"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("019680", "KR7019680008"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("020760", "KR7020760005"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("031860", "KR7031860000"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("032980", "KR7032980005"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("033630", "KR7033630005"): {
        "reason": "user-approved permanent exclusion for a delisted P1 identity with an unexecuted signal and lifecycle gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("033660", "KR7033660002"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("043220", "KR7043220003"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("123100", "KR7123100000"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
        "policy_version": "permanent_identity_exclusions_v01",
    },
    ("130960", "KR7130960008"): {
        "reason": "user-approved permanent exclusion after a P1 lifecycle remediable-unresolved gate finding",
        "approval_scope": "P1 final exclusion closure V02",
        "failure_class": "P1_LIFECYCLE_REMEDIABLE_UNRESOLVED",
        "approved_date": "2026-09-26",
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
