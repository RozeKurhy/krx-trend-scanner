"""Rolling production market-data refresh path for MarketDataRepositoryV2.

The one-time E2E full-population closure produced ``FullPopulationRunner`` /
``create_production_runner``: a *closure* tool, hash-pinned to a frozen
population/PIT authority and a frozen ``CANONICAL_CALENDAR_CUTOFF``
(``adjusted_price_pilot.CANONICAL_CALENDAR_CUTOFF = "2026-08-21"``). That tool
is correct for what it was built for -- certifying one historical closure --
but it cannot advance production data day over day: every per-ticker fetch
caps its end date at that frozen constant, and its checkpoints are validated
against it (``CHECKPOINT_AUTHORITY_MISMATCH``).

This module is the rolling counterpart. Its central idea (directive
``ROLLING_MARKET_DATA_REFRESH_PATH_V01`` section 9) is that the latest
certified date must be *authority state*, not a source-code constant: a
:class:`RollingAuthorityManifest` on disk, advanced only by an atomic,
all-legs-or-nothing promotion.

Four independent legs make up one refresh cycle:

* ``common_raw``    -- KOSPI+KOSDAQ whole-market snapshots. Already rolling
  (``KrxHistoricalBackfillRunner`` / ``backfill_krx_raw_stock_v01.py``);
  :class:`RollingRawMarketUpdater` is a thin wrapper, not a reimplementation.
* ``etf_raw``        -- ETF whole-market snapshots, newly separated from the
  bundled acceptance script so it can run independently
  (see ``scripts/backfill_krx_raw_etf_v01.py``).
* ``etf_adjusted``   -- adjusted OHLC for the fixed, Repository-V2-validated
  17-ticker ETF scope. Never routes through a PIT/expected-coverage gate (the
  original acceptance script fetches the full requested range directly), so
  it rolls forward safely with no calendar dependency.
* ``common_adjusted`` -- adjusted OHLC for the full COMMON population. This is
  the leg that *cannot* be completed here. Extending it requires a
  survivorship-safe PIT common-denominator calendar whose frontier covers
  ``target_as_of``; the only one this project has
  (``survivorship_safe_denominator_freeze/v01/pit_common_denominator_v01.json``)
  is deliberately frozen at 2026-08-21 for E2E survivorship-bias safety, and
  inventing a rolling extension rule for it is a decision for that
  workstream's owner, not something to improvise here. See
  :class:`RollingAdjustedPriceUpdater` -- it reuses the existing, already
  parameterized ``resolve_expected_coverage`` unchanged, and fails closed
  with :class:`InsufficientPitFrontierError` until a suitable PIT artifact is
  supplied.

Because one leg cannot complete, :class:`RollingRefreshCoordinator` cannot
promote the boundary today -- and that is the point of the coherence design:
the certified boundary is the *minimum* across required legs, so a blocked
leg blocks the whole promotion rather than producing a raw-ahead-of-adjusted
split state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    DEFAULT_HISTORICAL_CALENDAR_PATH,
    DEFAULT_PIT_PATH,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    DEFAULT_SUSPENSION_ERRATA_PATH,
    resolve_expected_coverage,
)
from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_etf_raw_provider import ETF_ENDPOINT, KrxRawEtfSnapshotProvider
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner, candidate_dates
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.universe.historical_authority_reconciliation import (
    DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    DEFAULT_RAW_ROOT as DEFAULT_BASIC_INFO_RAW_ROOT,
    classify_full_universe,
    load_basic_info_snapshots,
)


ROLLING_AUTHORITY_VERSION = "ROLLING_MARKET_DATA_V01"
DEFAULT_ROLLING_AUTHORITY_DIR = Path("data/market/rolling_authority")

# BLOCKER B (directive section 14): closure artifacts already certified, by direct evidence, that
# PIT COMMON population (3162 tickers) minus these 13 explicitly removed identities equals
# population_total=3149 in `market_data_repository_v2_parity/v01_session_authority_reconciliation_fix01`.
DEFAULT_REMOVED_IDENTITY_AUDIT_PATH = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/"
    "authority_cutover_v01/removed_13_identity_audit.json"
)
# The remaining 4 (population_total=3149 minus analytic_view_success=3145) are these explicitly
# certified EXPECTED_ZERO_STORE tickers -- store absence is the contractually correct behavior.
DEFAULT_ZERO_STORE_CONTRACT_PATH = Path(
    "artifacts/data/end_to_end_data_parity/v01/market_data_repository_v2_parity/"
    "v01_analytic_session_contract_adjudication/zero_store_contract.json"
)
# The closure's own per-ticker expected-coverage authority (``EFFECTIVE_CORRECTED_AUTHORITY_V01``) is
# strictly more precise than re-deriving "expected_last_date" from the raw frozen PIT interval alone
# (the latter is only the ``PIT_CALENDAR_APPROXIMATION`` tier of ``resolve_expected_coverage`` and does
# not model per-ticker wind-down/suspension days). A ticker whose disk state exactly matches what this
# CSV already certified is not a gap -- it is already-explained, certified population state, cited by
# its own recorded ``coverage_status`` rather than an invented tolerance rule.
DEFAULT_FULL_POPULATION_CLOSURE_RESULTS_PATH = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/"
    "authority_cutover_fix02/production_zero_call_run/full_population_results.csv"
)

# The four legs a target boundary must clear before it can be certified.
REQUIRED_LEGS = ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")

# The fixed, Repository-V2-validated ETF adjusted-price scope (directive
# section 19: "임의 확장하지 않는다"). This MUST stay identical to
# ``scripts/backfill_krx_etf_repository_v2_v01.py::ACCEPTANCE_TICKERS`` --
# ``tests/test_rolling_market_data_refresh_v01.py`` asserts the two never
# drift apart, the same allowlist+drift-test pairing already used for
# ``PATTERN_A_TEMPORAL_FIELDS``.
ETF_VALIDATED_ACCEPTANCE_TICKERS = (
    "0115D0", "069500", "091160", "091170", "091180", "102960", "102970",
    "117460", "117680", "117700", "140700", "140710", "229200", "244580",
    "266410", "300950", "305720",
)


class RollingAuthorityError(RuntimeError):
    """Raised when the rolling authority manifest is missing, malformed, or tampered with."""


class InsufficientPitFrontierError(RollingAuthorityError):
    """Raised when the supplied PIT/calendar authority does not cover ``target_as_of``.

    This is the expected, correct outcome for the COMMON adjusted-price leg
    today: no rolling-safe PIT extension exists yet. It is not a bug to catch
    and route around -- it is the designed fail-closed boundary.
    """


class RefreshLegFailure(RuntimeError):
    """Raised by the coordinator when a leg fails; carries the leg name for reporting."""

    def __init__(self, leg: str, cause: Exception) -> None:
        super().__init__(f"{leg} failed: {cause}")
        self.leg = leg
        self.cause = cause


def _iso_today_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_day(iso_date: str) -> str:
    from datetime import timedelta

    return (pd.Timestamp(iso_date).date() + timedelta(days=1)).isoformat()


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    """Stable sha256 over every field except the digest itself."""
    canonical = {k: v for k, v in payload.items() if k != "manifest_sha256"}
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RollingAuthorityManifest:
    """Rolling production boundary state -- data, never a source-code constant."""

    authority_version: str
    certified_through: str
    leg_boundaries: dict[str, str]
    previous_boundary: str | None
    raw_store_version: str
    adjusted_store_version: str
    instrument_contract_version: str
    bootstrap_source: dict[str, Any] | None
    generated_at: str
    # Directive ROLLING_AUTHORITY_HARDENING_V01 section 5-17: additive references to the merged
    # PIT/calendar authority files this manifest was certified against. All default to None so a
    # pre-hardening manifest.json remains loadable unchanged (load_rolling_authority's own digest
    # check recomputes over whatever keys were actually serialized) -- but
    # validate_merged_authority_coherence fails closed in production rolling mode until a manifest
    # carries real (non-None) values here, i.e. until it has been migrated.
    merged_pit_digest: str | None = None
    merged_pit_frontier: str | None = None
    merged_pit_schema_version: str | None = None
    merged_calendar_digest: str | None = None
    merged_calendar_frontier: str | None = None
    merged_calendar_schema_version: str | None = None
    manifest_sha256: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_digest(self) -> "RollingAuthorityManifest":
        payload = self.to_dict()
        payload["manifest_sha256"] = _manifest_digest(payload)
        return RollingAuthorityManifest(**payload)


def _coherent_boundary(leg_boundaries: Mapping[str, str]) -> str:
    missing = [leg for leg in REQUIRED_LEGS if leg not in leg_boundaries]
    if missing:
        raise RollingAuthorityError(f"ROLLING_MANIFEST_MISSING_LEG_BOUNDARIES: {missing}")
    return min(leg_boundaries[leg] for leg in REQUIRED_LEGS)


def _manifest_path(directory: Path) -> Path:
    return Path(directory) / "manifest.json"


def load_rolling_authority(directory: Path = DEFAULT_ROLLING_AUTHORITY_DIR) -> RollingAuthorityManifest:
    path = _manifest_path(directory)
    if not path.exists():
        raise RollingAuthorityError(f"ROLLING_MANIFEST_MISSING: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("authority_version") != ROLLING_AUTHORITY_VERSION:
        raise RollingAuthorityError(
            f"ROLLING_MANIFEST_AUTHORITY_VERSION_MISMATCH: {payload.get('authority_version')!r}"
        )
    stored_digest = payload.get("manifest_sha256", "")
    recomputed = _manifest_digest(payload)
    if stored_digest != recomputed:
        raise RollingAuthorityError(
            f"ROLLING_MANIFEST_CHECKSUM_MISMATCH: stored={stored_digest} recomputed={recomputed}"
        )
    expected_certified = _coherent_boundary(payload["leg_boundaries"])
    if payload["certified_through"] != expected_certified:
        raise RollingAuthorityError(
            "ROLLING_MANIFEST_CERTIFIED_THROUGH_INCOHERENT: "
            f"stored={payload['certified_through']} expected_min_of_legs={expected_certified}"
        )
    return RollingAuthorityManifest(**payload)


def write_rolling_authority(manifest: RollingAuthorityManifest, directory: Path = DEFAULT_ROLLING_AUTHORITY_DIR) -> None:
    """Atomically publish a new manifest (temp file + backup + os.replace, mirroring AdjustedPriceStore.save_full)."""
    if manifest.authority_version != ROLLING_AUTHORITY_VERSION:
        raise RollingAuthorityError(f"ROLLING_MANIFEST_AUTHORITY_VERSION_MISMATCH: {manifest.authority_version!r}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final_path = _manifest_path(directory)
    manifest = manifest.with_digest()
    token = uuid.uuid4().hex
    temp_path = directory / f".manifest.json.tmp_{token}"
    backup_path = directory / f".manifest.json.backup_{token}"
    replaced = False
    try:
        temp_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # Round-trip through load_rolling_authority's own validation before publishing.
        reloaded = json.loads(temp_path.read_text(encoding="utf-8"))
        if _manifest_digest(reloaded) != reloaded["manifest_sha256"]:
            raise RollingAuthorityError("ROLLING_MANIFEST_SELF_CHECK_FAILED_BEFORE_PUBLISH")
        if final_path.exists():
            final_path.replace(backup_path)
        os.replace(temp_path, final_path)
        replaced = True
    except Exception:
        if replaced and backup_path.exists():
            os.replace(backup_path, final_path)
        raise
    finally:
        for path in (temp_path, backup_path):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


def bootstrap_rolling_authority(
    *,
    raw_store: KrxRawStockStore,
    adjusted_store_dir: Path,
    etf_acceptance_tickers: Sequence[str] = ETF_VALIDATED_ACCEPTANCE_TICKERS,
    closure_evidence: Sequence[tuple[str, Path]] = (),
    raw_store_version: str = "KRX_RAW_STOCK_V01",
    adjusted_store_version: str = "ADJUSTED_PRICE_STORE_V02",
    instrument_contract_version: str = "REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
) -> RollingAuthorityManifest:
    """Derive the initial rolling boundary from *observed* store state, not a hardcoded literal.

    ``closure_evidence`` is a sequence of ``(label, path)`` pairs to trusted, already-certified
    closure artifacts (e.g. the full-population-closure and Repository-V2-parity
    ``final_decision.json`` files) -- read and cited verbatim as bootstrap provenance, never trusted
    blindly: a missing or unparsable evidence file fails the bootstrap rather than being skipped.
    """

    def _latest_complete(market: str) -> str | None:
        rows = [row for row in raw_store.list_manifest(market) if row.get("status") == "COMPLETE"]
        return max((str(row["date"]) for row in rows), default=None)

    common_raw = min(d for d in (_latest_complete("KOSPI"), _latest_complete("KOSDAQ")) if d is not None) if (
        _latest_complete("KOSPI") and _latest_complete("KOSDAQ")
    ) else None
    etf_raw = _latest_complete("ETF")
    if common_raw is None or etf_raw is None:
        raise RollingAuthorityError("BOOTSTRAP_RAW_STORE_HAS_NO_COMPLETE_SNAPSHOTS")

    def _mode_actual_date_max(tickers: Sequence[str]) -> str | None:
        counts: dict[str, int] = {}
        for ticker in tickers:
            meta_path = Path(adjusted_store_dir) / f"{ticker}.meta.json"
            if not meta_path.exists():
                continue
            value = json.loads(meta_path.read_text(encoding="utf-8")).get("actual_date_max")
            if value:
                counts[value] = counts.get(value, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    all_common_tickers = [
        p.stem.removesuffix(".meta") if p.stem.endswith(".meta") else p.stem
        for p in Path(adjusted_store_dir).glob("*.meta.json")
    ]
    common_common_tickers = [t for t in all_common_tickers if t not in set(etf_acceptance_tickers)]
    common_adjusted = _mode_actual_date_max(common_common_tickers)
    etf_adjusted = _mode_actual_date_max(etf_acceptance_tickers)
    if common_adjusted is None or etf_adjusted is None:
        raise RollingAuthorityError("BOOTSTRAP_ADJUSTED_STORE_HAS_NO_READABLE_METADATA")

    evidence_records: list[dict[str, Any]] = []
    for label, path in closure_evidence:
        path = Path(path)
        if not path.exists():
            raise RollingAuthorityError(f"BOOTSTRAP_EVIDENCE_MISSING: {label} -> {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        evidence_records.append({"label": label, "path": str(path), "content": payload})

    leg_boundaries = {
        "common_raw": common_raw,
        "common_adjusted": common_adjusted,
        "etf_raw": etf_raw,
        "etf_adjusted": etf_adjusted,
    }
    manifest = RollingAuthorityManifest(
        authority_version=ROLLING_AUTHORITY_VERSION,
        certified_through=_coherent_boundary(leg_boundaries),
        leg_boundaries=leg_boundaries,
        previous_boundary=None,
        raw_store_version=raw_store_version,
        adjusted_store_version=adjusted_store_version,
        instrument_contract_version=instrument_contract_version,
        bootstrap_source={
            "method": "OBSERVED_STORE_STATE",
            "description": (
                "certified_through is the minimum of per-leg boundaries directly observed from the "
                "raw manifest (latest COMPLETE date) and the adjusted store (mode of actual_date_max), "
                "not a hardcoded literal."
            ),
            "evidence": evidence_records,
        },
        generated_at=_iso_today_utc(),
    )
    return manifest.with_digest()


@dataclass(frozen=True)
class PopulationAuditRecord:
    """Per-ticker accounting for the BLOCKER B full-population bootstrap audit."""

    ticker: str
    category: str  # "OK" | "EXPLAINED_GAP" | "UNEXPLAINED_GAP"
    reason: str
    expected_last_date: str | None
    actual_last_date: str | None


@dataclass(frozen=True)
class PopulationBootstrapAudit:
    candidate_boundary: str
    total_in_scope: int
    ok_count: int
    explained_gap_count: int
    unexplained_gap_count: int
    records: tuple[PopulationAuditRecord, ...]

    @property
    def certified(self) -> bool:
        return self.unexplained_gap_count == 0

    def unexplained(self) -> tuple[PopulationAuditRecord, ...]:
        return tuple(r for r in self.records if r.category == "UNEXPLAINED_GAP")

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "candidate_boundary": self.candidate_boundary,
            "total_in_scope": self.total_in_scope,
            "ok_count": self.ok_count,
            "explained_gap_count": self.explained_gap_count,
            "unexplained_gap_count": self.unexplained_gap_count,
            "unexplained_tickers": [asdict(r) for r in self.unexplained()],
        }


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# coverage_status values the closure's own PilotResult/full-population run already treats as a valid,
# certified outcome (adjusted_price_pilot.CoverageStatus) -- not an invented tolerance, a citation of
# an enum this project's own closure process already used to accept these exact tickers.
_CLOSURE_CERTIFIED_COVERAGE_STATUSES = frozenset(
    {"FULL_EXPECTED_COVERAGE", "SOURCE_ENDS_EARLY", "PARTIAL_EXPECTED_COVERAGE", "INTERNAL_GAPS"}
)


def _load_closure_certified_results(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}
    frame = pd.read_csv(path, dtype=str)
    return {str(row["ticker"]): row.to_dict() for _, row in frame.iterrows()}


def _classify_common_ticker(
    ticker: str,
    candidate_boundary: str,
    adjusted_store_dir: Path,
    removed_identities: set,
    zero_store_tickers: set,
    closure_certified: Mapping[str, Mapping[str, Any]],
    *,
    requested_start: str,
    stocks_dir: Path,
    pit_path: Path,
    historical_calendar_path: Path,
    suspension_authority_path: Path,
    suspension_errata_path: Path | None,
) -> PopulationAuditRecord:
    # 1. Already-certified, already-closed authority correction: this identity is not part of the
    #    required population at all (directive section 14: cite the closure artifact's *semantics*,
    #    not just its verdict).
    if ticker in removed_identities:
        return PopulationAuditRecord(
            ticker, "EXPLAINED_GAP", "INTENTIONAL_AUTHORITY_CORRECTION_REMOVED_IDENTITY", None, None
        )

    meta_path = Path(adjusted_store_dir) / f"{ticker}.meta.json"
    has_store = meta_path.exists()
    actual_last = _read_json(meta_path).get("actual_date_max") if has_store else None

    # 2. Already-certified explicit zero-store contract (DATA_UNAVAILABLE: ADJUSTED_MISSING is the
    #    contractually correct behavior for these tickers, not a gap to explain away).
    if ticker in zero_store_tickers:
        if not has_store:
            return PopulationAuditRecord(ticker, "EXPLAINED_GAP", "CERTIFIED_EXPECTED_ZERO_STORE", None, None)
        return PopulationAuditRecord(
            ticker, "UNEXPLAINED_GAP", "STORE_PRESENT_BUT_ZERO_STORE_CONTRACT_REQUIRES_ABSENCE", None, actual_last
        )

    resolution = resolve_expected_coverage(
        ticker,
        requested_start,
        candidate_boundary,
        stocks_dir=stocks_dir,
        pit_path=pit_path,
        historical_calendar_path=historical_calendar_path,
        suspension_authority_path=suspension_authority_path,
        suspension_errata_path=suspension_errata_path,
    )
    expected_dates = resolution.expected_tradable_dates
    expected_last = max(expected_dates) if expected_dates else None

    if expected_last is None:
        if resolution.authority_status == "ERROR":
            return PopulationAuditRecord(
                ticker, "UNEXPLAINED_GAP", f"COVERAGE_RESOLUTION_ERROR:{resolution.error_type}", None, actual_last
            )
        # No trading day is expected of this ticker inside the audited window at all -- nothing to
        # reconcile against the store, regardless of whether a store file happens to exist.
        return PopulationAuditRecord(ticker, "OK", "NO_EXPECTED_OBSERVATIONS_IN_WINDOW", None, actual_last)

    if actual_last is not None and expected_last is not None and actual_last >= expected_last:
        return PopulationAuditRecord(ticker, "OK", "ACTUAL_COVERAGE_MEETS_EXPECTED", expected_last, actual_last)

    # Apparent shortfall against this function's own PIT-interval-derived ``expected_last`` -- but
    # that derivation is only the PIT_CALENDAR_APPROXIMATION tier and does not model per-ticker
    # wind-down/suspension days. Before calling this unexplained, cross-reference the closure's own
    # per-ticker certified record (directive section 14: cite certified *semantics*, not just
    # verdict=ACCEPT). A ticker whose disk state has not drifted one bit from what the closure itself
    # already certified, under a coverage_status the closure's own enum already accepts, is not a new
    # gap -- it is unchanged, already-adjudicated population state.
    certified = closure_certified.get(ticker)
    if certified is not None:
        certified_last = certified.get("last_actual_date")
        certified_last = None if pd.isna(certified_last) else str(certified_last)
        coverage_status = certified.get("coverage_status")
        if certified_last == actual_last and coverage_status in _CLOSURE_CERTIFIED_COVERAGE_STATUSES:
            return PopulationAuditRecord(
                ticker, "EXPLAINED_GAP", f"CERTIFIED_BY_FULL_POPULATION_CLOSURE:{coverage_status}", expected_last, actual_last
            )

    if not has_store:
        return PopulationAuditRecord(
            ticker, "UNEXPLAINED_GAP", "NO_STORE_FILE_BUT_COVERAGE_EXPECTED", expected_last, None
        )
    return PopulationAuditRecord(
        ticker, "UNEXPLAINED_GAP", "ACTUAL_COVERAGE_SHORT_OF_EXPECTED", expected_last, actual_last
    )


def _classify_etf_ticker(ticker: str, candidate_boundary: str, adjusted_store_dir: Path) -> PopulationAuditRecord:
    meta_path = Path(adjusted_store_dir) / f"{ticker}.meta.json"
    if not meta_path.exists():
        return PopulationAuditRecord(ticker, "UNEXPLAINED_GAP", "ETF_ACCEPTANCE_TICKER_HAS_NO_STORE_FILE", candidate_boundary, None)
    actual_last = _read_json(meta_path).get("actual_date_max")
    if actual_last is not None and actual_last >= candidate_boundary:
        return PopulationAuditRecord(ticker, "OK", "ACTUAL_COVERAGE_MEETS_CANDIDATE_BOUNDARY", candidate_boundary, actual_last)
    return PopulationAuditRecord(
        ticker, "UNEXPLAINED_GAP", "ETF_ACCEPTANCE_TICKER_COVERAGE_SHORT_OF_CANDIDATE_BOUNDARY", candidate_boundary, actual_last
    )


def audit_full_population_bootstrap(
    *,
    adjusted_store_dir: Path,
    candidate_boundary: str,
    etf_acceptance_tickers: Sequence[str] = ETF_VALIDATED_ACCEPTANCE_TICKERS,
    requested_start: str = "2010-01-04",
    stocks_dir: Path = Path("data/raw/stocks"),
    pit_path: Path = DEFAULT_PIT_PATH,
    historical_calendar_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
    suspension_authority_path: Path = DEFAULT_SUSPENSION_AUTHORITY_PATH,
    suspension_errata_path: Path | None = DEFAULT_SUSPENSION_ERRATA_PATH,
    removed_identity_audit_path: Path = DEFAULT_REMOVED_IDENTITY_AUDIT_PATH,
    zero_store_contract_path: Path = DEFAULT_ZERO_STORE_CONTRACT_PATH,
    full_population_closure_results_path: Path | None = DEFAULT_FULL_POPULATION_CLOSURE_RESULTS_PATH,
) -> PopulationBootstrapAudit:
    """Replace ``mode(actual_date_max)`` with an exhaustive, per-ticker OK/explained/unexplained
    accounting (directive ``ROLLING_MARKET_DATA_AUTHORITY_FIX_V01`` section 14). In-scope population
    is every PIT COMMON ticker plus the fixed ETF acceptance scope -- nothing narrower, nothing wider.
    """

    pit = _read_json(pit_path)
    pit_tickers = sorted({it["ticker"] for it in pit.get("intervals", []) if it.get("state") == "COMMON"})

    removed_identities: set = set()
    if Path(removed_identity_audit_path).exists():
        removed_identities = set(_read_json(removed_identity_audit_path).get("removed_identities", []))
    zero_store_tickers: set = set()
    if Path(zero_store_contract_path).exists():
        zero_store_tickers = set(_read_json(zero_store_contract_path).get("tickers", []))
    closure_certified = _load_closure_certified_results(full_population_closure_results_path)

    records: list[PopulationAuditRecord] = []
    for ticker in pit_tickers:
        records.append(
            _classify_common_ticker(
                ticker,
                candidate_boundary,
                Path(adjusted_store_dir),
                removed_identities,
                zero_store_tickers,
                closure_certified,
                requested_start=requested_start,
                stocks_dir=Path(stocks_dir),
                pit_path=Path(pit_path),
                historical_calendar_path=Path(historical_calendar_path),
                suspension_authority_path=Path(suspension_authority_path),
                suspension_errata_path=Path(suspension_errata_path) if suspension_errata_path else None,
            )
        )
    for ticker in etf_acceptance_tickers:
        records.append(_classify_etf_ticker(ticker, candidate_boundary, Path(adjusted_store_dir)))

    ok_count = sum(1 for r in records if r.category == "OK")
    explained_gap_count = sum(1 for r in records if r.category == "EXPLAINED_GAP")
    unexplained_gap_count = sum(1 for r in records if r.category == "UNEXPLAINED_GAP")
    return PopulationBootstrapAudit(
        candidate_boundary=candidate_boundary,
        total_in_scope=len(records),
        ok_count=ok_count,
        explained_gap_count=explained_gap_count,
        unexplained_gap_count=unexplained_gap_count,
        records=tuple(records),
    )


def bootstrap_rolling_authority_v2(
    *,
    raw_store: KrxRawStockStore,
    adjusted_store_dir: Path,
    candidate_boundary: str,
    etf_acceptance_tickers: Sequence[str] = ETF_VALIDATED_ACCEPTANCE_TICKERS,
    closure_evidence: Sequence[tuple[str, Path]] = (),
    raw_store_version: str = "KRX_RAW_STOCK_V01",
    adjusted_store_version: str = "ADJUSTED_PRICE_STORE_V02",
    instrument_contract_version: str = "REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
    audit_kwargs: Mapping[str, Any] | None = None,
) -> tuple[RollingAuthorityManifest, PopulationBootstrapAudit]:
    """Supersedes :func:`bootstrap_rolling_authority` for the COMMON/ETF *adjusted* legs (directive
    section 18-19). ``bootstrap_rolling_authority``'s ``mode(actual_date_max)`` heuristic is kept,
    unmodified, only as the now-explicitly-insufficient prior approach
    (``test_bootstrap_mode_is_not_sufficient``); every real bootstrap must go through this function,
    which requires ``UNEXPLAINED_BOOTSTRAP_GAP_COUNT == 0`` before it will certify anything and never
    silently overwrites an existing manifest.
    """

    audit = audit_full_population_bootstrap(
        adjusted_store_dir=adjusted_store_dir,
        candidate_boundary=candidate_boundary,
        etf_acceptance_tickers=etf_acceptance_tickers,
        **(audit_kwargs or {}),
    )
    if not audit.certified:
        raise RollingAuthorityError(
            f"BOOTSTRAP_UNEXPLAINED_POPULATION_GAP_COUNT={audit.unexplained_gap_count}: "
            f"{[r.ticker for r in audit.unexplained()][:10]}"
        )

    def _latest_complete(market: str) -> str | None:
        rows = [row for row in raw_store.list_manifest(market) if row.get("status") == "COMPLETE"]
        return max((str(row["date"]) for row in rows), default=None)

    kospi, kosdaq, etf_raw = _latest_complete("KOSPI"), _latest_complete("KOSDAQ"), _latest_complete("ETF")
    if kospi is None or kosdaq is None or etf_raw is None:
        raise RollingAuthorityError("BOOTSTRAP_RAW_STORE_HAS_NO_COMPLETE_SNAPSHOTS")
    common_raw = min(kospi, kosdaq)

    evidence_records: list[dict[str, Any]] = []
    for label, path in closure_evidence:
        path = Path(path)
        if not path.exists():
            raise RollingAuthorityError(f"BOOTSTRAP_EVIDENCE_MISSING: {label} -> {path}")
        evidence_records.append({"label": label, "path": str(path), "content": _read_json(path)})

    leg_boundaries = {
        "common_raw": common_raw,
        "common_adjusted": candidate_boundary,
        "etf_raw": etf_raw,
        "etf_adjusted": candidate_boundary,
    }
    manifest = RollingAuthorityManifest(
        authority_version=ROLLING_AUTHORITY_VERSION,
        certified_through=_coherent_boundary(leg_boundaries),
        leg_boundaries=leg_boundaries,
        previous_boundary=None,
        raw_store_version=raw_store_version,
        adjusted_store_version=adjusted_store_version,
        instrument_contract_version=instrument_contract_version,
        bootstrap_source={
            "method": "FULL_POPULATION_AUDIT",
            "description": (
                "certified_through for the adjusted legs is only accepted at candidate_boundary "
                "after every in-scope ticker (PIT COMMON population + ETF acceptance scope) is "
                "individually accounted for as OK/explained-gap, with zero unexplained gaps -- "
                "mode(actual_date_max) is no longer trusted as sufficient evidence on its own."
            ),
            "population_audit_summary": audit.to_summary_dict(),
            "evidence": evidence_records,
        },
        generated_at=_iso_today_utc(),
    )
    return manifest.with_digest(), audit


class RollingRawMarketUpdater:
    """COMMON (KOSPI+KOSDAQ) raw rolling leg. Thin wrapper -- ``KrxHistoricalBackfillRunner`` is
    already a rolling-capable updater; this class does not reimplement it."""

    def __init__(self, runner: KrxHistoricalBackfillRunner, raw_store: KrxRawStockStore) -> None:
        self.runner = runner
        self.raw_store = raw_store

    @staticmethod
    def plan(current_boundary: str, target_as_of: str) -> dict[str, Any]:
        start = _next_day(current_boundary)
        return {"leg": "common_raw", "start": start, "end": target_as_of, "markets": ["KOSPI", "KOSDAQ"]}

    def refresh(self, current_boundary: str, target_as_of: str, **run_kwargs: Any) -> dict[str, Any]:
        start = _next_day(current_boundary)
        result = self.runner.run(start, target_as_of, resume=True, markets=("KOSPI", "KOSDAQ"), **run_kwargs)
        new_boundary = max(
            (
                str(row["date"])
                for market in ("KOSPI", "KOSDAQ")
                for row in self.raw_store.list_manifest(market)
                if row.get("status") == "COMPLETE" and str(row["date"]) <= target_as_of
            ),
            default=current_boundary,
        )
        return {"leg": "common_raw", "runner_result": result, "new_boundary": new_boundary}


class RollingRawEtfUpdater:
    """ETF whole-market raw snapshot rolling leg, independent of any adjusted-price update.

    Reuses ``KrxRawEtfSnapshotProvider`` (the same class the bundled acceptance script uses) but as a
    standalone, ETF-only ingester. Session-date determination piggybacks on the COMMON raw store's
    already-established KOSPI manifest (COMPLETE/NO_DATA), the same convention
    ``backfill_krx_etf_repository_v2_v01.py`` already uses -- so this leg must run after the COMMON
    raw leg in a refresh cycle.
    """

    def __init__(self, provider: KrxRawEtfSnapshotProvider, raw_store: KrxRawStockStore, *, request_interval_ms: int = 100) -> None:
        self.provider = provider
        self.raw_store = raw_store
        self.request_interval_ms = request_interval_ms

    def _session_dates(self, start: str, end: str) -> tuple[list[str], list[str]]:
        rows = self.raw_store.list_manifest("KOSPI")
        trading = [str(r["date"]) for r in rows if start <= str(r["date"]) <= end and r["status"] == "COMPLETE"]
        closed = [str(r["date"]) for r in rows if start <= str(r["date"]) <= end and r["status"] == "NO_DATA"]
        return sorted(trading), sorted(closed)

    def plan(self, current_boundary: str, target_as_of: str) -> dict[str, Any]:
        start = _next_day(current_boundary)
        trading, closed = self._session_dates(start, target_as_of)
        return {"leg": "etf_raw", "start": start, "end": target_as_of, "trading_sessions": trading, "closed_sessions": closed}

    def refresh(self, current_boundary: str, target_as_of: str, *, resume: bool = True) -> dict[str, Any]:
        import time

        start = _next_day(current_boundary)
        trading, closed = self._session_dates(start, target_as_of)
        for day in closed:
            if self.raw_store.get_manifest("ETF", day) is None:
                self.raw_store.save_snapshot("ETF", day, _empty_etf_snapshot(), ETF_ENDPOINT)
        saved, failures = 0, []
        for day in trading:
            existing = self.raw_store.get_manifest("ETF", day)
            if resume and existing is not None and existing["status"] in {"COMPLETE", "NO_DATA"}:
                continue
            try:
                frame = self.provider.fetch_snapshot(day)
                self.raw_store.save_snapshot("ETF", day, frame, ETF_ENDPOINT)
                saved += 1
            except Exception as exc:  # noqa: BLE001 -- bounded, reported, not retried with a new source
                self.raw_store.save_failure("ETF", day, ETF_ENDPOINT, type(exc).__name__, str(exc))
                failures.append({"date": day, "error_type": type(exc).__name__})
                break
            if self.request_interval_ms:
                time.sleep(self.request_interval_ms / 1000.0)
        new_boundary = max(
            (str(r["date"]) for r in self.raw_store.list_manifest("ETF") if r.get("status") == "COMPLETE" and str(r["date"]) <= target_as_of),
            default=current_boundary,
        )
        return {"leg": "etf_raw", "saved": saved, "failures": failures, "new_boundary": new_boundary}


def _empty_etf_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "ticker": pd.Series([], dtype="string"),
            **{f: pd.Series([], dtype="int64") for f in ("open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares")},
        },
        columns=["date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"],
    )


class RollingEtfAdjustedUpdater:
    """ETF adjusted-price rolling leg for the fixed 17-ticker validated scope.

    Unlike COMMON, this never routed through ``resolve_expected_coverage``/PIT -- the original
    acceptance script fetches the full requested range directly from Naver each cycle -- so it has no
    frozen-calendar dependency and rolls forward safely. Never expands beyond
    ``ETF_VALIDATED_ACCEPTANCE_TICKERS``; scope expansion is a separate, unapproved phase.
    """

    def __init__(self, provider: NaverDirectAdjustedPriceDataProvider, store: AdjustedPriceStore, *, requested_start: str = "2023-01-02") -> None:
        self.provider = provider
        self.store = store
        self.requested_start = requested_start

    def refresh(self, current_boundary: str, target_as_of: str) -> dict[str, Any]:
        results, failures = [], []
        for ticker in ETF_VALIDATED_ACCEPTANCE_TICKERS:
            try:
                frame = self.provider.load_daily(ticker, self.requested_start, target_as_of)
                if frame.empty:
                    raise RuntimeError("EMPTY_ADJUSTED_AUTHORITY")
                self.store.save_full(ticker, frame, metadata_context={"requested_start": self.requested_start, "requested_end": target_as_of})
                results.append(ticker)
            except Exception as exc:  # noqa: BLE001 -- bounded, reported, not retried with a new source
                failures.append({"ticker": ticker, "error_type": type(exc).__name__})
                break
        new_boundary = target_as_of if not failures and len(results) == len(ETF_VALIDATED_ACCEPTANCE_TICKERS) else current_boundary
        return {"leg": "etf_adjusted", "updated": results, "failures": failures, "new_boundary": new_boundary}


class RollingAdjustedPriceUpdater:
    """COMMON adjusted-price rolling leg. Fails closed unless handed a PIT/calendar authority whose
    frontier already covers ``target_as_of`` -- see the module docstring and
    :class:`InsufficientPitFrontierError`. This class never falls back to the frozen E2E defaults
    (``survivorship_safe_denominator_freeze/v01/pit_common_denominator_v01.json``); callers must pass
    ``pit_path``/``historical_calendar_path`` explicitly.
    """

    def __init__(
        self,
        provider: NaverDirectAdjustedPriceDataProvider,
        store: AdjustedPriceStore,
        *,
        pit_path: Path,
        historical_calendar_path: Path,
    ) -> None:
        self.provider = provider
        self.store = store
        self.pit_path = Path(pit_path)
        self.historical_calendar_path = Path(historical_calendar_path)

    def _frontier(self) -> str:
        calendar = json.loads(self.historical_calendar_path.read_text(encoding="utf-8"))
        dates = calendar.get("trading_dates", [])
        pit = json.loads(self.pit_path.read_text(encoding="utf-8"))
        pit_ends = [it["effective_to"] for it in pit.get("intervals", []) if it.get("state") == "COMMON"]
        if not dates or not pit_ends:
            raise RollingAuthorityError("PIT_OR_CALENDAR_ARTIFACT_EMPTY")
        return min(max(dates), max(pit_ends))

    def refresh(
        self, tickers: Sequence[str], current_boundary: str, target_as_of: str, requested_start: str | None = None
    ) -> dict[str, Any]:
        """``requested_start=None`` (the default -- directive ROLLING_AUTHORITY_HARDENING_V01
        section 18-21) means EVERY ticker's own fetch lower bound is resolved independently from
        its current certified (ticker, isu_cd, market) identity in the PIT
        (``resolve_current_identity``), never a single blanket literal applied across the whole
        population -- this default previously being ``"2010-01-04"`` was the exact root cause of
        the 202-ticker phantom-row defect (COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01).

        A genuinely historical caller may still pass an explicit ``requested_start`` string, which
        is then used verbatim for every ticker in the batch, exactly as before -- e.g. a
        first-time/backfill population load where every ticker's PIT identity already starts at (or
        the caller explicitly wants) that literal date.
        """
        frontier = self._frontier()
        if target_as_of > frontier:
            raise InsufficientPitFrontierError(
                f"PIT/calendar frontier is {frontier}; cannot roll COMMON adjusted-price data to "
                f"{target_as_of} without a new survivorship-safe PIT extension, which this updater "
                "does not generate on its own."
            )
        return self._refresh_against(
            tickers, current_boundary, target_as_of, requested_start, self.pit_path, self.historical_calendar_path
        )

    def refresh_with_extension(
        self,
        tickers: Sequence[str],
        current_boundary: str,
        target_as_of: str,
        extension: PitExtensionResult,
        *,
        requested_start: str | None = None,
        workdir: Path,
    ) -> dict[str, Any]:
        """Same as :meth:`refresh`, but against a validated :class:`PitExtensionResult` instead of
        ``self.pit_path``/``self.historical_calendar_path`` (BLOCKER A, directive section 13). The
        frozen artifacts on disk are never touched -- the merged intervals/calendar are materialized
        to ``workdir`` only for the duration of this call."""
        if target_as_of > extension.extension_end:
            raise InsufficientPitFrontierError(
                f"Extension frontier is {extension.extension_end}; cannot roll COMMON adjusted-price "
                f"data to {target_as_of} without a further PIT extension."
            )
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        ext_pit_path = workdir / "extended_pit_common_denominator.json"
        ext_calendar_path = workdir / "extended_historical_trading_calendar.json"
        ext_pit_path.write_text(
            json.dumps({"intervals": list(extension.merged_intervals)}, ensure_ascii=False), encoding="utf-8"
        )
        ext_calendar_path.write_text(
            json.dumps({"trading_dates": list(extension.merged_calendar_dates)}, ensure_ascii=False), encoding="utf-8"
        )
        return self._refresh_against(
            tickers, current_boundary, target_as_of, requested_start, ext_pit_path, ext_calendar_path
        )

    def _refresh_against(
        self,
        tickers: Sequence[str],
        current_boundary: str,
        target_as_of: str,
        requested_start: str | None,
        pit_path: Path,
        historical_calendar_path: Path,
    ) -> dict[str, Any]:
        # requested_start=None (section 18-21): resolve EACH ticker's own fetch lower bound from
        # its current certified identity, read fresh from pit_path every call (never through
        # adjusted_price_pilot's lru_cache'd reader -- this path is invoked with different pit_path
        # values across calls, e.g. a per-run workdir extension file, so a stale cached mapping is a
        # real hazard here too, not just in the MarketDataRepositoryV2 read path).
        intervals_by_ticker: dict[str, list[dict[str, Any]]] | None = None
        if requested_start is None:
            raw_pit = json.loads(Path(pit_path).read_text(encoding="utf-8"))
            intervals_by_ticker = {}
            for iv in raw_pit.get("intervals", []):
                t = iv.get("ticker")
                if t:
                    intervals_by_ticker.setdefault(t, []).append(iv)

        results, failures, skipped = [], [], []
        for ticker in tickers:
            if requested_start is None:
                identity = resolve_current_identity(ticker, target_as_of, intervals_by_ticker or {})
                if identity.status != "RESOLVED":
                    skipped.append({"ticker": ticker, "reason": f"IDENTITY_{identity.status}"})
                    continue
                ticker_requested_start = str(identity.interval["effective_from"])
            else:
                ticker_requested_start = requested_start

            resolution = resolve_expected_coverage(
                ticker, ticker_requested_start, target_as_of, pit_path=pit_path, historical_calendar_path=historical_calendar_path
            )
            if resolution.authority_status == "ERROR":
                skipped.append({"ticker": ticker, "reason": resolution.authority_status})
                continue
            try:
                frame = self.provider.load_daily(ticker, ticker_requested_start, target_as_of)
                if frame.empty:
                    skipped.append({"ticker": ticker, "reason": "EMPTY_ADJUSTED_AUTHORITY"})
                    continue
                self.store.save_full(
                    ticker, frame, metadata_context={"requested_start": ticker_requested_start, "requested_end": target_as_of}
                )
                results.append(ticker)
            except Exception as exc:  # noqa: BLE001
                failures.append({"ticker": ticker, "error_type": type(exc).__name__})
        # The boundary only advances to target_as_of when every ticker actually reached it -- a
        # skip or failure means this leg did not fully cover target_as_of, so it must report the
        # unchanged current_boundary rather than let the coordinator assume full coverage.
        new_boundary = target_as_of if not failures and not skipped else current_boundary
        return {"leg": "common_adjusted", "updated": results, "skipped": skipped, "failures": failures, "new_boundary": new_boundary}


@dataclass(frozen=True)
class PitExtensionResult:
    """A validated, survivorship-safe rolling extension of the frozen PIT COMMON denominator
    (directive section 8-13, BLOCKER A). Never a mutation of the frozen artifact -- the frozen
    ``intervals`` are copied byte-for-byte into ``merged_intervals`` and only ever extended forward
    or appended to, never rewritten or removed."""

    merged_intervals: tuple[dict[str, Any], ...]
    merged_calendar_dates: tuple[str, ...]
    extension_start: str
    extension_end: str
    frozen_interval_count: int
    merged_interval_count: int
    new_ticker_count: int


def validate_pit_extension_survivorship_safety(
    frozen_intervals: Sequence[Mapping[str, Any]],
    new_intervals: Sequence[Mapping[str, Any]],
    boundary: str,
) -> list[str]:
    """Runtime assertion of the two invariants directive section 10 names explicitly:

    1. no ``new_intervals`` entry backdates a listing into the frozen population (its
       ``effective_from`` must be strictly after ``boundary`` -- a genuine new-window observation,
       never inferred from raw-row absence);
    2. no frozen ticker is removed -- checked structurally by the caller only ever *copying* (never
       filtering) ``frozen_intervals`` into the merge, so this function only needs to police the
       ``new_intervals`` side for backdating and for silently reusing a frozen key with a *shorter*
       effective_to (which would be a disguised truncation of history).
    """
    violations: list[str] = []
    frozen_latest_by_key: dict[tuple[str, Any, Any], str] = {}
    for iv in frozen_intervals:
        key = (iv.get("ticker"), iv.get("isu_cd"), iv.get("market"))
        frozen_latest_by_key[key] = max(frozen_latest_by_key.get(key, iv["effective_to"]), iv["effective_to"])

    for iv in new_intervals:
        if str(iv.get("effective_from")) <= boundary:
            violations.append(f"BACKDATED_NEW_INTERVAL:{iv.get('ticker')}:{iv.get('effective_from')}")
        key = (iv.get("ticker"), iv.get("isu_cd"), iv.get("market"))
        prior_end = frozen_latest_by_key.get(key)
        if prior_end is not None and str(iv.get("effective_to")) < prior_end:
            violations.append(
                f"EXTENSION_WOULD_SHORTEN_HISTORY:{iv.get('ticker')}:{prior_end}->{iv.get('effective_to')}"
            )
    return violations


def merge_pit_extension_intervals(
    frozen_intervals: Sequence[Mapping[str, Any]],
    new_intervals: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge new-window COMMON intervals into the frozen set.

    A continuation of an already-open identity (same ticker/isu_cd/market, still COMMON going into
    the frozen boundary) extends that frozen interval's ``effective_to`` forward in place -- it is
    never appended as a second, disjoint interval. A genuinely new identity (new listing, or a
    ticker-code reuse under a different ``isu_cd``) is appended as its own interval, exactly as the
    frozen artifact already models the 34 existing ticker-code-reuse cases. Frozen entries are always
    copied, never dropped -- a delisting observed during the extension window is represented by the
    *absence* of a continuation for that key, not by removing its frozen interval.
    """
    merged = [dict(iv) for iv in frozen_intervals]
    open_by_key: dict[tuple[str, Any, Any], dict[str, Any]] = {}
    for iv in merged:
        key = (iv.get("ticker"), iv.get("isu_cd"), iv.get("market"))
        if key not in open_by_key or iv["effective_to"] > open_by_key[key]["effective_to"]:
            open_by_key[key] = iv

    for niv in sorted(new_intervals, key=lambda x: (str(x.get("ticker")), str(x.get("effective_from")))):
        key = (niv.get("ticker"), niv.get("isu_cd"), niv.get("market"))
        continuation = open_by_key.get(key)
        if continuation is not None:
            if niv["effective_to"] > continuation["effective_to"]:
                continuation["effective_to"] = niv["effective_to"]
        else:
            appended = dict(niv)
            merged.append(appended)
            open_by_key[key] = appended
    return merged


