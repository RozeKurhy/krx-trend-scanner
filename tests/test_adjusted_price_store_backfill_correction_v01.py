"""test_adjusted_price_store_backfill_correction_v01.py

Regression guards for the identity-safe adjusted-price correction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.repository_v2 import (
    KNOWN_ADJUSTED_SOURCE_GAP_DATES,
    KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES,
)


ROOT = Path(__file__).resolve().parents[1]
CORRECTION = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix01"


def test_identity_safe_request_boundary_excludes_pre_identity_rows():
    metadata = json.loads((ROOT / "data/market/adjusted/stocks/446840.meta.json").read_text())
    frame = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks").load_daily("446840")

    assert metadata["requested_start"] == "2025-08-14"
    assert metadata["actual_date_min"] == "2025-08-14"
    assert frame.index.min() == pd.Timestamp("2025-08-14")
    assert frame.index.max() == pd.Timestamp("2026-08-21")
    assert len(frame) == 248


def test_pre_identity_rows_use_identity_authority_not_source_gap_authority():
    assert KNOWN_ADJUSTED_SOURCE_GAP_DATES == {}
    expected = {
        ("446840", date): "KRX/PIT identity authority: pre-boundary Kiwoom No.8 SPAC row"
        for date in {
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06",
        "2025-08-07", "2025-08-08", "2025-08-11", "2025-08-12",
        "2025-08-13",
        }
    }
    assert {key: KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES[key] for key in expected} == expected
    manifest = json.loads((CORRECTION / "correction/canonical_mutation_manifest.json").read_text())
    assert manifest["removed_dates"] == sorted(date for _, date in expected)
    assert manifest["source_truth_artifact"].endswith("ticker_446840_naver_verification_response.xml")


def test_identity_correction_preserves_existing_overlap_values():
    reconciliation = json.loads((CORRECTION / "correction/overlap_reconciliation.json").read_text())
    assert reconciliation["ticker_446840"]["changed_existing_overlap_values"] == 0
    assert reconciliation["ticker_446840"]["source_values_equal_for_retained_rows"] is True
    assert reconciliation["ticker_446840"]["deleted_valid_same_identity_rows"] == 0

    after = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks").load_daily("446840")
    assert after.loc[pd.Timestamp("2025-08-14"), "close"] == 8282.0


def test_corrected_provider_contract_remains_naver_only_without_fallback():
    response = (ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_source_gap_authority_review/v01/live_verification/ticker_446840_naver_verification_response.xml").read_text(encoding="EUC-KR")

    class _Response:
        status_code = 200

        def __init__(self, text: str):
            self.text = text

    class _Session:
        def get(self, *args, **kwargs):
            return _Response(response)

    provider = NaverDirectAdjustedPriceDataProvider(session=_Session())
    frame = provider.load_daily("446840", "2025-08-01", "2025-08-14")

    assert provider.source_descriptor == CURRENT_SOURCE_DESCRIPTOR
    assert provider.pykrx_fallback_call_count == 0
    assert len(frame) == 10


def test_population_audit_reconciles_every_effective_identity():
    summary = json.loads((CORRECTION / "blast_radius/identity_candidate_summary.json").read_text())

    assert summary["population_total"] == 3149
    assert summary["candidate_input_count"] == 46
    assert summary["candidate_output_count"] == 46
    assert summary["silent_drop_count"] == 0
    assert summary["sum"] == 46
    assert summary["unresolved_count"] == 0
    assert summary["missing_raw_cache_identities"] == 660
    assert summary["missing_raw_overlap_with_46"] == 0
