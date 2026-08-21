#!/usr/bin/env python
"""Phase 13I-2: frozen RESERVED_OOS_A evaluation; no tuning or network access."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

try:  # ``python scripts/...`` and module-import test execution both supported.
    from scripts.research_pattern_a_fast_lead_time_failure import _semantic_true, evaluate_fast_contract
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from research_pattern_a_fast_lead_time_failure import _semantic_true, evaluate_fast_contract
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features
from trend_scanner.validation.historical_snapshot import build_historical_snapshot


BASE_SHA = "94bc7edf2ea959f27d847b5cd9f23cd0cf3521c1"
FAST_CONTRACT_SHA = "2da3fc36744b27ec13edae3f690df72c796906e5"
PATTERN_A_FROZEN_SHA = "05d03e16501adbca889488294aaaaa0bd84005de"
OOS = Path("artifacts/patterns/pattern_a_fast/validation/oos")
RESULTS = OOS / "results"
REVIEW = OOS / "pattern_a_fast_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_oos_sample_manifest_v01.csv"
SEAL = OOS / "pattern_a_fast_oos_ground_truth_seal_v01.json"
ADJUDICATION = OOS / "pattern_a_fast_oos_outcome_adjudication_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_oos_evaluation_protocol_v01.json"
SCORE_CONTRACT = Path("artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json")
STAGE_CONTRACT = Path("artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json")
DOC = Path("docs/patterns/pattern_a_fast/validation/oos_evaluation_v01.md")
OUT = {
    "snapshot": RESULTS / "pattern_a_fast_oos_machine_snapshot_v01.csv",
    "confusion": RESULTS / "pattern_a_fast_oos_stage_confusion_v01.csv",
    "score": RESULTS / "pattern_a_fast_oos_score_evaluation_v01.json",
    "trigger": RESULTS / "pattern_a_fast_oos_trigger_events_v01.csv",
    "pair": RESULTS / "pattern_a_fast_oos_event_pairing_v01.csv",
    "lead": RESULTS / "pattern_a_fast_oos_lead_time_v01.csv",
    "summary": RESULTS / "pattern_a_fast_oos_evaluation_summary_v01.json",
}
STAGES = ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
ORDER = {stage: index for index, stage in enumerate(STAGES)}
PAIRING_PRECEDENCE = [
    "DATA_UNAVAILABLE", "SAME_WEEK", "PATTERN_A_ALREADY_ACTIVE",
    "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", "FAST_EARLIER_PATTERN_A_LATER",
    "FAST_EVENT_NO_PATTERN_A_CATCHUP",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def cliffs_delta(left: pd.Series, right: pd.Series) -> float | None:
    a, b = left.dropna().tolist(), right.dropna().tolist()
    if not a or not b:
        return None
    return float((sum(x > y for x in a for y in b) - sum(x < y for x in a for y in b)) / (len(a) * len(b)))


def load_inputs() -> tuple[pd.DataFrame, dict, dict, dict]:
    manifest = pd.read_csv(MANIFEST, dtype=str, keep_default_na=False)
    review = pd.read_csv(REVIEW, dtype=str, keep_default_na=False)
    merged = manifest.merge(review, on=["oos_sample_id", "source_sample_id", "ticker", "name", "reference_date", "outcome_review_end"], validate="one_to_one")
    assert merged.review_order_x.equals(merged.review_order_y)
    merged = merged.rename(columns={"review_order_x": "review_order"}).drop(columns=["review_order_y"])
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    adjudication = pd.read_csv(ADJUDICATION, dtype=str, keep_default_na=False)
    assert len(merged) == merged.oos_sample_id.nunique() == 20
    assert set(merged.oos_sample_id) == {f"OOS_A_{i:03d}" for i in range(1, 21)}
    assert protocol["fast_contract"] == "HIERARCHICAL_V01"
    assert protocol["fast_contract_sha"] == FAST_CONTRACT_SHA
    assert protocol["pattern_a_frozen_sha"] == PATTERN_A_FROZEN_SHA
    assert seal["human_review_csv_sha256"] == sha256(REVIEW)
    assert adjudication.oos_sample_id.tolist() == ["OOS_A_012"]
    assert merged.loc[merged.oos_sample_id.eq("OOS_A_012"), "outcome_review_status"].iloc[0] == "DATA_UNAVAILABLE"
    score = json.loads(SCORE_CONTRACT.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT.read_text(encoding="utf-8"))
    assert score["selected_research_prototype"] == "HIERARCHICAL_V01"
    assert stage["stage_semantics"] == STAGES
    return merged.sort_values("review_order", key=lambda series: series.astype(int)), protocol, score, stage


def point(ticker: str, name: str, daily: pd.DataFrame, weekly_date: pd.Timestamp, score: dict, stage: dict) -> dict:
    """One strict PIT point. No human field is an evaluator input."""
    snapshot = build_historical_snapshot(ticker, name, daily, weekly_date, include_incomplete_periods=False)
    if snapshot.weekly_as_of != weekly_date:
        raise ValueError(f"Incomplete weekly label: {ticker} {weekly_date.date()}")
    features: dict[str, float] = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(daily[daily.index <= weekly_date]))
    fast = evaluate_fast_contract(features, score, stage)
    pattern = evaluate_pattern_a(snapshot)
    pattern_ready = pattern.score is not None and pattern.stage is not None
    monthly_status = "READY" if not any(pd.isna(features.get(key, np.nan)) for key in ("range_position_24m", "monthly_down_month_ratio_12m")) else "UNAVAILABLE"
    daily_status = "READY" if not any(pd.isna(features.get(key, np.nan)) for key in ("recent_5d_max_gap_abs_pct", "atr_14_pct")) else "UNAVAILABLE"
    return {
        **fast,
        "monthly_component_status": monthly_status,
        "weekly_component_status": fast["fast_score_status"] if fast["fast_weekly_core_score"] == fast["fast_weekly_core_score"] else "UNAVAILABLE",
        "daily_component_status": daily_status,
        "conditional_breakout_status": fast["fast_conditional_status"],
        "wma200_status": "UNKNOWN" if pd.isna(features.get("close_vs_wma200_pct", np.nan)) else "READY",
        "pattern_a_evaluation_status": "READY" if pattern_ready else "UNAVAILABLE",
        "pattern_a_score": number(pattern.score),
        "pattern_a_stage": pattern.stage.value if pattern.stage else None,
        "pattern_a_candidate_active": _semantic_true(pattern.candidate_state.value == "candidate") if pattern_ready else np.nan,
        "effective_as_of": snapshot.effective_as_of.strftime("%Y-%m-%d") if snapshot.effective_as_of is not None else "",
        "monthly_as_of": snapshot.monthly_as_of.strftime("%Y-%m-%d") if snapshot.monthly_as_of is not None else "",
        "weekly_as_of": snapshot.weekly_as_of.strftime("%Y-%m-%d") if snapshot.weekly_as_of is not None else "",
    }


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
    if daily is None:
        raise RuntimeError(f"CACHE_MISSING: {sample.ticker}; no substitution permitted")
    daily = daily.sort_index()
    reference, end = pd.Timestamp(sample.reference_date), pd.Timestamp(sample.outcome_review_end)
    start = reference - pd.Timedelta(weeks=104)
    rows = []
    for weekly_date in to_weekly(daily[daily.index <= end]).index:
        if weekly_date < start or weekly_date > end:
            continue
        week_daily = daily[daily.index <= weekly_date]
        if week_daily.empty or week_daily.index.max().normalize() != weekly_date.normalize():
            continue
        value = point(sample.ticker, sample["name"], daily, weekly_date, score, stage)
        rows.append({"oos_sample_id": sample.oos_sample_id, "ticker": sample.ticker, "name": sample["name"], "weekly_date": weekly_date.strftime("%Y-%m-%d"), **value})
    timeline = annotate(pd.DataFrame(rows).sort_values("weekly_date").reset_index(drop=True))
    if timeline.empty:
        raise RuntimeError(f"NO_COMPLETED_WEEKLY_TIMELINE: {sample.oos_sample_id}")
    return timeline


def pair_events(timeline: pd.DataFrame, sample: pd.Series) -> pd.DataFrame:
    rows = []
    # The 104-week pre-reference slice is evidence for left-censored prior
    # Pattern A activity only. OOS Fast events themselves begin at reference.
    observed = timeline[
        timeline.fast_trigger_event_status.eq("OBSERVED")
        & (pd.to_datetime(timeline.weekly_date) >= pd.Timestamp(sample.reference_date))
    ]
    candidate_events = timeline[timeline.pattern_a_candidate_event_status.eq("OBSERVED")]
    for sequence, (_, event) in enumerate(observed.iterrows(), start=1):
        event_date = pd.Timestamp(event.weekly_date)
        pattern_ready = event.pattern_a_evaluation_status == "READY"
        same = candidate_events[candidate_events.weekly_date.eq(event.weekly_date)]
        prior_activity = timeline[(pd.to_datetime(timeline.weekly_date) < event_date) & timeline.pattern_a_evaluation_status.eq("READY") & timeline.pattern_a_candidate_active.map(_semantic_true)]
        prior = candidate_events[pd.to_datetime(candidate_events.weekly_date) < event_date]
        future = candidate_events[pd.to_datetime(candidate_events.weekly_date) > event_date]
        if not pattern_ready:
            status, next_date = "DATA_UNAVAILABLE", None
        elif not same.empty:
            status, next_date = "SAME_WEEK", event.weekly_date
        elif _semantic_true(event.pattern_a_candidate_active):
            status, next_date = "PATTERN_A_ALREADY_ACTIVE", None
        elif not prior_activity.empty:
            status, next_date = "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", None
        elif not future.empty:
            status, next_date = "FAST_EARLIER_PATTERN_A_LATER", future.iloc[0].weekly_date
        else:
            status, next_date = "FAST_EVENT_NO_PATTERN_A_CATCHUP", None
        lead_days = (pd.Timestamp(next_date) - event_date).days if status in {"SAME_WEEK", "FAST_EARLIER_PATTERN_A_LATER"} else np.nan
        rows.append({
            "oos_sample_id": sample.oos_sample_id, "ticker": sample.ticker, "name": sample["name"],
            "reference_date": sample.reference_date, "outcome_review_end": sample.outcome_review_end,
            "fast_trigger_event_sequence": sequence, "fast_trigger_event_date": event.weekly_date,
            "fast_trigger_event_status": "OBSERVED", "fast_score_at_event": event.fast_score,
            "pattern_a_status_at_fast_event": event.pattern_a_evaluation_status,
            "pattern_a_active_at_fast_event": event.pattern_a_candidate_active if pattern_ready else np.nan,
            "pattern_a_was_active_before_fast_event": "YES" if not prior_activity.empty else "NO" if pattern_ready else "",
            "pattern_a_prior_active_date": prior_activity.iloc[-1].weekly_date if not prior_activity.empty else "",
            "pattern_a_prior_candidate_event_date": prior.iloc[-1].weekly_date if not prior.empty else "",
            "pattern_a_next_candidate_event_date": next_date or "", "pair_status": status,
            "lead_weeks": lead_days / 7 if not pd.isna(lead_days) else np.nan,
            "censor_status": "DATA_UNAVAILABLE" if status == "DATA_UNAVAILABLE" else "RIGHT_CENSORED" if status == "FAST_EVENT_NO_PATTERN_A_CATCHUP" else "NOT_CENSORED",
        })
    return pd.DataFrame(rows)


def machine_snapshot(samples: pd.DataFrame, score: dict, stage: dict, cache: ParquetCache) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, timelines = [], []
    for _, sample in samples.iterrows():
        timeline = sample_timeline(sample, score, stage, cache)
        timelines.append(timeline)
        reference = timeline[timeline.weekly_date.eq(sample.reference_date)]
        if len(reference) != 1:
            raise RuntimeError(f"REFERENCE_NOT_COMPLETED_OR_NONUNIQUE: {sample.oos_sample_id}")
        value = reference.iloc[0]
        machine_stage = value.fast_machine_stage if value.fast_machine_stage_status == "READY" else ""
        human_stage = sample.weekly_stage_at_reference
        if not machine_stage:
            call, delta, match = "UNAVAILABLE", np.nan, "UNAVAILABLE"
        else:
            delta = ORDER[machine_stage] - ORDER[human_stage]
            call, match = ("EXACT", "EXACT") if delta == 0 else ("OVER_CALL", "MISMATCH") if delta > 0 else ("UNDER_CALL", "MISMATCH")
        rows.append({
            "oos_sample_id": sample.oos_sample_id, "ticker": sample.ticker, "name": sample["name"], "reference_date": sample.reference_date,
            "human_stage": human_stage, "human_outcome_label": sample.human_label,
            "human_outcome_available": str(sample.outcome_review_status == "COMPLETE").lower(),
            "machine_stage_status": value.fast_machine_stage_status, "machine_stage_proto": machine_stage,
            "machine_score_status": value.fast_score_status, "machine_score": value.fast_score,
            "monthly_component_status": value.monthly_component_status, "weekly_component_status": value.weekly_component_status,
            "daily_component_status": value.daily_component_status, "conditional_breakout_status": value.conditional_breakout_status,
            "wma200_status": value.wma200_status, "effective_as_of": value.effective_as_of,
            "monthly_as_of": value.monthly_as_of, "weekly_as_of": value.weekly_as_of,
            "stage_match": match, "stage_delta": delta, "stage_call_type": call,
        })
    return pd.DataFrame(rows), pd.concat(timelines, ignore_index=True)


def stage_confusion(snapshot: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    ready = snapshot[snapshot.machine_stage_status.eq("READY")]
    rows = []
    for human in STAGES:
        subset = ready[ready.human_stage.eq(human)]
        total = len(subset)
        row = {"human_stage": human, **{machine: int((subset.machine_stage_proto == machine).sum()) for machine in STAGES}, "ready_total": total}
        row.update({f"{machine}_rate": (row[machine] / total if total else None) for machine in STAGES})
        rows.append(row)
    exact = int((ready.stage_call_type == "EXACT").sum())
    return pd.DataFrame(rows), {
        "exact_match_count": exact, "exact_match_rate": (exact / len(ready) if len(ready) else None),
        "overcall_count": int((ready.stage_call_type == "OVER_CALL").sum()),
        "undercall_count": int((ready.stage_call_type == "UNDER_CALL").sum()),
    }


def score_evaluation(snapshot: pd.DataFrame, protocol: dict) -> dict:
    primary = protocol["primary_score_comparison"]
    positive, negative = primary["positive_labels"], primary["negative_labels"]
    available = snapshot[snapshot.machine_score_status.isin(["READY", "PARTIAL"])]
    def group(labels: list[str]) -> dict:
        human = snapshot[snapshot.human_outcome_label.isin(labels)]
        usable = available[available.human_outcome_label.isin(labels)].machine_score.dropna()
        return {"human_group_n": int(len(human)), "score_available_n": int(len(usable)), "median": number(usable.median())}
    left, right = group(positive), group(negative)
    primary_status = "INCONCLUSIVE" if left["human_group_n"] < 3 or right["human_group_n"] < 3 else "PASS"
    result = {"primary_comparison_name": primary["name"], "positive_labels": positive, "negative_labels": negative,
              "n_positive": left["human_group_n"], "n_early_or_none": right["human_group_n"],
              "positive": left, "early_or_none": right, "minimum_n_per_group": 3,
              "median_positive": left["median"], "median_early_or_none": right["median"],
              "median_difference": None, "cliffs_delta": None, "primary_status": primary_status,
              "primary_reason": "INSUFFICIENT_POSITIVE_STRUCTURE_SAMPLE_SIZE" if primary_status == "INCONCLUSIVE" else "NOT_EVALUATED_PENDING_GATE"}
    if primary_status != "INCONCLUSIVE":
        a, b = available[available.human_outcome_label.isin(positive)].machine_score.dropna(), available[available.human_outcome_label.isin(negative)].machine_score.dropna()
        result.update({"median_difference": number(a.median() - b.median()), "cliffs_delta": cliffs_delta(a, b), "primary_status": "OOS_SCORE_DIRECTION_FAIL" if a.median() <= b.median() else "PASS", "primary_reason": "PREREGISTERED_DIRECTION_GATE"})
    secondary = []
    for left_label, right_label in protocol["secondary_score_comparisons"]:
        left_n, right_n = int((snapshot.human_outcome_label == left_label).sum()), int((snapshot.human_outcome_label == right_label).sum())
        secondary.append({"comparison": f"{left_label}_vs_{right_label}", "human_group_n": {left_label: left_n, right_label: right_n}, "status": "INCONCLUSIVE" if min(left_n, right_n) < 3 else "DESCRIPTIVE_ONLY", "reason": "INSUFFICIENT_SAMPLE_SIZE" if min(left_n, right_n) < 3 else "NOT_RUN_AS_OFFICIAL_GATE"})
    result["secondary_comparisons"] = secondary
    return result


def summary(samples: pd.DataFrame, snapshot: pd.DataFrame, pairs: pd.DataFrame, score_result: dict, stage_result: dict) -> dict:
    lead = pairs.loc[pairs.pair_status.eq("FAST_EARLIER_PATTERN_A_LATER"), "lead_weeks"] if not pairs.empty else pd.Series(dtype=float)
    pair_counts = {status: int((pairs.pair_status == status).sum()) if not pairs.empty else 0 for status in PAIRING_PRECEDENCE}
    stage_ready = int((snapshot.machine_stage_status == "READY").sum())
    score_counts = snapshot.machine_score_status.value_counts().to_dict()
    unavailable = int(score_counts.get("UNAVAILABLE", 0))
    hard = []
    if stage_ready / len(snapshot) < .80 or unavailable / len(snapshot) > .20:
        hard.append("OOS_DATA_COVERAGE_FAIL")
    if score_result["primary_status"] == "OOS_SCORE_DIRECTION_FAIL": hard.append("OOS_SCORE_DIRECTION_FAIL")
    lead_status = "OOS_LEAD_INCONCLUSIVE" if len(lead) < 3 else "OOS_LEAD_DIRECTION_FAIL" if lead.median() <= 0 else "PASS"
    if lead_status == "OOS_LEAD_DIRECTION_FAIL": hard.append(lead_status)
    overall = hard[0] if hard else "NO_HARD_OOS_FAILURE_BUT_PRIMARY_SCORE_INCONCLUSIVE" if score_result["primary_status"] == "INCONCLUSIVE" else "NO_HARD_OOS_FAILURE"
    return {
        "version": "pattern_a_fast_oos_evaluation_summary_v01", "base_sha": BASE_SHA,
        "ground_truth_seal_sha": sha256(SEAL), "fast_contract": "HIERARCHICAL_V01", "fast_contract_sha": FAST_CONTRACT_SHA,
        "pattern_a_frozen_sha": PATTERN_A_FROZEN_SHA, "protocol_sha256": sha256(PROTOCOL),
        "oos_sample_count": 20, "human_outcome_labeled_count": 19, "human_outcome_unavailable_count": 1,
        "machine_stage_ready_count": stage_ready, "machine_stage_ready_rate": stage_ready / len(snapshot), "machine_stage_unavailable_count": len(snapshot) - stage_ready,
        "machine_score_ready_count": int(score_counts.get("READY", 0)), "machine_score_partial_count": int(score_counts.get("PARTIAL", 0)),
        "machine_score_unavailable_count": unavailable, "machine_score_unavailable_rate": unavailable / len(snapshot),
        "human_stage_distribution": {stage: int((snapshot.human_stage == stage).sum()) for stage in STAGES},
        "machine_stage_distribution": {stage: int((snapshot.machine_stage_proto == stage).sum()) for stage in STAGES},
        **stage_result, "primary_score_comparison": score_result["primary_comparison_name"], "primary_score_status": score_result["primary_status"],
        "fast_trigger_event_count": int(len(pairs)), "pair_status_distribution": pair_counts,
        "clean_primary_lead_n": int(len(lead)), "median_lead_weeks": number(lead.median()), "lead_iqr": number(lead.quantile(.75) - lead.quantile(.25)), "lead_min": number(lead.min()), "lead_max": number(lead.max()),
        "lead_direction_status": lead_status, "data_coverage_status": "OOS_DATA_COVERAGE_FAIL" if "OOS_DATA_COVERAGE_FAIL" in hard else "PASS",
        "hard_failures": hard, "overall_oos_status": overall, "positive_anchor_count": 4, "positive_anchors_in_metrics": False,
        "retuning_performed": False, "production_frozen": False, "network_requests": 0,
    }


def write_document(summary_data: dict, score_data: dict, snapshot: pd.DataFrame) -> None:
    stage_rows = "\n".join(
        f"| {row.oos_sample_id} | {row.human_stage} | {row.machine_stage_proto or 'UNAVAILABLE'} | {row.machine_stage_status} | {row.machine_score_status} | {row.machine_score or 'N/A'} | {row.stage_call_type} |"
        for row in snapshot.itertuples(index=False)
    )
    DOC.write_text(f"""pattern_a_fast_oos_evaluation_v01.md
