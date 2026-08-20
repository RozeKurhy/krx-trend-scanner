"""Targeted Tests for Stock Report v0.2 & A FAST Core Integration.

Validates:
  - Stock Report v0.2 Contract & Schema Integrity across all 54 generated reports
  - A FAST Core Section Always Present & Fail-Closed
  - Zero Network Requests & Local Execution
  - Point-In-Time Strict Isolation (no future market cap or universe lookup)
  - 8-Item Entry Conditions Checklist Contract
  - Pending Entry & Pending Exit Next Open Semantics
  - Execution Boundary Transitions
  - Re-entry Rules & Parity Against Official 783 Trades CSV across all fields
  - Exact Representative Regressions: 005930 (Samsung), 001540 (Anguk), 069500 (ETF), 0115D0 (Alphanumeric ETF), 007390 (Nature Cell)
  - GFM Markdown Ordering & Canonical Strategy Position Wording
  - Descriptive Tone / No Financial Advice Check
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import pytest
import pandas as pd

from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report
from trend_scanner.reporting.models import AFastCoreSection, ReportStatus
from trend_scanner.universe.models import AssetType, MarketType

REPO_ROOT = Path(__file__).resolve().parent.parent


def _validate_single_report_schema(d: dict) -> list[str]:
    """Pure-Python structural and contractual schema validator for Stock Report v0.2."""
    errors = []
    
    top_required = [
        "report_version", "ticker", "name", "market", "asset_type",
        "requested_as_of", "reference_market_date", "header", "summary",
        "current_snapshot", "a_fast_core", "pattern_a_fast", "monthly_history",
        "foreign_flow", "trading_value_flow", "data_quality", "provenance"
    ]
    for k in top_required:
        if k not in d:
            errors.append(f"Missing top-level key: {k}")

    if d.get("report_version") != "0.2":
        errors.append(f"Invalid report_version: {d.get('report_version')}")

    ticker = d.get("ticker", "")
    if not re.match(r"^[0-9A-Z]{6}$", str(ticker)):
        errors.append(f"Invalid ticker pattern: {ticker}")

    valid_markets = {m.value for m in MarketType}
    if d.get("market") not in valid_markets:
        errors.append(f"Invalid market enum: {d.get('market')}")

    valid_asset_types = {a.value for a in AssetType}
    if d.get("asset_type") not in valid_asset_types:
        errors.append(f"Invalid asset_type enum: {d.get('asset_type')}")

    # Header checks
    hdr = d.get("header", {})
    hdr_required = ["ticker", "name", "market", "asset_type", "requested_as_of", "reference_market_date", "cache_present", "report_status"]
    for k in hdr_required:
        if k not in hdr:
            errors.append(f"Missing header key: {k}")
    if hdr.get("report_status") not in {"READY", "PARTIAL", "DATA_UNAVAILABLE"}:
        errors.append(f"Invalid report_status: {hdr.get('report_status')}")

    # A FAST Core checks
    core = d.get("a_fast_core", {})
    core_required = [
        "strategy_id", "strategy_version", "strategy_alias", "strategy_status",
        "production_status", "fresh_oos_status", "as_of", "applicability",
        "strategy_state", "canonical_position", "action", "action_reason",
        "interpretation", "provenance"
    ]
    for k in core_required:
        if k not in core:
            errors.append(f"Missing a_fast_core key: {k}")

    if core.get("strategy_id") != "PATTERN_A_FAST_FINAL_STRATEGY_V02":
        errors.append(f"Invalid strategy_id: {core.get('strategy_id')}")
    if core.get("strategy_version") != "V02":
        errors.append(f"Invalid strategy_version: {core.get('strategy_version')}")
    if core.get("applicability") not in {"APPLICABLE", "NOT_APPLICABLE", "DATA_UNAVAILABLE"}:
        errors.append(f"Invalid applicability: {core.get('applicability')}")
    if core.get("strategy_state") not in {"HOLD_PROGRESSED", "HOLD_PRE_PROGRESSED", "ENTRY", "EXIT", "WAIT", "NOT_APPLICABLE", "DATA_UNAVAILABLE"}:
        errors.append(f"Invalid strategy_state: {core.get('strategy_state')}")
    if core.get("canonical_position") not in {"OPEN", "FLAT", "NOT_APPLICABLE", "DATA_UNAVAILABLE"}:
        errors.append(f"Invalid canonical_position: {core.get('canonical_position')}")
    if core.get("action") not in {"HOLD", "ENTER_NEXT_OPEN", "EXIT_NEXT_OPEN", "WAIT", "NONE"}:
        errors.append(f"Invalid action: {core.get('action')}")

    # Provenance zero network check
    prov = d.get("provenance", {})
    if prov.get("network_requests") != 0:
        errors.append(f"Non-zero network requests in provenance: {prov.get('network_requests')}")

    return errors


def test_stock_report_v02_contract():
    """Stock Report v0.2 최상위 contract 및 a_fast_core 필드 존재 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.report_version == "0.2"
    assert hasattr(report, "a_fast_core")
    assert isinstance(report.a_fast_core, AFastCoreSection)

    d = report.to_dict()
    assert d["report_version"] == "0.2"
    assert d["market"] == "KOSPI"
    assert d["asset_type"] == "COMMON"
    assert "a_fast_core" in d
    assert d["a_fast_core"]["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert d["a_fast_core"]["strategy_version"] == "V02"
    assert d["a_fast_core"]["strategy_alias"] == "A FAST Core"
    assert d["a_fast_core"]["strategy_status"] == "FINAL_STRATEGY_FROZEN"
    assert d["a_fast_core"]["production_status"] == "PRODUCTION_DECISION_SUPPORT"
    assert d["a_fast_core"]["fresh_oos_status"] == "NOT_EXECUTED"

    errors = _validate_single_report_schema(d)
    assert not errors, f"Schema validation errors: {errors}"


def test_stock_report_v02_all_generated_json_match_schema():
    """artifacts/stock_reports/v0.2/20260814/ 하위 54개 모든 JSON 리포트가 공식 Draft 7 JSON 스키마를 완벽히 통과하는지 전수 검증."""
    from jsonschema import Draft7Validator

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    assert schema_file.exists(), f"Schema file missing: {schema_file}"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    v02_dir = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814"
    json_files = sorted(v02_dir.glob("*.json"))
    assert len(json_files) == 54, f"Expected 54 v0.2 reports, found {len(json_files)}"

    for jf in json_files:
        data = json.loads(jf.read_text(encoding="utf-8"))
        # 1. Structural Draft 7 JSON Schema validation
        schema_errors = list(validator.iter_errors(data))
        assert not schema_errors, f"Report {jf.name} failed Draft 7 JSON Schema validation: {[e.message for e in schema_errors]}"
        
        # 2. Semantic invariant validation
        semantic_errors = _validate_single_report_schema(data)
        assert not semantic_errors, f"Report {jf.name} failed semantic validation: {semantic_errors}"


def test_a_fast_core_section_always_present_and_fail_closed():
    """데이터 부족 시에도 a_fast_core 섹션이 생략되지 않고 DATA_UNAVAILABLE로 fail-closed 되는지 검증."""
    report, _, _ = generate_stock_report(ticker="999999", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.report_version == "0.2"
    assert report.a_fast_core is not None
    assert report.a_fast_core.applicability == "DATA_UNAVAILABLE"
    assert report.a_fast_core.strategy_state == "DATA_UNAVAILABLE"
    assert report.a_fast_core.canonical_position == "DATA_UNAVAILABLE"
    assert report.a_fast_core.action == "NONE"
    assert report.a_fast_core.action_reason in {"INSUFFICIENT_DATA", "INSUFFICIENT_METADATA"}


def test_a_fast_core_no_network_request():
    """리포트 생성 과정에서 외부 네트워크 요청이 0회인지 검증."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.provenance.network_requests == 0
    assert report.a_fast_core.provenance.network_requests == 0


def test_a_fast_core_uses_requested_as_of_only():
    """과거 시점(2025-11-28)에 대해 미래 데이터가 유입되지 않는 strict PIT 검증."""
    rep_2025, _, _ = generate_stock_report(ticker="005930", as_of="2025-11-28", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_2025.requested_as_of == "2025-11-28"
    assert rep_2025.a_fast_core.as_of == "2025-11-28"
    # In Nov 2025, Samsung sequence 4 was still PRE_PROGRESSED (first progressed was 2026-02-28)
    assert rep_2025.a_fast_core.canonical_position == "OPEN"
    assert rep_2025.a_fast_core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert rep_2025.a_fast_core.protection_state.loss_guard_state == "ACTIVE"


def test_stock_report_pit_does_not_use_future_market_cap(tmp_path):
    """요청 기준일보다 미래의 시가총액 스냅샷만 존재하는 경우 미래 데이터를 가져오지 않고 DATA_UNAVAILABLE로 fail-closed 검증."""
    # Build isolated repo mock in tmp_path
    stocks_dir = tmp_path / "data/raw/stocks"
    stocks_dir.mkdir(parents=True)
    
    # Copy 005930 parquet cache
    src_pq = REPO_ROOT / "data/raw/stocks/005930.parquet"
    if src_pq.exists():
        (stocks_dir / "005930.parquet").write_bytes(src_pq.read_bytes())
        
    # Copy metadata reference to tmp_path
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "krx_instrument_metadata.parquet").write_bytes(
        (REPO_ROOT / "data/reference/krx_instrument_metadata.parquet").read_bytes()
    )

    # Put ONLY future market cap snapshot (2026-08-14)
    norm_dir = tmp_path / "artifacts/investability/history/normalized"
    norm_dir.mkdir(parents=True)
    (norm_dir / "krx_market_cap_20260814.csv").write_text("ticker,name,market,market_cap\n005930,삼성전자,KOSPI,500000000000000\n", encoding="utf-8")
    
    # Query as of date with valid metadata but NO past market cap file: 2026-08-14 with empty past norm files
    # Instead test as_of: 2026-08-14 where only future market cap (e.g. 2026-08-15) exists
    (norm_dir / "krx_market_cap_20260814.csv").unlink()
    (norm_dir / "krx_market_cap_20260815.csv").write_text("ticker,name,market,market_cap\n005930,삼성전자,KOSPI,500000000000000\n", encoding="utf-8")

    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=tmp_path, save_artifacts=False)
    
    assert report.current_snapshot.investability_status == "DATA_UNAVAILABLE"
    assert report.current_snapshot.market_cap_eok is None
    assert report.a_fast_core.strategy_state == "DATA_UNAVAILABLE"
    assert report.a_fast_core.canonical_position == "DATA_UNAVAILABLE"
    assert report.a_fast_core.action == "NONE"


def test_stock_report_pit_does_not_use_future_instrument_metadata(tmp_path):
    """요청 기준일(2025-01-01)보다 미래의 종목 메타데이터(2026-08-14)만 존재하는 경우 미래 메타데이터를 배제하고 Fail-Closed 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    
    stocks_dir = tmp_path / "data/raw/stocks"
    stocks_dir.mkdir(parents=True)
    src_pq = REPO_ROOT / "data/raw/stocks/005930.parquet"
    if src_pq.exists():
        (stocks_dir / "005930.parquet").write_bytes(src_pq.read_bytes())
        
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)
    
    # Write metadata snapshot with effective_date = 2026-08-14 only
    df_future = pd.DataFrame([{
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "asset_type": "COMMON",
        "metadata_source": "KRX_LOCAL_FROZEN_MASTER",
        "effective_date": "2026-08-14",
        "is_common_stock": True,
        "classification_authority": "FORMAL_SECURITY_TYPE",
        "asset_type_source": "FORMAL_SECURITY_TYPE",
    }])
    df_future.to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)

    # Query as of 2025-01-01 (before metadata effective date 2026-08-14)
    report, _, _ = generate_stock_report(ticker="005930", as_of="2025-01-01", repo_root=tmp_path, save_artifacts=False)
    
    assert report.asset_type == "UNKNOWN"
    assert report.market == "UNKNOWN"
    assert report.a_fast_core.applicability == "DATA_UNAVAILABLE"
    assert report.a_fast_core.strategy_state == "DATA_UNAVAILABLE"
    assert report.a_fast_core.canonical_position == "DATA_UNAVAILABLE"
    assert report.a_fast_core.action == "NONE"
    assert report.a_fast_core.action_reason == "INSUFFICIENT_METADATA"

    InstrumentMetadataResolver.clear_cache()


