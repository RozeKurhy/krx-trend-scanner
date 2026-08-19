"""Semantic Parity: src/trend_scanner runtime FAST evaluator vs frozen Phase 13H script.

`src/trend_scanner/patterns/pattern_a_fast_evaluator.py`는 frozen research script
(`scripts/research_pattern_a_fast_lead_time_failure.py`)에 대한 production-safe
런타임 대체 구현이다. 이 테스트는 두 구현이 동일한 입력에서 완전히 동일한 결과를
내는지 확인해, 재구현이 원래 로직을 왜곡하지 않았음을 증명한다.

frozen script 자체는 이 테스트에서도 수정하지 않는다.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from scripts.research_pattern_a_fast_lead_time_failure import evaluate_timeline_point

REPO_ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT = REPO_ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT = REPO_ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"


@pytest.fixture(scope="module")
def contracts() -> tuple[dict, dict]:
    score = json.loads(SCORE_CONTRACT.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT.read_text(encoding="utf-8"))
    return score, stage


def test_frozen_oos_ground_truth_case_084670(contracts):
    """w.md 지정 최소 parity case: 084670 / 2025-12-26 -> EXTENDED / 53.45."""
    score, stage = contracts
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    daily = cache.load("084670").sort_index()
    weekly_date = pd.Timestamp("2025-12-26")

    result = evaluate_pattern_a_fast("084670", "동양고속", daily, weekly_date, score, stage)

    assert result["fast_machine_stage"] == "EXTENDED"
    assert result["fast_machine_stage_status"] == "READY"
    assert result["fast_score"] == pytest.approx(53.45, abs=1e-2)
    assert result["fast_score_status"] == "READY"


def test_runtime_evaluator_matches_frozen_script_exactly_across_many_weeks(contracts):
    """001540/005930의 완료된 주봉 다수에서 새 runtime evaluator와 frozen script가 완전히 동일한 dict를 반환한다."""
    score, stage = contracts
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")

    compared = 0
    for ticker, name in [("001540", "안국약품"), ("005930", "삼성전자"), ("000020", "동화약품")]:
        daily = cache.load(ticker).sort_index()
        as_of = daily.index.max()
        weekly_labels = [w for w in to_weekly(daily).index if w <= as_of]
        weekly_labels = [
            w for w in weekly_labels
            if not daily[daily.index <= w].empty and daily[daily.index <= w].index.max().normalize() == w.normalize()
        ]
        # 최근 26주만 비교해도 회귀 감지에는 충분하고 테스트 실행 시간을 절약한다.
        for weekly_date in weekly_labels[-26:]:
            runtime_result = evaluate_pattern_a_fast(ticker, name, daily, weekly_date, score, stage)
            frozen_result = evaluate_timeline_point(ticker, name, daily, weekly_date, score, stage)
            assert runtime_result == frozen_result, f"mismatch at {ticker} {weekly_date.date()}"
            compared += 1

    assert compared >= 50, "비교 대상 주봉 수가 예상보다 적음"


def test_evaluate_fast_contract_matches_frozen_helper_directly(contracts):
    """evaluate_fast_contract 자체(zone/coefficient/rule interpreter)가 frozen script 버전과 동일하다."""
    from scripts.research_pattern_a_fast_lead_time_failure import evaluate_fast_contract as frozen_evaluate_fast_contract
    from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_fast_contract as runtime_evaluate_fast_contract

    score, stage = contracts
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    daily = cache.load("001540").sort_index()
    weekly_date = pd.Timestamp("2026-08-14")

    from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
    from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
    from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features
    from trend_scanner.validation.historical_snapshot import build_historical_snapshot

    snapshot = build_historical_snapshot("001540", "안국약품", daily, weekly_date, include_incomplete_periods=False)
    features: dict[str, float] = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(daily[daily.index <= weekly_date]))

    assert runtime_evaluate_fast_contract(features, score, stage) == frozen_evaluate_fast_contract(features, score, stage)


def _has_scripts_import(source: str) -> bool:
    return any(
        line.strip().startswith(("import scripts", "from scripts"))
        for line in source.splitlines()
    )


def test_evaluator_does_not_import_scripts_package():
    """Test 1: src/trend_scanner runtime evaluator가 scripts/를 import하지 않는다 (packaging boundary)."""
    import trend_scanner.patterns.pattern_a_fast_evaluator as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not _has_scripts_import(source), "runtime evaluator가 scripts/ 패키지를 import해서는 안 됨"


def test_pattern_a_fast_report_does_not_import_scripts_package():
    """pattern_a_fast_report.py도 더 이상 scripts/를 runtime import하지 않는다."""
    import trend_scanner.reporting.pattern_a_fast_report as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not _has_scripts_import(source)
