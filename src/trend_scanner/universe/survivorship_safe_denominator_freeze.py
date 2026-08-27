"""Survivorship-safe historical denominator freeze (SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01).

Freezes two separate canonical contracts from the full KRX PIT Basic Info
authority (+ supplemental authority), never merged into one ticker list:

  A. Population Universe — every identity that was COMMON at least once,
     anywhere in the frozen historical period (2010-01-04..2026-08-21).
     Used by population-level consumers (AdjustedPriceStore population
     target, historical coverage denominators).

  B. Point-In-Time (PIT) Common Denominator — for each historical trading
     date, the identities that were actually COMMON *on that date*. Used by
     survivorship-safe backtests and date-specific market statistics
     (breadth, advance/decline, new-high/new-low).

Both are derived from a single walk over the full authority
(``classify_full_universe`` in ``historical_authority_reconciliation``), not
from two independent computations and not from arithmetic over separately
known counts — see docs/architecture/survivorship_safe_denominator_freeze_v01.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence

from trend_scanner.data.krx_historical_instrument_acquisition import load_historical_trading_calendar
from trend_scanner.universe.historical_authority_reconciliation import (
    CLASS_COMMON,
    CLASS_NOT_COMMON,
    DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    DEFAULT_CALENDAR_PATH,
    DEFAULT_RAW_ROOT,
    DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR,
    DEFAULT_TARGET_IDENTITY_PATH,
    classify_full_universe,
    load_basic_info_snapshots,
    load_supplemental_authority_records,
    load_target_identities,
    reconcile_target_identities,
)


_ARTIFACTS = Path("artifacts")
_FREEZE_DIR = (
    _ARTIFACTS
    / "data/end_to_end_data_parity/v01/"
    / "survivorship_safe_denominator_freeze/v01"
)
DEFAULT_POPULATION_ARTIFACT_PATH = _FREEZE_DIR / "historical_common_population_v01.json"
DEFAULT_PIT_ARTIFACT_PATH = _FREEZE_DIR / "pit_common_denominator_v01.json"
DEFAULT_CLOSURE_ARTIFACT_PATH = _FREEZE_DIR / "survivorship_safe_denominator_freeze_v01.json"

FREEZE_STATUS_CLOSED_AND_FROZEN = "CLOSED_AND_FROZEN"
FREEZE_STATUS_BLOCKED = "BLOCKED"

AUTHORITY_SOURCE = "TIER_A_KRX_OPEN_API_BASIC_INFO"
EXPECTED_HISTORICAL_START = "2010-01-04"
EXPECTED_HISTORICAL_END = "2026-08-21"
EXPECTED_TRADING_DATE_COUNT = 4095
EXPECTED_HISTORICAL_ONLY_COUNTS = {"COMMON_REQUIRED": 605, "NOT_COMMON": 511, "UNRESOLVED": 0}


class FreezeContractError(RuntimeError):
    """Fail-closed contract error for the denominator freeze."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _numeric_or_alpha(ticker: str) -> str:
    return "numeric" if ticker.isdigit() else "alphanumeric"