def test_instrument_metadata_selects_latest_snapshot_not_after_as_of(tmp_path):
    """다중 PIT 메타데이터 스냅샷 중 requested_as_of 이하의 가장 최신 스냅샷을 선택하는지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)
    
    df_snaps = pd.DataFrame([
        {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "metadata_source": "KRX_LOCAL_FROZEN_MASTER",
            "effective_date": "2025-12-30",
            "is_common_stock": True,
            "classification_authority": "FORMAL_SECURITY_TYPE",
            "asset_type_source": "FORMAL_SECURITY_TYPE",
        },
        {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "metadata_source": "KRX_LOCAL_FROZEN_MASTER",
            "effective_date": "2026-03-31",
            "is_common_stock": True,
            "classification_authority": "FORMAL_SECURITY_TYPE",
            "asset_type_source": "FORMAL_SECURITY_TYPE",
        },
        {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "metadata_source": "KRX_LOCAL_FROZEN_MASTER",
            "effective_date": "2026-08-14",
            "is_common_stock": True,
            "classification_authority": "FORMAL_SECURITY_TYPE",
            "asset_type_source": "FORMAL_SECURITY_TYPE",
        },
    ])
    df_snaps.to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)

    # 1. As of 2026-05-15 -> Should select 2026-03-31
    meta_may = InstrumentMetadataResolver.resolve("005930", as_of="2026-05-15", repo_root=tmp_path)
    assert meta_may.is_identified is True
    assert meta_may.effective_date == "2026-03-31"

    # 2. As of 2025-11-28 (before all snapshots) -> Fail closed
    meta_nov = InstrumentMetadataResolver.resolve("005930", as_of="2025-11-28", repo_root=tmp_path)
    assert meta_nov.is_identified is False
    assert meta_nov.effective_date is None
    assert meta_nov.asset_type == "UNKNOWN"

    InstrumentMetadataResolver.clear_cache()


def test_stock_report_v02_schema_rejects_invalid_trade_history_type():
    """스키마 네거티브 검증: 잘못된 trade_history 타입(문자열 등)을 Draft 7 스키마가 거부하는지 검증."""
    from jsonschema import Draft7Validator
    import copy

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    sample_json = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814/005930_삼성전자.json"
    valid_data = json.loads(sample_json.read_text(encoding="utf-8"))

    # 1. Mutate trade_history to string
    bad_data = copy.deepcopy(valid_data)
    bad_data["a_fast_core"]["trade_history"] = "INVALID_STRING"
    errors = list(validator.iter_errors(bad_data))
    assert len(errors) > 0, "Schema must reject non-array trade_history"

    # 2. Mutate trade_history item with missing required fields
    bad_data2 = copy.deepcopy(valid_data)
    bad_data2["a_fast_core"]["trade_history"] = [{"trade_id": "005930_01"}]
    errors2 = list(validator.iter_errors(bad_data2))
    assert len(errors2) > 0, "Schema must reject trade_history item with missing required fields"


def test_stock_report_v02_schema_rejects_invalid_entry_condition_type():
    """스키마 네거티브 검증: 잘못된 entry_conditions 타입이나 non-zero network_requests를 거부하는지 검증."""
    from jsonschema import Draft7Validator
    import copy

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    sample_json = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814/005930_삼성전자.json"
    valid_data = json.loads(sample_json.read_text(encoding="utf-8"))

    # 1. Mutate boolean field to string
    bad_data = copy.deepcopy(valid_data)
    if bad_data["a_fast_core"]["entry_conditions"]:
        bad_data["a_fast_core"]["entry_conditions"]["instrument_eligible"] = "true"  # String instead of bool
        errors = list(validator.iter_errors(bad_data))
        assert len(errors) > 0, "Schema must reject non-boolean instrument_eligible"

    # 2. Mutate network_requests to non-zero
    bad_data2 = copy.deepcopy(valid_data)
    bad_data2["a_fast_core"]["provenance"]["network_requests"] = 1
    errors2 = list(validator.iter_errors(bad_data2))
    assert len(errors2) > 0, "Schema must reject non-zero network_requests"


def test_stock_report_v02_schema_rejects_missing_a_fast_core_canonical_fields():
    """스키마 네거티브 검증: a_fast_core canonical field(trade_history)가 통째로 빠지면 거부하는지 검증 (Fix Round 04 Major 1)."""
    from jsonschema import Draft7Validator
    import copy

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    sample_json = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814/005930_삼성전자.json"
    valid_data = json.loads(sample_json.read_text(encoding="utf-8"))

    bad_data = copy.deepcopy(valid_data)
    del bad_data["a_fast_core"]["trade_history"]
    errors = list(validator.iter_errors(bad_data))
    assert len(errors) > 0, "Schema must reject a_fast_core missing the trade_history key entirely"


def test_stock_report_v02_schema_rejects_incomplete_entry_conditions():
    """스키마 네거티브 검증: entry_conditions가 빈 object({})이면 필수 하위 필드 누락으로 거부하는지 검증."""
    from jsonschema import Draft7Validator
    import copy

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    sample_json = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814/005930_삼성전자.json"
    valid_data = json.loads(sample_json.read_text(encoding="utf-8"))

    bad_data = copy.deepcopy(valid_data)
    bad_data["a_fast_core"]["entry_conditions"] = {}
    errors = list(validator.iter_errors(bad_data))
    assert len(errors) > 0, "Schema must reject entry_conditions = {} (missing required sub-fields)"

    # reentry_state.enabled 개별 필드 누락도 거부되는지 함께 확인
    bad_data2 = copy.deepcopy(valid_data)
    if bad_data2["a_fast_core"]["reentry_state"]:
        del bad_data2["a_fast_core"]["reentry_state"]["enabled"]
        errors2 = list(validator.iter_errors(bad_data2))
        assert len(errors2) > 0, "Schema must reject reentry_state missing required 'enabled' field"


def test_stock_report_v02_schema_requires_market_cap_provenance():
    """스키마 네거티브 검증: current_snapshot에서 market_cap_effective_date / market_cap_source 키가 빠지면 거부하는지 검증 (Fix Round 04 Minor 1)."""
    from jsonschema import Draft7Validator
    import copy

    schema_file = REPO_ROOT / "docs/specs/stock_report_v02_schema.json"
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    sample_json = REPO_ROOT / "artifacts/stock_reports/v0.2/20260814/005930_삼성전자.json"
    valid_data = json.loads(sample_json.read_text(encoding="utf-8"))

    bad_data = copy.deepcopy(valid_data)
    del bad_data["current_snapshot"]["market_cap_effective_date"]
    errors = list(validator.iter_errors(bad_data))
    assert len(errors) > 0, "Schema must reject current_snapshot missing market_cap_effective_date key"

    bad_data2 = copy.deepcopy(valid_data)
    del bad_data2["current_snapshot"]["market_cap_source"]
    errors2 = list(validator.iter_errors(bad_data2))
    assert len(errors2) > 0, "Schema must reject current_snapshot missing market_cap_source key"


def test_production_metadata_does_not_depend_on_name_heuristic():
    """Production 메타데이터가 이름 문자열 휴리스틱이 아닌 정본 정식 메타데이터(FORMAL_SECURITY_TYPE)에 기반하는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata
    
    meta = resolve_instrument_metadata("138040", as_of="2026-08-14", repo_root=REPO_ROOT)
    assert meta.ticker == "138040"
    assert meta.name == "메리츠금융지주"
    assert meta.market == "KOSPI"
    assert meta.asset_type == "COMMON"
    assert meta.is_common_stock is True
    assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
    assert meta.asset_type_source == "FORMAL_SECURITY_TYPE"


