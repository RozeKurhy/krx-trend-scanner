"""Offline contract tests for historical universe authority reconciliation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket

import pytest

from trend_scanner.universe.historical_authority_reconciliation import (
    AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION,
    BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
    CLASS_COMMON,
    CLASS_NOT_COMMON,
    CLASS_UNRESOLVED,
    DEFAULT_TARGET_IDENTITY_PATH,
    HISTORICAL_AUTHORITY_UNRESOLVED,
    HISTORICAL_COMMON_REQUIRED,
    HISTORICAL_NOT_COMMON,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    SUPPLEMENTAL_AUTHORITY_ACTIVE_SPAC_AT_HISTORICAL_CUTOFF,
    SUPPLEMENTAL_AUTHORITY_MERGER_WITHDRAWN_SPAC_IDENTITY_PRESERVED,
    SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED,
    SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED,
    SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED,
    SUPPLEMENTAL_AUTHORITY_SPAC_TERMINATION_IN_PROGRESS_NO_COMMON_TRANSITION,
    SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT,
    ReconciliationContractError,
    build_denominator_candidate,
    build_pit_identity_timeline,
    canonical_target_identity_records,
    classify_security_type,
    derive_target_identities,
    evaluate_denominator_freeze_gate,
    evaluate_survivorship_bias_gate,
    evaluate_ticker_identity_reuse_gate,
    load_basic_info_snapshots,
    load_supplemental_authority_records,
    load_target_identities,
    reconcile_target_identities,
    run_reconciliation_preflight,
    target_identity_set_hash,
)


ROOT = Path(__file__).resolve().parents[1]
_ENDPOINT = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}


def _write_acquisition_fixture(
    tmp_path: Path,
    dates: list[str],
    rows_by_date_market: dict[tuple[str, str], list[dict[str, str]]],
    *,
    tamper_sha_for: tuple[str, str] | None = None,
    wrong_row_count_for: tuple[str, str] | None = None,
    drop_entry_for: tuple[str, str] | None = None,
    extra_entry: bool = False,
    non_complete_status_for: tuple[str, str] | None = None,
    final_summary_status: str = READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    runner_status: str = "COMPLETE",
    frozen_checkpoint_sha_override: str | None = None,
    omit_checkpoint_manifest_sha: bool = False,
    omit_final_summary_fields: tuple[str, ...] = (),
    target_count_override: int | None = None,
    completed_count_override: int | None = None,
    pending_count_override: int | None = None,
) -> tuple[Path, Path, Path]:
    """Write a raw Basic Info archive plus a matching acquisition
    checkpoint/final-summary fixture, with optional corruption knobs for the
    MAJOR-01/FIX02 acquisition-authority-binding gate tests."""

    raw_root = tmp_path / "basic_info"
    entries: dict[str, dict[str, object]] = {}
    for day in dates:
        bas_dd = day.replace("-", "")
        for market in ("KOSPI", "KOSDAQ"):
            rows = rows_by_date_market[(day, market)]
            content = json.dumps({"OutBlock_1": rows}, ensure_ascii=False).encode("utf-8")
            path = raw_root / day[:4] / bas_dd / f"{market}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            if tamper_sha_for == (day, market):
                digest = "0" * 64
            row_count = len(rows) if wrong_row_count_for != (day, market) else len(rows) + 1
            key = f"{bas_dd}|{market}|{_ENDPOINT[market]}"
            if drop_entry_for == (day, market):
                continue
            entries[key] = {
                "basDd": bas_dd,
                "market": market,
                "endpoint": _ENDPOINT[market],
                "status": "COMPLETE" if non_complete_status_for != (day, market) else "PAUSED_QUOTA",
                "raw_path": str(path),
                "raw_content_sha256": digest,
                "row_count": row_count,
                "schema_validation": "PASS",
                "identity_validation": "PASS",
            }
    if extra_entry:
        entries["99999999|KOSPI|stk_isu_base_info"] = {
            "basDd": "99999999", "market": "KOSPI", "endpoint": "stk_isu_base_info",
            "status": "COMPLETE", "raw_path": "unused", "raw_content_sha256": "f" * 64,
            "row_count": 0, "schema_validation": "PASS", "identity_validation": "PASS",
        }
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_bytes = json.dumps(
        {"schema_version": "KRX_HISTORICAL_INSTRUMENT_ACQUISITION_V01", "entries": entries}
    ).encode("utf-8")
    checkpoint_path.write_bytes(checkpoint_bytes)

    expected_pair_count = len(dates) * 2
    final_summary: dict[str, object] = {
        "schema_version": "KRX_HISTORICAL_UNIVERSE_ACQUISITION_CLOSURE_V01",
        "status": final_summary_status,
        "runner_status": runner_status,
        "target_count": target_count_override if target_count_override is not None else expected_pair_count,
        "completed_count": completed_count_override if completed_count_override is not None else expected_pair_count,
        "pending_count": pending_count_override if pending_count_override is not None else 0,
        "failures": 0,
        "schema_failures": 0,
        "identity_failures": 0,
        "quota_pause": False,
        "raw_file_count": expected_pair_count,
    }
    if not omit_checkpoint_manifest_sha:
        final_summary["checkpoint_manifest_sha256"] = (
            frozen_checkpoint_sha_override
            if frozen_checkpoint_sha_override is not None
            else hashlib.sha256(checkpoint_bytes).hexdigest()
        )
    for field in omit_final_summary_fields:
        final_summary.pop(field, None)
    final_summary_path = tmp_path / "acquisition_final_summary.json"
    final_summary_path.write_text(json.dumps(final_summary), encoding="utf-8")
    return raw_root, checkpoint_path, final_summary_path


def _coordinated_tamper(
    checkpoint_path: Path,
    raw_root: Path,
    day: str,
    market: str,
    new_rows: list[dict[str, str]],
) -> None:
    """Mutate a raw file AND its checkpoint entry so raw<->checkpoint stay
    internally consistent, while the checkpoint FILE BYTES (and therefore its
    overall SHA256) change — this is the coordinated tamper that a frozen
    closure checkpoint_manifest_sha256 must still catch (Section 33)."""

    bas_dd = day.replace("-", "")
    path = raw_root / day[:4] / bas_dd / f"{market}.json"
    content = json.dumps({"OutBlock_1": new_rows}, ensure_ascii=False).encode("utf-8")
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    key = f"{bas_dd}|{market}|{_ENDPOINT[market]}"
    payload["entries"][key]["raw_content_sha256"] = digest
    payload["entries"][key]["row_count"] = len(new_rows)
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")


def _target(ticker: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "identity_key": f"ticker:{ticker}",
        "identity_type": "numeric" if ticker.isdigit() else "alphanumeric",
        "current_presence": False,
        "source": "synthetic fixture",
    }


def _row(
    ticker: str,
    *,
    isu_cd: str | None = None,
    market: str = "KOSDAQ",
    group: str = "주권",
    kind: str = "보통주",
    sector: str = "",
) -> dict[str, str]:
    return {
        "ISU_CD": isu_cd or f"KR{ticker}",
        "ISU_SRT_CD": ticker,
        "MKT_TP_NM": market,
        "LIST_DD": "20100104",
        "SECUGRP_NM": group,
        "KIND_STKCERT_TP_NM": kind,
        "SECT_TP_NM": sector,
    }


def _snapshot(day: str, *rows: dict[str, str]) -> dict[str, object]:
    return {
        "effective_date": day,
        "effective_date_source": "REQUEST_BAS_DD",
        "market": "KOSDAQ",
        "endpoint": "ksq_isu_base_info",
        "rows": list(rows),
    }


def test_target_identity_artifact_has_frozen_1116_contract() -> None:
    loaded = load_target_identities(ROOT / DEFAULT_TARGET_IDENTITY_PATH)
    assert loaded["counts"] == {"total": 1116, "numeric": 1058, "alphanumeric": 58}
    assert len(loaded["identities"]) == 1116
    assert loaded["target_identity_set_sha256"] == target_identity_set_hash(loaded["identities"])
    assert all(isinstance(row["ticker"], str) for row in loaded["identities"])


def test_target_hash_is_order_independent_and_preserves_alpha() -> None:
    records = [_target("005930"), _target("00088K")]
    assert target_identity_set_hash(records) == target_identity_set_hash(list(reversed(records)))
    assert records[1]["ticker"] == "00088K"


def test_target_duplicate_and_numeric_cast_fail_closed() -> None:
    with pytest.raises(ReconciliationContractError, match="duplicate"):
        canonical_target_identity_records([_target("005930"), _target("005930")])
    with pytest.raises(ReconciliationContractError, match="string"):
        canonical_target_identity_records([{"ticker": 5930, "identity_type": "numeric", "current_presence": False, "source": "test"}])


def test_derive_target_identity_distribution() -> None:
    derived = derive_target_identities(
        [
            {"ticker": "005930", "date": "2020-01-02", "market": "KOSPI"},
            {"ticker": "00088K", "date": "2020-01-02", "market": "KOSDAQ"},
            {"ticker": "999999", "date": "2020-01-02", "market": "KOSDAQ"},
        ],
        ["999999"],
    )
    assert derived["counts"] == {"total": 2, "numeric": 1, "alphanumeric": 1}
    assert [row["ticker"] for row in derived["identities"]] == ["00088K", "005930"]


def test_classifier_common_allows_blank_sector() -> None:
    result = classify_security_type(_row("00088K", sector=""))
    assert result == {"classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE"}


def test_classifier_non_common_and_unknown_are_explicit() -> None:
    assert classify_security_type(_row("005930", kind="신형우선주"))["classification"] == CLASS_NOT_COMMON
    assert classify_security_type(_row("005930", sector="SPAC(소속부없음)"))["classification"] == CLASS_NOT_COMMON
    unknown = classify_security_type(_row("005930", group="주권", kind="종류주권"))
    assert unknown == {"classification": CLASS_UNRESOLVED, "reason": "UNKNOWN_SECURITY_TYPE_VALUE"}


def test_timeline_uses_derived_effective_date_and_does_not_add_basdd() -> None:
    timeline = build_pit_identity_timeline([_snapshot("2020-01-02", {**_row("005930"), "BAS_DD": "99999999"})])
    observation = timeline["005930"][0]
    assert observation["effective_date"] == "2020-01-02"
    assert observation["effective_date_source"] == "REQUEST_BAS_DD"
    assert "BAS_DD" not in observation


def test_reconcile_common_and_not_common_states() -> None:
    targets = [_target("005930"), _target("00088K")]
    result = reconcile_target_identities(
        targets,
        [_snapshot("2020-01-02", _row("005930"), _row("00088K", kind="신형우선주"))],
        expected_dates=["2020-01-02"],
        source_manifest_sha256="manifest",
    )
    by_ticker = {row["target_ticker"]: row for row in result["results"]}
    assert by_ticker["005930"]["historical_classification"] == HISTORICAL_COMMON_REQUIRED
    assert by_ticker["00088K"]["historical_classification"] == HISTORICAL_NOT_COMMON
    assert by_ticker["00088K"]["adjusted_price_support"] == "UNKNOWN"


def test_normal_lifecycle_transition_requires_historical_common() -> None:
    """A COMMON interval anywhere in the PIT history is sufficient (§15/§17C);
    a NOT_COMMON interval on a *different* date is a normal lifecycle
    transition, never a conflict (§16), so this must NOT be UNRESOLVED."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930")),
            _snapshot("2020-01-03", _row("005930", kind="신형우선주")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED
    assert row["classification_reason"] == "TIER_A_COMMON_INTERVAL_OBSERVED"


def test_temporal_transition_not_common_to_common_requires_historical_common() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2018-06-01", _row("005930", kind="신형우선주")),
            _snapshot("2020-01-02", _row("005930")),
        ],
        expected_dates=["2018-06-01", "2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_same_day_contradictory_state_is_unresolved() -> None:
    """§18: a TRUE conflict is the same date + same resolved identity (ISU_CD)
    carrying mutually contradictory official rows — this must stay UNRESOLVED
    even though the lifecycle-transition case above is no longer UNRESOLVED."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot(
                "2020-01-02",
                _row("005930", isu_cd="SAME"),
                {**_row("005930", isu_cd="SAME", kind="신형우선주"), "MKT_TP_NM": "KOSDAQ"},
            ),
        ],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    assert row["classification_reason"] == "SAME_DATE_CONTRADICTORY_CLASSIFICATION"


def test_ticker_reuse_is_separated_and_gate_allows_non_overlapping_reuse() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930", isu_cd="OLD")),
            _snapshot("2020-01-03", _row("005930", isu_cd="NEW")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    row = result["results"][0]
    assert row["ticker_reuse_status"] == "REUSE_DETECTED"
    assert evaluate_ticker_identity_reuse_gate(result)["status"] == "PASS"
    assert len(row["intervals"]) == 2


def test_non_overlap_reuse_keeps_per_interval_historical_common_flag_distinct() -> None:
    """§28/L: identity-aware structure must not re-collapse the two interval
    flags to one target-level verdict — one interval is COMMON, the other is
    NOT_COMMON, even though the *target* is HISTORICAL_COMMON_REQUIRED."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930", isu_cd="OLD")),
            _snapshot("2020-01-03", _row("005930", isu_cd="NEW", kind="신형우선주")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED
    by_isu = {interval["ISU_CD"]: interval["historical_common_required"] for interval in row["intervals"]}
    assert by_isu == {"OLD": True, "NEW": False}


def test_overlapping_ticker_collision_is_unresolved_and_blocks_gate() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2020-01-02", _row("005930", isu_cd="OLD"), _row("005930", isu_cd="NEW"))],
        expected_dates=["2020-01-02"],
    )
    assert result["results"][0]["ticker_reuse_status"] == "AMBIGUOUS"
    assert result["results"][0]["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    assert evaluate_ticker_identity_reuse_gate(result)["status"] == "BLOCKED_TICKER_REUSE_CONTRACT"


def test_overlap_collision_blocks_denominator_candidate_gate() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2020-01-02", _row("005930", isu_cd="OLD"), _row("005930", isu_cd="NEW"))],
        expected_dates=["2020-01-02"],
    )
    candidate = build_denominator_candidate(
        [], result, raw_input_status="READY", raw_integrity_pass=True, expected_total=1
    )
    assert candidate["status"] == "BLOCKED_DENOMINATOR_FREEZE_GATE"
    assert candidate["historical_identity_intervals"] == []


