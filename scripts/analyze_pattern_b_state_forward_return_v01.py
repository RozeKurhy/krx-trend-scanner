#!/usr/bin/env python3
"""Pattern B V02 state forward-return distribution study V01.

This is a descriptive information study, not a trading strategy or backtest.
It reuses the sealed Pattern B feature/state implementations and Repository V2
price/corporate-action authority. All horizon endpoints are exact exchange
calendar offsets; absent prices are never filled or extrapolated.
"""

from __future__ import annotations

import argparse
import bisect
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.patterns import pattern_b_operational as pattern_b_op  # noqa: E402
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b  # noqa: E402
from trend_scanner.patterns.pattern_b_features_v01 import (  # noqa: E402
    STATUS_OK,
    _ma_distance,
    _range_position,
    completed_bars,
    compute_pattern_b_features_v01,
)
from trend_scanner.patterns.pattern_b_state_v02 import (  # noqa: E402
    FEATURES,
    MA24_DISTANCE,
    RANGE_36M,
    RANGE_52W,
    STATES,
    classify_pattern_b_state_v02,
)
from trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
    apply_permanent_identity_exclusions,
)

HORIZONS: dict[str, int] = {"3M": 63, "6M": 126, "12M": 252, "24M": 504}
PANEL_B_MIN_MARKET_CAP_KRW = 1_000_000_000_000
GROUPS = {
    "LOW": ("DEEP_DEPRESSED", "DEPRESSED"),
    "MID": ("NORMAL",),
    "HIGH": ("OVERHEATED", "EXTREME_OVERHEATED"),
}
SUMMARY_COLUMNS = (
    "panel", "horizon", "state_or_group", "n", "mean_return", "median_return",
    "positive_ratio", "ge_20_ratio", "ge_50_ratio", "ge_100_ratio", "le_20_ratio",
    "le_30_ratio", "le_50_ratio", "mean_mfe", "median_mfe", "mean_mae", "median_mae",
)


def interval_key(interval: Any, ticker_hint: str | None = None) -> tuple[str, str, str, str, str]:
    def value(name: str) -> str:
        if isinstance(interval, dict):
            return str(interval[name])
        if name == "ticker" and ticker_hint is not None:
            return ticker_hint
        return str(getattr(interval, name))

    return (
        value("ticker").strip().zfill(6), value("isu_cd").strip().upper(),
        value("market").strip().upper(), value("effective_from")[:10],
        value("effective_to")[:10],
    )


def month_end_snapshot_dates(trading_dates: Iterable[str], frontier: str) -> list[str]:
    """Last exchange date of each fully closed calendar month through frontier."""
    frontier_month = frontier[:7]
    by_month: dict[str, str] = {}
    for day in trading_dates:
        text = str(day)[:10]
        if text > frontier or text[:7] >= frontier_month:
            continue
        by_month[text[:7]] = text
    return [by_month[month] for month in sorted(by_month)]


def horizon_endpoint(snapshot_date: str, horizon: str, trading_dates: list[str]) -> str | None:
    """Return the exact Nth exchange session strictly after a snapshot."""
    start = bisect.bisect_left(trading_dates, snapshot_date)
    if start >= len(trading_dates) or trading_dates[start] != snapshot_date:
        return None
    end = start + HORIZONS[horizon]
    return trading_dates[end] if end < len(trading_dates) else None


def state_from_precomputed_bars(
    monthly_bars: pd.DataFrame,
    weekly_bars: pd.DataFrame,
    as_of: str,
) -> dict[str, Any]:
    """Evaluate exact authoritative V01 feature helpers on completed PIT bars.

    Bars are aggregated once per identity chain for speed. A bar is selected only
    when its calendar label is <= as_of, matching ``compute_pattern_b_features_v01``.
    MonthEnd and W-FRI bars with eligible labels contain no post-as_of sessions.
    """
    cut = pd.Timestamp(as_of).normalize()
    month_n = int(monthly_bars.index.searchsorted(cut, side="right"))
    week_n = int(weekly_bars.index.searchsorted(cut, side="right"))
    monthly = monthly_bars.iloc[:month_n]
    weekly = weekly_bars.iloc[:week_n]
    values = {
        RANGE_36M: _range_position(monthly, 36),
        MA24_DISTANCE: _ma_distance(monthly, 24),
        RANGE_52W: _range_position(weekly, 52),
    }
    missing = [key for key in FEATURES if values[key].status != STATUS_OK]
    if missing:
        return {
            "state": None,
            "reason": "|".join(f"{key}:{values[key].status}" for key in missing),
            "range_36m": values[RANGE_36M].value,
            "monthly_ma24_distance": values[MA24_DISTANCE].value,
            "range_52w": values[RANGE_52W].value,
            "monthly_last_bar": monthly.index[-1].date().isoformat() if len(monthly) else "",
            "weekly_last_bar": weekly.index[-1].date().isoformat() if len(weekly) else "",
            "monthly_bar_count": len(monthly),
            "weekly_bar_count": len(weekly),
        }
    state = classify_pattern_b_state_v02(*(values[key].value for key in FEATURES))
    return {
        "state": state,
        "reason": "",
        "range_36m": values[RANGE_36M].value,
        "monthly_ma24_distance": values[MA24_DISTANCE].value,
        "range_52w": values[RANGE_52W].value,
        "monthly_last_bar": monthly.index[-1].date().isoformat() if len(monthly) else "",
        "weekly_last_bar": weekly.index[-1].date().isoformat() if len(weekly) else "",
        "monthly_bar_count": len(monthly),
        "weekly_bar_count": len(weekly),
    }


