#!/usr/bin/env python3
"""Build exact-date B Select Core V2 current status for Phase 4D.

The runner replays the already-sealed B Select candidate event authority against
the exact monthly Pattern B observation authority, then appends the current
published report observation. It emits current lifecycle state only: no new
backtest, portfolio simulation, performance metric, network request, or order.
"""

from __future__ import annotations

import argparse
import bisect
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_source
from scripts.analyze_pattern_b_state_forward_return_v01 import month_end_snapshot_dates
from trend_scanner.data.repository_v2_loader import (
    RepositoryV2DailyLoader,
    build_production_repository_v2,
)
from trend_scanner.backtest.snapshot_context import (
    build_historical_snapshot_from_context,
    build_precomputed_ticker_context,
)
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    load_rolling_production_market_calendar,
)
from trend_scanner.patterns import pattern_b_operational
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b
from trend_scanner.strategies.b_select_core_v2 import (
    BSelectLifecycleError,
    STRATEGY_ID,
    STRATEGY_NAME,
    exact_month_end_sessions,
    is_entry_signal,
    next_exact_session,
    replay_lifecycle,
    resolve_progressed_episode,
)


STAGE_HISTORY_REL = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/"
    "candidate_signal_stage_history.csv"
)
STAGE_HISTORY_METADATA_REL = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/metadata.json"
)
MONTHLY_SAMPLE_REL = pattern_b_source.SAMPLE_PATH
STATUS_RELATIVE = Path("artifacts/strategies/b_select_core_v2/production")
CANONICAL_HISTORY_REBUILD_TARGET_AS_OF = "2026-10-03"
CANONICAL_HISTORY_REBUILD_REFERENCE_DATE = "2026-10-02"
ASSET_TYPE = "COMMON"
SCOPE_TYPE = "PUBLISHED_COMMON_REPORTS"
SCOPE_LABEL = "현재 공개 COMMON 리포트 기준"
ALLOWED_PREVIOUS_STAGES = frozenset({"EARLY_TREND", "TRANSITION"})


class BSelectStatusError(RuntimeError):
    """The B Select current status cannot be produced without ambiguity."""


