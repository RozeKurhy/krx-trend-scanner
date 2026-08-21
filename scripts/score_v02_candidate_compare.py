"""Pattern A Score Design v0.2 Candidate 비교 스크립트.

목적: v0.1 OOS Case Validation에서 실제로 재현된 두 실패 메커니즘
(SKC형 Core/Supporting, LG/한국타이어형 alignment bonus)과 Pattern A/B
경계 문제(넷마블)를 구조적으로 해결하는 v0.2 후보를 development set에서
비교한다. 최종 후보를 자동으로 고르지 않는다 — 표만 만들고 선택은
문서(docs/patterns/pattern_a/archive/legacy_full_history.md의 Score Design v0.2 절)에 사람이 기록한다.

**Pattern A 점수 코드(pattern_a_score.py) 자체는 이 스크립트에서 건드리지
않는다.** Candidate B/C는 이 스크립트 안에서만 존재하는 로컬 함수다.
Candidate A는 `_score_v01_baseline()`이라는 이 스크립트 내부의 frozen
v0.1 재현 함수다(재리뷰 후속, 아래 "버전 고정 안내" 참고).

**완전 독립 고정(재현성 최종 후속)**: `_score_v01_baseline()`은 Base
curve/weight, Transition curve/weight, progressed evidence threshold/
penalty table을 전부 `V01_*` 상수(이 스크립트 안에 리터럴로 직접 옮겨
적음)로 계산한다 — production `pattern_a_score.py`의 `BASE_WEIGHTS`/
`BASE_POINTS`/`MA24_SLOPE_POINTS`/`WEEKLY_MA12_SLOPE_POINTS`/
`MA24_SLOPE_ACCELERATION_POINTS`/`PROGRESSED_EVIDENCE_THRESHOLDS`/
`PROGRESSED_PENALTY_BY_EVIDENCE_COUNT`는 이 계산 경로 어디에서도
참조하지 않는다. 값을 담지 않는 순수 계산 로직(`_weighted_piecewise_score`,
`_harmonic_mean`, `_piecewise_linear`, `_is_missing`)만 production에서
재사용한다 — 이 함수들은 어떤 curve/weight/threshold도 하드코딩하지
않고 인자로 받은 값만 계산하므로, production Score가 v0.3/v0.4로
바뀌어도 frozen v0.1 baseline 결과에 영향을 주지 않는다.
`score_pattern_a()`/`_compute_transition()`/`_alignment_bonus()`는 이제
v0.2 동작이라 Candidate A 계산에 전혀 쓰지 않는다 — `score_pattern_a()`는
별도로 "현재 production이 실제로 무엇을 반환하는가"를 보여주는
`current_v02_score` 참고 컬럼에만 쓴다.

**완전 독립 고정(재현성 최종 마무리)**: `_score_v01_baseline()`은 alignment
판정에도 더 이상 production `_transition_alignment()`을 쓰지 않는다.
이 함수는 순수 수학 helper가 아니라 v0.1 당시의 scoring policy(어떤
feature가 얼마 이상이면 정렬로 볼지)이므로, 로컬 `_v01_transition_alignment()`
로 그 정책을 그대로 리터럴 고정했다 — weekly_ma12_slope/ma24_slope/
ma24_slope_acceleration이 전부 0 초과면 정렬, 하나라도 결측이면 미정렬.
production `_transition_alignment()`은 이제 Candidate B/C 비교
(`align_variants()`)에서만 쓰고, Candidate A 경로에는 전혀 관여하지
않는다. 따라서 향후 production의 alignment 정의가 바뀌어도 Candidate A는
영향받지 않는다.

Transition Candidate:
    A. v0.1 그대로: 0.60*ma24_core + 0.20*weekly + 0.20*acceleration (가중합)
    B. Core gating: core_score(ma24_slope)가 낮으면 support_score(weekly/
       acceleration 평균)의 기여를 support_multiplier로 깎는다.
    C. Core + confirmation: Supporting은 독립 점수가 아니라 core_score가
       이미 일정 수준 이상일 때만 추가되는 confirmation bonus다.

Alignment Candidate(Transition 구조와 별개로 4개 비교, item 8):
    A. 현재 +8 유지  B. 축소(+4)  C. Core-strength 조건부  D. 완전 제거(0)

새 downtrend 구조 신호 후보 2개(item 9, analysis-only — FeatureRow/
PATTERN_A_FEATURE_SCOPE/Score 어디에도 아직 연결하지 않는다):
    long_term_high_slope_36m, prior_leg_drift_36m
    (trend_scanner.features.downtrend_structure, look-ahead 방지는
    HistoricalSnapshot.monthly가 이미 보장한다)

새 KRX fetch 없음 — 기존 historical_snapshot 캐시(exploration/holdout/
negative_control/OOS v0.1 29건)만 재사용한다. OOS2는 선정도 계산도 하지
않는다.

**버전 고정 안내(재현성 후속 수정)**: 최초 버전(commit df3de43)에서는
Candidate A가 `score_pattern_a()`를 직접 호출했다 — 그 시점엔
pattern_a_score.py가 아직 v0.1이라 정확한 baseline이었지만, v0.2가
freeze(`fffce85`)된 뒤 재실행하면 Candidate A도 v0.2를 반환해서 "A=v0.1,
B/C=신규 후보"라는 비교 전제가 깨지는 문제가 있었다. 이 재리뷰 후속
수정으로 Candidate A는 `_score_v01_baseline()`(frozen v0.1 formula를
이 스크립트 안에서 명시적으로 재현)을 쓰도록 바뀌었다 — **이제는 main
HEAD의 어느 시점에서 실행해도 v0.1 baseline / Candidate B / Candidate
C(=production v0.2) 비교가 항상 재현된다.**

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/score_v02_candidate_compare.py

CSV: data/processed/score_v02_candidate_compare.csv (로컬 전용, data/
전체가 gitignore).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.features.downtrend_structure import (
    long_term_high_slope_36m,
    prior_leg_drift_36m,
)
from trend_scanner.patterns.pattern_a_score import (
    ALIGNMENT_BONUS,
    MA24_SLOPE_ACCELERATION_POINTS,
    MA24_SLOPE_POINTS,
    WEEKLY_MA12_SLOPE_POINTS,
    _harmonic_mean,
    _is_missing,
    _piecewise_linear,
    _transition_alignment,
    _weighted_piecewise_score,
    score_pattern_a,
)

# 주의(재현성 최종 후속): 위 4개(MA24_SLOPE_ACCELERATION_POINTS/
# MA24_SLOPE_POINTS/WEEKLY_MA12_SLOPE_POINTS/ALIGNMENT_BONUS)는 Candidate
# B/C(core_score/support_score 계산, align_variants의 "keep8" 옵션)에서만
# 쓴다 — v0.1/v0.2가 이 개별 curve/상수는 그대로 공유하기 때문에 안전하고,
# 이번 라운드도 Candidate B/C 로직은 건드리지 않는다(item 10). **Candidate
# A(_score_v01_baseline)는 이 production import를 전혀 쓰지 않는다** —
# 아래 V01_* 상수만 쓴다.
# 주의(재현성 최종 마무리): _transition_alignment도 마찬가지로 이제
# align_variants()(Candidate B/C 비교)에서만 쓴다. Candidate A는 이 이름을
# 전혀 쓰지 않고 아래 정의된 _v01_transition_alignment()만 쓴다.
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
)
from trend_scanner.validation.oos_v01_manifest import (
    OOS_V01_DIAGNOSTIC_SNAPSHOTS,
    OOS_V01_STAGE_AUDIT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "score_v02_candidate_compare.csv"

# scripts/score_design_validate.py / base_expansion_validate.py와 동일한
# 종목/날짜(재정의가 아니라 그대로 옮긴 것 — 이 스크립트 하나로 재현
# 가능하도록 중복을 감수하는 이 repo의 기존 관례를 그대로 따른다).
EXPLORATION_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "068270", "name": "셀트리온", "date": "2019-12-31", "label": "pre_breakout"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-12-31", "label": "trend_progressed"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "035420", "name": "NAVER", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "005930", "name": "삼성전자", "date": "2019-09-30", "label": "pre_breakout"},
    {"ticker": "005930", "name": "삼성전자", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "005930", "name": "삼성전자", "date": "2021-03-31", "label": "trend_progressed"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-03-31", "label": "pre_breakout"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-12-31", "label": "early_trend"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2024-06-30", "label": "trend_progressed"},
]

HOLDOUT_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "005380", "name": "현대차", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "005380", "name": "현대차", "date": "2020-08-31", "label": "early_trend"},
    {"ticker": "005380", "name": "현대차", "date": "2021-02-28", "label": "trend_progressed"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "051910", "name": "LG화학", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "000270", "name": "기아", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "000270", "name": "기아", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "000270", "name": "기아", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "012330", "name": "현대모비스", "date": "2024-11-30", "label": "pre_breakout"},
    {"ticker": "012330", "name": "현대모비스", "date": "2025-06-30", "label": "early_trend"},
    {"ticker": "012330", "name": "현대모비스", "date": "2026-02-28", "label": "trend_progressed"},
]

NEGATIVE_CONTROL_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "003550", "name": "LG", "date": "2020-12-31", "label": "failed_breakout"},
    {"ticker": "010130", "name": "고려아연", "date": "2022-06-30", "label": "failed_breakout"},
    {"ticker": "011170", "name": "롯데케미칼", "date": "2023-01-31", "label": "failed_higher_low"},
    {"ticker": "009150", "name": "삼성전기", "date": "2022-12-31", "label": "failed_momentum"},
    {"ticker": "018260", "name": "삼성에스디에스", "date": "2023-07-31", "label": "failed_breakout"},
    {"ticker": "032830", "name": "삼성생명", "date": "2021-02-28", "label": "failed_ma24_turn"},
    {"ticker": "034730", "name": "SK", "date": "2020-12-31", "label": "failed_weekly_turn"},
    {"ticker": "011200", "name": "HMM", "date": "2024-10-31", "label": "failed_breakout"},
]

NEGATIVE_SUBGROUP: dict[str, str] = {
    "003550": "confirmed_negative",
    "010130": "confirmed_negative",
    "011170": "confirmed_negative",
    "032830": "confirmed_negative",
    "034730": "confirmed_negative",
    "009150": "ambiguous_negative",
    "018260": "ambiguous_negative",
    "011200": "ambiguous_negative",
}

# 특히 주목해서 별도 표로 뽑아볼 known false positive / 진단 케이스.
# (source, ticker, snapshot_date, 별칭)
KNOWN_FP_CASES: list[tuple[str, str, str, str]] = [
    ("negative_control", "003550", "2020-12-31", "LG(alignment FP)"),
    ("oos", "161390", "2024-04-30", "한국타이어(alignment FP)"),
    ("oos", "011790", "2024-06-30", "SKC(Core/Supporting FP)"),
    ("oos", "251270", "2020-08-31", "넷마블 boundary(A/B 경계)"),
]
CLEAN_EARLY_CASE = ("oos", "005490", "2023-03-31")  # 가장 깨끗한 audited EARLY_TREND
FAST_MOVER_CASES = [
    ("oos", "042660", "2024-10-31", "positive_pre_breakout"),
    ("oos", "042660", "2025-01-31", "positive_early_trend(EARLY/PROGRESSED 경계)"),
    ("oos", "042660", "2025-07-31", "positive_trend_progressed"),
]

FEATURE_ATTRS = (
    "range_36m",
    "avg_price_change_12m",
    "ma_spread",
    "ma24_slope",
    "weekly_ma12_slope",
    "ma24_slope_acceleration",
    "range_position",
)


def _feature_values(features: Any) -> dict[str, float]:
    return {name: getattr(features, name) for name in FEATURE_ATTRS}


# --- Candidate A: Frozen v0.1 baseline ---
#
# pattern_a_score.py는 이제 v0.2를 반환하므로(score_pattern_a,
# _compute_transition, _alignment_bonus는 전부 v0.2 동작), Candidate A는
# 이 스크립트 안에서 v0.1 Score Design(commit 6e7cc95~fffce85 직전)을
# 명시적으로 재현한다.
#
# **완전 독립 고정(재현성 최종 후속)**: Base curve/weight, Transition
# curve/weight, progressed evidence threshold/penalty table을 전부
# V01_* 상수로 이 스크립트 안에 직접 옮겨 적었다 — production
# pattern_a_score.py의 BASE_WEIGHTS/BASE_POINTS/MA24_SLOPE_POINTS/
# WEEKLY_MA12_SLOPE_POINTS/MA24_SLOPE_ACCELERATION_POINTS/
# PROGRESSED_EVIDENCE_THRESHOLDS/PROGRESSED_PENALTY_BY_EVIDENCE_COUNT는
# _score_v01_baseline() 계산 경로 어디에서도 참조하지 않는다. 지금은
# v0.1/v0.2가 이 값들을 그대로 공유해서 결과가 같지만, 그건 "우연히
# 같다"이지 "같은 걸 가리킨다"가 아니다 — 앞으로 v0.3에서 이 curve/
# threshold/penalty 중 하나라도 바뀌어도 frozen v0.1 baseline은 여기
# 적힌 리터럴 값을 계속 쓴다. _piecewise_linear/_harmonic_mean/
# _is_missing/_weighted_piecewise_score는 값을 담고 있지 않은 순수 계산
# 로직이라 재사용한다(item 9). alignment 판정은 정책이라 재사용하지
# 않는다 — 아래 _v01_transition_alignment()가 v0.1 정책을 리터럴로
# 고정한다(재현성 최종 마무리).
V01_RANGE_36M_POINTS: tuple[tuple[float, float], ...] = ((0.6, 100.0), (1.2, 60.0), (2.0, 0.0))
V01_AVG_PRICE_CHANGE_12M_POINTS: tuple[tuple[float, float], ...] = ((0.10, 100.0), (0.30, 50.0), (0.60, 0.0))
V01_MA_SPREAD_POINTS: tuple[tuple[float, float], ...] = ((0.10, 100.0), (0.25, 50.0), (0.40, 0.0))
V01_BASE_WEIGHTS: dict[str, float] = {
    "range_36m": 0.55,
    "avg_price_change_12m": 0.30,
    "ma_spread": 0.15,
}
V01_BASE_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "range_36m": V01_RANGE_36M_POINTS,
    "avg_price_change_12m": V01_AVG_PRICE_CHANGE_12M_POINTS,
    "ma_spread": V01_MA_SPREAD_POINTS,
}

V01_MA24_SLOPE_POINTS: tuple[tuple[float, float], ...] = (
    (-0.05, 0.0),
    (0.00, 50.0),
    (0.05, 90.0),
    (0.15, 100.0),
)
V01_WEEKLY_MA12_SLOPE_POINTS: tuple[tuple[float, float], ...] = ((0.00, 20.0), (0.15, 100.0))
V01_MA24_SLOPE_ACCELERATION_POINTS: tuple[tuple[float, float], ...] = ((0.00, 30.0), (0.05, 100.0))
V01_TRANSITION_WEIGHTS: dict[str, float] = {
    "ma24_slope": 0.60,
    "weekly_ma12_slope": 0.20,
    "ma24_slope_acceleration": 0.20,
}
V01_TRANSITION_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "ma24_slope": V01_MA24_SLOPE_POINTS,
    "weekly_ma12_slope": V01_WEEKLY_MA12_SLOPE_POINTS,
    "ma24_slope_acceleration": V01_MA24_SLOPE_ACCELERATION_POINTS,
}

# core strength 조건은 v0.1에 없다 — 정렬 충족 시 항상 전액 지급.
V01_ALIGNMENT_BONUS = 8.0

V01_PROGRESSED_EVIDENCE_THRESHOLDS: dict[str, float] = {
    "range_36m": 1.2,
    "avg_price_change_12m": 0.30,
    "ma_spread": 0.20,
    "ma24_slope": 0.10,
    "range_position": 0.85,
}
V01_PROGRESSED_PENALTY_BY_EVIDENCE_COUNT: dict[int, float] = {
    0: 0.0,
    1: 0.0,
    2: 10.0,
    3: 20.0,
    4: 28.0,
    5: 35.0,
}


@dataclass
class V01BaselineResult:
    base_score: float | None
    transition_score: float | None
    balanced_core_score: float | None
    alignment_bonus: float
    progressed_penalty: float
    progressed_evidence_count: int
    pattern_a_score: float | None
    insufficient_data: bool


def _v01_progressed_evidence_count(fv: dict[str, float]) -> int:
    count = 0
    for name, threshold in V01_PROGRESSED_EVIDENCE_THRESHOLDS.items():
        value = fv.get(name)
        if _is_missing(value):
            continue
        if value >= threshold:
            count += 1
    return count


def _v01_progressed_penalty(evidence_count: int) -> float:
    return V01_PROGRESSED_PENALTY_BY_EVIDENCE_COUNT.get(evidence_count, 35.0)


def _v01_transition_alignment(fv: dict[str, float]) -> bool:
    """v0.1 당시 alignment 판정 정책을 리터럴로 고정한다. production
    _transition_alignment()과 지금은 조건이 같지만, 이 함수는 그걸
    호출하지 않는다 — production 쪽 정의가 v0.3에서 바뀌어도 이 함수는
    weekly_ma12_slope/ma24_slope/ma24_slope_acceleration이 전부 0을
    초과하는지만 계속 그대로 판정한다."""
    weekly = fv.get("weekly_ma12_slope")
    ma24 = fv.get("ma24_slope")
    accel = fv.get("ma24_slope_acceleration")
    if _is_missing(weekly) or _is_missing(ma24) or _is_missing(accel):
        return False
    return weekly > 0 and ma24 > 0 and accel > 0


def _score_v01_baseline(fv: dict[str, float]) -> V01BaselineResult:
    """frozen v0.1 Score Design 그대로 재현한다(재구현이 아니라 v0.1이
    실제로 썼던 가중합 Transition + 항상 +8 alignment bonus). 이 함수는
    production pattern_a_score.py의 scoring constant나 alignment 판정
    함수를 하나도 참조하지 않는다 — 전부 위 V01_* 상수와
    _v01_transition_alignment()다."""
    base = _weighted_piecewise_score(fv, V01_BASE_WEIGHTS, V01_BASE_POINTS)
    transition = _weighted_piecewise_score(fv, V01_TRANSITION_WEIGHTS, V01_TRANSITION_POINTS)

    required_missing = _is_missing(fv.get("range_36m")) or _is_missing(fv.get("ma24_slope"))
    insufficient_data = required_missing or base.score is None or transition.score is None

    if insufficient_data:
        return V01BaselineResult(
            base_score=base.score,
            transition_score=transition.score,
            balanced_core_score=None,
            alignment_bonus=0.0,
            progressed_penalty=0.0,
            progressed_evidence_count=0,
            pattern_a_score=None,
            insufficient_data=True,
        )

    balanced_core = _harmonic_mean(base.score, transition.score)
    aligned = _v01_transition_alignment(fv)
    alignment_bonus = V01_ALIGNMENT_BONUS if aligned else 0.0
    evidence_count = _v01_progressed_evidence_count(fv)
    penalty = _v01_progressed_penalty(evidence_count)
    final = max(0.0, min(100.0, balanced_core + alignment_bonus - penalty))

    return V01BaselineResult(
        base_score=base.score,
        transition_score=transition.score,
        balanced_core_score=balanced_core,
        alignment_bonus=alignment_bonus,
        progressed_penalty=penalty,
        progressed_evidence_count=evidence_count,
        pattern_a_score=final,
        insufficient_data=False,
    )


# --- Candidate B: Core gating ---
CORE_WEIGHT = 0.60
SUPPORT_WEIGHT = 0.40
# core_score가 낮을 때 support 기여를 얼마나 깎을지(설명 가능한 3구간
# piecewise). raw ma24_slope가 아니라 이미 0~100으로 변환된 core_score를
# gate 기준으로 쓴다(item 5 권장안 — threshold를 새로 하나 더 만들지
# 않기 위해 MA24_SLOPE_POINTS가 만든 스케일을 그대로 재사용).
CORE_GATE_POINTS: tuple[tuple[float, float], ...] = ((0.0, 0.0), (30.0, 0.25), (60.0, 1.0), (100.0, 1.0))

# --- Candidate C: Core + confirmation ---
CONFIRMATION_MAX = 20.0
# core_score가 50 미만이면 confirmation 기여가 0(= Supporting이 Core
# 없이 점수를 만들 수 없다), 80 이상이면 최대 확인 보너스를 전부 인정.
CONFIRMATION_GATE_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (50.0, 0.0),
    (80.0, 1.0),
    (100.0, 1.0),
)

# --- Alignment candidates ---
ALIGN_REDUCED_BONUS = 4.0
ALIGN_CORE_STRONG_THRESHOLD = 60.0  # Candidate B의 CORE_GATE_POINTS "full contribution" 지점과 동일값 재사용
ALIGN_CORE_STRONG_BONUS = 8.0
ALIGN_CORE_WEAK_BONUS = 3.0


def _core_score(ma24_slope: float) -> float | None:
    if _is_missing(ma24_slope):
        return None
    return _piecewise_linear(ma24_slope, MA24_SLOPE_POINTS)


def _support_score(weekly: float, accel: float) -> float | None:
    parts = []
    if not _is_missing(weekly):
        parts.append(_piecewise_linear(weekly, WEEKLY_MA12_SLOPE_POINTS))
    if not _is_missing(accel):
        parts.append(_piecewise_linear(accel, MA24_SLOPE_ACCELERATION_POINTS))
    if not parts:
        return None
    return sum(parts) / len(parts)


def candidate_b_transition(fv: dict[str, float]) -> dict[str, float | None]:
    core = _core_score(fv.get("ma24_slope"))
    if core is None:
        return {"transition_b": None, "core_score": None, "support_score": None, "support_multiplier": None}
    support = _support_score(fv.get("weekly_ma12_slope"), fv.get("ma24_slope_acceleration"))
    if support is None:
        return {"transition_b": core, "core_score": core, "support_score": None, "support_multiplier": None}
    multiplier = _piecewise_linear(core, CORE_GATE_POINTS)
    transition = CORE_WEIGHT * core + SUPPORT_WEIGHT * support * multiplier
    return {
        "transition_b": transition,
        "core_score": core,
        "support_score": support,
        "support_multiplier": multiplier,
    }


def candidate_c_transition(fv: dict[str, float]) -> dict[str, float | None]:
    core = _core_score(fv.get("ma24_slope"))
    if core is None:
        return {
            "transition_c": None,
            "core_score": None,
            "support_score": None,
            "confirmation_gate": None,
            "confirmation_bonus": None,
        }
    support = _support_score(fv.get("weekly_ma12_slope"), fv.get("ma24_slope_acceleration"))
    if support is None:
        return {
            "transition_c": core,
            "core_score": core,
            "support_score": None,
            "confirmation_gate": None,
            "confirmation_bonus": 0.0,
        }
    gate = _piecewise_linear(core, CONFIRMATION_GATE_POINTS)
    confirmation_bonus = CONFIRMATION_MAX * (support / 100.0) * gate
    transition = min(100.0, core + confirmation_bonus)
    return {
        "transition_c": transition,
        "core_score": core,
        "support_score": support,
        "confirmation_gate": gate,
        "confirmation_bonus": confirmation_bonus,
    }


def align_variants(fv: dict[str, float], core_score: float | None) -> dict[str, float]:
    aligned = _transition_alignment(fv)
    a_keep = ALIGNMENT_BONUS if aligned else 0.0
    b_reduced = ALIGN_REDUCED_BONUS if aligned else 0.0
    if not aligned or core_score is None:
        c_conditional = 0.0
    elif core_score >= ALIGN_CORE_STRONG_THRESHOLD:
        c_conditional = ALIGN_CORE_STRONG_BONUS
    else:
        c_conditional = ALIGN_CORE_WEAK_BONUS
    return {
        "align_a_keep8": a_keep,
        "align_b_reduced4": b_reduced,
        "align_c_core_conditional": c_conditional,
        "align_d_removed": 0.0,
    }


def _final_score(
    base_score: float | None, transition_score: float | None, align_bonus: float, penalty: float
) -> float | None:
    if base_score is None or transition_score is None:
        return None
    balanced = _harmonic_mean(base_score, transition_score)
    if balanced is None:
        return None
    return max(0.0, min(100.0, balanced + align_bonus - penalty))


def _load_daily(cache: ParquetCache, tickers: dict[str, str]) -> dict[str, pd.DataFrame]:
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(f"{ticker} 캐시가 없습니다. 새로 fetch하지 않습니다 — 먼저 캐시를 채워주세요.")
        daily_by_ticker[ticker] = daily
    return daily_by_ticker


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    exploration_tickers = {s["ticker"]: s["name"] for s in EXPLORATION_SNAPSHOTS}
    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}
    negative_tickers = {s["ticker"]: s["name"] for s in NEGATIVE_CONTROL_SNAPSHOTS}
    oos_tickers = {s.ticker: s.name for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS}

    exploration_daily = _load_daily(cache, exploration_tickers)
    holdout_daily = _load_daily(cache, holdout_tickers)
    negative_daily = _load_daily(cache, negative_tickers)
    oos_daily = _load_daily(cache, oos_tickers)

    records: list[dict] = []

    def _add_record(
        source: str, group: str, ticker: str, name: str, date: str, label: str, audited_label: str | None,
        snap: HistoricalSnapshot,
    ) -> None:
        fv = _feature_values(snap.features)
        v01 = _score_v01_baseline(fv)
        # production v0.2를 직접 호출하는 건 여기(참고용 cross-check
        # 컬럼)뿐이다 — Candidate A/B/C 계산 어디에도 쓰지 않는다.
        v02 = score_pattern_a(snap.features)

        row: dict[str, Any] = {
            "source": source,
            "group": group,
            "ticker": ticker,
            "name": name,
            "date": date,
            "label": label,
            "audited_label": audited_label,
            "insufficient_data": v01.insufficient_data,
            "base_score": v01.base_score,
            "final_a": v01.pattern_a_score,
            "transition_a": v01.transition_score,
            "align_v01_bonus": v01.alignment_bonus,
            "progressed_penalty": v01.progressed_penalty,
            "progressed_evidence_count": v01.progressed_evidence_count,
            "current_v02_score": v02.pattern_a_score,
            "long_term_high_slope_36m": long_term_high_slope_36m(snap.monthly),
            "prior_leg_drift_36m": prior_leg_drift_36m(snap.monthly),
        }
        for name_ in FEATURE_ATTRS:
            row[name_] = getattr(snap.features, name_)

        if v01.insufficient_data:
            row.update(
                {
                    "transition_b": None,
                    "transition_c": None,
                    "core_score": None,
                    "support_score": None,
                    "final_b_align01": None,
                    "final_c_align01": None,
                }
            )
            for k in ("align_a_keep8", "align_b_reduced4", "align_c_core_conditional", "align_d_removed"):
                row[k] = None
            for cand in ("a", "b", "c"):
                for align_name in ("keep8", "reduced4", "core_conditional", "removed"):
                    row[f"final_{cand}_align_{align_name}"] = None
            records.append(row)
            return

        b = candidate_b_transition(fv)
        c = candidate_c_transition(fv)
        row["transition_b"] = b["transition_b"]
        row["transition_c"] = c["transition_c"]
        row["core_score"] = b["core_score"]
        row["support_score"] = b["support_score"]
        row["support_multiplier"] = b.get("support_multiplier")
        row["confirmation_gate"] = c.get("confirmation_gate")
        row["confirmation_bonus"] = c.get("confirmation_bonus")

        # stage 1: transition만 비교 (alignment는 v0.1 그대로 고정)
        row["final_b_align01"] = _final_score(
            v01.base_score, b["transition_b"], v01.alignment_bonus, v01.progressed_penalty
        )
        row["final_c_align01"] = _final_score(
            v01.base_score, c["transition_c"], v01.alignment_bonus, v01.progressed_penalty
        )

        # stage 2: 각 transition candidate x alignment candidate 전체 grid
        aligns = align_variants(fv, b["core_score"])
        row.update(aligns)
        transitions = {"a": v01.transition_score, "b": b["transition_b"], "c": c["transition_c"]}
        align_map = {
            "keep8": aligns["align_a_keep8"],
            "reduced4": aligns["align_b_reduced4"],
            "core_conditional": aligns["align_c_core_conditional"],
            "removed": aligns["align_d_removed"],
        }
        for cand_name, cand_transition in transitions.items():
            for align_name, align_bonus in align_map.items():
                row[f"final_{cand_name}_align_{align_name}"] = _final_score(
                    v01.base_score, cand_transition, align_bonus, v01.progressed_penalty
                )

        records.append(row)

    for s in EXPLORATION_SNAPSHOTS:
        daily = exploration_daily[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("exploration", f"exploration_{s['label']}", s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in HOLDOUT_SNAPSHOTS:
        daily = holdout_daily[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("holdout", f"holdout_{s['label']}", s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in NEGATIVE_CONTROL_SNAPSHOTS:
        daily = negative_daily[s["ticker"]]
        subgroup = NEGATIVE_SUBGROUP[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("negative_control", subgroup, s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        daily = oos_daily[s.ticker]
        audited = OOS_V01_STAGE_AUDIT.get((s.ticker, s.snapshot_date))
        audited_label = audited.audited_stage_label if audited is not None else None
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        _add_record("oos", s.original_group, s.ticker, s.name, s.snapshot_date, s.original_group, audited_label, snap)

    df = pd.DataFrame(records)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    # --- 재현성 check: Candidate C(align_c_core_conditional) == production v0.2 ---
    # 채택된 v0.2 구조(Transition C + Alignment C)가 실제로 production
    # score_pattern_a()와 같은 값을 내는지 매 실행마다 확인한다.
    print("=" * 100)
    print("[재현성 check] Candidate C(align_c_core_conditional) vs current_v02_score(production)")
    print("=" * 100)
    checkable = df[df["current_v02_score"].notna() & df["final_c_align_core_conditional"].notna()]
    if checkable.empty:
        print("비교 가능한 행 없음(전부 insufficient_data)")
    else:
        diff = (checkable["final_c_align_core_conditional"] - checkable["current_v02_score"]).abs()
        max_diff = diff.max()
        mismatches = checkable[diff > 1e-6]
        print(f"비교 대상 {len(checkable)}건, 최대 절대 오차 {max_diff:.10f}")
        if mismatches.empty:
            print("전부 일치 — Candidate C가 production v0.2를 정확히 재현한다.")
        else:
            for _, r in mismatches.iterrows():
                print(
                    f"  불일치: {r['ticker']} {r['name']} {r['date']} "
                    f"candidate_c={r['final_c_align_core_conditional']} "
                    f"production={r['current_v02_score']}"
                )
            raise SystemExit(
                f"{len(mismatches)}건에서 Candidate C가 production v0.2와 불일치 — "
                "이 스크립트의 Candidate C 구현이 pattern_a_score.py와 어긋났다."
            )
    print()

    # --- Stage 1: Transition Candidate A/B/C (alignment은 v0.1 고정) ---
    print("=" * 100)
    print("[Stage 1] Transition Candidate A/B/C 그룹별 final score (alignment=v0.1 고정) min/median/max")
    print("=" * 100)
    for group in dict.fromkeys(df["group"]):
        sub = df[df["group"] == group]
        row = {"group": group, "n": len(sub)}
        for col, label in [("final_a", "A"), ("final_b_align01", "B"), ("final_c_align01", "C")]:
            values = sub[col].dropna()
            if values.empty:
                row[f"{label}_median"] = float("nan")
                row[f"{label}_min"] = float("nan")
                row[f"{label}_max"] = float("nan")
            else:
                row[f"{label}_median"] = values.median()
                row[f"{label}_min"] = values.min()
                row[f"{label}_max"] = values.max()
        print(
            f"{group:<32} n={row['n']:>2}  "
            f"A(min/med/max)={row['A_min']:.1f}/{row['A_median']:.1f}/{row['A_max']:.1f}  "
            f"B={row['B_min']:.1f}/{row['B_median']:.1f}/{row['B_max']:.1f}  "
            f"C={row['C_min']:.1f}/{row['C_median']:.1f}/{row['C_max']:.1f}"
        )
    print()

    # --- Known FP 4건 ---
    print("=" * 100)
    print("[Known FP] LG / 한국타이어 / SKC / 넷마블 boundary — transition/align/final 비교")
    print("=" * 100)
    for source, ticker, date, alias in KNOWN_FP_CASES:
        sub = df[(df["source"] == source) & (df["ticker"] == ticker) & (df["date"] == date)]
        if sub.empty:
            print(f"{alias}: 레코드 없음")
            continue
        r = sub.iloc[0]
        print(
            f"{alias:<26} core={r['core_score']:.1f} support={r['support_score']} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"align_v01={r['align_v01_bonus']:.1f}  final A/B/C(align v0.1)={r['final_a']:.1f}/"
            f"{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- Clean early case ---
    print("=" * 100)
    print("[Clean early case] 005490 2023-03-31 (가장 깨끗한 audited EARLY_TREND)")
    print("=" * 100)
    sub = df[(df["ticker"] == CLEAN_EARLY_CASE[1]) & (df["date"] == CLEAN_EARLY_CASE[2])]
    if not sub.empty:
        r = sub.iloc[0]
        print(
            f"core={r['core_score']:.1f} support={r['support_score']:.1f} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"final A/B/C(align v0.1)={r['final_a']:.1f}/{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- 042660 fast mover ---
    print("=" * 100)
    print("[042660 한화오션 fast mover] base/transition/penalty/final A/B/C 비교")
    print("=" * 100)
    for source, ticker, date, label in FAST_MOVER_CASES:
        sub = df[(df["ticker"] == ticker) & (df["date"] == date)]
        if sub.empty:
            continue
        r = sub.iloc[0]
        print(
            f"{date} ({label:<45}) base={r['base_score']:.1f} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"penalty={r['progressed_penalty']:.1f} evidence={r['progressed_evidence_count']}  "
            f"final A/B/C(align v0.1)={r['final_a']:.1f}/{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- 새 downtrend Feature 그룹별 raw value ---
    print("=" * 100)
    print("[새 Feature] long_term_high_slope_36m / prior_leg_drift_36m 그룹별 min/median/max")
    print("=" * 100)
    for group in dict.fromkeys(df["group"]):
        sub = df[df["group"] == group]
        for col in ("long_term_high_slope_36m", "prior_leg_drift_36m"):
            values = sub[col].dropna()
            if values.empty:
                continue
            print(f"{group:<32} {col:<26} n={len(values):>2} min={values.min():+.4f} median={values.median():+.4f} max={values.max():+.4f}")
    print()

    print("=" * 100)
    print("[새 Feature] downtrend_reversal_boundary vs positive_pre_breakout 종목별 raw value")
    print("=" * 100)
    for group in ("downtrend_reversal_boundary", "positive_pre_breakout"):
        sub = df[df["group"] == group]
        for _, r in sub.iterrows():
            print(
                f"{group:<28} {r['ticker']} {r['name']:<12} {r['date']}  "
                f"avg_price_change_12m={r['avg_price_change_12m']!s:>10}  "
                f"long_term_high_slope_36m={r['long_term_high_slope_36m']!s:>10}  "
                f"prior_leg_drift_36m={r['prior_leg_drift_36m']!s:>10}"
            )
    print()


if __name__ == "__main__":
    main()
