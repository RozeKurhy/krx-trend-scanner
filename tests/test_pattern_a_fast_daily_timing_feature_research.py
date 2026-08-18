"""Phase 13F Daily Timing Feature Research 테스트.

w.md §24(최소 33개 확인)와 §25(CASE A-E synthetic timing unit test)를
다룬다. Threshold/Rule/Classifier/Optimal Entry Date는 이 Phase의 범위가
아니므로 그에 대한 테스트는 없다(만들지 않는다는 것 자체가 계약).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_daily_features import (
    FEATURE_NAMES,
    compute_daily_timing_features,
)
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily


def _daily_frame(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    """영업일 인덱스의 합성 daily DataFrame. high/low/open을 안 주면
    close와 같게 채운다."""
    n = len(closes)
    idx = pd.bdate_range("2020-01-02", periods=n)
    highs = highs if highs is not None else closes
    lows = lows if lows is not None else closes
    opens = opens if opens is not None else closes
    volumes = volumes if volumes is not None else [1000.0] * n
    return pd.DataFrame(
        {
            "open": opens, "high": highs, "low": lows, "close": closes,
            "volume": volumes, "trading_value": [v * c for v, c in zip(volumes, closes)],
        },
        index=idx,
    )


def _make_daily(start: str, periods: int, seed: int = 0) -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=periods)
    rng = np.random.default_rng(seed)
    close = 10_000 + np.cumsum(rng.normal(5, 60, size=periods))
    close = np.clip(close, 1_000, None)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000, 10_000, size=periods),
            "trading_value": close * rng.integers(1_000, 10_000, size=periods),
        },
        index=idx,
    )


@pytest.fixture
def daily() -> pd.DataFrame:
    return _make_daily("2018-01-02", periods=252 * 6)


# --------------------------------------------------------------------------
# §25 CASE A-E: synthetic timing unit tests
# --------------------------------------------------------------------------


def test_case_a_breakout_offset0_and_prior_high_frozen():
    """CASE A: prior 20d high=100, current close=105, current high=110 ->
    breakout offset=0, prior high는 100으로 유지(current bar 제외)."""
    closes = [85.0] * 20 + [105.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs.append(110.0)
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    assert feats["days_since_20d_close_breakout"] == 0.0
    assert feats["close_above_prior_20d_high"] == 1.0
    assert feats["distance_to_prior_20d_high_pct"] == pytest.approx(105.0 / 100.0 - 1.0)


def test_case_b_breakout_hold_success():
    """CASE B: breakout at offset10(level=100), subsequent closes
    103,102,101, current=104 -> hold metrics valid."""
    closes = [85.0] * 20 + [101.0, 103.0, 102.0, 101.0, 104.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs += [120.0, 103.0, 102.0, 101.0, 104.0]
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    assert feats["days_since_20d_close_breakout"] == 4.0
    assert feats["post_breakout_min_close_vs_level_pct_20d"] == pytest.approx(101.0 / 100.0 - 1.0)
    assert feats["post_breakout_close_hold_ratio_20d"] == 1.0
    assert feats["close_back_below_breakout_level_20d"] == 0.0


def test_case_c_breakout_hold_failure_via_low():
    """CASE C: breakout at offset10(level=100), subsequent low=94,
    current close=96 -> hold failure(저가 기준) 확인."""
    closes = [85.0] * 20 + [101.0, 96.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs += [120.0, 96.0]
    lows = [80.0] * 20 + [95.0, 94.0]
    daily = _daily_frame(closes, highs=highs, lows=lows)
    feats = compute_daily_timing_features(daily)
    assert feats["days_since_20d_close_breakout"] == 1.0
    assert feats["post_breakout_min_low_vs_level_pct_20d"] == pytest.approx(94.0 / 100.0 - 1.0)
    assert feats["close_back_below_breakout_level_20d"] == 1.0


def test_case_d_horizon_boundary_offset20_not_observed():
    """CASE D: breakout only offset=20(offset>=20이므로 search
    horizon=20 밖) -> NOT_OBSERVED."""
    closes = [85.0] * 20 + [101.0] + [90.0] * 20
    highs = [90.0] * 20
    highs[0] = 100.0
    highs += [101.0] + [90.0] * 20
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["days_since_20d_close_breakout"])
    assert np.isnan(feats["post_breakout_close_hold_ratio_20d"])
    assert np.isnan(feats["close_back_below_breakout_level_20d"])


def test_case_e_extension_synthetic_gradual_vs_spike():
    """CASE E: 20일 동안 완만히 상승 vs 최근 5일 급등을 synthetic으로
    만들어 recent_5d_max_runup / close_vs_dma20_pct가 의도대로 차이나는지
    검증."""
    gradual = [100.0 + i * 0.2 for i in range(20)]  # 완만한 상승, 20일간 +3.8%
    gradual_daily = _daily_frame(gradual)
    gradual_feats = compute_daily_timing_features(gradual_daily)

    spike = [100.0] * 15 + [105.0, 112.0, 120.0, 130.0, 140.0]  # 최근 5일 급등
    spike_daily = _daily_frame(spike)
    spike_feats = compute_daily_timing_features(spike_daily)

    assert spike_feats["recent_5d_max_runup"] > gradual_feats["recent_5d_max_runup"]
    assert spike_feats["close_vs_dma20_pct"] > gradual_feats["close_vs_dma20_pct"]


# --------------------------------------------------------------------------
# §20 Daily Breakout Semantic Guard: horizon boundary / stale / multiple event
# --------------------------------------------------------------------------


def test_offset19_detected_offset20_not_observed_low_level():
    """§24 item 9/10: _find_breakout_event 직접 호출로 offset=19는
    detection되고 offset=20은 NOT_OBSERVED임을 확인."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    closes_19 = pd.Series([85.0] * 20 + [101.0] + [90.0] * 19)
    highs_19 = pd.Series([90.0] * 20 + [101.0] + [90.0] * 19)
    highs_19.iloc[0] = 100.0
    event_19 = mod._find_breakout_event(closes_19, highs_19, 20, 20)
    assert event_19 is not None
    assert (len(closes_19) - 1) - event_19[0] == 19

    closes_20 = pd.Series([85.0] * 20 + [101.0] + [90.0] * 20)
    highs_20 = pd.Series([90.0] * 20 + [101.0] + [90.0] * 20)
    highs_20.iloc[0] = 100.0
    event_20 = mod._find_breakout_event(closes_20, highs_20, 20, 20)
    assert event_20 is None


