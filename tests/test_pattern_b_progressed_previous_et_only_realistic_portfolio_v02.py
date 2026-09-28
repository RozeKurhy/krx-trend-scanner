from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as runner
from scripts import run_p2_1_realistic_portfolio_v01 as portfolio


def _valid_handoff_case() -> dict[str, object]:
    head = "a" * 40
    preflight = {
        "status": "PASS",
        "starting_head": head,
        "starting_origin_main": head,
        "starting_worktree_status": "",
        "official_criteria_sha256": "criteria-hash",
        "common_rules_sha256": "rules-hash",
        "permanent_exclusion_policy_sha256": "exclusion-hash",
        "permanent_exclusion_identity_count": 109,
        "workers": 10,
        "frozen_source_hashes_verified_by_window": {window_id: True for window_id in runner.WINDOW_IDS},
    }
    return {
        "preflight": preflight,
        "status_output": f"?? {runner.OUTPUT_ROOT.as_posix()}/preflight.json",
        "output_entries": ["preflight.json"],
        "current_head": head,
        "origin_main": head,
        "official_criteria_sha256": "criteria-hash",
        "common_rules_sha256": "rules-hash",
        "exclusion_policy_sha256": "exclusion-hash",
        "exclusion_identity_count": 109,
        "workers": 10,
    }


def test_preflight_handoff_accepts_only_current_pass_preflight() -> None:
    case = _valid_handoff_case()

    assert runner.validate_preflight_handoff(**case) == []


def test_preflight_handoff_rejects_extra_output_file() -> None:
    case = _valid_handoff_case()
    case["output_entries"] = ["preflight.json", "unexpected.csv"]

    assert "UNEXPECTED_PREFLIGHT_OUTPUT_CONTENTS" in runner.validate_preflight_handoff(**case)


def test_preflight_handoff_rejects_window_output_directory() -> None:
    case = _valid_handoff_case()
    case["output_entries"] = ["p1", "preflight.json"]

    assert "UNEXPECTED_PREFLIGHT_OUTPUT_CONTENTS" in runner.validate_preflight_handoff(**case)


def test_preflight_handoff_rejects_untracked_file_outside_output_root() -> None:
    case = _valid_handoff_case()
    case["status_output"] += "\n?? unrelated.csv"

    assert "WORKTREE_CHANGED_OUTSIDE_PREFLIGHT" in runner.validate_preflight_handoff(**case)


def test_preflight_handoff_rejects_tracked_modification() -> None:
    case = _valid_handoff_case()
    case["status_output"] += "\n M scripts/source.py"

    assert "WORKTREE_CHANGED_OUTSIDE_PREFLIGHT" in runner.validate_preflight_handoff(**case)


def test_preflight_handoff_rejects_head_change() -> None:
    case = _valid_handoff_case()
    case["current_head"] = "b" * 40

    errors = runner.validate_preflight_handoff(**case)
    assert "HEAD_DIFFERS_FROM_ORIGIN_MAIN" in errors
    assert "PREFLIGHT_HEAD_MISMATCH" in errors


def test_preflight_handoff_rejects_stale_provenance() -> None:
    case = _valid_handoff_case()
    preflight = case["preflight"]
    assert isinstance(preflight, dict)
    preflight["official_criteria_sha256"] = "stale"
    preflight["common_rules_sha256"] = "stale"
    preflight["permanent_exclusion_policy_sha256"] = "stale"
    preflight["permanent_exclusion_identity_count"] = 108
    preflight["workers"] = 9
    preflight["frozen_source_hashes_verified_by_window"]["P1"] = False

    errors = runner.validate_preflight_handoff(**case)
    assert "OFFICIAL_CRITERIA_SHA256_MISMATCH" in errors
    assert "COMMON_RULES_SHA256_MISMATCH" in errors
    assert "EXCLUSION_POLICY_SHA256_MISMATCH" in errors
    assert "EXCLUSION_IDENTITY_COUNT_MISMATCH" in errors
    assert "WORKER_COUNT_MISMATCH" in errors
    assert "FROZEN_SOURCE_HASH_VERIFICATION_FAILED" in errors


