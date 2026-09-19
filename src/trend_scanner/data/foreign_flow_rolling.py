"""Phase 3A foreign-flow rolling snapshot orchestration.

This module reuses :class:`ForeignFlowDataProvider` for date-level collection and
the Phase 1 rolling market calendar for completeness.  It deliberately does not
change the foreign-flow feature calculation semantics or the production artifact
while being exercised by focused tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Iterable

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.foreign_flow_provider import (
    ForeignFlowDataProvider,
    compute_file_sha256,
)
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar


PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

FLOW_SOURCE_DIR = Path("artifacts/patterns/pattern_a/production/flow/source")
FLOW_PARQUET_TEMPLATE = "foreign_flow_daily_{date}.parquet"
FLOW_META_TEMPLATE = "foreign_flow_daily_{date}_meta.json"

REQUIRED_FLOW_COLUMNS = (
    "date",
    "ticker",
    "foreign_net_buy_value",
    "foreign_buy_value",
    "foreign_sell_value",
)
_SNAPSHOT_RE = re.compile(r"^foreign_flow_daily_(?P<date>\d{8})\.parquet$")


@dataclass
class ForeignFlowRollingResult:
    """Structured result returned by the Phase 3A orchestration function."""

    target_as_of: str
    status: str
    reason: str
    seed_snapshot_as_of: str | None = None
    requested_trading_dates: list[str] | None = None
    missing_trading_dates: list[str] | None = None
    fetched_trading_dates: list[str] | None = None
    output_path: Path | None = None
    row_count: int = 0
    date_min: str | None = None
    date_max: str | None = None

    def __post_init__(self) -> None:
        self.requested_trading_dates = list(self.requested_trading_dates or [])
        self.missing_trading_dates = list(self.missing_trading_dates or [])
        self.fetched_trading_dates = list(self.fetched_trading_dates or [])

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for the CLI and reports."""
        return {
            "target_as_of": self.target_as_of,
            "status": self.status,
            "reason": self.reason,
            "seed_snapshot_as_of": self.seed_snapshot_as_of,
            "requested_trading_dates": list(self.requested_trading_dates or []),
            "missing_trading_dates": list(self.missing_trading_dates or []),
            "fetched_trading_dates": list(self.fetched_trading_dates or []),
            "output_path": str(self.output_path) if self.output_path is not None else None,
            "row_count": int(self.row_count),
            "date_min": self.date_min,
            "date_max": self.date_max,
        }


class _BlockedInput(Exception):
    """Internal marker for an expected unavailable or invalid source."""


def _normalise_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="raise").normalize()
    return parsed.strftime("%Y-%m-%d")


def _target_output_path(repo_root: Path, target_as_of: str) -> Path:
    compact = target_as_of.replace("-", "")
    return repo_root / FLOW_SOURCE_DIR / FLOW_PARQUET_TEMPLATE.format(date=compact)


def _meta_path(parquet_path: Path) -> Path:
    match = _SNAPSHOT_RE.fullmatch(parquet_path.name)
    if match is None:
        raise ValueError(f"Unexpected foreign-flow snapshot filename: {parquet_path.name}")
    return parquet_path.with_name(FLOW_META_TEMPLATE.format(date=match.group("date")))


