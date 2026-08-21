"""Phase 13E Weekly Trigger Feature Research 테스트.

w.md §23(최소 20개 확인)과 §24(CASE A-D synthetic breakout unit test)를
다룬다. Threshold/Rule/Classifier는 이 Phase의 범위가 아니므로 그에 대한
테스트는 없다(만들지 않는다는 것 자체가 계약).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_weekly_features import (
    FEATURE_NAMES,
    compute_weekly_trigger_features,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily


def _weekly_frame(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    """W-FRI 인덱스의 합성 주봉 DataFrame. high/low를 안 주면 close와 같게 채운다."""
    n = len(closes)
    idx = pd.date_range("2015-01-02", periods=n, freq="W-FRI")
    highs = highs if highs is not None else closes
    lows = lows if lows is not None else closes
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": [1000] * n},
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
# §24 CASE A-D: synthetic breakout unit tests
# --------------------------------------------------------------------------


def test_case_a_simple_breakout_detected():
    """26주 prior high=100, reference close=105 -> breakout offset=0."""
    closes = [85.0] * 26 + [105.0]
    highs = [90.0] * 26
    highs[0] = 100.0
    highs.append(105.0)
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 0.0
    assert feats["close_above_prior_26w_high"] == 1.0


def test_case_b_current_week_high_excluded_from_prior_high():
    """current week high=110이지만 prior 26w high=100 -> current week high가
    prior high 계산에 leak되면 breakout을 놓치는 버그가 생긴다(반드시
    이전 bar만 사용)."""
    closes = [85.0] * 26 + [105.0]
    highs = [90.0] * 26
    highs[5] = 100.0
    highs.append(110.0)  # reference 자신의 high(110) — prior_high 계산에서 반드시 제외돼야 함
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 0.0, "reference 자신의 high가 prior high 계산에 leak됨(버그)"
    assert feats["distance_to_prior_26w_high_pct"] == pytest.approx(105.0 / 100.0 - 1.0)


def test_case_c_breakout_hold_success():
    """breakout at T(level=100), T+1=103, T+2=101, reference(T+3)=108 ->
    post-breakout 구간 전부 level 위에서 마감(hold 성공)."""
    closes = [85.0] * 26 + [101.0, 103.0, 101.0, 108.0]
    highs = [90.0] * 26
    highs[0] = 100.0
    highs += [120.0, 103.0, 101.0, 108.0]  # T의 high=120(재돌파로 오검출되지 않도록 큰 wick)
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 3.0
    assert feats["post_breakout_min_close_vs_level_pct_26w"] == pytest.approx(101.0 / 100.0 - 1.0)
    assert feats["post_breakout_close_hold_ratio_26w"] == 1.0
    assert feats["weeks_closed_above_breakout_level_26w"] == 3.0
    assert feats["close_back_below_breakout_level"] == 0.0


def test_case_d_breakout_hold_failure():
    """breakout at T(level=100), T+1=96, reference(T+2)=95 -> post-breakout
    구간이 이미 level 아래로 이탈(hold 실패)."""
    closes = [85.0] * 26 + [101.0, 96.0, 95.0]
    highs = [90.0] * 26
    highs[0] = 100.0
    highs += [120.0, 96.0, 95.0]
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 2.0
    assert feats["post_breakout_min_close_vs_level_pct_26w"] == pytest.approx(95.0 / 100.0 - 1.0)
    assert feats["post_breakout_close_hold_ratio_26w"] == 0.0
    assert feats["weeks_closed_above_breakout_level_26w"] == 0.0
    assert feats["close_back_below_breakout_level"] == 1.0


def test_no_breakout_event_yields_nan_not_zero():
    """직전 26주 안에 close가 prior high를 넘은 적이 없으면 age/hold
    feature는 전부 NaN(NOT_OBSERVED)이어야 한다 — 0으로 채우면 '방금
    돌파'와 '돌파 없음'을 구분할 수 없게 된다."""
    closes = [100.0 - i * 0.1 for i in range(30)]  # 완만한 하락, 신고점 갱신 없음
    weekly = _weekly_frame(closes)
    feats = compute_weekly_trigger_features(weekly)
    assert np.isnan(feats["weeks_since_26w_close_breakout"])
    assert np.isnan(feats["post_breakout_close_hold_ratio_26w"])
    assert np.isnan(feats["close_back_below_breakout_level"])


# --------------------------------------------------------------------------
# Phase 13E Correction §6: Recent 26w Breakout Horizon regression tests
# --------------------------------------------------------------------------


