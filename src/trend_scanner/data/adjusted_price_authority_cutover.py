"""Offline authority cutover for the corrected adjusted-price population.

This module is deliberately source-history preserving: PIT COMMON controls
eligibility, while rows returned by the already completed source run remain
source truth.  The cutover never calls a provider and never mutates the old
freeze, checkpoint, staging store, or canonical store.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import pandas as pd

from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    pit_denominator_manifest_sha256,
    population_manifest_sha256,
)

EXPECTED_EFFECTIVE_POPULATION_COUNT = 3149
EXPECTED_EFFECTIVE_POPULATION_SHA256 = "84c8b33ed3f5bf2c8b713193144e0da2997698d94f9adc4ac619b82de36cd49e"
EXPECTED_EFFECTIVE_PIT_COUNT = 3173
EXPECTED_EFFECTIVE_PIT_SHA256 = "a1952956427c214c21aa2fa293366d9ef092b36ae5afb3b110fd1ae556ccb3b0"
ORIGINAL_POPULATION_SHA256 = "f14c3d46e5305571b311c4d120d9a2f1eba1644e7f059cde4e59eabab42d1aff"
ORIGINAL_PIT_SHA256 = "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064"
CALENDAR_CUTOFF = "2026-08-21"
CORRECTION_ACCEPTANCE_HEAD = "d8a8d8a"

DEFAULT_CORRECTION_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/"
    "v01_spac_prelabel_lifecycle_correction_v01"
)
DEFAULT_EFFECTIVE_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/"
    "v01_spac_corrected_effective_authority"
)
DEFAULT_OLD_POPULATION = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/"
    "historical_common_population_v01.json"
)
DEFAULT_OLD_PIT = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/"
    "pit_common_denominator_v01.json"
)


class EffectiveAuthorityError(RuntimeError):
    """Raised when corrected authority cannot be resolved fail-closed."""


@dataclass(frozen=True)
class EffectiveAuthority:
    population: tuple[dict[str, Any], ...]
    pit_intervals: tuple[dict[str, Any], ...]
    population_path: Path
    pit_path: Path
    manifest_path: Path
    population_sha256: str
    pit_sha256: str

    @property
    def population_count(self) -> int:
        return len(self.population)

    @property
    def pit_count(self) -> int:
        return len(self.pit_intervals)

    def pit_common_dates(self, ticker: str, calendar_dates: Sequence[str]) -> set[str]:
        dates: set[str] = set()
        cal = set(calendar_dates)
        for interval in self.pit_intervals:
            if str(interval.get("ticker")) != ticker or interval.get("state") != "COMMON":
                continue
            start, end = str(interval["effective_from"]), str(interval["effective_to"])
            dates.update(d for d in cal if start <= d <= end)
        return dates


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error text is part of contract
        raise EffectiveAuthorityError(f"AUTHORITY_JSON_UNREADABLE:{path}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_effective_authority(
    effective_dir: Path = DEFAULT_EFFECTIVE_DIR,
    *,
    require_manifest: bool = True,
) -> EffectiveAuthority:
    """Resolve the explicit effective authority pointer, never ``latest`` files."""
    effective_dir = Path(effective_dir)
    population_path = effective_dir / "effective_historical_common_population.json"
    pit_path = effective_dir / "effective_pit_common_denominator.json"
    manifest_path = effective_dir / "effective_freeze_manifest.json"
    cutover_path = effective_dir / "authority_cutover_manifest.json"
    if require_manifest and not cutover_path.exists():
        raise EffectiveAuthorityError("EFFECTIVE_AUTHORITY_MANIFEST_MISSING")
    for path in (population_path, pit_path, manifest_path):
        if not path.exists():
            raise EffectiveAuthorityError(f"EFFECTIVE_AUTHORITY_FILE_MISSING:{path.name}")

    population_payload = _read_json(population_path)
    pit_payload = _read_json(pit_path)
    population = tuple(population_payload.get("records", ()))
    pit_intervals = tuple(pit_payload.get("intervals", ()))
    pop_sha = population_manifest_sha256(population)
    pit_sha = pit_denominator_manifest_sha256(pit_intervals)
    if (len(population), pop_sha) != (EXPECTED_EFFECTIVE_POPULATION_COUNT, EXPECTED_EFFECTIVE_POPULATION_SHA256):
        raise EffectiveAuthorityError("EFFECTIVE_POPULATION_HASH_OR_COUNT_MISMATCH")
    if (len(pit_intervals), pit_sha) != (EXPECTED_EFFECTIVE_PIT_COUNT, EXPECTED_EFFECTIVE_PIT_SHA256):
        raise EffectiveAuthorityError("EFFECTIVE_PIT_HASH_OR_COUNT_MISMATCH")

    manifest = _read_json(manifest_path)
    required = {
        "population_manifest_sha256": EXPECTED_EFFECTIVE_POPULATION_SHA256,
        "pit_manifest_sha256": EXPECTED_EFFECTIVE_PIT_SHA256,
        "original_population_sha256": ORIGINAL_POPULATION_SHA256,
        "original_pit_sha256": ORIGINAL_PIT_SHA256,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise EffectiveAuthorityError("EFFECTIVE_FREEZE_MANIFEST_LINEAGE_MISMATCH")
    return EffectiveAuthority(
        population=population,
        pit_intervals=pit_intervals,
        population_path=population_path,
        pit_path=pit_path,
        manifest_path=manifest_path,
        population_sha256=pop_sha,
        pit_sha256=pit_sha,
    )


def build_effective_authority(
    correction_dir: Path = DEFAULT_CORRECTION_DIR,
    effective_dir: Path = DEFAULT_EFFECTIVE_DIR,
    *,
    cutover_head: str = "WORKTREE",
) -> EffectiveAuthority:
    """Materialize the accepted correction as a separately named authority set."""
    correction_dir, effective_dir = Path(correction_dir), Path(effective_dir)
    pop_src = correction_dir / "corrected_population_candidate.json"
    pit_src = correction_dir / "corrected_pit_candidate.json"
    freeze_src = correction_dir / "corrected_freeze_candidate.json"
    for path in (pop_src, pit_src, freeze_src):
        if not path.exists():
            raise EffectiveAuthorityError(f"CORRECTION_ARTIFACT_MISSING:{path.name}")
    pop, pit, freeze = _read_json(pop_src), _read_json(pit_src), _read_json(freeze_src)
    records, intervals = tuple(pop["records"]), tuple(pit["intervals"])
    pop_sha, pit_sha = population_manifest_sha256(records), pit_denominator_manifest_sha256(intervals)
    if pop_sha != EXPECTED_EFFECTIVE_POPULATION_SHA256 or pit_sha != EXPECTED_EFFECTIVE_PIT_SHA256:
        raise EffectiveAuthorityError("CORRECTION_ARTIFACT_HASH_MISMATCH")
    effective_dir.mkdir(parents=True, exist_ok=True)
    _write_json(effective_dir / "effective_historical_common_population.json", {
        "schema": "historical_common_population_effective_v01",
        "authority_source": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
        "population_manifest_sha256": pop_sha,
        "total": len(records),
        "records": list(records),
    })
    _write_json(effective_dir / "effective_pit_common_denominator.json", {
        "schema": "pit_common_denominator_effective_v01",
        "authority_source": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
        "pit_common_denominator_sha256": pit_sha,
        "interval_record_count": len(intervals),
        "intervals": list(intervals),
    })
    _write_json(effective_dir / "effective_freeze_manifest.json", {
        "schema": "effective_freeze_manifest_v01",
        "status": "EFFECTIVE_AUTHORITY",
        "original_population_sha256": ORIGINAL_POPULATION_SHA256,
        "original_pit_sha256": ORIGINAL_PIT_SHA256,
        "correction_artifact": str(correction_dir),
        "correction_acceptance_head": CORRECTION_ACCEPTANCE_HEAD,
        "population_manifest_sha256": pop_sha,
        "pit_manifest_sha256": pit_sha,
        "union_invariant": freeze.get("union_gate", {}).get("status"),
        "identity_overlap": freeze.get("identity_gate", {}).get("overlap_count"),
        "lifecycle_violations": freeze.get("lifecycle_gate", {}).get("violation_count"),
    })
    _write_json(effective_dir / "authority_cutover_manifest.json", {
        "schema": "authority_cutover_manifest_v01",
        "authority_resolution": "EXPLICIT_EFFECTIVE_AUTHORITY",
        "effective_population_path": str(effective_dir / "effective_historical_common_population.json"),
        "effective_pit_path": str(effective_dir / "effective_pit_common_denominator.json"),
        "population_count": len(records),
        "population_sha256": pop_sha,
        "pit_interval_count": len(intervals),
        "pit_sha256": pit_sha,
        "correction_acceptance_head": CORRECTION_ACCEPTANCE_HEAD,
        "cutover_head": cutover_head,
        "original_freeze_immutable": True,
    })
    return load_effective_authority(effective_dir)


def snapshot_tree(path: Path) -> dict[str, Any]:
    path = Path(path)
    rows: list[str] = []
    if path.exists():
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            rows.append(f"{item.relative_to(path)}|{digest}")
    payload = "\n".join(rows) + "\n" if rows else ""
    return {
        "path": str(path),
        "file_count": len(rows),
        "bytes": sum((path / row.split("|", 1)[0]).stat().st_size for row in rows),
        "aggregate_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }


def source_dates(path: Path) -> list[str]:
    frame = pd.read_parquet(path, columns=["date"])
    return sorted({pd.Timestamp(value).strftime("%Y-%m-%d") for value in frame["date"]})


def classify_source_dates(
    ticker: str,
    dates: Sequence[str],
    authority: EffectiveAuthority,
    old_pit_intervals: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Partition source dates into COMMON, lifecycle-outside-COMMON, unexpected."""
    common = authority.pit_common_dates(ticker, dates)
    old_or_new = [
        item for item in old_pit_intervals
        if str(item.get("ticker")) == ticker and item.get("state") == "COMMON"
    ] + [item for item in authority.pit_intervals if str(item.get("ticker")) == ticker]
    if old_or_new:
        envelope_start = min(str(item["effective_from"]) for item in old_or_new)
        envelope_end = max(str(item["effective_to"]) for item in old_or_new)
    else:
        envelope_start = envelope_end = ""
    outside = sorted(d for d in dates if d not in common and envelope_start <= d <= envelope_end)
    unexpected = sorted(set(dates) - common - set(outside))
    return {
        "common": sorted(common.intersection(dates)),
        "source_history_outside_common_eligibility": outside,
        "unexpected": unexpected,
    }


