"""Phase 13J-2 PASS A Human-stage freeze integrity tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from tests.helpers.frozen_integrity import (
    EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256,
    PATTERN_A_EVALUATOR_SHA256,
    PATTERN_A_FEATURE_SET_SHA256,
    PREPARE_INVESTABLE_OOS_SCRIPT_SHA256,
    assert_file_sha256,
)
from trend_scanner.validation.pattern_a_final_closure import EXPECTED_FROZEN_HASHES


ROOT = Path(__file__).resolve().parents[1]
BASE = "34df893fccb4c25d4dc346a359617cbe2a034974"  # Phase 13J-2 freeze reference commit (역사적 참조용, 더 이상 git diff 대상 아님 -- FIX_03)
OOS = ROOT / "artifacts/patterns/pattern_a_fast/validation/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json"
SCRIPT = ROOT / "scripts/freeze_pattern_a_fast_investable_oos_human_stage_v01.py"

FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_ASSET_SHA256 = "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe"
FROZEN_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
FROZEN_MAPPING_SHA256 = "6d861d3b86f9c1e0fa4e7e48c1d59c385c3e089c05608fd45151536ab5c6b40b"

# Authoritative user-provided PASS A result: order, sample_id, ticker,
# reference_date, human_stage, human_stage_confidence.
EXPECTED = [
    (1, "INV_OOS_B_002", "281740", "2023-03-31", "TREND", "HIGH"),
    (2, "INV_OOS_B_004", "064350", "2022-09-30", "SETUP", "MEDIUM"),
    (3, "INV_OOS_B_030", "010620", "2023-03-31", "SETUP", "LOW"),
    (4, "INV_OOS_B_024", "004020", "2024-12-27", "WATCH", "HIGH"),
    (5, "INV_OOS_B_031", "270520", "2024-03-29", "WATCH", "HIGH"),
    (6, "INV_OOS_B_007", "036710", "2023-06-30", "SETUP", "MEDIUM"),
    (7, "INV_OOS_B_005", "000720", "2021-06-25", "TREND", "MEDIUM"),
    (8, "INV_OOS_B_008", "200130", "2023-12-22", "WATCH", "HIGH"),
    (9, "INV_OOS_B_023", "125210", "2023-03-31", "SETUP", "MEDIUM"),
    (10, "INV_OOS_B_010", "022100", "2024-09-27", "WATCH", "HIGH"),
    (11, "INV_OOS_B_009", "402030", "2025-06-27", "SETUP", "HIGH"),
    (12, "INV_OOS_B_018", "033780", "2023-09-22", "SETUP", "LOW"),
    (13, "INV_OOS_B_006", "138040", "2025-06-27", "TREND", "HIGH"),
    (14, "INV_OOS_B_034", "005850", "2021-06-25", "EXTENDED", "HIGH"),
    (15, "INV_OOS_B_028", "217330", "2024-03-29", "SETUP", "MEDIUM"),
    (16, "INV_OOS_B_016", "256940", "2022-12-23", "WATCH", "HIGH"),
    (17, "INV_OOS_B_022", "010140", "2024-03-29", "SETUP", "HIGH"),
    (18, "INV_OOS_B_027", "084370", "2024-12-27", "WATCH", "HIGH"),
    (19, "INV_OOS_B_033", "018880", "2022-12-23", "WATCH", "HIGH"),
    (20, "INV_OOS_B_035", "222080", "2025-03-28", "WATCH", "HIGH"),
    (21, "INV_OOS_B_011", "048410", "2024-09-27", "WATCH", "HIGH"),
    (22, "INV_OOS_B_012", "214320", "2023-12-22", "SETUP", "HIGH"),
    (23, "INV_OOS_B_003", "060230", "2023-06-30", "WATCH", "MEDIUM"),
    (24, "INV_OOS_B_029", "002350", "2024-06-28", "WATCH", "HIGH"),
    (25, "INV_OOS_B_013", "119830", "2024-06-28", "WATCH", "MEDIUM"),
    (26, "INV_OOS_B_020", "271560", "2023-12-22", "WATCH", "HIGH"),
    (27, "INV_OOS_B_021", "214150", "2021-06-25", "SETUP", "HIGH"),
    (28, "INV_OOS_B_001", "178920", "2023-06-30", "WATCH", "MEDIUM"),
    (29, "INV_OOS_B_026", "101530", "2024-09-27", "WATCH", "HIGH"),
    (30, "INV_OOS_B_015", "079940", "2024-12-27", "SETUP", "HIGH"),
    (31, "INV_OOS_B_025", "028050", "2022-03-25", "SETUP", "HIGH"),
    (32, "INV_OOS_B_019", "051900", "2025-06-27", "WATCH", "HIGH"),
    (33, "INV_OOS_B_036", "086520", "2021-03-26", "SETUP", "MEDIUM"),
    (34, "INV_OOS_B_032", "005180", "2024-06-28", "EXTENDED", "HIGH"),
    (35, "INV_OOS_B_017", "074600", "2023-09-22", "SETUP", "HIGH"),
    (36, "INV_OOS_B_014", "053080", "2023-09-22", "EXTENDED", "HIGH"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review() -> pd.DataFrame:
    return pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)


def _seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def test_authoritative_stage_labels_and_identity_mapping_are_exact():
    review = _review()
    actual = review[["review_order", "sample_id", "ticker", "reference_date", "human_stage", "human_stage_confidence"]].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.str.zfill(6)
    expected = pd.DataFrame(EXPECTED, columns=actual.columns)
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected)
    assert len(review) == review.sample_id.nunique() == review.ticker.nunique() == 36
    assert review.review_order.astype(int).tolist() == list(range(1, 37))
    assert review.stage_review_status.eq("COMPLETE").all()
    assert review.human_stage.value_counts().to_dict() == {"WATCH": 16, "SETUP": 14, "TREND": 3, "EXTENDED": 3}
    assert review.human_stage_confidence.value_counts().to_dict() == {"HIGH": 25, "MEDIUM": 9, "LOW": 2}
    manifest = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    assets = pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False)
    review_order = assets[["review_order", "sample_id"]].drop_duplicates()
    frozen = review_order.merge(
        manifest[["sample_id", "ticker", "name", "historical_market", "completed_weekly_reference_date", "outcome_review_end"]],
        on="sample_id",
        validate="one_to_one",
    ).rename(columns={"completed_weekly_reference_date": "reference_date"})
    identity_fields = ["review_order", "sample_id", "ticker", "name", "historical_market", "reference_date", "outcome_review_end"]
    actual_identity = review[identity_fields].copy()
    actual_identity["review_order"] = actual_identity.review_order.astype(int)
    actual_identity["ticker"] = actual_identity.ticker.str.zfill(6)
    frozen_identity = frozen[identity_fields].copy()
    frozen_identity["review_order"] = frozen_identity.review_order.astype(int)
    frozen_identity["ticker"] = frozen_identity.ticker.str.zfill(6)
    pd.testing.assert_frame_equal(
        actual_identity.sort_values("review_order").reset_index(drop=True),
        frozen_identity.sort_values("review_order").reset_index(drop=True),
    )


def test_trigger_and_pass_a_fields_remain_frozen_after_later_outcome_annotation():
    review = _review()
    assert review.human_trigger_event_observed.eq("NO").all()
    assert review.human_trigger_event_date.eq("").all()


def test_pass_a_seal_binds_human_review_and_all_frozen_inputs():
    review, seal = _review(), _seal()
    payload = "\n".join(f"{int(row.review_order)}|{row.sample_id}" for row in review[["review_order", "sample_id"]].itertuples(index=False))
    assert seal["status"] == "HUMAN_STAGE_PASS_A_FROZEN"
    assert seal["sample_count"] == seal["review_mapping_count"] == 36
    # This seal is the immutable PASS A checkpoint, not the later PASS B CSV.
    assert seal["human_review_csv_sha256"] == "2a1c3cf172664f168e6e1c115bf242aabd5e342da8e73e44b0832690680fd5f4"
    assert seal["selection_manifest_sha256"] == FROZEN_SELECTION_SHA256 == _sha256(MANIFEST)
    assert seal["blind_asset_manifest_sha256"] == FROZEN_ASSET_SHA256 == _sha256(ASSETS)
    assert seal["evaluation_protocol_sha256"] == FROZEN_PROTOCOL_SHA256 == _sha256(PROTOCOL)
    assert seal["review_order_sample_mapping_sha256"] == FROZEN_MAPPING_SHA256 == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert seal["human_stage_distribution"] == {"WATCH": 16, "SETUP": 14, "TRIGGER": 0, "TREND": 3, "EXTENDED": 3}
    assert seal["human_stage_confidence_distribution"] == {"LOW": 2, "MEDIUM": 9, "HIGH": 25}
    assert (seal["trigger_yes_count"], seal["trigger_no_count"], seal["trigger_date_populated_count"]) == (0, 36, 0)
    assert (seal["stage_complete_count"], seal["stage_pending_count"], seal["outcome_pending_count"]) == (36, 0, 36)


def test_charts_assets_machine_code_and_outcome_evaluation_remain_untouched():
    """TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_03: manifest/assets/
    protocol/charts are already individually sha256-verified above (in
    `test_pass_a_seal_binds_human_review_and_all_frozen_inputs` and the
    per-asset loop right below), so re-checking them via a historical
    whole-file/whole-directory diff was redundant and, for Pattern A source,
    a false-positive risk against later legitimate docs-path changes. Only
    the Pattern A production source + the two OOS scripts are checked here,
    via explicit sha256 (score/stage reuse the existing
    `EXPECTED_FROZEN_HASHES` authority instead of a second hardcoded copy).
    """
    assets = pd.read_csv(ASSETS, dtype=str, keep_default_na=False)
    assert len(assets[assets.human_exposure_phase.eq("PASS_A")]) == 108
    assert len(assets[assets.human_exposure_phase.eq("PASS_B_AFTER_STAGE_FREEZE")]) == 36
    for asset in assets.itertuples(index=False):
        resolved_path = ROOT / asset.file_path.replace("artifacts/pattern_a_fast/", "artifacts/patterns/pattern_a_fast/validation/")
        assert _sha256(resolved_path) == asset.sha256
    assert_file_sha256(ROOT / "src/trend_scanner/patterns/pattern_a_evaluator.py", PATTERN_A_EVALUATOR_SHA256)
    assert_file_sha256(ROOT / "src/trend_scanner/patterns/pattern_a_feature_set.py", PATTERN_A_FEATURE_SET_SHA256)
    assert_file_sha256(ROOT / "src/trend_scanner/patterns/pattern_a_score.py", EXPECTED_FROZEN_HASHES["pattern_a_score.py"])
    assert_file_sha256(ROOT / "src/trend_scanner/patterns/pattern_a_stage.py", EXPECTED_FROZEN_HASHES["pattern_a_stage.py"])
    assert_file_sha256(ROOT / "scripts/prepare_pattern_a_fast_investable_oos_v01.py", PREPARE_INVESTABLE_OOS_SCRIPT_SHA256)
    assert_file_sha256(ROOT / "scripts/evaluate_pattern_a_fast_oos_v01.py", EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256)
    seal = _seal()
    assert seal["human_outcome_labels_present"] is False and seal["outcome_charts_exposed"] is False
    assert seal["machine_outputs_exposed"] is False and seal["future_data_used"] is False
    assert seal["oos_evaluation_executed"] is False and seal["retuning_performed"] is False
    assert seal["sample_mutation"] is False and seal["network_market_request_count"] == 0
    source = SCRIPT.read_text(encoding="utf-8")
    assert not any(token in source for token in ("requests", "urllib", "yfinance", "pykrx", "OUTCOME_DIR", "to_weekly"))
    assert "def assert_frozen_identity" in source and "historical_market" in source and "outcome_review_end" in source
