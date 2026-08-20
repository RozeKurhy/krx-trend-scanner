"""KRX Instrument Metadata Authority Lineage Tests (Fix Round 05/06).

data/reference/krx_instrument_metadata.{csv,parquet}가 실제 verified upstream
formal source(scripts/build_krx_instrument_metadata.py)에 연결되어 있는지,
manifest와 artifact가 실제로 일치하는지, historical row가 production trust에서
정확히 배제되는지를 검증한다. 이 테스트들은 모두 로컬 파일만 읽으며 네트워크를
사용하지 않는다(ZERO_NETWORK_RUNTIME 유지).

Fix Round 06부터 "verified"(FORMAL_SECURITY_TYPE) 날짜는 매 build 실행 시점의
실제 KST 달력 날짜(SOURCE_OBSERVATION_DATE)이며 하드코딩된 고정값이 아니다.
이 파일은 manifest에서 그 값을 읽어 VERIFIED_DATE로 사용한다(§2 backdating 금지와
동일한 원칙 — 테스트도 임의 날짜를 상정하지 않는다).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.csv"
PARQUET_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.parquet"
MANIFEST_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata_manifest.json"
BUILDER_SCRIPT_PATH = REPO_ROOT / "scripts/build_krx_instrument_metadata.py"

_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
VERIFIED_DATE = _manifest["verified_snapshot_effective_date"]
BASELINE_DATE = _manifest["verified_snapshot_baseline_date"]


def test_instrument_metadata_manifest_exists():
    """generation manifest 파일이 실제로 존재하고 필수 필드를 모두 포함하는지 검증."""
    assert MANIFEST_PATH.exists()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required_fields = [
        "artifact_version", "generated_at", "effective_date", "upstream_authority",
        "upstream_source_name", "upstream_source_location", "retrieval_method",
        "source_snapshot_date", "source_snapshot_path", "source_snapshot_sha256",
        "artifact_csv_sha256", "artifact_parquet_sha256", "builder_script",
        "mapping_version", "row_count", "ticker_count",
        "verified_snapshot_effective_date", "verified_snapshot_baseline_date",
        "verified_row_count", "asset_type_distribution_verified_rows",
        "unknown_count_verified_rows", "unmapped_formal_category_count_verified_rows",
        "zero_network_runtime", "backdating_prevention",
    ]
    for f in required_fields:
        assert f in manifest, f"manifest missing required field: {f}"
    assert manifest["zero_network_runtime"] is True
    assert Path(REPO_ROOT / manifest["builder_script"]).exists()


def test_instrument_metadata_manifest_matches_artifact():
    """manifest에 기록된 row_count/ticker_count가 실제 artifact와 일치하는지 검증."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)

    assert len(df) == manifest["row_count"]
    assert df["ticker"].nunique() == manifest["ticker_count"]


def test_manifest_csv_artifact_checksum_matches_file():
    """manifest의 artifact_csv_sha256이 실제 CSV 파일 bytes의 해시와 일치하는지 검증 (Fix Round 06 Major 2)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    assert actual == manifest["artifact_csv_sha256"]


def test_manifest_parquet_artifact_checksum_matches_file():
    """manifest의 artifact_parquet_sha256이 실제 parquet 파일 bytes의 해시와 일치하는지 검증 (Fix Round 06 Major 2)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    actual = hashlib.sha256(PARQUET_PATH.read_bytes()).hexdigest()
    assert actual == manifest["artifact_parquet_sha256"]


