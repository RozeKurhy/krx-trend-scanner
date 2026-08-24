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

from .assessment_models import AssessmentEvidence, FundamentalsAssessmentResult
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
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4}
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
EARNINGS_METRICS = frozenset({"operating_income", "net_income"})
MARGIN_TYPES = frozenset({
    "OPERATING_MARGIN", "NET_MARGIN", "OPERATING_CASH_FLOW_MARGIN",
    "TTM_OPERATING_MARGIN", "TTM_NET_MARGIN", "TTM_OPERATING_CASH_FLOW_MARGIN",
    "MARGIN_EXPANSION_TREND",
})
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
                reason="FINANCIAL_PROFILE_NOT_IMPLEMENTED",
                diagnostics={"financial_revenue_margin_policy": "NOT_APPLICABLE"},
            )

        if not observations or current is None:
            return self._insufficient(
                ticker=ticker, family=family, requested=requested,
                reason="NO_DERIVED_METRICS",
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

        selected: dict[str, list[tuple[DerivedMetricObservation | None, str]]] = {
            axis: [] for axis in AXES
        }
        selected["GROWTH"] = self._growth_inputs(observations, current)
        selected["PROFITABILITY"] = self._profitability_inputs(observations, current)
        selected["CASH_FLOW"] = self._cash_flow_inputs(observations, current)
        selected["MOMENTUM"] = self._momentum_inputs(observations, current)

        evidence: list[AssessmentEvidence] = []
        future_source_count = 0
        ready_missing_pit_count = 0
        for axis in AXES:
            for item, code_hint in selected[axis]:
                item_evidence, future, missing_pit = self._make_evidence(
                    axis, item, code_hint, current=current, requested_as_of=requested,
                )
                evidence.append(item_evidence)
                future_source_count += future
                ready_missing_pit_count += missing_pit

        by_axis = {axis: [item for item in evidence if item.axis == axis] for axis in AXES}
        axis_resolution = {
            "GROWTH": self._growth_state(by_axis["GROWTH"]),
            "PROFITABILITY": self._profitability_state(by_axis["PROFITABILITY"]),
            "CASH_FLOW": self._cash_flow_state(by_axis["CASH_FLOW"]),
            "MOMENTUM": self._momentum_state(by_axis["MOMENTUM"]),
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
        deterioration_axes = sum(
            axis_resolution[axis] in {"NEGATIVE", "WEAK"}
            for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        )
        improvement_axes = sum(
            axis_resolution[axis] in {"POSITIVE", "STRONG"}
            for axis in ("GROWTH", "PROFITABILITY", "CASH_FLOW")
        )
        momentum_state = axis_resolution["MOMENTUM"]
        overall_state, matched_rule_id = self._overall_state(
            available_axis_count=available_axis_count,
            transition_codes=transition_codes,
            deterioration_axes=deterioration_axes,
            improvement_axes=improvement_axes,
            axis_resolution=axis_resolution,
            momentum_state=momentum_state,
            risks=risks,
        )
        diagnostics = {
            "provider_cutoff_mismatch_count": provider_cutoff_mismatch_count,
            "future_assessment_source_count": future_source_count,
            "ready_missing_pit_available_count": ready_missing_pit_count,
            "ready_future_pit_available_count": sum(
                1 for item in ready_evidence
                if requested and _as_date(item.pit_available_from) and _as_date(item.pit_available_from) > _as_date(requested)
            ),
            "axis_resolution": dict(axis_resolution),
            "deterioration_axis_count": deterioration_axes,
            "improvement_axis_count": improvement_axes,
            "transition_codes": sorted(code for code in transition_codes if code),
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
            axis_resolution=axis_resolution, assessment_rule_conflict_count=0,
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
                return sorted(same, key=lambda item: (str(item.anchor_rcept_no) if hasattr(item, "anchor_rcept_no") else ""))[0]
        return None

    @staticmethod
    def _latest_at_or_before(observations: Iterable[DerivedMetricObservation], current: Any, metric: str, metric_types: Iterable[str]) -> DerivedMetricObservation | None:
        types = tuple(metric_types)
        candidates = [item for item in observations if item.metric == metric and item.metric_type in types
                      and _period_key(item) <= _period_key(current)]
        if not candidates:
            return None
        return max(candidates, key=_period_key)

    def _growth_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        growth_type = "ANNUAL_YOY" if current.fiscal_period == "FY" else "QUARTERLY_YOY"
        output: list[tuple[DerivedMetricObservation | None, str]] = []
        for metric in FLOW_METRICS:
            item = self._at_current(observations, current, metric, (growth_type, f"{metric.upper()}_GROWTH"))
            output.append((item, f"{metric.upper()}_GROWTH"))
        for metric in EARNINGS_METRICS:
            output.append((self._at_current(observations, current, metric, ("EARNINGS_TRANSITION",)), "EARNINGS_TRANSITION"))
        return output

    def _profitability_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        output: list[tuple[DerivedMetricObservation | None, str]] = []
        for metric, metric_type, code in (
            ("operating_income", "OPERATING_MARGIN", "OPERATING_MARGIN"),
            ("net_income", "NET_MARGIN", "NET_MARGIN"),
        ):
            output.append((self._at_current(observations, current, metric, (metric_type,)), code))
            output.append((self._at_current(observations, current, metric, ("MARGIN_EXPANSION_TREND",)), "MARGIN_EXPANSION_TREND"))
        for metric, metric_type, code in (
            ("operating_income", "TTM_OPERATING_MARGIN", "TTM_OPERATING_MARGIN"),
            ("net_income", "TTM_NET_MARGIN", "TTM_NET_MARGIN"),
        ):
            output.append((self._latest_at_or_before(observations, current, metric, (metric_type,)), code))
        return output

    def _cash_flow_inputs(self, observations: tuple[DerivedMetricObservation, ...], current: Any) -> list[tuple[DerivedMetricObservation | None, str]]:
        growth_type = "ANNUAL_YOY" if current.fiscal_period == "FY" else "QUARTERLY_YOY"
        output = [
            (self._at_current(observations, current, "operating_cash_flow", (growth_type, "OPERATING_CASH_FLOW_GROWTH")), "OPERATING_CASH_FLOW_GROWTH"),
            (self._at_current(observations, current, "operating_cash_flow", ("OPERATING_CASH_FLOW_MARGIN",)), "OPERATING_CASH_FLOW_MARGIN"),
            (self._at_current(observations, current, "operating_cash_flow", ("OPERATING_CASH_FLOW_TREND",)), "OPERATING_CASH_FLOW_TREND"),
            (self._latest_at_or_before(observations, current, "operating_cash_flow", ("TTM_YOY",)), "TTM_OPERATING_CASH_FLOW_YOY"),
            (self._latest_at_or_before(observations, current, "operating_cash_flow", ("TTM_OPERATING_CASH_FLOW_MARGIN",)), "TTM_OPERATING_CASH_FLOW_MARGIN"),
        ]
        return output

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
    def _overall_state(*, available_axis_count: int, transition_codes: set[str | None], deterioration_axes: int,
                       improvement_axes: int, axis_resolution: Mapping[str, str], momentum_state: str,
                       risks: tuple[str, ...]) -> tuple[str, str]:
        if available_axis_count < 2:
            return "INSUFFICIENT_DATA", "OVERALL_INSUFFICIENT_DATA_V01"
        if ("LOSS_TO_PROFIT" in transition_codes and improvement_axes >= 1
                and not (axis_resolution["CASH_FLOW"] == "WEAK" and "OCF_TREND_DETERIORATING" in risks)):
            return "TURNAROUND", "OVERALL_TURNAROUND_V01"
        if deterioration_axes >= 3 or (
            "PROFIT_TO_LOSS" in transition_codes and deterioration_axes >= 2
        ):
            return "WEAK", "OVERALL_WEAK_V01"
        if deterioration_axes >= 2:
            return "WEAKENING", "OVERALL_WEAKENING_V01"
        if (axis_resolution["GROWTH"] in {"STRONG", "POSITIVE"}
                and axis_resolution["PROFITABILITY"] in {"STRONG", "POSITIVE"}
                and axis_resolution["CASH_FLOW"] in {"STRONG", "POSITIVE"}
                and momentum_state in {"ACCELERATING", "IMPROVING", "STABLE"}
                and not risks):
            return "STRONG", "OVERALL_STRONG_V01"
        if (improvement_axes >= 2 and not (deterioration_axes >= 2)
                and axis_resolution["CASH_FLOW"] not in {"NEGATIVE", "WEAK"}):
            return "IMPROVING", "OVERALL_IMPROVING_V01"
        return "MIXED", "OVERALL_MIXED_V01"

    def _insufficient(self, *, ticker: str, family: str, requested: str | None, reason: str) -> FundamentalsAssessmentResult:
        return FundamentalsAssessmentResult(
            ticker=ticker, company_family=family, requested_as_of=requested,
            current_fiscal_year=None, current_fiscal_period=None,
            overall_state="INSUFFICIENT_DATA", growth_state=UNAVAILABLE,
            profitability_state=UNAVAILABLE, cash_flow_state=UNAVAILABLE,
            momentum_state=UNAVAILABLE, strengths=(), risks=(), evidence=(),
            available_axis_count=0, missing_axis_count=self.total_axis_count,
            pit_available_from=None, status="INSUFFICIENT_DATA",
            matched_rule_id="OVERALL_INSUFFICIENT_DATA_V01",
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
) -> FundamentalsAssessmentResult:
    """Convenience function for the pure assessment engine."""

    return FundamentalsAssessmentEngine().assess(source, requested_as_of=requested_as_of)


FundamentalsAssessment = FundamentalsAssessmentEngine
