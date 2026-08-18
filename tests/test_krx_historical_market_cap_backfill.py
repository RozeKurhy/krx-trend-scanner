"""Phase 13J-0 completed-weekly KRX historical market-cap integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

from trend_scanner.validation.historical_snapshot import build_historical_snapshot


ROOT = Path(__file__).resolve().parents[1]
BASE = "cb2aba5d680c2f5e770ef9441e2e781d82a8cb2e"
HISTORY = ROOT / "artifacts/investability/history"
AUDIT = HISTORY / "krx_historical_market_cap_backfill_audit_v01.json"
GRID = HISTORY / "krx_market_cap_reference_grid_v01.csv"
PROVENANCE = HISTORY / "krx_historical_market_cap_provenance_v01.csv"
REFERENCE_TICKER = "000150"
EXPECTED_CANDIDATES = [
    "2020-03-27", "2020-06-26", "2020-09-25", "2020-12-25", "2021-03-26", "2021-06-25",
    "2021-09-24", "2021-12-31", "2022-03-25", "2022-06-24", "2022-09-30", "2022-12-30",
    "2023-03-31", "2023-06-30", "2023-09-22", "2023-12-29", "2024-03-29", "2024-06-28",
    "2024-09-27", "2024-12-27", "2025-03-28", "2025-06-27",
]


def _audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _computed_completed_weekly_dates() -> dict[str, str]:
    daily = pd.read_parquet(ROOT / "data/raw/stocks" / f"{REFERENCE_TICKER}.parquet")
    result = {}
    for candidate in EXPECTED_CANDIDATES:
        snapshot = build_historical_snapshot(REFERENCE_TICKER, REFERENCE_TICKER, daily, candidate, include_incomplete_periods=False)
        assert snapshot.weekly_as_of is not None
        result[candidate] = snapshot.weekly_as_of.strftime("%Y-%m-%d")
    return result


def test_all_22_references_follow_the_frozen_completed_weekly_contract():
    audit = _audit()
    grid = pd.read_csv(GRID, dtype=str)
    computed = _computed_completed_weekly_dates()
    assert audit["status"] == "HISTORICAL_MARKET_CAP_PIT_READY"
    assert audit["reference_date_semantics"] == "BUILD_HISTORICAL_SNAPSHOT_COMPLETED_W_FRI"
    assert audit["all_reference_dates_covered"] is True
    assert audit["all_completed_weekly_reference_dates_match_effective_date"] is True
    assert (audit["reference_candidate_count"], audit["resolved_reference_count"], audit["active_reference_count"]) == (22, 22, 22)
    assert grid.calendar_candidate_date.tolist() == EXPECTED_CANDIDATES
    assert len(grid) == 22
    assert (grid.effective_date <= grid.calendar_candidate_date).all()
    assert (grid.completed_weekly_reference_date == grid.effective_date).all()
    assert grid.set_index("calendar_candidate_date").completed_weekly_reference_date.to_dict() == computed
    assert (grid.date_resolution_status == "EXACT_COMPLETED_WEEK").sum() == 18
    assert (grid.date_resolution_status == "PRIOR_COMPLETED_WEEK").sum() == 4


def test_active_and_superseded_sources_are_krx_only_hash_sealed_and_unambiguous():
    audit = _audit()
    provenance = pd.read_csv(PROVENANCE, dtype=str).fillna("")
    active = provenance[provenance.reference_status.eq("ACTIVE_REFERENCE")]
    superseded = provenance[provenance.reference_status.eq("SUPERSEDED_NON_REFERENCE_SOURCE")]
    assert audit["provider"] == audit["network_provider"].replace("_ONLY", "") == "KRX"
    assert audit["source_product"] == "ALL_STOCK_MARKET_DATA"
    assert audit["source_screen_id"] == "MDC0201020101"
    assert audit["network_request_count"] == 33
    assert len(active) == 22
    assert len(superseded) == audit["superseded_source_count"] == 4
    assert set(provenance.source_provider) == {"KRX"}
    assert set(provenance.retrieval_status) == {"SUCCESS"}
    assert not set(active.source_file) & set(superseded.source_file)
    for row in provenance.itertuples(index=False):
        raw = ROOT / row.source_file
        normalized = ROOT / row.normalized_file
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == row.sha256
        assert hashlib.sha256(normalized.read_bytes()).hexdigest() == row.normalized_sha256


def test_active_normalized_snapshots_preserve_canonical_metrics_and_existing_crosscheck():
    provenance = pd.read_csv(PROVENANCE, dtype=str).fillna("")
    active = provenance[provenance.reference_status.eq("ACTIVE_REFERENCE")]
    expected_columns = ["ticker", "name", "raw_market", "market", "close", "volume", "trading_value", "market_cap", "shares_outstanding", "effective_date"]
    for row in active.itertuples(index=False):
        frame = pd.read_csv(ROOT / row.normalized_file, dtype={"ticker": str})
        assert frame.columns.tolist() == expected_columns
        assert frame.ticker.str.len().eq(6).all() and frame.ticker.is_unique
        assert set(frame.market) <= {"KOSPI", "KOSDAQ", "KONEX", "OTHER"}
        assert (pd.to_numeric(frame.market_cap) > 0).all()
        assert (pd.to_numeric(frame.shares_outstanding) > 0).all()
        assert frame.effective_date.nunique() == 1 and frame.effective_date.iloc[0] == row.effective_date
    assert _audit()["existing_20250131_crosscheck"]["comparison_status"] == "PASS"
    assert len(pd.read_csv(HISTORY / "krx_historical_market_cap_crosscheck_anomalies_v01.csv")) == 0


def test_no_substitution_or_interpolation_and_phase10_inputs_are_unchanged():
    audit = _audit()
    assert audit["current_market_cap_substitution_used"] is False
    assert audit["future_shares_substitution_used"] is False
    assert audit["market_cap_interpolation_used"] is False
    assert audit["third_party_market_data_used"] is False
    assert audit["sample_generated_count"] == 0 and audit["oos_evaluation_executed"] is False
    protected = [
        "artifacts/investability/source/krx_market_cap_20250131.csv", "artifacts/investability/source/krx_market_cap_20260814.csv",
        "artifacts/pattern_a_fast/oos", "artifacts/pattern_a_fast/human_anchors", "artifacts/pattern_a_fast/ground_truth",
        "artifacts/pattern_a_fast/research", "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_historical_investability_pit_audit_v01.json",
        "scripts/evaluate_pattern_a_fast_oos_v01.py", "scripts/research_pattern_a_fast_lead_time_failure.py",
        "scripts/research_pattern_a_fast_score_stage_prototype.py", "docs/roadmap.md",
    ]
    assert subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False).returncode == 0
