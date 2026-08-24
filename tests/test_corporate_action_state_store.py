from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from trend_scanner.data.corporate_action_detector import CorporateActionDetector, CorporateActionSnapshot
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.errors import MarketDataError


def _snapshot(as_of: str, listed_shares: int = 100, par_value: int | None = 5000):
    return CorporateActionSnapshot("005930", as_of, listed_shares, par_value)


def _dirty_store(tmp_path):
    store = CorporateActionStateStore(tmp_path / "state.sqlite3")
    detector = CorporateActionDetector()
    store.evaluate_and_record(_snapshot("2024-01-01"), detector)
    decision = store.evaluate_and_record(_snapshot("2024-01-02", 101), detector)
    return store, decision


def test_baseline_and_dirty_latch(tmp_path):
    store = CorporateActionStateStore(tmp_path / "state.sqlite3")
    detector = CorporateActionDetector()
    store.evaluate_and_record(_snapshot("2024-01-01"), detector)
    assert store.get("005930").status == "CLEAN"
    store.evaluate_and_record(_snapshot("2024-01-02", 101), detector)
    assert store.get("005930").status == "DIRTY"
    store.evaluate_and_record(_snapshot("2024-01-03", 101), detector)
    state = store.get("005930")
    assert state.status == "DIRTY"
    assert state.dirty_reason == "LISTED_SHARES_CHANGED"


def test_allowed_transitions_and_audit_log(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    assert store.get("005930").status == "REFRESHING"
    store.mark_clean("005930", "a" * 64)
    assert store.get("005930").status == "CLEAN"
    log = store.transition_log("005930")
    assert [(row["from_status"], row["to_status"]) for row in log] == [
        (None, "CLEAN"),
        ("CLEAN", "DIRTY"),
        ("DIRTY", "REFRESHING"),
        ("REFRESHING", "CLEAN"),
    ]


def test_illegal_transition_is_rejected(tmp_path):
    store, _ = _dirty_store(tmp_path)
    with pytest.raises(MarketDataError):
        store.transition("005930", "CLEAN")
    assert store.get("005930").status == "DIRTY"


def test_failed_state_can_retry_and_dirty_can_be_reasserted(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    store.mark_failed("005930", "PARTIAL_REFRESH_RESPONSE", "missing date")
    assert store.get("005930").status == "FAILED"
    store.evaluate_and_record(_snapshot("2024-01-03", 101), CorporateActionDetector())
    assert store.get("005930").status == "FAILED"
    assert store.claim_refresh("005930") is True
    assert store.get("005930").status == "REFRESHING"


def test_compare_and_set_claim_allows_one_worker(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = CorporateActionStateStore(path)
    second = CorporateActionStateStore(path)
    detector = CorporateActionDetector()
    first.evaluate_and_record(_snapshot("2024-01-01"), detector)
    first.evaluate_and_record(_snapshot("2024-01-02", 101), detector)
    assert first.claim_refresh("005930") is True
    assert second.claim_refresh("005930") is False
    assert second.get("005930").status == "REFRESHING"


def test_interrupted_refresh_recovery(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    old = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert store.recover_interrupted(stale_before=old) == 1
    state = store.get("005930")
    assert state.status == "FAILED"
    assert state.dirty_reason == "INTERRUPTED_REFRESH"
    assert store.transition_log("005930")[-1]["reason"] == "INTERRUPTED_REFRESH"


def test_recent_refreshing_is_not_recovered_when_threshold_excludes_it(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    old = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert store.recover_interrupted(stale_before=old) == 0
    assert store.get("005930").status == "REFRESHING"


def test_persisted_state_contains_required_and_snapshot_fields(tmp_path):
    store, _ = _dirty_store(tmp_path)
    state = store.get("005930")
    assert state is not None
    for field in (
        "ticker", "as_of", "status", "dirty_reason", "last_success_at", "last_attempt_at",
        "dirty_since", "last_error", "updated_at", "last_content_sha256",
        "refresh_requested_start", "refresh_requested_end", "listed_shares", "par_value",
    ):
        assert hasattr(state, field)


def test_unknown_persisted_status_fails_closed(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = CorporateActionStateStore(path)
    store.evaluate_and_record(_snapshot("2024-01-01"), CorporateActionDetector())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE corporate_action_state SET status='UNKNOWN' WHERE ticker='005930'")
        connection.commit()
    with pytest.raises(MarketDataError):
        store.get("005930")


def test_observation_during_refresh_is_rejected_without_state_mutation(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    before = store.get("005930")
    before_log_count = len(store.transition_log("005930"))
    with pytest.raises(MarketDataError, match="OBSERVATION_DURING_REFRESH"):
        store.evaluate_and_record(_snapshot("2024-01-03", 300), CorporateActionDetector())
    after = store.get("005930")
    assert after == before
    assert len(store.transition_log("005930")) == before_log_count


def test_rejected_refreshing_observation_can_be_replayed_after_clean_and_become_dirty(tmp_path):
    store, _ = _dirty_store(tmp_path)
    assert store.claim_refresh("005930") is True
    with pytest.raises(MarketDataError, match="OBSERVATION_DURING_REFRESH"):
        store.evaluate_and_record(_snapshot("2024-01-03", 300), CorporateActionDetector())
    store.mark_clean("005930", "a" * 64)
    decision = store.evaluate_and_record(_snapshot("2024-01-03", 300), CorporateActionDetector())
    assert decision.is_dirty is True
    assert store.get("005930").status == "DIRTY"
    assert store.get("005930").listed_shares == 300


def test_out_of_order_concurrent_observation_cannot_regress_state(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = CorporateActionStateStore(path)
    second = CorporateActionStateStore(path)
    detector = CorporateActionDetector()
    first.evaluate_and_record(_snapshot("2024-01-01", 100), detector)
    second.evaluate_and_record(_snapshot("2024-01-03", 300), detector)
    with pytest.raises(MarketDataError, match="OUT_OF_ORDER"):
        first.evaluate_and_record(_snapshot("2024-01-02", 200), detector)
    state = second.get("005930")
    assert state.as_of.isoformat() == "2024-01-03"
    assert state.listed_shares == 300


def test_evaluate_and_record_reads_current_persisted_snapshot_atomically(tmp_path):
    path = tmp_path / "state.sqlite3"
    worker_a = CorporateActionStateStore(path)
    worker_b = CorporateActionStateStore(path)
    detector = CorporateActionDetector()
    worker_a.evaluate_and_record(_snapshot("2024-01-01", 100), detector)
    worker_b.evaluate_and_record(_snapshot("2024-01-02", 200), detector)
    with pytest.raises(MarketDataError, match="OUT_OF_ORDER"):
        worker_a.evaluate_and_record(_snapshot("2024-01-01", 150), detector)
    assert worker_a.get("005930").listed_shares == 200


def test_stale_decision_cannot_overwrite_newer_state(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = CorporateActionStateStore(path)
    detector = CorporateActionDetector()
    store.evaluate_and_record(_snapshot("2024-01-01", 100), detector)
    stale_snapshot = _snapshot("2024-01-02", 200)
    stale_decision = detector.evaluate(_snapshot("2024-01-01", 100), stale_snapshot)
    store.evaluate_and_record(_snapshot("2024-01-03", 300), detector)
    with pytest.raises(MarketDataError, match="STALE_DECISION"):
        store.record_observation(stale_snapshot, stale_decision)
    assert store.get("005930").as_of.isoformat() == "2024-01-03"
    assert store.get("005930").listed_shares == 300
