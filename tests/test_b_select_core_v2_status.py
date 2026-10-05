from __future__ import annotations

import json

import pytest

from scripts import build_b_select_core_v2_status as status_v2
from scripts import export_strategy_monitor_web as strategy_monitor


def test_v1_production_snapshot_is_not_a_v2_baseline(tmp_path):
    source = tmp_path / "artifacts/strategies/b_select_core_v1/production/20261003/status.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "status": "PASS",
        "strategy_id": "PATTERN_B_SELECT_CORE_V01",
        "requested_as_of": "2026-10-03",
        "reference_market_date": "2026-10-02",
    }))

    assert status_v2._latest_prior_status(tmp_path, "2026-10-02", ["2026-10-02"]) is None


def test_fresh_history_replay_is_limited_to_the_approved_reference():
    with pytest.raises(status_v2.BSelectStatusError, match="CANONICAL_HISTORY_REBUILD_SCOPE_INVALID"):
        status_v2.build_b_select_status(
            repo_root="/missing/repository",
            target_as_of="2026-10-04",
            reference_market_date="2026-10-02",
            fresh_history_replay=True,
        )


def test_permanent_exclusions_block_new_entries():
    assert len(status_v2.PERMANENT_IDENTITY_EXCLUSIONS) == 181
    assert all(not status_v2._is_new_entry_allowed(*pair) for pair in status_v2.PERMANENT_IDENTITY_EXCLUSIONS)


def test_canonical_v2_exact_session_authority_needs_no_v1_source(tmp_path):
    status = {
        "strategy_id": status_v2.STRATEGY_ID,
        "requested_as_of": "2026-10-03",
        "reference_market_date": "2026-10-02",
        "catchup_audit": {
            "replay_mode": "V2_CANONICAL_FULL_HISTORY_REPLAY",
            "catchup_session_count": 0,
            "catchup_session_dates": [],
            "recovered_month_end_dates": ["2026-09-30"],
            "skipped_krx_session_count": 0,
        },
        "catchup_entry_pattern_a_authorities": [{
            "ticker": "064260",
            "isu_cd": "KR7064260003",
            "component_id": "064260:KR7064260003:000",
            "entry_signal_date": "2026-09-30",
            "entry_pattern_a_stage_recomputed": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
            "previous_pattern_a_stage_date": "2026-08-31",
            "source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS",
        }],
    }

    authority = strategy_monitor._read_catchup_entry_stage_authority(status, repo_root=tmp_path)
    key = ("064260", "KR7064260003", "064260:KR7064260003:000", "2026-09-30")

    assert set(authority) == {key}
    assert authority[key]["source"] == "REPOSITORY_V2_EXACT_SESSION_EVALUATORS"


def test_v1_entry_authority_is_rejected_for_canonical_v2():
    status = {
        "strategy_id": status_v2.STRATEGY_ID,
        "requested_as_of": "2026-10-03",
        "reference_market_date": "2026-10-02",
        "catchup_audit": {
            "replay_mode": "V2_CANONICAL_FULL_HISTORY_REPLAY",
            "catchup_session_count": 0,
            "catchup_session_dates": [],
            "recovered_month_end_dates": ["2026-09-30"],
            "skipped_krx_session_count": 0,
        },
        "catchup_entry_pattern_a_authorities": [{
            "ticker": "064260",
            "isu_cd": "KR7064260003",
            "component_id": "064260:KR7064260003:000",
            "entry_signal_date": "2026-09-30",
            "entry_pattern_a_stage_recomputed": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
            "previous_pattern_a_stage_date": "2026-08-31",
            "source": "V1_PROMOTION_BASELINE_STATUS",
        }],
    }

    with pytest.raises(ValueError, match="authority is inconsistent"):
        strategy_monitor._read_catchup_entry_stage_authority(status)


def test_strategy_monitor_v2_history_rejects_v1_source_rows():
    with pytest.raises(ValueError, match="unexpected PATTERN_B_SELECT_CORE_V02 history source strategy"):
        strategy_monitor._validate_history_identities(
            status_v2.STRATEGY_ID,
            [{"strategy_id": "PATTERN_B_SELECT_CORE_V01", "ticker": "064260", "trade_sequence": 1,
              "entry_execution_date": "2026-07-01"}],
            allowed_source_ids={status_v2.STRATEGY_ID},
        )
