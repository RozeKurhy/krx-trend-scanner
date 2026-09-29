#!/usr/bin/env python3
"""Audit whether preserved zero-OHLC ETF sentinels reach ETF-36 entry signals.

This analysis-only evaluator replay is limited to the ten ETFs already identified
in the frozen ETF-36 study. It never alters raw rows, contracts, strategy code,
or the existing trade ledger, and does not simulate positions or exits.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any
import warnings

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_etf_36_afast_v2_vs_julia_5window_simple_v01 as study  # noqa: E402
from trend_scanner.data.resampler import to_monthly, to_weekly  # noqa: E402
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a  # noqa: E402
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_fast_contract  # noqa: E402
from trend_scanner.features.pivot import find_pivot_lows  # noqa: E402
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features  # noqa: E402
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features  # noqa: E402
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features  # noqa: E402
from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context  # noqa: E402

AUTHORITY_COMMIT = "b5df1642f04fcf9804e9aeda4309c59bc3bac915"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
BASE_REL = Path("artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01")
OUTPUT_REL = Path("artifacts/research/etf_36_zero_ohlc_sentinel_signal_impact_audit_v01")
TICKERS = (
    "133690", "139230", "140700", "157490", "160580", "195980",
    "228800", "228810", "241180", "266410",
)
STRATEGIES = ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "JULIA_STRATEGY_V00")
SUPPORT_DATE = "2026-09-01"

# Feature names and roles are traced from the frozen evaluator and strategy code.
FEATURE_META: dict[str, tuple[str, str, str]] = {
    "fast.range_position_24m": (
        "MONTHLY_24", "A FAST monthly permission gate",
        "monthly_regime_features.range_position_24m",
    ),
    "pattern_a.range_position_36m": (
        "MONTHLY_36", "Pattern A stage entry gate",
        "FeatureRow.range_position consumed by classify_pattern_a_stage",
    ),
    "pattern_a.range_36m": (
        "MONTHLY_36", "Pattern A score availability and score input",
        "FeatureRow.range_36m consumed by score_pattern_a",
    ),
    "fast.higher_weekly_low_count_13w": (
        "WEEKLY_13", "A FAST stage and required score input",
        "weekly_trigger_features.higher_weekly_low_count_13w",
    ),
    "fast.recent_5d_max_gap_abs_pct": (
        "DAILY_5", "A FAST daily risk entry gate",
        "daily_timing_features.recent_5d_max_gap_abs_pct",
    ),
    "fast.atr_14_pct": (
        "DAILY_14", "A FAST daily risk entry gate",
        "daily_timing_features.atr_14_pct",
    ),
    "pit.avg_volume_20d": (
        "DAILY_20", "Point-in-time ETF entry eligibility",
        "ETF-36 raw eligibility rolling volume average",
    ),
    "diagnostic.monthly_distance_from_12m_low": (
        "MONTHLY_12", "Diagnostic only; not consumed by entry contract",
        "monthly_regime_features.distance_from_12m_low",
    ),
    "diagnostic.monthly_distance_from_24m_low": (
        "MONTHLY_24", "Diagnostic only; not consumed by entry contract",
        "monthly_regime_features.distance_from_24m_low",
    ),
    "diagnostic.weekly_distance_from_13w_low_pct": (
        "WEEKLY_13", "Diagnostic only; not consumed by entry contract",
        "weekly_trigger_features.distance_from_13w_low_pct",
    ),
    "diagnostic.weekly_distance_from_26w_low_pct": (
        "WEEKLY_26", "Diagnostic only; not consumed by entry contract",
        "weekly_trigger_features.distance_from_26w_low_pct",
    ),
    "diagnostic.weekly_distance_from_52w_low_pct": (
        "WEEKLY_52", "Diagnostic only; not consumed by entry contract",
        "weekly_trigger_features.distance_from_52w_low_pct",
    ),
    "diagnostic.pattern_a_pivot_low_slope": (
        "MONTHLY_PIVOT", "Diagnostic only; not consumed by Pattern A score or stage",
        "FeatureRow.pivot_low_slope",
    ),
    "diagnostic.pattern_a_range_position_52w": (
        "WEEKLY_52", "Diagnostic only; not consumed by Pattern A score or stage",
        "FeatureRow.range_position_52w",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def read_manifest(market: str, end_date: str = SUPPORT_DATE) -> list[tuple[str, str, str, str]]:
    manifest = RAW_ROOT / "manifest.sqlite3"
    connection = sqlite3.connect(f"file:{manifest}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT date,status,file_path,file_sha256 FROM raw_snapshot_manifest "
            "WHERE market=? AND date<=? AND status='COMPLETE' ORDER BY date",
            (market, end_date),
        ).fetchall()
    finally:
        connection.close()
    return [(str(day), str(status), str(path or ""), str(file_sha or "")) for day, status, path, file_sha in rows]


def load_target_daily() -> tuple[dict[str, pd.DataFrame], list[str], dict[str, Any]]:
    """Read and SHA-verify local KRX ETF partitions through frozen support."""
    calendar_rows = read_manifest("KOSPI")
    calendar_dates = [day for day, status, _path, _sha in calendar_rows if status in {"COMPLETE", "NO_DATA"}]
    if not calendar_dates or calendar_dates[-1] != SUPPORT_DATE:
        raise RuntimeError(f"KRX_CALENDAR_SUPPORT_MISMATCH:{calendar_dates[-1:]}")

    etf_rows = read_manifest("ETF")
    accum: dict[str, list[pd.DataFrame]] = {ticker: [] for ticker in TICKERS}
    verified_file_count = 0
    scanned_file_count = 0
    hash_errors: list[str] = []
    for _day, status, relative_path, expected_sha in etf_rows:
        if status == "NO_DATA":
            continue
        path = RAW_ROOT / relative_path
        actual_sha = sha256_file(path)
        scanned_file_count += 1
        if not expected_sha or actual_sha != expected_sha:
            hash_errors.append(path.relative_to(ROOT).as_posix())
            continue
        verified_file_count += 1
        frame = pd.read_parquet(path)
        tickers = frame["ticker"].astype(str).str.strip().str.zfill(6)
        selected_mask = tickers.isin(TICKERS)
        if not selected_mask.any():
            continue
        selected = frame.loc[selected_mask, [
            "date", "ticker", "open", "high", "low", "close", "volume", "trading_value",
        ]].copy()
        selected["ticker"] = tickers.loc[selected_mask].to_numpy()
        for ticker, group in selected.groupby("ticker", sort=False):
            accum[str(ticker)].append(group)
    if hash_errors:
        raise RuntimeError(f"RAW_PARTITION_HASH_MISMATCH:{len(hash_errors)}")

    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker, parts in accum.items():
        if not parts:
            raise RuntimeError(f"NO_RAW_HISTORY:{ticker}")
        frame = pd.concat(parts, ignore_index=True)
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        if frame["date"].duplicated().any():
            raise RuntimeError(f"DUPLICATE_RAW_TICKER_DATE:{ticker}")
        frame = frame.sort_values("date")
        frame = frame.loc[frame["date"] <= pd.Timestamp(SUPPORT_DATE)]
        frame = frame.set_index("date").drop(columns=["ticker"])
        for column in ("open", "high", "low", "close", "volume", "trading_value"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        daily_by_ticker[ticker] = frame

    diagnostics = {
        "raw_etf_partition_count_through_support": len(etf_rows),
        "raw_etf_partition_files_scanned": scanned_file_count,
        "raw_etf_partition_files_sha_verified": verified_file_count,
        "raw_partition_hash_error_count": len(hash_errors),
        "raw_etf_target_ticker_daily_rows": sum(len(frame) for frame in daily_by_ticker.values()),
        "krx_calendar_session_count_through_support": len(calendar_dates),
        "krx_calendar_first_date": calendar_dates[0],
        "krx_calendar_last_date": calendar_dates[-1],
    }
    return daily_by_ticker, calendar_dates, diagnostics


def load_spans() -> pd.DataFrame:
    path = ROOT / BASE_REL / "effective_span_audit.csv"
    spans = pd.read_csv(path, dtype={"ticker": "string", "window_id": "string"})
    spans["ticker"] = spans["ticker"].map(study._norm_ticker)
    return spans.loc[
        spans["ticker"].isin(TICKERS) & spans["coverage_status"].ne("NOT_EVALUABLE")
    ].copy()


def load_ledger() -> pd.DataFrame:
    path = ROOT / BASE_REL / "trade_ledger.csv"
    ledger = pd.read_csv(path, dtype={"ticker": "string", "strategy_id": "string", "window_id": "string"})
    ledger["ticker"] = ledger["ticker"].map(study._norm_ticker)
    return ledger


def sentinel_periods(
    daily_by_ticker: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, dict[str, set[pd.Timestamp]]]]:
    rows: list[dict[str, Any]] = []
    periods: dict[str, dict[str, set[pd.Timestamp]]] = {}
    for ticker, daily in daily_by_ticker.items():
        numeric = daily[["open", "high", "low", "close", "volume"]]
        sent_mask = (
            numeric["open"].eq(0) & numeric["high"].eq(0) & numeric["low"].eq(0)
            & numeric["close"].gt(0) & numeric["volume"].eq(0)
        )
        sent_dates = pd.DatetimeIndex(daily.index[sent_mask])
        weekly = to_weekly(daily)
        monthly = to_monthly(daily)
        sent_weeks = {
            (pd.Timestamp(date) + pd.Timedelta(days=(4 - pd.Timestamp(date).weekday()) % 7)).normalize()
            for date in sent_dates
        }
        sent_months = {pd.Timestamp(pd.Timestamp(date) + pd.offsets.MonthEnd(0)).normalize() for date in sent_dates}
        periods[ticker] = {"dates": set(sent_dates), "weeks": sent_weeks, "months": sent_months}
        for raw_date in sent_dates:
            date = pd.Timestamp(raw_date)
            week_label = (date + pd.Timedelta(days=(4 - date.weekday()) % 7)).normalize()
            month_label = pd.Timestamp(date + pd.offsets.MonthEnd(0)).normalize()
            week_rows = daily.loc[(daily.index > week_label - pd.Timedelta(days=7)) & (daily.index <= week_label)]
            month_rows = daily.loc[daily.index.to_period("M") == date.to_period("M")]
            rows.append({
                "ticker": ticker,
                "sentinel_date": date.strftime("%Y-%m-%d"),
                "open": 0, "high": 0, "low": 0,
                "close": json_safe(numeric.loc[date, "close"]),
                "volume": 0,
                "weekly_bar_label": week_label.strftime("%Y-%m-%d"),
                "weekly_bar_low": json_safe(weekly.loc[week_label, "low"]) if week_label in weekly.index else None,
                "weekly_bar_high": json_safe(weekly.loc[week_label, "high"]) if week_label in weekly.index else None,
                "weekly_bar_positive_ohlc_session_count": int(((week_rows[["open", "high", "low", "close"]] > 0).all(axis=1)).sum()),
                "monthly_bar_label": month_label.strftime("%Y-%m-%d"),
                "monthly_bar_low": json_safe(monthly.loc[month_label, "low"]) if month_label in monthly.index else None,
                "monthly_bar_high": json_safe(monthly.loc[month_label, "high"]) if month_label in monthly.index else None,
                "monthly_bar_positive_ohlc_session_count": int(((month_rows[["open", "high", "low", "close"]] > 0).all(axis=1)).sum()),
            })
    result = pd.DataFrame(rows).sort_values(["ticker", "sentinel_date"]).reset_index(drop=True)
    return result, periods


def trailing_matches(frame: pd.DataFrame, labels: set[pd.Timestamp], count: int) -> list[pd.Timestamp]:
    if frame.empty:
        return []
    tail = set(pd.DatetimeIndex(frame.index[-count:]).normalize())
    return sorted(tail.intersection(labels))


def trailing_daily_matches(daily: pd.DataFrame, labels: set[pd.Timestamp], count: int) -> list[pd.Timestamp]:
    tail = set(pd.DatetimeIndex(daily.index[-count:]).normalize())
    return sorted(tail.intersection(labels))


def actual_entry_contract(result: dict[str, Any]) -> bool:
    stage = str(result.get("pattern_a_stage") or "").upper()
    return bool(
        result.get("fast_machine_stage") == "TRIGGER"
        and result.get("fast_machine_stage_status") == "READY"
        and result.get("fast_monthly_permission_state") == "PERMITTED_REGIME"
        and result.get("fast_daily_risk_state") in {"NORMAL", "ELEVATED"}
        and result.get("fast_score_status") in {"READY", "PARTIAL"}
        and stage in {"TRANSITION", "EARLY_TREND"}
    )


def compute_eligibility(daily: pd.DataFrame, listing_date: str, calendar_dates: list[str]) -> pd.DataFrame:
    """Match the frozen ETF-36 date/close/20-session-volume candidate gate."""
    sessions = pd.DatetimeIndex(pd.to_datetime(calendar_dates))
    aligned = daily.reindex(sessions)
    volumes = pd.to_numeric(aligned["volume"], errors="coerce")
    closes = pd.to_numeric(aligned["close"], errors="coerce")
    counts = volumes.rolling(window=20, min_periods=20).count()
    avg_volume = volumes.rolling(window=20, min_periods=20).mean()
    minimum_listing_date = pd.Timestamp(listing_date) + pd.DateOffset(years=2)
    eligible = (
        (sessions >= minimum_listing_date)
        & closes.ge(1000).fillna(False).to_numpy()
        & avg_volume.ge(10000).fillna(False).to_numpy()
        & counts.eq(20).fillna(False).to_numpy()
    )
    return pd.DataFrame({
        "date": sessions,
        "close": closes.to_numpy(),
        "avg_volume_20d": avg_volume.to_numpy(),
        "volume_count_20d": counts.to_numpy(),
        "eligible_before_window_start": eligible,
    }).set_index("date")


def audit(
    daily_by_ticker: dict[str, pd.DataFrame],
    calendar_dates: list[str],
    raw_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    output_dir = ROOT / OUTPUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    base_dir = ROOT / BASE_REL
    ledger_path = base_dir / "trade_ledger.csv"
    universe_path = base_dir / "official_etf_universe_36.csv"
    span_path = base_dir / "effective_span_audit.csv"
    raw_manifest = RAW_ROOT / "manifest.sqlite3"
    ledger_sha_before = sha256_file(ledger_path)
    universe_sha_before = sha256_file(universe_path)
    span_sha_before = sha256_file(span_path)
    manifest_sha_before = sha256_file(raw_manifest)
    source_paths = (
        "src/trend_scanner/patterns/pattern_a_fast_evaluator.py",
        "src/trend_scanner/patterns/pattern_a_evaluator.py",
        "src/trend_scanner/patterns/pattern_a_stage.py",
        "src/trend_scanner/patterns/pattern_a_score.py",
        "src/trend_scanner/research/pattern_a_fast_monthly_features.py",
        "src/trend_scanner/research/pattern_a_fast_weekly_features.py",
        "src/trend_scanner/research/pattern_a_fast_daily_features.py",
        "src/trend_scanner/validation/feature_report.py",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "src/trend_scanner/validation/julia_strategy_v00.py",
    )
    strategy_hashes_before = {rel: sha256_file(ROOT / rel) for rel in source_paths}

    sentinels, periods = sentinel_periods(daily_by_ticker)
    spans = load_spans()
    ledger = load_ledger()
    score, stage = study.base._read_contracts()
    calendar, _month_ends = study.base._calendar_from_dates(calendar_dates)
    study._WINDOWS, window_errors = study._resolved_windows(calendar_dates)
    if window_errors:
        raise RuntimeError(f"FROZEN_STANDARD_WINDOWS_MISMATCH:{window_errors}")

    official_universe = pd.read_csv(universe_path, dtype={"ticker": "string"})
    official_universe["ticker"] = official_universe["ticker"].map(study._norm_ticker)
    meta = official_universe.set_index("ticker").to_dict("index")

    feature_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    nonfinite_counts: dict[str, int] = {}
    nonfinite_kind_counts: dict[str, dict[str, int]] = {}
    diagnostic_nonfinite_counts: dict[str, int] = {}
    signal_path_nonfinite_counts: dict[str, int] = {}
    contract_candidate_count = 0
    actionable_candidate_count = 0
    evaluator_call_count = 0

    for ticker in TICKERS:
        daily = daily_by_ticker[ticker]
        instrument = meta[ticker]
        listing_date = str(instrument["listing_date"])
        daily = daily.loc[daily.index >= pd.Timestamp(listing_date)].copy()
        context = study.base.build_precomputed_ticker_context(ticker, str(instrument["name"]), daily)
        eligible_frame = compute_eligibility(daily, listing_date, calendar_dates)
        sentinel = periods[ticker]
        sentinel_months = sentinel["months"]
        sentinel_weeks = sentinel["weeks"]
        sentinel_dates = sentinel["dates"]
        if not sentinel_dates:
            raise RuntimeError(f"EXPECTED_SENTINEL_MISSING:{ticker}")
        daily_date_set = set(daily.index.normalize())
        valid_weeks = [
            pd.Timestamp(week).normalize()
            for week in context.full_weekly.index
            if pd.Timestamp(week).normalize() in daily_date_set
            and pd.Timestamp(week).normalize() <= pd.Timestamp(SUPPORT_DATE)
        ]

        # The longest direct entry-path dependency is the completed 36-month
        # Pattern A low/range feature. Do not replay outside its sentinel window.
        first_sentinel = min(sentinel_dates)
        last_sentinel = max(sentinel_dates)
        eval_stop = (pd.Timestamp(last_sentinel) + pd.DateOffset(months=38)).normalize()
        candidate_weeks = [week for week in valid_weeks if first_sentinel <= week <= eval_stop]
        for week in candidate_weeks:
            try:
                snapshot = build_historical_snapshot_from_context(
                    context, week, include_incomplete_periods=False, market_calendar=calendar,
                )
                if snapshot.weekly_as_of != week:
                    continue
                monthly, weekly = snapshot.monthly, snapshot.weekly
                daily_as_of = context.slice_daily_up_to(week)
                with np.errstate(divide="ignore", invalid="ignore", over="ignore"), warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    monthly_features = compute_monthly_regime_features(monthly)
                    weekly_features = compute_weekly_trigger_features(weekly)
                    daily_features = compute_daily_timing_features(daily_as_of)
                    features = {**monthly_features, **weekly_features, **daily_features}
                    fast = evaluate_fast_contract(features, score, stage)
                    pattern = evaluate_pattern_a(snapshot)
                evaluator_call_count += 1
            except Exception as exc:
                raise RuntimeError(
                    f"TARGETED_EVALUATOR_ERROR:{ticker}:{week:%Y-%m-%d}:{type(exc).__name__}"
                ) from exc

            monthly_active = {
                12: trailing_matches(monthly, sentinel_months, 12),
                24: trailing_matches(monthly, sentinel_months, 24),
                36: trailing_matches(monthly, sentinel_months, 36),
            }
            weekly_active = {
                13: trailing_matches(weekly, sentinel_weeks, 13),
                26: trailing_matches(weekly, sentinel_weeks, 26),
                52: trailing_matches(weekly, sentinel_weeks, 52),
            }
            daily_active = {
                5: trailing_daily_matches(daily_as_of, sentinel_dates, 5),
                14: trailing_daily_matches(daily_as_of, sentinel_dates, 14),
                20: trailing_daily_matches(daily_as_of, sentinel_dates, 20),
            }
            active: dict[str, tuple[list[pd.Timestamp], Any]] = {}

            def add(name: str, source_dates: list[pd.Timestamp], value: Any) -> None:
                if source_dates:
                    active[name] = (source_dates, value)

            if len(monthly) >= 24:
                add("fast.range_position_24m", monthly_active[24], features.get("range_position_24m"))
            if len(monthly) >= 36:
                add("pattern_a.range_position_36m", monthly_active[36], getattr(snapshot.features, "range_position", np.nan))
                add("pattern_a.range_36m", monthly_active[36], getattr(snapshot.features, "range_36m", np.nan))
            if len(weekly) >= 13:
                add("fast.higher_weekly_low_count_13w", weekly_active[13], features.get("higher_weekly_low_count_13w"))
            if len(daily_as_of) >= 6:
                add("fast.recent_5d_max_gap_abs_pct", daily_active[5], features.get("recent_5d_max_gap_abs_pct"))
            if len(daily_as_of) >= 15:
                add("fast.atr_14_pct", daily_active[14], features.get("atr_14_pct"))
            if week in eligible_frame.index and eligible_frame.loc[week, "volume_count_20d"] == 20:
                add("pit.avg_volume_20d", daily_active[20], eligible_frame.loc[week, "avg_volume_20d"])

            for length, feature_name, actual_name in (
                (12, "diagnostic.monthly_distance_from_12m_low", "distance_from_12m_low"),
                (24, "diagnostic.monthly_distance_from_24m_low", "distance_from_24m_low"),
            ):
                if len(monthly) >= length:
                    add(feature_name, monthly_active[length], features.get(actual_name))
            for length, feature_name, actual_name in (
                (13, "diagnostic.weekly_distance_from_13w_low_pct", "distance_from_13w_low_pct"),
                (26, "diagnostic.weekly_distance_from_26w_low_pct", "distance_from_26w_low_pct"),
                (52, "diagnostic.weekly_distance_from_52w_low_pct", "distance_from_52w_low_pct"),
            ):
                if len(weekly) >= length:
                    add(feature_name, weekly_active[length], features.get(actual_name))

            pivots = find_pivot_lows(monthly["low"], window=2) if "low" in monthly else []
            last_pivots = pivots[-4:]
            month_positions = {pd.Timestamp(label).normalize(): index for index, label in enumerate(monthly.index)}
            pivot_source_months = {
                month for month in monthly_active[36]
                if any(
                    abs(month_positions.get(pd.Timestamp(pivot_date).normalize(), -100000)
                        - month_positions.get(month, 100000)) <= 2
                    for pivot_date, _value in last_pivots
                )
            }
            if len(pivots) >= 2:
                add(
                    "diagnostic.pattern_a_pivot_low_slope",
                    sorted(pivot_source_months),
                    getattr(snapshot.features, "pivot_low_slope", np.nan),
                )
            if len(weekly) >= 52:
                add(
                    "diagnostic.pattern_a_range_position_52w",
                    weekly_active[52],
                    getattr(snapshot.features, "range_position_52w", np.nan),
                )

            if not active:
                continue
            eval_date = week.strftime("%Y-%m-%d")
            fast_result = {
                **fast,
                "pattern_a_stage": pattern.stage.value if pattern.stage else None,
                "pattern_a_evaluation_status": "READY" if pattern.score is not None and pattern.stage is not None else "UNAVAILABLE",
            }
            contract_candidate = actual_entry_contract(fast_result)
            for feature_name, (source_dates, value) in active.items():
                nonfinite = isinstance(value, (int, float, np.number)) and not math.isfinite(float(value))
                if value is None or value is pd.NA:
                    value_kind = "MISSING"
                elif isinstance(value, (int, float, np.number)):
                    numeric_value = float(value)
                    value_kind = (
                        "POSITIVE_INFINITY" if numeric_value == math.inf
                        else "NEGATIVE_INFINITY" if numeric_value == -math.inf
                        else "NAN" if math.isnan(numeric_value)
                        else "FINITE"
                    )
                else:
                    value_kind = type(value).__name__.upper()
                if nonfinite:
                    nonfinite_counts[feature_name] = nonfinite_counts.get(feature_name, 0) + 1
                    kinds = nonfinite_kind_counts.setdefault(feature_name, {})
                    kinds[value_kind] = kinds.get(value_kind, 0) + 1
                    if FEATURE_META[feature_name][1].startswith("Diagnostic only;"):
                        diagnostic_nonfinite_counts[feature_name] = diagnostic_nonfinite_counts.get(feature_name, 0) + 1
                    else:
                        signal_path_nonfinite_counts[feature_name] = signal_path_nonfinite_counts.get(feature_name, 0) + 1
                timeframe, role, source = FEATURE_META[feature_name]
                feature_rows.append({
                    "ticker": ticker,
                    "evaluation_date": eval_date,
                    "feature_name": feature_name,
                    "timeframe_window": timeframe,
                    "signal_path_role": role,
                    "source_feature": source,
                    "source_sentinel_bar_labels": "|".join(date.strftime("%Y-%m-%d") for date in source_dates),
                    "actual_value": json_safe(value),
                    "actual_value_kind": value_kind,
                    "actual_value_nonfinite": nonfinite,
                    "contract_entry_candidate_at_evaluation": contract_candidate,
                })

            for span in spans.loc[spans["ticker"] == ticker].to_dict("records"):
                window_id = str(span["window_id"])
                start = pd.Timestamp(span["comparison_effective_start"])
                end = pd.Timestamp(span["comparison_effective_end"])
                if not (start <= week <= end):
                    continue
                signal_features = [
                    name for name in active
                    if not FEATURE_META[name][1].startswith("Diagnostic only;")
                ]
                if not signal_features:
                    continue
                next_rows = daily.loc[daily.index > week]
                next_date = next_rows.index[0] if not next_rows.empty else None
                exec_within_window = next_date is not None and next_date.normalize() <= end
                eligible = bool(
                    week in eligible_frame.index
                    and bool(eligible_frame.loc[week, "eligible_before_window_start"])
                    and week >= start
                )
                candidate = contract_candidate and exec_within_window
                actionable = candidate and eligible
                if candidate:
                    contract_candidate_count += 1
                if actionable:
                    actionable_candidate_count += 1
                for strategy_id in STRATEGIES:
                    match = ledger.loc[
                        (ledger["ticker"] == ticker)
                        & (ledger["window_id"] == window_id)
                        & (ledger["strategy_id"] == strategy_id)
                        & (ledger["signal_date"] == eval_date)
                    ]
                    recorded = None if match.empty else str(match.iloc[0]["trade_identity"])
                    signal_rows.append({
                        "ticker": ticker,
                        "window_id": window_id,
                        "strategy_id": strategy_id,
                        "evaluation_date": eval_date,
                        "exposed_signal_path_features": "|".join(signal_features),
                        "contract_entry_candidate": candidate,
                        "pit_eligible_on_raw_rows": eligible,
                        "actionable_candidate_before_position_state": actionable,
                        "existing_ledger_trade_identity_on_date": recorded,
                        "existing_ledger_entry_signal_exposed": recorded is not None,
                        "counterfactual_trade_change_determined": False,
                        "impact_status": "UNRESOLVED_SIGNAL_PATH_EXPOSURE",
                    })

    signal_frame = pd.DataFrame(signal_rows)
    feature_frame = pd.DataFrame(feature_rows)
    if signal_frame.empty:
        raise RuntimeError("NO_SIGNAL_PATH_EVALUATIONS_RECORDED")
    if signal_frame.duplicated(["ticker", "window_id", "strategy_id", "evaluation_date"]).any():
        raise RuntimeError("DUPLICATE_SIGNAL_EVALUATION_ROW")

    direct_trade_frame = ledger.loc[ledger["ticker"].isin(TICKERS)].copy()
    exposed_signal_keys = {
        (row["ticker"], row["window_id"], row["strategy_id"], row["evaluation_date"])
        for row in signal_rows
        if row["existing_ledger_entry_signal_exposed"]
    }
    trade_rows: list[dict[str, Any]] = []
    for row in direct_trade_frame.to_dict("records"):
        signal_date = str(row["signal_date"])
        key = (row["ticker"], row["window_id"], row["strategy_id"], signal_date)
        matching = signal_frame.loc[
            (signal_frame["ticker"] == row["ticker"])
            & (signal_frame["window_id"] == row["window_id"])
            & (signal_frame["strategy_id"] == row["strategy_id"])
            & (signal_frame["evaluation_date"] == signal_date)
        ]
        feature_list = "" if matching.empty else str(matching.iloc[0]["exposed_signal_path_features"])
        trade_rows.append({
            "trade_identity": row["trade_identity"],
            "ticker": row["ticker"],
            "window_id": row["window_id"],
            "strategy_id": row["strategy_id"],
            "signal_date": signal_date,
            "entry_execution_date": row["entry_execution_date"],
            "direct_signal_path_exposure": key in exposed_signal_keys,
            "exposed_signal_path_features": feature_list,
            "estimated_trade_count_at_risk": 1 if key in exposed_signal_keys else 0,
            "actual_trade_identity_change_confirmed": False,
            "impact_status": "POTENTIAL_ENTRY_IDENTITY_EXPOSURE" if key in exposed_signal_keys else "NO_DIRECT_ENTRY_DATE_OVERLAP",
        })
    trade_frame = pd.DataFrame(trade_rows)

    ledger_exposure_count = int(trade_frame["direct_signal_path_exposure"].sum())
    exposed_eval_count = int(len(signal_frame))
    exposed_unique_eval_count = int(signal_frame[["ticker", "evaluation_date"]].drop_duplicates().shape[0])
    diagnostic_nonfinite_count = int(sum(diagnostic_nonfinite_counts.values()))

    sentinels.to_csv(output_dir / "sentinel_rows.csv", index=False, encoding="utf-8-sig")
    feature_frame.to_csv(output_dir / "sentinel_feature_impact.csv", index=False, encoding="utf-8-sig")
    signal_frame.to_csv(output_dir / "sentinel_signal_impact.csv", index=False, encoding="utf-8-sig")
    trade_frame.to_csv(output_dir / "sentinel_trade_impact.csv", index=False, encoding="utf-8-sig")

    impacted_trade_summary = (
        trade_frame.loc[trade_frame["direct_signal_path_exposure"]]
        .groupby(["ticker", "window_id", "strategy_id", "signal_date", "exposed_signal_path_features"], dropna=False)
        .size().reset_index(name="estimated_trade_count")
    )
    candidate_summary = (
        signal_frame.loc[signal_frame["actionable_candidate_before_position_state"]]
        .groupby(["ticker", "window_id", "strategy_id"], dropna=False)
        .size().reset_index(name="actionable_candidate_evaluation_count")
    )

    ledger_sha_after = sha256_file(ledger_path)
    universe_sha_after = sha256_file(universe_path)
    span_sha_after = sha256_file(span_path)
    manifest_sha_after = sha256_file(raw_manifest)
    strategy_hashes_after = {rel: sha256_file(ROOT / rel) for rel in source_paths}
    strategy_changed = [rel for rel in source_paths if strategy_hashes_before[rel] != strategy_hashes_after[rel]]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    checks = {
        "authority_commit_matches_head": head == AUTHORITY_COMMIT,
        "sentinel_ticker_count_10": int(sentinels["ticker"].nunique()) == 10,
        "sentinel_row_count_78": len(sentinels) == 78,
        "universe_changed_0": universe_sha_before == universe_sha_after,
        "trade_ledger_changed_0": ledger_sha_before == ledger_sha_after,
        "effective_span_artifact_changed_0": span_sha_before == span_sha_after,
        "strategy_source_changed_0": not strategy_changed,
        "raw_manifest_changed_0": manifest_sha_before == manifest_sha_after,
        "raw_partition_hash_mismatch_0": raw_diagnostics["raw_partition_hash_error_count"] == 0,
        "market_refetch_0": True,
        "forty_day_recomputation_0": True,
        "full_backtest_rerun_0": True,
        "only_10_affected_tickers_evaluator_replayed": evaluator_call_count > 0,
    }
    verdict = "ETF_36_ZERO_OHLC_SENTINEL_SIGNAL_IMPACT_AUDIT_CHECK_REQUIRED"
    validation = {
        "verdict": verdict,
        "authority_commit": AUTHORITY_COMMIT,
        "current_head": head,
        "scope": {
            "source": "Existing ETF-36 A FAST V2 vs Julia V00 five-window artifacts and local KRX raw partitions",
            "target_tickers": list(TICKERS),
            "strategies": list(STRATEGIES),
            "official_windows": sorted(spans["window_id"].unique().tolist()),
            "targeted_evaluator_calls": evaluator_call_count,
            "unique_exposed_ticker_evaluation_dates": exposed_unique_eval_count,
            "window_strategy_evaluation_rows": exposed_eval_count,
            "candidate_definition": "Frozen entry contract gates plus actual raw ETF-36 date/close/20-session-volume eligibility; position-state suppression is not simulated",
            "signal_count_definition": "Existing trade-ledger entries whose signal date is directly exposed to at least one entry-path feature",
            "trade_count_definition": "Existing trade identities with directly exposed entry signal dates; exposure count, not proven counterfactual change count",
        },
        "counts": {
            "sentinel_ticker_count": int(sentinels["ticker"].nunique()),
            "sentinel_row_count": len(sentinels),
            "sentinel_affected_evaluation_count": exposed_eval_count,
            "sentinel_affected_unique_ticker_evaluation_date_count": exposed_unique_eval_count,
            "sentinel_affected_entry_candidate_count": actionable_candidate_count,
            "sentinel_contract_candidate_count_before_pit_eligibility": contract_candidate_count,
            "sentinel_affected_entry_signal_count": ledger_exposure_count,
            "sentinel_affected_trade_count": ledger_exposure_count,
            "sentinel_confirmed_changed_entry_signal_count": 0,
            "sentinel_confirmed_changed_trade_identity_count": 0,
            "sentinel_actual_change_count_determined": False,
            "estimated_existing_trade_identities_at_risk_minimum": ledger_exposure_count,
            "diagnostic_nonfinite_feature_evaluation_count": diagnostic_nonfinite_count,
            "diagnostic_nonfinite_feature_counts_by_name": diagnostic_nonfinite_counts,
            "nonfinite_value_kind_counts_by_name": nonfinite_kind_counts,
            "signal_path_nonfinite_feature_counts_by_name": signal_path_nonfinite_counts,
        },
        "at_risk_entry_signal_rows": impacted_trade_summary.to_dict("records"),
        "actionable_candidate_evaluation_counts_by_ticker_window_strategy": candidate_summary.to_dict("records"),
        "authority_and_integrity": {
            "universe_sha256_before": universe_sha_before,
            "universe_sha256_after": universe_sha_after,
            "trade_ledger_sha256_before": ledger_sha_before,
            "trade_ledger_sha256_after": ledger_sha_after,
            "effective_span_sha256_before": span_sha_before,
            "effective_span_sha256_after": span_sha_after,
            "raw_manifest_sha256_before": manifest_sha_before,
            "raw_manifest_sha256_after": manifest_sha_after,
            "strategy_source_sha256": strategy_hashes_after,
            "strategy_source_changed_paths": strategy_changed,
            **raw_diagnostics,
        },
        "validation": {
            "checks": checks,
            "passed": all(checks.values()),
            "errors": [name for name, passed in checks.items() if not passed],
            "universe_change_count": 0,
            "trade_ledger_change_count": 0,
            "strategy_source_change_count": len(strategy_changed),
            "market_refetch_count": 0,
            "forty_day_recomputation_count": 0,
            "full_backtest_rerun_count": 0,
            "targeted_evaluator_replay_ticker_count": len(TICKERS),
            "raw_rows_modified": False,
            "strategy_rules_modified": False,
        },
        "interpretation": {
            "signal_path_exposure_found": True,
            "why_check_required": (
                "Zero low bars fall inside features consumed by A FAST monthly permission, weekly trigger, "
                "daily risk, Pattern A stage/score, and the raw 20-session volume eligibility gate. "
                "Existing ledger entries overlap this exposure. No canonical counterfactual OHLCV treatment "
                "is authorized by the source contract, and this audit does not alter raw rows or replay an adjusted backtest."
            ),
            "certification_eligible": False,
            "original_simple_backtest_certified_pass": False,
            "no_automatic_correction_or_rerun": True,
        },
    }
    (output_dir / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, default=json_safe) + "\n",
        encoding="utf-8",
    )

    exposed_features = feature_frame.loc[
        ~feature_frame["signal_path_role"].str.startswith("Diagnostic only;")
    ]
    feature_summary = (
        exposed_features.groupby(["ticker", "feature_name", "signal_path_role"], dropna=False)
        .agg(evaluation_count=("evaluation_date", "nunique"),
             first_evaluation_date=("evaluation_date", "min"),
             last_evaluation_date=("evaluation_date", "max"))
        .reset_index()
    )
    positive_infinity_count = sum(
        kinds.get("POSITIVE_INFINITY", 0) for kinds in nonfinite_kind_counts.values()
    )
    nan_count = sum(kinds.get("NAN", 0) for kinds in nonfinite_kind_counts.values())
    lines = [
        "# ETF-36 Zero-OHLC Sentinel Signal Impact Audit V01",
        "",
        f"Verdict: {verdict}",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 반사실 재계산으로 확정된 수정 거래 없음; 실제 변경 수는 미판정 |",
        f"| MAJOR | {ledger_exposure_count} | 신호 경로에 직접 노출된 기존 거래 ID 수 (변경 확정 수가 아닌 위험 노출 수) |",
        f"| MINOR | {diagnostic_nonfinite_count} | 신호 결정에 쓰이지 않는 non-finite 진단 feature 평가 건수 |",
        "",
        "## 판정 근거",
        "",
        f"원시 sentinel {len(sentinels)}행 / {sentinels['ticker'].nunique()}개 ETF가 completed weekly/monthly bars로 집계됐어. 전체 5-window 백테스트는 재실행하지 않았고, 영향 가능 기간의 10개 ETF evaluator만 {evaluator_call_count:,}회 평가했어. 거래 원장은 기존 기록 그대로 읽어 대조했어.",
        "",
        f"- sentinel_affected_evaluation_count: {exposed_eval_count:,} (ticker × window × strategy × evaluation date)",
        f"- 고유 ticker × evaluation date: {exposed_unique_eval_count:,}",
        f"- sentinel_affected_entry_candidate_count: {actionable_candidate_count:,} (고정 entry gate 및 실제 PIT 자격 통과; position 상태는 제외)",
        f"- entry contract만 통과한 후보 평가: {contract_candidate_count:,}",
        f"- sentinel_affected_entry_signal_count: {ledger_exposure_count} (기존 ledger signal date와 입력 노출 날짜 일치)",
        f"- sentinel_affected_trade_count: {ledger_exposure_count}개 trade identity 직접 노출. 실제로 바뀐 identity 수는 반사실 평가 없이는 확정할 수 없어.",
        f"- 진단값: distance-from-low 계열 {positive_infinity_count:,}건은 +Inf, pivot_low_slope {nan_count:,}건은 NaN. 이 진단 feature들은 entry contract에 사용되지 않아.",
        "",
        "A FAST는 월봉 range_position_24m, 주봉 higher_weekly_low_count_13w, 일봉 recent_5d_max_gap_abs_pct / atr_14_pct를 entry gate에서 읽어. Pattern A entry stage와 score도 36개월 저점 기반 range_position / range_36m을 읽고, ETF-36 자격 필터는 최근 20회 volume 평균을 사용해. 영향 경로가 진단 전용 feature에 한정되지 않아.",
        "",
        "### 직접 노출된 기존 신호/거래",
        "",
        "| 종목 | Window | Strategy | Evaluation / signal date | 노출 feature | 추정 at-risk trade |",
        "|---|---|---|---|---|---:|",
    ]
    for row in impacted_trade_summary.to_dict("records"):
        lines.append(
            f"| {row['ticker']} | {row['window_id']} | {row['strategy_id']} | {row['signal_date']} | "
            f"{row['exposed_signal_path_features']} | {row['estimated_trade_count']} |"
        )
    lines.extend([
        "",
        "위 행은 sentinel이 포함된 입력을 소비한 기존 ledger 진입 신호의 노출 목록이야. 정제된 데이터에서 해당 거래가 실제로 달라졌다고 단정하지는 않아. 무거래 행의 canonical 대체 OHLCV 규칙이 정해지지 않았고 원시 행 변경 및 자동 재실행이 금지돼 있어, verdict는 CHECK_REQUIRED야. 기존 단순 백테스트를 certified PASS로 승격할 수 없어.",
        "",
        "### Feature exposure 요약",
        "",
        "| Ticker | Feature | Role | Affected evaluation dates | First | Last |",
        "|---|---|---|---:|---|---|",
    ])
    for row in feature_summary.to_dict("records"):
        lines.append(
            f"| {row['ticker']} | {row['feature_name']} | {row['signal_path_role']} | "
            f"{row['evaluation_count']} | {row['first_evaluation_date']} | {row['last_evaluation_date']} |"
        )
    lines.extend([
        "",
        "진단 전용 distance_from_low 계열은 sentinel 포함 rolling low가 0이라 +Inf가 되고, pivot_low_slope는 0 pivot 평균 분모에서 NaN이 발생했어. A FAST entry contract 및 Pattern A 점수/stage는 이 feature들을 읽지 않아. pivot_low_slope와 range_position_52w는 해당 전략 판정에 사용되지 않아. 실제 비유한값 종류와 정확한 evaluation date는 sentinel_feature_impact.csv에서 확인할 수 있어.",
        "",
        "## 검증",
        "",
        f"- ticker / row: {sentinels['ticker'].nunique()} / {len(sentinels)}",
        "- universe 변경: 0; universe SHA 유지",
        f"- trade ledger 변경: 0; SHA {ledger_sha_before} 유지",
        f"- strategy source 변경: {len(strategy_changed)}; KRX market refetch 0; 40D 재계산 0; 전체 ETF-36 5-window backtest 재실행 0",
        f"- 영향 ETF evaluator replay: {len(TICKERS)}개만, {evaluator_call_count:,}회",
        f"- 검증 checks: {'PASS' if all(checks.values()) else 'FAIL'} ({', '.join(name for name, value in checks.items() if not value) or '오류 없음'})",
        "",
        "## 산출물",
        "",
        "- sentinel_rows.csv: sentinel별 weekly/monthly bar 소속 및 bar 내 양수 OHLC 행 수",
        "- sentinel_feature_impact.csv: 영향을 받은 evaluation date별 입력 feature, 실제 값, non-finite 여부",
        "- sentinel_signal_impact.csv: window/strategy별 evaluation, 후보 판정, PIT 자격, 원 ledger signal 교차",
        "- sentinel_trade_impact.csv: 기존 ledger 거래의 직접 entry-date 노출 여부",
        "- validation.json: count, SHA, 실행 제한 및 verdict",
        "",
    ])
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return validation


def main() -> int:
    # Existing resampling/pct_change code emits known dependency deprecations
    # during this read-only replay; they do not indicate changed calculations.
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    daily_by_ticker, calendar_dates, raw_diagnostics = load_target_daily()
    result = audit(daily_by_ticker, calendar_dates, raw_diagnostics)
    print(json.dumps({
        "verdict": result["verdict"],
        "counts": result["counts"],
        "validation_passed": result["validation"]["passed"],
        "output_dir": str(OUTPUT_REL),
    }, ensure_ascii=False, indent=2))
    return 0 if result["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
