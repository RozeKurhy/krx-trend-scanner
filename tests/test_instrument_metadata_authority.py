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
    """13개 구 SPAC ticker가 종목명 substring이 아니라 SECT_TP_NM formal 필드만으로
    SPAC 확인됐는지 검증 (Fix Round 07 Major 3: current production SPAC 판정에서
    ISU_NM/ISU_ENG_NM substring 사용 금지 — formal API 필드에서 나온 문자열이어도
    이름 substring matching이면 heuristic이다)."""
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
        assert "SECT_TP_NM=SPAC" in source, \
            f"{ticker}: SPAC 판정 근거가 SECT_TP_NM formal 필드에 없음"


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


# --- Fix Round 07 Major 1: Historical Research eligibility의 survivorship bias 제거 ----

def test_historical_research_does_not_depend_on_future_verified_snapshot(tmp_path):
    """동일 품질의 LEGACY_UNVERIFIED historical row는, 이 ticker에 대해 이후 시점에
    FORMAL_SECURITY_TYPE row가 존재하든(A) 존재하지 않든(B) 동일하게
    HISTORICAL_LEGACY_RESEARCH 자격을 얻는지 검증 (survivorship bias 제거)."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)

    historical_row = {
        "ticker": "111111", "name": "TEST_A", "market": "KOSPI", "asset_type": "COMMON",
        "metadata_source": "TEST", "effective_date": "2020-01-01",
        "classification_authority": "LEGACY_UNVERIFIED", "asset_type_source": "LEGACY_UNVERIFIED",
    }
    future_formal_row = dict(historical_row, ticker="111111", effective_date="2026-08-21",
                              classification_authority="FORMAL_SECURITY_TYPE", asset_type_source="FORMAL_SECURITY_TYPE")

    # A: future FORMAL row exists
    pd.DataFrame([historical_row, future_formal_row]).to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)
    meta_a = InstrumentMetadataResolver.resolve("111111", as_of="2020-01-01", repo_root=tmp_path)
    InstrumentMetadataResolver.clear_cache()

    # B: no future FORMAL row at all (e.g. delisted before ever re-verified)
    pd.DataFrame([dict(historical_row, ticker="222222")]).to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)
    meta_b = InstrumentMetadataResolver.resolve("222222", as_of="2020-01-01", repo_root=tmp_path)
    InstrumentMetadataResolver.clear_cache()

    assert meta_a.is_eligible_for_historical_legacy_research is True
    assert meta_b.is_eligible_for_historical_legacy_research is True
    assert meta_a.is_eligible_for_historical_legacy_research == meta_b.is_eligible_for_historical_legacy_research


def test_delisted_historical_ticker_can_use_legacy_research_mode():
    """380440(엔에이치스팩19호, delisted)의 historical as_of 조회가 future verified
    snapshot 부재 때문에 막히지 않고 HISTORICAL_LEGACY_RESEARCH로 인정되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    last_row_date = df[df.ticker == "380440"]["effective_date"].max()

    meta = resolve_instrument_metadata("380440", as_of=last_row_date, repo_root=REPO_ROOT)
    assert meta.is_identified is True
    assert meta.asset_type == "SPAC"
    assert meta.classification_authority == "LEGACY_UNVERIFIED"
    assert meta.is_trusted_for_production is False
    assert meta.is_eligible_for_historical_legacy_research is True


