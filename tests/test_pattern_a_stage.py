"""pattern_a_stage.py(Pattern A Stage Classifier v0.1) 검증 테스트.

여기서 다루는 것:
    - Score 독립성(pattern_a_score/Score 파생값을 쓰지 않는지).
    - StageEvidence 개별 신호의 precedence 동작(synthetic FeatureRow로
      각 stage 분기를 격리해서 확인).
    - insufficient_data 처리(필요한 Feature가 NaN이면 stage=None).
    - Stage Truth Set 46건 회귀(KRX 캐시가 있을 때만, skipif).

여기서 다루지 않는 것: threshold 최적화나 confusion matrix 상세 통계 —
그건 scripts/pattern_a_stage_validate.py와
docs/patterns/pattern_a/validation/stage_classifier_v01.md에서 다룬다.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.feature_report import FeatureRow
from trend_scanner.validation.historical_snapshot import HistoricalSnapshot, build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"

NAN = float("nan")


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "Stage manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."

_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}


def _make_feature_row(**overrides: object) -> FeatureRow:
    """단위 테스트용 synthetic FeatureRow. classify_pattern_a_stage가
    실제로 참조하는 7개 필드(ma24_slope/weekly_ma12_slope/
    ma24_slope_acceleration/avg_price_change_12m/ma_spread/range_position/
    distance_to_resistance)만 overrides로 지정하고, 나머지는 분류 로직이
    쓰지 않는 필드라 임의 값으로 채운다."""
    base: dict[str, object] = dict(
        ticker="TEST",
        name="테스트",
        as_of=pd.Timestamp("2024-01-31"),
        daily_rows=500,
        weekly_rows=100,
        monthly_rows=36,
        monthly_bar_may_be_incomplete=False,
        weekly_bar_may_be_incomplete=False,
        close=10000.0,
        high_36m=12000.0,
        low_36m=8000.0,
        high_24m=12000.0,
        low_24m=8000.0,
        high_12m=11000.0,
        low_12m=9000.0,
        range_36m=0.4,
        range_24m=0.4,
        range_12m=0.2,
        compression_ratio=0.5,
        avg_price_change_12m=0.0,
        range_position=0.5,
        distance_to_resistance=0.2,
        pivot_low_count=2,
        pivot_low_1=9000.0,
        pivot_low_1_date=pd.Timestamp("2023-06-30"),
        pivot_low_2=NAN,
        pivot_low_2_date=None,
        pivot_low_3=NAN,
        pivot_low_3_date=None,
        pivot_low_slope=NAN,
        ma6=10000.0,
        ma12=9800.0,
        ma24=9500.0,
        ma6_slope=0.01,
        ma12_slope=0.01,
        ma24_slope=0.0,
        ma24_slope_acceleration=0.0,
        ma_spread=0.05,
        ma_spread_12m_ago=0.05,
        ma_spread_ratio=1.0,
        atr_pct=0.02,
        atr_pct_12m_ago=0.02,
        atr_ratio=1.0,
        avg_monthly_hl_range_12m=500.0,
        volume_3m_avg=100000.0,
        volume_12m_avg=100000.0,
        volume_ratio_3m_12m=1.0,
        trading_value_3m_avg=1e9,
        trading_value_12m_avg=1e9,
        trading_value_ratio_3m_12m=1.0,
        trading_value_nan_ratio_daily=0.0,
        range_position_52w=0.5,
        weekly_ma12_slope=0.0,
    )
    base.update(overrides)
    return FeatureRow(**base)


def _make_snapshot(features: FeatureRow, monthly: pd.DataFrame | None = None) -> HistoricalSnapshot:
    """단위 테스트용 synthetic HistoricalSnapshot. monthly를 안 주면 빈
    프레임을 쓴다 — `_build_lifecycle_context`는 len(monthly)<2면 바로
    '확장 이력 없음'으로 처리하므로, episode 관련 없는 evidence/precedence
    테스트에서는 이걸로 충분하다."""
    return HistoricalSnapshot(
        requested_snapshot_date=pd.Timestamp("2024-01-31"),
        effective_as_of=pd.Timestamp("2024-01-31"),
        include_incomplete_periods=False,
        monthly_as_of=pd.Timestamp("2024-01-31"),
        weekly_as_of=pd.Timestamp("2024-01-31"),
        features=features,
        monthly=monthly if monthly is not None else pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
    )


# --- Score 독립성 ---


def test_module_does_not_import_pattern_a_score():
    import trend_scanner.patterns.pattern_a_stage as stage_module

    assert not hasattr(stage_module, "score_pattern_a")
    assert not hasattr(stage_module, "pattern_a_score")


def test_module_source_does_not_reference_score_derived_names():
    """import 여부뿐 아니라 소스 코드 자체(모듈 docstring 제외)에 Score
    파생 변수명이 전혀 등장하지 않는지도 확인한다(우회 참조 방지). 모듈
    docstring은 "Score와의 독립성"을 설명하며 이 이름들을 의도적으로
    인용하므로 검사 대상에서 뺀다."""
    import trend_scanner.patterns.pattern_a_stage as stage_module

    full_source = Path(stage_module.__file__).read_text(encoding="utf-8")
    _, _, source = full_source.partition('"""\n\nfrom __future__')
    assert source, "모듈 docstring 종료 지점을 못 찾았다 — 테스트 파싱 로직 확인 필요"
    forbidden = [
        "score_pattern_a(",
        "base_score",
        "transition_score",
        "balanced_core_score",
        "alignment_bonus",
        "confirmation_bonus",
        "progressed_penalty",
    ]
    for name in forbidden:
        assert name not in source, f"Score 파생값 참조 발견: {name}"


