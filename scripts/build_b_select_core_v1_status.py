#!/usr/bin/env python3
"""Build exact-date B Select Core V1 current status for Phase 4D.

The runner replays the already-sealed B Select candidate event authority against
the exact monthly Pattern B observation authority, then appends the current
published report observation. It emits current lifecycle state only: no new
backtest, portfolio simulation, performance metric, network request, or order.
"""

from __future__ import annotations

import argparse
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
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.strategies.b_select_core_v1 import (
    BSelectLifecycleError,
    STRATEGY_ID,
    STRATEGY_NAME,
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
STATUS_RELATIVE = Path("artifacts/strategies/b_select_core_v1/production")
ASSET_TYPE = "COMMON"
SCOPE_TYPE = "PUBLISHED_COMMON_REPORTS"
SCOPE_LABEL = "현재 공개 COMMON 리포트 기준"
ALLOWED_PREVIOUS_STAGES = frozenset({"EARLY_TREND", "TRANSITION"})


class BSelectStatusError(RuntimeError):
    """The B Select current status cannot be produced without ambiguity."""


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


def _latest_prior_status(root: Path, reference_market_date: str, trading_dates: list[str]) -> dict[str, Any] | None:
    candidates = []
    for path in (root / STATUS_RELATIVE).glob("*/status.json"):
        try:
            value = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        prior_reference = str(value.get("reference_market_date", ""))[:10]
        if value.get("strategy_id") == STRATEGY_ID and value.get("status") == "PASS" and prior_reference < reference_market_date:
            candidates.append((prior_reference, str(value.get("requested_as_of", ""))[:10], value))
    if not candidates:
        return None
    prior_reference, _, value = max(candidates, key=lambda item: (item[0], item[1]))
    try:
        previous_index = trading_dates.index(prior_reference)
        current_index = trading_dates.index(reference_market_date)
    except ValueError as exc:
        raise BSelectStatusError("B_SELECT_PRIOR_STATUS_DATE_NOT_IN_KRX_CALENDAR") from exc
    if current_index != previous_index + 1:
        raise BSelectStatusError("B_SELECT_PRIOR_STATUS_SESSION_GAP")
    return value


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
) -> dict[str, Any]:
    root = Path(repo_root)
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
    interval_components, _ = pattern_b_source._interval_components(intervals, trading_dates)
    identity_by_ticker = _current_identity_map(intervals, interval_components, reference_market_date)
    sample_frame, permanent_exclusion_count = _load_monthly_states(
        root,
        intervals,
        interval_components,
        trading_dates,
    )
    candidate_rows = _load_candidate_signals(root)
    candidate_rows = _rebind_candidate_components(
        candidate_rows,
        intervals,
        interval_components,
        set(identity_by_ticker),
    )
    prior_status = _latest_prior_status(root, reference_market_date, trading_dates)
    # The first history-aware build must replay the complete sealed authority
    # instead of starting from a legacy current-state snapshot with no ledger.
    if prior_status and any(
        not isinstance(item.get("trade_history"), list)
        for item in prior_status.get("items", [])
        if isinstance(item, dict)
    ):
        prior_status = None
    prior_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    if prior_status:
        for item in prior_status.get("items", []):
            if isinstance(item, dict):
                prior_by_identity[(str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())] = item

    repo = build_production_repository_v2(root, end=reference_market_date)
    out_items: list[dict[str, Any]] = []
    lifecycle_errors = 0
    date_mismatch_count = 0
    future_reference_count = 0
    duplicate_item_count = 0
    cross_contamination_count = 0
    excluded_items = 0

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
        if (ticker, identity["isu_cd"]) in PERMANENT_IDENTITY_EXCLUSIONS:
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

        prior_item = prior_by_identity.get(pair)
        observations: list[dict[str, Any]] = []
        entry_signals: list[dict[str, Any]] = []
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
        )
        if prior_item and prior_item.get("component_id") == identity["component_id"]:
            prior_ref = str(prior_status["reference_market_date"])[:10]
            observations.append({"date": prior_ref, "state": prior_item.get("pattern_b_state")})
            prior_trade = prior_item.get("current_trade")
            prior_pending = prior_item.get("pending_event")
            if prior_item.get("canonical_position") == "OPEN" and isinstance(prior_trade, dict):
                initial_position = {
                    "trade_sequence": prior_trade.get("trade_sequence"),
                    "entry_signal_date": prior_trade.get("entry_signal_date"),
                    "entry_execution_date": prior_trade.get("entry_execution_date"),
                    "entry_open": prior_trade.get("entry_open"),
                    "exit_signal_date": prior_pending.get("signal_date") if isinstance(prior_pending, dict) and prior_pending.get("kind") == "EXIT" else None,
                    "exit_execution_date": prior_pending.get("execution_date") if isinstance(prior_pending, dict) and prior_pending.get("kind") == "EXIT" else None,
                }
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
                }
                if kind == "ENTRY":
                    entry_signals.append({
                        "date": signal_day,
                        "pattern_a_stage": prior_item.get("pattern_a_stage"),
                        "previous_pattern_a_stage": prior_item.get("previous_pattern_a_stage"),
                    })
        else:
            sample_rows = sample_frame.loc[
                sample_frame["ticker"].astype(str).str.zfill(6).eq(ticker)
                & sample_frame["isu_cd"].astype(str).str.upper().eq(identity["isu_cd"])
                & sample_frame["component_id"].astype(str).eq(identity["component_id"])
                & sample_frame["snapshot_date"].astype(str).le(reference_market_date),
                ["snapshot_date", "state"],
            ]
            observations.extend(
                {"date": str(row.snapshot_date)[:10], "state": str(row.state)}
                for row in sample_rows.sort_values("snapshot_date").itertuples(index=False)
            )
            for row in candidate_rows:
                if (
                    str(row.get("ticker", "")).zfill(6) == ticker
                    and str(row.get("isu_cd", "")).upper() == identity["isu_cd"]
                    and str(row.get("component_id", "")) == identity["component_id"]
                    and str(row.get("previous_pattern_a_stage", "")) in ALLOWED_PREVIOUS_STAGES
                    and str(row.get("entry_pattern_a_stage_recomputed", "")) == "PROGRESSED"
                    and str(row.get("entry_signal_status", "")) in {"FILLED", "SUPPRESSED_ALREADY_HOLDING"}
                ):
                    entry_signals.append({
                        "date": str(row.get("entry_signal_date", ""))[:10],
                        "pattern_a_stage": "PROGRESSED",
                        "previous_pattern_a_stage": str(row["previous_pattern_a_stage"]),
                        "source_entry_execution_date": str(row.get("entry_execution_date", ""))[:10] or None,
                        "source_entry_open": _safe_float(row.get("entry_reference_open")),
                    })

        # Add the current official Pattern B state as an exact observation.
        # If it satisfies entry, this is a signal on the reference date and its
        # next-session fill remains pending until a later reference run.
        observations = [row for row in observations if row["date"] != reference_market_date]
        observations.append({"date": reference_market_date, "state": b_state})
        if is_entry_signal(b_state, current_stage, previous_stage):
            if prior_item and prior_item.get("action") == "ENTER_NEXT_OPEN":
                pass
            else:
                entry_signals.append({
                    "date": reference_market_date,
                    "pattern_a_stage": current_stage,
                    "previous_pattern_a_stage": previous_stage,
                    "source_entry_execution_date": None,
                    "source_entry_open": None,
                })

        # Candidate rows already carry exact historic next-open dates/prices.
        # Cross-check the dates against the authoritative KRX calendar, then
        # read those exact execution dates through Repository V2 for the replay.
        required_open_dates: set[str] = set()
        signal_source = {
            (str(row.get("entry_signal_date", ""))[:10]): row
            for row in candidate_rows
            if str(row.get("ticker", "")).zfill(6) == ticker
            and str(row.get("isu_cd", "")).upper() == identity["isu_cd"]
            and str(row.get("component_id", "")) == identity["component_id"]
        }
        for signal in entry_signals:
            signal_day = str(signal["date"])
            execution_day = next_exact_session(signal_day, trading_dates)
            if execution_day and execution_day <= reference_market_date:
                required_open_dates.add(execution_day)
            if signal_day in signal_source:
                source_row = signal_source[signal_day]
                source_execution = str(source_row.get("entry_execution_date", ""))[:10]
                if source_execution and execution_day != source_execution:
                    raise BSelectStatusError(f"B_SELECT_ENTRY_NEXT_SESSION_MISMATCH:{ticker}:{signal_day}")
        state_by_date = {str(row["date"]): row["state"] for row in observations}
        for signal in entry_signals:
            signal_day = str(signal["date"])
            normal_dates = [
                day for day, state in sorted(state_by_date.items())
                if day > signal_day and state == "NORMAL"
            ]
            if normal_dates:
                exit_day = next_exact_session(normal_dates[0], trading_dates)
                if exit_day and exit_day <= reference_market_date:
                    required_open_dates.add(exit_day)

        if initial_pending and initial_pending.get("execution_date") and initial_pending["execution_date"] <= reference_market_date:
            required_open_dates.add(str(initial_pending["execution_date"]))
        if required_open_dates:
            loader = RepositoryV2DailyLoader(
                repo,
                start=min(required_open_dates),
                end=reference_market_date,
            )
            daily = loader.load(ticker)
            if daily is None or daily.empty:
                raise BSelectStatusError(f"B_SELECT_EXACT_EXECUTION_DATA_MISSING:{ticker}")
            for day in required_open_dates:
                if day not in daily.index or day not in trading_dates:
                    raise BSelectStatusError(f"B_SELECT_EXACT_NEXT_OPEN_MISSING:{ticker}:{day}")
                interval_match = any(
                    str(row.get("ticker", "")).zfill(6) == ticker
                    and str(row.get("isu_cd", "")).upper() == identity["isu_cd"]
                    and str(row.get("state", "")).upper() == "COMMON"
                    and str(row.get("effective_from", ""))[:10] <= day <= str(row.get("effective_to", ""))[:10]
                    for row in intervals
                )
                if not interval_match:
                    raise BSelectStatusError(f"B_SELECT_EXECUTION_IDENTITY_MISMATCH:{ticker}:{day}")
                price = _safe_float(daily.loc[pd.Timestamp(day), "open"])
                if price is None or price <= 0:
                    raise BSelectStatusError(f"B_SELECT_EXACT_NEXT_OPEN_INVALID:{ticker}:{day}")
                exact_opens[day] = price

        lifecycle = None
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
                    initial_position=initial_position,
                    initial_pending=initial_pending,
                    initial_trade_sequence=initial_trade_sequence,
                )
            except BSelectLifecycleError as exc:
                lifecycle_errors += 1
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
                elif position and b_state == "NORMAL":
                    action, strategy_state, canonical_position = "EXIT", "EXIT_PENDING", "OPEN"
                    action_reason = "PATTERN_B_NORMAL_NEXT_OPEN_PENDING"
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
                        }
                pending_event = None
                if pending:
                    pending_event = {
                        "kind": pending.get("kind"),
                        "signal_date": pending.get("signal_date"),
                        "execution_date": pending.get("execution_date"),
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
                    initial_position=initial_position,
                    initial_pending=initial_pending,
                    initial_trade_sequence=initial_trade_sequence,
                )
            except BSelectLifecycleError:
                lifecycle_errors += 1
                history_lifecycle = None

        prior_history = (prior_item or {}).get("trade_history") or []
        trade_history = [
            dict(trade) for trade in prior_history
            if isinstance(trade, dict) and trade.get("trade_status") != "OPEN_AT_REFERENCE"
        ]
        if history_lifecycle is not None:
            trade_history.extend(dict(trade) for trade in history_lifecycle["completed_trades"])
            open_position = history_lifecycle.get("position")
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
                })

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
            "current_trade": current_trade,
            "trade_history": trade_history,
            "pending_event": pending_event,
            "latest_close": latest_close,
            "latest_close_as_of": latest_close_as_of,
            "bucket": _bucket(action, data_status),
            "component_id": identity["component_id"],
        }
        out_items.append(item)

    tickers = [item["ticker"] for item in out_items]
    duplicate_item_count = len(tickers) - len(set(tickers))
    if duplicate_item_count:
        raise BSelectStatusError("B_SELECT_DUPLICATE_OUTPUT_TICKER")
    if any(item.get("asset_type") != ASSET_TYPE for item in out_items):
        cross_contamination_count += sum(item.get("asset_type") != ASSET_TYPE for item in out_items)
        raise BSelectStatusError("B_SELECT_ASSET_SCOPE_CONTAMINATION")
    counts = {key: 0 for key in ("entry", "hold", "exit", "watch", "unavailable")}
    for item in out_items:
        counts[item["bucket"]] += 1
    status = "PASS" if lifecycle_errors == 0 and date_mismatch_count == 0 and cross_contamination_count == 0 else "CHECK_REQUIRED"
    if status != "PASS":
        raise BSelectStatusError(
            f"B_SELECT_CURRENT_STATUS_CHECK_REQUIRED:lifecycle={lifecycle_errors},dates={date_mismatch_count}"
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
        "network_requests": 0,
        "evaluation_error_count": lifecycle_errors,
        "permanent_identity_exclusion_count": excluded_items,
        "historical_candidate_signal_count": sum(
            1 for row in candidate_rows
            if str(row.get("previous_pattern_a_stage", "")) in ALLOWED_PREVIOUS_STAGES
            and str(row.get("entry_pattern_a_stage_recomputed", "")) == "PROGRESSED"
        ),
        "date_mismatch_count": date_mismatch_count,
        "future_reference_count": future_reference_count,
        "duplicate_item_count": duplicate_item_count,
        "cross_strategy_contamination_count": cross_contamination_count,
        "calendar_authority": _calendar_authority_payload(calendar_provenance),
        "source_authorities": {
            "pattern_b_monthly_states": str(MONTHLY_SAMPLE_REL),
            "pattern_a_stage_history": str(STAGE_HISTORY_REL),
            "current_status_source": "PUBLISHED_COMMON_STOCK_REPORTS",
            "lifecycle_mode": "PER_IDENTITY_CURRENT_STATE_REPLAY",
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
    args = parser.parse_args(argv)
    output = args.output or ROOT / STATUS_RELATIVE / args.target_as_of.replace("-", "") / "status.json"
    payload = build_b_select_status(
        repo_root=ROOT,
        index_path=args.index,
        stocks_path=args.stocks,
        target_as_of=args.target_as_of,
        reference_market_date=args.reference_market_date,
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
