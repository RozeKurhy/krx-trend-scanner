"""Pattern A v0.1 Score Design.

Feature Set Freeze v0.1(pattern_a_feature_set.py, docs/patterns/pattern_a.md)
로 확정한 Feature Set을 이용해 Pattern A Score의 구조를 정의한다.

핵심 철학:

    Base / Long-Term Structure  +  Trend Transition

둘 다 있어야 높은 점수를 받는다. Base 40점 + Transition 60점처럼 단순
가산식을 쓰면 Base가 거의 없어도 Transition만 강하면 높은 점수가 나올 수
있다(SK하이닉스 같은 이미 진행된 종목을 다시 높게 평가하는 문제 재발).
그래서 두 축을 합칠 때 harmonic mean을 쓴다 — 한쪽이 낮으면 전체 점수가
크게 낮아진다.

    balanced_core = harmonic_mean(base_score, transition_score)
    pattern_a_score = clip(balanced_core + alignment_bonus - progressed_penalty, 0, 100)

Already Progressed Penalty는 Base Score와 같은 원본 값을 다시 감점하는
double counting을 피하기 위해, 개별 Feature 하나가 아니라 "여러 신호가
동시에 진행됨을 가리킬 때만" 적용하는 composite evidence count로 만든다
(progressed_evidence_count, 아래 참고).

threshold(soft piecewise breakpoint)는 전부 관찰된 분포를 참고한 "설명
가능한 반올림 숫자"다. 미래 수익률 최적화, grid search, 그룹 분리도
최대화로 고른 값이 아니다 — 자세한 근거는 docs/patterns/pattern_a.md의
"Score Design" 절 참고.

이 모듈은 FeatureRow(또는 같은 속성을 가진 임의 객체)를 받아 순수하게
점수만 계산한다. 종목 신원은 모른다(models/score.py의 ScanResult가 합친다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.feature_report import FeatureRow


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _piecewise_linear(value: float, points: tuple[tuple[float, float], ...]) -> float:
    """points는 (x, y) 쌍을 x 오름차순으로 정렬한 것. 범위 밖 값은 양 끝 y로
    고정한다(clip). 구간 안에서는 선형 보간한다."""
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= value <= x1:
            frac = (value - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]  # pragma: no cover - points가 정렬돼 있으면 도달 안 함


# --- Base Score (Axis 1: Long-Term Structure / Base Context) ---
#
# "얼마나 압축됐는가"가 아니라 "아직 장기적으로 과도하게 확장되지 않았는가"를
# 본다. 값이 작거나 중간이면 Base 적합도가 높고, 매우 크면 낮다(단조 감소).
# breakpoint는 Base/Expansion Validation(docs/patterns/pattern_a.md)에서
# 관찰한 4그룹(holdout pre/early/progressed, confirmed_negative) 분포를
# 참고한 반올림 숫자다 — 관측된 1.1767/1.2614 사이 빈틈을 그대로 쓰지 않고
# 1.2라는 라운드 넘버를 썼다(이 값 하나가 단독으로 progressed를 가르지
# 않는다 — 연속 곡선이 완만하게 낮추고, Already Progressed Penalty는 이
# 값 포함 5개 신호가 동시에 나타날 때만 추가로 붙는다).
RANGE_36M_POINTS: tuple[tuple[float, float], ...] = ((0.6, 100.0), (1.2, 60.0), (2.0, 0.0))

# avg_price_change_12m: 낮거나 완만한 상승은 Base로 허용하고, 매우 크면
# Already Progressed 쪽으로 본다. 절대 양수라는 이유만으로 감점하지 않는다
# (early trend에서도 가격 중심이 오르는 건 정상).
AVG_PRICE_CHANGE_12M_POINTS: tuple[tuple[float, float], ...] = ((0.10, 100.0), (0.30, 50.0), (0.60, 0.0))

# ma_spread: 단독 분리력이 약하고 노이즈가 크므로(Low-Medium 확신도) 완만한
# 보조 지표로만 쓴다. 좁다고 무조건 좋은 Base로 보지 않고, 매우 넓을 때만
# 확장 가능성을 보조적으로 반영한다.
MA_SPREAD_POINTS: tuple[tuple[float, float], ...] = ((0.10, 100.0), (0.25, 50.0), (0.40, 0.0))

# range_36m(High) > avg_price_change_12m(Medium) > ma_spread(Low-Medium)
# 검증 근거 강도 순으로 비중을 뒀다(docs/patterns/pattern_a.md 권장 범위:
# 50~60% / 25~35% / 10~20%).
BASE_WEIGHTS: dict[str, float] = {
    "range_36m": 0.55,
    "avg_price_change_12m": 0.30,
    "ma_spread": 0.15,
}

BASE_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "range_36m": RANGE_36M_POINTS,
    "avg_price_change_12m": AVG_PRICE_CHANGE_12M_POINTS,
    "ma_spread": MA_SPREAD_POINTS,
}


# --- Transition Score (Axis 2: Trend Transition) ---
#
# ma24_slope는 hard binary(> 0 이면 만점, <= 0 이면 0점)로 만들지 않는다.
# Pattern A는 상승 "전환 중"도 찾고 싶기 때문이다. 강한 음수는 낮은 점수,
# 0 근처는 중간(negative_control도 0 근처에 몰려 있어 "가능성은 있으나
# 미확인" 정도로만 취급), 완만한 양수부터 빠르게 올라간다. 지나치게 큰
# 양수를 여기서 다시 깎지 않는다("너무 크면 나쁘다" 이중 역할 금지) —
# 과도한 상승은 Already Progressed Penalty가 별도로 담당한다.
MA24_SLOPE_POINTS: tuple[tuple[float, float], ...] = (
    (-0.05, 0.0),
    (0.00, 50.0),
    (0.05, 90.0),
    (0.15, 100.0),
)

# weekly_ma12_slope: 단독 양수가 negative_control에서도 흔했으므로 큰
# 독립 점수를 주지 않는다(완만한 형태 + 비중 자체도 작음).
WEEKLY_MA12_SLOPE_POINTS: tuple[tuple[float, float], ...] = ((0.00, 20.0), (0.15, 100.0))

# ma24_slope_acceleration: 단독 positive가 false positive에서도 많았으므로
# Supporting 역할만 한다.
MA24_SLOPE_ACCELERATION_POINTS: tuple[tuple[float, float], ...] = ((0.00, 30.0), (0.05, 100.0))

TRANSITION_WEIGHTS: dict[str, float] = {
    "ma24_slope": 0.60,
    "weekly_ma12_slope": 0.20,
    "ma24_slope_acceleration": 0.20,
}

TRANSITION_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "ma24_slope": MA24_SLOPE_POINTS,
    "weekly_ma12_slope": WEEKLY_MA12_SLOPE_POINTS,
    "ma24_slope_acceleration": MA24_SLOPE_ACCELERATION_POINTS,
}


@dataclass
class ComponentScore:
    """축 하나(Base 또는 Transition)의 가중합 결과. 결측 Feature는 가중치를
    재정규화해서 계산하고, 어떤 Feature도 유효하지 않으면 score=None이다."""

    score: float | None
    valid_features: tuple[str, ...]
    missing_features: tuple[str, ...]


def _weighted_piecewise_score(
    feature_values: dict[str, float],
    weights: dict[str, float],
    points: dict[str, tuple[tuple[float, float], ...]],
) -> ComponentScore:
    valid: list[str] = []
    missing: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for name, weight in weights.items():
        value = feature_values.get(name)
        if _is_missing(value):
            missing.append(name)
            continue
        valid.append(name)
        weighted_sum += weight * _piecewise_linear(value, points[name])
        weight_total += weight

    if weight_total == 0.0:
        return ComponentScore(None, tuple(valid), tuple(missing))
    return ComponentScore(weighted_sum / weight_total, tuple(valid), tuple(missing))


def _harmonic_mean(a: float | None, b: float | None) -> float | None:
    """0 division과 NaN을 안전하게 처리한 harmonic mean. 둘 중 하나가
    None(축 자체를 계산 못함)이면 None을 반환한다. 둘 다 0이거나 합이
    0이면(음수는 나오지 않으므로 사실상 둘 다 0인 경우만) 0.0을 반환한다."""
    if a is None or b is None:
        return None
    if a + b <= 0:
        return 0.0
    return 2 * a * b / (a + b)


# --- Transition Alignment ---
#
# 검증에서 가장 의미 있었던 interaction(Combination E). Hard Filter가
# 아니라 완전 충족 시에만 소규모 bonus를 준다 — 부분 충족은 bonus 없음.
# 결측 Feature가 하나라도 있으면 정렬 여부를 확인할 수 없으므로 False로
# 취급한다(미확인 == 정렬 안 됨, bonus 없음).
ALIGNMENT_BONUS = 8.0


def _transition_alignment(feature_values: dict[str, float]) -> bool:
    weekly = feature_values.get("weekly_ma12_slope")
    ma24 = feature_values.get("ma24_slope")
    accel = feature_values.get("ma24_slope_acceleration")
    if _is_missing(weekly) or _is_missing(ma24) or _is_missing(accel):
        return False
    return weekly > 0 and ma24 > 0 and accel > 0


# --- Already Progressed Penalty ---
#
# Base Score와 같은 원본 값(range_36m/avg_price_change_12m/ma_spread)을
# 다시 단독으로 감점하면 double counting이 된다. 그래서 "여러 신호가
# 동시에 강하게 나타날 때만" 붙는 composite evidence count로 만든다.
# threshold는 전부 반올림 숫자이며, range_36m=1.2는 Base Score 곡선의
# breakpoint와 같은 값을 재사용한 것 — Base Expansion Validation에서
# 관찰된 gap(1.1767~1.2614)을 정밀 조준한 게 아니라, 그 곡선을 그대로
# "이미 확장 신호로 셀 만큼 큰 값"의 기준으로 재사용했을 뿐이다. 이 값
# 하나만으로 penalty가 크게 붙지 않는다(1개 evidence는 penalty 0).
PROGRESSED_EVIDENCE_THRESHOLDS: dict[str, float] = {
    "range_36m": 1.2,
    "avg_price_change_12m": 0.30,
    "ma_spread": 0.20,
    "ma24_slope": 0.10,
    "range_position": 0.85,
}

# evidence 개수별 penalty. 1개는 "거의 없음"(0), 2개부터 완만하게 붙고
# 5개(모든 신호 동시 발생) 최대 35점을 넘지 않는다.
PROGRESSED_PENALTY_BY_EVIDENCE_COUNT: dict[int, float] = {
    0: 0.0,
    1: 0.0,
    2: 10.0,
    3: 20.0,
    4: 28.0,
    5: 35.0,
}


def _progressed_evidence_count(feature_values: dict[str, float]) -> int:
    count = 0
    for name, threshold in PROGRESSED_EVIDENCE_THRESHOLDS.items():
        value = feature_values.get(name)
        if _is_missing(value):
            continue  # 결측은 evidence로 세지 않는다(불확실 == 진행 증거 아님)
        if value >= threshold:
            count += 1
    return count


def _progressed_penalty(evidence_count: int) -> float:
    return PROGRESSED_PENALTY_BY_EVIDENCE_COUNT.get(evidence_count, 35.0)


# --- Stage (초안, heuristic. threshold는 Score Validation 결과를 보고 조정 예정) ---
#
# Feature/component score -> Stage 방향으로만 흐른다(Stage가 Score를
# 역으로 결정하지 않는다). base_score/transition_score가 없으면(둘 중
# 하나라도 계산 불가) Stage도 None이다 — insufficient_data 케이스.
_STAGE_WEAK_BASE_THRESHOLD = 60.0
_STAGE_TRANSITION_LOW = 40.0
_STAGE_TRANSITION_HIGH = 70.0
_STAGE_PROGRESSED_EVIDENCE_COUNT = 3


def _classify_stage(
    base_score: float | None, transition_score: float | None, progressed_evidence_count: int
) -> PatternAStage | None:
    if base_score is None or transition_score is None:
        return None
    if progressed_evidence_count >= _STAGE_PROGRESSED_EVIDENCE_COUNT:
        return PatternAStage.PROGRESSED
    if transition_score < _STAGE_TRANSITION_LOW:
        return PatternAStage.BASE if base_score >= _STAGE_WEAK_BASE_THRESHOLD else PatternAStage.WEAK
    if transition_score >= _STAGE_TRANSITION_HIGH:
        return PatternAStage.EARLY_TREND
    return PatternAStage.TRANSITION


@dataclass
class PatternAResult:
    """Pattern A v0.1 Score 결과. 종목 신원(ticker/name)은 포함하지 않는다
    (models/score.py의 ScanResult가 합친다).

    insufficient_data=True면 pattern_a_score/stage는 항상 None이다 —
    ma24_slope(Core)가 결측이거나 Base Feature가 전부 결측인 경우.
    """

    base_score: float | None
    base_valid_features: tuple[str, ...]
    base_missing_features: tuple[str, ...]

    transition_score: float | None
    transition_valid_features: tuple[str, ...]
    transition_missing_features: tuple[str, ...]

    balanced_core_score: float | None
    alignment_bonus: float
    progressed_penalty: float
    progressed_evidence_count: int

    pattern_a_score: float | None

    stage: PatternAStage | None

    flags: dict[str, bool] = field(default_factory=dict)

    feature_snapshot: FeatureRow | None = None


def score_pattern_a(features: Any) -> PatternAResult:
    """FeatureRow(또는 같은 속성을 가진 객체)를 받아 Pattern A v0.1 Score를
    계산한다. 순수 함수 — features 계산 자체는 하지 않는다."""
    feature_values = {
        name: getattr(features, name)
        for name in (
            "range_36m",
            "avg_price_change_12m",
            "ma_spread",
            "ma24_slope",
            "weekly_ma12_slope",
            "ma24_slope_acceleration",
            "range_position",
        )
    }

    base = _weighted_piecewise_score(feature_values, BASE_WEIGHTS, BASE_POINTS)
    transition = _weighted_piecewise_score(feature_values, TRANSITION_WEIGHTS, TRANSITION_POINTS)

    ma24_missing = _is_missing(feature_values.get("ma24_slope"))
    insufficient_data = ma24_missing or base.score is None or transition.score is None

    if insufficient_data:
        return PatternAResult(
            base_score=base.score,
            base_valid_features=base.valid_features,
            base_missing_features=base.missing_features,
            transition_score=transition.score,
            transition_valid_features=transition.valid_features,
            transition_missing_features=transition.missing_features,
            balanced_core_score=None,
            alignment_bonus=0.0,
            progressed_penalty=0.0,
            progressed_evidence_count=0,
            pattern_a_score=None,
            stage=None,
            flags={
                "transition_alignment": False,
                "already_progressed": False,
                "insufficient_data": True,
            },
            feature_snapshot=features if isinstance(features, FeatureRow) else None,
        )

    balanced_core = _harmonic_mean(base.score, transition.score)
    alignment = _transition_alignment(feature_values)
    alignment_bonus = ALIGNMENT_BONUS if alignment else 0.0
    evidence_count = _progressed_evidence_count(feature_values)
    penalty = _progressed_penalty(evidence_count)

    final = balanced_core + alignment_bonus - penalty
    final = max(0.0, min(100.0, final))

    stage = _classify_stage(base.score, transition.score, evidence_count)

    return PatternAResult(
        base_score=base.score,
        base_valid_features=base.valid_features,
        base_missing_features=base.missing_features,
        transition_score=transition.score,
        transition_valid_features=transition.valid_features,
        transition_missing_features=transition.missing_features,
        balanced_core_score=balanced_core,
        alignment_bonus=alignment_bonus,
        progressed_penalty=penalty,
        progressed_evidence_count=evidence_count,
        pattern_a_score=final,
        stage=stage,
        flags={
            "transition_alignment": alignment,
            "already_progressed": evidence_count >= _STAGE_PROGRESSED_EVIDENCE_COUNT,
            "insufficient_data": False,
        },
        feature_snapshot=features if isinstance(features, FeatureRow) else None,
    )
