#!/usr/bin/env python3
"""Run the official local-only FastCore V2/V4 matched-entry A/B replay."""

from __future__ import annotations

from array import array
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import argparse
import json
import multiprocessing as mp
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_fastcore_v3_exit_ab_v00 as diagnostic
from scripts import run_fastcore_v3_simple_v00 as v3
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data import repository_v2 as repository_v2_module
from trend_scanner.validation.pattern_a_fast_winner_hwm_exit_v01 import MFE_TIERS, mfe_tier


CONTROL_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"
V3_OFFICIAL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_v3_matched_ab_official_v01/summary.json"
V3_FAILURE_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_v3_failure_review_v01/summary.json"
V3_MATCHED_PATH = ROOT / "artifacts/backtests/fastcore_v3_matched_ab_official_v01/matched_trades.csv"
PLAN_PATH = ROOT / "docs/patterns/pattern_a_fast/validation_plan/version_04_matched_ab_validation.md"
V4_README_PATH = ROOT / "docs/patterns/pattern_a_fast/strategy/version_04/README.md"

OUT_DIR = ROOT / "artifacts/backtests/fastcore_v4_matched_ab_official_v01"
MATCHED_PATH = OUT_DIR / "matched_trades.csv"
SUMMARY_PATH = OUT_DIR / "summary.json"
ROBUSTNESS_PATH = OUT_DIR / "robustness.csv"
EXIT_REASON_PATH = OUT_DIR / "exit_reason_diagnostics.csv"
REPRESENTATIVE_PATH = OUT_DIR / "representative_cases.csv"
REPORT_PATH = OUT_DIR / "report.md"

EXPECTED_TRADES = 973
EXPECTED_UNIQUE_TICKERS = 542
EXPECTED_PERIOD = ("2021-04-01", "2026-08-14", "2026-08-21")
EXPECTED_FINAL_VALUATION = "2026-08-21 CLOSE"
WORK_ID = "FASTCORE_V4_MATCHED_AB_OFFICIAL_V01"
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V04"
EXIT_CONTRACT_ID = "TWO_PHASE_PRICE_STRUCTURE_HWM_EXIT_V01"
SUPPORT_END = pd.Timestamp("2026-08-21")
CONTEXT_START = pd.Timestamp("2018-01-01")

PRE_WINNER_BASELINE = {
    "trade_count": 236,
    "tail_le_30_count": 138,
    "tail_le_40_count": 110,
    "median_holding_days": 468.5,
    "open_at_cutoff_count": 236,
}
WINNER_TAIL_BASELINE = {
    "v2_ge_50_v3_lt_50_count": 133,
    "v2_ge_100_v3_lt_100_count": 48,
}


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _normalise_control(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str, "trade_id": str})
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    frame["isu_cd"] = frame["isu_cd"].astype(str).str.strip()
    frame["trade_id"] = frame["trade_id"].astype(str).str.strip()
    return frame


def validate_control_input(control: pd.DataFrame, control_summary: Mapping[str, Any]) -> None:
    if len(control) != EXPECTED_TRADES:
        raise AssertionError(f"expected {EXPECTED_TRADES} CONTROL rows, got {len(control)}")
    if int(control["ticker"].nunique()) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError(f"expected {EXPECTED_UNIQUE_TICKERS} CONTROL tickers, got {control['ticker'].nunique()}")
    if int(control_summary.get("total_trades", -1)) != EXPECTED_TRADES:
        raise AssertionError("CONTROL summary total_trades does not match frozen value")
    if int(control_summary.get("unique_tickers", -1)) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError("CONTROL summary unique_tickers does not match frozen value")
    period = (
        str(control_summary.get("common_start_date")),
        str(control_summary.get("signal_end_date")),
        str(control_summary.get("execution_support_end_date")),
    )
    if period != EXPECTED_PERIOD:
        raise AssertionError(f"CONTROL period does not match frozen value: {period}")
    signal_dates = pd.to_datetime(control["entry_signal_date"], errors="raise")
    execution_dates = pd.to_datetime(control["entry_execution_date"], errors="raise")
    if bool((signal_dates < pd.Timestamp(EXPECTED_PERIOD[0])).any()) or bool((signal_dates > pd.Timestamp(EXPECTED_PERIOD[1])).any()):
        raise AssertionError("CONTROL signal dates fall outside the frozen period")
    if bool((execution_dates < pd.Timestamp(EXPECTED_PERIOD[0])).any()) or bool((execution_dates > pd.Timestamp(EXPECTED_PERIOD[2])).any()):
        raise AssertionError("CONTROL execution dates fall outside the frozen support period")
    if int(control["trade_id"].duplicated().sum()) != 0:
        raise AssertionError("duplicated CONTROL trade identity")


def validate_frozen_baselines(
    control_summary: Mapping[str, Any],
    v3_summary: Mapping[str, Any],
    failure_summary: Mapping[str, Any],
) -> None:
    if str(v3_summary.get("status")) != "COMPLETE":
        raise AssertionError("existing V3 official summary is not COMPLETE")
    if str(failure_summary.get("status")) != "COMPLETE":
        raise AssertionError("existing V3 failure review is not COMPLETE")
    if int(failure_summary.get("network_requests", -1)) != 0:
        raise AssertionError("existing V3 failure review was not network-free")
    if str(v3_summary.get("evaluation_start")) != EXPECTED_PERIOD[0]:
        raise AssertionError("existing V3 official evaluation start differs")
    if str(v3_summary.get("signal_cutoff")) != EXPECTED_PERIOD[1]:
        raise AssertionError("existing V3 official signal cutoff differs")
    if str(v3_summary.get("execution_support_end")) != EXPECTED_PERIOD[2]:
        raise AssertionError("existing V3 official support end differs")
    if str(v3_summary.get("final_valuation")) != EXPECTED_FINAL_VALUATION:
        raise AssertionError("existing V3 official final valuation differs")
    integrity = v3_summary.get("integrity", {})
    if not bool(integrity.get("pass")) or int(integrity.get("matched_rows", -1)) != EXPECTED_TRADES or int(integrity.get("unique_tickers", -1)) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError("existing V3 official integrity baseline differs")
    pre = v3_summary.get("pre_winner", {}).get("v3", {})
    if {
        "trade_count": int(v3_summary.get("pre_winner", {}).get("trade_count", -1)),
        "tail_le_30_count": int(pre.get("tail_le_30_count", -1)),
        "tail_le_40_count": int(pre.get("tail_le_40_count", -1)),
        "median_holding_days": float(pre.get("median_holding_days", -1)),
        "open_at_cutoff_count": int(pre.get("open_at_cutoff_count", -1)),
    } != PRE_WINNER_BASELINE:
        raise AssertionError("existing V3 Pre-Winner baseline differs")
    cohorts = failure_summary.get("cohorts", {})
    if int(cohorts.get("PRE_WINNER_LT_20", {}).get("trade_count", -1)) != EXPECTED_PRE_WINNER_COUNT:
        raise AssertionError("existing V3 failure-review Pre-Winner cohort differs")
    if int(cohorts.get("WINNER_CAPABLE_GE_20", {}).get("trade_count", -1)) != EXPECTED_WINNER_CAPABLE_COUNT:
        raise AssertionError("existing V3 failure-review Winner-capable cohort differs")
    damage = failure_summary.get("winner_side_effect", {}).get("large_winner_damage", {})
    if int(damage.get("V2_GE_50_V3_LT_50", {}).get("trade_count", -1)) != WINNER_TAIL_BASELINE["v2_ge_50_v3_lt_50_count"]:
        raise AssertionError("existing V3 >=50 tail baseline differs")
    if int(damage.get("V2_GE_100_V3_LT_100", {}).get("trade_count", -1)) != WINNER_TAIL_BASELINE["v2_ge_100_v3_lt_100_count"]:
        raise AssertionError("existing V3 >=100 tail baseline differs")
    if int(control_summary.get("total_trades", -1)) != EXPECTED_TRADES:
        raise AssertionError("CONTROL summary changed from frozen count")