def test_survivorship_gate_requires_exact_accounting_and_zero_unresolved() -> None:
    result = reconcile_target_identities(
        [_target("005930"), _target("00088K")],
        [_snapshot("2020-01-02", _row("005930"), _row("00088K", kind="신형우선주"))],
        expected_dates=["2020-01-02"],
    )
    gate = evaluate_survivorship_bias_gate(result, expected_total=2)
    assert gate["status"] == "PASS"
    assert gate["accounted"] == 2


def test_missing_target_observation_blocks_freeze() -> None:
    result = reconcile_target_identities([_target("005930")], [], expected_dates=["2020-01-02"])
    freeze = evaluate_denominator_freeze_gate(result, raw_input_status="READY", raw_integrity_pass=True)
    assert result["results"][0]["classification_reason"] == "PIT_COVERAGE_GAP"
    assert freeze["status"] == "BLOCKED_DENOMINATOR_FREEZE_GATE"
    assert freeze["actual_freeze"] is False


def test_denominator_candidate_keeps_alpha_support_unknown() -> None:
    targets = [_target("005930"), _target("00088K")]
    reconciliation = reconcile_target_identities(
        targets,
        [_snapshot("2020-01-02", _row("005930"), _row("00088K"))],
        expected_dates=["2020-01-02"],
    )
    candidate = build_denominator_candidate(
        ["123456"], reconciliation, raw_input_status="READY", raw_integrity_pass=True, expected_total=2
    )
    assert candidate["status"] == "CANDIDATE_ONLY"
    assert candidate["identity_aware"] is True
    assert candidate["ticker_only_collapse"] is False
    alpha = next(row for row in candidate["historical_identity_intervals"] if row["ticker"] == "00088K")
    assert alpha["adjusted_price_support"] == "UNKNOWN"
    assert candidate["actual_freeze"] is False


