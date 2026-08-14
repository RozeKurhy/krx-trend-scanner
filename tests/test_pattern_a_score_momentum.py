"""Pattern A Score Momentum v0.1 유닛 및 통합 테스트.

검증 항목:
1. test_frozen_score_equality: 관측 시점 Score가 직접 계산한 Frozen Score v0.2와 100% 동일함.
2. test_1m_delta_arithmetic: 1M Score Delta가 정확한 산술 차분(Current - 1M_ago)임을 검증.
3. test_3m_and_6m_delta_arithmetic: 3M, 6M Horizon Delta 산술 검증.
4. test_component_delta_decomposition: Base, Transition, Core, Alignment, Progressed penalty delta 검증.
5. test_history_readiness_thresholds_36_37_39_42:
   - 36 completed months: current score ready, 1M unavailable
   - 37 completed months: 1M ready
   - 39 completed months: 3M ready
   - 42 completed months: 6M ready
6. test_partial_horizon_readiness: 39개월 데이터에서 1M/3M은 ready, 6M은 ready=False로 부분 준비도 정상 반환.
7. test_incomplete_current_month_cadence: 월 중간 as_of 시 직전 완성 월봉을 anchor로 사용.
8. test_no_lookahead_contamination: as_of 이후의 미래 데이터가 Momentum 계산에 일체 영향 없음.
9. test_determinism: 동일 입력 시 100% 결정론적 일치.
10. test_score_stage_legacy_isolation: Score 내부 legacy stage에 일체 의존하지 않음.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.patterns.pattern_a_score_momentum import (
    PatternAScoreMomentumResult,
    compute_pattern_a_score_momentum,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _create_mock_daily(
    months: int = 45,
    start_date: str = "2020-01-01",
) -> pd.DataFrame:
    """합성 테스트용 일봉 데이터 생성."""
    dates = pd.date_range(start=start_date, periods=months * 21, freq="B")
    n = len(dates)

    return pd.DataFrame(
        {
            "open": [10000.0 + i * 10 for i in range(n)],
            "high": [10500.0 + i * 10 for i in range(n)],
            "low": [9500.0 + i * 10 for i in range(n)],
            "close": [10200.0 + i * 10 for i in range(n)],
            "volume": [100000 for _ in range(n)],
            "trading_value": [1000000000.0 for _ in range(n)],
        },
        index=dates,
    )


def test_frozen_score_equality():
    """관측 시점 Score가 직접 계산한 Frozen Score v0.2와 100% 동일함을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("000660")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=50)

    as_of = "2023-11-30"
    result = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, as_of)

    assert result.horizon_1m.ready is True
    # 직접 snapshot 생성하여 score_pattern_a 계산
    direct_snap = build_historical_snapshot(
        "000660", "SK하이닉스", daily, as_of, include_incomplete_periods=False
    )
    direct_res = score_pattern_a(direct_snap.features)

    current_obs = result.observations[-1]
    assert current_obs.anchor_date == pd.Timestamp(as_of)
    assert current_obs.score == direct_res.pattern_a_score
    assert current_obs.score_result.base_score == direct_res.base_score
    assert current_obs.score_result.transition_score == direct_res.transition_score
    assert current_obs.score_result.core_score == direct_res.core_score
    assert current_obs.score_result.progressed_penalty == direct_res.progressed_penalty


def test_1m_delta_arithmetic():
    """1M Score Delta가 정확한 산술 차분(Current - 1M_ago)임을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("000660")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=50)

    result = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, "2023-11-30")

    h1 = result.horizon_1m
    assert h1.ready is True
    assert h1.current_score is not None
    assert h1.prior_score is not None
    expected_delta = round(h1.current_score - h1.prior_score, 4)
    assert h1.score_delta == expected_delta


def test_3m_and_6m_delta_arithmetic():
    """3M 및 6M Horizon Delta 산술 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("000660")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=50)

    result = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, "2023-11-30")

    h3 = result.horizon_3m
    assert h3.ready is True
    assert h3.score_delta == round(h3.current_score - h3.prior_score, 4)

    h6 = result.horizon_6m
    assert h6.ready is True
    assert h6.score_delta == round(h6.current_score - h6.prior_score, 4)