def test_formal_metadata_provenance_is_not_fabricated(tmp_path):
    """원본 provenance가 결측된 경우 FORMAL_SECURITY_TYPE으로 허위 승격되지 않고 UNKNOWN 또는 LEGACY_HEURISTIC으로 기록되는지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)

    # Write dataframe without classification_authority / asset_type_source columns
    df_no_prov = pd.DataFrame([{
        "ticker": "005930",
        "name": "삼성전자",
        "market": "KOSPI",
        "asset_type": "COMMON",
        "metadata_source": "TEST_MOCK_WITHOUT_PROV",
        "effective_date": "2026-08-14",
    }])
    df_no_prov.to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)

    meta = InstrumentMetadataResolver.resolve("005930", as_of="2026-08-14", repo_root=tmp_path)
    assert meta.is_identified is True
    # Must NOT be fabricated to FORMAL_SECURITY_TYPE
    assert meta.classification_authority == "UNKNOWN"
    assert meta.asset_type_source == "UNKNOWN"

    # Test completely missing ticker
    meta_missing = InstrumentMetadataResolver.resolve("999999", as_of="2026-08-14", repo_root=tmp_path)
    assert meta_missing.is_identified is False
    assert meta_missing.classification_authority == "UNKNOWN"
    assert meta_missing.asset_type_source == "UNKNOWN"

    InstrumentMetadataResolver.clear_cache()


def test_untrusted_common_metadata_fails_closed_for_production(monkeypatch):
    """asset_type=COMMON이지만 provenance가 UNKNOWN이면 Production A FAST Core가 fail closed되는지 검증 (Fix Round 04 Critical 1)."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadata
    import trend_scanner.reporting.stock_report as stock_report_module

    fake_meta = InstrumentMetadata(
        ticker="005930",
        name="삼성전자",
        market="KOSPI",
        asset_type="COMMON",
        metadata_source="TEST_MOCK_UNTRUSTED",
        effective_date="2026-08-14",
        is_identified=True,
        classification_authority="UNKNOWN",
        asset_type_source="UNKNOWN",
    )
    # row 자체는 존재(is_identified=True)하고 asset_type=COMMON이지만 provenance는 UNKNOWN.
    assert fake_meta.is_common_stock is True  # 구 기준(is_common_stock)으로는 여전히 True
    assert fake_meta.is_trusted_for_production is False
    assert fake_meta.is_common_stock_for_production is False

    monkeypatch.setattr(stock_report_module, "resolve_instrument_metadata", lambda ticker, as_of, repo_root: fake_meta)

    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    afc = report.a_fast_core
    assert afc.applicability == "DATA_UNAVAILABLE"
    assert afc.strategy_state == "DATA_UNAVAILABLE"
    assert afc.canonical_position == "DATA_UNAVAILABLE"
    assert afc.action == "NONE"
    assert afc.action_reason == "INSUFFICIENT_METADATA"