def test_horizon_case_a_breakout_deep_inside_horizon_detected():
    """§6 item A: search horizon(26주) 안쪽 깊숙한 지점(offset=20)의
    breakout도 정상 detection된다."""
    closes = [85.0] * 26 + [101.0] + [90.0] * 20
    highs = [90.0] * 26
    highs[0] = 100.0
    highs += [101.0] + [90.0] * 20
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 20.0


def test_horizon_case_b_only_stale_breakout_yields_nan():
    """§6 item B: 존재하는 breakout이 search horizon(26주)보다 오래된
    것뿐이면 weeks_since_26w_close_breakout과 그에 의존하는 모든 feature가
    NaN이어야 한다 — Phase 13E Correction의 핵심 버그(원래는 152주 전
    breakout까지 끌어왔음)를 재현/검증."""
    closes = [85.0] * 26 + [101.0] + [90.0] * 30  # breakout at offset=30 (>25)
    highs = [90.0] * 26
    highs[0] = 100.0
    highs += [101.0] + [90.0] * 30
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert np.isnan(feats["weeks_since_26w_close_breakout"])
    assert np.isnan(feats["post_breakout_min_close_vs_level_pct_26w"])
    assert np.isnan(feats["post_breakout_close_hold_ratio_26w"])
    assert np.isnan(feats["close_back_below_breakout_level"])
    assert np.isnan(feats["higher_low_after_breakout_count"])


def test_horizon_case_c_offset_25_allowed_offset_26_not_observed():
    """§6 item C: boundary test. offset=25(search horizon 마지막)는
    detection되고, offset=26은 NOT_OBSERVED(NaN)여야 한다."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    closes_25 = pd.Series([85.0] * 26 + [101.0] + [90.0] * 25)
    highs_25 = pd.Series([90.0] * 26 + [101.0] + [90.0] * 25)
    highs_25.iloc[0] = 100.0
    event_25 = mod._find_breakout_event(closes_25, highs_25, 26, 26)
    assert event_25 is not None
    assert event_25[0] == 26  # positional index of the breakout week
    assert (len(closes_25) - 1) - event_25[0] == 25  # offset == 25

    closes_26 = pd.Series([85.0] * 26 + [101.0] + [90.0] * 26)
    highs_26 = pd.Series([90.0] * 26 + [101.0] + [90.0] * 26)
    highs_26.iloc[0] = 100.0
    event_26 = mod._find_breakout_event(closes_26, highs_26, 26, 26)
    assert event_26 is None


def test_horizon_case_d_stale_event_not_selected_when_absent_recently():
    """§6 item D: stale breakout이 실제로 존재해도(index0의 high=100,
    close[26]=101이 진짜 breakout이지만 offset=30으로 horizon 밖) 최근
    26주 안에는 breakout이 없으므로 그 stale event를 선택하지 않고
    None을 반환해야 한다(_find_breakout_event를 직접 호출해 저수준
    검증)."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    closes = pd.Series([85.0] * 26 + [101.0] + [90.0] * 30)
    highs = pd.Series([90.0] * 26 + [101.0] + [90.0] * 30)
    highs.iloc[0] = 100.0
    event = mod._find_breakout_event(closes, highs, 26, 26)
    assert event is None


def test_horizon_case_e_most_recent_of_multiple_events_selected():
    """§6 item E: 최근 26주 안에 breakout event가 여러 개 있으면 가장
    최근 event를 사용해야 한다(오래된 첫 breakout의 level이 아니라)."""
    closes = (
        [85.0] * 26  # index0-25: 배경
        + [105.0]  # index26: breakout1(level=100), offset=8 from reference(34)
        + [90.0] * 2  # index27-28
        + [110.0]  # index29: breakout2(level=105, prior_high@29 includes index26=105), offset=5
        + [90.0] * 4  # index30-33
        + [95.0]  # index34: reference
    )
    highs = (
        [90.0] * 26
        + [105.0]
        + [90.0] * 2
        + [110.0]
        + [90.0] * 4
        + [95.0]
    )
    highs[0] = 100.0
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["weeks_since_26w_close_breakout"] == 5.0  # breakout2, not breakout1(offset=8)
    assert feats["post_breakout_min_close_vs_level_pct_26w"] == pytest.approx(90.0 / 105.0 - 1.0)


# --------------------------------------------------------------------------
# Phase 13E Correction §6 items F/G: Effective Sample N regression tests
# --------------------------------------------------------------------------


