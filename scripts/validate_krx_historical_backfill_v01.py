#!/usr/bin/env python3
"""Offline, bounded live-pilot, and local-coverage validation for raw KRX backfill."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
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

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner, candidate_dates, prioritize_blockers  # noqa: E402
from trend_scanner.data.krx_openapi_client import (  # noqa: E402
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_provider import (  # noqa: E402
    MARKET_ENDPOINTS,
    MARKETS,
    RAW_COLUMNS,
    KrxRawStockSnapshotError,
    KrxRawStockSnapshotProvider,
)
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX04"
FIX_START_HEAD = "ca9b5e6eabbad693fb10a829a241b28b82de879b"
DEFAULT_OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
PILOT_DATES = ("2018-04-27", "2018-05-04", "2026-08-21")
SAMSUNG_LISTED_SHARES_EXPECTED = {
    "2018-04-27": 128386494,
    "2018-05-04": 6419324700,
}
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
ALLOWED_PATHS = {
    "src/trend_scanner/data/krx_raw_stock_provider.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "src/trend_scanner/data/krx_historical_backfill.py",
    "tests/test_krx_raw_stock_provider.py",
    "tests/test_krx_raw_stock_store.py",
    "tests/test_krx_historical_backfill.py",
    "tests/test_krx_open_api_validation_v01.py",
    # FIX03 updates the CLOSED architecture guard to use its frozen END;
    # these two validator/test paths are bounded regression evidence, not
    # production runtime behavior.
    "scripts/validate_krx_production_data_architecture_v01.py",
    "tests/test_krx_production_data_architecture_v01.py",
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


def pilot_status(results: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Return the highest-priority actual blocker from bounded pilot results."""

    blockers = prioritize_blockers(
        blocker
        for result in results
        for blocker in result.get("blockers", [])
    )
    return ("PASS" if not blockers else blockers[0], blockers)


def pilot_parameters(diagnostic_only: bool = False) -> dict[str, Any]:
    """Return the bounded request contract for each live validation mode."""

    if diagnostic_only:
        return {
            "mode": "live-diagnostic",
            "dates": (PILOT_DATES[0],),
            "markets": MARKETS,
            "request_budget": 2,
            "max_transient_retries": 0,
        }
    return {
        "mode": "live-pilot",
        "dates": PILOT_DATES,
        "markets": MARKETS,
        "request_budget": 6,
        "max_transient_retries": 0,
    }


def _evidence_metadata(mode: str, source_head: str | None = None) -> dict[str, Any]:
    return {
        "validation_generation": FIX_VERSION,
        "source_head": source_head,
        "mode": mode,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "legacy": False,
    }


def _is_current_evidence(payload: Any, mode: str) -> bool:
    return isinstance(payload, dict) and payload.get("validation_generation") == FIX_VERSION and payload.get("mode") == mode and payload.get("legacy") is False


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_legacy_live_evidence(output: Path) -> dict[str, Any]:
    existing = _load_json(output / "legacy_live_evidence.json")
    if existing is not None:
        return existing
    legacy: dict[str, Any] = {}
    for name in ("live_diagnostic_summary.json", "live_pilot_summary.json"):
        payload = _load_json(output / name)
        if payload is not None and not _is_current_evidence(payload, payload.get("mode", "live-pilot")):
            legacy[name.removesuffix("_summary.json")] = payload
    if not legacy:
        return {"validation_generation": "PRE_FIX04", "legacy": True, "evidence": {}}
    return {
        "validation_generation": "PRE_FIX04",
        "legacy": True,
        "evidence": legacy,
    }


def _error_code(exc: Exception) -> str:
    if getattr(exc, "error_code", None):
        return str(exc.error_code)
    text = str(exc)
    return text.split(":", 1)[0] if text.startswith("RAW_") else type(exc).__name__.upper()


def _snapshot_blocker(exc: Exception, diagnostic: dict[str, Any]) -> str:
    if isinstance(exc, KrxOpenApiAuthorizationError):
        return "BLOCKED_KRX_AUTH"
    if isinstance(exc, (KrxOpenApiRateLimitError, KrxOpenApiQuotaExceeded)):
        return "BACKFILL_PAUSED_QUOTA"
    if isinstance(exc, KrxOpenApiBudgetError):
        return "BACKFILL_PAUSED_TASK_BUDGET"
    http_status = diagnostic.get("http_status")
    if (isinstance(http_status, int) and 500 <= http_status <= 599) or (http_status is None and diagnostic.get("transport_error_type")):
        return "BLOCKED_KRX_TRANSPORT"
    if isinstance(exc, KrxRawStockSnapshotError) or _error_code(exc).startswith("RAW_"):
        return "BLOCKED_KRX_SCHEMA"
    return "BLOCKED_MORE_EVIDENCE_REQUIRED"


def _client_audit_diagnostic(client: KrxOpenApiClient, market: str) -> dict[str, Any]:
    endpoint_key = MARKET_ENDPOINTS[market].strip("/")
    for item in reversed(client.audit):
        if item.get("endpoint_key") == endpoint_key:
            return {
                "http_status": item.get("http_status"),
                "record_count": item.get("record_count", 0),
                "top_level_keys": item.get("top_level_keys", []),
                "transport_error_type": item.get("error_type"),
            }
    return {}


