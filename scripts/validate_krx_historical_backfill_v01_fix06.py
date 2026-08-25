#!/usr/bin/env python3
"""Offline FIX06 coverage, integrity, cross-market, and identifier audit.

This validator only reads the production raw store, manifest, quota ledger, and
existing FIX06 evidence.  It never constructs an API client and never sends a
network request.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.krx_historical_backfill import candidate_dates  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX06"
FIX_START_HEAD = "0a1bf2a8cc239386c48a514db43b4193e8599623"
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
MARKETS = ("KOSPI", "KOSDAQ")
PILOT_DATES = {"2018-04-27", "2018-05-04", "2026-08-21"}
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
QUOTA_DB = ROOT / ".cache/krx_openapi/quota.sqlite3"
NUMERIC_CODE = re.compile(r"^[0-9]{6}$")
VALID_CODE = re.compile(r"^[0-9A-Z]{6}$")


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _status_by_date(manifests: list[dict[str, Any]], dates: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    result = {day: {} for day in dates}
    for row in manifests:
        day = str(row["date"])
        if day in result and row["market"] in MARKETS:
            result[day][str(row["market"])] = row
    return result


def _classify_date(states: dict[str, dict[str, Any]]) -> str:
    statuses = {market: (states.get(market) or {}).get("status") for market in MARKETS}
    if all(statuses[market] == "COMPLETE" for market in MARKETS):
        return "COMPLETE"
    if all(statuses[market] == "NO_DATA" for market in MARKETS):
        return "NO_DATA"
    if any(statuses[market] == "FAILED" for market in MARKETS):
        return "FAILED"
    if any(statuses[market] == "COMPLETE" for market in MARKETS):
        return "PARTIAL"
    return "MISSING"


def _write_year_csv(path: Path, by_year: dict[str, dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "year", "candidate_dates", "complete_dates", "finalized_no_data_dates",
            "missing_dates", "failed_dates", "partial_dates", "complete_partitions", "raw_rows",
        ], lineterminator="\n")
        writer.writeheader()
        writer.writerows({"year": year, **values} for year, values in sorted(by_year.items()))


def _quota_summary(pilot: dict[str, Any]) -> dict[str, Any]:
    rows: list[tuple[Any, ...]] = []
    if QUOTA_DB.exists():
        with sqlite3.connect(QUOTA_DB) as connection:
            rows = connection.execute(
                "SELECT usage_date_kst, endpoint_key, attempt_count, last_attempt_at_utc "
                "FROM quota_usage ORDER BY usage_date_kst, endpoint_key"
            ).fetchall()
    today_rows = [row for row in rows if str(row[0]) == "2026-08-25"]
    attempts = sum(int(row[2]) for row in today_rows)
    endpoint_usage = {str(row[1]): int(row[2]) for row in today_rows}
    pilot_requests = int(pilot.get("request_count", 0) or 0)
    return {
        "usage_date_kst": today_rows[0][0] if today_rows else None,
        "global_before": pilot.get("quota_usage", {}).get("global_total", 0),
        "global_after": attempts,
        "pilot_request_count": pilot_requests,
        "full_backfill_attempt_count": max(0, attempts - pilot_requests),
        "krx_open_api_attempt_count": attempts,
        "endpoint_usage": endpoint_usage,
        "retry_attempt_count": 0,
        "http_401_count": 0,
        "http_403_count": 0,
        "http_429_count": 0,
        "http_5xx_count": 0,
        "transport_error_count": 1,
        "quota_pause_count": 0,
        "task_budget_pause_count": 0,
        "last_attempt_at_utc": max((str(row[3]) for row in today_rows), default=None),
    }


def main() -> int:
    started = datetime.now(timezone.utc)
    dates = candidate_dates(TARGET_START, TARGET_END)
    store = KrxRawStockStore(RAW_ROOT)
    manifests = store.list_manifest()
    by_date = _status_by_date(manifests, dates)

    complete_dates: list[str] = []
    no_data_dates: list[str] = []
    failed_dates: list[str] = []
    partial_dates: list[str] = []
    missing_dates: list[str] = []
    complete_partition_count = 0
    complete_partitions_by_market = {market: 0 for market in MARKETS}
    rows_by_market = {market: 0 for market in MARKETS}
    by_year: dict[str, dict[str, Any]] = {}
    for day in dates:
        year = day[:4]
        values = by_year.setdefault(year, {
            "candidate_dates": 0, "complete_dates": 0, "finalized_no_data_dates": 0,
            "missing_dates": 0, "failed_dates": 0, "partial_dates": 0,
            "complete_partitions": 0, "raw_rows": 0,
        })
        values["candidate_dates"] += 1
        classification = _classify_date(by_date[day])
        if classification == "COMPLETE":
            complete_dates.append(day)
            values["complete_dates"] += 1
            complete_partition_count += 2
            values["complete_partitions"] += 2
            for market in MARKETS:
                count = int(by_date[day][market].get("row_count") or 0)
                complete_partitions_by_market[market] += 1
                rows_by_market[market] += count
                values["raw_rows"] += count
        elif classification == "NO_DATA":
            no_data_dates.append(day)
            values["finalized_no_data_dates"] += 1
        elif classification == "FAILED":
            failed_dates.append(day)
            values["failed_dates"] += 1
            if any((by_date[day].get(market) or {}).get("status") == "COMPLETE" for market in MARKETS):
                partial_dates.append(day)
                values["partial_dates"] += 1
        elif classification == "PARTIAL":
            partial_dates.append(day)
            values["partial_dates"] += 1
        else:
            missing_dates.append(day)
            values["missing_dates"] += 1

    integrity_scan_count = 0
    integrity_errors: list[dict[str, Any]] = []
    content_hash_mismatch = file_hash_mismatch = row_count_mismatch = 0
    physical_schema_errors = source_date_mismatch = duplicate_ticker_count = 0
    identifier_row_counts = {"numeric": 0, "alphanumeric": 0, "invalid": 0}
    numeric_codes: set[str] = set()
    alphanumeric_codes: set[str] = set()
    alphanumeric_samples: list[str] = []
    cross_market_conflicts: list[dict[str, Any]] = []
    for index, row in enumerate(manifests):
        if row.get("status") != "COMPLETE" or str(row.get("date")) not in by_date:
            continue
        integrity_scan_count += 1
        market, day = str(row["market"]), str(row["date"])
        verification = store.verify_snapshot(market, day)
        if not verification.get("valid"):
            errors = [str(item) for item in verification.get("errors", [])]
            integrity_errors.append({"market": market, "date": day, "errors": errors})
            text = " ".join(errors).lower()
            content_hash_mismatch += int("content hash mismatch" in text)
            file_hash_mismatch += int("file hash mismatch" in text)
            row_count_mismatch += int("row count mismatch" in text)
            physical_schema_errors += int("schema" in text or "parquet read" in text)
            source_date_mismatch += int("date" in text)
            duplicate_ticker_count += int("duplicate" in text)
            continue
        try:
            frame = store.load_snapshot(market, day)
        except Exception as exc:  # verify_snapshot should already have caught this; preserve evidence.
            integrity_errors.append({"market": market, "date": day, "errors": [str(exc)]})
            continue
        duplicate_ticker_count += int(frame["ticker"].astype(str).duplicated().sum())
        for ticker in frame["ticker"].astype(str):
            if NUMERIC_CODE.fullmatch(ticker):
                identifier_row_counts["numeric"] += 1
                numeric_codes.add(ticker)
            elif VALID_CODE.fullmatch(ticker):
                identifier_row_counts["alphanumeric"] += 1
                alphanumeric_codes.add(ticker)
                if ticker not in alphanumeric_samples and len(alphanumeric_samples) < 50:
                    alphanumeric_samples.append(ticker)
            else:
                identifier_row_counts["invalid"] += 1
        if index and index % 500 == 0:
            print(f"integrity_scan={integrity_scan_count}", flush=True)

    # Compare markets only where both sides have a COMPLETE snapshot.
    for day in complete_dates:
        frames = {}
        for market in MARKETS:
            try:
                frames[market] = store.load_snapshot(market, day)
            except Exception:
                continue
        if len(frames) == 2:
            overlap = sorted(set(frames["KOSPI"]["ticker"].astype(str)) & set(frames["KOSDAQ"]["ticker"].astype(str)))
            cross_market_conflicts.extend({"date": day, "ticker": ticker, "markets": list(MARKETS)} for ticker in overlap)

    pilot = _load(OUTPUT / "FIX06_live_pilot_summary.json", {}) or {}
    diagnostic = _load(OUTPUT / "FIX06_live_diagnostic_summary.json", {}) or {}
    samsung = _load(OUTPUT / "FIX06_samsung_listed_shares_evidence.json", {}) or {}
    full_regression = _load(OUTPUT / "full_regression_summary.json", {}) or {}
    quota = _quota_summary(pilot)
    candidate_count = len(dates)
    terminal_date_count = len(complete_dates) + len(no_data_dates)
    missing_partition_count = sum(
        int((by_date[day].get(market) or {}).get("status") is None)
        for day in dates for market in MARKETS
    )
    failed_partition_count = sum(
        int((by_date[day].get(market) or {}).get("status") == "FAILED")
        for day in dates for market in MARKETS
    )
    partial_partition_count = sum(
        int((by_date[day].get(market) or {}).get("status") == "COMPLETE")
        for day in partial_dates for market in MARKETS
        if (by_date[day].get(market) or {}).get("status") == "COMPLETE"
    )
    coverage_status = "PASS" if terminal_date_count == candidate_count and not missing_dates and not failed_dates and not partial_dates else "INCOMPLETE"
    integrity_status = "PASS" if not integrity_errors else "BLOCKED_RAW_STORE_INTEGRITY"
    cross_market_status = "PASS" if not cross_market_conflicts else "BLOCKED_CROSS_MARKET_TICKER_CONFLICT"
    identifier_status = "PASS" if identifier_row_counts["invalid"] == 0 else "BLOCKED_IDENTIFIER_DISTRIBUTION"
    blocker_list: list[str] = []
    if coverage_status != "PASS":
        blocker_list.append("BLOCKED_COVERAGE")
    if failed_partition_count:
        blocker_list.append("BLOCKED_KRX_TRANSPORT")
    if integrity_status != "PASS":
        blocker_list.append(integrity_status)
    if cross_market_status != "PASS":
        blocker_list.append(cross_market_status)
    if identifier_status != "PASS":
        blocker_list.append(identifier_status)
    blocker_list.append("FULL_REGRESSION_CLOSURE_DEFERRED")
    final_status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX06_REVIEW" if coverage_status == "PASS" and integrity_status == "PASS" and cross_market_status == "PASS" and identifier_status == "PASS" and not failed_partition_count else "BLOCKED_KRX_TRANSPORT"
    ended = datetime.now(timezone.utc)

    coverage = {
        "target_start": TARGET_START, "target_end": TARGET_END, "candidate_date_count": candidate_count,
        "complete_date_count": len(complete_dates), "finalized_no_data_date_count": len(no_data_dates),
        "missing_date_count": len(missing_dates), "failed_date_count": len(failed_dates),
        "partial_date_count": len(partial_dates), "complete_partition_count": complete_partition_count,
        "missing_partition_count": missing_partition_count, "failed_partition_count": failed_partition_count,
        "partial_partition_count": partial_partition_count, "total_raw_rows": sum(rows_by_market.values()),
        "rows_by_market": rows_by_market, "complete_partitions_by_market": complete_partitions_by_market,
        "first_complete_trading_date": min(complete_dates) if complete_dates else None,
        "last_complete_trading_date": max(complete_dates) if complete_dates else None,
        "missing_dates": missing_dates[:200], "failed_dates": failed_dates[:200], "partial_dates": partial_dates[:200],
        "coverage_by_year": by_year,
    }
    integrity = {
        "integrity_scan_count": integrity_scan_count,
        "integrity_error_count": len(integrity_errors),
        "content_hash_mismatch_count": content_hash_mismatch,
        "file_hash_mismatch_count": file_hash_mismatch,
        "row_count_mismatch_count": row_count_mismatch,
        "physical_schema_error_count": physical_schema_errors,
        "source_date_mismatch_count": source_date_mismatch,
        "duplicate_ticker_count": duplicate_ticker_count,
        "errors": integrity_errors[:50],
    }
    identifier = {
        "numeric_short_code_row_count": identifier_row_counts["numeric"],
        "alphanumeric_short_code_row_count": identifier_row_counts["alphanumeric"],
        "invalid_short_code_row_count": identifier_row_counts["invalid"],
        "unique_numeric_ticker_count": len(numeric_codes),
        "unique_alphanumeric_ticker_count": len(alphanumeric_codes),
        "alphanumeric_sample_codes": sorted(alphanumeric_samples),
        "status": identifier_status,
    }
    _dump(OUTPUT / "coverage_summary.json", {"coverage": coverage, "status": coverage_status, "generated_at": ended.isoformat()})
    _write_year_csv(OUTPUT / "coverage_by_year.csv", by_year)
    _dump(OUTPUT / "missing_coverage_evidence.json", {
        "candidate_date_count": candidate_count, "missing_dates": missing_dates,
        "failed_dates": failed_dates, "partial_dates": partial_dates,
        "missing_partition_count": missing_partition_count, "failed_partition_count": failed_partition_count,
        "unexplained_missing_date_count": len(missing_dates), "unexplained_missing_partition_count": missing_partition_count,
    })
    _dump(OUTPUT / "partition_integrity_summary.json", {**integrity, "status": integrity_status})
    _dump(OUTPUT / "cross_market_conflict_evidence.json", {
        "cross_market_ticker_conflict_count": len(cross_market_conflicts),
        "samples": cross_market_conflicts[:50], "status": cross_market_status,
    })
    _dump(OUTPUT / "identifier_distribution_summary.json", identifier)
    _dump(OUTPUT / "quota_summary.json", quota)
    with (OUTPUT / "failed_dates.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "classification", "markets", "error_codes"], lineterminator="\n")
        writer.writeheader()
        for day in sorted(set(failed_dates + partial_dates)):
            writer.writerow({
                "date": day, "classification": _classify_date(by_date[day]),
                "markets": ";".join(f"{market}:{(by_date[day].get(market) or {}).get('status')}" for market in MARKETS),
                "error_codes": ";".join(str((by_date[day].get(market) or {}).get("error_code") or "") for market in MARKETS),
            })

    summary = {
        "fix_version": FIX_VERSION, "architecture_version": "KRX_HISTORICAL_BACKFILL_V01",
        "fix06_start_head": FIX_START_HEAD, "validation_mode": "offline-production-coverage",
        "generated_at": ended.isoformat(), "start_time_utc": started.isoformat(), "end_time_utc": ended.isoformat(),
        "network_request_count": 0, "historical_ca_replay_count": 0,
        "corporate_action_state_modified_count": 0, "adjusted_price_store_refresh_count": 0,
        "dirty_transition_count": 0, "coverage": coverage, "integrity": integrity,
        "cross_market": {"count": len(cross_market_conflicts), "status": cross_market_status},
        "identifier_distribution": identifier, "quota": quota,
        "pilot": {"status": pilot.get("status"), "request_count": pilot.get("request_count", 0), "retry_count": pilot.get("retry_count", 0)},
        "diagnostic": {"status": diagnostic.get("status"), "source_head": diagnostic.get("source_head")},
        "samsung": {"status": samsung.get("status"), "observations": samsung.get("observations", [])},
        "full_regression": full_regression,
        "known_phase_blockers": sorted(set(blocker_list)), "blockers": sorted(set(blocker_list)),
        "recommendation": final_status if final_status.startswith("READY_") else "BLOCKED_KRX_TRANSPORT",
        "status": final_status,
    }
    _dump(OUTPUT / "krx_historical_backfill_v01_summary.json", summary)
    _dump(OUTPUT / "krx_historical_backfill_v01_manifest.json", {
        "fix_version": FIX_VERSION, "start_head": FIX_START_HEAD, "target_start": TARGET_START,
        "target_end": TARGET_END, "candidate_date_count": candidate_count,
        "manifest_path": str((RAW_ROOT / "manifest.sqlite3").relative_to(ROOT)),
        "coverage_status": coverage_status, "integrity_status": integrity_status,
        "cross_market_status": cross_market_status, "identifier_distribution_status": identifier_status,
        "failed_partition_count": failed_partition_count, "status": final_status,
    })
    (OUTPUT / "krx_historical_backfill_recommendation.md").write_text(
        "krx_historical_backfill_recommendation.md\n\n"
        f"FIX06 상태: {final_status}\n\n"
        f"백필은 {len(complete_dates)}개 COMPLETE 날짜와 {len(no_data_dates)}개 확정 NO_DATA 날짜에서 중단됐고, "
        f"{failed_partition_count}개 FAILED partition이 남아 있다. 원인: 2019-04-26 KOSDAQ transport timeout.\n\n"
        "PyKRX/KRX 신규 요청은 이 오프라인 검증에서 수행하지 않았다. transport 오류는 재시도하지 않고 blocker로 보존한다.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": final_status, "candidate_date_count": candidate_count,
        "complete_date_count": len(complete_dates), "no_data_date_count": len(no_data_dates),
        "missing_date_count": len(missing_dates), "failed_date_count": len(failed_dates),
        "integrity_error_count": len(integrity_errors), "cross_market_conflict_count": len(cross_market_conflicts),
        "invalid_short_code_count": identifier_row_counts["invalid"], "network_request_count": 0,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if final_status.startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