# --- insufficient_data ---


def test_insufficient_data_when_required_feature_is_nan():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(ma24_slope=NAN)
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage is None
    assert result.evidence.insufficient_data is True
    assert result.reason_codes == ("insufficient_data",)


def test_sufficient_data_when_all_required_fields_present():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row()
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage is not None
    assert result.evidence.insufficient_data is False


# --- Precedence: WEAK ---


def test_weak_via_steep_ma24_slope():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(ma24_slope=-0.06, weekly_ma12_slope=0.0, avg_price_change_12m=-0.1)
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.WEAK
    assert result.evidence.active_decline is True


def test_weak_via_accelerating_decline_and_large_past_drop():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=-0.01,
        ma24_slope_acceleration=-0.02,
        avg_price_change_12m=-0.2,
        weekly_ma12_slope=0.0,
        range_position=0.5,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.WEAK


def test_weak_via_weekly_not_turned_and_very_low_range_position():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=-0.01,
        ma24_slope_acceleration=0.0,
        avg_price_change_12m=0.0,
        weekly_ma12_slope=-0.01,
        range_position=0.1,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.WEAK


# --- Precedence: PROGRESSED ---


def test_progressed_via_core_positive_and_large_avg_price_change():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.05,
        weekly_ma12_slope=-0.01,
        avg_price_change_12m=0.5,
        ma_spread=0.1,
        range_position=0.85,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.PROGRESSED
    assert result.evidence.core_turning_positive is True
    assert result.evidence.weekly_turning_positive is False


def test_progressed_via_core_positive_and_wide_ma_spread_even_if_avg_change_below_bar():
    """expansion_present는 avg_price_change_12m/ma_spread 중 하나만
    만족해도 된다(AND 아니라 OR) — 000810 삼성화재 2024-06-30 사례에서
    확인된 설계."""
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.05,
        weekly_ma12_slope=0.0,
        avg_price_change_12m=0.28,
        ma_spread=0.25,
        range_position=0.85,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.PROGRESSED


# --- Precedence: EARLY_TREND ---


def test_early_trend_via_breakout_like_structure_without_expansion():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.03,
        weekly_ma12_slope=0.08,
        avg_price_change_12m=0.05,
        ma_spread=0.1,
        range_position=0.85,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.EARLY_TREND
    assert result.evidence.breakout_like_structure is True


# --- Precedence: TRANSITION ---


def test_transition_when_both_core_and_weekly_turning_but_not_breakout_structure():
    """005490 POSCO 2022-12-31류: core/weekly 둘 다 양전환이지만
    range_position이 breakout 기준(0.60)에 못 미치면 TRANSITION."""
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.016,
        weekly_ma12_slope=0.0755,
        avg_price_change_12m=0.0,
        ma_spread=0.05,
        range_position=0.51,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.TRANSITION


def test_transition_when_only_core_turning_positive():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.01,
        weekly_ma12_slope=0.0,
        avg_price_change_12m=0.0,
        ma_spread=0.05,
        range_position=0.4,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.TRANSITION


def test_transition_when_only_weekly_turning_positive_meaningfully():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=-0.01,
        weekly_ma12_slope=0.05,
        avg_price_change_12m=0.0,
        ma_spread=0.05,
        range_position=0.4,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.TRANSITION


# --- Precedence: BASE ---


def test_base_fallback_when_no_signal_fires():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.0,
        weekly_ma12_slope=0.0,
        avg_price_change_12m=0.0,
        ma_spread=0.05,
        range_position=0.4,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.BASE


def test_base_does_not_require_weekly_positive_slope():
    """BASE의 최종 정의(docs/patterns/pattern_a/validation/stage_label_audit_freeze.md)는
    weekly_ma12_slope>0을 필수조건으로 두지 않는다 — weekly가 소폭
    음수여도 다른 신호가 전부 안 뜨면 BASE."""
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    features = _make_feature_row(
        ma24_slope=0.0,
        weekly_ma12_slope=-0.005,
        ma24_slope_acceleration=0.0,
        avg_price_change_12m=0.0,
        ma_spread=0.05,
        range_position=0.4,
    )
    result = classify_pattern_a_stage(_make_snapshot(features))
    assert result.stage == PatternAStage.BASE


