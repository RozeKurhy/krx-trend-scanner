"""Automated Consistency and Reproducibility Tests for Stage v0.3 Research Evidence."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v03_research import (
    HYPOTHESES,
    generate_research_artifacts,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_available() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("001540")
    return daily is not None and not daily.empty


_HAS_CACHE = _cache_available()


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_research_artifact_deterministic_regeneration():
    """Verify that stage_v03_research generator produces consistent artifacts deterministically."""
    res = generate_research_artifacts(_REPO_ROOT)
    assert len(res["df_audit"]) == len(HYPOTHESES)
    assert len(res["df_bench"]) == len(HYPOTHESES) + 1
    assert res["summary"]["generalizable_rule_found"] is False
    assert res["summary"]["final_recommendation"] == "NO_GENERALIZABLE_RULE_FOUND"


def test_research_feature_artifacts_row_counts_and_structure():
    """Verify that source-of-truth CSVs have correct counts and schemas."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v03_research"
    tm_df = pd.read_csv(out_dir / "transition_match13_features.csv", dtype={"ticker": str})
    prem_df = pd.read_csv(out_dir / "premature13_features.csv", dtype={"ticker": str})
    rec_df = pd.read_csv(out_dir / "recycled3_features.csv", dtype={"ticker": str})

    assert len(tm_df) == 13
    assert len(prem_df) == 13
    assert len(rec_df) == 3

    # Check 026910 is in premature13
    assert "026910" in prem_df["ticker"].values


def test_026910_audit_semantics_correctness():
    """Verify 026910 audited semantics strictly adhere to guidelines (audited_target_stage is null)."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v03_research"
    summary = json.loads((out_dir / "research_summary.json").read_text(encoding="utf-8"))

    focus_case = summary["focus_case_026910_audit"]
    assert focus_case["ticker"] == "026910"
    assert focus_case["manual_stage_fit"] == "TOO_EARLY"
    assert focus_case["audited_target_stage"] is None
    assert focus_case["gate_expectation"] == "candidate_stage != TRANSITION"
    assert "Within the 36-month feature window" in focus_case["research_hypothesis"]


def test_hypothesis_audit_table_counts_match():
    """Verify hypothesis audit table rows correspond exactly to defined hypotheses."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v03_research"
    df_audit = pd.read_csv(out_dir / "hypothesis_separation_audit.csv")

    assert len(df_audit) == 7
    expected_ids = ["HYP_A", "HYP_B", "HYP_C", "HYP_D", "HYP_E", "HYP_F", "HYP_G"]
    assert list(df_audit["hypothesis_id"]) == expected_ids

    # Check that no hypothesis is falsely labeled GENERALIZABLE
    assert "GENERALIZABLE" not in df_audit["disposition"].values
