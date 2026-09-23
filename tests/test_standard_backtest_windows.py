from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import run_fastcore_control as runner
from trend_scanner.backtest.standard_windows import (
    STANDARD_BACKTEST_WINDOWS,
    StandardWindowResolutionError,
    resolve_standard_backtest_window,
)
from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    load_rolling_production_market_calendar,
)


ROOT = Path(__file__).resolve().parents[1]


def test_standard_window_dates_resolve_from_validated_rolling_calendar():
    calendar = load_rolling_production_market_calendar(ROOT)
    assert calendar is not None
    assert calendar.source_name == "ROLLING_AUTHORITY_MERGED_CALENDAR_V01"
    assert calendar.metadata["certified_through"] >= "2026-09-01"

    expected = {
        "P1": ("2014-01-02", "2026-08-31", "2026-09-01"),
        "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
        "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
        "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
        "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
    }
    assert set(STANDARD_BACKTEST_WINDOWS) == set(expected)
    for window_id, dates in expected.items():
        result = resolve_standard_backtest_window(window_id, calendar)
        actual = tuple(
            date.strftime("%Y-%m-%d")
            for date in (result.effective_start, result.effective_end, result.execution_support)
        )
        assert actual == dates

    assert calendar.is_completed_month("2026-08-31") is True
    assert calendar.is_trading_day("2026-08-31") is True
    assert calendar.is_trading_day("2026-09-01") is True


def test_standard_window_resolution_fails_closed_without_end_or_support_coverage():
    calendar = MarketCalendarAuthority(
        trading_dates=pd.DatetimeIndex(["2010-01-04", "2026-08-21"]),
        completed_month_ends=[],
        metadata={"certified_through": "2026-08-21"},
    )
    with pytest.raises(StandardWindowResolutionError, match="CALENDAR_AUTHORITY_SHORT_OF_WINDOW_END"):
        resolve_standard_backtest_window("P1", calendar)


def test_unknown_standard_window_fails_closed():
    with pytest.raises(StandardWindowResolutionError, match="UNKNOWN_STANDARD_WINDOW"):
        resolve_standard_backtest_window("P4", None)


def test_runner_candidate_artifact_readiness_is_separate_from_window_validity():
    candidates = runner.validate_frozen_inputs()
    windows = {window_id: runner.resolve_runner_window(window_id) for window_id in STANDARD_BACKTEST_WINDOWS}
    readiness = {
        window_id: runner.candidate_artifact_window_readiness(candidates, window)
        for window_id, window in windows.items()
    }

    assert all(window.resolution.window.window_id == key for key, window in windows.items())
    assert readiness["P2-1"]["status"] == "READY"
    assert readiness["P3-1"]["status"] == "READY"
    assert readiness["P1"]["status"] == "BLOCKED_CANDIDATE_ARTIFACT_RANGE"
    assert readiness["P2-2"]["status"] == "BLOCKED_CANDIDATE_ARTIFACT_RANGE"
    assert readiness["P3-2"]["status"] == "BLOCKED_CANDIDATE_ARTIFACT_RANGE"


def test_resolve_only_accepts_window_without_running_backtest(monkeypatch, capsys):
    monkeypatch.setattr(
        runner,
        "run_pipeline",
        lambda *_args, **_kwargs: pytest.fail("resolve-only must not run the strategy backtest"),
    )

    assert runner.main(["--window", "P2-1", "--resolve-only"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["window_id"] == "P2-1"
    assert payload["runner_accepts_window"] is True
    assert payload["runner_readiness"]["status"] == "READY"
    assert payload["backtest_executed"] is False


def test_runner_default_dates_remain_unchanged():
    assert runner.COMMON_START_DATE == pd.Timestamp("2021-04-01")
    assert runner.SIGNAL_END_DATE == pd.Timestamp("2026-08-14")
    assert runner.EXECUTION_SUPPORT_END_DATE == pd.Timestamp("2026-08-21")
