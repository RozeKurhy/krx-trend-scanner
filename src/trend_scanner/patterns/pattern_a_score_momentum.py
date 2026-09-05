"""Pattern A Score Momentum v0.1.

Frozen Pattern A Score v0.2를 완료된 월봉(Completed Monthly) 기준 시간축으로
반복 평가하여 정확한 Calendar 1M, 3M, 6M 시점 간의 Score 변화량(Raw Delta) 및 Component Delta를
산출하는 순수 측정 계층(Pure Measurement Layer)이다.

[핵심 설계 원칙]:
1. Pure Measurement Layer: 별도의 가중 점수, alpha threshold, good/bad 판정을 만들지 않는다.
2. Frozen Score Repeated Evaluation: 각 observation 시점마다 Frozen Score v0.2를 그대로 호출한다.
3. Completed Monthly Cadence: 진행 중인 월봉을 배제하고 `req_ts` 기준 완성된 월봉만을 anchor로 사용한다.
4. Exact Calendar Horizon: 단순 봉 순서(ordinal)가 아닌 정확한 Calendar Month 이전 시점과 비교한다 (Missing month silent backfill 금지).
5. Error Provenance & True Insufficient History 구분: 계산 에러, 히스토리 부족(Insufficient History), 중간 월봉 누락(Missing Month)을 명확히 구분한다.
6. Stage / Candidate State 완전 독립: `score_result.stage` 등 Score 내부 legacy stage를 일체 참조하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.data.resampler import to_monthly
from trend_scanner.backtest.snapshot_context import (
    PrecomputedTickerContext,
    build_historical_snapshot_from_context,
)
from trend_scanner.patterns.pattern_a_score import PatternAResult, score_pattern_a
from trend_scanner.validation.historical_snapshot import (
    _drop_incomplete_current_month,
    build_historical_snapshot,
)


@dataclass(frozen=True)
class PatternAScoreObservation:
    """단일 완성 월봉 Anchor 시점의 Pattern A Score 평가 관측값."""

    anchor_date: pd.Timestamp
    effective_as_of: pd.Timestamp | None
    monthly_as_of: pd.Timestamp | None
    score_result: PatternAResult | None
    reason_codes: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None

    @property
    def score(self) -> float | None:
        """Pattern A Score 값 (Score 평가 실패 시 None)."""
        if self.score_result is None:
            return None
        return self.score_result.pattern_a_score


@dataclass(frozen=True)
class PatternAMonthlyScoreDelta:
    """인접한 두 완성 월봉(1개월 간격) 사이의 Score 차분 관측값."""

    from_anchor: pd.Timestamp
    to_anchor: pd.Timestamp
    ready: bool
    score_delta: float | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatternAScoreMomentumHorizon:
    """특정 기간(1M, 3M, 6M) 동안의 Score 및 세부 Component 변화량."""

    months: int
    current_anchor: pd.Timestamp
    prior_anchor: pd.Timestamp
    ready: bool

    current_score: float | None
    prior_score: float | None
    score_delta: float | None

    base_score_delta: float | None = None
    transition_score_delta: float | None = None
    core_score_delta: float | None = None
    support_score_delta: float | None = None
    confirmation_bonus_delta: float | None = None
    balanced_core_score_delta: float | None = None
    alignment_bonus_delta: float | None = None
    progressed_penalty_delta: float | None = None
    progressed_evidence_count_delta: int | None = None

    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatternAScoreMomentumResult:
    """종목 단위 Pattern A Score Momentum 종합 결과."""

    ticker: str
    name: str
    requested_as_of: pd.Timestamp
    momentum_anchor: pd.Timestamp | None

    observations: tuple[PatternAScoreObservation, ...]

    horizon_1m: PatternAScoreMomentumHorizon
    horizon_3m: PatternAScoreMomentumHorizon
    horizon_6m: PatternAScoreMomentumHorizon

    available_horizons: tuple[int, ...]
    missing_horizons: tuple[int, ...]

    monthly_score_deltas: tuple[PatternAMonthlyScoreDelta, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _diff_float(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(float(a) - float(b), 4)


def _diff_int(a: int | None, b: int | None) -> int | None:
    if a is None or b is None:
        return None
    return int(a) - int(b)


def _get_calendar_month_end(base_month_end: pd.Timestamp, months_back: int) -> pd.Timestamp:
    """주어진 월말(Timestamp)로부터 정확히 months_back 개월 전의 월말 Timestamp를 산출한다."""
    target = base_month_end - pd.DateOffset(months=months_back)
    return target + pd.offsets.MonthEnd(0)


def compute_pattern_a_score_momentum(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    as_of: str | pd.Timestamp,
    *,
    context: PrecomputedTickerContext | None = None,
) -> PatternAScoreMomentumResult:
    """특정 as_of 시점 기준으로 정확한 Calendar 1M, 3M, 6M Pattern A Score Momentum을 계산한다.

    ``context`` is an optional, semantics-preserving precomputed ticker view.
    When supplied by a production batch consumer, it reuses the already
    validated weekly/monthly buckets for the seven historical observations;
    the legacy per-call path remains the default for isolated callers/tests.
    """
    clean_ticker = str(ticker).strip().zfill(6)
    clean_name = str(name).strip()
    req_ts = pd.Timestamp(as_of)

    if daily.empty:
        dummy_anchor = req_ts
        empty_horizon = lambda m: PatternAScoreMomentumHorizon(
            months=m,
            current_anchor=dummy_anchor,
            prior_anchor=dummy_anchor,
            ready=False,
            current_score=None,
            prior_score=None,
            score_delta=None,
            reason_codes=("NO_DAILY_DATA",),
        )
        return PatternAScoreMomentumResult(
            ticker=clean_ticker,
            name=clean_name,
            requested_as_of=req_ts,
            momentum_anchor=None,
            observations=(),
            horizon_1m=empty_horizon(1),
            horizon_3m=empty_horizon(3),
            horizon_6m=empty_horizon(6),
            available_horizons=(),
            missing_horizons=(1, 3, 6),
            reason_codes=("NO_DAILY_DATA",),
        )

    # 1. requested as_of까지 일봉 슬라이싱 (Lookahead 방지)
    sliced_daily = daily.loc[daily.index <= req_ts]
    if sliced_daily.empty:
        dummy_anchor = req_ts
        empty_horizon = lambda m: PatternAScoreMomentumHorizon(
            months=m,
            current_anchor=dummy_anchor,
            prior_anchor=dummy_anchor,
            ready=False,
            current_score=None,
            prior_score=None,
            score_delta=None,
            reason_codes=("NO_DATA_BEFORE_AS_OF",),
        )
        return PatternAScoreMomentumResult(
            ticker=clean_ticker,
            name=clean_name,
            requested_as_of=req_ts,
            momentum_anchor=None,
            observations=(),
            horizon_1m=empty_horizon(1),
            horizon_3m=empty_horizon(3),
            horizon_6m=empty_horizon(6),
            available_horizons=(),
            missing_horizons=(1, 3, 6),
            reason_codes=("NO_DATA_BEFORE_AS_OF",),
        )

    # 2. 완성 월봉(Completed Monthly Bars) 목록 추출 (NaN 빈 행 제외)
    # [Major 1]: req_ts를 전달하여 HistoricalSnapshot과 동일한 completed month contract 유지
    if context is None:
        raw_monthly = to_monthly(sliced_daily)
    else:
        raw_monthly = context.monthly_up_to(req_ts)
    valid_monthly = raw_monthly.dropna(subset=["close"])
    completed_monthly = _drop_incomplete_current_month(valid_monthly, req_ts)

    if completed_monthly.empty:
        dummy_anchor = req_ts
        empty_horizon = lambda m: PatternAScoreMomentumHorizon(
            months=m,
            current_anchor=dummy_anchor,
            prior_anchor=dummy_anchor,
            ready=False,
            current_score=None,
            prior_score=None,
            score_delta=None,
            reason_codes=("NO_COMPLETED_MONTHLY_BARS",),
        )
        return PatternAScoreMomentumResult(
            ticker=clean_ticker,
            name=clean_name,
            requested_as_of=req_ts,
            momentum_anchor=None,
            observations=(),
            horizon_1m=empty_horizon(1),
            horizon_3m=empty_horizon(3),
            horizon_6m=empty_horizon(6),
            available_horizons=(),
            missing_horizons=(1, 3, 6),
            reason_codes=("NO_COMPLETED_MONTHLY_BARS",),
        )

    momentum_anchor_ts = completed_monthly.index.max()
    available_monthly_set = set(completed_monthly.index)
    first_available_month_ts = completed_monthly.index.min()

    # 3. Calendar T-6, T-5, T-4, T-3, T-2, T-1, T 시점에 대한 Score Observation 산출
    obs_offsets = [6, 5, 4, 3, 2, 1, 0]
    observations_list: list[PatternAScoreObservation] = []
    offset_to_obs: dict[int, PatternAScoreObservation] = {}
    offset_to_status: dict[int, str] = {}  # "OK", "INSUFFICIENT_HISTORY", "MISSING_MONTH", "ERROR"

    for offset in obs_offsets:
        expected_anchor = _get_calendar_month_end(momentum_anchor_ts, offset)
        anchor_str = expected_anchor.strftime("%Y-%m-%d")

        # 해당 calendar month의 월봉 데이터가 존재하는지 확인
        if expected_anchor not in available_monthly_set:
            if expected_anchor < first_available_month_ts:
                # 전체 데이터 시작 시점 이전 ➔ 실제 히스토리 부족
                insufficient_code = (
                    "INSUFFICIENT_HISTORY_CURRENT"
                    if offset == 0
                    else f"INSUFFICIENT_HISTORY_{offset}M"
                )
                obs = PatternAScoreObservation(
                    anchor_date=expected_anchor,
                    effective_as_of=None,
                    monthly_as_of=None,
                    score_result=None,
                    reason_codes=(insufficient_code,),
                )
                offset_to_status[offset] = "INSUFFICIENT_HISTORY"
            else:
                # 데이터 기간 내에 해당 월만 누락 ➔ 중간 월봉 결측
                missing_code = (
                    "MISSING_MONTHLY_OBSERVATION_CURRENT"
                    if offset == 0
                    else f"MISSING_MONTHLY_OBSERVATION_{offset}M"
                )
                obs = PatternAScoreObservation(
                    anchor_date=expected_anchor,
                    effective_as_of=None,
                    monthly_as_of=None,
                    score_result=None,
                    reason_codes=(missing_code,),
                )
                offset_to_status[offset] = "MISSING_MONTH"

            observations_list.append(obs)
            offset_to_obs[offset] = obs
            continue

        # 데이터가 존재하는 경우 HistoricalSnapshot & Score 계산 시도
        try:
            if context is None:
                snapshot = build_historical_snapshot(
                    ticker=clean_ticker,
                    name=clean_name,
                    daily=sliced_daily,
                    snapshot_date=anchor_str,
                    include_incomplete_periods=False,
                )
            else:
                snapshot = build_historical_snapshot_from_context(
                    context,
                    snapshot_date=anchor_str,
                    include_incomplete_periods=False,
                )
            score_res = score_pattern_a(snapshot.features)
            if score_res.pattern_a_score is None:
                # 히스토리 부족으로 인한 점수 미산출인지 확인
                is_insufficient = (
                    score_res.flags.get("insufficient_data", False)
                    or (snapshot.monthly is not None and len(snapshot.monthly) < 36)
                )
                if is_insufficient:
                    insufficient_code = (
                        "INSUFFICIENT_HISTORY_CURRENT"
                        if offset == 0
                        else f"INSUFFICIENT_HISTORY_{offset}M"
                    )
                    obs = PatternAScoreObservation(
                        anchor_date=expected_anchor,
                        effective_as_of=snapshot.effective_as_of,
                        monthly_as_of=snapshot.monthly_as_of,
                        score_result=score_res,
                        reason_codes=(insufficient_code,),
                    )
                    offset_to_status[offset] = "INSUFFICIENT_HISTORY"
                else:
                    unavail_code = (
                        "SCORE_CALCULATION_UNAVAILABLE_CURRENT"
                        if offset == 0
                        else "SCORE_CALCULATION_UNAVAILABLE"
                    )
                    obs = PatternAScoreObservation(
                        anchor_date=expected_anchor,
                        effective_as_of=snapshot.effective_as_of,
                        monthly_as_of=snapshot.monthly_as_of,
                        score_result=score_res,
                        reason_codes=(unavail_code,),
                    )
                    offset_to_status[offset] = "ERROR"
            else:
                obs = PatternAScoreObservation(
                    anchor_date=expected_anchor,
                    effective_as_of=snapshot.effective_as_of,
                    monthly_as_of=snapshot.monthly_as_of,
                    score_result=score_res,
                    reason_codes=(),
                )
                offset_to_status[offset] = "OK"
        except Exception as exc:
            error_type = type(exc).__name__
            error_msg = str(exc)
            err_code = "OBSERVATION_ERROR_CURRENT" if offset == 0 else "OBSERVATION_ERROR"
            obs = PatternAScoreObservation(
                anchor_date=expected_anchor,
                effective_as_of=None,
                monthly_as_of=None,
                score_result=None,
                reason_codes=(err_code,),
                error_type=error_type,
                error_message=error_msg,
            )
            offset_to_status[offset] = "ERROR"

        observations_list.append(obs)
        offset_to_obs[offset] = obs

    # 4. Horizon별 Delta 계산 함수 (1M, 3M, 6M)
    current_obs = offset_to_obs.get(0)
    current_status = offset_to_status.get(0, "ERROR")
    current_score = current_obs.score if current_obs is not None else None

    def _build_horizon(months: int) -> PatternAScoreMomentumHorizon:
        expected_prior_anchor = _get_calendar_month_end(momentum_anchor_ts, months)
        prior_obs = offset_to_obs.get(months)
        prior_status = offset_to_status.get(months, "ERROR")

        # Current Score가 계산 불가한 경우
        if current_obs is None or current_score is None or current_status != "OK":
            curr_reasons = list(current_obs.reason_codes) if current_obs else []
            reasons = ["CURRENT_SCORE_UNAVAILABLE"]
            if current_status == "INSUFFICIENT_HISTORY":
                reasons.append("INSUFFICIENT_HISTORY_CURRENT")
            elif "OBSERVATION_ERROR" in curr_reasons or current_status == "ERROR":
                reasons.append("OBSERVATION_ERROR_CURRENT")
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=expected_prior_anchor,
                ready=False,
                current_score=None,
                prior_score=None,
                score_delta=None,
                reason_codes=tuple(reasons),
            )

        # Prior Observation 상태에 따른 사유 분리
        if prior_status == "INSUFFICIENT_HISTORY":
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=expected_prior_anchor,
                ready=False,
                current_score=current_score,
                prior_score=None,
                score_delta=None,
                reason_codes=(f"INSUFFICIENT_HISTORY_{months}M",),
            )
        elif prior_status == "MISSING_MONTH":
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=expected_prior_anchor,
                ready=False,
                current_score=current_score,
                prior_score=None,
                score_delta=None,
                reason_codes=(f"MISSING_MONTHLY_OBSERVATION_{months}M",),
            )
        elif prior_status == "ERROR" or prior_obs is None or prior_obs.score is None:
            err_reason = f"OBSERVATION_ERROR_{months}M"
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=expected_prior_anchor,
                ready=False,
                current_score=current_score,
                prior_score=None,
                score_delta=None,
                reason_codes=(err_reason,),
            )

        # 정상 산출 (OK)
        curr_res = current_obs.score_result
        prior_res = prior_obs.score_result

        return PatternAScoreMomentumHorizon(
            months=months,
            current_anchor=momentum_anchor_ts,
            prior_anchor=expected_prior_anchor,
            ready=True,
            current_score=current_score,
            prior_score=prior_obs.score,
            score_delta=_diff_float(current_score, prior_obs.score),
            base_score_delta=_diff_float(curr_res.base_score, prior_res.base_score),
            transition_score_delta=_diff_float(
                curr_res.transition_score, prior_res.transition_score
            ),
            core_score_delta=_diff_float(curr_res.core_score, prior_res.core_score),
            support_score_delta=_diff_float(curr_res.support_score, prior_res.support_score),
            confirmation_bonus_delta=_diff_float(
                curr_res.confirmation_bonus, prior_res.confirmation_bonus
            ),
            balanced_core_score_delta=_diff_float(
                curr_res.balanced_core_score, prior_res.balanced_core_score
            ),
            alignment_bonus_delta=_diff_float(curr_res.alignment_bonus, prior_res.alignment_bonus),
            progressed_penalty_delta=_diff_float(
                curr_res.progressed_penalty, prior_res.progressed_penalty
            ),
            progressed_evidence_count_delta=_diff_int(
                curr_res.progressed_evidence_count, prior_res.progressed_evidence_count
            ),
            reason_codes=(),
        )

    h_1m = _build_horizon(1)
    h_3m = _build_horizon(3)
    h_6m = _build_horizon(6)

    avail_horizons = []
    miss_horizons = []
    for m, h in [(1, h_1m), (3, h_3m), (6, h_6m)]:
        if h.ready:
            avail_horizons.append(m)
        else:
            miss_horizons.append(m)

    # 5. 구조화된 Month-to-Month Delta History 계산 (T-6->T-5, ..., T-1->T)
    structured_m2m: list[PatternAMonthlyScoreDelta] = []
    for i in range(len(observations_list) - 1):
        o_from = observations_list[i]
        o_to = observations_list[i + 1]
        s_from = o_from.score
        s_to = o_to.score

        if s_from is not None and s_to is not None:
            structured_m2m.append(
                PatternAMonthlyScoreDelta(
                    from_anchor=o_from.anchor_date,
                    to_anchor=o_to.anchor_date,
                    ready=True,
                    score_delta=round(s_to - s_from, 4),
                    reason_codes=(),
                )
            )
        else:
            m_reasons = []
            if s_from is None:
                m_reasons.extend(o_from.reason_codes or ("OBSERVATION_UNAVAILABLE_FROM",))
            if s_to is None:
                m_reasons.extend(o_to.reason_codes or ("OBSERVATION_UNAVAILABLE_TO",))
            structured_m2m.append(
                PatternAMonthlyScoreDelta(
                    from_anchor=o_from.anchor_date,
                    to_anchor=o_to.anchor_date,
                    ready=False,
                    score_delta=None,
                    reason_codes=tuple(m_reasons),
                )
            )

    global_reasons: list[str] = []
    if miss_horizons:
        global_reasons.append(f"MISSING_HORIZONS_{'_'.join(str(m) for m in miss_horizons)}")

    return PatternAScoreMomentumResult(
        ticker=clean_ticker,
        name=clean_name,
        requested_as_of=req_ts,
        momentum_anchor=momentum_anchor_ts,
        observations=tuple(observations_list),
        horizon_1m=h_1m,
        horizon_3m=h_3m,
        horizon_6m=h_6m,
        available_horizons=tuple(avail_horizons),
        missing_horizons=tuple(miss_horizons),
        monthly_score_deltas=tuple(structured_m2m),
        reason_codes=tuple(global_reasons),
    )
