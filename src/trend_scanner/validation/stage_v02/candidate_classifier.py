"""Pattern A Stage v0.2 Candidate Classifier Implementation (Validation/Analysis Only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_stage import (
    StageLifecycleContext,
    _build_lifecycle_context,
    ACTIVE_DECLINE_STEEP_MA24_SLOPE,
    ACTIVE_DECLINE_ACCEL_AVG_CHG,
    ACTIVE_DECLINE_LOW_RANGE_POSITION,
    BREAKOUT_RANGE_POSITION,
    EXPANSION_AVG_CHG,
    EXPANSION_MA_SPREAD,
    WEEKLY_MEANINGFUL_POSITIVE,
)
from trend_scanner.validation.feature_report import FeatureRow
from trend_scanner.validation.historical_snapshot import HistoricalSnapshot
from trend_scanner.validation.stage_v02.allowlist import (
    CANDIDATE_RAW_FEATURE_ALLOWLIST,
    CANDIDATE_RULE_SPEC_VERSION,
)


@dataclass(frozen=True)
class CandidateDiagnostics:
    """Full boolean sub-clause diagnostics and trace for candidate evaluation."""

    # Raw features presence / validity
    insufficient_data: bool
    positive_signal_from_missing: bool

    # Clause diagnostics
    active_decline: bool
    core_turning_positive: bool
    weekly_turning_positive: bool

    # Expansion / Progression clauses
    standard_expansion: bool
    mature_post_breakout: bool
    progression_eligible: bool

    # Early trend clause
    breakout_like_structure: bool

    # Transition clauses & sub-clauses
    ma_order_bullish: bool
    ma_order_bearish: bool
    spread_ratio_confirmation: bool
    core_led: bool
    weekly_led: bool
    transition_eligibility: bool

    # Lifecycle state & termination
    previously_expanded_before_snapshot: bool
    current_strict_expansion: bool
    current_episode_terminated: bool
    previously_expanded_after_snapshot: bool

    # Execution trace
    precedence_path: str
    veto_applied: str | None


@dataclass(frozen=True)
class CandidateStageResult:
    """Stage v0.2 candidate evaluation result."""

    candidate_stage: PatternAStage | None
    candidate_reason_codes: tuple[str, ...]
    candidate_diagnostics: CandidateDiagnostics
    context: StageLifecycleContext


def _is_invalid_float(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, (int, float)):
        return math.isnan(val) or math.isinf(val)
    return False


def classify_pattern_a_stage_v02_candidate(
    snapshot: HistoricalSnapshot,
    override_state_before: bool | None = None,
) -> CandidateStageResult:
    """Evaluate Stage v0.2 candidate logic for a given historical snapshot.

    Score v0.2 and score derived values are strictly prohibited as input.
    Only raw FeatureRow fields and un-leaked historical snapshot data are consumed.
    """
    features = snapshot.features
    monthly = snapshot.monthly

    # Required core features validation
    core_required = (
        "ma6",
        "ma12",
        "ma24",
        "ma24_slope",
        "weekly_ma12_slope",
        "ma24_slope_acceleration",
        "avg_price_change_12m",
        "ma_spread",
        "range_position",
        "distance_to_resistance",
    )
    missing_fields = [name for name in core_required if _is_invalid_float(getattr(features, name, None))] if features is not None else True

    if missing_fields or features is None or monthly is None:
        state_val = bool(override_state_before) if override_state_before is not None else False
        empty_diag = CandidateDiagnostics(
            insufficient_data=True,
            positive_signal_from_missing=False,
            active_decline=False,
            core_turning_positive=False,
            weekly_turning_positive=False,
            standard_expansion=False,
            mature_post_breakout=False,
            progression_eligible=False,
            breakout_like_structure=False,
            ma_order_bullish=False,
            ma_order_bearish=False,
            spread_ratio_confirmation=False,
            core_led=False,
            weekly_led=False,
            transition_eligibility=False,
            previously_expanded_before_snapshot=state_val,
            current_strict_expansion=False,
            current_episode_terminated=False,
            previously_expanded_after_snapshot=state_val,
            precedence_path="insufficient_data",
            veto_applied=None,
        )
        empty_context = StageLifecycleContext(
            prior_expansion_detected=False,
            episode_broken_after_expansion=False,
            last_expansion_month=None,
            months_since_expansion=None,
            previously_expanded_in_current_episode=False,
        )
        return CandidateStageResult(
            candidate_stage=None,
            candidate_reason_codes=("insufficient_data",),
            candidate_diagnostics=empty_diag,
            context=empty_context,
        )

    # Lifecycle context builder (v0.1 point formula)
    context = _build_lifecycle_context(monthly)

    # Bind raw feature values
    ma6: float = float(features.ma6)
    ma12: float = float(features.ma12)
    ma24: float = float(features.ma24)
    ma24_slope: float = float(features.ma24_slope)
    weekly_ma12_slope: float = float(features.weekly_ma12_slope)
    ma24_slope_accel: float = float(features.ma24_slope_acceleration)
    avg_price_change_12m: float = float(features.avg_price_change_12m)
    ma_spread: float = float(features.ma_spread)
    ma_spread_ratio_val = getattr(features, "ma_spread_ratio", None)
    if ma_spread_ratio_val is not None and not _is_invalid_float(ma_spread_ratio_val):
        ma_spread_ratio = float(ma_spread_ratio_val)
        spread_ratio_confirmation = ma_spread_ratio >= 0.75
    else:
        ma_spread_ratio = float("nan")
        spread_ratio_confirmation = False
    range_position: float = float(features.range_position)
    distance_to_resistance: float = float(features.distance_to_resistance)

    # 2. Compute boolean sub-clauses
    core_turning_positive = ma24_slope > 0
    weekly_turning_positive = weekly_ma12_slope >= WEEKLY_MEANINGFUL_POSITIVE

    active_decline = (
        ma24_slope <= ACTIVE_DECLINE_STEEP_MA24_SLOPE
        or (ma24_slope_accel < 0 and avg_price_change_12m <= ACTIVE_DECLINE_ACCEL_AVG_CHG)
        or (weekly_ma12_slope <= 0 and range_position <= ACTIVE_DECLINE_LOW_RANGE_POSITION)
    )

    # Progression clauses (mature_post_breakout is DIAGNOSTIC_ONLY)
    standard_expansion = core_turning_positive and (avg_price_change_12m >= EXPANSION_AVG_CHG or ma_spread >= EXPANSION_MA_SPREAD)
    mature_post_breakout = core_turning_positive and (range_position >= 0.90 and avg_price_change_12m >= 0.25 and ma_spread >= 0.18)
    progression_eligible = standard_expansion

    # Breakout clause
    breakout_like_structure = core_turning_positive and weekly_turning_positive and range_position >= BREAKOUT_RANGE_POSITION

    # MA ordering & spread ratio confirmation
    ma_order_bullish = bool(ma6 > ma12 > ma24)
    ma_order_bearish = bool(ma6 < ma12 < ma24)

    # Transition pathways
    core_led = (
        ma24_slope >= 0.001
        and (ma_order_bullish or spread_ratio_confirmation or range_position >= 0.50 or ma24_slope >= 0.015)
        and (avg_price_change_12m >= 0.05 or range_position >= 0.25)
    )
    weekly_led = (
        weekly_ma12_slope >= 0.03
        and (
            (ma24_slope >= -0.040 and range_position >= 0.45)
            or (ma24_slope >= -0.025 and not ma_order_bearish and (avg_price_change_12m >= -0.25 or range_position >= 0.30))
        )
    )
    transition_eligibility = core_led or weekly_led

    # Lifecycle state evaluation
    # previously_expanded_before_snapshot is determined by context or explicit stream state_before
    if override_state_before is not None:
        previously_expanded_before = override_state_before
    else:
        previously_expanded_before = context.previously_expanded_in_current_episode

    current_strict_expansion = core_turning_positive and avg_price_change_12m >= 0.30
    current_episode_terminated = bool(
        previously_expanded_before
        and weekly_ma12_slope < 0
        and avg_price_change_12m < 0.20
        and range_position < 0.40
    )

    # State after computation
    if current_episode_terminated:
        previously_expanded_after = False
    elif current_strict_expansion:
        previously_expanded_after = True
    else:
        previously_expanded_after = previously_expanded_before

    # 3. Decision Precedence Order (Frozen Cascade)
    veto_applied: str | None = None

    if active_decline:
        stage = PatternAStage.WEAK
        reason = ["active_decline"]
        precedence_path = "active_decline"
    elif progression_eligible:
        stage = PatternAStage.PROGRESSED
        reason = ["core_turning_positive", "expansion_present"]
        precedence_path = "progression_eligible"
    elif breakout_like_structure:
        stage = PatternAStage.EARLY_TREND
        reason = ["breakout_like_structure"]
        precedence_path = "breakout_like_structure"
    elif transition_eligibility:
        if current_episode_terminated:
            # Termination is an admission veto to TRANSITION, falling through to BASE
            stage = PatternAStage.BASE
            reason = ["episode_terminated_transition_veto", "fallback_base"]
            veto_applied = "episode_terminated_transition_veto"
            precedence_path = "transition_terminated_veto_fallback_base"
        else:
            stage = PatternAStage.TRANSITION
            reason = []
            if core_led:
                reason.append("core_led_transition")
            if weekly_led:
                reason.append("weekly_led_transition")
            precedence_path = "transition_eligible"
    else:
        stage = PatternAStage.BASE
        reason = ["fallback_base"]
        precedence_path = "fallback_base"

    diagnostics = CandidateDiagnostics(
        insufficient_data=False,
        positive_signal_from_missing=False,
        active_decline=active_decline,
        core_turning_positive=core_turning_positive,
        weekly_turning_positive=weekly_turning_positive,
        standard_expansion=standard_expansion,
        mature_post_breakout=mature_post_breakout,
        progression_eligible=progression_eligible,
        breakout_like_structure=breakout_like_structure,
        ma_order_bullish=ma_order_bullish,
        ma_order_bearish=ma_order_bearish,
        spread_ratio_confirmation=spread_ratio_confirmation,
        core_led=core_led,
        weekly_led=weekly_led,
        transition_eligibility=transition_eligibility,
        previously_expanded_before_snapshot=previously_expanded_before,
        current_strict_expansion=current_strict_expansion,
        current_episode_terminated=current_episode_terminated,
        previously_expanded_after_snapshot=previously_expanded_after,
        precedence_path=precedence_path,
        veto_applied=veto_applied,
    )

    return CandidateStageResult(
        candidate_stage=stage,
        candidate_reason_codes=tuple(reason),
        candidate_diagnostics=diagnostics,
        context=context,
    )
