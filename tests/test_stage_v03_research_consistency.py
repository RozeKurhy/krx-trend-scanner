"""Automated Consistency and Reproducibility Tests for Stage v0.3 Research Evidence."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v03_research import (
    HYPOTHESES,
    evaluate_benchmark_with_demotion_rule,
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
    """Verify that stage_v03_research generator produces byte-for-byte / identical payload deterministically across multiple runs."""
    res1 = generate_research_artifacts(_REPO_ROOT)
    res2 = generate_research_artifacts(_REPO_ROOT)

    # 1. Compare DataFrames
    pd.testing.assert_frame_equal(res1["df_audit"], res2["df_audit"])
    pd.testing.assert_frame_equal(res1["df_bench"], res2["df_bench"])

    # 2. Compare JSON summaries
    assert res1["summary"] == res2["summary"]
    assert res1["summary"]["generalizable_rule_found"] is False
    assert res1["summary"]["final_recommendation"] == "NO_GENERALIZABLE_RULE_FOUND"


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


def test_hypothesis_audit_count_exact_equality():
    """Verify that hypothesis_separation_audit.csv numbers match exact source feature evaluations."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v03_research"
    df_tm = pd.read_csv(out_dir / "transition_match13_features.csv", dtype={"ticker": str})
    df_prem = pd.read_csv(out_dir / "premature13_features.csv", dtype={"ticker": str})
    df_rec = pd.read_csv(out_dir / "recycled3_features.csv", dtype={"ticker": str})
    df_audit = pd.read_csv(out_dir / "hypothesis_separation_audit.csv")

    row_026910 = df_prem[df_prem["ticker"] == "026910"].iloc[0]

    for hyp in HYPOTHESES:
        audit_row = df_audit[df_audit["hypothesis_id"] == hyp.hypothesis_id].iloc[0]

        # Calculate directly
        exp_026910_aff = bool(hyp.demote_rule(row_026910))
        exp_prem_demoted = sum(1 for _, r in df_prem.iterrows() if r["candidate_stage"] == "transition" and hyp.demote_rule(r))
        exp_tm_lost = sum(1 for _, r in df_tm.iterrows() if r["candidate_stage"] == "transition" and hyp.demote_rule(r))
        exp_rec_demoted = sum(1 for _, r in df_rec.iterrows() if r["candidate_stage"] == "transition" and hyp.demote_rule(r))

        assert audit_row["026910_affected"] == exp_026910_aff
        assert audit_row["premature_removed_count"] == 3 + exp_prem_demoted
        assert audit_row["transition_match_lost_count"] == exp_tm_lost
        assert audit_row["recycled_removed_count"] == 2 + exp_rec_demoted


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_benchmark_impact_exact_equality():
    """Verify that benchmark_impact.csv numbers match live evaluation from evaluate_benchmark_with_demotion_rule."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v03_research"
    df_bench = pd.read_csv(out_dir / "benchmark_impact.csv")

    # Check baseline row
    base_row = df_bench[df_bench["condition_id"] == "BASELINE_V02"].iloc[0]
    live_base = evaluate_benchmark_with_demotion_rule(_REPO_ROOT, lambda f: False)
    assert base_row["calib_exact"] == live_base["calib_exact"]
    assert base_row["calib_sev"] == live_base["calib_sev"]
    assert base_row["oos_exact"] == live_base["oos_exact"]
    assert base_row["oos_sev"] == live_base["oos_sev"]

    # Check each hypothesis row
    for hyp in HYPOTHESES:
        bench_row = df_bench[df_bench["condition_id"] == hyp.hypothesis_id].iloc[0]
        live_hyp = evaluate_benchmark_with_demotion_rule(_REPO_ROOT, hyp.demote_rule)
        assert bench_row["calib_exact"] == live_hyp["calib_exact"]
        assert bench_row["calib_sev"] == live_hyp["calib_sev"]
        assert bench_row["oos_exact"] == live_hyp["oos_exact"]
        assert bench_row["oos_sev"] == live_hyp["oos_sev"]