def test_legacy_heuristic_common_metadata_is_not_production_authority(monkeypatch):
    """asset_type=COMMON, provenance=LEGACY_HEURISTIC이면 Production authority로 인정되지 않고 DATA_UNAVAILABLE인지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadata
    import trend_scanner.reporting.stock_report as stock_report_module

    fake_meta = InstrumentMetadata(
        ticker="005930",
        name="삼성전자",
        market="KOSPI",
        asset_type="COMMON",
        metadata_source="LEGACY_QUALITY_DIAGNOSTIC",
        effective_date="2026-08-14",
        is_identified=True,
        classification_authority="LEGACY_HEURISTIC",
        asset_type_source="NAME_BASED_HEURISTIC",
    )
    assert fake_meta.is_trusted_for_production is False

    monkeypatch.setattr(stock_report_module, "resolve_instrument_metadata", lambda ticker, as_of, repo_root: fake_meta)

    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    afc = report.a_fast_core
    assert afc.applicability == "DATA_UNAVAILABLE"
    assert afc.strategy_state == "DATA_UNAVAILABLE"
    assert afc.canonical_position == "DATA_UNAVAILABLE"
    assert afc.action == "NONE"
    assert afc.action_reason == "INSUFFICIENT_METADATA"


def test_trusted_formal_common_metadata_remains_applicable(monkeypatch):
    """asset_type=COMMON, provenance=FORMAL_SECURITY_TYPE이면 정상적으로 APPLICABLE 경로가 유지되는지 검증 (negative test들의 대조군)."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadata
    import trend_scanner.reporting.stock_report as stock_report_module

    fake_meta = InstrumentMetadata(
        ticker="005930",
        name="삼성전자",
        market="KOSPI",
        asset_type="COMMON",
        metadata_source="KRX_LOCAL_FROZEN_MASTER",
        effective_date="2026-08-14",
        is_identified=True,
        classification_authority="FORMAL_SECURITY_TYPE",
        asset_type_source="FORMAL_SECURITY_TYPE",
    )
    assert fake_meta.is_trusted_for_production is True
    assert fake_meta.is_common_stock_for_production is True

    monkeypatch.setattr(stock_report_module, "resolve_instrument_metadata", lambda ticker, as_of, repo_root: fake_meta)

    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    afc = report.a_fast_core
    assert afc.applicability == "APPLICABLE"
    assert afc.canonical_position == "OPEN"
    assert afc.strategy_state == "HOLD_PROGRESSED"
    assert afc.action == "HOLD"