def test_component_delta_decomposition():
    """Base, Transition, Core, Support, Confirmation, Alignment, Progressed penalty delta 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("000660")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=50)

    result = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, "2023-11-30")
    h3 = result.horizon_3m

    curr_res = result.observations[-1].score_result
    # 3개월 전 observation: index -4 (offset 3)
    prior_res = result.observations[-4].score_result

    assert h3.base_score_delta == round(curr_res.base_score - prior_res.base_score, 4)
    assert h3.transition_score_delta == round(
        curr_res.transition_score - prior_res.transition_score, 4
    )
    assert h3.core_score_delta == round(curr_res.core_score - prior_res.core_score, 4)
    assert h3.alignment_bonus_delta == round(
        curr_res.alignment_bonus - prior_res.alignment_bonus, 4
    )
    assert h3.progressed_penalty_delta == round(
        curr_res.progressed_penalty - prior_res.progressed_penalty, 4
    )
    assert (
        h3.progressed_evidence_count_delta
        == curr_res.progressed_evidence_count - prior_res.progressed_evidence_count
    )


def test_history_readiness_thresholds_36_37_39_42():
    """36M(Current만), 37M(1M), 39M(3M), 42M(6M) 히스토리 요구조건 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=60)

    monthly_all = to_monthly(daily)

    def _slice_completed_months(n_months: int) -> pd.DataFrame:
        # n_months + 1 calendar months 슬라이스 후 마지막 월봉을 미완성(월중)으로 만들어 n_months completed bars 확보
        m_slice = monthly_all.tail(n_months + 1)
        start = m_slice.index[0] - pd.offsets.MonthBegin(1)
        end = m_slice.index[-1]
        return daily.loc[(daily.index >= start) & (daily.index <= end)]

    # 1. 36 completed months: Current Score ready, 1M not ready
    d_36 = _slice_completed_months(36)
    res_36 = compute_pattern_a_score_momentum(
        "005930", "삼성전자", d_36, d_36.index.max().strftime("%Y-%m-%d")
    )
    assert res_36.observations[-1].score is not None
    assert res_36.horizon_1m.ready is False
    assert res_36.horizon_3m.ready is False
    assert res_36.horizon_6m.ready is False

    # 2. 37 completed months: 1M ready, 3M/6M not ready
    d_37 = _slice_completed_months(37)
    res_37 = compute_pattern_a_score_momentum(
        "005930", "삼성전자", d_37, d_37.index.max().strftime("%Y-%m-%d")
    )
    assert res_37.horizon_1m.ready is True
    assert res_37.horizon_3m.ready is False
    assert res_37.horizon_6m.ready is False

    # 3. 39 completed months: 1M & 3M ready, 6M not ready
    d_39 = _slice_completed_months(39)
    res_39 = compute_pattern_a_score_momentum(
        "005930", "삼성전자", d_39, d_39.index.max().strftime("%Y-%m-%d")
    )
    assert res_39.horizon_1m.ready is True
    assert res_39.horizon_3m.ready is True
    assert res_39.horizon_6m.ready is False

    # 4. 42 completed months: 1M, 3M, 6M 모두 ready
    d_42 = _slice_completed_months(42)
    res_42 = compute_pattern_a_score_momentum(
        "005930", "삼성전자", d_42, d_42.index.max().strftime("%Y-%m-%d")
    )
    assert res_42.horizon_1m.ready is True
    assert res_42.horizon_3m.ready is True
    assert res_42.horizon_6m.ready is True


