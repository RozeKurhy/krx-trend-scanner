"""Pattern A: 장기 베이스 수렴형.

점수 산식과 Hard Filter 임계값은 아직 검증되지 않았다. 자세한 스펙은
docs/patterns/pattern_a.md 를 참고한다. 여기서는 결과 구조와 가중치만
고정하고, 실제 스코어링은 구현하지 않는다.

Feature Set Freeze v0.1(docs/patterns/pattern_a.md 참고) 이후: 아래
PATTERN_A_WEIGHTS의 5영역 100점 배점은 **검증 이전의 초기 가설**이었고,
Feature Validation/Historical Snapshot/Holdout/Negative Control/Base-
Expansion Validation 검증 결과 이 구조를 그대로 쓸 근거가 약해졌다. 실제
배점은 Score Design 단계에서 `pattern_a_feature_set.py`의 축 구조(Base
Context/Trend Transition/Stage Context, FeatureAxis 참고)를 기준으로
다시 설계한다. 이 상수는 기존 테스트가 참조하고 있어 값은 그대로
남겨두지만, 최종 배점표로 취급하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

PATTERN_A_MAX_SCORE = 100

PATTERN_A_WEIGHTS = {
    "base_quality": 25,
    "low_structure": 20,
    "ma_transition": 25,
    "volatility_compression": 15,
    "breakout_position": 15,
}


@dataclass
class PatternAResult:
    """Pattern A 평가 결과. 종목 신원(ticker/name)은 포함하지 않는다.

    evaluate_pattern_a는 OHLCV DataFrame만 입력받는 순수 함수이므로 종목이
    무엇인지 알지 못한다. 종목 식별 정보는 상위 스캐너 계층에서 ScanResult로
    합친다(models/score.py 참고).
    """

    pattern_a_score: float

    rejected: bool
    rejection_reasons: tuple[str, ...]

    base_score: float
    low_score: float
    ma_score: float
    volatility_score: float
    breakout_score: float

    ma6_slope: float
    ma12_slope: float
    ma24_slope: float

    ma24_slope_acceleration: float

    ma_spread: float
    ma_spread_12m_ago: float
    ma_spread_ratio: float

    low_regression_slope: float

    atr_pct: float
    atr_ratio: float

    distance_to_resistance: float
    range_position: float


def evaluate_pattern_a(daily: pd.DataFrame) -> PatternAResult:
    """일봉 OHLCV DataFrame을 받아 Pattern A 점수를 계산한다.

    daily는 DatetimeIndex와 open/high/low/close/volume 컬럼을 가져야 하며,
    내부적으로 resampler를 통해 주봉/월봉으로 변환해 features 모듈의
    함수들로 각 영역 점수를 계산한다.

    아직 구현되지 않았다: 점수 산식과 Hard Filter 임계값이 검증되지 않은
    상태로 코드에 고정되는 것을 막기 위해 의도적으로 미구현 상태로 둔다.
    """
    raise NotImplementedError(
        "Pattern A 스코어링 로직은 아직 구현되지 않았습니다. "
        "docs/patterns/pattern_a.md 참고."
    )