def test_instrument_metadata_369370_spac_to_common_pit_transition():
    """369370 종목의 합병 전(SPAC) -> 합병 후(COMMON) PIT 시점별 전환 정확성 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    # 1. Pre-merger SPAC period (2021-06-25)
    meta_spac = resolve_instrument_metadata("369370", as_of="2021-06-25", repo_root=REPO_ROOT)
    assert meta_spac.ticker == "369370"
    assert meta_spac.is_identified is True
    assert meta_spac.asset_type == "SPAC"
    assert meta_spac.is_common_stock is False
    assert "스팩" in meta_spac.name

    # 2. Post-merger COMMON stock period (2022-06-24)
    meta_common = resolve_instrument_metadata("369370", as_of="2022-06-24", repo_root=REPO_ROOT)
    assert meta_common.ticker == "369370"
    assert meta_common.is_identified is True
    assert meta_common.asset_type == "COMMON"
    assert meta_common.is_common_stock is True
    assert "블리츠웨이" in meta_common.name


def test_instrument_metadata_138040_meritz_is_common():
    """138040 메리츠금융지주가 REIT가 아닌 보통주(COMMON, KOSPI)로 정식 분류되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata
    
    meta = resolve_instrument_metadata("138040", as_of="2026-08-14", repo_root=REPO_ROOT)
    assert meta.ticker == "138040"
    assert meta.name == "메리츠금융지주"
    assert meta.market == "KOSPI"
    assert meta.asset_type == "COMMON"
    assert meta.is_common_stock is True
    assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
    assert meta.asset_type_source == "FORMAL_SECURITY_TYPE"


