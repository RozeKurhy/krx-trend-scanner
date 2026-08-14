"""Pattern A v0.1 Feature Set Freeze.

Feature Validation -> Historical Snapshot -> Holdout -> Negative Control ->
Outcome Audit까지 검증한 결과를 바탕으로, Pattern A가 실제로 사용할
Feature와 그 역할을 확정한다. 자세한 근거는 docs/patterns/pattern_a.md의
"Validation Evidence" 표를 참고한다.

이 모듈은 분류만 담는다. Score 계산, 가중치, threshold와는 아직 연결하지
않는다(`evaluate_pattern_a`는 여전히 미구현). `PatternAStage`도 이름만
정의한 enum이고, 자동 분류 로직은 없다.

여기 나온 Feature 이름은 전부 `trend_scanner.validation.feature_report.
FeatureRow`의 실제 필드명과 일치해야 한다(테스트로 검증).
"""

from __future__ import annotations

from enum import Enum


class FeatureRole(str, Enum):
    """Pattern A Feature Set 안에서 각 Feature가 맡는 역할."""

    CORE = "core"
    SUPPORTING = "supporting"
    STAGE = "stage"
    DIAGNOSTIC = "diagnostic"
    DROP = "drop"


class PatternAStage(str, Enum):
    """Pattern A가 구분하려는 종목 상태. 자동 분류 threshold는 미구현."""

    BASE = "base"
    TRANSITION = "transition"
    EARLY_TREND = "early_trend"
    PROGRESSED = "progressed"
    WEAK = "weak"


# Core: Pattern A 판단의 중심. ma24_slope만 해당한다 — weekly/acceleration은
# 단독으로는 negative_control에서도 흔하게 양수라 Core로 승격하지 않는다.
CORE_FEATURES: frozenset[str] = frozenset({"ma24_slope"})

# Supporting: Core 신호를 보강하지만 단독으로 Pattern A를 결정하지 않는다.
# weekly_ma12_slope/ma24_slope_acceleration은 ma24_slope와 결합됐을 때만
# (Combination D/E) early_trend/negative_control 구분력이 확인됐다.
SUPPORTING_FEATURES: frozenset[str] = frozenset(
    {"weekly_ma12_slope", "ma24_slope_acceleration"}
)

# Stage/Context: 좋고 나쁨 점수가 아니라 현재 종목이 어느 단계인지(Base/
# Transition/Early Trend/Progressed) 판별하는 참고 Feature. range_position류는
# breakout 단계 판별, range_36m/ma_spread류는 Base/Expansion Context 판별에
# 쓴다. ma_spread는 "수렴 정도"로는 약했지만(Diagnostic 사유는 spread_ratio만
# 해당), "확장 정도"로는 이미 진행된 종목을 가려내는 데 참고가 된다(negative
# 중앙값 0.122가 positive pre_breakout 0.077보다 넓고 progressed는
# 0.22~0.34로 더 넓다) — ALREADY_PROGRESSED_CANDIDATE_SIGNALS에도 포함.
STAGE_FEATURES: frozenset[str] = frozenset(
    {
        "range_position",
        "range_position_52w",
        "distance_to_resistance",
        "range_36m",
        "range_24m",
        "range_12m",
        "avg_price_change_12m",
        "ma_spread",
    }
)

# Diagnostic only: 리포트에는 남기지만 Score에 직접 넣지 않는다. 값 범위가
# 그룹 간 크게 겹치거나(ma_spread_ratio) 가설이 재현되지 않았다
# (compression_ratio, atr_ratio).
DIAGNOSTIC_FEATURES: frozenset[str] = frozenset(
    {"ma_spread_ratio", "atr_ratio", "compression_ratio"}
)

# Drop: v0.1에서 사용하지 않는다. exploration/holdout/negative_control
# 전부에서 값이 미미하고(±0.001) 상태 구분력이 없었다.
DROPPED_FEATURES: frozenset[str] = frozenset({"pivot_low_slope"})

FEATURE_ROLES: dict[str, FeatureRole] = {
    **{name: FeatureRole.CORE for name in CORE_FEATURES},
    **{name: FeatureRole.SUPPORTING for name in SUPPORTING_FEATURES},
    **{name: FeatureRole.STAGE for name in STAGE_FEATURES},
    **{name: FeatureRole.DIAGNOSTIC for name in DIAGNOSTIC_FEATURES},
    **{name: FeatureRole.DROP for name in DROPPED_FEATURES},
}

# Already Progressed / Expansion State 판별 후보(threshold 미확정). "좋은
# 상승 추세"를 무조건 높게 평가하지 않기 위해, 이미 너무 진행된 종목을
# 걸러낼 때 볼 Feature만 정리한다 — 어떤 Feature를 볼지만 확정하고, 값이
# 얼마 이상이어야 "이미 진행됨"인지는 Score Design 단계에서 정한다.
ALREADY_PROGRESSED_CANDIDATE_SIGNALS: tuple[str, ...] = (
    "ma24_slope",
    "ma_spread",
    "range_36m",
    "avg_price_change_12m",
    "range_position",
)
