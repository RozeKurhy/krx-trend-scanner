"""Offline historical-universe authority reconciliation harness.

This module intentionally has no network client.  It prepares and validates
the reconciliation that will consume the KRX Basic Info PIT archive after the
separate acquisition phase completes.  The default path is a preflight: a
missing raw archive is represented as a normal waiting state and never causes
an implicit download.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence


EXPECTED_TARGET_TOTAL = 1116
EXPECTED_NUMERIC_TOTAL = 1058
EXPECTED_ALPHANUMERIC_TOTAL = 58
HISTORICAL_START = "2010-01-04"
HISTORICAL_END = "2026-08-21"
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")

_ARTIFACTS = Path("artifacts")
DEFAULT_TARGET_IDENTITY_PATH = (
    _ARTIFACTS
    / "data/end_to_end_data_parity/v01/"
    / "historical_universe_authority_reconciliation/v01/harness_implementation/"
    / "target_identities.json"
)
DEFAULT_TARGET_SUMMARY_PATH = (
    _ARTIFACTS
    / "data/end_to_end_data_parity/v01/adjusted_population_preflight/fix01/"
    / "historical_universe_reconciliation.json"
)
DEFAULT_RAW_ROOT = Path("data/reference/source/history/krx_instrument_master/v01/basic_info")
DEFAULT_CALENDAR_PATH = Path("data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
DEFAULT_ACQUISITION_CHECKPOINT_PATH = Path("data/reference/source/history/krx_instrument_master/v01/checkpoint.json")
DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH = Path(
    "data/reference/source/history/krx_instrument_master/v01/acquisition_final_summary.json"
)
DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR = Path(
    "data/reference/source/history/krx_instrument_master/v01/supplemental_authority"
)
DEFAULT_HARNESS_OUTPUT_DIR = (
    _ARTIFACTS
    / "data/end_to_end_data_parity/v01/"
    / "historical_universe_authority_reconciliation/v01/harness_implementation"
)

CLASS_COMMON = "COMMON"
CLASS_NOT_COMMON = "NOT_COMMON"
CLASS_UNRESOLVED = "UNRESOLVED"

HISTORICAL_COMMON_REQUIRED = "HISTORICAL_COMMON_REQUIRED"
HISTORICAL_NOT_COMMON = "HISTORICAL_NOT_COMMON"
HISTORICAL_AUTHORITY_UNRESOLVED = "HISTORICAL_AUTHORITY_UNRESOLVED"

AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION = "AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION"
BLOCKED_RECONCILIATION_INPUT_AUTHORITY = "BLOCKED_RECONCILIATION_INPUT_AUTHORITY"

# Acquisition closure contract (Section A).  The acquisition harness itself
# (``krx_historical_instrument_acquisition.py``) is never modified here; this
# module only consumes its checkpoint.json and an explicit final-summary
# artifact that a separate, already-approved acquisition execution produces.
READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION = "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
ACQUISITION_COMPLETE_STATUS = "COMPLETE"

# Production instrument-metadata authority alignment (Section E, Minor).
# docs/architecture/instrument_metadata_authority.md §6.1: a formally COMMON
# (보통주) row filed under the 관리종목(소속부없음) section is fail-closed to
# UNKNOWN when the same ticker also carries a Tier A SPAC-section observation
# anywhere in its history.  ``classify_security_type`` stays row-pure; this
# label only feeds the cross-observation alignment step below.
_MANAGED_ISSUE_SECTION = "관리종목(소속부없음)"
PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY = (
    "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY"
)

# Supplemental authority layer (HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01).
# KRX PIT Basic Info stays the sole primary authority and is never modified;
# these records add official non-Basic-Info evidence (OpenDART filings, KRX
# official issue-name fields) keyed by (target_ticker, ISU_CD) so a specific,
# individually-investigated identity can be resolved without widening any
# row-pure classification rule. Absence of a record is never an implicit
# resolution — see ``load_supplemental_authority_records``.
SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED = "SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED"
SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_ABSORBED_TERMINATED = "SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_ABSORBED_TERMINATED"
SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED = "SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED"
SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED = "SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED"
SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT = "SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT"
_SUPPLEMENTAL_DECISION_TO_CLASS = {"COMMON": CLASS_COMMON, "NOT_COMMON": CLASS_NOT_COMMON}


class ReconciliationContractError(RuntimeError):
    """Fail-closed contract error with a reportable terminal status."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _normalise_ticker(value: Any) -> str:
    """Require a six-character string; never cast numeric identifiers."""

    if not isinstance(value, str):
        raise ReconciliationContractError(
            "BLOCKED_TARGET_IDENTITY_CONTRACT", "ticker must remain a string"
        )
    ticker = value.strip()
    if ticker != ticker.upper() or not TICKER_RE.fullmatch(ticker):
        raise ReconciliationContractError(
            "BLOCKED_TARGET_IDENTITY_CONTRACT", f"invalid ticker identifier: {value!r}"
        )
    return ticker


def _normalise_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ReconciliationContractError(
            BLOCKED_RECONCILIATION_INPUT_AUTHORITY, f"invalid effective date: {value!r}"
        ) from exc


