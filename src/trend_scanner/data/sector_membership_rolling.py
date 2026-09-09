"""Build an exact-date Sector Membership authority from KRX Marketplace CSVs.

The production entrypoint reads the official browser-downloaded raw CSVs,
validates all 46 sector contracts, resolves the target universe, and publishes
only after every gate passes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.krx_sector_index import (
    KRX_NATIVE_SECTOR_INDEX_MAP,
    KOSDAQ_SECTOR_CODES,
    KOSPI_SECTOR_CODES,
    MAPPING_CONTRACT_VERSION,
    mapping_contract_sha256,
)
from trend_scanner.data.sector_membership import (
    POLICY_VERSION,
    STORE_COLUMNS,
    SectorMembershipSnapshotUnavailable,
    sector_membership_meta_path_for_date,
    sector_membership_path_for_date,
)


AS_OF = "2026-09-04"
EXPECTED_SECTOR_COUNT = 46
MIN_INTER_CALL_SECONDS = 10.0
MARKETPLACE_SOURCE_TYPE = "KRX_DATA_MARKETPLACE_OFFICIAL_INDEX_CONSTITUENTS_CSV"
MARKETPLACE_ROOT = Path(".cache/krx_marketplace/sector_membership")
CHECKPOINT_ROOT = MARKETPLACE_ROOT.parent / "checkpoints"
TARGET_UNIVERSE_PATH = Path("data/market/rolling_authority/merged_pit_intervals.json")
SOURCE_AUTHORITY = "KRX_DATA_MARKETPLACE_INDEX_CONSTITUENTS"
AGGREGATE_SECTOR_CODES = frozenset({"1021", "1027", "2024"})
VALID_RESOLUTION_STATUSES = frozenset({"MAPPED", "AGGREGATE_ONLY", "UNMAPPED"})
_TICKER_PATTERN = re.compile(r"^[0-9A-Z]{6}$")

NATIVE_SECTOR_CODES = tuple(KRX_NATIVE_SECTOR_INDEX_MAP)
if len(NATIVE_SECTOR_CODES) != EXPECTED_SECTOR_COUNT:
    raise RuntimeError("native sector contract must contain exactly 46 codes")
if set(KOSPI_SECTOR_CODES) | set(KOSDAQ_SECTOR_CODES) != set(NATIVE_SECTOR_CODES):
    raise RuntimeError("native sector market partitions do not cover the 46-code contract")


class RollingMembershipError(ValueError):
    """Raised when a rolling membership run cannot pass its publication gate."""


@dataclass(frozen=True)
class SectorCheckpoint:
    sector_code: str
    sector_name: str
    market: str
    effective_date: str
    member_tickers: tuple[str, ...]
    fetch_status: str
    cache_hit: bool = False
    error: str | None = None


@dataclass(frozen=True)
class RollingMembershipRun:
    report: dict[str, Any]
    snapshot: pd.DataFrame | None
    checkpoints: tuple[SectorCheckpoint, ...]


def _normalise_date(value: str | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _checkpoint_dir(repo_root: Path, effective_date: str) -> Path:
    return repo_root / CHECKPOINT_ROOT / effective_date.replace("-", "")


def _checkpoint_path(repo_root: Path, effective_date: str, sector_code: str) -> Path:
    return _checkpoint_dir(repo_root, effective_date) / f"{sector_code}.json"


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(raw_path)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalise_ticker(value: Any) -> str:
    text = str(value).strip().upper()
    if text.isdigit():
        text = text.zfill(6)
    if not _TICKER_PATTERN.fullmatch(text):
        raise RollingMembershipError(f"INVALID_TICKER_PAYLOAD:{text[:32]}")
    return text


def _normalise_member_payload(payload: Any) -> tuple[str, ...]:
    if payload is None or isinstance(payload, (str, bytes, Mapping)):
        raise RollingMembershipError("INVALID_TICKER_PAYLOAD_TYPE")
    if not isinstance(payload, (list, tuple, set, frozenset, pd.Index, pd.Series)):
        raise RollingMembershipError("INVALID_TICKER_PAYLOAD_TYPE")
    tickers = tuple(sorted(_normalise_ticker(item) for item in payload))
    if not tickers:
        raise RollingMembershipError("EMPTY_MEMBERSHIP_RESPONSE")
    if len(set(tickers)) != len(tickers):
        raise RollingMembershipError("DUPLICATE_TICKER_IN_SECTOR_RESPONSE")
    return tickers


def _checkpoint_to_payload(checkpoint: SectorCheckpoint) -> dict[str, Any]:
    return {
        "sector_code": checkpoint.sector_code,
        "sector_name": checkpoint.sector_name,
        "market": checkpoint.market,
        "effective_date": checkpoint.effective_date,
        "member_tickers": list(checkpoint.member_tickers),
        "fetch_status": checkpoint.fetch_status,
        "cache_hit": checkpoint.cache_hit,
        "error": checkpoint.error,
    }


def _checkpoint_from_payload(
    payload: Mapping[str, Any],
    *,
    sector_code: str,
    effective_date: str,
) -> SectorCheckpoint:
    contract = KRX_NATIVE_SECTOR_INDEX_MAP[sector_code]
    if (
        str(payload.get("sector_code")) != sector_code
        or str(payload.get("sector_name")) != contract["idx_name"]
        or str(payload.get("market")) != contract["market"]
        or str(payload.get("effective_date")) != effective_date
    ):
        raise RollingMembershipError("INVALID_CHECKPOINT_IDENTITY")
    status = str(payload.get("fetch_status", ""))
    raw_tickers = payload.get("member_tickers")
    if status == "SUCCESS":
        tickers = _normalise_member_payload(raw_tickers)
    elif status == "FAILED":
        tickers = tuple()
    else:
        raise RollingMembershipError("INVALID_CHECKPOINT_STATUS")
    return SectorCheckpoint(
        sector_code=sector_code,
        sector_name=contract["idx_name"],
        market=contract["market"],
        effective_date=effective_date,
        member_tickers=tickers,
        fetch_status=status,
        cache_hit=True,
        error=None if payload.get("error") is None else str(payload.get("error")),
    )


def _load_checkpoint(repo_root: Path, effective_date: str, sector_code: str) -> SectorCheckpoint | None:
    path = _checkpoint_path(repo_root, effective_date, sector_code)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise RollingMembershipError("INVALID_CHECKPOINT_PAYLOAD")
        return _checkpoint_from_payload(payload, sector_code=sector_code, effective_date=effective_date)
    except (OSError, json.JSONDecodeError, RollingMembershipError, TypeError, ValueError) as exc:
        raise RollingMembershipError(f"INVALID_CHECKPOINT:{sector_code}:{type(exc).__name__}") from exc


def _save_checkpoint(repo_root: Path, checkpoint: SectorCheckpoint) -> None:
    _atomic_write_json(
        _checkpoint_path(repo_root, checkpoint.effective_date, checkpoint.sector_code),
        _checkpoint_to_payload(checkpoint),
    )


def load_local_target_universe(
    effective_date: str | pd.Timestamp,
    *,
    repo_root: Path,
    path: Path | str | None = None,
) -> pd.DataFrame:
    """Load the local merged PIT COMMON authority for one exact date."""

    date_text = _normalise_date(effective_date)
    target_path = Path(path) if path is not None else repo_root / TARGET_UNIVERSE_PATH
    if not target_path.exists():
        raise RollingMembershipError(f"TARGET_UNIVERSE_MISSING:{target_path}")
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RollingMembershipError(f"TARGET_UNIVERSE_INVALID:{target_path}") from exc
    rows = [
        {
            "ticker": _normalise_ticker(item.get("ticker")),
            "market": str(item.get("market", "")).strip().upper(),
        }
        for item in payload.get("intervals", [])
        if item.get("state") == "COMMON"
        and str(item.get("effective_from", "")) <= date_text <= str(item.get("effective_to", ""))
        and str(item.get("market", "")).strip().upper() in {"KOSPI", "KOSDAQ"}
    ]
    frame = pd.DataFrame(rows, columns=["ticker", "market"])
    if frame.empty or frame["ticker"].duplicated().any():
        raise RollingMembershipError("TARGET_UNIVERSE_DUPLICATE_OR_EMPTY")
    if not frame["market"].isin({"KOSPI", "KOSDAQ"}).all():
        raise RollingMembershipError("TARGET_UNIVERSE_MARKET_INVALID")
    return frame.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)


def _marketplace_manifest_path(repo_root: Path, effective_date: str) -> Path:
    return repo_root / MARKETPLACE_ROOT / effective_date.replace("-", "") / "manifest.json"


def _read_marketplace_csv(path: Path, *, sector_code: str) -> tuple[str, ...]:
    if not path.exists():
        raise RollingMembershipError(f"MARKETPLACE_FILE_MISSING:{sector_code}:{path}")
    try:
        with path.open("r", encoding="cp949", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            required = {"종목코드", "종목명"}
            if not required.issubset(headers):
                raise RollingMembershipError(f"MARKETPLACE_SCHEMA_MISSING:{sector_code}")
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise RollingMembershipError(f"MARKETPLACE_ENCODING_INVALID:{sector_code}") from exc
    if not rows:
        raise RollingMembershipError(f"MARKETPLACE_EMPTY_FILE:{sector_code}")
    tickers: list[str] = []
    for row in rows:
        raw_ticker = str(row.get("종목코드") or "").strip()
        if not raw_ticker:
            raise RollingMembershipError(f"MARKETPLACE_BLANK_TICKER:{sector_code}")
        if not str(row.get("종목명") or "").strip():
            raise RollingMembershipError(f"MARKETPLACE_BLANK_NAME:{sector_code}:{raw_ticker}")
        tickers.append(_normalise_ticker(raw_ticker))
    if len(set(tickers)) != len(tickers):
        raise RollingMembershipError(f"MARKETPLACE_DUPLICATE_TICKER:{sector_code}")
    return tuple(sorted(tickers))


def load_marketplace_sector_checkpoints(
    effective_date: str | pd.Timestamp,
    *,
    repo_root: Path,
    progress_fn: Callable[[str], None] | None = None,
) -> tuple[tuple[SectorCheckpoint, ...], dict[str, Any]]:
    """Load and validate all 46 official KRX Marketplace sector CSVs."""

    date_text = _normalise_date(effective_date)
    manifest_path = _marketplace_manifest_path(repo_root, date_text)
    if not manifest_path.exists():
        raise RollingMembershipError(f"MARKETPLACE_MANIFEST_MISSING:{manifest_path}")
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RollingMembershipError(f"MARKETPLACE_MANIFEST_INVALID:{manifest_path}") from exc
    if not isinstance(raw_manifest, list):
        raise RollingMembershipError("MARKETPLACE_MANIFEST_INVALID_TYPE")
    by_code: dict[str, Mapping[str, Any]] = {}
    for item in raw_manifest:
        if not isinstance(item, Mapping):
            raise RollingMembershipError("MARKETPLACE_MANIFEST_ROW_INVALID")
        code = str(item.get("sector_code", "")).strip()
        if code in by_code:
            raise RollingMembershipError(f"MARKETPLACE_DUPLICATE_SECTOR:{code}")
        by_code[code] = item
    if set(by_code) != set(NATIVE_SECTOR_CODES):
        missing = sorted(set(NATIVE_SECTOR_CODES) - set(by_code))
        unexpected = sorted(set(by_code) - set(NATIVE_SECTOR_CODES))
        raise RollingMembershipError(f"MARKETPLACE_SECTOR_CONTRACT_MISMATCH:missing={missing}:unexpected={unexpected}")

    checkpoints: list[SectorCheckpoint] = []
    for sector_code in NATIVE_SECTOR_CODES:
        contract = KRX_NATIVE_SECTOR_INDEX_MAP[sector_code]
        item = by_code[sector_code]
        if (
            str(item.get("effective_date")) != date_text
            or str(item.get("sector_name")) != contract["idx_name"]
            or str(item.get("market")) != contract["market"]
            or str(item.get("parse_status")) != "PASS"
        ):
            raise RollingMembershipError(f"MARKETPLACE_MANIFEST_CONTRACT_MISMATCH:{sector_code}")
        raw_path = str(item.get("file_path", "")).strip()
        if not raw_path:
            raise RollingMembershipError(f"MARKETPLACE_FILE_PATH_MISSING:{sector_code}")
        path = (repo_root / raw_path).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise RollingMembershipError(f"MARKETPLACE_FILE_OUTSIDE_REPO:{sector_code}") from exc
        tickers = _read_marketplace_csv(path, sector_code=sector_code)
        expected_rows = item.get("row_count")
        if expected_rows is not None and int(expected_rows) != len(tickers):
            raise RollingMembershipError(f"MARKETPLACE_ROW_COUNT_MISMATCH:{sector_code}")
        checkpoint = SectorCheckpoint(
            sector_code=sector_code,
            sector_name=contract["idx_name"],
            market=contract["market"],
            effective_date=date_text,
            member_tickers=tickers,
            fetch_status="SUCCESS",
            cache_hit=True,
        )
        checkpoints.append(checkpoint)
        if progress_fn is not None:
            progress_fn(f"marketplace {sector_code} {len(tickers)}")
    report = {
        "effective_date": date_text,
        "request_date": date_text.replace("-", ""),
        "expected_sector_codes": EXPECTED_SECTOR_COUNT,
        "expected_codes": list(NATIVE_SECTOR_CODES),
        "attempted_calls": 0,
        "attempted_codes": [],
        "successful_codes": [item.sector_code for item in checkpoints],
        "failed_codes": [],
        "successful_sector_count": len(checkpoints),
        "failed_sector_count": 0,
        "duplicate_calls": 0,
        "retry_count": 0,
        "cache_hits": len(checkpoints),
        "min_inter_call_seconds": None,
        "required_min_inter_call_seconds": 0.0,
        "stop_reason": None,
        "source_method": MARKETPLACE_SOURCE_TYPE,
        "source_manifest": str(manifest_path.relative_to(repo_root)),
        "other_financial_network_calls": 0,
    }
    return tuple(checkpoints), report


def _failure_reason(sector_code: str, exc: Exception) -> str:
    return f"LOCAL_FETCHER_FAILURE:{sector_code}:{type(exc).__name__}"


def collect_sector_checkpoints(
    effective_date: str | pd.Timestamp,
    *,
    repo_root: Path,
    fetcher: Callable[[str, str], Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    min_inter_call_seconds: float = MIN_INTER_CALL_SECONDS,
    progress_fn: Callable[[str], None] | None = None,
    retry_failed_checkpoints: bool = False,
) -> tuple[tuple[SectorCheckpoint, ...], dict[str, Any]]:
    """Load Marketplace CSVs, or use an explicit local test fetcher."""

    if fetcher is None:
        return load_marketplace_sector_checkpoints(
            effective_date,
            repo_root=repo_root,
            progress_fn=progress_fn,
        )

    date_text = _normalise_date(effective_date)
    request_date = date_text.replace("-", "")
    fetch = fetcher
    checkpoints: list[SectorCheckpoint] = []
    attempted_codes: list[str] = []
    call_starts: list[float] = []
    cache_hits = 0
    stop_reason: str | None = None
    last_call_start: float | None = None

    for sector_code in NATIVE_SECTOR_CODES:
        cached = _load_checkpoint(repo_root, date_text, sector_code)
        if cached is not None:
            if cached.fetch_status != "SUCCESS":
                if not retry_failed_checkpoints:
                    checkpoints.append(cached)
                    cache_hits += 1
                    stop_reason = f"CHECKPOINT_FAILED:{sector_code}"
                    break
            else:
                checkpoints.append(cached)
                cache_hits += 1
                if progress_fn is not None:
                    progress_fn(f"cache {sector_code} {len(cached.member_tickers)}")
                continue

        if len(attempted_codes) >= EXPECTED_SECTOR_COUNT:
            stop_reason = "SECTOR_HARD_CAP"
            break
        if last_call_start is not None:
            elapsed = monotonic_fn() - last_call_start
            sleep_for = max(0.0, min_inter_call_seconds - elapsed)
            if sleep_for > 0:
                sleep_fn(sleep_for)
        call_start = monotonic_fn()
        last_call_start = call_start
        call_starts.append(call_start)
        attempted_codes.append(sector_code)
        contract = KRX_NATIVE_SECTOR_INDEX_MAP[sector_code]
        try:
            member_tickers = _normalise_member_payload(fetch(sector_code, request_date))
            checkpoint = SectorCheckpoint(
                sector_code=sector_code,
                sector_name=contract["idx_name"],
                market=contract["market"],
                effective_date=date_text,
                member_tickers=member_tickers,
                fetch_status="SUCCESS",
            )
            _save_checkpoint(repo_root, checkpoint)
            checkpoints.append(checkpoint)
            if progress_fn is not None:
                progress_fn(f"live {sector_code} {len(member_tickers)}")
        except Exception as exc:
            checkpoint = SectorCheckpoint(
                sector_code=sector_code,
                sector_name=contract["idx_name"],
                market=contract["market"],
                effective_date=date_text,
                member_tickers=tuple(),
                fetch_status="FAILED",
                error=type(exc).__name__,
            )
            _save_checkpoint(repo_root, checkpoint)
            checkpoints.append(checkpoint)
            stop_reason = _failure_reason(sector_code, exc)
            if progress_fn is not None:
                progress_fn(f"failed {sector_code} {type(exc).__name__}")
            break

    success_codes = [item.sector_code for item in checkpoints if item.fetch_status == "SUCCESS"]
    failed_codes = [item.sector_code for item in checkpoints if item.fetch_status != "SUCCESS"]
    duplicate_calls = len(attempted_codes) - len(set(attempted_codes))
    delays = [right - left for left, right in zip(call_starts, call_starts[1:])]
    report = {
        "effective_date": date_text,
        "request_date": request_date,
        "expected_sector_codes": len(NATIVE_SECTOR_CODES),
        "expected_codes": list(NATIVE_SECTOR_CODES),
        "attempted_calls": len(attempted_codes),
        "attempted_codes": attempted_codes,
        "successful_codes": success_codes,
        "failed_codes": failed_codes,
        "successful_sector_count": len(success_codes),
        "failed_sector_count": len(failed_codes),
        "duplicate_calls": duplicate_calls,
        "retry_count": 0,
        "cache_hits": cache_hits,
        "min_inter_call_seconds": min(delays) if delays else None,
        "required_min_inter_call_seconds": min_inter_call_seconds,
        "stop_reason": stop_reason,
        "source_method": "TEST_INJECTED_LOCAL_FETCHER",
        "other_financial_network_calls": 0,
    }
    return tuple(checkpoints), report


def resolve_sector_membership(
    target_universe: pd.DataFrame,
    checkpoints: Sequence[SectorCheckpoint],
    *,
    effective_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """Resolve exact-date membership using the frozen most-specific policy."""

    date_text = _normalise_date(effective_date)
    by_ticker: dict[str, list[str]] = {}
    for checkpoint in checkpoints:
        if checkpoint.fetch_status != "SUCCESS":
            continue
        contract = KRX_NATIVE_SECTOR_INDEX_MAP.get(checkpoint.sector_code)
        if contract is None or checkpoint.market != contract["market"]:
            raise RollingMembershipError("INVALID_SECTOR_CHECKPOINT_CONTRACT")
        for ticker in checkpoint.member_tickers:
            by_ticker.setdefault(ticker, []).append(checkpoint.sector_code)

    rows: list[dict[str, Any]] = []
    for row in target_universe.itertuples(index=False):
        ticker = str(row.ticker).strip().upper()
        market = str(row.market).strip().upper()
        candidates = {
            code
            for code in by_ticker.get(ticker, [])
            if KRX_NATIVE_SECTOR_INDEX_MAP[code]["market"] == market
        }
        aggregate = candidates & AGGREGATE_SECTOR_CODES
        leaves = candidates - AGGREGATE_SECTOR_CODES
        if len(leaves) > 1:
            raise RollingMembershipError(f"MULTIPLE_LEAF_MEMBERSHIP:{ticker}")
        if len(leaves) == 1:
            code = next(iter(leaves))
            status = "MAPPED"
        elif len(aggregate) == 1:
            code = next(iter(aggregate))
            status = "AGGREGATE_ONLY"
        elif not candidates:
            code = None
            status = "UNMAPPED"
        else:
            raise RollingMembershipError(f"MULTIPLE_AGGREGATE_MEMBERSHIP:{ticker}")
        contract = KRX_NATIVE_SECTOR_INDEX_MAP.get(code) if code is not None else None
        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "effective_date": date_text,
                "sector_code": code,
                "sector_name": contract["idx_name"] if contract else None,
                "resolution_status": status,
                "policy_version": POLICY_VERSION,
                "source_authority": SOURCE_AUTHORITY,
                "source_artifact_sha256": None,
            }
        )
    frame = pd.DataFrame(rows, columns=list(STORE_COLUMNS))
    if frame.empty or frame["ticker"].duplicated().any():
        raise RollingMembershipError("DUPLICATE_FINAL_TICKER")
    if not set(frame["resolution_status"]).issubset(VALID_RESOLUTION_STATUSES):
        raise RollingMembershipError("INVALID_RESOLUTION_STATUS")
    if not bool(frame["sector_code"].dropna().isin(set(NATIVE_SECTOR_CODES)).all()):
        raise RollingMembershipError("INVALID_FINAL_SECTOR_CODE")
    return frame.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)


def _source_artifact_sha256(checkpoints: Sequence[SectorCheckpoint], target_universe: pd.DataFrame) -> str:
    payload = {
        "checkpoints": [_checkpoint_to_payload(item) for item in checkpoints],
        "target_universe": target_universe.to_dict("records"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(raw_path)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_publish_meta(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_json(path, payload)


def build_rolling_sector_membership(
    effective_date: str | pd.Timestamp = AS_OF,
    *,
    repo_root: Path,
    fetcher: Callable[[str, str], Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    min_inter_call_seconds: float = MIN_INTER_CALL_SECONDS,
    target_universe_path: Path | str | None = None,
    progress_fn: Callable[[str], None] | None = None,
    retry_failed_checkpoints: bool = False,
) -> RollingMembershipRun:
    """Run collection, resolution, validation, and gated publication."""

    date_text = _normalise_date(effective_date)
    target_universe = load_local_target_universe(
        date_text,
        repo_root=repo_root,
        path=target_universe_path,
    )
    checkpoints, fetch_report = collect_sector_checkpoints(
        date_text,
        repo_root=repo_root,
        fetcher=fetcher,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
        min_inter_call_seconds=min_inter_call_seconds,
        progress_fn=progress_fn,
        retry_failed_checkpoints=retry_failed_checkpoints,
    )
    report: dict[str, Any] = {
        **fetch_report,
        "target_population": int(len(target_universe)),
        "target_market_counts": target_universe["market"].value_counts().to_dict(),
        "published": False,
        "publication_status": "BLOCKED",
    }
    if fetch_report["stop_reason"] is not None or fetch_report["successful_sector_count"] != EXPECTED_SECTOR_COUNT:
        report["publication_reason"] = "ALL_46_SECTORS_REQUIRED"
        return RollingMembershipRun(report=report, snapshot=None, checkpoints=checkpoints)

    try:
        snapshot = resolve_sector_membership(target_universe, checkpoints, effective_date=date_text)
    except RollingMembershipError as exc:
        report["publication_reason"] = str(exc)
        return RollingMembershipRun(report=report, snapshot=None, checkpoints=checkpoints)

    source_hash = _source_artifact_sha256(checkpoints, target_universe)
    snapshot["source_artifact_sha256"] = source_hash
    resolved_counts = snapshot["resolution_status"].value_counts().to_dict()
    report.update(
        {
            "mapped": int(resolved_counts.get("MAPPED", 0)),
            "aggregate_only": int(resolved_counts.get("AGGREGATE_ONLY", 0)),
            "unmapped": int(resolved_counts.get("UNMAPPED", 0)),
            "duplicate_final_rows": int(snapshot["ticker"].duplicated().sum()),
            "target_reconciliation": int(len(snapshot)) == int(len(target_universe)),
        }
    )
    if len(snapshot) != len(target_universe) or snapshot["ticker"].duplicated().any():
        report["publication_reason"] = "TARGET_UNIVERSE_RECONCILIATION_FAILED"
        return RollingMembershipRun(report=report, snapshot=None, checkpoints=checkpoints)

    store_path = sector_membership_path_for_date(date_text, repo_root)
    meta_path = sector_membership_meta_path_for_date(date_text, repo_root)
    if store_path.exists() or meta_path.exists():
        report["publication_reason"] = "TARGET_SNAPSHOT_ALREADY_EXISTS"
        return RollingMembershipRun(report=report, snapshot=None, checkpoints=checkpoints)

    _atomic_write_parquet(snapshot, store_path)
    store_sha = _file_sha256(store_path)
    generated_at = datetime.now(timezone.utc).isoformat()
    meta = {
        "schema_version": "SECTOR_MEMBERSHIP_STORE_V01",
        "snapshot_effective_date": date_text,
        "source_authority": SOURCE_AUTHORITY,
        "source_type": MARKETPLACE_SOURCE_TYPE,
        "policy": POLICY_VERSION,
        "source_method": MARKETPLACE_SOURCE_TYPE,
        "source_request_date": date_text.replace("-", ""),
        "source_artifact_sha256": source_hash,
        "mapping_contract_version": MAPPING_CONTRACT_VERSION,
        "mapping_contract_sha256": mapping_contract_sha256(),
        "native_sector_count": len(NATIVE_SECTOR_CODES),
        "sector_count": len(NATIVE_SECTOR_CODES),
        "native_sector_codes": list(NATIVE_SECTOR_CODES),
        "target_universe_path": str((Path(target_universe_path) if target_universe_path is not None else repo_root / TARGET_UNIVERSE_PATH).relative_to(repo_root)),
        "population_total": len(snapshot),
        "target_population": len(snapshot),
        "mapped": int(resolved_counts.get("MAPPED", 0)),
        "mapped_count": int(resolved_counts.get("MAPPED", 0)),
        "aggregate_only": int(resolved_counts.get("AGGREGATE_ONLY", 0)),
        "aggregate_only_count": int(resolved_counts.get("AGGREGATE_ONLY", 0)),
        "unmapped": int(resolved_counts.get("UNMAPPED", 0)),
        "unmapped_count": int(resolved_counts.get("UNMAPPED", 0)),
        "network": fetch_report,
        "generated_at": generated_at,
        "store_sha256": store_sha,
        "store_path": str(store_path.relative_to(repo_root)),
    }
    _atomic_publish_meta(meta_path, meta)
    report.update(
        {
            "published": True,
            "publication_status": "PASS",
            "publication_reason": "ALL_GATES_PASS",
            "parquet": str(store_path.relative_to(repo_root)),
            "meta": str(meta_path.relative_to(repo_root)),
            "store_sha256": store_sha,
        }
    )
    return RollingMembershipRun(report=report, snapshot=snapshot, checkpoints=checkpoints)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build exact-date rolling KRX sector membership authority")
    parser.add_argument("--as-of", default=AS_OF)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--min-delay-seconds", type=float, default=MIN_INTER_CALL_SECONDS)
    parser.add_argument(
        "--retry-failed-checkpoints",
        action="store_true",
        help="Start a new explicit run after a prior failed checkpoint; never retries within one run.",
    )
    args = parser.parse_args()

    def progress(message: str) -> None:
        print(message, flush=True)

    result = build_rolling_sector_membership(
        args.as_of,
        repo_root=args.repo_root.resolve(),
        min_inter_call_seconds=args.min_delay_seconds,
        progress_fn=progress,
        retry_failed_checkpoints=args.retry_failed_checkpoints,
    )
    print(json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0 if result.report.get("published") else 2


if __name__ == "__main__":
    raise SystemExit(main())
