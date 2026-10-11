#!/usr/bin/env python3
"""Research-only P3-2 V2 CONTROL vs alignment+500B portfolio replay.

No production strategy code is modified. The frozen V2 evaluator's external
entry_signal_filter is the only candidate change; it is called before V2
re-entry state advances.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2 import _is_non_trading_placeholder
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import load_rolling_authority, validate_merged_authority_coherence
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    build_precomputed_ticker_context,
    simulate_ticker_core_v02_reentry,
)
import trend_scanner.validation.pattern_a_fast_core_v02_reentry as frozen_v2

import scripts.run_v2_official_adoption_revalidation_v02 as portfolio
from scripts.run_fastcore_neg40_weak_protect_p2_1 import IdentitySegment

OUT = Path(__file__).resolve().parent
ROLLING = ROOT / "data/market/rolling_authority"
PRICE_DIR = ROOT / "data/market/adjusted/stocks"
RAW_DIR = ROOT / "data/market/raw/krx_stocks/v01"
EVAL_START = pd.Timestamp("2022-01-03")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
INITIAL_CAPITAL = 200_000_000.0
WORKERS = 10
MARKET_CAP_FLOOR = 500_000_000_000
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
_EVALUATION_CACHE_LOCAL = threading.local()
_ORIGINAL_FAST_EVALUATOR = frozen_v2.evaluate_pattern_a_fast


def install_per_ticker_evaluation_cache() -> None:
    """Memoize pure weekly V2 feature results across CONTROL/candidate replays.

    Cache lifetime is one ticker task and both groups share the same immutable
    Repository V2 frame and precomputed context.
    """
    def cached_evaluate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        cache = getattr(_EVALUATION_CACHE_LOCAL, "cache", None)
        if cache is None:
            return _ORIGINAL_FAST_EVALUATOR(*args, **kwargs)
        week = pd.Timestamp(args[3]).normalize().strftime("%Y-%m-%d")
        key = (str(args[0]).zfill(6), week, id(kwargs.get("context")), id(args[4]), id(args[5]), id(kwargs.get("market_calendar")))
        if key in cache:
            _EVALUATION_CACHE_LOCAL.hits += 1
            return cache[key]
        result = _ORIGINAL_FAST_EVALUATOR(*args, **kwargs)
        cache[key] = result
        _EVALUATION_CACHE_LOCAL.misses += 1
        return result
    frozen_v2.evaluate_pattern_a_fast = cached_evaluate


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def build_authority() -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, tuple[IdentitySegment, ...]]]:
    manifest = load_rolling_authority(ROLLING)
    pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, ROLLING)
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("ROLLING_MARKET_CALENDAR_UNAVAILABLE")
    all_rows = pit_payload.get("intervals", [])
    grouped: dict[str, list[IdentitySegment]] = {}
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in all_rows:
        if row.get("state") != "COMMON":
            continue
        start = pd.Timestamp(row["effective_from"]).normalize()
        end = pd.Timestamp(row["effective_to"]).normalize()
        if start > CUTOFF or end < EVAL_START:
            continue
        ticker = str(row["ticker"]).zfill(6)
        isu = str(row["isu_cd"]).strip().upper()
        market = str(row["market"]).strip().upper()
        if (ticker, isu) in PERMANENT_IDENTITY_EXCLUSIONS:
            continue
        segment = IdentitySegment(ticker, isu, market, start, end)
        key = (ticker, isu, market, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if key in seen:
            raise RuntimeError(f"DUPLICATE_PIT_SEGMENT:{key}")
        seen.add(key)
        grouped.setdefault(ticker, []).append(segment)
    for ticker, segments in grouped.items():
        segments.sort(key=lambda x: (x.effective_from, x.effective_to, x.isu_cd, x.market))
        prior: IdentitySegment | None = None
        for segment in segments:
            if prior and segment.effective_from <= prior.effective_to:
                raise RuntimeError(f"OVERLAPPING_PIT_IDENTITIES:{ticker}:{prior.key}:{segment.key}")
            prior = segment
    return calendar, pit_payload, calendar_payload, {k: tuple(v) for k, v in sorted(grouped.items())}


class ExactSignalMcap:
    """Thread-safe verified cache for exact KRX market/date partitions."""

    def __init__(self) -> None:
        self.store = KrxRawStockStore(RAW_DIR)
        self.cache: dict[tuple[str, str], tuple[dict[str, Any] | None, dict[str, list[Any]] | None, str | None]] = {}
        self.lock = threading.RLock()

    def resolve(self, segment: IdentitySegment, day: pd.Timestamp) -> dict[str, Any]:
        date_text = pd.Timestamp(day).strftime("%Y-%m-%d")
        key = (segment.market.upper(), date_text)
        with self.lock:
            cached = self.cache.get(key)
        if cached is None:
            manifest = self.store.get_manifest(*key)
            cap_rows: dict[str, list[Any]] | None = None
            error: str | None = None
            if manifest is None or manifest.get("status") != "COMPLETE":
                error = "EXACT_RAW_PARTITION_UNAVAILABLE"
            else:
                try:
                    frame = self.store.load_snapshot(*key)
                    cap_rows = {
                        str(ticker).zfill(6): group["market_cap"].tolist()
                        for ticker, group in frame.groupby(frame["ticker"].astype(str).str.zfill(6), sort=False)
                    }
                    del frame
                except Exception as exc:
                    error = f"EXACT_RAW_PARTITION_INVALID:{type(exc).__name__}"
            cached = (manifest, cap_rows, error)
            with self.lock:
                cached = self.cache.setdefault(key, cached)
        manifest, cap_rows, error = cached
        base: dict[str, Any] = {
            "mcap_source_date": date_text,
            "mcap_source_market": segment.market,
            "mcap_partition_status": None if manifest is None else manifest.get("status"),
            "mcap_partition_path": None if manifest is None else manifest.get("file_path"),
            "mcap_partition_file_sha256": None if manifest is None else manifest.get("file_sha256"),
            "mcap_partition_content_sha256": None if manifest is None else manifest.get("content_sha256"),
            "market_cap_krw": None,
        }
        if error or cap_rows is None:
            base.update(mcap_status="UNRESOLVED", mcap_reason=error or "EXACT_RAW_PARTITION_UNAVAILABLE")
            return base
        values = cap_rows.get(segment.ticker, [])
        if len(values) == 0:
            base.update(mcap_status="UNRESOLVED", mcap_reason="EXACT_RAW_TICKER_ROW_MISSING")
        elif len(values) != 1:
            base.update(mcap_status="UNRESOLVED", mcap_reason="DUPLICATE_EXACT_RAW_TICKER_ROWS")
        else:
            raw_value = values[0]
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = float("nan")
            if not math.isfinite(value) or value <= 0 or not value.is_integer():
                base.update(mcap_status="UNRESOLVED", mcap_reason="INVALID_EXACT_RAW_MKTCAP")
            else:
                base["market_cap_krw"] = int(value)
                if value >= MARKET_CAP_FLOOR:
                    base.update(mcap_status="PASS", mcap_reason="EXACT_RAW_MKTCAP_AT_OR_ABOVE_500B")
                else:
                    base.update(mcap_status="REJECT_BELOW_THRESHOLD", mcap_reason="EXACT_RAW_MKTCAP_BELOW_500B")
        return base


def active_segments(segments: tuple[IdentitySegment, ...], day: pd.Timestamp) -> list[IdentitySegment]:
    return [s for s in segments if s.effective_from <= day <= s.effective_to]


def monthly_alignment(
    daily: pd.DataFrame,
    signal_date: pd.Timestamp,
    completed_month_ends: pd.DatetimeIndex,
) -> dict[str, Any]:
    day = pd.Timestamp(signal_date).normalize()
    signal_close: float | None = None
    if day in daily.index:
        try:
            value = float(daily.at[day, "close"])
            signal_close = value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError):
            pass
    if signal_close is None:
        return {"signal_day_adjusted_close": None, "ma20": None, "ma60": None, "ma_status": "SIGNAL_CLOSE_UNAVAILABLE", "ma_reason": "NO_EXACT_SIGNAL_DAY_ADJUSTED_CLOSE"}

    signal_month = day.to_period("M")
    month_ends = [pd.Timestamp(d).normalize() for d in completed_month_ends if pd.Timestamp(d).to_period("M") < signal_month]
    month_ends = sorted(month_ends)
    last_60_ends = month_ends[-60:]
    close_by_month = daily["close"].copy()
    close_by_month.index = pd.DatetimeIndex(close_by_month.index).to_period("M")
    close_by_month = close_by_month.groupby(level=0, sort=True).last()
    target_periods = [d.to_period("M") for d in last_60_ends]
    if len(target_periods) != 60 or len(set(target_periods)) != 60:
        return {"signal_day_adjusted_close": signal_close, "ma20": None, "ma60": None, "ma_status": "MA_UNAVAILABLE", "ma_reason": "FEWER_THAN_60_PRIOR_COMPLETED_MONTHS"}
    selected = close_by_month.reindex(target_periods)
    if len(selected) != 60 or selected.isna().any():
        missing = [str(period) for period, value in selected.items() if pd.isna(value)]
        return {"signal_day_adjusted_close": signal_close, "ma20": None, "ma60": None, "ma_status": "MA_UNAVAILABLE", "ma_reason": "MISSING_PRIOR_COMPLETED_MONTH_BARS", "ma_missing_months": missing}
    values = pd.to_numeric(selected, errors="coerce").astype(float)
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any():
        return {"signal_day_adjusted_close": signal_close, "ma20": None, "ma60": None, "ma_status": "MA_UNAVAILABLE", "ma_reason": "INVALID_PRIOR_COMPLETED_MONTH_BAR"}
    ma20 = float(values.iloc[-20:].mean())
    ma60 = float(values.mean())
    passed = signal_close > ma20 > ma60
    return {
        "signal_day_adjusted_close": signal_close,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_window_first_month": str(target_periods[-20]),
        "ma20_window_last_month": str(target_periods[-1]),
        "ma60_window_first_month": str(target_periods[0]),
        "ma60_window_last_month": str(target_periods[-1]),
        "ma_status": "PASS" if passed else "ALIGNMENT_FAIL",
        "ma_reason": "STRICT_CLOSE_GT_MA20_GT_MA60" if passed else "STRICT_ALIGNMENT_NOT_MET",
    }


def stable_sample_tickers(all_tickers: list[str], count: int = 30) -> list[str]:
    ranked = sorted(all_tickers, key=lambda t: hashlib.sha256(f"P3-2:{t}".encode()).hexdigest())
    forced = [t for t in ("005930", "000660", "005380", "000270", "035420", "380440") if t in all_tickers]
    selected = list(dict.fromkeys(forced + ranked))[:max(count, len(forced))]
    return selected


def evaluator_rows_for_ticker(
    ticker: str,
    *,
    loader: RepositoryV2DailyLoader,
    calendar: Any,
    segments_by_ticker: Mapping[str, tuple[IdentitySegment, ...]],
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    mcap_resolver: ExactSignalMcap,
) -> dict[str, Any]:
    segments = segments_by_ticker[ticker]
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        return {"ticker": ticker, "data_status": "DATA_UNAVAILABLE", "control_trades": [], "candidate_trades": [], "audits": [], "errors": ["REPOSITORY_V2_ADJUSTED_OR_RAW_UNAVAILABLE"]}
    daily = daily.sort_index()
    if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
        raise RuntimeError(f"INVALID_REPOSITORY_V2_DAILY_INDEX:{ticker}")
    if not {"open", "high", "low", "close"}.issubset(daily.columns):
        raise RuntimeError(f"REPOSITORY_V2_OHLC_COLUMNS_MISSING:{ticker}")
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    monthly_cache: dict[str, dict[str, Any]] = {}
    audit_by_day: dict[str, dict[str, Any]] = {}
    audit_lock = threading.RLock()

    def decision(signal_date: pd.Timestamp, evaluation: Mapping[str, Any]) -> dict[str, Any]:
        day = pd.Timestamp(signal_date).normalize()
        date_text = day.strftime("%Y-%m-%d")
        with audit_lock:
            if date_text in audit_by_day:
                return audit_by_day[date_text]
        active = active_segments(segments, day)
        identity: IdentitySegment | None = active[0] if len(active) == 1 else None
        common: dict[str, Any] = {
            "ticker": ticker,
            "signal_date": date_text,
            "fast_machine_stage": evaluation.get("fast_machine_stage"),
            "fast_machine_stage_status": evaluation.get("fast_machine_stage_status"),
            "fast_monthly_permission_state": evaluation.get("fast_monthly_permission_state"),
            "fast_daily_risk_state": evaluation.get("fast_daily_risk_state"),
            "fast_score_status": evaluation.get("fast_score_status"),
            "pattern_a_stage": evaluation.get("pattern_a_stage"),
            "active_common_identity_count": len(active),
            "isu_cd": None if identity is None else identity.isu_cd,
            "market": None if identity is None else identity.market,
            "identity_effective_from": None if identity is None else identity.effective_from.strftime("%Y-%m-%d"),
            "identity_effective_to": None if identity is None else identity.effective_to.strftime("%Y-%m-%d"),
            "seen_in_control_scan": False,
            "seen_in_candidate_scan": False,
        }
        if len(active) != 1:
            common.update(pit_status="UNRESOLVED", pit_reason="NO_ACTIVE_COMMON_IDENTITY" if not active else "AMBIGUOUS_ACTIVE_COMMON_IDENTITY")
            common.update(signal_day_adjusted_close=None, ma20=None, ma60=None, ma_status="NOT_EVALUATED", ma_reason="PIT_IDENTITY_UNRESOLVED", mcap_status="NOT_EVALUATED", mcap_reason="PIT_IDENTITY_UNRESOLVED")
            common["candidate_status"] = "REJECT_PIT_IDENTITY_UNRESOLVED"
        else:
            common.update(pit_status="PASS", pit_reason="EXACT_ACTIVE_COMMON_PIT_IDENTITY")
            ma = monthly_cache.get(date_text)
            if ma is None:
                ma = monthly_alignment(daily, day, pd.DatetimeIndex(calendar.completed_month_ends))
                monthly_cache[date_text] = ma
            common.update(ma)
            cap = mcap_resolver.resolve(identity, day)
            common.update(cap)
            if ma.get("ma_status") == "MA_UNAVAILABLE":
                candidate_status = "REJECT_MA_UNAVAILABLE"
            elif ma.get("ma_status") != "PASS":
                candidate_status = "REJECT_ALIGNMENT"
            elif cap.get("mcap_status") == "UNRESOLVED":
                candidate_status = "REJECT_MCAP_UNRESOLVED"
            elif cap.get("mcap_status") != "PASS":
                candidate_status = "REJECT_MCAP_BELOW_500B"
            else:
                candidate_status = "PASS"
            common["candidate_status"] = candidate_status
        with audit_lock:
            prior = audit_by_day.setdefault(date_text, common)
            return prior

    def control_filter(signal_date: pd.Timestamp, evaluation: Mapping[str, Any]) -> bool:
        row = decision(signal_date, evaluation)
        row["seen_in_control_scan"] = True
        return row["pit_status"] == "PASS"

    def candidate_filter(signal_date: pd.Timestamp, evaluation: Mapping[str, Any]) -> bool:
        row = decision(signal_date, evaluation)
        row["seen_in_candidate_scan"] = True
        return row["pit_status"] == "PASS" and row["candidate_status"] == "PASS"

    common_kwargs = {
        "ticker": ticker,
        "name": ticker,
        "market": segments[0].market,
        "daily": daily,
        "score_contract": score_contract,
        "stage_contract": stage_contract,
        "cutoff_date": CUTOFF,
        "snapshot_context": context,
        "market_calendar": calendar,
        "entry_search_start": EVAL_START,
        "signal_cutoff_date": CUTOFF,
        "execution_support_date": SUPPORT,
        "strict_errors": True,
        "entry_execution_cutoff_date": CUTOFF,
        "entry_signal_cutoff_date": CUTOFF,
    }
    _EVALUATION_CACHE_LOCAL.cache = {}
    _EVALUATION_CACHE_LOCAL.hits = 0
    _EVALUATION_CACHE_LOCAL.misses = 0
    control = simulate_ticker_core_v02_reentry(**common_kwargs, entry_signal_filter=control_filter)
    candidate = simulate_ticker_core_v02_reentry(**common_kwargs, entry_signal_filter=candidate_filter)
    cache_stats = {"evaluation_cache_hits": _EVALUATION_CACHE_LOCAL.hits, "evaluation_cache_misses": _EVALUATION_CACHE_LOCAL.misses}
    _EVALUATION_CACHE_LOCAL.cache = None

    def add_identity(record: Any) -> dict[str, Any]:
        row = record.to_dict()
        signal = pd.Timestamp(row["entry_signal_date"]).normalize()
        active = active_segments(segments, signal)
        if len(active) != 1:
            raise RuntimeError(f"ACCEPTED_SIGNAL_IDENTITY_NOT_UNIQUE:{ticker}:{signal.date()}")
        segment = active[0]
        row.update({
            "isu_cd": segment.isu_cd,
            "standard_isu_cd": segment.isu_cd,
            "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
            "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
            "market": segment.market,
            "pair_id": "|".join((ticker, segment.isu_cd, signal.strftime("%Y-%m-%d"), str(row["entry_execution_date"]))),
            "lifecycle_state": "",
            "lifecycle_evidence_id": "",
        })
        return row

    return {
        "ticker": ticker,
        "data_status": "AVAILABLE",
        "control_trades": [add_identity(x) for x in control],
        "candidate_trades": [add_identity(x) for x in candidate],
        "audits": list(audit_by_day.values()),
        "errors": [],
        "daily_rows": int(len(daily)),
        "first_daily_date": daily.index.min().strftime("%Y-%m-%d"),
        "last_daily_date": daily.index.max().strftime("%Y-%m-%d"),
        **cache_stats,
    }


def source_streams(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["ticker"]).zfill(6),
            str(row["isu_cd"]).strip().upper(),
            str(row["market"]).strip().upper(),
            str(row["identity_effective_from"]),
            str(row["identity_effective_to"]),
        )
        out.setdefault(key, []).append(row)
    for group in out.values():
        group.sort(key=lambda r: (str(r["entry_signal_date"]), str(r["entry_execution_date"]), str(r["trade_id"])))
    return out


def make_portfolio_context(
    *, calendar: Any, segments_by_ticker: Mapping[str, tuple[IdentitySegment, ...]], repository: Any,
) -> Any:
    run = SimpleNamespace(
        window=SimpleNamespace(window_id="P3-2", effective_start=EVAL_START, effective_end=CUTOFF, execution_support=SUPPORT),
        calendar=calendar,
        loader=RepositoryV2DailyLoader(repository, end=SUPPORT),
        segments_by_ticker=segments_by_ticker,
        lifecycle_settlements=(),
    )
    return portfolio.WindowContext(
        window_id="P3-2", run=run, source_rows=[], source_details={}, data_frames={}, frame_hashes={},
        segment_by_key={}, typed_lifecycle_by_id={}, legacy_lifecycle=(), raw_store=KrxRawStockStore(RAW_DIR),
        raw_partition_cache={},
    )


def replay_group(ctx: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scoped, issues = portfolio.scope_streams(ctx, rows, CUTOFF)
    # Scope output is independently checked below; portfolio replay consumes the exact pre-fixed rows.
    if sum(len(v) for v in scoped.values()) != len(rows):
        raise RuntimeError(f"PORTFOLIO_SCOPE_DROPPED_TRADE_ROWS:{len(rows)}:{sum(map(len, scoped.values()))}")
    result = portfolio.portfolio_replay(ctx, scoped, issues)
    result["metrics"].update(observed_nav_metrics(result["daily_equity"], result["missing_marks"]))
    return result


def observed_nav_metrics(daily_equity: list[dict[str, Any]], missing_marks: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in daily_equity if row.get("equity") is not None and not pd.isna(row.get("equity"))]
    valid_dates = {str(row["date"]) for row in valid}
    missing_dates = [str(row["date"]) for row in daily_equity if str(row["date"]) not in valid_dates]
    coverage = len(valid) / len(daily_equity) if daily_equity else 0.0
    peak_equity = INITIAL_CAPITAL
    peak_date = EVAL_START.strftime("%Y-%m-%d")
    max_drawdown = 0.0
    max_peak_date = peak_date
    max_trough_date = peak_date
    max_recovery_date: str | None = peak_date
    max_peak_level = INITIAL_CAPITAL
    under_water = 0
    max_under_water = 0
    for row in valid:
        day = str(row["date"])
        equity = float(row["equity"])
        if equity > peak_equity:
            peak_equity = equity
            peak_date = day
        if max_recovery_date is None and equity >= max_peak_level:
            max_recovery_date = day
            under_water = 0
        drawdown = equity / peak_equity - 1.0 if peak_equity else 0.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            max_peak_date = peak_date
            max_trough_date = day
            max_recovery_date = None
            max_peak_level = peak_equity
            under_water = 1
            max_under_water = max(max_under_water, under_water)
        elif max_recovery_date is None:
            under_water += 1
            max_under_water = max(max_under_water, under_water)
    cutoff = next((row for row in daily_equity if row.get("date") == CUTOFF.strftime("%Y-%m-%d")), None)
    return {
        "total_valuation_days": len(daily_equity),
        "valid_nav_days": len(valid),
        "missing_nav_days": len(daily_equity) - len(valid),
        "nav_coverage_pct": coverage * 100.0,
        "mdd_type": "EXACT" if coverage == 1.0 else "OBSERVED" if coverage >= 0.9 else "CHECK_REQUIRED",
        "observed_mdd_pct": max_drawdown * 100.0,
        "mdd_pct": max_drawdown * 100.0 if coverage >= 0.9 else None,
        "mdd_peak_date": max_peak_date,
        "mdd_trough_date": max_trough_date,
        "mdd_recovery_date": max_recovery_date,
        "mdd_underwater_sessions": max_under_water,
        "mdd_recovered": max_recovery_date is not None,
        "mdd_unresolved_mark_count": len(missing_marks),
        "mdd_unresolved_day_count": len(set(missing_dates)),
        "maximum_consecutive_missing_nav_days": _max_consecutive_missing_days(daily_equity),
        "cutoff_equity_krw": None if cutoff is None else cutoff.get("equity"),
        "portfolio_daily_nav_complete": len(valid) == len(daily_equity),
    }


def _max_consecutive_missing_days(daily_equity: list[dict[str, Any]]) -> int:
    current = maximum = 0
    for row in daily_equity:
        if row.get("equity") is None or pd.isna(row.get("equity")):
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def comparison_rows(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    names = sorted(set(control) | set(candidate))
    rows = []
    for name in names:
        a, b = control.get(name), candidate.get(name)
        delta = None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
            delta = b - a
        rows.append({"metric": name, "control": a, "alignment_mcap_500b": b, "candidate_minus_control": delta})
    return rows


def evaluate_gates(control: Mapping[str, Any], candidate: Mapping[str, Any], integrity: Mapping[str, Any]) -> dict[str, Any]:
    total_days = int(candidate.get("total_valuation_days") or 0)
    nav_days = int(candidate.get("valid_nav_days") or 0)
    coverage = nav_days / total_days if total_days else None
    a_status = "PASS" if int(integrity.get("critical_integrity_error_count", 0)) == 0 else "FAIL"
    if integrity.get("unresolved_universe_price_tickers"):
        a_status = "CHECK_REQUIRED"
    costs_ok = bool(integrity.get("all_filled_sides_costed"))
    b_status = "PASS" if costs_ok else "FAIL"
    ret = candidate.get("total_return_pct")
    cagr = candidate.get("cagr_pct")
    c_status = "CHECK_REQUIRED" if ret is None or cagr is None else ("PASS" if ret > 0 and cagr > 0 else "FAIL")
    mdd = candidate.get("mdd_pct")
    control_mdd = control.get("mdd_pct")
    if mdd is None or control_mdd is None:
        d_status = "CHECK_REQUIRED"
        relative = None
    else:
        relative = float(control_mdd) - float(mdd)
        d_status = "PASS" if float(mdd) >= -40.0 and relative < 5.0 else "FAIL"
    if coverage is None or coverage < 0.90:
        e_status = "CHECK_REQUIRED"
        coverage_type = "CHECK_REQUIRED"
    elif coverage == 1.0:
        e_status = "PASS"
        coverage_type = "EXACT"
    else:
        e_status = "OBSERVED"
        coverage_type = "OBSERVED"
    return {
        "window": "P3-2",
        "candidate_period_preliminary": {
            "A_integrity": {"status": a_status, "critical_integrity_error_count": integrity.get("critical_integrity_error_count"), "unresolved_universe_price_tickers": integrity.get("unresolved_universe_price_tickers")},
            "B_costs": {"status": b_status, "all_filled_sides_costed": costs_ok, "commission_rate_each_side": 0.00015, "slippage_rate_each_side": 0.001, "sell_tax_rate": 0},
            "C_profitability": {"status": c_status, "total_return_pct": ret, "cagr_pct": cagr},
            "D_mdd": {"status": d_status, "candidate_mdd_pct": mdd, "control_mdd_pct": control_mdd, "control_mdd_minus_candidate_mdd_pp": relative, "absolute_floor_pct": -40.0, "relative_failure_threshold_pp": 5.0},
            "E_validity": {"status": e_status, "coverage_type": coverage_type, "valid_nav_days": nav_days, "total_valuation_days": total_days, "coverage_pct": None if coverage is None else coverage * 100},
        },
        "whole_five_window_adoption": "NOT_EVALUATED",
        "baseline_promotion": "NOT_EVALUATED",
        "current_official_baseline": "A FAST Core V2",
    }


def dump_group(group: str, result: Mapping[str, Any]) -> None:
    pd.DataFrame(result["events"]).to_csv(OUT / f"{group.lower()}_portfolio_events.csv", index=False)
    pd.DataFrame(result["daily_equity"]).to_csv(OUT / f"{group.lower()}_daily_equity.csv", index=False)
    pd.DataFrame(result["cash_events"]).to_csv(OUT / f"{group.lower()}_cash_events.csv", index=False)
    pd.DataFrame(result["valuation_carry_audit"]).to_csv(OUT / f"{group.lower()}_valuation_audit.csv", index=False)
    pd.DataFrame(result["missing_marks"]).to_csv(OUT / f"{group.lower()}_missing_marks.csv", index=False)
    skipped = [row for row in result["events"] if str(row.get("event_status", "")).startswith("SKIPPED")]
    pd.DataFrame(skipped).to_csv(OUT / f"{group.lower()}_skipped_entries.csv", index=False)


def main() -> int:
    mode = "--full" if "--full" in sys.argv else "--sample"
    started = time.perf_counter()
    cpu_started = time.process_time()
    OUT.mkdir(parents=True, exist_ok=True)
    authority_started = time.perf_counter()
    calendar, pit_payload, calendar_payload, segments_by_ticker = build_authority()
    authority_seconds = time.perf_counter() - authority_started
    all_tickers = sorted(segments_by_ticker)
    sample_mode = mode != "--full"
    tickers = stable_sample_tickers(all_tickers) if sample_mode else all_tickers
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    repository_started = time.perf_counter()
    repository = build_repository_v2(ROOT, end=SUPPORT)
    loader = RepositoryV2DailyLoader(repository, end=SUPPORT)
    mcap = ExactSignalMcap()
    repository_setup_seconds = time.perf_counter() - repository_started
    install_per_ticker_evaluation_cache()

    def work(ticker: str) -> dict[str, Any]:
        return evaluator_rows_for_ticker(
            ticker, loader=loader, calendar=calendar, segments_by_ticker=segments_by_ticker,
            score_contract=score_contract, stage_contract=stage_contract, mcap_resolver=mcap,
        )

    print(f"Starting {mode}: {len(tickers)} tickers / workers={WORKERS}", flush=True)
    evaluation_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p3-2-v2-eval") as pool:
        outcomes = list(pool.map(work, tickers))
    evaluation_seconds = time.perf_counter() - evaluation_started
    control_rows = [row for outcome in outcomes for row in outcome["control_trades"]]
    candidate_rows = [row for outcome in outcomes for row in outcome["candidate_trades"]]
    audit_rows = [row for outcome in outcomes for row in outcome["audits"]]
    audit_rows.sort(key=lambda row: (str(row["signal_date"]), str(row["ticker"]), str(row.get("isu_cd") or "")))
    control_rows.sort(key=lambda row: (row["entry_execution_date"], row["ticker"], row["isu_cd"], row["entry_signal_date"], row["trade_id"]))
    candidate_rows.sort(key=lambda row: (row["entry_execution_date"], row["ticker"], row["isu_cd"], row["entry_signal_date"], row["trade_id"]))

    pd.DataFrame(audit_rows).to_csv(OUT / ("sample_candidate_signal_filter_audit.csv" if sample_mode else "candidate_signal_filter_audit.csv"), index=False)
    pd.DataFrame(control_rows).to_csv(OUT / ("sample_control_trades.csv" if sample_mode else "control_trades.csv"), index=False)
    pd.DataFrame(candidate_rows).to_csv(OUT / ("sample_candidate_trades.csv" if sample_mode else "candidate_trades.csv"), index=False)
    if not sample_mode:
        pd.DataFrame([
            {k: outcome.get(k) for k in ("ticker", "data_status", "daily_rows", "first_daily_date", "last_daily_date", "evaluation_cache_hits", "evaluation_cache_misses")}
            for outcome in outcomes
        ]).to_csv(OUT / "ticker_price_source_audit.csv", index=False)
        partition_rows = []
        for (market, day), (manifest_row, _cap_rows, error) in sorted(mcap.cache.items()):
            partition_rows.append({
                "market": market,
                "partition_date": day,
                "status": None if manifest_row is None else manifest_row.get("status"),
                "file_path": None if manifest_row is None else manifest_row.get("file_path"),
                "file_sha256": None if manifest_row is None else manifest_row.get("file_sha256"),
                "content_sha256": None if manifest_row is None else manifest_row.get("content_sha256"),
                "resolution_error": error,
            })
        pd.DataFrame(partition_rows).to_csv(OUT / "signal_date_krx_partition_hashes.csv", index=False)
        available_tickers = [outcome["ticker"] for outcome in outcomes if outcome.get("data_status") == "AVAILABLE"]
        price_hash_rows = []
        for ticker in available_tickers:
            path = PRICE_DIR / f"{ticker}.parquet"
            price_hash_rows.append({"ticker": ticker, "path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})
        pd.DataFrame(price_hash_rows).to_csv(OUT / "repository_v2_adjusted_price_file_hashes.csv", index=False)

    control_replay_started = time.perf_counter()
    ctx_control = make_portfolio_context(calendar=calendar, segments_by_ticker=segments_by_ticker, repository=repository)
    control_result = replay_group(ctx_control, control_rows)
    control_replay_seconds = time.perf_counter() - control_replay_started
    candidate_replay_started = time.perf_counter()
    ctx_candidate = make_portfolio_context(calendar=calendar, segments_by_ticker=segments_by_ticker, repository=repository)
    candidate_result = replay_group(ctx_candidate, candidate_rows)
    candidate_replay_seconds = time.perf_counter() - candidate_replay_started
    prefix = "sample_" if sample_mode else ""
    for group, result in (("control", control_result), ("candidate", candidate_result)):
        pd.DataFrame(result["events"]).to_csv(OUT / f"{prefix}{group}_portfolio_events.csv", index=False)
        pd.DataFrame(result["daily_equity"]).to_csv(OUT / f"{prefix}{group}_daily_equity.csv", index=False)
        pd.DataFrame(result["cash_events"]).to_csv(OUT / f"{prefix}{group}_cash_events.csv", index=False)
        pd.DataFrame(result["valuation_carry_audit"]).to_csv(OUT / f"{prefix}{group}_valuation_audit.csv", index=False)
        pd.DataFrame(result["missing_marks"]).to_csv(OUT / f"{prefix}{group}_missing_marks.csv", index=False)
        skipped = [row for row in result["events"] if str(row.get("event_status", "")).startswith("SKIPPED")]
        pd.DataFrame(skipped).to_csv(OUT / f"{prefix}{group}_skipped_entries.csv", index=False)

    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss_bytes / (1024 * 1024) if sys.platform != "darwin" else rss_bytes / (1024 * 1024)
    missing_price = sorted(outcome["ticker"] for outcome in outcomes if outcome["data_status"] != "AVAILABLE")
    sample_batches = max(1, math.ceil(len(tickers) / WORKERS))
    full_batches = max(1, math.ceil(len(all_tickers) / WORKERS))
    estimated_full_evaluation = evaluation_seconds * (full_batches / sample_batches)
    portfolio_scale = max(1.0, len(all_tickers) / max(1, len(tickers))) if sample_mode else 1.0
    estimated_full_portfolio = (control_replay_seconds + candidate_replay_seconds) * portfolio_scale
    estimated_full_wall = authority_seconds + repository_setup_seconds + estimated_full_evaluation + estimated_full_portfolio if sample_mode else wall
    control_metrics = control_result["metrics"]
    candidate_metrics = candidate_result["metrics"]
    benchmark = {
        "schema": "fast_core_v2_alignment_500b_sample_benchmark_v01",
        "mode": "SAMPLE" if sample_mode else "FULL",
        "sample_ticker_count": len(tickers),
        "eligible_universe_ticker_count": len(all_tickers),
        "workers": WORKERS,
        "wall_seconds_including_portfolio_replays": round(wall, 3),
        "authority_setup_seconds": round(authority_seconds, 3),
        "repository_index_setup_seconds": round(repository_setup_seconds, 3),
        "signal_generation_seconds": round(evaluation_seconds, 3),
        "control_portfolio_replay_seconds": round(control_replay_seconds, 3),
        "candidate_portfolio_replay_seconds": round(candidate_replay_seconds, 3),
        "cpu_seconds": round(cpu, 3),
        "max_rss_mb": round(rss_mb, 2),
        "evaluator_outcomes": len(outcomes),
        "control_trade_count": len(control_rows),
        "candidate_trade_count": len(candidate_rows),
        "candidate_signal_audit_count": len(audit_rows),
        "frozen_weekly_evaluation_cache_hits": sum(int(outcome.get("evaluation_cache_hits", 0)) for outcome in outcomes),
        "frozen_weekly_evaluation_cache_misses": sum(int(outcome.get("evaluation_cache_misses", 0)) for outcome in outcomes),
        "candidate_signal_rejections": dict(pd.Series([row.get("candidate_status") for row in audit_rows]).value_counts().sort_index()),
        "unresolved_price_tickers": missing_price,
        "raw_signal_date_partition_count_loaded": len(mcap.cache),
        "estimated_full_wall_seconds_linear": round(estimated_full_wall, 3),
        "estimated_full_wall_hours_linear": round(estimated_full_wall / 3600, 4),
        "estimated_full_signal_generation_seconds_by_worker_batches": round(estimated_full_evaluation, 3),
        "estimated_full_portfolio_seconds_conservative_linear_trade_scaling": round(estimated_full_portfolio, 3),
        "estimated_full_wall_seconds_by_staged_estimate": round(estimated_full_wall, 3),
        "estimated_full_wall_hours_by_staged_estimate": round(estimated_full_wall / 3600, 4),
        "control_sample_metrics": control_metrics,
        "candidate_sample_metrics": candidate_metrics,
        "candidate_reentry_state_contract": "entry_signal_filter rejects before trade_seq/position-state advances; verified by frozen evaluator source",
        "portfolio_event_order": "single sequential replay",
        "status": "SAMPLE_COMPLETED" if sample_mode else "FULL_COMPLETED",
    }
    write_json(OUT / ("sample_benchmark.json" if sample_mode else "full_run_execution.json"), benchmark)
    print(json.dumps({k: benchmark[k] for k in ("mode", "sample_ticker_count", "eligible_universe_ticker_count", "workers", "authority_setup_seconds", "repository_index_setup_seconds", "signal_generation_seconds", "control_portfolio_replay_seconds", "candidate_portfolio_replay_seconds", "wall_seconds_including_portfolio_replays", "cpu_seconds", "max_rss_mb", "frozen_weekly_evaluation_cache_hits", "frozen_weekly_evaluation_cache_misses", "control_trade_count", "candidate_trade_count", "candidate_signal_audit_count", "estimated_full_signal_generation_seconds_by_worker_batches", "estimated_full_portfolio_seconds_conservative_linear_trade_scaling", "estimated_full_wall_hours_by_staged_estimate", "unresolved_price_tickers", "status")}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