def _samsung_evidence(store: KrxRawStockStore | None, available_dates: tuple[str, ...]) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    target_dates = tuple(day for day in SAMSUNG_LISTED_SHARES_EXPECTED if day in available_dates)
    for day in target_dates:
        expected = SAMSUNG_LISTED_SHARES_EXPECTED[day]
        observed: int | None = None
        ticker_found = False
        snapshot_available = False
        if store is not None:
            try:
                frame = store.load_snapshot("KOSPI", day)
                snapshot_available = True
                matched = frame.loc[frame["ticker"].astype(str) == "005930"]
                if not matched.empty:
                    ticker_found = True
                    observed = int(matched.iloc[0]["listed_shares"])
            except Exception:
                snapshot_available = False
        observations.append({
            "date": day,
            "ticker": "005930",
            "expected": expected,
            "observed": observed,
            "ticker_found": ticker_found,
            "snapshot_available": snapshot_available,
            "match": bool(ticker_found and observed == expected),
        })
    if not observations:
        return {"ticker": "005930", "observations": [], "status": "NOT_RUN", "blockers": []}
    if len(observations) < len(SAMSUNG_LISTED_SHARES_EXPECTED):
        status = "PARTIAL_EVIDENCE"
        blockers: list[str] = []
    elif all(item["match"] for item in observations):
        status = "PASS"
        blockers = []
    else:
        status = "MISMATCH"
        blockers = ["BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE"]
    return {"ticker": "005930", "observations": observations, "status": status, "blockers": blockers}


def _schema_evidence_status(current_diagnostic: dict[str, Any]) -> str:
    status = current_diagnostic.get("status", "NOT_RUN")
    if status == "NOT_RUN":
        return "NOT_RUN"
    if status == "BLOCKED_KRX_SCHEMA":
        return "BLOCKED_KRX_SCHEMA"
    if status == "BLOCKED_KRX_TRANSPORT":
        return "NO_SCHEMA_CONCLUSION_TRANSPORT_BLOCKED"
    if status == "PASS":
        return "NO_SCHEMA_BLOCKER"
    return "NO_SCHEMA_CONCLUSION"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _validation_source_head(implementation_head: str) -> str:
    """Return the HEAD that actually supplied source, or flag a dirty source tree."""

    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    source_dirty = any(
        (line[3:] if len(line) >= 4 else line).strip()
        and not (line[3:] if len(line) >= 4 else line).strip().startswith("artifacts/")
        for line in dirty
    )
    return "WORKTREE_DIRTY" if source_dirty else implementation_head


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
        "tests/test_krx_open_api_validation_v01.py",
        "tests/test_krx_production_data_architecture_v01.py",
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
        "required_field_missing_count": 0,
        "ohlc_relation_error_count": 0,
        "store_test_failure_count": 0,
        "partition_integrity_error_count": 0,
        "partition_conflict_count": 0,
        "physical_schema_error_count": 0,
        "content_hash_mismatch_count": 0,
        "file_hash_mismatch_count": 0,
        "cross_market_ticker_conflict_count": 0,
        "candidate_date_count": 0,
        "complete_date_count": 0,
        "finalized_no_data_date_count": 0,
        "no_data_date_count": 0,
        "failed_date_count": 0,
        "partial_date_count": 0,
        "unexplained_missing_date_count": 0,
        "unexplained_missing_partition_count": 0,
        "missing_kospi_partition_count": 0,
        "missing_kosdaq_partition_count": 0,
        "complete_partition_count": 0,
        "partition_integrity_scan_count": 0,
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
        "cross_market_conflict_sample_count": 0,
    }


