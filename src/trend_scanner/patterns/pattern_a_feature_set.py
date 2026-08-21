"""Pattern A v0.1 Feature Set Freeze.

Feature Validation -> Historical Snapshot -> Holdout -> Negative Control ->
Outcome Audit -> Base/Expansion Validation까지 검증한 결과를 바탕으로,
Pattern A가 실제로 사용할 Feature와 그 역할/축을 확정한다. 자세한 근거는
docs/patterns/pattern_a/archive/legacy_full_history.md의 "Validation Evidence"/"Base / Expansion
Validation" 표를 참고한다.

이 모듈은 분류만 담는다. Score 계산, 가중치, threshold와는 아직 연결하지
않는다(`evaluate_pattern_a`는 여전히 미구현). `PatternAStage`도 이름만
정의한 enum이고, 자동 분류 로직은 없다.

여기 나온 Feature 이름은 전부 `trend_scanner.validation.feature_report.
FeatureRow`의 실제 필드명과 일치해야 한다(테스트로 검증).

Role과 Axis는 서로 다른 질문에 답한다.

* FeatureRole: Score Design에서 이 Feature를 어떻게 쓸 것인가(핵심/보조/
  참고/진단용/미사용).
* FeatureAxis: Pattern A의 어느 축(Base/Transition/Stage) 개념에 속하는가.

Diagnostic/Drop Feature에는 Axis를 부여하지 않는다 — Axis는 Score Design에
실제로 쓰일 축 구조(BASE/TRANSITION/STAGE)에만 매핑한다(과도한 프레임워크
방지).
"""

from __future__ import annotations

from enum import Enum


class FeatureRole(str, Enum):
    """Pattern A Feature Set 안에서 각 Feature가 맡는 역할."""

    CORE = "core"
    SUPPORTING = "supporting"
    CONTEXT = "context"
    DIAGNOSTIC = "diagnostic"
    DROP = "drop"


class FeatureAxis(str, Enum):
    """Pattern A가 재설계한 3축 구조. CONTEXT Feature를 어느 축 개념으로
    해석할지 구분한다(Transition Feature도 축은 있지만 Role이 이미
    CORE/SUPPORTING이라 굳이 다시 나눌 필요는 없다 — 아래 FEATURE_AXES에서
    Transition Feature도 포함해서 매핑한다)."""

    BASE = "base"
    TRANSITION = "transition"
    STAGE = "stage"


class PatternAStage(str, Enum):
    """Pattern A가 구분하려는 종목 상태. 자동 분류 threshold는 미구현."""

    BASE = "base"
    TRANSITION = "transition"
    EARLY_TREND = "early_trend"
    PROGRESSED = "progressed"
    WEAK = "weak"


# --- Axis 2: Trend Transition ---

# Core: Pattern A 판단의 중심. ma24_slope만 해당한다 — weekly/acceleration은
# 단독으로는 negative_control에서도 흔하게 양수라 Core로 승격하지 않는다.
TRANSITION_CORE_FEATURES: frozenset[str] = frozenset({"ma24_slope"})

# Supporting: Core 신호를 보강하지만 단독으로 Pattern A를 결정하지 않는다.
# weekly_ma12_slope/ma24_slope_acceleration은 ma24_slope와 결합됐을 때만
# (Combination D/E) early_trend/negative_control 구분력이 확인됐다.
TRANSITION_SUPPORTING_FEATURES: frozenset[str] = frozenset(
    {"weekly_ma12_slope", "ma24_slope_acceleration"}
)

# --- Axis 1: Long-Term Structure / Base Context ---

# Base/Expansion Validation v0.1(scripts/base_expansion_validate.py,
# docs/patterns/pattern_a/archive/legacy_full_history.md 참고)로 재검증됨. holdout pre_breakout/
# early_trend/trend_progressed 3단계 + confirmed_negative 4그룹 비교 결과:
#
# * range_36m: trend_progressed 최소값(1.2614)이 나머지 세 그룹의 최댓값
#   (confirmed_negative 1.1767)보다 커서 4그룹을 완전히 분리한다 — 가장
#   깨끗한 Already Progressed 판별 신호.
# * avg_price_change_12m: 중앙값 차이가 매우 크다(progressed 0.7251 vs
#   나머지 -0.12~0.05). 다만 confirmed_negative 1건(고려아연 0.3117)이
#   progressed 최솟값(현대차 0.2220)보다 커서 완전히 깨끗하진 않다.
# * ma_spread: 방향은 있으나(progressed 중앙값 0.2777이 가장 높음) 노이즈가
#   크다 — pre_breakout(0.0774)이 early_trend(0.0627)보다 오히려 높고,
#   confirmed_negative 1건(롯데케미칼 0.2626)이 progressed 최솟값(0.1828)
#   보다 크다. 그래도 극단값에서는 방향이 유지돼 Context로 남긴다.
# * range_24m: range_36m과 순위가 사실상 동일(인접 종목 1쌍만 뒤바뀜)하고
#   4그룹 분리력도 비슷해 range_36m과 중복 정보 — Diagnostic으로 내림.
# * range_12m: trend_progressed 최솟값(0.9097)이 confirmed_negative
#   최댓값(1.0693)보다 낮아 range 계열 중 유일하게 분리에 실패한다(오히려
#   노이즈 추가) — Diagnostic으로 내림.
BASE_CONTEXT_FEATURES: frozenset[str] = frozenset(
    {"range_36m", "avg_price_change_12m", "ma_spread"}
)

