"""Offline contract tests for historical universe authority reconciliation."""

from __future__ import annotations

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
    load_target_identities,
    reconcile_target_identities,
    run_reconciliation_preflight,
    target_identity_set_hash,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_conflicting_official_classification_is_unresolved() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930")),
            _snapshot("2020-01-03", _row("005930", kind="신형우선주")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    row = result["results"][0]
    assert row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    assert row["classification_reason"] == "CONFLICTING_OFFICIAL_CLASSIFICATION"


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


def test_overlapping_ticker_collision_is_unresolved_and_blocks_gate() -> None:
    result = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2020-01-02", _row("005930", isu_cd="OLD"), _row("005930", isu_cd="NEW"))],
        expected_dates=["2020-01-02"],
    )
    assert result["results"][0]["ticker_reuse_status"] == "AMBIGUOUS"
    assert result["results"][0]["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED
    assert evaluate_ticker_identity_reuse_gate(result)["status"] == "BLOCKED_TICKER_REUSE_CONTRACT"


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
    alpha = next(row for row in candidate["entries"] if row["ticker"] == "00088K")
    assert alpha["adjusted_price_support"] == "UNKNOWN"
    assert candidate["actual_freeze"] is False


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


def test_default_preflight_reports_pending_authority_without_network() -> None:
    result = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info",
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
