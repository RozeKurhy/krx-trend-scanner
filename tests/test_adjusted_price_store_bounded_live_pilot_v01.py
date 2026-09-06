"""Tests for Adjusted Price Store Bounded Live Pilot (FIX07)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    CANONICAL_CALENDAR_CUTOFF,
    CANONICAL_EXECUTION_ID,
    DEFAULT_ACTUAL_SOURCE_DATES_PATH,
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_CLOSURE_MANIFEST_PATH,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
    PilotResult,
    PilotSample,
    PilotSampleGroup,
    SourceEligibilityStatus,
    SourceResponseStatus,
    build_pilot_sample_manifest,
    evaluate_pilot_acceptance,
    execute_single_pilot_query,
    is_nontradable_or_phantom_row,
    load_historical_suspension_authority,
    resolve_expected_coverage,
    run_bounded_live_pilot,
)
from trend_scanner.data.adjusted_price_provider import (
    AdjustedPriceDataProvider,
    normalize_ticker,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)


def test_frozen_population_hash_gate_matches_canonical():
    """Verify frozen population count and SHA256 integrity."""
    records = load_historical_common_population(DEFAULT_POPULATION_ARTIFACT_PATH)
    assert len(records) == EXPECTED_POPULATION_COUNT == 3162
    calc_sha = population_manifest_sha256(records)
    assert calc_sha == EXPECTED_POPULATION_SHA256


def test_sample_authority_assertions_group_b_rejects_current_common():
    """Verify Group B sample authority strictly rejects currently-common tickers like 001040."""
    manifest = build_pilot_sample_manifest()
    group_b_samples = [s for s in manifest if s.sample_group == PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED]
    assert len(group_b_samples) == 5

    group_b_tickers = {s.ticker for s in group_b_samples}
    assert "001040" not in group_b_tickers
    assert group_b_tickers == {"000030", "000060", "000360", "000470", "002670"}

    for s in group_b_samples:
        assert s.historical_only is True
        assert s.currently_common is False
        assert s.last_common_date < "2026-08-21"


def test_sample_authority_assertions_group_d_is_exact_23_census():
    """Verify Group D contains all 23 alphanumeric common stocks in the population."""
    manifest = build_pilot_sample_manifest()
    group_d_samples = [s for s in manifest if s.sample_group == PilotSampleGroup.GROUP_D_ALPHA]
    assert len(group_d_samples) == 23
    for s in group_d_samples:
        assert s.numeric_or_alpha == "alphanumeric"


def test_production_provider_normalizes_valid_alpha_and_numeric():
    """Verify production normalize_ticker supports ^[0-9A-Z]{6}$ and rejects invalid."""
    assert normalize_ticker("005930") == "005930"
    assert normalize_ticker("5930") == "005930"
    assert normalize_ticker("0008Z0") == "0008Z0"
    assert normalize_ticker("0001A0") == "0001A0"
    assert normalize_ticker("00781K") == "00781K"

    with pytest.raises(MarketDataError):
        normalize_ticker("")
    with pytest.raises(MarketDataError):
        normalize_ticker("TOOLONG123")
    with pytest.raises(MarketDataError):
        normalize_ticker("00593#")
    with pytest.raises(MarketDataError):
        normalize_ticker("abc")


class MockDummyProvider:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame
        self.call_count = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.call_count += 1
        return self._frame


def test_canonical_live_artifacts_remain_unmodified_after_hermetic_reuse(tmp_path):
    """Verify Section 21 & 32: Hermetic REUSE execution modifies 0 tracked files and preserves canonical SHA256."""
    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    target_files = [
        "pilot_summary.json",
        "pilot_results.csv",
        "pilot_actual_source_dates.json",
        "pilot_sample_manifest.json",
        "pilot_closure_manifest.json",
        "historical_suspension_authority_v01.json",
    ]
    before_hashes = {f: hashlib.sha256((canonical_dir / f).read_bytes()).hexdigest() for f in target_files}

    hermetic_out = tmp_path / "reuse_verification"
    res = run_bounded_live_pilot(input_dir=canonical_dir, output_dir=hermetic_out, mode="reuse")
    summary = res["summary"]

    assert summary["final_verdict"] == "ACCEPT"
    assert summary["execution_provenance"]["execution_mode"] == "REUSE"
    assert summary["execution_provenance"]["new_live_request_count"] == 0
    assert summary["execution_provenance"]["reused_sample_count"] == 43
    assert summary["quality_validation"]["ohlc_quality_revalidated"] is False
    assert summary["quality_validation"]["coverage_revalidated"] is True

    # Check output written to tmp_path only
    assert (hermetic_out / "reuse_results.csv").exists()
    assert (hermetic_out / "reuse_summary.json").exists()

    after_hashes = {f: hashlib.sha256((canonical_dir / f).read_bytes()).hexdigest() for f in target_files}
    for f in target_files:
        assert before_hashes[f] == after_hashes[f], f"Canonical artifact {f} was modified by REUSE!"


def test_reuse_missing_manifest_fails_closed(tmp_path):
    """Verify Section 18: REUSE without pilot_closure_manifest.json fails closed with REUSE_TRUST_MANIFEST_MISSING."""
    test_dir = tmp_path / "no_manifest_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    (test_dir / "pilot_actual_source_dates.json").write_text(
        (canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="REUSE_TRUST_MANIFEST_MISSING"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_invalid_manifest_fails_closed(tmp_path):
    """Verify Section 19: REUSE with incomplete closure manifest fails closed with REUSE_TRUST_MANIFEST_INVALID."""
    test_dir = tmp_path / "invalid_manifest_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    (test_dir / "pilot_actual_source_dates.json").write_text(
        (canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Missing required keys
    (test_dir / "pilot_closure_manifest.json").write_text(
        '{"schema": "invalid", "canonical_execution_id": "test"}', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="REUSE_TRUST_MANIFEST_INVALID"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_missing_sample_manifest_fails_closed(tmp_path):
    """Verify FIX07 Major 1: REUSE without pilot_sample_manifest.json fails closed with REUSE_SAMPLE_MANIFEST_MISSING."""
    test_dir = tmp_path / "no_sample_manifest"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_closure_manifest.json", "pilot_actual_source_dates.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_MANIFEST_MISSING"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_missing_suspension_authority_fails_closed(tmp_path):
    """Verify FIX07 Major 1: REUSE without historical_suspension_authority_v01.json fails closed with REUSE_SUSPENSION_AUTHORITY_MISSING."""
    test_dir = tmp_path / "no_suspension_auth"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_closure_manifest.json", "pilot_actual_source_dates.json", "pilot_sample_manifest.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SUSPENSION_AUTHORITY_MISSING"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_hash_mismatch_fails_closed(tmp_path):
    """Verify Section 10: REUSE fails closed with REUSE_HASH_MISMATCH if actual source dates artifact is modified."""
    test_dir = tmp_path / "tampered_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_closure_manifest.json", "pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")
    (test_dir / "pilot_actual_source_dates.json").write_text(
        '{"schema": "tampered", "execution_id": "ADJUSTED_PRICE_PILOT_FIX04_1787819364_LIVE", "samples": []}', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="REUSE_HASH_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_execution_id_mismatch_fails_closed(tmp_path):
    """Verify Section 11: REUSE fails closed with REUSE_EXECUTION_ID_MISMATCH if execution id does not match trusted."""
    test_dir = tmp_path / "id_mismatch_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    act_content = (canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8")
    tampered_act_content = act_content.replace(CANONICAL_EXECUTION_ID, "OTHER_EXEC_ID")
    tampered_sha = hashlib.sha256(tampered_act_content.encode("utf-8")).hexdigest()

    manifest_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    manifest_data["pilot_actual_source_dates_sha256"] = tampered_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    (test_dir / "pilot_actual_source_dates.json").write_text(tampered_act_content, encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_EXECUTION_ID_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_sample_manifest_hash_mismatch_fails_closed(tmp_path):
    """Verify Section 12: REUSE fails closed with REUSE_SAMPLE_MANIFEST_HASH_MISMATCH if sample manifest is modified."""
    test_dir = tmp_path / "sample_manifest_mismatch"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_closure_manifest.json", "pilot_actual_source_dates.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    (test_dir / "pilot_sample_manifest.json").write_text('[]', encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_MANIFEST_HASH_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_suspension_authority_hash_mismatch_fails_closed(tmp_path):
    """Verify Section 13: REUSE fails closed with REUSE_SUSPENSION_AUTHORITY_HASH_MISMATCH if suspension authority is modified."""
    test_dir = tmp_path / "suspension_mismatch"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_closure_manifest.json", "pilot_actual_source_dates.json", "pilot_sample_manifest.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    (test_dir / "historical_suspension_authority_v01.json").write_text('{"records": []}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SUSPENSION_AUTHORITY_HASH_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_actual_evidence_extra_sample_fails_closed(tmp_path):
    """Verify FIX07 Major 2: REUSE with extra sample in actual dates artifact fails closed with REUSE_SAMPLE_CONTRACT_MISMATCH."""
    test_dir = tmp_path / "extra_sample_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    act_data = json.loads((canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"))
    extra_sample = dict(act_data["samples"][0])
    extra_sample["ticker"] = "999999"
    act_data["samples"].append(extra_sample)

    new_act_content = json.dumps(act_data)
    new_sha = hashlib.sha256(new_act_content.encode("utf-8")).hexdigest()
    (test_dir / "pilot_actual_source_dates.json").write_text(new_act_content, encoding="utf-8")

    manifest_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    manifest_data["pilot_actual_source_dates_sha256"] = new_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_CONTRACT_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_actual_evidence_missing_sample_fails_closed(tmp_path):
    """Verify FIX07 Major 2: REUSE with missing sample in actual dates artifact fails closed with REUSE_SAMPLE_CONTRACT_MISMATCH."""
    test_dir = tmp_path / "missing_sample_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    act_data = json.loads((canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"))
    act_data["samples"] = act_data["samples"][1:]  # Drop first sample

    new_act_content = json.dumps(act_data)
    new_sha = hashlib.sha256(new_act_content.encode("utf-8")).hexdigest()
    (test_dir / "pilot_actual_source_dates.json").write_text(new_act_content, encoding="utf-8")

    manifest_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    manifest_data["pilot_actual_source_dates_sha256"] = new_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_CONTRACT_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_actual_evidence_duplicate_sample_fails_closed(tmp_path):
    """Verify FIX07 Major 2: REUSE with duplicate sample in actual dates artifact fails closed with REUSE_ACTUAL_EVIDENCE_DUPLICATE_SAMPLE."""
    test_dir = tmp_path / "dup_sample_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    act_data = json.loads((canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"))
    act_data["samples"].append(dict(act_data["samples"][0]))  # Duplicate first sample

    new_act_content = json.dumps(act_data)
    new_sha = hashlib.sha256(new_act_content.encode("utf-8")).hexdigest()
    (test_dir / "pilot_actual_source_dates.json").write_text(new_act_content, encoding="utf-8")

    manifest_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    manifest_data["pilot_actual_source_dates_sha256"] = new_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_ACTUAL_EVIDENCE_DUPLICATE_SAMPLE"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_sample_group_mismatch_fails_closed(tmp_path):
    """Verify FIX07 Major 2: REUSE with sample_group mismatch fails closed with REUSE_SAMPLE_CONTRACT_MISMATCH."""
    test_dir = tmp_path / "group_mismatch_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_sample_manifest.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    act_data = json.loads((canonical_dir / "pilot_actual_source_dates.json").read_text(encoding="utf-8"))
    # Change sample group of first sample from GROUP_A_NUMERIC to GROUP_E_MARKET_TRANSFER
    act_data["samples"][0]["sample_group"] = "GROUP_E_MARKET_TRANSFER"

    new_act_content = json.dumps(act_data)
    new_sha = hashlib.sha256(new_act_content.encode("utf-8")).hexdigest()
    (test_dir / "pilot_actual_source_dates.json").write_text(new_act_content, encoding="utf-8")

    manifest_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    manifest_data["pilot_actual_source_dates_sha256"] = new_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_CONTRACT_MISMATCH"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_canonical_manifest_duplicate_sample_fails_closed(tmp_path):
    """Verify FIX07 Section 18: Canonical sample manifest with duplicate sample fails closed with REUSE_SAMPLE_CONTRACT_DUPLICATE."""
    test_dir = tmp_path / "manifest_dup_pilot"
    test_dir.mkdir()

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    for f in ["pilot_actual_source_dates.json", "historical_suspension_authority_v01.json"]:
        (test_dir / f).write_text((canonical_dir / f).read_text(encoding="utf-8"), encoding="utf-8")

    manifest_records = json.loads((canonical_dir / "pilot_sample_manifest.json").read_text(encoding="utf-8"))
    manifest_records.append(dict(manifest_records[0]))

    new_manifest_content = json.dumps(manifest_records)
    new_manifest_sha = hashlib.sha256(new_manifest_content.encode("utf-8")).hexdigest()
    (test_dir / "pilot_sample_manifest.json").write_text(new_manifest_content, encoding="utf-8")

    closure_data = json.loads((canonical_dir / "pilot_closure_manifest.json").read_text(encoding="utf-8"))
    closure_data["pilot_sample_manifest_sha256"] = new_manifest_sha
    (test_dir / "pilot_closure_manifest.json").write_text(json.dumps(closure_data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REUSE_SAMPLE_CONTRACT_DUPLICATE"):
        run_bounded_live_pilot(input_dir=test_dir, mode="reuse")


def test_reuse_calendar_runtime_drift_fails_closed(tmp_path):
    """Verify FIX07 Minor 1: Runtime canonical calendar drift fails closed with REUSE_CALENDAR_DRIFT."""
    fake_cal = tmp_path / "drifted_calendar.json"
    fake_cal.write_text(
        json.dumps({"cutoff_date": "2026-08-14", "trading_dates": ["2026-08-14"] * 3800}), encoding="utf-8"
    )

    canonical_dir = Path(DEFAULT_ARTIFACT_DIR)
    with pytest.raises(RuntimeError, match="REUSE_CALENDAR_DRIFT"):
        run_bounded_live_pilot(
            input_dir=canonical_dir,
            output_dir=tmp_path / "reuse_verification",
            canonical_calendar_path=fake_cal,
            mode="reuse",
        )


def test_suspension_authority_artifact_sha_and_records():
    """Verify Section 36: suspension authority artifact loads valid records and SHA256."""
    halts_map, sha = load_historical_suspension_authority(DEFAULT_SUSPENSION_AUTHORITY_PATH)
    assert len(sha) == 64
    assert "000030" in halts_map
    assert len(halts_map["000030"]) == 22
    assert "000060" in halts_map
    assert len(halts_map["000060"]) == 29
    assert "000360" in halts_map
    assert len(halts_map["000360"]) == 71
    assert "000470" in halts_map
    assert len(halts_map["000470"]) == 25
    assert "002670" in halts_map
    assert len(halts_map["002670"]) == 27
    assert "035720" in halts_map
    assert len(halts_map["035720"]) == 3


def test_no_circular_expected_mutation_and_pit_approximation_gap_fails():
    """Verify PIT approximation gap without independent evidence does NOT rewrite expected and fails FULL."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"])
    frame = pd.DataFrame(
        {"open": [100.0] * 4, "high": [105.0] * 4, "low": [95.0] * 4, "close": [100.0] * 4},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="999999",
        isu_cd=["KR7999999001"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED,
        numeric_or_alpha="numeric",
        first_common_date="2024-01-02",
        last_common_date="2024-01-08",
        query_start="2024-01-02",
        query_end="2024-01-08",
        sample_reason="test",
        currently_common=False,
        historical_only=True,
    )
    resolution = ExpectedCoverageResolution(
        ticker="999999",
        query_start="2024-01-02",
        query_end="2024-01-08",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="PIT_COMMON_INTERVAL_CALENDAR",
        authority_quality=AuthorityQuality.PIT_CALENDAR_APPROXIMATION.value,
        raw_observed_count=5,
        excluded_nontradable_count=0,
        expected_tradable_count=5,
        expected_tradable_dates=("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"),
        nontradable_dates=(),
        source_path="test",
    )

    res, act_dates = execute_single_pilot_query(sample, provider=mock, resolution=resolution)

    # 1. Expected resolution is NOT mutated to 4 dates
    assert res.expected_observation_count == 5
    assert resolution.expected_tradable_count == 5

    # 2. Missing is detected honestly
    assert res.missing_expected_count == 1
    assert res.coverage_status == CoverageStatus.INTERNAL_GAPS.value

    # 3. Not promoted to FULL
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value


def test_all_group_acceptance_gate_negative_controls():
    """Verify Section 29: evaluating acceptance fails if any group (A, B, C, D, E) or global metric fails."""
    def _dummy_res(group: str, status: str = "ELIGIBLE_FULL", missing: int = 0, unexpected: int = 0, auth_status: str = "VALID") -> PilotResult:
        return PilotResult(
            ticker="005930",
            isu_cd="KR7005930003",
            market="KOSPI",
            sample_group=group,
            numeric_or_alpha="numeric",
            source="PyKRX",
            adjusted=True,
            request_start="2024-01-02",
            request_end="2024-01-04",
            attempt_count=1,
            source_status="SUCCESS",
            coverage_status="FULL_EXPECTED_COVERAGE" if (missing == 0 and unexpected == 0) else "INTERNAL_GAPS",
            eligibility_status=status,
            expected_authority_status=auth_status,
            expected_authority_source="TEST",
            expected_authority_quality="TEST",
            raw_observed_count=3,
            excluded_nontradable_count=0,
            expected_observation_count=3,
            actual_source_row_count=3 if missing == 0 else 2,
            matched_expected_count=3 if missing == 0 else 2,
            missing_expected_count=missing,
            unexpected_source_date_count=unexpected,
            first_expected_date="2024-01-02",
            last_expected_date="2024-01-04",
            first_actual_date="2024-01-02",
            last_actual_date="2024-01-04",
            coverage_ratio=1.0 if missing == 0 else 0.67,
            duplicate_count=0,
            invalid_ohlc_count=0,
            future_row_count=0,
            error_type=None,
            error_message_sanitized=None,
            evidence_summary="test",
        )

    base_results = (
        [_dummy_res(PilotSampleGroup.GROUP_A_NUMERIC.value) for _ in range(8)]
        + [_dummy_res(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value) for _ in range(5)]
        + [_dummy_res(PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value) for _ in range(4)]
        + [_dummy_res(PilotSampleGroup.GROUP_D_ALPHA.value) for _ in range(23)]
        + [_dummy_res(PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value) for _ in range(3)]
    )

    eval_pass = evaluate_pilot_acceptance(base_results)
    assert eval_pass["final_verdict"] == "ACCEPT"

    # 1. Group A inject failure
    res_fail_a = list(base_results)
    res_fail_a[0] = _dummy_res(PilotSampleGroup.GROUP_A_NUMERIC.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_a)["final_verdict"] == "CHANGES_REQUESTED"

    # 2. Group B inject failure
    res_fail_b = list(base_results)
    res_fail_b[8] = _dummy_res(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_b)["final_verdict"] == "CHANGES_REQUESTED"

    # 3. Group C inject failure
    res_fail_c = list(base_results)
    res_fail_c[13] = _dummy_res(PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value, status="ELIGIBLE_PARTIAL", unexpected=1)
    assert evaluate_pilot_acceptance(res_fail_c)["final_verdict"] == "CHANGES_REQUESTED"

    # 4. Group D inject failure (22/23)
    res_fail_d = list(base_results)
    res_fail_d[17] = _dummy_res(PilotSampleGroup.GROUP_D_ALPHA.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_d)["final_verdict"] == "CHANGES_REQUESTED"

    # 5. Group E inject failure
    res_fail_e = list(base_results)
    res_fail_e[40] = _dummy_res(PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value, status="ELIGIBLE_PARTIAL", auth_status="INSUFFICIENT_AUTHORITY")
    assert evaluate_pilot_acceptance(res_fail_e)["final_verdict"] == "CHANGES_REQUESTED"


def test_canonical_closure_manifest_integrity():
    """Verify Section 30 & 38: Canonical closure manifest matches exact artifact hashes and proves ACCEPT gate."""
    artifact_dir = Path(DEFAULT_ARTIFACT_DIR)
    manifest_file = artifact_dir / "pilot_sample_manifest.json"
    results_file = artifact_dir / "pilot_results.csv"
    summary_file = artifact_dir / "pilot_summary.json"
    actual_dates_file = artifact_dir / "pilot_actual_source_dates.json"
    suspension_file = artifact_dir / "historical_suspension_authority_v01.json"
    closure_file = artifact_dir / "pilot_closure_manifest.json"

    assert manifest_file.exists()
    assert results_file.exists()
    assert summary_file.exists()
    assert actual_dates_file.exists()
    assert suspension_file.exists()
    assert closure_file.exists()

    with open(summary_file, encoding="utf-8") as f:
        summary_data = json.load(f)
    with open(closure_file, encoding="utf-8") as f:
        closure_data = json.load(f)

    # 1. Exact Execution Provenance Matches Canonical LIVE
    assert summary_data["execution_id"] == CANONICAL_EXECUTION_ID == closure_data["canonical_execution_id"]
    assert summary_data["execution_provenance"]["execution_mode"] == "LIVE" == closure_data["canonical_execution_mode"]
    assert summary_data["execution_provenance"]["new_live_request_count"] == 43
    assert summary_data["execution_provenance"]["reused_sample_count"] == 0
    assert summary_data["request_accounting"]["cumulative_total_pykrx_requests"] == 129
    assert summary_data["final_verdict"] == "ACCEPT" == closure_data["final_verdict"]

    # 2. Exact Hash Pinning Matches File Bytes
    assert hashlib.sha256(summary_file.read_bytes()).hexdigest() == closure_data["pilot_summary_sha256"]
    assert hashlib.sha256(results_file.read_bytes()).hexdigest() == closure_data["pilot_results_sha256"]
    assert hashlib.sha256(actual_dates_file.read_bytes()).hexdigest() == closure_data["pilot_actual_source_dates_sha256"]
    assert hashlib.sha256(manifest_file.read_bytes()).hexdigest() == closure_data["pilot_sample_manifest_sha256"]
    assert hashlib.sha256(suspension_file.read_bytes()).hexdigest() == closure_data["historical_suspension_authority_sha256"]
