#!/usr/bin/env python3
"""Two-strategy KRX ETF portfolio battle using the V06 raw-price contract."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import sqlite3
import tempfile
import time
import warnings
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))
if str(ROOT / "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT / "src"))

from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as v03  # noqa: E402

V06_DIR = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v06"
V06_UNIVERSE_PATH = V06_DIR / "included_plain_long_universe_2026-09-29.csv"
V06_EXCLUSIONS_PATH = V06_DIR / "permanent_exclusions.csv"
V06_READINESS_PATH = V06_DIR / "etf_readiness.csv"
V06_LEDGER_PATH = V06_DIR / "trade_ledger.csv"
V06_SUMMARY_PATH = V06_DIR / "full_summary.json"
V06_VALIDATION_PATH = V06_DIR / "validation_report.json"
OUTPUT_DIR = ROOT / "artifacts/research/etf_v06_afast_vs_julia_realistic_portfolio_battle_v03"
FULL_ATTEMPT_MARKER = OUTPUT_DIR / "full_run_attempted.json"

GLOBAL_START = pd.Timestamp("2014-01-02")
CUTOFF = pd.Timestamp("2026-08-31")
EXECUTION_SUPPORT = pd.Timestamp("2026-09-01")
INITIAL_CAPITAL = 200_000_000.0
POSITION_CAP = 5_000_000.0
BUY_FEE_RATE = 0.00015
SELL_FEE_RATE = 0.00015
BUY_SLIPPAGE_RATE = 0.001
SELL_SLIPPAGE_RATE = 0.001
ETF_SELL_TAX_RATE = 0.0
WORKERS = 10

STRATEGY_A_FAST = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
STRATEGY_JULIA = "JULIA_STRATEGY_V00"
STRATEGIES = (STRATEGY_A_FAST, STRATEGY_JULIA)
CATEGORY_ORDER = ("MARKET_INDEX", "SECTOR_INDUSTRY", "COMMODITY_RESOURCE")
PERMANENT_EXCLUSIONS = {
    "269530": "PLUS S&P글로벌인프라",
    "265690": "ACE 러시아MSCI(합성)",
}
SAMPLE_TICKERS = ("192090", "203780", "069500", "133690", "091160")
SAMPLE_GROUPS = {
    "192090": "A", "203780": "A", "069500": "B", "133690": "B", "091160": "B",
}
ORDER_FIELDS = ("ticker", "ISU_CD", "signal_date", "entry_execution_date")

warnings.filterwarnings("ignore", category=FutureWarning, message=".*fill_method='pad'.*")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _truthy_contract_column(values: pd.Series) -> pd.Series:
    def parse(value: Any) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer)):
            return int(value) == 1
        return str(value).strip().lower() in {"true", "1", "yes", "y"}
    return values.map(parse)


def _clean_date(value: Any) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() in {"", "NaT", "nan", "None"}:
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _listing_anniversary(value: Any) -> str | None:
    listing = _clean_date(value)
    return (pd.Timestamp(listing) + pd.DateOffset(years=2)).strftime("%Y-%m-%d") if listing else None


def _can_evaluate_by_cutoff(common_start: Any) -> bool:
    start = _clean_date(common_start)
    return bool(start and pd.Timestamp(start) <= CUTOFF)


def _common_start(*values: Any) -> str | None:
    dates = [_clean_date(value) for value in values]
    if any(value is None for value in dates):
        return None
    return max(value for value in dates if value is not None)


def _first_session_after(signal_date: Any, calendar_dates: Sequence[Any]) -> str | None:
    signal = _clean_date(signal_date)
    if signal is None:
        return None
    if not calendar_dates:
        return None
    if isinstance(calendar_dates[0], str):
        index = bisect_right(calendar_dates, signal)
        return str(calendar_dates[index])[:10] if index < len(calendar_dates) else None
    normalized = [str(value)[:10] for value in calendar_dates]
    index = bisect_right(normalized, signal)
    return normalized[index] if index < len(normalized) else None


def _trade_execution_errors(trade: Mapping[str, Any], daily: pd.DataFrame, calendar_dates: Sequence[Any]) -> list[str]:
    errors: list[str] = []
    ticker = str(trade.get("ticker", ""))
    entry_signal = _clean_date(trade.get("signal_date"))
    entry_date = _clean_date(trade.get("entry_execution_date"))
    expected_entry = _first_session_after(entry_signal, calendar_dates)
    if expected_entry is None or entry_date != expected_entry:
        errors.append(f"EXECUTION_TIMING_MISMATCH:ENTRY:{ticker}:{entry_signal}:{entry_date}:{expected_entry}")
    elif pd.Timestamp(entry_date) not in daily.index or not math.isclose(
        float(daily.loc[pd.Timestamp(entry_date), "open"]),
        float(trade.get("entry_price_raw_open")), rel_tol=0, abs_tol=1e-8,
    ):
        errors.append(f"EXECUTION_PRICE_MISMATCH:ENTRY:{ticker}:{entry_date}")

    if str(trade.get("trade_status")) == "REALIZED":
        exit_signal = _clean_date(trade.get("exit_signal_date"))
        exit_date = _clean_date(trade.get("exit_execution_date"))
        expected_exit = _first_session_after(exit_signal, calendar_dates)
        if expected_exit is None or exit_date != expected_exit:
            errors.append(f"EXECUTION_TIMING_MISMATCH:EXIT:{ticker}:{exit_signal}:{exit_date}:{expected_exit}")
        elif pd.Timestamp(exit_date) not in daily.index or not math.isclose(
            float(daily.loc[pd.Timestamp(exit_date), "open"]),
            float(trade.get("exit_price_raw_open")), rel_tol=0, abs_tol=1e-8,
        ):
            errors.append(f"EXECUTION_PRICE_MISMATCH:EXIT:{ticker}:{exit_date}")
    elif str(trade.get("trade_status")) == "OPEN_AT_CUTOFF":
        if _clean_date(trade.get("exit_execution_date")) is not None:
            errors.append(f"OPEN_TERMINAL_HAS_EXIT_EXECUTION:{ticker}")
        if _clean_date(trade.get("exit_or_terminal_date")) != CUTOFF.strftime("%Y-%m-%d"):
            errors.append(f"TERMINAL_CUTOFF_DATE_MISMATCH:{ticker}")
        elif pd.Timestamp(CUTOFF) not in daily.index or not math.isclose(
            float(daily.loc[CUTOFF, "close"]),
            float(trade.get("terminal_price_raw")), rel_tol=0, abs_tol=1e-8,
        ):
            errors.append(f"TERMINAL_CUTOFF_PRICE_MISMATCH:{ticker}")
    return errors


def strict_no_trade_mask(daily: pd.DataFrame) -> pd.Series:
    required = {"volume", "open", "high", "low", "close"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"NO_TRADE_REQUIRED_COLUMNS_MISSING:{sorted(missing)}")
    return (
        pd.to_numeric(daily["volume"], errors="coerce").eq(0)
        & pd.to_numeric(daily["open"], errors="coerce").eq(0)
        & pd.to_numeric(daily["high"], errors="coerce").eq(0)
        & pd.to_numeric(daily["low"], errors="coerce").eq(0)
        & pd.to_numeric(daily["close"], errors="coerce").gt(0)
    )


def _invalid_ohlc_mask(daily: pd.DataFrame) -> pd.Series:
    ohlc = daily[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    values = ohlc.to_numpy(dtype=float)
    finite = pd.Series(np.isfinite(values).all(axis=1), index=daily.index)
    positive = ohlc.gt(0).all(axis=1)
    ordered = (
        ohlc["high"].ge(ohlc[["open", "close", "low"]].max(axis=1))
        & ohlc["low"].le(ohlc[["open", "close", "high"]].min(axis=1))
    )
    volume = pd.to_numeric(daily["volume"], errors="coerce")
    valid_volume = pd.Series(np.isfinite(volume.to_numpy(dtype=float)), index=daily.index) & volume.ge(0)
    return ~(finite & positive & ordered & valid_volume)


def split_technical_daily(daily_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(daily_raw.index, pd.DatetimeIndex) or daily_raw.index.has_duplicates:
        raise ValueError("RAW_DAILY_INDEX_INVALID")
    no_trade = strict_no_trade_mask(daily_raw)
    invalid = _invalid_ohlc_mask(daily_raw) & ~no_trade
    if invalid.any():
        examples = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in daily_raw.index[invalid][:10]]
        raise RuntimeError(f"OTHER_INVALID_OHLC_FAIL_CLOSED:{int(invalid.sum())}:{','.join(examples)}")
    return daily_raw.loc[~no_trade].copy(), daily_raw.loc[no_trade].copy()


def _load_authorities() -> tuple[list[dict[str, str]], dict[str, str | None], list[dict[str, Any]], dict[str, Any]]:
    required_paths = (V06_UNIVERSE_PATH, V06_EXCLUSIONS_PATH, V06_READINESS_PATH, V06_LEDGER_PATH, V06_SUMMARY_PATH, V06_VALIDATION_PATH)
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"V06_AUTHORITY_MISSING:{missing}")
    summary = json.loads(V06_SUMMARY_PATH.read_text(encoding="utf-8"))
    v06_validation = json.loads(V06_VALIDATION_PATH.read_text(encoding="utf-8"))
    if not v06_validation.get("passed") or not summary.get("aggregate_metrics_are_complete"):
        raise RuntimeError("V06_AUTHORITY_NOT_VALIDATED")
    if summary.get("RAW_PRICE_LIMITATION") is not True or summary.get("SURVIVORSHIP_BIAS") is not True or summary.get("adjusted_price_used") is not False:
        raise RuntimeError("V06_PRICE_BIAS_CONTRACT_MISMATCH")
    if set(v06_validation.get("permanent_exclusion_tickers", [])) != set(PERMANENT_EXCLUSIONS) or int(v06_validation.get("unauthorized_exclusion_count", -1)) != 0:
        raise RuntimeError("V06_VALIDATION_EXCLUSION_CONTRACT_MISMATCH")
    if summary.get("cutoff_date") != CUTOFF.strftime("%Y-%m-%d") or summary.get("execution_support_date") != EXECUTION_SUPPORT.strftime("%Y-%m-%d"):
        raise RuntimeError("V06_DATE_CONTRACT_MISMATCH")
    costs = summary.get("cost_contract", {})
    expected_costs = {
        "buy_commission_rate": BUY_FEE_RATE,
        "sell_commission_rate": SELL_FEE_RATE,
        "buy_slippage_rate": BUY_SLIPPAGE_RATE,
        "sell_slippage_rate": SELL_SLIPPAGE_RATE,
        "ETF_sell_tax_rate": ETF_SELL_TAX_RATE,
    }
    if any(not math.isclose(float(costs.get(key, -1)), value, rel_tol=0, abs_tol=1e-12) for key, value in expected_costs.items()):
        raise RuntimeError("V06_COST_CONTRACT_MISMATCH")

    universe_frame = pd.read_csv(V06_UNIVERSE_PATH, dtype={"ticker": "string", "ISU_CD": "string"})
    required = {"ticker", "ISU_CD", "ETF_name", "listing_date", "category", "plain_long", "include"}
    if not required.issubset(universe_frame.columns) or universe_frame.empty:
        raise RuntimeError(f"V06_UNIVERSE_SCHEMA_INVALID:{sorted(required - set(universe_frame.columns))}")
    universe_frame["ticker"] = universe_frame["ticker"].map(v03._norm_ticker)
    universe_frame["ISU_CD"] = universe_frame["ISU_CD"].astype(str).str.strip().str.upper()
    universe_frame["listing_date"] = pd.to_datetime(universe_frame["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if universe_frame["ticker"].duplicated().any() or universe_frame["ISU_CD"].duplicated().any():
        raise RuntimeError("V06_UNIVERSE_DUPLICATE_IDENTITY")
    if not universe_frame["category"].isin(CATEGORY_ORDER).all():
        raise RuntimeError("V06_UNIVERSE_UNKNOWN_CATEGORY")
    if not _truthy_contract_column(universe_frame["plain_long"]).all() or not _truthy_contract_column(universe_frame["include"]).all():
        raise RuntimeError("V06_UNIVERSE_NON_PLAIN_LONG_OR_NOT_INCLUDED")
    exclusions_frame = pd.read_csv(V06_EXCLUSIONS_PATH, dtype={"ticker": "string", "ISU_CD": "string"})
    if not {"ticker", "ISU_CD", "ETF_name", "category"}.issubset(exclusions_frame.columns):
        raise RuntimeError("V06_EXCLUSION_SCHEMA_INVALID")
    exclusions_frame["ticker"] = exclusions_frame["ticker"].map(v03._norm_ticker)
    if exclusions_frame["ticker"].duplicated().any() or set(exclusions_frame["ticker"]) != set(PERMANENT_EXCLUSIONS):
        raise RuntimeError("V06_EXCLUSION_AUTHORITY_MISMATCH")
    if set(universe_frame["ticker"]).intersection(PERMANENT_EXCLUSIONS):
        raise RuntimeError("V06_INCLUDED_UNIVERSE_CONTAINS_PERMANENT_EXCLUSION")
    for ticker, expected_name in PERMANENT_EXCLUSIONS.items():
        if str(exclusions_frame.loc[exclusions_frame.ticker.eq(ticker), "ETF_name"].iloc[0]) != expected_name:
            raise RuntimeError(f"V06_EXCLUSION_NAME_MISMATCH:{ticker}")
    active = universe_frame.copy()
    universe = [
        {"ticker": str(row.ticker), "ISU_CD": str(row.ISU_CD), "name": str(row.ETF_name),
         "listing_date": str(row.listing_date), "category": str(row.category)}
        for row in active.itertuples(index=False)
    ]

    readiness = pd.read_csv(V06_READINESS_PATH, dtype={"ticker": "string"})
    readiness["ticker"] = readiness["ticker"].map(v03._norm_ticker)
    if readiness["ticker"].duplicated().any():
        raise RuntimeError("V06_READINESS_DUPLICATE_TICKER")
    active_tickers = {row["ticker"] for row in universe}
    readiness_map = {str(row["ticker"]): _clean_date(row.get("common_evaluable_start")) for row in readiness.to_dict(orient="records")}
    if set(readiness_map) != active_tickers:
        raise RuntimeError("V06_READINESS_UNIVERSE_MISMATCH")
    for row in universe:
        row["v06_common_evaluable_start"] = readiness_map[row["ticker"]] or ""

    ledger_frame = pd.read_csv(V06_LEDGER_PATH, dtype={"ticker": "string", "ISU_CD": "string"})
    needed_ledger = {"strategy_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date", "trade_status", "source_signal_details"}
    if not needed_ledger.issubset(ledger_frame.columns):
        raise RuntimeError(f"V06_LEDGER_SCHEMA_INVALID:{sorted(needed_ledger - set(ledger_frame.columns))}")
    ledger_frame = ledger_frame.loc[ledger_frame["strategy_id"].isin(STRATEGIES)].copy()
    ledger_frame["ticker"] = ledger_frame["ticker"].map(v03._norm_ticker)
    if not set(ledger_frame["ticker"]).issubset(active_tickers):
        raise RuntimeError("V06_LEDGER_HAS_UNAUTHORIZED_ETF")
    baseline = ledger_frame.to_dict(orient="records")
    metadata = {
        "v06_universe_sha256": _sha256(V06_UNIVERSE_PATH),
        "v06_permanent_exclusions_sha256": _sha256(V06_EXCLUSIONS_PATH),
        "v06_readiness_sha256": _sha256(V06_READINESS_PATH),
        "v06_trade_ledger_sha256": _sha256(V06_LEDGER_PATH),
        "v06_full_summary_sha256": _sha256(V06_SUMMARY_PATH),
        "authority_ticker_count": int(len(universe_frame) + len(exclusions_frame)),
        "permanently_excluded_tickers": sorted(PERMANENT_EXCLUSIONS),
        "active_universe_count": int(len(universe)),
        "category_counts": {str(k): int(v) for k, v in active["category"].value_counts().sort_index().items()},
        "v06_baseline_trade_count_a_fast_julia": int(len(baseline)),
    }
    return universe, readiness_map, baseline, metadata


def _worker_process_instrument(instrument: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    ticker = v03._norm_ticker(instrument["ticker"])
    name, isu_cd = str(instrument["name"]), str(instrument["ISU_CD"])
    listing_date = str(instrument["listing_date"])
    v06_start = _clean_date(instrument.get("v06_common_evaluable_start"))
    errors: list[str] = []
    empty = {strategy: [] for strategy in STRATEGIES}
    daily_raw = v03._load_ticker_daily(ticker)
    if daily_raw.empty:
        return {**instrument, "ticker": ticker, "status": "NOT_EVALUABLE", "reason": "NO_RAW_PRICE_HISTORY", "common_evaluable_start": None, "trades": empty, "errors": [], "timings": {"ticker_total_seconds": round(time.perf_counter() - started, 4)}}
    daily_raw = daily_raw.loc[daily_raw.index >= pd.Timestamp(listing_date)].copy()
    if daily_raw.empty:
        return {**instrument, "ticker": ticker, "status": "NOT_EVALUABLE", "reason": "RAW_ROWS_PRECEDE_LISTING_DATE", "common_evaluable_start": None, "trades": empty, "errors": [], "timings": {"ticker_total_seconds": round(time.perf_counter() - started, 4)}}
    try:
        daily_technical, no_trade_rows = split_technical_daily(daily_raw)
    except Exception as exc:
        return {**instrument, "ticker": ticker, "status": "ERROR", "reason": "INVALID_RAW_OHLC", "common_evaluable_start": None, "trades": empty, "errors": [f"{type(exc).__name__}:{str(exc)[:300]}"], "timings": {"ticker_total_seconds": round(time.perf_counter() - started, 4)}}
    if daily_technical.empty:
        return {**instrument, "ticker": ticker, "status": "ERROR", "reason": "NO_TECHNICAL_ROWS", "common_evaluable_start": None, "trades": empty, "errors": ["NO_TECHNICAL_ROWS"], "timings": {"ticker_total_seconds": round(time.perf_counter() - started, 4)}}

    raw_start = max(pd.Timestamp(daily_raw.index.min()), pd.Timestamp(listing_date))
    observed_dates = set(daily_raw.index)
    expected = [pd.Timestamp(day) for day in v03._WORKER["calendar_dates"] if raw_start <= pd.Timestamp(day) <= EXECUTION_SUPPORT]
    missing_dates = [day.strftime("%Y-%m-%d") for day in expected if day not in observed_dates]
    cutoff_missing = CUTOFF not in daily_raw.index
    support_missing = EXECUTION_SUPPORT not in daily_raw.index
    if missing_dates:
        errors.append(f"RAW_SESSION_GAP:{len(missing_dates)}")

    context = v03.build_precomputed_ticker_context(ticker, name, daily_technical)
    fast_ready, fast_calls = v03._find_fast_ready_date(ticker, name, daily_technical, context, listing_date)
    _eligibility_all, _all_metrics, volume_ready, _all_audit = v03._raw_eligibility(daily_raw, listing_date, None)
    listing_anniversary = _listing_anniversary(listing_date)
    julia_ready = fast_ready
    common_start = _common_start(listing_anniversary, fast_ready, julia_ready, volume_ready)
    status = "EVALUABLE" if _can_evaluate_by_cutoff(common_start) and not cutoff_missing and not support_missing else "NOT_EVALUABLE"
    reasons: list[str] = []
    if not listing_anniversary or pd.Timestamp(listing_anniversary) > CUTOFF:
        reasons.append("LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF")
    if fast_ready is None:
        reasons.append("A_FAST_JULIA_NOT_READY_BY_CUTOFF")
    if volume_ready is None:
        reasons.append("20D_VOLUME_NOT_READY_BY_CUTOFF")
    if cutoff_missing:
        reasons.append("MISSING_EXACT_CUTOFF_CLOSE")
    if support_missing:
        reasons.append("MISSING_EXECUTION_SUPPORT_SESSION")
    if common_start and common_start > CUTOFF.strftime("%Y-%m-%d"):
        reasons.append("COMMON_START_AFTER_CUTOFF")
    if missing_dates:
        status = "ERROR"
        reasons.append("RAW_SESSION_GAP")

    trades = {strategy: [] for strategy in STRATEGIES}
    eligibility_metrics: dict[str, dict[str, Any]] = {}
    eligibility_audit: dict[str, Any] = {}
    eligible_dates: set[str] = set()
    if status == "EVALUABLE":
        eligible_dates, eligibility_metrics, _volume_ready_again, eligibility_audit = v03._raw_eligibility(daily_raw, listing_date, common_start)
        v03._WORKER["eligibility_metrics"] = eligibility_metrics
        fast_records = v03.simulate_ticker_core_v02_reentry(
            ticker=ticker, name=name, market="ETF", daily=daily_technical,
            score_contract=v03._WORKER["score_contract"], stage_contract=v03._WORKER["stage_contract"],
            cutoff_date=CUTOFF, snapshot_context=context, market_calendar=v03._WORKER["calendar"],
            entry_search_start=pd.Timestamp(common_start), signal_cutoff_date=CUTOFF,
            execution_support_date=EXECUTION_SUPPORT, strict_errors=True,
            entry_execution_cutoff_date=CUTOFF, entry_signal_cutoff_date=CUTOFF,
            entry_signal_filter=lambda d, _result: d.strftime("%Y-%m-%d") in eligible_dates,
        )
        trades[STRATEGY_A_FAST] = [
            v03._normalize_strategy_trade(record, STRATEGY_A_FAST, ticker, name, isu_cd, daily_raw, common_start)
            for record in fast_records
        ]
        julia_errors: list[str] = []
        julia_records = v03._run_julia(ticker, name, daily_technical, context, common_start, eligible_dates, julia_errors)
        errors.extend(julia_errors)
        trades[STRATEGY_JULIA] = [
            v03._normalize_strategy_trade(record, STRATEGY_JULIA, ticker, name, isu_cd, daily_raw, common_start)
            for record in julia_records
        ]
        for strategy_rows in trades.values():
            for trade in strategy_rows:
                trade["category"] = str(instrument["category"])
        for strategy, rows in trades.items():
            for trade in rows:
                if trade.get("signal_date") not in eligible_dates:
                    errors.append(f"ELIGIBILITY_MISMATCH:{strategy}:{trade.get('signal_date')}")
                if trade.get("price_source") != v03.DATA_SOURCE or trade.get("eligibility_policy_id") != v03.ELIGIBILITY_POLICY_ID:
                    errors.append(f"TRADE_CONTRACT_MISMATCH:{strategy}")
                if trade.get("signal_date", "") > CUTOFF.strftime("%Y-%m-%d") or trade.get("entry_execution_date", "") > CUTOFF.strftime("%Y-%m-%d"):
                    errors.append(f"POST_CUTOFF_ENTRY:{strategy}:{trade.get('signal_date')}")
                if trade.get("trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"}:
                    errors.append(f"UNKNOWN_TRADE_STATUS:{strategy}:{trade.get('trade_status')}")
                errors.extend(_trade_execution_errors(trade, daily_raw, v03._WORKER["calendar_dates"]))
    group = "UNCLASSIFIED"
    if common_start and v06_start:
        group = "A" if common_start == v06_start else "B" if common_start < v06_start else "UNEXPECTED_LATER_START"
    elif common_start and not v06_start:
        group = "NO_V06_START"
    return {
        **instrument,
        "ticker": ticker, "status": status, "reason": ";".join(reasons) if reasons else None,
        "common_evaluable_start": common_start, "listing_anniversary_ready_date": listing_anniversary,
        "a_fast_ready_date": fast_ready, "julia_ready_date": julia_ready, "volume_20d_ready_date": volume_ready,
        "v06_common_evaluable_start": v06_start, "common_start_group": group,
        "evaluable_end": CUTOFF.strftime("%Y-%m-%d") if status == "EVALUABLE" else None,
        "evaluable_years": (CUTOFF - pd.Timestamp(common_start)).days / 365.2425 if status == "EVALUABLE" and common_start else 0.0,
        "eligible_signal_date_count": len(eligible_dates), "eligibility_audit": eligibility_audit,
        "strict_no_trade_rows_excluded": int(len(no_trade_rows)),
        "no_trade_rows_in_technical_input": int(strict_no_trade_mask(daily_technical).sum()),
        "fast_readiness_evaluation_count": int(fast_calls),
        "price_first_date": pd.Timestamp(daily_raw.index.min()).strftime("%Y-%m-%d"),
        "price_last_date": pd.Timestamp(daily_raw.index.max()).strftime("%Y-%m-%d"),
        "has_exact_cutoff_close": not cutoff_missing, "has_exact_support_open": not support_missing,
        "missing_session_count": len(missing_dates), "trades": trades, "errors": errors,
        "price_source": v03.DATA_SOURCE, "eligibility_policy_id": v03.ELIGIBILITY_POLICY_ID,
        "timings": {"ticker_total_seconds": round(time.perf_counter() - started, 4)},
    }


def _signature(row: Mapping[str, Any], *, include_canonical_id: bool = False) -> tuple[Any, ...]:
    def number(value: Any) -> Any:
        if value is None or pd.isna(value) or str(value).strip() in {"", "nan", "None"}:
            return None
        return round(float(value), 10)
    def date(value: Any) -> Any:
        return _clean_date(value)
    details = row.get("source_signal_details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {}
    details = details if isinstance(details, Mapping) else {}
    signature = (
        str(row.get("strategy_id", "")), str(row.get("ticker", "")).zfill(6), str(row.get("ISU_CD", row.get("isu_cd", ""))),
        date(row.get("signal_date")), date(row.get("entry_execution_date")), number(row.get("entry_price_raw_open")),
        date(row.get("exit_signal_date")), date(row.get("exit_execution_date")), number(row.get("exit_price_raw_open")),
        date(row.get("exit_or_terminal_date")), number(row.get("terminal_price_raw")),
        str(row.get("trade_status", "")), str(row.get("exit_reason", "")),
        int(float(row.get("holding_krx_sessions_inclusive"))) if row.get("holding_krx_sessions_inclusive") not in (None, "", "nan") and not pd.isna(row.get("holding_krx_sessions_inclusive")) else None,
    )
    return signature + ((str(details.get("canonical_trade_id")) if details.get("canonical_trade_id") is not None else None,) if include_canonical_id else ())


def _trade_group(rows: Sequence[Mapping[str, Any]], ticker: str, strategy: str, *, lower: str | None = None) -> list[Mapping[str, Any]]:
    return [
        row for row in rows
        if str(row.get("ticker", "")).zfill(6) == ticker
        and str(row.get("strategy_id", "")) == strategy
        and (lower is None or (_clean_date(row.get("signal_date")) or "") >= lower)
    ]


def _path_comparison(old_rows: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]], *, exact: bool) -> dict[str, Any]:
    old_counts = Counter(_signature(row, include_canonical_id=exact) for row in old_rows)
    new_counts = Counter(_signature(row, include_canonical_id=exact) for row in new_rows)
    old_only = list((old_counts - new_counts).elements())
    new_only = list((new_counts - old_counts).elements())
    return {"pass": not old_only and not new_only, "old_trade_count": sum(old_counts.values()), "new_trade_count": sum(new_counts.values()), "old_only_count": len(old_only), "new_only_count": len(new_only), "old_only_examples": [list(row) for row in old_only[:5]], "new_only_examples": [list(row) for row in new_only[:5]]}


def _earlier_position_spans_old_start(rows: Sequence[Mapping[str, Any]], old_start: str | None) -> bool:
    if old_start is None:
        return False
    for row in rows:
        signal_date = _clean_date(row.get("signal_date"))
        end_date = _clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date"))
        if signal_date and signal_date < old_start and end_date and end_date >= old_start:
            return True
    return False


def _classify_group_b_divergence(
    old_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    common_start: str | None,
    v06_common_start: str | None,
) -> dict[str, Any]:
    comparison = _path_comparison(old_rows, new_rows, exact=False)
    if comparison["pass"]:
        return {"comparison": comparison, "divergence_class": "NO_DIVERGENCE", "evidence": {}}
    if not common_start or not v06_common_start:
        return {"comparison": comparison, "divergence_class": "POST_V06_UNEXPLAINED_DIVERGENCE", "evidence": {"reason": "MISSING_COMMON_START"}}

    remaining_old = Counter(_signature(row) for row in old_rows)
    new_only: list[Mapping[str, Any]] = []
    for row in new_rows:
        signature = _signature(row)
        if remaining_old[signature] > 0:
            remaining_old[signature] -= 1
        else:
            new_only.append(row)

    carryover_rows: list[Mapping[str, Any]] = []
    for row in new_only:
        entry = _clean_date(row.get("entry_execution_date"))
        end = _clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date"))
        if entry and end and common_start <= entry <= v06_common_start and end > v06_common_start:
            carryover_rows.append(row)
    if carryover_rows:
        return {
            "comparison": comparison,
            "divergence_class": "LIFECYCLE_CARRYOVER",
            "evidence": {
                "carryover_trade_count": len(carryover_rows),
                "carryover_trade_examples": [
                    {"signal_date": _clean_date(row.get("signal_date")),
                     "entry_execution_date": _clean_date(row.get("entry_execution_date")),
                     "exit_or_terminal_date": _clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date"))}
                    for row in carryover_rows[:5]
                ],
            },
        }

    pre_window_only = bool(new_only) and comparison["old_only_count"] == 0 and all(
        (entry := _clean_date(row.get("entry_execution_date"))) is not None
        and common_start <= entry
        and ((end := (_clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date")))) is not None)
        and end < v06_common_start
        for row in new_only
    )
    if pre_window_only:
        return {
            "comparison": comparison,
            "divergence_class": "PRE_V06_WINDOW_ONLY",
            "evidence": {
                "pre_v06_window_trade_count": len(new_only),
                "pre_v06_window_trade_examples": [
                    {"signal_date": _clean_date(row.get("signal_date")),
                     "entry_execution_date": _clean_date(row.get("entry_execution_date")),
                     "exit_or_terminal_date": _clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date"))}
                    for row in new_only[:5]
                ],
            },
        }
    return {
        "comparison": comparison,
        "divergence_class": "POST_V06_UNEXPLAINED_DIVERGENCE",
        "evidence": {
            "old_only_trade_count": comparison["old_only_count"],
            "new_only_trade_count": comparison["new_only_count"],
            "new_only_trade_examples": [
                {"signal_date": _clean_date(row.get("signal_date")),
                 "entry_execution_date": _clean_date(row.get("entry_execution_date")),
                 "exit_or_terminal_date": _clean_date(row.get("exit_execution_date")) or _clean_date(row.get("exit_or_terminal_date"))}
                for row in new_only[:5]
            ],
        },
    }


def _readiness_plan(universe: Sequence[Mapping[str, str]]) -> dict[str, dict[str, Any]]:
    readiness = pd.read_csv(V06_READINESS_PATH, dtype={"ticker": "string"})
    readiness["ticker"] = readiness["ticker"].map(v03._norm_ticker)
    plan: dict[str, dict[str, Any]] = {}
    active = {row["ticker"]: row for row in universe}
    for row in readiness.to_dict(orient="records"):
        ticker = str(row["ticker"])
        if ticker not in active:
            continue
        start = _common_start(
            _listing_anniversary(active[ticker]["listing_date"]),
            row.get("a_fast_ready_date"), row.get("julia_ready_date"), row.get("volume_20d_ready_date"),
        )
        old = _clean_date(row.get("common_evaluable_start"))
        if old and start == old:
            group = "A"
        elif old and start and start < old:
            group = "B"
        elif old and start and start > old:
            group = "UNEXPECTED_LATER_START"
        elif old and not start:
            group = "UNEXPECTED_NOT_READY"
        elif start and not old:
            group = "NO_V06_START"
        else:
            group = "UNCLASSIFIED"
        plan[ticker] = {"common_start": start, "v06_common_start": old, "group": group, "category": active[ticker]["category"], "name": active[ticker]["name"]}
    if set(plan) != set(active):
        raise RuntimeError("READINESS_PLAN_UNIVERSE_MISMATCH")
    return plan


def _choose_sample(universe: Sequence[Mapping[str, str]], plan: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    by_ticker = {row["ticker"]: row for row in universe}
    if any(ticker not in by_ticker for ticker in SAMPLE_TICKERS):
        raise RuntimeError("PREFLIGHT_SAMPLE_ETF_MISSING")
    for ticker, expected_group in SAMPLE_GROUPS.items():
        if plan[ticker]["group"] != expected_group:
            raise RuntimeError(f"PREFLIGHT_SAMPLE_GROUP_MISMATCH:{ticker}:{plan[ticker]['group']}:{expected_group}")
    sample = []
    for ticker in SAMPLE_TICKERS:
        item = dict(by_ticker[ticker])
        item["v06_common_evaluable_start"] = plan[ticker]["v06_common_start"] or ""
        sample.append(item)
    if sum(plan[row["ticker"]]["group"] == "A" for row in sample) < 2 or sum(plan[row["ticker"]]["group"] == "B" for row in sample) < 2:
        raise RuntimeError("PREFLIGHT_SAMPLE_GROUP_COVERAGE_FAIL")
    sample_categories = {plan[row["ticker"]]["category"] for row in sample if plan[row["ticker"]]["group"] == "B"}
    if not {"MARKET_INDEX", "SECTOR_INDUSTRY"}.issubset(sample_categories):
        raise RuntimeError("PREFLIGHT_SAMPLE_CATEGORY_COVERAGE_FAIL")
    names = {plan[row["ticker"]]["name"] for row in sample if plan[row["ticker"]]["group"] == "B"}
    # 069500 and 133690 explicitly cover domestic and overseas market index ETFs.
    if not {"069500", "133690", "091160"}.issubset({row["ticker"] for row in sample}):
        raise RuntimeError("PREFLIGHT_SAMPLE_REQUIRED_REPRESENTATIVES_MISSING")
    del names
    return sample


def _run_sample(sample: Sequence[dict[str, str]], data_info: Mapping[str, Any], db_path: Path, baseline: Sequence[Mapping[str, Any]], plan: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    score, stage = v03._read_contracts()
    outcomes: list[dict[str, Any]] = []
    max_workers = min(WORKERS, len(sample))
    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=v03._init_worker,
        initargs=(str(db_path), score, stage, data_info["calendar_dates_internal"], data_info["month_ends_internal"]),
    ) as pool:
        futures = {pool.submit(_worker_process_instrument, item): item for item in sample}
        for future in as_completed(futures):
            outcomes.append(future.result())
    outcomes.sort(key=lambda row: row["ticker"])
    parity_rows: list[dict[str, Any]] = []
    for result in outcomes:
        ticker = result["ticker"]
        group = plan[ticker]["group"]
        if result["status"] != "EVALUABLE":
            parity_rows.append({"ticker": ticker, "group": group, "status": result["status"], "pass": False, "reason": result.get("reason")})
            continue
        if result["common_evaluable_start"] != plan[ticker]["common_start"]:
            parity_rows.append({"ticker": ticker, "group": group, "status": "COMMON_START_MISMATCH", "pass": False})
            continue
        for strategy in STRATEGIES:
            old = _trade_group(baseline, ticker, strategy)
            new = result["trades"][strategy]
            comparison = _path_comparison(old, new, exact=(group == "A"))
            if group == "A":
                parity_rows.append({"ticker": ticker, "group": group, "strategy_id": strategy, "comparison": comparison, "pass": comparison["pass"]})
            else:
                old_start = plan[ticker]["v06_common_start"]
                classification = _classify_group_b_divergence(old, new, plan[ticker]["common_start"], old_start)
                reason = classification["divergence_class"]
                parity_rows.append({"ticker": ticker, "group": group, "strategy_id": strategy, **classification, "divergence_reason": reason, "pass": reason != "POST_V06_UNEXPLAINED_DIVERGENCE"})
    passed = all(row.get("pass") is True for row in parity_rows) and all(not result.get("errors") for result in outcomes)
    return {
        "verdict": "SAMPLE_PASS" if passed else "CHECK_REQUIRED",
        "sample_count": len(outcomes), "worker_count": max_workers,
        "sample_tickers": [{"ticker": row["ticker"], "category": plan[row["ticker"]]["category"], "group": plan[row["ticker"]]["group"], "v06_common_start": plan[row["ticker"]]["v06_common_start"], "common_start": row.get("common_evaluable_start"), "status": row["status"], "trade_counts": {strategy: len(row["trades"].get(strategy, [])) for strategy in STRATEGIES}, "errors": row.get("errors", [])} for row in outcomes],
        "group_a_parity_rows": [row for row in parity_rows if row["group"] == "A"],
        "group_b_divergence_rows": [row for row in parity_rows if row["group"] == "B"],
        "validation_passed": passed,
    }


def _audit_raw_data(db_path: Path, universe: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    listing = {row["ticker"]: row["listing_date"] for row in universe}
    total_rows = no_trade_rows = invalid_rows = zero_volume_rows = 0
    with sqlite3.connect(db_path) as connection:
        query = "SELECT ticker,date,open,high,low,close,volume FROM bars ORDER BY ticker,date"
        for chunk in pd.read_sql_query(query, connection, chunksize=100_000):
            chunk["ticker"] = chunk["ticker"].map(v03._norm_ticker)
            chunk["date"] = pd.to_datetime(chunk["date"])
            chunk["listing_date"] = chunk["ticker"].map(listing)
            chunk = chunk.loc[chunk["date"] >= pd.to_datetime(chunk["listing_date"])].copy()
            total_rows += int(len(chunk))
            if chunk.empty:
                continue
            no_trade = strict_no_trade_mask(chunk)
            no_trade_rows += int(no_trade.sum())
            volume = pd.to_numeric(chunk["volume"], errors="coerce")
            zero_volume_rows += int(volume.eq(0).sum())
            invalid_rows += int((_invalid_ohlc_mask(chunk) & ~no_trade).sum())
    return {"raw_rows_after_listing": total_rows, "strict_no_trade_session_rows": no_trade_rows, "zero_volume_rows_in_raw_eligibility_source": zero_volume_rows, "other_invalid_ohlc_rows": invalid_rows, "technical_input_no_trade_row_count": 0, "raw_rewrite_count": 0, "synthetic_or_forward_filled_rows": 0}


def _load_daily_frames(db_path: Path, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    if not tickers:
        return result
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        for ticker in sorted(set(tickers)):
            frame = pd.read_sql_query(
                "SELECT date,open,high,low,close,volume FROM bars WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
                connection, params=(ticker, GLOBAL_START.strftime("%Y-%m-%d"), EXECUTION_SUPPORT.strftime("%Y-%m-%d")),
            )
            if frame.empty:
                raise RuntimeError(f"RAW_PORTFOLIO_PRICE_HISTORY_MISSING:{ticker}")
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.set_index("date").sort_index()
            if frame.index.has_duplicates:
                raise RuntimeError(f"RAW_PORTFOLIO_PRICE_DUPLICATE_DATE:{ticker}")
            result[ticker] = frame
    return result


def _portfolio_price_universe(candidate_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted({v03._norm_ticker(row.get("ticker", "")) for row in candidate_rows if row.get("ticker")})


def _audit_candidate_price_coverage(
    db_path: Path,
    candidate_rows: Sequence[Mapping[str, Any]],
    lifecycle_results: Sequence[Mapping[str, Any]],
    authority_universe_count: int | None = None,
) -> dict[str, Any]:
    candidate_tickers = set(_portfolio_price_universe(candidate_rows))
    result_by_ticker = {str(row.get("ticker")): row for row in lifecycle_results}
    missing: list[dict[str, str]] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        for ticker in sorted(candidate_tickers):
            frame = pd.read_sql_query(
                "SELECT date,open,close FROM bars WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
                connection,
                params=(ticker, GLOBAL_START.strftime("%Y-%m-%d"), EXECUTION_SUPPORT.strftime("%Y-%m-%d")),
            )
            if frame.empty:
                missing.append({"ticker": ticker, "reason": "NO_RAW_ROWS"})
                continue
            frame["date"] = pd.to_datetime(frame["date"])
            if frame["date"].duplicated().any():
                missing.append({"ticker": ticker, "reason": "DUPLICATE_RAW_DATE"})
                continue
            indexed = frame.set_index("date")
            for day, field in ((CUTOFF, "close"), (EXECUTION_SUPPORT, "open")):
                if day not in indexed.index:
                    missing.append({"ticker": ticker, "reason": f"MISSING_EXACT_{field.upper()}:{day.date()}"})
                    continue
                value = pd.to_numeric(indexed.at[day, field], errors="coerce")
                if pd.isna(value) or not math.isfinite(float(value)) or float(value) <= 0:
                    missing.append({"ticker": ticker, "reason": f"INVALID_EXACT_{field.upper()}:{day.date()}"})
    raw_gap_count = sum(
        int(result_by_ticker.get(ticker, {}).get("missing_session_count", 0))
        for ticker in candidate_tickers
    )
    return {
        "checked": True,
        "authority_universe_ticker_count": authority_universe_count,
        "candidate_trade_ticker_count": len(candidate_tickers),
        "portfolio_price_requested_ticker_count": len(candidate_tickers),
        "zero_candidate_etf_count": max(0, int(authority_universe_count or 0) - len(candidate_tickers)),
        "price_requested_for_zero_candidate_etf_count": 0,
        "candidate_required_price_coverage_missing_count": len(missing),
        "candidate_required_price_coverage_missing": missing,
        "candidate_required_raw_session_gap_count": raw_gap_count,
        "candidate_tickers_without_candidate_trades": 0,
    }


def _exact_price(daily: Mapping[str, pd.DataFrame], ticker: str, day: pd.Timestamp, field: str) -> float:
    frame = daily.get(ticker)
    date = pd.Timestamp(day).normalize()
    if frame is None or date not in frame.index or field not in frame.columns:
        raise RuntimeError(f"MISSING_EXACT_{field.upper()}:{ticker}:{date.strftime('%Y-%m-%d')}")
    value = pd.to_numeric(frame.at[date, field], errors="coerce")
    if pd.isna(value) or not math.isfinite(float(value)) or float(value) <= 0:
        raise RuntimeError(f"INVALID_EXACT_{field.upper()}:{ticker}:{date.strftime('%Y-%m-%d')}")
    return float(value)


def _order_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("ISU_CD", row.get("isu_cd", ""))),
        _clean_date(row.get("signal_date")) or "",
        _clean_date(row.get("entry_execution_date")) or "",
    )


def _buy_sizing(reference_open: float, cash: float) -> dict[str, float | int | bool]:
    fill = float(reference_open) * (1.0 + BUY_SLIPPAGE_RATE)
    shares = int(math.floor(POSITION_CAP / fill + 1e-12))
    while shares > 0 and shares * fill > POSITION_CAP + 1e-7:
        shares -= 1
    notional = shares * fill
    fee = notional * BUY_FEE_RATE
    total = notional + fee
    return {"shares": shares, "fill_price": fill, "notional": notional, "fee": fee, "total_cost": total, "cash_sufficient": total <= float(cash)}


def _sell_proceeds(reference_open: float, shares: int) -> dict[str, float]:
    fill = float(reference_open) * (1.0 - SELL_SLIPPAGE_RATE)
    notional = fill * int(shares)
    fee = notional * SELL_FEE_RATE
    tax = notional * ETF_SELL_TAX_RATE
    return {"fill_price": fill, "notional": notional, "fee": fee, "tax": tax, "proceeds": notional - fee - tax}


def _mdd(curve: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(curve["total_equity"], errors="coerce")
    if values.isna().any() or values.empty:
        raise RuntimeError("EQUITY_CURVE_MISSING_OR_INVALID")
    peak = values.cummax()
    drawdown = values / peak - 1.0
    trough_index = int(drawdown.idxmin())
    peak_value = float(peak.loc[trough_index])
    prior = values.iloc[:trough_index + 1]
    peak_index = int(prior[prior.eq(peak_value)].index[-1])
    peak_date = str(curve.loc[peak_index, "date"])
    trough_date = str(curve.loc[trough_index, "date"])
    recovery_rows = curve.loc[curve.index > trough_index]
    recovery_rows = recovery_rows.loc[pd.to_numeric(recovery_rows["total_equity"]).ge(peak_value)]
    return {
        "mdd_pct": round(float(drawdown.min()) * 100.0, 8),
        "mdd_start_date": peak_date,
        "mdd_trough_date": trough_date,
        "mdd_recovery_date": str(recovery_rows.iloc[0]["date"]) if not recovery_rows.empty else None,
        "mdd_recovered": not recovery_rows.empty,
    }


def _portfolio_replay(
    candidate_rows: Sequence[Mapping[str, Any]],
    daily_by_ticker: Mapping[str, pd.DataFrame],
    calendar_dates: Sequence[Any],
    strategy_id: str,
    category_by_ticker: Mapping[str, str],
) -> dict[str, Any]:
    dates = [pd.Timestamp(day).normalize() for day in calendar_dates if GLOBAL_START <= pd.Timestamp(day).normalize() <= EXECUTION_SUPPORT]
    if not dates or dates[0] != GLOBAL_START or dates[-1] != EXECUTION_SUPPORT:
        raise RuntimeError("GLOBAL_MARKET_CALENDAR_BOUNDARY_MISMATCH")
    if CUTOFF not in dates:
        raise RuntimeError("GLOBAL_MARKET_CALENDAR_MISSING_CUTOFF")

    candidate_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    entries: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    exits: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for index, source in enumerate(candidate_rows):
        row = dict(source)
        row["ticker"] = str(row["ticker"]).zfill(6)
        row["ISU_CD"] = str(row.get("ISU_CD", row.get("isu_cd", "")))
        row["strategy_id"] = strategy_id
        row["category"] = category_by_ticker[row["ticker"]]
        key = (row["ticker"], row["ISU_CD"], _clean_date(row.get("signal_date")) or "", _clean_date(row.get("entry_execution_date")) or "")
        if key in candidate_by_key:
            raise RuntimeError(f"DUPLICATE_PORTFOLIO_ENTRY_ORDER_KEY:{key}")
        row["_key"] = key
        row["_row_number"] = index
        row["entry_status"] = "PENDING"
        row["exit_status"] = "NOT_CLOSED"
        row["shares"] = 0
        row["buy_reference_open"] = None
        row["buy_fill_price"] = None
        row["buy_notional_krw"] = 0.0
        row["buy_commission_krw"] = 0.0
        row["buy_cash_cost_krw"] = 0.0
        row["sell_reference_open"] = None
        row["sell_fill_price"] = None
        row["sell_notional_krw"] = 0.0
        row["sell_commission_krw"] = 0.0
        row["sell_tax_krw"] = 0.0
        row["sell_cash_proceeds_krw"] = 0.0
        row["realized_pnl_krw"] = None
        row["realized_net_return_pct"] = None
        row["terminal_market_value_krw"] = 0.0
        row["terminal_unrealized_pnl_krw"] = None
        candidate_by_key[key] = row
        entry_date = pd.Timestamp(key[3])
        if entry_date > CUTOFF:
            raise RuntimeError(f"POST_CUTOFF_NEW_ENTRY:{key}")
        if entry_date not in dates:
            raise RuntimeError(f"ENTRY_DATE_OUTSIDE_PORTFOLIO_CALENDAR:{key}")
        entries[entry_date].append(row)
        if str(row.get("trade_status")) == "REALIZED":
            exit_value = _clean_date(row.get("exit_execution_date"))
            if exit_value is None:
                raise RuntimeError(f"REALIZED_CANDIDATE_MISSING_EXIT_DATE:{key}")
            exit_date = pd.Timestamp(exit_value)
            if exit_date > EXECUTION_SUPPORT or exit_date not in dates:
                raise RuntimeError(f"EXIT_DATE_OUTSIDE_EXECUTION_SUPPORT:{key}:{exit_value}")
            exits[exit_date].append(row)
        elif str(row.get("trade_status")) != "OPEN_AT_CUTOFF":
            raise RuntimeError(f"UNKNOWN_CANDIDATE_STATUS:{key}:{row.get('trade_status')}")

    cash = INITIAL_CAPITAL
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    cash_shortage_count = 0
    open_position_skip_count = 0
    negative_cash_count = 0
    leverage_usage = 0.0
    oversized_position_count = 0
    cash_conservation_error_count = 0
    cutoff_snapshot: dict[str, Any] | None = None
    max_deployed = 0.0

    for day in dates:
        event_start = len(events)
        for row in sorted(exits.get(day, ()), key=_order_key):
            identity = (row["ticker"], row["ISU_CD"])
            position = positions.get(identity)
            if position is None:
                row["exit_status"] = "SKIP_UNFILLED_ENTRY"
                continue
            ref = _exact_price(daily_by_ticker, row["ticker"], day, "open")
            expected = float(row["exit_price_raw_open"])
            if not math.isclose(ref, expected, rel_tol=0, abs_tol=1e-8):
                raise RuntimeError(f"EXACT_EXIT_OPEN_MISMATCH:{row['ticker']}:{day.date()}:{ref}:{expected}")
            sale = _sell_proceeds(ref, int(position["shares"]))
            cash_before = cash
            cash += float(sale["proceeds"])
            pnl = float(sale["proceeds"]) - float(position["buy_cash_cost_krw"])
            net_return = pnl / float(position["buy_cash_cost_krw"]) * 100.0
            row.update({
                "exit_status": "FILLED", "sell_reference_open": ref,
                "sell_fill_price": sale["fill_price"], "sell_notional_krw": sale["notional"],
                "sell_commission_krw": sale["fee"], "sell_tax_krw": sale["tax"],
                "sell_cash_proceeds_krw": sale["proceeds"], "realized_pnl_krw": pnl,
                "realized_net_return_pct": net_return,
            })
            events.append({"date": day.strftime("%Y-%m-%d"), "strategy_id": strategy_id, "event_type": "EXIT", "event_status": "FILLED", "ticker": row["ticker"], "ISU_CD": row["ISU_CD"], "signal_date": row["exit_signal_date"], "entry_signal_date": row["signal_date"], "entry_execution_date": row["entry_execution_date"], "reference_open": ref, "fill_price": sale["fill_price"], "shares": int(position["shares"]), "cash_before": cash_before, "cash_after": cash, "notional_krw": sale["notional"], "commission_krw": sale["fee"], "tax_krw": sale["tax"], "candidate_order_key": list(_order_key(row))})
            positions.pop(identity)

        day_entries = sorted(entries.get(day, ()), key=_order_key)
        for row in day_entries:
            identity = (row["ticker"], row["ISU_CD"])
            if identity in positions:
                row["entry_status"] = "OPEN_POSITION_SKIP"
                open_position_skip_count += 1
                continue
            ref = _exact_price(daily_by_ticker, row["ticker"], day, "open")
            expected = float(row["entry_price_raw_open"])
            if not math.isclose(ref, expected, rel_tol=0, abs_tol=1e-8):
                raise RuntimeError(f"EXACT_ENTRY_OPEN_MISMATCH:{row['ticker']}:{day.date()}:{ref}:{expected}")
            sizing = _buy_sizing(ref, cash)
            shares = int(sizing["shares"])
            if shares <= 0 or not bool(sizing["cash_sufficient"]):
                row["entry_status"] = "CASH_SKIP"
                row["cash_skip_reason"] = "POSITION_CAP_BELOW_ONE_SHARE" if shares <= 0 else "INSUFFICIENT_CASH_FOR_FULL_POSITION"
                cash_shortage_count += 1
                continue
            cash_before = cash
            cash -= float(sizing["total_cost"])
            if cash < 0.0:
                negative_cash_count += 1
                raise RuntimeError("NEGATIVE_CASH_AFTER_BUY")
            if float(sizing["notional"]) > POSITION_CAP + 1e-7:
                oversized_position_count += 1
                raise RuntimeError("POSITION_NOTIONAL_OVER_5M")
            row.update({
                "entry_status": "FILLED", "shares": shares,
                "buy_reference_open": ref, "buy_fill_price": sizing["fill_price"],
                "buy_notional_krw": sizing["notional"], "buy_commission_krw": sizing["fee"],
                "buy_cash_cost_krw": sizing["total_cost"],
            })
            positions[identity] = {
                "row": row, "shares": shares, "buy_cash_cost_krw": float(sizing["total_cost"]),
                "buy_notional_krw": float(sizing["notional"]), "entry_date": day,
                "cutoff_mark": None,
            }
            events.append({"date": day.strftime("%Y-%m-%d"), "strategy_id": strategy_id, "event_type": "ENTRY", "event_status": "FILLED", "ticker": row["ticker"], "ISU_CD": row["ISU_CD"], "signal_date": row["signal_date"], "entry_signal_date": row["signal_date"], "entry_execution_date": row["entry_execution_date"], "reference_open": ref, "fill_price": sizing["fill_price"], "shares": shares, "cash_before": cash_before, "cash_after": cash, "notional_krw": sizing["notional"], "commission_krw": sizing["fee"], "tax_krw": 0.0, "candidate_order_key": list(_order_key(row))})

        if day == CUTOFF:
            cutoff_snapshot = {"cash": cash, "open_positions": len(positions), "terminal_positions": sum(str(item["row"].get("trade_status")) == "OPEN_AT_CUTOFF" for item in positions.values())}
            for position in positions.values():
                position["cutoff_mark"] = _exact_price(daily_by_ticker, position["row"]["ticker"], CUTOFF, "close")
        invested = 0.0
        for identity, position in positions.items():
            if day > CUTOFF:
                mark = position.get("cutoff_mark")
                if mark is None:
                    raise RuntimeError(f"SUPPORT_DAY_WITHOUT_CUTOFF_MARK:{identity}")
            else:
                mark = _exact_price(daily_by_ticker, identity[0], day, "close")
            invested += float(mark) * int(position["shares"])
            if day == CUTOFF:
                row = position["row"]
                if str(row.get("trade_status")) == "OPEN_AT_CUTOFF":
                    buy_cost = float(position["buy_cash_cost_krw"])
                    row["terminal_market_value_krw"] = float(mark) * int(position["shares"])
                    row["terminal_unrealized_pnl_krw"] = row["terminal_market_value_krw"] - buy_cost
                    row["exit_status"] = "OPEN_AT_CUTOFF"
                else:
                    row["portfolio_open_at_cutoff_pending_support"] = True
        equity = cash + invested
        if equity < -1e-7:
            negative_cash_count += 1
            raise RuntimeError("NEGATIVE_EQUITY")
        if abs(equity - cash - invested) > 1e-6:
            cash_conservation_error_count += 1
        max_deployed = max(max_deployed, invested)
        event_rows = events[event_start:]
        curve_rows.append({
            "date": day.strftime("%Y-%m-%d"), "strategy_id": strategy_id,
            "cash": cash, "invested_market_value": invested, "total_equity": equity,
            "open_positions": len(positions), "cash_ratio": cash / equity if equity else 0.0,
            "invested_ratio": invested / equity if equity else 0.0,
            "valuation_basis_date": CUTOFF.strftime("%Y-%m-%d") if day > CUTOFF else day.strftime("%Y-%m-%d"),
            "execution_support_only": day > CUTOFF,
        })
        # Exit orders run before entry orders; entry sequence must match the W tuple.
        exit_orders = [row for row in event_rows if row["event_type"] == "EXIT"]
        entry_orders = [row for row in event_rows if row["event_type"] == "ENTRY"]
        if any(exit_orders[i]["candidate_order_key"] > exit_orders[i + 1]["candidate_order_key"] for i in range(len(exit_orders) - 1)):
            raise RuntimeError("EXIT_ORDER_NOT_DETERMINISTIC")
        if any(entry_orders[i]["candidate_order_key"] > entry_orders[i + 1]["candidate_order_key"] for i in range(len(entry_orders) - 1)):
            raise RuntimeError("ENTRY_ORDER_NOT_DETERMINISTIC")
        event_types = [row["event_type"] for row in event_rows]
        first_entry_position = next((i for i, event_type in enumerate(event_types) if event_type == "ENTRY"), len(event_types))
        if "EXIT" in event_types[first_entry_position:]:
            raise RuntimeError("SAME_DAY_SELL_BEFORE_BUY_ORDER_MISMATCH")

    if cutoff_snapshot is None:
        raise RuntimeError("CUTOFF_SNAPSHOT_MISSING")
    curve = pd.DataFrame(curve_rows)
    portfolio_ledger = pd.DataFrame(sorted(candidate_by_key.values(), key=lambda row: (_clean_date(row.get("entry_execution_date")) or "", _order_key(row))))
    event_frame = pd.DataFrame(events)
    closed = portfolio_ledger.loc[(portfolio_ledger["entry_status"] == "FILLED") & (portfolio_ledger["exit_status"] == "FILLED")].copy()
    terminal = portfolio_ledger.loc[(portfolio_ledger["entry_status"] == "FILLED") & (portfolio_ledger["exit_status"] == "OPEN_AT_CUTOFF")].copy()
    final_equity = float(curve.iloc[-1]["total_equity"])
    cutoff_curve = curve.loc[curve["date"] <= CUTOFF.strftime("%Y-%m-%d")].copy()
    final_cutoff_equity = float(cutoff_curve.iloc[-1]["total_equity"])
    elapsed_days = max(1, int((pd.Timestamp(curve.iloc[-1]["date"]) - pd.Timestamp(curve.iloc[0]["date"])).days))
    cagr = (final_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0 if final_equity > 0 else None
    mdd = _mdd(curve)
    returns = pd.to_numeric(closed.get("realized_net_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    holding = []
    for row in closed.to_dict(orient="records"):
        entry, exit_date = pd.Timestamp(row["entry_execution_date"]), pd.Timestamp(row["exit_execution_date"])
        holding.append(sum(entry <= date <= exit_date for date in dates))
    terminal_market_value = float(pd.to_numeric(terminal.get("terminal_market_value_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    terminal_pnl = float(pd.to_numeric(terminal.get("terminal_unrealized_pnl_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    realized_pnl = float(pd.to_numeric(closed.get("realized_pnl_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    summary = {
        "strategy_id": strategy_id,
        "initial_capital_krw": INITIAL_CAPITAL,
        "final_equity_krw": final_equity,
        "final_equity_at_cutoff_krw": final_cutoff_equity,
        "final_cash_krw": float(curve.iloc[-1]["cash"]),
        "cash_at_cutoff_krw": float(cutoff_snapshot["cash"]),
        "terminal_market_value_krw": terminal_market_value,
        "terminal_unrealized_pnl_krw": terminal_pnl,
        "realized_pnl_krw": realized_pnl,
        "total_return_pct": (final_equity / INITIAL_CAPITAL - 1.0) * 100.0,
        "CAGR_pct": cagr * 100.0 if cagr is not None else None,
        **mdd,
        "period_start": GLOBAL_START.strftime("%Y-%m-%d"),
        "cutoff_date": CUTOFF.strftime("%Y-%m-%d"),
        "execution_support_date": EXECUTION_SUPPORT.strftime("%Y-%m-%d"),
        "candidate_entry_signals": int(len(portfolio_ledger)),
        "filled_entries": int((portfolio_ledger["entry_status"] == "FILLED").sum()),
        "CASH_SKIP": int((portfolio_ledger["entry_status"] == "CASH_SKIP").sum()),
        "open_position_skip": int((portfolio_ledger["entry_status"] == "OPEN_POSITION_SKIP").sum()),
        "total_exits": int((portfolio_ledger["exit_status"] == "FILLED").sum()),
        "terminal_positions": int(len(terminal)),
        "fill_rate_pct": float((portfolio_ledger["entry_status"] == "FILLED").sum() / len(portfolio_ledger) * 100.0) if len(portfolio_ledger) else None,
        "realized_trade_count": int(len(closed)),
        "realized_positive_rate_pct": float((returns > 0).mean() * 100.0) if len(returns) else None,
        "realized_mean_return_pct": float(returns.mean()) if len(returns) else None,
        "realized_median_return_pct": float(returns.median()) if len(returns) else None,
        "median_holding_sessions": float(np.median(holding)) if holding else None,
        "realized_ge_20_pct_count": int((returns >= 20).sum()), "realized_ge_50_pct_count": int((returns >= 50).sum()), "realized_ge_100_pct_count": int((returns >= 100).sum()),
        "realized_le_minus_15_pct_count": int((returns <= -15).sum()), "realized_le_minus_30_pct_count": int((returns <= -30).sum()), "realized_le_minus_40_pct_count": int((returns <= -40).sum()), "realized_le_minus_50_pct_count": int((returns <= -50).sum()),
        "average_cash_krw": float(cutoff_curve["cash"].mean()), "average_cash_ratio_pct": float(cutoff_curve["cash_ratio"].mean() * 100.0),
        "average_invested_capital_krw": float(cutoff_curve["invested_market_value"].mean()), "average_invested_ratio_pct": float(cutoff_curve["invested_ratio"].mean() * 100.0),
        "average_concurrent_positions": float(cutoff_curve["open_positions"].mean()), "median_concurrent_positions": float(cutoff_curve["open_positions"].median()), "max_concurrent_positions": int(cutoff_curve["open_positions"].max()),
        "max_capital_deployed_krw": max_deployed,
        "buy_notional_krw": float(pd.to_numeric(portfolio_ledger["buy_notional_krw"], errors="coerce").fillna(0).sum()),
        "sell_notional_krw": float(pd.to_numeric(portfolio_ledger["sell_notional_krw"], errors="coerce").fillna(0).sum()),
        "buy_commission_krw": float(pd.to_numeric(portfolio_ledger["buy_commission_krw"], errors="coerce").fillna(0).sum()),
        "sell_commission_krw": float(pd.to_numeric(portfolio_ledger["sell_commission_krw"], errors="coerce").fillna(0).sum()),
        "sell_tax_krw": float(pd.to_numeric(portfolio_ledger["sell_tax_krw"], errors="coerce").fillna(0).sum()),
        "turnover_multiple_initial_capital": float((pd.to_numeric(portfolio_ledger["buy_notional_krw"], errors="coerce").fillna(0).sum() + pd.to_numeric(portfolio_ledger["sell_notional_krw"], errors="coerce").fillna(0).sum()) / INITIAL_CAPITAL),
        "negative_cash_count": negative_cash_count,
        "leverage_usage_krw": leverage_usage,
        "position_notional_over_5m_count": oversized_position_count,
        "cash_conservation_error_count": cash_conservation_error_count,
        "same_day_ordering_mismatch_count": 0,
        "post_cutoff_new_entry_count": sum(
            1 for value in portfolio_ledger["entry_execution_date"]
            if (_clean_date(value) or "") > CUTOFF.strftime("%Y-%m-%d")
        ),
        "run_status": "COMPLETED",
        "cutoff_open_positions_including_support_exits": int(cutoff_snapshot["open_positions"]),
        "cutoff_terminal_positions": int(cutoff_snapshot["terminal_positions"]),
        "execution_contract": {
            "per_position_notional_cap_krw": POSITION_CAP,
            "integer_shares": True, "partial_buys": False, "cash_shortage": "CASH_SKIP_NO_CARRY",
            "same_day_order": list(ORDER_FIELDS), "exits_before_entries": True,
            "same_session_sale_proceeds_reusable": True, "concurrent_holding_cap": None,
            "buy_fee_rate": BUY_FEE_RATE, "sell_fee_rate": SELL_FEE_RATE,
            "buy_slippage_rate": BUY_SLIPPAGE_RATE, "sell_slippage_rate": SELL_SLIPPAGE_RATE,
            "ETF_sell_tax_rate": ETF_SELL_TAX_RATE,
            "terminal_mark": "exact 2026-08-31 raw close; no hypothetical exit costs",
        },
    }
    return {"ledger": portfolio_ledger, "events": event_frame, "curve": curve, "summary": summary}


def _annual_returns(curve: pd.DataFrame) -> list[dict[str, Any]]:
    frame = curve.copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    previous_equity = INITIAL_CAPITAL
    rows: list[dict[str, Any]] = []
    for year in range(GLOBAL_START.year, EXECUTION_SUPPORT.year + 1):
        group = frame.loc[frame["year"].eq(year)]
        if group.empty:
            continue
        ending = float(group.iloc[-1]["total_equity"])
        rows.append({"year": year, "year_label": f"{year}_YTD" if year == EXECUTION_SUPPORT.year else str(year), "starting_equity_krw": previous_equity, "ending_equity_krw": ending, "return_pct": (ending / previous_equity - 1.0) * 100.0 if previous_equity else None, "execution_support_included": year == EXECUTION_SUPPORT.year})
        previous_equity = ending
    return rows


def _category_contribution(strategy_id: str, ledger: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        group = ledger.loc[ledger["category"].eq(category)]
        filled = group.loc[group["entry_status"].eq("FILLED")]
        realized = filled.loc[filled["exit_status"].eq("FILLED")]
        returns = pd.to_numeric(realized["realized_net_return_pct"], errors="coerce").dropna()
        rows.append({
            "strategy_id": strategy_id, "category": category,
            "candidate_entries": int(len(group)), "filled_trades": int(len(filled)),
            "realized_trades": int(len(realized)),
            "realized_positive_rate_pct": float((returns > 0).mean() * 100.0) if len(returns) else None,
            "median_realized_return_pct": float(returns.median()) if len(returns) else None,
            "capital_deployed_krw": float(pd.to_numeric(filled["buy_notional_krw"], errors="coerce").fillna(0).sum()),
            "realized_pnl_contribution_krw": float(pd.to_numeric(realized["realized_pnl_krw"], errors="coerce").fillna(0).sum()),
            "terminal_position_count": int(filled["exit_status"].eq("OPEN_AT_CUTOFF").sum()),
            "terminal_market_value_krw": float(pd.to_numeric(filled["terminal_market_value_krw"], errors="coerce").fillna(0).sum()),
        })
    return rows


def _post_cutoff_candidate_entry_count(trades: Sequence[Mapping[str, Any]]) -> int:
    cutoff = CUTOFF.strftime("%Y-%m-%d")
    return sum(
        1 for trade in trades
        if (_clean_date(trade.get("entry_execution_date")) or "") > cutoff
    )


def _validation_and_parity(
    results: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]],
    universe: Sequence[Mapping[str, str]], plan: Mapping[str, Mapping[str, Any]],
    portfolio: Mapping[str, Mapping[str, Any]], sample: Mapping[str, Any], raw_audit: Mapping[str, Any],
    price_coverage: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    price_coverage = dict(price_coverage or {
        "checked": False,
        "candidate_trade_ticker_count": 0,
        "portfolio_price_requested_ticker_count": 0,
        "zero_candidate_etf_count": len(universe),
        "price_requested_for_zero_candidate_etf_count": 0,
        "candidate_required_price_coverage_missing_count": 0,
        "candidate_required_price_coverage_missing": [],
        "candidate_required_raw_session_gap_count": 0,
    })
    result_tickers = [str(row.get("ticker")) for row in results]
    process_errors = [row for row in results if row.get("status") == "ERROR" or row.get("errors")]
    all_new = [trade for result in results for strategy in STRATEGIES for trade in result.get("trades", {}).get(strategy, [])]
    new_group_a_mismatches: list[dict[str, Any]] = []
    group_b_divergences: list[dict[str, Any]] = []
    group_b_classification_counts = Counter()
    group_a_count = sum(1 for ticker in plan if plan[ticker]["group"] == "A")
    group_b_count = sum(1 for ticker in plan if plan[ticker]["group"] == "B")
    unexpected_later_start_tickers = sorted(ticker for ticker, item in plan.items() if item["group"] in {"UNEXPECTED_LATER_START", "UNEXPECTED_NOT_READY"})
    expected_comparable = {
        ticker for ticker, item in plan.items() if item["group"] in {"A", "B"}
    }
    result_by_ticker = {str(row.get("ticker")): row for row in results}
    expected_not_evaluable = sorted(
        ticker for ticker in expected_comparable
        if result_by_ticker.get(ticker, {}).get("status") != "EVALUABLE"
    )
    for result in results:
        ticker = str(result.get("ticker", ""))
        group = plan.get(ticker, {}).get("group", "UNCLASSIFIED")
        if group not in {"A", "B"} or result.get("status") != "EVALUABLE":
            continue
        for strategy in STRATEGIES:
            old_rows = _trade_group(baseline, ticker, strategy)
            new_rows = result.get("trades", {}).get(strategy, [])
            comparison = _path_comparison(old_rows, new_rows, exact=(group == "A"))
            if group == "A" and not comparison["pass"]:
                new_group_a_mismatches.append({"ticker": ticker, "strategy_id": strategy, "comparison": comparison})
            elif group == "B":
                classification = _classify_group_b_divergence(
                    old_rows, new_rows, plan[ticker]["common_start"], plan[ticker]["v06_common_start"],
                )
                reason = classification["divergence_class"]
                group_b_classification_counts[reason] += 1
                if reason != "NO_DIVERGENCE":
                    group_b_divergences.append({"ticker": ticker, "strategy_id": strategy, **classification, "divergence_reason": reason})
    group_b_unexplained = group_b_classification_counts["POST_V06_UNEXPLAINED_DIVERGENCE"]
    start_deltas = [
        (pd.Timestamp(plan[ticker]["v06_common_start"]) - pd.Timestamp(plan[ticker]["common_start"])).days
        for ticker in plan if plan[ticker]["group"] == "B" and plan[ticker]["common_start"] and plan[ticker]["v06_common_start"]
    ]
    all_candidate_tickers = {str(trade.get("ticker", "")).zfill(6) for trade in all_new}
    unauthorized = sorted(all_candidate_tickers - {row["ticker"] for row in universe})
    unauthorized_exclusions = sorted(
        all_candidate_tickers.intersection(PERMANENT_EXCLUSIONS)
    )
    mismatch_start_count = sum(
        1 for result in results
        if str(result.get("ticker")) in expected_comparable
        and result.get("status") == "EVALUABLE"
        and result.get("common_evaluable_start") != plan.get(str(result.get("ticker")), {}).get("common_start")
    )
    eligibility_mismatch = sum(sum("ELIGIBILITY_MISMATCH" in str(error) for error in result.get("errors", [])) for result in results)
    timing_mismatch = sum(
        1 for result in results for error in result.get("errors", [])
        if str(error).startswith("EXECUTION_TIMING_MISMATCH")
    )
    execution_price_mismatch = sum(
        1 for result in results for error in result.get("errors", [])
        if str(error).startswith(("EXECUTION_PRICE_MISMATCH", "TERMINAL_CUTOFF_PRICE_MISMATCH"))
    )
    terminal_contract_mismatch = sum(
        1 for result in results for error in result.get("errors", [])
        if str(error).startswith(("OPEN_TERMINAL_HAS_EXIT_EXECUTION", "TERMINAL_CUTOFF_DATE_MISMATCH"))
    )
    technical_no_trade_rows = sum(
        int(result.get("no_trade_rows_in_technical_input", 0)) for result in results
    )
    post_cutoff_candidate_entries = _post_cutoff_candidate_entry_count(all_new)
    group_a_parity_mismatch_count = len(new_group_a_mismatches)
    portfolio_summaries = [portfolio[strategy]["summary"] for strategy in STRATEGIES]
    negative_cash = sum(item["negative_cash_count"] for item in portfolio_summaries)
    leverage = sum(float(item["leverage_usage_krw"]) for item in portfolio_summaries)
    over_cap = sum(item["position_notional_over_5m_count"] for item in portfolio_summaries)
    ordering_mismatch = sum(item["same_day_ordering_mismatch_count"] for item in portfolio_summaries)
    post_cutoff_entries = max(
        post_cutoff_candidate_entries,
        sum(item["post_cutoff_new_entry_count"] for item in portfolio_summaries),
    )
    canonical_ids = []
    for row in all_new:
        details = row.get("source_signal_details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
        if isinstance(details, Mapping) and details.get("canonical_trade_id") is not None:
            canonical_ids.append((str(row.get("strategy_id")), str(row.get("ticker", "")).zfill(6), str(details["canonical_trade_id"])))
    duplicate_trade_ids = len(canonical_ids) - len(set(canonical_ids))
    passed = bool(
        len(result_tickers) == len(set(result_tickers)) == len(universe)
        and set(result_tickers) == {row["ticker"] for row in universe}
        and not process_errors and not unauthorized and mismatch_start_count == 0
        and not expected_not_evaluable and not unauthorized_exclusions and not unexpected_later_start_tickers
        and eligibility_mismatch == 0 and timing_mismatch == 0
        and execution_price_mismatch == 0 and terminal_contract_mismatch == 0
        and post_cutoff_candidate_entries == 0 and duplicate_trade_ids == 0
        and raw_audit.get("other_invalid_ohlc_rows") == 0
        and raw_audit.get("technical_input_no_trade_row_count") == 0
        and technical_no_trade_rows == 0
        and sum(1 for trade in all_new if trade.get("category") not in CATEGORY_ORDER) == 0
        and group_a_parity_mismatch_count == 0 and group_b_unexplained == 0
        and negative_cash == 0 and leverage <= 1e-7 and over_cap == 0
        and ordering_mismatch == 0 and post_cutoff_entries == 0
        and all(item["cash_conservation_error_count"] == 0 for item in portfolio_summaries)
        and all(item.get("run_status") == "COMPLETED" for item in portfolio_summaries)
        and price_coverage.get("checked") is True
        and int(price_coverage.get("price_requested_for_zero_candidate_etf_count", -1)) == 0
        and int(price_coverage.get("candidate_required_price_coverage_missing_count", -1)) == 0
        and sample.get("validation_passed") is True
    )
    verdict = "ETF_V06_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_BATTLE_V03_COMPLETE" if passed else "CHECK_REQUIRED"
    validation = {
        "verdict": verdict, "passed": passed,
        "worker_count": WORKERS, "full_portfolio_run_attempt_count": 1,
        "portfolio_run_attempt_count": int(any(item.get("run_status") == "COMPLETED" for item in portfolio_summaries)),
        "portfolio_price_coverage_checked": bool(price_coverage.get("checked")),
        "portfolio_price_requested_ticker_count": int(price_coverage.get("portfolio_price_requested_ticker_count", 0)),
        "candidate_trade_ticker_count": int(price_coverage.get("candidate_trade_ticker_count", 0)),
        "zero_candidate_etf_count": int(price_coverage.get("zero_candidate_etf_count", 0)),
        "price_requested_for_zero_candidate_etf_count": int(price_coverage.get("price_requested_for_zero_candidate_etf_count", 0)),
        "candidate_required_price_coverage_missing_count": int(price_coverage.get("candidate_required_price_coverage_missing_count", 0)),
        "candidate_required_price_coverage_missing": list(price_coverage.get("candidate_required_price_coverage_missing", [])),
        "candidate_required_raw_session_gap_count": int(price_coverage.get("candidate_required_raw_session_gap_count", 0)),
        "sample_verdict": sample.get("verdict"), "sample_ticker_count": sample.get("sample_count"),
        "universe_expected_count": len(universe), "universe_result_count": len(result_tickers),
        "duplicate_result_ticker_count": len(result_tickers) - len(set(result_tickers)),
        "missing_result_tickers": sorted({row["ticker"] for row in universe} - set(result_tickers)),
        "unauthorized_etf_count": len(unauthorized), "unauthorized_etf_tickers": unauthorized,
        "unauthorized_exclusion_count": len(unauthorized_exclusions),
        "unauthorized_exclusion_tickers": unauthorized_exclusions,
        "unknown_category_count": sum(1 for trade in all_new if trade.get("category") not in CATEGORY_ORDER),
        "candidate_trade_count": len(all_new), "duplicate_canonical_trade_id_count": duplicate_trade_ids,
        "common_start_formula_mismatch_count": mismatch_start_count,
        "expected_comparable_not_evaluable_count": len(expected_not_evaluable),
        "expected_comparable_not_evaluable_tickers": expected_not_evaluable,
        "common_eligibility_mismatch_count": eligibility_mismatch,
        "execution_timing_mismatch_count": timing_mismatch,
        "execution_price_mismatch_count": execution_price_mismatch,
        "terminal_contract_mismatch_count": terminal_contract_mismatch,
        "post_cutoff_new_entry_count": post_cutoff_entries,
        "future_fallback_count": 0, "nearest_date_fallback_count": 0,
        "no_trade_session_contract_mismatch_count": max(int(raw_audit.get("technical_input_no_trade_row_count", 0)), technical_no_trade_rows),
        "raw_invalid_ohlc_count": int(raw_audit.get("other_invalid_ohlc_rows", -1)),
        "raw_session_gap_count": sum(int(row.get("missing_session_count", 0)) for row in results),
        "group_a_ticker_count": group_a_count,
        "group_a_v06_parity_mismatch_count": group_a_parity_mismatch_count,
        "group_b_ticker_count": group_b_count,
        "unexpected_later_or_missing_start_count": len(unexpected_later_start_tickers),
        "unexpected_later_or_missing_start_tickers": unexpected_later_start_tickers,
        "no_v06_start_ticker_count": sum(1 for item in plan.values() if item["group"] == "NO_V06_START"),
        "unclassified_non_evaluable_ticker_count": sum(1 for item in plan.values() if item["group"] == "UNCLASSIFIED"),
        "group_b_pre_v06_window_only_divergence_count": group_b_classification_counts["PRE_V06_WINDOW_ONLY"],
        "group_b_lifecycle_carryover_divergence_count": group_b_classification_counts["LIFECYCLE_CARRYOVER"],
        "group_b_post_v06_unexplained_divergence_count": group_b_unexplained,
        "group_b_changed_trade_path_ticker_count": len({row["ticker"] for row in group_b_divergences}),
        "group_b_divergent_strategy_path_count": len(group_b_divergences),
        "group_b_unexplained_divergence_count": group_b_unexplained,
        "group_b_earliest_start_delta_days": min(start_deltas) if start_deltas else None,
        "group_b_max_start_delta_days": max(start_deltas) if start_deltas else None,
        "negative_cash_count": negative_cash, "leverage_usage_krw": leverage,
        "position_notional_over_5m_count": over_cap,
        "same_day_ordering_mismatch_count": ordering_mismatch,
        "process_error_count": len(process_errors),
        "process_errors": [{"ticker": row.get("ticker"), "status": row.get("status"), "errors": row.get("errors"), "reason": row.get("reason")} for row in process_errors[:50]],
        "cash_conservation_error_count": sum(item["cash_conservation_error_count"] for item in portfolio_summaries),
        "raw_data_audit": dict(raw_audit),
        "portfolio_price_coverage": price_coverage,
    }
    parity = {
        "group_a_definition": "new_common_start == V06 common_evaluable_start; exact path parity required",
        "group_b_definition": "new_common_start < V06 common_evaluable_start; path divergence allowed when caused by earlier-position lifecycle effect",
        "group_a_ticker_count": group_a_count,
        "group_a_parity_mismatch_count": group_a_parity_mismatch_count,
        "group_a_mismatches": new_group_a_mismatches,
        "group_b_ticker_count": group_b_count,
        "group_b_earliest_start_delta_days": min(start_deltas) if start_deltas else None,
        "group_b_max_start_delta_days": max(start_deltas) if start_deltas else None,
        "group_b_changed_trade_path_ticker_count": len({row["ticker"] for row in group_b_divergences}),
        "group_b_changed_ticker_details": group_b_divergences,
        "group_b_classification_counts": {
            "NO_DIVERGENCE": group_b_classification_counts["NO_DIVERGENCE"],
            "PRE_V06_WINDOW_ONLY": group_b_classification_counts["PRE_V06_WINDOW_ONLY"],
            "LIFECYCLE_CARRYOVER": group_b_classification_counts["LIFECYCLE_CARRYOVER"],
            "POST_V06_UNEXPLAINED_DIVERGENCE": group_b_classification_counts["POST_V06_UNEXPLAINED_DIVERGENCE"],
        },
        "group_b_unexplained_divergence_count": group_b_unexplained,
    }
    return validation, parity


def _write_outputs(
    result_rows: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]],
    portfolio: Mapping[str, Mapping[str, Any]], sample: Mapping[str, Any],
    validation: Mapping[str, Any], parity: Mapping[str, Any], metadata: Mapping[str, Any],
    plan: Mapping[str, Mapping[str, Any]], raw_audit: Mapping[str, Any], runtime: Mapping[str, Any],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_path = OUTPUT_DIR / "candidate_trade_ledger.csv"
    if not candidate_path.is_file():
        candidate_frame = _candidate_ledger_frame(result_rows, plan)
        candidate_frame.to_csv(candidate_path, index=False, lineterminator="\n")

    portfolio_frames = []
    event_frames = []
    curve_frames = []
    metrics_rows = []
    execution_rows = []
    category_rows = []
    annual_rows = []
    for strategy in STRATEGIES:
        item = portfolio[strategy]
        ledger = item["ledger"].copy()
        ledger["source_signal_details"] = ledger["source_signal_details"].map(lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, Mapping) else value)
        portfolio_frames.append(ledger)
        events = item["events"].copy()
        if not events.empty:
            event_frames.append(events)
        curve = item["curve"].copy()
        curve_frames.append(curve)
        metrics_rows.append(item["summary"])
        execution_rows.append({
            "strategy_id": strategy,
            "run_status": item["summary"].get("run_status", "COMPLETED"),
            "candidate_entries": item["summary"]["candidate_entry_signals"],
            "filled_entries": item["summary"]["filled_entries"],
            "CASH_SKIP": item["summary"]["CASH_SKIP"],
            "open_position_skip": item["summary"]["open_position_skip"],
            "total_exits": item["summary"]["total_exits"],
            "terminal_positions": item["summary"]["terminal_positions"],
            "fill_rate_pct": item["summary"]["fill_rate_pct"],
            "cutoff_open_positions_including_support_exits": item["summary"]["cutoff_open_positions_including_support_exits"],
            "cutoff_terminal_positions": item["summary"]["cutoff_terminal_positions"],
        })
        category_rows.extend(_category_contribution(strategy, item["ledger"]))
        annual_rows.extend({"strategy_id": strategy, **row} for row in _annual_returns(curve))
    portfolio_frame = pd.concat(portfolio_frames, ignore_index=True) if portfolio_frames else pd.DataFrame()
    portfolio_frame.to_csv(OUTPUT_DIR / "portfolio_trade_ledger.csv", index=False, lineterminator="\n")
    pd.concat(curve_frames, ignore_index=True).to_csv(OUTPUT_DIR / "equity_curve.csv", index=False, lineterminator="\n")
    pd.DataFrame(metrics_rows).to_csv(OUTPUT_DIR / "portfolio_metrics.csv", index=False, lineterminator="\n")
    pd.DataFrame(execution_rows).to_csv(OUTPUT_DIR / "execution_summary.csv", index=False, lineterminator="\n")
    pd.DataFrame(annual_rows).to_csv(OUTPUT_DIR / "annual_returns.csv", index=False, lineterminator="\n")
    pd.DataFrame(category_rows).to_csv(OUTPUT_DIR / "category_contribution.csv", index=False, lineterminator="\n")
    _write_json(OUTPUT_DIR / "parity_report.json", parity)
    _write_json(OUTPUT_DIR / "validation.json", validation)
    _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
    _write_json(OUTPUT_DIR / "source_authorities.json", {**dict(metadata), "raw_data_audit": dict(raw_audit), "runtime": dict(runtime), "verdict": validation["verdict"]})
    summary = _render_summary(validation, parity, metrics_rows, execution_rows, category_rows, annual_rows, sample, runtime)
    (OUTPUT_DIR / "summary.md").write_text(summary, encoding="utf-8")


def _candidate_ledger_frame(
    result_rows: Sequence[Mapping[str, Any]], plan: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    candidate_rows: list[dict[str, Any]] = []
    categories = {str(row["ticker"]): str(row["category"]) for row in result_rows}
    for result in result_rows:
        ticker = str(result["ticker"])
        group = plan[ticker]["group"]
        for strategy in STRATEGIES:
            for trade in result.get("trades", {}).get(strategy, []):
                details = trade.get("source_signal_details", {})
                candidate_rows.append({
                    **{key: value for key, value in trade.items() if key != "source_signal_details"},
                    "category": categories[ticker], "common_start_group": group,
                    "v06_common_evaluable_start": plan[ticker]["v06_common_start"],
                    "source_signal_details": json.dumps(details, ensure_ascii=False, sort_keys=True),
                    "canonical_trade_id": details.get("canonical_trade_id") if isinstance(details, Mapping) else None,
                })
    frame = pd.DataFrame(candidate_rows)
    if not frame.empty:
        frame.sort_values(["strategy_id", "signal_date", "ticker", "ISU_CD", "entry_execution_date"], kind="mergesort", inplace=True)
    else:
        frame = pd.DataFrame(columns=[
            "strategy_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date",
            "trade_status", "category", "common_start_group", "v06_common_evaluable_start",
            "source_signal_details", "canonical_trade_id",
        ])
    return frame


def _save_candidate_lifecycle(
    results: Sequence[Mapping[str, Any]],
    universe: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Mapping[str, Any]],
    sample: Mapping[str, Any],
    lifecycle_seconds: float,
) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger = _candidate_ledger_frame(results, plan)
    ledger_path = OUTPUT_DIR / "candidate_trade_ledger.csv"
    ledger.to_csv(ledger_path, index=False, lineterminator="\n")
    candidate_tickers = _portfolio_price_universe(ledger.to_dict(orient="records"))
    status_counts = Counter(str(row.get("status")) for row in results)
    strategy_trade_counts = {
        strategy: int(ledger["strategy_id"].eq(strategy).sum()) if not ledger.empty else 0
        for strategy in STRATEGIES
    }
    worker_errors = [
        {"ticker": row.get("ticker"), "status": row.get("status"), "errors": row.get("errors", [])}
        for row in results if row.get("status") == "ERROR" or row.get("errors")
    ]
    summary = {
        "verdict": "CANDIDATE_LIFECYCLE_SAVED",
        "sealed": True,
        "sealed_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "candidate_trade_ledger_sha256": _sha256(ledger_path),
        "authority_universe_ticker_count": len(universe),
        "lifecycle_result_count": len(results),
        "lifecycle_status_counts": dict(sorted(status_counts.items())),
        "candidate_worker_error_count": len(worker_errors),
        "candidate_worker_errors": worker_errors[:50],
        "candidate_trade_count": int(len(ledger)),
        "candidate_trade_count_by_strategy": strategy_trade_counts,
        "candidate_ticker_count": len(candidate_tickers),
        "candidate_tickers": candidate_tickers,
        "candidate_status_counts": dict(sorted(Counter(ledger.get("trade_status", pd.Series(dtype=str)).astype(str)).items())),
        "group_a_ticker_count": sum(item["group"] == "A" for item in plan.values()),
        "group_b_ticker_count": sum(item["group"] == "B" for item in plan.values()),
        "sample_verdict": sample.get("verdict"),
        "worker_count": WORKERS,
        "lifecycle_wall_seconds": round(lifecycle_seconds, 3),
    }
    _write_json(OUTPUT_DIR / "candidate_summary.json", summary)
    marker = json.loads(FULL_ATTEMPT_MARKER.read_text(encoding="utf-8"))
    marker.update({
        "candidate_ledger_sealed": True,
        "candidate_ledger_sealed_at": summary["sealed_at"],
        "candidate_trade_ledger_sha256": summary["candidate_trade_ledger_sha256"],
        "candidate_trade_count": summary["candidate_trade_count"],
        "candidate_ticker_count": summary["candidate_ticker_count"],
    })
    _write_json(FULL_ATTEMPT_MARKER, marker)
    return summary


def _render_summary(validation: Mapping[str, Any], parity: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]], execution: Sequence[Mapping[str, Any]], categories: Sequence[Mapping[str, Any]], annual: Sequence[Mapping[str, Any]], sample: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    by_strategy = {str(row["strategy_id"]): row for row in metrics}
    ex_by_strategy = {str(row["strategy_id"]): row for row in execution}
    lines = [
        "# ETF V06 A FAST vs Julia 실전 포트폴리오 배틀 V03", "",
        f"- Verdict: {validation['verdict']}",
        f"- 기간: {GLOBAL_START.date()} ~ {CUTOFF.date()} (체결 지원 {EXECUTION_SUPPORT.date()})",
        "- Universe: V06 CURRENT SURVIVING PLAIN LONG, 지정 영구 제외 2종목 유지",
        "- 데이터: KRX raw OHLCV; RAW_PRICE_LIMITATION=TRUE; SURVIVORSHIP_BIAS=TRUE",
        "- Select Core: readiness, common start, candidate ledger, portfolio 실행에 사용하지 않음",
        f"- 공통 시작: Group A {parity['group_a_ticker_count']} ETF; Group B {parity['group_b_ticker_count']} ETF",
        f"- Sample: {sample.get('verdict')} ({sample.get('sample_count')} ETF); Full worker: {WORKERS}; full-run attempt: {validation.get('full_portfolio_run_attempt_count')}",
        "- 포트폴리오: 초기자본 200,000,000원, 매수 notional 5,000,000원 상한, 정수 수량, 무레버리지, cash shortage는 CASH_SKIP, 동시보유 상한 없음.",
        "- 비용: 매수·매도 수수료 각 0.015%; 매수 슬리피지 +0.1%, 매도 -0.1%; 매도세 0%.",
        "- 체결 순서: 해당 날짜 매도를 먼저 처리하고 매도 대금은 같은 세션의 다음 정렬 매수에 재사용. 신규 진입은 신호 다음 첫 exact KRX 세션 시가.",
        "- Equity curve는 2014-01-02부터 2026-09-01까지 저장해. 2026-09-01은 cutoff 이전 exit 신호의 체결 지원일이며 신규 진입은 없어. TERMINAL 평가는 2026-08-31 raw close야.", "",
        "## Portfolio 비교", "",
        "| 전략 | Final equity | Return | CAGR | MDD | Avg cash ratio | Avg invested ratio | Avg positions | Max positions | CASH_SKIP | Fill rate | Median holding | Terminal # / value |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def num(value: Any, suffix: str = "") -> str:
        if value is None or pd.isna(value): return "n/a"
        return f"{float(value):,.2f}{suffix}"
    for strategy in STRATEGIES:
        row, ex = by_strategy[strategy], ex_by_strategy[strategy]
        lines.append(
            f"| {strategy} | {num(row['final_equity_krw'])} | {num(row['total_return_pct'],'%')} | {num(row['CAGR_pct'],'%')} | {num(row['mdd_pct'],'%')} | {num(row['average_cash_ratio_pct'],'%')} | {num(row['average_invested_ratio_pct'],'%')} | {num(row['average_concurrent_positions'])} | {num(row['max_concurrent_positions'])} | {ex['CASH_SKIP']} | {num(ex['fill_rate_pct'],'%')} | {num(row['median_holding_sessions'])} | {ex['terminal_positions']} / {num(row['terminal_market_value_krw'])} |"
        )
    classes = parity.get("group_b_classification_counts", {})
    lines += ["", "## Parity", "", f"- Group A exact V06 parity mismatch: {parity['group_a_parity_mismatch_count']}", f"- Group B: {parity['group_b_ticker_count']} ETF; 시작일 앞당김 {parity['group_b_earliest_start_delta_days']}~{parity['group_b_max_start_delta_days']}일; trade path 변경 ETF {parity['group_b_changed_trade_path_ticker_count']}개.", f"- Group B divergence: PRE_V06_WINDOW_ONLY {classes.get('PRE_V06_WINDOW_ONLY', 0)}건; LIFECYCLE_CARRYOVER {classes.get('LIFECYCLE_CARRYOVER', 0)}건; POST_V06_UNEXPLAINED_DIVERGENCE {classes.get('POST_V06_UNEXPLAINED_DIVERGENCE', 0)}건.", "- ETF·전략별 근거는 parity_report.json에 기록했어.", "", "## Category realized contribution", "", "| 전략 | Category | Filled | Positive rate | Median net return | Capital deployed | Realized P/L |", "|---|---|---:|---:|---:|---:|---:|"]
    for row in categories:
        lines.append(f"| {row['strategy_id']} | {row['category']} | {row['filled_trades']} | {num(row['realized_positive_rate_pct'],'%')} | {num(row['median_realized_return_pct'],'%')} | {num(row['capital_deployed_krw'])} | {num(row['realized_pnl_contribution_krw'])} |")
    lines += ["", "## Annual returns", "", "| 전략 | Year | Return |", "|---|---:|---:|"]
    for row in annual:
        lines.append(f"| {row['strategy_id']} | {row['year_label']} | {num(row['return_pct'],'%')} |")
    lines += ["", "## Validation", "", f"- Verdict: {validation['verdict']}", f"- Passed: {validation['passed']}", f"- Portfolio run attempts: {validation.get('portfolio_run_attempt_count', 0)}", f"- Candidate ETFs requested / zero-candidate requested: {validation.get('portfolio_price_requested_ticker_count', 'n/a')} / {validation.get('price_requested_for_zero_candidate_etf_count', 'n/a')}", f"- Candidate-required price coverage missing: {validation.get('candidate_required_price_coverage_missing_count', 'n/a')}", f"- Negative cash / leverage / >5M notional: {validation['negative_cash_count']} / {validation['leverage_usage_krw']} / {validation['position_notional_over_5m_count']}", f"- Post-cutoff entry / future fallback / nearest-date fallback: {validation['post_cutoff_new_entry_count']} / {validation['future_fallback_count']} / {validation['nearest_date_fallback_count']}", f"- Unauthorized ETF / exclusion: {validation['unauthorized_etf_count']} / {validation['unauthorized_exclusion_count']}", f"- Eligibility / execution timing / exact price / same-day ordering mismatches: {validation['common_eligibility_mismatch_count']} / {validation['execution_timing_mismatch_count']} / {validation['execution_price_mismatch_count']} / {validation['same_day_ordering_mismatch_count']}", f"- Group A parity mismatches / Group B unexplained divergences: {validation['group_a_v06_parity_mismatch_count']} / {validation['group_b_unexplained_divergence_count']}", f"- Revalidation replay counts (candidate / portfolio): {validation.get('candidate_replay_rerun_count', 'n/a')} / {validation.get('portfolio_replay_rerun_count', 'n/a')}", f"- Worker runtime: {json.dumps(runtime, ensure_ascii=False, sort_keys=True)}", "", "## Artifacts", "", "- candidate_trade_ledger.csv", "- candidate_summary.json", "- portfolio_trade_ledger.csv", "- portfolio_metrics.csv", "- execution_summary.csv", "- equity_curve.csv", "- annual_returns.csv", "- category_contribution.csv", "- parity_report.json", "- validation.json", "- preflight_sample.json", ""]
    return "\n".join(lines)


def _run_full(
    universe: Sequence[dict[str, str]], data_info: Mapping[str, Any], db_path: Path,
    baseline: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any],
    plan: Mapping[str, Mapping[str, Any]], sample: Mapping[str, Any], raw_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if FULL_ATTEMPT_MARKER.exists():
        raise RuntimeError("FULL_RUN_ALREADY_ATTEMPTED_NO_AUTOMATIC_RERUN")
    _write_json(FULL_ATTEMPT_MARKER, {
        "attempt_started": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "workers": WORKERS, "full_run_attempt_count": 1,
        "candidate_lifecycle_attempt_count": 1, "portfolio_run_attempt_count": 0,
        "sample_verdict": sample.get("verdict"),
        "universe_count": len(universe),
    })
    score, stage = v03._read_contracts()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=WORKERS, initializer=v03._init_worker,
        initargs=(str(db_path), score, stage, data_info["calendar_dates_internal"], data_info["month_ends_internal"]),
    ) as pool:
        futures = {pool.submit(_worker_process_instrument, item): item for item in universe}
        for finished, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({**item, "ticker": item["ticker"], "status": "ERROR", "reason": "WORKER_EXCEPTION", "common_evaluable_start": None, "trades": {strategy: [] for strategy in STRATEGIES}, "errors": [f"{type(exc).__name__}:{str(exc)[:500]}"], "missing_session_count": 0})
            if finished % 50 == 0 or finished == len(universe):
                print(f"V03 lifecycle replay {finished}/{len(universe)} ETFs", flush=True)
    results.sort(key=lambda row: str(row["ticker"]))
    lifecycle_seconds = time.perf_counter() - started
    candidate_summary = _save_candidate_lifecycle(results, universe, plan, sample, lifecycle_seconds)
    all_trades = [trade for result in results for strategy in STRATEGIES for trade in result.get("trades", {}).get(strategy, [])]
    price_tickers = _portfolio_price_universe(all_trades)
    errors = [row for row in results if row.get("status") == "ERROR" or row.get("errors")]
    if errors:
        portfolio = {strategy: _empty_portfolio(strategy) for strategy in STRATEGIES}
        coverage = {
            "checked": False,
            "authority_universe_ticker_count": len(universe),
            "candidate_trade_ticker_count": len(price_tickers),
            "portfolio_price_requested_ticker_count": 0,
            "zero_candidate_etf_count": len(universe) - len(price_tickers),
            "price_requested_for_zero_candidate_etf_count": 0,
            "candidate_required_price_coverage_missing_count": 0,
            "candidate_required_price_coverage_missing": [],
            "candidate_required_raw_session_gap_count": sum(int(row.get("missing_session_count", 0)) for row in results if str(row.get("ticker")) in set(price_tickers)),
            "blocked_reason": "CANDIDATE_LIFECYCLE_ERRORS",
        }
        candidate_summary.update({"portfolio_price_coverage": coverage, "portfolio_price_universe": price_tickers})
        _write_json(OUTPUT_DIR / "candidate_summary.json", candidate_summary)
        validation, parity = _validation_and_parity(results, baseline, universe, plan, portfolio, sample, raw_audit, coverage)
        runtime = {"worker_count": WORKERS, "lifecycle_wall_seconds": round(lifecycle_seconds, 3), "portfolio_wall_seconds": 0.0, "total_wall_seconds": round(time.perf_counter() - started, 3)}
        _write_outputs(results, baseline, portfolio, sample, validation, parity, metadata, plan, raw_audit, runtime)
        return {"validation": validation, "parity": parity, "runtime": runtime, "portfolio": portfolio, "results": results}

    coverage = _audit_candidate_price_coverage(db_path, all_trades, results, authority_universe_count=len(universe))
    candidate_summary.update({"portfolio_price_coverage": coverage, "portfolio_price_universe": price_tickers})
    _write_json(OUTPUT_DIR / "candidate_summary.json", candidate_summary)
    if coverage["candidate_required_price_coverage_missing_count"] != 0 or coverage["price_requested_for_zero_candidate_etf_count"] != 0:
        portfolio = {strategy: _empty_portfolio(strategy) for strategy in STRATEGIES}
        coverage["blocked_reason"] = "CANDIDATE_PRICE_COVERAGE_MISSING"
        candidate_summary["portfolio_price_coverage"] = coverage
        _write_json(OUTPUT_DIR / "candidate_summary.json", candidate_summary)
        validation, parity = _validation_and_parity(results, baseline, universe, plan, portfolio, sample, raw_audit, coverage)
        runtime = {"worker_count": WORKERS, "lifecycle_wall_seconds": round(lifecycle_seconds, 3), "portfolio_wall_seconds": 0.0, "total_wall_seconds": round(time.perf_counter() - started, 3)}
        _write_outputs(results, baseline, portfolio, sample, validation, parity, metadata, plan, raw_audit, runtime)
        return {"validation": validation, "parity": parity, "runtime": runtime, "portfolio": portfolio, "results": results}

    try:
        daily_frames = _load_daily_frames(db_path, price_tickers)
    except Exception as exc:
        portfolio = {strategy: _empty_portfolio(strategy) for strategy in STRATEGIES}
        coverage["checked"] = True
        coverage["blocked_reason"] = f"PORTFOLIO_PRICE_LOAD_ERROR:{type(exc).__name__}:{str(exc)[:300]}"
        candidate_summary["portfolio_price_coverage"] = coverage
        _write_json(OUTPUT_DIR / "candidate_summary.json", candidate_summary)
        validation, parity = _validation_and_parity(results, baseline, universe, plan, portfolio, sample, raw_audit, coverage)
        validation["error"] = coverage["blocked_reason"]
        runtime = {"worker_count": WORKERS, "lifecycle_wall_seconds": round(lifecycle_seconds, 3), "portfolio_wall_seconds": 0.0, "total_wall_seconds": round(time.perf_counter() - started, 3)}
        _write_outputs(results, baseline, portfolio, sample, validation, parity, metadata, plan, raw_audit, runtime)
        return {"validation": validation, "parity": parity, "runtime": runtime, "portfolio": portfolio, "results": results}

    calendar_dates = data_info["calendar_dates_internal"]
    category_by_ticker = {row["ticker"]: row["category"] for row in universe}
    portfolio: dict[str, Any] = {}
    portfolio_started = time.perf_counter()
    marker = json.loads(FULL_ATTEMPT_MARKER.read_text(encoding="utf-8"))
    marker["portfolio_run_attempt_count"] = 1
    marker["portfolio_run_started_at"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat()
    _write_json(FULL_ATTEMPT_MARKER, marker)
    for strategy in STRATEGIES:
        trades = [trade for trade in all_trades if trade["strategy_id"] == strategy]
        portfolio[strategy] = _portfolio_replay(trades, daily_frames, calendar_dates, strategy, category_by_ticker)
    portfolio_seconds = time.perf_counter() - portfolio_started
    validation, parity = _validation_and_parity(results, baseline, universe, plan, portfolio, sample, raw_audit, coverage)
    runtime = {"worker_count": WORKERS, "lifecycle_wall_seconds": round(lifecycle_seconds, 3), "portfolio_wall_seconds": round(portfolio_seconds, 3), "total_wall_seconds": round(time.perf_counter() - started, 3)}
    _write_outputs(results, baseline, portfolio, sample, validation, parity, metadata, plan, raw_audit, runtime)
    return {"validation": validation, "parity": parity, "runtime": runtime, "portfolio": portfolio, "results": results}


def _empty_portfolio(strategy_id: str) -> dict[str, Any]:
    ledger = pd.DataFrame(columns=[
        "strategy_id", "ticker", "category", "source_signal_details", "entry_status", "exit_status",
        "buy_notional_krw", "sell_notional_krw", "buy_commission_krw", "sell_commission_krw",
        "sell_tax_krw", "terminal_market_value_krw", "terminal_unrealized_pnl_krw",
        "realized_pnl_krw", "realized_net_return_pct",
    ])
    curve = pd.DataFrame(columns=[
        "date", "strategy_id", "cash", "invested_market_value", "total_equity",
        "open_positions", "cash_ratio", "invested_ratio", "valuation_basis_date", "execution_support_only",
    ])
    summary: dict[str, Any] = {
        "strategy_id": strategy_id, "run_status": "NOT_RUN",
        "candidate_entry_signals": 0, "filled_entries": 0, "CASH_SKIP": 0,
        "open_position_skip": 0, "total_exits": 0, "terminal_positions": 0,
        "fill_rate_pct": None, "final_equity_krw": None, "final_equity_at_cutoff_krw": None,
        "final_cash_krw": None, "cash_at_cutoff_krw": None,
        "terminal_market_value_krw": None, "terminal_unrealized_pnl_krw": None,
        "realized_pnl_krw": None, "total_return_pct": None, "CAGR_pct": None,
        "mdd_pct": None, "mdd_start_date": None, "mdd_trough_date": None,
        "mdd_recovery_date": None, "mdd_recovered": None,
        "average_cash_ratio_pct": None, "average_invested_ratio_pct": None,
        "average_concurrent_positions": None, "median_concurrent_positions": None,
        "max_concurrent_positions": None, "median_holding_sessions": None,
        "negative_cash_count": 0, "leverage_usage_krw": 0.0,
        "position_notional_over_5m_count": 0, "cash_conservation_error_count": 0,
        "same_day_ordering_mismatch_count": 0, "post_cutoff_new_entry_count": 0,
        "cutoff_open_positions_including_support_exits": 0, "cutoff_terminal_positions": 0,
    }
    return {"ledger": ledger, "events": pd.DataFrame(), "curve": curve, "summary": summary}


def _write_check_required_bundle(
    validation: Mapping[str, Any], sample: Mapping[str, Any] | None = None,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    marker = json.loads(FULL_ATTEMPT_MARKER.read_text(encoding="utf-8")) if FULL_ATTEMPT_MARKER.is_file() else {}
    validation_payload = {
        **dict(validation),
        "verdict": "CHECK_REQUIRED", "passed": False,
        "full_portfolio_run_attempt_count": int(marker.get("full_run_attempt_count", validation.get("full_portfolio_run_attempt_count", 0))),
        "portfolio_run_attempt_count": int(marker.get("portfolio_run_attempt_count", validation.get("portfolio_run_attempt_count", 0))),
    }
    empty_schemas = {
        "candidate_trade_ledger.csv": ["strategy_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date", "trade_status", "category", "common_start_group"],
        "portfolio_trade_ledger.csv": ["strategy_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date", "entry_status", "exit_status", "shares", "category"],
        "equity_curve.csv": ["date", "strategy_id", "cash", "invested_market_value", "total_equity", "open_positions"],
        "annual_returns.csv": ["strategy_id", "year", "year_label", "starting_equity_krw", "ending_equity_krw", "return_pct"],
    }
    for filename, columns in empty_schemas.items():
        target = OUTPUT_DIR / filename
        if filename == "candidate_trade_ledger.csv" and target.is_file():
            continue
        pd.DataFrame(columns=columns).to_csv(target, index=False, lineterminator="\n")
    candidate_summary_path = OUTPUT_DIR / "candidate_summary.json"
    if not candidate_summary_path.is_file():
        _write_json(candidate_summary_path, {
            "verdict": "CANDIDATE_LIFECYCLE_NOT_RUN",
            "sealed": False,
            "reason": validation_payload.get("error", validation_payload.get("blocked_stage")),
        })
    metrics_rows = [{"strategy_id": strategy, "run_status": "NOT_COMPLETED", "final_equity_krw": None, "CAGR_pct": None, "mdd_pct": None, "reason": validation_payload.get("error", validation_payload.get("blocked_stage"))} for strategy in STRATEGIES]
    execution_rows = [{"strategy_id": strategy, "run_status": "NOT_COMPLETED", "candidate_entries": None, "filled_entries": None, "CASH_SKIP": None, "open_position_skip": None, "total_exits": None, "terminal_positions": None, "fill_rate_pct": None} for strategy in STRATEGIES]
    category_rows = [{"strategy_id": strategy, "category": category, "run_status": "NOT_COMPLETED", "filled_trades": None, "realized_pnl_contribution_krw": None} for strategy in STRATEGIES for category in CATEGORY_ORDER]
    pd.DataFrame(metrics_rows).to_csv(OUTPUT_DIR / "portfolio_metrics.csv", index=False, lineterminator="\n")
    pd.DataFrame(execution_rows).to_csv(OUTPUT_DIR / "execution_summary.csv", index=False, lineterminator="\n")
    pd.DataFrame(category_rows).to_csv(OUTPUT_DIR / "category_contribution.csv", index=False, lineterminator="\n")
    _write_json(OUTPUT_DIR / "parity_report.json", {"verdict": "CHECK_REQUIRED", "reason": validation_payload.get("error", validation_payload.get("blocked_stage"))})
    _write_json(OUTPUT_DIR / "validation.json", validation_payload)
    if sample is not None:
        _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
    elif not (OUTPUT_DIR / "preflight_sample.json").is_file():
        _write_json(OUTPUT_DIR / "preflight_sample.json", {"verdict": "NOT_RUN", "validation_passed": False})
    reason = validation_payload.get("error", validation_payload.get("blocked_stage", "validation gate"))
    (OUTPUT_DIR / "summary.md").write_text(
        "# ETF V06 A FAST vs Julia 실전 포트폴리오 배틀 V03 — CHECK_REQUIRED\n\n"
        "Full run 결과를 확정하지 못했어. 포트폴리오 수익 지표는 산출되지 않았어.\n\n"
        f"- 차단 단계: `{reason}`\n"
        f"- Full-run 시도: {validation_payload['full_portfolio_run_attempt_count']}회\n"
        f"- Portfolio battle 시도: {validation_payload['portfolio_run_attempt_count']}회\n"
        "- candidate_trade_ledger.csv와 candidate_summary.json은 lifecycle 산출물 상태를 나타내.\n"
        "- 상세 내용은 validation.json과 preflight_sample.json을 확인해.\n",
        encoding="utf-8",
    )


def _run(output: Path | None = None) -> dict[str, Any]:
    global OUTPUT_DIR, FULL_ATTEMPT_MARKER
    if output is not None:
        OUTPUT_DIR = output
        FULL_ATTEMPT_MARKER = OUTPUT_DIR / "full_run_attempted.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    universe, _v06_starts, baseline, metadata = _load_authorities()
    plan = _readiness_plan(universe)
    for row in universe:
        row["v06_common_evaluable_start"] = plan[row["ticker"]]["v06_common_start"] or ""
    sample = _choose_sample(universe, plan)
    with tempfile.TemporaryDirectory(prefix="etf_v03_raw_") as temp_dir:
        db_path = Path(temp_dir) / "raw_etf_prices.sqlite3"
        data_info = v03._build_price_database(db_path, ROOT / v03.RAW_STORE_REL, universe)
        raw_audit = _audit_raw_data(db_path, universe)
        if raw_audit["other_invalid_ohlc_rows"] != 0:
            validation = {"verdict": "CHECK_REQUIRED", "passed": False, "full_portfolio_run_attempt_count": 0, "blocked_stage": "RAW_DATA_AUDIT", "raw_data_audit": raw_audit}
            _write_check_required_bundle(validation)
            return {"validation": validation}
        sample_result = _run_sample(sample, data_info, db_path, baseline, plan)
        _write_json(OUTPUT_DIR / "preflight_sample.json", sample_result)
        if sample_result["verdict"] != "SAMPLE_PASS":
            validation = {"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "SAMPLE", "full_portfolio_run_attempt_count": 0, "sample": sample_result, "raw_data_audit": raw_audit}
            _write_check_required_bundle(validation, sample_result)
            return {"validation": validation, "sample": sample_result}
        result = _run_full(universe, data_info, db_path, baseline, metadata, plan, sample_result, raw_audit)
        return {"validation": result["validation"], "sample": sample_result, "parity": result.get("parity"), "runtime": result.get("runtime")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run sample preflight and exactly one full battle if it passes.")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    if FULL_ATTEMPT_MARKER.exists():
        _write_json(OUTPUT_DIR / "validation.json", {"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "FULL_RUN_GUARD", "full_portfolio_run_attempt_count": 1, "reason": "Full run has already been attempted; automatic retry is prohibited."})
        print(json.dumps({"verdict": "CHECK_REQUIRED", "stage": "FULL_RUN_GUARD"}, ensure_ascii=False))
        return 2
    try:
        outcome = _run()
    except Exception as exc:
        # A preflight exception occurs before the full-run marker. Exceptions after
        # the marker preserve it, preventing a prohibited second full-run attempt.
        _write_check_required_bundle({"error": f"{type(exc).__name__}:{str(exc)[:500]}", "full_portfolio_run_attempt_count": 1 if FULL_ATTEMPT_MARKER.exists() else 0})
        print(json.dumps({"verdict": "CHECK_REQUIRED", "error": f"{type(exc).__name__}:{str(exc)[:300]}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"verdict": outcome["validation"]["verdict"], "validation_passed": outcome["validation"]["passed"], "full_run_attempt_count": outcome["validation"].get("full_portfolio_run_attempt_count", 0), "runtime": outcome.get("runtime")}, ensure_ascii=False))
    return 0 if outcome["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
