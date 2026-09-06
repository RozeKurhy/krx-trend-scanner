"""Offline helpers for the CONSUMER_MIGRATION_AND_VALIDATION_V01_FIX01.

This module is deliberately an evidence-only layer.  It is not imported by
production scanners/reports and never reads a network source.  The helpers
make the two source frames comparable and keep all classifications explicit so
an evidence runner cannot silently turn a missing or changed row into parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.data.repository_v2 import _project_analytic_sessions, _session_projection_evidence


FIELDS = ("open", "high", "low", "close", "volume", "trading_value")
OHLC_FIELDS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class InputDifference:
    ticker: str
    date: str
    field: str
    legacy_value: Any
    v2_value: Any
    absolute_difference: float | None
    relative_difference: float | None
    authority_classification: str
    consumer_relevance: str


def canonical_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Return a strict, sorted daily frame without filling or joining by position."""

    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(FIELDS), index=pd.DatetimeIndex([], name=None))
    # Select only the comparable columns up front.  The frozen parquet inputs
    # are already numeric/DatetimeIndex in the normal path; avoiding an
    # unconditional deep copy + ``to_numeric`` pass for every ticker keeps the
    # 2,500-ticker census bounded while retaining strict coercion for unusual
    # fixtures.
    result = frame.loc[:, [field for field in FIELDS if field in frame.columns]].copy()
    # Pandas propagates ``DataFrame.attrs`` through scalar access and deep
    # copies it on every ``.at`` lookup.  Session audit attrs may contain the
    # full raw-only evidence list, so comparisons must use a metadata-free
    # view; the original V2 frame remains untouched for canary evidence.
    result.attrs = {}
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.DatetimeIndex(pd.to_datetime(result.index, errors="raise"))
    if not result.index.is_normalized:
        result.index = result.index.normalize()
    for field in result.columns:
        if not pd.api.types.is_numeric_dtype(result[field]):
            result[field] = pd.to_numeric(result[field], errors="coerce")
    if not result.index.is_unique:
        raise ValueError("DUPLICATE_INPUT_DATE")
    return result.sort_index()


