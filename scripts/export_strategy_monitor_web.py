#!/usr/bin/env python3
"""Project published strategy authority into the static monitor JSON.

The exporter does not run a strategy, calculate signals or indicators, perform
a backtest, or call an external provider. It derives display-only Select Core
holding age and causal peak drawdown from Repository V2 prices plus the exact
rolling KRX calendar and PIT identity authority.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from trend_scanner.strategies.b_select_core_fundamental_status import (
    FUNDAMENTAL_STATUSES,
    item_status_asof,
    resolve_statuses,
    status_key,
    status_keys,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "web/data/stock-index.json"
STOCKS_PATH = ROOT / "web/data/stocks"
OUTPUT_PATH = ROOT / "web/data/strategy-monitor.json"
ENTRY_STAGE_HISTORY_REL = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/"
    "candidate_signal_stage_history.csv"
)
ENTRY_STAGE_HISTORY_METADATA_REL = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/metadata.json"
)
ALLOWED_ENTRY_PREVIOUS_STAGES = {"EARLY_TREND", "TRANSITION"}
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
STRATEGY_LABEL = "A FAST Core V2"
B_SELECT_ID = "PATTERN_B_SELECT_CORE_V02"
B_SELECT_LABEL = "B Select Core V2"
LEGACY_B_SELECT_ID = "PATTERN_B_SELECT_CORE_V01"
JULIA_ID = "JULIA_ETF_STRATEGY_V01"
JULIA_LABEL = "Julia V1"
DEFAULT_STRATEGY_ID = STRATEGY_ID


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _date_set(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value)[:10] for value in values if value is not None}


def _select_core_history_path_metrics(
    repo_root: Path,
    trades: list[dict[str, Any]],
    items: list[dict[str, Any]],
    reference_market_date: str,
) -> list[dict[str, Any]]:
    """Add display-only exact-session age and causal peak drawdown to B history.

    REALIZED drawdown is evaluated on its exit signal session; OPEN_AT_REFERENCE
    drawdown is evaluated on the reference session. The evaluation session's
    HIGH is never included in the prior peak. Price rows come from Repository V2
    and are accepted only when the rolling KRX calendar, PIT identity, and
    session-projection audit cover the complete interval.
    """
    result = [
        {**trade, "holding_age_sessions": None, "peak_drawdown_pct": None}
        for trade in trades
    ]
    if not result:
        return result

    rolling_dir = repo_root / "data/market/rolling_authority"
    required_authority = (
        rolling_dir / "manifest.json",
        rolling_dir / "merged_pit_intervals.json",
        rolling_dir / "merged_trading_calendar.json",
    )
    if not all(path.is_file() for path in required_authority):
        return result

    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
    from trend_scanner.data.errors import MarketDataError
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2
    from trend_scanner.data.rolling_market_data_refresh import (
        load_rolling_authority,
        validate_merged_authority_coherence,
    )

    manifest = load_rolling_authority(rolling_dir)
    pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, rolling_dir)
    calendar = load_rolling_production_market_calendar(repo_root)
    if calendar is None:
        return result

    calendar_dates = [value.strftime("%Y-%m-%d") for value in calendar.trading_dates]
    if (
        calendar_dates != calendar_payload.get("trading_dates")
        or not calendar_dates
        or calendar_dates[-1] != manifest.merged_calendar_frontier
        or pit_payload.get("pit_frontier", "") < reference_market_date
        or manifest.merged_calendar_frontier < reference_market_date
    ):
        raise ValueError("B Select history display authority does not cover the reference market date")
    calendar_positions = {day: index for index, day in enumerate(calendar_dates)}
    if reference_market_date not in calendar_positions:
        return result

    intervals_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for raw in pit_payload.get("intervals", []):
        if str(raw.get("state", "")).upper() != "COMMON":
            continue
        ticker = str(raw.get("ticker", "")).strip().zfill(6)
        interval = {
            **raw,
            "ticker": ticker,
            "isu_cd": str(raw.get("isu_cd", "")).strip().upper(),
            "effective_from": str(raw.get("effective_from", ""))[:10],
            "effective_to": str(raw.get("effective_to", ""))[:10],
        }
        intervals_by_ticker.setdefault(ticker, []).append(interval)

    items_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        key = (str(item.get("ticker", "")).strip().zfill(6), str(item.get("isu_cd", "")).strip().upper())
        items_by_identity.setdefault(key, []).append(item)

    try:
        repository = build_production_repository_v2(repo_root, end=reference_market_date)
    except (FileNotFoundError, OSError):
        repository = None
    blocking_projection_keys = (
        "unexplained_adjusted_only_dates",
        "rejected_raw_only_dates",
        "known_adjusted_gap_dates",
        "outside_identity_lifecycle_dates",
        "adjusted_source_nonusable_dates",
        "adjusted_analytic_invalid_dates",
        "shared_placeholder_conflict_dates",
    )

    def exact_identity_sessions(ticker: str, isu_cd: str, sessions: list[str]) -> bool:
        for day in sessions:
            active = [
                interval
                for interval in intervals_by_ticker.get(ticker, [])
                if interval["effective_from"] <= day <= interval["effective_to"]
            ]
            if len(active) != 1 or active[0]["isu_cd"] != isu_cd:
                return False
        return bool(sessions)

    def query_frame(ticker: str, start: str, end: str) -> Any:
        if repository is None:
            return None
        try:
            return repository.get_daily(ticker, start, end)
        except (FileNotFoundError, MarketDataError, OSError):
            return None

    def frame_covers(frame: Any, required_sessions: list[str], requested_sessions: list[str]) -> bool:
        if frame is None or frame.empty or "high" not in frame.columns or "low" not in frame.columns:
            return False
        projection = frame.attrs.get("session_projection_audit", {})
        frame_rows = {value.strftime("%Y-%m-%d"): frame.loc[value] for value in frame.index}
        frame_dates = set(frame_rows)
        required = set(required_sessions)
        if (
            not required.issubset(frame_dates)
            or not frame_dates.issubset(set(requested_sessions))
            or projection.get("projected_date_set_exact_match") is not True
            or int(projection.get("silent_inner_drop_count", 0) or 0) != 0
            or not required.issubset(_date_set(projection.get("adjusted_dates")))
            or not required.issubset(_date_set(projection.get("raw_dates")))
            or any(required & _date_set(projection.get(key)) for key in blocking_projection_keys)
        ):
            return False
        return all(
            _finite_positive(frame_rows[day].get("high")) is not None
            and _finite_positive(frame_rows[day].get("low")) is not None
            for day in required_sessions
        )

    # Session age is based only on the exact rolling KRX calendar and PIT
    # identity. Price availability is independently required for drawdown.
    eligible_for_prices: list[tuple[int, str, str, str, str, float | None]] = []
    for index, trade in enumerate(result):
        ticker = str(trade.get("ticker", "")).strip().zfill(6)
        isu_cd = str(trade.get("isu_cd", "")).strip().upper()
        entry_date = str(trade.get("entry_execution_date", ""))[:10]
        realized = trade.get("trade_status") == "REALIZED"
        age_end = str(trade.get("exit_execution_date", ""))[:10] if realized else reference_market_date
        evaluation_date = str(trade.get("exit_signal_date", ""))[:10] if realized else reference_market_date
        entry_price = _finite_positive(trade.get("entry_price"))
        if (
            not isu_cd or entry_date not in calendar_positions or age_end not in calendar_positions
            or evaluation_date not in calendar_positions or entry_date > age_end
            or entry_date > evaluation_date or evaluation_date > reference_market_date
        ):
            continue

        age_sessions = calendar_dates[calendar_positions[entry_date] : calendar_positions[age_end] + 1]
        if (
            age_sessions
            and age_sessions[0] == entry_date
            and age_sessions[-1] == age_end
            and exact_identity_sessions(ticker, isu_cd, age_sessions)
        ):
            trade["holding_age_sessions"] = len(age_sessions)

        price_sessions = calendar_dates[
            calendar_positions[entry_date] : calendar_positions[evaluation_date] + 1
        ]
        if (
            price_sessions
            and price_sessions[0] == entry_date
            and price_sessions[-1] == evaluation_date
            and exact_identity_sessions(ticker, isu_cd, price_sessions)
        ):
            eligible_for_prices.append((index, ticker, isu_cd, entry_date, evaluation_date, entry_price))

    # One Repository V2 read per exact ticker range covers repeated trades;
    # if a broad ticker range has an unrelated projection anomaly, retry only
    # each requested trade interval, never substituting a neighboring session.
    by_ticker: dict[str, list[tuple[int, str, str, str, str, float | None]]] = {}
    for entry in eligible_for_prices:
        by_ticker.setdefault(entry[1], []).append(entry)

    for ticker, rows in by_ticker.items():
        broad_start = min(row[3] for row in rows)
        broad_end = max(row[4] for row in rows)
        broad_sessions = calendar_dates[
            calendar_positions[broad_start] : calendar_positions[broad_end] + 1
        ]
        shared_frame = query_frame(ticker, broad_start, broad_end)
        for index, row_ticker, isu_cd, entry_date, evaluation_date, entry_price in rows:
            start_index = calendar_positions[entry_date]
            end_index = calendar_positions[evaluation_date]
            sessions = calendar_dates[start_index : end_index + 1]
            frame = shared_frame
            if not frame_covers(frame, sessions, broad_sessions):
                frame = query_frame(ticker, entry_date, evaluation_date)
                frame_sessions = calendar_dates[start_index : end_index + 1]
                if not frame_covers(frame, sessions, frame_sessions):
                    continue
            frame_rows = {value.strftime("%Y-%m-%d"): frame.loc[value] for value in frame.index}
            entry_open = _finite_positive(frame_rows[entry_date].get("open"))
            if (
                entry_price is None or entry_open is None
                or not math.isclose(entry_open, entry_price, rel_tol=1e-10, abs_tol=1e-7)
            ):
                continue
            if evaluation_date == entry_date:
                # Same-session price ordering is unknowable without lookahead.
                continue
            prior_sessions = sessions[:-1]
            highs = [_finite_positive(frame_rows[day].get("high")) for day in prior_sessions]
            evaluation_low = _finite_positive(frame_rows[evaluation_date].get("low"))
            if evaluation_low is None or not highs or any(value is None for value in highs):
                continue
            peak_high = max(value for value in highs if value is not None)
            drawdown_pct = (evaluation_low / peak_high - 1.0) * 100.0
            result[index]["peak_drawdown_pct"] = 0.0 if abs(drawdown_pct) <= 1e-10 else drawdown_pct

            if result[index].get("trade_status") == "OPEN_AT_REFERENCE":
                published_items = items_by_identity.get((row_ticker, isu_cd), [])
                if len(published_items) > 1:
                    raise ValueError(f"B Select holding display item identity is ambiguous: {row_ticker} {isu_cd}")
                if published_items:
                    source_item = published_items[0]
                    source_close = _finite_positive(source_item.get("latest_close"))
                    source_date = str(source_item.get("latest_close_as_of", ""))[:10]
                    reference_close = _finite_positive(frame_rows[evaluation_date].get("close"))
                    if (
                        source_close is not None and source_date == reference_market_date
                        and reference_close is not None
                        and not math.isclose(source_close, reference_close, rel_tol=1e-10, abs_tol=1e-7)
                    ):
                        raise ValueError(f"B Select holding reference close parity mismatch: {row_ticker} {isu_cd}")

    # Current open positions are canonical strategy rows, including identities
    # that no longer have a published stock report. Resolve their display-only
    # current price from the same exact-session Repository V2 authority rather
    # than relying on a report file to exist. Keep these fields off trade_history
    # below: this is a current-position projection, not a ledger rewrite.
    if repository is not None:
        for index, trade in enumerate(result):
            if trade.get("trade_status") != "OPEN_AT_REFERENCE":
                continue
            ticker = str(trade.get("ticker", "")).strip().zfill(6)
            isu_cd = str(trade.get("isu_cd", "")).strip().upper()
            entry_date = str(trade.get("entry_execution_date", ""))[:10]
            if not exact_identity_sessions(ticker, isu_cd, [entry_date, reference_market_date]):
                continue

            entry_frame = query_frame(ticker, entry_date, entry_date)
            current_frame = query_frame(
                ticker, reference_market_date, reference_market_date
            )
            if (
                not frame_covers(entry_frame, [entry_date], [entry_date])
                or not frame_covers(
                    current_frame,
                    [reference_market_date],
                    [reference_market_date],
                )
            ):
                continue

            entry_rows = {
                value.strftime("%Y-%m-%d"): entry_frame.loc[value]
                for value in entry_frame.index
            }
            current_rows = {
                value.strftime("%Y-%m-%d"): current_frame.loc[value]
                for value in current_frame.index
            }
            entry_open = _finite_positive(entry_rows[entry_date].get("open"))
            reference_close = _finite_positive(
                current_rows[reference_market_date].get("close")
            )
            entry_price = _finite_positive(trade.get("entry_price"))
            if reference_close is None:
                continue
            if (
                entry_price is None
                or entry_open is None
                or not math.isclose(
                    entry_open, entry_price, rel_tol=1e-10, abs_tol=1e-7
                )
            ):
                continue

            published_items = items_by_identity.get((ticker, isu_cd), [])
            if len(published_items) > 1:
                raise ValueError(
                    f"B Select holding display item identity is ambiguous: {ticker} {isu_cd}"
                )
            if published_items:
                source_item = published_items[0]
                source_close = _finite_positive(source_item.get("latest_close"))
                source_date = str(source_item.get("latest_close_as_of", ""))[:10]
                if (
                    source_close is not None
                    and source_date == reference_market_date
                    and not math.isclose(
                        source_close, reference_close, rel_tol=1e-10, abs_tol=1e-7
                    )
                ):
                    raise ValueError(
                        f"B Select holding reference close parity mismatch: {ticker} {isu_cd}"
                    )

            trade["latest_close"] = reference_close
            trade["latest_close_as_of"] = reference_market_date
            trade["current_return_pct"] = (
                reference_close / entry_price - 1.0
            ) * 100.0

    return result


def _read_entry_stage_authority(repo_root: Path) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    path = repo_root / ENTRY_STAGE_HISTORY_REL
    metadata_path = repo_root / ENTRY_STAGE_HISTORY_METADATA_REL
    metadata = _read_json(metadata_path)
    expected_hash = (
        metadata.get("generated_files", {})
        .get(ENTRY_STAGE_HISTORY_REL.name, {})
        .get("sha256")
    )
    if not path.is_file() or not expected_hash:
        raise ValueError("B Select entry Pattern A authority is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise ValueError("B Select entry Pattern A authority hash mismatch")
    authority: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (
                str(row.get("ticker", "")).zfill(6),
                str(row.get("isu_cd", "")).upper(),
                str(row.get("component_id", "")),
                str(row.get("entry_signal_date", ""))[:10],
            )
            authority.setdefault(key, []).append(row)
    return authority


def _read_catchup_entry_stage_authority(
    b_select_status: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[tuple[str, str, str, str], dict[str, str]]:
    """Read exact-session Pattern A lineage emitted by the B Select replay."""
    audit = b_select_status.get("catchup_audit") or {}
    if not isinstance(audit, dict):
        raise ValueError("B Select catch-up audit is invalid")
    session_dates = audit.get("catchup_session_dates") or []
    recovered_month_end_dates = audit.get("recovered_month_end_dates") or []
    if not isinstance(session_dates, list):
        raise ValueError("B Select catch-up session dates are invalid")
    if not isinstance(recovered_month_end_dates, list):
        raise ValueError("B Select recovered month-end dates are invalid")
    if (
        int(audit.get("catchup_session_count", len(session_dates))) != len(session_dates)
        or int(audit.get("skipped_krx_session_count", 0)) != 0
        or session_dates != sorted(set(session_dates))
        or recovered_month_end_dates != sorted(set(recovered_month_end_dates))
    ):
        raise ValueError("B Select catch-up session audit is inconsistent")
    authorized_signal_dates = set(session_dates) | set(recovered_month_end_dates)

    rows = b_select_status.get("catchup_entry_pattern_a_authorities") or []
    if not isinstance(rows, list):
        raise ValueError("B Select catch-up entry Pattern A authority is invalid")
    authority: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("B Select catch-up entry Pattern A authority row is invalid")
        row = {key: str(raw.get(key) or "").strip() for key in (
            "ticker",
            "isu_cd",
            "component_id",
            "entry_signal_date",
            "entry_pattern_a_stage_recomputed",
            "previous_pattern_a_stage",
            "previous_pattern_a_stage_date",
            "source",
        )}
        row["ticker"] = row["ticker"].zfill(6)
        row["isu_cd"] = row["isu_cd"].upper()
        row["entry_signal_date"] = row["entry_signal_date"][:10]
        row["entry_pattern_a_stage_recomputed"] = row["entry_pattern_a_stage_recomputed"].upper()
        row["previous_pattern_a_stage"] = row["previous_pattern_a_stage"].upper()
        row["previous_pattern_a_stage_date"] = row["previous_pattern_a_stage_date"][:10]
        key = (
            row["ticker"],
            row["isu_cd"],
            row["component_id"],
            row["entry_signal_date"],
        )
        if (
            not row["isu_cd"]
            or not row["component_id"]
            or row["entry_signal_date"] not in authorized_signal_dates
            or row["entry_pattern_a_stage_recomputed"] != "PROGRESSED"
            or row["previous_pattern_a_stage"] not in ALLOWED_ENTRY_PREVIOUS_STAGES
            or not row["previous_pattern_a_stage_date"]
            or row["previous_pattern_a_stage_date"] > row["entry_signal_date"]
            or row["source"] != "REPOSITORY_V2_EXACT_SESSION_EVALUATORS"
            or key in authority
        ):
            raise ValueError(
                f"B Select catch-up entry Pattern A authority is inconsistent: {key[0]} {key[3]}"
            )
        authority[key] = row

    return authority


def _validate_b_select_entry_contexts(
    items: list[dict[str, Any]],
    authority: dict[tuple[str, str, str, str], list[dict[str, str]]],
    *,
    catchup_authority: dict[tuple[str, str, str, str], dict[str, str]] | None = None,
) -> None:
    fields = (
        "entry_pattern_a_stage",
        "entry_previous_pattern_a_stage",
        "entry_previous_pattern_a_stage_date",
    )
    for item in items:
        is_open = item.get("canonical_position") == "OPEN"
        pending = item.get("pending_event")
        is_pending_entry = (
            item.get("action") in {"ENTRY", "ENTER_NEXT_OPEN"}
            or (isinstance(pending, dict) and pending.get("kind") == "ENTRY")
        )
        has_context = any(item.get(field) is not None for field in fields)
        if not is_open and not is_pending_entry:
            if has_context:
                raise ValueError(f"B Select non-entry item has fake entry Pattern A context: {item.get('ticker')}")
            continue

        if is_open:
            trade = item.get("current_trade")
            if not isinstance(trade, dict):
                raise ValueError(f"B Select OPEN item has no current trade: {item.get('ticker')}")
            entry_signal_date = str(trade.get("entry_signal_date") or "")[:10]
        else:
            if not isinstance(pending, dict) or pending.get("kind") != "ENTRY":
                raise ValueError(f"B Select pending entry item has no ENTRY event: {item.get('ticker')}")
            entry_signal_date = str(pending.get("signal_date") or "")[:10]

        key = (
            str(item.get("ticker", "")).zfill(6),
            str(item.get("isu_cd", "")).upper(),
            str(item.get("component_id", "")),
            entry_signal_date,
        )
        matches = authority.get(key, [])
        catchup_source = (catchup_authority or {}).get(key)
        if len(matches) > 1 or (len(matches) == 0 and catchup_source is None):
            raise ValueError(
                f"B Select entry Pattern A authority match count is not one: {key[0]} {entry_signal_date}"
            )
        source = matches[0] if matches else catchup_source
        if source is None:
            raise ValueError(
                f"B Select entry Pattern A authority match count is not one: {key[0]} {entry_signal_date}"
            )
        expected = {
            "entry_pattern_a_stage": str(source.get("entry_pattern_a_stage_recomputed", "")).strip().upper(),
            "entry_previous_pattern_a_stage": str(source.get("previous_pattern_a_stage", "")).strip().upper(),
            "entry_previous_pattern_a_stage_date": str(source.get("previous_pattern_a_stage_date", ""))[:10],
        }
        if catchup_source is not None:
            catchup_expected = {
                "entry_pattern_a_stage": catchup_source["entry_pattern_a_stage_recomputed"],
                "entry_previous_pattern_a_stage": catchup_source["previous_pattern_a_stage"],
                "entry_previous_pattern_a_stage_date": catchup_source["previous_pattern_a_stage_date"],
            }
            if expected != catchup_expected:
                raise ValueError(
                    f"B Select entry Pattern A exact catch-up authority mismatch: {key[0]} {entry_signal_date}"
                )
        if (
            expected["entry_pattern_a_stage"] != "PROGRESSED"
            or expected["entry_previous_pattern_a_stage"] not in ALLOWED_ENTRY_PREVIOUS_STAGES
            or not expected["entry_previous_pattern_a_stage_date"]
            or any(item.get(field) != expected[field] for field in fields)
        ):
            raise ValueError(f"B Select entry Pattern A context does not match authority: {key[0]} {entry_signal_date}")


def _trade_projection(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_sequence": trade.get("trade_sequence"),
        "entry_execution_date": trade.get("entry_execution_date"),
        "entry_open": trade.get("entry_open"),
        "return_pct": trade.get("return_pct"),
        "trade_status": trade.get("trade_status"),
    }


def _first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _normalize_trade(
    strategy_id: str,
    trade: dict[str, Any],
    *,
    ticker: str,
    name: str,
    market: str,
    asset_type: str,
) -> dict[str, Any]:
    """Normalize an authoritative source trade without recalculating it."""
    sequence = _first_value(trade, "trade_sequence", "sequence")
    entry_date = _first_value(trade, "entry_execution_date", "entry_date")
    entry_price = _first_value(trade, "entry_open", "entry_open_krw", "entry_price")
    exit_date = _first_value(trade, "exit_execution_date", "exit_date")
    exit_price = _first_value(trade, "exit_price", "exit_price_krw")
    return_pct = _first_value(trade, "return_pct", "terminal_return_pct")
    trade_status = trade.get("trade_status")
    if not sequence or not entry_date or entry_price is None or not trade_status:
        raise ValueError(f"incomplete {strategy_id} trade source: {ticker}")
    try:
        entry_price = float(entry_price)
        exit_price = float(exit_price) if exit_price is not None else None
        return_pct = float(return_pct) if return_pct is not None else None
        sequence = int(sequence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {strategy_id} trade source value: {ticker}") from exc
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise ValueError(f"invalid {strategy_id} entry price: {ticker}")
    if exit_price is not None and (not math.isfinite(exit_price) or exit_price <= 0):
        raise ValueError(f"invalid {strategy_id} exit price: {ticker}")
    if return_pct is not None and not math.isfinite(return_pct):
        raise ValueError(f"invalid {strategy_id} return: {ticker}")
    entry_execution_date = str(entry_date)[:10]
    exit_execution_date = str(exit_date)[:10] if exit_date else None
    if trade_status == "REALIZED" and (not exit_execution_date or exit_price is None or return_pct is None):
        raise ValueError(f"incomplete realized {strategy_id} trade: {ticker}")
    exit_reason = None
    if exit_execution_date:
        exit_reason = _first_value(trade, "exit_type", "exit_reason")
    return {
        "strategy_id": str(trade.get("strategy_id") or strategy_id),
        "exit_strategy_id": (
            str(trade.get("exit_strategy_id"))
            if trade.get("exit_strategy_id") is not None
            else None
        ),
        "ticker": ticker,
        "name": name,
        "market": market,
        "asset_type": asset_type,
        "trade_sequence": sequence,
        "entry_signal_date": str(trade.get("entry_signal_date") or "")[:10] or None,
        "entry_execution_date": entry_execution_date,
        "entry_price": entry_price,
        "exit_signal_date": str(trade.get("exit_signal_date") or "")[:10] or None,
        "exit_execution_date": exit_execution_date,
        "exit_price": exit_price,
        "return_pct": return_pct,
        "trade_status": str(trade_status),
        "exit_reason": str(exit_reason) if exit_reason is not None else None,
    }


def _validate_history_identities(
    strategy_id: str,
    trades: list[dict[str, Any]],
    *,
    allowed_source_ids: set[str] | None = None,
) -> None:
    allowed_source_ids = allowed_source_ids or {strategy_id}
    for trade in trades:
        source_id = str(trade.get("strategy_id") or strategy_id)
        if source_id not in allowed_source_ids:
            raise ValueError(f"unexpected {strategy_id} history source strategy: {source_id}")
    identities = [
        (
            str(trade.get("strategy_id") or strategy_id),
            trade["ticker"],
            trade["trade_sequence"],
            trade["entry_execution_date"],
        )
        for trade in trades
    ]
    if len(identities) != len(set(identities)):
        raise ValueError(f"duplicate {strategy_id} trade identity")


def _item_bucket(item: dict[str, Any]) -> str:
    if item["data_status"] != "READY" or item["canonical_position"] == "NOT_APPLICABLE":
        return "unavailable"
    action = item["action"]
    if action in {"ENTRY", "ENTER_NEXT_OPEN"}:
        return "entry"
    if action == "HOLD":
        return "hold"
    if action in {"EXIT", "EXIT_NEXT_OPEN"}:
        return "exit"
    if action in {"WATCH", "WAIT"}:
        return "watch"
    return "unavailable"


def _project_item(index_item: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    identity = report.get("identity") or {}
    decision = report.get("decision") or {}
    strategy = report.get("strategy") or {}
    technical = report.get("technical_details") or {}
    pattern = report.get("pattern") or {}
    price = report.get("price_trend") or {}
    availability = report.get("availability") or {}

    ticker = str(index_item.get("ticker") or "").upper()
    if identity.get("ticker") != ticker:
        raise ValueError(f"strategy monitor ticker mismatch: {ticker}")
    for index_key, report_key in (("name", "name"), ("market", "market"), ("asset_type", "asset_type")):
        if index_item.get(index_key) != identity.get(report_key):
            raise ValueError(f"strategy monitor identity mismatch: {ticker} {index_key}")

    action = decision.get("action")
    strategy_action = strategy.get("action")
    if action != strategy_action:
        raise ValueError(f"strategy action mismatch: {ticker}")
    strategy_state = decision.get("strategy_state")
    if strategy_state != strategy.get("state"):
        raise ValueError(f"strategy state mismatch: {ticker}")
    canonical_position = decision.get("canonical_position")
    if canonical_position != strategy.get("position"):
        raise ValueError(f"canonical position mismatch: {ticker}")

    data_status = "READY"
    current_trade: dict[str, Any] | None = None
    history = strategy.get("history") or []
    open_trades = [
        trade for trade in history
        if isinstance(trade, dict) and trade.get("trade_status") == "OPEN_AT_CUTOFF"
    ]
    if canonical_position == "OPEN":
        if len(open_trades) != 1:
            data_status = "CHECK_REQUIRED"
        else:
            current_trade = _trade_projection(open_trades[0])
    elif open_trades:
        data_status = "CHECK_REQUIRED"
    elif canonical_position == "NOT_APPLICABLE":
        data_status = "NOT_APPLICABLE"
    elif canonical_position not in {"FLAT", "OPEN"}:
        data_status = "CHECK_REQUIRED"
    if not action or not strategy_state or not canonical_position:
        data_status = "CHECK_REQUIRED"

    item = {
        "ticker": ticker,
        "name": identity.get("name"),
        "market": identity.get("market"),
        "asset_type": identity.get("asset_type"),
        "sector_name": technical.get("sector_name"),
        "action": action,
        "strategy_state": strategy_state,
        "canonical_position": canonical_position,
        "pattern_stage": pattern.get("official_stage"),
        "pattern_score": pattern.get("score"),
        "latest_close": price.get("latest_close"),
        "latest_close_as_of": price.get("latest_close_as_of"),
        "report_status": availability.get("report_status") or technical.get("report_status"),
        "data_status": data_status,
        "current_trade": current_trade,
    }
    item["bucket"] = _item_bucket(item)
    return item


def build_strategy_monitor(
    repo_root: Path = ROOT,
    *,
    index_path: Path | None = None,
    stocks_path: Path | None = None,
    target_as_of: str | None = None,
    reference_market_date: str | None = None,
    b_select_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``index_path``/``stocks_path``(선택, PHASE4C_MANDATORY_ANALYSIS_DISPLAY_V01)를
    명시하면 ``web/data/`` 대신 그 exact-target 소스를 읽는다. 생략하면 기존과
    완전히 동일하게 ``repo_root/web/data/``를 읽는다(하위 호환). ``target_as_of``/
    ``reference_market_date``를 명시하면 published report의 requested_as_of/
    reference_market_date가 그 값과 정확히 일치하는지 fail-closed로 검증한다
    (생략 시 기존처럼 mixed일 경우 "MIXED"로만 표시하고 raise하지 않는다).
    """
    index_path = index_path if index_path is not None else repo_root / "web/data/stock-index.json"
    stocks_path = stocks_path if stocks_path is not None else repo_root / "web/data/stocks"
    index = _read_json(index_path)
    index_items = index.get("items") or []
    available = [item for item in index_items if item.get("report_available") is True]
    available.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("ticker") or "")))
    if index.get("available_report_count") != len(available):
        raise ValueError("stock index available report count mismatch")

    expected_tickers = {str(item.get("ticker") or "").upper() for item in available}
    report_paths = {path.stem for path in stocks_path.glob("*.json")}
    if report_paths != expected_tickers:
        raise ValueError("published stock report files do not match stock index")

    common_items: list[dict[str, Any]] = []
    etf_items: list[dict[str, Any]] = []
    fast_history: list[dict[str, Any]] = []
    julia_history: list[dict[str, Any]] = []
    as_of_values: set[str] = set()
    reference_market_date_values: set[str] = set()
    for index_item in available:
        ticker = str(index_item.get("ticker") or "").upper()
        report = _read_json(stocks_path / f"{ticker}.json")
        technical = report.get("technical_details") or {}
        as_of = str(technical.get("requested_as_of") or "")[:10]
        ref = str(technical.get("reference_market_date") or "")[:10]
        if as_of:
            as_of_values.add(as_of)
        if ref:
            reference_market_date_values.add(ref)
        if index_item.get("asset_type") == "COMMON":
            common_items.append(_project_item(index_item, report))
            for trade in (report.get("strategy") or {}).get("history") or []:
                if not isinstance(trade, dict):
                    raise ValueError(f"invalid A FAST trade history row: {ticker}")
                fast_history.append(_normalize_trade(
                    STRATEGY_ID,
                    trade,
                    ticker=ticker,
                    name=str(index_item.get("name") or ticker),
                    market=str(index_item.get("market") or ""),
                    asset_type="COMMON",
                ))
        elif index_item.get("asset_type") == "ETF":
            strategy = report.get("strategy") or {}
            if (
                strategy.get("source") != "official_strategy"
                or strategy.get("strategy_id") != JULIA_ID
                or strategy.get("strategy_name") != JULIA_LABEL
            ):
                raise ValueError(f"Julia source strategy mismatch: {ticker}")
            etf_items.append(_project_item(index_item, report))
            for trade in strategy.get("history") or []:
                if not isinstance(trade, dict):
                    raise ValueError(f"invalid Julia trade history row: {ticker}")
                julia_history.append(_normalize_trade(
                    JULIA_ID,
                    trade,
                    ticker=ticker,
                    name=str(index_item.get("name") or ticker),
                    market=str(index_item.get("market") or ""),
                    asset_type="ETF",
                ))

    if target_as_of is not None and as_of_values != {target_as_of}:
        raise ValueError(
            f"strategy monitor requested_as_of mismatch: expected {target_as_of!r}, got {sorted(as_of_values)}"
        )
    if reference_market_date is not None and reference_market_date_values != {reference_market_date}:
        raise ValueError(
            f"strategy monitor reference_market_date mismatch: expected {reference_market_date!r}, "
            f"got {sorted(reference_market_date_values)}"
        )

    resolved_as_of = (
        target_as_of if target_as_of is not None
        else (next(iter(as_of_values)) if len(as_of_values) == 1 else "MIXED")
    )
    resolved_reference = (
        reference_market_date if reference_market_date is not None
        else (next(iter(reference_market_date_values)) if len(reference_market_date_values) == 1 else "MIXED")
    )

    if b_select_status is None:
        b_select_path = repo_root / "artifacts/strategies/b_select_core_v2/production" / resolved_as_of.replace("-", "") / "status.json"
        if not b_select_path.is_file():
            raise ValueError("B Select current status artifact is missing")
        b_select_status = _read_json(b_select_path)
    b_select_strategy_id = str(b_select_status.get("strategy_id") or "")
    b_select_label = (
        "B Select Core V2" if b_select_strategy_id == B_SELECT_ID
        else "B Select Core V1" if b_select_strategy_id == LEGACY_B_SELECT_ID
        else ""
    )
    expected_strategy_id = B_SELECT_ID if resolved_reference >= "2026-10-02" else LEGACY_B_SELECT_ID
    expected_source_ids = {expected_strategy_id}
    if (
        b_select_status.get("status") != "PASS"
        or b_select_strategy_id != expected_strategy_id
        or b_select_status.get("requested_as_of") != resolved_as_of
        or b_select_status.get("reference_market_date") != resolved_reference
        or (b_select_status.get("scope") or {}).get("type") != "PUBLISHED_COMMON_REPORTS"
    ):
        raise ValueError("B Select current status is invalid or date-mismatched")
    b_items = b_select_status.get("items")
    if not isinstance(b_items, list):
        raise ValueError("B Select current status items are invalid")
    common_tickers = {item["ticker"] for item in common_items}
    if {str(item.get("ticker", "")).zfill(6) for item in b_items} != common_tickers:
        raise ValueError("B Select current status COMMON scope does not match published reports")
    _validate_b_select_entry_contexts(
        b_items,
        _read_entry_stage_authority(repo_root),
        catchup_authority=_read_catchup_entry_stage_authority(b_select_status, repo_root=repo_root),
    )
    b_counts = b_select_status.get("counts") or {}
    expected_bucket_counts = {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0}
    for item in b_items:
        if item.get("asset_type") != "COMMON" or item.get("bucket") not in expected_bucket_counts:
            raise ValueError("B Select current status item contract is invalid")
        expected_bucket_counts[item["bucket"]] += 1
    if (
        b_select_status.get("count") != len(b_items)
        or (b_select_status.get("scope") or {}).get("report_count") != len(b_items)
        or b_counts != expected_bucket_counts
        or any(
            b_select_status.get(key) != 0
            for key in (
                "network_requests",
                "evaluation_error_count",
                "date_mismatch_count",
                "future_reference_count",
                "duplicate_item_count",
                "cross_strategy_contamination_count",
            )
        )
    ):
        raise ValueError("B Select current status diagnostics or counts are invalid")
    if len(etf_items) != 36:
        raise ValueError(f"Official ETF 36 report count mismatch: {len(etf_items)}")

    # Display-only historical PIT fundamental status (entry_signal_date for a
    # trade/position, requested_as_of for an item without a signal). One value
    # per key is shared by the list, its filter, the trade history and the stock
    # report card; it never changes B Select Core V2 signals or buckets.
    b_history_source = b_select_status.get("canonical_trade_history")
    if b_history_source is None:
        b_history_source = [
            {**trade, "ticker": item.get("ticker"), "isu_cd": item.get("isu_cd"),
             "name": item.get("name"), "market": item.get("market")}
            for item in b_items
            for trade in item.get("trade_history", [])
        ]
    if not isinstance(b_history_source, list):
        raise ValueError("B Select canonical trade history is invalid")
    index_names = {
        str(item.get("ticker", "")).zfill(6): str(item.get("name") or item.get("ticker") or "")
        for item in index.get("items", [])
        if isinstance(item, dict)
    }
    fundamental_keys = status_keys(b_items, resolved_as_of)
    for trade in b_history_source:
        if not isinstance(trade, dict):
            raise ValueError("invalid B Select canonical trade history row")
        if trade.get("entry_signal_date"):
            fundamental_keys.setdefault(
                status_key(trade.get("ticker"), trade.get("isu_cd"), trade["entry_signal_date"]),
                "ENTRY_SIGNAL_DATE",
            )
    fundamental = resolve_statuses(fundamental_keys, repo_root)

    def fundamental_for(ticker: Any, isu_cd: Any, asof: Any) -> str:
        status = fundamental[status_key(ticker, isu_cd, asof)]["fundamental_status"]
        if status not in FUNDAMENTAL_STATUSES:
            raise ValueError(f"invalid B Select fundamental status: {ticker} {asof}")
        return status

    b_history: list[dict[str, Any]] = []
    for trade in b_history_source:
        normalized = _normalize_trade(
            b_select_strategy_id,
            trade,
            ticker=str(trade.get("ticker") or "").zfill(6),
            name=(
                index_names.get(str(trade.get("ticker", "")).zfill(6), str(trade.get("ticker") or ""))
                if not trade.get("name") or str(trade.get("name")) == str(trade.get("ticker"))
                else str(trade.get("name"))
            ),
            market=str(trade.get("market") or ""),
            asset_type="COMMON",
        )
        normalized["fundamental_status"] = fundamental_for(
            trade.get("ticker"), trade.get("isu_cd"), trade.get("entry_signal_date")
        )
        normalized["isu_cd"] = str(trade.get("isu_cd") or "").upper()
        b_history.append(normalized)
    _validate_history_identities(STRATEGY_ID, fast_history)
    _validate_history_identities(
        b_select_strategy_id,
        b_history,
        allowed_source_ids=expected_source_ids,
    )
    _validate_history_identities(JULIA_ID, julia_history)
    b_current_items = [
        {key: value for key, value in item.items() if key != "trade_history"}
        for item in b_items
    ]
    for item in b_current_items:
        asof, _ = item_status_asof(item, resolved_as_of)
        item["fundamental_status"] = fundamental_for(item.get("ticker"), item.get("isu_cd"), asof)

    def counts_for(items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0}
        for item in items:
            bucket = item.get("bucket")
            if bucket not in counts:
                raise ValueError(f"unknown strategy item bucket: {bucket!r}")
            counts[bucket] += 1
        return counts

    b_history = _select_core_history_path_metrics(
        repo_root,
        b_history,
        b_current_items,
        resolved_reference,
    )
    b_canonical_open_positions = [
        trade for trade in b_history
        if trade.get("trade_status") == "OPEN_AT_REFERENCE"
    ]
    incomplete_open_prices = [
        (trade.get("ticker"), trade.get("isu_cd"))
        for trade in b_canonical_open_positions
        if (
            _finite_positive(trade.get("latest_close")) is None
            or str(trade.get("latest_close_as_of", ""))[:10] != resolved_reference
            or trade.get("current_return_pct") is None
            or not math.isfinite(float(trade.get("current_return_pct")))
            or not isinstance(trade.get("holding_age_sessions"), int)
            or trade.get("holding_age_sessions", 0) < 1
        )
    ]
    if incomplete_open_prices:
        raise ValueError(
            "B Select canonical OPEN current Repository V2 price is incomplete: "
            f"{incomplete_open_prices[:10]}"
        )
    open_position_display_fields = {
        "latest_close",
        "latest_close_as_of",
        "current_return_pct",
    }
    b_history_payload = [
        {
            key: value
            for key, value in trade.items()
            if key not in open_position_display_fields
        }
        for trade in b_history
    ]
    if (
        b_select_status.get("canonical_current_open_position_count") is not None
        and b_select_status.get("canonical_current_open_position_count") != len(b_canonical_open_positions)
    ):
        raise ValueError("B Select canonical current OPEN count mismatch")
    strategies = [
        {
            "id": STRATEGY_ID,
            "label": STRATEGY_LABEL,
            "asset_scope": "COMMON",
            "scope": {
                "type": "PUBLISHED_COMMON_REPORTS",
                "label": "현재 공개 COMMON 리포트 기준",
                "report_count": len(common_items),
            },
            "counts": counts_for(common_items),
            "items": common_items,
            "trade_history": fast_history,
        },
        {
            "id": b_select_strategy_id,
            "label": b_select_label,
            "asset_scope": "COMMON",
            "scope": {
                "type": "PUBLISHED_COMMON_REPORTS",
                "label": "현재 공개 COMMON 리포트 기준",
                "report_count": len(b_items),
            },
            "counts": dict(b_select_status.get("counts") or {}),
            "items": b_current_items,
            "trade_history": b_history_payload,
            "canonical_current_open_positions": b_canonical_open_positions,
            "canonical_current_open_position_count": len(b_canonical_open_positions),
        },
        {
            "id": JULIA_ID,
            "label": JULIA_LABEL,
            "asset_scope": "OFFICIAL_ETF_36",
            "scope": {
                "type": "OFFICIAL_ETF_36",
                "label": "Official ETF 36 기준",
                "report_count": len(etf_items),
            },
            "counts": counts_for(etf_items),
            "items": etf_items,
            "trade_history": julia_history,
        },
    ]
    for strategy in strategies:
        if len(strategy["items"]) != strategy["scope"]["report_count"]:
            raise ValueError(f"strategy monitor scope count mismatch: {strategy['id']}")

    return {
        "schema_version": 2,
        "source": {
            "type": "PUBLISHED_STOCK_REPORTS",
            "path": "web/data/stocks/*.json",
        },
        "default_strategy_id": DEFAULT_STRATEGY_ID,
        "requested_as_of": resolved_as_of,
        "reference_market_date": resolved_reference,
        "as_of": resolved_as_of,
        "strategies": strategies,
    }


def export_strategy_monitor(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    payload = build_strategy_monitor()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    payload = export_strategy_monitor(args.output)
    print(json.dumps({
        "as_of": payload["as_of"],
        "strategies": [
            {"id": strategy["id"], "scope_count": strategy["scope"]["report_count"], "counts": strategy["counts"]}
            for strategy in payload["strategies"]
        ],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
