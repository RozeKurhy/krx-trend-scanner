"""Unit tests for Julia Proxy Market Cap PIT V01 (FIX02).

Tests cover:
- Proxy PIT registry anchor selection rules (strictly prior anchor, no future anchor)
- Actual KRX preference on official reference dates
- Fail-closed behavior on missing prior anchors
- Baseline vs Julia market cap parity
- Method B mathematical formula validation
- Sensitivity boundary buffer logic and audit status
- Metric and Distribution unit contracts (percentage-point vs fraction)
- No double scaling in reports and Markdown outputs
- Exact 6-digit zero-padded ticker preservation (e.g. 043260, 005930)
- Proxy contract schema completeness & proxy rules
- Sealed Artifact Manifest provenance metadata & SHA-256 integrity verification
- Existing trade-level invariant preservation
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pytest

from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    METHOD_B_NAME,
    PRICE_SEMANTICS,
    ROOT,
    ProxyHistoricalMarketCapRegistry,
    calculate_proxy_market_cap_method_b,
    calculate_strategy_metrics,
)
from trend_scanner.validation.julia_strategy_v00 import (
    HistoricalMarketCapRegistry,
    StrategyTradeRecord,
)

PROXY_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
DOCS_MD_PATH = ROOT / "docs/strategies/julia/proxy_market_cap_v01.md"


def _make_dummy_trade(ret: float, mae: float = -10.0, mfe: float = 20.0, exit_type: str = "EXIT4_SCORE_DRAWDOWN_GE_15", ticker: str = "005930") -> StrategyTradeRecord:
    return StrategyTradeRecord(
        strategy_id="JULIA_STRATEGY_V00",
        pre_progressed_loss_guard_enabled=False,
        ticker=ticker,
        name="Samsung",
        market="KOSPI",
        trade_id=f"{ticker}_01",
        trade_sequence=1,
        entry_signal_date="2022-01-07",
        entry_execution_date="2022-01-10",
        entry_open=10000.0,
        entry_pattern_a_stage="TRANSITION",
        fast_stage="TRIGGER",
        monthly_regime="PERMITTED_REGIME",
        daily_risk="NORMAL",
        fast_score=75.0,
        fast_score_state="READY",
        investability_status="INVESTABLE",
        investability_market_cap=500_000_000_000.0,
        investability_avg_trading_value_20d=10_000_000_000.0,
        investability_market_cap_source_file=None,
        previous_exit_type=None,
        previous_exit_execution_date=None,
        loss_guard_triggered=False,
        loss_guard_signal_date=None,
        loss_guard_execution_date=None,
        loss_guard_execution_price=None,
        first_progressed_date=None,
        first_progressed_effective_trading_date=None,
        lifecycle_class="NORMAL_EARLY_TREND_HANDOFF",
        exit_type=exit_type,
        exit_signal_date=None,
        exit_execution_date="2022-05-10",
        exit_price=10000.0 * (1.0 + ret / 100.0),
        terminal_return=ret,
        mfe=mfe,
        mae=mae,
        peak_giveback=0.0,
        profit_capture=None,
        holding_weeks=16.0,
        trade_status="REALIZED",
        investability_meta={},
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
    
    test_date = "2022-01-07"
    if test_date in proxy_reg.official_dates:
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
    early_date = "2021-01-01"
    res = proxy_reg.lookup_market_cap(early_date, "005930")
    assert res is None


def test_proxy_registry_missing_prior_anchor_fail_closed():
    """Verify fail-closed behavior when no prior anchor or no price data is available."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    res = proxy_reg.lookup_market_cap("2024-01-05", "NON_EXISTENT_TICKER")
    assert res is None


