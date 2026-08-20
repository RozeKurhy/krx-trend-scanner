"""KRX Instrument Metadata Authority Lineage Tests (Fix Round 05).

data/reference/krx_instrument_metadata.{csv,parquet}가 실제 verified upstream
formal source(scripts/build_krx_instrument_metadata.py)에 연결되어 있는지,
manifest와 artifact가 실제로 일치하는지, historical row가 production trust에서
정확히 배제되는지를 검증한다. 이 테스트들은 모두 로컬 파일만 읽으며 네트워크를
사용하지 않는다(ZERO_NETWORK_RUNTIME 유지).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.csv"
PARQUET_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.parquet"
MANIFEST_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata_manifest.json"


def test_instrument_metadata_manifest_exists():
    """generation manifest 파일이 실제로 존재하고 필수 필드를 모두 포함하는지 검증."""
    assert MANIFEST_PATH.exists()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required_fields = [
        "artifact_version", "generated_at", "effective_date", "upstream_authority",
        "upstream_source_name", "upstream_source_location", "retrieval_method",
        "source_snapshot_date", "source_checksum_sha256", "builder_script",
        "mapping_version", "row_count", "ticker_count",
        "verified_snapshot_effective_date", "verified_row_count",
        "asset_type_distribution_verified_rows", "unknown_count_verified_rows",
        "unmapped_formal_category_count_verified_rows", "zero_network_runtime",
    ]
    for f in required_fields:
        assert f in manifest, f"manifest missing required field: {f}"
    assert manifest["zero_network_runtime"] is True
    assert Path(REPO_ROOT / manifest["builder_script"]).exists()


def test_instrument_metadata_manifest_matches_artifact():
    """manifest에 기록된 row_count/ticker_count/checksum이 실제 artifact와 일치하는지 검증."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)

    assert len(df) == manifest["row_count"]
    assert df["ticker"].nunique() == manifest["ticker_count"]

    import hashlib
    actual_checksum = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    assert actual_checksum == manifest["source_checksum_sha256"]


def test_instrument_metadata_csv_parquet_row_parity():
    """CSV와 Parquet의 row 수 및 (ticker, effective_date) unique key가 정확히 일치하는지 검증."""
    csv_df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    pq_df = pd.read_parquet(PARQUET_PATH)

    assert len(csv_df) == len(pq_df)

    csv_keys = set(zip(csv_df["ticker"], csv_df["effective_date"]))
    pq_keys = set(zip(pq_df["ticker"], pq_df["effective_date"]))
    assert csv_keys == pq_keys

    dup = csv_df.duplicated(subset=["ticker", "effective_date"]).sum()
    assert dup == 0, "duplicate canonical (ticker, effective_date) key found"


def test_instrument_metadata_formal_rows_have_valid_source_lineage():
    """verified(2026-08-14) FORMAL_SECURITY_TYPE row는 source_security_type이 비어있지 않은지 검증."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    verified = df[df["effective_date"] == "2026-08-14"]
    formal = verified[verified["classification_authority"] == "FORMAL_SECURITY_TYPE"]
    assert not formal.empty
    assert (formal["source_security_type"].fillna("") != "").all(), \
        "FORMAL_SECURITY_TYPE row는 반드시 실제 source_security_type 근거를 가져야 한다"


def test_instrument_metadata_unknown_rows_are_not_production_trusted():
    """asset_type=UNKNOWN인 verified row는 is_trusted_for_production=False인지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    unknown_verified = df[(df["effective_date"] == "2026-08-14") & (df["asset_type"] == "UNKNOWN")]
    assert not unknown_verified.empty
    for ticker in unknown_verified["ticker"]:
        meta = InstrumentMetadataResolver.resolve(ticker, as_of="2026-08-14", repo_root=REPO_ROOT)
        assert meta.is_trusted_for_production is False
    InstrumentMetadataResolver.clear_cache()


