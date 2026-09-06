"""PATTERN_A_PARITY_V01 러너의 오프라인 비교/가드 단위 검증."""

from __future__ import annotations

import socket

import pandas as pd
import pytest

from scripts.run_pattern_a_parity_v01 import (
    CORE_COLUMNS,
    NetworkAudit,
    NetworkRequestBlocked,
    _candidate_core_from_snapshot,
    compare_frames,
    network_guard,
)


def _row(**overrides: object) -> dict[str, object]:
    row = {column: None for column in CORE_COLUMNS}
    row.update(
        {
            "ticker": "000001",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "raw_data_ready": True,
            "feature_ready": True,
            "score_ready": True,
            "stage_ready": True,
            "evaluator_ready": True,
            "candidate_state": "candidate",
            "evaluator_reason_codes": "",
            "momentum_reason_codes_1m": "",
            "momentum_reason_codes_3m": "",
            "momentum_reason_codes_6m": "",
        }
    )
    row.update(overrides)
    return row


def test_compare_frames_respects_numeric_tolerance_and_structural_drift():
    left = pd.DataFrame([_row(pattern_a_score=10.0)])
    right = pd.DataFrame([_row(pattern_a_score=10.0 + 1e-13)])
    result = compare_frames(left, right)
    assert result["numeric_mismatch_count"] == 0

    right.loc[0, "official_stage"] = "transition"
    result = compare_frames(left, right)
    assert result["structural_mismatch_count"] == 1


def test_missing_snapshot_is_explicit_and_schema_complete():
    result = _candidate_core_from_snapshot("1", "예시", "KOSPI", None)
    assert result["ticker"] == "000001"
    assert result["candidate_state"] == "insufficient_data"
    assert result["evaluator_reason_codes"] == "CACHE_MISSING"
    assert set(result) == set(CORE_COLUMNS)


def test_network_guard_fails_closed_and_restores_socket():
    audit = NetworkAudit()
    original = socket.socket.connect
    with pytest.raises(NetworkRequestBlocked):
        with network_guard(audit):
            socket.socket().connect(("127.0.0.1", 1))
    assert audit.request_count == 1
    assert socket.socket.connect is original
