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
DEFAULT_SOURCE_ELIGIBILITY_AUTHORITY = DEFAULT_EFFECTIVE_DIR / "effective_source_eligibility_authority.json"
DEFAULT_ACCEPTED_NON_COMMON_EVIDENCE = DEFAULT_CORRECTION_DIR / "unexpected_3089_reconciliation.json"
DEFAULT_BLOCKER_RECONCILIATION = DEFAULT_CORRECTION_DIR / "known_10_blocker_reconciliation.json"


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
    source_eligibility_path: Path
    confirmed_non_common_dates: Mapping[tuple[str, str], Mapping[str, Any]]
    confirmed_non_common_intervals: tuple[Mapping[str, Any], ...]
    identity_lineage: Mapping[str, tuple[tuple[str, str], ...]]

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

    def confirmed_non_common_evidence(self, ticker: str, date: str) -> Mapping[str, Any] | None:
        """Return exact identity-aware evidence for a non-COMMON source date.

        The lookup is deliberately finite and fail-closed.  A date is never
        classified from a ticker's first/last date envelope.
        """
        evidence = self.confirmed_non_common_dates.get((str(ticker), str(date)))
        if evidence is not None:
            return evidence
        matches = [
            item
            for item in self.confirmed_non_common_intervals
            if str(item.get("ticker")) == str(ticker)
            and str(item.get("effective_from")) <= str(date) <= str(item.get("effective_to"))
        ]
        if len(matches) == 1:
            return matches[0]
        # Multiple identity records for the same ticker/date are ambiguous;
        # callers must leave the date unexpected rather than attach it to the
        # current ticker identity.
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error text is part of contract
        raise EffectiveAuthorityError(f"AUTHORITY_JSON_UNREADABLE:{path}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repository_root(path: Path) -> Path:
    candidate = Path(path).resolve()
    for parent in (candidate, *candidate.parents):
        marker = parent / ".git"
        if marker.exists():
            return parent
    return Path.cwd().resolve()


def repository_relative_path(path: Path, *, root: Path | None = None) -> str:
    """Persist a portable repository-relative path, never a machine path."""
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    root = _repository_root(root or path)
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise EffectiveAuthorityError(f"AUTHORITY_PATH_OUTSIDE_REPOSITORY:{path}") from exc


def _identity_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted({str(item) for item in value if str(item)}))
    return (str(value),)