def canonical_target_identity_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and sort the target set without changing identifier strings."""

    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "target record is not an object")
        ticker = _normalise_ticker(raw.get("ticker"))
        if ticker in seen:
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", f"duplicate target ticker: {ticker}")
        identity_type = str(raw.get("identity_type", "")).strip().lower()
        expected_type = "numeric" if ticker.isdigit() else "alphanumeric"
        if identity_type != expected_type:
            raise ReconciliationContractError(
                "BLOCKED_TARGET_IDENTITY_CONTRACT",
                f"{ticker}: identity_type must be {expected_type}",
            )
        current_presence = raw.get("current_presence")
        if not isinstance(current_presence, bool):
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", f"{ticker}: current_presence must be boolean")
        source = raw.get("source", raw.get("provenance"))
        if not isinstance(source, (str, Mapping)):
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", f"{ticker}: source/provenance is required")
        entry = dict(raw)
        entry["ticker"] = ticker
        entry["identity_type"] = identity_type
        entry["current_presence"] = current_presence
        entry.setdefault("identity_key", f"ticker:{ticker}")
        canonical.append(entry)
        seen.add(ticker)

    canonical.sort(key=lambda row: (str(row["ticker"]), str(row["identity_type"])))
    return canonical


def target_identity_set_hash(records: Iterable[Mapping[str, Any]]) -> str:
    """Hash contract: sorted ``ticker|identity_type`` lines with final newline."""

    rows = canonical_target_identity_records(records)
    serialised = "\n".join(f"{row['ticker']}|{row['identity_type']}" for row in rows) + "\n"
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


canonical_target_set_hash = target_identity_set_hash


def _validate_target_counts(records: Sequence[Mapping[str, Any]], *, expected: bool = True) -> dict[str, int]:
    counts = {
        "total": len(records),
        "numeric": sum(str(row["ticker"]).isdigit() for row in records),
        "alphanumeric": sum(not str(row["ticker"]).isdigit() for row in records),
    }
    if expected and counts != {
        "total": EXPECTED_TARGET_TOTAL,
        "numeric": EXPECTED_NUMERIC_TOTAL,
        "alphanumeric": EXPECTED_ALPHANUMERIC_TOTAL,
    }:
        raise ReconciliationContractError(
            "BLOCKED_TARGET_IDENTITY_CONTRACT",
            f"target counts mismatch: {counts}",
        )
    return counts


def load_target_identities(
    path: str | Path = DEFAULT_TARGET_IDENTITY_PATH,
    *,
    expected: bool = True,
) -> dict[str, Any]:
    """Load the compact, deterministic 1116-identity target artifact."""

    target_path = Path(path)
    if not target_path.is_file():
        raise ReconciliationContractError(
            "BLOCKED_TARGET_IDENTITY_CONTRACT", f"target identity artifact is missing: {target_path}"
        )
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "target identity artifact is unreadable") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("identities"), list):
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "target identity artifact shape is invalid")
    records = canonical_target_identity_records(payload["identities"])
    counts = _validate_target_counts(records, expected=expected)
    digest = target_identity_set_hash(records)
    declared = payload.get("target_identity_set_sha256")
    if declared != digest:
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "target identity hash mismatch")
    return {
        **dict(payload),
        "path": str(target_path),
        "identities": records,
        "counts": counts,
        "target_identity_set_sha256": digest,
    }


def derive_target_identities(
    historical_rows: Iterable[Mapping[str, Any]],
    current_common_tickers: Iterable[str],
    *,
    expected: bool = False,
    source: str = "local historical market-data inventory minus verified current COMMON",
) -> dict[str, Any]:
    """Derive target identities from local historical rows and current authority."""

    current = {_normalise_ticker(value) for value in current_common_tickers}
    inventory: dict[str, dict[str, Any]] = {}
    for row in historical_rows:
        if not isinstance(row, Mapping):
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "historical inventory row is not an object")
        ticker = _normalise_ticker(row.get("ticker"))
        day = _normalise_date(row.get("date"))
        market = str(row.get("market", "")).strip().upper()
        if market not in {"KOSPI", "KOSDAQ"}:
            raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", f"{ticker}: invalid market {market!r}")
        item = inventory.setdefault(ticker, {"dates": [], "markets": set(), "row_count": 0})
        item["dates"].append(day)
        item["markets"].add(market)
        item["row_count"] += 1

    targets: list[dict[str, Any]] = []
    for ticker in sorted(set(inventory) - current):
        item = inventory[ticker]
        identity_type = "numeric" if ticker.isdigit() else "alphanumeric"
        targets.append(
            {
                "ticker": ticker,
                "identity_key": f"ticker:{ticker}",
                "identity_type": identity_type,
                "current_presence": False,
                "source": source,
                "provenance": {
                    "historical_inventory": "data/market/raw/krx_stocks/v01",
                    "current_common_authority": "data/reference/krx_instrument_metadata.parquet",
                    "effective_date": "verified snapshot date from metadata manifest",
                },
                "observed_date_min": min(item["dates"]),
                "observed_date_max": max(item["dates"]),
                "markets_seen": sorted(item["markets"]),
                "historical_row_count": item["row_count"],
            }
        )
    canonical = canonical_target_identity_records(targets)
    counts = _validate_target_counts(canonical, expected=expected)
    return {
        "schema": "historical_universe_authority_target_identity_v01",
        "generated_offline": True,
        "source": source,
        "historical_period": [HISTORICAL_START, HISTORICAL_END],
        "identities": canonical,
        "counts": counts,
        "target_identity_set_sha256": target_identity_set_hash(canonical),
        "serialization": "sorted UTF-8 lines: ticker|identity_type plus final newline",
    }


def derive_target_identities_from_repository(repo_root: str | Path = ".") -> dict[str, Any]:
    """Reproduce the frozen 1116 target set using only local parquet files."""

    root = Path(repo_root)
    raw_root = root / "data/market/raw/krx_stocks/v01"
    files = sorted(raw_root.rglob("*.parquet"))
    if not files:
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "historical market-data parquet inventory is missing")

    try:
        import pyarrow.dataset as ds
        dataset = ds.dataset(
            [str(path) for path in files],
            format="parquet",
            partitioning=ds.partitioning(flavor="hive"),
        )
        table = dataset.to_table(columns=["date", "ticker", "market"])
        frame = table.to_pandas()
    except Exception as exc:  # pragma: no cover - exercised only on a broken local install
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "historical inventory is unreadable") from exc

    rows = frame[["date", "ticker", "market"]].rename(columns={"date": "date"}).to_dict("records")
    metadata_path = root / "data/reference/krx_instrument_metadata.parquet"
    manifest_path = root / "data/reference/krx_instrument_metadata_manifest.json"
    try:
        import pandas as pd
        metadata = pd.read_parquet(metadata_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verified_date = str(manifest["verified_snapshot_effective_date"])
        current = metadata.loc[
            (metadata["effective_date"].astype(str) == verified_date)
            & metadata["market"].isin(["KOSPI", "KOSDAQ"])
            & (metadata["asset_type"] == "COMMON"),
            "ticker",
        ].astype(str).tolist()
    except Exception as exc:  # pragma: no cover - broken local reference data
        raise ReconciliationContractError("BLOCKED_TARGET_IDENTITY_CONTRACT", "current common authority is unreadable") from exc

    result = derive_target_identities(
        rows,
        current,
        expected=True,
        source="local market-data inventory minus verified current COMMON authority",
    )
    result["provenance"] = {
        "historical_inventory_path": "data/market/raw/krx_stocks/v01",
        "current_authority_path": "data/reference/krx_instrument_metadata.parquet",
        "current_authority_manifest": "data/reference/krx_instrument_metadata_manifest.json",
        "verified_date": verified_date,
        "network_requests": 0,
    }
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
    temporary.replace(path)


def write_target_identity_artifact(payload: Mapping[str, Any], path: str | Path = DEFAULT_TARGET_IDENTITY_PATH) -> Path:
    """Write only the compact target reference artifact; never production output."""

    target_path = Path(path)
    _atomic_write_json(target_path, payload)
    return target_path


@dataclass(frozen=True)
class BasicInfoInput:
    status: str
    raw_root: str
    expected_files: int
    current_files: int
    files_by_market: dict[str, int]
    snapshots: tuple[dict[str, Any], ...]
    raw_manifest_sha256: str | None
    errors: tuple[str, ...] = ()
    derived_raw_manifest_sha256: str | None = None
    # SHA256 of the checkpoint.json FILE BYTES itself, bound against the
    # acquisition closure's frozen checkpoint_manifest_sha256 (FIX02 Section
    # B) — distinct from raw_manifest_sha256 above (Section 16 naming).
    checkpoint_authority_sha256: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "raw_root": self.raw_root,
            "expected_files": self.expected_files,
            "current_files": self.current_files,
            "files_by_market": self.files_by_market,
            "raw_manifest_sha256": self.raw_manifest_sha256,
            "derived_raw_manifest_sha256": self.derived_raw_manifest_sha256,
            "checkpoint_authority_sha256": self.checkpoint_authority_sha256,
            "errors": list(self.errors),
        }


def _canonical_raw_manifest_digest(entries: Iterable[tuple[str, str, str]]) -> str:
    """Canonical ``basDd|market|raw_content_sha256`` digest (sorted, final newline).

    Both the acquisition-authority digest (from stored checkpoint hashes) and
    the derived-validation digest (from freshly re-hashed raw bytes) must use
    this exact same canonicalization, or the two digests are not comparable.
    """

    lines = sorted(f"{bas_dd}|{market}|{digest}" for bas_dd, market, digest in entries)
    manifest = "\n".join(lines) + "\n" if lines else ""
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _expected_dates(calendar_dates: Iterable[str] | None) -> list[str]:
    if calendar_dates is not None:
        dates = [_normalise_date(value) for value in calendar_dates]
        if dates != sorted(set(dates)):
            raise ReconciliationContractError(BLOCKED_RECONCILIATION_INPUT_AUTHORITY, "calendar dates must be sorted and unique")
        return dates
    try:
        from trend_scanner.data.krx_historical_instrument_acquisition import load_historical_trading_calendar
        return list(load_historical_trading_calendar(DEFAULT_CALENDAR_PATH)["trading_dates"])
    except Exception as exc:
        raise ReconciliationContractError(BLOCKED_RECONCILIATION_INPUT_AUTHORITY, "historical calendar is unavailable") from exc


def _blocked(
    root: Path,
    expected_paths: set[Path],
    actual_paths: set[Path],
    errors: Sequence[str],
    *,
    checkpoint_authority_sha256: str | None = None,
) -> BasicInfoInput:
    return BasicInfoInput(
        status=BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
        raw_root=str(root),
        expected_files=len(expected_paths),
        current_files=len(actual_paths),
        files_by_market={
            market: sum(path.name == f"{market}.json" for path in actual_paths)
            for market in ("KOSPI", "KOSDAQ")
        },
        snapshots=(),
        raw_manifest_sha256=None,
        errors=tuple(errors[:20]),
        checkpoint_authority_sha256=checkpoint_authority_sha256,
    )


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FINAL_SUMMARY_FIELDS = (
    "status", "runner_status", "target_count", "completed_count", "pending_count", "checkpoint_manifest_sha256",
)


@dataclass(frozen=True)
class AcquisitionAuthorityCheck:
    entries: dict[str, dict[str, Any]] | None
    errors: tuple[str, ...]
    # SHA256 of the current checkpoint.json FILE BYTES — distinct from
    # raw_manifest_sha256, which digests the per-file raw_content_sha256
    # values recorded *inside* the checkpoint (Section 16 naming).
    checkpoint_authority_sha256: str | None = None


def _load_acquisition_authority(
    dates: Sequence[str],
    *,
    checkpoint_path: Path,
    final_summary_path: Path,
) -> AcquisitionAuthorityCheck:
    """Validate the acquisition closure/checkpoint/manifest immutable authority.

    ``entries`` is ``None`` when any structural/status/coverage check failed;
    callers must treat that as fail-closed regardless of raw-file presence
    (Section A). FIX02 adds the closure ↔ checkpoint binding (Section B): the
    closure's frozen ``checkpoint_manifest_sha256`` must exact-match the
    current checkpoint.json file bytes, not just the per-file raw hashes
    already bound by FIX01.
    """

    errors: list[str] = []
    frozen_checkpoint_sha: str | None = None
    missing_fields: list[str] = []

    if not final_summary_path.is_file():
        errors.append(f"missing_acquisition_final_summary:{final_summary_path}")
        summary: Mapping[str, Any] | None = None
    else:
        try:
            summary = json.loads(final_summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = None
        if not isinstance(summary, Mapping):
            errors.append("acquisition_final_summary_unreadable")
        else:
            missing_fields = sorted(field for field in _REQUIRED_FINAL_SUMMARY_FIELDS if field not in summary)
            if missing_fields:
                errors.append(f"acquisition_final_summary_missing_fields:{missing_fields}")
            if summary.get("status") != READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION:
                errors.append(f"acquisition_final_summary_status_invalid:{summary.get('status')!r}")
            if summary.get("runner_status") != ACQUISITION_COMPLETE_STATUS:
                errors.append(f"acquisition_final_summary_runner_status_invalid:{summary.get('runner_status')!r}")
            candidate_sha = summary.get("checkpoint_manifest_sha256")
            if isinstance(candidate_sha, str) and _HEX64_RE.fullmatch(candidate_sha):
                frozen_checkpoint_sha = candidate_sha
            else:
                errors.append(f"acquisition_final_summary_checkpoint_sha_format_invalid:{candidate_sha!r}")

    if not checkpoint_path.is_file():
        errors.append(f"missing_acquisition_checkpoint:{checkpoint_path}")
        return AcquisitionAuthorityCheck(None, tuple(errors))
    checkpoint_bytes = checkpoint_path.read_bytes()
    current_checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    try:
        checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append("acquisition_checkpoint_unreadable")
        return AcquisitionAuthorityCheck(None, tuple(errors), current_checkpoint_sha256)
    if not isinstance(checkpoint_payload, Mapping) or not isinstance(checkpoint_payload.get("entries"), Mapping):
        errors.append("acquisition_checkpoint_shape_invalid")
        return AcquisitionAuthorityCheck(None, tuple(errors), current_checkpoint_sha256)
    checkpoint_entries: dict[str, Any] = dict(checkpoint_payload["entries"])

    # Section B / MAJOR-01: the closure's frozen checkpoint digest must match
    # the checkpoint file as it exists right now — a raw+checkpoint
    # coordinated tamper that keeps per-file hashes internally consistent
    # would otherwise slip past the FIX01 per-entry binding alone.
    if frozen_checkpoint_sha is not None and frozen_checkpoint_sha != current_checkpoint_sha256:
        errors.append(
            f"ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH:current={current_checkpoint_sha256}:frozen={frozen_checkpoint_sha}"
        )

    expected_keys = {
        f"{day.replace('-', '')}|{market}|{'stk_isu_base_info' if market == 'KOSPI' else 'ksq_isu_base_info'}"
        for day in dates
        for market in ("KOSPI", "KOSDAQ")
    }
    if isinstance(summary, Mapping) and not missing_fields:
        # Section 26: the count gate scales with the calendar under test
        # (expected_keys), not a hardcoded 8190 — production naturally lands
        # on 8190 once the calendar covers the full frozen historical range.
        expected_pair_count = len(expected_keys)
        if (
            summary.get("target_count") != expected_pair_count
            or summary.get("completed_count") != expected_pair_count
            or summary.get("pending_count") != 0
        ):
            errors.append(
                "acquisition_final_summary_count_mismatch:"
                f"target={summary.get('target_count')},completed={summary.get('completed_count')},"
                f"pending={summary.get('pending_count')},expected={expected_pair_count}"
            )
    actual_keys = set(checkpoint_entries)
    missing_entries = sorted(expected_keys - actual_keys)
    extra_entries = sorted(actual_keys - expected_keys)
    if missing_entries:
        errors.append(f"acquisition_checkpoint_missing_entries:{len(missing_entries)}")
    if extra_entries:
        errors.append(f"acquisition_checkpoint_extra_entries:{len(extra_entries)}")

    non_complete: dict[str, int] = {}
    for key in sorted(expected_keys & actual_keys):
        entry = checkpoint_entries[key]
        entry_status = str(entry.get("status")) if isinstance(entry, Mapping) else "INVALID_ENTRY"
        if entry_status != ACQUISITION_COMPLETE_STATUS:
            non_complete[entry_status] = non_complete.get(entry_status, 0) + 1
    if non_complete:
        errors.append(f"acquisition_checkpoint_non_complete_statuses:{non_complete}")

    if errors:
        return AcquisitionAuthorityCheck(None, tuple(errors), current_checkpoint_sha256)

    for key in expected_keys:
        entry = checkpoint_entries[key]
        if entry.get("schema_validation") != "PASS" or entry.get("identity_validation") != "PASS":
            errors.append(f"acquisition_checkpoint_validation_not_pass:{key}")
        elif not entry.get("raw_content_sha256"):
            errors.append(f"acquisition_checkpoint_missing_sha:{key}")

    if errors:
        return AcquisitionAuthorityCheck(None, tuple(errors), current_checkpoint_sha256)

    return AcquisitionAuthorityCheck(checkpoint_entries, tuple(errors), current_checkpoint_sha256)


def load_basic_info_snapshots(
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    *,
    calendar_dates: Iterable[str] | None = None,
    acquisition_checkpoint_path: str | Path = DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    acquisition_final_summary_path: str | Path = DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
) -> BasicInfoInput:
    """Load and validate raw Basic Info without making any network request.

    A missing raw root is normal waiting (Section 30).  A raw root that
    exists but whose files, acquisition checkpoint, or acquisition final
    summary do not exactly and provably match the immutable acquisition
    authority is fail-closed as ``BLOCKED_RECONCILIATION_INPUT_AUTHORITY``
    (Section 31) — never silently treated as waiting, and never accepted on
    the strength of a freshly recomputed hash alone (Section 9).
    """

    root = Path(raw_root)
    checkpoint_path = Path(acquisition_checkpoint_path)
    final_summary_path = Path(acquisition_final_summary_path)
    dates = _expected_dates(calendar_dates)
    expected_paths = {
        root / day[:4] / day.replace("-", "") / f"{market}.json"
        for day in dates
        for market in ("KOSPI", "KOSDAQ")
    }
    if not root.exists():
        return BasicInfoInput(
            status=AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION,
            raw_root=str(root),
            expected_files=len(expected_paths),
            current_files=0,
            files_by_market={"KOSPI": 0, "KOSDAQ": 0},
            snapshots=(),
            raw_manifest_sha256=None,
        )

    actual_paths = set(root.rglob("*.json"))
    missing = sorted(expected_paths - actual_paths)
    extra = sorted(actual_paths - expected_paths)
    if missing or extra:
        errors = [f"missing:{path}" for path in missing[:20]] + [f"extra:{path}" for path in extra[:20]]
        return _blocked(root, expected_paths, actual_paths, errors)

    authority_check = _load_acquisition_authority(
        dates, checkpoint_path=checkpoint_path, final_summary_path=final_summary_path
    )
    checkpoint_entries = authority_check.entries
    if checkpoint_entries is None:
        return _blocked(
            root, expected_paths, actual_paths, list(authority_check.errors),
            checkpoint_authority_sha256=authority_check.checkpoint_authority_sha256,
        )
    checkpoint_authority_sha256 = authority_check.checkpoint_authority_sha256

    try:
        from trend_scanner.data.krx_historical_instrument_acquisition import validate_basic_info_response
    except Exception as exc:  # pragma: no cover
        raise ReconciliationContractError(BLOCKED_RECONCILIATION_INPUT_AUTHORITY, "Basic Info schema validator unavailable") from exc

    snapshots: list[dict[str, Any]] = []
    authority_tuples: list[tuple[str, str, str]] = []
    derived_tuples: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for day in dates:
        bas_dd = day.replace("-", "")
        for market in ("KOSPI", "KOSDAQ"):
            endpoint = "stk_isu_base_info" if market == "KOSPI" else "ksq_isu_base_info"
            key = f"{bas_dd}|{market}|{endpoint}"
            entry = checkpoint_entries[key]
            path = root / day[:4] / bas_dd / f"{market}.json"
            try:
                content = path.read_bytes()
                current_digest = hashlib.sha256(content).hexdigest()
                derived_tuples.append((bas_dd, market, current_digest))
                stored_digest = entry.get("raw_content_sha256")
                if current_digest != stored_digest:
                    errors.append(f"raw_sha_tamper:{key}")
                    continue
                payload = json.loads(content.decode("utf-8"))
                checked = validate_basic_info_response(payload, bas_dd=bas_dd, market=market, endpoint=endpoint)
                if checked["row_count"] != int(entry.get("row_count", -1)):
                    errors.append(f"row_count_mismatch:{key}")
                    continue
                rows = []
                for row in checked["records"]:
                    # The KRX short code is a six-character string contract;
                    # do not silently uppercase, cast, or strip leading zeros.
                    _normalise_ticker(row["ISU_SRT_CD"])
                    # effective_date is derived metadata; BAS_DD is never injected into the source row.
                    rows.append({
                        **row,
                        "effective_date": bas_dd,
                        "effective_date_source": "REQUEST_BAS_DD",
                    })
                snapshots.append({
                    "effective_date": day,
                    "effective_date_source": "REQUEST_BAS_DD",
                    "market": market,
                    "endpoint": endpoint,
                    "raw_path": str(path),
                    "raw_content_sha256": current_digest,
                    "rows": rows,
                })
                authority_tuples.append((bas_dd, market, stored_digest))
            except Exception as exc:
                errors.append(f"{path}:{type(exc).__name__}:{exc}")

    if errors:
        return _blocked(root, expected_paths, actual_paths, errors, checkpoint_authority_sha256=checkpoint_authority_sha256)

    return BasicInfoInput(
        status="READY",
        raw_root=str(root),
        expected_files=len(expected_paths),
        current_files=len(actual_paths),
        files_by_market={"KOSPI": len(dates), "KOSDAQ": len(dates)},
        snapshots=tuple(snapshots),
        # Authority digest: derived from the acquisition checkpoint's own
        # stored hashes, never from the hashes this loader just recomputed
        # (Section 9/52) — the current-raw digest is retained separately.
        raw_manifest_sha256=_canonical_raw_manifest_digest(authority_tuples),
        derived_raw_manifest_sha256=_canonical_raw_manifest_digest(derived_tuples),
        checkpoint_authority_sha256=checkpoint_authority_sha256,
    )


load_basic_info_raw = load_basic_info_snapshots


def load_supplemental_authority_records(
    directory: str | Path = DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load supplemental (non-Basic-Info) official authority records.

    Returns a lookup keyed by ``(target_ticker, isu_cd)``. A missing directory
    or an empty/absent ``records`` list yields an empty lookup — this is a
    fail-closed default, never an implicit resolution. Each manifest file
    under ``directory`` is expected to carry a top-level ``records`` list of
    individually-investigated identities (see
    ``data/reference/source/history/krx_instrument_master/v01/supplemental_authority/``).
    """

    directory = Path(directory)
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    if not directory.is_dir():
        return lookup
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload.get("records", []):
            ticker = str(record.get("target_ticker", "")).strip()
            isu_cd = str(record.get("isu_cd", "")).strip()
            if ticker and isu_cd:
                lookup[(ticker, isu_cd)] = record
    return lookup