# --- Axis 3: Stage / Breakout Context ---

# 좋고 나쁨 점수가 아니라 현재 종목이 어느 단계인지 판별하는 참고 Feature.
# 전부 range 내 "위치"(0~1 정규화)를 나타낸다는 공통점이 있다 — Base
# Context의 "폭/변화율" Feature와는 단위가 다르므로 같은 축에 섞지 않는다.
STAGE_CONTEXT_FEATURES: frozenset[str] = frozenset(
    {"range_position", "range_position_52w", "distance_to_resistance"}
)

# --- Diagnostic only: 리포트에는 남기지만 Score에 직접 넣지 않는다 ---

# ma_spread_ratio/atr_ratio/compression_ratio: 값 범위가 그룹 간 크게
# 겹치거나 가설이 재현되지 않았다(Feature Set Freeze v0.1). range_24m/
# range_12m: Base/Expansion Validation에서 각각 "중복"과 "분리력 부족"으로
# 내려왔다(위 BASE_CONTEXT_FEATURES 주석 참고).
DIAGNOSTIC_FEATURES: frozenset[str] = frozenset(
    {
        "ma_spread_ratio",
        "atr_ratio",
        "compression_ratio",
        "range_24m",
        "range_12m",
    }
)

# --- Drop: v0.1에서 사용하지 않는다 ---

# exploration/holdout/negative_control 전부에서 값이 미미하고(±0.001)
# 상태 구분력이 없었다.
DROPPED_FEATURES: frozenset[str] = frozenset({"pivot_low_slope"})

FEATURE_ROLES: dict[str, FeatureRole] = {
    **{name: FeatureRole.CORE for name in TRANSITION_CORE_FEATURES},
    **{name: FeatureRole.SUPPORTING for name in TRANSITION_SUPPORTING_FEATURES},
    **{name: FeatureRole.CONTEXT for name in BASE_CONTEXT_FEATURES},
    **{name: FeatureRole.CONTEXT for name in STAGE_CONTEXT_FEATURES},
    **{name: FeatureRole.DIAGNOSTIC for name in DIAGNOSTIC_FEATURES},
    **{name: FeatureRole.DROP for name in DROPPED_FEATURES},
}

FEATURE_AXES: dict[str, FeatureAxis] = {
    **{name: FeatureAxis.TRANSITION for name in TRANSITION_CORE_FEATURES},
    **{name: FeatureAxis.TRANSITION for name in TRANSITION_SUPPORTING_FEATURES},
    **{name: FeatureAxis.BASE for name in BASE_CONTEXT_FEATURES},
    **{name: FeatureAxis.STAGE for name in STAGE_CONTEXT_FEATURES},
}

# Pattern A 후보로 명시적으로 검토한 Feature 전체 목록(ground truth,
# 파생하지 않고 직접 나열한다 — FEATURE_ROLES의 union으로 만들면 "role
# 분류가 안 된 scope 항목"을 test가 절대 잡아낼 수 없다). FeatureRow의
# 나머지 필드(ma6/ma12/ma24 원시 레벨, volume/trading_value 참고 지표,
# pivot 상세 등)는 애초 Pattern A 후보로 논의된 적이 없어 여기 포함하지
# 않는다.
PATTERN_A_FEATURE_SCOPE: frozenset[str] = frozenset(
    {
        "ma24_slope",
        "weekly_ma12_slope",
        "ma24_slope_acceleration",
        "range_36m",
        "avg_price_change_12m",
        "ma_spread",
        "range_position",
        "range_position_52w",
        "distance_to_resistance",
        "compression_ratio",
        "atr_ratio",
        "ma_spread_ratio",
        "range_24m",
        "range_12m",
        "pivot_low_slope",
    }
)

# Already Progressed / Expansion State 판별 후보(threshold 미확정). "좋은
# 상승 추세"를 무조건 높게 평가하지 않기 위해, 이미 너무 진행된 종목을
# 걸러낼 때 볼 Feature만 정리한다 — 어떤 Feature를 볼지만 확정하고, 값이
# 얼마 이상이어야 "이미 진행됨"인지는 Score Design 단계에서 정한다.
# Base/Expansion Validation으로 range_36m/avg_price_change_12m은 강하게,
# ma_spread는 노이즈가 있지만 방향성 있게 뒷받침됐다.
ALREADY_PROGRESSED_CANDIDATE_SIGNALS: tuple[str, ...] = (
    "ma24_slope",
    "ma_spread",
    "range_36m",
    "avg_price_change_12m",
    "range_position",
)
