from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scripts import run_daily_update_phase4d_v01 as phase4d
from trend_scanner.validation import a_fast_alignment_publication_gate_v13 as gate


def _event_fixture():
    v06 = {
        "blocker_code": "REPLAY_STATE_UNAVAILABLE",
        "v05_blocker_in_scope": "true",
        "classification": "BASELINE_DATA_LIMITATION",
        "root_cause_type": "SAVED_EVIDENCE_FIXTURE",
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "event_date": "2026-10-08",
        "reference_market_date": "2026-10-08",
        "reason_code": "DATA_UNAVAILABLE",
        "allowed": "false",
        "entry_created": "false",
        "evidence_paths": '["data/saved-source.bin"]',
    }
    v07 = {key: value for key, value in v06.items() if key != "v05_blocker_in_scope"}
    key_payload = {field: v06[field] for field in gate.KEY_FIELDS}
    event = {
        "event_id": gate.sha256_bytes(gate.canonical_json(key_payload)),
        "event_key": key_payload,
        "eligibility_class": "VERIFIED_BASELINE_DATA_LIMITATION",
        "allowed": "false",
        "entry_created": "false",
        "v06_source_row_sha256": gate.sha256_bytes(gate.canonical_json(v06)),
        "v07_source_row_sha256": gate.sha256_bytes(gate.canonical_json(v07)),
        "source_evidence_paths": ["data/saved-source.bin"],
        "source_evidence_sha256": {"data/saved-source.bin": "a" * 64},
    }
    return [v06], [v07], [event], {"000001": "KR7000000001"}


def _reconcile(v06, v07, v12, identities):
    return gate.reconcile_blocker_events(
        v06,
        v07,
        v12,
        identities,
        expected_event_count=1,
        expected_code_counts={"REPLAY_STATE_UNAVAILABLE": 1},
    )


def test_one_saved_event_reconciles_without_v08_rows():
    result = _reconcile(*_event_fixture())
    assert result["event_count"] == 1
    assert result["v08_event_rows_used"] is False
    assert result["allowed_true_count"] == 0
    assert result["entry_created_true_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing_v07", "BLOCKER_V07_EVENT_COUNT_MISMATCH"),
        ("duplicate_v06", "BLOCKER_EVENT_DUPLICATE"),
        ("changed_reason", "BLOCKER_V06_V07_EVENT_SET_MISMATCH"),
        ("wrong_identity", "BLOCKER_CANDIDATE_IDENTITY_MISMATCH"),
        ("allowed_true", "BLOCKER_V06_ALLOWED_TRUE"),
        ("entry_created", "BLOCKER_V06_ENTRY_CREATED"),
        ("bad_v06_hash", "BLOCKER_V12_V06_ROW_HASH_MISMATCH"),
        ("v08_source", "BLOCKER_V08_EVIDENCE_USED"),
    ],
)
def test_event_reconciliation_fails_closed(mutation, error):
    v06, v07, v12, identities = _event_fixture()
    if mutation == "missing_v07":
        v07 = []
    elif mutation == "duplicate_v06":
        v06 = v06 + v06
    elif mutation == "changed_reason":
        v07[0]["reason_code"] = "DIFFERENT"
    elif mutation == "wrong_identity":
        identities["000001"] = "KR7000000002"
    elif mutation == "allowed_true":
        v06[0]["allowed"] = "true"
        v07[0]["allowed"] = "true"
        v12[0]["allowed"] = "true"
    elif mutation == "entry_created":
        v06[0]["entry_created"] = "true"
        v07[0]["entry_created"] = "true"
        v12[0]["entry_created"] = "true"
    elif mutation == "bad_v06_hash":
        v12[0]["v06_source_row_sha256"] = "0" * 64
    elif mutation == "v08_source":
        v06[0]["evidence_paths"] = '["artifacts/V08/event.json"]'
        v07[0]["evidence_paths"] = '["artifacts/V08/event.json"]'
        v12[0]["v06_source_row_sha256"] = gate.sha256_bytes(gate.canonical_json(v06[0]))
        v12[0]["v07_source_row_sha256"] = gate.sha256_bytes(gate.canonical_json(v07[0]))
        v12[0]["source_evidence_paths"] = ["artifacts/V08/event.json"]
        v12[0]["source_evidence_sha256"] = {"artifacts/V08/event.json": "b" * 64}

    with pytest.raises(gate.AlignmentEligibilityGateError, match=error):
        _reconcile(v06, v07, v12, identities)