def _synthetic_matrix_for_summary() -> pd.DataFrame:
    """build_summary()의 effective-n 로직만 검증하기 위한 최소 synthetic
    matrix(실제 KRX 캐시 불필요) — 40행이 아니라 9행이지만 human_label/
    weekly_stage_at_reference 컬럼과 feature 결측 패턴만 있으면 충분."""
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


def test_effective_n_sum_matches_feature_count():
    """§6 item F: 각 analysis feature에 대해 sum(human_label별 effective
    n) == feature count(non-NaN 개수)여야 한다."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import research_pattern_a_fast_weekly_trigger as script

    matrix = _synthetic_matrix_for_summary()
    original_analysis_features = script.ANALYSIS_FEATURES
    script.ANALYSIS_FEATURES = ["feature_x"]
    try:
        summary = script.build_summary(matrix)
    finally:
        script.ANALYSIS_FEATURES = original_analysis_features

    row = summary.iloc[0]
    label_n_sum = sum(row[f"{label}_n"] for label in ("GOOD_TRIGGER", "NO_SETUP", "TOO_EARLY"))
    assert label_n_sum == row["count"] == 7  # 9 rows - 2 NaN


def test_setup_good_watch_early_none_n_matches_non_missing_count():
    """§6 item G: n_SETUP_GOOD / n_WATCH_EARLY_NONE이 실제 non-missing
    개수와 일치해야 한다(원래는 NaN 포함 raw count였음)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import research_pattern_a_fast_weekly_trigger as script

    matrix = _synthetic_matrix_for_summary()
    original_analysis_features = script.ANALYSIS_FEATURES
    script.ANALYSIS_FEATURES = ["feature_x"]
    try:
        summary = script.build_summary(matrix)
    finally:
        script.ANALYSIS_FEATURES = original_analysis_features

    row = summary.iloc[0]
    # SETUP & GOOD_TRIGGER rows: index 0(1.0), 1(NaN) -> non-missing=1
    assert row["n_SETUP_GOOD"] == 1
    # WATCH & (TOO_EARLY|NO_SETUP) rows: index 3(4.0),4(5.0),5(NaN),6(7.0),7(8.0) -> non-missing=4
    assert row["n_WATCH_EARLY_NONE"] == 4


# --------------------------------------------------------------------------
# §23 최소 확인 20개
# --------------------------------------------------------------------------


def test_compute_weekly_trigger_features_only_accepts_weekly_dataframe():
    """item 1: weekly DataFrame만 입력받는다."""
    params = inspect.signature(compute_weekly_trigger_features).parameters
    assert list(params) == ["weekly"]


def test_no_human_label_argument():
    """item 2."""
    assert "human_label" not in inspect.signature(compute_weekly_trigger_features).parameters


def test_no_weekly_stage_argument():
    """item 3."""
    assert "weekly_stage_at_reference" not in inspect.signature(compute_weekly_trigger_features).parameters


def test_no_trigger_event_date_argument():
    """item 4."""
    assert "trigger_event_date" not in inspect.signature(compute_weekly_trigger_features).parameters


def test_future_daily_row_append_does_not_change_reference_week_features(daily):
    """item 5: reference_date 이후 실제 daily row를 원본에 추가해도
    reference_date 시점 feature 값이 바뀌지 않아야 한다(진짜 leakage
    테스트 — raw daily 입력에 미래 행을 추가한 뒤 전체 파이프라인을
    다시 통과시킨다)."""
    ref = pd.Timestamp("2022-06-24")
    snap_before = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats_before = compute_weekly_trigger_features(snap_before.weekly)

    future_idx = pd.bdate_range(start=daily.index.max() + pd.Timedelta(days=1), periods=120)
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

    snap_after = build_historical_snapshot("000000", "테스트", future_daily, ref, include_incomplete_periods=False)
    feats_after = compute_weekly_trigger_features(snap_after.weekly)

    assert snap_before.weekly.equals(snap_after.weekly)
    for name in FEATURE_NAMES:
        a, b = feats_before[name], feats_after[name]
        if np.isnan(a):
            assert np.isnan(b), name
        else:
            assert a == pytest.approx(b), name


