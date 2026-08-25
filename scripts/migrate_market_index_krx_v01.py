"""Resumable KRX Open API migration for MARKET_INDEX (1001/2001 only).

The runner derives its calendar from the closed raw-stock manifest, uses the
canonical shared quota database, writes only staging until every gate passes,
and never falls back to PyKRX.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterable, Mapping

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import (
    DEFAULT_INDEX_STORE_ROOT,
    INDEX_STORE_COLUMNS,
    INDEX_STORE_SCHEMA_VERSION,
    IndexStore,
    MARKET_INDEX_FAMILY,
    file_sha256,
    normalize_index_frame,
)
from trend_scanner.data.krx_market_index import (
    FETCH_MODE,
    KRX_MARKET_INDEX_MAP,
    MAPPING_CONTRACT_VERSION,
    MARKET_INDEX_SOURCE_NAME,
    KrxMarketIndexBuilder,
    KrxMarketIndexError,
    mapping_contract_as_dict,
    mapping_contract_sha256,
)
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/market_index_migration/v01"
STAGING_DIR = ROOT / ".cache/krx_openapi/market_index_migration/v01"
STAGING_PARQUET = STAGING_DIR / "market_index_staging.parquet"
STAGING_META = STAGING_DIR / "market_index_staging.meta.json"
OPERATIONAL_LEDGER_PATH = STAGING_DIR / "quota_run_ledger.json"
OPERATIONAL_LEDGER_SCHEMA_VERSION = "KRX_INDEX_MIGRATION_RUN_LEDGER_V01"
PRODUCTION_PARQUET = ROOT / DEFAULT_INDEX_STORE_ROOT / "market_index.parquet"
PRODUCTION_META = ROOT / DEFAULT_INDEX_STORE_ROOT / "market_index.meta.json"
START_HEAD = "9e1856df7c2a9e4232484a88220735ceaae6d0fe"
START_DATE = "2010-01-04"
END_DATE = "2026-08-21"
LEGACY_REFERENCE = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet"
LEGACY_REFERENCE_SHA256 = "82646acedfa97e85fcec7f88922ab8bc0990f7623f9d9e7a3f9bc78156dd71fa"
PILOT_DATES = ("2010-01-04", "2018-05-04", "2026-08-21")
OHLC_FIELDS = ("open", "high", "low", "close")
RS_COMPARE_FIELDS = (
    "market_rs_data_status", "market_benchmark_name", "market_benchmark_code",
    "market_benchmark_last_observation_date", "market_return_3m", "market_return_6m",
    "market_return_12m", "market_rs_3m", "market_rs_6m", "market_rs_12m",
    "market_anchor_date_3m", "market_anchor_date_6m", "market_anchor_date_12m",
)
RS_NUMERIC_FIELDS = (
    "market_return_3m", "market_return_6m", "market_return_12m",
    "market_rs_3m", "market_rs_6m", "market_rs_12m",
)
RS_IDENTITY_FIELDS = (
    "market_rs_data_status", "market_benchmark_name", "market_benchmark_code",
    "market_benchmark_last_observation_date", "market_anchor_date_3m",
    "market_anchor_date_6m", "market_anchor_date_12m",
)
MARKET_INDEX_CODES = frozenset({"1001", "2001"})
RS_NUMERIC_TOLERANCE = 1e-12
OPERATIONAL_RUN_STATES = frozenset({"STARTED", "COMPLETED", "PARTIAL", "BLOCKED"})
TERMINAL_RUN_STATES = frozenset({"COMPLETED", "PARTIAL", "BLOCKED"})
FATAL_RUN_BLOCKERS = frozenset({
    "BLOCKED_KRX_AUTH",
    "BLOCKED_KRX_TRANSPORT",
    "BLOCKED_KRX_INDEX_SCHEMA",
    "BLOCKED_STAGING_LEDGER_DIVERGENCE",
    "BLOCKED_CURRENT_SOURCE_FREEZE",
})
IMMUTABLE_VALIDATION_ANCHORS = (
    "fix01_validation_source_head",
    "fix02_validation_source_head",
    "fix03_validation_source_head",
    "fix04_validation_source_head",
)


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
    for value in (os.getenv("KRX_OPEN_API_AUTH_KEY", ""), _read_env_value(ROOT / ".env", "KRX_OPEN_API_AUTH_KEY"), _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY")):
        if value.strip():
            return value.strip()
    return ""


def safe_write_json(path: Path, value: Any, secret: str = "") -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if secret and secret in text:
        raise ValueError("secret detected in artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def atomic_write_json(path: Path, value: Any) -> None:
    """Persist operational state atomically so a crash cannot leave half JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _sha_dates(values: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def derive_raw_trading_calendar(
    start: str = START_DATE,
    end: str = END_DATE,
    raw_store: KrxRawStockStore | None = None,
) -> dict[str, Any]:
    """Derive target dates from paired COMPLETE raw-store manifest rows."""

    store = raw_store or KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    rows = store.list_manifest()
    states: dict[str, dict[str, str]] = {}
    for row in rows:
        day = str(row.get("date", ""))
        if start <= day <= end and str(row.get("market", "")) in {"KOSPI", "KOSDAQ"}:
            states.setdefault(day, {})[str(row["market"])] = str(row.get("status", ""))
    target: list[str] = []
    no_data: list[str] = []
    asymmetric: list[str] = []
    for day in sorted(states):
        pair = states[day]
        if pair.get("KOSPI") == pair.get("KOSDAQ") == "COMPLETE":
            target.append(day)
        elif pair.get("KOSPI") == pair.get("KOSDAQ") == "NO_DATA":
            no_data.append(day)
        else:
            asymmetric.append(day)
    if asymmetric:
        raise MarketDataError("BLOCKED_RAW_TRADING_CALENDAR_INCONSISTENT")
    return {
        "requested_start": start,
        "requested_end": end,
        "candidate_date_count": len(states),
        "complete_trading_date_count": len(target),
        "no_data_date_count": len(no_data),
        "asymmetric_date_count": len(asymmetric),
        "first_trading_date": target[0] if target else None,
        "last_trading_date": target[-1] if target else None,
        "target_date_sha256": _sha_dates(target),
        "target_dates": target,
        "no_data_dates": no_data,
    }


def load_offline_calendar(start: str = START_DATE, end: str = END_DATE) -> dict[str, Any]:
    """Load the already-closed raw manifest without constructing any client."""

    store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    rows = store.list_manifest()
    states: dict[str, dict[str, str]] = {}
    for row in rows:
        day = str(row.get("date", ""))
        market = str(row.get("market", ""))
        if start <= day <= end and market in {"KOSPI", "KOSDAQ"}:
            states.setdefault(day, {})[market] = str(row.get("status", ""))
    target = sorted(day for day, pair in states.items() if pair.get("KOSPI") == pair.get("KOSDAQ") == "COMPLETE")
    no_data = sorted(day for day, pair in states.items() if pair.get("KOSPI") == pair.get("KOSDAQ") == "NO_DATA")
    asymmetric = sorted(day for day, pair in states.items() if day not in set(target) and day not in set(no_data))
    if asymmetric:
        raise MarketDataError("BLOCKED_RAW_TRADING_CALENDAR_INCONSISTENT")
    return {
        "requested_start": start,
        "requested_end": end,
        "candidate_date_count": len(states),
        "complete_trading_date_count": len(target),
        "no_data_date_count": len(no_data),
        "asymmetric_date_count": len(asymmetric),
        "first_trading_date": target[0] if target else None,
        "last_trading_date": target[-1] if target else None,
        "target_date_sha256": _sha_dates(target),
        "target_dates": target,
        "no_data_dates": no_data,
    }


def _load_staging() -> pd.DataFrame:
    if not STAGING_PARQUET.exists() or not STAGING_META.exists():
        return pd.DataFrame(columns=list(INDEX_STORE_COLUMNS))
    try:
        return normalize_index_frame(pd.read_parquet(STAGING_PARQUET), MARKET_INDEX_FAMILY)
    except Exception as exc:
        raise MarketDataError("BLOCKED_STAGING_INTEGRITY") from exc


def validate_complete_staged_date(frame: pd.DataFrame, day: str) -> dict[str, Any]:
    """Return the fail-closed completeness decision for one staged date."""

    date_text = _date(day)
    if frame.empty:
        rows = frame
    else:
        rows = frame[frame["date"].astype(str) == date_text]
    codes = [str(value) for value in rows.get("index_code", pd.Series(dtype="string")).tolist()]
    duplicate_count = int(rows.duplicated(subset=["date", "family", "index_code"]).sum()) if not rows.empty else 0
    if duplicate_count:
        status = "FAIL_STAGING_PAIR_DUPLICATE"
    elif len(rows) != 2 or set(codes) != MARKET_INDEX_CODES or len(set(codes)) != 2:
        status = "BLOCKED_STAGING_PAIR_INCOMPLETE" if set(codes).issubset(MARKET_INDEX_CODES) else "FAIL_STAGING_PAIR_INVALID"
    else:
        status = "COMPLETE"
    return {
        "date": date_text,
        "status": status,
        "row_count": int(len(rows)),
        "codes": sorted(set(codes)),
        "duplicate_count": duplicate_count,
    }


def validate_staging_reuse(frame: pd.DataFrame, target_dates: Iterable[str]) -> dict[str, Any]:
    """Validate an existing staging file without fetching or rewriting it."""

    normalized = normalize_index_frame(frame, MARKET_INDEX_FAMILY)
    targets = {_date(day) for day in target_dates}
    staged_dates = set(normalized["date"].astype(str)) if not normalized.empty else set()
    extra_dates = sorted(staged_dates - targets)
    if extra_dates:
        raise MarketDataError("BLOCKED_STAGING_EXTRA_DATE")
    reports = [validate_complete_staged_date(normalized, day) for day in sorted(staged_dates)]
    incomplete = [item for item in reports if item["status"] != "COMPLETE"]
    if incomplete:
        code = incomplete[0]["status"]
        raise MarketDataError(code)
    return {
        "row_count": int(len(normalized)),
        "date_count": int(len(staged_dates)),
        "pair_complete_date_count": int(len(reports)),
        "incomplete_pair_date_count": int(len(incomplete)),
        "staged_dates": sorted(staged_dates),
        "extra_calendar_date_count": len(extra_dates),
        "decision": "STAGING_REUSE_AUTHORIZED",
    }


def _terminal_run(ledger: Mapping[str, Any]) -> Mapping[str, Any] | None:
    runs = ledger.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    terminal = runs[-1]
    if not isinstance(terminal, Mapping) or str(terminal.get("state")) not in TERMINAL_RUN_STATES:
        return None
    return terminal


def _terminal_snapshot_complete(run: Mapping[str, Any] | None) -> bool:
    if run is None:
        return False
    try:
        return int(run["staging_date_count_after"]) >= 0 and int(run["staging_row_count_after"]) >= 0 and bool(str(run.get("staging_sha_after", "")))
    except (KeyError, TypeError, ValueError):
        return False


def validate_operational_ledger_chain(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Validate adjacent staging snapshots without requiring legacy null hashes."""

    runs = ledger.get("runs")
    if not isinstance(runs, list) or not runs:
        return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA", "date_chain_mismatch": 0, "row_chain_mismatch": 0, "sha_chain_mismatch": 0}
    date_mismatch = row_mismatch = sha_mismatch = 0
    for previous, current in zip(runs, runs[1:]):
        try:
            date_mismatch += int(int(current["staging_date_count_before"]) != int(previous["staging_date_count_after"]))
            row_mismatch += int(int(current["staging_row_count_before"]) != int(previous["staging_row_count_after"]))
        except (KeyError, TypeError, ValueError):
            date_mismatch += 1
            row_mismatch += 1
        previous_sha = str(previous.get("staging_sha_after") or "")
        current_sha = str(current.get("staging_sha_before") or "")
        if previous_sha and current_sha and previous_sha != current_sha:
            sha_mismatch += 1
    terminal_complete = _terminal_snapshot_complete(_terminal_run(ledger))
    return {
        "status": "PASS" if not date_mismatch and not row_mismatch and not sha_mismatch else "FAIL",
        "date_chain_mismatch": date_mismatch,
        "row_chain_mismatch": row_mismatch,
        "sha_chain_mismatch": sha_mismatch,
        "terminal_snapshot_complete": terminal_complete,
        "adjacent_chain_count": max(0, len(runs) - 1),
    }


def validate_staging_ledger_continuity(frame: pd.DataFrame, ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Require current staging to equal the last terminal operational snapshot."""

    terminal = _terminal_run(ledger)
    current = _staging_snapshot(frame)
    if terminal is None:
        return {"status": "FAIL", "reason": "BLOCKED_STAGING_LEDGER_DIVERGENCE", "current": current, "terminal": None}
    terminal_snapshot = {
        "date_count": terminal.get("staging_date_count_after"),
        "row_count": terminal.get("staging_row_count_after"),
        "sha256": terminal.get("staging_sha_after"),
    }
    matches = (
        current["date_count"] == terminal_snapshot["date_count"]
        and current["row_count"] == terminal_snapshot["row_count"]
        and bool(terminal_snapshot["sha256"])
        and current["sha256"] == terminal_snapshot["sha256"]
    )
    return {
        "status": "PASS" if matches else "FAIL",
        "reason": "STAGING_LEDGER_CONTINUITY_PASS" if matches else "BLOCKED_STAGING_LEDGER_DIVERGENCE",
        "current": current,
        "terminal": terminal_snapshot,
    }


def _now_kst_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _staging_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "date_count": int(frame["date"].nunique()) if not frame.empty else 0,
        "row_count": int(len(frame)),
        "sha256": file_sha256(STAGING_PARQUET) if STAGING_PARQUET.exists() else None,
    }


def _phase_cumulative_from_runs(runs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    global_delta = client_count = audit_count = retry_count = 0
    endpoint_deltas: dict[str, int] = {}
    for run in runs:
        global_delta += int(run.get("global_delta", 0))
        client_count += int(run.get("client_request_count", 0))
        audit_count += int(run.get("audit_entry_count", 0))
        retry_count += int(run.get("retry_count", 0))
        for endpoint, value in dict(run.get("endpoint_deltas", {})).items():
            endpoint_deltas[str(endpoint)] = endpoint_deltas.get(str(endpoint), 0) + int(value)
    return {
        "global_delta": global_delta,
        "client_request_count": client_count,
        "audit_entry_count": audit_count,
        "retry_count": retry_count,
        "endpoint_deltas": endpoint_deltas,
    }


def _validate_ledger_structure(ledger: Mapping[str, Any]) -> dict[str, Any]:
    if ledger.get("schema_version") != OPERATIONAL_LEDGER_SCHEMA_VERSION or not isinstance(ledger.get("runs"), list):
        return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
    if any(not isinstance(run, Mapping) for run in ledger["runs"]):
        return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
    ids = [str(run.get("run_id", "")) for run in ledger["runs"]]
    if len(ids) != len(set(ids)) or any(not run_id for run_id in ids):
        return {"status": "FAIL", "reason": "BLOCKED_DUPLICATE_RUN_ID"}
    for run in ledger["runs"]:
        if str(run.get("state")) not in OPERATIONAL_RUN_STATES:
            return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
        if str(run.get("state")) == "STARTED":
            return {"status": "FAIL", "reason": "BLOCKED_INCOMPLETE_RUN_JOURNAL"}
    return {"status": "PASS"}


def validate_operational_ledger(ledger: Mapping[str, Any], *, require_terminal_snapshot: bool = False) -> dict[str, Any]:
    """Validate the mutable run ledger and its run-derived quota totals."""

    structure = _validate_ledger_structure(ledger)
    if structure["status"] != "PASS":
        return structure
    for run in ledger["runs"]:
        try:
            before_dates = int(run["staging_date_count_before"])
            after_dates = int(run["staging_date_count_after"])
            before_rows = int(run["staging_row_count_before"])
            after_rows = int(run["staging_row_count_after"])
            fetched = int(run["dates_fetched"])
        except (KeyError, TypeError, ValueError):
            return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
        if min(before_dates, after_dates, before_rows, after_rows, fetched) < 0 or after_dates < before_dates or after_rows < before_rows:
            return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
        if after_dates - before_dates != fetched and str(run.get("state")) not in {"PARTIAL", "BLOCKED"}:
            return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
    chain = validate_operational_ledger_chain(ledger)
    if chain["status"] != "PASS":
        return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_STAGING_CHAIN", "chain": chain}
    if require_terminal_snapshot and not chain["terminal_snapshot_complete"]:
        return {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA", "chain": chain}
    quota = validate_quota_reconciliation(ledger)
    return {"status": "PASS" if quota.get("status") == "PASS" else "FAIL", "quota": quota, "chain": chain}


def _normalize_seed_run(run: Mapping[str, Any], *, before_dates: int, after_dates: int, before_rows: int, after_rows: int, dates_fetched: int, next_pending: str | None) -> dict[str, Any]:
    result = dict(run)
    result.setdefault("run_type", result.get("scope", "HISTORICAL_BACKFILL"))
    result.setdefault("state", "COMPLETED")
    result.setdefault("started_at_kst", None)
    result.setdefault("completed_at_kst", None)
    result.setdefault("endpoint_before", {})
    result.setdefault("endpoint_after", {})
    result.setdefault("staging_date_count_before", before_dates)
    result.setdefault("staging_date_count_after", after_dates)
    result.setdefault("staging_row_count_before", before_rows)
    result.setdefault("staging_row_count_after", after_rows)
    result.setdefault("staging_sha_before", None)
    result.setdefault("staging_sha_after", None)
    result.setdefault("dates_fetched", dates_fetched)
    result.setdefault("next_pending_date", next_pending)
    result.setdefault("run_status", "COMPLETED")
    return result


def seed_operational_ledger_from_checkpoint(*, frame: pd.DataFrame, path: Path = OPERATIONAL_LEDGER_PATH, target_dates: Iterable[str] = ()) -> dict[str, Any]:
    """Seed .cache operational state only from the known 656-date checkpoint."""

    observed = _staging_snapshot(frame)
    expected_sha = "5685dc257b20a833e510367c7e77c15a0a4786564a80d93f493f750172e3890e"
    if observed["sha256"] != expected_sha or observed["date_count"] != 656 or observed["row_count"] != 1312:
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_MISSING_FOR_ADVANCED_STAGING")
    if any(item["status"] != "COMPLETE" for item in (validate_complete_staged_date(frame, day) for day in frame["date"].astype(str).unique())):
        raise MarketDataError("BLOCKED_STAGING_REUSE")
    static_path = ARTIFACT_DIR / "fix01" / "quota_run_ledger.json"
    static = _read_json_artifact(static_path)
    source_runs = static.get("runs")
    if not isinstance(source_runs, list) or len(source_runs) != 2:
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")
    runs = [
        _normalize_seed_run(source_runs[0], before_dates=0, after_dates=3, before_rows=0, after_rows=6, dates_fetched=3, next_pending="2010-01-05"),
        _normalize_seed_run(source_runs[1], before_dates=3, after_dates=656, before_rows=6, after_rows=1312, dates_fetched=653, next_pending="2012-08-16"),
    ]
    ledger = {"schema_version": OPERATIONAL_LEDGER_SCHEMA_VERSION, "phase": "KRX_INDEX_MIGRATION_V01", "runs": runs, "phase_cumulative": _phase_cumulative_from_runs(runs), "seed_source": str(static_path.relative_to(ROOT)), "seed_checkpoint_sha256": expected_sha}
    if validate_operational_ledger(ledger).get("status") != "PASS":
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")
    atomic_write_json(path, ledger)
    return ledger


def load_operational_ledger(path: Path = OPERATIONAL_LEDGER_PATH, *, require_terminal_snapshot: bool = False) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA") from exc
    if not isinstance(ledger, dict):
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")
    structure = _validate_ledger_structure(ledger)
    if structure["status"] != "PASS":
        raise MarketDataError(str(structure["reason"]))
    if validate_operational_ledger(ledger, require_terminal_snapshot=require_terminal_snapshot).get("status") != "PASS":
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")
    return ledger


def upgrade_seeded_ledger_checkpoint(*, frame: pd.DataFrame, path: Path = OPERATIONAL_LEDGER_PATH) -> dict[str, Any]:
    """Add the canonical current staging SHA to the known FIX03 seed, offline only."""

    observed = _staging_snapshot(frame)
    expected_sha = "5685dc257b20a833e510367c7e77c15a0a4786564a80d93f493f750172e3890e"
    if observed != {"date_count": 656, "row_count": 1312, "sha256": expected_sha}:
        raise MarketDataError("BLOCKED_STAGING_LEDGER_DIVERGENCE")
    ledger = load_operational_ledger(path)
    if ledger is None or len(ledger.get("runs", [])) != 2 or ledger.get("phase_cumulative", {}).get("global_delta") != 1312:
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")
    if [str(run.get("run_id")) for run in ledger["runs"]] != ["RUN1_PILOT", "RUN2_HISTORICAL_BACKFILL_TRANCHE"]:
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")
    terminal = ledger["runs"][-1]
    existing_sha = str(terminal.get("staging_sha_after") or "")
    if existing_sha and existing_sha != expected_sha:
        raise MarketDataError("BLOCKED_STAGING_LEDGER_DIVERGENCE")
    terminal["staging_sha_after"] = expected_sha
    ledger["continuity_upgrade"] = "FIX04_LEDGER_CONTINUITY_UPGRADE_V01"
    if validate_operational_ledger(ledger, require_terminal_snapshot=True).get("status") != "PASS":
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")
    atomic_write_json(path, ledger)
    return ledger


def ensure_operational_ledger(*, frame: pd.DataFrame, path: Path = OPERATIONAL_LEDGER_PATH, target_dates: Iterable[str] = ()) -> dict[str, Any]:
    existing = load_operational_ledger(path)
    if existing is not None:
        if not _terminal_snapshot_complete(_terminal_run(existing)):
            return upgrade_seeded_ledger_checkpoint(frame=frame, path=path)
        return existing
    return seed_operational_ledger_from_checkpoint(frame=frame, path=path, target_dates=target_dates)


def _append_run_record(ledger: dict[str, Any], run: Mapping[str, Any], path: Path) -> dict[str, Any]:
    run_id = str(run.get("run_id", ""))
    if any(str(item.get("run_id")) == run_id for item in ledger.get("runs", []) if isinstance(item, Mapping)):
        raise MarketDataError("BLOCKED_DUPLICATE_RUN_ID")
    if any(str(item.get("state")) == "STARTED" for item in ledger.get("runs", []) if isinstance(item, Mapping)):
        raise MarketDataError("BLOCKED_INCOMPLETE_RUN_JOURNAL")
    candidate = dict(run)
    ledger["runs"].append(candidate)
    ledger["phase_cumulative"] = _phase_cumulative_from_runs(ledger["runs"])
    if str(candidate.get("state")) != "STARTED" and validate_operational_ledger(ledger, require_terminal_snapshot=True).get("status") != "PASS":
        ledger["runs"].pop()
        ledger["phase_cumulative"] = _phase_cumulative_from_runs(ledger["runs"])
        raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")
    atomic_write_json(path, ledger)
    return ledger


def _update_run_record(ledger: dict[str, Any], run_id: str, updates: Mapping[str, Any], path: Path) -> dict[str, Any]:
    for run in ledger.get("runs", []):
        if str(run.get("run_id")) == run_id:
            run.update(dict(updates))
            ledger["phase_cumulative"] = _phase_cumulative_from_runs(ledger["runs"])
            if validate_operational_ledger(ledger, require_terminal_snapshot=True).get("status") != "PASS":
                raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")
            atomic_write_json(path, ledger)
            return ledger
    raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")


def append_operational_run(ledger: dict[str, Any], run: Mapping[str, Any], path: Path = OPERATIONAL_LEDGER_PATH) -> dict[str, Any]:
    return _append_run_record(ledger, run, path)


def update_operational_run(ledger: dict[str, Any], run_id: str, updates: Mapping[str, Any], path: Path = OPERATIONAL_LEDGER_PATH) -> dict[str, Any]:
    return _update_run_record(ledger, run_id, updates, path)


def network_summary_from_operational_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    phase = _phase_cumulative_from_runs(ledger.get("runs", []))
    endpoints = phase.get("endpoint_deltas", {})
    return {
        "krx_request_count": phase["client_request_count"],
        "kospi_dd_trd_request_count": int(endpoints.get("kospi_dd_trd", 0)),
        "kosdaq_dd_trd_request_count": int(endpoints.get("kosdaq_dd_trd", 0)),
        "krx_dd_trd_request_count": 0,
        "retry_count": phase["retry_count"],
        "audit_entry_count": phase["audit_entry_count"],
        "pykrx_live_market_calls": 0,
        "status": "PASS" if phase["client_request_count"] == phase["audit_entry_count"] and sum(endpoints.values()) == phase["client_request_count"] else "FAIL",
    }


def validate_cumulative_progress(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("krx_request_count", "kospi_dd_trd_request_count", "kosdaq_dd_trd_request_count", "audit_entry_count", "retry_count")
    regressions = [field for field in fields if int(current.get(field, 0)) < int(previous.get(field, 0))]
    return {"status": "PASS" if not regressions else "FAIL", "regressions": regressions}


def _save_staging(frame: pd.DataFrame, *, start: str, end: str) -> dict[str, Any]:
    store = IndexStore(STAGING_DIR)
    metadata = store.save_family_full(
        MARKET_INDEX_FAMILY,
        frame,
        metadata_context={"requested_start": start, "requested_end": end, "fetch_mode": FETCH_MODE, "mapping_contract_version": MAPPING_CONTRACT_VERSION, "mapping_contract_sha256": mapping_contract_sha256()},
        output_parquet=STAGING_PARQUET,
        output_meta=STAGING_META,
    )
    return metadata


def _quota_usage(quota: Any | None) -> dict[str, Any]:
    if quota is None or not hasattr(quota, "get_usage"):
        return {"global_total": 0, "endpoint_usage": {}}
    return quota.get_usage()


def _available_whole_dates(quota: Any | None, pending_count: int) -> int:
    if quota is None:
        return pending_count
    if not hasattr(quota, "remaining"):
        return pending_count
    kospi = quota.remaining("kospi_dd_trd")
    kosdaq = quota.remaining("kosdaq_dd_trd")
    global_remaining = min(int(kospi.get("global", 0)), int(kosdaq.get("global", 0)))
    endpoint_remaining = min(int(kospi.get("endpoint", 0)), int(kosdaq.get("endpoint", 0)))
    return max(0, min(pending_count, endpoint_remaining, global_remaining // 2))


def _classify_blocker(exc: Exception) -> str:
    if isinstance(exc, KrxOpenApiAuthorizationError):
        return "BLOCKED_KRX_AUTH"
    if isinstance(exc, KrxOpenApiRateLimitError) or isinstance(exc, KrxOpenApiQuotaExceeded):
        return "BACKFILL_PAUSED_QUOTA"
    if isinstance(exc, KrxOpenApiBudgetError):
        return "BACKFILL_PAUSED_QUOTA"
    if isinstance(exc, KrxMarketIndexError):
        if exc.error_code == "BLOCKED_KRX_TRANSPORT":
            return "BLOCKED_KRX_TRANSPORT"
        return "BLOCKED_KRX_INDEX_SCHEMA"
    return "BLOCKED_KRX_TRANSPORT" if "transport" in str(exc).lower() else "BLOCKED_KRX_INDEX_SCHEMA"


def terminal_run_state(blockers: Iterable[str], pending_after: Iterable[str]) -> str:
    blocker_set = {str(value) for value in blockers}
    if blocker_set & FATAL_RUN_BLOCKERS:
        return "BLOCKED"
    if blocker_set or list(pending_after):
        return "PARTIAL"
    return "COMPLETED"


class MarketIndexMigrationRunner:
    """Sequential, whole-date resumable staging runner."""

    def __init__(self, *, client: Any | None = None, quota: Any | None = None, auth_key: str | None = None, max_requests: int = 10_000, throttle_seconds: float = 0.0) -> None:
        self.quota = quota or LocalKrxOpenApiQuota()
        if client is not None:
            self.client = client
        else:
            from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
            key = (auth_key or load_auth_key()).strip()
            if not key:
                raise ValueError("KRX_OPEN_API_AUTH_KEY is required")
            self.client = KrxOpenApiClient(key, max_requests=max_requests, max_transient_retries=0, quota=self.quota)
        self.builder = KrxMarketIndexBuilder(client=self.client, throttle_seconds=throttle_seconds)

    def run(self, calendar: Mapping[str, Any], *, resume: bool = True, publish: bool = False, max_dates: int | None = None, operational_ledger_path: Path | None = None, run_type: str = "HISTORICAL_BACKFILL_RESUME", run_id: str | None = None) -> dict[str, Any]:
        if publish:
            raise MarketDataError("PRODUCTION_PUBLISH_REQUIRES_FINALIZATION")
        target_dates = list(calendar.get("target_dates", []))
        existing = _load_staging() if resume else pd.DataFrame(columns=list(INDEX_STORE_COLUMNS))
        reuse = validate_staging_reuse(existing, target_dates)
        complete_existing = set(reuse["staged_dates"])
        pending = [day for day in target_dates if day not in complete_existing]
        quota_before = _quota_usage(self.quota)
        ledger: dict[str, Any] | None = None
        if operational_ledger_path is not None:
            ledger = ensure_operational_ledger(frame=existing, path=operational_ledger_path, target_dates=target_dates)
            continuity = validate_staging_ledger_continuity(existing, ledger)
            if continuity.get("status") != "PASS":
                raise MarketDataError("BLOCKED_STAGING_LEDGER_DIVERGENCE")
        capacity = _available_whole_dates(self.quota, len(pending))
        if max_dates is not None:
            capacity = min(capacity, int(max_dates))
        if pending and capacity <= 0:
            result = self._result(calendar, existing, pending, quota_before, blockers=["BACKFILL_PAUSED_QUOTA"])
            result["operational_ledger_path"] = str(operational_ledger_path) if operational_ledger_path else None
            result["operational_run_created"] = False
            return result
        operational_run_id: str | None = None
        staging_before = _staging_snapshot(existing)
        request_before = int(getattr(self.client, "request_count", 0))
        audit_before = len(getattr(self.client, "audit", []) or [])
        retry_before = int(getattr(self.client, "retry_count", 0))
        if operational_ledger_path is not None:
            assert ledger is not None
            operational_run_id = run_id or f"RUN_{run_type}_{datetime.now().strftime('%Y%m%dT%H%M%S%f')}"
            run_record = {
                "run_id": operational_run_id,
                "usage_date_kst": quota_before.get("usage_date_kst"),
                "run_type": run_type,
                "state": "STARTED",
                "started_at_kst": _now_kst_iso(),
                "completed_at_kst": None,
                "global_before": int(quota_before.get("global_total", 0)),
                "global_after": int(quota_before.get("global_total", 0)),
                "global_delta": 0,
                "endpoint_before": dict(quota_before.get("endpoint_usage", {})),
                "endpoint_after": dict(quota_before.get("endpoint_usage", {})),
                "endpoint_deltas": {},
                "client_request_count": 0,
                "audit_entry_count": 0,
                "retry_count": 0,
                "staging_date_count_before": staging_before["date_count"],
                "staging_date_count_after": staging_before["date_count"],
                "staging_row_count_before": staging_before["row_count"],
                "staging_row_count_after": staging_before["row_count"],
                "staging_sha_before": staging_before["sha256"],
                "staging_sha_after": staging_before["sha256"],
                "dates_fetched": 0,
                "next_pending_date": pending[0] if pending else None,
                "run_status": "STARTED",
            }
            ledger = _append_run_record(ledger, run_record, operational_ledger_path)
        selected = pending[:capacity]
        fetched_dates: list[str] = []
        blockers: list[str] = []
        for day in selected:
            try:
                frame, report = self.builder.fetch_date(day)
                pair = validate_complete_staged_date(frame, day)
                if report["status"] != "COMPLETE" or pair["status"] != "COMPLETE":
                    raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "target trading date did not yield two rows")
                existing = pd.concat([existing, frame], ignore_index=True)
                existing = normalize_index_frame(existing, MARKET_INDEX_FAMILY)
                _save_staging(existing, start=calendar["requested_start"], end=calendar["requested_end"])
                fetched_dates.append(day)
            except Exception as exc:
                blockers.append(_classify_blocker(exc))
                break
        pending_after = [day for day in target_dates if day not in set(existing["date"].astype(str).unique())]
        if not blockers and pending_after:
            blockers.append("BACKFILL_PAUSED_QUOTA")
        result = self._result(calendar, existing, pending_after, quota_before, blockers=blockers)
        result["dates_fetched_this_run"] = fetched_dates
        result["dates_resumed_or_skipped"] = sorted(complete_existing)
        result["production_index_store_publish_count"] = 0
        if operational_ledger_path is not None and ledger is not None and operational_run_id is not None:
            quota_after = _quota_usage(self.quota)
            endpoint_before = dict(quota_before.get("endpoint_usage", {}))
            endpoint_after = dict(quota_after.get("endpoint_usage", {}))
            endpoint_deltas = {key: int(endpoint_after.get(key, 0)) - int(endpoint_before.get(key, 0)) for key in set(endpoint_before) | set(endpoint_after)}
            staging_after = _staging_snapshot(existing)
            state = terminal_run_state(blockers, pending_after)
            ledger = _update_run_record(ledger, operational_run_id, {
                "state": state,
                "completed_at_kst": _now_kst_iso(),
                "global_after": int(quota_after.get("global_total", 0)),
                "global_delta": int(quota_after.get("global_total", 0)) - int(quota_before.get("global_total", 0)),
                "endpoint_after": endpoint_after,
                "endpoint_deltas": endpoint_deltas,
                "client_request_count": int(getattr(self.client, "request_count", 0)) - request_before,
                "audit_entry_count": len(getattr(self.client, "audit", []) or []) - audit_before,
                "retry_count": int(getattr(self.client, "retry_count", 0)) - retry_before,
                "staging_date_count_after": staging_after["date_count"],
                "staging_row_count_after": staging_after["row_count"],
                "staging_sha_after": staging_after["sha256"],
                "dates_fetched": len(fetched_dates),
                "next_pending_date": pending_after[0] if pending_after else None,
                "run_status": state,
            }, operational_ledger_path)
            result["operational_ledger_path"] = str(operational_ledger_path)
            result["operational_run_id"] = operational_run_id
            result["operational_run_state"] = state
            result["phase_network_summary"] = network_summary_from_operational_ledger(ledger)
        return result

    def _result(self, calendar: Mapping[str, Any], frame: pd.DataFrame, pending: list[str], quota_before: Mapping[str, Any], *, blockers: list[str]) -> dict[str, Any]:
        quota_after = _quota_usage(self.quota)
        request_count = int(getattr(self.client, "request_count", 0))
        target_count = int(calendar.get("complete_trading_date_count", len(calendar.get("target_dates", []))))
        complete_count = int(frame["date"].nunique()) if not frame.empty else 0
        status = "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01"
        return {
            "status": status,
            "target_date_count": target_count,
            "complete_date_count": complete_count,
            "pending_date_count": len(pending),
            "failed_date_count": 0,
            "next_pending_date": pending[0] if pending else None,
            "staging_rows": int(len(frame)),
            "krx_request_count": request_count,
            "quota_before": dict(quota_before),
            "quota_after": dict(quota_after),
            "quota_delta": int(quota_after.get("global_total", 0)) - int(quota_before.get("global_total", 0)),
            "client_request_count": request_count,
            "audit_entry_count": len(getattr(self.client, "audit", []) or []),
            "retry_count": int(getattr(self.client, "retry_count", 0)),
            "blockers": sorted(set(blockers)),
            "staging_parquet": str(STAGING_PARQUET),
            "staging_meta": str(STAGING_META),
            "codes": ["1001", "2001"],
        }


def legacy_reference_summary(path: Path = LEGACY_REFERENCE) -> dict[str, Any]:
    if not path.exists():
        return {"reference_sha256": None, "reference_hash_match": False, "status": "BLOCKED_LEGACY_MARKET_REFERENCE_MISSING"}
    observed = file_sha256(path)
    return {"reference_path": str(path), "reference_sha256": LEGACY_REFERENCE_SHA256, "observed_sha256": observed, "reference_hash_match": observed == LEGACY_REFERENCE_SHA256}


def compare_legacy_market_parity(new_frame: pd.DataFrame, reference_path: Path = LEGACY_REFERENCE) -> tuple[pd.DataFrame, dict[str, Any]]:
    reference_info = legacy_reference_summary(reference_path)
    if not reference_info.get("reference_hash_match"):
        raise MarketDataError("BLOCKED_LEGACY_MARKET_REFERENCE_HASH_MISMATCH" if reference_path.exists() else "BLOCKED_LEGACY_MARKET_REFERENCE_MISSING")
    reference = pd.read_parquet(reference_path).copy()
    left = new_frame.copy()
    for frame in (left, reference):
        frame["date"] = frame["date"].astype(str)
        frame["index_code"] = frame["index_code"].astype(str)
    left = left[left["index_code"].isin(MARKET_INDEX_CODES)]
    reference = reference[reference["index_code"].isin(MARKET_INDEX_CODES)]
    session_counts = reference.groupby("index_code")["date"].nunique().to_dict()
    if any(int(session_counts.get(code, 0)) < 253 for code in MARKET_INDEX_CODES):
        raise MarketDataError("BLOCKED_LEGACY_MARKET_REFERENCE_COVERAGE")
    left_map = {(row.date, row.index_code): row for row in left.itertuples()}
    ref_map = {(row.date, row.index_code): row for row in reference.itertuples()}
    if len(left_map) != len(left) or len(ref_map) != len(reference):
        raise MarketDataError("BLOCKED_LEGACY_MARKET_REFERENCE_DUPLICATE_KEY")
    reference_dates = {key[0] for key in ref_map}
    reference_date_min = min(reference_dates) if reference_dates else None
    reference_date_max = max(reference_dates) if reference_dates else None
    new_only_keys = set(left_map) - set(ref_map)
    extra_within_scope = {
        key for key in new_only_keys
        if reference_date_min is not None and reference_date_min <= key[0] <= reference_date_max
    }
    ignored_outside_scope = new_only_keys - extra_within_scope
    rows: list[dict[str, Any]] = []
    compared_fields = exact_fields = ohlc_mismatches = 0
    missing_rows = 0
    for key in sorted(set(ref_map)):
        lrow, rrow = left_map.get(key), ref_map.get(key)
        row: dict[str, Any] = {"date": key[0], "index_code": key[1], "index_name": getattr(lrow or rrow, "index_name", "")}
        row_mismatch = lrow is None
        missing_rows += int(lrow is None)
        for field in OHLC_FIELDS:
            lv = getattr(lrow, field, None) if lrow is not None else None
            rv = getattr(rrow, field, None) if rrow is not None else None
            try:
                match = lv is not None and rv is not None and Decimal(str(lv)) == Decimal(str(rv))
            except (InvalidOperation, ValueError):
                match = False
            row[f"krx_{field}"] = "" if lv is None else str(lv)
            row[f"reference_{field}"] = "" if rv is None else str(rv)
            row[f"{field}_match"] = bool(match)
            compared_fields += int(lv is not None and rv is not None)
            exact_fields += int(match)
            row_mismatch |= not match
        row["row_mismatch"] = bool(row_mismatch)
        ohlc_mismatches += int(row_mismatch and lrow is not None)
        rows.append(row)
    result = pd.DataFrame(rows)
    mismatch_count = missing_rows + ohlc_mismatches
    summary = {
        **reference_info,
        "reference_date_min": reference_date_min,
        "reference_date_max": reference_date_max,
        "reference_key_count": len(ref_map),
        "reference_date_count": len(reference_dates),
        "1001_session_count": int(session_counts.get("1001", 0)),
        "2001_session_count": int(session_counts.get("2001", 0)),
        "compared_key_count": len(set(left_map) & set(ref_map)),
        "compared_index_count": len({key[1] for key in set(left_map) & set(ref_map)}),
        "compared_date_count": len({key[0] for key in set(left_map) & set(ref_map)}),
        "compared_field_count": compared_fields,
        "exact_field_count": exact_fields,
        "ohlc_mismatch_count": ohlc_mismatches,
        "mismatch_count": mismatch_count,
        "missing_krx_row_count": missing_rows,
        "extra_krx_within_reference_scope_count": len(extra_within_scope),
        "ignored_krx_outside_reference_scope_count": len(ignored_outside_scope),
        "status": "PASS" if missing_rows == 0 and len(extra_within_scope) == 0 and ohlc_mismatches == 0 else "FAIL",
    }
    return result, summary


def market_rs_parity(new_frame: pd.DataFrame, reference_path: Path = LEGACY_REFERENCE) -> dict[str, Any]:
    old = pd.read_parquet(reference_path)
    dates = pd.to_datetime(old["date"].astype(str)).sort_values().drop_duplicates()
    stock = pd.DataFrame({"close": range(100, 100 + len(dates))}, index=dates)
    cases: dict[str, Any] = {}
    for market, code, name in (("KOSPI", "1001", "코스피"), ("KOSDAQ", "2001", "코스닥")):
        old_result = compute_relative_strength_features("SYNTH01", str(dates.max().date()), stock, old, market)
        new_result = compute_relative_strength_features("SYNTH01", str(dates.max().date()), stock, new_frame, market)
        old_dict, new_dict = old_result.to_dict(), new_result.to_dict()
        identity_match = all(old_dict.get(field) == new_dict.get(field) for field in RS_IDENTITY_FIELDS)
        numeric_diffs: list[float] = []
        numeric_checks: dict[str, bool] = {}
        for field in RS_NUMERIC_FIELDS:
            old_value, new_value = old_dict.get(field), new_dict.get(field)
            if old_value is None or new_value is None:
                numeric_checks[field] = old_value is None and new_value is None
            else:
                try:
                    diff = abs(float(old_value) - float(new_value))
                    numeric_diffs.append(diff)
                    numeric_checks[field] = diff <= RS_NUMERIC_TOLERANCE
                except (TypeError, ValueError):
                    numeric_checks[field] = False
        status_match = old_dict.get("market_rs_data_status") == new_dict.get("market_rs_data_status") == "READY"
        canonical_identity_match = (
            old_dict.get("market_benchmark_code") == new_dict.get("market_benchmark_code") == code
            and old_dict.get("market_benchmark_name") == new_dict.get("market_benchmark_name") == name
        )
        ready_numeric_complete = (
            not status_match
            or all(old_dict.get(field) is not None and new_dict.get(field) is not None for field in RS_NUMERIC_FIELDS)
        )
        returns_match = all(numeric_checks[f"market_return_{h}"] for h in ("3m", "6m", "12m"))
        rs_match = all(numeric_checks[f"market_rs_{h}"] for h in ("3m", "6m", "12m"))
        all_numeric_match = all(numeric_checks.values()) and ready_numeric_complete
        max_abs_numeric_diff = max(numeric_diffs, default=None)
        numeric_tolerance_match = max_abs_numeric_diff is not None and max_abs_numeric_diff <= RS_NUMERIC_TOLERANCE
        case_status = all((status_match, identity_match, canonical_identity_match, returns_match, rs_match, all_numeric_match, numeric_tolerance_match))
        cases[market] = {
            "old_status": old_dict["market_rs_data_status"],
            "new_status": new_dict["market_rs_data_status"],
            "status_match": status_match,
            "identity_fields_match": identity_match,
            "canonical_identity_match": canonical_identity_match,
            "benchmark_code_match": old_dict["market_benchmark_code"] == new_dict["market_benchmark_code"] == code,
            "benchmark_name_match": old_dict["market_benchmark_name"] == new_dict["market_benchmark_name"] == name,
            "last_observation_match": old_dict["market_benchmark_last_observation_date"] == new_dict["market_benchmark_last_observation_date"],
            "anchor_dates_match": all(old_dict[f"market_anchor_date_{h}"] == new_dict[f"market_anchor_date_{h}"] for h in ("3m", "6m", "12m")),
            "market_returns_match": returns_match,
            "market_rs_match": rs_match,
            "numeric_fields_match": all_numeric_match,
            "ready_numeric_complete": ready_numeric_complete,
            "max_abs_numeric_diff": max_abs_numeric_diff,
            "numeric_tolerance_match": numeric_tolerance_match,
            "status": "PASS" if case_status else "FAIL",
        }
    return {"cases": cases, "status": "PASS" if all(item["status"] == "PASS" for item in cases.values()) else "FAIL"}


def validate_quota_reconciliation(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Validate independent runs and derive phase totals from their deltas.

    A KST quota counter may reset between runs.  Therefore no phase value is
    calculated by subtracting a later run's global counter from an earlier
    run's counter; ``runs`` is the sole phase authority.
    """

    runs = ledger.get("runs")
    if not isinstance(runs, list) or not runs:
        return {"status": "FAIL", "reason": "runs ledger is required", "run_reconciliation": "FAIL"}
    run_results: list[dict[str, Any]] = []
    derived_delta = derived_client = derived_audit = 0
    derived_endpoint: dict[str, int] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            run_results.append({"status": "FAIL", "reason": "invalid run record"})
            continue
        try:
            global_before = int(run["global_before"])
            global_after = int(run["global_after"])
            declared_delta = int(run["global_delta"])
            client_count = int(run["client_request_count"])
            audit_count = int(run["audit_entry_count"])
            endpoint_deltas = {str(key): int(value) for key, value in dict(run["endpoint_deltas"]).items()}
            checks = {
                "counter_delta_match": global_after - global_before == declared_delta,
                "client_delta_match": declared_delta == client_count,
                "audit_delta_match": declared_delta == audit_count,
                "endpoint_delta_match": sum(endpoint_deltas.values()) == declared_delta,
            }
        except (KeyError, TypeError, ValueError):
            run_results.append({"run_id": run.get("run_id"), "status": "FAIL", "reason": "missing or invalid run fields"})
            continue
        run_status = "PASS" if all(checks.values()) else "FAIL"
        run_results.append({"run_id": run.get("run_id"), "usage_date_kst": run.get("usage_date_kst"), "status": run_status, **checks})
        derived_delta += declared_delta
        derived_client += client_count
        derived_audit += audit_count
        for endpoint, value in endpoint_deltas.items():
            derived_endpoint[endpoint] = derived_endpoint.get(endpoint, 0) + value

    phase = ledger.get("phase_cumulative") if isinstance(ledger.get("phase_cumulative"), Mapping) else {}
    declared_phase_delta = ledger.get("phase_global_delta", phase.get("global_delta"))
    declared_phase_client = ledger.get("phase_request_count", ledger.get("client_request_count_phase", phase.get("client_request_count")))
    declared_phase_audit = ledger.get("phase_audit_count", ledger.get("audit_entry_count_phase", phase.get("audit_entry_count")))
    declared_phase_endpoint = ledger.get("phase_endpoint_deltas", phase.get("endpoint_deltas"))
    phase_checks = {
        "phase_delta_matches_runs": declared_phase_delta is not None and int(declared_phase_delta) == derived_delta,
        "phase_client_matches_runs": declared_phase_client is not None and int(declared_phase_client) == derived_client,
        "phase_audit_matches_runs": declared_phase_audit is not None and int(declared_phase_audit) == derived_audit,
        "phase_endpoint_matches_runs": declared_phase_endpoint is not None and {str(k): int(v) for k, v in dict(declared_phase_endpoint).items()} == derived_endpoint,
    }
    all_run_pass = bool(run_results) and all(item.get("status") == "PASS" for item in run_results)
    return {
        "status": "PASS" if all_run_pass and all(phase_checks.values()) else "FAIL",
        "run_reconciliation": "PASS" if all_run_pass else "FAIL",
        "runs": run_results,
        "derived_phase_delta": derived_delta,
        "derived_request_count": derived_client,
        "derived_audit_count": derived_audit,
        "derived_endpoint_deltas": derived_endpoint,
        **phase_checks,
    }


def _gate_status(value: Mapping[str, Any] | None, *, default_reason: str) -> dict[str, Any]:
    if value is None:
        return {"status": "FAIL", "reason": default_reason}
    status = str(value.get("status", "FAIL"))
    return {**dict(value), "status": "PASS" if status == "PASS" else "FAIL"}


def validate_current_source_freeze(validation_source_head: str, repo_root: Path = ROOT) -> dict[str, Any]:
    """Validate the executable source tree at runtime, not a static diff artifact."""

    source_prefixes = ("src/", "scripts/", "tests/", "docs/")
    allowed_artifact_prefix = "artifacts/data/krx_openapi/market_index_migration/v01/"
    try:
        current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", validation_source_head, current_head], cwd=repo_root, check=False).returncode == 0
        committed = subprocess.check_output(["git", "diff", "--name-only", f"{validation_source_head}..{current_head}"], cwd=repo_root, text=True).splitlines()
        status_lines = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_root, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"validation_source_head": validation_source_head, "status": "FAIL", "reason": str(exc)}
    forbidden_committed = [path for path in committed if not path.startswith(allowed_artifact_prefix)]
    tracked_source: list[str] = []
    staged_source: list[str] = []
    untracked_source: list[str] = []
    for line in status_lines:
        if not line:
            continue
        state, path = line[:2], line[3:]
        path = path.split(" -> ")[-1]
        if not path.startswith(source_prefixes):
            continue
        if state == "??":
            untracked_source.append(path)
        else:
            tracked_source.append(path)
            if state[0] != " ":
                staged_source.append(path)
    status = "PASS" if ancestor and not forbidden_committed and not tracked_source and not staged_source and not untracked_source else "FAIL"
    return {
        "validation_source_head": validation_source_head,
        "current_head": current_head,
        "source_head_is_ancestor": ancestor,
        "committed_changed_files_since_source": committed,
        "forbidden_committed_changes": forbidden_committed,
        "tracked_source_worktree_changes": sorted(set(tracked_source)),
        "staged_source_changes": sorted(set(staged_source)),
        "untracked_source_changes": sorted(set(untracked_source)),
        "status": status,
    }


def resolve_validation_source_head(manifest_path: Path = ARTIFACT_DIR / "market_index_migration_v01_manifest.json") -> str:
    manifest = _read_json_artifact(manifest_path)
    value = str(manifest.get("fix04_validation_source_head", "")).strip()
    if not value:
        raise MarketDataError("BLOCKED_VALIDATION_SOURCE_ANCHOR_MISSING")
    return value


def validate_manifest_anchor_immutability(manifest: Mapping[str, Any], *, field: str, proposed: str | None) -> dict[str, Any]:
    existing = str(manifest.get(field, "")).strip()
    candidate = str(proposed or "").strip()
    if existing and candidate and existing != candidate:
        raise MarketDataError("BLOCKED_VALIDATION_SOURCE_ANCHOR_MUTATION")
    return {"field": field, "existing": existing or None, "proposed": candidate or None, "status": "PASS"}


def validate_resume_pre_network(*, staging_frame: pd.DataFrame, ledger: Mapping[str, Any], target_dates: Iterable[str], validation_source_head: str, repo_root: Path = ROOT) -> dict[str, Any]:
    """Run every resumable provenance gate before constructing a KRX client."""

    try:
        staging = validate_staging_reuse(staging_frame, target_dates)
    except Exception as exc:
        raise MarketDataError(str(exc)) from exc
    ledger_gate = validate_operational_ledger(ledger, require_terminal_snapshot=True)
    if ledger_gate.get("status") != "PASS":
        raise MarketDataError(str(ledger_gate.get("reason", "BLOCKED_OPERATIONAL_LEDGER_RECONCILIATION")))
    continuity = validate_staging_ledger_continuity(staging_frame, ledger)
    if continuity.get("status") != "PASS":
        raise MarketDataError("BLOCKED_STAGING_LEDGER_DIVERGENCE")
    source_guard = validate_current_source_freeze(validation_source_head, repo_root)
    if source_guard.get("status") != "PASS":
        raise MarketDataError("BLOCKED_CURRENT_SOURCE_FREEZE")
    return {"staging": staging, "ledger": ledger_gate, "continuity": continuity, "source_guard": source_guard, "status": "PASS"}


def validate_runtime_network_provenance(ledger: Mapping[str, Any]) -> dict[str, Any]:
    summary = network_summary_from_operational_ledger(ledger)
    quota = validate_quota_reconciliation(ledger)
    return {**summary, "status": "PASS" if summary["status"] == "PASS" and quota.get("status") == "PASS" else "FAIL", "quota_status": quota.get("status")}


def finalize_market_index_migration(
    *,
    calendar: Mapping[str, Any],
    staging_frame: pd.DataFrame | None = None,
    legacy_reference_path: Path = LEGACY_REFERENCE,
    quota_ledger: Mapping[str, Any] | None = None,
    provenance_audit: Mapping[str, Any] | None = None,
    secret: str = "",
    diff_guard: Mapping[str, Any] | None = None,
    operational_ledger_path: Path | None = None,
    validation_source_head: str | None = None,
    source_freeze_repo: Path = ROOT,
    publish: bool = False,
    production_writer: Any | None = None,
) -> dict[str, Any]:
    """Run the ordered finalization gates; production write is the last action."""

    frame = staging_frame if staging_frame is not None else _load_staging()
    gates: dict[str, Any] = {}
    production_write_count = 0
    effective_ledger: dict[str, Any] | None = None
    if operational_ledger_path is not None:
        try:
            effective_ledger = load_operational_ledger(operational_ledger_path, require_terminal_snapshot=True)
            if effective_ledger is None:
                raise MarketDataError("BLOCKED_OPERATIONAL_LEDGER_SCHEMA")
        except MarketDataError as exc:
            gates["operational_ledger_load_gate"] = {"status": "FAIL", "reason": str(exc)}
        else:
            gates["operational_ledger_load_gate"] = {"status": "PASS", "run_count": len(effective_ledger.get("runs", []))}
    else:
        effective_ledger = dict(quota_ledger) if isinstance(quota_ledger, Mapping) else None
        gates["operational_ledger_load_gate"] = {"status": "PASS" if effective_ledger is not None else "FAIL", "authority": "supplied_quota_ledger"}

    # 1. staging verification / 2. full target coverage / 3. exact pairs
    try:
        target_dates = {_date(value) for value in calendar.get("target_dates", [])}
        normalized = normalize_index_frame(frame, MARKET_INDEX_FAMILY)
        reuse = validate_staging_reuse(normalized, target_dates)
        gates["staging_verification_gate"] = {"status": "PASS", **reuse}
    except Exception as exc:
        gates["staging_verification_gate"] = {"status": "FAIL", "reason": str(exc)}
        normalized = frame
    target_dates = {_date(value) for value in calendar.get("target_dates", [])}
    observed_dates = set(normalized["date"].astype(str)) if isinstance(normalized, pd.DataFrame) and not normalized.empty else set()
    gates["coverage_gate"] = {"status": "PASS" if observed_dates == target_dates else "FAIL", "target_date_count": len(target_dates), "observed_date_count": len(observed_dates)}
    pair_reports = [validate_complete_staged_date(normalized, day) for day in sorted(observed_dates)] if isinstance(normalized, pd.DataFrame) else []
    gates["pair_gate"] = {"status": "PASS" if len(pair_reports) == len(observed_dates) and all(item["status"] == "COMPLETE" for item in pair_reports) else "FAIL", "reports": pair_reports}
    if operational_ledger_path is not None and effective_ledger is not None:
        gates["staging_ledger_continuity_gate"] = validate_staging_ledger_continuity(normalized, effective_ledger)
    elif operational_ledger_path is not None:
        gates["staging_ledger_continuity_gate"] = {"status": "FAIL", "reason": "BLOCKED_OPERATIONAL_LEDGER_SCHEMA"}
    else:
        gates["staging_ledger_continuity_gate"] = {"status": "PASS", "reason": "legacy finalizer fixture has no operational path"}

    # 4. reference SHA / 5. legacy OHLC / 6. market RS
    try:
        ref_info = legacy_reference_summary(legacy_reference_path)
        gates["legacy_reference_sha_gate"] = {**ref_info, "status": "PASS" if ref_info.get("reference_hash_match") else "FAIL"}
        _, legacy_summary = compare_legacy_market_parity(normalized, legacy_reference_path)
        gates["legacy_ohlc_parity_gate"] = legacy_summary
    except Exception as exc:
        gates.setdefault("legacy_reference_sha_gate", {"status": "FAIL", "reason": str(exc)})
        gates["legacy_ohlc_parity_gate"] = {"status": "FAIL", "reason": str(exc)}
    try:
        gates["market_rs_parity_gate"] = market_rs_parity(normalized, legacy_reference_path)
    except Exception as exc:
        gates["market_rs_parity_gate"] = {"status": "FAIL", "reason": str(exc)}

    # 7. provenance/network audit / 8. secret scan / 9. diff-source freeze
    if operational_ledger_path is not None and effective_ledger is not None:
        gates["provenance_network_gate"] = validate_runtime_network_provenance(effective_ledger)
    else:
        gates["provenance_network_gate"] = _gate_status(provenance_audit, default_reason="provenance audit not supplied")
    if not publish and not secret:
        gates["secret_gate"] = {"status": "NOT_EVALUATED", "reason": "non-publish diagnostic has no secret"}
    elif not secret:
        gates["secret_gate"] = {"status": "FAIL", "reason": "BLOCKED_SECRET_SCAN_UNAVAILABLE", "secret_occurrence_count": 0, "scanned_file_count": 0}
    else:
        scan = secret_scan(secret)
        scanned_count = int(scan.get("scanned_file_count", 0))
        occurrence_count = int(scan.get("secret_occurrence_count", 0))
        if scanned_count <= 0:
            gates["secret_gate"] = {**scan, "status": "FAIL", "reason": "BLOCKED_SECRET_SCAN_EMPTY_SCOPE"}
        elif occurrence_count > 0:
            gates["secret_gate"] = {**scan, "status": "FAIL", "reason": "BLOCKED_SECRET_EXPOSURE"}
        else:
            gates["secret_gate"] = {**scan, "status": "PASS", "scan_status": "PASS"}
    if operational_ledger_path is not None:
        try:
            source_head = validation_source_head or resolve_validation_source_head()
        except MarketDataError as exc:
            gates["runtime_source_freeze_gate"] = {"status": "FAIL", "reason": str(exc)}
        else:
            gates["runtime_source_freeze_gate"] = validate_current_source_freeze(source_head, source_freeze_repo)
        gates["diff_source_freeze_gate"] = gates["runtime_source_freeze_gate"]
    else:
        gates["diff_source_freeze_gate"] = _gate_status(diff_guard, default_reason="diff/source freeze diagnostic not supplied")
        gates["runtime_source_freeze_gate"] = gates["diff_source_freeze_gate"]
    ordered = (
        "staging_verification_gate", "operational_ledger_load_gate", "staging_ledger_continuity_gate", "coverage_gate", "pair_gate", "legacy_reference_sha_gate",
        "legacy_ohlc_parity_gate", "market_rs_parity_gate", "provenance_network_gate",
        "secret_gate", "runtime_source_freeze_gate", "quota_gate",
    )
    quota_result = validate_quota_reconciliation(effective_ledger or {})
    gates["quota_gate"] = quota_result
    gates["all_gates_pass"] = {"status": "PASS" if all(gates.get(name, {}).get("status") == "PASS" for name in ordered) else "FAIL", "order": list(ordered)}

    if publish and gates["all_gates_pass"]["status"] == "PASS":
        writer = production_writer or (lambda value: IndexStore(PRODUCTION_PARQUET.parent).save_family_full(MARKET_INDEX_FAMILY, value))
        writer(normalized)
        production_write_count = 1
        gates["production_reload_integrity_gate"] = IndexStore(PRODUCTION_PARQUET.parent).verify_family(MARKET_INDEX_FAMILY) if production_writer is None else {"status": "PASS"}
    else:
        gates["production_reload_integrity_gate"] = {"status": "NOT_RUN"}
    return {"status": "PASS" if gates["all_gates_pass"]["status"] == "PASS" and (not publish or production_write_count == 1) else "FAIL", "gates": gates, "production_index_store_publish_count": production_write_count}


def secret_scan(secret: str) -> dict[str, Any]:
    if not secret:
        return {"secret_occurrence_count": 0, "scanned_file_count": 0, "status": "BLOCKED_SECRET_SCAN_UNAVAILABLE"}
    try:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = []
    paths.extend(str(path.relative_to(ROOT)) for path in ARTIFACT_DIR.rglob("*") if path.is_file())
    count = scanned = 0
    for raw in sorted(set(path for path in paths if path and path not in {".env"} )):
        path = ROOT / raw
        if path.is_file():
            scanned += 1
            count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
    return {"secret_occurrence_count": count, "scanned_file_count": scanned}


def write_migration_artifacts(*, calendar: Mapping[str, Any], pilot: Mapping[str, Any], backfill: Mapping[str, Any], source_head: str, auth_key: str = "", operational_ledger: Mapping[str, Any] | None = None, validation_source_head: str | None = None) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_json(ARTIFACT_DIR / "market_index_mapping_contract.json", {"mapping_version": MAPPING_CONTRACT_VERSION, "entries": mapping_contract_as_dict(), "mapping_sha256": mapping_contract_sha256()}, auth_key)
    safe_write_json(ARTIFACT_DIR / "raw_trading_calendar_summary.json", {key: value for key, value in calendar.items() if key != "target_dates"}, auth_key)
    pilot_path = ARTIFACT_DIR / "pilot_summary.json"
    if str(pilot.get("status")) != "NOT_RUN" and not pilot_path.exists():
        safe_write_json(pilot_path, {**pilot, "validation_source_head": source_head}, auth_key)
    previous_backfill = _read_json_artifact(ARTIFACT_DIR / "backfill_progress_summary.json")
    progress = {**backfill, "artifact_generation_head": source_head}
    if "validation_source_head" in previous_backfill:
        progress["validation_source_head"] = previous_backfill["validation_source_head"]
    safe_write_json(ARTIFACT_DIR / "backfill_progress_summary.json", progress, auth_key)
    safe_write_json(ARTIFACT_DIR / "coverage_summary.json", {"raw_target_date_count": calendar.get("complete_trading_date_count"), "index_store_date_count": backfill.get("complete_date_count"), "index_store_row_count": backfill.get("staging_rows"), "index_count": 2, "codes": ["1001", "2001"], "status": "PASS" if backfill.get("status", "").startswith("READY_") else "PARTIAL"}, auth_key)
    network_summary = network_summary_from_operational_ledger(operational_ledger) if operational_ledger is not None else {"krx_request_count": backfill.get("krx_request_count", 0), "kospi_dd_trd_request_count": backfill.get("kospi_dd_trd_request_count", 0), "kosdaq_dd_trd_request_count": backfill.get("kosdaq_dd_trd_request_count", 0), "krx_dd_trd_request_count": 0, "retry_count": backfill.get("retry_count", 0), "audit_entry_count": backfill.get("audit_entry_count", 0), "pykrx_live_market_calls": 0}
    previous_network = _read_json_artifact(ARTIFACT_DIR / "network_request_summary.json")
    if previous_network:
        cumulative = validate_cumulative_progress(previous_network, network_summary)
        if cumulative["status"] != "PASS":
            raise MarketDataError("BLOCKED_CUMULATIVE_EVIDENCE_REGRESSION")
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", network_summary, auth_key)
    safe_write_json(ARTIFACT_DIR / "secret_scan.json", secret_scan(auth_key), auth_key)
    manifest = _read_json_artifact(ARTIFACT_DIR / "market_index_migration_v01_manifest.json")
    if validation_source_head:
        validate_manifest_anchor_immutability(manifest, field="fix04_validation_source_head", proposed=validation_source_head)
        if not manifest.get("fix04_validation_source_head"):
            manifest["fix04_validation_source_head"] = validation_source_head
    manifest.update({"work_id": "KRX_INDEX_MIGRATION_V01", "start_head": START_HEAD, "phase_start_head": START_HEAD, "original_implementation_head": "f20e428c0b8d6a6f7bd6a87e7ceb5395c98edf62", "fix01_start_head": "b7f265bd93c19dd72953553787e34b382a9678f4", "status": backfill.get("status"), "current_status": backfill.get("status"), "blockers": backfill.get("blockers", []), "artifact_generation_head": source_head, "last_resume_execution_head": source_head, "artifact_files": sorted(str(path.relative_to(ARTIFACT_DIR)) for path in ARTIFACT_DIR.rglob("*") if path.is_file())})
    if operational_ledger is not None:
        manifest.update({"operational_ledger_schema": OPERATIONAL_LEDGER_SCHEMA_VERSION, "operational_ledger_path": str(OPERATIONAL_LEDGER_PATH.relative_to(ROOT))})
    safe_write_json(ARTIFACT_DIR / "market_index_migration_v01_manifest.json", manifest, auth_key)


def _read_json_artifact(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _quota_blocked_result(calendar: Mapping[str, Any], frame: pd.DataFrame, pending: list[str], quota_before: Mapping[str, Any], quota_after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01",
        "target_date_count": int(calendar.get("complete_trading_date_count", len(calendar.get("target_dates", [])))),
        "complete_date_count": int(frame["date"].nunique()) if not frame.empty else 0,
        "pending_date_count": len(pending),
        "failed_date_count": 0,
        "next_pending_date": pending[0] if pending else None,
        "staging_rows": int(len(frame)),
        "krx_request_count": 0,
        "quota_before": dict(quota_before),
        "quota_after": dict(quota_after),
        "quota_delta": 0,
        "client_request_count": 0,
        "audit_entry_count": 0,
        "retry_count": 0,
        "blockers": ["BACKFILL_PAUSED_QUOTA"],
        "production_index_store_publish_count": 0,
        "operational_run_created": False,
        "staging_parquet": str(STAGING_PARQUET),
        "staging_meta": str(STAGING_META),
        "codes": ["1001", "2001"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate KOSPI/KOSDAQ representative indexes to KRX Open API IndexStore")
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end", default=END_DATE)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--finalize", action="store_true", help="run offline finalization gates against current staging")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.publish and not args.finalize:
        parser.error("--publish requires --finalize")
    if args.finalize:
        calendar = load_offline_calendar(args.start, args.end)
        auth_key = load_auth_key()
        result = finalize_market_index_migration(
            calendar=calendar,
            secret=auth_key,
            operational_ledger_path=OPERATIONAL_LEDGER_PATH,
            validation_source_head=resolve_validation_source_head(),
            publish=args.publish,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") == "PASS" else 1

    calendar = derive_raw_trading_calendar(args.start, args.end)
    existing = _load_staging()
    ledger = ensure_operational_ledger(frame=existing, path=OPERATIONAL_LEDGER_PATH, target_dates=calendar["target_dates"])
    validation_source_head = resolve_validation_source_head()
    validate_resume_pre_network(staging_frame=existing, ledger=ledger, target_dates=calendar["target_dates"], validation_source_head=validation_source_head)
    quota = LocalKrxOpenApiQuota()
    quota_before = _quota_usage(quota)
    pending = [day for day in calendar["target_dates"] if day not in set(existing["date"].astype(str).unique())]
    capacity = _available_whole_dates(quota, len(pending))
    auth_key = load_auth_key()
    runner: MarketIndexMigrationRunner | None = None
    if pending and capacity > 0:
        runner = MarketIndexMigrationRunner(auth_key=auth_key, quota=quota)
    dates = list(PILOT_DATES) if args.pilot else None
    if dates is not None:
        missing = sorted(set(dates) - set(calendar["target_dates"]))
        if missing:
            raise SystemExit(f"pilot dates are not raw target dates: {missing}")
        if runner is None:
            raise MarketDataError("BACKFILL_PAUSED_QUOTA")
        pilot = runner.run({**calendar, "target_dates": dates, "complete_trading_date_count": len(dates)}, resume=True, publish=False, operational_ledger_path=OPERATIONAL_LEDGER_PATH, run_type="PILOT")
        backfill = {"status": pilot.get("status"), "krx_request_count": pilot.get("krx_request_count"), "blockers": pilot.get("blockers", [])}
    else:
        pilot = {"status": "NOT_RUN", "request_count": 0}
        backfill = _quota_blocked_result(calendar, existing, pending, quota_before, _quota_usage(quota)) if runner is None else runner.run(calendar, resume=True, publish=False, operational_ledger_path=OPERATIONAL_LEDGER_PATH)
    operational_ledger = load_operational_ledger(OPERATIONAL_LEDGER_PATH, require_terminal_snapshot=True)
    write_migration_artifacts(calendar=calendar, pilot=pilot, backfill=backfill, source_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), auth_key=auth_key, operational_ledger=operational_ledger)
    print(json.dumps({"pilot": pilot, "backfill": backfill}, ensure_ascii=False, indent=2))
    return 0 if str(backfill.get("status", "")).startswith(("READY_", "PARTIAL_")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_DIR", "END_DATE", "LEGACY_REFERENCE", "LEGACY_REFERENCE_SHA256", "PILOT_DATES", "START_DATE", "START_HEAD",
    "ARTIFACT_DIR", "OPERATIONAL_LEDGER_PATH", "OPERATIONAL_LEDGER_SCHEMA_VERSION", "MarketIndexMigrationRunner", "append_operational_run", "atomic_write_json", "compare_legacy_market_parity", "derive_raw_trading_calendar", "ensure_operational_ledger", "finalize_market_index_migration", "legacy_reference_summary", "load_auth_key", "load_offline_calendar", "load_operational_ledger", "market_rs_parity", "mapping_contract_sha256", "network_summary_from_operational_ledger", "resolve_validation_source_head", "safe_write_json", "secret_scan", "seed_operational_ledger_from_checkpoint", "terminal_run_state", "upgrade_seeded_ledger_checkpoint", "update_operational_run", "validate_complete_staged_date", "validate_current_source_freeze", "validate_cumulative_progress", "validate_manifest_anchor_immutability", "validate_operational_ledger", "validate_operational_ledger_chain", "validate_quota_reconciliation", "validate_resume_pre_network", "validate_runtime_network_provenance", "validate_staging_ledger_continuity", "validate_staging_reuse", "write_migration_artifacts",
]
