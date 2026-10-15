from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import run_daily_update_phase4d_v01 as phase4d
from scripts import run_daily_update_phase4e_v01 as phase4e
from trend_scanner.validation import a_fast_alignment_publication_gate_v13 as v13_gate


TARGET = "2026-10-11"
REFERENCE = "2026-10-08"
CANDIDATE = phase4d.V13_ALIGNMENT_CANDIDATE_DIGEST
CURRENT_PUBLIC = "e3c6ecc19187eb8951c1c9ef1626a2b54a9cffe1f6d415721b75a0cca8e89b61"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_monitor(*, digest: str | None = CANDIDATE, valid_scope: bool = True) -> dict:
    scope = {
        "type": "PUBLISHED_COMMON_REPORTS",
        "report_count": 1459 if valid_scope else 1458,
        "requested_as_of": TARGET,
        "reference_market_date": REFERENCE,
        "output_strategy_id": phase4d.PROMOTED_STRATEGY_ID,
    }
    row = {
        "id": phase4d.PROMOTED_STRATEGY_ID,
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
    }
    return {
        "requested_as_of": TARGET,
        "reference_market_date": REFERENCE,
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
        "strategies": [row],
    }


def _write_candidate_stage(
    root: Path,
    *,
    monitor_marker: bool = True,
    digest: str | None = CANDIDATE,
    valid_scope: bool = True,
    stage_data_relative_path: Path | None = None,
) -> tuple[Path, Path]:
    stage_data = root / (stage_data_relative_path or phase4d.V13_ALIGNMENT_STAGE_RELATIVE_PATH)
    (stage_data / "stocks").mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        payload = {"requested_as_of": TARGET, "reference_market_date": REFERENCE, "name": name}
        if name == "strategy-monitor.json" and monitor_marker:
            payload = _write_monitor(digest=digest, valid_scope=valid_scope)
        (stage_data / name).write_text(json.dumps(payload), encoding="utf-8")
    (stage_data / "stocks/000001.json").write_text('{"ticker":"000001"}', encoding="utf-8")
    status_path = stage_data.parent / phase4d.B_SELECT_STATUS_STAGING_NAME
    status_path.write_text('{"status":"PASS","snapshot":"candidate"}', encoding="utf-8")
    return stage_data, status_path


def _write_public_snapshot(root: Path, *, monitor_digest: str = CURRENT_PUBLIC) -> tuple[Path, Path]:
    web_data = root / "web/data"
    (web_data / "stocks").mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        payload = {"snapshot": "old", "file": name}
        if name == "strategy-monitor.json":
            payload = {"strategy_replay_digest": monitor_digest}
        (web_data / name).write_text(json.dumps(payload), encoding="utf-8")
    (web_data / "keep-existing.json").write_text('{"keep":true}', encoding="utf-8")
    (web_data / "stocks/old.json").write_text('{"snapshot":"old"}', encoding="utf-8")
    status_path = phase4d._b_select_status_path(root, TARGET)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text('{"status":"PASS","snapshot":"old"}', encoding="utf-8")
    return web_data, status_path


def _web_snapshot(web_data: Path) -> dict[str, str]:
    return {
        path.relative_to(web_data).as_posix(): _sha(path)
        for path in sorted(web_data.rglob("*")) if path.is_file()
    }


