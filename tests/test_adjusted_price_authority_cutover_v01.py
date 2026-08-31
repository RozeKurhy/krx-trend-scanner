"""Focused offline contracts for corrected adjusted-price authority cutover."""

from __future__ import annotations

import json
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
FIX01_OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix01"


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
    old = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/fresh_full_population_run_v01/full_population_checkpoint.json"
    checkpoint = json.loads(old.read_text(encoding="utf-8"))
    path = tmp_path / "full_population_checkpoint.json"
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    runner = FullPopulationRunner(
        population_path=authority.population_path,
        pit_path=authority.pit_path,
        artifact_dir=tmp_path,
        expected_population_count=authority.population_count,
        expected_population_sha256=authority.population_sha256,
        expected_pit_sha256=authority.pit_sha256,
        provider=object(),
    )
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


def test_exact_authority_reconciles_3089_and_additional_1615(authority):
    assert len(authority.confirmed_non_common_dates) == 3089
    assert len(authority.confirmed_non_common_intervals) == 10
    census = json.loads((FIX01_OUT / "outside_common_4704_reconciliation.json").read_text(encoding="utf-8"))
    assert census["old_current_outside_total"] == 4704
    assert census["category_counts"]["ACCEPTED_SPAC_NON_COMMON"] == 3089
    assert census["category_counts"]["OTHER_AUTHORITY_CONFIRMED_NON_COMMON"] == 1615
    assert census["category_counts"]["UNRESOLVED"] == 0
    assert census["sum_check"] is True


def test_clean_room_candidates_are_measured_and_deterministic():
    a = json.loads((FIX01_OUT / "candidate_a_integrity.json").read_text(encoding="utf-8"))
    b = json.loads((FIX01_OUT / "candidate_b_integrity.json").read_text(encoding="utf-8"))
    determinism = json.loads((FIX01_OUT / "candidate_determinism_comparison.json").read_text(encoding="utf-8"))
    assert a["integrity_pass"] is True and b["integrity_pass"] is True
    assert a["parquet_count"] == a["metadata_pair_count"] == 3145
    assert a["zero_store_success_count"] == 4
    assert a["unreadable_files"] == a["future_rows"] == a["source_invalid_ohlc_rows"] == 0
    assert a["analytic_invalid_source_native_rows"] > 0
    assert determinism["deterministic"] is True


def test_actual_production_zero_network_passes_and_special_cases():
    first = json.loads((FIX01_OUT / "first_production_zero_network_pass.json").read_text(encoding="utf-8"))
    second = json.loads((FIX01_OUT / "second_production_zero_call_pass.json").read_text(encoding="utf-8"))
    assert first["provider_calls"] == second["provider_calls"] == 0
    assert first["result"]["summary"]["status_counts"]["closure_complete_total"] == 3149
    assert second["result"]["summary"]["network_accounting"]["reused_without_network"] == 3149
    assert json.loads((FIX01_OUT / "special_case_000610.json").read_text(encoding="utf-8"))["validator"] == "PASS"
    assert json.loads((FIX01_OUT / "special_case_000360.json").read_text(encoding="utf-8"))["resolved_authority_conflict_count"] == 1