def build_rolling_pit_extension(
    *,
    extension_calendar_dates: Sequence[str],
    frozen_pit_path: Path = DEFAULT_PIT_PATH,
    historical_calendar_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
    basic_info_raw_root: Path = DEFAULT_BASIC_INFO_RAW_ROOT,
    acquisition_checkpoint_path: Path = DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    acquisition_final_summary_path: Path = DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
) -> PitExtensionResult:
    """Attempt a genuine, survivorship-safe rolling extension of the frozen PIT COMMON denominator
    (BLOCKER A). Reuses ``load_basic_info_snapshots``/``classify_full_universe`` UNCHANGED -- the same
    authority (``TIER_A_KRX_OPEN_API_BASIC_INFO``) the frozen artifact itself was built from -- fed
    only with dates strictly after the frozen boundary, so anything it classifies is structurally
    incapable of backdating into the frozen population (section 9: never infer membership from raw
    OHLCV row presence/absence).

    Fails closed with :class:`InsufficientPitFrontierError` when the Basic Info acquisition archive
    does not yet cover ``extension_calendar_dates`` -- today's real production case, since the archive
    is itself frozen at the same 2026-08-21 boundary as everything else and genuinely extending it
    requires a new, live acquisition run (out of scope for this directive; no network calls here).
    """
    frozen = _read_json(frozen_pit_path)
    frozen_intervals = frozen.get("intervals", [])
    base_calendar = _read_json(historical_calendar_path)
    base_dates = list(base_calendar.get("trading_dates", []))
    if not base_dates:
        raise RollingAuthorityError("HISTORICAL_CALENDAR_EMPTY")
    boundary = max(base_dates)

    new_dates = sorted({d for d in extension_calendar_dates if d > boundary})
    if not new_dates:
        raise InsufficientPitFrontierError(
            f"NO_EXTENSION_CALENDAR_DATES_BEYOND_FROZEN_BOUNDARY: boundary={boundary}"
        )

    basic_info = load_basic_info_snapshots(
        basic_info_raw_root,
        calendar_dates=new_dates,
        acquisition_checkpoint_path=acquisition_checkpoint_path,
        acquisition_final_summary_path=acquisition_final_summary_path,
    )
    if not basic_info.ready:
        raise InsufficientPitFrontierError(
            "BASIC_INFO_ACQUISITION_AUTHORITY_INSUFFICIENT_FOR_EXTENSION: "
            f"status={basic_info.status} extension_dates={new_dates[0]}..{new_dates[-1]}"
        )

    extended_timeline = classify_full_universe(basic_info.snapshots, expected_dates=new_dates)
    new_common_intervals: list[dict[str, Any]] = []
    for ticker, intervals in extended_timeline.items():
        for iv in intervals:
            if iv.get("classification") != "COMMON":
                continue
            new_common_intervals.append(
                {
                    "ticker": ticker,
                    "isu_cd": iv.get("ISU_CD"),
                    "market": iv.get("market"),
                    "state": "COMMON",
                    "effective_from": iv["effective_from"],
                    "effective_to": iv["effective_to"],
                }
            )

    violations = validate_pit_extension_survivorship_safety(frozen_intervals, new_common_intervals, boundary)
    if violations:
        raise RollingAuthorityError(f"PIT_EXTENSION_SURVIVORSHIP_VIOLATION: {violations}")

    merged_intervals = merge_pit_extension_intervals(frozen_intervals, new_common_intervals)
    frozen_tickers = {iv.get("ticker") for iv in frozen_intervals}
    new_ticker_count = len({iv["ticker"] for iv in new_common_intervals} - frozen_tickers)

    return PitExtensionResult(
        merged_intervals=tuple(merged_intervals),
        merged_calendar_dates=tuple(sorted(set(base_dates) | set(new_dates))),
        extension_start=new_dates[0],
        extension_end=new_dates[-1],
        frozen_interval_count=len(frozen_intervals),
        merged_interval_count=len(merged_intervals),
        new_ticker_count=new_ticker_count,
    )


