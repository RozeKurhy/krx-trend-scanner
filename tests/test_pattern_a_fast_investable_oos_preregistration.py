"""Phase 13J-1 frozen OOS-B package and blind review mapping integrity tests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from scripts.prepare_pattern_a_fast_investable_oos_v01 import outcome_chart_title, stage_chart_title

from tests.helpers.frozen_integrity import (
    EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256,
    RESEARCH_LEAD_TIME_FAILURE_SCRIPT_SHA256,
    RESEARCH_SCORE_STAGE_PROTOTYPE_SCRIPT_SHA256,
    SOURCE_MARKET_CAP_20250131_SHA256,
    SOURCE_MARKET_CAP_20260814_SHA256,
    assert_file_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = "aae2db99beebcbfe518fd614e2ab650dc432e569"  # Phase 13J-1 freeze reference commit (역사적 참조용, 더 이상 git diff 대상 아님 -- FIX_03)
OOS = ROOT / "artifacts/patterns/pattern_a_fast/validation/investable_oos"
HISTORY = ROOT / "artifacts/patterns/pattern_a/validation/investability_history"
SOURCE = ROOT / "artifacts/patterns/pattern_a/production/investability/source"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_investable_oos_preregistration_seal_v01.json"
SCRIPT = ROOT / "scripts/prepare_pattern_a_fast_investable_oos_v01.py"

FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_HUMAN_REVIEW_SHA256 = "25d5f524517c7eabe6ab232e5ba97964ff00aae06f59a4362ba49cb5f78c99d1"
FROZEN_EVALUATION_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False),
    )


def test_frozen_krx_inputs_phase10_contract_and_protected_inputs_are_unchanged():
    """TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_03: this used to
    `git diff --quiet BASE -- protected` over whole directories
    (artifacts/patterns/pattern_a/validation/investability_history, artifacts/patterns/pattern_a/production/investability/source,
    artifacts/pattern_a_fast/{oos,human_anchors,ground_truth,research}), which
    treats any later legitimate addition under those paths as a frozen-
    evidence violation ("directory unchanged since BASE" instead of
    "preregistered exact frozen inputs unchanged", per design). The
    provenance-tracked historical files under artifacts/patterns/pattern_a/validation/investability_history/
    are already row-level sha256 sealed in
    test_active_and_superseded_sources_are_krx_only_hash_sealed_and_unambiguous
    (test_krx_historical_market_cap_backfill.py); the ground_truth/research/oos/
    human_anchors directories carry no additional frozen claim beyond what is
    already sha256-sealed elsewhere (test_pattern_a_fast_lead_time_failure_analysis.py's
    4-file frozen allowlist). What this test uniquely claims to protect -- the
    two canonical PIT market-cap snapshots and the 3 scripts -- is now checked
    by explicit sha256 instead.
    """
    seal = _seal()
    grid = pd.read_csv(HISTORY / "krx_market_cap_reference_grid_v01.csv", dtype=str)
    audit = json.loads((HISTORY / "krx_historical_market_cap_backfill_audit_v01.json").read_text())
    provenance = pd.read_csv(HISTORY / "krx_historical_market_cap_provenance_v01.csv", dtype=str).fillna("")
    assert (audit["status"], audit["reference_date_semantics"]) == ("HISTORICAL_MARKET_CAP_PIT_READY", "BUILD_HISTORICAL_SNAPSHOT_COMPLETED_W_FRI")
    assert len(grid) == audit["active_reference_count"] == 22
    assert (grid.completed_weekly_reference_date == grid.effective_date).all()
    assert len(provenance[provenance.reference_status.eq("ACTIVE_REFERENCE")]) == 22
    assert len(provenance[provenance.reference_status.eq("SUPERSEDED_NON_REFERENCE_SOURCE")]) == 4
    assert seal["phase10_market_cap_threshold"] == 100_000_000_000.0
    assert seal["phase10_avg_trading_value_20d_threshold"] == 300_000_000.0
    assert seal["phase10_close_filter"] == "NONE"
    assert_file_sha256(SOURCE / "krx_market_cap_20250131.csv", SOURCE_MARKET_CAP_20250131_SHA256)
    assert_file_sha256(SOURCE / "krx_market_cap_20260814.csv", SOURCE_MARKET_CAP_20260814_SHA256)
    assert_file_sha256(ROOT / "scripts/evaluate_pattern_a_fast_oos_v01.py", EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256)
    assert_file_sha256(ROOT / "scripts/research_pattern_a_fast_lead_time_failure.py", RESEARCH_LEAD_TIME_FAILURE_SCRIPT_SHA256)
    assert_file_sha256(ROOT / "scripts/research_pattern_a_fast_score_stage_prototype.py", RESEARCH_SCORE_STAGE_PROTOTYPE_SCRIPT_SHA256)


def test_sample_and_protocol_freezes_are_byte_exact_while_the_human_template_seal_is_preserved():
    seal, manifest, review, _ = _seal(), *_frames()
    assert _sha256(MANIFEST) == FROZEN_SELECTION_SHA256 == seal["selection_manifest_sha256"]
    # The preregistration seal preserves the original blank PASS A template. Phase
    # 13J-2 writes authorized Human fields and seals that new CSV separately.
    assert seal["human_review_sha256"] == FROZEN_HUMAN_REVIEW_SHA256
    assert _sha256(PROTOCOL) == FROZEN_EVALUATION_PROTOCOL_SHA256 == seal["evaluation_protocol_sha256"]
    assert len(manifest) == manifest.ticker.nunique() == 36
    assert manifest.sample_id.tolist() == [f"INV_OOS_B_{number:03d}" for number in range(1, 37)]
    assert manifest.selection_hash.nunique() == 36
    assert review.review_order.astype(int).tolist() == list(range(1, 37))
    assert review.sample_id.nunique() == 36
    # The preregistration seal preserves the original blank PASS B template.
    # Phase 13J-3 seals authorized outcome fields in a separate GT checkpoint.
    assert review.human_trigger_event_date.eq("").all()
    assert seal["human_review_started"] is False
    assert seal["human_stage_labels_present"] is False and seal["human_outcome_labels_present"] is False
    assert seal["oos_evaluation_executed"] is False and seal["retuning_performed"] is False
    assert seal["network_market_request_count"] == 0


def test_review_order_to_asset_mapping_is_exact_and_all_asset_counts_are_complete():
    seal, manifest, review, assets = _seal(), *_frames()
    assert "review_order" in assets.columns
    review_mapping = review[["review_order", "sample_id"]].astype({"review_order": int}).sort_values("review_order").reset_index(drop=True)
    asset_mapping = assets[["review_order", "sample_id"]].drop_duplicates().astype({"review_order": int}).sort_values("review_order").reset_index(drop=True)
    pd.testing.assert_frame_equal(review_mapping, asset_mapping)
    assert len(asset_mapping) == len(review_mapping) == len(manifest) == 36
    assert (assets.groupby("review_order").size() == 4).all()
    assert (assets.groupby("sample_id").size() == 4).all()
    mapping_payload = "\n".join(f"{row.review_order}|{row.sample_id}" for row in review_mapping.itertuples(index=False))
    assert seal["review_asset_mapping_status"] == "EXACT"
    assert seal["review_order_sample_mapping_sha256"] == hashlib.sha256(mapping_payload.encode("utf-8")).hexdigest()


def test_chart_filenames_titles_and_boundaries_follow_the_frozen_review_mapping_without_stale_pngs():
    seal, _, review, assets = _seal(), *_frames()
    stage = assets[assets.human_exposure_phase.eq("PASS_A")]
    outcome = assets[assets.human_exposure_phase.eq("PASS_B_AFTER_STAGE_FREEZE")]
    assert len(stage) == seal["stage_blind_chart_count"] == 108
    assert len(outcome) == seal["outcome_blind_chart_count"] == 36
    expected_stage_paths, expected_outcome_paths = set(), set()
    review_by_sample = review.set_index("sample_id")
    for row in assets.itertuples(index=False):
        path = ROOT / row.file_path.replace("artifacts/pattern_a_fast/", "artifacts/patterns/pattern_a_fast/validation/")
        assert path.is_file() and _sha256(path) == row.sha256
        prefix = f"{int(row.review_order):03d}_{row.sample_id}_"
        assert path.name.startswith(prefix)
        if row.human_exposure_phase == "PASS_A":
            assert re.fullmatch(rf"{int(row.review_order):03d}_{row.sample_id}_(monthly|weekly|daily)\.png", path.name)
            assert row.data_end <= row.reference_date
            expected_stage_paths.add(path)
        else:
            assert path.name == f"{int(row.review_order):03d}_{row.sample_id}_outcome.png"
            assert row.data_start >= row.reference_date
            expected_outcome_paths.add(path)
    assert set((OOS / "charts/stage_blind").glob("*.png")) == expected_stage_paths
    assert set((OOS / "charts/outcome_blind").glob("*.png")) == expected_outcome_paths
    first = review_by_sample.loc[review.iloc[0].sample_id]
    assert stage_chart_title(int(first.review_order), first, pd.Timestamp(first.reference_date)) == (
        f"OOS-B Review {int(first.review_order):03d} | {first.ticker} {first['name']} | as of {first.reference_date}"
    )
    assert outcome_chart_title(int(first.review_order), first) == f"OOS-B Outcome Review {int(first.review_order):03d} | {first.ticker} {first['name']}"


def test_asset_seal_is_hash_bound_and_generator_remains_local_only_without_resampling():
    seal = _seal()
    source = SCRIPT.read_text(encoding="utf-8")
    assert seal["blind_asset_manifest_sha256"] == _sha256(ASSETS)
    assert "def frozen_package" in source and "def ordered_review_samples" in source
    assert "validate=\"one_to_one\"" in source and "generate_assets(samples, review)" in source
    assert "MarketDataRepository" not in source and not any(token in source for token in ("requests", "urllib", "yfinance", "pykrx"))
    assert "collect_candidates()" not in source[source.index("def main"):]
    assert seal["status"] == "READY_FOR_BLIND_HUMAN_INVESTABLE_OOS_LABELING"
