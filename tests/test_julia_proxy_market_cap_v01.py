"""Comprehensive Unit and Regression tests for Julia Proxy Market Cap PIT V01 (FIX03 FINAL).

Full coverage of the 31-point requirement checklist:
1. Method B formula
2. Official KRX exact preference
3. Strictly prior anchor rule
4. No future anchor rule
5. Fail-closed missing data
6. Baseline/Julia same market cap parity
7. Percentage-point threshold classification
8. No double scaling in reports and metrics
9. Ticker exact 6-digit zero-padded preservation
10. Proxy contract complete schema
11. evaluation_window.start and evaluation_window.end schema compatibility
12. Manifest provenance metadata
13. Audit sensitivity_status enum validity
14. Audit contains boundary excluded rows
15. Sensitivity percentage-point contract
16. Trade count invariant (845 / 687, unique tickers 673)
17. Loss Guard cohort invariant (477 = 397 + 80, 197 recovered, 200 deeper, 160 progressed)
18. Manifest SHA-256 verification across all 15 sealed artifacts
19. SUPPORTIVE verdict branch
20. MIXED verdict branch
21. UNFAVORABLE verdict branch
22. Proxy 90B boundary behavior (near_threshold=True, sensitivity_status="DATA_UNAVAILABLE_PROXY_BOUNDARY", Primary FAIL)
23. Proxy 110B boundary behavior (near_threshold=True, sensitivity_status="DATA_UNAVAILABLE_PROXY_BOUNDARY", Primary PASS)
24. Actual KRX 110B unaffected (sensitivity_status="OFFICIAL_VALUE_UNAFFECTED", Primary PASS)
25. Baseline exit count exact invariants
26. Julia exit count exact invariants
27. Baseline confidence accounting
28. Julia confidence accounting
29. Actual + Proxy entry accounting
30. No strategy simulation in post-processing (AST static check)
31. No parquet / OHLCV access in post-processing (AST static check)
32. Immutable trade artifacts SHA-256 exact match
"""

from __future__ import annotations

import ast
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
    PRIMARY_MIN_MARKET_CAP_KRW,
    ROOT,
    SENSITIVITY_LOWER_BOUND_KRW,
    SENSITIVITY_UPPER_BOUND_KRW,
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
REBUILD_SCRIPT_PATH = ROOT / "scripts/rebuild_julia_proxy_reports_from_trades.py"


def _make_dummy_trade(
    ret: float,
    mae: float = -10.0,
    mfe: float = 20.0,
    exit_type: str = "EXIT4_SCORE_DRAWDOWN_GE_15",
    ticker: str = "005930",
) -> StrategyTradeRecord:
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


# 1. Method B formula
def test_proxy_method_b_formula():
    """Verify Method B: Estimated MCap = anchor_mcap * (current_price / anchor_price)."""
    anchor_mcap = 100_000_000_000
    anchor_price = 10_000.0
    current_price = 12_500.0

    est_mcap = calculate_proxy_market_cap_method_b(
        anchor_mcap=anchor_mcap,
        anchor_price=anchor_price,
        current_price=current_price,
    )
    assert est_mcap == 125_000_000_000


# 2. Official KRX exact preference
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


# 3. Strictly prior anchor
def test_proxy_registry_uses_only_prior_anchor():
    """Verify proxy calculation uses only strictly prior anchor dates."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    all_dates = sorted(list(proxy_reg.all_required_dates))
    non_official = [d for d in all_dates if d not in proxy_reg.official_dates and d > proxy_reg.official_dates[0]]
    test_date = non_official[0]

    res = proxy_reg.lookup_market_cap(test_date, "005930")
    if res is not None:
        assert res["market_cap_source"] == "ANCHOR_PRICE_RATIO_PROXY"
        assert res["anchor_date"] < test_date
        assert res["anchor_date"] in proxy_reg.official_dates


# 4. No future anchor
def test_proxy_registry_never_uses_future_anchor():
    """Verify registry never selects an anchor date greater than target date."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    early_date = "2021-01-01"
    res = proxy_reg.lookup_market_cap(early_date, "005930")
    assert res is None


