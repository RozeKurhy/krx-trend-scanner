"""Official ETF 36 Stock Report v0.6 adapter for Julia V1.

The common technical/flow sections are produced by the existing Stock Report
generator. Julia lifecycle and ETF point-in-time eligibility use exact local
raw KRX OHLCV and the frozen V00 evaluator; this module makes no network calls.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.market_calendar import MarketCalendarAuthority, load_rolling_production_market_calendar
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.filters.investability import InvestabilityEvaluationResult, InvestabilityStatus
from trend_scanner.reporting.fundamentals_report import build_fundamentals_section
from trend_scanner.reporting.models import ReportStatus
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report
from trend_scanner.universe.asset_classifier import AssetType


STRATEGY_ID = "JULIA_ETF_STRATEGY_V01"
STRATEGY_NAME = "Julia V1"
ELIGIBILITY_CONTRACT = "ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01"
UNIVERSE_REL = Path(
    "artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01/official_etf_universe_36.csv"
)
EFFECTIVE_SPAN_REL = Path(
    "artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01/effective_span_audit.csv"
)
CLEAN_READY_REL = Path(
    "artifacts/research/etf_36_zero_ohlc_sentinel_clean_eligibility_closure_v01/clean_strategy_ready_dates.csv"
)
SCORE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
)
STAGE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
)


@dataclass(frozen=True)
class ETFIdentity:
    ticker: str
    name: str
    listing_date: str
    major_category: str
    isu_cd: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_official_etf36(repo_root: Path) -> tuple[list[ETFIdentity], str]:
    """Load and validate the exact frozen 36 ETF universe."""
    import csv

    path = repo_root / UNIVERSE_REL
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    identities = [
        ETFIdentity(
            ticker=str(row["ticker"]).strip().zfill(6),
            name=str(row["name"]).strip(),
            listing_date=str(row["listing_date"]).strip()[:10],
            major_category=str(row["major_category"]).strip(),
            isu_cd=str(row["ISU_CD"]).strip(),
        )
        for row in rows
    ]
    tickers = [row.ticker for row in identities]
    isu_codes = [row.isu_cd for row in identities]
    categories = {name: sum(row.major_category == name for row in identities) for name in (
        "MARKET_INDEX", "SECTOR_INDEX", "COMMODITY_RESOURCE"
    )}
    if len(identities) != 36 or len(set(tickers)) != 36 or len(set(isu_codes)) != 36:
        raise ValueError("FROZEN_ETF36_COUNT_OR_DUPLICATE_MISMATCH")
    if categories != {"MARKET_INDEX": 12, "SECTOR_INDEX": 19, "COMMODITY_RESOURCE": 5}:
        raise ValueError(f"FROZEN_ETF36_CATEGORY_MISMATCH:{categories}")
    if "474800" in set(tickers):
        raise ValueError("FROZEN_ETF36_CONTAINS_FORBIDDEN_TICKER")
    return identities, _sha256(path)


def load_strategy_ready_dates(repo_root: Path) -> dict[str, dict[str, str]]:
    """Resolve the frozen Julia ready date and clean-ready date per ticker."""
    import csv

    with (repo_root / EFFECTIVE_SPAN_REL).open("r", encoding="utf-8-sig", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))
    with (repo_root / CLEAN_READY_REL).open("r", encoding="utf-8-sig", newline="") as handle:
        clean_rows = list(csv.DictReader(handle))

    ready_by_ticker: dict[str, set[str]] = {}
    for row in audit_rows:
        ready_by_ticker.setdefault(str(row["ticker"]).zfill(6), set()).add(
            str(row["julia_strategy_eligible_date"]).strip()[:10]
        )
    clean_by_ticker = {str(row["ticker"]).zfill(6): row for row in clean_rows}
    result: dict[str, dict[str, str]] = {}
    for ticker, values in ready_by_ticker.items():
        values.discard("")
        if len(values) != 1:
            raise ValueError(f"JULIA_READY_DATE_INCONSISTENT:{ticker}")
        existing = next(iter(values))
        clean = clean_by_ticker.get(ticker)
        if clean:
            recorded_existing = str(clean["existing_strategy_ready_date"]).strip()[:10]
            clean_ready = str(clean["clean_strategy_ready_date"]).strip()[:10]
            if recorded_existing != existing or not clean_ready:
                raise ValueError(f"CLEAN_READY_DATE_AUTHORITY_MISMATCH:{ticker}")
            if str(clean.get("sentinel_labels_remaining_at_ready", "0")).strip() not in {"", "0"}:
                raise ValueError(f"CLEAN_READY_HAS_REMAINING_SENTINELS:{ticker}")
        else:
            clean_ready = existing
        result[ticker] = {
            "strategy_ready_date": existing,
            "clean_ready_date": clean_ready,
            "effective_start_date": max(existing, clean_ready),
        }
    return result


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _normalize_raw(raw: pd.DataFrame | None, reference_market_date: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = raw.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).normalize()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.loc[frame.index <= pd.Timestamp(reference_market_date)]
    required = ("open", "high", "low", "close", "volume")
    if any(column not in frame.columns for column in required):
        return pd.DataFrame(columns=list(required))
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _calendar_dates(calendar: MarketCalendarAuthority, reference_market_date: str) -> pd.DatetimeIndex:
    # Deliberately truncate even the calendar authority to reference date. A future
    # calendar row must never make the report imply a next-session execution.
    dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    dates = dates[dates <= pd.Timestamp(reference_market_date)]
    if len(dates) == 0 or dates[-1] != pd.Timestamp(reference_market_date):
        raise ValueError("REFERENCE_MARKET_DATE_NOT_IN_CERTIFIED_KRX_CALENDAR")
    return dates


def _next_market_date(date: str, calendar_dates: pd.DatetimeIndex) -> str | None:
    position = bisect_right(list(calendar_dates), pd.Timestamp(date))
    return _iso(calendar_dates[position]) if position < len(calendar_dates) else None


def compute_etf_eligibility(
    daily_raw: pd.DataFrame,
    *,
    listing_date: str,
    effective_start_date: str,
    calendar_dates: pd.DatetimeIndex,
) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    """Compute exact per-KRX-session ETF PIT values, without filling missing rows.

    Returns metrics by session, sessions meeting all signal conditions, and the
    subset whose exact next market session raw open is locally available.
    """
    sessions = pd.DatetimeIndex(calendar_dates)
    aligned = daily_raw.reindex(sessions)
    closes = pd.to_numeric(aligned["close"], errors="coerce")
    volumes = pd.to_numeric(aligned["volume"], errors="coerce")
    rolling_count = volumes.rolling(20, min_periods=20).count()
    rolling_mean = volumes.rolling(20, min_periods=20).mean()
    listing = pd.Timestamp(listing_date)
    start = pd.Timestamp(effective_start_date)

    metrics: dict[str, dict[str, Any]] = {}
    signal_pass_dates: set[str] = set()
    executable_dates: set[str] = set()
    for position, date in enumerate(sessions):
        key = _iso(date)
        close = _finite(closes.iloc[position])
        avg_volume = _finite(rolling_mean.iloc[position]) if rolling_count.iloc[position] == 20 else None
        window_start = _iso(sessions[position - 19]) if position >= 19 and avg_volume is not None else None
        window_start_position = max(0, position - 19)
        window_count = int(volumes.iloc[window_start_position:position + 1].count())
        metrics[key] = {
            "raw_close_krw": close,
            "avg_volume_20d_shares": avg_volume,
            "volume_window_sessions": 20 if avg_volume is not None else window_count,
            "volume_window_start": window_start,
            "volume_window_end": key if avg_volume is not None else None,
            "volume_window_includes_signal_date": True,
        }

        listing_pass = date >= listing + pd.DateOffset(years=2)
        passed = (
            listing_pass
            and date >= start
            and close is not None and close >= 1000
            and avg_volume is not None and avg_volume >= 10000
        )
        if not passed:
            continue
        signal_pass_dates.add(key)
        next_date = _next_market_date(key, sessions)
        if next_date is None:
            continue
        next_ts = pd.Timestamp(next_date)
        if next_ts not in daily_raw.index:
            continue
        next_open = _finite(daily_raw.loc[next_ts, "open"])
        if next_open is not None and next_open > 0:
            executable_dates.add(key)
    return metrics, signal_pass_dates, executable_dates


def _load_contracts(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    score_path = repo_root / SCORE_CONTRACT_REL
    stage_path = repo_root / STAGE_CONTRACT_REL
    if not score_path.is_file() or not stage_path.is_file():
        raise FileNotFoundError("PATTERN_A_FAST_FROZEN_CONTRACT_MISSING")
    return (
        json.loads(score_path.read_text(encoding="utf-8")),
        json.loads(stage_path.read_text(encoding="utf-8")),
    )


def _compact_trade(trade: Any) -> dict[str, Any]:
    """Expose V00 lifecycle facts without relabeling Phase10 fields as ETF rules."""
    return {
        "trade_id": trade.trade_id,
        "trade_sequence": trade.trade_sequence,
        "entry_signal_date": trade.entry_signal_date,
        "entry_execution_date": trade.entry_execution_date,
        "entry_open_krw": trade.entry_open,
        "entry_pattern_a_stage": trade.entry_pattern_a_stage,
        "fast_stage": trade.fast_stage,
        "monthly_regime": trade.monthly_regime,
        "daily_risk": trade.daily_risk,
        "fast_score": trade.fast_score,
        "fast_score_state": trade.fast_score_state,
        "first_progressed_date": trade.first_progressed_date,
        "first_progressed_effective_trading_date": trade.first_progressed_effective_trading_date,
        "lifecycle_class": trade.lifecycle_class,
        "exit_type": trade.exit_type,
        "exit_signal_date": trade.exit_signal_date,
        "exit_execution_date": trade.exit_execution_date,
        "exit_price_krw": trade.exit_price,
        "terminal_return_pct": trade.terminal_return,
        "trade_status": trade.trade_status,
        "pre_progressed_loss_guard_triggered": False,
    }


def _strategy_section(
    *,
    identity: ETFIdentity,
    raw: pd.DataFrame,
    context: Any,
    calendar: MarketCalendarAuthority,
    calendar_dates: pd.DatetimeIndex,
    ref_date: str,
    effective_start: str,
    readiness: dict[str, str],
    metrics: dict[str, dict[str, Any]],
    signal_pass_dates: set[str],
    executable_dates: set[str],
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    support_errors: list[str],
) -> dict[str, Any]:
    import trend_scanner.validation.julia_strategy_v00 as julia
    from trend_scanner.data.resampler import to_weekly
    from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

    ticker_dates = set(raw.index)
    original_fast = julia.evaluate_pattern_a_fast
    original_snapshot = julia.build_historical_snapshot_from_context
    original_pattern_a = julia.evaluate_pattern_a
    original_investability = julia.evaluate_investability

    def fast_with_calendar(*args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs["market_calendar"] = calendar
        try:
            return original_fast(*args, **kwargs)
        except Exception as exc:
            support_errors.append(f"FAST:{type(exc).__name__}:{str(exc)[:180]}")
            raise

    def snapshot_with_calendar(*args: Any, **kwargs: Any) -> Any:
        kwargs["market_calendar"] = calendar
        try:
            return original_snapshot(*args, **kwargs)
        except Exception as exc:
            support_errors.append(f"SNAPSHOT:{type(exc).__name__}:{str(exc)[:180]}")
            raise

    def pattern_a_with_audit(snapshot: Any) -> Any:
        try:
            return original_pattern_a(snapshot)
        except Exception as exc:
            support_errors.append(f"PATTERN_A:{type(exc).__name__}:{str(exc)[:180]}")
            raise

    def etf_pit_eligibility(
        ticker: str, as_of: Any, daily: pd.DataFrame, **_kwargs: Any
    ) -> InvestabilityEvaluationResult:
        date = _iso(as_of)
        exact_close = None
        if pd.Timestamp(date) in ticker_dates:
            exact_close = _finite(daily.loc[pd.Timestamp(date), "close"])
        allowed = date in executable_dates and date >= effective_start
        return InvestabilityEvaluationResult(
            ticker=ticker,
            as_of=date,
            status=InvestabilityStatus.INVESTABLE if allowed else InvestabilityStatus.DATA_UNAVAILABLE,
            reason="ETF_PIT_ELIGIBILITY_AND_EXACT_NEXT_OPEN_PASS" if allowed else "ETF_PIT_ELIGIBILITY_OR_EXACT_NEXT_OPEN_FAIL",
            market_cap=None,
            market_cap_eok=None,
            avg_trading_value_20d=None,
            avg_trading_value_20d_eok=None,
            avg_trading_value_60d=None,
            avg_trading_value_60d_eok=None,
            close=exact_close,
            close_ready=exact_close is not None,
            market_cap_ready=False,
            trading_value_20d_ready=False,
            trading_value_60d_ready=False,
            data_ready=allowed,
            market_cap_effective_date=None,
            close_effective_date=date if exact_close is not None else None,
            tv20_last_observation_date=date if date in metrics else None,
        )

    trades: list[Any] = []
    try:
        julia.evaluate_pattern_a_fast = fast_with_calendar
        julia.build_historical_snapshot_from_context = snapshot_with_calendar
        julia.evaluate_pattern_a = pattern_a_with_audit
        julia.evaluate_investability = etf_pit_eligibility
        trades = julia.simulate_ticker_strategy_2022(
            ticker=identity.ticker,
            name=identity.name,
            market="ETF",
            daily=raw,
            score_contract=score_contract,
            stage_contract=stage_contract,
            enable_loss_guard=False,
            start_date=pd.Timestamp(effective_start),
            cutoff_date=pd.Timestamp(ref_date),
            snapshot_context=context,
            enable_pre_window_pruning=True,
        )
        if any(
            trade.strategy_id != "JULIA_STRATEGY_V00" or trade.pre_progressed_loss_guard_enabled
            for trade in trades
        ):
            raise ValueError("JULIA_V00_LIFECYCLE_OR_LOSS_GUARD_PARITY_MISMATCH")
    finally:
        julia.evaluate_pattern_a_fast = original_fast
        julia.build_historical_snapshot_from_context = original_snapshot
        julia.evaluate_pattern_a = original_pattern_a
        julia.evaluate_investability = original_investability

    completed_weeks = [
        week for week in to_weekly(raw).index
        if week <= pd.Timestamp(ref_date) and week in ticker_dates
    ]
    latest_signal_date = _iso(completed_weeks[-1]) if completed_weeks else None
    fast_point: dict[str, Any] = {}
    if latest_signal_date:
        try:
            fast_point = evaluate_pattern_a_fast(
                identity.ticker,
                identity.name,
                raw,
                pd.Timestamp(latest_signal_date),
                score_contract,
                stage_contract,
                context=context,
                market_calendar=calendar,
            )
        except Exception as exc:
            support_errors.append(f"CURRENT_FAST:{type(exc).__name__}:{str(exc)[:180]}")

    active_trade = trades[-1] if trades and trades[-1].trade_status == "OPEN_AT_CUTOFF" else None
    canonical_position = "OPEN" if active_trade is not None else "FLAT"
    if active_trade is None:
        state, action, reason, timing = "WAIT", "WAIT", "NO_OPEN_POSITION", None
    elif active_trade.exit_signal_date and pd.Timestamp(active_trade.exit_signal_date) <= pd.Timestamp(ref_date):
        state, action, reason, timing = "EXIT", "EXIT_NEXT_OPEN", "EXIT_SIGNAL_PENDING_NEXT_KRX_OPEN", "NEXT_ACTUAL_KRX_SESSION_OPEN"
    elif active_trade.first_progressed_date and pd.Timestamp(active_trade.first_progressed_date) <= pd.Timestamp(ref_date):
        state, action, reason, timing = "HOLD_PROGRESSED", "HOLD", "OPEN_POSITION_PROGRESSED", None
    else:
        state, action, reason, timing = "HOLD_PRE_PROGRESSED", "HOLD", "OPEN_POSITION_PRE_PROGRESSED", None

    signal_metrics = metrics.get(latest_signal_date or "", {})
    signal_close = signal_metrics.get("raw_close_krw")
    signal_avg_volume = signal_metrics.get("avg_volume_20d_shares")
    signal_ts = pd.Timestamp(latest_signal_date) if latest_signal_date else None
    listing_pass = bool(signal_ts is not None and signal_ts >= pd.Timestamp(identity.listing_date) + pd.DateOffset(years=2))
    signal_start_pass = bool(signal_ts is not None and signal_ts >= pd.Timestamp(effective_start))
    close_pass = signal_close is not None and signal_close >= 1000
    volume_pass = signal_avg_volume is not None and signal_avg_volume >= 10000
    pit_pass = bool(
        latest_signal_date
        and latest_signal_date in signal_pass_dates
        and listing_pass and signal_start_pass and close_pass and volume_pass
    )
    next_signal_date = _next_market_date(latest_signal_date, calendar_dates) if latest_signal_date else None
    next_open = None
    if next_signal_date and pd.Timestamp(next_signal_date) in ticker_dates:
        next_open = _finite(raw.loc[pd.Timestamp(next_signal_date), "open"])
    next_open_pass = bool(
        latest_signal_date
        and latest_signal_date in executable_dates
        and next_signal_date is not None
        and next_open is not None
    )
    pa_stage = str(fast_point.get("pattern_a_stage") or "UNAVAILABLE").upper()
    fast_stage = fast_point.get("fast_machine_stage")
    fast_stage_status = fast_point.get("fast_machine_stage_status")
    monthly_regime = fast_point.get("fast_monthly_permission_state")
    daily_risk = fast_point.get("fast_daily_risk_state")
    fast_score_state = fast_point.get("fast_score_status")
    pa_pass = pa_stage in {"TRANSITION", "EARLY_TREND"}
    fast_pass = fast_stage == "TRIGGER" and fast_stage_status == "READY"
    regime_pass = monthly_regime == "PERMITTED_REGIME"
    risk_pass = daily_risk in {"NORMAL", "ELEVATED"}
    score_pass = fast_score_state in {"READY", "PARTIAL"}
    no_open = active_trade is None
    signal_is_current = bool(latest_signal_date and latest_signal_date == ref_date)
    failed = []
    for passed, code in (
        (True, "OFFICIAL_ETF36"),
        (listing_pass, "LISTED_AT_LEAST_TWO_YEARS"),
        (close_pass, "RAW_CLOSE_GE_1000"),
        (volume_pass, "RAW_VOLUME_20D_AVG_GE_10000"),
        (signal_start_pass, "STRATEGY_AND_CLEAN_READY"),
        (pa_pass, "PATTERN_A_TRANSITION_OR_EARLY_TREND"),
        (fast_pass, "FAST_TRIGGER_READY"),
        (regime_pass, "MONTHLY_REGIME_PERMITTED"),
        (risk_pass, "DAILY_RISK_ALLOWED"),
        (score_pass, "FAST_SCORE_READY_OR_PARTIAL"),
        (no_open, "NO_OPEN_POSITION"),
        (signal_is_current, "SIGNAL_DATE_IS_CURRENT_REFERENCE"),
        (next_open_pass, "EXACT_NEXT_KRX_OPEN_AVAILABLE"),
    ):
        if not passed:
            failed.append(code)
    entry_all = not failed

    current_raw = raw.loc[pd.Timestamp(ref_date)] if pd.Timestamp(ref_date) in ticker_dates else None
    current_close = _finite(current_raw["close"]) if current_raw is not None else None
    current_trade: dict[str, Any] | None = None
    protection_state: dict[str, Any] | None = None
    if active_trade is not None:
        current_return = (
            round((current_close / active_trade.entry_open - 1) * 100, 2)
            if current_close is not None and active_trade.entry_open else None
        )
        current_trade = {
            **_compact_trade(active_trade),
            "current_close_krw": current_close,
            "current_return_pct": current_return,
            "current_close_date": ref_date if current_close is not None else None,
            "pending_exit": bool(active_trade.exit_signal_date),
        }
        progressed = state in {"HOLD_PROGRESSED", "EXIT"} and bool(active_trade.first_progressed_date)
        protection_state = {
            "phase": "PROGRESSED" if progressed else "PRE_PROGRESSED",
            "loss_guard_state": "DISABLED",
            "loss_guard_threshold_pct": None,
            "first_progressed_date": active_trade.first_progressed_date,
            "lifecycle_class": active_trade.lifecycle_class,
            "exit3_state": "EXIT_PENDING" if str(active_trade.exit_type).startswith("EXIT3_") else "MONITORING",
            "exit4_state": "EXIT_PENDING" if active_trade.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15" else "MONITORING",
        }

    trade_history = [_compact_trade(trade) for trade in trades]
    for index, trade in enumerate(trades):
        if trade.trade_status == "OPEN_AT_CUTOFF":
            if pd.Timestamp(ref_date) in ticker_dates:
                exact_close = _finite(raw.loc[pd.Timestamp(ref_date), "close"])
                trade_history[index]["terminal_return_pct"] = (
                    round((exact_close / trade.entry_open - 1) * 100, 2)
                    if exact_close is not None and trade.entry_open else None
                )
            else:
                trade_history[index]["terminal_return_pct"] = None
    current_eligibility = metrics.get(ref_date, {})
    if state == "EXIT":
        interpretation = "Julia V1 청산 조건이 발생했어. 다음 실제 KRX 거래일의 정확한 시가 체결을 기다려야 해."
    elif state == "HOLD_PROGRESSED":
        interpretation = "Julia V1 포지션을 PROGRESSED 구간에서 보유 중이야. Pre-PROGRESSED Loss Guard는 비활성이야."
    elif state == "HOLD_PRE_PROGRESSED":
        interpretation = "Julia V1 포지션을 PROGRESSED 이전 구간에서 보유 중이야. Pre-PROGRESSED Loss Guard는 비활성이야."
    else:
        interpretation = "Julia V1의 현재 보유 포지션은 없어. 다음 진입은 완료된 주봉 신호와 exact KRX PIT·익일 시가 조건이 모두 확인돼야 해."

    ready_date = readiness["strategy_ready_date"]
    clean_date = readiness["clean_ready_date"]
    completed_count = sum(trade.trade_status == "REALIZED" for trade in trades)
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "strategy_version": "V1",
        "asset_scope": "OFFICIAL_ETF_36",
        "applicability": "APPLICABLE",
        "strategy_state": state,
        "canonical_position": canonical_position,
        "action": action,
        "action_reason": reason,
        "execution_timing": timing,
        "entry_conditions": {
            "signal_date": latest_signal_date,
            "official_etf36_membership": True,
            "eligibility_contract": ELIGIBILITY_CONTRACT,
            "listing_date": identity.listing_date,
            "listing_age_pass": listing_pass,
            "raw_close_krw": signal_close,
            "minimum_raw_close_krw": 1000,
            "raw_close_pass": bool(close_pass),
            "avg_volume_20d_shares": signal_avg_volume,
            "volume_window_sessions": signal_metrics.get("volume_window_sessions"),
            "volume_window_start": signal_metrics.get("volume_window_start"),
            "volume_window_end": signal_metrics.get("volume_window_end"),
            "volume_window_includes_signal_date": True,
            "minimum_avg_volume_20d_shares": 10000,
            "volume_pass": bool(volume_pass),
            "pit_eligibility_pass": pit_pass,
            "strategy_ready_date": ready_date,
            "clean_ready_date": clean_date,
            "effective_start_date": effective_start,
            "strategy_ready_pass": signal_start_pass,
            "pattern_a_stage": pa_stage,
            "pattern_a_stage_pass": pa_pass,
            "fast_stage": fast_stage,
            "fast_stage_status": fast_stage_status,
            "fast_trigger_pass": fast_pass,
            "monthly_regime": monthly_regime,
            "monthly_regime_pass": regime_pass,
            "daily_risk": daily_risk,
            "daily_risk_pass": risk_pass,
            "fast_score_state": fast_score_state,
            "fast_score_pass": score_pass,
            "no_open_position": no_open,
            "signal_date_is_current_reference": signal_is_current,
            "next_krx_session_date": next_signal_date,
            "next_open_raw_krw": next_open,
            "exact_next_open_available": next_open_pass,
            "all_conditions_met": entry_all,
            "failed_conditions": failed,
        },
        "current_trade": current_trade,
        "protection_state": protection_state,
        "reentry_state": {
            "enabled": True,
            "cooldown": "NONE",
            "maximum_reentries": "NONE",
            "completed_trade_count": completed_count,
            "current_trade_sequence": active_trade.trade_sequence if active_trade else None,
            "next_entry_sequence": (active_trade.trade_sequence + 1) if active_trade else (trades[-1].trade_sequence + 1 if trades else 1),
        },
        "trade_history": trade_history,
        "interpretation": interpretation,
        "eligibility_contract": ELIGIBILITY_CONTRACT,
        "provenance": {
            "evaluator_id": "JULIA_STRATEGY_V00",
            "loss_guard_enabled": False,
            "data_source": "KRX_RAW_ETF_OHLCV",
            "reference_market_date": ref_date,
            "strategy_ready_date": ready_date,
            "clean_ready_date": clean_date,
            "network_requests": 0,
            "support_evaluator_errors": list(support_errors),
        },
        "current_snapshot": {
            "as_of": ref_date,
            "official_etf36_membership": True,
            "listing_date": identity.listing_date,
            "listing_age_pass": bool(pd.Timestamp(ref_date) >= pd.Timestamp(identity.listing_date) + pd.DateOffset(years=2)),
            "raw_close_krw": current_eligibility.get("raw_close_krw"),
            "minimum_raw_close_krw": 1000,
            "raw_close_pass": bool(current_eligibility.get("raw_close_krw") is not None and current_eligibility["raw_close_krw"] >= 1000),
            "avg_volume_20d_shares": current_eligibility.get("avg_volume_20d_shares"),
            "volume_window_sessions": current_eligibility.get("volume_window_sessions"),
            "volume_window_start": current_eligibility.get("volume_window_start"),
            "volume_window_end": current_eligibility.get("volume_window_end"),
            "volume_window_includes_signal_date": True,
            "minimum_avg_volume_20d_shares": 10000,
            "volume_pass": bool(current_eligibility.get("avg_volume_20d_shares") is not None and current_eligibility["avg_volume_20d_shares"] >= 10000),
            "eligibility_pass": ref_date in signal_pass_dates,
            "eligibility_contract": ELIGIBILITY_CONTRACT,
            "strategy_ready_date": ready_date,
            "clean_ready_date": clean_date,
            "effective_start_date": effective_start,
            "market_cap_applicability": "NOT_APPLICABLE_TO_JULIA_ETF_ELIGIBILITY",
            "phase10_investability_applicability": "NOT_APPLICABLE",
        },
    }


def _readiness_status(
    *,
    raw: pd.DataFrame,
    reference_date: str,
    metrics: dict[str, dict[str, Any]],
    strategy: dict[str, Any],
    base_report: Any,
) -> tuple[str, str]:
    if raw.empty or len(raw) < 60:
        return "DATA_UNAVAILABLE", "RAW_HISTORY_MISSING_OR_LT_60_SESSIONS"
    reasons: list[str] = []
    snapshot = metrics.get(reference_date, {})
    current_complete = (
        snapshot.get("raw_close_krw") is not None
        and snapshot.get("avg_volume_20d_shares") is not None
    )
    if not current_complete:
        reasons.append("CURRENT_RAW_CLOSE_OR_VOLUME_WINDOW_INCOMPLETE")
    if strategy["provenance"]["support_evaluator_errors"]:
        reasons.append("JULIA_EVALUATOR_SUPPORT_ERRORS")

    if base_report.current_snapshot.pattern_a_score is None or base_report.data_quality.quality_status != "OK":
        reasons.append("PATTERN_A_OR_DATA_QUALITY_UNAVAILABLE")
    if base_report.pattern_a_fast.current.stage_availability == "UNAVAILABLE":
        reasons.append("PATTERN_A_FAST_UNAVAILABLE")
    if base_report.foreign_flow.data_status != "READY":
        reasons.append(f"FOREIGN_FLOW_{base_report.foreign_flow.data_status}")
    if base_report.relative_strength.data_status not in {"READY", "NOT_APPLICABLE"}:
        reasons.append(f"MARKET_RS_{base_report.relative_strength.data_status}")
    if base_report.sector_relative_strength.data_status not in {"READY", "NOT_APPLICABLE"}:
        reasons.append(f"SECTOR_RS_{base_report.sector_relative_strength.data_status}")
    if getattr(base_report.trading_value_flow.trading_value_state, "value", base_report.trading_value_flow.trading_value_state) == "TRADING_VALUE_UNAVAILABLE":
        reasons.append("TRADING_VALUE_UNAVAILABLE")
    if not reasons:
        return "READY", "RAW_PIT_JULIA_AND_APPLICABLE_COMMON_SECTIONS_READY"
    return "PARTIAL", ";".join(dict.fromkeys(reasons))


def _strategy_bullet(strategy: dict[str, Any]) -> str:
    return f"Julia V1: {strategy['strategy_state']}"


def _render_strategy_markdown(report_dict: dict[str, Any]) -> str:
    strategy = report_dict["official_strategy"]
    conditions = strategy["entry_conditions"]
    lines = [
        "## 2. Julia V1 전략 상태",
        f"- **전략 ID**: `{strategy['strategy_id']}`",
        f"- **전략 상태**: `{strategy['strategy_state']}`",
        f"- **전략 포지션**: `{strategy['canonical_position']}`",
        f"- **현재 행동**: `{strategy['action']}`",
        f"- **행동 사유**: `{strategy['action_reason']}`",
        f"- **실행 시점**: `{strategy['execution_timing'] or '해당 없음'}`",
        f"- **해석**: {strategy['interpretation']}",
        "",
        "### ETF 진입 조건 체크리스트",
        "| 진입 검증 항목 | 기준일 관측값 | 충족 여부 |",
        "|---|---|:---:|",
        f"| Official ETF36 | `{conditions['official_etf36_membership']}` | `PASS` |",
        f"| 상장 2년 이상 | `{conditions['listing_date']}` | `{'PASS' if conditions['listing_age_pass'] else 'FAIL'}` |",
        f"| raw 종가 ≥ 1,000원 | `{conditions['raw_close_krw']}` | `{'PASS' if conditions['raw_close_pass'] else 'FAIL'}` |",
        f"| 20 KRX 거래일 평균 raw 거래량 ≥ 10,000주 | `{conditions['avg_volume_20d_shares']}` | `{'PASS' if conditions['volume_pass'] else 'FAIL'}` |",
        f"| Strategy-ready / clean-ready | `{conditions['strategy_ready_date']} / {conditions['clean_ready_date']}` | `{'PASS' if conditions['strategy_ready_pass'] else 'FAIL'}` |",
        f"| Pattern A 국면 | `{conditions['pattern_a_stage']}` | `{'PASS' if conditions['pattern_a_stage_pass'] else 'FAIL'}` |",
        f"| FAST 주별 트리거 | `{conditions['fast_stage']} ({conditions['fast_stage_status']})` | `{'PASS' if conditions['fast_trigger_pass'] else 'FAIL'}` |",
        f"| 월간 국면 | `{conditions['monthly_regime']}` | `{'PASS' if conditions['monthly_regime_pass'] else 'FAIL'}` |",
        f"| 일봉 리스크 | `{conditions['daily_risk']}` | `{'PASS' if conditions['daily_risk_pass'] else 'FAIL'}` |",
        f"| FAST 점수 | `{conditions['fast_score_state']}` | `{'PASS' if conditions['fast_score_pass'] else 'FAIL'}` |",
        f"| 미보유 상태 | `{strategy['canonical_position']}` | `{'PASS' if conditions['no_open_position'] else 'FAIL'}` |",
        f"| 다음 실제 KRX 거래일 raw 시가 | `{conditions['next_krx_session_date']} / {conditions['next_open_raw_krw']}` | `{'PASS' if conditions['exact_next_open_available'] else 'FAIL'}` |",
        "",
        f"- **신규 진입 조건 전체 판정**: `{'PASS' if conditions['all_conditions_met'] else 'FAIL'}`",
        f"- **미충족 조건**: `{', '.join(conditions['failed_conditions']) if conditions['failed_conditions'] else '없음'}`",
        "",
        "### 현재 포지션",
    ]
    current = strategy.get("current_trade")
    if current:
        current_close = current.get("current_close_krw")
        current_return = current.get("current_return_pct")
        lines.extend([
            f"- **거래 ID / 순번**: `{current['trade_id']}` / `{current['trade_sequence']}`",
            f"- **진입 신호일 / 체결일**: `{current['entry_signal_date']}` / `{current['entry_execution_date']}`",
            f"- **진입 시가 / 기준일 종가**: `{current['entry_open_krw']}` / `{current_close if current_close is not None else 'N/A'}원`",
            f"- **수익률**: `{current_return if current_return is not None else 'N/A'}%`",
            f"- **Lifecycle**: `{current['lifecycle_class']}`",
            f"- **청산 신호**: `{current['exit_type']}` / `{current['exit_signal_date'] or '없음'}`",
        ])
    else:
        lines.append("- 기준일 현재 열린 Julia V1 포지션이 없어.")
    lines.extend([
        "",
        "### 보호 및 재진입",
        f"- **Pre-PROGRESSED Loss Guard**: `{strategy['provenance']['loss_guard_enabled'] and 'ENABLED' or 'DISABLED'}`",
        f"- **보호 상태**: `{strategy['protection_state'] or '열린 포지션 없음'}`",
        f"- **재진입 상태**: `{strategy['reentry_state']}`",
        "",
    ])
    history = strategy.get("trade_history") or []
    if history:
        lines.extend([
            "### Julia V1 전략 거래 이력",
            "| 순번 | 진입 신호일 | 진입 체결일 | 진입 시가 | 청산 유형 | 청산 체결일 | 청산 시가 | 수익률 | 상태 |",
            "|:---:|:---:|:---:|---:|---|:---:|---:|---:|:---:|",
        ])
        for row in history:
            exit_price = f"{row['exit_price_krw']:,.0f}원" if row["exit_price_krw"] is not None else "-"
            terminal_return = f"{row['terminal_return_pct']:+.2f}%" if row["terminal_return_pct"] is not None else "N/A"
            lines.append(
                f"| {row['trade_sequence']} | `{row['entry_signal_date']}` | `{row['entry_execution_date']}` | "
                f"{row['entry_open_krw']:,.0f}원 | `{row['exit_type']}` | "
                f"`{row['exit_execution_date'] or '-'}` | "
                f"{exit_price} | {terminal_return} | `{row['trade_status']}` |"
            )
    else:
        lines.append("- Julia V1 거래 이력이 없어.")
    lines.extend([
        "",
        "> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.",
        "",
        "---",
        "",
    ])
    return "\n".join(lines)


def _render_etf_snapshot(report_dict: dict[str, Any]) -> str:
    snap = report_dict["official_strategy"]["current_snapshot"]
    lines = [
        "## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷",
        f"- **Pattern A Score / 국면**: `{report_dict['current_snapshot'].get('pattern_a_score')}` / `{report_dict['current_snapshot'].get('official_stage')}`",
        f"- **Official ETF36 membership**: `{'PASS' if snap['official_etf36_membership'] else 'FAIL'}`",
        f"- **상장일 / 상장 2년 요건**: `{snap['listing_date']}` / `{'PASS' if snap['listing_age_pass'] else 'FAIL'}`",
        f"- **기준일 raw 종가**: `{snap['raw_close_krw'] if snap['raw_close_krw'] is not None else 'N/A'}원` (최소 1,000원: `{'PASS' if snap['raw_close_pass'] else 'FAIL'}`)",
        f"- **20 KRX 거래일 평균 raw 거래량**: `{snap['avg_volume_20d_shares'] if snap['avg_volume_20d_shares'] is not None else 'N/A'}주` (최소 10,000주: `{'PASS' if snap['volume_pass'] else 'FAIL'}`)",
        f"- **20일 창**: `{snap['volume_window_start'] or 'N/A'}` ~ `{snap['volume_window_end'] or 'N/A'}`; 신호일 포함: `{snap['volume_window_includes_signal_date']}`",
        f"- **ETF 적격성**: `{'PASS' if snap['eligibility_pass'] else 'FAIL'}` (`{ELIGIBILITY_CONTRACT}`)",
        f"- **Strategy-ready / clean-ready / 유효 시작일**: `{snap['strategy_ready_date']} / {snap['clean_ready_date']} / {snap['effective_start_date']}`",
        "- **시가총액 / Phase10 Investability**: `NOT_APPLICABLE` (Julia V1 ETF 적격성 조건이 아님)",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def render_etf_markdown(base_report: Any, payload: dict[str, Any]) -> str:
    """Render the shared report then replace ETF-specific sections only."""
    markdown = render_markdown_report(base_report).replace("종목 리포트 v0.5", "종목 리포트 v0.6", 1)
    markdown = markdown.replace("## 1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)", "## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷", 1)
    section_1 = re.compile(
        r"## 1\. 현재 기술적 국면 및 ETF 적격성 스냅샷.*?\n---\n\n", re.DOTALL
    )
    markdown, count = section_1.subn(_render_etf_snapshot(payload), markdown, count=1)
    if count != 1:
        raise ValueError("ETF_V06_MARKDOWN_CURRENT_SNAPSHOT_ANCHOR_MISSING")
    strategy_pattern = re.compile(r"## 2\. 패스트 코어 V2 전략 상태.*?\n## 3\. Pattern A FAST", re.DOTALL)
    replacement = _render_strategy_markdown(payload) + "## 3. Pattern A FAST"
    markdown, count = strategy_pattern.subn(replacement, markdown, count=1)
    if count != 1:
        raise ValueError("ETF_V06_MARKDOWN_STRATEGY_ANCHOR_MISSING")
    if "A FAST Core V2" in markdown or "패스트 코어 V2 전략 상태" in markdown:
        raise ValueError("ETF_V06_MARKDOWN_CONTAINS_COMMON_OFFICIAL_STRATEGY")
    return markdown


def validate_v06_report_payload(repo_root: Path, payload: dict[str, Any], markdown: str) -> None:
    """Fail closed on report contract, routing, network, and post-reference dates."""
    import jsonschema

    schema = json.loads((repo_root / "docs/reporting/schema_v06.json").read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
    if payload.get("asset_type") != "ETF":
        raise ValueError("V06_ASSET_TYPE_NOT_ETF")
    if "a_fast_core" in payload:
        raise ValueError("V06_CONTAINS_A_FAST_CORE_ROUTE")
    strategy = payload["official_strategy"]
    if strategy.get("strategy_id") != STRATEGY_ID or strategy.get("eligibility_contract") != ELIGIBILITY_CONTRACT:
        raise ValueError("V06_OFFICIAL_STRATEGY_ROUTE_MISMATCH")
    if payload["provenance"].get("network_requests") != 0 or strategy["provenance"].get("network_requests") != 0:
        raise ValueError("V06_NETWORK_REQUEST_RECORDED")
    reference = pd.Timestamp(payload["reference_market_date"])
    effective = payload.get("header", {}).get("effective_as_of")
    if effective and pd.Timestamp(effective) > reference:
        raise ValueError("V06_COMMON_DATA_AFTER_REFERENCE_DATE")

    def inspect_dates(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                inspect_dates(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                inspect_dates(child, key)
        elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            if key not in {"requested_as_of", "target_as_of"} and pd.Timestamp(value) > reference:
                raise ValueError(f"V06_POST_REFERENCE_DATE_FIELD:{key}:{value}")

    inspect_dates(payload)
    if "## 2. Julia V1 전략 상태" not in markdown:
        raise ValueError("V06_MARKDOWN_JULIA_SECTION_MISSING")
    if "A FAST Core V2" in markdown or "패스트 코어 V2 전략 상태" in markdown:
        raise ValueError("V06_MARKDOWN_COMMON_STRATEGY_ROUTE_PRESENT")
    if "Pre-PROGRESSED Loss Guard**: `DISABLED`" not in markdown:
        raise ValueError("V06_MARKDOWN_LOSS_GUARD_NOT_EXPLICIT")


def generate_etf_stock_report_v06(
    identity: ETFIdentity,
    *,
    repo_root: Path,
    repository: MarketDataRepositoryV2,
    calendar: MarketCalendarAuthority,
    target_as_of: str,
    reference_market_date: str,
    readiness: dict[str, str],
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Create one official ETF36 Stock Report v0.6 payload and Markdown."""
    root = Path(repo_root).resolve()
    target = _iso(target_as_of)
    ref_date = _iso(reference_market_date)
    if pd.Timestamp(target) < pd.Timestamp(ref_date):
        raise ValueError("TARGET_AS_OF_BEFORE_REFERENCE_MARKET_DATE")

    raw = _normalize_raw(repository.get_raw_daily(identity.ticker, identity.listing_date, ref_date), ref_date)
    base, _, _ = generate_stock_report(
        identity.ticker,
        as_of=target,
        repo_root=repo_root,
        save_artifacts=False,
        repository=repository,
        fundamentals_section=None,
        reference_market_date=ref_date,
        daily_override=raw if not raw.empty else None,
    )
    if base.asset_type != AssetType.ETF.value:
        raise ValueError(f"ASSET_TYPE_NOT_ETF:{identity.ticker}:{base.asset_type}")
    if base.header.effective_as_of and base.header.effective_as_of > ref_date:
        raise ValueError(f"COMMON_REPORT_LOOKAHEAD:{identity.ticker}:{base.header.effective_as_of}")

    calendar_dates = _calendar_dates(calendar, ref_date)
    metrics, signal_pass_dates, executable_dates = compute_etf_eligibility(
        raw,
        listing_date=identity.listing_date,
        effective_start_date=readiness["effective_start_date"],
        calendar_dates=calendar_dates,
    )
    context = build_precomputed_ticker_context(identity.ticker, identity.name, raw) if not raw.empty else None
    errors: list[str] = []
    if context is None:
        strategy = {
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
            "strategy_version": "V1",
            "asset_scope": "OFFICIAL_ETF_36",
            "applicability": "APPLICABLE",
            "strategy_state": "DATA_UNAVAILABLE",
            "canonical_position": "DATA_UNAVAILABLE",
            "action": "NONE",
            "action_reason": "RAW_HISTORY_UNAVAILABLE",
            "execution_timing": None,
            "entry_conditions": {"all_conditions_met": False, "failed_conditions": ["RAW_HISTORY_UNAVAILABLE"]},
            "current_trade": None,
            "protection_state": None,
            "reentry_state": {"enabled": True, "cooldown": "NONE", "maximum_reentries": "NONE", "completed_trade_count": 0, "current_trade_sequence": None, "next_entry_sequence": 1},
            "trade_history": [],
            "interpretation": "raw KRX 데이터가 없어 Julia V1 상태를 판정할 수 없어.",
            "eligibility_contract": ELIGIBILITY_CONTRACT,
            "provenance": {"evaluator_id": "JULIA_STRATEGY_V00", "loss_guard_enabled": False, "data_source": "KRX_RAW_ETF_OHLCV", "reference_market_date": ref_date, "strategy_ready_date": readiness["strategy_ready_date"], "clean_ready_date": readiness["clean_ready_date"], "network_requests": 0, "support_evaluator_errors": []},
            "current_snapshot": {"as_of": ref_date, "official_etf36_membership": True, "listing_date": identity.listing_date, "listing_age_pass": None, "raw_close_krw": None, "minimum_raw_close_krw": 1000, "raw_close_pass": False, "avg_volume_20d_shares": None, "volume_window_sessions": None, "volume_window_start": None, "volume_window_end": None, "volume_window_includes_signal_date": True, "minimum_avg_volume_20d_shares": 10000, "volume_pass": False, "eligibility_pass": False, "eligibility_contract": ELIGIBILITY_CONTRACT, "strategy_ready_date": readiness["strategy_ready_date"], "clean_ready_date": readiness["clean_ready_date"], "effective_start_date": readiness["effective_start_date"], "market_cap_applicability": "NOT_APPLICABLE_TO_JULIA_ETF_ELIGIBILITY", "phase10_investability_applicability": "NOT_APPLICABLE"},
        }
    else:
        strategy = _strategy_section(
            identity=identity,
            raw=raw,
            context=context,
            calendar=calendar,
            calendar_dates=calendar_dates,
            ref_date=ref_date,
            effective_start=readiness["effective_start_date"],
            readiness=readiness,
            metrics=metrics,
            signal_pass_dates=signal_pass_dates,
            executable_dates=executable_dates,
            score_contract=score_contract,
            stage_contract=stage_contract,
            support_errors=errors,
        )

    readiness_status, readiness_reason = _readiness_status(
        raw=raw,
        reference_date=ref_date,
        metrics=metrics,
        strategy=strategy,
        base_report=base,
    )
    base.report_version = "0.6"
    base.header.report_status = ReportStatus(readiness_status)
    base.current_snapshot.market_cap_eok = None
    base.current_snapshot.avg_trading_value_20d_eok = None
    base.current_snapshot.investability_status = "NOT_APPLICABLE"
    base.current_snapshot.investability_reason = "ETF_JULIA_USES_RAW_PIT_ELIGIBILITY_CONTRACT"
    base.current_snapshot.is_investable = False
    base.current_snapshot.market_cap_effective_date = None
    base.current_snapshot.market_cap_source = None
    base.summary.headline = (
        f"{identity.name}({identity.ticker})의 공식 ETF36 Julia V1 리포트야. "
        f"분석 기준일 {target}, 실제 시장 데이터 기준일 {ref_date}야."
    )
    base.summary.strategy_headline = strategy["interpretation"]
    inherited_bullets = [
        line for line in base.summary.bullet_points
        if not any(token in line for token in ("패스트 코어 V2", "Phase 10", "시가총액", "Investability"))
    ]
    current = strategy["current_snapshot"]
    eligibility_bullet = (
        f"ETF 적격성: {'PASS' if current['eligibility_pass'] else 'FAIL'} · "
        f"raw 종가 {current['raw_close_krw'] if current['raw_close_krw'] is not None else 'N/A'}원 · "
        f"20D 평균 거래량 {current['avg_volume_20d_shares'] if current['avg_volume_20d_shares'] is not None else 'N/A'}주"
    )
    base.summary.bullet_points = [_strategy_bullet(strategy), eligibility_bullet, *inherited_bullets]
    base.summary.combined_narrative = (
        f"{identity.name}은(는) 기준일 {ref_date}에 Julia V1 상태 {strategy['strategy_state']}야. "
        f"ETF PIT 적격성은 {'PASS' if current['eligibility_pass'] else 'FAIL'}이며 "
        f"시가총액과 Phase10 Investability는 이 ETF 전략의 적격성 기준이 아니야. "
        f"공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어."
    )

    payload = base.to_dict()
    payload.pop("a_fast_core", None)
    payload["report_version"] = "0.6"
    payload["readiness_status"] = readiness_status
    payload["readiness_reason"] = readiness_reason
    payload["official_strategy"] = strategy
    payload["current_snapshot"]["etf_eligibility"] = current
    payload["provenance"]["investability_contract"] = ELIGIBILITY_CONTRACT
    payload["provenance"]["network_requests"] = 0
    markdown = render_etf_markdown(base, payload)
    validate_v06_report_payload(root, payload, markdown)
    return payload, markdown