@lru_cache(maxsize=4)
def _cached_rolling_production_market_calendar(root_path: str) -> Any:
    """Load the immutable rolling calendar once per build root."""
    return load_rolling_production_market_calendar(Path(root_path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BSelectStatusError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _load_candidate_signals(root: Path) -> list[dict[str, Any]]:
    path = root / STAGE_HISTORY_REL
    metadata_path = root / STAGE_HISTORY_METADATA_REL
    if not path.is_file() or not metadata_path.is_file():
        raise BSelectStatusError("B_SELECT_STAGE_HISTORY_AUTHORITY_MISSING")
    metadata = _read_json(metadata_path)
    expected = (
        metadata.get("generated_files", {})
        .get(STAGE_HISTORY_REL.name, {})
        .get("sha256")
    )
    actual = _sha256(path)
    if not expected or actual != expected:
        raise BSelectStatusError("B_SELECT_STAGE_HISTORY_HASH_MISMATCH")
    source_studies = metadata.get("source_studies") or {}
    for rel_key, metadata_key in (
        ("stage_linkage", "stage_linkage_sha256"),
        ("progressed_raw_signals", None),
        ("progressed_trade_ledger", None),
    ):
        rel = source_studies.get(rel_key)
        if not rel:
            continue
        source_path = root / str(rel)
        expected_hash = source_studies.get(metadata_key) if metadata_key else None
        if rel_key == "stage_linkage":
            if not source_path.is_file() or _sha256(source_path) != expected_hash:
                raise BSelectStatusError("B_SELECT_RAW_STAGE_LINKAGE_HASH_MISMATCH")
        elif not source_path.is_file():
            raise BSelectStatusError(f"B_SELECT_SOURCE_MISSING:{rel_key}")
    frame = pd.read_csv(path, dtype={"ticker": "string", "isu_cd": "string"})
    rows = frame.to_dict(orient="records")
    keys = [
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper(), str(row.get("entry_signal_date", ""))[:10])
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise BSelectStatusError("B_SELECT_STAGE_HISTORY_DUPLICATE_KEY")
    return rows


def _current_identity_map(
    intervals: list[dict[str, Any]],
    interval_components: Mapping[tuple[str, str, str, str, str], str],
    reference_market_date: str,
) -> dict[str, dict[str, str]]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in intervals:
        if (
            str(row.get("state", "")).upper() == "COMMON"
            and str(row.get("effective_from", ""))[:10] <= reference_market_date
            <= str(row.get("effective_to", ""))[:10]
        ):
            by_ticker.setdefault(str(row.get("ticker", "")).zfill(6), []).append(row)
    result: dict[str, dict[str, str]] = {}
    for ticker, rows in by_ticker.items():
        if len(rows) != 1:
            raise BSelectStatusError(f"B_SELECT_ACTIVE_IDENTITY_AMBIGUOUS:{ticker}")
        row = rows[0]
        key = pattern_b_source.interval_key(row)
        component_id = interval_components.get(key)
        if not component_id:
            raise BSelectStatusError(f"B_SELECT_ACTIVE_COMPONENT_MISSING:{ticker}")
        result[ticker] = {
            "isu_cd": str(row["isu_cd"]).upper(),
            "market": str(row["market"]).upper(),
            "component_id": component_id,
            "effective_from": str(row["effective_from"])[:10],
            "effective_to": str(row["effective_to"])[:10],
        }
    return result


def _load_monthly_states(
    root: Path,
    intervals: list[dict[str, Any]],
    interval_components: Mapping[tuple[str, str, str, str, str], str],
    trading_dates: list[str],
) -> tuple[pd.DataFrame, int]:
    """Load sealed monthly B observations and rebind them to current PIT intervals.

    The frozen Pattern B sample was built at the 2026-09-21 PIT frontier while
    this monitor uses the 2026-09-23 frontier. An interval end extended by that
    frontier move remains valid for every earlier observation date; ticker,
    ISU, market, effective start, and active date still have to match exactly.
    """
    path = root / MONTHLY_SAMPLE_REL
    if not path.is_file():
        raise BSelectStatusError("B_SELECT_MONTHLY_STATE_AUTHORITY_MISSING")
    frame = pd.read_csv(path, compression="gzip", dtype={"ticker": "string", "isu_cd": "string"})
    frame["ticker"] = frame["ticker"].map(lambda value: str(value).strip().zfill(6))
    frame["isu_cd"] = frame["isu_cd"].map(lambda value: str(value).strip().upper())
    frame["market"] = frame["market"].astype(str).str.upper()
    for column in ("snapshot_date", "effective_from", "effective_to", "monthly_last_bar", "weekly_last_bar"):
        frame[column] = frame[column].fillna("").astype(str).str[:10]
    if frame.duplicated(["ticker", "isu_cd", "snapshot_date"]).any():
        raise BSelectStatusError("B_SELECT_MONTHLY_STATE_DUPLICATE_KEY")
    for column in ("monthly_last_bar", "weekly_last_bar"):
        future = frame[column].ne("") & frame[column].gt(frame["snapshot_date"])
        if future.any():
            raise BSelectStatusError(f"B_SELECT_MONTHLY_STATE_FUTURE_BAR:{column}")
    allowed_states = {"DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED"}
    if not set(frame["state"].dropna().astype(str)) <= allowed_states:
        raise BSelectStatusError("B_SELECT_MONTHLY_STATE_LABEL_INVALID")

    intervals_by_start: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in intervals:
        if str(row.get("state", "")).upper() != "COMMON":
            continue
        key = (
            str(row.get("ticker", "")).zfill(6),
            str(row.get("isu_cd", "")).upper(),
            str(row.get("market", "")).upper(),
            str(row.get("effective_from", ""))[:10],
        )
        intervals_by_start.setdefault(key, []).append(row)
    components: list[str] = []
    invalid_rows: list[str] = []
    for row in frame[["ticker", "isu_cd", "market", "effective_from", "effective_to", "snapshot_date"]].to_dict("records"):
        key = (row["ticker"], row["isu_cd"], row["market"], row["effective_from"])
        matches = [
            interval for interval in intervals_by_start.get(key, [])
            if interval["effective_from"] <= row["snapshot_date"] <= interval["effective_to"]
            and row["effective_from"] <= row["snapshot_date"] <= row["effective_to"]
        ]
        if len(matches) != 1 or row["snapshot_date"] not in trading_dates:
            invalid_rows.append(f"{row['ticker']}:{row['snapshot_date']}")
            components.append("")
            continue
        component = interval_components.get(pattern_b_source.interval_key(matches[0]))
        if not component:
            invalid_rows.append(f"{row['ticker']}:{row['snapshot_date']}:COMPONENT")
            components.append("")
            continue
        components.append(component)
    if invalid_rows:
        raise BSelectStatusError(f"B_SELECT_MONTHLY_STATE_PIT_MISMATCH:{invalid_rows[0]}")
    frame["component_id"] = components
    exclusions = {(str(ticker).zfill(6), str(isu).upper()) for ticker, isu in PERMANENT_IDENTITY_EXCLUSIONS}
    excluded_mask = pd.Series(
        [(ticker, isu) in exclusions for ticker, isu in zip(frame["ticker"], frame["isu_cd"])],
        index=frame.index,
    )
    return frame.loc[~excluded_mask].copy(), len(exclusions)


def _rebind_candidate_components(
    rows: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    interval_components: Mapping[tuple[str, str, str, str, str], str],
    current_tickers: set[str],
) -> list[dict[str, Any]]:
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for interval in intervals:
        if str(interval.get("state", "")).upper() == "COMMON":
            by_identity.setdefault(
                (str(interval.get("ticker", "")).zfill(6), str(interval.get("isu_cd", "")).upper()),
                [],
            ).append(interval)
    for row in rows:
        ticker = str(row.get("ticker", "")).zfill(6)
        if ticker not in current_tickers:
            continue
        isu_cd = str(row.get("isu_cd", "")).upper()
        day = str(row.get("entry_signal_date", ""))[:10]
        matches = [
            interval for interval in by_identity.get((ticker, isu_cd), [])
            if str(interval.get("effective_from", ""))[:10] <= day <= str(interval.get("effective_to", ""))[:10]
        ]
        if len(matches) == 1:
            row["component_id"] = interval_components[pattern_b_source.interval_key(matches[0])]
        else:
            row["component_id"] = "OUTSIDE_ACTIVE_PIT"
    return rows


def _entry_pattern_a_context(
    candidate_rows: list[dict[str, Any]],
    *,
    ticker: str,
    isu_cd: str,
    component_id: str,
    entry_signal_date: str,
) -> dict[str, str]:
    """Resolve one stage-qualified entry row from the sealed candidate authority."""
    day = str(entry_signal_date or "")[:10]
    matches = [
        row for row in candidate_rows
        if str(row.get("ticker", "")).zfill(6) == str(ticker).zfill(6)
        and str(row.get("isu_cd", "")).upper() == str(isu_cd).upper()
        and str(row.get("component_id", "")) == str(component_id)
        and str(row.get("entry_signal_date", ""))[:10] == day
    ]
    if len(matches) != 1:
        raise BSelectStatusError(
            f"B_SELECT_ENTRY_PATTERN_A_SOURCE_MATCH_COUNT:{str(ticker).zfill(6)}:{day}:{len(matches)}"
        )
    source = matches[0]
    entry_stage = str(source.get("entry_pattern_a_stage_recomputed", "")).strip().upper()
    previous_stage = str(source.get("previous_pattern_a_stage", "")).strip().upper()
    previous_date_value = source.get("previous_pattern_a_stage_date")
    previous_date = (
        None
        if previous_date_value is None or pd.isna(previous_date_value)
        else str(previous_date_value).strip()[:10]
    )
    if not previous_date or previous_date.lower() == "nan":
        previous_date = ""
    if (
        entry_stage != "PROGRESSED"
        or previous_stage not in ALLOWED_PREVIOUS_STAGES
        or not previous_date
    ):
        raise BSelectStatusError(
            f"B_SELECT_ENTRY_PATTERN_A_SOURCE_NOT_QUALIFIED:{str(ticker).zfill(6)}:{day}"
        )
    return {
        "entry_pattern_a_stage": entry_stage,
        "entry_previous_pattern_a_stage": previous_stage,
        "entry_previous_pattern_a_stage_date": previous_date,
    }


def _history_before_exact_stage(
    history: list[dict[str, Any]],
    *,
    day: str,
    current_stage: str,
    ticker: str,
) -> list[dict[str, Any]]:
    """Keep prior monthly observations and let exact-day data own its stage.

    A monthly history row marked unavailable because the instrument had no
    exact month-end bar is not a stage observation for an exact daily session
    on that same date. An available same-date monthly stage must still match
    the exact daily evaluator or the replay fails closed.
    """
    exact_day = str(day)[:10]
    result: list[dict[str, Any]] = []
    for row in history:
        row_day = str(row.get("as_of", ""))[:10]
        if row_day > exact_day:
            continue
        if row_day == exact_day and str(row.get("stage", "")) != current_stage:
            if (
                str(row.get("stage", "")) == "UNAVAILABLE"
                and row.get("data_available") is False
            ):
                continue
            raise BSelectStatusError(
                f"B_SELECT_CATCHUP_PATTERN_A_SAME_DAY_STAGE_MISMATCH:{ticker}:{exact_day}"
            )
        result.append(row)
    return result


def _report_previous_stage(
    report: Mapping[str, Any],
    *,
    reference_market_date: str,
    trading_dates: list[str],
    root: Path,
    identity: Mapping[str, str],
    repository: Any | None = None,
    resolve_full_history: bool = True,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    pattern = report.get("pattern") or {}
    current_stage = pattern.get("official_stage")
    history = pattern.get("history_12m") or []
    if current_stage != "PROGRESSED":
        return current_stage, None, None
    stages: dict[str, str] = {}
    for row in history:
        day = str(row.get("as_of", ""))[:10]
        stage = str(row.get("stage", "UNAVAILABLE"))
        if not day or day > reference_market_date or day in stages:
            raise BSelectStatusError(f"B_SELECT_PATTERN_A_HISTORY_INVALID:{identity.get('ticker')}")
        stages[day] = stage
    # The report's 12-month history is monthly, while official_stage belongs
    # to the exact current market-date snapshot. Include that snapshot instead
    # of incorrectly requiring the monthly display history to end today.
    if reference_market_date in stages:
        if stages[reference_market_date] != current_stage:
            raise BSelectStatusError(f"B_SELECT_PATTERN_A_CURRENT_STAGE_MISMATCH:{identity.get('ticker')}")
    else:
        stages[reference_market_date] = str(current_stage or "UNAVAILABLE")
    active_dates = sorted(stages)
    if not active_dates or stages[active_dates[-1]] != current_stage:
        raise BSelectStatusError(f"B_SELECT_PATTERN_A_CURRENT_STAGE_MISMATCH:{identity.get('ticker')}")
    trading_positions = {day: index for index, day in enumerate(trading_dates)}
    snapshot_positions = {day: index for index, day in enumerate(active_dates)}
    result = resolve_progressed_episode(
        active_dates,
        stages,
        active_dates[-1],
        snapshot_positions,
        trading_positions,
    )
    if (
        result["previous_pattern_a_stage"] == "UNAVAILABLE"
        and result["episode_boundary_reason"] == "NO_PRIOR_DISTINCT_STAGE"
    ):
        if not resolve_full_history:
            # The display report contains only a rolling 12-month window. Keep
            # the older stage explicitly unknown unless it can affect today's
            # entry decision; never substitute a guessed predecessor.
            return current_stage, None, result
        # Reports expose only a 12-month display history. Rebuild the same
        # official Stage authority from Repository V2 when the episode starts
        # before that display window; never guess the previous Stage.
        ticker = str(identity["ticker"])
        repository = repository or build_production_repository_v2(root, end=reference_market_date)
        loader = RepositoryV2DailyLoader(repository, start=identity["effective_from"], end=reference_market_date)
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise BSelectStatusError(f"B_SELECT_PATTERN_A_HISTORY_UNAVAILABLE:{ticker}")
        month_ends = [
            day for day in month_end_snapshot_dates(trading_dates, reference_market_date)
            if day >= identity["effective_from"]
        ]
        calendar = MarketCalendarAuthority.from_dates(
            dates=[pd.Timestamp(day) for day in trading_dates],
            completed_month_ends=[pd.Timestamp(day) for day in month_ends],
            last_completed_month=month_ends[-1][:7] if month_ends else None,
            source_name="ROLLING_AUTHORITY_MERGED_CALENDAR_V01",
        )
        full_stages: dict[str, str] = {}
        for day in month_ends:
            snapshot = build_historical_snapshot(
                ticker,
                str((report.get("identity") or {}).get("name") or ticker),
                daily,
                day,
                include_incomplete_periods=False,
                market_calendar=calendar,
            )
            classified = classify_pattern_a_stage(snapshot)
            full_stages[day] = classified.stage.name.upper() if classified.stage else "UNAVAILABLE"
        for row in history:
            day = str(row.get("as_of", ""))[:10]
            if day <= reference_market_date:
                full_stages[day] = str(row.get("stage", "UNAVAILABLE"))
                if day not in month_ends:
                    month_ends.append(day)
        full_stages[reference_market_date] = str(current_stage)
        month_ends.append(reference_market_date)
        month_ends = sorted(set(month_ends))
        full_active = [day for day in month_ends if day >= identity["effective_from"]]
        result = resolve_progressed_episode(
            full_active,
            full_stages,
            full_active[-1],
            {day: index for index, day in enumerate(full_active)},
            trading_positions,
        )
    return current_stage, result["previous_pattern_a_stage"], result


def _month_end_context_from_report(
    report: Mapping[str, Any],
    *,
    day: str,
    trading_dates: list[str],
    root: Path,
    identity: Mapping[str, str],
    repository: Any,
) -> dict[str, Any]:
    """Resolve a missing monthly lifecycle observation from the same-run report.

    Phase 4 reports retain exact month-end Pattern B and Pattern A history even
    when the separate research snapshot authority has an older frontier. Reuse
    those sealed report rows and recompute predecessor lineage only when the
    month-end entry conditions need it.
    """
    target_day = str(day)[:10]
    pattern_b = report.get("pattern_b") or {}
    b_rows_by_source: list[dict[str, Any]] = []
    for field in ("monthly_history_24m", "monthly_history"):
        rows = pattern_b.get(field) or []
        matches = [row for row in rows if str(row.get("as_of", ""))[:10] == target_day]
        if len(matches) > 1:
            raise BSelectStatusError(f"B_SELECT_MONTH_END_PATTERN_B_HISTORY_DUPLICATE:{identity.get('ticker')}:{target_day}")
        if matches:
            b_rows_by_source.append(matches[0])
    if not b_rows_by_source:
        raise BSelectStatusError(f"B_SELECT_MONTH_END_PATTERN_B_HISTORY_MISSING:{identity.get('ticker')}:{target_day}")
    if any(row != b_rows_by_source[0] for row in b_rows_by_source[1:]):
        raise BSelectStatusError(f"B_SELECT_MONTH_END_PATTERN_B_HISTORY_CONFLICT:{identity.get('ticker')}:{target_day}")
    b_row = b_rows_by_source[0]
    monthly_last_bar = str(b_row.get("monthly_last_bar", ""))[:10]
    if monthly_last_bar and monthly_last_bar > target_day:
        raise BSelectStatusError(f"B_SELECT_MONTH_END_PATTERN_B_BAR_MISMATCH:{identity.get('ticker')}:{target_day}")
    b_state = b_row.get("pattern_b_state") if b_row.get("evaluation_status") == "READY" else None

    pattern_a = report.get("pattern") or {}
    a_history = pattern_a.get("history_24m") or pattern_a.get("history_12m") or []
    a_rows = [row for row in a_history if str(row.get("as_of", ""))[:10] == target_day]
    if len(a_rows) > 1:
        raise BSelectStatusError(f"B_SELECT_MONTH_END_PATTERN_A_HISTORY_DUPLICATE:{identity.get('ticker')}:{target_day}")
    a_row = a_rows[0] if a_rows else None
    a_stage = str((a_row or {}).get("stage") or "UNAVAILABLE").upper()
    previous_stage = None
    previous_context = None
    if b_state == "DEPRESSED" and a_stage == "PROGRESSED":
        stage_report = dict(report)
        stage_report["pattern"] = {
            **pattern_a,
            "official_stage": a_stage,
            "history_12m": [
                row for row in (pattern_a.get("history_12m") or [])
                if str(row.get("as_of", ""))[:10] <= target_day
            ],
        }
        _stage, previous_stage, previous_context = _report_previous_stage(
            stage_report,
            reference_market_date=target_day,
            trading_dates=trading_dates,
            root=root,
            identity=identity,
            repository=repository,
            resolve_full_history=True,
        )
    return {
        "date": target_day,
        "pattern_b_state": b_state,
        "pattern_b_evaluation_status": b_row.get("evaluation_status"),
        "pattern_a_stage": a_stage,
        "previous_pattern_a_stage": previous_stage,
        "previous_pattern_a_stage_date": (
            previous_context.get("previous_pattern_a_stage_date") if previous_context else None
        ),
    }


def _latest_prior_status(
    root: Path,
    reference_market_date: str,
    trading_dates: list[str],
) -> tuple[dict[str, Any], str] | None:
    candidates: list[tuple[str, str, dict[str, Any], Path]] = []
    for path in (root / STATUS_RELATIVE).glob("*/status.json"):
        try:
            value = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        prior_reference = str(value.get("reference_market_date", ""))[:10]
        if value.get("strategy_id") == STRATEGY_ID and value.get("status") == "PASS" and prior_reference < reference_market_date:
            candidates.append((prior_reference, str(value.get("requested_as_of", ""))[:10], value, path))
    if not candidates:
        return None
    prior_reference, _, value, path = max(candidates, key=lambda item: (item[0], item[1]))
    try:
        _catchup_session_dates(prior_reference, reference_market_date, trading_dates)
    except ValueError as exc:
        raise BSelectStatusError("B_SELECT_PRIOR_STATUS_DATE_NOT_IN_KRX_CALENDAR") from exc
    return value, str(path.relative_to(root))


def _catchup_session_dates(
    prior_reference_market_date: str,
    reference_market_date: str,
    trading_dates: list[str],
) -> list[str]:
    """Return every exact KRX session after the prior PASS through current reference."""
    prior = str(prior_reference_market_date)[:10]
    current = str(reference_market_date)[:10]
    try:
        prior_index = trading_dates.index(prior)
        current_index = trading_dates.index(current)
    except ValueError as exc:
        raise ValueError("catch-up boundary is not an exact KRX session") from exc
    if current_index <= prior_index:
        raise ValueError("catch-up reference must follow the prior PASS reference")
    return trading_dates[prior_index + 1:current_index + 1]


def _is_new_entry_allowed(ticker: str, isu_cd: str) -> bool:
    return (str(ticker).zfill(6), str(isu_cd).upper()) not in PERMANENT_IDENTITY_EXCLUSIONS


def _build_exact_session_contexts(
    *,
    root: Path,
    ticker: str,
    name: str,
    identity: Mapping[str, str],
    intervals: list[dict[str, Any]],
    trading_dates: list[str],
    session_dates: list[str],
    report_pattern_history: list[dict[str, Any]],
    repository: Any,
    pattern_a_evaluation_dates: set[str] | None = None,
    pattern_a_only_if_pattern_b_depressed: bool = False,
) -> list[dict[str, Any]]:
    """Evaluate exact per-session Pattern A/B state from production authorities.

    This is an in-memory replay input builder. It writes no intermediate status
    artifacts and uses the same Repository V2, Pattern B history chain, Pattern
    A snapshot policy, and frozen evaluators as Stock Report production.
    """
    if not session_dates:
        return []
    calendar = _cached_rolling_production_market_calendar(str(root.resolve()))
    if calendar is None:
        raise BSelectStatusError("B_SELECT_CATCHUP_MARKET_CALENDAR_MISSING")
    calendar_dates = [value.strftime("%Y-%m-%d") for value in calendar.trading_dates]
    if calendar_dates != trading_dates or session_dates[-1] not in calendar_dates:
        raise BSelectStatusError("B_SELECT_CATCHUP_MARKET_CALENDAR_MISMATCH")

    ticker = str(ticker).zfill(6)
    active = [
        row for row in intervals
        if str(row.get("ticker", "")).zfill(6) == ticker
        and str(row.get("isu_cd", "")).upper() == str(identity["isu_cd"]).upper()
        and str(row.get("state", "")).upper() == "COMMON"
        and str(row.get("effective_from", ""))[:10] <= session_dates[-1]
        <= str(row.get("effective_to", ""))[:10]
    ]
    if len(active) != 1:
        raise BSelectStatusError(f"B_SELECT_CATCHUP_ACTIVE_IDENTITY_AMBIGUOUS:{ticker}")

    chain = pattern_b_operational.history_chain(ticker, active[0], intervals, trading_dates)
    pattern_b_daily = pattern_b_operational.load_history(repository, ticker, chain, session_dates[-1])
    if pattern_b_daily is None or pattern_b_daily.empty:
        raise BSelectStatusError(f"B_SELECT_CATCHUP_PATTERN_B_HISTORY_MISSING:{ticker}")
    pattern_a_context = None
    contexts: list[dict[str, Any]] = []
    for day in session_dates:
        pattern_b_result = evaluate_pattern_b(ticker, pattern_b_daily, day, name=name)
        pattern_b_state = (
            pattern_b_result.pattern_b_state
            if pattern_b_result.evaluation_status.value == "READY"
            else None
        )
        should_evaluate_pattern_a = (
            pattern_a_evaluation_dates is None
            or day in pattern_a_evaluation_dates
        ) and not (
            pattern_a_only_if_pattern_b_depressed
            and pattern_b_state != "DEPRESSED"
        )
        if not should_evaluate_pattern_a:
            contexts.append({
                "date": day,
                "pattern_b_state": pattern_b_state,
                "pattern_b_evaluation_status": pattern_b_result.evaluation_status.value,
                "pattern_a_stage": None,
                "previous_pattern_a_stage": None,
                "previous_pattern_a_stage_date": None,
            })
            continue
        if pattern_a_context is None:
            pattern_a_daily = RepositoryV2DailyLoader(repository, end=session_dates[-1]).load(ticker)
            if pattern_a_daily is None or pattern_a_daily.empty:
                raise BSelectStatusError(f"B_SELECT_CATCHUP_PATTERN_A_HISTORY_MISSING:{ticker}")
            pattern_a_context = build_precomputed_ticker_context(ticker, name, pattern_a_daily)
        snapshot = build_historical_snapshot_from_context(
            pattern_a_context,
            day,
            include_incomplete_periods=False,
            market_calendar=calendar,
            market_calendar_as_of=day,
        )
        pattern_a_result = evaluate_pattern_a(snapshot)
        current_stage = (
            pattern_a_result.lifecycle_stage.name.upper()
            if pattern_a_result.lifecycle_stage is not None
            else "UNAVAILABLE"
        )
        previous_stage = None
        previous_context = None
        if current_stage == "PROGRESSED":
            history = _history_before_exact_stage(
                report_pattern_history,
                day=day,
                current_stage=current_stage,
                ticker=ticker,
            )
            stage_report = {
                "identity": {"ticker": ticker, "name": name},
                "pattern": {"official_stage": current_stage, "history_12m": history},
            }
            _stage, previous_stage, previous_context = _report_previous_stage(
                stage_report,
                reference_market_date=day,
                trading_dates=trading_dates,
                root=root,
                identity=identity,
                repository=repository,
                resolve_full_history=(
                    pattern_b_result.pattern_b_state == "DEPRESSED"
                    and current_stage == "PROGRESSED"
                ),
            )
        contexts.append({
            "date": day,
            "pattern_b_state": pattern_b_state,
            "pattern_b_evaluation_status": pattern_b_result.evaluation_status.value,
            "pattern_a_stage": current_stage,
            "previous_pattern_a_stage": previous_stage,
            "previous_pattern_a_stage_date": (
                previous_context.get("previous_pattern_a_stage_date")
                if previous_context else None
            ),
        })
    return contexts


def _feature_boundary_sessions(
    trading_dates: list[str],
    start_date: str,
    end_date: str,
) -> list[str]:
    """Return sessions where completed weekly/monthly Pattern B features change."""
    if start_date > end_date:
        return []
    first = pd.Timestamp(start_date).normalize()
    last = pd.Timestamp(end_date).normalize()
    labels = set(pd.date_range(first, last, freq="W-FRI"))
    labels.update(pd.date_range(first, last, freq=pd.offsets.MonthEnd()))
    output: set[str] = set()
    for label in labels:
        target = label.strftime("%Y-%m-%d")
        position = bisect.bisect_left(trading_dates, target)
        if position < len(trading_dates) and trading_dates[position] <= end_date:
            output.add(trading_dates[position])
    return sorted(output)


def _identity_active_on(
    intervals: list[dict[str, Any]],
    ticker: str,
    isu_cd: str,
    day: str,
) -> bool:
    return any(
        str(row.get("ticker", "")).zfill(6) == str(ticker).zfill(6)
        and str(row.get("isu_cd", "")).upper() == str(isu_cd).upper()
        and str(row.get("state", "")).upper() == "COMMON"
        and str(row.get("effective_from", ""))[:10] <= day <= str(row.get("effective_to", ""))[:10]
        for row in intervals
    )


def _first_valid_open_schedule(
    *,
    repository: Any,
    ticker: str,
    isu_cd: str,
    signal_dates: set[str],
    intervals: list[dict[str, Any]],
    trading_dates: list[str],
    reference_market_date: str,
) -> tuple[dict[str, float], dict[str, str]]:
    """Load exact opens once and schedule each signal at its first valid OPEN."""
    ticker = str(ticker).zfill(6)
    isu_cd = str(isu_cd).upper()
    valid_signal_dates = sorted(day for day in signal_dates if day and day <= reference_market_date)
    if not valid_signal_dates:
        return {}, {}
    first_data_date = next_exact_session(valid_signal_dates[0], trading_dates)
    if first_data_date is None or first_data_date > reference_market_date:
        return {}, {
            day: next_exact_session(reference_market_date, trading_dates) or next_exact_session(day, trading_dates)
            for day in valid_signal_dates
            if next_exact_session(reference_market_date, trading_dates) or next_exact_session(day, trading_dates)
        }
    loader = RepositoryV2DailyLoader(
        repository,
        start=first_data_date,
        end=reference_market_date,
    )
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        raise BSelectStatusError(f"B_SELECT_EXACT_EXECUTION_DATA_MISSING:{ticker}")
    exact_opens: dict[str, float] = {}
    for day in trading_dates:
        if day < first_data_date or day > reference_market_date or day not in daily.index:
            continue
        price = _safe_float(daily.loc[pd.Timestamp(day), "open"])
        if price is not None and price > 0:
            exact_opens[day] = price

    execution_by_signal_date: dict[str, str] = {}
    future_execution_date = next_exact_session(reference_market_date, trading_dates)
    for signal_day in valid_signal_dates:
        execution_day = None
        for day in trading_dates:
            if day <= signal_day:
                continue
            if day > reference_market_date:
                break
            if (
                day in exact_opens
                and _identity_active_on(intervals, ticker, isu_cd, day)
            ):
                execution_day = day
                break
        execution_by_signal_date[signal_day] = execution_day or future_execution_date or next_exact_session(signal_day, trading_dates)
    return exact_opens, {
        day: execution
        for day, execution in execution_by_signal_date.items()
        if execution is not None
    }


def _bucket(action: str, data_status: str) -> str:
    if data_status != "READY":
        return "unavailable"
    if action in {"ENTRY", "ENTER_NEXT_OPEN"}:
        return "entry"
    if action == "HOLD":
        return "hold"
    if action == "EXIT":
        return "exit"
    if action in {"WAIT", "WATCH"}:
        return "watch"
    return "unavailable"


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none"} else text[:10]


def _calendar_authority_payload(provenance: Mapping[str, Any]) -> dict[str, str]:
    frontier = provenance.get("calendar_frontier")
    sha256 = provenance.get("calendar_sha256")
    if not frontier or not sha256:
        raise BSelectStatusError("B_SELECT_CALENDAR_PROVENANCE_MISSING")
    return {"frontier": str(frontier), "sha256": str(sha256)}


def build_b_select_status(
    *,
    repo_root: Path = ROOT,
    index_path: Path | None = None,
    stocks_path: Path | None = None,
    target_as_of: str,
    reference_market_date: str,
    fresh_history_replay: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root)
    if fresh_history_replay and (
        target_as_of != CANONICAL_HISTORY_REBUILD_TARGET_AS_OF
        or reference_market_date != CANONICAL_HISTORY_REBUILD_REFERENCE_DATE
    ):
        raise BSelectStatusError("B_SELECT_CANONICAL_HISTORY_REBUILD_SCOPE_INVALID")
    index_path = Path(index_path or root / "web/data/stock-index.json")
    stocks_path = Path(stocks_path or root / "web/data/stocks")
    index = _read_json(index_path)
    if index.get("requested_as_of") != target_as_of or index.get("reference_market_date") != reference_market_date:
        raise BSelectStatusError("B_SELECT_STOCK_INDEX_DATE_MISMATCH")
    common_rows = [
        item for item in index.get("items", [])
        if isinstance(item, dict) and item.get("report_available") is True and item.get("asset_type") == ASSET_TYPE
    ]
    common_rows.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("ticker") or "")))
    if len(common_rows) != len({str(item.get("ticker", "")).zfill(6) for item in common_rows}):
        raise BSelectStatusError("B_SELECT_DUPLICATE_COMMON_INDEX_TICKER")

    intervals, trading_dates, calendar_provenance = pattern_b_source._load_authorities(root)
    if reference_market_date not in trading_dates:
        raise BSelectStatusError("B_SELECT_REFERENCE_NOT_EXACT_KRX_SESSION")
    month_end_sessions = exact_month_end_sessions(trading_dates)
    interval_components, _ = pattern_b_source._interval_components(intervals, trading_dates)
    identity_by_ticker = _current_identity_map(intervals, interval_components, reference_market_date)
    sample_frame, permanent_exclusion_count = _load_monthly_states(
        root,
        intervals,
        interval_components,
        trading_dates,
    )
    if permanent_exclusion_count != 181:
        raise BSelectStatusError(
            f"B_SELECT_PERMANENT_EXCLUSION_AUTHORITY_COUNT_MISMATCH:{permanent_exclusion_count}"
        )
    sample_authority_frontier = str(sample_frame["snapshot_date"].max())[:10]
    candidate_rows = _load_candidate_signals(root)
    candidate_rows = _rebind_candidate_components(
        candidate_rows,
        intervals,
        interval_components,
        set(identity_by_ticker),
    )
    sample_rows_by_identity = {
        (str(ticker).zfill(6), str(isu_cd).upper(), str(component_id)): group[
            ["snapshot_date", "state"]
        ].sort_values("snapshot_date")
        for (ticker, isu_cd, component_id), group in sample_frame.groupby(
            ["ticker", "isu_cd", "component_id"], sort=False
        )
    }
    current_common_tickers = {
        str(item.get("ticker", "")).zfill(6) for item in common_rows
    }
    monthly_state_by_signal: dict[tuple[str, str, str, str], str] = {}
    for row in sample_frame[
        ["ticker", "isu_cd", "component_id", "snapshot_date", "state"]
    ].to_dict("records"):
        monthly_state_by_signal[(
            str(row["ticker"]).zfill(6),
            str(row["isu_cd"]).upper(),
            str(row["component_id"]),
            str(row["snapshot_date"])[:10],
        )] = str(row["state"])
    canonical_candidate_rows_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    canonical_candidate_signal_keys: set[tuple[str, str, str]] = set()
    for row in candidate_rows:
        ticker = str(row.get("ticker", "")).zfill(6)
        isu_cd = str(row.get("isu_cd", "")).upper()
        component_id = str(row.get("component_id", ""))
        signal_date = _date_text(row.get("entry_signal_date"))
        previous_stage = str(row.get("previous_pattern_a_stage") or "").strip().upper()
        current_stage = str(row.get("entry_pattern_a_stage_recomputed") or "").strip().upper()
        if (
            (ticker, isu_cd) in PERMANENT_IDENTITY_EXCLUSIONS
            or component_id == "OUTSIDE_ACTIVE_PIT"
            or previous_stage not in ALLOWED_PREVIOUS_STAGES
            or current_stage != "PROGRESSED"
        ):
            continue
        if signal_date not in month_end_sessions:
            raise BSelectStatusError(f"B_SELECT_CANDIDATE_ENTRY_NOT_MONTH_END:{ticker}:{signal_date}")
        monthly_state = monthly_state_by_signal.get((ticker, isu_cd, component_id, signal_date))
        if monthly_state != "DEPRESSED":
            raise BSelectStatusError(
                f"B_SELECT_CANDIDATE_ENTRY_MONTHLY_PATTERN_B_MISMATCH:{ticker}:{signal_date}:{monthly_state}"
            )
        if str(row.get("entry_pattern_a_lookahead_free", "")).lower() != "true":
            raise BSelectStatusError(f"B_SELECT_CANDIDATE_ENTRY_PATTERN_A_NOT_PIT:{ticker}:{signal_date}")
        if not is_entry_signal(monthly_state, current_stage, previous_stage):
            raise BSelectStatusError(f"B_SELECT_CANDIDATE_ENTRY_RULE_MISMATCH:{ticker}:{signal_date}")
        signal_key = (ticker, isu_cd, signal_date)
        if signal_key in canonical_candidate_signal_keys:
            raise BSelectStatusError(f"B_SELECT_CANONICAL_CANDIDATE_SIGNAL_DUPLICATE:{ticker}:{signal_date}")
        canonical_candidate_signal_keys.add(signal_key)
        key = (ticker, isu_cd)
        canonical_candidate_rows_by_identity.setdefault(key, []).append(row)
    for rows in canonical_candidate_rows_by_identity.values():
        rows.sort(key=lambda row: _date_text(row.get("entry_signal_date")))
    fresh_month_end_dates = sorted(
        day for day in month_end_sessions
        if sample_authority_frontier < day <= reference_market_date
    )
    fresh_signal_dates = [key[2] for key in canonical_candidate_signal_keys] + fresh_month_end_dates
    fresh_history_start_date = min(fresh_signal_dates) if fresh_signal_dates else reference_market_date
    fresh_exact_sessions = (
        [
            day for day in trading_dates
            if fresh_history_start_date <= day <= reference_market_date
        ]
        if fresh_history_replay
        else []
    )
    fresh_boundary_dates = (
        _feature_boundary_sessions(trading_dates, fresh_history_start_date, reference_market_date)
        if fresh_history_replay
        else []
    )
    candidate_rows_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for candidate in candidate_rows:
        key = (
            str(candidate.get("ticker", "")).zfill(6),
            str(candidate.get("isu_cd", "")).upper(),
            str(candidate.get("component_id", "")),
        )
        candidate_rows_by_identity.setdefault(key, []).append(candidate)
    candidate_entry_execution_mismatch_rows: set[tuple[str, str, str, str, str]] = set()
    candidate_exit_execution_mismatch_rows: set[tuple[str, str, str, str, str]] = set()
    prior_status_result = (
        None
        if fresh_history_replay
        else _latest_prior_status(root, reference_market_date, trading_dates)
    )
    prior_status = prior_status_result[0] if prior_status_result else None
    prior_artifact_path = prior_status_result[1] if prior_status_result else None
    catchup_session_dates: list[str] = []
    prior_source_authorities = (prior_status or {}).get("source_authorities") or {}
    if not fresh_history_replay and prior_status is None:
        raise BSelectStatusError("B_SELECT_V2_BASELINE_MISSING")
    if prior_status is not None:
        if (
            prior_status.get("strategy_id") != STRATEGY_ID
            or prior_source_authorities.get("signal_cadence") != "MONTH_END_ENTRY_DAILY_NORMAL_EXIT"
            or any(
                not isinstance(item.get("trade_history"), list)
                for item in prior_status.get("items", [])
                if isinstance(item, dict)
            )
        ):
            raise BSelectStatusError("B_SELECT_V2_BASELINE_CONTRACT_INVALID")
        try:
            prior_reference = str(prior_status["reference_market_date"])[:10]
            catchup_session_dates = _catchup_session_dates(
                prior_reference, reference_market_date, trading_dates
            )
        except ValueError as exc:
            raise BSelectStatusError("B_SELECT_PRIOR_STATUS_SESSION_RANGE_INVALID") from exc
    prior_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    if prior_status:
        for item in prior_status.get("items", []):
            if isinstance(item, dict):
                prior_by_identity[(str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())] = item
    baseline_strategy_id = str((prior_status or {}).get("strategy_id") or "")
    historical_candidate_signal_count = len(canonical_candidate_signal_keys)

    repo = build_production_repository_v2(root, end=reference_market_date)
    out_items: list[dict[str, Any]] = []
    lifecycle_errors = 0
    date_mismatch_count = 0
    future_reference_count = 0
    duplicate_item_count = 0
    cross_contamination_count = 0
    excluded_items = 0
    excluded_identity_scope_count = 0
    catchup_identity_count = 0
    catchup_observation_count = 0
    reference_run_entry_signal_count = 0
    exact_open_missing_count = 0
    lifecycle_error_details: list[str] = []
    catchup_entry_stage_authorities: dict[tuple[str, str, str, str], dict[str, str]] = {}

    for index_item in common_rows:
        ticker = str(index_item.get("ticker", "")).zfill(6)
        name = str(index_item.get("name") or ticker)
        identity = identity_by_ticker.get(ticker)
        report_path = stocks_path / f"{ticker}.json"
        if identity is None or not report_path.is_file():
            raise BSelectStatusError(f"B_SELECT_COMMON_SOURCE_MISSING:{ticker}")
        identity = {**identity, "ticker": ticker}
        pair = (ticker, identity["isu_cd"])
        report = _read_json(report_path)
        report_identity = report.get("identity") or {}
        technical = report.get("technical_details") or {}
        pattern_b = report.get("pattern_b") or {}
        report_pattern = report.get("pattern") or {}
        if (
            report_identity.get("ticker") != ticker
            or report_identity.get("asset_type") != ASSET_TYPE
            or technical.get("requested_as_of") != target_as_of
            or technical.get("reference_market_date") != reference_market_date
        ):
            date_mismatch_count += 1
            raise BSelectStatusError(f"B_SELECT_REPORT_IDENTITY_OR_DATE_MISMATCH:{ticker}")
        if str(pattern_b.get("as_of", ""))[:10] != reference_market_date:
            date_mismatch_count += 1
            raise BSelectStatusError(f"B_SELECT_PATTERN_B_REFERENCE_MISMATCH:{ticker}")
        pair = (ticker, identity["isu_cd"])
        prior_item = prior_by_identity.get(pair)
        is_excluded_identity = not _is_new_entry_allowed(*pair)
        if is_excluded_identity:
            excluded_identity_scope_count += 1
        if is_excluded_identity:
            excluded_items += 1
            item = {
                "ticker": ticker,
                "isu_cd": identity["isu_cd"],
                "name": name,
                "market": identity["market"],
                "asset_type": ASSET_TYPE,
                "action": "NOT_APPLICABLE",
                "strategy_state": "NOT_APPLICABLE",
                "canonical_position": "NOT_APPLICABLE",
                "action_reason": "PERMANENT_IDENTITY_EXCLUSION",
                "data_status": "NOT_APPLICABLE",
                "pattern_b_state": None,
                "pattern_a_stage": None,
                "previous_pattern_a_stage": None,
                "previous_pattern_a_stage_date": None,
                "current_trade": None,
                "trade_history": [],
                "pending_event": None,
                "latest_close": None,
                "latest_close_as_of": None,
                "bucket": "unavailable",
                "component_id": identity["component_id"],
                "permanent_identity_excluded": True,
            }
            out_items.append(item)
            continue
        b_state = pattern_b.get("pattern_b_state") if pattern_b.get("evaluation_status") == "READY" else None
        current_stage, previous_stage, previous_context = _report_previous_stage(
            report,
            reference_market_date=reference_market_date,
            trading_dates=trading_dates,
            root=root,
            identity=identity,
            repository=repo,
            resolve_full_history=(b_state == "DEPRESSED" and report_pattern.get("official_stage") == "PROGRESSED"),
        )
        latest_close = _safe_float((report.get("price_trend") or {}).get("latest_close"))
        latest_close_as_of = str((report.get("price_trend") or {}).get("latest_close_as_of") or "")[:10] or None
        if latest_close_as_of not in {None, reference_market_date}:
            date_mismatch_count += 1
            raise BSelectStatusError(f"B_SELECT_LATEST_CLOSE_REFERENCE_MISMATCH:{ticker}")

        incremental_identity = bool(
            prior_status
            and prior_item
        )
        observations: list[dict[str, Any]] = []
        entry_signals: list[dict[str, Any]] = []
        entry_context_by_signal_date: dict[str, dict[str, str]] = {}
        identity_key = (ticker, identity["isu_cd"], identity["component_id"])
        sample_rows = sample_rows_by_identity.get(
            identity_key,
            pd.DataFrame(columns=["snapshot_date", "state"]),
        )
        sample_rows = sample_rows.loc[sample_rows["snapshot_date"].astype(str).le(reference_market_date)]
        identity_candidate_rows = (
            canonical_candidate_rows_by_identity.get(pair, [])
            if fresh_history_replay
            else candidate_rows_by_identity.get(identity_key, [])
        )

        def register_catchup_entry_authority(context: dict[str, Any]) -> None:
            signal_date = str(context.get("date") or "")[:10]
            previous_stage_date = str(context.get("previous_pattern_a_stage_date") or "")[:10]
            entry_stage = str(context.get("pattern_a_stage") or "").strip().upper()
            previous_stage = str(context.get("previous_pattern_a_stage") or "").strip().upper()
            if (
                not signal_date
                or entry_stage != "PROGRESSED"
                or previous_stage not in ALLOWED_PREVIOUS_STAGES
                or not previous_stage_date
            ):
                raise BSelectStatusError(
                    f"B_SELECT_CATCHUP_ENTRY_PATTERN_A_AUTHORITY_INVALID:{ticker}:{signal_date}"
                )
            authority_key = (
                ticker,
                identity["isu_cd"],
                identity["component_id"],
                signal_date,
            )
            authority_row = {
                "ticker": ticker,
                "isu_cd": identity["isu_cd"],
                "component_id": identity["component_id"],
                "entry_signal_date": signal_date,
                "entry_pattern_a_stage_recomputed": entry_stage,
                "previous_pattern_a_stage": previous_stage,
                "previous_pattern_a_stage_date": previous_stage_date,
                "source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS",
            }
            existing = catchup_entry_stage_authorities.get(authority_key)
            if existing is not None and existing != authority_row:
                raise BSelectStatusError(
                    f"B_SELECT_CATCHUP_ENTRY_PATTERN_A_AUTHORITY_CONFLICT:{ticker}:{signal_date}"
                )
            catchup_entry_stage_authorities[authority_key] = authority_row
            entry_context_by_signal_date[signal_date] = {
                "entry_pattern_a_stage": entry_stage,
                "entry_previous_pattern_a_stage": previous_stage,
                "entry_previous_pattern_a_stage_date": previous_stage_date,
            }

        exact_opens: dict[str, float] = {}
        initial_position: dict[str, Any] | None = None
        initial_pending: dict[str, Any] | None = None
        initial_trade_sequence = max(
            (
                int(trade.get("trade_sequence") or 0)
                for trade in ((prior_item or {}).get("trade_history") or [])
                if isinstance(trade, dict)
            ),
            default=0,
        ) if incremental_identity else 0
        if fresh_history_replay:
            identity_candidate_rows = [
                row for row in identity_candidate_rows
                if _date_text(row.get("entry_signal_date")) <= reference_market_date
            ]
            identity_signal_dates = {
                _date_text(row.get("entry_signal_date")) for row in identity_candidate_rows
            }
            identity_start_date = min(identity_signal_dates | set(fresh_month_end_dates)) \
                if identity_signal_dates or fresh_month_end_dates else reference_market_date
            observation_dates = {
                day for day in fresh_boundary_dates if day >= identity_start_date
            }
            observation_dates.update(identity_signal_dates)
            observation_dates.update(fresh_month_end_dates)
            for signal_day in identity_signal_dates | set(fresh_month_end_dates):
                execution_day = next_exact_session(signal_day, trading_dates)
                if execution_day and execution_day <= reference_market_date:
                    observation_dates.add(execution_day)
            observation_dates.add(reference_market_date)
            session_dates = sorted(observation_dates)
            if identity_signal_dates or fresh_month_end_dates:
                session_contexts = _build_exact_session_contexts(
                    root=root,
                    ticker=ticker,
                    name=name,
                    identity=identity,
                    intervals=intervals,
                    trading_dates=trading_dates,
                    session_dates=session_dates,
                    report_pattern_history=report_pattern.get("history_12m") or [],
                    repository=repo,
                    pattern_a_evaluation_dates=set(fresh_month_end_dates),
                    pattern_a_only_if_pattern_b_depressed=True,
                )
            else:
                session_contexts = [{
                    "date": reference_market_date,
                    "pattern_b_state": b_state,
                    "pattern_b_evaluation_status": pattern_b.get("evaluation_status"),
                    "pattern_a_stage": current_stage,
                    "previous_pattern_a_stage": previous_stage,
                    "previous_pattern_a_stage_date": (
                        previous_context.get("previous_pattern_a_stage_date")
                        if previous_context else None
                    ),
                }]
            if not session_contexts or session_contexts[-1]["date"] != reference_market_date:
                raise BSelectStatusError(f"B_SELECT_FRESH_HISTORY_FINAL_SESSION_MISSING:{ticker}")
            final_context = session_contexts[-1]
            if final_context["pattern_b_state"] != b_state:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_FRESH_HISTORY_FINAL_PATTERN_B_PARITY_MISMATCH:{ticker}")
            if final_context["pattern_b_evaluation_status"] != pattern_b.get("evaluation_status"):
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_FRESH_HISTORY_FINAL_PATTERN_B_STATUS_PARITY_MISMATCH:{ticker}")
            context_by_date = {str(context["date"]): context for context in session_contexts}
            for row in identity_candidate_rows:
                signal_day = _date_text(row.get("entry_signal_date"))
                context = context_by_date.get(signal_day)
                if context is None or context.get("pattern_b_state") != "DEPRESSED":
                    date_mismatch_count += 1
                    raise BSelectStatusError(
                        f"B_SELECT_FRESH_HISTORY_ENTRY_PATTERN_B_AUTHORITY_MISMATCH:{ticker}:{signal_day}"
                    )
                entry_stage = str(row.get("entry_pattern_a_stage_recomputed") or "").strip().upper()
                entry_previous_stage = str(row.get("previous_pattern_a_stage") or "").strip().upper()
                entry_previous_date = _date_text(row.get("previous_pattern_a_stage_date"))
                if not is_entry_signal("DEPRESSED", entry_stage, entry_previous_stage) or not entry_previous_date:
                    raise BSelectStatusError(
                        f"B_SELECT_FRESH_HISTORY_ENTRY_STAGE_AUTHORITY_INVALID:{ticker}:{signal_day}"
                    )
                entry_signals.append({
                    "date": signal_day,
                    "pattern_a_stage": entry_stage,
                    "previous_pattern_a_stage": entry_previous_stage,
                })
                entry_context_by_signal_date[signal_day] = {
                    "entry_pattern_a_stage": entry_stage,
                    "entry_previous_pattern_a_stage": entry_previous_stage,
                    "entry_previous_pattern_a_stage_date": entry_previous_date,
                }
            for context in session_contexts:
                signal_day = str(context["date"])
                if (
                    signal_day not in fresh_month_end_dates
                    or signal_day in identity_signal_dates
                    or not is_entry_signal(
                        context.get("pattern_b_state"),
                        context.get("pattern_a_stage") or "",
                        context.get("previous_pattern_a_stage") or "",
                    )
                ):
                    continue
                register_catchup_entry_authority(context)
                entry_signals.append({
                    "date": signal_day,
                    "pattern_a_stage": context["pattern_a_stage"],
                    "previous_pattern_a_stage": context["previous_pattern_a_stage"],
                })
            observations.extend({
                "date": str(context["date"]),
                "state": context["pattern_b_state"],
            } for context in session_contexts)
            catchup_identity_count += 1
            catchup_observation_count += len(observations)
        elif incremental_identity:
            prior_trade = prior_item.get("current_trade")
            prior_pending = prior_item.get("pending_event")
            if prior_item.get("canonical_position") == "OPEN" and isinstance(prior_trade, dict):
                initial_position = dict(prior_trade)
                initial_position.update({
                    "trade_sequence": prior_trade.get("trade_sequence"),
                    "entry_signal_date": prior_trade.get("entry_signal_date"),
                    "entry_execution_date": prior_trade.get("entry_execution_date"),
                    "entry_open": prior_trade.get("entry_open"),
                    "exit_signal_date": prior_pending.get("signal_date") if isinstance(prior_pending, dict) and prior_pending.get("kind") == "EXIT" else None,
                    "exit_execution_date": prior_pending.get("execution_date") if isinstance(prior_pending, dict) and prior_pending.get("kind") == "EXIT" else None,
                    "strategy_id": str(prior_trade.get("strategy_id") or baseline_strategy_id),
                })
                prior_entry_signal = _date_text(prior_trade.get("entry_signal_date"))
                prior_entry_context = {
                    "entry_pattern_a_stage": prior_item.get("entry_pattern_a_stage"),
                    "entry_previous_pattern_a_stage": prior_item.get("entry_previous_pattern_a_stage"),
                    "entry_previous_pattern_a_stage_date": prior_item.get("entry_previous_pattern_a_stage_date"),
                }
                if prior_entry_signal and all(prior_entry_context.values()):
                    entry_context_by_signal_date[prior_entry_signal] = prior_entry_context
            if isinstance(prior_pending, dict):
                kind = str(prior_pending.get("kind", ""))
                signal_day = str(prior_pending.get("signal_date", ""))[:10]
                execution_day = prior_pending.get("execution_date")
                if execution_day is None:
                    execution_day = next_exact_session(signal_day, trading_dates)
                initial_pending = {
                    "kind": kind,
                    "signal_date": signal_day,
                    "execution_date": str(execution_day)[:10] if execution_day else None,
                    "sequence": int((prior_trade or {}).get("trade_sequence") or 1),
                    "strategy_id": str(prior_pending.get("strategy_id") or baseline_strategy_id),
                }
            session_contexts = _build_exact_session_contexts(
                root=root,
                ticker=ticker,
                name=name,
                identity=identity,
                intervals=intervals,
                trading_dates=trading_dates,
                session_dates=catchup_session_dates,
                report_pattern_history=report_pattern.get("history_12m") or [],
                repository=repo,
            )
            if not session_contexts or session_contexts[-1]["date"] != reference_market_date:
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_SESSION_MISSING:{ticker}")
            final_context = session_contexts[-1]
            if final_context["pattern_b_state"] != b_state:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_B_PARITY_MISMATCH:{ticker}")
            if final_context["pattern_b_evaluation_status"] != pattern_b.get("evaluation_status"):
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_B_STATUS_PARITY_MISMATCH:{ticker}")
            if final_context["pattern_a_stage"] != current_stage:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_A_PARITY_MISMATCH:{ticker}")
            if final_context["previous_pattern_a_stage"] != previous_stage:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PREVIOUS_STAGE_PARITY_MISMATCH:{ticker}")
            catchup_identity_count += 1
            for context in session_contexts[:-1]:
                observations.append({"date": context["date"], "state": context["pattern_b_state"]})
                catchup_observation_count += 1
                if _is_new_entry_allowed(*pair) and context["date"] in month_end_sessions and is_entry_signal(
                    context["pattern_b_state"],
                    context["pattern_a_stage"],
                    context["previous_pattern_a_stage"],
                ):
                    previous_stage_date = context.get("previous_pattern_a_stage_date")
                    if not previous_stage_date:
                        raise BSelectStatusError(
                            f"B_SELECT_CATCHUP_ENTRY_PREVIOUS_STAGE_DATE_MISSING:{ticker}:{context['date']}"
                        )
                    register_catchup_entry_authority(context)
                    entry_signals.append({
                        "date": context["date"],
                        "pattern_a_stage": context["pattern_a_stage"],
                        "previous_pattern_a_stage": context["previous_pattern_a_stage"],
                    })
        else:
            # A newly published or re-componented V2 identity starts flat at
            # the prior V2 reference and replays only subsequent exact sessions.
            session_contexts = _build_exact_session_contexts(
                root=root,
                ticker=ticker,
                name=name,
                identity=identity,
                intervals=intervals,
                trading_dates=trading_dates,
                session_dates=catchup_session_dates,
                report_pattern_history=report_pattern.get("history_12m") or [],
                repository=repo,
            )
            if not session_contexts or session_contexts[-1]["date"] != reference_market_date:
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_SESSION_MISSING:{ticker}")
            final_context = session_contexts[-1]
            if final_context["pattern_b_state"] != b_state:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_B_PARITY_MISMATCH:{ticker}")
            if final_context["pattern_b_evaluation_status"] != pattern_b.get("evaluation_status"):
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_B_STATUS_PARITY_MISMATCH:{ticker}")
            if final_context["pattern_a_stage"] != current_stage:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PATTERN_A_PARITY_MISMATCH:{ticker}")
            if final_context["previous_pattern_a_stage"] != previous_stage:
                date_mismatch_count += 1
                raise BSelectStatusError(f"B_SELECT_CATCHUP_FINAL_PREVIOUS_STAGE_PARITY_MISMATCH:{ticker}")
            catchup_identity_count += 1
            for context in session_contexts[:-1]:
                observations.append({"date": context["date"], "state": context["pattern_b_state"]})
                catchup_observation_count += 1
                if _is_new_entry_allowed(*pair) and context["date"] in month_end_sessions and is_entry_signal(
                    context["pattern_b_state"],
                    context["pattern_a_stage"],
                    context["previous_pattern_a_stage"],
                ):
                    if not context.get("previous_pattern_a_stage_date"):
                        raise BSelectStatusError(
                            f"B_SELECT_CATCHUP_ENTRY_PREVIOUS_STAGE_DATE_MISSING:{ticker}:{context['date']}"
                        )
                    register_catchup_entry_authority(context)
                    entry_signals.append({
                        "date": context["date"],
                        "pattern_a_stage": context["pattern_a_stage"],
                        "previous_pattern_a_stage": context["previous_pattern_a_stage"],
                    })

        # Add the current official Pattern B state as an exact observation.
        # If it satisfies entry, this is a signal on the reference date and its
        # next-session fill remains pending until a later reference run.
        observations = [row for row in observations if row["date"] != reference_market_date]
        observations.append({
            "date": reference_market_date,
            "state": b_state,
        })
        if (
            not fresh_history_replay
            and _is_new_entry_allowed(*pair)
            and reference_market_date in month_end_sessions
            and is_entry_signal(b_state, current_stage, previous_stage)
        ):
            previous_stage_date = (
                previous_context.get("previous_pattern_a_stage_date")
                if previous_context else None
            )
            if not previous_stage_date:
                raise BSelectStatusError(f"B_SELECT_CURRENT_ENTRY_PREVIOUS_STAGE_DATE_MISSING:{ticker}")
            register_catchup_entry_authority({
                "date": reference_market_date,
                "pattern_a_stage": current_stage,
                "previous_pattern_a_stage": previous_stage,
                "previous_pattern_a_stage_date": previous_stage_date,
            })
            entry_signals.append({
                "date": reference_market_date,
                "pattern_a_stage": current_stage,
                "previous_pattern_a_stage": previous_stage,
                "source_entry_execution_date": None,
                "source_entry_open": None,
            })

        reference_run_entry_signal_count += sum(
            str(signal.get("date") or "")[:10] == reference_market_date
            for signal in entry_signals
        )

        # The canonical replay schedules every entry/exit at the first later
        # exact KRX session with a valid OPEN for this exact identity.
        execution_by_signal_date: dict[str, str] = {}
        signal_source = {
            (str(row.get("entry_signal_date", ""))[:10]): row
            for row in identity_candidate_rows
        }
        state_by_date = {str(row["date"]): row["state"] for row in observations}
        schedule_signal_dates = {str(signal["date"])[:10] for signal in entry_signals}
        if initial_pending and initial_pending.get("signal_date"):
            schedule_signal_dates.add(str(initial_pending["signal_date"])[:10])
        if initial_position:
            prior_reference = str(prior_status["reference_market_date"])[:10] if prior_status else ""
            schedule_signal_dates.update(
                day for day, state in state_by_date.items()
                if state == "NORMAL" and (not prior_reference or day > prior_reference)
            )
        schedule_signal_dates.update(
            day for day, state in state_by_date.items()
            if state == "NORMAL"
            and any(str(signal["date"])[:10] < day for signal in entry_signals)
        )
        if schedule_signal_dates:
            exact_opens, execution_by_signal_date = _first_valid_open_schedule(
                repository=repo,
                ticker=ticker,
                isu_cd=identity["isu_cd"],
                signal_dates=schedule_signal_dates,
                intervals=intervals,
                trading_dates=trading_dates,
                reference_market_date=reference_market_date,
            )
            if initial_pending and initial_pending.get("signal_date"):
                scheduled_pending_date = execution_by_signal_date.get(str(initial_pending["signal_date"])[:10])
                if scheduled_pending_date:
                    initial_pending["execution_date"] = scheduled_pending_date
            for signal_day, source_row in signal_source.items():
                if str(source_row.get("entry_signal_status", "")) == "FILLED":
                    saved_execution = _date_text(source_row.get("entry_execution_date"))
                    scheduled_execution = execution_by_signal_date.get(signal_day)
                    if saved_execution and scheduled_execution and saved_execution != scheduled_execution:
                        candidate_entry_execution_mismatch_rows.add((
                            ticker, identity["isu_cd"], signal_day, scheduled_execution, saved_execution,
                        ))
                exit_signal_day = _date_text(source_row.get("exit_signal_date"))
                saved_exit_execution = _date_text(source_row.get("exit_execution_date"))
                scheduled_exit_execution = execution_by_signal_date.get(exit_signal_day)
                if exit_signal_day and saved_exit_execution and scheduled_exit_execution and saved_exit_execution != scheduled_exit_execution:
                    candidate_exit_execution_mismatch_rows.add((
                        ticker, identity["isu_cd"], exit_signal_day, scheduled_exit_execution, saved_exit_execution,
                    ))
            if candidate_entry_execution_mismatch_rows or candidate_exit_execution_mismatch_rows:
                entry_mismatch = sorted(candidate_entry_execution_mismatch_rows)[0] if candidate_entry_execution_mismatch_rows else None
                exit_mismatch = sorted(candidate_exit_execution_mismatch_rows)[0] if candidate_exit_execution_mismatch_rows else None
                mismatch = entry_mismatch or exit_mismatch
                raise BSelectStatusError(
                    f"B_SELECT_FIRST_VALID_OPEN_SOURCE_PARITY_MISMATCH:{mismatch[0]}:{mismatch[2]}:"
                    f"{mismatch[3]}!={mismatch[4]}"
                )

        lifecycle = None
        if b_state is None and initial_position:
            raise BSelectStatusError(f"B_SELECT_DAILY_OPEN_POSITION_STATE_UNAVAILABLE:{ticker}")
        if b_state is None:
            data_status = "UNAVAILABLE"
            action = "NONE"
            strategy_state = "DATA_UNAVAILABLE"
            canonical_position = "NOT_APPLICABLE"
            current_trade = None
            pending_event = None
            action_reason = "PATTERN_B_UNAVAILABLE"
        else:
            try:
                lifecycle = replay_lifecycle(
                    observations,
                    entry_signals,
                    trading_dates=trading_dates,
                    exact_opens=exact_opens,
                    reference_market_date=reference_market_date,
                    execution_by_signal_date=execution_by_signal_date,
                    initial_position=initial_position,
                    initial_pending=initial_pending,
                    initial_trade_sequence=initial_trade_sequence,
                )
            except BSelectLifecycleError as exc:
                lifecycle_errors += 1
                lifecycle_error_details.append(f"{ticker}:{exc}")
                data_status = "CHECK_REQUIRED"
                action = "NONE"
                strategy_state = "CHECK_REQUIRED"
                canonical_position = "NOT_APPLICABLE"
                current_trade = None
                pending_event = None
                action_reason = str(exc)
                lifecycle = None
            if lifecycle is not None:
                data_status = "READY"
                position = lifecycle["position"]
                pending = lifecycle["pending"]
                if pending and pending.get("kind") == "ENTRY" and position is None:
                    action, strategy_state, canonical_position = "ENTER_NEXT_OPEN", "ENTRY_PENDING", "FLAT"
                    action_reason = "OFFICIAL_ENTRY_RULE_NEXT_OPEN_PENDING"
                elif pending and pending.get("kind") == "EXIT":
                    action, strategy_state, canonical_position = "EXIT", "EXIT_PENDING", "OPEN"
                    action_reason = "PATTERN_B_NORMAL_DAILY_NEXT_OPEN_PENDING"
                elif position:
                    action, strategy_state, canonical_position = "HOLD", "HOLD", "OPEN"
                    action_reason = "POSITION_OPEN_PATTERN_B_NOT_NORMAL"
                else:
                    action, strategy_state, canonical_position = "WAIT", "WAIT", "FLAT"
                    action_reason = "NO_ACTIVE_B_SELECT_SIGNAL"
                current_trade = None
                if position:
                    close = latest_close if latest_close_as_of == reference_market_date else None
                    return_pct = (close / float(position["entry_open"]) - 1.0) * 100.0 if close is not None else None
                    if close is None:
                        lifecycle_errors += 1
                        lifecycle_error_details.append(
                            f"{ticker}:LATEST_EXACT_CLOSE_UNAVAILABLE_FOR_OPEN_POSITION"
                        )
                        data_status = "CHECK_REQUIRED"
                        action = "NONE"
                        strategy_state = "CHECK_REQUIRED"
                        canonical_position = "NOT_APPLICABLE"
                        action_reason = "LATEST_EXACT_CLOSE_UNAVAILABLE_FOR_OPEN_POSITION"
                    else:
                        current_trade = {
                            "trade_sequence": position.get("trade_sequence"),
                            "entry_signal_date": position.get("entry_signal_date"),
                            "entry_execution_date": position.get("entry_execution_date"),
                            "entry_open": position.get("entry_open"),
                            "return_pct": return_pct,
                            "trade_status": "OPEN_AT_REFERENCE",
                            "strategy_id": str(position.get("strategy_id") or STRATEGY_ID),
                        }
                        for quantity_key in ("quantity", "shares", "entry_quantity"):
                            if position.get(quantity_key) is not None:
                                current_trade[quantity_key] = position[quantity_key]
                pending_event = None
                if pending:
                    pending_event = {
                        "kind": pending.get("kind"),
                        "signal_date": pending.get("signal_date"),
                        "execution_date": pending.get("execution_date"),
                        "strategy_id": str(pending.get("strategy_id") or STRATEGY_ID),
                    }
                if pending_event and pending_event.get("execution_date") and pending_event["execution_date"] <= reference_market_date:
                    future_reference_count += 1

        # Keep a per-identity execution ledger separate from the current-state
        # projection. On later daily runs, carry realized rows forward, replace
        # the prior open projection, and append any newly completed executions.
        history_lifecycle = lifecycle
        if history_lifecycle is None and b_state is None:
            try:
                history_lifecycle = replay_lifecycle(
                    observations,
                    entry_signals,
                    trading_dates=trading_dates,
                    exact_opens=exact_opens,
                    reference_market_date=reference_market_date,
                    execution_by_signal_date=execution_by_signal_date,
                    initial_position=initial_position,
                    initial_pending=initial_pending,
                    initial_trade_sequence=initial_trade_sequence,
                )
            except BSelectLifecycleError as exc:
                lifecycle_errors += 1
                lifecycle_error_details.append(f"{ticker}:HISTORY:{exc}")
                history_lifecycle = None

        prior_history = (prior_item or {}).get("trade_history") or [] if incremental_identity else []
        if any(
            not isinstance(trade, dict)
            or str(trade.get("strategy_id") or "") != STRATEGY_ID
            or trade.get("exit_strategy_id") not in {None, STRATEGY_ID}
            for trade in prior_history
        ):
            raise BSelectStatusError(f"B_SELECT_V2_BASELINE_HISTORY_LEAK:{ticker}")
        trade_history = [
            dict(trade)
            for trade in prior_history
            if trade.get("trade_status") != "OPEN_AT_REFERENCE"
        ]
        if history_lifecycle is not None:
            trade_history.extend(dict(trade) for trade in history_lifecycle["completed_trades"])
            open_position = history_lifecycle.get("position")
            if fresh_history_replay and b_state is None and open_position:
                raise BSelectStatusError(
                    f"B_SELECT_FRESH_HISTORY_OPEN_POSITION_STATE_UNAVAILABLE:{ticker}"
                )
            if open_position:
                close = latest_close if latest_close_as_of == reference_market_date else None
                entry_open = float(open_position["entry_open"])
                trade_history.append({
                    "trade_sequence": open_position.get("trade_sequence"),
                    "entry_signal_date": open_position.get("entry_signal_date"),
                    "entry_execution_date": open_position.get("entry_execution_date"),
                    "entry_open": entry_open,
                    "exit_signal_date": open_position.get("exit_signal_date"),
                    "exit_execution_date": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "trade_status": "OPEN_AT_REFERENCE",
                    "return_pct": (close / entry_open - 1.0) * 100.0 if close is not None else None,
                    "strategy_id": str(open_position.get("strategy_id") or STRATEGY_ID),
                })
                for quantity_key in ("quantity", "shares", "entry_quantity"):
                    if open_position.get(quantity_key) is not None:
                        trade_history[-1][quantity_key] = open_position[quantity_key]

        entry_context = None
        if canonical_position == "OPEN":
            if not isinstance(current_trade, dict):
                raise BSelectStatusError(f"B_SELECT_OPEN_TRADE_MISSING_FOR_ENTRY_CONTEXT:{ticker}")
            entry_signal_date = str(current_trade.get("entry_signal_date") or "")[:10]
            entry_context = entry_context_by_signal_date.get(entry_signal_date)
            if entry_context is None:
                entry_context = _entry_pattern_a_context(
                    candidate_rows,
                    ticker=ticker,
                    isu_cd=identity["isu_cd"],
                    component_id=identity["component_id"],
                    entry_signal_date=entry_signal_date,
                )
        elif action in {"ENTRY", "ENTER_NEXT_OPEN"} or (
            isinstance(pending_event, dict) and pending_event.get("kind") == "ENTRY"
        ):
            if not isinstance(pending_event, dict) or pending_event.get("kind") != "ENTRY":
                raise BSelectStatusError(f"B_SELECT_PENDING_ENTRY_EVENT_MISSING:{ticker}")
            entry_signal_date = str(pending_event.get("signal_date") or "")[:10]
            entry_context = entry_context_by_signal_date.get(entry_signal_date)
            if entry_context is None:
                entry_context = _entry_pattern_a_context(
                    candidate_rows,
                    ticker=ticker,
                    isu_cd=identity["isu_cd"],
                    component_id=identity["component_id"],
                    entry_signal_date=entry_signal_date,
                )

        item = {
            "ticker": ticker,
            "isu_cd": identity["isu_cd"],
            "name": name,
            "market": identity["market"],
            "asset_type": ASSET_TYPE,
            "action": action,
            "strategy_state": strategy_state,
            "canonical_position": canonical_position,
            "action_reason": action_reason,
            "data_status": data_status,
            "pattern_b_state": b_state,
            "pattern_a_stage": current_stage,
            "previous_pattern_a_stage": previous_stage,
            "previous_pattern_a_stage_date": previous_context.get("previous_pattern_a_stage_date") if previous_context else None,
            **(entry_context or {}),
            "current_trade": current_trade,
            "trade_history": trade_history,
            "pending_event": pending_event,
            "latest_close": latest_close,
            "latest_close_as_of": latest_close_as_of,
            "bucket": _bucket(action, data_status),
            "component_id": identity["component_id"],
            "permanent_identity_excluded": is_excluded_identity,
        }
        out_items.append(item)

    current_identity_pairs = {
        (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
        for item in out_items
    }
    canonical_trade_history: list[dict[str, Any]] = []
    for item in out_items:
        for trade in item.get("trade_history", []):
            canonical_trade_history.append({
                **dict(trade),
                "ticker": str(item.get("ticker", "")).zfill(6),
                "isu_cd": str(item.get("isu_cd", "")).upper(),
                "name": str(item.get("name") or item.get("ticker") or ""),
                "market": str(item.get("market") or ""),
                "asset_type": ASSET_TYPE,
            })

    historical_only_identity_count = 0
    historical_only_pending_events: list[dict[str, Any]] = []
    if fresh_history_replay:
        for pair, identity_rows in sorted(canonical_candidate_rows_by_identity.items()):
            if pair in current_identity_pairs:
                continue
            rows_by_component: dict[str, list[dict[str, Any]]] = {}
            for source_row in identity_rows:
                rows_by_component.setdefault(str(source_row.get("component_id", "")), []).append(source_row)
            for component_id, component_rows in sorted(rows_by_component.items()):
                ticker, isu_cd = pair
                signal_dates = sorted({_date_text(row.get("entry_signal_date")) for row in component_rows})
                interval_candidates = [
                    interval for interval in intervals
                    if str(interval.get("ticker", "")).zfill(6) == ticker
                    and str(interval.get("isu_cd", "")).upper() == isu_cd
                    and str(interval.get("state", "")).upper() == "COMMON"
                    and interval_components.get(pattern_b_source.interval_key(interval)) == component_id
                    and any(
                        str(interval.get("effective_from", ""))[:10] <= day
                        <= str(interval.get("effective_to", ""))[:10]
                        for day in signal_dates
                    )
                ]
                if not interval_candidates:
                    raise BSelectStatusError(f"B_SELECT_CANONICAL_HISTORY_INTERVAL_MISSING:{ticker}:{isu_cd}")
                last_interval = max(
                    interval_candidates,
                    key=lambda row: str(row.get("effective_to", ""))[:10],
                )
                interval_end = min(reference_market_date, str(last_interval.get("effective_to", ""))[:10])
                eligible_end_dates = [
                    day for day in trading_dates
                    if str(last_interval.get("effective_from", ""))[:10] <= day <= interval_end
                ]
                if not eligible_end_dates:
                    raise BSelectStatusError(f"B_SELECT_CANONICAL_HISTORY_INTERVAL_HAS_NO_SESSION:{ticker}:{isu_cd}")
                identity_end_date = eligible_end_dates[-1]
                active_intervals = [
                    interval for interval in intervals
                    if str(interval.get("ticker", "")).zfill(6) == ticker
                    and str(interval.get("isu_cd", "")).upper() == isu_cd
                    and str(interval.get("state", "")).upper() == "COMMON"
                    and interval_components.get(pattern_b_source.interval_key(interval)) == component_id
                    and str(interval.get("effective_from", ""))[:10] <= identity_end_date
                    <= str(interval.get("effective_to", ""))[:10]
                ]
                if len(active_intervals) != 1:
                    raise BSelectStatusError(f"B_SELECT_CANONICAL_HISTORY_ACTIVE_IDENTITY_AMBIGUOUS:{ticker}:{isu_cd}")
                active_interval = active_intervals[0]
                identity = {
                    "ticker": ticker,
                    "isu_cd": isu_cd,
                    "market": str(active_interval.get("market", "")).upper(),
                    "component_id": component_id,
                    "effective_from": str(active_interval.get("effective_from", ""))[:10],
                    "effective_to": str(active_interval.get("effective_to", ""))[:10],
                }
                start_date = min(signal_dates)
                session_dates = set(_feature_boundary_sessions(trading_dates, start_date, identity_end_date))
                session_dates.update(day for day in signal_dates if day <= identity_end_date)
                session_dates.add(identity_end_date)
                sessions = sorted(session_dates)
                if any(day < str(active_interval.get("effective_from", ""))[:10] for day in sessions):
                    sessions = [day for day in sessions if day >= str(active_interval.get("effective_from", ""))[:10]]
                contexts = _build_exact_session_contexts(
                    root=root,
                    ticker=ticker,
                    name=ticker,
                    identity=identity,
                    intervals=intervals,
                    trading_dates=trading_dates,
                    session_dates=sessions,
                    report_pattern_history=[],
                    repository=repo,
                    pattern_a_evaluation_dates=set(),
                )
                context_by_date = {str(context["date"]): context for context in contexts}
                observations = [
                    {"date": str(context["date"]), "state": context["pattern_b_state"]}
                    for context in contexts
                ]
                entry_signals: list[dict[str, Any]] = []
                for source_row in component_rows:
                    signal_day = _date_text(source_row.get("entry_signal_date"))
                    if signal_day > identity_end_date:
                        continue
                    context = context_by_date.get(signal_day)
                    if context is None or context.get("pattern_b_state") != "DEPRESSED":
                        raise BSelectStatusError(
                            f"B_SELECT_CANONICAL_HISTORY_PATTERN_B_SIGNAL_MISMATCH:{ticker}:{signal_day}"
                        )
                    entry_signals.append({
                        "date": signal_day,
                        "pattern_a_stage": str(source_row.get("entry_pattern_a_stage_recomputed") or "").upper(),
                        "previous_pattern_a_stage": str(source_row.get("previous_pattern_a_stage") or "").upper(),
                    })
                schedule_signal_dates = {str(signal["date"]) for signal in entry_signals}
                schedule_signal_dates.update(
                    str(observation["date"])
                    for observation in observations
                    if observation.get("state") == "NORMAL"
                    and any(str(signal["date"]) < str(observation["date"]) for signal in entry_signals)
                )
                exact_opens, execution_by_signal_date = _first_valid_open_schedule(
                    repository=repo,
                    ticker=ticker,
                    isu_cd=isu_cd,
                    signal_dates=schedule_signal_dates,
                    intervals=intervals,
                    trading_dates=trading_dates,
                    reference_market_date=identity_end_date,
                )
                for source_row in component_rows:
                    signal_day = _date_text(source_row.get("entry_signal_date"))
                    saved_execution = _date_text(source_row.get("entry_execution_date"))
                    scheduled_execution = execution_by_signal_date.get(signal_day)
                    if (
                        str(source_row.get("entry_signal_status", "")) == "FILLED"
                        and saved_execution and scheduled_execution
                        and saved_execution != scheduled_execution
                    ):
                        raise BSelectStatusError(
                            f"B_SELECT_FIRST_VALID_ENTRY_OPEN_PARITY_MISMATCH:{ticker}:{signal_day}:"
                            f"{saved_execution}!={scheduled_execution}"
                        )
                lifecycle = replay_lifecycle(
                    observations,
                    entry_signals,
                    trading_dates=trading_dates,
                    exact_opens=exact_opens,
                    execution_by_signal_date=execution_by_signal_date,
                    reference_market_date=identity_end_date,
                )
                trades = [dict(trade) for trade in lifecycle["completed_trades"]]
                position = lifecycle.get("position")
                if position:
                    trades.append({
                        "trade_sequence": position.get("trade_sequence"),
                        "entry_signal_date": position.get("entry_signal_date"),
                        "entry_execution_date": position.get("entry_execution_date"),
                        "entry_open": position.get("entry_open"),
                        "exit_signal_date": position.get("exit_signal_date"),
                        "exit_execution_date": None,
                        "exit_price": None,
                        "exit_reason": None,
                        "trade_status": "OPEN_AT_REFERENCE",
                        "return_pct": None,
                        "strategy_id": STRATEGY_ID,
                    })
                if trades:
                    historical_only_identity_count += 1
                for trade in trades:
                    canonical_trade_history.append({
                        **trade,
                        "ticker": ticker,
                        "isu_cd": isu_cd,
                        "name": ticker,
                        "market": identity["market"],
                        "asset_type": ASSET_TYPE,
                    })
                pending = lifecycle.get("pending")
                if pending:
                    historical_only_pending_events.append({
                        **dict(pending),
                        "ticker": ticker,
                        "isu_cd": isu_cd,
                        "strategy_id": STRATEGY_ID,
                    })

    canonical_trade_history.sort(key=lambda trade: (
        str(trade.get("entry_execution_date") or ""),
        str(trade.get("ticker", "")),
        str(trade.get("isu_cd", "")),
        int(trade.get("trade_sequence") or 0),
    ))
    canonical_current_open_positions = [
        dict(trade) for trade in canonical_trade_history
        if trade.get("trade_status") == "OPEN_AT_REFERENCE"
    ]
    canonical_history_keys: set[tuple[Any, ...]] = set()
    for trade in canonical_trade_history:
        key = (
            str(trade.get("ticker", "")).zfill(6),
            str(trade.get("isu_cd", "")).upper(),
            trade.get("trade_sequence"),
            trade.get("entry_signal_date"),
            trade.get("trade_status"),
        )
        if key in canonical_history_keys:
            raise BSelectStatusError("B_SELECT_CANONICAL_HISTORY_DUPLICATE_GLOBAL_ROW")
        canonical_history_keys.add(key)

    tickers = [item["ticker"] for item in out_items]
    duplicate_item_count = len(tickers) - len(set(tickers))
    if duplicate_item_count:
        raise BSelectStatusError("B_SELECT_DUPLICATE_OUTPUT_TICKER")
    if any(item.get("asset_type") != ASSET_TYPE for item in out_items):
        cross_contamination_count += sum(item.get("asset_type") != ASSET_TYPE for item in out_items)
        raise BSelectStatusError("B_SELECT_ASSET_SCOPE_CONTAMINATION")
    duplicate_execution_count = 0
    duplicate_trade_history_row_count = 0
    for item in out_items:
        ticker = str(item.get("ticker", "")).zfill(6)
        history_keys: set[tuple[Any, ...]] = set()
        execution_keys: set[tuple[Any, ...]] = set()
        for trade in item.get("trade_history", []):
            if not isinstance(trade, dict):
                continue
            history_key = (
                trade.get("trade_sequence"),
                trade.get("entry_signal_date"),
                trade.get("entry_execution_date"),
                trade.get("exit_signal_date"),
                trade.get("exit_execution_date"),
                trade.get("trade_status"),
            )
            if history_key in history_keys:
                duplicate_trade_history_row_count += 1
            history_keys.add(history_key)
            sequence = trade.get("trade_sequence")
            for kind, date in (
                ("ENTRY", trade.get("entry_execution_date")),
                ("EXIT", trade.get("exit_execution_date")),
            ):
                if date is None:
                    continue
                execution_key = (sequence, kind, str(date)[:10])
                if execution_key in execution_keys:
                    duplicate_execution_count += 1
                execution_keys.add(execution_key)
    if duplicate_execution_count or duplicate_trade_history_row_count:
        raise BSelectStatusError(
            "B_SELECT_CATCHUP_DUPLICATE_LEDGER_ROWS:"
            f"executions={duplicate_execution_count},history={duplicate_trade_history_row_count}"
        )
    if future_reference_count:
        raise BSelectStatusError(f"B_SELECT_CATCHUP_FUTURE_REFERENCE_EVENTS:{future_reference_count}")
    counts = {key: 0 for key in ("entry", "hold", "exit", "watch", "unavailable")}
    for item in out_items:
        counts[item["bucket"]] += 1
    status = "PASS" if lifecycle_errors == 0 and date_mismatch_count == 0 and cross_contamination_count == 0 else "CHECK_REQUIRED"
    if status != "PASS":
        raise BSelectStatusError(
            f"B_SELECT_CURRENT_STATUS_CHECK_REQUIRED:lifecycle={lifecycle_errors},dates={date_mismatch_count},"
            f"details={'|'.join(lifecycle_error_details[:5])}"
        )
    return {
        "schema_version": 1,
        "status": status,
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "scope": {
            "type": SCOPE_TYPE,
            "label": SCOPE_LABEL,
            "report_count": len(common_rows),
        },
        "count": len(out_items),
        "counts": counts,
        "items": out_items,
        "canonical_trade_history": canonical_trade_history,
        "canonical_pending_events": historical_only_pending_events,
        "canonical_trade_history_row_count": len(canonical_trade_history),
        "canonical_current_open_positions": canonical_current_open_positions,
        "canonical_current_open_position_count": len(canonical_current_open_positions),
        "historical_only_identity_count": historical_only_identity_count,
        "network_requests": 0,
        "evaluation_error_count": lifecycle_errors,
        "permanent_identity_exclusion_count": permanent_exclusion_count,
        "permanent_identity_excluded_item_count": excluded_items,
        "permanent_identity_excluded_common_item_count": excluded_identity_scope_count,
        "current_v1_source_row_count": 0,
        "reference_run_entry_signal_count": reference_run_entry_signal_count,
        "historical_candidate_signal_count": historical_candidate_signal_count,
        "candidate_entry_execution_mismatch_count": len(candidate_entry_execution_mismatch_rows),
        "candidate_entry_execution_mismatches": [
            {
                "ticker": ticker,
                "isu_cd": isu_cd,
                "signal_date": signal_date,
                "next_exact_krx_session": expected_date,
                "saved_execution_date": saved_date,
                "disposition": "EXCLUDED_FROM_EXACT_NEXT_SESSION_REPLAY",
            }
            for ticker, isu_cd, signal_date, expected_date, saved_date
            in sorted(candidate_entry_execution_mismatch_rows)
        ],
        "candidate_exit_execution_mismatch_count": len(candidate_exit_execution_mismatch_rows),
        "candidate_exit_execution_mismatches": [
            {
                "ticker": ticker,
                "isu_cd": isu_cd,
                "signal_date": signal_date,
                "next_exact_krx_session": expected_date,
                "saved_execution_date": saved_date,
            }
            for ticker, isu_cd, signal_date, expected_date, saved_date
            in sorted(candidate_exit_execution_mismatch_rows)
        ],
        "historical_execution_authority_status": (
            "CHECK_REQUIRED"
            if candidate_entry_execution_mismatch_rows or candidate_exit_execution_mismatch_rows
            else "PASS"
        ),
        "date_mismatch_count": date_mismatch_count,
        "future_reference_count": future_reference_count,
        "duplicate_item_count": duplicate_item_count,
        "cross_strategy_contamination_count": cross_contamination_count,
        "catchup_audit": {
            "replay_mode": (
                "V2_CANONICAL_FULL_HISTORY_REPLAY"
                if fresh_history_replay
                else "INCREMENTAL_DAILY_V2_CATCHUP"
            ),
            "prior_artifact_path": prior_artifact_path,
            "prior_reference_market_date": (
                str(prior_status.get("reference_market_date"))[:10] if prior_status else None
            ),
            "catchup_from": (
                str(prior_status.get("reference_market_date"))[:10] if prior_status else None
            ),
            "catchup_to": reference_market_date if prior_status else None,
            "catchup_session_count": len(catchup_session_dates),
            "catchup_session_dates": catchup_session_dates,
            "recovered_month_end_dates": [
                day
                for day in sorted(month_end_sessions)
                if day < reference_market_date
                and day > sample_authority_frontier
            ],
            "catchup_identity_count": catchup_identity_count,
            "catchup_session_replay_count": catchup_identity_count * len(catchup_session_dates),
            "catchup_intermediate_observation_count": catchup_observation_count,
            "skipped_krx_session_count": 0,
            "future_reference_count": future_reference_count,
            "duplicate_execution_count": duplicate_execution_count,
            "duplicate_trade_history_row_count": duplicate_trade_history_row_count,
            "exact_open_missing_count": exact_open_missing_count,
            "lifecycle_error_count": lifecycle_errors,
            "date_mismatch_count": date_mismatch_count,
        },
        "canonical_history": (
            {
                "status": "FRESH_REPLAY",
                "start_date": fresh_history_start_date,
                "end_date": reference_market_date,
                "exact_session_count": len(fresh_exact_sessions),
                "entry_candidate_signal_count": historical_candidate_signal_count,
                "new_month_end_signal_dates": fresh_month_end_dates,
                "sample_authority_frontier": sample_authority_frontier,
                "current_v1_source_row_count": 0,
                "trade_history_row_count": len(canonical_trade_history),
                "current_open_position_count": len(canonical_current_open_positions),
                "historical_only_identity_count": historical_only_identity_count,
            }
            if fresh_history_replay
            else None
        ),
        "catchup_entry_pattern_a_authorities": [
            catchup_entry_stage_authorities[key]
            for key in sorted(catchup_entry_stage_authorities)
        ],
        "calendar_authority": _calendar_authority_payload(calendar_provenance),
        "source_authorities": {
            "pattern_b_monthly_states": str(MONTHLY_SAMPLE_REL),
            "pattern_a_stage_history": str(STAGE_HISTORY_REL),
            "current_status_source": "PUBLISHED_COMMON_STOCK_REPORTS",
            "catchup_status_source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS",
            "lifecycle_mode": "MONTH_END_ENTRY_DAILY_NORMAL_EXIT_WITH_EXACT_SESSION_CATCHUP",
            "signal_cadence": "MONTH_END_ENTRY_DAILY_NORMAL_EXIT",
            "month_end_signal_date_count": len(month_end_sessions),
        },
    }


def write_b_select_status(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True)
    parser.add_argument("--reference-market-date", required=True)
    parser.add_argument("--index", type=Path, default=ROOT / "web/data/stock-index.json")
    parser.add_argument("--stocks", type=Path, default=ROOT / "web/data/stocks")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fresh-history-replay",
        action="store_true",
        help="reconstruct the 2026-10-03 V2 canonical history without a prior status seed",
    )
    args = parser.parse_args(argv)
    output = args.output or ROOT / STATUS_RELATIVE / args.target_as_of.replace("-", "") / "status.json"
    payload = build_b_select_status(
        repo_root=ROOT,
        index_path=args.index,
        stocks_path=args.stocks,
        target_as_of=args.target_as_of,
        reference_market_date=args.reference_market_date,
        fresh_history_replay=args.fresh_history_replay,
    )
    write_b_select_status(payload, output)
    print(json.dumps({
        "status": payload["status"],
        "strategy_id": payload["strategy_id"],
        "requested_as_of": payload["requested_as_of"],
        "reference_market_date": payload["reference_market_date"],
        "count": payload["count"],
        "counts": payload["counts"],
        "evaluation_error_count": payload["evaluation_error_count"],
        "network_requests": payload["network_requests"],
        "output": str(output),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