def _install_test_gate(monkeypatch: pytest.MonkeyPatch, *, reject: str | None = None) -> list[Path]:
    calls: list[Path] = []

    def validate_evidence(root: Path, stage_root: Path) -> dict:
        calls.append(stage_root)
        monitor_path = stage_root / "web/strategy-monitor.json"
        monitor = json.loads(monitor_path.read_text()) if monitor_path.is_file() else {}
        scope = monitor.get("strategy_replay_scope") or {}
        if reject == "EVIDENCE_MISSING":
            raise v13_gate.AlignmentEligibilityGateError("V12_EVIDENCE_MISSING")
        if not monitor_path.is_file() or monitor.get("strategy_replay_mode") != "FULL_HISTORY_ALIGNMENT_WEB":
            raise v13_gate.AlignmentEligibilityGateError("CANDIDATE_MONITOR_REPLAY_MODE_MISMATCH")
        if monitor.get("strategy_replay_digest") != CANDIDATE:
            raise v13_gate.AlignmentEligibilityGateError("CANDIDATE_MONITOR_DIGEST_MISMATCH")
        if reject == "DATE_MISMATCH" or monitor.get("requested_as_of") != TARGET:
            raise v13_gate.AlignmentEligibilityGateError("CANDIDATE_MONITOR_TARGET_DATE_MISMATCH")
        if reject == "SCOPE_MISMATCH" or scope.get("report_count") != 1459:
            raise v13_gate.AlignmentEligibilityGateError("CANDIDATE_COMMON_SCOPE_COUNT_MISMATCH")
        status_path = stage_root / phase4d.B_SELECT_STATUS_STAGING_NAME
        if not status_path.is_file():
            raise v13_gate.AlignmentEligibilityGateError("V09_B_SELECT_STATUS_HASH_MISSING")
        return {
            "candidate_binding": {"candidate_digest": CANDIDATE},
            "stage_fingerprint_sha256": "a" * 64,
            "b_select_status_sha256": _sha(status_path),
        }

    monkeypatch.setattr(v13_gate, "validate_alignment_candidate_evidence", validate_evidence)
    monkeypatch.setattr(phase4d, "validate_staging", lambda *args, **kwargs: {"status": "PASS"})
    return calls


def test_a1_designated_stage_without_monitor_markers_fails_direct_promote_before_public_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    stage_data, _ = _write_candidate_stage(
        tmp_path,
        monitor_marker=False,
        stage_data_relative_path=v13_gate.V05_STAGE_REL / "web",
    )
    web_data, status_destination = _write_public_snapshot(tmp_path)
    old_web = _web_snapshot(web_data)
    old_status = _sha(status_destination)
    calls = _install_test_gate(monkeypatch)

    with pytest.raises(phase4d.Phase4DError, match="ELIGIBILITY_GATE_FAILED"):
        phase4d.promote(stage_data, web_data, target_as_of=TARGET)

    assert len(calls) == 1
    assert _web_snapshot(web_data) == old_web
    assert _sha(status_destination) == old_status
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))


@pytest.mark.parametrize(
    ("gate_reject", "monitor_digest", "valid_scope", "target", "message"),
    [
        ("EVIDENCE_MISSING", CANDIDATE, True, TARGET, "ELIGIBILITY_GATE_FAILED"),
        (None, "f" * 64, True, TARGET, "DIGEST_NOT_BOUND"),
        ("SCOPE_MISMATCH", CANDIDATE, False, TARGET, "ELIGIBILITY_GATE_FAILED"),
        (None, CANDIDATE, True, "2026-10-10", "TARGET_DATE_MISMATCH"),
    ],
)
def test_a2_evidence_digest_scope_and_date_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_reject: str | None,
    monitor_digest: str,
    valid_scope: bool,
    target: str,
    message: str,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    stage_data, _ = _write_candidate_stage(
        tmp_path,
        digest=monitor_digest,
        valid_scope=valid_scope,
    )
    web_data, status_destination = _write_public_snapshot(tmp_path)
    old_web = _web_snapshot(web_data)
    old_status = _sha(status_destination)
    calls = _install_test_gate(monkeypatch, reject=gate_reject)

    with pytest.raises(phase4d.Phase4DError, match=message):
        phase4d.promote(
            stage_data,
            web_data,
            target_as_of=target,
            alignment_candidate_digest=CANDIDATE,
        )

    assert _web_snapshot(web_data) == old_web
    assert _sha(status_destination) == old_status
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))
    if gate_reject is not None or (monitor_digest == CANDIDATE and valid_scope):
        assert calls