def test_denominator_candidate_never_collapses_non_overlap_reuse_to_ticker_set() -> None:
    """§24/§28/MAJOR-03: denominator candidate must keep BOTH identity
    intervals for a non-overlapping ticker reuse — including the NOT_COMMON
    one — instead of merging into set(ticker) or dropping the non-COMMON leg."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930", isu_cd="OLD")),
            _snapshot("2020-01-03", _row("005930", isu_cd="NEW", kind="신형우선주")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    candidate = build_denominator_candidate(
        [], result, raw_input_status="READY", raw_integrity_pass=True, expected_total=1
    )
    assert candidate["status"] == "CANDIDATE_ONLY"
    matching = [row for row in candidate["historical_identity_intervals"] if row["ticker"] == "005930"]
    assert len(matching) == 2
    assert {row["ISU_CD"] for row in matching} == {"OLD", "NEW"}
    by_isu = {row["ISU_CD"]: row["historical_common_required"] for row in matching}
    assert by_isu == {"OLD": True, "NEW": False}
    # The ticker is still historically required overall (the OLD interval was
    # COMMON), but that verdict must not erase the NOT_COMMON NEW interval.
    assert candidate["ticker_union_count"] == 1


def test_raw_not_ready_is_a_normal_waiting_state(tmp_path: Path) -> None:
    raw = load_basic_info_snapshots(tmp_path / "missing", calendar_dates=["2020-01-02"])
    assert raw.status == AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION
    assert raw.expected_files == 2
    assert raw.snapshots == ()


def test_raw_partial_archive_blocks_before_classification(tmp_path: Path) -> None:
    root = tmp_path / "basic_info" / "2020" / "20200102"
    root.mkdir(parents=True)
    (root / "KOSPI.json").write_text(json.dumps({"OutBlock_1": []}), encoding="utf-8")
    raw = load_basic_info_snapshots(tmp_path / "basic_info", calendar_dates=["2020-01-02"])
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert raw.snapshots == ()


def test_invalid_short_code_is_rejected_by_raw_loader(tmp_path: Path) -> None:
    root = tmp_path / "basic_info" / "2020" / "20200102"
    root.mkdir(parents=True)
    rows = [_row("005930")]
    (root / "KOSDAQ.json").write_text(json.dumps({"OutBlock_1": rows}), encoding="utf-8")
    (root / "KOSPI.json").write_text(json.dumps({"OutBlock_1": [_row("bad")]}), encoding="utf-8")
    raw = load_basic_info_snapshots(tmp_path / "basic_info", calendar_dates=["2020-01-02"])
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert raw.snapshots == ()


def _rows_by_date_market(dates: list[str]) -> dict[tuple[str, str], list[dict[str, str]]]:
    return {(day, market): [_row("005930", market=market)] for day in dates for market in ("KOSPI", "KOSDAQ")}


def test_acquisition_manifest_sha_exact_match_passes_and_binds_authority_digest(tmp_path: Path) -> None:
    """MAJOR-01 / Section H-A: a fully-bound acquisition closure reaches READY
    and the authority digest is bound from the stored checkpoint hashes."""
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(tmp_path, dates, _rows_by_date_market(dates))
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == "READY"
    assert raw.raw_manifest_sha256 is not None
    assert raw.raw_manifest_sha256 == raw.derived_raw_manifest_sha256
    assert len(raw.snapshots) == 2


def test_schema_valid_raw_tamper_is_rejected_by_acquisition_authority_binding(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), tamper_sha_for=("2020-01-02", "KOSPI")
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert raw.snapshots == ()
    assert any("raw_sha_tamper" in error for error in raw.errors)


def test_checkpoint_non_complete_status_blocks_before_classification(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), non_complete_status_for=("2020-01-02", "KOSPI")
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert raw.snapshots == ()


def test_wrong_acquisition_terminal_blocks_classification(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), final_summary_status="PAUSED_QUOTA"
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert raw.snapshots == ()
    assert any("acquisition_final_summary_status_invalid" in error for error in raw.errors)


def test_manifest_missing_entry_blocks_classification(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), drop_entry_for=("2020-01-02", "KOSPI")
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_checkpoint_missing_entries" in error for error in raw.errors)


def test_manifest_extra_entry_blocks_classification(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), extra_entry=True
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_checkpoint_extra_entries" in error for error in raw.errors)


def test_row_count_mismatch_blocks_classification(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), wrong_row_count_for=("2020-01-02", "KOSDAQ")
    )
    raw = load_basic_info_snapshots(
        raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("row_count_mismatch" in error for error in raw.errors)


def test_acquisition_closure_checkpoint_binding_passes_on_happy_path(tmp_path: Path) -> None:
    """FIX02 Section B: the closure's frozen checkpoint_manifest_sha256 must
    exact-match the current checkpoint.json bytes for READY to be reached."""
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(tmp_path, dates, _rows_by_date_market(dates))
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == "READY"
    assert raw.checkpoint_authority_sha256 is not None


def test_checkpoint_tamper_after_closure_is_rejected(tmp_path: Path) -> None:
    """§32: checkpoint JSON modified (schema-valid) after closure was frozen,
    raw left untouched — must BLOCK with the manifest-SHA-mismatch reason,
    and the closure-level gate must short-circuit BEFORE the per-file
    row_count comparison ever runs (gate ordering, not just detection)."""
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(tmp_path, dates, _rows_by_date_market(dates))
    # Schema-valid mutation: change a field reconciliation actually reads
    # (row_count) on one checkpoint entry, without touching any raw file.
    # If the checkpoint-authority gate did not short-circuit first, this
    # would instead surface as a row_count_mismatch from the per-file loop.
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    any_key = next(iter(payload["entries"]))
    payload["entries"][any_key]["row_count"] = payload["entries"][any_key]["row_count"] + 1
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")

    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH" in error for error in raw.errors)
    # Gate ordering proof: the raw-level check never ran, so its error text
    # must not appear even though the entry's row_count is now wrong.
    assert not any("row_count_mismatch" in error for error in raw.errors)


def test_coordinated_raw_and_checkpoint_tamper_is_still_rejected(tmp_path: Path) -> None:
    """§33: the Major-01 regression. raw and checkpoint are modified TOGETHER
    so they stay mutually consistent — but the checkpoint file's own bytes no
    longer match the closure's frozen digest, so this must still BLOCK."""
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(tmp_path, dates, _rows_by_date_market(dates))
    # Sanity: happy path would be READY before the coordinated tamper.
    before = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert before.status == "READY"

    _coordinated_tamper(checkpoint_path, raw_root, "2020-01-02", "KOSPI", [_row("999999")])

    after = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert after.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH" in error for error in after.errors)