def _load_fast_daily_by_ticker(control: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compose the fixed CONTROL tickers with one local raw-store pass.

    Repository V2 remains the authority for the adjusted/raw session
    projection, but its general-purpose indexed raw reader retains every
    raw partition in memory and then performs a per-ticker selection.  The
    official CONTROL has a fixed, finite ticker set, so this runner builds a
    compact in-memory raw panel in one pass and feeds the same projection
    function.  No source files or production code are changed.
    """
    tickers = {str(value).zfill(6) for value in control["ticker"].unique()}
    raw_root = ROOT / "data/market/raw/krx_stocks/v01"
    store = KrxRawStockStore(raw_root)
    numeric_fields = ("open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares")
    physical_fields = ("date", "ticker", *numeric_fields)
    accumulators: dict[str, dict[str, array]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for day in store.list_dates(market):
            if day > EXPECTED_PERIOD[2]:
                continue
            snapshot = store.load_snapshot(market, day)
            if snapshot.empty:
                continue
            snapshot = snapshot[snapshot["ticker"].isin(tickers)]
            if snapshot.empty:
                continue
            for values in snapshot.loc[:, list(physical_fields)].itertuples(index=False, name=None):
                observed_date, raw_ticker, *numeric = values
                ticker = str(raw_ticker).zfill(6)
                accumulator = accumulators.setdefault(
                    ticker,
                    {field: array("q") if field == "date" else array("d") for field in ("date", *numeric_fields)},
                )
                accumulator["date"].append(pd.Timestamp(observed_date).value)
                for field, value in zip(numeric_fields, numeric, strict=True):
                    accumulator[field].append(float(value) if pd.notna(value) else float("nan"))
            del snapshot

    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in sorted(tickers):
        values = accumulators.get(ticker)
        if values is None:
            raise RuntimeError(f"missing local raw panel for CONTROL ticker {ticker}")
        raw = pd.DataFrame(
            {
                "date": pd.to_datetime(values["date"]),
                "open": values["open"],
                "high": values["high"],
                "low": values["low"],
                "close": values["close"],
                "volume": values["volume"],
                "trading_value": values["trading_value"],
                "market_cap": values["market_cap"],
                "listed_shares": values["listed_shares"],
            }
        ).set_index("date").sort_index()
        raw = raw.loc[raw.index >= CONTEXT_START]
        if raw.index.has_duplicates:
            raise AssertionError(f"raw cross-market ticker/date conflict for {ticker}")
        adjusted = adjusted_store.load_daily_source(
            ticker,
            CONTEXT_START.strftime("%Y-%m-%d"),
            EXPECTED_PERIOD[2],
        )
        try:
            projected_adjusted, projected_raw, audit = repository_v2_module._project_analytic_sessions(adjusted, raw)
        except Exception as exc:
            evidence = repository_v2_module._session_projection_evidence(adjusted, raw)
            if evidence["unexplained_adjusted_only_dates"] or not evidence["rejected_raw_only_dates"]:
                raise RuntimeError(
                    f"Repository V2 session composition failed for CONTROL ticker {ticker}: {exc}; "
                    f"adjusted_only={evidence['unexplained_adjusted_only_dates'][:5]} "
                    f"raw_only={evidence['rejected_raw_only_dates'][:5]} "
                    f"adjusted_rows={len(adjusted)} raw_rows={len(raw)}"
                ) from exc
            # A current local raw snapshot can contain a date for which the
            # adjusted analytic authority has no row.  Keep the adjusted
            # session set authoritative and record this explicit raw-only
            # reconciliation; never synthesize adjusted OHLC values.
            raw = raw.loc[raw.index.intersection(adjusted.index)]
            projected_adjusted, projected_raw, audit = repository_v2_module._project_analytic_sessions(adjusted, raw)
            audit["explicit_raw_only_reconciliation_count"] = len(evidence["rejected_raw_only_dates"])
            audit["explicit_raw_only_reconciliation_dates"] = evidence["rejected_raw_only_dates"]
        if projected_adjusted.empty or projected_raw.empty:
            raise RuntimeError(f"empty composed Repository V2 daily data for CONTROL ticker {ticker}")
        daily = pd.concat(
            [
                projected_adjusted.loc[:, ["open", "high", "low", "close"]],
                projected_raw.loc[:, ["volume", "trading_value"]],
            ],
            axis=1,
        ).loc[:, list(repository_v2_module.DAILY_COLUMNS)]
        repository_v2_module.validate_repository_v2_daily(daily)
        daily.attrs["session_projection_audit"] = {
            "explicit_raw_only_reconciliation_count": int(
                audit.get("explicit_raw_only_reconciliation_count", 0) or 0
            ),
            "explicit_raw_only_reconciliation_dates": list(
                audit.get("explicit_raw_only_reconciliation_dates", ())
            ),
            "projected_adjusted_rows": int(audit.get("projected_adjusted_rows", len(projected_adjusted))),
            "projected_raw_rows": int(audit.get("projected_raw_rows", len(projected_raw))),
        }
        daily_by_ticker[ticker] = daily
        del raw, adjusted, projected_adjusted, projected_raw, audit, values
    return daily_by_ticker


class _InMemoryDailyLoader:
    """Small adapter that lets the existing PIT FAST state helper be reused."""

    def __init__(self, daily_by_ticker: Mapping[str, pd.DataFrame]) -> None:
        self.daily_by_ticker = daily_by_ticker

    def load(self, ticker: str) -> pd.DataFrame | None:
        return self.daily_by_ticker.get(str(ticker).zfill(6))


_STATE_DAILY_BY_TICKER: Mapping[str, pd.DataFrame] = {}


def _state_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[dict[str, list[tuple[pd.Timestamp, str]]], int]:
    ticker, records = item
    daily = _STATE_DAILY_BY_TICKER[str(ticker)]
    subset = pd.DataFrame.from_records(records)
    states, _loaded, errors = diagnostic._state_index(
        subset,
        _InMemoryDailyLoader({str(ticker): daily}),
    )
    return states, errors


def _state_index_parallel(
    control: pd.DataFrame,
    daily_by_ticker: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, list[tuple[pd.Timestamp, str]]], int]:
    """Run the unchanged PIT FAST state helper in ticker-sized fork tasks."""
    global _STATE_DAILY_BY_TICKER
    _STATE_DAILY_BY_TICKER = daily_by_ticker
    groups = [
        (str(ticker), group.to_dict("records"))
        for ticker, group in control.groupby("ticker", sort=True)
    ]
    state_index: dict[str, list[tuple[pd.Timestamp, str]]] = {}
    error_count = 0
    context = mp.get_context("fork")
    worker_count = min(4, max(1, len(groups)))
    with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as pool:
        futures = [pool.submit(_state_worker, item) for item in groups]
        for future in as_completed(futures):
            states, errors = future.result()
            state_index.update(states)
            error_count += int(errors)
    return state_index, error_count


EXPECTED_PRE_WINNER_COUNT = 236
EXPECTED_WINNER_CAPABLE_COUNT = 737


def classify_full_path_mfe(value: float) -> str:
    return "PRE_WINNER_LT_20" if float(value) < 20.0 else "WINNER_CAPABLE_GE_20"


def _full_path_metrics(row: Mapping[str, Any], daily_full: pd.DataFrame) -> tuple[float, float, float]:
    lifecycle = diagnostic._lifecycle(row)
    daily = diagnostic.clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        raise RuntimeError(f"missing identity-scoped daily data for {row['trade_id']}")
    daily = daily.loc[daily.index <= SUPPORT_END]
    entry_date = _date(row["entry_execution_date"])
    path = daily.loc[daily.index >= entry_date]
    if path.empty:
        raise RuntimeError(f"missing post-entry daily data for {row['trade_id']}")
    highs = pd.to_numeric(path["high"], errors="coerce").dropna()
    lows = pd.to_numeric(path["low"], errors="coerce").dropna()
    if highs.empty or lows.empty:
        raise RuntimeError(f"missing post-entry HIGH/LOW data for {row['trade_id']}")
    entry_open = float(row["entry_open"])
    hwm = max(entry_open, float(highs.max()))
    trough = min(entry_open, float(lows.min()))
    return hwm, round((hwm / entry_open - 1.0) * 100.0, 6), round((trough / entry_open - 1.0) * 100.0, 6)


def _next_session(daily: pd.DataFrame, date: pd.Timestamp) -> pd.Timestamp | None:
    future = daily.loc[(daily.index > _date(date)) & (daily.index <= SUPPORT_END)]
    return _date(future.index[0]) if not future.empty else None


def _path_metrics(
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    end_date: pd.Timestamp,
    entry_open: float,
    extra_price: float | None = None,
) -> tuple[float, float, float, float]:
    held = daily.loc[(daily.index >= _date(entry_date)) & (daily.index <= _date(end_date))]
    highs = pd.to_numeric(held["high"], errors="coerce").dropna().tolist() if not held.empty else []
    lows = pd.to_numeric(held["low"], errors="coerce").dropna().tolist() if not held.empty else []
    if extra_price is not None:
        highs.append(float(extra_price))
        lows.append(float(extra_price))
    hwm = max([float(entry_open), *[float(value) for value in highs]])
    trough = min([float(entry_open), *[float(value) for value in lows]])
    mfe = round((hwm / float(entry_open) - 1.0) * 100.0, 2)
    mae = round((trough / float(entry_open) - 1.0) * 100.0, 2)
    return round(hwm, 2), round(trough, 2), mfe, mae


def v4_exit_decision(
    *,
    mfe_pct: float,
    hwm_price: float,
    current_close: float,
    entry_open: float,
    fast_state: str | None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Evaluate one completed EOD observation under the frozen V4 contract."""
    close = float(current_close)
    hwm = float(hwm_price)
    entry = float(entry_open)
    if hwm <= 0.0 or close <= 0.0 or entry <= 0.0:
        raise ValueError("price inputs must be positive")
    mfe = round(float(mfe_pct), 10)
    state = str(fast_state or "UNAVAILABLE").upper()
    if mfe < 20.0:
        entry_return = round((close / entry - 1.0) * 100.0, 10)
        if entry_return <= -15.0 and state == "WATCH":
            return "PRE_WINNER_PRICE_STRUCTURE_FAILURE", None, None, "PRE_WINNER_LT_20"
        return None, None, None, None
    tier = mfe_tier(mfe)
    if tier is None:
        raise AssertionError(f"Winner MFE has no active band: {mfe}")
    soft, hard, label = tier
    drawdown = round((close / hwm - 1.0) * 100.0, 10)
    if drawdown <= hard:
        return "WINNER_HARD_EXIT", soft, hard, label
    if drawdown <= soft and state == "WATCH":
        return "WINNER_SOFT_WATCH_EXIT", soft, hard, label
    return None, soft, hard, label


def replay_v4_entry(
    row: Mapping[str, Any],
    daily_full: pd.DataFrame,
    states: list[tuple[pd.Timestamp, str]],
) -> dict[str, Any]:
    lifecycle = diagnostic._lifecycle(row)
    daily = diagnostic.clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        raise RuntimeError(f"missing identity-scoped data for CONTROL trade {row['trade_id']}")
    daily = daily.loc[daily.index <= SUPPORT_END]
    entry_date = _date(row["entry_execution_date"])
    if entry_date not in daily.index:
        raise RuntimeError(f"CONTROL entry date unavailable for {row['trade_id']}: {entry_date.date()}")
    entry_open = float(row["entry_open"])
    observed_open = float(daily.loc[entry_date, "open"])
    if abs(observed_open - entry_open) > 1e-8:
        raise AssertionError(f"entry OPEN mismatch for {row['trade_id']}: {observed_open} != {entry_open}")

    valuation_date = _date(daily.index[-1])
    hwm = entry_open
    max_hwm_drawdown = 0.0
    exit_signal_date: pd.Timestamp | None = None
    exit_reason: str | None = None
    exit_fast_state: str | None = None
    soft_threshold: float | None = None
    hard_threshold: float | None = None
    exit_mfe_tier: str | None = None
    exit_phase: str | None = None
    unexecuted_exit_signal_date: pd.Timestamp | None = None
    unexecuted_exit_reason: str | None = None

    for date, bar in daily.loc[daily.index >= entry_date].iterrows():
        date = _date(date)
        high = float(bar["high"])
        close = float(bar["close"])
        hwm = max(hwm, high)
        mfe_pct = round((hwm / entry_open - 1.0) * 100.0, 10)
        drawdown_pct = round((close / hwm - 1.0) * 100.0, 10)
        max_hwm_drawdown = min(max_hwm_drawdown, drawdown_pct)
        fast_state = v3.latest_fast_state(states, date)
        decision, soft, hard, tier = v4_exit_decision(
            mfe_pct=mfe_pct,
            hwm_price=hwm,
            current_close=close,
            entry_open=entry_open,
            fast_state=fast_state,
        )
        if decision is not None:
            exit_signal_date = date
            exit_reason = decision
            exit_fast_state = fast_state
            soft_threshold = soft
            hard_threshold = hard
            exit_mfe_tier = tier
            exit_phase = "PRE_WINNER" if decision.startswith("PRE_WINNER") else "WINNER"
            break

    exit_execution_date: pd.Timestamp | None = None
    exit_price: float | None = None
    trade_status = "OPEN_AT_CUTOFF"
    if exit_signal_date is not None:
        exit_execution_date = _next_session(daily, exit_signal_date)
        if exit_execution_date is not None:
            exit_price = float(daily.loc[exit_execution_date, "open"])
            trade_status = "REALIZED"
        else:
            unexecuted_exit_signal_date = exit_signal_date
            unexecuted_exit_reason = exit_reason
            exit_signal_date = None
            exit_reason = None
            exit_fast_state = None
            soft_threshold = None
            hard_threshold = None
            exit_mfe_tier = None
            exit_phase = None

    if trade_status == "REALIZED" and exit_execution_date is not None and exit_price is not None:
        metric_end = exit_signal_date if exit_signal_date is not None else exit_execution_date
        hwm, _trough, mfe, mae = _path_metrics(daily, entry_date, metric_end, entry_open, exit_price)
        terminal_return = round((exit_price / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= exit_execution_date)]))
        final_valuation_date = exit_execution_date
        final_valuation_price = exit_price
    else:
        final_close = float(daily.loc[valuation_date, "close"])
        hwm, _trough, mfe, mae = _path_metrics(daily, entry_date, valuation_date, entry_open)
        terminal_return = round((final_close / entry_open - 1.0) * 100.0, 2)
        holding_days = int(len(daily.loc[(daily.index >= entry_date) & (daily.index <= valuation_date)]))
        final_valuation_date = valuation_date
        final_valuation_price = final_close
        exit_reason = "OPEN_AT_CUTOFF"

    return {
        "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
        "entry_open": entry_open,
        "exit_reason": exit_reason,
        "exit_signal_date": exit_signal_date.strftime("%Y-%m-%d") if exit_signal_date is not None else None,
        "exit_execution_date": exit_execution_date.strftime("%Y-%m-%d") if exit_execution_date is not None else None,
        "exit_price": exit_price,
        "terminal_return": terminal_return,
        "strategy_path_mfe": mfe,
        "strategy_path_mae": mae,
        "holding_days": holding_days,
        "trade_status": trade_status,
        "hwm_price": hwm,
        "max_hwm_drawdown_pct": round(max_hwm_drawdown, 2),
        "fast_state_at_exit": exit_fast_state,
        "active_soft_threshold": soft_threshold,
        "active_hard_threshold": hard_threshold,
        "mfe_tier": exit_mfe_tier,
        "phase_at_exit": exit_phase,
        "final_valuation_date": final_valuation_date.strftime("%Y-%m-%d"),
        "final_valuation_price": round(final_valuation_price, 2),
        "unexecuted_exit_signal_date": unexecuted_exit_signal_date.strftime("%Y-%m-%d") if unexecuted_exit_signal_date is not None else None,
        "unexecuted_exit_reason": unexecuted_exit_reason,
    }