def test_future_formal_snapshot_does_not_change_historical_mode_result(tmp_path):
    """future formal row를 추가하기 전/후로 동일 historical as_of 조회 결과가
    (eligibility, asset_type, effective_date 모두) 완전히 동일한지 검증."""
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    InstrumentMetadataResolver.clear_cache()
    ref_dir = tmp_path / "data/reference"
    ref_dir.mkdir(parents=True)

    base_row = {
        "ticker": "333333", "name": "TEST_C", "market": "KOSPI", "asset_type": "COMMON",
        "metadata_source": "TEST", "effective_date": "2020-01-01",
        "classification_authority": "LEGACY_UNVERIFIED", "asset_type_source": "LEGACY_UNVERIFIED",
    }

    pd.DataFrame([base_row]).to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)
    before = InstrumentMetadataResolver.resolve("333333", as_of="2020-01-01", repo_root=tmp_path)
    InstrumentMetadataResolver.clear_cache()

    future_row = dict(base_row, effective_date="2026-08-21",
                       classification_authority="FORMAL_SECURITY_TYPE", asset_type_source="FORMAL_SECURITY_TYPE")
    pd.DataFrame([base_row, future_row]).to_parquet(ref_dir / "krx_instrument_metadata.parquet", index=False)
    after = InstrumentMetadataResolver.resolve("333333", as_of="2020-01-01", repo_root=tmp_path)
    InstrumentMetadataResolver.clear_cache()

    assert before.is_eligible_for_historical_legacy_research is True
    assert after.is_eligible_for_historical_legacy_research is True
    assert before.asset_type == after.asset_type
    assert before.effective_date == after.effective_date
    assert before.classification_authority == after.classification_authority


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
    실제 corruption 사례에 대한 회귀 방지).

    baseline_date는 verified_snapshot_effective_date보다 미래일 수 없다(<=) — 같은 날
    재실행(idempotent rebuild)하는 경우 baseline_date == effective_date가 될 수 있으므로
    엄격한 미만(<)이 아니라 이하(<=)로 검증한다(Fix Round 07: baseline_date는 이 build가
    데이터를 건드리기 이전, 즉 직전 build 실행의 verified snapshot을 가리킨다)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["verified_snapshot_baseline_date"] <= manifest["verified_snapshot_effective_date"]

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    baseline_rows = df[df["effective_date"] == manifest["verified_snapshot_baseline_date"]]
    assert not baseline_rows.empty
    if manifest["verified_snapshot_baseline_date"] != manifest["verified_snapshot_effective_date"]:
        assert (baseline_rows["classification_authority"] == "LEGACY_UNVERIFIED").all(), (
            "baseline_date(과거 build가 backdate했던 날짜) row는 현재 build에서 재검증된 적이 "
            "없으므로 FORMAL_SECURITY_TYPE으로 남아있으면 안 된다"
        )


# --- Fix Round 07 Major 3: SPAC current 판정에서 이름 substring 완전 제거 --------------

_MANAGED_SECTION_SPACS = {
    "465320": "교보15호기업인수목적",
    "471050": "대신밸런스제17호기업인수목적",
    "472220": "신영해피투모로우제10호기업인수목적",
}


