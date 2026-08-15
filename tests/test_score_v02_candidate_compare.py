"""scripts/score_v02_candidate_compare.py의 재현성 회귀 테스트.

scripts/는 패키지가 아니라서(pyproject.toml pythonpath는 src/만 포함)
importlib로 파일 경로 기준으로 직접 로드한다 — main()은 KRX 캐시가 있어야
동작하지만, 이 테스트가 쓰는 함수(_score_v01_baseline/candidate_c_transition/
align_variants 등)는 모듈 import 시점에는 실행되지 않는 순수 함수라
캐시 없이도 임포트/호출 가능하다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _SCRIPT_PATH)
compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# dataclass가 typing 평가 시 sys.modules[cls.__module__]을 찾으므로
# exec 전에 등록해야 한다(그냥 module_from_spec만으로는 sys.modules에
# 안 들어간다).
sys.modules[_spec.name] = compare
_spec.loader.exec_module(compare)


def _features(**overrides) -> SimpleNamespace:
    base = {
        "range_36m": float("nan"),
        "avg_price_change_12m": float("nan"),
        "ma_spread": float("nan"),
        "ma24_slope": float("nan"),
        "weekly_ma12_slope": float("nan"),
        "ma24_slope_acceleration": float("nan"),
        "range_position": float("nan"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- v0.1 baseline: production 상수로부터 완전 독립(재현성 최종 후속) ---


def test_v01_baseline_does_not_import_production_base_or_penalty_constants():
    """production BASE_WEIGHTS/BASE_POINTS/PROGRESSED_EVIDENCE_THRESHOLDS/
    PROGRESSED_PENALTY_BY_EVIDENCE_COUNT를 다시 import하면 이 테스트가
    실패한다 — v0.1 baseline이 production 상수에 조용히 재의존하는 걸
    막는 구조적 가드다."""
    forbidden = (
        "BASE_WEIGHTS",
        "BASE_POINTS",
        "PROGRESSED_EVIDENCE_THRESHOLDS",
        "PROGRESSED_PENALTY_BY_EVIDENCE_COUNT",
    )
    for name in forbidden:
        assert not hasattr(compare, name), f"{name}은 production에서 import하면 안 된다(V01_* 상수만 써야 한다)"


def test_v01_base_constants_are_frozen_literals():
    assert compare.V01_RANGE_36M_POINTS == ((0.6, 100.0), (1.2, 60.0), (2.0, 0.0))
    assert compare.V01_AVG_PRICE_CHANGE_12M_POINTS == ((0.10, 100.0), (0.30, 50.0), (0.60, 0.0))
    assert compare.V01_MA_SPREAD_POINTS == ((0.10, 100.0), (0.25, 50.0), (0.40, 0.0))
    assert compare.V01_BASE_WEIGHTS == {
        "range_36m": 0.55,
        "avg_price_change_12m": 0.30,
        "ma_spread": 0.15,
    }


def test_v01_transition_constants_are_frozen_literals():
    assert compare.V01_MA24_SLOPE_POINTS == ((-0.05, 0.0), (0.00, 50.0), (0.05, 90.0), (0.15, 100.0))
    assert compare.V01_WEEKLY_MA12_SLOPE_POINTS == ((0.00, 20.0), (0.15, 100.0))
    assert compare.V01_MA24_SLOPE_ACCELERATION_POINTS == ((0.00, 30.0), (0.05, 100.0))
    assert compare.V01_TRANSITION_WEIGHTS == {
        "ma24_slope": 0.60,
        "weekly_ma12_slope": 0.20,
        "ma24_slope_acceleration": 0.20,
    }


def test_v01_progressed_and_alignment_constants_are_frozen_literals():
    assert compare.V01_PROGRESSED_EVIDENCE_THRESHOLDS == {
        "range_36m": 1.2,
        "avg_price_change_12m": 0.30,
        "ma_spread": 0.20,
        "ma24_slope": 0.10,
        "range_position": 0.85,
    }
    assert compare.V01_PROGRESSED_PENALTY_BY_EVIDENCE_COUNT == {
        0: 0.0,
        1: 0.0,
        2: 10.0,
        3: 20.0,
        4: 28.0,
        5: 35.0,
    }
    assert compare.V01_ALIGNMENT_BONUS == 8.0


def test_v01_baseline_survives_production_constant_mutation(monkeypatch):
    """future drift 시뮬레이션(item 13): production 상수를 억지로 바꿔도
    frozen v0.1 결과가 그대로여야 한다 — "지금 우연히 같아서 통과"가
    아니라 "애초에 그 값을 안 본다"는 걸 직접 증명한다."""
    import trend_scanner.patterns.pattern_a_score as production

    fv = compare._feature_values(_skc_like_features())
    before = compare._score_v01_baseline(fv)

    monkeypatch.setattr(
        production,
        "BASE_WEIGHTS",
        {"range_36m": 1.0, "avg_price_change_12m": 0.0, "ma_spread": 0.0},
    )
    monkeypatch.setattr(production, "MA24_SLOPE_POINTS", ((-1.0, 0.0), (1.0, 100.0)))
    monkeypatch.setattr(production, "WEEKLY_MA12_SLOPE_POINTS", ((-1.0, 0.0), (1.0, 100.0)))
    monkeypatch.setattr(production, "MA24_SLOPE_ACCELERATION_POINTS", ((-1.0, 0.0), (1.0, 100.0)))
    monkeypatch.setattr(
        production,
        "PROGRESSED_PENALTY_BY_EVIDENCE_COUNT",
        {0: 99.0, 1: 99.0, 2: 99.0, 3: 99.0, 4: 99.0, 5: 99.0},
    )
    monkeypatch.setattr(production, "ALIGNMENT_BONUS", 1.0)

    after = compare._score_v01_baseline(fv)

    assert after.base_score == before.base_score
    assert after.transition_score == before.transition_score
    assert after.alignment_bonus == before.alignment_bonus
    assert after.progressed_penalty == before.progressed_penalty
    assert after.pattern_a_score == pytest.approx(before.pattern_a_score)


def test_v01_baseline_alignment_survives_production_alignment_function_mutation(monkeypatch):
    """재현성 최종 마무리(alignment): production _transition_alignment()을
    무조건 반대로 바꿔도 frozen v0.1의 alignment_bonus/최종 점수는 그대로여야
    한다 — _score_v01_baseline()이 이제 production alignment 함수를 아예
    호출하지 않고 _v01_transition_alignment()만 쓴다는 것을 증명한다."""
    fv = compare._feature_values(
        _features(
            range_36m=0.6,
            avg_price_change_12m=0.10,
            ma_spread=0.10,
            ma24_slope=0.05,
            weekly_ma12_slope=0.15,
            ma24_slope_acceleration=0.05,
            range_position=0.5,
        )
    )
    before = compare._score_v01_baseline(fv)
    assert before.alignment_bonus == 8.0  # sanity: v0.1 정책상 정렬 케이스

    # compare 모듈이 production에서 import해 쓰는 이름을 무조건 반대로 바꾼다
    # (production._transition_alignment 자체를 바꿔도 compare는 import 시점에
    # 함수 객체를 이미 바인딩했으므로, 실제로 compare 쪽에서 참조 가능한
    # 이름을 패치해야 "production이 바뀌었다"는 상황을 재현할 수 있다).
    monkeypatch.setattr(compare, "_transition_alignment", lambda _fv: False)

    after = compare._score_v01_baseline(fv)
    assert after.alignment_bonus == before.alignment_bonus == 8.0
    assert after.pattern_a_score == pytest.approx(before.pattern_a_score)


@pytest.mark.parametrize(
    "missing_field", ["weekly_ma12_slope", "ma24_slope", "ma24_slope_acceleration"]
)
def test_v01_transition_alignment_false_when_any_field_missing(missing_field):
    values = dict(
        weekly_ma12_slope=0.05,
        ma24_slope=0.05,
        ma24_slope_acceleration=0.05,
    )
    values[missing_field] = float("nan")
    fv = compare._feature_values(
        _features(
            range_36m=0.6,
            avg_price_change_12m=0.10,
            ma_spread=0.10,
            range_position=0.5,
            **values,
        )
    )
    assert compare._v01_transition_alignment(fv) is False


# --- v0.1 baseline: Transition formula ---


def test_v01_baseline_transition_is_060_020_020_weighted_sum():
    fv = compare._feature_values(
        _features(
            range_36m=0.6,
            avg_price_change_12m=0.10,
            ma_spread=0.10,
            ma24_slope=0.05,  # core_score = 90
            weekly_ma12_slope=0.15,  # weekly_score = 100
            ma24_slope_acceleration=0.05,  # accel_score = 100
            range_position=0.5,
        )
    )
    result = compare._score_v01_baseline(fv)

    expected = 0.60 * 90.0 + 0.20 * 100.0 + 0.20 * 100.0
    assert result.transition_score == pytest.approx(expected)


# --- v0.1 baseline: alignment는 core 세기와 무관하게 항상 +8 ---


def test_v01_baseline_alignment_is_always_full_bonus_when_aligned_even_with_weak_core():
    fv = compare._feature_values(
        _features(
            range_36m=0.6,
            avg_price_change_12m=0.10,
            ma_spread=0.10,
            ma24_slope=0.005,  # core_score = 54 (v0.2라면 ALIGNMENT_BONUS_WEAK_CORE 대상)
            weekly_ma12_slope=0.05,
            ma24_slope_acceleration=0.01,
            range_position=0.5,
        )
    )
    result = compare._score_v01_baseline(fv)

    assert result.alignment_bonus == 8.0


# --- v0.1 baseline: required anchor ---


@pytest.mark.parametrize("missing_field", ["range_36m", "ma24_slope"])
def test_v01_baseline_required_anchor_missing_marks_insufficient_data(missing_field):
    values = dict(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=0.05,
        weekly_ma12_slope=0.05,
        ma24_slope_acceleration=0.02,
        range_position=0.5,
    )
    values[missing_field] = float("nan")
    fv = compare._feature_values(_features(**values))
    result = compare._score_v01_baseline(fv)

    assert result.insufficient_data is True
    assert result.pattern_a_score is None


# --- v0.1 baseline: progressed penalty table ---


@pytest.mark.parametrize(
    "evidence_count,expected_penalty",
    [(0, 0.0), (1, 0.0), (2, 10.0), (3, 20.0), (4, 28.0), (5, 35.0)],
)
def test_v01_baseline_progressed_penalty_matches_evidence_table(evidence_count, expected_penalty):
    assert compare._v01_progressed_penalty(evidence_count) == expected_penalty


# --- Candidate A(v0.1) vs 현재 production v0.2: weak core + strong support ---


def _skc_like_features() -> SimpleNamespace:
    return _features(
        range_36m=0.6,
        avg_price_change_12m=0.10,
        ma_spread=0.10,
        ma24_slope=-0.01,  # core 약함
        weekly_ma12_slope=0.20,  # support 최대
        ma24_slope_acceleration=0.10,  # support 최대
        range_position=0.5,
    )


def test_candidate_a_v01_differs_from_current_v02_on_weak_core_strong_support():
    features = _skc_like_features()
    fv = compare._feature_values(features)

    v01 = compare._score_v01_baseline(fv)
    v02 = score_pattern_a(features)

    # v0.1: Supporting 40% 비중이 그대로 반영돼 transition이 높다.
    assert v01.transition_score > 50.0
    # v0.2: confirmation_bonus=0(core<50)이라 transition이 core_score 그대로, 낮다.
    assert v02.transition_score <= 40.0
    assert v01.pattern_a_score != pytest.approx(v02.pattern_a_score)
    assert v01.pattern_a_score > v02.pattern_a_score


# --- Candidate C == production v0.2 ---


@pytest.mark.parametrize(
    "features",
    [
        _skc_like_features(),
        _features(
            range_36m=0.6,
            avg_price_change_12m=0.10,
            ma_spread=0.10,
            ma24_slope=0.06,
            weekly_ma12_slope=0.05,
            ma24_slope_acceleration=0.01,
            range_position=0.5,
        ),
        _features(
            range_36m=1.5,
            avg_price_change_12m=0.5,
            ma_spread=0.3,
            ma24_slope=0.15,
            weekly_ma12_slope=0.2,
            ma24_slope_acceleration=0.1,
            range_position=0.9,
        ),
    ],
)
def test_candidate_c_matches_production_v02_score(features):
    fv = compare._feature_values(features)
    v01 = compare._score_v01_baseline(fv)
    c = compare.candidate_c_transition(fv)
    aligns = compare.align_variants(fv, c["core_score"])
    reproduced = compare._final_score(
        v01.base_score, c["transition_c"], aligns["align_c_core_conditional"], v01.progressed_penalty
    )

    v02 = score_pattern_a(features)

    assert reproduced == pytest.approx(v02.pattern_a_score)


# --- known case 5건: v0.1 baseline / production v0.2 값을 코드에 고정 ---
#
# 실제 KRX 캐시(data/raw/stocks/*.parquet, gitignore)가 있어야 재현
# 가능하다 — 이 저장소를 새로 clone한 환경에는 캐시가 없으므로 skip한다.
# 목적은 향후 pattern_a_score.py가 v0.3, v0.4로 바뀌어도 "v0.1 baseline과
# v0.2 freeze 당시 비교했던 숫자"가 테스트 코드 안에 고정돼 조용히
# 깨지지 않게 하는 것이다(item 11).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"
_KNOWN_CASES = [
    # (ticker, name, date, v0.1 baseline final, production v0.2 final)
    ("003550", "LG", "2020-12-31", 71.25, 76.60),
    ("161390", "한국타이어", "2024-04-30", 75.36, 82.49),
    ("011790", "SKC", "2024-06-30", 70.66, 52.45),
    ("251270", "넷마블 boundary", "2020-08-31", 74.67, 57.32),
    ("005490", "POSCO홀딩스 clean early", "2023-03-31", 76.46, 85.77),
]


def _cache_has_all_known_case_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for ticker, _, date_str, _, _ in _KNOWN_CASES:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            return False
        req_start = pd.Timestamp(date_str) - pd.DateOffset(months=36)
        if daily.index.min() > req_start:
            return False
    return True


@pytest.mark.skipif(
    not _cache_has_all_known_case_tickers(),
    reason="known case 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다.",
)
@pytest.mark.parametrize("ticker,name,date,expected_v01,expected_v02", _KNOWN_CASES)
def test_known_case_v01_baseline_and_v02_match_documented_values(ticker, name, date, expected_v01, expected_v02):
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load(ticker)
    snap = build_historical_snapshot(ticker, name, daily, date, include_incomplete_periods=False)

    fv = compare._feature_values(snap.features)
    v01 = compare._score_v01_baseline(fv)
    v02 = score_pattern_a(snap.features)

    assert v01.pattern_a_score == pytest.approx(expected_v01, abs=0.01)
    assert v02.pattern_a_score == pytest.approx(expected_v02, abs=0.01)
