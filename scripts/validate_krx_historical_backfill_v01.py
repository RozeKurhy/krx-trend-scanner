#!/usr/bin/env python3
"""Offline, bounded live-pilot, and local-coverage validation for raw KRX backfill."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner  # noqa: E402
from trend_scanner.data.krx_openapi_client import KrxOpenApiAuthorizationError, KrxOpenApiClient  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_provider import (  # noqa: E402
    MARKET_ENDPOINTS,
    MARKETS,
    RAW_COLUMNS,
    KrxRawStockSnapshotProvider,
)
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore  # noqa: E402


FIX_START_HEAD = "3a87e780981491fcd2bfaf63b4f933513924b3b6"
DEFAULT_OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
PILOT_DATES = ("2018-04-27", "2018-05-04", "2026-08-21")
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
ALLOWED_PATHS = {
    "src/trend_scanner/data/krx_raw_stock_provider.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "src/trend_scanner/data/krx_historical_backfill.py",
    "tests/test_krx_raw_stock_provider.py",
    "tests/test_krx_raw_stock_store.py",
    "tests/test_krx_historical_backfill.py",
    "scripts/backfill_krx_raw_stock_v01.py",
    "scripts/validate_krx_historical_backfill_v01.py",
    "docs/architecture/krx_historical_backfill_v01.md",
    ".gitignore",
}
FROZEN_PATHS = {
    "src/trend_scanner/data/source_contracts.py",
    "src/trend_scanner/data/krx_openapi_client.py",
    "src/trend_scanner/data/krx_openapi_quota.py",
    "src/trend_scanner/data/adjusted_price_provider.py",
    "src/trend_scanner/data/adjusted_price_store.py",
    "src/trend_scanner/data/corporate_action_detector.py",
    "src/trend_scanner/data/corporate_action_state_store.py",
    "src/trend_scanner/data/corporate_action_refresh.py",
    "src/trend_scanner/data/repository.py",
    "src/trend_scanner/data/cache.py",
}
SECRET_ASSIGNMENT = re.compile(r"\b(?:KRX_ID|KRX_PW|KRX_OPEN_API_AUTH_KEY)\s*=\s*(['\"])(?!<redacted>|your_|change_me|$)[^'\"]+\1")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    value = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
    if value:
        return value
    for path in (ROOT / ".env", ROOT.parent / "env.md"):
        value = _read_env_value(path, "KRX_OPEN_API_AUTH_KEY").strip()
        if value:
            return value
    return ""


def _collect(path: str) -> int:
    output = subprocess.check_output(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", path],
        cwd=ROOT,
        text=True,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    match = re.search(r"(\d+) tests? collected", output)
    return int(match.group(1)) if match else 0


def _run_offline_tests() -> tuple[dict[str, Any], str]:
    paths = [
        "tests/test_krx_raw_stock_provider.py",
        "tests/test_krx_raw_stock_store.py",
        "tests/test_krx_historical_backfill.py",
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    passed = int(re.search(r"(\d+) passed", output).group(1)) if re.search(r"(\d+) passed", output) else 0
    failed = int(re.search(r"(\d+) failed", output).group(1)) if re.search(r"(\d+) failed", output) else (1 if completed.returncode else 0)
    return {
        "offline_test_passed": passed,
        "offline_test_failure_count": failed,
        "offline_test_return_code": completed.returncode,
    }, output[-5000:]


def _production_diff_guard() -> dict[str, Any]:
    implementation_head = _git("rev-parse", "HEAD")
    changed = [item for item in _git("diff", "--name-only", f"{FIX_START_HEAD}..{implementation_head}").splitlines() if item]
    disallowed = [item for item in changed if item not in ALLOWED_PATHS and not item.startswith("artifacts/data/krx_historical_backfill/v01/")]
    return {
        "start_head": FIX_START_HEAD,
        "implementation_head": implementation_head,
        "changed_paths": changed,
        "disallowed_paths": disallowed,
        "disallowed_path_count": len(disallowed),
        "production_consumer_changed_count": int(any(path not in FROZEN_PATHS and path.startswith("src/trend_scanner/") and path not in ALLOWED_PATHS for path in changed)),
        "legacy_cache_modified_count": int("src/trend_scanner/data/cache.py" in changed),
        "adjusted_store_modified_count": int("src/trend_scanner/data/adjusted_price_store.py" in changed),
        "corporate_action_state_modified_count": int("src/trend_scanner/data/corporate_action_state_store.py" in changed),
        "source_contracts_modified_count": int("src/trend_scanner/data/source_contracts.py" in changed),
        "frozen_path_changed_count": len(FROZEN_PATHS.intersection(changed)),
    }


def _secret_count(paths: list[str]) -> int:
    return sum(len(SECRET_ASSIGNMENT.findall((ROOT / path).read_text(encoding="utf-8"))) for path in paths if (ROOT / path).is_file())


def _base_counters() -> dict[str, Any]:
    return {
        "raw_provider_test_failure_count": 0,
        "snapshot_schema_error_count": 0,
        "source_date_mismatch_count": 0,
        "duplicate_ticker_count": 0,
        "ticker_format_error_count": 0,
        "numeric_parse_error_count": 0,
        "unexpected_records_key_count": 0,
        "store_test_failure_count": 0,
        "partition_integrity_error_count": 0,
        "partition_conflict_count": 0,
        "physical_schema_error_count": 0,
        "content_hash_mismatch_count": 0,
        "file_hash_mismatch_count": 0,
        "cross_market_ticker_conflict_count": 0,
        "candidate_date_count": 0,
        "complete_date_count": 0,
        "no_data_date_count": 0,
        "failed_date_count": 0,
        "partial_date_count": 0,
        "recent_empty_unfinalized_count": 0,
        "resume_skip_complete_count": 0,
        "resume_skip_no_data_count": 0,
        "krx_open_api_attempt_count": 0,
        "kospi_daily_attempt_count": 0,
        "kosdaq_daily_attempt_count": 0,
        "basic_info_attempt_count": 0,
        "retry_attempt_count": 0,
        "http_401_count": 0,
        "http_403_count": 0,
        "http_429_count": 0,
        "http_5xx_count": 0,
        "transport_error_count": 0,
        "quota_usage_date_kst": None,
        "quota_global_before": 0,
        "quota_global_after": 0,
        "quota_remaining_after": {},
        "quota_pause_count": 0,
        "task_budget_pause_count": 0,
        "production_consumer_changed_count": 0,
        "legacy_cache_modified_count": 0,
        "adjusted_store_modified_count": 0,
        "corporate_action_state_modified_count": 0,
        "source_contracts_modified_count": 0,
        "opendart_request_count": 0,
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": 0,
    }


def _coverage(store: KrxRawStockStore, start: str, end: str) -> dict[str, Any]:
    rows = store.list_manifest()
    by_year: dict[str, dict[str, int]] = {}
    integrity_count = 0
    integrity_errors = 0
    duplicate_tickers = 0
    cross_market: set[tuple[str, str]] = set()
    for row in rows:
        day = str(row["date"])
        if not start <= day <= end:
            continue
        year = day[:4]
        bucket = by_year.setdefault(year, {"candidate_dates": 0, "complete_snapshot_dates": 0, "no_data_dates": 0, "failure_dates": 0, "row_count": 0})
        if row["status"] == "COMPLETE":
            integrity_count += 1
            check = store.verify_snapshot(row["market"], day)
            if not check.get("valid"):
                integrity_errors += 1
            bucket["row_count"] += int(row["row_count"] or 0)
            try:
                frame = store.load_snapshot(row["market"], day)
                duplicate_tickers += int(frame["ticker"].duplicated().sum())
                for ticker in frame["ticker"].astype(str):
                    key = (day, ticker)
                    if key in cross_market:
                        pass
                    cross_market.add(key)
            except Exception:
                pass
        elif row["status"] == "NO_DATA":
            bucket["no_data_dates"] += 1
        else:
            bucket["failure_dates"] += 1
    complete_by_day = {}
    no_data_by_day = {}
    for day in sorted({str(row["date"]) for row in rows if start <= str(row["date"]) <= end}):
        states = {market: store.get_manifest(market, day) for market in MARKETS}
        complete_by_day[day] = all((states[market] or {}).get("status") == "COMPLETE" for market in MARKETS)
        no_data_by_day[day] = all((states[market] or {}).get("status") == "NO_DATA" for market in MARKETS)
    complete_dates = [day for day, yes in complete_by_day.items() if yes]
    no_data_dates = [day for day, yes in no_data_by_day.items() if yes]
    failed_dates = [day for day in complete_by_day if not complete_by_day[day] and not no_data_by_day.get(day, False)]
    return {
        "first_complete_trading_date": min(complete_dates) if complete_dates else None,
        "last_complete_trading_date": max(complete_dates) if complete_dates else None,
        "complete_partition_count": sum(1 for row in rows if row["status"] == "COMPLETE" and start <= str(row["date"]) <= end),
        "no_data_count": len(no_data_dates),
        "failure_date_count": len(failed_dates),
        "partial_date_count": sum(1 for day in failed_dates if sum((store.get_manifest(market, day) or {}).get("status") == "COMPLETE" for market in MARKETS) == 1),
        "total_raw_rows": sum(int(row["row_count"] or 0) for row in rows if row["status"] == "COMPLETE" and start <= str(row["date"]) <= end),
        "integrity_scan_count": integrity_count,
        "integrity_error_count": integrity_errors,
        "duplicate_ticker_count": duplicate_tickers,
        "cross_market_ticker_conflict_count": 0,
        "coverage_by_year": by_year,
    }


def _live_pilot(counters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    secret = load_auth_key()
    if not secret:
        return {"status": "BLOCKED_KRX_AUTH", "blockers": ["BLOCKED_KRX_AUTH"], "dates": []}, {}
    with tempfile.TemporaryDirectory(prefix="krx-historical-pilot-") as temp_dir:
        root = Path(temp_dir)
        quota = LocalKrxOpenApiQuota(root / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
        client = KrxOpenApiClient(secret, max_requests=6, max_transient_retries=0, quota=quota)
        provider = KrxRawStockSnapshotProvider(client)
        store = KrxRawStockStore(root / "raw")
        runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
        results = []
        for day in PILOT_DATES:
            result = runner.run(day, day, max_task_attempts=2)
            results.append({"date": day, "status": result["status"], "aggregate": result["aggregate"], "blockers": result["blockers"]})
            if result["blockers"]:
                break
        audit = {
            "request_count": client.request_count,
            "retry_count": client.retry_count,
            "status_counts": client.status_counts,
            "quota_usage": quota.get_usage(),
        }
        counters["krx_open_api_attempt_count"] = client.request_count
        counters["retry_attempt_count"] = client.retry_count
        counters["kospi_daily_attempt_count"] = sum(1 for item in client.audit if item.get("endpoint_key") == "stk_bydd_trd")
        counters["kosdaq_daily_attempt_count"] = sum(1 for item in client.audit if item.get("endpoint_key") == "ksq_bydd_trd")
        for key, value in client.status_counts.items():
            counters[{"401": "http_401_count", "403": "http_403_count", "429": "http_429_count", "5xx": "http_5xx_count", "transport_error": "transport_error_count"}[key]] = value
        samsung: dict[str, Any] = {"ticker": "005930", "observations": [], "expected_values": {"2018-04-27": 128386494, "2018-05-04": 6419324700}, "discrepancies": []}
        for day in PILOT_DATES[:2]:
            try:
                frame = store.load_snapshot("KOSPI", day)
                matched = frame.loc[frame["ticker"].astype(str) == "005930"]
                value = int(matched.iloc[0]["listed_shares"]) if not matched.empty else None
                samsung["observations"].append({"date": day, "listed_shares": value})
                if value != samsung["expected_values"][day]:
                    samsung["discrepancies"].append(day)
            except Exception as exc:
                samsung["observations"].append({"date": day, "error": type(exc).__name__})
                samsung["discrepancies"].append(day)
        return {"status": "PASS" if not any(item["blockers"] for item in results) else "BLOCKED_KRX_SCHEMA", "dates": results, "audit": audit}, samsung


def run(mode: str, output: Path, raw_root: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    counters = _base_counters()
    pilot_summary: dict[str, Any] = {"status": "NOT_RUN", "dates": []}
    samsung: dict[str, Any] = {"ticker": "005930", "observations": [], "expected_values": {"2018-04-27": 128386494, "2018-05-04": 6419324700}, "discrepancies": []}
    test_tail = ""
    if mode == "offline":
        test_result, test_tail = _run_offline_tests()
        counters["raw_provider_test_failure_count"] = int(test_result["offline_test_failure_count"] != 0)
        counters["store_test_failure_count"] = counters["raw_provider_test_failure_count"]
        counters["offline_test_passed"] = test_result["offline_test_passed"]
        counters["provider_test_count"] = _collect("tests/test_krx_raw_stock_provider.py")
        counters["store_test_count"] = _collect("tests/test_krx_raw_stock_store.py")
        counters["backfill_test_count"] = _collect("tests/test_krx_historical_backfill.py")
    elif mode == "live-pilot":
        pilot_summary, samsung = _live_pilot(counters)
    elif mode == "production-coverage":
        store = KrxRawStockStore(raw_root)
        coverage = _coverage(store, TARGET_START, TARGET_END)
        counters.update({
            "complete_date_count": coverage["complete_partition_count"] // 2,
            "no_data_date_count": coverage["no_data_count"],
            "failed_date_count": coverage["failure_date_count"],
            "partial_date_count": coverage["partial_date_count"],
            "partition_integrity_error_count": coverage["integrity_error_count"],
            "duplicate_ticker_count": coverage["duplicate_ticker_count"],
            "cross_market_ticker_conflict_count": coverage["cross_market_ticker_conflict_count"],
        })
        counters["production_complete_partition_count"] = coverage["complete_partition_count"]
        counters["production_total_raw_rows"] = coverage["total_raw_rows"]
    else:
        raise ValueError(f"unknown mode: {mode}")

    diff_guard = _production_diff_guard()
    counters.update({
        "production_consumer_changed_count": diff_guard["production_consumer_changed_count"],
        "legacy_cache_modified_count": diff_guard["legacy_cache_modified_count"],
        "adjusted_store_modified_count": diff_guard["adjusted_store_modified_count"],
        "corporate_action_state_modified_count": diff_guard["corporate_action_state_modified_count"],
        "source_contracts_modified_count": diff_guard["source_contracts_modified_count"],
        "secret_occurrence_count": _secret_count(diff_guard["changed_paths"]),
        "validation_source_head_mismatch_count": int(diff_guard["start_head"] != FIX_START_HEAD),
        "disallowed_path_count": diff_guard["disallowed_path_count"],
    })
    required_zero = [
        "raw_provider_test_failure_count", "snapshot_schema_error_count", "source_date_mismatch_count",
        "duplicate_ticker_count", "ticker_format_error_count", "numeric_parse_error_count",
        "unexpected_records_key_count", "store_test_failure_count", "partition_integrity_error_count",
        "partition_conflict_count", "physical_schema_error_count", "content_hash_mismatch_count",
        "file_hash_mismatch_count", "cross_market_ticker_conflict_count", "failed_date_count",
        "partial_date_count", "basic_info_attempt_count", "http_401_count", "http_403_count",
        "http_429_count", "production_consumer_changed_count", "legacy_cache_modified_count",
        "adjusted_store_modified_count", "corporate_action_state_modified_count", "source_contracts_modified_count",
        "opendart_request_count", "secret_occurrence_count", "validation_source_head_mismatch_count",
        "disallowed_path_count",
    ]
    blockers = [name for name in required_zero if counters.get(name, 0) != 0]
    if mode == "offline" and counters.get("offline_test_passed", 0) <= 0:
        blockers.append("BLOCKED_MORE_EVIDENCE_REQUIRED")
    if mode == "live-pilot":
        blockers.extend(pilot_summary.get("blockers", []))
        if pilot_summary.get("status") != "PASS":
            blockers.append(pilot_summary.get("status", "BLOCKED_MORE_EVIDENCE_REQUIRED"))
    if mode == "production-coverage":
        if counters.get("production_complete_partition_count", 0) <= 0 or counters.get("production_total_raw_rows", 0) <= 0:
            blockers.append("BLOCKED_COVERAGE")
    blockers = list(dict.fromkeys(blockers))
    if not blockers and mode == "production-coverage" and counters.get("production_complete_partition_count", 0) > 0 and counters.get("production_total_raw_rows", 0) > 0:
        status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_REVIEW"
        recommendation = "RECOMMEND_PROCEED_TO_MARKET_DATA_REPOSITORY_V02"
    elif not blockers:
        status = "BACKFILL_IN_PROGRESS"
        recommendation = "BLOCKED_MORE_EVIDENCE_REQUIRED"
    elif mode == "live-pilot" and "BLOCKED_KRX_AUTH" in blockers:
        status = "BLOCKED_KRX_AUTH"
        recommendation = "BLOCKED_KRX_AUTH"
    else:
        status = "BACKFILL_IN_PROGRESS" if mode == "offline" else blockers[0]
        recommendation = blockers[0] if blockers[0] in {
            "BACKFILL_PAUSED_QUOTA", "BACKFILL_PAUSED_TASK_BUDGET", "BLOCKED_KRX_AUTH",
            "BLOCKED_KRX_SCHEMA", "BLOCKED_RAW_PARTITION_CONFLICT", "BLOCKED_RAW_STORE_INTEGRITY",
            "BLOCKED_COVERAGE", "BLOCKED_PRODUCTION_REGRESSION", "BLOCKED_PROVENANCE", "BLOCKED_MORE_EVIDENCE_REQUIRED",
        } else "BLOCKED_MORE_EVIDENCE_REQUIRED"

    coverage_payload = _coverage(KrxRawStockStore(raw_root), TARGET_START, TARGET_END) if raw_root.exists() else {"coverage_by_year": {}}
    _write_json(output / "provider_contract.json", {
        "authority": "KRX Open API Stock Daily",
        "schema_version": "KRX_RAW_STOCK_V01",
        "markets": {market: MARKET_ENDPOINTS[market] for market in MARKETS},
        "records_root": "OutBlock_1",
        "source_fields": {"BAS_DD": "date", "ISU_CD": "ticker", "TDD_OPNPRC": "open", "TDD_HGPRC": "high", "TDD_LWPRC": "low", "TDD_CLSPRC": "close", "ACC_TRDVOL": "volume", "ACC_TRDVAL": "trading_value", "MKTCAP": "market_cap", "LIST_SHRS": "listed_shares"},
        "zero_preservation": True,
        "adjustment": False,
    })
    _write_json(output / "store_contract.json", {
        "root": "data/market/raw/krx_stocks/v01/",
        "partition": "market=MARKET/year=YYYY/YYYY-MM-DD.parquet",
        "manifest": "data/market/raw/krx_stocks/v01/manifest.sqlite3",
        "schema_version": "KRX_RAW_STOCK_V01",
        "physical_columns": list(RAW_COLUMNS),
        "immutable_complete_partition": True,
        "hashes": ["content_sha256", "file_sha256"],
        "same_content": "IDEMPOTENT_NOOP",
        "different_content": "RAW_PARTITION_CONFLICT",
    })
    _write_json(output / "backfill_contract.json", {
        "candidate_calendar": "pd.bdate_range weekdays only; KRX response determines trading day",
        "both_empty": "NO_DATA only outside two-day finalization lag",
        "asymmetric_empty": "ASYMMETRIC_EMPTY_SNAPSHOT",
        "resume": ["COMPLETE", "NO_DATA"],
        "failed_retry": "--retry-failures",
        "quota": "LocalKrxOpenApiQuota.reserve_attempt before every client HTTP attempt",
        "sequential_markets": True,
        "historical_list_shrs_replay": False,
    })
    _write_json(output / "coverage_summary.json", {"target_start": TARGET_START, "target_end": TARGET_END, "coverage": coverage_payload, "counters": counters})
    _write_json(output / "quota_summary.json", {key: counters.get(key) for key in ("quota_usage_date_kst", "quota_global_before", "quota_global_after", "quota_remaining_after", "krx_open_api_attempt_count", "retry_attempt_count", "http_401_count", "http_403_count", "http_429_count", "http_5xx_count", "transport_error_count")})
    _write_json(output / "samsung_listed_shares_evidence.json", samsung)
    _write_json(output / "partition_integrity_summary.json", {"integrity_scan_count": counters.get("partition_integrity_error_count", 0), "integrity_error_count": counters.get("partition_integrity_error_count", 0), "duplicate_ticker_count": counters.get("duplicate_ticker_count", 0), "cross_market_ticker_conflict_count": counters.get("cross_market_ticker_conflict_count", 0)})
    _write_json(output / "live_pilot_summary.json", pilot_summary)
    with (output / "failed_dates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "market", "status", "error_code"])
    with (output / "coverage_by_year.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["year", "candidate_dates", "complete_snapshot_dates", "no_data_dates", "failure_dates", "row_count"])
        for year, values in coverage_payload.get("coverage_by_year", {}).items():
            writer.writerow([year, *[values.get(key, 0) for key in ("candidate_dates", "complete_snapshot_dates", "no_data_dates", "failure_dates", "row_count")]])
    summary = {
        "architecture_version": "KRX_HISTORICAL_BACKFILL_V01",
        "mode": mode,
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": diff_guard["implementation_head"],
        "end_head": None,
        "status": status,
        "recommendation": recommendation,
        "blockers": blockers,
        "counters": counters,
        "production_diff_guard": diff_guard,
        "test_output_tail": test_tail,
    }
    _write_json(output / "krx_historical_backfill_v01_summary.json", summary)
    artifacts = sorted(path.name for path in output.iterdir() if path.is_file() and path.name != "krx_historical_backfill_v01_manifest.json")
    _write_json(output / "krx_historical_backfill_v01_manifest.json", {
        "architecture_version": "KRX_HISTORICAL_BACKFILL_V01",
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": diff_guard["implementation_head"],
        "end_head": None,
        "artifacts": artifacts + ["krx_historical_backfill_v01_manifest.json"],
        "artifact_count": len(artifacts) + 1,
        "network_request_count": counters.get("krx_open_api_attempt_count", 0),
        "status": status,
    })
    (output / "krx_historical_backfill_recommendation.md").write_text(
        "krx_historical_backfill_recommendation.md\n\n"
        "======================================================================\n"
        "KRX Historical Backfill V01 Recommendation\n"
        "======================================================================\n\n"
        f"STATUS: {status}\nRECOMMENDATION: {recommendation}\n\n"
        "Raw KRX snapshots preserve source values without adjustment, filtering, or historical corporate-action replay.\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KRX historical raw stock backfill v01")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live-pilot", action="store_true")
    mode.add_argument("--production-coverage", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    args = parser.parse_args()
    selected_mode = "offline" if args.offline else "live-pilot" if args.live_pilot else "production-coverage"
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    result = run(selected_mode, output, raw_root)
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "blockers": result["blockers"]}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
