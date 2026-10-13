from __future__ import annotations

import json

import pytest

from scripts import build_b_select_core_v2_status as status_v2
from scripts import export_strategy_monitor_web as strategy_monitor
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_source


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
    assert len(status_v2.PERMANENT_IDENTITY_EXCLUSIONS) == 185
    assert all(not status_v2._is_new_entry_allowed(*pair) for pair in status_v2.PERMANENT_IDENTITY_EXCLUSIONS)


def test_incremental_status_carries_forward_authority_for_still_open_exact_catchup_entry():
    key = ("064260", "KR7064260003", "064260:KR7064260003:000", "2026-09-30")
    row = {
        "ticker": key[0],
        "isu_cd": key[1],
        "component_id": key[2],
        "entry_signal_date": key[3],
        "entry_pattern_a_stage_recomputed": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
        "previous_pattern_a_stage_date": "2025-08-29",
        "source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS",
    }
    prior_item = {
        "ticker": key[0],
        "isu_cd": key[1],
        "component_id": key[2],
        "canonical_position": "OPEN",
        "action": "HOLD",
        "current_trade": {"entry_signal_date": key[3]},
        "pending_event": None,
        "entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "EARLY_TREND",
        "entry_previous_pattern_a_stage_date": "2025-08-29",
    }
    prior_status = {
        "catchup_audit": {
            "catchup_session_dates": [],
            "recovered_month_end_dates": [key[3]],
        },
        "catchup_entry_pattern_a_authorities": [row],
        "items": [prior_item],
    }

    authorities, inherited_keys = status_v2._carry_forward_active_entry_stage_authorities(
        prior_status,
        [dict(prior_item)],
        current_catchup_authority_keys=set(),
    )

    assert set(authorities) == {key}
    assert inherited_keys == [key]
    assert authorities[key] == row


def test_incremental_status_rejects_changed_context_for_inherited_open_entry_authority():
    key = ("064260", "KR7064260003", "064260:KR7064260003:000", "2026-09-30")
    row = {
        "ticker": key[0],
        "isu_cd": key[1],
        "component_id": key[2],
        "entry_signal_date": key[3],
        "entry_pattern_a_stage_recomputed": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
        "previous_pattern_a_stage_date": "2025-08-29",
        "source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS",
    }
    item = {
        "ticker": key[0],
        "isu_cd": key[1],
        "component_id": key[2],
        "canonical_position": "OPEN",
        "action": "HOLD",
        "current_trade": {"entry_signal_date": key[3]},
        "pending_event": None,
        "entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "TRANSITION",
        "entry_previous_pattern_a_stage_date": "2025-08-29",
    }
    prior_status = {
        "catchup_audit": {
            "catchup_session_dates": [],
            "recovered_month_end_dates": [key[3]],
        },
        "catchup_entry_pattern_a_authorities": [row],
        "items": [{**item, "entry_previous_pattern_a_stage": "EARLY_TREND"}],
    }

    with pytest.raises(status_v2.BSelectStatusError, match="PRIOR_ENTRY_PATTERN_A_CONTEXT_MISMATCH"):
        status_v2._carry_forward_active_entry_stage_authorities(
            prior_status,
            [item],
            current_catchup_authority_keys=set(),
        )


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


def _canonical_trade(
    *,
    status: str,
    ticker: str = "123456",
    isu_cd: str = "KR7123456000",
    exit_signal_date: str | None = None,
    exit_execution_date: str | None = None,
) -> dict:
    realized = status == "REALIZED"
    return {
        "ticker": ticker,
        "isu_cd": isu_cd,
        "trade_sequence": 1,
        "entry_signal_date": "2026-09-30",
        "entry_execution_date": "2026-10-01",
        "entry_open": 100.0,
        "exit_signal_date": exit_signal_date,
        "exit_execution_date": exit_execution_date,
        "exit_price": 110.0 if realized else None,
        "exit_reason": "PATTERN_B_NORMAL_NEXT_OPEN" if realized else None,
        "trade_status": status,
        "return_pct": 10.0 if realized else 3.0,
        "strategy_id": status_v2.STRATEGY_ID,
        "exit_strategy_id": status_v2.STRATEGY_ID if realized else None,
    }


def test_incremental_canonical_history_retains_hidden_realized_and_open_rows():
    realized = _canonical_trade(
        status="REALIZED", ticker="234567", isu_cd="KR7234567000",
        exit_signal_date="2026-10-01", exit_execution_date="2026-10-02",
    )
    open_row = _canonical_trade(status="OPEN_AT_REFERENCE")
    updated_open = {**open_row, "return_pct": 4.0}
    key = status_v2._canonical_trade_key(open_row)

    merged, transitioned = status_v2._merge_incremental_canonical_history(
        prior_rows=[realized, open_row],
        current_rows=[],
        hidden_open_updates={key: updated_open},
        current_identity_pairs={("654321", "KR7654321000")},
        prior_reference_market_date="2026-10-02",
        reference_market_date="2026-10-08",
        trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
    )

    assert len(merged) == 2
    merged_by_key = {status_v2._canonical_trade_key(row): row for row in merged}
    assert merged_by_key[status_v2._canonical_trade_key(realized)] == realized
    assert merged_by_key[key]["return_pct"] == 4.0
    assert merged_by_key[key]["trade_status"] == "OPEN_AT_REFERENCE"
    assert transitioned == 0


