"""Julia Strategy V00 and 2022+ Controlled Comparative Backtest Engine.

Core Strategy Mandate:
  - Base Strategy: PATTERN_A_FAST_FINAL_STRATEGY_V02 (A FAST Core V2)
  - Experiment: JULIA_STRATEGY_V00
  - Classification: EXPLORATORY_CANDIDATE / SAME_SAMPLE_RETROSPECTIVE
  - ONLY ONE DELTA: Pre-PROGRESSED Loss Guard (ON at -15% -> OFF)
  - Evaluation Window: 2022-01-01 to 2026-08-14
  - Initial Position State: FLAT
  - Lookback: Full pre-2022 history used for signal and feature calculation (Lookback != Window)
  - Strict PIT Historical Investability: Point-in-time exact KRX snapshot, Fail Closed on missing dates.
  - Manifest-Driven Strict Provenance: Dual SHA (Source + Normalized) verification, no silent fallbacks.
"""

from __future__ import annotations

import bisect
from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityEvaluationResult,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    DATA_CUTOFF,
    calculate_distribution_stats,
)

logger = logging.getLogger(__name__)

EVALUATION_START_DATE = pd.Timestamp("2022-01-01")
EVALUATION_END_DATE = DATA_CUTOFF  # 2026-08-14

VALID_CHANNELS = {
    "KRX_DATA_MARKETPLACE_UI_CSV",
    "KRX_DATA_MARKETPLACE_JSON_ENDPOINT",
    "KRX_OPEN_API",
}