def _normalise_flow_rows(frame: pd.DataFrame, *, context: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise _BlockedInput(f"{context}:NON_DATAFRAME_RESPONSE")
    missing = [column for column in REQUIRED_FLOW_COLUMNS if column not in frame.columns]
    if missing:
        raise _BlockedInput(f"{context}:MISSING_COLUMNS:{','.join(missing)}")
    if frame.empty:
        raise _BlockedInput(f"{context}:EMPTY_RESPONSE")

    result = frame.copy()
    if result["date"].isna().any() or result["ticker"].isna().any():
        raise _BlockedInput(f"{context}:NULL_KEY")
    try:
        result["date"] = pd.to_datetime(result["date"], errors="raise").dt.strftime("%Y-%m-%d")
    except Exception as exc:  # noqa: BLE001 - normalise source failures to BLOCKED
        raise _BlockedInput(f"{context}:INVALID_DATE") from exc
    result["ticker"] = result["ticker"].astype(str).str.strip().str.zfill(6)
    if (result["ticker"] == "").any():
        raise _BlockedInput(f"{context}:EMPTY_TICKER")

    try:
        for column in REQUIRED_FLOW_COLUMNS[2:]:
            result[column] = pd.to_numeric(result[column], errors="raise")
    except Exception as exc:  # noqa: BLE001 - normalise source failures to BLOCKED
        raise _BlockedInput(f"{context}:INVALID_NUMERIC_VALUE") from exc

    if result.duplicated(subset=["date", "ticker"]).any():
        raise _BlockedInput(f"{context}:DUPLICATE_DATE_TICKER")
    return result


def _load_valid_snapshot(parquet_path: Path, *, expected_as_of: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load and minimally validate one exact-date snapshot."""
    match = _SNAPSHOT_RE.fullmatch(parquet_path.name)
    if match is None:
        raise _BlockedInput("SNAPSHOT_FILENAME_INVALID")
    filename_as_of = _normalise_date(match.group("date"))
    if filename_as_of != expected_as_of:
        raise _BlockedInput("SNAPSHOT_FILENAME_DATE_MISMATCH")

    meta_path = _meta_path(parquet_path)
    if not meta_path.exists():
        raise _BlockedInput("SNAPSHOT_META_MISSING")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - invalid seed is a blocked input
        raise _BlockedInput("SNAPSHOT_META_INVALID") from exc
    if not isinstance(meta, dict):
        raise _BlockedInput("SNAPSHOT_META_INVALID")
    try:
        meta_as_of = _normalise_date(meta["requested_as_of"])
    except Exception as exc:  # noqa: BLE001 - invalid seed is a blocked input
        raise _BlockedInput("SNAPSHOT_META_REQUESTED_AS_OF_INVALID") from exc
    if meta_as_of != filename_as_of:
        raise _BlockedInput("SNAPSHOT_META_FILENAME_DATE_MISMATCH")

    try:
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:  # noqa: BLE001 - unreadable seed is a blocked input
        raise _BlockedInput("SNAPSHOT_PARQUET_UNREADABLE") from exc
    frame = _normalise_flow_rows(frame, context="SNAPSHOT")
    if frame["date"].gt(expected_as_of).any():
        raise _BlockedInput("SNAPSHOT_DATE_AFTER_REQUESTED_AS_OF")
    return frame, meta


def _find_snapshot_paths(source_dir: Path) -> Iterable[tuple[str, Path]]:
    for candidate in sorted(source_dir.glob("foreign_flow_daily_*.parquet")):
        match = _SNAPSHOT_RE.fullmatch(candidate.name)
        if match is not None:
            yield _normalise_date(match.group("date")), candidate


def _calendar_dates(calendar: Any) -> list[str]:
    trading_dates = getattr(calendar, "trading_dates", calendar)
    try:
        parsed = pd.to_datetime(list(trading_dates), errors="raise").normalize()
    except Exception as exc:  # noqa: BLE001 - invalid authority is blocked
        raise _BlockedInput("ROLLING_MARKET_CALENDAR_INVALID") from exc
    if len(parsed) == 0:
        raise _BlockedInput("ROLLING_MARKET_CALENDAR_EMPTY")
    return sorted({date.strftime("%Y-%m-%d") for date in parsed})


def _load_calendar(repo_root: Path, calendar: Any | None) -> Any:
    resolved = calendar if calendar is not None else load_rolling_production_market_calendar(repo_root)
    if resolved is None:
        raise _BlockedInput("ROLLING_MARKET_CALENDAR_UNAVAILABLE")
    return resolved


def _required_trading_dates(calendar: Any, *, start_as_of: str, target_as_of: str) -> list[str]:
    return [
        date
        for date in _calendar_dates(calendar)
        if start_as_of <= date <= target_as_of
    ]


def _result(
    *,
    target_as_of: str,
    status: str,
    reason: str,
    output_path: Path | None,
    seed_snapshot_as_of: str | None = None,
    requested: list[str] | None = None,
    missing: list[str] | None = None,
    fetched: list[str] | None = None,
    frame: pd.DataFrame | None = None,
) -> ForeignFlowRollingResult:
    date_min = date_max = None
    row_count = 0
    if frame is not None and not frame.empty:
        date_min = str(frame["date"].min())
        date_max = str(frame["date"].max())
        row_count = len(frame)
    return ForeignFlowRollingResult(
        target_as_of=target_as_of,
        status=status,
        reason=reason,
        seed_snapshot_as_of=seed_snapshot_as_of,
        requested_trading_dates=requested,
        missing_trading_dates=missing,
        fetched_trading_dates=fetched,
        output_path=output_path,
        row_count=row_count,
        date_min=date_min,
        date_max=date_max,
    )


def _publish_snapshot(
    *,
    repo_root: Path,
    output_path: Path,
    target_as_of: str,
    frame: pd.DataFrame,
    seed_snapshot_as_of: str,
    incremental_trading_dates: list[str],
    requested_trading_dates: list[str],
) -> None:
    """Validate in memory, then publish parquet and metadata without CSV output."""
    final_frame = _normalise_flow_rows(frame, context="FINAL")
    if final_frame["date"].gt(target_as_of).any():
        raise _BlockedInput("FINAL_DATE_AFTER_REQUESTED_AS_OF")
    final_completed_dates = set(final_frame["date"].unique())
    missing_final = set(requested_trading_dates) - final_completed_dates
    if missing_final:
        raise _BlockedInput("FINAL_TRADING_DATE_GAP")
    final_frame = final_frame.sort_values(by=["date", "ticker"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temp_parquet = output_path.with_name(f".{output_path.name}.{token}.tmp.parquet")
    meta_path = _meta_path(output_path)
    temp_meta = meta_path.with_name(f".{meta_path.name}.{token}.tmp")
    try:
        final_frame.to_parquet(temp_parquet, index=False)
        meta = {
            "source_name": "KRX_PYKRX_FOREIGN_FLOW",
            "requested_as_of": target_as_of,
            "seed_snapshot_as_of": seed_snapshot_as_of,
            "existing_cache_through": seed_snapshot_as_of,
            "incremental_trading_dates": list(incremental_trading_dates),
            "trading_dates_count": len(requested_trading_dates),
            "date_min": str(final_frame["date"].min()),
            "date_max": str(final_frame["date"].max()),
            "row_count": len(final_frame),
            "ticker_count": int(final_frame["ticker"].nunique()),
            "parquet_file": str(output_path.relative_to(repo_root)),
            "parquet_sha256": compute_file_sha256(temp_parquet),
            "pykrx_data_calls": len(incremental_trading_dates),
        }
        temp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_parquet, output_path)
        os.replace(temp_meta, meta_path)
    finally:
        for temporary in (temp_parquet, temp_meta):
            if temporary.exists():
                temporary.unlink()


def update_foreign_flow_snapshot(
    target_as_of: str,
    *,
    repo_root: Path,
    provider: Any | None = None,
    calendar: Any | None = None,
) -> ForeignFlowRollingResult:
    """Incrementally publish one exact-date foreign-flow snapshot.

    The target date is always caller supplied.  Existing snapshots are read only
    until all missing dates have been fetched and final completeness has passed.
    """
    try:
        target = _normalise_date(target_as_of)
    except Exception:
        return _result(
            target_as_of=str(target_as_of),
            status=FAILED,
            reason="INVALID_TARGET_AS_OF",
            output_path=None,
        )

    repo_root = Path(repo_root)
    source_dir = repo_root / FLOW_SOURCE_DIR
    output_path = _target_output_path(repo_root, target)

    exact_frame: pd.DataFrame | None = None
    exact_meta: dict[str, Any] | None = None

    # A structurally valid exact target still needs rolling-calendar completeness.
    # Only a complete target is a pure, zero-call, zero-write NOOP.
    if output_path.exists():
        try:
            exact_frame, exact_meta = _load_valid_snapshot(output_path, expected_as_of=target)
        except _BlockedInput:
            exact_frame = None
        if exact_frame is not None:
            try:
                calendar = _load_calendar(repo_root, calendar)
                exact_requested_dates = _required_trading_dates(
                    calendar,
                    start_as_of=str(exact_frame["date"].min()),
                    target_as_of=target,
                )
            except _BlockedInput as exc:
                return _result(
                    target_as_of=target,
                    status=BLOCKED,
                    reason=str(exc),
                    output_path=output_path,
                    seed_snapshot_as_of=target,
                    frame=exact_frame,
                )
            except Exception:
                return _result(
                    target_as_of=target,
                    status=BLOCKED,
                    reason="ROLLING_MARKET_CALENDAR_UNAVAILABLE",
                    output_path=output_path,
                    seed_snapshot_as_of=target,
                    frame=exact_frame,
                )

            exact_completed_dates = set(exact_frame["date"].unique())
            exact_missing_dates = [
                date for date in exact_requested_dates if date not in exact_completed_dates
            ]
            if not exact_missing_dates:
                return _result(
                    target_as_of=target,
                    status=NOOP_ALREADY_COMPLETE,
                    reason="EXACT_TARGET_SNAPSHOT_ALREADY_COMPLETE",
                    output_path=output_path,
                    seed_snapshot_as_of=target,
                    requested=exact_requested_dates,
                    missing=[],
                    fetched=[],
                    frame=exact_frame,
                )

    valid_candidates: list[tuple[str, Path, pd.DataFrame, dict[str, Any]]] = []
    if exact_frame is not None:
        valid_candidates.append((target, output_path, exact_frame, exact_meta or {}))
    else:
        for snapshot_as_of, snapshot_path in _find_snapshot_paths(source_dir):
            if snapshot_as_of >= target:
                continue
            try:
                snapshot_frame, snapshot_meta = _load_valid_snapshot(
                    snapshot_path,
                    expected_as_of=snapshot_as_of,
                )
            except _BlockedInput:
                continue
            valid_candidates.append((snapshot_as_of, snapshot_path, snapshot_frame, snapshot_meta))

    if not valid_candidates:
        return _result(
            target_as_of=target,
            status=BLOCKED,
            reason="NO_USABLE_SEED_SNAPSHOT",
            output_path=output_path,
        )

    seed_as_of, _, seed_frame, _ = max(valid_candidates, key=lambda item: item[0])
    seed_date_min = str(seed_frame["date"].min())

    try:
        calendar = _load_calendar(repo_root, calendar)
        requested_dates = _required_trading_dates(
            calendar,
            start_as_of=seed_date_min,
            target_as_of=target,
        )
    except _BlockedInput as exc:
        return _result(
            target_as_of=target,
            status=BLOCKED,
            reason=str(exc),
            output_path=output_path,
            seed_snapshot_as_of=seed_as_of,
        )
    except Exception:
        return _result(
            target_as_of=target,
            status=BLOCKED,
            reason="ROLLING_MARKET_CALENDAR_UNAVAILABLE",
            output_path=output_path,
            seed_snapshot_as_of=seed_as_of,
        )

    completed_dates = set(seed_frame["date"].unique())
    missing_dates = [date for date in requested_dates if date not in completed_dates]
    flow_provider = provider if provider is not None else ForeignFlowDataProvider()
    fetched_frames: list[pd.DataFrame] = []
    fetched_dates: list[str] = []

    for date in missing_dates:
        try:
            fetched = flow_provider.fetch_date_batch(date)
            fetched_frame = _normalise_flow_rows(fetched, context=f"FETCH:{date}")
            if set(fetched_frame["date"].unique()) != {date}:
                raise _BlockedInput(f"FETCH:{date}:DATE_MISMATCH")
        except (MarketDataError, _BlockedInput):
            return _result(
                target_as_of=target,
                status=BLOCKED,
                reason=f"REQUIRED_DATE_FETCH_BLOCKED:{date}",
                output_path=output_path,
                seed_snapshot_as_of=seed_as_of,
                requested=requested_dates,
                missing=missing_dates,
                fetched=fetched_dates,
            )
        except Exception:
            return _result(
                target_as_of=target,
                status=FAILED,
                reason=f"REQUIRED_DATE_FETCH_FAILED:{date}",
                output_path=output_path,
                seed_snapshot_as_of=seed_as_of,
                requested=requested_dates,
                missing=missing_dates,
                fetched=fetched_dates,
            )
        fetched_frames.append(fetched_frame)
        fetched_dates.append(date)

    try:
        frames = [seed_frame, *fetched_frames]
        merged = pd.concat(frames, ignore_index=True)
        merged = _normalise_flow_rows(merged, context="MERGED")
        if merged.duplicated(subset=["date", "ticker"]).any():
            raise _BlockedInput("MERGED:DUPLICATE_DATE_TICKER")
        _publish_snapshot(
            repo_root=repo_root,
            output_path=output_path,
            target_as_of=target,
            frame=merged,
            seed_snapshot_as_of=seed_as_of,
            incremental_trading_dates=missing_dates,
            requested_trading_dates=requested_dates,
        )
    except _BlockedInput as exc:
        return _result(
            target_as_of=target,
            status=BLOCKED,
            reason=str(exc),
            output_path=output_path,
            seed_snapshot_as_of=seed_as_of,
            requested=requested_dates,
            missing=missing_dates,
            fetched=fetched_dates,
        )
    except Exception:
        return _result(
            target_as_of=target,
            status=FAILED,
            reason="UNEXPECTED_MERGE_OR_PUBLISH_ERROR",
            output_path=output_path,
            seed_snapshot_as_of=seed_as_of,
            requested=requested_dates,
            missing=missing_dates,
            fetched=fetched_dates,
        )

    return _result(
        target_as_of=target,
        status=PASS,
        reason="EXACT_TARGET_SNAPSHOT_PUBLISHED",
        output_path=output_path,
        seed_snapshot_as_of=seed_as_of,
        requested=requested_dates,
        missing=missing_dates,
        fetched=fetched_dates,
        frame=merged,
    )
