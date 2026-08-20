#!/usr/bin/env python3
"""KRX Instrument Metadata Canonical Build (Fix Round 06, Critical 1/2, Major 2).

data/reference/krx_instrument_metadata.{csv,parquet}의 asset_type 분류를
실제 verified upstream KRX formal source에 연결한다.

Upstream authority (실제 확인됨, build-time에만 network 접근 — Stock Report
runtime은 이 artifact를 읽기만 하며 ZERO_NETWORK_RUNTIME=YES 유지):

  1. 전종목기본정보 (KRX MDC, bld=dbms/MDC/STAT/standard/MDCSTAT01901)
     mktId=ALL(KOSPI+KOSDAQ), mktId=KNX(코넥스) 각각 조회.
     인증 세션(KRX_ID/KRX_PW, .env) 필요 — 익명 요청은 이 bld에서 "LOGOUT"으로 거부됨.
     필드: SECUGRP_NM(증권그룹명), SECT_TP_NM(소속부명), KIND_STKCERT_TP_NM(주권종류구분명:
     보통주/구형우선주/신형우선주/종류주권), ISU_NM(공식 한글 종목명), ISU_ENG_NM(공식
     영문 종목명).
  2. pykrx get_etf_ticker_list / get_etn_ticker_list (동일 인증 세션 필요).
  3. 상폐종목검색 (delisted finder) — manifest 기록 및 경계 확인용(현재 상장이 아닌
     티커의 존재 자체를 확인하는 데만 사용, security type 필드는 제공하지 않음).

Fix Round 06 Critical 1 — PIT backdating 금지 (w.md §2):
  이 스크립트가 실제로 verify할 수 있는 것은 "스크립트 실행 시점"(SOURCE_OBSERVATION_DATE,
  실행 시각의 UTC 날짜)의 KRX 상장 상태 단 하나의 snapshot뿐이다. Fix Round 05는 이
  값을 임의의 --as-of-date(과거 날짜, 예: 2026-08-14)에 덮어써 실제 관측일보다 과거
  시점을 formal-verified라고 주장하는 PIT lookahead 오류를 냈다. 이 스크립트는 그
  CLI 인자를 완전히 제거했다 — 새로 검증된 row의 effective_date는 항상
  SOURCE_OBSERVATION_DATE이며, 그 값을 다른 날짜로 바꿔 쓸 방법 자체가 코드에 없다
  (backdating은 인자 부재로 구조적으로 불가능하다). effective_date ==
  SOURCE_OBSERVATION_DATE가 아닌 모든 row(이전 실행에서 잘못 formal-verified로
  표시된 2026-08-14 row 포함)는 매 실행마다 classification_authority/
  asset_type_source가 "LEGACY_UNVERIFIED"로 낮춰진다(과거 값을 오늘자 조회
  결과로 소급 덮어쓰지 않는다).

Fix Round 06 Critical 2 — SPAC identity의 section-independence (w.md §3):
  SPAC이 관리종목(소속부없음)으로 이동하면 SECT_TP_NM에서 "SPAC" 문자열이 사라진다
  (실제 사례: 465320, 471050, 472220). SECT_TP_NM 단독 판정은 이 상태 전이에
  취약하므로, 동일 formal record 내의 두 개의 독립된 공식 필드로 교차 검증한다:
  ISU_ENG_NM(공식 영문명)에 "Special Purpose Acquisition" 포함 여부, ISU_NM(공식
  한글명)에 "기업인수목적" 포함 여부. 실측 결과 이 두 신호는 완전히 동일한 71개
  ticker 집합을 가리키며(교집합=합집합), SECT_TP_NM 기반 신호(68개)의 상위 집합이다
  — 즉 SECT_TP_NM이 SPAC 지위를 잃어도 공식 종목명 필드는 SPAC 정체성을 계속 보존한다.

Fix Round 06 Major 2 — checksum 의미 분리 (w.md §5):
  Fix Round 05는 "source_checksum_sha256"라는 이름으로 실제로는 산출물(CSV)의
  해시를 기록했다(source가 아니라 artifact의 해시). 이 스크립트는 세 값을 분리한다:
    - source_snapshot_sha256: canonical-serialize한 실제 upstream KRX 응답
      데이터(equity + ETF/ETN ticker 목록 + delisted reference)의 해시.
    - artifact_csv_sha256 / artifact_parquet_sha256: 실제 생성된 산출물 파일의 해시.
  Canonical source snapshot은 data/reference/source/에 실제로 저장하여(git 추적)
  manifest의 source_snapshot_sha256을 재계산으로 검증 가능하게 한다.

Usage:
    uv run python scripts/build_krx_instrument_metadata.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from pykrx.website.comm.auth import build_krx_session, set_auth_session  # noqa: E402
from pykrx.website.krx.market.core import 전종목기본정보, 상폐종목검색  # noqa: E402
from pykrx import stock  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.csv"
PARQUET_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.parquet"
MANIFEST_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata_manifest.json"
SOURCE_SNAPSHOT_DIR = REPO_ROOT / "data/reference/source"

METADATA_SOURCE_VERIFIED = "KRX_MDC_VERIFIED_LIVE"
METADATA_SOURCE_LEGACY = "KRX_LOCAL_FROZEN_MASTER"
AUTH_FORMAL = "FORMAL_SECURITY_TYPE"
AUTH_UNMAPPED = "UNMAPPED_FORMAL_CATEGORY"
AUTH_LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
AUTH_UNKNOWN = "UNKNOWN"

BUILDER_SCRIPT = "scripts/build_krx_instrument_metadata.py"
MAPPING_VERSION = "v2"

# Fix Round 06 Critical 1: 유일한 진실. 새로 검증되는 row의 effective_date는
# 항상 이 값이며, 다른 값으로 대체할 CLI 경로가 없다 (backdating 구조적 차단).
# KRX 거래일/effective_date는 이 project 전체에서 KST(Asia/Seoul) 기준 달력 날짜이므로
# (build_krx_trading_calendar.py와 동일 관례), UTC 날짜가 아닌 KST 날짜를 쓴다 —
# UTC 자정 이후 KST 오전 시간대(UTC와 캘린더 날짜가 갈리는 구간)에 실행하면 UTC 기준은
# 하루 전 날짜로 어긋난다.
SOURCE_OBSERVATION_DATE = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")


def fetch_live_formal_universe() -> tuple[pd.DataFrame, set[str], set[str], pd.DataFrame]:
    """인증 세션으로 KRX MDC에서 실제 formal 분류 데이터를 조회한다."""
    sess = build_krx_session()
    if sess is None or not sess.is_authenticated:
        raise RuntimeError("KRX 인증 세션 생성 실패 — KRX_ID/KRX_PW(.env) 확인 필요.")
    set_auth_session(sess)

    df_kospi_kosdaq = 전종목기본정보().fetch(mktId="ALL", segTpCd="ALL")
    df_konex = 전종목기본정보().fetch(mktId="KNX", segTpCd="ALL")
    df_equity = pd.concat([df_kospi_kosdaq, df_konex], ignore_index=True)
    df_equity = df_equity.drop_duplicates(subset=["ISU_SRT_CD"], keep="first")

    etf_tickers = set(stock.get_etf_ticker_list())
    etn_tickers = set(stock.get_etn_ticker_list())

    df_delisted = 상폐종목검색().fetch("ALL", "")

    return df_equity, etf_tickers, etn_tickers, df_delisted


def map_row_to_asset_type(row: pd.Series) -> tuple[str, str, str, str]:
    """KRX formal category row -> (asset_type, source_security_type, classification_authority, asset_type_source).

    Priority order (w.md Fix Round 06 §3.4): SPAC identity -> REIT/security-group ->
    PREFERRED/COMMON -> UNKNOWN. (ETF/ETN은 이 함수 호출 이전, classify_ticker에서
    별도 formal ticker-list 소스로 먼저 판정된다.)

      SPAC identity (Fix Round 06 Critical 2, section-independent, 두 개의 독립된
      공식 필드로 교차 검증):
        SECT_TP_NM에 "SPAC" 포함
        OR ISU_ENG_NM(공식 영문명)에 "Special Purpose Acquisition" 포함
        OR ISU_NM(공식 한글명)에 "기업인수목적" 포함
        -> SPAC
        (SECT_TP_NM만 보면 관리종목(소속부없음)으로 전환된 SPAC(465320, 471050,
        472220 실측 확인)을 놓친다. ISU_ENG_NM/ISU_NM 신호는 실측상 완전히 동일한
        71개 ticker 집합이며 SECT_TP_NM 기반 68개의 상위 집합이다 — SPAC이 관리종목
        상태가 되어도 공식 종목명 필드는 정체성을 계속 보존하므로 SECT_TP_NM보다
        먼저, section 상태와 무관하게 판정한다.)
      SECUGRP_NM == "부동산투자회사"                -> REIT
      KIND_STKCERT_TP_NM == "보통주"                -> COMMON
      KIND_STKCERT_TP_NM in (구형우선주, 신형우선주)  -> PREFERRED
      KIND_STKCERT_TP_NM == "종류주권"
        AND ISU_NM에 "우선주" 포함                  -> PREFERRED
        (조사 결과: 이 KRX taxonomy에서 "종류주권"은 알파뉴메릭 ticker(K 접미)를
        쓰는 우선주 12건 전부에 해당하며, 그 근거는 같은 formal record의 공식
        종목명(ISU_NM) 필드가 "...우선주"/"...우선주(신형)"로 명시하고 있다는
        점이다. 이는 별도의 비공식 source의 이름 문자열과 대조하는 heuristic이
        아니라, 동일한 formal record 내부의 다른 formal field로 재확인하는
        것이다.)
      그 외(외국주권/주식예탁증권/사회간접자본투융자회사/
      투자회사/종류주권(비우선주) 등)                -> UNKNOWN (source는 formal이나 mapping 불가,
                                                        asset_type_source=UNMAPPED_FORMAL_CATEGORY)
    """
    secugrp = str(row.get("SECUGRP_NM", "")).strip()
    sect = str(row.get("SECT_TP_NM", "")).strip()
    kind = str(row.get("KIND_STKCERT_TP_NM", "")).strip()
    isu_nm = str(row.get("ISU_NM", "")).strip()
    isu_eng_nm = str(row.get("ISU_ENG_NM", "")).strip()
    source_security_type = (
        f"SECUGRP_NM={secugrp}|SECT_TP_NM={sect}|KIND_STKCERT_TP_NM={kind}"
        f"|ISU_NM={isu_nm}|ISU_ENG_NM={isu_eng_nm}"
    )

    is_spac = (
        "SPAC" in sect
        or "Special Purpose Acquisition" in isu_eng_nm
        or "기업인수목적" in isu_nm
    )
    if is_spac:
        return "SPAC", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if secugrp == "부동산투자회사":
        return "REIT", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if kind == "보통주":
        return "COMMON", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if kind in ("구형우선주", "신형우선주"):
        return "PREFERRED", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if kind == "종류주권" and "우선주" in isu_nm:
        return "PREFERRED", source_security_type, AUTH_FORMAL, AUTH_FORMAL

    # formal source에서 row는 찾았으나(예: 외국주권/주식예탁증권/종류주권(비우선주)/
    # 투자회사/사회간접자본투융자회사) AssetType enum으로 deterministic mapping이
    # 불가능한 경우. source는 formal이었다는 사실과 asset type mapping은 신뢰할 수
    # 없다는 사실을 w.md §2.10에 따라 별도 필드로 분리한다.
    return "UNKNOWN", source_security_type, AUTH_FORMAL, AUTH_UNMAPPED


def classify_ticker(
    ticker: str,
    df_equity: pd.DataFrame,
    etf_tickers: set[str],
    etn_tickers: set[str],
) -> tuple[str, str, str, str]:
    if ticker in etf_tickers:
        return "ETF", "PYKRX_ETF_TICKER_LIST", AUTH_FORMAL, AUTH_FORMAL
    if ticker in etn_tickers:
        return "ETN", "PYKRX_ETN_TICKER_LIST", AUTH_FORMAL, AUTH_FORMAL

    match = df_equity[df_equity["ISU_SRT_CD"] == ticker]
    if match.empty:
        # formal source(현재 상장 전종목 + ETF/ETN 목록)를 실제로 조회했으나
        # 이 ticker를 찾지 못함 — 임의로 COMMON 등을 추정하지 않고 UNKNOWN.
        return "UNKNOWN", "", AUTH_UNKNOWN, AUTH_UNKNOWN

    return map_row_to_asset_type(match.iloc[0])


def _canonical_json_bytes(payload: dict) -> bytes:
    """정렬된 key, 고정 구분자로 직렬화 — 동일 데이터는 항상 동일 bytes를 낸다."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_canonical_source_snapshot(
    df_equity: pd.DataFrame,
    etf_tickers: set[str],
    etn_tickers: set[str],
    df_delisted: pd.DataFrame,
) -> dict:
    """실제 upstream KRX 응답 데이터를 canonical(정렬, 문자열화) 형태로 직렬화한다.

    이 payload의 해시가 manifest의 source_snapshot_sha256이다 — 산출물(CSV/parquet)이
    아니라 실제 조회한 원본 응답 데이터의 fingerprint (Fix Round 06 Major 2).
    """
    equity_records = (
        df_equity.fillna("").astype(str).sort_values("ISU_SRT_CD").to_dict(orient="records")
    )
    if not df_delisted.empty:
        delisted_records = (
            df_delisted.fillna("").astype(str).sort_values(df_delisted.columns[0]).to_dict(orient="records")
        )
    else:
        delisted_records = []
    return {
        "source_observation_date": SOURCE_OBSERVATION_DATE,
        "equity": equity_records,
        "etf_tickers": sorted(etf_tickers),
        "etn_tickers": sorted(etn_tickers),
        "delisted": delisted_records,
    }


