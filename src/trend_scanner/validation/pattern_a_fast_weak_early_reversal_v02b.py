"""FAST + Pattern A WEAK Early Reversal Validation v0.2B Module.

Evaluates:
  Primary Question:
    "Does FAST TRIGGER occurring when Pattern A is WEAK capture early bottom reversals
     with superior long-term forward outcomes (Return, MFE, MAE) compared to TRANSITION?"
  Secondary Diagnostics:
    - Post-entry lifecycle follow-through (ever TRANSITION, EARLY_TREND, PROGRESSED and lead times).
    - Winner tail (>=20%, >=50%, >=100% Return and MFE) vs Failure tail (<=-20%, <=-30% Return and MAE).
    - Era distribution (2016-2020, 2021-2023, 2024-2026) and Market distribution (KOSPI vs KOSDAQ).
    - Risk Grade cross-tabs (NORMAL vs ELEVATED).

Strict Invariants:
  - Local cache only (zero external network requests).
  - PIT evaluation anchored on FIRST FAST v0.1 qualifying signal per ticker.
  - Next local trading day OPEN execution.
  - Zero Exit policy interference in Primary evaluation.
  - Research evaluation only (PRODUCTION_HOLD, zero production impact).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

logger = logging.getLogger(__name__)

DATA_CUTOFF = pd.Timestamp("2026-08-14")
HORIZONS = [4, 8, 12, 26]


@dataclass
class FastWeakSignalRecord:
    ticker: str
    name: str
    market: str
    fast_signal_date: str
    fast_execution_date: str
    entry_open: float
    fast_score: float | None
    fast_score_status: str
    daily_risk: str
    monthly_permission: str
    pattern_a_stage_at_signal: str
    research_cohort: str

    return_4w: float | None
    return_8w: float | None
    return_12w: float | None
    return_26w: float | None

    mfe_4w: float | None
    mfe_8w: float | None
    mfe_12w: float | None
    mfe_26w: float | None

    mae_4w: float | None
    mae_8w: float | None
    mae_12w: float | None
    mae_26w: float | None

    status_4w: str
    status_8w: str
    status_12w: str
    status_26w: str

    ever_transition: bool
    first_transition_date: str | None
    days_to_transition: int | None

    ever_early_trend: bool
    first_early_trend_date: str | None
    days_to_early_trend: int | None

    ever_progressed: bool
    first_progressed_date: str | None
    days_to_progressed: int | None

    evaluation_status: str
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickerWeakDiagnostic:
    ticker: str
    name: str
    market: str
    evaluation_status: str
    fast_qualified: bool
    fast_first_signal_date: str | None
    fast_first_pa_stage: str | None
    fast_executable: bool
    non_executable_reason: str | None
    research_cohort: str | None
    warning_count: int
    first_exception_type: str | None
    first_exception_message: str | None


def simulate_ticker_weak_early_reversal(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> tuple[TickerWeakDiagnostic, FastWeakSignalRecord | None]:
    """Simulate FAST first signal and track post-entry Pattern A lifecycle."""
    if daily is None or daily.empty:
        diag = TickerWeakDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="CACHE_MISSING",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            research_cohort=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns):
        diag = TickerWeakDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INVALID_OHLCV",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            research_cohort=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    if len(daily) < 60:
        diag = TickerWeakDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INSUFFICIENT_HISTORY",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            research_cohort=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    weekly_bars = to_weekly(daily)
    valid_weeks = [
        w for w in weekly_bars.index
        if daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]

    fast_first_w: pd.Timestamp | None = None
    fast_first_res: dict | None = None
    fast_first_pa_stage: str | None = None

    warning_count = 0
    first_ex_type: str | None = None
    first_ex_msg: str | None = None

    for w in valid_weeks:
        try:
            res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
            is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
            is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
            is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
            is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
            is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)

            raw_stage = res.get("pattern_a_stage")
            pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

            if is_fast and fast_first_w is None:
                fast_first_w = w
                fast_first_res = res
                fast_first_pa_stage = pa_stage
                break
        except Exception as e:
            warning_count += 1
            if first_ex_type is None:
                first_ex_type = type(e).__name__
                first_ex_msg = str(e)

    if fast_first_w is None or fast_first_res is None:
        diag = TickerWeakDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="ELIGIBLE",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            research_cohort=None,
            warning_count=warning_count,
            first_exception_type=first_ex_type,
            first_exception_message=first_ex_msg,
        )
        return diag, None

    # Research Cohort
    if fast_first_pa_stage == "WEAK":
        research_cohort = "FAST_WEAK"
    elif fast_first_pa_stage == "TRANSITION":
        research_cohort = "FAST_TRANSITION"
    elif fast_first_pa_stage == "EARLY_TREND":
        research_cohort = "FAST_EARLY_TREND"
    elif fast_first_pa_stage == "BASE":
        research_cohort = "FAST_BASE"
    elif fast_first_pa_stage == "PROGRESSED":
        research_cohort = "FAST_PROGRESSED"
    else:
        research_cohort = "FAST_UNAVAILABLE"

    # Execution check for FIRST FAST signal
    fut_daily = daily[(daily.index > fast_first_w) & (daily.index <= cutoff_date)]
    if fut_daily.empty:
        diag = TickerWeakDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="ELIGIBLE",
            fast_qualified=True,
            fast_first_signal_date=fast_first_w.strftime("%Y-%m-%d"),
            fast_first_pa_stage=fast_first_pa_stage,
            fast_executable=False,
            non_executable_reason="NO_NEXT_TRADING_DAY_BEFORE_CUTOFF",
            research_cohort=research_cohort,
            warning_count=warning_count,
            first_exception_type=first_ex_type,
            first_exception_message=first_ex_msg,
        )
        return diag, None

    fast_exec_d = fut_daily.index[0]
    entry_open = float(fut_daily.iloc[0]["open"])

    diag = TickerWeakDiagnostic(
        ticker=ticker,
        name=name,
        market=market,
        evaluation_status="ELIGIBLE",
        fast_qualified=True,
        fast_first_signal_date=fast_first_w.strftime("%Y-%m-%d"),
        fast_first_pa_stage=fast_first_pa_stage,
        fast_executable=True,
        non_executable_reason=None,
        research_cohort=research_cohort,
        warning_count=warning_count,
        first_exception_type=first_ex_type,
        first_exception_message=first_ex_msg,
    )

    # Calculate Forward Horizon metrics from FAST hypothetical entry open
    fut_weeks = [
        fw for fw in weekly_bars.index
        if fw > fast_first_w and fw <= cutoff_date and daily[daily.index <= fw].index.max().normalize() == fw.normalize()
    ]

    returns: dict[str, float | None] = {}
    mfes: dict[str, float | None] = {}
    maes: dict[str, float | None] = {}
    statuses: dict[str, str] = {}

    for h in HORIZONS:
        if len(fut_weeks) >= h:
            target_w = fut_weeks[h - 1]
            target_c = float(daily.loc[target_w, "close"])
            returns[f"return_{h}w"] = round(((target_c - entry_open) / entry_open) * 100, 2)
            per_daily = daily[(daily.index >= fast_exec_d) & (daily.index <= target_w)]
            max_h = float(per_daily["high"].max())
            mfes[f"mfe_{h}w"] = round(((max_h - entry_open) / entry_open) * 100, 2)
            min_l = float(per_daily["low"].min())
            maes[f"mae_{h}w"] = round(((min_l - entry_open) / entry_open) * 100, 2)
            statuses[f"status_{h}w"] = "COMPLETED"
        else:
            returns[f"return_{h}w"] = None
            mfes[f"mfe_{h}w"] = None
            maes[f"mae_{h}w"] = None
            statuses[f"status_{h}w"] = "CENSORED"

    # Trace post-entry completed monthly PIT Pattern A snapshots
    monthly_bars = to_monthly(daily)
    m_dates = [
        m for m in monthly_bars.index
        if m >= fast_first_w and m <= cutoff_date
    ]

    ever_trans = False
    first_trans_d: pd.Timestamp | None = None
    ever_early = False
    first_early_d: pd.Timestamp | None = None
    ever_prog = False
    first_prog_d: pd.Timestamp | None = None

    for m in m_dates:
        try:
            snap = build_historical_snapshot(ticker, name, daily[daily.index <= m], m, include_incomplete_periods=False)
            eval_res = evaluate_pattern_a(snap)
            st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"

            if st == "TRANSITION" and not ever_trans:
                ever_trans = True
                first_trans_d = m
            if st == "EARLY_TREND" and not ever_early:
                ever_early = True
                first_early_d = m
            if st == "PROGRESSED" and not ever_prog:
                ever_prog = True
                first_prog_d = m
        except Exception as e:
            warning_count += 1
            if first_ex_type is None:
                first_ex_type = type(e).__name__
                first_ex_msg = str(e)

    days_trans = (first_trans_d - fast_first_w).days if first_trans_d else None
    days_early = (first_early_d - fast_first_w).days if first_early_d else None
    days_prog = (first_prog_d - fast_first_w).days if first_prog_d else None

    fast_score = fast_first_res.get("fast_score")
    fast_score_avail = fast_first_res.get("fast_score_status", "UNKNOWN")
    daily_risk = fast_first_res.get("fast_daily_risk_state", "UNKNOWN")
    monthly_regime = fast_first_res.get("fast_monthly_permission_state", "UNKNOWN")

    record = FastWeakSignalRecord(
        ticker=ticker,
        name=name,
        market=market,
        fast_signal_date=fast_first_w.strftime("%Y-%m-%d"),
        fast_execution_date=fast_exec_d.strftime("%Y-%m-%d"),
        entry_open=round(entry_open, 2),
        fast_score=round(fast_score, 2) if fast_score is not None else None,
        fast_score_status=fast_score_avail,
        daily_risk=daily_risk,
        monthly_permission=monthly_regime,
        pattern_a_stage_at_signal=fast_first_pa_stage or "UNAVAILABLE",
        research_cohort=research_cohort,
        return_4w=returns["return_4w"],
        return_8w=returns["return_8w"],
        return_12w=returns["return_12w"],
        return_26w=returns["return_26w"],
        mfe_4w=mfes["mfe_4w"],
        mfe_8w=mfes["mfe_8w"],
        mfe_12w=mfes["mfe_12w"],
        mfe_26w=mfes["mfe_26w"],
        mae_4w=maes["mae_4w"],
        mae_8w=maes["mae_8w"],
        mae_12w=maes["mae_12w"],
        mae_26w=maes["mae_26w"],
        status_4w=statuses["status_4w"],
        status_8w=statuses["status_8w"],
        status_12w=statuses["status_12w"],
        status_26w=statuses["status_26w"],
        ever_transition=ever_trans,
        first_transition_date=first_trans_d.strftime("%Y-%m-%d") if first_trans_d else None,
        days_to_transition=days_trans,
        ever_early_trend=ever_early,
        first_early_trend_date=first_early_d.strftime("%Y-%m-%d") if first_early_d else None,
        days_to_early_trend=days_early,
        ever_progressed=ever_prog,
        first_progressed_date=first_prog_d.strftime("%Y-%m-%d") if first_prog_d else None,
        days_to_progressed=days_prog,
        evaluation_status="ELIGIBLE",
        warning_count=warning_count,
    )

    return diag, record


def calculate_distribution_stats(series: pd.Series) -> dict[str, Any]:
    usable = series.dropna().astype(float)
    if usable.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "std": None,
            "min": None,
            "max": None,
            "positive_rate": None,
        }
    pos_rate = float((usable > 0).mean() * 100)
    return {
        "count": int(len(usable)),
        "mean": round(float(usable.mean()), 2),
        "median": round(float(usable.median()), 2),
        "p25": round(float(np.percentile(usable, 25)), 2),
        "p75": round(float(np.percentile(usable, 75)), 2),
        "std": round(float(usable.std()), 2) if len(usable) > 1 else 0.0,
        "min": round(float(usable.min()), 2),
        "max": round(float(usable.max()), 2),
        "positive_rate": round(pos_rate, 1),
    }
