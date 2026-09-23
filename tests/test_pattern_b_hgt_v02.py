"""Pattern B human ground truth V02 (holdout) — sealed labels and record integrity."""

from __future__ import annotations

import collections
import csv
import hashlib
import json
from pathlib import Path

_V = Path(__file__).resolve().parents[1] / "docs/patterns/pattern_b/validation"
LABELS = _V / "human_ground_truth_labels_v02.csv"
RECORD = _V / "human_ground_truth_v02.md"
SEAL = _V / "human_ground_truth_v02_seal.json"
README = _V.parent / "README.md"
STATES = {"DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED"}


def _rows() -> list[dict]:
    with LABELS.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def test_labels_have_exact_sample_set_and_allowed_values():
    rows = _rows()
    assert len(rows) == 36
    ids = [r["sample_id"] for r in rows]
    assert len(set(ids)) == 36
    assert sorted(ids) == [f"PBHOLD_{i:03d}" for i in range(1, 37)]
    assert all(r["label"] in STATES for r in rows)
    assert all(r["confidence"] in {"HIGH", "MEDIUM", "LOW"} for r in rows)
    assert all(r["note"].strip() for r in rows)


def test_labels_have_no_identity_feature_or_prediction_fields():
    with LABELS.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == ["sample_id", "label", "confidence", "note"]
    seal_keys = set(_seal())
    forbidden = {"ticker", "stock_name", "as_of", "predicted_state", "36M_RANGE_POSITION",
                 "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION"}
    assert not forbidden & (set(header) | seal_keys)


def test_seal_matches_files_and_counts():
    seal = _seal()
    for key, path in (("labels_file_sha256", LABELS), ("record_file_sha256", RECORD)):
        assert seal[key] == hashlib.sha256(path.read_bytes()).hexdigest()
    rows = _rows()
    assert seal["sample_count"] == 36
    assert seal["label_counts"] == dict(collections.Counter(r["label"] for r in rows)) | {
        s: 0 for s in STATES if s not in {r["label"] for r in rows}
    }
    assert seal["confidence_counts"] == {
        c: sum(r["confidence"] == c for r in rows) for c in ("HIGH", "MEDIUM", "LOW")
    }


def test_judge_and_blind_scope_are_recorded():
    seal = _seal()
    assert seal["judge"] == "user" and seal["judge_count"] == 1
    assert seal["rule_blind"] is False
    assert seal["identity_blind"] and seal["feature_values_blind"] and seal["automatic_prediction_blind"]
    record = RECORD.read_text(encoding="utf-8")
    assert "판정자: 사용자 1명" in record
    assert "규칙에 대해 완전히 가려진 판정은 아니다" in record


def test_no_automatic_evaluation_is_recorded_yet():
    record = RECORD.read_text(encoding="utf-8")
    assert "자동 상태 판정, 사람 판정과\n> 자동 판정의 비교는 아직 하지 않았다" in record
    readme = README.read_text(encoding="utf-8")
    assert "별도 검증 표본 V02 사람 판정 완료·봉인, 자동 평가는 아직 미실시" in readme


SEALED_LABELS_SHA256 = "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8"


def test_sealed_labels_are_unchanged():
    assert hashlib.sha256(LABELS.read_bytes()).hexdigest() == SEALED_LABELS_SHA256
    assert _seal()["labels_file_sha256"] == SEALED_LABELS_SHA256
    by_id = {r["sample_id"]: r for r in _rows()}
    assert (by_id["PBHOLD_009"]["label"], by_id["PBHOLD_009"]["confidence"]) == ("NORMAL", "MEDIUM")
    seal = _seal()
    assert seal["label_counts"] == {
        "DEEP_DEPRESSED": 8, "DEPRESSED": 6, "NORMAL": 8, "OVERHEATED": 7, "EXTREME_OVERHEATED": 7,
    }
    assert seal["confidence_counts"] == {"HIGH": 22, "MEDIUM": 13, "LOW": 1}


def test_record_states_the_single_ai_prior_opinion_and_its_rejection():
    record = RECORD.read_text(encoding="utf-8")
    assert "36개 표본의 최종 상태와 신뢰도는 모두 사용자가 결정했다" in record
    assert "`PBHOLD_009`에서는" in record and "`OVERHEATED` / `MEDIUM` 의견을 1회 제시했다" in record
    assert "채택하지 않고 `NORMAL` / `MEDIUM`으로 직접 최종 판정했다" in record
    assert "그 외 표본에서는\n  AI가 사용자보다 먼저 상태 판정을 제시하지 않았다" in record
    assert "`PBHOLD_009`에서 AI의 선행 상태 의견이 1건 있었다" in record
    assert "상태 의견을 보태거나 판정값을 고치지 않았다" not in record
