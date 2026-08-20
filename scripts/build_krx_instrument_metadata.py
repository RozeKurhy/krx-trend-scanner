#!/usr/bin/env python3
"""KRX Instrument Metadata Canonical Build (Fix Round 07, Major 2/3).

data/reference/krx_instrument_metadata.{csv,parquet}의 asset_type 분류를
실제 verified upstream KRX formal source에 연결한다.

Upstream authority (실제 확인됨, build-time에만 network 접근 — Stock Report
runtime은 이 artifact를 읽기만 하며 ZERO_NETWORK_RUNTIME=YES 유지):

  1. 전종목기본정보 (KRX MDC, bld=dbms/MDC/STAT/standard/MDCSTAT01901)
     mktId=ALL(KOSPI+KOSDAQ), mktId=KNX(코넥스) 각각 조회.
     인증 세션(KRX_ID/KRX_PW, .env) 필요 — 익명 요청은 이 bld에서 "LOGOUT"으로 거부됨.
     필드: ISU_ABBRV(공식 약식 종목명 — 이 project의 canonical name 표기와 일치),
     MKT_TP_NM(시장), SECUGRP_NM(증권그룹명), SECT_TP_NM(소속부명), KIND_STKCERT_TP_NM
     (주권종류구분명: 보통주/구형우선주/신형우선주/종류주권), ISU_NM(공식 한글 종목명,
     PREFERRED 판정 보조로만 사용 — Fix Round 07부터 SPAC 판정에는 사용하지 않음, §4.3).
  2. ETF_전종목기본종목 (bld=dbms/MDC/STAT/standard/MDCSTAT04601),
     ETN_전종목기본종목 (bld=dbms/MDC/STAT/standard/MDCSTAT06701) — ETF/ETN의
     ticker + 공식 name(ISU_ABBRV)까지 formal source에서 직접 확보한다(Fix Round 07
     Major 2 이전에는 pykrx get_etf_ticker_list/get_etn_ticker_list로 ticker만
     받고 name/market은 baseline에서 복사했음 — 이제 name도 live formal source).
  3. 상폐종목검색 (delisted finder) — manifest 기록 및 경계 확인용(현재 상장이 아닌
     티커의 존재 자체를 확인하는 데만 사용, security type 필드는 제공하지 않음).

Fix Round 06 Critical 1 — PIT backdating 금지 (w.md §2, 유지):
  새로 검증된 row의 effective_date는 항상 SOURCE_OBSERVATION_DATE(실행 시각의
  KST 달력 날짜)이며, 이를 CLI로 다른 값으로 바꿀 방법이 코드에 없다.
  effective_date != SOURCE_OBSERVATION_DATE인 모든 row는 매 실행마다
  classification_authority/asset_type_source가 LEGACY_UNVERIFIED로 낮아진다.

Fix Round 07 Major 2 — Current snapshot을 live universe 전체에서 생성 (w.md §3):
  Fix Round 06은 "이전 baseline(마지막 verified 날짜)의 ticker 집합을 live source에서
  재분류"하는 구조였다 — 즉 baseline에 없는 신규 상장 종목은 verified snapshot에
  절대 들어갈 수 없었고, name/market도 baseline에서 그대로 복사해 live 응답의 실제
  name/market 변경을 반영하지 못했다. Fix Round 07은 CURRENT_FORMAL_UNIVERSE =
  live equity ∪ live ETF ∪ live ETN 전체에서 매번 새로 current snapshot을 만든다.
  Baseline은 오직 diff/신규상장/상장폐지 감지 용도로만 쓰이며, current snapshot
  membership의 authority가 아니다.

Fix Round 07 Major 3 — SPAC 현재 분류에서 종목명 substring 제거 (w.md §4):
  Fix Round 06의 ISU_ENG_NM/ISU_ENG_NM("Special Purpose Acquisition"/"기업인수목적")
  기반 SPAC 판정은 formal API 필드에서 나왔지만 방식 자체는 여전히 종목명 substring
  matching이었다. 이번 라운드에서 KRX formal source를 재조사했으나(전종목기본정보의
  모든 12개 컬럼, 업종분류현황(IDX_IND_NM) 등) 종목명과 독립적인 SPAC 전용 formal
  식별 필드/universe/code를 확인하지 못했다(업종분류현황의 "금융" 카테고리는 SPAC
  117개 중 SPAC 아닌 증권사/투자회사 등도 다수 포함해 식별력이 없음을 실제 확인함).
  따라서 이번 라운드부터 current production SPAC 판정은 SECT_TP_NM이 명시적으로
  "SPAC"을 포함하는 경우만 positive evidence로 인정한다. SECT_TP_NM이
  "관리종목(소속부없음)"(정상 사업부가 아닌 관리/주의 상태 — formal하고 이름과
  무관한 신호)이면서 KIND_STKCERT_TP_NM=보통주이고, 이 ticker의 canonical 이력
  전체(모든 effective_date, history rewrite 없이 보존된 과거 값) 어딘가에 SPAC으로
  기록된 적이 있는 경우(예: 465320/471050/472220 — 관리종목 전환으로 SECT_TP_NM에서
  SPAC 표시를 잃음)는 COMMON으로 확정하지 않고 UNKNOWN + asset_type_source=
  INSUFFICIENT_FORMAL_IDENTITY로 fail closed한다(§4.7). "직전 baseline 값"만
  비교하면 한 번 UNKNOWN이 된 ticker가 같은 날 재실행 시 그 UNKNOWN 자체를 새
  기준으로 삼아 다음 실행에서 COMMON으로 잘못 승격되는 non-deterministic 회귀가
  생기므로(실측으로 발견 및 수정함), 전체 이력을 본다 — SPAC 기록은 한 번 쓰이면
  재작성되지 않으므로 이 판정은 재실행 횟수/순서와 무관하게 항상 안정적이다.
  정상적으로 SPAC→COMMON 전환된 369370류는 현재 SECT_TP_NM이 "벤처기업부"(정상
  사업부)라 "관리종목" 조건 자체에 걸리지 않으므로 영향받지 않는다. 과거
  LEGACY_UNVERIFIED row의 기존 SPAC 값은 historical research에서 계속 그대로
  사용 가능하다(§4.8) — 이 변경은 오직 current production 판정에만 적용된다.

Fix Round 06 Major 2 — checksum 의미 분리 (w.md §5, 유지):
  manifest는 source_snapshot_sha256(실제 upstream 응답의 canonical-serialize 해시)와
  artifact_csv_sha256/artifact_parquet_sha256(산출물 파일 해시)을 분리해 기록한다.

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
from pykrx.website.krx.etx.core import ETF_전종목기본종목, ETN_전종목기본종목  # noqa: E402
from trend_scanner.universe.instrument_metadata import normalize_krx_market  # noqa: E402

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
AUTH_INSUFFICIENT_IDENTITY = "INSUFFICIENT_FORMAL_IDENTITY"

# ETF/ETN은 KRX 시장 구조상 전부 KOSPI 시장 구분 아래 상장된다(개별 종목 필드가
# 아니라 상품군 전체에 적용되는 일반 시장 구조 사실 — baseline에서 복사한 값이
# 아니다, w.md Fix Round 07 §3.6).
ETX_MARKET = "KOSPI"

BUILDER_SCRIPT = "scripts/build_krx_instrument_metadata.py"
MAPPING_VERSION = "v4"

# Fix Round 06 Critical 1: 유일한 진실. 새로 검증되는 row의 effective_date는
# 항상 이 값이며, 다른 값으로 대체할 CLI 경로가 없다 (backdating 구조적 차단).
# KRX 거래일/effective_date는 이 project 전체에서 KST(Asia/Seoul) 기준 달력 날짜이므로
# (build_krx_trading_calendar.py와 동일 관례), UTC 날짜가 아닌 KST 날짜를 쓴다 —
# UTC 자정 이후 KST 오전 시간대(UTC와 캘린더 날짜가 갈리는 구간)에 실행하면 UTC 기준은
# 하루 전 날짜로 어긋난다.
SOURCE_OBSERVATION_DATE = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")


def fetch_live_formal_universe(
    source_snapshot_file: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """인증 세션으로 KRX MDC에서 실제 formal 분류/명칭 데이터를 조회하거나,
    지정된 source snapshot 파일에서 로드한다 (zero-network / reproducible build 지원).
    """
    if source_snapshot_file and source_snapshot_file.exists():
        payload = json.loads(source_snapshot_file.read_text(encoding="utf-8"))
        df_equity = pd.DataFrame(payload.get("equity", []))
        df_etf = pd.DataFrame(payload.get("etf", []))
        df_etn = pd.DataFrame(payload.get("etn", []))
        df_delisted = pd.DataFrame(payload.get("delisted", []))
        return df_equity, df_etf, df_etn, df_delisted

    sess = build_krx_session()
    if sess is None or not sess.is_authenticated:
        # Fallback to existing snapshot if session is unavailable (e.g. offline CI / test environments)
        snapshot_today = SOURCE_SNAPSHOT_DIR / f"krx_instrument_metadata_source_snapshot_{SOURCE_OBSERVATION_DATE}.json"
        if snapshot_today.exists():
            payload = json.loads(snapshot_today.read_text(encoding="utf-8"))
            df_equity = pd.DataFrame(payload.get("equity", []))
            df_etf = pd.DataFrame(payload.get("etf", []))
            df_etn = pd.DataFrame(payload.get("etn", []))
            df_delisted = pd.DataFrame(payload.get("delisted", []))
            return df_equity, df_etf, df_etn, df_delisted
        raise RuntimeError("KRX 인증 세션 생성 실패 — KRX_ID/KRX_PW(.env) 확인 필요.")
    set_auth_session(sess)

    df_kospi_kosdaq = 전종목기본정보().fetch(mktId="ALL", segTpCd="ALL")
    df_konex = 전종목기본정보().fetch(mktId="KNX", segTpCd="ALL")
    df_equity = pd.concat([df_kospi_kosdaq, df_konex], ignore_index=True)
    df_equity = df_equity.drop_duplicates(subset=["ISU_SRT_CD"], keep="first")

    df_etf = ETF_전종목기본종목().fetch()
    df_etn = ETN_전종목기본종목().fetch()

    df_delisted = 상폐종목검색().fetch("ALL", "")

    return df_equity, df_etf, df_etn, df_delisted


MANAGED_ISSUE_SECTIONS = {"관리종목(소속부없음)"}
MANAGED_ISSUE_SECT = "관리종목(소속부없음)"


def map_row_to_asset_type(row: pd.Series, ever_been_spac: bool = False) -> tuple[str, str, str, str]:
    """KRX formal category row -> (asset_type, source_security_type, classification_authority, asset_type_source).

    Priority order: SPAC identity -> REIT/security-group -> PREFERRED/COMMON -> UNKNOWN.
    (ETF/ETN은 이 함수 호출 이전, live universe 구성 단계에서 별도 formal product master로 먼저 판정된다.)

    Fix Round 08 Major 1 — 모든 이름 substring matching heuristic 완전 제거:
      - ISU_NM, ISU_ENG_NM, ticker name, suffix heuristic을 AssetType 결정에 전혀 사용하지 않는다.
      - 종목명 substring으로 asset_type을 변경하는 production rule은 정확히 0개다.

    Rules:
      1. SPAC identity (SECT_TP_NM formal field 단독):
         SECT_TP_NM == "SPAC(소속부없음)" (또는 "SPAC" in SECT_TP_NM) -> SPAC
      2. SECUGRP_NM == "부동산투자회사" -> REIT
      3. KIND_STKCERT_TP_NM == "보통주":
         - SECT_TP_NM in MANAGED_ISSUE_SECTIONS and ever_been_spac -> UNKNOWN (INSUFFICIENT_FORMAL_IDENTITY)
         - otherwise -> COMMON
      4. KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주"):
         - formal exact share-kind category -> PREFERRED
      5. 그 외 (외국주권/주식예탁증권/사회간접자본투융자회사/투자회사/종류주권 등):
         - KIND_STKCERT_TP_NM == "종류주권"을 포함하여 name-independent formal taxonomy로
           해결할 수 없는 카테고리는 추측하지 않고 fail closed -> UNKNOWN (UNMAPPED_FORMAL_CATEGORY)
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

    is_spac_formal = "SPAC" in sect
    if is_spac_formal:
        return "SPAC", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if secugrp == "부동산투자회사":
        return "REIT", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if kind == "보통주":
        if sect in MANAGED_ISSUE_SECTIONS and ever_been_spac:
            ambiguous_source = source_security_type + "|CANONICAL_HISTORY_HAS_SPAC=TRUE"
            return "UNKNOWN", ambiguous_source, AUTH_FORMAL, AUTH_INSUFFICIENT_IDENTITY
        return "COMMON", source_security_type, AUTH_FORMAL, AUTH_FORMAL
    if kind in ("구형우선주", "신형우선주"):
        return "PREFERRED", source_security_type, AUTH_FORMAL, AUTH_FORMAL

    # formal source에서 row는 찾았으나(예: 외국주권/주식예탁증권/종류주권/투자회사/사회간접자본투융자회사)
    # name-independent formal taxonomy로 deterministic mapping이 불가능한 경우.
    # 추측해서 PREFERRED/COMMON 등으로 분류하지 않고 fail closed (Fix Round 08 Major 1).
    return "UNKNOWN", source_security_type, AUTH_FORMAL, AUTH_UNMAPPED