def compose_v2_frame(adjusted: pd.DataFrame | None, raw: pd.DataFrame | None, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compose an already-authority-validated adjusted/raw pair exactly as V2 does."""

    if adjusted is None or adjusted.empty or raw is None or raw.empty:
        return canonical_frame(None), {"status": "MISSING_AUTHORITY_INPUT", "ticker": ticker}
    adj = canonical_frame(adjusted).loc[:, list(OHLC_FIELDS)]
    raw_frame = raw.copy()
    if "date" in raw_frame.columns:
        raw_frame.index = pd.DatetimeIndex(pd.to_datetime(raw_frame.pop("date"), errors="raise")).normalize()
    if "ticker" in raw_frame.columns:
        raw_frame = raw_frame.drop(columns=["ticker"])
    # Keep raw ancillary columns for the repository's session audit (they are
    # evidence-only and are not exposed by the composed six-column view).
    raw_frame = raw_frame.sort_index()
    for column in ("open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"):
        if column not in raw_frame.columns:
            raw_frame[column] = 0
        raw_frame[column] = pd.to_numeric(raw_frame[column], errors="coerce")
    raw_frame = raw_frame.loc[:, ["open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"]]
    adj.attrs["ticker"] = ticker
    raw_frame.attrs["ticker"] = ticker
    # The common case is an exact session/date match with no placeholder or
    # analytically invalid candle.  Avoid the repository audit's per-date
    # Series materialisation for this path; it is semantically identical but
    # makes a 2,500-ticker frozen census tractable.  Exceptional dates still
    # go through the canonical fail-closed projection helper below.
    same_dates = set(adj.index) == set(raw_frame.index)
    raw_values = raw_frame[["open", "high", "low", "close", "volume", "trading_value"]]
    placeholder_mask = (
        (raw_values["open"] == 0) & (raw_values["high"] == 0) &
        (raw_values["low"] == 0) & (raw_values["close"] > 0) &
        (raw_values["volume"] == 0) & (raw_values["trading_value"] == 0)
    )
    invalid_mask = (
        (adj["high"] < adj["low"]) | (adj["high"] < adj["open"]) |
        (adj["high"] < adj["close"]) | (adj["low"] > adj["open"]) |
        (adj["low"] > adj["close"])
    )
    if same_dates and not bool(placeholder_mask.any()) and not bool(invalid_mask.any()):
        result = pd.concat([adj.loc[:, list(OHLC_FIELDS)], raw_frame.loc[:, ["volume", "trading_value"]]], axis=1).loc[:, list(FIELDS)]
        return result.sort_index(), {"status": "OK", "confirmed_nontrading_shared_dates": [], "adjusted_analytic_invalid_dates": []}
    try:
        projected_adj, projected_raw, audit = _project_analytic_sessions(adj, raw_frame)
    except Exception:
        # Preserve the exact evidence even for an admitted-session mismatch;
        # the caller must classify it as a blocker rather than silently
        # dropping the ticker.  The evidence helper performs no filling or
        # positional join and returns the same projected frames V2 would have
        # used before its fail-closed guard raised.
        evidence = _session_projection_evidence(adj, raw_frame)
        projected_adj, projected_raw, audit = evidence["projected_adjusted"], evidence["projected_raw"], evidence
        audit["status"] = "REPOSITORY_V2_TRADING_SESSION_MISMATCH"
    result = pd.concat(
        [projected_adj.loc[:, list(OHLC_FIELDS)], projected_raw.loc[:, ["volume", "trading_value"]]],
        axis=1,
    ).loc[:, list(FIELDS)]
    result.attrs["session_projection_audit"] = {
        key: value for key, value in audit.items() if key not in {"projected_adjusted", "projected_raw"}
    }
    return result.sort_index(), {"status": "OK", **result.attrs["session_projection_audit"]}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value


def field_differences(ticker: str, legacy: pd.DataFrame, v2: pd.DataFrame, *, lifecycle: bool = False) -> list[InputDifference]:
    """Emit one record per changed shared cell; equality is exact after numeric coercion."""

    left, right = canonical_frame(legacy), canonical_frame(v2)
    shared = left.index.intersection(right.index).sort_values()
    if len(shared) == 0:
        return []
    left_shared = left.loc[shared, list(FIELDS)]
    right_shared = right.loc[shared, list(FIELDS)]
    unequal = left_shared.ne(right_shared) & ~(left_shared.isna() & right_shared.isna())
    rows: list[InputDifference] = []
    # ``DataFrame.stack`` retains False values for a boolean frame.  Masking
    # them to NA first is essential: otherwise every equal cell would be
    # emitted as a zero-delta difference and the census would report millions
    # of false drifts.
    changed_cells = unequal.where(unequal).stack()
    for date, field in changed_cells.index:
        a, b = left_shared.at[date, field], right_shared.at[date, field]
        av, bv = _number(a), _number(b)
        absolute = abs(av - bv) if av is not None and bv is not None else None
        relative = (absolute / abs(av)) if absolute is not None and av not in (0.0, None) else None
        if field in ("volume", "trading_value"):
            classification = "LEGACY_RAW_ANCILLARY_DRIFT"
            relevance = "CONSUMER_DEPENDENT_RAW_FIELD"
        elif lifecycle:
            classification = "CANONICAL_AUTHORITY_CORRECTION"
            relevance = "LIFECYCLE_BOUNDARY"
        else:
            classification = "LEGACY_ADJUSTED_VALUE_DRIFT"
            relevance = "CONSUMER_DEPENDENT_ADJUSTED_FIELD"
        rows.append(InputDifference(ticker, pd.Timestamp(date).date().isoformat(), field, a, b, absolute, relative, classification, relevance))
    return rows


def classify_row_set(ticker: str, legacy: pd.DataFrame, v2: pd.DataFrame, *, lifecycle_boundary: str | None = None, known_analytic_dates: set[str] | None = None, known_nontrading_dates: set[str] | None = None, authority_gap: bool = False) -> list[dict[str, Any]]:
    """Classify every date-set difference; unknown differences remain explicit."""

    left, right = canonical_frame(legacy), canonical_frame(v2)
    known_analytic_dates = known_analytic_dates or set()
    known_nontrading_dates = known_nontrading_dates or set()
    rows: list[dict[str, Any]] = []
    for date in sorted(set(left.index) ^ set(right.index)):
        iso = pd.Timestamp(date).date().isoformat()
        legacy_present, v2_present = date in left.index, date in right.index
        if lifecycle_boundary and iso < lifecycle_boundary:
            classification = "IDENTITY_LIFECYCLE_CORRECTION"
            reason = f"canonical identity boundary excludes pre-boundary date (<{lifecycle_boundary})"
        elif iso in known_nontrading_dates:
            classification = "KNOWN_NON_TRADING_SESSION_PROJECTION"
            reason = "raw authority placeholder satisfies NON_TRADING_PLACEHOLDER_V01 and is explicitly excluded from analytic view"
        elif iso in known_analytic_dates:
            classification = "CANONICAL_ANALYTIC_SESSION_EXCLUSION"
            reason = "canonical adjusted source marks date analytically unusable"
        elif authority_gap:
            classification = "KNOWN_AUTHORITY_GAP"
            reason = "canonical V2 adjusted/raw authority input is absent for this ticker"
        else:
            classification = "UNEXPLAINED_ROW_SET_DRIFT"
            reason = "no admitted authority classification"
        rows.append({"ticker": ticker, "date": iso, "legacy_present": legacy_present, "v2_present": v2_present, "difference_type": "LEGACY_ONLY" if legacy_present else "V2_ONLY", "authority_classification": classification, "authority_reason": reason})
    return rows


__all__ = ["FIELDS", "OHLC_FIELDS", "InputDifference", "canonical_frame", "compose_v2_frame", "field_differences", "classify_row_set"]