def test_465320_not_misclassified_as_common():
    """465320(교보15호스팩)이 관리종목(소속부없음) 전환 이후 formal name-independent SPAC
    identity source를 확보하지 못해 UNKNOWN으로 fail closed되는지 검증 — COMMON도 SPAC도
    아니어야 한다(Fix Round 07 Major 3, w.md §4.10: "둘 중 어느 쪽이든 COMMON은 금지")."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    meta = resolve_instrument_metadata("465320", as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert meta.asset_type == "UNKNOWN"
    assert meta.asset_type != "COMMON"
    assert meta.is_trusted_for_production is False
    assert meta.is_common_stock_for_production is False


def test_471050_not_misclassified_as_common():
    """471050(대신밸런스제17호스팩)이 관리종목(소속부없음) 전환 이후 formal name-independent
    SPAC identity source를 확보하지 못해 UNKNOWN으로 fail closed되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    meta = resolve_instrument_metadata("471050", as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert meta.asset_type == "UNKNOWN"
    assert meta.asset_type != "COMMON"
    assert meta.is_trusted_for_production is False
    assert meta.is_common_stock_for_production is False


def test_managed_section_spac_without_identity_evidence_fails_closed():
    """SECT_TP_NM이 SPAC 문자열을 잃은 3개 실측 사례(465320/471050/472220) 모두, formal
    name-independent identity source가 없으므로 UNKNOWN + INSUFFICIENT_FORMAL_IDENTITY로
    fail closed되는지 검증 (w.md §4.10 test_managed_section_spac_without_identity_evidence_fails_closed)."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    for ticker, name_hint in _MANAGED_SECTION_SPACS.items():
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "UNKNOWN", f"{ticker}({name_hint}) expected UNKNOWN, got {meta.asset_type}"
        assert meta.asset_type_source == "INSUFFICIENT_FORMAL_IDENTITY"
        assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
        assert meta.is_trusted_for_production is False


def test_current_asset_type_does_not_use_isu_name_substrings():
    """current production 판정 결과가 ISU_NM의 "기업인수목적" substring에 의존하지 않는지
    검증 — 3개 관리종목 전환 SPAC은 ISU_NM에 "기업인수목적"이 포함되지만 이제 SPAC으로
    승격되지 않는다 (Fix Round 07 Major 3)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "ISU_NM=" in row["source_security_type"] and "기업인수목적" in row["source_security_type"], (
            f"{ticker}: 이 테스트는 ISU_NM에 '기업인수목적'이 포함된 케이스를 전제한다"
        )
        assert row["asset_type"] != "SPAC", (
            f"{ticker}: asset_type이 SPAC이면 ISU_NM substring이 여전히 판정에 쓰이고 있다는 신호"
        )


def test_current_asset_type_does_not_use_english_name_substrings():
    """current production 판정 결과가 ISU_ENG_NM의 "Special Purpose Acquisition" substring에
    의존하지 않는지 검증 (Fix Round 07 Major 3)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "ISU_ENG_NM=" in row["source_security_type"] and "Special Purpose Acquisition" in row["source_security_type"], (
            f"{ticker}: 이 테스트는 ISU_ENG_NM에 'Special Purpose Acquisition'이 포함된 케이스를 전제한다"
        )
        assert row["asset_type"] != "SPAC", (
            f"{ticker}: asset_type이 SPAC이면 ISU_ENG_NM substring이 여전히 판정에 쓰이고 있다는 신호"
        )


def test_spac_formal_identity_source_is_name_independent():
    """13개 alphanumeric SPAC과 3개 관리종목 전환 SPAC을 나누는 유일한 formal 근거가
    SECT_TP_NM(section 상태)이지 종목명이 아닌지 검증. 13개는 SECT_TP_NM에 SPAC이
    포함되어 SPAC으로 유지되고, 3개는 SECT_TP_NM에 SPAC이 없어(종목명은 둘 다 SPAC을
    암시함에도) UNKNOWN으로 갈린다 — 이것이 이름이 아니라 formal field가 판정 기준임을
    보여준다 (Fix Round 07 Major 3)."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    alphanumeric_spacs = [
        "0099W0", "0105P0", "0093G0", "0130H0", "0054V0", "0096B0", "0096D0",
        "0044K0", "0071M0", "0097F0", "0091W0", "0115H0", "0041J0",
    ]
    for ticker in alphanumeric_spacs:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "SECT_TP_NM=SPAC" in row["source_security_type"]
        assert row["asset_type"] == "SPAC"

    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "SECT_TP_NM=SPAC" not in row["source_security_type"]
        assert row["asset_type"] == "UNKNOWN"