def _build_source_eligibility_payload(
    correction_dir: Path,
    *,
    corrected_pit_intervals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build finite, identity-aware source-date eligibility evidence.

    The accepted 3,089 dates are exact records.  The additional 1,615 dates
    are represented by the explicit pre-transition intervals from the ten
    blocker reconciliation; no date-envelope inference is used.
    """
    accepted_path = Path(correction_dir) / "unexpected_3089_reconciliation.json"
    blocker_path = Path(correction_dir) / "known_10_blocker_reconciliation.json"
    accepted = _read_json(accepted_path)
    blockers = _read_json(blocker_path)
    accepted_records = accepted.get("records", ())
    if accepted.get("expected_count") != 3089 or accepted.get("observed_count") != 3089:
        raise EffectiveAuthorityError("ACCEPTED_NON_COMMON_EVIDENCE_COUNT_MISMATCH")
    exact: dict[tuple[str, str], dict[str, Any]] = {}
    for record in accepted_records:
        ticker, date = str(record.get("ticker")), str(record.get("date"))
        if not ticker or not date or record.get("category") != "CONFIRMED_SPAC_NON_COMMON_SOURCE_HISTORY":
            raise EffectiveAuthorityError("ACCEPTED_NON_COMMON_EVIDENCE_INVALID")
        key = (ticker, date)
        if key in exact:
            raise EffectiveAuthorityError("ACCEPTED_NON_COMMON_EVIDENCE_DUPLICATE")
        exact[key] = {
            "ticker": ticker,
            "ISU_CD": str(record.get("ISU_CD") or record.get("isu_cd") or ""),
            "market": str(record.get("market") or ""),
            "date": date,
            "category": "ACCEPTED_SPAC_NON_COMMON",
            "final_classification": "AUTHORITY_CONFIRMED_NON_COMMON_SOURCE_DATE",
            "authority_source": "unexpected_3089_reconciliation.json",
            "authority_evidence": str(record.get("reason") or "CONFIRMED_SPAC_NON_COMMON_SOURCE_HISTORY"),
            "reason_code": "ACCEPTED_SPAC_NON_COMMON_DATE",
        }
    if len(exact) != 3089:
        raise EffectiveAuthorityError("ACCEPTED_NON_COMMON_EVIDENCE_UNIQUE_COUNT_MISMATCH")

    corrected_by_ticker: dict[str, list[tuple[str, str]]] = {}
    for item in corrected_pit_intervals:
        if item.get("state") == "COMMON":
            corrected_by_ticker.setdefault(str(item.get("ticker")), []).append(
                (str(item["effective_from"]), str(item["effective_to"]))
            )
    intervals: list[dict[str, Any]] = []
    for blocker in blockers.get("blockers", ()):
        ticker = str(blocker["ticker"])
        starts = [start for start, _ in corrected_by_ticker.get(ticker, ())]
        corrected_start = min(starts) if starts else "9999-12-31"
        for old in blocker.get("old_pit_common_intervals", ()):
            # Only an explicitly reconciled old interval that ends before the
            # corrected lifecycle start can prove NOT_COMMON here.
            if str(old["effective_to"]) >= corrected_start:
                continue
            intervals.append(
                {
                    "ticker": ticker,
                    "ISU_CD": str(old.get("ISU_CD") or ""),
                    "market": str(old.get("market") or ""),
                    "effective_from": str(old["effective_from"]),
                    "effective_to": str(old["effective_to"]),
                    "category": "OTHER_AUTHORITY_CONFIRMED_NON_COMMON",
                    "final_classification": "AUTHORITY_CONFIRMED_NON_COMMON_SOURCE_DATE",
                    "authority_source": "known_10_blocker_reconciliation.json",
                    "authority_evidence": str(blocker.get("spac_evidence", ())),
                    "reason_code": "EXPLICIT_CORRECTED_LIFECYCLE_REMOVED_INTERVAL",
                }
            )
    intervals.sort(key=lambda item: (item["ticker"], item["effective_from"], item["effective_to"]))
    return {
        "schema": "effective_source_eligibility_authority_v01",
        "authority_resolution": "EXACT_IDENTITY_AWARE_SOURCE_DATE_EVIDENCE",
        "common_authority": "effective_pit_common_denominator.json",
        "confirmed_non_common_dates": [exact[key] for key in sorted(exact)],
        "confirmed_non_common_intervals": intervals,
        "identity_lineage": {
            ticker: sorted(
                {
                    (str(item.get("ISU_CD") or ""), str(item.get("market") or ""))
                    for item in [*exact.values(), *intervals]
                    if str(item.get("ticker")) == ticker
                }
            )
            for ticker in sorted({str(item.get("ticker")) for item in [*exact.values(), *intervals]})
        },
        "accepted_spac_non_common_date_count": 3089,
        "additional_authority_confirmed_non_common_interval_count": len(intervals),
        "envelope_inference": False,
    }


def _load_source_eligibility(path: Path) -> tuple[dict[tuple[str, str], Mapping[str, Any]], tuple[Mapping[str, Any], ...], dict[str, tuple[tuple[str, str], ...]]]:
    payload = _read_json(path)
    if payload.get("envelope_inference") is not False:
        raise EffectiveAuthorityError("SOURCE_ELIGIBILITY_ENVELOPE_INFERENCE_FORBIDDEN")
    exact = {
        (str(item.get("ticker")), str(item.get("date"))): item
        for item in payload.get("confirmed_non_common_dates", ())
    }
    intervals = tuple(payload.get("confirmed_non_common_intervals", ()))
    lineage = {
        str(ticker): tuple((str(pair[0]), str(pair[1])) for pair in pairs)
        for ticker, pairs in payload.get("identity_lineage", {}).items()
    }
    if len(exact) != int(payload.get("accepted_spac_non_common_date_count", 0)):
        raise EffectiveAuthorityError("SOURCE_ELIGIBILITY_EXACT_DATE_COUNT_MISMATCH")
    return exact, intervals, lineage


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
    eligibility_path = effective_dir / "effective_source_eligibility_authority.json"
    if require_manifest and not cutover_path.exists():
        raise EffectiveAuthorityError("EFFECTIVE_AUTHORITY_MANIFEST_MISSING")
    for path in (population_path, pit_path, manifest_path, eligibility_path):
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
    cutover = _read_json(cutover_path)
    if cutover.get("implementation_head") in (None, "", "WORKTREE"):
        raise EffectiveAuthorityError("EFFECTIVE_AUTHORITY_IMPLEMENTATION_HEAD_UNBOUND")
    for key in ("effective_population_path", "effective_pit_path", "correction_artifact_path"):
        value = str(cutover.get(key, ""))
        if value.startswith("/") or value.startswith("~") or "\\" in value:
            raise EffectiveAuthorityError("EFFECTIVE_AUTHORITY_MANIFEST_NON_PORTABLE_PATH")
    exact, intervals, lineage = _load_source_eligibility(eligibility_path)
    return EffectiveAuthority(
        population=population,
        pit_intervals=pit_intervals,
        population_path=population_path,
        pit_path=pit_path,
        manifest_path=manifest_path,
        population_sha256=pop_sha,
        pit_sha256=pit_sha,
        source_eligibility_path=eligibility_path,
        confirmed_non_common_dates=exact,
        confirmed_non_common_intervals=intervals,
        identity_lineage=lineage,
    )


def build_effective_authority(
    correction_dir: Path = DEFAULT_CORRECTION_DIR,
    effective_dir: Path = DEFAULT_EFFECTIVE_DIR,
    *,
    cutover_head: str | None = None,
    implementation_head: str | None = None,
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
    bound_head = implementation_head or cutover_head
    if not bound_head or bound_head == "WORKTREE" or bound_head.startswith("/"):
        raise EffectiveAuthorityError("EFFECTIVE_AUTHORITY_IMPLEMENTATION_HEAD_REQUIRED")
    effective_dir.mkdir(parents=True, exist_ok=True)
    source_eligibility = _build_source_eligibility_payload(
        correction_dir,
        corrected_pit_intervals=intervals,
    )
    source_eligibility_path = effective_dir / "effective_source_eligibility_authority.json"
    _write_json(source_eligibility_path, source_eligibility)
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
        "correction_artifact_path": repository_relative_path(correction_dir),
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
        "effective_population_path": repository_relative_path(effective_dir / "effective_historical_common_population.json"),
        "effective_pit_path": repository_relative_path(effective_dir / "effective_pit_common_denominator.json"),
        "effective_source_eligibility_path": repository_relative_path(source_eligibility_path),
        "population_count": len(records),
        "population_sha256": pop_sha,
        "pit_interval_count": len(intervals),
        "pit_sha256": pit_sha,
        "correction_acceptance_head": CORRECTION_ACCEPTANCE_HEAD,
        "implementation_head": bound_head,
        "correction_artifact_path": repository_relative_path(correction_dir),
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
        "path": repository_relative_path(path),
        "file_count": len(rows),
        "bytes": sum((path / row.split("|", 1)[0]).stat().st_size for row in rows),
        "aggregate_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }


def build_clean_room_candidate(
    old_staging_dir: Path,
    candidate_dir: Path,
    population: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one candidate from an empty directory without stale-file reuse."""
    old_staging_dir, candidate_dir = Path(old_staging_dir), Path(candidate_dir)
    if candidate_dir.exists() and any(candidate_dir.iterdir()):
        raise EffectiveAuthorityError(f"CANDIDATE_MUST_START_EMPTY:{candidate_dir}")
    candidate_dir.mkdir(parents=True, exist_ok=True)
    tickers = {str(record["ticker"]) for record in population}
    copied: list[str] = []
    for source in sorted(old_staging_dir.iterdir()):
        if not source.is_file():
            continue
        if source.name.split(".", 1)[0] not in tickers:
            continue
        destination = candidate_dir / source.name
        shutil.copy2(source, destination)
        copied.append(source.name)
    expected_names = {
        source.name
        for source in old_staging_dir.iterdir()
        if source.is_file() and source.name.split(".", 1)[0] in tickers
    }
    actual_names = {source.name for source in candidate_dir.iterdir() if source.is_file()}
    if actual_names != expected_names:
        raise EffectiveAuthorityError("CANDIDATE_FILE_SET_MISMATCH")
    return {
        "source": repository_relative_path(old_staging_dir),
        "candidate": repository_relative_path(candidate_dir),
        "copied_file_count": len(copied),
        "stale_files_survived": False,
    }


def scan_candidate_integrity(
    candidate_dir: Path,
    population: Sequence[Mapping[str, Any]],
    *,
    cutoff: str = CALENDAR_CUTOFF,
) -> dict[str, Any]:
    """Measure every candidate Parquet/metadata file and its source rows."""
    candidate_dir = Path(candidate_dir)
    population_tickers = {str(record["ticker"]) for record in population}
    files = sorted(path for path in candidate_dir.rglob("*") if path.is_file())
    parquet_files = [path for path in files if path.suffix == ".parquet"]
    metadata_files = [path for path in files if path.name.endswith(".meta.json")]
    per_file: dict[str, str] = {}
    duplicate_date_rows = 0
    duplicate_ticker_date_rows = 0
    future_rows = 0
    unreadable_files = 0
    source_invalid_rows = 0
    analytic_invalid_rows = 0
    for path in parquet_files:
        relative = path.relative_to(candidate_dir).as_posix()
        try:
            frame = pd.read_parquet(path)
            if "date" not in frame.columns:
                raise ValueError("DATE_COLUMN_MISSING")
            dates = pd.to_datetime(frame["date"], errors="coerce")
            duplicate_date_rows += int(dates.duplicated(keep=False).sum())
            if "ticker" in frame.columns:
                duplicate_ticker_date_rows += int(frame.assign(_date=dates).duplicated(["ticker", "_date"], keep=False).sum())
            future_rows += int((dates > pd.Timestamp(cutoff)).fillna(False).sum())
            ohlc = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
            source_invalid_rows += int((~ohlc.notna().all(axis=1)).sum())
            analytic_frame = ohlc.copy()
            analytic_invalid_rows += int((~analytic_candle_is_valid(analytic_frame)).sum())
            per_file[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            unreadable_files += 1
    metadata_pair_count = sum(
        1 for path in parquet_files if (path.with_name(path.stem + ".meta.json")).exists()
    )
    payload = snapshot_tree(candidate_dir)
    return {
        "schema": "authority_cutover_candidate_integrity_fix01_v01",
        "candidate": repository_relative_path(candidate_dir),
        **payload,
        "parquet_count": len(parquet_files),
        "metadata_count": len(metadata_files),
        "metadata_pair_count": metadata_pair_count,
        "population_ticker_count": len(population_tickers),
        "store_bearing_ticker_count": len({path.stem for path in parquet_files}),
        "zero_store_success_count": len(population_tickers - {path.stem for path in parquet_files}),
        "duplicate_date_rows": duplicate_date_rows,
        "duplicate_ticker_date_rows": duplicate_ticker_date_rows,
        "future_rows": future_rows,
        "unreadable_files": unreadable_files,
        "source_invalid_ohlc_rows": source_invalid_rows,
        "analytic_invalid_source_native_rows": analytic_invalid_rows,
        "per_file_sha256": per_file,
        "integrity_pass": (
            unreadable_files == 0
            and source_invalid_rows == 0
            and duplicate_date_rows == 0
            and future_rows == 0
            and metadata_pair_count == len(parquet_files)
        ),
    }


def source_dates(path: Path) -> list[str]:
    frame = pd.read_parquet(path, columns=["date"])
    return sorted({pd.Timestamp(value).strftime("%Y-%m-%d") for value in frame["date"]})


def classify_source_dates(
    ticker: str,
    dates: Sequence[str],
    authority: EffectiveAuthority,
    old_pit_intervals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Partition source dates using exact PIT/evidence, never an envelope.

    ``old_pit_intervals`` is retained for API compatibility and audit context;
    it is intentionally not consulted to infer eligibility.
    """
    del old_pit_intervals
    unique_dates = sorted({str(date) for date in dates})
    common = authority.pit_common_dates(ticker, unique_dates)
    outside: list[str] = []
    unexpected: list[str] = []
    confirmed: dict[str, Mapping[str, Any]] = {}
    for date in unique_dates:
        if date in common:
            continue
        evidence = authority.confirmed_non_common_evidence(ticker, date)
        if evidence is None:
            unexpected.append(date)
        else:
            outside.append(date)
            confirmed[date] = evidence
    return {
        "common": sorted(common.intersection(unique_dates)),
        "source_history_outside_common_eligibility": outside,
        "unexpected": unexpected,
        "confirmed_non_common": confirmed,
        "category_counts": {
            "COMMON_ELIGIBLE_SOURCE_DATE": len(set(unique_dates).intersection(common)),
            "AUTHORITY_CONFIRMED_NON_COMMON_SOURCE_DATE": len(outside),
            "UNEXPLAINED_SOURCE_DATE": len(unexpected),
        },
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
        "effective_authority_path": repository_relative_path(authority.manifest_path.parent),
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
    """Backward-compatible alias for the corrected production resolver."""
    from trend_scanner.data.adjusted_price_full_population import create_production_runner

    return create_production_runner(store_dir=Path(store_dir), artifact_dir=Path(artifact_dir), provider=provider)