def test_observed_mdd_excludes_whole_unresolved_equity_days() -> None:
    rows = [
        {"date": "2024-01-02", "equity": 200_000_000.0},
        {"date": "2024-01-03", "equity": None},
        {"date": "2024-01-04", "equity": 100_000_000.0},
    ]

    result = runner.summarize_valuation(
        rows,
        [{"date": "2024-01-03", "skip_reason": "MISSING_EXACT_DAILY_MARK"}],
        {"effective_end": "2024-01-04"},
    )

    assert result["mdd_type"] == "OBSERVED_BELOW_90_COVERAGE"
    assert result["coverage_pct"] == 200.0 / 3.0
    assert result["mdd_pct"] == -50.0
    assert result["missing_days"] == 1
    assert result["unresolved_marks"] == 1
    assert result["missing_span_count"] == 1
    assert result["max_consecutive_missing_days"] == 1
    assert result["peak_date"] == "2024-01-02"
    assert result["trough_date"] == "2024-01-04"


def test_ninety_percent_coverage_is_observed_not_exact() -> None:
    rows = [
        {"date": f"2024-01-{day:02d}", "equity": None if day == 3 else 200_000_000.0}
        for day in range(1, 11)
    ]

    result = runner.summarize_valuation(rows, [], {"effective_end": "2024-01-10"})

    assert result["coverage_pct"] == 90.0
    assert result["mdd_type"] == "OBSERVED"


def test_relative_mdd_equal_to_five_percentage_points_fails() -> None:
    input_audit = {
        "source_hashes_verified": True,
        "frozen_source_hashes_verified": True,
        "exclusion_leakage_zero": True,
        "duplicate_input_key_count": 0,
        "post_cutoff_entry_count": 0,
        "lookahead_entry_count": 0,
        "identity_overlap_violation_count": 0,
        "repository_v2_silent_inner_drop_count": 0,
        "execution_price_audit": {"missing_exact_opens": 0, "price_mismatch_count": 0},
    }
    metrics = {
        "cash_conservation_pass": True,
        "position_cap": None,
        "cumulative_return_pct": 10.0,
        "CAGR_pct": 2.0,
        "final_equity": 220_000_000.0,
    }
    costs = {"mismatch_count": 0, "coverage_complete": True}

    gates, evidence = runner.gate_status(
        window_id="P2-1",
        metrics=metrics,
        valuation={"coverage_pct": 100.0, "mdd_pct": -40.0},
        v2_reference={"mdd_pct": -35.0},
        input_audit=input_audit,
        cost_audit=costs,
        unresolved_execution_event_count=0,
    )

    assert gates == {"A": "PASS", "B": "PASS", "C": "PASS", "D": "FAIL", "E": "PASS"}
    assert evidence["relative_mdd_deterioration_pp"] == 5.0


def _mdd_gates(candidate_mdd: float | None, v2_mdd: float | None) -> dict[str, str]:
    input_audit = {
        "source_hashes_verified": True,
        "frozen_source_hashes_verified": True,
        "exclusion_leakage_zero": True,
        "duplicate_input_key_count": 0,
        "post_cutoff_entry_count": 0,
        "lookahead_entry_count": 0,
        "identity_overlap_violation_count": 0,
        "repository_v2_silent_inner_drop_count": 0,
        "execution_price_audit": {"missing_exact_opens": 0, "price_mismatch_count": 0},
    }
    metrics = {
        "cash_conservation_pass": True,
        "position_cap": None,
        "cumulative_return_pct": 1.0,
        "CAGR_pct": 1.0,
        "final_equity": 202_000_000.0,
    }
    gates, _ = runner.gate_status(
        window_id="P2-1",
        metrics=metrics,
        valuation={"coverage_pct": 100.0, "mdd_pct": candidate_mdd},
        v2_reference={"mdd_pct": v2_mdd},
        input_audit=input_audit,
        cost_audit={"mismatch_count": 0, "coverage_complete": True},
        unresolved_execution_event_count=0,
    )
    return gates


