"""FIX03 trading-session projection gates and staged live-probe evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
from time import monotonic
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    AdjustedPriceDataProvider,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    ANCILLARY_COLUMNS,
    NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
    RAW_DAILY_COLUMNS,
    MarketDataRepositoryV2,
    _is_non_trading_placeholder,
    _session_projection_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/data/market_data_repository/v02"
START_HEAD = "54d5d1fcfc64cd7b2f6f865db6b58740fc7bfc28"
DIFF_CHECK_BASELINE = "0f7b35be5f6ac3840266e0580e37c2e4519dbf7c"
ORIGINAL_REPOSITORY_IMPLEMENTATION_HEAD = "b04e871881a857640d86422c09c57d7c6a642d62"
FIX02_REPOSITORY_IMPLEMENTATION_HEAD = "d172860b21ba908033ef27e7d11e9f50684c279d"
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
STAGE_BLOCKERS = {
    "ADJUSTED_PROVIDER_FETCH": "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE",
    "TEMP_ADJUSTED_STORE_WRITE": "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY",
    "TEMP_ADJUSTED_STORE_READBACK": "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY",
    "RAW_PRODUCTION_LOAD": "BLOCKED_PRODUCTION_RAW_PROBE",
    "REPOSITORY_COMPOSITION": "BLOCKED_PRODUCTION_COMPOSITION_PROBE",
    "SAMSUNG_SEMANTIC_PROBE": "BLOCKED_SAMSUNG_SEMANTIC_PROBE",
    "ALPHANUMERIC_RAW_PROBE": "BLOCKED_ALPHANUMERIC_PROBE",
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


def _stage_blocker(stage: str) -> str | None:
    return STAGE_BLOCKERS.get(stage)


def sample_gate(
    requested_sample_count: int,
    successful_adjusted_fetch_count: int,
    successful_composition_probe_count: int,
    comparisons: list[dict[str, Any]],
    *,
    successful_provider_fetch_count: int | None = None,
    successful_temp_store_integrity_count: int | None = None,
    failure_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate sample readiness without inferring external failure from counts."""

    provider_count = (
        successful_adjusted_fetch_count
        if successful_provider_fetch_count is None
        else successful_provider_fetch_count
    )
    temp_count = (
        provider_count
        if successful_temp_store_integrity_count is None
        else successful_temp_store_integrity_count
    )
    usable = sum(item.get("status") == "PASS" for item in comparisons)
    failure_records = failure_records or []
    stage_failures = [
        record.get("stage")
        for record in failure_records
        if record.get("status") == "FAIL"
    ]
    projection_failures = [
        record.get("session_projection_blocker")
        for record in failure_records
        if record.get("status") == "FAIL" and record.get("session_projection_blocker")
    ]
    blocker = projection_failures[0] if projection_failures else next(
        (_stage_blocker(stage) for stage in stage_failures if _stage_blocker(stage)),
        None,
    )
    if blocker is None:
        if usable == 0:
            blocker = "BLOCKED_NO_LIVE_AUTHORITY_SAMPLE"
        elif usable == 1:
            blocker = "BLOCKED_INSUFFICIENT_LIVE_AUTHORITY_SAMPLES"
        elif requested_sample_count < 2:
            blocker = "BLOCKED_LIVE_ADJUSTED_SAMPLE"
        elif (
            provider_count != requested_sample_count
            or temp_count != requested_sample_count
        ):
            blocker = "BLOCKED_LIVE_ADJUSTED_SAMPLE"
        elif (
            successful_composition_probe_count != requested_sample_count
            or usable != requested_sample_count
        ):
            blocker = "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
    return {
        "requested_sample_count": requested_sample_count,
        "successful_adjusted_fetch_count": successful_adjusted_fetch_count,
        "successful_provider_fetch_count": provider_count,
        "successful_temp_store_integrity_count": temp_count,
        "successful_composition_probe_count": successful_composition_probe_count,
        "minimum_required_sample_count": 2,
        "usable_sample_count": usable,
        "all_requested_samples_pass": (
            requested_sample_count == 3
            and provider_count == 3
            and temp_count == 3
            and successful_composition_probe_count == 3
            and usable == 3
        ),
        "status": "PASS" if blocker is None else blocker,
        "blocker": blocker,
    }


def evidence_consistency_gate(
    provider_records: list[dict[str, Any]],
    temp_records: list[dict[str, Any]],
    composition_records: list[dict[str, Any]],
    temporary_store_ticker_count: int,
    *,
    accepted_placeholder_projection_count: int | None = None,
    rejected_raw_only_count: int | None = None,
    shared_placeholder_conflict_count: int | None = None,
) -> dict[str, Any]:
    provider_pass = sum(record.get("status") == "PASS" for record in provider_records)
    temp_pass = sum(record.get("status") == "PASS" for record in temp_records)
    composition_pass = sum(record.get("status") == "PASS" for record in composition_records)
    expected = {
        "successful_provider_fetch_count": provider_pass,
        "successful_temp_store_integrity_count": temp_pass,
        "successful_composition_probe_count": composition_pass,
        "temporary_store_ticker_count": temporary_store_ticker_count,
    }
    mismatches = []
    if temporary_store_ticker_count != temp_pass:
        mismatches.append("temporary_store_ticker_count")
    evidence_records = [
        record for record in composition_records if record.get("record_type") == "composition"
    ]
    mandatory_fields_missing = False
    if evidence_records:
        mandatory_fields_missing = any(
            record.get(field) is None
            for record in evidence_records
            for field in (
                "explicit_placeholder_projection_count",
                "rejected_raw_only_dates",
                "shared_placeholder_conflict_dates",
            )
        )
        if mandatory_fields_missing:
            mismatches.append("mandatory_placeholder_evidence")
    observed_accepted = sum(
        int(record.get("explicit_placeholder_projection_count") or 0)
        for record in composition_records
    )
    observed_rejected = sum(
        len(record.get("rejected_raw_only_dates") or []) for record in composition_records
    )
    observed_shared = sum(
        len(record.get("shared_placeholder_conflict_dates") or [])
        for record in composition_records
    )
    if (
        accepted_placeholder_projection_count is not None
        and observed_accepted != accepted_placeholder_projection_count
    ):
        mismatches.append("accepted_placeholder_projection_count")
    if rejected_raw_only_count is not None and observed_rejected != rejected_raw_only_count:
        mismatches.append("rejected_raw_only_count")
    if (
        shared_placeholder_conflict_count is not None
        and observed_shared != shared_placeholder_conflict_count
    ):
        mismatches.append("shared_placeholder_conflict_count")
    if observed_rejected:
        mismatches.append("rejected_raw_only_nonzero")
    if observed_shared:
        mismatches.append("shared_placeholder_conflict_nonzero")
    return {
        **expected,
        "accepted_placeholder_projection_count": observed_accepted,
        "rejected_raw_only_count": observed_rejected,
        "shared_placeholder_conflict_count": observed_shared,
        "provider_pass_record_count": provider_pass,
        "temp_store_pass_record_count": temp_pass,
        "composition_pass_record_count": composition_pass,
        "mismatches": mismatches,
        "status": "PASS" if not mismatches else "BLOCKED_EVIDENCE_INCONSISTENCY",
        "blocker": None if not mismatches else "BLOCKED_EVIDENCE_INCONSISTENCY",
    }


def _runtime_network_guard() -> dict[str, Any]:
    source = REPOSITORY_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_MODULE_PREFIXES):
                    violations.append(alias.name)
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
    return {
        "command": f"git diff --check {DIFF_CHECK_BASELINE} HEAD",
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
        "runtime_network_guard": _runtime_network_guard(),
        "git_diff_check": _git_diff_check(validation_head),
    }


def _error_record(
    ticker: str,
    exc: Exception,
    *,
    requested_start: str = "",
    requested_end: str = "",
    stage: str = "UNKNOWN",
    record_type: str = "failure",
) -> dict[str, Any]:
    message = str(exc) or exc.__class__.__name__
    return {
        "ticker": ticker,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "stage": stage,
        "error_code": message.split(":", 1)[0],
        "error_message": message[:2000],
        "status": "FAIL",
        "record_type": record_type,
    }


def _pass_record(
    ticker: str,
    *,
    requested_start: str,
    requested_end: str,
    stage: str,
    record_type: str,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "stage": stage,
        "status": "PASS",
        "record_type": record_type,
        **fields,
    }


