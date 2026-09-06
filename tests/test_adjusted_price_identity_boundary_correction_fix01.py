"""test_adjusted_price_identity_boundary_correction_fix01.py

Offline acceptance tests for the identity-boundary correction.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.repository_v2 import (
    KNOWN_ADJUSTED_SOURCE_GAP_DATES,
    KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES,
    _project_analytic_sessions,
)


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix01"
SOURCE_XML = ROOT / (
    "artifacts/data/end_to_end_data_parity/v01/adjusted_source_gap_authority_review/v01/"
    "live_verification/ticker_446840_naver_verification_response.xml"
)


def test_ticker_continuity_is_not_identity_continuity() -> None:
    authority = json.loads((FIX / "446840/corporate_identity_authority.json").read_text())
    assert authority["ticker_code_continuity"] is True
    assert authority["economic_identity_continuity"] is False
    assert authority["effective_transition_date"] == "2025-08-14"
    assert authority["pre_boundary_identity"].startswith("Kiwoom No.8 SPAC")
    assert authority["post_boundary_identity"].startswith("Gitsn")


def test_source_presence_is_preserved_but_not_analytic_eligibility() -> None:
    semantics = json.loads((FIX / "446840/source_vs_identity_semantics.json").read_text())
    assert semantics["source_response"]["returned_rows"] == 10
    assert semantics["source_response"]["pre_boundary_rows"] == 9
    assert semantics["semantic_contract"] == {
        "SOURCE_ROW_EXISTS": True,
        "IDENTITY_ROW_ELIGIBLE": False,
        "ANALYTIC_ROW_ELIGIBLE": False,
        "reason": "Rows before 2025-08-14 are source-present but belong to the pre-boundary SPAC identity.",
    }


def test_identity_authority_excludes_exact_pre_boundary_pairs_without_gap_fallback() -> None:
    dates = [
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06",
        "2025-08-07", "2025-08-08", "2025-08-11", "2025-08-12",
        "2025-08-13", "2025-08-14",
    ]
    adjusted = pd.DataFrame(
        {"open": [40.0], "high": [42.0], "low": [39.0], "close": [41.0]},
        index=pd.DatetimeIndex([dates[-1]]),
    )
    raw = pd.DataFrame(
        {
            "ticker": ["446840"] * len(dates),
            "open": [40] * len(dates), "high": [42] * len(dates),
            "low": [39] * len(dates), "close": [41] * len(dates),
            "volume": [10] * len(dates), "trading_value": [10] * len(dates),
            "market_cap": [100] * len(dates), "listed_shares": [100] * len(dates),
        },
        index=pd.DatetimeIndex(dates),
    )
    raw.attrs["ticker"] = "446840"
    _, projected_raw, evidence = _project_analytic_sessions(adjusted, raw)
    assert KNOWN_ADJUSTED_SOURCE_GAP_DATES == {}
    assert evidence["outside_identity_lifecycle_dates"] == dates[:-1]
    assert list(projected_raw.index) == [pd.Timestamp("2025-08-14")]


def test_true_same_identity_repair_path_remains_storage_compatible(tmp_path: Path) -> None:
    """An explicit same-identity repair can still write a bounded leading interval."""

    store = AdjustedPriceStore(tmp_path)
    frame = pd.DataFrame(
        {"open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5], "close": [10.2, 11.2]},
        index=pd.DatetimeIndex(["2025-01-02", "2025-01-03"]),
    )
    frame.attrs["source_native_adjusted"] = True
    store.save_full("999999", frame, metadata_context={"requested_start": "2025-01-02", "requested_end": "2025-01-03"})
    restored = store.load_daily("999999")
    assert restored.index.min() == pd.Timestamp("2025-01-02")
    assert len(restored) == 2
    assert ("999999", "2025-01-02") not in KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES


def test_candidate_audit_closes_the_exact_46_without_silent_drop() -> None:
    summary = json.loads((FIX / "blast_radius/identity_candidate_summary.json").read_text())
    assert summary["candidate_input_count"] == summary["candidate_output_count"] == 46
    assert summary["silent_drop_count"] == 0
    assert summary["unresolved_count"] == 0
    assert summary["classification_counts"] == {
        "IDENTITY_BOUNDARY_EXPECTED": 24,
        "TRUE_ACQUISITION_TRUNCATION": 0,
        "LEGITIMATE_SOURCE_GAP": 0,
        "NO_ACTION_REQUIRED": 22,
        "UNRESOLVED": 0,
    }
    with (FIX / "blast_radius/identity_candidate_audit.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 46
    assert {row["ticker"] for row in rows}.__len__() == 46
    assert all(row["raw_pre_boundary_present"] == "True" for row in rows)


def test_previously_captured_naver_response_is_offline_and_no_fallback() -> None:
    response = SOURCE_XML.read_text(encoding="EUC-KR")

    class _Response:
        status_code = 200

        def __init__(self, text: str):
            self.text = text

    class _Session:
        def get(self, *args, **kwargs):
            return _Response(response)

    provider = NaverDirectAdjustedPriceDataProvider(session=_Session())
    frame = provider.load_daily("446840", "2025-08-01", "2025-08-14")
    assert len(frame) == 10
    assert provider.pykrx_fallback_call_count == 0
