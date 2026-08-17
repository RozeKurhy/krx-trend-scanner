"""Phase 13E — Pattern A Fast Weekly Trigger Feature Candidates (RESEARCH ONLY).

Purely descriptive, deterministic feature functions over a PIT-sliced
completed-weekly OHLCV DataFrame (as produced by
``trend_scanner.validation.historical_snapshot.build_historical_snapshot``,
``include_incomplete_periods=False``). Nothing here is a Production Rule /
Threshold / Score / Classifier — see
docs/validation/pattern_a_fast_weekly_trigger_feature_research_v01.md for the
research findings and the explicit "No Threshold Frozen" declaration.

This module must never be imported by ``trend_scanner.patterns`` (production
evaluator) or by the scanner pipeline (w.md §22).

Indexing convention (verified empirically across all 40 Human Calibration
samples before writing this module — see docs §4): for every sample,
``weekly.index[-1] == reference_date``. So ``weekly.iloc[-1]`` IS the
reference week itself, not a week before it.

Two different window conventions are used depending on the feature's
economic meaning:

- "Current position" features (MA, return, range position, momentum,
  higher-low count, ...) include the reference week itself in their window
  (``iloc[-k:]``) — the question is "where does this week sit".
- "Prior structure" features (prior high, breakout state/age/hold) EXCLUDE
  the reference week from the window used to compute the prior reference
  level (``iloc[-(k+1):-1]``) — the question is "did the reference week
  cross a level set before it". Mixing the two up is exactly the bug §24
  CASE B guards against: if the reference week's own high leaks into its
  own prior-high window, breakout detection becomes tautological.

All windows are bar-count based (``iloc[-n:]``), not calendar-week based.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    family: str
    formula: str
    required_history_bars: int
    timeframe: str
    pit_safe: bool
    missing_behavior: str
    human_interpretation: str
    research_question: str


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    # --- 7.1 Weekly MA Structure ---
    FeatureSpec(
        "weekly_ma12", "7.1_weekly_ma_structure",
        "mean(close[-12:]) (진단용 raw 값, 순위분석 대상 아님)",
        12, "weekly", True, "n<12 -> NaN",
        "12주 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "weekly_ma26", "7.1_weekly_ma_structure",
        "mean(close[-26:]) (진단용 raw 값)",
        26, "weekly", True, "n<26 -> NaN",
        "26주 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "weekly_ma52", "7.1_weekly_ma_structure",
        "mean(close[-52:]) (진단용 raw 값)",
        52, "weekly", True, "n<52 -> NaN",
        "52주 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "weekly_ma200", "7.1_weekly_ma_structure",
        "mean(close[-200:]) (진단용 raw 값)",
        200, "weekly", True, "n<200 -> NaN",
        "200주 단순이동평균 — §7.2 200주선 저항 연구의 기반",
        "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "close_vs_wma12_pct", "7.1_weekly_ma_structure",
        "close[-1] / weekly_ma12 - 1",
        12, "weekly", True, "n<12 -> NaN",
        "단기(12주) 이평 대비 현재가 위치",
        "Q(13E-Hyp A/B): SETUP/TRIGGER sample의 단기 이평 이격도",
    ),
    FeatureSpec(
        "close_vs_wma26_pct", "7.1_weekly_ma_structure",
        "close[-1] / weekly_ma26 - 1",
        26, "weekly", True, "n<26 -> NaN",
        "중기(26주) 이평 대비 현재가 위치",
        "GOOD vs TOO_EARLY 구분에서 중기 이격도가 유효한가",
    ),
    FeatureSpec(
        "close_vs_wma52_pct", "7.1_weekly_ma_structure",
        "close[-1] / weekly_ma52 - 1",
        52, "weekly", True, "n<52 -> NaN",
        "장기(52주) 이평 대비 현재가 위치",
        "TOO_LATE/TOO_EXTENDED 구분에서 장기 이격도가 과도한가",
    ),
    FeatureSpec(
        "close_vs_wma200_pct", "7.1_weekly_ma_structure",
        "close[-1] / weekly_ma200 - 1",
        200, "weekly", True, "n<200 -> NaN",
        "200주 이평(장기 저항선) 대비 현재가 위치 — §7.2의 핵심 연속형 값",
        "Q7(13D 이관): '주봉 200 이평 저항' Human Observation의 직접 대응",
    ),
    FeatureSpec(
        "wma12_vs_wma26_pct", "7.1_weekly_ma_structure",
        "weekly_ma12 / weekly_ma26 - 1",
        26, "weekly", True, "n<26 -> NaN",
        "단기/중기 이평 상대 위치 — 정배열/역배열의 단기 축",
        "SETUP 구간 단기 이평 구조 개선 여부",
    ),
    FeatureSpec(
        "wma52_vs_wma200_pct", "7.1_weekly_ma_structure",
        "weekly_ma52 / weekly_ma200 - 1",
        200, "weekly", True, "n<200 -> NaN",
        "장기 이평 상대 위치 — 정배열/역배열의 장기 축(200주선 대비 52주선)",
        "장기 구조 개선이 200주선 근처에서도 확인되는가",
    ),
    FeatureSpec(
        "wma12_slope_1w", "7.1_weekly_ma_structure",
        "mean(close[-12:])/mean(close[-13:-1]) - 1 (1주 전 대비 MA12 변화율)",
        13, "weekly", True, "n<13 -> NaN",
        "단기 이평의 최근 1주 기울기 변화",
        "상승 구조 개선 속도(단기)",
    ),
    FeatureSpec(
        "wma26_slope_1w", "7.1_weekly_ma_structure",
        "mean(close[-26:])/mean(close[-27:-1]) - 1",
        27, "weekly", True, "n<27 -> NaN",
        "중기 이평의 최근 1주 기울기 변화",
        "상승 구조 개선 속도(중기)",
    ),
    FeatureSpec(
        "wma52_slope_1w", "7.1_weekly_ma_structure",
        "mean(close[-52:])/mean(close[-53:-1]) - 1",
        53, "weekly", True, "n<53 -> NaN",
        "장기 이평의 최근 1주 기울기 변화",
        "장기 하락 압력이 개선 중인가",
    ),
    FeatureSpec(
        "wma200_slope_1w", "7.1_weekly_ma_structure",
        "mean(close[-200:])/mean(close[-201:-1]) - 1",
        201, "weekly", True, "n<201 -> NaN",
        "200주 이평의 최근 1주 기울기 변화",
        "장기 저항선 자체가 상승 전환 중인가",
    ),
    # --- 7.2 200-Week MA Resistance ---
    FeatureSpec(
        "high_vs_wma200_pct", "7.2_200w_ma_resistance",
        "high[-1] / weekly_ma200 - 1",
        200, "weekly", True, "n<200 -> NaN",
        "reference 주의 고가가 200주선 대비 어디 있는지(종가보다 관대한 저항 접근도)",
        "200주 저항에 '닿았는지'를 종가보다 먼저 포착 가능한가",
    ),
    FeatureSpec(
        "weeks_above_wma200_recent_12w", "7.2_200w_ma_resistance",
        "count(close[-12:] > weekly_ma200)"
        " — weekly_ma200은 reference 시점 고정값 근사(매주 rolling 재계산 아님, 명시적 근사)",
        200, "weekly", True, "n<200 -> NaN",
        "최근 12주 중 200주선 위에서 마감한 주의 수(0~12)",
        "Q7(13D 이관): 200주선 위 체류 기간이 GOOD_TRIGGER와 관련 있는가",
    ),
    # --- 7.3 Prior High Proximity (reference week 반드시 제외) ---
    FeatureSpec(
        "distance_to_prior_13w_high_pct", "7.3_prior_high_proximity",
        "close[-1] / max(high[-14:-1]) - 1 (직전 13주, reference 제외)",
        14, "weekly", True, "n<14 -> NaN",
        "직전 13주 고점 대비 현재가 위치(0에 가까울수록 돌파 임박/직전)",
        "SETUP -> TRIGGER 전환 직전 이 값이 0에 수렴하는가",
    ),
    FeatureSpec(
        "distance_to_prior_26w_high_pct", "7.3_prior_high_proximity",
        "close[-1] / max(high[-27:-1]) - 1 (직전 26주, reference 제외)",
        27, "weekly", True, "n<27 -> NaN",
        "직전 26주 고점 대비 현재가 위치",
        "w.md 예시 window(26w)와 일치 — breakout 판정의 기준 축",
    ),
    FeatureSpec(
        "distance_to_prior_52w_high_pct", "7.3_prior_high_proximity",
        "close[-1] / max(high[-53:-1]) - 1 (직전 52주, reference 제외)",
        53, "weekly", True, "n<53 -> NaN",
        "직전 52주 고점 대비 현재가 위치",
        "더 긴 창에서도 동일한 근접/돌파 신호가 유지되는가",
    ),
    # --- 7.4 Breakout State (26주 대표 window; 13w/52w는 §7.3 distance로 이미 연속형 커버) ---
    FeatureSpec(
        "close_above_prior_26w_high", "7.4_breakout_state",
        "1.0 if close[-1] > max(high[-27:-1]) else 0.0",
        27, "weekly", True, "n<27 -> NaN",
        "종가 기준 직전 26주 고점 돌파 여부(boolean)",
        "이 값만으로 Trigger 판정하지 않음 — 분리력 참고용",
    ),
    FeatureSpec(
        "high_above_prior_26w_high", "7.4_breakout_state",
        "1.0 if high[-1] > max(high[-27:-1]) else 0.0",
        27, "weekly", True, "n<27 -> NaN",
        "고가 기준 직전 26주 고점 돌파 시도 여부(종가 미달 돌파 포함)",
        "종가 돌파와 고가 돌파 시도의 괴리가 있는 sample이 있는가",
    ),
    # --- 7.5 Breakout Age (PIT-critical backward scan, 26주 대표 window) ---
    FeatureSpec(
        "weeks_since_26w_close_breakout", "7.5_breakout_age",
        "reference 기준 backward scan: 각 과거 week i에서 그 시점 직전 26주"
        " high(= max(high[i-26:i]), i 미포함)를 다시 계산하고 close[i] >"
        " prior_high[i]인 가장 최근 event까지의 주 수. offset=0이면 reference"
        " 주 자체가 breakout.",
        27, "weekly", True, "직전 26주 내 event 없음 -> NaN(NOT_OBSERVED)",
        "가장 최근 26주 고점 돌파가 몇 주 전이었는지",
        "GOOD_TRIGGER는 이 값이 작은가(최근 돌파), TOO_LATE는 큰가(오래된 돌파)",
    ),
    # --- 7.6 Breakout Hold / Support (breakout_level은 event 시점에 frozen) ---
    FeatureSpec(
        "post_breakout_min_close_vs_level_pct_26w", "7.6_breakout_hold_support",
        "event week 다음 주부터 reference까지 종가 중 최저값 / breakout_level - 1"
        "(event=reference면 관찰 구간 없음 -> NaN)",
        27, "weekly", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 종가가 breakout level을 얼마나 지켰는지(최악 시점 기준)",
        "FALSE_TRIGGER는 이 값이 음수로 크게 내려가는가",
    ),
    FeatureSpec(
        "post_breakout_min_low_vs_level_pct_26w", "7.6_breakout_hold_support",
        "event week 다음 주부터 reference까지 저가 중 최저값 / breakout_level - 1",
        27, "weekly", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 저가 기준으로도 breakout level을 지켰는지(종가보다 보수적)",
        "장중 이탈은 있었지만 종가는 지킨 sample 구분 가능한가",
    ),
    FeatureSpec(
        "post_breakout_close_hold_ratio_26w", "7.6_breakout_hold_support",
        "event week 다음 주부터 reference까지 (종가 > breakout_level)인 주의 비율(0~1)",
        27, "weekly", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 지지에 성공한 주의 비율",
        "13D §12와 동일하게 Cliff's Delta 1차 근거로 사용",
    ),
    FeatureSpec(
        "weeks_closed_above_breakout_level_26w", "7.6_breakout_hold_support",
        "event week 다음 주부터 reference까지 (종가 > breakout_level)인 주의 개수(정수)",
        27, "weekly", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 지지 마감 주 수(절대 개수, post window 길이가 sample마다 달라 비율과 별도 참고)",
        "post_breakout_close_hold_ratio_26w와 함께 관찰 구간 길이 효과 분리",
    ),
    # --- 7.7 Higher-Low Structure ---
    FeatureSpec(
        "higher_weekly_low_count_8w", "7.7_higher_low_structure",
        "count(i in 1..7: low[-8:][i] > low[-8:][i-1])",
        8, "weekly", True, "n<8 -> NaN",
        "최근 8주 중 전주 대비 저점이 높아진 주의 수(단순 카운트, pivot 정의 아님)",
        "'저점이 점점 높아짐' 관찰의 가장 단순한 연속형 근사(단기)",
    ),
    FeatureSpec(
        "higher_weekly_low_count_13w", "7.7_higher_low_structure",
        "count(i in 1..12: low[-13:][i] > low[-13:][i-1])",
        13, "weekly", True, "n<13 -> NaN",
        "최근 13주 중 higher-low count",
        "더 긴 창에서도 유효한가",
    ),
    FeatureSpec(
        "weekly_low_slope_8w", "7.7_higher_low_structure",
        "(low[-1] - low[-1-8]) / 8 / close[-1] (저점 시작-끝 단순 기울기, 8주 간격, 가격 스케일 정규화)",
        9, "weekly", True, "n<9 -> NaN",
        "최근 8주 저점의 방향(양수=저점 상승 추세)",
        "higher_weekly_low_count_8w와 상관/보완 관계 확인",
    ),
    FeatureSpec(
        "weekly_low_slope_13w", "7.7_higher_low_structure",
        "(low[-1] - low[-1-13]) / 13 / close[-1]",
        14, "weekly", True, "n<14 -> NaN",
        "최근 13주 저점의 방향",
        "더 긴 창에서도 방향이 유지되는가",
    ),
    FeatureSpec(
        "rolling_low_4w_change", "7.7_higher_low_structure",
        "min(low[-4:]) / min(low[-8:-4]) - 1 (최근 4주 최저 vs 그 이전 4주 최저)",
        8, "weekly", True, "n<8 -> NaN",
        "직전 4주 구간 대비 최근 4주 구간의 저점 상승률",
        "w.md §7.5 예시 정의를 그대로 따름",
    ),
    FeatureSpec(
        "rolling_low_8w_change", "7.7_higher_low_structure",
        "min(low[-8:]) / min(low[-16:-8]) - 1",
        16, "weekly", True, "n<16 -> NaN",
        "직전 8주 구간 대비 최근 8주 구간의 저점 상승률",
        "더 긴 창에서도 저점 상승 추세가 유지되는가",
    ),
    # --- 7.8 Support / Bottom Stabilization ---
    FeatureSpec(
        "weeks_since_13w_low", "7.8_support_bottom_stabilization",
        "(13-1) - argmin(low[-13:]) (최근주=0)",
        13, "weekly", True, "n<13 -> NaN",
        "13주 저점을 찍은 지 몇 주 지났는지",
        "TOO_EARLY는 이 값이 작은가(최근 저점, 아직 지지 검증 안 됨)",
    ),
    FeatureSpec(
        "weeks_since_26w_low", "7.8_support_bottom_stabilization",
        "(26-1) - argmin(low[-26:])",
        26, "weekly", True, "n<26 -> NaN",
        "26주 저점을 찍은 지 몇 주 지났는지",
        "더 긴 창에서 저점 확정 여부",
    ),
    FeatureSpec(
        "distance_from_13w_low_pct", "7.8_support_bottom_stabilization",
        "close[-1] / min(low[-13:]) - 1",
        13, "weekly", True, "n<13 -> NaN",
        "최근 13주 저점 대비 현재 위치",
        "저점 근접도가 WATCH/SETUP 경계와 관련 있는가",
    ),
    FeatureSpec(
        "distance_from_26w_low_pct", "7.8_support_bottom_stabilization",
        "close[-1] / min(low[-26:]) - 1",
        26, "weekly", True, "n<26 -> NaN",
        "최근 26주 저점 대비 현재 위치",
        "더 긴 창에서도 유효한가",
    ),
    FeatureSpec(
        "weekly_down_week_ratio_8w", "7.8_support_bottom_stabilization",
        "count(weekly_return[-8:] < 0) / 8",
        9, "weekly", True, "n<9 -> NaN",
        "최근 8주 중 하락 마감한 주의 비율",
        "저점 갱신 지속 중인지 vs 안정화 중인지 구분",
    ),
    # --- 7.9 Weekly MA Compression / Expansion ---
    FeatureSpec(
        "weekly_ma_spread_pct", "7.9_ma_compression_expansion",
        "(max(wma12,wma26,wma52,wma200) - min(wma12,wma26,wma52,wma200)) / close[-1]",
        200, "weekly", True, "n<200 -> NaN",
        "4개 주요 이평선이 얼마나 벌어져 있는지(압축/확산)",
        "SETUP 구간에서 이평 수렴이 실제로 관찰되는가(Rule 아님, 관찰만)",
    ),
    FeatureSpec(
        "wma12_wma26_gap_pct", "7.9_ma_compression_expansion",
        "|wma12 - wma26| / close[-1]",
        26, "weekly", True, "n<26 -> NaN",
        "단기 이평 쌍의 압축 정도(엉킴)",
        "w.md §7.9 예시(wma12_wma26_gap_pct)와 동일",
    ),
    # --- 7.10 Weekly Momentum / Acceleration ---
    FeatureSpec(
        "weekly_return_4w", "7.10_momentum_acceleration",
        "close[-1] / close[-1-4] - 1",
        5, "weekly", True, "n<5 -> NaN",
        "최근 4주 수익률(초단기 momentum)",
        "돌파 직후 momentum 강도",
    ),
    FeatureSpec(
        "weekly_return_8w", "7.10_momentum_acceleration",
        "close[-1] / close[-1-8] - 1",
        9, "weekly", True, "n<9 -> NaN",
        "최근 8주 수익률",
        "단기~중기 momentum",
    ),
    FeatureSpec(
        "weekly_return_13w", "7.10_momentum_acceleration",
        "close[-1] / close[-1-13] - 1",
        14, "weekly", True, "n<14 -> NaN",
        "최근 13주 수익률",
        "TOO_LATE/TOO_EXTENDED 구분(7.11과 공유)",
    ),
    FeatureSpec(
        "weekly_return_26w", "7.10_momentum_acceleration",
        "close[-1] / close[-1-26] - 1",
        27, "weekly", True, "n<27 -> NaN",
        "최근 26주 수익률",
        "더 긴 창에서의 momentum/과열 여부",
    ),
    FeatureSpec(
        "recent_4w_return_vs_prior_12w", "7.10_momentum_acceleration",
        "mean(weekly_return[-4:]) - mean(weekly_return[-16:-4])",
        17, "weekly", True, "n<17 -> NaN",
        "최근 4주 평균 주간수익률 - 그 이전 12주 평균(추세 가속/감속)",
        "SETUP -> TRIGGER 전환 직전 가속 신호가 있는가",
    ),
    FeatureSpec(
        "weekly_positive_ratio_8w", "7.10_momentum_acceleration",
        "count(weekly_return[-8:] > 0) / 8",
        9, "weekly", True, "n<9 -> NaN",
        "최근 8주 중 상승 마감한 주의 비율",
        "weekly_down_week_ratio_8w와의 상관/중복성 확인용",
    ),
    # --- 7.11 Extension / Late Entry (중복 재사용은 §7.1/§7.8/§7.10에 이미 정의) ---
    FeatureSpec(
        "distance_from_52w_low_pct", "7.11_extension_late_entry",
        "close[-1] / min(low[-52:]) - 1",
        52, "weekly", True, "n<52 -> NaN",
        "최근 52주 저점 대비 현재 위치 — 값이 클수록 이미 많이 상승",
        "TOO_LATE sample이 이 값이 특히 큰가",
    ),
    FeatureSpec(
        "range_position_26w", "7.11_extension_late_entry",
        "(close[-1] - min(low[-26:])) / (max(high[-26:]) - min(low[-26:]))",
        26, "weekly", True, "n<26 또는 range=0 -> NaN",
        "26주 range 내 현재 위치(0=하단, 1=상단)",
        "GOOD_TRIGGER와 TOO_EXTENDED가 이 값에서 어떻게 갈리는가",
    ),
    FeatureSpec(
        "range_position_52w", "7.11_extension_late_entry",
        "(close[-1] - min(low[-52:])) / (max(high[-52:]) - min(low[-52:]))",
        52, "weekly", True, "n<52 또는 range=0 -> NaN",
        "52주 range 내 현재 위치",
        "더 긴 창에서도 유지되는가",
    ),
    FeatureSpec(
        "recent_8w_max_runup", "7.11_extension_late_entry",
        "max(close[-8:]) / min(close[-8:]) - 1",
        8, "weekly", True, "n<8 -> NaN",
        "최근 8주 내 최대 변동폭(저점 대비 고점 상승폭)",
        "TOO_EXTENDED sample은 최근 급등 흔적이 있는가",
    ),
    FeatureSpec(
        "consecutive_positive_weeks", "7.11_extension_late_entry",
        "reference 주부터 역순으로 weekly_return>0이 끊기지 않고 이어진 주 수",
        2, "weekly", True, "n<2 -> NaN",
        "연속 상승 주 수 — 값이 클수록 단기 과열",
        "TOO_LATE/TOO_EXTENDED sample의 연속 상승 주 수가 더 긴가",
    ),
    # --- 7.12 False Breakout Risk (대부분 §7.6 재사용, 신규만) ---
    FeatureSpec(
        "higher_low_after_breakout_count", "7.12_false_breakout_risk",
        "breakout event(§7.5) 다음 주부터 reference까지, 전주 대비 저점이"
        " 높아진 주의 수(event 없음 또는 관찰 구간<2주 -> NaN)",
        27, "weekly", True, "event 없음 또는 관찰 구간<2 -> NaN",
        "돌파 이후 저점이 계속 높아지며 건강하게 지지되는지",
        "FALSE_TRIGGER는 돌파 후 higher-low가 거의 없는가",
    ),
    FeatureSpec(
        "close_back_below_breakout_level", "7.12_false_breakout_risk",
        "1.0 if (event 존재 and close[-1] < breakout_level) else 0.0"
        "(event 없으면 NaN)",
        27, "weekly", True, "event 없음 -> NaN",
        "reference 시점 기준 돌파 레벨 아래로 종가가 이미 복귀했는지(boolean)",
        "FALSE_TRIGGER 판정의 가장 직접적인 machine 근사(Human Label 아님, §18/§19 참고)",
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)
DIAGNOSTIC_ONLY_FEATURES: frozenset[str] = frozenset(
    {"weekly_ma12", "weekly_ma26", "weekly_ma52", "weekly_ma200"}
)


def _tail_or_none(series: pd.Series, k: int) -> pd.Series | None:
    if len(series) < k:
        return None
    return series.iloc[-k:]


def _find_breakout_event(close: pd.Series, high: pd.Series, k: int) -> tuple[int, float] | None:
    """reference 주(마지막 행)부터 backward로 스캔해, 각 과거 week i에서 그
    시점 기준 직전 k주 high(= high.iloc[i-k:i].max(), i 미포함)를 다시 계산하고
    close.iloc[i] > prior_high_at_i인 가장 최근 event를 찾는다.

    reference 주 자체(offset=0)도 breakout 후보에 포함한다 — "방금 돌파"도
    유효한 event다. 반환값은 (event의 positional index, 그 시점의 breakout_level)
    또는 event가 없으면 None. i-k:i 슬라이스는 항상 i(검사 대상 주) 자체의
    high/close를 포함하지 않으므로 CASE B(당해 주 고가가 자기 자신의 prior
    high 계산에 leak되는 버그)를 구조적으로 방지한다.
    """
    n = len(close)
    if n < k + 1:
        return None
    for offset in range(0, n - k):
        i = n - 1 - offset
        if i < k:
            break
        prior_high_at_i = high.iloc[i - k : i].max()
        if close.iloc[i] > prior_high_at_i:
            return i, float(prior_high_at_i)
    return None


def compute_weekly_trigger_features(weekly: pd.DataFrame) -> dict[str, float]:
    """PIT-sliced completed-weekly OHLCV(``weekly.index`` 전부
    ``reference_date`` 이하, 마지막 행이 reference week 자체)로부터 §7 후보
    Feature를 계산한다.

    호출자는 반드시 ``weekly``가 이미 reference_date 이하로 슬라이스된
    completed-period 데이터임을 보장해야 한다(이 함수 자체는 그 보장을
    강제하지 않는다 — leakage 방지는 상위 호출부의 책임이며 targeted test로
    검증한다). 함수 시그니처는 의도적으로 ``weekly`` 하나만 받는다 —
    human_label / weekly_stage_at_reference / trigger_event_date 등은
    입력으로 존재하지 않는다(w.md §5).
    """
    close = weekly["close"]
    high = weekly["high"]
    low = weekly["low"]
    n = len(weekly)
    out: dict[str, float] = {name: np.nan for name in FEATURE_NAMES}

    def wma(k: int) -> float:
        w = _tail_or_none(close, k)
        if w is None:
            return np.nan
        return float(w.mean())

    ma12, ma26, ma52, ma200 = wma(12), wma(26), wma(52), wma(200)
    out["weekly_ma12"], out["weekly_ma26"], out["weekly_ma52"], out["weekly_ma200"] = ma12, ma26, ma52, ma200

    def close_vs_pct(ma_value: float) -> float:
        if np.isnan(ma_value):
            return np.nan
        return float(close.iloc[-1] / ma_value - 1.0)

    out["close_vs_wma12_pct"] = close_vs_pct(ma12)
    out["close_vs_wma26_pct"] = close_vs_pct(ma26)
    out["close_vs_wma52_pct"] = close_vs_pct(ma52)
    out["close_vs_wma200_pct"] = close_vs_pct(ma200)

    if not np.isnan(ma12) and not np.isnan(ma26):
        out["wma12_vs_wma26_pct"] = float(ma12 / ma26 - 1.0)
    if not np.isnan(ma52) and not np.isnan(ma200):
        out["wma52_vs_wma200_pct"] = float(ma52 / ma200 - 1.0)

    def wma_slope_1w(k: int) -> float:
        if n < k + 1:
            return np.nan
        ma_now = close.iloc[-k:].mean()
        ma_prev = close.iloc[-k - 1 : -1].mean()
        if ma_prev == 0:
            return np.nan
        return float(ma_now / ma_prev - 1.0)

    out["wma12_slope_1w"] = wma_slope_1w(12)
    out["wma26_slope_1w"] = wma_slope_1w(26)
    out["wma52_slope_1w"] = wma_slope_1w(52)
    out["wma200_slope_1w"] = wma_slope_1w(200)

    if not np.isnan(ma200):
        out["high_vs_wma200_pct"] = float(high.iloc[-1] / ma200 - 1.0)
        w12 = _tail_or_none(close, 12)
        if w12 is not None:
            out["weeks_above_wma200_recent_12w"] = float((w12 > ma200).sum())

    def prior_high(k: int) -> float:
        if n < k + 1:
            return np.nan
        return float(high.iloc[-(k + 1) : -1].max())

    ph13, ph26, ph52 = prior_high(13), prior_high(26), prior_high(52)
    if not np.isnan(ph13):
        out["distance_to_prior_13w_high_pct"] = float(close.iloc[-1] / ph13 - 1.0)
    if not np.isnan(ph26):
        out["distance_to_prior_26w_high_pct"] = float(close.iloc[-1] / ph26 - 1.0)
        out["close_above_prior_26w_high"] = 1.0 if close.iloc[-1] > ph26 else 0.0
        out["high_above_prior_26w_high"] = 1.0 if high.iloc[-1] > ph26 else 0.0
    if not np.isnan(ph52):
        out["distance_to_prior_52w_high_pct"] = float(close.iloc[-1] / ph52 - 1.0)

    event = _find_breakout_event(close, high, 26)
    if event is not None:
        i_event, breakout_level = event
        offset = float((n - 1) - i_event)
        out["weeks_since_26w_close_breakout"] = offset

        post_start, post_end = i_event + 1, n
        if post_start < post_end:
            post_close = close.iloc[post_start:post_end]
            post_low = low.iloc[post_start:post_end]
            out["post_breakout_min_close_vs_level_pct_26w"] = float(post_close.min() / breakout_level - 1.0)
            out["post_breakout_min_low_vs_level_pct_26w"] = float(post_low.min() / breakout_level - 1.0)
            hold_count = int((post_close > breakout_level).sum())
            out["post_breakout_close_hold_ratio_26w"] = float(hold_count / len(post_close))
            out["weeks_closed_above_breakout_level_26w"] = float(hold_count)

            post_low_with_event = low.iloc[i_event:post_end]
            if len(post_low_with_event) >= 2:
                vals = post_low_with_event.to_numpy()
                out["higher_low_after_breakout_count"] = float(
                    sum(1 for j in range(1, len(vals)) if vals[j] > vals[j - 1])
                )
        out["close_back_below_breakout_level"] = 1.0 if close.iloc[-1] < breakout_level else 0.0

    def higher_low_count(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        vals = w.to_numpy()
        return float(sum(1 for i in range(1, len(vals)) if vals[i] > vals[i - 1]))

    out["higher_weekly_low_count_8w"] = higher_low_count(8)
    out["higher_weekly_low_count_13w"] = higher_low_count(13)

    def low_slope(k: int) -> float:
        if n < k + 1 or close.iloc[-1] == 0:
            return np.nan
        return float((low.iloc[-1] - low.iloc[-1 - k]) / k / close.iloc[-1])

    out["weekly_low_slope_8w"] = low_slope(8)
    out["weekly_low_slope_13w"] = low_slope(13)

    def rolling_low_change(k: int) -> float:
        if n < 2 * k:
            return np.nan
        current = low.iloc[-k:].min()
        prior = low.iloc[-2 * k : -k].min()
        if prior <= 0:
            return np.nan
        return float(current / prior - 1.0)

    out["rolling_low_4w_change"] = rolling_low_change(4)
    out["rolling_low_8w_change"] = rolling_low_change(8)

    def weeks_since_low(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        idx_min = int(np.argmin(w.to_numpy()))
        return float((k - 1) - idx_min)

    out["weeks_since_13w_low"] = weeks_since_low(13)
    out["weeks_since_26w_low"] = weeks_since_low(26)

    def distance_from_low(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        return float(close.iloc[-1] / w.min() - 1.0)

    out["distance_from_13w_low_pct"] = distance_from_low(13)
    out["distance_from_26w_low_pct"] = distance_from_low(26)
    out["distance_from_52w_low_pct"] = distance_from_low(52)

    weekly_return = close.pct_change()

    def down_ratio(k: int) -> float:
        w = _tail_or_none(weekly_return, k)
        if w is None or w.isna().any():
            return np.nan
        return float((w < 0).sum() / k)

    def up_ratio(k: int) -> float:
        w = _tail_or_none(weekly_return, k)
        if w is None or w.isna().any():
            return np.nan
        return float((w > 0).sum() / k)

    out["weekly_down_week_ratio_8w"] = down_ratio(8)
    out["weekly_positive_ratio_8w"] = up_ratio(8)

    mas = [x for x in (ma12, ma26, ma52, ma200) if not np.isnan(x)]
    if len(mas) == 4 and close.iloc[-1] != 0:
        out["weekly_ma_spread_pct"] = float((max(mas) - min(mas)) / close.iloc[-1])
    if not np.isnan(ma12) and not np.isnan(ma26) and close.iloc[-1] != 0:
        out["wma12_wma26_gap_pct"] = float(abs(ma12 - ma26) / close.iloc[-1])

    def ret(k: int) -> float:
        if n < k + 1:
            return np.nan
        return float(close.iloc[-1] / close.iloc[-1 - k] - 1.0)

    out["weekly_return_4w"] = ret(4)
    out["weekly_return_8w"] = ret(8)
    out["weekly_return_13w"] = ret(13)
    out["weekly_return_26w"] = ret(26)

    wr16 = _tail_or_none(weekly_return, 16)
    if wr16 is not None and wr16.notna().all():
        out["recent_4w_return_vs_prior_12w"] = float(wr16.iloc[-4:].mean() - wr16.iloc[:12].mean())

    def range_position(k: int) -> float:
        hi_w = _tail_or_none(high, k)
        lo_w = _tail_or_none(low, k)
        if hi_w is None or lo_w is None:
            return np.nan
        hi, lo = hi_w.max(), lo_w.min()
        if hi <= lo:
            return np.nan
        return float((close.iloc[-1] - lo) / (hi - lo))

    out["range_position_26w"] = range_position(26)
    out["range_position_52w"] = range_position(52)

    w8 = _tail_or_none(close, 8)
    if w8 is not None and w8.min() > 0:
        out["recent_8w_max_runup"] = float(w8.max() / w8.min() - 1.0)

    if n >= 2:
        streak = 0
        returns = weekly_return.iloc[1:]
        for r in reversed(returns.tolist()):
            if np.isnan(r) or r <= 0:
                break
            streak += 1
        out["consecutive_positive_weeks"] = float(streak)

    return out