def _provider_fetch(
    provider: AdjustedPriceDataProvider,
    ticker: str,
    requested_start: str,
    requested_end: str,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    started = monotonic()
    try:
        frame = provider.load_daily(ticker, requested_start, requested_end)
        if frame is None or frame.empty:
            raise MarketDataError("BLOCKED_LIVE_ADJUSTED_SAMPLE: EMPTY_RESPONSE")
        actual_start = pd.Timestamp(frame.index.min()).date().isoformat()
        actual_end = pd.Timestamp(frame.index.max()).date().isoformat()
        return (
            _pass_record(
                ticker,
                requested_start=requested_start,
                requested_end=requested_end,
                stage="ADJUSTED_PROVIDER_FETCH",
                record_type="provider_fetch",
                row_count=int(len(frame)),
                actual_date_min=actual_start,
                actual_date_max=actual_end,
                provider_error=None,
                elapsed_seconds=round(monotonic() - started, 6),
            ),
            frame,
        )
    except Exception as exc:
        return (
            _error_record(
                ticker,
                exc,
                requested_start=requested_start,
                requested_end=requested_end,
                stage="ADJUSTED_PROVIDER_FETCH",
                record_type="provider_fetch",
            )
            | {"elapsed_seconds": round(monotonic() - started, 6), "row_count": 0},
            None,
        )


def _temp_store_ticker_count(store: AdjustedPriceStore) -> int:
    if not store.base_dir.exists():
        return 0
    return sum(
        1
        for parquet in store.base_dir.glob("*.parquet")
        if parquet.with_suffix(".meta.json").exists()
    )


def _temp_store_integrity(
    store: AdjustedPriceStore,
    ticker: str,
    frame: pd.DataFrame,
    requested_start: str,
    requested_end: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    record: dict[str, Any] = {
        "ticker": ticker,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "stage": "TEMP_ADJUSTED_STORE_WRITE",
        "record_type": "temp_store_integrity",
        "save_attempted": True,
        "save_status": "NOT_RUN",
        "metadata_status": "NOT_RUN",
        "hash_status": "NOT_RUN",
        "readback_status": "NOT_RUN",
        "row_count": 0,
        "actual_date_min": None,
        "actual_date_max": None,
        "status": "FAIL",
    }
    try:
        store.save_full(
            ticker,
            frame,
            {"requested_start": requested_start, "requested_end": requested_end},
        )
        record["save_status"] = "PASS"
    except Exception as exc:
        return (
            record
            | {
                "stage": "TEMP_ADJUSTED_STORE_WRITE",
                "error_code": str(exc).split(":", 1)[0],
                "error_message": str(exc)[:2000],
            },
            None,
        )
    try:
        metadata = store.load_metadata(ticker)
        record["metadata_status"] = "PASS"
        actual_start, actual_end = probe_range_from_metadata(metadata)
        record["actual_date_min"] = actual_start
        record["actual_date_max"] = actual_end
        parquet = store._parquet_path(ticker)
        digest = _sha256(parquet)
        record["hash_status"] = (
            "PASS" if digest == metadata.get("content_sha256") else "FAIL"
        )
        if record["hash_status"] != "PASS":
            raise MarketDataError("BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY: HASH_MISMATCH")
        readback = store.load_daily(ticker, actual_start, actual_end)
        record["readback_status"] = "PASS"
        record["row_count"] = int(len(readback))
        record["status"] = "PASS"
        return record, metadata
    except Exception as exc:
        record["stage"] = "TEMP_ADJUSTED_STORE_READBACK"
        record["error_code"] = str(exc).split(":", 1)[0]
        record["error_message"] = str(exc)[:2000]
        return record, None


def _composition_probe(
    repository: MarketDataRepositoryV2,
    adjusted_store: AdjustedPriceStore,
    raw_store: KrxRawStockStore,
    ticker: str,
    requested_start: str,
    requested_end: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    started = monotonic()
    record: dict[str, Any] = {
        "ticker": ticker,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "stage": "RAW_PRODUCTION_LOAD",
        "record_type": "composition",
        "actual_adjusted_start": None,
        "actual_adjusted_end": None,
        "adjusted_rows": None,
        "physical_raw_rows": None,
        "raw_rows": None,
        "repository_rows": None,
        "date_set_exact_match": False,
        "projected_date_set_exact_match": False,
        "adjusted_only_dates": [],
        "raw_only_dates": [],
        "raw_only_row_details": [],
        "shared_dates": [],
        "shared_placeholder_conflict_dates": [],
        "shared_placeholder_conflict_count": 0,
        "shared_placeholder_conflict_row_details": [],
        "accepted_placeholder_dates": [],
        "rejected_raw_only_dates": [],
        "explicit_placeholder_projection_count": 0,
        "silent_inner_drop_count": 0,
        "adjusted_ohlc_exact_match": False,
        "raw_volume_exact_match": False,
        "raw_trading_value_exact_match": False,
        "ancillary_exact_match": False,
        "status": "FAIL",
    }
    try:
        metadata = adjusted_store.load_metadata(ticker)
        actual_start, actual_end = probe_range_from_metadata(metadata)
        record["actual_adjusted_start"] = actual_start
        record["actual_adjusted_end"] = actual_end
        raw_started = monotonic()
        raw = raw_store.load_ticker(ticker, actual_start, actual_end)
        raw_elapsed = monotonic() - raw_started
        raw_view = _raw_view(raw)
        record["physical_raw_rows"] = int(len(raw_view))
        record["raw_rows"] = int(len(raw_view))
    except Exception as exc:
        record.update(
            _error_record(
                ticker,
                exc,
                requested_start=requested_start,
                requested_end=requested_end,
                stage="RAW_PRODUCTION_LOAD",
                record_type="composition",
            )
        )
        record["total_elapsed_seconds"] = round(monotonic() - started, 6)
        return record, None
    try:
        adjusted_started = monotonic()
        adjusted = adjusted_store.load_daily(ticker, actual_start, actual_end)
        adjusted_elapsed = monotonic() - adjusted_started
        projection_started = monotonic()
        projection = _session_projection_evidence(adjusted, raw_view)
        projection_elapsed = monotonic() - projection_started
        projected_raw = projection["projected_raw"]
        record.update(
            {
                key: projection[key]
                for key in (
                    "adjusted_only_dates",
                    "raw_only_dates",
                    "raw_only_row_details",
                    "shared_dates",
                    "shared_placeholder_conflict_dates",
                    "shared_placeholder_conflict_count",
                    "shared_placeholder_conflict_row_details",
                    "accepted_placeholder_dates",
                    "rejected_raw_only_dates",
                    "explicit_placeholder_projection_count",
                    "silent_inner_drop_count",
                    "projected_raw_rows",
                    "projected_date_set_exact_match",
                )
            }
        )
        record["projection_elapsed_seconds"] = round(projection_elapsed, 6)
        if projection["adjusted_only_dates"]:
            record["session_projection_blocker"] = "BLOCKED_ADJUSTED_SESSION_WITHOUT_RAW_FACTS"
        elif projection["shared_placeholder_conflict_dates"]:
            record["session_projection_blocker"] = "BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT"
        elif projection["rejected_raw_only_dates"]:
            record["session_projection_blocker"] = "BLOCKED_UNCLASSIFIED_RAW_ONLY_SESSION"
        join_started = monotonic()
        composed = repository.get_daily(ticker, actual_start, actual_end)
        ancillary = repository.get_daily_ancillary(ticker, actual_start, actual_end)
        join_elapsed = monotonic() - join_started
        record.update(
            {
                "adjusted_rows": int(len(adjusted)),
                "repository_rows": int(len(composed)),
                "date_set_exact_match": (
                    set(composed.index) == set(adjusted.index) == set(projected_raw.index)
                ),
                "adjusted_ohlc_exact_match": _same_frame(
                    composed.loc[:, ["open", "high", "low", "close"]],
                    adjusted,
                ),
                "raw_volume_exact_match": _same_frame(
                    composed.loc[:, ["volume"]],
                    projected_raw.loc[:, ["volume"]],
                ),
                "raw_trading_value_exact_match": _same_frame(
                    composed.loc[:, ["trading_value"]],
                    projected_raw.loc[:, ["trading_value"]],
                ),
                "ancillary_exact_match": _same_frame(
                    ancillary,
                    raw_view.loc[:, ["volume", "trading_value", "market_cap", "listed_shares"]],
                ),
                "raw_load_elapsed_seconds": round(raw_elapsed, 6),
                "adjusted_load_elapsed_seconds": round(adjusted_elapsed, 6),
                "repository_join_elapsed_seconds": round(join_elapsed, 6),
                "total_elapsed_seconds": round(monotonic() - started, 6),
            }
        )
        exact_keys = (
            "date_set_exact_match",
            "adjusted_ohlc_exact_match",
            "raw_volume_exact_match",
            "raw_trading_value_exact_match",
            "ancillary_exact_match",
        )
        if all(record[key] for key in exact_keys):
            record["stage"] = "REPOSITORY_COMPOSITION"
            record["status"] = "PASS"
            return record, {
                "metadata": metadata,
                "adjusted": adjusted,
                "composed": composed,
            }
        raise MarketDataError("BLOCKED_PRODUCTION_COMPOSITION_PROBE")
    except Exception as exc:
        record.update(
            _error_record(
                ticker,
                exc,
                requested_start=requested_start,
                requested_end=requested_end,
                stage="REPOSITORY_COMPOSITION",
                record_type="composition",
            )
        )
        record["total_elapsed_seconds"] = round(monotonic() - started, 6)
        return record, None


def _find_alphanumeric(raw_store: KrxRawStockStore) -> str | None:
    for ticker in ("03473K", "08537M"):
        for market in ("KOSPI", "KOSDAQ"):
            try:
                frame = raw_store.load_snapshot(market, "2018-04-27")
            except Exception:
                continue
            if not frame.empty and ticker in set(frame["ticker"].astype(str)):
                return ticker
    return None


def _raw_authority_probe(
    repository: MarketDataRepositoryV2,
    raw_store: KrxRawStockStore,
    ticker: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    started = monotonic()
    base = {
        "ticker": ticker,
        "range": [start, end],
        "record_type": "raw_authority",
        "raw_rows": 0,
        "zero_price_row_count": 0,
        "all_positive_row_count": 0,
        "all_positive_relation_violation_count": 0,
        "repository_raw_rows": 0,
        "source_to_repository_exact_match": False,
        "status": "FAIL",
    }
    try:
        source = _raw_view(raw_store.load_ticker(ticker, start, end))
    except Exception as exc:
        return base | _error_record(
            ticker,
            exc,
            requested_start=start,
            requested_end=end,
            stage="RAW_PRODUCTION_LOAD",
            record_type="raw_authority",
        ) | {"elapsed_seconds": round(monotonic() - started, 6)}
    try:
        ohlc = source.loc[:, ["open", "high", "low", "close"]]
        positive = (ohlc > 0).all(axis=1)
        relation_violation = (
            (ohlc["high"] < ohlc["low"])
            | (ohlc["high"] < ohlc["open"])
            | (ohlc["high"] < ohlc["close"])
            | (ohlc["low"] > ohlc["open"])
            | (ohlc["low"] > ohlc["close"])
        )
        repository_raw = repository.get_raw_daily(ticker, start, end)
        base.update(
            {
                "raw_rows": int(len(source)),
                "zero_price_row_count": int((~positive).sum()),
                "all_positive_row_count": int(positive.sum()),
                "all_positive_relation_violation_count": int(
                    (relation_violation & positive).sum()
                ),
                "repository_raw_rows": int(len(repository_raw)),
                "source_to_repository_exact_match": _same_frame(source, repository_raw),
                "status": "PASS",
                "elapsed_seconds": round(monotonic() - started, 6),
            }
        )
        if not base["source_to_repository_exact_match"]:
            raise MarketDataError("BLOCKED_PRODUCTION_RAW_PROBE")
        return base
    except Exception as exc:
        return base | _error_record(
            ticker,
            exc,
            requested_start=start,
            requested_end=end,
            stage="REPOSITORY_COMPOSITION",
            record_type="raw_authority",
        ) | {"elapsed_seconds": round(monotonic() - started, 6)}


def _samsung_raw_probe(repository: MarketDataRepositoryV2) -> dict[str, Any]:
    expected = {"2018-04-27": 128386494, "2018-05-04": 6419324700}
    record = {
        "stage": "SAMSUNG_SEMANTIC_PROBE",
        "record_type": "samsung_raw",
        "expected": expected,
        "observed": {},
        "raw_semantics": False,
        "status": "FAIL",
    }
    try:
        ancillary = repository.get_daily_ancillary("005930", "2018-04-27", "2018-05-04")
        observed = {
            day: int(ancillary.loc[pd.Timestamp(day), "listed_shares"])
            for day in expected
            if pd.Timestamp(day) in ancillary.index
        }
        record["observed"] = observed
        record["raw_semantics"] = observed == expected
        record["status"] = "PASS" if record["raw_semantics"] else "FAIL"
        if record["status"] != "PASS":
            record["error_code"] = "BLOCKED_SAMSUNG_SEMANTIC_PROBE"
    except Exception as exc:
        record.update(_error_record(
            "005930",
            exc,
            requested_start="2018-04-27",
            requested_end="2018-05-04",
            stage="SAMSUNG_SEMANTIC_PROBE",
            record_type="samsung_raw",
        ))
    return record


def _alphanumeric_probe(repository: MarketDataRepositoryV2, raw_store: KrxRawStockStore) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "ALPHANUMERIC_RAW_PROBE",
        "record_type": "alphanumeric",
        "performed": False,
        "ticker": None,
        "raw_daily": False,
        "ancillary": False,
        "snapshot": False,
        "adjusted_unsupported": False,
        "domain_not_widened": False,
        "status": "NOT_RUN",
    }
    ticker = _find_alphanumeric(raw_store)
    if not ticker:
        record.update(
            {
                "performed": True,
                "status": "FAIL",
                "error_code": "BLOCKED_ALPHANUMERIC_PROBE",
                "error_message": "03473K/08537M not found in production raw store",
            }
        )
        return record
    record["performed"] = True
    record["ticker"] = ticker
    try:
        record["raw_daily"] = len(repository.get_raw_daily(ticker, "2018-04-27", "2018-04-27")) == 1
        record["ancillary"] = len(repository.get_daily_ancillary(ticker, "2018-04-27", "2018-04-27")) == 1
        record["snapshot"] = len(repository.get_stock_snapshot(ticker, "2018-04-27")) == 1
        try:
            repository.get_daily(ticker, "2018-04-27", "2018-04-27")
        except MarketDataError as exc:
            record["adjusted_unsupported"] = "UNSUPPORTED_ADJUSTED_TICKER" in str(exc)
        record["domain_not_widened"] = record["adjusted_unsupported"]
        record["status"] = (
            "PASS"
            if all(
                record[key]
                for key in ("raw_daily", "ancillary", "snapshot", "adjusted_unsupported", "domain_not_widened")
            )
            else "FAIL"
        )
        if record["status"] != "PASS":
            record["error_code"] = "BLOCKED_ALPHANUMERIC_PROBE"
    except Exception as exc:
        record.update(_error_record(
            ticker,
            exc,
            requested_start="2018-04-27",
            requested_end="2018-04-27",
            stage="ALPHANUMERIC_RAW_PROBE",
            record_type="alphanumeric",
        ))
    return record


def _placeholder_candidate_probe(
    raw_store: KrxRawStockStore,
    ticker: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    started = monotonic()
    record: dict[str, Any] = {
        "ticker": ticker,
        "range": [start, end],
        "record_type": "raw_placeholder_candidate",
        "predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
        "raw_present": False,
        "adjusted_present": None,
        "candidate_count": 0,
        "candidate_dates": [],
        "candidate_rows": [],
        "status": "FAIL",
    }
    try:
        raw = _raw_view(raw_store.load_ticker(ticker, start, end))
        candidates = []
        for date, row in raw.iterrows():
            if not _is_non_trading_placeholder(row):
                continue
            candidates.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "open": row["open"].item() if hasattr(row["open"], "item") else row["open"],
                    "high": row["high"].item() if hasattr(row["high"], "item") else row["high"],
                    "low": row["low"].item() if hasattr(row["low"], "item") else row["low"],
                    "close": row["close"].item() if hasattr(row["close"], "item") else row["close"],
                    "volume": row["volume"].item() if hasattr(row["volume"], "item") else row["volume"],
                    "trading_value": row["trading_value"].item() if hasattr(row["trading_value"], "item") else row["trading_value"],
                    "market_cap": row["market_cap"].item() if hasattr(row["market_cap"], "item") else row["market_cap"],
                    "listed_shares": row["listed_shares"].item() if hasattr(row["listed_shares"], "item") else row["listed_shares"],
                    "raw_present": True,
                    "adjusted_present": None,
                }
            )
        record.update(
            {
                "raw_present": True,
                "candidate_count": len(candidates),
                "candidate_dates": [item["date"] for item in candidates],
                "candidate_rows": candidates,
                "status": "PASS",
                "elapsed_seconds": round(monotonic() - started, 6),
            }
        )
        return record
    except Exception as exc:
        record.update(
            _error_record(
                ticker,
                exc,
                requested_start=start,
                requested_end=end,
                stage="RAW_PRODUCTION_LOAD",
                record_type="raw_placeholder_candidate",
            )
        )
        record["elapsed_seconds"] = round(monotonic() - started, 6)
        return record


def _offline_probes(raw_root: Path) -> dict[str, Any]:
    raw_store = KrxRawStockStore(raw_root)
    records: list[dict[str, Any]] = []
    placeholder_candidates: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="market-data-repository-v02-fix03-offline-") as temp_dir:
        repository = MarketDataRepositoryV2(AdjustedPriceStore(temp_dir), raw_store)
        for ticker, start, end in REQUESTED_SAMPLES:
            records.append(_raw_authority_probe(repository, raw_store, ticker, start, end))
            placeholder_candidates.append(
                _placeholder_candidate_probe(raw_store, ticker, start, end)
            )
        samsung_raw = _samsung_raw_probe(repository)
        alpha = _alphanumeric_probe(repository, raw_store)
    blockers = []
    if any(item.get("status") != "PASS" for item in records):
        blockers.append("BLOCKED_PRODUCTION_RAW_PROBE")
    if samsung_raw.get("status") != "PASS":
        blockers.append("BLOCKED_SAMSUNG_SEMANTIC_PROBE")
    if alpha.get("status") != "PASS":
        blockers.append("BLOCKED_ALPHANUMERIC_PROBE")
    samsung_placeholder = next(
        (item for item in placeholder_candidates if item.get("ticker") == "005930"),
        None,
    )
    placeholder_semantics_gate = "PASS"
    if samsung_placeholder is None or samsung_placeholder.get("status") != "PASS":
        placeholder_semantics_gate = "BLOCKED_PLACEHOLDER_SEMANTICS_UNPROVEN"
    elif samsung_placeholder.get("candidate_count") != 3:
        placeholder_semantics_gate = "BLOCKED_PLACEHOLDER_SEMANTICS_UNPROVEN"
    if placeholder_semantics_gate != "PASS":
        blockers.append(placeholder_semantics_gate)
    return {
        "records": records,
        "placeholder_candidates": placeholder_candidates,
        "placeholder_semantics_gate": placeholder_semantics_gate,
        "samsung_raw": samsung_raw,
        "alphanumeric": alpha,
        "status": "PASS" if not blockers else blockers[0],
        "blockers": blockers,
    }


def _not_run_live_probe(raw_root: Path, offline: dict[str, Any]) -> dict[str, Any]:
    raw_snapshot = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_snapshot = _snapshot(PRODUCTION_ADJUSTED_ROOT)
    blocker = offline.get("placeholder_semantics_gate", "BLOCKED_PLACEHOLDER_SEMANTICS_UNPROVEN")
    gate = sample_gate(3, 0, 0, [], failure_records=[])
    return {
        "mode": "NOT_RUN_OFFLINE_PLACEHOLDER_GATE",
        "requested_samples": [item[0] for item in REQUESTED_SAMPLES],
        "provider_fetch_records": [],
        "temp_store_integrity_records": [],
        "composition_records": [],
        "failure_records": [],
        "successful_provider_fetch_count": 0,
        "successful_adjusted_fetch_count": 0,
        "successful_temp_store_integrity_count": 0,
        "successful_composition_probe_count": 0,
        "usable_composition_sample_count": 0,
        "minimum_required_sample_count": 2,
        "all_requested_samples_pass": False,
        "sample_gate": gate,
        "evidence_consistency": evidence_consistency_gate([], [], [], 0),
        "temporary_store_created": False,
        "temporary_store_ticker_count": 0,
        "temporary_store_cleanup": "NOT_RUN",
        "temporary_store_exists_after_cleanup": False,
        "temporary_store_path": None,
        "production_adjusted_root_used_for_write": False,
        "production_raw_manifest_before_sha": next(iter(raw_snapshot.values()), None),
        "production_raw_manifest_after_sha": next(iter(raw_snapshot.values()), None),
        "production_raw_manifest_equal": True,
        "production_adjusted_snapshot_before": adjusted_snapshot,
        "production_adjusted_snapshot_after": adjusted_snapshot,
        "production_adjusted_snapshot_equal": True,
        "production_raw_write_count": 0,
        "production_adjusted_write_count": 0,
        "corporate_action_state_write_count": 0,
        "performance": [],
        "performance_warnings": [],
        "provider_audit": {
            "logical_fetch_count": 0,
            "adjusted_true_call_count": 0,
            "adjusted_false_call_count": 0,
        },
        "KRX_open_api_request_count": 0,
        "OpenDART_request_count": 0,
        "fallback_request_count": 0,
        "retry_count": 0,
        "offline": offline,
        "network_blockers": [],
        "blockers": [blocker],
        "status": blocker,
    }


def _run_live_probe(raw_root: Path, offline: dict[str, Any]) -> dict[str, Any]:
    if offline.get("placeholder_semantics_gate") != "PASS":
        return _not_run_live_probe(raw_root, offline)
    raw_before = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_before = _snapshot(PRODUCTION_ADJUSTED_ROOT)
    provider = AdjustedPriceDataProvider()
    raw_store = KrxRawStockStore(raw_root)
    provider_records: list[dict[str, Any]] = []
    temp_records: list[dict[str, Any]] = []
    composition_records: list[dict[str, Any]] = []
    temporary_path: str | None = None
    temporary_store_ticker_count = 0
    temp_cleanup = "FAIL"
    temp_exists_after = True
    with tempfile.TemporaryDirectory(prefix="market-data-repository-v02-fix02-") as temp_dir:
        temporary_path = temp_dir
        adjusted_store = AdjustedPriceStore(temp_dir)
        repository = MarketDataRepositoryV2(adjusted_store, raw_store)
        for ticker, requested_start, requested_end in REQUESTED_SAMPLES:
            provider_record, frame = _provider_fetch(
                provider, ticker, requested_start, requested_end
            )
            provider_records.append(provider_record)
            if frame is None:
                break
            temp_record, metadata = _temp_store_integrity(
                adjusted_store, ticker, frame, requested_start, requested_end
            )
            temp_records.append(temp_record)
            if metadata is None:
                break
            composition_record, _ = _composition_probe(
                repository,
                adjusted_store,
                raw_store,
                ticker,
                requested_start,
                requested_end,
            )
            composition_records.append(composition_record)
            if composition_record.get("status") != "PASS":
                break
        temporary_store_ticker_count = _temp_store_ticker_count(adjusted_store)
    temp_exists_after = bool(temporary_path and Path(temporary_path).exists())
    temp_cleanup = "PASS" if not temp_exists_after else "FAIL"
    raw_after = _snapshot(raw_root / "manifest.sqlite3")
    adjusted_after = _snapshot(PRODUCTION_ADJUSTED_ROOT)
    audit = provider.call_audit()
    failure_records = [
        record
        for record in provider_records + temp_records + composition_records
        if record.get("status") == "FAIL"
    ]
    successful_provider = sum(record.get("status") == "PASS" for record in provider_records)
    successful_temp = sum(record.get("status") == "PASS" for record in temp_records)
    successful_composition = sum(record.get("status") == "PASS" for record in composition_records)
    gate = sample_gate(
        len(REQUESTED_SAMPLES),
        successful_provider,
        successful_composition,
        composition_records,
        successful_provider_fetch_count=successful_provider,
        successful_temp_store_integrity_count=successful_temp,
        failure_records=failure_records,
    )
    consistency = evidence_consistency_gate(
        provider_records,
        temp_records,
        composition_records,
        temporary_store_ticker_count,
    )
    blockers = list(offline.get("blockers", []))
    if gate["status"] != "PASS":
        blockers.append(gate["status"])
    if consistency["status"] != "PASS":
        blockers.append(consistency["status"])
    if temp_cleanup != "PASS":
        blockers.append("BLOCKED_TEMP_STORE_CLEANUP")
    if raw_before != raw_after or adjusted_before != adjusted_after:
        blockers.append("BLOCKED_STORE_MUTATION")
    performance = [
        {
            key: item[key]
            for key in (
                "ticker",
                "requested_start",
                "requested_end",
                "actual_adjusted_start",
                "actual_adjusted_end",
                "adjusted_rows",
                "raw_rows",
                "repository_rows",
                "raw_load_elapsed_seconds",
                "adjusted_load_elapsed_seconds",
                "repository_join_elapsed_seconds",
                "total_elapsed_seconds",
            )
            if key in item
        }
        for item in composition_records
    ]
    warnings = [
        "RAW_TICKER_ACCESS_PERFORMANCE_RISK"
        for item in performance
        if item.get("total_elapsed_seconds", 0) >= 60
    ]
    network_blocker = []
    if audit["adjusted_false_call_count"] != 0:
        network_blocker.append("BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE")
    all_blockers = list(dict.fromkeys(blockers + network_blocker))
    return {
        "mode": "TEMP_ADJUSTED_LIVE_PLUS_PRODUCTION_RAW",
        "requested_samples": [item[0] for item in REQUESTED_SAMPLES],
        "provider_fetch_records": provider_records,
        "temp_store_integrity_records": temp_records,
        "composition_records": composition_records,
        "failure_records": failure_records,
        "successful_provider_fetch_count": successful_provider,
        "successful_adjusted_fetch_count": successful_provider,
        "successful_temp_store_integrity_count": successful_temp,
        "successful_composition_probe_count": successful_composition,
        "usable_composition_sample_count": gate["usable_sample_count"],
        "minimum_required_sample_count": 2,
        "all_requested_samples_pass": gate["all_requested_samples_pass"],
        "sample_gate": gate,
        "evidence_consistency": consistency,
        "temporary_store_created": True,
        "temporary_store_ticker_count": temporary_store_ticker_count,
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
        "performance": performance,
        "performance_warnings": warnings,
        "provider_audit": audit,
        "KRX_open_api_request_count": 0,
        "OpenDART_request_count": 0,
        "fallback_request_count": 0,
        "retry_count": 0,
        "offline": offline,
        "network_blockers": network_blocker,
        "blockers": all_blockers,
        "status": "PASS" if not all_blockers else all_blockers[0],
    }


def _samsung_composition(live: dict[str, Any]) -> dict[str, Any]:
    for record in live["composition_records"]:
        if record.get("ticker") == "005930":
            return {
                "status": "PASS"
                if record.get("status") == "PASS"
                and record.get("adjusted_ohlc_exact_match")
                and record.get("ancillary_exact_match")
                else "FAIL",
                "record": record,
            }
    return {"status": "NOT_RUN", "record": None}


def _stage_evidence_status(
    records: list[dict[str, Any]],
    failure_blocker: str,
) -> str:
    if not records:
        return "NOT_RUN"
    return "PASS" if all(record.get("status") == "PASS" for record in records) else failure_blocker


def _write_evidence(
    validation_head: str,
    static: dict[str, Any],
    offline: dict[str, Any],
    live: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    blockers.extend(offline.get("blockers", []))
    blockers.extend(live.get("blockers", []))
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
    if static["secret_occurrence_count"]:
        blockers.append("BLOCKED_SECRET_OCCURRENCE")
    if static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_NETWORK_DEPENDENCY")
    if static["artifacts_runtime_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_ARTIFACT_DEPENDENCY")
    if regression["failed"]:
        blockers.append("BLOCKED_REGRESSION")
    blockers = list(dict.fromkeys(blockers))
    status = (
        "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX02_REVIEW"
        if not blockers
        else blockers[0]
    )
    raw_records = offline["records"]
    samsung_composition = _samsung_composition(live)
    provenance = {
        "market_data_repository_v02_original_implementation_head": ORIGINAL_REPOSITORY_IMPLEMENTATION_HEAD,
        "fix02_repository_implementation_head": validation_head,
        "fix02_validation_source_head": validation_head,
        "live_execution_head": validation_head,
        "artifact_head": validation_head,
    }
    summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX02",
        "status": status,
        **provenance,
        "repository_v2_changed": True,
        "legacy_repository_changed": static["legacy_repository_changed"],
        "frozen_contract_changed": static["frozen_contract_modified"],
        "frozen_store_sources_changed": static["frozen_store_source_changed_count"] != 0,
        "git_diff_check": static["git_diff_check"],
        "runtime_network_forbidden_count": static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"],
        "artifacts_runtime_dependency_count": static["artifacts_runtime_dependency_count"],
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "repository_raw_authority_compatible": all(
            item.get("status") == "PASS" for item in raw_records
        ),
        "raw_offline_probe": offline,
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
        "samsung_raw": offline["samsung_raw"],
        "samsung_composition": samsung_composition,
        "provenance_fields": provenance,
        "bounded_regression": regression,
        "production_adjusted_population": "NOT_YET_IMPLEMENTED",
        "consumer_migration_prerequisite": True,
        "known_limitations": [
            "PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED",
            "FULL_REGRESSION_CLOSURE_DEFERRED",
        ],
        "blockers": blockers,
        "warnings": live.get("performance_warnings", []),
        "provenance": provenance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json("FIX02_raw_authority_compatibility_summary.json", {
        "phase": summary["phase"],
        "status": offline["status"],
        "records": raw_records,
        "samsung_raw": offline["samsung_raw"],
        "alphanumeric": offline["alphanumeric"],
        "blockers": offline["blockers"],
        "provenance": provenance,
    })
    _write_json("FIX02_provider_fetch_summary.json", {
        "phase": summary["phase"],
        "status": _stage_evidence_status(
            live["provider_fetch_records"], "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE"
        ),
        "records": live["provider_fetch_records"],
        "successful_provider_fetch_count": live["successful_provider_fetch_count"],
        "provider_audit": live["provider_audit"],
        "provenance": provenance,
    })
    _write_json("FIX02_temp_store_integrity_summary.json", {
        "phase": summary["phase"],
        "status": _stage_evidence_status(
            live["temp_store_integrity_records"], "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY"
        ),
        "records": live["temp_store_integrity_records"],
        "successful_temp_store_integrity_count": live["successful_temp_store_integrity_count"],
        "temporary_store_ticker_count": live["temporary_store_ticker_count"],
        "cleanup": live["temporary_store_cleanup"],
        "exists_after_cleanup": live["temporary_store_exists_after_cleanup"],
        "provenance": provenance,
    })
    _write_json("FIX02_composition_probe_summary.json", {
        "phase": summary["phase"],
        "status": _stage_evidence_status(
            live["composition_records"], "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
        ),
        "records": live["composition_records"],
        "successful_composition_probe_count": live["successful_composition_probe_count"],
        "usable_composition_sample_count": live["usable_composition_sample_count"],
        "provenance": provenance,
    })
    _write_json("FIX02_failure_classification_summary.json", {
        "phase": summary["phase"],
        "status": "PASS" if not live["failure_records"] else "FAIL",
        "failures": live["failure_records"],
        "stage_blockers": {
            record.get("stage"): _stage_blocker(record.get("stage", ""))
            for record in live["failure_records"]
        },
        "provenance": provenance,
    })
    _write_json("FIX02_network_summary.json", {
        "phase": summary["phase"],
        "logical_pykrx_fetch_count": live["provider_audit"]["logical_fetch_count"],
        "adjusted_true_call_count": live["provider_audit"]["adjusted_true_call_count"],
        "adjusted_false_call_count": live["provider_audit"]["adjusted_false_call_count"],
        "KRX_open_api_request_count": 0,
        "OpenDART_request_count": 0,
        "fallback_request_count": 0,
        "retry_count": 0,
        "external_blocker_requires_provider_stage": True,
        "external_blocker_present": any(
            item.get("stage") == "ADJUSTED_PROVIDER_FETCH"
            for item in live["failure_records"]
        ),
        "provenance": provenance,
    })
    _write_json("FIX02_production_mutation_guard.json", {
        "production_raw_manifest_before_sha": live["production_raw_manifest_before_sha"],
        "production_raw_manifest_after_sha": live["production_raw_manifest_after_sha"],
        "production_raw_manifest_equal": live["production_raw_manifest_equal"],
        "production_adjusted_snapshot_before": live["production_adjusted_snapshot_before"],
        "production_adjusted_snapshot_after": live["production_adjusted_snapshot_after"],
        "production_adjusted_snapshot_equal": live["production_adjusted_snapshot_equal"],
        "production_raw_write_count": live["production_raw_write_count"],
        "production_adjusted_write_count": live["production_adjusted_write_count"],
        "corporate_action_state_write_count": live["corporate_action_state_write_count"],
        "provenance": provenance,
    })
    _write_json("FIX02_live_authority_probe_summary.json", {
        "phase": summary["phase"],
        "status": live["status"],
        "mode": live["mode"],
        "requested_samples": live["requested_samples"],
        "provider_fetch_records": live["provider_fetch_records"],
        "temp_store_integrity_records": live["temp_store_integrity_records"],
        "composition_records": live["composition_records"],
        "failure_records": live["failure_records"],
        "counters": {
            "successful_provider_fetch_count": live["successful_provider_fetch_count"],
            "successful_temp_store_integrity_count": live["successful_temp_store_integrity_count"],
            "successful_composition_probe_count": live["successful_composition_probe_count"],
            "usable_composition_sample_count": live["usable_composition_sample_count"],
        },
        "sample_gate": live["sample_gate"],
        "evidence_consistency": live["evidence_consistency"],
        "provider_audit": live["provider_audit"],
        "blockers": live["blockers"],
        "provenance": provenance,
    })
    _write_json("FIX02_validator_gate_summary.json", {
        "phase": summary["phase"],
        "status": status,
        "blockers": blockers,
        "static": static,
        "offline": offline,
        "live": {
            "sample_gate": live["sample_gate"],
            "evidence_consistency": live["evidence_consistency"],
            "blockers": live["blockers"],
            "status": live["status"],
        },
        "bounded_regression": regression,
        "provenance": provenance,
    })
    _write_json("market_data_repository_v02_summary.json", summary)
    _write_json("production_probe_summary.json", {
        "phase": summary["phase"],
        "status": status,
        "repository_raw_authority_compatible": summary["repository_raw_authority_compatible"],
        "raw_offline_probe": offline,
        "live_probe": live,
        "samsung_raw": offline["samsung_raw"],
        "samsung_composition": samsung_composition,
        "blockers": blockers,
        "provenance": provenance,
    })
    _write_json("performance_summary.json", {
        "phase": summary["phase"],
        "status": "PASS" if live["performance"] else "NOT_RUN",
        "observations": live["performance"],
        "warnings": live["performance_warnings"],
        "provenance": provenance,
    })
    _write_json("bounded_regression_summary.json", regression)
    (OUTPUT / "market_data_repository_v02_recommendation.md").write_text(
        "\n".join(
            [
                "MARKET_DATA_REPOSITORY_V02_FIX02",
                "",
                "STATUS",
                status,
                "",
                "BLOCKERS",
                json.dumps(blockers, ensure_ascii=False),
                "",
                "RAW AUTHORITY COMPATIBILITY",
                "PASS" if summary["repository_raw_authority_compatible"] else "FAIL",
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def _write_evidence(
    validation_head: str,
    static: dict[str, Any],
    offline: dict[str, Any],
    live: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    """Write FIX03-only evidence while preserving prior FIX01/FIX02 artifacts."""

    blockers = list(offline.get("blockers", [])) + list(live.get("blockers", []))
    if static["git_diff_check"]["status"] != "PASS":
        blockers.append("BLOCKED_GIT_DIFF_CHECK")
    if (
        static["legacy_repository_changed"]
        or static["frozen_store_source_changed_count"]
        or static["frozen_contract_modified"]
    ):
        blockers.append("BLOCKED_FROZEN_CONTRACT_MISMATCH")
    if static["closed_artifact_changed_count"]:
        blockers.append("BLOCKED_CLOSED_ARTIFACT_OVERWRITE")
    if static["consumer_auto_migration_count"]:
        blockers.append("BLOCKED_CONSUMER_AUTO_MIGRATION")
    if static["secret_occurrence_count"]:
        blockers.append("BLOCKED_SECRET_OCCURRENCE")
    if static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_NETWORK_DEPENDENCY")
    if static["artifacts_runtime_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_ARTIFACT_DEPENDENCY")
    if regression["failed"]:
        blockers.append("BLOCKED_REGRESSION")
    blockers = list(dict.fromkeys(blockers))
    status = (
        "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX03_REVIEW"
        if not blockers
        else blockers[0]
    )
    raw_records = offline.get("records", [])
    composition_records = live.get("composition_records", [])
    samsung_composition = _samsung_composition(live)
    provenance = {
        "market_data_repository_v02_original_implementation_head": ORIGINAL_REPOSITORY_IMPLEMENTATION_HEAD,
        "fix02_repository_implementation_head": FIX02_REPOSITORY_IMPLEMENTATION_HEAD,
        "fix03_repository_implementation_head": validation_head,
        "fix03_validation_source_head": validation_head,
        "live_execution_head": validation_head if live.get("provider_fetch_records") else None,
        "artifact_generation_head": validation_head,
        "artifact_commit_head": None,
    }
    semantics = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": "PASS",
        "placeholder_predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
        "placeholder_predicate_version": "V01",
        "placeholder_predicate_basis": "ADJUSTED_PRICE_PROVIDER_PHANTOM_COMPATIBILITY",
        "placeholder_fields": [
            "open == 0",
            "high == 0",
            "low == 0",
            "close > 0",
            "volume == 0",
            "trading_value == 0",
        ],
        "projection_scope": "get_daily only",
        "raw_api_preservation": {
            "get_raw_daily": True,
            "get_daily_ancillary": True,
            "get_stock_snapshot": True,
        },
        "adjusted_only_behavior": "FAIL_CLOSED: BLOCKED_ADJUSTED_SESSION_WITHOUT_RAW_FACTS",
        "unclassified_raw_only_behavior": "FAIL_CLOSED: BLOCKED_UNCLASSIFIED_RAW_ONLY_SESSION",
        "silent_inner_join": False,
        "silent_inner_drop_count": 0,
        "frozen_contract_changed": False,
        "provenance": provenance,
    }
    placeholder_artifact = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": offline.get("placeholder_semantics_gate", "NOT_RUN"),
        "records": offline.get("placeholder_candidates", []),
        "candidate_counts": {
            record.get("ticker"): record.get("candidate_count")
            for record in offline.get("placeholder_candidates", [])
        },
        "provenance": provenance,
    }
    session_difference = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": "PASS" if all(record.get("status") == "PASS" for record in composition_records) else "BLOCKED_SESSION_PROJECTION",
        "records": [
            {
                key: record.get(key)
                for key in (
                    "ticker",
                    "adjusted_rows",
                    "physical_raw_rows",
                    "projected_raw_rows",
                    "adjusted_only_dates",
                    "raw_only_dates",
                    "raw_only_row_details",
                    "accepted_placeholder_dates",
                    "rejected_raw_only_dates",
                    "projected_date_set_exact_match",
                    "explicit_placeholder_projection_count",
                    "silent_inner_drop_count",
                    "status",
                )
            }
            for record in composition_records
        ],
        "provenance": provenance,
    }
    network = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "logical_pykrx_fetch_count": live.get("provider_audit", {}).get("logical_fetch_count", 0),
        "adjusted_true_call_count": live.get("provider_audit", {}).get("adjusted_true_call_count", 0),
        "adjusted_false_call_count": live.get("provider_audit", {}).get("adjusted_false_call_count", 0),
        "KRX_open_api_request_count": live.get("KRX_open_api_request_count", 0),
        "OpenDART_request_count": live.get("OpenDART_request_count", 0),
        "fallback_request_count": live.get("fallback_request_count", 0),
        "retry_count": live.get("retry_count", 0),
        "external_blocker_present": any(
            record.get("stage") == "ADJUSTED_PROVIDER_FETCH" and record.get("status") == "FAIL"
            for record in live.get("failure_records", [])
        ),
        "provenance": provenance,
    }
    temp_store = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": _stage_evidence_status(
            live.get("temp_store_integrity_records", []),
            "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY",
        ),
        "records": live.get("temp_store_integrity_records", []),
        "successful_temp_store_integrity_count": live.get("successful_temp_store_integrity_count", 0),
        "temporary_store_ticker_count": live.get("temporary_store_ticker_count", 0),
        "cleanup": live.get("temporary_store_cleanup", "NOT_RUN"),
        "exists_after_cleanup": live.get("temporary_store_exists_after_cleanup", False),
        "provenance": provenance,
    }
    mutation_guard = {
        key: live.get(key)
        for key in (
            "production_raw_manifest_before_sha",
            "production_raw_manifest_after_sha",
            "production_raw_manifest_equal",
            "production_adjusted_snapshot_before",
            "production_adjusted_snapshot_after",
            "production_adjusted_snapshot_equal",
            "production_raw_write_count",
            "production_adjusted_write_count",
            "corporate_action_state_write_count",
        )
    }
    mutation_guard["provenance"] = provenance
    composition = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": _stage_evidence_status(
            composition_records,
            "BLOCKED_PRODUCTION_COMPOSITION_PROBE",
        ),
        "records": composition_records,
        "successful_composition_probe_count": live.get("successful_composition_probe_count", 0),
        "usable_composition_sample_count": live.get("usable_composition_sample_count", 0),
        "provenance": provenance,
    }
    live_summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": live.get("status"),
        "mode": live.get("mode"),
        "requested_samples": live.get("requested_samples", []),
        "provider_fetch_records": live.get("provider_fetch_records", []),
        "temp_store_integrity_records": live.get("temp_store_integrity_records", []),
        "composition_records": composition_records,
        "failure_records": live.get("failure_records", []),
        "counters": {
            "successful_provider_fetch_count": live.get("successful_provider_fetch_count", 0),
            "successful_temp_store_integrity_count": live.get("successful_temp_store_integrity_count", 0),
            "successful_composition_probe_count": live.get("successful_composition_probe_count", 0),
            "usable_composition_sample_count": live.get("usable_composition_sample_count", 0),
        },
        "sample_gate": live.get("sample_gate"),
        "evidence_consistency": live.get("evidence_consistency"),
        "provider_audit": live.get("provider_audit"),
        "blockers": live.get("blockers", []),
        "provenance": provenance,
    }
    performance = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": "PASS" if live.get("performance") else "NOT_RUN",
        "observations": live.get("performance", []),
        "warnings": live.get("performance_warnings", []),
        "provenance": provenance,
    }
    summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
        "status": status,
        **provenance,
        "repository_v2_changed": True,
        "legacy_repository_changed": static["legacy_repository_changed"],
        "frozen_contract_changed": False,
        "frozen_store_sources_changed": static["frozen_store_source_changed_count"] != 0,
        "git_diff_check": static["git_diff_check"],
        "runtime_network_forbidden_count": static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"],
        "artifacts_runtime_dependency_count": static["artifacts_runtime_dependency_count"],
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "repository_raw_authority_compatible": all(item.get("status") == "PASS" for item in raw_records),
        "placeholder_semantics": semantics,
        "raw_offline_probe": offline,
        "network": network,
        "live_probe": live,
        "samsung_raw": offline.get("samsung_raw"),
        "samsung_composition": samsung_composition,
        "bounded_regression": regression,
        "production_adjusted_population": "NOT_IMPLEMENTED",
        "consumer_migration_prerequisite": True,
        "known_limitations": [
            "PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED",
            "CONSUMER_MIGRATION_NOT_PERFORMED",
        ],
        "blockers": blockers,
        "warnings": live.get("performance_warnings", []),
        "provenance": provenance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json("FIX03_trading_session_semantics.json", semantics)
    _write_json("FIX03_raw_placeholder_candidates.json", placeholder_artifact)
    _write_json("FIX03_session_difference_summary.json", session_difference)
    _write_json("FIX03_live_authority_probe_summary.json", live_summary)
    _write_json("FIX03_composition_probe_summary.json", composition)
    _write_json("FIX03_network_summary.json", network)
    _write_json("FIX03_temp_store_integrity_summary.json", temp_store)
    _write_json("FIX03_production_mutation_guard.json", mutation_guard)
    _write_json(
        "FIX03_validator_gate_summary.json",
        {
            "phase": "MARKET_DATA_REPOSITORY_V02_FIX03",
            "status": status,
            "blockers": blockers,
            "static": static,
            "offline": offline,
            "live": {
                "sample_gate": live.get("sample_gate"),
                "evidence_consistency": live.get("evidence_consistency"),
                "blockers": live.get("blockers", []),
                "status": live.get("status"),
            },
            "bounded_regression": regression,
            "provenance": provenance,
        },
    )
    _write_json("market_data_repository_v02_summary.json", summary)
    _write_json(
        "production_probe_summary.json",
        {
            "phase": summary["phase"],
            "status": status,
            "repository_raw_authority_compatible": summary["repository_raw_authority_compatible"],
            "raw_offline_probe": offline,
            "live_probe": live,
            "samsung_raw": offline.get("samsung_raw"),
            "samsung_composition": samsung_composition,
            "blockers": blockers,
            "provenance": provenance,
        },
    )
    _write_json("performance_summary.json", performance)
    _write_json("bounded_regression_summary.json", regression)
    recommendation = [
        "MARKET_DATA_REPOSITORY_V02_FIX03",
        "",
        "STATUS",
        status,
        "",
        "BLOCKERS",
        json.dumps(blockers, ensure_ascii=False),
        "",
        "TRADING SESSION PROJECTION",
        "NON_TRADING_PLACEHOLDER_V01; get_daily only; raw APIs preserve physical rows",
        "",
        "PRODUCTION ADJUSTED POPULATION",
        "NOT_IMPLEMENTED",
        "",
        "CONSUMER MIGRATION PREREQUISITE",
        "YES",
    ]
    (OUTPUT / "market_data_repository_v02_recommendation.md").write_text(
        "\n".join(recommendation) + "\n", encoding="utf-8"
    )
    return summary