def test_formal_spac_authority_precedes_common_share_type_mapping():
    """관리종목 전환 SPAC들이 KIND_STKCERT_TP_NM=보통주임에도(=COMMON으로 오분류될 수 있는
    조건) SPAC 이력 인지(§4.7 ambiguity 감지)가 우선 적용되어 COMMON이 아닌 UNKNOWN으로
    fail closed됐는지 검증 (Fix Round 07 Major 3, 우선순위 재정의)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in _MANAGED_SECTION_SPACS:
        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "KIND_STKCERT_TP_NM=보통주" in row["source_security_type"], (
            f"{ticker}: 이 테스트는 '보통주로 오분류될 수 있었던' 케이스를 전제하므로 "
            "KIND_STKCERT_TP_NM=보통주가 source에 있어야 한다"
        )
        assert row["asset_type"] != "COMMON"
        assert row["asset_type"] == "UNKNOWN"


# --- Fix Round 08 Major 1: Remove all name substring logic from production AssetType authority ---

def test_name_only_change_does_not_change_production_asset_type():
    """동일한 formal classification fields를 가진 두 row에서 ISU_NM만 변경되었을 때
    AssetType 결과가 변경되지 않는지 검증 (w.md §1.4)."""
    from scripts.build_krx_instrument_metadata import map_row_to_asset_type

    # Case 1: 종류주권 (Row A contains "우선주", Row B does not)
    row_a = pd.Series({
        "SECUGRP_NM": "주권",
        "SECT_TP_NM": "",
        "KIND_STKCERT_TP_NM": "종류주권",
        "ISU_NM": "삼성물산1우선주(신형)",
        "ISU_ENG_NM": "SAMSUNG C&T CORPORATION(1PB)",
    })
    row_b = pd.Series({
        "SECUGRP_NM": "주권",
        "SECT_TP_NM": "",
        "KIND_STKCERT_TP_NM": "종류주권",
        "ISU_NM": "일반회사주권",
        "ISU_ENG_NM": "NORMAL COMPANY",
    })

    type_a, _, auth_a, src_a = map_row_to_asset_type(row_a)
    type_b, _, auth_b, src_b = map_row_to_asset_type(row_b)

    assert type_a == type_b == "UNKNOWN", "종류주권은 이름과 무관하게 UNKNOWN으로 동일해야 한다"
    assert auth_a == auth_b == "FORMAL_SECURITY_TYPE"
    assert src_a == src_b == "UNMAPPED_FORMAL_CATEGORY"

    # Case 2: 보통주 (Row C contains "우선주", Row D does not)
    row_c = pd.Series({
        "SECUGRP_NM": "주권",
        "SECT_TP_NM": "우량기업부",
        "KIND_STKCERT_TP_NM": "보통주",
        "ISU_NM": "가짜우선주이름보통주",
        "ISU_ENG_NM": "FAKE PREFERRED NAME COMMON",
    })
    row_d = pd.Series({
        "SECUGRP_NM": "주권",
        "SECT_TP_NM": "우량기업부",
        "KIND_STKCERT_TP_NM": "보통주",
        "ISU_NM": "진짜보통주",
        "ISU_ENG_NM": "REAL COMMON",
    })

    type_c, _, auth_c, _ = map_row_to_asset_type(row_c)
    type_d, _, auth_d, _ = map_row_to_asset_type(row_d)

    assert type_c == type_d == "COMMON", "보통주는 이름에 '우선주'가 포함되어도 formal code에 따라 COMMON이어야 한다"
    assert auth_c == auth_d == "FORMAL_SECURITY_TYPE"


def test_preferred_classification_does_not_use_name_substrings():
    """12개 종류주권 ticker가 이름에 '우선주'가 포함되어 있어도 formal taxonomy 부족으로
    UNKNOWN + UNMAPPED_FORMAL_CATEGORY로 fail closed되는지 검증 (Fix Round 08 Major 1)."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    jongryu_tickers = [
        "00781K", "00806K", "02826K", "03473K", "03481K", "18064K",
        "28513K", "35320K", "36328K", "37550K", "38380K", "45226K",
    ]
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker in jongryu_tickers:
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "UNKNOWN", f"{ticker} expected UNKNOWN, got {meta.asset_type}"
        assert meta.asset_type_source == "UNMAPPED_FORMAL_CATEGORY"
        assert meta.is_trusted_for_production is False
        assert meta.is_common_stock_for_production is False

        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert "KIND_STKCERT_TP_NM=종류주권" in row["source_security_type"]


