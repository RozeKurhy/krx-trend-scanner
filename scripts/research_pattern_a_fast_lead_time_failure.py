#!/usr/bin/env python
"""Phase 13H: Pattern A Fast vs frozen Pattern A lead/failure research only.

The script evaluates cached daily OHLCV at completed weekly points.  Fast is
evaluated by interpreting the frozen 13G-2 JSON contracts; Pattern A uses the
official frozen ``build_historical_snapshot -> evaluate_pattern_a`` path.
Neither contract, human annotation, nor market data cache is mutated.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily


BASE_SHA = "2da3fc36744b27ec13edae3f690df72c796906e5"
PATTERN_A_FROZEN_SHA = "05d03e16501adbca889488294aaaaa0bd84005de"
HUMAN_CALIBRATION_SHA = "2e5a87f8214fe91d6cd2dbfa2bdc03cc2453d696"
RESEARCH = Path("artifacts/patterns/pattern_a_fast/research/feature_role")
GT = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth")
CONTRACT = Path("artifacts/patterns/pattern_a_fast/production/contract_prototype")
REVIEW = GT / "pattern_a_fast_human_review_v01.csv"
SOURCE = GT / "pattern_a_fast_ground_truth_source_v01.csv"
CALIBRATION = RESEARCH / "pattern_a_fast_calibration_score_prototype_v01.csv"
SCORE_CONTRACT = CONTRACT / "pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT = CONTRACT / "pattern_a_fast_stage_prototype_v01.json"
OUT = {
    "timeline": RESEARCH / "pattern_a_fast_vs_pattern_a_timeline_v01.csv",
    "pairs": RESEARCH / "pattern_a_fast_trigger_event_pair_v01.csv",
    "reference": RESEARCH / "pattern_a_fast_reference_comparison_v01.csv",
    "failure": RESEARCH / "pattern_a_fast_failure_analysis_v01.csv",
    "summary": RESEARCH / "pattern_a_fast_lead_time_summary_v01.json",
}
CONSTRUCTIVE = {"SETUP", "TRIGGER", "TREND"}


def _date(value: object) -> str | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _number(value: object) -> float:
    return float(value) if value is not None and not pd.isna(value) else np.nan


def _semantic_true(value: object) -> bool:
    """Return True only for an explicit boolean True, never for missing data."""
    return value is True or (isinstance(value, np.bool_) and value == np.bool_(True))


def _pattern_a_ready_and_active(row: pd.Series) -> bool:
    return row.pattern_a_evaluation_status == "READY" and _semantic_true(row.pattern_a_candidate_active)


def load_labeled_samples() -> pd.DataFrame:
    review = pd.read_csv(REVIEW, dtype=str, keep_default_na=False)
    source = pd.read_csv(SOURCE, dtype=str, keep_default_na=False)
    labeled = review.loc[
        (review.weekly_stage_at_reference != "UNLABELED")
        & (review.human_label != "UNLABELED")
    ].copy()
    labeled = labeled.merge(
        source[["sample_id", "outcome_review_end"]], on="sample_id", how="left", validate="one_to_one"
    )
    assert len(labeled) == labeled.sample_id.nunique() == 40
    assert labeled.outcome_review_end.notna().all()
    return labeled


def load_contracts() -> tuple[dict, dict]:
    score = json.loads(SCORE_CONTRACT.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT.read_text(encoding="utf-8"))
    assert score["selected_research_prototype"] == "HIERARCHICAL_V01"
    assert stage["stage_semantics"] == ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
    return score, stage


def _zone(value: object, zones: list[dict], output: str) -> float:
    if pd.isna(value):
        return np.nan
    for zone in zones:
        if "upper_bound" in zone and float(value) <= float(zone["upper_bound"]):
            return float(zone[output])
    return float(zones[-1][output])


def _coefficient(formula: str, symbol: str) -> float:
    match = re.search(rf"([0-9.]+) \* {re.escape(symbol)}", formula)
    if not match:
        raise ValueError(f"cannot parse coefficient for {symbol}: {formula}")
    return float(match.group(1))


def _compare(value: object, condition: dict) -> bool:
    if pd.isna(value):
        return False
    operator, threshold = condition["operator"], float(condition["value"])
    return {">": float(value) > threshold, ">=": float(value) >= threshold, "<=": float(value) <= threshold}[operator]


def _unknown_or_compare(value: object, semantic: str) -> bool:
    """Interpret the frozen ``UNKNOWN_OR_>=_-0.10`` contract string."""
    if pd.isna(value):
        return True
    match = re.fullmatch(r"UNKNOWN_OR_(>=|>|<=)_(-?[0-9.]+)", semantic)
    if not match:
        raise ValueError(f"unsupported stage semantic: {semantic}")
    return _compare(value, {"operator": match.group(1), "value": float(match.group(2))})


def _all_rule(row: dict, rule: dict) -> bool:
    return all(_compare(row[field], condition) for field, condition in rule.items() if field != "any_of")


def _any_rule(row: dict, rules: list[dict]) -> bool:
    return any(_all_rule(row, rule) for rule in rules)


def evaluate_fast_contract(features: dict, score: dict, stage: dict) -> dict:
    """Evaluate the two frozen JSON contracts without importing 13G-2 code."""
    monthly_map = score["monthly_permission_mapping"]
    pos, down = features.get("range_position_24m"), features.get("monthly_down_month_ratio_12m")
    if pd.isna(pos) or pd.isna(down):
        monthly_state, monthly_score = "UNAVAILABLE", np.nan
    else:
        pos_zones = monthly_map["range_position_24m"]["zones"]
        down_zones = monthly_map["monthly_down_month_ratio_12m"]["zones"]
        weights = monthly_map["component_formula"]["weights"]
        monthly_score = round(
            weights["range_position_24m"] * _zone(pos, pos_zones, "score")
            + weights["monthly_down_month_ratio_12m"] * _zone(down, down_zones, "score"), 2
        )
        monthly_state = ("EARLY_REGIME" if float(pos) <= float(pos_zones[0]["upper_bound"])
                         else "PERMITTED_REGIME" if float(pos) <= float(pos_zones[1]["upper_bound"])
                         else "LATE_OR_EXTENDED_REGIME")

    weekly_map = score["weekly_core_mapping"]
    required_weekly = [name for name in score["required_direct_inputs"] if name in weekly_map and name != "close_vs_wma200_pct"]
    if any(pd.isna(features.get(name, np.nan)) for name in required_weekly):
        weekly_score, weekly_status = np.nan, "UNAVAILABLE"
    else:
        parts = []
        for name, mapping in weekly_map.items():
            if name == "missing":
                continue
            value = features.get(name, np.nan)
            if not pd.isna(value):
                parts.append((_zone(value, mapping["zones"], "score"), float(mapping["weight"])))
        weekly_score = round(sum(value * weight for value, weight in parts) / sum(weight for _, weight in parts), 2)
        weekly_status = "PARTIAL" if pd.isna(features.get("close_vs_wma200_pct", np.nan)) else "READY"

    conditional_map = score["conditional_breakout_mapping"]["post_breakout_min_low_vs_level_pct_26w"]
    conditional_value = features.get("post_breakout_min_low_vs_level_pct_26w", np.nan)
    conditional_status = "EVENT_NOT_OBSERVED" if pd.isna(conditional_value) else "EVENT_OBSERVED"
    conditional_score = np.nan if pd.isna(conditional_value) else _zone(conditional_value, conditional_map["zones"], "score")

    daily_map = score["daily_risk_mapping"]
    gap, atr = features.get("recent_5d_max_gap_abs_pct", np.nan), features.get("atr_14_pct", np.nan)
    if pd.isna(gap) or pd.isna(atr):
        daily_state, daily_risk = "UNAVAILABLE", np.nan
    else:
        gap_risk = _zone(gap, daily_map["recent_5d_max_gap_abs_pct"]["zones"], "risk")
        atr_risk = _zone(atr, daily_map["atr_14_pct"]["zones"], "risk")
        daily_risk = round(min(100.0, gap_risk + _coefficient(daily_map["formula"], "atr_risk") * atr_risk), 2)
        daily_state = "NORMAL" if daily_risk <= 25 else "ELEVATED" if daily_risk <= 60 else "EXTREME"

    if any(pd.isna(value) for value in (monthly_score, weekly_score, daily_risk)):
        fast_score, fast_score_status = np.nan, "UNAVAILABLE"
    else:
        aggregate = score["aggregate_formula"]
        base = (_coefficient(aggregate["base"], "weekly_core_score") * weekly_score
                + _coefficient(aggregate["base"], "monthly_permission_score") * monthly_score)
        refine = 0.0 if pd.isna(conditional_score) else _coefficient(aggregate["conditional_refinement"], "(conditional_breakout_quality - 50)") * (conditional_score - 50)
        penalty = _coefficient(aggregate["final"], "daily_timing_risk") * daily_risk
        fast_score = round(float(np.clip(base + refine - penalty, 0, 100)), 2)
        fast_score_status = weekly_status

    required_stage = stage["required_stage_inputs"]
    if any(pd.isna(features.get(name, np.nan)) for name in required_stage):
        fast_stage, fast_stage_status = None, "UNAVAILABLE"
    else:
        extended = stage["extended_rule_candidate"]
        ready_rule = stage["ready_structure_candidate"]
        ready = (
            _compare(features["distance_to_prior_26w_high_pct"], ready_rule["distance_to_prior_26w_high_pct"])
            and _compare(features["higher_weekly_low_count_13w"], ready_rule["higher_weekly_low_count_13w"])
            and _unknown_or_compare(features.get("close_vs_wma200_pct", np.nan), ready_rule["close_vs_wma200_pct"])
        )
        marker = features.get("weeks_since_26w_close_breakout", np.nan)
        if _all_rule(features, {"close_vs_wma200_pct": extended["close_vs_wma200_pct"]}) and _any_rule(features, extended["any_of"]):
            fast_stage = "EXTENDED"
        elif ready and not pd.isna(marker) and _compare(marker, stage["trigger_rule_candidate"]["weeks_since_26w_close_breakout"]):
            fast_stage = "TRIGGER"
        elif _all_rule(features, {key: value for key, value in stage["trend_rule_candidate"].items() if key != "any_of"}) and _any_rule(features, stage["trend_rule_candidate"]["any_of"]):
            fast_stage = "TREND"
        elif _all_rule(features, {key: value for key, value in stage["setup_rule_candidate"].items() if key != "any_of"}) and _any_rule(features, stage["setup_rule_candidate"]["any_of"]):
            fast_stage = "SETUP"
        else:
            fast_stage = "WATCH"
        fast_stage_status = "READY"

    return {
        "fast_score": fast_score, "fast_score_status": fast_score_status,
        "fast_monthly_permission_state": monthly_state, "fast_daily_risk_state": daily_state,
        "fast_machine_stage": fast_stage, "fast_machine_stage_status": fast_stage_status,
        "fast_weekly_core_score": weekly_score, "fast_conditional_status": conditional_status,
    }


def evaluate_timeline_point(ticker: str, name: str, daily: pd.DataFrame, weekly_date: pd.Timestamp, score: dict, stage: dict) -> dict:
    snapshot = build_historical_snapshot(ticker, name, daily, weekly_date, include_incomplete_periods=False)
    if snapshot.weekly_as_of != weekly_date:
        raise ValueError(f"incomplete weekly date passed to evaluator: {ticker} {weekly_date}")
    features = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(daily[daily.index <= weekly_date]))
    fast = evaluate_fast_contract(features, score, stage)
    pattern = evaluate_pattern_a(snapshot)
    pattern_stage = pattern.stage.value if pattern.stage else None
    pattern_active = pattern.candidate_state.value == "candidate"
    pattern_status = "READY" if pattern.score is not None and pattern.stage is not None else "UNAVAILABLE"
    return {
        **fast,
        "pattern_a_evaluation_status": pattern_status,
        "pattern_a_score": pattern.score,
        "pattern_a_stage": pattern_stage,
        "pattern_a_candidate_active": pattern_active if pattern_status == "READY" else np.nan,
    }


def build_timeline(samples: pd.DataFrame, score: dict, stage: dict) -> pd.DataFrame:
    cache, rows = ParquetCache(), []
    for ticker, contexts in samples.groupby("ticker", sort=True):
        contexts = contexts.copy()
        daily = load_raw_daily(ticker, cache)
        if daily is None:
            raise RuntimeError(f"CACHE_MISSING for frozen sample ticker {ticker}")
        contexts["analysis_start"] = pd.to_datetime(contexts.reference_date) - pd.Timedelta(weeks=104)
        contexts["analysis_end"] = pd.to_datetime(contexts.outcome_review_end)
        start, end = contexts.analysis_start.min(), contexts.analysis_end.max()
        name = contexts.name.iloc[0]
        for weekly_date in to_weekly(daily[daily.index <= end]).index:
            if weekly_date < start or weekly_date > end:
                continue
            # W-FRI label이더라도 금요일 자체가 거래소 휴장인 주는 frozen
            # HistoricalSnapshot이 completed bar로 인정하지 않는다. 해당 label을
            # 억지로 목요일 snapshot으로 치환하지 않고 제외한다.
            week_daily = daily[daily.index <= weekly_date]
            if week_daily.empty or week_daily.index.max().normalize() != weekly_date.normalize():
                continue
            point = evaluate_timeline_point(ticker, name, daily, weekly_date, score, stage)
            active_contexts = contexts[(contexts.analysis_start <= weekly_date) & (contexts.analysis_end >= weekly_date)]
            if active_contexts.empty:
                continue
            rows.append({"ticker": ticker, "name": name, "weekly_date": _date(weekly_date), "sample_context_count": len(active_contexts), **point})
    timeline = pd.DataFrame(rows).sort_values(["ticker", "weekly_date"]).reset_index(drop=True)
    timeline = annotate_event_statuses(timeline)
    return timeline


def annotate_event_statuses(timeline: pd.DataFrame) -> pd.DataFrame:
    out = timeline.copy()
    out["fast_trigger_event_status"] = "NOT_OBSERVED"
    out["pattern_a_candidate_event_status"] = "NOT_OBSERVED"
    for _, group in out.groupby("ticker", sort=False):
        previous_fast_ready: str | None = None
        previous_pattern_valid: bool | None = None
        for index, row in group.iterrows():
            fast_stage, fast_ready = row.fast_machine_stage, row.fast_machine_stage_status == "READY"
            if fast_ready and fast_stage == "TRIGGER":
                if previous_fast_ready is None:
                    out.at[index, "fast_trigger_event_status"] = "LEFT_CENSORED"
                elif previous_fast_ready != "TRIGGER":
                    out.at[index, "fast_trigger_event_status"] = "OBSERVED"
            if fast_ready:
                previous_fast_ready = fast_stage
            else:
                previous_fast_ready = None

            valid = row.pattern_a_evaluation_status == "READY"
            active = _pattern_a_ready_and_active(row)
            if active:
                if previous_pattern_valid is None:
                    out.at[index, "pattern_a_candidate_event_status"] = "LEFT_CENSORED"
                elif previous_pattern_valid is False:
                    out.at[index, "pattern_a_candidate_event_status"] = "OBSERVED"
            previous_pattern_valid = active if valid else None
    return out


def direct_jump_dates(timeline: pd.DataFrame) -> set[tuple[str, str]]:
    dates: set[tuple[str, str]] = set()
    for ticker, group in timeline.groupby("ticker", sort=False):
        prior = None
        for _, row in group.iterrows():
            current = row.fast_machine_stage if row.fast_machine_stage_status == "READY" else None
            if prior in {"WATCH", "SETUP"} and current == "TREND":
                dates.add((ticker, row.weekly_date))
            prior = current
    return dates


def build_pairs(timeline: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    max_end = samples.assign(end=pd.to_datetime(samples.outcome_review_end)).groupby("ticker").end.max()
    for ticker, group in timeline.groupby("ticker", sort=False):
        group = group.sort_values("weekly_date").reset_index(drop=True)
        observed = group[group.fast_trigger_event_status == "OBSERVED"]
        candidate_events = group[group.pattern_a_candidate_event_status == "OBSERVED"]
        for sequence, (_, event) in enumerate(observed.iterrows(), start=1):
            event_date = pd.Timestamp(event.weekly_date)
            pattern_ready = event.pattern_a_evaluation_status == "READY"
            same = candidate_events[candidate_events.weekly_date == event.weekly_date]
            prior_activity = group[
                (pd.to_datetime(group.weekly_date) < event_date)
                & group.pattern_a_evaluation_status.eq("READY")
                & group.pattern_a_candidate_active.map(_semantic_true)
            ]
            prior = candidate_events[pd.to_datetime(candidate_events.weekly_date) < event_date]
            future = candidate_events[pd.to_datetime(candidate_events.weekly_date) > event_date]
            if not pattern_ready:
                pair_status, next_date = "DATA_UNAVAILABLE", None
            elif not same.empty:
                pair_status, next_date = "SAME_WEEK", event.weekly_date
            elif _semantic_true(event.pattern_a_candidate_active):
                pair_status, next_date = "PATTERN_A_ALREADY_ACTIVE", None
            elif not prior_activity.empty:
                pair_status, next_date = "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", None
            elif not future.empty:
                pair_status, next_date = "FAST_EARLIER_PATTERN_A_LATER", future.iloc[0].weekly_date
            else:
                pair_status, next_date = "FAST_EVENT_NO_PATTERN_A_CATCHUP", None
            lead_days = (pd.Timestamp(next_date) - event_date).days if pair_status in {"SAME_WEEK", "FAST_EARLIER_PATTERN_A_LATER"} else np.nan
            rows.append({
                "ticker": ticker, "name": event.name if False else event["name"],
                "fast_trigger_event_date": event.weekly_date, "fast_trigger_event_sequence": sequence,
                "fast_trigger_event_status": "OBSERVED", "fast_score_at_event": event.fast_score,
                "fast_monthly_state_at_event": event.fast_monthly_permission_state,
                "fast_daily_risk_at_event": event.fast_daily_risk_state,
                "pattern_a_status_at_fast_event": event.pattern_a_evaluation_status,
                "pattern_a_active_at_fast_event": event.pattern_a_candidate_active if pattern_ready else np.nan,
                "pattern_a_was_active_before_fast_event": "YES" if not prior_activity.empty else "NO" if pattern_ready else np.nan,
                "pattern_a_prior_active_date": prior_activity.iloc[-1].weekly_date if not prior_activity.empty else None,
                "pattern_a_prior_candidate_event_date": prior.iloc[-1].weekly_date if not prior.empty else None,
                "pattern_a_next_candidate_event_date": next_date, "pair_status": pair_status,
                "lead_days": lead_days, "lead_weeks": lead_days / 7 if not pd.isna(lead_days) else np.nan,
                "analysis_end": _date(max_end[ticker]), "censor_status": "DATA_UNAVAILABLE" if pair_status == "DATA_UNAVAILABLE" else "RIGHT_CENSORED" if pair_status == "FAST_EVENT_NO_PATTERN_A_CATCHUP" else "NOT_CENSORED",
            })
    return pd.DataFrame(rows)


def build_reference(timeline: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, sample in samples.iterrows():
        group = timeline[timeline.ticker.eq(sample.ticker)].copy()
        current = group[group.weekly_date.eq(sample.reference_date)]
        if len(current) != 1:
            raise AssertionError(f"missing/nonunique reference timeline row: {sample.sample_id}")
        point = current.iloc[0]
        later = group[(group.weekly_date > sample.reference_date) & (group.pattern_a_candidate_event_status == "OBSERVED") & (group.weekly_date <= sample.outcome_review_end)]
        pattern_ready = point.pattern_a_evaluation_status == "READY"
        active, constructive = _pattern_a_ready_and_active(point), point.fast_machine_stage in CONSTRUCTIVE
        next_date = later.iloc[0].weekly_date if not later.empty else None
        if point.fast_machine_stage_status != "READY" or not pattern_ready:
            status, weeks = "DATA_UNAVAILABLE", np.nan
        elif active:
            status, weeks = "PATTERN_A_ALREADY_ACTIVE", 0.0
        elif not next_date:
            status, weeks = "PATTERN_A_NOT_OBSERVED_WITHIN_WINDOW", np.nan
        else:
            status, weeks = "PATTERN_A_LATER_CATCHUP", (pd.Timestamp(next_date) - pd.Timestamp(sample.reference_date)).days / 7
        comparison = ("DATA_UNAVAILABLE" if status == "DATA_UNAVAILABLE" else
                      "BOTH_ACTIVE_AT_REFERENCE" if active and constructive else
                      "PATTERN_A_ONLY_AT_REFERENCE" if active else
                      "FAST_CONSTRUCTIVE_PATTERN_A_INACTIVE" if constructive else "NEITHER_ACTIVE_AT_REFERENCE")
        rows.append({
            "sample_id": sample.sample_id, "ticker": sample.ticker, "name": sample["name"], "reference_date": sample.reference_date,
            "human_stage": sample.weekly_stage_at_reference, "human_label": sample.human_label,
            "fast_score": point.fast_score, "fast_score_status": point.fast_score_status,
            "fast_stage": point.fast_machine_stage, "fast_stage_status": point.fast_machine_stage_status,
            "monthly_permission_state": point.fast_monthly_permission_state, "daily_risk_state": point.fast_daily_risk_state,
            "pattern_a_score": point.pattern_a_score, "pattern_a_stage": point.pattern_a_stage,
            "pattern_a_candidate_active": point.pattern_a_candidate_active, "pattern_a_status": point.pattern_a_evaluation_status,
            "reference_comparison_status": comparison, "pattern_a_next_candidate_date": next_date,
            "reference_to_pattern_a_candidate_weeks": weeks, "reference_catchup_status": status,
        })
    return pd.DataFrame(rows)


def build_failure(reference: pd.DataFrame, timeline: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    q1, q3 = reference.fast_score.quantile([.25, .75])
    direct = direct_jump_dates(timeline)
    rows = []
    for _, row in reference.iterrows():
        flags = []
        if row.human_label == "FALSE_TRIGGER" and row.fast_stage in CONSTRUCTIVE: flags.append("FAST_FALSE_TRIGGER_CONTEXT")
        if row.human_label == "TOO_EARLY" and row.fast_stage in CONSTRUCTIVE: flags.append("FAST_TOO_EARLY_CONTEXT")
        if row.human_label in {"TOO_LATE", "TOO_EXTENDED"} and (row.fast_stage in {"TREND", "EXTENDED"} or row.daily_risk_state in {"ELEVATED", "EXTREME"}): flags.append("FAST_TOO_LATE_CONTEXT")
        if row.fast_score >= q3 and row.human_label in {"FALSE_TRIGGER", "NO_SETUP", "TOO_EARLY", "TOO_EXTENDED"}: flags.append("FAST_HIGH_SCORE_BAD_OUTCOME")
        if row.fast_score <= q1 and row.human_label in {"GOOD_TRIGGER", "BORDERLINE_TRIGGER"}: flags.append("FAST_LOW_SCORE_GOOD_OUTCOME")
        if row.pattern_a_status == "READY" and _semantic_true(row.pattern_a_candidate_active): flags.append("PATTERN_A_ALREADY_ACTIVE")
        if row.reference_catchup_status == "PATTERN_A_NOT_OBSERVED_WITHIN_WINDOW": flags.append("PATTERN_A_NO_CATCHUP")
        if row.fast_stage_status != "READY" or row.pattern_a_status != "READY": flags.append("DATA_UNAVAILABLE")
        context = timeline[(timeline.ticker == row.ticker) & (timeline.weekly_date >= row.reference_date)]
        if any((row.ticker, date) in direct for date in context.weekly_date): flags.append("FAST_DIRECT_JUMP_NO_TRIGGER")
        if not flags: flags = ["NO_CLEAR_FAILURE"]
        for flag in flags:
            rows.append({"sample_id": row.sample_id, "ticker": row.ticker, "reference_date": row.reference_date, "human_label": row.human_label,
                         "failure_type": flag, "fast_stage": row.fast_stage, "fast_score": row.fast_score,
                         "pattern_a_stage": row.pattern_a_stage, "pattern_a_candidate_active": row.pattern_a_candidate_active,
                         "evidence": f"reference status={row.reference_comparison_status}; catchup={row.reference_catchup_status}",
                         "severity": "DESCRIPTIVE", "interpretation": "research evidence only; no contract retuning", "production_rule_change_recommended": "NO"})
    return pd.DataFrame(rows)


def reproduce_calibration(samples: pd.DataFrame, score: dict, stage: dict) -> None:
    baseline = pd.read_csv(CALIBRATION, dtype={"ticker": str}).set_index("sample_id")
    cache = ParquetCache()
    for _, sample in samples.iterrows():
        daily = load_raw_daily(sample.ticker, cache)
        point = evaluate_timeline_point(sample.ticker, sample["name"], daily, pd.Timestamp(sample.reference_date), score, stage)
        expected = baseline.loc[sample.sample_id]
        assert point["fast_score_status"] == expected.score_status
        assert point["fast_machine_stage_status"] == expected.machine_stage_status
        assert point["fast_machine_stage"] == expected.machine_stage_proto
        assert np.isclose(point["fast_score"], expected.pattern_a_fast_score_proto, equal_nan=True)


def summary_dict(samples: pd.DataFrame, timeline: pd.DataFrame, pairs: pd.DataFrame, reference: pd.DataFrame, failure: pd.DataFrame) -> dict:
    earlier = pairs[pairs.pair_status == "FAST_EARLIER_PATTERN_A_LATER"].lead_weeks
    horizons = {str(h): int((earlier <= h).sum()) for h in (4, 8, 13, 26, 52)}
    fast_status = timeline.fast_trigger_event_status
    direct_count = len(direct_jump_dates(timeline))
    observed_count = int((fast_status == "OBSERVED").sum())
    pair_counts = pairs.pair_status.value_counts().sort_index().to_dict()
    assert len(pairs) == observed_count == sum(pair_counts.values())
    return {
        "base_sha": BASE_SHA, "fast_contract_sha": BASE_SHA, "pattern_a_frozen_sha": PATTERN_A_FROZEN_SHA,
        "human_calibration_sha": HUMAN_CALIBRATION_SHA,
        "analysis_window": "reference minus 104 weeks through frozen outcome_review_end",
        "unique_tickers": int(samples.ticker.nunique()), "reference_samples": int(len(samples)), "timeline_rows": int(len(timeline)),
        "fast_trigger_events": observed_count, "paired_events": int(len(pairs)), "pair_status_counts": pair_counts,
        "pattern_a_already_active": int((pairs.pair_status == "PATTERN_A_ALREADY_ACTIVE").sum()), "same_week": int((pairs.pair_status == "SAME_WEEK").sum()),
        "pattern_a_prior_activity_before_fast_event": int((pairs.pair_status == "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT").sum()),
        "pattern_a_data_unavailable_at_fast_event": int((pairs.pair_status == "DATA_UNAVAILABLE").sum()),
        "fast_earlier_pattern_a_later": int(len(earlier)), "no_pattern_a_catchup": int((pairs.pair_status == "FAST_EVENT_NO_PATTERN_A_CATCHUP").sum()),
        "pair_status_reconciliation": {"observed_fast_trigger_events": observed_count, "classified_pairs": int(sum(pair_counts.values())), "pass": True},
        "left_censored": int((fast_status == "LEFT_CENSORED").sum()), "direct_jump_without_trigger": direct_count,
        "lead_weeks_summary": {"n": int(len(earlier)), "median": _number(earlier.median()), "iqr": _number(earlier.quantile(.75) - earlier.quantile(.25)), "min": _number(earlier.min()), "max": _number(earlier.max())},
        "catchup_horizons": horizons, "human_label_summary": samples.human_label.value_counts().sort_index().to_dict(),
        "failure_type_counts": dict(sorted(Counter(failure.failure_type).items())),
        "limitations": ["In-sample 40 human calibration records only", "No threshold/weight/stage retuning", "Observed events exclude left-censored and direct-jump synthetic dates"],
        "production_frozen": False,
    }


def main() -> None:
    samples, (score, stage) = load_labeled_samples(), load_contracts()
    reproduce_calibration(samples, score, stage)
    timeline = build_timeline(samples, score, stage)
    pairs = build_pairs(timeline, samples)
    reference = build_reference(timeline, samples)
    failure = build_failure(reference, timeline, pairs)
    for key, frame in (("timeline", timeline), ("pairs", pairs), ("reference", reference), ("failure", failure)):
        frame.to_csv(OUT[key], index=False)
    OUT["summary"].write_text(json.dumps(summary_dict(samples, timeline, pairs, reference, failure), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote timeline={len(timeline)}, pairs={len(pairs)}, reference={len(reference)}, failure={len(failure)}")


if __name__ == "__main__":
    main()
