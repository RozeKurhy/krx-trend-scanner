"""Audit-backed, offline reconciliation for the local KRX quota ledger.

This module never opens a network connection.  It corrects only known local
accounting gaps and records an immutable reconciliation id so reruns are
idempotent and auditable.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RECONCILIATION_TABLE = "quota_reconciliation"
DISCOVERY_DATES = ("2010-01-04", "2018-04-27", "2026-08-21")
DISCOVERY_ENDPOINTS = {"stk_isu_base_info", "ksq_isu_base_info"}


def file_sha256(path: str | Path) -> str:
    """Return a SHA-256 digest without exposing file contents."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _endpoint_key(value: str) -> str:
    key = str(value).strip().strip("/").split("/")[-1]
    if not key:
        raise ValueError("endpoint key must not be empty")
    return key


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RECONCILIATION_TABLE} (
            reconciliation_id TEXT PRIMARY KEY,
            usage_date_kst TEXT NOT NULL,
            endpoint_delta_json TEXT NOT NULL,
            evidence_path TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('APPLIED', 'ALREADY_RECONCILED'))
        )
        """
    )


def reconcile_known_attempts(
    quota: LocalKrxOpenApiQuota,
    *,
    reconciliation_id: str,
    usage_date_kst: str,
    corrections: Mapping[str, int],
    evidence_path: str | Path,
    evidence_sha256: str | None = None,
    applied_at_utc: str | None = None,
) -> dict[str, Any]:
    """Apply positive, evidence-backed deltas exactly once.

    Existing endpoint rows and unrelated endpoints are preserved.  A repeated
    reconciliation id returns ``ALREADY_RECONCILED`` without changing counts.
    """

    if not reconciliation_id.strip():
        raise ValueError("reconciliation_id must not be empty")
    if not _DATE_RE.fullmatch(usage_date_kst):
        raise ValueError("usage_date_kst must be YYYY-MM-DD")
    normalized = {_endpoint_key(key): int(value) for key, value in corrections.items()}
    if not normalized or any(value <= 0 for value in normalized.values()):
        raise ValueError("corrections must contain positive endpoint deltas")
    evidence = Path(evidence_path)
    if not evidence.is_file():
        raise FileNotFoundError(evidence)
    actual_hash = file_sha256(evidence)
    expected_hash = (evidence_sha256 or actual_hash).lower()
    if actual_hash != expected_hash:
        raise ValueError("evidence SHA-256 mismatch")
    applied_at = applied_at_utc or _utc_now()

    with quota._connect() as connection:  # noqa: SLF001 - same canonical SQLite DB
        connection.execute("BEGIN IMMEDIATE")
        _ensure_table(connection)
        existing = connection.execute(
            f"SELECT * FROM {RECONCILIATION_TABLE} WHERE reconciliation_id = ?",
            (reconciliation_id,),
        ).fetchone()
        if existing is not None:
            stored_delta = json.loads(str(existing["endpoint_delta_json"]))
            if (
                str(existing["usage_date_kst"]) != usage_date_kst
                or stored_delta != normalized
                or str(existing["evidence_sha256"]) != actual_hash
            ):
                connection.rollback()
                raise ValueError("reconciliation id already exists with different provenance")
            before = json.loads(str(existing["before_json"]))
            after = json.loads(str(existing["after_json"]))
            connection.commit()
            return {
                "reconciliation_id": reconciliation_id,
                "usage_date_kst": usage_date_kst,
                "endpoint_delta": normalized,
                "evidence_path": str(evidence),
                "evidence_sha256": actual_hash,
                "before": before,
                "after": after,
                "status": "ALREADY_RECONCILED",
                "applied_at_utc": str(existing["applied_at_utc"]),
            }

        before_usage = _usage(connection, usage_date_kst)
        after_endpoint_usage = dict(before_usage["endpoint_usage"])
        for endpoint, delta in normalized.items():
            after_endpoint_usage[endpoint] = after_endpoint_usage.get(endpoint, 0) + delta
            row = connection.execute(
                "SELECT attempt_count, last_attempt_at_utc FROM quota_usage WHERE usage_date_kst = ? AND endpoint_key = ?",
                (usage_date_kst, endpoint),
            ).fetchone()
            timestamp = str(row["last_attempt_at_utc"]) if row else applied_at
            connection.execute(
                """
                INSERT INTO quota_usage(usage_date_kst, endpoint_key, attempt_count, last_attempt_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(usage_date_kst, endpoint_key) DO UPDATE SET attempt_count = excluded.attempt_count
                """,
                (usage_date_kst, endpoint, after_endpoint_usage[endpoint], timestamp),
            )
        after_usage = {"usage_date_kst": usage_date_kst, "endpoint_usage": dict(sorted(after_endpoint_usage.items()))}
        after_usage["global_total"] = sum(after_endpoint_usage.values())
        connection.execute(
            f"""
            INSERT INTO {RECONCILIATION_TABLE}
              (reconciliation_id, usage_date_kst, endpoint_delta_json, evidence_path,
               evidence_sha256, before_json, after_json, applied_at_utc, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'APPLIED')
            """,
            (
                reconciliation_id,
                usage_date_kst,
                json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                str(evidence),
                actual_hash,
                json.dumps(before_usage, sort_keys=True, separators=(",", ":")),
                json.dumps(after_usage, sort_keys=True, separators=(",", ":")),
                applied_at,
            ),
        )
        connection.commit()
    return {
        "reconciliation_id": reconciliation_id,
        "usage_date_kst": usage_date_kst,
        "endpoint_delta": normalized,
        "evidence_path": str(evidence),
        "evidence_sha256": actual_hash,
        "before": before_usage,
        "after": after_usage,
        "status": "APPLIED",
        "applied_at_utc": applied_at,
    }


def validate_historical_authority_discovery_evidence(
    evidence_path: str | Path,
    *,
    usage_date_kst: str,
    corrections: Mapping[str, int],
) -> dict[str, Any]:
    """Validate the exact six-call discovery semantics before any correction."""

    if usage_date_kst != "2026-08-26":
        raise ValueError("historical authority discovery evidence belongs to 2026-08-26")
    expected_delta = {"stk_isu_base_info": 3, "ksq_isu_base_info": 3}
    normalized = {_endpoint_key(key): int(value) for key, value in corrections.items()}
    if normalized != expected_delta:
        raise ValueError("discovery evidence supports exactly +3/+3 basic-info corrections")
    evidence = Path(evidence_path)
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("discovery evidence is unreadable") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("discovery evidence entries are missing")
    matches = [
        entry for entry in entries
        if isinstance(entry, dict)
        and entry.get("source") == "KRX Open API"
        and all(endpoint in str(entry.get("endpoint", "")) for endpoint in DISCOVERY_ENDPOINTS)
    ]
    if len(matches) != 1:
        raise ValueError("expected one six-call KRX Open API discovery entry")
    entry = matches[0]
    timestamp = str(entry.get("timestamp", ""))
    if not timestamp.startswith("2026-08-26") or "+09:00" not in timestamp:
        raise ValueError("discovery timestamp is not a 2026-08-26 KST session")
    rows = entry.get("response_rows")
    if not isinstance(rows, dict) or set(rows) != set(DISCOVERY_DATES):
        raise ValueError("discovery snapshots must cover the three frozen dates")
    endpoint_counts = {endpoint: 0 for endpoint in DISCOVERY_ENDPOINTS}
    for day in DISCOVERY_DATES:
        markets = rows.get(day)
        if not isinstance(markets, dict) or set(markets) != {"KOSPI", "KOSDAQ"}:
            raise ValueError("discovery response rows must include both markets for each date")
        endpoint_counts["stk_isu_base_info"] += 1
        endpoint_counts["ksq_isu_base_info"] += 1
    if entry.get("request_count") != 6 or endpoint_counts != expected_delta:
        raise ValueError("discovery evidence does not prove six basic-info requests")
    if payload.get("logical_request_count", 0) < 6:
        raise ValueError("discovery ledger logical request count is inconsistent")
    return {
        "status": "PASS",
        "evidence_path": str(evidence),
        "usage_date_kst": usage_date_kst,
        "source": entry["source"],
        "timestamp": timestamp,
        "snapshot_dates": list(DISCOVERY_DATES),
        "endpoint_delta": expected_delta,
        "request_count": 6,
        "evidence_sha256": file_sha256(evidence),
    }


def reconcile_historical_authority_discovery(
    quota: LocalKrxOpenApiQuota,
    *,
    reconciliation_id: str,
    usage_date_kst: str,
    corrections: Mapping[str, int],
    evidence_path: str | Path,
    evidence_sha256: str | None = None,
    applied_at_utc: str | None = None,
) -> dict[str, Any]:
    """Semantic gate followed by the generic idempotent ledger correction."""

    semantic = validate_historical_authority_discovery_evidence(
        evidence_path, usage_date_kst=usage_date_kst, corrections=corrections
    )
    result = reconcile_known_attempts(
        quota,
        reconciliation_id=reconciliation_id,
        usage_date_kst=usage_date_kst,
        corrections=corrections,
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha256 or semantic["evidence_sha256"],
        applied_at_utc=applied_at_utc,
    )
    result["semantic_validation"] = semantic
    return result


def _usage(connection: sqlite3.Connection, usage_date_kst: str) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT endpoint_key, attempt_count FROM quota_usage WHERE usage_date_kst = ? ORDER BY endpoint_key",
        (usage_date_kst,),
    ).fetchall()
    endpoints = {str(row["endpoint_key"]): int(row["attempt_count"]) for row in rows}
    return {"usage_date_kst": usage_date_kst, "endpoint_usage": endpoints, "global_total": sum(endpoints.values())}


__all__ = [
    "DISCOVERY_DATES", "DISCOVERY_ENDPOINTS", "RECONCILIATION_TABLE", "file_sha256",
    "reconcile_historical_authority_discovery", "reconcile_known_attempts",
    "validate_historical_authority_discovery_evidence",
]