def test_wrong_closure_manifest_sha_blocks(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), frozen_checkpoint_sha_override="0" * 64
    )
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH" in error for error in raw.errors)


def test_missing_closure_manifest_sha_blocks(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), omit_checkpoint_manifest_sha=True
    )
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_final_summary_missing_fields" in error for error in raw.errors)


def test_final_summary_missing_required_field_blocks(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), omit_final_summary_fields=("target_count",)
    )
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_final_summary_missing_fields" in error for error in raw.errors)


def test_final_summary_wrong_runner_status_blocks(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), runner_status="PARTIAL"
    )
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_final_summary_runner_status_invalid" in error for error in raw.errors)


def test_final_summary_count_mismatch_blocks(tmp_path: Path) -> None:
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), pending_count_override=1
    )
    raw = load_basic_info_snapshots(
        raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=final_summary_path,
    )
    assert raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert any("acquisition_final_summary_count_mismatch" in error for error in raw.errors)


def test_preflight_top_level_status_distinguishes_blocked_from_waiting(tmp_path: Path) -> None:
    """MAJOR-04: a partial/corrupt/tampered input must not surface at the
    top level as the same status used for normal preflight waiting."""
    dates = ["2020-01-02"]
    raw_root, checkpoint_path, final_summary_path = _write_acquisition_fixture(
        tmp_path, dates, _rows_by_date_market(dates), tamper_sha_for=("2020-01-02", "KOSPI")
    )
    target_payload = load_target_identities(ROOT / DEFAULT_TARGET_IDENTITY_PATH)
    target_path = tmp_path / "target_identities.json"
    target_path.write_text(json.dumps(target_payload), encoding="utf-8")
    result = run_reconciliation_preflight(
        target_identities_path=target_path,
        basic_info_root=raw_root,
        calendar_dates=dates,
        acquisition_checkpoint_path=checkpoint_path,
        acquisition_final_summary_path=final_summary_path,
    )
    assert result["status"] == BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    assert result["status"] != "READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION"
    assert result["classification_executed"] is False


