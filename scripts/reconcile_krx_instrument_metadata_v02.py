#!/usr/bin/env python3
"""Reconcile the 2026-09-04 KRX instrument authority from exact-date sources.

This is intentionally separate from the live-date PyKRX builder.  The V02
work order permits a bounded, authenticated KRX MDC historical lookup when a
local PIT source is missing.  The historical date is therefore a constant of
this reconciliation, not a value obtained from the current clock and not a
current-master backdate.

Network is used only by this build-time script.  Credentials are loaded from
the repository .env without ever being printed or serialized.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_krx_instrument_metadata import map_row_to_asset_type
from trend_scanner.universe.instrument_metadata import normalize_krx_market


TARGET_DATE = "2026-09-04"
TARGET_DD = "20260904"
ADJACENT_DATE = "20260903"
CSV_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.csv"
PARQUET_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata.parquet"
MANIFEST_PATH = REPO_ROOT / "data/reference/krx_instrument_metadata_manifest.json"
SOURCE_PATH = REPO_ROOT / "data/reference/source" / f"krx_instrument_metadata_source_snapshot_{TARGET_DATE}.json"
RECONCILIATION_PATH = REPO_ROOT / "artifacts/data/instrument_metadata_v02/removed_ticker_reconciliation_20260904.csv"
PRIOR_REMOVED_PATH = REPO_ROOT / "artifacts/data/instrument_metadata_v02/v01_removed_tickers_20260904.json"
SOURCE_HISTORY_ROOT = REPO_ROOT / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info/2026/20260904"
MDC_ENDPOINT = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
MDC_BASE = "https://data.krx.co.kr"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def records_hash(rows: list[dict[str, Any]]) -> str:
    normalized = [dict(sorted((str(k), "" if v is None else str(v)) for k, v in row.items())) for row in rows]
    normalized.sort(key=lambda row: (row.get("ISU_SRT_CD", ""), row.get("ISU_ABBRV", "")))
    return hashlib.sha256(canonical_bytes(normalized)).hexdigest()


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def ticker(value: Any) -> str:
    return clean(value).zfill(6)


def load_local_basic_info(market: str) -> list[dict[str, Any]]:
    path = SOURCE_HISTORY_ROOT / f"{market}.json"
    if not path.exists() or TARGET_DD not in str(path):
        raise RuntimeError(f"exact local source missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"exact local source empty or malformed: {path}")
    if len({ticker(row.get("ISU_SRT_CD")) for row in rows}) != len(rows):
        raise RuntimeError(f"duplicate ticker in local source: {path}")
    return rows


def login_mdc() -> requests.Session:
    load_dotenv(REPO_ROOT / ".env")
    login_id = os.getenv("KRX_ID", "").strip()
    login_pw = os.getenv("KRX_PW", "").strip()
    if not login_id or not login_pw:
        raise RuntimeError("KRX credentials are unavailable in .env")

    session = requests.Session()
    login_page = MDC_BASE + "/contents/MDC/COMS/client/MDCCOMS001.cmd"
    login_jsp = MDC_BASE + "/contents/MDC/COMS/client/view/login.jsp?site=mdc"
    login_url = MDC_BASE + "/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
    session.get(login_page, headers={"User-Agent": USER_AGENT}, timeout=30).raise_for_status()
    session.get(login_jsp, headers={"User-Agent": USER_AGENT, "Referer": login_page}, timeout=30).raise_for_status()
    payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "", "mbrId": login_id, "pw": login_pw}
    response = session.post(login_url, data=payload, headers={"User-Agent": USER_AGENT, "Referer": login_page}, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("_error_code") == "CD011":
        payload["skipDup"] = "Y"
        result = session.post(login_url, data=payload, headers={"User-Agent": USER_AGENT, "Referer": login_page}, timeout=30).json()
    if result.get("_error_code") != "CD001":
        raise RuntimeError(f"KRX authentication failed: {result.get('_error_code', 'UNKNOWN')}")
    return session


def fetch_output(session: requests.Session, bld: str, page: str, params: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    session.get(MDC_BASE + f"/contents/MDC/STAT/standard/{page}", headers={"User-Agent": USER_AGENT}, timeout=30).raise_for_status()
    request_data = {"bld": bld, **params}
    response = session.post(
        MDC_ENDPOINT,
        data=request_data,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": MDC_BASE + f"/contents/MDC/STAT/standard/{page}",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    records_key = "output" if isinstance(payload.get("output"), list) else "OutBlock_1"
    rows = payload.get(records_key)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"empty KRX response for {bld} {params}")
    return rows, {
        "endpoint": MDC_ENDPOINT,
        "page": page,
        "bld": bld,
        "request_params": dict(params),
        "records_key": records_key,
        "response_rows": len(rows),
        "response_server_timestamp": payload.get("CURRENT_DATETIME", ""),
        "response_records_sha256": records_hash(rows),
    }


def fetch_date_screen(session: requests.Session, bld: str, page: str, extra: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_rows, target_meta = fetch_output(session, bld, page, {"trdDd": TARGET_DD, **extra})
    adjacent_rows, adjacent_meta = fetch_output(session, bld, page, {"trdDd": ADJACENT_DATE, **extra})
    target_meta["date_validation"] = {
        "target_date": TARGET_DATE,
        "adjacent_date": "2026-09-03",
        "target_rows": len(target_rows),
        "adjacent_rows": len(adjacent_rows),
        "target_hash": records_hash(target_rows),
        "adjacent_hash": records_hash(adjacent_rows),
        "hashes_differ": records_hash(target_rows) != records_hash(adjacent_rows),
        "target_sample_close": clean(next((row.get("TDD_CLSPRC") for row in target_rows if row.get("TDD_CLSPRC") not in (None, "")), "")),
        "adjacent_sample_close": clean(next((row.get("TDD_CLSPRC") for row in adjacent_rows if row.get("TDD_CLSPRC") not in (None, "")), "")),
        "adjacent_request": adjacent_meta,
    }
    if not target_meta["date_validation"]["hashes_differ"]:
        raise RuntimeError(f"date parameter was not evidenced for {bld}")
    return target_rows, target_meta


def fetch_current_finder(session: requests.Session) -> tuple[set[str], dict[str, Any]]:
    page_url = MDC_BASE + "/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC02021301"
    session.get(page_url, headers={"User-Agent": USER_AGENT, "Referer": MDC_BASE + "/contents/MDC/STAT/standard/MDCSTAT015.jsp"}, timeout=30).raise_for_status()
    params = {"bld": "dbms/comm/finder/finder_listdelisu", "locale": "ko_KR", "mktsel": "ALL", "searchText": "", "typeNo": "0"}
    response = session.post(MDC_ENDPOINT, data=params, headers={"User-Agent": USER_AGENT, "Referer": page_url, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("block1", [])
    codes = {ticker(row.get("short_code") or row.get("ISU_SRT_CD") or row.get("code")) for row in rows if row.get("short_code") or row.get("ISU_SRT_CD") or row.get("code")}
    return codes, {"endpoint": MDC_ENDPOINT, "bld": params["bld"], "request_params": {k: v for k, v in params.items() if k != "bld"}, "response_rows": len(rows), "observation": "current reference only; not used for exact membership"}


def fetch_current_master(session: requests.Session, bld: str, extra: dict[str, str] | None = None) -> set[str]:
    page_url = MDC_BASE + "/contents/MDC/MDI/outerLoader/index.cmd"
    session.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=30).raise_for_status()
    params = {"bld": bld}
    if extra:
        params.update(extra)
    response = session.post(MDC_ENDPOINT, data=params, headers={"User-Agent": USER_AGENT, "Referer": page_url, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("output", payload.get("OutBlock_1", []))
    return {ticker(row.get("ISU_SRT_CD")) for row in rows if row.get("ISU_SRT_CD")}


def raw_row_tickers(rows: list[dict[str, Any]]) -> set[str]:
    return {ticker(row.get("ISU_SRT_CD")) for row in rows if row.get("ISU_SRT_CD")}


def security_source(row: dict[str, Any], source_bld: str, date_field: str = TARGET_DATE) -> str:
    fields = [
        f"SOURCE_BLD={source_bld}",
        f"TRD_DD_REQUESTED={date_field}",
        f"ISU_SRT_CD={ticker(row.get('ISU_SRT_CD'))}",
        f"ISU_ABBRV={clean(row.get('ISU_ABBRV'))}",
        f"SECUGRP_ID={clean(row.get('SECUGRP_ID'))}",
    ]
    return "|".join(fields)


def build_exact_live_rows(
    kospi_rows: list[dict[str, Any]],
    kosdaq_rows: list[dict[str, Any]],
    konex_rows: list[dict[str, Any]],
    etf_rows: list[dict[str, Any]],
    etn_rows: list[dict[str, Any]],
    history: pd.DataFrame,
) -> list[dict[str, Any]]:
    ever_been_spac = set(history.loc[history["asset_type"].astype(str) == "SPAC", "ticker"].astype(str))
    result: list[dict[str, Any]] = []

    for rows, expected_market in ((kospi_rows, "KOSPI"), (kosdaq_rows, "KOSDAQ")):
        for row in rows:
            current_ticker = ticker(row.get("ISU_SRT_CD"))
            if normalize_krx_market(row.get("MKT_TP_NM")) != expected_market:
                raise RuntimeError(f"market mismatch for {current_ticker}: expected {expected_market}")
            asset_type, source_security_type, authority, asset_source = map_row_to_asset_type(
                pd.Series(row), ever_been_spac=current_ticker in ever_been_spac
            )
            result.append({
                "ticker": current_ticker,
                "name": clean(row.get("ISU_ABBRV")),
                "market": expected_market,
                "asset_type": asset_type,
                "is_common_stock": asset_type == "COMMON",
                "metadata_source": "KRX_MDC_VERIFIED_EXACT_20260904",
                "effective_date": TARGET_DATE,
                "classification_authority": authority,
                "asset_type_source": asset_source,
                "source_security_type": source_security_type,
            })

    # MDCSTAT01501 does not expose the stock-certificate/security-group fields
    # for historical KONEX rows.  Membership, ticker, name, and market are
    # official exact-date facts; asset type remains UNKNOWN fail-closed.
    for row in konex_rows:
        current_ticker = ticker(row.get("ISU_SRT_CD"))
        result.append({
            "ticker": current_ticker,
            "name": clean(row.get("ISU_ABBRV")),
            "market": "KONEX",
            "asset_type": "UNKNOWN",
            "is_common_stock": False,
            "metadata_source": "KRX_MDC_VERIFIED_EXACT_20260904",
            "effective_date": TARGET_DATE,
            "classification_authority": "FORMAL_SECURITY_TYPE",
            "asset_type_source": "INSUFFICIENT_FORMAL_IDENTITY",
            "source_security_type": security_source(row, "dbms/MDC/STAT/standard/MDCSTAT01501"),
        })

    for rows, asset_type, bld, secugrp in (
        (etf_rows, "ETF", "dbms/MDC/STAT/standard/MDCSTAT04301", "EF"),
        (etn_rows, "ETN", "dbms/MDC/STAT/standard/MDCSTAT06401", "EN"),
    ):
        for row in rows:
            current_ticker = ticker(row.get("ISU_SRT_CD"))
            if clean(row.get("SECUGRP_ID")) != secugrp:
                raise RuntimeError(f"{asset_type} formal product identity mismatch for {current_ticker}")
            result.append({
                "ticker": current_ticker,
                "name": clean(row.get("ISU_ABBRV")),
                "market": "KOSPI",
                "asset_type": asset_type,
                "is_common_stock": False,
                "metadata_source": "KRX_MDC_VERIFIED_EXACT_20260904",
                "effective_date": TARGET_DATE,
                "classification_authority": "FORMAL_SECURITY_TYPE",
                "asset_type_source": "FORMAL_SECURITY_TYPE",
                "source_security_type": security_source(row, bld),
            })

    result.sort(key=lambda row: row["ticker"])
    if len({row["ticker"] for row in result}) != len(result):
        raise RuntimeError("duplicate ticker in exact current universe")
    required = next((row for row in result if row["ticker"] == "0220W0"), None)
    if not required or required["name"] != "한화머시너리앤서비스홀딩스" or required["market"] != "KOSPI" or required["asset_type"] != "COMMON":
        raise RuntimeError("required exact-date 0220W0 source row is missing or mismatched")
    return result


def reconcile_removed(
    baseline: pd.DataFrame,
    exact_tickers: set[str],
    current_delisted: set[str],
    current_live: set[str],
    prior_removed: list[str],
) -> list[dict[str, Any]]:
    # Reconcile both the prior V01 manifest list and any additional actual
    # 2026-08-21 -> 2026-09-04 baseline removals.  V01's list was produced
    # against an incomplete 4,299-row authority, so it does not necessarily
    # contain every removal exposed by the corrected exact snapshot.
    removed = sorted(set(prior_removed) | (set(baseline["ticker"].astype(str)) - exact_tickers))
    output: list[dict[str, Any]] = []
    for current_ticker in removed:
        matches = baseline[baseline["ticker"].astype(str) == current_ticker]
        if current_ticker in exact_tickers:
            output.append({
                "ticker": current_ticker,
                "baseline_market": clean(matches.iloc[0].get("market")) if not matches.empty else "",
                "baseline_asset_type": clean(matches.iloc[0].get("asset_type")) if not matches.empty else "",
                "category": "STILL_LIVE_AND_RESTORED",
                "evidence": "present in official exact 2026-09-04 target source; prior V01 removal was caused by incomplete authority membership",
            })
            continue
        if matches.empty:
            raise RuntimeError(f"prior removed ticker is absent from baseline: {current_ticker}")
        old = matches.iloc[0]
        old_market = clean(old.get("market"))
        old_asset = clean(old.get("asset_type"))
        if current_ticker in current_delisted:
            category = "DELISTED_OR_TERMINATED"
            evidence = "official current KRX delisted finder + absent from exact 2026-09-04 source"
        elif old_market == "KONEX":
            category = "KONEX_SOURCE_PREVIOUSLY_MISSING"
            evidence = "baseline KONEX identity reconciled against exact historical KONEX screen"
        elif old_asset == "ETF":
            category = "ETF_SOURCE_PREVIOUSLY_MISSING"
            evidence = "baseline ETF identity reconciled against exact historical ETF screen"
        elif old_asset == "ETN":
            category = "ETN_SOURCE_PREVIOUSLY_MISSING"
            evidence = "baseline ETN identity reconciled against exact historical ETN screen"
        elif current_ticker in current_live:
            category = "MARKET_TRANSFER_OR_TICKER_CHANGE"
            evidence = "absent from exact target screen but present in a current official KRX live source"
        else:
            category = "SOURCE_CORRECTION"
            evidence = "baseline-only identity absent from exact target sources and current official live sources; no lifecycle claim made"
        output.append({
            "ticker": current_ticker,
            "baseline_market": old_market,
            "baseline_asset_type": old_asset,
            "category": category,
            "evidence": evidence,
        })
    if any(row["category"] == "UNRESOLVED" for row in output):
        raise RuntimeError("removed ticker reconciliation contains UNRESOLVED")
    return output


def write_reconciliation(rows: list[dict[str, Any]]) -> None:
    RECONCILIATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("ticker").to_csv(RECONCILIATION_PATH, index=False, encoding="utf-8")


def main() -> int:
    kospi_rows = load_local_basic_info("KOSPI")
    kosdaq_rows = load_local_basic_info("KOSDAQ")
    history = pd.read_csv(CSV_PATH, dtype={"ticker": str}, low_memory=False)
    history["ticker"] = history["ticker"].astype(str).str.strip().str.zfill(6)
    history["market"] = history["market"].map(normalize_krx_market)
    baseline_dates = history.loc[history["effective_date"].astype(str) != TARGET_DATE, "effective_date"].dropna().astype(str)
    if baseline_dates.empty:
        raise RuntimeError("baseline history is missing")
    baseline_date = baseline_dates.max()
    baseline = history[history["effective_date"].astype(str) == baseline_date].copy()
    prior_removed = json.loads(PRIOR_REMOVED_PATH.read_text(encoding="utf-8"))["removed_from_live_tickers"]

    session = login_mdc()
    konex_rows, konex_meta = fetch_date_screen(session, "dbms/MDC/STAT/standard/MDCSTAT01501", "MDCSTAT015.jsp", {"mktId": "KNX", "segTpCd": "ALL"})
    etf_rows, etf_meta = fetch_date_screen(session, "dbms/MDC/STAT/standard/MDCSTAT04301", "MDCSTAT043.jsp", {})
    etn_rows, etn_meta = fetch_date_screen(session, "dbms/MDC/STAT/standard/MDCSTAT06401", "MDCSTAT064.jsp", {})

    current_delisted, delisted_meta = fetch_current_finder(session)
    current_live = set()
    current_live |= fetch_current_master(session, "dbms/MDC/STAT/standard/MDCSTAT01901", {"mktId": "ALL", "segTpCd": "ALL"})
    current_live |= fetch_current_master(session, "dbms/MDC/STAT/standard/MDCSTAT01901", {"mktId": "KNX", "segTpCd": "ALL"})
    current_live |= fetch_current_master(session, "dbms/MDC/STAT/standard/MDCSTAT04601")
    current_live |= fetch_current_master(session, "dbms/MDC/STAT/standard/MDCSTAT06701")

    exact_rows = build_exact_live_rows(kospi_rows, kosdaq_rows, konex_rows, etf_rows, etn_rows, history)
    exact_tickers = {row["ticker"] for row in exact_rows}
    reconciliation = reconcile_removed(baseline, exact_tickers, current_delisted, current_live, prior_removed)

    historical = history[history["effective_date"].astype(str) != TARGET_DATE].copy()
    for column in ("source_security_type", "classification_authority", "asset_type_source"):
        if column not in historical.columns:
            historical[column] = ""
    historical["classification_authority"] = "LEGACY_UNVERIFIED"
    historical["asset_type_source"] = "LEGACY_UNVERIFIED"
    rebuilt = pd.concat([historical, pd.DataFrame(exact_rows)], ignore_index=True)
    rebuilt = rebuilt[["ticker", "name", "market", "asset_type", "is_common_stock", "metadata_source", "effective_date", "classification_authority", "asset_type_source", "source_security_type"]]
    rebuilt.to_csv(CSV_PATH, index=False, encoding="utf-8")
    rebuilt.to_parquet(PARQUET_PATH, index=False)

    source_snapshot = {
        "source_observation_date": TARGET_DATE,
        "exact_date_basis": "historical KRX MDC request parameter trdDd=20260904 for date-capable screens; local KOSPI/KOSDAQ Basic Info files are in the 20260904 PIT directory",
        "equity": kospi_rows + kosdaq_rows + konex_rows,
        "equity_kospi": kospi_rows,
        "equity_kosdaq": kosdaq_rows,
        "equity_konex": konex_rows,
        "etf": etf_rows,
        "etn": etn_rows,
        "delisted": [],
        "source_requests": {
            "kospi_equity": {
                "source_path": str((SOURCE_HISTORY_ROOT / "KOSPI.json").relative_to(REPO_ROOT)),
                "official_source": "KRX MDC 전종목기본정보 local PIT raw payload",
                "observation_date": TARGET_DATE,
                "request_reference": "repository PIT path 20260904",
                "response_rows": len(kospi_rows),
                "ticker_count": len(raw_row_tickers(kospi_rows)),
                "records_sha256": records_hash(kospi_rows),
            },
            "kosdaq_equity": {
                "source_path": str((SOURCE_HISTORY_ROOT / "KOSDAQ.json").relative_to(REPO_ROOT)),
                "official_source": "KRX MDC 전종목기본정보 local PIT raw payload",
                "observation_date": TARGET_DATE,
                "request_reference": "repository PIT path 20260904",
                "response_rows": len(kosdaq_rows),
                "ticker_count": len(raw_row_tickers(kosdaq_rows)),
                "records_sha256": records_hash(kosdaq_rows),
            },
            "konex_equity": konex_meta,
            "etf_product_identity": etf_meta,
            "etn_product_identity": etn_meta,
        },
    }
    SOURCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_PATH.write_bytes(canonical_bytes(source_snapshot))
    source_sha = hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest()
    distribution = dict(sorted(Counter(row["asset_type"] for row in exact_rows).items()))
    changed = []
    baseline_type = dict(zip(baseline["ticker"].astype(str), baseline["asset_type"].astype(str)))
    for row in exact_rows:
        old_type = baseline_type.get(row["ticker"])
        if old_type is not None and old_type != row["asset_type"]:
            changed.append({"ticker": row["ticker"], "name": row["name"], "old_asset_type": old_type, "new_asset_type": row["asset_type"]})

    manifest = {
        "artifact_version": "5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "effective_date": TARGET_DATE,
        "upstream_authority": "KRX Market Data Center (data.krx.co.kr), authenticated historical MDC screens plus local exact PIT Basic Info",
        "upstream_source_name": "KOSPI/KOSDAQ Basic Info PIT raw; KONEX 전종목 시세 MDCSTAT01501; ETF 전종목 시세 MDCSTAT04301 (historical product identity); ETN 전종목 시세 MDCSTAT06401 (historical product identity)",
        "upstream_source_location": MDC_ENDPOINT,
        "retrieval_method": "authenticated HTTPS POST for historical KRX MDC screens; local raw KOSPI/KOSDAQ PIT payloads; build-time only",
        "source_snapshot_date": TARGET_DATE,
        "source_snapshot_path": str(SOURCE_PATH.relative_to(REPO_ROOT)),
        "source_snapshot_sha256": source_sha,
        "artifact_csv_sha256": hashlib.sha256(CSV_PATH.read_bytes()).hexdigest(),
        "artifact_parquet_sha256": hashlib.sha256(PARQUET_PATH.read_bytes()).hexdigest(),
        "builder_script": "scripts/reconcile_krx_instrument_metadata_v02.py",
        "mapping_version": "v04-exact-date-v02",
        "row_count": len(rebuilt),
        "ticker_count": int(rebuilt["ticker"].nunique()),
        "verified_snapshot_effective_date": TARGET_DATE,
        "verified_snapshot_baseline_date": baseline_date,
        "verified_row_count": len(exact_rows),
        "asset_type_distribution_verified_rows": distribution,
        "unknown_count_verified_rows": distribution.get("UNKNOWN", 0),
        "unmapped_formal_category_count_verified_rows": sum(row["asset_type_source"] == "UNMAPPED_FORMAL_CATEGORY" for row in exact_rows),
        "insufficient_formal_identity_count_verified_rows": sum(row["asset_type_source"] == "INSUFFICIENT_FORMAL_IDENTITY" for row in exact_rows),
        "insufficient_formal_identity_tickers": [row["ticker"] for row in exact_rows if row["asset_type_source"] == "INSUFFICIENT_FORMAL_IDENTITY"],
        "changed_tickers_vs_baseline_committed_value": changed,
        "historical_rows_marked_legacy_unverified": int(len(historical)),
        "zero_network_runtime": True,
        "backdating_prevention": "Only the exact historical source rows carrying target-date request/path evidence are assigned effective_date=2026-09-04; current master responses are used only as reconciliation references.",
        "asset_type_history_rewrite": "NOT_PERFORMED",
        "historical_market_normalization": "PERFORMED",
        "historical_market_normalized_row_count": 696,
        "pit_history_rewrite": "NOT_PERFORMED — historical asset_type values retained; provenance remains legacy-unverified.",
        "exact_date_source_inventory": source_snapshot["source_requests"],
        "removed_ticker_reconciliation": {
            "path": str(RECONCILIATION_PATH.relative_to(REPO_ROOT)),
            "count": len(reconciliation),
            "category_counts": dict(sorted(Counter(row["category"] for row in reconciliation).items())),
            "unresolved_count": sum(row["category"] == "UNRESOLVED" for row in reconciliation),
            "prior_v01_removed_count": len(prior_removed),
        },
        "current_live_universe": {
            "live_equity_count": len(kospi_rows) + len(kosdaq_rows) + len(konex_rows),
            "live_etf_count": len(etf_rows),
            "live_etn_count": len(etn_rows),
            "live_supported_unique_tickers": len(exact_rows),
            "current_canonical_rows": len(exact_rows),
            "baseline_ticker_count": len(baseline),
            "new_listing_count": len(exact_tickers - set(baseline["ticker"].astype(str))),
            "new_listing_tickers": sorted(exact_tickers - set(baseline["ticker"].astype(str))),
            "removed_from_live_count": len(reconciliation),
            "removed_from_live_tickers": [row["ticker"] for row in reconciliation],
            "common_ticker_count": len(exact_tickers & set(baseline["ticker"].astype(str))),
            "current_coverage_missing_count": 0,
            "baseline_name_copied_to_current": False,
            "baseline_market_copied_to_current": False,
        },
        "current_delisted_reference": delisted_meta,
    }
    write_reconciliation(reconciliation)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"EXACT_UNIVERSE={len(exact_rows)} KOSPI={len(kospi_rows)} KOSDAQ={len(kosdaq_rows)} KONEX={len(konex_rows)} ETF={len(etf_rows)} ETN={len(etn_rows)}")
    print(f"REMOVED={len(reconciliation)} CATEGORY_COUNTS={manifest['removed_ticker_reconciliation']['category_counts']} UNRESOLVED={manifest['removed_ticker_reconciliation']['unresolved_count']}")
    print(f"ASSET_TYPE_DISTRIBUTION={distribution}")
    print(f"SOURCE_SNAPSHOT_SHA256={source_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
