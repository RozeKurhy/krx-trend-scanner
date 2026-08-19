"""Phase 13J-3 PASS B Human outcome ground-truth freeze integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "f6b6448c280706e1e2d17d19809f369ac3feea95"
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
PASS_A_SEAL = OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json"
GROUND_TRUTH_SEAL = OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json"
SCRIPT = ROOT / "scripts/freeze_pattern_a_fast_investable_oos_human_ground_truth_v01.py"

PRE_PASS_B_SHA256 = "2a1c3cf172664f168e6e1c115bf242aabd5e342da8e73e44b0832690680fd5f4"
PASS_A_SEAL_SHA256 = "4c908daa5ab803ccbf20f355027391aaa3f2d63c31e3f60ac60df6e34b9201ea"
FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_ASSET_SHA256 = "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe"
FROZEN_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
FROZEN_MAPPING_SHA256 = "6d861d3b86f9c1e0fa4e7e48c1d59c385c3e089c05608fd45151536ab5c6b40b"

# Authoritative user-provided PASS B result: order, sample_id, ticker, outcome, confidence.
EXPECTED_OUTCOMES = [
    (1, "INV_OOS_B_002", "281740", "GOOD_TRIGGER", "HIGH"),
    (2, "INV_OOS_B_004", "064350", "BORDERLINE_TRIGGER", "MEDIUM"),
    (3, "INV_OOS_B_030", "010620", "BORDERLINE_TRIGGER", "MEDIUM"),
    (4, "INV_OOS_B_024", "004020", "TOO_EARLY", "HIGH"),
    (5, "INV_OOS_B_031", "270520", "NO_SETUP", "HIGH"),
    (6, "INV_OOS_B_007", "036710", "FALSE_TRIGGER", "HIGH"),
    (7, "INV_OOS_B_005", "000720", "TOO_LATE", "HIGH"),
    (8, "INV_OOS_B_008", "200130", "NO_SETUP", "HIGH"),
    (9, "INV_OOS_B_023", "125210", "FALSE_TRIGGER", "HIGH"),
    (10, "INV_OOS_B_010", "022100", "TOO_EARLY", "HIGH"),
    (11, "INV_OOS_B_009", "402030", "FALSE_TRIGGER", "HIGH"),
    (12, "INV_OOS_B_018", "033780", "GOOD_TRIGGER", "HIGH"),
    (13, "INV_OOS_B_006", "138040", "TOO_LATE", "HIGH"),
    (14, "INV_OOS_B_034", "005850", "TOO_EXTENDED", "HIGH"),
    (15, "INV_OOS_B_028", "217330", "FALSE_TRIGGER", "HIGH"),
    (16, "INV_OOS_B_016", "256940", "BORDERLINE_TRIGGER", "MEDIUM"),
    (17, "INV_OOS_B_022", "010140", "GOOD_TRIGGER", "HIGH"),
    (18, "INV_OOS_B_027", "084370", "TOO_EARLY", "HIGH"),
    (19, "INV_OOS_B_033", "018880", "NO_SETUP", "HIGH"),
    (20, "INV_OOS_B_035", "222080", "TOO_EARLY", "HIGH"),
    (21, "INV_OOS_B_011", "048410", "NO_SETUP", "HIGH"),
    (22, "INV_OOS_B_012", "214320", "FALSE_TRIGGER", "HIGH"),
    (23, "INV_OOS_B_003", "060230", "NO_SETUP", "HIGH"),
    (24, "INV_OOS_B_029", "002350", "TOO_EARLY", "HIGH"),
    (25, "INV_OOS_B_013", "119830", "TOO_EARLY", "HIGH"),
    (26, "INV_OOS_B_020", "271560", "TOO_EARLY", "HIGH"),
    (27, "INV_OOS_B_021", "214150", "BORDERLINE_TRIGGER", "MEDIUM"),
    (28, "INV_OOS_B_001", "178920", "TOO_EARLY", "HIGH"),
    (29, "INV_OOS_B_026", "101530", "BORDERLINE_TRIGGER", "MEDIUM"),
    (30, "INV_OOS_B_015", "079940", "GOOD_TRIGGER", "HIGH"),
    (31, "INV_OOS_B_025", "028050", "BORDERLINE_TRIGGER", "MEDIUM"),
    (32, "INV_OOS_B_019", "051900", "NO_SETUP", "HIGH"),
    (33, "INV_OOS_B_036", "086520", "GOOD_TRIGGER", "HIGH"),
    (34, "INV_OOS_B_032", "005180", "TOO_EXTENDED", "HIGH"),
    (35, "INV_OOS_B_017", "074600", "BORDERLINE_TRIGGER", "MEDIUM"),
    (36, "INV_OOS_B_014", "053080", "TOO_EXTENDED", "HIGH"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review() -> pd.DataFrame:
    return pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)


def _seal() -> dict:
    return json.loads(GROUND_TRUTH_SEAL.read_text(encoding="utf-8"))


def test_authoritative_outcome_rows_distributions_and_complete_status_are_exact():
    review = _review()
    actual = review[["review_order", "sample_id", "ticker", "human_outcome_label", "human_outcome_confidence"]].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.str.zfill(6)
    expected = pd.DataFrame(EXPECTED_OUTCOMES, columns=actual.columns)
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected)
    assert review.outcome_review_status.eq("COMPLETE").all()
    assert review.human_outcome_label.value_counts().to_dict() == {
        "TOO_EARLY": 8, "BORDERLINE_TRIGGER": 7, "NO_SETUP": 6,
        "GOOD_TRIGGER": 5, "FALSE_TRIGGER": 5, "TOO_EXTENDED": 3, "TOO_LATE": 2,
    }
    assert review.human_outcome_confidence.value_counts().to_dict() == {"HIGH": 29, "MEDIUM": 7}


def test_pass_a_stage_trigger_and_frozen_identity_are_unchanged():
    review = _review()
    assert review.human_stage.value_counts().to_dict() == {"WATCH": 16, "SETUP": 14, "TREND": 3, "EXTENDED": 3}
    assert review.human_stage_confidence.value_counts().to_dict() == {"HIGH": 25, "MEDIUM": 9, "LOW": 2}
    assert review.human_trigger_event_observed.eq("NO").all() and review.human_trigger_event_date.eq("").all()
    assert review.stage_review_status.eq("COMPLETE").all()
    manifest = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    assets = pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False)
    frozen = assets[["review_order", "sample_id"]].drop_duplicates().merge(
        manifest[["sample_id", "ticker", "name", "historical_market", "completed_weekly_reference_date", "outcome_review_end"]],
        on="sample_id", validate="one_to_one",
    ).rename(columns={"completed_weekly_reference_date": "reference_date"})
    fields = ["review_order", "sample_id", "ticker", "name", "historical_market", "reference_date", "outcome_review_end"]
    actual = review[fields].copy(); actual["review_order"] = actual.review_order.astype(int); actual["ticker"] = actual.ticker.str.zfill(6)
    frozen = frozen[fields].copy(); frozen["review_order"] = frozen.review_order.astype(int); frozen["ticker"] = frozen.ticker.str.zfill(6)
    pd.testing.assert_frame_equal(actual.sort_values("review_order").reset_index(drop=True), frozen.sort_values("review_order").reset_index(drop=True))


def test_ground_truth_seal_binds_pass_b_csv_and_all_prior_frozen_inputs():
    review, seal = _review(), _seal()
    mapping = "\n".join(f"{int(row.review_order)}|{row.sample_id}" for row in review[["review_order", "sample_id"]].itertuples(index=False))
    assert seal["status"] == "HUMAN_OUTCOME_PASS_B_GROUND_TRUTH_FROZEN"
    assert seal["base_commit"] == BASE
    assert seal["pre_pass_b_human_review_sha256"] == PRE_PASS_B_SHA256
    assert seal["post_pass_b_human_review_sha256"] == _sha256(REVIEW)
    assert seal["pass_a_freeze_seal_sha256"] == PASS_A_SEAL_SHA256 == _sha256(PASS_A_SEAL)
    assert seal["selection_manifest_sha256"] == FROZEN_SELECTION_SHA256 == _sha256(MANIFEST)
    assert seal["blind_asset_manifest_sha256"] == FROZEN_ASSET_SHA256 == _sha256(ASSETS)
    assert seal["evaluation_protocol_sha256"] == FROZEN_PROTOCOL_SHA256 == _sha256(PROTOCOL)
    assert seal["review_order_sample_mapping_sha256"] == FROZEN_MAPPING_SHA256 == hashlib.sha256(mapping.encode("utf-8")).hexdigest()
    assert (seal["sample_count"], seal["stage_complete_count"], seal["outcome_complete_count"], seal["outcome_pending_count"]) == (36, 36, 36, 0)
    assert seal["outcome_distribution"] == {"GOOD_TRIGGER": 5, "BORDERLINE_TRIGGER": 7, "FALSE_TRIGGER": 5, "TOO_EARLY": 8, "TOO_LATE": 2, "TOO_EXTENDED": 3, "NO_SETUP": 6}
    assert seal["outcome_confidence_distribution"] == {"LOW": 0, "MEDIUM": 7, "HIGH": 29}


def test_charts_pass_a_seal_and_non_evaluation_boundaries_remain_unchanged():
    assets = pd.read_csv(ASSETS, dtype=str, keep_default_na=False)
    assert len(assets[assets.human_exposure_phase.eq("PASS_A")]) == 108
    assert len(assets[assets.human_exposure_phase.eq("PASS_B_AFTER_STAGE_FREEZE")]) == 36
    for asset in assets.itertuples(index=False):
        assert _sha256(ROOT / asset.file_path) == asset.sha256
    protected = [
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json",
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_selection_manifest_v01.csv",
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv",
        "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_evaluation_protocol_v01.json",
        "artifacts/pattern_a_fast/investable_oos/charts",
        # HistoricalSnapshot's post-freeze PIT raw-frame exposure is verified
        # by the final-closure source identity gate. Keep the actual frozen
        # Pattern A model implementation protected here.
        "src/trend_scanner/patterns/pattern_a_evaluator.py",
        "src/trend_scanner/patterns/pattern_a_feature_set.py",
        "src/trend_scanner/patterns/pattern_a_score.py",
        "src/trend_scanner/patterns/pattern_a_stage.py",
        "scripts/evaluate_pattern_a_fast_oos_v01.py",
        # docs/roadmap.md is a living project document, not frozen research
        # evidence; it is expected to evolve after PHASE_13_RESEARCH_CLOSED.
    ]
    assert subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False).returncode == 0
    seal = _seal()
    assert seal["pass_a_stage_mutation"] is False and seal["sample_mutation"] is False and seal["resampling_performed"] is False
    assert seal["machine_outputs_exposed_to_human"] is False and seal["oos_evaluation_executed"] is False and seal["retuning_performed"] is False
    assert seal["outcome_window_exposed_to_human"] is True and seal["network_market_request_count"] == 0
    source = SCRIPT.read_text(encoding="utf-8")
    assert not any(token in source for token in ("requests", "urllib", "yfinance", "pykrx", "evaluate_pattern", "to_weekly", "matplotlib"))
