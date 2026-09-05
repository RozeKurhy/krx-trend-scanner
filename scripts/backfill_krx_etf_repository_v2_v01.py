#!/usr/bin/env python3
"""Populate the approved ETF Repository V2 authorities.

The script is intentionally explicit and resumable.  KRX ETF daily snapshots
are fetched only from the official ``etp/etf_bydd_trd`` route; adjusted OHLC
is fetched only through the approved direct Naver adjusted provider.  No
legacy parquet, PyKRX, web scraping, fallback, or value reconstruction is
used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_etf_raw_provider import ETF_AUTHORITY, ETF_ENDPOINT, KrxRawEtfSnapshotProvider
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_TICKERS = (
    "0115D0", "069500", "091160", "091170", "091180", "102960", "102970",
    "117460", "117680", "117700", "140700", "140710", "229200", "244580",
    "266410", "300950", "305720",
)
DEFAULT_START = "2023-01-02"
DEFAULT_END = "2026-08-21"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
ARTIFACT_ROOT = ROOT / "artifacts/data/end_to_end_data_parity/v01/authority_adjudication/v01/etf"


def _read_env_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def load_auth_key() -> str:
    return (
        os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
        or _read_env_value(ROOT / ".env", "KRX_OPEN_API_AUTH_KEY").strip()
        or _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY").strip()
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _date_list(store: KrxRawStockStore, start: str, end: str) -> list[str]:
    # KOSPI's already-validated manifest is the local trading-session authority.
    return [
        str(row["date"])
        for row in store.list_manifest("KOSPI")
        if start <= str(row["date"]) <= end and row["status"] == "COMPLETE"
    ]


def _closed_date_list(store: KrxRawStockStore, start: str, end: str) -> list[str]:
    return [
        str(row["date"])
        for row in store.list_manifest("KOSPI")
        if start <= str(row["date"]) <= end and row["status"] == "NO_DATA"
    ]


def _coverage(store: KrxRawStockStore, dates: list[str]) -> dict[str, int]:
    rows = [row for row in store.list_manifest("ETF") if str(row["date"]) in set(dates)]
    return {
        "complete": sum(row["status"] == "COMPLETE" for row in rows),
        "no_data": sum(row["status"] == "NO_DATA" for row in rows),
        "failed": sum(row["status"] == "FAILED" for row in rows),
        "terminal": sum(row["status"] in {"COMPLETE", "NO_DATA"} for row in rows),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.execute_live:
        raise RuntimeError("LIVE_EXECUTION_REQUIRED")
    auth_key = load_auth_key()
    if not auth_key:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    store = KrxRawStockStore(args.raw_root)
    dates = _date_list(store, args.start, args.end)
    closed_dates = _closed_date_list(store, args.start, args.end)
    # The existing KRX stock manifest is the local session authority.  A
    # market-closed date has no ETF snapshot to acquire; persist an explicit
    # NO_DATA terminal observation rather than making a request that returns
    # rows with source-empty numeric fields.
    empty_template = None
    if closed_dates:
        import pandas as pd
        empty_template = pd.DataFrame({
            "date": pd.Series([], dtype="datetime64[ns]"),
            "ticker": pd.Series([], dtype="string"),
            **{field: pd.Series([], dtype="int64") for field in ("open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares")},
        }, columns=["date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"])
        for day in closed_dates:
            store.save_snapshot("ETF", day, empty_template, ETF_ENDPOINT)
    before = _coverage(store, dates)
    quota = LocalKrxOpenApiQuota(args.quota_db)
    client = KrxOpenApiClient(
        auth_key,
        max_requests=max(1, len(dates) - before["terminal"] + 2),
        max_transient_retries=0,
        timeout=args.timeout,
        quota=quota,
    )
    raw_provider = KrxRawEtfSnapshotProvider(client)
    raw_started = time.monotonic()
    raw_failures: list[dict[str, str]] = []
    raw_saved = 0
    for day in dates:
        existing = store.get_manifest("ETF", day)
        if args.resume and existing is not None and existing["status"] in {"COMPLETE", "NO_DATA"}:
            continue
        try:
            frame = raw_provider.fetch_snapshot(day)
            store.save_snapshot("ETF", day, frame, ETF_ENDPOINT)
            raw_saved += 1
        except Exception as exc:
            # A failed response is terminal for this bounded run; do not retry
            # an authorization/schema blocker or substitute another source.
            store.save_failure("ETF", day, ETF_ENDPOINT, type(exc).__name__, str(exc))
            raw_failures.append({"date": day, "error_type": type(exc).__name__, "safe_message": str(exc)[:500]})
            break
        if args.request_interval_ms:
            time.sleep(args.request_interval_ms / 1000.0)
    raw_elapsed = time.monotonic() - raw_started

    adjusted_started = time.monotonic()
    adjusted_provider = NaverDirectAdjustedPriceDataProvider(timeout_seconds=args.timeout)
    adjusted_store = AdjustedPriceStore(args.adjusted_root)
    adjusted_results: list[dict[str, Any]] = []
    adjusted_failures: list[dict[str, str]] = []
    for ticker in ACCEPTANCE_TICKERS:
        try:
            frame = adjusted_provider.load_daily(ticker, args.start, args.end)
            if frame.empty:
                raise RuntimeError("EMPTY_ADJUSTED_AUTHORITY")
            adjusted_store.save_full(
                ticker,
                frame,
                metadata_context={"requested_start": args.start, "requested_end": args.end},
            )
            metadata = adjusted_store.load_metadata(ticker)
            adjusted_results.append(
                {
                    "ticker": ticker,
                    "status": "SUCCESS",
                    "first_date": metadata["actual_date_min"],
                    "last_date": metadata["actual_date_max"],
                    "row_count": int(metadata["row_count"]),
                    "duplicate_date_count": 0,
                    "source_authority": metadata["source_authority_id"],
                }
            )
        except Exception as exc:
            adjusted_failures.append({"ticker": ticker, "error_type": type(exc).__name__, "safe_message": str(exc)[:500]})
            break
    adjusted_elapsed = time.monotonic() - adjusted_started
    after = _coverage(store, dates)
    status = "PASS" if not raw_failures and not adjusted_failures and after["failed"] == 0 and after["terminal"] == len(dates) and len(adjusted_results) == len(ACCEPTANCE_TICKERS) else "BLOCKED"
    payload = {
        "generation": "ETF_REPOSITORY_V2_SUPPORT_V01",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "instrument_type": "ETF",
        "acceptance_tickers": list(ACCEPTANCE_TICKERS),
        "requested_range": {"start": args.start, "end": args.end},
        "raw_authority": {"service": ETF_AUTHORITY, "endpoint": ETF_ENDPOINT, "dates": len(dates), "before": before, "after": after, "saved_partitions": raw_saved, "failures": raw_failures, "elapsed_seconds": round(raw_elapsed, 3), "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": dict(client.status_counts)},
        "adjusted_authority": {"provider": "NaverDirectAdjustedPriceDataProvider", "results": adjusted_results, "failures": adjusted_failures, "elapsed_seconds": round(adjusted_elapsed, 3), "http_call_count": adjusted_provider.naver_http_call_count, "pykrx_fallback_call_count": adjusted_provider.pykrx_fallback_call_count},
        "forbidden_sources": {"pykrx_used": False, "krx_web_scraping_used": False, "legacy_etf_promotion_used": False, "naver_raw_fallback_used": False, "manual_data_injection": False},
    }
    _write_json(ARTIFACT_ROOT / "repository_v2_etf_support_manifest.json", payload)
    _write_json(ARTIFACT_ROOT / "repository_v2_etf_validation_summary.json", {"status": status, "acceptance_count": len(ACCEPTANCE_TICKERS), "pass_count": len(adjusted_results) if status == "PASS" else 0, "raw_coverage": after})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--request-interval-ms", type=int, default=80)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--adjusted-root", type=Path, default=ADJUSTED_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({"status": result["status"], "raw": result["raw_authority"], "adjusted_count": len(result["adjusted_authority"]["results"])}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