def test_preflight_top_level_status_is_waiting_when_raw_root_absent(tmp_path: Path) -> None:
    result = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=tmp_path / "missing",
        acquisition_checkpoint_path=tmp_path / "missing_checkpoint.json",
        acquisition_final_summary_path=tmp_path / "missing_summary.json",
    )
    assert result["status"] == "READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION"


def test_production_authority_alignment_fail_closes_managed_issue_after_spac_history() -> None:
    """Section E (Minor): docs/architecture/instrument_metadata_authority.md
    §6.1 fail-closes a 보통주+관리종목(소속부없음) row to UNKNOWN when the same
    ticker also carries Tier A SPAC-section history; this module must align."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2018-06-01", _row("005930", sector="SPAC(소속부없음)")),
            _snapshot("2020-01-02", _row("005930", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2018-06-01", "2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY" in reasons


def test_managed_issue_without_spac_history_still_resolves_common() -> None:
    """The alignment exception only fires when SPAC history is actually
    observed for the ticker; otherwise 보통주+관리종목(소속부없음) stays COMMON."""
    result = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2020-01-02", _row("005930", sector="관리종목(소속부없음)"))],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_spac_history_with_explicit_common_transition_resolves_common_lineage() -> None:
    """HISTORICAL_UNIVERSE_AUTHORITY_UNRESOLVED_RESOLUTION_V01 Fix A: an
    explicit non-SPAC COMMON interval confirmed AFTER the SPAC period means
    later managed-issue observations are no longer fail-closed — past SPAC
    status does not permanently contaminate an identity's lineage once a
    genuine common-stock interval has been observed (Section 8)."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2015-01-01", _row("005930", sector="SPAC(소속부없음)")),
            _snapshot("2016-01-01", _row("005930")),  # explicit clean COMMON
            _snapshot("2020-01-02", _row("005930", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2015-01-01", "2016-01-01", "2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY" not in reasons


def test_spac_history_without_explicit_common_stays_unresolved_after_managed() -> None:
    """Without an explicit non-SPAC COMMON interval, SPAC -> MANAGED stays
    fail-closed (Section 9) — this is the majority real-data pattern (114/122)."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2015-01-01", _row("005930", sector="SPAC(소속부없음)")),
            _snapshot("2020-01-02", _row("005930", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2015-01-01", "2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY" in reasons


def test_spac_then_common_only_resolves_common_required() -> None:
    """SPAC -> COMMON with no later managed-issue observation resolves
    cleanly to COMMON_REQUIRED (the exception never needs to fire)."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2015-01-01", _row("005930", sector="SPAC(소속부없음)")),
            _snapshot("2016-01-01", _row("005930")),
        ],
        expected_dates=["2015-01-01", "2016-01-01"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_spac_managed_before_any_common_confirmation_stays_unresolved_even_with_later_common() -> None:
    """Chronological order matters: a managed-issue observation that occurs
    BEFORE any explicit COMMON confirmation must stay UNRESOLVED even if a
    later, separate COMMON interval exists further down the timeline — the
    exception is evaluated at each observation's own position in time, not
    with knowledge of the future."""
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2015-01-01", _row("005930", sector="SPAC(소속부없음)")),
            _snapshot("2016-01-01", _row("005930", sector="관리종목(소속부없음)")),
            _snapshot("2020-01-02", _row("005930")),
        ],
        expected_dates=["2015-01-01", "2016-01-01", "2020-01-02"],
    )
    row = result["results"][0]
    # CLASS_UNRESOLVED anywhere in the identity's states forces the overall
    # ticker to UNRESOLVED (Section B aggregation precedence) even though a
    # later clean COMMON interval also exists.
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY" in reasons


