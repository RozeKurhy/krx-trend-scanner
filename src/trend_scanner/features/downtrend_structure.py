"""Pattern A / Pattern B 경계 판별용 장기 하락 구조 후보 Feature (v0.2 설계).

Score Design v0.2 재리뷰(item 9)에서 요청한 "장기 하락 구조" 신호 후보
2개를 계산만 한다. 아직 FeatureRow/PATTERN_A_FEATURE_SCOPE/Score 어디에도
연결하지 않는다 — analysis-only 검증(scripts/score_v02_candidate_compare.py)
전용이다. 실제로 채택되면 그때 FeatureRow에 정식으로 편입한다.

두 후보는 서로 다른 질문에 답한다(넷마블형 "하락 도중 반등"과 079550/
005490형 "이미 하락 후 base 형성" 진짜 positive를 구분하기 위해 하나만
보지 않는다):

    long_term_high_slope_36m
        36개월 구간을 오래된/최근 12개월 블록으로 나눠, 최근 블록 고점이
        가장 오래된 블록 고점 대비 얼마나 낮은가. 값이 크게 음수일수록
        "고점이 계속 낮아지는" 구조 — 하락이 "있었다"는 사실만 본다.

    prior_leg_drift_36m
        avg_price_change_12m(최근 12개월 평균 종가 vs 그 이전 12개월
        평균 종가)과 완전히 같은 계산을, 12개월 더 과거 구간(24~36개월
        전 vs 12~24개월 전)에 적용한 값. avg_price_change_12m과 나란히
        보면 "최근에도 여전히 하락 중인가"(둘 다 음수) vs "예전 leg는
        하락했지만 최근 leg는 멈췄는가"(prior만 크게 음수)를 구분한다 —
        하락이 "지금도 진행 중인가"를 본다.

둘 다 36개월 미만이면 NaN(range_36m/avg_price_change_12m와 같은 결측
정책). daily/monthly 계산은 호출자가 look-ahead 방지가 이미 적용된
프레임(HistoricalSnapshot.monthly)을 넘겨야 한다 — 이 모듈 자체는 슬라이싱
을 하지 않는다.
"""

from __future__ import annotations

import pandas as pd

NAN = float("nan")


def _safe_div(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return NAN
    return numerator / denominator


def long_term_high_slope_36m(monthly: pd.DataFrame) -> float:
    if len(monthly) < 36 or "high" not in monthly.columns:
        return NAN
    early_high = monthly["high"].iloc[-36:-24].max()
    recent_high = monthly["high"].iloc[-12:].max()
    return _safe_div(recent_high - early_high, early_high)


def prior_leg_drift_36m(monthly: pd.DataFrame) -> float:
    if len(monthly) < 36 or "close" not in monthly.columns:
        return NAN
    older_leg = monthly["close"].iloc[-36:-24].mean()
    recent_leg = monthly["close"].iloc[-24:-12].mean()
    return _safe_div(recent_leg - older_leg, older_leg)
