"""Pattern A Score Momentum v0.1.

Frozen Pattern A Score v0.2를 완료된 월봉(Completed Monthly) 기준 시간축으로
반복 평가하여 1M, 3M, 6M 시점 간의 Score 변화량(Raw Delta) 및 Component Delta를 산출하는
순수 측정 계층(Measurement Layer)이다.

[핵심 설계 원칙]:
1. Pure Measurement Layer: 별도의 가중 점수, alpha threshold, good/bad 판정을 만들지 않는다.
2. Frozen Score Repeated Evaluation: 각 observation 시점마다 Frozen Score v0.2를 그대로 호출한다.
3. Completed Monthly Cadence: 진행 중인 월봉을 배제하고 완성된 월봉만을 anchor로 사용한다.
4. Stage / Candidate State 완전 독립: `score_result.stage` 등 Score 내부 legacy stage를 일체 참조하지 않는다.
5. Partial Readiness: 37M(1M만 가능), 39M(1M,3M 가능), 42M(1M,3M,6M 가능) 등 horizon별 부분 준비도를 지원한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.data.resampler import to_monthly
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

    @property
    def score(self) -> float | None:
        """Pattern A Score 값 (Score 평가 실패 시 None)."""
        if self.score_result is None:
            return None
        return self.score_result.pattern_a_score


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

    monthly_score_deltas: tuple[float, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _diff_float(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(float(a) - float(b), 4)


def _diff_int(a: int | None, b: int | None) -> int | None:
    if a is None or b is None:
        return None
    return int(a) - int(b)


def compute_pattern_a_score_momentum(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    as_of: str | pd.Timestamp,
) -> PatternAScoreMomentumResult:
    """특정 as_of 시점 기준으로 1M, 3M, 6M Pattern A Score Momentum을 계산한다.

    Args:
        ticker: 종목코드 (6자리)
        name: 종목명
        daily: 일봉 OHLCV DataFrame
        as_of: 요청 기준일 (YYYY-MM-DD 또는 pd.Timestamp)

    Returns:
        PatternAScoreMomentumResult: 1M, 3M, 6M Horizon별 Score Delta 및 Component Delta
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

    # 2. 완성 월봉(Completed Monthly Bars) 목록 추출
    raw_monthly = to_monthly(sliced_daily)
    last_trading_ts = sliced_daily.index.max()
    completed_monthly = _drop_incomplete_current_month(raw_monthly, last_trading_ts)

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

    # 3. 최대 최근 7개 완성 월봉 시점(T-6, ..., T)에 대한 Score Observation 산출
    # completed_monthly 인덱스는 오름차순
    completed_dates = list(completed_monthly.index)
    # T 시점 인덱스 = len - 1
    t_idx = len(completed_dates) - 1

    # 관측할 offset들: 0(T), 1(T-1), 2(T-2), 3(T-3), 4(T-4), 5(T-5), 6(T-6)
    # 인덱스가 유효한 시점만 순서대로 관측 (오름차순 T-6 -> T)
    obs_offsets = [6, 5, 4, 3, 2, 1, 0]
    observations_list: list[PatternAScoreObservation] = []
    offset_to_obs: dict[int, PatternAScoreObservation] = {}

    for offset in obs_offsets:
        target_idx = t_idx - offset
        if target_idx < 0:
            continue
        anchor_date = completed_dates[target_idx]
        anchor_str = anchor_date.strftime("%Y-%m-%d")

        try:
            # HistoricalSnapshot 생성 (include_incomplete_periods=False)
            snapshot = build_historical_snapshot(
                ticker=clean_ticker,
                name=clean_name,
                daily=sliced_daily,
                snapshot_date=anchor_str,
                include_incomplete_periods=False,
            )
            # Frozen Score v0.2 산출
            score_res = score_pattern_a(snapshot.features)
            obs = PatternAScoreObservation(
                anchor_date=anchor_date,
                effective_as_of=snapshot.effective_as_of,
                monthly_as_of=snapshot.monthly_as_of,
                score_result=score_res,
            )
        except Exception:
            obs = PatternAScoreObservation(
                anchor_date=anchor_date,
                effective_as_of=None,
                monthly_as_of=None,
                score_result=None,
            )

        observations_list.append(obs)
        offset_to_obs[offset] = obs

    # 4. Horizon별 Delta 계산 함수
    current_obs = offset_to_obs.get(0)
    current_score = current_obs.score if current_obs is not None else None

    def _build_horizon(months: int) -> PatternAScoreMomentumHorizon:
        prior_obs = offset_to_obs.get(months)
        prior_anchor = (
            completed_dates[t_idx - months]
            if (t_idx - months) >= 0
            else momentum_anchor_ts - pd.DateOffset(months=months)
        )

        if current_obs is None or current_score is None:
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=prior_anchor,
                ready=False,
                current_score=None,
                prior_score=None,
                score_delta=None,
                reason_codes=("CURRENT_SCORE_UNAVAILABLE",),
            )

        if prior_obs is None or prior_obs.score_result is None or prior_obs.score is None:
            return PatternAScoreMomentumHorizon(
                months=months,
                current_anchor=momentum_anchor_ts,
                prior_anchor=prior_anchor,
                ready=False,
                current_score=current_score,
                prior_score=None,
                score_delta=None,
                reason_codes=(f"INSUFFICIENT_HISTORY_{months}M",),
            )

        curr_res = current_obs.score_result
        prior_res = prior_obs.score_result

        return PatternAScoreMomentumHorizon(
            months=months,
            current_anchor=momentum_anchor_ts,
            prior_anchor=prior_anchor,
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

    # 5. Month-to-Month Delta History 계산 (T-6->T-5, ..., T-1->T)
    m2m_deltas: list[float] = []
    for i in range(len(observations_list) - 1):
        prev_s = observations_list[i].score
        next_s = observations_list[i + 1].score
        if prev_s is not None and next_s is not None:
            m2m_deltas.append(round(next_s - prev_s, 4))

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
        monthly_score_deltas=tuple(m2m_deltas),
        reason_codes=tuple(global_reasons),
    )
