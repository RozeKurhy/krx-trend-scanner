from __future__ import annotations

import pytest

from trend_scanner.fundamentals.assessment import FundamentalsAssessmentEngine
from trend_scanner.fundamentals.assessment_models import FundamentalsAssessmentResult
from trend_scanner.fundamentals.derived_metrics import DerivedMetricObservation, DerivedMetricsResult


AS_OF = "2025-10-15"


def _item(metric: str, metric_type: str, value, *, status: str = "READY", metadata=None,
          family: str = "NON_FINANCIAL", period: str = "Q3", pit: str | None = AS_OF,
          source_dt: str = AS_OF, reason: str | None = None) -> DerivedMetricObservation:
    return DerivedMetricObservation(
        ticker="TEST", corp_code="TEST", company_family=family, fiscal_year="2025",
        fiscal_period=period, metric=metric, metric_type=metric_type, value=value,
        resolution_status=status, reason=reason, period_end="2025-09-30",
        source_rcept_nos=(f"R-{metric}-{metric_type}",), source_rcept_dts=(source_dt,),
        source_sha256s=(f"sha-{metric}-{metric_type}",), requested_as_of=AS_OF,
        pit_available_from=pit, metadata=metadata or {},
    )


def _scenario(*, revenue=10, operating_income=10, net_income=10, ocf=10,
              op_margin=10, net_margin=5, ocf_margin=4,
              op_expansion="EXPANDING", net_expansion="EXPANDING",
              ocf_trend="IMPROVING", acceleration=1, streak=3,
              op_transition="PROFIT_GROWTH", net_transition="PROFIT_GROWTH"):
    rows = [
        _item("revenue", "QUARTERLY_YOY", revenue),
        _item("operating_income", "QUARTERLY_YOY", operating_income),
        _item("net_income", "QUARTERLY_YOY", net_income),
        _item("operating_cash_flow", "QUARTERLY_YOY", ocf),
        _item("operating_income", "OPERATING_MARGIN", op_margin),
        _item("net_income", "NET_MARGIN", net_margin),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", ocf_margin),
        _item("operating_income", "MARGIN_EXPANSION_TREND", 1 if op_expansion == "EXPANDING" else -1 if op_expansion == "CONTRACTING" else 0,
              metadata={"classification": op_expansion}),
        _item("net_income", "MARGIN_EXPANSION_TREND", 1 if net_expansion == "EXPANDING" else -1 if net_expansion == "CONTRACTING" else 0,
              metadata={"classification": net_expansion}),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", ocf_trend),
        *[_item(metric, "YOY_GROWTH_ACCELERATION", acceleration) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        *[_item(metric, "CONSECUTIVE_YOY_GROWTH", streak) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        _item("operating_income", "EARNINGS_TRANSITION", op_transition),
        _item("net_income", "EARNINGS_TRANSITION", net_transition),
    ]
    return DerivedMetricsResult(tuple(rows))


def test_broad_strong_is_deterministic_and_has_no_score():
    result = FundamentalsAssessmentEngine().assess(_scenario())
    assert isinstance(result, FundamentalsAssessmentResult)
    assert result.overall_state == "STRONG"
    assert result.matched_rule_id == "OVERALL_STRONG_V01"
    assert result.status == "READY"
    assert not any("score" in key.lower() for key in result.to_dict())


def test_turnaround_uses_transition_without_percentage_growth():
    result = FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT"))
    assert result.overall_state == "TURNAROUND"
    assert "LOSS_TO_PROFIT" in result.strengths
    transition = next(item for item in result.evidence if item.metric_type == "EARNINGS_TRANSITION" and item.metric == "operating_income")
    assert transition.explanation_code == "LOSS_TO_PROFIT"


def test_margin_warning_is_mixed_and_cash_divergence_is_a_risk():
    warning = FundamentalsAssessmentEngine().assess(_scenario(op_expansion="CONTRACTING", net_expansion="CONTRACTING", ocf=0, ocf_margin=-1, ocf_trend="DETERIORATING"))
    assert warning.overall_state in {"MIXED", "WEAKENING"}
    divergence = FundamentalsAssessmentEngine().assess(_scenario(ocf=-20, ocf_margin=-1, ocf_trend="DETERIORATING"))
    assert divergence.overall_state == "MIXED"
    assert any(code.startswith("OPERATING_CASH_FLOW") or code.startswith("OCF_") for code in divergence.risks)


def test_broad_weak_and_deceleration_are_not_positive():
    weak = FundamentalsAssessmentEngine().assess(_scenario(revenue=-10, operating_income=-20, net_income=-20, ocf=-20,
                                                            op_margin=-2, net_margin=-3, ocf_margin=-4,
                                                            op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                                            ocf_trend="DETERIORATING", acceleration=-1,
                                                            op_transition="PROFIT_DECLINE", net_transition="PROFIT_DECLINE"))
    assert weak.overall_state == "WEAK"
    slowing = FundamentalsAssessmentEngine().assess(_scenario(op_margin=-1, net_margin=-1, ocf=-10, ocf_margin=-1,
                                                               op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                                               ocf_trend="DETERIORATING", acceleration=-1))
    assert slowing.overall_state == "WEAKENING"
    assert slowing.momentum_state in {"DECELERATING", "DETERIORATING"}


def test_insufficient_data_does_not_backfill_previous_period():
    rows = (_item("revenue", "QUARTERLY_YOY", 10),)
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(rows), requested_as_of=AS_OF)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.overall_state == "INSUFFICIENT_DATA"
    assert result.available_axis_count < 2


def test_unavailable_current_metric_is_not_zero_or_previous_period_fallback():
    rows = list(_scenario())
    index = next(i for i, item in enumerate(rows) if item.metric == "revenue" and item.metric_type == "QUARTERLY_YOY")
    rows[index] = _item("revenue", "QUARTERLY_YOY", None, status="INPUT_NOT_READY", reason="MARGIN_INPUT_UNAVAILABLE")
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(tuple(rows)))
    evidence = next(item for item in result.evidence if item.metric == "revenue" and item.axis == "GROWTH")
    assert evidence.status == "INPUT_NOT_READY"
    assert evidence.value is None
    assert evidence.direction == "NEUTRAL"


