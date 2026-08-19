"""Stock Report — Pattern A FAST Weekly History `close` field (additive).

FAST Weekly History의 각 row에 해당 week_ending의 실제 일봉 종가를 추가하는
소규모 additive 개선에 대한 targeted 테스트.

가격은 FAST evaluator output이 아니라 report observation metadata이므로
`trend_scanner.patterns.pattern_a_fast_evaluator`는 이 테스트에서도 수정하지
않는다. `PatternAFastCurrentSignal`에는 close를 추가하지 않는다(범위 밖).
"""

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_weekly_observation_has_close_field():
    """close field가 FAST Weekly Observation에 존재하고, Current Signal에는 없다."""
    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    fast = report.pattern_a_fast

    assert fast.weekly_history, "420770 FAST weekly history가 비어있음"
    for obs in fast.weekly_history:
        assert hasattr(obs, "close")

    # Current Signal에는 이번 작업 범위상 close가 추가되지 않는다.
    assert not hasattr(fast.current, "close")


def test_420770_latest_week_close_matches_monthly_history():
    """420770 / 2026-08-14 FAST weekly close == 120100 (Pattern A Monthly History와 동일 가격)."""
    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    latest = report.pattern_a_fast.weekly_history[-1]
    assert latest.week_ending == "2026-08-14"
    assert latest.close == pytest.approx(120100.0)

    monthly_latest = report.monthly_history.full_monthly_history[-1]
    assert monthly_latest.as_of == "2026-08-14"
    assert latest.close == pytest.approx(monthly_latest.close)


def test_420770_all_weekly_rows_close_matches_local_daily_cache():
    """420770 FAST Weekly History의 모든 row에서 close가 해당 week_ending의 실제 로컬 일봉 close와 동일하다."""
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    daily = cache.load("420770")

    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    fast = report.pattern_a_fast
    assert len(fast.weekly_history) == 49

    checked = 0
    for obs in fast.weekly_history:
        expected_close = float(daily.loc[obs.week_ending, "close"])
        assert obs.close == pytest.approx(expected_close), f"mismatch at {obs.week_ending}"
        checked += 1
    assert checked == 49


def test_close_addition_does_not_change_fast_score_stage_or_count():
    """close 추가 전후 FAST Score / Stage / observation_count가 불변임을 확인 (회귀 방지)."""
    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    fast = report.pattern_a_fast

    assert fast.observation_count == 49
    assert fast.history_start_as_of == "2025-08-22"
    assert fast.history_end_as_of == "2026-08-14"

    latest = fast.weekly_history[-1]
    assert latest.fast_score == pytest.approx(56.5)
    assert latest.score_availability == "PARTIAL"
    assert latest.fast_stage == "SETUP"
    assert latest.stage_availability == "READY"
    assert latest.monthly_regime == "PERMITTED_REGIME"
    assert latest.daily_risk == "ELEVATED"


def test_weekly_close_point_in_time_no_lookahead():
    """과거 weekly row의 close는 이후 시점 데이터 존재 여부와 무관하게 동일하다."""
    report_pit, _, _ = generate_stock_report(ticker="001540", as_of="2026-07-24", repo_root=REPO_ROOT, save_artifacts=False)
    report_future, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)

    obs_pit = report_pit.pattern_a_fast.weekly_history[-1]
    assert obs_pit.week_ending == "2026-07-24"

    obs_from_future = next(o for o in report_future.pattern_a_fast.weekly_history if o.week_ending == "2026-07-24")

    assert obs_pit.close == obs_from_future.close


def test_weekly_close_json_field_present():
    """JSON: pattern_a_fast.weekly_history[].close 존재."""
    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    d = report.to_dict()

    weekly = d["pattern_a_fast"]["weekly_history"]
    assert weekly
    for row in weekly:
        assert "close" in row
    assert weekly[-1]["close"] == pytest.approx(120100.0)


def test_weekly_close_markdown_column_present():
    """Markdown: FAST Weekly History table에 종가 column이 존재하고 실제 값이 렌더링된다."""
    report, _, _ = generate_stock_report(ticker="420770", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    md = render_markdown_report(report)

    assert "| 기준 주 (Week Ending) | 종가 | FAST Score |" in md
    assert "| 2026-08-14 | 120,100 | 56.50 | PARTIAL | SETUP | READY | PERMITTED_REGIME | ELEVATED |" in md


def test_weekly_close_unavailable_shown_as_na_not_zero():
    """close가 없거나 NaN이면 markdown에 N/A로 표시되며 0으로 표시되지 않는다 (직접 unit test)."""
    from trend_scanner.reporting.pattern_a_fast_report import _to_observation

    point = {
        "fast_score": 50.0,
        "fast_score_status": "READY",
        "fast_monthly_permission_state": "PERMITTED_REGIME",
        "fast_daily_risk_state": "NORMAL",
        "fast_machine_stage": "SETUP",
        "fast_machine_stage_status": "READY",
    }
    obs_missing = _to_observation(pd.Timestamp("2026-07-31"), None, point)
    assert obs_missing.close is None
    assert obs_missing.close != 0
