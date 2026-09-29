#!/usr/bin/env python3
"""Run the guarded V06 plain-long ETF three-strategy replay."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as v03  # noqa: E402

OUTPUT_DIR = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v06"
V05_UNIVERSE_PATH = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v05/included_plain_long_universe_2026-09-29.csv"
UNIVERSE_PATH = OUTPUT_DIR / "included_plain_long_universe_2026-09-29.csv"
FULL_ATTEMPT_MARKER = OUTPUT_DIR / "full_run_attempted.json"
PERMANENT_EXCLUSIONS = {
    "269530": "PLUS S&P글로벌인프라",
    "265690": "ACE 러시아MSCI(합성)",
}
SAMPLE_SELECTION = (
    ("DOMESTIC_MARKET", "069500"),
    ("OVERSEAS_MARKET", "133690"),
    ("SECTOR", "091160"),
    ("GOLD", "132030"),
    ("SILVER", "144600"),
    ("CRUDE_OIL", "261220"),
    ("COPPER", "138910"),
)
CATEGORY_ORDER = ("MARKET_INDEX", "SECTOR_INDUSTRY", "COMMODITY_RESOURCE")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _load_universe() -> tuple[pd.DataFrame, list[dict[str, str]], dict[str, Any]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not V05_UNIVERSE_PATH.is_file():
        raise RuntimeError(f"V05_CLASSIFICATION_AUTHORITY_MISSING:{V05_UNIVERSE_PATH}")
    source = pd.read_csv(V05_UNIVERSE_PATH, dtype={"ticker": "string", "ISU_CD": "string"})
    required = {
        "ticker", "ISU_CD", "ETF_name", "listing_date", "category",
        "classification_basis", "plain_long", "include",
    }
    missing = sorted(required - set(source.columns))
    if missing or source.empty:
        raise RuntimeError(f"V05_INCLUDED_UNIVERSE_INVALID:{missing}")
    source["ticker"] = source["ticker"].map(v03._norm_ticker)
    if source["ticker"].duplicated().any():
        raise RuntimeError("V05_INCLUDED_UNIVERSE_DUPLICATE_TICKER")
    exclusions_found = set(source.loc[source["ticker"].isin(PERMANENT_EXCLUSIONS), "ticker"])
    if exclusions_found != set(PERMANENT_EXCLUSIONS):
        raise RuntimeError(f"V06_PERMANENT_EXCLUSION_SET_MISMATCH:{sorted(exclusions_found)}")
    source["listing_date"] = pd.to_datetime(source["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if source[["ticker", "ISU_CD", "ETF_name", "listing_date", "category"]].isna().any().any():
        raise RuntimeError("V05_INCLUDED_UNIVERSE_REQUIRED_VALUE_MISSING")
    if not source["plain_long"].astype(bool).all() or not source["include"].astype(bool).all():
        raise RuntimeError("V05_INCLUDED_UNIVERSE_AUTHORITY_HAS_NONINCLUDED_ROWS")
    if not source["category"].isin(CATEGORY_ORDER).all():
        raise RuntimeError("V05_INCLUDED_UNIVERSE_HAS_OUT_OF_SCOPE_CATEGORY")
    for ticker, expected_name in PERMANENT_EXCLUSIONS.items():
        actual_name = str(source.loc[source["ticker"].eq(ticker), "ETF_name"].iloc[0])
        if actual_name != expected_name:
            raise RuntimeError(f"V06_PERMANENT_EXCLUSION_NAME_MISMATCH:{ticker}")

    excluded = source.loc[source["ticker"].isin(PERMANENT_EXCLUSIONS)].copy()
    frame = source.loc[~source["ticker"].isin(PERMANENT_EXCLUSIONS)].copy()
    if len(frame) != len(source) - 2:
        raise RuntimeError("V06_UNAUTHORIZED_UNIVERSE_CHANGE")
    frame = frame.sort_values("ticker", kind="mergesort").reset_index(drop=True)
    frame.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
    excluded.to_csv(OUTPUT_DIR / "permanent_exclusions.csv", index=False, encoding="utf-8-sig")
    universe = [
        {
            "ticker": row.ticker,
            "ISU_CD": str(row.ISU_CD).strip().upper(),
            "name": str(row.ETF_name).strip(),
            "listing_date": row.listing_date,
            "category": row.category,
        }
        for row in frame.itertuples(index=False)
    ]
    audit = {
        "authority": str(V05_UNIVERSE_PATH.relative_to(ROOT)),
        "authority_sha256": _sha256(V05_UNIVERSE_PATH),
        "authority_ticker_count": int(len(source)),
        "included_ticker_count": int(len(frame)),
        "category_counts": {
            str(k): int(v) for k, v in frame["category"].value_counts().sort_index().items()
        },
        "permanent_exclusions": [
            {"ticker": ticker, "name": name, "reason": "USER_PREAUTHORIZED_RAW_OHLC_STRUCTURE_EXCLUSION"}
            for ticker, name in PERMANENT_EXCLUSIONS.items()
        ],
        "permanent_exclusion_tickers": sorted(PERMANENT_EXCLUSIONS),
        "unauthorized_exclusion_count": 0,
        "target_ticker_sha256": hashlib.sha256(
            "\n".join(frame["ticker"].tolist()).encode("utf-8")
        ).hexdigest(),
    }
    _write_json(OUTPUT_DIR / "universe_audit.json", audit)
    return frame, universe, audit


def strict_no_trade_mask(daily: pd.DataFrame) -> pd.Series:
    """Apply only the exact W06 signature."""
    required = {"volume", "open", "high", "low", "close"}
    if not required.issubset(daily.columns):
        raise ValueError(f"NO_TRADE_REQUIRED_COLUMNS_MISSING:{sorted(required - set(daily.columns))}")
    return (
        daily["volume"].eq(0) & daily["open"].eq(0) & daily["high"].eq(0)
        & daily["low"].eq(0) & daily["close"].gt(0)
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
    """Drop exact no-trade rows only from technical input; never fill or mutate raw data."""
    if not isinstance(daily_raw.index, pd.DatetimeIndex) or daily_raw.index.has_duplicates:
        raise ValueError("RAW_DAILY_INDEX_INVALID")
    no_trade = strict_no_trade_mask(daily_raw)
    invalid = _invalid_ohlc_mask(daily_raw) & ~no_trade
    if invalid.any():
        dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in daily_raw.index[invalid][:10]]
        raise RuntimeError(f"OTHER_INVALID_OHLC_FAIL_CLOSED:{len(dates)}:{','.join(dates)}")
    technical = daily_raw.loc[~no_trade].copy()
    removed = daily_raw.loc[no_trade].copy()
    if not technical.index.isin(daily_raw.index).all():
        raise RuntimeError("SYNTHETIC_TECHNICAL_ROW_DETECTED")
    return technical, removed


def common_period_start(
    listing_anniversary: str | None,
    fast_ready: str | None,
    select_ready: str | None,
    julia_ready: str | None,
    volume_ready: str | None,
) -> str | None:
    dates = (listing_anniversary, fast_ready, select_ready, julia_ready, volume_ready)
    if any(value is None or str(value) == "" for value in dates):
        return None
    return max(pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates if value is not None)


def post_cutoff_entry_count(trades: list[Mapping[str, Any]], cutoff: str | None = None) -> int:
    limit = cutoff or v03._iso(v03.CUTOFF)
    return sum(
        1 for trade in trades
        if str(trade.get("signal_date", "")) > limit
        or str(trade.get("entry_execution_date", "")) > limit
    )


def _audit_technical_rows(db_path: Path, universe: list[dict[str, str]]) -> dict[str, Any]:
    listing_by_ticker = {row["ticker"]: row["listing_date"] for row in universe}
    events: list[dict[str, Any]] = []
    invalid_examples: list[dict[str, str]] = []
    total_rows = strict_count = invalid_count = 0
    with sqlite3.connect(db_path) as connection:
        query = "SELECT ticker,date,open,high,low,close,volume FROM bars ORDER BY ticker,date"
        for chunk in pd.read_sql_query(query, connection, chunksize=100_000):
            chunk["ticker"] = chunk["ticker"].map(v03._norm_ticker)
            chunk["date"] = pd.to_datetime(chunk["date"])
            chunk["listing_date"] = chunk["ticker"].map(listing_by_ticker)
            chunk = chunk.loc[chunk["date"] >= pd.to_datetime(chunk["listing_date"])].copy()
            if chunk.empty:
                continue
            total_rows += len(chunk)
            no_trade = strict_no_trade_mask(chunk)
            strict_count += int(no_trade.sum())
            for row in chunk.loc[no_trade, ["ticker", "date", "close"]].itertuples(index=False):
                events.append({
                    "ticker": str(row.ticker),
                    "date": pd.Timestamp(row.date).strftime("%Y-%m-%d"),
                    "close": float(row.close),
                })
            invalid = _invalid_ohlc_mask(chunk) & ~no_trade
            invalid_count += int(invalid.sum())
            if invalid.any() and len(invalid_examples) < 25:
                for row in chunk.loc[invalid].head(25 - len(invalid_examples)).itertuples(index=False):
                    invalid_examples.append({
                        "ticker": str(row.ticker),
                        "date": pd.Timestamp(row.date).strftime("%Y-%m-%d"),
                    })
    events.sort(key=lambda row: (row["ticker"], row["date"]))
    pd.DataFrame(events, columns=["ticker", "date", "close"]).to_csv(
        OUTPUT_DIR / "no_trade_session_events_2026-09-29.csv", index=False
    )
    summary = {
        "snapshot_date": "2026-09-29",
        "universe_count": len(universe),
        "raw_ticker_date_rows_from_listing": total_rows,
        "technical_input_rows_after_exact_filter": total_rows - strict_count,
        "no_trade_definition": "volume == 0 AND open == 0 AND high == 0 AND low == 0 AND close > 0",
        "no_trade_rows_excluded_from_technical_ohlc": strict_count,
        "no_trade_ticker_count": len({row["ticker"] for row in events}),
        "volume_zero_retained_in_raw_eligibility": True,
        "raw_source_rewritten": False,
        "synthetic_fill_count": 0,
        "other_invalid_ohlc_row_count": invalid_count,
        "other_invalid_ohlc_examples": invalid_examples,
        "permanent_exclusion_tickers": sorted(PERMANENT_EXCLUSIONS),
        "cutoff_date": v03._iso(v03.CUTOFF),
        "execution_support_date": v03._iso(v03.EXECUTION_SUPPORT),
    }
    _write_json(OUTPUT_DIR / "no_trade_session_audit.json", summary)
    return summary


def _market_month_observations_v06(
    ticker: str, name: str, daily: pd.DataFrame, context: Any, listing_date: str,
) -> tuple[list[dict[str, Any]], str | None, int]:
    """Use the canonical evaluators at their original KRX month-end dates."""
    observations: list[dict[str, Any]] = []
    ready_date = None
    for date in v03._WORKER["month_ends"]:
        if date < listing_date or pd.Timestamp(date) < daily.index.min() or pd.Timestamp(date) > v03.CUTOFF:
            continue
        b_result = v03.evaluate_pattern_b(ticker, daily, date, name=name)
        snapshot = v03.build_historical_snapshot_from_context(
            context, date, include_incomplete_periods=False,
            market_calendar=v03._WORKER["calendar"],
        )
        a_result = v03.evaluate_pattern_a(snapshot)
        a_stage = a_result.stage.value.upper() if a_result.stage is not None else "UNAVAILABLE"
        a_score = float(a_result.score) if a_result.score is not None and math.isfinite(float(a_result.score)) else None
        b_state = (
            b_result.pattern_b_state
            if b_result.evaluation_status == v03.PatternBEvaluationStatus.READY else None
        )
        observations.append({
            "date": date,
            "pattern_b_state": b_state,
            "pattern_b_status": b_result.evaluation_status.value,
            "pattern_a_stage": a_stage,
            "pattern_a_score": a_score,
            "pattern_b_monthly_last_bar": b_result.monthly_last_bar,
            "pattern_b_weekly_last_bar": b_result.weekly_last_bar,
        })
        if (
            ready_date is None
            and b_result.evaluation_status == v03.PatternBEvaluationStatus.READY
            and a_stage != "UNAVAILABLE"
        ):
            ready_date = date
    return observations, ready_date, len(observations)


def _process_ticker_v06(instrument: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    ticker = v03._norm_ticker(instrument["ticker"])
    name, isu_cd = str(instrument["name"]), str(instrument["ISU_CD"])
    listing_date = v03._iso(instrument["listing_date"])
    errors: list[str] = []
    timings: dict[str, float] = {}
    empty_trades = {strategy: [] for strategy in v03.STRATEGY_IDS}
    daily_raw = v03._load_ticker_daily(ticker)
    if daily_raw.empty:
        return {
            **instrument, "ticker": ticker, "status": "NOT_EVALUABLE",
            "reason": "NO_RAW_ETF_PRICE_HISTORY_THROUGH_CUTOFF",
            "common_evaluable_start": None, "evaluable_years": 0.0,
            "missing_session_count": 0, "strict_no_trade_rows_excluded": 0,
            "no_trade_rows_in_technical_input": 0, "trades": empty_trades, "errors": [],
        }
    daily_raw = daily_raw.loc[daily_raw.index >= pd.Timestamp(listing_date)].copy()
    if daily_raw.empty:
        return {
            **instrument, "ticker": ticker, "status": "NOT_EVALUABLE",
            "reason": "RAW_ROWS_PRECEDE_CURRENT_LISTING_DATE",
            "common_evaluable_start": None, "evaluable_years": 0.0,
            "missing_session_count": 0, "strict_no_trade_rows_excluded": 0,
            "no_trade_rows_in_technical_input": 0, "trades": empty_trades, "errors": [],
        }
    daily_technical, no_trade_rows = split_technical_daily(daily_raw)
    if daily_technical.empty:
        raise RuntimeError(f"NO_VALID_TECHNICAL_OHLC_ROWS:{ticker}")

    cutoff_missing = v03.CUTOFF not in daily_raw.index
    observed_dates = set(daily_raw.index)
    raw_start = max(pd.Timestamp(daily_raw.index.min()), pd.Timestamp(listing_date))
    expected = [
        pd.Timestamp(day) for day in v03._WORKER["calendar_dates"]
        if raw_start <= pd.Timestamp(day) <= v03.EXECUTION_SUPPORT
    ]
    missing_dates = [d.strftime("%Y-%m-%d") for d in expected if d not in observed_dates]
    cutoff_gaps = sum(pd.Timestamp(d) <= v03.CUTOFF for d in missing_dates)
    if cutoff_gaps:
        errors.append(f"RAW_SESSION_GAP_THROUGH_CUTOFF:{cutoff_gaps}")
    if not cutoff_missing and v03.EXECUTION_SUPPORT not in daily_raw.index:
        errors.append("RAW_EXECUTION_SUPPORT_SESSION_MISSING")

    phase = time.perf_counter()
    context = v03.build_precomputed_ticker_context(ticker, name, daily_technical)
    timings["context_seconds"] = round(time.perf_counter() - phase, 4)
    ready_started = time.perf_counter()
    fast_ready, fast_calls = v03._find_fast_ready_date(
        ticker, name, daily_technical, context, listing_date
    )
    observations, select_ready, monthly_calls = _market_month_observations_v06(
        ticker, name, daily_technical, context, listing_date
    )
    _elig, _metrics, volume_ready, _audit = v03._raw_eligibility(daily_raw, listing_date, None)
    julia_ready = fast_ready
    listing_anniversary = (
        pd.Timestamp(listing_date) + pd.DateOffset(years=2)
    ).strftime("%Y-%m-%d")
    common_start = common_period_start(
        listing_anniversary, fast_ready, select_ready, julia_ready, volume_ready
    )
    timings["readiness_seconds"] = round(time.perf_counter() - ready_started, 4)
    evaluable = bool(common_start and pd.Timestamp(common_start) <= v03.CUTOFF and not cutoff_missing)
    reasons = []
    if pd.Timestamp(listing_date) + pd.DateOffset(years=2) > v03.CUTOFF:
        reasons.append("LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF")
    if fast_ready is None:
        reasons.append("A_FAST_OR_JULIA_NOT_READY_BY_CUTOFF")
    if select_ready is None:
        reasons.append("SELECT_CORE_NOT_READY_BY_CUTOFF")
    if volume_ready is None:
        reasons.append("20D_VOLUME_WINDOW_NOT_READY_BY_CUTOFF")
    if cutoff_missing:
        reasons.append("MISSING_EXACT_CUTOFF_CLOSE")
    if common_start and pd.Timestamp(common_start) > v03.CUTOFF:
        reasons.append("COMMON_START_AFTER_CUTOFF")

    eligible_dates: set[str] = set()
    eligibility_metrics: dict[str, dict[str, Any]] = {}
    eligibility_audit: dict[str, Any] = {}
    if common_start is not None:
        eligible_dates, eligibility_metrics, _, eligibility_audit = v03._raw_eligibility(
            daily_raw, listing_date, common_start
        )
    v03._WORKER["eligibility_metrics"] = eligibility_metrics
    prior_stage = v03._resolve_previous_stage(
        observations, v03._WORKER["calendar_positions"]
    ) if observations else {}
    trades = {strategy: [] for strategy in v03.STRATEGY_IDS}
    select_raw_count = select_pit_count = 0
    if common_start is not None:
        for observation in observations:
            date = observation["date"]
            prior = prior_stage.get(date, {}).get("previous_pattern_a_stage")
            if (
                date >= common_start and date <= v03._iso(v03.CUTOFF)
                and observation["pattern_b_state"] == "DEPRESSED"
                and observation["pattern_a_stage"] == "PROGRESSED"
                and prior in {"EARLY_TREND", "TRANSITION"}
            ):
                select_raw_count += 1
                nxt = v03._first_session_after(date)
                if date in eligible_dates and nxt is not None and nxt <= v03._iso(v03.CUTOFF):
                    select_pit_count += 1
    timings["stage_history_seconds"] = round(
        time.perf_counter() - ready_started - timings["readiness_seconds"], 4
    )

    if evaluable:
        phase = time.perf_counter()
        fast_records = v03.simulate_ticker_core_v02_reentry(
            ticker=ticker, name=name, market="ETF", daily=daily_technical,
            score_contract=v03._WORKER["score_contract"],
            stage_contract=v03._WORKER["stage_contract"],
            cutoff_date=v03.CUTOFF, snapshot_context=context,
            market_calendar=v03._WORKER["calendar"],
            entry_search_start=pd.Timestamp(common_start),
            signal_cutoff_date=v03.CUTOFF, execution_support_date=v03.EXECUTION_SUPPORT,
            strict_errors=True, entry_execution_cutoff_date=v03.CUTOFF,
            entry_signal_cutoff_date=v03.CUTOFF,
            entry_signal_filter=lambda d, _result: d.strftime("%Y-%m-%d") in eligible_dates,
        )
        trades[v03.STRATEGY_A_FAST] = [
            v03._normalize_strategy_trade(
                record, v03.STRATEGY_A_FAST, ticker, name, isu_cd, daily_raw, common_start
            ) for record in fast_records
        ]
        timings["a_fast_seconds"] = round(time.perf_counter() - phase, 4)
        phase = time.perf_counter()
        trades[v03.STRATEGY_SELECT] = v03._run_select_core(
            ticker, name, isu_cd, daily_raw, observations, common_start, eligible_dates, prior_stage
        )
        timings["select_core_seconds"] = round(time.perf_counter() - phase, 4)
        julia_errors: list[str] = []
        phase = time.perf_counter()
        julia_records = v03._run_julia(
            ticker, name, daily_technical, context, common_start, eligible_dates, julia_errors
        )
        errors.extend(julia_errors)
        trades[v03.STRATEGY_JULIA] = [
            v03._normalize_strategy_trade(
                record, v03.STRATEGY_JULIA, ticker, name, isu_cd, daily_raw, common_start
            ) for record in julia_records
        ]
        timings["julia_seconds"] = round(time.perf_counter() - phase, 4)
    else:
        timings.update({"a_fast_seconds": 0.0, "select_core_seconds": 0.0, "julia_seconds": 0.0})

    for strategy_id, rows in trades.items():
        for trade in rows:
            if trade["signal_date"] not in eligible_dates:
                errors.append(f"TRADE_SIGNAL_FAILED_SHARED_PIT_ELIGIBILITY:{strategy_id}:{trade['signal_date']}")
            if trade["price_source"] != v03.DATA_SOURCE or trade["eligibility_policy_id"] != v03.ELIGIBILITY_POLICY_ID:
                errors.append(f"TRADE_CONTRACT_MISMATCH:{strategy_id}")
    if v03._iso(v03.EXECUTION_SUPPORT) in missing_dates:
        errors.append("RAW_EXECUTION_SUPPORT_SESSION_MISSING")
    return {
        **instrument, "ticker": ticker,
        "status": "EVALUABLE" if evaluable else "NOT_EVALUABLE",
        "reason": ";".join(reasons) if reasons else None,
        "common_evaluable_start": common_start,
        "evaluable_end": v03._iso(v03.CUTOFF) if evaluable else None,
        "evaluable_years": (
            (v03.CUTOFF - pd.Timestamp(common_start)).days / 365.2425
            if evaluable and common_start else 0.0
        ),
        "listing_age_at_cutoff_years": (v03.CUTOFF - pd.Timestamp(listing_date)).days / 365.2425,
        "listing_anniversary_ready_date": listing_anniversary,
        "a_fast_ready_date": fast_ready, "select_core_ready_date": select_ready,
        "julia_ready_date": julia_ready, "volume_20d_ready_date": volume_ready,
        "eligible_signal_date_count": len(eligible_dates), "eligibility_audit": eligibility_audit,
        "_eligible_signal_dates": eligible_dates,
        "strict_no_trade_rows_excluded": int(len(no_trade_rows)),
        "no_trade_rows_in_technical_input": int(strict_no_trade_mask(daily_technical).sum()),
        "pattern_b_month_observation_count": len(observations),
        "pattern_b_state_counts": dict(v03.Counter(row["pattern_b_state"] or "UNAVAILABLE" for row in observations)),
        "pattern_a_stage_counts": dict(v03.Counter(row["pattern_a_stage"] for row in observations)),
        "select_raw_candidate_count": select_raw_count,
        "select_pit_eligible_candidate_count": select_pit_count,
        "pattern_b_evaluator_calls": monthly_calls,
        "fast_evaluator_calls_for_readiness": fast_calls,
        "price_first_date": v03._iso(daily_raw.index.min()),
        "price_last_date": v03._iso(daily_raw.index.max()),
        "has_exact_cutoff_close": not cutoff_missing,
        "missing_session_count": len(missing_dates),
        "missing_session_dates": missing_dates[:20],
        "trades": trades, "errors": errors,
        "timings": {**timings, "ticker_total_seconds": round(time.perf_counter() - started, 4)},
        "price_source": v03.DATA_SOURCE, "eligibility_policy_id": v03.ELIGIBILITY_POLICY_ID,
    }


def _validate_results_v06(
    results: list[dict[str, Any]],
    universe: list[dict[str, str]],
    universe_audit: Mapping[str, Any],
) -> dict[str, Any]:
    base = v03._validate_results(results, universe)
    trades = [
        trade for result in results
        for rows in result.get("trades", {}).values() for trade in rows
    ]
    period_errors: set[str] = set()
    eligibility_errors = int(base["eligibility_policy_mismatch_count"])
    technical_no_trade_rows = 0
    for result in results:
        expected_start = common_period_start(
            result.get("listing_anniversary_ready_date"),
            result.get("a_fast_ready_date"),
            result.get("select_core_ready_date"),
            result.get("julia_ready_date"),
            result.get("volume_20d_ready_date"),
        )
        if result.get("common_evaluable_start") != expected_start:
            period_errors.add(str(result["ticker"]))
        technical_no_trade_rows += int(result.get("no_trade_rows_in_technical_input", 0))
        eligible_dates = result.get("_eligible_signal_dates", set())
        for trade in (
            trade for rows in result.get("trades", {}).values() for trade in rows
        ):
            if trade.get("common_evaluable_start") != expected_start:
                period_errors.add(f"{result['ticker']}:{trade.get('strategy_id')}:PERIOD")
            if trade.get("signal_date") not in eligible_dates:
                eligibility_errors += 1
        eligibility_errors += sum(
            "TRADE_SIGNAL_FAILED_SHARED_PIT_ELIGIBILITY" in error
            for error in result.get("errors", [])
        )

    authority_count = int(universe_audit.get("authority_ticker_count", -1))
    included_count = int(universe_audit.get("included_ticker_count", -1))
    audit_exclusions = {
        str(row.get("ticker")) for row in universe_audit.get("permanent_exclusions", [])
    }
    unauthorized_exclusions = int(
        authority_count - included_count != 2
        or included_count != 427
        or audit_exclusions != set(PERMANENT_EXCLUSIONS)
        or set(PERMANENT_EXCLUSIONS).intersection({row["ticker"] for row in universe})
        or int(universe_audit.get("unauthorized_exclusion_count", 1)) != 0
    )
    post_cutoff = post_cutoff_entry_count(trades)
    passed = bool(
        base["current_universe_all_records_preserved"]
        and base["duplicate_result_instrument_count"] == 0
        and base["raw_session_gap_count"] == 0
        and base["process_error_instrument_count"] == 0
        and not base["evaluator_or_execution_errors"]
        and base["future_fallback_count"] == 0
        and base["nearest_date_fallback_count"] == 0
        and post_cutoff == 0
        and unauthorized_exclusions == 0
        and base["common_period_mismatch_count"] == 0
        and not period_errors
        and base["price_source_mismatch_count"] == 0
        and eligibility_errors == 0
        and technical_no_trade_rows == 0
    )
    return {
        **base,
        "post_cutoff_new_entry_count": post_cutoff,
        "unauthorized_exclusion_count": unauthorized_exclusions,
        "eligibility_mismatch_count": eligibility_errors,
        "exact_common_period_mismatch_count": len(period_errors),
        "exact_common_period_mismatch_instruments": sorted(period_errors),
        "technical_no_trade_input_row_count": technical_no_trade_rows,
        "permanent_exclusion_tickers": sorted(PERMANENT_EXCLUSIONS),
        "passed": passed,
    }


def _error_result(instrument: Mapping[str, str], exc: BaseException) -> dict[str, Any]:
    reason = f"{type(exc).__name__}:{str(exc)[:500]}"
    return {
        **instrument,
        "ticker": instrument["ticker"],
        "status": "PROCESS_ERROR",
        "reason": reason,
        "common_evaluable_start": None,
        "evaluable_years": 0.0,
        "missing_session_count": 0,
        "trades": {strategy: [] for strategy in v03.STRATEGY_IDS},
        "errors": [f"WORKER_FAILURE:{reason}"],
        "strict_no_trade_rows_excluded": 0,
        "no_trade_rows_in_technical_input": 0,
        "_eligible_signal_dates": set(),
    }


def _run_sample(
    universe: list[dict[str, str]],
    db_path: Path,
    data_info: Mapping[str, Any],
    universe_audit: Mapping[str, Any],
) -> dict[str, Any]:
    by_ticker = {row["ticker"]: row for row in universe}
    missing = [ticker for _label, ticker in SAMPLE_SELECTION if ticker not in by_ticker]
    if missing:
        raise RuntimeError(f"V06_REPRESENTATIVE_SAMPLE_MISSING:{missing}")
    selected = [by_ticker[ticker] for _label, ticker in SAMPLE_SELECTION]
    score, stage = v03._read_contracts()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=10,
        initializer=v03._init_worker,
        initargs=(
            str(db_path), score, stage,
            data_info["calendar_dates_internal"], data_info["month_ends_internal"],
        ),
    ) as pool:
        futures = {pool.submit(_process_ticker_v06, item): item for item in selected}
        for future in as_completed(futures):
            instrument = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(_error_result(instrument, exc))
    results.sort(key=lambda row: row["ticker"])
    validation = _validate_results_v06(results, selected, universe_audit)
    sample = {
        "verdict": "SAMPLE_PASS" if validation["passed"] else "CHECK_REQUIRED",
        "sample_basis": "domestic market, overseas market, sector, gold, silver, crude oil, copper",
        "workers": 10,
        "cutoff_date": v03._iso(v03.CUTOFF),
        "execution_support_date": v03._iso(v03.EXECUTION_SUPPORT),
        "sample_count": len(results),
        "sample_rows": [
            {
                **v03._serialize_instrument(row),
                "category": row.get("category"),
                "sample_label": next(label for label, ticker in SAMPLE_SELECTION if ticker == row["ticker"]),
                "strict_no_trade_rows_excluded": row.get("strict_no_trade_rows_excluded", 0),
                "trade_counts": {
                    strategy: len(row.get("trades", {}).get(strategy, []))
                    for strategy in v03.STRATEGY_IDS
                },
                "errors": row.get("errors", []),
                "timings": row.get("timings", {}),
            }
            for row in results
        ],
        "validation": validation,
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
    return sample


def _category_summaries(universe_frame: pd.DataFrame, trade_frame: pd.DataFrame) -> list[dict[str, Any]]:
    category_by_ticker = universe_frame.set_index("ticker")["category"].to_dict()
    ledger = trade_frame.copy()
    if not ledger.empty:
        ledger["category"] = ledger["ticker"].map(category_by_ticker)
    rows = []
    for category in CATEGORY_ORDER:
        ticker_count = int(universe_frame["category"].eq(category).sum())
        for strategy in v03.STRATEGY_IDS:
            subset = (
                ledger.loc[(ledger["category"] == category) & (ledger["strategy_id"] == strategy)]
                if not ledger.empty else pd.DataFrame()
            )
            gross = pd.to_numeric(subset.get("gross_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
            net = pd.to_numeric(
                subset.get("commission_slippage_pre_tax_return_pct", pd.Series(dtype=float)),
                errors="coerce",
            ).dropna()
            rows.append({
                "category": category,
                "strategy_id": strategy,
                "etf_count": ticker_count,
                "trade_count": int(len(subset)),
                "positive_return_rate_pct_gross": float((gross > 0).mean() * 100) if len(gross) else None,
                "mean_gross_return_pct": float(gross.mean()) if len(gross) else None,
                "median_gross_return_pct": float(gross.median()) if len(gross) else None,
                "mean_cost_adjusted_return_pct": float(net.mean()) if len(net) else None,
                "median_cost_adjusted_return_pct": float(net.median()) if len(net) else None,
            })
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "category_strategy_summary.csv", index=False)
    return rows


def _render_report(summary: Mapping[str, Any], category_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# V06 Plain-long ETF 3전략 백테스트",
        "",
        f"- 판정: {summary['verdict']}",
        f"- Universe: {summary['universe']['current_etf_count']}개; 분류별 {json.dumps(summary['universe']['category_counts'], ensure_ascii=False)}",
        "- Permanent exclusion: 269530 PLUS S&P글로벌인프라, 265690 ACE 러시아MSCI(합성)",
        "- Strict NO_TRADE_SESSION 행은 기술 OHLC에서만 제외; 원시 거래량 0은 20D 창에 유지",
        "- cutoff 2026-08-31; execution support 2026-09-01; worker=10",
        "",
        "## 전략별 결과",
        "",
        "| 전략 | 거래 | ETF | 양수 비율 | gross 평균/중앙값 | 비용 반영 평균/중앙값 | 보유 평균/중앙값(세션) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, values in summary.get("strategies", {}).items():
        gross = values.get("trade_weighted_all_positions_gross", {})
        net = values.get("trade_weighted_all_positions_after_cost", {})
        lines.append(
            f"| {strategy} | {values.get('trade_count')} | {values.get('unique_etf_count')} | "
            f"{gross.get('positive_rate_pct')}% | {gross.get('mean_pct')} / {gross.get('median_pct')}% | "
            f"{net.get('mean_pct')} / {net.get('median_pct')}% | "
            f"{values.get('average_holding_krx_sessions')} / {values.get('median_holding_krx_sessions')} |"
        )
    lines.extend([
        "",
        "## 검증",
        "",
        f"- PROCESS_ERROR: {summary['validation'].get('process_error_instrument_count')}",
        f"- evaluator/execution errors: {len(summary['validation'].get('evaluator_or_execution_errors', []))}",
        f"- future/nearest-date fallback: {summary['validation'].get('future_fallback_count')} / {summary['validation'].get('nearest_date_fallback_count')}",
        f"- post-cutoff entry: {summary['validation'].get('post_cutoff_new_entry_count')}",
        f"- unauthorized exclusion: {summary['validation'].get('unauthorized_exclusion_count')}",
        f"- common period / eligibility mismatch: {summary['validation'].get('exact_common_period_mismatch_count')} / {summary['validation'].get('eligibility_mismatch_count')}",
        f"- price source mismatch: {summary['validation'].get('price_source_mismatch_count')}",
        f"- validation passed: {summary['validation'].get('passed')}",
        "",
        "## Category별 결과",
        "",
        "| Category | Strategy | ETF | Trades | Positive % | Mean/Median gross | Mean/Median cost-adjusted |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in category_rows:
        lines.append(
            f"| {row['category']} | {row['strategy_id']} | {row['etf_count']} | {row['trade_count']} | "
            f"{row['positive_return_rate_pct_gross']}% | {row['mean_gross_return_pct']} / "
            f"{row['median_gross_return_pct']}% | {row['mean_cost_adjusted_return_pct']} / "
            f"{row['median_cost_adjusted_return_pct']}% |"
        )
    return "\n".join(lines) + "\n"


def _run_full_v06(
    universe_frame: pd.DataFrame,
    universe: list[dict[str, str]],
    db_path: Path,
    data_info: Mapping[str, Any],
    universe_audit: Mapping[str, Any],
    no_trade_audit: Mapping[str, Any],
    workers: int,
) -> dict[str, Any]:
    if workers != 10:
        raise RuntimeError(f"V06_FULL_RUN_REQUIRES_EXACTLY_10_WORKERS:{workers}")
    if FULL_ATTEMPT_MARKER.exists():
        raise RuntimeError("V06_FULL_RUN_ALREADY_ATTEMPTED_NO_AUTOMATIC_RERUN")
    _write_json(FULL_ATTEMPT_MARKER, {
        "attempt_started": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "workers": 10,
        "universe_count": len(universe),
        "sample_verdict": "SAMPLE_PASS",
        "full_run_attempt_count": 1,
    })
    score, stage = v03._read_contracts()
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=10,
        initializer=v03._init_worker,
        initargs=(
            str(db_path), score, stage,
            data_info["calendar_dates_internal"], data_info["month_ends_internal"],
        ),
    ) as pool:
        futures = {pool.submit(_process_ticker_v06, item): item for item in universe}
        for number, future in enumerate(as_completed(futures), start=1):
            instrument = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(_error_result(instrument, exc))
            if number % 50 == 0 or number == len(universe):
                print(f"V06 full replay {number}/{len(universe)} ETFs", flush=True)
    results.sort(key=lambda row: row["ticker"])
    validation = _validate_results_v06(results, universe, universe_audit)
    all_trades = [
        trade for result in results
        for rows in result.get("trades", {}).values() for trade in rows
    ]
    trade_frame = pd.DataFrame(all_trades)
    if not trade_frame.empty:
        trade_frame.sort_values(
            ["strategy_id", "signal_date", "ticker", "entry_execution_date"],
            kind="mergesort",
        ).to_csv(OUTPUT_DIR / "trade_ledger.csv", index=False)
    else:
        pd.DataFrame(columns=[
            "strategy_id", "ticker", "signal_date", "entry_execution_date",
            "gross_return_pct", "commission_slippage_pre_tax_return_pct",
        ]).to_csv(OUTPUT_DIR / "trade_ledger.csv", index=False)
    instrument_rows = [
        {**v03._serialize_instrument(row), "category": row.get("category")}
        for row in results
    ]
    pd.DataFrame(instrument_rows).sort_values("ticker", kind="mergesort").to_csv(
        OUTPUT_DIR / "etf_readiness.csv", index=False
    )

    evaluable = [row for row in results if row.get("status") == "EVALUABLE"]
    strategies: dict[str, Any] = {}
    top_bottom_rows: list[dict[str, Any]] = []
    for strategy in v03.STRATEGY_IDS:
        strategy_trades = [
            trade for result in results for trade in result.get("trades", {}).get(strategy, [])
        ]
        strategies[strategy] = v03._strategy_summary(strategy, strategy_trades, evaluable)
        ordered = sorted(
            strategy_trades,
            key=lambda row: (row["gross_return_pct"], row["ticker"], row["signal_date"]),
        )
        top_bottom_rows.extend(
            {"ranking": "BOTTOM_10", "rank": rank, **row}
            for rank, row in enumerate(ordered[:10], start=1)
        )
        top_bottom_rows.extend(
            {"ranking": "TOP_10", "rank": rank, **row}
            for rank, row in enumerate(reversed(ordered[-10:]), start=1)
        )
    pd.DataFrame(top_bottom_rows).to_csv(OUTPUT_DIR / "top_bottom_trades.csv", index=False)
    category_rows = _category_summaries(universe_frame, trade_frame)
    timing_rows = [row.get("timings", {}) for row in results]
    runtime = {
        key: round(sum(float(row.get(key, 0)) for row in timing_rows), 3)
        for key in (
            "context_seconds", "readiness_seconds", "stage_history_seconds",
            "a_fast_seconds", "select_core_seconds", "julia_seconds",
        )
    }
    runtime["wall_clock_seconds"] = round(time.perf_counter() - started, 3)
    summary = {
        "verdict": (
            "ETF_PLAIN_LONG_THREE_STRATEGY_SIMPLE_BACKTEST_V06_COMPLETE"
            if validation["passed"] else "CHECK_REQUIRED"
        ),
        "analysis_scope": "EXPLORATORY / CURRENT_SURVIVORS / PLAIN_LONG_MARKET_SECTOR_RESOURCE / RAW_ETF_PRICE",
        "snapshot_date": "2026-09-29",
        "cutoff_date": v03._iso(v03.CUTOFF),
        "execution_support_date": v03._iso(v03.EXECUTION_SUPPORT),
        "SURVIVORSHIP_BIAS": True,
        "RAW_PRICE_LIMITATION": True,
        "adjusted_price_used": False,
        "aggregate_metrics_are_complete": bool(validation["passed"]),
        "universe": {
            "authority_ticker_count": int(universe_audit["authority_ticker_count"]),
            "current_etf_count": len(universe),
            "category_counts": universe_audit["category_counts"],
            "permanent_exclusion_tickers": sorted(PERMANENT_EXCLUSIONS),
            "evaluable_etf_count": len(evaluable),
            "not_evaluable_etf_count": len(universe) - len(evaluable),
            "all_target_etfs_retained_in_readiness_output": len(results) == len(universe),
            "classification_file": str(UNIVERSE_PATH.relative_to(ROOT)),
        },
        "method": {
            "common_evaluable_start": "max(listing date + 2 years, A FAST ready date, Select Core ready date, Julia ready date, 20D raw volume ready date)",
            "common_evaluable_end": v03._iso(v03.CUTOFF),
            "technical_no_trade_rule": "Only volume=0 AND open=0 AND high=0 AND low=0 AND close>0 rows are omitted from technical OHLC inputs.",
            "raw_eligibility": "Raw volume zero remains in the trailing 20 KRX-session average; raw close and listing date are evaluated point-in-time.",
            "synthetic_price_handling": "No OHLC correction, forward-fill, interpolation, or raw source rewrite.",
            "entry_eligibility": "Exact historical raw close >= 1000 KRW; trailing 20 KRX sessions average raw volume >= 10000 shares; listing age >= 2 years.",
            "entry_execution": "Signal EOD then first exact KRX session open; entry execution no later than 2026-08-31.",
            "exit_execution_support": "An exit signaled on or before cutoff may fill through the first exact KRX session on 2026-09-01.",
            "strategy_rule_changes": "None. Existing canonical strategy implementations and Select Core adapter retained.",
            "period_exactness": "One per-ETF common start and cutoff shared by all three strategy replays.",
            "worker_count": 10,
            "full_run_attempt_count": 1,
        },
        "cost_contract": {
            "buy_commission_rate": v03.COMMISSION_RATE,
            "sell_commission_rate": v03.COMMISSION_RATE,
            "buy_slippage_rate": v03.SLIPPAGE_RATE,
            "sell_slippage_rate": v03.SLIPPAGE_RATE,
            "ETF_sell_tax_rate": 0.0,
            "open_position_cost_treatment": "Exact cutoff raw close after entry cost; no hypothetical exit fee.",
            "return_contract": "Gross raw-price return and commission/slippage pre-tax return separately.",
        },
        "strategies": strategies,
        "category_results": category_rows,
        "validation": validation,
        "runtime": runtime,
        "data_source_preflight": {
            key: value for key, value in data_info.items() if not key.endswith("_internal")
        },
        "sample_preflight_verdict": "SAMPLE_PASS",
        "no_trade_session_audit": dict(no_trade_audit),
        "artifact_files": [
            "included_plain_long_universe_2026-09-29.csv", "permanent_exclusions.csv",
            "universe_audit.json", "no_trade_session_audit.json",
            "no_trade_session_events_2026-09-29.csv", "preflight_sample.json",
            "etf_readiness.csv", "trade_ledger.csv", "top_bottom_trades.csv",
            "category_strategy_summary.csv", "full_summary.json",
            "validation_report.json", "full_report.md",
        ],
    }
    _write_json(OUTPUT_DIR / "full_summary.json", summary)
    _write_json(OUTPUT_DIR / "validation_report.json", validation)
    (OUTPUT_DIR / "full_report.md").write_text(
        _render_report(summary, category_rows), encoding="utf-8"
    )
    return summary


def _write_stage_report(stage: str, reason: str, details: Mapping[str, Any]) -> None:
    body = json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    (OUTPUT_DIR / "v06_stage_report.md").write_text(
        "\n".join([
            "# V06 ETF plain-long 실행 단계 보고서",
            "",
            "- 판정: CHECK_REQUIRED",
            f"- 중단 단계: {stage}",
            f"- 사유: {reason}",
            "",
            "## 단계 정보",
            "",
            body,
            "",
            "full replay는 실행하지 않음. blocker 수정 후 자동 재실행하지 않음.",
            "",
        ]),
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if FULL_ATTEMPT_MARKER.exists():
        _write_stage_report("GUARD", "이미 full-run 시도가 기록돼 재실행을 막았어.", {
            "marker": str(FULL_ATTEMPT_MARKER),
        })
        print(json.dumps({"verdict": "CHECK_REQUIRED", "stage": "GUARD"}, ensure_ascii=False))
        return 2
    try:
        universe_frame, universe, universe_audit = _load_universe()
    except Exception as exc:
        _write_stage_report("UNIVERSE", f"{type(exc).__name__}:{str(exc)[:500]}", {})
        print(json.dumps({"verdict": "CHECK_REQUIRED", "stage": "UNIVERSE"}, ensure_ascii=False))
        return 2

    with tempfile.TemporaryDirectory(prefix="etf_plain_long_v06_") as temp_dir:
        db_path = Path(temp_dir) / "raw_etf_prices.sqlite3"
        try:
            data_info = v03._build_price_database(
                db_path, ROOT / v03.RAW_STORE_REL, universe
            )
            no_trade_audit = _audit_technical_rows(db_path, universe)
        except Exception as exc:
            _write_stage_report("RAW_DATA", f"{type(exc).__name__}:{str(exc)[:500]}", {})
            print(json.dumps({"verdict": "CHECK_REQUIRED", "stage": "RAW_DATA"}, ensure_ascii=False))
            return 2
        if no_trade_audit["other_invalid_ohlc_row_count"]:
            _write_stage_report(
                "RAW_OHLC_AUDIT",
                "정의된 NO_TRADE_SESSION 이외의 비정상 OHLC가 있어 fail-closed 처리했어.",
                no_trade_audit,
            )
            print(json.dumps({
                "verdict": "CHECK_REQUIRED",
                "stage": "RAW_OHLC_AUDIT",
                "invalid_rows": no_trade_audit["other_invalid_ohlc_row_count"],
            }, ensure_ascii=False))
            return 2

        try:
            sample = _run_sample(universe, db_path, data_info, universe_audit)
        except Exception as exc:
            sample = {
                "verdict": "CHECK_REQUIRED",
                "sample_count": 0,
                "error": f"{type(exc).__name__}:{str(exc)[:500]}",
            }
            _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
        if sample["verdict"] != "SAMPLE_PASS":
            _write_stage_report("SAMPLE", "대표 표본 검증이 통과하지 못했어.", sample)
            print(json.dumps({
                "verdict": "CHECK_REQUIRED",
                "stage": "SAMPLE",
                "sample_count": sample.get("sample_count"),
                "validation_passed": sample.get("validation", {}).get("passed"),
            }, ensure_ascii=False))
            return 2
        try:
            full = _run_full_v06(
                universe_frame, universe, db_path, data_info,
                universe_audit, no_trade_audit, workers=10,
            )
        except Exception as exc:
            _write_stage_report("FULL_RUN", f"{type(exc).__name__}:{str(exc)[:500]}", {})
            print(json.dumps({"verdict": "CHECK_REQUIRED", "stage": "FULL_RUN"}, ensure_ascii=False))
            return 2
        if full["verdict"] != "ETF_PLAIN_LONG_THREE_STRATEGY_SIMPLE_BACKTEST_V06_COMPLETE":
            _write_stage_report("FULL_RUN_VALIDATION", "full-run 검증 실패. 자동 재실행하지 않아.", full["validation"])
        print(json.dumps({
            "verdict": full["verdict"],
            "universe_count": len(universe),
            "evaluable_etf_count": full["universe"]["evaluable_etf_count"],
            "trade_counts": {
                key: value["trade_count"] for key, value in full["strategies"].items()
            },
            "runtime_seconds": full["runtime"]["wall_clock_seconds"],
            "validation_passed": full["validation"]["passed"],
        }, ensure_ascii=False))
        return 0 if full["validation"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
