"""Pattern A FAST Weekly History Adapter for Stock Report (additive, Contract v0.1).

Pattern A는 월 단위가 핵심 시간축이고, Pattern A FAST(HIERARCHICAL_V01)는 주 단위가
핵심 시간축이다. 이 모듈은 두 History를 하나의 표로 합치지 않고, FAST 전용 주별
history를 별도로 생성한다.

FAST scoring / stage 로직은 여기서 재계산하지 않는다.
``trend_scanner.patterns.pattern_a_fast_evaluator.evaluate_pattern_a_fast``
(HIERARCHICAL_V01 frozen JSON contract 해석 + frozen Pattern A 평가, Phase 13H
frozen script와 semantic parity 검증됨)를 그대로 재사용하며, 이 모듈은 완료된
주봉(weekly bar)에 대해 그 evaluator를 반복 호출하는 report adapter 역할만 한다.
Pattern A Score / Stage / Candidate State / Investability / Production
Ranking / Flow에는 어떤 영향도 주지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.reporting.models import (
    PatternAFastCurrentSignal,
    PatternAFastSection,
    PatternAFastWeeklyObservation,
)

logger = logging.getLogger(__name__)

FAST_CONTRACT_NAME = "HIERARCHICAL_V01"
FAST_LABEL = "Experimental / Early Signal"
FAST_LIFECYCLE_STATUS = "PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD"

# Pattern A Monthly History의 "최근 12개월(recent_12m)" 관측 구간과 동일한 calendar
# range를 FAST Weekly History에도 적용한다 (기존 report 관례를 따름, row 수를 억지로
# 맞추지는 않는다).
WEEKLY_HISTORY_LOOKBACK = pd.Timedelta(days=52 * 7)

_INTERPRETATION_BY_STAGE = {
    "WATCH": "FAST 기준 명확한 초기 상승 전환 구조가 아직 확인되지 않았습니다.",
    "SETUP": "주봉 기준 상승 전환 가능성을 보여주는 초기 구조가 형성되고 있으나 아직 Trigger 단계는 아닙니다.",
    "TRIGGER": "월봉 환경이 허용되는 상태에서 주봉 기준 초기 상승 전환 구조가 감지되었습니다.",
    "TREND": "FAST 기준 초기 상승 구조가 Trigger 이후 이어지고 있습니다.",
    "EXTENDED": "FAST 관점에서는 초기 진입 구간이 상당 부분 진행된 상태입니다.",
}
_INTERPRETATION_UNAVAILABLE = "FAST 평가에 필요한 데이터가 부족하여 국면을 판단할 수 없습니다."


def _empty_section() -> PatternAFastSection:
    empty_current = PatternAFastCurrentSignal(
        as_of=None,
        fast_score=None,
        score_availability="UNAVAILABLE",
        fast_stage=None,
        stage_availability="UNAVAILABLE",
        monthly_regime=None,
        daily_risk=None,
        interpretation=_INTERPRETATION_UNAVAILABLE,
    )
    return PatternAFastSection(
        status="EXPERIMENTAL",
        label=FAST_LABEL,
        contract=FAST_CONTRACT_NAME,
        lifecycle_status=FAST_LIFECYCLE_STATUS,
        current=empty_current,
        weekly_history=[],
        history_start_as_of=None,
        history_end_as_of=None,
        observation_count=0,
    )


def _load_fast_contracts(root_path: Path) -> tuple[dict, dict] | None:
    score_path = root_path / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
    stage_path = root_path / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"
    if not score_path.exists() or not stage_path.exists():
        return None
    score = json.loads(score_path.read_text(encoding="utf-8"))
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    return score, stage


def _interpretation(fast_stage: str | None) -> str:
    if fast_stage is None:
        return _INTERPRETATION_UNAVAILABLE
    return _INTERPRETATION_BY_STAGE.get(fast_stage, _INTERPRETATION_UNAVAILABLE)


def _to_observation(week_label: pd.Timestamp, close: float | None, point: dict) -> PatternAFastWeeklyObservation:
    fast_score = point["fast_score"]
    fast_stage = point["fast_machine_stage"]
    return PatternAFastWeeklyObservation(
        week_ending=week_label.strftime("%Y-%m-%d"),
        close=close,
        fast_score=None if fast_score is None or pd.isna(fast_score) else float(fast_score),
        score_availability=point["fast_score_status"],
        fast_stage=fast_stage,
        stage_availability=point["fast_machine_stage_status"],
        monthly_regime=point["fast_monthly_permission_state"],
        daily_risk=point["fast_daily_risk_state"],
        interpretation=_interpretation(fast_stage),
    )


def build_pattern_a_fast_section(
    ticker: str,
    name: str,
    daily_slice: pd.DataFrame,
    as_of: pd.Timestamp,
    root_path: Path,
) -> PatternAFastSection:
    """Pattern A FAST Weekly History section을 생성한다.

    ``daily_slice``는 호출자가 이미 ``as_of`` 시점까지로 PIT-슬라이싱한 데이터여야
    한다 (Stock Report의 기존 Pattern A 슬라이싱 관례와 동일). 완료된 주봉만
    포함하며, 미래 데이터로 과거 주 결과가 달라지지 않는다.
    """
    if daily_slice is None or daily_slice.empty:
        return _empty_section()

    contracts = _load_fast_contracts(root_path)
    if contracts is None:
        logger.warning("Pattern A FAST contracts not found under %s; skipping FAST section.", root_path)
        return _empty_section()
    score, stage = contracts

    daily_sorted = daily_slice.sort_index()
    lookback_start = as_of - WEEKLY_HISTORY_LOOKBACK
    weekly_labels = [label for label in to_weekly(daily_sorted).index if lookback_start <= label <= as_of]

    observations: list[PatternAFastWeeklyObservation] = []
    for week_label in weekly_labels:
        week_daily = daily_sorted[daily_sorted.index <= week_label]
        # Phase 13 completed-week contract: 해당 주의 마지막 거래일이 곧 주봉 label과
        # 일치해야만 완료된 주봉으로 인정한다 (미완료 현재 주는 제외).
        if week_daily.empty or week_daily.index.max().normalize() != week_label.normalize():
            continue
        # 완료된 주봉만 evaluator에 전달하므로 evaluate_pattern_a_fast의 유일한 raise
        # 경로(미완료 weekly date)는 여기서 발생하지 않는다. 그 외 예외는 데이터
        # 부족이 아닌 programming error이므로 여기서 숨기지 않고 그대로 전파한다.
        point = evaluate_pattern_a_fast(ticker, name, daily_sorted, week_label, score, stage)
        # 가격은 FAST evaluator의 output이 아니라 report observation metadata다.
        # week_daily의 마지막 행이 곧 completed-week 판정에 쓰인 그 거래일이므로
        # 그 행의 close를 그대로 사용한다(월말/평균/최신가 대체 금지, fail-closed).
        raw_close = week_daily.iloc[-1].get("close")
        close = None if raw_close is None or pd.isna(raw_close) else float(raw_close)
        observations.append(_to_observation(week_label, close, point))

    if not observations:
        return _empty_section()

    latest = observations[-1]
    current = PatternAFastCurrentSignal(
        as_of=latest.week_ending,
        fast_score=latest.fast_score,
        score_availability=latest.score_availability,
        fast_stage=latest.fast_stage,
        stage_availability=latest.stage_availability,
        monthly_regime=latest.monthly_regime,
        daily_risk=latest.daily_risk,
        interpretation=latest.interpretation,
    )

    return PatternAFastSection(
        status="EXPERIMENTAL",
        label=FAST_LABEL,
        contract=FAST_CONTRACT_NAME,
        lifecycle_status=FAST_LIFECYCLE_STATUS,
        current=current,
        weekly_history=observations,
        history_start_as_of=observations[0].week_ending,
        history_end_as_of=observations[-1].week_ending,
        observation_count=len(observations),
    )
