from pathlib import Path

from scripts.analyze_fastcore_v2_entry_pattern_score_bucket_v02 import (
    _bucket_rows,
    score_bucket,
)


def test_score_bucket_boundaries() -> None:
    assert score_bucket(0.0) == "[0, 5)"
    assert score_bucket(5.0) == "[5, 10)"
    assert score_bucket(85.0) == "[85, 90)"
    assert score_bucket(99.99) == "[95, 100]"
    assert score_bucket(100.0) == "[95, 100]"


def test_score_bucket_rejects_out_of_range() -> None:
    for value in (-0.01, 100.01):
        try:
            score_bucket(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)


def test_current_trade_key_is_unique_and_frozen_baseline_is_not_referenced() -> None:
    source = Path("scripts/analyze_fastcore_v2_entry_pattern_score_bucket_v02.py").read_text(encoding="utf-8")
    assert "core_v02_reentry/trades.csv" not in source
    keys = [("000001", "000001_01"), ("000002", "000002_01")]
    assert len(keys) == len(set(keys))


def test_bucket_aggregation_keeps_realized_and_open_returns_separate() -> None:
    rows = [
        {"score_status": "READY", "score_bucket": "[85, 90)", "trade_status": "REALIZED", "return_pct": 50.0},
        {"score_status": "READY", "score_bucket": "[85, 90)", "trade_status": "OPEN_AT_CUTOFF", "return_pct": -40.0},
        {"score_status": "UNAVAILABLE", "score_bucket": None, "trade_status": "REALIZED", "return_pct": 1.0},
    ]
    result = {row["score_bucket"]: row for row in _bucket_rows(rows)}
    assert result["[85, 90)"]["trade_count"] == 2
    assert result["[85, 90)"]["realized_count"] == 1
    assert result["[85, 90)"]["open_count"] == 1
    assert result["[85, 90)"]["avg_return_pct_all"] == 5.0