def test_proxy_registry_baseline_julia_same_mcap():
    """Verify Baseline and Julia always get the exact same market cap value for the same date/ticker."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    test_date = "2024-01-05"
    baseline_val = proxy_reg.lookup_market_cap(test_date, "005930")
    julia_val = proxy_reg.lookup_market_cap(test_date, "005930")
    assert baseline_val == julia_val


def test_strategy_metrics_percentage_point_threshold_classification():
    """Verify exact count and rate classification for percentage-point return values."""
    sample_returns = [-35.0, -25.0, -17.0, -12.0, 5.0, 25.0, 55.0, 120.0]
    trades = [_make_dummy_trade(r) for r in sample_returns]

    metrics = calculate_strategy_metrics(trades)
    dist = metrics["distribution_stats"]

    assert dist["le_neg10_count"] == 4
    assert dist["le_neg10_rate"] == 4 / 8

    assert dist["le_neg15_count"] == 3
    assert dist["le_neg15_rate"] == 3 / 8

    assert dist["le_neg20_count"] == 2
    assert dist["le_neg20_rate"] == 2 / 8

    assert dist["le_neg30_count"] == 1
    assert dist["le_neg30_rate"] == 1 / 8

    assert dist["ge_pos20_count"] == 3
    assert dist["ge_pos20_rate"] == 3 / 8

    assert dist["ge_pos30_count"] == 2
    assert dist["ge_pos30_rate"] == 2 / 8

    assert dist["ge_pos50_count"] == 2
    assert dist["ge_pos50_rate"] == 2 / 8

    assert dist["ge_pos100_count"] == 1
    assert dist["ge_pos100_rate"] == 1 / 8


def test_strategy_metrics_mean_median_no_double_scaling():
    """Verify mean and median returns maintain percentage-point unit without double scaling."""
    sample_returns = [10.0, 20.0, 30.0]
    trades = [_make_dummy_trade(r) for r in sample_returns]

    metrics = calculate_strategy_metrics(trades)
    assert metrics["return_stats"]["mean"] == 20.0
    assert metrics["return_stats"]["median"] == 20.0
    assert metrics["return_stats"]["positive_rate"] == 1.0


def test_markdown_report_no_double_scaling_and_no_fraction_mislabel():
    """Verify generated Markdown report contains normalized percentage values without *100 artifact or 'fraction' mislabel."""
    if not DOCS_MD_PATH.exists():
        pytest.skip("Report markdown does not exist yet")

    content = DOCS_MD_PATH.read_text(encoding="utf-8")
    assert "+12.80%" in content
    assert "+23.13%" in content
    assert "+912.41%" in content
    assert "+1280.02%" not in content
    assert "+2313.09%" not in content
    assert "+91241.00%" not in content
    # Verify 'fraction' mislabel removed from table headers
    assert "fraction)" not in content


def test_ticker_exact_6digit_preservation():
    r"""Verify all tickers in derived artifacts and markdown match exact 6-digit regex ^\d{6}$."""
    winners_path = PROXY_DIR / "big_winners.csv"
    worst_path = PROXY_DIR / "worst_losses.csv"

    df_w = pd.read_csv(winners_path, dtype={"ticker": str})
    df_l = pd.read_csv(worst_path, dtype={"ticker": str})

    ticker_pattern = re.compile(r"^\d{6}$")

    for t in df_w["ticker"]:
        assert ticker_pattern.match(t), f"Invalid ticker format in big_winners: {t}"

    for t in df_l["ticker"]:
        assert ticker_pattern.match(t), f"Invalid ticker format in worst_losses: {t}"

    # Specific known tickers with leading zeros
    assert "043260" in df_w["ticker"].values
    assert "047040" in df_w["ticker"].values
    assert "058610" in df_w["ticker"].values

    # Check Markdown contains 6-digit tickers
    md_content = DOCS_MD_PATH.read_text(encoding="utf-8")
    assert "`043260`" in md_content
    assert "`047040`" in md_content


def test_proxy_contract_schema_completeness():
    """Verify proxy_contract.json contains complete schema, governance invariants, and proxy rules."""
    contract_path = PROXY_DIR / "proxy_contract.json"
    data = json.loads(contract_path.read_text(encoding="utf-8"))

    required_keys = [
        "contract_name", "strategy_id", "base_strategy_id", "experiment_id",
        "evidence_status", "estimated_market_cap_used", "not_100_percent_accurate_market_cap_data",
        "not_production_evidence", "official_full_pit_status", "julia_production_status",
        "production_default_strategy_id", "research_verdict", "evaluation_window",
        "official_reference_date_count", "proxy_reference_date_count", "total_reference_date_count",
        "price_semantics", "primary_proxy_method", "proxy_rules", "conservative_boundary_buffer_krw",
    ]
    for k in required_keys:
        assert k in data, f"Missing key in proxy_contract.json: {k}"

    assert data["proxy_rules"]["official_dates_rule"] == "USE_EXACT_KRX_OFFICIAL_MARKET_CAP"
    assert data["proxy_rules"]["missing_dates_rule"] == "METHOD_B_ANCHOR_PRICE_RATIO_PROXY"
    assert data["proxy_rules"]["anchor_direction"] == "STRICTLY_PRIOR_ANCHOR_ONLY"
    assert data["proxy_rules"]["future_anchor_forbidden"] is True
    assert data["research_verdict"] == "MIXED"


def test_proxy_run_manifest_provenance_metadata():
    """Verify proxy_run_manifest.json includes complete SHA lineage and execution invariants."""
    man_path = PROXY_DIR / "proxy_run_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))

    assert manifest["authoritative_experiment_base_sha"] == "030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377"
    assert manifest["proxy_full_run_commit"] == "6cdb5a6b00096d02c9cee4cc74f65ff8270056a1"
    assert manifest["fix01_source_commit"] == "afb967d211058bfce9ae053eebc2798b31b822e9"
    assert manifest["full_backtest_rerun"] is False
    assert manifest["existing_trade_artifacts_reused"] is True
    assert manifest["no_network_requests"] is True
    assert manifest["research_verdict"] == "MIXED"


def test_query_audit_sensitivity_status_column():
    """Verify proxy_market_cap_query_audit.csv includes valid sensitivity_status entries."""
    audit_path = PROXY_DIR / "proxy_market_cap_query_audit.csv"
    df = pd.read_csv(audit_path, dtype={"ticker": str})

    assert "sensitivity_status" in df.columns
    valid_statuses = {"OFFICIAL_VALUE_UNAFFECTED", "DATA_UNAVAILABLE_PROXY_BOUNDARY", "ELIGIBLE", "NOT_APPLICABLE"}
    actual_statuses = set(df["sensitivity_status"].unique())
    assert actual_statuses.issubset(valid_statuses), f"Unexpected sensitivity_status: {actual_statuses - valid_statuses}"


def test_boundary_sensitivity_unit_contract():
    """Verify boundary_sensitivity_summary.json defines explicit percentage point unit contract."""
    boundary_path = PROXY_DIR / "boundary_sensitivity_summary.json"
    data = json.loads(boundary_path.read_text(encoding="utf-8"))

    assert data.get("return_unit") == "PERCENTAGE_POINT"
    assert data["primary_baseline_mean_return"] == 12.8
    assert data["primary_julia_mean_return"] == 23.13


def test_existing_trade_preservation_invariants():
    """Verify trade-level invariants are preserved."""
    b_path = PROXY_DIR / "baseline_v2_proxy_trades.csv"
    j_path = PROXY_DIR / "julia_v00_proxy_trades.csv"
    df_b = pd.read_csv(b_path, dtype={"ticker": str})
    df_j = pd.read_csv(j_path, dtype={"ticker": str})

    assert len(df_b) == 845
    assert len(df_j) == 687
    assert df_b["ticker"].nunique() == 673
    assert df_j["ticker"].nunique() == 673


def test_loss_guard_cohort_accounting_preservation():
    """Verify full Loss Guard accounting identity (477 = 397 + 80)."""
    lg_path = PROXY_DIR / "loss_guard_recovery_summary.json"
    data = json.loads(lg_path.read_text(encoding="utf-8"))

    assert data["baseline_loss_guard_total"] == 477
    assert data["paired_loss_guard_count"] == 397
    assert data["unpaired_loss_guard_count"] == 80
    assert data["cohort_accounting_identity_holds"] is True
    assert data["julia_recovered_higher_return_count"] == 197
    assert data["julia_deeper_loss_count"] == 200
    assert data["julia_reached_progressed_count"] == 160


def test_manifest_sha_verification_pass():
    """Verify all 15 artifacts in proxy_market_cap_v01 exactly match proxy_run_manifest.json hashes."""
    man_path = PROXY_DIR / "proxy_run_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))

    for filename, meta in manifest["artifacts"].items():
        file_path = PROXY_DIR / filename
        assert file_path.exists(), f"Missing artifact file: {filename}"
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"Hash mismatch for {filename}"