def generate_official_etf36_reports(
    *,
    repo_root: Path,
    target_as_of: str,
    reference_market_date: str,
    output_dir: Path,
    tickers: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Generate the requested subset (full frozen set by default) once."""
    root = Path(repo_root).resolve()
    universe, universe_sha = load_official_etf36(root)
    ready_dates = load_strategy_ready_dates(root)
    if set(ready_dates) != {item.ticker for item in universe}:
        raise ValueError("STRATEGY_READY_AUDIT_TICKER_SET_MISMATCH")
    selected = set(str(ticker).zfill(6) for ticker in tickers) if tickers is not None else {item.ticker for item in universe}
    if not selected <= {item.ticker for item in universe}:
        raise ValueError("REQUESTED_TICKER_OUTSIDE_OFFICIAL_ETF36")

    output = Path(output_dir)
    (output / "json").mkdir(parents=True, exist_ok=True)
    calendar = load_rolling_production_market_calendar(root)
    if calendar is None:
        raise RuntimeError("ROLLING_KRX_CALENDAR_UNAVAILABLE")
    repository = build_production_repository_v2(root, end=target_as_of)
    score_contract, stage_contract = _load_contracts(root)
    failures: list[dict[str, str]] = []
    non_ready: list[dict[str, str]] = []
    readiness_counts = {"READY": 0, "PARTIAL": 0, "DATA_UNAVAILABLE": 0}
    state_counts: dict[str, int] = {}
    eligibility_counts = {"PASS": 0, "FAIL": 0}
    generated_tickers: list[str] = []
    evaluator_error_tickers: list[dict[str, Any]] = []
    for identity in universe:
        if identity.ticker not in selected:
            continue
        try:
            payload, markdown = generate_etf_stock_report_v06(
                identity,
                repo_root=root,
                repository=repository,
                calendar=calendar,
                target_as_of=target_as_of,
                reference_market_date=reference_market_date,
                readiness=ready_dates[identity.ticker],
                score_contract=score_contract,
                stage_contract=stage_contract,
            )
            if payload["asset_type"] != "ETF" or payload["official_strategy"]["strategy_id"] != STRATEGY_ID:
                raise ValueError("REPORT_CONTRACT_IDENTITY_MISMATCH")
            name = identity.name
            stem = f"{identity.ticker}_{name}"
            (output / "json" / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            (output / f"{stem}.md").write_text(markdown, encoding="utf-8")
            generated_tickers.append(identity.ticker)
            readiness_counts[payload["readiness_status"]] += 1
            evaluator_errors = payload["official_strategy"]["provenance"].get("support_evaluator_errors", [])
            if evaluator_errors:
                evaluator_error_tickers.append({"ticker": identity.ticker, "errors": evaluator_errors})
            state = payload["official_strategy"]["strategy_state"]
            state_counts[state] = state_counts.get(state, 0) + 1
            eligibility_counts["PASS" if payload["official_strategy"]["current_snapshot"]["eligibility_pass"] else "FAIL"] += 1
            if payload["readiness_status"] != "READY":
                non_ready.append({"ticker": identity.ticker, "status": payload["readiness_status"], "reason": payload["readiness_reason"]})
        except Exception as exc:
            failures.append({"ticker": identity.ticker, "reason": f"{type(exc).__name__}:{str(exc)[:300]}"})

    result = {
        "target_as_of": _iso(target_as_of),
        "reference_market_date": _iso(reference_market_date),
        "expected_count": len(selected),
        "generated_count": len(generated_tickers),
        "generated_tickers": generated_tickers,
        "readiness_status_counts": readiness_counts,
        "strategy_id_counts": {STRATEGY_ID: len(generated_tickers)},
        "strategy_state_counts": state_counts,
        "eligibility_pass_fail_counts": eligibility_counts,
        "failed_tickers_and_reasons": failures,
        "non_ready_tickers_and_reasons": non_ready,
        "source_universe_sha256": universe_sha,
        "network_requests": 0,
        "post_asof_data_references": 0,
        "julia_evaluator_error_tickers": evaluator_error_tickers,
        "code_commit": None,
    }
    summary_file = output / "generation_summary.json"
    summary_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