def test_a2_spoofed_stage_path_is_not_trusted_without_designated_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    designated, _ = _write_candidate_stage(tmp_path)
    spoof = tmp_path / "artifacts/staging/spoofed/web"
    shutil.copytree(designated, spoof)
    web_data, status_destination = _write_public_snapshot(tmp_path)
    old_web = _web_snapshot(web_data)
    old_status = _sha(status_destination)

    with pytest.raises(
        phase4d.Phase4DError,
        match="ELIGIBILITY_GATE_FAILED:ALIGNMENT_STAGE_PATH_NOT_DESIGNATED",
    ):
        phase4d.promote(spoof, web_data, target_as_of=TARGET)

    assert _web_snapshot(web_data) == old_web
    assert _sha(status_destination) == old_status


def test_a3_phase4d_validates_candidate_and_snapshot_without_promoting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    _write_candidate_stage(tmp_path)
    web_data, _ = _write_public_snapshot(tmp_path)
    (web_data / "strategy-monitor.json").write_text(
        json.dumps({"strategy_replay_digest": CURRENT_PUBLIC}), encoding="utf-8",
    )
    monkeypatch.setattr(
        phase4d,
        "inspect_published_payload",
        lambda *args, **kwargs: {"reference_market_date": REFERENCE, "validation": {"status": "PASS"}},
    )
    calls = _install_test_gate(monkeypatch)
    monkeypatch.setattr(
        phase4d,
        "_inspect_final_promotion_snapshot",
        lambda *args, **kwargs: {"status": "PASS", "protected_file_count": 151, "route_count": 399},
    )
    monkeypatch.setattr(phase4d, "promote", lambda *args, **kwargs: pytest.fail("promotion must remain off"))

    result = phase4d.run_phase4d(
        TARGET,
        execute_live=False,
        root=tmp_path,
        alignment_candidate_digest=CANDIDATE,
    )

    assert result["status"] == "PASS"
    assert result["candidate_eligibility"]["status"] == "PASS"
    assert result["promote_snapshot_validation"]["status"] == "PASS"
    assert result["publication"] is None
    assert result["web_data_writes"] == 0
    assert result["b_select_status_writes"] == 0
    assert result["promotion_called"] is False
    assert len(calls) == 1


def test_b1_phase4e_does_not_noop_old_public_digest_and_routes_explicit_candidate_to_phase4d(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    _write_candidate_stage(tmp_path)
    web_data, _ = _write_public_snapshot(tmp_path)
    (web_data / "strategy-monitor.json").write_text(
        json.dumps({"strategy_replay_digest": CURRENT_PUBLIC}), encoding="utf-8",
    )
    monkeypatch.setattr(
        phase4d,
        "inspect_published_payload",
        lambda *args, **kwargs: {"reference_market_date": REFERENCE, "validation": {"status": "PASS"}},
    )
    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: pytest.fail("candidate mode must skip 4A"))
    monkeypatch.setattr(phase4e, "run_phase4b", lambda *args, **kwargs: pytest.fail("candidate mode must skip 4B"))
    monkeypatch.setattr(phase4e, "run_phase4c", lambda *args, **kwargs: pytest.fail("candidate mode must skip 4C"))
    monkeypatch.setattr(phase4e, "run_etf_stock_reports", lambda *args, **kwargs: pytest.fail("candidate mode must skip ETF regeneration"))
    captured: dict[str, object] = {}

    def phase4d_candidate(target_as_of: str, **kwargs: object) -> dict[str, str]:
        captured.update(target_as_of=target_as_of, **kwargs)
        return {"status": "PASS"}

    monkeypatch.setattr(phase4e, "run_phase4d", phase4d_candidate)
    result = phase4e.run_phase4e(
        TARGET,
        root=tmp_path,
        execute_live=False,
        alignment_candidate_digest=CANDIDATE,
    )

    assert result["overall_status"] == "PASS"
    assert result["phases"]["4D"]["status"] == "PASS"
    assert captured["alignment_candidate_digest"] == CANDIDATE
    assert result["etf_stock_reports"]["status"] == "NOT_RUN_SAVED_ALIGNMENT_CANDIDATE"


