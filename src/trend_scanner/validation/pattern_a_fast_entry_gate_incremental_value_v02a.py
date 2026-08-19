"""Pattern A Entry Gate Incremental Value v0.2A Evaluation Module.

Evaluates:
  Primary Question:
    "Does Pattern A Stage Gate (TRANSITION / EARLY_TREND) at the FIRST FAST v0.1 qualifying signal
     discriminate forward outcome (4W, 8W, 12W, 26W Return, MFE, MAE) compared to Gate Reject?"
  Secondary Question:
    "For Gate Rejected FAST signals that later qualified for Combined Entry, did the waiting period
     avoid drawdown (loss avoidance) or miss an initial surge (opportunity cost)?"

Strict Rules:
  - Local cache only (zero external network requests).
  - PIT evaluation anchored on FIRST FAST v0.1 qualifying signal per ticker.
  - Next local trading day OPEN hypothetical execution.
  - No Exit policy interference in Primary evaluation.
  - No parameter sweeps or threshold re-tuning.
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
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

logger = logging.getLogger(__name__)

DATA_CUTOFF = pd.Timestamp("2026-08-14")
HORIZONS = [4, 8, 12, 26]


@dataclass
class FastGateSignalRecord:
    ticker: str
    name: str
    market: str
    fast_signal_date: str
    fast_execution_date: str
    fast_entry_open: float
    fast_stage: str
    fast_monthly_regime: str
    daily_risk: str
    fast_score: float | None
    fast_score_status: str
    pattern_a_stage_at_fast_signal: str
    gate_group: str
    gate_pass: bool

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

    later_combined_qualified: bool
    later_combined_signal_date: str | None
    later_combined_execution_date: str | None
    later_combined_open: float | None
    combined_entry_delay_days: int | None
    waiting_period_return_pct: float | None
    waiting_mfe_pct: float | None
    waiting_mae_pct: float | None

    evaluation_status: str
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickerGateDiagnostic:
    ticker: str
    name: str
    market: str
    evaluation_status: str
    fast_qualified: bool
    fast_first_signal_date: str | None
    fast_first_pa_stage: str | None
    fast_executable: bool
    non_executable_reason: str | None
    gate_pass: bool | None
    gate_group: str | None
    later_combined_qualified: bool
    later_combined_signal_date: str | None
    entry_delay_days: int | None
    warning_count: int
    first_exception_type: str | None
    first_exception_message: str | None


def simulate_ticker_gate_incremental_value(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> tuple[TickerGateDiagnostic, FastGateSignalRecord | None]:
    """Simulate FAST first signal and evaluate Pattern A Gate incremental value."""
    if daily is None or daily.empty:
        diag = TickerGateDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="CACHE_MISSING",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            gate_pass=None,
            gate_group=None,
            later_combined_qualified=False,
            later_combined_signal_date=None,
            entry_delay_days=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns):
        diag = TickerGateDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INVALID_OHLCV",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            gate_pass=None,
            gate_group=None,
            later_combined_qualified=False,
            later_combined_signal_date=None,
            entry_delay_days=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    if len(daily) < 60:
        diag = TickerGateDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INSUFFICIENT_HISTORY",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            gate_pass=None,
            gate_group=None,
            later_combined_qualified=False,
            later_combined_signal_date=None,
            entry_delay_days=None,
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

    later_combined_w: pd.Timestamp | None = None
    later_combined_res: dict | None = None

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

            if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"} and later_combined_w is None:
                later_combined_w = w
                later_combined_res = res
        except Exception as e:
            warning_count += 1
            if first_ex_type is None:
                first_ex_type = type(e).__name__
                first_ex_msg = str(e)

    if fast_first_w is None or fast_first_res is None:
        diag = TickerGateDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="ELIGIBLE",
            fast_qualified=False,
            fast_first_signal_date=None,
            fast_first_pa_stage=None,
            fast_executable=False,
            non_executable_reason=None,
            gate_pass=None,
            gate_group=None,
            later_combined_qualified=False,
            later_combined_signal_date=None,
            entry_delay_days=None,
            warning_count=warning_count,
            first_exception_type=first_ex_type,
            first_exception_message=first_ex_msg,
        )
        return diag, None

    # Determine Gate Cohort for FIRST FAST signal
    gate_pass = bool(fast_first_pa_stage in {"TRANSITION", "EARLY_TREND"})
    if fast_first_pa_stage == "TRANSITION":
        gate_group = "PASS_TRANSITION"
    elif fast_first_pa_stage == "EARLY_TREND":
        gate_group = "PASS_EARLY_TREND"
    elif fast_first_pa_stage == "WEAK":
        gate_group = "REJECT_WEAK"
    elif fast_first_pa_stage == "BASE":
        gate_group = "REJECT_BASE"
    elif fast_first_pa_stage == "PROGRESSED":
        gate_group = "REJECT_PROGRESSED"
    else:
        gate_group = "REJECT_UNAVAILABLE"

    # Execution check for FIRST FAST signal
    fut_daily = daily[(daily.index > fast_first_w) & (daily.index <= cutoff_date)]
    if fut_daily.empty:
        diag = TickerGateDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="ELIGIBLE",
            fast_qualified=True,
            fast_first_signal_date=fast_first_w.strftime("%Y-%m-%d"),
            fast_first_pa_stage=fast_first_pa_stage,
            fast_executable=False,
            non_executable_reason="NO_NEXT_TRADING_DAY_BEFORE_CUTOFF",
            gate_pass=gate_pass,
            gate_group=gate_group,
            later_combined_qualified=later_combined_w is not None,
            later_combined_signal_date=later_combined_w.strftime("%Y-%m-%d") if later_combined_w else None,
            entry_delay_days=(later_combined_w - fast_first_w).days if later_combined_w else None,
            warning_count=warning_count,
            first_exception_type=first_ex_type,
            first_exception_message=first_ex_msg,
        )
        return diag, None

    fast_exec_d = fut_daily.index[0]
    fast_entry_open = float(fut_daily.iloc[0]["open"])

    delay_days = (later_combined_w - fast_first_w).days if later_combined_w else None

    diag = TickerGateDiagnostic(
        ticker=ticker,
        name=name,
        market=market,
        evaluation_status="ELIGIBLE",
        fast_qualified=True,
        fast_first_signal_date=fast_first_w.strftime("%Y-%m-%d"),
        fast_first_pa_stage=fast_first_pa_stage,
        fast_executable=True,
        non_executable_reason=None,
        gate_pass=gate_pass,
        gate_group=gate_group,
        later_combined_qualified=later_combined_w is not None,
        later_combined_signal_date=later_combined_w.strftime("%Y-%m-%d") if later_combined_w else None,
        entry_delay_days=delay_days,
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
            returns[f"return_{h}w"] = round(((target_c - fast_entry_open) / fast_entry_open) * 100, 2)
            per_daily = daily[(daily.index >= fast_exec_d) & (daily.index <= target_w)]
            max_h = float(per_daily["high"].max())
            mfes[f"mfe_{h}w"] = round(((max_h - fast_entry_open) / fast_entry_open) * 100, 2)
            min_l = float(per_daily["low"].min())
            maes[f"mae_{h}w"] = round(((min_l - fast_entry_open) / fast_entry_open) * 100, 2)
            statuses[f"status_{h}w"] = "COMPLETED"
        else:
            returns[f"return_{h}w"] = None
            mfes[f"mfe_{h}w"] = None
            maes[f"mae_{h}w"] = None
            statuses[f"status_{h}w"] = "CENSORED"

    # Secondary Waiting Period Diagnostic
    later_comb_sig_date_str: str | None = None
    later_comb_exec_date_str: str | None = None
    later_comb_open: float | None = None
    wait_ret: float | None = None
    wait_mfe: float | None = None
    wait_mae: float | None = None

    if not gate_pass:
        if later_combined_w is not None:
            later_comb_sig_date_str = later_combined_w.strftime("%Y-%m-%d")
            fut_comb = daily[(daily.index > later_combined_w) & (daily.index <= cutoff_date)]
            if not fut_comb.empty:
                later_comb_exec_d = fut_comb.index[0]
                later_comb_exec_date_str = later_comb_exec_d.strftime("%Y-%m-%d")
                later_comb_open = float(fut_comb.iloc[0]["open"])
                wait_ret = round(((later_comb_open - fast_entry_open) / fast_entry_open) * 100, 2)

                wait_daily = daily[(daily.index >= fast_exec_d) & (daily.index < later_comb_exec_d)]
                if not wait_daily.empty:
                    wait_h = float(max(wait_daily["high"].tolist() + [later_comb_open]))
                    wait_l = float(min(wait_daily["low"].tolist() + [later_comb_open]))
                else:
                    wait_h = float(max(fast_entry_open, later_comb_open))
                    wait_l = float(min(fast_entry_open, later_comb_open))
                wait_mfe = round(((wait_h - fast_entry_open) / fast_entry_open) * 100, 2)
                wait_mae = round(((wait_l - fast_entry_open) / fast_entry_open) * 100, 2)
    else:
        # For Gate Pass, waiting period is 0 (immediate execution)
        later_comb_sig_date_str = fast_first_w.strftime("%Y-%m-%d")
        later_comb_exec_date_str = fast_exec_d.strftime("%Y-%m-%d")
        later_comb_open = fast_entry_open
        delay_days = 0
        wait_ret = 0.0
        wait_mfe = 0.0
        wait_mae = 0.0

    fast_score = fast_first_res.get("fast_score")
    fast_score_avail = fast_first_res.get("fast_score_status", "UNKNOWN")
    daily_risk = fast_first_res.get("fast_daily_risk_state", "UNKNOWN")
    monthly_regime = fast_first_res.get("fast_monthly_permission_state", "UNKNOWN")

    record = FastGateSignalRecord(
        ticker=ticker,
        name=name,
        market=market,
        fast_signal_date=fast_first_w.strftime("%Y-%m-%d"),
        fast_execution_date=fast_exec_d.strftime("%Y-%m-%d"),
        fast_entry_open=round(fast_entry_open, 2),
        fast_stage="TRIGGER",
        fast_monthly_regime=monthly_regime,
        daily_risk=daily_risk,
        fast_score=round(fast_score, 2) if fast_score is not None else None,
        fast_score_status=fast_score_avail,
        pattern_a_stage_at_fast_signal=fast_first_pa_stage or "UNAVAILABLE",
        gate_group=gate_group,
        gate_pass=gate_pass,
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
        later_combined_qualified=later_combined_w is not None,
        later_combined_signal_date=later_comb_sig_date_str,
        later_combined_execution_date=later_comb_exec_date_str,
        later_combined_open=round(later_comb_open, 2) if later_comb_open is not None else None,
        combined_entry_delay_days=delay_days,
        waiting_period_return_pct=wait_ret,
        waiting_mfe_pct=wait_mfe,
        waiting_mae_pct=wait_mae,
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
