#!/usr/bin/env python3
"""Expand the approved ETF adjusted-price scope by the fixed 11-ticker set.

This is a bounded, resumable expansion.  It reads the existing local ETF raw
store, fetches only missing tickers through the approved Naver adjusted-price
provider, persists through ``AdjustedPriceStore``, and validates the composed
Repository V2 view before reporting promotion readiness.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2_loader import build_repository_v2
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver


ROOT = Path(__file__).resolve().parents[1]
NEW_ETF_TICKERS = (
    "226490", "139230", "139260", "157490", "143860", "266390",
    "266360", "133690", "360750", "241180", "192090",
)
EXISTING_ETF_TICKERS = (
    "0115D0", "069500", "091160", "091170", "091180", "102960", "102970",
    "117460", "117680", "117700", "140700", "140710", "229200", "244580",
    "266410", "300950", "305720",
)
REQUESTED_START = "2023-01-02"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
ARTIFACT_ROOT = ROOT / "artifacts/data/etf_adjusted_scope_expansion/v01"
ARTIFACT_PATH = ARTIFACT_ROOT / "validation_summary.json"


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _raw_partition_path(store: KrxRawStockStore, row: dict[str, Any]) -> Path:
    path = Path(str(row["file_path"]))
    return path if path.is_absolute() else store.root / path


def determine_target_end(
    adjusted_store: AdjustedPriceStore,
    existing_tickers: Iterable[str] = EXISTING_ETF_TICKERS,
) -> str:
    """Use the common latest valid date of the existing approved ETF stores."""

    latest_dates: list[str] = []
    for ticker in existing_tickers:
        if not adjusted_store.is_current_authority_snapshot(ticker):
            raise RuntimeError(f"EXISTING_ETF_ADJUSTED_AUTHORITY_INVALID:{ticker}")
        metadata = adjusted_store.load_metadata(ticker)
        latest_dates.append(_date(metadata["actual_date_max"]))
    if not latest_dates:
        raise RuntimeError("EXISTING_ETF_ADJUSTED_SCOPE_EMPTY")
    return min(latest_dates)


def validate_metadata(
    repo_root: Path,
    tickers: Iterable[str] = NEW_ETF_TICKERS,
    *,
    as_of: str,
) -> list[dict[str, Any]]:
    """Validate the fixed expansion set against local formal PIT metadata."""

    InstrumentMetadataResolver.clear_cache()
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        metadata = InstrumentMetadataResolver.resolve(ticker, as_of=as_of, repo_root=repo_root)
        row = {
            "ticker": ticker,
            "name": metadata.name,
            "asset_type": metadata.asset_type,
            "trusted_for_production": metadata.is_trusted_for_production,
            "classification_authority": metadata.classification_authority,
            "asset_type_source": metadata.asset_type_source,
            "status": "PASS" if metadata.asset_type == "ETF" and metadata.is_trusted_for_production else "FAIL",
        }
        rows.append(row)
    return rows


def validate_raw_coverage(
    raw_store: KrxRawStockStore,
    tickers: Iterable[str],
    target_end: str,
    *,
    lookback_start: str | None = None,
) -> dict[str, Any]:
    """Read-only validation of recent whole-market ETF raw snapshots."""

    normalized = tuple(str(ticker).zfill(6) for ticker in tickers)
    target_end = _date(target_end)
    lookback_start = lookback_start or _date(pd.Timestamp(target_end) - pd.DateOffset(years=1))
    manifest = [
        row for row in raw_store.list_manifest("ETF")
        if row["status"] == "COMPLETE" and lookback_start <= str(row["date"]) <= target_end
    ]
    seen = {ticker: set() for ticker in normalized}
    for row in manifest:
        path = _raw_partition_path(raw_store, row)
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=["ticker", "close"])
        present = set(frame.loc[frame["ticker"].astype(str).isin(normalized), "ticker"].astype(str))
        for ticker in present:
            seen[ticker].add(str(row["date"]))

    target_row = next((row for row in manifest if str(row["date"]) == target_end), None)
    latest_present: dict[str, bool] = {ticker: False for ticker in normalized}
    target_snapshot_valid = False
    if target_row is not None:
        target_snapshot_valid = raw_store.verify_snapshot("ETF", target_end).get("valid", False)
        target_frame = pd.read_parquet(_raw_partition_path(raw_store, target_row), columns=["ticker"])
        target_tickers = set(target_frame["ticker"].astype(str))
        latest_present = {ticker: ticker in target_tickers for ticker in normalized}

    coverage = {ticker: len(seen[ticker]) for ticker in normalized}
    passed = bool(manifest) and target_snapshot_valid and all(latest_present.values()) and all(coverage.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "lookback_start": lookback_start,
        "target_end": target_end,
        "complete_session_count": len(manifest),
        "coverage_sessions": coverage,
        "target_end_present": latest_present,
        "target_snapshot_valid": target_snapshot_valid,
    }


def validate_adjusted_frame(
    ticker: str,
    frame: pd.DataFrame,
    *,
    requested_start: str,
    target_end: str,
) -> list[str]:
    """Validate one Naver adjusted frame before it reaches the durable store."""

    errors: list[str] = []
    if frame.empty:
        return ["EMPTY_ADJUSTED_AUTHORITY"]
    if tuple(frame.columns) != ("open", "high", "low", "close"):
        errors.append("ADJUSTED_COLUMNS_INVALID")
    index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce"))
    if index.isna().any():
        errors.append("ADJUSTED_DATE_INVALID")
    if index.has_duplicates:
        errors.append("ADJUSTED_DATE_DUPLICATE")
    if not index.is_monotonic_increasing:
        errors.append("ADJUSTED_DATE_NOT_SORTED")
    if not frame.index.empty:
        if index.min() > pd.Timestamp(requested_start) + pd.DateOffset(days=1):
            errors.append("ADJUSTED_START_COVERAGE_INSUFFICIENT")
        if _date(index.max()) != _date(target_end):
            errors.append("ADJUSTED_TARGET_END_MISMATCH")
    if len(frame) <= 250:
        errors.append("ADJUSTED_HISTORY_TOO_SHORT")
    values = frame.loc[:, [column for column in ("open", "high", "low", "close") if column in frame.columns]]
    if not values.empty and not np.isfinite(values.to_numpy(dtype=float)).all():
        errors.append("ADJUSTED_OHLC_NOT_FINITE")
    if "close" in frame and (frame["close"] <= 0).any():
        errors.append("ADJUSTED_CLOSE_NOT_POSITIVE")
    return errors


def fetch_missing_adjusted(
    provider: Any,
    adjusted_store: Any,
    tickers: Iterable[str],
    *,
    requested_start: str,
    target_end: str,
) -> dict[str, Any]:
    """Fetch only absent tickers and persist only frames that pass validation."""

    existing: list[str] = []
    fetched: list[str] = []
    failures: list[dict[str, Any]] = []
    for ticker in tickers:
        if adjusted_store.exists(ticker):
            existing.append(ticker)
            continue
        try:
            frame = provider.load_daily(ticker, requested_start, target_end)
            errors = validate_adjusted_frame(
                ticker,
                frame,
                requested_start=requested_start,
                target_end=target_end,
            )
            if errors:
                raise RuntimeError(",".join(errors))
            adjusted_store.save_full(
                ticker,
                frame,
                metadata_context={"requested_start": requested_start, "requested_end": target_end},
            )
            stored = adjusted_store.load_metadata(ticker)
            if _date(stored["actual_date_max"]) != _date(target_end):
                raise RuntimeError("STORED_TARGET_END_MISMATCH")
            fetched.append(ticker)
        except Exception as exc:  # noqa: BLE001 - bounded per-ticker report
            failures.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)[:500]})
    return {"existing": existing, "fetched": fetched, "failures": failures}


def validate_repository_v2(
    repo_root: Path,
    tickers: Iterable[str],
    *,
    target_end: str,
) -> dict[str, Any]:
    """Validate the approved Repository V2 join for the recent 12-month window."""

    normalized = tuple(str(ticker).zfill(6) for ticker in tickers)
    lookback_start = _date(pd.Timestamp(target_end) - pd.DateOffset(years=1))
    repository = build_repository_v2(repo_root, end=target_end)
    rows: dict[str, Any] = {}
    for ticker in normalized:
        try:
            frame = repository.get_daily(ticker, lookback_start, target_end)
            first = _date(frame.index.min()) if not frame.empty else None
            last = _date(frame.index.max()) if not frame.empty else None
            passed = (
                not frame.empty
                and {"close", "volume", "trading_value"}.issubset(frame.columns)
                and first is not None
                and first <= lookback_start
                and last == target_end
            )
            rows[ticker] = {"status": "PASS" if passed else "FAIL", "row_count": len(frame), "first_date": first, "last_date": last}
        except Exception as exc:  # noqa: BLE001 - bounded per-ticker report
            rows[ticker] = {"status": "FAIL", "error_type": type(exc).__name__, "message": str(exc)[:500]}
    passed_count = sum(row["status"] == "PASS" for row in rows.values())
    return {
        "status": "PASS" if passed_count == len(normalized) else "FAIL",
        "lookback_start": lookback_start,
        "target_end": target_end,
        "pass_count": passed_count,
        "rows": rows,
    }


def write_artifact(payload: dict[str, Any], path: Path = ARTIFACT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(*, repo_root: Path = ROOT, execute_live: bool = False) -> dict[str, Any]:
    adjusted_store = AdjustedPriceStore(repo_root / "data/market/adjusted/stocks")
    raw_store = KrxRawStockStore(repo_root / "data/market/raw/krx_stocks/v01")
    target_end = determine_target_end(adjusted_store)
    metadata_rows = validate_metadata(repo_root, as_of=target_end)
    raw_coverage = validate_raw_coverage(raw_store, NEW_ETF_TICKERS, target_end)
    existing_count = sum(adjusted_store.exists(ticker) for ticker in NEW_ETF_TICKERS)
    payload: dict[str, Any] = {
        "status": "PREFLIGHT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_tickers": list(NEW_ETF_TICKERS),
        "target_end": target_end,
        "metadata_pass_count": sum(row["status"] == "PASS" for row in metadata_rows),
        "raw_coverage_pass_count": len(NEW_ETF_TICKERS) if raw_coverage["status"] == "PASS" else 0,
        "adjusted_existing_count": existing_count,
        "adjusted_fetched_count": 0,
        "adjusted_pass_count": 0,
        "repository_v2_pass_count": 0,
        "metadata": metadata_rows,
        "raw_coverage": raw_coverage,
        "failures": [],
    }
    if payload["metadata_pass_count"] != len(NEW_ETF_TICKERS):
        payload["status"] = "BLOCKED_BY_ETF_METADATA"
        write_artifact(payload, repo_root / ARTIFACT_PATH.relative_to(ROOT))
        return payload
    if raw_coverage["status"] != "PASS":
        payload["status"] = "BLOCKED_BY_ETF_RAW_COVERAGE"
        write_artifact(payload, repo_root / ARTIFACT_PATH.relative_to(ROOT))
        return payload
    if not execute_live:
        payload["status"] = "PREFLIGHT_PASS"
        write_artifact(payload, repo_root / ARTIFACT_PATH.relative_to(ROOT))
        return payload

    provider = NaverDirectAdjustedPriceDataProvider(timeout_seconds=10.0)
    fetch_result = fetch_missing_adjusted(
        provider,
        adjusted_store,
        NEW_ETF_TICKERS,
        requested_start=REQUESTED_START,
        target_end=target_end,
    )
    payload["adjusted_fetched_count"] = len(fetch_result["fetched"])
    payload["adjusted_existing_count"] = len(fetch_result["existing"])
    payload["failures"].extend(fetch_result["failures"])
    payload["provider_audit"] = provider.call_audit()
    if fetch_result["failures"]:
        payload["status"] = "BLOCKED_BY_ETF_ADJUSTED_FETCH"
        write_artifact(payload, repo_root / ARTIFACT_PATH.relative_to(ROOT))
        return payload

    repository_result = validate_repository_v2(repo_root, NEW_ETF_TICKERS, target_end=target_end)
    payload["repository_v2_pass_count"] = repository_result["pass_count"]
    payload["repository_v2"] = repository_result
    payload["adjusted_pass_count"] = len(NEW_ETF_TICKERS)
    payload["status"] = "PASS" if repository_result["status"] == "PASS" else "BLOCKED_BY_ETF_REPOSITORY_V2_COVERAGE"
    write_artifact(payload, repo_root / ARTIFACT_PATH.relative_to(ROOT))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args(argv)
    result = run(execute_live=args.execute_live)
    print(json.dumps({"status": result["status"], "target_end": result["target_end"], "requested_count": len(result["requested_tickers"])}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"PREFLIGHT_PASS", "PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
