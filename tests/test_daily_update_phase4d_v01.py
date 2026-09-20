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