def test_incremental_canonical_history_accepts_only_exact_normal_next_open_transition():
    open_row = _canonical_trade(status="OPEN_AT_REFERENCE")
    realized = _canonical_trade(
        status="REALIZED",
        exit_signal_date="2026-10-06",
        exit_execution_date="2026-10-07",
    )
    key = status_v2._canonical_trade_key(open_row)

    merged, transitioned = status_v2._merge_incremental_canonical_history(
        prior_rows=[open_row],
        current_rows=[],
        hidden_open_updates={key: realized},
        current_identity_pairs={("654321", "KR7654321000")},
        prior_reference_market_date="2026-10-02",
        reference_market_date="2026-10-08",
        trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
    )

    assert merged == [realized]
    assert transitioned == 1


def test_incremental_canonical_history_fails_closed_when_hidden_open_has_no_update():
    open_row = _canonical_trade(status="OPEN_AT_REFERENCE")
    with pytest.raises(status_v2.BSelectStatusError, match="HIDDEN_OPEN_UPDATE_SET_MISMATCH"):
        status_v2._merge_incremental_canonical_history(
            prior_rows=[open_row],
            current_rows=[],
            hidden_open_updates={},
            current_identity_pairs={("654321", "KR7654321000")},
            prior_reference_market_date="2026-10-02",
            reference_market_date="2026-10-08",
            trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
        )


def test_incremental_canonical_history_rejects_duplicate_and_mismatched_identity_rows():
    open_row = _canonical_trade(status="OPEN_AT_REFERENCE")
    key = status_v2._canonical_trade_key(open_row)
    with pytest.raises(status_v2.BSelectStatusError, match="DUPLICATE_KEY"):
        status_v2._merge_incremental_canonical_history(
            prior_rows=[open_row, dict(open_row)],
            current_rows=[],
            hidden_open_updates={key: open_row},
            current_identity_pairs={("654321", "KR7654321000")},
            prior_reference_market_date="2026-10-02",
            reference_market_date="2026-10-08",
            trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
        )
    mismatched = {**open_row, "isu_cd": "KR7999999000"}
    with pytest.raises(status_v2.BSelectStatusError, match="HIDDEN_IDENTITY_MISMATCH"):
        status_v2._merge_incremental_canonical_history(
            prior_rows=[open_row],
            current_rows=[],
            hidden_open_updates={key: mismatched},
            current_identity_pairs={("654321", "KR7654321000")},
            prior_reference_market_date="2026-10-02",
            reference_market_date="2026-10-08",
            trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
        )


def test_incremental_canonical_history_persists_hidden_rows_across_following_update():
    realized = _canonical_trade(
        status="REALIZED", ticker="234567", isu_cd="KR7234567000",
        exit_signal_date="2026-10-01", exit_execution_date="2026-10-02",
    )
    open_row = _canonical_trade(status="OPEN_AT_REFERENCE")
    key = status_v2._canonical_trade_key(open_row)
    first, _ = status_v2._merge_incremental_canonical_history(
        prior_rows=[realized, open_row],
        current_rows=[],
        hidden_open_updates={key: open_row},
        current_identity_pairs={("654321", "KR7654321000")},
        prior_reference_market_date="2026-10-02",
        reference_market_date="2026-10-08",
        trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
    )
    open_from_first = next(row for row in first if row["trade_status"] == "OPEN_AT_REFERENCE")
    second, _ = status_v2._merge_incremental_canonical_history(
        prior_rows=first,
        current_rows=[],
        hidden_open_updates={key: open_from_first},
        current_identity_pairs={("654321", "KR7654321000")},
        prior_reference_market_date="2026-10-08",
        reference_market_date="2026-10-09",
        trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"],
    )

    assert second == first
    assert len(second) == 2


def test_incremental_canonical_history_keeps_064260_in_exact_public_identity_scope():
    open_row = _canonical_trade(
        status="OPEN_AT_REFERENCE", ticker="064260", isu_cd="KR7064260003"
    )
    current_row = {**open_row, "return_pct": 5.0}
    merged, transitioned = status_v2._merge_incremental_canonical_history(
        prior_rows=[open_row],
        current_rows=[current_row],
        hidden_open_updates={},
        current_identity_pairs={("064260", "KR7064260003")},
        prior_reference_market_date="2026-10-02",
        reference_market_date="2026-10-08",
        trading_dates=["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"],
    )
    assert merged == [current_row]
    assert transitioned == 0