def test_incomplete_future_week_does_not_affect_features(daily):
    """item 6: reference 이후 진행 중인 주의 daily row가 섞여도
    completed-period 계약 덕분에 feature 값이 바뀌지 않아야 한다."""
    ref = pd.Timestamp("2022-06-22")  # 수요일
    snap_before = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats_before = compute_weekly_trigger_features(snap_before.weekly)

    partial_idx = pd.bdate_range(start=ref + pd.Timedelta(days=1), periods=2)  # 같은 주 남은 거래일
    rng = np.random.default_rng(999)
    extra = pd.DataFrame(
        {
            "open": 99999, "high": 99999, "low": 99999, "close": 99999,
            "volume": rng.integers(1_000, 10_000, size=len(partial_idx)),
            "trading_value": 99999,
        },
        index=partial_idx,
    )
    daily_with_partial_week = pd.concat([daily, extra]).sort_index()

    snap_after = build_historical_snapshot(
        "000000", "테스트", daily_with_partial_week, ref, include_incomplete_periods=False
    )
    feats_after = compute_weekly_trigger_features(snap_after.weekly)

    assert snap_before.weekly.equals(snap_after.weekly)
    for name in FEATURE_NAMES:
        a, b = feats_before[name], feats_after[name]
        if np.isnan(a):
            assert np.isnan(b), name
        else:
            assert a == pytest.approx(b), name


def test_current_week_excluded_from_prior_high_family():
    """item 7 (매우 중요, CASE B와 동일 취지를 §7.3 distance feature에도
    적용): distance_to_prior_26w_high_pct가 reference 자신의 고가를 분모
    계산에 포함하지 않는다."""
    closes = [85.0] * 26 + [90.0]
    highs = [90.0] * 26
    highs[0] = 100.0
    highs.append(500.0)  # reference 자신의 극단적 고가 — prior high 계산에서 제외돼야 함
    weekly = _weekly_frame(closes, highs=highs)
    feats = compute_weekly_trigger_features(weekly)
    assert feats["distance_to_prior_26w_high_pct"] == pytest.approx(90.0 / 100.0 - 1.0)


