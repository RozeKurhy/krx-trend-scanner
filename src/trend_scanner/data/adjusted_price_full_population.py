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
from typing import Any, Callable, Mapping, Protocol, Sequence

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
    NaverDirectAdjustedPriceDataProvider,
    normalize_ticker,
    validate_adjusted_ohlc,
)
from trend_scanner.data.adjusted_price_semantics import (
    CLOSURE_ACCOUNTING_SCHEMA_VERSION,
    ClosureState,
    TRADABILITY_CONTRACT_VERSION,
    analytic_candle_is_valid,
)
from trend_scanner.data.adjusted_price_source_authority import (
    CURRENT_SOURCE_DESCRIPTOR,
    assert_current_descriptor,
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
CHECKPOINT_SCHEMA_VERSION = "full_population_checkpoint_v02"
SOURCE_PROVIDER_VERSION = "NaverDirectAdjustedPriceDataProvider_v02"


class AcquisitionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    ERROR = "ERROR"
    INSUFFICIENT_AUTHORITY = "INSUFFICIENT_AUTHORITY"
    NO_USABLE_OBSERVATIONS = "NO_USABLE_OBSERVATIONS"
    COMPLETE_WITH_ADJUDICATED_NONUSABLE = "COMPLETE_WITH_ADJUDICATED_NONUSABLE"


# These are terminal closure outcomes.  A terminal outcome is a successful
# population-closure result even when the source produced no rows to persist.
# Keep this set as the single orchestration predicate used by checkpoints,
# aggregates, failure artifacts and resume accounting.
CLOSURE_SUCCESS_STATUSES = frozenset(
    {
        AcquisitionStatus.COMPLETE.value,
        AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
    }
)

_NO_USABLE_TERMINAL_STATES = frozenset(
    {
        "RAW_ROWS_PRESENT_ALL_PHANTOM",
        "RAW_ROWS_PRESENT_AUTHORITY_SUPPRESSED",
        "NO_USABLE_OBSERVATIONS",
    }
)
_ADJUDICATED_TERMINAL_STATES = frozenset(
    {
        "RAW_ROWS_PRESENT_ALL_PHANTOM",
        "RAW_ROWS_PRESENT_ALL_SOURCE_NONUSABLE",
        "ADJUDICATED_SOURCE_NONUSABLE",
        "MIXED_USABLE_AND_ADJUDICATED",
    }
)


def is_closure_success(status: str | AcquisitionStatus) -> bool:
    """Return whether *status* is one of the three successful closure outcomes."""
    value = status.value if isinstance(status, AcquisitionStatus) else str(status)
    return value in CLOSURE_SUCCESS_STATUSES


def validate_terminal_success_evidence(info: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Validate status-specific checkpoint evidence before allowing a resume.

    Status alone is never trusted: zero-store terminal states must carry the
    counters and approved terminal state that prove why no rows were written.
    A normal COMPLETE must still be backed by a non-empty verified store; the
    caller performs the physical store/date/authority checks.
    """
    status = str(info.get("acquisition_status", ""))
    if not is_closure_success(status):
        return False, "NOT_CLOSURE_SUCCESS"

    def _nonnegative_int(key: str) -> int | None:
        value = info.get(key, 0)
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    stored = _nonnegative_int("stored_row_count")
    usable = _nonnegative_int("usable_source_count")
    adjudicated = _nonnegative_int("adjudicated_source_nonusable_count")
    silent = _nonnegative_int("silent_missing_count")
    unexpected = _nonnegative_int(
        "unexpected_source_count" if "unexpected_source_count" in info else "unexpected_count"
    )
    authority_conflict = _nonnegative_int("authority_conflict_count")
    resolved_authority_conflict = _nonnegative_int("resolved_authority_conflict_count")
    unresolved_authority_conflict = _nonnegative_int("unresolved_authority_conflict_count")
    if None in {
        stored,
        usable,
        adjudicated,
        silent,
        unexpected,
        authority_conflict,
        resolved_authority_conflict,
        unresolved_authority_conflict,
    }:
        return False, "MALFORMED_TERMINAL_COUNTER"
    actual_dates = info.get("actual_dates", [])
    if not isinstance(actual_dates, (list, tuple)):
        return False, "MALFORMED_TERMINAL_DATES"
    for optional_counter in ("expected_count", "actual_row_count", "matched_count", "missing_count"):
        if optional_counter in info and _nonnegative_int(optional_counter) is None:
            return False, "MALFORMED_TERMINAL_COUNTER"
    assert stored is not None and usable is not None and adjudicated is not None
    assert silent is not None and unexpected is not None and authority_conflict is not None
    assert resolved_authority_conflict is not None and unresolved_authority_conflict is not None

    # ``authority_conflict_count`` is retained as the total audit count.  A
    # pre-FIX03 checkpoint has no explicit unresolved counter, so its total is
    # conservatively treated as unresolved and cannot be reused blindly.
    legacy_conflict_counter = "unresolved_authority_conflict_count" not in info
    if legacy_conflict_counter:
        unresolved_authority_conflict = authority_conflict
    if resolved_authority_conflict + unresolved_authority_conflict != authority_conflict:
        return False, "AUTHORITY_CONFLICT_COUNTER_INCONSISTENT"

    def _date_tuple(key: str) -> tuple[str, ...] | None:
        value = info.get(key, ())
        if not isinstance(value, (list, tuple)):
            return None
        dates = tuple(str(item) for item in value)
        if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) for date in dates):
            return None
        if len(set(dates)) != len(dates):
            return None
        return dates

    resolved_dates = _date_tuple("resolved_authority_conflict_dates")
    unresolved_dates = _date_tuple("unresolved_authority_conflict_dates")
    if resolved_dates is None or unresolved_dates is None:
        return False, "MALFORMED_AUTHORITY_CONFLICT_DATES"
    if legacy_conflict_counter and authority_conflict > 0:
        return False, "LEGACY_AUTHORITY_CONFLICT_EVIDENCE_AMBIGUOUS"
    if (
        "resolved_authority_conflict_dates" in info
        and len(resolved_dates) != resolved_authority_conflict
    ) or (
        "unresolved_authority_conflict_dates" in info
        and len(unresolved_dates) != unresolved_authority_conflict
    ):
        return False, "AUTHORITY_CONFLICT_DATE_COUNT_MISMATCH"
    if set(resolved_dates).intersection(unresolved_dates):
        return False, "AUTHORITY_CONFLICT_DATE_OVERLAP"

    if silent != 0 or unexpected != 0 or unresolved_authority_conflict != 0:
        return False, "UNRESOLVED_TERMINAL_COUNTER"

    terminal_state = info.get("terminal_state")
    if status == AcquisitionStatus.COMPLETE.value:
        if stored <= 0 or usable <= 0:
            return False, "COMPLETE_REQUIRES_STORED_USABLE_ROWS"
        return True, None

    if status == AcquisitionStatus.NO_USABLE_OBSERVATIONS.value:
        if stored != 0 or usable != 0 or adjudicated != 0:
            return False, "NO_USABLE_COUNTER_INCONSISTENT"
        if terminal_state not in _NO_USABLE_TERMINAL_STATES:
            return False, "NO_USABLE_TERMINAL_STATE_UNAPPROVED"
        return True, None

    # COMPLETE_WITH_ADJUDICATED_NONUSABLE permits either an all-adjudicated
    # zero-store terminal or a mixed store + adjudicated result.
    if adjudicated <= 0:
        return False, "ADJUDICATED_TERMINAL_REQUIRES_ADJUDICATED_ROWS"
    if terminal_state not in _ADJUDICATED_TERMINAL_STATES:
        return False, "ADJUDICATED_TERMINAL_STATE_UNAPPROVED"
    if stored == 0 and usable != 0:
        return False, "ZERO_STORE_ADJUDICATED_HAS_USABLE_ROWS"
    if stored > 0 and usable <= 0:
        return False, "MIXED_ADJUDICATED_REQUIRES_USABLE_STORE"
    return True, None


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
    usable_source_count: int = 0
    confirmed_nontrading_count: int = 0
    adjudicated_source_nonusable_count: int = 0
    silent_missing_count: int = 0
    authority_conflict_count: int = 0
    resolved_authority_conflict_count: int = 0
    unresolved_authority_conflict_count: int = 0
    resolved_authority_conflict_dates: tuple[str, ...] = ()
    unresolved_authority_conflict_dates: tuple[str, ...] = ()
    phantom_count: int = 0
    analytic_invalid_ohlc_count: int = 0
    terminal_state: str | None = None
    authority_suppressed_source_count: int = 0
    authority_suppressed_source_dates: tuple[str, ...] = ()
    source_presence_audit: tuple[dict[str, Any], ...] = ()


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
    source_authority_id: str
    source_provider_version: str
    closure_accounting_schema_version: str
    tradability_contract_version: str
    store_schema_version: str
    pit_authority_sha256: str


class AdjustedPriceProviderProtocol(Protocol):
    source_descriptor: Any

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame: ...

    def call_audit(self) -> dict[str, int]: ...


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
        provider: AdjustedPriceProviderProtocol | None = None,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.5,
        execution_id: str | None = None,
    ) -> None:
        self.population_path = population_path
        self.store = AdjustedPriceStore(store_dir)
        self.artifact_dir = Path(artifact_dir)
        self.provider = provider if provider is not None else NaverDirectAdjustedPriceDataProvider()
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

    @staticmethod
    def _validate_provider_authority(provider: AdjustedPriceProviderProtocol) -> None:
        try:
            assert_current_descriptor(provider.source_descriptor)
        except (AttributeError, MarketDataError) as exc:
            raise MarketDataError("PROVIDER_AUTHORITY_MISMATCH") from exc

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

            expected_compatibility = {
                "source_authority_id": CURRENT_SOURCE_DESCRIPTOR.source_authority_id,
                "source_provider_version": SOURCE_PROVIDER_VERSION,
                "closure_accounting_schema_version": CLOSURE_ACCOUNTING_SCHEMA_VERSION,
                "tradability_contract_version": TRADABILITY_CONTRACT_VERSION,
                "store_schema_version": "ADJUSTED_PRICE_V02",
                "pit_authority_sha256": "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
            }
            mismatches = {
                key: (data.get(key), expected)
                for key, expected in expected_compatibility.items()
                if data.get(key) != expected
            }
            if mismatches:
                raise RuntimeError(
                    "CHECKPOINT_COMPATIBILITY_MISMATCH: checkpoint semantic identity is stale: "
                    + ", ".join(f"{key}={got!r} expected={expected!r}" for key, (got, expected) in mismatches.items())
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
                source_authority_id=data["source_authority_id"],
                source_provider_version=data["source_provider_version"],
                closure_accounting_schema_version=data["closure_accounting_schema_version"],
                tradability_contract_version=data["tradability_contract_version"],
                store_schema_version=data["store_schema_version"],
                pit_authority_sha256=data["pit_authority_sha256"],
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
            source_authority_id=CURRENT_SOURCE_DESCRIPTOR.source_authority_id,
            source_provider_version=SOURCE_PROVIDER_VERSION,
            closure_accounting_schema_version=CLOSURE_ACCOUNTING_SCHEMA_VERSION,
            tradability_contract_version=TRADABILITY_CONTRACT_VERSION,
            store_schema_version="ADJUSTED_PRICE_V02",
            pit_authority_sha256="6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
        )

    def save_checkpoint(self, checkpoint: FullPopulationCheckpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        temp_p = self.checkpoint_path.with_suffix(".json.tmp")
        payload = asdict(checkpoint)
        temp_p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp_p, self.checkpoint_path)

    def _is_completed_checkpoint_reusable(
        self,
        rec: Mapping[str, Any],
        info: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate a completed checkpoint entry without contacting a provider."""
        valid_evidence, evidence_error = validate_terminal_success_evidence(info)
        if not valid_evidence:
            return False, evidence_error

        ticker = str(rec["ticker"])
        status = str(info.get("acquisition_status"))
        expected_start = str(rec["first_common_date"])
        expected_end = min(str(rec["last_common_date"]), CANONICAL_CALENDAR_CUTOFF)
        stored_count = int(info.get("stored_row_count", 0))
        actual_dates = list(info.get("actual_dates", []))

        # The checkpoint identity is validated by load_or_create_checkpoint.
        # If an entry carries per-record identity, reject stale values too.
        if info.get("source_authority_id") not in (None, CURRENT_SOURCE_DESCRIPTOR.source_authority_id):
            return False, "CHECKPOINT_SOURCE_AUTHORITY_MISMATCH"
        if info.get("source_provider_version") not in (None, SOURCE_PROVIDER_VERSION):
            return False, "CHECKPOINT_PROVIDER_VERSION_MISMATCH"

        if status == AcquisitionStatus.COMPLETE.value or stored_count > 0:
            verified, verify_error = verify_stored_ticker_integrity(
                self.store,
                ticker,
                stored_count,
                actual_dates,
                expected_requested_start=expected_start,
                expected_requested_end=expected_end,
            )
            if not verified:
                return False, verify_error
            if not self.store.is_current_authority_snapshot(ticker):
                return False, "STORE_AUTHORITY_SNAPSHOT_STALE"
            return True, None

        # A zero-store terminal is valid only when the evidence validator has
        # proved the adjudicated/non-trading outcome.  A physical store would
        # contradict stored_row_count=0 and therefore forces a refetch.
        if self.store.exists(ticker):
            return False, "ZERO_STORE_TERMINAL_HAS_STORE"
        return True, None

    @staticmethod
    def _checkpoint_entry_from_record(
        rec_obj: TickerAcquisitionRecord,
        actual_dates: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Serialize complete terminal evidence for status-aware resumption."""
        return {
            "ticker": rec_obj.ticker,
            "acquisition_status": rec_obj.acquisition_status,
            "source_status": rec_obj.source_status,
            "coverage_status": rec_obj.coverage_status,
            "requested_start": rec_obj.requested_start,
            "requested_end": rec_obj.requested_end,
            "stored_row_count": rec_obj.stored_row_count,
            "stored_start": rec_obj.stored_start,
            "stored_end": rec_obj.stored_end,
            "authority_source": rec_obj.authority_source,
            "authority_quality": rec_obj.authority_quality,
            "expected_count": rec_obj.expected_observation_count,
            "actual_row_count": rec_obj.actual_source_row_count,
            "matched_count": rec_obj.matched_expected_count,
            "missing_count": rec_obj.missing_expected_count,
            "unexpected_source_count": rec_obj.unexpected_source_date_count,
            "first_actual_date": rec_obj.first_actual_date,
            "last_actual_date": rec_obj.last_actual_date,
            "post_write_verified": rec_obj.post_write_verified,
            "actual_dates": list(actual_dates),
            "source_execution_attempt_count": rec_obj.attempt_count,
            "usable_source_count": rec_obj.usable_source_count,
            "confirmed_nontrading_count": rec_obj.confirmed_nontrading_count,
            "adjudicated_source_nonusable_count": rec_obj.adjudicated_source_nonusable_count,
            "silent_missing_count": rec_obj.silent_missing_count,
            "authority_conflict_count": rec_obj.authority_conflict_count,
            "resolved_authority_conflict_count": rec_obj.resolved_authority_conflict_count,
            "unresolved_authority_conflict_count": rec_obj.unresolved_authority_conflict_count,
            "resolved_authority_conflict_dates": list(rec_obj.resolved_authority_conflict_dates),
            "unresolved_authority_conflict_dates": list(rec_obj.unresolved_authority_conflict_dates),
            "phantom_count": rec_obj.phantom_count,
            "authority_suppressed_source_count": rec_obj.authority_suppressed_source_count,
            "authority_suppressed_source_dates": list(rec_obj.authority_suppressed_source_dates),
            "source_presence_audit": list(rec_obj.source_presence_audit),
            "terminal_state": rec_obj.terminal_state,
            "source_authority_id": CURRENT_SOURCE_DESCRIPTOR.source_authority_id,
            "source_provider_version": SOURCE_PROVIDER_VERSION,
            "updated_at": rec_obj.updated_at,
        }

    @staticmethod
    def _record_from_checkpoint(
        rec: Mapping[str, Any],
        info: Mapping[str, Any],
    ) -> TickerAcquisitionRecord:
        """Rehydrate a terminal record without invoking provider or store writes."""
        status = str(info["acquisition_status"])
        actual_dates = tuple(str(d) for d in info.get("actual_dates", []))
        return TickerAcquisitionRecord(
            ticker=str(rec["ticker"]),
            isu_cd=",".join(rec.get("isu_cd", [])),
            market=",".join(rec.get("market", [])),
            first_common_date=str(rec["first_common_date"]),
            last_common_date=str(rec["last_common_date"]),
            numeric_or_alpha=str(rec.get("numeric_or_alpha", "")),
            currently_common=bool(rec.get("currently_common", False)),
            historical_only=bool(rec.get("historical_only", False)),
            requested_start=str(info.get("requested_start", rec["first_common_date"])),
            requested_end=str(info.get("requested_end", min(str(rec["last_common_date"]), CANONICAL_CALENDAR_CUTOFF))),
            authority_source=str(info.get("authority_source", "CHECKPOINT")),
            authority_quality=str(info.get("authority_quality", "CHECKPOINT_VERIFIED")),
            expected_observation_count=int(info.get("expected_count", 0)),
            actual_source_row_count=int(info.get("actual_row_count", 0)),
            matched_expected_count=int(info.get("matched_count", 0)),
            missing_expected_count=int(info.get("missing_count", info.get("silent_missing_count", 0))),
            unexpected_source_date_count=int(info.get("unexpected_source_count", info.get("unexpected_count", 0))),
            first_actual_date=info.get("first_actual_date") or (actual_dates[0] if actual_dates else None),
            last_actual_date=info.get("last_actual_date") or (actual_dates[-1] if actual_dates else None),
            source_status=str(info.get("source_status", "SUCCESS")),
            coverage_status=str(info.get("coverage_status", CoverageStatus.NO_EXPECTED_OBSERVATIONS.value)),
            acquisition_status=status,
            attempt_count=0,
            retry_count=0,
            reused_without_network=True,
            stored_row_count=int(info.get("stored_row_count", 0)),
            stored_start=info.get("stored_start"),
            stored_end=info.get("stored_end"),
            duplicate_count=int(info.get("duplicate_count", 0)),
            invalid_ohlc_count=int(info.get("invalid_ohlc_count", 0)),
            future_row_count=int(info.get("future_row_count", 0)),
            post_write_verified=bool(info.get("post_write_verified", False)),
            error_type=None,
            error_message_sanitized=None,
            updated_at=datetime.now(timezone.utc).isoformat(),
            usable_source_count=int(info.get("usable_source_count", 0)),
            confirmed_nontrading_count=int(info.get("confirmed_nontrading_count", 0)),
            adjudicated_source_nonusable_count=int(info.get("adjudicated_source_nonusable_count", 0)),
            silent_missing_count=int(info.get("silent_missing_count", info.get("missing_count", 0))),
            authority_conflict_count=int(info.get("authority_conflict_count", 0)),
            resolved_authority_conflict_count=int(info.get("resolved_authority_conflict_count", 0)),
            unresolved_authority_conflict_count=int(
                info.get(
                    "unresolved_authority_conflict_count",
                    info.get("authority_conflict_count", 0),
                )
            ),
            resolved_authority_conflict_dates=tuple(
                str(item) for item in info.get("resolved_authority_conflict_dates", ())
            ),
            unresolved_authority_conflict_dates=tuple(
                str(item)
                for item in info.get(
                    "unresolved_authority_conflict_dates",
                    info.get("authority_conflict_dates", ()),
                )
            ),
            phantom_count=int(info.get("phantom_count", 0)),
            analytic_invalid_ohlc_count=int(info.get("analytic_invalid_ohlc_count", 0)),
            terminal_state=info.get("terminal_state"),
            authority_suppressed_source_count=int(info.get("authority_suppressed_source_count", 0)),
            authority_suppressed_source_dates=tuple(info.get("authority_suppressed_source_dates", ())),
            source_presence_audit=tuple(info.get("source_presence_audit", ())),
        )

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

            # 1. If recorded as any closure-success status, validate terminal
            # evidence and then verify only the store that the status requires.
            if t in checkpoint.completed_tickers:
                info = checkpoint.completed_tickers[t]
                is_valid, _ = self._is_completed_checkpoint_reusable(rec, info)
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
                        and not resolution.unresolved_authority_conflict_dates
                        and resolution.expected_tradable_count > 0
                        and len(df) == resolution.expected_tradable_count
                        and list(df.index.strftime("%Y-%m-%d")) == list(resolution.expected_tradable_dates)
                        and meta is not None
                        and self.store.is_current_authority_snapshot(t)
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
                elif st in {
                    AcquisitionStatus.EMPTY.value,
                    AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
                    AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
                }:
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
        provider: AdjustedPriceProviderProtocol | None = None,
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
        phantom_dates: set[str] = set()
        source_nonusable_dates: set[str] = set()
        phantom_count = 0
        source_nonusable_count = 0
        raw_source_row_count = 0
        source_native_adjusted = False
        source_row_audit: list[dict[str, Any]] = []
        raw_frame = pd.DataFrame()

        cache_is_current = False
        if cached_info is not None and "actual_dates" in cached_info:
            cache_is_current, _ = verify_stored_ticker_integrity(
                self.store,
                ticker,
                cached_info.get("stored_row_count", len(cached_info.get("actual_dates", []))),
                cached_info.get("actual_dates", []),
                expected_requested_start=req_start,
                expected_requested_end=req_end,
            )
            cache_is_current = cache_is_current and self.store.is_current_authority_snapshot(ticker)
        if cache_is_current:
            actual_dates = cached_info["actual_dates"]
            attempt_count = 0  # Reused from cache without network call
            retry_count = 0
            reused_without_network = True
        else:
            if provider is None:
                provider = self.provider
            self._validate_provider_authority(provider)

            for attempt in range(1, self.max_retries + 2):
                attempt_count = attempt
                try:
                    frame = provider.load_daily(ticker, req_start, req_end)
                    raw_frame = frame.copy()
                    actual_dates = [d.strftime("%Y-%m-%d") for d in frame.index]
                    source_native_adjusted = bool(frame.attrs.get("source_native_adjusted", False))
                    phantom_dates = set(str(d) for d in frame.attrs.get("phantom_dates", ()))
                    source_nonusable_dates = set(
                        str(d) for d in frame.attrs.get("source_nonusable_dates", ())
                    )
                    phantom_count = int(frame.attrs.get("phantom_row_count", len(phantom_dates)))
                    source_nonusable_count = int(
                        frame.attrs.get("source_nonusable_row_count", len(source_nonusable_dates))
                    )
                    raw_source_row_count = int(
                        frame.attrs.get(
                            "raw_source_row_count",
                            len(actual_dates) + phantom_count + source_nonusable_count,
                        )
                    )
                    source_row_audit = [dict(entry) for entry in frame.attrs.get("source_row_audit", ())]
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
        analytic_invalid_ohlc_count = 0
        future_row_count = 0
        first_actual = actual_dates[0] if actual_dates else None
        last_actual = actual_dates[-1] if actual_dates else None

        if not frame.empty:
            duplicate_count = int(frame.index.duplicated().sum())
            req_end_ts = pd.Timestamp(req_end)
            future_row_count = int((frame.index > req_end_ts).sum())
            analytic_valid = analytic_candle_is_valid(frame)
            analytic_invalid_ohlc_count = int((~analytic_valid).sum())
            invalid_ohlc_count = 0 if source_native_adjusted else analytic_invalid_ohlc_count
        elif cached_info is not None:
            duplicate_count = len(actual_dates) - len(set(actual_dates))
            future_row_count = sum(1 for d in actual_dates if d > req_end)

        # 2. Coverage Evaluation and independent authority reconciliation.
        # The provider reports source facts only.  Market tradability comes
        # from the independent expected-coverage authority.
        authority_nontrading_dates = set(resolution.nontradable_dates)
        authority_tradable_dates = set(resolution.expected_tradable_dates)
        authority_conflict_dates = set(resolution.authority_conflict_dates)
        resolved_authority_conflict_dates = set(
            resolution.resolved_authority_conflict_dates
        )
        unresolved_authority_conflict_dates = set(
            resolution.unresolved_authority_conflict_dates
        )
        # Older/custom resolution providers may only expose the historical
        # conflict list.  Treat those conflicts as unresolved unless the
        # resolver explicitly supplied a resolved/unresolved split.
        if (
            authority_conflict_dates
            and not resolved_authority_conflict_dates
            and not unresolved_authority_conflict_dates
        ):
            unresolved_authority_conflict_dates = set(authority_conflict_dates)
        resolved_authority_conflict_dates.intersection_update(authority_conflict_dates)
        unresolved_authority_conflict_dates.update(
            authority_conflict_dates - resolved_authority_conflict_dates
        )
        resolved_authority_conflict_dates.difference_update(
            unresolved_authority_conflict_dates
        )
        authority_conflict_dates.update(
            resolved_authority_conflict_dates | unresolved_authority_conflict_dates
        )
        source_positive_dates = set(actual_dates)
        source_dates = source_positive_dates | phantom_dates | source_nonusable_dates
        authority_suppressed_dates = authority_nontrading_dates.intersection(source_dates)

        # Preserve an auditable record for positive Naver rows that independent
        # authority suppresses as non-trading before any store write.
        if authority_suppressed_dates.intersection(source_positive_dates) and not raw_frame.empty:
            for date_str in sorted(authority_suppressed_dates.intersection(source_positive_dates)):
                ts = pd.Timestamp(date_str)
                if ts in raw_frame.index:
                    row = raw_frame.loc[ts]
                    source_row_audit.append(
                        {
                            "ticker": ticker,
                            "date": date_str,
                            "classification": "NAVER_POSITIVE_NONTRADING_PLACEHOLDER",
                            "reason": "independent authority confirms nontrading; source row suppressed",
                            "source_authority": getattr(getattr(provider, "source_descriptor", None), "source_authority_id", "UNKNOWN"),
                            "source_row_present": True,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                        }
                    )

        # A phantom is only closed when independent authority accounts for its
        # date as either non-trading or tradable.  Unknown authority is a hard
        # failure rather than an inferred non-trading day.
        authority_ready = resolution.authority_status in {
            AuthorityStatus.VALID.value,
            AuthorityStatus.NO_EXPECTED_OBSERVATIONS.value,
        }
        unresolved_phantom_dates = phantom_dates - authority_nontrading_dates - authority_tradable_dates
        if not authority_ready:
            unresolved_phantom_dates = set(phantom_dates)
        authority_tradable_phantom_dates = phantom_dates.intersection(authority_tradable_dates)
        adjudicated_dates = (
            set(resolution.adjudicated_source_nonusable_dates)
            | source_nonusable_dates
            | authority_tradable_phantom_dates
        ) - authority_nontrading_dates

        # Remove authority-suppressed positive rows from the usable source
        # frame.  Their presence remains in source_presence_audit above.
        if authority_suppressed_dates.intersection(source_positive_dates) and not frame.empty:
            suppressed_ts = pd.to_datetime(sorted(authority_suppressed_dates.intersection(source_positive_dates)))
            frame = frame.loc[~frame.index.isin(suppressed_ts)].copy()
            frame.attrs.update(raw_frame.attrs)
            actual_dates = [d.strftime("%Y-%m-%d") for d in frame.index]
            row_count = len(actual_dates)
            first_actual = actual_dates[0] if actual_dates else None
            last_actual = actual_dates[-1] if actual_dates else None

        exp_set = set(resolution.expected_tradable_dates)
        exp_set -= authority_nontrading_dates
        exp_set -= adjudicated_dates
        act_set = set(actual_dates)
        matched_set = exp_set.intersection(act_set)
        missing_set = exp_set - act_set
        unexpected_set = act_set - exp_set

        matched_count = len(matched_set)
        missing_count = len(missing_set)
        unexpected_count = len(unexpected_set)
        expected_count = len(exp_set)
        confirmed_nontrading_count = len(authority_nontrading_dates)

        if last_error is not None:
            source_status = "ERROR"
        elif row_count == 0 and raw_source_row_count == 0:
            source_status = "EMPTY"
        elif invalid_ohlc_count > 0 or duplicate_count > 0 or future_row_count > 0:
            source_status = "SCHEMA_ANOMALY"
        else:
            source_status = "SUCCESS"

        all_phantom_terminal = (
            row_count == 0
            and raw_source_row_count > 0
            and phantom_count == raw_source_row_count
            and not unresolved_phantom_dates
        )
        all_source_nonusable_terminal = (
            row_count == 0
            and source_nonusable_count > 0
            and source_nonusable_count == raw_source_row_count
        )
        all_authority_suppressed_terminal = (
            row_count == 0
            and raw_source_row_count > 0
            and len(authority_suppressed_dates) == raw_source_row_count
        )
        if unresolved_phantom_dates or unresolved_authority_conflict_dates:
            coverage_status = CoverageStatus.INSUFFICIENT_COVERAGE_AUTHORITY.value
        elif (all_phantom_terminal or all_source_nonusable_terminal or all_authority_suppressed_terminal) and expected_count == 0:
            coverage_status = CoverageStatus.NO_EXPECTED_OBSERVATIONS.value
        elif resolution.authority_status != AuthorityStatus.VALID.value:
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
            forbidden_dates = set(actual_dates).intersection(authority_nontrading_dates | adjudicated_dates)
            if forbidden_dates:
                raise MarketDataError(
                    "STORE_WRITE_AUTHORITY_INTERSECTION: " + ",".join(sorted(forbidden_dates))
                )
            try:
                self.store.save_full(
                    ticker,
                    frame,
                    source_descriptor=provider.source_descriptor if provider is not None else None,
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
        elif cache_is_current and cached_info is not None and cached_info.get("post_write_verified"):
            verified, v_err = verify_stored_ticker_integrity(
                self.store, ticker, row_count, actual_dates
            )
            post_write_verified = verified
            if verified:
                stored_row_count = row_count
                stored_start = first_actual
                stored_end = last_actual

        # 4. Determine Final Acquisition Status
        terminal_state: str | None = None
        if unresolved_authority_conflict_dates:
            terminal_state = "UNRESOLVED_AUTHORITY_CONFLICT"
            acq_status = AcquisitionStatus.INSUFFICIENT_AUTHORITY.value
        elif unresolved_phantom_dates:
            terminal_state = "UNRESOLVED_ACTIVITY_EVIDENCE"
            acq_status = AcquisitionStatus.INSUFFICIENT_AUTHORITY.value
        elif all_phantom_terminal:
            terminal_state = "RAW_ROWS_PRESENT_ALL_PHANTOM"
            if set(phantom_dates).issubset(authority_nontrading_dates):
                acq_status = AcquisitionStatus.NO_USABLE_OBSERVATIONS.value
            else:
                acq_status = AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value
        elif all_source_nonusable_terminal:
            terminal_state = "RAW_ROWS_PRESENT_ALL_SOURCE_NONUSABLE"
            acq_status = AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value
        elif all_authority_suppressed_terminal:
            terminal_state = "RAW_ROWS_PRESENT_AUTHORITY_SUPPRESSED"
            acq_status = AcquisitionStatus.NO_USABLE_OBSERVATIONS.value
        elif resolution.authority_status != AuthorityStatus.VALID.value:
            acq_status = AcquisitionStatus.INSUFFICIENT_AUTHORITY.value
        elif source_status == "ERROR":
            acq_status = AcquisitionStatus.ERROR.value
        elif source_status == "EMPTY":
            acq_status = AcquisitionStatus.EMPTY.value
        elif expected_count == 0 and not unexpected_set and (phantom_count or source_nonusable_count):
            terminal_state = "ADJUDICATED_SOURCE_NONUSABLE"
            acq_status = AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value
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
            usable_source_count=row_count,
            confirmed_nontrading_count=confirmed_nontrading_count,
            adjudicated_source_nonusable_count=len(adjudicated_dates),
            silent_missing_count=missing_count,
            authority_conflict_count=len(authority_conflict_dates),
            resolved_authority_conflict_count=len(resolved_authority_conflict_dates),
            unresolved_authority_conflict_count=len(unresolved_authority_conflict_dates),
            resolved_authority_conflict_dates=tuple(sorted(resolved_authority_conflict_dates)),
            unresolved_authority_conflict_dates=tuple(sorted(unresolved_authority_conflict_dates)),
            phantom_count=phantom_count,
            analytic_invalid_ohlc_count=analytic_invalid_ohlc_count,
            terminal_state=terminal_state,
            authority_suppressed_source_count=len(authority_suppressed_dates),
            authority_suppressed_source_dates=tuple(sorted(authority_suppressed_dates)),
            source_presence_audit=tuple(source_row_audit),
        )

    def run_acquisition(
        self,
        provider: AdjustedPriceProviderProtocol | None = None,
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

        active_provider = provider or self.provider
        self._validate_provider_authority(active_provider)

        # Acquisition Loop
        start_time = time.time()
        for idx, rec in enumerate(population, start=1):
            t = rec["ticker"]

            # Resumability: every closure-success status is reusable when its
            # status-specific evidence and store/authority state are valid.
            if t in checkpoint.completed_tickers:
                info = checkpoint.completed_tickers[t]
                is_valid, _ = self._is_completed_checkpoint_reusable(rec, info)
                if is_valid:
                    rec_obj = self._record_from_checkpoint(rec, info)
                    records.append(rec_obj)
                    consecutive_errors = 0
                    consecutive_empties = 0
                    if progress_callback:
                        progress_callback(idx, total_population, t, f"{rec_obj.acquisition_status} (REUSED)")
                    continue

            # Query via provider with gentle rate-throttling to prevent KRX IP block
            rec_obj = self.process_single_ticker(rec, provider=active_provider)
            records.append(rec_obj)
            if not rec_obj.reused_without_network:
                time.sleep(0.50)  # Gentle delay between source requests

            if is_closure_success(rec_obj.acquisition_status):
                consecutive_errors = 0
                consecutive_empties = 0
                actual_dates_list = (
                    self.store.load_daily(t).index.strftime("%Y-%m-%d").tolist()
                    if self.store.exists(t)
                    else []
                )
                checkpoint.completed_tickers[t] = self._checkpoint_entry_from_record(
                    rec_obj,
                    actual_dates_list,
                )
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
                    "usable_source_count": rec_obj.usable_source_count,
                    "confirmed_nontrading_count": rec_obj.confirmed_nontrading_count,
                    "adjudicated_source_nonusable_count": rec_obj.adjudicated_source_nonusable_count,
                    "silent_missing_count": rec_obj.silent_missing_count,
                    "authority_conflict_count": rec_obj.authority_conflict_count,
                    "resolved_authority_conflict_count": rec_obj.resolved_authority_conflict_count,
                    "unresolved_authority_conflict_count": rec_obj.unresolved_authority_conflict_count,
                    "resolved_authority_conflict_dates": list(rec_obj.resolved_authority_conflict_dates),
                    "unresolved_authority_conflict_dates": list(rec_obj.unresolved_authority_conflict_dates),
                    "phantom_count": rec_obj.phantom_count,
                    "authority_suppressed_source_count": rec_obj.authority_suppressed_source_count,
                    "authority_suppressed_source_dates": list(rec_obj.authority_suppressed_source_dates),
                    "source_presence_audit": list(rec_obj.source_presence_audit),
                    "terminal_state": rec_obj.terminal_state,
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
        normal_complete_count = sum(
            1 for r in records if r.acquisition_status == AcquisitionStatus.COMPLETE.value
        )
        no_usable_count = sum(
            1 for r in records if r.acquisition_status == AcquisitionStatus.NO_USABLE_OBSERVATIONS.value
        )
        adjudicated_complete_count = sum(
            1
            for r in records
            if r.acquisition_status == AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value
        )
        closure_complete_count = normal_complete_count + no_usable_count + adjudicated_complete_count
        if closure_complete_count != sum(1 for r in records if is_closure_success(r.acquisition_status)):
            raise RuntimeError("CLOSURE_ACCOUNTING_INVARIANT_FAILED: terminal status count mismatch")

        # The canonical `complete` field is closure-complete (all three
        # terminal success states).  `normal_complete` preserves the ordinary
        # COMPLETE subset for consumers that need the finer breakdown.
        complete_count = closure_complete_count
        partial_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.PARTIAL.value)
        empty_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.EMPTY.value)
        error_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.ERROR.value)
        insufficient_auth_count = sum(1 for r in records if r.acquisition_status == AcquisitionStatus.INSUFFICIENT_AUTHORITY.value)

        alpha_records = [r for r in records if r.numeric_or_alpha == "alphanumeric"]
        alpha_complete = sum(1 for r in alpha_records if is_closure_success(r.acquisition_status))

        current_common_records = [r for r in records if r.currently_common]
        current_complete = sum(1 for r in current_common_records if is_closure_success(r.acquisition_status))

        historical_records = [r for r in records if r.historical_only]
        historical_complete = sum(1 for r in historical_records if is_closure_success(r.acquisition_status))

        total_expected_rows = sum(r.expected_observation_count for r in records)
        total_actual_rows = sum(r.actual_source_row_count for r in records)
        total_stored_rows = sum(r.stored_row_count for r in records)

        total_missing = sum(r.missing_expected_count for r in records)
        total_unexpected = sum(r.unexpected_source_date_count for r in records)
        total_duplicates = sum(r.duplicate_count for r in records)
        total_invalid_ohlc = sum(r.invalid_ohlc_count for r in records)
        total_analytic_invalid_ohlc = sum(r.analytic_invalid_ohlc_count for r in records)
        total_future_rows = sum(r.future_row_count for r in records)
        total_usable = sum(r.usable_source_count for r in records)
        total_confirmed_nontrading = sum(r.confirmed_nontrading_count for r in records)
        total_source_nonusable = sum(r.adjudicated_source_nonusable_count for r in records)
        total_silent_missing = sum(r.silent_missing_count for r in records)
        total_authority_conflicts = sum(r.authority_conflict_count for r in records)
        total_resolved_authority_conflicts = sum(
            r.resolved_authority_conflict_count for r in records
        )
        total_unresolved_authority_conflicts = sum(
            r.unresolved_authority_conflict_count for r in records
        )
        if (
            total_authority_conflicts
            != total_resolved_authority_conflicts + total_unresolved_authority_conflicts
        ):
            raise RuntimeError(
                "AUTHORITY_CONFLICT_ACCOUNTING_INVARIANT_FAILED: "
                "total != resolved + unresolved"
            )
        total_phantom = sum(r.phantom_count for r in records)
        total_authority_suppressed = sum(r.authority_suppressed_source_count for r in records)

        logical_queries = total_count
        new_live_queries = sum(1 for r in records if not r.reused_without_network)
        physical_attempts = sum(r.attempt_count for r in records)
        total_retries = sum(r.retry_count for r in records)
        reused_count = sum(1 for r in records if r.reused_without_network)

        failures = [r for r in records if not is_closure_success(r.acquisition_status)]
        if failures:
            failures_df = pd.DataFrame([asdict(r) for r in failures])
            self.failures_csv_path.write_text(failures_df.to_csv(index=False), encoding="utf-8")
        elif self.failures_csv_path.exists():
            self.failures_csv_path.unlink()

        # Verdict evaluation via canonical dynamic adjudicator (BLOCKER D)
        from trend_scanner.data.adjusted_price_diagnostics import (
            adjudicate_adjusted_price_full_population_state,
            load_canonical_authority_state,
        )

        auth_state = load_canonical_authority_state(self.artifact_dir)
        cap_status = auth_state.get("provider_capability_status", "UNKNOWN")

        quality_clean = (total_duplicates == 0 and total_invalid_ohlc == 0 and total_future_rows == 0)
        if total_unresolved_authority_conflicts > 0:
            adj = {
                "final_verdict": "CHANGES_REQUESTED",
                "recommended_next_state": "NEEDS_FIX02_FIX04",
                "provider_capability_status": cap_status,
                "provider_fix_required": False,
                "source_authority_review_required": False,
                "residual_resume_eligible": False,
                "reason_codes": ["UNRESOLVED_AUTHORITY_CONFLICTS_BLOCK_CLOSURE"],
            }
        else:
            adj = adjudicate_adjusted_price_full_population_state(
                population_count=total_count,
                complete_count=closure_complete_count,
                partial_count=partial_count,
                empty_count=empty_count,
                error_count=error_count,
                provider_capability_status=cap_status,
                quality_clean=quality_clean,
                final_resume_passed=False,
            )
        verdict = adj["final_verdict"]
        next_state = adj["recommended_next_state"]

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
                "normal_complete": normal_complete_count,
                "partial": partial_count,
                "empty": empty_count,
                "error": error_count,
                "insufficient_authority": insufficient_auth_count,
                "no_usable_observations": no_usable_count,
                "complete_with_adjudicated_nonusable": adjudicated_complete_count,
                "closure_complete_total": closure_complete_count,
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
                "total_silent_missing_dates": total_silent_missing,
                "total_usable_source_rows": total_usable,
                "total_confirmed_nontrading_dates": total_confirmed_nontrading,
                "total_adjudicated_source_nonusable_dates": total_source_nonusable,
                "total_authority_conflict_dates": total_authority_conflicts,
                "total_resolved_authority_conflict_dates": total_resolved_authority_conflicts,
                "total_unresolved_authority_conflict_dates": total_unresolved_authority_conflicts,
                "total_phantom_rows": total_phantom,
                "total_authority_suppressed_source_rows": total_authority_suppressed,
            },
            "authority_conflict_totals": {
                "total_authority_conflicts": total_authority_conflicts,
                "total_resolved_authority_conflicts": total_resolved_authority_conflicts,
                "total_unresolved_authority_conflicts": total_unresolved_authority_conflicts,
            },
            "data_quality_totals": {
                "total_duplicates": total_duplicates,
                "total_invalid_ohlc": total_invalid_ohlc,
                "total_future_rows": total_future_rows,
                "total_analytic_invalid_ohlc": total_analytic_invalid_ohlc,
            },
            "closure_accounting": {
                "schema_version": CLOSURE_ACCOUNTING_SCHEMA_VERSION,
                "tradability_contract_version": TRADABILITY_CONTRACT_VERSION,
                "states": [state.value for state in ClosureState],
                "normal_complete": normal_complete_count,
                "no_usable_observations": no_usable_count,
                "complete_with_adjudicated_nonusable": adjudicated_complete_count,
                "closure_complete_total": closure_complete_count,
                "unresolved_total": total_count - closure_complete_count,
                "total_authority_conflicts": total_authority_conflicts,
                "resolved_authority_conflict_count": total_resolved_authority_conflicts,
                "unresolved_authority_conflict_count": total_unresolved_authority_conflicts,
                "failure_count": total_count - closure_complete_count,
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
            "source_provider": SOURCE_PROVIDER_VERSION,
            "store_version": "ADJUSTED_PRICE_STORE_V02",
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
            "verified_complete": closure_complete_count,
            "needs_fetch": total_count - closure_complete_count,
            "network_calls_performed": new_live_queries,
            "physical_attempts": physical_attempts,
            "retries": total_retries,
            "reused_without_network": reused_count,
            "updated_at": now_iso,
        }
        execution_audit_path.write_text(json.dumps(execution_audit_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # 6. Resume Audit Record (Dedicated Zero-Call Idempotency Verification)
        all_complete = (closure_complete_count == total_count == EXPECTED_POPULATION_COUNT)
        is_true_resume_pass = (all_complete and new_live_queries == 0 and physical_attempts == 0)
        resume_audit_payload = {
            "schema": "full_population_resume_audit_v01",
            "execution_id": self.execution_id,
            "population_total": total_count,
            "verified_complete": closure_complete_count,
            "needs_fetch": total_count - closure_complete_count,
            "network_calls_performed": new_live_queries if is_true_resume_pass else None,
            "physical_attempts": physical_attempts if is_true_resume_pass else None,
            "retries": total_retries if is_true_resume_pass else None,
            "reused_without_network": reused_count if is_true_resume_pass else None,
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
            "completed_count": closure_complete_count,
            "failure_count": total_count - closure_complete_count,
            "normal_complete_count": normal_complete_count,
            "no_usable_observations_count": no_usable_count,
            "complete_with_adjudicated_nonusable_count": adjudicated_complete_count,
            "total_authority_conflict_count": total_authority_conflicts,
            "resolved_authority_conflict_count": total_resolved_authority_conflicts,
            "unresolved_authority_conflict_count": total_unresolved_authority_conflicts,
            "total_authority_conflicts": total_authority_conflicts,
            "total_resolved_authority_conflicts": total_resolved_authority_conflicts,
            "total_unresolved_authority_conflicts": total_unresolved_authority_conflicts,
        }
        self.closure_manifest_path.write_text(json.dumps(closure_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return summary_payload
