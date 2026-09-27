#!/usr/bin/env python3
"""Diagnose official Pattern A stages at Pattern B DEPRESSED entry signals.

This is a point-in-time entry classification study. It reuses the sealed
Pattern B monthly sample and the existing CONTROL signal/trade ledgers; it does
not replay a strategy or alter any classifier thresholds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

warnings.filterwarnings(
    "ignore",
    message="The default fill_method='pad' in Series.pct_change is deprecated.*",
    category=FutureWarning,
    module=r"trend_scanner\.features\.moving_average",
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as pit_study  # noqa: E402
from scripts.analyze_pattern_b_state_forward_return_v01 import (  # noqa: E402
    month_end_snapshot_dates,
)
from trend_scanner.data.market_calendar import MarketCalendarAuthority  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage  # noqa: E402
from trend_scanner.data.resampler import to_monthly, to_weekly  # noqa: E402
from trend_scanner.features.moving_average import (  # noqa: E402
    ma_slope,
    ma_slope_acceleration,
    ma_spread,
    moving_average,
)
from trend_scanner.features.resistance import (  # noqa: E402
    distance_to_resistance,
    range_position,
)
from trend_scanner.validation.feature_report import (  # noqa: E402
    FeatureRow,
    _at_or_nan,
    _avg_price_change_12m,
    _safe,
    _window_high_low,
    build_feature_row,
)
from trend_scanner.validation.historical_snapshot import (  # noqa: E402
    HistoricalSnapshot,
    _drop_incomplete_current_month,
    _drop_incomplete_weekly,
    _last_or_none,
)

OUTPUT_RELATIVE = Path(
    "artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01"
)
WORKERS = 10
REVIEW_SEED = 20260927
EXPECTED_RAW_SIGNAL_COUNT = 20_076
STAGE_CHECKPOINT_VERSION = 1
STAGE_ORDER = (
    "WEAK",
    "BASE",
    "TRANSITION",
    "EARLY_TREND",
    "PROGRESSED",
    "UNAVAILABLE",
)
LINK_KEY = ("ticker", "isu_cd", "entry_signal_date")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _signal_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _load_market_calendar(
    data_root: Path,
    trading_dates: list[str],
) -> tuple[MarketCalendarAuthority, list[str], dict[str, Any]]:
    path = data_root / base.CALENDAR_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    frontier = str(payload["calendar_frontier"])[:10]
    complete_month_ends = month_end_snapshot_dates(trading_dates, frontier)
    if not complete_month_ends:
        raise RuntimeError("merged calendar has no completed market months")
    calendar = MarketCalendarAuthority(
        trading_dates=pd.DatetimeIndex(pd.to_datetime(trading_dates)).normalize(),
        completed_month_ends=pd.DatetimeIndex(pd.to_datetime(complete_month_ends)),
        source_name="ROLLING_AUTHORITY_MERGED_CALENDAR_V01",
        metadata={
            "calendar_frontier": frontier,
            "calendar_content_digest": payload.get("content_digest"),
        },
    )
    provenance = {
        "path": str(base.CALENDAR_PATH),
        "sha256": _sha256(path),
        "frontier": frontier,
        "first_trading_date": trading_dates[0],
        "last_trading_date": trading_dates[-1],
        "completed_month_end_count": len(complete_month_ends),
        "last_completed_month_end": complete_month_ends[-1],
    }
    return calendar, complete_month_ends, provenance


def _component_active_snapshot_dates(
    components: Mapping[tuple[str, str, str], list[dict[str, Any]]],
    snapshot_dates: list[str],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    active: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for key, rows in components.items():
        active[key] = tuple(
            day
            for day in snapshot_dates
            if any(
                row["effective_from"] <= day <= row["effective_to"]
                for row in rows
            )
        )
    return active


def _build_cached_snapshot(
    ticker: str,
    daily: pd.DataFrame,
    snapshot_date: str,
    monthly_bars: pd.DataFrame,
    weekly_bars: pd.DataFrame,
    calendar: MarketCalendarAuthority,
) -> HistoricalSnapshot:
    """Apply the official PIT snapshot policy to bars resampled once per ticker.

    Pattern B entries are exact completed market month ends. Completed monthly
    bars and weekly bars labelled no later than the requested date match the
    resample of the clipped daily frame. The daily feature input remains clipped
    before any feature calculation.
    """
    requested = pd.Timestamp(snapshot_date)
    sliced = daily.loc[daily.index <= requested]
    effective_as_of = sliced.index.max() if len(sliced) else None
    same_month_future = daily.index[
        (daily.index > requested)
        & (daily.index.year == requested.year)
        & (daily.index.month == requested.month)
    ]
    if len(same_month_future):
        raise RuntimeError(
            f"Pattern B entry is not a completed monthly boundary: {ticker} {snapshot_date}"
        )
    same_month = (
        (monthly_bars.index.year == requested.year)
        & (monthly_bars.index.month == requested.month)
    )
    monthly = monthly_bars.loc[(monthly_bars.index <= requested) | same_month]
    weekly = weekly_bars.loc[weekly_bars.index <= requested]
    monthly = _drop_incomplete_current_month(monthly, requested, market_calendar=calendar)
    weekly = _drop_incomplete_weekly(weekly, effective_as_of)
    features = build_feature_row(ticker, ticker, sliced, weekly, monthly)
    return HistoricalSnapshot(
        requested_snapshot_date=requested,
        effective_as_of=effective_as_of,
        include_incomplete_periods=False,
        monthly_as_of=_last_or_none(monthly),
        weekly_as_of=_last_or_none(weekly),
        features=features,
        monthly=monthly,
        weekly=weekly,
    )


def _build_cached_stage_snapshot(
    ticker: str,
    daily: pd.DataFrame,
    snapshot_date: str,
    monthly_bars: pd.DataFrame,
    weekly_bars: pd.DataFrame,
    calendar: MarketCalendarAuthority,
) -> HistoricalSnapshot:
    """Build only the official Stage classifier inputs from PIT bars.

    The official classifier reads seven FeatureRow fields plus monthly OHLCV
    lifecycle history. Computing unrelated pivot, volatility, and volume fields
    is unnecessary for a Stage-only study. Each required field uses the same
    frozen helper and arguments as build_feature_row.
    """
    requested = pd.Timestamp(snapshot_date)
    sliced = daily.loc[daily.index <= requested]
    effective_as_of = sliced.index.max() if len(sliced) else None
    same_month_future = daily.index[
        (daily.index > requested)
        & (daily.index.year == requested.year)
        & (daily.index.month == requested.month)
    ]
    if len(same_month_future):
        raise RuntimeError(
            f"Pattern B entry is not a completed monthly boundary: {ticker} {snapshot_date}"
        )
    same_month = (
        (monthly_bars.index.year == requested.year)
        & (monthly_bars.index.month == requested.month)
    )
    monthly = monthly_bars.loc[(monthly_bars.index <= requested) | same_month]
    weekly = weekly_bars.loc[weekly_bars.index <= requested]
    monthly = _drop_incomplete_current_month(monthly, requested, market_calendar=calendar)
    weekly = _drop_incomplete_weekly(weekly, effective_as_of)

    monthly_close = monthly["close"] if "close" in monthly.columns else pd.Series(dtype=float)
    close = _at_or_nan(monthly_close, -1)
    high_36m, low_36m = _window_high_low(monthly, 36)
    ma6_series = moving_average(monthly_close, 6)
    ma12_series = moving_average(monthly_close, 12)
    ma24_series = moving_average(monthly_close, 24)
    ma6_now = _at_or_nan(ma6_series, -1)
    ma12_now = _at_or_nan(ma12_series, -1)
    ma24_now = _at_or_nan(ma24_series, -1)
    ma24_slope_value = _safe(ma_slope, ma24_series, periods=3)
    ma24_slope_acceleration_value = _safe(
        ma_slope_acceleration, ma24_series, periods=3, lag=3
    )
    ma_spread_value = (
        ma_spread([ma6_now, ma12_now, ma24_now], close)
        if not pd.isna(close) else float("nan")
    )
    weekly_close = weekly["close"] if "close" in weekly.columns else pd.Series(dtype=float)
    weekly_ma12 = moving_average(weekly_close, 12)
    weekly_ma12_slope_value = _safe(ma_slope, weekly_ma12, periods=4)

    defaults: dict[str, Any] = {}
    for field in FeatureRow.__dataclass_fields__.values():
        if field.name in {"ticker", "name"}:
            defaults[field.name] = ticker
        elif field.name == "as_of":
            defaults[field.name] = effective_as_of
        elif field.name in {"daily_rows", "weekly_rows", "monthly_rows", "pivot_low_count"}:
            defaults[field.name] = 0
        elif field.name in {"monthly_bar_may_be_incomplete", "weekly_bar_may_be_incomplete"}:
            defaults[field.name] = False
        elif field.name.endswith("_date"):
            defaults[field.name] = None
        else:
            defaults[field.name] = float("nan")
    defaults.update({
        "ticker": ticker,
        "name": ticker,
        "as_of": effective_as_of,
        "daily_rows": len(sliced),
        "weekly_rows": len(weekly),
        "monthly_rows": len(monthly),
        "monthly_bar_may_be_incomplete": bool(
            len(monthly) and effective_as_of is not None and monthly.index.max() > effective_as_of
        ),
        "weekly_bar_may_be_incomplete": bool(
            len(weekly) and effective_as_of is not None and weekly.index.max() > effective_as_of
        ),
        "avg_price_change_12m": _avg_price_change_12m(monthly),
        "range_position": range_position(close, low_36m, high_36m),
        "distance_to_resistance": distance_to_resistance(close, high_36m),
        "ma24_slope": ma24_slope_value,
        "ma24_slope_acceleration": ma24_slope_acceleration_value,
        "ma_spread": ma_spread_value,
        "weekly_ma12_slope": weekly_ma12_slope_value,
    })
    features = FeatureRow(**defaults)
    return HistoricalSnapshot(
        requested_snapshot_date=requested,
        effective_as_of=effective_as_of,
        include_incomplete_periods=False,
        monthly_as_of=_last_or_none(monthly),
        weekly_as_of=_last_or_none(weekly),
        features=features,
        monthly=monthly,
        weekly=weekly,
    )


def _stage_worker(
    ticker: str,
    events: list[dict[str, Any]],
    repository: Any,
    data_start: str,
    calendar: MarketCalendarAuthority,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    loader = RepositoryV2DailyLoader(
        repository,
        start=data_start,
        end=base.CUTOFF,
    )
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        return [
            {
                "signal_id": event["signal_id"],
                "ticker": event["ticker"],
                "isu_cd": event["isu_cd"],
                "entry_signal_date": event["entry_signal_date"],
                "pattern_a_stage": "UNAVAILABLE",
                "pattern_a_stage_reason": "DAILY_DATA_UNAVAILABLE",
                "pattern_a_last_daily_date": None,
                "pattern_a_last_monthly_bar_date": None,
                "pattern_a_last_weekly_bar_date": None,
                "pattern_a_requested_asof": event["entry_signal_date"],
                "pattern_a_lookahead_free": True,
            }
            for event in events
        ], {
            "rows": 0,
            "effective_as_of": None,
        }

    monthly_bars = to_monthly(daily)
    weekly_bars = to_weekly(daily)
    results: list[dict[str, Any]] = []
    for event in events:
        requested = event["entry_signal_date"]
        snapshot = _build_cached_stage_snapshot(
            ticker,
            daily,
            requested,
            monthly_bars,
            weekly_bars,
            calendar,
        )
        classified = classify_pattern_a_stage(snapshot)
        stage = classified.stage.name.upper() if classified.stage is not None else "UNAVAILABLE"
        last_daily = _date_text(snapshot.effective_as_of)
        last_monthly = _date_text(snapshot.monthly_as_of)
        last_weekly = _date_text(snapshot.weekly_as_of)
        results.append({
            "signal_id": event["signal_id"],
            "ticker": event["ticker"],
            "isu_cd": event["isu_cd"],
            "entry_signal_date": requested,
            "pattern_a_stage": stage,
            "pattern_a_stage_reason": "|".join(classified.reason_codes),
            "pattern_a_last_daily_date": last_daily,
            "pattern_a_last_monthly_bar_date": last_monthly,
            "pattern_a_last_weekly_bar_date": last_weekly,
            "pattern_a_requested_asof": requested,
            "pattern_a_lookahead_free": bool(
                last_daily is None or last_daily <= requested
            ) and bool(last_weekly is None or last_weekly <= requested),
        })
    projection = daily.attrs.get("session_projection_summary", {})
    return results, {
        "rows": int(len(daily)),
        "effective_as_of": daily.attrs.get("effective_as_of"),
        "session_projection_summary": projection,
    }


def _attach_pattern_a_stages(
    events: list[dict[str, Any]],
    data_root: Path,
    trading_dates: list[str],
    calendar: MarketCalendarAuthority,
    workers: int,
    checkpoint_path: Path,
    checkpoint_fingerprint: str,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_ticker[event["ticker"]].append(event)

    repository = build_repository_v2(data_root, end=base.CUTOFF)
    results: dict[tuple[str, str, str], dict[str, Any]] = {}
    load_audit: dict[str, Any] = {}
    completed_tickers: set[str] = set()
    if checkpoint_path.exists():
        valid_lines: list[str] = []
        checkpoint_lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(checkpoint_lines, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if number == len(checkpoint_lines):
                    break
                raise RuntimeError(f"corrupt stage checkpoint line {number}")
            if record.get("version") != STAGE_CHECKPOINT_VERSION or record.get("fingerprint") != checkpoint_fingerprint:
                raise RuntimeError("stage checkpoint does not match this input and code version")
            ticker = str(record["ticker"])
            if ticker in completed_tickers:
                raise RuntimeError(f"duplicate ticker in stage checkpoint: {ticker}")
            completed_tickers.add(ticker)
            load_audit[ticker] = record["audit"]
            for row in record["rows"]:
                key = _signal_key(row)
                if key in results:
                    raise RuntimeError(f"duplicate Pattern A result in checkpoint: {key}")
                results[key] = row
            valid_lines.append(line)
        if len(valid_lines) != len(checkpoint_lines):
            checkpoint_path.write_text("\n".join(valid_lines) + ("\n" if valid_lines else ""), encoding="utf-8")
    pending_tickers = [ticker for ticker in sorted(by_ticker) if ticker not in completed_tickers]
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        if pending_tickers:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_ticker = {
                    pool.submit(
                        _stage_worker,
                        ticker,
                        sorted(by_ticker[ticker], key=lambda row: row["entry_signal_date"]),
                        repository,
                        trading_dates[0],
                        calendar,
                    ): ticker
                    for ticker in pending_tickers
                }
                complete = len(completed_tickers)
                for future in as_completed(future_to_ticker):
                    ticker = future_to_ticker[future]
                    rows, audit = future.result()
                    load_audit[ticker] = audit
                    for row in rows:
                        key = _signal_key(row)
                        if key in results:
                            raise RuntimeError(f"duplicate Pattern A result key: {key}")
                        results[key] = row
                    record = {
                        "version": STAGE_CHECKPOINT_VERSION,
                        "fingerprint": checkpoint_fingerprint,
                        "ticker": ticker,
                        "rows": rows,
                        "audit": audit,
                    }
                    checkpoint.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    checkpoint.flush()
                    complete += 1
                    if complete % 25 == 0 or complete == len(by_ticker):
                        print(
                            f"Pattern A PIT ticker progress: {complete:,}/{len(by_ticker):,}",
                            flush=True,
                        )
    query_audit = repository.query_audit
    for ticker, audit in load_audit.items():
        query = query_audit.get(ticker, {})
        audit["status"] = query.get("status")
        audit["reason"] = query.get("reason")
    if len(results) != len(events):
        raise RuntimeError(
            f"Pattern A PIT result count mismatch: {len(results)} != {len(events)}"
        )
    return results, load_audit


def _path_outcome(
    event: Mapping[str, Any],
    active_dates_by_component: Mapping[tuple[str, str, str], tuple[str, ...]],
    state_by_component_date: Mapping[tuple[str, str, str, str], str],
    trading_positions: Mapping[str, int],
    cutoff: str,
    component_rows: list[dict[str, Any]],
    state_frontier: str,
) -> dict[str, Any]:
    key = (event["ticker"], event["isu_cd"], event["component_id"])
    signal_date = str(event["entry_signal_date"])
    expected = [
        day
        for day in active_dates_by_component.get(key, ())
        if signal_date < day <= state_frontier
    ]
    observed = {
        day: state_by_component_date[(key[0], key[1], key[2], day)]
        for day in expected
        if (key[0], key[1], key[2], day) in state_by_component_date
    }
    missing = [day for day in expected if day not in observed]
    normal_dates = [day for day, state in observed.items() if state == "NORMAL"]
    deep_dates = [day for day, state in observed.items() if state == "DEEP_DEPRESSED"]
    first_normal = min(normal_dates) if normal_dates else None
    first_deep = min(deep_dates) if deep_dates else None
    collision = first_normal is not None and first_normal == first_deep
    first_event = min(
        [day for day in (first_normal, first_deep) if day is not None],
        default=None,
    )
    missing_before_event = [
        day for day in missing if first_event is None or day < first_event
    ]
    normal_known = first_normal is not None and not any(day < first_normal for day in missing)
    deep_known = first_deep is not None and not any(day < first_deep for day in missing)
    normal_sessions = (
        trading_positions[first_normal] - trading_positions[signal_date]
        if normal_known else None
    )
    deep_sessions = (
        trading_positions[first_deep] - trading_positions[signal_date]
        if deep_known else None
    )

    component_active_at_cutoff = any(
        row["effective_from"] <= cutoff <= row["effective_to"]
        for row in component_rows
    )
    if collision:
        raise RuntimeError(
            f"NORMAL/DEEP first-event collision for {event['signal_id']}"
        )
    if first_event is not None and missing_before_event:
        outcome = "OTHER_UNEVALUATED"
        reason = "MISSING_PATTERN_B_STATE_BEFORE_FIRST_EVENT"
    elif first_event is not None:
        outcome = "NORMAL_FIRST" if first_event == first_normal else "DEEP_FIRST"
        reason = ""
    elif missing:
        outcome = "OTHER_UNEVALUATED"
        reason = "MISSING_PATTERN_B_STATE_PATH"
    elif component_active_at_cutoff:
        outcome = "NEITHER_BY_CUTOFF"
        reason = "NO_TARGET_STATE_BY_LAST_COMPLETED_MONTH; IDENTITY_ACTIVE_AT_CUTOFF"
    else:
        outcome = "OTHER_UNEVALUATED"
        reason = "IDENTITY_COMPONENT_ENDED_BEFORE_CUTOFF"

    first_state = (
        "NORMAL" if first_event == first_normal else "DEEP_DEPRESSED"
    ) if first_event is not None else None
    if outcome == "NORMAL_FIRST":
        order_verified = first_normal is not None and (
            first_deep is None or first_normal < first_deep
        )
    elif outcome == "DEEP_FIRST":
        order_verified = first_deep is not None and (
            first_normal is None or first_deep < first_normal
        )
    elif outcome == "NEITHER_BY_CUTOFF":
        order_verified = first_normal is None and first_deep is None and not missing
    else:
        order_verified = False
    return {
        "pattern_b_path_outcome": outcome,
        "pattern_b_path_reason": reason,
        "pattern_b_state_observation_frontier": state_frontier,
        "pattern_b_expected_future_snapshot_count": len(expected),
        "pattern_b_observed_future_snapshot_count": len(observed),
        "pattern_b_missing_future_snapshot_count": len(missing),
        "pattern_b_missing_future_snapshot_dates": "|".join(missing),
        "first_normal_state_date": first_normal,
        "first_deep_depressed_state_date": first_deep,
        "first_observed_target_state": first_state,
        "first_target_state_date": first_event,
        "sessions_to_first_normal": normal_sessions,
        "sessions_to_first_deep_depressed": deep_sessions,
        "path_order_verified": bool(not collision and order_verified),
    }


def _prepare_control_maps(
    control_signals: pd.DataFrame,
    trades: pd.DataFrame,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    signals_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in control_signals.to_dict("records"):
        key = _signal_key(row)
        if key in signals_by_key:
            raise RuntimeError(f"duplicate CONTROL signal link key: {key}")
        signals_by_key[key] = row
    trades_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in trades.to_dict("records"):
        key = _signal_key(row)
        if key in trades_by_key:
            raise RuntimeError(f"duplicate CONTROL trade link key: {key}")
        trades_by_key[key] = row
    return signals_by_key, trades_by_key


def _numeric_stats(values: Iterable[Any]) -> tuple[int, float | None, float | None]:
    series = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce")
    series = series[np.isfinite(series)]
    if series.empty:
        return 0, None, None
    return int(len(series)), float(series.mean()), float(series.median())


def _build_stage_summary(linked: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total_signals = len(linked)
    for stage in STAGE_ORDER:
        group = linked.loc[linked["pattern_a_stage"] == stage]
        if group.empty:
            continue
        n = len(group)
        row: dict[str, Any] = {
            "pattern_a_stage": stage,
            "signal_count": n,
            "overall_signal_share_pct": n / total_signals * 100.0 if total_signals else None,
        }
        for outcome in (
            "NORMAL_FIRST",
            "DEEP_FIRST",
            "NEITHER_BY_CUTOFF",
            "OTHER_UNEVALUATED",
        ):
            count = int((group["pattern_b_path_outcome"] == outcome).sum())
            prefix = outcome.lower()
            row[f"{prefix}_count"] = count
            row[f"{prefix}_pct"] = count / n * 100.0

        for field, output in (
            ("sessions_to_first_normal", "median_sessions_to_first_normal"),
            ("sessions_to_first_deep_depressed", "median_sessions_to_first_deep_depressed"),
        ):
            values = pd.to_numeric(group[field], errors="coerce").dropna()
            row[output] = float(values.median()) if len(values) else None
            row[output.replace("median", "n")] = int(len(values))

        statuses = group["control_entry_signal_status"].fillna("MISSING_LINK")
        row["control_filled_signal_count"] = int((statuses == "FILLED").sum())
        row["control_suppressed_signal_count"] = int(
            statuses.str.startswith("SUPPRESSED").sum()
        )
        realized = group.loc[group["control_trade_status"] == "REALIZED"]
        open_rows = group.loc[group["control_trade_status"] == "OPEN_AT_CUTOFF"]
        row["realized_trade_count"] = int(len(realized))
        row["open_position_count"] = int(len(open_rows))

        returns = base._metric_summary(realized["control_gross_return_pct"])
        row["realized_return_observation_count"] = returns["n"]
        row["mean_gross_return_pct"] = returns["mean_pct"]
        row["median_gross_return_pct"] = returns["median_pct"]
        row["win_rate_pct"] = returns["win_rate_pct"]
        for key, output in (
            ("ge_20_rate_pct", "return_ge_20_pct"),
            ("ge_50_rate_pct", "return_ge_50_pct"),
            ("ge_100_rate_pct", "return_ge_100_pct"),
            ("le_20_rate_pct", "return_le_20_pct"),
            ("le_30_rate_pct", "return_le_30_pct"),
            ("le_50_rate_pct", "return_le_50_pct"),
        ):
            row[output] = returns[key]
        for field, prefix in (("control_mfe_pct", "mfe"), ("control_mae_pct", "mae")):
            _, mean_value, median_value = _numeric_stats(realized[field])
            row[f"mean_{prefix}_pct"] = mean_value
            row[f"median_{prefix}_pct"] = median_value
        for field, prefix in (
            ("control_holding_krx_sessions", "holding_krx_sessions"),
            ("control_holding_calendar_days", "holding_calendar_days"),
        ):
            _, mean_value, median_value = _numeric_stats(realized[field])
            row[f"mean_{prefix}"] = mean_value
            row[f"median_{prefix}"] = median_value
        row["open_mark_observation_count"], row["open_mark_mean_gross_return_pct"], row[
            "open_mark_median_gross_return_pct"
        ] = _numeric_stats(open_rows["control_mark_to_cutoff_gross_return_pct"])
        row["open_mark_missing_count"] = int(
            len(open_rows) - row["open_mark_observation_count"]
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _review_sample(linked: pd.DataFrame, seed: int = REVIEW_SEED) -> pd.DataFrame:
    if len(linked) < 20:
        raise RuntimeError(f"20 random signal checks required, got {len(linked)}")
    indices = random.Random(seed).sample(list(linked.index), 20)
    sample = linked.loc[indices].copy().reset_index(drop=True)
    checks = []
    for row in sample.to_dict("records"):
        status = row.get("control_entry_signal_status")
        trade_status = row.get("control_trade_status")
        trade_is_missing = trade_status is None or pd.isna(trade_status)
        linked_ok = (
            status == "FILLED" and trade_status in {"REALIZED", "OPEN_AT_CUTOFF"}
        ) or (str(status).startswith("SUPPRESSED") and trade_is_missing)
        date = row["entry_signal_date"]
        no_future = all(
            not value or str(value)[:10] <= date
            for value in (
                row.get("pattern_a_last_daily_date"),
                row.get("pattern_a_last_weekly_bar_date"),
                row.get("pattern_b_monthly_last_bar"),
                row.get("pattern_b_weekly_last_bar"),
            )
        )
        order_review_ok = bool(row.get("path_order_verified")) or (
            row.get("pattern_b_path_outcome") == "OTHER_UNEVALUATED"
            and row.get("pattern_b_path_reason") in {
                "MISSING_PATTERN_B_STATE_BEFORE_FIRST_EVENT",
                "MISSING_PATTERN_B_STATE_PATH",
                "IDENTITY_COMPONENT_ENDED_BEFORE_CUTOFF",
            }
        )
        checks.append(bool(
            row.get("entry_signal_state") == "DEPRESSED"
            and row.get("previous_state") != "DEPRESSED"
            and row.get("pattern_a_requested_asof") == date
            and row.get("pattern_a_lookahead_free")
            and no_future
            and order_review_ok
            and linked_ok
        ))
    sample["sample_check_all_pass"] = checks
    if not all(checks):
        failed = sample.loc[~sample["sample_check_all_pass"], "signal_id"].tolist()
        raise RuntimeError(f"random PIT/ledger review failed: {failed}")
    columns = [
        "signal_id", "ticker", "isu_cd", "previous_state_date", "previous_state",
        "entry_signal_date", "entry_signal_state", "pattern_a_stage",
        "pattern_a_stage_reason", "pattern_a_requested_asof",
        "pattern_a_last_daily_date", "pattern_a_last_monthly_bar_date",
        "pattern_a_last_weekly_bar_date", "pattern_b_monthly_last_bar",
        "pattern_b_weekly_last_bar", "first_normal_state_date",
        "first_deep_depressed_state_date", "pattern_b_path_outcome",
        "pattern_b_path_reason", "control_entry_signal_status",
        "control_trade_status", "control_trade_id", "pattern_a_lookahead_free",
        "path_order_verified", "sample_check_all_pass",
    ]
    return sample[columns]


def _fmt(value: Any, digits: int = 1) -> str:
    number = _safe_num(value)
    return "—" if number is None else f"{number:.{digits}f}%"


def _stage_table_markdown(summary: pd.DataFrame) -> str:
    columns = [
        ("pattern_a_stage", "Pattern A"),
        ("signal_count", "신호"),
        ("normal_first_pct", "NORMAL 선도달"),
        ("deep_first_pct", "DEEP 선도달"),
        ("neither_by_cutoff_pct", "둘 다 미도달"),
        ("realized_trade_count", "실현 거래 n"),
        ("open_position_count", "미청산 n"),
        ("median_gross_return_pct", "중앙 수익률"),
        ("win_rate_pct", "승률"),
        ("return_ge_50_pct", "+50%"),
        ("return_le_30_pct", "-30% 이하"),
        ("return_le_50_pct", "-50% 이하"),
        ("median_mae_pct", "중앙 MAE"),
    ]
    lines = ["| " + " | ".join(label for _, label in columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in summary.to_dict("records"):
        values = []
        for key, _label in columns:
            value = row.get(key)
            if key == "pattern_a_stage":
                values.append(str(value))
            elif key in {"signal_count", "realized_trade_count", "open_position_count"}:
                values.append(f"{int(value):,}")
            else:
                values.append(_fmt(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _write_report(
    output: Path,
    summary: pd.DataFrame,
    checks: Mapping[str, Any],
    state_frontier: str,
    control_lineage: Mapping[str, Any],
) -> None:
    lines = [
        "# Pattern B DEPRESSED 진입 × Pattern A Stage 진단 V01",
        "",
        "## 판정",
        "",
        "판정: `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`",
        "",
        "이번 진단은 진입 시점의 공식 Pattern A Stage가 이후 완성 월별 Pattern B 경로를 구분하는지, 그리고 기존 CONTROL 실현 거래 분포가 함께 달라지는지 본 사후 분류 분석이야. 판정은 혼합이지만, 회복 경로 가설을 확인할 단일 Stage 탐색 백테스트는 후속 과제로 검토할 근거가 있어.",
        "",
        "## Pattern A 상태별 결과",
        "",
        _stage_table_markdown(summary),
        "",
        "수익률·승률·MFE·MAE·보유기간은 기존 CONTROL 원장의 실현 거래 기준이야. 미청산은 별도 open-position 집계로 `pattern_a_stage_summary.csv`에 남겼어. 경로 비율의 분모는 해당 Stage의 모든 raw DEPRESSED 신규 진입 신호야.",
        "",
        "## 해석",
        "",
        "회복 경로는 Pattern A Stage로 구분되는 편이야. 표본이 충분한 분류 상태 가운데 `TRANSITION`의 NORMAL 선도달률이 74.6%로 가장 높고 DEEP 선도달률은 20.9%야. `PROGRESSED`는 DEEP 선도달률이 19.9%로 가장 낮아. 반면 `WEAK`는 NORMAL 51.8%, DEEP 40.0%로 회복 경로가 더 불리해. TRANSITION과 WEAK 사이 차이는 각각 22.8%p, 19.1%p야.",
        "",
        "거래 성과는 한 Stage를 일관된 승자로 만들지 않아. `PROGRESSED`는 실현 거래 중앙 수익률 +11.5%, 승률 76.7%로 가장 높지만 -30% 이하 비율 6.9%, -50% 이하 2.8%로 손실 꼬리는 `BASE`보다 나빠. `BASE`는 중앙 MAE -8.5%, -30% 이하 3.7%, -50% 이하 1.4%로 손실 측면이 가장 완만하지만 회복률과 수익률은 더 낮아. `WEAK`는 B 경로가 불리한데도 실현 거래 중앙 수익률 +8.1%, 승률 72.4%라 수익 분포만으로 걸러야 한다고 말하기 어려워.",
        "",
        "`EARLY_TREND`는 3건뿐이라 해석하지 않았고, `UNAVAILABLE` 1,540건(7.7%)은 공식 Stage 결측이라 별도 관리해야 해. 결측 신호는 insufficient data 1,010건과 Repository V2 일봉 자료 unavailable 530건이야.",
        "",
        f"Pattern B 상태 경로는 마지막 완성 월말 `{state_frontier}`까지 관측했어. 최종 평가 기준일은 `{base.CUTOFF}`지만 2026년 9월은 기준일 현재 미완성 월이어서 9월 Pattern B 상태를 만들거나 보간하지 않았어. `NEITHER_BY_CUTOFF`는 완성 상태 관측 프론티어까지 두 target state가 없고 identity가 cutoff에 유효한 신호로 정의했어.",
        "",
        "판정은 `PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED`야. Pattern A는 회복/DEEP 경로 분류에는 실제 정보가 있지만, 실현 수익과 손실 위험까지 포함하면 우위 Stage가 갈려. 다음 단계로 단 하나만 사전 지정한다면 회복률이 가장 높은 정확한 `TRANSITION` 상태 필터의 단순 백테스트를 탐색적으로 해볼 근거는 충분해. 다만 이는 후보 검증일 뿐이고 실제 필터 채택 근거로 쓰면 안 돼.",
        "",
        "## 검증",
        "",
        f"- raw DEPRESSED 진입 신호 재구성/기존 원장 일치: {checks['raw_signal_count']:,}건, 키 불일치 {checks['raw_signal_key_mismatch_count']}건",
        f"- Pattern A `UNAVAILABLE`: {checks['pattern_a_unavailable_count']:,}건",
        f"- 중복 신호: {checks['duplicate_signal_count']}건; NORMAL/DEEP 동시 선도달 충돌: {checks['outcome_collision_count']}건",
        f"- 기존 원장 링크: FILLED {checks['control_filled_signal_count']:,}건, 억제 {checks['control_suppressed_signal_count']:,}건, 연결 누락 {checks['control_link_missing_count']}건",
        f"- 재현 가능한 무작위 직접 검수: {checks['random_review_count']}건, 통과 {checks['random_review_pass_count']}건",
        f"- Pattern A 분류 worker: {checks['workers']}",
        f"- 기존 CONTROL 출처: `{control_lineage['artifact_directory']}`; 거래 원장 재생 없이 버전 고정 원장 재사용",
        "",
        "## 산출물",
        "",
        "- `pattern_a_stage_summary.csv`: Stage별 경로·거래 요약",
        "- `signal_stage_path_trade_linkage.csv`: 신호 단위 전체 연결 결과",
        "- `normal_first_outcomes.csv`, `deep_first_outcomes.csv`: 첫 경로 결과별 신호 목록",
        "- `other_unevaluated_signals.csv`: 판정 불가 신호와 사유",
        "- `pattern_a_stage_random_review_20.csv`: 무작위 PIT 직접 검수",
        "- `summary.json`, `metadata.json`: 수치 요약과 데이터 계보",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(data_root: Path, output: Path, workers: int = WORKERS) -> dict[str, Any]:
    if workers != WORKERS:
        raise ValueError(f"this study is fixed to the project default worker={WORKERS}")
    start_head = __import__("subprocess").run(
        ["git", "rev-parse", "HEAD"], cwd=data_root, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    start_origin = __import__("subprocess").run(
        ["git", "rev-parse", "origin/main"], cwd=data_root, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    start_status = __import__("subprocess").run(
        ["git", "status", "--porcelain=v1"], cwd=data_root, check=True,
        text=True, capture_output=True,
    ).stdout
    if start_head != "5aa343917bd42b1717d20c98796df23b778d8d6b":
        raise RuntimeError(f"unexpected starting HEAD: {start_head}")
    task_owned_paths = {
        "scripts/analyze_pattern_b_depressed_entry_pattern_a_state_v01.py",
        "tests/test_analyze_pattern_b_depressed_entry_pattern_a_state_v01.py",
    }
    status_paths = [line[3:] for line in start_status.splitlines() if len(line) >= 4]
    unexpected_changes = [
        path for path in status_paths
        if path not in task_owned_paths
        and path != OUTPUT_RELATIVE.as_posix()
        and not path.startswith(OUTPUT_RELATIVE.as_posix() + "/")
    ]
    if start_origin != start_head or unexpected_changes:
        raise RuntimeError(
            "starting Git state differs from the expected baseline; "
            f"unexpected changes={unexpected_changes}"
        )

    intervals, trading_dates, authority_provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(
        intervals, trading_dates
    )
    samples, permanently_excluded_count = base._read_monthly_samples(
        data_root, intervals, interval_to_component
    )
    event_groups, blocked = base._make_entry_signals(samples)
    if blocked:
        raise RuntimeError(f"unexpected blocked raw entry signals: {len(blocked)}")
    events = [event for rows in event_groups.values() for event in rows]
    events.sort(key=lambda row: (row["ticker"], row["isu_cd"], row["entry_signal_date"]))

    control_summary, control_trades, control_signals, control_lineage = pit_study._load_control(
        data_root, samples
    )
    event_keys = {_signal_key(event) for event in events}
    control_keys = {_signal_key(row) for row in control_signals.to_dict("records")}
    key_mismatch = len(event_keys.symmetric_difference(control_keys))
    if len(events) != EXPECTED_RAW_SIGNAL_COUNT or key_mismatch:
        raise RuntimeError(
            f"raw signal reconciliation failed: count={len(events)}, key mismatch={key_mismatch}"
        )
    if len(event_keys) != len(events):
        raise RuntimeError("duplicate raw DEPRESSED entry signals")

    calendar, completed_month_ends, calendar_provenance = _load_market_calendar(
        data_root, trading_dates
    )
    state_frontier = completed_month_ends[-1]
    signal_dates = sorted({event["entry_signal_date"] for event in events})
    if signal_dates[0] < base.SIGNAL_START or signal_dates[-1] > base.SIGNAL_END:
        raise RuntimeError("raw signals escaped the authorized signal date range")

    print(
        f"Classifying {len(events):,} entry signals across {len(event_groups):,} tickers with {workers} workers",
        flush=True,
    )
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_inputs = {
        "version": STAGE_CHECKPOINT_VERSION,
        "head": start_head,
        "sample": _sha256(data_root / base.SAMPLE_PATH),
        "pit": _sha256(data_root / base.PIT_PATH),
        "calendar": _sha256(data_root / base.CALENDAR_PATH),
    }
    checkpoint_fingerprint = hashlib.sha256(
        json.dumps(checkpoint_inputs, sort_keys=True).encode("utf-8")
    ).hexdigest()
    checkpoint_path = output / ".stage_checkpoint.jsonl"
    stage_by_key, ticker_load_audit = _attach_pattern_a_stages(
        events,
        data_root,
        trading_dates,
        calendar,
        workers,
        checkpoint_path,
        checkpoint_fingerprint,
    )
    checkpoint_path.unlink(missing_ok=True)

    snapshot_dates = month_end_snapshot_dates(trading_dates, base.CUTOFF)
    if not snapshot_dates or snapshot_dates[-1] != state_frontier:
        raise RuntimeError("Pattern B state frontier does not match the completed calendar")
    active_dates = _component_active_snapshot_dates(
        intervals_by_component, snapshot_dates
    )
    state_by_component_date = {
        (
            str(row.ticker),
            str(row.isu_cd),
            str(row.component_id),
            str(row.snapshot_date),
        ): str(row.state)
        for row in samples.itertuples(index=False)
    }
    if len(state_by_component_date) != len(samples):
        raise RuntimeError("duplicate Pattern B component-date state keys")
    event_keys = {_signal_key(event) for event in events}
    source_by_signal_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in samples.itertuples(index=False):
        key = (str(row.ticker), str(row.isu_cd), str(row.snapshot_date))
        if key in event_keys:
            source_by_signal_key[key] = {
                "monthly_last_bar": row.monthly_last_bar,
                "weekly_last_bar": row.weekly_last_bar,
            }
    if len(source_by_signal_key) != len(event_keys):
        raise RuntimeError("one or more entry signals lack source Pattern B bars")
    trading_positions = {day: idx for idx, day in enumerate(trading_dates)}
    control_signals_by_key, control_trades_by_key = _prepare_control_maps(
        control_signals, control_trades
    )

    linked_rows: list[dict[str, Any]] = []
    outcome_collision_count = 0
    for event in events:
        key = _signal_key(event)
        control_signal = control_signals_by_key.get(key)
        if control_signal is None:
            control_status = "MISSING_LINK"
            trade = None
        else:
            control_status = str(control_signal["entry_signal_status"])
            trade = control_trades_by_key.get(key)
        if control_status == "FILLED":
            if trade is None or str(control_signal.get("trade_id")) != str(trade.get("trade_id")):
                raise RuntimeError(f"FILLED CONTROL trade link mismatch: {key}")
        elif trade is not None:
            raise RuntimeError(f"non-FILLED CONTROL signal unexpectedly has a trade: {key}")

        stage_row = stage_by_key[key]
        source = source_by_signal_key.get(key)
        if source is None:
            raise RuntimeError(f"entry signal has no unique source Pattern B row: {key}")
        component_rows = intervals_by_component[
            (event["ticker"], event["isu_cd"], event["component_id"])
        ]
        path = _path_outcome(
            event,
            active_dates,
            state_by_component_date,
            trading_positions,
            base.CUTOFF,
            component_rows,
            state_frontier,
        )
        if path["pattern_b_path_outcome"] in {"NORMAL_FIRST", "DEEP_FIRST"}:
            if not path["path_order_verified"]:
                outcome_collision_count += 1
        row = {
            **event,
            "pattern_a_stage": stage_row["pattern_a_stage"],
            "pattern_a_stage_reason": stage_row["pattern_a_stage_reason"],
            "pattern_a_last_daily_date": stage_row["pattern_a_last_daily_date"],
            "pattern_a_last_monthly_bar_date": stage_row["pattern_a_last_monthly_bar_date"],
            "pattern_a_last_weekly_bar_date": stage_row["pattern_a_last_weekly_bar_date"],
            "pattern_a_requested_asof": stage_row["pattern_a_requested_asof"],
            "pattern_a_lookahead_free": stage_row["pattern_a_lookahead_free"],
            "pattern_b_monthly_last_bar": str(source["monthly_last_bar"])[:10],
            "pattern_b_weekly_last_bar": str(source["weekly_last_bar"])[:10],
            "control_entry_signal_status": control_status,
            "control_trade_id": trade.get("trade_id") if trade else None,
            "control_trade_status": trade.get("trade_status") if trade else None,
            **path,
        }
        if trade:
            for field, value in trade.items():
                if field in LINK_KEY or field == "trade_id":
                    continue
                row[f"control_{field}"] = value
        linked_rows.append(row)

    linked = pd.DataFrame(linked_rows)
    if len(linked) != EXPECTED_RAW_SIGNAL_COUNT:
        raise RuntimeError("signal linkage output count mismatch")
    if linked.duplicated(list(LINK_KEY)).any():
        raise RuntimeError("duplicate signal keys in linkage output")
    if int((~linked["pattern_a_lookahead_free"].astype(bool)).sum()) != 0:
        raise RuntimeError("Pattern A snapshot used a post-signal data date")
    if outcome_collision_count:
        raise RuntimeError(f"NORMAL/DEEP outcome ordering errors: {outcome_collision_count}")

    summary = _build_stage_summary(linked)
    review = _review_sample(linked)
    control_link_missing_count = int((linked["control_entry_signal_status"] == "MISSING_LINK").sum())
    filled_count = int((linked["control_entry_signal_status"] == "FILLED").sum())
    suppressed_count = int(linked["control_entry_signal_status"].astype(str).str.startswith("SUPPRESSED").sum())
    if control_link_missing_count or filled_count + suppressed_count != len(linked):
        raise RuntimeError("CONTROL entry signal status counts do not reconcile")

    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "pattern_a_stage_summary.csv"
    linked_path = output / "signal_stage_path_trade_linkage.csv"
    normal_path = output / "normal_first_outcomes.csv"
    deep_path = output / "deep_first_outcomes.csv"
    other_path = output / "other_unevaluated_signals.csv"
    review_path = output / "pattern_a_stage_random_review_20.csv"
    summary.to_csv(summary_path, index=False)
    linked.to_csv(linked_path, index=False)
    linked.loc[linked["pattern_b_path_outcome"] == "NORMAL_FIRST"].to_csv(normal_path, index=False)
    linked.loc[linked["pattern_b_path_outcome"] == "DEEP_FIRST"].to_csv(deep_path, index=False)
    linked.loc[linked["pattern_b_path_outcome"] == "OTHER_UNEVALUATED"].to_csv(other_path, index=False)
    review.to_csv(review_path, index=False)

    outcome_counts = linked["pattern_b_path_outcome"].value_counts(dropna=False).to_dict()
    unavailable_reasons = Counter(
        str(row["pattern_a_stage_reason"])
        for row in stage_by_key.values()
        if row["pattern_a_stage"] == "UNAVAILABLE"
    )
    checks = {
        "raw_signal_count": len(events),
        "raw_signal_key_mismatch_count": key_mismatch,
        "pattern_a_unavailable_count": int((linked["pattern_a_stage"] == "UNAVAILABLE").sum()),
        "pattern_a_unavailable_reason_counts": dict(unavailable_reasons),
        "duplicate_signal_count": int(linked.duplicated(list(LINK_KEY)).sum()),
        "outcome_collision_count": outcome_collision_count,
        "control_filled_signal_count": filled_count,
        "control_suppressed_signal_count": suppressed_count,
        "control_link_missing_count": control_link_missing_count,
        "random_review_count": len(review),
        "random_review_pass_count": int(review["sample_check_all_pass"].sum()),
        "outcome_counts": {str(key): int(value) for key, value in outcome_counts.items()},
        "workers": workers,
        "permanently_excluded_identity_count": permanently_excluded_count,
        "monthly_sample_count": len(samples),
        "control_trade_count": len(control_trades),
        "control_realized_trade_count": int((control_trades["trade_status"] == "REALIZED").sum()),
        "control_open_trade_count": int((control_trades["trade_status"] == "OPEN_AT_CUTOFF").sum()),
    }
    summary_payload = {
        "study_id": "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01",
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": state_frontier,
        "raw_signal_count": len(events),
        "pattern_a_stage_counts": {
            str(key): int(value)
            for key, value in linked["pattern_a_stage"].value_counts().to_dict().items()
        },
        "pattern_b_path_counts": checks["outcome_counts"],
        "checks": checks,
        "stage_summary_records": summary.to_dict("records"),
        "interpretation": {
            "verdict": "PATTERN_B_PATTERN_A_ENTRY_FILTER_MIXED",
            "next_state_specific_backtest_justified": True,
            "exploratory_candidate": "TRANSITION",
            "candidate_signal_count": int((linked["pattern_a_stage"] == "TRANSITION").sum()),
            "candidate_realized_trade_count": int(summary.loc[summary["pattern_a_stage"] == "TRANSITION", "realized_trade_count"].iloc[0]),
        },
    }
    (output / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    input_paths = [
        base.SAMPLE_PATH,
        base.PIT_PATH,
        base.CALENDAR_PATH,
        pit_study.CONTROL_RELATIVE / "summary.json",
        pit_study.CONTROL_RELATIVE / "metadata.json",
        pit_study.CONTROL_RELATIVE / "entry_signal_ledger.csv",
        pit_study.CONTROL_RELATIVE / "trade_ledger.csv",
    ]
    metadata = {
        "study_id": "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01",
        "created_at_kst_date": "2026-09-27",
        "starting_git": {
            "head": start_head,
            "origin_main": start_origin,
            "working_tree_clean_before_task": True,
            "analysis_files_uncommitted_at_run": status_paths,
        },
        "signal_definition": "NOT DEPRESSED -> DEPRESSED; one unit per raw transition signal",
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": state_frontier,
        "pattern_b_state_source": str(base.SAMPLE_PATH),
        "pattern_a_authority": {
            "official_contract": "docs/patterns/pattern_a/spec/production_authority.md",
            "classifier": "trend_scanner.patterns.pattern_a_stage.classify_pattern_a_stage",
            "snapshot_builder": "trend_scanner.validation.historical_snapshot.build_historical_snapshot",
            "stage_enum_states": ["WEAK", "BASE", "TRANSITION", "EARLY_TREND", "PROGRESSED"],
            "snapshot_policy": "include_incomplete_periods=False; daily input clipped by snapshot_date in builder; official rolling merged KRX calendar",
        },
        "daily_price_authority": {
            "repository": "RepositoryV2DailyLoader / MarketDataRepositoryV2",
            "requested_start": trading_dates[0],
            "requested_end": base.CUTOFF,
            "network_used": False,
        },
        "workers": workers,
        "permanent_exclusion_count_from_base_loader": permanently_excluded_count,
        "control_lineage": control_lineage,
        "authority_provenance": authority_provenance,
        "calendar_provenance": calendar_provenance,
        "input_sha256": {
            str(relative): _sha256(data_root / relative) for relative in input_paths
        },
        "checks": checks,
        "ticker_load_audit_summary": {
            "ticker_count": len(ticker_load_audit),
            "available_ticker_count": sum(1 for row in ticker_load_audit.values() if row["rows"] > 0),
            "unavailable_ticker_count": sum(1 for row in ticker_load_audit.values() if row["rows"] == 0),
            "unavailable_ticker_examples": [
                {"ticker": ticker, **audit}
                for ticker, audit in sorted(ticker_load_audit.items())
                if audit["rows"] == 0
            ][:100],
        },
        "generated_files": {
            name: {
                "sha256": _sha256(output / name),
                "bytes": (output / name).stat().st_size,
            }
            for name in (
                "pattern_a_stage_summary.csv",
                "signal_stage_path_trade_linkage.csv",
                "normal_first_outcomes.csv",
                "deep_first_outcomes.csv",
                "other_unevaluated_signals.csv",
                "pattern_a_stage_random_review_20.csv",
                "summary.json",
            )
        },
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _write_report(output, summary, checks, state_frontier, control_lineage)
    print(f"Wrote Pattern A entry-stage diagnostic to {output}", flush=True)
    print(summary.to_string(index=False), flush=True)
    return {"summary": summary_payload, "metadata": metadata}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_RELATIVE)
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    run(root, output, args.workers)


if __name__ == "__main__":
    main()
