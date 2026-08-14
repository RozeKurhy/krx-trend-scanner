import dataclasses
import math
from types import SimpleNamespace

import pytest

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score import (
    ALIGNMENT_BONUS,
    ALIGNMENT_BONUS_WEAK_CORE,
    ALIGNMENT_CORE_STRONG_THRESHOLD,
    CONFIRMATION_MAX,
    PatternAResult,
    _harmonic_mean,
    _piecewise_linear,
    score_pattern_a,
)

_ALL_BASE_MAX = {"range_36m": 0.5, "avg_price_change_12m": 0.05, "ma_spread": 0.05}
_ALL_TRANSITION_MAX = {"ma24_slope": 0.20, "weekly_ma12_slope": 0.20, "ma24_slope_acceleration": 0.10}
_NEUTRAL_RANGE_POSITION = {"range_position": 0.3}


def _features(**overrides) -> SimpleNamespace:
    base = {
        "range_36m": float("nan"),
        "avg_price_change_12m": float("nan"),
        "ma_spread": float("nan"),
        "ma24_slope": float("nan"),
        "weekly_ma12_slope": float("nan"),
        "ma24_slope_acceleration": float("nan"),
        "range_position": float("nan"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- 순수 math helper ---


def test_piecewise_linear_clips_outside_range_and_interpolates_inside():
    points = ((0.0, 100.0), (1.0, 0.0))
    assert _piecewise_linear(-5.0, points) == 100.0
    assert _piecewise_linear(5.0, points) == 0.0
    assert _piecewise_linear(0.5, points) == 50.0


def test_harmonic_mean_balances_two_axes():
    assert _harmonic_mean(90.0, 90.0) == 90.0
    # 한쪽이 낮으면 평균보다 훨씬 낮게 나온다(단순 산술평균 60이 아님)
    assert _harmonic_mean(90.0, 30.0) == 45.0
    assert _harmonic_mean(30.0, 90.0) == 45.0


def test_harmonic_mean_handles_zero_division_safely():
    assert _harmonic_mean(0.0, 0.0) == 0.0
    assert _harmonic_mean(0.0, 100.0) == 0.0
    assert not math.isnan(_harmonic_mean(0.0, 0.0))


def test_harmonic_mean_returns_none_when_either_axis_is_none():
    assert _harmonic_mean(None, 50.0) is None
    assert _harmonic_mean(50.0, None) is None


# --- score_pattern_a: 정상 경로 ---


def test_final_score_clips_to_100_even_when_raw_sum_exceeds_it():
    features = _features(**_ALL_BASE_MAX, **_ALL_TRANSITION_MAX, **_NEUTRAL_RANGE_POSITION)
    result = score_pattern_a(features)

    assert result.base_score == 100.0
    assert result.transition_score == 100.0
    assert result.balanced_core_score == 100.0
    assert result.alignment_bonus == 8.0  # 전부 양수 -> transition_alignment 충족
    assert result.pattern_a_score == 100.0  # 108이 아니라 100으로 clip
    assert result.flags["transition_alignment"] is True


def test_progressed_penalty_absent_for_early_candidate_with_one_evidence_signal():
    # ma24_slope만 progressed 기준(>=0.10)을 넘고 나머지 evidence는 없음 -> evidence_count=1 -> penalty 0
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.11,
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.progressed_evidence_count == 1
    assert result.progressed_penalty == 0.0


def test_strong_transition_with_weak_base_does_not_score_high():
    # SK하이닉스형 실패 모드: Transition은 완전히 강하지만 Base가 완전히 무너진 경우
    features = _features(
        range_36m=3.0,
        avg_price_change_12m=1.0,
        ma_spread=1.0,
        ma24_slope=0.20,
        weekly_ma12_slope=0.20,
        ma24_slope_acceleration=0.10,
        range_position=0.9,
    )
    result = score_pattern_a(features)

    assert result.base_score == 0.0
    assert result.transition_score == 100.0
    assert result.balanced_core_score == 0.0  # harmonic mean이 낮은 쪽에 지배됨
    assert result.progressed_evidence_count == 5  # 5개 신호 전부 progressed 기준 초과
    assert result.progressed_penalty == 35.0
    assert result.pattern_a_score == 0.0
    assert result.flags["already_progressed"] is True


def test_strong_base_with_weak_transition_does_not_score_high():
    features = _features(
        range_36m=0.5,
        avg_price_change_12m=0.05,
        ma_spread=0.05,
        ma24_slope=-0.10,
        weekly_ma12_slope=-0.05,
        ma24_slope_acceleration=-0.05,
        range_position=0.3,
    )
    result = score_pattern_a(features)

    assert result.base_score == 100.0
    assert result.transition_score < 20.0
    assert result.pattern_a_score < 30.0
    assert result.flags["transition_alignment"] is False


# --- score_pattern_a: 결측 처리 ---


def test_missing_core_feature_marks_insufficient_data():
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        # ma24_slope 결측
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.flags["insufficient_data"] is True
    assert result.pattern_a_score is None
    assert result.stage is None
    assert "ma24_slope" in result.transition_missing_features


def test_missing_non_core_base_feature_still_produces_a_score_via_renormalized_weights():
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        # ma_spread 결측
        ma24_slope=0.05,
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.flags["insufficient_data"] is False
    assert result.pattern_a_score is not None
    assert "ma_spread" in result.base_missing_features
    assert result.base_score == pytest.approx(100.0)  # 남은 두 Feature 모두 만점 구간이라 재정규화해도 100


def test_missing_range_36m_marks_insufficient_data_even_with_other_base_features_valid():
    # range_36m은 required anchor라서 avg_price_change_12m/ma_spread가 멀쩡해도
    # 재정규화로 대신할 수 없다.
    features = _features(
        # range_36m 결측
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.05,
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.flags["insufficient_data"] is True
    assert result.pattern_a_score is None
    assert result.stage is None
    assert "range_36m" in result.base_missing_features


def test_all_base_features_missing_marks_insufficient_data():
    features = _features(
        ma24_slope=0.05,
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.base_score is None
    assert result.flags["insufficient_data"] is True
    assert result.pattern_a_score is None


# --- PatternAResult 구조 ---


def test_pattern_a_result_has_new_three_axis_fields():
    field_names = {f.name for f in dataclasses.fields(PatternAResult)}
    expected = {
        "base_score",
        "base_valid_features",
        "base_missing_features",
        "transition_score",
        "transition_valid_features",
        "transition_missing_features",
        "balanced_core_score",
        "alignment_bonus",
        "progressed_penalty",
        "progressed_evidence_count",
        "pattern_a_score",
        "stage",
        "flags",
        "feature_snapshot",
    }
    assert expected <= field_names
    # 폐기된 5영역 구조 필드가 남아있지 않아야 한다
    assert "low_score" not in field_names
    assert "volatility_score" not in field_names
    assert "breakout_score" not in field_names
    assert "rejected" not in field_names


def test_stage_is_progressed_when_evidence_count_reaches_three():
    features = _features(
        range_36m=3.0,
        avg_price_change_12m=1.0,
        ma_spread=1.0,
        ma24_slope=0.20,
        weekly_ma12_slope=0.20,
        ma24_slope_acceleration=0.10,
        range_position=0.9,
    )
    result = score_pattern_a(features)
    assert result.stage is PatternAStage.PROGRESSED


# --- Transition Score v0.2: Core + Confirmation (재리뷰 후속) ---


def test_weak_core_with_strong_support_cannot_score_high_via_supporting_alone():
    # SKC 실패 재현 테스트: ma24_slope는 약한 음수(core_score < 50)인데
    # weekly/acceleration은 최대치. v0.1이었다면 Supporting 40% 비중만으로
    # transition_score가 60점대까지 올라갔지만, v0.2는 confirmation_gate가
    # 0이라 Supporting이 아무리 강해도 transition_score는 core_score 그대로다.
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=-0.01,
        weekly_ma12_slope=0.20,
        ma24_slope_acceleration=0.10,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.core_score < 50.0
    assert result.support_score == 100.0
    assert result.confirmation_bonus == 0.0
    assert result.transition_score == pytest.approx(result.core_score)
    assert result.transition_score <= 40.0


def test_strong_core_with_strong_support_allows_high_transition():
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.15,  # core_score = 100
        weekly_ma12_slope=0.20,
        ma24_slope_acceleration=0.10,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.core_score == 100.0
    assert result.support_score == 100.0
    assert result.confirmation_bonus > 0.0
    assert result.transition_score == 100.0  # 100 + bonus를 100으로 clip


def test_mid_core_with_strong_support_gives_partial_confirmation():
    # core_score가 confirmation gate 구간(50~80) 안에 있으면 confirmation_bonus가
    # 0도 최대치도 아닌 부분적인 값이어야 한다.
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.02,  # core_score = 66 (50~90 구간 보간)
        weekly_ma12_slope=0.20,
        ma24_slope_acceleration=0.10,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert 50.0 < result.core_score < 80.0
    assert 0.0 < result.confirmation_bonus < CONFIRMATION_MAX
    assert result.core_score < result.transition_score < result.core_score + CONFIRMATION_MAX


def test_alignment_with_weak_core_does_not_get_full_bonus():
    # 정렬 조건(weekly/ma24/accel 전부 양수)은 만족하지만 core_score가
    # ALIGNMENT_CORE_STRONG_THRESHOLD 미만인 LG형 사례 — 축소된 보너스만 받는다.
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.005,  # core_score < 60
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.01,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.flags["transition_alignment"] is True
    assert result.core_score < ALIGNMENT_CORE_STRONG_THRESHOLD
    assert result.alignment_bonus == ALIGNMENT_BONUS_WEAK_CORE
    assert result.alignment_bonus < ALIGNMENT_BONUS


def test_alignment_with_strong_core_gets_full_bonus():
    features = _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.06,  # core_score >= 60
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.01,
        range_position=0.5,
    )
    result = score_pattern_a(features)

    assert result.flags["transition_alignment"] is True
    assert result.core_score >= ALIGNMENT_CORE_STRONG_THRESHOLD
    assert result.alignment_bonus == ALIGNMENT_BONUS


def test_pattern_a_result_has_core_and_support_diagnostic_fields():
    field_names = {f.name for f in dataclasses.fields(PatternAResult)}
    assert {"core_score", "support_score", "confirmation_bonus"} <= field_names
