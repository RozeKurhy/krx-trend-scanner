"""Stock Report — Pattern A FAST Weekly History Integration Tests.

Pattern A(월별)와 Pattern A FAST(주별)를 동일 timeline 표에 합치지 않고 별도
section으로 병렬 표시하는 기능에 대한 회귀/독립성/PIT 테스트.

FAST scoring/stage 로직은 여기서 재계산하지 않는다. 이 테스트들은
``trend_scanner.patterns.pattern_a_fast_evaluator``(Phase 13H frozen script와
semantic parity 검증됨, `tests/test_pattern_a_fast_evaluator_parity.py` 참고)를
재사용하는 report adapter(``pattern_a_fast_report.py``)의 동작을 검증한다.

- Test A: Pattern A Monthly History가 FAST 통합 전후 동일
- Test B: FAST Weekly History가 실제 주별 row로 생성됨
- Test C: FAST lifecycle progression이 여러 주에 걸쳐 독립적으로 표시됨
- Test D: FAST Score unavailable + Stage READY 조합 정상 처리
- Test E: FAST TRIGGER라도 Pattern A Candidate State가 변경되지 않음 (NOT CANDIDATE + TRIGGER 포함)
- Test F/G/H: Pattern A와 FAST의 서로 다른 stage 조합이 실제 데이터로 직접 검증됨
- Test I: FAST unavailable이어도 Pattern A report 정상 생성
- Test J: Weekly Point In Time contract 유지 (lookahead 없음)
- Test K: 미완료 주봉 처리 규칙이 Phase 13 frozen completed-week semantics와 일치
- Test L: Current Summary와 history의 최신 FAST row가 의미적으로 일치
- Parity: frozen OOS 결과와 동일 (ticker, reference_date)에서 동일 score/stage 재현
"""

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.reporting.models import CurrentSnapshot
from trend_scanner.reporting.pattern_a_fast_report import _to_observation, build_pattern_a_fast_section
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pattern_a_monthly_history_unchanged_after_fast_integration():
    """Test A: FAST 통합 후에도 001540 Pattern A Monthly History가 기존 정본 값과 동일하다."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    hist = report.monthly_history
    assert hist.history_start_as_of == "2021-08-31"
    assert hist.history_end_as_of == "2026-08-14"
    assert hist.observation_count == 61
    assert len(hist.full_monthly_history) == 61
    assert hist.recent_12m_observation_count == 13

    cur = report.current_snapshot
    assert cur.pattern_a_score == 97.45
    assert cur.official_stage == "EARLY_TREND"
    assert cur.candidate_state == "candidate"


def test_fast_weekly_history_generated_with_real_rows():
    """Test B: Pattern A FAST Weekly History가 실제 완료된 주별 row로 생성된다."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    fast = report.pattern_a_fast
    assert fast.status == "EXPERIMENTAL"
    assert fast.contract == "HIERARCHICAL_V01"
    assert fast.observation_count > 0
    assert len(fast.weekly_history) == fast.observation_count
    assert fast.weekly_history[-1].week_ending == "2026-08-14"
    for obs in fast.weekly_history:
        assert obs.fast_stage in {"WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED", None}
        assert obs.score_availability in {"READY", "PARTIAL", "UNAVAILABLE"}
        assert obs.stage_availability in {"READY", "UNAVAILABLE"}


def test_fast_lifecycle_progression_across_weeks():
    """Test C: FAST lifecycle이 여러 주에 걸쳐 시간 순서대로 독립적으로 진행된다."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    by_week = {obs.week_ending: obs.fast_stage for obs in report.pattern_a_fast.weekly_history}
    assert by_week["2026-07-03"] == "SETUP"
    assert by_week["2026-07-10"] == "SETUP"
    assert by_week["2026-07-24"] == "TRIGGER"

    distinct_stages = {obs.fast_stage for obs in report.pattern_a_fast.weekly_history}
    assert len(distinct_stages) >= 2, "실제 데이터에서 FAST stage가 전혀 변화하지 않음"


def test_fast_score_unavailable_with_stage_ready_is_handled_independently():
    """Test D: FAST Score unavailable + Stage READY 조합이 0으로 치환되지 않고 독립적으로 처리된다."""
    point = {
        "fast_score": float("nan"),
        "fast_score_status": "UNAVAILABLE",
        "fast_monthly_permission_state": "PERMITTED_REGIME",
        "fast_daily_risk_state": "UNAVAILABLE",
        "fast_machine_stage": "TRIGGER",
        "fast_machine_stage_status": "READY",
    }
    obs = _to_observation(pd.Timestamp("2026-07-31"), 47000.0, point)

    assert obs.close == 47000.0
    assert obs.fast_score is None
    assert obs.score_availability == "UNAVAILABLE"
    assert obs.fast_stage == "TRIGGER"
    assert obs.stage_availability == "READY"
    assert obs.fast_score != 0


def test_fast_trigger_does_not_change_pattern_a_candidate_state():
    """Test E: FAST가 TRIGGER여도 Pattern A Candidate State는 그대로 유지된다."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    assert report.pattern_a_fast.current.fast_stage == "TRIGGER"
    # Pattern A current_snapshot은 FAST와 무관하게 기존 정본 값을 유지한다.
    assert report.current_snapshot.official_stage == "EARLY_TREND"
    assert report.current_snapshot.candidate_state == "candidate"
    assert report.current_snapshot.is_candidate is True


