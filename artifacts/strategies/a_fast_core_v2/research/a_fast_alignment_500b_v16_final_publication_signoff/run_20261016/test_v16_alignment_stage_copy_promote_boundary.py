from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import run_daily_update_phase4d_v01 as phase4d
from trend_scanner.validation import a_fast_alignment_publication_gate_v13 as v13_gate


TARGET = "2026-10-11"
RUN_OUTPUT = Path(__file__).parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path, *, exclude: set[str] | None = None) -> dict[str, str]:
    excluded = exclude or set()
    return {
        path.relative_to(root).as_posix(): _sha(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    }


def test_direct_promote_runs_v12_gate_for_copied_alignment_stage_without_cli_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_stage_root = phase4d.ROOT / v13_gate.V09_STAGE_REL
    source_web = source_stage_root / "web"
    source_monitor = source_web / "strategy-monitor.json"
    source_monitor_sha = _sha(source_monitor)
    original_payload_hashes = _tree(source_stage_root, exclude={"web/strategy-monitor.json"})

    copied_stage_root = tmp_path / "copied-alignment-stage"
    shutil.copytree(source_stage_root, copied_stage_root)
    stage_data = copied_stage_root / "web"
    monitor_path = stage_data / "strategy-monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    monitor.pop("strategy_replay_digest", None)
    alignment_rows = [
        row for row in monitor.get("strategies", [])
        if isinstance(row, dict) and row.get("id") == phase4d.PROMOTED_STRATEGY_ID
    ]
    assert len(alignment_rows) == 1
    alignment_rows[0].pop("strategy_replay_digest", None)
    monitor_path.write_text(json.dumps(monitor, ensure_ascii=False), encoding="utf-8")

    assert monitor.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
    assert monitor.get("default_strategy_id") == phase4d.PROMOTED_STRATEGY_ID
    assert alignment_rows[0].get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
    assert alignment_rows[0].get("strategy_replay_scope") == monitor.get("strategy_replay_scope")
    assert "strategy_replay_digest" not in monitor
    assert "strategy_replay_digest" not in alignment_rows[0]
    assert _tree(copied_stage_root, exclude={"web/strategy-monitor.json"}) == original_payload_hashes
    copied_file_count = sum(1 for path in copied_stage_root.rglob("*") if path.is_file())
    assert copied_file_count == 1502

    web_data = tmp_path / "web/data"
    web_data.mkdir(parents=True)
    (web_data / "sentinel.json").write_text('{"old":"web"}', encoding="utf-8")
    status_destination = phase4d._b_select_status_path(tmp_path, TARGET)
    status_destination.parent.mkdir(parents=True, exist_ok=True)
    status_destination.write_text('{"old":"status"}', encoding="utf-8")
    before_web = _tree(web_data)
    before_status_sha = _sha(status_destination)

    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    gate_calls: list[dict[str, str]] = []
    real_gate = v13_gate.validate_alignment_candidate_evidence

    def track_gate(root: Path, stage_root: Path, **kwargs: object) -> dict:
        gate_calls.append({"root": str(root), "stage_root": str(stage_root)})
        return real_gate(root, stage_root, **kwargs)

    monkeypatch.setattr(v13_gate, "validate_alignment_candidate_evidence", track_gate)

    with pytest.raises(
        phase4d.Phase4DError,
        match="PHASE4D_ALIGNMENT_ELIGIBILITY_GATE_FAILED:ALIGNMENT_STAGE_PATH_NOT_DESIGNATED",
    ) as captured:
        # No alignment_candidate_digest argument: candidate discovery must come from content.
        phase4d.promote(stage_data, web_data, target_as_of=TARGET)

    assert len(gate_calls) == 1
    assert Path(gate_calls[0]["stage_root"]) == copied_stage_root
    assert _tree(web_data) == before_web
    assert _sha(status_destination) == before_status_sha
    assert _sha(source_monitor) == source_monitor_sha
    assert not (web_data.parent / phase4d.PHASE4D_PUBLISH_JOURNAL).exists()
    assert not list(web_data.parent.glob(".phase4d-publish-txn-*"))

    result = {
        "scenario": "copied_v09_alignment_stage_outside_fixed_v05_v09_paths_digest_cli_omitted_monitor_digest_fields_removed",
        "source_v09_stage_file_count": copied_file_count,
        "source_v09_stage_payload_bytes": sum(path.stat().st_size for path in copied_stage_root.rglob("*") if path.is_file()),
        "candidate_content_preserved": {
            "alignment_strategy_id": monitor.get("default_strategy_id"),
            "strategy_replay_mode": monitor.get("strategy_replay_mode"),
            "alignment_scope_preserved": True,
            "all_non_monitor_stage_file_hashes_match_source": True,
            "candidate_digest_fields_removed_from_monitor": True,
        },
        "direct_promote_digest_argument": None,
        "gate_invocations": gate_calls,
        "gate_rejection": str(captured.value),
        "public_web_data_unchanged": True,
        "b_select_status_unchanged": True,
        "promotion_transaction_created": False,
        "source_v09_stage_unchanged": _sha(source_monitor) == source_monitor_sha,
    }
    (RUN_OUTPUT / "copy_stage_promote_test_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
