#!/usr/bin/env python
"""Phase 13J-4 frozen Investable OOS-B evaluation (local cache only)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scripts.research_pattern_a_fast_lead_time_failure import _semantic_true, evaluate_fast_contract
except ModuleNotFoundError:  # pragma: no cover
    from research_pattern_a_fast_lead_time_failure import _semantic_true, evaluate_fast_contract
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features
from trend_scanner.validation.historical_snapshot import build_historical_snapshot


ROOT = Path(__file__).resolve().parents[1]
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
PASS_A_SEAL = OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json"
GROUND_TRUTH_SEAL = OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json"
SCORE_CONTRACT = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"
OUT_JSON = OOS / "pattern_a_fast_investable_oos_evaluation_v01.json"
OUT_SAMPLES = OOS / "pattern_a_fast_investable_oos_evaluation_samples_v01.csv"
OUT_PAIRS = OOS / "pattern_a_fast_investable_oos_evaluation_event_pairs_v01.csv"
DOC = ROOT / "docs/patterns/pattern_a_fast/validation/investable_oos_evaluation_v01.md"

BASE_SHA = "753f7601078aad46e3f3329887e3a9c60203bea7"
FAST_CONTRACT_SHA = "2da3fc36744b27ec13edae3f690df72c796906e5"
PATTERN_A_FROZEN_SHA = "05d03e16501adbca889488294aaaaa0bd84005de"
FROZEN_SELECTION_SHA = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_ASSET_SHA = "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe"
FROZEN_PROTOCOL_SHA = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
FROZEN_PASS_A_SHA = "4c908daa5ab803ccbf20f355027391aaa3f2d63c31e3f60ac60df6e34b9201ea"
FROZEN_REVIEW_SHA = "c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585"
FROZEN_GROUND_TRUTH_SEAL_SHA = "c626759b046e4a1bc223685c41c3e9744e5fb989c28dbccdf91f8f3794852689"
FROZEN_MAPPING_SHA = "6d861d3b86f9c1e0fa4e7e48c1d59c385c3e089c05608fd45151536ab5c6b40b"
STAGES = ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
ORDER = {stage: number for number, stage in enumerate(STAGES)}
OUTCOMES = ["GOOD_TRIGGER", "BORDERLINE_TRIGGER", "FALSE_TRIGGER", "TOO_EARLY", "TOO_LATE", "TOO_EXTENDED", "NO_SETUP"]
PAIRING_PRECEDENCE = ["DATA_UNAVAILABLE", "SAME_WEEK", "PATTERN_A_ALREADY_ACTIVE", "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", "FAST_EARLIER_PATTERN_A_LATER", "FAST_EVENT_NO_PATTERN_A_CATCHUP"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def mapping_sha256(review: pd.DataFrame) -> str:
    rows = review[["review_order", "sample_id"]].sort_values("review_order", kind="mergesort")
    payload = "\n".join(f"{int(row.review_order)}|{row.sample_id}" for row in rows.itertuples(index=False))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def score_stats(values: pd.Series) -> dict:
    usable = values.dropna().astype(float)
    return {"n": int(len(usable)), "median": number(usable.median()), "mean": number(usable.mean()),
            "q1": number(usable.quantile(.25)), "q3": number(usable.quantile(.75)),
            "iqr": number(usable.quantile(.75) - usable.quantile(.25)),
            "min": number(usable.min()), "max": number(usable.max())}


def assert_frozen_input_hashes() -> None:
    """Verify every byte-frozen input before model evaluation or output write."""
    expected_hashes = {REVIEW: FROZEN_REVIEW_SHA, MANIFEST: FROZEN_SELECTION_SHA, ASSETS: FROZEN_ASSET_SHA,
                       PROTOCOL: FROZEN_PROTOCOL_SHA, PASS_A_SEAL: FROZEN_PASS_A_SHA}
    for path, expected in expected_hashes.items():
        if sha256(path) != expected:
            raise RuntimeError(f"FROZEN_INPUT_HASH_MISMATCH: {path.name}")
    if sha256(GROUND_TRUTH_SEAL) != FROZEN_GROUND_TRUTH_SEAL_SHA:
        raise RuntimeError("GROUND_TRUTH_SEAL_HASH_MISMATCH")


def load_inputs() -> tuple[pd.DataFrame, dict, dict, dict]:
    """Fail closed before computing any machine value or writing any output."""
    assert_frozen_input_hashes()
    review = pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)
    manifest = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    assets = pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    ground_truth = json.loads(GROUND_TRUTH_SEAL.read_text(encoding="utf-8"))
    if ground_truth["post_pass_b_human_review_sha256"] != FROZEN_REVIEW_SHA or ground_truth["pass_a_freeze_seal_sha256"] != FROZEN_PASS_A_SHA:
        raise RuntimeError("GROUND_TRUTH_SEAL_INTEGRITY_FAIL")
    if ground_truth["status"] != "HUMAN_OUTCOME_PASS_B_GROUND_TRUTH_FROZEN" or ground_truth["sample_mutation"] or ground_truth["pass_a_stage_mutation"]:
        raise RuntimeError("GROUND_TRUTH_SEAL_STATE_FAIL")
    if len(review) != 36 or mapping_sha256(review) != FROZEN_MAPPING_SHA:
        raise RuntimeError("REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    if Counter(review.human_stage) != Counter({"WATCH": 16, "SETUP": 14, "TREND": 3, "EXTENDED": 3}):
        raise RuntimeError("PASS_A_STAGE_DISTRIBUTION_FAIL")
    if Counter(review.human_outcome_label) != Counter({"GOOD_TRIGGER": 5, "BORDERLINE_TRIGGER": 7, "FALSE_TRIGGER": 5, "TOO_EARLY": 8, "TOO_LATE": 2, "TOO_EXTENDED": 3, "NO_SETUP": 6}):
        raise RuntimeError("PASS_B_OUTCOME_DISTRIBUTION_FAIL")
    if not review.stage_review_status.eq("COMPLETE").all() or not review.outcome_review_status.eq("COMPLETE").all():
        raise RuntimeError("GROUND_TRUTH_NOT_COMPLETE")
    identity = ["sample_id", "ticker", "name", "historical_market"]
    merged = review.merge(manifest, on=identity, validate="one_to_one", suffixes=("", "_manifest"))
    if len(merged) != 36 or not (merged.reference_date == merged.completed_weekly_reference_date).all():
        raise RuntimeError("SELECTION_IDENTITY_FREEZE_INTEGRITY_FAIL")
    # The manifest has four blinded assets per reviewed sample.  Identity is
    # therefore checked after reducing that fixed asset bundle to one mapping.
    mapping = assets[["review_order", "sample_id"]].drop_duplicates().copy()
    mapping.review_order = mapping.review_order.astype(int)
    if not mapping.sort_values("review_order").reset_index(drop=True).equals(review[["review_order", "sample_id"]].astype({"review_order": int}).sort_values("review_order").reset_index(drop=True)):
        raise RuntimeError("BLIND_ASSET_MAPPING_FREEZE_INTEGRITY_FAIL")
    if protocol["fast_contract"] != "HIERARCHICAL_V01" or protocol["fast_contract_sha"] != FAST_CONTRACT_SHA or protocol["pattern_a_frozen_sha"] != PATTERN_A_FROZEN_SHA:
        raise RuntimeError("FROZEN_MODEL_PROTOCOL_MISMATCH")
    if protocol["stage_order"] != STAGES or protocol["lead_precedence"] != PAIRING_PRECEDENCE:
        raise RuntimeError("FROZEN_PROTOCOL_SEMANTICS_MISMATCH")
    score = json.loads(SCORE_CONTRACT.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT.read_text(encoding="utf-8"))
    if score["selected_research_prototype"] != "HIERARCHICAL_V01" or stage["stage_semantics"] != STAGES:
        raise RuntimeError("FROZEN_FAST_CONTRACT_MISMATCH")
    return merged.sort_values("review_order", kind="mergesort").reset_index(drop=True), protocol, score, stage


def point(ticker: str, name: str, daily: pd.DataFrame, weekly_date: pd.Timestamp, score: dict, stage: dict) -> dict:
    """A strict point-in-time evaluation: source bars are cut at weekly_date."""
    visible = daily[daily.index <= weekly_date].copy()
    snapshot = build_historical_snapshot(ticker, name, visible, weekly_date, include_incomplete_periods=False)
    if snapshot.weekly_as_of != weekly_date or snapshot.effective_as_of > weekly_date:
        raise RuntimeError(f"PIT_SNAPSHOT_AS_OF_FAIL: {ticker} {weekly_date.date()}")
    features: dict = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(visible))
    fast = evaluate_fast_contract(features, score, stage)
    pattern = evaluate_pattern_a(snapshot)
    pattern_ready = pattern.score is not None and pattern.stage is not None
    monthly_ready = not any(pd.isna(features.get(key, np.nan)) for key in ("range_position_24m", "monthly_down_month_ratio_12m"))
    daily_ready = not any(pd.isna(features.get(key, np.nan)) for key in ("recent_5d_max_gap_abs_pct", "atr_14_pct"))
    return {**fast,
            "monthly_component_status": "READY" if monthly_ready else "UNAVAILABLE",
            "weekly_component_status": fast["fast_score_status"] if not pd.isna(fast["fast_weekly_core_score"]) else "UNAVAILABLE",
            "daily_component_status": "READY" if daily_ready else "UNAVAILABLE",
            "conditional_breakout_status": fast["fast_conditional_status"],
            "wma200_status": "UNKNOWN" if pd.isna(features.get("close_vs_wma200_pct", np.nan)) else "READY",
            "pattern_a_evaluation_status": "READY" if pattern_ready else "UNAVAILABLE",
            "pattern_a_score": number(pattern.score), "pattern_a_stage": pattern.stage.value if pattern.stage else "",
            "pattern_a_candidate_active": _semantic_true(pattern.candidate_state.value == "candidate") if pattern_ready else np.nan,
            "effective_as_of": snapshot.effective_as_of.strftime("%Y-%m-%d"),
            "monthly_as_of": snapshot.monthly_as_of.strftime("%Y-%m-%d") if snapshot.monthly_as_of is not None else "",
            "weekly_as_of": snapshot.weekly_as_of.strftime("%Y-%m-%d") if snapshot.weekly_as_of is not None else ""}


def annotate(timeline: pd.DataFrame) -> pd.DataFrame:
    out = timeline.copy()
    out["fast_trigger_event_status"] = "NOT_OBSERVED"
    out["pattern_a_candidate_event_status"] = "NOT_OBSERVED"
    previous_fast: str | None = None
    previous_pattern: bool | None = None
    for index, row in out.iterrows():
        ready, fast_stage = row.fast_machine_stage_status == "READY", row.fast_machine_stage
        if ready and fast_stage == "TRIGGER":
            out.at[index, "fast_trigger_event_status"] = "LEFT_CENSORED" if previous_fast is None else "OBSERVED" if previous_fast != "TRIGGER" else "NOT_OBSERVED"
        previous_fast = fast_stage if ready else None
        pattern_ready = row.pattern_a_evaluation_status == "READY"
        active = _semantic_true(row.pattern_a_candidate_active)
        if active:
            out.at[index, "pattern_a_candidate_event_status"] = "LEFT_CENSORED" if previous_pattern is None else "OBSERVED" if previous_pattern is False else "NOT_OBSERVED"
        previous_pattern = active if pattern_ready else None
    return out


def sample_timeline(sample: pd.Series, score: dict, stage: dict, cache: ParquetCache) -> pd.DataFrame:
    daily = cache.load(sample.ticker)
    if daily is None or daily.empty:
        raise RuntimeError(f"CACHE_MISSING_NO_SUBSTITUTION: {sample.ticker}")
    daily = daily.sort_index()
    reference, end = pd.Timestamp(sample.reference_date), pd.Timestamp(sample.outcome_review_end)
    rows = []
    for weekly_date in to_weekly(daily[daily.index <= end]).index:
        if weekly_date < reference - pd.Timedelta(weeks=104) or weekly_date > end:
            continue
        if daily[daily.index <= weekly_date].index.max().normalize() != weekly_date.normalize():
            continue
        rows.append({"sample_id": sample.sample_id, "ticker": sample.ticker, "name": sample["name"], "weekly_date": weekly_date.strftime("%Y-%m-%d"),
                     **point(sample.ticker, sample["name"], daily, weekly_date, score, stage)})
    timeline = pd.DataFrame(rows).sort_values("weekly_date").reset_index(drop=True)
    if timeline.empty:
        raise RuntimeError(f"NO_COMPLETED_WEEKLY_TIMELINE: {sample.sample_id}")
    return annotate(timeline)


def pair_events(timeline: pd.DataFrame, sample: pd.Series) -> pd.DataFrame:
    rows = []
    observed = timeline[(timeline.fast_trigger_event_status == "OBSERVED") & (pd.to_datetime(timeline.weekly_date) >= pd.Timestamp(sample.reference_date))]
    candidate_events = timeline[timeline.pattern_a_candidate_event_status == "OBSERVED"]
    for sequence, (_, event) in enumerate(observed.iterrows(), 1):
        event_date = pd.Timestamp(event.weekly_date)
        pattern_ready = event.pattern_a_evaluation_status == "READY"
        same = candidate_events[candidate_events.weekly_date == event.weekly_date]
        prior_activity = timeline[(pd.to_datetime(timeline.weekly_date) < event_date) & (timeline.pattern_a_evaluation_status == "READY") & timeline.pattern_a_candidate_active.map(_semantic_true)]
        prior = candidate_events[pd.to_datetime(candidate_events.weekly_date) < event_date]
        future = candidate_events[pd.to_datetime(candidate_events.weekly_date) > event_date]
        if not pattern_ready:
            status, next_date = "DATA_UNAVAILABLE", ""
        elif not same.empty:
            status, next_date = "SAME_WEEK", event.weekly_date
        elif _semantic_true(event.pattern_a_candidate_active):
            status, next_date = "PATTERN_A_ALREADY_ACTIVE", ""
        elif not prior_activity.empty:
            status, next_date = "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", ""
        elif not future.empty:
            status, next_date = "FAST_EARLIER_PATTERN_A_LATER", future.iloc[0].weekly_date
        else:
            status, next_date = "FAST_EVENT_NO_PATTERN_A_CATCHUP", ""
        lead_weeks = (pd.Timestamp(next_date) - event_date).days / 7 if status in {"SAME_WEEK", "FAST_EARLIER_PATTERN_A_LATER"} else np.nan
        rows.append({"sample_id": sample.sample_id, "ticker": sample.ticker, "name": sample["name"], "reference_date": sample.reference_date,
                     "outcome_review_end": sample.outcome_review_end, "fast_trigger_event_sequence": sequence,
                     "fast_trigger_event_date": event.weekly_date, "fast_score_at_event": number(event.fast_score),
                     "pattern_a_status_at_fast_event": event.pattern_a_evaluation_status,
                     "pattern_a_active_at_fast_event": event.pattern_a_candidate_active if pattern_ready else "",
                     "pattern_a_prior_active_date": prior_activity.iloc[-1].weekly_date if not prior_activity.empty else "",
                     "pattern_a_prior_candidate_event_date": prior.iloc[-1].weekly_date if not prior.empty else "",
                     "pattern_a_next_candidate_event_date": next_date, "pair_status": status, "lead_weeks": lead_weeks,
                     "censor_status": "DATA_UNAVAILABLE" if status == "DATA_UNAVAILABLE" else "RIGHT_CENSORED" if status == "FAST_EVENT_NO_PATTERN_A_CATCHUP" else "NOT_CENSORED"})
    return pd.DataFrame(rows)


def build_outputs(samples: pd.DataFrame, protocol: dict, score: dict, stage: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cache, sample_rows, pair_frames = ParquetCache(), [], []
    for _, sample in samples.iterrows():
        timeline = sample_timeline(sample, score, stage, cache)
        reference = timeline[timeline.weekly_date == sample.reference_date]
        if len(reference) != 1:
            raise RuntimeError(f"REFERENCE_NOT_COMPLETED_OR_NONUNIQUE: {sample.sample_id}")
        value = reference.iloc[0]
        machine_stage = value.fast_machine_stage if value.fast_machine_stage_status == "READY" else ""
        delta = ORDER[machine_stage] - ORDER[sample.human_stage] if machine_stage else np.nan
        call = "UNAVAILABLE" if not machine_stage else "EXACT" if delta == 0 else "OVER_CALL" if delta > 0 else "UNDER_CALL"
        pairs = pair_events(timeline, sample)
        pair_frames.append(pairs)
        first = pairs.iloc[0] if not pairs.empty else None
        sample_rows.append({"review_order": int(sample.review_order), "sample_id": sample.sample_id, "ticker": sample.ticker, "name": sample["name"],
                            "reference_date": sample.reference_date, "outcome_review_end": sample.outcome_review_end,
                            "human_stage": sample.human_stage, "human_stage_confidence": sample.human_stage_confidence,
                            "human_outcome_label": sample.human_outcome_label, "human_outcome_confidence": sample.human_outcome_confidence,
                            "machine_stage_status": value.fast_machine_stage_status, "machine_stage": machine_stage,
                            "machine_score_status": value.fast_score_status, "machine_score": number(value.fast_score),
                            "monthly_state": value.fast_monthly_permission_state, "weekly_core_score": number(value.fast_weekly_core_score),
                            "daily_risk_state": value.fast_daily_risk_state, "monthly_component_status": value.monthly_component_status,
                            "weekly_component_status": value.weekly_component_status, "daily_component_status": value.daily_component_status,
                            "conditional_breakout_status": value.conditional_breakout_status, "wma200_status": value.wma200_status,
                            "pattern_a_evaluation_status": value.pattern_a_evaluation_status, "pattern_a_score": number(value.pattern_a_score),
                            "pattern_a_stage": value.pattern_a_stage, "pattern_a_candidate_active": value.pattern_a_candidate_active,
                            "effective_as_of": value.effective_as_of, "monthly_as_of": value.monthly_as_of, "weekly_as_of": value.weekly_as_of,
                            "stage_delta": number(delta), "stage_call_type": call,
                            "fast_event_status": "OBSERVED" if first is not None else "NOT_OBSERVED",
                            "first_fast_event_date": first.fast_trigger_event_date if first is not None else "",
                            "first_pair_status": first.pair_status if first is not None else ""})
    snapshot = pd.DataFrame(sample_rows).sort_values("review_order").reset_index(drop=True)
    pairs = pd.concat(pair_frames, ignore_index=True) if any(not item.empty for item in pair_frames) else pd.DataFrame(columns=["sample_id", "pair_status", "lead_weeks"])
    primary = protocol["primary_score_comparison"]
    usable = snapshot[snapshot.machine_score_status.isin(["READY", "PARTIAL"])]
    groups = {label: score_stats(usable.loc[usable.human_outcome_label == label, "machine_score"]) for label in OUTCOMES}
    positive = usable[usable.human_outcome_label.isin(primary["positive_labels"])].machine_score
    negative = usable[usable.human_outcome_label.isin(primary["negative_labels"])].machine_score
    pos_stats, neg_stats = score_stats(positive), score_stats(negative)
    min_n = primary["minimum_n_per_group"]
    if min(pos_stats["n"], neg_stats["n"]) < min_n:
        primary_status, reason = "INCONCLUSIVE", "INSUFFICIENT_SCORE_AVAILABLE_SAMPLE_SIZE"
    elif positive.median() <= negative.median():
        primary_status, reason = "OOS_SCORE_DIRECTION_FAIL", "PREREGISTERED_DIRECTION_GATE"
    else:
        primary_status, reason = "PASS", "PREREGISTERED_DIRECTION_GATE"
    stage_ready = snapshot.machine_stage_status.eq("READY")
    score_unavailable = snapshot.machine_score_status.eq("UNAVAILABLE")
    lead = pairs.loc[pairs.pair_status.eq("FAST_EARLIER_PATTERN_A_LATER"), "lead_weeks"] if not pairs.empty else pd.Series(dtype=float)
    lead_stats = score_stats(lead)
    lead_status = "INCONCLUSIVE" if lead_stats["n"] < protocol["lead_minimum_clean_n"] else "FAIL" if lead_stats["median"] <= 0 else "PASS"
    availability = {"stage_ready_count": int(stage_ready.sum()), "stage_ready_rate": float(stage_ready.mean()),
                    "score_unavailable_count": int(score_unavailable.sum()), "score_unavailable_rate": float(score_unavailable.mean()),
                    "status": "PASS" if stage_ready.mean() >= protocol["stage_ready_coverage_minimum"] and score_unavailable.mean() <= protocol["score_unavailable_rate_maximum"] else "FAIL"}
    exact = int((snapshot.stage_call_type == "EXACT").sum())
    hard_failures = []
    if availability["status"] == "FAIL": hard_failures.append("OOS_DATA_COVERAGE_FAIL")
    if primary_status == "OOS_SCORE_DIRECTION_FAIL": hard_failures.append(primary_status)
    if lead_status == "FAIL": hard_failures.append("OOS_LEAD_DIRECTION_FAIL")
    summary = {"version": "PATTERN_A_FAST_INVESTABLE_OOS_B_EVALUATION_V01", "phase": "13J-4", "base_sha": BASE_SHA,
               "network_market_request_count": 0, "retuning_performed": False, "production_frozen": False,
               "frozen_inputs": {"human_review_sha256": sha256(REVIEW), "ground_truth_seal_sha256": sha256(GROUND_TRUTH_SEAL),
                                  "pass_a_seal_sha256": sha256(PASS_A_SEAL), "selection_manifest_sha256": sha256(MANIFEST),
                                  "blind_asset_manifest_sha256": sha256(ASSETS), "evaluation_protocol_sha256": sha256(PROTOCOL),
                                  "review_order_sample_mapping_sha256": mapping_sha256(pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False))},
               "fast_contract": "HIERARCHICAL_V01", "fast_contract_sha": FAST_CONTRACT_SHA, "pattern_a_frozen_sha": PATTERN_A_FROZEN_SHA,
               "sample_count": 36, "human_outcome_distribution": {label: int((snapshot.human_outcome_label == label).sum()) for label in OUTCOMES},
               "availability": availability,
               "stage_comparison": {"human_distribution": {label: int((snapshot.human_stage == label).sum()) for label in STAGES},
                                    "machine_distribution": {label: int((snapshot.machine_stage == label).sum()) for label in STAGES},
                                    "exact_match_count": exact, "exact_match_rate": exact / int(stage_ready.sum()) if stage_ready.any() else None,
                                    "over_call_count": int((snapshot.stage_call_type == "OVER_CALL").sum()), "under_call_count": int((snapshot.stage_call_type == "UNDER_CALL").sum())},
               "primary_score_comparison": {"positive_labels": primary["positive_labels"], "negative_labels": primary["negative_labels"],
                                            "minimum_n_per_group": min_n, "positive": pos_stats, "early_or_none": neg_stats,
                                            "median_difference": number(positive.median() - negative.median()), "status": primary_status, "reason": reason},
               "descriptive_score_by_outcome": groups,
               "too_early_analysis": {"human_n": int((snapshot.human_outcome_label == "TOO_EARLY").sum()),
                                      "monthly_state_distribution": snapshot.loc[snapshot.human_outcome_label == "TOO_EARLY", "monthly_state"].value_counts().to_dict(),
                                      "daily_risk_distribution": snapshot.loc[snapshot.human_outcome_label == "TOO_EARLY", "daily_risk_state"].value_counts().to_dict(),
                                      "weekly_component_status_distribution": snapshot.loc[snapshot.human_outcome_label == "TOO_EARLY", "weekly_component_status"].value_counts().to_dict()},
               "good_vs_borderline": {"GOOD_TRIGGER": groups["GOOD_TRIGGER"], "BORDERLINE_TRIGGER": groups["BORDERLINE_TRIGGER"]},
               "event_pairing": {"fast_trigger_event_count": int(len(pairs)), "pair_status_distribution": {status: int((pairs.pair_status == status).sum()) if not pairs.empty else 0 for status in PAIRING_PRECEDENCE},
                                 "clean_lead": {**lead_stats, "status": lead_status}},
               "hard_failures": hard_failures, "hard_failure_count": len(hard_failures),
               "historical_coverage_limitation": "Local cache is approximately 20 trading years; early 2020 through 2021-H1 history can be insufficient. The frozen 36-sample OOS-B population was not replaced.",
               "overall_oos_b_status": "FAIL" if hard_failures else "INCONCLUSIVE" if primary_status == "INCONCLUSIVE" or lead_status == "INCONCLUSIVE" else "PASS"}
    return snapshot, pairs, summary


def write_document(summary: dict) -> None:
    primary, availability, stage, event = summary["primary_score_comparison"], summary["availability"], summary["stage_comparison"], summary["event_pairing"]
    DOC.write_text(f'''pattern_a_fast_investable_oos_evaluation_v01.md
==================================================
Phase 13J-4 Frozen Investable OOS-B Evaluation
==================================================

1. Scope and integrity
Base commit: {BASE_SHA}
Population: 36 frozen Investable OOS-B samples. HIERARCHICAL_V01 and frozen Pattern A were evaluated with local cached OHLCV only; network market requests=0 and retuning=false.
Human review SHA-256: {summary["frozen_inputs"]["human_review_sha256"]}
Ground-truth seal SHA-256: {summary["frozen_inputs"]["ground_truth_seal_sha256"]}
The evaluator hard-gates the human review, PASS A seal, selection manifest, blind asset manifest, protocol, and review-order mapping before it computes an output. No label, sample, chart, model, or frozen seal was changed.

2. Point-in-time method
At every weekly point, the source daily bars are explicitly truncated at that weekly date before historical snapshot construction. `effective_as_of` must not exceed that date. Fast trigger events are observed only from the frozen reference date; the preceding 104 weeks are used solely to determine prior Pattern A activity. Pairing follows the frozen precedence without new rules.

3. Availability
Stage READY: {availability["stage_ready_count"]}/36 ({availability["stage_ready_rate"]:.1%}). Score UNAVAILABLE: {availability["score_unavailable_count"]}/36 ({availability["score_unavailable_rate"]:.1%}). Preregistered availability status: {availability["status"]}.

4. Human outcome and primary score comparison
Outcome distribution: {summary["human_outcome_distribution"]}.
POSITIVE_STRUCTURE (GOOD_TRIGGER+BORDERLINE_TRIGGER): score n={primary["positive"]["n"]}, median={primary["positive"]["median"]}. EARLY_OR_NONE (TOO_EARLY+NO_SETUP): score n={primary["early_or_none"]["n"]}, median={primary["early_or_none"]["median"]}. Minimum group n={primary["minimum_n_per_group"]}. Primary status: {primary["status"]} ({primary["reason"]}). Other outcome groups and GOOD-vs-BORDERLINE are descriptive only in the JSON artifact.

5. Stage comparison
Exact match: {stage["exact_match_count"]}; rate: {stage["exact_match_rate"]}; over-call: {stage["over_call_count"]}; under-call: {stage["under_call_count"]}. Human and model stages are descriptive, using WATCH < SETUP < TRIGGER < TREND < EXTENDED. Human TRIGGER n=0 is preserved and is not treated as an error.

6. Events and lead time
Observed Fast trigger events: {event["fast_trigger_event_count"]}. Pair-status distribution: {event["pair_status_distribution"]}. Clean lead population (FAST_EARLIER_PATTERN_A_LATER): n={event["clean_lead"]["n"]}, median weeks={event["clean_lead"]["median"]}, status={event["clean_lead"]["status"]}. A clean-lead n below the preregistered 3 is INCONCLUSIVE, not evidence of no lead.

7. TOO_EARLY diagnostic
TOO_EARLY n={summary["too_early_analysis"]["human_n"]}. Frozen monthly, weekly, and daily component distributions are retained as descriptive diagnostics in the JSON artifact; no threshold/model adjustment was made after ground-truth exposure.

8. Failure and limitation
Hard failures: {summary["hard_failures"]} (count={summary["hard_failure_count"]}). Overall OOS-B status: {summary["overall_oos_b_status"]}.
Historical coverage limitation: {summary["historical_coverage_limitation"]}
''', encoding="utf-8")


def main() -> None:
    samples, protocol, score, stage = load_inputs()
    snapshot, pairs, summary = build_outputs(samples, protocol, score, stage)
    # Output is written only after all frozen-input gates and evaluation complete.
    snapshot.to_csv(OUT_SAMPLES, index=False)
    pairs.to_csv(OUT_PAIRS, index=False)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_document(summary)
    print(f"evaluated samples={len(snapshot)}, fast_events={len(pairs)}, status={summary['overall_oos_b_status']}")


if __name__ == "__main__":
    main()
