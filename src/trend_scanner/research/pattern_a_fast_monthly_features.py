"""Phase 13D — Pattern A Fast Monthly Regime Feature Candidates (RESEARCH ONLY).

Purely descriptive, deterministic feature functions over a PIT-sliced
completed-monthly OHLCV DataFrame (as produced by
``trend_scanner.validation.historical_snapshot.build_historical_snapshot``).
Nothing here is a Production Rule / Threshold / Score / Classifier — see
docs/validation/pattern_a_fast_monthly_regime_feature_research_v01.md for
the research findings and the explicit "No Threshold Frozen" declaration.

This module must never be imported by ``trend_scanner.patterns`` (production
evaluator) or by the scanner pipeline (w.md §19).

All windows are **bar-count based** (``iloc[-n:]``), not calendar-month
based — with halted-trading gaps the two can diverge, so "지난 12개월"
문구는 실제로는 "최근 12개 completed monthly bar"를 뜻한다.
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
    # --- 6.1 Long-Term Return / Drawdown ---
    FeatureSpec(
        "return_6m", "6.1_long_term_return_drawdown",
        "close[-1] / close[-1-6] - 1 (최근 6개 completed monthly bar 수익률)",
        7, "monthly", True, "n<7 -> NaN",
        "최근 6개월 장기 추세 방향/크기",
        "Q1/Q2: Positive sample의 최근 6개월 수익률이 TOO_EARLY/NO_SETUP보다 높은가?",
    ),
    FeatureSpec(
        "return_12m", "6.1_long_term_return_drawdown",
        "close[-1] / close[-1-12] - 1",
        13, "monthly", True, "n<13 -> NaN",
        "최근 12개월 장기 추세",
        "Q1/Q2: 장기 상승/하락 방향이 label과 관련 있는가?",
    ),
    FeatureSpec(
        "return_24m", "6.1_long_term_return_drawdown",
        "close[-1] / close[-1-24] - 1",
        25, "monthly", True, "n<25 -> NaN",
        "최근 24개월 장기 추세",
        "Q1/Q2: 더 긴 창에서도 같은 방향성이 유지되는가?",
    ),
    FeatureSpec(
        "drawdown_from_12m_high", "6.1_long_term_return_drawdown",
        "close[-1] / max(high[-12:]) - 1 (0 이하, 0에 가까울수록 고점 근접)",
        12, "monthly", True, "n<12 -> NaN",
        "최근 12개월 고점 대비 현재 낙폭 — 이미 조정이 많이 됐는지",
        "Q3: TOO_EXTENDED/TOO_LATE sample은 이 값이 0에 가까운가(고점 근접)?",
    ),
    FeatureSpec(
        "drawdown_from_24m_high", "6.1_long_term_return_drawdown",
        "close[-1] / max(high[-24:]) - 1",
        24, "monthly", True, "n<24 -> NaN",
        "최근 24개월 고점 대비 낙폭",
        "Q3: 더 긴 창에서도 Extended 여부가 구분되는가?",
    ),
    FeatureSpec(
        "drawdown_from_36m_high", "6.1_long_term_return_drawdown",
        "close[-1] / max(high[-36:]) - 1",
        36, "monthly", True, "n<36 -> NaN",
        "최근 36개월 고점 대비 낙폭",
        "Q3: 36개월 스케일에서도 유효한 신호인가?",
    ),
    FeatureSpec(
        "distance_from_12m_low", "6.1_long_term_return_drawdown",
        "close[-1] / min(low[-12:]) - 1 (0 이상, 0에 가까울수록 저점 근접)",
        12, "monthly", True, "n<12 -> NaN",
        "최근 12개월 저점 대비 현재 위치 — 바닥권 여부",
        "Q5: 역배열/장기하락 관찰을 이 수치로 설명할 수 있는가?",
    ),
    FeatureSpec(
        "distance_from_24m_low", "6.1_long_term_return_drawdown",
        "close[-1] / min(low[-24:]) - 1",
        24, "monthly", True, "n<24 -> NaN",
        "최근 24개월 저점 대비 현재 위치",
        "Q5: 더 긴 창에서도 바닥권 여부가 유효한가?",
    ),
    # --- 6.2 Monthly Moving Average Structure ---
    FeatureSpec(
        "monthly_ma6", "6.2_monthly_ma_structure",
        "mean(close[-6:])", 6, "monthly", True, "n<6 -> NaN",
        "6개월 단순이동평균(진단용 raw 값, 순위분석 대상 아님)",
        "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "monthly_ma12", "6.2_monthly_ma_structure",
        "mean(close[-12:])", 12, "monthly", True, "n<12 -> NaN",
        "12개월 단순이동평균(진단용 raw 값, 순위분석 대상 아님)",
        "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "monthly_ma24", "6.2_monthly_ma_structure",
        "mean(close[-24:])", 24, "monthly", True, "n<24 -> NaN",
        "24개월 단순이동평균(진단용 raw 값, 순위분석 대상 아님)",
        "다른 MA파생 feature 계산의 기반",
    ),
    FeatureSpec(
        "close_vs_ma6_pct", "6.2_monthly_ma_structure",
        "close[-1] / monthly_ma6 - 1",
        6, "monthly", True, "n<6 -> NaN",
        "단기(6개월) 이평 대비 현재가 위치",
        "Q2/Q3: Positive/Extended sample의 단기 이평 이격도 차이",
    ),
    FeatureSpec(
        "close_vs_ma12_pct", "6.2_monthly_ma_structure",
        "close[-1] / monthly_ma12 - 1",
        12, "monthly", True, "n<12 -> NaN",
        "중기(12개월) 이평 대비 현재가 위치",
        "Q2/Q3: 중기 이평 이격도가 label을 구분하는가",
    ),
    FeatureSpec(
        "close_vs_ma24_pct", "6.2_monthly_ma_structure",
        "close[-1] / monthly_ma24 - 1",
        24, "monthly", True, "n<24 -> NaN",
        "장기(24개월) 이평 대비 현재가 위치 — '주봉 200MA 저항' 관찰의 월봉판 근사",
        "Q7: Monthly 스케일에서 장기 이평 저항을 일부라도 설명 가능한가",
    ),
    FeatureSpec(
        "ma6_slope_1m", "6.2_monthly_ma_structure",
        "mean(close[-6:])/mean(close[-7:-1]) - 1 (1개월 전 대비 MA6 변화율)",
        7, "monthly", True, "n<7 -> NaN",
        "단기 이평의 최근 1개월 기울기 변화",
        "Q6: 이평 기울기가 개선/악화 중인지가 label과 관련 있는가",
    ),
    FeatureSpec(
        "ma12_slope_1m", "6.2_monthly_ma_structure",
        "mean(close[-12:])/mean(close[-13:-1]) - 1",
        13, "monthly", True, "n<13 -> NaN",
        "중기 이평의 최근 1개월 기울기 변화",
        "Q6: 중기 이평 기울기 방향",
    ),
    FeatureSpec(
        "ma24_slope_1m", "6.2_monthly_ma_structure",
        "mean(close[-24:])/mean(close[-25:-1]) - 1",
        25, "monthly", True, "n<25 -> NaN",
        "장기 이평의 최근 1개월 기울기 변화",
        "Q6: 장기 이평 기울기 방향",
    ),
    # --- 6.3 MA Alignment / Compression ---
    FeatureSpec(
        "ma_alignment_score", "6.3_ma_alignment_compression",
        "ma6>ma12>ma24 -> +1(정배열) / ma6<ma12<ma24 -> -1(역배열) / 그외 -> 0(엉킴)",
        24, "monthly", True, "n<24 -> NaN",
        "정배열/역배열/엉킴을 -1/0/+1 순서형 값으로 표현(Rule 아님, metadata)",
        "Q5: '역배열+장기하락' Human Observation을 이 값으로 표현 가능한가",
    ),
    FeatureSpec(
        "ma_spread_pct", "6.3_ma_alignment_compression",
        "(max(ma6,ma12,ma24) - min(ma6,ma12,ma24)) / close[-1]",
        24, "monthly", True, "n<24 -> NaN",
        "세 이평선이 얼마나 벌어져 있는지(압축/확산)",
        "Q5: 이평선 엉킴(압축)이 WATCH/SETUP 경계와 관련 있는가",
    ),
    FeatureSpec(
        "max_ma_gap_pct", "6.3_ma_alignment_compression",
        "max(|ma6-ma12|, |ma12-ma24|, |ma6-ma24|) / close[-1]",
        24, "monthly", True, "n<24 -> NaN",
        "이평선 쌍 중 가장 크게 벌어진 간격",
        "ma_spread_pct와 함께 압축/확산 정도 교차검증",
    ),
    FeatureSpec(
        "min_ma_gap_pct", "6.3_ma_alignment_compression",
        "min(|ma6-ma12|, |ma12-ma24|, |ma6-ma24|) / close[-1]",
        24, "monthly", True, "n<24 -> NaN",
        "이평선 쌍 중 가장 근접한 간격 — 이평선 수렴(엉킴) 정도",
        "Q5: '이평선 엉킴' 관찰과 대응되는가",
    ),
    FeatureSpec(
        "close_above_ma_count", "6.3_ma_alignment_compression",
        "count({ma6,ma12,ma24} 중 close[-1] > ma)",
        24, "monthly", True, "n<24 -> NaN",
        "현재가가 몇 개의 장기 이평선 위에 있는지(0~3)",
        "Q7: 이평선 저항 개수와 label의 관계",
    ),
    FeatureSpec(
        "close_below_ma_count", "6.3_ma_alignment_compression",
        "count({ma6,ma12,ma24} 중 close[-1] < ma)",
        24, "monthly", True, "n<24 -> NaN",
        "'현재가 위에 장기 이평선이 다수 존재'라는 Human Observation의 직접 대응",
        "Q5/Q7: 이 값이 클수록 WATCH/NO_SETUP인가",
    ),
    # --- 6.4 Long-Term Range Position ---
    FeatureSpec(
        "range_position_12m", "6.4_long_term_range_position",
        "(close[-1] - min(low[-12:])) / (max(high[-12:]) - min(low[-12:]))",
        12, "monthly", True, "n<12 또는 range=0 -> NaN",
        "12개월 range 내 현재 위치(0=하단, 1=상단)",
        "Q1/Q3: Positive/Extended sample의 range 내 위치 차이",
    ),
    FeatureSpec(
        "range_position_24m", "6.4_long_term_range_position",
        "(close[-1] - min(low[-24:])) / (max(high[-24:]) - min(low[-24:]))",
        24, "monthly", True, "n<24 또는 range=0 -> NaN",
        "24개월 range 내 현재 위치",
        "Q1/Q3: 더 긴 창에서도 유지되는가",
    ),
    FeatureSpec(
        "range_position_36m", "6.4_long_term_range_position",
        "(close[-1] - min(low[-36:])) / (max(high[-36:]) - min(low[-36:]))",
        36, "monthly", True, "n<36 또는 range=0 -> NaN",
        "36개월 range 내 현재 위치",
        "Q1/Q3: 36개월 스케일에서도 유효한가",
    ),
    # --- 6.5 Recovery / Bottoming Proxy ---
    FeatureSpec(
        "months_since_12m_low", "6.5_recovery_bottoming_proxy",
        "(12-1) - argmin(low[-12:]) (최근월=0)",
        12, "monthly", True, "n<12 -> NaN",
        "12개월 저점을 찍은 지 몇 개월 지났는지",
        "Q6: '바닥이 아직 없다'는 관찰과 대응 — 값이 작을수록 최근에 저점",
    ),
    FeatureSpec(
        "months_since_24m_low", "6.5_recovery_bottoming_proxy",
        "(24-1) - argmin(low[-24:])",
        24, "monthly", True, "n<24 -> NaN",
        "24개월 저점을 찍은 지 몇 개월 지났는지",
        "Q6: 더 긴 창에서 바닥 확정 여부",
    ),
    FeatureSpec(
        "higher_monthly_low_count_12m", "6.5_recovery_bottoming_proxy",
        "count(i in 1..11: low[-12:][i] > low[-12:][i-1])",
        12, "monthly", True, "n<12 -> NaN",
        "최근 12개월 중 전월 대비 저점이 높아진 달의 수(단순 카운트, pivot 정의 아님)",
        "Q5: 'higher low' 관찰의 가장 단순한 연속형 근사",
    ),
    # --- 6.6 Trend Deceleration / Reversal ---
    FeatureSpec(
        "ma12_slope_change_3m", "6.6_trend_deceleration_reversal",
        "ma12_slope_1m(now) - ma12_slope_1m(3개월 전 시점)",
        16, "monthly", True, "n<16 -> NaN",
        "중기 이평 기울기가 최근 3개월 사이 개선/악화됐는지",
        "Q4/Q6: 장기 하락이 둔화되는 중인지 표현",
    ),
    FeatureSpec(
        "recent_3m_return_vs_prior_9m", "6.6_trend_deceleration_reversal",
        "mean(monthly_return[-3:]) - mean(monthly_return[-12:-3])",
        13, "monthly", True, "n<13 -> NaN",
        "최근 3개월 평균 월수익률 - 그 이전 9개월 평균 월수익률(추세 가속/감속)",
        "Q4: WATCH -> GOOD/BORDERLINE 전환 직전 가속 신호가 있는가",
    ),
    FeatureSpec(
        "monthly_down_month_ratio_6m", "6.6_trend_deceleration_reversal",
        "count(monthly_return[-6:] < 0) / 6",
        7, "monthly", True, "n<7 -> NaN",
        "최근 6개월 중 하락 마감한 달의 비율",
        "Q2: NO_SETUP sample이 이 비율이 더 높은가",
    ),
    FeatureSpec(
        "monthly_down_month_ratio_12m", "6.6_trend_deceleration_reversal",
        "count(monthly_return[-12:] < 0) / 12",
        13, "monthly", True, "n<13 -> NaN",
        "최근 12개월 중 하락 마감한 달의 비율",
        "Q2: 더 긴 창에서도 유지되는가",
    ),
    FeatureSpec(
        "monthly_up_month_ratio_6m", "6.6_trend_deceleration_reversal",
        "count(monthly_return[-6:] > 0) / 6",
        7, "monthly", True, "n<7 -> NaN",
        "최근 6개월 중 상승 마감한 달의 비율",
        "monthly_down_month_ratio_6m과의 상관/중복성 확인용",
    ),
    # --- 6.7 Extended / Overheated Monthly Position ---
    FeatureSpec(
        "recent_3m_return", "6.7_extended_overheated_position",
        "close[-1] / close[-4] - 1",
        4, "monthly", True, "n<4 -> NaN",
        "최근 3개월 수익률 — 단기 과열 여부",
        "Q3: TOO_EXTENDED sample이 이 값이 유독 큰가",
    ),
    FeatureSpec(
        "recent_6m_max_runup", "6.7_extended_overheated_position",
        "max(close[-6:]) / min(close[-6:]) - 1",
        6, "monthly", True, "n<6 -> NaN",
        "최근 6개월 내 최대 변동폭(저점 대비 고점 상승폭)",
        "Q3: Extended sample은 최근 급등 흔적이 있는가",
    ),
    FeatureSpec(
        "consecutive_positive_months", "6.7_extended_overheated_position",
        "reference월부터 역순으로 monthly_return>0이 끊기지 않고 이어진 개월 수",
        2, "monthly", True, "n<2 -> NaN",
        "연속 상승 개월 수 — 값이 클수록 단기 과열/연속 상승",
        "Q3: TOO_EXTENDED/TOO_LATE sample의 연속 상승 개월 수가 더 긴가",
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)
DIAGNOSTIC_ONLY_FEATURES: frozenset[str] = frozenset(
    {"monthly_ma6", "monthly_ma12", "monthly_ma24"}
)


def _tail_or_none(series: pd.Series, k: int) -> pd.Series | None:
    if len(series) < k:
        return None
    return series.iloc[-k:]


def compute_monthly_regime_features(monthly: pd.DataFrame) -> dict[str, float]:
    """PIT-sliced completed-monthly OHLCV(``monthly.index`` 전부
    ``reference_date`` 이하)로부터 §6 후보 Feature를 계산한다.

    호출자는 반드시 ``monthly``가 이미 reference_date 이하로 슬라이스된
    completed-period 데이터임을 보장해야 한다(이 함수 자체는 그 보장을
    강제하지 않는다 — leakage 방지는 상위 호출부의 책임이며
    targeted test로 검증한다).
    """
    close = monthly["close"]
    high = monthly["high"]
    low = monthly["low"]
    n = len(monthly)
    out: dict[str, float] = {name: np.nan for name in FEATURE_NAMES}

    def ret(k: int) -> float:
        if n < k + 1:
            return np.nan
        return float(close.iloc[-1] / close.iloc[-1 - k] - 1.0)

    out["return_6m"] = ret(6)
    out["return_12m"] = ret(12)
    out["return_24m"] = ret(24)

    def drawdown_from_high(k: int) -> float:
        w = _tail_or_none(high, k)
        if w is None:
            return np.nan
        return float(close.iloc[-1] / w.max() - 1.0)

    out["drawdown_from_12m_high"] = drawdown_from_high(12)
    out["drawdown_from_24m_high"] = drawdown_from_high(24)
    out["drawdown_from_36m_high"] = drawdown_from_high(36)

    def distance_from_low(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        return float(close.iloc[-1] / w.min() - 1.0)

    out["distance_from_12m_low"] = distance_from_low(12)
    out["distance_from_24m_low"] = distance_from_low(24)

    def ma(k: int) -> float:
        w = _tail_or_none(close, k)
        if w is None:
            return np.nan
        return float(w.mean())

    ma6, ma12, ma24 = ma(6), ma(12), ma(24)
    out["monthly_ma6"], out["monthly_ma12"], out["monthly_ma24"] = ma6, ma12, ma24

    def close_vs_ma_pct(ma_value: float) -> float:
        if np.isnan(ma_value):
            return np.nan
        return float(close.iloc[-1] / ma_value - 1.0)

    out["close_vs_ma6_pct"] = close_vs_ma_pct(ma6)
    out["close_vs_ma12_pct"] = close_vs_ma_pct(ma12)
    out["close_vs_ma24_pct"] = close_vs_ma_pct(ma24)

    def ma_slope_1m(k: int) -> float:
        if n < k + 1:
            return np.nan
        ma_now = close.iloc[-k:].mean()
        ma_prev = close.iloc[-k - 1 : -1].mean()
        if ma_prev == 0:
            return np.nan
        return float(ma_now / ma_prev - 1.0)

    out["ma6_slope_1m"] = ma_slope_1m(6)
    out["ma12_slope_1m"] = ma_slope_1m(12)
    out["ma24_slope_1m"] = ma_slope_1m(24)

    if not any(np.isnan(x) for x in (ma6, ma12, ma24)):
        if ma6 > ma12 > ma24:
            out["ma_alignment_score"] = 1.0
        elif ma6 < ma12 < ma24:
            out["ma_alignment_score"] = -1.0
        else:
            out["ma_alignment_score"] = 0.0

        gaps = [abs(ma6 - ma12), abs(ma12 - ma24), abs(ma6 - ma24)]
        out["ma_spread_pct"] = float((max(ma6, ma12, ma24) - min(ma6, ma12, ma24)) / close.iloc[-1])
        out["max_ma_gap_pct"] = float(max(gaps) / close.iloc[-1])
        out["min_ma_gap_pct"] = float(min(gaps) / close.iloc[-1])

        current = float(close.iloc[-1])
        mas = (ma6, ma12, ma24)
        out["close_above_ma_count"] = float(sum(1 for m in mas if current > m))
        out["close_below_ma_count"] = float(sum(1 for m in mas if current < m))

    def range_position(k: int) -> float:
        hi_w = _tail_or_none(high, k)
        lo_w = _tail_or_none(low, k)
        if hi_w is None or lo_w is None:
            return np.nan
        hi, lo = hi_w.max(), lo_w.min()
        if hi <= lo:
            return np.nan
        return float((close.iloc[-1] - lo) / (hi - lo))

    out["range_position_12m"] = range_position(12)
    out["range_position_24m"] = range_position(24)
    out["range_position_36m"] = range_position(36)

    def months_since_low(k: int) -> float:
        w = _tail_or_none(low, k)
        if w is None:
            return np.nan
        idx_min = int(np.argmin(w.to_numpy()))
        return float((k - 1) - idx_min)

    out["months_since_12m_low"] = months_since_low(12)
    out["months_since_24m_low"] = months_since_low(24)

    w12 = _tail_or_none(low, 12)
    if w12 is not None:
        vals = w12.to_numpy()
        out["higher_monthly_low_count_12m"] = float(sum(1 for i in range(1, len(vals)) if vals[i] > vals[i - 1]))

    def ma12_slope_1m_at_offset(offset: int) -> float:
        # offset=0 -> 현재 시점, offset=3 -> 3개월 전 시점에서의 동일 계산
        if n < 12 + 1 + offset:
            return np.nan
        end = n - offset
        ma_now = close.iloc[end - 12 : end].mean()
        ma_prev = close.iloc[end - 13 : end - 1].mean()
        if ma_prev == 0:
            return np.nan
        return float(ma_now / ma_prev - 1.0)

    slope_now = ma12_slope_1m_at_offset(0)
    slope_3m_ago = ma12_slope_1m_at_offset(3)
    if not (np.isnan(slope_now) or np.isnan(slope_3m_ago)):
        out["ma12_slope_change_3m"] = float(slope_now - slope_3m_ago)

    monthly_return = close.pct_change()
    mr12 = _tail_or_none(monthly_return, 12)
    if mr12 is not None and mr12.notna().all():
        out["recent_3m_return_vs_prior_9m"] = float(mr12.iloc[-3:].mean() - mr12.iloc[:9].mean())
        out["monthly_down_month_ratio_12m"] = float((mr12 < 0).sum() / 12)
    mr6 = _tail_or_none(monthly_return, 6)
    if mr6 is not None and mr6.notna().all():
        out["monthly_down_month_ratio_6m"] = float((mr6 < 0).sum() / 6)
        out["monthly_up_month_ratio_6m"] = float((mr6 > 0).sum() / 6)

    if n >= 4:
        out["recent_3m_return"] = float(close.iloc[-1] / close.iloc[-4] - 1.0)

    w6 = _tail_or_none(close, 6)
    if w6 is not None and w6.min() > 0:
        out["recent_6m_max_runup"] = float(w6.max() / w6.min() - 1.0)

    if n >= 2:
        streak = 0
        returns = monthly_return.iloc[1:]  # 첫 값은 항상 NaN
        for r in reversed(returns.tolist()):
            if np.isnan(r) or r <= 0:
                break
            streak += 1
        out["consecutive_positive_months"] = float(streak)

    return out
