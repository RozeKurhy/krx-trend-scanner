#!/usr/bin/env python3
"""Rolling production refresh for the two KRX representative market indexes.

This is intentionally narrower than ``migrate_market_index_krx_v01.py``.  It
derives the incremental date set from the paired COMPLETE stock raw manifest,
fetches only missing dates through the existing KRX Open API market-index
builder, and atomically republishes the existing IndexStore family.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import (
    DEFAULT_INDEX_STORE_ROOT,
    INDEX_STORE_COLUMNS,
    IndexStore,
    MARKET_INDEX_FAMILY,
    file_sha256,
    normalize_index_frame,
)
from trend_scanner.data.krx_market_index import (
    FETCH_MODE,
    KRX_MARKET_INDEX_MAP,
    MAPPING_CONTRACT_VERSION,
    KrxMarketIndexBuilder,
    mapping_contract_sha256,
)
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore


ROOT = Path(__file__).resolve().parents[1]
MARKET_INDEX_CODES = frozenset({"1001", "2001"})
RAW_MARKETS = ("KOSPI", "KOSDAQ")


class MarketIndexRollingRefreshError(MarketDataError):
    """Stable fail-closed error for the rolling market-index path."""

    def __init__(self, error_code: str, message: str = "") -> None:
        self.error_code = str(error_code)
        detail = f": {message}" if message else ""
        super().__init__(f"{self.error_code}{detail}")


def _date_text(value: str | date) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketIndexRollingRefreshError("BLOCKED_INVALID_DATE", repr(value)) from exc


def _normalize_dates(values: Iterable[str | date]) -> list[str]:
    return sorted({_date_text(value) for value in values})


def validate_market_index_frame(
    frame: pd.DataFrame,
    *,
    expected_dates: Iterable[str | date] | None = None,
) -> pd.DataFrame:
    """Validate the complete two-code MARKET_INDEX contract."""

    try:
        normalized = normalize_index_frame(frame, MARKET_INDEX_FAMILY)
    except Exception as exc:
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_FRAME", str(exc)) from exc

    if normalized.empty:
        if expected_dates and _normalize_dates(expected_dates):
            raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_DATE_COVERAGE")
        return normalized

    if not set(normalized["index_code"].astype(str)).issubset(MARKET_INDEX_CODES):
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_CODE_CONTRACT")

    duplicate_count = int(normalized.duplicated(["date", "family", "index_code"]).sum())
    if duplicate_count:
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_DUPLICATE_PAIR")

    date_code_sets = normalized.groupby("date", sort=True)["index_code"].agg(lambda values: set(values.astype(str)))
    incomplete_dates = [str(day) for day, codes in date_code_sets.items() if codes != MARKET_INDEX_CODES]
    if incomplete_dates:
        raise MarketIndexRollingRefreshError(
            "BLOCKED_MARKET_INDEX_INCOMPLETE_PAIR",
            ",".join(incomplete_dates),
        )

    for code, contract in KRX_MARKET_INDEX_MAP.items():
        rows = normalized.loc[normalized["index_code"].astype(str) == code]
        if rows.empty or not rows["source_index_class"].eq(contract["source_index_class"]).all() or not rows["index_name"].eq(contract["source_index_name"]).all():
            raise MarketIndexRollingRefreshError(
                "BLOCKED_MARKET_INDEX_MAPPING_IDENTITY",
                f"index_code={code}",
            )

    if expected_dates is not None:
        expected = set(_normalize_dates(expected_dates))
        observed = set(normalized["date"].astype(str))
        if observed != expected:
            raise MarketIndexRollingRefreshError(
                "BLOCKED_MARKET_INDEX_DATE_COVERAGE",
                f"expected={sorted(expected)} observed={sorted(observed)}",
            )
    return normalized


def derive_incremental_trading_dates(
    raw_store: Any,
    boundary: str | date,
    target_as_of: str | date,
    *,
    existing_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Derive missing dates from paired KOSPI/KOSDAQ COMPLETE manifest rows."""

    boundary_text = _date_text(boundary)
    target_text = _date_text(target_as_of)
    if target_text < boundary_text:
        raise MarketIndexRollingRefreshError("BLOCKED_TARGET_BEFORE_BOUNDARY")

    existing_dates: set[str] = set()
    if existing_frame is not None:
        validated_existing = validate_market_index_frame(existing_frame)
        existing_dates = set(validated_existing["date"].astype(str))

    states: dict[str, dict[str, str]] = {}
    for row in raw_store.list_manifest():
        market = str(row.get("market", "")).strip().upper()
        if market not in RAW_MARKETS:
            continue
        day = _date_text(str(row.get("date", "")))
        if boundary_text < day <= target_text:
            states.setdefault(day, {})[market] = str(row.get("status", "")).strip().upper()

    complete_dates: list[str] = []
    no_data_dates: list[str] = []
    for day in sorted(states):
        pair = states[day]
        statuses = (pair.get("KOSPI"), pair.get("KOSDAQ"))
        if statuses == ("COMPLETE", "COMPLETE"):
            complete_dates.append(day)
        elif statuses == ("NO_DATA", "NO_DATA"):
            no_data_dates.append(day)
        else:
            raise MarketIndexRollingRefreshError(
                "BLOCKED_RAW_MANIFEST_INCOMPLETE_PAIR",
                f"date={day} statuses={pair}",
            )

    missing_dates = [day for day in complete_dates if day not in existing_dates]
    return {
        "boundary": boundary_text,
        "target_as_of": target_text,
        "candidate_complete_dates": complete_dates,
        "already_present_dates": [day for day in complete_dates if day in existing_dates],
        "no_data_dates": no_data_dates,
        "missing_dates": missing_dates,
        "first_missing_date": missing_dates[0] if missing_dates else None,
        "last_missing_date": missing_dates[-1] if missing_dates else None,
        "missing_date_count": len(missing_dates),
    }


