"""scripts/oos2_hard_negative_audit.py의 counterfactual helper 테스트.

이 audit은 Score를 다시 계산하는 게 아니라 이미 계산된 결과 필드에서
counterfactual(final_without_alignment/alignment_lift/
raw_final_before_clip/confirmation_share)만 사후에 유도한다 — 그
유도 공식 자체를 검증한다. production Score 재계산 경로(build_
historical_snapshot/score_pattern_a)는 KRX 캐시가 있어야 하므로
skip 가능하게 분리했다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.oos_v02_manifest import OOS_V02_VALIDATION_SNAPSHOTS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"

_SCRIPT_PATH = _REPO_ROOT / "scripts" / "oos2_hard_negative_audit.py"
_spec = importlib.util.spec_from_file_location("oos2_hard_negative_audit", _SCRIPT_PATH)
audit = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for snap in OOS_V02_VALIDATION_SNAPSHOTS:
        daily = cache.load(snap.ticker)
        if daily is None or daily.empty:
            return False
        req_start = pd.Timestamp(snap.snapshot_date) - pd.DateOffset(months=36)
        if daily.index.min() > req_start:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "OOS2 manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


def test_final_without_alignment_clips_to_0_100():
    assert audit.final_without_alignment(93.85, 0.0) == pytest.approx(93.85)
    assert audit.final_without_alignment(10.0, 50.0) == 0.0
    assert audit.final_without_alignment(150.0, 0.0) == 100.0


def test_alignment_lift_matches_known_case_현대해상():
    """001450 현대해상(2017-08-31): balanced_core=93.8492, penalty=0,
    alignment_bonus=8 → pattern_a_score는 101.8492에서 100으로 clip.
    final_without_alignment=93.8492, 따라서 실현된 alignment_lift는
    8이 아니라 clip 때문에 6.1508이어야 한다(재리뷰 item 8의 핵심)."""
    balanced = 93.8492
    penalty = 0.0
    without = audit.final_without_alignment(balanced, penalty)
    lift = audit.alignment_lift(100.0, without)
    assert without == pytest.approx(93.8492, abs=1e-3)
    assert lift == pytest.approx(6.1508, abs=1e-3)


def test_raw_final_before_clip_can_exceed_100():
    raw = audit.raw_final_before_clip(93.8492, 8.0, 0.0)
    assert raw == pytest.approx(101.8492, abs=1e-3)
    assert raw > 100.0


def test_confirmation_share_none_when_transition_is_zero():
    assert audit.confirmation_share(0.0, 0.0) is None


def test_confirmation_share_ratio():
    assert audit.confirmation_share(11.5857, 100.0) == pytest.approx(0.115857, abs=1e-4)


def test_manifest_still_has_38_snapshots_and_4_hard_negative_cases():
    """manifest는 이번 라운드에서 수정하지 않는다 — 개수 불변을 확인한다."""
    assert len(OOS_V02_VALIDATION_SNAPSHOTS) == 38
    hard_negative = [s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.case_group == "hard_negative_false_turn"]
    assert len(hard_negative) == 4


def test_audit_script_uses_production_score_pattern_a_identity():
    import trend_scanner.patterns.pattern_a_score as production

    assert audit.score_pattern_a is production.score_pattern_a


def test_audit_script_reuses_v01_baseline_without_reimplementing():
    assert hasattr(audit._compare, "_score_v01_baseline")
    assert callable(audit._compare._score_v01_baseline)


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_audit_output_contains_all_four_hard_negative_cases():
    from trend_scanner.data.cache import ParquetCache
    from trend_scanner.validation.historical_snapshot import build_historical_snapshot

    cache = ParquetCache(base_dir=_CACHE_DIR)
    hard_negative = [s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.case_group == "hard_negative_false_turn"]
    seen = set()
    for spec in hard_negative:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = audit.score_pattern_a(snap.features)
        assert result.pattern_a_score is not None
        seen.add((spec.ticker, spec.snapshot_date))

        if spec.ticker == "001450":
            # 문서의 헤드라인 counterfactual(alignment_lift=6.15)을
            # production 재계산 결과로 직접 guard한다 — 하드코딩된
            # 입력값만으로 통과하는 test_alignment_lift_matches_known_case_
            # 현대해상와 달리, production이 나중에 바뀌면 이 assert가
            # 먼저 깨진다.
            wo_align = audit.final_without_alignment(result.balanced_core_score, result.progressed_penalty)
            lift = audit.alignment_lift(result.pattern_a_score, wo_align)
            assert lift == pytest.approx(6.15, abs=0.01)
    assert len(seen) == 4
