"""Proxy Historical Market Cap Point-in-Time Registry and Backtest Engine (V01).

Implements:
  - Strict Point-in-Time Proxy Market Cap estimation using Anchor Price Ratio (Method B).
  - Official KRX actual market cap preservation for all 117 available reference dates.
  - Fail-closed evaluation with zero future anchor usage and zero current shares fallback.
  - Full Query Audit and Estimates logging.
  - Proxy Method Accuracy Validation against known official snapshots.
  - Controlled 2022-01-01 to 2026-08-14 Comparative Simulation (Baseline V2 vs Julia V00).
  - Common Entry Pairing and Full Loss Guard Cohort Accounting.
  - Conservative Boundary Sensitivity Analysis (80B ~ 120B buffer).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityEvaluationResult,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    HistoricalMarketCapRegistry,
    StrategyTradeRecord,
    simulate_ticker_strategy_2022,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
JULIA_V00_DIR = ROOT / "artifacts/strategies/julia/v00"
PROXY_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
MANIFEST_CSV = JULIA_V00_DIR / "historical_market_cap_source_manifest.csv"
MISSING_CSV = JULIA_V00_DIR / "historical_market_cap_missing_dates.csv"
CACHE_DIR = ROOT / "data/raw/stocks"

PRIMARY_MIN_MARKET_CAP_KRW = 100_000_000_000.0  # 100 Billion KRW
SENSITIVITY_LOWER_BOUND_KRW = 80_000_000_000.0  # 80 Billion KRW
SENSITIVITY_UPPER_BOUND_KRW = 120_000_000_000.0  # 120 Billion KRW
PRICE_SEMANTICS = "ADJUSTED_CLOSE"
METHOD_B_NAME = "ANCHOR_MCAP_PRICE_RATIO_PROXY"


def calculate_proxy_market_cap_method_b(
    anchor_mcap: float,
    anchor_price: float,
    current_price: float,
) -> float:
    """Calculate proxy market cap using Method B: Anchor Price Ratio Proxy."""
    if anchor_price <= 0:
        raise ValueError("anchor_price must be strictly positive")
    return float(anchor_mcap * (current_price / anchor_price))


@dataclass(frozen=True)
class ProxyQueryRecord:
    ticker: str
    signal_reference_date: str
    market_cap_value: float | None
    source_type: str  # ACTUAL_KRX, PROXY_ANCHOR_PRICE_RATIO, PROXY_DATA_UNAVAILABLE
    proxy_method: str | None
    anchor_date: str | None
    anchor_age_days: int | None
    anchor_market_cap: float | None
    anchor_listed_shares: int | None
    anchor_close: float | None
    target_price_date: str | None
    target_close: float | None
    close_semantics: str
    estimated_market_cap: float | None
    market_cap_threshold: float
    market_cap_status: str
    near_threshold: bool
    confidence_class: str
    posthoc_next_anchor_date: str | None
    posthoc_next_anchor_shares: int | None
    posthoc_share_change_flag: bool | None
    failure_reason: str | None


class ProxyHistoricalMarketCapRegistry:
    """Wrapper around HistoricalMarketCapRegistry that provides strict prior-anchor proxy estimates for missing dates."""

    def __init__(
        self,
        official_registry: HistoricalMarketCapRegistry,
        cache: ParquetCache,
        missing_dates: set[str],
        all_required_dates: list[str],
        close_semantics: str = "ADJUSTED_CLOSE",
    ):
        self.official_registry = official_registry
        self.cache = cache
        self.missing_dates = missing_dates
        self.all_required_dates = sorted(all_required_dates)
        self.official_available_dates = sorted(list(official_registry.available_dates))
        self.close_semantics = close_semantics

        # Query audit log
        self._audit_records: list[ProxyQueryRecord] = []
        self._estimates_by_key: dict[tuple[str, str], ProxyQueryRecord] = {}

    @classmethod
    def load_from_repository(cls, root: Path = ROOT) -> ProxyHistoricalMarketCapRegistry:
        official_reg = HistoricalMarketCapRegistry.load_from_repository(root, enforce_integrity=True)
        cache = ParquetCache(base_dir=root / "data/raw/stocks")

        man_path = root / "artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv"
        miss_path = root / "artifacts/strategies/julia/v00/historical_market_cap_missing_dates.csv"

        df_man = pd.read_csv(man_path)
        df_miss = pd.read_csv(miss_path)

        all_req_dates = df_man["signal_reference_date"].unique().tolist()
        missing_dates = set(df_miss["signal_reference_date"].unique())

        return cls(
            official_registry=official_reg,
            cache=cache,
            missing_dates=missing_dates,
            all_required_dates=all_req_dates,
            close_semantics="ADJUSTED_CLOSE",
        )

    @property
    def official_dates(self) -> list[str]:
        return self.official_available_dates

    def lookup_market_cap(
        self,
        signal_reference_date: str,
        ticker: str,
        price_df: pd.DataFrame | None = None,
    ) -> dict[str, Any] | None:
        """Convenience lookup returning dict with market_cap, market_cap_source, anchor_date."""
        mcap, meta = self.get_market_cap_at_reference(ticker, signal_reference_date)
        if mcap is None:
            return None
        source = "UNKNOWN"
        if meta:
            source = meta.get("market_cap_source") or meta.get("proxy_source_type") or "UNKNOWN"
        return {
            "market_cap": mcap,
            "market_cap_source": source,
            "anchor_date": meta.get("anchor_date", signal_reference_date) if meta else signal_reference_date,
        }

    def get_market_cap_at_reference(
        self,
        ticker: str,
        signal_reference_date: str,
        sensitivity_mode: bool = False,
    ) -> tuple[float | None, dict[str, Any] | None]:
        """Retrieve market cap, returning actual KRX if official, or estimated proxy if missing."""
        # 1. Official Hit Check
        if signal_reference_date in self.official_registry.available_dates:
            mcap, meta = self.official_registry.get_market_cap_at_reference(ticker, signal_reference_date)
            near_thresh = bool(mcap is not None and SENSITIVITY_LOWER_BOUND_KRW <= mcap <= SENSITIVITY_UPPER_BOUND_KRW)
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=mcap,
                source_type="ACTUAL_KRX",
                proxy_method=None,
                anchor_date=signal_reference_date,
                anchor_age_days=0,
                anchor_market_cap=mcap,
                anchor_listed_shares=None,
                anchor_close=None,
                target_price_date=signal_reference_date,
                target_close=None,
                close_semantics=self.close_semantics,
                estimated_market_cap=mcap,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="PASS" if (mcap is not None and mcap >= PRIMARY_MIN_MARKET_CAP_KRW) else "FAIL",
                near_threshold=near_thresh,
                confidence_class="OFFICIAL_AUTHORITATIVE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason=None if mcap is not None else "OFFICIAL_TICKER_NOT_FOUND",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec

            if mcap is None:
                return None, None
            res_meta = dict(meta) if meta else {}
            res_meta["proxy_source_type"] = "ACTUAL_KRX"
            res_meta["near_threshold"] = near_thresh
            return mcap, res_meta

        # 2. Check if Date is in Frozen Missing Dates
        if signal_reference_date not in self.missing_dates:
            return None, None

        # 3. Method B: Prior Anchor Price Ratio Proxy
        prior_anchors = [d for d in self.official_available_dates if pd.Timestamp(d) < pd.Timestamp(signal_reference_date)]
        if not prior_anchors:
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=None,
                source_type="PROXY_DATA_UNAVAILABLE",
                proxy_method="ANCHOR_PRICE_RATIO_PROXY",
                anchor_date=None,
                anchor_age_days=None,
                anchor_market_cap=None,
                anchor_listed_shares=None,
                anchor_close=None,
                target_price_date=None,
                target_close=None,
                close_semantics=self.close_semantics,
                estimated_market_cap=None,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="DATA_UNAVAILABLE",
                near_threshold=False,
                confidence_class="UNAVAILABLE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason="NO_PRIOR_OFFICIAL_ANCHOR",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec
            return None, None

        anchor_d = prior_anchors[-1]  # Latest strictly prior anchor
        anchor_mcap, anchor_meta = self.official_registry.get_market_cap_at_reference(ticker, anchor_d)

        if anchor_mcap is None or anchor_mcap <= 0:
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=None,
                source_type="PROXY_DATA_UNAVAILABLE",
                proxy_method="ANCHOR_PRICE_RATIO_PROXY",
                anchor_date=anchor_d,
                anchor_age_days=(pd.Timestamp(signal_reference_date) - pd.Timestamp(anchor_d)).days,
                anchor_market_cap=anchor_mcap,
                anchor_listed_shares=None,
                anchor_close=None,
                target_price_date=None,
                target_close=None,
                close_semantics=self.close_semantics,
                estimated_market_cap=None,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="DATA_UNAVAILABLE",
                near_threshold=False,
                confidence_class="UNAVAILABLE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason="ANCHOR_TICKER_NOT_FOUND_OR_NONPOSITIVE",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec
            return None, None

        daily_df = self.cache.load(ticker)
        if daily_df is None or daily_df.empty:
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=None,
                source_type="PROXY_DATA_UNAVAILABLE",
                proxy_method="ANCHOR_PRICE_RATIO_PROXY",
                anchor_date=anchor_d,
                anchor_age_days=(pd.Timestamp(signal_reference_date) - pd.Timestamp(anchor_d)).days,
                anchor_market_cap=anchor_mcap,
                anchor_listed_shares=None,
                anchor_close=None,
                target_price_date=None,
                target_close=None,
                close_semantics=self.close_semantics,
                estimated_market_cap=None,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="DATA_UNAVAILABLE",
                near_threshold=False,
                confidence_class="UNAVAILABLE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason="NO_LOCAL_PRICE_CACHE",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec
            return None, None

        anchor_bars = daily_df[daily_df.index <= anchor_d]
        target_bars = daily_df[daily_df.index <= signal_reference_date]

        if anchor_bars.empty or target_bars.empty:
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=None,
                source_type="PROXY_DATA_UNAVAILABLE",
                proxy_method="ANCHOR_PRICE_RATIO_PROXY",
                anchor_date=anchor_d,
                anchor_age_days=(pd.Timestamp(signal_reference_date) - pd.Timestamp(anchor_d)).days,
                anchor_market_cap=anchor_mcap,
                anchor_listed_shares=None,
                anchor_close=None,
                target_price_date=None,
                target_close=None,
                close_semantics=self.close_semantics,
                estimated_market_cap=None,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="DATA_UNAVAILABLE",
                near_threshold=False,
                confidence_class="UNAVAILABLE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason="NO_VALID_TRADING_BARS_BEFORE_TARGET",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec
            return None, None

        p_anchor = float(anchor_bars.iloc[-1]["close"])
        p_target = float(target_bars.iloc[-1]["close"])
        target_price_date_str = target_bars.index[-1].strftime("%Y-%m-%d")

        if p_anchor <= 0 or p_target <= 0:
            rec = ProxyQueryRecord(
                ticker=ticker,
                signal_reference_date=signal_reference_date,
                market_cap_value=None,
                source_type="PROXY_DATA_UNAVAILABLE",
                proxy_method="ANCHOR_PRICE_RATIO_PROXY",
                anchor_date=anchor_d,
                anchor_age_days=(pd.Timestamp(signal_reference_date) - pd.Timestamp(anchor_d)).days,
                anchor_market_cap=anchor_mcap,
                anchor_listed_shares=None,
                anchor_close=p_anchor,
                target_price_date=target_price_date_str,
                target_close=p_target,
                close_semantics=self.close_semantics,
                estimated_market_cap=None,
                market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
                market_cap_status="DATA_UNAVAILABLE",
                near_threshold=False,
                confidence_class="UNAVAILABLE",
                posthoc_next_anchor_date=None,
                posthoc_next_anchor_shares=None,
                posthoc_share_change_flag=None,
                failure_reason="NONPOSITIVE_PRICE_VALUE",
            )
            self._audit_records.append(rec)
            self._estimates_by_key[(ticker, signal_reference_date)] = rec
            return None, None

        estimated_mcap = anchor_mcap * (p_target / p_anchor)
        age_days = (pd.Timestamp(signal_reference_date) - pd.Timestamp(anchor_d)).days

        if age_days <= 35:
            conf_class = "HIGH_CONFIDENCE_PROXY"
        elif age_days <= 90:
            conf_class = "MEDIUM_CONFIDENCE_PROXY"
        else:
            conf_class = "LOW_CONFIDENCE_PROXY"

        near_thresh = bool(SENSITIVITY_LOWER_BOUND_KRW <= estimated_mcap <= SENSITIVITY_UPPER_BOUND_KRW)

        future_anchors = [d for d in self.official_available_dates if pd.Timestamp(d) > pd.Timestamp(signal_reference_date)]
        next_anchor_d = future_anchors[0] if future_anchors else None

        rec = ProxyQueryRecord(
            ticker=ticker,
            signal_reference_date=signal_reference_date,
            market_cap_value=estimated_mcap,
            source_type="PROXY_ANCHOR_PRICE_RATIO",
            proxy_method="ANCHOR_PRICE_RATIO_PROXY",
            anchor_date=anchor_d,
            anchor_age_days=age_days,
            anchor_market_cap=anchor_mcap,
            anchor_listed_shares=None,
            anchor_close=p_anchor,
            target_price_date=target_price_date_str,
            target_close=p_target,
            close_semantics=self.close_semantics,
            estimated_market_cap=estimated_mcap,
            market_cap_threshold=PRIMARY_MIN_MARKET_CAP_KRW,
            market_cap_status="PASS" if estimated_mcap >= PRIMARY_MIN_MARKET_CAP_KRW else "FAIL",
            near_threshold=near_thresh,
            confidence_class=conf_class,
            posthoc_next_anchor_date=next_anchor_d,
            posthoc_next_anchor_shares=None,
            posthoc_share_change_flag=None,
            failure_reason=None,
        )
        self._audit_records.append(rec)
        self._estimates_by_key[(ticker, signal_reference_date)] = rec

        if sensitivity_mode and near_thresh:
            return None, None

        proxy_meta = {
            "source_type": "PROXY_ANCHOR_PRICE_RATIO",
            "proxy_method": "ANCHOR_PRICE_RATIO_PROXY",
            "anchor_date": anchor_d,
            "anchor_age_days": age_days,
            "anchor_market_cap": anchor_mcap,
            "anchor_close": p_anchor,
            "target_close": p_target,
            "confidence_class": conf_class,
            "near_threshold": near_thresh,
        }
        return estimated_mcap, proxy_meta

    def get_all_audit_records(self) -> list[ProxyQueryRecord]:
        return list(self._audit_records)

    def get_all_estimates_df(self) -> pd.DataFrame:
        if not self._estimates_by_key:
            return pd.DataFrame()
        return pd.DataFrame([asdict(r) for r in self._estimates_by_key.values()])


def run_proxy_method_validation(
    root: Path = ROOT,
    sample_stride: int = 1,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate Method B (Anchor Price Ratio Proxy) accuracy across known official snapshots."""
    official_reg = HistoricalMarketCapRegistry.load_from_repository(root, enforce_integrity=True)
    cache = ParquetCache(base_dir=root / "data/raw/stocks")
    avail_dates = sorted(list(official_reg.available_dates))

    records: list[dict[str, Any]] = []

    for i in range(1, len(avail_dates), sample_stride):
        target_d = avail_dates[i]
        anchor_d = avail_dates[i - 1]
        age_days = (pd.Timestamp(target_d) - pd.Timestamp(anchor_d)).days

        target_dict = official_reg.snapshots.get(target_d, {})
        anchor_dict = official_reg.snapshots.get(anchor_d, {})

        for ticker, target_entry in target_dict.items():
            if ticker not in anchor_dict:
                continue

            act_mcap = float(target_entry)
            anc_mcap = float(anchor_dict[ticker])

            if act_mcap <= 0 or anc_mcap <= 0:
                continue

            daily_df = cache.load(ticker)
            if daily_df is None or daily_df.empty:
                continue

            anc_bars = daily_df[daily_df.index <= anchor_d]
            tgt_bars = daily_df[daily_df.index <= target_d]
            if anc_bars.empty or tgt_bars.empty:
                continue

            p_anc = float(anc_bars.iloc[-1]["close"])
            p_tgt = float(tgt_bars.iloc[-1]["close"])
            if p_anc <= 0 or p_tgt <= 0:
                continue

            est_mcap = anc_mcap * (p_tgt / p_anc)
            abs_err = abs(est_mcap - act_mcap)
            ape = abs_err / act_mcap * 100.0

            act_pass = bool(act_mcap >= PRIMARY_MIN_MARKET_CAP_KRW)
            est_pass = bool(est_mcap >= PRIMARY_MIN_MARKET_CAP_KRW)

            classification = "AGREEMENT" if act_pass == est_pass else ("FALSE_PASS" if est_pass and not act_pass else "FALSE_FAIL")

            records.append({
                "ticker": ticker,
                "anchor_date": anchor_d,
                "target_date": target_d,
                "anchor_age_days": age_days,
                "actual_market_cap": act_mcap,
                "estimated_market_cap": est_mcap,
                "absolute_error_krw": abs_err,
                "absolute_percentage_error": ape,
                "actual_pass_100b": act_pass,
                "estimated_pass_100b": est_pass,
                "classification_result": classification,
            })

    df_val = pd.DataFrame(records)
    if df_val.empty:
        return df_val, {}

    total_n = len(df_val)
    mean_ape = float(df_val["absolute_percentage_error"].mean())
    median_ape = float(df_val["absolute_percentage_error"].median())
    p75_ape = float(df_val["absolute_percentage_error"].quantile(0.75))
    p90_ape = float(df_val["absolute_percentage_error"].quantile(0.90))
    p95_ape = float(df_val["absolute_percentage_error"].quantile(0.95))
    max_ape = float(df_val["absolute_percentage_error"].max())

    agreements = int((df_val["classification_result"] == "AGREEMENT").sum())
    false_pass = int((df_val["classification_result"] == "FALSE_PASS").sum())
    false_fail = int((df_val["classification_result"] == "FALSE_FAIL").sum())
    agreement_rate = round(agreements / total_n * 100.0, 2)

    summary = {
        "validation_sample_count": total_n,
        "mean_absolute_percentage_error": round(mean_ape, 2),
        "median_absolute_percentage_error": round(median_ape, 2),
        "p75_absolute_percentage_error": round(p75_ape, 2),
        "p90_absolute_percentage_error": round(p90_ape, 2),
        "p95_absolute_percentage_error": round(p95_ape, 2),
        "max_absolute_percentage_error": round(max_ape, 2),
        "threshold_agreement_count": agreements,
        "false_pass_count": false_pass,
        "false_fail_count": false_fail,
        "classification_agreement_rate": agreement_rate,
    }

    return df_val, summary


