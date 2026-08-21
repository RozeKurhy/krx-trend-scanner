"""Phase 13D Monthly Regime Feature Research 테스트.

Feature 계산 자체의 PIT-safety(leakage 없음), determinism, 그리고
research script가 frozen 13C artifact를 절대 건드리지 않는다는 계약을
다룬다. Threshold/Rule/Classifier는 이 Phase의 범위가 아니므로 그에 대한
테스트는 없다(만들지 않는다는 것 자체가 계약).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_monthly_features import (
    FEATURE_NAMES,
    compute_monthly_regime_features,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily


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


def test_feature_computation_is_deterministic(daily):
    ref = pd.Timestamp("2022-06-24")
    snap1 = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    snap2 = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats1 = compute_monthly_regime_features(snap1.monthly)
    feats2 = compute_monthly_regime_features(snap2.monthly)
    assert feats1 == feats2 or all(
        (np.isnan(feats1[k]) and np.isnan(feats2[k])) or feats1[k] == feats2[k] for k in FEATURE_NAMES
    )


def test_no_future_daily_row_influence(daily):
    """reference_date 이후 실제 daily row를 원본 데이터에 추가해도
    reference_date 시점 feature 값이 바뀌지 않아야 한다(진짜 leakage 테스트 —
    monthly DataFrame이 아니라 raw daily 입력에 미래 행을 추가한 뒤 전체
    파이프라인(build_historical_snapshot -> compute_monthly_regime_features)을
    다시 통과시킨다)."""
    ref = pd.Timestamp("2022-06-24")
    snap_before = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats_before = compute_monthly_regime_features(snap_before.monthly)

    # 미래 행을 원본 daily 뒤에 그대로 이어붙인다(재생성이 아니라 append) —
    # 그래야 prefix가 byte-identical함이 자명하게 보장된다.
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
    feats_after = compute_monthly_regime_features(snap_after.monthly)

    assert snap_before.monthly.equals(snap_after.monthly)
    for name in FEATURE_NAMES:
        a, b = feats_before[name], feats_after[name]
        if np.isnan(a):
            assert np.isnan(b), name
        else:
            assert a == pytest.approx(b), name


def test_incomplete_future_monthly_period_does_not_affect_features(daily):
    """reference_date 이후 아직 완료되지 않은(진행 중인) 월의 daily row가
    섞여 들어와도 completed-period 계약(build_historical_snapshot,
    include_incomplete_periods=False) 덕분에 feature 값이 바뀌지 않아야
    한다."""
    ref = pd.Timestamp("2022-06-24")  # 금요일, 6월 마지막 완료 주가 아닐 수 있음 -> 월 중순
    snap_before = build_historical_snapshot("000000", "테스트", daily, ref, include_incomplete_periods=False)
    feats_before = compute_monthly_regime_features(snap_before.monthly)

    # ref 다음날부터 같은 달이 끝날 때까지(진행 중인 달) 며칠만 추가
    partial_future_idx = pd.bdate_range(start=ref + pd.Timedelta(days=1), periods=4)
    rng = np.random.default_rng(999)
    extra = pd.DataFrame(
        {
            "open": 99999, "high": 99999, "low": 99999, "close": 99999,
            "volume": rng.integers(1_000, 10_000, size=len(partial_future_idx)),
            "trading_value": 99999,
        },
        index=partial_future_idx,
    )
    daily_with_partial_month = pd.concat([daily, extra]).sort_index()

    snap_after = build_historical_snapshot(
        "000000", "테스트", daily_with_partial_month, ref, include_incomplete_periods=False
    )
    feats_after = compute_monthly_regime_features(snap_after.monthly)

    assert snap_before.monthly.equals(snap_after.monthly)
    for name in FEATURE_NAMES:
        a, b = feats_before[name], feats_after[name]
        if np.isnan(a):
            assert np.isnan(b), name
        else:
            assert a == pytest.approx(b), name


def test_insufficient_history_fails_safe_to_nan(daily):
    """required_history_bars에 못 미치면 silent fallback(예: MA36 부족 시
    MA24로 대체) 없이 NaN이어야 한다."""
    short_daily = daily.iloc[:60]  # 몇 개월 안 되는 짧은 이력
    ref = short_daily.index[-1]
    snap = build_historical_snapshot("000000", "테스트", short_daily, ref, include_incomplete_periods=False)
    feats = compute_monthly_regime_features(snap.monthly)
    assert np.isnan(feats["return_24m"])
    assert np.isnan(feats["monthly_ma24"])
    assert np.isnan(feats["drawdown_from_36m_high"])
    assert np.isnan(feats["range_position_36m"])


def test_feature_names_are_stable_and_unique():
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert len(FEATURE_NAMES) == 37


def test_frozen_13c_worksheet_not_imported_or_modified():
    """이 research 모듈이 frozen 13C worksheet 파일을 자체적으로
    read/write하는 로직을 갖고 있지 않음을 확인한다(그 책임은 스크립트에
    있고, 스크립트는 pytest 대상이 아니다 — w.md §20 lightweight
    validation은 git diff로 별도 확인)."""
    import trend_scanner.research.pattern_a_fast_monthly_features as mod

    assert "pattern_a_fast_human_review_v01" not in mod.__file__
    import inspect

    src = inspect.getsource(mod)
    assert "to_csv" not in src
    assert "human_review" not in src


def test_research_module_does_not_import_production_pattern_a():
    """소스의 실제 import 문에 trend_scanner.patterns(production evaluator)가
    없는지 확인한다 — docstring 내 산문 언급은 오탐이므로 import 문 라인만
    검사한다(w.md §19: production evaluator/scanner pipeline에 연결 금지)."""
    import trend_scanner.research.pattern_a_fast_monthly_features as mod

    assert not hasattr(mod, "evaluate_pattern_a")
    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("trend_scanner.patterns" in ln for ln in import_lines)


_REAL_TICKER = "003100"
_HAS_REAL_CACHE = load_raw_daily(_REAL_TICKER, ParquetCache()) is not None
_SKIP_REASON = "실제 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


def test_compute_monthly_regime_features_does_not_accept_human_label():
    """human_label(정답)이 feature 계산의 입력으로 흘러 들어갈 수 없음을
    함수 시그니처 자체로 보증한다(w.md §20 item 4)."""
    import inspect

    params = inspect.signature(compute_monthly_regime_features).parameters
    assert "human_label" not in params
    assert list(params) == ["monthly"]


def test_research_module_has_no_phase12_dependency():
    """research 모듈의 실제 import 문에 Phase 12(relative_strength 등) 의존이
    없는지 확인한다 — import 문 라인만 검사해 docstring 산문 언급의 오탐을
    피한다(w.md §20 item 10)."""
    import trend_scanner.research.pattern_a_fast_monthly_features as mod

    with open(mod.__file__, encoding="utf-8") as f:
        import_lines = [ln for ln in f if ln.startswith("from ") or ln.startswith("import ")]
    assert not any("relative_strength" in ln or "phase12" in ln.lower() for ln in import_lines)


_MATRIX_CSV = Path(__file__).resolve().parents[1] / "artifacts/patterns/pattern_a_fast/research/feature_role/monthly_regime_feature_matrix_v01.csv"


@pytest.mark.skipif(not _MATRIX_CSV.exists(), reason="research script를 먼저 실행해야 함")
def test_feature_matrix_has_exactly_40_unique_labeled_samples():
    """커밋된 feature matrix output 자체를 직접 읽어 정확히 40행,
    sample_id 중복 없음, human_label에 UNLABELED가 없음을 확인한다
    (w.md §20 item 2, 3 — load_labeled_samples()가 아니라 실제 산출물을
    검증해야 §27 Dataset Gate를 의미 있게 커버한다)."""
    matrix = pd.read_csv(_MATRIX_CSV, dtype=str)
    assert len(matrix) == 40
    assert matrix["sample_id"].nunique() == 40
    assert (matrix["human_label"] != "UNLABELED").all()
    assert (matrix["weekly_stage_at_reference"] != "UNLABELED").all()


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_load_labeled_samples_filters_to_40_from_frozen_worksheet():
    """load_labeled_samples()가 frozen worksheet 60행 중 정확히 40개만
    선택하는지 확인한다. 나머지 20개(UNLABELED)는 필터 조건 자체로
    구조적으로 제외된다."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from research_pattern_a_fast_monthly_regime import load_labeled_samples

    labeled = load_labeled_samples()
    assert len(labeled) == 40
    assert labeled["sample_id"].nunique() == 40
    assert (labeled["human_label"] != "UNLABELED").all()
    assert (labeled["weekly_stage_at_reference"] != "UNLABELED").all()


@pytest.mark.skipif(not _HAS_REAL_CACHE, reason=_SKIP_REASON)
def test_real_cache_sample_matches_source_completed_monthly_bars():
    """실제 13C-1 frozen 샘플 중 하나(003100 선광, 2025-08-22)를 이용해
    monthly_feature가 completed monthly bars 수와 일관된지 확인한다."""
    daily = load_raw_daily(_REAL_TICKER, ParquetCache())
    ref = pd.Timestamp("2025-08-22")
    snap = build_historical_snapshot(_REAL_TICKER, "선광", daily, ref, include_incomplete_periods=False)
    assert snap.monthly.index.max() <= ref
    feats = compute_monthly_regime_features(snap.monthly)
    assert not np.isnan(feats["range_position_12m"])
    assert not np.isnan(feats["monthly_ma6"])
