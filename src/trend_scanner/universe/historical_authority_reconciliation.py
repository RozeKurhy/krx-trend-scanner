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
            "errors": list(self.errors),
        }


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


def load_basic_info_snapshots(
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    *,
    calendar_dates: Iterable[str] | None = None,
) -> BasicInfoInput:
    """Load and validate raw Basic Info without making any network request."""

    root = Path(raw_root)
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
        errors = tuple(
            [f"missing:{path}" for path in missing[:20]]
            + [f"extra:{path}" for path in extra[:20]]
        )
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
            errors=errors,
        )

    try:
        from trend_scanner.data.krx_historical_instrument_acquisition import validate_basic_info_response
    except Exception as exc:  # pragma: no cover
        raise ReconciliationContractError(BLOCKED_RECONCILIATION_INPUT_AUTHORITY, "Basic Info schema validator unavailable") from exc

    snapshots: list[dict[str, Any]] = []
    manifest_lines: list[str] = []
    errors: list[str] = []
    for day in dates:
        bas_dd = day.replace("-", "")
        for market in ("KOSPI", "KOSDAQ"):
            endpoint = "stk_isu_base_info" if market == "KOSPI" else "ksq_isu_base_info"
            path = root / day[:4] / bas_dd / f"{market}.json"
            try:
                content = path.read_bytes()
                payload = json.loads(content.decode("utf-8"))
                checked = validate_basic_info_response(payload, bas_dd=bas_dd, market=market, endpoint=endpoint)
                digest = hashlib.sha256(content).hexdigest()
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
                    "raw_content_sha256": digest,
                    "rows": rows,
                })
                manifest_lines.append(f"{bas_dd}|{market}|{digest}")
            except Exception as exc:
                errors.append(f"{path}:{type(exc).__name__}:{exc}")

    if errors:
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
        )

    manifest = "\n".join(sorted(manifest_lines)) + "\n"
    return BasicInfoInput(
        status="READY",
        raw_root=str(root),
        expected_files=len(expected_paths),
        current_files=len(actual_paths),
        files_by_market={"KOSPI": len(dates), "KOSDAQ": len(dates)},
        snapshots=tuple(snapshots),
        raw_manifest_sha256=hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
    )


load_basic_info_raw = load_basic_info_snapshots


# Central mapping based on observed KRX formal field combinations.  Unknown
# combinations deliberately remain unresolved instead of falling through to
# COMMON.  The sector field may be blank when the other two fields suffice.
SECURITY_TYPE_MAPPING: tuple[dict[str, Any], ...] = (
    {"rule": "SECUGRP_NM=주권 and KIND_STKCERT_TP_NM=보통주 and SECT_TP_NM not SPAC", "classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE"},
    {"rule": "SECUGRP_NM in {외국주권,주식예탁증권,사회간접자본투융자회사,투자회사} and KIND_STKCERT_TP_NM=보통주", "classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE"},
    {"rule": "SECUGRP_NM=부동산투자회사", "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"},
    {"rule": "SECUGRP_NM=주권 and SECT_TP_NM starts SPAC", "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"},
    {"rule": "KIND_STKCERT_TP_NM in {구형우선주,신형우선주}", "classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"},
)
_COMMON_GROUPS = frozenset({"주권", "외국주권", "주식예탁증권", "사회간접자본투융자회사", "투자회사"})
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
    if group == "부동산투자회사":
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if group == "주권" and sector.startswith("SPAC"):
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if kind in _PREFERRED_KINDS:
        return {"classification": CLASS_NOT_COMMON, "reason": "TIER_A_NON_COMMON_SECURITY_TYPE"}
    if group in _COMMON_GROUPS and kind == "보통주":
        return {"classification": CLASS_COMMON, "reason": "TIER_A_COMMON_SECURITY_TYPE"}
    return {"classification": CLASS_UNRESOLVED, "reason": "UNKNOWN_SECURITY_TYPE_VALUE"}


def build_security_type_mapping_evidence() -> dict[str, Any]:
    return {
        "schema": "historical_universe_security_type_mapping_v01",
        "authority": "KRX Open API Basic Info Tier A observed/local formal inventory",
        "mappings": [dict(rule) for rule in SECURITY_TYPE_MAPPING],
        "unknown_policy": "UNRESOLVED; never default to COMMON",
        "sector_blank_policy": "SECT_TP_NM blank is allowed when group+kind establish an observed rule",
    }


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


