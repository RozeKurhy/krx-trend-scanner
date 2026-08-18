"""Phase 13J-0 KRX-only historical market-cap PIT source integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "cb2aba5d680c2f5e770ef9441e2e781d82a8cb2e"
HISTORY = ROOT / "artifacts/investability/history"
AUDIT = HISTORY / "krx_historical_market_cap_backfill_audit_v01.json"
GRID = HISTORY / "krx_market_cap_reference_grid_v01.csv"
PROVENANCE = HISTORY / "krx_historical_market_cap_provenance_v01.csv"
EXPECTED_CANDIDATES = [
    "2020-03-27", "2020-06-26", "2020-09-25", "2020-12-25",
    "2021-03-26", "2021-06-25", "2021-09-24", "2021-12-31",
    "2022-03-25", "2022-06-24", "2022-09-30", "2022-12-30",
    "2023-03-31", "2023-06-30", "2023-09-22", "2023-12-29",
    "2024-03-29", "2024-06-28", "2024-09-27", "2024-12-27",
    "2025-03-28", "2025-06-27",
]


def _audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_all_22_krx_reference_mappings_are_exactly_covered_and_pit_safe():
    audit = _audit()
    grid = pd.read_csv(GRID, dtype=str)
    assert audit["status"] == "HISTORICAL_MARKET_CAP_PIT_READY"
    assert audit["all_reference_dates_covered"] is True
    assert (audit["reference_candidate_count"], audit["resolved_reference_count"], audit["successful_snapshot_count"]) == (22, 22, 22)
    assert audit["failed_snapshot_count"] == audit["review_required_count"] == 0
    assert grid.calendar_candidate_date.tolist() == EXPECTED_CANDIDATES
    assert len(grid) == 22
    assert (grid.effective_date <= grid.calendar_candidate_date).all()
    assert grid.date_resolution_status.isin(["EXACT_TRADING_DATE", "HOLIDAY_FALLBACK"]).all()
    assert grid.loc[grid.calendar_candidate_date.eq("2020-12-25"), "effective_date"].item() == "2020-12-24"
    assert grid.loc[grid.calendar_candidate_date.eq("2021-12-31"), "effective_date"].item() == "2021-12-30"
    assert grid.loc[grid.calendar_candidate_date.eq("2022-12-30"), "effective_date"].item() == "2022-12-29"
    assert grid.loc[grid.calendar_candidate_date.eq("2023-12-29"), "effective_date"].item() == "2023-12-28"


def test_sources_are_krx_only_immutable_and_hash_sealed():
    audit = _audit()
    provenance = pd.read_csv(PROVENANCE, dtype=str)
    assert audit["provider"] == "KRX"
    assert audit["network_provider"] == "KRX_ONLY"
    assert audit["source_product"] == "ALL_STOCK_MARKET_DATA"
    assert audit["source_screen_id"] == "MDC0201020101"
    assert audit["third_party_market_data_used"] is False
    assert audit["network_request_count"] == 29
    assert len(provenance) == 22
    assert set(provenance.source_provider) == {"KRX"}
    assert set(provenance.retrieval_status) == {"SUCCESS"}
    for row in provenance.itertuples(index=False):
        raw = ROOT / row.source_file
        normalized = ROOT / row.normalized_file
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == row.sha256
        assert hashlib.sha256(normalized.read_bytes()).hexdigest() == row.normalized_sha256


def test_normalized_snapshots_preserve_historical_market_identity_and_canonical_metrics():
    provenance = pd.read_csv(PROVENANCE, dtype=str)
    expected_columns = ["ticker", "name", "raw_market", "market", "close", "volume", "trading_value", "market_cap", "shares_outstanding", "effective_date"]
    for row in provenance.itertuples(index=False):
        frame = pd.read_csv(ROOT / row.normalized_file, dtype={"ticker": str})
        assert frame.columns.tolist() == expected_columns
        assert frame.ticker.str.len().eq(6).all()
        assert frame.ticker.is_unique
        assert set(frame.market) <= {"KOSPI", "KOSDAQ", "KONEX", "OTHER"}
        assert (pd.to_numeric(frame.market_cap) > 0).all()
        assert (pd.to_numeric(frame.shares_outstanding) > 0).all()
        assert frame.effective_date.nunique() == 1
        assert frame.effective_date.iloc[0] == row.effective_date
    assert _audit()["existing_20250131_crosscheck"]["comparison_status"] == "PASS"
    assert len(pd.read_csv(HISTORY / "krx_historical_market_cap_crosscheck_anomalies_v01.csv")) == 0


def test_no_substitution_interpolation_or_oos_work_and_protected_inputs_are_unchanged():
    audit = _audit()
    assert audit["current_market_cap_substitution_used"] is False
    assert audit["future_shares_substitution_used"] is False
    assert audit["market_cap_interpolation_used"] is False
    assert audit["sample_generated_count"] == 0
    assert audit["oos_evaluation_executed"] is False
    forbidden = [
        "pattern_a_fast_investable_oos_selection_manifest_v01.csv",
        "pattern_a_fast_investable_oos_human_review_v01.csv",
        "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv",
        "pattern_a_fast_investable_oos_evaluation_protocol_v01.json",
        "pattern_a_fast_investable_oos_preregistration_seal_v01.json",
        "charts/stage_blind", "charts/outcome_blind",
    ]
    investable_oos = ROOT / "artifacts/pattern_a_fast/investable_oos"
    assert not any((investable_oos / item).exists() for item in forbidden)
    protected = [
        "artifacts/investability/source/krx_market_cap_20250131.csv",
        "artifacts/investability/source/krx_market_cap_20260814.csv",
        "artifacts/pattern_a_fast/oos", "artifacts/pattern_a_fast/human_anchors",
        "artifacts/pattern_a_fast/ground_truth", "artifacts/pattern_a_fast/research",
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_historical_investability_pit_audit_v01.json",
        "scripts/evaluate_pattern_a_fast_oos_v01.py", "scripts/research_pattern_a_fast_lead_time_failure.py",
        "scripts/research_pattern_a_fast_score_stage_prototype.py", "docs/roadmap.md",
    ]
    result = subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False)
    assert result.returncode == 0
