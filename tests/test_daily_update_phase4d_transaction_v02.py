from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_daily_update_phase4d_v01 as phase4d


TARGET = "2026-10-13"


def _write_snapshot(root: Path, label: str) -> tuple[Path, Path]:
    web_data = root / "web/data"
    stocks = web_data / "stocks"
    stocks.mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        (web_data / name).write_text(json.dumps({"snapshot": label, "file": name}), encoding="utf-8")
    (web_data / "keep-existing.json").write_text(json.dumps({"snapshot": "preserve-me"}), encoding="utf-8")
    (stocks / f"{label}.json").write_text(json.dumps({"snapshot": label}), encoding="utf-8")
    status_path = phase4d._b_select_status_path(root, TARGET)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"snapshot": label, "strategy_id": phase4d.B_SELECT_ID}), encoding="utf-8")
    return web_data, status_path


def _write_stage(root: Path, label: str) -> Path:
    stage = root / "web/.phase4d-stage-test/data"
    stocks = stage / "stocks"
    stocks.mkdir(parents=True)
    for name in phase4d.REQUIRED_FILES:
        (stage / name).write_text(json.dumps({"snapshot": label, "file": name}), encoding="utf-8")
    (stocks / f"{label}.json").write_text(json.dumps({"snapshot": label}), encoding="utf-8")
    (stage / phase4d.B_SELECT_STATUS_STAGING_NAME).write_text(
        json.dumps({"snapshot": label, "strategy_id": phase4d.B_SELECT_ID}), encoding="utf-8",
    )
    return stage


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _status_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase4d_directory_snapshot_publish_and_readback_are_complete(tmp_path: Path):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")
    prior_data = _file_snapshot(web_data)
    prior_status = _status_hash(status_path)

    def validate(status_destination: Path):
        assert status_destination == status_path
        assert {path.name for path in (web_data / "stocks").glob("*.json")} == {"new.json"}
        assert json.loads((web_data / "stock-index.json").read_text()) == {
            "snapshot": "new", "file": "stock-index.json",
        }
        assert json.loads(status_destination.read_text())["snapshot"] == "new"
        return {"status": "PASS", "new_snapshot": True}

    result = phase4d.promote(stage, web_data, target_as_of=TARGET, post_publish_validate=validate)

    assert result["post_publish_readback"] == {"status": "PASS", "new_snapshot": True}
    assert result["publication"]["cross_path_atomicity"] is False
    assert "briefly absent" in result["publication"]["temporary_exposure"]
    assert _file_snapshot(web_data) != prior_data
    assert (web_data / "keep-existing.json").is_file()
    assert status_path.is_file() and _status_hash(status_path) != prior_status
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))


@pytest.mark.parametrize(
    "checkpoint",
    [
        "before_stocks_backup", "after_stocks_backup",
        "before_stocks_promote", "after_stocks_promote",
        *(f"before_json_replace:{name}" for name in phase4d.REQUIRED_FILES),
        *(f"after_json_replace:{name}" for name in phase4d.REQUIRED_FILES),
        "before_status_backup", "after_status_backup",
        "before_status_promote", "after_status_promote",
        "before_post_readback", "after_post_readback",
    ],
)
def test_phase4d_fault_injection_restores_full_old_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")
    old_data = _file_snapshot(web_data)
    old_status = _status_hash(status_path)

    def inject(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"injected:{checkpoint}")

    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", inject)
    with pytest.raises((RuntimeError, phase4d.Phase4DError)):
        phase4d.promote(
            stage,
            web_data,
            target_as_of=TARGET,
            post_publish_validate=lambda _status: {"status": "PASS"},
        )

    assert _file_snapshot(web_data) == old_data, checkpoint
    assert _status_hash(status_path) == old_status, checkpoint
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists(), checkpoint
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*")), checkpoint


def test_phase4d_readback_validation_failure_rolls_back_both_public_paths(tmp_path: Path):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")
    old_data = _file_snapshot(web_data)
    old_status = _status_hash(status_path)

    def reject_readback(_status: Path):
        raise ValueError("synthetic readback mismatch")

    with pytest.raises(phase4d.Phase4DError, match="ROLLED_BACK"):
        phase4d.promote(stage, web_data, target_as_of=TARGET, post_publish_validate=reject_readback)

    assert _file_snapshot(web_data) == old_data
    assert _status_hash(status_path) == old_status


