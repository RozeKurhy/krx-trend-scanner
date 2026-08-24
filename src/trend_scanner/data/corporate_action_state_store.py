"""SQLite-backed corporate-action dirty/refresh state machine."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_detector import (
    CorporateActionDecision,
    CorporateActionDetector,
    CorporateActionSnapshot,
    INITIAL_BASELINE,
    normalise_as_of,
)
from trend_scanner.data.errors import MarketDataError


DEFAULT_CORPORATE_ACTION_STATE_PATH = Path("data/market/state/corporate_action.sqlite3")
STATUSES = ("CLEAN", "DIRTY", "REFRESHING", "FAILED")
ALLOWED_TRANSITIONS = {
    "CLEAN": {"CLEAN", "DIRTY"},
    "DIRTY": {"DIRTY", "REFRESHING"},
    "REFRESHING": {"CLEAN", "FAILED"},
    "FAILED": {"DIRTY", "REFRESHING"},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CorporateActionState:
    ticker: str
    as_of: date
    status: str
    dirty_reason: str | None
    last_success_at: str | None
    last_attempt_at: str | None
    dirty_since: str | None
    last_error: str | None
    updated_at: str
    last_content_sha256: str | None
    refresh_requested_start: str | None
    refresh_requested_end: str | None
    listed_shares: int
    par_value: int | float | None
    listed_shares_semantics: str
    source_name: str

    def snapshot(self) -> CorporateActionSnapshot:
        return CorporateActionSnapshot(
            ticker=self.ticker,
            as_of=self.as_of,
            listed_shares=self.listed_shares,
            par_value=self.par_value,
            listed_shares_semantics=self.listed_shares_semantics,
            source_name=self.source_name,
        )


class CorporateActionStateStore:
    """Persist current state and an append-only transition audit log."""

    def __init__(self, path: Path | str = DEFAULT_CORPORATE_ACTION_STATE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS corporate_action_state (
                    ticker TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('CLEAN','DIRTY','REFRESHING','FAILED')),
                    dirty_reason TEXT,
                    last_success_at TEXT,
                    last_attempt_at TEXT,
                    dirty_since TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    last_content_sha256 TEXT,
                    refresh_requested_start TEXT,
                    refresh_requested_end TEXT,
                    listed_shares INTEGER NOT NULL,
                    par_value REAL,
                    listed_shares_semantics TEXT NOT NULL,
                    source_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS corporate_action_transition_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    reason TEXT,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_corporate_action_log_ticker
                    ON corporate_action_transition_log(ticker, id);
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _row_to_state(row: sqlite3.Row | None) -> CorporateActionState | None:
        if row is None:
            return None
        status = str(row["status"])
        if status not in STATUSES:
            raise MarketDataError(f"알 수 없는 corporate action status입니다: {status}")
        try:
            as_of = normalise_as_of(row["as_of"])
        except MarketDataError:
            raise
        return CorporateActionState(
            ticker=normalize_ticker(row["ticker"]),
            as_of=as_of,
            status=status,
            dirty_reason=row["dirty_reason"],
            last_success_at=row["last_success_at"],
            last_attempt_at=row["last_attempt_at"],
            dirty_since=row["dirty_since"],
            last_error=row["last_error"],
            updated_at=row["updated_at"],
            last_content_sha256=row["last_content_sha256"],
            refresh_requested_start=row["refresh_requested_start"],
            refresh_requested_end=row["refresh_requested_end"],
            listed_shares=int(row["listed_shares"]),
            par_value=row["par_value"],
            listed_shares_semantics=row["listed_shares_semantics"],
            source_name=row["source_name"],
        )

    @staticmethod
    def _insert_log(
        connection: sqlite3.Connection,
        ticker: str,
        from_status: str | None,
        to_status: str,
        as_of: date,
        reason: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO corporate_action_transition_log
                (ticker, from_status, to_status, as_of, reason, occurred_at, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                from_status,
                to_status,
                as_of.isoformat(),
                reason,
                _utc_now(),
                json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _fetch_locked(connection: sqlite3.Connection, ticker: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM corporate_action_state WHERE ticker = ?", (ticker,)
        ).fetchone()

    def get(self, ticker: str) -> CorporateActionState | None:
        normalized = normalize_ticker(ticker)
        with self._connect() as connection:
            return self._row_to_state(self._fetch_locked(connection, normalized))

    def list_states(self) -> list[CorporateActionState]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM corporate_action_state ORDER BY ticker"
            ).fetchall()
        return [self._row_to_state(row) for row in rows]  # type: ignore[list-item]

    def transition_log(self, ticker: str) -> list[dict[str, Any]]:
        normalized = normalize_ticker(ticker)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM corporate_action_transition_log WHERE ticker = ? ORDER BY id",
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def evaluate_and_record(
        self,
        snapshot: CorporateActionSnapshot,
        detector: CorporateActionDetector | None = None,
    ) -> CorporateActionDecision:
        detector = detector or CorporateActionDetector()
        with self._transaction() as connection:
            previous = self._row_to_state(self._fetch_locked(connection, snapshot.ticker))
            if previous is not None and previous.status == "REFRESHING":
                raise MarketDataError("OBSERVATION_DURING_REFRESH")
            decision = detector.evaluate(previous.snapshot() if previous else None, snapshot)
            self._record_observation_locked(connection, snapshot, decision, previous)
            return decision

    def record_observation(
        self,
        snapshot: CorporateActionSnapshot,
        decision: CorporateActionDecision,
    ) -> CorporateActionState:
        if decision.ticker != snapshot.ticker or decision.current_as_of != snapshot.as_of:
            raise MarketDataError("decision과 snapshot의 ticker/as_of가 일치하지 않습니다.")
        with self._transaction() as connection:
            previous = self._row_to_state(self._fetch_locked(connection, snapshot.ticker))
            if previous is not None and previous.status == "REFRESHING":
                raise MarketDataError("OBSERVATION_DURING_REFRESH")
            if previous is None:
                if decision.previous_as_of is not None:
                    raise MarketDataError("STALE_DECISION")
            else:
                if decision.previous_as_of != previous.as_of:
                    raise MarketDataError("STALE_DECISION")
                if snapshot.as_of < previous.as_of:
                    raise MarketDataError("OUT_OF_ORDER")
                if (
                    decision.previous_listed_shares != previous.listed_shares
                    or decision.previous_par_value != previous.par_value
                ):
                    raise MarketDataError("STALE_DECISION")
            return self._record_observation_locked(connection, snapshot, decision, previous)

    def _record_observation_locked(
        self,
        connection: sqlite3.Connection,
        snapshot: CorporateActionSnapshot,
        decision: CorporateActionDecision,
        previous: CorporateActionState | None,
    ) -> CorporateActionState:
        """Persist an already-evaluated observation inside the caller transaction."""

        previous_status = previous.status if previous else None
        now = _utc_now()
        if previous is None:
            target_status = "DIRTY" if decision.is_dirty else "CLEAN"
            dirty_reason = ";".join(decision.dirty_reasons) if decision.is_dirty else INITIAL_BASELINE
            dirty_since = now if decision.is_dirty else None
            last_error = None
        elif decision.is_dirty:
            target_status = "DIRTY"
            dirty_reason = ";".join(decision.dirty_reasons)
            dirty_since = previous.dirty_since or now
            last_error = None
        else:
            target_status = previous.status if previous.status in {"DIRTY", "FAILED"} else "CLEAN"
            dirty_reason = previous.dirty_reason if target_status != "CLEAN" else None
            dirty_since = previous.dirty_since if target_status != "CLEAN" else None
            last_error = previous.last_error if target_status == "FAILED" else None

        if target_status not in STATUSES:
            raise MarketDataError(f"알 수 없는 target status입니다: {target_status}")
        if (
            previous_status is not None
            and target_status != previous_status
            and target_status not in ALLOWED_TRANSITIONS[previous_status]
        ):
            raise MarketDataError(f"허용되지 않은 transition입니다: {previous_status} -> {target_status}")
        values = (
            snapshot.as_of.isoformat(), target_status, dirty_reason,
            previous.last_success_at if previous else None,
            previous.last_attempt_at if previous else None, dirty_since, last_error, now,
            previous.last_content_sha256 if previous else None,
            previous.refresh_requested_start if previous else None,
            previous.refresh_requested_end if previous else None,
            snapshot.listed_shares, snapshot.par_value,
            snapshot.listed_shares_semantics, snapshot.source_name, snapshot.ticker,
        )
        if previous is None:
            connection.execute(
                """
                INSERT INTO corporate_action_state
                (as_of,status,dirty_reason,last_success_at,last_attempt_at,dirty_since,
                 last_error,updated_at,last_content_sha256,refresh_requested_start,
                 refresh_requested_end,listed_shares,par_value,listed_shares_semantics,
                 source_name,ticker)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, values,
            )
        else:
            connection.execute(
                """
                UPDATE corporate_action_state SET
                as_of=?, status=?, dirty_reason=?, last_success_at=?, last_attempt_at=?,
                dirty_since=?, last_error=?, updated_at=?, last_content_sha256=?,
                refresh_requested_start=?, refresh_requested_end=?, listed_shares=?,
                par_value=?, listed_shares_semantics=?, source_name=? WHERE ticker=?
                """, values,
            )
        if previous_status != target_status:
            self._insert_log(
                connection, snapshot.ticker, previous_status, target_status,
                snapshot.as_of, dirty_reason, {"dirty_reasons": list(decision.dirty_reasons)},
            )
        state = self._row_to_state(self._fetch_locked(connection, snapshot.ticker))
        if state is None:
            raise MarketDataError("state 저장 후 조회에 실패했습니다.")
        return state

    def transition(self, ticker: str, to_status: str, reason: str | None = None) -> CorporateActionState:
        normalized = normalize_ticker(ticker)
        if to_status not in STATUSES:
            raise MarketDataError(f"알 수 없는 target status입니다: {to_status}")
        with self._transaction() as connection:
            row = self._fetch_locked(connection, normalized)
            current = self._row_to_state(row)
            if current is None:
                raise MarketDataError("ABSENT ticker는 observation 없이 transition할 수 없습니다.")
            if to_status not in ALLOWED_TRANSITIONS[current.status]:
                raise MarketDataError(f"허용되지 않은 transition입니다: {current.status} -> {to_status}")
            now = _utc_now()
            connection.execute(
                "UPDATE corporate_action_state SET status=?, dirty_reason=?, updated_at=? WHERE ticker=?",
                (to_status, reason or current.dirty_reason, now, normalized),
            )
            self._insert_log(connection, normalized, current.status, to_status, current.as_of, reason)
            result = self._row_to_state(self._fetch_locked(connection, normalized))
            if result is None:
                raise MarketDataError("transition 후 state 조회에 실패했습니다.")
            return result

    def claim_refresh(self, ticker: str) -> bool:
        normalized = normalize_ticker(ticker)
        with self._transaction() as connection:
            current = self._row_to_state(self._fetch_locked(connection, normalized))
            if current is None or current.status not in {"DIRTY", "FAILED"}:
                return False
            now = _utc_now()
            connection.execute(
                "UPDATE corporate_action_state SET status='REFRESHING', last_attempt_at=?, updated_at=? WHERE ticker=?",
                (now, now, normalized),
            )
            self._insert_log(connection, normalized, current.status, "REFRESHING", current.as_of, "REFRESH_CLAIM")
            return True

    def mark_clean(self, ticker: str, content_sha256: str | None = None) -> CorporateActionState:
        normalized = normalize_ticker(ticker)
        with self._transaction() as connection:
            current = self._row_to_state(self._fetch_locked(connection, normalized))
            if current is None or current.status != "REFRESHING":
                raise MarketDataError("REFRESHING 상태에서만 CLEAN 전환할 수 있습니다.")
            now = _utc_now()
            connection.execute(
                """
                UPDATE corporate_action_state SET status='CLEAN', dirty_reason=NULL,
                dirty_since=NULL, last_error=NULL, last_success_at=?, updated_at=?,
                last_content_sha256=? WHERE ticker=?
                """,
                (now, now, content_sha256, normalized),
            )
            self._insert_log(connection, normalized, "REFRESHING", "CLEAN", current.as_of, "REFRESH_SUCCESS")
            result = self._row_to_state(self._fetch_locked(connection, normalized))
            if result is None:
                raise MarketDataError("CLEAN 전환 후 state 조회에 실패했습니다.")
            return result

    def mark_failed(self, ticker: str, reason: str, error: str) -> CorporateActionState:
        normalized = normalize_ticker(ticker)
        with self._transaction() as connection:
            current = self._row_to_state(self._fetch_locked(connection, normalized))
            if current is None or current.status != "REFRESHING":
                raise MarketDataError("REFRESHING 상태에서만 FAILED 전환할 수 있습니다.")
            now = _utc_now()
            connection.execute(
                """
                UPDATE corporate_action_state SET status='FAILED', dirty_reason=?,
                last_error=?, updated_at=? WHERE ticker=?
                """,
                (reason, error[:2000], now, normalized),
            )
            self._insert_log(connection, normalized, "REFRESHING", "FAILED", current.as_of, reason, {"error": error[:2000]})
            result = self._row_to_state(self._fetch_locked(connection, normalized))
            if result is None:
                raise MarketDataError("FAILED 전환 후 state 조회에 실패했습니다.")
            return result

    def recover_interrupted(self, stale_before: datetime | None = None) -> int:
        recovered = 0
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM corporate_action_state WHERE status='REFRESHING'"
            ).fetchall()
            for row in rows:
                last_attempt = row["last_attempt_at"]
                if stale_before is not None and last_attempt:
                    try:
                        attempt = datetime.fromisoformat(last_attempt)
                    except ValueError as exc:
                        raise MarketDataError("last_attempt_at timestamp가 잘못되었습니다.") from exc
                    if attempt >= stale_before:
                        continue
                ticker = normalize_ticker(row["ticker"])
                as_of = normalise_as_of(row["as_of"])
                now = _utc_now()
                connection.execute(
                    "UPDATE corporate_action_state SET status='FAILED', dirty_reason='INTERRUPTED_REFRESH', last_error='INTERRUPTED_REFRESH', updated_at=? WHERE ticker=?",
                    (now, ticker),
                )
                self._insert_log(connection, ticker, "REFRESHING", "FAILED", as_of, "INTERRUPTED_REFRESH")
                recovered += 1
        return recovered


__all__ = [
    "ALLOWED_TRANSITIONS",
    "CorporateActionState",
    "CorporateActionStateStore",
    "DEFAULT_CORPORATE_ACTION_STATE_PATH",
    "STATUSES",
]