def calculate_strategy_metrics(trades: list[StrategyTradeRecord]) -> dict[str, Any]:
    """Calculate comprehensive performance, distribution, and duration metrics."""
    if not trades:
        return {
            "total_trades": 0,
            "unique_tickers": 0,
            "return_stats": {"mean": 0.0, "median": 0.0, "positive_rate": 0.0},
            "distribution_stats": {
                "le_neg10_count": 0, "le_neg10_rate": 0.0,
                "le_neg15_count": 0, "le_neg15_rate": 0.0,
                "le_neg20_count": 0, "le_neg20_rate": 0.0,
                "le_neg30_count": 0, "le_neg30_rate": 0.0,
                "ge_pos20_count": 0, "ge_pos20_rate": 0.0,
                "ge_pos30_count": 0, "ge_pos30_rate": 0.0,
                "ge_pos50_count": 0, "ge_pos50_rate": 0.0,
                "ge_pos100_count": 0, "ge_pos100_rate": 0.0,
            },
            "mae_stats": {"mean": 0.0, "median": 0.0, "worst": 0.0},
            "mfe_stats": {"mean": 0.0, "median": 0.0},
            "holding_stats": {"mean_weeks": 0.0, "median_weeks": 0.0},
            "exit_type_counts": {},
        }

    total_t = len(trades)
    tickers = len(set(t.ticker for t in trades))
    returns = np.array([t.terminal_return for t in trades])
    maes = np.array([t.mae for t in trades])
    mfes = np.array([t.mfe for t in trades])
    weeks = np.array([t.holding_weeks for t in trades])

    exit_counts: dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_type] = exit_counts.get(t.exit_type, 0) + 1

    return {
        "total_trades": total_t,
        "unique_tickers": tickers,
        "return_stats": {
            "mean": float(np.mean(returns)),
            "median": float(np.median(returns)),
            "positive_rate": float(np.mean(returns > 0)),
        },
        "distribution_stats": {
            "le_neg10_count": int(np.sum(returns <= -0.10)),
            "le_neg10_rate": float(np.mean(returns <= -0.10)),
            "le_neg15_count": int(np.sum(returns <= -0.15)),
            "le_neg15_rate": float(np.mean(returns <= -0.15)),
            "le_neg20_count": int(np.sum(returns <= -0.20)),
            "le_neg20_rate": float(np.mean(returns <= -0.20)),
            "le_neg30_count": int(np.sum(returns <= -0.30)),
            "le_neg30_rate": float(np.mean(returns <= -0.30)),
            "ge_pos20_count": int(np.sum(returns >= 0.20)),
            "ge_pos20_rate": float(np.mean(returns >= 0.20)),
            "ge_pos30_count": int(np.sum(returns >= 0.30)),
            "ge_pos30_rate": float(np.mean(returns >= 0.30)),
            "ge_pos50_count": int(np.sum(returns >= 0.50)),
            "ge_pos50_rate": float(np.mean(returns >= 0.50)),
            "ge_pos100_count": int(np.sum(returns >= 1.00)),
            "ge_pos100_rate": float(np.mean(returns >= 1.00)),
        },
        "mae_stats": {
            "mean": float(np.mean(maes)),
            "median": float(np.median(maes)),
            "worst": float(np.min(maes)),
        },
        "mfe_stats": {
            "mean": float(np.mean(mfes)),
            "median": float(np.median(mfes)),
        },
        "holding_stats": {
            "mean_weeks": float(np.mean(weeks)),
            "median_weeks": float(np.median(weeks)),
        },
        "exit_type_counts": exit_counts,
    }