def _hidden_open_replay_fixture():
    trade = _canonical_trade(status="OPEN_AT_REFERENCE")
    interval = {
        "ticker": trade["ticker"],
        "isu_cd": trade["isu_cd"],
        "state": "COMMON",
        "effective_from": "2020-01-01",
        "effective_to": "2026-10-08",
        "market": "KOSDAQ",
    }
    interval_key = pattern_b_source.interval_key(interval)
    return trade, interval, {interval_key: "123456:KR7123456000:000"}


def test_historical_only_open_replay_uses_exact_sessions_and_realizes_normal_next_open(monkeypatch):
    trade, interval, components = _hidden_open_replay_fixture()
    session_dates = ["2026-10-06", "2026-10-07", "2026-10-08"]
    monkeypatch.setattr(
        status_v2,
        "_build_exact_session_contexts",
        lambda **kwargs: [
            {"date": day, "pattern_b_state": "NORMAL" if day == "2026-10-06" else "DEPRESSED",
             "pattern_b_evaluation_status": "READY"}
            for day in kwargs["session_dates"]
        ],
    )
    monkeypatch.setattr(
        status_v2,
        "_first_valid_open_schedule",
        lambda **kwargs: ({"2026-10-07": 110.0}, {"2026-10-06": "2026-10-07"}),
    )

    updates, pending, audit = status_v2._replay_historical_only_open_positions(
        prior_status={"canonical_trade_history": [trade], "canonical_pending_events": []},
        current_identity_pairs={("654321", "KR7654321000")},
        intervals=[interval],
        interval_components=components,
        trading_dates=["2026-10-01", "2026-10-02", *session_dates],
        session_dates=session_dates,
        repository=object(),
        reference_market_date="2026-10-08",
        root=status_v2.ROOT,
    )

    key = status_v2._canonical_trade_key(trade)
    assert updates[key]["trade_status"] == "REALIZED"
    assert updates[key]["exit_signal_date"] == "2026-10-06"
    assert updates[key]["exit_execution_date"] == "2026-10-07"
    assert updates[key]["exit_price"] == 110.0
    assert pending == []
    assert audit[0]["observations"] == [
        {"date": "2026-10-06", "pattern_b_state": "NORMAL"},
        {"date": "2026-10-07", "pattern_b_state": "DEPRESSED"},
        {"date": "2026-10-08", "pattern_b_state": "DEPRESSED"},
    ]
    assert audit[0]["exit_signal_dates"] == ["2026-10-06"]


def test_historical_only_open_replay_keeps_open_when_no_normal_and_blocks_missing_states(monkeypatch):
    trade, interval, components = _hidden_open_replay_fixture()
    session_dates = ["2026-10-06", "2026-10-07", "2026-10-08"]

    class FakeLoader:
        def __init__(self, repository, *, start, end):
            self.end = end

        def load(self, ticker):
            return status_v2.pd.DataFrame(
                {"close": [105.0]}, index=[status_v2.pd.Timestamp(self.end)]
            )

    monkeypatch.setattr(status_v2, "RepositoryV2DailyLoader", FakeLoader)
    monkeypatch.setattr(
        status_v2,
        "_build_exact_session_contexts",
        lambda **kwargs: [
            {"date": day, "pattern_b_state": "DEPRESSED", "pattern_b_evaluation_status": "READY"}
            for day in kwargs["session_dates"]
        ],
    )
    updates, pending, audit = status_v2._replay_historical_only_open_positions(
        prior_status={"canonical_trade_history": [trade], "canonical_pending_events": []},
        current_identity_pairs={("654321", "KR7654321000")},
        intervals=[interval],
        interval_components=components,
        trading_dates=["2026-10-01", "2026-10-02", *session_dates],
        session_dates=session_dates,
        repository=object(),
        reference_market_date="2026-10-08",
        root=status_v2.ROOT,
    )
    key = status_v2._canonical_trade_key(trade)
    assert updates[key]["trade_status"] == "OPEN_AT_REFERENCE"
    assert updates[key]["return_pct"] == pytest.approx(5.0)
    assert pending == []
    assert audit[0]["exit_signal_dates"] == []

    monkeypatch.setattr(
        status_v2,
        "_build_exact_session_contexts",
        lambda **kwargs: [
            {"date": day, "pattern_b_state": None, "pattern_b_evaluation_status": "UNAVAILABLE"}
            for day in kwargs["session_dates"]
        ],
    )
    with pytest.raises(status_v2.BSelectStatusError, match="HIDDEN_PATTERN_B_UNAVAILABLE"):
        status_v2._replay_historical_only_open_positions(
            prior_status={"canonical_trade_history": [trade], "canonical_pending_events": []},
            current_identity_pairs={("654321", "KR7654321000")},
            intervals=[interval],
            interval_components=components,
            trading_dates=["2026-10-01", "2026-10-02", *session_dates],
            session_dates=session_dates,
            repository=object(),
            reference_market_date="2026-10-08",
            root=status_v2.ROOT,
        )
