"""Pattern B operational policy V02 and full-universe audit V02 (fixtures only)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from trend_scanner.patterns import pattern_b_operational as op

_ROOT = Path(__file__).resolve().parents[1]
for _name in ("audit_pattern_b_full_universe_v01", "audit_pattern_b_full_universe_v02"):
    _spec = importlib.util.spec_from_file_location(_name, _ROOT / f"scripts/{_name}.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
audit = sys.modules["audit_pattern_b_full_universe_v02"]

T = "2026-09-21"
_HOLIDAYS = {"2015-01-01", "2021-01-01", "2024-01-01"}  # KRX New Year closures used by the fixtures
DATES = [d.date().isoformat() for d in pd.bdate_range("2010-01-04", T) if d.date().isoformat() not in _HOLIDAYS]


def _iv(frm, to, market="KOSPI", isu="KR7000001001", state="COMMON", ticker="000001"):
    return {"ticker": ticker, "isu_cd": isu, "market": market, "state": state,
            "effective_from": frm, "effective_to": to}


ACTIVE = _iv("2024-01-02", T)


def test_kosdaq_to_kospi_next_trading_day_is_stitched():
    prev = _iv("2010-01-04", "2023-12-29", market="KOSDAQ")
    chain = op.history_chain("000001", ACTIVE, [prev, ACTIVE], DATES)
    assert chain.market_transfer_stitched and chain.stop_reason == op.STOP_NONE
    assert [s.market for s in chain.segments] == ["KOSDAQ", "KOSPI"]
    assert chain.history_effective_from == "2010-01-04"
    assert audit.verify_chain(chain, DATES)


def test_kospi_to_kosdaq_is_stitched_and_chains_repeat():
    first = _iv("2010-01-04", "2014-12-31", market="KOSDAQ")
    middle = _iv("2015-01-02", "2023-12-29", market="KOSPI")
    active = _iv("2024-01-02", T, market="KOSDAQ")
    chain = op.history_chain("000001", active, [first, middle, active], DATES)
    assert [s.market for s in chain.segments] == ["KOSDAQ", "KOSPI", "KOSDAQ"]
    assert chain.history_effective_from == "2010-01-04"


def test_isu_change_is_not_stitched():
    prev = _iv("2010-01-04", "2023-12-29", market="KOSDAQ", isu="KR7000001999")
    chain = op.history_chain("000001", ACTIVE, [prev, ACTIVE], DATES)
    assert not chain.market_transfer_stitched and chain.stop_reason == op.STOP_ISU_CHANGE


def test_non_common_predecessor_is_not_stitched():
    prev = _iv("2010-01-04", "2023-12-29", market="KOSDAQ", state="SPAC")
    chain = op.history_chain("000001", ACTIVE, [prev, ACTIVE], DATES)
    assert not chain.market_transfer_stitched and chain.stop_reason == op.STOP_NON_COMMON


def test_non_common_segment_in_between_blocks_the_older_one():
    older = _iv("2010-01-04", "2020-12-31", market="KOSDAQ")
    between = _iv("2021-01-04", "2023-12-29", market="KOSDAQ", state="DELISTED")
    chain = op.history_chain("000001", ACTIVE, [older, between, ACTIVE], DATES)
    assert len(chain.segments) == 1 and chain.stop_reason == op.STOP_NON_COMMON


def test_trading_day_gap_is_not_stitched():
    prev = _iv("2010-01-04", "2023-12-27", market="KOSDAQ")
    chain = op.history_chain("000001", ACTIVE, [prev, ACTIVE], DATES)
    assert not chain.market_transfer_stitched and chain.stop_reason == op.STOP_GAP


def test_long_relisting_gap_is_not_stitched():
    prev = _iv("2010-01-04", "2016-05-04", market="KOSDAQ")
    active = _iv("2024-03-13", T, market="KOSDAQ")
    chain = op.history_chain("000001", active, [prev, active], DATES)
    assert len(chain.segments) == 1 and chain.stop_reason == op.STOP_GAP


def test_same_market_contiguous_is_not_stitched():
    prev = _iv("2010-01-04", "2023-12-29", market="KOSPI")
    chain = op.history_chain("000001", ACTIVE, [prev, ACTIVE], DATES)
    assert not chain.market_transfer_stitched and chain.stop_reason == op.STOP_SAME_MARKET


def test_overlap_and_ambiguity_fail_closed():
    overlapping = _iv("2023-06-01", "2024-06-28", market="KOSDAQ")
    with pytest.raises(op.PatternBHistoryError):
        op.history_chain("000001", ACTIVE, [overlapping, ACTIVE], DATES)
    a = _iv("2010-01-04", "2023-12-29", market="KOSDAQ")
    b = _iv("2015-01-02", "2023-12-29", market="KOSDAQ", isu="KR7000001002")
    with pytest.raises(op.PatternBHistoryError):
        op.history_chain("000001", ACTIVE, [a, b, ACTIVE], DATES)


def test_other_tickers_are_ignored():
    other = _iv("2010-01-04", "2023-12-29", market="KOSDAQ", ticker="000002")
    chain = op.history_chain("000001", ACTIVE, [other, ACTIVE], DATES)
    assert len(chain.segments) == 1 and chain.stop_reason == op.STOP_NONE


def _frame(start, end):
    idx = pd.bdate_range(start, end)
    close = np.linspace(100, 110, len(idx))
    f = pd.DataFrame({"high": close * 1.01, "low": close * 0.99, "close": close}, index=idx)
    f.attrs["data_authority"] = "MarketDataRepositoryV2"
    return f


def test_stitch_frames_concatenates_in_segment_ranges():
    a, b = op.HistorySegment("KOSDAQ", "X", "2020-01-02", "2023-12-29"), op.HistorySegment("KOSPI", "X", "2024-01-02", T)
    out = op.stitch_frames([(a, _frame("2020-01-02", "2023-12-29")), (b, _frame("2024-01-02", T))], T)
    assert out.index.is_unique and out.index.is_monotonic_increasing
    assert out.index.min() == pd.Timestamp("2020-01-02") and out.index.max() == pd.Timestamp(T)


def test_stitch_frames_fails_closed():
    a, b = op.HistorySegment("KOSDAQ", "X", "2020-01-02", "2023-12-29"), op.HistorySegment("KOSPI", "X", "2024-01-02", T)
    with pytest.raises(op.PatternBHistoryError, match="outside"):
        op.stitch_frames([(a, _frame("2020-01-02", "2024-01-05")), (b, _frame("2024-01-02", T))], T)
    with pytest.raises(op.PatternBHistoryError, match="outside"):
        op.stitch_frames([(a, _frame("2020-01-02", "2023-12-29")), (b, _frame("2024-01-02", "2026-09-25"))], T)
    foreign = _frame("2024-01-02", T)
    foreign.attrs = {}
    with pytest.raises(op.PatternBHistoryError, match="MarketDataRepositoryV2"):
        op.stitch_frames([(a, _frame("2020-01-02", "2023-12-29")), (b, foreign)], T)


def test_freshness_status():
    assert op.expected_weekly_bar("2026-09-21") == "2026-09-18"
    assert op.expected_weekly_bar("2026-09-18") == "2026-09-18"
    assert op.freshness_status("2026-09-18", T) == op.CURRENT
    assert op.freshness_status("2026-09-11", T) == op.STALE
    assert op.freshness_status(None, T) == op.STALE
    assert op.freshness_status("", T) == op.STALE
    assert op.CURRENT not in ("DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED")


def _row(ticker, status="READY", state="NORMAL", fresh="CURRENT", weekly="2026-09-18"):
    return {"ticker": ticker, "repository_status": "LOADED", "error": "", "evaluation_status": status,
            "pattern_b_state": state, "feature_contract_version": "V01",
            "state_rule_version": "PATTERN_B_STATE_RULE_V02", "freshness_status": fresh,
            "weekly_last_bar": weekly, "expected_weekly_bar": "2026-09-18", "_chain_valid": True}


def test_v02_invariants_pass_and_catch_freshness_errors():
    rows = [_row("1"), _row("2", fresh="STALE", weekly="2026-09-11"), _row("3", "UNAVAILABLE", None, "STALE", "")]
    assert audit.check_invariants_v02(rows, {"1", "2", "3"})["pass"]
    bad = [_row("1", fresh="STALE"), _row("2", fresh="CURRENT", weekly="2026-09-11"), _row("3", fresh="FRESH")]
    bad[0]["_chain_valid"] = False
    z = audit.check_invariants_v02(bad, {"1", "2", "3"})["zero_checks"]
    assert z["stale_with_expected_weekly_bar"] == 1 and z["current_with_other_weekly_bar"] == 1
    assert z["unknown_freshness_status"] == 1 and z["non_eligible_segment_stitch"] == 1
