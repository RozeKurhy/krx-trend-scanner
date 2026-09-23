"""Pattern B HGT criteria V02 (current-state first) — prospective-only seal and protections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_V = _ROOT / "docs/patterns/pattern_b/validation"
CRITERIA = _V / "human_ground_truth_criteria_v02.md"
SEAL = _V / "human_ground_truth_criteria_v02_seal.json"

PROTECTED_SHA256 = {
    "human_ground_truth_v01.md": "e10c6173b6da61fc3a8d4d8438ca0d7eccec4a4b75241a28fe247836a581c0d0",
    "human_ground_truth_labels_v01.csv": "6b2f01cd4e2879805879a270a457c0b72f4f1b468994107d2cfd193d160f77bc",
    "human_ground_truth_labels_v02.csv": "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "human_ground_truth_v02.md": "c48b5f190fc2c49d488764139e2abc91b1df9b6a2b422576855eb3df92bb5c0e",
    "state_rule_v01_holdout_v02_predictions.csv": "86163eaad28916e0c53ddb111d570b97147f4ff9e6c4689975236e76c6ad81a4",
    "state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "holdout_v02_posthoc_adjudication_v01.md": "b2345b3cc1f1a9a4431b8e41b8e8a707e970c3d825a6716a4799d21d6f5115ea",
    "holdout_v02_posthoc_adjudication_v01_seal.json": "044b8f8cea4deffb75d6bf119e0303ec898e040c8e1d5fadb8ad8404cc6311f2",
    "feature_raw_values_v02.csv": "5613bc03f0126ea6dbf3609e6826709c1ed119a0f919b02dec7f1eb74ce8f986",
}
STATE_RULE = {
    _ROOT / "src/trend_scanner/patterns/pattern_b_state_v01.py":
        "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    _V / "state_rule_v01.md": "247e274a8a5255332be5ed1a84c30a7bd95f1b1899be6013590128dde9f860f5",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal() -> dict:
    return json.loads(SEAL.read_text(encoding="utf-8"))


def test_seal_flags_and_hashes():
    seal = _seal()
    assert seal["version"] == "PATTERN_B_HGT_CRITERIA_V02"
    assert seal["prospective_only"] is True and seal["created_after_holdout_v02"] is True
    assert seal["automatic_prediction_blind_at_design"] is False
    assert seal["holdout_v02_reusable"] is False
    assert seal["criteria_file_sha256"] == _sha(CRITERIA)
    assert seal["source_posthoc_record_sha256"] == _sha(_V / "holdout_v02_posthoc_adjudication_v01.md")
    assert seal["source_official_evaluation_seal_sha256"] == _sha(
        _V / "state_rule_v01_holdout_v02_evaluation_seal.json"
    )
    assert seal["reference_hgt_criteria_v01_sha256"] == _sha(_V / "human_ground_truth_v01.md")


def test_criteria_state_the_current_state_principles():
    text = CRITERIA.read_text(encoding="utf-8")
    for phrase in (
        "오른쪽 마지막 가격이 자기 장기 가격 사이클에서 현재 어느\n위치에 있는지",
        "왼쪽 시작 가격 대비 배수를 쓰지 않는다",
        "과거 최고점은 현재 상태를 유지시키지 않는다",
        "고점 대비 하락 폭만으로 침체로 보지 않는다",
        "월봉이 핵심이고 주봉은 현재 극단성을 보조로 확인한다",
        "과거 경로는 별도 축 후보",
        "V02는 다시 평가하지 않는다",
        "V03 이후",
    ):
        assert phrase in text, phrase
    for token in ("DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED", "UNCERTAIN"):
        assert f"`{token}`" in text


def test_prior_records_and_rule_are_unchanged():
    for name, digest in PROTECTED_SHA256.items():
        assert _sha(_V / name) == digest, name
    for path, digest in STATE_RULE.items():
        assert _sha(path) == digest, path.name