def derive_population_and_pit_records(
    full_universe: Mapping[str, list[dict[str, Any]]],
    *,
    last_trading_date: str = EXPECTED_HISTORICAL_END,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Single walk over ``classify_full_universe`` output producing both the
    Population Universe records and the PIT COMMON interval records together.

    Deriving these from one shared walk (rather than two separate
    computations) is what makes the union invariant
    (``evaluate_population_pit_union_invariant``) a real property instead of
    a test of two code paths happening to agree.
    """

    population: list[dict[str, Any]] = []
    pit_intervals: list[dict[str, Any]] = []

    for ticker, intervals in full_universe.items():
        common_intervals = [iv for iv in intervals if iv["classification"] == CLASS_COMMON]
        if not common_intervals:
            continue

        states = {iv["classification"] for iv in intervals}
        isu_values = sorted({str(iv.get("ISU_CD") or "").strip() for iv in common_intervals} - {""})
        markets = sorted({str(iv.get("market", "")).strip() for iv in common_intervals} - {""})
        supplemental_used = any(
            str(iv.get("classification_reason", "")).startswith("SUPPLEMENTAL_AUTHORITY_") for iv in common_intervals
        )
        last_common_interval = max(common_intervals, key=lambda iv: iv["effective_to"])
        currently_common = last_common_interval["effective_to"] == last_trading_date

        population.append(
            {
                "ticker": ticker,
                "isu_cd": isu_values,
                "market": markets,
                "first_common_date": min(iv["effective_from"] for iv in common_intervals),
                "last_common_date": max(iv["effective_to"] for iv in common_intervals),
                "common_interval_count": len(common_intervals),
                "numeric_or_alpha": _numeric_or_alpha(ticker),
                "authority_source": AUTHORITY_SOURCE,
                "included_in_population": True,
                "lifecycle_transition_present": CLASS_COMMON in states and CLASS_NOT_COMMON in states,
                "currently_common": currently_common,
                "historical_only": not currently_common,
                "supplemental_authority_used": supplemental_used,
            }
        )

        for iv in common_intervals:
            pit_intervals.append(
                {
                    "ticker": ticker,
                    "isu_cd": iv.get("ISU_CD"),
                    "market": iv.get("market", ""),
                    "state": CLASS_COMMON,
                    "effective_from": iv["effective_from"],
                    "effective_to": iv["effective_to"],
                }
            )

    population.sort(key=lambda r: (tuple(r["market"]), r["ticker"], tuple(r["isu_cd"])))
    pit_intervals.sort(key=lambda r: (r["market"], r["ticker"], str(r["isu_cd"]), r["effective_from"]))
    return population, pit_intervals


def population_manifest_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash contract: sorted canonical lines, final newline (matches the
    ``target_identity_set_hash`` convention in historical_authority_reconciliation)."""

    lines = sorted(
        "|".join(
            [
                ",".join(row["market"]),
                row["ticker"],
                ",".join(row["isu_cd"]),
                row["first_common_date"],
                row["last_common_date"],
                str(row["common_interval_count"]),
                row["numeric_or_alpha"],
            ]
        )
        for row in records
    )
    serialised = "\n".join(lines) + "\n" if lines else ""
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def pit_denominator_manifest_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    lines = sorted(
        "|".join([row["market"], row["ticker"], str(row["isu_cd"]), row["effective_from"], row["effective_to"]])
        for row in records
    )
    serialised = "\n".join(lines) + "\n" if lines else ""
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def write_population_artifact(
    records: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: str,
    path: str | Path = DEFAULT_POPULATION_ARTIFACT_PATH,
) -> Path:
    numeric = sum(1 for r in records if r["numeric_or_alpha"] == "numeric")
    alpha = sum(1 for r in records if r["numeric_or_alpha"] == "alphanumeric")
    payload = {
        "schema": "historical_common_population_v01",
        "authority_source": AUTHORITY_SOURCE,
        "population_manifest_sha256": manifest_sha256,
        "total": len(records),
        "numeric": numeric,
        "alpha": alpha,
        "records": list(records),
    }
    return _atomic_write_json(Path(path), payload)


def write_pit_artifact(
    records: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: str,
    trading_dates_sha256: str,
    path: str | Path = DEFAULT_PIT_ARTIFACT_PATH,
) -> Path:
    payload = {
        "schema": "pit_common_denominator_v01",
        "authority_source": AUTHORITY_SOURCE,
        "pit_common_denominator_sha256": manifest_sha256,
        "trading_dates_sha256": trading_dates_sha256,
        "interval_record_count": len(records),
        "intervals": list(records),
    }
    return _atomic_write_json(Path(path), payload)


def load_historical_common_population(path: str | Path = DEFAULT_POPULATION_ARTIFACT_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload["records"])


def load_pit_common_intervals(path: str | Path = DEFAULT_PIT_ARTIFACT_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload["intervals"])


def get_common_universe_as_of(
    date: str,
    market: str | None = None,
    *,
    intervals: Sequence[Mapping[str, Any]] | None = None,
    intervals_path: str | Path = DEFAULT_PIT_ARTIFACT_PATH,
    calendar_path: str | Path = DEFAULT_CALENDAR_PATH,
) -> list[dict[str, Any]]:
    """Identity-aware COMMON set as of ``date`` (PIT denominator query).

    Fail-closed contract (Section 34): ``date`` must be an exact frozen
    trading date — no fallback to the nearest prior/next trading day, no
    current-universe fallback. Unknown/non-trading/out-of-range dates raise
    ``FreezeContractError`` rather than silently returning an empty or
    approximate set.
    """

    calendar = load_historical_trading_calendar(calendar_path)
    trading_dates = set(calendar["trading_dates"])
    if date not in trading_dates:
        raise FreezeContractError(
            "BLOCKED_UNKNOWN_TRADING_DATE",
            f"{date!r} is not a frozen trading date (range {calendar['first_trading_date']}..{calendar['last_trading_date']})",
        )
    if intervals is None:
        intervals = load_pit_common_intervals(intervals_path)
    matches = [
        {"ticker": row["ticker"], "isu_cd": row["isu_cd"], "market": row["market"]}
        for row in intervals
        if row["effective_from"] <= date <= row["effective_to"] and (market is None or row["market"] == market)
    ]
    matches.sort(key=lambda r: (r["market"], r["ticker"], str(r["isu_cd"])))
    return matches


def evaluate_population_pit_union_invariant(
    population_records: Sequence[Mapping[str, Any]],
    pit_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Section 28: UNION over all PIT COMMON interval identities must exactly
    equal the Population Universe. Identity key is (ticker, isu_cd)."""

    population_keys = {(r["ticker"], isu) for r in population_records for isu in (r["isu_cd"] or [None])}
    pit_keys = {(r["ticker"], r["isu_cd"]) for r in pit_records}
    missing_in_population = sorted(pit_keys - population_keys)
    population_never_pit = sorted(population_keys - pit_keys)
    passed = not missing_in_population and not population_never_pit
    return {
        "gate": "POPULATION_PIT_UNION_INVARIANT",
        "population_identity_count": len(population_keys),
        "pit_identity_count": len(pit_keys),
        "missing_in_population": [list(k) for k in missing_in_population],
        "population_never_pit_common": [list(k) for k in population_never_pit],
        "status": "PASS" if passed else "BLOCKED_UNION_MISMATCH",
    }


def evaluate_identity_gate(pit_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """No (ticker, isu_cd, market) should have two COMMON intervals with
    overlapping date ranges — that would mean the same identity is claimed
    COMMON twice for an overlapping period, an internal contradiction."""

    by_identity: dict[tuple[str, Any, str], list[tuple[str, str]]] = {}
    for row in pit_records:
        key = (row["ticker"], row["isu_cd"], row["market"])
        by_identity.setdefault(key, []).append((row["effective_from"], row["effective_to"]))
    overlaps: list[dict[str, Any]] = []
    for key, ranges in by_identity.items():
        ranges.sort()
        for (from1, to1), (from2, to2) in zip(ranges, ranges[1:]):
            if from2 <= to1:
                overlaps.append({"identity": list(key), "range_1": [from1, to1], "range_2": [from2, to2]})
    return {
        "gate": "PIT_IDENTITY_OVERLAP_GATE",
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "status": "PASS" if not overlaps else "BLOCKED_INTERVAL_OVERLAP",
    }


def evaluate_lifecycle_gate(full_universe: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Every COMMON<->NOT_COMMON boundary in the full-universe intervals must
    have non-overlapping effective ranges within the same (ticker, isu_cd,
    market) — i.e. ``_intervalize`` never silently duplicated a date across
    two differently-classified intervals for the same identity."""

    violations: list[dict[str, Any]] = []
    for ticker, intervals in full_universe.items():
        by_identity: dict[tuple[Any, str], list[dict[str, Any]]] = {}
        for iv in intervals:
            by_identity.setdefault((iv.get("ISU_CD"), iv.get("market", "")), []).append(iv)
        for (isu, market), ivs in by_identity.items():
            ordered = sorted(ivs, key=lambda iv: iv["effective_from"])
            for prev, curr in zip(ordered, ordered[1:]):
                if curr["effective_from"] <= prev["effective_to"]:
                    violations.append(
                        {
                            "ticker": ticker,
                            "isu_cd": isu,
                            "market": market,
                            "prev": [prev["effective_from"], prev["effective_to"], prev["classification"]],
                            "curr": [curr["effective_from"], curr["effective_to"], curr["classification"]],
                        }
                    )
    return {
        "gate": "LIFECYCLE_BOUNDARY_GATE",
        "violation_count": len(violations),
        "violations": violations,
        "status": "PASS" if not violations else "BLOCKED_LIFECYCLE_BOUNDARY",
    }


def compute_pit_daily_statistics(
    pit_records: Sequence[Mapping[str, Any]],
    trading_dates: Sequence[str],
) -> dict[str, Any]:
    """Section 39/40/41: reconstruct the per-date denominator count by direct
    interval coverage (not assertion) to get coverage, min/max/median, and
    the day-over-day delta series for discontinuity diagnostics in one pass."""

    daily_counts: list[int] = []
    daily_market_counts: dict[str, list[int]] = {}
    markets = sorted({row["market"] for row in pit_records})
    for market_name in markets:
        daily_market_counts[market_name] = []

    # Sort intervals once; for each date do a linear scan bucket via sweep.
    sorted_intervals = sorted(pit_records, key=lambda r: r["effective_from"])
    for day in trading_dates:
        count = sum(1 for row in sorted_intervals if row["effective_from"] <= day <= row["effective_to"])
        daily_counts.append(count)
        for market_name in markets:
            daily_market_counts[market_name].append(
                sum(
                    1
                    for row in sorted_intervals
                    if row["market"] == market_name and row["effective_from"] <= day <= row["effective_to"]
                )
            )

    zero_dates = [trading_dates[i] for i, c in enumerate(daily_counts) if c == 0]
    deltas = [daily_counts[i] - daily_counts[i - 1] for i in range(1, len(daily_counts))]
    return {
        "date_coverage": len(trading_dates),
        "first_date": trading_dates[0] if trading_dates else None,
        "last_date": trading_dates[-1] if trading_dates else None,
        "first_date_count": daily_counts[0] if daily_counts else 0,
        "last_date_count": daily_counts[-1] if daily_counts else 0,
        "min_daily_count": min(daily_counts) if daily_counts else 0,
        "max_daily_count": max(daily_counts) if daily_counts else 0,
        "median_daily_count": statistics.median(daily_counts) if daily_counts else 0,
        "zero_count_date_count": len(zero_dates),
        "zero_count_dates": zero_dates,
        "market_breakdown": {
            m: {"min": min(v), "max": max(v), "median": statistics.median(v)} for m, v in daily_market_counts.items()
        },
        "max_daily_delta": max((abs(d) for d in deltas), default=0),
        "daily_counts": daily_counts,
    }


def detect_daily_count_discontinuities(
    daily_counts: Sequence[int],
    trading_dates: Sequence[str],
    *,
    absolute_threshold: int = 30,
) -> list[dict[str, Any]]:
    """Diagnostic-only (Section 40): flags day-over-day deltas above
    ``absolute_threshold`` for human review. Never blocks the freeze on its
    own — a legitimate mass-listing/delisting day is not an error."""

    findings = []
    for i in range(1, len(daily_counts)):
        delta = daily_counts[i] - daily_counts[i - 1]
        if abs(delta) >= absolute_threshold:
            findings.append({"date": trading_dates[i], "previous_date": trading_dates[i - 1], "delta": delta})
    return findings


def run_survivorship_safe_denominator_freeze(
    *,
    target_identities_path: str | Path = DEFAULT_TARGET_IDENTITY_PATH,
    basic_info_root: str | Path = DEFAULT_RAW_ROOT,
    acquisition_checkpoint_path: str | Path = DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    acquisition_final_summary_path: str | Path = DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    supplemental_authority_dir: str | Path = DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR,
    calendar_path: str | Path = DEFAULT_CALENDAR_PATH,
    population_artifact_path: str | Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_artifact_path: str | Path = DEFAULT_PIT_ARTIFACT_PATH,
    closure_artifact_path: str | Path = DEFAULT_CLOSURE_ARTIFACT_PATH,
    created_from_head: str | None = None,
) -> dict[str, Any]:
    """Run the full offline freeze: authority preflight, historical-only
    reconciliation re-verification, full-universe classification, Population
    + PIT derivation, gates, artifact writes. Zero network."""

    calendar = load_historical_trading_calendar(calendar_path)
    trading_dates = calendar["trading_dates"]

    raw = load_basic_info_snapshots(
        basic_info_root,
        calendar_dates=trading_dates,
        acquisition_checkpoint_path=acquisition_checkpoint_path,
        acquisition_final_summary_path=acquisition_final_summary_path,
    )
    if raw.status != "READY":
        return {
            "status": FREEZE_STATUS_BLOCKED,
            "reason": f"primary authority not READY: {raw.status}",
            "raw_input": raw.as_dict(),
        }

    supplemental_authority = load_supplemental_authority_records(supplemental_authority_dir)

    # Historical-only 1,116-target reconciliation re-verification (Section 21/46).
    target = load_target_identities(target_identities_path)
    historical_only = reconcile_target_identities(
        target["identities"],
        raw.snapshots,
        expected_dates=trading_dates,
        source_manifest_sha256=raw.raw_manifest_sha256,
        supplemental_authority=supplemental_authority,
    )
    historical_only_counts = historical_only["counts"]

    full_universe = classify_full_universe(
        raw.snapshots,
        expected_dates=trading_dates,
        source_manifest_sha256=raw.raw_manifest_sha256,
        supplemental_authority=supplemental_authority,
    )

    population_records, pit_records = derive_population_and_pit_records(
        full_universe, last_trading_date=calendar["last_trading_date"]
    )
    pop_hash = population_manifest_sha256(population_records)
    pit_hash = pit_denominator_manifest_sha256(pit_records)

    union_gate = evaluate_population_pit_union_invariant(population_records, pit_records)
    identity_gate = evaluate_identity_gate(pit_records)
    lifecycle_gate = evaluate_lifecycle_gate(full_universe)
    stats = compute_pit_daily_statistics(pit_records, trading_dates)
    discontinuities = detect_daily_count_discontinuities(stats["daily_counts"], trading_dates)

    target_tickers = {t["ticker"] for t in target["identities"]}
    currently_common = sum(1 for r in population_records if r["currently_common"])
    historical_only_population = sum(1 for r in population_records if r["historical_only"])
    in_target_common = sum(1 for r in population_records if r["ticker"] in target_tickers)
    outside_target_common = len(population_records) - in_target_common

    numeric_pop = sum(1 for r in population_records if r["numeric_or_alpha"] == "numeric")
    alpha_pop = sum(1 for r in population_records if r["numeric_or_alpha"] == "alphanumeric")
    kospi_pop = sum(1 for r in population_records if "KOSPI" in r["market"])
    kosdaq_pop = sum(1 for r in population_records if "KOSDAQ" in r["market"])
    lifecycle_count = sum(1 for r in population_records if r["lifecycle_transition_present"])

    write_population_artifact(population_records, manifest_sha256=pop_hash, path=population_artifact_path)
    write_pit_artifact(
        pit_records,
        manifest_sha256=pit_hash,
        trading_dates_sha256=calendar["trading_dates_sha256"],
        path=pit_artifact_path,
    )

    historical_ok = (
        historical_only_counts.get("HISTORICAL_COMMON_REQUIRED") == EXPECTED_HISTORICAL_ONLY_COUNTS["COMMON_REQUIRED"]
        and historical_only_counts.get("HISTORICAL_NOT_COMMON") == EXPECTED_HISTORICAL_ONLY_COUNTS["NOT_COMMON"]
        and historical_only_counts.get("HISTORICAL_AUTHORITY_UNRESOLVED") == EXPECTED_HISTORICAL_ONLY_COUNTS["UNRESOLVED"]
    )
    date_coverage_ok = stats["date_coverage"] == EXPECTED_TRADING_DATE_COUNT
    all_gates_pass = (
        union_gate["status"] == "PASS"
        and identity_gate["status"] == "PASS"
        and lifecycle_gate["status"] == "PASS"
        and historical_ok
        and date_coverage_ok
    )
    freeze_status = FREEZE_STATUS_CLOSED_AND_FROZEN if all_gates_pass else FREEZE_STATUS_BLOCKED

    closure = {
        "schema": "survivorship_safe_denominator_freeze_v01",
        "status": freeze_status,
        "authority_version": "SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01",
        "authority_checkpoint_sha256": raw.checkpoint_authority_sha256,
        "supplemental_authority": {
            "directory": str(supplemental_authority_dir),
            "record_count": len(supplemental_authority),
        },
        "trading_calendar": {
            "trading_dates_sha256": calendar["trading_dates_sha256"],
            "period_start": calendar["first_trading_date"],
            "period_end": calendar["last_trading_date"],
            "trading_date_count": calendar["trading_date_count"],
        },
        "population": {
            "total": len(population_records),
            "numeric": numeric_pop,
            "alpha": alpha_pop,
            "kospi": kospi_pop,
            "kosdaq": kosdaq_pop,
            "currently_common": currently_common,
            "historical_only": historical_only_population,
            "in_frozen_target_common": in_target_common,
            "outside_frozen_target_common": outside_target_common,
            "lifecycle_transition_identity_count": lifecycle_count,
            "population_manifest_sha256": pop_hash,
        },
        "pit": {
            "trading_date_coverage": stats["date_coverage"],
            "interval_record_count": len(pit_records),
            "first_date": stats["first_date"],
            "last_date": stats["last_date"],
            "min_daily_count": stats["min_daily_count"],
            "max_daily_count": stats["max_daily_count"],
            "median_daily_count": stats["median_daily_count"],
            "market_breakdown": stats["market_breakdown"],
            "discontinuity_count": len(discontinuities),
            "pit_common_denominator_sha256": pit_hash,
        },
        "historical_only_reconciliation": {
            "HISTORICAL_COMMON_REQUIRED": historical_only_counts.get("HISTORICAL_COMMON_REQUIRED"),
            "HISTORICAL_NOT_COMMON": historical_only_counts.get("HISTORICAL_NOT_COMMON"),
            "HISTORICAL_AUTHORITY_UNRESOLVED": historical_only_counts.get("HISTORICAL_AUTHORITY_UNRESOLVED"),
        },
        "gates": {
            "population_pit_union_invariant": union_gate,
            "identity_gate": identity_gate,
            "lifecycle_gate": lifecycle_gate,
        },
        "created_from_head": created_from_head,
        "population_artifact_path": str(population_artifact_path),
        "pit_artifact_path": str(pit_artifact_path),
    }
    _atomic_write_json(Path(closure_artifact_path), closure)

    return {
        "status": freeze_status,
        "closure": closure,
        "union_gate": union_gate,
        "identity_gate": identity_gate,
        "lifecycle_gate": lifecycle_gate,
        "daily_statistics": stats,
        "discontinuities": discontinuities,
        "network_requests": {"krx_open_api": 0, "krx_mdc": 0, "pykrx": 0, "opendart": 0},
    }


__all__ = [
    "DEFAULT_CLOSURE_ARTIFACT_PATH",
    "DEFAULT_PIT_ARTIFACT_PATH",
    "DEFAULT_POPULATION_ARTIFACT_PATH",
    "FREEZE_STATUS_BLOCKED",
    "FREEZE_STATUS_CLOSED_AND_FROZEN",
    "FreezeContractError",
    "compute_pit_daily_statistics",
    "derive_population_and_pit_records",
    "detect_daily_count_discontinuities",
    "evaluate_identity_gate",
    "evaluate_lifecycle_gate",
    "evaluate_population_pit_union_invariant",
    "get_common_universe_as_of",
    "load_historical_common_population",
    "load_pit_common_intervals",
    "pit_denominator_manifest_sha256",
    "population_manifest_sha256",
    "run_survivorship_safe_denominator_freeze",
    "write_pit_artifact",
    "write_population_artifact",
]
