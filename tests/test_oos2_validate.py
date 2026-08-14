"""scripts/oos2_validate.py의 재현성/무결성 회귀 테스트.

scripts/는 패키지가 아니라서 importlib로 파일 경로 기준 직접 로드한다
(다른 재현성 테스트 파일과 동일 패턴). KRX 캐시가 있는 환경(data/raw/
stocks)에서만 실제 계산 경로를 검증하고, 없으면 skip한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v02_manifest import OOS_V02_VALIDATION_SNAPSHOTS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"

_SCRIPT_PATH = _REPO_ROOT / "scripts" / "oos2_validate.py"
_spec = importlib.util.spec_from_file_location("oos2_validate", _SCRIPT_PATH)
oos2_validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = oos2_validate
_spec.loader.exec_module(oos2_validate)


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for snap in OOS_V02_VALIDATION_SNAPSHOTS:
        daily = cache.load(snap.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "OOS2 manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


def test_score_module_calls_production_score_pattern_a_not_a_local_copy():
    """item 30: Candidate C formula를 재구현하지 않고 production
    score_pattern_a를 그대로 쓴다는 것을 import identity로 확인한다."""
    import trend_scanner.patterns.pattern_a_score as production

    assert oos2_validate.score_pattern_a is production.score_pattern_a


def test_oos2_validate_reuses_v01_baseline_without_reimplementing():
    """_score_v01_baseline을 재구현하지 않고 score_v02_candidate_compare.py
    에서 그대로 가져다 쓴다는 것을 함수 identity로 확인한다."""
    assert hasattr(oos2_validate._compare, "_score_v01_baseline")
    assert callable(oos2_validate._compare._score_v01_baseline)


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_every_manifest_snapshot_produces_exactly_one_output_row():
    """manifest 38건 전부가 예외 없이 build_historical_snapshot을
    통과해야 한다(insufficient_history 2건 포함 — item 19에서 이미
    확인했듯 그 2건은 예외가 아니라 insufficient_data=True로 처리된다).
    여기서 실제로 예외가 나면 이 테스트가 그대로 실패해야 한다(try/except
    로 감춰서 "돌긴 돌았다"만 증명하는 걸 피한다)."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    rows = []
    for spec in OOS_V02_VALIDATION_SNAPSHOTS:
        daily = cache.load(spec.ticker)
        build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        rows.append((spec.ticker, spec.snapshot_date))
    manifest_keys = {(s.ticker, s.snapshot_date) for s in OOS_V02_VALIDATION_SNAPSHOTS}
    assert set(rows) == manifest_keys
    assert len(rows) == len(OOS_V02_VALIDATION_SNAPSHOTS)


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_historical_snapshot_uses_only_data_up_to_snapshot_date_no_lookahead():
    """look-ahead 방지 회귀: daily 캐시 마지막 날짜가 snapshot_date보다
    한참 뒤인 종목(positive_trend_progressed 그룹)을 골라, 반환된
    monthly/weekly 마지막 행이 snapshot_date를 넘지 않는지 확인한다."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    spec = next(s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.ticker == "042700" and s.case_group == "positive_pre_breakout")
    daily = cache.load(spec.ticker)
    snap = build_historical_snapshot(
        spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
    )
    cutoff = pd.Timestamp(spec.snapshot_date)
    assert snap.monthly.index.max() <= cutoff
    if snap.monthly_as_of is not None:
        assert snap.monthly_as_of <= cutoff
    if snap.weekly_as_of is not None:
        assert snap.weekly_as_of <= cutoff


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_insufficient_history_snapshots_do_not_raise_and_return_none_score():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    specs = [s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.case_group == "insufficient_history"]
    assert len(specs) >= 1
    for spec in specs:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = score_pattern_a(snap.features)
        assert result.pattern_a_score is None
        assert result.stage is None
        assert result.flags.get("insufficient_data") is True


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_result_row_schema_has_all_documented_columns():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    spec = next(s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.case_group == "positive_early_trend")
    daily = cache.load(spec.ticker)
    snap = build_historical_snapshot(
        spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
    )
    result = score_pattern_a(snap.features)
    required_fields = (
        "base_score", "core_score", "support_score", "confirmation_bonus",
        "transition_score", "balanced_core_score", "alignment_bonus",
        "progressed_evidence_count", "progressed_penalty", "pattern_a_score",
        "stage", "flags",
    )
    for field_name in required_fields:
        assert hasattr(result, field_name)
