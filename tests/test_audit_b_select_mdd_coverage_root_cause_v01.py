from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/audit_b_select_mdd_coverage_root_cause_v01.py"
SPEC = importlib.util.spec_from_file_location("audit_b_select_mdd_coverage_root_cause_v01", SCRIPT_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_raw_nontrading_placeholder_requires_exact_zero_ohl_volume_and_positive_shares() -> None:
    placeholder = {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 2505,
        "volume": 0,
        "trading_value": 0,
        "listed_shares": 1000000,
    }
    assert AUDIT.raw_nontrading_placeholder(placeholder)
    assert not AUDIT.raw_nontrading_placeholder({**placeholder, "volume": 1})
    assert not AUDIT.raw_nontrading_placeholder({**placeholder, "listed_shares": 0})


def test_valid_raw_trade_requires_positive_ohlc_and_volume() -> None:
    row = {"open": 100, "high": 120, "low": 90, "close": 110, "volume": 50}
    assert AUDIT.valid_raw_trade(row)
    assert not AUDIT.valid_raw_trade({**row, "volume": 0})
    assert not AUDIT.valid_raw_trade({**row, "low": 0})


def test_max_consecutive_missing_dates_uses_exact_session_adjacency() -> None:
    sessions = ["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
    assert AUDIT.max_consecutive_dates(["2024-01-08", "2024-01-09", "2024-01-11"], sessions) == 2


def test_missing_day_and_carry_classification_fail_closed() -> None:
    assert AUDIT.classify_missing_day(0, False) == "CASH_ONLY_DAY_MISSING"
    assert AUDIT.classify_missing_day(2, True) == "POSITION_WITH_UNPRICED_MARK"
    assert AUDIT.classify_missing_day(1, False) == "PORTFOLIO_EQUITY_GENERATION_BUG_CANDIDATE"
    assert AUDIT.recoverable_by_carry([{"valuation_carry_allowed": True}])
    assert not AUDIT.recoverable_by_carry([])
    assert not AUDIT.recoverable_by_carry([
        {"valuation_carry_allowed": True},
        {"valuation_carry_allowed": False},
    ])
