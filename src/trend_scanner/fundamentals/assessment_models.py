"""Deterministic, provenance-preserving Fundamentals Assessment models.

Assessment models deliberately contain no score, price, market, or provider
state.  They are the serializable boundary between the assessment engine and
future report/UI consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AssessmentEvidence:
    """One auditable explanation code derived from a Derived Metric."""

    axis: str
    metric: str
    metric_type: str
    fiscal_year: str
    fiscal_period: str
    value: Any
    classification: str | None
    direction: str
    explanation_code: str
    requested_as_of: str | None
    pit_available_from: str | None
    source_rcept_nos: tuple[str, ...] = ()
    source_rcept_dts: tuple[str, ...] = ()
    source_sha256s: tuple[str, ...] = ()
    status: str = "READY"
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "metric": self.metric,
            "metric_type": self.metric_type,
            "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period,
            "value": self.value,
            "classification": self.classification,
            "direction": self.direction,
            "explanation_code": self.explanation_code,
            "requested_as_of": self.requested_as_of,
            "pit_available_from": self.pit_available_from,
            "source_rcept_nos": list(self.source_rcept_nos),
            "source_rcept_dts": list(self.source_rcept_dts),
            "source_sha256s": list(self.source_sha256s),
            "status": self.status,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FundamentalsAssessmentResult:
    """Complete deterministic assessment for one ticker and one PIT cutoff."""

    ticker: str
    company_family: str
    requested_as_of: str | None
    current_fiscal_year: str | None
    current_fiscal_period: str | None
    overall_state: str
    growth_state: str
    profitability_state: str
    cash_flow_state: str
    momentum_state: str
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    evidence: tuple[AssessmentEvidence, ...]
    available_axis_count: int
    missing_axis_count: int
    pit_available_from: str | None
    status: str
    matched_rule_id: str
    total_axis_count: int = 4
    available_evidence_count: int = 0
    missing_evidence_count: int = 0
    axis_resolution: Mapping[str, str] = field(default_factory=dict)
    assessment_rule_conflict_count: int = 0
    assessment_rule_mismatch_count: int = 0
    assessment_scope: str = "EXPLICIT_RANGE"
    currentness_status: str = "RANGE_ONLY"
    growth_direction: str = "UNAVAILABLE"
    profitability_direction: str = "UNAVAILABLE"
    cash_flow_direction: str = "UNAVAILABLE"
    axis_directions: Mapping[str, str] = field(default_factory=dict)
    improving_direction_axis_count: int = 0
    deteriorating_direction_axis_count: int = 0
    negative_level_axis_count: int = 0
    matched_candidate_rules: tuple[str, ...] = ()
    expected_rule_overlaps: tuple[tuple[str, str], ...] = ()
    reason: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strengths", tuple(self.strengths))
        object.__setattr__(self, "risks", tuple(self.risks))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "axis_resolution", dict(self.axis_resolution))
        object.__setattr__(self, "axis_directions", dict(self.axis_directions))
        object.__setattr__(self, "matched_candidate_rules", tuple(self.matched_candidate_rules))
        object.__setattr__(self, "expected_rule_overlaps", tuple(tuple(item) for item in self.expected_rule_overlaps))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "company_family": self.company_family,
            "requested_as_of": self.requested_as_of,
            "current_fiscal_year": self.current_fiscal_year,
            "current_fiscal_period": self.current_fiscal_period,
            "overall_state": self.overall_state,
            "growth_state": self.growth_state,
            "profitability_state": self.profitability_state,
            "cash_flow_state": self.cash_flow_state,
            "momentum_state": self.momentum_state,
            "strengths": list(self.strengths),
            "risks": list(self.risks),
            "evidence": [item.to_dict() for item in self.evidence],
            "available_axis_count": self.available_axis_count,
            "missing_axis_count": self.missing_axis_count,
            "total_axis_count": self.total_axis_count,
            "available_evidence_count": self.available_evidence_count,
            "missing_evidence_count": self.missing_evidence_count,
            "pit_available_from": self.pit_available_from,
            "status": self.status,
            "matched_rule_id": self.matched_rule_id,
            "axis_resolution": dict(self.axis_resolution),
            "assessment_rule_conflict_count": self.assessment_rule_conflict_count,
            "assessment_rule_mismatch_count": self.assessment_rule_mismatch_count,
            "assessment_scope": self.assessment_scope,
            "currentness_status": self.currentness_status,
            "growth_direction": self.growth_direction,
            "profitability_direction": self.profitability_direction,
            "cash_flow_direction": self.cash_flow_direction,
            "axis_directions": dict(self.axis_directions),
            "improving_direction_axis_count": self.improving_direction_axis_count,
            "deteriorating_direction_axis_count": self.deteriorating_direction_axis_count,
            "negative_level_axis_count": self.negative_level_axis_count,
            "matched_candidate_rules": list(self.matched_candidate_rules),
            "expected_rule_overlaps": [list(item) for item in self.expected_rule_overlaps],
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }
