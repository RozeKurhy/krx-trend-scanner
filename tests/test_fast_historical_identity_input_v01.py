from __future__ import annotations

import inspect
from types import SimpleNamespace

import pandas as pd

import trend_scanner.reporting.stock_report as stock_report


def test_fast_alignment_replay_reads_with_current_pit_identity_bounds(monkeypatch):
    repository = SimpleNamespace()
    expected = pd.DataFrame(
        {"close": [100.0]}, index=pd.DatetimeIndex(["2026-10-08"])
    )
    calls = []

    class Loader:
        def __init__(self, actual_repository, *, end, historical_identity):
            calls.append((actual_repository, pd.Timestamp(end).strftime("%Y-%m-%d"), historical_identity))

        def load(self, ticker):
            assert ticker == "214150"
            return expected

    monkeypatch.setattr(stock_report, "RepositoryV2DailyLoader", Loader)

    loaded = stock_report._load_fast_alignment_daily(repository, "214150", "2026-10-08")

    assert loaded is expected
    assert calls == [(repository, "2026-10-08", False)]
    source = inspect.getsource(stock_report.generate_stock_report)
    assert "_load_fast_alignment_daily(repository, clean_ticker, market_data_end)" in source
    assert "historical_identity=True" not in source


def test_fast_alignment_replay_keeps_expected_unavailable_fail_closed(monkeypatch):
    class Loader:
        def __init__(self, _repository, *, end, historical_identity):
            assert pd.Timestamp(end).strftime("%Y-%m-%d") == "2026-10-08"
            assert historical_identity is False

        def load(self, _ticker):
            return None

    monkeypatch.setattr(stock_report, "RepositoryV2DailyLoader", Loader)

    assert stock_report._load_fast_alignment_daily(object(), "214150", "2026-10-08") is None
