"""Phase 13C-1 Final Sampling Balance Correction 관련 스크립트 테스트.

scripts/prepare_pattern_a_fast_ground_truth.py와
scripts/generate_pattern_a_fast_ground_truth_charts.py는 trend_scanner
패키지가 아니라 독립 스크립트라 importlib으로 파일 경로 기반 import한다.
가격/수익률 데이터가 필요 없는 순수 함수만 다룬다(§10 targeted tests).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prepare = _load_module(
    "_test_prepare_pattern_a_fast_ground_truth",
    "scripts/prepare_pattern_a_fast_ground_truth.py",
)
charts = _load_module(
    "_test_generate_pattern_a_fast_ground_truth_charts",
    "scripts/generate_pattern_a_fast_ground_truth_charts.py",
)


# --- Historical stratum deterministic selection (w.md §3/§10) --------------


def test_stable_hash_key_is_deterministic_across_calls():
    sample_id = "005930_20220630"
    first = prepare._stable_hash_key(sample_id)
    second = prepare._stable_hash_key(sample_id)
    assert first == second


def test_stable_hash_key_ordering_is_reproducible_and_not_score_based():
    """historical stratum 선정은 forward return 크기가 아니라 sample_id의
    stable hash로만 순서가 정해져야 한다(w.md §3) — 이 테스트는 그 정렬이
    가격/점수 정보 없이도 매번 동일한 순서로 재현됨을 확인한다."""
    sample_ids = [f"{ticker:06d}_20220630" for ticker in (5930, 660, 5380, 35420, 68270, 1)]
    order_1 = sorted(sample_ids, key=prepare._stable_hash_key)
    order_2 = sorted(sample_ids, key=prepare._stable_hash_key)
    assert order_1 == order_2
    # 정렬 함수 시그니처 자체가 sample_id 문자열만 입력받는다 — 가격/수익률
    # 등 outcome 관련 인자가 존재하지 않는다는 것 자체가 "forward return
    # magnitude가 selection probability를 결정하지 않는다"는 계약의 증거다.
    assert prepare._stable_hash_key.__code__.co_argcount == 1


def test_historical_coverage_dates_are_before_recent_stratum_window():
    """RECENT_SYSTEMATIC과 HISTORICAL_COVERAGE 두 stratum의 날짜 그리드가
    겹치지 않아야 "Recent Regime Pool"과 "과거 market regime" 구분이
    실제로 성립한다(w.md §1)."""
    recent_dates = set(prepare.RECENT_COHORT_B_DATES)
    historical_dates = set(prepare.HISTORICAL_COVERAGE_DATES)
    assert recent_dates.isdisjoint(historical_dates)
    assert max(historical_dates) < min(recent_dates)


# --- Orphan chart expected-set (w.md §8) ------------------------------------


def test_expected_chart_filenames_covers_four_suffixes_per_sample():
    expected = charts.expected_chart_filenames(["005930_20220630", "000660_20230101"])
    assert expected == {
        "005930_20220630_monthly_pit.png",
        "005930_20220630_weekly_pit.png",
        "005930_20220630_daily_pit.png",
        "005930_20220630_weekly_outcome.png",
        "000660_20230101_monthly_pit.png",
        "000660_20230101_weekly_pit.png",
        "000660_20230101_daily_pit.png",
        "000660_20230101_weekly_outcome.png",
    }


def test_remove_orphan_charts_deletes_only_files_outside_expected_set(tmp_path):
    chart_dir = tmp_path / "charts"
    chart_dir.mkdir()
    keep = "005930_20220630_monthly_pit.png"
    orphan = "003100_20180629_monthly_pit.png"
    (chart_dir / keep).write_bytes(b"keep")
    (chart_dir / orphan).write_bytes(b"orphan")

    removed = charts.remove_orphan_charts(chart_dir, expected={keep})

    assert removed == [orphan]
    assert (chart_dir / keep).exists()
    assert not (chart_dir / orphan).exists()


def test_remove_orphan_charts_on_missing_dir_is_noop(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    assert charts.remove_orphan_charts(missing_dir, expected={"x.png"}) == []
