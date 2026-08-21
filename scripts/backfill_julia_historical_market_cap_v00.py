#!/usr/bin/env python
"""Robust KRX Historical Market Cap Backfill for Julia Strategy V00 Required Signal Dates.

Fetches canonical KRX all-stock market cap snapshots for all missing required signal reference dates,
normalizes them according to Phase 13J-0 / Historical Investability contract, and builds
artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv
import pandas as pd
import requests

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

HISTORY_DIR = ROOT / "artifacts/patterns/pattern_a/validation/investability_history"
SOURCE_DIR = HISTORY_DIR / "source"
NORMALIZED_DIR = HISTORY_DIR / "normalized"
JULIA_V00_DIR = ROOT / "artifacts/strategies/julia/v00"

REQUIRED_DATES_CSV = JULIA_V00_DIR / "historical_market_cap_required_dates.csv"
MANIFEST_CSV = JULIA_V00_DIR / "historical_market_cap_source_manifest.csv"
SOURCE_PROVIDER = "KRX"
SOURCE_PRODUCT = "ALL_STOCK_MARKET_DATA"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REFERER = "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DirectKRXClient:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "X-Requested-With": "XMLHttpRequest",
        }
        self._warmup()

    def _warmup(self):
        try:
            self.session.get(REFERER, headers=self.headers, timeout=15)
        except Exception:
            pass

    def fetch_market_snapshot(self, date_compact: str, max_retries: int = 6) -> list[dict[str, Any]]:
        url = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        payload = {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
            "mktId": "ALL",
            "trdDd": date_compact,
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.post(url, headers=self.headers, data=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    out = data.get("OutBlock_1", [])
                    if out:
                        return out
                # If error page or empty response, wait and recreate session
                wait_time = 5.0 * attempt
                logger.warning("Attempt %d for %s received non-JSON/empty response. Cooling down %ds...", attempt, date_compact, wait_time)
                time.sleep(wait_time)
                self.session = requests.Session()
                self._warmup()
            except Exception as e:
                wait_time = 5.0 * attempt
                logger.warning("Attempt %d for %s failed (%s). Cooling down %ds...", attempt, date_compact, e, wait_time)
                time.sleep(wait_time)
                self.session = requests.Session()
                self._warmup()

        return []


def resolve_trading_date(client: DirectKRXClient, candidate_date_str: str) -> str:
    c_compact = candidate_date_str.replace("-", "")
    rows = client.fetch_market_snapshot(c_compact, max_retries=3)
    if rows:
        return c_compact

    dt = pd.Timestamp(candidate_date_str)
    for offset in range(1, 8):
        prior_dt = dt - pd.Timedelta(days=offset)
        prior_compact = prior_dt.strftime("%Y%m%d")
        rows = client.fetch_market_snapshot(prior_compact, max_retries=2)
        if rows:
            logger.info("Candidate %s was holiday/weekend, resolved to prior trading date %s", candidate_date_str, prior_compact)
            return prior_compact

    raise ValueError(f"Unable to resolve trading date for candidate {candidate_date_str}")


def raw_to_normalized(raw_rows: list[dict[str, Any]], effective_date_iso: str) -> pd.DataFrame:
    df_raw = pd.DataFrame(raw_rows)
    # KRX Column mapping for MDCSTAT01501:
    # ISU_SRT_CD -> ticker
    # ISU_ABBRV -> name
    # MKT_NM -> raw_market / market
    # TDD_CLSPRC -> close
    # ACC_TRDVOL -> volume
    # ACC_TRDVAL -> trading_value
    # MKTCAP -> market_cap
    # LIST_SHRS -> shares_outstanding
    records = []
    for _, r in df_raw.iterrows():
        ticker = str(r.get("ISU_SRT_CD", "")).strip().zfill(6)
        name = str(r.get("ISU_ABBRV", "")).strip()
        mkt_raw = str(r.get("MKT_NM", "")).strip()
        mkt = "KOSPI" if mkt_raw.startswith("KOSPI") else "KOSDAQ" if mkt_raw.startswith("KOSDAQ") else "KONEX" if mkt_raw.startswith("KONEX") else "OTHER"

        def _num(val: Any) -> int | None:
            if val is None or pd.isna(val):
                return None
            s = str(val).replace(",", "").strip()
            return int(s) if s and s != "-" else None

        records.append({
            "ticker": ticker,
            "name": name,
            "raw_market": mkt_raw,
            "market": mkt,
            "close": _num(r.get("TDD_CLSPRC")),
            "volume": _num(r.get("ACC_TRDVOL")),
            "trading_value": _num(r.get("ACC_TRDVAL")),
            "market_cap": _num(r.get("MKTCAP")),
            "shares_outstanding": _num(r.get("LIST_SHRS")),
            "effective_date": effective_date_iso,
        })

    df = pd.DataFrame(records)
    if df["ticker"].duplicated().any():
        df = df.drop_duplicates(subset=["ticker"], keep="first")
    return df


def backfill_all_required_dates() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    JULIA_V00_DIR.mkdir(parents=True, exist_ok=True)

    if not REQUIRED_DATES_CSV.exists():
        raise FileNotFoundError(f"Missing required dates manifest: {REQUIRED_DATES_CSV}")

    df_req = pd.read_csv(REQUIRED_DATES_CSV)
    required_dates = sorted(df_req["signal_reference_date"].unique().tolist())
    total_dates = len(required_dates)
    logger.info("Processing %d required signal reference dates...", total_dates)

    client = DirectKRXClient()
    manifest_rows: list[dict[str, Any]] = []

    for idx, sig_d_str in enumerate(required_dates, 1):
        target_compact = sig_d_str.replace("-", "")
        norm_filename = f"krx_market_cap_{target_compact}.csv"
        raw_filename = f"krx_market_cap_{target_compact}.csv"
        norm_path = NORMALIZED_DIR / norm_filename
        raw_path = SOURCE_DIR / raw_filename

        # Check if already existing and valid
        if norm_path.exists() and norm_path.stat().st_size > 1000:
            df_norm = pd.read_csv(norm_path, dtype={"ticker": str})
            eff_d = str(df_norm.iloc[0]["effective_date"]) if not df_norm.empty else sig_d_str
            raw_sha = sha256_file(raw_path) if raw_path.exists() else sha256_file(norm_path)
            norm_sha = sha256_file(norm_path)

            manifest_rows.append({
                "signal_reference_date": sig_d_str,
                "source_provider": SOURCE_PROVIDER,
                "source_product": SOURCE_PRODUCT,
                "requested_date": sig_d_str,
                "effective_date": eff_d,
                "date_resolution_status": "EXACT_COMPLETED_WEEK" if eff_d == sig_d_str else "PRIOR_COMPLETED_WEEK",
                "raw_source_file": str(raw_path.relative_to(ROOT)) if raw_path.exists() else str(norm_path.relative_to(ROOT)),
                "normalized_source_file": str(norm_path.relative_to(ROOT)),
                "raw_sha256": raw_sha,
                "normalized_sha256": norm_sha,
                "row_count": len(df_norm),
                "source_status": "AVAILABLE_EXISTING",
            })
            continue

        # Fetch directly from KRX MDCSTAT01501
        logger.info("[%d/%d] Fetching KRX snapshot for %s...", idx, total_dates, sig_d_str)
        resolved_compact = resolve_trading_date(client, sig_d_str)
        raw_rows = client.fetch_market_snapshot(resolved_compact, max_retries=6)

        if not raw_rows or len(raw_rows) < 500:
            raise ValueError(f"Empty or incomplete KRX snapshot for {sig_d_str} (resolved {resolved_compact})")

        eff_d_iso = f"{resolved_compact[:4]}-{resolved_compact[4:6]}-{resolved_compact[6:8]}"
        df_snapshot = raw_to_normalized(raw_rows, eff_d_iso)

        # Save files
        df_snapshot.to_csv(norm_path, index=False, encoding="utf-8")
        df_snapshot.to_csv(raw_path, index=False, encoding="utf-8")

        raw_sha = sha256_file(raw_path)
        norm_sha = sha256_file(norm_path)

        manifest_rows.append({
            "signal_reference_date": sig_d_str,
            "source_provider": SOURCE_PROVIDER,
            "source_product": SOURCE_PRODUCT,
            "requested_date": sig_d_str,
            "effective_date": eff_d_iso,
            "date_resolution_status": "EXACT_COMPLETED_WEEK" if eff_d_iso == sig_d_str else "PRIOR_COMPLETED_WEEK",
            "raw_source_file": str(raw_path.relative_to(ROOT)),
            "normalized_source_file": str(norm_path.relative_to(ROOT)),
            "raw_sha256": raw_sha,
            "normalized_sha256": norm_sha,
            "row_count": len(df_snapshot),
            "source_status": "BACKFILLED_FIX02",
        })
        logger.info("Successfully saved snapshot for %s (%d tickers)", sig_d_str, len(df_snapshot))
        time.sleep(1.0)  # Safe rate limit

    df_manifest = pd.DataFrame(manifest_rows)
    df_manifest.to_csv(MANIFEST_CSV, index=False)
    logger.info("Manifest successfully created at %s with %d entries (100%% coverage)!", MANIFEST_CSV, len(df_manifest))


if __name__ == "__main__":
    backfill_all_required_dates()
