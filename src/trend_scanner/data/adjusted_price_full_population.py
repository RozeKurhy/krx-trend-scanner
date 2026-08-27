"""Adjusted Price Store Full Population Pipeline (ADJUSTED_PRICE_STORE_FULL_POPULATION_V01_FIX01).

Acquires, validates and persists adjusted daily OHLC for all 3,162 frozen Historical Common Population
identities using PyKRX adjusted=True as the authoritative source.

Invariants:
1. Frozen Authority: strictly validates 3,162 population count and SHA256.
2. Checkpoint Authority Fail-Closed: raises CHECKPOINT_AUTHORITY_MISMATCH on tampered population or cutoff.
3. Independent Expected Coverage: determines expected tradable dates without PyKRX feedback.
4. Exact Resume Accounting: reused COMPLETE tickers have physical attempts = 0 and reused_without_network = True.
5. Systemic Circuit Breakers: halts safely on consecutive errors or consecutive empties.
6. Atomic Storage & Post-Write Verify: verifies schema, row count, date min/max, and date set match.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    CANONICAL_CALENDAR_CUTOFF,
    DEFAULT_CANONICAL_CALENDAR_PATH,
    DEFAULT_HISTORICAL_CALENDAR_PATH,
    DEFAULT_PIT_PATH,
    DEFAULT_STOCKS_RAW_DIR,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    EXPECTED_CALENDAR_ROW_COUNT,
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
    load_historical_suspension_authority,
    resolve_expected_coverage,
)
from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    AdjustedPriceDataProvider,
    normalize_ticker,
    validate_adjusted_ohlc,
)
from trend_scanner.data.adjusted_price_store import (
    AdjustedPriceStore,
    DEFAULT_ADJUSTED_PRICE_STORE_DIR,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)

DEFAULT_FULL_POPULATION_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population/v01"
)
CHECKPOINT_SCHEMA_VERSION = "full_population_checkpoint_v01"


class AcquisitionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    ERROR = "ERROR"
    INSUFFICIENT_AUTHORITY = "INSUFFICIENT_AUTHORITY"


@dataclass
class TickerAcquisitionRecord:
    ticker: str
    isu_cd: str
    market: str
    first_common_date: str
    last_common_date: str
    numeric_or_alpha: str
    currently_common: bool
    historical_only: bool
    requested_start: str
    requested_end: str
    authority_source: str
    authority_quality: str
    expected_observation_count: int
    actual_source_row_count: int
    matched_expected_count: int
    missing_expected_count: int
    unexpected_source_date_count: int
    first_actual_date: str | None
    last_actual_date: str | None
    source_status: str
    coverage_status: str
    acquisition_status: str
    attempt_count: int
    retry_count: int
    reused_without_network: bool
    stored_row_count: int
    stored_start: str | None
    stored_end: str | None
    duplicate_count: int
    invalid_ohlc_count: int
    future_row_count: int
    post_write_verified: bool
    error_type: str | None
    error_message_sanitized: str | None
    updated_at: str


@dataclass
class FullPopulationCheckpoint:
    schema: str
    execution_id: str
    started_at: str
    updated_at: str
    population_count: int
    population_sha256: str
    calendar_cutoff_date: str
    completed_tickers: dict[str, dict[str, Any]]
    in_progress_tickers: dict[str, dict[str, Any]]


def sanitize_error_message(msg: str | None) -> str | None:
    if not msg:
        return None
    return re.sub(r"(token|auth|pw|password|key|secret)=\S+", r"\1=***", str(msg), flags=re.IGNORECASE)


def verify_stored_ticker_integrity(
    store: AdjustedPriceStore,
    ticker: str,
    expected_row_count: int,
    expected_dates: Sequence[str],
    expected_requested_start: str | None = None,
    expected_requested_end: str | None = None,
) -> tuple[bool, str | None]:
    """Verify that stored parquet + metadata sidecar matches exact expected actual rows, dates, and metadata bounds."""
    try:
        if not store.exists(ticker):
            return False, "STORE_FILES_MISSING"

        if expected_requested_start is not None or expected_requested_end is not None:
            meta = store.load_metadata(ticker)
            if not meta:
                return False, "STORE_METADATA_MISSING"
            stored_req_start = meta.get("requested_start")
            stored_req_end = meta.get("requested_end")
            if expected_requested_start is not None and stored_req_start != expected_requested_start:
                return False, f"METADATA_START_BOUND_MISMATCH: stored={stored_req_start}, expected={expected_requested_start}"
            if expected_requested_end is not None and stored_req_end != expected_requested_end:
                return False, f"METADATA_END_BOUND_MISMATCH: stored={stored_req_end}, expected={expected_requested_end}"

        frame = store.load_daily(ticker)
        if len(frame) != expected_row_count:
            return False, f"ROW_COUNT_MISMATCH: stored={len(frame)}, expected={expected_row_count}"

        stored_dates = [d.strftime("%Y-%m-%d") for d in frame.index]
        if stored_dates != list(expected_dates):
            return False, "STORED_DATES_SET_MISMATCH"

        return True, None
    except Exception as exc:
        return False, f"STORE_VERIFY_ERROR: {sanitize_error_message(str(exc))}"


class FullPopulationRunner:
    """Orchestrates bounded resumable acquisition and verification across 3,162 identities."""

    def __init__(
        self,
        population_path: Path = Path(DEFAULT_POPULATION_ARTIFACT_PATH),
        store_dir: Path = DEFAULT_ADJUSTED_PRICE_STORE_DIR,
        artifact_dir: Path = DEFAULT_FULL_POPULATION_DIR,
        provider: AdjustedPriceDataProvider | None = None,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.5,
        execution_id: str | None = None,
    ) -> None:
        self.population_path = population_path
        self.store = AdjustedPriceStore(store_dir)
        self.artifact_dir = Path(artifact_dir)
        self.provider = provider
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.execution_id = execution_id or f"ADJUSTED_PRICE_STORE_FULL_POPULATION_V01_{int(time.time())}"

        self.checkpoint_path = self.artifact_dir / "full_population_checkpoint.json"
        self.manifest_path = self.artifact_dir / "full_population_manifest.json"
        self.results_csv_path = self.artifact_dir / "full_population_results.csv"
        self.summary_path = self.artifact_dir / "full_population_summary.json"
        self.closure_manifest_path = self.artifact_dir / "full_population_closure_manifest.json"
        self.resume_audit_path = self.artifact_dir / "full_population_resume_audit.json"
        self.failures_csv_path = self.artifact_dir / "full_population_failures.csv"

    def load_population(self) -> list[dict[str, Any]]:
        records = load_historical_common_population(self.population_path)
        calc_sha = population_manifest_sha256(records)
        if len(records) != EXPECTED_POPULATION_COUNT or calc_sha != EXPECTED_POPULATION_SHA256:
            raise RuntimeError(
                f"FROZEN_POPULATION_MUTATION: count={len(records)} (expected {EXPECTED_POPULATION_COUNT}), "
                f"sha256={calc_sha} (expected {EXPECTED_POPULATION_SHA256})"
            )
        return sorted(records, key=lambda x: x["ticker"])

    def load_or_create_checkpoint(self, population_records: list[dict[str, Any]]) -> FullPopulationCheckpoint:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()

        if self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"CHECKPOINT_CORRUPTION: Failed to parse checkpoint JSON: {exc}")

            if data.get("schema") != CHECKPOINT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"CHECKPOINT_SCHEMA_MISMATCH: Expected schema '{CHECKPOINT_SCHEMA_VERSION}', "
                    f"got '{data.get('schema')}'"
                )

            if (
                data.get("population_count") != EXPECTED_POPULATION_COUNT
                or data.get("population_sha256") != EXPECTED_POPULATION_SHA256
            ):
                raise RuntimeError(
                    f"CHECKPOINT_AUTHORITY_MISMATCH: Checkpoint population metadata "
                    f"(count={data.get('population_count')}, sha256={data.get('population_sha256')}) "
                    f"does not match frozen authority (count={EXPECTED_POPULATION_COUNT}, sha256={EXPECTED_POPULATION_SHA256})"
                )

            if data.get("calendar_cutoff_date") != CANONICAL_CALENDAR_CUTOFF:
                raise RuntimeError(
                    f"CHECKPOINT_AUTHORITY_MISMATCH: Checkpoint cutoff '{data.get('calendar_cutoff_date')}' "
                    f"does not match canonical cutoff '{CANONICAL_CALENDAR_CUTOFF}'"
                )

            return FullPopulationCheckpoint(
                schema=data.get("schema", CHECKPOINT_SCHEMA_VERSION),
                execution_id=data.get("execution_id", self.execution_id),
                started_at=data.get("started_at", now_iso),
                updated_at=now_iso,
                population_count=data.get("population_count", EXPECTED_POPULATION_COUNT),
                population_sha256=data.get("population_sha256", EXPECTED_POPULATION_SHA256),
                calendar_cutoff_date=data.get("calendar_cutoff_date", CANONICAL_CALENDAR_CUTOFF),
                completed_tickers=data.get("completed_tickers", {}),
                in_progress_tickers=data.get("in_progress_tickers", {}),
            )

        return FullPopulationCheckpoint(
            schema=CHECKPOINT_SCHEMA_VERSION,
            execution_id=self.execution_id,
            started_at=now_iso,
            updated_at=now_iso,
            population_count=len(population_records),
            population_sha256=EXPECTED_POPULATION_SHA256,
            calendar_cutoff_date=CANONICAL_CALENDAR_CUTOFF,
            completed_tickers={},
            in_progress_tickers={},
        )

    def save_checkpoint(self, checkpoint: FullPopulationCheckpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        temp_p = self.checkpoint_path.with_suffix(".json.tmp")
        payload = asdict(checkpoint)
        temp_p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp_p, self.checkpoint_path)

    def dry_run_classify(self) -> dict[str, Any]:
        """Strictly classify all 3,162 identities without performing any network calls."""
        population = self.load_population()
        checkpoint = self.load_or_create_checkpoint(population)

        already_complete: list[str] = []
        needs_fetch: list[str] = []
        existing_partial: list[str] = []
        existing_empty: list[str] = []
        existing_error: list[str] = []
        authority_blocked: list[str] = []

        for rec in population:
            t = rec["ticker"]
            req_start = rec["first_common_date"]
            req_end = min(rec["last_common_date"], CANONICAL_CALENDAR_CUTOFF)

            # 1. If recorded as COMPLETE in checkpoint, verify stored physical file + metadata bounds
            if t in checkpoint.completed_tickers:
                info = checkpoint.completed_tickers[t]
                is_valid, _ = verify_stored_ticker_integrity(
                    self.store,
                    t,
                    info.get("stored_row_count", 0),
                    info.get("actual_dates", []),
                    expected_requested_start=req_start,
                    expected_requested_end=req_end,
                )
                if is_valid:
                    already_complete.append(t)
                    continue

            # 2. Strict store check (without checkpoint, must strictly verify against independent expected resolution + metadata bounds)
            if self.store.exists(t):
                try:
                    df = self.store.load_daily(t)
                    meta = self.store.load_metadata(t)
                    resolution = resolve_expected_coverage(t, req_start, req_end)
                    if (
                        resolution.authority_status == AuthorityStatus.VALID.value
                        and resolution.expected_tradable_count > 0
                        and len(df) == resolution.expected_tradable_count
                        and list(df.index.strftime("%Y-%m-%d")) == list(resolution.expected_tradable_dates)
                        and meta is not None
                        and meta.get("requested_start") == req_start
                        and meta.get("requested_end") == req_end
                    ):
                        already_complete.append(t)
                        continue
                except Exception:
                    pass

            # 3. Check in-progress status from checkpoint
            if t in checkpoint.in_progress_tickers:
                st = checkpoint.in_progress_tickers[t].get("acquisition_status")
                if st == AcquisitionStatus.PARTIAL.value:
                    existing_partial.append(t)
                elif st == AcquisitionStatus.EMPTY.value:
                    existing_empty.append(t)
                elif st == AcquisitionStatus.ERROR.value:
                    existing_error.append(t)
                elif st == AcquisitionStatus.INSUFFICIENT_AUTHORITY.value:
                    authority_blocked.append(t)
                else:
                    needs_fetch.append(t)
            else:
                needs_fetch.append(t)

        return {
            "population_count": len(population),
            "already_complete_count": len(already_complete),
            "needs_fetch_count": len(needs_fetch),
            "existing_partial_count": len(existing_partial),
            "existing_empty_count": len(existing_empty),
            "existing_error_count": len(existing_error),
            "authority_blocked_count": len(authority_blocked),
            "reconciliation_sum": (
                len(already_complete)
                + len(needs_fetch)
                + len(existing_partial)
                + len(existing_empty)
                + len(existing_error)
                + len(authority_blocked)
            ),
        }

    def process_single_ticker(
        self,
        rec: dict[str, Any],
        provider: AdjustedPriceDataProvider | None = None,
        cached_info: dict[str, Any] | None = None,
    ) -> TickerAcquisitionRecord:
        """Process acquisition, coverage resolution, storage and verification for a single ticker."""
        ticker = rec["ticker"]
        req_start = rec["first_common_date"]
        req_end = min(rec["last_common_date"], CANONICAL_CALENDAR_CUTOFF)

        # 1. Resolve strictly independent expected coverage
        resolution = resolve_expected_coverage(ticker, req_start, req_end)

        attempt_count = 0
        retry_count = 0
        reused_without_network = False
        last_error: Exception | None = None
        frame: pd.DataFrame = pd.DataFrame()
        actual_dates: list[str] = []

        if cached_info is not None and "actual_dates" in cached_info:
            actual_dates = cached_info["actual_dates"]
            attempt_count = 0  # Reused from cache without network call
            retry_count = 0
            reused_without_network = True
        else:
            if provider is None:
                provider = self.provider or AdjustedPriceDataProvider()

            for attempt in range(1, self.max_retries + 2):
                attempt_count = attempt
                try:
                    frame = provider.load_daily(ticker, req_start, req_end)
                    actual_dates = [d.strftime("%Y-%m-%d") for d in frame.index]
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt <= self.max_retries:
                        retry_count += 1
                        time.sleep(self.retry_delay_seconds * attempt)

        now_iso = datetime.now(timezone.utc).isoformat()
        error_type = type(last_error).__name__ if last_error else None
        error_msg = sanitize_error_message(str(last_error)) if last_error else None

        row_count = len(actual_dates)
        duplicate_count = 0
        invalid_ohlc_count = 0
        future_row_count = 0
        first_actual = actual_dates[0] if actual_dates else None
        last_actual = actual_dates[-1] if actual_dates else None

        if not frame.empty:
            duplicate_count = int(frame.index.duplicated().sum())
            req_end_ts = pd.Timestamp(req_end)
            future_row_count = int((frame.index > req_end_ts).sum())
            relation_violations = (
                (frame["high"] < frame["low"])
                | (frame["high"] < frame["open"])
                | (frame["high"] < frame["close"])
                | (frame["low"] > frame["open"])
                | (frame["low"] > frame["close"])
                | (frame["open"] <= 0)
                | (frame["high"] <= 0)
                | (frame["low"] <= 0)
                | (frame["close"] <= 0)
                | frame[list(ADJUSTED_OHLC_COLUMNS)].isna().any(axis=1)
            )
            invalid_ohlc_count = int(relation_violations.sum())
        elif cached_info is not None:
            duplicate_count = len(actual_dates) - len(set(actual_dates))
            future_row_count = sum(1 for d in actual_dates if d > req_end)

        # 2. Coverage Evaluation
        exp_set = set(resolution.expected_tradable_dates)
        act_set = set(actual_dates)
        matched_set = exp_set.intersection(act_set)
        missing_set = exp_set - act_set
        unexpected_set = act_set - exp_set

        matched_count = len(matched_set)
        missing_count = len(missing_set)
        unexpected_count = len(unexpected_set)
        expected_count = resolution.expected_tradable_count

        if last_error is not None:
            source_status = "ERROR"
        elif row_count == 0:
            source_status = "EMPTY"
        elif invalid_ohlc_count > 0 or duplicate_count > 0 or future_row_count > 0:
            source_status = "SCHEMA_ANOMALY"
        else:
            source_status = "SUCCESS"

        if resolution.authority_status != AuthorityStatus.VALID.value:
            coverage_status = CoverageStatus.INSUFFICIENT_COVERAGE_AUTHORITY.value
        elif expected_count == 0 and row_count == 0:
            coverage_status = CoverageStatus.NO_EXPECTED_OBSERVATIONS.value
        elif expected_count == 0 and row_count > 0:
            coverage_status = CoverageStatus.UNEXPECTED_SOURCE_ONLY.value
        elif missing_count == 0 and unexpected_count == 0:
            coverage_status = CoverageStatus.FULL_EXPECTED_COVERAGE.value
        else:
            coverage_status = CoverageStatus.PARTIAL_EXPECTED_COVERAGE.value

        # 3. Store Write & Post-Write Verification
        post_write_verified = False
        stored_row_count = 0
        stored_start: str | None = None
        stored_end: str | None = None

        if (
            source_status == "SUCCESS"
            and not frame.empty
            and invalid_ohlc_count == 0
            and duplicate_count == 0
            and future_row_count == 0
        ):
            try:
                self.store.save_full(
                    ticker,
                    frame,
                    metadata_context={"requested_start": req_start, "requested_end": req_end},
                )
                verified, v_err = verify_stored_ticker_integrity(
                    self.store, ticker, row_count, actual_dates
                )
                post_write_verified = verified
                if verified:
                    stored_row_count = row_count
                    stored_start = first_actual
                    stored_end = last_actual
                else:
                    error_type = "POST_WRITE_VERIFY_FAILURE"
                    error_msg = v_err
            except Exception as exc:
                error_type = "STORE_WRITE_ERROR"
                error_msg = sanitize_error_message(str(exc))
        elif cached_info is not None and cached_info.get("post_write_verified"):
            verified, v_err = verify_stored_ticker_integrity(
                self.store, ticker, row_count, actual_dates
            )
            post_write_verified = verified
            if verified:
                stored_row_count = row_count
                stored_start = first_actual
                stored_end = last_actual

        # 4. Determine Final Acquisition Status
        if resolution.authority_status != AuthorityStatus.VALID.value:
            acq_status = AcquisitionStatus.INSUFFICIENT_AUTHORITY.value
        elif source_status == "ERROR":
            acq_status = AcquisitionStatus.ERROR.value
        elif source_status == "EMPTY":
            acq_status = AcquisitionStatus.EMPTY.value
        elif (
            coverage_status == CoverageStatus.FULL_EXPECTED_COVERAGE.value
            and expected_count > 0
            and post_write_verified
            and stored_row_count == row_count == expected_count
        ):
            acq_status = AcquisitionStatus.COMPLETE.value
        else:
            acq_status = AcquisitionStatus.PARTIAL.value

        return TickerAcquisitionRecord(
            ticker=ticker,
            isu_cd=",".join(rec["isu_cd"]),
            market=",".join(rec["market"]),
            first_common_date=rec["first_common_date"],
            last_common_date=rec["last_common_date"],
            numeric_or_alpha=rec["numeric_or_alpha"],
            currently_common=rec["currently_common"],
            historical_only=rec["historical_only"],
            requested_start=req_start,
            requested_end=req_end,
            authority_source=resolution.authority_source,
            authority_quality=resolution.authority_quality,
            expected_observation_count=expected_count,
            actual_source_row_count=row_count,
            matched_expected_count=matched_count,
            missing_expected_count=missing_count,
            unexpected_source_date_count=unexpected_count,
            first_actual_date=first_actual,
            last_actual_date=last_actual,
            source_status=source_status,
            coverage_status=coverage_status,
            acquisition_status=acq_status,
            attempt_count=attempt_count,
            retry_count=retry_count,
            reused_without_network=reused_without_network,
            stored_row_count=stored_row_count,
            stored_start=stored_start,
            stored_end=stored_end,
            duplicate_count=duplicate_count,
            invalid_ohlc_count=invalid_ohlc_count,
            future_row_count=future_row_count,
            post_write_verified=post_write_verified,
            error_type=error_type,
            error_message_sanitized=error_msg,
            updated_at=now_iso,
        )

    def run_acquisition(
        self,
        provider: AdjustedPriceDataProvider | None = None,
        dry_run: bool = False,
        circuit_breaker_error_threshold: int = 20,
        circuit_breaker_empty_threshold: int = 20,
        progress_callback: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Execute full population acquisition with resumability, rate throttling and circuit-breaker."""
        population = self.load_population()
        checkpoint = self.load_or_create_checkpoint(population)
        records: list[TickerAcquisitionRecord] = []

        total_population = len(population)
        consecutive_errors = 0
        consecutive_empties = 0

        # Preflight Classification
        preflight_summary = self.dry_run_classify()

        if dry_run:
            return {
                "execution_id": self.execution_id,
                "mode": "DRY_RUN",
                "preflight": preflight_summary,
                "status": "DRY_RUN_COMPLETED",
            }

        # Acquisition Loop
        start_time = time.time()
        for idx, rec in enumerate(population, start=1):
            t = rec["ticker"]

            # Resumability: if already complete and verified, reuse without network call
            if t in checkpoint.completed_tickers:
                info = checkpoint.completed_tickers[t]
                is_valid, _ = verify_stored_ticker_integrity(
                    self.store, t, info.get("stored_row_count", 0), info.get("actual_dates", [])
                )
                if is_valid:
                    rec_obj = self.process_single_ticker(rec, cached_info=info)
                    records.append(rec_obj)
                    consecutive_errors = 0
                    consecutive_empties = 0
                    if progress_callback:
                        progress_callback(idx, total_population, t, "COMPLETE (REUSED)")
                    continue

            # Query via provider with gentle rate-throttling to prevent KRX IP block
            rec_obj = self.process_single_ticker(rec, provider=provider)
            records.append(rec_obj)
            if not rec_obj.reused_without_network:
                time.sleep(0.25)  # Gentle delay between live PyKRX requests

            if rec_obj.acquisition_status == AcquisitionStatus.COMPLETE.value:
                consecutive_errors = 0
                consecutive_empties = 0
                actual_dates_list = (
                    self.store.load_daily(t).index.strftime("%Y-%m-%d").tolist()
                    if self.store.exists(t)
                    else []
                )
                checkpoint.completed_tickers[t] = {
                    "ticker": t,
                    "acquisition_status": rec_obj.acquisition_status,
                    "requested_start": rec_obj.requested_start,
                    "requested_end": rec_obj.requested_end,
                    "stored_row_count": rec_obj.stored_row_count,
                    "expected_count": rec_obj.expected_observation_count,
                    "actual_row_count": rec_obj.actual_source_row_count,
                    "first_actual_date": rec_obj.first_actual_date,
                    "last_actual_date": rec_obj.last_actual_date,
                    "post_write_verified": rec_obj.post_write_verified,
                    "actual_dates": actual_dates_list,
                    "source_execution_attempt_count": rec_obj.attempt_count,
                    "updated_at": rec_obj.updated_at,
                }
                if t in checkpoint.in_progress_tickers:
                    del checkpoint.in_progress_tickers[t]
            else:
                checkpoint.in_progress_tickers[t] = {
                    "ticker": t,
                    "acquisition_status": rec_obj.acquisition_status,
                    "source_status": rec_obj.source_status,
                    "coverage_status": rec_obj.coverage_status,
                    "missing_count": rec_obj.missing_expected_count,
                    "unexpected_count": rec_obj.unexpected_source_date_count,
                    "error_type": rec_obj.error_type,
                    "error_message": rec_obj.error_message_sanitized,
                    "updated_at": rec_obj.updated_at,
                }
                if rec_obj.acquisition_status == AcquisitionStatus.ERROR.value:
                    consecutive_errors += 1
                    consecutive_empties = 0
                elif rec_obj.acquisition_status == AcquisitionStatus.EMPTY.value:
                    consecutive_empties += 1
                    consecutive_errors = 0
                else:
                    consecutive_errors = 0
                    consecutive_empties = 0

            # Periodic checkpoint save every 10 tickers
            if idx % 10 == 0 or idx == total_population:
                self.save_checkpoint(checkpoint)

            if progress_callback:
                progress_callback(idx, total_population, t, rec_obj.acquisition_status)

            # Circuit breakers
            if consecutive_errors >= circuit_breaker_error_threshold:
                self.save_checkpoint(checkpoint)
                raise RuntimeError(
                    f"CIRCUIT_BREAKER_TRIGGERED: Aborted after {consecutive_errors} consecutive provider errors. "
                    f"Last error on ticker {t}: {rec_obj.error_type}: {rec_obj.error_message_sanitized}"
                )
            if consecutive_empties >= circuit_breaker_empty_threshold:
                self.save_checkpoint(checkpoint)
                raise RuntimeError(
                    f"CIRCUIT_BREAKER_TRIGGERED: Aborted after {consecutive_empties} consecutive empty responses. "
                    f"Last empty on ticker {t} ({rec['first_common_date']} ~ {rec['last_common_date']})"
                )

        # Final checkpoint save
        self.save_checkpoint(checkpoint)

        # Generate operational artifacts
        summary_payload = self.generate_operational_artifacts(records, preflight_summary, time.time() - start_time)

        return {
            "execution_id": self.execution_id,
            "mode": "ACQUISITION",
            "records": records,
            "summary": summary_payload,
        }

    def generate_operational_artifacts(
        self,
        records: Sequence[TickerAcquisitionRecord],
        preflight_summary: dict[str, Any],
        duration_seconds: float,
    ) -> dict[str, Any]:
        """Generate results CSV, manifest, summary JSON, closure manifest, and resume audit."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

        # 1. Save Results CSV
        results_df = pd.DataFrame([asdict(r) for r in records])
        results_csv_content = results_df.to_csv(index=False)
        self.results_csv_path.write_text(results_csv_content, encoding="utf-8")
        results_sha = hashlib.sha256(results_csv_content.encode("utf-8")).hexdigest()

        # 2. Compute Aggregate Metrics
        total_count = len(records)
        complete_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.COMPLETE.value)
        partial_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.PARTIAL.value)
        empty_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.EMPTY.value)
        error_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.ERROR.value)
        insufficient_auth_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.INSUFFICIENT_AUTHORITY.value)

        alpha_records = [r for r in records if r.numeric_or_alpha == "alphanumeric"]
        alpha_complete = sum(1 for r in alpha_records if r.acquisition_status == AcquisitionStatus.COMPLETE.value)

        current_common_records = [r for r in records if r.currently_common]
        current_complete = sum(1 for r in current_common_records if r.acquisition_status == AcquisitionStatus.COMPLETE.value)

        historical_records = [r for r in records if r.historical_only]
        historical_complete = sum(1 for r in historical_records if r.acquisition_status == AcquisitionStatus.COMPLETE.value)

        total_expected_rows = sum(r.expected_observation_count for r in records)
        total_actual_rows = sum(r.actual_source_row_count for r in records)
        total_stored_rows = sum(r.stored_row_count for r in records)

        total_missing = sum(r.missing_expected_count for r in records)
        total_unexpected = sum(r.unexpected_source_date_count for r in records)
        total_duplicates = sum(r.duplicate_count for r in records)
        total_invalid_ohlc = sum(r.invalid_ohlc_count for r in records)
        total_future_rows = sum(r.future_row_count for r in records)

        logical_queries = total_count
        new_live_queries = sum(1 for r in records if not r.reused_without_network)
        physical_attempts = sum(r.attempt_count for r in records)
        total_retries = sum(r.retry_count for r in records)
        reused_count = sum(1 for r in records if r.reused_without_network)

        failures = [r for r in records if r.acquisition_status != AcquisitionStatus.COMPLETE.value]
        if failures:
            failures_df = pd.DataFrame([asdict(r) for r in failures])
            self.failures_csv_path.write_text(failures_df.to_csv(index=False), encoding="utf-8")
        elif self.failures_csv_path.exists():
            self.failures_csv_path.unlink()

        # Verdict evaluation
        all_complete = (complete_count == total_count == EXPECTED_POPULATION_COUNT)
        quality_clean = (total_duplicates == 0 and total_invalid_ohlc == 0 and total_future_rows == 0)

        if all_complete and quality_clean:
            verdict = "ACCEPT"
            next_state = "READY_FOR_MARKET_DATA_REPOSITORY_V02_PARITY"
        else:
            verdict = "CHANGES_REQUESTED"
            # When pre-2014 data is unrecoverable within the frozen PyKRX authority:
            next_state = "NEEDS_ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW"

        now_iso = datetime.now(timezone.utc).isoformat()

        # 3. Summary Payload
        summary_payload = {
            "schema": "adjusted_price_store_full_population_summary_v01",
            "execution_id": self.execution_id,
            "status": "FULL_POPULATION_COMPLETED",
            "final_verdict": verdict,
            "next_state": next_state,
            "execution_timestamp": now_iso,
            "duration_seconds": round(duration_seconds, 2),
            "frozen_authority": {
                "population_count": EXPECTED_POPULATION_COUNT,
                "population_manifest_sha256": EXPECTED_POPULATION_SHA256,
                "pit_trading_dates_count": 4095,
                "pit_manifest_sha256": "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
                "calendar_cutoff_date": CANONICAL_CALENDAR_CUTOFF,
                "calendar_row_count": EXPECTED_CALENDAR_ROW_COUNT,
            },
            "status_counts": {
                "population_total": total_count,
                "complete": complete_count,
                "partial": partial_count,
                "empty": empty_count,
                "error": error_count,
                "insufficient_authority": insufficient_auth_count,
            },
            "subgroup_breakdown": {
                "alpha_23_census": {
                    "total": len(alpha_records),
                    "complete": alpha_complete,
                    "pass": alpha_complete == len(alpha_records) == 23,
                },
                "current_common": {
                    "total": len(current_common_records),
                    "complete": current_complete,
                },
                "historical_only": {
                    "total": len(historical_records),
                    "complete": historical_complete,
                },
            },
            "coverage_totals": {
                "total_expected_rows": total_expected_rows,
                "total_actual_source_rows": total_actual_rows,
                "total_stored_rows": total_stored_rows,
                "total_missing_expected_dates": total_missing,
                "total_unexpected_source_dates": total_unexpected,
            },
            "data_quality_totals": {
                "total_duplicates": total_duplicates,
                "total_invalid_ohlc": total_invalid_ohlc,
                "total_future_rows": total_future_rows,
            },
            "network_accounting": {
                "population_records_processed": logical_queries,
                "new_live_ticker_queries": new_live_queries,
                "physical_provider_attempts": physical_attempts,
                "retries": total_retries,
                "reused_without_network": reused_count,
                "krx_open_api_requests": 0,
                "opendart_requests": 0,
                "krx_mdc_requests": 0,
            },
            "preflight": preflight_summary,
        }

        summary_content = json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n"
        self.summary_path.write_text(summary_content, encoding="utf-8")
        summary_sha = hashlib.sha256(summary_content.encode("utf-8")).hexdigest()

        # 4. Manifest
        manifest_payload = {
            "schema": "full_population_manifest_v01",
            "execution_id": self.execution_id,
            "population_count": EXPECTED_POPULATION_COUNT,
            "population_sha256": EXPECTED_POPULATION_SHA256,
            "pit_sha256": "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
            "calendar_cutoff_date": CANONICAL_CALENDAR_CUTOFF,
            "source_provider": "PyKRX (get_market_ohlcv_by_date, adjusted=True)",
            "store_version": "ADJUSTED_PRICE_STORE_V01",
            "results_csv_sha256": results_sha,
            "summary_sha256": summary_sha,
        }
        self.manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # 5. Execution Audit Record (Captures current live acquisition run stats)
        execution_audit_path = self.artifact_dir / "full_population_execution_audit.json"
        execution_audit_payload = {
            "schema": "full_population_execution_audit_v01",
            "execution_id": self.execution_id,
            "population_total": total_count,
            "verified_complete": complete_count,
            "needs_fetch": total_count - complete_count,
            "network_calls_performed": new_live_queries,
            "physical_attempts": physical_attempts,
            "retries": total_retries,
            "reused_without_network": reused_count,
            "updated_at": now_iso,
        }
        execution_audit_path.write_text(json.dumps(execution_audit_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # 6. Resume Audit Record (Dedicated Zero-Call Idempotency Verification)
        is_true_resume_pass = (all_complete and new_live_queries == 0 and physical_attempts == 0)
        resume_audit_payload = {
            "schema": "full_population_resume_audit_v01",
            "execution_id": self.execution_id,
            "population_total": total_count,
            "verified_complete": complete_count,
            "needs_fetch": total_count - complete_count,
            "network_calls_performed": new_live_queries if is_true_resume_pass else None,
            "physical_attempts": physical_attempts if is_true_resume_pass else None,
            "reused_without_network": reused_count,
            "is_idempotent": is_true_resume_pass,
            "eligibility": "PASS" if is_true_resume_pass else "NOT_ELIGIBLE_UNRESOLVED_POPULATION",
            "audit_execution_status": "EXECUTED" if is_true_resume_pass else "NOT_EXECUTED",
            "updated_at": now_iso,
        }
        resume_audit_content = json.dumps(resume_audit_payload, indent=2, ensure_ascii=False) + "\n"
        self.resume_audit_path.write_text(resume_audit_content, encoding="utf-8")
        resume_audit_sha = hashlib.sha256(resume_audit_content.encode("utf-8")).hexdigest()

        # 7. Closure Manifest
        closure_payload = {
            "schema": "full_population_closure_manifest_v01",
            "execution_id": self.execution_id,
            "final_verdict": verdict,
            "next_state": next_state,
            "population_sha256": EXPECTED_POPULATION_SHA256,
            "pit_sha256": "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
            "calendar_cutoff_date": CANONICAL_CALENDAR_CUTOFF,
            "results_sha256": results_sha,
            "summary_sha256": summary_sha,
            "resume_audit_sha256": resume_audit_sha,
            "completed_count": complete_count,
            "failure_count": total_count - complete_count,
        }
        self.closure_manifest_path.write_text(json.dumps(closure_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return summary_payload
