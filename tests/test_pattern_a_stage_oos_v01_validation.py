"""pattern_a_stage_oos_v01_validate.py의 OOS Validation 결과 재현성 검증 테스트.

이 테스트는 Stage Classifier v0.1을 35건 OOS manifest에 실행했을 때
동일한 검증 결과(EXACT 24, ADJACENT 10, SEVERE 1, NODATA 0)가
재현되는지 회귀 검증한다 (cache availability guard 포함).
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


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_oos_v01_validation_results_reproducibility():
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
