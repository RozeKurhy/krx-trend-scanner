#!/usr/bin/env python3
"""KRX Instrument Metadata Canonical Build (Fix Round 05, Major 1).

data/reference/krx_instrument_metadata.{csv,parquet}의 asset_type 분류를
실제 verified upstream KRX formal source에 연결한다.

Upstream authority (실제 확인됨, build-time에만 network 접근 — Stock Report
runtime은 이 artifact를 읽기만 하며 ZERO_NETWORK_RUNTIME=YES 유지):

  1. 전종목기본정보 (KRX MDC, bld=dbms/MDC/STAT/standard/MDCSTAT01901)
     mktId=ALL(KOSPI+KOSDAQ), mktId=KNX(코넥스) 각각 조회.
     인증 세션(KRX_ID/KRX_PW, .env) 필요 — 익명 요청은 이 bld에서 "LOGOUT"으로 거부됨.
     필드: SECUGRP_NM(증권그룹명), SECT_TP_NM(소속부명, SPAC은 여기 "SPAC(소속부없음)"로
     명시됨), KIND_STKCERT_TP_NM(주권종류구분명: 보통주/구형우선주/신형우선주/종류주권).
  2. pykrx get_etf_ticker_list / get_etn_ticker_list (동일 인증 세션 필요).
  3. 상폐종목검색 (delisted finder) — manifest 기록 및 경계 확인용(현재 상장이 아닌
     티커의 존재 자체를 확인하는 데만 사용, security type 필드는 제공하지 않음).

PIT 범위 제한 (w.md Fix Round 05 §2.13 — history rewrite 금지):
  이 스크립트가 verify할 수 있는 것은 "오늘"(스크립트 실행 시점의 실제 KRX 상장
  상태) 하나의 snapshot뿐이다. 이 project의 canonical metadata는 여러 과거
  effective_date PIT snapshot을 담고 있으므로, 이 스크립트는 effective_date ==
  --as-of-date(기본 2026-08-14, 이 project의 "현재" 기준일)인 row만 갱신하고,
  그보다 과거의 모든 historical row는 값(asset_type 등)을 그대로 두되
  classification_authority/asset_type_source를 "LEGACY_UNVERIFIED"로 낮춘다
  (과거 값을 오늘자 조회 결과로 소급 덮어쓰지 않는다).

Usage:
    uv run python scripts/build_krx_instrument_metadata.py [--dry-run] [--as-of-date 2026-08-14]
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

METADATA_SOURCE_VERIFIED = "KRX_MDC_VERIFIED_LIVE"
METADATA_SOURCE_LEGACY = "KRX_LOCAL_FROZEN_MASTER"
AUTH_FORMAL = "FORMAL_SECURITY_TYPE"
AUTH_UNMAPPED = "UNMAPPED_FORMAL_CATEGORY"
AUTH_LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
AUTH_UNKNOWN = "UNKNOWN"

BUILDER_SCRIPT = "scripts/build_krx_instrument_metadata.py"
MAPPING_VERSION = "v1"


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

    Deterministic mapping (실제 확인된 KRX taxonomy 기준):
      SECT_TP_NM에 "SPAC" 포함                    -> SPAC
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
    source_security_type = f"SECUGRP_NM={secugrp}|SECT_TP_NM={sect}|KIND_STKCERT_TP_NM={kind}"

    if "SPAC" in sect:
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


def build(as_of_date: str, dry_run: bool) -> None:
    print("=" * 80)
    print("KRX Instrument Metadata Canonical Build (Fix Round 05)")
    print("=" * 80)
    print(f"Verified snapshot date (this project's canonical as-of): {as_of_date}")

    df_equity, etf_tickers, etn_tickers, df_delisted = fetch_live_formal_universe()
    print(f"Live formal universe: equity(KOSPI+KOSDAQ+KONEX)={len(df_equity)}, "
          f"ETF={len(etf_tickers)}, ETN={len(etn_tickers)}, delisted_reference={len(df_delisted)}")

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str})
    if "source_security_type" not in df.columns:
        df["source_security_type"] = ""

    is_current = df["effective_date"] == as_of_date
    print(f"Rows at {as_of_date} (verified this run): {is_current.sum()}")
    print(f"Historical rows (untouched values, downgraded to LEGACY_UNVERIFIED): {(~is_current).sum()}")

    verified_count = 0
    changed_tickers: list[dict] = []
    asset_type_dist: dict[str, int] = {}
    not_found_tickers: list[str] = []
    unmapped_tickers: list[str] = []

    for idx in df.index[is_current]:
        ticker = df.at[idx, "ticker"]
        old_asset_type = df.at[idx, "asset_type"]
        asset_type, source_security_type, auth, asset_source = classify_ticker(
            ticker, df_equity, etf_tickers, etn_tickers
        )

        df.at[idx, "asset_type"] = asset_type
        df.at[idx, "is_common_stock"] = asset_type == "COMMON"
        df.at[idx, "source_security_type"] = source_security_type
        df.at[idx, "metadata_source"] = METADATA_SOURCE_VERIFIED
        df.at[idx, "classification_authority"] = auth
        df.at[idx, "asset_type_source"] = asset_source

        verified_count += 1
        asset_type_dist[asset_type] = asset_type_dist.get(asset_type, 0) + 1
        if auth == AUTH_UNKNOWN:
            not_found_tickers.append(ticker)
        if asset_source == AUTH_UNMAPPED:
            unmapped_tickers.append(ticker)
        if old_asset_type != asset_type:
            changed_tickers.append({"ticker": ticker, "name": df.at[idx, "name"],
                                     "old_asset_type": old_asset_type, "new_asset_type": asset_type})

    df.loc[~is_current, "classification_authority"] = AUTH_LEGACY_UNVERIFIED
    df.loc[~is_current, "asset_type_source"] = AUTH_LEGACY_UNVERIFIED

    print(f"\nVerified rows: {verified_count}")
    print(f"Asset type distribution (verified rows): {asset_type_dist}")
    print(f"Formal source found but ticker not found (UNKNOWN, category D): {len(not_found_tickers)}")
    print(f"Formal source found, mapping unmapped (UNMAPPED_FORMAL_CATEGORY): {len(unmapped_tickers)}")
    print(f"asset_type CHANGED vs prior committed value: {len(changed_tickers)}")
    for c in changed_tickers:
        print(f"  {c['ticker']} {c['name']}: {c['old_asset_type']} -> {c['new_asset_type']}")

    if dry_run:
        print("\n--dry-run: no files written.")
        return

    df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"\nWrote {CSV_PATH} and {PARQUET_PATH} ({len(df)} rows).")

    csv_bytes = CSV_PATH.read_bytes()
    checksum = hashlib.sha256(csv_bytes).hexdigest()

    manifest = {
        "artifact_version": "2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "effective_date": as_of_date,
        "upstream_authority": "KRX Market Data Center (data.krx.co.kr), authenticated session",
        "upstream_source_name": "전종목기본정보 (bld=dbms/MDC/STAT/standard/MDCSTAT01901); "
                                 "pykrx get_etf_ticker_list / get_etn_ticker_list; "
                                 "상폐종목검색 (delisted reference only)",
        "upstream_source_location": "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        "retrieval_method": "authenticated HTTPS POST (KRX_ID/KRX_PW via .env), build-time only, "
                             "not used at Stock Report runtime",
        "source_snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source_checksum_sha256": checksum,
        "builder_script": BUILDER_SCRIPT,
        "mapping_version": MAPPING_VERSION,
        "row_count": len(df),
        "ticker_count": df["ticker"].nunique(),
        "verified_snapshot_effective_date": as_of_date,
        "verified_row_count": verified_count,
        "asset_type_distribution_verified_rows": asset_type_dist,
        "unknown_count_verified_rows": len(not_found_tickers),
        "unmapped_formal_category_count_verified_rows": len(unmapped_tickers),
        "changed_tickers_vs_prior_committed_value": changed_tickers,
        "historical_rows_marked_legacy_unverified": int((~is_current).sum()),
        "zero_network_runtime": True,
        "pit_history_rewrite": "NOT_PERFORMED — historical effective_date rows keep their prior asset_type "
                                "value unchanged; only classification_authority/asset_type_source were "
                                "downgraded to LEGACY_UNVERIFIED because their formal provenance cannot be "
                                "re-verified from a live snapshot taken at build time.",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX Instrument Metadata Canonical Build v1")
    parser.add_argument("--dry-run", action="store_true", help="계획만 출력하고 파일을 쓰지 않음")
    parser.add_argument("--as-of-date", type=str, default="2026-08-14",
                         help="검증 대상 effective_date (이 project의 canonical 현재 기준일)")
    args = parser.parse_args()

    build(as_of_date=args.as_of_date, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