# --- StageLifecycleContext: semantic consistency ---


def test_episode_broken_cycle_reset_reason_code_appended_when_past_expansion_then_break():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    dates = pd.date_range("2018-01-31", periods=40, freq="ME")
    monthly = pd.DataFrame(
        {
            "open": 1000.0,
            "high": 1000.0,
            "low": 1000.0,
            "close": 1000.0,
            "volume": 1000.0,
        },
        index=dates,
    )
    # 확장 구간(과거)을 만든다: close가 크게 오른 뒤(avg_price_change_12m
    # 큰 폭) 급락해서 episode_broken 조건(ma24_slope<=-0.045)을 만족시킨다.
    monthly.loc[dates[0:12], "close"] = [1000 + i * 20 for i in range(12)]
    monthly.loc[dates[12:24], "close"] = [1240 + i * 60 for i in range(12)]
    monthly.loc[dates[24:30], "close"] = [1900 - i * 150 for i in range(6)]
    monthly.loc[dates[30:], "close"] = 1000.0
    monthly["open"] = monthly["high"] = monthly["low"] = monthly["close"]

    features = _make_feature_row(
        ma24_slope=-0.06,
        weekly_ma12_slope=-0.02,
        ma24_slope_acceleration=-0.01,
        avg_price_change_12m=-0.3,
        range_position=0.05,
    )
    result = classify_pattern_a_stage(_make_snapshot(features, monthly=monthly))
    assert result.stage == PatternAStage.WEAK
    assert result.context.prior_expansion_detected is True
    assert result.context.episode_broken_after_expansion is True
    assert result.context.previously_expanded_in_current_episode is False
    assert "episode_broken_cycle_reset" in result.reason_codes


def test_lifecycle_context_prior_expansion_and_not_broken():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    dates = pd.date_range("2020-01-31", periods=36, freq="ME")
    monthly = pd.DataFrame(
        {
            "open": 1000.0,
            "high": 1000.0,
            "low": 1000.0,
            "close": 1000.0,
            "volume": 1000.0,
        },
        index=dates,
    )
    # 과거에 완만한 상승 확장 후 장기 지지 유지 (break 없음)
    monthly.loc[dates[0:12], "close"] = [1000 + i * 10 for i in range(12)]
    monthly.loc[dates[12:24], "close"] = [1120 + i * 50 for i in range(12)]
    monthly.loc[dates[24:], "close"] = [1720 + i * 5 for i in range(12)]
    monthly["open"] = monthly["high"] = monthly["low"] = monthly["close"]

    features = _make_feature_row(
        ma24_slope=0.02,
        weekly_ma12_slope=0.05,
        avg_price_change_12m=0.10,
        range_position=0.75,
    )
    result = classify_pattern_a_stage(_make_snapshot(features, monthly=monthly))
    assert result.context.prior_expansion_detected is True
    assert result.context.episode_broken_after_expansion is False
    assert result.context.previously_expanded_in_current_episode is True


def test_lifecycle_context_no_prior_expansion():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    dates = pd.date_range("2020-01-31", periods=36, freq="ME")
    monthly = pd.DataFrame(
        {
            "open": 1000.0,
            "high": 1000.0,
            "low": 1000.0,
            "close": 1000.0,
            "volume": 1000.0,
        },
        index=dates,
    )
    # 평탄한 박스권 (확장 없음)
    features = _make_feature_row(
        ma24_slope=0.0,
        weekly_ma12_slope=0.0,
        avg_price_change_12m=0.0,
        range_position=0.4,
    )
    result = classify_pattern_a_stage(_make_snapshot(features, monthly=monthly))
    assert result.context.prior_expansion_detected is False
    assert result.context.episode_broken_after_expansion is False
    assert result.context.previously_expanded_in_current_episode is False


# --- Stage Truth Set 46건 Frozen v0.1 Regression Fixture (KRX 캐시 필요) ---