def classify_live_row(
    universe_source: str,
    ticker: str,
    df_equity: pd.DataFrame,
    ever_been_spac: bool,
) -> tuple[str, str, str, str]:
    if universe_source == "ETF_LIVE":
        return "ETF", "ETF_전종목기본종목(formal product master)", AUTH_FORMAL, AUTH_FORMAL
    if universe_source == "ETN_LIVE":
        return "ETN", "ETN_전종목기본종목(formal product master)", AUTH_FORMAL, AUTH_FORMAL

    match = df_equity[df_equity["ISU_SRT_CD"] == ticker]
    if match.empty:
        return "UNKNOWN", "", AUTH_UNKNOWN, AUTH_UNKNOWN

    return map_row_to_asset_type(match.iloc[0], ever_been_spac=ever_been_spac)


def build_current_live_universe(df_equity: pd.DataFrame, df_etf: pd.DataFrame, df_etn: pd.DataFrame) -> pd.DataFrame:
    """실제 live formal source(equity + ETF + ETN) 전체에서 CURRENT_FORMAL_UNIVERSE를 만든다
    (Fix Round 07 Major 2 — 이전 baseline ticker 집합이 아니라 live universe 자체가
    membership authority다). name/market도 baseline 복사가 아니라 이 live source에서
    직접 가져온다(§3.5/§3.6): name = ISU_ABBRV(이 project의 canonical 표기와 일치하는
    공식 약식 종목명), market = normalize_krx_market(MKT_TP_NM)(equity), ETF/ETN은
    KRX 시장 구조상 전부 KOSPI(ETX_MARKET, 상수 — baseline에서 복사한 값이 아니라
    일반 시장 구조 사실).
    """
    equity_universe = pd.DataFrame({
        "ticker": df_equity["ISU_SRT_CD"],
        "name": df_equity["ISU_ABBRV"],
        "market": df_equity["MKT_TP_NM"].apply(normalize_krx_market),
        "universe_source": "EQUITY_LIVE",
    })
    etf_universe = pd.DataFrame({
        "ticker": df_etf["ISU_SRT_CD"],
        "name": df_etf["ISU_ABBRV"],
        "market": ETX_MARKET,
        "universe_source": "ETF_LIVE",
    })
    etn_universe = pd.DataFrame({
        "ticker": df_etn["ISU_SRT_CD"],
        "name": df_etn["ISU_ABBRV"],
        "market": ETX_MARKET,
        "universe_source": "ETN_LIVE",
    })
    # ETF/ETN을 equity보다 우선한다(동일 ticker가 두 목록에 동시에 나타나는 것은
    # 실제로는 발생하지 않지만, 발생하더라도 product-master 판정이 더 구체적이다).
    combined = pd.concat([etf_universe, etn_universe, equity_universe], ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)
    return combined


