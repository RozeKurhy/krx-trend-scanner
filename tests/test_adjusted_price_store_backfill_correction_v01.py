"""test_adjusted_price_store_backfill_correction_v01.py

Regression guards for the bounded adjusted-price backfill correction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.repository_v2 import KNOWN_ADJUSTED_SOURCE_GAP_DATES


ROOT = Path(__file__).resolve().parents[1]
CORRECTION = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_backfill_correction/v01"


def test_correction_request_boundary_covers_proven_leading_rows():
    metadata = json.loads((ROOT / "data/market/adjusted/stocks/446840.meta.json").read_text())
    frame = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks").load_daily("446840")

    assert metadata["requested_start"] == "2025-08-01"
    assert metadata["actual_date_min"] == "2025-08-01"
    assert frame.index.min() == pd.Timestamp("2025-08-01")
    assert frame.index.max() == pd.Timestamp("2026-08-21")
    assert len(frame) == 257


def test_false_source_gap_authority_is_not_admitted_after_correction():
    assert KNOWN_ADJUSTED_SOURCE_GAP_DATES == {}
    corrected = json.loads((CORRECTION / "correction/corrected_rows.json").read_text())
    assert corrected["source_authority_id"] == CURRENT_SOURCE_DESCRIPTOR.source_authority_id
    assert corrected["row_count"] == 9
    assert {row["date"] for row in corrected["rows"]} == {
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06",
        "2025-08-07", "2025-08-08", "2025-08-11", "2025-08-12",
        "2025-08-13",
    }


def test_leading_gap_correction_preserves_existing_overlap_values():
    reconciliation = json.loads((CORRECTION / "correction/mutation_reconciliation.json").read_text())
    assert reconciliation["changed_existing_row_count"] == 0
    assert reconciliation["deleted_row_count"] == 0
    assert reconciliation["ticker_446840"]["overlap_value_equal"] is True
    assert reconciliation["ticker_446840"]["source_values_equal"] is True

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
    summary = json.loads((CORRECTION / "blast_radius/population_audit_summary.json").read_text())

    assert summary["input_population_count"] == 3149
    assert summary["output_classification_count"] == 3149
    assert summary["unresolved_count"] == 0
    assert summary["proven_affected_ticker_count"] == 1
    assert summary["potential_candidate_count"] == 46
