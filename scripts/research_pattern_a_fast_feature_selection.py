#!/usr/bin/env python
"""Phase 13G-1 feature selection / role assignment (research only).

This program is intentionally a read-only consumer of the frozen 13C--13F
research artifacts.  It does not load market data, recalculate features, or
create a production score or lifecycle rule.  It produces a role registry,
cross-timeframe redundancy view, selected 40-sample matrix, and candidate
architecture metadata for advisor review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


BASE_COMMIT = "505c412f504dbb1a5a475e2562a0a1749eaa6508"
HUMAN_CALIBRATION_SHA = "2e5a87f8214fe91d6cd2dbfa2bdc03cc2453d696"
MONTHLY_RESEARCH_SHA = "6917b1341553b58fa42390ba1507fc9b80551fee"
WEEKLY_RESEARCH_SHA = "415583ab97835d6d98c945476de45aafdd6371b7"
DAILY_RESEARCH_SHA = BASE_COMMIT

RESEARCH_DIR = Path("artifacts/patterns/pattern_a_fast/research/feature_role")
MONTHLY_MATRIX = RESEARCH_DIR / "monthly_regime_feature_matrix_v01.csv"
WEEKLY_MATRIX = RESEARCH_DIR / "weekly_trigger_feature_matrix_v01.csv"
DAILY_MATRIX = RESEARCH_DIR / "daily_timing_feature_matrix_v01.csv"
JOIN_MATRIX = RESEARCH_DIR / "monthly_weekly_daily_research_join_v01.csv"
MONTHLY_SUMMARY = RESEARCH_DIR / "monthly_regime_feature_summary_v01.csv"
WEEKLY_SUMMARY = RESEARCH_DIR / "weekly_trigger_feature_summary_v01.csv"
DAILY_SUMMARY = RESEARCH_DIR / "daily_timing_feature_summary_v01.csv"

REGISTRY_PATH = RESEARCH_DIR / "pattern_a_fast_feature_role_registry_v01.csv"
REDUNDANCY_PATH = RESEARCH_DIR / "pattern_a_fast_cross_timeframe_redundancy_v01.csv"
SELECTED_MATRIX_PATH = RESEARCH_DIR / "pattern_a_fast_selected_feature_matrix_v01.csv"
ARCHITECTURE_PATH = RESEARCH_DIR / "pattern_a_fast_candidate_architecture_v01.json"

ROLE_ENUM = {
    "MONTHLY_PERMISSION",
    "WEEKLY_CORE",
    "DAILY_TIMING_RISK",
    "CONDITIONAL_STRUCTURE",
    "DIAGNOSTIC",
    "HOLD_RESEARCH",
    "DROP_REDUNDANT",
}
STATUS_ENUM = {"PRIMARY", "SECONDARY", "CONDITIONAL", "DIAGNOSTIC", "HOLD", "DROP"}


@dataclass(frozen=True)
class FeatureSpec:
    timeframe: str
    feature_name: str
    source_phase: str
    candidate_role: str
    selection_status: str
    semantic_concept: str
    expected_direction: str
    monotonicity: str
    event_conditioned: str
    primary_comparison: str
    secondary_evidence: str
    redundancy_group: str
    redundancy_with: str
    human_observation: str
    case_study_support: str
    known_counterexample: str
    known_limitation: str
    missing_semantics: str
    selection_rationale: str
    next_phase_usage: str


# These are role hypotheses, not executable gate, score, or stage behaviour.
SPECS = (
    FeatureSpec("MONTHLY", "range_position_24m", "13D", "MONTHLY_PERMISSION", "PRIMARY", "long-term price location / early-to-extended zone", "ZONE_DEPENDENT", "NON_MONOTONIC_CANDIDATE", "NO", "GOOD_TRIGGER vs NO_SETUP", "full coverage; separates early and extended endpoints", "LONG_TERM_POSITION", "close_vs_ma24_pct; higher_monthly_low_count_12m", "captures long-horizon location without creating a trigger", "천일고속 early-to-extended pair", "very high values can be TOO_EXTENDED", "40 calibration samples; zone shape not frozen", "FULL_COVERAGE", "Retains the monthly location semantic; its non-monotonic pattern rules out a one-sided hard gate.", "GATE_OR_ZONE_CANDIDATE"),
    FeatureSpec("MONTHLY", "drawdown_from_12m_high", "13D", "MONTHLY_PERMISSION", "SECONDARY", "recovery distance from recent high", "CLOSER_TO_HIGHER_LEVEL", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "strong label separation with distinct drawdown wording", "LONG_TERM_DRAWDOWN", "range_position_24m", "recovery context complements location", "LS pair", "can overlap strongly with long-term location", "does not independently prove a weekly trigger", "FULL_COVERAGE", "Kept as a secondary recovery view because it describes a different reference frame from range position.", "SCORE_CANDIDATE"),
    FeatureSpec("MONTHLY", "close_vs_ma24_pct", "13D", "DROP_REDUNDANT", "DROP", "monthly moving-average price location", "HIGHER_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "strong same-timeframe correlation with range position", "LONG_TERM_POSITION", "range_position_24m", "weekly and daily MA-distance shadows also exist", "천일고속 pair", "correlation 0.935 with range_position_24m", "price position is already represented more broadly", "FULL_COVERAGE", "Dropped as the strongest duplicate of retained range position; this is not an assertion that MA location lacks research value.", "NO_PRODUCTION_ROLE_YET"),
    FeatureSpec("MONTHLY", "ma_alignment_score", "13D", "MONTHLY_PERMISSION", "SECONDARY", "monthly moving-average order / structure", "MORE_ALIGNED_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "order information differs conceptually from raw price location", "MA_ALIGNMENT", "close_vs_ma24_pct; range_position_24m", "long-horizon structure context", "LS pair", "shares location information in small sample", "coarse discrete score and calibration-only evidence", "FULL_COVERAGE", "Retained behind range position because MA ordering may add structural context after redundant raw MA distance is removed.", "SCORE_CANDIDATE"),
    FeatureSpec("MONTHLY", "monthly_down_month_ratio_12m", "13D", "MONTHLY_PERMISSION", "PRIMARY", "down-month persistence / downside pressure", "LOWER_IS_STRUCTURALLY_HEALTHIER", "EXPECTED_NEGATIVE", "NO", "GOOD_TRIGGER vs FALSE_TRIGGER", "high separation from failed structure and differs from price magnitude", "DOWNSIDE_PERSISTENCE", "range_position_24m; close_vs_ma24_pct", "adds persistence rather than another price level", "안국약품 trigger anchor", "can co-move with recovery and location", "descriptive direction only; no cutoff", "FULL_COVERAGE", "Primary monthly complement to location because it preserves the separate question of persistent downside pressure.", "GATE_CANDIDATE"),
    FeatureSpec("MONTHLY", "higher_monthly_low_count_12m", "13D", "MONTHLY_PERMISSION", "SECONDARY", "monthly bottoming / higher-low structure", "MORE_HIGHER_LOWS_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "human-readable bottoming evidence", "BOTTOMING", "range_position_24m; close_vs_ma24_pct", "monthly bottoming is not a weekly trigger", "LS pair", "correlation 0.817 with range position", "may be redundant after location and persistence inputs", "FULL_COVERAGE", "Kept as secondary rather than promoted: it is interpretable bottoming evidence but substantially overlaps retained long-term location.", "SCORE_CANDIDATE"),
    FeatureSpec("MONTHLY", "recent_3m_return", "13D", "DIAGNOSTIC", "DIAGNOSTIC", "short-horizon monthly momentum / extension context", "CONTEXT_DEPENDENT", "NON_MONOTONIC_CANDIDATE", "NO", "GOOD_TRIGGER vs TOO_EXTENDED", "very strong extension contrast but mixed false-trigger evidence", "MONTHLY_MOMENTUM", "wma12_vs_wma26_pct", "useful to explain late/extended cases", "우리기술 good-vs-too-late pair", "GOOD vs FALSE direction is mixed", "too short-horizon to become a monthly permission primary", "FULL_COVERAGE", "Diagnostic only: it describes progress and extension but does not safely grant long-term permission by itself.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("WEEKLY", "post_breakout_min_low_vs_level_pct_26w", "13E", "CONDITIONAL_STRUCTURE", "CONDITIONAL", "post-event breakout hold quality", "HIGHER_HOLD_IS_BETTER_WHEN_EVENT_EXISTS", "EXPECTED_POSITIVE", "YES", "GOOD_TRIGGER vs NO_SETUP", "strong observed-event separation; event is machine-derived", "BREAKOUT_HOLD", "rolling_low_4w_change", "conditional breakout-quality context only", "안국약품 trigger anchor", "no recent event is not BAD", "available for 19 of 40; EVENT_NOT_OBSERVED is semantic", "EVENT_NOT_OBSERVED", "Conditional by design: it can assess a recent observed breakout but cannot become a universal gate or a human-trigger replacement.", "CONDITIONAL_SCORE_CANDIDATE"),
    FeatureSpec("WEEKLY", "close_vs_wma200_pct", "13E", "WEEKLY_CORE", "PRIMARY", "weekly long-term resistance / price relation", "ABOVE_OR_NEAR_RESISTANCE_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "directly maps to the human weekly-200MA-resistance observation", "WEEKLY_RESISTANCE", "wma52_slope_1w", "weekly long-horizon resistance differs from daily timing", "천일고속 pair", "only 30 effective observations due to history", "insufficient history is not a negative observation", "INSUFFICIENT_HISTORY", "Primary weekly structural candidate because it directly represents resistance, while missing history remains non-scoring metadata.", "GATE_CANDIDATE"),
    FeatureSpec("WEEKLY", "distance_to_prior_26w_high_pct", "13E", "WEEKLY_CORE", "PRIMARY", "proximity to prior 26-week high", "CLOSER_TO_PRIOR_HIGH_IS_MORE_READY", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "full coverage and lower cross-timeframe redundancy than MA-distance shadows", "PRIOR_HIGH_PROXIMITY", "close_vs_wma200_pct", "weekly readiness without inventing a trigger event", "우리기술 pair", "does not determine whether a breakout has occurred", "no numeric proximity boundary is selected", "FULL_COVERAGE", "Primary weekly readiness semantic: it remains distinct from long-term resistance and does not create a machine stage.", "SCORE_CANDIDATE"),
    FeatureSpec("WEEKLY", "higher_weekly_low_count_13w", "13E", "WEEKLY_CORE", "PRIMARY", "weekly higher-low structure", "MORE_HIGHER_LOWS_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "direct structural signal with full coverage", "HIGHER_LOW_STRUCTURE", "rolling_low_4w_change", "retains the core weekly progression semantic", "LS pair", "GOOD vs FALSE contrast is mixed", "small labeled groups limit confidence", "FULL_COVERAGE", "Primary weekly structural candidate because it preserves higher-low information not reducible to prior-high proximity.", "SCORE_CANDIDATE"),
    FeatureSpec("WEEKLY", "wma52_slope_1w", "13E", "WEEKLY_CORE", "SECONDARY", "weekly long-term trend direction", "RISING_SLOPE_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs TOO_EARLY", "full coverage but high shadow correlation with daily DMA200", "WEEKLY_TREND", "close_vs_dma200_pct; wma12_vs_wma26_pct", "weekly direction is more relevant than daily long-MA shadow", "천일고속 pair", "does not isolate a trigger; overlaps MA alignment", "one-week slope can be noisy", "FULL_COVERAGE", "Kept as a secondary weekly source of trend direction; daily DMA200 is demoted to avoid duplicate cross-timeframe trend inputs.", "SCORE_CANDIDATE"),
    FeatureSpec("WEEKLY", "wma12_vs_wma26_pct", "13E", "WEEKLY_CORE", "SECONDARY", "weekly medium-term MA alignment", "MORE_POSITIVE_ALIGNMENT_IS_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs TOO_EXTENDED", "describes extension as well as alignment", "WEEKLY_ALIGNMENT", "wma52_slope_1w; close_vs_dma200_pct", "weekly alignment is retained before daily MA shadows", "우리기술 good-vs-too-late pair", "strong overlap with weekly slope and daily long-MA distance", "nonlinear late/extended behaviour remains unresolved", "FULL_COVERAGE", "Secondary only: it is interpretable weekly alignment but must not duplicate trend and daily MA features as an independent primary.", "SCORE_CANDIDATE"),
    FeatureSpec("WEEKLY", "rolling_low_4w_change", "13E", "DIAGNOSTIC", "DIAGNOSTIC", "short weekly low progression", "HIGHER_LOW_PROGRESS_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "useful progression explanation but overlaps higher-low count and breakout hold", "SHORT_PROGRESS", "higher_weekly_low_count_13w; post_breakout_min_low_vs_level_pct_26w", "helps explain short-term progression", "안국약품 trigger anchor", "correlation 0.844 with conditional breakout hold", "short window is unstable and redundant with retained weekly structure", "FULL_COVERAGE", "Diagnostic only: it is a compact case-study aid but adds insufficient independent responsibility beside retained higher-low and conditional hold semantics.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("DAILY", "close_vs_dma200_pct", "13F", "DIAGNOSTIC", "DIAGNOSTIC", "daily long-MA location", "HIGHER_IS_STRUCTURALLY_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "strong separation but cross-timeframe shadow of weekly trend", "DAILY_MA_SHADOW", "wma52_slope_1w; wma12_vs_wma26_pct", "daily context may explain an entry, never reverse weekly structure", "에이치엠넥스 DMA200-below GOOD_TRIGGER", "correlation 0.905 with weekly wma52 slope", "daily long-MA location is not a hard eligibility condition", "FULL_COVERAGE", "Diagnostic shadow only: weekly trend owns the structural responsibility, and the documented GOOD_TRIGGER below DMA200 rejects a daily hard filter.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("DAILY", "dma20_vs_dma60_pct", "13F", "DIAGNOSTIC", "DIAGNOSTIC", "daily short/medium MA alignment", "MORE_POSITIVE_ALIGNMENT_IS_STRONGER", "EXPECTED_POSITIVE", "NO", "GOOD_TRIGGER vs TOO_EXTENDED", "daily alignment overlaps weekly low progression", "DAILY_MA_SHADOW", "rolling_low_4w_change; wma12_vs_wma26_pct", "daily timing context only", "우리기술 good-vs-too-late pair", "correlation 0.839 with weekly rolling-low change", "may duplicate weekly trigger-quality structure", "FULL_COVERAGE", "Diagnostic shadow only: daily MA alignment does not receive an independent core responsibility ahead of the weekly layer.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("DAILY", "recent_5d_max_gap_abs_pct", "13F", "DAILY_TIMING_RISK", "PRIMARY", "recent maximum absolute daily gap / shock risk", "LOWER_VOLATILITY_RISK_IS_PREFERABLE", "EXPECTED_NEGATIVE", "NO", "GOOD_TRIGGER vs NO_SETUP", "strong separation from NO_SETUP, FALSE, and EXTENDED; direct shock interpretation", "DAILY_VOLATILITY", "atr_14_pct", "represents discrete event-like gap risk rather than broad range", "FALSE_TRIGGER review", "moderately correlated with ATR", "40-sample evidence; no risk cutoff is selected", "FULL_COVERAGE", "Chosen as the single primary daily volatility representative because it is directly interpretable as recent shock risk; ATR remains a secondary breadth check.", "RISK_MODIFIER_CANDIDATE"),
    FeatureSpec("DAILY", "higher_daily_low_count_10d", "13F", "HOLD_RESEARCH", "HOLD", "daily higher-low count", "UNRESOLVED", "UNRESOLVED", "NO", "GOOD_TRIGGER vs NO_SETUP", "observed separation has counterintuitive sign", "DAILY_MICRO_STRUCTURE", "higher_weekly_low_count_13w", "possible base-versus-active-trigger interpretation", "안국약품 trigger anchor", "GOOD median is lower than NO_SETUP", "causal and directional meaning not established", "FULL_COVERAGE", "Held for research: apparent separation is insufficient when the direction contradicts the naive structural reading.", "NO_PRODUCTION_ROLE_YET"),
    FeatureSpec("DAILY", "gap_from_prev_close_pct", "13F", "DIAGNOSTIC", "DIAGNOSTIC", "one-day directional gap", "CONTEXT_DEPENDENT", "UNRESOLVED", "NO", "GOOD_TRIGGER vs NO_SETUP", "low redundancy does not overcome one-day noise", "DAILY_GAP", "recent_5d_max_gap_abs_pct", "useful single-bar explanation only", "FALSE_TRIGGER review", "7 exact-zero observations and weak label separation", "tick and one-day noise sensitivity", "FULL_COVERAGE", "Diagnostic only: independence from other variables does not turn a noisy one-day observation into a timing primary.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("DAILY", "lower_wick_pct", "13F", "DIAGNOSTIC", "DIAGNOSTIC", "single-candle lower-wick morphology", "CONTEXT_DEPENDENT", "UNRESOLVED", "NO", "GOOD_TRIGGER vs NO_SETUP", "price-level artifact check passed but causal meaning is weak", "DAILY_CANDLE", "recent_5d_max_gap_abs_pct", "candle description may help review", "FALSE_TRIGGER review", "mixed FALSE and EARLY evidence", "single-candle instability", "FULL_COVERAGE", "Diagnostic only: morphology can annotate a case but is not assigned direct structural or risk authority.", "DIAGNOSTIC_ONLY"),
    FeatureSpec("DAILY", "atr_14_pct", "13F", "DAILY_TIMING_RISK", "SECONDARY", "rolling daily volatility breadth", "LOWER_VOLATILITY_RISK_IS_PREFERABLE", "EXPECTED_NEGATIVE", "NO", "GOOD_TRIGGER vs TOO_EXTENDED", "broad range-risk context complements discrete gap shock", "DAILY_VOLATILITY", "recent_5d_max_gap_abs_pct", "moderate redundancy is explicitly consolidated", "천일고속 extended case", "Spearman 0.791 with max gap", "does not receive equal primary responsibility", "FULL_COVERAGE", "Secondary volatility companion: it describes persistent range breadth while max-gap owns the primary short-shock role.", "RISK_MODIFIER_CANDIDATE"),
)


def _source_column(spec: FeatureSpec) -> str:
    if spec.timeframe == "MONTHLY":
        return f"MONTHLY_{spec.feature_name}"
    if spec.timeframe == "WEEKLY":
        return f"WEEKLY_{spec.feature_name}"
    return spec.feature_name


def _read_summary(spec: FeatureSpec) -> pd.Series:
    path = {"MONTHLY": MONTHLY_SUMMARY, "WEEKLY": WEEKLY_SUMMARY, "DAILY": DAILY_SUMMARY}[spec.timeframe]
    summary = pd.read_csv(path).set_index("feature_name")
    return summary.loc[spec.feature_name]


def _max_correlations(join: pd.DataFrame, spec: FeatureSpec) -> tuple[float | None, float | None]:
    source = _source_column(spec)
    all_columns = {_source_column(item): item for item in SPECS}
    corr = join[list(all_columns)].corr(method="spearman")[source]
    same, cross = [], []
    for column, value in corr.items():
        if column == source or pd.isna(value):
            continue
        target = all_columns[column]
        (same if target.timeframe == spec.timeframe else cross).append(abs(float(value)))
    return (max(same) if same else None, max(cross) if cross else None)


def build_registry(join: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec in SPECS:
        summary = _read_summary(spec)
        same_corr, cross_corr = _max_correlations(join, spec)
        rows.append(
            {
                "timeframe": spec.timeframe,
                "feature_name": spec.feature_name,
                "source_phase": spec.source_phase,
                "source_priority": "HIGH",
                "candidate_role": spec.candidate_role,
                "selection_status": spec.selection_status,
                "semantic_concept": spec.semantic_concept,
                "expected_direction": spec.expected_direction,
                "monotonicity": spec.monotonicity,
                "event_conditioned": spec.event_conditioned,
                "availability_count": int(summary["count"]),
                "missing_count": int(summary["missing_count"]),
                "primary_comparison": spec.primary_comparison,
                "primary_effect_size": float(summary["cliffs_delta_GOOD_TRIGGER_vs_NO_SETUP"]),
                "secondary_evidence": spec.secondary_evidence,
                "max_abs_corr_same_timeframe": same_corr,
                "max_abs_corr_cross_timeframe": cross_corr,
                "redundancy_group": spec.redundancy_group,
                "redundancy_with": spec.redundancy_with,
                "human_observation": spec.human_observation,
                "case_study_support": spec.case_study_support,
                "known_counterexample": spec.known_counterexample,
                "known_limitation": spec.known_limitation,
                "missing_semantics": spec.missing_semantics,
                "selection_rationale": spec.selection_rationale,
                "next_phase_usage": spec.next_phase_usage,
            }
        )
    registry = pd.DataFrame(rows)
    assert len(registry) == 21
    assert registry["candidate_role"].isin(ROLE_ENUM).all()
    assert registry["selection_status"].isin(STATUS_ENUM).all()
    return registry


def build_cross_timeframe_redundancy(join: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    specs_by_column = {_source_column(spec): spec for spec in SPECS}
    corr = join[list(specs_by_column)].corr(method="spearman")
    rows = []
    columns = list(specs_by_column)
    for index, column_a in enumerate(columns):
        for column_b in columns[index + 1 :]:
            spec_a, spec_b = specs_by_column[column_a], specs_by_column[column_b]
            if spec_a.timeframe == spec_b.timeframe:
                continue
            value = corr.loc[column_a, column_b]
            if pd.isna(value):
                continue
            abs_value = abs(float(value))
            status_a = registry.loc[registry.feature_name == spec_a.feature_name, "selection_status"].item()
            status_b = registry.loc[registry.feature_name == spec_b.feature_name, "selection_status"].item()
            if abs_value >= 0.85:
                action = "STRONG_REDUNDANCY_REVIEWED"
            elif abs_value >= 0.70:
                action = "MODERATE_REDUNDANCY_REVIEWED"
            else:
                action = "RETAIN_DISTINCT_TIMEFRAME_SEMANTICS"
            overlap = "MA_OR_PRICE_LOCATION" if "ma" in spec_a.feature_name or "ma" in spec_b.feature_name else "TIMEFRAME_SPECIFIC_OR_REVIEW_REQUIRED"
            rows.append(
                {
                    "feature_a": spec_a.feature_name,
                    "timeframe_a": spec_a.timeframe,
                    "feature_b": spec_b.feature_name,
                    "timeframe_b": spec_b.timeframe,
                    "spearman_corr": float(value),
                    "abs_corr": abs_value,
                    "semantic_overlap": overlap,
                    "recommended_action": action,
                    "notes": f"selection={status_a}/{status_b}; correlation is evidence, not an automatic drop rule",
                }
            )
    return pd.DataFrame(rows).sort_values(["abs_corr", "feature_a", "feature_b"], ascending=[False, True, True])


def build_selected_matrix(join: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    selected = registry[registry.selection_status.isin({"PRIMARY", "SECONDARY", "CONDITIONAL"})]
    identity = ["sample_id", "ticker", "name", "reference_date", "weekly_stage_at_reference", "human_label"]
    columns = identity + [_source_column(next(spec for spec in SPECS if spec.feature_name == name)) for name in selected.feature_name]
    matrix = join[columns].copy()
    matrix.columns = identity + selected.feature_name.tolist()
    assert len(matrix) == 40
    assert matrix.sample_id.nunique() == 40
    assert not (matrix.human_label == "UNLABELED").any()
    return matrix


def build_architecture(registry: pd.DataFrame) -> dict:
    def entries(statuses: set[str], roles: set[str] | None = None) -> list[dict]:
        subset = registry[registry.selection_status.isin(statuses)]
        if roles is not None:
            subset = subset[subset.candidate_role.isin(roles)]
        return subset[["feature_name", "candidate_role", "selection_status", "next_phase_usage"]].to_dict("records")

    return {
        "version": "v0.1",
        "base_commit": BASE_COMMIT,
        "human_calibration_sha": HUMAN_CALIBRATION_SHA,
        "monthly_research_sha": MONTHLY_RESEARCH_SHA,
        "weekly_research_sha": WEEKLY_RESEARCH_SHA,
        "daily_research_sha": DAILY_RESEARCH_SHA,
        "architecture_status": "CANDIDATE_ARCHITECTURE_COMPLETE_ADVISOR_REVIEW_PENDING",
        "monthly_permission_features": entries({"PRIMARY", "SECONDARY"}, {"MONTHLY_PERMISSION"}),
        "weekly_core_features": entries({"PRIMARY", "SECONDARY"}, {"WEEKLY_CORE"}),
        "conditional_weekly_features": entries({"CONDITIONAL"}, {"CONDITIONAL_STRUCTURE"}),
        "daily_timing_features": entries({"PRIMARY", "SECONDARY"}, {"DAILY_TIMING_RISK"}),
        "diagnostic_features": entries({"DIAGNOSTIC"}),
        "hold_features": entries({"HOLD"}),
        "dropped_features": entries({"DROP"}),
        "redundancy_decisions": [
            {"pair": ["range_position_24m", "close_vs_ma24_pct"], "decision": "retain range position; drop close-vs-MA duplicate"},
            {"pair": ["wma52_slope_1w", "close_vs_dma200_pct"], "decision": "weekly owns trend; daily MA is diagnostic shadow"},
            {"pair": ["recent_5d_max_gap_abs_pct", "atr_14_pct"], "decision": "max-gap primary risk; ATR secondary breadth"},
        ],
        "missing_semantics": {
            "post_breakout_min_low_vs_level_pct_26w": "EVENT_NOT_OBSERVED is not BAD and is not imputed",
            "close_vs_wma200_pct": "INSUFFICIENT_HISTORY is not BAD and is not imputed",
        },
        "non_decisions": [
            "No numeric cutoff is selected.",
            "No feature weighting or formula is selected.",
            "No automated stage inference or trade signal is selected.",
            "Human trigger events are unchanged.",
        ],
        "next_phase": "13G-2 threshold / score / stage contract prototype remains separate and is not started here.",
    }


def main() -> None:
    for path in (MONTHLY_MATRIX, WEEKLY_MATRIX, DAILY_MATRIX, JOIN_MATRIX, MONTHLY_SUMMARY, WEEKLY_SUMMARY, DAILY_SUMMARY):
        if not path.exists():
            raise FileNotFoundError(path)
    # Keep stock codes as strings: selected-matrix identity must retain the
    # leading zeros present in the frozen calibration artifact.
    join = pd.read_csv(JOIN_MATRIX, dtype={"sample_id": "string", "ticker": "string"})
    registry = build_registry(join)
    redundancy = build_cross_timeframe_redundancy(join, registry)
    selected = build_selected_matrix(join, registry)
    architecture = build_architecture(registry)

    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(REGISTRY_PATH, index=False)
    redundancy.to_csv(REDUNDANCY_PATH, index=False)
    selected.to_csv(SELECTED_MATRIX_PATH, index=False)
    ARCHITECTURE_PATH.write_text(json.dumps(architecture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"registry: {REGISTRY_PATH} ({len(registry)} rows)")
    print(f"cross-timeframe redundancy: {REDUNDANCY_PATH} ({len(redundancy)} rows)")
    print(f"selected matrix: {SELECTED_MATRIX_PATH} ({len(selected)} rows)")
    print(f"architecture: {ARCHITECTURE_PATH}")
    print(f"selection counts: {registry.selection_status.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
