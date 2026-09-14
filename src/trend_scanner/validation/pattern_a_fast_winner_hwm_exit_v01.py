"""Pure deterministic WINNER_HWM_EXIT_V01 candidate evaluator.

This module is a research candidate contract only.  It is intentionally not
connected to production reports, strategy defaults, or re-entry generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V03"
BASE_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
EXIT_CONTRACT_ID = "WINNER_HWM_EXIT_V01"
WINNER_THRESHOLD_PCT = 20.0
HWM_PRICE_FIELD = "daily_high"
BREACH_PRICE_FIELD = "daily_close"
WEAK_FAST_STATES = frozenset({"WATCH", "SETUP"})
SIGNAL_TIMING = "COMPLETED_DAILY_EOD"
EXECUTION_TIMING = "NEXT_LOCAL_TRADING_DAY_OPEN"

# Inclusive lower bound, exclusive upper bound, soft drawdown, hard drawdown.
MFE_TIERS: tuple[tuple[float, float | None, float, float, str], ...] = (
    (20.0, 50.0, -10.0, -20.0, "MFE_20_TO_50"),
    (50.0, 100.0, -15.0, -25.0, "MFE_50_TO_100"),
    (100.0, 200.0, -20.0, -30.0, "MFE_100_TO_200"),
    (200.0, 400.0, -25.0, -35.0, "MFE_200_TO_400"),
    (400.0, None, -30.0, -40.0, "MFE_400_PLUS"),
)


@dataclass(frozen=True)
class EodExitDecision:
    """One completed daily observation and its deterministic exit result."""

    decision: str | None
    hwm_price: float
    mfe_pct: float
    drawdown_pct: float
    soft_threshold_pct: float | None
    hard_threshold_pct: float | None
    mfe_tier: str | None


def mfe_tier(mfe_pct: float) -> tuple[float, float, str] | None:
    """Return the active soft/hard band using exact boundary ownership."""
    for lower, upper, soft, hard, label in MFE_TIERS:
        if mfe_pct >= lower and (upper is None or mfe_pct < upper):
            return soft, hard, label
    return None


def update_hwm(previous_hwm_price: float, daily_high: float) -> float:
    """Update a non-decreasing price HWM from a completed daily HIGH."""
    previous = float(previous_hwm_price)
    high = float(daily_high)
    if not math.isfinite(previous) or not math.isfinite(high):
        raise ValueError("HWM inputs must be finite")
    if previous <= 0.0 or high <= 0.0:
        raise ValueError("HWM inputs must be positive")
    return max(previous, high)


def exit_decision(
    *,
    mfe_pct: float,
    hwm_price: float,
    current_close: float,
    fast_state: str | None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Evaluate one completed EOD close against the current price HWM.

    The return shape is kept compatible with the existing local V3 research
    runner.  ``None`` is HOLD, including every Pre-Winner observation.
    """
    tier = mfe_tier(float(mfe_pct))
    if tier is None:
        return None, None, None, None
    soft, hard, label = tier
    hwm = float(hwm_price)
    close = float(current_close)
    if not math.isfinite(hwm) or not math.isfinite(close) or hwm <= 0.0 or close <= 0.0:
        raise ValueError("price inputs must be finite and positive")
    # Round only the comparison value so an exact threshold is not lost to
    # binary floating-point representation.
    drawdown_pct = round((close / hwm - 1.0) * 100.0, 10)
    if drawdown_pct <= hard:
        return "HARD_EXIT", soft, hard, label
    if drawdown_pct <= soft and fast_state in WEAK_FAST_STATES:
        return "SOFT_EXIT", soft, hard, label
    return None, soft, hard, label


def evaluate_eod(
    *,
    entry_open: float,
    previous_hwm_price: float,
    daily_high: float,
    daily_close: float,
    fast_state: str | None,
) -> EodExitDecision:
    """Update HWM with today's HIGH, then evaluate today's completed CLOSE."""
    entry = float(entry_open)
    if not math.isfinite(entry) or entry <= 0.0:
        raise ValueError("entry_open must be finite and positive")
    hwm = update_hwm(previous_hwm_price, daily_high)
    mfe_pct = round((hwm / entry - 1.0) * 100.0, 10)
    decision, soft, hard, label = exit_decision(
        mfe_pct=mfe_pct,
        hwm_price=hwm,
        current_close=daily_close,
        fast_state=fast_state,
    )
    drawdown_pct = round((float(daily_close) / hwm - 1.0) * 100.0, 10)
    return EodExitDecision(
        decision=decision,
        hwm_price=hwm,
        mfe_pct=mfe_pct,
        drawdown_pct=drawdown_pct,
        soft_threshold_pct=soft,
        hard_threshold_pct=hard,
        mfe_tier=label,
    )
