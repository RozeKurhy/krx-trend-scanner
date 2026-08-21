"""Targeted tests for Pattern A FAST Strategy Finalization Provenance and CSV Comparison."""

import json
from pathlib import Path
import pytest

from scripts.compare_pattern_a_fast_corrected_baseline import compare_baselines

ROOT = Path(__file__).resolve().parent.parent


def test_baseline_csv_cardinality_and_population_invariants():
    """Verify deterministic CSV comparison invariants between legacy (553) and corrected (551)."""
    res = compare_baselines()

    assert res["legacy_trade_count"] == 553
    assert res["corrected_trade_count"] == 551
    assert res["common_count"] == 542
    assert res["legacy_only_count"] == 11
    assert res["corrected_only_count"] == 9

    # Cardinality exact match
    assert res["legacy_trade_count"] == res["common_count"] + res["legacy_only_count"]
    assert res["corrected_trade_count"] == res["common_count"] + res["corrected_only_count"]

    # Sanity checks: 000270 (Kia) and 001450 (Hyundai Marine) are common tickers, NOT dropped
    assert "000270" not in res["legacy_only_tickers"]
    assert "000270" in res["shifted_entry_date_tickers"] or "000270" not in res["corrected_only_tickers"]
    assert "001450" not in res["legacy_only_tickers"]

    # Specific dropped and gained verification
    assert "002020" in res["legacy_only_tickers"]  # 코오롱
    assert "011690" in res["corrected_only_tickers"]  # 와이투솔루션

    # Shifted and changed counts
    assert res["shifted_entry_date_count"] == 55
    assert res["changed_exit_type_count"] == 4
    assert res["changed_loss_guard_count"] == 4
    assert res["changed_first_progressed_date_count"] == 0


def test_provenance_consistency_across_artifacts():
    """Verify provenance metadata consistency across JSON, Markdown, and evaluation artifacts."""
    # 1. Final strategy JSON
    strat_json_path = ROOT / "artifacts/pattern_a_fast/final_strategy_v01/pattern_a_fast_final_strategy_v01.json"
    strat_json = json.loads(strat_json_path.read_text(encoding="utf-8"))

    assert strat_json["evaluation_basis"] == "CORRECTED_PIT_BASELINE"
    assert strat_json["calendar_authority_commit"] == "88d54d85bdee1f2121bec9b27a250cbc1cb9f98f"
    assert strat_json["corrected_evaluation_commit"] == "f73e0c23b10cc3e3f8215693ef5095b2c0f6716d"
    assert strat_json["architecture_authority_commit"] == "89df82a938dba1961c2342064db2dc0061a5f2ca"
    assert strat_json["preregistration_authority_commit"] == "a5c29e7e97cb7e6830c3dcd25d824e5779f2312f"

    # 2. Evaluation JSON (both active and corrected_pit)
    eval_json_paths = [
        ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/pattern_a_fast_strategy_finalization_v01_evaluation.json",
        ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01/pattern_a_fast_strategy_finalization_v01_evaluation.json",
    ]

    for ep in eval_json_paths:
        data = json.loads(ep.read_text(encoding="utf-8"))
        meta = data["metadata"]
        assert meta["evaluation_basis"] == "CORRECTED_PIT_BASELINE"
        assert meta["calendar_authority_commit"] == "88d54d85bdee1f2121bec9b27a250cbc1cb9f98f"
        assert meta["corrected_evaluation_commit"] == "f73e0c23b10cc3e3f8215693ef5095b2c0f6716d"
        assert meta["total_common_universe"] == 2528
        assert meta["phase10_investable_universe"] == 1081
        assert meta["primary_trade_count"] == 551
        assert meta["transition_count"] == 477
        assert meta["early_trend_count"] == 74

    # 3. Final strategy Markdown
    strat_md_path = ROOT / "docs/patterns/pattern_a_fast/strategy/final_v01.md"
    strat_md = strat_md_path.read_text(encoding="utf-8")
    assert "88d54d8" in strat_md
    assert "f73e0c2" in strat_md
    assert "CORRECTED_PIT_BASELINE" in strat_md
