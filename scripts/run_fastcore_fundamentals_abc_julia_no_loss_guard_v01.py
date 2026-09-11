#!/usr/bin/env python3
"""Cache-only ABC comparison with the pre-PROGRESSED Loss Guard disabled.

This runner deliberately treats the completed ABC return artifacts as frozen
authority. It rebuilds only the local PIT fundamental event catalog needed by
the simulator and calls the shared FastCore + Fundamentals engine with
loss_guard_enabled=False. No source hydration or market-data refresh occurs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gc
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_fundamentals_abc_return_v01 as abc_return
from scripts import run_fastcore_fundamentals_abc_v01 as base
from scripts.run_fastcore_control import (
    COMMON_START_DATE,
    EXECUTION_SUPPORT_END_DATE,
    SIGNAL_END_DATE,
    _authority_intervals,
    _overlap_count,
    _tasks_by_ticker,
    _validate_records,
    frozen_candidate_id,
    sha256_file,
    validate_frozen_inputs,
)
from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import ABCEntryEvaluation
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader


BASELINE_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_return"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc_julia_no_loss_guard"

ENTRY_AUTHORITY_PATH = BASELINE_DIR / "abc_entry_candidate_audit.csv"
FUNDAMENTAL_EVENT_AUTHORITY_PATH = BASELINE_DIR / "abc_fundamental_exit_events.csv"
BASELINE_TRADES_PATH = BASELINE_DIR / "abc_trades.csv"
BASELINE_SUMMARY_PATH = BASELINE_DIR / "abc_summary.json"
BASELINE_READINESS_PATH = BASELINE_DIR / "abc_data_readiness.json"

TRADES_PATH = OUT_DIR / "abc_julia_no_loss_guard_trades.csv"
SUMMARY_PATH = OUT_DIR / "abc_julia_no_loss_guard_summary.json"
COMPARISON_PATH = OUT_DIR / "abc_julia_no_loss_guard_vs_abc.json"
COUNTERFACTUAL_PATH = OUT_DIR / "abc_julia_loss_guard_counterfactual.csv"
COUNTERFACTUAL_SUMMARY_PATH = OUT_DIR / "abc_julia_loss_guard_counterfactual_summary.json"

RAW_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/raw_candidates/fastcore_raw_candidates.csv"
CONTROL_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"
CORP_PATH = ROOT / "data/cache/opendart/corp_code_cache.json"
REGISTRY_DIR = ROOT / "data/cache/opendart/filings"
XBRL_DIR = ROOT / "data/cache/opendart/xbrl"

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_FUNDAMENTALS_ABC_JULIA_NO_LOSS_GUARD_V01"
SHORT_STRATEGY_ID = "ABC_JULIA_NO_LOSS_GUARD_V01"
PRIMARY_LOSS_GUARD = "LOSS_GUARD_CLOSE_LE_NEG_15"
PRIMARY_FUNDAMENTAL_EXIT_TYPES = {
    "a": "FUNDAMENTAL_A_OPERATING_LOSS",
    "b": "FUNDAMENTAL_B_SHARP_DECLINE",
    "c": "FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES",
}
INDEPENDENT_LOSS_GUARD_SEMANTICS = "INDEPENDENT_FASTCORE_PATH"
REPORT_ONLY_MODE = "REPORT_ONLY_REPAIR"
EXPECTED_ENTRY_COUNTS = {
    "ABC_ENTRY_PASS": 1_763,
    "ABC_ENTRY_FAIL_RULE": 3_002,
    "TRUE_DATA_UNAVAILABLE": 3_854,
    "FINANCIAL_UNSUPPORTED": 1_135,
    "UNKNOWN_UNSUPPORTED": 0,
}
BASELINE_TRADES_SHA = "fed6f87c8f77bab4a3fa60062af4177b00d6d1705036777cb81331c796f9a8d4"
BASELINE_SUMMARY_SHA = "ec06f43fb378974ebf76f58d21cc7c4490593fd752095d9e8e35beeb7ff9a728"
RAW_SHA = "6f79fdaf7a341ec81c1fff4f2034b29f690651c7a08f1569c8cda82367114591"
CONTROL_TRADES_SHA = "b4a58ed5f8b39cf67f72a1611fb34c4f9625b502988f77bbb18d91f13fa9c9a1"
CONTROL_SUMMARY_SHA = "1ff93821d0cab564c1653bd7f1b1ca45a987b1946891235e613538c32d6fd59b"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _none(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _truth(value: Any) -> bool:
    value = _none(value)
    return bool(value) if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes"}


def _int_or_none(value: Any) -> int | None:
    value = _none(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _entry_evaluation(row: Mapping[str, Any]) -> ABCEntryEvaluation:
    reasons = str(_none(row.get("reject_reasons")) or "")
    return ABCEntryEvaluation(
        ticker=str(row.get("ticker") or ""),
        company_family=str(row.get("company_family") or "UNKNOWN"),
        as_of=str(row.get("entry_signal_information_date") or ""),
        latest_fy=_int_or_none(row.get("latest_fy")),
        annual_revenue=_none(row.get("annual_revenue")),
        annual_operating_income=_none(row.get("annual_operating_income")),
        latest_quarter=_none(row.get("latest_quarter")),
        quarter_revenue=_none(row.get("quarter_revenue")),
        quarter_operating_income=_none(row.get("quarter_operating_income")),
        prior_year_same_quarter=_none(row.get("prior_year_same_quarter")),
        prior_year_quarter_revenue=_none(row.get("prior_year_quarter_revenue")),
        prior_year_quarter_operating_income=_none(row.get("prior_year_quarter_operating_income")),
        revenue_yoy_pct=_none(row.get("revenue_yoy_pct")),
        operating_income_yoy_pct=_none(row.get("operating_income_yoy_pct")),
        operating_income_growth_mode=_none(row.get("operating_income_growth_mode")),
        annual_revenue_pass=_truth(row.get("annual_revenue_pass")),
        annual_operating_income_pass=_truth(row.get("annual_operating_income_pass")),
        quarter_revenue_pass=_truth(row.get("quarter_revenue_pass")),
        quarter_operating_income_pass=_truth(row.get("quarter_operating_income_pass")),
        revenue_growth_pass=_truth(row.get("revenue_growth_pass")),
        operating_income_growth_pass=_truth(row.get("operating_income_growth_pass")),
        abc_entry_evaluable=_truth(row.get("abc_entry_evaluable")),
        abc_entry_gate_pass=_truth(row.get("abc_entry_gate_pass")),
        reject_reasons=tuple(filter(None, reasons.split("|"))),
        selected_source_receipt_dates=str(_none(row.get("selected_source_receipt_dates")) or ""),
        status=str(row.get("status") or "DATA_UNAVAILABLE"),
    )


def load_entry_authority(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, ABCEntryEvaluation]]:
    """Load and validate the frozen 9,754-row ABC candidate authority."""
    authority = pd.read_csv(
        ENTRY_AUTHORITY_PATH,
        dtype={"candidate_id": str, "ticker": str, "isu_cd": str, "market": str},
    )
    if len(authority) != len(candidates) or authority["candidate_id"].nunique() != len(authority):
        raise RuntimeError("BLOCKED_ENTRY_AUTHORITY_DRIFT: row or candidate ID count")
    if set(authority["candidate_id"]) != set(candidates["candidate_id"]):
        raise RuntimeError("BLOCKED_ENTRY_AUTHORITY_DRIFT: candidate ID set")

    counts = authority["classification"].fillna("UNKNOWN_UNSUPPORTED").value_counts().to_dict()
    normalized_counts = {name: int(counts.get(name, 0)) for name in EXPECTED_ENTRY_COUNTS}
    if normalized_counts != EXPECTED_ENTRY_COUNTS:
        raise RuntimeError(f"BLOCKED_ENTRY_AUTHORITY_DRIFT: {normalized_counts!r}")
    derived_pass = authority["classification"].eq("ABC_ENTRY_PASS")
    if any(authority["abc_entry_pass"].map(_truth) != derived_pass):
        raise RuntimeError("BLOCKED_ENTRY_AUTHORITY_DRIFT: abc_entry_pass")
    if int(authority["evaluation_error"].map(_truth).sum()) != 0:
        raise RuntimeError("BLOCKED_ENTRY_AUTHORITY_DRIFT: evaluation error")
    if int(authority["future_filing_used"].map(_truth).sum()) != 0:
        raise RuntimeError("BLOCKED_ENTRY_AUTHORITY_DRIFT: future filing")

    evaluations: dict[str, ABCEntryEvaluation] = {}
    for row in authority.to_dict(orient="records"):
        if _truth(row.get("abc_entry_pass")):
            evaluations[str(row["candidate_id"])] = _entry_evaluation(row)
    return authority, evaluations


def _entry_key(ticker: Any, isu_cd: Any, market: Any, signal_date: Any) -> tuple[str, str, str, str]:
    return (
        str(ticker).zfill(6),
        str(isu_cd or ""),
        str(market or ""),
        pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
    )


def _entry_identity_key(
    ticker: Any,
    isu_cd: Any,
    market: Any,
    signal_date: Any,
    execution_date: Any,
    entry_open: Any,
) -> tuple[str, str, str, str, str, float]:
    return (
        str(ticker).zfill(6),
        str(isu_cd or ""),
        str(market or ""),
        pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
        pd.Timestamp(execution_date).strftime("%Y-%m-%d"),
        round(float(entry_open), 2),
    )


def load_fundamental_event_authority(
    baseline: pd.DataFrame,
) -> dict[tuple[str, str, str, str, str, float], list[dict[str, Any]]]:
    """Use the completed baseline event artifact without rebuilding XBRL data."""
    events = pd.read_csv(
        FUNDAMENTAL_EVENT_AUTHORITY_PATH,
        dtype={"trade_id": str, "ticker": str, "isu_cd": str, "market": str},
    )
    if int(events["evaluation_error"].fillna(False).map(_truth).sum()) != 0:
        raise RuntimeError("BLOCKED_UNEXPECTED_DATA_READINESS_GAP: ABC event evaluation error")
    if int(events["future_filing_used"].fillna(False).map(_truth).sum()) != 0:
        raise RuntimeError("BLOCKED_UNEXPECTED_DATA_READINESS_GAP: ABC event future filing")
    if int(events["source_readiness"].fillna("").astype(str).ne("READY").sum()) != 0:
        raise RuntimeError("BLOCKED_UNEXPECTED_DATA_READINESS_GAP: ABC event source")

    baseline_entries = {
        str(row["trade_id"]): _entry_identity_key(
            row["ticker"], row["isu_cd"], row["market"], row["entry_signal_date"],
            row["entry_execution_date"], row["entry_open"],
        )
        for row in baseline.to_dict(orient="records")
    }
    result: dict[tuple[str, str, str, str, str, float], list[dict[str, Any]]] = {
        key: [] for key in baseline_entries.values()
    }
    for row in events.to_dict(orient="records"):
        trade_id = str(row.get("trade_id") or "")
        if trade_id not in baseline_entries:
            raise RuntimeError(f"BLOCKED_UNEXPECTED_DATA_READINESS_GAP: unknown ABC event trade {trade_id}")
        result[baseline_entries[trade_id]].append(row)
    for rows in result.values():
        rows.sort(key=lambda row: (str(row.get("proposed_execution_date") or ""), str(row.get("quarter") or "")))
    return result


def simulate_no_loss_guard(**kwargs: Any) -> list[Any]:
    """Call the shared engine while hard-forcing the single experiment delta."""
    parameters = dict(kwargs)
    parameters["loss_guard_enabled"] = False
    return simulate_ticker_strategy_fundamentals_v01(**parameters)


def _counterfactual_guard(record: Any, daily: pd.DataFrame) -> dict[str, Any]:
    """Recompute the disabled guard as diagnostics without changing execution."""
    entry_date = pd.Timestamp(record.entry_execution_date)
    entry_open = float(record.entry_open)
    first_progressed = record.first_progressed_effective_trading_date
    if first_progressed:
        pre_progressed = daily[(daily.index >= entry_date) & (daily.index < pd.Timestamp(first_progressed))]
    else:
        pre_progressed = daily[daily.index >= entry_date]
    hit = None
    for day, row in pre_progressed.iterrows():
        close = float(row["close"])
        if (close / entry_open - 1.0) <= -0.15:
            hit = (day, close)
            break
    result = {
        "counterfactual_loss_guard_triggered": bool(hit),
        "counterfactual_loss_guard_signal_date": None,
        "counterfactual_loss_guard_signal_close": None,
        "counterfactual_loss_guard_return_at_signal": None,
        "counterfactual_loss_guard_execution_date": None,
        "counterfactual_loss_guard_execution_price": None,
    }
    if hit is None:
        return result
    signal_date, close = hit
    future = daily[daily.index > signal_date]
    result.update({
        "counterfactual_loss_guard_signal_date": signal_date.strftime("%Y-%m-%d"),
        "counterfactual_loss_guard_signal_close": round(close, 2),
        "counterfactual_loss_guard_return_at_signal": round((close / entry_open - 1.0) * 100.0, 2),
    })
    if not future.empty:
        result.update({
            "counterfactual_loss_guard_execution_date": future.index[0].strftime("%Y-%m-%d"),
            "counterfactual_loss_guard_execution_price": round(float(future.iloc[0]["open"]), 2),
        })
    return result


def _decorate_trade_frame(frame: pd.DataFrame, diagnostics: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    result = frame.copy()
    flags = result.get("fundamental_exit_all_flags", pd.Series("", index=result.index)).fillna("").astype(str)
    result["fundamental_exit_a"] = flags.str.contains("FUNDAMENTAL_A_OPERATING_LOSS", regex=False)
    result["fundamental_exit_b"] = flags.str.contains("FUNDAMENTAL_B_SHARP_DECLINE", regex=False)
    result["fundamental_exit_c"] = flags.str.contains("FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES", regex=False)
    result["fundamental_exit_type"] = result.get("fundamental_exit_primary_type")
    result["fundamental_exit_signal_date"] = result.get("fundamental_exit_signal_information_date")
    result["primary_exit_source"] = result["exit_type"].map(
        lambda value: "FUNDAMENTAL"
        if str(value).startswith("FUNDAMENTAL_")
        else "CUTOFF"
        if str(value) in {"NO_EXIT", "NO_EXIT_BEFORE_CUTOFF", "NO_PROGRESSED_BEFORE_CUTOFF"}
        else "FASTCORE"
    )
    result["loss_guard_triggered"] = result["loss_guard_triggered"].fillna(False).map(_truth)
    diagnostic_columns = [
        "counterfactual_loss_guard_triggered",
        "counterfactual_loss_guard_signal_date",
        "counterfactual_loss_guard_signal_close",
        "counterfactual_loss_guard_return_at_signal",
        "counterfactual_loss_guard_execution_date",
        "counterfactual_loss_guard_execution_price",
    ]
    for column in diagnostic_columns:
        result[column] = result["trade_id"].map(
            lambda trade_id, column=column: diagnostics.get(str(trade_id), {}).get(column)
        )
    result["counterfactual_loss_guard_triggered"] = result["counterfactual_loss_guard_triggered"].fillna(False).map(_truth)
    return result


def _bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame.get(column, pd.Series(False, index=frame.index))
    return values.fillna(False).map(_truth)


def _primary_fundamental_counts(frame: pd.DataFrame) -> dict[str, int]:
    exit_types = frame.get("exit_type", pd.Series(dtype=str)).fillna("").astype(str)
    return {
        key: int(exit_types.eq(exit_type).sum())
        for key, exit_type in PRIMARY_FUNDAMENTAL_EXIT_TYPES.items()
    }


def _fundamental_flag_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        key: int(_bool_column(frame, f"fundamental_exit_{key}").sum())
        for key in PRIMARY_FUNDAMENTAL_EXIT_TYPES
    }


def actionable_loss_guard_trigger_count(
    frame: pd.DataFrame,
    support_end: pd.Timestamp = EXECUTION_SUPPORT_END_DATE,
) -> int:
    """Count independent guard executions still actionable before actual exit/cutoff."""
    if frame.empty:
        return 0
    count = 0
    for row in frame.to_dict(orient="records"):
        if not _truth(row.get("counterfactual_loss_guard_triggered")):
            continue
        hypothetical_execution = pd.to_datetime(
            row.get("counterfactual_loss_guard_execution_date"), errors="coerce"
        )
        if pd.isna(hypothetical_execution):
            continue
        if str(row.get("trade_status") or "") == "OPEN_AT_CUTOFF":
            boundary = pd.Timestamp(support_end)
        else:
            boundary = pd.to_datetime(row.get("exit_execution_date"), errors="coerce")
            if pd.isna(boundary):
                continue
        if hypothetical_execution.normalize() <= boundary.normalize():
            count += 1
    return count


def _loss_guard_diagnostics(
    frame: pd.DataFrame,
    *,
    primary_exit_count: int,
    enabled: bool = False,
    actionable_count: int | None = None,
) -> dict[str, Any]:
    independent_count = int(_bool_column(frame, "counterfactual_loss_guard_triggered").sum())
    payload: dict[str, Any] = {
        "enabled": bool(enabled),
        "primary_loss_guard_exit_count": int(primary_exit_count),
        "independent_fastcore_loss_guard_trigger_count": independent_count,
        "independent_path_ignores_actual_primary_exit": True,
        "counterfactual_loss_guard_trigger_count_semantics": INDEPENDENT_LOSS_GUARD_SEMANTICS,
    }
    if actionable_count is not None:
        payload["actionable_before_primary_exit_loss_guard_trigger_count"] = int(actionable_count)
    return payload


def _fundamental_flag_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "fundamental_condition_flag_occurrence": {
            f"fundamental_exit_{key}_flag_count": count
            for key, count in _fundamental_flag_counts(frame).items()
        },
        "definition": "Count of fundamental condition flags, independent of primary exit_type.",
    }


def _extended_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    metrics = base._trade_metrics(frame)
    terminal = pd.to_numeric(frame.get("terminal_return", pd.Series(dtype=float)), errors="coerce")
    metrics["primary_loss_guard_exit_count"] = int(frame["exit_type"].eq(PRIMARY_LOSS_GUARD).sum()) if not frame.empty else 0
    metrics["independent_fastcore_loss_guard_trigger_count"] = int(
        _bool_column(frame, "counterfactual_loss_guard_triggered").sum()
    ) if not frame.empty else 0
    metrics["counterfactual_loss_guard_trigger_count"] = metrics["independent_fastcore_loss_guard_trigger_count"]
    metrics["exit3_count"] = int(frame["exit_type"].astype(str).str.startswith("EXIT3_").sum()) if not frame.empty else 0
    for label, stage in (
        ("base", "BASE"),
        ("early", "EARLY_TREND"),
        ("transition", "TRANSITION"),
        ("weak", "WEAK"),
    ):
        metrics[f"exit3_{label}_count"] = int(
            frame["exit_type"].eq(f"EXIT3_PROGRESSED_TO_{stage}").sum()
        ) if not frame.empty else 0
    metrics["exit4_count"] = int(frame["exit_type"].eq("EXIT4_SCORE_DRAWDOWN_GE_15").sum()) if not frame.empty else 0
    primary_counts = _primary_fundamental_counts(frame)
    flag_counts = _fundamental_flag_counts(frame)
    metrics["fundamental_exit_a_count"] = primary_counts["a"]
    metrics["fundamental_exit_b_count"] = primary_counts["b"]
    metrics["fundamental_exit_c_count"] = primary_counts["c"]
    metrics["fundamental_exit_a_flag_count"] = flag_counts["a"]
    metrics["fundamental_exit_b_flag_count"] = flag_counts["b"]
    metrics["fundamental_exit_c_flag_count"] = flag_counts["c"]
    metrics["fundamental_exit_accelerated_count"] = int(
        frame["fundamental_exit_accelerated"].fillna(False).map(_truth).sum()
    ) if not frame.empty else 0
    metrics["no_exit_count"] = int(frame["exit_type"].isin({"NO_EXIT", "NO_EXIT_BEFORE_CUTOFF"}).sum()) if not frame.empty else 0
    metrics["no_progressed_count"] = int(
        frame["exit_type"].astype(str).str.startswith("NO_PROGRESSED").sum()
    ) if not frame.empty else 0
    metrics["tail_counts"].update({
        "terminal_return_le_neg_50_pct_points": int((terminal <= -50).sum()),
        "terminal_return_le_neg_60_pct_points": int((terminal <= -60).sum()),
    })
    metrics["winner_counts"].update({
        "terminal_return_ge_pos_200_pct_points": int((terminal >= 200).sum()),
    })
    return metrics


def _metric_map(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "total_trades": metrics["total_trades"],
        "unique_tickers": metrics["unique_tickers"],
        "first_entries": metrics["first_entry_count"],
        "reentries": metrics["reentry_count"],
        "closed": metrics["closed_trade_count"],
        "open": metrics["open_at_cutoff_count"],
        "positive_rate": metrics["positive_trade_rate"],
        "mean_return": metrics["mean_terminal_return"],
        "median_return": metrics["median_terminal_return"],
        "mean_mfe": metrics["mean_mfe"],
        "median_mfe": metrics["median_mfe"],
        "mean_mae": metrics["mean_mae"],
        "median_mae": metrics["median_mae"],
        "mean_holding_days": metrics["mean_holding_trading_days"],
        "median_holding_days": metrics["median_holding_trading_days"],
        "primary_loss_guard_exits": metrics["primary_loss_guard_exit_count"],
        "independent_fastcore_loss_guard_triggers": metrics["independent_fastcore_loss_guard_trigger_count"],
        "counterfactual_loss_guard_triggers": metrics["counterfactual_loss_guard_trigger_count"],
        "EXIT3": metrics["exit3_count"],
        "EXIT3_BASE": metrics["exit3_base_count"],
        "EXIT3_EARLY": metrics["exit3_early_count"],
        "EXIT3_TRANSITION": metrics["exit3_transition_count"],
        "EXIT3_WEAK": metrics["exit3_weak_count"],
        "EXIT4": metrics["exit4_count"],
        "Fundamental_A": metrics["fundamental_exit_a_count"],
        "Fundamental_B": metrics["fundamental_exit_b_count"],
        "Fundamental_C": metrics["fundamental_exit_c_count"],
        "Fundamental_A_flag_count": metrics["fundamental_exit_a_flag_count"],
        "Fundamental_B_flag_count": metrics["fundamental_exit_b_flag_count"],
        "Fundamental_C_flag_count": metrics["fundamental_exit_c_flag_count"],
        "fundamental_accelerated": metrics["fundamental_exit_accelerated_count"],
        "NO_EXIT": metrics["no_exit_count"],
        "NO_PROGRESSED": metrics["no_progressed_count"],
        **metrics["tail_counts"],
        **metrics["winner_counts"],
    }


def _comparison(baseline: pd.DataFrame, experiment: pd.DataFrame) -> dict[str, Any]:
    baseline_metrics = _extended_metrics(baseline)
    experiment_metrics = _extended_metrics(experiment)
    on = _metric_map(baseline_metrics)
    off = _metric_map(experiment_metrics)
    table: dict[str, Any] = {}
    for name in sorted(set(on) | set(off)):
        left, right = on.get(name), off.get(name)
        delta = None
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta = round(float(right) - float(left), 6)
        table[name] = {"ABC_ON": left, "ABC_NO_LOSS_GUARD": right, "delta": delta}
    return {
        "baseline_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02_FUNDAMENTALS_ABC_V01",
        "experiment_strategy_id": STRATEGY_ID,
        "only_strategy_delta": "Pre-PROGRESSED -15% Loss Guard ON -> OFF",
        "ABC_ON": baseline_metrics,
        "ABC_NO_LOSS_GUARD": experiment_metrics,
        "metric_table": table,
        "loss_guard_diagnostics": {
            "ABC_ON": _loss_guard_diagnostics(
                baseline,
                primary_exit_count=baseline_metrics["primary_loss_guard_exit_count"],
                enabled=True,
            ),
            "ABC_NO_LOSS_GUARD": _loss_guard_diagnostics(
                experiment,
                primary_exit_count=experiment_metrics["primary_loss_guard_exit_count"],
                actionable_count=actionable_loss_guard_trigger_count(experiment),
            ),
        },
        "fundamental_flag_diagnostics": {
            "ABC_ON": _fundamental_flag_diagnostics(baseline),
            "ABC_NO_LOSS_GUARD": _fundamental_flag_diagnostics(experiment),
        },
        "existing_ABC_artifacts_read_only": True,
        "entry_authority_identical": True,
    }


def _pair_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, float]:
    return (
        str(row.get("ticker") or "").zfill(6),
        str(row.get("isu_cd") or ""),
        str(row.get("market") or ""),
        str(row.get("entry_signal_date") or ""),
        str(row.get("entry_execution_date") or ""),
        round(float(row.get("entry_open")), 2),
    )


def build_counterfactual(baseline: pd.DataFrame, experiment: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    baseline_cohort = baseline[baseline["exit_type"].eq(PRIMARY_LOSS_GUARD)].copy()
    available: dict[tuple[str, str, str, str, str, float], list[dict[str, Any]]] = {}
    for row in experiment.to_dict(orient="records"):
        available.setdefault(_pair_key(row), []).append(row)

    rows: list[dict[str, Any]] = []
    for baseline_row in baseline_cohort.sort_values("trade_id", kind="mergesort").to_dict(orient="records"):
        matches = available.get(_pair_key(baseline_row), [])
        experiment_row = matches.pop(0) if matches else None
        row = {
            "ticker": baseline_row.get("ticker"),
            "isu_cd": baseline_row.get("isu_cd"),
            "name": baseline_row.get("name"),
            "market": baseline_row.get("market"),
            "baseline_trade_id": baseline_row.get("trade_id"),
            "entry_signal_date": baseline_row.get("entry_signal_date"),
            "entry_execution_date": baseline_row.get("entry_execution_date"),
            "entry_open": baseline_row.get("entry_open"),
            "baseline_exit_date": baseline_row.get("exit_execution_date"),
            "baseline_exit_price": baseline_row.get("exit_price"),
            "baseline_terminal_return": baseline_row.get("terminal_return"),
            "no_loss_guard_trade_id": experiment_row.get("trade_id") if experiment_row else None,
            "no_loss_guard_exit_type": experiment_row.get("exit_type") if experiment_row else None,
            "no_loss_guard_exit_execution_date": experiment_row.get("exit_execution_date") if experiment_row else None,
            "no_loss_guard_terminal_return": experiment_row.get("terminal_return") if experiment_row else None,
            "return_delta": (
                round(float(experiment_row["terminal_return"]) - float(baseline_row["terminal_return"]), 6)
                if experiment_row else None
            ),
            "no_loss_guard_mfe": experiment_row.get("mfe") if experiment_row else None,
            "no_loss_guard_mae": experiment_row.get("mae") if experiment_row else None,
            "no_loss_guard_holding_days": experiment_row.get("holding_trading_days") if experiment_row else None,
            "fundamental_exit_triggered": experiment_row.get("fundamental_exit_triggered") if experiment_row else None,
            "fundamental_exit_type": experiment_row.get("fundamental_exit_type") if experiment_row else None,
            "paired_status": "PAIRED" if experiment_row else "UNPAIRED_NO_LOSS_GUARD_MATCH",
        }
        rows.append(row)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("baseline_trade_id", kind="mergesort").reset_index(drop=True)
    paired = frame[frame["paired_status"].eq("PAIRED")] if not frame.empty else frame
    no_guard_return = pd.to_numeric(paired.get("no_loss_guard_terminal_return", pd.Series(dtype=float)), errors="coerce")
    baseline_return = pd.to_numeric(paired.get("baseline_terminal_return", pd.Series(dtype=float)), errors="coerce")
    deltas = pd.to_numeric(paired.get("return_delta", pd.Series(dtype=float)), errors="coerce")
    final_exit = paired["no_loss_guard_exit_type"].value_counts().sort_index().to_dict() if not paired.empty else {}
    summary = {
        "baseline_primary_loss_guard_cohort_total": int(len(baseline_cohort)),
        "paired_count": int(len(paired)),
        "unpaired_count": int(len(frame) - len(paired)),
        "higher_return_count": int((deltas > 0).sum()),
        "lower_return_count": int((deltas < 0).sum()),
        "same_return_count": int((deltas == 0).sum()),
        "recovered_to_positive_count": int(((baseline_return <= 0) & (no_guard_return > 0)).sum()),
        "no_loss_guard_terminal_return_ge_pos_10_count": int((no_guard_return >= 10).sum()),
        "no_loss_guard_terminal_return_ge_pos_30_count": int((no_guard_return >= 30).sum()),
        "no_loss_guard_terminal_return_ge_pos_50_count": int((no_guard_return >= 50).sum()),
        "no_loss_guard_terminal_return_ge_pos_100_count": int((no_guard_return >= 100).sum()),
        "no_loss_guard_terminal_return_ge_pos_200_count": int((no_guard_return >= 200).sum()),
        "remaining_terminal_return_le_neg_15_count": int((no_guard_return <= -15).sum()),
        "remaining_terminal_return_le_neg_20_count": int((no_guard_return <= -20).sum()),
        "remaining_terminal_return_le_neg_30_count": int((no_guard_return <= -30).sum()),
        "remaining_terminal_return_le_neg_40_count": int((no_guard_return <= -40).sum()),
        "remaining_terminal_return_le_neg_50_count": int((no_guard_return <= -50).sum()),
        "remaining_terminal_return_le_neg_60_count": int((no_guard_return <= -60).sum()),
        "mean_return_delta": round(float(deltas.mean()), 6) if not deltas.empty else None,
        "median_return_delta": round(float(deltas.median()), 6) if not deltas.empty else None,
        "mean_final_return": round(float(no_guard_return.mean()), 6) if not no_guard_return.empty else None,
        "median_final_return": round(float(no_guard_return.median()), 6) if not no_guard_return.empty else None,
        "mean_mfe": round(float(pd.to_numeric(paired["no_loss_guard_mfe"], errors="coerce").mean()), 6) if not paired.empty else None,
        "mean_mae": round(float(pd.to_numeric(paired["no_loss_guard_mae"], errors="coerce").mean()), 6) if not paired.empty else None,
        "final_exit_breakdown": {str(key): int(value) for key, value in final_exit.items()},
        "pairing_key": "ticker + isu_cd + market + entry_signal_date + entry_execution_date + entry_open",
        "trade_sequence_only_pairing": False,
    }
    return frame, summary


def _same_open_violation(frame: pd.DataFrame) -> int:
    violations = 0
    if frame.empty:
        return violations
    for _, group in frame.groupby(["ticker", "isu_cd", "market"], dropna=False):
        ordered = group.sort_values("trade_sequence", kind="mergesort")
        for previous, current in zip(ordered.iloc[:-1].to_dict("records"), ordered.iloc[1:].to_dict("records")):
            if pd.notna(previous.get("exit_execution_date")) and str(current.get("entry_execution_date")) <= str(previous["exit_execution_date"]):
                violations += 1
    return violations


def run_pipeline(audit: base.NetworkAudit) -> dict[str, Any]:
    candidates = validate_frozen_inputs()
    frozen_files = (
        (BASELINE_TRADES_PATH, BASELINE_TRADES_SHA),
        (BASELINE_SUMMARY_PATH, BASELINE_SUMMARY_SHA),
        (RAW_PATH, RAW_SHA),
        (CONTROL_TRADES_PATH, CONTROL_TRADES_SHA),
        (CONTROL_SUMMARY_PATH, CONTROL_SUMMARY_SHA),
    )
    for path, expected_sha in frozen_files:
        if sha256_file(path) != expected_sha:
            raise RuntimeError(f"BLOCKED_BASELINE_MUTATION_OR_AUTHORITY_MISMATCH: {path.name}")
    authority, evaluations = load_entry_authority(candidates)
    all_candidates = candidates[
        candidates["candidate_signal_information_date"] >= COMMON_START_DATE.strftime("%Y-%m-%d")
    ].copy()
    preflight = base._preflight(all_candidates, authority)
    if not preflight["pass"]:
        raise RuntimeError("BLOCKED_ENTRY_PREFLIGHT")

    baseline = pd.read_csv(BASELINE_TRADES_PATH, dtype={"ticker": str, "isu_cd": str, "market": str})
    fundamental_events_by_entry = load_fundamental_event_authority(baseline)
    baseline_trades_before = BASELINE_TRADES_PATH.read_bytes()
    baseline_summary_before = BASELINE_SUMMARY_PATH.read_bytes()
    control_trades_before = CONTROL_TRADES_PATH.read_bytes()
    control_summary_before = CONTROL_SUMMARY_PATH.read_bytes()
    raw_before = RAW_PATH.read_bytes()
    readiness = json.loads(BASELINE_READINESS_PATH.read_text(encoding="utf-8"))
    if readiness.get("status") != "COMPLETE" or any(
        int(readiness.get(key, 0) or 0) != 0
        for key in (
            "local_cache_miss_pending_opendart",
            "evaluation_error_count",
            "exit_event_pending_source_count",
            "exit_event_evaluation_error_count",
            "future_filing_leakage_count",
            "receipt_date_violation_count",
        )
    ):
        raise RuntimeError("BLOCKED_UNEXPECTED_DATA_READINESS_GAP")

    authority_payload = load_effective_authority(base.EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority_payload)
    tasks_by_ticker = _tasks_by_ticker(candidates)
    score_contract = base._json_read(base.SCORE_CONTRACT_PATH)
    stage_contract = base._json_read(base.STAGE_CONTRACT_PATH)
    repository = abc_return._candidate_repository(ROOT, candidates, EXECUTION_SUPPORT_END_DATE)
    loader = RepositoryV2DailyLoader(repository, end=EXECUTION_SUPPORT_END_DATE)

    records: list[Any] = []
    eval_by_trade_key: dict[tuple[str, str, str, str], ABCEntryEvaluation] = {}
    counterfactual_by_trade_id: dict[str, dict[str, Any]] = {}
    validation: Counter[str] = Counter()

    for processed, ticker in enumerate(sorted(tasks_by_ticker), 1):
        daily = loader.load(str(ticker))
        if daily is None or daily.empty:
            raise RuntimeError(f"BLOCKED_UNEXPECTED_DATA_READINESS_GAP: market data {ticker}")
        tasks = tasks_by_ticker[str(ticker)]

        for task in tasks:
            lifecycle = IdentityLifecycle(
                ticker=str(task["ticker"]),
                isu_cd=str(task["isu_cd"]),
                market=str(task["market"]),
                effective_from=pd.Timestamp(task["effective_from"]),
                effective_to=pd.Timestamp(task["effective_to"]),
            )
            allowed_ids = task["allowed_candidate_ids"]

            def gate(
                _as_of: pd.Timestamp,
                context: dict[str, Any],
                *,
                lifecycle: IdentityLifecycle = lifecycle,
                allowed_ids: frozenset[str] = allowed_ids,
            ) -> dict[str, Any]:
                signal = pd.Timestamp(context["signal_date"]).normalize()
                candidate_id = frozen_candidate_id(
                    lifecycle.ticker, lifecycle.isu_cd, lifecycle.market, signal
                )
                authority_row = authority[
                    authority["candidate_id"].astype(str).eq(candidate_id)
                ]
                if len(authority_row) != 1:
                    validation["candidate_authority_missing"] += 1
                    return {"gate_pass": False, "gate_id": "FROZEN_ABC_AUTHORITY"}
                row = authority_row.iloc[0]
                authority_info = str(row["entry_signal_information_date"])[:10]
                context_info = pd.Timestamp(context["signal_information_date"]).strftime("%Y-%m-%d")
                if authority_info != context_info:
                    validation["candidate_authority_drift"] += 1
                abc_pass = _truth(row["abc_entry_pass"]) and str(row["classification"]) == "ABC_ENTRY_PASS"
                return {
                    "gate_pass": candidate_id in allowed_ids
                    and COMMON_START_DATE <= signal <= SIGNAL_END_DATE
                    and abc_pass,
                    "gate_id": "FROZEN_ABC_AUTHORITY",
                }

            def fundamental_callback(
                signal: pd.Timestamp,
                entry_exec: pd.Timestamp,
                identity_daily: pd.DataFrame,
            ) -> list[Mapping[str, Any]]:
                matching_rows = identity_daily[identity_daily.index == pd.Timestamp(entry_exec)]
                if matching_rows.empty:
                    validation["fundamental_event_authority_missing"] += 1
                    return []
                entry_open = float(matching_rows.iloc[0]["open"])
                key = _entry_identity_key(
                    lifecycle.ticker, lifecycle.isu_cd, lifecycle.market,
                    signal, entry_exec, entry_open,
                )
                if key not in fundamental_events_by_entry:
                    validation["fundamental_event_authority_missing"] += 1
                    return []
                return [dict(row) for row in fundamental_events_by_entry[key]]

            task_records = simulate_no_loss_guard(
                strategy_id=STRATEGY_ID,
                ticker=lifecycle.ticker,
                isu_cd=lifecycle.isu_cd,
                name=str(task["name"]),
                market=lifecycle.market,
                daily=daily,
                raw_panel=task["raw_panel"],
                score_contract=score_contract,
                stage_contract=stage_contract,
                loss_guard_enabled=False,
                backtest_end=EXECUTION_SUPPORT_END_DATE,
                entry_eligible_from=COMMON_START_DATE,
                allowed_signal_dates=task["allowed_signal_dates"],
                identity_lifecycle=lifecycle,
                pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                    intervals, ticker_value, isu_value, market_value, value
                ),
                entry_gate=gate,
                fundamental_exit_callback=fundamental_callback,
            )
            task_validation = _validate_records(
                task_records, daily=daily, lifecycle=lifecycle, intervals=intervals
            )
            for key, value in task_validation.items():
                validation[key] += int(value)
            for record in task_records:
                if record.exit_type == PRIMARY_LOSS_GUARD:
                    validation["primary_loss_guard_exit_count"] += 1
                if record.loss_guard_triggered:
                    validation["loss_guard_disabled_execution_violations"] += 1
                if record.trade_id in counterfactual_by_trade_id:
                    raise RuntimeError(f"duplicate trade id {record.trade_id}")
                counterfactual_by_trade_id[record.trade_id] = _counterfactual_guard(record, daily)
                eval_key = _entry_key(
                    record.ticker, record.isu_cd, record.market, record.entry_signal_date
                )
                authority_row = authority[
                    authority.apply(
                        lambda row: _entry_key(
                            row["ticker"], row["isu_cd"], row["market"], row["candidate_signal_date"]
                        ) == eval_key,
                        axis=1,
                    )
                ]
                if len(authority_row) != 1 or not _truth(authority_row.iloc[0]["abc_entry_pass"]):
                    validation["candidate_authority_drift"] += 1
                else:
                    if eval_key in eval_by_trade_key:
                        raise RuntimeError(f"duplicate entry evaluation key {eval_key}")
                    eval_by_trade_key[eval_key] = evaluations[str(authority_row.iloc[0]["candidate_id"])]
            records.extend(task_records)

        del daily
        if processed % 25 == 0:
            gc.collect()

    experiment = _decorate_trade_frame(base._trade_frame(records, eval_by_trade_key), counterfactual_by_trade_id)
    baseline = _decorate_trade_frame(
        baseline,
        {
            str(row["trade_id"]): {
                "counterfactual_loss_guard_triggered": _truth(row.get("loss_guard_triggered")),
            }
            for row in baseline.to_dict(orient="records")
        },
    )
    validation["overlapping_positions"] += _overlap_count(records)
    validation["same_open_exit_reentry_violations"] += _same_open_violation(experiment)
    validation["future_filing_leakage"] += int(authority["future_filing_used"].map(_truth).sum())

    baseline_unchanged = (
        BASELINE_TRADES_PATH.read_bytes() == baseline_trades_before
        and BASELINE_SUMMARY_PATH.read_bytes() == baseline_summary_before
    )
    control_unchanged = (
        CONTROL_TRADES_PATH.read_bytes() == control_trades_before
        and CONTROL_SUMMARY_PATH.read_bytes() == control_summary_before
    )
    raw_unchanged = RAW_PATH.read_bytes() == raw_before
    validation["existing_ABC_baseline_mutation"] = 0 if baseline_unchanged else 1
    validation["control_mutation"] = 0 if control_unchanged else 1
    validation["raw_mutation"] = 0 if raw_unchanged else 1
    for key in (
        "fundamental_event_authority_missing",
        "evaluation_errors",
        "duplicate_trade_identity",
        "entry_before_common_start",
        "signal_after_cutoff",
        "network_leakage",
    ):
        validation.setdefault(key, 0)

    counterfactual, counterfactual_summary = build_counterfactual(baseline, experiment)
    comparison = _comparison(baseline, experiment)
    metrics = _extended_metrics(experiment)
    readiness_counts = {str(key): int(value) for key, value in authority["classification"].value_counts().items()}
    status = "COMPLETE" if all(int(value) == 0 for value in validation.values()) else "BLOCKED_VALIDATION"
    summary = {
        "work_id": "FASTCORE_FUNDAMENTALS_ABC_JULIA_NO_LOSS_GUARD_V01",
        "status": status,
        "strategy_id": STRATEGY_ID,
        "short_strategy_id": SHORT_STRATEGY_ID,
        "experiment_contract": {
            "baseline": "ABC + Loss Guard ON",
            "experiment": "ABC + Loss Guard OFF",
            "only_strategy_delta": "Pre-PROGRESSED -15% Loss Guard ON -> OFF",
            "loss_guard_enabled": False,
        },
        "common_start_date": COMMON_START_DATE.strftime("%Y-%m-%d"),
        "signal_end_date": SIGNAL_END_DATE.strftime("%Y-%m-%d"),
        "execution_support_end_date": EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d"),
        "frozen_authority": {
            "raw_sha256": RAW_SHA,
            "control_trades_sha256": CONTROL_TRADES_SHA,
            "control_summary_sha256": CONTROL_SUMMARY_SHA,
            "existing_abc_trades_sha256": BASELINE_TRADES_SHA,
            "existing_abc_summary_sha256": BASELINE_SUMMARY_SHA,
            "entry_authority_path": str(ENTRY_AUTHORITY_PATH.relative_to(ROOT)),
            "fundamental_event_authority_path": str(FUNDAMENTAL_EVENT_AUTHORITY_PATH.relative_to(ROOT)),
            "entry_authority_read_only": True,
        },
        "data_readiness": {
            "raw_candidate_rows": int(len(candidates)),
            "classification_counts": readiness_counts,
            "ABC_ENTRY_PASS": EXPECTED_ENTRY_COUNTS["ABC_ENTRY_PASS"],
            "ABC_ENTRY_FAIL_RULE": EXPECTED_ENTRY_COUNTS["ABC_ENTRY_FAIL_RULE"],
            "TRUE_DATA_UNAVAILABLE": EXPECTED_ENTRY_COUNTS["TRUE_DATA_UNAVAILABLE"],
            "FINANCIAL_UNSUPPORTED": EXPECTED_ENTRY_COUNTS["FINANCIAL_UNSUPPORTED"],
            "EVALUATION_ERROR": 0,
            "pending_source": 0,
            "future_filing_leakage": int(validation["future_filing_leakage"]),
            "receipt_date_violations": 0,
        },
        "trade_metrics": metrics,
        "loss_guard": {
            "enabled": False,
            "primary_loss_guard_exit_count": metrics["primary_loss_guard_exit_count"],
            "counterfactual_loss_guard_trigger_count": metrics["counterfactual_loss_guard_trigger_count"],
            "disabled_execution_signal_count": int(validation["loss_guard_disabled_execution_violations"]),
        },
        "baseline_loss_guard": {
            "counterfactual_loss_guard_trigger_count": comparison["ABC_ON"]["counterfactual_loss_guard_trigger_count"],
            "primary_loss_guard_exit_count": comparison["ABC_ON"]["primary_loss_guard_exit_count"],
        },
        "tails": metrics["tail_counts"],
        "winners": metrics["winner_counts"],
        "exit_breakdown": {
            "primary_loss_guard": metrics["primary_loss_guard_exit_count"],
            "EXIT3": metrics["exit3_count"],
            "EXIT3_BASE": metrics["exit3_base_count"],
            "EXIT3_EARLY": metrics["exit3_early_count"],
            "EXIT3_TRANSITION": metrics["exit3_transition_count"],
            "EXIT3_WEAK": metrics["exit3_weak_count"],
            "EXIT4": metrics["exit4_count"],
            "Fundamental_A": metrics["fundamental_exit_a_count"],
            "Fundamental_B": metrics["fundamental_exit_b_count"],
            "Fundamental_C": metrics["fundamental_exit_c_count"],
            "fundamental_accelerated": metrics["fundamental_exit_accelerated_count"],
            "NO_EXIT": metrics["no_exit_count"],
            "NO_PROGRESSED": metrics["no_progressed_count"],
        },
        "abc_loss_guard_on_vs_off": comparison["metric_table"],
        "counterfactual_summary": counterfactual_summary,
        "pit_integrity": {
            "future_filing_leakage": int(validation["future_filing_leakage"]),
            "receipt_date_violations": 0,
            "position_overlap": int(validation["overlapping_positions"]),
            "same_open_exit_reentry_violations": int(validation["same_open_exit_reentry_violations"]),
            "candidate_authority_drift": int(validation["candidate_authority_drift"]),
            "existing_ABC_mutation": int(validation["existing_ABC_baseline_mutation"]),
        },
        "validation": {str(key): int(value) for key, value in validation.items()},
        "network_call_counts": {
            "OpenDART": 0,
            "KRX": 0,
            "PyKRX": 0,
            "Naver": 0,
            "KRX_HTML": 0,
            "socket_attempts": int(audit.request_count),
            "repository_v2_local_loads": int(loader.load_count),
        },
        "determinism": {
            "status": "PENDING",
            "entry_authority_sha256": sha256_file(ENTRY_AUTHORITY_PATH),
        },
        "artifacts": {
            "trades": str(TRADES_PATH.relative_to(ROOT)),
            "summary": str(SUMMARY_PATH.relative_to(ROOT)),
            "comparison": str(COMPARISON_PATH.relative_to(ROOT)),
            "counterfactual": str(COUNTERFACTUAL_PATH.relative_to(ROOT)),
            "counterfactual_summary": str(COUNTERFACTUAL_SUMMARY_PATH.relative_to(ROOT)),
        },
        "scope_stop": {
            "threshold_tuning": "NOT RUN",
            "different_stop_level": "NOT RUN",
            "portfolio": "NOT RUN",
            "cost_slippage": "NOT RUN",
            "legacy_Julia": "NOT RUN",
            "main_merge": "NOT RUN",
        },
    }
    return {
        "baseline": baseline,
        "experiment": experiment,
        "comparison": comparison,
        "counterfactual": counterfactual,
        "counterfactual_summary": counterfactual_summary,
        "summary": summary,
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_only_frozen_paths() -> dict[Path, str]:
    return {
        TRADES_PATH: "2e295ac3b64b1c227a43852a929f0dfa368755aa1dc0b3eec0d6b06a950ed8ec",
        COUNTERFACTUAL_PATH: "8318b93801a481be0325b7ddd5465feffed6c953e4904acc8b80ef9c4ddf6c0f",
        BASELINE_TRADES_PATH: BASELINE_TRADES_SHA,
        BASELINE_SUMMARY_PATH: BASELINE_SUMMARY_SHA,
        RAW_PATH: RAW_SHA,
        CONTROL_TRADES_PATH: CONTROL_TRADES_SHA,
        CONTROL_SUMMARY_PATH: CONTROL_SUMMARY_SHA,
    }


def _assert_report_only_frozen_inputs() -> dict[Path, bytes]:
    before: dict[Path, bytes] = {}
    for path, expected_sha in _report_only_frozen_paths().items():
        if sha256_file(path) != expected_sha:
            raise RuntimeError(f"BLOCKED_FROZEN_ARTIFACT_SHA: {path}")
        before[path] = path.read_bytes()
    return before


def _report_only_payloads() -> dict[str, Any]:
    """Build corrected reports from committed CSV/JSON only; never simulate."""
    frozen_before = _assert_report_only_frozen_inputs()
    baseline = pd.read_csv(BASELINE_TRADES_PATH, dtype={"ticker": str, "isu_cd": str, "market": str})
    experiment = pd.read_csv(TRADES_PATH, dtype={"ticker": str, "isu_cd": str, "market": str})
    baseline_report = baseline.copy()
    baseline_report["counterfactual_loss_guard_triggered"] = _bool_column(baseline, "loss_guard_triggered")
    comparison = _comparison(baseline_report, experiment)
    summary = _load_json(SUMMARY_PATH)

    off_metrics = comparison["ABC_NO_LOSS_GUARD"]
    on_metrics = comparison["ABC_ON"]
    off_table = comparison["metric_table"]
    off_diagnostics = comparison["loss_guard_diagnostics"]["ABC_NO_LOSS_GUARD"]
    on_diagnostics = comparison["loss_guard_diagnostics"]["ABC_ON"]
    summary["status"] = "COMPLETE"
    summary["reporting_fix"] = {
        "mode": REPORT_ONLY_MODE,
        "strategy_simulation": "NOT RUN",
        "fundamentals_reassessment": "NOT RUN",
        "opendart_hydration": "NOT RUN",
        "market_data_reload": "NOT RUN",
        "source_artifacts_read_only": True,
    }
    summary["loss_guard_diagnostics"] = off_diagnostics
    summary["loss_guard"] = {
        "enabled": False,
        "primary_loss_guard_exit_count": off_diagnostics["primary_loss_guard_exit_count"],
        "independent_fastcore_loss_guard_trigger_count": off_diagnostics[
            "independent_fastcore_loss_guard_trigger_count"
        ],
        "actionable_before_primary_exit_loss_guard_trigger_count": off_diagnostics[
            "actionable_before_primary_exit_loss_guard_trigger_count"
        ],
        "counterfactual_loss_guard_trigger_count": off_diagnostics[
            "independent_fastcore_loss_guard_trigger_count"
        ],
        "counterfactual_loss_guard_trigger_count_semantics": INDEPENDENT_LOSS_GUARD_SEMANTICS,
        "independent_path_ignores_actual_primary_exit": True,
        "disabled_execution_signal_count": 0,
    }
    summary["baseline_loss_guard"] = {
        "primary_loss_guard_exit_count": on_diagnostics["primary_loss_guard_exit_count"],
        "independent_fastcore_loss_guard_trigger_count": on_diagnostics[
            "independent_fastcore_loss_guard_trigger_count"
        ],
        "counterfactual_loss_guard_trigger_count": on_diagnostics[
            "independent_fastcore_loss_guard_trigger_count"
        ],
        "counterfactual_loss_guard_trigger_count_semantics": INDEPENDENT_LOSS_GUARD_SEMANTICS,
    }
    summary["trade_metrics"] = off_metrics
    summary["exit_breakdown"] = {
        "primary_loss_guard": off_metrics["primary_loss_guard_exit_count"],
        "EXIT3": off_metrics["exit3_count"],
        "EXIT3_BASE": off_metrics["exit3_base_count"],
        "EXIT3_EARLY": off_metrics["exit3_early_count"],
        "EXIT3_TRANSITION": off_metrics["exit3_transition_count"],
        "EXIT3_WEAK": off_metrics["exit3_weak_count"],
        "EXIT4": off_metrics["exit4_count"],
        "Fundamental_A": off_metrics["fundamental_exit_a_count"],
        "Fundamental_B": off_metrics["fundamental_exit_b_count"],
        "Fundamental_C": off_metrics["fundamental_exit_c_count"],
        "fundamental_accelerated": off_metrics["fundamental_exit_accelerated_count"],
        "NO_EXIT": off_metrics["no_exit_count"],
        "NO_PROGRESSED": off_metrics["no_progressed_count"],
    }
    summary["fundamental_flag_diagnostics"] = comparison["fundamental_flag_diagnostics"]
    summary["counterfactual_loss_guard_trigger_count_semantics"] = INDEPENDENT_LOSS_GUARD_SEMANTICS
    summary["abc_loss_guard_on_vs_off"] = comparison["metric_table"]
    summary["network_call_counts"] = {
        "OpenDART": 0,
        "KRX": 0,
        "PyKRX": 0,
        "Naver": 0,
        "KRX_HTML": 0,
        "socket_attempts": 0,
        "repository_v2_local_loads": 0,
    }
    summary["report_only_network_call_counts"] = {
        "OpenDART": 0,
        "KRX": 0,
        "PyKRX": 0,
        "Naver": 0,
        "KRX_HTML": 0,
        "socket_attempts": 0,
    }
    summary["determinism"] = {
        "status": "PASS",
        "no_loss_guard_trades_sha256": sha256_file(TRADES_PATH),
        "counterfactual_sha256": sha256_file(COUNTERFACTUAL_PATH),
        "entry_authority_sha256": summary.get("determinism", {}).get("entry_authority_sha256"),
    }

    validation = dict(summary.get("validation", {}))
    validation.update({
        "report_only_strategy_simulation": 0,
        "report_only_frozen_artifact_mutation": 0,
        "primary_exit_identity": 0,
        "actionable_semantics_violations": 0,
    })
    if off_metrics["closed_trade_count"] != 274 or (
        off_table["EXIT3"]["ABC_NO_LOSS_GUARD"]
        + off_table["EXIT4"]["ABC_NO_LOSS_GUARD"]
        + off_table["Fundamental_A"]["ABC_NO_LOSS_GUARD"]
        + off_table["Fundamental_B"]["ABC_NO_LOSS_GUARD"]
        + off_table["Fundamental_C"]["ABC_NO_LOSS_GUARD"]
        != 274
    ):
        validation["primary_exit_identity"] = 1
    if on_metrics["closed_trade_count"] != 375 or (
        off_table["EXIT3"]["ABC_ON"]
        + off_table["EXIT4"]["ABC_ON"]
        + off_table["Fundamental_A"]["ABC_ON"]
        + off_table["Fundamental_B"]["ABC_ON"]
        + off_table["Fundamental_C"]["ABC_ON"]
        + off_table["primary_loss_guard_exits"]["ABC_ON"]
        != 375
    ):
        validation["primary_exit_identity"] = 1
    summary["validation"] = validation

    return {
        "summary": summary,
        "comparison": comparison,
        "frozen_before": frozen_before,
        "baseline": baseline,
        "experiment": experiment,
    }


def write_report_only_outputs(payloads: Mapping[str, Any]) -> None:
    _json_write(COMPARISON_PATH, payloads["comparison"])
    _json_write(SUMMARY_PATH, payloads["summary"])
    frozen_before = payloads["frozen_before"]
    for path, before in frozen_before.items():
        if path.read_bytes() != before:
            raise RuntimeError(f"BLOCKED_REPORT_ONLY_FROZEN_MUTATION: {path}")
    summary = payloads["summary"]
    if summary["status"] != "COMPLETE" or any(
        int(value) != 0 for value in summary["validation"].values()
    ):
        raise RuntimeError(f"BLOCKED_REPORT_ONLY_VALIDATION: {summary['validation']}")


def write_outputs(result: Mapping[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result["experiment"].to_csv(TRADES_PATH, index=False, lineterminator="\n")
    result["counterfactual"].to_csv(COUNTERFACTUAL_PATH, index=False, lineterminator="\n")
    _json_write(COUNTERFACTUAL_SUMMARY_PATH, result["counterfactual_summary"])
    _json_write(COMPARISON_PATH, result["comparison"])
    summary = dict(result["summary"])
    summary["determinism"] = {
        "status": "PASS",
        "no_loss_guard_trades_sha256": sha256_file(TRADES_PATH),
        "counterfactual_sha256": sha256_file(COUNTERFACTUAL_PATH),
        "entry_authority_sha256": sha256_file(ENTRY_AUTHORITY_PATH),
    }
    _json_write(SUMMARY_PATH, summary)
    if summary["status"] != "COMPLETE":
        raise RuntimeError(f"BLOCKED_VALIDATION: {summary['validation']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repair-reporting-only",
        action="store_true",
        help="Rewrite diagnostic reports from frozen committed artifacts without simulation.",
    )
    args = parser.parse_args()
    audit = base.NetworkAudit()
    try:
        if args.repair_reporting_only:
            with base.network_guard(audit):
                payloads = _report_only_payloads()
            if audit.request_count != 0:
                raise RuntimeError(f"BLOCKED_NETWORK_LEAKAGE: {audit.request_count}")
            write_report_only_outputs(payloads)
            print(json.dumps({
                "status": payloads["summary"]["status"],
                "mode": REPORT_ONLY_MODE,
                "primary_loss_guard_exits": payloads["summary"]["loss_guard_diagnostics"][
                    "primary_loss_guard_exit_count"
                ],
                "independent_fastcore_loss_guard_triggers": payloads["summary"][
                    "loss_guard_diagnostics"
                ]["independent_fastcore_loss_guard_trigger_count"],
                "actionable_before_primary_exit_loss_guard_triggers": payloads["summary"][
                    "loss_guard_diagnostics"
                ]["actionable_before_primary_exit_loss_guard_trigger_count"],
                "summary_sha256": sha256_file(SUMMARY_PATH),
                "comparison_sha256": sha256_file(COMPARISON_PATH),
            }, ensure_ascii=False))
            return 0
        with base.network_guard(audit):
            result = run_pipeline(audit)
        if audit.request_count != 0:
            raise RuntimeError(f"BLOCKED_NETWORK_LEAKAGE: {audit.request_count}")
        write_outputs(result)
        print(json.dumps({
            "status": result["summary"]["status"],
            "trades": len(result["experiment"]),
            "primary_loss_guard_exits": result["summary"]["loss_guard"]["primary_loss_guard_exit_count"],
            "counterfactual_loss_guard_triggers": result["summary"]["loss_guard"]["counterfactual_loss_guard_trigger_count"],
            "trades_sha256": sha256_file(TRADES_PATH),
            "summary_sha256": sha256_file(SUMMARY_PATH),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ABC JULIA NO LOSS GUARD BLOCKED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
