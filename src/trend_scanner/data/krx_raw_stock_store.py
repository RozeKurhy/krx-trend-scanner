"""Immutable market/date-partitioned store for raw KRX stock snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Iterable
import uuid

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import (
    RAW_COLUMNS,
    SCHEMA_VERSION,
    KrxRawStockSnapshotError,
    is_valid_krx_short_code,
    normalize_bas_dd,
    normalize_market,
    validate_raw_snapshot_frame,
)


def _normalize_store_market(market: str) -> str:
    """Normalize markets supported by the shared raw partition store.

    The stock provider remains limited to KOSPI/KOSDAQ.  ETF snapshots use
    the same lossless partition schema and manifest, but a distinct official
    KRX Open API route; accepting ETF here must not make the stock provider
    silently call a stock endpoint.
    """

    value = str(market).strip().upper()
    if value == "ETF":
        return value
    return normalize_market(value)


DEFAULT_RAW_STOCK_ROOT = Path("data/market/raw/krx_stocks/v01")
MANIFEST_FILENAME = "manifest.sqlite3"
STATUSES = ("COMPLETE", "NO_DATA", "FAILED")


@dataclass(frozen=True)
class RawSnapshotSaveResult:
    market: str
    date: str
    status: str
    operation: str
    file_path: str | None
    row_count: int
    content_sha256: str | None
    file_sha256: str | None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_content_bytes(frame: pd.DataFrame) -> bytes:
    normalized = frame.loc[:, list(RAW_COLUMNS)].copy()
    normalized = normalized.sort_values(["date", "ticker"], kind="mergesort").reset_index(drop=True)
    if not normalized.empty:
        normalized["date"] = pd.to_datetime(normalized["date"]).dt.strftime("%Y-%m-%d")
    return normalized.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _typed_empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "ticker": pd.Series([], dtype="string"),
            **{field: pd.Series([], dtype="int64") for field in RAW_COLUMNS[2:]},
        },
        columns=list(RAW_COLUMNS),
    )


class KrxRawStockStore:
    """Persist immutable KRX market/date partitions with a SQLite manifest."""

    def __init__(self, root: Path | str = DEFAULT_RAW_STOCK_ROOT) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / MANIFEST_FILENAME
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize_manifest()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.manifest_path), timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_manifest(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_snapshot_manifest (
                    market TEXT NOT NULL,
                    date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('COMPLETE','NO_DATA','FAILED')),
                    schema_version TEXT NOT NULL,
                    source_endpoint TEXT NOT NULL,
                    file_path TEXT,
                    row_count INTEGER NOT NULL CHECK(row_count >= 0),
                    content_sha256 TEXT,
                    file_sha256 TEXT,
                    ingested_at_utc TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    PRIMARY KEY (market, date)
                )
                """
            )

    def _partition_path(self, market: str, bas_dd: Any) -> Path:
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        return self.root / f"market={normalized_market}" / f"year={day[:4]}" / f"{day}.parquet"

    def _manifest_row(self, market: str, bas_dd: Any) -> dict[str, Any] | None:
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM raw_snapshot_manifest WHERE market=? AND date=?",
                (normalized_market, day),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_manifest(self, market: str, bas_dd: Any) -> dict[str, Any] | None:
        return self._manifest_row(market, bas_dd)

    def list_manifest(self, market: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM raw_snapshot_manifest"
        params: tuple[Any, ...] = ()
        if market is not None:
            query += " WHERE market=?"
            params = (_normalize_store_market(market),)
        query += " ORDER BY date, market"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def _verify_complete_row(self, row: dict[str, Any], *, expected_frame: pd.DataFrame | None = None) -> pd.DataFrame:
        file_path = Path(str(row["file_path"]))
        if not file_path.is_absolute():
            file_path = self.root / file_path
        if not file_path.exists():
            raise MarketDataError("RAW_PARTITION_INTEGRITY: file missing")
        if row.get("file_sha256") != _sha256_file(file_path):
            raise MarketDataError("RAW_PARTITION_INTEGRITY: file hash mismatch")
        try:
            physical = pd.read_parquet(file_path)
        except Exception as exc:
            raise MarketDataError("RAW_PARTITION_INTEGRITY: parquet read failed") from exc
        try:
            frame = validate_raw_snapshot_frame(physical, row["date"])
        except KrxRawStockSnapshotError as exc:
            raise MarketDataError(f"RAW_PARTITION_INTEGRITY: {exc}") from exc
        if int(row["row_count"]) != len(frame):
            raise MarketDataError("RAW_PARTITION_INTEGRITY: row count mismatch")
        if row.get("content_sha256") != _sha256_bytes(_canonical_content_bytes(frame)):
            raise MarketDataError("RAW_PARTITION_INTEGRITY: content hash mismatch")
        if expected_frame is not None and row.get("content_sha256") != _sha256_bytes(_canonical_content_bytes(expected_frame)):
            raise MarketDataError("RAW_PARTITION_CONFLICT")
        return frame

    def verify_snapshot(self, market: str, bas_dd: Any) -> dict[str, Any]:
        row = self._manifest_row(market, bas_dd)
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        if row is None:
            return {"market": normalized_market, "date": day, "exists": False, "valid": False, "status": None, "errors": ["MISSING_MANIFEST"]}
        if row["status"] == "NO_DATA":
            return {
                "market": normalized_market,
                "date": day,
                "exists": True,
                "valid": row["schema_version"] == SCHEMA_VERSION and int(row["row_count"]) == 0,
                "status": "NO_DATA",
                "errors": [] if row["schema_version"] == SCHEMA_VERSION and int(row["row_count"]) == 0 else ["INVALID_NO_DATA_MANIFEST"],
            }
        if row["status"] != "COMPLETE":
            return {"market": normalized_market, "date": day, "exists": True, "valid": False, "status": row["status"], "errors": [row.get("error_code") or "FAILED"]}
        try:
            frame = self._verify_complete_row(row)
        except MarketDataError as exc:
            return {"market": normalized_market, "date": day, "exists": True, "valid": False, "status": row["status"], "errors": [str(exc)]}
        return {
            "market": normalized_market,
            "date": day,
            "exists": True,
            "valid": True,
            "status": "COMPLETE",
            "row_count": len(frame),
            "content_sha256": row["content_sha256"],
            "file_sha256": row["file_sha256"],
            "errors": [],
        }

    def save_snapshot(
        self,
        market: str,
        bas_dd: Any,
        frame: pd.DataFrame,
        source_endpoint: str,
    ) -> RawSnapshotSaveResult:
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        source_endpoint = str(source_endpoint).strip()
        if not source_endpoint:
            raise MarketDataError("source_endpoint must not be empty")
        try:
            normalized = validate_raw_snapshot_frame(frame, day)
        except KrxRawStockSnapshotError as exc:
            raise MarketDataError(str(exc)) from exc
        content_sha = _sha256_bytes(_canonical_content_bytes(normalized))
        existing = self._manifest_row(normalized_market, day)
        if existing is not None:
            if existing["status"] == "COMPLETE":
                self._verify_complete_row(existing)
                if existing.get("content_sha256") == content_sha:
                    return RawSnapshotSaveResult(normalized_market, day, "COMPLETE", "IDEMPOTENT_NOOP", existing.get("file_path"), len(normalized), content_sha, existing.get("file_sha256"))
                raise MarketDataError("RAW_PARTITION_CONFLICT")
            if existing["status"] == "NO_DATA" and normalized.empty:
                return RawSnapshotSaveResult(normalized_market, day, "NO_DATA", "IDEMPOTENT_NOOP", None, 0, None, None)
            if existing["status"] == "NO_DATA":
                raise MarketDataError("RAW_PARTITION_CONFLICT")

        status = "NO_DATA" if normalized.empty else "COMPLETE"
        final_path = self._partition_path(normalized_market, day)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = final_path.parent / f".{final_path.name}.{uuid.uuid4().hex}.tmp"
        file_sha: str | None = None
        file_path_value: str | None = None
        if status == "COMPLETE":
            try:
                normalized.to_parquet(temp_path, index=False)
                read_back = pd.read_parquet(temp_path)
                read_back = validate_raw_snapshot_frame(read_back, day)
                if _sha256_bytes(_canonical_content_bytes(read_back)) != content_sha:
                    raise MarketDataError("RAW_PARTITION_INTEGRITY: read-back content mismatch")
                file_sha = _sha256_file(temp_path)
                os.replace(temp_path, final_path)
                file_path_value = str(final_path.relative_to(self.root))
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO raw_snapshot_manifest
                        (market,date,status,schema_version,source_endpoint,file_path,row_count,
                         content_sha256,file_sha256,ingested_at_utc,error_code,error_message)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(market,date) DO UPDATE SET
                        status=excluded.status, schema_version=excluded.schema_version,
                        source_endpoint=excluded.source_endpoint, file_path=excluded.file_path,
                        row_count=excluded.row_count, content_sha256=excluded.content_sha256,
                        file_sha256=excluded.file_sha256, ingested_at_utc=excluded.ingested_at_utc,
                        error_code=NULL, error_message=NULL
                    """,
                    (normalized_market, day, status, SCHEMA_VERSION, source_endpoint, file_path_value,
                     len(normalized), content_sha if status == "COMPLETE" else None, file_sha, now, None, None),
                )
                connection.commit()
        except Exception:
            # A newly written partition has no valid manifest until this commit.
            # Never remove a file that belonged to an existing valid partition.
            if status == "COMPLETE" and existing is None and final_path.exists():
                final_path.unlink()
            raise
        return RawSnapshotSaveResult(normalized_market, day, status, "SAVED", file_path_value, len(normalized), content_sha if status == "COMPLETE" else None, file_sha)

    def save_failure(self, market: str, bas_dd: Any, source_endpoint: str, error_code: str, error_message: str = "") -> None:
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        existing = self._manifest_row(normalized_market, day)
        if existing is not None and existing["status"] == "COMPLETE":
            self._verify_complete_row(existing)
            return
        if existing is not None and existing["status"] == "NO_DATA":
            # NO_DATA is a finalized, valid terminal observation.  A later
            # failure must not silently downgrade it to FAILED; correction is
            # intentionally reserved for an explicit repair workflow.
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO raw_snapshot_manifest
                    (market,date,status,schema_version,source_endpoint,file_path,row_count,
                     content_sha256,file_sha256,ingested_at_utc,error_code,error_message)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(market,date) DO UPDATE SET
                    status='FAILED', schema_version=excluded.schema_version,
                    source_endpoint=excluded.source_endpoint, row_count=0,
                    content_sha256=NULL, file_sha256=NULL,
                    ingested_at_utc=excluded.ingested_at_utc,
                    error_code=excluded.error_code, error_message=excluded.error_message
                """,
                (normalized_market, day, "FAILED", SCHEMA_VERSION, source_endpoint, None, 0, None, None,
                 datetime.now(timezone.utc).isoformat(), str(error_code), str(error_message)[:2000]),
            )
            connection.commit()

    def exists(self, market: str, bas_dd: Any) -> bool:
        row = self._manifest_row(market, bas_dd)
        return row is not None and row["status"] in {"COMPLETE", "NO_DATA"}

    def load_snapshot(self, market: str, bas_dd: Any) -> pd.DataFrame:
        normalized_market = _normalize_store_market(market)
        day = normalize_bas_dd(bas_dd)
        row = self._manifest_row(normalized_market, day)
        if row is None:
            raise FileNotFoundError(self._partition_path(normalized_market, day))
        if row["status"] == "NO_DATA":
            return _typed_empty()
        if row["status"] != "COMPLETE":
            raise MarketDataError(f"RAW_PARTITION_{row['status']}")
        return self._verify_complete_row(row).copy()

    def list_dates(self, market: str) -> list[str]:
        return [str(row["date"]) for row in self.list_manifest(market) if row["status"] in {"COMPLETE", "NO_DATA"}]

    def load_ticker(self, ticker: str, start: Any | None = None, end: Any | None = None) -> pd.DataFrame:
        value = str(ticker)
        if not is_valid_krx_short_code(value):
            raise MarketDataError("RAW_TICKER_FORMAT_ERROR")
        start_day = normalize_bas_dd(start) if start is not None else None
        end_day = normalize_bas_dd(end) if end is not None else None
        if start_day and end_day and start_day > end_day:
            raise MarketDataError("RAW_TICKER_INVALID_RANGE")
        by_date: dict[str, tuple[str, dict[str, Any]]] = {}
        for market in ("KOSPI", "KOSDAQ", "ETF"):
            for day in self.list_dates(market):
                if start_day and day < start_day or end_day and day > end_day:
                    continue
                frame = self.load_snapshot(market, day)
                matched = frame.loc[frame["ticker"].astype(str) == value]
                for _, row in matched.iterrows():
                    if day in by_date:
                        raise MarketDataError("CROSS_MARKET_TICKER_CONFLICT")
                    by_date[day] = (market, row.to_dict())
        if not by_date:
            return _typed_empty()
        rows = [item[1][1] for item in sorted(by_date.items())]
        result = pd.DataFrame(rows, columns=list(RAW_COLUMNS))
        validated = [
            validate_raw_snapshot_frame(group.loc[:, list(RAW_COLUMNS)], day)
            for day, group in result.groupby(result["date"].map(lambda value: normalize_bas_dd(value)), sort=True)
        ]
        return pd.concat(validated, ignore_index=True) if validated else _typed_empty()


__all__ = [
    "DEFAULT_RAW_STOCK_ROOT",
    "MANIFEST_FILENAME",
    "RawSnapshotSaveResult",
    "KrxRawStockStore",
    "SCHEMA_VERSION",
]