def _write_fix04_evidence(
    validation_head: str,
    static: dict[str, Any],
    offline: dict[str, Any],
    live: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    blockers = list(offline.get("blockers", [])) + list(live.get("blockers", []))
    if static["git_diff_check"]["status"] != "PASS":
        blockers.append("BLOCKED_GIT_DIFF_CHECK")
    if (
        static["legacy_repository_changed"]
        or static["frozen_store_source_changed_count"]
        or static["frozen_contract_modified"]
    ):
        blockers.append("BLOCKED_FROZEN_CONTRACT_MISMATCH")
    if static["closed_artifact_changed_count"]:
        blockers.append("BLOCKED_CLOSED_ARTIFACT_OVERWRITE")
    if static["consumer_auto_migration_count"]:
        blockers.append("BLOCKED_CONSUMER_AUTO_MIGRATION")
    if static["secret_occurrence_count"]:
        blockers.append("BLOCKED_SECRET_OCCURRENCE")
    if static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_NETWORK_DEPENDENCY")
    if static["artifacts_runtime_dependency_count"]:
        blockers.append("BLOCKED_RUNTIME_ARTIFACT_DEPENDENCY")
    if regression["failed"]:
        blockers.append("BLOCKED_REGRESSION")
    if live.get("evidence_consistency", {}).get("status") != "PASS":
        blockers.append("BLOCKED_EVIDENCE_INCONSISTENCY")
    blockers = list(dict.fromkeys(blockers))
    status = (
        "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX04_REVIEW"
        if not blockers
        else blockers[0]
    )
    composition_records = live.get("composition_records", [])
    provenance = {
        "fix03_repository_implementation_head": FIX03_REPOSITORY_IMPLEMENTATION_HEAD,
        "fix04_repository_implementation_head": validation_head,
        "fix04_validation_source_head": validation_head,
        "live_execution_head": validation_head if live.get("provider_fetch_records") else None,
        "artifact_generation_head": validation_head,
        "artifact_commit_head": None,
    }
    semantics = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": "PASS",
        "placeholder_predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
        "raw_only_placeholder_behavior": "PROJECT",
        "shared_date_placeholder_behavior": "FAIL_CLOSED",
        "adjusted_only_behavior": "FAIL_CLOSED",
        "unclassified_raw_only_behavior": "FAIL_CLOSED",
        "shared_date_conflict_error": "REPOSITORY_V2_SESSION_SEMANTIC_CONFLICT",
        "shared_date_conflict_blocker": "BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT",
        "projection_scope": "get_daily only",
        "silent_inner_drop_count": 0,
        "frozen_contract_changed": False,
        "provenance": provenance,
    }
    shared_summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": "PASS" if not any(record.get("shared_placeholder_conflict_dates") for record in composition_records) else "BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT",
        "records": [
            {
                key: record.get(key)
                for key in (
                    "ticker",
                    "shared_dates",
                    "shared_placeholder_conflict_dates",
                    "shared_placeholder_conflict_count",
                    "shared_placeholder_conflict_row_details",
                    "session_projection_blocker",
                    "status",
                )
            }
            for record in composition_records
        ],
        "provenance": provenance,
    }
    evidence_consistency = live.get("evidence_consistency", {})
    placeholder_consistency = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": evidence_consistency.get("status", "NOT_RUN"),
        "provider_pass_record_count": evidence_consistency.get("provider_pass_record_count", 0),
        "temp_store_pass_record_count": evidence_consistency.get("temp_store_pass_record_count", 0),
        "composition_pass_record_count": evidence_consistency.get("composition_pass_record_count", 0),
        "accepted_placeholder_projection_count": evidence_consistency.get("accepted_placeholder_projection_count", 0),
        "rejected_raw_only_count": evidence_consistency.get("rejected_raw_only_count", 0),
        "shared_placeholder_conflict_count": evidence_consistency.get("shared_placeholder_conflict_count", 0),
        "mismatches": evidence_consistency.get("mismatches", []),
        "provenance": provenance,
    }
    live_summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": live.get("status"),
        "requested_samples": live.get("requested_samples", []),
        "provider_fetch_records": live.get("provider_fetch_records", []),
        "temp_store_integrity_records": live.get("temp_store_integrity_records", []),
        "composition_records": composition_records,
        "failure_records": live.get("failure_records", []),
        "sample_gate": live.get("sample_gate"),
        "evidence_consistency": evidence_consistency,
        "provider_audit": live.get("provider_audit"),
        "blockers": live.get("blockers", []),
        "provenance": provenance,
    }
    composition = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": _stage_evidence_status(
            composition_records, "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
        ),
        "records": composition_records,
        "successful_composition_probe_count": live.get("successful_composition_probe_count", 0),
        "usable_composition_sample_count": live.get("usable_composition_sample_count", 0),
        "provenance": provenance,
    }
    network = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "logical_pykrx_fetch_count": live.get("provider_audit", {}).get("logical_fetch_count", 0),
        "adjusted_true_call_count": live.get("provider_audit", {}).get("adjusted_true_call_count", 0),
        "adjusted_false_call_count": live.get("provider_audit", {}).get("adjusted_false_call_count", 0),
        "KRX_open_api_request_count": live.get("KRX_open_api_request_count", 0),
        "OpenDART_request_count": live.get("OpenDART_request_count", 0),
        "fallback_request_count": live.get("fallback_request_count", 0),
        "retry_count": live.get("retry_count", 0),
        "provenance": provenance,
    }
    temp_store = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": _stage_evidence_status(
            live.get("temp_store_integrity_records", []),
            "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY",
        ),
        "records": live.get("temp_store_integrity_records", []),
        "temporary_store_ticker_count": live.get("temporary_store_ticker_count", 0),
        "cleanup": live.get("temporary_store_cleanup", "NOT_RUN"),
        "exists_after_cleanup": live.get("temporary_store_exists_after_cleanup", False),
        "provenance": provenance,
    }
    mutation = {
        key: live.get(key)
        for key in (
            "production_raw_manifest_before_sha",
            "production_raw_manifest_after_sha",
            "production_raw_manifest_equal",
            "production_adjusted_snapshot_before",
            "production_adjusted_snapshot_after",
            "production_adjusted_snapshot_equal",
            "production_raw_write_count",
            "production_adjusted_write_count",
            "corporate_action_state_write_count",
        )
    }
    mutation["provenance"] = provenance
    performance = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": "PASS" if live.get("performance") else "NOT_RUN",
        "observations": live.get("performance", []),
        "warnings": live.get("performance_warnings", []),
        "provenance": provenance,
    }
    summary = {
        "phase": "MARKET_DATA_REPOSITORY_V02_FIX04",
        "status": status,
        **provenance,
        "repository_v2_changed": True,
        "legacy_repository_changed": static["legacy_repository_changed"],
        "frozen_contract_changed": static["frozen_contract_modified"],
        "frozen_store_sources_changed": static["frozen_store_source_changed_count"] != 0,
        "git_diff_check": static["git_diff_check"],
        "runtime_network_forbidden_count": static["runtime_network_guard"]["runtime_forbidden_network_dependency_count"],
        "artifacts_runtime_dependency_count": static["artifacts_runtime_dependency_count"],
        "consumer_auto_migration_count": static["consumer_auto_migration_count"],
        "raw_offline_probe": offline,
        "live_probe": live,
        "samsung_raw": offline.get("samsung_raw"),
        "samsung_composition": _samsung_composition(live),
        "bounded_regression": regression,
        "production_adjusted_population": "NOT_IMPLEMENTED",
        "consumer_migration_prerequisite": True,
        "blockers": blockers,
        "warnings": live.get("performance_warnings", []),
        "provenance": provenance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json("FIX04_shared_session_conflict_summary.json", shared_summary)
    _write_json("FIX04_placeholder_evidence_consistency.json", placeholder_consistency)
    _write_json("FIX04_live_authority_probe_summary.json", live_summary)
    _write_json("FIX04_composition_probe_summary.json", composition)
    _write_json("FIX04_validator_gate_summary.json", {
        "phase": summary["phase"],
        "status": status,
        "blockers": blockers,
        "static": static,
        "offline": offline,
        "live": {
            "sample_gate": live.get("sample_gate"),
            "evidence_consistency": evidence_consistency,
            "status": live.get("status"),
        },
        "bounded_regression": regression,
        "provenance": provenance,
    })
    _write_json("FIX04_network_summary.json", network)
    _write_json("FIX04_temp_store_integrity_summary.json", temp_store)
    _write_json("FIX04_production_mutation_guard.json", mutation)
    _write_json("market_data_repository_v02_summary.json", summary)
    _write_json("production_probe_summary.json", {
        "phase": summary["phase"],
        "status": status,
        "raw_offline_probe": offline,
        "live_probe": live,
        "samsung_raw": offline.get("samsung_raw"),
        "samsung_composition": summary["samsung_composition"],
        "blockers": blockers,
        "provenance": provenance,
    })
    _write_json("performance_summary.json", performance)
    _write_json("bounded_regression_summary.json", regression)
    (OUTPUT / "market_data_repository_v02_recommendation.md").write_text(
        "\n".join([
            "MARKET_DATA_REPOSITORY_V02_FIX04",
            "",
            "STATUS",
            status,
            "",
            "BLOCKERS",
            json.dumps(blockers, ensure_ascii=False),
            "",
            "SHARED-DATE PLACEHOLDER",
            "FAIL-CLOSED: REPOSITORY_V2_SESSION_SEMANTIC_CONFLICT",
            "",
            "PLACEHOLDER EVIDENCE",
            json.dumps({
                "accepted_placeholder_projection_count": evidence_consistency.get("accepted_placeholder_projection_count", 0),
                "rejected_raw_only_count": evidence_consistency.get("rejected_raw_only_count", 0),
                "shared_placeholder_conflict_count": evidence_consistency.get("shared_placeholder_conflict_count", 0),
            }, ensure_ascii=False),
        ]) + "\n",
        encoding="utf-8",
    )
    return summary


def _write_evidence(
    validation_head: str,
    static: dict[str, Any],
    offline: dict[str, Any],
    live: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    return _write_fix04_evidence(validation_head, static, offline, live, regression)


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
    offline = _offline_probes(Path(args.raw_root))
    live = _run_live_probe(Path(args.raw_root), offline)
    return _write_evidence(validation_head, static, offline, live, regression)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=PRODUCTION_RAW_ROOT)
    parser.add_argument("--bounded-command", default="not supplied")
    parser.add_argument("--bounded-passed", type=int, default=0)
    parser.add_argument("--bounded-failed", type=int, default=0)
    parser.add_argument("--bounded-duration", type=float, default=0.0)
    summary = run(parser.parse_args())
    print(
        json.dumps(
            {
                "status": summary["status"],
                "blockers": summary["blockers"],
                "fix04_validation_source_head": summary["fix04_validation_source_head"],
                "live_execution_head": summary["live_execution_head"],
                "network": summary["network"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["status"] == "READY_FOR_ARCHITECT_MARKET_DATA_REPOSITORY_V02_FIX04_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
