"""COMMON Stock Report integration for the existing Pattern B authority."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b
from trend_scanner.reporting.pattern_b_report import build_pattern_b_section


TARGET = "2026-09-25"


class FakeRepository:
    query_audit: dict[str, dict] = {}

    def __init__(self, daily: pd.DataFrame):
        self.daily = daily

    def get_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        return self.daily.loc[start:end].copy()


def _write_authorities(root: Path) -> None:
    authority = root / "data/market/rolling_authority"
    authority.mkdir(parents=True)
    intervals = [{
        "ticker": "005930",
        "market": "KOSPI",
        "isu_cd": "KR7005930003",
        "effective_from": "2015-01-01",
        "effective_to": TARGET,
        "state": "COMMON",
    }]
    calendar = pd.bdate_range("2015-01-01", TARGET).strftime("%Y-%m-%d").tolist()
    (authority / "merged_pit_intervals.json").write_text(
        json.dumps({"intervals": intervals}), encoding="utf-8",
    )
    (authority / "merged_trading_calendar.json").write_text(
        json.dumps({"dates": calendar}), encoding="utf-8",
    )


def _daily_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2015-01-02", TARGET)
    index = np.arange(len(dates), dtype=float)
    close = 1000 + index * 0.03 + 80 * np.sin(index / 31)
    return pd.DataFrame({
        "open": close,
        "high": close + 3,
        "low": close - 3,
        "close": close,
        "volume": 1000,
        "trading_value": close * 1000,
    }, index=dates)


def test_common_stock_report_uses_pattern_b_evaluator_and_cuts_history_at_as_of(tmp_path):
    _write_authorities(tmp_path)
    daily = _daily_frame()
    future_row = daily.iloc[[-1]].copy()
    future_row.index = [pd.Timestamp("2026-09-28")]
    repository = FakeRepository(pd.concat([daily, future_row]).sort_index())
    section = build_pattern_b_section(
        ticker="005930",
        name="삼성전자",
        asset_type="COMMON",
        metadata_provenance_mode="CURRENT_VERIFIED",
        as_of=TARGET,
        monthly_observations=[SimpleNamespace(as_of="2026-08-31")],
        repo_root=tmp_path,
        repository=repository,
    )

    assert section is not None
    expected = evaluate_pattern_b("005930", daily, TARGET, name="삼성전자")
    assert section.evaluation_status == expected.evaluation_status.value
    assert section.pattern_b_state == expected.pattern_b_state
    assert section.range_36m == expected.range_36m
    assert section.monthly_ma24_distance == expected.monthly_ma24_distance
    assert section.range_52w == expected.range_52w
    assert section.as_of == TARGET
    assert section.provenance.market_data_authority == "MarketDataRepositoryV2"
    assert section.provenance.state_rule_version == "PATTERN_B_STATE_RULE_V02"
    assert all(point.as_of <= TARGET for point in section.monthly_history)
    assert section.monthly_history[-1].as_of == TARGET


def test_non_common_report_does_not_receive_pattern_b_section(tmp_path):
    assert build_pattern_b_section(
        ticker="069500",
        name="KODEX 200",
        asset_type="ETF",
        metadata_provenance_mode="CURRENT_VERIFIED",
        as_of=TARGET,
        monthly_observations=[],
        repo_root=tmp_path,
        repository=None,
    ) is None