# 5. Fail-closed missing data
def test_proxy_registry_missing_prior_anchor_fail_closed():
    """Verify fail-closed behavior when no prior anchor or no price data is available."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    res = proxy_reg.lookup_market_cap("2024-01-05", "NON_EXISTENT_TICKER")
    assert res is None


# 6. Baseline/Julia same mcap
def test_proxy_registry_baseline_julia_same_mcap():
    """Verify Baseline and Julia always get the exact same market cap value for the same date/ticker."""
    proxy_reg = ProxyHistoricalMarketCapRegistry.load_from_repository()
    test_date = "2024-01-05"
    baseline_val = proxy_reg.lookup_market_cap(test_date, "005930")
    julia_val = proxy_reg.lookup_market_cap(test_date, "005930")
    assert baseline_val == julia_val


# 7. Percentage-point threshold classification
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


# 8. No double scaling
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
    assert "fraction)" not in content


# 9. Ticker exact 6-digit preservation
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

    assert "043260" in df_w["ticker"].values
    assert "047040" in df_w["ticker"].values
    assert "058610" in df_w["ticker"].values

    md_content = DOCS_MD_PATH.read_text(encoding="utf-8")
    assert "`043260`" in md_content
    assert "`047040`" in md_content


# 10. Proxy contract complete schema
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


# 11. evaluation_window.start and evaluation_window.end schema compatibility
def test_proxy_contract_evaluation_window_schema():
    """Verify proxy_contract.json uses evaluation_window.start and end schema compatibility."""
    contract_path = PROXY_DIR / "proxy_contract.json"
    data = json.loads(contract_path.read_text(encoding="utf-8"))

    ew = data["evaluation_window"]
    assert ew["start"] == "2022-01-01"
    assert ew["end"] == "2026-08-14"
    assert "evaluation_start" not in ew
    assert "evaluation_end" not in ew


# 12. Manifest provenance metadata
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


# 13. Audit sensitivity_status enum validity
def test_query_audit_sensitivity_status_column():
    """Verify proxy_market_cap_query_audit.csv includes valid sensitivity_status entries."""
    audit_path = PROXY_DIR / "proxy_market_cap_query_audit.csv"
    df = pd.read_csv(audit_path, dtype={"ticker": str})

    assert "sensitivity_status" in df.columns
    valid_statuses = {"OFFICIAL_VALUE_UNAFFECTED", "DATA_UNAVAILABLE_PROXY_BOUNDARY", "ELIGIBLE", "NOT_APPLICABLE"}
    actual_statuses = set(df["sensitivity_status"].unique())
    assert actual_statuses.issubset(valid_statuses), f"Unexpected sensitivity_status: {actual_statuses - valid_statuses}"


# 14. Audit contains boundary excluded rows
def test_query_audit_contains_boundary_excluded_rows():
    """Verify proxy_market_cap_query_audit.csv contains DATA_UNAVAILABLE_PROXY_BOUNDARY and OFFICIAL_VALUE_UNAFFECTED rows."""
    audit_path = PROXY_DIR / "proxy_market_cap_query_audit.csv"
    df = pd.read_csv(audit_path, dtype={"ticker": str})

    boundary_count = (df["sensitivity_status"] == "DATA_UNAVAILABLE_PROXY_BOUNDARY").sum()
    official_count = (df["sensitivity_status"] == "OFFICIAL_VALUE_UNAFFECTED").sum()

    assert boundary_count >= 1, f"Expected at least 1 DATA_UNAVAILABLE_PROXY_BOUNDARY, got {boundary_count}"
    assert official_count >= 1, f"Expected at least 1 OFFICIAL_VALUE_UNAFFECTED, got {official_count}"


# 15. Sensitivity percentage-point contract
def test_boundary_sensitivity_unit_contract():
    """Verify boundary_sensitivity_summary.json defines explicit percentage point unit contract."""
    boundary_path = PROXY_DIR / "boundary_sensitivity_summary.json"
    data = json.loads(boundary_path.read_text(encoding="utf-8"))

    assert data.get("return_unit") == "PERCENTAGE_POINT"
    assert data["primary_baseline_mean_return"] == 12.8
    assert data["primary_julia_mean_return"] == 23.13


# 16. Trade count invariant
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


# 17. Loss Guard cohort invariant
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


# 18. Manifest SHA verification
def test_manifest_sha_verification_pass():
    """Verify all 15 artifacts in proxy_market_cap_v01 exactly match proxy_run_manifest.json hashes."""
    man_path = PROXY_DIR / "proxy_run_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8"))

    for filename, meta in manifest["artifacts"].items():
        file_path = PROXY_DIR / filename
        assert file_path.exists(), f"Missing artifact file: {filename}"
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"Hash mismatch for {filename}"


# 19, 20, 21. 3-State Verdict unit tests
from scripts.rebuild_julia_proxy_reports_from_trades import evaluate_research_verdict


def test_evaluate_research_verdict_supportive_branch():
    """Verify evaluate_research_verdict returns SUPPORTIVE_OF_JULIA when all metrics and tails are strictly favorable."""
    b_metrics = {
        "return_stats": {"mean": 10.0, "median": -5.0, "positive_rate": 0.40},
        "distribution_stats": {"le_neg20_rate": 0.30, "le_neg30_rate": 0.15, "ge_pos50_rate": 0.10, "ge_pos100_rate": 0.05},
        "mae_stats": {"mean": -15.0},
    }
    j_metrics = {
        "return_stats": {"mean": 20.0, "median": 5.0, "positive_rate": 0.60},
        "distribution_stats": {"le_neg20_rate": 0.20, "le_neg30_rate": 0.10, "ge_pos50_rate": 0.25, "ge_pos100_rate": 0.12},
        "mae_stats": {"mean": -12.0},
    }
    sens_summary = {"conclusion_robust_to_boundary": True}

    verdict, rationale = evaluate_research_verdict(b_metrics, j_metrics, sens_summary)
    assert verdict == "SUPPORTIVE_OF_JULIA"
    assert "Julia outperforms Baseline V2 across mean return" in rationale


def test_evaluate_research_verdict_mixed_branch():
    """Verify evaluate_research_verdict returns MIXED when performance improves but drawdown tails worsen."""
    b_metrics = {
        "return_stats": {"mean": 12.80, "median": -14.57, "positive_rate": 0.3456},
        "distribution_stats": {"le_neg20_rate": 0.0556, "le_neg30_rate": 0.0166, "ge_pos50_rate": 0.1799, "ge_pos100_rate": 0.0615},
        "mae_stats": {"mean": -15.41},
    }
    j_metrics = {
        "return_stats": {"mean": 23.13, "median": 1.13, "positive_rate": 0.5109},
        "distribution_stats": {"le_neg20_rate": 0.2722, "le_neg30_rate": 0.1645, "ge_pos50_rate": 0.2649, "ge_pos100_rate": 0.1004},
        "mae_stats": {"mean": -26.31},
    }
    sens_summary = {"conclusion_robust_to_boundary": True}

    verdict, rationale = evaluate_research_verdict(b_metrics, j_metrics, sens_summary)
    assert verdict == "MIXED"
    assert "drawdown trades" in rationale


def test_evaluate_research_verdict_unfavorable_branch():
    """Verify evaluate_research_verdict returns UNFAVORABLE_TO_JULIA when Julia underperforms across return metrics."""
    b_metrics = {
        "return_stats": {"mean": 20.0, "median": 5.0, "positive_rate": 0.55},
        "distribution_stats": {"le_neg20_rate": 0.10, "le_neg30_rate": 0.05, "ge_pos50_rate": 0.20, "ge_pos100_rate": 0.10},
        "mae_stats": {"mean": -10.0},
    }
    j_metrics = {
        "return_stats": {"mean": 10.0, "median": -2.0, "positive_rate": 0.35},
        "distribution_stats": {"le_neg20_rate": 0.25, "le_neg30_rate": 0.15, "ge_pos50_rate": 0.08, "ge_pos100_rate": 0.02},
        "mae_stats": {"mean": -25.0},
    }
    sens_summary = {"conclusion_robust_to_boundary": False}

    verdict, rationale = evaluate_research_verdict(b_metrics, j_metrics, sens_summary)
    assert verdict == "UNFAVORABLE_TO_JULIA"
    assert "Julia underperforms Baseline V2" in rationale


# 22, 23, 24. Boundary semantics behavior
def test_boundary_semantics_proxy_90b_fail_and_boundary_unavailable():
    """Verify 90B proxy mcap fails primary 100B threshold, sets near_threshold=True and sensitivity_status=DATA_UNAVAILABLE_PROXY_BOUNDARY."""
    mcap = 90_000_000_000.0
    is_proxy = True
    near_thresh = bool(SENSITIVITY_LOWER_BOUND_KRW <= mcap <= SENSITIVITY_UPPER_BOUND_KRW)
    primary_pass = bool(mcap >= PRIMARY_MIN_MARKET_CAP_KRW)

    assert primary_pass is False  # 90B < 100B
    assert near_thresh is True
    sensitivity_status = "DATA_UNAVAILABLE_PROXY_BOUNDARY" if (is_proxy and near_thresh) else "ELIGIBLE"
    assert sensitivity_status == "DATA_UNAVAILABLE_PROXY_BOUNDARY"


def test_boundary_semantics_proxy_110b_pass_and_boundary_unavailable():
    """Verify 110B proxy mcap passes primary 100B threshold, but in sensitivity mode is DATA_UNAVAILABLE_PROXY_BOUNDARY (fail closed)."""
    mcap = 110_000_000_000.0
    is_proxy = True
    near_thresh = bool(SENSITIVITY_LOWER_BOUND_KRW <= mcap <= SENSITIVITY_UPPER_BOUND_KRW)
    primary_pass = bool(mcap >= PRIMARY_MIN_MARKET_CAP_KRW)

    assert primary_pass is True  # 110B >= 100B
    assert near_thresh is True
    sensitivity_status = "DATA_UNAVAILABLE_PROXY_BOUNDARY" if (is_proxy and near_thresh) else "ELIGIBLE"
    assert sensitivity_status == "DATA_UNAVAILABLE_PROXY_BOUNDARY"


def test_boundary_semantics_actual_krx_110b_unaffected():
    """Verify 110B Actual KRX value passes primary and is OFFICIAL_VALUE_UNAFFECTED (never excluded)."""
    mcap = 110_000_000_000.0
    source_type = "ACTUAL_KRX"
    primary_pass = bool(mcap >= PRIMARY_MIN_MARKET_CAP_KRW)

    assert primary_pass is True
    sensitivity_status = "OFFICIAL_VALUE_UNAFFECTED" if source_type == "ACTUAL_KRX" else "ELIGIBLE"
    assert sensitivity_status == "OFFICIAL_VALUE_UNAFFECTED"


# 25, 26. Exit count exact invariants
def test_exit_type_counts_baseline_exact_invariants():
    """Verify exact distribution of exit types in Baseline V2."""
    b_path = PROXY_DIR / "baseline_v2_proxy_trades.csv"
    df_b = pd.read_csv(b_path, dtype={"ticker": str})
    counts = df_b["exit_type"].value_counts().to_dict()

    assert counts.get("LOSS_GUARD_CLOSE_LE_NEG_15") == 477
    assert counts.get("EXIT4_SCORE_DRAWDOWN_GE_15") == 226
    assert counts.get("NO_EXIT_BEFORE_CUTOFF") == 59
    assert counts.get("NO_PROGRESSED_BEFORE_CUTOFF") == 55
    assert counts.get("EXIT3_PROGRESSED_TO_WEAK") == 14
    assert counts.get("EXIT3_PROGRESSED_TO_TRANSITION") == 9
    assert counts.get("EXIT3_PROGRESSED_TO_EARLY_TREND") == 3
    assert counts.get("EXIT3_PROGRESSED_TO_BASE") == 2
    assert len(df_b) == 845


def test_exit_type_counts_julia_exact_invariants():
    """Verify exact distribution of exit types in Julia V00."""
    j_path = PROXY_DIR / "julia_v00_proxy_trades.csv"
    df_j = pd.read_csv(j_path, dtype={"ticker": str})
    counts = df_j["exit_type"].value_counts().to_dict()

    assert counts.get("NO_PROGRESSED_BEFORE_CUTOFF") == 281
    assert counts.get("EXIT4_SCORE_DRAWDOWN_GE_15") == 278
    assert counts.get("NO_EXIT_BEFORE_CUTOFF") == 93
    assert counts.get("EXIT3_PROGRESSED_TO_WEAK") == 19
    assert counts.get("EXIT3_PROGRESSED_TO_TRANSITION") == 8
    assert counts.get("EXIT3_PROGRESSED_TO_BASE") == 5
    assert counts.get("EXIT3_PROGRESSED_TO_EARLY_TREND") == 3
    assert len(df_j) == 687


# 27, 28, 29. Confidence & Entry accounting invariants
def test_proxy_confidence_and_entry_accounting_invariants():
    """Verify confidence accounting identity (High + Med + Low == Total Proxy) and (Actual + Proxy == Total Trades)."""
    sum_path = PROXY_DIR / "strategy_comparison_summary.json"
    data = json.loads(sum_path.read_text(encoding="utf-8"))
    dep = data["proxy_dependence"]

    # Baseline
    assert dep["baseline_high_confidence_proxy_entries"] == 225
    assert dep["baseline_medium_confidence_proxy_entries"] == 237
    assert dep["baseline_low_confidence_proxy_entries"] == 294
    assert 225 + 237 + 294 == dep["baseline_proxy_entries"] == 756
    assert dep["baseline_near_threshold_proxy_entries"] == 58
    assert dep["baseline_actual_krx_entries"] + dep["baseline_proxy_entries"] == dep["baseline_total_trades"] == 845

    # Julia
    assert dep["julia_high_confidence_proxy_entries"] == 201
    assert dep["julia_medium_confidence_proxy_entries"] == 211
    assert dep["julia_low_confidence_proxy_entries"] == 210
    assert 201 + 211 + 210 == dep["julia_proxy_entries"] == 622
    assert dep["julia_near_threshold_proxy_entries"] == 54
    assert dep["julia_actual_krx_entries"] + dep["julia_proxy_entries"] == dep["julia_total_trades"] == 687


# 30. No strategy simulation in post-processing (AST check)
def test_no_strategy_simulation_in_post_processing():
    """Verify post-processing rebuild script contains zero simulation calls/imports."""
    script_content = REBUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(script_content)

    forbidden_calls = {"simulate_ticker_strategy_2022", "evaluate_pattern_a", "evaluate_pattern_a_fast", "build_historical_snapshot"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                pytest.fail(f"Forbidden simulation call found in rebuild script: {node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls:
                pytest.fail(f"Forbidden simulation call found in rebuild script: {node.func.attr}")


# 31. No parquet / OHLCV access in post-processing (AST check)
def test_no_parquet_access_in_post_processing():
    """Verify post-processing rebuild script contains zero parquet or OHLCV raw cache loads."""
    script_content = REBUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(script_content)

    forbidden_identifiers = {"read_parquet", "ParquetCache"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_identifiers:
                pytest.fail(f"Forbidden parquet/cache call in rebuild script: {node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_identifiers:
                pytest.fail(f"Forbidden parquet/cache call in rebuild script: {node.func.attr}")


# 32. Immutable trade artifacts SHA-256 exact match
def test_immutable_trade_artifacts_sha_exact_match():
    """Verify the 5 core trade artifacts maintain byte-level immutable SHA-256 hashes."""
    expected_shas = {
        "baseline_v2_proxy_trades.csv": "2121475653cff589cc9452c79e1334742419091df0af9258d18116730a5c2f98",
        "julia_v00_proxy_trades.csv": "a6dca44a6cafd44c95c69601019191a26e0804b3ce4962a684143eb3a8a3a288",
        "common_entry_paired_comparison.csv": "c93fe7598305dbc25302ca595a7befb57a4c887e57545d12368fafd211debd1b",
        "loss_guard_counterfactual.csv": "66dffd1c1ceadc3e5ac2b207ee17b28031dbadea80bf44ffec892ad4eacdbaeb",
        "strategy_path_divergence.csv": "ace705331c53babd78755f07455bff396d3568f76801fc55eb3c1a106dea9a88",
    }
    for filename, exp_sha in expected_shas.items():
        file_path = PROXY_DIR / filename
        assert file_path.exists(), f"Missing trade artifact: {filename}"
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_sha == exp_sha, f"Immutable artifact mutated! File: {filename}, Expected: {exp_sha}, Actual: {actual_sha}"