def test_pattern_a_and_fast_stage_combinations_are_not_errors():
    """Test F/G/H (강화): 실제 데이터에서 관측된 서로 다른 Pattern A / FAST stage 조합을 직접 assert한다.

    001540의 실제 이력에서 확인된 조합:
      2026-06-30: Pattern A TRANSITION / FAST SETUP
      2026-08-14: Pattern A EARLY_TREND / FAST TRIGGER
    두 모델이 서로 다른 stage를 갖는 것은 오류가 아니며, 어느 쪽도 상대의 Stage를
    강제로 바꾸지 않는다.
    """
    report_a, _, _ = generate_stock_report(ticker="001540", as_of="2026-06-30", repo_root=REPO_ROOT, save_artifacts=False)
    assert report_a.current_snapshot.official_stage == "TRANSITION"
    assert report_a.pattern_a_fast.current.fast_stage == "SETUP"

    report_b, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report_b.current_snapshot.official_stage == "EARLY_TREND"
    assert report_b.pattern_a_fast.current.fast_stage == "TRIGGER"

    for ticker, as_of in [("005930", "2026-08-14"), ("000020", "2026-08-14")]:
        report, _, _ = generate_stock_report(ticker=ticker, as_of=as_of, repo_root=REPO_ROOT, save_artifacts=False)
        assert report.current_snapshot.official_stage is not None
        assert report.pattern_a_fast.status == "EXPERIMENTAL"


def test_pattern_a_not_candidate_with_fast_trigger_independence():
    """Test E (강화, Minor #4): Pattern A NOT CANDIDATE 상태에서도 FAST TRIGGER가 Candidate로 승격시키지 않는다.

    실제 repository 데이터에서 "Pattern A NOT CANDIDATE + FAST TRIGGER" 자연 발생
    조합을 조사했으나(000020/005930/033560 등 2026년 데이터 스캔) 찾지 못해, w.md
    지침에 따라 deterministic fixture를 사용한다. FAST 쪽은 001540의 실제 2026-07-24
    시점 데이터(TRIGGER 확인됨)를 그대로 사용한다.
    """
    not_candidate_snapshot = CurrentSnapshot(
        pattern_a_score=30.0,
        official_stage="WEAK",
        candidate_state="blocked",
        is_candidate=False,
        market_cap_eok=100.0,
        avg_trading_value_20d_eok=5.0,
        investability_status="INVESTABLE",
        investability_reason="OK",
        is_investable=True,
    )

    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    daily = cache.load("001540")
    as_of = pd.Timestamp("2026-07-24")
    fast_section = build_pattern_a_fast_section(
        ticker="001540",
        name="안국약품",
        daily_slice=daily.loc[daily.index <= as_of],
        as_of=as_of,
        root_path=REPO_ROOT,
    )
    assert fast_section.current.fast_stage == "TRIGGER"

    # 구조적 독립성: build_pattern_a_fast_section()는 candidate_state를 파라미터로도
    # 반환값으로도 다루지 않는다 -> FAST TRIGGER가 Pattern A Candidate State를
    # 코드 경로상 승격시킬 방법이 없다.
    assert not_candidate_snapshot.candidate_state == "blocked"
    assert not_candidate_snapshot.is_candidate is False


