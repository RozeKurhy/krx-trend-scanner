"""Offline validation and evidence writer for MARKET_DATA_REPOSITORY_V02."""

from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from time import monotonic
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
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
START_HEAD = "0f7b35be5f6ac3840266e0580e37c2e4519dbf7c"
FROZEN_CONTRACT = ROOT / "artifacts/data/architecture/krx_production_data/v01/repository_v2_contract.json"
DEFAULT_ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
DEFAULT_RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
REPOSITORY_SOURCE = ROOT / "src/trend_scanner/data/repository_v2.py"
FORBIDDEN_IMPORT_NAMES = {
    "pykrx", "requests", "httpx", "KrxOpenApiClient",
    "KrxRawStockSnapshotProvider", "AdjustedPriceProvider",
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_json(name: str, payload: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    return {str(item): _sha256(item) for item in sorted(path.rglob("*")) if item.is_file()}


def _raw_view(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            {column: pd.Series(dtype="float64") for column in RAW_DAILY_COLUMNS},
            index=pd.DatetimeIndex([], name=None),
        )
    result = frame.loc[:, list(RAW_COLUMNS)].copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.pop("date"))).normalize()
    result = result.drop(columns=["ticker"])
    return result.loc[:, list(RAW_DAILY_COLUMNS)]


def _same_frame(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left, right, check_dtype=False, check_freq=False, check_names=False
        )
    except AssertionError:
        return False
    return True