def test_breakout_features_use_only_past_data():
    """item 8: breakout feature가 과거 data만 사용함 — CASE A/B/C/D로
    이미 커버되지만, prior_high 계산 함수 자체가 close/high/k/search_horizon
    네 인자만 받고 미래 인자를 받지 않음을 시그니처로도 재확인(Phase 13E
    Correction §1로 search_horizon 파라미터가 추가됨)."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    params = inspect.signature(mod._find_breakout_event).parameters
    assert list(params) == ["close", "high", "k", "search_horizon"]


def test_breakout_support_feature_uses_only_post_event_to_reference_window():
    """item 9: breakout support feature가 event 이후 ~ reference까지만
    사용함 — event 이전 구간의 값을 바꿔도 post-breakout 지표가 불변."""
    closes = [85.0] * 26 + [101.0, 103.0, 101.0, 108.0]
    highs = [90.0] * 26
    highs[0] = 100.0
    highs += [120.0, 103.0, 101.0, 108.0]
    weekly = _weekly_frame(closes, highs=highs)
    feats_before = compute_weekly_trigger_features(weekly)

    weekly2 = weekly.copy()
    weekly2.iloc[10, weekly2.columns.get_loc("close")] = 1.0  # event 이전 구간 값을 임의로 훼손
    weekly2.iloc[10, weekly2.columns.get_loc("low")] = 1.0
    feats_after = compute_weekly_trigger_features(weekly2)

    for name in (
        "post_breakout_min_close_vs_level_pct_26w",
        "post_breakout_close_hold_ratio_26w",
        "weeks_closed_above_breakout_level_26w",
    ):
        assert feats_before[name] == pytest.approx(feats_after[name]), name


def test_weekly_low_slope_uses_correct_k_week_span():
    """weekly_low_slope_8w의 formula(low[-1]-low[-1-8])/8가 실제로 8주
    간격을 쓰는지 확인한다 — off-by-one으로 low[-8](7주 간격)을 쓰면
    분자/분모 간격이 안 맞아 값이 12.5% 어긋난다."""
    n = 9
    lows = [10.0] * (n - 1) + [20.0]  # index0=10 ... index7=10, index8(reference)=20
    weekly = _weekly_frame(lows)  # close=high=low 전부 lows와 동일하게 채워짐
    feats = compute_weekly_trigger_features(weekly)
    expected = (20.0 - 10.0) / 8 / 20.0
    assert feats["weekly_low_slope_8w"] == pytest.approx(expected)


def test_insufficient_history_fails_safe_to_nan():
    """item 10: WMA200/52w high 등 required history 부족 시 silent
    fallback 없이 NaN이어야 한다."""
    weekly = _weekly_frame([100.0] * 30)
    feats = compute_weekly_trigger_features(weekly)
    assert np.isnan(feats["weekly_ma200"])
    assert np.isnan(feats["close_vs_wma200_pct"])
    assert np.isnan(feats["distance_from_52w_low_pct"])
    assert np.isnan(feats["range_position_52w"])


_MATRIX_CSV = Path(__file__).resolve().parents[1] / "artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_matrix_v01.csv"


@pytest.mark.skipif(not _MATRIX_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_matrix_has_exactly_40_unique_labeled_samples():
    """item 11, 12, 13, 14: 커밋된 matrix output을 직접 읽어 40행,
    sample_id unique=40, UNLABELED 0건을 검증한다."""
    matrix = pd.read_csv(_MATRIX_CSV, dtype=str)
    assert len(matrix) == 40
    assert matrix["sample_id"].nunique() == 40
    assert (matrix["human_label"] != "UNLABELED").all()
    assert (matrix["weekly_stage_at_reference"] != "UNLABELED").all()


_SUMMARY_CSV = Path(__file__).resolve().parents[1] / "artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_summary_v01.csv"


@pytest.mark.skipif(not _SUMMARY_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_summary_csv_effective_n_sum_matches_count_for_every_feature():
    """Phase 13E Correction §6 item F를 커밋된 산출물 자체로 재검증한다
    (synthetic matrix 테스트만으로는 실제 build_summary 호출 결과를
    보증하지 못한다는 advisor 지적 반영) — 48개 feature 전부에 대해
    sum(human_label별 effective n) == count(전체 non-NaN 개수)."""
    summary = pd.read_csv(_SUMMARY_CSV)
    label_cols = [
        c for c in summary.columns
        if c.endswith("_n") and not c.startswith(("STAGE_", "GROUP_")) and c not in ("n_SETUP_GOOD", "n_WATCH_EARLY_NONE")
    ]
    assert len(label_cols) == 7  # GOOD_TRIGGER/BORDERLINE_TRIGGER/FALSE_TRIGGER/TOO_EARLY/TOO_LATE/TOO_EXTENDED/NO_SETUP
    label_n_sum = summary[label_cols].sum(axis=1)
    assert (label_n_sum == summary["count"]).all()


def test_feature_computation_is_deterministic(daily):
    """item 15."""
    ref = pd.Timestamp("2022-06-24")
    snap1 = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    snap2 = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats1 = compute_weekly_trigger_features(snap1.weekly)
    feats2 = compute_weekly_trigger_features(snap2.weekly)
    for name in FEATURE_NAMES:
        a, b = feats1[name], feats2[name]
        if np.isnan(a):
            assert np.isnan(b)
        else:
            assert a == b


def test_frozen_13c_worksheet_not_imported_or_modified():
    """item 16."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "to_csv" not in src
    assert "human_review" not in src


def test_frozen_13d_artifacts_not_imported_or_modified():
    """item 17."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "monthly_regime_feature" not in src


def test_research_module_does_not_import_production_pattern_a():
    """item 18."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    assert not hasattr(mod, "evaluate_pattern_a")
    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("trend_scanner.patterns" in ln for ln in import_lines)


def test_research_module_has_no_phase12_dependency():
    """item 19."""
    import trend_scanner.research.pattern_a_fast_weekly_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("relative_strength" in ln or "phase12" in ln.lower() for ln in import_lines)


def test_feature_names_are_stable_and_unique():
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert len(FEATURE_NAMES) == 52


_REAL_TICKER = "003100"
_HAS_REAL_CACHE = load_raw_daily(_REAL_TICKER, ParquetCache()) is not None
_SKIP_REASON = "실제 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_real_cache_sample_reference_week_equals_reference_date():
    """item 20(No network 대체 확인 겸): 실제 13C-1 frozen 샘플에서
    weekly.index[-1] == reference_date 가정(모듈 docstring의 근거)이
    실제로 성립하는지 재확인."""
    daily = load_raw_daily(_REAL_TICKER, ParquetCache())
    ref = pd.Timestamp("2025-08-22")
    snap = build_historical_snapshot(_REAL_TICKER, "선광", daily, ref, include_incomplete_periods=False)
    assert snap.weekly.index[-1] == ref
    feats = compute_weekly_trigger_features(snap.weekly)
    assert not np.isnan(feats["distance_to_prior_26w_high_pct"])
