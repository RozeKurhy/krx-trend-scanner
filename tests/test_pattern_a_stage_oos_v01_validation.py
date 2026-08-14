"""pattern_a_stage_oos_v01_validate.py의 OOS Validation 결과 재현성 및 Prediction Freeze 테스트.

이 테스트는 Stage Classifier v0.1(commit 43ee01c)을 35건 OOS manifest(commit 93f26a0)에
실행했을 때의 공식 first run 결과(commit ae3508e)가 1건의 drift 없이 완벽히
재현되는지 2-tier(per-snapshot regression + aggregate count)로 회귀 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "OOS manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."

_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}

# 35개 frozen prediction fixture (ae3508e first run 기준)
_FROZEN_OOS_V01_PREDICTIONS: tuple[tuple[str, str, PatternAStage], ...] = (
    # WEAK Truth (7) -> Predicted WEAK (7)
    ("006360", "2023-10-31", PatternAStage.WEAK),
    ("006360", "2022-11-30", PatternAStage.WEAK),
    ("009830", "2024-04-30", PatternAStage.WEAK),
    ("018880", "2024-06-30", PatternAStage.WEAK),
    ("000720", "2024-03-31", PatternAStage.WEAK),
    ("035420", "2022-10-31", PatternAStage.WEAK),
    ("004170", "2024-08-31", PatternAStage.WEAK),

    # BASE Truth (7) -> Predicted: BASE (3), TRANSITION (2), WEAK (2)
    ("017670", "2023-12-31", PatternAStage.BASE),
    ("030200", "2023-10-31", PatternAStage.TRANSITION),
    ("024110", "2023-11-30", PatternAStage.TRANSITION),
    ("028260", "2023-10-31", PatternAStage.BASE),
    ("005940", "2023-10-31", PatternAStage.BASE),
    ("271560", "2024-08-31", PatternAStage.WEAK),
    ("068270", "2023-09-30", PatternAStage.WEAK),

    # TRANSITION Truth (7) -> Predicted: TRANSITION (4), BASE (2), WEAK (1)
    ("000660", "2023-05-31", PatternAStage.BASE),
    ("005830", "2023-06-30", PatternAStage.TRANSITION),
    ("006260", "2022-10-31", PatternAStage.WEAK),
    ("028050", "2021-03-31", PatternAStage.BASE),
    ("003230", "2022-04-30", PatternAStage.TRANSITION),
    ("035900", "2020-07-31", PatternAStage.TRANSITION),
    ("055550", "2024-01-31", PatternAStage.TRANSITION),

    # EARLY_TREND Truth (7) -> Predicted: EARLY_TREND (3), TRANSITION (4)
    ("000660", "2023-11-30", PatternAStage.EARLY_TREND),
    ("005850", "2023-04-30", PatternAStage.EARLY_TREND),
    ("005830", "2023-12-31", PatternAStage.TRANSITION),
    ("006260", "2023-02-28", PatternAStage.TRANSITION),
    ("028050", "2021-06-30", PatternAStage.EARLY_TREND),
    ("003230", "2022-11-30", PatternAStage.TRANSITION),
    ("272210", "2024-03-31", PatternAStage.TRANSITION),

    # PROGRESSED Truth (7) -> Predicted: PROGRESSED (7)
    ("000660", "2024-06-30", PatternAStage.PROGRESSED),
    ("003230", "2024-06-30", PatternAStage.PROGRESSED),
    ("086520", "2023-07-31", PatternAStage.PROGRESSED),
    ("086520", "2023-11-30", PatternAStage.PROGRESSED),
    ("035900", "2023-06-30", PatternAStage.PROGRESSED),
    ("138040", "2024-08-31", PatternAStage.PROGRESSED),
    ("006260", "2023-07-31", PatternAStage.PROGRESSED),
)


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_oos_v01_all_predictions_match_frozen_first_run():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    expected_pred_map = {
        (ticker, date): pred for ticker, date, pred in _FROZEN_OOS_V01_PREDICTIONS
    }

    assert len(expected_pred_map) == 35

    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        assert daily is not None and not daily.empty

        snapshot = build_historical_snapshot(
            ticker=spec.ticker,
            name=spec.name,
            daily=daily,
            snapshot_date=spec.snapshot_date,
            include_incomplete_periods=False,
        )
        result = classify_pattern_a_stage(snapshot)
        expected_stage = expected_pred_map.get((spec.ticker, spec.snapshot_date))

        assert result.stage == expected_stage, (
            f"Prediction drift for {spec.ticker} ({spec.name}) on {spec.snapshot_date}: "
            f"expected {expected_stage}, got {result.stage}"
        )


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_oos_v01_aggregate_metrics_regression():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact_count = 0
    adjacent_count = 0
    severe_count = 0
    nodata_count = 0

    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        assert daily is not None and not daily.empty

        snapshot = build_historical_snapshot(
            ticker=spec.ticker,
            name=spec.name,
            daily=daily,
            snapshot_date=spec.snapshot_date,
            include_incomplete_periods=False,
        )
        result = classify_pattern_a_stage(snapshot)
        predicted = result.stage

        if predicted is None:
            nodata_count += 1
        elif predicted == spec.manual_stage:
            exact_count += 1
        else:
            dist = abs(_STAGE_ORDER[predicted] - _STAGE_ORDER[spec.manual_stage])
            if dist == 1:
                adjacent_count += 1
            else:
                severe_count += 1

    assert len(PATTERN_A_STAGE_OOS_V01_LABELS) == 35
    assert nodata_count == 0
    assert exact_count == 24
    assert adjacent_count == 10
    assert severe_count == 1


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_oos_v01_key_challenge_cases_explicit_assertions():
    cache = ParquetCache(base_dir=_CACHE_DIR)

    def _get_pred(ticker: str, name: str, date: str) -> PatternAStage | None:
        daily = cache.load(ticker)
        assert daily is not None and not daily.empty
        snapshot = build_historical_snapshot(
            ticker=ticker, name=name, daily=daily, snapshot_date=date, include_incomplete_periods=False
        )
        return classify_pattern_a_stage(snapshot).stage

    # 1. Episode continuation: 에코프로 2023-11-30 -> PROGRESSED
    assert _get_pred("086520", "에코프로", "2023-11-30") == PatternAStage.PROGRESSED

    # 2. Surge recovery: JYP Ent. 2020-07-31 -> TRANSITION
    assert _get_pred("035900", "JYP Ent.", "2020-07-31") == PatternAStage.TRANSITION

    # 3. False turn: GS건설 2022-11-30 -> WEAK
    assert _get_pred("006360", "GS건설", "2022-11-30") == PatternAStage.WEAK

    # 4. Cycle reset: 셀트리온 2023-09-30 -> WEAK (active_decline boundary)
    assert _get_pred("068270", "셀트리온", "2023-09-30") == PatternAStage.WEAK

    # 5. LS transition false negative: LS 2022-10-31 -> WEAK
    assert _get_pred("006260", "LS", "2022-10-31") == PatternAStage.WEAK
