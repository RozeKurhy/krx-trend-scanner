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