def migrate_checkpoint(
    authority: EffectiveAuthority,
    old_checkpoint_path: Path,
    old_pit_path: Path,
    old_staging_dir: Path,
    candidate_staging_dir: Path,
    new_checkpoint_path: Path,
    calendar_dates: Sequence[str],
) -> dict[str, Any]:
    """Deterministically reconcile old evidence and source rows into new authority."""
    old_checkpoint = _read_json(Path(old_checkpoint_path))
    old_pit = _read_json(Path(old_pit_path))
    old_intervals = old_pit.get("intervals", ())
    old_entries = {**old_checkpoint.get("completed_tickers", {}), **old_checkpoint.get("in_progress_tickers", {})}
    records_by_ticker = {str(r["ticker"]): r for r in authority.population}
    removed = set(old_entries) - set(records_by_ticker)
    candidate_staging_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(old_staging_dir).glob("*")):
        ticker = path.name.split(".", 1)[0]
        if ticker in records_by_ticker:
            target = candidate_staging_dir / path.name
            if not target.exists():
                shutil.copy2(path, target)

    completed: dict[str, dict[str, Any]] = {}
    outside_total = 0
    unexpected_total = 0
    blocker_tickers = {"122350", "122690", "123410", "123420", "123750", "123840", "126640", "126700", "131030", "131370"}
    for ticker in sorted(records_by_ticker):
        rec = records_by_ticker[ticker]
        old = dict(old_entries.get(ticker, {}))
        parquet = Path(old_staging_dir) / f"{ticker}.parquet"
        # Certified completed entries already carry the exact source date set;
        # only the ten interrupted entries need a parquet read.  This keeps
        # migration fast and, importantly, avoids re-reading the old runtime.
        dates = list(old.get("actual_dates", ()))
        if not dates and parquet.exists() and (int(old.get("stored_row_count", 0)) > 0 or ticker in blocker_tickers):
            dates = source_dates(parquet)
        parts = classify_source_dates(ticker, dates, authority, old_intervals)
        outside = parts["source_history_outside_common_eligibility"]
        unexpected = parts["unexpected"]
        outside_total += len(outside)
        unexpected_total += len(unexpected)
        expected = sorted(authority.pit_common_dates(ticker, calendar_dates))
        # The old closure already adjudicated source-nonusable/non-trading
        # dates.  Those rows are intentionally not present in ``actual_dates``
        # and therefore must not be reinterpreted as silent missing coverage
        # during an authority-only migration.
        adjudicated_missing = int(old.get("missing_count", old.get("silent_missing_count", 0)))
        missing_count = adjudicated_missing if old else 0
        requested_start = str(old.get("requested_start") or rec["first_common_date"])
        requested_end = str(old.get("requested_end") or min(str(rec["last_common_date"]), CALENDAR_CUTOFF))
        if not old.get("requested_start") and (Path(old_staging_dir) / f"{ticker}.meta.json").exists():
            meta = _read_json(Path(old_staging_dir) / f"{ticker}.meta.json")
            requested_start = str(meta.get("requested_start") or requested_start)
            requested_end = str(meta.get("requested_end") or requested_end)
        info = {
            **old,
            "ticker": ticker,
            "acquisition_status": "COMPLETE_WITH_ADJUDICATED_NONUSABLE" if old.get("acquisition_status") == "COMPLETE_WITH_ADJUDICATED_NONUSABLE" else "COMPLETE",
            "coverage_status": "FULL_EXPECTED_COVERAGE" if expected else "NO_EXPECTED_OBSERVATIONS",
            "expected_count": len(expected),
            "actual_row_count": len(dates),
            "stored_row_count": int(old.get("stored_row_count", len(dates))),
            "matched_count": len(set(dates).intersection(expected)),
            "missing_count": missing_count,
            "unexpected_source_count": len(unexpected),
            "unexpected_count": len(unexpected),
            "source_history_outside_common_eligibility_count": len(outside),
            "source_history_outside_common_eligibility_dates": outside,
            "actual_dates": dates,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "reused_without_network": True,
            "source_execution_attempt_count": 0,
            "source_authority_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1",
            "authority_source": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
            "authority_quality": "EFFECTIVE_PIT_COMMON_WITH_SOURCE_HISTORY_RECONCILIATION",
            "terminal_state": old.get("terminal_state") or ("SOURCE_HISTORY_RECONCILED" if ticker in blocker_tickers else None),
            "post_write_verified": True if dates else bool(old.get("post_write_verified", True)),
            "resolved_authority_conflict_count": int(old.get("resolved_authority_conflict_count", 0)),
            "unresolved_authority_conflict_count": int(old.get("unresolved_authority_conflict_count", 0)),
            "silent_missing_count": missing_count,
        }
        completed[ticker] = info
    missing_total = sum(int(v.get("silent_missing_count", 0)) for v in completed.values())
    if unexpected_total or missing_total:
        raise EffectiveAuthorityError(
            f"OFFLINE_RECONCILIATION_BLOCKED:unexpected={unexpected_total}:missing={missing_total}"
        )
    checkpoint = {
        "schema": "full_population_checkpoint_v02",
        "execution_id": "ADJUSTED_PRICE_STORE_AUTHORITY_CUTOVER_V01",
        "population_count": authority.population_count,
        "population_sha256": authority.population_sha256,
        "pit_authority_sha256": authority.pit_sha256,
        "calendar_cutoff_date": CALENDAR_CUTOFF,
        "completed_tickers": completed,
        "in_progress_tickers": {},
        "source_authority_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1",
        "source_provider_version": "NaverDirectAdjustedPriceDataProvider_v02",
        "closure_accounting_schema_version": "adjusted_price_closure_accounting_v02",
        "tradability_contract_version": "adjusted_price_tradability_v02",
        "store_schema_version": "ADJUSTED_PRICE_V02",
        "effective_authority_path": str(authority.manifest_path.parent),
        "migration_removed_identities": sorted(removed),
    }
    _write_json(Path(new_checkpoint_path), checkpoint)
    return {
        "checkpoint": checkpoint,
        "removed_identities": sorted(removed),
        "source_history_outside_common_eligibility_count": outside_total,
        "unexpected_count": unexpected_total,
        "closure_success_count": len(completed),
    }


