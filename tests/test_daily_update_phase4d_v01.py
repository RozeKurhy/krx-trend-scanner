"""Focused fail-closed checks for the Phase 4D static projection runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_daily_update_phase4d_v01 as phase4d


def test_target_as_of_is_required():
    with pytest.raises(SystemExit):
        phase4d.build_parser().parse_args([])


def test_phase4d_reads_v2_b_select_status_path_and_id(tmp_path: Path):
    assert phase4d.B_SELECT_ID == "PATTERN_B_SELECT_CORE_V02"
    assert phase4d._b_select_status_path(tmp_path, "2026-10-05") == (
        tmp_path / "artifacts/strategies/b_select_core_v2/production/20261005/status.json"
    )


def test_explicit_phase4c_rebuild_skips_validation_of_old_published_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _unexpected_inspection(*args, **kwargs):
        raise AssertionError("old published snapshot must not block an explicit rebuild")

    monkeypatch.setattr(phase4d, "inspect_published_payload", _unexpected_inspection)

    def _make_stage_root(*args, **kwargs):
        path = tmp_path / "phase4d-stage"
        path.mkdir()
        return str(path)

    monkeypatch.setattr(phase4d.tempfile, "mkdtemp", _make_stage_root)
    monkeypatch.setattr(
        phase4d,
        "_stage_payloads",
        lambda target, stage, *, phase4c_result: {
            "reference_market_date": "2026-10-02",
            "sector_membership": {},
        },
    )
    monkeypatch.setattr(phase4d, "validate_staging", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        phase4d,
        "_inspect_final_promotion_snapshot",
        lambda *args, **kwargs: {"status": "PASS", "protected_file_count": 0},
    )
    result = phase4d.run_phase4d(
        "2026-10-03",
        execute_live=False,
        phase4c_result={
            "status": "PASS",
            "network_calls": 0,
            "web_data_writes": 0,
            "reference_market_date": "2026-10-02",
        },
    )

    assert result["status"] == "PASS"
    assert result["post_promote_readback"] is None


def test_staging_requires_all_mandatory_outputs(tmp_path: Path):
    (tmp_path / "stocks").mkdir()
    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_STAGE_REQUIRED_OUTPUT_MISSING"):
        phase4d.validate_staging(tmp_path, "2026-09-17", "2026-09-17")


def test_b_select_monitor_projection_matches_status_without_display_only_fields():
    status_items = [{
        "ticker": "064260",
        "action": "HOLD",
        "trade_history": [{"trade_sequence": 1}],
    }]
    monitor_items = [{
        "ticker": "064260",
        "action": "HOLD",
        "fundamental_status": "UNKNOWN",
    }]

    assert phase4d._b_select_monitor_items_match_status(monitor_items, status_items)
    monitor_items[0]["action"] = "EXIT"
    assert not phase4d._b_select_monitor_items_match_status(monitor_items, status_items)


def _health_validation_fixture(
    tmp_path: Path,
    *,
    overall_status: str = "NORMAL",
    fundamentals_status: str = "NORMAL",
    integrity: dict[str, int] | None = None,
) -> tuple[Path, dict[str, dict]]:
    target = "2026-09-17"
    stage = tmp_path / "stage"
    stocks_dir = stage / "stocks"
    stocks_dir.mkdir(parents=True)
    common_item = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "asset_type": "COMMON",
        "bucket": "unavailable",
        "trade_history": [],
        "permanent_identity_excluded": False,
    }
    common_monitor_item = {key: value for key, value in common_item.items() if key != "trade_history"}
    b_status = {
        "status": "PASS",
        "strategy_id": phase4d.B_SELECT_ID,
        "requested_as_of": target,
        "reference_market_date": target,
        "scope": {"type": "PUBLISHED_COMMON_REPORTS", "report_count": 1},
        "count": 1,
        "counts": {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 1},
        "items": [common_item],
        "network_requests": 0,
        "evaluation_error_count": 0,
        "date_mismatch_count": 0,
        "future_reference_count": 0,
        "duplicate_item_count": 0,
        "cross_strategy_contamination_count": 0,
        "permanent_identity_exclusion_count": 181,
        "current_v1_source_row_count": 0,
        "source_authorities": {"signal_cadence": "MONTH_END_ENTRY_DAILY_NORMAL_EXIT"},
    }
    documents: dict[str, dict] = {
        "stock-index.json": {
            "requested_as_of": target,
            "reference_market_date": target,
            "items": [{"ticker": "000001", "report_available": True}],
            "available_report_count": 1,
        },
        "market-ranking.json": {
            "requested_as_of": target,
            "reference_market_date": target,
            "items": [{"ticker": "000001"}],
            "scope": {"report_count": 1},
        },
        "strategy-monitor.json": {
            "schema_version": 2,
            "default_strategy_id": phase4d.STRATEGY_ID,
            "requested_as_of": target,
            "reference_market_date": target,
            "strategies": [
                {
                    "id": phase4d.STRATEGY_ID,
                    "label": "A FAST Core V2",
                    "asset_scope": "COMMON",
                    "scope": {"type": "PUBLISHED_COMMON_REPORTS", "report_count": 1},
                    "counts": b_status["counts"],
                    "items": [common_monitor_item],
                },
                {
                    "id": phase4d.B_SELECT_ID,
                    "label": "B Select Core V2",
                    "asset_scope": "COMMON",
                    "scope": {"type": "PUBLISHED_COMMON_REPORTS", "report_count": 1},
                    "counts": b_status["counts"],
                    "items": [common_monitor_item],
                },
                {
                    "id": phase4d.JULIA_ID,
                    "label": "Julia V1",
                    "asset_scope": "OFFICIAL_ETF_36",
                    "scope": {"type": "OFFICIAL_ETF_36", "report_count": 0},
                    "counts": {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0},
                    "items": [],
                },
            ],
        },
        "sector-rs-ranking.json": {
            "requested_as_of": target,
            "reference_market_date": target,
            "as_of": target,
            "items": [{"ticker": "000001", "report_available": True}],
            "scope": {"population_count": 1},
        },
        "foreign-net-buy-ranking.json": {
            "requested_as_of": target,
            "reference_market_date": target,
            "as_of": target,
            "items": [{"ticker": "000001", "report_available": True}],
            "coverage": {"target_common_universe_count": 1, "flow_covered_count": 1},
        },
        "health.json": {
            "requested_as_of": target,
            "reference_market_date": target,
            "overall_status": overall_status,
            "fundamentals": {
                "status": fundamentals_status,
                "output_integrity": integrity or {
                    "outside_universe_count": 0,
                    "invalid_output_count": 0,
                    "duplicate_payload_count": 0,
                },
            },
            "stock_reports": {
                "ready": True,
                "report_version": "0.7",
                "source_json_count": 1,
                "web_compact_count": 1,
                "web_index_available_report_count": 1,
            },
        },
    }
    documents["stocks/000001.json"] = {
        "identity": {"asset_type": "COMMON"},
        "technical_details": {
            "requested_as_of": target,
            "reference_market_date": target,
            "report_version": "0.7",
        },
        "strategy": {"id": phase4d.STRATEGY_ID},
    }
    documents[phase4d.B_SELECT_STATUS_STAGING_NAME] = b_status
    for name in phase4d.REQUIRED_FILES:
        (stage / name).touch()
    (stocks_dir / "000001.json").touch()
    (stage / phase4d.B_SELECT_STATUS_STAGING_NAME).touch()
    return stage, documents


def test_validate_staging_rejects_non_normal_health(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path, overall_status="CHECK_REQUIRED")
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_HEALTH_OVERALL_NOT_NORMAL"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_rejects_non_normal_fundamentals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path, fundamentals_status="CHECK_REQUIRED")
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_HEALTH_FUNDAMENTALS_NOT_NORMAL"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_rejects_fundamentals_integrity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(
        tmp_path,
        integrity={"outside_universe_count": 1, "invalid_output_count": 0, "duplicate_payload_count": 0},
    )
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_HEALTH_FUNDAMENTALS_INTEGRITY_FAILED"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_rejects_legacy_report_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    documents["stocks/000001.json"]["technical_details"]["report_version"] = "0.5"
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_STOCK_REPORT_VERSION_MISMATCH"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_requires_v07_health_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    documents["health.json"]["stock_reports"]["report_version"] = "0.5"
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_STOCK_REPORT_VERSION_MISMATCH: health.json"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_accepts_normal_health(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    result = phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")

    assert result["health_overall_status"] == "NORMAL"
    assert result["stock_report_count"] == 1


def test_validate_staging_accepts_promoted_fast_row_and_matching_report_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    promoted_id = phase4d.PROMOTED_STRATEGY_ID
    monitor = documents["strategy-monitor.json"]
    monitor["default_strategy_id"] = promoted_id
    monitor["strategies"][0].update({
        "id": promoted_id,
        "label": "A FAST Core V2 Alignment 500B",
        "promotion_gate_status": "ACTIVE",
        "effective_signal_date": "2026-09-01",
    })
    documents["stocks/000001.json"]["strategy"]["id"] = promoted_id
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    result = phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")
    assert result["stock_report_count"] == 1


def test_validate_staging_accepts_inactive_full_history_replay_and_rejects_mismatched_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    stage, documents = _health_validation_fixture(tmp_path)
    promoted_id = phase4d.PROMOTED_STRATEGY_ID
    digest = "d" * 64
    scope = {
        "type": "PUBLISHED_COMMON_REPORTS",
        "report_count": 1,
        "requested_as_of": "2026-09-17",
        "reference_market_date": "2026-09-17",
        "output_strategy_id": promoted_id,
    }
    monitor = documents["strategy-monitor.json"]
    monitor.update({
        "default_strategy_id": promoted_id,
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
    })
    monitor["strategies"][0].update({
        "id": promoted_id,
        "label": "A FAST Core V2 Alignment 500B",
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
    })
    documents["stocks/000001.json"]["strategy"].update({
        "id": promoted_id,
        "strategy_id": promoted_id,
        "strategy_replay_mode": "FULL_HISTORY_ALIGNMENT_WEB",
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
        "history": [],
    })
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    result = phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")

    assert result["fast_replay_projection"]["trade_mismatch_count"] == 0
    assert result["fast_replay_projection"]["open_mismatch_count"] == 0

    monitor["strategies"][0]["strategy_replay_digest"] = "e" * 64
    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_FAST_FULL_HISTORY_REPLAY_PROVENANCE_INVALID"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_validate_staging_rejects_mismatched_promoted_report_and_monitor_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    promoted_id = phase4d.PROMOTED_STRATEGY_ID
    monitor = documents["strategy-monitor.json"]
    monitor["default_strategy_id"] = promoted_id
    monitor["strategies"][0].update({
        "id": promoted_id,
        "label": "A FAST Core V2 Alignment 500B",
        "promotion_gate_status": "ACTIVE",
        "effective_signal_date": "2026-09-01",
    })
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_FAST_REPORT_MONITOR_STRATEGY_MISMATCH"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def _write_noop_canonical(root: Path, *, alignment: bool) -> dict:
    target = "2026-09-17"
    report_dir = root / "artifacts/reporting/stock_reports/20260917"
    json_dir = report_dir / "json"
    json_dir.mkdir(parents=True)
    strategy_id = phase4d.PROMOTED_STRATEGY_ID if alignment else phase4d.STRATEGY_ID
    core = {"strategy_id": strategy_id, "canonical_position": "FLAT", "current_trade": None, "trade_history": []}
    if alignment:
        core["strategy_replay_mode"] = phase4d.phase4b.FULL_HISTORY_ALIGNMENT_WEB
        core["promotion_gate_audit"] = []
    (json_dir / "000001.json").write_text(json.dumps({
        "ticker": "000001",
        "asset_type": "COMMON",
        "requested_as_of": target,
        "reference_market_date": target,
        "a_fast_core": core,
    }), encoding="utf-8")
    if alignment:
        result = phase4d.phase4b.finalize_full_history_alignment_reports(
            report_dir, {"000001"}, target, target,
        )
        assert result["valid"] is True
        return result
    return {"strategy_id": strategy_id}


def _write_noop_monitor(root: Path, *, alignment: dict | None) -> None:
    target = "2026-09-17"
    if alignment is None:
        monitor = {
            "requested_as_of": target,
            "reference_market_date": target,
            "default_strategy_id": phase4d.STRATEGY_ID,
            "strategies": [{"id": phase4d.STRATEGY_ID}],
        }
    else:
        monitor = {
            "requested_as_of": target,
            "reference_market_date": target,
            "default_strategy_id": phase4d.PROMOTED_STRATEGY_ID,
            "strategy_replay_mode": phase4d.phase4b.FULL_HISTORY_ALIGNMENT_WEB,
            "strategy_replay_digest": alignment["strategy_replay_digest"],
            "strategy_replay_scope": alignment["strategy_replay_scope"],
            "strategies": [{
                "id": phase4d.PROMOTED_STRATEGY_ID,
                "strategy_replay_mode": phase4d.phase4b.FULL_HISTORY_ALIGNMENT_WEB,
                "strategy_replay_digest": alignment["strategy_replay_digest"],
                "strategy_replay_scope": alignment["strategy_replay_scope"],
            }],
        }
    path = root / "web/data/strategy-monitor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(monitor), encoding="utf-8")


def _run_noop_precheck(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    target = "2026-09-17"
    monkeypatch.setattr(phase4d, "ROOT", root)
    monkeypatch.setattr(
        phase4d,
        "inspect_published_payload",
        lambda *args, **kwargs: {"reference_market_date": target, "validation": {"fixture": True}},
    )
    monkeypatch.setattr(
        phase4d,
        "_inspect_final_promotion_snapshot",
        lambda *args, **kwargs: {"status": "PASS", "protected_file_count": 0},
    )
    monkeypatch.setattr(phase4d, "validate_staging", lambda *args, **kwargs: {})
    return phase4d.run_phase4d(target, execute_live=False, root=root)


def test_phase4d_does_not_noop_on_v2_web_when_canonical_alignment_is_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    _write_noop_canonical(tmp_path, alignment=True)
    _write_noop_monitor(tmp_path, alignment=None)
    stage_calls = []
    monkeypatch.setattr(
        phase4d,
        "_stage_payloads",
        lambda target, stage, *, phase4c_result=None: (
            stage_calls.append(target) or {"reference_market_date": target, "sector_membership": {}}
        ),
    )

    result = _run_noop_precheck(tmp_path, monkeypatch)

    assert result["status"] == "PASS"
    assert stage_calls == ["2026-09-17"]


def test_phase4d_keeps_noop_when_published_alignment_matches_canonical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    canonical = _write_noop_canonical(tmp_path, alignment=True)
    _write_noop_monitor(tmp_path, alignment=canonical)
    monkeypatch.setattr(
        phase4d,
        "_stage_payloads",
        lambda *args, **kwargs: pytest.fail("matching Alignment publication must remain NOOP"),
    )

    result = _run_noop_precheck(tmp_path, monkeypatch)

    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["web_data_writes"] == 0


def test_phase4d_fails_closed_when_canonical_alignment_digest_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    canonical = _write_noop_canonical(tmp_path, alignment=True)
    _write_noop_monitor(tmp_path, alignment=canonical)
    report_path = tmp_path / "artifacts/reporting/stock_reports/20260917/json/000001.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["a_fast_core"]["strategy_replay_digest"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        phase4d,
        "_stage_payloads",
        lambda *args, **kwargs: pytest.fail("invalid canonical must fail before staging"),
    )

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_CANONICAL_FULL_HISTORY_ALIGNMENT_INVALID"):
        _run_noop_precheck(tmp_path, monkeypatch)


def test_phase4d_preserves_v2_noop_for_v2_canonical_and_published_web(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    _write_noop_canonical(tmp_path, alignment=False)
    _write_noop_monitor(tmp_path, alignment=None)
    monkeypatch.setattr(
        phase4d,
        "_stage_payloads",
        lambda *args, **kwargs: pytest.fail("existing V2 canonical/web should remain NOOP"),
    )

    result = _run_noop_precheck(tmp_path, monkeypatch)

    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["web_data_writes"] == 0


def test_phase4d_reuses_existing_exact_date_b_select_status_without_recalculation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    target = "2026-09-17"
    status = {
        "status": "PASS",
        "strategy_id": phase4d.B_SELECT_ID,
        "requested_as_of": target,
        "reference_market_date": target,
        "network_requests": 0,
        "count": 1,
        "items": [],
    }
    status_path = phase4d._b_select_status_path(tmp_path, target)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    calls = []
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    monkeypatch.setattr(
        phase4d.phase4c,
        "run_phase4c",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "PASS"},
    )

    result = phase4d._run_phase4c_for_phase4d(target)

    assert result["status"] == "PASS"
    assert len(calls) == 1
    assert calls[0][1]["b_select_status_override"] == status


def test_phase4d_rejects_invalid_existing_b_select_status_without_recalculation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    target = "2026-09-17"
    status_path = phase4d._b_select_status_path(tmp_path, target)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({
        "status": "PASS",
        "strategy_id": phase4d.B_SELECT_ID,
        "requested_as_of": "2026-09-16",
        "network_requests": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    monkeypatch.setattr(
        phase4d.phase4c,
        "run_phase4c",
        lambda *args, **kwargs: pytest.fail("invalid stored B Select status must not trigger recalculation"),
    )

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_B_SELECT_CANONICAL_STATUS_INVALID"):
        phase4d._run_phase4c_for_phase4d(target)


def test_phase4d_uses_existing_builder_when_exact_date_b_select_status_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    target = "2026-09-17"
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(
        phase4d.phase4c,
        "run_phase4c",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "PASS"},
    )

    phase4d._run_phase4c_for_phase4d(target)

    assert len(calls) == 1
    assert calls[0][0] == (target,)
    assert calls[0][1] == {"root": tmp_path}


def test_phase4d_reuses_the_validated_phase4c_foreign_ranking_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    payload = {"requested_as_of": "2026-09-17", "items": [{"ticker": "000001"}]}
    monkeypatch.setattr(
        phase4d.foreign_web,
        "build_foreign_net_buy_ranking",
        lambda **kwargs: pytest.fail("Phase4D must not rebuild the Phase4C repository projection"),
    )

    result = phase4d._foreign_net_buy_payload(
        {"_foreign_net_buy_for_phase4d": payload},
        as_of="2026-09-17",
    )

    assert result is payload


def _promotion_fixture(root: Path) -> tuple[Path, Path]:
    web_data = root / "web/data"
    stage_data = root / ".phase4d-stage/data"
    web_data.mkdir(parents=True)
    (web_data / "stocks").mkdir()
    stage_data.mkdir(parents=True)
    (stage_data / "stocks").mkdir()
    for index, name in enumerate(phase4d.REQUIRED_FILES):
        (web_data / name).write_text(json.dumps({"old": index}), encoding="utf-8")
        (stage_data / name).write_text(json.dumps({"new": index}), encoding="utf-8")
    (web_data / "stocks/000001.json").write_text('{"old":true}', encoding="utf-8")
    (stage_data / "stocks/000001.json").write_text('{"new":true}', encoding="utf-8")
    (stage_data / phase4d.B_SELECT_STATUS_STAGING_NAME).write_text('{"status":"PASS"}', encoding="utf-8")
    (web_data / "etf-ranking.json").write_text('{"name":"etf"}', encoding="utf-8")
    (web_data / "fear-index.json").write_text('{"name":"fear"}', encoding="utf-8")
    identity_reports = web_data / "identity-reports"
    identity_reports.mkdir()
    for index in range(148):
        (identity_reports / f"{index:06d}.json").write_text(json.dumps({"identity": index}), encoding="utf-8")
    (web_data / "identity-report-routes.json").write_text(json.dumps({
        "route_count": 2,
        "supplemental_report_count": 1,
        "items": [
            {"url": "./data/stocks/000001.json"},
            {"url": "./data/identity-reports/000000.json"},
        ],
    }), encoding="utf-8")
    return stage_data, web_data


def test_phase4d_promote_snapshot_preserves_151_sidecars_and_routes(tmp_path: Path):
    stage_data, web_data = _promotion_fixture(tmp_path)

    snapshot_check = phase4d._inspect_final_promotion_snapshot(stage_data, web_data)

    assert snapshot_check["status"] == "PASS"
    assert snapshot_check["protected_file_count"] == 151
    assert snapshot_check["route_integrity"]["route_count"] == 2
    assert snapshot_check["route_integrity"]["missing_route_count"] == 0
    promoted = phase4d.promote(
        stage_data,
        web_data,
        target_as_of="2026-09-17",
        post_publish_validate=lambda _status_path: {"status": "PASS"},
    )
    assert promoted["promoted_snapshot_validation"]["protected_files"] == snapshot_check["protected_files"]
    assert (web_data / "stocks/000001.json").read_text(encoding="utf-8") == '{"new":true}'
    assert (web_data / "identity-reports/000000.json").is_file()


def test_phase4d_promote_snapshot_fails_when_a_protected_file_is_missing(tmp_path: Path):
    stage_data, web_data = _promotion_fixture(tmp_path)
    snapshot = tmp_path / "staged-final"
    phase4d._build_promotion_snapshot(stage_data, web_data, snapshot)
    (snapshot / "identity-reports/000000.json").unlink()

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_PROMOTION_PROTECTED_WEB_FILES_MISMATCH"):
        phase4d._validate_promoted_snapshot(web_data, snapshot)


def test_validate_staging_rejects_invalid_promoted_effective_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    promoted_id = phase4d.PROMOTED_STRATEGY_ID
    monitor = documents["strategy-monitor.json"]
    monitor["default_strategy_id"] = promoted_id
    monitor["strategies"][0].update({
        "id": promoted_id,
        "label": "A FAST Core V2 Alignment 500B",
        "promotion_gate_status": "ACTIVE",
        "effective_signal_date": "2026-19-01",
    })
    documents["stocks/000001.json"]["strategy"]["id"] = promoted_id
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_FAST_ACTIVE_GATE_DATE_INVALID"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17")


def test_phase4d_combined_contract_requires_exact_official_etf36(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stage, documents = _health_validation_fixture(tmp_path)
    monkeypatch.setattr(phase4d, "_read_json", lambda path: documents[path.relative_to(stage).as_posix()])

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_ETF36_SET_MISMATCH"):
        phase4d.validate_staging(stage, "2026-09-17", "2026-09-17", require_etf36=True)


def test_foreign_ui_uses_date_contract_not_legacy_fixed_date():
    script = (Path(__file__).resolve().parents[1] / "web/js/foreign.js").read_text(encoding="utf-8")
    assert 'value.as_of === "2026-09-04"' not in script
    assert "value.as_of === value.reference_market_date" in script
    assert "value.reference_market_date <= value.requested_as_of" in script


def test_phase4d_passes_periodic_sector_membership_snapshot_to_foreign_export(monkeypatch, tmp_path):
    selected_path = tmp_path / "sector_membership_20260917.parquet"
    resolver_calls = []
    foreign_calls = []

    def _resolver(target_as_of, *, root):
        resolver_calls.append((target_as_of, root))
        return "2026-09-17", selected_path

    monkeypatch.setattr(phase4d.phase4c, "resolve_sector_membership_for_target", _resolver)
    monkeypatch.setattr(
        phase4d.stock_web,
        "build_web_payload",
        lambda *args, **kwargs: ({"items": []}, {}, {}),
    )
    monkeypatch.setattr(phase4d.market_web, "build_market_ranking", lambda **kwargs: {})
    monkeypatch.setattr(phase4d.strategy_web, "build_strategy_monitor", lambda **kwargs: {})
    monkeypatch.setattr(
        phase4d.b_select_status_web,
        "build_b_select_status",
        lambda **kwargs: {
            "status": "PASS",
            "strategy_id": phase4d.B_SELECT_ID,
            "requested_as_of": "2026-09-18",
            "reference_market_date": "2026-09-18",
            "count": 0,
            "counts": {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0},
            "evaluation_error_count": 0,
            "network_requests": 0,
            "items": [],
        },
    )
    monkeypatch.setattr(phase4d.sector_web, "build_sector_rs_web_payload", lambda **kwargs: {})

    def _foreign(**kwargs):
        foreign_calls.append(kwargs)
        return {}

    monkeypatch.setattr(phase4d.foreign_web, "build_foreign_net_buy_ranking", _foreign)
    monkeypatch.setattr(phase4d.health_web, "build_health", lambda *args, **kwargs: {})

    stage_data = tmp_path / "stage"
    stage_data.mkdir()
    result = phase4d._stage_payloads(
        "2026-09-18",
        stage_data,
        phase4c_result={
            "status": "PASS",
            "network_calls": 0,
            "web_data_writes": 0,
            "reference_market_date": "2026-09-18",
        },
    )

    assert resolver_calls == [("2026-09-18", phase4d.ROOT)]
    assert foreign_calls[0]["sector_path"] == selected_path
    assert result["sector_membership"] == {
        "effective_date": "2026-09-17",
        "path": str(selected_path),
    }
