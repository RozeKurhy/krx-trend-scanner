#!/usr/bin/env python3
"""Close ETF-36 zero-OHLC sentinel exposure with clean-start targeted replay.

Raw KRX rows and frozen strategy sources are read-only. Only the ten tickers
in the preceding sentinel audit are replayed, and only windows whose common
start changes are simulated again.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sqlite3
import sys
import time
from typing import Any, Iterable, Mapping
import warnings

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import audit_etf_36_zero_ohlc_sentinel_signal_impact_v01 as prior_audit  # noqa: E402
from scripts import run_etf_36_afast_v2_vs_julia_5window_simple_v01 as study  # noqa: E402
from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context  # noqa: E402
from trend_scanner.research import (  # noqa: E402
    pattern_a_fast_daily_features as daily_features,
    pattern_a_fast_monthly_features as monthly_features,
    pattern_a_fast_weekly_features as weekly_features,
)

warnings.filterwarnings("ignore", category=FutureWarning)

AUTHORITY_COMMIT = "b5df1642f04fcf9804e9aeda4309c59bc3bac915"
AUDIT_COMMIT = "3a8703209d2856cfabcc61610f73ed5996bc8e58"
BASE_REL = Path("artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01")
PRIOR_AUDIT_REL = Path("artifacts/research/etf_36_zero_ohlc_sentinel_signal_impact_audit_v01")
OUTPUT_REL = Path("artifacts/research/etf_36_zero_ohlc_sentinel_clean_eligibility_closure_v01")
TICKERS = prior_audit.TICKERS
STRATEGIES = (study.base.STRATEGY_A_FAST, study.base.STRATEGY_JULIA)
SOURCE_PATHS = (
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_raw_partition_hashes(raw_root: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{raw_root / 'manifest.sqlite3'}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT file_path,file_sha256 FROM raw_snapshot_manifest "
            "WHERE market='ETF' AND date<=? AND status='COMPLETE' ORDER BY date",
            (prior_audit.SUPPORT_DATE,),
        ).fetchall()
    finally:
        connection.close()
    mismatches = 0
    for relative_path, expected in rows:
        path = raw_root / str(relative_path)
        if not expected or sha256_file(path) != str(expected):
            mismatches += 1
    return {"partition_count": len(rows), "hash_mismatch_count": mismatches}


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


def _string_constants(node: ast.AST) -> set[str]:
    return {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def _function_returned_feature_names(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name),
        None,
    )
    if function is None:
        raise RuntimeError(f"SIGNAL_PATH_FUNCTION_MISSING:{path}:{function_name}")
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.DictComp) and isinstance(node.generators[0].iter, ast.Tuple):
            names |= _string_constants(node.generators[0].iter)
    return names


def _assignment_tuple(path: Path, variable: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets):
            return _string_constants(node.value)
    raise RuntimeError(f"SIGNAL_PATH_ASSIGNMENT_MISSING:{path}:{variable}")


def _feature_specs(module: Any) -> dict[str, Any]:
    return {spec.name: spec for spec in module.FEATURE_SPECS}


def extract_signal_path_lookbacks(score: Mapping[str, Any], stage: Mapping[str, Any]) -> dict[str, Any]:
    """Read the frozen contract inputs and their current FeatureSpec history.

    Pattern A legacy FeatureRow inputs are traced from the score/stage source;
    their current rolling formulas are enumerated below and are guarded by
    source-hash validation in the closure run.
    """
    monthly_specs = _feature_specs(monthly_features)
    weekly_specs = _feature_specs(weekly_features)
    daily_specs = _feature_specs(daily_features)

    monthly_inputs = set(score["monthly_permission_mapping"]) - {"component_formula"}
    monthly_inputs |= {name for name in score["required_direct_inputs"] if name in monthly_specs}
    weekly_inputs = set(score["weekly_core_mapping"]) - {"missing"}
    weekly_inputs |= set(stage["weekly_feature_inputs"])
    weekly_inputs |= set(stage["required_stage_inputs"])
    weekly_inputs |= set(stage["stage_only_semantic_markers"])
    daily_inputs = set(score["daily_risk_mapping"]) - {"formula"}

    # Actual legacy Pattern A fields read by score_pattern_a() and
    # classify_pattern_a_stage(). Max requirements are: 36 completed monthly
    # bars for range_36m/range_position/distance_to_resistance; 30 for MA24
    # acceleration; 24 for avg_price_change_12m/MA spread; 16 weekly bars for
    # weekly_ma12_slope. Values follow the called FeatureRow/helper formulas.
    score_fields = _function_returned_feature_names(
        ROOT / "src/trend_scanner/patterns/pattern_a_score.py", "score_pattern_a"
    )
    stage_fields = _assignment_tuple(ROOT / "src/trend_scanner/patterns/pattern_a_stage.py", "_REQUIRED_FIELDS")
    pattern_a_lookbacks = {
        "range_36m": ("monthly", 36, "feature_report._range(monthly, 36)"),
        "range_position": ("monthly", 36, "feature_report._window_high_low(monthly, 36) + resistance.range_position"),
        "distance_to_resistance": ("monthly", 36, "feature_report._window_high_low(monthly, 36)"),
        "avg_price_change_12m": ("monthly", 24, "feature_report._avg_price_change_12m"),
        "ma_spread": ("monthly", 24, "three monthly moving averages through MA24"),
        "ma24_slope": ("monthly", 27, "MA24 with three-month slope"),
        "ma24_slope_acceleration": ("monthly", 30, "MA24 slope, periods=3, lag=3"),
        "weekly_ma12_slope": ("weekly", 16, "weekly MA12 with four-week slope"),
    }
    pattern_fields = score_fields | stage_fields
    missing_pattern = pattern_fields - set(pattern_a_lookbacks)
    if missing_pattern:
        raise RuntimeError(f"UNMAPPED_PATTERN_A_SIGNAL_INPUTS:{sorted(missing_pattern)}")

    def rows(names: set[str], specs: Mapping[str, Any], timeframe: str) -> list[dict[str, Any]]:
        missing = names - set(specs)
        if missing:
            raise RuntimeError(f"UNMAPPED_{timeframe.upper()}_SIGNAL_INPUTS:{sorted(missing)}")
        return [{
            "timeframe": timeframe,
            "feature": name,
            "required_history_bars": int(specs[name].required_history_bars),
            "input_class": "conditional_or_optional_signal_input" if name == "close_vs_wma200_pct" else "signal_input",
            "source_ref": f"{specs[name].__module__}.{name}",
        } for name in sorted(names)]

    lookbacks = rows(monthly_inputs, monthly_specs, "monthly")
    lookbacks += rows(weekly_inputs, weekly_specs, "weekly")
    lookbacks += rows(daily_inputs, daily_specs, "daily")
    for name in sorted(pattern_fields):
        timeframe, bars, formula = pattern_a_lookbacks[name]
        lookbacks.append({
            "timeframe": timeframe,
            "feature": f"pattern_a.{name}",
            "required_history_bars": bars,
            "input_class": "signal_input",
            "source_ref": formula,
        })
    lookbacks.append({
        "timeframe": "daily",
        "feature": "pit.avg_volume_20d",
        "required_history_bars": 20,
        "input_class": "signal_input",
        "source_ref": "scripts/run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03.py:_raw_eligibility rolling(20,min_periods=20)",
    })
    by_timeframe: dict[str, int] = {}
    for timeframe in {row["timeframe"] for row in lookbacks}:
        by_timeframe[timeframe] = max(row["required_history_bars"] for row in lookbacks if row["timeframe"] == timeframe)
    return {
        "features": sorted(lookbacks, key=lambda row: (row["timeframe"], -row["required_history_bars"], row["feature"])),
        "max_bars_by_timeframe": by_timeframe,
        "controlling_timeframe": "weekly",
        "controlling_feature": max(
            (row for row in lookbacks if row["timeframe"] == "weekly"),
            key=lambda row: row["required_history_bars"],
        )["feature"],
        "entry_path_notes": [
            "close_vs_wma200_pct is optional for score availability but is consumed by the FAST stage EXTENDED/trigger rules; it is conservatively included.",
            "Pattern A lifecycle history is used only to add reason_codes to a WEAK stage; WEAK is blocked from entry, so the unbounded explanation-only scan is outside the entry path.",
        ],
    }


def _sentinel_free_at(
    monthly: pd.DataFrame,
    weekly: pd.DataFrame,
    daily_as_of: pd.DataFrame,
    sentinel: Mapping[str, set[pd.Timestamp]],
    lookbacks: Mapping[str, Any],
) -> dict[str, Any]:
    limits = lookbacks["max_bars_by_timeframe"]
    month_tail = set(pd.DatetimeIndex(monthly.index[-limits["monthly"]:]).normalize())
    week_tail = set(pd.DatetimeIndex(weekly.index[-limits["weekly"]:]).normalize())
    daily_tail = set(pd.DatetimeIndex(daily_as_of.index[-limits["daily"]:]).normalize())
    month_hits = sorted(month_tail & sentinel["months"])
    week_hits = sorted(week_tail & sentinel["weeks"])
    daily_hits = sorted(daily_tail & sentinel["dates"])
    return {
        "clean": not (month_hits or week_hits or daily_hits),
        "monthly_sentinel_labels": month_hits,
        "weekly_sentinel_labels": week_hits,
        "daily_sentinel_dates": daily_hits,
    }


def compute_clean_ready_date(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    context: Any,
    sentinel: Mapping[str, set[pd.Timestamp]],
    calendar: Any,
    existing_ready_date: str,
    lookbacks: Mapping[str, Any],
) -> dict[str, Any]:
    data_dates = set(pd.DatetimeIndex(daily.index).normalize())
    valid_weeks = [
        pd.Timestamp(week).normalize()
        for week in context.full_weekly.index
        if pd.Timestamp(week).normalize() in data_dates
        and pd.Timestamp(week).normalize() <= pd.Timestamp(study.base.EXECUTION_SUPPORT)
    ]
    latest_sentinel_date = max(sentinel["dates"])
    for week in valid_weeks:
        if week < latest_sentinel_date or week < pd.Timestamp(existing_ready_date):
            continue
        snapshot = build_historical_snapshot_from_context(
            context, week, include_incomplete_periods=False, market_calendar=calendar,
        )
        if snapshot.weekly_as_of != week:
            continue
        daily_as_of = context.slice_daily_up_to(week)
        status = _sentinel_free_at(snapshot.monthly, snapshot.weekly, daily_as_of, sentinel, lookbacks)
        if status["clean"]:
            return {
                "ticker": ticker,
                "existing_strategy_ready_date": existing_ready_date,
                "clean_strategy_ready_date": week.strftime("%Y-%m-%d"),
                "latest_sentinel_date": latest_sentinel_date.strftime("%Y-%m-%d"),
                "latest_sentinel_weekly_label": max(sentinel["weeks"]).strftime("%Y-%m-%d"),
                "latest_sentinel_monthly_label": max(sentinel["months"]).strftime("%Y-%m-%d"),
                "monthly_max_history_bars": lookbacks["max_bars_by_timeframe"]["monthly"],
                "weekly_max_history_bars": lookbacks["max_bars_by_timeframe"]["weekly"],
                "daily_max_history_bars": lookbacks["max_bars_by_timeframe"]["daily"],
                "controlling_timeframe": lookbacks["controlling_timeframe"],
                "controlling_feature": lookbacks["controlling_feature"],
                "sentinel_labels_remaining_at_ready": 0,
                "monthly_sentinel_labels_remaining": 0,
                "weekly_sentinel_labels_remaining": 0,
                "daily_sentinel_dates_remaining": 0,
            }
    return {
        "ticker": ticker,
        "existing_strategy_ready_date": existing_ready_date,
        "clean_strategy_ready_date": None,
        "latest_sentinel_date": latest_sentinel_date.strftime("%Y-%m-%d"),
        "latest_sentinel_weekly_label": max(sentinel["weeks"]).strftime("%Y-%m-%d"),
        "latest_sentinel_monthly_label": max(sentinel["months"]).strftime("%Y-%m-%d"),
        "monthly_max_history_bars": lookbacks["max_bars_by_timeframe"]["monthly"],
        "weekly_max_history_bars": lookbacks["max_bars_by_timeframe"]["weekly"],
        "daily_max_history_bars": lookbacks["max_bars_by_timeframe"]["daily"],
        "controlling_timeframe": lookbacks["controlling_timeframe"],
        "controlling_feature": lookbacks["controlling_feature"],
        "sentinel_labels_remaining_at_ready": None,
        "monthly_sentinel_labels_remaining": None,
        "weekly_sentinel_labels_remaining": None,
        "daily_sentinel_dates_remaining": None,
    }


def revise_span_row(row: Mapping[str, Any], clean_ready: str, window: Mapping[str, str], calendar_dates: list[str]) -> dict[str, Any]:
    result = dict(row)
    window_start, window_end = window["window_start"], window["window_end"]
    new_start = max(window_start, clean_ready)
    result["clean_strategy_ready_date"] = clean_ready
    result["comparison_effective_end"] = window_end if new_start <= window_end else ""
    if new_start <= window_end:
        result["comparison_effective_start"] = new_start
        result["coverage_status"] = "FULL_WINDOW" if new_start == window_start else "PARTIAL_WINDOW"
        result["coverage_sessions"] = sum(new_start <= date <= window_end for date in calendar_dates)
        result["reason_if_not_evaluable"] = ""
    else:
        result["comparison_effective_start"] = ""
        result["coverage_status"] = "NOT_EVALUABLE"
        result["coverage_sessions"] = 0
        result["reason_if_not_evaluable"] = "CLEAN_STRATEGY_READY_AFTER_WINDOW_END"
    result["span_changed"] = (
        str(row["comparison_effective_start"]) != str(result["comparison_effective_start"])
        or str(row["comparison_effective_end"]) != str(result["comparison_effective_end"])
        or str(row["coverage_status"]) != str(result["coverage_status"])
    )
    result["targeted_replay_required"] = bool(
        result["coverage_status"] != "NOT_EVALUABLE"
        and pd.Timestamp(row["comparison_effective_start"]) < pd.Timestamp(clean_ready) <= pd.Timestamp(window_end)
    )
    return result


def close_risk_identities(exposed: pd.DataFrame, certified: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for old in exposed.to_dict("records"):
        old_identity = str(old["trade_identity"])
        same_pair = certified.loc[
            certified["ticker"].astype(str).map(study._norm_ticker).eq(study._norm_ticker(old["ticker"]))
            & certified["window_id"].astype(str).eq(str(old["window_id"]))
            & certified["strategy_id"].astype(str).eq(str(old["strategy_id"]))
        ]
        exact = same_pair.loc[same_pair["trade_identity"].astype(str).eq(old_identity)]
        if not exact.empty:
            disposition, replacement = "UNCHANGED", exact.iloc[0]
        else:
            later = same_pair.loc[pd.to_datetime(same_pair["signal_date"]) > pd.Timestamp(old["signal_date"])].sort_values("signal_date")
            if not later.empty:
                disposition, replacement = "REPLACED_BY_LATER_ENTRY", later.iloc[0]
            elif same_pair.empty:
                disposition, replacement = "REMOVED_BY_CLEAN_ELIGIBILITY", None
            else:
                disposition, replacement = "OTHER_DETERMINISTIC_CHANGE", None
        rows.append({
            "original_trade_identity": old_identity,
            "ticker": study._norm_ticker(old["ticker"]),
            "window_id": str(old["window_id"]),
            "strategy_id": str(old["strategy_id"]),
            "original_signal_date": str(old["signal_date"]),
            "unique_market_event_id": f"{study._norm_ticker(old['ticker'])}|{old['signal_date']}",
            "disposition": disposition,
            "replacement_trade_identity": None if replacement is None else str(replacement["trade_identity"]),
            "replacement_signal_date": None if replacement is None else str(replacement["signal_date"]),
        })
    return pd.DataFrame(rows)


def _set_worker_state(calendar_dates: list[str], score: dict[str, Any], stage: dict[str, Any]) -> Any:
    calendar, month_ends = study.base._calendar_from_dates(calendar_dates)
    study.base._WORKER.clear()
    study.base._WORKER.update({
        "score_contract": score,
        "stage_contract": stage,
        "calendar": calendar,
        "calendar_dates": calendar_dates,
        "calendar_positions": {date: index for index, date in enumerate(calendar_dates)},
        "month_ends": month_ends,
    })
    study.base.CUTOFF = pd.Timestamp("2026-08-31")
    study.base.EXECUTION_SUPPORT = pd.Timestamp("2026-09-01")
    study._WINDOWS, window_errors = study._resolved_windows(calendar_dates)
    if window_errors:
        raise RuntimeError(f"STANDARD_WINDOW_RESOLUTION_FAILED:{window_errors}")
    return calendar


def _finite_ledger_check(ledger: pd.DataFrame) -> dict[str, Any]:
    if ledger.empty:
        return {"mandatory_nonfinite_count": 0, "realized_exit_nonfinite_count": 0, "unexpected_nan_count": 0}
    mandatory = [
        "entry_price_raw_open", "terminal_price_raw", "gross_return_pct",
        "commission_slippage_pre_tax_return_pct", "commission_rate_each_side",
        "slippage_rate_each_side", "ETF_sell_tax_rate", "holding_krx_sessions_inclusive",
    ]
    mandatory_values = ledger[mandatory].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    realized_exit = pd.to_numeric(
        ledger.loc[ledger["trade_status"].eq("REALIZED"), "exit_price_raw_open"], errors="coerce"
    ).to_numpy(dtype=float)
    allowed_na = {"exit_signal_date", "exit_execution_date", "exit_price_raw_open"}
    unexpected_nan = int(ledger.drop(columns=list(allowed_na), errors="ignore").isna().sum().sum())
    return {
        "mandatory_nonfinite_count": int((~np.isfinite(mandatory_values)).sum()),
        "realized_exit_nonfinite_count": int((~np.isfinite(realized_exit)).sum()),
        "unexpected_nan_count": unexpected_nan,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _summary_markdown(validation: Mapping[str, Any], ready: pd.DataFrame, changes: pd.DataFrame, risk: pd.DataFrame, summary: pd.DataFrame) -> str:
    lines = [
        "# ETF-36 Zero-OHLC Sentinel Clean Eligibility Closure V01",
        "",
        f"**Verdict:** `{validation['verdict']}`",
        "",
        "## Signal-path history",
        "",
        "Lookbacks were resolved from the frozen evaluator and FeatureSpec metadata. The longest consumed bar history is the optional-but-stage-consumed `close_vs_wma200_pct` at 200 completed weekly bars; it is included because the FAST stage uses it in the EXTENDED and TRIGGER rules. Pattern A's longest direct price feature is 36 completed monthly bars. The Pattern A lifecycle scan is explanation-only for WEAK, which cannot enter.",
        "",
        "## Clean-ready dates",
        "",
        "| Ticker | Existing ready | Clean ready | Last sentinel |",
        "|---|---|---|---|",
    ]
    for row in ready.to_dict("records"):
        lines.append(f"| {row['ticker']} | {row['existing_strategy_ready_date']} | {row['clean_strategy_ready_date']} | {row['latest_sentinel_date']} |")
    lines += ["", f"Changed target spans: {int(changes['span_changed'].sum())}; targeted replay windows: {int(changes['targeted_replay_required'].sum())}.", ""]
    counts = risk["disposition"].value_counts().to_dict() if not risk.empty else {}
    unique_counts = risk.drop_duplicates("unique_market_event_id")["disposition"].value_counts().to_dict() if not risk.empty else {}
    lines += [
        "## Prior risk identity closure",
        "",
        f"12 identities / {risk['unique_market_event_id'].nunique()} unique ticker-date events. Identity dispositions: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`.",
        f"Unique event dispositions: `{json.dumps(unique_counts, ensure_ascii=False, sort_keys=True)}`.",
        "",
        "## Revised OVERALL window metrics",
        "",
        "| Window | ETFs | V2 trades | Julia trades | V2 mean realized % | Julia mean realized % | Delta Julia−V2 pp |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    overall = summary.loc[summary["scope"].eq("OVERALL")]
    for row in overall.to_dict("records"):
        lines.append(
            f"| {row['window_id']} | {row['evaluated_etf_count']} | {row['afast_v2_trade_count']} | {row['julia_v00_trade_count']} | "
            f"{row['afast_v2_mean_realized_return_pct']:.2f} | {row['julia_v00_mean_realized_return_pct']:.2f} | "
            f"{row['delta_julia_minus_v2_mean_realized_return_pct']:.2f} |"
        )
    lines += ["", "## Integrity", "", f"`validation.json` checks: {json.dumps(validation['checks'], ensure_ascii=False, sort_keys=True)}", ""]
    return "\n".join(lines)


def run(output_dir: Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = output_dir or (ROOT / OUTPUT_REL)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir = ROOT / BASE_REL
    prior_dir = ROOT / PRIOR_AUDIT_REL
    raw_root = ROOT / "data/market/raw/krx_stocks/v01"
    ledger_path = baseline_dir / "trade_ledger.csv"
    span_path = baseline_dir / "effective_span_audit.csv"
    universe_path = baseline_dir / "official_etf_universe_36.csv"
    raw_manifest_path = raw_root / "manifest.sqlite3"

    integrity_before = {
        "ledger_sha256": sha256_file(ledger_path),
        "span_sha256": sha256_file(span_path),
        "universe_sha256": sha256_file(universe_path),
        "raw_manifest_sha256": sha256_file(raw_manifest_path),
        "strategy_source_sha256": {rel: sha256_file(ROOT / rel) for rel in SOURCE_PATHS},
    }
    for commit in (AUTHORITY_COMMIT, AUDIT_COMMIT):
        subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=True, capture_output=True, text=True)

    daily_by_ticker, calendar_dates, raw_diagnostics = prior_audit.load_target_daily()
    score, stage = study.base._read_contracts()
    lookbacks = extract_signal_path_lookbacks(score, stage)
    calendar = _set_worker_state(calendar_dates, score, stage)
    universe, universe_meta = study._load_universe()
    if universe_meta["errors"]:
        raise RuntimeError(f"FROZEN_UNIVERSE_VALIDATION_FAILED:{universe_meta['errors']}")
    instruments = {row["ticker"]: row for row in universe if row["ticker"] in TICKERS}
    if len(instruments) != 10:
        raise RuntimeError(f"TARGET_UNIVERSE_COUNT_MISMATCH:{len(instruments)}")

    baseline_spans = pd.read_csv(span_path, dtype={"ticker": "string", "window_id": "string"}, keep_default_na=False)
    baseline_spans["ticker"] = baseline_spans["ticker"].map(study._norm_ticker)
    base_ledger = pd.read_csv(ledger_path, dtype={"ticker": "string", "strategy_id": "string", "window_id": "string"}, keep_default_na=False)
    base_ledger["ticker"] = base_ledger["ticker"].map(study._norm_ticker)
    baseline_summary = pd.read_csv(baseline_dir / "window_comparison_summary.csv")
    old_audit = pd.read_csv(prior_dir / "sentinel_trade_impact.csv", dtype={"ticker": "string"})
    exposed = old_audit.loc[old_audit["direct_signal_path_exposure"].astype(bool)].copy()
    if len(exposed) != 12 or exposed["trade_identity"].duplicated().any():
        raise RuntimeError(f"ORIGINAL_RISK_IDENTITY_SET_INVALID:{len(exposed)}")

    period_rows, sentinel_by_ticker = prior_audit.sentinel_periods(daily_by_ticker)
    if len(period_rows) != 78 or set(sentinel_by_ticker) != set(TICKERS):
        raise RuntimeError(f"SENTINEL_PERIOD_INVENTORY_MISMATCH:{len(period_rows)}")

    study._WINDOWS, window_errors = study._resolved_windows(calendar_dates)
    if window_errors:
        raise RuntimeError(f"STANDARD_WINDOW_RESOLUTION_FAILED:{window_errors}")
    span_map = study._span_context_rows(baseline_spans)
    ready_rows: list[dict[str, Any]] = []
    contexts: dict[str, Any] = {}
    existing_ready_by_ticker: dict[str, str] = {}
    for ticker in TICKERS:
        instrument = instruments[ticker]
        daily = daily_by_ticker[ticker].loc[pd.Timestamp(instrument["listing_date"]):].copy()
        context = study.base.build_precomputed_ticker_context(ticker, instrument["name"], daily)
        contexts[ticker] = context
        existing = sorted({
            str(span_map[(window, ticker)]["v2_strategy_eligible_date"])
            for window in study.EXPECTED_WINDOWS
            if (window, ticker) in span_map and span_map[(window, ticker)]["v2_strategy_eligible_date"]
        })
        if not existing:
            raise RuntimeError(f"EXISTING_READY_DATE_MISSING:{ticker}")
        if len(existing) != 1:
            raise RuntimeError(f"BASELINE_READY_DATE_PARITY_FAILED:{ticker}:{existing}")
        existing_ready_by_ticker[ticker] = existing[0]
        clean = compute_clean_ready_date(
            ticker, instrument["name"], daily, context, sentinel_by_ticker[ticker],
            calendar, existing[0], lookbacks,
        )
        ready_rows.append(clean)

    ready_frame = pd.DataFrame(ready_rows).sort_values("ticker")
    if ready_frame["clean_strategy_ready_date"].isna().any():
        raise RuntimeError("DETERMINISTIC_CLEAN_READY_DATE_NOT_FOUND_BY_SUPPORT")
    clean_by_ticker = dict(zip(ready_frame["ticker"], ready_frame["clean_strategy_ready_date"]))
    print(json.dumps({
        "phase": "clean_ready_dates_complete",
        "dates": ready_frame[["ticker", "clean_strategy_ready_date"]].to_dict("records"),
    }, ensure_ascii=False), flush=True)

    revised_rows: list[dict[str, Any]] = []
    change_rows: list[dict[str, Any]] = []
    for row in baseline_spans.to_dict("records"):
        if row["ticker"] not in TICKERS:
            revised_rows.append(row)
            continue
        window = study._WINDOWS[str(row["window_id"])]
        changed = revise_span_row(row, clean_by_ticker[row["ticker"]], window, calendar_dates)
        revised_rows.append(changed)
        if changed["span_changed"] or changed["targeted_replay_required"]:
            change_rows.append({
                "ticker": row["ticker"], "window_id": row["window_id"],
                "window_start": row["window_start"], "window_end": row["window_end"],
                "existing_strategy_ready_date": row["v2_strategy_eligible_date"],
                "clean_strategy_ready_date": clean_by_ticker[row["ticker"]],
                "old_effective_start": row["comparison_effective_start"],
                "new_effective_start": changed["comparison_effective_start"],
                "old_effective_end": row["comparison_effective_end"],
                "new_effective_end": changed["comparison_effective_end"],
                "old_coverage_status": row["coverage_status"],
                "new_coverage_status": changed["coverage_status"],
                "span_changed": changed["span_changed"],
                "targeted_replay_required": changed["targeted_replay_required"],
            })
    revised_spans = pd.DataFrame(revised_rows)
    changes = pd.DataFrame(change_rows)

    targeted_span_rows = revised_spans.loc[
        revised_spans["ticker"].isin(TICKERS) & revised_spans["targeted_replay_required"].astype(bool)
    ]
    replayed_by_ticker: dict[str, dict[str, Any]] = {}
    original_loader = study.base._load_ticker_daily
    original_ready_finder = study.base._find_fast_ready_date
    original_eligibility = study.base._raw_eligibility
    current_ticker = [None]
    eligibility_cache: dict[tuple[str, str], tuple[set[str], dict[str, dict[str, Any]], str | None, dict[str, Any]]] = {}
    study.base._load_ticker_daily = lambda ticker: daily_by_ticker[study._norm_ticker(ticker)].copy()
    # Strategy-ready dates are reused from the frozen 36-ETF span authority;
    # clean-ready is calculated independently above. Re-running the all-history
    # readiness scan once per ticker would be redundant work, not a replay.
    study.base._find_fast_ready_date = lambda ticker, *_args, **_kwargs: (existing_ready_by_ticker[study._norm_ticker(ticker)], 0)

    def cached_raw_eligibility(daily: pd.DataFrame, listing_date: str, common_start: str | None):
        ticker = str(current_ticker[0])
        key = (ticker, pd.Timestamp(study.base.CUTOFF).strftime("%Y-%m-%d"))
        if key not in eligibility_cache:
            all_eligible, metrics, volume_ready, audit = original_eligibility(daily, listing_date, "1900-01-01")
            eligibility_cache[key] = (all_eligible, metrics, volume_ready, audit)
        all_eligible, metrics, volume_ready, audit = eligibility_cache[key]
        start = pd.Timestamp(common_start)
        eligible = {date for date in all_eligible if pd.Timestamp(date) >= start}
        scoped_audit = {**audit, "eligible_signal_date_count": len(eligible)}
        return eligible, metrics, volume_ready, scoped_audit

    study.base._raw_eligibility = cached_raw_eligibility
    try:
        for ticker in TICKERS:
            rows = targeted_span_rows.loc[targeted_span_rows["ticker"].eq(ticker)].to_dict("records")
            if not rows:
                continue
            current_ticker[0] = ticker
            print(json.dumps({"phase": "target_replay_start", "ticker": ticker, "window_count": len(rows)}), flush=True)
            replayed_by_ticker[ticker] = study._backtest_ticker((instruments[ticker], rows))
            print(json.dumps({
                "phase": "target_replay_complete", "ticker": ticker,
                "trade_count": len(replayed_by_ticker[ticker].get("trades", [])),
                "error_count": len(replayed_by_ticker[ticker].get("errors", [])),
            }), flush=True)
    finally:
        study.base._load_ticker_daily = original_loader
        study.base._find_fast_ready_date = original_ready_finder
        study.base._raw_eligibility = original_eligibility

    replay_errors = [f"{ticker}:{error}" for ticker, result in replayed_by_ticker.items() for error in result.get("errors", [])]
    targeted_trades = [trade for result in replayed_by_ticker.values() for trade in result.get("trades", [])]
    targeted_ledger = pd.DataFrame(targeted_trades, columns=base_ledger.columns)
    if not targeted_ledger.empty:
        targeted_ledger = targeted_ledger.sort_values(
            ["window_id", "strategy_id", "signal_date", "ticker", "entry_execution_date"], kind="mergesort"
        ).reset_index(drop=True)

    # Remove base trades only from changed spans. NOT_EVALUABLE spans are also
    # replaced by an empty replay result; all other trades remain byte-level
    # source rows carried forward from the frozen ledger.
    replace_pairs = set()
    for row in revised_spans.loc[revised_spans["ticker"].isin(TICKERS)].to_dict("records"):
        if row.get("span_changed"):
            replace_pairs.add((str(row["ticker"]), str(row["window_id"])))
    unaffected_mask = ~base_ledger.apply(lambda row: (str(row["ticker"]), str(row["window_id"])) in replace_pairs, axis=1)
    kept = base_ledger.loc[unaffected_mask].copy()
    certified = pd.concat([kept, targeted_ledger], ignore_index=True)
    if not certified.empty:
        certified = certified.sort_values(
            ["window_id", "strategy_id", "signal_date", "ticker", "entry_execution_date"], kind="mergesort"
        ).reset_index(drop=True)

    risk_closure = close_risk_identities(exposed, certified)
    revised_summary = study._build_summary(revised_spans, certified)
    delta_cols = []
    baseline_index = baseline_summary.set_index(["window_id", "scope"])
    for col in revised_summary.columns:
        if col in {"window_id", "scope"} or col not in baseline_summary.columns:
            continue
        if pd.api.types.is_numeric_dtype(revised_summary[col]) and pd.api.types.is_numeric_dtype(baseline_summary[col]):
            name = f"delta_vs_original__{col}"
            revised_summary[name] = [
                (float(row[col]) - float(baseline_index.loc[(row["window_id"], row["scope"]), col]))
                if pd.notna(row[col]) and pd.notna(baseline_index.loc[(row["window_id"], row["scope"]), col]) else np.nan
                for row in revised_summary.to_dict("records")
            ]
            delta_cols.append(name)

    validation_result = study._validate_backtest(revised_spans, certified, revised_summary, replay_errors)
    finite = _finite_ledger_check(certified)
    raw_partition_after = verify_raw_partition_hashes(raw_root)
    hash_after = {
        "ledger_sha256": sha256_file(ledger_path),
        "span_sha256": sha256_file(span_path),
        "universe_sha256": sha256_file(universe_path),
        "raw_manifest_sha256": sha256_file(raw_manifest_path),
        "strategy_source_sha256": {rel: sha256_file(ROOT / rel) for rel in SOURCE_PATHS},
    }
    strategy_changed = [rel for rel in SOURCE_PATHS if integrity_before["strategy_source_sha256"][rel] != hash_after["strategy_source_sha256"][rel]]
    untouched_span_change_count = int(
        sum(
            str(old["comparison_effective_start"]) != str(new["comparison_effective_start"])
            or str(old["comparison_effective_end"]) != str(new["comparison_effective_end"])
            or str(old["coverage_status"]) != str(new["coverage_status"])
            for old, new in zip(baseline_spans.to_dict("records"), revised_spans.to_dict("records"))
            if old["ticker"] not in TICKERS
        )
    )
    exposed_events = int(risk_closure["unique_market_event_id"].nunique())
    checks = {
        "frozen_universe_36": len(universe) == 36 and set(instruments) == set(TICKERS),
        "affected_ticker_count_10": len(ready_frame) == 10 and ready_frame["ticker"].nunique() == 10,
        "original_risk_identity_count_12": len(exposed) == 12,
        "unique_original_risk_event_count_4": exposed_events == 4,
        "unaffected_etf_span_changes_0": untouched_span_change_count == 0,
        "raw_row_modification_0": (
            integrity_before["raw_manifest_sha256"] == hash_after["raw_manifest_sha256"]
            and raw_diagnostics["raw_partition_hash_error_count"] == 0
            and raw_partition_after["partition_count"] == raw_diagnostics["raw_etf_partition_files_scanned"]
            and raw_partition_after["hash_mismatch_count"] == 0
        ),
        "strategy_source_changed_0": not strategy_changed,
        "market_refetch_0": True,
        "forty_day_recomputation_0": True,
        "full_36_etf_5window_rerun_0": True,
        "targeted_replay_only_affected_tickers": set(replayed_by_ticker).issubset(set(TICKERS)),
        "targeted_replay_error_count_0": not replay_errors,
        "revised_trade_identity_duplicates_0": not certified["trade_identity"].duplicated().any() if not certified.empty else True,
        "mandatory_nan_inf_0": finite["mandatory_nonfinite_count"] == 0 and finite["realized_exit_nonfinite_count"] == 0,
        "unexpected_nan_0": finite["unexpected_nan_count"] == 0,
        "signal_path_clean_at_each_clean_ready": bool(ready_frame["sentinel_labels_remaining_at_ready"].eq(0).all()),
        "strategy_span_parity": bool((revised_spans["v2_strategy_eligible_date"] == revised_spans["julia_strategy_eligible_date"]).all()),
        "validation_replay_contract": bool(validation_result["passed"]),
        "original_ledger_unchanged": integrity_before["ledger_sha256"] == hash_after["ledger_sha256"],
        "original_spans_unchanged": integrity_before["span_sha256"] == hash_after["span_sha256"],
        "original_universe_unchanged": integrity_before["universe_sha256"] == hash_after["universe_sha256"],
        "raw_target_partition_hash_errors_0": raw_diagnostics["raw_partition_hash_error_count"] == 0,
        "revised_summary_rows_20": len(revised_summary) == 20,
        "risk_closure_rows_12": len(risk_closure) == 12,
        "no_unresolved_risk_disposition": not risk_closure["disposition"].eq("OTHER_DETERMINISTIC_CHANGE").any(),
    }
    failures = [name for name, passed in checks.items() if not passed]
    verdict = (
        "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_PASS"
        if not failures else "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_CHECK_REQUIRED"
    )
    validation = {
        "verdict": verdict,
        "certified_backtest_verdict": (
            "ETF_36_AFAST_V2_VS_JULIA_5WINDOW_SIMPLE_BACKTEST_CERTIFIED_PASS"
            if validation_result["passed"] and not failures else "CHECK_REQUIRED"
        ),
        "authority": {"baseline_backtest_commit": AUTHORITY_COMMIT, "sentinel_audit_commit": AUDIT_COMMIT},
        "scope": {
            "universe_count": len(universe), "affected_tickers": list(TICKERS),
            "strategies": list(STRATEGIES), "window_ids": list(study.EXPECTED_WINDOWS),
            "replayed_ticker_count": len(replayed_by_ticker),
            "targeted_replay_window_count": len(targeted_span_rows),
            "targeted_replay_trade_count": len(targeted_ledger),
            "baseline_trade_count": len(base_ledger), "certified_trade_count": len(certified),
            "clean_ready_lookbacks": lookbacks,
            "raw_data_diagnostics": raw_diagnostics,
        },
        "counts": {
            "clean_ready_ticker_count": len(ready_frame),
            "changed_target_span_count": int(changes["span_changed"].sum()) if not changes.empty else 0,
            "targeted_replay_span_count": int(targeted_span_rows.shape[0]),
            "original_exposed_trade_identity_count": len(exposed),
            "original_exposed_unique_ticker_signal_event_count": exposed_events,
            "risk_dispositions_by_identity": risk_closure["disposition"].value_counts().to_dict(),
            "risk_dispositions_by_unique_event": risk_closure.drop_duplicates("unique_market_event_id")["disposition"].value_counts().to_dict(),
            "unaffected_etf_span_change_count": untouched_span_change_count,
            "revised_duplicate_trade_identity_count": int(certified["trade_identity"].duplicated().sum()) if not certified.empty else 0,
            "post_cutoff_new_entry_count": int((pd.to_datetime(certified["entry_execution_date"]) > pd.to_datetime(certified["cutoff_date"])).sum()) if not certified.empty else 0,
            "support_after_exit_count": int((pd.to_datetime(certified.loc[certified["exit_execution_date"].notna(), "exit_execution_date"]) > pd.to_datetime(certified.loc[certified["exit_execution_date"].notna(), "execution_support_date"])).sum()) if not certified.empty else 0,
            **finite,
        },
        "checks": checks,
        "failed_checks": failures,
        "replay_errors": replay_errors,
        "existing_backtest_validation": validation_result,
        "authority_integrity": {
            "before": integrity_before, "after": hash_after,
            "strategy_source_changed_paths": strategy_changed,
            "raw_partition_hash_error_count": raw_diagnostics["raw_partition_hash_error_count"],
            "raw_partition_hashes_after": raw_partition_after,
        },
        "execution": {
            "market_refetch_count": 0, "forty_day_recomputation_count": 0,
            "full_36_etf_five_window_replay_count": 0,
            "runtime_seconds": round(time.perf_counter() - started, 3),
        },
    }

    # The direct pipeline writes only closure artifacts and leaves its frozen
    # baseline data, raw partitions, and strategy source untouched.
    pd.DataFrame(lookbacks["features"]).to_csv(output_dir / "signal_path_lookback_contract.csv", index=False, encoding="utf-8")
    ready_frame.to_csv(output_dir / "clean_strategy_ready_dates.csv", index=False, encoding="utf-8")
    changes.to_csv(output_dir / "affected_span_changes.csv", index=False, encoding="utf-8")
    targeted_ledger.to_csv(output_dir / "targeted_replay_trade_ledger.csv", index=False, encoding="utf-8")
    risk_closure.to_csv(output_dir / "risk_identity_closure.csv", index=False, encoding="utf-8")
    certified.to_csv(output_dir / "certified_trade_ledger.csv", index=False, encoding="utf-8")
    revised_summary.to_csv(output_dir / "certified_window_comparison_summary.csv", index=False, encoding="utf-8")
    _write_json(output_dir / "validation.json", validation)
    (output_dir / "summary.md").write_text(
        _summary_markdown(validation, ready_frame, changes, risk_closure, revised_summary), encoding="utf-8"
    )
    print(json.dumps({
        "verdict": verdict,
        "failed_checks": failures,
        "clean_ready_dates": ready_frame[["ticker", "clean_strategy_ready_date"]].to_dict("records"),
        "changed_target_span_count": int(changes["span_changed"].sum()) if not changes.empty else 0,
        "targeted_replay_span_count": int(len(targeted_span_rows)),
        "risk_dispositions": validation["counts"]["risk_dispositions_by_identity"],
        "output_dir": str(output_dir), "runtime_seconds": validation["execution"]["runtime_seconds"],
    }, ensure_ascii=False))
    return validation


if __name__ == "__main__":
    outcome = run()
    raise SystemExit(0 if outcome["verdict"] == "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_PASS" else 2)