def test_stale_breakout_ignored_even_if_only_event():
    """§24 item 11: 존재하는 breakout이 search horizon(20일)보다 오래된
    것뿐이면 이를 선택하지 않고 None."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    closes = pd.Series([85.0] * 20 + [101.0] + [90.0] * 25)  # breakout at offset=25 (>19)
    highs = pd.Series([90.0] * 20 + [101.0] + [90.0] * 25)
    highs.iloc[0] = 100.0
    event = mod._find_breakout_event(closes, highs, 20, 20)
    assert event is None


def test_multiple_recent_breakout_most_recent_selected():
    """§24 item 12: 최근 20일 안에 breakout event가 여러 개 있으면 가장
    최근 event를 사용한다."""
    closes = (
        [85.0] * 20
        + [105.0]  # index20: breakout1(level=100)
        + [90.0] * 2
        + [110.0]  # index23: breakout2(level=105)
        + [90.0] * 4
        + [95.0]  # index28: current
    )
    highs = [90.0] * 20 + [105.0] + [90.0] * 2 + [110.0] + [90.0] * 4 + [95.0]
    highs[0] = 100.0
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    assert feats["days_since_20d_close_breakout"] == 5.0  # breakout2, not breakout1
    assert feats["post_breakout_min_close_vs_level_pct_20d"] == pytest.approx(90.0 / 105.0 - 1.0)


def test_no_breakout_event_yields_nan_not_zero():
    """event가 없으면 event-dependent feature는 0이 아니라 NaN(§21)."""
    closes = [100.0 - i * 0.1 for i in range(25)]  # 완만한 하락, 신고점 갱신 없음
    daily = _daily_frame(closes)
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["days_since_20d_close_breakout"])
    assert np.isnan(feats["post_breakout_close_hold_ratio_20d"])
    assert np.isnan(feats["close_back_below_breakout_level_20d"])


def test_breakout_level_frozen_at_event_time():
    """§24 item 13: breakout_level은 event 당시 prior high로 고정 —
    event 이전 구간 값을 훼손해도 post-breakout 지표가 불변."""
    closes = [85.0] * 20 + [101.0, 103.0, 102.0, 104.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs += [120.0, 103.0, 102.0, 104.0]
    daily = _daily_frame(closes, highs=highs)
    feats_before = compute_daily_timing_features(daily)

    daily2 = daily.copy()
    daily2.iloc[5, daily2.columns.get_loc("close")] = 1.0
    daily2.iloc[5, daily2.columns.get_loc("low")] = 1.0
    feats_after = compute_daily_timing_features(daily2)

    for name in (
        "post_breakout_min_close_vs_level_pct_20d",
        "post_breakout_close_hold_ratio_20d",
        "days_closed_above_breakout_level_20d",
    ):
        assert feats_before[name] == pytest.approx(feats_after[name]), name


def test_post_breakout_hold_uses_only_event_to_current_window():
    """§24 item 15: post breakout hold는 event 이후 ~ current까지만
    사용한다(위 test_breakout_level_frozen_at_event_time과 함께 §24 item
    13/15를 모두 커버)."""
    closes = [85.0] * 20 + [101.0, 108.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs += [120.0, 108.0]
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    # post window = index21(108.0)만 포함, index20(event 자체)은 제외
    assert feats["post_breakout_min_close_vs_level_pct_20d"] == pytest.approx(108.0 / 100.0 - 1.0)


# --------------------------------------------------------------------------
# §6/§22 PIT / current-day-excluded semantics
# --------------------------------------------------------------------------


def test_current_day_excluded_from_prior_high():
    """§24 item 6: current day의 극단적 고가가 prior high 계산에 leak되지
    않는다."""
    closes = [85.0] * 20 + [90.0]
    highs = [90.0] * 20
    highs[0] = 100.0
    highs.append(500.0)  # current 자신의 극단적 고가 — prior high 계산에서 제외돼야 함
    daily = _daily_frame(closes, highs=highs)
    feats = compute_daily_timing_features(daily)
    assert feats["distance_to_prior_20d_high_pct"] == pytest.approx(90.0 / 100.0 - 1.0)


def test_current_day_excluded_from_volume_benchmark():
    """§24 item 7: current day 거래량이 volume_vs_20d_avg의 분모(prior
    20일 평균)에 포함되지 않는다."""
    closes = [100.0] * 21
    volumes = [1000.0] * 20 + [999999.0]  # current day 거래량 폭증
    daily = _daily_frame(closes, volumes=volumes)
    feats = compute_daily_timing_features(daily)
    assert feats["volume_vs_20d_avg"] == pytest.approx(999999.0 / 1000.0)


def test_future_daily_row_append_does_not_change_reference_day_features(daily):
    """§24 item 5: reference_date 이후 실제 daily row를 원본에 추가해도
    PIT slice 재실행 후 feature 값이 바뀌지 않아야 한다."""
    ref = pd.Timestamp("2022-06-24")
    daily_before = daily[daily.index <= ref]
    feats_before = compute_daily_timing_features(daily_before)

    future_idx = pd.bdate_range(start=daily.index.max() + pd.Timedelta(days=1), periods=60)
    rng = np.random.default_rng(123)
    future_close = daily["close"].iloc[-1] + np.cumsum(rng.normal(5, 60, size=len(future_idx)))
    future_close = np.clip(future_close, 1_000, None)
    future_rows = pd.DataFrame(
        {
            "open": future_close, "high": future_close * 1.01, "low": future_close * 0.99,
            "close": future_close,
            "volume": rng.integers(1_000, 10_000, size=len(future_idx)),
            "trading_value": future_close * rng.integers(1_000, 10_000, size=len(future_idx)),
        },
        index=future_idx,
    )
    future_daily = pd.concat([daily, future_rows])
    assert future_daily.loc[: daily.index.max()].equals(daily)

    daily_after = future_daily[future_daily.index <= ref]
    feats_after = compute_daily_timing_features(daily_after)

    assert daily_before.equals(daily_after)
    for name in FEATURE_NAMES:
        a, b = feats_before[name], feats_after[name]
        if np.isnan(a):
            assert np.isnan(b), name
        else:
            assert a == pytest.approx(b), name


# --------------------------------------------------------------------------
# Required history / fail-safe
# --------------------------------------------------------------------------


def test_insufficient_history_fails_safe_to_nan():
    """§24 item 16: required history 부족 시 silent fallback 없이 NaN."""
    daily = _daily_frame([100.0] * 30)
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["daily_ma200"])
    assert np.isnan(feats["close_vs_dma200_pct"])
    assert np.isnan(feats["dma60_vs_dma120_pct"])


def test_ma200_insufficient_history_yields_nan():
    """§24 item 17: MA200 history 부족 시 NaN(별도 확인)."""
    daily = _daily_frame([100.0] * 199)
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["daily_ma200"])
    assert np.isnan(feats["close_vs_dma200_pct"])


def test_atr_calculation_deterministic():
    """§24 item 18: ATR 계산이 결정론적이다(같은 입력 -> 같은 출력)."""
    daily = _daily_frame(
        [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0, 107.0, 109.0,
         111.0, 110.0, 112.0, 114.0, 113.0],
        highs=[101.0, 103.0, 102.0, 104.0, 106.0, 105.0, 107.0, 109.0, 108.0, 110.0,
               112.0, 111.0, 113.0, 115.0, 114.0],
        lows=[99.0, 101.0, 100.0, 102.0, 104.0, 103.0, 105.0, 107.0, 106.0, 108.0,
              110.0, 109.0, 111.0, 113.0, 112.0],
    )
    feats1 = compute_daily_timing_features(daily)
    feats2 = compute_daily_timing_features(daily.copy())
    assert feats1["atr_14_pct"] == feats2["atr_14_pct"]
    assert not np.isnan(feats1["atr_14_pct"])


def test_range_position_divide_by_zero_fail_safe():
    """§24 item 19: high==low(flat range)면 range_position은 NaN(0으로
    나누기 대신)."""
    daily = _daily_frame([100.0] * 10)  # high=low=close 전부 동일 -> range=0
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["range_position_10d"])


def test_volume_denominator_zero_fail_safe():
    """§24 item 20: prior volume 평균이 0(거래정지 등)이면 NaN."""
    closes = [100.0] * 21
    volumes = [0.0] * 20 + [1000.0]
    daily = _daily_frame(closes, volumes=volumes)
    feats = compute_daily_timing_features(daily)
    assert np.isnan(feats["volume_vs_20d_avg"])


# --------------------------------------------------------------------------
# §24 최소 확인 33개 — 함수 시그니처 / metadata / 결정론 / frozen 검증
# --------------------------------------------------------------------------


def test_compute_daily_timing_features_only_accepts_daily_dataframe():
    """item 1: daily DataFrame만 입력받는다."""
    params = inspect.signature(compute_daily_timing_features).parameters
    assert list(params) == ["daily"]


def test_no_human_label_argument():
    """item 2."""
    assert "human_label" not in inspect.signature(compute_daily_timing_features).parameters


def test_no_weekly_stage_argument():
    """item 3."""
    assert "weekly_stage_at_reference" not in inspect.signature(compute_daily_timing_features).parameters


def test_no_trigger_event_argument():
    """item 4."""
    assert "trigger_event_date" not in inspect.signature(compute_daily_timing_features).parameters
    assert "outcome_review_end" not in inspect.signature(compute_daily_timing_features).parameters


def test_feature_computation_is_deterministic(daily):
    """item 27."""
    ref = pd.Timestamp("2022-06-24")
    d1 = daily[daily.index <= ref]
    d2 = daily[daily.index <= ref].copy()
    feats1 = compute_daily_timing_features(d1)
    feats2 = compute_daily_timing_features(d2)
    for name in FEATURE_NAMES:
        a, b = feats1[name], feats2[name]
        if np.isnan(a):
            assert np.isnan(b)
        else:
            assert a == b


def test_frozen_13c_worksheet_not_imported_or_modified():
    """item 28."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "to_csv" not in src
    assert "human_review" not in src


