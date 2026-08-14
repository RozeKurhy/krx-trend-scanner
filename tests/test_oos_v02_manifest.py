"""oos_v02_manifest.py의 selection freeze 검증 테스트.

이 테스트는 manifest만 검증한다(중복, 형식, development ticker와의
분리) — Score/Feature 계산이나 look-ahead 검증은 여기서 하지 않는다.
그건 validation 단계(scripts/oos2_validate.py)에서 실제 Score를 계산할
때 별도로 검증한다.

score_v02_candidate_compare.py는 scripts/라 pythonpath에 없어서(패키지가
아님) importlib로 파일 경로 기준 직접 로드한다 — 다른 재현성 테스트
파일(test_score_v02_candidate_compare.py)과 동일한 패턴이다.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from trend_scanner.validation.oos_v01_manifest import OOS_V01_DIAGNOSTIC_SNAPSHOTS
from trend_scanner.validation.oos_v02_manifest import (
    OOS_V02_VALIDATION_SNAPSHOTS,
    OOS2SnapshotSpec,
)

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _SCRIPT_PATH)
compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = compare
_spec.loader.exec_module(compare)

_ALLOWED_CASE_GROUPS = {
    "positive_pre_breakout",
    "positive_early_trend",
    "positive_trend_progressed",
    "hard_negative_false_turn",
    "downtrend_reversal_boundary",
    "strong_core_failure",
    "weak_core_strong_support",
    "fast_mover",
    "insufficient_history",
}


def _development_tickers() -> set[str]:
    """OOS2 이전에 이미 v0.2 설계에 쓰인 development ticker 전체 집합을
    코드에서 직접 derive한다(사람이 손으로 옮겨 적은 목록이 아니다) —
    exploration/holdout/negative_control(score_v02_candidate_compare.py)
    + OOS v0.1 diagnostic 29건(oos_v01_manifest.py)."""
    tickers: set[str] = set()
    for row in (
        compare.EXPLORATION_SNAPSHOTS
        + compare.HOLDOUT_SNAPSHOTS
        + compare.NEGATIVE_CONTROL_SNAPSHOTS
    ):
        tickers.add(row["ticker"])
    for source, ticker, _date, _alias in compare.FAST_MOVER_CASES:
        tickers.add(ticker)
    for snap in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        tickers.add(snap.ticker)
    return tickers


def test_manifest_has_no_duplicate_ticker_date_keys():
    keys = [(s.ticker, s.snapshot_date) for s in OOS_V02_VALIDATION_SNAPSHOTS]
    assert len(keys) == len(set(keys))


def test_manifest_snapshot_dates_are_parseable_iso_dates():
    for snap in OOS_V02_VALIDATION_SNAPSHOTS:
        date.fromisoformat(snap.snapshot_date)


def test_manifest_case_groups_are_from_allowed_set():
    for snap in OOS_V02_VALIDATION_SNAPSHOTS:
        assert snap.case_group in _ALLOWED_CASE_GROUPS, (
            f"{snap.ticker}/{snap.snapshot_date}: 알 수 없는 case_group "
            f"'{snap.case_group}'"
        )


def test_manifest_tickers_are_disjoint_from_development_tickers():
    """OOS2 ticker ∩ development ticker = 0 목표를 코드로 직접 검증한다
    (item 4) — 손으로 눈으로 대조한 목록이 아니라 실제 dev 종목 상수를
    import해서 비교한다."""
    oos2_tickers = {s.ticker for s in OOS_V02_VALIDATION_SNAPSHOTS}
    dev_tickers = _development_tickers()
    overlap = oos2_tickers & dev_tickers
    assert overlap == set(), f"development ticker와 겹치는 OOS2 종목: {overlap}"


def test_manifest_has_recommended_minimum_size():
    assert 30 <= len(OOS_V02_VALIDATION_SNAPSHOTS) <= 40


@pytest.mark.parametrize(
    "case_group",
    sorted(_ALLOWED_CASE_GROUPS),
)
def test_every_case_group_has_at_least_one_snapshot(case_group):
    matching = [s for s in OOS_V02_VALIDATION_SNAPSHOTS if s.case_group == case_group]
    assert len(matching) >= 1, f"case_group '{case_group}'에 snapshot이 없다"


def test_manifest_entries_have_non_empty_selection_reason_and_expected_behavior():
    for snap in OOS_V02_VALIDATION_SNAPSHOTS:
        assert isinstance(snap, OOS2SnapshotSpec)
        assert snap.selection_reason.strip()
        assert snap.expected_behavior.strip()