def _canonical_json_bytes(payload: dict) -> bytes:
    """정렬된 key, 고정 구분자로 직렬화 — 동일 데이터는 항상 동일 bytes를 낸다."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_canonical_source_snapshot(
    df_equity: pd.DataFrame,
    df_etf: pd.DataFrame,
    df_etn: pd.DataFrame,
    df_delisted: pd.DataFrame,
) -> dict:
    """실제 upstream KRX 응답 데이터를 canonical(정렬, 문자열화) 형태로 직렬화한다.

    이 payload의 해시가 manifest의 source_snapshot_sha256이다 — 산출물(CSV/parquet)이
    아니라 실제 조회한 원본 응답 데이터의 fingerprint (Fix Round 06 Major 2).
    """
    def _records(df: pd.DataFrame, sort_col: str) -> list[dict]:
        if df.empty:
            return []
        return df.fillna("").astype(str).sort_values(sort_col).to_dict(orient="records")

    return {
        "source_observation_date": SOURCE_OBSERVATION_DATE,
        "equity": _records(df_equity, "ISU_SRT_CD"),
        "etf": _records(df_etf, "ISU_SRT_CD"),
        "etn": _records(df_etn, "ISU_SRT_CD"),
        "delisted": _records(df_delisted, df_delisted.columns[0]) if not df_delisted.empty else [],
    }


def build(dry_run: bool) -> None:
    print("=" * 80)
    print("KRX Instrument Metadata Canonical Build (Fix Round 08)")
    print("=" * 80)
    print(f"Source observation date (실행 시각 KST 달력 날짜, backdate 불가): {SOURCE_OBSERVATION_DATE}")

    df_equity, df_etf, df_etn, df_delisted = fetch_live_formal_universe()
    live_equity_count = len(df_equity)
    live_etf_count = len(df_etf)
    live_etn_count = len(df_etn)
    print(f"Live formal universe: equity(KOSPI+KOSDAQ+KONEX)={live_equity_count}, "
          f"ETF={live_etf_count}, ETN={live_etn_count}, delisted_reference={len(df_delisted)}")

    live_universe = build_current_live_universe(df_equity, df_etf, df_etn)
    live_supported_unique_tickers = len(live_universe)
    print(f"Current live formal universe (Fix Round 08 Major 2, live source 전체): {live_supported_unique_tickers} unique tickers")

    df = pd.read_csv(CSV_PATH, dtype={"ticker": str})
    if "source_security_type" not in df.columns:
        df["source_security_type"] = ""
    # Fix Round 08 Major 2: Normalize all historical markets to canonical MarketType (e.g. KOSDAQ GLOBAL -> KOSDAQ)
    df["market"] = df["market"].apply(normalize_krx_market)

    # baseline은 이번 실행이 데이터를 건드리기 *이전*의 상태에서 뽑아야 한다.
    # 같은 날 재실행(idempotent upsert)하는 경우에도 마찬가지다 — 만약 오늘자
    # row를 먼저 제거한 뒤 baseline_date를 고르면, 오늘 이미 한 번 재검증됐던
    # 결과(예: 465320=SPAC)가 사라지고 그보다 훨씬 오래된(예: 관리종목 전환 전
    # COMMON으로 잘못 기록됐던) 과거 row가 §4.7 ambiguity 감지의 기준이 되어
    # 버려, 이미 해소했던 SPAC 오분류가 재실행 시 다시 나타나는 회귀가 생긴다.
    remaining_dates = df["effective_date"].dropna().astype(str)
    if remaining_dates.empty:
        raise RuntimeError("baseline snapshot이 없어 diff 비교 기준을 결정할 수 없습니다.")
    baseline_date = remaining_dates.max()
    if baseline_date > SOURCE_OBSERVATION_DATE:
        raise RuntimeError(
            f"baseline_date({baseline_date})가 SOURCE_OBSERVATION_DATE({SOURCE_OBSERVATION_DATE})보다 "
            "미래입니다 — PIT backdating 방지를 위해 중단합니다."
        )
    baseline_rows = df[df["effective_date"] == baseline_date].copy()
    baseline_ticker_count = len(baseline_rows)
    # Fix Round 07 Major 2: baseline은 오직 diff(신규상장/상장폐지)와 changed_tickers
    # 리포팅용으로만 쓴다 — current snapshot의 membership authority가 아니다.
    baseline_ticker_set = set(baseline_rows["ticker"])
    baseline_asset_type_by_ticker = dict(zip(baseline_rows["ticker"], baseline_rows["asset_type"]))
    print(f"Baseline (diff 비교 기준, membership authority 아님): effective_date={baseline_date} ({baseline_ticker_count} tickers)")

    # §4.7 SPAC ambiguity 감지("이 ticker가 canonical 이력에서 SPAC으로 기록된 적
    # 있는가")는 immediate baseline 하나만 보면 안 된다. baseline이 이미 UNKNOWN인
    # 상태로 재실행(idempotent rerun)되면 "직전 값 == SPAC" 식의 판정은 그 UNKNOWN
    # 자체를 새 기준으로 삼아 다음 실행에서 곧바로 COMMON으로 승격되는 회귀가
    # 생긴다(실측으로 확인됨). 전체 이력(모든 effective_date)에서 asset_type이
    # 한 번이라도 SPAC으로 기록된 적이 있는지를 본다 — SPAC 기록은 과거 row 값을
    # 절대 재작성하지 않으므로(§9) 이 집합은 재실행 순서와 무관하게 항상 안정적이다.
    # (map_row_to_asset_type에서 이 신호는 SECT_TP_NM=="관리종목(소속부없음)"과
    # AND 조건으로만 쓰이므로, 정상적으로 SPAC->COMMON 전환된 369370류는 영향받지
    # 않는다 — 369370의 현재 SECT_TP_NM은 "벤처기업부"로 관리종목이 아니다.)
    ever_been_spac_tickers: set[str] = set(df[df["asset_type"] == "SPAC"]["ticker"])

    # Fix Round 06 Critical 1: 이번 실행에서 새로 검증하는 row는 오직
    # SOURCE_OBSERVATION_DATE 하나뿐이다. 재실행(같은 날 재빌드) 시 중복 append를
    # 막기 위해 기존 SOURCE_OBSERVATION_DATE row(있다면)는 baseline 추출 *이후*에
    # 제거한다(idempotent upsert) — baseline_date == SOURCE_OBSERVATION_DATE인
    # 경우(같은 날 재실행) baseline_rows는 이미 위에서 정확히 캡처된 상태다.
    already_present = df["effective_date"] == SOURCE_OBSERVATION_DATE
    if already_present.any():
        print(f"기존 {SOURCE_OBSERVATION_DATE} row {already_present.sum()}건 발견 — 재검증을 위해 교체합니다.")
        df = df[~already_present].reset_index(drop=True)

    live_ticker_set = set(live_universe["ticker"])
    new_listing_tickers = sorted(live_ticker_set - baseline_ticker_set)
    removed_from_live_tickers = sorted(baseline_ticker_set - live_ticker_set)
    common_ticker_count = len(live_ticker_set & baseline_ticker_set)
    print(f"NEW_LISTING_COUNT={len(new_listing_tickers)}, REMOVED_FROM_LIVE_COUNT={len(removed_from_live_tickers)}, "
          f"COMMON_TICKER_COUNT={common_ticker_count}")

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
    insufficient_identity_tickers: list[str] = []

    new_rows: list[dict] = []
    for _, live_row in live_universe.iterrows():
        ticker = live_row["ticker"]
        baseline_asset_type = baseline_asset_type_by_ticker.get(ticker)
        asset_type, source_security_type, auth, asset_source = classify_live_row(
            live_row["universe_source"], ticker, df_equity, ticker in ever_been_spac_tickers
        )

        new_rows.append({
            "ticker": ticker,
            "name": live_row["name"],
            "market": live_row["market"],
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
        if asset_source == AUTH_INSUFFICIENT_IDENTITY:
            insufficient_identity_tickers.append(ticker)
        if baseline_asset_type is not None and baseline_asset_type != asset_type:
            changed_tickers.append({"ticker": ticker, "name": live_row["name"],
                                     "old_asset_type": baseline_asset_type, "new_asset_type": asset_type})

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    historical_row_count = int((df["effective_date"] != SOURCE_OBSERVATION_DATE).sum())
    # 지원 대상으로 정의한 live ticker(live_universe 전체)는 전부 current canonical
    # snapshot에 row가 생겼어야 한다(§3.11 coverage invariant) — 구성상 항상 0이어야 함.
    current_coverage_missing_count = len(live_ticker_set - set(row["ticker"] for row in new_rows))

    print(f"\nVerified rows (effective_date={SOURCE_OBSERVATION_DATE}): {verified_count}")
    print(f"Asset type distribution (verified rows): {asset_type_dist}")
    print(f"Formal source found but ticker not found (UNKNOWN, category D): {len(not_found_tickers)}")
    print(f"Formal source found, mapping unmapped (UNMAPPED_FORMAL_CATEGORY): {len(unmapped_tickers)}")
    print(f"Formal SPAC identity 상실 + ambiguous(INSUFFICIENT_FORMAL_IDENTITY): {len(insufficient_identity_tickers)} {insufficient_identity_tickers}")
    print(f"asset_type CHANGED vs baseline({baseline_date}) committed value: {len(changed_tickers)}")
    for c in changed_tickers:
        print(f"  {c['ticker']} {c['name']}: {c['old_asset_type']} -> {c['new_asset_type']}")
    print(f"Historical/legacy rows (all effective_date != {SOURCE_OBSERVATION_DATE}, downgraded to LEGACY_UNVERIFIED): {historical_row_count}")
    print(f"CURRENT_COVERAGE_MISSING_COUNT: {current_coverage_missing_count}")

    source_snapshot = build_canonical_source_snapshot(df_equity, df_etf, df_etn, df_delisted)
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
        "artifact_version": "4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "effective_date": SOURCE_OBSERVATION_DATE,
        "upstream_authority": "KRX Market Data Center (data.krx.co.kr), authenticated session",
        "upstream_source_name": "전종목기본정보 (bld=dbms/MDC/STAT/standard/MDCSTAT01901); "
                                 "ETF_전종목기본종목 (bld=dbms/MDC/STAT/standard/MDCSTAT04601); "
                                 "ETN_전종목기본종목 (bld=dbms/MDC/STAT/standard/MDCSTAT06701); "
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
        "insufficient_formal_identity_count_verified_rows": len(insufficient_identity_tickers),
        "insufficient_formal_identity_tickers": insufficient_identity_tickers,
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
        "current_live_universe": {
            "live_equity_count": live_equity_count,
            "live_etf_count": live_etf_count,
            "live_etn_count": live_etn_count,
            "live_supported_unique_tickers": live_supported_unique_tickers,
            "current_canonical_rows": verified_count,
            "baseline_ticker_count": baseline_ticker_count,
            "new_listing_count": len(new_listing_tickers),
            "new_listing_tickers": new_listing_tickers,
            "removed_from_live_count": len(removed_from_live_tickers),
            "removed_from_live_tickers": removed_from_live_tickers,
            "common_ticker_count": common_ticker_count,
            "current_coverage_missing_count": current_coverage_missing_count,
            "baseline_name_copied_to_current": False,
            "baseline_market_copied_to_current": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX Instrument Metadata Canonical Build v3")
    parser.add_argument("--dry-run", action="store_true", help="계획만 출력하고 파일을 쓰지 않음")
    args = parser.parse_args()

    build(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
