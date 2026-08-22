"""Pattern A FAST (HIERARCHICAL_V01) runtime contract evaluator.

Phase 13H 연구 스크립트 ``scripts/research_pattern_a_fast_lead_time_failure.py``의
``evaluate_fast_contract`` / ``evaluate_timeline_point``는 frozen JSON contract
(``pattern_a_fast_score_prototype_v01.json`` / ``pattern_a_fast_stage_prototype_v01.json``)
를 해석해 HIERARCHICAL_V01 Score/Stage를 계산한다. 그 로직 자체는 이 두 JSON
contract가 담고 있는 데이터(zone, weight, threshold, formula 계수)이며, 이 모듈의
코드는 그 데이터를 해석하는 범용 interpreter일 뿐이다.

`src/trend_scanner`만 wheel에 포함되고 `scripts/`는 포함되지 않으므로, 배포/Web API
런타임이 frozen research script를 직접 import하는 구조는 안전하지 않다. 이 모듈은
frozen script를 수정하지 않은 채, 동일한 contract-interpretation 로직을
`src/trend_scanner` 내부의 production-safe 위치로 옮겨온 것이다.

frozen script(``scripts/research_pattern_a_fast_lead_time_failure.py``)는 Phase 13H
연구 기록으로 그대로 남아 있으며 이 모듈이 대체하지 않는다. 두 구현의 의미적 동일성은
``tests/test_pattern_a_fast_evaluator_parity.py``로 검증한다.

HIERARCHICAL_V01 Score 산식, FAST Stage rule, threshold, frozen JSON contract는
이 모듈에서 변경하지 않는다(재튜닝 없음).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features
from trend_scanner.validation.historical_snapshot import (
    PrecomputedTickerContext,
    build_historical_snapshot,
    build_historical_snapshot_from_context,
)


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
    """Evaluate the two frozen JSON contracts without reimplementing their semantics."""
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


def evaluate_pattern_a_fast(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    weekly_date: pd.Timestamp,
    score: dict,
    stage: dict,
    context: PrecomputedTickerContext | None = None,
) -> dict:
    """단일 (ticker, weekly_date) 시점의 Pattern A FAST + 참고용 Pattern A 결과를 반환한다.

    ``weekly_date``는 완료된 주봉(completed weekly bar)이어야 한다. 호출자가
    completed-week 여부를 먼저 확인해야 하며, 미완료 주가 전달되면
    ``ValueError``를 raise한다(frozen script의 ``evaluate_timeline_point``와 동일 계약).

    ``context``(선택, BACKTEST_PERFORMANCE_ENGINEERING_V01 Phase 4): 생략 시
    기존과 완전히 동일한 legacy 경로(``build_historical_snapshot``, 매 호출마다
    전체 daily를 다시 resample)를 사용한다. 전달되면 동일한 ticker에 대해
    미리 만들어둔 ``PrecomputedTickerContext``(``build_precomputed_ticker_context``)를
    사용하는 최적화 경로(``build_historical_snapshot_from_context``)로 스냅샷을
    구성하며, Feature/Pattern A/FAST 산식은 전혀 변경되지 않는다 -- 대량
    parity test(tests/test_backtest_performance_engine_v01_snapshot_context.py)로
    두 경로의 동일성을 증명했다.
    """
    if context is not None:
        snapshot = build_historical_snapshot_from_context(context, weekly_date, include_incomplete_periods=False)
        daily_up_to = context.slice_daily_up_to(weekly_date)
    else:
        snapshot = build_historical_snapshot(ticker, name, daily, weekly_date, include_incomplete_periods=False)
        daily_up_to = daily[daily.index <= weekly_date]
    if snapshot.weekly_as_of != weekly_date:
        raise ValueError(f"incomplete weekly date passed to evaluator: {ticker} {weekly_date}")
    features: dict[str, float] = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(daily_up_to))
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
