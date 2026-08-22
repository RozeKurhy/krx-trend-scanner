"""Research-parameter externalization for the 2022+ backtest engine (w.md Section 20).

Only the market-cap eligibility threshold is externalized here, per w.md
Section 20 (explicit request) -- liquidity threshold externalization is
explicitly out of scope for this task (w.md Section 21: "이번 작업에서
변경 금지"). The production investability default
(``MIN_MARKET_CAP_KRW`` = 100B) is never changed; this config only lets a
future research script pass a different threshold into
``simulate_ticker_strategy_2022(min_market_cap_krw=...)`` without touching
``filters.investability.MIN_MARKET_CAP_KRW`` itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from trend_scanner.filters.investability import MIN_MARKET_CAP_KRW


@dataclass(frozen=True)
class BacktestConfig:
    min_market_cap_krw: float = MIN_MARKET_CAP_KRW
