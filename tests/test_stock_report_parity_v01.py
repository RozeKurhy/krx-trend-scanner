"""Offline contract checks for STOCK_REPORT_PARITY_V01."""

from __future__ import annotations

import json
import socket
from tempfile import TemporaryDirectory
from pathlib import Path

from jsonschema import Draft7Validator

from scripts.run_stock_report_parity_v01 import (
    CANONICAL_DIR,
    EXPECTED_PHASE12_CLOSURE_SHA,
    RS_SOURCE_PATH,
    TICKER_RE,
    derive_corpus,
    offline_guards,
    sha256_file,
)
from trend_scanner.reporting.stock_report import generate_stock_report


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_authority_is_54_reports_and_preserves_ticker_identity():
    tickers, reports, hashes = derive_corpus()
    assert len(tickers) == 54
    assert len(reports) == 54
    assert len(hashes) == 108
    assert "0115D0" in tickers
    assert all(TICKER_RE.fullmatch(ticker) for ticker in tickers)
    assert {path.stem.split("_", 1)[0] for path in CANONICAL_DIR.glob("*.md")} == set(tickers)


def test_all_canonical_json_validate_against_frozen_v03_schema():
    schema = json.loads((ROOT / "docs/reporting/stock_report/schema_v03.json").read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    errors = []
    for path in sorted(CANONICAL_DIR.glob("*.json")):
        errors.extend((path.name, error.message) for error in validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))))
    assert errors == []


def test_canaries_non_common_and_sector_julia_boundaries():
    reports = {value["ticker"]: value for value in (json.loads(path.read_text(encoding="utf-8")) for path in CANONICAL_DIR.glob("*.json"))}
    samsung = reports["005930"]
    assert samsung["header"]["report_status"] == "READY"
    assert samsung["relative_strength"]["data_status"] == "READY"
    assert samsung["a_fast_core"]["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    etf = reports["069500"]
    assert etf["asset_type"] == "ETF"
    assert etf["relative_strength"]["applicability"] == "NOT_APPLICABLE"
    assert etf["relative_strength"]["data_status"] == "NOT_EVALUATED"
    schema_text = (ROOT / "docs/reporting/stock_report/schema_v03.json").read_text(encoding="utf-8").lower()
    assert "sector_relative_strength" not in schema_text
    assert '"sector_rs"' not in schema_text
    assert '"julia"' not in schema_text


def test_exact_phase12_source_identity_and_no_network_socket_is_used():
    manifest = json.loads((ROOT / "artifacts/reporting/stock_reports/validation/v0.3/stock_report_v03_manifest_20260814.json").read_text(encoding="utf-8"))
    assert sha256_file(RS_SOURCE_PATH) == manifest["phase12_source"]["sha256"]
    assert manifest["phase12_source"]["closure_sha"] == EXPECTED_PHASE12_CLOSURE_SHA
    # A real executable call is made while the runner's fail-closed guard is
    # installed.  Any accidental KRX/PyKRX/Naver/OpenDART request therefore
    # fails the test instead of silently reaching the network.
    original_connect = socket.socket.connect
    with TemporaryDirectory(prefix="stock_report_parity_test_") as output:
        with offline_guards() as state:
            generate_stock_report("005930", "2026-08-14", ROOT, True, output)
        assert state["network"].calls == 0
        assert state["scanner_calls"]["count"] == 0
    assert socket.socket.connect is original_connect