# Central mapping based on observed KRX formal field combinations.  Unknown
# combinations deliberately remain unresolved instead of falling through to
# COMMON.  The sector field may be blank when the other two fields suffice.
SECURITY_TYPE_MAPPING: tuple[dict[str, Any], ...] = (
    {
        "rule": "SECUGRP_NM=주권 and KIND_STKCERT_TP_NM=보통주 and SECT_TP_NM not SPAC",
        "classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE",
        "SECUGRP_NM": "주권", "KIND_STKCERT_TP_NM": "보통주", "SECT_TP_NM_condition": "does not start with SPAC",
    },
    {
        # "주식예탁증서" added per HISTORICAL_UNIVERSE_AUTHORITY_UNRESOLVED_RESOLUTION_V01
        # Fix B3: verified exact-value KRX terminology predecessor of
        # "주식예탁증권" — all surviving DR tickers (950010/950100/950110)
        # switch SECUGRP_NM from 증서->증권 on the exact same date
        # (2014-03-03), same ISU_CD, same ISU_ABBRV either side of the cutover.
        "rule": "SECUGRP_NM in {외국주권,주식예탁증권,주식예탁증서,사회간접자본투융자회사,투자회사} and KIND_STKCERT_TP_NM=보통주",
        "classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE",
        "SECUGRP_NM": "외국주권 | 주식예탁증권 | 주식예탁증서 | 사회간접자본투융자회사 | 투자회사", "KIND_STKCERT_TP_NM": "보통주", "SECT_TP_NM_condition": "any",
    },
    {
        # "선박투자회사" added per Fix B1: shares the exact documented exclusion
        # principle already applied to 부동산투자회사/REIT in
        # docs/patterns/pattern_a/validation/universe_quality_v01.md §2.1 —
        # "배당 중심 구조로 일반 추세 스캐너 대상에서 제외" (dividend-centric
        # distribution structure). Both are special-purpose-law asset-pooling
        # vehicles (선박투자회사법 / 부동산투자회사법) required to distribute
        # the large majority of income as dividends, not operating companies.
        "rule": "SECUGRP_NM in {부동산투자회사,선박투자회사}",
        "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE",
        "SECUGRP_NM": "부동산투자회사 | 선박투자회사", "KIND_STKCERT_TP_NM": "any", "SECT_TP_NM_condition": "any",
    },
    {
        "rule": "SECUGRP_NM=주권 and SECT_TP_NM starts SPAC",
        "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE",
        "SECUGRP_NM": "주권", "KIND_STKCERT_TP_NM": "any", "SECT_TP_NM_condition": "starts with SPAC",
    },
    {
        "rule": "KIND_STKCERT_TP_NM in {구형우선주,신형우선주}",
        "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE",
        "SECUGRP_NM": "any", "KIND_STKCERT_TP_NM": "구형우선주 | 신형우선주", "SECT_TP_NM_condition": "any",
    },
)
_COMMON_GROUPS = frozenset({"주권", "외국주권", "주식예탁증권", "주식예탁증서", "사회간접자본투융자회사", "투자회사"})
# Dividend-centric asset-pooling vehicles excluded per the same principle as
# docs/patterns/pattern_a/validation/universe_quality_v01.md §2.1's REIT
# exclusion ("배당 중심 구조로 일반 추세 스캐너 대상에서 제외") — not a
# ticker-name or suffix heuristic, an official SECUGRP_NM value match.
_DIVIDEND_FOCUSED_INVESTMENT_VEHICLE_GROUPS = frozenset({"부동산투자회사", "선박투자회사"})
_PREFERRED_KINDS = frozenset({"구형우선주", "신형우선주"})