# Directive COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01 section 8-13/16-17: a durable, on-disk copy
# of the current PitExtensionResult, so both the repair orchestration and MarketDataRepositoryV2's
# read-side identity guard resolve the SAME (ticker, isu_cd, market) authority without recomputing
# build_rolling_pit_extension() (a Basic-Info-snapshot classification pass) on every read.
DEFAULT_MERGED_PIT_PATH = DEFAULT_ROLLING_AUTHORITY_DIR / "merged_pit_intervals.json"
DEFAULT_MERGED_CALENDAR_PATH = DEFAULT_ROLLING_AUTHORITY_DIR / "merged_trading_calendar.json"

# Directive ROLLING_AUTHORITY_HARDENING_V01 section 5-17: the merged PIT/calendar artifacts get
# their own schema-versioned wrapper + content digest, referenced from manifest.json, so a tampered,
# stale, or mismatched merged authority file fails closed instead of being trusted silently (the
# exact gap flagged as a MAJOR finding at the end of COMMON_ADJUSTED_PHANTOM_ROW_REMEDIATION_V01).
MERGED_PIT_SCHEMA_VERSION = "MERGED_PIT_V01"
MERGED_CALENDAR_SCHEMA_VERSION = "MERGED_CALENDAR_V01"


def _content_digest(items: Sequence[Any]) -> str:
    """Stable sha256 over a bare JSON list, mirroring ``_manifest_digest``'s canonicalization so the
    project has one digest style. Deliberately hashes ONLY the payload list (``intervals`` /
    ``trading_dates``), never the metadata wrapper around it -- the wrapper's own fields (frontier,
    built_at_utc, ...) are cross-checked against the manifest separately."""
    blob = json.dumps(list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MergedAuthorityPublishResult:
    """The digests/frontiers a caller must copy into ``RollingAuthorityManifest`` so the manifest
    references exactly what :func:`write_merged_pit_extension` just published."""

    merged_pit_digest: str
    merged_pit_frontier: str
    merged_pit_schema_version: str
    merged_calendar_digest: str
    merged_calendar_frontier: str
    merged_calendar_schema_version: str
    built_against_certified_through: str


_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_basic_info_frontier_field(
    source_basic_info_frontier: str,
    target_as_of: str,
    *,
    required_authority_frontier: str | None = None,
) -> None:
    """Directive ROLLING_AUTHORITY_FINAL_CLOSURE_V01 section 20-24: ``source_basic_info_frontier``
    is a DATE (the rolling Basic Info authority's own frontier, e.g. ``BASIC_INFO_AUTHORITY_FRONTIER``
    from the rolling acquisition archive's ``authorized_dates``), never an ISO-8601 acquisition
    ``completed_at_utc`` timestamp -- that is a structurally different concept and belongs in the
    separate ``source_basic_info_acquired_at_utc`` field instead. Fails closed via
    :class:`RollingAuthorityError` on any of: wrong shape (not exactly ``YYYY-MM-DD``), a frontier
    later than ``target_as_of`` (a structural impossibility), or a frontier earlier than a supplied
    ``required_authority_frontier`` (insufficient authority to certify this target)."""
    if not isinstance(source_basic_info_frontier, str) or not _DATE_ONLY_PATTERN.match(source_basic_info_frontier):
        raise RollingAuthorityError(
            f"SOURCE_BASIC_INFO_FRONTIER_INVALID_TYPE: expected a bare YYYY-MM-DD date, got "
            f"{source_basic_info_frontier!r} -- an ISO-8601 timestamp (acquired_at) must never be used "
            "as a frontier value"
        )
    if source_basic_info_frontier > target_as_of:
        raise RollingAuthorityError(
            f"SOURCE_BASIC_INFO_FRONTIER_EXCEEDS_TARGET_AS_OF: frontier={source_basic_info_frontier} "
            f"target_as_of={target_as_of}"
        )
    if required_authority_frontier is not None and source_basic_info_frontier < required_authority_frontier:
        raise RollingAuthorityError(
            f"SOURCE_BASIC_INFO_FRONTIER_INSUFFICIENT_AUTHORITY: frontier={source_basic_info_frontier} "
            f"required={required_authority_frontier}"
        )


def write_merged_pit_extension(
    extension: PitExtensionResult,
    directory: Path = DEFAULT_ROLLING_AUTHORITY_DIR,
    *,
    built_against_certified_through: str,
    target_as_of: str | None = None,
    source_basic_info_frontier: str | None = None,
    source_basic_info_acquired_at_utc: str | None = None,
) -> MergedAuthorityPublishResult:
    """Atomically publish ``extension``'s merged intervals/calendar (temp file + os.replace,
    mirroring ``write_rolling_authority``), each wrapped with coherence metadata (schema_version,
    built_at_utc, frontier, built_against_certified_through, content_digest). Never mutates the
    frozen PIT/calendar artifacts this extension was built from -- this is a separate, additive,
    rolling-authority-owned artifact.

    Returns the exact digests/frontiers the caller must then write into the manifest via
    :func:`write_rolling_authority` -- publishing the manifest reference is the caller's
    responsibility (section 15's ordering contract: build -> validate -> digest -> publish manifest).
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pit_final = directory / "merged_pit_intervals.json"
    cal_final = directory / "merged_trading_calendar.json"

    intervals = list(extension.merged_intervals)
    calendar_dates = list(extension.merged_calendar_dates)
    pit_digest = _content_digest(intervals)
    cal_digest = _content_digest(calendar_dates)
    pit_frontier = max((str(iv.get("effective_to")) for iv in intervals), default="")
    cal_frontier = max((str(d) for d in calendar_dates), default="")
    built_at = _iso_today_utc()
    resolved_target_as_of = target_as_of if target_as_of is not None else extension.extension_end

    if source_basic_info_frontier is not None:
        validate_basic_info_frontier_field(source_basic_info_frontier, resolved_target_as_of)

    pit_payload = {
        "schema_version": MERGED_PIT_SCHEMA_VERSION,
        "authority_version": ROLLING_AUTHORITY_VERSION,
        "built_at_utc": built_at,
        "target_as_of": resolved_target_as_of,
        "pit_frontier": pit_frontier,
        "built_against_certified_through": built_against_certified_through,
        "source_basic_info_frontier": source_basic_info_frontier,
        "source_basic_info_acquired_at_utc": source_basic_info_acquired_at_utc,
        "content_digest": pit_digest,
        "intervals": intervals,
    }
    cal_payload = {
        "schema_version": MERGED_CALENDAR_SCHEMA_VERSION,
        "authority_version": ROLLING_AUTHORITY_VERSION,
        "built_at_utc": built_at,
        "calendar_frontier": cal_frontier,
        "built_against_certified_through": built_against_certified_through,
        "content_digest": cal_digest,
        "trading_dates": calendar_dates,
    }

    pit_token, cal_token = uuid.uuid4().hex, uuid.uuid4().hex
    pit_temp = directory / f".merged_pit_intervals.json.tmp_{pit_token}"
    cal_temp = directory / f".merged_trading_calendar.json.tmp_{cal_token}"
    pit_temp.write_text(json.dumps(pit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cal_temp.write_text(json.dumps(cal_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(pit_temp, pit_final)
    os.replace(cal_temp, cal_final)

    return MergedAuthorityPublishResult(
        merged_pit_digest=pit_digest,
        merged_pit_frontier=pit_frontier,
        merged_pit_schema_version=MERGED_PIT_SCHEMA_VERSION,
        merged_calendar_digest=cal_digest,
        merged_calendar_frontier=cal_frontier,
        merged_calendar_schema_version=MERGED_CALENDAR_SCHEMA_VERSION,
        built_against_certified_through=built_against_certified_through,
    )


def validate_merged_authority_coherence(
    manifest: "RollingAuthorityManifest", directory: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail-closed coherence check between ``manifest.json`` and the merged PIT/calendar files it
    references (directive ROLLING_AUTHORITY_HARDENING_V01 section 9-13). Reads both files directly
    (never through ``adjusted_price_pilot``'s ``lru_cache``'d readers, which are keyed on a stable
    path here and would otherwise risk serving a stale cached mapping alongside freshly-read
    metadata) and returns the parsed payloads so the caller resolves identity against exactly what
    was just validated.

    Raises :class:`RollingAuthorityError` -- with zero fallback to unclamped/ignore-checksum/
    warn-and-continue behavior -- for: a manifest not yet migrated to this schema (missing
    references), a missing merged authority file, a schema/version mismatch, a digest mismatch
    (against the file's own stored digest OR the manifest's reference), a frontier mismatch, or a
    merged authority built against a certified_through LATER than the manifest's current one (which
    would mean the file is from the future relative to the manifest -- a structural impossibility).

    ``built_against_certified_through`` is deliberately NOT required to equal the manifest's current
    ``certified_through`` exactly: a boundary-only promotion (raw/adjusted legs advancing without any
    new identity ever appearing) legitimately does not require republishing the merged PIT, so
    ``built_against_certified_through <= certified_through`` is the correct invariant, not equality.
    """
    directory = Path(directory)
    pit_path = directory / "merged_pit_intervals.json"
    cal_path = directory / "merged_trading_calendar.json"

    if manifest.merged_pit_digest is None or manifest.merged_pit_frontier is None or manifest.merged_pit_schema_version is None:
        raise RollingAuthorityError(
            "ROLLING_MANIFEST_MISSING_MERGED_PIT_REFERENCE: manifest not migrated to the "
            "coherence-contract schema (ROLLING_AUTHORITY_HARDENING_V01)"
        )
    if (
        manifest.merged_calendar_digest is None
        or manifest.merged_calendar_frontier is None
        or manifest.merged_calendar_schema_version is None
    ):
        raise RollingAuthorityError(
            "ROLLING_MANIFEST_MISSING_MERGED_CALENDAR_REFERENCE: manifest not migrated to the "
            "coherence-contract schema (ROLLING_AUTHORITY_HARDENING_V01)"
        )
    if not pit_path.exists():
        raise RollingAuthorityError(f"MERGED_PIT_ARTIFACT_MISSING_FOR_PRODUCTION_ROLLING_MODE: {pit_path}")
    if not cal_path.exists():
        raise RollingAuthorityError(f"MERGED_CALENDAR_ARTIFACT_MISSING_FOR_PRODUCTION_ROLLING_MODE: {cal_path}")

    pit_payload = json.loads(pit_path.read_text(encoding="utf-8"))
    cal_payload = json.loads(cal_path.read_text(encoding="utf-8"))

    if pit_payload.get("schema_version") != manifest.merged_pit_schema_version:
        raise RollingAuthorityError(
            f"MERGED_PIT_SCHEMA_VERSION_MISMATCH: file={pit_payload.get('schema_version')!r} "
            f"manifest={manifest.merged_pit_schema_version!r}"
        )
    recomputed_pit_digest = _content_digest(pit_payload.get("intervals", []))
    if pit_payload.get("content_digest") != recomputed_pit_digest:
        raise RollingAuthorityError(
            f"MERGED_PIT_CONTENT_DIGEST_SELF_MISMATCH: stored={pit_payload.get('content_digest')!r} "
            f"recomputed={recomputed_pit_digest!r}"
        )
    if recomputed_pit_digest != manifest.merged_pit_digest:
        raise RollingAuthorityError(
            f"MERGED_PIT_DIGEST_MISMATCH_WITH_MANIFEST: file={recomputed_pit_digest!r} "
            f"manifest={manifest.merged_pit_digest!r}"
        )
    if pit_payload.get("pit_frontier") != manifest.merged_pit_frontier:
        raise RollingAuthorityError(
            f"MERGED_PIT_FRONTIER_MISMATCH_WITH_MANIFEST: file={pit_payload.get('pit_frontier')!r} "
            f"manifest={manifest.merged_pit_frontier!r}"
        )
    pit_built_against = str(pit_payload.get("built_against_certified_through") or "")
    if pit_built_against > manifest.certified_through:
        raise RollingAuthorityError(
            "MERGED_PIT_BUILT_AGAINST_FUTURE_CERTIFIED_THROUGH: "
            f"merged_pit_built_against={pit_built_against} manifest_certified_through={manifest.certified_through}"
        )

    if cal_payload.get("schema_version") != manifest.merged_calendar_schema_version:
        raise RollingAuthorityError(
            f"MERGED_CALENDAR_SCHEMA_VERSION_MISMATCH: file={cal_payload.get('schema_version')!r} "
            f"manifest={manifest.merged_calendar_schema_version!r}"
        )
    recomputed_cal_digest = _content_digest(cal_payload.get("trading_dates", []))
    if cal_payload.get("content_digest") != recomputed_cal_digest:
        raise RollingAuthorityError(
            f"MERGED_CALENDAR_CONTENT_DIGEST_SELF_MISMATCH: stored={cal_payload.get('content_digest')!r} "
            f"recomputed={recomputed_cal_digest!r}"
        )
    if recomputed_cal_digest != manifest.merged_calendar_digest:
        raise RollingAuthorityError(
            f"MERGED_CALENDAR_DIGEST_MISMATCH_WITH_MANIFEST: file={recomputed_cal_digest!r} "
            f"manifest={manifest.merged_calendar_digest!r}"
        )
    if cal_payload.get("calendar_frontier") != manifest.merged_calendar_frontier:
        raise RollingAuthorityError(
            f"MERGED_CALENDAR_FRONTIER_MISMATCH_WITH_MANIFEST: file={cal_payload.get('calendar_frontier')!r} "
            f"manifest={manifest.merged_calendar_frontier!r}"
        )
    cal_built_against = str(cal_payload.get("built_against_certified_through") or "")
    if cal_built_against > manifest.certified_through:
        raise RollingAuthorityError(
            "MERGED_CALENDAR_BUILT_AGAINST_FUTURE_CERTIFIED_THROUGH: "
            f"merged_calendar_built_against={cal_built_against} manifest_certified_through={manifest.certified_through}"
        )

    return pit_payload, cal_payload


@dataclass(frozen=True)
class IdentityResolution:
    """Result of resolving the CURRENT certified (ticker, isu_cd, market) identity as of a given
    date (directive section 5/16/17: never a ticker-only earliest-interval shortcut)."""

    ticker: str
    as_of: str
    status: str  # "RESOLVED" | "AMBIGUOUS" | "NO_OPEN_IDENTITY"
    interval: dict[str, Any] | None
    candidate_intervals: tuple[dict[str, Any], ...]


def _combine_same_isu_intervals(isu_cd: Any, ivs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Collapse one identity's (possibly market-transfer-split) interval rows into one combined
    range. A market transfer (e.g. KOSDAQ -> KOSPI) re-keys ``(ticker, isu_cd, market)`` even though
    it is the SAME real corporate identity and the SAME isu_cd -- its true history spans the union of
    all such rows, not just the most recent market's own interval (directive section 16's "current
    identity" is about distinct SECURITIES, not about market re-listing)."""
    latest = max(ivs, key=lambda iv: str(iv.get("effective_to")))
    return {
        **latest,
        "isu_cd": isu_cd,
        "effective_from": min(str(iv.get("effective_from")) for iv in ivs),
        "effective_to": max(str(iv.get("effective_to")) for iv in ivs),
        "component_intervals": tuple(ivs),
    }


def resolve_current_identity(
    ticker: str, as_of: str, intervals_by_ticker: Mapping[str, Sequence[Mapping[str, Any]]]
) -> IdentityResolution:
    """Resolve the single CURRENT (ticker, isu_cd) COMMON identity relevant to ``as_of``.

    ``intervals_by_ticker`` is keyed by bare ticker string (as produced by
    ``adjusted_price_pilot._load_cached_pit_intervals_by_ticker`` over the merged PIT) and may map to
    MORE THAN ONE interval row for two structurally different reasons that must NOT be conflated:

    1. A market transfer (same isu_cd, ``market`` changes, e.g. KOSDAQ -> KOSPI) -- rows are combined
       via :func:`_combine_same_isu_intervals` into one identity spanning the union of all its rows.
    2. A genuinely reused ticker code (DIFFERENT isu_cd values under the same numeric code) -- these
       are grouped separately by isu_cd first, THEN each group's own combined range is checked for
       whether it covers ``as_of``. Directive section 16 explicitly forbids resolving via "earliest
       effective_from" across the whole ticker (that is exactly the mistake that caused the
       phantom-row defect) -- grouping by isu_cd first prevents that.

    - Exactly one distinct isu_cd recorded for this ticker: that combined identity IS the answer,
      regardless of whether it happens to cover ``as_of`` -- a normal, already-delisted single-identity
      ticker queried at a later date is not ambiguous, and its own combined bounds are what any clamp
      should use.
    - Two or more distinct isu_cd values recorded: filter to the per-isu_cd combined ranges whose
      ``effective_from <= as_of <= effective_to``. Exactly one covering match is RESOLVED. Zero
      covering matches means no identity is authoritative for ``as_of`` under this reused code (e.g. a
      genuine gap between two occupants) -- an explainable, non-ambiguous absence, not a fetch/
      visibility authority (NO_OPEN_IDENTITY). More than one covering match is a genuine, unexpected
      ambiguity and must fail closed -- never pick one arbitrarily.
    - Zero intervals recorded at all: NO_OPEN_IDENTITY (no COMMON authority exists for this ticker).
    """
    all_candidates = tuple(intervals_by_ticker.get(ticker, ()))
    if len(all_candidates) == 0:
        return IdentityResolution(ticker, as_of, "NO_OPEN_IDENTITY", None, all_candidates)

    by_isu: dict[Any, list[dict[str, Any]]] = {}
    for iv in all_candidates:
        by_isu.setdefault(iv.get("isu_cd"), []).append(dict(iv))
    combined_by_isu = {isu_cd: _combine_same_isu_intervals(isu_cd, ivs) for isu_cd, ivs in by_isu.items()}

    if len(combined_by_isu) == 1:
        (only,) = combined_by_isu.values()
        return IdentityResolution(ticker, as_of, "RESOLVED", only, all_candidates)

    covering = tuple(
        iv for iv in combined_by_isu.values() if str(iv["effective_from"]) <= as_of <= str(iv["effective_to"])
    )
    if len(covering) == 1:
        return IdentityResolution(ticker, as_of, "RESOLVED", covering[0], all_candidates)
    if len(covering) == 0:
        return IdentityResolution(ticker, as_of, "NO_OPEN_IDENTITY", None, all_candidates)
    return IdentityResolution(ticker, as_of, "AMBIGUOUS", None, all_candidates)


class RollingRefreshCoordinator:
    """Sequences all four legs and promotes the certified boundary atomically, only when every
    required leg reaches ``target_as_of``. A failed or blocked leg leaves the existing manifest file
    untouched -- there is no partial-promotion code path."""

    def __init__(
        self,
        *,
        raw_updater: RollingRawMarketUpdater,
        raw_etf_updater: RollingRawEtfUpdater,
        etf_adjusted_updater: RollingEtfAdjustedUpdater,
        common_adjusted_updater: RollingAdjustedPriceUpdater,
        common_adjusted_tickers: Sequence[str],
        authority_dir: Path = DEFAULT_ROLLING_AUTHORITY_DIR,
        raw_store: KrxRawStockStore | None = None,
        adjusted_store: AdjustedPriceStore | None = None,
    ) -> None:
        self.raw_updater = raw_updater
        self.raw_etf_updater = raw_etf_updater
        self.etf_adjusted_updater = etf_adjusted_updater
        self.common_adjusted_updater = common_adjusted_updater
        self.common_adjusted_tickers = common_adjusted_tickers
        self.authority_dir = Path(authority_dir)
        # Optional: when both are supplied, execute() enforces the pre/post historical-mutation
        # guard (directive section 28) automatically. Omitted by callers (e.g. unit tests using fake
        # leg updaters with no real stores) simply skip the guard rather than failing.
        self.raw_store = raw_store
        self.adjusted_store = adjusted_store

    def plan(self, target_as_of: str) -> dict[str, Any]:
        manifest = load_rolling_authority(self.authority_dir)
        return {
            "current_certified_through": manifest.certified_through,
            "target_as_of": target_as_of,
            "leg_boundaries": dict(manifest.leg_boundaries),
            "common_raw": self.raw_updater.plan(manifest.leg_boundaries["common_raw"], target_as_of),
            "etf_raw": self.raw_etf_updater.plan(manifest.leg_boundaries["etf_raw"], target_as_of),
        }

    def execute(self, target_as_of: str, *, dry_run: bool = True) -> dict[str, Any]:
        manifest = load_rolling_authority(self.authority_dir)
        if target_as_of <= manifest.certified_through:
            return {"status": "NOOP_ALREADY_CERTIFIED", "certified_through": manifest.certified_through}
        if dry_run:
            return {"status": "DRY_RUN", "plan": self.plan(target_as_of)}

        guard_tickers = [*self.common_adjusted_tickers, *ETF_VALIDATED_ACCEPTANCE_TICKERS]
        pre_fingerprint = (
            history_fingerprint(self.raw_store, self.adjusted_store, guard_tickers, manifest.certified_through)
            if self.raw_store is not None and self.adjusted_store is not None
            else None
        )

        leg_results: dict[str, Any] = {}
        try:
            leg_results["common_raw"] = self.raw_updater.refresh(manifest.leg_boundaries["common_raw"], target_as_of)
            leg_results["etf_raw"] = self.raw_etf_updater.refresh(manifest.leg_boundaries["etf_raw"], target_as_of)
            leg_results["etf_adjusted"] = self.etf_adjusted_updater.refresh(manifest.leg_boundaries["etf_adjusted"], target_as_of)
            leg_results["common_adjusted"] = self.common_adjusted_updater.refresh(
                self.common_adjusted_tickers, manifest.leg_boundaries["common_adjusted"], target_as_of
            )
        except Exception as exc:
            return {
                "status": "FAILED",
                "certified_through": manifest.certified_through,
                "boundary_unchanged": True,
                "leg_results_before_failure": leg_results,
                "error": str(exc),
            }

        new_leg_boundaries = {
            "common_raw": leg_results["common_raw"]["new_boundary"],
            "etf_raw": leg_results["etf_raw"]["new_boundary"],
            "etf_adjusted": leg_results["etf_adjusted"]["new_boundary"],
            "common_adjusted": leg_results["common_adjusted"]["new_boundary"],
        }
        new_certified = _coherent_boundary(new_leg_boundaries)
        if new_certified <= manifest.certified_through:
            return {
                "status": "NO_ADVANCE",
                "certified_through": manifest.certified_through,
                "boundary_unchanged": True,
                "leg_results": leg_results,
                "new_leg_boundaries": new_leg_boundaries,
            }

        if pre_fingerprint is not None:
            post_fingerprint = history_fingerprint(self.raw_store, self.adjusted_store, guard_tickers, manifest.certified_through)
            if post_fingerprint != pre_fingerprint:
                return {
                    "status": "FAILED",
                    "certified_through": manifest.certified_through,
                    "boundary_unchanged": True,
                    "leg_results": leg_results,
                    "error": "PREVIOUS_CERTIFIED_HISTORY_MUTATION_DETECTED",
                    "pre_fingerprint": pre_fingerprint,
                    "post_fingerprint": post_fingerprint,
                }

        new_manifest = RollingAuthorityManifest(
            authority_version=manifest.authority_version,
            certified_through=new_certified,
            leg_boundaries=new_leg_boundaries,
            previous_boundary=manifest.certified_through,
            raw_store_version=manifest.raw_store_version,
            adjusted_store_version=manifest.adjusted_store_version,
            instrument_contract_version=manifest.instrument_contract_version,
            bootstrap_source=manifest.bootstrap_source,
            generated_at=_iso_today_utc(),
        )
        write_rolling_authority(new_manifest, self.authority_dir)
        return {"status": "PROMOTED", "certified_through": new_certified, "previous_boundary": manifest.certified_through, "leg_results": leg_results}


def history_fingerprint(raw_store: KrxRawStockStore, adjusted_store: AdjustedPriceStore, tickers: Sequence[str], boundary: str) -> dict[str, str]:
    """Stable digest of everything at/before ``boundary``, for the pre/post mutation guard.

    Raw: hash of the manifest's own recorded ``content_sha256`` per (market, date) -- cheap, and
    those digests were themselves computed from partition file bytes at write time; a raw partition
    file for a date <= ``boundary`` is never rewritten by this refresh, so its manifest row is a valid
    proxy for its content.

    Adjusted: ``AdjustedPriceStore.save_full`` rewrites each ticker's *entire* file, so its stored
    ``content_sha256`` legitimately changes on every touched ticker regardless of whether pre-boundary
    rows actually changed -- it cannot be the mutation signal. This instead reads each ticker's
    ``date <= boundary`` slice directly (via ``load_daily(..., end=boundary)``) and hashes the actual
    values, for a caller-supplied, *fixed* ``tickers`` list (the pre-refresh ticker set) so a
    before/after comparison is never confused by tickers a refresh newly added.
    """
    raw_rows = sorted(
        (str(r["market"]), str(r["date"]), str(r.get("content_sha256") or ""))
        for r in raw_store.list_manifest()
        if str(r["date"]) <= boundary
    )
    raw_digest = hashlib.sha256(json.dumps(raw_rows, separators=(",", ":")).encode()).hexdigest()

    adjusted_rows = []
    for ticker in sorted(tickers):
        if not adjusted_store.exists(ticker):
            adjusted_rows.append((ticker, ""))
            continue
        frame = adjusted_store.load_daily(ticker, end=boundary)
        payload = frame.round(6).to_csv() if not frame.empty else ""
        adjusted_rows.append((ticker, hashlib.sha256(payload.encode()).hexdigest()))
    adjusted_digest = hashlib.sha256(json.dumps(adjusted_rows, separators=(",", ":")).encode()).hexdigest()
    return {"raw_history_sha256": raw_digest, "adjusted_history_sha256": adjusted_digest}


def count_rows_after(dates: Sequence[str], target_as_of: str) -> int:
    """Future-row guard (directive section 29): count observations strictly after ``target_as_of``."""
    return sum(1 for d in dates if str(d)[:10] > target_as_of)


__all__ = [
    "ROLLING_AUTHORITY_VERSION",
    "DEFAULT_ROLLING_AUTHORITY_DIR",
    "DEFAULT_REMOVED_IDENTITY_AUDIT_PATH",
    "DEFAULT_ZERO_STORE_CONTRACT_PATH",
    "DEFAULT_FULL_POPULATION_CLOSURE_RESULTS_PATH",
    "REQUIRED_LEGS",
    "ETF_VALIDATED_ACCEPTANCE_TICKERS",
    "RollingAuthorityError",
    "InsufficientPitFrontierError",
    "RefreshLegFailure",
    "RollingAuthorityManifest",
    "load_rolling_authority",
    "write_rolling_authority",
    "bootstrap_rolling_authority",
    "PopulationAuditRecord",
    "PopulationBootstrapAudit",
    "audit_full_population_bootstrap",
    "bootstrap_rolling_authority_v2",
    "PitExtensionResult",
    "validate_pit_extension_survivorship_safety",
    "merge_pit_extension_intervals",
    "build_rolling_pit_extension",
    "DEFAULT_MERGED_PIT_PATH",
    "DEFAULT_MERGED_CALENDAR_PATH",
    "MERGED_PIT_SCHEMA_VERSION",
    "MERGED_CALENDAR_SCHEMA_VERSION",
    "MergedAuthorityPublishResult",
    "write_merged_pit_extension",
    "validate_basic_info_frontier_field",
    "validate_merged_authority_coherence",
    "IdentityResolution",
    "resolve_current_identity",
    "RollingRawMarketUpdater",
    "RollingRawEtfUpdater",
    "RollingEtfAdjustedUpdater",
    "RollingAdjustedPriceUpdater",
    "RollingRefreshCoordinator",
    "history_fingerprint",
    "count_rows_after",
    "candidate_dates",
]