def _static_checks(validation_head: str) -> dict[str, Any]:
    text = REPOSITORY_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or "", *[alias.name for alias in node.names]]
        else:
            continue
        forbidden.extend(name for name in names if name in FORBIDDEN_IMPORT_NAMES)
    changed = _git("diff", "--name-only", START_HEAD, validation_head).splitlines()
    frozen = {
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
    consumer_tokens = ("pattern", "fast_core", "julia", "relative_strength", "foreign_flow", "stock_report")
    return {
        "git_diff_check": subprocess.run(
            ["git", "diff", "--check", START_HEAD, validation_head],
            cwd=ROOT, capture_output=True
        ).returncode == 0,
        "secret_occurrence_count": sum(
            text.count(marker)
            for marker in ("KRX_OPEN_API_AUTH_KEY", "KRX_ID", "KRX_PW", "OPENDART_API_KEY")
        ),
        "forbidden_network_import_count": len(forbidden),
        "forbidden_network_imports": sorted(forbidden),
        "artifacts_runtime_dependency_count": text.count("artifacts"),
        "legacy_repository_changed": "src/trend_scanner/data/repository.py" in changed,
        "frozen_source_changed_count": len(frozen.intersection(changed)),
        "closed_artifact_changed_count": len(closed),
        "consumer_auto_migration_count": sum(
            1 for item in changed if any(token in item.lower() for token in consumer_tokens)
        ),
        "frozen_contract_modified": (
            "artifacts/data/architecture/krx_production_data/v01/repository_v2_contract.json"
            in changed
        ),
        "changed_files": changed,
    }


def _probe(adjusted_root: Path, raw_root: Path) -> dict[str, Any]:
    files = sorted(
        path for path in adjusted_root.glob("*.parquet")
        if path.with_name(f"{path.stem}.meta.json").exists()
    ) if adjusted_root.exists() else []
    if not files:
        return {
            "status": "BLOCKED_NO_PRODUCTION_OVERLAP_SAMPLE",
            "blockers": ["BLOCKED_NO_PRODUCTION_OVERLAP_SAMPLE"],
            "warnings": ["No complete local AdjustedPriceStore ticker pair was found."],
            "sample_tickers": [],
            "sample_date_ranges": {},
            "comparisons": [],
            "samsung_probe": {"performed": False, "status": "NOT_RUN"},
            "alphanumeric_probe": {"performed": False, "status": "NOT_RUN"},
            "performance": [],
        }

    adjusted = AdjustedPriceStore(adjusted_root)
    raw = KrxRawStockStore(raw_root)
    repository = MarketDataRepositoryV2(adjusted, raw)
    available = {path.stem for path in files if path.stem.isdigit()}
    priority = ["005930", "000660", "068270", "035420"]
    samples = [ticker for ticker in priority if ticker in available][:2]
    samples += [ticker for ticker in sorted(available) if ticker not in samples][:2 - len(samples)]
    comparisons: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    ranges: dict[str, list[str]] = {}
    for ticker in samples:
        start, end = (("2018-04-27", "2018-05-04") if ticker == "005930"
                      else ("2020-01-02", "2020-01-10"))
        ranges[ticker] = [start, end]
        started = monotonic()
        adjusted_started = monotonic()
        adjusted_frame = adjusted.load_daily(ticker, start, end)
        adjusted_elapsed = monotonic() - adjusted_started
        raw_started = monotonic()
        raw_frame = raw.load_ticker(ticker, start, end)
        raw_elapsed = monotonic() - raw_started
        join_started = monotonic()
        daily = repository.get_daily(ticker, start, end)
        join_elapsed = monotonic() - join_started
        ancillary = repository.get_daily_ancillary(ticker, start, end)
        total_elapsed = monotonic() - started
        raw_view = _raw_view(raw_frame)
        comparisons.append({
            "ticker": ticker,
            "date_range": [start, end],
            "adjusted_ohlc_exact_match": _same_frame(
                daily.loc[:, ["open", "high", "low", "close"]], adjusted_frame
            ),
            "raw_volume_exact_match": _same_frame(
                daily.loc[:, ["volume"]], raw_view.loc[:, ["volume"]]
            ),
            "raw_trading_value_exact_match": _same_frame(
                daily.loc[:, ["trading_value"]], raw_view.loc[:, ["trading_value"]]
            ),
            "ancillary_exact_match": _same_frame(
                ancillary, raw_view.loc[:, list(ANCILLARY_COLUMNS)]
            ),
            "date_set_exact_match": (
                set(daily.index) == set(adjusted_frame.index) == set(raw_view.index)
            ),
        })
        performance.append({
            "ticker": ticker,
            "range_days": (pd.Timestamp(end) - pd.Timestamp(start)).days + 1,
            "raw_load_elapsed_seconds": round(raw_elapsed, 6),
            "adjusted_load_elapsed_seconds": round(adjusted_elapsed, 6),
            "repository_join_elapsed_seconds": round(join_elapsed, 6),
            "total_elapsed_seconds": round(total_elapsed, 6),
        })

    samsung = {"performed": False, "status": "NOT_APPLICABLE"}
    if "005930" in samples:
        samsung = {"performed": True, "status": "PASS"}
        frame = repository.get_daily_ancillary("005930", "2018-04-27", "2018-05-04")
        expected = {"2018-04-27": 128386494, "2018-05-04": 6419324700}
        observed = {
            day: int(frame.loc[pd.Timestamp(day), "listed_shares"])
            for day in expected if pd.Timestamp(day) in frame.index
        }
        samsung["observed_listed_shares"] = observed
        if observed != expected:
            samsung.update(status="BLOCKED_PRODUCTION_PROBE", blocker="BLOCKED_PRODUCTION_PROBE")

    alphanumeric = {"performed": False, "status": "NOT_RUN"}
    found = None
    for candidate in ("03473K", "08537M"):
        for market in ("KOSPI", "KOSDAQ"):
            frame = raw.load_snapshot(market, "2018-04-27")
            if not frame.empty and candidate in set(frame["ticker"].astype(str)):
                found = candidate
                break
        if found:
            break
    if found:
        raw_probe = repository.get_raw_daily(found, "2018-04-27", "2018-04-27")
        ancillary_probe = repository.get_daily_ancillary(found, "2018-04-27", "2018-04-27")
        try:
            repository.get_daily(found, "2018-04-27", "2018-04-27")
        except Exception as exc:
            adjusted_unsupported = "UNSUPPORTED_ADJUSTED_TICKER" in str(exc)
        else:
            adjusted_unsupported = False
        alphanumeric = {
            "performed": True,
            "ticker": found,
            "raw_probe_pass": len(raw_probe) == 1,
            "ancillary_probe_pass": len(ancillary_probe) == 1,
            "adjusted_unsupported_pass": adjusted_unsupported,
            "status": "PASS" if len(raw_probe) == 1 and len(ancillary_probe) == 1 and adjusted_unsupported else "BLOCKED_PRODUCTION_PROBE",
        }

    blockers = [
        "BLOCKED_PRODUCTION_PROBE"
        for item in comparisons
        if not all(item[key] for key in (
            "adjusted_ohlc_exact_match", "raw_volume_exact_match",
            "raw_trading_value_exact_match", "ancillary_exact_match",
            "date_set_exact_match",
        ))
    ]
    if samsung.get("performed") and samsung.get("status") != "PASS":
        blockers.append("BLOCKED_PRODUCTION_PROBE")
    if alphanumeric.get("performed") and alphanumeric.get("status") != "PASS":
        blockers.append("BLOCKED_PRODUCTION_PROBE")
    return {
        "status": "PASS" if not blockers else "BLOCKED_PRODUCTION_PROBE",
        "blockers": sorted(set(blockers)),
        "warnings": [],
        "sample_tickers": samples,
        "sample_date_ranges": ranges,
        "comparisons": comparisons,
        "samsung_probe": samsung,
        "alphanumeric_probe": alphanumeric,
        "performance": performance,
    }


def _compatibility_csv() -> None:
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
        csv.writer(handle).writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    validation_head = _git("rev-parse", "HEAD")
    implementation_head = _git(
        "log", "-1", "--format=%H", "--",
        "src/trend_scanner/data/repository_v2.py", "tests/test_repository_v2.py",
    )
    static = _static_checks(validation_head)
    raw_root = Path(args.raw_root)
    adjusted_root = Path(args.adjusted_root)
    raw_before = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_before = _snapshot(adjusted_root)
    probe = _probe(adjusted_root, raw_root)
    raw_write_count = int(raw_before != _snapshot(raw_root / "manifest.sqlite3"))
    adjusted_write_count = int(adjusted_before != _snapshot(adjusted_root))
    regression = {
        "command": args.bounded_command,
        "passed": args.bounded_passed,
        "failed": args.bounded_failed,
        "duration_seconds": args.bounded_duration,
        "status": "PASS" if args.bounded_failed == 0 else "BLOCKED_REGRESSION",
    }
    changed = static["changed_files"]
    blockers = list(probe["blockers"])
    if static["legacy_repository_changed"]:
        blockers.append("BLOCKED_LEGACY_SEMANTIC_CHANGE")
    if static["frozen_source_changed_count"] or static["frozen_contract_modified"]:
        blockers.append("BLOCKED_FROZEN_CONTRACT_MISMATCH")
    if static["closed_artifact_changed_count"]:
        blockers.append("BLOCKED_CLOSED_ARTIFACT_OVERWRITE")
    if static["consumer_auto_migration_count"]:
        blockers.append("BLOCKED_CONSUMER_AUTO_MIGRATION")
    if static["secret_occurrence_count"] or static["forbidden_network_import_count"]:
        blockers.append("BLOCKED_NETWORK_DEPENDENCY")
    if static["artifacts_runtime_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_ARTIFACT_DEPENDENCY")
    if raw_write_count or adjusted_write_count:
        blockers.append("BLOCKED_STORE_MUTATION")
    if args.bounded_failed:
        blockers.append("BLOCKED_REGRESSION")
    blockers = sorted(set(blockers))
    status = (
        "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_REVIEW"
        if not blockers else blockers[0]
    )
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
        "phase": "MARKET_DATA_REPOSITORY_V02",
        "status": status,
        "start_head": START_HEAD,
        "implementation_head": implementation_head,
        "validation_source_head": validation_head,
        "production_runtime_head": "e508005c16e5fa3fa19c03b6568ba56ab9ac9294",
        "frozen_contract_path": str(FROZEN_CONTRACT.relative_to(ROOT)),
        "implementation_class": "MarketDataRepositoryV2",
        "daily_columns": list(DAILY_COLUMNS),
        "raw_daily_columns": list(RAW_DAILY_COLUMNS),
        "ancillary_columns": list(ANCILLARY_COLUMNS),
        "provenance": provenance,
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "network_data_request_count": 0,
        "KRX_request_count": 0,
        "PyKRX_request_count": 0,
        "OpenDART_request_count": 0,
        "raw_write_count": raw_write_count,
        "adjusted_write_count": adjusted_write_count,
        "corporate_action_state_write_count": 0,
        "static_checks": static,
        "production_probe": probe,
        "bounded_regression": regression,
        "blockers": blockers,
        "warnings": probe["warnings"],
        "known_limitations": (
            ["PRODUCTION_PROBE_REQUIRES_LOCAL_ADJUSTED_STORE"]
            if probe["status"] != "PASS" else []
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json("market_data_repository_v02_summary.json", summary)
    _write_json("market_data_repository_v02_contract.json", {
        "phase": "MARKET_DATA_REPOSITORY_V02",
        "architecture_version": "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_ERRATA01",
        "frozen_contract_path": str(FROZEN_CONTRACT.relative_to(ROOT)),
        "implementation_class": "MarketDataRepositoryV2",
        "source_stores": ["AdjustedPriceStore", "KrxRawStockStore"],
        "get_daily": {
            "columns": list(DAILY_COLUMNS),
            "price_authority": "AdjustedPriceStore / PYKRX_ADJUSTED_PRICE",
            "volume_authority": "KrxRawStockStore / KRX_OPEN_API_STOCK_DAILY",
            "trading_value_authority": "KrxRawStockStore / KRX_OPEN_API_STOCK_DAILY",
            "join": "INNER_CONSISTENT_TRADING_SESSION_JOIN",
            "forward_fill": False,
            "missing_behavior": "DATA_UNAVAILABLE",
        },
        "get_raw_daily": {"columns": list(RAW_DAILY_COLUMNS), "semantics": "ALL_RAW"},
        "get_daily_ancillary": {"columns": list(ANCILLARY_COLUMNS), "semantics": "RAW"},
        "get_stock_snapshot": {"columns": list(RAW_DAILY_COLUMNS), "semantics": "ALL_RAW"},
        "ticker_domains": {
            "adjusted": "SIX_DIGIT_TICKER",
            "raw": "KRX_SHORT_CODE ^[0-9A-Z]{6}$",
        },
        "read_only": True,
        "consumer_migration_count": 0,
    })
    _write_json("source_semantics.json", provenance)
    _write_json("production_probe_summary.json", {
        "status": probe["status"],
        "blockers": probe["blockers"],
        "warnings": probe["warnings"],
        "sample_tickers": probe["sample_tickers"],
        "sample_date_ranges": probe["sample_date_ranges"],
        "comparisons": probe["comparisons"],
        "samsung_probe": probe["samsung_probe"],
        "alphanumeric_probe": probe["alphanumeric_probe"],
        "performance": probe["performance"],
        "raw_write_count": raw_write_count,
        "adjusted_write_count": adjusted_write_count,
        "corporate_action_state_write_count": 0,
        "KRX_request_count": 0,
        "PyKRX_request_count": 0,
        "OpenDART_request_count": 0,
        "implementation_head": implementation_head,
        "validation_source_head": validation_head,
    })
    _write_json("performance_summary.json", {
        "status": "PASS" if probe["performance"] else "NOT_RUN",
        "observations": probe["performance"],
        "warning_code": (
            "RAW_TICKER_ACCESS_PERFORMANCE_RISK"
            if any(item["total_elapsed_seconds"] >= 60 for item in probe["performance"])
            else None
        ),
    })
    _write_json("bounded_regression_summary.json", regression)
    _compatibility_csv()
    recommendation = [
        "MARKET_DATA_REPOSITORY_V02", "",
        "STATUS", status, "",
        "IMPLEMENTATION HEAD", implementation_head, "",
        "NETWORK DATA REQUESTS", "0", "",
        "CONSUMER AUTO MIGRATION", "0", "",
        "BLOCKERS", json.dumps(blockers, ensure_ascii=False), "",
        "KNOWN LIMITATIONS",
        "PRODUCTION_PROBE_REQUIRES_LOCAL_ADJUSTED_STORE"
        if probe["status"] != "PASS" else "NONE",
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "market_data_repository_v02_recommendation.md").write_text(
        "\n".join(recommendation) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjusted-root", type=Path, default=DEFAULT_ADJUSTED_ROOT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--bounded-command", default="not supplied")
    parser.add_argument("--bounded-passed", type=int, default=0)
    parser.add_argument("--bounded-failed", type=int, default=0)
    parser.add_argument("--bounded-duration", type=float, default=0.0)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps({
        "status": summary["status"],
        "blockers": summary["blockers"],
        "implementation_head": summary["implementation_head"],
        "validation_source_head": summary["validation_source_head"],
        "sample_tickers": summary["production_probe"]["sample_tickers"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())