def test_candidate_binding_pins_candidate_date_and_common_scope():
    binding = {
        "requested_as_of": gate.EXPECTED["requested_as_of"],
        "reference_market_date": gate.EXPECTED["reference_market_date"],
        "strategy_replay_digest": gate.EXPECTED["candidate_digest"],
        "common_ticker_count": gate.EXPECTED["common_count"],
        "v05_source_manifest_sha256": gate.EXPECTED_HASHES["v05_source_manifest"],
        "v05_stage_manifest_sha256": gate.EXPECTED_HASHES["v05_stage_manifest"],
    }
    assert gate.verify_candidate_binding(binding)["candidate_digest"] == gate.EXPECTED["candidate_digest"]
    for key, value, expected_error in (
        ("strategy_replay_digest", "another-candidate", "V12_CANDIDATE_DIGEST_MISMATCH"),
        ("requested_as_of", "2026-10-12", "V12_REQUESTED_AS_OF_MISMATCH"),
        ("common_ticker_count", 1458, "V12_COMMON_COUNT_MISMATCH"),
    ):
        changed = {**binding, key: value}
        with pytest.raises(gate.AlignmentEligibilityGateError, match=expected_error):
            gate.verify_candidate_binding(changed)


def test_pinned_evidence_and_stage_hashes_reject_missing_tampering_and_extra_files(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"ready":true}\n', encoding="utf-8")
    expected = gate.sha256_file(evidence)
    assert gate.verify_pinned_file(evidence, expected, "fixture") == expected
    with pytest.raises(gate.AlignmentEligibilityGateError, match="PINNED_FILE_SHA256_MISMATCH"):
        gate.verify_pinned_file(evidence, "0" * 64, "fixture")
    with pytest.raises(gate.AlignmentEligibilityGateError, match="PINNED_FILE_MISSING"):
        gate.verify_pinned_file(tmp_path / "missing.json", expected, "fixture")

    stage = tmp_path / "stage"
    stage.mkdir()
    payload = stage / "stock-index.json"
    payload.write_text('{"items":[]}\n', encoding="utf-8")
    declared = {"stock-index.json": gate.sha256_file(payload)}
    assert gate.verify_declared_stage_files(stage, declared, label="fixture")["matched_file_count"] == 1
    payload.write_text('{"items":[1]}\n', encoding="utf-8")
    with pytest.raises(gate.AlignmentEligibilityGateError, match="STAGE_FILE_SHA_MISMATCH"):
        gate.verify_declared_stage_files(stage, declared, label="fixture")
    payload.write_text('{"items":[]}\n', encoding="utf-8")
    (stage / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(gate.AlignmentEligibilityGateError, match="STAGE_FILE_SHA_MISMATCH"):
        gate.verify_declared_stage_files(stage, declared, label="fixture")


def test_old_publication_digest_is_not_a_noop_for_new_candidate():
    assert gate.candidate_noop_decision(
        gate.EXPECTED["candidate_digest"],
        gate.EXPECTED["current_public_digest"],
        published_payload_valid=True,
    ) == "VALIDATE_NEW_CANDIDATE"
    assert gate.candidate_noop_decision("same", "same", False) == "VALIDATE_NEW_CANDIDATE"
    assert gate.candidate_noop_decision("same", "same", True) == "NOOP_ALREADY_COMPLETE"


def test_alignment_stage_binding_is_narrow_and_rejects_an_unbound_candidate(tmp_path):
    designated = tmp_path / phase4d.V13_ALIGNMENT_STAGE_RELATIVE_PATH
    designated.mkdir(parents=True)
    monitor_path = designated / "strategy-monitor.json"
    monitor_path.write_text(json.dumps({
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": gate.EXPECTED["candidate_digest"],
        "requested_as_of": gate.EXPECTED["requested_as_of"],
        "reference_market_date": gate.EXPECTED["reference_market_date"],
    }), encoding="utf-8")
    assert phase4d._alignment_candidate_binding(designated, tmp_path)["candidate_digest"] == gate.EXPECTED["candidate_digest"]

    monitor = json.loads(monitor_path.read_text())
    monitor["strategy_replay_digest"] = "changed"
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")
    with pytest.raises(phase4d.Phase4DError, match="DIGEST_NOT_BOUND"):
        phase4d._alignment_candidate_binding(designated, tmp_path)

    monitor["strategy_replay_digest"] = gate.EXPECTED["candidate_digest"]
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")
    elsewhere = tmp_path / "unapproved" / "web"
    elsewhere.mkdir(parents=True)
    (elsewhere / "strategy-monitor.json").write_text(json.dumps(monitor), encoding="utf-8")
    with pytest.raises(phase4d.Phase4DError, match="STAGE_NOT_DESIGNATED"):
        phase4d._alignment_candidate_binding(elsewhere, tmp_path)

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "strategy-monitor.json").write_text(json.dumps({
        "strategy_replay_mode": "DAILY",
        "strategy_replay_digest": "legacy",
        "strategies": [{"id": "PATTERN_A_FAST_FINAL_STRATEGY_V02"}],
    }), encoding="utf-8")
    assert phase4d._alignment_candidate_binding(legacy, tmp_path) is None