==================================================
Phase 13I-2 Frozen OOS Evaluation
==================================================

1. Purpose
RESERVED_OOS_A 20건에 HIERARCHICAL_V01과 frozen Pattern A를 최초 실행했다. raw cached OHLCV만 사용했고 network request는 0이다. 재튜닝은 하지 않았다.

2. Frozen Contracts
Base: {BASE_SHA}
Fast: HIERARCHICAL_V01 / {FAST_CONTRACT_SHA}
Pattern A: {PATTERN_A_FROZEN_SHA}
Ground truth seal SHA-256: {summary_data['ground_truth_seal_sha']}

3. OOS Population and Human Ground Truth
OOS population은 20건 그대로다. Human outcome labeled는 19건이며 OOS_A_012는 거래정지로 DATA_UNAVAILABLE다. Stage 및 availability에는 포함하고 outcome label group에는 제외했다.

4. Machine Availability
Stage READY: {summary_data['machine_stage_ready_count']}/20 ({summary_data['machine_stage_ready_rate']:.1%}); UNAVAILABLE: {summary_data['machine_stage_unavailable_count']}.
Score READY/PARTIAL/UNAVAILABLE: {summary_data['machine_score_ready_count']}/{summary_data['machine_score_partial_count']}/{summary_data['machine_score_unavailable_count']}.
Data coverage status: {summary_data['data_coverage_status']}.