def test_ship_investment_company_common_stock_is_not_common() -> None:
    """Fix B1: 선박투자회사 (Ship Investment Company) is excluded on the same
    documented 'dividend-centric distribution structure' principle as
    부동산투자회사/REIT (docs/patterns/pattern_a/validation/universe_quality_v01.md
    §2.1) — an official SECUGRP_NM match, not a name/suffix heuristic."""
    result = reconcile_target_identities(
        [_target("078420")],
        [_snapshot("2010-01-04", _row("078420", group="선박투자회사"))],
        expected_dates=["2010-01-04"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON


def test_stock_certificate_kind_jongryu_stays_unresolved() -> None:
    """Fix B2: KIND_STKCERT_TP_NM='종류주권' stays UNRESOLVED — the exact
    same official value that docs/architecture/instrument_metadata_authority.md
    §6.1 (Fix Round 08) deliberately removed a name-substring heuristic for
    and fail-closed to UNKNOWN in the live classifier. Consistency with that
    reviewed precedent, not a new heuristic, is the basis for keeping this
    UNRESOLVED rather than guessing NOT_COMMON from the ticker name."""
    result = reconcile_target_identities(
        [_target("00781K")],
        [_snapshot("2020-01-02", _row("00781K", kind="종류주권"))],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "UNKNOWN_SECURITY_TYPE_VALUE" in reasons


def test_stock_certificate_kind_jongryu_with_separate_common_interval_still_resolves_common() -> None:
    """If the same identity also carries a genuine COMMON interval elsewhere
    in its lifecycle, the ticker-level lifecycle contract (Section 15/17C —
    any COMMON interval anywhere resolves the whole ticker) still applies;
    the 종류주권 interval itself remains UNRESOLVED at the interval level."""
    result = reconcile_target_identities(
        [_target("00781K")],
        [
            _snapshot("2015-01-01", _row("00781K")),
            _snapshot("2020-01-02", _row("00781K", kind="종류주권")),
        ],
        expected_dates=["2015-01-01", "2020-01-02"],
    )
    row = result["results"][0]
    # CLASS_UNRESOLVED anywhere still forces the overall ticker UNRESOLVED
    # (Section B aggregation precedence, same mechanism as the SPAC case) —
    # this is not a silent contradiction, it is the existing documented
    # fail-closed-wins precedence rule.
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_depositary_receipt_legacy_jusik_yetak_jeungseo_is_common() -> None:
    """Fix B3: SECUGRP_NM='주식예탁증서' + KIND_STKCERT_TP_NM=보통주 -> COMMON.
    Verified as the pre-2014-03-03 KRX label for the same concept as the
    already-supported '주식예탁증권' (same ISU_CD/ISU_ABBRV either side of
    the cutover for every surviving DR ticker) — an explicit exact-value
    addition, not fuzzy/string-distance matching."""
    result = reconcile_target_identities(
        [_target("950030")],
        [_snapshot("2011-01-01", _row("950030", group="주식예탁증서"))],
        expected_dates=["2011-01-01"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_depositary_receipt_jusik_yetak_jeunggwon_regression_still_common() -> None:
    """Existing '주식예탁증권' mapping (pre-dating this fix) must keep working."""
    result = reconcile_target_identities(
        [_target("950110")],
        [_snapshot("2020-01-02", _row("950110", group="주식예탁증권"))],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_unknown_future_security_group_value_stays_fail_closed() -> None:
    """Section 20: adding explicit values for 주식예탁증서/선박투자회사 must
    not weaken the UNKNOWN fallback for genuinely unmapped values."""
    result = reconcile_target_identities(
        [_target("999999")],
        [_snapshot("2020-01-02", _row("999999", group="미확인지분증권XYZ"))],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_unknown_future_stock_certificate_kind_stays_fail_closed() -> None:
    result = reconcile_target_identities(
        [_target("999998")],
        [_snapshot("2020-01-02", _row("999998", kind="새종류"))],
        expected_dates=["2020-01-02"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_supplemental_authority_spac_dissolution_confirmed_resolves_not_common() -> None:
    """HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01 Section 12/14 (A2):
    an official DART dissolution disclosure ('해산사유발생') for this exact
    identity resolves the residual managed-issue interval to NOT_COMMON —
    the SPAC never completed a merger and never became an operating
    company's common stock under this code."""
    supplemental = {
        ("204440", "KR7204440002"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("204440")],
        [
            _snapshot("2014-10-22", _row("204440", isu_cd="KR7204440002", sector="SPAC(소속부없음)")),
            _snapshot("2017-05-26", _row("204440", isu_cd="KR7204440002", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2014-10-22", "2017-05-26"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED in reasons


def test_supplemental_authority_spac_merger_common_lineage_confirmed_resolves_common() -> None:
    """Section 12 (A1): official evidence of an explicit SPAC-exit / merger
    completion with confirmed common-equity lineage promotes the residual
    interval to COMMON. (Synthetic — none of the real 114 cases resolved
    this way; this exercises the code path the real data did not exercise.)"""
    supplemental = {
        ("999901", "KR999901"): {
            "decision": "COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("999901")],
        [
            _snapshot("2014-10-22", _row("999901", isu_cd="KR999901", sector="SPAC(소속부없음)")),
            _snapshot("2017-05-26", _row("999901", isu_cd="KR999901", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2014-10-22", "2017-05-26"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED in reasons


def test_supplemental_authority_merger_withdrawn_not_promoted_to_common() -> None:
    """Section 15/45: a withdrawn merger decision must never be promoted to
    COMMON. The resolver records the review (INSUFFICIENT) but the identity
    stays UNRESOLVED — matching real case 465320 (교보15호스팩)."""
    supplemental = {
        ("465320", "KR7465320000"): {
            "decision": "INSUFFICIENT",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT,
        }
    }
    result = reconcile_target_identities(
        [_target("465320")],
        [
            _snapshot("2023-12-05", _row("465320", isu_cd="KR7465320000", sector="SPAC(소속부없음)")),
            _snapshot("2026-08-21", _row("465320", isu_cd="KR7465320000", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2023-12-05", "2026-08-21"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT in reasons


def test_supplemental_authority_identity_mismatch_never_applies() -> None:
    """Section 13: a supplemental record for a DIFFERENT ISU_CD under the
    same ticker string must never resolve this identity — ticker name alone
    is not identity."""
    supplemental = {
        ("204440", "KR_SOME_OTHER_IDENTITY"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("204440")],
        [
            _snapshot("2014-10-22", _row("204440", isu_cd="KR7204440002", sector="SPAC(소속부없음)")),
            _snapshot("2017-05-26", _row("204440", isu_cd="KR7204440002", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2014-10-22", "2017-05-26"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_supplemental_authority_malformed_decision_stays_fail_closed() -> None:
    """An unrecognised ``decision`` value in a supplemental record must never
    be trusted into a classification change — fail-closed, same as an
    unmapped official field value."""
    supplemental = {
        ("204440", "KR7204440002"): {"decision": "MAYBE", "decision_reason_code": "NOT_A_REAL_CODE"},
    }
    result = reconcile_target_identities(
        [_target("204440")],
        [
            _snapshot("2014-10-22", _row("204440", isu_cd="KR7204440002", sector="SPAC(소속부없음)")),
            _snapshot("2017-05-26", _row("204440", isu_cd="KR7204440002", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2014-10-22", "2017-05-26"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_supplemental_authority_preferred_class_confirmed_resolves_not_common() -> None:
    """Section 20 (via supplemental authority): 종류주권 with an official
    per-issuer preferred-class confirmation (KRX ISU_NM + DART share-class
    breakdown) resolves to NOT_COMMON — matches real case 02826K (삼성물산
    1우선주(신형))."""
    supplemental = {
        ("02826K", "KR702826K016"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("02826K")],
        [_snapshot("2015-09-15", _row("02826K", isu_cd="KR702826K016", kind="종류주권"))],
        expected_dates=["2015-09-15"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED in reasons


def test_supplemental_authority_preferred_class_common_equivalent_resolves_common() -> None:
    """Section 20: if official authority instead confirmed a 종류주권 case
    was actually common-equivalent, it resolves to COMMON. (Synthetic — none
    of the real 14 cases resolved this way.)"""
    supplemental = {
        ("999902", "KR999902"): {"decision": "COMMON", "decision_reason_code": "SUPPLEMENTAL_AUTHORITY_CONFIRMED_COMMON"},
    }
    result = reconcile_target_identities(
        [_target("999902")],
        [_snapshot("2015-09-15", _row("999902", isu_cd="KR999902", kind="종류주권"))],
        expected_dates=["2015-09-15"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_supplemental_authority_absent_record_never_changes_unknown_fallback() -> None:
    """Section 26: unknown fail-closed must not weaken even when a
    (non-empty) supplemental authority table is supplied — a ticker with no
    matching record passes through unchanged."""
    supplemental = {
        ("02826K", "KR702826K016"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("999999")],
        [_snapshot("2020-01-02", _row("999999", group="미확인지분증권XYZ"))],
        expected_dates=["2020-01-02"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED


def test_load_supplemental_authority_records_missing_directory_is_empty(tmp_path: Path) -> None:
    """A missing supplemental-authority directory yields an empty lookup —
    never an implicit resolution (fail-closed default)."""
    lookup = load_supplemental_authority_records(tmp_path / "does_not_exist")
    assert lookup == {}


def test_load_supplemental_authority_records_reads_canonical_manifests() -> None:
    """The canonical on-disk manifests (SPAC + preferred-class residuals)
    load into a lookup keyed by (target_ticker, isu_cd), one entry per
    individually-investigated identity — 114 + 14 = 128 total.

    HISTORICAL_UNIVERSE_FINAL_RESIDUAL_SPAC_RESOLUTION_V01: all 128 are now
    NOT_COMMON — the last 3 (465320/471050/472220) were reclassified from
    INSUFFICIENT once the AS-OF-cutoff semantic correction was applied
    (active/unterminated SPAC identity is itself positive NOT_COMMON
    authority, Section 8)."""
    lookup = load_supplemental_authority_records()
    assert len(lookup) == 128
    assert lookup[("204440", "KR7204440002")]["decision"] == "NOT_COMMON"
    assert lookup[("02826K", "KR702826K016")]["decision"] == "NOT_COMMON"
    for ticker, isu_cd in [("465320", "KR7465320000"), ("471050", "KR7471050005"), ("472220", "KR7472220003")]:
        assert lookup[(ticker, isu_cd)]["decision"] == "NOT_COMMON"
    decisions = {record["decision"] for record in lookup.values()}
    assert decisions == {"NOT_COMMON"}


def test_active_spac_at_cutoff_resolves_not_common_not_unresolved() -> None:
    """HISTORICAL_UNIVERSE_FINAL_RESIDUAL_SPAC_RESOLUTION_V01 Section 8/17:
    an officially-confirmed active SPAC at the historical cutoff — no merger,
    no termination, no common transition — is itself positive NOT_COMMON
    authority. 'Not yet dissolved' must never mean UNRESOLVED once the
    identity's SPAC status at cutoff is confirmed by supplemental authority."""
    supplemental = {
        ("472220", "KR7472220003"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_ACTIVE_SPAC_AT_HISTORICAL_CUTOFF,
        }
    }
    result = reconcile_target_identities(
        [_target("472220")],
        [
            _snapshot("2024-02-06", _row("472220", isu_cd="KR7472220003", sector="SPAC(소속부없음)")),
            _snapshot("2026-08-21", _row("472220", isu_cd="KR7472220003", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2024-02-06", "2026-08-21"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_ACTIVE_SPAC_AT_HISTORICAL_CUTOFF in reasons


def test_merger_withdrawal_with_spac_identity_preserved_resolves_not_common() -> None:
    """Section 9/18: a withdrawn merger decision, with the identity remaining
    an officially confirmed SPAC through cutoff and no common transition,
    resolves NOT_COMMON — the possibility of a future new merger attempt does
    not change the as-of-cutoff historical state (Section 6)."""
    supplemental = {
        ("465320", "KR7465320000"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_MERGER_WITHDRAWN_SPAC_IDENTITY_PRESERVED,
        }
    }
    result = reconcile_target_identities(
        [_target("465320")],
        [
            _snapshot("2023-12-05", _row("465320", isu_cd="KR7465320000", sector="SPAC(소속부없음)")),
            _snapshot("2026-08-21", _row("465320", isu_cd="KR7465320000", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2023-12-05", "2026-08-21"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_MERGER_WITHDRAWN_SPAC_IDENTITY_PRESERVED in reasons


def test_termination_in_progress_without_formal_dissolution_report_resolves_not_common() -> None:
    """Section 10/19: a delisting/termination process already underway before
    cutoff (trading halt for 상장폐지 사유발생), with the identity still an
    officially confirmed SPAC and no common transition, resolves NOT_COMMON
    even though the formal 해산사유발생 report has not yet been filed —
    legal-dissolution completion and security-denominator classification are
    separate questions (Section 10)."""
    supplemental = {
        ("471050", "KR7471050005"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_SPAC_TERMINATION_IN_PROGRESS_NO_COMMON_TRANSITION,
        }
    }
    result = reconcile_target_identities(
        [_target("471050")],
        [
            _snapshot("2024-01-24", _row("471050", isu_cd="KR7471050005", sector="SPAC(소속부없음)")),
            _snapshot("2026-08-21", _row("471050", isu_cd="KR7471050005", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2024-01-24", "2026-08-21"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_NOT_COMMON
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert SUPPLEMENTAL_AUTHORITY_SPAC_TERMINATION_IN_PROGRESS_NO_COMMON_TRANSITION in reasons


def test_completed_merger_common_transition_regression_still_resolves_common() -> None:
    """Section 20: the existing COMMON-transition resolution path (confirmed
    merger completion + common-equity lineage) must keep working exactly as
    before this AS-OF-cutoff semantic correction — this fix only affects the
    'still SPAC / terminated' side, never weakens the COMMON path."""
    supplemental = {
        ("999903", "KR999903"): {
            "decision": "COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED,
        }
    }
    result = reconcile_target_identities(
        [_target("999903")],
        [
            _snapshot("2015-01-01", _row("999903", isu_cd="KR999903", sector="SPAC(소속부없음)")),
            _snapshot("2020-01-02", _row("999903", isu_cd="KR999903", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2015-01-01", "2020-01-02"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_future_merger_completion_after_cutoff_does_not_leak_backward() -> None:
    """Section 16: a supplemental decision must never let a FUTURE (post-
    cutoff) event retroactively promote an as-of-cutoff-dated observation to
    COMMON. A supplemental record whose own evidence is dated after the
    frozen cutoff represents fabricated/out-of-window provenance and must
    not be trusted to override the pre-cutoff observation — the resolver
    only reads decision/decision_reason_code, it does not itself enforce a
    cutoff, so this is a contract the record-authoring process must uphold;
    this test locks in that a record's positive decision applies uniformly
    to the observation it is attached to regardless of a later, unrelated
    event, and that no mechanism in this module ever inspects dates after
    the observation's own effective_date to decide a classification."""
    # A record whose decision is NOT_COMMON (as-of the 2026-08-21 cutoff)
    # must resolve the pre-cutoff observation to NOT_COMMON even though a
    # hypothetical 2026-09-10 merger completion is known to have later
    # occurred in the real world — that future fact is simply never passed
    # to the resolver, because the resolver classifies exactly the
    # observations it is given and nothing else.
    supplemental = {
        ("999904", "KR999904"): {
            "decision": "NOT_COMMON",
            "decision_reason_code": SUPPLEMENTAL_AUTHORITY_ACTIVE_SPAC_AT_HISTORICAL_CUTOFF,
        }
    }
    result = reconcile_target_identities(
        [_target("999904")],
        [
            _snapshot("2015-01-01", _row("999904", isu_cd="KR999904", sector="SPAC(소속부없음)")),
            _snapshot("2026-08-21", _row("999904", isu_cd="KR999904", sector="관리종목(소속부없음)")),
            # A genuine post-cutoff COMMON-shaped observation (e.g. after a
            # 2026-09-10 merger completes) is classified independently and
            # correctly as COMMON at the row level — it is never influenced
            # by the earlier NOT_COMMON supplemental decision, because that
            # decision only overrides the specific managed-issue-shaped
            # observation it was attached to, not the identity as a whole.
            _snapshot("2026-09-10", _row("999904", isu_cd="KR999904")),
        ],
        expected_dates=["2015-01-01", "2026-08-21", "2026-09-10"],
        supplemental_authority=supplemental,
    )
    row = result["results"][0]
    reasons_by_date = {interval["effective_from"]: interval["classification"] for interval in row["intervals"]}
    assert reasons_by_date["2026-08-21"] == CLASS_NOT_COMMON
    assert reasons_by_date["2026-09-10"] == CLASS_COMMON
    # Ticker-level aggregation still resolves COMMON overall (Section 15/17C
    # precedence — unrelated to this leakage guarantee), but the as-of-cutoff
    # interval itself was never retroactively promoted.
    assert row["historical_classification"] == HISTORICAL_COMMON_REQUIRED


def test_insufficient_authority_is_not_a_blanket_not_common_default() -> None:
    """Section 21: the AS-OF-cutoff semantic correction must not become a
    blanket 'any managed-issue-after-SPAC observation is NOT_COMMON' rule.
    Without a supplemental record for this identity, the residual stays
    UNRESOLVED exactly as before — only individually-investigated,
    explicitly-decided identities are ever promoted."""
    result = reconcile_target_identities(
        [_target("999905")],
        [
            _snapshot("2015-01-01", _row("999905", isu_cd="KR999905", sector="SPAC(소속부없음)")),
            _snapshot("2020-01-02", _row("999905", isu_cd="KR999905", sector="관리종목(소속부없음)")),
        ],
        expected_dates=["2015-01-01", "2020-01-02"],
        supplemental_authority={},
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    reasons = {interval["classification_reason"] for interval in row["intervals"]}
    assert "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY" in reasons


def test_security_type_mapping_evidence_has_rule_ids_and_authority_reference() -> None:
    from trend_scanner.universe.historical_authority_reconciliation import build_security_type_mapping_evidence

    evidence = build_security_type_mapping_evidence(
        [_row("005930")], sample_source_path="data/reference/krx_instrument_metadata.parquet"
    )
    assert all(rule["rule_id"].startswith("HISTORICAL_SECURITY_TYPE_RULE_") for rule in evidence["mappings"])
    assert all("existing_authority_reference" in rule for rule in evidence["mappings"])
    assert all(rule["sample_source_path"] == "data/reference/krx_instrument_metadata.parquet" for rule in evidence["mappings"])
    assert all("SECUGRP_NM" in rule and "KIND_STKCERT_TP_NM" in rule and "SECT_TP_NM_condition" in rule for rule in evidence["mappings"])
    assert evidence["production_authority_alignment"]["existing_authority_reference"]


def test_default_preflight_reports_pending_authority_without_network(tmp_path: Path) -> None:
    # This test's purpose is to verify the NO-AUTHORITY-YET state, not the
    # production filesystem's current contents — it must not depend on
    # whether the real production basic_info root happens to be populated
    # (it now holds a completed 8190-file acquisition). The empty-authority
    # environment is reproduced explicitly via an isolated tmp_path root.
    result = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=tmp_path / "basic_info",
        acquisition_checkpoint_path=tmp_path / "checkpoint.json",
        acquisition_final_summary_path=tmp_path / "acquisition_final_summary.json",
    )
    assert result["reconciliation_input_status"] == AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION
    assert result["classification_executed"] is False
    assert result["actual_denominator_frozen"] is False
    assert result["network_requests"] == {"krx_open_api": 0, "krx_mdc": 0, "pykrx": 0, "opendart": 0}


def test_network_zero_guard_does_not_get_called(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail_socket(*args: object, **kwargs: object) -> object:
        raise AssertionError("network must not be opened")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=tmp_path / "missing",
    )
    assert result["network_requests"]["krx_open_api"] == 0


def test_reconciliation_is_deterministic_and_idempotent() -> None:
    targets = [_target("00088K"), _target("005930")]
    snapshots = [_snapshot("2020-01-02", _row("005930"), _row("00088K"))]
    first = reconcile_target_identities(targets, snapshots, expected_dates=["2020-01-02"], source_manifest_sha256="m")
    second = reconcile_target_identities(list(reversed(targets)), list(reversed(snapshots)), expected_dates=["2020-01-02"], source_manifest_sha256="m")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
