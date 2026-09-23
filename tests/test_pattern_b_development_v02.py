"""Pattern B development set V02 (Criteria V02) — selection, blind pack, seal, protections."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/build_pattern_b_development_v02_chart_pack.py"
_spec = importlib.util.spec_from_file_location("build_pattern_b_development_v02_chart_pack", _SCRIPT)
dev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dev
_spec.loader.exec_module(dev)

SEAL = json.loads(dev.SEAL.read_text(encoding="utf-8"))
PUBLIC = [dev.PROTOCOL, dev.CHART_RECORD, dev.SEAL, _ROOT / "docs/patterns/pattern_b/README.md"]
PROTECTED_SHA256 = {
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02.md": "3944a1316d4ecf92f855dfac83ec6fb5b9513750caa9875b61fc8801795d5233",
    "docs/patterns/pattern_b/validation/human_ground_truth_criteria_v02_seal.json": "e4ffac7a0345a821cc4658b837f76f68d184e7966d0863fe8b32d4c84b9ea9f6",
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v01.csv": "6b2f01cd4e2879805879a270a457c0b72f4f1b468994107d2cfd193d160f77bc",
    "docs/patterns/pattern_b/validation/human_ground_truth_labels_v02.csv": "cbbc8785e20d03e4937317d9de11f79529ad4d8abea23763a490763c3e23e5c8",
    "docs/patterns/pattern_b/validation/holdout_v02_seal.json": "f1bf7135042c8de8af14ed18739ef104c7b68a9e388931cc8edcb1bdd0eaf9d5",
    "src/trend_scanner/patterns/pattern_b_state_v01.py": "a69280eb02b7c0aa434a14d126aaf9063f58ab5a603d887b1f73cdc9122e3d46",
    "docs/patterns/pattern_b/validation/state_rule_v01_holdout_v02_evaluation_seal.json": "f39d5360ab886bd7e9712736e4a5c424b1d59b79862cbc0328e453df3c20b76d",
    "docs/patterns/pattern_b/validation/robust_current_position_feature_research_v01.json": "bcc4f305e24620072609bf73b91074d43934b30d6f6bb40f93b1c0897d427bb9",
    "docs/patterns/pattern_b/validation/robust_current_position_feature_research_v01.md": "bb53e94bd7cb1132a9985d878a79fb6c4c5761b889c94154f0e69317882d29a4",
}
PRIVATE = dev.MANIFEST.exists()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_anchor_rule_and_hash_namespace():
    cal = pd.bdate_range("2019-01-01", "2025-12-31")
    assert dev.resolve_anchor(cal, 2019) == pd.Timestamp("2019-12-31")
    assert dev.resolve_anchor(cal[cal != pd.Timestamp("2019-12-31")], 2019) == pd.Timestamp("2019-12-30")
    assert dev.hash_key(pd.Timestamp("2021-12-30"), "123456") == hashlib.sha256(
        b"PATTERN_B_DEVELOPMENT_V02|2021-12-30|123456").hexdigest()


def test_seal_contract_and_flags():
    assert SEAL["version"] == "PATTERN_B_DEVELOPMENT_V02"
    assert SEAL["development_only"] is True and SEAL["holdout"] is False
    assert SEAL["criteria_version"] == "PATTERN_B_HGT_CRITERIA_V02"
    assert SEAL["sample_count"] == 36 and SEAL["sample_ids"] == list(dev.SAMPLE_IDS)
    assert SEAL["human_labels_collected"] is False
    assert SEAL["feature_values_revealed"] is False and SEAL["automatic_predictions_revealed"] is False
    for key in ("v01_exact_sample_overlap", "holdout_v02_exact_sample_overlap",
                "v01_ticker_overlap", "holdout_v02_ticker_overlap"):
        assert SEAL[key] == 0
    assert SEAL["criteria_file_sha256"] == _sha(dev.CRITERIA)
    assert SEAL["protocol_record_sha256"] == _sha(dev.PROTOCOL)
    assert SEAL["chart_pack_record_sha256"] == _sha(dev.CHART_RECORD)


def test_public_files_hold_no_features_or_predictions():
    for path in PUBLIC:
        text = path.read_text(encoding="utf-8")
        for token in ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION",
                      "predicted_state", "automatic_label"):
            assert token not in text, (path.name, token)
    seal_keys = set(SEAL)
    assert not {"ticker", "stock_name", "as_of", "tickers"} & seal_keys


@pytest.mark.skipif(not PRIVATE, reason="private development manifest is local only")
def test_private_selection_and_pack_match_seal():
    rows = dev._manifest_rows(dev.MANIFEST)
    assert sorted(r["sample_id"] for r in rows) == list(dev.SAMPLE_IDS)
    assert len({r["ticker"] for r in rows}) == 36
    v01_t, v02_t = dev.excluded_tickers()
    assert not {r["ticker"] for r in rows} & (v01_t | v02_t)
    keys = {(r["ticker"], r["as_of"]) for r in rows}
    assert not keys & {(r["ticker"], r["as_of"]) for r in dev._manifest_rows(dev.V01_MANIFEST)}
    assert not keys & {(r["ticker"], r["as_of"]) for r in dev._manifest_rows(dev.HOLDOUT_V02_MANIFEST)}
    assert SEAL["private_manifest_sha256"] == _sha(dev.MANIFEST)
    assert SEAL["chart_pack_sha256"] == _sha(dev.OUT_DIR / dev.ZIP_NAME)
    summary = json.loads((dev.PRIVATE_DIR / "verification_summary.json").read_text(encoding="utf-8"))
    for key, value in dev.EXPECTED_SUMMARY.items():
        assert summary[key] == value, key
    for r in rows:
        assert r["monthly_last_date"] <= r["as_of"] and r["weekly_last_date"] <= r["as_of"]
    identity = {r["ticker"] for r in rows} | {r["stock_name"] for r in rows if r["stock_name"]} | {r["as_of"] for r in rows}
    for path in PUBLIC + [_SCRIPT]:
        text = path.read_text(encoding="utf-8")
        assert not [t for t in identity if t in text], path.name


def test_protected_files_are_unchanged():
    for rel, digest in PROTECTED_SHA256.items():
        assert _sha(_ROOT / rel) == digest, rel