def test_phase4d_identity_route_readback_failure_restores_old_routes_and_reports(tmp_path: Path):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")
    report_name = "000001--KR7000000001.json"
    (web_data / "identity-reports").mkdir()
    (web_data / "identity-reports" / report_name).write_text(
        json.dumps({"snapshot": "old"}), encoding="utf-8",
    )
    (web_data / "identity-report-routes.json").write_text(json.dumps({
        "items": [{"url": f"./data/identity-reports/{report_name}"}],
    }), encoding="utf-8")
    (stage / "identity-reports").mkdir()
    (stage / "identity-reports" / report_name).write_text(
        json.dumps({"snapshot": "new"}), encoding="utf-8",
    )
    (stage / "identity-report-routes.json").write_text(json.dumps({
        "items": [{"url": f"./data/identity-reports/{report_name}"}],
    }), encoding="utf-8")
    old_data = _file_snapshot(web_data)
    old_status = _status_hash(status_path)

    def reject_readback(_status: Path):
        assert json.loads((web_data / "identity-reports" / report_name).read_text()) == {"snapshot": "new"}
        raise ValueError("synthetic identity route readback mismatch")

    with pytest.raises(phase4d.Phase4DError, match="ROLLED_BACK"):
        phase4d.promote(stage, web_data, target_as_of=TARGET, post_publish_validate=reject_readback)

    assert _file_snapshot(web_data) == old_data
    assert _status_hash(status_path) == old_status
    assert json.loads((web_data / "identity-reports" / report_name).read_text()) == {"snapshot": "old"}


@pytest.mark.parametrize("crash_checkpoint", ["after_stocks_backup", "after_stocks_promote", "after_status_promote"])
def test_phase4d_interrupted_process_recovers_from_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_checkpoint: str,
):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")
    old_data = _file_snapshot(web_data)
    old_status = _status_hash(status_path)

    def crash(name: str) -> None:
        if name == crash_checkpoint:
            raise SystemExit(f"crash:{crash_checkpoint}")

    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", crash)
    with pytest.raises(SystemExit):
        phase4d.promote(stage, web_data, target_as_of=TARGET)

    assert (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).is_file()
    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", lambda _name: None)
    recovery = phase4d._recover_pending_promotion(web_data)

    assert recovery["status"] == "OLD_SNAPSHOT_RESTORED"
    assert _file_snapshot(web_data) == old_data
    assert _status_hash(status_path) == old_status
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))


def test_phase4d_unpublished_orphan_staging_is_cleaned_without_touching_live_snapshot(tmp_path: Path):
    web_data, status_path = _write_snapshot(tmp_path, "old")
    old_data = _file_snapshot(web_data)
    old_status = _status_hash(status_path)
    orphan = web_data.parent / ".phase4d-publish-txn-orphan"
    (orphan / "new-web-data").mkdir(parents=True)
    (orphan / "new-web-data" / "partial.json").write_text("unpublished", encoding="utf-8")

    recovery = phase4d._recover_pending_promotion(web_data)
    assert recovery["status"] == "UNPUBLISHED_STAGING_CLEANED"
    assert _file_snapshot(web_data) == old_data
    assert _status_hash(status_path) == old_status
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))


def test_phase4d_recovery_failure_preserves_backups_and_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    web_data, _status_path = _write_snapshot(tmp_path, "old")
    stage = _write_stage(tmp_path, "new")

    def crash(name: str) -> None:
        if name == "after_stocks_promote":
            raise SystemExit("simulated process stop")

    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", crash)
    with pytest.raises(SystemExit):
        phase4d.promote(stage, web_data, target_as_of=TARGET)
    monkeypatch.setattr(phase4d, "_phase4d_checkpoint", lambda _name: None)

    tx_dir = next(web_data.parent.glob(".phase4d-publish-txn-*"))
    (tx_dir / "previous-web-data" / "stock-index.json").write_text("corrupt", encoding="utf-8")
    with pytest.raises(phase4d.Phase4DError, match="BACKUPS_PRESERVED"):
        phase4d._recover_pending_promotion(web_data)
    assert tx_dir.exists()
    assert (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).is_file()
