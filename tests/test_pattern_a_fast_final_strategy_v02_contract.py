"""Targeted Contract & Documentation Invariant Tests for Pattern A FAST Final Strategy V02."""

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent

V01_DOC_PATH = ROOT / "docs/validation/pattern_a_fast_final_strategy_v01.md"
V01_JSON_PATH = ROOT / "artifacts/pattern_a_fast/final_strategy_v01/pattern_a_fast_final_strategy_v01.json"
V02_DOC_PATH = ROOT / "docs/validation/pattern_a_fast_final_strategy_v02.md"
V02_JSON_PATH = ROOT / "artifacts/pattern_a_fast/final_strategy_v02/pattern_a_fast_final_strategy_v02.json"
VERSIONS_INDEX_PATH = ROOT / "docs/validation/pattern_a_fast_strategy_versions.md"
V03_PREREG_PATH = ROOT / "docs/validation/pattern_a_fast_fresh_oos_v03_prereg.md"


def test_v01_frozen_baseline_preserved():
    """Section 2, 10: Verify V01 document and json are intact as historical frozen baseline."""
    assert V01_DOC_PATH.exists()
    assert V01_JSON_PATH.exists()

    v01_doc = V01_DOC_PATH.read_text(encoding="utf-8")
    assert "PATTERN_A_FAST_FINAL_STRATEGY_V01" in v01_doc
    assert "FIRST_QUALIFYING_ENTRY_PER_TICKER" in v01_doc

    v01_json = json.loads(V01_JSON_PATH.read_text(encoding="utf-8"))
    assert v01_json["strategy_name"] == "PATTERN_A_FAST_FINAL_STRATEGY_V01"
    assert v01_json["entry_contract"]["entry_selection"] == "FIRST_QUALIFYING_ENTRY_PER_TICKER"
    assert v01_json["strategy_status"] == "FINAL_STRATEGY_FROZEN"


def test_v02_strategy_contract_completeness():
    """Section 3, 11, 26: Verify V02 strategy document and JSON completeness."""
    assert V02_DOC_PATH.exists()
    assert V02_JSON_PATH.exists()

    v02_doc = V02_DOC_PATH.read_text(encoding="utf-8")
    assert "PATTERN_A_FAST_FINAL_STRATEGY_V02" in v02_doc
    assert "A FAST Core V2" in v02_doc
    assert "REENTRY_ONLY" in v02_doc
    assert "MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER" in v02_doc
    assert "STRATEGY_FINALIZATION_CLOSED" in v02_doc

    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))
    assert v02_json["strategy_name"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert v02_json["strategy_version"] == "v0.2"
    assert v02_json["strategy_alias"] == "A FAST Core V2"
    assert v02_json["preferred_alias"] == "A FAST Core"
    assert v02_json["strategy_status"] == "FINAL_STRATEGY_FROZEN"
    assert v02_json["research_status"] == "STRATEGY_FINALIZATION_CLOSED"
    assert v02_json["supersedes_for_current_use"] == "PATTERN_A_FAST_FINAL_STRATEGY_V01"
    assert v02_json["delta_from_v01"] == "REENTRY_ONLY"
    assert v02_json["production_status"] == "PRODUCTION_HOLD"


def test_v02_reentry_contract_invariants():
    """Section 5, 27: Verify V02 re-entry contract settings."""
    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))
    reentry = v02_json["reentry_contract"]

    assert reentry["enabled"] is True
    assert reentry["eligibility"] == "FULL_FRESH_ENTRY_CONTRACT"
    assert reentry["position_requirement"] == "NO_OPEN_POSITION"
    assert reentry["cooldown"] == "NONE"
    assert reentry["maximum_reentries"] == "NONE"
    assert reentry["pyramiding"] is False
    assert reentry["overlapping_same_ticker_position"] is False
    assert reentry["same_open_exit_and_reentry"] is False
    assert reentry["state_reset"] == "FULL"
    assert reentry["entry_open_reset"] is True
    assert reentry["loss_guard_reset"] is True
    assert reentry["progressed_lifecycle_reset"] is True
    assert reentry["exit4_hwm_reset"] is True


def test_v02_entry_and_exit_contract_match_v01():
    """Section 6-9: Verify V02 preserves V01's entry, loss guard, exit, and coverage rules exactly."""
    v01_json = json.loads(V01_JSON_PATH.read_text(encoding="utf-8"))
    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))

    # Entry components
    assert v02_json["entry_contract"]["allowed_pattern_a_stages"] == v01_json["entry_contract"]["allowed_pattern_a_stages"]
    assert v02_json["entry_contract"]["excluded_pattern_a_stages"] == v01_json["entry_contract"]["excluded_pattern_a_stages"]
    assert v02_json["entry_contract"]["fast_machine_stage"] == v01_json["entry_contract"]["fast_machine_stage"]
    assert v02_json["entry_contract"]["monthly_permission_state"] == v01_json["entry_contract"]["monthly_permission_state"]
    assert v02_json["entry_contract"]["daily_risk_allowed_states"] == v01_json["entry_contract"]["daily_risk_allowed_states"]
    assert v02_json["entry_contract"]["fast_score_allowed_statuses"] == v01_json["entry_contract"]["fast_score_allowed_statuses"]

    # Hold and Loss Guard
    assert v02_json["hold_and_loss_guard_contract"]["trigger_condition"] == v01_json["hold_and_loss_guard_contract"]["trigger_condition"]
    assert v02_json["hold_and_loss_guard_contract"]["active_window"] == v01_json["hold_and_loss_guard_contract"]["active_window"]

    # Exit
    assert v02_json["exit_contract"]["normal_lifecycle"]["frozen_drawdown_threshold_pt"] == v01_json["exit_contract"]["normal_lifecycle"]["frozen_drawdown_threshold_pt"]
    assert v02_json["exit_contract"]["coverage_hole"]["coverage_exit4_trigger"] == v01_json["exit_contract"]["coverage_hole"]["coverage_exit4_trigger"]


def test_v03_prereg_superseded_banner():
    """Section 21, 22: Verify V03 Fresh OOS prereg document has superseded banner."""
    assert V03_PREREG_PATH.exists()
    v03_doc = V03_PREREG_PATH.read_text(encoding="utf-8")
    assert "SUPERSEDED_HISTORICAL_PREREGISTRATION" in v03_doc
    assert "DO NOT USE FOR V02 FORWARD VALIDATION" in v03_doc


def test_strategy_versions_index():
    """Section 25: Verify strategy versions index document exists and correctly links V01 and V02."""
    assert VERSIONS_INDEX_PATH.exists()
    index_doc = VERSIONS_INDEX_PATH.read_text(encoding="utf-8")
    assert "PATTERN_A_FAST_FINAL_STRATEGY_V01" in index_doc
    assert "PATTERN_A_FAST_FINAL_STRATEGY_V02" in index_doc
    assert "HISTORICAL_FROZEN_BASELINE" in index_doc
    assert "MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER" in index_doc