def test_snapshot_mutation_is_detected_before_promotion(tmp_path):
    stage = tmp_path / "stage"
    snapshot = tmp_path / "snapshot"
    (stage / "stocks").mkdir(parents=True)
    (snapshot / "stocks").mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        (stage / name).write_text("{}\n", encoding="utf-8")
        (snapshot / name).write_text("{}\n", encoding="utf-8")
    (stage / "stocks/000001.json").write_text('{"ticker":"000001"}\n', encoding="utf-8")
    (snapshot / "stocks/000001.json").write_text('{"ticker":"000001"}\n', encoding="utf-8")
    phase4d._assert_alignment_snapshot_matches_stage(stage, snapshot)
    (snapshot / "stocks/000001.json").write_text('{"ticker":"changed"}\n', encoding="utf-8")
    with pytest.raises(phase4d.Phase4DError, match="SNAPSHOT_STOCKS_MISMATCH"):
        phase4d._assert_alignment_snapshot_matches_stage(stage, snapshot)


def test_alignment_promotion_gate_fails_before_recovery_or_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    stage_data = tmp_path / phase4d.V13_ALIGNMENT_STAGE_RELATIVE_PATH
    (stage_data / "stocks").mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        (stage_data / name).write_text("{}\n", encoding="utf-8")
    (stage_data / "strategy-monitor.json").write_text(json.dumps({
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": gate.EXPECTED["candidate_digest"],
        "requested_as_of": gate.EXPECTED["requested_as_of"],
        "reference_market_date": gate.EXPECTED["reference_market_date"],
    }), encoding="utf-8")
    (stage_data.parent / phase4d.B_SELECT_STATUS_STAGING_NAME).write_text("{}\n", encoding="utf-8")
    web_data = tmp_path / "web/data"
    web_data.mkdir(parents=True)
    sentinel = web_data / "keep.json"
    sentinel.write_text('{"old":true}\n', encoding="utf-8")

    def reject_gate(*_args, **_kwargs):
        raise gate.AlignmentEligibilityGateError("FIXTURE_EVIDENCE_TAMPERED")

    def recovery_must_not_run(*_args, **_kwargs):
        pytest.fail("recovery ran before the Alignment eligibility gate")

    monkeypatch.setattr(gate, "validate_alignment_candidate_evidence", reject_gate)
    monkeypatch.setattr(phase4d, "_recover_pending_promotion", recovery_must_not_run)
    with pytest.raises(phase4d.Phase4DError, match="ELIGIBILITY_GATE_FAILED"):
        phase4d.promote(stage_data, web_data, target_as_of=gate.EXPECTED["requested_as_of"])

    assert sentinel.read_text(encoding="utf-8") == '{"old":true}\n'
    assert not phase4d._b_select_status_path(tmp_path, gate.EXPECTED["requested_as_of"]).exists()
    assert not (tmp_path / "web" / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()


def test_saved_candidate_dryrun_uses_phase4d_and_never_promotes():
    result = gate.preflight_alignment_candidate(ROOT)
    assert result["status"] == "V13_LOCAL_DRYRUN_READY_FOR_EXPLICIT_PUBLISH_APPROVAL_REVIEW"
    assert result["promotion_called"] is False
    assert result["canonical_web_data_writes"] == 0
    assert result["b_select_status_writes"] == 0
    assert result["phase4d_validate_staging"]["common_stock_report_count"] == 1459
    assert result["phase4d_validate_staging"]["etf_stock_report_count"] == 36
    assert result["phase4d_final_snapshot"]["route_integrity"]["route_count"] == 399
    assert result["candidate_eligibility"]["independent_blocker_reconciliation"]["event_count"] == 204


def test_pages_repository_guard_runs_before_configure_upload_and_deploy():
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    guard = workflow.index("Guard production Repository V2 entrypoints")
    configure = workflow.index("Configure Pages")
    upload = workflow.index("Upload Pages artifact")
    deploy = workflow.index("Deploy to GitHub Pages")
    assert guard < configure < upload < deploy
    assert "python -m pytest -q tests/test_production_repository_factory_guard_v01.py" in workflow[guard:configure]
