"""Pattern B full-universe audit V01 — identity selection, invariants, replay sampling (fixtures only)."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/audit_pattern_b_full_universe_v01.py"
_spec = importlib.util.spec_from_file_location("audit_pattern_b_full_universe_v01", _SCRIPT)
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)

T = "2026-09-21"


def _iv(ticker, frm, to, market="KOSPI", isu=None, state="COMMON"):
    return {"ticker": ticker, "isu_cd": isu or f"KR7{ticker}0001", "market": market, "state": state,
            "effective_from": frm, "effective_to": to}


def _basic(ticker, market="KOSPI"):
    return {"ticker": ticker, "name": f"name{ticker}", "market": market}


def _row(ticker, status="READY", state="NORMAL", repo=audit.LOADED, error=""):
    return {"ticker": ticker, "repository_status": repo, "error": error, "evaluation_status": status,
            "pattern_b_state": state, "feature_contract_version": "V01",
            "state_rule_version": "PATTERN_B_STATE_RULE_V02"}


def test_exact_active_interval_is_selected():
    intervals = [_iv("000001", "2010-01-04", "2015-12-31", isu="KR7000001OLD"),
                 _iv("000001", "2016-01-04", T), _iv("000002", "2020-01-02", T, market="KOSDAQ")]
    resolved, problems = audit.resolve_identities(
        {"000001", "000002"}, [_basic("000001"), _basic("000002", "KOSDAQ")], intervals, T)
    assert not any(problems.values())
    assert resolved["000001"]["identity_effective_from"] == "2016-01-04"
    assert resolved["000001"]["isu_cd"] == "KR70000010001"
    assert resolved["000002"]["market"] == "KOSDAQ"


def test_overlapping_intervals_fail_closed():
    intervals = [_iv("000001", "2010-01-04", T), _iv("000001", "2020-01-02", T, isu="KR7000001NEW")]
    resolved, problems = audit.resolve_identities({"000001"}, [_basic("000001")], intervals, T)
    assert resolved == {} and problems["ambiguous_interval"] == ["000001"]


def test_missing_interval_fails_closed():
    intervals = [_iv("000001", "2010-01-04", "2026-09-18"), _iv("000001", "2020-01-02", T, state="DELISTED")]
    resolved, problems = audit.resolve_identities({"000001"}, [_basic("000001")], intervals, T)
    assert resolved == {} and problems["missing_interval"] == ["000001"]


def test_market_mismatch_and_missing_basic_info_fail_closed():
    intervals = [_iv("000001", "2010-01-04", T), _iv("000002", "2010-01-04", T)]
    resolved, problems = audit.resolve_identities(
        {"000001", "000002"}, [_basic("000001", "KOSDAQ")], intervals, T)
    assert resolved == {}
    assert problems["market_mismatch"] == ["000001"] and problems["missing_basic_info"] == ["000002"]


def test_non_target_markets_are_not_active():
    intervals = [_iv("000001", "2010-01-04", T, market="KONEX")]
    assert audit.active_intervals(intervals, T) == {}


def test_prior_same_isu_segment_is_flagged():
    intervals = [_iv("000001", "2010-01-04", "2018-05-31", market="KOSDAQ"), _iv("000001", "2018-06-01", T)]
    resolved, _ = audit.resolve_identities({"000001"}, [_basic("000001")], intervals, T)
    assert audit.prior_same_isu_segments(resolved, intervals) == {"000001"}


def test_expected_last_bars():
    assert audit.expected_last_bars("2026-09-21") == ("2026-08-31", "2026-09-18")
    assert audit.expected_last_bars("2026-09-30") == ("2026-09-30", "2026-09-25")
    assert audit.expected_last_bars("2026-09-25") == ("2026-08-31", "2026-09-25")


def test_invariants_pass_on_consistent_rows():
    rows = [_row("000001"), _row("000002", "UNAVAILABLE", None), _row("000003", state="DEEP_DEPRESSED")]
    result = audit.check_invariants(rows, {"000001", "000002", "000003"})
    assert result["pass"]
    assert all(v == 0 for v in result["zero_checks"].values())


def test_invariants_catch_coverage_and_state_violations():
    universe = {"000001", "000002", "000003", "000004"}
    rows = [_row("000001", state=None), _row("000002", "UNAVAILABLE", "NORMAL"),
            _row("000003", state="SIXTH"), _row("000003"), _row("000009"),
            _row("000004", status="", state=None, repo=audit.DATA_UNAVAILABLE)]
    z = audit.check_invariants(rows, universe)["zero_checks"]
    assert z["ready_null_state"] == 1 and z["unavailable_with_state"] == 1
    assert z["unknown_pattern_b_state"] == 1 and z["duplicate_ticker"] == 1
    assert z["extra_ticker"] == 1 and z["repository_data_unavailable"] == 1
    assert not audit.check_invariants(rows, universe)["pass"]


def test_invariants_catch_unprocessed_and_errors():
    rows = [_row("000001"), _row("000002", status="", state=None, error="PatternBFeatureInputError: x")]
    result = audit.check_invariants(rows, {"000001", "000002", "000003"})
    assert result["zero_checks"]["unprocessed_ticker"] == 1
    assert result["zero_checks"]["hard_error"] == 1
    assert not result["equalities"]["processed_equals_universe"]
    assert not result["pass"]


def test_replay_sample_is_deterministic_sha256_order():
    tickers = [f"{i:06d}" for i in range(100)]
    sample = audit.replay_sample(tickers)
    assert len(sample) == 20
    assert sample == audit.replay_sample(list(reversed(tickers)))
    assert sample == sorted(tickers, key=lambda t: hashlib.sha256(t.encode()).hexdigest())[:20]


def test_distribution_counts():
    rows = [_row("1"), _row("2", state="OVERHEATED"), _row("3", "UNAVAILABLE", None)]
    rows[2]["reason_codes"] = "36M_RANGE_POSITION:INSUFFICIENT_BARS"
    d = audit.distribution(rows)
    assert (d["ready"], d["unavailable"]) == (2, 1)
    assert d["states"]["NORMAL"] == 1 and d["states"]["OVERHEATED"] == 1
    assert sum(d["states"].values()) == d["ready"]
    assert d["unavailable_reason_codes"] == {"36M_RANGE_POSITION:INSUFFICIENT_BARS": 1}