def _coverage(store: KrxRawStockStore, start: str, end: str) -> dict[str, Any]:
    candidates = candidate_dates(start, end)
    by_year: dict[str, dict[str, int]] = {}
    complete_dates: list[str] = []
    no_data_dates: list[str] = []
    failed_dates: list[str] = []
    partial_dates: list[str] = []
    missing_dates: list[str] = []
    integrity_scan_count = 0
    integrity_errors = 0
    content_hash_mismatches = 0
    file_hash_mismatches = 0
    duplicate_tickers = 0
    cross_market_conflicts: list[dict[str, Any]] = []
    total_rows = 0
    rows_by_market = {market: 0 for market in MARKETS}
    complete_partition_count = 0
    missing_partition_count = 0
    missing_by_market = {market: 0 for market in MARKETS}

    for day in candidates:
        year = day[:4]
        bucket = by_year.setdefault(year, {
            "candidate_dates": 0, "complete_dates": 0, "finalized_no_data_dates": 0,
            "failed_dates": 0, "partial_dates": 0, "missing_dates": 0,
            "complete_partitions": 0, "row_count": 0,
        })
        bucket["candidate_dates"] += 1
        states = {market: store.get_manifest(market, day) for market in MARKETS}
        statuses = {market: (states[market] or {}).get("status") for market in MARKETS}
        is_complete = all(statuses[market] == "COMPLETE" for market in MARKETS)
        is_no_data = all(statuses[market] == "NO_DATA" for market in MARKETS)
        if is_complete:
            complete_dates.append(day)
            bucket["complete_dates"] += 1
        elif is_no_data:
            no_data_dates.append(day)
            bucket["finalized_no_data_dates"] += 1
        else:
            missing_for_day = False
            if any(statuses[market] is None for market in MARKETS):
                missing_for_day = True
                for market in MARKETS:
                    if statuses[market] is None:
                        missing_partition_count += 1
                        missing_by_market[market] += 1
            if any(status == "FAILED" for status in statuses.values()):
                failed_dates.append(day)
                bucket["failed_dates"] += 1
            if sum(status == "COMPLETE" for status in statuses.values()) == 1:
                partial_dates.append(day)
                bucket["partial_dates"] += 1
            if missing_for_day:
                missing_dates.append(day)
                bucket["missing_dates"] += 1

        if is_complete:
            frames: dict[str, pd.DataFrame] = {}
            for market in MARKETS:
                complete_partition_count += 1
                bucket["complete_partitions"] += 1
                integrity_scan_count += 1
                check = store.verify_snapshot(market, day)
                if not check.get("valid"):
                    integrity_errors += 1
                    error_text = " ".join(str(item) for item in check.get("errors", []))
                    content_hash_mismatches += int("content hash mismatch" in error_text)
                    file_hash_mismatches += int("file hash mismatch" in error_text)
                    continue
                frame = store.load_snapshot(market, day)
                frames[market] = frame
                duplicate_tickers += int(frame["ticker"].duplicated().sum())
                row_count = len(frame)
                total_rows += row_count
                rows_by_market[market] += row_count
                bucket["row_count"] += row_count

            seen: dict[str, str] = {}
            for market in MARKETS:
                frame = frames.get(market)
                if frame is None:
                    continue
                for ticker in frame["ticker"].astype(str):
                    previous = seen.get(ticker)
                    if previous is not None and previous != market:
                        cross_market_conflicts.append({"date": day, "ticker": ticker, "markets": [previous, market]})
                    else:
                        seen[ticker] = market

    return {
        "candidate_date_count": len(candidates),
        "first_complete_trading_date": min(complete_dates) if complete_dates else None,
        "last_complete_trading_date": max(complete_dates) if complete_dates else None,
        "complete_date_count": len(complete_dates),
        "finalized_no_data_date_count": len(no_data_dates),
        "no_data_count": len(no_data_dates),
        "failed_date_count": len(failed_dates),
        "failure_date_count": len(failed_dates),
        "partial_date_count": len(partial_dates),
        "unexplained_missing_date_count": len(missing_dates),
        "unexplained_missing_partition_count": missing_partition_count,
        "missing_kospi_partition_count": missing_by_market["KOSPI"],
        "missing_kosdaq_partition_count": missing_by_market["KOSDAQ"],
        "complete_partition_count": complete_partition_count,
        "total_raw_rows": total_rows,
        "rows_by_market": rows_by_market,
        "integrity_scan_count": integrity_scan_count,
        "partition_integrity_scan_count": integrity_scan_count,
        "integrity_error_count": integrity_errors,
        "partition_integrity_error_count": integrity_errors,
        "content_hash_mismatch_count": content_hash_mismatches,
        "file_hash_mismatch_count": file_hash_mismatches,
        "duplicate_ticker_count": duplicate_tickers,
        "cross_market_ticker_conflict_count": len(cross_market_conflicts),
        "cross_market_conflict_samples": cross_market_conflicts[:20],
        "coverage_by_year": by_year,
        "missing_dates": missing_dates[:100],
    }