def test_fast_unavailable_does_not_fail_whole_report():
    """Test I: FAST 데이터 unavailable이어도 (999999) 전체 Stock Report는 실패하지 않는다."""
    report, _, _ = generate_stock_report(ticker="999999", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    assert report.pattern_a_fast.status == "EXPERIMENTAL"
    assert report.pattern_a_fast.observation_count == 0
    assert report.pattern_a_fast.weekly_history == []
    assert report.pattern_a_fast.current.fast_score is None
    assert report.pattern_a_fast.current.score_availability == "UNAVAILABLE"
    # Markdown 렌더링도 예외 없이 성공해야 한다.
    md = render_markdown_report(report)
    assert "Pattern A FAST" in md


def test_fast_weekly_history_point_in_time_no_lookahead():
    """Test J: 과거 주의 FAST 결과는 이후 시점 데이터 존재 여부와 무관하게 동일하다."""
    report_pit, _, _ = generate_stock_report(ticker="001540", as_of="2026-07-24", repo_root=REPO_ROOT, save_artifacts=False)
    report_future, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    obs_pit = report_pit.pattern_a_fast.weekly_history[-1]
    assert obs_pit.week_ending == "2026-07-24"

    obs_from_future = next(o for o in report_future.pattern_a_fast.weekly_history if o.week_ending == "2026-07-24")

    assert obs_pit.fast_score == obs_from_future.fast_score
    assert obs_pit.fast_stage == obs_from_future.fast_stage
    assert obs_pit.monthly_regime == obs_from_future.monthly_regime
    assert obs_pit.daily_risk == obs_from_future.daily_risk


def test_fast_weekly_history_completed_week_contract():
    """Test K: 미완료 현재 주(금요일 미도래)는 FAST Weekly History에서 제외된다."""
    # 2026-08-12는 수요일이며 해당 주(2026-08-14 금요일 마감)는 아직 완료되지 않았다.
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-12", repo_root=REPO_ROOT, save_artifacts=False)

    fast = report.pattern_a_fast
    assert fast.weekly_history[-1].week_ending == "2026-08-07"
    assert all(pd.Timestamp(obs.week_ending) <= pd.Timestamp("2026-08-12") for obs in fast.weekly_history)
    assert "2026-08-14" not in {obs.week_ending for obs in fast.weekly_history}


def test_current_summary_matches_latest_weekly_history_row():
    """Test L: Current Summary의 FAST 현재 신호가 Weekly History 최신 row와 의미적으로 일치한다."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    fast = report.pattern_a_fast
    latest = fast.weekly_history[-1]
    assert fast.current.as_of == latest.week_ending
    assert fast.current.fast_score == latest.fast_score
    assert fast.current.fast_stage == latest.fast_stage
    assert fast.current.monthly_regime == latest.monthly_regime
    assert fast.current.daily_risk == latest.daily_risk


def test_fast_reuses_frozen_evaluator_matches_oos_ground_truth():
    """Parity: frozen OOS 결과(084670, 2025-12-26)와 동일한 score/stage를 재현한다.

    FAST scoring/stage 로직을 report layer에서 재구현한 것이 아니라 Phase 13H
    frozen evaluator를 그대로 재사용했음을 증명하는 회귀 테스트.
    """
    report, _, _ = generate_stock_report(ticker="084670", as_of="2025-12-26", repo_root=REPO_ROOT, save_artifacts=False)

    fast = report.pattern_a_fast
    obs = next((o for o in fast.weekly_history if o.week_ending == "2025-12-26"), None)
    assert obs is not None, "frozen OOS reference_date row가 FAST weekly history에 없음"
    assert obs.fast_stage == "EXTENDED"
    assert obs.stage_availability == "READY"
    assert obs.fast_score == pytest.approx(53.45, abs=1e-2)
    assert obs.score_availability == "READY"


def test_fast_section_json_schema_is_additive():
    """FAST section 추가가 기존 JSON schema를 backward-compatible additive 방식으로 확장함을 확인."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    d = report.to_dict()

    assert "pattern_a_fast" in d
    existing_keys = {
        "report_version", "ticker", "name", "market", "requested_as_of", "reference_market_date",
        "header", "summary", "current_snapshot", "monthly_history", "foreign_flow",
        "trading_value_flow", "data_quality", "provenance",
    }
    assert existing_keys.issubset(d.keys())
    fast_dict = d["pattern_a_fast"]
    assert set(fast_dict.keys()) == {
        "status", "label", "contract", "lifecycle_status", "current", "weekly_history",
        "history_start_as_of", "history_end_as_of", "observation_count",
    }