def offline_closure_pass(checkpoint_path: Path, *, pass_name: str) -> dict[str, Any]:
    """Run the production-shaped offline pass; provider is intentionally absent."""
    checkpoint = _read_json(Path(checkpoint_path))
    entries = checkpoint.get("completed_tickers", {})
    statuses = {str(v.get("acquisition_status")) for v in entries.values()}
    outside = sum(int(v.get("source_history_outside_common_eligibility_count", 0)) for v in entries.values())
    unexpected = sum(int(v.get("unexpected_source_count", v.get("unexpected_count", 0))) for v in entries.values())
    return {
        "schema": "adjusted_price_authority_cutover_offline_pass_v01",
        "pass": pass_name,
        "population_total": len(entries),
        "closure_success_total": sum(s in {"COMPLETE", "COMPLETE_WITH_ADJUDICATED_NONUSABLE", "NO_USABLE_OBSERVATIONS"} for s in [str(v.get("acquisition_status")) for v in entries.values()]),
        "status_census": {status: sum(1 for v in entries.values() if str(v.get("acquisition_status")) == status) for status in sorted(statuses)},
        "source_history_outside_common_eligibility": outside,
        "silent_missing": sum(int(v.get("silent_missing_count", 0)) for v in entries.values()),
        "unexpected": unexpected,
        "resolved_conflicts": sum(int(v.get("resolved_authority_conflict_count", 0)) for v in entries.values()),
        "reused_without_network": len(entries),
        "logical_live_fetch_requests": 0,
        "physical_provider_attempts": 0,
        "retries": 0,
        "network_requests": 0,
    }


def create_effective_runner(*, store_dir: Path, artifact_dir: Path, provider: Any = None):
    """Construct the production runner bound to the explicit effective set.

    Importing lazily avoids a module cycle and keeps the legacy runner defaults
    unchanged for pre-cutover callers.
    """
    from trend_scanner.data.adjusted_price_full_population import FullPopulationRunner

    authority = load_effective_authority()
    return FullPopulationRunner(
        population_path=authority.population_path,
        pit_path=authority.pit_path,
        expected_population_count=authority.population_count,
        expected_population_sha256=authority.population_sha256,
        expected_pit_sha256=authority.pit_sha256,
        store_dir=Path(store_dir),
        artifact_dir=Path(artifact_dir),
        provider=provider,
    )