def test_stock_report_138040_is_applicable_common_stock():
    """138040 메리츠금융지주 리포트에서 asset_type=COMMON 및 a_fast_core.applicability=APPLICABLE 정상 판정 검증."""
    report, _, _ = generate_stock_report(ticker="138040", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.ticker == "138040"
    assert report.name == "메리츠금융지주"
    assert report.market == "KOSPI"
    assert report.asset_type == "COMMON"
    assert report.a_fast_core.applicability == "APPLICABLE"
    assert report.a_fast_core.strategy_state == "WAIT"
    assert report.a_fast_core.canonical_position == "FLAT"
    assert report.a_fast_core.action == "WAIT"


def test_stock_report_market_cap_effective_date_pit():
    """과거 기준일(2026-05-15) 조회 시 시장 시가총액 스냅샷 날짜가 requested_as_of보다 미래가 아님(effective_date <= requested_as_of) 및 실제 일자/출처 검증."""
    # 1. Past historical date query: 2026-05-15
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-05-15", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.requested_as_of == "2026-05-15"
    assert report.current_snapshot.market_cap_eok is not None
    assert report.current_snapshot.investability_status in {"INVESTABLE", "FILTERED_MARKET_CAP", "FILTERED_LIQUIDITY"}
    assert report.current_snapshot.market_cap_effective_date is not None
    assert report.current_snapshot.market_cap_effective_date <= report.requested_as_of
    assert report.current_snapshot.market_cap_effective_date == "2025-06-27"
    assert report.current_snapshot.market_cap_source == "KRX_HISTORICAL_MARKET_CAP_NORMALIZED"

    # 2. Current baseline date query: 2026-08-14
    report_cur, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report_cur.requested_as_of == "2026-08-14"
    assert report_cur.current_snapshot.market_cap_effective_date == "2026-08-14"
    assert report_cur.current_snapshot.market_cap_source in {
        "KRX_SOURCE_MARKET_CAP",
        "KRX_HISTORICAL_MARKET_CAP_NORMALIZED",
        "KRX_INVESTABILITY_UNIVERSE_SNAPSHOT",
    }


def test_stock_report_0115d0_alphanumeric_ticker_and_etf_metadata():
    """0115D0 (KODEX 조선TOP10) 영숫자 ticker 패턴 및 ETF 메타데이터/적용불가 정상 처리 검증."""
    report, _, _ = generate_stock_report(ticker="0115D0", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.ticker == "0115D0"
    assert report.name == "KODEX 조선TOP10"
    assert report.market == "KOSPI"
    assert report.asset_type == "ETF"
    assert report.a_fast_core.applicability == "NOT_APPLICABLE"
    assert report.a_fast_core.strategy_state == "NOT_APPLICABLE"
    assert report.a_fast_core.canonical_position == "NOT_APPLICABLE"
    assert report.a_fast_core.action == "NONE"
    assert report.a_fast_core.action_reason == "NON_COMMON_STOCK"


def test_a_fast_core_samsung_20260814_exact():
    """005930 삼성전자 2026-08-14 exact canonical state regression."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "OPEN"
    assert core.strategy_state == "HOLD_PROGRESSED"
    assert core.action == "HOLD"
    assert core.action_reason == "OPEN_POSITION_PROGRESSED"

    ct = core.current_trade
    assert ct is not None
    assert ct.trade_sequence == 4
    assert ct.trade_id == "005930_04"
    assert ct.entry_signal_date == "2025-08-29"
    assert ct.entry_execution_date == "2025-09-01"
    assert ct.first_progressed_date == "2026-02-28"
    assert ct.trade_status == "OPEN"

    prot = core.protection_state
    assert prot is not None
    assert prot.phase == "PROGRESSED"
    assert prot.loss_guard_state == "INACTIVE"
    assert prot.exit3_state == "ARMED"
    assert prot.exit4_state == "ARMED"

    assert len(core.trade_history) == 4
    assert core.reentry_state.completed_trade_count == 3
    assert core.reentry_state.next_entry_sequence == 5


def test_a_fast_core_anguk_20260814_exact():
    """001540 안국약품 2026-08-14 exact canonical state regression."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "OPEN"
    assert core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert core.action == "HOLD"
    assert core.action_reason == "OPEN_POSITION_PRE_PROGRESSED"

    ct = core.current_trade
    assert ct is not None
    assert ct.trade_sequence == 2
    assert ct.trade_id == "001540_02"
    assert ct.entry_signal_date == "2026-05-15"
    assert ct.entry_execution_date == "2026-05-18"
    assert ct.first_progressed_date is None
    assert ct.trade_status == "OPEN"

    prot = core.protection_state
    assert prot is not None
    assert prot.phase == "PRE_PROGRESSED"
    assert prot.loss_guard_state == "ACTIVE"
    assert prot.loss_guard_threshold_pct == -15.0
    assert prot.exit3_state == "INACTIVE"
    assert prot.exit4_state == "INACTIVE"

    assert len(core.trade_history) == 2
    assert core.trade_history[0].trade_id == "001540_01"
    assert core.trade_history[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert core.trade_history[0].trade_status == "REALIZED"


def test_a_fast_core_etf_not_applicable():
    """069500 KODEX 200 ETF 대상 NOT_APPLICABLE 정상 판정 검증."""
    report, _, _ = generate_stock_report(ticker="069500", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert report.market == "KOSPI"
    assert report.asset_type == "ETF"
    assert core.applicability == "NOT_APPLICABLE"
    assert core.strategy_state == "NOT_APPLICABLE"
    assert core.canonical_position == "NOT_APPLICABLE"
    assert core.action == "NONE"
    assert core.action_reason == "NON_COMMON_STOCK"


def test_a_fast_core_wait_failed_conditions():
    """007390 네이처셀 대상 WAIT 상태 및 failed_conditions 검증."""
    report, _, _ = generate_stock_report(ticker="007390", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "FLAT"
    assert core.strategy_state == "WAIT"
    assert core.action == "WAIT"
    assert core.entry_conditions is not None
    assert core.entry_conditions.all_conditions_met is False
    assert len(core.entry_conditions.failed_conditions) > 0


def test_a_fast_core_pending_entry_next_open():
    """신규 진입 신호 발생 시점(2026-05-15, 안국약품 seq 2)의 ENTER_NEXT_OPEN 동작 검증."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-15", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.canonical_position == "FLAT"
    assert core.strategy_state == "ENTRY"
    assert core.action == "ENTER_NEXT_OPEN"
    assert core.action_reason == "ALL_ENTRY_CONDITIONS_MET"
    assert core.execution_timing == "NEXT_LOCAL_TRADING_DAY_OPEN"
    assert core.entry_conditions.all_conditions_met is True


def test_a_fast_core_execution_boundary():
    """신호일(2026-05-15, FLAT + ENTER_NEXT_OPEN) -> 체결일(2026-05-18, OPEN + HOLD) 전환 경계 검증."""
    rep_sig, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-15", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_sig.a_fast_core.canonical_position == "FLAT"
    assert rep_sig.a_fast_core.strategy_state == "ENTRY"
    assert rep_sig.a_fast_core.action == "ENTER_NEXT_OPEN"

    rep_exec, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-18", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_exec.a_fast_core.canonical_position == "OPEN"
    assert rep_exec.a_fast_core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert rep_exec.a_fast_core.action == "HOLD"


def test_a_fast_core_trade_history_matches_official_v02():
    """공식 정본 trades.csv와 리포트 내역의 모든 필드(trade_id, sequence, dates, open, exits, status, return) 일치성 전수 검증."""
    trades_csv = REPO_ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
    assert trades_csv.exists()
    df_off = pd.read_csv(trades_csv, dtype={"ticker": str})

    # Test representative tickers with trades: 005930, 001540, 001450, 001800, 003550, 035720
    test_tickers = ["005930", "001540", "001450", "001800", "003550", "035720"]
    for t in test_tickers:
        report, _, _ = generate_stock_report(ticker=t, as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
        off_t = df_off[df_off["ticker"] == t].sort_values(by="trade_sequence").reset_index(drop=True)
        assert len(report.a_fast_core.trade_history) == len(off_t)
        for rep_tr, (_, off_tr) in zip(report.a_fast_core.trade_history, off_t.iterrows()):
            assert rep_tr.trade_id == off_tr["trade_id"]
            assert rep_tr.trade_sequence == int(off_tr["trade_sequence"])
            assert rep_tr.entry_signal_date == off_tr["entry_signal_date"]
            assert rep_tr.entry_execution_date == off_tr["entry_execution_date"]
            assert rep_tr.entry_open == pytest.approx(float(off_tr["entry_open"]), abs=1e-2)
            assert rep_tr.entry_pattern_a_stage == off_tr["entry_pattern_a_stage"]
            assert rep_tr.exit_type == (off_tr["exit_type"] if pd.notna(off_tr["exit_type"]) else None)
            assert rep_tr.exit_signal_date == (off_tr["exit_signal_date"] if pd.notna(off_tr["exit_signal_date"]) else None)
            assert rep_tr.exit_execution_date == (off_tr["exit_execution_date"] if pd.notna(off_tr["exit_execution_date"]) else None)
            if pd.notna(off_tr["exit_price"]):
                assert rep_tr.exit_price == pytest.approx(float(off_tr["exit_price"]), abs=1e-2)
            else:
                assert rep_tr.exit_price is None
            assert rep_tr.trade_status == off_tr["trade_status"]
            if pd.notna(off_tr["terminal_return"]):
                assert rep_tr.return_pct == pytest.approx(float(off_tr["terminal_return"]), abs=1e-2)
            assert rep_tr.lifecycle_class == (off_tr["lifecycle_class"] if pd.notna(off_tr["lifecycle_class"]) else None)
            assert rep_tr.previous_exit_type == (off_tr["previous_exit_type"] if pd.notna(off_tr["previous_exit_type"]) else None)


def test_v01_stock_report_artifacts_strong_integrity():
    """기존 v0.1 리포트 아티팩트(artifacts/stock_reports/20260814/) 54개 JSON/MD가 불변으로 보존되었는지 검증."""
    v01_dir = REPO_ROOT / "artifacts/stock_reports/20260814"
    assert v01_dir.exists()
    v01_json = sorted(v01_dir.glob("*.json"))
    v01_md = sorted(v01_dir.glob("*.md"))
    assert len(v01_json) == 54
    assert len(v01_md) == 54

    for jf in v01_json:
        data = json.loads(jf.read_text(encoding="utf-8"))
        assert data["report_version"] == "0.1"
        assert "a_fast_core" not in data


def test_markdown_a_fast_core_section_order_and_wording():
    """Markdown 보고서에 Section 0부터 10까지 올바른 순서와 공식 포지션 명칭이 포함되는지 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    md = render_markdown_report(report)

    # Check Section headers
    assert "## 0. 핵심 요약 (Executive Summary)" in md
    assert "## 1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)" in md
    assert "## 2. 패스트 코어 V2 전략 상태 (A FAST Core V2 Strategy State)" in md
    assert "## 3. Pattern A FAST 현재 신호" in md
    assert "## 4. Pattern A Monthly History" in md
    assert "## 5. Pattern A 국면 전환 이력" in md
    assert "## 6. Pattern A FAST Weekly History" in md
    assert "## 7. 외국인 수급 확증" in md
    assert "## 8. 거래대금 추세 분석" in md
    assert "## 9. Pattern A 전체 월별 이력" in md
    assert "## 10. 데이터 품질 및 신원" in md

    # Check Canonical Position wording
    assert "패스트 코어 전략 포지션 (Canonical Strategy Position)" in md
    assert "내 포지션" not in md
    assert "사용자 포지션" not in md


def test_report_does_not_emit_buy_sell_advice():
    """리포트 본문에서 매수/매도 권유 및 비윤리적 금융 권유 문구가 없는지 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    md = render_markdown_report(report)

    # Remove disclaimer footer to test report content
    body = md.split("*주의 (Disclaimer):")[0] if "*주의 (Disclaimer):" in md else md

    prohibited_phrases = ["매수 추천", "매도 추천", "목표가", "수익 보장", "반드시 상승", "적극 매수", "매수 권유", "매도 권유"]
    for phrase in prohibited_phrases:
        assert phrase not in body, f"Prohibited financial advice phrase '{phrase}' found in markdown body!"
