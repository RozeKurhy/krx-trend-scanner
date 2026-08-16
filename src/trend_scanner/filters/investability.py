"""Downstream Investability and Tradability Filter Module (Phase 10C).

This module implements the downstream evaluation layer applied after Pattern A structural detection.
It evaluates market capitalization and short-term liquidity (20D average trading value)
to separate investable candidates from illiquid or microcap stocks without altering
underlying Pattern A score, stage, or raw candidate definitions.

[Policy Constants (Phase 10B Approved)]:
- MIN_MARKET_CAP_KRW: 100_000_000_000 (1,000억원)
- MIN_AVG_TRADING_VALUE_20D_KRW: 300_000_000 (3.0억원)
- Price hard threshold: NONE (NOT_NEEDED)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

# 1. Policy Constants
MIN_MARKET_CAP_KRW: float = 100_000_000_000.0  # 1,000 억원
MIN_AVG_TRADING_VALUE_20D_KRW: float = 300_000_000.0  # 3.0 억원


class InvestabilityStatus(str, Enum):
    """Downstream investability and liquidity status."""

    INVESTABLE = "INVESTABLE"
    """Passes all market cap and liquidity thresholds."""

    FILTERED_MARKET_CAP = "FILTERED_MARKET_CAP"
    """Market cap is below 1,000 억원."""

    FILTERED_LIQUIDITY = "FILTERED_LIQUIDITY"
    """20D average trading value is below 3.0 억원."""

    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    """Required metric (market cap, exact close observation, or 20D trading history) is missing."""


class InvestabilityReason(str, Enum):
    """Standard explanation codes for investability evaluation."""

    PASS_ALL_INVESTABILITY_FILTERS = "PASS_ALL_INVESTABILITY_FILTERS"
    MARKET_CAP_BELOW_1000EOK = "MARKET_CAP_BELOW_1000EOK"
    TV20_BELOW_3EOK = "TV20_BELOW_3EOK"
    REQUIRED_METRIC_UNAVAILABLE = "REQUIRED_METRIC_UNAVAILABLE"


@dataclass(frozen=True)
class InvestabilityEvaluationResult:
    """Evaluation result for a single stock's investability and tradability."""

    ticker: str
    as_of: str
    status: InvestabilityStatus
    reason: str
    market_cap: float | None
    market_cap_eok: float | None
    avg_trading_value_20d: float | None
    avg_trading_value_20d_eok: float | None
    avg_trading_value_60d: float | None
    avg_trading_value_60d_eok: float | None
    close: float | None
    close_ready: bool
    market_cap_ready: bool
    trading_value_20d_ready: bool
    trading_value_60d_ready: bool
    data_ready: bool
    market_cap_effective_date: str | None = None
    close_effective_date: str | None = None
    tv20_last_observation_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert evaluation result to dictionary."""
        return {
            "ticker": self.ticker,
            "as_of": self.as_of,
            "investability_status": self.status.value,
            "investability_reason": self.reason,
            "market_cap": self.market_cap,
            "market_cap_eok": self.market_cap_eok,
            "avg_trading_value_20d": self.avg_trading_value_20d,
            "avg_trading_value_20d_eok": self.avg_trading_value_20d_eok,
            "avg_trading_value_60d": self.avg_trading_value_60d,
            "avg_trading_value_60d_eok": self.avg_trading_value_60d_eok,
            "close": self.close,
            "close_ready": self.close_ready,
            "market_cap_ready": self.market_cap_ready,
            "trading_value_20d_ready": self.trading_value_20d_ready,
            "trading_value_60d_ready": self.trading_value_60d_ready,
            "investability_data_ready": self.data_ready,
            "market_cap_effective_date": self.market_cap_effective_date,
            "close_effective_date": self.close_effective_date,
            "tv20_last_observation_date": self.tv20_last_observation_date,
        }


def evaluate_investability(
    ticker: str,
    as_of: str | pd.Timestamp,
    daily: pd.DataFrame | None,
    market_cap: float | None = None,
    market_cap_effective_date: str | None = None,
    min_market_cap_krw: float = MIN_MARKET_CAP_KRW,
    min_avg_trading_value_20d_krw: float = MIN_AVG_TRADING_VALUE_20D_KRW,
) -> InvestabilityEvaluationResult:
    """Evaluate investability and tradability status for a single security Point-In-Time.

    Evaluation Precedence:
    1. Required metrics availability check:
       - Market cap available and > 0
       - Exact close observation exists on as_of
       - Complete 20-day trading value history exists on or before as_of
       If any required metric is missing -> DATA_UNAVAILABLE
    2. Market Cap Threshold:
       If market_cap < min_market_cap_krw -> FILTERED_MARKET_CAP
    3. 20D Average Trading Value Threshold:
       If avg_trading_value_20d < min_avg_trading_value_20d_krw -> FILTERED_LIQUIDITY
    4. Otherwise -> INVESTABLE

    Note: 60D Average Trading Value is a reference/sanity metric and does not trigger DATA_UNAVAILABLE by itself.
    """
    as_of_ts = pd.Timestamp(as_of)
    as_of_str = as_of_ts.strftime("%Y-%m-%d")

    # 1. Market Cap readiness
    mcap_ready = (market_cap is not None and not np.isnan(market_cap) and market_cap > 0)
    mcap_val = float(market_cap) if mcap_ready else None
    mcap_eok = round(mcap_val / 1e8, 2) if mcap_val is not None else None

    # 2. Daily slice inspection on or before as_of
    if daily is None or daily.empty:
        return InvestabilityEvaluationResult(
            ticker=ticker,
            as_of=as_of_str,
            status=InvestabilityStatus.DATA_UNAVAILABLE,
            reason=InvestabilityReason.REQUIRED_METRIC_UNAVAILABLE.value,
            market_cap=mcap_val,
            market_cap_eok=mcap_eok,
            avg_trading_value_20d=None,
            avg_trading_value_20d_eok=None,
            avg_trading_value_60d=None,
            avg_trading_value_60d_eok=None,
            close=None,
            close_ready=False,
            market_cap_ready=mcap_ready,
            trading_value_20d_ready=False,
            trading_value_60d_ready=False,
            data_ready=False,
            market_cap_effective_date=market_cap_effective_date,
            close_effective_date=None,
            tv20_last_observation_date=None,
        )

    daily_asof = daily.loc[daily.index <= as_of_ts]
    if daily_asof.empty or as_of_ts not in daily_asof.index:
        # Exact close on as_of missing (trading halt, stale, or holiday mismatch)
        return InvestabilityEvaluationResult(
            ticker=ticker,
            as_of=as_of_str,
            status=InvestabilityStatus.DATA_UNAVAILABLE,
            reason=InvestabilityReason.REQUIRED_METRIC_UNAVAILABLE.value,
            market_cap=mcap_val,
            market_cap_eok=mcap_eok,
            avg_trading_value_20d=None,
            avg_trading_value_20d_eok=None,
            avg_trading_value_60d=None,
            avg_trading_value_60d_eok=None,
            close=None,
            close_ready=False,
            market_cap_ready=mcap_ready,
            trading_value_20d_ready=False,
            trading_value_60d_ready=False,
            data_ready=False,
            market_cap_effective_date=market_cap_effective_date,
            close_effective_date=None,
            tv20_last_observation_date=None,
        )

    # Exact Close observation
    close_val = float(daily_asof.loc[as_of_ts, "close"])
    close_ready = not np.isnan(close_val)
    close_effective_date_str = as_of_ts.strftime("%Y-%m-%d")

    # Trading Value calculations
    tv_series = daily_asof["trading_value"].dropna() if "trading_value" in daily_asof.columns else pd.Series(dtype=float)
    tv_len = len(tv_series)

    # 20D Window contract
    if tv_len >= 20:
        tv_20_slice = tv_series.iloc[-20:]
        avg_tv_20 = float(tv_20_slice.mean())
        avg_tv_20_eok = round(avg_tv_20 / 1e8, 2)
        tv_20_ready = True
        tv20_last_date_str = tv_20_slice.index[-1].strftime("%Y-%m-%d")
    else:
        avg_tv_20 = None
        avg_tv_20_eok = None
        tv_20_ready = False
        tv20_last_date_str = None

    # 60D Window contract (Reference/Sanity)
    if tv_len >= 60:
        tv_60_slice = tv_series.iloc[-60:]
        avg_tv_60 = float(tv_60_slice.mean())
        avg_tv_60_eok = round(avg_tv_60 / 1e8, 2)
        tv_60_ready = True
    else:
        avg_tv_60 = None
        avg_tv_60_eok = None
        tv_60_ready = False

    data_ready = bool(mcap_ready and close_ready and tv_20_ready)

    # Evaluation Precedence
    if not data_ready:
        status = InvestabilityStatus.DATA_UNAVAILABLE
        reason = InvestabilityReason.REQUIRED_METRIC_UNAVAILABLE.value
    elif mcap_val < min_market_cap_krw:
        status = InvestabilityStatus.FILTERED_MARKET_CAP
        reason = f"{InvestabilityReason.MARKET_CAP_BELOW_1000EOK.value} ({mcap_eok:.1f}억)"
    elif avg_tv_20 < min_avg_trading_value_20d_krw:
        status = InvestabilityStatus.FILTERED_LIQUIDITY
        reason = f"{InvestabilityReason.TV20_BELOW_3EOK.value} ({avg_tv_20_eok:.2f}억)"
    else:
        status = InvestabilityStatus.INVESTABLE
        reason = InvestabilityReason.PASS_ALL_INVESTABILITY_FILTERS.value

    return InvestabilityEvaluationResult(
        ticker=ticker,
        as_of=as_of_str,
        status=status,
        reason=reason,
        market_cap=mcap_val,
        market_cap_eok=mcap_eok,
        avg_trading_value_20d=avg_tv_20,
        avg_trading_value_20d_eok=avg_tv_20_eok,
        avg_trading_value_60d=avg_tv_60,
        avg_trading_value_60d_eok=avg_tv_60_eok,
        close=close_val,
        close_ready=close_ready,
        market_cap_ready=mcap_ready,
        trading_value_20d_ready=tv_20_ready,
        trading_value_60d_ready=tv_60_ready,
        data_ready=data_ready,
        market_cap_effective_date=market_cap_effective_date,
        close_effective_date=close_effective_date_str,
        tv20_last_observation_date=tv20_last_date_str,
    )