def _live_diagnostic(counters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = pilot_parameters(diagnostic_only=True)
    secret = load_auth_key()
    if not secret:
        return {
            **_evidence_metadata("live-diagnostic"),
            "date": parameters["dates"][0],
            "dates": [],
            "candidate_dates": list(parameters["dates"]),
            "markets": list(parameters["markets"]),
            "request_budget": 2,
            "request_count": 0,
            "retry_count": 0,
            "status": "BLOCKED_KRX_AUTH",
            "blockers": ["BLOCKED_KRX_AUTH"],
            "per_market": {market: {"attempted": False, "status": "NOT_ATTEMPTED"} for market in MARKETS},
            "diagnostics": [],
            "failure_observations": [],
        }, _samsung_evidence(None, parameters["dates"])
    with tempfile.TemporaryDirectory(prefix="krx-historical-diagnostic-") as temp_dir:
        root = Path(temp_dir)
        quota = LocalKrxOpenApiQuota(root / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
        client = KrxOpenApiClient(secret, max_requests=2, max_transient_retries=0, quota=quota)
        provider = KrxRawStockSnapshotProvider(client)
        store = KrxRawStockStore(root / "raw")
        per_market: dict[str, dict[str, Any]] = {}
        diagnostics: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        stop = False
        day = parameters["dates"][0]
        for market in MARKETS:
            if stop:
                per_market[market] = {"attempted": False, "date": day, "market": market, "status": "NOT_ATTEMPTED"}
                continue
            endpoint = MARKET_ENDPOINTS[market]
            try:
                frame = provider.fetch_market_snapshot(market, day)
                audit = _client_audit_diagnostic(client, market)
                store.save_snapshot(market, day, frame, endpoint)
                per_market[market] = {
                    "attempted": True,
                    "date": day,
                    "market": market,
                    "endpoint": endpoint,
                    "status": "PASS",
                    "blocker": None,
                    "error_code": None,
                    "records_key": "OutBlock_1" if audit.get("http_status") == 200 else None,
                    **audit,
                    "record_count": len(frame),
                }
            except Exception as exc:
                diagnostic = dict(getattr(exc, "diagnostic", {}) or {})
                diagnostic.setdefault("date", day)
                diagnostic.setdefault("market", market)
                diagnostic.setdefault("endpoint", endpoint)
                diagnostic["error_code"] = _error_code(exc)
                blocker = _snapshot_blocker(exc, diagnostic)
                diagnostic["blocker"] = blocker
                diagnostics.append(diagnostic)
                failures.append({"date": day, "market": market, "status": "FAILED", "error_code": diagnostic["error_code"]})
                per_market[market] = {
                    "attempted": True,
                    "date": day,
                    "market": market,
                    "endpoint": endpoint,
                    "status": blocker,
                    **diagnostic,
                }
                if blocker in {"BLOCKED_KRX_AUTH", "BACKFILL_PAUSED_QUOTA", "BACKFILL_PAUSED_TASK_BUDGET"}:
                    stop = True
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
        for item in diagnostics:
            code = item.get("error_code")
            counter = {
                "RAW_SNAPSHOT_REQUIRED_FIELD_MISSING": "required_field_missing_count",
                "RAW_SNAPSHOT_RECORDS_KEY": "unexpected_records_key_count",
                "RAW_SNAPSHOT_DATE_MISMATCH": "source_date_mismatch_count",
                "RAW_SNAPSHOT_TICKER_FORMAT_ERROR": "ticker_format_error_count",
                "RAW_SNAPSHOT_NUMERIC_PARSE_ERROR": "numeric_parse_error_count",
                "RAW_SNAPSHOT_NUMERIC_RANGE_ERROR": "numeric_parse_error_count",
                "RAW_SNAPSHOT_OHLC_RELATION_ERROR": "ohlc_relation_error_count",
            }.get(code)
            if counter:
                counters[counter] += 1
        blockers = prioritize_blockers(item.get("blocker") for item in diagnostics)
        attempted_all = all(per_market[market].get("attempted") for market in MARKETS)
        passed_all = all(per_market[market].get("status") == "PASS" for market in MARKETS)
        status = "PASS" if attempted_all and passed_all and audit["request_count"] == 2 else (blockers[0] if blockers else "BLOCKED_MORE_EVIDENCE_REQUIRED")
        return {
            **_evidence_metadata("live-diagnostic"),
            "date": day,
            "dates": [],
            "candidate_dates": list(parameters["dates"]),
            "markets": list(parameters["markets"]),
            "request_budget": 2,
            "request_count": audit["request_count"],
            "retry_count": audit["retry_count"],
            "status": status,
            "blockers": blockers,
            "per_market": per_market,
            "audit": audit,
            "diagnostics": diagnostics,
            "failure_observations": failures,
        }, _samsung_evidence(store, parameters["dates"])


def _live_pilot(counters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = pilot_parameters()
    secret = load_auth_key()
    if not secret:
        return {
            **_evidence_metadata("live-pilot"),
            "dates": [],
            "markets": list(parameters["markets"]),
            "request_budget": 6,
            "request_count": 0,
            "retry_count": 0,
            "status": "BLOCKED_KRX_AUTH",
            "blockers": ["BLOCKED_KRX_AUTH"],
        }, _samsung_evidence(None, parameters["dates"])
    with tempfile.TemporaryDirectory(prefix="krx-historical-pilot-") as temp_dir:
        root = Path(temp_dir)
        quota = LocalKrxOpenApiQuota(root / "quota.sqlite3", endpoint_limit=100, global_safety_limit=100)
        client = KrxOpenApiClient(secret, max_requests=6, max_transient_retries=0, quota=quota)
        provider = KrxRawStockSnapshotProvider(client)
        store = KrxRawStockStore(root / "raw")
        runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
        results = []
        for day in parameters["dates"]:
            result = runner.run(day, day, max_task_attempts=2)
            results.append({
                "date": day,
                "status": result["status"],
                "aggregate": result["aggregate"],
                "blockers": result["blockers"],
                "diagnostics": result.get("diagnostics", []),
                "failure_observations": result.get("failure_observations", []),
            })
            if result["blockers"]:
                break
        audit = {"request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "quota_usage": quota.get_usage()}
        counters["krx_open_api_attempt_count"] = client.request_count
        counters["retry_attempt_count"] = client.retry_count
        counters["kospi_daily_attempt_count"] = sum(1 for item in client.audit if item.get("endpoint_key") == "stk_bydd_trd")
        counters["kosdaq_daily_attempt_count"] = sum(1 for item in client.audit if item.get("endpoint_key") == "ksq_bydd_trd")
        for key, value in client.status_counts.items():
            counters[{"401": "http_401_count", "403": "http_403_count", "429": "http_429_count", "5xx": "http_5xx_count", "transport_error": "transport_error_count"}[key]] = value
        diagnostics = [item for result in results for item in result.get("diagnostics", [])]
        failures = [item for result in results for item in result.get("failure_observations", [])]
        status, pilot_blockers = pilot_status(results)
        return {
            **_evidence_metadata("live-pilot"),
            "markets": list(parameters["markets"]),
            "request_budget": 6,
            "status": status,
            "blockers": pilot_blockers,
            "dates": results,
            "candidate_dates": list(parameters["dates"]),
            "request_count": audit["request_count"],
            "retry_count": audit["retry_count"],
            "audit": audit,
            "diagnostics": diagnostics,
            "failure_observations": failures,
        }, _samsung_evidence(store, parameters["dates"])


def run(mode: str, output: Path, raw_root: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    counters = _base_counters()
    pilot_summary: dict[str, Any] = {**_evidence_metadata("live-pilot"), "status": "NOT_RUN", "dates": [], "candidate_dates": list(PILOT_DATES)}
    diagnostic_summary: dict[str, Any] = {**_evidence_metadata("live-diagnostic"), "status": "NOT_RUN", "date": PILOT_DATES[0], "dates": [], "candidate_dates": [PILOT_DATES[0]]}
    legacy_live_evidence = _load_legacy_live_evidence(output)
    prior_live_summary = _load_json(output / "live_pilot_summary.json")
    prior_diagnostic_summary = _load_json(output / "live_diagnostic_summary.json")
    if mode != "live-pilot" and _is_current_evidence(prior_live_summary, "live-pilot"):
        pilot_summary = prior_live_summary
    if mode != "live-diagnostic" and _is_current_evidence(prior_diagnostic_summary, "live-diagnostic"):
        diagnostic_summary = prior_diagnostic_summary
    samsung: dict[str, Any] = _samsung_evidence(None, ())
    test_tail = ""
    if mode == "offline":
        test_result, test_tail = _run_offline_tests()
        counters["raw_provider_test_failure_count"] = int(test_result["offline_test_failure_count"] != 0)
        counters["store_test_failure_count"] = counters["raw_provider_test_failure_count"]
        counters["offline_test_passed"] = test_result["offline_test_passed"]
        counters["provider_test_count"] = _collect("tests/test_krx_raw_stock_provider.py")
        counters["store_test_count"] = _collect("tests/test_krx_raw_stock_store.py")
        counters["backfill_test_count"] = _collect("tests/test_krx_historical_backfill.py")
        counters["openapi_validation_test_count"] = _collect("tests/test_krx_open_api_validation_v01.py")
        counters["architecture_test_count"] = _collect("tests/test_krx_production_data_architecture_v01.py")
    elif mode == "live-diagnostic":
        diagnostic_summary, samsung = _live_diagnostic(counters)
    elif mode == "live-pilot":
        pilot_summary, samsung = _live_pilot(counters)
    elif mode == "production-coverage":
        store = KrxRawStockStore(raw_root)
        coverage = _coverage(store, TARGET_START, TARGET_END)
        counters.update({
            "candidate_date_count": coverage["candidate_date_count"],
            "complete_date_count": coverage["complete_date_count"],
            "finalized_no_data_date_count": coverage["finalized_no_data_date_count"],
            "no_data_date_count": coverage["finalized_no_data_date_count"],
            "failed_date_count": coverage["failed_date_count"],
            "partial_date_count": coverage["partial_date_count"],
            "unexplained_missing_date_count": coverage["unexplained_missing_date_count"],
            "unexplained_missing_partition_count": coverage["unexplained_missing_partition_count"],
            "missing_kospi_partition_count": coverage["missing_kospi_partition_count"],
            "missing_kosdaq_partition_count": coverage["missing_kosdaq_partition_count"],
            "complete_partition_count": coverage["complete_partition_count"],
            "partition_integrity_scan_count": coverage["partition_integrity_scan_count"],
            "partition_integrity_error_count": coverage["partition_integrity_error_count"],
            "content_hash_mismatch_count": coverage["content_hash_mismatch_count"],
            "file_hash_mismatch_count": coverage["file_hash_mismatch_count"],
            "duplicate_ticker_count": coverage["duplicate_ticker_count"],
            "cross_market_ticker_conflict_count": coverage["cross_market_ticker_conflict_count"],
        })
        counters["cross_market_conflict_sample_count"] = len(coverage.get("cross_market_conflict_samples", []))
        counters["production_complete_partition_count"] = coverage["complete_partition_count"]
        counters["production_total_raw_rows"] = coverage["total_raw_rows"]
    else:
        raise ValueError(f"unknown mode: {mode}")

    diff_guard = _production_diff_guard()
    validation_source_head = _validation_source_head(diff_guard["implementation_head"])
    pilot_summary = {**pilot_summary, **_evidence_metadata("live-pilot", diff_guard["implementation_head"])}
    diagnostic_summary = {**diagnostic_summary, **_evidence_metadata("live-diagnostic", diff_guard["implementation_head"])}
    full_regression = _load_json(output / "full_regression_summary.json") or {
        "command": "uv run pytest -q -p no:cacheprovider",
        "started_at": None,
        "finished_at": None,
        "completed": False,
        "return_code": None,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "deselected": 0,
        "duration_seconds": None,
        "slowest_tests": [],
        "hang_diagnostic": "NOT_RECORDED",
    }
    counters.update({
        "production_consumer_changed_count": diff_guard["production_consumer_changed_count"],
        "legacy_cache_modified_count": diff_guard["legacy_cache_modified_count"],
        "adjusted_store_modified_count": diff_guard["adjusted_store_modified_count"],
        "corporate_action_state_modified_count": diff_guard["corporate_action_state_modified_count"],
        "source_contracts_modified_count": diff_guard["source_contracts_modified_count"],
        "secret_occurrence_count": _secret_count(diff_guard["changed_paths"]),
        "validation_source_head_mismatch_count": int(validation_source_head != diff_guard["implementation_head"]),
        "disallowed_path_count": diff_guard["disallowed_path_count"],
    })
    required_zero = [
        "raw_provider_test_failure_count", "snapshot_schema_error_count", "source_date_mismatch_count",
        "duplicate_ticker_count", "ticker_format_error_count", "numeric_parse_error_count",
        "unexpected_records_key_count", "required_field_missing_count", "ohlc_relation_error_count",
        "store_test_failure_count", "partition_integrity_error_count", "unexplained_missing_date_count",
        "unexplained_missing_partition_count",
        "partition_conflict_count", "physical_schema_error_count", "content_hash_mismatch_count",
        "file_hash_mismatch_count", "cross_market_ticker_conflict_count", "failed_date_count",
        "partial_date_count", "basic_info_attempt_count", "http_401_count", "http_403_count",
        "http_429_count", "production_consumer_changed_count", "legacy_cache_modified_count",
        "adjusted_store_modified_count", "corporate_action_state_modified_count", "source_contracts_modified_count",
        "opendart_request_count", "secret_occurrence_count", "validation_source_head_mismatch_count",
        "disallowed_path_count", "http_5xx_count", "transport_error_count",
    ]
    counter_blocker_map = {
        "raw_provider_test_failure_count": "BLOCKED_KRX_SCHEMA",
        "snapshot_schema_error_count": "BLOCKED_KRX_SCHEMA",
        "source_date_mismatch_count": "BLOCKED_KRX_SCHEMA",
        "duplicate_ticker_count": "BLOCKED_KRX_SCHEMA",
        "ticker_format_error_count": "BLOCKED_KRX_SCHEMA",
        "numeric_parse_error_count": "BLOCKED_KRX_SCHEMA",
        "unexpected_records_key_count": "BLOCKED_KRX_SCHEMA",
        "required_field_missing_count": "BLOCKED_KRX_SCHEMA",
        "ohlc_relation_error_count": "BLOCKED_KRX_SCHEMA",
        "partition_integrity_error_count": "BLOCKED_RAW_STORE_INTEGRITY",
        "content_hash_mismatch_count": "BLOCKED_RAW_STORE_INTEGRITY",
        "file_hash_mismatch_count": "BLOCKED_RAW_STORE_INTEGRITY",
        "cross_market_ticker_conflict_count": "BLOCKED_CROSS_MARKET_TICKER_CONFLICT",
        "failed_date_count": "BLOCKED_COVERAGE",
        "partial_date_count": "BLOCKED_COVERAGE",
        "unexplained_missing_date_count": "BLOCKED_COVERAGE",
        "unexplained_missing_partition_count": "BLOCKED_COVERAGE",
        "http_401_count": "BLOCKED_KRX_AUTH",
        "http_403_count": "BLOCKED_KRX_AUTH",
        "http_429_count": "BACKFILL_PAUSED_QUOTA",
        "http_5xx_count": "BLOCKED_KRX_TRANSPORT",
        "transport_error_count": "BLOCKED_KRX_TRANSPORT",
        "validation_source_head_mismatch_count": "BLOCKED_PROVENANCE",
        "disallowed_path_count": "BLOCKED_PRODUCTION_REGRESSION",
        "secret_occurrence_count": "BLOCKED_PROVENANCE",
    }
    blockers = [counter_blocker_map.get(name, name) for name in required_zero if counters.get(name, 0) != 0]
    if mode == "offline" and counters.get("offline_test_passed", 0) <= 0:
        blockers.append("BLOCKED_MORE_EVIDENCE_REQUIRED")
    if mode == "live-diagnostic":
        blockers.extend(diagnostic_summary.get("blockers", []))
        if diagnostic_summary.get("status") != "PASS":
            blockers.append(diagnostic_summary.get("status", "BLOCKED_MORE_EVIDENCE_REQUIRED"))
    if mode == "live-pilot":
        blockers.extend(pilot_summary.get("blockers", []))
        if pilot_summary.get("status") != "PASS":
            blockers.append(pilot_summary.get("status", "BLOCKED_MORE_EVIDENCE_REQUIRED"))
        if samsung.get("status") != "PASS":
            blockers.extend(samsung.get("blockers", ["BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE"]))
    if mode == "production-coverage":
        if counters.get("candidate_date_count", 0) <= 0 or counters.get("production_complete_partition_count", 0) <= 0 or counters.get("production_total_raw_rows", 0) <= 0:
            blockers.append("BLOCKED_COVERAGE")
    if not full_regression.get("completed") or full_regression.get("return_code") != 0 or full_regression.get("failed", 0) != 0:
        blockers.append("BLOCKED_PRODUCTION_REGRESSION")
    blockers = prioritize_blockers(blockers)
    if any(item in blockers for item in {"unexplained_missing_date_count", "unexplained_missing_partition_count"}):
        blockers = ["BLOCKED_COVERAGE", *[item for item in blockers if item != "BLOCKED_COVERAGE"]]
    coverage_ready = (
        mode == "production-coverage"
        and counters.get("candidate_date_count", 0) > 0
        and counters.get("complete_date_count", 0) + counters.get("finalized_no_data_date_count", 0) == counters.get("candidate_date_count", 0)
        and counters.get("production_complete_partition_count", 0) > 0
        and counters.get("production_total_raw_rows", 0) > 0
    )
    if not blockers and coverage_ready:
        status = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX04_REVIEW"
        recommendation = "READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_FIX04_REVIEW"
    elif not blockers:
        status = "BACKFILL_IN_PROGRESS"
        recommendation = "BLOCKED_MORE_EVIDENCE_REQUIRED"
    elif mode in {"live-diagnostic", "live-pilot"} and "BLOCKED_KRX_AUTH" in blockers:
        status = "BLOCKED_KRX_AUTH"
        recommendation = "BLOCKED_KRX_AUTH"
    else:
        status = "BACKFILL_IN_PROGRESS" if mode == "offline" else blockers[0]
        recommendation = blockers[0] if blockers[0] in {
            "BACKFILL_PAUSED_QUOTA", "BACKFILL_PAUSED_TASK_BUDGET", "BLOCKED_KRX_AUTH", "BLOCKED_KRX_TRANSPORT",
            "BLOCKED_KRX_SCHEMA", "BLOCKED_RAW_PARTITION_CONFLICT", "BLOCKED_RAW_STORE_INTEGRITY",
            "BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE",
            "BLOCKED_COVERAGE", "BLOCKED_PRODUCTION_REGRESSION", "BLOCKED_PROVENANCE", "BLOCKED_MORE_EVIDENCE_REQUIRED",
        } else "BLOCKED_MORE_EVIDENCE_REQUIRED"

    coverage_payload = _coverage(KrxRawStockStore(raw_root), TARGET_START, TARGET_END) if raw_root.exists() else {
        "candidate_date_count": 0,
        "complete_date_count": 0,
        "finalized_no_data_date_count": 0,
        "unexplained_missing_date_count": 0,
        "unexplained_missing_partition_count": 0,
        "coverage_by_year": {},
    }
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
        "recent_empty": "RECENT_EMPTY_NOT_FINAL is report-only; no manifest checkpoint; general --resume refetches",
        "failed_retry": "--retry-failures",
        "quota": "LocalKrxOpenApiQuota.reserve_attempt before every client HTTP attempt",
        "sequential_markets": True,
        "historical_list_shrs_replay": False,
    })
    _write_json(output / "coverage_summary.json", {"target_start": TARGET_START, "target_end": TARGET_END, "coverage": coverage_payload, "counters": counters})
    _write_json(output / "quota_summary.json", {key: counters.get(key) for key in ("quota_usage_date_kst", "quota_global_before", "quota_global_after", "quota_remaining_after", "krx_open_api_attempt_count", "retry_attempt_count", "http_401_count", "http_403_count", "http_429_count", "http_5xx_count", "transport_error_count")})
    _write_json(output / "samsung_listed_shares_evidence.json", samsung)
    _write_json(output / "partition_integrity_summary.json", {
        "integrity_scan_count": counters.get("partition_integrity_scan_count", 0),
        "integrity_error_count": counters.get("partition_integrity_error_count", 0),
        "content_hash_mismatch_count": counters.get("content_hash_mismatch_count", 0),
        "file_hash_mismatch_count": counters.get("file_hash_mismatch_count", 0),
        "duplicate_ticker_count": counters.get("duplicate_ticker_count", 0),
        "cross_market_ticker_conflict_count": counters.get("cross_market_ticker_conflict_count", 0),
    })
    _write_json(output / "live_pilot_summary.json", pilot_summary)
    _write_json(output / "live_diagnostic_summary.json", diagnostic_summary)
    _write_json(output / "legacy_live_evidence.json", legacy_live_evidence)
    _write_json(output / "full_regression_summary.json", full_regression)
    with (output / "failed_dates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", "market", "status", "error_code"])
        written_failures: set[tuple[str, str, str, str]] = set()
        for item in pilot_summary.get("failure_observations", []):
            row = (str(item.get("date")), str(item.get("market")), str(item.get("status", "FAILED")), str(item.get("error_code")))
            written_failures.add(row)
            writer.writerow(row)
        for item in pilot_summary.get("dates", []):
            for observation in item.get("failure_observations", []):
                row = (str(observation.get("date")), str(observation.get("market")), str(observation.get("status", "FAILED")), str(observation.get("error_code")))
                written_failures.add(row)
                writer.writerow(row)
            # Preserve the prior bounded-pilot blocker even when its old
            # runner did not persist per-market failure observations.
            if "BLOCKED_KRX_SCHEMA" in item.get("blockers", []):
                for market in MARKETS:
                    row = (str(item.get("date")), market, "FAILED", "BLOCKED_KRX_SCHEMA")
                    if row not in written_failures:
                        writer.writerow(row)
                        written_failures.add(row)
        for item in diagnostic_summary.get("dates", []):
            for observation in item.get("failure_observations", []):
                row = (str(observation.get("date")), str(observation.get("market")), str(observation.get("status", "FAILED")), str(observation.get("error_code")))
                if row not in written_failures:
                    writer.writerow(row)
                    written_failures.add(row)
    with (output / "coverage_by_year.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["year", "candidate_dates", "complete_dates", "finalized_no_data_dates", "failed_dates", "partial_dates", "missing_dates", "complete_partitions", "row_count"])
        for year, values in coverage_payload.get("coverage_by_year", {}).items():
            writer.writerow([year, *[values.get(key, 0) for key in ("candidate_dates", "complete_dates", "finalized_no_data_dates", "failed_dates", "partial_dates", "missing_dates", "complete_partitions", "row_count")]])
    _write_json(output / "cross_market_conflict_evidence.json", {
        "count": coverage_payload.get("cross_market_ticker_conflict_count", 0),
        "samples": coverage_payload.get("cross_market_conflict_samples", []),
    })
    _write_json(output / "missing_coverage_evidence.json", {
        "candidate_date_count": coverage_payload.get("candidate_date_count", 0),
        "unexplained_missing_date_count": coverage_payload.get("unexplained_missing_date_count", 0),
        "unexplained_missing_partition_count": coverage_payload.get("unexplained_missing_partition_count", 0),
        "missing_dates": coverage_payload.get("missing_dates", []),
    })
    diagnostic_diagnostics = diagnostic_summary.get("diagnostics", [])
    schema_evidence_status = _schema_evidence_status(diagnostic_summary)
    _write_json(output / "schema_blocker_evidence.json", {
        "status": schema_evidence_status,
        "observations": diagnostic_diagnostics,
        "legacy_evidence": legacy_live_evidence,
        "note": "Current FIX04 diagnostic has not run; legacy evidence is preserved separately." if schema_evidence_status == "NOT_RUN" else None,
    })
    phase_results = {
        "offline_validation": {
            "status": "PASS" if mode == "offline" and not blockers else ("NOT_RUN" if mode != "offline" else status),
            "tests": counters.get("offline_test_passed", 0),
            "blockers": [] if mode != "offline" else blockers,
        },
        "live_diagnostic": {
            "status": diagnostic_summary.get("status", "NOT_RUN"),
            "attempts": diagnostic_summary.get("request_count", diagnostic_summary.get("audit", {}).get("request_count", 0)),
            "blockers": diagnostic_summary.get("blockers", []),
        },
        "live_pilot": {
            "status": pilot_summary.get("status", "NOT_RUN"),
            "attempts": pilot_summary.get("request_count", pilot_summary.get("audit", {}).get("request_count", 0)),
            "blockers": pilot_summary.get("blockers", []),
        },
        "samsung_evidence": {
            "status": samsung.get("status", "NOT_RUN"),
            "blockers": samsung.get("blockers", []),
            "observation_count": len(samsung.get("observations", [])),
        },
        "full_regression": {
            "status": "PASS" if full_regression.get("completed") and full_regression.get("return_code") == 0 and full_regression.get("failed", 0) == 0 else "INCOMPLETE",
            "completed": bool(full_regression.get("completed")),
            "return_code": full_regression.get("return_code"),
            "passed": full_regression.get("passed", 0),
            "failed": full_regression.get("failed", 0),
        },
        "production_coverage": {
            "status": "PASS" if coverage_ready else "INCOMPLETE",
            "candidate_date_count": coverage_payload.get("candidate_date_count", 0),
            "complete_date_count": coverage_payload.get("complete_date_count", 0),
            "finalized_no_data_date_count": coverage_payload.get("finalized_no_data_date_count", 0),
            "missing_date_count": coverage_payload.get("unexplained_missing_date_count", 0),
            "missing_partition_count": coverage_payload.get("unexplained_missing_partition_count", 0),
        },
    }
    known_phase_blockers: list[str] = []
    if diagnostic_summary.get("status") == "NOT_RUN":
        known_phase_blockers.append("LIVE_DIAGNOSTIC_NOT_RUN")
    if pilot_summary.get("status") == "NOT_RUN":
        known_phase_blockers.append("LIVE_PILOT_NOT_RUN")
    if mode == "live-pilot" and samsung.get("status") != "PASS":
        known_phase_blockers.append("SAMSUNG_EVIDENCE_INCOMPLETE")
    if not full_regression.get("completed") or full_regression.get("return_code") != 0 or full_regression.get("failed", 0) != 0:
        known_phase_blockers.append("FULL_REGRESSION_INCOMPLETE")
    elif mode != "live-pilot":
        known_phase_blockers.append("SAMSUNG_EVIDENCE_INCOMPLETE")
    if not coverage_ready:
        known_phase_blockers.append("PRODUCTION_COVERAGE_INCOMPLETE")
    summary = {
        "architecture_version": "KRX_HISTORICAL_BACKFILL_V01",
        "fix_version": FIX_VERSION,
        "mode": mode,
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": validation_source_head,
        "end_head": None,
        "status": status,
        "recommendation": recommendation,
        "blockers": blockers,
        "known_phase_blockers": known_phase_blockers,
        "phase_results": phase_results,
        "counters": counters,
        "production_diff_guard": diff_guard,
        "production_coverage": phase_results["production_coverage"],
        "full_regression": full_regression,
        "legacy_live_evidence": legacy_live_evidence,
        "test_output_tail": test_tail,
    }
    _write_json(output / "krx_historical_backfill_v01_summary.json", summary)
    artifacts = sorted(path.name for path in output.iterdir() if path.is_file() and path.name != "krx_historical_backfill_v01_manifest.json")
    _write_json(output / "krx_historical_backfill_v01_manifest.json", {
        "architecture_version": "KRX_HISTORICAL_BACKFILL_V01",
        "fix_version": FIX_VERSION,
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": validation_source_head,
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
        f"FIX_VERSION: {FIX_VERSION}\nSTATUS: {status}\nRECOMMENDATION: {recommendation}\n\n"
        "Raw KRX snapshots preserve source values without adjustment, filtering, or historical corporate-action replay.\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KRX historical raw stock backfill v01")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live-diagnostic", action="store_true")
    mode.add_argument("--live-pilot", action="store_true")
    mode.add_argument("--production-coverage", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    args = parser.parse_args()
    selected_mode = "offline" if args.offline else "live-diagnostic" if args.live_diagnostic else "live-pilot" if args.live_pilot else "production-coverage"
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    result = run(selected_mode, output, raw_root)
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "blockers": result["blockers"]}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
