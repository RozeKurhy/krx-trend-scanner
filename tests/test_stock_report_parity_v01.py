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
    FIX01_EVIDENCE_ROOT,
    RUNTIME_METADATA_FIELDS,
    RUNTIME_METADATA_FIELD_COUNT,
    RUNTIME_METADATA_SENTINEL,
    TICKER_RE,
    coway_cache_state,
    derive_corpus,
    markdown_runtime_delta,
    normalize_json_runtime_metadata,
    normalize_markdown_runtime_metadata,
    offline_guards,
    sha256_file,
    validate_runtime_metadata_delta,
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


def _metadata_fixture() -> tuple[dict, dict, dict]:
    canonical = {"header": {"cache_last_date": "2026-08-14"}, "data_quality": {"cache_last_date": "2026-08-14", "daily_rows_count": 1222}}
    current = {"header": {"cache_last_date": "2026-08-21"}, "data_quality": {"cache_last_date": "2026-08-21", "daily_rows_count": 1226}}
    state = {"current_cache_last_date": "2026-08-21", "current_rows_gt_as_of": 4, "current_rows_le_as_of": 1222, "canonical_daily_rows_count": 1222, "all_extra_rows_date_future": True, "pre_or_on_as_of_extra_row_count": 0}
    return canonical, current, state


def test_runtime_metadata_allowlist_is_exactly_three_fields():
    assert RUNTIME_METADATA_FIELD_COUNT == 3
    assert RUNTIME_METADATA_FIELDS == ("header.cache_last_date", "data_quality.cache_last_date", "data_quality.daily_rows_count")


def test_runtime_metadata_delta_requires_future_only_rows():
    canonical, current, state = _metadata_fixture()
    assert validate_runtime_metadata_delta(canonical, current, state)["passed"] is True
    state["current_cache_last_date"] = "2026-08-14"
    assert validate_runtime_metadata_delta(canonical, current, state)["passed"] is False


def test_runtime_metadata_delta_rejects_pre_asof_extra_row():
    canonical, current, state = _metadata_fixture()
    state["all_extra_rows_date_future"] = False
    assert validate_runtime_metadata_delta(canonical, current, state)["passed"] is False


def test_runtime_metadata_delta_rejects_any_pre_or_on_asof_extra_row():
    canonical, current, state = _metadata_fixture()
    state["pre_or_on_as_of_extra_row_count"] = 1
    assert validate_runtime_metadata_delta(canonical, current, state)["passed"] is False


def test_runtime_metadata_delta_rejects_asof_row_count_mismatch():
    canonical, current, state = _metadata_fixture()
    state["current_rows_le_as_of"] = 1221
    assert validate_runtime_metadata_delta(canonical, current, state)["passed"] is False


def test_non_allowlisted_json_field_still_fails():
    canonical, current, state = _metadata_fixture()
    current["summary"] = {"headline": "mutated"}
    result = validate_runtime_metadata_delta(canonical, current, state)
    assert result["passed"] is False
    assert "summary" in result["delta"]["paths"]


def test_strategy_field_cannot_be_normalized():
    canonical, current, _ = _metadata_fixture()
    canonical["current_snapshot"] = {"pattern_a_score": 1.0}
    current["current_snapshot"] = {"pattern_a_score": 2.0}
    assert normalize_json_runtime_metadata(canonical)["current_snapshot"] != normalize_json_runtime_metadata(current)["current_snapshot"]


def test_canonical_position_field_cannot_be_normalized():
    canonical, current, _ = _metadata_fixture()
    canonical["a_fast_core"] = {"canonical_position": "OPEN"}
    current["a_fast_core"] = {"canonical_position": "CLOSED"}
    result = validate_runtime_metadata_delta(canonical, current, _metadata_fixture()[2])
    assert result["passed"] is False
    assert "a_fast_core.canonical_position" in result["delta"]["paths"]


def test_relative_strength_field_cannot_be_normalized():
    canonical, current, _ = _metadata_fixture()
    canonical["relative_strength"] = {"market_rs_3m": 1.0}
    current["relative_strength"] = {"market_rs_3m": 2.0}
    result = validate_runtime_metadata_delta(canonical, current, _metadata_fixture()[2])
    assert result["passed"] is False
    assert "relative_strength.market_rs_3m" in result["delta"]["paths"]


def test_cache_first_date_field_cannot_be_normalized():
    canonical, current, _ = _metadata_fixture()
    canonical["header"]["cache_first_date"] = "2021-08-17"
    current["header"]["cache_first_date"] = "2021-08-16"
    result = validate_runtime_metadata_delta(canonical, current, _metadata_fixture()[2])
    assert result["passed"] is False
    assert "header.cache_first_date" in result["delta"]["paths"]


def test_markdown_normalization_is_exact_line_scoped():
    canonical = "- **로컬 일봉 캐시**: `정상 로드 (1222행)`\n- **데이터 기간**: `2021-08-17` ~ `2026-08-14`\n- **기타**: `same`\n"
    current = "- **로컬 일봉 캐시**: `정상 로드 (1226행)`\n- **데이터 기간**: `2021-08-17` ~ `2026-08-21`\n- **기타**: `same`\n"
    delta = markdown_runtime_delta(canonical, current)
    assert delta["passed"] is True
    assert delta["line_count"] == 2
    assert normalize_markdown_runtime_metadata(canonical, delta) == normalize_markdown_runtime_metadata(current, delta)
    mutated = current.replace("기타**: `same`", "기타**: `different`")
    assert markdown_runtime_delta(canonical, mutated)["passed"] is False


def test_coway_post_freeze_cache_delta_is_expected():
    _frame, state, extras = coway_cache_state()
    assert state["current_rows_le_as_of"] == state["canonical_daily_rows_count"] == 1222
    assert state["current_rows_gt_as_of"] == 4
    assert state["pre_or_on_as_of_extra_row_count"] == 0
    assert len(extras) == 4
    assert all(row["date"] > "2026-08-14" for row in extras)


def test_behavioral_parity_all_54_reports():
    summary = json.loads((FIX01_EVIDENCE_ROOT / "behavioral_parity/behavioral_summary.json").read_text(encoding="utf-8"))
    assert summary["behavioral_json_pass"] == "54/54"
    assert summary["behavioral_markdown_pass"] == "54/54"
    assert summary["behavioral_report_pass"] == "54/54"
    assert summary["normalized_json_semantic_mismatches"] == 0
    assert summary["normalized_markdown_mismatches"] == 0
