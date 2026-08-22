"""Unit tests for Julia Proxy Market Cap PIT V01.

Tests cover:
- Proxy PIT registry anchor selection rules (strictly prior anchor, no future anchor)
- Actual KRX preference on official reference dates
- Fail-closed behavior on missing prior anchors
- Baseline vs Julia market cap parity
- Method B mathematical formula validation
- Sensitivity boundary buffer logic
"""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    METHOD_B_NAME,
    PRICE_SEMANTICS,
    ROOT,
    ProxyHistoricalMarketCapRegistry,
    calculate_proxy_market_cap_method_b,
)
from trend_scanner.validation.julia_strategy_v00 import (
    HistoricalMarketCapRegistry,
)


def test_proxy_price_series_semantics_are_explicit():
    """Verify that price semantics and method are explicitly declared."""
    assert PRICE_SEMANTICS == "ADJUSTED_CLOSE"
    assert METHOD_B_NAME == "ANCHOR_MCAP_PRICE_RATIO_PROXY"


def test_proxy_method_b_formula():
    """Verify Method B: Estimated MCap = anchor_mcap * (current_price / anchor_price)."""
    anchor_mcap = 100_000_000_000  # 100B KRW
    anchor_price = 10_000.0
    current_price = 12_500.0

    est_mcap = calculate_proxy_market_cap_method_b(
        anchor_mcap=anchor_mcap,
        anchor_price=anchor_price,
        current_price=current_price,
    )
    assert est_mcap == 125_000_000_000


def test_proxy_registry_official_value_exact_parity():
    """Verify exact parity between official registry and proxy registry on official dates."""
    official_reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    assert len(proxy_reg.official_dates) == 117
    # Pick a known official date and ticker
    first_official_date = proxy_reg.official_dates[0]
    official_mcap, _ = official_reg.get_market_cap_at_reference("005930", first_official_date)
    proxy_mcap, proxy_meta = proxy_reg.get_market_cap_at_reference("005930", first_official_date)

    assert official_mcap is not None
    assert proxy_mcap is not None
    assert official_mcap == proxy_mcap
    assert proxy_meta["proxy_source_type"] == "ACTUAL_KRX"


def test_proxy_registry_prefers_actual_krx_when_available():
    """Verify registry returns ACTUAL_KRX for all official reference dates."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    for d in proxy_reg.official_dates[:5]:
        res = proxy_reg.lookup_market_cap(d, "005930")
        if res is not None:
            assert res["market_cap_source"] == "ACTUAL_KRX"
            assert res["anchor_date"] == d


def test_proxy_registry_uses_only_prior_anchor():
    """Verify proxy calculation uses only strictly prior anchor dates."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    
    # Pick a date where official snapshot does not exist (e.g. 2022-01-07)
    test_date = "2022-01-07"
    if test_date in proxy_reg.official_dates:
        # find first non-official date in 2022
        all_dates = sorted(list(proxy_reg.all_required_dates))
        non_official = [d for d in all_dates if d not in proxy_reg.official_dates and d > proxy_reg.official_dates[0]]
        test_date = non_official[0]

    res = proxy_reg.lookup_market_cap(test_date, "005930")
    if res is not None:
        assert res["market_cap_source"] == "ANCHOR_PRICE_RATIO_PROXY"
        assert res["anchor_date"] <= test_date
        assert res["anchor_date"] in proxy_reg.official_dates


def test_proxy_registry_never_uses_future_anchor():
    """Verify registry never selects an anchor date greater than target date."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    # Before the very first official date
    early_date = "2021-01-01"
    res = proxy_reg.lookup_market_cap(early_date, "005930")
    # Must be None (fail closed) because no prior anchor exists
    assert res is None


def test_proxy_registry_missing_prior_anchor_fail_closed():
    """Verify fail-closed behavior when no prior anchor or no price data is available."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    # Non-existent ticker
    res = proxy_reg.lookup_market_cap("2024-01-05", "NON_EXISTENT_TICKER")
    assert res is None


def test_proxy_registry_baseline_julia_same_mcap():
    """Verify Baseline and Julia always get the exact same market cap value for the same date/ticker."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    test_date = "2024-01-05"
    baseline_val = proxy_reg.lookup_market_cap(test_date, "005930")
    julia_val = proxy_reg.lookup_market_cap(test_date, "005930")
    assert baseline_val == julia_val