def _load_segment(repository, interval: dict[str, Any]) -> tuple[pd.DataFrame | None, pd.DataFrame | None, str]:
    ticker = str(interval["ticker"]).zfill(6)
    loader = RepositoryV2DailyLoader(
        repository,
        start=str(interval["effective_from"]),
        end=str(interval["effective_to"]),
    )
    daily = loader.load(ticker)
    if daily is None:
        reason = str(repository.query_audit.get(ticker, {}).get("reason") or "REPOSITORY_V2_EMPTY")
        return None, None, reason
    if daily.attrs.get("data_authority") != "MarketDataRepositoryV2":
        raise RuntimeError(f"wrong price authority for {ticker} {interval['effective_from']}")
    if daily.index.min().date().isoformat() < str(interval["effective_from"]):
        raise RuntimeError(f"price rows precede PIT interval for {ticker} {interval['effective_from']}")
    if daily.index.max().date().isoformat() > str(interval["effective_to"]):
        raise RuntimeError(f"price rows follow PIT interval for {ticker} {interval['effective_to']}")
    ancillary = loader.load_ancillary(ticker)
    if ancillary is None:
        ancillary = pd.DataFrame(columns=["market_cap", "listed_shares"], index=pd.DatetimeIndex([]))
    elif ancillary.attrs.get("data_authority") != "MarketDataRepositoryV2":
        raise RuntimeError(f"wrong ancillary authority for {ticker}")
    return daily, ancillary, ""


def _concat_chain(
    chain: Iterable[Any],
    frames: dict[tuple[str, str, str, str, str], pd.DataFrame | None],
    ticker: str,
) -> pd.DataFrame | None:
    pieces: list[pd.DataFrame] = []
    for segment in chain:
        frame = frames.get(interval_key(segment, ticker))
        if frame is None or frame.empty:
            return None
        pieces.append(frame)
    if not pieces:
        return None
    combined = pd.concat(pieces).sort_index()
    if combined.index.has_duplicates:
        raise RuntimeError("duplicate dates in authorized identity chain")
    return combined


def _exact_positive_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    number = int(value)
    if number <= 0 or float(value) != number:
        return None
    return number


def _outcome_for_horizon(
    *,
    sample: dict[str, Any],
    horizon: str,
    endpoint: str,
    ticker_intervals: list[dict[str, Any]],
    trading_dates: list[str],
    frames: dict[tuple[str, str, str, str, str], pd.DataFrame | None],
) -> tuple[dict[str, Any] | None, str]:
    source_key = interval_key(sample)
    candidates = [
        iv for iv in ticker_intervals
        if iv.get("state") == "COMMON"
        and str(iv.get("effective_from", "")) <= endpoint <= str(iv.get("effective_to", ""))
        and str(iv.get("isu_cd", "")).strip().upper() == sample["isu_cd"]
    ]
    if len(candidates) != 1:
        return None, "FUTURE_IDENTITY_NOT_CONTIGUOUS"
    try:
        chain = pattern_b_op.history_chain(sample["ticker"], candidates[0], ticker_intervals, trading_dates)
    except pattern_b_op.PatternBHistoryError:
        return None, "FUTURE_IDENTITY_AMBIGUOUS"
    if source_key not in {interval_key(segment, sample["ticker"]) for segment in chain.segments}:
        return None, "FUTURE_IDENTITY_NOT_CONTIGUOUS"
    future = _concat_chain(chain.segments, frames, sample["ticker"])
    if future is None:
        return None, "FUTURE_SEGMENT_DATA_UNAVAILABLE"
    endpoint_ts = pd.Timestamp(endpoint)
    if endpoint_ts not in future.index:
        return None, "NO_EXACT_ENDPOINT_CLOSE"
    forward = future.loc[(future.index > pd.Timestamp(sample["snapshot_date"])) & (future.index <= endpoint_ts)]
    if forward.empty:
        return None, "NO_FORWARD_PRICE_BARS"
    end_close = float(future.loc[endpoint_ts, "close"])
    start_close = float(sample["snapshot_close"])
    if not np.isfinite(end_close) or end_close <= 0 or not np.isfinite(start_close) or start_close <= 0:
        return None, "INVALID_EXACT_CLOSE"
    return {
        "snapshot_date": sample["snapshot_date"],
        "ticker": sample["ticker"],
        "isu_cd": sample["isu_cd"],
        "market": sample["market"],
        "state": sample["state"],
        "range_36m": sample["range_36m"],
        "monthly_ma24_distance": sample["monthly_ma24_distance"],
        "range_52w": sample["range_52w"],
        "market_cap_krw": sample["market_cap_krw"],
        "pit_market_cap_exact": sample["pit_market_cap_exact"],
        "panel_b_eligible": sample["panel_b_eligible"],
        "horizon": horizon,
        "expected_sessions": HORIZONS[horizon],
        "endpoint_date": endpoint,
        "snapshot_close": start_close,
        "forward_close": end_close,
        "forward_return": end_close / start_close - 1.0,
        "mfe": float(forward["high"].max()) / start_close - 1.0,
        "mae": float(forward["low"].min()) / start_close - 1.0,
        "observed_forward_price_bars": int(len(forward)),
    }, ""