5. Stage Results
Human-vs-machine exact/over-call/under-call: {summary_data['exact_match_count']}/{summary_data['overcall_count']}/{summary_data['undercall_count']}. Exact match rate는 READY machine stage 기준 {summary_data['exact_match_rate']}. 이는 descriptive metric이며 hard gate가 아니다.

| OOS ID | Human stage | Machine stage | Stage status | Score status | Score | Call |
|---|---|---|---|---|---:|---|
{stage_rows}

6. Score Results
Primary comparison: POSITIVE_STRUCTURE vs EARLY_OR_NONE. Human n_positive={score_data['n_positive']}, n_early_or_none={score_data['n_early_or_none']}; score-available n={score_data['positive']['score_available_n']}/{score_data['early_or_none']['score_available_n']}.
RESERVED_OOS_A has zero Human POSITIVE_STRUCTURE samples. Therefore the preregistered primary score-direction test is sample-size INCONCLUSIVE. The four Human Positive Anchors were NOT used in OOS metrics. Primary status: {score_data['primary_status']} ({score_data['primary_reason']}). All preregistered GOOD_TRIGGER secondary comparisons are INCONCLUSIVE when GOOD_TRIGGER n=0.

7. Trigger, Pairing, and Lead Time
Observed Fast trigger events: {summary_data['fast_trigger_event_count']}. Pair distribution: {summary_data['pair_status_distribution']}. Primary lead population is FAST_EARLIER_PATTERN_A_LATER only: n={summary_data['clean_primary_lead_n']}, median={summary_data['median_lead_weeks']}, IQR={summary_data['lead_iqr']}, min={summary_data['lead_min']}, max={summary_data['lead_max']}. Lead direction status: {summary_data['lead_direction_status']}.