def test_known_preferred_regressions_formal_share_kind():
    """구형우선주(001465, 001045) 및 신형우선주(00104K)가 formal code에 따라
    PREFERRED로 판정되고 production trusted되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    preferred_test_cases = {
        "001465": "구형우선주",  # BYC우
        "001045": "구형우선주",  # CJ우
        "00104K": "신형우선주",  # CJ4우(전환)
    }
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    for ticker, expected_kind in preferred_test_cases.items():
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.asset_type == "PREFERRED", f"{ticker} expected PREFERRED, got {meta.asset_type}"
        assert meta.classification_authority == "FORMAL_SECURITY_TYPE"
        assert meta.asset_type_source == "FORMAL_SECURITY_TYPE"
        assert meta.is_trusted_for_production is True
        assert meta.is_common_stock_for_production is False

        row = df[(df.ticker == ticker) & (df.effective_date == VERIFIED_DATE)].iloc[0]
        assert f"KIND_STKCERT_TP_NM={expected_kind}" in row["source_security_type"]


# --- Fix Round 08 Major 2: Centralized Market Normalization (KOSDAQ GLOBAL -> KOSDAQ) ---

def test_krx_market_normalization_kosdaq_global_to_kosdaq():
    """normalize_krx_market()가 KOSDAQ GLOBAL을 KOSDAQ으로 정확히 정규화하는지 검증 (w.md §2.4)."""
    from trend_scanner.universe.instrument_metadata import normalize_krx_market

    assert normalize_krx_market("KOSPI") == "KOSPI"
    assert normalize_krx_market("KOSDAQ") == "KOSDAQ"
    assert normalize_krx_market("KOSDAQ GLOBAL") == "KOSDAQ"
    assert normalize_krx_market("kosdaq global") == "KOSDAQ"
    assert normalize_krx_market("KONEX") == "KONEX"
    assert normalize_krx_market("UNKNOWN") == "UNKNOWN"
    assert normalize_krx_market("INVALID_MARKET") == "UNKNOWN"
    assert normalize_krx_market(None) == "UNKNOWN"
    assert normalize_krx_market("") == "UNKNOWN"


def test_known_krx_market_values_to_unknown_count_is_zero():
    """canonical artifact 전체에서 알려진 KRX 시장(KOSPI, KOSDAQ, KOSDAQ GLOBAL, KONEX)이
    UNKNOWN으로 오분류된 row 수가 0인지 검증 (w.md §2.4)."""
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    valid_markets = {"KOSPI", "KOSDAQ", "KONEX"}
    assert set(df["market"].unique()).issubset(valid_markets), (
        f"canonical CSV에 유효하지 않은 시장 구분이 포함되어 있음: {set(df['market'].unique()) - valid_markets}"
    )
    assert (df["market"] == "UNKNOWN").sum() == 0, "알려진 KRX 시장이 UNKNOWN으로 매핑된 row가 존재함"
    assert (df["market"] == "KOSDAQ GLOBAL").sum() == 0, "KOSDAQ GLOBAL이 KOSDAQ으로 정규화되지 않고 남아있음"


def test_kosdaq_global_tickers_resolve_as_canonical_kosdaq():
    """KOSDAQ GLOBAL에 속한 대표 종목(196170 알테오젠, 241710 코스메카코리아, 009520 포스코엠텍)이
    MarketType.KOSDAQ으로 정확히 resolve되는지 검증."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    kg_sample_tickers = ["196170", "241710", "009520"]
    for ticker in kg_sample_tickers:
        meta = resolve_instrument_metadata(ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
        assert meta.market == "KOSDAQ", f"{ticker} expected market KOSDAQ, got {meta.market}"


# --- Fix Round 08 Minor 1: Harden Former SPAC Managed Issue Taxonomy ---

def test_managed_issue_taxonomy_is_contractually_exact():
    """KRX formal taxonomy에서 관리종목 category가 오직 '관리종목(소속부없음)' 하나만
    존재하는지 검증 (w.md §3.1)."""
    from scripts.build_krx_instrument_metadata import MANAGED_ISSUE_SECTIONS

    assert MANAGED_ISSUE_SECTIONS == {"관리종목(소속부없음)"}

    # source snapshot 내 모든 SECT_TP_NM 중 관리 관련 category는 이 값뿐이어야 함
    snapshot_path = REPO_ROOT / f"data/reference/source/krx_instrument_metadata_source_snapshot_{VERIFIED_DATE}.json"
    if snapshot_path.exists():
        snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
        for row in snap.get("equity", []):
            sect = row.get("SECT_TP_NM", "")
            if "관리" in sect:
                assert sect in MANAGED_ISSUE_SECTIONS, f"예상치 못한 관리종목 taxonomy 값 발견: {sect}"


def test_normal_common_in_managed_section_remains_common_if_no_spac_history():
    """과거 SPAC 이력이 전혀 없는 일반 기업이 관리종목(소속부없음)에 지정된 경우,
    COMMON으로 정상 분류되는지 검증 (w.md §3.2)."""
    from trend_scanner.universe.instrument_metadata import resolve_instrument_metadata

    # 관리종목에 속한 일반 보통주 종목
    df = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    managed_commons = df[
        (df.effective_date == VERIFIED_DATE)
        & (df.source_security_type.str.contains("SECT_TP_NM=관리종목(소속부없음)", regex=False, na=False))
        & (df.source_security_type.str.contains("KIND_STKCERT_TP_NM=보통주", regex=False, na=False))
        & (df.asset_type == "COMMON")
    ]
    assert len(managed_commons) > 0, "SPAC 이력 없는 관리종목 보통주가 최소 1개 이상 존재해야 한다"
    sample_ticker = managed_commons.iloc[0]["ticker"]
    meta = resolve_instrument_metadata(sample_ticker, as_of=VERIFIED_DATE, repo_root=REPO_ROOT)
    assert meta.asset_type == "COMMON"
    assert meta.is_trusted_for_production is True