def _v2_exit_category(row: Mapping[str, Any]) -> str:
    if str(row.get("trade_status", "")) == "OPEN_AT_CUTOFF":
        return "OPEN_AT_CUTOFF"
    exit_type = str(row.get("exit_type", ""))
    if exit_type.startswith("LOSS_GUARD"):
        return "LOSS_GUARD"
    if exit_type.startswith("EXIT3"):
        return "EXIT3"
    if exit_type.startswith("EXIT4"):
        return "EXIT4"
    if exit_type.startswith("NO_"):
        return "OPEN_AT_CUTOFF"
    return exit_type


def _load_v3_reference() -> pd.DataFrame:
    if not V3_MATCHED_PATH.exists():
        raise AssertionError("existing V3 official matched artifact is missing")
    frame = pd.read_csv(V3_MATCHED_PATH, dtype={"control_trade_id": str, "ticker": str})
    if len(frame) != EXPECTED_TRADES or int(frame["control_trade_id"].nunique()) != EXPECTED_TRADES:
        raise AssertionError("existing V3 official matched artifact identity count differs")
    required = {"control_trade_id", "v3_exit_reason", "v3_terminal_return", "v3_strategy_path_mfe", "v3_giveback"}
    if not required.issubset(frame.columns):
        raise AssertionError("existing V3 official matched artifact lacks required reference columns")
    return frame[["control_trade_id", "v3_exit_reason", "v3_terminal_return", "v3_strategy_path_mfe", "v3_giveback"]].copy()