def classify_security_type(row: Mapping[str, Any]) -> dict[str, str]:
    """Return a three-state official-field classification with a reason."""

    required = ("SECUGRP_NM", "KIND_STKCERT_TP_NM", "SECT_TP_NM")
    if any(field not in row for field in required):
        return {"classification": CLASS_UNRESOLVED, "reason": "MISSING_SECURITY_TYPE_FIELD"}
    values = {field: row[field] for field in required}
    if any(not isinstance(value, str) for value in values.values()):
        return {"classification": CLASS_UNRESOLVED, "reason": "INVALID_SECURITY_TYPE_VALUE"}
    group = values["SECUGRP_NM"].strip()
    kind = values["KIND_STKCERT_TP_NM"].strip()
    sector = values["SECT_TP_NM"].strip()
    if group in _DIVIDEND_FOCUSED_INVESTMENT_VEHICLE_GROUPS:
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if group == "주권" and sector.startswith("SPAC"):
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if kind in _PREFERRED_KINDS:
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if group in _COMMON_GROUPS and kind == "보통주":
        return {"classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE"}
    return {"classification": CLASS_UNRESOLVED, "reason": "UNKNOWN_SECURITY_TYPE_VALUE"}


def build_security_type_mapping_evidence(
    observed_rows: Iterable[Mapping[str, Any]] = (),
    *,
    sample_source_path: str | None = None,
) -> dict[str, Any]:
    """Mapping provenance evidence, strengthened per Section E (Minor).

    ``observed_rows`` (if provided) is a local sample used only to count how
    many observed formal-field combinations match each rule; it never widens
    or narrows the mapping itself, and an unmatched combination is reported
    as its own UNRESOLVED inventory row rather than guessed. ``sample_source_path``
    should name where that sample actually came from (Section 37 requires this
    to be a real local path, not left implicit).
    """

    reason_sample_counts: dict[str, int] = {}
    unresolved_combinations: dict[tuple[str, str, str], int] = {}
    for row in observed_rows:
        checked = classify_security_type(row)
        reason_sample_counts[checked["reason"]] = reason_sample_counts.get(checked["reason"], 0) + 1
        if checked["classification"] == CLASS_UNRESOLVED:
            key = (
                str(row.get("SECUGRP_NM", "")).strip(),
                str(row.get("KIND_STKCERT_TP_NM", "")).strip(),
                str(row.get("SECT_TP_NM", "")).strip(),
            )
            unresolved_combinations[key] = unresolved_combinations.get(key, 0) + 1

    mappings = []
    for index, rule in enumerate(SECURITY_TYPE_MAPPING):
        mappings.append({
            "rule_id": f"HISTORICAL_SECURITY_TYPE_RULE_{index + 1:02d}",
            **dict(rule),
            "authority_tier": "TIER_A",
            "existing_authority_reference": "docs/architecture/instrument_metadata_authority.md#6-source-category--assettype-deterministic-mapping-fix-round-08-갱신",
            "sample_source_path": sample_source_path,
            # Multiple rules can share one reason string (rules 1-2 both
            # resolve TIER_A_COMMON_SECURITY_TYPE); this count is per REASON,
            # not per rule — it cannot distinguish which of rules 1/2 (or
            # 3/4/5) actually fired for a given sample row.
            "observed_sample_count": reason_sample_counts.get(rule["reason"], 0),
        })
    return {
        "schema": "historical_universe_security_type_mapping_v01",
        "authority": "KRX Open API Basic Info Tier A observed/local formal inventory",
        "observed_sample_count_caveat": (
            "observed_sample_count is aggregated per classification reason, not per rule_id; "
            "rules sharing a reason (1-2 for COMMON, 3-5 for NOT_COMMON) cannot be individually attributed"
        ),
        "mappings": mappings,
        "unknown_policy": "UNRESOLVED; never default to COMMON",
        "sector_blank_policy": "SECT_TP_NM blank is allowed when group+kind establish an observed rule",
        "production_authority_alignment": {
            "existing_authority_reference": "docs/architecture/instrument_metadata_authority.md §6.1",
            "note": (
                "Production maps any KIND_STKCERT_TP_NM=보통주 row to COMMON regardless of SECUGRP_NM "
                "(외국주권/주식예탁증권/주식예탁증서/사회간접자본투융자회사/투자회사 included), matching this "
                "module's rules 1-2. 부동산투자회사(REIT)/선박투자회사 are excluded under rule 3 on the same "
                "documented 'dividend-centric distribution structure' principle "
                "(docs/patterns/pattern_a/validation/universe_quality_v01.md §2.1) — not a bare SECUGRP_NM "
                "enumeration. The one alignment gap production carries — 보통주 + SECT_TP_NM=관리종목(소속부없음) "
                "on an identity that also has Tier A SPAC-section history earlier in its own timeline, with no "
                "explicit non-SPAC COMMON interval yet confirmed between the SPAC period and this observation — "
                "is fail-closed to UNKNOWN instead of guessed as COMMON; that exception is applied in "
                "reconcile_target_identities via reason="
                f"{PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY!r} rather than in this "
                "row-pure classifier, since it requires the identity's chronological observation history. Once "
                "an explicit non-SPAC COMMON interval is confirmed for that identity, later managed-issue "
                "observations resolve normally (COMMON) — the exception never re-applies retroactively for that "
                "identity (HISTORICAL_UNIVERSE_AUTHORITY_UNRESOLVED_RESOLUTION_V01 Fix A)."
            ),
        },
        "unresolved_combinations_observed": [
            {"SECUGRP_NM": group, "KIND_STKCERT_TP_NM": kind, "SECT_TP_NM": sector, "count": count}
            for (group, kind, sector), count in sorted(unresolved_combinations.items())
        ],
    }