def build(dry_run: bool) -> None:
    print("=" * 80)
    print("KRX Instrument Metadata Canonical Build (Fix Round 06)")
    print("=" * 80)
    print(f"Source observation date (실행 시각 KST 달력 날짜, backdate 불가): {SOURCE_OBSERVATION_DATE}")

    df_equity, etf_tickers, etn_tickers, df_delisted = fetch_live_formal_universe()
    print(f"Live formal universe: equity(KOSPI+KOSDAQ+KONEX)={len(df_equity)}, "
          f"ETF={len(etf_tickers)}, ETN={len(etn_tickers)}, delisted_reference={len(df_delisted)}")

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str})
    if "source_security_type" not in df.columns:
        df["source_security_type"] = ""

    # Fix Round 06 Critical 1: 이번 실행에서 새로 검증하는 row는 오직
    # SOURCE_OBSERVATION_DATE 하나뿐이다. 재실행(같은 날 재빌드) 시 중복 append를
    # 막기 위해 기존 SOURCE_OBSERVATION_DATE row(있다면)는 먼저 제거한다(idempotent upsert).
    already_present = df["effective_date"] == SOURCE_OBSERVATION_DATE
    if already_present.any():
        print(f"기존 {SOURCE_OBSERVATION_DATE} row {already_present.sum()}건 발견 — 재검증을 위해 교체합니다.")
        df = df[~already_present].reset_index(drop=True)

    remaining_dates = df["effective_date"].dropna().astype(str)
    if remaining_dates.empty:
        raise RuntimeError("baseline snapshot이 없어 재검증할 ticker 목록을 결정할 수 없습니다.")
    baseline_date = remaining_dates.max()
    if baseline_date >= SOURCE_OBSERVATION_DATE:
        raise RuntimeError(
            f"baseline_date({baseline_date})가 SOURCE_OBSERVATION_DATE({SOURCE_OBSERVATION_DATE})보다 "
            "과거가 아닙니다 — PIT backdating 방지를 위해 중단합니다."
        )
    baseline_rows = df[df["effective_date"] == baseline_date].copy()
    print(f"Baseline ticker universe for re-verification: effective_date={baseline_date} ({len(baseline_rows)} tickers)")

    # 과거의 모든 기존 row(이전 실행에서 잘못 FORMAL_SECURITY_TYPE으로 표시된
    # baseline_date row 포함)는 이번 실행에서 재검증되지 않았으므로 LEGACY_UNVERIFIED로
    # 낮춘다. 값(asset_type 등)은 그대로 두고(과거 값을 오늘자 조회로 소급 덮어쓰지 않음)
    # provenance만 낮춘다.
    df["classification_authority"] = AUTH_LEGACY_UNVERIFIED
    df["asset_type_source"] = AUTH_LEGACY_UNVERIFIED

    verified_count = 0
    changed_tickers: list[dict] = []
    asset_type_dist: dict[str, int] = {}
    not_found_tickers: list[str] = []
    unmapped_tickers: list[str] = []

    new_rows: list[dict] = []
    for _, base_row in baseline_rows.iterrows():
        ticker = base_row["ticker"]
        old_asset_type = base_row["asset_type"]
        asset_type, source_security_type, auth, asset_source = classify_ticker(
            ticker, df_equity, etf_tickers, etn_tickers
        )

        new_rows.append({
            "ticker": ticker,
            "name": base_row["name"],
            "market": base_row["market"],
            "asset_type": asset_type,
            "is_common_stock": asset_type == "COMMON",
            "metadata_source": METADATA_SOURCE_VERIFIED,
            "effective_date": SOURCE_OBSERVATION_DATE,
            "classification_authority": auth,
            "asset_type_source": asset_source,
            "source_security_type": source_security_type,
        })

        verified_count += 1
        asset_type_dist[asset_type] = asset_type_dist.get(asset_type, 0) + 1
        if auth == AUTH_UNKNOWN:
            not_found_tickers.append(ticker)
        if asset_source == AUTH_UNMAPPED:
            unmapped_tickers.append(ticker)
        if old_asset_type != asset_type:
            changed_tickers.append({"ticker": ticker, "name": base_row["name"],
                                     "old_asset_type": old_asset_type, "new_asset_type": asset_type})

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    historical_row_count = int((df["effective_date"] != SOURCE_OBSERVATION_DATE).sum())

    print(f"\nVerified rows (effective_date={SOURCE_OBSERVATION_DATE}): {verified_count}")
    print(f"Asset type distribution (verified rows): {asset_type_dist}")
    print(f"Formal source found but ticker not found (UNKNOWN, category D): {len(not_found_tickers)}")
    print(f"Formal source found, mapping unmapped (UNMAPPED_FORMAL_CATEGORY): {len(unmapped_tickers)}")
    print(f"asset_type CHANGED vs baseline({baseline_date}) committed value: {len(changed_tickers)}")
    for c in changed_tickers:
        print(f"  {c['ticker']} {c['name']}: {c['old_asset_type']} -> {c['new_asset_type']}")
    print(f"Historical/legacy rows (all effective_date != {SOURCE_OBSERVATION_DATE}, downgraded to LEGACY_UNVERIFIED): {historical_row_count}")

    source_snapshot = build_canonical_source_snapshot(df_equity, etf_tickers, etn_tickers, df_delisted)
    source_snapshot_sha256 = hashlib.sha256(_canonical_json_bytes(source_snapshot)).hexdigest()

    if dry_run:
        print("\n--dry-run: no files written.")
        return

    df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"\nWrote {CSV_PATH} and {PARQUET_PATH} ({len(df)} rows).")

    SOURCE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    source_snapshot_path = SOURCE_SNAPSHOT_DIR / f"krx_instrument_metadata_source_snapshot_{SOURCE_OBSERVATION_DATE}.json"
    # 저장하는 bytes는 반드시 checksum을 계산한 canonical bytes와 완전히 동일해야 한다
    # (pretty-print로 다시 직렬화하면 checksum이 파일 내용과 어긋난다).
    source_snapshot_path.write_bytes(_canonical_json_bytes(source_snapshot))
    print(f"Wrote {source_snapshot_path}.")

    artifact_csv_sha256 = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    artifact_parquet_sha256 = hashlib.sha256(PARQUET_PATH.read_bytes()).hexdigest()

    manifest = {
        "artifact_version": "3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "effective_date": SOURCE_OBSERVATION_DATE,
        "upstream_authority": "KRX Market Data Center (data.krx.co.kr), authenticated session",
        "upstream_source_name": "전종목기본정보 (bld=dbms/MDC/STAT/standard/MDCSTAT01901); "
                                 "pykrx get_etf_ticker_list / get_etn_ticker_list; "
                                 "상폐종목검색 (delisted reference only)",
        "upstream_source_location": "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        "retrieval_method": "authenticated HTTPS POST (KRX_ID/KRX_PW via .env), build-time only, "
                             "not used at Stock Report runtime",
        "source_snapshot_date": SOURCE_OBSERVATION_DATE,
        "source_snapshot_path": str(source_snapshot_path.relative_to(REPO_ROOT)),
        "source_snapshot_sha256": source_snapshot_sha256,
        "artifact_csv_sha256": artifact_csv_sha256,
        "artifact_parquet_sha256": artifact_parquet_sha256,
        "builder_script": BUILDER_SCRIPT,
        "mapping_version": MAPPING_VERSION,
        "row_count": len(df),
        "ticker_count": df["ticker"].nunique(),
        "verified_snapshot_effective_date": SOURCE_OBSERVATION_DATE,
        "verified_snapshot_baseline_date": baseline_date,
        "verified_row_count": verified_count,
        "asset_type_distribution_verified_rows": asset_type_dist,
        "unknown_count_verified_rows": len(not_found_tickers),
        "unmapped_formal_category_count_verified_rows": len(unmapped_tickers),
        "changed_tickers_vs_baseline_committed_value": changed_tickers,
        "historical_rows_marked_legacy_unverified": historical_row_count,
        "zero_network_runtime": True,
        "backdating_prevention": "SOURCE_OBSERVATION_DATE는 pd.Timestamp.now(tz='Asia/Seoul')에서만 파생되며 "
                                  "CLI로 다른 값을 주입할 방법이 없다 (Fix Round 06 Critical 1). "
                                  "새로 검증된 row의 effective_date는 항상 이 값과 동일하다.",
        "pit_history_rewrite": "NOT_PERFORMED — 과거 effective_date row는 asset_type 값을 그대로 두되 "
                                "classification_authority/asset_type_source만 LEGACY_UNVERIFIED로 낮춘다. "
                                f"이전 실행에서 {baseline_date}에 잘못 FORMAL_SECURITY_TYPE으로 표시되었던 "
                                "row도 이번 실행에서 동일하게 LEGACY_UNVERIFIED로 재정정된다.",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX Instrument Metadata Canonical Build v2")
    parser.add_argument("--dry-run", action="store_true", help="계획만 출력하고 파일을 쓰지 않음")
    args = parser.parse_args()

    build(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
