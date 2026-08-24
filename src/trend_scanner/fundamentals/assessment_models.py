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
class SamePeriodYoYPoint:
    """One same-fiscal-period YoY point retained for multi-year diagnostics."""

    fiscal_year: str
    fiscal_period: str
    metric: str
    metric_type: str
    yoy_value: Any
    resolution_status: str
    pit_available_from: str | None
    source_rcept_nos: tuple[str, ...] = ()
    source_rcept_dts: tuple[str, ...] = ()
    source_sha256s: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period,
            "metric": self.metric,
            "metric_type": self.metric_type,
            "yoy_value": self.yoy_value,
            "resolution_status": self.resolution_status,
            "pit_available_from": self.pit_available_from,
            "source_rcept_nos": list(self.source_rcept_nos),
            "source_rcept_dts": list(self.source_rcept_dts),
            "source_sha256s": list(self.source_sha256s),
        }


@dataclass(frozen=True)
class SamePeriodYoYSeries:
    """Deterministic same-period series and its contiguous trend result."""

    metric: str
    fiscal_period: str
    points: tuple[SamePeriodYoYPoint, ...]
    usable_yoy_point_count: int
    trend_state: str
    contiguous_fiscal_years: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))
        object.__setattr__(self, "contiguous_fiscal_years", tuple(self.contiguous_fiscal_years))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "fiscal_period": self.fiscal_period,
            "points": [item.to_dict() for item in self.points],
            "usable_yoy_point_count": self.usable_yoy_point_count,
            "trend_state": self.trend_state,
            "contiguous_fiscal_years": list(self.contiguous_fiscal_years),
        }


@dataclass(frozen=True)
class DirectionComponent:
    """One independently resolved directional component."""

    axis: str
    component_id: str
    metric: str
    state: str
    evidence_codes: tuple[str, ...] = ()
    source_periods: tuple[str, ...] = ()
    source_fiscal_years: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_codes", tuple(self.evidence_codes))
        object.__setattr__(self, "source_periods", tuple(self.source_periods))
        object.__setattr__(self, "source_fiscal_years", tuple(self.source_fiscal_years))

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "component_id": self.component_id,
            "metric": self.metric,
            "state": self.state,
            "evidence_codes": list(self.evidence_codes),
            "source_periods": list(self.source_periods),
            "source_fiscal_years": list(self.source_fiscal_years),
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
    same_period_yoy_series: Mapping[str, SamePeriodYoYSeries] = field(default_factory=dict)
    direction_components: Mapping[str, tuple[DirectionComponent, ...]] = field(default_factory=dict)
    short_term_directions: Mapping[str, str] = field(default_factory=dict)
    multi_year_directions: Mapping[str, str] = field(default_factory=dict)
    multi_year_trends: Mapping[str, str] = field(default_factory=dict)
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
        object.__setattr__(self, "same_period_yoy_series", dict(self.same_period_yoy_series))
        object.__setattr__(self, "direction_components", {
            str(axis): tuple(items) for axis, items in self.direction_components.items()
        })
        object.__setattr__(self, "short_term_directions", dict(self.short_term_directions))
        object.__setattr__(self, "multi_year_directions", dict(self.multi_year_directions))
        object.__setattr__(self, "multi_year_trends", dict(self.multi_year_trends))
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
            "same_period_yoy_series": {
                metric: series.to_dict() if hasattr(series, "to_dict") else dict(series)
                for metric, series in self.same_period_yoy_series.items()
            },
            "direction_components": {
                axis: [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in items]
                for axis, items in self.direction_components.items()
            },
            "short_term_directions": dict(self.short_term_directions),
            "multi_year_directions": dict(self.multi_year_directions),
            "multi_year_trends": dict(self.multi_year_trends),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }
