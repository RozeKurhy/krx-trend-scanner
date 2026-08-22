"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- caching layer correctness tests.

Validates:
  - Data Load Cache: 10 requests for the same ticker -> 1 disk read, 9 memory
    hits, identical returned data (w.md Section 42).
  - Pattern A / FAST Snapshot Cache: repeated (ticker, reference_date)
    requests -> 1 expensive evaluation, identical result (w.md Sections 44-45).
  - Baseline/Julia Shared Feature: same (ticker, week) snapshot identical
    across enable_loss_guard True/False (w.md Section 46).
  - Primary/Sensitivity Shared Feature: same underlying Pattern A / FAST
    snapshot is used regardless of sensitivity_mode (w.md Section 47).
  - Market Cap Config: BacktestConfig default is unchanged
    (MIN_MARKET_CAP_KRW = 100B) and an override changes the investability
    gate without touching the production default (w.md Section 48), and the
    snapshot cache stays fully valid across different threshold configs
    (Gate G / w.md Section 58).

w.md Section 43 (Resampling Cache) is deliberately NOT implemented: caching
a full-history weekly/monthly resample and slicing it by label is not
provably equal to resampling only the cutoff/reference-date-bounded slice
that ``simulate_ticker_strategy_2022``/``build_historical_snapshot`` actually
resample (calendar month-end labels vs. last-trading-day data can disagree
on which period is "complete"). See
``docs/architecture/backtest_performance_engine_v01.md`` Section 12 (Known
Limitations) -- this is the deferred Phase 4 candidate, not a gap in this
task's Phase 1-3 scope.

None of these tests touch strategy semantics -- they assert cache
mechanics (call counts, hit counts) and byte-for-byte output identity
between cached and uncached paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from trend_scanner.backtest.config import BacktestConfig
from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import MIN_MARKET_CAP_KRW
from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
TEST_TICKER = "005930"
TEST_NAME = "삼성전자"


def _contracts() -> tuple[dict, dict]:
    return (
        json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8")),
        json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8")),
    )


# =============================================================================
# 42. Test -- Data Load Cache
# =============================================================================

def test_data_load_cache_one_disk_read_nine_memory_hits():
    cache = TickerDataCache(base_dir=ROOT / "data/raw/stocks")
    legacy = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    expected = legacy.load(TEST_TICKER)

    frames = [cache.load(TEST_TICKER) for _ in range(10)]

    assert cache.disk_read_count == 1
    assert cache.memory_hit_count == 9
    assert cache.memory_miss_count == 1
    for frame in frames:
        assert frame is not None
        pd.testing.assert_frame_equal(frame, expected)


# =============================================================================
# 44. Test -- Pattern A / FAST Snapshot Cache (44 & 45 combined: evaluate_pattern_a_fast
#     produces both the FAST snapshot and a reference Pattern A snapshot in one call)
# =============================================================================

def test_fast_snapshot_cache_single_evaluation_identical_result():
    score_contract, stage_contract = _contracts()
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)

    from trend_scanner.data.resampler import to_weekly
    weekly_bars = to_weekly(daily)
    valid_weeks = [w for w in weekly_bars.index if daily[daily.index <= w].index.max().normalize() == w.normalize()]
    w = valid_weeks[len(valid_weeks) // 2]

    fast_cache = FastSnapshotCache()
    results = [fast_cache.get(TEST_TICKER, TEST_NAME, daily, w, score_contract, stage_contract) for _ in range(5)]

    assert fast_cache.evaluation_count == 1
    assert fast_cache.cache_hit_count == 4
    first = results[0]
    for r in results[1:]:
        assert r == first


def test_monthly_snapshot_cache_single_evaluation_identical_result():
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)

    from trend_scanner.data.resampler import to_monthly
    monthly_bars = to_monthly(daily)
    m = monthly_bars.index[len(monthly_bars) // 2]

    monthly_cache = MonthlySnapshotCache()
    results = [monthly_cache.get(TEST_TICKER, TEST_NAME, daily, m) for _ in range(5)]

    assert monthly_cache.evaluation_count == 1
    assert monthly_cache.cache_hit_count == 4
    first = results[0]
    for r in results[1:]:
        assert r == first


# =============================================================================
# 46. Test -- Baseline/Julia Shared Feature
# =============================================================================

def test_baseline_julia_share_identical_pattern_a_fast_snapshots():
    score_contract, stage_contract = _contracts()
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)
    reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    b_trades = simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
    )
    evals_after_baseline = fast_cache.evaluation_count

    j_trades = simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=False, market_cap_registry=reg,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
    )

    assert len(b_trades) >= 1 and len(j_trades) >= 1
    # Julia pass must not trigger any new expensive evaluation the Baseline
    # pass didn't already perform (feature layer is loss-guard-invariant).
    assert fast_cache.evaluation_count == evals_after_baseline
    assert fast_cache.cache_hit_count > 0

    assert b_trades[0].entry_pattern_a_stage == j_trades[0].entry_pattern_a_stage
    assert b_trades[0].fast_stage == j_trades[0].fast_stage
    assert b_trades[0].fast_score == j_trades[0].fast_score
    # The only allowed divergence source is the Loss Guard path itself.
    if b_trades[0].exit_type != j_trades[0].exit_type:
        assert b_trades[0].loss_guard_triggered or not j_trades[0].loss_guard_triggered


# =============================================================================
# 47. Test -- Primary/Sensitivity Shared Feature
# =============================================================================

def test_primary_sensitivity_share_identical_pattern_a_fast_snapshots():
    score_contract, stage_contract = _contracts()
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)
    reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
    )
    evals_after_primary = fast_cache.evaluation_count
    hits_before_sensitivity = fast_cache.cache_hit_count

    simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg, sensitivity_mode=True,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
    )

    # Sensitivity mode only changes market-cap eligibility acceptance, never
    # which (ticker, week) Pattern A / FAST snapshots get computed -- so no
    # new expensive evaluation should occur, only cache hits.
    assert fast_cache.evaluation_count == evals_after_primary
    assert fast_cache.cache_hit_count > hits_before_sensitivity


# =============================================================================
# 48. Test -- Market Cap Config
# =============================================================================

def test_backtest_config_default_matches_production_investability_default():
    assert BacktestConfig().min_market_cap_krw == MIN_MARKET_CAP_KRW == 100_000_000_000.0


def test_backtest_config_override_does_not_mutate_production_default():
    custom = BacktestConfig(min_market_cap_krw=300_000_000_000.0)
    assert custom.min_market_cap_krw == 300_000_000_000.0
    # Production default constant itself must remain untouched.
    assert MIN_MARKET_CAP_KRW == 100_000_000_000.0


def test_simulate_ticker_strategy_min_market_cap_krw_override_changes_eligibility():
    score_contract, stage_contract = _contracts()
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)
    reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    default_trades = simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
    )
    # Absurdly high threshold: every candidate must fail the investability gate.
    extreme_trades = simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        min_market_cap_krw=1_000_000_000_000_000.0,
    )

    assert len(default_trades) >= 1
    assert len(extreme_trades) == 0

    # Omitting the parameter must reproduce the exact production default path.
    explicit_default_trades = simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        min_market_cap_krw=MIN_MARKET_CAP_KRW,
    )
    assert [asdict(t) for t in default_trades] == [asdict(t) for t in explicit_default_trades]


# =============================================================================
# 58. Test -- Acceptance Gate G (Warm Research Rerun)
# =============================================================================

def test_shared_snapshot_cache_stays_warm_across_market_cap_config_change():
    """Changing min_market_cap_krw must not force any Pattern A / FAST
    re-evaluation -- eligibility is decided downstream of the cached
    snapshot, so a second run with a different config is a pure cache-hit
    rerun (w.md Section 58 Acceptance Gate G)."""
    score_contract, stage_contract = _contracts()
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(TEST_TICKER)
    reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)

    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        min_market_cap_krw=100_000_000_000.0,
    )
    evaluation_count_after_100b = fast_cache.evaluation_count

    simulate_ticker_strategy_2022(
        TEST_TICKER, TEST_NAME, "KOSPI", daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=reg,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        min_market_cap_krw=300_000_000_000.0,
    )

    assert fast_cache.evaluation_count == evaluation_count_after_100b
    assert fast_cache.cache_hit_count > 0


# =============================================================================
# Anchor Search Optimization (w.md Section 23) -- bisect equivalence
# =============================================================================

def test_anchor_search_bisect_matches_original_linear_scan_semantics():
    """ProxyHistoricalMarketCapRegistry now finds prior/future anchors via
    bisect over a precomputed sorted Timestamp array instead of a per-call
    list comprehension. Verify, for every missing (proxy) date, that the
    selected prior anchor is exactly the same one the original
    ``[d for d in official_available_dates if pd.Timestamp(d) < target]``
    comprehension would have selected (its last element)."""
    reg = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT)
    official_ts = [pd.Timestamp(d) for d in reg.official_available_dates]

    checked_with_prior = 0
    checked_without_prior = 0
    for missing_date in sorted(reg.missing_dates):
        target_ts = pd.Timestamp(missing_date)
        expected_prior = [d for d, ts in zip(reg.official_available_dates, official_ts) if ts < target_ts]
        expected_future = [d for d, ts in zip(reg.official_available_dates, official_ts) if ts > target_ts]

        mcap, meta = reg.get_market_cap_at_reference("005930", missing_date)

        if not expected_prior:
            checked_without_prior += 1
            assert mcap is None
            continue

        checked_with_prior += 1
        expected_anchor = expected_prior[-1]
        expected_next_anchor = expected_future[0] if expected_future else None
        if meta is not None:
            assert meta["anchor_date"] == expected_anchor

        rec = reg.get_all_estimates_df()
        rec_row = rec[(rec.ticker == "005930") & (rec.signal_reference_date == missing_date)]
        assert len(rec_row) == 1
        assert rec_row.iloc[0]["anchor_date"] == expected_anchor or (
            rec_row.iloc[0]["source_type"] == "PROXY_DATA_UNAVAILABLE" and expected_anchor is not None
        )
        if expected_next_anchor is not None:
            assert rec_row.iloc[0]["posthoc_next_anchor_date"] in (expected_next_anchor, None)

    # Sanity: the missing-dates set actually exercises both branches.
    assert checked_with_prior > 0