def _relative_mdd_result(candidate_mdd: float | None, v2_mdd: float | None) -> dict[str, object]:
    gates = _mdd_gates(candidate_mdd, v2_mdd)
    return runner.compare_to_v2(
        "P2-1",
        {"mdd_pct": candidate_mdd},
        {},
        {},
        gates,
        {"mdd_pct": v2_mdd},
    )


def test_compare_to_v2_relative_mdd_fails_at_exact_five_point_limit() -> None:
    result = _relative_mdd_result(candidate_mdd=-40.0, v2_mdd=-35.0)

    assert result["mdd_deterioration_pp"] == 5.0
    assert result["relative_mdd_gate"] == "FAIL"


def test_compare_to_v2_reports_relative_failure_when_absolute_gate_also_fails() -> None:
    result = _relative_mdd_result(candidate_mdd=-40.5, v2_mdd=-33.0)

    assert result["mdd_deterioration_pp"] == 7.5
    assert result["relative_mdd_gate"] == "FAIL"
    assert _mdd_gates(candidate_mdd=-40.5, v2_mdd=-33.0)["D"] == "FAIL"


def test_compare_to_v2_relative_pass_is_independent_of_absolute_gate_failure() -> None:
    result = _relative_mdd_result(candidate_mdd=-40.5, v2_mdd=-38.5)

    assert result["mdd_deterioration_pp"] == 2.0
    assert result["relative_mdd_gate"] == "PASS"
    assert _mdd_gates(candidate_mdd=-40.5, v2_mdd=-38.5)["D"] == "FAIL"


def test_compare_to_v2_requires_both_mdds_for_relative_gate() -> None:
    for candidate_mdd, v2_mdd in [(None, -35.0), (-40.0, None)]:
        result = _relative_mdd_result(candidate_mdd, v2_mdd)

        assert result["relative_mdd_gate"] == "CHECK_REQUIRED"


def test_execution_date_uses_first_later_session_with_an_exact_open() -> None:
    dates = pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
    frame = pd.DataFrame(
        {"open": [100.0, None, 101.0, 102.0], "close": [100.0, None, 101.0, 102.0]},
        index=dates,
    )
    record = {
        "pair_id": "p1",
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "entry_signal_date": "2024-01-04",
        "entry_execution_date": "2024-01-08",
        "trade_status": "OPEN_AT_CUTOFF",
    }

    result = runner.verify_next_session_execution_dates(
        [record],
        {"000001": frame},
        [day.strftime("%Y-%m-%d") for day in dates],
        {
            "effective_end": "2024-01-08",
            "execution_support": "2024-01-09",
        },
    )

    assert result["status"] == "PASS"
    assert result["checked_entry_count"] == 1


def test_official_portfolio_replay_applies_zero_sell_tax() -> None:
    dates = pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-08"])
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0],
            "high": [100.0, 100.0, 110.0],
            "low": [100.0, 100.0, 110.0],
            "close": [100.0, 100.0, 110.0],
        },
        index=dates,
    )
    record = {
        "pair_id": "p1",
        "trade_id": "t1",
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "entry_signal_date": "2024-01-04",
        "entry_execution_date": "2024-01-05",
        "entry_market_cap": 1,
        "entry_price": 100.0,
        "exit_signal_date": "2024-01-05",
        "exit_execution_date": "2024-01-08",
        "exit_price": 110.0,
        "trade_status": "REALIZED",
    }
    prior_schedule = portfolio.SELL_TAX_SCHEDULE

    replay = runner.run_replay(
        [record],
        {"000001": frame},
        [day.strftime("%Y-%m-%d") for day in dates],
        {
            "effective_start": "2024-01-04",
            "effective_end": "2024-01-05",
            "execution_support": "2024-01-08",
        },
        "TEST_ZERO_TAX_V02",
    )

    exits = [event for event in replay["events"] if event["event_type"] == "EXIT"]
    assert len(exits) == 1
    assert exits[0]["event_status"] == "EXECUTED"
    assert exits[0]["sell_tax"] == 0.0
    assert replay["metrics"]["total_sell_tax_krw"] == 0.0
    assert replay["metrics"]["cash_conservation_pass"] is True
    assert portfolio.SELL_TAX_SCHEDULE == prior_schedule
