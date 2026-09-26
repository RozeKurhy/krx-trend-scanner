"""Pattern B development set V02 human labels — sealed values, record, and protections."""

from __future__ import annotations

import collections
import csv
import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_V = _ROOT / "docs/patterns/pattern_b/validation"
LABELS = _V / "development_v02_human_labels.csv"
RECORD = _V / "development_v02_human_labels.md"
SEAL = json.loads((_V / "development_v02_human_labels_seal.json").read_text(encoding="utf-8"))
STATES = ("DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED")
PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/development_v02_seal.json": "a9b406830da243e4ffd96c4bb47383811fc862e0069fb0a959f4b1cd67213854",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv": "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict]:
    with LABELS.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_labels_are_exact_and_valid():
    with LABELS.open(encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == ["sample_id", "label", "confidence"]
    rows = _rows()
    ids = [r["sample_id"] for r in rows]
    assert ids == [f"PBDEV2_{i:03d}" for i in range(1, 37)] and len(set(ids)) == 36
    assert all(r["label"] in STATES for r in rows)
    assert all(r["confidence"] in {"HIGH", "MEDIUM", "LOW"} for r in rows)


def test_distribution_and_seal_match():
    rows = _rows()
    counts = collections.Counter(r["label"] for r in rows)
    assert {s: counts[s] for s in STATES} == SEAL["label_counts"] == {
        "DEEP_DEPRESSED": 11, "DEPRESSED": 12, "NORMAL": 8, "OVERHEATED": 4, "EXTREME_OVERHEATED": 1,
    }
    assert SEAL["confidence_counts"] == {"HIGH": 35, "MEDIUM": 1, "LOW": 0}
    assert [r["sample_id"] for r in rows if r["confidence"] == "MEDIUM"] == ["PBDEV2_019"]
    assert SEAL["labels_file_sha256"] == _sha(LABELS)
    assert SEAL["record_file_sha256"] == _sha(RECORD)
    assert SEAL["development_pack_seal_sha256"] == _sha(_V / "development_v02_seal.json")
    assert SEAL["criteria_file_sha256"] == _sha(_V / "human_ground_truth_criteria_v02.md")


def test_method_flags_and_record():
    assert SEAL["judge"] == "user" and SEAL["judge_count"] == 1
    assert SEAL["notes_included"] is False and SEAL["medium_samples_rereviewed"] is True
    assert SEAL["ai_interpretive_notes_after_user_judgment"] is True
    assert SEAL["feature_values_revealed"] is False and SEAL["automatic_predictions_revealed"] is False
    assert SEAL["identity_blind"] is True and SEAL["rule_blind"] is False
    record = RECORD.read_text(encoding="utf-8")
    assert "마지막 명시 판정이며,\n  이전 중간 판정을 모두 대체한다" in record
    assert "판정자는 지표 값과 자동 판정을 보지 않았다" in record
    assert "차트 해석 메모를 제공했으나, 최종 상태와 신뢰도는 사용자의 마지막 명시 판정만 사용했다" in record
    for token in ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION", "predicted"):
        assert token not in record and token not in LABELS.read_text(encoding="utf-8")


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