def _identity_exclusion_rows(intervals: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    objects = [SimpleNamespace(**interval) for interval in intervals]
    _, excluded = apply_permanent_identity_exclusions(objects)
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for row in excluded:
        key = (row["ticker"], row["isu_cd"].upper())
        by_identity.setdefault(key, row)
    rows = [by_identity[key] for key in sorted(by_identity)]
    return rows, set(by_identity)


def _summary_row(panel: str, horizon: str, label: str, frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["forward_return"].astype(float)
    mfe = frame["mfe"].astype(float)
    mae = frame["mae"].astype(float)
    n = len(frame)
    if not n:
        return dict.fromkeys(SUMMARY_COLUMNS, None) | {
            "panel": panel, "horizon": horizon, "state_or_group": label, "n": 0,
        }
    return {
        "panel": panel,
        "horizon": horizon,
        "state_or_group": label,
        "n": int(n),
        "mean_return": float(returns.mean()),
        "median_return": float(returns.median()),
        "positive_ratio": float((returns > 0).mean()),
        "ge_20_ratio": float((returns >= 0.20).mean()),
        "ge_50_ratio": float((returns >= 0.50).mean()),
        "ge_100_ratio": float((returns >= 1.00).mean()),
        "le_20_ratio": float((returns <= -0.20).mean()),
        "le_30_ratio": float((returns <= -0.30).mean()),
        "le_50_ratio": float((returns <= -0.50).mean()),
        "mean_mfe": float(mfe.mean()),
        "median_mfe": float(mfe.median()),
        "mean_mae": float(mae.mean()),
        "median_mae": float(mae.median()),
    }


def summarize_outcomes(outcomes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    state_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    for panel in ("ALL", "PIT_1T_PLUS"):
        selected_panel = outcomes if panel == "ALL" else outcomes.loc[outcomes["panel_b_eligible"]]
        for horizon in HORIZONS:
            selected_horizon = selected_panel.loc[selected_panel["horizon"] == horizon]
            for state in STATES:
                state_rows.append(_summary_row(
                    panel, horizon, state, selected_horizon.loc[selected_horizon["state"] == state],
                ))
            group_frame = selected_horizon.copy()
            group_frame["group"] = group_frame["state"].map(
                {state: group for group, members in GROUPS.items() for state in members}
            )
            for group in GROUPS:
                group_rows.append(_summary_row(
                    panel, horizon, group, group_frame.loc[group_frame["group"] == group],
                ))
    return pd.DataFrame(state_rows, columns=SUMMARY_COLUMNS), pd.DataFrame(group_rows, columns=SUMMARY_COLUMNS)


def _write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False, encoding="utf-8", compression="gzip" if path.suffix == ".gz" else None)
        return
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8", compression="gzip" if path.suffix == ".gz" else None)


def _run_spot_checks(
    repository,
    sample_frame: pd.DataFrame,
    outcome_frame: pd.DataFrame,
    intervals_by_ticker: dict[str, list[dict[str, Any]]],
    trading_dates: list[str],
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    state_checks: list[dict[str, Any]] = []
    pit_checks: list[dict[str, Any]] = []
    if sample_frame.empty or outcome_frame.empty:
        raise RuntimeError("not enough samples to perform required 20 spot checks")

    unique_outcome_keys = outcome_frame.drop_duplicates(["snapshot_date", "ticker", "isu_cd"])
    selected = unique_outcome_keys.sample(n=min(20, len(unique_outcome_keys)), random_state=seed)
    samples_by_key = sample_frame.set_index(["snapshot_date", "ticker", "isu_cd"], drop=False)
    dates_set = set(trading_dates)
    for _, outcome in selected.iterrows():
        key = (outcome["snapshot_date"], outcome["ticker"], outcome["isu_cd"])
        sample = samples_by_key.loc[key]
        ticker = str(sample["ticker"])
        ivs = intervals_by_ticker[ticker]
        active = [
            iv for iv in ivs
            if str(iv.get("effective_from", "")) <= sample["snapshot_date"] <= str(iv.get("effective_to", ""))
            and str(iv.get("isu_cd", "")).upper() == sample["isu_cd"]
            and iv.get("state") == "COMMON"
        ]
        if len(active) != 1:
            raise RuntimeError(f"spot-check identity is not unique: {key}")
        chain = pattern_b_op.history_chain(ticker, active[0], ivs, trading_dates)
        daily = pattern_b_op.load_history(repository, ticker, chain, sample["snapshot_date"])
        if daily is None:
            raise RuntimeError(f"spot-check authoritative PIT history unavailable: {key}")
        as_of_frame = daily.loc[daily.index <= pd.Timestamp(sample["snapshot_date"])]
        if as_of_frame.empty or as_of_frame.index.max() > pd.Timestamp(sample["snapshot_date"]):
            raise RuntimeError(f"look-ahead in spot-check input: {key}")
        official = evaluate_pattern_b(ticker, daily, sample["snapshot_date"])
        if official.pattern_b_state != sample["state"]:
            raise RuntimeError(f"optimized/authoritative Pattern B mismatch: {key}")
        for col, value in (("range_36m", official.range_36m),
                           ("monthly_ma24_distance", official.monthly_ma24_distance),
                           ("range_52w", official.range_52w)):
            if not np.isclose(float(sample[col]), float(value), rtol=0, atol=1e-12):
                raise RuntimeError(f"optimized/authoritative feature mismatch {col}: {key}")
        expected_endpoint = horizon_endpoint(sample["snapshot_date"], outcome["horizon"], trading_dates)
        if expected_endpoint != outcome["endpoint_date"] or expected_endpoint not in dates_set:
            raise RuntimeError(f"non-exact exchange-session endpoint: {key}")
        endpoint_iv = [
            iv for iv in ivs
            if iv.get("state") == "COMMON"
            and str(iv.get("effective_from", "")) <= expected_endpoint <= str(iv.get("effective_to", ""))
            and str(iv.get("isu_cd", "")).upper() == sample["isu_cd"]
        ]
        future_ok = False
        if len(endpoint_iv) == 1:
            future_chain = pattern_b_op.history_chain(ticker, endpoint_iv[0], ivs, trading_dates)
            if interval_key(active[0]) in {
                interval_key(segment, ticker) for segment in future_chain.segments
            }:
                forward_daily = pattern_b_op.load_history(repository, ticker, future_chain, expected_endpoint)
                if forward_daily is not None and pd.Timestamp(expected_endpoint) in forward_daily.index:
                    close = float(forward_daily.loc[pd.Timestamp(expected_endpoint), "close"])
                    future_ok = np.isclose(close, float(outcome["forward_close"]), rtol=0, atol=1e-10)
        if not future_ok:
            raise RuntimeError(f"exact forward close did not reproduce: {key}")
        state_checks.append({
            "snapshot_date": sample["snapshot_date"], "ticker": ticker, "isu_cd": sample["isu_cd"],
            "state": sample["state"], "authoritative_monthly_last_bar": official.monthly_last_bar,
            "authoritative_weekly_last_bar": official.weekly_last_bar,
            "pit_input_max_date": as_of_frame.index.max().date().isoformat(),
            "forward_start_date": sample["snapshot_date"], "forward_start_close": outcome["snapshot_close"],
            "horizon": outcome["horizon"], "expected_sessions": HORIZONS[outcome["horizon"]],
            "forward_end_date": expected_endpoint, "forward_end_close": outcome["forward_close"],
            "state_and_endpoint_verified": True,
        })

    eligible = sample_frame.loc[
        sample_frame["pit_market_cap_exact"]
        & (sample_frame["market_cap_krw"] >= PANEL_B_MIN_MARKET_CAP_KRW)
    ].drop_duplicates(["snapshot_date", "ticker", "isu_cd"])
    if len(eligible) < 20:
        raise RuntimeError(f"PIT 1T+ sample has fewer than 20 unique checks: {len(eligible)}")
    selected_pit = eligible.sample(n=20, random_state=seed + 1)
    for _, sample in selected_pit.iterrows():
        point = repository.get_stock_snapshot(str(sample["ticker"]), str(sample["snapshot_date"]))
        if point.index[0].date().isoformat() != sample["snapshot_date"]:
            raise RuntimeError("market cap check did not read exact snapshot date")
        observed = _exact_positive_int(point.iloc[0]["market_cap"])
        expected = _exact_positive_int(sample["market_cap_krw"])
        if observed != expected or observed is None or observed < PANEL_B_MIN_MARKET_CAP_KRW:
            raise RuntimeError(f"exact PIT market cap mismatch: {sample['ticker']} {sample['snapshot_date']}")
        pit_checks.append({
            "snapshot_date": sample["snapshot_date"], "ticker": sample["ticker"],
            "isu_cd": sample["isu_cd"], "market_cap_krw": observed,
            "exact_snapshot_date_verified": True, "threshold_verified": True,
        })
    return state_checks, pit_checks


def _run_survivorship_checks(
    sample_frame: pd.DataFrame,
    outcome_frame: pd.DataFrame,
    intervals_by_ticker: dict[str, list[dict[str, Any]]],
    trading_dates: list[str],
    frontier: str,
    seed: int,
) -> list[dict[str, Any]]:
    """Verify terminal PIT identities remain in Panel A and are censored by horizon."""
    candidates: list[dict[str, Any]] = []
    for _, sample in sample_frame.iterrows():
        interval_end = str(sample["effective_to"])
        if interval_end >= frontier:
            continue
        ticker, isu_cd = str(sample["ticker"]).strip().zfill(6), str(sample["isu_cd"]).upper()
        later_same_identity = [
            iv for iv in intervals_by_ticker[ticker]
            if iv.get("state") == "COMMON"
            and str(iv.get("isu_cd", "")).upper() == isu_cd
            and str(iv.get("effective_from", "")) > interval_end
        ]
        if later_same_identity:
            continue
        horizons_past_end = [
            (horizon, horizon_endpoint(str(sample["snapshot_date"]), horizon, trading_dates))
            for horizon in HORIZONS
        ]
        horizons_past_end = [
            (horizon, endpoint) for horizon, endpoint in horizons_past_end
            if endpoint is not None and endpoint > interval_end
        ]
        if not horizons_past_end:
            continue
        horizon, endpoint = max(horizons_past_end, key=lambda item: HORIZONS[item[0]])
        candidates.append({
            "snapshot_date": str(sample["snapshot_date"]), "ticker": ticker,
            "isu_cd": isu_cd, "state": str(sample["state"]),
            "identity_interval_end": interval_end, "horizon": horizon,
            "expected_endpoint_date": endpoint,
        })
    if not candidates:
        raise RuntimeError("no terminal PIT identity snapshots available for survivorship audit")
    candidate_frame = pd.DataFrame(candidates).sort_values("snapshot_date")
    candidate_frame = candidate_frame.drop_duplicates(["ticker", "isu_cd"], keep="last")
    if len(candidate_frame) < 20:
        raise RuntimeError(f"fewer than 20 terminal PIT identities for survivorship audit: {len(candidate_frame)}")
    chosen = candidate_frame.sample(n=20, random_state=seed + 2)
    outcome_keys = set(zip(
        outcome_frame["snapshot_date"].astype(str),
        outcome_frame["ticker"].map(lambda value: str(value).strip().zfill(6)),
        outcome_frame["isu_cd"].astype(str),
        outcome_frame["horizon"].astype(str),
    ))
    sample_keys = set(zip(
        sample_frame["snapshot_date"].astype(str),
        sample_frame["ticker"].map(lambda value: str(value).strip().zfill(6)),
        sample_frame["isu_cd"].astype(str),
    ))
    rows: list[dict[str, Any]] = []
    for _, row in chosen.iterrows():
        key = (row["snapshot_date"], row["ticker"], row["isu_cd"], row["horizon"])
        present = key in outcome_keys
        if present or (row["snapshot_date"], row["ticker"], row["isu_cd"]) not in sample_keys:
            raise RuntimeError(f"terminal PIT identity survivorship check failed: {key}")
        rows.append({
            **row.to_dict(),
            "panel_a_snapshot_retained": True,
            "endpoint_after_identity_interval_end": True,
            "outcome_row_present": False,
            "verification": "PASS",
        })
    return rows


def run_study(data_root: Path, output_dir: Path, seed: int = 20260927) -> dict[str, Any]:
    started = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    pit_path = data_root / "data/market/rolling_authority/merged_pit_intervals.json"
    calendar_path = data_root / "data/market/rolling_authority/merged_trading_calendar.json"
    pit = json.loads(pit_path.read_text(encoding="utf-8"))
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    intervals: list[dict[str, Any]] = [dict(iv) for iv in pit["intervals"]]
    intervals_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for iv in intervals:
        iv["ticker"] = str(iv["ticker"]).strip().zfill(6)
        iv["isu_cd"] = str(iv["isu_cd"]).strip().upper()
        intervals_by_ticker[iv["ticker"]].append(iv)
    for ivs in intervals_by_ticker.values():
        ivs.sort(key=lambda iv: (iv["effective_from"], iv["effective_to"], iv["isu_cd"], iv["market"]))
    trading_dates = [str(day)[:10] for day in calendar["trading_dates"]]
    if trading_dates != sorted(set(trading_dates)):
        raise RuntimeError("merged trading calendar must be sorted and unique")
    frontier = str(calendar.get("calendar_frontier") or pit["pit_frontier"])[:10]
    snapshot_dates = month_end_snapshot_dates(trading_dates, frontier)
    trading_date_set = set(trading_dates)
    snapshot_by_month = {day[:7]: day for day in snapshot_dates}
    if not snapshot_by_month or len(snapshot_by_month) != len(snapshot_dates):
        raise RuntimeError("monthly snapshot calendar construction failed")

    exclusion_rows, excluded_identities = _identity_exclusion_rows(intervals)
    eligible_intervals = [
        iv for iv in intervals
        if iv.get("state") == "COMMON" and (iv["ticker"], iv["isu_cd"]) not in excluded_identities
    ]
    active_snapshot_count = 0
    permanent_excluded_months = 0
    for iv in intervals:
        covered = sum(str(iv["effective_from"]) <= day <= str(iv["effective_to"]) for day in snapshot_dates)
        active_snapshot_count += covered if iv.get("state") == "COMMON" else 0
        if (iv["ticker"], iv["isu_cd"]) in excluded_identities:
            permanent_excluded_months += covered

    print(
        f"Loading authoritative Repository V2; intervals={len(eligible_intervals)} "
        f"snapshots={len(snapshot_dates)} frontier={frontier}", flush=True,
    )
    repository = build_repository_v2(data_root, end=frontier)
    sample_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    feature_unavailable: Counter[str] = Counter()
    segment_unavailable: Counter[str] = Counter()
    outcome_ineligible: Counter[str] = Counter()
    snapshot_no_exact_close = 0
    segment_load_errors: list[dict[str, Any]] = []

    eligible_tickers = sorted({iv["ticker"] for iv in eligible_intervals})
    for ticker_index, ticker in enumerate(eligible_tickers, 1):
        ticker_intervals = intervals_by_ticker[ticker]
        usable_intervals = [
            iv for iv in ticker_intervals
            if iv.get("state") == "COMMON"
            and (ticker, str(iv["isu_cd"]).upper()) not in excluded_identities
        ]
        frames: dict[tuple[str, str, str, str, str], pd.DataFrame | None] = {}
        ancillary_frames: dict[tuple[str, str, str, str, str], pd.DataFrame | None] = {}
        for iv in usable_intervals:
            key = interval_key(iv)
            try:
                daily, ancillary, reason = _load_segment(repository, iv)
            except Exception as exc:  # preserve identity-level evidence; fail loudly in the report
                detail = f"{type(exc).__name__}: {exc}"
                segment_load_errors.append({**iv, "reason": detail})
                frames[key] = None
                ancillary_frames[key] = None
                segment_unavailable["UNEXPECTED_LOAD_ERROR"] += 1
                continue
            frames[key], ancillary_frames[key] = daily, ancillary
            if daily is None:
                segment_unavailable[reason] += 1
                segment_load_errors.append({**iv, "reason": reason})

        for iv in usable_intervals:
            active_months = [
                day for day in snapshot_dates
                if str(iv["effective_from"]) <= day <= str(iv["effective_to"])
            ]
            if not active_months:
                continue
            try:
                chain = pattern_b_op.history_chain(ticker, iv, ticker_intervals, trading_dates)
            except pattern_b_op.PatternBHistoryError as exc:
                segment_unavailable["AMBIGUOUS_HISTORY_CHAIN"] += len(active_months)
                segment_load_errors.append({**iv, "reason": f"PatternBHistoryError: {exc}"})
                continue
            history = _concat_chain(chain.segments, frames, ticker)
            if history is None:
                segment_unavailable["CHAIN_DATA_UNAVAILABLE"] += len(active_months)
                continue
            max_date = history.index.max()
            monthly_bars = completed_bars(history, pd.offsets.MonthEnd(), max_date)
            weekly_bars = completed_bars(history, "W-FRI", max_date)
            key = interval_key(iv)
            own_daily = frames.get(key)
            own_ancillary = ancillary_frames.get(key)
            for snapshot_date in active_months:
                active_snapshot_count += 0  # the denominator was counted from PIT intervals above
                if own_daily is None or pd.Timestamp(snapshot_date) not in own_daily.index:
                    snapshot_no_exact_close += 1
                    continue
                state_values = state_from_precomputed_bars(monthly_bars, weekly_bars, snapshot_date)
                if state_values["state"] is None:
                    feature_unavailable[state_values["reason"]] += 1
                    continue
                snapshot_close = float(own_daily.loc[pd.Timestamp(snapshot_date), "close"])
                if not np.isfinite(snapshot_close) or snapshot_close <= 0:
                    snapshot_no_exact_close += 1
                    continue
                cap_value = None
                cap_exact = False
                if own_ancillary is not None and not own_ancillary.empty:
                    stamp = pd.Timestamp(snapshot_date)
                    if stamp in own_ancillary.index:
                        cap_value = _exact_positive_int(own_ancillary.loc[stamp, "market_cap"])
                        cap_exact = cap_value is not None
                sample = {
                    "snapshot_date": snapshot_date,
                    "ticker": ticker,
                    "isu_cd": str(iv["isu_cd"]).upper(),
                    "market": str(iv["market"]).upper(),
                    "effective_from": str(iv["effective_from"]),
                    "effective_to": str(iv["effective_to"]),
                    "state": state_values["state"],
                    "range_36m": state_values["range_36m"],
                    "monthly_ma24_distance": state_values["monthly_ma24_distance"],
                    "range_52w": state_values["range_52w"],
                    "monthly_last_bar": state_values["monthly_last_bar"],
                    "weekly_last_bar": state_values["weekly_last_bar"],
                    "monthly_bar_count": state_values["monthly_bar_count"],
                    "weekly_bar_count": state_values["weekly_bar_count"],
                    "snapshot_close": snapshot_close,
                    "market_cap_krw": cap_value,
                    "pit_market_cap_exact": cap_exact,
                    "panel_b_eligible": bool(cap_exact and cap_value >= PANEL_B_MIN_MARKET_CAP_KRW),
                }
                sample_rows.append(sample)
                for horizon in HORIZONS:
                    endpoint = horizon_endpoint(snapshot_date, horizon, trading_dates)
                    if endpoint is None:
                        outcome_ineligible[f"{horizon}:ENDPOINT_AFTER_FRONTIER"] += 1
                        continue
                    row, reason = _outcome_for_horizon(
                        sample=sample,
                        horizon=horizon,
                        endpoint=endpoint,
                        ticker_intervals=ticker_intervals,
                        trading_dates=trading_dates,
                        frames=frames,
                    )
                    if row is None:
                        outcome_ineligible[f"{horizon}:{reason}"] += 1
                    else:
                        outcome_rows.append(row)
        if ticker_index % 100 == 0 or ticker_index == len(eligible_tickers):
            print(
                f"[{ticker_index}/{len(eligible_tickers)}] PIT snapshots={len(sample_rows):,} "
                f"outcomes={len(outcome_rows):,} elapsed={time.time()-started:.0f}s",
                flush=True,
            )

    sample_frame = pd.DataFrame(sample_rows)
    outcome_frame = pd.DataFrame(outcome_rows)
    if sample_frame.empty or outcome_frame.empty:
        raise RuntimeError("the eligible study sample is empty")
    sample_key = ["snapshot_date", "ticker", "isu_cd"]
    outcome_key = sample_key + ["horizon"]
    if sample_frame.duplicated(sample_key).any():
        duplicates = sample_frame.loc[sample_frame.duplicated(sample_key, keep=False), sample_key].head(5)
        raise RuntimeError(f"duplicate monthly PIT snapshot keys: {duplicates.to_dict('records')}")
    if outcome_frame.duplicated(outcome_key).any():
        raise RuntimeError("duplicate panel outcome keys")
    if not outcome_frame["endpoint_date"].map(trading_date_set.__contains__).all():
        raise RuntimeError("outcome endpoint not in the authoritative exchange calendar")
    state_summary, group_summary = summarize_outcomes(outcome_frame)

    state_checks, pit_checks = _run_spot_checks(
        repository, sample_frame, outcome_frame, intervals_by_ticker, trading_dates, seed,
    )
    survivorship_checks = _run_survivorship_checks(
        sample_frame, outcome_frame, intervals_by_ticker, trading_dates, frontier, seed,
    )

    _write_csv(output_dir / "snapshot_samples.csv.gz", sample_frame)
    _write_csv(output_dir / "forward_outcomes.csv.gz", outcome_frame)
    _write_csv(output_dir / "summary_by_state.csv", state_summary)
    _write_csv(output_dir / "summary_by_group.csv", group_summary)
    _write_csv(output_dir / "permanent_identity_exclusions.csv", exclusion_rows)
    _write_csv(output_dir / "segment_data_issues.csv", segment_load_errors)
    _write_csv(output_dir / "lookahead_spot_checks.csv", state_checks)
    _write_csv(output_dir / "pit_market_cap_spot_checks.csv", pit_checks)
    _write_csv(output_dir / "survivorship_spot_checks.csv", survivorship_checks)

    horizon_counts: dict[str, Any] = {}
    for horizon in HORIZONS:
        h = outcome_frame.loc[outcome_frame["horizon"] == horizon]
        horizon_counts[horizon] = {
            "n": int(len(h)),
            "snapshot_start": str(h["snapshot_date"].min()) if len(h) else None,
            "snapshot_end": str(h["snapshot_date"].max()) if len(h) else None,
            "endpoint_start": str(h["endpoint_date"].min()) if len(h) else None,
            "endpoint_end": str(h["endpoint_date"].max()) if len(h) else None,
            "distinct_snapshot_dates": int(h["snapshot_date"].nunique()),
            "panel_b_n": int(h["panel_b_eligible"].sum()),
        }
    missing_cap_n = int((~sample_frame["pit_market_cap_exact"]).sum())
    metadata = {
        "study": "KRX Pattern B State Forward Return Study V01",
        "started_from_head": "78aa728a7116ad18e7f74744f30efde745f05521",
        "pit_authority_frontier": pit.get("pit_frontier"),
        "pit_authority_content_digest": pit.get("content_digest"),
        "calendar_frontier": frontier,
        "calendar_content_digest": calendar.get("content_digest"),
        "first_trading_date": trading_dates[0],
        "last_trading_date": trading_dates[-1],
        "snapshot_months": len(snapshot_dates),
        "snapshot_start": snapshot_dates[0],
        "snapshot_end": snapshot_dates[-1],
        "snapshot_rule": "last exchange trading date of each fully closed calendar month; frontier month excluded",
        "feature_contract": "Pattern B Feature Contract V01; adjusted OHLC through snapshot only; MonthEnd and W-FRI completed bars",
        "state_rule": "Pattern B State Rule V02; unchanged authoritative classifier",
        "interval_count_all": len(intervals),
        "interval_count_common": sum(iv.get("state") == "COMMON" for iv in intervals),
        "eligible_identity_keys": len({(iv["ticker"], iv["isu_cd"]) for iv in eligible_intervals}),
        "permanent_excluded_identity_count": len(exclusion_rows),
        "permanent_excluded_snapshot_identity_months": permanent_excluded_months,
        "common_identity_month_cells_before_price_state_eligibility": active_snapshot_count,
        "panel_a_snapshot_count": len(sample_frame),
        "panel_a_unique_identity_count": int(sample_frame[["ticker", "isu_cd"]].drop_duplicates().shape[0]),
        "exact_pit_market_cap_count": int(sample_frame["pit_market_cap_exact"].sum()),
        "missing_or_invalid_exact_pit_market_cap_count": missing_cap_n,
        "panel_b_snapshot_count": int(sample_frame["panel_b_eligible"].sum()),
        "panel_b_threshold_krw": PANEL_B_MIN_MARKET_CAP_KRW,
        "horizons": HORIZONS,
        "horizon_counts": horizon_counts,
        "feature_unavailable_reasons": dict(feature_unavailable),
        "segment_unavailable_reasons": dict(segment_unavailable),
        "outcome_ineligible_reasons": dict(outcome_ineligible),
        "snapshot_without_exact_adjusted_close_count": snapshot_no_exact_close,
        "lookahead_spot_checks": len(state_checks),
        "pit_market_cap_spot_checks": len(pit_checks),
        "survivorship_spot_checks": len(survivorship_checks),
        "random_seed": seed,
        "raw_repository_reader_stats": repository.raw_reader_stats,
        "elapsed_seconds": round(time.time() - started, 2),
        "artifacts": [
            "snapshot_samples.csv.gz", "forward_outcomes.csv.gz", "summary_by_state.csv",
            "summary_by_group.csv", "permanent_identity_exclusions.csv", "segment_data_issues.csv",
            "lookahead_spot_checks.csv", "pit_market_cap_spot_checks.csv", "survivorship_spot_checks.csv",
        ],
    }
    (output_dir / "study_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "artifacts/patterns/pattern_b/state_forward_return_v01",
    )
    parser.add_argument("--seed", type=int, default=20260927)
    args = parser.parse_args()
    metadata = run_study(args.data_root, args.output_dir, args.seed)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