8. Failure / Diagnostic Summary
Direct-jump is not a hard production criterion. Only preregistered data coverage, score direction, and lead direction can create hard failures.

9. Hard Gate Decision
Hard failures: {summary_data['hard_failures']}. Overall OOS status: {summary_data['overall_oos_status']}. HIERARCHICAL_V01 production_frozen remains false. This result does not claim fully OOS validated, and follow-up Investable OOS validation remains necessary.

10. Interpretation
RESERVED_OOS_A의 사람 positive structure 표본은 0건이다. 따라서 primary score direction은 PASS도 FAIL도 아닌 표본 부족 INCONCLUSIVE다. anchor 4건은 모든 OOS metric에서 제외했다.

11. Limitations
OOS_A_012 outcome-label interpretation requires advisor review. Stage/availability에는 포함했지만 human outcome label group과 secondary comparison에서는 제외했다.

12. Production Decision
이번 OOS 결과만으로 PRODUCTION_GO나 fully OOS validated를 선언하지 않는다. production_frozen은 false다.

13. Next Step
OOS_A_012 outcome-label interpretation requires advisor review. No tuning occurred after OOS labels were revealed. Next step is advisor review; no new OOS set is designed in this phase.
""", encoding="utf-8")


def main() -> None:
    samples, protocol, score, stage = load_inputs()
    RESULTS.mkdir(parents=True, exist_ok=True)
    snapshot, timeline = machine_snapshot(samples, score, stage, ParquetCache())
    confusion, stage_result = stage_confusion(snapshot)
    score_result = score_evaluation(snapshot, protocol)
    pair_frames = [pair_events(timeline[timeline.oos_sample_id.eq(sample.oos_sample_id)].reset_index(drop=True), sample) for _, sample in samples.iterrows()]
    pairs = pd.concat(pair_frames, ignore_index=True) if any(not frame.empty for frame in pair_frames) else pd.DataFrame(columns=["oos_sample_id", "pair_status", "lead_weeks"])
    observed = sum(
        int(((timeline.oos_sample_id == sample.oos_sample_id) & timeline.fast_trigger_event_status.eq("OBSERVED") & (pd.to_datetime(timeline.weekly_date) >= pd.Timestamp(sample.reference_date))).sum())
        for _, sample in samples.iterrows()
    )
    assert len(pairs) == observed == sum(Counter(pairs.pair_status).values())
    lead = pairs.copy()
    lead["primary_lead_eligible"] = lead.pair_status.eq("FAST_EARLIER_PATTERN_A_LATER")
    lead.loc[~lead.primary_lead_eligible, "lead_weeks"] = np.nan
    data = summary(samples, snapshot, pairs, score_result, stage_result)
    snapshot.to_csv(OUT["snapshot"], index=False)
    confusion.to_csv(OUT["confusion"], index=False)
    OUT["score"].write_text(json.dumps(score_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pairs.to_csv(OUT["pair"], index=False)
    pairs.to_csv(OUT["trigger"], index=False) if pairs.empty else pairs[[column for column in pairs.columns if column != "lead_weeks"]].to_csv(OUT["trigger"], index=False)
    lead.to_csv(OUT["lead"], index=False)
    OUT["summary"].write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_document(data, score_result, snapshot)
    print(f"wrote snapshot={len(snapshot)}, observed_events={observed}, pairs={len(pairs)}")


if __name__ == "__main__":
    main()