def test_manifest_source_checksum_is_not_output_csv_checksum():
    """source_snapshot_sha256이 artifact_csv_sha256과 다른 값인지 검증 — Fix Round 05가 냈던,
    산출물(CSV) 해시를 'source' 해시로 잘못 라벨링한 버그의 재발 방지 (Fix Round 06 Major 2)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["source_snapshot_sha256"] != manifest["artifact_csv_sha256"], (
        "source_snapshot_sha256은 실제 upstream 응답 데이터의 해시여야 하며, "
        "산출물 CSV 파일의 해시와 우연히도 같아서는 안 된다(같다면 output hash를 "
        "source hash로 잘못 재사용하고 있다는 강한 신호)."
    )
    assert manifest["source_snapshot_sha256"] != manifest["artifact_parquet_sha256"]


def test_source_snapshot_checksum_matches_canonical_source_snapshot():
    """manifest의 source_snapshot_sha256을 실제로 저장된 canonical source snapshot 파일에서 재계산해 검증 (Fix Round 06 Major 2)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    snapshot_path = REPO_ROOT / manifest["source_snapshot_path"]
    assert snapshot_path.exists(), f"source snapshot artifact missing: {snapshot_path}"

    recomputed = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    assert recomputed == manifest["source_snapshot_sha256"], (
        "저장된 source snapshot 파일의 bytes로부터 재계산한 해시가 manifest의 "
        "source_snapshot_sha256과 일치해야 한다 — 검증 가능성 자체가 이 필드의 목적이다."
    )

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["source_observation_date"] == VERIFIED_DATE
    assert "equity" in payload and len(payload["equity"]) > 0


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
    """verified(VERIFIED_DATE) FORMAL_SECURITY_TYPE row는 source_security_type이 비어있지 않은지 검증."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    verified = df[df["effective_date"] == VERIFIED_DATE]
    formal = verified[verified["classification_authority"] == "FORMAL_SECURITY_TYPE"]
    assert not formal.empty
    assert (formal["source_security_type"].fillna("") != "").all(), \
        "FORMAL_SECURITY_TYPE row는 반드시 실제 source_security_type 근거를 가져야 한다"


def test_instrument_metadata_unknown_rows_are_not_production_trusted():
    """asset_type=UNKNOWN인 verified row는 is_trusted_for_production=False인지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    unknown_verified = df[(df["effective_date"] == VERIFIED_DATE) & (df["asset_type"] == "UNKNOWN")]
    assert not unknown_verified.empty
    for ticker in unknown_verified["ticker"]:
        meta = InstrumentMetadataResolver.resolve(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.is_trusted_for_production is False
    InstrumentMetadataResolver.clear_cache()


def test_instrument_metadata_unmapped_formal_category_fails_closed():
    """asset_type_source=UNMAPPED_FORMAL_CATEGORY row가 있다면 is_trusted_for_production=False인지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    unmapped = df[(df["effective_date"] == VERIFIED_DATE) & (df["asset_type_source"] == "UNMAPPED_FORMAL_CATEGORY")]
    for ticker in unmapped["ticker"]:
        meta = InstrumentMetadataResolver.resolve(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.is_trusted_for_production is False
    InstrumentMetadataResolver.clear_cache()


def test_instrument_metadata_no_heuristic_promotion():
    """13개 구 SPAC ticker가 이름 heuristic이 아니라 formal 필드로 SPAC 확인됐는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    spac_tickers = [
        "0099W0", "0105P0", "0093G0", "0130H0", "0054V0", "0096B0", "0096D0",
        "0044K0", "0071M0", "0097F0", "0091W0", "0115H0", "0041J0",
    ]
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in spac_tickers:
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "SPAC"
        assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        source = row["source_security_type"]
        assert ("SPAC" in source) or ("Special Purpose Acquisition" in source) or ("기업인수목적" in source), \
            f"{ticker}: SPAC 판정 근거가 formal source_security_type 필드에 없음"


def test_instrument_metadata_known_common_regressions():
    """Fix Round 03/04에서 복원된 종목이 이번 verified build에서도 COMMON으로 유지되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    common_tickers = {
        "037030": "파워넷", "047310": "파워로직스", "140520": "대창스틸",
        "195940": "HK이노엔", "138040": "메리츠금융지주",
    }
    for ticker, name_hint in common_tickers.items():
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "COMMON", f"{ticker}({name_hint}) expected COMMON, got {meta.asset_type}"
        assert meta.is_trusted_for_production is True


def test_instrument_metadata_known_etf_regressions():
    """069500/0115D0가 verified ETF product list 기준으로 여전히 ETF인지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    for ticker in ["069500", "0115D0"]:
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "ETF"
        assert meta.is_trusted_for_production is True


def test_instrument_metadata_known_spac_regressions():
    """380440(엔에이치스팩19호)이 delisted 상태라 verified row가 없고, 기존 값(SPAC)이 유지되는지 검증."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    row = df[df.ticker == "380440"]
    assert not row.empty
    assert (row["classification_authority"] == "FORMAL_SECURITY_TYPE").sum() == 0, \
        "380440은 현재 delisted라 어떤 verified row도 있으면 안 된다"
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

    post_verified = resolve_instrument_metadata("369370", as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert post_verified.asset_type == "COMMON"
    assert post_verified.classification_authority == "FORMAL_SECURITY_TYPE"
    assert post_verified.is_trusted_for_production is True


def test_instrument_metadata_historical_rows_are_legacy_unverified():
    """VERIFIED_DATE 이외 모든 row가 LEGACY_UNVERIFIED로 일괄 다운그레이드됐는지 검증 (history rewrite 없이)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    historical = df[df["effective_date"] != VERIFIED_DATE]
    assert not historical.empty
    assert (historical["classification_authority"] == "LEGACY_UNVERIFIED").all()
    assert (historical["asset_type_source"] == "LEGACY_UNVERIFIED").all()


# --- Fix Round 06 Critical 1: PIT backdating 구조적 차단 -------------------------------

def test_live_metadata_snapshot_cannot_be_backdated():
    """builder 스크립트에 임의 날짜를 주입할 CLI 경로 자체가 없는지 검증 (Fix Round 06 Critical 1).

    Fix Round 05는 --as-of-date로 임의 과거 날짜를 지정할 수 있어, 실제로는
    빌드 시점(예: 2026-08-20/21)에 관측한 live snapshot을 2026-08-14라는 과거
    effective_date에 써넣는 PIT lookahead를 냈다. 이 스크립트는 그 인자를
    완전히 제거했다.
    """
    source = BUILDER_SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'add_argument("--as-of-date"' not in source, (
        "builder script의 argparse는 verified snapshot의 effective_date를 CLI로 주입받는 "
        "옵션을 등록하고 있으면 안 된다 (backdating 경로 원천 차단)"
    )
    assert "SOURCE_OBSERVATION_DATE" in source
    assert "Timestamp.now" in source

    # 스크립트 텍스트가 아니라 실제 산출물에서도 검증한다: FORMAL_SECURITY_TYPE row는
    # 오직 하나의 effective_date에만 존재해야 하며, 그 날짜는 artifact 전체의 최댓값이어야
    # 한다 — CLI 인자 이름이 나중에 바뀌어도(예: --snapshot-date) 이 검증은 깨지지 않는다.
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    formal_dates = set(df[df["classification_authority"] == "FORMAL_SECURITY_TYPE"]["effective_date"])
    assert len(formal_dates) == 1, f"FORMAL_SECURITY_TYPE row는 단일 effective_date에만 존재해야 한다: {formal_dates}"
    assert formal_dates == {df["effective_date"].max()}


def test_verified_metadata_effective_date_matches_source_observation_date():
    """manifest의 verified_snapshot_effective_date == source_snapshot_date == effective_date(top-level)인지 검증 (Fix Round 06 Critical 1)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["verified_snapshot_effective_date"] == manifest["source_snapshot_date"]
    assert manifest["verified_snapshot_effective_date"] == manifest["effective_date"]


def test_manifest_does_not_claim_historical_verification_from_live_source():
    """이전 실행에서 formal-verified라고 잘못 주장됐던 baseline_date row가 이번 build에서
    LEGACY_UNVERIFIED로 재정정됐는지 검증 (Fix Round 06 Critical 1 — Fix Round 05의
    실제 corruption 사례에 대한 회귀 방지)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["verified_snapshot_baseline_date"] < manifest["verified_snapshot_effective_date"]

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    baseline_rows = df[df["effective_date"] == manifest["verified_snapshot_baseline_date"]]
    assert not baseline_rows.empty
    assert (baseline_rows["classification_authority"] == "LEGACY_UNVERIFIED").all(), (
        "baseline_date(과거 build가 backdate했던 날짜) row는 현재 build에서 재검증된 적이 "
        "없으므로 FORMAL_SECURITY_TYPE으로 남아있으면 안 된다"
    )


# --- Fix Round 06 Critical 2: section-independent SPAC identity ------------------------

_MANAGED_SECTION_SPACS = {
    "465320": "교보15호기업인수목적",
    "471050": "대신밸런스제17호기업인수목적",
    "472220": "신영해피투모로우제10호기업인수목적",
}


def test_465320_not_misclassified_as_common():
    """465320(교보15호스팩)이 관리종목(소속부없음) 전환 이후에도 COMMON이 아닌 SPAC으로 유지되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    meta = resolve_instrument_metadata("465320", as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert meta.asset_type == "SPAC"
    assert meta.is_trusted_for_production is True
    assert meta.is_common_stock_for_production is False


def test_471050_not_misclassified_as_common():
    """471050(대신밸런스제17호스팩)이 관리종목(소속부없음) 전환 이후에도 COMMON이 아닌 SPAC으로 유지되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    meta = resolve_instrument_metadata("471050", as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert meta.asset_type == "SPAC"
    assert meta.is_trusted_for_production is True
    assert meta.is_common_stock_for_production is False


def test_spac_remains_spac_when_section_changes():
    """SECT_TP_NM이 SPAC 문자열을 잃은 3개 실측 사례(465320/471050/472220) 모두 SPAC으로 유지되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    for ticker, name_hint in _MANAGED_SECTION_SPACS.items():
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "SPAC", f"{ticker}({name_hint}) expected SPAC, got {meta.asset_type}"
        assert meta.classification_authority == "FORMAL_SECURITY_TYPE"


def test_spac_identity_is_not_derived_from_current_section_only():
    """3개 관리종목 전환 SPAC의 source_security_type에 SECT_TP_NM=SPAC 문자열이 없는데도
    ISU_ENG_NM/ISU_NM 필드 근거로 SPAC 판정됐는지 검증 — section 상태와 무관한 identity (Fix Round 06 Critical 2)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)]
        assert not row.empty, f"{ticker}: verified row missing"
        source = row.iloc[0]["source_security_type"]
        assert "SECT_TP_NM=SPAC" not in source, (
            f"{ticker}: 이 테스트는 SECT_TP_NM이 더 이상 SPAC을 나타내지 않는 사례를 검증하는 것이므로 "
            "source_security_type에 SECT_TP_NM=SPAC이 있으면 전제가 깨진다"
        )
        assert ("Special Purpose Acquisition" in source) or ("기업인수목적" in source), (
            f"{ticker}: SPAC 판정 근거가 ISU_ENG_NM/ISU_NM 공식 필드에 없음"
        )


def test_formal_spac_authority_precedes_common_share_type_mapping():
    """관리종목 전환 SPAC들이 KIND_STKCERT_TP_NM=보통주임에도(=COMMON으로 오분류될 수 있는 조건)
    SPAC identity가 우선 적용되어 실제로는 SPAC으로 판정됐는지 검증 (Fix Round 06 Critical 2, 우선순위)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "KIND_STKCERT_TP_NM=보통주" in row["source_security_type"], (
            f"{ticker}: 이 테스트는 '보통주로 오분류될 수 있었던' 케이스를 전제하므로 "
            "KIND_STKCERT_TP_NM=보통주가 source에 있어야 한다"
        )
        assert row["asset_type"] == "SPAC"
