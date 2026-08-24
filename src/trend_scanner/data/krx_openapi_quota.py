"""Local safety accounting for KRX Open API HTTP attempts.

The counter is intentionally not described as the official KRX usage meter.
It records attempts made by this process family, keyed by the KST calendar date,
so a retry or an uncertain transport failure consumes one local unit before the
network opener is called.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
DEFAULT_DB_PATH = Path(".cache/krx_openapi/quota.sqlite3")
DEFAULT_ENDPOINT_LIMIT = 10_000
DEFAULT_GLOBAL_SAFETY_LIMIT = 10_000
DEFAULT_QUOTA_RESERVE = 0


class KrxOpenApiQuotaExceeded(RuntimeError):
    """Raised before an opener call when the local safety limit is exhausted."""

    def __init__(self, message: str, *, endpoint_key: str, usage_date_kst: str, endpoint_before: int, global_before: int) -> None:
        super().__init__(message)
        self.endpoint_key = endpoint_key
        self.usage_date_kst = usage_date_kst
        self.endpoint_before = endpoint_before
        self.global_before = global_before


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


class LocalKrxOpenApiQuota:
    """SQLite-backed endpoint and global local quota counter."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        endpoint_limit: int | None = None,
        global_safety_limit: int | None = None,
        reserve: int | None = None,
    ) -> None:
        configured_path = os.getenv("KRX_OPEN_API_QUOTA_DB", "").strip()
        self.db_path = Path(db_path or configured_path or DEFAULT_DB_PATH)
        self.endpoint_limit = endpoint_limit if endpoint_limit is not None else _int_env("KRX_OPEN_API_DAILY_ENDPOINT_LIMIT", DEFAULT_ENDPOINT_LIMIT)
        self.global_safety_limit = global_safety_limit if global_safety_limit is not None else _int_env("KRX_OPEN_API_DAILY_GLOBAL_SAFETY_LIMIT", DEFAULT_GLOBAL_SAFETY_LIMIT)
        self.reserve = reserve if reserve is not None else _int_env("KRX_OPEN_API_QUOTA_RESERVE", DEFAULT_QUOTA_RESERVE)
        if self.endpoint_limit <= 0 or self.global_safety_limit <= 0:
            raise ValueError("quota limits must be positive")
        if self.reserve >= self.endpoint_limit or self.reserve >= self.global_safety_limit:
            raise ValueError("quota reserve must be lower than both limits")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def usage_date_kst(now: datetime | None = None) -> str:
        moment = now.astimezone(KST) if now is not None and now.tzinfo else (now.replace(tzinfo=KST) if now is not None else datetime.now(KST))
        return moment.date().isoformat()

    @staticmethod
    def utc_now_iso(now: datetime | None = None) -> str:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_usage (
                    usage_date_kst TEXT NOT NULL,
                    endpoint_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                    last_attempt_at_utc TEXT NOT NULL,
                    PRIMARY KEY (usage_date_kst, endpoint_key)
                )
                """
            )

    def reserve_attempt(self, endpoint_key: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Atomically reserve one unit immediately before an opener call."""

        key = endpoint_key.strip().strip("/").split("/")[-1]
        if not key:
            raise ValueError("endpoint_key must not be empty")
        usage_date = self.usage_date_kst(now)
        timestamp = self.utc_now_iso(now)
        endpoint_limit = self.endpoint_limit - self.reserve
        global_limit = self.global_safety_limit - self.reserve
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempt_count FROM quota_usage WHERE usage_date_kst = ? AND endpoint_key = ?",
                (usage_date, key),
            ).fetchone()
            endpoint_before = int(row["attempt_count"]) if row else 0
            global_before = int(connection.execute("SELECT COALESCE(SUM(attempt_count), 0) AS total FROM quota_usage WHERE usage_date_kst = ?", (usage_date,)).fetchone()["total"])
            if endpoint_before >= endpoint_limit or global_before >= global_limit:
                connection.rollback()
                raise KrxOpenApiQuotaExceeded(
                    "local KRX Open API quota exhausted before request",
                    endpoint_key=key,
                    usage_date_kst=usage_date,
                    endpoint_before=endpoint_before,
                    global_before=global_before,
                )
            endpoint_after = endpoint_before + 1
            global_after = global_before + 1
            connection.execute(
                """
                INSERT INTO quota_usage(usage_date_kst, endpoint_key, attempt_count, last_attempt_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(usage_date_kst, endpoint_key) DO UPDATE SET
                    attempt_count = excluded.attempt_count,
                    last_attempt_at_utc = excluded.last_attempt_at_utc
                """,
                (usage_date, key, endpoint_after, timestamp),
            )
            connection.commit()
        return {"usage_date_kst": usage_date, "endpoint_key": key, "quota_endpoint_before": endpoint_before, "quota_endpoint_after": endpoint_after, "quota_global_before": global_before, "quota_global_after": global_after, "last_attempt_at_utc": timestamp}

    def get_usage(self, usage_date_kst: str | None = None) -> dict[str, Any]:
        usage_date = usage_date_kst or self.usage_date_kst()
        with self._connect() as connection:
            rows = connection.execute("SELECT endpoint_key, attempt_count, last_attempt_at_utc FROM quota_usage WHERE usage_date_kst = ? ORDER BY endpoint_key", (usage_date,)).fetchall()
        endpoint_usage = {str(row["endpoint_key"]): int(row["attempt_count"]) for row in rows}
        return {"usage_date_kst": usage_date, "endpoint_usage": endpoint_usage, "global_total": sum(endpoint_usage.values()), "last_attempt_at_utc": max((str(row["last_attempt_at_utc"]) for row in rows), default=None)}

    def get_endpoint_usage(self, endpoint_key: str, usage_date_kst: str | None = None) -> int:
        key = endpoint_key.strip().strip("/").split("/")[-1]
        return int(self.get_usage(usage_date_kst)["endpoint_usage"].get(key, 0))

    def get_global_usage(self, usage_date_kst: str | None = None) -> int:
        return int(self.get_usage(usage_date_kst)["global_total"])

    def remaining(self, endpoint_key: str, usage_date_kst: str | None = None) -> dict[str, int]:
        usage = self.get_usage(usage_date_kst)
        endpoint_used = int(usage["endpoint_usage"].get(endpoint_key.strip().strip("/").split("/")[-1], 0))
        effective_endpoint_limit = self.endpoint_limit - self.reserve
        effective_global_limit = self.global_safety_limit - self.reserve
        return {"endpoint": max(0, effective_endpoint_limit - endpoint_used), "global": max(0, effective_global_limit - int(usage["global_total"]))}