def test_frozen_13d_artifacts_not_imported():
    """item 29."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "monthly_regime_feature" not in src


def test_frozen_13e_artifacts_not_imported():
    """item 30."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "weekly_trigger_feature" not in src


def test_research_module_does_not_import_production_pattern_a():
    """item 31."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    assert not hasattr(mod, "evaluate_pattern_a")
    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("trend_scanner.patterns" in ln for ln in import_lines)


def test_research_module_has_no_phase12_dependency():
    """item 32."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("relative_strength" in ln or "phase12" in ln.lower() for ln in import_lines)


def test_feature_names_are_stable_and_unique():
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert len(FEATURE_NAMES) == 55


# --------------------------------------------------------------------------
# 커밋된 matrix/summary CSV 직접 검증 (research script 실행 후에만 동작)
# --------------------------------------------------------------------------

_MATRIX_CSV = Path(__file__).resolve().parents[1] / "artifacts/pattern_a_fast/research/daily_timing_feature_matrix_v01.csv"


@pytest.mark.skipif(not _MATRIX_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_matrix_has_exactly_40_unique_labeled_samples():
    """item 21, 22, 23: 커밋된 matrix output을 직접 읽어 40행,
    sample_id unique=40, UNLABELED 0건을 검증한다."""
    matrix = pd.read_csv(_MATRIX_CSV, dtype=str)
    assert len(matrix) == 40
    assert matrix["sample_id"].nunique() == 40
    assert (matrix["human_label"] != "UNLABELED").all()
    assert (matrix["weekly_stage_at_reference"] != "UNLABELED").all()


_SUMMARY_CSV = Path(__file__).resolve().parents[1] / "artifacts/pattern_a_fast/research/daily_timing_feature_summary_v01.csv"


@pytest.mark.skipif(not _SUMMARY_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_summary_csv_effective_n_sum_matches_count_for_every_feature():
    """item 24/25: 커밋된 산출물 자체로, 모든 feature에 대해
    sum(human_label별 effective n) == count(전체 non-NaN 개수)."""
    summary = pd.read_csv(_SUMMARY_CSV)
    label_cols = [
        c for c in summary.columns
        if c.endswith("_n") and not c.startswith(("STAGE_", "GROUP_")) and c not in ("n_SETUP_GOOD", "n_WATCH_EARLY_NONE")
    ]
    assert len(label_cols) == 7  # GOOD_TRIGGER/BORDERLINE_TRIGGER/FALSE_TRIGGER/TOO_EARLY/TOO_LATE/TOO_EXTENDED/NO_SETUP
    label_n_sum = summary[label_cols].sum(axis=1)
    assert (label_n_sum == summary["count"]).all()


@pytest.mark.skipif(not _SUMMARY_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_setup_good_watch_early_none_n_matches_non_missing_count():
    """item 26: n_SETUP_GOOD / n_WATCH_EARLY_NONE이 각 feature의 실제
    non-missing 개수 이하(0 이상)임을 sanity check(합성 matrix
    테스트와는 별개로 실제 산출물 자체를 확인)."""
    summary = pd.read_csv(_SUMMARY_CSV)
    assert (summary["n_SETUP_GOOD"] >= 0).all()
    assert (summary["n_WATCH_EARLY_NONE"] >= 0).all()
    assert (summary["n_SETUP_GOOD"] <= 10).all()  # SETUP 전체 n=10
    assert (summary["n_WATCH_EARLY_NONE"] <= 17).all()  # WATCH(24) 중 TOO_EARLY(8)+NO_SETUP(9) 최대 17


def _synthetic_matrix_for_summary() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "human_label": [
                "GOOD_TRIGGER", "GOOD_TRIGGER", "GOOD_TRIGGER",
                "NO_SETUP", "NO_SETUP", "NO_SETUP",
                "TOO_EARLY", "TOO_EARLY", "TOO_EARLY",
            ],
            "weekly_stage_at_reference": [
                "SETUP", "SETUP", "TRIGGER",
                "WATCH", "WATCH", "WATCH",
                "WATCH", "WATCH", "SETUP",
            ],
            "feature_x": [1.0, np.nan, 3.0, 4.0, 5.0, np.nan, 7.0, 8.0, 9.0],
        }
    )


def test_effective_n_sum_matches_feature_count_synthetic():
    """item 25(synthetic으로 build_summary 로직 자체 검증)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import research_pattern_a_fast_daily_timing as script

    matrix = _synthetic_matrix_for_summary()
    original = script.ANALYSIS_FEATURES
    script.ANALYSIS_FEATURES = ["feature_x"]
    try:
        summary = script.build_summary(matrix)
    finally:
        script.ANALYSIS_FEATURES = original

    row = summary.iloc[0]
    label_n_sum = sum(row[f"{label}_n"] for label in ("GOOD_TRIGGER", "NO_SETUP", "TOO_EARLY"))
    assert label_n_sum == row["count"] == 7


def test_setup_good_watch_early_none_n_matches_non_missing_count_synthetic():
    """item 26(synthetic)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import research_pattern_a_fast_daily_timing as script

    matrix = _synthetic_matrix_for_summary()
    original = script.ANALYSIS_FEATURES
    script.ANALYSIS_FEATURES = ["feature_x"]
    try:
        summary = script.build_summary(matrix)
    finally:
        script.ANALYSIS_FEATURES = original

    row = summary.iloc[0]
    assert row["n_SETUP_GOOD"] == 1
    assert row["n_WATCH_EARLY_NONE"] == 4


def test_no_network():
    """item 33: 이 모듈은 순수 함수만 있고 네트워크 관련 import가 없다."""
    import trend_scanner.research.pattern_a_fast_daily_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "requests" not in src
    assert "urllib" not in src
    assert "pykrx" not in src.lower()


_REAL_TICKER = "003100"
_HAS_REAL_CACHE = load_raw_daily(_REAL_TICKER, ParquetCache()) is not None
_SKIP_REASON = "실제 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_real_cache_sample_reference_day_equals_reference_date():
    """실제 13C-1 frozen 샘플에서 daily PIT slice의 마지막 행이
    reference_date와 일치하는지(모듈 docstring의 근거) 재확인."""
    daily = load_raw_daily(_REAL_TICKER, ParquetCache())
    ref = pd.Timestamp("2025-08-22")
    sliced = daily[daily.index <= ref]
    assert sliced.index[-1] == ref
    feats = compute_daily_timing_features(sliced)
    assert not np.isnan(feats["distance_to_prior_20d_high_pct"])