def test_instrument_metadata_unmapped_formal_category_fails_closed():
    """asset_type_source=UNMAPPED_FORMAL_CATEGORY row가 있다면 is_trusted_for_production=False인지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    unmapped = df[(df["effective_date"] == "2026-08-14") & (df["asset_type_source"] == "UNMAPPED_FORMAL_CATEGORY")]
    for ticker in unmapped["ticker"]:
        meta = InstrumentMetadataResolver.resolve(ticker, as_of="2026-08-14", repo_root=REPO_ROOT)
        assert meta.is_trusted_for_production is False
    InstrumentMetadataResolver.clear_cache()


def test_instrument_metadata_no_heuristic_promotion():
    """13개 구 SPAC ticker가 이름 heuristic이 아니라 formal SECT_TP_NM 필드로 SPAC 확인됐는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    spac_tickers = [
        "0099W0", "0105P0", "0093G0", "0130H0", "0054V0", "0096B0", "0096D0",
        "0044K0", "0071M0", "0097F0", "0091W0", "0115H0", "0041J0",
    ]
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in spac_tickers:
        meta = resolve_instrument_metadata(ticker, as_of="2026-08-14", repo_root=REPO_ROOT)
        assert meta.asset_type == "SPAC"
        assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
        row = df[(df.ticker == ticker) & (df.effective_date == "2026-08-14")].iloc[0]
        assert "SPAC" in row["source_security_type"], \
            f"{ticker}: SPAC 판정 근거가 formal SECT_TP_NM 필드(source_security_type)에 없음"


def test_instrument_metadata_known_common_regressions():
    """Fix Round 03/04에서 복원된 6개 종목이 이번 verified build에서도 COMMON으로 유지되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    common_tickers = {
        "037030": "파워넷", "047310": "파워로직스", "140520": "대창스틸",
        "195940": "HK이노엔", "138040": "메리츠금융지주",
    }
    for ticker, name_hint in common_tickers.items():
        meta = resolve_instrument_metadata(ticker, as_of="2026-08-14", repo_root=REPO_ROOT)
        assert meta.asset_type == "COMMON", f"{ticker}({name_hint}) expected COMMON, got {meta.asset_type}"
        assert meta.is_trusted_for_production is True


def test_instrument_metadata_known_etf_regressions():
    """069500/0115D0가 verified ETF product list 기준으로 여전히 ETF인지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    for ticker in ["069500", "0115D0"]:
        meta = resolve_instrument_metadata(ticker, as_of="2026-08-14", repo_root=REPO_ROOT)
        assert meta.asset_type == "ETF"
        assert meta.is_trusted_for_production is True


def test_instrument_metadata_known_spac_regressions():
    """380440(엔에이치스팩19호)이 현재 delisted 상태라 2026-08-14 verified row가 없고, 기존 값(SPAC)이 유지되는지 검증."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    row = df[df.ticker == "380440"]
    assert not row.empty
    assert (row["effective_date"] == "2026-08-14").sum() == 0, \
        "380440은 현재 delisted라 verified(2026-08-14) row가 없어야 한다"
    assert (row["asset_type"] == "SPAC").all()


def test_instrument_metadata_369370_pit_transition():
    """369370: 합병 전/후 asset_type은 PIT대로 정확하되, historical row는 LEGACY_UNVERIFIED로 fail closed되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    pre = resolve_instrument_metadata("369370", as_of="2021-06-25", repo_root=REPO_ROOT)
    assert pre.asset_type == "SPAC"
    assert pre.classification_authority == "LEGACY_UNVERIFIED"
    assert pre.is_trusted_for_production is False

    post_historical = resolve_instrument_metadata("369370", as_of="2022-06-24", repo_root=REPO_ROOT)
    assert post_historical.asset_type == "COMMON"
    assert post_historical.classification_authority == "LEGACY_UNVERIFIED"
    assert post_historical.is_trusted_for_production is False

    post_verified = resolve_instrument_metadata("369370", as_of="2026-08-14", repo_root=REPO_ROOT)
    assert post_verified.asset_type == "COMMON"
    assert post_verified.classification_authority == "FORMAL_SECURITY_TYPE"
    assert post_verified.is_trusted_for_production is True


def test_instrument_metadata_historical_rows_are_legacy_unverified():
    """2026-08-14 이전 모든 historical row가 LEGACY_UNVERIFIED로 일괄 다운그레이드됐는지 검증 (history rewrite 없이)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    historical = df[df["effective_date"] != "2026-08-14"]
    assert not historical.empty
    assert (historical["classification_authority"] == "LEGACY_UNVERIFIED").all()
    assert (historical["asset_type_source"] == "LEGACY_UNVERIFIED").all()
