"""Phase 13J-1 Investable OOS-B preregistration integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "aae2db99beebcbfe518fd614e2ab650dc432e569"
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
HISTORY = ROOT / "artifacts/investability/history"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_investable_oos_preregistration_seal_v01.json"
SCRIPT = ROOT / "scripts/prepare_pattern_a_fast_investable_oos_v01.py"


def _seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(ASSETS, dtype=str, keep_default_na=False),
    )


def test_frozen_krx_inputs_and_phase10_pit_investability_contract_are_exact():
    seal, grid = _seal(), pd.read_csv(HISTORY / "krx_market_cap_reference_grid_v01.csv", dtype=str)
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
    assert seal["historical_market_cap_audit_sha256"] == hashlib.sha256((HISTORY / "krx_historical_market_cap_backfill_audit_v01.json").read_bytes()).hexdigest()


def test_sample_freeze_meets_all_quotas_firewalls_and_diversity_constraints():
    seal, manifest, _, _ = _seal(), *_frames()
    expected = {"ADVANCED_CANDIDATE": 10, "SETUP_CANDIDATE": 10, "WATCH_HIGH_SCORE": 8, "EXTENDED_CONTROL": 4, "WATCH_LOW_SCORE_CONTROL": 4}
    assert seal["status"] == "READY_FOR_BLIND_HUMAN_INVESTABLE_OOS_LABELING"
    assert len(manifest) == seal["sample_actual"] == 36
    assert manifest.sample_id.tolist() == [f"INV_OOS_B_{i:03d}" for i in range(1, 37)]
    assert manifest.ticker.nunique() == 36 and not manifest.prior_60_ticker_overlap.any() and not manifest.human_positive_anchor_overlap.any()
    assert manifest.sampling_stratum.value_counts().to_dict() == expected == seal["stratum_actual_counts"]
    assert manifest.reference_quarter.nunique() >= 10
    assert manifest.completed_weekly_reference_date.value_counts().max() <= 3
    assert manifest.historical_market.value_counts().max() <= 2 * len(manifest) // 3
    assert set(manifest.historical_market) <= {"KOSPI", "KOSDAQ"}
    assert manifest.market_cap_at_reference.astype(float).ge(seal["phase10_market_cap_threshold"]).all()
    assert manifest.avg_trading_value_20d_at_reference.astype(float).ge(seal["phase10_avg_trading_value_20d_threshold"]).all()
    assert manifest.investability_status.eq("INVESTABLE").all()
    assert manifest.machine_stage_status.eq("READY").all()
    assert manifest.effective_as_of.le(manifest.completed_weekly_reference_date).all()
    assert manifest.monthly_as_of.le(manifest.completed_weekly_reference_date).all()
    assert manifest.weekly_as_of.eq(manifest.completed_weekly_reference_date).all()
    watch = manifest[manifest.sampling_stratum.str.startswith("WATCH_")]
    assert watch.fast_score_status.isin(["READY", "PARTIAL"]).all()
    assert watch.watch_score_percentile.notna().all()
    assert manifest.human_review_exposed.eq(False).all()


def test_human_sheet_and_blind_assets_do_not_expose_machine_outputs_or_labels():
    seal, manifest, review, assets = _seal(), *_frames()
    forbidden = {"machine_stage", "fast_score", "sampling_stratum", "watch_score_percentile", "selection_hash", "pattern_a"}
    assert not forbidden & set(review.columns)
    assert len(review) == len(manifest) and review.sample_id.nunique() == len(review)
    assert review.review_order.astype(int).tolist() == list(range(1, len(review) + 1))
    assert review.human_stage.eq("UNLABELED").all() and review.human_stage_confidence.eq("UNLABELED").all()
    assert review.human_trigger_event_observed.eq("UNLABELED").all() and review.human_trigger_event_date.eq("").all()
    assert review.stage_review_status.eq("PENDING").all()
    assert review.human_outcome_label.eq("UNLABELED").all() and review.human_outcome_confidence.eq("UNLABELED").all()
    assert review.outcome_review_status.eq("PENDING").all()
    assert len(assets) == 4 * len(manifest)
    assert (assets.groupby("sample_id").size() == 4).all()
    assert (assets.loc[assets.human_exposure_phase.eq("PASS_A"), "asset_type"].isin(["MONTHLY_STAGE_BLIND", "WEEKLY_STAGE_BLIND", "DAILY_STAGE_BLIND"])).all()
    assert assets.human_exposure_phase.eq("PASS_A").sum() == seal["stage_blind_chart_count"] == 3 * len(manifest)
    assert assets.human_exposure_phase.eq("PASS_B_AFTER_STAGE_FREEZE").sum() == seal["outcome_blind_chart_count"] == len(manifest)
    for row in assets.itertuples(index=False):
        path = ROOT / row.file_path
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row.sha256
        assert row.data_end <= row.reference_date if row.human_exposure_phase == "PASS_A" else row.data_start >= row.reference_date


def test_protocol_and_seal_are_hash_bound_and_pre_label_pre_evaluation():
    seal, protocol = _seal(), json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["claim_boundary"] == "retrospective historical OOS with preregistered blind human review"
    assert protocol["primary_score_comparison"]["positive_labels"] == ["GOOD_TRIGGER", "BORDERLINE_TRIGGER"]
    assert protocol["primary_score_comparison"]["negative_labels"] == ["TOO_EARLY", "NO_SETUP"]
    assert protocol["primary_score_comparison"]["minimum_n_per_group"] == 5
    assert protocol["primary_score_comparison"]["cliffs_delta_hard_threshold"] is None
    assert protocol["stage_exact_match_hard_threshold"] is None
    assert protocol["lead_minimum_clean_n"] == 3
    assert protocol["stage_ready_coverage_minimum"] == 0.80 and protocol["score_unavailable_rate_maximum"] == 0.20
    assert protocol["no_sample_replacement_after_freeze"] is True
    for key, path in {"selection_manifest_sha256": MANIFEST, "human_review_sha256": REVIEW, "blind_asset_manifest_sha256": ASSETS, "evaluation_protocol_sha256": PROTOCOL}.items():
        assert seal[key] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert seal["human_machine_outputs_exposed"] is False
    assert seal["human_review_started"] is False
    assert seal["human_stage_labels_present"] is False and seal["human_outcome_labels_present"] is False
    assert seal["oos_evaluation_executed"] is False and seal["retuning_performed"] is False
    assert seal["network_market_request_count"] == 0


def test_sampling_is_local_pit_only_and_protected_inputs_are_unchanged():
    source = SCRIPT.read_text(encoding="utf-8")
    selection = source[source.index("def collect_candidates"):source.index("def assign_strata")]
    assert "evaluate_investability" in selection and "daily.index <=" in source
    assert "MarketDataRepository" not in source and not any(token in source for token in ("requests", "urllib", "yfinance", "pykrx"))
    assert "outcome_review_end" not in selection and "human_label" not in selection and "pattern_a" not in selection
    protected = [
        "artifacts/investability/history", "artifacts/investability/source/krx_market_cap_20250131.csv", "artifacts/investability/source/krx_market_cap_20260814.csv",
        "artifacts/pattern_a_fast/oos", "artifacts/pattern_a_fast/human_anchors", "artifacts/pattern_a_fast/ground_truth", "artifacts/pattern_a_fast/research",
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_historical_investability_pit_audit_v01.json",
        "scripts/evaluate_pattern_a_fast_oos_v01.py", "scripts/research_pattern_a_fast_lead_time_failure.py", "scripts/research_pattern_a_fast_score_stage_prototype.py", "docs/roadmap.md",
    ]
    assert subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False).returncode == 0
