"""Phase 13I-1 integrity tests: reserved OOS is blind and unevaluated."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "ddc7480bb24119ca3e8caca6d7b7f451f8eb097a"
CONTRACT_SEAL_BASE = "311c235706bd07a67bfd3c658403f7d31da603c1"
OOS = ROOT / "artifacts/patterns/pattern_a_fast/validation/oos"
SOURCE = ROOT / "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv"
CALIBRATION = ROOT / "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_oos_sample_manifest_v01.csv"
REVIEW = OOS / "pattern_a_fast_oos_human_review_v01.csv"
ASSETS = OOS / "pattern_a_fast_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_oos_evaluation_protocol_v01.json"
AUDIT = OOS / "pattern_a_fast_oos_blindness_audit_v01.json"
SCRIPT = ROOT / "scripts/prepare_pattern_a_fast_oos_blind_review.py"


def _module():
    spec = importlib.util.spec_from_file_location("oos_blind_prepare", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(SOURCE, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(CALIBRATION, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False),
        pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False),
    )


def test_base_sha_is_exact_frozen_13h_commit():
    assert _module().BASE_SHA == BASE


def test_population_is_exactly_60_40_20_dual_unlabeled_holdout():
    source, review, manifest, _ = _frames()
    status = review[["sample_id", "weekly_stage_at_reference", "human_label"]]
    merged = source.merge(status, on="sample_id", validate="one_to_one")
    expected = merged.loc[
        (merged.weekly_stage_at_reference_y == "UNLABELED") & (merged.human_label_y == "UNLABELED")
    ]
    assert (len(source), len(expected), len(manifest)) == (60, 20, 20)
    assert set(manifest.source_sample_id) == set(expected.sample_id)


def test_calibration_is_excluded_without_sample_or_ticker_reference_overlap():
    source, review, manifest, _ = _frames()
    merged = source.merge(review[["sample_id", "weekly_stage_at_reference", "human_label"]], on="sample_id")
    calibration = merged.loc[
        (merged.weekly_stage_at_reference_y != "UNLABELED") & (merged.human_label_y != "UNLABELED")
    ]
    assert len(calibration) == 40
    assert not set(manifest.source_sample_id) & set(calibration.sample_id)
    assert not set(zip(manifest.ticker, manifest.reference_date)) & set(zip(calibration.ticker, calibration.reference_date))


def test_oos_manifest_preserves_leading_zero_tickers_and_frozen_dates():
    source, _, manifest, _ = _frames()
    original = source.set_index("sample_id")
    assert all(len(ticker) == 6 and ticker.isdigit() for ticker in manifest.ticker)
    for row in manifest.to_dict(orient="records"):
        frozen = original.loc[row["source_sample_id"]]
        assert (row["ticker"], row["name"], row["reference_date"], row["outcome_review_end"]) == (
            frozen.ticker, frozen["name"], frozen.reference_date, frozen.outcome_review_end
        )


def test_manifest_constants_and_deterministic_seeded_order():
    module = _module()
    _, _, manifest, _ = _frames()
    expected = sorted(manifest.source_sample_id, key=module.stable_order_key)
    assert manifest.oos_set.eq("RESERVED_OOS_A").all()
    assert manifest.sample_source.eq("RESERVED_13C_UNLABELED_HOLDOUT").all()
    assert manifest.review_order.tolist() == list(range(1, 21))
    assert manifest.source_sample_id.tolist() == expected
    assert manifest.oos_sample_id.tolist() == [f"OOS_A_{i:03d}" for i in range(1, 21)]


def test_human_review_sheet_has_no_model_output_columns_after_label_freeze():
    _, _, manifest, review = _frames()
    forbidden = ("fast_", "pattern_a_", "score", "machine_stage", "candidate", "lead", "failure", "pair_status", "sampling_cohort", "structure_bucket")
    assert [column for column in review.columns if any(token in column for token in forbidden) and column != "source_sample_id"] == []
    assert len(review) == 20
    assert set(review.oos_sample_id) == set(manifest.oos_sample_id)
    assert review.weekly_stage_at_reference.isin(["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]).all()
    assert review.stage_review_status.eq("COMPLETE").all()
    assert review.human_label.isin([
        "GOOD_TRIGGER", "BORDERLINE_TRIGGER", "FALSE_TRIGGER", "TOO_EARLY", "TOO_LATE",
        "TOO_EXTENDED", "NO_SETUP", "UNLABELED",
    ]).all()


def test_template_hash_is_frozen_in_manifest_and_audit():
    _, _, manifest, _ = _frames()
    initial_template = subprocess.run(
        ["git", "show", f"{CONTRACT_SEAL_BASE}:artifacts/pattern_a_fast/oos/pattern_a_fast_oos_human_review_v01.csv"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout
    digest = hashlib.sha256(initial_template).hexdigest()
    audit = json.loads(AUDIT.read_text())
    assert manifest.template_sha256.nunique() == 1
    assert manifest.template_sha256.iloc[0] == digest == audit["human_review_template_sha256"]


def test_chart_inventory_hashes_and_visibility_boundaries_are_exact():
    _, _, manifest, _ = _frames()
    assets = pd.read_csv(ASSETS, keep_default_na=False)
    assert len(assets) == 80
    assert (assets.asset_type.str.startswith("STAGE_")).sum() == 60
    assert (assets.asset_type == "OUTCOME_WEEKLY").sum() == 20
    dates = manifest.set_index("oos_sample_id")
    for asset in assets.itertuples(index=False):
        path = ROOT / asset.file_path.replace("artifacts/pattern_a_fast/", "artifacts/patterns/pattern_a_fast/validation/")
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == asset.sha256
        boundary = dates.loc[asset.oos_sample_id, "reference_date"] if asset.asset_type.startswith("STAGE_") else dates.loc[asset.oos_sample_id, "outcome_review_end"]
        assert asset.max_visible_date <= boundary
        assert asset.blindness_status == "PASS"


def test_blindness_audit_records_no_evaluation_or_model_annotations():
    audit = json.loads(AUDIT.read_text())
    assert audit == {
        **audit,
        "oos_rows": 20,
        "calibration_overlap": 0,
        "fast_output_columns_in_review_sheet": [],
        "pattern_a_output_columns_in_review_sheet": [],
        "model_annotations_in_stage_charts": 0,
        "model_annotations_in_outcome_charts": 0,
        "stage_chart_future_leak_count": 0,
        "unlabeled_stage_count": 20,
        "unlabeled_outcome_count": 20,
        "evaluation_run_on_oos": False,
        "status": "PASS",
    }


def test_preregistered_protocol_is_complete_and_unevaluated():
    protocol = json.loads(PROTOCOL.read_text())
    required = {
        "version", "base_sha", "oos_set", "oos_sample_count", "calibration_excluded_count",
        "fast_contract", "fast_contract_sha", "pattern_a_frozen_sha", "human_label_taxonomy",
        "human_stage_taxonomy", "evaluation_metrics", "pairing_semantics", "availability_semantics",
        "decision_rules", "inconclusive_rules", "production_frozen",
    }
    assert required <= set(protocol)
    assert protocol["base_sha"] == BASE
    assert protocol["fast_contract"] == "HIERARCHICAL_V01"
    assert protocol["fast_contract_sha"] == "2da3fc36744b27ec13edae3f690df72c796906e5"
    assert protocol["pattern_a_frozen_sha"] == "05d03e16501adbca889488294aaaaa0bd84005de"
    assert protocol["oos_sample_count"] == 20
    assert protocol["calibration_excluded_count"] == 40
    assert protocol["production_frozen"] is False
    assert protocol["evaluation_executed_in_13i_1"] is False
    assert protocol["decision_rules"]["no_retuning_after_labels"] is True
    assert protocol["inconclusive_rules"]["status"] == "OOS_LEAD_INCONCLUSIVE"


def test_primary_score_comparison_and_hard_gate_are_exactly_sealed():
    protocol = json.loads(PROTOCOL.read_text())
    primary = protocol["primary_score_comparison"]
    assert primary == {
        "name": "POSITIVE_STRUCTURE_vs_EARLY_OR_NONE",
        "positive_group": "POSITIVE_STRUCTURE",
        "positive_labels": ["GOOD_TRIGGER", "BORDERLINE_TRIGGER"],
        "negative_group": "EARLY_OR_NONE",
        "negative_labels": ["TOO_EARLY", "NO_SETUP"],
        "metrics": [
            "n_positive", "n_early_or_none", "median_positive", "median_early_or_none",
            "median_difference", "cliffs_delta",
        ],
    }
    assert protocol["secondary_score_comparisons"] == [
        ["GOOD_TRIGGER", "NO_SETUP"],
        ["GOOD_TRIGGER", "FALSE_TRIGGER"],
        ["GOOD_TRIGGER", "TOO_EARLY"],
        ["GOOD_TRIGGER", "TOO_EXTENDED"],
    ]
    gate = protocol["decision_rules"]["score_direction"]
    assert gate["failure_status"] == "OOS_SCORE_DIRECTION_FAIL"
    assert gate["inconclusive_status"] == "INCONCLUSIVE"
    assert gate["minimum_n_per_group"] == 3
    assert "POSITIVE_STRUCTURE vs EARLY_OR_NONE" in gate["rule"]
    assert "median(POSITIVE_STRUCTURE) <= median(EARLY_OR_NONE)" in gate["rule"]


def test_pairing_precedence_matches_frozen_13h_conservative_order():
    protocol = json.loads(PROTOCOL.read_text())
    expected = [
        "DATA_UNAVAILABLE",
        "SAME_WEEK",
        "PATTERN_A_ALREADY_ACTIVE",
        "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT",
        "FAST_EARLIER_PATTERN_A_LATER",
        "FAST_EVENT_NO_PATTERN_A_CATCHUP",
    ]
    assert protocol["pairing_semantics"] == expected
    assert _module().PAIRING_PRECEDENCE == expected
    source = (ROOT / "scripts/research_pattern_a_fast_lead_time_failure.py").read_text(encoding="utf-8")
    positions = [source.index(f'pair_status, next_date = "{status}"') for status in expected]
    assert positions == sorted(positions)


def test_contract_seal_preserves_all_original_blind_assets_from_base():
    assets = pd.read_csv(ASSETS, keep_default_na=False)
    assert len(assets) == 80
    for asset in assets.itertuples(index=False):
        path = ROOT / asset.file_path.replace("artifacts/pattern_a_fast/", "artifacts/patterns/pattern_a_fast/validation/")
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == asset.sha256


def test_contract_seal_base_is_recorded_in_protocol():
    protocol = json.loads(PROTOCOL.read_text())
    assert protocol["contract_seal_base_sha"] == CONTRACT_SEAL_BASE


def test_oos_result_artifacts_are_limited_to_the_frozen_13i_2_evaluation_set():
    allowed = {
        "pattern_a_fast_oos_machine_snapshot_v01.csv",
        "pattern_a_fast_oos_stage_confusion_v01.csv",
        "pattern_a_fast_oos_score_evaluation_v01.json",
        "pattern_a_fast_oos_trigger_events_v01.csv",
        "pattern_a_fast_oos_event_pairing_v01.csv",
        "pattern_a_fast_oos_lead_time_v01.csv",
        "pattern_a_fast_oos_evaluation_summary_v01.json",
    }
    results = OOS / "results"
    assert {path.name for path in results.iterdir() if path.is_file()} == allowed


def test_generator_is_cache_only_and_has_no_evaluator_dependency():
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = ("requests", "urllib", "yfinance", "pykrx", "evaluate_", "research_pattern_a_fast", "score_at_reference", "candidate_state")
    assert not [token for token in forbidden if token in source]
    assert "ParquetCache" in source and "cache.load" in source


def test_frozen_13c_to_13h_and_production_inputs_unchanged_from_base():
    expected_hashes = {
        "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv": "62f02794956ceac2edc08d8c5df2b44ad9e06ac98967d1d77e4572ecf2af0005",
        "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv": "ea71bd1850aa52479d5c09a9d54a45b4f43493147a2bd98a8e93e6ae0d6fed4c",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json": "be0dc21c3764aeb147a3565e65850fc179ecc91e5700e8221932f12ce28ae501",
        "artifacts/patterns/pattern_a_fast/research/feature_role/pattern_a_fast_trigger_event_pair_v01.csv": "a06ef1c9cc674a09421005887adc2696198cc4f6b38381f59abb78d452d467f3",
        "artifacts/patterns/pattern_a_fast/research/feature_role/pattern_a_fast_lead_time_summary_v01.json": "a2569300d4ed877b8eef96dd0d11972cfef75628c9587cf997f8117cdcfca952",
    }
    for path_str, expected in expected_hashes.items():
        actual = hashlib.sha256((ROOT / path_str).read_bytes()).hexdigest()
        assert actual == expected, f"{path_str}: expected {expected}, got {actual}"
