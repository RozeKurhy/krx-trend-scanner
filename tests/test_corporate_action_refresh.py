from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_detector import CorporateActionDetector, CorporateActionSnapshot
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore


def _frame(values=(100, 101, 102, 103, 104), start="2024-01-02"):
    index = pd.date_range(start, periods=len(values), freq="D")
    close = [float(value + 2) for value in values]
    return pd.DataFrame(
        {
            "open": [float(value) for value in values],
            "high": [float(value + 5) for value in values],
            "low": [float(value - 1) for value in values],
            "close": close,
        },
        index=index,
    )


class _Provider:
    def __init__(self, frame=None, error=None):
        self.frame = frame
        self.error = error
        self.calls = []

    def load_daily(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if self.error:
            raise self.error
        return self.frame.copy()


def _seed(tmp_path, frame=None):
    frame = frame if frame is not None else _frame()
    adjusted = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted.save_full("005930", frame, {"requested_start": "2024-01-02", "requested_end": "2024-01-06"})
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")
    detector = CorporateActionDetector()
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000), detector)
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 101, 5000), detector)
    return adjusted, state, frame


def test_refresh_success_requires_full_history_and_marks_clean(tmp_path):
    adjusted, state, old = _seed(tmp_path)
    refreshed = _frame((110, 111, 112, 113, 114, 115))
    provider = _Provider(refreshed)
    result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
    assert result.status == "CLEAN"
    assert result.reason == "REFRESH_SUCCESS"
    assert state.get("005930").status == "CLEAN"
    assert len(provider.calls) == 1
    assert len(adjusted.load_daily("005930")) == 6
    assert result.before_content_sha256 != result.after_content_sha256
    assert set(old.index).issubset(set(adjusted.load_daily("005930").index))


def test_provider_failure_marks_failed_and_preserves_old_store(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    before = (Path(adjusted.base_dir) / "005930.parquet").read_bytes()
    provider = _Provider(error=RuntimeError("network failure"))
    result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
    assert result.status == "FAILED"
    assert state.get("005930").status == "FAILED"
    assert (Path(adjusted.base_dir) / "005930.parquet").read_bytes() == before


def test_partial_response_is_rejected_before_save(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    partial = _frame((110, 111, 113, 114), start="2024-01-02")
    provider = _Provider(partial)
    result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
    assert result.status == "FAILED"
    assert result.reason == "PARTIAL_REFRESH_RESPONSE"
    assert state.get("005930").status == "FAILED"
    assert len(adjusted.load_daily("005930")) == 5


def test_empty_response_is_rejected_before_save(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    empty = pd.DataFrame(
        {column: pd.Series(dtype="float64") for column in ("open", "high", "low", "close")},
        index=pd.DatetimeIndex([]),
    )
    result = CorporateActionRefreshService(state, _Provider(empty), adjusted).refresh_dirty("005930", "2024-01-07")
    assert result.status == "FAILED"
    assert result.reason == "EMPTY_REFRESH_RESPONSE"
    assert len(adjusted.load_daily("005930")) == 5


def test_missing_store_fails_without_provider_fetch(tmp_path):
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")
    detector = CorporateActionDetector()
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000), detector)
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 101, 5000), detector)
    provider = _Provider(_frame())
    result = CorporateActionRefreshService(state, provider, AdjustedPriceStore(tmp_path / "missing")).refresh_dirty("005930", "2024-01-07")
    assert result.status == "FAILED"
    assert result.reason == "ADJUSTED_STORE_MISSING"
    assert provider.calls == []


def test_refresh_end_cannot_shrink_existing_coverage(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    provider = _Provider(_frame((110, 111, 112, 113, 114)))
    result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-04")
    assert result.status == "FAILED"
    assert result.reason == "REFRESH_END_BEFORE_EXISTING_COVERAGE"
    assert provider.calls == []


def test_failed_refresh_can_retry_successfully(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    provider = _Provider(error=RuntimeError("temporary"))
    service = CorporateActionRefreshService(state, provider, adjusted)
    first = service.refresh_dirty("005930", "2024-01-07")
    assert first.status == "FAILED"
    provider.error = None
    provider.frame = _frame((110, 111, 112, 113, 114, 115))
    second = service.refresh_dirty("005930", "2024-01-07")
    assert second.status == "CLEAN"
    assert len(provider.calls) == 2


def test_clean_ticker_does_not_fetch(tmp_path):
    adjusted, state, _ = _seed(tmp_path)
    # Complete a successful refresh first, then a second invocation is a NOOP.
    provider = _Provider(_frame((110, 111, 112, 113, 114, 115)))
    service = CorporateActionRefreshService(state, provider, adjusted)
    assert service.refresh_dirty("005930", "2024-01-07").status == "CLEAN"
    second = service.refresh_dirty("005930", "2024-01-08")
    assert second.status == "NOOP"
    assert len(provider.calls) == 1