def inspect_production_index(store: IndexStore) -> dict[str, Any]:
    """Read and summarize the current production family without network calls."""

    frame = validate_market_index_frame(store.load_family(MARKET_INDEX_FAMILY))
    parquet_path = store.root / "market_index.parquet"
    per_code_last = {
        code: str(frame.loc[frame["index_code"].astype(str) == code, "date"].max())
        for code in sorted(MARKET_INDEX_CODES)
    }
    per_date = frame.groupby("date")["index_code"].agg(lambda values: set(values.astype(str)))
    missing_pair_count = int(sum(codes != MARKET_INDEX_CODES for codes in per_date))
    return {
        "path": str(parquet_path.resolve()),
        "first_date": str(frame["date"].min()),
        "last_date": str(frame["date"].max()),
        "row_count": int(len(frame)),
        "per_code_last": per_code_last,
        "duplicate_count": int(frame.duplicated(["date", "family", "index_code"]).sum()),
        "missing_pair_count": missing_pair_count,
        "sha256": file_sha256(parquet_path),
        "frame": frame,
    }


def _historical_signature(frame: pd.DataFrame, boundary: str) -> str:
    historical = frame.loc[frame["date"].astype(str) <= boundary, list(INDEX_STORE_COLUMNS)].copy()
    historical = historical.sort_values(["date", "index_code"], kind="mergesort").reset_index(drop=True)
    historical["date"] = historical["date"].astype(str)
    return __import__("hashlib").sha256(historical.to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()


def append_market_index_rows(
    current_frame: pd.DataFrame,
    increment_frame: pd.DataFrame,
    *,
    expected_dates: Iterable[str | date],
) -> pd.DataFrame:
    """Append one complete, non-overlapping increment and revalidate all rows."""

    current = validate_market_index_frame(current_frame)
    increment = validate_market_index_frame(increment_frame, expected_dates=expected_dates)
    current_keys = set(zip(current["date"].astype(str), current["index_code"].astype(str)))
    increment_keys = set(zip(increment["date"].astype(str), increment["index_code"].astype(str)))
    if current_keys & increment_keys:
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_DUPLICATE_PAIR")
    merged = pd.concat([current, increment], ignore_index=True)
    return validate_market_index_frame(merged)


def refresh_market_index(
    *,
    target_as_of: str | date,
    raw_store: KrxRawStockStore,
    index_store: IndexStore,
    builder: KrxMarketIndexBuilder | None = None,
) -> dict[str, Any]:
    """Perform one bounded rolling refresh and publish only a valid complete family."""

    pre_run = inspect_production_index(index_store)
    current = pre_run["frame"]
    boundaries = pre_run["per_code_last"]
    if len(set(boundaries.values())) != 1:
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_BOUNDARY_MISMATCH", str(boundaries))
    boundary = next(iter(boundaries.values()))
    plan = derive_incremental_trading_dates(raw_store, boundary, target_as_of, existing_frame=current)
    if not plan["missing_dates"]:
        return {
            "status": "IDEMPOTENT_NOOP",
            "pre_run": {key: value for key, value in pre_run.items() if key != "frame"},
            "plan": plan,
            "fetched_dates": [],
            "request_count": 0,
            "historical_signature_before": _historical_signature(current, boundary),
            "historical_signature_after": _historical_signature(current, boundary),
        }

    if builder is None:
        raise MarketIndexRollingRefreshError("BLOCKED_BUILDER_REQUIRED")
    increment, build_report = builder.build(plan["missing_dates"])
    validated_increment = validate_market_index_frame(increment, expected_dates=plan["missing_dates"])
    merged = append_market_index_rows(current, validated_increment, expected_dates=plan["missing_dates"])
    historical_before = _historical_signature(current, boundary)
    historical_after = _historical_signature(merged, boundary)
    if historical_before != historical_after:
        raise MarketIndexRollingRefreshError("BLOCKED_HISTORICAL_ROWS_CHANGED")

    metadata = index_store.save_family_full(
        MARKET_INDEX_FAMILY,
        merged,
        metadata_context={
            "published": True,
            "fetch_mode": FETCH_MODE,
            "mapping_contract_version": MAPPING_CONTRACT_VERSION,
            "mapping_contract_sha256": mapping_contract_sha256(),
            "rolling_refresh": True,
            "previous_boundary": boundary,
            "requested_end": _date_text(target_as_of),
            "fetched_date_count": len(plan["missing_dates"]),
        },
    )
    final = inspect_production_index(index_store)
    return {
        "status": "PROMOTED",
        "pre_run": {key: value for key, value in pre_run.items() if key != "frame"},
        "plan": plan,
        "fetched_dates": list(plan["missing_dates"]),
        "request_count": int(getattr(builder.client, "request_count", 0)),
        "build_report": build_report,
        "metadata": metadata,
        "final": {key: value for key, value in final.items() if key != "frame"},
        "historical_signature_before": historical_before,
        "historical_signature_after": historical_after,
    }


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
    """Load the existing key without ever printing it."""

    for value in (
        os.getenv("KRX_OPEN_API_AUTH_KEY", ""),
        _read_env_value(ROOT / ".env", "KRX_OPEN_API_AUTH_KEY"),
        _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY"),
    ):
        if value.strip():
            return value.strip()
    return ""


def build_plan(*, target_as_of: str, raw_root: Path, index_root: Path) -> dict[str, Any]:
    index_store = IndexStore(index_root)
    pre_run = inspect_production_index(index_store)
    boundaries = pre_run["per_code_last"]
    if len(set(boundaries.values())) != 1:
        raise MarketIndexRollingRefreshError("BLOCKED_MARKET_INDEX_BOUNDARY_MISMATCH", str(boundaries))
    plan = derive_incremental_trading_dates(
        KrxRawStockStore(raw_root),
        next(iter(boundaries.values())),
        target_as_of,
        existing_frame=pre_run["frame"],
    )
    return {
        "status": "PLAN",
        "pre_run": {key: value for key, value in pre_run.items() if key != "frame"},
        "plan": plan,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roll MARKET_INDEX production store to a target date")
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--execute-live", action="store_true", help="fetch and publish the incremental rows")
    parser.add_argument("--raw-root", type=Path, default=ROOT / DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--index-root", type=Path, default=ROOT / DEFAULT_INDEX_STORE_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    parser.add_argument("--max-requests", type=int, default=80)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(target_as_of=args.target_as_of, raw_root=args.raw_root, index_root=args.index_root)
        if not args.execute_live:
            print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2, default=str))
            return 0
        auth_key = load_auth_key()
        if not auth_key:
            print(json.dumps({"status": "BLOCKED_KRX_AUTH"}, ensure_ascii=False))
            return 1
        quota = LocalKrxOpenApiQuota(args.quota_db)
        client = KrxOpenApiClient(auth_key, max_requests=args.max_requests, max_transient_retries=0, quota=quota)
        result = refresh_market_index(
            target_as_of=args.target_as_of,
            raw_store=KrxRawStockStore(args.raw_root),
            index_store=IndexStore(args.index_root),
            builder=KrxMarketIndexBuilder(client=client),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
        return 0 if result["status"] in {"PROMOTED", "IDEMPOTENT_NOOP"} else 1
    except Exception as exc:  # noqa: BLE001 - retain redaction-safe error output
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
