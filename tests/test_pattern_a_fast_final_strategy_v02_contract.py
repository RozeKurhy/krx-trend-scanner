"""Targeted Contract & Documentation Invariant Tests for Pattern A FAST Final Strategy V02 (Final Fix)."""

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
    """Section 2: Verify V01 document and json are intact as historical frozen baseline."""
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
    """Section 3, 11: Verify V02 strategy document and JSON completeness."""
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


def test_v02_reentry_only_full_contract_equality():
    """Section 13-16: Verify REENTRY_ONLY invariant via full dictionary contract equality."""
    v01_json = json.loads(V01_JSON_PATH.read_text(encoding="utf-8"))
    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))

    # Entry Contract: 100% equal except entry_selection
    v01_entry_core = {k: v for k, v in v01_json["entry_contract"].items() if k != "entry_selection"}
    v02_entry_core = {k: v for k, v in v02_json["entry_contract"].items() if k != "entry_selection"}
    assert v01_entry_core == v02_entry_core

    assert v01_json["entry_contract"]["entry_selection"] == "FIRST_QUALIFYING_ENTRY_PER_TICKER"
    assert v02_json["entry_contract"]["entry_selection"] == "MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER"

    # Hold and Loss Guard Contract: Full equality
    assert v01_json["hold_and_loss_guard_contract"] == v02_json["hold_and_loss_guard_contract"]

    # Exit Contract: Full equality (Normal Exit3/Exit4, Coverage Exit4, Never Progressed)
    assert v01_json["exit_contract"] == v02_json["exit_contract"]


def test_v02_final_evidence_authority():
    """Section 3, 4, 18: Verify final evidence authority commit and provenance separation."""
    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))

    expected_closure_sha = "36273d97ae6d4f5b1dbc72cca186bc6009b5fa51"
    expected_trade_gen_sha = "b9ba613be973906915e5081a0e5828dd6e1350d6"

    assert v02_json["evaluation_evidence_commit"] == expected_closure_sha
    assert v02_json["reentry_evidence_closure_commit"] == expected_closure_sha
    assert v02_json["reentry_trade_generation_commit"] == expected_trade_gen_sha

    v02_doc = V02_DOC_PATH.read_text(encoding="utf-8")
    assert "36273d9" in v02_doc
    assert "cdfeaed" not in v02_doc


def test_v02_risk_semantics_separate_gap_and_structural_tail():
    """Section 6-8, 19: Verify Loss Guard gap risk is decoupled from post-PROGRESSED structural tail."""
    v02_json = json.loads(V02_JSON_PATH.read_text(encoding="utf-8"))
    tradeoffs = v02_json["known_tradeoffs"]

    # -77.72 must not be inside loss_guard_execution_risk
    assert "-77.72" not in tradeoffs["loss_guard_execution_risk"]

    # deep_downside_tail must exist and capture 011170_02 structural tail
    assert "deep_downside_tail" in tradeoffs
    tail = tradeoffs["deep_downside_tail"]
    assert tail["worst_terminal_return_pct"] == -77.72
    assert tail["trade_id"] == "011170_02"
    assert tail["classification"] == "OPEN_AT_CUTOFF_STRUCTURAL_TAIL"
    assert "coverage" in tail["context"].lower() or "structural tail" in tail["classification"].lower()


def test_strategy_docs_do_not_contain_local_file_urls():
    """Section 11, 12, 20: Verify strategy documentation files contain zero local filesystem URLs or paths."""
    forbidden_tokens = ["file:///", "/Users/", "Users/june", "Documents/projects"]

    docs_to_check = [V02_DOC_PATH, VERSIONS_INDEX_PATH, V03_PREREG_PATH]
    for doc_path in docs_to_check:
        assert doc_path.exists()
        content = doc_path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in content, f"Found forbidden local path token '{token}' in {doc_path.name}"


def test_v03_prereg_superseded_banner():
    """Section 21: Verify V03 Fresh OOS prereg document has superseded banner."""
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
