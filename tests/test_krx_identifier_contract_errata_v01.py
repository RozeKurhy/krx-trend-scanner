"""Offline contract tests for the verified KRX short-code ERRATA overlay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import is_valid_krx_short_code
from trend_scanner.data.source_contracts import (
    ARCHITECTURE_VERSION,
    ENDPOINT_IDENTIFIER_CONTRACT,
    STORE_FIELD_PROVENANCE,
)


ROOT = Path(__file__).resolve().parents[1]
ERRATA = ROOT / "artifacts/data/architecture/krx_production_data/v01/errata"


@pytest.mark.parametrize("ticker", ["005930", "005935", "03473K", "08537M"])
def test_verified_short_code_shapes_are_accepted(ticker):
    assert is_valid_krx_short_code(ticker)


@pytest.mark.parametrize("ticker", ["03473k", "03473-K", "03473 K", "3473K", "KR7005930003", ""])
def test_short_code_shape_is_fail_closed(ticker):
    assert not is_valid_krx_short_code(ticker)


def test_errata_contract_namespace_is_declared_exactly():
    assert ARCHITECTURE_VERSION == "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_ERRATA01"
    assert ENDPOINT_IDENTIFIER_CONTRACT["DAILY_TRADING"]["fields"]["ISU_CD"]["identifier_namespace"] == "KRX_SHORT_CODE"
    assert ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["ISU_SRT_CD"]["identifier_namespace"] == "KRX_SHORT_CODE"
    by_key = {(item.owner_store, item.target_field): item for item in STORE_FIELD_PROVENANCE}
    assert by_key[("KRXRawStockStore", "ticker")].source_semantics == "KRX_SHORT_CODE"
    assert by_key[("StockMasterStore", "ticker")].source_semantics == "KRX_SHORT_CODE"
    assert by_key[("InstrumentClassificationStore", "ticker")].source_semantics == "KRX_SHORT_CODE"


def test_adjusted_price_numeric_only_policy_is_unchanged():
    assert normalize_ticker("5930") == "005930"
    with pytest.raises(MarketDataError):
        normalize_ticker("03473K")


def test_census_artifacts_are_complete_and_source_shape_valid():
    daily = json.loads((ERRATA / "identifier_shape_census.json").read_text(encoding="utf-8"))
    basic = json.loads((ERRATA / "basic_info_identifier_census.json").read_text(encoding="utf-8"))
    assert daily["decision"] == "VALIDATED_KRX_SHORT_CODE"
    assert daily["aggregate"]["all_match_candidate_regex"] is True
    assert daily["aggregate"]["contains_letter_count"] > 0
    assert daily["aggregate"]["invalid_length_count"] == 0
    assert daily["aggregate"]["invalid_charset_count"] == 0
    assert basic["status"] == "VALIDATED_KRX_SHORT_CODE"
    assert basic["fallback"]["executed"] is False


def test_errata_does_not_auto_migrate_consumers():
    matrix = json.loads((ERRATA / "identifier_impact_matrix.json").read_text(encoding="utf-8"))
    assert matrix["consumer_auto_migration_count"] == 0
    assert not any(item["requires_change"] and item["classification"].startswith("D_") for item in matrix["hits"])


def test_corrected_diagnostic_is_two_request_pass_with_two_date_samsung_evidence():
    diagnostic = json.loads((ROOT / "artifacts/data/krx_historical_backfill/v01/FIX06_live_diagnostic_summary.json").read_text(encoding="utf-8"))
    samsung = json.loads((ROOT / "artifacts/data/krx_historical_backfill/v01/FIX06_samsung_listed_shares_evidence.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "PASS"
    assert diagnostic["request_count"] == 2
    assert diagnostic["retry_count"] == 0
    assert all(item["ticker_format_error_count"] == 0 for item in diagnostic["diagnostics"])
    assert samsung["status"] == "PASS"
    assert len(samsung["observations"]) == 2
    assert all(item["match"] is True for item in samsung["observations"])
