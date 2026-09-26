"""Focused offline contracts for corrected adjusted-price authority cutover."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from trend_scanner.data.adjusted_price_authority_cutover import (
    DEFAULT_EFFECTIVE_DIR,
    DEFAULT_OLD_PIT,
    EXPECTED_EFFECTIVE_POPULATION_COUNT,
    EXPECTED_EFFECTIVE_POPULATION_SHA256,
    EXPECTED_EFFECTIVE_PIT_COUNT,
    EXPECTED_EFFECTIVE_PIT_SHA256,
    EffectiveAuthorityError,
    classify_source_dates,
    load_effective_authority,
)
from trend_scanner.data.adjusted_price_full_population import (
    FullPopulationRunner,
    create_legacy_runner,
    create_production_runner,
    resolve_active_adjusted_price_authority,
)


ROOT = Path(__file__).resolve().parents[1]
FIX02_OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix02"


@pytest.fixture(scope="module")
def authority():
    return load_effective_authority(ROOT / DEFAULT_EFFECTIVE_DIR)


def test_effective_authority_count_and_hash(authority):
    assert authority.population_count == EXPECTED_EFFECTIVE_POPULATION_COUNT == 3149
    assert authority.population_sha256 == EXPECTED_EFFECTIVE_POPULATION_SHA256
    assert authority.pit_count == EXPECTED_EFFECTIVE_PIT_COUNT == 3173
    assert authority.pit_sha256 == EXPECTED_EFFECTIVE_PIT_SHA256


def test_effective_manifest_has_original_lineage(authority):
    manifest = json.loads(authority.manifest_path.read_text(encoding="utf-8"))
    assert manifest["original_population_sha256"].startswith("f14c3d46")
    assert manifest["original_pit_sha256"].startswith("6b542ae0")
    cutover = json.loads((authority.manifest_path.parent / "authority_cutover_manifest.json").read_text(encoding="utf-8"))
    assert cutover["implementation_head"] not in {"", "WORKTREE"}
    assert len(cutover["implementation_head"]) == 40
    assert all(char in "0123456789abcdef" for char in cutover["implementation_head"])
    assert all(not str(cutover[key]).startswith("/") for key in ("effective_population_path", "effective_pit_path", "correction_artifact_path"))


def test_runner_accepts_explicit_effective_authority(authority):
    runner = FullPopulationRunner(
        population_path=authority.population_path,
        pit_path=authority.pit_path,
        expected_population_count=authority.population_count,
        expected_population_sha256=authority.population_sha256,
        expected_pit_sha256=authority.pit_sha256,
        provider=object(),
    )
    assert len(runner.load_population()) == 3149


def test_production_default_resolves_corrected_authority(authority):
    resolved = resolve_active_adjusted_price_authority()
    assert resolved.population_count == 3149
    runner = create_production_runner(store_dir=ROOT / "data/market/adjusted/staging/authority_cutover_fix01_candidate_A/stocks", artifact_dir=ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix01", provider=object())
    assert runner.expected_population_count == 3149
    assert runner.expected_pit_sha256 == authority.pit_sha256
    assert create_legacy_runner(provider=object()).expected_population_count == 3162


def test_old_checkpoint_cannot_be_reused_with_effective_authority(authority, tmp_path):
    runner = FullPopulationRunner(
        population_path=authority.population_path,
        pit_path=authority.pit_path,
        artifact_dir=tmp_path,
        expected_population_count=authority.population_count,
        expected_population_sha256=authority.population_sha256,
        expected_pit_sha256=authority.pit_sha256,
        provider=object(),
    )
    # A tiny, deliberately stale checkpoint makes this contract independent of
    # ignored resume scratch or a historical run's local-only checkpoint.
    checkpoint = asdict(runner.load_or_create_checkpoint(runner.load_population()))
    checkpoint["pit_authority_sha256"] = "0" * 64
    runner.checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(RuntimeError, match="CHECKPOINT_COMPATIBILITY_MISMATCH|CHECKPOINT_AUTHORITY_MISMATCH"):
        runner.load_or_create_checkpoint(runner.load_population())


def test_not_common_source_history_is_not_unexpected(authority):
    old_pit = json.loads((ROOT / DEFAULT_OLD_PIT).read_text(encoding="utf-8"))["intervals"]
    parts = classify_source_dates("123840", ["2013-09-23", "2013-09-24"], authority, old_pit)
    assert "2013-09-23" in parts["source_history_outside_common_eligibility"]
    assert parts["unexpected"] == []


def test_unexplained_source_date_still_blocks(authority):
    old_pit = json.loads((ROOT / DEFAULT_OLD_PIT).read_text(encoding="utf-8"))["intervals"]
    parts = classify_source_dates("123840", ["2009-12-31"], authority, old_pit)
    assert parts["unexpected"] == ["2009-12-31"]


def test_removed_pure_spac_identities_are_absent(authority):
    removed = {"121910", "121950", "122290", "122750", "123160", "123290", "123300", "123550", "123910", "124050", "126680", "128910", "380440"}
    assert removed.isdisjoint({record["ticker"] for record in authority.population})


def test_source_history_rows_remain_outside_eligibility(authority):
    old_pit = json.loads((ROOT / DEFAULT_OLD_PIT).read_text(encoding="utf-8"))["intervals"]
    parts = classify_source_dates("123840", ["2011-05-02"], authority, old_pit)
    assert parts["source_history_outside_common_eligibility"] == ["2011-05-02"]


def test_envelope_gap_alone_does_not_imply_not_common():
    class SyntheticAuthority:
        pit_intervals = ({"ticker": "T", "state": "COMMON", "effective_from": "2010-01-01", "effective_to": "2010-01-10"},)

        def pit_common_dates(self, ticker, calendar_dates):
            return {date for date in calendar_dates if date == "2010-01-01"}

        def confirmed_non_common_evidence(self, ticker, date):
            return None

    parts = classify_source_dates("T", ["2010-01-01", "2010-01-05"], SyntheticAuthority(), ())
    assert parts["common"] == ["2010-01-01"]
    assert parts["unexpected"] == ["2010-01-05"]


def test_unknown_is_not_not_common_even_for_reused_ticker():
    class ReusedTickerAuthority:
        pit_intervals = ()

        def pit_common_dates(self, ticker, calendar_dates):
            return set()

        def confirmed_non_common_evidence(self, ticker, date):
            return None

    parts = classify_source_dates("REUSED", ["2014-01-02"], ReusedTickerAuthority(), ())
    assert parts["unexpected"] == ["2014-01-02"]


def test_exact_authority_matches_current_accepted_closure(authority):
    assert len(authority.confirmed_non_common_dates) == 3089
    assert len(authority.confirmed_non_common_intervals) == 10
    summary = json.loads((FIX02_OUT / "production_zero_call_run/full_population_summary.json").read_text(encoding="utf-8"))
    binding = json.loads((FIX02_OUT / "authority_manifest_binding.json").read_text(encoding="utf-8"))
    assert binding["matches_fix02_code_head"] is True
    assert binding["population_count"] == authority.population_count
    assert summary["frozen_authority"]["population_count"] == authority.population_count
    assert summary["frozen_authority"]["population_manifest_sha256"] == authority.population_sha256
    assert summary["status_counts"]["closure_complete_total"] == authority.population_count


def test_current_accepted_artifacts_are_bound_and_deterministic():
    manifest = json.loads((FIX02_OUT / "artifact_manifest.json").read_text(encoding="utf-8"))
    binding = json.loads((FIX02_OUT / "authority_manifest_binding.json").read_text(encoding="utf-8"))
    consistency = json.loads((FIX02_OUT / "operational_artifact_consistency.json").read_text(encoding="utf-8"))
    assert binding["matches_fix02_code_head"] is True
    assert binding["portable_paths"] is True
    assert consistency["all_execution_ids_same"] is True
    assert consistency["summary_closure_verdict_match"] is True
    assert consistency["summary_closure_next_state_match"] is True
    for relative_path, expected_sha256 in manifest["files"].items():
        artifact_path = FIX02_OUT / relative_path
        assert artifact_path.is_file(), relative_path
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == expected_sha256, relative_path


def test_current_production_zero_network_run_closes_authority():
    result = json.loads((FIX02_OUT / "production_zero_call_result.json").read_text(encoding="utf-8"))
    summary = json.loads((FIX02_OUT / "production_zero_call_run/full_population_summary.json").read_text(encoding="utf-8"))
    closure = json.loads((FIX02_OUT / "production_zero_call_run/full_population_closure_manifest.json").read_text(encoding="utf-8"))
    assert result["final_verdict"] == "ACCEPT"
    assert result["provider_calls"] == result["physical_attempts"] == result["network_calls_performed"] == 0
    assert result["reused_without_network"] == result["population_total"]
    assert summary["status_counts"]["closure_complete_total"] == result["population_total"]
    assert closure["completed_count"] == result["population_total"]
    assert closure["failure_count"] == closure["total_unresolved_authority_conflicts"] == 0
