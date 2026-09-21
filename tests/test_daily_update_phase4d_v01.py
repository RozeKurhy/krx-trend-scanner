"""Focused fail-closed checks for the Phase 4D static projection runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_daily_update_phase4d_v01 as phase4d


def test_target_as_of_is_required():
    with pytest.raises(SystemExit):
        phase4d.build_parser().parse_args([])


def test_staging_requires_all_mandatory_outputs(tmp_path: Path):
    (tmp_path / "stocks").mkdir()
    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_STAGE_REQUIRED_OUTPUT_MISSING"):
        phase4d.validate_staging(tmp_path, "2026-09-17", "2026-09-17")


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