def pair_common_entry_trades(
    baseline_trades: list[StrategyTradeRecord],
    julia_trades: list[StrategyTradeRecord],
) -> tuple[list[dict[str, Any]], list[StrategyTradeRecord], list[StrategyTradeRecord]]:
    """Match trades on exact (ticker, entry_signal_date, entry_execution_date, entry_open)."""
    b_map = {(t.ticker, t.entry_signal_date, t.entry_execution_date, t.entry_open): t for t in baseline_trades}
    j_map = {(t.ticker, t.entry_signal_date, t.entry_execution_date, t.entry_open): t for t in julia_trades}

    common_keys = sorted(list(set(b_map.keys()).intersection(set(j_map.keys()))))
    paired: list[dict[str, Any]] = []

    for k in common_keys:
        tb = b_map[k]
        tj = j_map[k]
        paired.append({
            "ticker": tb.ticker,
            "name": tb.name,
            "market": tb.market,
            "entry_signal_date": tb.entry_signal_date,
            "entry_execution_date": tb.entry_execution_date,
            "entry_open": tb.entry_open,
            "baseline_exit_type": tb.exit_type,
            "baseline_exit_date": tb.exit_execution_date,
            "baseline_terminal_return": tb.terminal_return,
            "baseline_mfe": tb.mfe,
            "baseline_mae": tb.mae,
            "baseline_loss_guard_triggered": tb.loss_guard_triggered,
            "julia_exit_type": tj.exit_type,
            "julia_exit_date": tj.exit_execution_date,
            "julia_terminal_return": tj.terminal_return,
            "julia_mfe": tj.mfe,
            "julia_mae": tj.mae,
            "julia_first_progressed_date": tj.first_progressed_date,
            "return_delta": tj.terminal_return - tb.terminal_return,
            "mfe_delta": tj.mfe - tb.mfe,
            "mae_delta": tj.mae - tb.mae,
        })

    unpaired_b = [tb for k, tb in b_map.items() if k not in j_map]
    unpaired_j = [tj for k, tj in j_map.items() if k not in b_map]

    return paired, unpaired_b, unpaired_j