def build_matched(
    control: pd.DataFrame,
    daily_by_ticker: Mapping[str, pd.DataFrame],
    states: Mapping[str, list[tuple[pd.Timestamp, str]]],
    v3_reference: pd.DataFrame,
) -> pd.DataFrame:
    v3_by_id = v3_reference.set_index("control_trade_id")
    rows: list[dict[str, Any]] = []
    ordered = control.sort_values(["ticker", "entry_signal_date", "trade_sequence", "trade_id"], kind="mergesort")
    for row in ordered.to_dict("records"):
        control_id = str(row["trade_id"])
        if control_id not in v3_by_id.index:
            raise AssertionError(f"missing V3 reference row for {control_id}")
        v4 = replay_v4_entry(row, daily_by_ticker[str(row["ticker"])], states.get(diagnostic._identity_key(row), []))
        _hwm, full_path_mfe, full_path_mae = _full_path_metrics(row, daily_by_ticker[str(row["ticker"])])
        v3_row = v3_by_id.loc[control_id]
        v2_return = float(row["terminal_return"])
        v4_return = float(v4["terminal_return"])
        delta = round(v4_return - v2_return, 6)
        rows.append({
            "ticker": str(row["ticker"]),
            "name": str(row["name"]),
            "market": str(row["market"]),
            "isu_cd": str(row["isu_cd"]),
            "control_trade_id": control_id,
            "control_trade_sequence": int(row["trade_sequence"]),
            "identity_lifecycle": f"{row['identity_effective_from']}|{row['identity_effective_to']}",
            "identity_effective_from": str(row["identity_effective_from"]),
            "identity_effective_to": str(row["identity_effective_to"]),
            "entry_signal_date": str(row["entry_signal_date"]),
            "entry_execution_date": str(row["entry_execution_date"]),
            "entry_open": float(row["entry_open"]),
            "full_path_raw_mfe": full_path_mfe,
            "full_path_raw_mae": full_path_mae,
            "full_path_mfe_cohort": classify_full_path_mfe(full_path_mfe),
            "v2_exit_reason": str(row["exit_type"]),
            "v2_exit_category": _v2_exit_category(row),
            "v2_exit_signal_date": row["exit_signal_date"] if pd.notna(row["exit_signal_date"]) else None,
            "v2_exit_execution_date": row["exit_execution_date"] if pd.notna(row["exit_execution_date"]) else None,
            "v2_exit_price": float(row["exit_price"]) if pd.notna(row["exit_price"]) else None,
            "v2_terminal_return": v2_return,
            "v2_mfe": float(row["mfe"]),
            "v2_mae": float(row["mae"]),
            "v2_holding_days": int(row["holding_trading_days"]),
            "v2_trade_status": str(row["trade_status"]),
            "v2_giveback": round(float(row["mfe"]) - v2_return, 6),
            "v4_exit_reason": v4["exit_reason"],
            "v4_exit_signal_date": v4["exit_signal_date"],
            "v4_exit_execution_date": v4["exit_execution_date"],
            "v4_exit_price": v4["exit_price"],
            "v4_terminal_return": v4_return,
            "v4_strategy_path_mfe": v4["strategy_path_mfe"],
            "v4_strategy_path_mae": v4["strategy_path_mae"],
            "v4_holding_days": v4["holding_days"],
            "v4_trade_status": v4["trade_status"],
            "v4_fast_state_at_exit": v4["fast_state_at_exit"],
            "v4_active_soft_threshold": v4["active_soft_threshold"],
            "v4_active_hard_threshold": v4["active_hard_threshold"],
            "v4_mfe_tier": v4["mfe_tier"],
            "v4_phase_at_exit": v4["phase_at_exit"],
            "v4_max_hwm_drawdown_pct": v4["max_hwm_drawdown_pct"],
            "v4_final_valuation_date": v4["final_valuation_date"],
            "v4_final_valuation_price": v4["final_valuation_price"],
            "v4_unexecuted_exit_signal_date": v4["unexecuted_exit_signal_date"],
            "v4_unexecuted_exit_reason": v4["unexecuted_exit_reason"],
            "v4_giveback": round(float(v4["strategy_path_mfe"]) - v4_return, 6),
            "v3_exit_reason": str(v3_row["v3_exit_reason"]),
            "v3_terminal_return": float(v3_row["v3_terminal_return"]),
            "v3_strategy_path_mfe": float(v3_row["v3_strategy_path_mfe"]),
            "v3_giveback": float(v3_row["v3_giveback"]),
            "entry_signal_date_match": True,
            "entry_execution_date_match": str(row["entry_execution_date"]) == str(v4["entry_execution_date"]),
            "entry_open_match": abs(float(row["entry_open"]) - float(v4["entry_open"])) <= 1e-8,
            "return_delta_v4_minus_v2": delta,
            "improved_worsened_same": "improved" if delta > 0 else "worsened" if delta < 0 else "same",
        })
    return pd.DataFrame(rows).reset_index(drop=True)


def validate_matched_integrity(matched: pd.DataFrame) -> dict[str, Any]:
    if len(matched) != EXPECTED_TRADES:
        raise AssertionError(f"matched rows != {EXPECTED_TRADES}: {len(matched)}")
    duplicated = int(matched["control_trade_id"].duplicated().sum())
    if duplicated != 0:
        raise AssertionError("duplicated matched CONTROL trade identity")
    signal_matches = int(matched["entry_signal_date_match"].sum())
    execution_matches = int(matched["entry_execution_date_match"].sum())
    open_matches = int(matched["entry_open_match"].sum())
    if signal_matches != EXPECTED_TRADES or execution_matches != EXPECTED_TRADES or open_matches != EXPECTED_TRADES:
        raise AssertionError("matched entry identity mismatch")
    execution_dates = pd.to_datetime(matched["v4_exit_execution_date"].dropna(), errors="raise")
    if bool((execution_dates > SUPPORT_END).any()):
        raise AssertionError("V4 execution exceeds fixed support end")
    if int(matched["ticker"].nunique()) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError("matched unique ticker count differs")
    return {
        "matched_rows": EXPECTED_TRADES,
        "unique_tickers": EXPECTED_UNIQUE_TICKERS,
        "entry_signal_date_match_count": signal_matches,
        "entry_execution_date_match_count": execution_matches,
        "entry_open_match_count": open_matches,
        "missing_entries": 0,
        "duplicated_control_trade_identity": duplicated,
        "arbitrary_excluded_entries": 0,
        "common_cutoff": EXPECTED_PERIOD[2],
        "future_data_or_lookahead": False,
        "pass": True,
    }


