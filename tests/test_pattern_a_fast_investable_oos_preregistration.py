"""Phase 13J-1 strict-PIT block integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "0f460fa0132956296b3e6b003053a05acf019538"
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
AUDIT = OOS / "pattern_a_fast_investable_oos_historical_investability_pit_audit_v01.json"
SCRIPT = ROOT / "scripts/prepare_pattern_a_fast_investable_oos_v01.py"


def _audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_historical_market_cap_pit_is_blocked_without_substitution():
    report = _audit()
    assert report["status"] == "HISTORICAL_INVESTABILITY_PIT_BLOCKED"
    assert report["calendar_quarter_reference_candidate_count"] == 22
    assert report["exact_completed_week_grid_status"] == "NOT_DERIVABLE_FOR_FULL_PERIOD_FROM_LOCAL_CACHE"
    assert len(report["missing_market_cap_calendar_candidates"]) == 22
    assert report["available_market_cap_effective_dates"] == ["2025-01-31", "2026-08-14"]
    assert report["raw_ohlcv_cache"]["contains_market_cap"] is False
    assert report["raw_ohlcv_cache"]["contains_shares_outstanding"] is False
    assert "current_market_cap" in report["prohibited_substitutions_not_used"]
    assert "future_shares_outstanding" in report["prohibited_substitutions_not_used"]


def test_blocked_phase_creates_no_sample_or_human_or_evaluation_outputs():
    report = _audit()
    assert report["sample_generated_count"] == 0
    assert report["human_stage_review_started"] is False
    assert report["human_outcome_review_started"] is False
    assert report["oos_evaluation_executed"] is False
    assert report["network_market_request_count"] == 0
    forbidden = [
        "pattern_a_fast_investable_oos_selection_manifest_v01.csv",
        "pattern_a_fast_investable_oos_human_review_v01.csv",
        "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv",
        "pattern_a_fast_investable_oos_evaluation_protocol_v01.json",
        "pattern_a_fast_investable_oos_preregistration_seal_v01.json",
        "charts/stage_blind",
        "charts/outcome_blind",
    ]
    assert not any((OOS / path).exists() for path in forbidden)


def test_audit_is_local_only_reproducible_and_its_source_files_are_hashed():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "pd.read_parquet" in source
    assert not [token for token in ("requests", "urllib", "pykrx", "yfinance", "MarketDataRepository") if token in source]
    for item in _audit()["local_market_cap_sources"]:
        path = ROOT / item["file_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_frozen_oos_a_and_phase_13i_2_are_unchanged():
    protected = [
        "artifacts/pattern_a_fast/oos",
        "artifacts/pattern_a_fast/human_anchors",
        "artifacts/pattern_a_fast/ground_truth",
        "artifacts/pattern_a_fast/research",
        "scripts/research_pattern_a_fast_lead_time_failure.py",
        "scripts/research_pattern_a_fast_score_stage_prototype.py",
        "scripts/evaluate_pattern_a_fast_oos_v01.py",
        "docs/roadmap.md",
    ]
    result = subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False)
    assert result.returncode == 0
