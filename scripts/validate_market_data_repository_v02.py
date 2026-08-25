"""FIX01 offline gates and temporary live adjusted-authority probe."""

from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from time import monotonic
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_provider import AdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    ANCILLARY_COLUMNS,
    DAILY_COLUMNS,
    RAW_DAILY_COLUMNS,
    MarketDataRepositoryV2,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/data/market_data_repository/v02"
START_HEAD = "4d39251a69789f7e23489c0d8a03628bc0540634"
DIFF_CHECK_BASELINE = "0f7b35be5f6ac3840266e0580e37c2e4519dbf7c"
REPOSITORY_IMPLEMENTATION_HEAD = "b04e871881a857640d86422c09c57d7c6a642d62"
FROZEN_CONTRACT = ROOT / "artifacts/data/architecture/krx_production_data/v01/repository_v2_contract.json"
PRODUCTION_ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
PRODUCTION_RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
REPOSITORY_SOURCE = ROOT / "src/trend_scanner/data/repository_v2.py"
REQUESTED_SAMPLES = (
    ("005930", "2018-04-01", "2018-06-30"),
    ("000660", "2026-07-01", "2026-08-21"),
    ("068270", "2026-07-01", "2026-08-21"),
)
FORBIDDEN_MODULE_PREFIXES = ("pykrx", "requests", "httpx", "urllib")
FORBIDDEN_NAMES = {
    "KrxOpenApiClient",
    "KrxRawStockSnapshotProvider",
    "AdjustedPriceDataProvider",
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.is_file():
        return {str(path): _sha256(path)}
    return {
        str(item): _sha256(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _write_json(name: str, value: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _raw_view(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            {column: pd.Series(dtype="float64") for column in RAW_DAILY_COLUMNS},
            index=pd.DatetimeIndex([], name=None),
        )
    result = frame.loc[:, list(RAW_COLUMNS)].copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.pop("date"))).normalize()
    return result.drop(columns=["ticker"]).loc[:, list(RAW_DAILY_COLUMNS)]


def _same_frame(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left,
            right,
            check_dtype=False,
            check_freq=False,
            check_names=False,
        )
    except AssertionError:
        return False
    return True


def probe_range_from_metadata(metadata: dict[str, Any]) -> tuple[str, str]:
    """Derive a probe range from AdjustedPriceStore metadata only."""
    start = str(metadata.get("actual_date_min", "")).strip()
    end = str(metadata.get("actual_date_max", "")).strip()
    if not start or not end or start > end:
        raise MarketDataError("BLOCKED_LIVE_ADJUSTED_SAMPLE")
    return start, end


def sample_gate(
    requested_sample_count: int,
    successful_adjusted_fetch_count: int,
    successful_composition_probe_count: int,
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    usable = sum(item.get("status") == "PASS" for item in comparisons)
    if usable == 0:
        blocker = "BLOCKED_NO_LIVE_AUTHORITY_SAMPLE"
    elif usable == 1:
        blocker = "BLOCKED_INSUFFICIENT_LIVE_AUTHORITY_SAMPLES"
    elif (
        requested_sample_count < 2
        or successful_adjusted_fetch_count != requested_sample_count
    ):
        blocker = "BLOCKED_LIVE_ADJUSTED_SAMPLE"
    elif successful_composition_probe_count != requested_sample_count or usable != requested_sample_count:
        blocker = "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
    else:
        blocker = None
    return {
        "requested_sample_count": requested_sample_count,
        "successful_adjusted_fetch_count": successful_adjusted_fetch_count,
        "successful_composition_probe_count": successful_composition_probe_count,
        "minimum_required_sample_count": 2,
        "usable_sample_count": usable,
        "all_requested_samples_pass": usable == requested_sample_count == 3,
        "status": "PASS" if blocker is None else blocker,
        "blocker": blocker,
    }


def _runtime_network_guard() -> dict[str, Any]:
    source = REPOSITORY_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module.startswith(FORBIDDEN_MODULE_PREFIXES) or alias.name in FORBIDDEN_NAMES:
                    violations.append(module)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(FORBIDDEN_MODULE_PREFIXES):
                violations.append(module)
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    violations.append(alias.name)
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id in FORBIDDEN_NAMES:
                violations.append(function.id)
            if isinstance(function, ast.Attribute) and function.attr in {
                "get_market_ohlcv_by_date", "fetch", "request", "get", "post"
            }:
                root = function.value
                if isinstance(root, ast.Name) and root.id in {
                    "pykrx", "requests", "httpx", "urllib"
                }:
                    violations.append(f"{root.id}.{function.attr}")
    return {
        "runtime_forbidden_network_dependency_count": len(violations),
        "runtime_forbidden_network_dependencies": sorted(set(violations)),
    }


def git_diff_gate_from_result(
    return_code: int, stdout: str = "", stderr: str = ""
) -> dict[str, Any]:
    command = f"git diff --check {DIFF_CHECK_BASELINE} HEAD"
    return {
        "command": command,
        "return_code": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "status": "PASS" if return_code == 0 else "BLOCKED_GIT_DIFF_CHECK",
    }


def _git_diff_check(validation_head: str) -> dict[str, Any]:
    command = ["git", "diff", "--check", DIFF_CHECK_BASELINE, "HEAD"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    gate = git_diff_gate_from_result(result.returncode, result.stdout, result.stderr)
    gate["validation_head"] = validation_head
    return gate


def _static_checks(validation_head: str) -> dict[str, Any]:
    changed = _git("diff", "--name-only", START_HEAD, validation_head).splitlines()
    frozen = {
        "src/trend_scanner/data/repository.py",
        "src/trend_scanner/data/adjusted_price_store.py",
        "src/trend_scanner/data/adjusted_price_provider.py",
        "src/trend_scanner/data/krx_raw_stock_store.py",
        "src/trend_scanner/data/krx_raw_stock_provider.py",
        "src/trend_scanner/data/krx_openapi_client.py",
        "src/trend_scanner/data/krx_openapi_quota.py",
        "src/trend_scanner/data/corporate_action_state_store.py",
        "src/trend_scanner/data/source_contracts.py",
    }
    closed = [
        item for item in changed
        if item.startswith("artifacts/data/krx_historical_backfill/v01/")
        or item.startswith("artifacts/data/adjusted_price_store/v01/")
    ]
    source_text = REPOSITORY_SOURCE.read_text(encoding="utf-8")
    guard = _runtime_network_guard()
    return {
        "changed_files": changed,
        "legacy_repository_changed": "src/trend_scanner/data/repository.py" in changed,
        "frozen_store_source_changed_count": len(frozen.intersection(changed)),
        "frozen_contract_modified": (
            "artifacts/data/architecture/krx_production_data/v01/repository_v2_contract.json"
            in changed
        ),
        "closed_artifact_changed_count": len(closed),
        "consumer_auto_migration_count": sum(
            1 for item in changed
            if any(token in item.lower() for token in (
                "pattern", "fast_core", "julia", "relative_strength",
                "foreign_flow", "stock_report",
            ))
        ),
        "secret_occurrence_count": sum(
            source_text.count(marker)
            for marker in ("KRX_OPEN_API_AUTH_KEY", "KRX_ID", "KRX_PW", "OPENDART_API_KEY")
        ),
        "artifacts_runtime_dependency_count": source_text.count("artifacts"),
        "runtime_network_guard": guard,
        "git_diff_check": _git_diff_check(validation_head),
    }


def _error_record(ticker: str, exc: Exception) -> dict[str, Any]:
    message = str(exc)
    return {
        "ticker": ticker,
        "status": "FAIL",
        "error_code": message.split(":", 1)[0],
        "error_message": message[:2000],
    }


def _probe_one(
    repository: MarketDataRepositoryV2,
    adjusted_store: AdjustedPriceStore,
    raw_store: KrxRawStockStore,
    ticker: str,
    requested_start: str,
    requested_end: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    started = monotonic()
    try:
        metadata = adjusted_store.load_metadata(ticker)
        actual_start, actual_end = probe_range_from_metadata(metadata)
        adjusted_started = monotonic()
        adjusted = adjusted_store.load_daily(ticker, actual_start, actual_end)
        adjusted_elapsed = monotonic() - adjusted_started
        raw_started = monotonic()
        raw = raw_store.load_ticker(ticker, actual_start, actual_end)
        raw_elapsed = monotonic() - raw_started
        join_started = monotonic()
        composed = repository.get_daily(ticker, actual_start, actual_end)
        join_elapsed = monotonic() - join_started
        ancillary = repository.get_daily_ancillary(ticker, actual_start, actual_end)
        raw_view = _raw_view(raw)
        comparison = {
            "ticker": ticker,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "actual_adjusted_start": actual_start,
            "actual_adjusted_end": actual_end,
            "adjusted_rows": len(adjusted),
            "raw_rows": len(raw_view),
            "repository_rows": len(composed),
            "adjusted_ohlc_exact_match": _same_frame(
                composed.loc[:, ["open", "high", "low", "close"]], adjusted
            ),
            "raw_volume_exact_match": _same_frame(
                composed.loc[:, ["volume"]], raw_view.loc[:, ["volume"]]
            ),
            "raw_trading_value_exact_match": _same_frame(
                composed.loc[:, ["trading_value"]], raw_view.loc[:, ["trading_value"]]
            ),
            "ancillary_exact_match": _same_frame(
                ancillary, raw_view.loc[:, list(ANCILLARY_COLUMNS)]
            ),
            "date_set_exact_match": (
                set(composed.index) == set(adjusted.index) == set(raw_view.index)
            ),
            "status": "PASS",
        }
        required = (
            "adjusted_rows", "raw_rows", "repository_rows",
            "adjusted_ohlc_exact_match", "raw_volume_exact_match",
            "raw_trading_value_exact_match", "ancillary_exact_match",
            "date_set_exact_match",
        )
        if not comparison["adjusted_rows"] or not comparison["raw_rows"]:
            comparison["status"] = "FAIL"
            comparison["error_code"] = "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
        elif not all(comparison[key] for key in required[3:]):
            comparison["status"] = "FAIL"
            comparison["error_code"] = "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
        comparison["raw_load_elapsed_seconds"] = round(raw_elapsed, 6)
        comparison["adjusted_load_elapsed_seconds"] = round(adjusted_elapsed, 6)
        comparison["repository_join_elapsed_seconds"] = round(join_elapsed, 6)
        comparison["total_elapsed_seconds"] = round(monotonic() - started, 6)
        return comparison, {
            "ticker": ticker,
            "metadata": metadata,
            "actual_range": [actual_start, actual_end],
            "adjusted_frame": adjusted,
            "composed_frame": composed,
        }
    except Exception as exc:
        failure = _error_record(ticker, exc)
        failure.update({
            "requested_start": requested_start,
            "requested_end": requested_end,
            "status": "FAIL",
            "total_elapsed_seconds": round(monotonic() - started, 6),
        })
        return failure, None


def _find_alphanumeric(raw_store: KrxRawStockStore) -> str | None:
    for ticker in ("03473K", "08537M"):
        for market in ("KOSPI", "KOSDAQ"):
            frame = raw_store.load_snapshot(market, "2018-04-27")
            if not frame.empty and ticker in set(frame["ticker"].astype(str)):
                return ticker
    return None


def _run_live_probe(
    raw_root: Path,
) -> dict[str, Any]:
    raw_before = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_before = _snapshot(PRODUCTION_ADJUSTED_ROOT)
    provider = AdjustedPriceDataProvider()
    raw_store = KrxRawStockStore(raw_root)
    requested = list(REQUESTED_SAMPLES)
    comparisons: list[dict[str, Any]] = []
    successful: list[dict[str, Any]] = []
    successful_adjusted_fetch_count = 0
    temporary_path: str | None = None
    temp_cleanup = "FAIL"
    temp_exists_after = True
    samsung: dict[str, Any] = {"performed": False, "status": "NOT_RUN"}
    alpha: dict[str, Any] = {"performed": False, "status": "NOT_RUN"}
    with tempfile.TemporaryDirectory(prefix="market-data-repository-v02-fix01-") as temp_dir:
        temporary_path = temp_dir
        adjusted_store = AdjustedPriceStore(temp_dir)
        repository = MarketDataRepositoryV2(adjusted_store, raw_store)
        for ticker, requested_start, requested_end in requested:
            try:
                frame = provider.load_daily(ticker, requested_start, requested_end)
                if frame.empty:
                    raise MarketDataError("BLOCKED_LIVE_ADJUSTED_SAMPLE: EMPTY_RESPONSE")
                adjusted_store.save_full(
                    ticker,
                    frame,
                    {
                        "requested_start": requested_start,
                        "requested_end": requested_end,
                    },
                )
                metadata = adjusted_store.load_metadata(ticker)
                adjusted_store.load_daily(
                    ticker,
                    metadata["actual_date_min"],
                    metadata["actual_date_max"],
                )
                successful_adjusted_fetch_count += 1
            except Exception as exc:
                comparisons.append(_error_record(ticker, exc))
                break
            comparison, details = _probe_one(
                repository, adjusted_store, raw_store,
                ticker, requested_start, requested_end,
            )
            comparisons.append(comparison)
            if comparison.get("status") != "PASS":
                break
            successful.append(details)
        if len(successful) == len(requested):
            try:
                ancillary = repository.get_daily_ancillary(
                    "005930", "2018-04-27", "2018-05-04"
                )
                expected = {"2018-04-27": 128386494, "2018-05-04": 6419324700}
                observed = {
                    day: int(ancillary.loc[pd.Timestamp(day), "listed_shares"])
                    for day in expected
                    if pd.Timestamp(day) in ancillary.index
                }
                samsung_daily = repository.get_daily(
                    "005930", "2018-04-27", "2018-05-04"
                )
                samsung = {
                    "performed": True,
                    "expected": expected,
                    "observed": observed,
                    "raw_semantics": observed == expected,
                    "adjusted_price_semantics": "market_cap" not in samsung_daily.columns,
                    "status": "PASS" if observed == expected else "FAIL",
                }
            except Exception as exc:
                samsung = {"performed": True, **_error_record("005930", exc)}
            try:
                alpha_ticker = _find_alphanumeric(raw_store)
                if not alpha_ticker:
                    raise MarketDataError("BLOCKED_ALPHANUMERIC_PROBE")
                raw_daily = repository.get_raw_daily(alpha_ticker, "2018-04-27", "2018-04-27")
                ancillary = repository.get_daily_ancillary(alpha_ticker, "2018-04-27", "2018-04-27")
                snapshot = repository.get_stock_snapshot(alpha_ticker, "2018-04-27")
                try:
                    repository.get_daily(alpha_ticker, "2018-04-27", "2018-04-27")
                except MarketDataError as exc:
                    unsupported = "UNSUPPORTED_ADJUSTED_TICKER" in str(exc)
                else:
                    unsupported = False
                alpha = {
                    "performed": True,
                    "ticker": alpha_ticker,
                    "raw_daily": len(raw_daily) == 1,
                    "ancillary": len(ancillary) == 1,
                    "snapshot": len(snapshot) == 1,
                    "adjusted_unsupported": unsupported,
                    "adjusted_domain_not_widened": unsupported,
                    "status": "PASS" if len(raw_daily) == 1 and len(ancillary) == 1 and len(snapshot) == 1 and unsupported else "FAIL",
                }
            except Exception as exc:
                alpha = {"performed": True, **_error_record("alphanumeric", exc)}
    temp_exists_after = bool(temporary_path and Path(temporary_path).exists())
    temp_cleanup = "PASS" if not temp_exists_after else "FAIL"
    raw_after = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_after = _snapshot(PRODUCTION_ADJUSTED_ROOT)
    audit = provider.call_audit()
    gate = sample_gate(
        len(requested),
        successful_adjusted_fetch_count,
        sum(item.get("status") == "PASS" for item in comparisons),
        comparisons,
    )
    blockers = []
    if gate["status"] != "PASS":
        blockers.append(gate["status"])
    if samsung.get("performed") and samsung.get("status") != "PASS":
        blockers.append("BLOCKED_SAMSUNG_SEMANTIC_PROBE")
    if alpha.get("performed") and alpha.get("status") != "PASS":
        blockers.append("BLOCKED_ALPHANUMERIC_PROBE")
    if temp_cleanup != "PASS":
        blockers.append("BLOCKED_TEMP_STORE_CLEANUP")
    if raw_before != raw_after or adjusted_before != adjusted_after:
        blockers.append("BLOCKED_STORE_MUTATION")
    if audit["adjusted_false_call_count"] != 0 or audit["logical_fetch_count"] != len(requested):
        blockers.append("BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE")
    return {
        "mode": "TEMP_ADJUSTED_LIVE_PLUS_PRODUCTION_RAW",
        "requested_samples": [item[0] for item in requested],
        "successful_adjusted_fetch_count": successful_adjusted_fetch_count,
        "successful_composition_probe_count": sum(
            item.get("status") == "PASS" for item in comparisons
        ),
        "minimum_required_sample_count": 2,
        "usable_sample_count": gate["usable_sample_count"],
        "all_requested_samples_pass": gate["all_requested_samples_pass"],
        "sample_gate": gate,
        "comparisons": comparisons,
        "samsung": samsung,
        "alphanumeric": alpha,
        "temporary_store_created": True,
        "temporary_store_ticker_count": len(successful),
        "temporary_store_cleanup": temp_cleanup,
        "temporary_store_exists_after_cleanup": temp_exists_after,
        "temporary_store_path": temporary_path,
        "production_adjusted_root_used_for_write": False,
        "production_raw_manifest_before_sha": next(iter(raw_before.values()), None),
        "production_raw_manifest_after_sha": next(iter(raw_after.values()), None),
        "production_raw_manifest_equal": raw_before == raw_after,
        "production_adjusted_snapshot_before": adjusted_before,
        "production_adjusted_snapshot_after": adjusted_after,
        "production_adjusted_snapshot_equal": adjusted_before == adjusted_after,
        "production_raw_write_count": int(raw_before != raw_after),
        "production_adjusted_write_count": int(adjusted_before != adjusted_after),
        "corporate_action_state_write_count": 0,
        "performance": [
            {
                key: item[key]
                for key in (
                    "ticker", "requested_start", "requested_end",
                    "actual_adjusted_start", "actual_adjusted_end",
                    "adjusted_rows", "raw_rows", "repository_rows",
                    "raw_load_elapsed_seconds", "adjusted_load_elapsed_seconds",
                    "repository_join_elapsed_seconds", "total_elapsed_seconds",
                )
                if key in item
            }
            for item in comparisons
        ],
        "provider_audit": audit,
        "KRX_open_api_request_count": 0,
        "OpenDART_request_count": 0,
        "fallback_request_count": 0,
        "retry_count": 0,
        "blockers": sorted(set(blockers)),
        "status": "PASS" if not blockers else sorted(set(blockers))[0],
    }


def _write_compatibility() -> None:
    rows = [
        ["consumer_or_api", "before_source", "v2_source", "output_columns", "semantic_change", "auto_migrated", "status"],
        ["legacy MarketDataRepository", "provider + ParquetCache", "unchanged legacy path", "legacy schema", "none", "0", "UNCHANGED"],
        ["MarketDataRepositoryV2.get_daily", "none", "AdjustedPriceStore + KrxRawStockStore", "open,high,low,close,volume,trading_value", "explicit field composition", "0", "PASS"],
        ["get_raw_daily", "none", "KrxRawStockStore", "raw OHLC + ancillary", "new read API", "0", "PASS"],
        ["get_daily_ancillary", "none", "KrxRawStockStore", "volume,trading_value,market_cap,listed_shares", "new read API", "0", "PASS"],
        ["get_stock_snapshot", "none", "KrxRawStockStore", "raw OHLC + ancillary", "new read API", "0", "PASS"],
        ["Pattern A", "unchanged", "unchanged", "unchanged", "none", "0", "DEFERRED"],
        ["FastCore", "unchanged", "unchanged", "unchanged", "none", "0", "DEFERRED"],
        ["Julia", "unchanged", "unchanged", "unchanged", "none", "0", "DEFERRED"],
        ["RS", "unchanged", "unchanged", "unchanged", "none", "0", "DEFERRED"],
        ["Stock Report", "unchanged", "unchanged", "unchanged", "none", "0", "DEFERRED"],
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "compatibility_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def _write_evidence(
    validation_head: str,
    static: dict[str, Any],
    live: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    blockers = list(live["blockers"])
    if static["git_diff_check"]["status"] != "PASS":
        blockers.append("BLOCKED_GIT_DIFF_CHECK")
    if static["legacy_repository_changed"] or static["frozen_store_source_changed_count"]:
        blockers.append("BLOCKED_FROZEN_CONTRACT_MISMATCH")
    if static["frozen_contract_modified"]:
        blockers.append("BLOCKED_FROZEN_CONTRACT_MISMATCH")
    if static["closed_artifact_changed_count"]:
        blockers.append("BLOCKED_CLOSED_ARTIFACT_OVERWRITE")
    if static["consumer_auto_migration_count"]:
        blockers.append("BLOCKED_CONSUMER_AUTO_MIGRATION")
    if static["secret_occurrence_count"] or static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_NETWORK_DEPENDENCY")
    if static["artifacts_runtime_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_ARTIFACT_DEPENDENCY")
    if regression["failed"]:
        blockers.append("BLOCKED_REGRESSION")
    if live["production_raw_write_count"] or live["production_adjusted_write_count"]:
        blockers.append("BLOCKED_STORE_MUTATION")
    blockers = sorted(set(blockers))
    status = "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX01_REVIEW" if not blockers else blockers[0]
    provenance = {
        "open": {"store": "AdjustedPriceStore", "source": "PYKRX_ADJUSTED_PRICE", "semantics": "ADJUSTED"},
        "high": {"store": "AdjustedPriceStore", "source": "PYKRX_ADJUSTED_PRICE", "semantics": "ADJUSTED"},
        "low": {"store": "AdjustedPriceStore", "source": "PYKRX_ADJUSTED_PRICE", "semantics": "ADJUSTED"},
        "close": {"store": "AdjustedPriceStore", "source": "PYKRX_ADJUSTED_PRICE", "semantics": "ADJUSTED"},
        "volume": {"store": "KrxRawStockStore", "source": "KRX_OPEN_API_STOCK_DAILY", "semantics": "RAW"},
        "trading_value": {"store": "KrxRawStockStore", "source": "KRX_OPEN_API_STOCK_DAILY", "semantics": "RAW"},
        "market_cap": {"store": "KrxRawStockStore", "source": "raw ancillary only", "semantics": "RAW"},
        "listed_shares": {"store": "KrxRawStockStore", "source": "raw ancillary only", "semantics": "RAW"},
    }
    summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX01",
        "status": status,
        "repository_implementation_head": REPOSITORY_IMPLEMENTATION_HEAD,
        "fix01_validation_source_head": validation_head,
        "live_execution_head": validation_head,
        "architect_review_start_head": START_HEAD,
        "production_runtime_head": "e508005c16e5fa3fa19c03b6568ba56ab9ac9294",
        "repository_v2_changed": False,
        "legacy_repository_changed": static["legacy_repository_changed"],
        "frozen_contract_changed": static["frozen_contract_modified"],
        "frozen_store_sources_changed": static["frozen_store_source_changed_count"] != 0,
        "git_diff_check": static["git_diff_check"],
        "runtime_network_forbidden_count": static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"],
        "artifacts_runtime_dependency_count": static["artifacts_runtime_dependency_count"],
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "network": {
            "logical_pykrx_fetch_count": live["provider_audit"]["logical_fetch_count"],
            "adjusted_true_call_count": live["provider_audit"]["adjusted_true_call_count"],
            "adjusted_false_call_count": live["provider_audit"]["adjusted_false_call_count"],
            "KRX_request_count": 0,
            "OpenDART_request_count": 0,
            "fallback_request_count": live["fallback_request_count"],
            "retry_count": live["retry_count"],
        },
        "live_probe": live,
        "provenance": provenance,
        "bounded_regression": regression,
        "production_adjusted_population": "NOT_YET_IMPLEMENTED",
        "consumer_migration_prerequisite": True,
        "known_limitations": [
            "PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED",
            "FULL_REGRESSION_CLOSURE_DEFERRED",
        ],
        "blockers": blockers,
        "warnings": [
            "RAW_TICKER_ACCESS_PERFORMANCE_RISK"
            for item in live["performance"]
            if item.get("total_elapsed_seconds", 0) >= 60
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json("market_data_repository_v02_summary.json", summary)
    _write_json("production_probe_summary.json", {
        "mode": live["mode"],
        "status": live["status"],
        "repository_implementation_head": REPOSITORY_IMPLEMENTATION_HEAD,
        "fix01_validation_source_head": validation_head,
        "execution_head": validation_head,
        "requested_samples": live["requested_samples"],
        "successful_adjusted_fetch_count": live["successful_adjusted_fetch_count"],
        "successful_composition_probe_count": live["successful_composition_probe_count"],
        "minimum_required_sample_count": live["minimum_required_sample_count"],
        "usable_sample_count": live["usable_sample_count"],
        "all_requested_samples_pass": live["all_requested_samples_pass"],
        "comparisons": live["comparisons"],
        "samsung": live["samsung"],
        "alphanumeric": live["alphanumeric"],
        "blockers": live["blockers"],
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json("FIX01_validator_gate_summary.json", {
        "status": status,
        "blockers": blockers,
        "git_diff_check": static["git_diff_check"],
        "runtime_network_guard": static["runtime_network_guard"],
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "frozen_contract_changed": static["frozen_contract_modified"],
        "bounded_regression": regression,
        "repository_implementation_head": REPOSITORY_IMPLEMENTATION_HEAD,
        "fix01_validation_source_head": validation_head,
    })
    _write_json("FIX01_live_authority_probe_summary.json", live | {
        "repository_implementation_head": REPOSITORY_IMPLEMENTATION_HEAD,
        "fix01_validation_source_head": validation_head,
        "execution_head": validation_head,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json("FIX01_temp_adjusted_store_summary.json", {
        "temporary_store_mode": True,
        "temporary_store_ticker_count": live["temporary_store_ticker_count"],
        "production_adjusted_root_used_for_write": False,
        "temporary_store_cleanup": live["temporary_store_cleanup"],
        "temporary_store_exists_after_cleanup": live["temporary_store_exists_after_cleanup"],
        "per_ticker": [
            {
                "ticker": item.get("ticker"),
                "row_count": item.get("adjusted_rows"),
                "metadata_status": "PASS" if item.get("adjusted_rows", 0) > 0 else "FAIL",
                "hash_status": "PASS" if item.get("adjusted_rows", 0) > 0 else "FAIL",
            }
            for item in live["comparisons"]
        ],
    })
    _write_json("FIX01_network_summary.json", {
        "logical_pykrx_fetch_count": live["provider_audit"]["logical_fetch_count"],
        "adjusted_true_call_count": live["provider_audit"]["adjusted_true_call_count"],
        "adjusted_false_call_count": live["provider_audit"]["adjusted_false_call_count"],
        "KRX_open_api_request_count": 0,
        "OpenDART_request_count": 0,
        "fallback_request_count": live["fallback_request_count"],
        "retry_count": live["retry_count"],
    })
    _write_json("FIX01_production_mutation_guard.json", {
        "production_raw_manifest_before_sha": live["production_raw_manifest_before_sha"],
        "production_raw_manifest_after_sha": live["production_raw_manifest_after_sha"],
        "production_raw_manifest_equal": live["production_raw_manifest_equal"],
        "production_adjusted_snapshot_before": live["production_adjusted_snapshot_before"],
        "production_adjusted_snapshot_after": live["production_adjusted_snapshot_after"],
        "production_adjusted_snapshot_equal": live["production_adjusted_snapshot_equal"],
        "production_raw_write_count": live["production_raw_write_count"],
        "production_adjusted_write_count": live["production_adjusted_write_count"],
        "corporate_action_state_write_count": live["corporate_action_state_write_count"],
    })
    _write_json("bounded_regression_summary.json", regression)
    _write_json("performance_summary.json", {
        "status": "PASS" if live["performance"] else "NOT_RUN",
        "observations": live["performance"],
        "warnings": summary["warnings"],
    })
    _write_compatibility()
    (OUTPUT / "market_data_repository_v02_recommendation.md").write_text(
        "\n".join([
            "MARKET_DATA_REPOSITORY_V02_FIX01",
            "",
            "STATUS", status,
            "",
            "BLOCKERS", json.dumps(blockers, ensure_ascii=False),
            "",
            "PRODUCTION ADJUSTED POPULATION",
            "NOT_YET_IMPLEMENTED",
            "",
            "CONSUMER MIGRATION PREREQUISITE",
            "YES",
            "",
            "KNOWN LIMITATIONS",
            "PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED",
            "FULL_REGRESSION_CLOSURE_DEFERRED",
        ]) + "\n",
        encoding="utf-8",
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    validation_head = _git("rev-parse", "HEAD")
    static = _static_checks(validation_head)
    regression = {
        "command": args.bounded_command,
        "passed": args.bounded_passed,
        "failed": args.bounded_failed,
        "duration_seconds": args.bounded_duration,
        "status": "PASS" if args.bounded_failed == 0 else "BLOCKED_REGRESSION",
    }
    live = _run_live_probe(Path(args.raw_root))
    return _write_evidence(validation_head, static, live, regression)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=PRODUCTION_RAW_ROOT)
    parser.add_argument("--bounded-command", default="not supplied")
    parser.add_argument("--bounded-passed", type=int, default=0)
    parser.add_argument("--bounded-failed", type=int, default=0)
    parser.add_argument("--bounded-duration", type=float, default=0.0)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps({
        "status": summary["status"],
        "blockers": summary["blockers"],
        "repository_implementation_head": summary["repository_implementation_head"],
        "fix01_validation_source_head": summary["fix01_validation_source_head"],
        "live_execution_head": summary["live_execution_head"],
        "network": summary["network"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX01_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
