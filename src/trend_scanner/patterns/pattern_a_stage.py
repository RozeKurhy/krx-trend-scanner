"""Pattern A Stage Classifier v0.1.

Score와 독립적으로, `docs/patterns/pattern_a/validation/stage_label_audit_freeze.md`가 확정한 Stage
정의와 `pattern_a_stage_manifest.py`의 46건 manual truth set을 근거로
`PatternAStage`(base/transition/early_trend/progressed/weak)를 rule-based로
판정한다.

**Score와의 독립성**: 이 모듈은 `pattern_a_score` 모듈을 import하지 않고,
`score_pattern_a()`/`base_score`/`transition_score`/`balanced_core_score`/
`alignment_bonus`/`confirmation_bonus`/`progressed_penalty` 등 Score 파생
값을 전혀 쓰지 않는다. 입력은 `HistoricalSnapshot`(raw `FeatureRow` +
look-ahead 없는 monthly OHLCV)뿐이다. `pattern_a_score.py`에는 이미
Score 파생값 기반 provisional stage heuristic(`_classify_stage`)이 있지만,
이번 커밋에서는 건드리지 않는다 — 이 모듈은 그것과 독립된 별도 production
candidate다.

**Threshold 근거**: 아래 threshold는 `pattern_a_stage_manifest.py`의 46건
truth set에 기록된 실제 Feature 값(각 row의 stage_reason에 인용된
range_position/ma24_slope/weekly_ma12_slope/avg_price_change_12m/ma_spread
값)을 손으로 대조해 잡았다 — ML fitting이 아니라 사람이 읽을 수 있는
rule이다. 자세한 근거와 46건 validation 결과는
`docs/patterns/pattern_a/validation/stage_classifier_v01.md` 참고.

**range_position 선택**: Stage/Breakout 판정에는 36개월 monthly
`range_position`(FeatureRow, resistance.range_position(close, low_36m,
high_36m))을 쓴다. `range_position_52w`(주간 기준)가 아니라 이걸 쓰는
이유는, manifest의 46건 stage_reason이 대부분 이 값을 근거로 판정을
남겼기 때문이다(1건만 range_position_52w를 보조로 언급) — 기존 manual
판정 근거와 판정 축을 맞추기 위함이다. 또한 monthly range_position은
`HistoricalSnapshot.monthly`만으로 과거 시점 series를 재구성할 수 있어서
(주간 프레임은 HistoricalSnapshot에 없다) episode/cycle reset 판정에도
동일한 축을 그대로 재사용할 수 있다는 실용적 이유도 있다.

**Precedence, not blended score**: 여러 evidence를 하나의 stage_score로
합산해 cutoff로 나누지 않는다. 대신 정해진 순서로 조건을 검사해 가장 먼저
맞는 stage를 채택한다(else-if 사슬) — 이래야 "왜 이 종목이 이 Stage인가"를
사람이 그대로 따라 읽을 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trend_scanner.features.moving_average import moving_average, ma_slope_series
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.feature_report import FeatureRow
from trend_scanner.validation.historical_snapshot import HistoricalSnapshot

# --- Threshold constants ---
# 46건 truth set과 손으로 대조해 잡은 값. docs/validation/
# pattern_a_stage_classifier_v01.md의 "Threshold/rule rationale" 참고.

WEEKLY_MEANINGFUL_POSITIVE = 0.03
"""weekly_ma12_slope가 이 값 이상이어야 '의미 있게' 양전환으로 본다.
0 초과만 요구하면 BASE 중에도 weekly가 살짝 양수인 사례
(015760/023530/011210/032830 등, +0.007~+0.02)가 전부 TRANSITION 신호로
오분류된다."""

ACTIVE_DECLINE_STEEP_MA24_SLOPE = -0.045
ACTIVE_DECLINE_ACCEL_AVG_CHG = -0.15
ACTIVE_DECLINE_LOW_RANGE_POSITION = 0.20
"""active_decline 3-branch OR의 구성 threshold. 단일 신호가 아니라
(가파른 ma24_slope) OR (가속화되는 하락+큰 과거 낙폭) OR (weekly 미전환+
매우 낮은 위치) 중 하나라도 맞으면 WEAK 후보로 본다."""

BREAKOUT_RANGE_POSITION = 0.60
"""core/weekly가 모두 양전환했고 range_position이 이 이상이면 이미 가격이
박스 상단까지 따라온 것으로 보고 breakout_like_structure로 판정한다."""

PRICE_EXTENDED_RANGE_POSITION = 0.80
NEAR_RESISTANCE_DISTANCE = 0.10

EXPANSION_AVG_CHG = 0.30
EXPANSION_MA_SPREAD = 0.20
"""expansion_present는 AND가 아니라 OR다. avg_price_change_12m만으로도
확장이 뚜렷한 사례(000810 삼성화재 2024-06-30: avg_chg=0.387이지만
ma_spread=0.185로 0.20 문턱을 근소하게 못 넘김)가 있어서, AND로 두면
PROGRESSED가 EARLY_TREND로 밀린다."""

# Episode/Cycle reset 판정에 쓰는 threshold. "과거 확장이 있었다"의 기준은
# strict historical expansion proxy인 ma24_slope > 0 AND avg_price_change_12m >= 0.30 (AND)
# 으로 잡는다 (direct PROGRESSED의 expansion_present[avg_chg>=0.30 OR ma_spread>=0.20]와
# 달리, 과거 탐색 시 false positive를 줄이기 위해 더 엄격한 AND 기준 적용).
# range_position 단독 신호로 잡으면 EARLY_TREND 구간(range_position은 이미 높지만
# avg_price_change_12m은 아직 낮음)도 매달 걸려서 "직전 달"이 항상 last_expansion으로
# 잡히는 문제가 실측으로 확인됐다(months_since_expansion이 거의 항상 1).
EPISODE_PEAK_AVG_CHG = 0.30
EPISODE_BREAK_MA24_SLOPE = -0.045
EPISODE_BREAK_RANGE_POSITION = 0.20


@dataclass(frozen=True)
class StageEvidence:
    """현재 snapshot 시점 evidence. 전부 raw FeatureRow 값에서만 파생한다."""

    active_decline: bool
    core_turning_positive: bool
    weekly_turning_positive: bool
    breakout_like_structure: bool
    near_resistance: bool
    expansion_present: bool
    price_extended: bool
    insufficient_data: bool


@dataclass(frozen=True)
class StageLifecycleContext:
    """snapshot 이전 과거 구간에서 expansion proxy가 감지됐는지와,
    그 이후 장기 추세 붕괴로 episode가 종료(cycle reset)되었는지를 나타낸다.
    Pattern A episode/cycle reset 개념(docs/patterns/pattern_a/validation/stage_label_audit_freeze.md)을
    판정용으로 옮긴 것 — Score에는 연결하지 않는다.

    - prior_expansion_detected: snapshot 이전에 strict historical expansion proxy
      (ma24_slope > 0 AND avg_price_change_12m >= 0.30)가 한 번이라도 감지됐는가.
    - episode_broken_after_expansion: 마지막 historical expansion 이후 현재 이전까지
      episode break evidence(ma24_slope <= -0.045 OR range_position <= 0.20)가
      발생했는가.
    - last_expansion_month: 마지막 historical expansion proxy가 감지된 월.
    - months_since_expansion: 마지막 historical expansion 이후 경과 개월 수.
    - previously_expanded_in_current_episode: prior_expansion_detected AND NOT
      episode_broken_after_expansion (현재 episode에 속하는 과거 확장이 존재하는가).
    """

    prior_expansion_detected: bool
    episode_broken_after_expansion: bool
    last_expansion_month: str | None
    months_since_expansion: int | None
    previously_expanded_in_current_episode: bool


@dataclass(frozen=True)
class StageClassificationResult:
    stage: PatternAStage | None
    reason_codes: tuple[str, ...]
    evidence: StageEvidence
    context: StageLifecycleContext


def _is_missing(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


_REQUIRED_FIELDS = (
    "ma24_slope",
    "weekly_ma12_slope",
    "ma24_slope_acceleration",
    "avg_price_change_12m",
    "ma_spread",
    "range_position",
    "distance_to_resistance",
)


def _empty_evidence(insufficient_data: bool) -> StageEvidence:
    return StageEvidence(
        active_decline=False,
        core_turning_positive=False,
        weekly_turning_positive=False,
        breakout_like_structure=False,
        near_resistance=False,
        expansion_present=False,
        price_extended=False,
        insufficient_data=insufficient_data,
    )


def _build_evidence(features: FeatureRow) -> StageEvidence:
    if any(_is_missing(getattr(features, name)) for name in _REQUIRED_FIELDS):
        return _empty_evidence(insufficient_data=True)

    core_turning_positive = features.ma24_slope > 0
    weekly_turning_positive = features.weekly_ma12_slope >= WEEKLY_MEANINGFUL_POSITIVE

    active_decline = (
        features.ma24_slope <= ACTIVE_DECLINE_STEEP_MA24_SLOPE
        or (
            features.ma24_slope_acceleration < 0
            and features.avg_price_change_12m <= ACTIVE_DECLINE_ACCEL_AVG_CHG
        )
        or (
            features.weekly_ma12_slope <= 0
            and features.range_position <= ACTIVE_DECLINE_LOW_RANGE_POSITION
        )
    )

    breakout_like_structure = (
        core_turning_positive
        and weekly_turning_positive
        and features.range_position >= BREAKOUT_RANGE_POSITION
    )

    expansion_present = (
        features.avg_price_change_12m >= EXPANSION_AVG_CHG
        or features.ma_spread >= EXPANSION_MA_SPREAD
    )

    # price_extended은 range_position 단독으로는 EARLY_TREND와 PROGRESSED를
    # 못 가른다(실측: EARLY_TREND 46건 truth 중 range_position=0.83~0.96인
    # 사례가 다수라 PROGRESSED의 0.82~0.97 구간과 사실상 겹친다). 그래서
    # PROGRESSED 판정에는 이 신호를 단독으로 쓰지 않는다(아래 참고) —
    # evidence 필드는 진단용으로만 남긴다.
    return StageEvidence(
        active_decline=active_decline,
        core_turning_positive=core_turning_positive,
        weekly_turning_positive=weekly_turning_positive,
        breakout_like_structure=breakout_like_structure,
        near_resistance=features.distance_to_resistance <= NEAR_RESISTANCE_DISTANCE,
        expansion_present=expansion_present,
        price_extended=features.range_position >= PRICE_EXTENDED_RANGE_POSITION,
        insufficient_data=False,
    )


def _historical_monthly_series(monthly: pd.DataFrame) -> dict[str, pd.Series]:
    """`snapshot.monthly`(look-ahead 없는 monthly OHLCV)만으로 evidence
    axis에 쓰는 Feature들의 전체 historical series를 재구성한다.
    build_feature_row()/_avg_price_change_12m()/resistance.range_position()과
    동일한 point formula의 vectorized 버전이다 — 새 Feature가 아니라 기존
    Feature를 과거 시점마다 계산한 것.
    """
    close = monthly["close"] if "close" in monthly.columns else pd.Series(dtype=float)

    ma24_series = moving_average(close, 24)
    ma24_slope_series = ma_slope_series(ma24_series, periods=3)

    high_36m_series = monthly["high"].rolling(36).max() if "high" in monthly.columns else pd.Series(dtype=float)
    low_36m_series = monthly["low"].rolling(36).min() if "low" in monthly.columns else pd.Series(dtype=float)
    range_position_series = (close - low_36m_series) / (high_36m_series - low_36m_series)

    recent_12_avg = close.rolling(12).mean()
    prior_12_avg = recent_12_avg.shift(12)
    avg_price_change_12m_series = (recent_12_avg - prior_12_avg) / prior_12_avg

    return {
        "ma24_slope": ma24_slope_series,
        "range_position": range_position_series,
        "avg_price_change_12m": avg_price_change_12m_series,
    }


def _build_lifecycle_context(monthly: pd.DataFrame) -> StageLifecycleContext:
    """현재 snapshot 이전(과거) monthly 구간만 사용해 '과거 확장 프록시가
    감지되었는지'와 '그 확장이 이후 꺾여 episode가 종료되었는지'를 판정한다.
    현재 시점(마지막 행)은 여기서 다루지 않는다 — 그건 StageEvidence의 몫이다.

    strict historical expansion proxy:
        과거 어느 달에 ma24_slope > 0 AND avg_price_change_12m >= 0.30 (AND)
        이 성립한 적이 있는가.
        (direct PROGRESSED의 expansion_present[avg_chg>=0.30 OR ma_spread>=0.20]와
        완전히 동일한 정의가 아니다 — historical 탐색에서는 오래된 확장 false positive를
        줄이기 위해 더 엄격한 AND 기준을 사용한다).
    """
    if len(monthly) < 2:
        return StageLifecycleContext(
            prior_expansion_detected=False,
            episode_broken_after_expansion=False,
            last_expansion_month=None,
            months_since_expansion=None,
            previously_expanded_in_current_episode=False,
        )

    series = _historical_monthly_series(monthly)
    # 현재 시점(마지막 행)은 제외하고 과거 구간만 스캔한다.
    past = {name: s.iloc[:-1] for name, s in series.items()}

    # "확장이 있었다"의 기준을 range_position만으로 잡으면 EARLY_TREND
    # 구간(range_position이 이미 높지만 avg_price_change_12m은 아직 낮은
    # 상태)도 매달 걸려서 "직전 달"이 항상 last_expansion으로 잡히는
    # 문제가 실측으로 확인됐다(months_since_expansion이 거의 항상 1).
    # 그래서 여기서는 strict historical expansion proxy
    # (core_turning_positive and avg_price_change_12m 큰 폭)만
    # 과거 확장으로 본다 — range_position 단독 신호는 쓰지 않는다.
    expanded_mask = (past["ma24_slope"] > 0) & (past["avg_price_change_12m"] >= EPISODE_PEAK_AVG_CHG)
    expanded_mask = expanded_mask.fillna(False)

    if not expanded_mask.any():
        return StageLifecycleContext(
            prior_expansion_detected=False,
            episode_broken_after_expansion=False,
            last_expansion_month=None,
            months_since_expansion=None,
            previously_expanded_in_current_episode=False,
        )

    last_expansion_idx = expanded_mask[expanded_mask].index[-1]
    last_expansion_pos = monthly.index.get_loc(last_expansion_idx)
    current_pos = len(monthly) - 1
    months_since = current_pos - last_expansion_pos

    window_ma24_slope = series["ma24_slope"].iloc[last_expansion_pos + 1 : current_pos]
    window_range_position = series["range_position"].iloc[last_expansion_pos + 1 : current_pos]

    episode_broken_after_expansion = bool(
        (window_ma24_slope <= EPISODE_BREAK_MA24_SLOPE).fillna(False).any()
        or (window_range_position <= EPISODE_BREAK_RANGE_POSITION).fillna(False).any()
    )

    last_expansion_month = str(getattr(last_expansion_idx, "date", lambda: last_expansion_idx)())
    previously_expanded_in_current_episode = not episode_broken_after_expansion

    return StageLifecycleContext(
        prior_expansion_detected=True,
        episode_broken_after_expansion=episode_broken_after_expansion,
        last_expansion_month=last_expansion_month,
        months_since_expansion=months_since,
        previously_expanded_in_current_episode=previously_expanded_in_current_episode,
    )


def classify_pattern_a_stage(snapshot: HistoricalSnapshot) -> StageClassificationResult:
    """`snapshot.effective_as_of` 시점까지의 정보만으로 Pattern A Stage를
    판정한다. Score 파생값은 쓰지 않는다(모듈 docstring 참고).

    Precedence(우선순위 순서, 하나의 blended score가 아니라 순서대로 검사):
    1. insufficient_data - 필요한 Feature 중 하나라도 없으면 stage=None.
    2. active_decline -> WEAK. 단, 이미 과거에 확장했다가 꺾인
       상태(prior_expansion_detected and episode_broken_after_expansion)라도
       WEAK로 본다 — "꺾인 뒤"이므로 새로운 cycle의 WEAK/BASE 후보로 재시작한 것이다.
    3. core_turning_positive and expansion_present -> PROGRESSED(직접
       판정). weekly_turning_positive는 요구하지 않는다 — 실측 결과
       PROGRESSED 사례는 오히려 weekly_ma12_slope가 낮거나 음수인 경우가
       많다(모멘텀이 이미 성숙해서 단기 기울기가 둔화됨). weekly가 여전히
       강하게 양전환 중인 건 오히려 EARLY_TREND(신선한 돌파)의 특징이다.
       range_position도 여기서 gate로 안 쓴다 — 실측상 EARLY_TREND와
       PROGRESSED의 range_position 분포가 크게 겹쳐서(둘 다 0.6~0.97대)
       분리력이 없었다. expansion_present(avg_price_change_12m/ma_spread)
       가 실제로 EARLY_TREND/PROGRESSED를 가르는 신호였다.
    4. breakout_like_structure(core+weekly 양전환 + range_position 상단)
       -> EARLY_TREND.
    5. core_turning_positive 또는 weekly_turning_positive 중 하나라도
       True면 TRANSITION.
    6. 그 외 전부 BASE(fallback).

    **episode/cycle reset(StageLifecycleContext)을 최종 판정에 아직 쓰지
    않는 이유**: "이미 이 episode 안에서 확장했었고 아직 안 꺾였으면
    (previously_expanded_in_current_episode=True) PROGRESSED로 유지"라는
    override를 넣어 46건에 실측 검증했더니, 079550 2023-12-31류(지금
    evidence는 약하지만 실제로 PROGRESSED가 맞는 사례)를 올바르게 잡아주는
    것보다, 오래 전 확장 이력이 있지만 이미 새 국면으로 넘어간 종목
    (086790/010620/042660 등)을 잘못 PROGRESSED로 밀어올리는 부작용이 더
    컸다(override 적용 시 37/46, 미적용 시 38/46, 게다가 미적용이 SEVERE
    오분류도 더 적었다). 079550 하나를 맞추려고 override를 유지하면 다른
    종목에서 더 많은 오분류가 생긴다 — 특정 종목을 위해 global rule을
    비틀지 않는다는 원칙에 따라, v0.1은 override 없이 출시하고 이 실패
    모드를 그대로 문서화한다. `StageLifecycleContext` 계산 자체(episode/cycle
    reset 판정)는 이 함수가 항상 수행해서 `StageClassificationResult.context`로
    반환한다 — WEAK 판정에서 `episode_broken_cycle_reset` reason_code로
    실제로 쓰인다. 최종 stage override로 안 쓸 뿐, 구조 자체는 v0.1에
    존재하고 다음 버전이 이 데이터를 그대로 이어받아 recency 조건 등을
    추가할 수 있다.
    """
    features = snapshot.features
    evidence = _build_evidence(features)

    if evidence.insufficient_data:
        return StageClassificationResult(
            stage=None,
            reason_codes=("insufficient_data",),
            evidence=evidence,
            context=StageLifecycleContext(
                prior_expansion_detected=False,
                episode_broken_after_expansion=False,
                last_expansion_month=None,
                months_since_expansion=None,
                previously_expanded_in_current_episode=False,
            ),
        )

    context = _build_lifecycle_context(snapshot.monthly)

    if evidence.active_decline:
        reason = ["active_decline"]
        if context.prior_expansion_detected and context.episode_broken_after_expansion:
            reason.append("episode_broken_cycle_reset")
        return StageClassificationResult(
            stage=PatternAStage.WEAK,
            reason_codes=tuple(reason),
            evidence=evidence,
            context=context,
        )

    if evidence.core_turning_positive and evidence.expansion_present:
        return StageClassificationResult(
            stage=PatternAStage.PROGRESSED,
            reason_codes=("core_turning_positive", "expansion_present"),
            evidence=evidence,
            context=context,
        )

    if evidence.breakout_like_structure:
        return StageClassificationResult(
            stage=PatternAStage.EARLY_TREND,
            reason_codes=("breakout_like_structure",),
            evidence=evidence,
            context=context,
        )

    if evidence.core_turning_positive or evidence.weekly_turning_positive:
        return StageClassificationResult(
            stage=PatternAStage.TRANSITION,
            reason_codes=("core_or_weekly_turning_positive", "not_breakout_like_structure"),
            evidence=evidence,
            context=context,
        )

    return StageClassificationResult(
        stage=PatternAStage.BASE,
        reason_codes=("fallback_no_active_decline_no_transition_signal",),
        evidence=evidence,
        context=context,
    )
