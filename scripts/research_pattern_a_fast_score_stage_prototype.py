#!/usr/bin/env python
"""Phase 13G-2 score/stage research prototype; frozen artifacts only."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE = "4fc5f9d11c23cd96703c5b066d5f60200fb41703"
R = Path("artifacts/pattern_a_fast/research")
REGISTRY, SELECTED, WEEKLY = (R / "pattern_a_fast_feature_role_registry_v01.csv", R / "pattern_a_fast_selected_feature_matrix_v01.csv", R / "weekly_trigger_feature_matrix_v01.csv")
OUT = {
    "thresholds": R / "pattern_a_fast_threshold_candidates_v01.csv",
    "score": R / "pattern_a_fast_score_prototype_v01.json",
    "stage": R / "pattern_a_fast_stage_prototype_v01.json",
    "calibration": R / "pattern_a_fast_calibration_score_prototype_v01.csv",
    "evaluation": R / "pattern_a_fast_stage_prototype_evaluation_v01.csv",
    "diagnostics": R / "pattern_a_fast_score_prototype_diagnostics_v01.csv",
}


def zone(value: float, cuts: list[tuple[float, float]], default: float) -> float:
    if pd.isna(value):
        return np.nan
    for upper, score in cuts:
        if value <= upper:
            return score
    return default


def monthly(row: pd.Series) -> tuple[str, float]:
    pos, down = row.range_position_24m, row.monthly_down_month_ratio_12m
    if pd.isna(pos) or pd.isna(down):
        return "UNAVAILABLE", np.nan
    pos_score = zone(pos, [(0.25, 35), (0.85, 85)], 40)
    down_score = zone(down, [(0.40, 85), (0.60, 60)], 35)
    state = "EARLY_REGIME" if pos <= 0.25 else "LATE_OR_EXTENDED_REGIME" if pos > 0.85 else "PERMITTED_REGIME"
    return state, round(0.70 * pos_score + 0.30 * down_score, 2)


def weekly(row: pd.Series) -> tuple[float, str]:
    values: list[tuple[float, float]] = []
    wma = row.close_vs_wma200_pct
    if not pd.isna(wma): values.append((zone(wma, [(-0.10, 30), (-0.02, 60)], 85), 0.30))
    values += [
        (zone(row.distance_to_prior_26w_high_pct, [(-0.25, 30), (-0.10, 60), (0.30, 85)], 60), 0.35),
        (zone(row.higher_weekly_low_count_13w, [(3, 30), (5, 60)], 85), 0.20),
        (zone(row.wma52_slope_1w, [(0.0, 35)], 70), 0.10),
        (zone(row.wma12_vs_wma26_pct, [(0.0, 40)], 70), 0.05),
    ]
    valid = [(score, weight) for score, weight in values if not pd.isna(score)]
    return round(sum(score * weight for score, weight in valid) / sum(weight for _, weight in valid), 2), "PARTIAL" if pd.isna(wma) else "READY"


def conditional(row: pd.Series) -> tuple[str, float]:
    value = row.post_breakout_min_low_vs_level_pct_26w
    if pd.isna(value): return "EVENT_NOT_OBSERVED", np.nan
    return "EVENT_OBSERVED", zone(value, [(-0.10, 25), (0.0, 55)], 80)


def daily_risk(row: pd.Series) -> tuple[str, float]:
    gap = zone(row.recent_5d_max_gap_abs_pct, [(0.03, 10), (0.07, 45)], 80)
    atr = zone(row.atr_14_pct, [(0.03, 10), (0.07, 45)], 80)
    risk = min(100.0, gap + 0.25 * atr)  # max-gap main, ATR capped confirmation
    return "NORMAL" if risk <= 25 else "ELEVATED" if risk <= 60 else "EXTREME", round(risk, 2)


def aggregate(monthly_score: float, weekly_score: float, breakout: float, risk: float) -> float:
    base = 0.70 * weekly_score + 0.30 * monthly_score
    refinement = 0.10 * (breakout - 50) if not pd.isna(breakout) else 0.0
    return round(float(np.clip(base + refinement - 0.15 * risk, 0, 100)), 2)


def score_contract() -> dict:
    """Serialize the exact executable mapping; this is not a new variant."""
    return {"version":"v0.1","base_commit":BASE,"architecture_sha":BASE,"prototype_status":"RESEARCH_PROTOTYPE_ADVISOR_REVIEW_PENDING","production_frozen":False,
        "implemented_prototypes":["HIERARCHICAL_V01"],"aggregate_formula_candidates":["HIERARCHICAL_V01"],"selected_research_prototype":"HIERARCHICAL_V01",
        "deferred_concepts":["WEEKLY_DOMINANT_SOFT_V01 was considered conceptually but was not implemented or evaluated."],
        "monthly_permission_mapping":{"range_position_24m":{"zones":[{"upper_bound":.25,"score":35},{"upper_bound":.85,"score":85},{"lower_bound":.85,"score":40}]},"monthly_down_month_ratio_12m":{"zones":[{"upper_bound":.40,"score":85},{"upper_bound":.60,"score":60},{"lower_bound":.60,"score":35}]},"component_formula":{"weights":{"range_position_24m":.70,"monthly_down_month_ratio_12m":.30},"expression":"0.70 * range_position_score + 0.30 * downside_ratio_score"}},
        "weekly_core_mapping":{"close_vs_wma200_pct":{"zones":[{"upper_bound":-.10,"score":30},{"upper_bound":-.02,"score":60},{"lower_bound":-.02,"score":85}],"weight":.30},"distance_to_prior_26w_high_pct":{"zones":[{"upper_bound":-.25,"score":30},{"upper_bound":-.10,"score":60},{"upper_bound":.30,"score":85},{"lower_bound":.30,"score":60}],"weight":.35},"higher_weekly_low_count_13w":{"zones":[{"upper_bound":3,"score":30},{"upper_bound":5,"score":60},{"lower_bound":5,"score":85}],"weight":.20},"wma52_slope_1w":{"zones":[{"upper_bound":0,"score":35},{"lower_bound":0,"score":70}],"weight":.10},"wma12_vs_wma26_pct":{"zones":[{"upper_bound":0,"score":40},{"lower_bound":0,"score":70}],"weight":.05},"missing":"WMA200 UNKNOWN removes its contribution; available weights are renormalized"},
        "conditional_breakout_mapping":{"post_breakout_min_low_vs_level_pct_26w":{"zones":[{"upper_bound":-.10,"score":25},{"upper_bound":0,"score":55},{"lower_bound":0,"score":80}]},"EVENT_NOT_OBSERVED":{"status":"NOT_APPLICABLE","refinement":0}},
        "daily_risk_mapping":{"recent_5d_max_gap_abs_pct":{"zones":[{"upper_bound":.03,"risk":10},{"upper_bound":.07,"risk":45},{"lower_bound":.07,"risk":80}]},"atr_14_pct":{"zones":[{"upper_bound":.03,"risk":10},{"upper_bound":.07,"risk":45},{"lower_bound":.07,"risk":80}]},"formula":"min(100, max_gap_risk + 0.25 * atr_risk)"},
        "aggregate_formula":{"prototype_id":"HIERARCHICAL_V01","base":"0.70 * weekly_core_score + 0.30 * monthly_permission_score","conditional_refinement":"0.10 * (conditional_breakout_quality - 50) when event observed else 0","final":"clip(base + conditional_refinement - 0.15 * daily_timing_risk, 0, 100)"},
        "score_status_semantics":{"READY":"all expected direct inputs available","PARTIAL":"WMA200 UNKNOWN; weekly weights renormalized","UNAVAILABLE":"unexpected Monthly primary missing"},"non_decisions":["No optimization","No production score","No trade signal"]}


def stage_contract() -> dict:
    return {"version":"v0.1","production_frozen":False,"weekly_only":True,"score_input":False,"monthly_input":False,"daily_input":False,"previous_stage_input":False,
        "stage_semantics":["WATCH","SETUP","TRIGGER","TREND","EXTENDED"],"evaluation_order":["EXTENDED","TRIGGER","TREND","SETUP","WATCH"],
        "weekly_feature_inputs":["close_vs_wma200_pct","distance_to_prior_26w_high_pct","higher_weekly_low_count_13w","wma52_slope_1w","wma12_vs_wma26_pct"],"stage_only_semantic_markers":["weeks_since_26w_close_breakout"],
        "extended_rule_candidate":{"close_vs_wma200_pct":{"operator":">","value":.50},"any_of":[{"wma52_slope_1w":{"operator":">","value":.01}},{"wma12_vs_wma26_pct":{"operator":">","value":.10}}]},
        "ready_structure_candidate":{"distance_to_prior_26w_high_pct":{"operator":">=","value":-.10},"higher_weekly_low_count_13w":{"operator":">=","value":5},"close_vs_wma200_pct":"UNKNOWN_OR_>=_-0.10"},
        "trigger_rule_candidate":{"requires":"ready_structure_candidate","weeks_since_26w_close_breakout":{"observed":True,"operator":"<=","value":12}},
        "trend_rule_candidate":{"distance_to_prior_26w_high_pct":{"operator":">=","value":-.10},"higher_weekly_low_count_13w":{"operator":">=","value":6},"any_of":[{"wma52_slope_1w":{"operator":">","value":0}},{"wma12_vs_wma26_pct":{"operator":">","value":0}}]},
        "setup_rule_candidate":{"higher_weekly_low_count_13w":{"operator":">=","value":5},"any_of":[{"distance_to_prior_26w_high_pct":{"operator":">=","value":-.25}},{"wma52_slope_1w":{"operator":">","value":0}},{"wma12_vs_wma26_pct":{"operator":">","value":0}}]},"watch_rule_candidate":"fallback when no higher-priority rule matches","snapshot_independence":True,"human_trigger_event_policy":"not used as input and never backfilled","missing_behavior":"WMA200 UNKNOWN is not automatic WATCH"}


def stage(row: pd.Series) -> str:
    """Weekly-only current-snapshot lifecycle; never reads score or human fields."""
    wma, distance, lows = row.close_vs_wma200_pct, row.distance_to_prior_26w_high_pct, row.higher_weekly_low_count_13w
    slope, align, age = row.wma52_slope_1w, row.wma12_vs_wma26_pct, row.weeks_since_26w_close_breakout
    if wma > 0.50 and (slope > 0.01 or align > 0.10): return "EXTENDED"
    ready = distance >= -0.10 and lows >= 5 and (pd.isna(wma) or wma >= -0.10)
    if ready and not pd.isna(age) and age <= 12: return "TRIGGER"
    if distance >= -0.10 and lows >= 6 and (slope > 0 or align > 0): return "TREND"
    if lows >= 5 and (distance >= -0.25 or slope > 0 or align > 0): return "SETUP"
    return "WATCH"


def candidates() -> pd.DataFrame:
    rows = []
    def add(component, timeframe, feature, ident, typ, direction, lo, hi, state, provenance, missing):
        rows.append(dict(component=component,timeframe=timeframe,feature_name=feature,candidate_id=ident,candidate_type=typ,direction=direction,lower_bound=lo,upper_bound=hi,boundary_inclusive="YES",semantic_state=state,provenance=provenance,calibration_evidence="bounded rounded candidate; not optimized",case_study_evidence="critical-pair review",known_counterexample="small in-sample calibration",missing_behavior=missing,selected_for_prototype="YES",production_frozen="NO"))
    for f, vals in [("range_position_24m", [(None,.25,"EARLY_REGIME"),(.25,.85,"PERMITTED_REGIME"),(.85,None,"LATE_OR_EXTENDED_REGIME")]), ("monthly_down_month_ratio_12m", [(None,.40,"IMPROVING"),(.40,.60,"NEUTRAL"),(.60,None,"HEAVY_DOWNSIDE")])]:
        for i,(lo,hi,state_name) in enumerate(vals): add("monthly_permission","MONTHLY",f,f"{f}_{i+1}","ZONE","NON_MONOTONIC" if f.startswith("range") else "LOWER_IS_BETTER",lo,hi,state_name,"ROUNDED_CALIBRATION_GAP","UNAVAILABLE")
    for f, vals, direction in [("close_vs_wma200_pct",[-.10,-.02],"HIGHER_IS_BETTER"),("distance_to_prior_26w_high_pct",[-.25,-.10,.30],"SWEET_SPOT"),("higher_weekly_low_count_13w",[3,5],"HIGHER_IS_BETTER"),("recent_5d_max_gap_abs_pct",[.03,.07],"LOWER_IS_LOWER_RISK"),("atr_14_pct",[.03,.07],"LOWER_IS_LOWER_RISK")]:
        for i, cut in enumerate(vals): add("weekly_core" if f.startswith(("close","distance","higher")) else "daily_risk","WEEKLY" if f.startswith(("close","distance","higher")) else "DAILY",f,f"{f}_{i+1}","BOUNDARY",direction,None,cut,"CANDIDATE","ROUNDED_CALIBRATION_GAP","UNKNOWN")
    for f in ("wma52_slope_1w","wma12_vs_wma26_pct","post_breakout_min_low_vs_level_pct_26w"):
        add("weekly_secondary" if f.startswith("wma") else "conditional_breakout","WEEKLY",f,f"{f}_zero","STRUCTURAL_ZERO","POSITIVE_IS_CONSTRUCTIVE",None,0.0,"CANDIDATE","STRUCTURAL_ZERO","EVENT_NOT_OBSERVED" if f.startswith("post") else "UNKNOWN")
    return pd.DataFrame(rows)


def cliffs(x, y):
    x, y = list(pd.Series(x).dropna()), list(pd.Series(y).dropna())
    if len(x) < 2 or len(y) < 2: return np.nan
    return (sum(a>b for a,b in itertools.product(x,y))-sum(a<b for a,b in itertools.product(x,y)))/(len(x)*len(y))


def main() -> None:
    registry, selected, weekly_raw = pd.read_csv(REGISTRY), pd.read_csv(SELECTED, dtype={"ticker":str}), pd.read_csv(WEEKLY)
    assert len(registry)==21 and len(selected)==40 and selected.sample_id.nunique()==40
    markers = weekly_raw[["sample_id","weeks_since_26w_close_breakout"]]
    data = selected.merge(markers,on="sample_id",how="left",validate="one_to_one")
    output=[]
    for _, row in data.iterrows():
        mstate, mscore = monthly(row); wscore, wstatus = weekly(row); cstatus, cscore = conditional(row); rstate, risk = daily_risk(row)
        output.append({**row[["sample_id","ticker","name","reference_date","weekly_stage_at_reference","human_label"]].to_dict(),"monthly_permission_state_proto":mstate,"monthly_permission_score_proto":mscore,"weekly_core_score_proto":wscore,"conditional_breakout_status":cstatus,"conditional_breakout_quality_proto":cscore,"daily_timing_risk_state_proto":rstate,"daily_timing_risk_proto":risk,"pattern_a_fast_score_proto":aggregate(mscore,wscore,cscore,risk),"score_status":"UNAVAILABLE" if pd.isna(mscore) else wstatus,"machine_stage_proto":stage(row),"diagnostic_mismatch_reason":"DESCRIPTIVE_ONLY"})
    calibration=pd.DataFrame(output); calibration.to_csv(OUT["calibration"],index=False)
    candidates().to_csv(OUT["thresholds"],index=False)
    evaluation=calibration.groupby(["weekly_stage_at_reference","machine_stage_proto"]).size().reset_index(name="count").rename(columns={"weekly_stage_at_reference":"human_stage"}); evaluation.to_csv(OUT["evaluation"],index=False)
    diag=[]
    for left,right in [("GOOD_TRIGGER","NO_SETUP"),("GOOD_TRIGGER","TOO_EARLY"),("GOOD_TRIGGER","FALSE_TRIGGER"),("GOOD_TRIGGER","TOO_EXTENDED")]:
        a,b=calibration.query("human_label == @left").pattern_a_fast_score_proto,calibration.query("human_label == @right").pattern_a_fast_score_proto
        diag.append(dict(prototype_id="HIERARCHICAL_V01",comparison=f"{left}_vs_{right}",n_left=len(a),n_right=len(b),median_left=a.median(),median_right=b.median(),median_diff=a.median()-b.median(),cliffs_delta=cliffs(a,b)))
    pd.DataFrame(diag).to_csv(OUT["diagnostics"],index=False)
    OUT["score"].write_text(json.dumps(score_contract(),ensure_ascii=False,indent=2)+"\n"); OUT["stage"].write_text(json.dumps(stage_contract(),ensure_ascii=False,indent=2)+"\n")
    print(f"wrote {len(calibration)} calibration rows; stage={calibration.machine_stage_proto.value_counts().to_dict()}")

if __name__ == "__main__": main()