def test_b2_candidate_noop_requires_matching_valid_public_digest_date_and_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    _write_candidate_stage(tmp_path)
    web_data, _ = _write_public_snapshot(tmp_path)
    (web_data / "strategy-monitor.json").write_text(
        json.dumps(_write_monitor()), encoding="utf-8",
    )
    monkeypatch.setattr(
        phase4d,
        "inspect_published_payload",
        lambda *args, **kwargs: {"reference_market_date": REFERENCE, "validation": {"status": "PASS"}},
    )
    monkeypatch.setattr(phase4d, "_validate_v13_alignment_stage", lambda *args, **kwargs: pytest.fail("NOOP should not revalidate stage"))

    result = phase4d.run_phase4d(
        TARGET,
        execute_live=False,
        root=tmp_path,
        alignment_candidate_digest=CANDIDATE,
    )
    e_result = phase4e._phase4d_noop_precheck(
        TARGET,
        root=tmp_path,
        alignment_candidate_digest=CANDIDATE,
    )

    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["web_data_writes"] == 0
    assert e_result is not None and e_result["status"] == "NOOP_ALREADY_COMPLETE"


def test_b3_daily_noop_contract_is_unchanged_without_candidate_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    published = {"reference_market_date": REFERENCE, "validation": {"status": "PASS"}}
    monkeypatch.setattr(phase4d, "inspect_published_payload", lambda *args, **kwargs: published)
    monkeypatch.setattr(phase4e, "_published_monitor_matches_canonical_fast_replay", lambda *args, **kwargs: True)

    result = phase4e._phase4d_noop_precheck(TARGET, root=tmp_path)

    assert result is not None
    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["reason"] == "VALID_EXACT_TARGET_WEB_PAYLOAD"


@pytest.mark.parametrize("change", ["mutate", "delete", "replace"])
def test_c1_c2_status_change_after_final_gate_fails_before_public_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    stage_data, status_source = _write_candidate_stage(tmp_path)
    web_data, status_destination = _write_public_snapshot(tmp_path)
    old_web = _web_snapshot(web_data)
    old_status = _sha(status_destination)
    _install_test_gate(monkeypatch)
    replace_destinations: list[Path] = []
    real_replace = phase4d.os.replace

    def track_replace(source: str | Path, destination: str | Path) -> None:
        replace_destinations.append(Path(destination))
        real_replace(source, destination)

    monkeypatch.setattr(phase4d.os, "replace", track_replace)

    def change_after_gate(name: str) -> None:
        if name == "after_alignment_final_gate":
            if change == "mutate":
                status_source.write_text('{"status":"TAMPERED"}', encoding="utf-8")
            elif change == "delete":
                status_source.unlink()
            else:
                replacement = status_source.with_name("b-select-status.replacement.json")
                replacement.write_text('{"status":"REPLACED"}', encoding="utf-8")
                real_replace(replacement, status_source)

    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", change_after_gate)
    with pytest.raises(phase4d.Phase4DError, match="STATUS_STAGE_COPY_HASH_MISMATCH|PROMOTION_FAILED_ROLLED_BACK"):
        phase4d.promote(
            stage_data,
            web_data,
            target_as_of=TARGET,
            alignment_candidate_digest=CANDIDATE,
        )

    assert _web_snapshot(web_data) == old_web
    assert _sha(status_destination) == old_status
    assert web_data not in replace_destinations
    assert status_destination not in replace_destinations
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))


def test_c3_matching_status_sha_promotes_only_inside_temporary_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    stage_data, status_source = _write_candidate_stage(tmp_path)
    web_data, status_destination = _write_public_snapshot(tmp_path)
    _install_test_gate(monkeypatch)

    result = phase4d.promote(
        stage_data,
        web_data,
        target_as_of=TARGET,
        alignment_candidate_digest=CANDIDATE,
        post_publish_validate=lambda _path: {"status": "PASS"},
    )

    assert result["publication"]["status"] == "COMMITTED_AND_READ_BACK"
    assert _sha(status_destination) == _sha(status_source)
    assert (web_data / "stocks/000001.json").is_file()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))