EXPECTED_V01_PREDICTIONS: dict[tuple[str, str], PatternAStage] = {
    ("042700", "2019-12-31"): PatternAStage.WEAK,
    ("105560", "2023-12-31"): PatternAStage.BASE,
    ("086790", "2023-12-31"): PatternAStage.BASE,
    ("001040", "2023-12-31"): PatternAStage.TRANSITION,
    ("000880", "2024-12-31"): PatternAStage.TRANSITION,
    ("042700", "2020-11-30"): PatternAStage.EARLY_TREND,
    ("105560", "2024-02-29"): PatternAStage.TRANSITION,
    ("086790", "2024-02-29"): PatternAStage.EARLY_TREND,
    ("001040", "2024-03-31"): PatternAStage.EARLY_TREND,
    ("000880", "2025-02-28"): PatternAStage.EARLY_TREND,
    ("042700", "2023-12-31"): PatternAStage.PROGRESSED,
    ("105560", "2025-12-31"): PatternAStage.PROGRESSED,
    ("086790", "2025-12-31"): PatternAStage.PROGRESSED,
    ("214150", "2023-12-31"): PatternAStage.PROGRESSED,
    ("000810", "2024-06-30"): PatternAStage.PROGRESSED,
    ("015760", "2025-11-30"): PatternAStage.PROGRESSED,
    ("015760", "2023-12-31"): PatternAStage.BASE,
    ("034220", "2020-12-31"): PatternAStage.TRANSITION,
    ("011210", "2019-12-31"): PatternAStage.BASE,
    ("023530", "2025-05-31"): PatternAStage.TRANSITION,
    ("023530", "2023-12-31"): PatternAStage.BASE,
    ("034220", "2020-09-30"): PatternAStage.WEAK,
    ("010620", "2023-12-31"): PatternAStage.TRANSITION,
    ("010620", "2024-12-31"): PatternAStage.PROGRESSED,
    ("012450", "2021-12-31"): PatternAStage.PROGRESSED,
    ("012450", "2022-12-31"): PatternAStage.PROGRESSED,
    ("012450", "2024-06-30"): PatternAStage.PROGRESSED,
    ("079550", "2020-12-31"): PatternAStage.BASE,
    ("079550", "2021-12-31"): PatternAStage.PROGRESSED,
    ("079550", "2023-12-31"): PatternAStage.EARLY_TREND,
    ("005490", "2022-12-31"): PatternAStage.WEAK,
    ("005490", "2023-03-31"): PatternAStage.EARLY_TREND,
    ("005490", "2023-07-31"): PatternAStage.EARLY_TREND,
    ("042660", "2024-10-31"): PatternAStage.TRANSITION,
    ("042660", "2025-07-31"): PatternAStage.PROGRESSED,
    ("003550", "2020-12-31"): PatternAStage.TRANSITION,
    ("010130", "2022-06-30"): PatternAStage.PROGRESSED,
    ("011170", "2023-01-31"): PatternAStage.WEAK,
    ("009150", "2022-12-31"): PatternAStage.WEAK,
    ("018260", "2023-07-31"): PatternAStage.WEAK,
    ("032830", "2021-02-28"): PatternAStage.BASE,
    ("034730", "2020-12-31"): PatternAStage.TRANSITION,
    ("011200", "2024-10-31"): PatternAStage.WEAK,
    ("005380", "2020-08-31"): PatternAStage.EARLY_TREND,
    ("051910", "2020-06-30"): PatternAStage.EARLY_TREND,
    ("000270", "2020-09-30"): PatternAStage.EARLY_TREND,
}


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_frozen_v01_predictions_match_all_46_snapshots():
    """v0.1 classifier가 frozen calibrated baseline이므로 46건 각각의
    출력 결과가 정확히 EXPECTED_V01_PREDICTIONS fixture와 100% 일치해야 한다."""
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_LABELS:
        key = (spec.ticker, spec.snapshot_date)
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = classify_pattern_a_stage(snap)
        assert result.stage == EXPECTED_V01_PREDICTIONS[key], (
            f"{key} prediction mismatch: got {result.stage}, expected {EXPECTED_V01_PREDICTIONS[key]}"
        )


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_classifier_against_46_row_truth_set_matches_frozen_baseline():
    """46건 calibration truth set에 대한 frozen baseline 검증.
    정확히 exact 38건(82.6%), adjacent 5건(10.9%), severe 3건(6.5%)이어야 한다."""
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact = 0
    adjacent = 0
    severe = 0
    total = 0
    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = classify_pattern_a_stage(snap)
        total += 1
        assert result.stage is not None
        if result.stage == spec.audited_stage:
            exact += 1
        elif abs(_STAGE_ORDER[result.stage] - _STAGE_ORDER[spec.audited_stage]) == 1:
            adjacent += 1
        else:
            severe += 1

    assert total == 46
    assert exact == 38, f"EXACT match count expected 38, got {exact}"
    assert adjacent == 5, f"ADJACENT mismatch count expected 5, got {adjacent}"
    assert severe == 3, f"SEVERE mismatch count expected 3, got {severe}"
    assert exact / total == pytest.approx(38 / 46)


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_classifier_never_raises_on_46_row_truth_set():
    from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage

    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = classify_pattern_a_stage(snap)
        assert result.stage is None or isinstance(result.stage, PatternAStage)
        assert isinstance(result.reason_codes, tuple)
        assert len(result.reason_codes) >= 1
