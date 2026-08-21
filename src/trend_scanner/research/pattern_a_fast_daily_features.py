"""Phase 13F — Pattern A Fast Daily Timing Feature Candidates (RESEARCH ONLY).

Purely descriptive, deterministic feature functions over a PIT-sliced daily
OHLCV DataFrame (``daily[daily.index <= reference_date]``, as recommended by
w.md §10 — this module does NOT extend
``trend_scanner.validation.historical_snapshot.HistoricalSnapshot`` with a
new ``daily`` field; callers are expected to slice the raw
``load_raw_daily()`` output themselves). Nothing here is a Production Rule /
Threshold / Score / Classifier — see
docs/patterns/pattern_a_fast/research/daily_timing_features_v01.md for the
research findings and the explicit "No Threshold Frozen" / "No Optimal Entry
Date" declarations.

This module must never be imported by ``trend_scanner.patterns`` (production
evaluator) or by the scanner pipeline (w.md §28).

Reference-bar semantics (verified empirically across all 40 Human
Calibration samples before writing this module): ``reference_date`` is
always an actual completed trading day for every sample (``daily[daily.index
<= reference_date].index[-1] == reference_date`` in all 40 cases, gap=0).
The general contract this module assumes is nonetheless the weaker one —
"current bar" = the last row of the PIT-sliced frame (``daily.iloc[-1]``),
which is the most recent trading day at or before ``reference_date`` and may
precede it if a given ``reference_date`` were ever a non-trading day. Callers
that need to know whether the two coincided should record the PIT frame's
own ``index[-1]`` (``effective_daily_as_of``) alongside the feature values.

Window convention (mirrors Phase 13E's weekly module, w.md §6):

- "Current position" features (MA, return, range position, momentum,
  candle location, volume, volatility, ...) include the reference/current
  day itself in their window (``iloc[-k:]``).
- "Prior structure" features (prior high, breakout state/age/hold) EXCLUDE
  the current day from the window used to compute the prior reference level
  (``iloc[-(k+1):-1]``) — the question is "did the current day cross a level
  set before it". This is w.md §6's explicit example
  (``prior_20d_high = max(high[-21:-1])``).

All windows are bar-count based (``iloc[-n:]``), not calendar-day based.

Deliberate de-duplication vs. w.md's candidate list (w.md §8 "Avoid
Indicator Zoo" + advisor review): several w.md-suggested names are the exact
same quantity as another candidate under a different name/family. Rather
than compute both under two names, each is implemented once and the other
family's docstring says which feature it reuses:

- §7.2's ``distance_from_dmaN_pct`` == §7.1's ``close_vs_dmaN_pct``.
- §7.7's ``higher_daily_low_count_5d`` / ``rolling_low_5d_change`` are also
  the values §7.8 asks for under the same names.
- Of the w.md-offered multi-window choices (10d/20d/60d triples, 5/14/20
  ATR windows, etc.) this module keeps one or two representative windows per
  family rather than the full grid, to keep the feature count in the same
  order of magnitude as Phase 13E's weekly module (52 total) instead of a
  multiplicative "indicator zoo".
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
    # --- 7.1 Daily MA Structure ---
    FeatureSpec(
        "daily_ma5", "7.1_daily_ma_structure",
        "mean(close[-5:]) (진단용 raw 값, 순위분석 대상 아님)",
        5, "daily", True, "n<5 -> NaN",
        "5일 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "daily_ma20", "7.1_daily_ma_structure",
        "mean(close[-20:]) (진단용 raw 값)",
        20, "daily", True, "n<20 -> NaN",
        "20일 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "daily_ma60", "7.1_daily_ma_structure",
        "mean(close[-60:]) (진단용 raw 값)",
        60, "daily", True, "n<60 -> NaN",
        "60일 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "daily_ma120", "7.1_daily_ma_structure",
        "mean(close[-120:]) (진단용 raw 값)",
        120, "daily", True, "n<120 -> NaN",
        "120일 단순이동평균", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "daily_ma200", "7.1_daily_ma_structure",
        "mean(close[-200:]) (진단용 raw 값)",
        200, "daily", True, "n<200 -> NaN",
        "200일 단순이동평균(충분한 history가 있을 때만)", "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "close_vs_dma5_pct", "7.1_daily_ma_structure",
        "close[-1] / daily_ma5 - 1",
        5, "daily", True, "n<5 -> NaN",
        "초단기(5일) 이평 대비 현재가 위치",
        "§7.2 distance_from_dma5_pct와 동일값(재사용, 중복 미생성)",
    ),
    FeatureSpec(
        "close_vs_dma20_pct", "7.1_daily_ma_structure",
        "close[-1] / daily_ma20 - 1",
        20, "daily", True, "n<20 -> NaN",
        "단기(20일) 이평 대비 현재가 위치",
        "GOOD_TRIGGER가 TOO_EARLY보다 이 값이 안정적인가(Hyp A)",
    ),
    FeatureSpec(
        "close_vs_dma60_pct", "7.1_daily_ma_structure",
        "close[-1] / daily_ma60 - 1",
        60, "daily", True, "n<60 -> NaN",
        "중기(60일) 이평 대비 현재가 위치",
        "장기 Daily 추세와 충돌하는가",
    ),
    FeatureSpec(
        "close_vs_dma120_pct", "7.1_daily_ma_structure",
        "close[-1] / daily_ma120 - 1",
        120, "daily", True, "n<120 -> NaN",
        "장기(120일) 이평 대비 현재가 위치",
        "TOO_LATE/TOO_EXTENDED 구분에서 장기 이격도가 과도한가",
    ),
    FeatureSpec(
        "close_vs_dma200_pct", "7.1_daily_ma_structure",
        "close[-1] / daily_ma200 - 1",
        200, "daily", True, "n<200 -> NaN",
        "초장기(200일) 이평 대비 현재가 위치",
        "장기 저항/지지선 대비 위치",
    ),
    FeatureSpec(
        "dma5_vs_dma20_pct", "7.1_daily_ma_structure",
        "daily_ma5 / daily_ma20 - 1",
        20, "daily", True, "n<20 -> NaN",
        "초단기/단기 이평 상대 위치 — 정배열/역배열의 최단기 축",
        "돌파 직후 단기 정배열 전환이 보이는가",
    ),
    FeatureSpec(
        "dma20_vs_dma60_pct", "7.1_daily_ma_structure",
        "daily_ma20 / daily_ma60 - 1",
        60, "daily", True, "n<60 -> NaN",
        "단기/중기 이평 상대 위치",
        "SETUP 구간 단기 이평 구조 개선 여부",
    ),
    FeatureSpec(
        "dma60_vs_dma120_pct", "7.1_daily_ma_structure",
        "daily_ma60 / daily_ma120 - 1",
        120, "daily", True, "n<120 -> NaN",
        "중기/장기 이평 상대 위치",
        "장기 구조 개선이 중기 이평까지 확인되는가",
    ),
    FeatureSpec(
        "dma5_slope_1d", "7.1_daily_ma_structure",
        "mean(close[-5:])/mean(close[-6:-1]) - 1 (1일 전 대비 MA5 변화율)",
        6, "daily", True, "n<6 -> NaN",
        "초단기 이평의 최근 1일 기울기 변화",
        "단기 상승이 너무 급한가",
    ),
    FeatureSpec(
        "dma20_slope_1d", "7.1_daily_ma_structure",
        "mean(close[-20:])/mean(close[-21:-1]) - 1",
        21, "daily", True, "n<21 -> NaN",
        "단기 이평의 최근 1일 기울기 변화",
        "단기 이평이 회복 중인가",
    ),
    # --- 7.2 Short-Term Extension (distance_from_dmaN_pct는 §7.1 close_vs_dmaN_pct 재사용) ---
    FeatureSpec(
        "daily_return_5d", "7.2_short_term_extension",
        "close[-1] / close[-1-5] - 1",
        6, "daily", True, "n<6 -> NaN",
        "최근 5일 수익률(초단기 momentum)",
        "돌파 직후 momentum 강도",
    ),
    FeatureSpec(
        "daily_return_10d", "7.2_short_term_extension",
        "close[-1] / close[-1-10] - 1",
        11, "daily", True, "n<11 -> NaN",
        "최근 10일 수익률",
        "단기~중기 momentum",
    ),
    FeatureSpec(
        "daily_return_20d", "7.2_short_term_extension",
        "close[-1] / close[-1-20] - 1",
        21, "daily", True, "n<21 -> NaN",
        "최근 20일 수익률",
        "TOO_LATE/TOO_EXTENDED 구분(급등 여부)",
    ),
    FeatureSpec(
        "recent_5d_max_runup", "7.2_short_term_extension",
        "max(close[-5:]) / min(close[-5:]) - 1",
        5, "daily", True, "n<5 -> NaN",
        "최근 5일 내 최대 변동폭(저점 대비 고점 상승폭)",
        "Weekly는 좋지만 Daily는 이미 너무 급하게 오른 상태인가",
    ),
    FeatureSpec(
        "recent_10d_max_runup", "7.2_short_term_extension",
        "max(close[-10:]) / min(close[-10:]) - 1",
        10, "daily", True, "n<10 -> NaN",
        "최근 10일 내 최대 변동폭",
        "더 긴 창에서도 급등 흔적이 유지되는가",
    ),
    FeatureSpec(
        "consecutive_positive_days", "7.2_short_term_extension",
        "reference 일부터 역순으로 daily_return>0이 끊기지 않고 이어진 일 수",
        2, "daily", True, "n<2 -> NaN",
        "연속 상승일 수 — 값이 클수록 단기 과열",
        "TOO_LATE/TOO_EXTENDED sample의 연속 상승일이 더 긴가",
    ),
    # --- 7.3 Prior Daily High Proximity (current bar 반드시 제외) ---
    FeatureSpec(
        "distance_to_prior_10d_high_pct", "7.3_prior_high_proximity",
        "close[-1] / max(high[-11:-1]) - 1 (직전 10일, current 제외)",
        11, "daily", True, "n<11 -> NaN",
        "직전 10일 고점 대비 현재가 위치(0에 가까울수록 돌파 임박/직전)",
        "돌파 직전 이 값이 0에 수렴하는가",
    ),
    FeatureSpec(
        "distance_to_prior_20d_high_pct", "7.3_prior_high_proximity",
        "close[-1] / max(high[-21:-1]) - 1 (직전 20일, current 제외)",
        21, "daily", True, "n<21 -> NaN",
        "직전 20일 고점 대비 현재가 위치",
        "§7.4/§7.5 20일 breakout window와 동일 축",
    ),
    # --- 7.4 Daily Breakout State (20일 대표 window) ---
    FeatureSpec(
        "close_above_prior_20d_high", "7.4_daily_breakout_state",
        "1.0 if close[-1] > max(high[-21:-1]) else 0.0",
        21, "daily", True, "n<21 -> NaN",
        "종가 기준 직전 20일 고점 돌파 여부(boolean)",
        "13E에서 확인한 대로 희귀/상수에 가까울 수 있음 — 결과가 약하면 LOW/REJECTED 처리",
    ),
    FeatureSpec(
        "high_above_prior_20d_high", "7.4_daily_breakout_state",
        "1.0 if high[-1] > max(high[-21:-1]) else 0.0",
        21, "daily", True, "n<21 -> NaN",
        "고가 기준 직전 20일 고점 돌파 시도 여부(종가 미달 돌파 포함)",
        "종가 돌파와 고가 돌파 시도의 괴리가 있는 sample이 있는가",
    ),
    FeatureSpec(
        "close_breakout_strength_20d", "7.4_daily_breakout_state",
        "close[-1] / max(high[-21:-1]) - 1 (연속형, distance_to_prior_20d_high_pct와 동일 수식"
        " — breakout 여부와 무관하게 항상 계산되는 연속형 버전임을 명시)",
        21, "daily", True, "n<21 -> NaN",
        "돌파 강도(연속형) — distance_to_prior_20d_high_pct와 같은 값이지만 breakout family로 별도 분류",
        "boolean보다 연속형이 분리력이 더 나은가",
    ),
    # --- 7.5 Recent Daily Breakout Age (PIT-critical backward scan, 20일 대표 window) ---
    FeatureSpec(
        "days_since_20d_close_breakout", "7.5_daily_breakout_age",
        "current bar 기준 backward scan, offset 0..19(최근 20개 completed"
        " daily observation)로 제한: 각 candidate day i(offset=0..19)에서"
        " 그 시점 직전 20일 high(= max(high[i-20:i]), i 미포함)를 다시"
        " 계산하고 close[i] > prior_high[i]인 가장 최근 event까지의 일 수."
        " offset=0이면 current day 자체가 breakout. offset>=20의 event는"
        " 검색 대상이 아니다(Phase 13E Correction과 동일한 semantics를"
        " 재사용 — w.md §20 Daily Breakout Semantic Guard).",
        21, "daily", True, "최근 20일 search horizon 내 event 없음 -> NaN(NOT_OBSERVED)",
        "가장 최근 20일(offset 0..19) 이내의 고점 돌파가 몇 일 전이었는지",
        "GOOD_TRIGGER는 이 값이 작은가(최근 돌파), TOO_LATE는 큰가(horizon 내에서 오래된 돌파)",
    ),
    # --- 7.6 Daily Breakout Hold / Retest (breakout_level은 event 시점에 frozen) ---
    FeatureSpec(
        "post_breakout_min_close_vs_level_pct_20d", "7.6_daily_breakout_hold",
        "event(§7.5의 20일 search horizon 내 event) 다음 날부터 current bar까지"
        " 종가 중 최저값 / breakout_level - 1(event=current면 관찰 구간"
        " 없음 -> NaN, horizon 밖 event는 애초에 event로 취급 안 됨)",
        21, "daily", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 종가가 breakout level을 얼마나 지켰는지(최악 시점 기준)",
        "FALSE_TRIGGER는 이 값이 음수로 크게 내려가는가",
    ),
    FeatureSpec(
        "post_breakout_min_low_vs_level_pct_20d", "7.6_daily_breakout_hold",
        "event(§7.5) 다음 날부터 current bar까지 저가 중 최저값 / breakout_level - 1",
        21, "daily", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 저가 기준으로도 breakout level을 지켰는지(종가보다 보수적)",
        "장중 이탈은 있었지만 종가는 지킨 sample 구분 가능한가",
    ),
    FeatureSpec(
        "post_breakout_close_hold_ratio_20d", "7.6_daily_breakout_hold",
        "event(§7.5) 다음 날부터 current bar까지 (종가 > breakout_level)인 날의 비율(0~1)",
        21, "daily", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 지지에 성공한 날의 비율",
        "13D/13E와 동일하게 Cliff's Delta 1차 근거로 사용",
    ),
    FeatureSpec(
        "days_closed_above_breakout_level_20d", "7.6_daily_breakout_hold",
        "event(§7.5) 다음 날부터 current bar까지 (종가 > breakout_level)인 날의 개수(정수)",
        21, "daily", True, "event 없음 또는 관찰 구간 0 -> NaN",
        "돌파 이후 지지 마감일 수(절대 개수, post window 길이가 sample마다 달라 비율과 별도 참고)",
        "post_breakout_close_hold_ratio_20d와 함께 관찰 구간 길이 효과 분리",
    ),
    FeatureSpec(
        "close_back_below_breakout_level_20d", "7.6_daily_breakout_hold",
        "1.0 if (event 존재 and close[-1] < breakout_level) else 0.0"
        "(event 없으면 NaN)",
        21, "daily", True, "event 없음 -> NaN",
        "current bar 기준 돌파 레벨 아래로 종가가 이미 복귀했는지(boolean)",
        "FALSE_TRIGGER 판정의 가장 직접적인 machine 근사(Human Label 아님)",
    ),
    # --- 7.7 Pullback Quality (higher_daily_low_count_5d / rolling_low_5d_change는 §7.8과 공유) ---
    FeatureSpec(
        "pullback_from_20d_high_pct", "7.7_pullback_quality",
        "close[-1] / max(high[-20:]) - 1 (current bar 포함 20일 range)",
        20, "daily", True, "n<20 -> NaN",
        "최근 20일 고점 대비 현재 위치(급등 후 쉬어가는 눌림 정도)",
        "건강한 눌림(적당히 조정)과 추세 붕괴(과도한 조정)를 구분할 수 있는가",
    ),
    FeatureSpec(
        "close_vs_recent_5d_high_pct", "7.7_pullback_quality",
        "close[-1] / max(high[-5:]) - 1 (current bar 포함 5일 range)",
        5, "daily", True, "n<5 -> NaN",
        "최근 5일 고점 대비 현재 위치(초단기 눌림)",
        "돌파 직후인지 이미 눌림 중인지 구분",
    ),
    FeatureSpec(
        "days_since_20d_high", "7.7_pullback_quality",
        "(20-1) - argmax(high[-20:]) (current bar=0)",
        20, "daily", True, "n<20 -> NaN",
        "20일 고점을 찍은 지 며칠 지났는지",
        "고점 직후(눌림 시작)인지 오래전인지",
    ),
    FeatureSpec(
        "higher_daily_low_count_5d", "7.7_pullback_quality",
        "count(i in 1..4: low[-5:][i] > low[-5:][i-1])",
        5, "daily", True, "n<5 -> NaN",
        "최근 5일 중 전일 대비 저점이 높아진 날의 수(단순 카운트, pivot 정의 아님)",
        "§7.8 재사용 — '저점이 점점 높아짐' 관찰의 가장 단순한 연속형 근사(단기)",
    ),
    FeatureSpec(
        "rolling_low_5d_change", "7.7_pullback_quality",
        "min(low[-5:]) / min(low[-10:-5]) - 1 (최근 5일 최저 vs 그 이전 5일 최저)",
        10, "daily", True, "n<10 -> NaN",
        "§7.8 재사용 — 직전 5일 구간 대비 최근 5일 구간의 저점 상승률",
        "13E의 rolling_low_4w_change와 동일 개념의 daily 버전",
    ),
    # --- 7.8 Short-Term Support / Low Structure ---
    FeatureSpec(
        "days_since_10d_low", "7.8_support_low_structure",
        "(10-1) - argmin(low[-10:]) (current bar=0)",
        10, "daily", True, "n<10 -> NaN",
        "10일 저점을 찍은 지 며칠 지났는지",
        "최근 저점을 찍은 직후인가(아직 지지 검증 안 됨)",
    ),
    FeatureSpec(
        "days_since_20d_low", "7.8_support_low_structure",
        "(20-1) - argmin(low[-20:])",
        20, "daily", True, "n<20 -> NaN",
        "20일 저점을 찍은 지 며칠 지났는지",
        "더 긴 창에서 저점 확정 여부",
    ),
    FeatureSpec(
        "daily_low_slope_10d", "7.8_support_low_structure",
        "(low[-1] - low[-1-10]) / 10 / close[-1] (저점 시작-끝 단순 기울기, 10일 간격, 가격 스케일 정규화)",
        11, "daily", True, "n<11 -> NaN",
        "최근 10일 저점의 방향(양수=저점 상승 추세)",
        "higher_daily_low_count_10d와 상관/보완 관계 확인",
    ),
    FeatureSpec(
        "higher_daily_low_count_10d", "7.8_support_low_structure",
        "count(i in 1..9: low[-10:][i] > low[-10:][i-1])",
        10, "daily", True, "n<10 -> NaN",
        "최근 10일 중 higher-low count",
        "5일보다 긴 창에서도 유효한가",
    ),
    # --- 7.9 Daily Range Position ---
    FeatureSpec(
        "range_position_10d", "7.9_range_position",
        "(close[-1] - min(low[-10:])) / (max(high[-10:]) - min(low[-10:]))",
        10, "daily", True, "n<10 또는 range=0 -> NaN",
        "10일 range 내 현재 위치(0=하단, 1=상단)",
        "너무 낮으면 구조 약화, 중간이면 pullback, 너무 높으면 breakout/과열 — 단조 가정 금지(§31)",
    ),
    FeatureSpec(
        "range_position_20d", "7.9_range_position",
        "(close[-1] - min(low[-20:])) / (max(high[-20:]) - min(low[-20:]))",
        20, "daily", True, "n<20 또는 range=0 -> NaN",
        "20일 range 내 현재 위치",
        "GOOD_TRIGGER와 TOO_EXTENDED가 이 값에서 어떻게 갈리는가",
    ),
    # --- 7.10 Volatility / Risk ---
    FeatureSpec(
        "daily_true_range_pct", "7.10_volatility_risk",
        "max(high[-1]-low[-1], |high[-1]-close[-2]|, |low[-1]-close[-2]|) / close[-1]",
        2, "daily", True, "n<2 -> NaN",
        "current bar 단일 True Range(종가 대비 정규화)",
        "reference day 하루의 변동폭 자체가 이미 큰가",
    ),
    FeatureSpec(
        "atr_14_pct", "7.10_volatility_risk",
        "mean(daily_true_range[-14:]) / close[-1] (§23: 최근 14 completed"
        " daily TR의 평균, ATR/close로 정규화)",
        15, "daily", True, "n<15 -> NaN",
        "최근 14일 평균 변동성(종가 대비 정규화, 종목 간 비교 가능)",
        "GOOD_TRIGGER 시점은 FALSE/EXTENDED와 비교해 변동성이 더 안정적인가(Hyp D)",
    ),
    FeatureSpec(
        "realized_volatility_20d", "7.10_volatility_risk",
        "std(daily_return[-20:]) (20일 일간수익률의 표준편차)",
        21, "daily", True, "n<21 또는 return에 NaN 포함 -> NaN",
        "최근 20일 일간수익률 변동성",
        "ATR과 다른 각도(종가 기준)의 변동성 측정치",
    ),
    FeatureSpec(
        "gap_from_prev_close_pct", "7.10_volatility_risk",
        "open[-1] / close[-2] - 1",
        2, "daily", True, "n<2 -> NaN",
        "current bar 시가의 전일 종가 대비 갭",
        "돌파가 갭으로 발생했는가(장중 vs 갭)",
    ),
    FeatureSpec(
        "recent_5d_max_gap_abs_pct", "7.10_volatility_risk",
        "max(|open[-5:]/close.shift(1)[-5:] - 1|) (최근 5일 중 최대 절대 갭)",
        6, "daily", True, "n<6 -> NaN",
        "최근 5일 중 가장 컸던 갭의 절대값",
        "최근 변동성 급증(갭 빈발) 여부",
    ),
    # --- 7.11 Volume / Participation (Phase 11 foreign/institution flow와 독립) ---
    FeatureSpec(
        "volume_vs_20d_avg", "7.11_volume_participation",
        "volume[-1] / mean(volume[-21:-1]) (current day 분자, prior 20일 분모, current 제외)",
        21, "daily", True, "분모 0 또는 결측 -> NaN",
        "current day 거래량이 최근 20일 평균 대비 몇 배인지",
        "돌파/상승 시 거래 참여가 증가하고 있는가",
    ),
    FeatureSpec(
        "volume_5d_vs_prior_20d", "7.11_volume_participation",
        "mean(volume[-5:]) / mean(volume[-25:-5]) - 1 (최근 5일 평균 vs 그 이전 20일 평균)",
        25, "daily", True, "분모 0 또는 결측 -> NaN",
        "최근 5일 거래 참여가 그 이전 20일 대비 얼마나 늘었는지",
        "최근 국면 전환 시 거래대금이 실제로 증가하는가",
    ),
    FeatureSpec(
        "up_day_volume_ratio_10d", "7.11_volume_participation",
        "sum(volume[-10:] where daily_return>0) / sum(volume[-10:]) (상승일 거래량 비중)",
        11, "daily", True, "n<11 또는 총 거래량 0 -> NaN",
        "최근 10일 중 상승일에 거래량이 더 실렸는지",
        "건강한 전환은 상승일 거래 참여가 더 큰가(Hyp F)",
    ),
    # --- 7.12 Daily Candle Location ---
    FeatureSpec(
        "close_location_in_daily_range", "7.12_daily_candle_location",
        "(close[-1] - low[-1]) / (high[-1] - low[-1])",
        1, "daily", True, "high==low -> NaN",
        "current bar 캔들 내 종가 위치(0=저가권, 1=고가권)",
        "장대 양봉 종가 고가권 / 윗꼬리 실패 / 아랫꼬리 지지 구분",
    ),
    FeatureSpec(
        "daily_body_pct", "7.12_daily_candle_location",
        "|close[-1] - open[-1]| / close[-1]",
        1, "daily", True, "close==0 -> NaN",
        "current bar 캔들 몸통 크기(종가 대비 정규화)",
        "실체가 큰 결정적인 하루였는가",
    ),
    FeatureSpec(
        "upper_wick_pct", "7.12_daily_candle_location",
        "(high[-1] - max(open[-1],close[-1])) / close[-1]",
        1, "daily", True, "close==0 -> NaN",
        "current bar 윗꼬리 크기(종가 대비 정규화)",
        "고점에서 매도 압력에 밀린 윗꼬리 실패 흔적",
    ),
    FeatureSpec(
        "lower_wick_pct", "7.12_daily_candle_location",
        "(min(open[-1],close[-1]) - low[-1]) / close[-1]",
        1, "daily", True, "close==0 -> NaN",
        "current bar 아랫꼬리 크기(종가 대비 정규화)",
        "저점에서 매수세 유입에 의한 아랫꼬리 지지 흔적",
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)
DIAGNOSTIC_ONLY_FEATURES: frozenset[str] = frozenset(
    {"daily_ma5", "daily_ma20", "daily_ma60", "daily_ma120", "daily_ma200"}
)


def _tail_or_none(series: pd.Series, k: int) -> pd.Series | None:
    if len(series) < k:
        return None
    return series.iloc[-k:]


def _find_breakout_event(
    close: pd.Series, high: pd.Series, k: int, search_horizon: int
) -> tuple[int, float] | None:
    """current bar(마지막 행)부터 backward로 최대 ``search_horizon``개
    candidate day만 스캔해(offset 0..search_horizon-1), 각 과거 day i에서
    그 시점 기준 직전 k일 high(= high.iloc[i-k:i].max(), i 미포함)를 다시
    계산하고 close.iloc[i] > prior_high_at_i인 가장 최근 event를 찾는다.

    Phase 13E Correction에서 발견된 stale-event 버그(w.md §20 Daily
    Breakout Semantic Guard)를 처음부터 재발시키지 않기 위해
    ``search_horizon``을 필수 위치 인자로 강제한다(기본값 없음 — 호출부가
    horizon을 실수로 생략할 수 없다). search_horizon 밖의 event는 존재해도
    무시하고 None을 반환한다(NOT_OBSERVED와 동일하게 처리).

    current bar 자체(offset=0)도 breakout 후보에 포함한다 — "방금 돌파"도
    유효한 event다. 반환값은 (event의 positional index, 그 시점의
    breakout_level) 또는 event가 없으면 None. i-k:i 슬라이스는 항상 i(검사
    대상 day) 자체의 high/close를 포함하지 않으므로, 당해 day의 고가가
    자기 자신의 prior high 계산에 leak되는 버그를 구조적으로 방지한다.
    """
    n = len(close)
    if n < k + 1:
        return None
    for offset in range(0, min(n - k, search_horizon)):
        i = n - 1 - offset
        if i < k:
            break
        prior_high_at_i = high.iloc[i - k : i].max()
        if close.iloc[i] > prior_high_at_i:
            return i, float(prior_high_at_i)
    return None


def compute_daily_timing_features(daily: pd.DataFrame) -> dict[str, float]:
    """PIT-sliced daily OHLCV(``daily.index`` 전부 ``reference_date`` 이하,
    마지막 행이 current bar — 실증적으로는 40개 샘플 전부 reference_date
    자신)로부터 §7 후보 Feature를 계산한다.

    호출자는 반드시 ``daily``가 이미 ``daily[daily.index <= reference_date]``
    로 슬라이스된 데이터임을 보장해야 한다(이 함수 자체는 그 보장을
    강제하지 않는다 — leakage 방지는 상위 호출부의 책임이며 targeted test로
    검증한다). 함수 시그니처는 의도적으로 ``daily`` 하나만 받는다 —
    human_label / weekly_stage_at_reference / trigger_event_date /
    outcome_review_end 등은 입력으로 존재하지 않는다(w.md §5).
    """
    close = daily["close"]
    high = daily["high"]
    low = daily["low"]
    open_ = daily["open"]
    volume = daily["volume"]
    n = len(daily)
    out: dict[str, float] = {name: np.nan for name in FEATURE_NAMES}

    def dma(k: int) -> float:
        w = _tail_or_none(close, k)
        if w is None:
            return np.nan
        return float(w.mean())

    ma5, ma20, ma60, ma120, ma200 = dma(5), dma(20), dma(60), dma(120), dma(200)
    out["daily_ma5"], out["daily_ma20"], out["daily_ma60"] = ma5, ma20, ma60
    out["daily_ma120"], out["daily_ma200"] = ma120, ma200

    def close_vs_pct(ma_value: float) -> float:
        if np.isnan(ma_value):
            return np.nan
        return float(close.iloc[-1] / ma_value - 1.0)

    out["close_vs_dma5_pct"] = close_vs_pct(ma5)
    out["close_vs_dma20_pct"] = close_vs_pct(ma20)
    out["close_vs_dma60_pct"] = close_vs_pct(ma60)
    out["close_vs_dma120_pct"] = close_vs_pct(ma120)
    out["close_vs_dma200_pct"] = close_vs_pct(ma200)

    if not np.isnan(ma5) and not np.isnan(ma20):
        out["dma5_vs_dma20_pct"] = float(ma5 / ma20 - 1.0)
    if not np.isnan(ma20) and not np.isnan(ma60):
        out["dma20_vs_dma60_pct"] = float(ma20 / ma60 - 1.0)
    if not np.isnan(ma60) and not np.isnan(ma120):
        out["dma60_vs_dma120_pct"] = float(ma60 / ma120 - 1.0)

    def dma_slope_1d(k: int) -> float:
        if n < k + 1:
            return np.nan
        ma_now = close.iloc[-k:].mean()
        ma_prev = close.iloc[-k - 1 : -1].mean()
        if ma_prev == 0:
            return np.nan
        return float(ma_now / ma_prev - 1.0)

    out["dma5_slope_1d"] = dma_slope_1d(5)
    out["dma20_slope_1d"] = dma_slope_1d(20)

    def ret(k: int) -> float:
        if n < k + 1:
            return np.nan
        return float(close.iloc[-1] / close.iloc[-1 - k] - 1.0)

    out["daily_return_5d"] = ret(5)
    out["daily_return_10d"] = ret(10)
    out["daily_return_20d"] = ret(20)

    w5 = _tail_or_none(close, 5)
    if w5 is not None and w5.min() > 0:
        out["recent_5d_max_runup"] = float(w5.max() / w5.min() - 1.0)
    w10 = _tail_or_none(close, 10)
    if w10 is not None and w10.min() > 0:
        out["recent_10d_max_runup"] = float(w10.max() / w10.min() - 1.0)

    daily_return = close.pct_change()
    if n >= 2:
        streak = 0
        returns = daily_return.iloc[1:]
        for r in reversed(returns.tolist()):
            if np.isnan(r) or r <= 0:
                break
            streak += 1
        out["consecutive_positive_days"] = float(streak)

    def prior_high(k: int) -> float:
        if n < k + 1:
            return np.nan
        return float(high.iloc[-(k + 1) : -1].max())

    ph10, ph20 = prior_high(10), prior_high(20)
    if not np.isnan(ph10):
        out["distance_to_prior_10d_high_pct"] = float(close.iloc[-1] / ph10 - 1.0)
    if not np.isnan(ph20):
        out["distance_to_prior_20d_high_pct"] = float(close.iloc[-1] / ph20 - 1.0)
        out["close_above_prior_20d_high"] = 1.0 if close.iloc[-1] > ph20 else 0.0
        out["high_above_prior_20d_high"] = 1.0 if high.iloc[-1] > ph20 else 0.0
        out["close_breakout_strength_20d"] = float(close.iloc[-1] / ph20 - 1.0)

    event = _find_breakout_event(close, high, 20, 20)
    if event is not None:
        i_event, breakout_level = event
        offset = float((n - 1) - i_event)
        out["days_since_20d_close_breakout"] = offset

        post_start, post_end = i_event + 1, n
        if post_start < post_end:
            post_close = close.iloc[post_start:post_end]
            post_low = low.iloc[post_start:post_end]
            out["post_breakout_min_close_vs_level_pct_20d"] = float(post_close.min() / breakout_level - 1.0)
            out["post_breakout_min_low_vs_level_pct_20d"] = float(post_low.min() / breakout_level - 1.0)
            hold_count = int((post_close > breakout_level).sum())
            out["post_breakout_close_hold_ratio_20d"] = float(hold_count / len(post_close))
            out["days_closed_above_breakout_level_20d"] = float(hold_count)
        out["close_back_below_breakout_level_20d"] = 1.0 if close.iloc[-1] < breakout_level else 0.0

    w20_high = _tail_or_none(high, 20)
    if w20_high is not None:
        out["pullback_from_20d_high_pct"] = float(close.iloc[-1] / w20_high.max() - 1.0)
    w5_high = _tail_or_none(high, 5)
    if w5_high is not None:
        out["close_vs_recent_5d_high_pct"] = float(close.iloc[-1] / w5_high.max() - 1.0)

    def days_since_high(k: int) -> float:
        w = _tail_or_none(high, k)
        if w is None:
            return np.nan
        idx_max = int(np.argmax(w.to_numpy()))
        return float((k - 1) - idx_max)

    out["days_since_20d_high"] = days_since_high(20)

    def higher_low_count(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        vals = w.to_numpy()
        return float(sum(1 for i in range(1, len(vals)) if vals[i] > vals[i - 1]))

    out["higher_daily_low_count_5d"] = higher_low_count(5)
    out["higher_daily_low_count_10d"] = higher_low_count(10)

    def rolling_low_change(k: int) -> float:
        if n < 2 * k:
            return np.nan
        current = low.iloc[-k:].min()
        prior = low.iloc[-2 * k : -k].min()
        if prior <= 0:
            return np.nan
        return float(current / prior - 1.0)

    out["rolling_low_5d_change"] = rolling_low_change(5)

    def days_since_low(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        idx_min = int(np.argmin(w.to_numpy()))
        return float((k - 1) - idx_min)

    out["days_since_10d_low"] = days_since_low(10)
    out["days_since_20d_low"] = days_since_low(20)

    def low_slope(k: int) -> float:
        if n < k + 1 or close.iloc[-1] == 0:
            return np.nan
        return float((low.iloc[-1] - low.iloc[-1 - k]) / k / close.iloc[-1])

    out["daily_low_slope_10d"] = low_slope(10)

    def range_position(k: int) -> float:
        hi_w = _tail_or_none(high, k)
        lo_w = _tail_or_none(low, k)
        if hi_w is None or lo_w is None:
            return np.nan
        hi, lo = hi_w.max(), lo_w.min()
        if hi <= lo:
            return np.nan
        return float((close.iloc[-1] - lo) / (hi - lo))

    out["range_position_10d"] = range_position(10)
    out["range_position_20d"] = range_position(20)

    if n >= 2:
        prev_close = close.iloc[-2]
        tr = max(
            high.iloc[-1] - low.iloc[-1],
            abs(high.iloc[-1] - prev_close),
            abs(low.iloc[-1] - prev_close),
        )
        if close.iloc[-1] != 0:
            out["daily_true_range_pct"] = float(tr / close.iloc[-1])
        if prev_close != 0:
            out["gap_from_prev_close_pct"] = float(open_.iloc[-1] / prev_close - 1.0)

    if n >= 15:
        prev_close_series = close.shift(1)
        tr_series = pd.concat(
            [
                high - low,
                (high - prev_close_series).abs(),
                (low - prev_close_series).abs(),
            ],
            axis=1,
        ).max(axis=1)
        tr14 = tr_series.iloc[-14:]
        if tr14.notna().all() and close.iloc[-1] != 0:
            out["atr_14_pct"] = float(tr14.mean() / close.iloc[-1])

    ret21 = _tail_or_none(daily_return, 21)
    if ret21 is not None and ret21.iloc[1:].notna().all():
        out["realized_volatility_20d"] = float(ret21.iloc[1:].std())

    if n >= 6:
        prev_close_series = close.shift(1)
        gap_series = (open_ / prev_close_series - 1.0).iloc[-5:]
        if gap_series.notna().all():
            out["recent_5d_max_gap_abs_pct"] = float(gap_series.abs().max())

    if n >= 21:
        vol_window = volume.iloc[-21:-1]
        cur_vol = volume.iloc[-1]
        if vol_window.notna().all() and vol_window.mean() > 0 and pd.notna(cur_vol):
            out["volume_vs_20d_avg"] = float(cur_vol / vol_window.mean())

    if n >= 25:
        recent5 = volume.iloc[-5:]
        prior20 = volume.iloc[-25:-5]
        if recent5.notna().all() and prior20.notna().all() and prior20.mean() > 0:
            out["volume_5d_vs_prior_20d"] = float(recent5.mean() / prior20.mean() - 1.0)

    if n >= 11:
        w10_ret = daily_return.iloc[-10:]
        w10_vol = volume.iloc[-10:]
        if w10_ret.notna().all() and w10_vol.notna().all() and w10_vol.sum() > 0:
            up_vol = w10_vol[w10_ret > 0].sum()
            out["up_day_volume_ratio_10d"] = float(up_vol / w10_vol.sum())

    day_range = high.iloc[-1] - low.iloc[-1]
    if day_range > 0:
        out["close_location_in_daily_range"] = float((close.iloc[-1] - low.iloc[-1]) / day_range)
    if close.iloc[-1] != 0:
        out["daily_body_pct"] = float(abs(close.iloc[-1] - open_.iloc[-1]) / close.iloc[-1])
        out["upper_wick_pct"] = float((high.iloc[-1] - max(open_.iloc[-1], close.iloc[-1])) / close.iloc[-1])
        out["lower_wick_pct"] = float((min(open_.iloc[-1], close.iloc[-1]) - low.iloc[-1]) / close.iloc[-1])

    return out
