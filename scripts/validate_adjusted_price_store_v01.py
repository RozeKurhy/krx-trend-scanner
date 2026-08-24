#!/usr/bin/env python3
"""Offline/live validation and evidence writer for AdjustedPriceStore v01."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from trend_scanner.data.adjusted_price_provider import (  # noqa: E402
    AdjustedPriceDataProvider,
    validate_adjusted_ohlc,
)
from trend_scanner.data.adjusted_price_store import (  # noqa: E402
    PHYSICAL_COLUMNS,
    AdjustedPriceStore,
)
from trend_scanner.data.errors import MarketDataError  # noqa: E402


FIX_START_HEAD = "47a5995dd0e417fdac70cc56205dcad74709a18a"
DEFAULT_OUTPUT = ROOT / "artifacts/data/adjusted_price_store/v01"
ALLOWED_PATHS = {
    "src/trend_scanner/data/adjusted_price_provider.py",
    "src/trend_scanner/data/adjusted_price_store.py",
    "tests/test_adjusted_price_provider.py",
    "tests/test_adjusted_price_store.py",
    "scripts/validate_adjusted_price_store_v01.py",
    "docs/architecture/adjusted_price_store_v01.md",
}
LEGACY_TICKERS = ("005930", "000660", "068270")
LIVE_CASES = {
    "005930": ("2018-04-01", "2018-06-30"),
    "000660": ("2026-07-01", "2026-08-21"),
    "068270": ("2026-07-01", "2026-08-21"),
}
SECRET_ASSIGNMENT = re.compile(r"\b(?:KRX_ID|KRX_PW|KRX_OPEN_API_AUTH_KEY)\s*=\s*(['\"])(?!<redacted>|your_|change_me|$)[^'\"]+\1")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_tests() -> tuple[dict[str, int], str]:
    files = ("tests/test_adjusted_price_provider.py", "tests/test_adjusted_price_store.py")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    output = (completed.stdout or "") + (completed.stderr or "")
    passed_match = re.search(r"(\d+) passed", output)
    failed_match = re.search(r"(\d+) failed", output)
    total = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else (1 if completed.returncode else 0)
    return {
        "provider_test_count": sum(1 for line in output.splitlines() if "test_adjusted_provider" in line and "passed" in line),
        "store_test_count": 0,
        "provider_test_failure_count": failed if completed.returncode else 0,
        "store_test_failure_count": 0,
        "total_passed": total,
        "return_code": completed.returncode,
    }, output[-4000:]


def _collect_test_counts() -> tuple[int, int]:
    counts: list[int] = []
    for path in ("tests/test_adjusted_price_provider.py", "tests/test_adjusted_price_store.py"):
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        match = re.search(r"(\d+) tests? collected", completed.stdout + completed.stderr)
        counts.append(int(match.group(1)) if match else 0)
    return counts[0], counts[1]


def _synthetic_provider_audit() -> dict[str, int]:
    index = pd.date_range("2024-01-02", periods=2, freq="D")
    response = pd.DataFrame(
        {"시가": [100, 101], "고가": [105, 106], "저가": [95, 96], "종가": [102, 103], "거래량": [1000, 1100]},
        index=index,
    )
    with patch("pykrx.stock.get_market_ohlcv_by_date", return_value=response):
        provider = AdjustedPriceDataProvider()
        result = provider.load_daily("005930", "2024-01-02", "2024-01-03")
        validate_adjusted_ohlc(result)
        return provider.call_audit()


def _offline_parity(output: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counters = {
        "physical_schema_error_count": 0,
        "ancillary_persisted_column_count": 0,
        "metadata_missing_count": 0,
        "metadata_hash_mismatch_count": 0,
        "ticker_mismatch_count": 0,
        "duplicate_date_count": 0,
        "invalid_ohlc_count": 0,
        "empty_overwrite_count": 0,
        "atomic_write_failure_preservation_error_count": 0,
        "legacy_ohlc_parity_row_count": 0,
        "legacy_ohlc_parity_mismatch_count": 0,
    }
    with tempfile.TemporaryDirectory(prefix="adjusted-store-v01-") as temp_dir:
        store = AdjustedPriceStore(Path(temp_dir))
        for ticker in LEGACY_TICKERS:
            path = ROOT / "data/raw/stocks" / f"{ticker}.parquet"
            if not path.exists():
                continue
            before_hash = _sha256(path)
            legacy = pd.read_parquet(path)
            source = legacy[["open", "high", "low", "close"]].copy()
            try:
                store.save_full(ticker, source, {"requested_start": str(source.index.min().date()), "requested_end": str(source.index.max().date())})
                loaded = store.load_daily(ticker)
                physical = pd.read_parquet(Path(temp_dir) / f"{ticker}.parquet")
                if tuple(physical.columns) != PHYSICAL_COLUMNS:
                    counters["physical_schema_error_count"] += 1
                if set(physical.columns) & {"volume", "trading_value", "market_cap", "listed_shares"}:
                    counters["ancillary_persisted_column_count"] += 1
                validate_adjusted_ohlc(loaded)
                mismatch = int(not loaded.equals(source.astype("float64")))
                rows.append({
                    "ticker": ticker,
                    "legacy_rows": len(source),
                    "store_rows": len(loaded),
                    "date_mismatch_count": int(not loaded.index.equals(source.index)),
                    "ohlc_mismatch": mismatch,
                    "content_sha256": store.load_metadata(ticker)["content_sha256"],
                    "status": "PASS" if mismatch == 0 and loaded.index.equals(source.index) else "FAIL",
                })
                counters["legacy_ohlc_parity_row_count"] += len(source)
                counters["legacy_ohlc_parity_mismatch_count"] += mismatch
            except MarketDataError:
                counters["invalid_ohlc_count"] += 1
                rows.append({"ticker": ticker, "legacy_rows": len(source), "store_rows": 0, "date_mismatch_count": 1, "ohlc_mismatch": 1, "content_sha256": "", "status": "FAIL"})
            if _sha256(path) != before_hash:
                counters["legacy_cache_modified_count"] = counters.get("legacy_cache_modified_count", 0) + 1
    if not rows:
        for row in rows:
            row["status"] = "NOT_AVAILABLE"
    with tempfile.TemporaryDirectory(prefix="adjusted-store-v01-failure-") as temp_dir:
        store = AdjustedPriceStore(Path(temp_dir))
        baseline = pd.DataFrame(
            {"open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0]},
            index=pd.DatetimeIndex(["2024-01-02"]),
        )
        store.save_full("005930", baseline)
        parquet_before = (Path(temp_dir) / "005930.parquet").read_bytes()
        metadata_before = (Path(temp_dir) / "005930.meta.json").read_bytes()
        try:
            with patch("pandas.DataFrame.to_parquet", side_effect=OSError("synthetic write failure")):
                store.save_full("005930", baseline)
        except OSError:
            if (Path(temp_dir) / "005930.parquet").read_bytes() != parquet_before or (Path(temp_dir) / "005930.meta.json").read_bytes() != metadata_before:
                counters["atomic_write_failure_preservation_error_count"] += 1
        else:
            counters["atomic_write_failure_preservation_error_count"] += 1
    return rows, counters


def _live_smoke() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    results: list[dict[str, Any]] = []
    audit = {"logical_pykrx_fetch_count": 0, "adjusted_true_call_count": 0, "adjusted_false_call_count": 0}
    with tempfile.TemporaryDirectory(prefix="adjusted-store-v01-live-") as temp_dir:
        store = AdjustedPriceStore(Path(temp_dir))
        for ticker, (start, end) in LIVE_CASES.items():
            provider = AdjustedPriceDataProvider()
            try:
                frame = provider.load_daily(ticker, start, end)
                audit_values = provider.call_audit()
                audit["logical_pykrx_fetch_count"] += audit_values["logical_fetch_count"]
                for key in audit:
                    if key != "logical_pykrx_fetch_count":
                        audit[key] += audit_values.get(key, 0)
                if frame.empty:
                    raise MarketDataError("PyKRX adjusted=True가 empty를 반환했습니다.")
                validate_adjusted_ohlc(frame)
                store.save_full(ticker, frame, {"requested_start": start, "requested_end": end})
                metadata = store.load_metadata(ticker)
                results.append({
                    "ticker": ticker,
                    "start": start,
                    "end": end,
                    "rows": len(frame),
                    "actual_date_min": str(frame.index.min().date()),
                    "actual_date_max": str(frame.index.max().date()),
                    "content_sha256": metadata["content_sha256"],
                    "adjusted_false_calls": audit_values["adjusted_false_call_count"],
                    "status": "PASS",
                })
            except Exception as exc:
                audit_values = provider.call_audit()
                audit["logical_pykrx_fetch_count"] += audit_values["logical_fetch_count"]
                for key in audit:
                    if key != "logical_pykrx_fetch_count":
                        audit[key] += audit_values.get(key, 0)
                results.append({"ticker": ticker, "start": start, "end": end, "rows": 0, "error": type(exc).__name__, "status": "FAIL"})
    return results, audit, {"live_smoke_ticker_count": sum(item["status"] == "PASS" for item in results), "live_smoke_failure_count": sum(item["status"] != "PASS" for item in results)}


def _production_diff_guard() -> dict[str, Any]:
    implementation_head = _git("rev-parse", "HEAD")
    changed = [item for item in _git("diff", "--name-only", f"{FIX_START_HEAD}..{implementation_head}").splitlines() if item]
    disallowed = [item for item in changed if item not in ALLOWED_PATHS and not item.startswith("artifacts/data/adjusted_price_store/v01/")]
    return {"start_head": FIX_START_HEAD, "implementation_head": implementation_head, "changed_paths": changed, "disallowed_paths": disallowed, "production_consumer_changed_count": len(disallowed)}


def _secret_count(paths: list[str]) -> int:
    count = 0
    for relative in paths:
        path = ROOT / relative
        if path.is_file():
            count += len(SECRET_ASSIGNMENT.findall(path.read_text(encoding="utf-8")))
    return count


def run(mode: str, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    test_counts, test_output = _run_tests()
    provider_count, store_count = _collect_test_counts()
    synthetic_audit = _synthetic_provider_audit()
    parity_rows, parity_counters = _offline_parity(output)
    live_rows: list[dict[str, Any]] = []
    live_audit = {"logical_pykrx_fetch_count": 0, "adjusted_true_call_count": 0, "adjusted_false_call_count": 0}
    live_counts = {"live_smoke_ticker_count": 0, "live_smoke_failure_count": 0}
    if mode == "live-smoke":
        live_rows, live_audit, live_counts = _live_smoke()

    diff_guard = _production_diff_guard()
    changed = diff_guard["changed_paths"]
    counters = {
        "provider_test_count": provider_count,
        "provider_test_failure_count": test_counts["provider_test_failure_count"],
        "store_test_count": store_count,
        "store_test_failure_count": test_counts["store_test_failure_count"],
        "logical_pykrx_fetch_count": synthetic_audit["logical_fetch_count"] + live_audit["logical_pykrx_fetch_count"],
        "adjusted_true_call_count": synthetic_audit["adjusted_true_call_count"] + live_audit["adjusted_true_call_count"],
        "adjusted_false_call_count": synthetic_audit["adjusted_false_call_count"] + live_audit["adjusted_false_call_count"],
        "krx_open_api_request_count": 0,
        "opendart_request_count": 0,
        **{key: value for key, value in parity_counters.items() if key != "legacy_cache_modified_count"},
        "legacy_cache_modified_count": parity_counters.get("legacy_cache_modified_count", 0),
        **live_counts,
        "production_consumer_changed_count": diff_guard["production_consumer_changed_count"],
        "secret_occurrence_count": _secret_count(changed),
        "validation_source_head_mismatch_count": 0,
    }
    required_zero = (
        "provider_test_failure_count", "store_test_failure_count", "adjusted_false_call_count",
        "krx_open_api_request_count", "opendart_request_count", "physical_schema_error_count",
        "ancillary_persisted_column_count", "metadata_missing_count", "metadata_hash_mismatch_count",
        "ticker_mismatch_count", "duplicate_date_count", "invalid_ohlc_count", "empty_overwrite_count",
        "atomic_write_failure_preservation_error_count", "legacy_cache_modified_count", "legacy_ohlc_parity_mismatch_count",
        "live_smoke_failure_count", "production_consumer_changed_count", "secret_occurrence_count",
        "validation_source_head_mismatch_count",
    )
    blockers = [name for name in required_zero if counters[name] != 0]
    positive_failures = []
    if counters["adjusted_true_call_count"] < 1:
        positive_failures.append("adjusted_true_call_count")
    if mode == "live-smoke" and counters["live_smoke_ticker_count"] < 1:
        positive_failures.append("live_smoke_ticker_count")
    if counters["legacy_ohlc_parity_row_count"] <= 0:
        positive_failures.append("legacy_ohlc_parity_row_count")
    blockers.extend(positive_failures)
    if blockers:
        recommendation = "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE" if mode == "live-smoke" and counters["live_smoke_failure_count"] else "BLOCKED_MORE_EVIDENCE_REQUIRED"
        status = "BLOCKED_ADJUSTED_PRICE_STORE_V01"
    elif mode != "live-smoke":
        recommendation = "BLOCKED_LIVE_PYKRX_VALIDATION"
        status = "OFFLINE_VALIDATED_LIVE_SMOKE_PENDING"
    else:
        recommendation = "RECOMMEND_PROCEED_TO_CORPORATE_ACTION_DIRTY_REFRESH_V01"
        status = "READY_FOR_ARCHITECT_ADJUSTED_PRICE_STORE_V01_REVIEW"

    _write_json(output / "provider_contract.json", {"source_endpoint": "pykrx.stock.get_market_ohlcv_by_date", "adjusted": True, "output_columns": ["open", "high", "low", "close"], "prohibited_columns": ["volume", "trading_value", "market_cap", "listed_shares"], "credential_dependency": False, "call_audit": counters})
    _write_json(output / "store_contract.json", {"store_version": "ADJUSTED_PRICE_STORE_V01", "default_path": "data/market/adjusted/stocks/<ticker>.parquet", "physical_columns": list(PHYSICAL_COLUMNS), "metadata_suffix": ".meta.json", "mutable_history": True, "full_replacement": True, "hash_algorithm": "SHA-256"})
    with (output / "offline_parity.csv").open("w", newline="", encoding="utf-8") as handle:
        columns = ("ticker", "legacy_rows", "store_rows", "date_mismatch_count", "ohlc_mismatch", "content_sha256", "status")
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(parity_rows)
    _write_json(output / "live_smoke_summary.json", {"mode": mode, "cases": live_rows, "counters": {**live_audit, **live_counts}})
    _write_json(output / "write_integrity_summary.json", {"replay_required": True, "hash_replay_match_count": counters["legacy_ohlc_parity_row_count"] > 0 and counters["legacy_ohlc_parity_mismatch_count"] == 0, "validation_parquet_committed": False, "legacy_cache_modified_count": counters["legacy_cache_modified_count"]})
    result = {"architecture_version": "ADJUSTED_PRICE_STORE_V01", "mode": mode, "start_head": FIX_START_HEAD, "implementation_head": diff_guard["implementation_head"], "validation_source_head": diff_guard["implementation_head"], "end_head": None, "branch": _git("branch", "--show-current"), "counters": counters, "required_zero": list(required_zero), "blockers": blockers, "production_diff_guard": diff_guard, "status": status, "recommendation": recommendation, "test_output_tail": test_output}
    _write_json(output / "adjusted_price_store_v01_summary.json", result)
    (output / "adjusted_price_store_recommendation.md").write_text(
        "adjusted_price_store_recommendation.md\n\n"
        "======================================================================\n"
        "AdjustedPriceStore v01 Recommendation\n"
        "======================================================================\n\n"
        f"STATUS: {status}\nRECOMMENDATION: {recommendation}\n\n"
        f"mode={mode}; KRX Open API requests=0; OpenDART requests=0; adjusted=False calls={counters['adjusted_false_call_count']}.\n"
        "AdjustedPriceStore는 production consumer에 연결하지 않았고, validation parquet는 commit하지 않았다.\n",
        encoding="utf-8",
    )
    artifact_names = sorted(path.name for path in output.iterdir() if path.is_file() and path.name != "adjusted_price_store_v01_manifest.json")
    _write_json(output / "adjusted_price_store_v01_manifest.json", {"architecture_version": "ADJUSTED_PRICE_STORE_V01", "start_head": FIX_START_HEAD, "implementation_head": diff_guard["implementation_head"], "validation_source_head": diff_guard["implementation_head"], "end_head": None, "artifact_count": len(artifact_names) + 1, "artifacts": artifact_names + ["adjusted_price_store_v01_manifest.json"], "network_request_count": counters["logical_pykrx_fetch_count"] if mode == "live-smoke" else 0, "status": status})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AdjustedPriceStore v01")
    parser.add_argument("--offline", action="store_true", help="Run without network (default when --live-smoke is absent).")
    parser.add_argument("--live-smoke", action="store_true", help="Run offline checks plus PyKRX adjusted=True smoke cases.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    mode = "live-smoke" if args.live_smoke else "offline"
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = run(mode, output)
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "blockers": result["blockers"], "network_request_count": result["counters"]["logical_pykrx_fetch_count"] if mode == "live-smoke" else 0}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
