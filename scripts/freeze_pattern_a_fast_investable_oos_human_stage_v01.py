#!/usr/bin/env python
"""Phase 13J-2: apply the user-completed OOS-B PASS A stage review once and seal it.

This script consumes only the authoritative user-provided PIT labels below.  It
does not read outcome charts, future prices, machine outputs, or evaluation data.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json"

BASE_COMMIT = "34df893fccb4c25d4dc346a359617cbe2a034974"
FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_REVIEW_TEMPLATE_SHA256 = "25d5f524517c7eabe6ab232e5ba97964ff00aae06f59a4362ba49cb5f78c99d1"
FROZEN_ASSET_SHA256 = "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe"
FROZEN_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
FROZEN_MAPPING_SHA256 = "6d861d3b86f9c1e0fa4e7e48c1d59c385c3e089c05608fd45151536ab5c6b40b"
STAGES = ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
CONFIDENCES = ["LOW", "MEDIUM", "HIGH"]

# review_order, sample_id, ticker, name, reference_date, stage, confidence
LABELS = [
    (1, "INV_OOS_B_002", "281740", "레이크머티리얼즈", "2023-03-31", "TREND", "HIGH"),
    (2, "INV_OOS_B_004", "064350", "현대로템", "2022-09-30", "SETUP", "MEDIUM"),
    (3, "INV_OOS_B_030", "010620", "현대미포조선", "2023-03-31", "SETUP", "LOW"),
    (4, "INV_OOS_B_024", "004020", "현대제철", "2024-12-27", "WATCH", "HIGH"),
    (5, "INV_OOS_B_031", "270520", "지오릿에너지", "2024-03-29", "WATCH", "HIGH"),
    (6, "INV_OOS_B_007", "036710", "심텍홀딩스", "2023-06-30", "SETUP", "MEDIUM"),
    (7, "INV_OOS_B_005", "000720", "현대건설", "2021-06-25", "TREND", "MEDIUM"),
    (8, "INV_OOS_B_008", "200130", "콜마비앤에이치", "2023-12-22", "WATCH", "HIGH"),
    (9, "INV_OOS_B_023", "125210", "아모그린텍", "2023-03-31", "SETUP", "MEDIUM"),
    (10, "INV_OOS_B_010", "022100", "포스코DX", "2024-09-27", "WATCH", "HIGH"),
    (11, "INV_OOS_B_009", "402030", "코난테크놀로지", "2025-06-27", "SETUP", "HIGH"),
    (12, "INV_OOS_B_018", "033780", "KT&G", "2023-09-22", "SETUP", "LOW"),
    (13, "INV_OOS_B_006", "138040", "메리츠금융지주", "2025-06-27", "TREND", "HIGH"),
    (14, "INV_OOS_B_034", "005850", "에스엘", "2021-06-25", "EXTENDED", "HIGH"),
    (15, "INV_OOS_B_028", "217330", "싸이토젠", "2024-03-29", "SETUP", "MEDIUM"),
    (16, "INV_OOS_B_016", "256940", "케이피에스", "2022-12-23", "WATCH", "HIGH"),
    (17, "INV_OOS_B_022", "010140", "삼성중공업", "2024-03-29", "SETUP", "HIGH"),
    (18, "INV_OOS_B_027", "084370", "유진테크", "2024-12-27", "WATCH", "HIGH"),
    (19, "INV_OOS_B_033", "018880", "한온시스템", "2022-12-23", "WATCH", "HIGH"),
    (20, "INV_OOS_B_035", "222080", "씨아이에스", "2025-03-28", "WATCH", "HIGH"),
    (21, "INV_OOS_B_011", "048410", "현대바이오", "2024-09-27", "WATCH", "HIGH"),
    (22, "INV_OOS_B_012", "214320", "이노션", "2023-12-22", "SETUP", "HIGH"),
    (23, "INV_OOS_B_003", "060230", "소니드", "2023-06-30", "WATCH", "MEDIUM"),
    (24, "INV_OOS_B_029", "002350", "넥센타이어", "2024-06-28", "WATCH", "HIGH"),
    (25, "INV_OOS_B_013", "119830", "아이텍", "2024-06-28", "WATCH", "MEDIUM"),
    (26, "INV_OOS_B_020", "271560", "오리온", "2023-12-22", "WATCH", "HIGH"),
    (27, "INV_OOS_B_021", "214150", "클래시스", "2021-06-25", "SETUP", "HIGH"),
    (28, "INV_OOS_B_001", "178920", "PI첨단소재", "2023-06-30", "WATCH", "MEDIUM"),
    (29, "INV_OOS_B_026", "101530", "해태제과식품", "2024-09-27", "WATCH", "HIGH"),
    (30, "INV_OOS_B_015", "079940", "가비아", "2024-12-27", "SETUP", "HIGH"),
    (31, "INV_OOS_B_025", "028050", "삼성엔지니어링", "2022-03-25", "SETUP", "HIGH"),
    (32, "INV_OOS_B_019", "051900", "LG생활건강", "2025-06-27", "WATCH", "HIGH"),
    (33, "INV_OOS_B_036", "086520", "에코프로", "2021-03-26", "SETUP", "MEDIUM"),
    (34, "INV_OOS_B_032", "005180", "빙그레", "2024-06-28", "EXTENDED", "HIGH"),
    (35, "INV_OOS_B_017", "074600", "원익QnC", "2023-09-22", "SETUP", "HIGH"),
    (36, "INV_OOS_B_014", "053080", "케이엔솔", "2023-09-22", "EXTENDED", "HIGH"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapping_sha256(review: pd.DataFrame) -> str:
    rows = review[["review_order", "sample_id"]].copy().sort_values("review_order", kind="mergesort")
    payload = "\n".join(f"{int(row.review_order)}|{row.sample_id}" for row in rows.itertuples(index=False))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def frozen_identity() -> pd.DataFrame:
    """Return the Phase 13J-1 sealed review identity without recomputation."""
    manifest = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    assets = pd.read_csv(ASSETS, dtype={"ticker": str}, keep_default_na=False)
    review_order = assets[["review_order", "sample_id"]].drop_duplicates()
    if len(review_order) != 36 or review_order.sample_id.nunique() != 36:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    fields = ["sample_id", "ticker", "name", "historical_market", "completed_weekly_reference_date", "outcome_review_end"]
    frozen = review_order.merge(manifest[fields], on="sample_id", how="inner", validate="one_to_one")
    if len(frozen) != 36:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")
    frozen = frozen.rename(columns={"completed_weekly_reference_date": "reference_date"})
    frozen["review_order"] = frozen.review_order.astype(int)
    frozen["ticker"] = frozen.ticker.astype(str).str.zfill(6)
    return frozen.sort_values("review_order", kind="mergesort").reset_index(drop=True)


def assert_frozen_identity(review: pd.DataFrame) -> None:
    fields = ["review_order", "sample_id", "ticker", "name", "historical_market", "reference_date", "outcome_review_end"]
    actual = review[fields].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.astype(str).str.zfill(6)
    actual = actual.sort_values("review_order", kind="mergesort").reset_index(drop=True)
    if not actual.equals(frozen_identity()[fields]):
        raise RuntimeError("INVESTABLE_OOS_REVIEW_IDENTITY_FREEZE_INTEGRITY_FAIL")


def assert_frozen_inputs(review: pd.DataFrame) -> None:
    if sha256(MANIFEST) != FROZEN_SELECTION_SHA256:
        raise RuntimeError("INVESTABLE_OOS_SAMPLE_FREEZE_INTEGRITY_FAIL")
    if sha256(ASSETS) != FROZEN_ASSET_SHA256 or sha256(PROTOCOL) != FROZEN_PROTOCOL_SHA256:
        raise RuntimeError("INVESTABLE_OOS_BLIND_ASSET_MAPPING_FAIL")
    if len(review) != 36 or review.review_order.astype(int).tolist() != list(range(1, 37)):
        raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    if mapping_sha256(review) != FROZEN_MAPPING_SHA256:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    assert_frozen_identity(review)
    pre_label = ["human_stage", "human_stage_confidence", "human_trigger_event_observed", "stage_review_status"]
    if not all(review[column].eq("UNLABELED" if column != "stage_review_status" else "PENDING").all() for column in pre_label):
        raise RuntimeError("HUMAN_STAGE_PASS_A_ALREADY_STARTED")
    if not review.human_trigger_event_date.eq("").all():
        raise RuntimeError("HUMAN_STAGE_PASS_A_ALREADY_STARTED")
    for column, expected in {"human_outcome_label": "UNLABELED", "human_outcome_confidence": "UNLABELED", "outcome_review_status": "PENDING"}.items():
        if not review[column].eq(expected).all():
            raise RuntimeError("OUTCOME_REVIEW_MUST_NOT_START")


def apply_authoritative_labels(review: pd.DataFrame) -> pd.DataFrame:
    expected = pd.DataFrame(LABELS, columns=["review_order", "sample_id", "ticker", "name", "reference_date", "human_stage", "human_stage_confidence"])
    expected["review_order"] = expected.review_order.astype(int)
    actual = review[["review_order", "sample_id", "ticker", "name", "reference_date"]].copy()
    actual["review_order"] = actual.review_order.astype(int)
    actual["ticker"] = actual.ticker.astype(str).str.zfill(6)
    if not actual.equals(expected[["review_order", "sample_id", "ticker", "name", "reference_date"]]):
        raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    labelled = review.copy()
    labelled["human_stage"] = expected.human_stage
    labelled["human_stage_confidence"] = expected.human_stage_confidence
    labelled["human_trigger_event_observed"] = "NO"
    labelled["human_trigger_event_date"] = ""
    labelled["stage_review_status"] = "COMPLETE"
    return labelled


def write_seal(review: pd.DataFrame) -> None:
    stage_counts = Counter(review.human_stage)
    confidence_counts = Counter(review.human_stage_confidence)
    seal = {
        "version": "PATTERN_A_FAST_INVESTABLE_OOS_B_HUMAN_STAGE_PASS_A_FREEZE_V01",
        "phase": "13J-2",
        "base_commit": BASE_COMMIT,
        "human_review_file": REVIEW.relative_to(ROOT).as_posix(),
        "human_review_csv_sha256": sha256(REVIEW),
        "pre_pass_a_human_review_template_sha256": FROZEN_REVIEW_TEMPLATE_SHA256,
        "selection_manifest_file": MANIFEST.relative_to(ROOT).as_posix(),
        "selection_manifest_sha256": sha256(MANIFEST),
        "blind_asset_manifest_file": ASSETS.relative_to(ROOT).as_posix(),
        "blind_asset_manifest_sha256": sha256(ASSETS),
        "evaluation_protocol_file": PROTOCOL.relative_to(ROOT).as_posix(),
        "evaluation_protocol_sha256": sha256(PROTOCOL),
        "review_order_sample_mapping_sha256": mapping_sha256(review),
        "sample_count": len(review),
        "review_mapping_count": int(review.sample_id.nunique()),
        "human_stage_distribution": {stage: int(stage_counts[stage]) for stage in STAGES},
        "human_stage_confidence_distribution": {confidence: int(confidence_counts[confidence]) for confidence in CONFIDENCES},
        "trigger_yes_count": int(review.human_trigger_event_observed.eq("YES").sum()),
        "trigger_no_count": int(review.human_trigger_event_observed.eq("NO").sum()),
        "trigger_date_populated_count": int(review.human_trigger_event_date.ne("").sum()),
        "stage_complete_count": int(review.stage_review_status.eq("COMPLETE").sum()),
        "stage_pending_count": int(review.stage_review_status.eq("PENDING").sum()),
        "outcome_pending_count": int(review.outcome_review_status.eq("PENDING").sum()),
        "human_outcome_labels_present": False,
        "outcome_charts_exposed": False,
        "machine_outputs_exposed": False,
        "future_data_used": False,
        "oos_evaluation_executed": False,
        "retuning_performed": False,
        "sample_mutation": False,
        "network_market_request_count": 0,
        "status": "HUMAN_STAGE_PASS_A_FROZEN",
    }
    SEAL.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    review = pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)
    assert_frozen_inputs(review)
    labelled = apply_authoritative_labels(review)
    labelled.to_csv(REVIEW, index=False)
    write_seal(labelled)
    print("HUMAN_STAGE_PASS_A_FROZEN: samples=36, outcome_review=NOT_STARTED")


if __name__ == "__main__":
    main()