def _apply_supplemental_authority(
    obs: Mapping[str, Any],
    classification: str,
    reason: str,
    supplemental_authority: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[str, str]:
    """Override a residual UNRESOLVED classification using a supplemental
    authority record for this exact ``(ticker, ISU_CD)`` identity, if one
    exists (HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01).

    A record's ``decision`` of "INSUFFICIENT" (or any value this module does
    not recognise) never changes the classification — only the reason code is
    updated to show the identity was reviewed. Absence of a record for this
    identity is a no-op: the row-pure/primary-authority result passes through
    unchanged.
    """

    key = (str(obs.get("ticker", "")).strip(), str(obs.get("ISU_CD", "")).strip())
    record = supplemental_authority.get(key)
    if record is None:
        return classification, reason
    decision = str(record.get("decision", "")).strip()
    reason_code = str(record.get("decision_reason_code", "") or "").strip()
    if decision in _SUPPLEMENTAL_DECISION_TO_CLASS:
        return _SUPPLEMENTAL_DECISION_TO_CLASS[decision], reason_code or classification
    if decision == "INSUFFICIENT":
        return classification, reason_code or SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT
    return classification, reason


def _classify_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    supplemental_authority: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Row-pure classification plus the documented cross-observation
    production-authority alignment exception (see ``build_security_type_mapping_evidence``),
    plus an optional supplemental-authority override for individually
    investigated residual identities (HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01).

    HISTORICAL_UNIVERSE_AUTHORITY_UNRESOLVED_RESOLUTION_V01 Fix A: the SPAC
    exception is chronological, not a blanket "SPAC ever observed" flag. Past
    SPAC status does not permanently contaminate an identity's lineage —
    only a managed-issue observation that occurs BEFORE any explicit
    non-SPAC COMMON interval has been confirmed for that same identity is
    fail-closed. Once a genuine COMMON observation is confirmed (chronologically,
    ``observations`` is pre-sorted by ``build_pit_identity_timeline``), later
    managed-issue observations for that identity resolve normally instead —
    no arbitrary time threshold, purely explicit-transition-based (Section 8/9).

    ``supplemental_authority`` (see ``load_supplemental_authority_records``)
    only ever narrows a residual UNRESOLVED result for an identity that was
    individually investigated against official non-Basic-Info evidence; it
    never widens or replaces the primary Basic-Info-driven classification for
    any other identity. ``None``/empty behaves exactly as before this layer
    existed.
    """

    supplemental_authority = supplemental_authority or {}
    classified: list[dict[str, Any]] = []
    spac_seen = False
    common_confirmed = False
    for obs in observations:
        is_spac_obs = (
            str(obs.get("SECUGRP_NM", "")).strip() == "주권"
            and str(obs.get("SECT_TP_NM", "")).strip().startswith("SPAC")
        )
        checked = classify_security_type(obs)
        classification = checked["classification"]
        reason = checked["reason"]
        is_managed_common_shape = (
            classification == CLASS_COMMON
            and str(obs.get("KIND_STKCERT_TP_NM", "")).strip() == "보통주"
            and str(obs.get("SECT_TP_NM", "")).strip() == _MANAGED_ISSUE_SECTION
        )
        if is_managed_common_shape and spac_seen and not common_confirmed:
            classification = CLASS_UNRESOLVED
            reason = PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY
            classification, reason = _apply_supplemental_authority(obs, classification, reason, supplemental_authority)
        elif classification == CLASS_UNRESOLVED and reason == "UNKNOWN_SECURITY_TYPE_VALUE":
            classification, reason = _apply_supplemental_authority(obs, classification, reason, supplemental_authority)
        merged = dict(obs)
        merged["classification"] = classification
        merged["classification_reason"] = reason
        classified.append(merged)
        if is_spac_obs:
            spac_seen = True
        if classification == CLASS_COMMON and not is_managed_common_shape:
            common_confirmed = True
    return classified


def build_pit_identity_timeline(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build ticker timelines while keeping effective date as derived metadata."""

    timeline: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        effective_date = _normalise_date(snapshot.get("effective_date"))
        source = str(snapshot.get("effective_date_source", "REQUEST_BAS_DD"))
        for source_row in snapshot.get("rows", []):
            if not isinstance(source_row, Mapping):
                continue
            raw_ticker = source_row.get("ISU_SRT_CD")
            try:
                ticker = _normalise_ticker(raw_ticker)
            except ReconciliationContractError:
                ticker = str(raw_ticker).strip().upper() if isinstance(raw_ticker, str) else ""
            row = dict(source_row)
            row["ticker"] = ticker
            row["effective_date"] = effective_date
            row["effective_date_source"] = source
            row.pop("BAS_DD", None)
            timeline.setdefault(ticker, []).append(row)
    for rows in timeline.values():
        rows.sort(key=lambda row: (row["effective_date"], str(row.get("ISU_CD", ""))))
    return timeline


def _intervalize(
    classified: Sequence[Mapping[str, Any]],
    expected_dates: Sequence[str] | None,
    *,
    source_manifest_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Build identity-aware intervals from already-classified observations.

    Each interval keeps ``ISU_CD``/``effective_from``/``effective_to`` so a
    non-overlapping ticker reuse never collapses into a single ticker-only
    row downstream (Section C).  ``historical_common_required`` is an
    interval-level fact (this interval's own classification), never
    inherited from the target's overall historical verdict.
    """

    if not classified:
        return []
    date_index = {day: index for index, day in enumerate(expected_dates or [])}
    isu_order: list[str] = []
    intervals: list[dict[str, Any]] = []
    for obs in classified:
        ticker = str(obs.get("ticker", obs.get("ISU_SRT_CD", "")))
        isu = str(obs.get("ISU_CD", "") or "").strip()
        if isu and isu not in isu_order:
            isu_order.append(isu)
        # classification_reason is part of the merge key (not just
        # classification) so a reason transition always draws an interval
        # boundary — otherwise a supplemental-authority override on one
        # observation can be silently swallowed into an adjacent same
        # -classification interval's original reason, breaking Section 33
        # traceability (HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01).
        state = (isu, str(obs.get("MKT_TP_NM", "")).strip(), obs["classification"], obs["classification_reason"])
        current = {
            "effective_from": obs["effective_date"],
            "effective_to": obs["effective_date"],
            "ticker": ticker,
            "ISU_CD": obs.get("ISU_CD"),
            "market": obs.get("MKT_TP_NM", ""),
            "classification": obs["classification"],
            "classification_reason": obs["classification_reason"],
            "historical_common_required": obs["classification"] == CLASS_COMMON,
            "reuse_group": f"{ticker}:{isu}" if isu else None,
            "authority": "TIER_A_KRX_OPEN_API_BASIC_INFO",
            "source_manifest_sha256": source_manifest_sha256,
        }
        if intervals:
            previous = intervals[-1]
            previous_state = (
                str(previous.get("ISU_CD", "") or ""),
                str(previous.get("market", "")).strip(),
                previous["classification"],
                previous["classification_reason"],
            )
            adjacent = True
            if date_index:
                adjacent = date_index.get(previous["effective_to"], -2) + 1 == date_index.get(current["effective_from"], -1)
            if previous_state == state and adjacent:
                previous["effective_to"] = current["effective_to"]
                continue
        intervals.append(current)
    return intervals


def reconcile_target_identities(
    target_identities: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]],
    *,
    expected_dates: Sequence[str] | None = None,
    source_manifest_sha256: str | None = None,
    supplemental_authority: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile target identities against already-loaded PIT snapshots.

    ``supplemental_authority`` (see ``load_supplemental_authority_records``)
    is optional and defaults to ``None`` (no override — identical behaviour
    to before HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01).
    """

    targets = canonical_target_identity_records(target_identities)
    timeline = build_pit_identity_timeline(snapshots)
    results: list[dict[str, Any]] = []
    for target in targets:
        ticker = target["ticker"]
        observations = timeline.get(ticker, [])
        classified = _classify_observations(observations, supplemental_authority=supplemental_authority)
        states: list[str] = []
        reasons: list[str] = []
        dates: list[str] = []
        markets: set[str] = set()
        isu_values: set[str] = set()
        by_date: dict[str, set[str]] = {}
        conflict_groups: dict[tuple[str, str], set[str]] = {}
        for observation in classified:
            states.append(observation["classification"])
            reasons.append(observation["classification_reason"])
            dates.append(observation["effective_date"])
            markets.add(str(observation.get("MKT_TP_NM", "")).strip())
            isu = str(observation.get("ISU_CD", "")).strip()
            isu_values.add(isu)
            by_date.setdefault(observation["effective_date"], set()).add(isu)
            conflict_groups.setdefault((observation["effective_date"], isu), set()).add(observation["classification"])
        overlapping_codes = any(len(codes) > 1 for codes in by_date.values())
        if overlapping_codes:
            reuse_status = "AMBIGUOUS"
        elif len(isu_values - {""}) > 1:
            reuse_status = "REUSE_DETECTED"
        else:
            reuse_status = "PASS"
        # A true conflict (Section 18) is the SAME effective date and SAME
        # resolved identity carrying mutually contradictory official rows —
        # never a plain lifecycle transition across different dates.
        true_conflict = any(
            {CLASS_COMMON, CLASS_NOT_COMMON} <= state_set for state_set in conflict_groups.values()
        )

        if not observations:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "PIT_COVERAGE_GAP"
        elif reuse_status == "AMBIGUOUS":
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "IDENTITY_COLLISION"
        elif true_conflict:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "SAME_DATE_CONTRADICTORY_CLASSIFICATION"
        elif CLASS_UNRESOLVED in states:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = next((item for item in reasons if item not in {"TIER_A_COMMON_SECURITY_TYPE", "TIER_A_NON_COMMON_SECURITY_TYPE"}), "UNKNOWN_SECURITY_TYPE_VALUE")
        elif CLASS_COMMON in states:
            # A resolved COMMON interval anywhere in the PIT history is
            # sufficient (Section 15/17C); a NOT_COMMON interval elsewhere is
            # a normal lifecycle transition, not a conflict (Section 16).
            final = HISTORICAL_COMMON_REQUIRED
            reason = "TIER_A_COMMON_SECURITY_TYPE" if CLASS_NOT_COMMON not in states else "TIER_A_COMMON_INTERVAL_OBSERVED"
        else:
            final = HISTORICAL_NOT_COMMON
            reason = "TIER_A_NON_COMMON_SECURITY_TYPE"

        intervals = _intervalize(classified, expected_dates, source_manifest_sha256=source_manifest_sha256)
        results.append(
            {
                "target_ticker": ticker,
                "identity_key": target.get("identity_key", f"ticker:{ticker}"),
                "ISU_CD": sorted(code for code in isu_values if code),
                "markets_seen": sorted(markets - {""}),
                "first_seen_date": min(dates) if dates else None,
                "last_seen_date": max(dates) if dates else None,
                "numeric_or_alpha": target["identity_type"],
                "historical_classification": final,
                "classification_reason": reason,
                "authority_tier": "TIER_A_KRX_OPEN_API_BASIC_INFO" if observations else "NONE",
                "common_observation_count": states.count(CLASS_COMMON),
                "not_common_observation_count": states.count(CLASS_NOT_COMMON),
                "unresolved_observation_count": states.count(CLASS_UNRESOLVED),
                "security_type_states": sorted(set(states)),
                "ticker_reuse_status": reuse_status,
                "intervals": intervals,
                "adjusted_price_support": "UNKNOWN" if target["identity_type"] == "alphanumeric" else "NUMERIC_CONSUMER_CONTRACT_UNCHANGED",
                "source_manifest_sha256": source_manifest_sha256,
            }
        )

    counts = {
        HISTORICAL_COMMON_REQUIRED: sum(row["historical_classification"] == HISTORICAL_COMMON_REQUIRED for row in results),
        HISTORICAL_NOT_COMMON: sum(row["historical_classification"] == HISTORICAL_NOT_COMMON for row in results),
        HISTORICAL_AUTHORITY_UNRESOLVED: sum(row["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED for row in results),
    }
    return {
        "results": results,
        # Section 22: identity-aware structure kept alongside the per-target
        # view so a non-overlapping ticker reuse never has to be recovered
        # from a lossy ticker-only set downstream.
        "results_by_target": results,
        "identity_intervals": [interval for row in results for interval in row["intervals"]],
        "counts": counts,
        "target_total": len(targets),
        "source_manifest_sha256": source_manifest_sha256,
    }


def evaluate_survivorship_bias_gate(reconciliation: Mapping[str, Any], *, expected_total: int = EXPECTED_TARGET_TOTAL) -> dict[str, Any]:
    counts = dict(reconciliation.get("counts", {}))
    accounted = sum(int(counts.get(key, 0)) for key in (HISTORICAL_COMMON_REQUIRED, HISTORICAL_NOT_COMMON, HISTORICAL_AUTHORITY_UNRESOLVED))
    unresolved = int(counts.get(HISTORICAL_AUTHORITY_UNRESOLVED, 0))
    passed = accounted == expected_total and unresolved == 0 and int(reconciliation.get("target_total", expected_total)) == expected_total
    return {
        "gate": "SURVIVORSHIP_BIAS_GATE",
        "classified_common": int(counts.get(HISTORICAL_COMMON_REQUIRED, 0)),
        "classified_not_common": int(counts.get(HISTORICAL_NOT_COMMON, 0)),
        "unresolved": unresolved,
        "accounted": accounted,
        "expected_total": expected_total,
        "status": "PASS" if passed else "BLOCKED_SURVIVORSHIP_GATE",
    }


def evaluate_ticker_identity_reuse_gate(reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    results = list(reconciliation.get("results", []))
    ambiguous = [row.get("target_ticker") for row in results if row.get("ticker_reuse_status") == "AMBIGUOUS"]
    return {
        "gate": "TICKER_IDENTITY_REUSE_GATE",
        "ambiguous_collision_count": len(ambiguous),
        "ambiguous_tickers": ambiguous,
        "reuse_detected_count": sum(row.get("ticker_reuse_status") == "REUSE_DETECTED" for row in results),
        "status": "PASS" if not ambiguous else "BLOCKED_TICKER_REUSE_CONTRACT",
    }


def evaluate_denominator_freeze_gate(
    reconciliation: Mapping[str, Any],
    *,
    raw_input_status: str,
    raw_integrity_pass: bool,
    expected_total: int = EXPECTED_TARGET_TOTAL,
) -> dict[str, Any]:
    survivor = evaluate_survivorship_bias_gate(reconciliation, expected_total=expected_total)
    reuse = evaluate_ticker_identity_reuse_gate(reconciliation)
    ready = raw_input_status == "READY" and raw_integrity_pass and survivor["status"] == "PASS" and reuse["status"] == "PASS"
    if raw_input_status != "READY":
        status = "NOT_EXECUTED_INPUT_AUTHORITY_PENDING"
    elif ready:
        status = "ELIGIBLE_NOT_PUBLISHED"
    else:
        status = "BLOCKED_DENOMINATOR_FREEZE_GATE"
    return {
        "gate": "FINAL_DENOMINATOR_FREEZE_GATE",
        "survivorship_bias_gate": survivor,
        "ticker_identity_reuse_gate": reuse,
        "raw_integrity_pass": raw_integrity_pass,
        "actual_freeze": False,
        "status": status,
    }


evaluate_final_denominator_freeze_gate = evaluate_denominator_freeze_gate


def build_denominator_candidate(
    current_common_tickers: Iterable[str],
    reconciliation: Mapping[str, Any],
    *,
    raw_input_status: str,
    raw_integrity_pass: bool,
    expected_total: int = EXPECTED_TARGET_TOTAL,
) -> dict[str, Any]:
    """Build a test/next-step candidate only; never publish production authority."""

    gate = evaluate_denominator_freeze_gate(
        reconciliation,
        raw_input_status=raw_input_status,
        raw_integrity_pass=raw_integrity_pass,
        expected_total=expected_total,
    )
    if gate["status"] not in {"ELIGIBLE_NOT_PUBLISHED"}:
        return {
            "status": gate["status"],
            "current_entries": [],
            "historical_identity_intervals": [],
            "actual_freeze": False,
        }
    current = {_normalise_ticker(value) for value in current_common_tickers}
    # Section 24: never collapse to set(ticker) — keep each historical
    # identity interval (ticker + ISU_CD + effective interval) distinct so a
    # non-overlapping ticker reuse is never re-merged into one ticker row.
    # Every identity interval is kept — including NOT_COMMON ones — so a
    # non-overlapping reuse never loses an interval (Section 26: "identity
    # 정보를 유실하지 않는 것이 목적").  Only intervals with
    # historical_common_required=True feed the COMMON-candidate ticker union.
    historical_identity_intervals = [
        {
            "ticker": interval["ticker"],
            "ISU_CD": interval.get("ISU_CD"),
            "effective_from": interval["effective_from"],
            "effective_to": interval["effective_to"],
            "historical_common_required": bool(interval.get("historical_common_required")),
            "adjusted_price_support": "UNKNOWN" if not str(interval["ticker"]).isdigit() else "NUMERIC_CONSUMER_CONTRACT_UNCHANGED",
        }
        for interval in reconciliation.get("identity_intervals", [])
    ]
    current_entries = [
        {
            "ticker": ticker,
            "adjusted_price_support": "UNKNOWN" if not ticker.isdigit() else "NUMERIC_CONSUMER_CONTRACT_UNCHANGED",
        }
        for ticker in sorted(current)
    ]
    historical_common_tickers = {
        interval["ticker"] for interval in historical_identity_intervals if interval["historical_common_required"]
    }
    ticker_union = current | historical_common_tickers
    return {
        "status": "CANDIDATE_ONLY",
        "current_entries": current_entries,
        "historical_identity_intervals": historical_identity_intervals,
        # NOT "count": historical_identity_intervals now includes NOT_COMMON
        # legs too (Section 26), so a summed count would overstate the
        # candidate's actual COMMON-denominator size. Use ticker_union_count
        # for that; these two are raw structural sizes only.
        "current_entry_count": len(current_entries),
        "historical_identity_interval_count": len(historical_identity_intervals),
        "ticker_union_count": len(ticker_union),
        "numeric_ticker_union_count": sum(ticker.isdigit() for ticker in ticker_union),
        "alphanumeric_ticker_union_count": sum(not ticker.isdigit() for ticker in ticker_union),
        "identity_aware": True,
        "ticker_only_collapse": False,
        "actual_freeze": False,
    }


def run_reconciliation_preflight(
    *,
    target_identities_path: str | Path = DEFAULT_TARGET_IDENTITY_PATH,
    basic_info_root: str | Path = DEFAULT_RAW_ROOT,
    calendar_dates: Iterable[str] | None = None,
    acquisition_checkpoint_path: str | Path = DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    acquisition_final_summary_path: str | Path = DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    supplemental_authority_dir: str | Path = DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR,
) -> dict[str, Any]:
    """Run the default offline preflight; no classification occurs without raw authority."""

    target = load_target_identities(target_identities_path)
    raw = load_basic_info_snapshots(
        basic_info_root,
        calendar_dates=calendar_dates,
        acquisition_checkpoint_path=acquisition_checkpoint_path,
        acquisition_final_summary_path=acquisition_final_summary_path,
    )
    if raw.status == AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION:
        # Section 30: normal preflight waiting — CLI exit 0.
        return {
            "status": "READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION",
            "reconciliation_input_status": raw.status,
            "target": {"counts": target["counts"], "target_identity_set_sha256": target["target_identity_set_sha256"]},
            "raw_input": raw.as_dict(),
            "classification_executed": False,
            "actual_denominator_frozen": False,
            "network_requests": {"krx_open_api": 0, "krx_mdc": 0, "pykrx": 0, "opendart": 0},
            "survivorship_bias_gate": "BLOCKED_INPUT_PENDING",
            "ticker_identity_reuse_gate": "BLOCKED_INPUT_PENDING",
            "denominator_freeze_gate": "NOT_EXECUTED_INPUT_AUTHORITY_PENDING",
        }
    if raw.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY:
        # Section 31/MAJOR-04: partial/corrupt/tampered/wrong-terminal input is
        # never reported as the same top-level status as normal waiting, so
        # the CLI (Section 32) can map this to a non-zero exit distinctly.
        return {
            "status": BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
            "reconciliation_input_status": raw.status,
            "target": {"counts": target["counts"], "target_identity_set_sha256": target["target_identity_set_sha256"]},
            "raw_input": raw.as_dict(),
            "classification_executed": False,
            "actual_denominator_frozen": False,
            "network_requests": {"krx_open_api": 0, "krx_mdc": 0, "pykrx": 0, "opendart": 0},
            "survivorship_bias_gate": "BLOCKED_INPUT_AUTHORITY",
            "ticker_identity_reuse_gate": "BLOCKED_INPUT_AUTHORITY",
            "denominator_freeze_gate": "NOT_EXECUTED_INPUT_AUTHORITY_PENDING",
        }
    supplemental_authority = load_supplemental_authority_records(supplemental_authority_dir)
    reconciliation = reconcile_target_identities(
        target["identities"],
        raw.snapshots,
        expected_dates=_expected_dates(calendar_dates),
        source_manifest_sha256=raw.raw_manifest_sha256,
        supplemental_authority=supplemental_authority,
    )
    survivor = evaluate_survivorship_bias_gate(reconciliation)
    reuse = evaluate_ticker_identity_reuse_gate(reconciliation)
    freeze = evaluate_denominator_freeze_gate(reconciliation, raw_input_status=raw.status, raw_integrity_pass=True)
    return {
        "status": "RECONCILIATION_EXECUTED",
        "reconciliation_input_status": raw.status,
        "target": {"counts": target["counts"], "target_identity_set_sha256": target["target_identity_set_sha256"]},
        "raw_input": raw.as_dict(),
        "reconciliation": reconciliation,
        "survivorship_bias_gate": survivor,
        "ticker_identity_reuse_gate": reuse,
        "denominator_freeze_gate": freeze,
        "classification_executed": True,
        "actual_denominator_frozen": False,
        "network_requests": {"krx_open_api": 0, "krx_mdc": 0, "pykrx": 0, "opendart": 0},
        "supplemental_authority": {
            "directory": str(supplemental_authority_dir),
            "record_count": len(supplemental_authority),
            "decision_counts": {
                decision: sum(1 for record in supplemental_authority.values() if record.get("decision") == decision)
                for decision in sorted({str(record.get("decision")) for record in supplemental_authority.values()})
            },
        },
    }


reconcile_historical_universe = reconcile_target_identities


__all__ = [
    "AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION",
    "BLOCKED_RECONCILIATION_INPUT_AUTHORITY",
    "CLASS_COMMON",
    "CLASS_NOT_COMMON",
    "CLASS_UNRESOLVED",
    "DEFAULT_ACQUISITION_CHECKPOINT_PATH",
    "DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH",
    "DEFAULT_HARNESS_OUTPUT_DIR",
    "DEFAULT_RAW_ROOT",
    "DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR",
    "DEFAULT_TARGET_IDENTITY_PATH",
    "EXPECTED_ALPHANUMERIC_TOTAL",
    "EXPECTED_NUMERIC_TOTAL",
    "EXPECTED_TARGET_TOTAL",
    "HISTORICAL_AUTHORITY_UNRESOLVED",
    "HISTORICAL_COMMON_REQUIRED",
    "HISTORICAL_NOT_COMMON",
    "PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY",
    "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION",
    "SUPPLEMENTAL_AUTHORITY_PREFERRED_CLASS_CONFIRMED",
    "SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED",
    "SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_ABSORBED_TERMINATED",
    "SUPPLEMENTAL_AUTHORITY_SPAC_MERGER_COMMON_LINEAGE_CONFIRMED",
    "SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT",
    "BasicInfoInput",
    "ReconciliationContractError",
    "SECURITY_TYPE_MAPPING",
    "build_denominator_candidate",
    "build_pit_identity_timeline",
    "build_security_type_mapping_evidence",
    "canonical_target_identity_records",
    "canonical_target_set_hash",
    "classify_security_type",
    "derive_target_identities",
    "derive_target_identities_from_repository",
    "evaluate_denominator_freeze_gate",
    "evaluate_final_denominator_freeze_gate",
    "evaluate_survivorship_bias_gate",
    "evaluate_ticker_identity_reuse_gate",
    "load_basic_info_raw",
    "load_basic_info_snapshots",
    "load_supplemental_authority_records",
    "load_target_identities",
    "reconcile_historical_universe",
    "reconcile_target_identities",
    "run_reconciliation_preflight",
    "target_identity_set_hash",
    "write_target_identity_artifact",
]