def test_partial_horizon_readiness():
    """39개월 히스토리 종목에서 6M horizon만 unavailable로 표시되고 전체 결과가 정상 반환됨을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=60)

    monthly_all = to_monthly(daily)
    m_39 = monthly_all.tail(40)
    d_39 = daily.loc[
        (daily.index >= m_39.index[0] - pd.offsets.MonthBegin(1)) & (daily.index <= m_39.index[-1])
    ]

    res = compute_pattern_a_score_momentum(
        "005930", "삼성전자", d_39, d_39.index.max().strftime("%Y-%m-%d")
    )
    assert res.available_horizons == (1, 3)
    assert res.missing_horizons == (6,)
    assert res.horizon_1m.ready is True
    assert res.horizon_3m.ready is True
    assert res.horizon_6m.ready is False
    assert res.horizon_6m.score_delta is None
    assert "INSUFFICIENT_HISTORY_6M" in res.horizon_6m.reason_codes


def test_incomplete_current_month_cadence():
    """월 중순(미완성 월봉) 요청 시 직전 완성 월봉을 Anchor로 삼아 Completed Monthly Cadence를 유지함을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("000660")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=50)

    # 2023-11-15 (11월 중순 미완성 봉)
    res = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, "2023-11-15")

    # Momentum latest anchor는 2023-10-31 완성 월봉이어야 함
    assert res.momentum_anchor == pd.Timestamp("2023-10-31")
    assert res.observations[-1].anchor_date == pd.Timestamp("2023-10-31")
    assert res.horizon_1m.current_anchor == pd.Timestamp("2023-10-31")
    assert res.horizon_1m.prior_anchor == pd.Timestamp("2023-09-30")


def test_no_lookahead_contamination():
    """as_of 이후 미래 일봉을 추가하거나 조작해도 과거 시점 Score Momentum 결과가 동일함을 검증."""
    daily_base = _create_mock_daily(months=50, start_date="2020-01-01")
    as_of = "2023-06-30"

    res1 = compute_pattern_a_score_momentum("005930", "삼성전자", daily_base, as_of)

    # 미래 데이터 조작 (2023-07-01 이후 가격 폭등/폭락 조작)
    daily_mutated = daily_base.copy()
    future_mask = daily_mutated.index > "2023-06-30"
    daily_mutated.loc[future_mask, "close"] *= 10.0

    res2 = compute_pattern_a_score_momentum("005930", "삼성전자", daily_mutated, as_of)

    assert res1.horizon_1m == res2.horizon_1m
    assert res1.horizon_3m == res2.horizon_3m
    assert res1.horizon_6m == res2.horizon_6m
    assert res1.monthly_score_deltas == res2.monthly_score_deltas


def test_determinism():
    """동일 입력에 대해 100% 결정론적 일치 검증."""
    daily = _create_mock_daily(months=50)
    as_of = "2023-10-31"

    res1 = compute_pattern_a_score_momentum("005930", "삼성전자", daily, as_of)
    res2 = compute_pattern_a_score_momentum("005930", "삼성전자", daily, as_of)

    assert res1.ticker == res2.ticker
    assert res1.name == res2.name
    assert res1.requested_as_of == res2.requested_as_of
    assert res1.momentum_anchor == res2.momentum_anchor
    assert res1.available_horizons == res2.available_horizons
    assert res1.missing_horizons == res2.missing_horizons
    assert res1.horizon_1m == res2.horizon_1m
    assert res1.horizon_3m == res2.horizon_3m
    assert res1.horizon_6m == res2.horizon_6m
    assert res1.monthly_score_deltas == res2.monthly_score_deltas

    # Observation sequence semantic 일치 검증
    assert len(res1.observations) == len(res2.observations)
    for o1, o2 in zip(res1.observations, res2.observations):
        assert o1.anchor_date == o2.anchor_date
        assert o1.effective_as_of == o2.effective_as_of
        assert o1.score == o2.score


def test_score_stage_legacy_isolation():
    """Momentum 계산이 score_result.stage(legacy heuristic)에 일체 의존하지 않음을 확인."""
    daily = _create_mock_daily(months=50)
    result = compute_pattern_a_score_momentum("005930", "삼성전자", daily, "2023-10-31")

    # Horizon 결과 및 Result 자체에 stage 관련 필드가 존재하지 않음
    assert not hasattr(result.horizon_1m, "stage")
    assert not hasattr(result.horizon_1m, "stage_delta")
    assert not hasattr(result, "stage")
