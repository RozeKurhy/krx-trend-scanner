"""Deterministic Fundamentals Assessment over Derived Metrics only.

This layer is intentionally a consumer of :class:`DerivedMetricsResult` (or
``DerivedMetricsBuild``).  It does not import raw XBRL, Periodization facts,
market prices, Pattern A, RS, or any network client.  Every label is produced
from explicit explanation-code rules so a report layer can translate codes
without making natural language authoritative.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .assessment_models import (
    AssessmentEvidence,
    DirectionComponent,
    FundamentalsAssessmentResult,
    SamePeriodYoYPoint,
    SamePeriodYoYSeries,
)
from .derived_metrics import DerivedMetricObservation, DerivedMetricsResult
from .derived_metrics_provider import DerivedMetricsBuild


AXES = ("GROWTH", "PROFITABILITY", "CASH_FLOW", "MOMENTUM")
POSITIVE_DIRECTIONS = frozenset({"POSITIVE"})
NEGATIVE_DIRECTIONS = frozenset({"NEGATIVE", "RISK"})
MOMENTUM_STATES = frozenset({"ACCELERATING", "IMPROVING", "STABLE", "DECELERATING", "DETERIORATING", "UNAVAILABLE"})
OVERALL_STATES = frozenset({
    "STRONG", "IMPROVING", "TURNAROUND", "MIXED", "WEAKENING", "WEAK",
    "INSUFFICIENT_DATA", "NOT_APPLICABLE",
})
READY = "READY"
INPUT_NOT_READY = "INPUT_NOT_READY"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNAVAILABLE = "UNAVAILABLE"
ASSESSMENT_SCOPE_CURRENT = "CURRENT_AS_OF"
ASSESSMENT_SCOPE_RANGE = "EXPLICIT_RANGE"
CURRENTNESS_VERIFIED = "VERIFIED"
CURRENTNESS_RANGE_ONLY = "RANGE_ONLY"
CURRENTNESS_STALE = "STALE_INPUT_RANGE"
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
EARNINGS_METRICS = frozenset({"operating_income", "net_income"})
MARGIN_TYPES = frozenset({
    "OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
    "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN",
    "MARGIN_EXPANSION_TREND",
})
MULTI_YEAR_STABLE_TOLERANCE = 1e-9
MULTI_YEAR_TREND_STATES = frozenset({
    "ACCELERATING", "DECELERATING", "STABLE", "REVERSING_UP", "REVERSING_DOWN",
    "MIXED", "INSUFFICIENT_DATA",
})
DIRECTION_STATES = frozenset({"IMPROVING", "STABLE", "DETERIORATING", "MIXED", "UNAVAILABLE"})
GROWTH_TYPES = frozenset({
    "QUARTERLY_YOY", "ANNUAL_YOY", "REVENUE_GROWTH", "OPERATING_INCOME_GROWTH",
    "NET_INCOME_GROWTH", "OPERATING_CASH_FLOW_GROWTH", "TTM_YOY",
})


def _as_of(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10].replace("/", "-")).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _as_date(value: Any) -> date | None:
    text = _as_of(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value in (None, "", "-", "—", "–") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _year(value: Any) -> int:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return -1


def _period_key(item: Any) -> tuple[int, int]:
    return (_year(getattr(item, "fiscal_year", "")), PERIOD_ORDER.get(getattr(item, "fiscal_period", ""), 0))


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


class FundamentalsAssessmentEngine:
    """Pure/stateless rule engine over a canonical Derived Metrics result."""

    total_axis_count = len(AXES)

    def assess(
        self,
        source: DerivedMetricsResult | DerivedMetricsBuild,
        *,
        requested_as_of: Any = None,
        assessment_scope: str = ASSESSMENT_SCOPE_RANGE,
        expected_current_fiscal_year: str | None = None,
    ) -> FundamentalsAssessmentResult:
        result, build_cutoff = self._coerce_source(source)
        requested = _as_of(requested_as_of) or build_cutoff or self._result_cutoff(result)
        observations = tuple(result.observations)
        if any(not isinstance(item, DerivedMetricObservation) for item in observations):
            raise TypeError("FundamentalsAssessmentEngine requires DerivedMetricObservation inputs")

        source_ticker = source.ticker if isinstance(source, DerivedMetricsBuild) else ""
        source_family = ""
        if isinstance(source, DerivedMetricsBuild) and source.periodization_builds:
            source_family = str(source.periodization_builds[0].company_family or "")
        ticker = observations[0].ticker if observations else source_ticker
        family = self._family(observations) if observations else (source_family or "UNKNOWN")
        current = max(observations, key=_period_key) if observations else None
        current_year = str(current.fiscal_year) if current else None
        current_period = str(current.fiscal_period) if current else None
        input_years = tuple(str(year) for year in getattr(source, "fiscal_years", ()) if year is not None)
        if assessment_scope == ASSESSMENT_SCOPE_CURRENT:
            currentness_status = (
                CURRENTNESS_VERIFIED
                if expected_current_fiscal_year is None or str(expected_current_fiscal_year) in input_years
                else CURRENTNESS_STALE
            )
        else:
            currentness_status = CURRENTNESS_RANGE_ONLY

        if family == "FINANCIAL":
            return FundamentalsAssessmentResult(
                ticker=ticker, company_family=family, requested_as_of=requested,
                current_fiscal_year=current_year, current_fiscal_period=current_period,
                overall_state="NOT_APPLICABLE", growth_state="UNAVAILABLE",
                profitability_state="UNAVAILABLE", cash_flow_state="UNAVAILABLE",
                momentum_state="UNAVAILABLE", strengths=(), risks=(), evidence=(),
                available_axis_count=0, missing_axis_count=self.total_axis_count,
                pit_available_from=None, status=NOT_APPLICABLE,
                matched_rule_id="FINANCIAL_PROFILE_NOT_IMPLEMENTED",
                assessment_scope=assessment_scope, currentness_status=currentness_status,
                axis_directions={axis: UNAVAILABLE for axis in AXES},
                reason="FINANCIAL_PROFILE_NOT_IMPLEMENTED",
                diagnostics={"financial_revenue_margin_policy": "NOT_APPLICABLE"},
            )

        if not observations or current is None:
            return self._insufficient(
                ticker=ticker, family=family, requested=requested,
                reason="NO_DERIVED_METRICS",
                assessment_scope=assessment_scope, currentness_status=currentness_status,
            )

        cutoff_mismatch = bool(build_cutoff and requested and build_cutoff != requested)
        declared_cutoffs = {
            _as_of(item.requested_as_of) for item in observations if item.requested_as_of not in (None, "")
        }
        provider_cutoff_mismatch_count = sum(
            1 for cutoff in declared_cutoffs if requested and cutoff != requested
        )
        if provider_cutoff_mismatch_count:
            cutoff_mismatch = True

        expected_years = tuple(
            sorted({str(year) for year in getattr(source, "fiscal_years", ()) if year is not None}, key=_year)
        ) or tuple(sorted({_year(item.fiscal_year) for item in observations if _year(item.fiscal_year) >= 0}))
        same_period_yoy_series = self._same_period_yoy_series(
            observations, current, expected_years=expected_years,
        )
        selected_specs: dict[str, list[tuple[DerivedMetricObservation | None, str, str, str | None]]] = {
            axis: [] for axis in AXES
        }
        for item, code_hint in self._growth_level_inputs(observations, current):
            selected_specs["GROWTH"].append((item, code_hint, "LEVEL", None))
        for component_id, item, code_hint in self._growth_direction_inputs(observations, current, same_period_yoy_series):
            selected_specs["GROWTH"].append((item, code_hint, "DIRECTION", component_id))
        for item, code_hint in self._profitability_level_inputs(observations, current):
            selected_specs["PROFITABILITY"].append((item, code_hint, "LEVEL", None))
        for component_id, item, code_hint in self._profitability_direction_inputs(observations, current):
            selected_specs["PROFITABILITY"].append((item, code_hint, "DIRECTION", component_id))
        for item, code_hint in self._cash_flow_level_inputs(observations, current):
            selected_specs["CASH_FLOW"].append((item, code_hint, "LEVEL", None))
        for component_id, item, code_hint in self._cash_flow_direction_inputs(observations, current, same_period_yoy_series):
            selected_specs["CASH_FLOW"].append((item, code_hint, "DIRECTION", component_id))
        for item, code_hint in self._momentum_inputs(observations, current):
            selected_specs["MOMENTUM"].append((item, code_hint, "MOMENTUM", None))

        evidence: list[AssessmentEvidence] = []
        evidence_by_kind: dict[str, list[AssessmentEvidence]] = {"LEVEL": [], "DIRECTION": [], "MOMENTUM": []}
        component_evidence: dict[str, list[AssessmentEvidence]] = {}
        future_source_count = 0
        ready_missing_pit_count = 0
        for axis in AXES:
            for item, code_hint, kind, component_id in selected_specs[axis]:
                item_evidence, future, missing_pit = self._make_evidence(
                    axis, item, code_hint, current=current, requested_as_of=requested,
                )
                evidence.append(item_evidence)
                evidence_by_kind[kind].append(item_evidence)
                if component_id:
                    component_evidence.setdefault(component_id, []).append(item_evidence)
                future_source_count += future
                ready_missing_pit_count += missing_pit

        by_axis = {axis: [item for item in evidence if item.axis == axis] for axis in AXES}
        level_by_axis = {
            axis: [item for item in evidence_by_kind["LEVEL"] if item.axis == axis]
            for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        }
        axis_resolution = {
            "GROWTH": self._growth_state(level_by_axis["GROWTH"]),
            "PROFITABILITY": self._profitability_state(level_by_axis["PROFITABILITY"]),
            "CASH_FLOW": self._cash_flow_state(level_by_axis["CASH_FLOW"]),
            "MOMENTUM": self._momentum_state(evidence_by_kind["MOMENTUM"]),
        }
        available_axis_count = sum(
            state not in {UNAVAILABLE, "INSUFFICIENT_DATA"} for state in axis_resolution.values()
        )
        missing_axis_count = self.total_axis_count - available_axis_count
        available_evidence_count = sum(item.status == READY for item in evidence)
        missing_evidence_count = len(evidence) - available_evidence_count
        ready_evidence = tuple(item for item in evidence if item.status == READY)
        pit_dates = [_as_date(item.pit_available_from) for item in ready_evidence if item.pit_available_from]
        pit_available_from = max(pit_dates).isoformat() if pit_dates else None
        strengths = _dedupe(item.explanation_code for item in ready_evidence if item.direction == "POSITIVE")
        risks = _dedupe(item.explanation_code for item in ready_evidence if item.direction in NEGATIVE_DIRECTIONS)
        transition_codes = {
            item.classification for item in ready_evidence
            if item.metric_type == "EARNINGS_TRANSITION"
        }
        direction_components = self._direction_components(
            observations=observations,
            current=current,
            same_period_yoy_series=same_period_yoy_series,
            component_evidence=component_evidence,
        )
        direction_components_by_axis = {
            axis: tuple(item for item in direction_components if item.axis == axis)
            for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        }
        axis_directions = {
            axis: self._aggregate_direction_components(direction_components_by_axis[axis])
            for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        }
        axis_directions["MOMENTUM"] = self._momentum_direction(axis_resolution["MOMENTUM"])
        short_term_directions = self._metric_direction_summary(direction_components, suffix="short_term")
        multi_year_directions = {
            metric: self._trend_to_direction(series.trend_state)
            for metric, series in same_period_yoy_series.items()
        }
        multi_year_trends = {
            metric: series.trend_state for metric, series in same_period_yoy_series.items()
        }
        core_axes = ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        improving_axes = sum(axis_directions[axis] == "IMPROVING" for axis in core_axes)
        deteriorating_axes = sum(axis_directions[axis] == "DETERIORATING" for axis in core_axes)
        negative_level_axes = sum(axis_resolution[axis] in {"NEGATIVE", "WEAK"} for axis in core_axes)
        momentum_state = axis_resolution["MOMENTUM"]
        rule = self._rule_diagnostics(
            available_axis_count=available_axis_count,
            transition_codes=transition_codes,
            improving_axes=improving_axes,
            deteriorating_axes=deteriorating_axes,
            negative_level_axes=negative_level_axes,
            axis_resolution=axis_resolution,
            axis_directions=axis_directions,
            momentum_state=momentum_state,
            risks=risks,
        )
        overall_state, matched_rule_id = rule["overall_state"], rule["matched_rule_id"]
        direction_component_overwrite_count = len(direction_components) - len({item.component_id for item in direction_components})
        direction_codes = {
            code for item in evidence_by_kind["DIRECTION"] for code in (item.explanation_code,)
        }
        diagnostics = {
            "provider_cutoff_mismatch_count": provider_cutoff_mismatch_count,
            "future_assessment_source_count": future_source_count,
            "ready_missing_pit_available_count": ready_missing_pit_count,
            "ready_future_pit_available_count": sum(
                1 for item in ready_evidence
                if requested and _as_date(item.pit_available_from) and _as_date(item.pit_available_from) > _as_date(requested)
            ),
            "axis_resolution": dict(axis_resolution),
            "axis_directions": dict(axis_directions),
            # Compatibility aliases; FIX01 rule decisions use explicit
            # level/direction counters below.
            "deterioration_axis_count": deteriorating_axes,
            "improvement_axis_count": improving_axes,
            "deteriorating_direction_axis_count": deteriorating_axes,
            "improving_direction_axis_count": improving_axes,
            "negative_level_axis_count": negative_level_axes,
            "transition_codes": sorted(code for code in transition_codes if code),
            "matched_candidate_rules": list(rule["matched_candidate_rules"]),
            "expected_rule_overlaps": [list(item) for item in rule["expected_rule_overlaps"]],
            "same_period_yoy_series": {
                metric: series.to_dict() for metric, series in same_period_yoy_series.items()
            },
            "direction_components": {
                axis: [item.to_dict() for item in items]
                for axis, items in direction_components_by_axis.items()
            },
            "short_term_directions": dict(short_term_directions),
            "multi_year_directions": dict(multi_year_directions),
            "multi_year_trends": dict(multi_year_trends),
            "level_contaminated_by_direction_count": 0,
            "direction_contaminated_by_level_count": 0,
            "direction_component_overwrite_count": max(0, direction_component_overwrite_count),
            "direction_order_dependence_count": 0,
            "positive_streak_used_as_improvement_count": int("POSITIVE_GROWTH_STREAK" in direction_codes),
            "current_yoy_sign_used_as_direction_count": sum(
                code.endswith("_YOY_POSITIVE") or code.endswith("_YOY_NEGATIVE")
                for code in direction_codes
            ),
            "ttm_yoy_sign_used_as_direction_count": sum(
                code.startswith("TTM_") and (code.endswith("_POSITIVE") or code.endswith("_NEGATIVE"))
                for code in direction_codes
            ),
            "improving_without_directional_support_count": int(any(
                axis_directions[axis] == "IMPROVING" and not any(
                    item.state == "IMPROVING" for item in direction_components_by_axis[axis]
                ) for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
            )),
            "weakening_without_directional_support_count": int(any(
                axis_directions[axis] == "DETERIORATING" and not any(
                    item.state == "DETERIORATING" for item in direction_components_by_axis[axis]
                ) for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
            )),
        }
        invalid_pit = bool(future_source_count or ready_missing_pit_count or diagnostics["ready_future_pit_available_count"])
        status = READY
        reason = None
        if cutoff_mismatch:
            status, overall_state, matched_rule_id = INPUT_NOT_READY, "INSUFFICIENT_DATA", "INPUT_CUTOFF_MISMATCH"
            reason = "PROVIDER_CUTOFF_MISMATCH"
        elif invalid_pit:
            status, overall_state, matched_rule_id = INPUT_NOT_READY, "INSUFFICIENT_DATA", "PIT_PROVENANCE_INVALID"
            reason = "FUTURE_OR_MISSING_PIT_PROVENANCE"
        elif currentness_status == CURRENTNESS_STALE:
            status, overall_state, matched_rule_id = INPUT_NOT_READY, "INSUFFICIENT_DATA", "STALE_INPUT_RANGE"
            reason = "CURRENT_AS_OF_INPUT_RANGE_OMITS_REQUESTED_YEAR"
        elif available_axis_count < 2:
            status, overall_state, matched_rule_id = "INSUFFICIENT_DATA", "INSUFFICIENT_DATA", "OVERALL_INSUFFICIENT_DATA_V01"
            reason = "ASSESSMENT_AXIS_COVERAGE_BELOW_MINIMUM"
        return FundamentalsAssessmentResult(
            ticker=ticker, company_family=family, requested_as_of=requested,
            current_fiscal_year=current_year, current_fiscal_period=current_period,
            overall_state=overall_state,
            growth_state=axis_resolution["GROWTH"],
            profitability_state=axis_resolution["PROFITABILITY"],
            cash_flow_state=axis_resolution["CASH_FLOW"],
            momentum_state=momentum_state, strengths=strengths, risks=risks,
            evidence=tuple(evidence), available_axis_count=available_axis_count,
            missing_axis_count=missing_axis_count, pit_available_from=pit_available_from,
            status=status, matched_rule_id=matched_rule_id,
            available_evidence_count=available_evidence_count,
            missing_evidence_count=missing_evidence_count,
            axis_resolution=axis_resolution,
            assessment_rule_conflict_count=rule["assessment_rule_conflict_count"],
            assessment_rule_mismatch_count=rule["assessment_rule_mismatch_count"],
            assessment_scope=assessment_scope, currentness_status=currentness_status,
            growth_direction=axis_directions["GROWTH"],
            profitability_direction=axis_directions["PROFITABILITY"],
            cash_flow_direction=axis_directions["CASH_FLOW"], axis_directions=axis_directions,
            improving_direction_axis_count=improving_axes,
            deteriorating_direction_axis_count=deteriorating_axes,
            negative_level_axis_count=negative_level_axes,
            matched_candidate_rules=rule["matched_candidate_rules"],
            expected_rule_overlaps=rule["expected_rule_overlaps"],
            same_period_yoy_series=same_period_yoy_series,
            direction_components=direction_components_by_axis,
            short_term_directions=short_term_directions,
            multi_year_directions=multi_year_directions,
            multi_year_trends=multi_year_trends,
            reason=reason, diagnostics=diagnostics,
        )

    @staticmethod
    def _coerce_source(source: Any) -> tuple[DerivedMetricsResult, str | None]:
        if isinstance(source, DerivedMetricsBuild):
            return source.result, _as_of(source.requested_as_of)
        if isinstance(source, DerivedMetricsResult):
            return source, None
        raise TypeError("Assessment input must be DerivedMetricsResult or DerivedMetricsBuild")

    @staticmethod
    def _result_cutoff(result: DerivedMetricsResult) -> str | None:
        values = {_as_of(item.requested_as_of) for item in result if item.requested_as_of not in (None, "")}
        return next(iter(values)) if len(values) == 1 else None

    @staticmethod
    def _family(observations: Iterable[DerivedMetricObservation]) -> str:
        families = {str(item.company_family or "UNKNOWN") for item in observations}
        if "FINANCIAL" in families and families <= {"FINANCIAL"}:
            return "FINANCIAL"
        return next(iter(families), "UNKNOWN") if len(families) == 1 else "UNKNOWN"

    @staticmethod
    def _at_current(observations: Iterable[DerivedMetricObservation], current: Any, metric: str, metric_types: Iterable[str]) -> DerivedMetricObservation | None:
        types = tuple(metric_types)
        candidates = [item for item in observations if item.metric == metric and item.metric_type in types
                      and item.fiscal_year == current.fiscal_year and item.fiscal_period == current.fiscal_period]
        for metric_type in types:
            same = [item for item in candidates if item.metric_type == metric_type]
            if same:
                return sorted(same, key=lambda item: (
                    tuple(str(value) for value in item.source_rcept_nos),
                    tuple(str(value) for value in item.source_sha256s),
                    str(item.value),
                ))[0]
        return None

    @staticmethod
    def _latest_at_or_before(observations: Iterable[DerivedMetricObservation], current: Any, metric: str, metric_types: Iterable[str]) -> DerivedMetricObservation | None:
        types = tuple(metric_types)
        candidates = [item for item in observations if item.metric == metric and item.metric_type in types
                      and _period_key(item) <= _period_key(current)]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (
            _period_key(item), tuple(str(value) for value in item.source_rcept_nos),
            tuple(str(value) for value in item.source_sha256s), str(item.value),
        ))

    @staticmethod
    def _yoy_metric_type(fiscal_period: str) -> str:
        return "ANNUAL_YOY" if fiscal_period == "FY" else "QUARTERLY_YOY"

    @classmethod
    def _same_period_yoy_series(
        cls,
        observations: tuple[DerivedMetricObservation, ...],
        current: Any,
        *,
        expected_years: tuple[str, ...],
    ) -> dict[str, SamePeriodYoYSeries]:
        period = str(current.fiscal_period)
        metric_type = cls._yoy_metric_type(period)
        years = tuple(sorted({str(year) for year in expected_years}, key=_year))
        output: dict[str, SamePeriodYoYSeries] = {}
        for metric in FLOW_METRICS:
            points: list[SamePeriodYoYPoint] = []
            for year in years:
                candidates = [item for item in observations
                              if item.metric == metric and item.fiscal_year == year
                              and item.fiscal_period == period and item.metric_type == metric_type]
                candidate = sorted(candidates, key=lambda item: (
                    tuple(str(value) for value in item.source_rcept_nos),
                    tuple(str(value) for value in item.source_sha256s), str(item.value),
                ))[0] if candidates else None
                if candidate is None:
                    points.append(SamePeriodYoYPoint(
                        fiscal_year=year, fiscal_period=period, metric=metric,
                        metric_type=metric_type, yoy_value=None, resolution_status=UNAVAILABLE,
                        pit_available_from=None,
                    ))
                else:
                    value = _number(candidate.value) if candidate.resolution_status == READY else None
                    points.append(SamePeriodYoYPoint(
                        fiscal_year=year, fiscal_period=period, metric=metric,
                        metric_type=metric_type, yoy_value=value,
                        resolution_status=candidate.resolution_status,
                        pit_available_from=candidate.pit_available_from,
                        source_rcept_nos=tuple(candidate.source_rcept_nos),
                        source_rcept_dts=tuple(candidate.source_rcept_dts),
                        source_sha256s=tuple(candidate.source_sha256s),
                    ))
            usable, contiguous_years = cls._contiguous_ready_suffix(points)
            trend = cls._multi_year_trend(usable)
            output[metric] = SamePeriodYoYSeries(
                metric=metric, fiscal_period=period, points=tuple(points),
                usable_yoy_point_count=len(usable), trend_state=trend,
                contiguous_fiscal_years=tuple(contiguous_years),
            )
        return output

    @staticmethod
    def _contiguous_ready_suffix(points: Iterable[SamePeriodYoYPoint]) -> tuple[tuple[SamePeriodYoYPoint, ...], tuple[str, ...]]:
        ordered = tuple(sorted(points, key=lambda item: _year(item.fiscal_year)))
        if not ordered:
            return (), ()
        suffix: list[SamePeriodYoYPoint] = []
        expected_year: int | None = None
        for point in reversed(ordered):
            value = _number(point.yoy_value)
            if point.resolution_status != READY or value is None:
                break
            year = _year(point.fiscal_year)
            if expected_year is not None and year != expected_year - 1:
                break
            suffix.append(point)
            expected_year = year
        suffix.reverse()
        return tuple(suffix), tuple(item.fiscal_year for item in suffix)

    @staticmethod
    def _multi_year_trend(points: tuple[SamePeriodYoYPoint, ...]) -> str:
        if len(points) < 3:
            return "INSUFFICIENT_DATA"
        values = tuple(float(_number(item.yoy_value)) for item in points)
        deltas = tuple(right - left for left, right in zip(values, values[1:]))
        tolerance = MULTI_YEAR_STABLE_TOLERANCE
        if all(abs(delta) <= tolerance for delta in deltas):
            return "STABLE"
        if all(delta > tolerance for delta in deltas):
            return "ACCELERATING"
        if all(delta < -tolerance for delta in deltas):
            return "DECELERATING"
        if len(deltas) >= 3:
            # A reversal is a two-delta prior run followed by an opposite
            # delta.  Later deltas in the same new direction do not erase the
            # detected turn; they confirm the new regime.
            for index in range(2, len(deltas)):
                prior = deltas[index - 2:index]
                latest = deltas[index]
                if all(delta > tolerance for delta in prior) and latest < -tolerance:
                    return "REVERSING_DOWN"
                if all(delta < -tolerance for delta in prior) and latest > tolerance:
                    return "REVERSING_UP"
        return "MIXED"

    @staticmethod
    def _trend_to_direction(trend: str) -> str:
        if trend in {"ACCELERATING", "REVERSING_UP"}:
            return "IMPROVING"
        if trend in {"DECELERATING", "REVERSING_DOWN"}:
            return "DETERIORATING"
        if trend in {"STABLE"}:
            return "STABLE"
        if trend == "MIXED":
            return "MIXED"
        return "UNAVAILABLE"

    def _growth_level_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any):
        growth_type = self._yoy_metric_type(str(current.fiscal_period))
        return [
            (self._at_current(observations, current, metric, (growth_type, f"{metric.upper()}_GROWTH")),
             f"{metric.upper()}_GROWTH")
            for metric in ("revenue", "operating_income", "net_income")
        ]

    def _growth_direction_inputs(self, observations, current, series):
        output = []
        for metric in FLOW_METRICS:
            output.append((f"{metric}_short_term_acceleration",
                           self._at_current(observations, current, metric, ("YOY_GROWTH_ACCELERATION",)),
                           "YOY_GROWTH_ACCELERATION"))
        for metric in EARNINGS_METRICS:
            output.append((f"{metric}_transition",
                           self._at_current(observations, current, metric, ("EARNINGS_TRANSITION",)),
                           "EARNINGS_TRANSITION"))
        return output

    def _profitability_level_inputs(self, observations, current):
        output = []
        for metric, metric_type, code in (
            ("operating_income", "OPERATING_MARGIN", "OPERATING_MARGIN"),
            ("net_income", "NET_MARGIN", "NET_MARGIN"),
            ("operating_income", "TTM_OPERATING_MARGIN", "TTM_OPERATING_MARGIN"),
            ("net_income", "TTM_NET_MARGIN", "TTM_NET_MARGIN"),
        ):
            getter = self._at_current if metric_type in {"OPERATING_MARGIN", "NET_MARGIN"} else self._latest_at_or_before
            output.append((getter(observations, current, metric, (metric_type,)), code))
        return output

    def _profitability_direction_inputs(self, observations, current):
        return [
            (f"{metric}_margin_direction",
             self._at_current(observations, current, metric, ("MARGIN_EXPANSION_TREND",)),
             "MARGIN_EXPANSION_TREND")
            for metric in ("operating_income", "net_income")
        ]

    def _cash_flow_level_inputs(self, observations, current):
        growth_type = self._yoy_metric_type(str(current.fiscal_period))
        return [
            (self._at_current(observations, current, "operating_cash_flow", (growth_type, "OPERATING_CASH_FLOW_GROWTH")), "OPERATING_CASH_FLOW_GROWTH"),
            (self._at_current(observations, current, "operating_cash_flow", ("OPERATING_CASH_FLOW_MARGIN",)), "OPERATING_CASH_FLOW_MARGIN"),
            (self._latest_at_or_before(observations, current, "operating_cash_flow", ("TTM_YOY",)), "TTM_OPERATING_CASH_FLOW_YOY"),
            (self._latest_at_or_before(observations, current, "operating_cash_flow", ("TTM_OPERATING_CASH_FLOW_MARGIN",)), "TTM_OPERATING_CASH_FLOW_MARGIN"),
        ]

    def _cash_flow_direction_inputs(self, observations, current, series):
        return [
            ("operating_cash_flow_short_term_trend",
             self._at_current(observations, current, "operating_cash_flow", ("OPERATING_CASH_FLOW_TREND",)),
             "OPERATING_CASH_FLOW_TREND"),
            ("operating_cash_flow_margin_direction",
             self._at_current(observations, current, "operating_cash_flow", ("MARGIN_EXPANSION_TREND",)),
             "MARGIN_EXPANSION_TREND"),
        ]

    @staticmethod
    def _direction_state_from_evidence(evidence: Iterable[AssessmentEvidence]) -> str:
        codes = {item.explanation_code for item in evidence if item.status == READY}
        if codes.intersection({"YOY_ACCELERATING", "MARGIN_EXPANDING", "OCF_TREND_IMPROVING", "LOSS_TO_PROFIT", "LOSS_NARROWING", "PROFIT_GROWTH"}):
            positive = True
        else:
            positive = False
        negative = bool(codes.intersection({"YOY_DECELERATING", "MARGIN_CONTRACTING", "OCF_TREND_DETERIORATING", "PROFIT_TO_LOSS", "LOSS_WIDENING", "PROFIT_DECLINE"}))
        if positive and negative:
            return "MIXED"
        if positive:
            return "IMPROVING"
        if negative:
            return "DETERIORATING"
        if evidence and any(item.status == READY for item in evidence):
            return "STABLE"
        return "UNAVAILABLE"

    def _direction_components(self, *, observations, current, same_period_yoy_series, component_evidence):
        components: list[DirectionComponent] = []
        for component_id, items in sorted(component_evidence.items()):
            if not items:
                continue
            axis = "GROWTH" if component_id.startswith(("revenue_", "operating_income_", "net_income_")) else "CASH_FLOW"
            if component_id.endswith("_margin_direction") and not component_id.startswith("operating_cash_flow_"):
                axis = "PROFITABILITY"
            logical_metric = items[0].metric
            for suffix in ("_short_term_acceleration", "_short_term_trend", "_transition", "_margin_direction", "_multi_year_trend"):
                if component_id.endswith(suffix):
                    logical_metric = component_id[:-len(suffix)]
                    break
            components.append(DirectionComponent(
                axis=axis, component_id=component_id,
                metric=logical_metric,
                state=self._direction_state_from_evidence(items),
                evidence_codes=tuple(sorted({item.explanation_code for item in items})),
                source_periods=tuple(sorted({item.fiscal_period for item in items}, key=lambda value: PERIOD_ORDER.get(value, 0))),
                source_fiscal_years=tuple(sorted({item.fiscal_year for item in items}, key=_year)),
            ))
        for metric, series in sorted(same_period_yoy_series.items()):
            axis = "CASH_FLOW" if metric == "operating_cash_flow" else "GROWTH"
            components.append(DirectionComponent(
                axis=axis, component_id=f"{metric}_multi_year_trend", metric=metric,
                state=self._trend_to_direction(series.trend_state),
                evidence_codes=(f"MULTI_YEAR_{series.trend_state}",),
                source_periods=(series.fiscal_period,),
                source_fiscal_years=series.contiguous_fiscal_years,
            ))
        return tuple(sorted(components, key=lambda item: (item.axis, item.component_id)))

    @staticmethod
    def _aggregate_direction_components(components: Iterable[DirectionComponent]) -> str:
        values = tuple(item.state for item in components if item.state != "UNAVAILABLE")
        if not values:
            return "UNAVAILABLE"
        improving = values.count("IMPROVING")
        deteriorating = values.count("DETERIORATING")
        mixed = values.count("MIXED")
        if mixed or (improving and deteriorating):
            return "MIXED"
        if improving > deteriorating:
            return "IMPROVING"
        if deteriorating > improving:
            return "DETERIORATING"
        return "STABLE"

    @staticmethod
    def _metric_direction_summary(components: Iterable[DirectionComponent], *, suffix: str) -> dict[str, str]:
        grouped: dict[str, list[DirectionComponent]] = {}
        for item in components:
            if f"_{suffix}_" in item.component_id or item.component_id.endswith(f"_{suffix}"):
                grouped.setdefault(item.metric, []).append(item)
        return {metric: FundamentalsAssessmentEngine._aggregate_direction_components(items)
                for metric, items in sorted(grouped.items())}

    def _growth_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        return self._growth_level_inputs(observations, current)

    def _profitability_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        return self._profitability_level_inputs(observations, current)

    def _cash_flow_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        return self._cash_flow_level_inputs(observations, current)

    def _momentum_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        output: list[tuple[DerivedMetricObservation | None, str]] = []
        for metric in FLOW_METRICS:
            output.append((self._at_current(observations, current, metric, ("YOY_GROWTH_ACCELERATION",)), "YOY_GROWTH_ACCELERATION"))
            output.append((self._at_current(observations, current, metric, ("CONSECUTIVE_YOY_GROWTH",)), "CONSECUTIVE_YOY_GROWTH"))
        output.extend([
            (self._at_current(observations, current, metric, ("MARGIN_EXPANSION_TREND",)), "MARGIN_EXPANSION_TREND")
            for metric in ("operating_income", "net_income")
        ])
        output.append((self._at_current(observations, current, "operating_cash_flow", ("OPERATING_CASH_FLOW_TREND",)), "OPERATING_CASH_FLOW_TREND"))
        for metric in EARNINGS_METRICS:
            output.append((self._at_current(observations, current, metric, ("EARNINGS_TRANSITION",)), "EARNINGS_TRANSITION"))
        return output

    def _make_evidence(
        self, axis: str, item: DerivedMetricObservation | None, code_hint: str,
        *, current: Any, requested_as_of: str | None,
    ) -> tuple[AssessmentEvidence, int, int]:
        if item is None:
            return AssessmentEvidence(
                axis=axis, metric=code_hint.lower(), metric_type=code_hint,
                fiscal_year=str(current.fiscal_year), fiscal_period=str(current.fiscal_period),
                value=None, classification=None, direction="NEUTRAL",
                explanation_code=f"{code_hint}_UNAVAILABLE", requested_as_of=requested_as_of,
                pit_available_from=None, status=UNAVAILABLE, reason="MISSING_CURRENT_DERIVED_METRIC",
            ), 0, 0
        status = item.resolution_status
        reason = item.reason
        future_count = 0
        missing_pit = 0
        cutoff = _as_date(requested_as_of)
        if status == READY and requested_as_of:
            item_cutoff = _as_of(item.requested_as_of)
            if item_cutoff and item_cutoff != requested_as_of:
                status, reason = INPUT_NOT_READY, "PROVIDER_CUTOFF_MISMATCH"
            pit = _as_date(item.pit_available_from)
            if pit is None:
                missing_pit = 1
                status, reason = INPUT_NOT_READY, "PIT_AVAILABILITY_UNKNOWN"
            elif cutoff and pit > cutoff:
                future_count += 1
                status, reason = INPUT_NOT_READY, "FUTURE_DATA_AFTER_REQUESTED_AS_OF"
            source_dates = [_as_date(value) for value in item.source_rcept_dts]
            if cutoff and any(value is not None and value > cutoff for value in source_dates):
                future_count += 1
                status, reason = INPUT_NOT_READY, "FUTURE_SOURCE_AFTER_REQUESTED_AS_OF"
        classification, direction, code = self._classify(item, code_hint, status)
        return AssessmentEvidence(
            axis=axis, metric=item.metric, metric_type=item.metric_type,
            fiscal_year=str(item.fiscal_year), fiscal_period=str(item.fiscal_period),
            value=item.value if status == READY else None, classification=classification,
            direction=direction, explanation_code=code,
            requested_as_of=requested_as_of, pit_available_from=item.pit_available_from,
            source_rcept_nos=tuple(item.source_rcept_nos), source_rcept_dts=tuple(item.source_rcept_dts),
            source_sha256s=tuple(item.source_sha256s), status=status, reason=reason,
            metadata=dict(item.metadata),
        ), future_count, missing_pit

    @staticmethod
    def _classify(item: DerivedMetricObservation, code_hint: str, status: str) -> tuple[str | None, str, str]:
        if status != READY:
            return None, "NEUTRAL", f"{code_hint}_UNAVAILABLE"
        value = item.value
        text = str(value).upper() if value is not None else ""
        if item.metric_type == "EARNINGS_TRANSITION":
            direction = "POSITIVE" if text in {"LOSS_TO_PROFIT", "LOSS_NARROWING", "PROFIT_GROWTH"} else "RISK" if text in {"PROFIT_TO_LOSS", "LOSS_WIDENING", "PROFIT_DECLINE"} else "NEUTRAL"
            return text or None, direction, text or "EARNINGS_TRANSITION_NEUTRAL"
        if item.metric_type == "MARGIN_EXPANSION_TREND":
            classification = str(item.metadata.get("classification") or text or "UNAVAILABLE").upper()
            direction = "POSITIVE" if classification == "EXPANDING" else "RISK" if classification == "CONTRACTING" else "NEUTRAL"
            return classification, direction, "MARGIN_EXPANDING" if direction == "POSITIVE" else "MARGIN_CONTRACTING" if direction == "RISK" else "MARGIN_FLAT"
        if item.metric_type in {"OPERATING_CASH_FLOW_TREND"}:
            direction = "POSITIVE" if text == "IMPROVING" else "RISK" if text == "DETERIORATING" else "NEUTRAL"
            return text or None, direction, "OCF_TREND_IMPROVING" if direction == "POSITIVE" else "OCF_TREND_DETERIORATING" if direction == "RISK" else "OCF_TREND_FLAT"
        if item.metric_type == "YOY_GROWTH_ACCELERATION":
            number = _number(value)
            direction = "POSITIVE" if number is not None and number > 0 else "RISK" if number is not None and number < 0 else "NEUTRAL"
            return "ACCELERATING" if direction == "POSITIVE" else "DECELERATING" if direction == "RISK" else "STABLE", direction, "YOY_ACCELERATING" if direction == "POSITIVE" else "YOY_DECELERATING" if direction == "RISK" else "YOY_ACCELERATION_FLAT"
        if item.metric_type == "CONSECUTIVE_YOY_GROWTH":
            number = _number(value)
            direction = "POSITIVE" if number is not None and number >= 2 else "NEUTRAL"
            return "POSITIVE_STREAK" if direction == "POSITIVE" else "NO_STREAK", direction, "POSITIVE_GROWTH_STREAK" if direction == "POSITIVE" else "NO_POSITIVE_GROWTH_STREAK"
        number = _number(value)
        if number is None:
            return None, "NEUTRAL", f"{code_hint}_UNAVAILABLE"
        direction = "POSITIVE" if number > 0 else "RISK" if number < 0 else "NEUTRAL"
        prefix = "TTM_" if item.metric_type == "TTM_YOY" else ""
        metric_name = item.metric.upper()
        if item.metric_type in GROWTH_TYPES:
            code = f"{prefix}{metric_name}_YOY_" + ("POSITIVE" if direction == "POSITIVE" else "NEGATIVE" if direction == "RISK" else "FLAT")
        elif item.metric_type in MARGIN_TYPES:
            code = f"{metric_name}_MARGIN_" + ("POSITIVE" if direction == "POSITIVE" else "NEGATIVE" if direction == "RISK" else "FLAT")
        else:
            code = f"{metric_name}_{item.metric_type}_" + direction
        return "POSITIVE" if direction == "POSITIVE" else "NEGATIVE" if direction == "RISK" else "FLAT", direction, code

    @staticmethod
    def _growth_state(evidence: list[AssessmentEvidence]) -> str:
        ready = [item for item in evidence if item.status == READY]
        if not ready:
            return UNAVAILABLE
        positive = sum(item.direction == "POSITIVE" for item in ready)
        negative = sum(item.direction in NEGATIVE_DIRECTIONS for item in ready)
        critical = any(item.classification == "PROFIT_TO_LOSS" for item in ready)
        if critical and negative >= 1:
            return "WEAK"
        if positive >= 2 and negative == 0:
            return "STRONG"
        if positive > negative and positive:
            return "POSITIVE"
        if negative >= 2 and positive == 0:
            return "WEAK"
        if negative > positive:
            return "NEGATIVE"
        return "MIXED"

    @staticmethod
    def _profitability_state(evidence: list[AssessmentEvidence]) -> str:
        ready = [item for item in evidence if item.status == READY]
        if not ready:
            return UNAVAILABLE
        positive = sum(item.direction == "POSITIVE" for item in ready)
        negative = sum(item.direction in NEGATIVE_DIRECTIONS for item in ready)
        if positive >= 3 and negative == 0:
            return "STRONG"
        if positive > negative:
            return "POSITIVE"
        if negative >= 3 and positive == 0:
            return "WEAK"
        if negative > positive:
            return "NEGATIVE"
        return "MIXED"

    @staticmethod
    def _cash_flow_state(evidence: list[AssessmentEvidence]) -> str:
        ready = [item for item in evidence if item.status == READY]
        if not ready:
            return UNAVAILABLE
        positive = sum(item.direction == "POSITIVE" for item in ready)
        negative = sum(item.direction in NEGATIVE_DIRECTIONS for item in ready)
        if positive >= 3 and negative == 0:
            return "STRONG"
        if positive > negative:
            return "POSITIVE"
        if negative >= 3 and positive == 0:
            return "WEAK"
        if negative > positive:
            return "NEGATIVE"
        return "MIXED"

    @staticmethod
    def _momentum_state(evidence: list[AssessmentEvidence]) -> str:
        ready = [item for item in evidence if item.status == READY]
        if not ready:
            return UNAVAILABLE
        positive = sum(item.direction == "POSITIVE" for item in ready)
        negative = sum(item.direction in NEGATIVE_DIRECTIONS for item in ready)
        accelerating = sum(item.classification == "ACCELERATING" for item in ready)
        decelerating = sum(item.classification == "DECELERATING" for item in ready)
        deteriorating = sum(item.classification == "DETERIORATING" for item in ready)
        if deteriorating or decelerating >= 2:
            return "DETERIORATING" if deteriorating else "DECELERATING"
        if accelerating >= 2:
            return "ACCELERATING"
        if positive > negative:
            return "IMPROVING"
        if negative > positive:
            return "DECELERATING"
        return "STABLE"

    @staticmethod
    def _momentum_direction(state: str) -> str:
        if state in {"ACCELERATING", "IMPROVING"}:
            return "IMPROVING"
        if state in {"DECELERATING", "DETERIORATING"}:
            return "DETERIORATING"
        if state == "STABLE":
            return "STABLE"
        return UNAVAILABLE

    @staticmethod
    def _rule_diagnostics(*, available_axis_count: int, transition_codes: set[str | None], improving_axes: int,
                          deteriorating_axes: int, negative_level_axes: int, axis_resolution: Mapping[str, str],
                          axis_directions: Mapping[str, str], momentum_state: str,
                          risks: tuple[str, ...]) -> dict[str, Any]:
        severe_cash = axis_resolution["CASH_FLOW"] == "WEAK" and "OCF_TREND_DETERIORATING" in risks
        strong_candidate = (
            all(axis_resolution[axis] in {"STRONG", "POSITIVE"} for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW"))
            and not {"PROFIT_TO_LOSS", "LOSS_TO_PROFIT"}.intersection(transition_codes)
            and deteriorating_axes == 0
            and momentum_state not in {"DECELERATING", "DETERIORATING"}
        )
        candidates: dict[str, bool] = {
            "OVERALL_INSUFFICIENT_DATA_V01": available_axis_count < 2,
            "OVERALL_TURNAROUND_V01": "LOSS_TO_PROFIT" in transition_codes and improving_axes >= 1 and not severe_cash,
            "OVERALL_WEAK_V01": negative_level_axes >= 3 or ("PROFIT_TO_LOSS" in transition_codes and negative_level_axes >= 2),
            "OVERALL_WEAKENING_V01": deteriorating_axes >= 2 and not (negative_level_axes >= 3 or ("PROFIT_TO_LOSS" in transition_codes and negative_level_axes >= 2)),
            "OVERALL_STRONG_V01": strong_candidate,
            "OVERALL_IMPROVING_V01": (
                improving_axes >= 2 and deteriorating_axes < 2 and negative_level_axes < 2
                and axis_resolution["CASH_FLOW"] not in {"NEGATIVE", "WEAK"}
                and not strong_candidate
            ),
        }
        matched = [name for name, value in candidates.items() if value]
        expected_pairs = {
            tuple(sorted(("OVERALL_TURNAROUND_V01", "OVERALL_IMPROVING_V01"))),
        }
        unexpected = [tuple(sorted((left, right))) for index, left in enumerate(matched) for right in matched[index + 1:]
                      if tuple(sorted((left, right))) not in expected_pairs]
        if not matched:
            matched.append("OVERALL_MIXED_V01")
        chosen = next((name for name in (
            "OVERALL_INSUFFICIENT_DATA_V01", "OVERALL_TURNAROUND_V01", "OVERALL_WEAK_V01",
            "OVERALL_WEAKENING_V01", "OVERALL_STRONG_V01", "OVERALL_IMPROVING_V01",
            "OVERALL_MIXED_V01",
        ) if name in matched), "OVERALL_MIXED_V01")
        return {
            "overall_state": chosen.removeprefix("OVERALL_").removesuffix("_V01"),
            "matched_rule_id": chosen,
            "matched_candidate_rules": tuple(matched),
            "expected_rule_overlaps": tuple(sorted(pair) for pair in expected_pairs if all(item in matched for item in pair)),
            "assessment_rule_conflict_count": len(unexpected),
            "assessment_rule_mismatch_count": int(chosen not in matched),
        }

    def _insufficient(self, *, ticker: str, family: str, requested: str | None, reason: str,
                      assessment_scope: str = ASSESSMENT_SCOPE_RANGE,
                      currentness_status: str = CURRENTNESS_RANGE_ONLY) -> FundamentalsAssessmentResult:
        return FundamentalsAssessmentResult(
            ticker=ticker, company_family=family, requested_as_of=requested,
            current_fiscal_year=None, current_fiscal_period=None,
            overall_state="INSUFFICIENT_DATA", growth_state=UNAVAILABLE,
            profitability_state=UNAVAILABLE, cash_flow_state=UNAVAILABLE,
            momentum_state=UNAVAILABLE, strengths=(), risks=(), evidence=(),
            available_axis_count=0, missing_axis_count=self.total_axis_count,
            pit_available_from=None, status="INSUFFICIENT_DATA",
            matched_rule_id="OVERALL_INSUFFICIENT_DATA_V01",
            assessment_scope=assessment_scope, currentness_status=currentness_status,
            axis_directions={axis: UNAVAILABLE for axis in AXES},
            matched_candidate_rules=("OVERALL_INSUFFICIENT_DATA_V01",),
            reason=reason,
        )

    # Consistent convenience aliases for consumers that use calculate/evaluate
    # terminology for deterministic engines.
    evaluate = assess
    calculate = assess


def assess_fundamentals(
    source: DerivedMetricsResult | DerivedMetricsBuild,
    *,
    requested_as_of: Any = None,
    assessment_scope: str = ASSESSMENT_SCOPE_RANGE,
    expected_current_fiscal_year: str | None = None,
) -> FundamentalsAssessmentResult:
    """Convenience function for the pure assessment engine."""

    return FundamentalsAssessmentEngine().assess(
        source, requested_as_of=requested_as_of,
        assessment_scope=assessment_scope,
        expected_current_fiscal_year=expected_current_fiscal_year,
    )


FundamentalsAssessment = FundamentalsAssessmentEngine