def test_sign_transition_and_zero_base_fail_closed():
    transition = FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT"))
    assert any(item.classification == "LOSS_TO_PROFIT" for item in transition.evidence)
    zero = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("revenue", "QUARTERLY_YOY", None, status="UNDEFINED_BASE", reason="NON_POSITIVE_OR_SIGN_TRANSITION_BASE"),
                              _item("operating_income", "QUARTERLY_YOY", 10),
                              _item("operating_cash_flow", "QUARTERLY_YOY", 10)))
    )
    assert not any(item.explanation_code == "REVENUE_YOY_POSITIVE" for item in zero.evidence)


def test_financial_is_explicitly_not_applicable():
    result = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("net_income", "QUARTERLY_YOY", 10, family="FINANCIAL"),))
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.overall_state == "NOT_APPLICABLE"
    assert result.matched_rule_id == "FINANCIAL_PROFILE_NOT_IMPLEMENTED"


def test_pit_and_cutoff_fail_closed_without_future_evidence():
    future = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("revenue", "QUARTERLY_YOY", 10, source_dt="2025-10-20", pit="2025-10-20"),
                              _item("operating_income", "QUARTERLY_YOY", 10),
                              _item("operating_cash_flow", "QUARTERLY_YOY", 10))),
        requested_as_of=AS_OF,
    )
    assert future.status == "INPUT_NOT_READY"
    assert future.diagnostics["future_assessment_source_count"] > 0
    mismatch = FundamentalsAssessmentEngine().assess(_scenario(), requested_as_of="2025-11-01")
    assert mismatch.status == "INPUT_NOT_READY"
    assert mismatch.matched_rule_id == "INPUT_CUTOFF_MISMATCH"
