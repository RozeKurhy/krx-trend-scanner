#!/usr/bin/env python
"""Phase 13J-3: apply the user-completed PASS B outcomes and seal ground truth.

The labels below are the authoritative Human PASS B result. This helper only
checks sealed identity/PASS A state and writes the three allowed outcome fields.
It does not load charts, market data, machine outputs, or evaluation code.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OOS = ROOT / "artifacts/patterns/pattern_a_fast/validation/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
PASS_A_SEAL = OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json"
GROUND_TRUTH_SEAL = OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json"

BASE_COMMIT = "f6b6448c280706e1e2d17d19809f369ac3feea95"
PRE_PASS_B_REVIEW_SHA256 = "2a1c3cf172664f168e6e1c115bf242aabd5e342da8e73e44b0832690680fd5f4"
PASS_A_SEAL_SHA256 = "4c908daa5ab803ccbf20f355027391aaa3f2d63c31e3f60ac60df6e34b9201ea"
FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_ASSET_SHA256 = "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe"
FROZEN_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
FROZEN_MAPPING_SHA256 = "6d861d3b86f9c1e0fa4e7e48c1d59c385c3e089c05608fd45151536ab5c6b40b"
STAGES = ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
STAGE_CONFIDENCES = ["LOW", "MEDIUM", "HIGH"]
OUTCOMES = ["GOOD_TRIGGER", "BORDERLINE_TRIGGER", "FALSE_TRIGGER", "TOO_EARLY", "TOO_LATE", "TOO_EXTENDED", "NO_SETUP"]

# review_order, sample_id, ticker, name, outcome, confidence
OUTCOME_LABELS = [
    (1, "INV_OOS_B_002", "281740", "레이크머티리얼즈", "GOOD_TRIGGER", "HIGH"),
    (2, "INV_OOS_B_004", "064350", "현대로템", "BORDERLINE_TRIGGER", "MEDIUM"),
    (3, "INV_OOS_B_030", "010620", "현대미포조선", "BORDERLINE_TRIGGER", "MEDIUM"),
    (4, "INV_OOS_B_024", "004020", "현대제철", "TOO_EARLY", "HIGH"),
    (5, "INV_OOS_B_031", "270520", "지오릿에너지", "NO_SETUP", "HIGH"),
    (6, "INV_OOS_B_007", "036710", "심텍홀딩스", "FALSE_TRIGGER", "HIGH"),
    (7, "INV_OOS_B_005", "000720", "현대건설", "TOO_LATE", "HIGH"),
    (8, "INV_OOS_B_008", "200130", "콜마비앤에이치", "NO_SETUP", "HIGH"),
    (9, "INV_OOS_B_023", "125210", "아모그린텍", "FALSE_TRIGGER", "HIGH"),
    (10, "INV_OOS_B_010", "022100", "포스코DX", "TOO_EARLY", "HIGH"),
    (11, "INV_OOS_B_009", "402030", "코난테크놀로지", "FALSE_TRIGGER", "HIGH"),
    (12, "INV_OOS_B_018", "033780", "KT&G", "GOOD_TRIGGER", "HIGH"),
    (13, "INV_OOS_B_006", "138040", "메리츠금융지주", "TOO_LATE", "HIGH"),
    (14, "INV_OOS_B_034", "005850", "에스엘", "TOO_EXTENDED", "HIGH"),
    (15, "INV_OOS_B_028", "217330", "싸이토젠", "FALSE_TRIGGER", "HIGH"),
    (16, "INV_OOS_B_016", "256940", "케이피에스", "BORDERLINE_TRIGGER", "MEDIUM"),
    (17, "INV_OOS_B_022", "010140", "삼성중공업", "GOOD_TRIGGER", "HIGH"),
    (18, "INV_OOS_B_027", "084370", "유진테크", "TOO_EARLY", "HIGH"),
    (19, "INV_OOS_B_033", "018880", "한온시스템", "NO_SETUP", "HIGH"),
    (20, "INV_OOS_B_035", "222080", "씨아이에스", "TOO_EARLY", "HIGH"),
    (21, "INV_OOS_B_011", "048410", "현대바이오", "NO_SETUP", "HIGH"),
    (22, "INV_OOS_B_012", "214320", "이노션", "FALSE_TRIGGER", "HIGH"),
    (23, "INV_OOS_B_003", "060230", "소니드", "NO_SETUP", "HIGH"),
    (24, "INV_OOS_B_029", "002350", "넥센타이어", "TOO_EARLY", "HIGH"),
    (25, "INV_OOS_B_013", "119830", "아이텍", "TOO_EARLY", "HIGH"),
    (26, "INV_OOS_B_020", "271560", "오리온", "TOO_EARLY", "HIGH"),
    (27, "INV_OOS_B_021", "214150", "클래시스", "BORDERLINE_TRIGGER", "MEDIUM"),
    (28, "INV_OOS_B_001", "178920", "PI첨단소재", "TOO_EARLY", "HIGH"),
    (29, "INV_OOS_B_026", "101530", "해태제과식품", "BORDERLINE_TRIGGER", "MEDIUM"),
    (30, "INV_OOS_B_015", "079940", "가비아", "GOOD_TRIGGER", "HIGH"),
    (31, "INV_OOS_B_025", "028050", "삼성엔지니어링", "BORDERLINE_TRIGGER", "MEDIUM"),
    (32, "INV_OOS_B_019", "051900", "LG생활건강", "NO_SETUP", "HIGH"),
    (33, "INV_OOS_B_036", "086520", "에코프로", "GOOD_TRIGGER", "HIGH"),
    (34, "INV_OOS_B_032", "005180", "빙그레", "TOO_EXTENDED", "HIGH"),
    (35, "INV_OOS_B_017", "074600", "원익QnC", "BORDERLINE_TRIGGER", "MEDIUM"),
    (36, "INV_OOS_B_014", "053080", "케이엔솔", "TOO_EXTENDED", "HIGH"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapping_sha256(review: pd.DataFrame) -> str:
    rows = review[["review_order", "sample_id"]].sort_values("review_order", kind="mergesort")
    payload = "\n".join(f"{int(row.review_order)}|{row.sample_id}" for row in rows.itertuples(index=False))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def frozen_identity() -> pd.DataFrame:
    manifest = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    assets = pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False)
    order = assets[["review_order", "sample_id"]].drop_duplicates()
    fields = ["sample_id", "ticker", "name", "historical_market", "completed_weekly_reference_date", "outcome_review_end"]
    frozen = order.merge(manifest[fields], on="sample_id", validate="one_to_one").rename(columns={"completed_weekly_reference_date": "reference_date"})
    if len(frozen) != 36:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    frozen["review_order"] = frozen.review_order.astype(int)
    frozen["ticker"] = frozen.ticker.astype(str).str.zfill(6)
    return frozen.sort_values("review_order", kind="mergesort").reset_index(drop=True)


def assert_pre_pass_b_state(review: pd.DataFrame) -> None:
    if sha256(REVIEW) != PRE_PASS_B_REVIEW_SHA256 or sha256(PASS_A_SEAL) != PASS_A_SEAL_SHA256:
        raise RuntimeError("INVESTABLE_OOS_PASS_A_FREEZE_INTEGRITY_FAIL")
    if sha256(MANIFEST) != FROZEN_SELECTION_SHA256 or sha256(ASSETS) != FROZEN_ASSET_SHA256 or sha256(PROTOCOL) != FROZEN_PROTOCOL_SHA256:
        raise RuntimeError("INVESTABLE_OOS_FROZEN_INPUT_INTEGRITY_FAIL")
    pass_a = json.loads(PASS_A_SEAL.read_text(encoding="utf-8"))
    if pass_a["status"] != "HUMAN_STAGE_PASS_A_FROZEN" or pass_a["human_review_csv_sha256"] != PRE_PASS_B_REVIEW_SHA256:
        raise RuntimeError("INVESTABLE_OOS_PASS_A_FREEZE_INTEGRITY_FAIL")
    identity_fields = ["review_order", "sample_id", "ticker", "name", "historical_market", "reference_date", "outcome_review_end"]
    actual = review[identity_fields].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.astype(str).str.zfill(6)
    actual = actual.sort_values("review_order", kind="mergesort").reset_index(drop=True)
    if not actual.equals(frozen_identity()[identity_fields]) or mapping_sha256(review) != FROZEN_MAPPING_SHA256:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    if Counter(review.human_stage) != Counter({"WATCH": 16, "SETUP": 14, "TREND": 3, "EXTENDED": 3}) or Counter(review.human_stage_confidence) != Counter({"HIGH": 25, "MEDIUM": 9, "LOW": 2}):
        raise RuntimeError("INVESTABLE_OOS_PASS_A_FREEZE_INTEGRITY_FAIL")
    if not review.human_trigger_event_observed.eq("NO").all() or not review.human_trigger_event_date.eq("").all() or not review.stage_review_status.eq("COMPLETE").all():
        raise RuntimeError("INVESTABLE_OOS_PASS_A_FREEZE_INTEGRITY_FAIL")
    if not review.human_outcome_label.eq("UNLABELED").all() or not review.human_outcome_confidence.eq("UNLABELED").all() or not review.outcome_review_status.eq("PENDING").all():
        raise RuntimeError("HUMAN_OUTCOME_PASS_B_ALREADY_STARTED")


def apply_authoritative_outcomes(review: pd.DataFrame) -> pd.DataFrame:
    expected = pd.DataFrame(OUTCOME_LABELS, columns=["review_order", "sample_id", "ticker", "name", "human_outcome_label", "human_outcome_confidence"])
    expected["review_order"] = expected.review_order.astype(int)
    actual = review[["review_order", "sample_id", "ticker", "name"]].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.astype(str).str.zfill(6)
    if not actual.equals(expected[["review_order", "sample_id", "ticker", "name"]]):
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    labelled = review.copy()
    labelled["human_outcome_label"] = expected.human_outcome_label
    labelled["human_outcome_confidence"] = expected.human_outcome_confidence
    labelled["outcome_review_status"] = "COMPLETE"
    return labelled


def write_ground_truth_seal(review: pd.DataFrame) -> None:
    stage_counts, outcome_counts = Counter(review.human_stage), Counter(review.human_outcome_label)
    outcome_confidence = Counter(review.human_outcome_confidence)
    seal = {
        "version": "PATTERN_A_FAST_INVESTABLE_OOS_B_HUMAN_GROUND_TRUTH_V01",
        "phase": "13J-3",
        "base_commit": BASE_COMMIT,
        "human_review_file": REVIEW.relative_to(ROOT).as_posix(),
        "pre_pass_b_human_review_sha256": PRE_PASS_B_REVIEW_SHA256,
        "post_pass_b_human_review_sha256": sha256(REVIEW),
        "pass_a_freeze_seal_file": PASS_A_SEAL.relative_to(ROOT).as_posix(),
        "pass_a_freeze_seal_sha256": sha256(PASS_A_SEAL),
        "selection_manifest_sha256": sha256(MANIFEST),
        "blind_asset_manifest_sha256": sha256(ASSETS),
        "evaluation_protocol_sha256": sha256(PROTOCOL),
        "review_order_sample_mapping_sha256": mapping_sha256(review),
        "sample_count": len(review),
        "stage_complete_count": int(review.stage_review_status.eq("COMPLETE").sum()),
        "stage_distribution": {stage: int(stage_counts[stage]) for stage in STAGES},
        "trigger_yes_count": int(review.human_trigger_event_observed.eq("YES").sum()),
        "trigger_no_count": int(review.human_trigger_event_observed.eq("NO").sum()),
        "trigger_date_populated_count": int(review.human_trigger_event_date.ne("").sum()),
        "outcome_complete_count": int(review.outcome_review_status.eq("COMPLETE").sum()),
        "outcome_pending_count": int(review.outcome_review_status.eq("PENDING").sum()),
        "outcome_distribution": {outcome: int(outcome_counts[outcome]) for outcome in OUTCOMES},
        "outcome_confidence_distribution": {confidence: int(outcome_confidence[confidence]) for confidence in STAGE_CONFIDENCES},
        "pass_a_stage_mutation": False,
        "sample_mutation": False,
        "resampling_performed": False,
        "machine_outputs_exposed_to_human": False,
        "oos_evaluation_executed": False,
        "retuning_performed": False,
        "network_market_request_count": 0,
        "outcome_window_exposed_to_human": True,
        "status": "HUMAN_OUTCOME_PASS_B_GROUND_TRUTH_FROZEN",
    }
    GROUND_TRUTH_SEAL.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    review = pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)
    assert_pre_pass_b_state(review)
    labelled = apply_authoritative_outcomes(review)
    labelled.to_csv(REVIEW, index=False)
    write_ground_truth_seal(labelled)
    print("HUMAN_OUTCOME_PASS_B_GROUND_TRUTH_FROZEN: samples=36")


if __name__ == "__main__":
    main()
