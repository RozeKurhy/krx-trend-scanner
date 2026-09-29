#!/usr/bin/env python3
"""Replay the certified ETF-36 trade ledger under two realistic position caps."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gc
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))
if str(ROOT / "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT / "src"))

from scripts import run_etf_36_afast_v2_vs_julia_5window_simple_v01 as study  # noqa: E402
from scripts import run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03 as engine  # noqa: E402
from scripts.finalize_etf_36_sentinel_closure_validator_v01 import load_revised_spans  # noqa: E402

BASE_REL = Path("artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01")
CLOSURE_REL = Path("artifacts/research/etf_36_zero_ohlc_sentinel_clean_eligibility_closure_v01")
OUTPUT_REL = Path("artifacts/research/etf_36_realistic_portfolio_afast_v2_vs_julia_15m_25m_v01")
LEDGER_NAME = "certified_trade_ledger.csv"
INITIAL_CAPITAL_KRW = 250_000_000.0
POSITION_SCENARIOS = {"15M": 15_000_000.0, "25M": 25_000_000.0}
WORKERS = 10
EXPECTED_LEDGER_ROWS = 505
EXPECTED_UNIVERSE_SIZE = 36
EXPECTED_WINDOWS = study.EXPECTED_WINDOWS
STRATEGY_ORDER = (engine.STRATEGY_A_FAST, engine.STRATEGY_JULIA)
STRATEGY_LABELS = {
    engine.STRATEGY_A_FAST: "A FAST Core V2",
    engine.STRATEGY_JULIA: "Julia V00",
}
EXIT_FILL_FIELDS = ("exit_signal_date", "exit_execution_date", "exit_price_raw_open")
PERCENT_POINT_TOLERANCE = 0.1

_WORKER_DAILY: dict[str, pd.DataFrame] = {}
_WORKER_CALENDAR: list[str] = []
_WORKER_CATEGORIES: dict[str, str] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: pd.DataFrame | Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if columns is not None:
        frame = frame.reindex(columns=list(columns))
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.10f")


def _input_paths(root: Path) -> dict[str, Path]:
    base = root / BASE_REL
    closure = root / CLOSURE_REL
    return {
        "certified_trade_ledger": closure / LEDGER_NAME,
        "certified_closure_validation": closure / "validation.json",
        "closure_summary": closure / "summary.md",
        "base_effective_span_audit": base / "effective_span_audit.csv",
        "affected_span_changes": closure / "affected_span_changes.csv",
        "official_etf_universe_36": base / "official_etf_universe_36.csv",
        "realistic_portfolio_engine": root / "scripts/run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03.py",
        "raw_price_database_builder": root / "scripts/run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03.py",
    }


def _load_authorities(root: Path = ROOT) -> dict[str, Any]:
    paths = _input_paths(root)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"CERTIFIED_AUTHORITY_FILE_MISSING:{','.join(missing)}")
    closure_dir = root / CLOSURE_REL
    base_dir = root / BASE_REL
    closure_validation = json.loads(paths["certified_closure_validation"].read_text(encoding="utf-8"))
    ledger = pd.read_csv(
        paths["certified_trade_ledger"],
        dtype={
            "ticker": "string", "ISU_CD": "string", "strategy_id": "string",
            "window_id": "string", "trade_identity": "string",
        },
        keep_default_na=False,
    )
    universe_frame = pd.read_csv(paths["official_etf_universe_36"], dtype={"ticker": "string"}, keep_default_na=False)
    spans = load_revised_spans(closure_dir, base_dir)
    universe: list[dict[str, Any]] = []
    for source in universe_frame.to_dict(orient="records"):
        row = dict(source)
        row["ticker"] = str(row["ticker"]).zfill(6)
        universe.append(row)
    category_by_ticker = {row["ticker"]: str(row["major_category"]) for row in universe}
    label_by_strategy: dict[str, str] = {}
    for strategy_id, part in ledger.groupby("strategy_id", sort=False):
        labels = sorted(set(part["strategy_label"].astype(str)))
        label_by_strategy[str(strategy_id)] = labels[0] if len(labels) == 1 else ""

    errors: list[str] = []
    checks: dict[str, bool] = {}
    checks["sentinel_closure_certified_pass"] = closure_validation.get("verdict") == "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_PASS"
    checks["simple_backtest_certified_pass"] = closure_validation.get("certified_backtest_verdict") == "ETF_36_AFAST_V2_VS_JULIA_5WINDOW_SIMPLE_BACKTEST_CERTIFIED_PASS"
    checks["certified_trade_ledger_505"] = len(ledger) == EXPECTED_LEDGER_ROWS
    checks["official_universe_36_unique"] = len(universe) == EXPECTED_UNIVERSE_SIZE and len(category_by_ticker) == EXPECTED_UNIVERSE_SIZE
    checks["effective_span_authority_180_unique"] = (
        len(spans) == 180 and not spans.duplicated(["window_id", "ticker"]).any()
    )
    checks["strategy_count_2"] = set(ledger["strategy_id"].astype(str)) == set(STRATEGY_ORDER)
    checks["window_count_5"] = set(ledger["window_id"].astype(str)) == set(EXPECTED_WINDOWS)
    checks["all_trade_tickers_in_universe"] = set(ledger["ticker"].astype(str)) <= set(category_by_ticker)
    checks["trade_identity_duplicate_0"] = int(ledger["trade_identity"].duplicated().sum()) == 0
    ledger_key_columns = ["strategy_id", "window_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date"]
    checks["engine_entry_key_duplicate_0"] = int(ledger.duplicated(ledger_key_columns).sum()) == 0

    span_map = {
        (str(row.window_id), str(row.ticker)): row
        for row in spans.itertuples(index=False)
    }
    span_mismatch_count = 0
    signal_before_start_count = 0
    entry_before_start_count = 0
    post_cutoff_entry_count = 0
    invalid_window_date_count = 0
    support_violation_count = 0
    for row in ledger.to_dict(orient="records"):
        window_id = str(row["window_id"])
        ticker = str(row["ticker"]).zfill(6)
        authority = span_map.get((window_id, ticker))
        if authority is None:
            span_mismatch_count += 1
            continue
        start, end, support = EXPECTED_WINDOWS[window_id]
        effective_start = str(authority.comparison_effective_start)
        effective_end = str(authority.comparison_effective_end)
        if (
            str(row["comparison_effective_start"]) != effective_start
            or str(row["comparison_effective_end"]) != effective_end
            or str(authority.window_start) != start
            or str(authority.window_end) != end
            or str(row["cutoff_date"]) != end
            or str(row["execution_support_date"]) != support
        ):
            span_mismatch_count += 1
        if str(row["signal_date"]) < effective_start:
            signal_before_start_count += 1
        if str(row["entry_execution_date"]) < effective_start:
            entry_before_start_count += 1
        if not (start <= str(row["signal_date"]) <= end and start <= str(row["entry_execution_date"]) <= end):
            invalid_window_date_count += 1
        if str(row["entry_execution_date"]) > end:
            post_cutoff_entry_count += 1
        if str(row["trade_status"]) == "REALIZED":
            if not str(row["exit_execution_date"]) or str(row["exit_execution_date"]) > support:
                support_violation_count += 1
        elif str(row["trade_status"]) == "OPEN_AT_CUTOFF":
            if str(row["exit_or_terminal_date"]) != end or str(row["exit_execution_date"]).strip():
                support_violation_count += 1
        else:
            support_violation_count += 1
    checks["certified_window_effective_span_parity"] = span_mismatch_count == 0
    checks["signal_before_effective_start_0"] = signal_before_start_count == 0
    checks["entry_before_effective_start_0"] = entry_before_start_count == 0
    checks["post_cutoff_entry_0"] = post_cutoff_entry_count == 0
    checks["trade_dates_within_standard_window"] = invalid_window_date_count == 0
    checks["source_execution_support_violation_0"] = support_violation_count == 0

    cost_fields = {
        "commission_rate_each_side": engine.BUY_FEE_RATE,
        "slippage_rate_each_side": engine.BUY_SLIPPAGE_RATE,
        "ETF_sell_tax_rate": engine.ETF_SELL_TAX_RATE,
    }
    for field, expected in cost_fields.items():
        values = pd.to_numeric(ledger[field], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            checks[f"certified_{field}_contract"] = False
        else:
            checks[f"certified_{field}_contract"] = bool(np.allclose(values.to_numpy(dtype=float), expected, rtol=0, atol=1e-12))
    tax_applied = ledger["tax_applied_to_backtest_pnl"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    checks["certified_ledger_has_no_tax_pnl_application"] = int(tax_applied.sum()) == 0
    checks["engine_contract_default_costs"] = (
        engine.BUY_FEE_RATE == 0.00015
        and engine.SELL_FEE_RATE == 0.00015
        and engine.BUY_SLIPPAGE_RATE == 0.001
        and engine.SELL_SLIPPAGE_RATE == 0.001
        and engine.ETF_SELL_TAX_RATE == 0.0
        and engine.ORDER_FIELDS == ("ticker", "ISU_CD", "signal_date", "entry_execution_date")
    )

    counts = {
        "certified_trade_count": int(len(ledger)),
        "source_trade_ticker_count": int(ledger["ticker"].nunique()),
        "official_universe_ticker_count": int(len(universe)),
        "source_strategy_count": int(ledger["strategy_id"].nunique()),
        "source_window_count": int(ledger["window_id"].nunique()),
        "source_trade_identity_duplicate_count": int(ledger["trade_identity"].duplicated().sum()),
        "engine_entry_key_duplicate_count": int(ledger.duplicated(ledger_key_columns).sum()),
        "signal_before_effective_start_count": signal_before_start_count,
        "entry_before_effective_start_count": entry_before_start_count,
        "post_cutoff_entry_count": post_cutoff_entry_count,
        "effective_span_mismatch_count": span_mismatch_count,
        "window_date_mismatch_count": invalid_window_date_count,
        "execution_support_violation_count": support_violation_count,
        "certified_tax_pnl_application_count": int(tax_applied.sum()),
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(name.upper())
    hashes = {name: _sha256(path) for name, path in paths.items()}
    return {
        "ledger": ledger,
        "universe": universe,
        "category_by_ticker": category_by_ticker,
        "label_by_strategy": label_by_strategy,
        "spans": spans,
        "span_map": span_map,
        "closure_validation": closure_validation,
        "checks": checks,
        "errors": errors,
        "counts": counts,
        "source_hashes": hashes,
    }


def _raw_price_checks(
    ledger: pd.DataFrame,
    universe: Sequence[Mapping[str, Any]],
    db_path: Path,
    data_info: Mapping[str, Any],
) -> dict[str, Any]:
    calendar = [str(value)[:10] for value in data_info["calendar_dates_internal"]]
    calendar_index = pd.DatetimeIndex(pd.to_datetime(calendar))
    calendar_set = set(calendar)
    daily = engine._load_daily_frames(db_path, sorted(set(ledger["ticker"].astype(str).str.zfill(6))))
    price_errors: list[str] = []
    entry_mismatch = exit_mismatch = terminal_mismatch = close_gap_count = 0
    required_valuation_sessions = 0
    for row in ledger.to_dict(orient="records"):
        ticker = str(row["ticker"]).zfill(6)
        frame = daily.get(ticker)
        if frame is None:
            price_errors.append(f"PRICE_FRAME_MISSING:{ticker}")
            continue
        entry_date = str(row["entry_execution_date"])
        if entry_date not in calendar_set or pd.Timestamp(entry_date) not in frame.index:
            entry_mismatch += 1
        else:
            observed = pd.to_numeric(frame.at[pd.Timestamp(entry_date), "open"], errors="coerce")
            expected = pd.to_numeric(row["entry_price_raw_open"], errors="coerce")
            if pd.isna(observed) or not math.isclose(float(observed), float(expected), rel_tol=0, abs_tol=1e-8):
                entry_mismatch += 1

        cutoff = str(row["cutoff_date"])
        status = str(row["trade_status"])
        if status == "REALIZED":
            exit_date = str(row["exit_execution_date"])
            if exit_date not in calendar_set or pd.Timestamp(exit_date) not in frame.index:
                exit_mismatch += 1
            else:
                observed = pd.to_numeric(frame.at[pd.Timestamp(exit_date), "open"], errors="coerce")
                expected = pd.to_numeric(row["exit_price_raw_open"], errors="coerce")
                if pd.isna(observed) or pd.isna(expected) or not math.isclose(float(observed), float(expected), rel_tol=0, abs_tol=1e-8):
                    exit_mismatch += 1
            valuation_end = pd.Timestamp(exit_date)
            required_dates = calendar_index[(calendar_index >= pd.Timestamp(entry_date)) & (calendar_index < valuation_end)]
        else:
            if cutoff not in calendar_set or pd.Timestamp(cutoff) not in frame.index:
                terminal_mismatch += 1
            else:
                observed = pd.to_numeric(frame.at[pd.Timestamp(cutoff), "close"], errors="coerce")
                expected = pd.to_numeric(row["terminal_price_raw"], errors="coerce")
                if pd.isna(observed) or pd.isna(expected) or not math.isclose(float(observed), float(expected), rel_tol=0, abs_tol=1e-8):
                    terminal_mismatch += 1
            required_dates = calendar_index[(calendar_index >= pd.Timestamp(entry_date)) & (calendar_index <= pd.Timestamp(cutoff))]

        required_valuation_sessions += len(required_dates)
        close = pd.to_numeric(frame.reindex(required_dates)["close"], errors="coerce")
        valid = np.isfinite(close.to_numpy(dtype=float)) & close.gt(0).to_numpy()
        close_gap_count += int((~valid).sum())

    raw_audit = engine._audit_raw_data(db_path, universe)
    required_window_dates = {
        day
        for dates in EXPECTED_WINDOWS.values()
        for day in dates
    }
    missing_window_dates = sorted(required_window_dates - calendar_set)
    current_universe_cutoff_count = int(data_info["current_universe_tickers_with_cutoff_prices"])
    current_universe_support_count = int(data_info["current_universe_tickers_with_support_prices"])
    return {
        "passed": (
            not price_errors
            and entry_mismatch == 0
            and exit_mismatch == 0
            and terminal_mismatch == 0
            and close_gap_count == 0
            and raw_audit["other_invalid_ohlc_rows"] == 0
            and not missing_window_dates
            and current_universe_cutoff_count == len(universe)
            and current_universe_support_count == len(universe)
        ),
        "errors": price_errors,
        "entry_execution_price_mismatch_count": entry_mismatch,
        "realized_exit_execution_price_mismatch_count": exit_mismatch,
        "open_terminal_close_mismatch_count": terminal_mismatch,
        "candidate_holding_close_missing_or_invalid_count": close_gap_count,
        "candidate_holding_valuation_session_count": required_valuation_sessions,
        "raw_data_audit": raw_audit,
        "calendar_session_count": len(calendar),
        "calendar_sha256": hashlib.sha256("\n".join(calendar).encode()).hexdigest(),
        "calendar_first_date": calendar[0] if calendar else None,
        "calendar_last_date": calendar[-1] if calendar else None,
        "missing_standard_window_calendar_dates": missing_window_dates,
        "official_universe_raw_cutoff_price_count": current_universe_cutoff_count,
        "official_universe_raw_execution_support_price_count": current_universe_support_count,
        "official_universe_raw_price_coverage_count": len(universe),
        "calendar_dates_internal": calendar,
        "loaded_candidate_tickers": sorted(daily),
        "raw_store_manifest_sha256": str(data_info["source_store_manifest_sha256"]),
        "raw_store_partition_count_through_support": int(data_info["raw_etf_partition_count_through_support"]),
        "local_raw_rewrite_count": 0,
        "market_refetch_count": 0,
        "signal_regeneration_count": 0,
        "clean_ready_recompute_count": 0,
        "forty_day_recomputation_count": 0,
        "new_tax_rule_count": 0,
    }


def _worker_init(db_path: str, tickers: list[str], calendar_dates: list[str], categories: dict[str, str]) -> None:
    global _WORKER_DAILY, _WORKER_CALENDAR, _WORKER_CATEGORIES
    _WORKER_DAILY = engine._load_daily_frames(Path(db_path), tickers)
    _WORKER_CALENDAR = list(calendar_dates)
    _WORKER_CATEGORIES = dict(categories)


def _augment_cash_audit(
    portfolio_ledger: pd.DataFrame,
    equity_curve: pd.DataFrame,
    job: Mapping[str, Any],
) -> tuple[pd.DataFrame, int, list[str]]:
    ledger = portfolio_ledger.copy()
    if ledger.empty:
        return ledger, 0, []
    ledger["portfolio_cash_before_entry_krw"] = np.nan
    ledger["portfolio_cash_after_entry_krw"] = np.nan
    ledger["intended_shares"] = 0
    ledger["required_cash_for_sized_order_krw"] = np.nan
    ledger["required_cash_for_one_share_krw"] = np.nan
    ledger["available_cash_krw"] = np.nan
    entries_by_date: dict[str, list[dict[str, Any]]] = {}
    exits_by_date: dict[str, list[dict[str, Any]]] = {}
    records = ledger.to_dict(orient="records")
    for row in records:
        entries_by_date.setdefault(str(row["entry_execution_date"]), []).append(row)
        if str(row.get("exit_status")) == "FILLED":
            exits_by_date.setdefault(str(row["exit_execution_date"]), []).append(row)
    cash = float(job["initial_capital_krw"])
    mismatch_count = 0
    errors: list[str] = []
    curve_cash = {str(row["date"]): float(row["cash"]) for row in equity_curve.to_dict(orient="records")}
    for date in _calendar_slice(_WORKER_CALENDAR, str(job["window_start"]), str(job["execution_support_date"])):
        for row in sorted(exits_by_date.get(date, []), key=engine._order_key):
            cash += float(row["sell_cash_proceeds_krw"])
        for row in sorted(entries_by_date.get(date, []), key=engine._order_key):
            before = cash
            status = str(row["entry_status"])
            if status in {"FILLED", "CASH_SKIP"}:
                sizing = engine._buy_sizing(float(row["entry_price_raw_open"]), cash)
                intended_shares = int(sizing["shares"])
                required_cash = float(sizing["total_cost"])
                row["intended_shares"] = intended_shares
                row["required_cash_for_sized_order_krw"] = required_cash
                row["required_cash_for_one_share_krw"] = float(sizing["fill_price"]) * (1.0 + engine.BUY_FEE_RATE)
                if status == "FILLED":
                    if intended_shares != int(row["shares"]) or not bool(sizing["cash_sufficient"]):
                        errors.append(f"FILLED_ENTRY_SIZING_MISMATCH:{row['trade_identity']}")
                    cash -= float(row["buy_cash_cost_krw"])
                else:
                    if intended_shares > 0 and bool(sizing["cash_sufficient"]):
                        errors.append(f"CASH_SKIP_WHEN_FULL_SIZE_AFFORDABLE:{row['trade_identity']}")
            elif status == "OPEN_POSITION_SKIP":
                row["cash_skip_reason"] = "OPEN_POSITION_ALREADY_HELD"
            else:
                errors.append(f"UNRESOLVED_ENTRY_STATUS:{row['trade_identity']}:{status}")
            row["portfolio_cash_before_entry_krw"] = before
            row["portfolio_cash_after_entry_krw"] = cash
            row["available_cash_krw"] = before
        expected_cash = curve_cash.get(date)
        if expected_cash is None or not math.isclose(cash, expected_cash, rel_tol=0, abs_tol=1e-5):
            mismatch_count += 1
    return pd.DataFrame(records), mismatch_count, errors


def _calendar_slice(calendar: Sequence[str], start: str, end: str) -> list[str]:
    return [str(day)[:10] for day in calendar if start <= str(day)[:10] <= end]


def _holding_records(
    portfolio_ledger: pd.DataFrame,
    calendar: Sequence[str],
    job: Mapping[str, Any],
) -> tuple[pd.DataFrame, int]:
    records = portfolio_ledger.loc[portfolio_ledger["entry_status"].eq("FILLED")].copy()
    calendar_dates = [pd.Timestamp(day) for day in _calendar_slice(calendar, str(job["window_start"]), str(job["execution_support_date"]))]
    calendar_set = set(calendar_dates)
    rows: list[dict[str, Any]] = []
    mismatches = 0
    for row in records.to_dict(orient="records"):
        entry = pd.Timestamp(row["entry_execution_date"])
        if str(row["exit_status"]) == "FILLED":
            terminal = pd.Timestamp(row["exit_execution_date"])
            holding_class = "CLOSED"
        elif str(row["exit_status"]) == "OPEN_AT_CUTOFF":
            terminal = pd.Timestamp(job["cutoff_date"])
            holding_class = "OPEN_AT_CUTOFF"
        else:
            mismatches += 1
            continue
        sessions = sum(entry <= day <= terminal for day in calendar_dates)
        source_sessions = int(pd.to_numeric(row["holding_krx_sessions_inclusive"], errors="coerce"))
        if entry not in calendar_set or terminal not in calendar_set or sessions != source_sessions:
            mismatches += 1
        rows.append({
            "scenario_id": job["scenario_id"],
            "window_id": job["window_id"],
            "strategy_id": job["strategy_id"],
            "strategy_label": job["strategy_label"],
            "holding_class": holding_class,
            "trade_identity": row["trade_identity"],
            "ticker": row["ticker"],
            "holding_krx_sessions": sessions,
            "holding_calendar_days": int((terminal - entry).days),
        })
    return pd.DataFrame(rows), mismatches


def _holding_stats(rows: pd.DataFrame, holding_class: str) -> dict[str, Any]:
    part = rows if holding_class == "ALL_FILLED_POSITIONS" else rows.loc[rows["holding_class"].eq(holding_class)]
    sessions = pd.to_numeric(part.get("holding_krx_sessions", pd.Series(dtype=float)), errors="coerce").dropna()
    calendar_days = pd.to_numeric(part.get("holding_calendar_days", pd.Series(dtype=float)), errors="coerce").dropna()
    if sessions.empty:
        return {
            "holding_class": holding_class,
            "filled_position_count": 0,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
            "p25_holding_sessions": None,
            "p75_holding_sessions": None,
            "p90_holding_sessions": None,
            "max_holding_sessions": None,
            "mean_holding_calendar_days": None,
            "median_holding_calendar_days": None,
        }
    return {
        "holding_class": holding_class,
        "filled_position_count": int(len(sessions)),
        "mean_holding_sessions": float(sessions.mean()),
        "median_holding_sessions": float(sessions.median()),
        "p25_holding_sessions": float(sessions.quantile(0.25)),
        "p75_holding_sessions": float(sessions.quantile(0.75)),
        "p90_holding_sessions": float(sessions.quantile(0.90)),
        "max_holding_sessions": int(sessions.max()),
        "mean_holding_calendar_days": float(calendar_days.mean()),
        "median_holding_calendar_days": float(calendar_days.median()),
    }


def _enrich_curve(curve: pd.DataFrame, job: Mapping[str, Any]) -> pd.DataFrame:
    result = curve.copy()
    equity = pd.to_numeric(result["total_equity"], errors="coerce")
    invested = pd.to_numeric(result["invested_market_value"], errors="coerce")
    peak = equity.cummax()
    result["scenario_id"] = job["scenario_id"]
    result["window_id"] = job["window_id"]
    result["strategy_label"] = job["strategy_label"]
    result["capital_utilization_pct"] = invested / equity * 100.0
    result["drawdown_pct"] = (equity / peak - 1.0) * 100.0
    result["concurrent_holdings"] = pd.to_numeric(result["open_positions"], errors="coerce").astype(int)
    return result


def _portfolio_summary_row(
    replay_summary: Mapping[str, Any],
    curve: pd.DataFrame,
    holding_rows: pd.DataFrame,
    job: Mapping[str, Any],
) -> dict[str, Any]:
    cutoff_curve = curve.loc[curve["date"].le(str(job["cutoff_date"]))].copy()
    holding = _holding_stats(holding_rows, "ALL_FILLED_POSITIONS")
    candidate_entries = int(replay_summary["candidate_entry_signals"])
    cash_skips = int(replay_summary["CASH_SKIP"])
    invested = pd.to_numeric(cutoff_curve["invested_market_value"], errors="coerce")
    utilization = pd.to_numeric(cutoff_curve["capital_utilization_pct"], errors="coerce")
    cash = pd.to_numeric(cutoff_curve["cash"], errors="coerce")
    cash_ratio = pd.to_numeric(cutoff_curve["cash_ratio"], errors="coerce") * 100.0
    return {
        "scenario_id": job["scenario_id"],
        "window_id": job["window_id"],
        "strategy_id": job["strategy_id"],
        "strategy_label": job["strategy_label"],
        "window_start": job["window_start"],
        "cutoff_date": job["cutoff_date"],
        "execution_support_date": job["execution_support_date"],
        "initial_equity_krw": float(replay_summary["initial_capital_krw"]),
        "per_ticker_position_cap_krw": float(job["position_cap_krw"]),
        "final_equity_krw": float(replay_summary["final_equity_krw"]),
        "total_return_pct": float(replay_summary["total_return_pct"]),
        "CAGR_pct": float(replay_summary["CAGR_pct"]),
        "MDD_pct": float(replay_summary["mdd_pct"]),
        "MDD_peak_date": replay_summary["mdd_start_date"],
        "MDD_trough_date": replay_summary["mdd_trough_date"],
        "MDD_recovery_date": replay_summary["mdd_recovery_date"],
        "realized_pnl_krw": float(replay_summary["realized_pnl_krw"]),
        "terminal_unrealized_pnl_krw": float(replay_summary["terminal_unrealized_pnl_krw"]),
        "candidate_entries": candidate_entries,
        "filled_entries": int(replay_summary["filled_entries"]),
        "CASH_SKIP_count": cash_skips,
        "CASH_SKIP_rate_pct": cash_skips / candidate_entries * 100.0 if candidate_entries else None,
        "open_position_skip_count": int(replay_summary["open_position_skip"]),
        "realized_trades": int(replay_summary["realized_trade_count"]),
        "open_at_cutoff_positions": int(replay_summary["terminal_positions"]),
        "positions_open_at_cutoff_including_support_exits": int(replay_summary["cutoff_open_positions_including_support_exits"]),
        "average_concurrent_holdings": float(replay_summary["average_concurrent_positions"]),
        "median_concurrent_holdings": float(replay_summary["median_concurrent_positions"]),
        "max_concurrent_holdings": int(replay_summary["max_concurrent_positions"]),
        "average_invested_capital_krw": float(invested.mean()),
        "median_invested_capital_krw": float(invested.median()),
        "max_invested_capital_krw": float(invested.max()),
        "average_capital_utilization_pct": float(utilization.mean()),
        "median_capital_utilization_pct": float(utilization.median()),
        "max_capital_utilization_pct": float(utilization.max()),
        "average_cash_balance_krw": float(cash.mean()),
        "median_cash_balance_krw": float(cash.median()),
        "average_cash_ratio_pct": float(cash_ratio.mean()),
        "median_cash_ratio_pct": float(cash_ratio.median()),
        "win_rate_pct": replay_summary["realized_positive_rate_pct"],
        "mean_return_pct": replay_summary["realized_mean_return_pct"],
        "median_return_pct": replay_summary["realized_median_return_pct"],
        "plus_50_pct_count": int(replay_summary["realized_ge_50_pct_count"]),
        "plus_100_pct_count": int(replay_summary["realized_ge_100_pct_count"]),
        "minus_15_pct_or_worse_count": int(replay_summary["realized_le_minus_15_pct_count"]),
        "minus_30_pct_or_worse_count": int(replay_summary["realized_le_minus_30_pct_count"]),
        "minus_40_pct_or_worse_count": int(replay_summary["realized_le_minus_40_pct_count"]),
        "mean_holding_sessions": holding["mean_holding_sessions"],
        "median_holding_sessions": holding["median_holding_sessions"],
        "p25_holding_sessions": holding["p25_holding_sessions"],
        "p75_holding_sessions": holding["p75_holding_sessions"],
        "p90_holding_sessions": holding["p90_holding_sessions"],
        "max_holding_sessions": holding["max_holding_sessions"],
        "mean_holding_calendar_days": holding["mean_holding_calendar_days"],
        "median_holding_calendar_days": holding["median_holding_calendar_days"],
        "negative_cash_count": int(replay_summary["negative_cash_count"]),
        "leverage_usage_krw": float(replay_summary["leverage_usage_krw"]),
        "sell_tax_krw": float(replay_summary["sell_tax_krw"]),
        "cash_conservation_error_count": int(replay_summary["cash_conservation_error_count"]),
        "cash_reconstruction_error_count": 0,
        "position_cap_violation_count": 0,
        "run_status": str(replay_summary["run_status"]),
    }


def _run_portfolio_job(job: Mapping[str, Any]) -> dict[str, Any]:
    engine.GLOBAL_START = pd.Timestamp(job["window_start"])
    engine.CUTOFF = pd.Timestamp(job["cutoff_date"])
    engine.EXECUTION_SUPPORT = pd.Timestamp(job["execution_support_date"])
    engine.INITIAL_CAPITAL = float(job["initial_capital_krw"])
    engine.POSITION_CAP = float(job["position_cap_krw"])
    source_rows = [dict(row) for row in job["trade_rows"]]
    replay = engine._portfolio_replay(
        source_rows,
        _WORKER_DAILY,
        _WORKER_CALENDAR,
        str(job["strategy_id"]),
        _WORKER_CATEGORIES,
    )
    audited_ledger, cash_reconstruction_errors, cash_errors = _augment_cash_audit(
        replay["ledger"], replay["curve"], job
    )
    curve = _enrich_curve(replay["curve"], job)
    holding_rows, holding_mismatch_count = _holding_records(audited_ledger, _WORKER_CALENDAR, job)
    cap_violations = int(
        pd.to_numeric(audited_ledger.loc[audited_ledger["entry_status"].eq("FILLED"), "buy_notional_krw"], errors="coerce")
        .gt(float(job["position_cap_krw"]) + 1e-7).sum()
    )
    summary = _portfolio_summary_row(replay["summary"], curve, holding_rows, job)
    summary["cash_reconstruction_error_count"] = cash_reconstruction_errors
    summary["position_cap_violation_count"] = cap_violations
    summary["holding_period_source_mismatch_count"] = holding_mismatch_count
    summary["cash_audit_error_count"] = len(cash_errors)
    if cash_errors:
        summary["cash_audit_errors"] = cash_errors
    return {
        "job": dict(job),
        "summary": summary,
        "ledger": audited_ledger,
        "curve": curve,
        "holding_rows": holding_rows,
        "events": replay["events"],
        "cash_audit_errors": cash_errors,
        "holding_period_source_mismatch_count": holding_mismatch_count,
    }


def _make_jobs(
    ledger: pd.DataFrame,
    label_by_strategy: Mapping[str, str],
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for window_id, (start, cutoff, support) in EXPECTED_WINDOWS.items():
        window_ledger = ledger.loc[ledger["window_id"].astype(str).eq(window_id)]
        for scenario_id, position_cap in POSITION_SCENARIOS.items():
            for strategy_id in STRATEGY_ORDER:
                candidates = window_ledger.loc[window_ledger["strategy_id"].astype(str).eq(strategy_id)]
                jobs.append({
                    "scenario_id": scenario_id,
                    "window_id": window_id,
                    "strategy_id": strategy_id,
                    "strategy_label": label_by_strategy.get(strategy_id, STRATEGY_LABELS[strategy_id]),
                    "window_start": start,
                    "cutoff_date": cutoff,
                    "execution_support_date": support,
                    "initial_capital_krw": INITIAL_CAPITAL_KRW,
                    "position_cap_krw": float(position_cap),
                    "trade_rows": candidates.to_dict(orient="records"),
                })
    return jobs


def _collect_results(jobs: Sequence[Mapping[str, Any]], db_path: Path, tickers: list[str], calendar: list[str], categories: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=WORKERS,
        initializer=_worker_init,
        initargs=(str(db_path), tickers, calendar, categories),
    ) as executor:
        futures = {executor.submit(_run_portfolio_job, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"completed {result['summary']['window_id']} {result['summary']['strategy_label']} "
                f"{result['summary']['scenario_id']}",
                flush=True,
            )
    window_order = {key: index for index, key in enumerate(EXPECTED_WINDOWS)}
    scenario_order = {key: index for index, key in enumerate(POSITION_SCENARIOS)}
    strategy_order = {key: index for index, key in enumerate(STRATEGY_ORDER)}
    results.sort(key=lambda item: (
        window_order[item["summary"]["window_id"]],
        scenario_order[item["summary"]["scenario_id"]],
        strategy_order[item["summary"]["strategy_id"]],
    ))
    return results


def _validate_results(
    results: Sequence[Mapping[str, Any]],
    jobs: Sequence[Mapping[str, Any]],
    calendar: Sequence[str],
    preflight: Mapping[str, Any],
    initial_hashes: Mapping[str, str],
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, bool] = {}
    checks["preflight_pass"] = bool(preflight["passed"])
    expected_keys = {
        (scenario, window, strategy)
        for scenario in POSITION_SCENARIOS
        for window in EXPECTED_WINDOWS
        for strategy in STRATEGY_ORDER
    }
    result_keys = {
        (str(item["summary"]["scenario_id"]), str(item["summary"]["window_id"]), str(item["summary"]["strategy_id"]))
        for item in results
    }
    checks["portfolio_results_20_exact"] = len(results) == 20 and result_keys == expected_keys and len(result_keys) == 20

    per_result: list[dict[str, Any]] = []
    filled_identity_duplicate_count = entry_before_span_count = post_cutoff_entry_count = support_violation_count = 0
    missing_equity_dates = curve_accounting_errors = negative_cash_count = leverage_result_count = 0
    metric_nonfinite_count = summary_reconciliation_error_count = cash_skip_reconciliation_error_count = 0
    position_cap_violation_count = holding_period_mismatch_count = cash_reconstruction_error_count = 0
    initial_capital_mismatch_count = position_cap_mismatch_count = 0
    total_candidate_count = total_filled_count = total_cash_skip_count = 0
    total_realized_count = total_open_count = 0
    calendar_series = [pd.Timestamp(day) for day in calendar]
    numeric_metrics = (
        "initial_equity_krw", "final_equity_krw", "total_return_pct", "CAGR_pct", "MDD_pct",
        "realized_pnl_krw", "terminal_unrealized_pnl_krw", "candidate_entries", "filled_entries",
        "CASH_SKIP_count", "CASH_SKIP_rate_pct", "open_position_skip_count", "realized_trades",
        "open_at_cutoff_positions", "average_concurrent_holdings", "median_concurrent_holdings",
        "max_concurrent_holdings", "average_invested_capital_krw", "median_invested_capital_krw",
        "max_invested_capital_krw", "average_capital_utilization_pct", "median_capital_utilization_pct",
        "max_capital_utilization_pct", "average_cash_balance_krw", "median_cash_balance_krw",
        "average_cash_ratio_pct", "median_cash_ratio_pct", "win_rate_pct", "mean_return_pct",
        "median_return_pct", "plus_50_pct_count", "plus_100_pct_count",
        "minus_15_pct_or_worse_count", "minus_30_pct_or_worse_count", "minus_40_pct_or_worse_count",
        "mean_holding_sessions", "median_holding_sessions", "p25_holding_sessions", "p75_holding_sessions",
        "p90_holding_sessions", "max_holding_sessions", "mean_holding_calendar_days", "median_holding_calendar_days",
        "negative_cash_count", "leverage_usage_krw", "sell_tax_krw",
    )
    job_map = {
        (str(job["scenario_id"]), str(job["window_id"]), str(job["strategy_id"])): job
        for job in jobs
    }
    for item in results:
        summary = dict(item["summary"])
        job = job_map[(summary["scenario_id"], summary["window_id"], summary["strategy_id"])]
        ledger = item["ledger"].copy()
        curve = item["curve"].copy()
        holding_rows = item["holding_rows"].copy()
        filled = ledger.loc[ledger["entry_status"].eq("FILLED")].copy()
        cash_skipped = ledger.loc[ledger["entry_status"].eq("CASH_SKIP")].copy()
        source_count = len(job["trade_rows"])
        candidate_count = len(ledger)
        filled_identity_duplicate_count += int(filled["trade_identity"].duplicated().sum())
        total_candidate_count += candidate_count
        total_filled_count += len(filled)
        total_cash_skip_count += len(cash_skipped)
        total_realized_count += int(summary["realized_trades"])
        total_open_count += int(summary["open_at_cutoff_positions"])
        if candidate_count != source_count:
            summary_reconciliation_error_count += 1
        statuses = ledger["entry_status"].value_counts().to_dict()
        if sum(int(statuses.get(status, 0)) for status in ("FILLED", "CASH_SKIP", "OPEN_POSITION_SKIP")) != candidate_count:
            summary_reconciliation_error_count += 1

        start = str(job["window_start"])
        cutoff = str(job["cutoff_date"])
        support = str(job["execution_support_date"])
        if not ledger.empty:
            effective_starts = pd.to_datetime(ledger["comparison_effective_start"], errors="coerce")
            signal_dates = pd.to_datetime(ledger["signal_date"], errors="coerce")
            entry_dates = pd.to_datetime(ledger["entry_execution_date"], errors="coerce")
            entry_before_span_count += int((signal_dates < effective_starts).sum())
            entry_before_span_count += int((entry_dates < effective_starts).sum())
            post_cutoff_entry_count += int((ledger["entry_execution_date"].astype(str) > cutoff).sum())
            realized_filled = filled.loc[filled["exit_status"].eq("FILLED")]
            support_violation_count += int((realized_filled["exit_execution_date"].astype(str) > support).sum())
            open_filled = filled.loc[filled["exit_status"].eq("OPEN_AT_CUTOFF")]
            support_violation_count += int((open_filled["exit_or_terminal_date"].astype(str) != cutoff).sum())

        expected_dates = _calendar_slice(calendar, start, support)
        curve_dates = curve["date"].astype(str).tolist()
        missing_for_result = len(set(expected_dates) - set(curve_dates)) + len(set(curve_dates) - set(expected_dates))
        if len(curve_dates) != len(expected_dates) or curve["date"].astype(str).duplicated().any() or curve_dates != expected_dates:
            missing_equity_dates += max(1, missing_for_result)

        cash = pd.to_numeric(curve["cash"], errors="coerce")
        invested = pd.to_numeric(curve["invested_market_value"], errors="coerce")
        equity = pd.to_numeric(curve["total_equity"], errors="coerce")
        negative_cash_count += int((cash < -1e-7).sum())
        curve_accounting_errors += int((~np.isclose(equity.to_numpy(dtype=float), cash.to_numpy(dtype=float) + invested.to_numpy(dtype=float), rtol=0, atol=1e-6)).sum())
        if not math.isclose(float(equity.iloc[-1]), float(summary["final_equity_krw"]), rel_tol=0, abs_tol=1e-6):
            summary_reconciliation_error_count += 1
        realized_pnl = pd.to_numeric(filled.loc[filled["exit_status"].eq("FILLED"), "realized_pnl_krw"], errors="coerce").sum()
        terminal_pnl = pd.to_numeric(filled.loc[filled["exit_status"].eq("OPEN_AT_CUTOFF"), "terminal_unrealized_pnl_krw"], errors="coerce").sum()
        if not math.isclose(float(realized_pnl), float(summary["realized_pnl_krw"]), rel_tol=0, abs_tol=1e-4):
            summary_reconciliation_error_count += 1
        if not math.isclose(float(terminal_pnl), float(summary["terminal_unrealized_pnl_krw"]), rel_tol=0, abs_tol=1e-4):
            summary_reconciliation_error_count += 1
        accounted_equity = float(summary["initial_equity_krw"]) + float(realized_pnl) + float(terminal_pnl)
        if not math.isclose(accounted_equity, float(summary["final_equity_krw"]), rel_tol=0, abs_tol=0.1):
            summary_reconciliation_error_count += 1
        cash_skip_reconciliation_error_count += abs(int(summary["CASH_SKIP_count"]) - len(cash_skipped))
        expected_cash_rate = len(cash_skipped) / candidate_count * 100.0 if candidate_count else 0.0
        if not math.isclose(float(summary["CASH_SKIP_rate_pct"] or 0.0), expected_cash_rate, rel_tol=0, abs_tol=1e-10):
            cash_skip_reconciliation_error_count += 1
        if (not filled.empty) and filled["trade_identity"].duplicated().any():
            filled_identity_duplicate_count += 1
        if (not filled.empty) and pd.to_numeric(filled["buy_notional_krw"], errors="coerce").gt(float(job["position_cap_krw"]) + 1e-7).any():
            position_cap_violation_count += int(pd.to_numeric(filled["buy_notional_krw"], errors="coerce").gt(float(job["position_cap_krw"]) + 1e-7).sum())
        position_cap_violation_count += int(summary["position_cap_violation_count"])
        holding_period_mismatch_count += int(item["holding_period_source_mismatch_count"])
        cash_reconstruction_error_count += int(summary["cash_reconstruction_error_count"]) + int(summary["cash_audit_error_count"])
        leverage_result_count += int(float(summary["leverage_usage_krw"]) != 0.0)
        initial_capital_mismatch_count += int(float(summary["initial_equity_krw"]) != INITIAL_CAPITAL_KRW)
        position_cap_mismatch_count += int(float(summary["per_ticker_position_cap_krw"]) != POSITION_SCENARIOS[summary["scenario_id"]])

        # Reconcile MDD, return, and CAGR independently from the saved daily curve.
        curve_peak = equity.cummax()
        curve_drawdown_pct = (equity / curve_peak - 1.0) * 100.0
        recomputed_mdd = float(curve_drawdown_pct.min())
        if not math.isclose(recomputed_mdd, float(summary["MDD_pct"]), rel_tol=0, abs_tol=1e-8):
            summary_reconciliation_error_count += 1
        recomputed_return = (float(equity.iloc[-1]) / INITIAL_CAPITAL_KRW - 1.0) * 100.0
        if not math.isclose(recomputed_return, float(summary["total_return_pct"]), rel_tol=0, abs_tol=1e-8):
            summary_reconciliation_error_count += 1
        elapsed_days = max(1, (pd.Timestamp(support) - pd.Timestamp(start)).days)
        recomputed_cagr = (float(equity.iloc[-1]) / INITIAL_CAPITAL_KRW) ** (365.25 / elapsed_days) - 1.0
        if abs(recomputed_cagr * 100.0 - float(summary["CAGR_pct"])) > PERCENT_POINT_TOLERANCE:
            summary_reconciliation_error_count += 1

        nonfinite = 0
        for field in numeric_metrics:
            value = summary.get(field)
            if value is None or pd.isna(value):
                if field in {"win_rate_pct", "mean_return_pct", "median_return_pct"} and int(summary["realized_trades"]) == 0:
                    continue
                if field.startswith(("mean_holding", "median_holding", "p25_holding", "p75_holding", "p90_holding", "max_holding")) and int(summary["filled_entries"]) == 0:
                    continue
                nonfinite += 1
            elif not math.isfinite(float(value)):
                nonfinite += 1
        metric_nonfinite_count += nonfinite

        per_result.append({
            "scenario_id": summary["scenario_id"],
            "window_id": summary["window_id"],
            "strategy_id": summary["strategy_id"],
            "source_candidate_count": source_count,
            "portfolio_candidate_count": candidate_count,
            "filled_entries": len(filled),
            "CASH_SKIP_count": len(cash_skipped),
            "realized_trades": int(summary["realized_trades"]),
            "open_at_cutoff_positions": int(summary["open_at_cutoff_positions"]),
            "missing_equity_date_count": 0 if curve_dates == expected_dates else missing_for_result,
            "negative_cash_count": int((cash < -1e-7).sum()),
            "leverage_usage_krw": float(summary["leverage_usage_krw"]),
            "cash_reconstruction_error_count": int(summary["cash_reconstruction_error_count"]),
            "holding_period_source_mismatch_count": int(item["holding_period_source_mismatch_count"]),
            "summary_reconciliation_pass": candidate_count == source_count and math.isclose(accounted_equity, float(summary["final_equity_krw"]), rel_tol=0, abs_tol=0.1),
            "required_metric_nan_inf_count": nonfinite,
        })

    final_hashes = {name: _sha256(path) for name, path in _input_paths(root).items()}
    final_hashes["raw_store_manifest"] = _sha256(root / engine.v03.RAW_STORE_REL / "manifest.sqlite3")
    checks["initial_capital_250m_exact"] = initial_capital_mismatch_count == 0 and len(results) == 20
    checks["position_sizing_15m_25m_exact"] = position_cap_mismatch_count == 0 and {POSITION_SCENARIOS[job["scenario_id"]] for job in jobs} == {15_000_000.0, 25_000_000.0}
    checks["negative_cash_0"] = negative_cash_count == 0
    checks["leverage_0"] = leverage_result_count == 0 and all(float(item["summary"]["leverage_usage_krw"]) == 0.0 for item in results)
    checks["duplicate_fill_identity_0"] = filled_identity_duplicate_count == 0
    checks["entry_before_effective_start_0"] = entry_before_span_count == 0
    checks["post_cutoff_new_entry_0"] = post_cutoff_entry_count == 0
    checks["execution_support_violation_0"] = support_violation_count == 0
    checks["missing_daily_equity_date_0"] = missing_equity_dates == 0
    checks["required_metrics_nan_inf_0"] = metric_nonfinite_count == 0
    checks["summary_reconciliation_pass"] = summary_reconciliation_error_count == 0 and curve_accounting_errors == 0
    checks["CASH_SKIP_ledger_reconciliation_pass"] = cash_skip_reconciliation_error_count == 0
    checks["cash_and_sizing_audit_pass"] = cash_reconstruction_error_count == 0 and position_cap_violation_count == 0
    checks["holding_period_source_parity_pass"] = holding_period_mismatch_count == 0
    checks["certified_inputs_unchanged"] = dict(initial_hashes) == final_hashes
    checks["portfolio_results_20_exact"] = checks["portfolio_results_20_exact"]
    for name, passed in checks.items():
        if not passed:
            errors.append(name.upper())

    return {
        "verdict": "ETF_36_REALISTIC_PORTFOLIO_AFAST_V2_VS_JULIA_15M_25M_PASS" if not errors else "CHECK_REQUIRED",
        "passed": not errors,
        "checks": checks,
        "errors": sorted(set(errors)),
        "input_counts": dict(preflight["authority_counts"]),
        "portfolio_counts": {
            "portfolio_result_count": int(len(results)),
            "candidate_entries": total_candidate_count,
            "filled_entries": total_filled_count,
            "CASH_SKIP_count": total_cash_skip_count,
            "realized_trades": total_realized_count,
            "open_at_cutoff_positions": total_open_count,
            "duplicate_fill_identity_count": filled_identity_duplicate_count,
            "entry_before_effective_start_count": entry_before_span_count,
            "post_cutoff_new_entry_count": post_cutoff_entry_count,
            "execution_support_violation_count": support_violation_count,
            "missing_daily_equity_date_count": missing_equity_dates,
            "negative_cash_count": negative_cash_count,
            "leverage_result_count": leverage_result_count,
            "required_metric_nan_inf_count": metric_nonfinite_count,
            "summary_reconciliation_error_count": summary_reconciliation_error_count,
            "cash_skip_reconciliation_error_count": cash_skip_reconciliation_error_count,
            "cash_and_sizing_audit_error_count": cash_reconstruction_error_count + position_cap_violation_count,
            "holding_period_source_mismatch_count": holding_period_mismatch_count,
        },
        "per_portfolio_checks": per_result,
        "initial_capital_krw": INITIAL_CAPITAL_KRW,
        "position_scenarios_krw": POSITION_SCENARIOS,
        "window_definitions": {
            window: {"start": values[0], "cutoff": values[1], "execution_support": values[2]}
            for window, values in EXPECTED_WINDOWS.items()
        },
        "worker_count": WORKERS,
        "portfolio_run_attempt_count": 1,
        "market_refetch_count": 0,
        "signal_regeneration_count": 0,
        "clean_ready_recompute_count": 0,
        "forty_day_recomputation_count": 0,
        "new_tax_rule_count": 0,
        "percent_point_tolerance": PERCENT_POINT_TOLERANCE,
        "source_hashes_after_run": final_hashes,
        "preflight": dict(preflight),
    }


def _filled_trade_rows(results: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for item in results:
        job = item["job"]
        ledger = item["ledger"]
        filled = ledger.loc[ledger["entry_status"].eq("FILLED")]
        for row in filled.to_dict(orient="records"):
            is_closed = str(row["exit_status"]) == "FILLED"
            entry_cost = float(row["buy_cash_cost_krw"])
            if is_closed:
                net_return = float(row["realized_net_return_pct"])
                exit_price = float(row["sell_fill_price"])
                realized_pnl = float(row["realized_pnl_krw"])
                terminal_pnl: float | None = None
                exit_execution = row["exit_execution_date"]
            else:
                net_return = float(row["terminal_unrealized_pnl_krw"]) / entry_cost * 100.0
                exit_price = None
                realized_pnl = None
                terminal_pnl = float(row["terminal_unrealized_pnl_krw"])
                exit_execution = None
            output.append({
                "scenario_id": job["scenario_id"],
                "window_id": job["window_id"],
                "strategy_id": job["strategy_id"],
                "strategy_label": job["strategy_label"],
                "ticker": str(row["ticker"]).zfill(6),
                "ETF_name": row.get("name", ""),
                "major_category": row.get("major_category", row.get("category", "")),
                "trade_identity": row["trade_identity"],
                "signal_date": row["signal_date"],
                "entry_execution_date": row["entry_execution_date"],
                "entry_reference_open": float(row["entry_price_raw_open"]),
                "entry_price": float(row["buy_fill_price"]),
                "allocated_capital_krw": entry_cost,
                "allocated_notional_krw": float(row["buy_notional_krw"]),
                "quantity": int(row["shares"]),
                "exit_signal_date": row.get("exit_signal_date", ""),
                "exit_execution_date": exit_execution,
                "exit_reference_open": row.get("exit_price_raw_open") if is_closed else None,
                "exit_price": exit_price,
                "terminal_mark_price": float(row["terminal_price_raw"]) if row.get("terminal_price_raw") not in (None, "") else None,
                "trade_status": row["trade_status"],
                "portfolio_exit_status": row["exit_status"],
                "holding_krx_sessions": int(row["holding_krx_sessions_inclusive"]),
                "holding_calendar_days": int((pd.Timestamp(row["exit_execution_date"] if is_closed else row["cutoff_date"]) - pd.Timestamp(row["entry_execution_date"])).days),
                "gross_return_pct": float(pd.to_numeric(row["gross_return_pct"], errors="coerce")),
                "net_pre_tax_return_pct": net_return,
                "return_basis": "REALIZED_AFTER_COSTS" if is_closed else "CUTOFF_MARK_TO_MARKET_NO_HYPOTHETICAL_EXIT_COSTS",
                "realized_pnl_krw": realized_pnl,
                "terminal_unrealized_pnl_krw": terminal_pnl,
                "portfolio_cash_before_entry_krw": float(row["portfolio_cash_before_entry_krw"]),
                "portfolio_cash_after_entry_krw": float(row["portfolio_cash_after_entry_krw"]),
                "buy_commission_krw": float(row["buy_commission_krw"]),
                "sell_commission_krw": float(row["sell_commission_krw"]) if is_closed else None,
                "sell_tax_krw": float(row["sell_tax_krw"]) if is_closed else None,
            })
    return pd.DataFrame(output)


def _cash_skip_rows(results: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for item in results:
        job = item["job"]
        ledger = item["ledger"]
        skipped = ledger.loc[ledger["entry_status"].eq("CASH_SKIP")]
        for row in skipped.to_dict(orient="records"):
            output.append({
                "scenario_id": job["scenario_id"],
                "window_id": job["window_id"],
                "strategy_id": job["strategy_id"],
                "strategy_label": job["strategy_label"],
                "ticker": str(row["ticker"]).zfill(6),
                "ETF_name": row.get("name", ""),
                "signal_date": row["signal_date"],
                "intended_entry_date": row["entry_execution_date"],
                "required_capital_krw": float(row["required_cash_for_sized_order_krw"]),
                "required_one_share_cash_krw": float(row["required_cash_for_one_share_krw"]),
                "available_cash_krw": float(row["available_cash_krw"]),
                "position_cap_krw": float(job["position_cap_krw"]),
                "intended_shares": int(row["intended_shares"]),
                "reference_entry_open": float(row["entry_price_raw_open"]),
                "skip_reason": row.get("cash_skip_reason", "INSUFFICIENT_CASH_FOR_FULL_POSITION"),
            })
    return pd.DataFrame(output)


def _comparison_rows(summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    strategy_rows: list[dict[str, Any]] = []
    sizing_rows: list[dict[str, Any]] = []
    for (window_id, scenario_id), part in summary.groupby(["window_id", "scenario_id"], sort=False):
        by_strategy = part.set_index("strategy_id")
        if set(STRATEGY_ORDER) == set(by_strategy.index):
            v2, julia = (by_strategy.loc[strategy] for strategy in STRATEGY_ORDER)
            strategy_rows.append({
                "window_id": window_id,
                "scenario_id": scenario_id,
                "julia_minus_v2_CAGR_pp": float(julia["CAGR_pct"] - v2["CAGR_pct"]),
                "julia_minus_v2_final_equity_krw": float(julia["final_equity_krw"] - v2["final_equity_krw"]),
                "julia_minus_v2_MDD_pp": float(julia["MDD_pct"] - v2["MDD_pct"]),
                "julia_minus_v2_CASH_SKIP_count": int(julia["CASH_SKIP_count"] - v2["CASH_SKIP_count"]),
                "julia_minus_v2_average_utilization_pp": float(julia["average_capital_utilization_pct"] - v2["average_capital_utilization_pct"]),
                "julia_minus_v2_mean_holding_sessions": float(julia["mean_holding_sessions"] - v2["mean_holding_sessions"]),
                "julia_minus_v2_median_holding_sessions": float(julia["median_holding_sessions"] - v2["median_holding_sessions"]),
                "julia_minus_v2_mean_holding_calendar_days": float(julia["mean_holding_calendar_days"] - v2["mean_holding_calendar_days"]),
            })
    for (window_id, strategy_id), part in summary.groupby(["window_id", "strategy_id"], sort=False):
        by_scenario = part.set_index("scenario_id")
        if set(POSITION_SCENARIOS) == set(by_scenario.index):
            small, large = by_scenario.loc["15M"], by_scenario.loc["25M"]
            sizing_rows.append({
                "window_id": window_id,
                "strategy_id": strategy_id,
                "strategy_label": small["strategy_label"],
                "25M_minus_15M_final_equity_krw": float(large["final_equity_krw"] - small["final_equity_krw"]),
                "25M_minus_15M_CAGR_pp": float(large["CAGR_pct"] - small["CAGR_pct"]),
                "25M_minus_15M_MDD_pp": float(large["MDD_pct"] - small["MDD_pct"]),
                "25M_minus_15M_CASH_SKIP_count": int(large["CASH_SKIP_count"] - small["CASH_SKIP_count"]),
                "25M_minus_15M_average_utilization_pp": float(large["average_capital_utilization_pct"] - small["average_capital_utilization_pct"]),
                "25M_minus_15M_mean_holding_sessions": float(large["mean_holding_sessions"] - small["mean_holding_sessions"]),
                "25M_minus_15M_median_holding_sessions": float(large["median_holding_sessions"] - small["median_holding_sessions"]),
            })
    return pd.DataFrame(strategy_rows), pd.DataFrame(sizing_rows)


def _fmt(value: Any, suffix: str = "", digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    if suffix == " KRW":
        return f"{float(value):,.0f}{suffix}"
    return f"{float(value):,.{digits}f}{suffix}"


def _render_summary(
    summary: pd.DataFrame,
    holding_summary: pd.DataFrame,
    strategy_deltas: pd.DataFrame,
    sizing_deltas: pd.DataFrame,
    validation: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> str:
    verdict = str(validation["verdict"])
    lines = [
        "# ETF-36 Realistic Portfolio — A FAST Core V2 vs Julia V00 — 15M / 25M V01",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        "## Authority and execution contract",
        "",
        "- Input: certified clean-eligibility closure ledger (505 trades), frozen effective spans, official ETF universe (36). No signal regeneration or clean-ready recalculation.",
        "- Portfolio matrix: 5 standard windows × 2 strategies × 2 position caps = 20 results; initial equity is 250,000,000 KRW in every result; worker count is 10.",
        "- The reused realistic engine keeps integer-share fills, no partial buys, no leverage, no concurrent position cap, deterministic ticker/ISU/signal/entry ordering, exits before entries, same-session sale proceeds reusable, and full-size cash-shortage `CASH_SKIP`.",
        f"- Existing cost contract: buy/sell commission {engine.BUY_FEE_RATE * 100:.4f}% each side; buy/sell slippage {engine.BUY_SLIPPAGE_RATE * 100:.2f}% each side; ETF sell tax {engine.ETF_SELL_TAX_RATE:.2f}%. No new tax rule.",
        "- Local raw ETF daily closes value positions through each cutoff. Realized exits on the execution-support session use its open. Remaining open positions retain the exact cutoff close on the support-date curve, with no hypothetical exit costs.",
        "- 15M vs 25M is position-sizing sensitivity only. This report makes no strategy-adoption decision.",
        "",
        "## Four-case comparison by window",
        "",
        "Each cell reports final equity / CAGR / MDD / CASH_SKIP count and rate / average capital utilization / mean and median holding sessions.",
        "",
        "| Window | A FAST / 15M | Julia / 15M | A FAST / 25M | Julia / 25M |",
        "|---|---|---|---|---|",
    ]
    ordered_windows = list(EXPECTED_WINDOWS)
    for window in ordered_windows:
        cells: list[str] = []
        for scenario, strategy in (("15M", STRATEGY_ORDER[0]), ("15M", STRATEGY_ORDER[1]), ("25M", STRATEGY_ORDER[0]), ("25M", STRATEGY_ORDER[1])):
            part = summary.loc[summary["window_id"].eq(window) & summary["scenario_id"].eq(scenario) & summary["strategy_id"].eq(strategy)]
            if part.empty:
                cells.append("CHECK_REQUIRED")
                continue
            row = part.iloc[0]
            cells.append(
                f"{_fmt(row['final_equity_krw'], ' KRW', 0)} / {_fmt(row['CAGR_pct'], '%')} / {_fmt(row['MDD_pct'], '%')} / "
                f"{int(row['CASH_SKIP_count'])} ({_fmt(row['CASH_SKIP_rate_pct'], '%')}) / "
                f"{_fmt(row['average_capital_utilization_pct'], '%')} / "
                f"{_fmt(row['mean_holding_sessions'], ' / ', 1)}{_fmt(row['median_holding_sessions'], '', 1)} sess"
            )
        lines.append(f"| {window} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Portfolio results — all 20 rows",
        "",
        "| Window | Scenario | Strategy | Final equity | Total return | CAGR | MDD | Realized PnL | Open terminal PnL | Filled / candidates | CASH_SKIP | Avg / max utilization | Avg / median holdings | Mean / median holding sessions |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"| {row['window_id']} | {row['scenario_id']} | {row['strategy_label']} | {_fmt(row['final_equity_krw'], ' KRW', 0)} | "
            f"{_fmt(row['total_return_pct'], '%')} | {_fmt(row['CAGR_pct'], '%')} | {_fmt(row['MDD_pct'], '%')} | "
            f"{_fmt(row['realized_pnl_krw'], ' KRW', 0)} | {_fmt(row['terminal_unrealized_pnl_krw'], ' KRW', 0)} | "
            f"{int(row['filled_entries'])} / {int(row['candidate_entries'])} | {int(row['CASH_SKIP_count'])} ({_fmt(row['CASH_SKIP_rate_pct'], '%')}) | "
            f"{_fmt(row['average_capital_utilization_pct'], '%')} / {_fmt(row['max_capital_utilization_pct'], '%')} | "
            f"{_fmt(row['average_concurrent_holdings'], '', 2)} / {_fmt(row['median_concurrent_holdings'], '', 2)} | "
            f"{_fmt(row['mean_holding_sessions'], '', 1)} / {_fmt(row['median_holding_sessions'], '', 1)} |"
        )

    lines += [
        "",
        "## Holding-period distribution",
        "",
        "Sessions are inclusive KRX sessions from entry execution through realized exit execution or cutoff for open positions. Calendar days are the date difference between those endpoints. Closed and open-at-cutoff positions are shown separately.",
        "",
        "| Window | Scenario | Strategy | Holding class | Filled positions | Mean sessions | Median | P25 | P75 | P90 | Max | Mean / median calendar days |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in holding_summary.to_dict(orient="records"):
        lines.append(
            f"| {row['window_id']} | {row['scenario_id']} | {row['strategy_label']} | {row['holding_class']} | {int(row['filled_position_count'])} | "
            f"{_fmt(row['mean_holding_sessions'], '', 1)} | {_fmt(row['median_holding_sessions'], '', 1)} | "
            f"{_fmt(row['p25_holding_sessions'], '', 1)} | {_fmt(row['p75_holding_sessions'], '', 1)} | {_fmt(row['p90_holding_sessions'], '', 1)} | "
            f"{_fmt(row['max_holding_sessions'], '', 0)} | {_fmt(row['mean_holding_calendar_days'], '', 1)} / {_fmt(row['median_holding_calendar_days'], '', 1)} |"
        )

    lines += [
        "",
        "## Strategy differences within each sizing scenario",
        "",
        "Positive holding-period differences mean Julia held filled positions longer. These are descriptive co-movements with cash use and MDD, not causal estimates.",
        "",
        "| Window | Scenario | Julia − V2 CAGR (pp) | Final equity (KRW) | MDD (pp) | CASH_SKIP | Avg utilization (pp) | Mean / median holding sessions | Mean holding calendar days |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in strategy_deltas.to_dict(orient="records"):
        lines.append(
            f"| {row['window_id']} | {row['scenario_id']} | {_fmt(row['julia_minus_v2_CAGR_pp'])} | {_fmt(row['julia_minus_v2_final_equity_krw'], ' KRW', 0)} | "
            f"{_fmt(row['julia_minus_v2_MDD_pp'])} | {int(row['julia_minus_v2_CASH_SKIP_count'])} | {_fmt(row['julia_minus_v2_average_utilization_pp'])} | "
            f"{_fmt(row['julia_minus_v2_mean_holding_sessions'], '', 1)} / {_fmt(row['julia_minus_v2_median_holding_sessions'], '', 1)} | {_fmt(row['julia_minus_v2_mean_holding_calendar_days'], '', 1)} |"
        )

    lines += [
        "",
        "## 25M minus 15M sizing sensitivity",
        "",
        "| Window | Strategy | Final equity (KRW) | CAGR (pp) | MDD (pp) | CASH_SKIP count | Avg utilization (pp) | Mean / median holding sessions |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sizing_deltas.to_dict(orient="records"):
        lines.append(
            f"| {row['window_id']} | {row['strategy_label']} | {_fmt(row['25M_minus_15M_final_equity_krw'], ' KRW', 0)} | {_fmt(row['25M_minus_15M_CAGR_pp'])} | "
            f"{_fmt(row['25M_minus_15M_MDD_pp'])} | {int(row['25M_minus_15M_CASH_SKIP_count'])} | {_fmt(row['25M_minus_15M_average_utilization_pp'])} | "
            f"{_fmt(row['25M_minus_15M_mean_holding_sessions'], '', 1)} / {_fmt(row['25M_minus_15M_median_holding_sessions'], '', 1)} |"
        )

    lines += [
        "",
        "## Validation and output files",
        "",
        f"- Validation verdict: `{validation['verdict']}`; all checks pass: `{validation['passed']}`.",
        f"- Preflight local-price checks: `{preflight['passed']}`; entry / realized-exit / open-terminal price mismatch: {preflight['entry_execution_price_mismatch_count']} / {preflight['realized_exit_execution_price_mismatch_count']} / {preflight['open_terminal_close_mismatch_count']}.",
        f"- Missing/invalid daily closes over all candidate holding spans: {preflight['candidate_holding_close_missing_or_invalid_count']}; local raw OHLC invalid rows: {preflight['raw_data_audit']['other_invalid_ohlc_rows']}.",
        f"- New trades / full signal replay / clean-ready recomputation / market refetch / 40D recomputation: 0 / 0 / 0 / 0 / 0. Portfolio ledger replays: {validation['portfolio_run_attempt_count']} batch of 20 results on {WORKERS} workers.",
        "- `portfolio_summary.csv`: all 20 portfolio metrics; `filled_trade_ledger.csv`: every filled position; `cash_skip_ledger.csv`: every cash-shortage skip; `holding_period_summary.csv`: holding distributions; `equity_curve.csv`: daily cash, market value, equity, holdings, utilization, and drawdown; `validation.json`: validation details.",
        "",
    ]
    return "\n".join(lines)


def _write_output_bundle(
    output_dir: Path,
    results: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    summary = pd.DataFrame([item["summary"] for item in results])
    holding_records: list[dict[str, Any]] = []
    for item in results:
        for holding_class in ("ALL_FILLED_POSITIONS", "CLOSED", "OPEN_AT_CUTOFF"):
            holding_records.append({
                "scenario_id": item["job"]["scenario_id"],
                "window_id": item["job"]["window_id"],
                "strategy_id": item["job"]["strategy_id"],
                "strategy_label": item["job"]["strategy_label"],
                **_holding_stats(item["holding_rows"], holding_class),
            })
    holdings = pd.DataFrame(holding_records)
    strategy_deltas, sizing_deltas = _comparison_rows(summary)
    _write_csv(output_dir / "portfolio_summary.csv", summary)
    _write_csv(output_dir / "filled_trade_ledger.csv", _filled_trade_rows(results))
    _write_csv(output_dir / "cash_skip_ledger.csv", _cash_skip_rows(results))
    _write_csv(output_dir / "holding_period_summary.csv", holdings)
    _write_csv(output_dir / "equity_curve.csv", pd.concat([item["curve"] for item in results], ignore_index=True))
    _write_csv(output_dir / "strategy_comparison_deltas.csv", strategy_deltas)
    _write_csv(output_dir / "sizing_sensitivity_deltas.csv", sizing_deltas)
    _write_json(output_dir / "validation.json", validation)
    (output_dir / "summary.md").write_text(
        _render_summary(summary, holdings, strategy_deltas, sizing_deltas, validation, preflight),
        encoding="utf-8",
    )


def _write_check_required_bundle(output_dir: Path, validation: Mapping[str, Any], error: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "portfolio_summary.csv", [], ["scenario_id", "window_id", "strategy_id", "run_status", "error"])
    _write_csv(output_dir / "filled_trade_ledger.csv", [], ["scenario_id", "window_id", "strategy_id", "trade_identity", "entry_status"])
    _write_csv(output_dir / "cash_skip_ledger.csv", [], ["scenario_id", "window_id", "strategy_id", "ticker", "skip_reason"])
    _write_csv(output_dir / "holding_period_summary.csv", [], ["scenario_id", "window_id", "strategy_id", "holding_class", "filled_position_count"])
    _write_csv(output_dir / "equity_curve.csv", [], ["scenario_id", "window_id", "strategy_id", "date", "cash", "invested_market_value", "total_equity", "concurrent_holdings", "capital_utilization_pct", "drawdown_pct"])
    _write_json(output_dir / "validation.json", validation)
    (output_dir / "summary.md").write_text(
        "# ETF-36 Realistic Portfolio — CHECK_REQUIRED\n\n"
        f"Portfolio result generation stopped at `{validation.get('blocked_stage', 'UNKNOWN')}`.\n\n"
        f"Reason: `{error}`\n\n"
        "No automatic correction or rerun was performed. Review `validation.json` before deciding the next step.\n",
        encoding="utf-8",
    )


def run_once(root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir or root / OUTPUT_REL
    if output_dir.exists():
        raise RuntimeError(f"OUTPUT_DIR_ALREADY_EXISTS_NO_RERUN:{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    portfolio_attempt_count = 0
    stage = "AUTHORITY_PREFLIGHT"
    authorities: dict[str, Any] | None = None
    preflight: dict[str, Any] = {"passed": False}
    try:
        authorities = _load_authorities(root)
        if authorities["errors"]:
            failed = {
                "verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": stage,
                "authority_checks": authorities["checks"], "authority_counts": authorities["counts"],
                "errors": authorities["errors"], "portfolio_run_attempt_count": 0,
            }
            _write_check_required_bundle(output_dir, failed, ",".join(authorities["errors"]))
            return failed

        stage = "LOCAL_RAW_PREFLIGHT"
        universe = authorities["universe"]
        with tempfile.TemporaryDirectory(prefix="etf36_realistic_portfolio_") as temp_dir:
            db_path = Path(temp_dir) / "certified_etf_prices.sqlite3"
            data_info = engine.v03._build_price_database(db_path, root / engine.v03.RAW_STORE_REL, universe)
            preflight = _raw_price_checks(authorities["ledger"], universe, db_path, data_info)
            preflight["authority_checks"] = authorities["checks"]
            preflight["authority_counts"] = authorities["counts"]
            preflight["authority_errors"] = authorities["errors"]
            if not preflight["passed"]:
                failed = {
                    "verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": stage,
                    "preflight": preflight, "errors": ["LOCAL_RAW_PRICE_PREFLIGHT_FAILED"],
                    "portfolio_run_attempt_count": 0,
                    "market_refetch_count": 0,
                }
                _write_check_required_bundle(output_dir, failed, "Local cached prices did not satisfy the certified-ledger valuation checks.")
                return failed

            calendar = list(preflight.pop("calendar_dates_internal"))
            tickers = list(preflight.pop("loaded_candidate_tickers"))
            input_hashes = dict(authorities["source_hashes"])
            raw_manifest_path = root / engine.v03.RAW_STORE_REL / "manifest.sqlite3"
            input_hashes["raw_store_manifest"] = _sha256(raw_manifest_path)
            preflight["source_hashes"] = input_hashes
            jobs = _make_jobs(authorities["ledger"], authorities["label_by_strategy"])
            categories = dict(authorities["category_by_ticker"])
            stage = "PORTFOLIO_RUN"
            portfolio_attempt_count = 1
            _write_json(output_dir / "full_run_attempted.json", {
                "portfolio_run_attempt_count": portfolio_attempt_count,
                "worker_count": WORKERS,
                "portfolio_result_count": len(jobs),
                "started_at_local": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
                "input_ledger_sha256": authorities["source_hashes"]["certified_trade_ledger"],
                "market_refetch_count": 0,
                "signal_regeneration_count": 0,
                "note": "One batch only. A failed run must not be automatically repeated.",
            })
            del authorities
            gc.collect()
            results = _collect_results(jobs, db_path, tickers, calendar, categories)
            stage = "RESULT_VALIDATION"
            validation = _validate_results(results, jobs, calendar, preflight, input_hashes, root)
            validation["runtime_seconds"] = round(time.perf_counter() - started, 3)
            validation["portfolio_run_attempt_count"] = portfolio_attempt_count
            _write_output_bundle(output_dir, results, validation, preflight)
            return validation
    except Exception as exc:
        failure = {
            "verdict": "CHECK_REQUIRED",
            "passed": False,
            "blocked_stage": stage,
            "portfolio_run_attempt_count": portfolio_attempt_count,
            "worker_count": WORKERS,
            "error_type": type(exc).__name__,
            "error": str(exc)[:600],
            "preflight": preflight,
            "market_refetch_count": 0,
            "signal_regeneration_count": 0,
            "clean_ready_recompute_count": 0,
            "automatic_rerun_count": 0,
        }
        _write_check_required_bundle(output_dir, failure, failure["error"])
        return failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT_REL)
    args = parser.parse_args()
    result = run_once(ROOT, args.output.resolve())
    print(json.dumps(_json_safe({
        "verdict": result.get("verdict"),
        "passed": result.get("passed"),
        "blocked_stage": result.get("blocked_stage"),
        "errors": result.get("errors", []),
        "portfolio_counts": result.get("portfolio_counts", {}),
        "runtime_seconds": result.get("runtime_seconds"),
    }), ensure_ascii=False))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