def _intervalize(observations: Sequence[Mapping[str, Any]], expected_dates: Sequence[str] | None) -> list[dict[str, Any]]:
    if not observations:
        return []
    date_index = {day: index for index, day in enumerate(expected_dates or [])}
    intervals: list[dict[str, Any]] = []
    for obs in observations:
        checked = classify_security_type(obs)
        state = (str(obs.get("ISU_CD", "")), str(obs.get("MKT_TP_NM", "")).strip(), checked["classification"])
        current = {
            "effective_from": obs["effective_date"],
            "effective_to": obs["effective_date"],
            "ticker": obs.get("ticker", obs.get("ISU_SRT_CD", "")),
            "ISU_CD": obs.get("ISU_CD"),
            "market": obs.get("MKT_TP_NM", ""),
            "security_type": checked["classification"],
            "classification": checked["classification"],
            "classification_reason": checked["reason"],
            "authority": "TIER_A_KRX_OPEN_API_BASIC_INFO",
        }
        if intervals:
            previous = intervals[-1]
            previous_state = (str(previous.get("ISU_CD", "")), str(previous.get("market", "")).strip(), previous["classification"])
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
) -> dict[str, Any]:
    """Reconcile target identities against already-loaded PIT snapshots."""

    targets = canonical_target_identity_records(target_identities)
    timeline = build_pit_identity_timeline(snapshots)
    results: list[dict[str, Any]] = []
    for target in targets:
        ticker = target["ticker"]
        observations = timeline.get(ticker, [])
        states: list[str] = []
        reasons: list[str] = []
        dates: list[str] = []
        markets: set[str] = set()
        isu_values: set[str] = set()
        by_date: dict[str, set[str]] = {}
        for observation in observations:
            checked = classify_security_type(observation)
            states.append(checked["classification"])
            reasons.append(checked["reason"])
            dates.append(observation["effective_date"])
            markets.add(str(observation.get("MKT_TP_NM", "")).strip())
            isu = str(observation.get("ISU_CD", "")).strip()
            isu_values.add(isu)
            by_date.setdefault(observation["effective_date"], set()).add(isu)
        overlapping_codes = any(len(codes) > 1 for codes in by_date.values())
        if overlapping_codes:
            reuse_status = "AMBIGUOUS"
        elif len(isu_values - {""}) > 1:
            reuse_status = "REUSE_DETECTED"
        else:
            reuse_status = "PASS"

        if not observations:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "PIT_COVERAGE_GAP"
        elif reuse_status == "AMBIGUOUS":
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "IDENTITY_COLLISION"
        elif CLASS_UNRESOLVED in states:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = next((item for item in reasons if item not in {"TIER_A_COMMON_SECURITY_TYPE", "TIER_A_NON_COMMON_SECURITY_TYPE"}), "UNKNOWN_SECURITY_TYPE_VALUE")
        elif CLASS_COMMON in states and CLASS_NOT_COMMON in states:
            final = HISTORICAL_AUTHORITY_UNRESOLVED
            reason = "CONFLICTING_OFFICIAL_CLASSIFICATION"
        elif CLASS_COMMON in states:
            final = HISTORICAL_COMMON_REQUIRED
            reason = "TIER_A_COMMON_SECURITY_TYPE"
        else:
            final = HISTORICAL_NOT_COMMON
            reason = "TIER_A_NON_COMMON_SECURITY_TYPE"

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
                "intervals": _intervalize(observations, expected_dates),
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
        return {"status": gate["status"], "entries": [], "actual_freeze": False}
    current = {_normalise_ticker(value) for value in current_common_tickers}
    historical = {
        row["target_ticker"]
        for row in reconciliation.get("results", [])
        if row.get("historical_classification") == HISTORICAL_COMMON_REQUIRED
    }
    entries = [
        {"ticker": ticker, "historical_common_required": ticker in historical, "adjusted_price_support": "UNKNOWN" if not ticker.isdigit() else "NUMERIC_CONSUMER_CONTRACT_UNCHANGED"}
        for ticker in sorted(current | historical)
    ]
    return {
        "status": "CANDIDATE_ONLY",
        "entries": entries,
        "count": len(entries),
        "numeric_count": sum(entry["ticker"].isdigit() for entry in entries),
        "alphanumeric_count": sum(not entry["ticker"].isdigit() for entry in entries),
        "actual_freeze": False,
    }


def run_reconciliation_preflight(
    *,
    target_identities_path: str | Path = DEFAULT_TARGET_IDENTITY_PATH,
    basic_info_root: str | Path = DEFAULT_RAW_ROOT,
    calendar_dates: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Run the default offline preflight; no classification occurs without raw authority."""

    target = load_target_identities(target_identities_path)
    raw = load_basic_info_snapshots(basic_info_root, calendar_dates=calendar_dates)
    if not raw.ready:
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
    reconciliation = reconcile_target_identities(target["identities"], raw.snapshots, expected_dates=_expected_dates(calendar_dates), source_manifest_sha256=raw.raw_manifest_sha256)
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
    }


reconcile_historical_universe = reconcile_target_identities


__all__ = [
    "AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION",
    "BLOCKED_RECONCILIATION_INPUT_AUTHORITY",
    "CLASS_COMMON",
    "CLASS_NOT_COMMON",
    "CLASS_UNRESOLVED",
    "DEFAULT_HARNESS_OUTPUT_DIR",
    "DEFAULT_RAW_ROOT",
    "DEFAULT_TARGET_IDENTITY_PATH",
    "EXPECTED_ALPHANUMERIC_TOTAL",
    "EXPECTED_NUMERIC_TOTAL",
    "EXPECTED_TARGET_TOTAL",
    "HISTORICAL_AUTHORITY_UNRESOLVED",
    "HISTORICAL_COMMON_REQUIRED",
    "HISTORICAL_NOT_COMMON",
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
    "load_target_identities",
    "reconcile_historical_universe",
    "reconcile_target_identities",
    "run_reconciliation_preflight",
    "target_identity_set_hash",
    "write_target_identity_artifact",
]