class HistoricalMarketCapIntegrityError(Exception):
    """Raised when historical market cap manifest or source file fails integrity verification."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class HistoricalMarketCapRegistry:
    snapshots: dict[str, dict[str, float]]
    metadata: dict[str, dict[str, Any]]

    @classmethod
    def load_from_repository(cls, root: Path, enforce_integrity: bool = True) -> HistoricalMarketCapRegistry:
        manifest_path = root / "artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv"
        history_dir = root / "artifacts/patterns/pattern_a/validation/investability_history"
        grid_path = history_dir / "krx_market_cap_reference_grid_v01.csv"

        snapshots: dict[str, dict[str, float]] = {}
        metadata: dict[str, dict[str, Any]] = {}

        # 1. Manifest Authority (Strict Fail-Closed, No Fallback if Manifest Exists)
        if manifest_path.exists():
            df_man = pd.read_csv(manifest_path, dtype=str).fillna("")
            for _, row in df_man.iterrows():
                sig_d = str(row.get("signal_reference_date", "")).strip()
                avail_str = str(row.get("available", "")).strip().lower()
                integ_status = str(row.get("integrity_status", "")).strip()

                is_available = (avail_str == "true") and (integ_status == "PASS")
                if not is_available:
                    continue

                provider = str(row.get("source_provider", "")).strip()
                channel = str(row.get("source_channel", "")).strip()
                role = str(row.get("source_role", "")).strip()
                auth_status = str(row.get("authority_status", "")).strip()
                eff_d = str(row.get("effective_date", "")).strip()
                raw_rel = str(row.get("raw_source_file", "")).strip()
                norm_rel = str(row.get("normalized_source_file", "")).strip()
                manifest_raw_sha = str(row.get("raw_sha256", "")).strip()
                manifest_norm_sha = str(row.get("normalized_sha256", "")).strip()

                if enforce_integrity:
                    if provider != "KRX":
                        raise HistoricalMarketCapIntegrityError(f"Invalid provider for {sig_d}: '{provider}'")
                    if channel not in VALID_CHANNELS:
                        raise HistoricalMarketCapIntegrityError(f"Invalid channel for {sig_d}: '{channel}'")
                    if not role:
                        raise HistoricalMarketCapIntegrityError(f"Missing source_role for {sig_d}")
                    if not auth_status:
                        raise HistoricalMarketCapIntegrityError(f"Missing authority_status for {sig_d}")
                    if not eff_d or pd.Timestamp(eff_d) > pd.Timestamp(sig_d):
                        raise HistoricalMarketCapIntegrityError(f"Effective date {eff_d} > signal date {sig_d}")
                    if not raw_rel:
                        raise HistoricalMarketCapIntegrityError(f"Missing raw_source_file in manifest for {sig_d}")
                    if not norm_rel:
                        raise HistoricalMarketCapIntegrityError(f"Missing normalized_source_file in manifest for {sig_d}")
                    if not manifest_raw_sha:
                        raise HistoricalMarketCapIntegrityError(f"Missing raw_sha256 in manifest for {sig_d}")
                    if not manifest_norm_sha:
                        raise HistoricalMarketCapIntegrityError(f"Missing normalized_sha256 in manifest for {sig_d}")

                raw_p = root / raw_rel
                norm_p = root / norm_rel

                if not raw_p.exists():
                    raise HistoricalMarketCapIntegrityError(f"Source file does not exist: {raw_p}")
                if not norm_p.exists():
                    raise HistoricalMarketCapIntegrityError(f"Normalized file does not exist: {norm_p}")

                if enforce_integrity:
                    actual_raw_sha = _sha256_file(raw_p)
                    if actual_raw_sha != manifest_raw_sha:
                        raise HistoricalMarketCapIntegrityError(
                            f"Source SHA mismatch for {sig_d}: expected {manifest_raw_sha}, got {actual_raw_sha}"
                        )
                    actual_norm_sha = _sha256_file(norm_p)
                    if actual_norm_sha != manifest_norm_sha:
                        raise HistoricalMarketCapIntegrityError(
                            f"Normalized SHA mismatch for {sig_d}: expected {manifest_norm_sha}, got {actual_norm_sha}"
                        )

                df = pd.read_csv(norm_p, dtype={"ticker": str})
                if df.empty or "ticker" not in df.columns or "market_cap" not in df.columns:
                    raise HistoricalMarketCapIntegrityError(f"Corrupt normalized file: {norm_p}")

                if enforce_integrity:
                    if df["ticker"].duplicated().any():
                        raise HistoricalMarketCapIntegrityError(f"Duplicate tickers in {norm_p}")
                    if not (df["market_cap"].dropna().astype(float) > 0).all():
                        raise HistoricalMarketCapIntegrityError(f"Non-positive market cap in {norm_p}")

                df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                mcaps = dict(zip(df["ticker"], df["market_cap"].astype(float)))
                snapshots[sig_d] = mcaps
                metadata[sig_d] = {
                    "source_provider": provider,
                    "source_channel": channel,
                    "source_role": role,
                    "source_file": raw_rel,
                    "normalized_file": norm_rel,
                    "source_sha256": manifest_raw_sha,
                    "normalized_sha256": manifest_norm_sha,
                    "requested_date": str(row.get("requested_date", "")).strip(),
                    "effective_date": eff_d,
                    "signal_reference_date": sig_d,
                    "authority_status": auth_status,
                }

            if snapshots:
                return cls(snapshots=snapshots, metadata=metadata)
            else:
                raise HistoricalMarketCapIntegrityError("Manifest contains zero available valid snapshots.")

        # 2. Legacy Fallback ONLY if Manifest does not exist at all
        if grid_path.exists():
            grid = pd.read_csv(grid_path, dtype=str)
            for _, row in grid.iterrows():
                eff_d = str(row["completed_weekly_reference_date"]).strip()
                src_file = str(row["source_file"]).strip()
                src_name = Path(src_file).name
                norm_file = history_dir / "normalized" / src_name
                if norm_file.exists():
                    df = pd.read_csv(norm_file, dtype={"ticker": str})
                    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                    mcaps = dict(zip(df["ticker"], df["market_cap"].astype(float)))
                    snapshots[eff_d] = mcaps
                    metadata[eff_d] = {
                        "source_provider": "KRX",
                        "source_channel": "KRX_DATA_MARKETPLACE_UI_CSV",
                        "source_role": "CANONICAL_RAW_UI_EXPORT",
                        "source_file": str(norm_file.relative_to(root)),
                        "normalized_file": str(norm_file.relative_to(root)),
                        "source_sha256": str(row.get("sha256", "")),
                        "normalized_sha256": str(row.get("sha256", "")),
                        "requested_date": eff_d,
                        "effective_date": eff_d,
                        "signal_reference_date": eff_d,
                        "authority_status": "CANONICAL_UI_AUTHORITY",
                    }

        return cls(snapshots=snapshots, metadata=metadata)

    @property
    def available_dates(self) -> set[str]:
        return set(self.snapshots.keys())

    def get_market_cap_at_reference(self, ticker: str, reference_date: str) -> tuple[float | None, dict[str, Any] | None]:
        if reference_date not in self.snapshots:
            return None, None
        mcap = self.snapshots[reference_date].get(ticker)
        meta = self.metadata.get(reference_date)
        return mcap, meta


@dataclass
class StrategyTradeRecord:
    strategy_id: str
    pre_progressed_loss_guard_enabled: bool

    ticker: str
    name: str
    market: str
    trade_id: str
    trade_sequence: int

    entry_signal_date: str
    entry_execution_date: str
    entry_open: float

    entry_pattern_a_stage: str
    fast_stage: str
    monthly_regime: str
    daily_risk: str
    fast_score: float | None
    fast_score_state: str

    # Historical Investability Provenance
    investability_status: str
    investability_market_cap: float | None
    investability_avg_trading_value_20d: float | None
    investability_market_cap_source_file: str | None

    previous_exit_type: str | None
    previous_exit_execution_date: str | None

    loss_guard_triggered: bool
    loss_guard_signal_date: str | None
    loss_guard_execution_date: str | None
    loss_guard_execution_price: float | None

    first_progressed_date: str | None
    first_progressed_effective_trading_date: str | None

    lifecycle_class: str

    exit_type: str
    exit_signal_date: str | None
    exit_execution_date: str | None
    exit_price: float | None

    terminal_return: float
    mfe: float
    mae: float
    peak_giveback: float
    profit_capture: float | None
    holding_weeks: float
    trade_status: str
    investability_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _calc_trade_outcome(
    entry_exec_d: pd.Timestamp,
    entry_open: float,
    exit_sig_d: pd.Timestamp | None,
    daily: pd.DataFrame,
    cutoff_date: pd.Timestamp,
) -> dict[str, Any]:
    exit_exec_d: pd.Timestamp | None = None
    exit_open: float | None = None
    trade_status: str = "OPEN_AT_CUTOFF"
    realized_ret: float | None = None
    mark_to_cutoff_ret: float | None = None

    if exit_sig_d is not None:
        fut_after_exit = daily[(daily.index > exit_sig_d) & (daily.index <= cutoff_date)]
        if not fut_after_exit.empty:
            exit_exec_d = fut_after_exit.index[0]
            exit_open = float(fut_after_exit.iloc[0]["open"])
            trade_status = "REALIZED"
            realized_ret = round(((exit_open - entry_open) / entry_open) * 100, 2)
        else:
            trade_status = "OPEN_AT_CUTOFF"

    if trade_status == "REALIZED" and exit_exec_d is not None and exit_open is not None:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index < exit_exec_d)]
        holding_days = len(daily[(daily.index >= entry_exec_d) & (daily.index <= exit_exec_d)])
        holding_weeks = round(holding_days / 5.0, 1)

        if not holding_daily.empty:
            high_cand = holding_daily["high"].tolist() + [exit_open]
            low_cand = holding_daily["low"].tolist() + [exit_open]
            peak_price = float(max(high_cand))
            min_price = float(min(low_cand))
        else:
            peak_price = float(max(entry_open, exit_open))
            min_price = float(min(entry_open, exit_open))

        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = realized_ret
    else:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
        holding_days = len(holding_daily)
        holding_weeks = round(holding_days / 5.0, 1)

        cutoff_close = float(holding_daily.iloc[-1]["close"]) if not holding_daily.empty else entry_open
        mark_to_cutoff_ret = round(((cutoff_close - entry_open) / entry_open) * 100, 2)

        peak_price = float(holding_daily["high"].max()) if not holding_daily.empty else entry_open
        min_price = float(holding_daily["low"].min()) if not holding_daily.empty else entry_open

        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = mark_to_cutoff_ret

    terminal_gb = round(mfe - terminal_ret, 2)
    terminal_pc = round(terminal_ret / mfe, 4) if mfe > 0 else None

    return {
        "exit_exec_d": exit_exec_d,
        "exit_open": exit_open,
        "trade_status": trade_status,
        "realized_ret": realized_ret,
        "mark_to_cutoff_ret": mark_to_cutoff_ret,
        "terminal_ret": terminal_ret,
        "mfe": mfe,
        "mae": mae,
        "terminal_giveback": terminal_gb,
        "terminal_profit_capture": terminal_pc,
        "holding_days": holding_days,
        "holding_weeks": holding_weeks,
    }


def simulate_ticker_strategy_2022(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    enable_loss_guard: bool,
    market_cap_registry: Any | None = None,
    start_date: pd.Timestamp = EVALUATION_START_DATE,
    cutoff_date: pd.Timestamp = EVALUATION_END_DATE,
    sensitivity_mode: bool = False,
    fast_snapshot_cache: Any | None = None,
    monthly_snapshot_cache: Any | None = None,
    min_market_cap_krw: float = MIN_MARKET_CAP_KRW,
    snapshot_context: Any | None = None,
    enable_pre_window_pruning: bool = True,
) -> list[StrategyTradeRecord]:
    """Simulate a single ticker trade lifecycle starting from start_date (2022-01-01+).

    ``snapshot_context`` (optional, BACKTEST_PERFORMANCE_ENGINEERING_V01
    Phase 4): a ``PrecomputedTickerContext`` (see
    ``trend_scanner.backtest.snapshot_context``) built once for THIS
    ticker's full daily history. When given, it is forwarded to
    ``fast_snapshot_cache``/``monthly_snapshot_cache`` so a cache miss uses
    the optimized snapshot-reuse path instead of re-resampling the full
    daily history on every miss. Omitted (default): behavior is
    byte-for-byte identical to today.

    ``min_market_cap_krw`` externalizes the investability market-cap
    eligibility gate as a research parameter (w.md Section 20 "Market Cap
    Threshold Architecture"). Default is unchanged
    (``MIN_MARKET_CAP_KRW`` = 100B, the production investability default);
    passing a different value only changes which candidates pass the
    strict-INVESTABLE gate below, and never touches
    ``filters.investability.MIN_MARKET_CAP_KRW`` itself.

    ``enable_pre_window_pruning`` (default True, BACKTEST_PERFORMANCE_ENGINEERING_V01
    Phase 4.1 Major Fix 2): skips straight to the earliest week whose next
    trading day could possibly be >= start_date, instead of evaluating
    every FAST snapshot from the ticker's very first valid week onward.
    Trade output is identical either way (this only prunes weeks that could
    never produce a usable signal); set False only for a legacy-equivalent
    before/after benchmark comparison within the same process.

    ``fast_snapshot_cache``/``monthly_snapshot_cache`` are optional
    strategy-invariant memoization caches (see
    ``trend_scanner.backtest.feature_cache``): ``evaluate_pattern_a_fast``
    and the monthly Pattern A snapshot are pure functions of
    ``(ticker, reference_date)`` given fixed ``daily``/contracts, independent
    of ``enable_loss_guard``/``sensitivity_mode``. When omitted (default),
    behavior is byte-for-byte identical to the original inline
    try/except evaluation -- this parameter never changes strategy output,
    only whether an already-computed result is reused.
    """
    # w.md Phase 4.1 Sections 7-8: when a PrecomputedTickerContext is given,
    # reuse its already-sorted daily and already-resampled weekly/monthly
    # (via the same tail-bucket-safe cutoff-safe views used for per-snapshot
    # construction) instead of repeating sort_index()/to_weekly()/
    # to_monthly() on every one of the 4 Baseline/Julia x Primary/
    # Sensitivity passes for this ticker. Legacy path (no context) is
    # completely unchanged.
    if snapshot_context is not None:
        if snapshot_context.daily.empty:
            return []
        daily = snapshot_context.daily_up_to(cutoff_date)
    else:
        if daily is None or daily.empty:
            return []
        daily = daily.sort_index()
        daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns) or len(daily) < 60:
        return []

    if snapshot_context is not None:
        weekly_bars = snapshot_context.weekly_up_to(cutoff_date)
        valid_weeks = snapshot_context.valid_weeks_up_to(cutoff_date)
    else:
        weekly_bars = to_weekly(daily)
        # A weekly label w's bar is "completed" (this ticker actually traded up
        # through the label date, i.e. daily[daily.index <= w].index.max() == w)
        # iff w itself is one of the ticker's own trading dates: if w is present
        # in daily.index, the last date <= w is trivially w itself; if w is
        # absent (e.g. a holiday Friday), the last date <= w is strictly earlier.
        # This turns an O(len(weekly_bars) * len(daily)) boolean-mask-per-week
        # scan into O(len(weekly_bars)) O(1) set lookups, with no semantic
        # change (w.md Phase 4 Section 8, VALID_WEEK_SET_MISMATCH=0 proof in
        # tests/test_backtest_performance_engine_v01_snapshot_context.py).
        _daily_dates_set = set(daily.index)
        valid_weeks = [w for w in weekly_bars.index if w in _daily_dates_set]

    if not valid_weeks:
        return []

    monthly_bars = snapshot_context.monthly_up_to(cutoff_date) if snapshot_context is not None else to_monthly(daily)

    strategy_id = "PATTERN_A_FAST_FINAL_STRATEGY_V02" if enable_loss_guard else "JULIA_STRATEGY_V00"

    trades: list[StrategyTradeRecord] = []
    trade_seq = 0

    # w.md Phase 4.1 Major Fix 2 (Section 5): a FAST-trigger signal at week w
    # can only ever produce a valid entry if next_trading_day_after(w) >=
    # start_date -- entries execute on the next trading day after the
    # signal week, and any entry before start_date is unconditionally
    # discarded later (the pre-existing `candidate_exec_d < start_date:
    # continue` check). Skipping straight to the earliest week that COULD
    # satisfy this avoids evaluating FAST snapshots for weeks whose result
    # can never matter (e.g. 2016-2021 history for a long-listed ticker),
    # while still keeping the late-2021-signal -> first-2022-trading-day-
    # execution case eligible (that week's next trading day is itself
    # >= start_date, so it is NOT pruned).
    daily_dates_sorted = list(daily.index)

    def _next_trading_day_or_far_future(w: pd.Timestamp) -> pd.Timestamp:
        pos = bisect.bisect_right(daily_dates_sorted, w)
        return daily_dates_sorted[pos] if pos < len(daily_dates_sorted) else pd.Timestamp.max

    def _next_trading_day_position(d: pd.Timestamp) -> int | None:
        """w.md Phase 4.1 Section 10: searchsorted-based equivalent of
        ``daily[(daily.index > d) & (daily.index <= cutoff_date)].index[0]``
        (daily is already cutoff-truncated, so the extra upper bound is a
        no-op here). Returns the position in daily_dates_sorted / daily.iloc,
        or None if there is no later trading day."""
        pos = bisect.bisect_right(daily_dates_sorted, d)
        return pos if pos < len(daily_dates_sorted) else None

    def _last_trading_day_position_on_or_before(d: pd.Timestamp) -> int | None:
        """w.md Phase 4.1 Section 12: searchsorted-based equivalent of
        ``daily[daily.index <= d].index.max()`` (returned as a position, not
        a date, so callers needing the row too don't pay for a second lookup)."""
        pos = bisect.bisect_right(daily_dates_sorted, d) - 1
        return pos if pos >= 0 else None

    if enable_pre_window_pruning:
        pre_window_start_idx = bisect.bisect_left(valid_weeks, start_date, key=_next_trading_day_or_far_future)
    else:
        pre_window_start_idx = 0

    cur_search_date: pd.Timestamp | None = valid_weeks[pre_window_start_idx] if pre_window_start_idx < len(valid_weeks) else None
    if cur_search_date is None:
        return []
    prev_exit_type: str | None = None
    prev_exit_exec_date: str | None = None

    while cur_search_date is not None and cur_search_date <= cutoff_date:
        found_signal_w: pd.Timestamp | None = None
        found_signal_res: dict | None = None
        entry_exec_date: pd.Timestamp | None = None
        entry_open_price: float | None = None
        inv_eval_record: InvestabilityEvaluationResult | None = None
        inv_source_meta: dict[str, Any] | None = None

        # valid_weeks is sorted ascending (built from weekly_bars.index in
        # order); bisect finds the first index >= cur_search_date directly
        # instead of scanning the full list every outer-loop iteration.
        candidate_weeks = valid_weeks[bisect.bisect_left(valid_weeks, cur_search_date):]
        for w in candidate_weeks:
            try:
                if fast_snapshot_cache is not None:
                    res = fast_snapshot_cache.get(ticker, name, daily, w, score_contract, stage_contract, context=snapshot_context)
                    if res is None:
                        continue
                elif snapshot_context is not None:
                    res = evaluate_pattern_a_fast(ticker, name, daily, w, score_contract, stage_contract, context=snapshot_context)
                else:
                    res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
                is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
                is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
                is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
                is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
                is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)

                raw_stage = res.get("pattern_a_stage")
                pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

                if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"}:
                    next_pos = _next_trading_day_position(w)
                    if next_pos is None:
                        continue
                    candidate_exec_d = daily_dates_sorted[next_pos]
                    if candidate_exec_d < start_date:
                        continue

                    # Strict Historical Investability PIT Gate
                    w_str = w.strftime("%Y-%m-%d")
                    mcap_val = None
                    src_meta = None
                    if market_cap_registry is not None:
                        try:
                            mcap_val, src_meta = market_cap_registry.get_market_cap_at_reference(
                                ticker, w_str, sensitivity_mode=sensitivity_mode
                            )
                        except TypeError:
                            mcap_val, src_meta = market_cap_registry.get_market_cap_at_reference(ticker, w_str)

                    if snapshot_context is not None:
                        daily_as_of = snapshot_context.slice_daily_up_to(w)
                    else:
                        w_pos = _last_trading_day_position_on_or_before(w)
                        daily_as_of = daily.iloc[: w_pos + 1] if w_pos is not None else daily.iloc[0:0]
                    inv_res = evaluate_investability(
                        ticker=ticker,
                        as_of=w,
                        daily=daily_as_of,
                        market_cap=mcap_val,
                        market_cap_effective_date=w_str if mcap_val is not None else None,
                        min_market_cap_krw=min_market_cap_krw,
                        min_avg_trading_value_20d_krw=MIN_AVG_TRADING_VALUE_20D_KRW,
                    )

                    # Fail Closed: Must be strictly INVESTABLE
                    if inv_res.status != InvestabilityStatus.INVESTABLE:
                        continue

                    found_signal_w = w
                    found_signal_res = res
                    entry_exec_date = candidate_exec_d
                    entry_open_price = float(daily.iloc[next_pos]["open"])
                    inv_eval_record = inv_res
                    inv_source_meta = src_meta
                    break
            except Exception:
                continue

        if (
            found_signal_w is None
            or found_signal_res is None
            or entry_exec_date is None
            or entry_open_price is None
            or inv_eval_record is None
        ):
            break

        trade_seq += 1
        trade_id = f"{ticker}_{trade_seq:02d}"

        pa_stage_at_entry = (found_signal_res["pattern_a_stage"] or "").upper()
        fast_score = found_signal_res.get("fast_score")
        fast_score_avail = found_signal_res.get("fast_score_status", "UNKNOWN")
        daily_risk = found_signal_res.get("fast_daily_risk_state", "UNKNOWN")
        monthly_regime = found_signal_res.get("fast_monthly_permission_state", "UNKNOWN")

        m_dates = [
            m for m in monthly_bars.index
            if m >= found_signal_w and m <= cutoff_date
        ]

        monthly_snapshots: list[dict[str, Any]] = []
        for m in m_dates:
            if monthly_snapshot_cache is not None:
                monthly_snapshots.append(monthly_snapshot_cache.get(ticker, name, daily, m, context=snapshot_context))
                continue
            try:
                if snapshot_context is not None:
                    snap = build_historical_snapshot_from_context(snapshot_context, m, include_incomplete_periods=False)
                else:
                    snap = build_historical_snapshot(ticker, name, daily[daily.index <= m], m, include_incomplete_periods=False)
                eval_res = evaluate_pattern_a(snap)
                st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
                sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
                monthly_snapshots.append({"date": m, "stage": st, "score": sc})
            except Exception:
                monthly_snapshots.append({"date": m, "stage": "UNAVAILABLE", "score": None})

        first_early_trend_d: pd.Timestamp | None = found_signal_w if pa_stage_at_entry == "EARLY_TREND" else None
        direct_handoff_observed = False
        early_trend_to_prog_d: pd.Timestamp | None = None
        first_progressed_d: pd.Timestamp | None = None
        first_prog_score: float | None = None
        skipped_handoff = False
        progressed_observed = False

        prev_valid_stage = pa_stage_at_entry
        had_early_trend = (pa_stage_at_entry == "EARLY_TREND")

        for row in monthly_snapshots:
            m = row["date"]
            st = row["stage"]
            sc = row["score"]

            if st == "UNAVAILABLE":
                continue

            if st == "EARLY_TREND":
                had_early_trend = True
                if first_early_trend_d is None:
                    first_early_trend_d = m

            if st == "PROGRESSED":
                progressed_observed = True
                if first_progressed_d is None:
                    first_progressed_d = m
                    first_prog_score = sc

                if prev_valid_stage == "EARLY_TREND" and not direct_handoff_observed:
                    direct_handoff_observed = True
                    early_trend_to_prog_d = m
                elif (
                    prev_valid_stage == "TRANSITION"
                    and not had_early_trend
                    and not direct_handoff_observed
                    and not skipped_handoff
                ):
                    skipped_handoff = True

            prev_valid_stage = st

        if direct_handoff_observed and early_trend_to_prog_d is not None:
            coverage_path = "NORMAL_EARLY_TREND_HANDOFF"
        elif skipped_handoff:
            coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"
        elif progressed_observed:
            coverage_path = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
        else:
            coverage_path = "NEVER_PROGRESSED"

        # Pre-PROGRESSED Loss Guard Check
        first_prog_eff_trading_d: pd.Timestamp | None = None
        if first_progressed_d is not None:
            _fp_pos = _last_trading_day_position_on_or_before(first_progressed_d)
            if _fp_pos is not None:
                first_prog_eff_trading_d = daily_dates_sorted[_fp_pos]
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index < first_prog_eff_trading_d)]
        else:
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index <= cutoff_date)]

        loss_guard_triggered = False
        loss_guard_sig_d: pd.Timestamp | None = None
        loss_guard_exec_d: pd.Timestamp | None = None
        loss_guard_exec_price: float | None = None

        if enable_loss_guard:
            for d, row in pre_prog_daily.iterrows():
                c_price = float(row["close"])
                if (c_price / entry_open_price - 1.0) <= -0.15:
                    loss_guard_triggered = True
                    loss_guard_sig_d = d
                    fut_after_stop = daily[(daily.index > d) & (daily.index <= cutoff_date)]
                    if not fut_after_stop.empty:
                        loss_guard_exec_d = fut_after_stop.index[0]
                        loss_guard_exec_price = float(fut_after_stop.iloc[0]["open"])
                    break

        # Simulate PROGRESSED Exits (E2: Exit 3 + Exit 4 + Coverage)
        e2_sig_d: pd.Timestamp | None = None
        e2_exit_type: str | None = None

        if coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
            in_p = False
            hwm_1 = None
            for row in monthly_snapshots:
                m = row["date"]
                st = row["stage"]
                sc = row["score"]
                if m < early_trend_to_prog_d:
                    continue
                if m == early_trend_to_prog_d:
                    in_p = True
                    hwm_1 = sc if sc is not None else 0.0
                    continue
                if in_p:
                    if st == "PROGRESSED":
                        if sc is not None and hwm_1 is not None:
                            hwm_1 = max(hwm_1, sc)
                            if hwm_1 - sc >= 15.0:
                                e2_sig_d = m
                                e2_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                break
                    elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                        e2_sig_d = m
                        e2_exit_type = f"EXIT3_PROGRESSED_TO_{st}"
                        break
            if e2_sig_d is None:
                e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"

        elif coverage_path in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
            if first_progressed_d is not None:
                hwm_2 = first_prog_score if first_prog_score is not None else 0.0
                in_p = True
                for row in monthly_snapshots:
                    m = row["date"]
                    st = row["stage"]
                    sc = row["score"]
                    if m <= first_progressed_d:
                        continue
                    if in_p:
                        if st == "PROGRESSED":
                            if sc is not None:
                                hwm_2 = max(hwm_2, sc)
                                if hwm_2 - sc >= 15.0:
                                    e2_sig_d = m
                                    e2_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                    break
                        else:
                            in_p = False
                            break
                if e2_sig_d is None:
                    e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"
            else:
                e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"
        else:
            e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"

        # Final trade outcome determination
        if loss_guard_triggered and loss_guard_sig_d is not None:
            final_sig_d = loss_guard_sig_d
            final_exit_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
        else:
            final_sig_d = e2_sig_d
            final_exit_type = e2_exit_type or "NO_EXIT"

        res_outcome = _calc_trade_outcome(entry_exec_date, entry_open_price, final_sig_d, daily, cutoff_date)

        record = StrategyTradeRecord(
            strategy_id=strategy_id,
            pre_progressed_loss_guard_enabled=enable_loss_guard,
            ticker=ticker,
            name=name,
            market=market,
            trade_id=trade_id,
            trade_sequence=trade_seq,
            entry_signal_date=found_signal_w.strftime("%Y-%m-%d"),
            entry_execution_date=entry_exec_date.strftime("%Y-%m-%d"),
            entry_open=round(entry_open_price, 2),
            entry_pattern_a_stage=pa_stage_at_entry,
            fast_stage="TRIGGER",
            monthly_regime=monthly_regime,
            daily_risk=daily_risk,
            fast_score=round(fast_score, 2) if fast_score is not None else None,
            fast_score_state=fast_score_avail,
            investability_status=inv_eval_record.status.value,
            investability_market_cap=inv_eval_record.market_cap,
            investability_avg_trading_value_20d=inv_eval_record.avg_trading_value_20d,
            investability_market_cap_source_file=inv_source_meta.get("source_file") if inv_source_meta else None,
            previous_exit_type=prev_exit_type,
            previous_exit_execution_date=prev_exit_exec_date,
            loss_guard_triggered=loss_guard_triggered,
            loss_guard_signal_date=loss_guard_sig_d.strftime("%Y-%m-%d") if loss_guard_sig_d else None,
            loss_guard_execution_date=loss_guard_exec_d.strftime("%Y-%m-%d") if loss_guard_exec_d else None,
            loss_guard_execution_price=round(loss_guard_exec_price, 2) if loss_guard_exec_price is not None else None,
            first_progressed_date=first_progressed_d.strftime("%Y-%m-%d") if first_progressed_d else None,
            first_progressed_effective_trading_date=first_prog_eff_trading_d.strftime("%Y-%m-%d") if first_prog_eff_trading_d else None,
            lifecycle_class=coverage_path,
            exit_type=final_exit_type,
            exit_signal_date=final_sig_d.strftime("%Y-%m-%d") if final_sig_d else None,
            exit_execution_date=res_outcome["exit_exec_d"].strftime("%Y-%m-%d") if res_outcome["exit_exec_d"] else None,
            exit_price=round(res_outcome["exit_open"], 2) if res_outcome["exit_open"] is not None else None,
            terminal_return=res_outcome["terminal_ret"],
            mfe=res_outcome["mfe"],
            mae=res_outcome["mae"],
            peak_giveback=res_outcome["terminal_giveback"],
            profit_capture=res_outcome["terminal_profit_capture"],
            holding_weeks=res_outcome["holding_weeks"],
            trade_status=res_outcome["trade_status"],
            investability_meta=inv_source_meta or {},
        )
        trades.append(record)

        # Update state for next search (Reentry)
        prev_exit_type = final_exit_type
        if res_outcome["trade_status"] == "REALIZED" and res_outcome["exit_exec_d"] is not None:
            prev_exit_exec_date = res_outcome["exit_exec_d"].strftime("%Y-%m-%d")
            cur_search_date = res_outcome["exit_exec_d"]
        else:
            cur_search_date = None
            break

    return trades