def _mean_median(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _side_stats(frame: pd.DataFrame, side: str) -> dict[str, Any]:
    return_col = f"{side}_terminal_return"
    mfe_col = "v2_mfe" if side == "v2" else "v4_strategy_path_mfe"
    mae_col = "v2_mae" if side == "v2" else "v4_strategy_path_mae"
    holding_col = f"{side}_holding_days"
    status_col = f"{side}_trade_status"
    giveback_col = f"{side}_giveback"
    returns = pd.to_numeric(frame[return_col], errors="coerce")
    mean_return, median_return = _mean_median(frame, return_col)
    mean_mfe, median_mfe = _mean_median(frame, mfe_col)
    mean_mae, median_mae = _mean_median(frame, mae_col)
    mean_holding, median_holding = _mean_median(frame, holding_col)
    mean_giveback, median_giveback = _mean_median(frame, giveback_col)
    total = len(frame)
    open_count = int((frame[status_col] == "OPEN_AT_CUTOFF").sum())
    result: dict[str, Any] = {
        "trades": total,
        "positive_count": int((returns > 0).sum()),
        "positive_rate_pct": round(float((returns > 0).mean() * 100.0), 6) if total else None,
        "mean_terminal_return_pct": mean_return,
        "median_terminal_return_pct": median_return,
        "mean_mfe_pct": mean_mfe,
        "median_mfe_pct": median_mfe,
        "mean_mae_pct": mean_mae,
        "median_mae_pct": median_mae,
        "mean_holding_days": mean_holding,
        "median_holding_days": median_holding,
        "p90_holding_days": round(float(pd.to_numeric(frame[holding_col], errors="coerce").quantile(0.9)), 6) if total else None,
        "open_at_cutoff_count": open_count,
        "open_at_cutoff_rate_pct": round(open_count / total * 100.0, 6) if total else None,
        "mean_giveback": mean_giveback,
        "median_giveback": median_giveback,
    }
    for threshold in (15, 20, 30, 40, 50, 60):
        count = int((returns <= -threshold).sum())
        result[f"tail_le_{threshold}_count"] = count
        result[f"tail_le_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else None
    for threshold in (20, 30, 50, 100, 200, 400):
        count = int((returns >= threshold).sum())
        result[f"winner_ge_{threshold}_count"] = count
        result[f"winner_ge_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else None
    return result


def build_robustness(matched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(dimension: str, group: str, frame: pd.DataFrame) -> None:
        mean_delta, median_delta = _mean_median(frame, "return_delta_v4_minus_v2")
        rows.append({
            "dimension": dimension,
            "group": group,
            "trade_count": len(frame),
            "mean_paired_v4_minus_v2_delta": mean_delta,
            "median_paired_v4_minus_v2_delta": median_delta,
        })

    for group in ("KOSPI", "KOSDAQ"):
        add("market", group, matched[matched["market"] == group])
    add("entry_type", "FIRST_ENTRY", matched[matched["control_trade_sequence"] == 1])
    add("entry_type", "REENTRY", matched[matched["control_trade_sequence"] > 1])
    years = pd.to_datetime(matched["entry_execution_date"], errors="raise").dt.year
    for year in sorted(years.unique()):
        add("entry_year", str(int(year)), matched[years == year])
    return pd.DataFrame(rows)


def _robustness_mean(robustness: pd.DataFrame, dimension: str, group: str) -> float | None:
    rows = robustness[(robustness["dimension"] == dimension) & (robustness["group"] == group)]
    if rows.empty or pd.isna(rows.iloc[0]["mean_paired_v4_minus_v2_delta"]):
        return None
    return float(rows.iloc[0]["mean_paired_v4_minus_v2_delta"])


def evaluate_repair_gates(matched: pd.DataFrame, v3_summary: Mapping[str, Any]) -> dict[str, Any]:
    pre = matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"]
    winner = matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"]
    if len(pre) != EXPECTED_PRE_WINNER_COUNT or len(winner) != EXPECTED_WINNER_CAPABLE_COUNT:
        raise AssertionError("full-path cohort counts differ from frozen 236/737")
    v3_pre = v3_summary["pre_winner"]["v3"]
    v4_pre = _side_stats(pre, "v4")
    pre_checks = {
        "tail_le_30_rate_lt_v3": bool(v4_pre["tail_le_30_rate_pct"] < v3_pre["tail_le_30_rate_pct"]),
        "tail_le_40_rate_lt_v3": bool(v4_pre["tail_le_40_rate_pct"] < v3_pre["tail_le_40_rate_pct"]),
        "median_holding_lt_v3": bool(v4_pre["median_holding_days"] < v3_pre["median_holding_days"]),
        "open_at_cutoff_rate_lt_v3": bool(v4_pre["open_at_cutoff_rate_pct"] < v3_pre["open_at_cutoff_rate_pct"]),
    }
    pre_gate = {
        "cohort_trade_count": len(pre),
        "v3_baseline": {
            "tail_le_30_count": PRE_WINNER_BASELINE["tail_le_30_count"],
            "tail_le_30_rate_pct": round(PRE_WINNER_BASELINE["tail_le_30_count"] / EXPECTED_PRE_WINNER_COUNT * 100.0, 6),
            "tail_le_40_count": PRE_WINNER_BASELINE["tail_le_40_count"],
            "tail_le_40_rate_pct": round(PRE_WINNER_BASELINE["tail_le_40_count"] / EXPECTED_PRE_WINNER_COUNT * 100.0, 6),
            "median_holding_days": PRE_WINNER_BASELINE["median_holding_days"],
            "open_at_cutoff_count": PRE_WINNER_BASELINE["open_at_cutoff_count"],
            "open_at_cutoff_rate_pct": 100.0,
        },
        "v4": v4_pre,
        "checks": pre_checks,
        "pass": bool(all(pre_checks.values())),
        "decision": "PRE_WINNER_REPAIR_PASS" if all(pre_checks.values()) else "PRE_WINNER_REPAIR_FAIL",
    }

    damage_50 = winner[(winner["v2_terminal_return"] >= 50.0) & (winner["v4_terminal_return"] < 50.0)]
    damage_100 = winner[(winner["v2_terminal_return"] >= 100.0) & (winner["v4_terminal_return"] < 100.0)]
    winner_gate = {
        "cohort_trade_count": len(winner),
        "v3_baseline": dict(WINNER_TAIL_BASELINE),
        "v4_damage": {
            "v2_ge_50_v4_lt_50_count": len(damage_50),
            "v2_ge_100_v4_lt_100_count": len(damage_100),
            "v2_ge_50_v4_lt_50_soft_count": int((damage_50["v4_exit_reason"] == "WINNER_SOFT_WATCH_EXIT").sum()),
            "v2_ge_50_v4_lt_50_hard_count": int((damage_50["v4_exit_reason"] == "WINNER_HARD_EXIT").sum()),
            "v2_ge_100_v4_lt_100_soft_count": int((damage_100["v4_exit_reason"] == "WINNER_SOFT_WATCH_EXIT").sum()),
            "v2_ge_100_v4_lt_100_hard_count": int((damage_100["v4_exit_reason"] == "WINNER_HARD_EXIT").sum()),
        },
        "checks": {
            "v2_ge_50_v4_lt_50_lt_133": bool(len(damage_50) < WINNER_TAIL_BASELINE["v2_ge_50_v3_lt_50_count"]),
            "v2_ge_100_v4_lt_100_lt_48": bool(len(damage_100) < WINNER_TAIL_BASELINE["v2_ge_100_v3_lt_100_count"]),
        },
    }
    winner_gate["pass"] = bool(all(winner_gate["checks"].values()))
    winner_gate["decision"] = "WINNER_TAIL_REPAIR_PASS" if winner_gate["pass"] else "WINNER_TAIL_REPAIR_FAIL"
    return {"pre_winner_repair": pre_gate, "winner_tail_repair": winner_gate}


def evaluate_preregistered_criteria(
    v2: Mapping[str, Any],
    v4: Mapping[str, Any],
    paired: Mapping[str, Any],
    robustness: pd.DataFrame,
    integrity_pass: bool,
    repair_gates: Mapping[str, Any],
) -> dict[str, Any]:
    path_a = bool(paired["mean_delta"] > 0 and paired["median_delta"] >= 0)
    path_b = bool(v4["winner_ge_50_count"] > v2["winner_ge_50_count"] and v4["winner_ge_100_count"] >= v2["winner_ge_100_count"])
    path_c = bool(v4["median_giveback"] < v2["median_giveback"] and v4["mean_giveback"] <= v2["mean_giveback"])
    performance_pass = bool(path_a or path_b or path_c)
    large_loss_worsened = bool(v4["tail_le_30_rate_pct"] > v2["tail_le_30_rate_pct"] and v4["tail_le_40_rate_pct"] > v2["tail_le_40_rate_pct"])
    capital_lock_worsened = bool(v4["median_holding_days"] > v2["median_holding_days"] and v4["open_at_cutoff_rate_pct"] > v2["open_at_cutoff_rate_pct"])
    risk_block = bool(large_loss_worsened and capital_lock_worsened)
    market_pass = bool(
        _robustness_mean(robustness, "market", "KOSPI") is not None
        and _robustness_mean(robustness, "market", "KOSPI") >= 0
        and _robustness_mean(robustness, "market", "KOSDAQ") is not None
        and _robustness_mean(robustness, "market", "KOSDAQ") >= 0
    )
    entry_type_pass = bool(
        _robustness_mean(robustness, "entry_type", "FIRST_ENTRY") is not None
        and _robustness_mean(robustness, "entry_type", "FIRST_ENTRY") >= 0
        and _robustness_mean(robustness, "entry_type", "REENTRY") is not None
        and _robustness_mean(robustness, "entry_type", "REENTRY") >= 0
    )
    year_rows = robustness[robustness["dimension"] == "entry_year"]
    year_means = pd.to_numeric(year_rows["mean_paired_v4_minus_v2_delta"], errors="coerce").dropna()
    year_pass = bool(not year_means.empty and int((year_means >= 0).sum()) >= len(year_means) / 2)
    official_eligible = bool(
        integrity_pass
        and repair_gates["pre_winner_repair"]["pass"]
        and repair_gates["winner_tail_repair"]["pass"]
        and performance_pass
        and not risk_block
    )
    default_criteria = {
        "criterion_1_mean_return_ge_v2": bool(v4["mean_terminal_return_pct"] >= v2["mean_terminal_return_pct"]),
        "criterion_2_median_return_ge_v2": bool(v4["median_terminal_return_pct"] >= v2["median_terminal_return_pct"]),
        "criterion_3_tail_le_30_rate_le_v2": bool(v4["tail_le_30_rate_pct"] <= v2["tail_le_30_rate_pct"]),
        "criterion_4_tail_le_40_rate_le_v2": bool(v4["tail_le_40_rate_pct"] <= v2["tail_le_40_rate_pct"]),
        "criterion_5_winner_or_giveback_improved": bool(path_b or path_c),
        "criterion_6_median_holding_le_v2": bool(v4["median_holding_days"] <= v2["median_holding_days"]),
        "criterion_7_open_at_cutoff_rate_le_v2": bool(v4["open_at_cutoff_rate_pct"] <= v2["open_at_cutoff_rate_pct"]),
        "criterion_8_robustness": bool(market_pass and entry_type_pass and year_pass),
        "criterion_9_pre_winner_repair": bool(repair_gates["pre_winner_repair"]["pass"]),
        "criterion_10_winner_tail_repair": bool(repair_gates["winner_tail_repair"]["pass"]),
    }
    default_eligible = bool(official_eligible and all(default_criteria.values()))
    return {
        "path_a_return_improvement": {"pass": path_a, "mean_delta_gt_zero": bool(paired["mean_delta"] > 0), "median_delta_ge_zero": bool(paired["median_delta"] >= 0)},
        "path_b_winner_preservation": {"pass": path_b, "v4_ge_50_gt_v2": bool(v4["winner_ge_50_count"] > v2["winner_ge_50_count"]), "v4_ge_100_ge_v2": bool(v4["winner_ge_100_count"] >= v2["winner_ge_100_count"])},
        "path_c_giveback_improvement": {"pass": path_c, "v4_median_giveback_lt_v2": bool(v4["median_giveback"] < v2["median_giveback"]), "v4_mean_giveback_le_v2": bool(v4["mean_giveback"] <= v2["mean_giveback"])},
        "performance_improvement_pass": performance_pass,
        "large_loss_area_worsened": large_loss_worsened,
        "capital_lock_area_worsened": capital_lock_worsened,
        "official_adoption_risk_block": risk_block,
        "official_adoption_eligible": official_eligible,
        "default_promotion_robustness": {"market": market_pass, "entry_type": entry_type_pass, "entry_year": year_pass},
        "default_promotion_criteria": default_criteria,
        "default_promotion_eligible": default_eligible,
    }


REPRESENTATIVE_FIELDS = [
    "ticker", "name", "market", "isu_cd", "control_trade_id", "control_trade_sequence", "entry_signal_date", "entry_execution_date", "entry_open",
    "full_path_raw_mfe", "full_path_mfe_cohort", "v2_exit_category", "v2_terminal_return", "v2_mfe", "v2_mae", "v2_holding_days", "v2_giveback",
    "v3_exit_reason", "v3_terminal_return", "v4_exit_reason", "v4_terminal_return", "v4_strategy_path_mfe", "v4_strategy_path_mae", "v4_holding_days", "v4_giveback",
    "return_delta_v4_minus_v2",
]


def _representative_row(case_type: str, rank: int, row: Mapping[str, Any]) -> dict[str, Any]:
    return {"case_type": case_type, "rank": rank, **{field: row.get(field) for field in REPRESENTATIVE_FIELDS}}


def build_representative_cases(matched: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    cases: list[dict[str, Any]] = []

    def add(case_type: str, frame: pd.DataFrame, sort_columns: list[str], ascending: list[bool]) -> None:
        if frame.empty:
            return
        ordered = frame.sort_values(sort_columns + ["ticker", "entry_execution_date", "control_trade_id"], ascending=ascending + [True, True, True], kind="mergesort").head(limit)
        cases.extend(_representative_row(case_type, rank, row) for rank, row in enumerate(ordered.to_dict("records"), start=1))

    pre = matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"]
    winner = matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"]
    add("PRE_WINNER_EXIT_REDUCED_LARGE_LOSS", pre[pre["v4_exit_reason"] == "PRE_WINNER_PRICE_STRUCTURE_FAILURE"], ["return_delta_v4_minus_v2"], [False])
    add("PRE_WINNER_EXIT_AFTER_FULL_PATH_WINNER", winner[winner["v4_exit_reason"] == "PRE_WINNER_PRICE_STRUCTURE_FAILURE"], ["return_delta_v4_minus_v2"], [True])
    add("PRE_WINNER_V4_STILL_LARGE_LOSS", pre, ["v4_terminal_return"], [True])
    add("V4_TAIL_PRESERVATION_VS_V3", winner[winner["v4_terminal_return"] > winner["v3_terminal_return"]], ["return_delta_v4_minus_v2"], [False])
    add("V4_SOFT_STILL_DAMAGES_WINNER", matched[(matched["v4_exit_reason"] == "WINNER_SOFT_WATCH_EXIT") & (matched["v2_terminal_return"] >= 50) & (matched["v4_terminal_return"] < 50)], ["return_delta_v4_minus_v2"], [True])
    add("V4_HARD_DAMAGES_WINNER", matched[(matched["v4_exit_reason"] == "WINNER_HARD_EXIT") & (matched["v2_terminal_return"] >= 50) & (matched["v4_terminal_return"] < 50)], ["return_delta_v4_minus_v2"], [True])
    add("PAIRED_DELTA_LOWEST", matched, ["return_delta_v4_minus_v2"], [True])
    add("PAIRED_DELTA_HIGHEST", matched, ["return_delta_v4_minus_v2"], [False])
    if not cases:
        return pd.DataFrame(columns=["case_type", "rank", *REPRESENTATIVE_FIELDS])
    return pd.DataFrame(cases)


def build_exit_reason_diagnostics(matched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    definitions = [
        ("V2", "LOSS_GUARD", "v2_exit_category"),
        ("V2", "EXIT3", "v2_exit_category"),
        ("V2", "EXIT4", "v2_exit_category"),
        ("V2", "OPEN_AT_CUTOFF", "v2_exit_category"),
        ("V4", "PRE_WINNER_PRICE_STRUCTURE_FAILURE", "v4_exit_reason"),
        ("V4", "WINNER_SOFT_WATCH_EXIT", "v4_exit_reason"),
        ("V4", "WINNER_HARD_EXIT", "v4_exit_reason"),
        ("V4", "OPEN_AT_CUTOFF", "v4_exit_reason"),
    ]
    for strategy, reason, column in definitions:
        frame = matched[matched[column] == reason]
        side = strategy.lower()
        stats = _side_stats(frame, side)
        rows.append({
            "strategy": strategy,
            "exit_reason": reason,
            "count": stats["trades"],
            "rate_pct": round(stats["trades"] / len(matched) * 100.0, 6),
            "mean_terminal_return": stats["mean_terminal_return_pct"],
            "median_terminal_return": stats["median_terminal_return_pct"],
            "mean_mfe": stats["mean_mfe_pct"],
            "median_mfe": stats["median_mfe_pct"],
            "mean_mae": stats["mean_mae_pct"],
            "median_mae": stats["median_mae_pct"],
            "mean_holding_days": stats["mean_holding_days"],
            "median_holding_days": stats["median_holding_days"],
            "mean_giveback": stats["mean_giveback"],
            "median_giveback": stats["median_giveback"],
        })
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        cells = ["" if value is None or pd.isna(value) else str(value) for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _build_report(summary: Mapping[str, Any], exit_reason: pd.DataFrame) -> str:
    v2 = summary["strategies"]["v2"]
    v4 = summary["strategies"]["v4"]
    paired = summary["paired"]
    decision = summary["preregistered_decision"]
    pre = summary["repair_gates"]["pre_winner_repair"]
    winner = summary["repair_gates"]["winner_tail_repair"]
    lines = [
        "# FastCore V4 공식 동일 진입 matched A/B 결과",
        "",
        "## 실행 상태",
        "",
        f"- 상태: `{summary['status']}`",
        f"- 기간: `{summary['evaluation_start']}` ~ `{summary['execution_support_end']}` 지원, signal cutoff `{summary['signal_cutoff']}`, 최종 평가 `{summary['final_valuation']}`",
        f"- matched 거래: `{summary['integrity']['matched_rows']}` / 고유 종목: `{summary['integrity']['unique_tickers']}`",
        f"- entry signal / execution / open 일치: `{summary['integrity']['entry_signal_date_match_count']}` / `{summary['integrity']['entry_execution_date_match_count']}` / `{summary['integrity']['entry_open_match_count']}`",
        f"- 네트워크 요청: `{summary['network_requests']}`",
        f"- adjusted analytic authority에 없는 raw-only 행 명시적 제외: `{summary['local_session_reconciliation']['raw_only_rows_explicitly_excluded']}`",
        "",
        "## V2 / V4 핵심 지표",
        "",
        "| 지표 | V2 | V4 |",
        "|---|---:|---:|",
        f"| mean terminal return | {v2['mean_terminal_return_pct']} | {v4['mean_terminal_return_pct']} |",
        f"| median terminal return | {v2['median_terminal_return_pct']} | {v4['median_terminal_return_pct']} |",
        f"| positive rate | {v2['positive_rate_pct']}% | {v4['positive_rate_pct']}% |",
        f"| mean MAE | {v2['mean_mae_pct']} | {v4['mean_mae_pct']} |",
        f"| median MAE | {v2['median_mae_pct']} | {v4['median_mae_pct']} |",
        f"| median holding | {v2['median_holding_days']} | {v4['median_holding_days']} |",
        f"| P90 holding | {v2['p90_holding_days']} | {v4['p90_holding_days']} |",
        f"| OPEN_AT_CUTOFF | {v2['open_at_cutoff_count']} ({v2['open_at_cutoff_rate_pct']}%) | {v4['open_at_cutoff_count']} ({v4['open_at_cutoff_rate_pct']}%) |",
        f"| <= -30% | {v2['tail_le_30_count']} ({v2['tail_le_30_rate_pct']}%) | {v4['tail_le_30_count']} ({v4['tail_le_30_rate_pct']}%) |",
        f"| <= -40% | {v2['tail_le_40_count']} ({v2['tail_le_40_rate_pct']}%) | {v4['tail_le_40_count']} ({v4['tail_le_40_rate_pct']}%) |",
        f"| >= +50% | {v2['winner_ge_50_count']} | {v4['winner_ge_50_count']} |",
        f"| >= +100% | {v2['winner_ge_100_count']} | {v4['winner_ge_100_count']} |",
        f"| mean giveback | {v2['mean_giveback']} | {v4['mean_giveback']} |",
        f"| median giveback | {v2['median_giveback']} | {v4['median_giveback']} |",
        "",
        "## Paired 결과",
        "",
        f"- mean V4 - V2 delta: `{paired['mean_delta']}`",
        f"- median V4 - V2 delta: `{paired['median_delta']}`",
        f"- improved / worsened / same: `{paired['improved_count']} / {paired['worsened_count']} / {paired['same_count']}`",
        "",
        "## Repair Gate",
        "",
        f"- Pre-Winner: `{pre['decision']}`; checks={pre['checks']}",
        f"- Winner Tail: `{winner['decision']}`; checks={winner['checks']}",
        "",
        "## 사전등록 판정",
        "",
        f"- Path A / B / C: `{decision['path_a_return_improvement']['pass']}` / `{decision['path_b_winner_preservation']['pass']}` / `{decision['path_c_giveback_improvement']['pass']}`",
        f"- large-loss worsened: `{decision['large_loss_area_worsened']}`",
        f"- capital-lock worsened: `{decision['capital_lock_area_worsened']}`",
        f"- Risk Block: `{decision['official_adoption_risk_block']}`",
        f"- OFFICIAL_ADOPTION_ELIGIBLE: `{decision['official_adoption_eligible']}`",
        f"- default promotion eligibility: `{decision['default_promotion_eligible']}`",
        "",
        "## 청산 이유",
        "",
        _markdown_table(exit_reason),
        "",
        "## MDD와 한계",
        "",
        "- MDD: `NOT_EVALUATED` — 고정 trade replay에 확정된 공통 포트폴리오 구성 규칙이 없어 새 모델을 만들지 않음",
        "- V3는 기존 공식 결과를 Repair 기준선과 대표 사례 비교용으로만 읽었으며 재실행하지 않음",
        "- 이 결과는 V4의 기계적 자격 판정이며, 공식 채택·기본 전략 승격 결정이 아님",
        "",
    ]
    return "\n".join(lines)


def run_official() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    control = _normalise_control(CONTROL_TRADES_PATH)
    control_summary = _json_read(CONTROL_SUMMARY_PATH)
    v3_summary = _json_read(V3_OFFICIAL_SUMMARY_PATH)
    failure_summary = _json_read(V3_FAILURE_SUMMARY_PATH)
    validate_control_input(control, control_summary)
    validate_frozen_baselines(control_summary, v3_summary, failure_summary)
    if not PLAN_PATH.exists() or not V4_README_PATH.exists():
        raise AssertionError("required V4 validation plan or README is missing")

    v3_reference = _load_v3_reference()
    daily_by_ticker = _load_fast_daily_by_ticker(control)
    raw_only_reconciliation_count = sum(
        int(frame.attrs.get("session_projection_audit", {}).get("explicit_raw_only_reconciliation_count", 0) or 0)
        for frame in daily_by_ticker.values()
    )
    states, state_errors = _state_index_parallel(control, daily_by_ticker)
    if state_errors != 0:
        raise AssertionError(f"weekly FAST state evaluation errors: {state_errors}")
    matched = build_matched(control, daily_by_ticker, states, v3_reference)
    integrity = validate_matched_integrity(matched)
    cohort_counts = matched["full_path_mfe_cohort"].value_counts().to_dict()
    if int(cohort_counts.get("PRE_WINNER_LT_20", 0)) != EXPECTED_PRE_WINNER_COUNT or int(cohort_counts.get("WINNER_CAPABLE_GE_20", 0)) != EXPECTED_WINNER_CAPABLE_COUNT:
        raise AssertionError(f"full-path cohort counts differ: {cohort_counts}")

    v2_stats = _side_stats(matched, "v2")
    v4_stats = _side_stats(matched, "v4")
    delta_mean, delta_median = _mean_median(matched, "return_delta_v4_minus_v2")
    paired = {
        "mean_delta": delta_mean,
        "median_delta": delta_median,
        "improved_count": int((matched["improved_worsened_same"] == "improved").sum()),
        "worsened_count": int((matched["improved_worsened_same"] == "worsened").sum()),
        "same_count": int((matched["improved_worsened_same"] == "same").sum()),
    }
    paired["improved_rate_pct"] = round(paired["improved_count"] / EXPECTED_TRADES * 100.0, 6)
    paired["worsened_rate_pct"] = round(paired["worsened_count"] / EXPECTED_TRADES * 100.0, 6)
    paired["same_rate_pct"] = round(paired["same_count"] / EXPECTED_TRADES * 100.0, 6)
    robustness = build_robustness(matched)
    repair_gates = evaluate_repair_gates(matched, v3_summary)
    decisions = evaluate_preregistered_criteria(v2_stats, v4_stats, paired, robustness, integrity["pass"], repair_gates)
    exit_reason = build_exit_reason_diagnostics(matched)
    representative = build_representative_cases(matched)
    summary: dict[str, Any] = {
        "work_id": WORK_ID,
        "status": "COMPLETE",
        "strategy_ids": {"control": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "candidate": STRATEGY_ID},
        "exit_contract": EXIT_CONTRACT_ID,
        "period": {
            "evaluation_start": EXPECTED_PERIOD[0],
            "signal_cutoff": EXPECTED_PERIOD[1],
            "execution_support_end": EXPECTED_PERIOD[2],
            "final_valuation": EXPECTED_FINAL_VALUATION,
        },
        "evaluation_start": EXPECTED_PERIOD[0],
        "signal_cutoff": EXPECTED_PERIOD[1],
        "execution_support_end": EXPECTED_PERIOD[2],
        "final_valuation": EXPECTED_FINAL_VALUATION,
        "control_trade_count": EXPECTED_TRADES,
        "control_unique_tickers": EXPECTED_UNIQUE_TICKERS,
        "integrity": integrity,
        "network_requests": 0,
        "local_session_reconciliation": {
            "raw_only_rows_explicitly_excluded": raw_only_reconciliation_count,
            "basis": "adjusted analytic authority date set; no adjusted OHLC synthesized",
        },
        "v2": v2_stats,
        "v4": v4_stats,
        "strategies": {"v2": v2_stats, "v4": v4_stats},
        "paired": paired,
        "pre_winner": {
            "definition": "full_path_raw_mfe < +20%",
            "trade_count": EXPECTED_PRE_WINNER_COUNT,
            "trade_rate_pct": round(EXPECTED_PRE_WINNER_COUNT / EXPECTED_TRADES * 100.0, 6),
            "v2": _side_stats(matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"], "v2"),
            "v4": _side_stats(matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"], "v4"),
        },
        "winner_capable": {
            "definition": "full_path_raw_mfe >= +20%",
            "trade_count": EXPECTED_WINNER_CAPABLE_COUNT,
            "trade_rate_pct": round(EXPECTED_WINNER_CAPABLE_COUNT / EXPECTED_TRADES * 100.0, 6),
            "v2": _side_stats(matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"], "v2"),
            "v4": _side_stats(matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"], "v4"),
        },
        "exit_reason_summary": exit_reason.to_dict(orient="records"),
        "repair_gates": repair_gates,
        "preregistered_decision": decisions,
        "OFFICIAL_ADOPTION_ELIGIBLE": decisions["official_adoption_eligible"],
        "default_promotion_eligibility": decisions["default_promotion_eligible"],
        "default_promotion_criteria": decisions["default_promotion_criteria"],
        "robustness_summary": robustness.to_dict(orient="records"),
        "mdd": {
            "status": "NOT_EVALUATED",
            "reason": "fixed-entry trade replay has no pre-confirmed common portfolio sizing/equity curve; new MDD model is prohibited",
        },
        "source_artifacts": {
            "validation_plan": str(PLAN_PATH.relative_to(ROOT)),
            "v4_readme": str(V4_README_PATH.relative_to(ROOT)),
            "control_trades": str(CONTROL_TRADES_PATH.relative_to(ROOT)),
            "control_summary": str(CONTROL_SUMMARY_PATH.relative_to(ROOT)),
            "v3_official_summary": str(V3_OFFICIAL_SUMMARY_PATH.relative_to(ROOT)),
            "v3_failure_review_summary": str(V3_FAILURE_SUMMARY_PATH.relative_to(ROOT)),
            "v3_official_matched_reference": str(V3_MATCHED_PATH.relative_to(ROOT)),
        },
        "limitations": [
            "V2 is reused from the fixed CONTROL authority; V3 is read-only diagnostic baseline and is not rerun.",
            "MDD is not evaluated because a common portfolio sizing/equity curve is not preregistered.",
            "No official adoption or default promotion decision is made in this lifecycle step.",
            "Current local raw-only dates absent from adjusted analytic authority were explicitly excluded from the composed evaluation view; no adjusted prices were synthesized.",
        ],
    }
    return summary, matched, robustness, exit_reason, representative


def write_outputs(
    summary: Mapping[str, Any],
    matched: pd.DataFrame,
    robustness: pd.DataFrame,
    exit_reason: pd.DataFrame,
    representative: pd.DataFrame,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
    robustness.to_csv(ROBUSTNESS_PATH, index=False, lineterminator="\n")
    exit_reason.to_csv(EXIT_REASON_PATH, index=False, lineterminator="\n")
    representative.to_csv(REPRESENTATIVE_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary, exit_reason), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the official offline FastCore V4 matched A/B backtest")
    audit = diagnostic.NetworkAudit()
    try:
        with diagnostic.network_guard(audit):
            summary, matched, robustness, exit_reason, representative = run_official()
        summary["network_requests"] = audit.request_count
        if audit.request_count != 0:
            summary["status"] = "FAIL"
            raise AssertionError(f"network_requests must be 0, got {audit.request_count}")
        write_outputs(summary, matched, robustness, exit_reason, representative)
        print(json.dumps({
            "status": summary["status"],
            "matched_trades": summary["integrity"]["matched_rows"],
            "unique_tickers": summary["integrity"]["unique_tickers"],
            "network_requests": summary["network_requests"],
            "pre_winner_repair": summary["repair_gates"]["pre_winner_repair"]["decision"],
            "winner_tail_repair": summary["repair_gates"]["winner_tail_repair"]["decision"],
            "official_adoption_eligible": summary["OFFICIAL_ADOPTION_ELIGIBLE"],
            "default_promotion_eligible": summary["default_promotion_eligibility"],
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"FASTCORE V4 OFFICIAL MATCHED A/B BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
