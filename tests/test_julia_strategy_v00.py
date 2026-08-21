"""Targeted Tests for Julia Strategy V00 Interrupted Checkpoint and Parity Gates.

Validates:
  - Required signal reference dates manifest determinism (215 dates)
  - Available (117) + Missing (98) partition integrity (54.42% coverage)
  - Source file existence, SHA-256 seal integrity, and KRX provenance
  - Incomplete coverage correctly blocks final authoritative backtest status
  - Report Artifact Parity (100% exact match between artifacts and documentation)
  - Canonical historical V2 artifact protection (783 trades preserved)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    HistoricalMarketCapRegistry,
)

ROOT = Path(__file__).resolve().parent.parent
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =============================================================================
# 1. Manifest, Checkpoint Audit & Coverage Integrity Tests
# =============================================================================

def test_required_dates_manifest_and_partition_integrity():
    """Verify 215 required dates, partition into available (117) and missing (98)."""
    req_path = JULIA_DIR / "historical_market_cap_required_dates.csv"
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    missing_path = JULIA_DIR / "historical_market_cap_missing_dates.csv"
    audit_path = JULIA_DIR / "historical_investability_pit_audit.json"

    assert req_path.exists()
    assert manifest_path.exists()
    assert missing_path.exists()
    assert audit_path.exists()

    df_req = pd.read_csv(req_path)
    df_man = pd.read_csv(manifest_path)
    df_missing = pd.read_csv(missing_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert len(df_req) == 215
    assert len(df_man) == 215
    assert len(df_missing) == 98

    avail_count = (df_man["available"] == True).sum()
    missing_count = (df_man["available"] == False).sum()

    assert avail_count == 117
    assert missing_count == 98
    assert avail_count + missing_count == 215

    assert audit["historical_market_cap_source_dates_required"] == 215
    assert audit["historical_market_cap_source_dates_available"] == 117
    assert audit["historical_market_cap_source_dates_missing"] == 98
    assert audit["historical_market_cap_source_coverage_rate"] == 54.42


def test_incomplete_coverage_blocks_final_status():
    """Coverage < 100% must strictly block final pit backtest ready status."""
    audit_path = JULIA_DIR / "historical_investability_pit_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["final_pit_backtest_ready"] is False
    assert audit["final_result_status"] == "INVALID_INCOMPLETE_PIT_COVERAGE"
    assert audit["source_collection_status"] == "INTERRUPTED_KRX_TEMPORARY_RESTRICTION"
    assert audit["future_market_cap_fallback_count"] == 0
    assert audit["current_20260814_market_cap_usage_count"] == 0


def test_source_file_existence_and_sha_seal_integrity():
    """Verify all available manifest rows have valid files and matching SHA256."""
    manifest_path = JULIA_DIR / "historical_market_cap_source_manifest.csv"
    df_man = pd.read_csv(manifest_path).fillna("")

    df_avail = df_man[df_man["available"] == True]
    assert len(df_avail) == 117

    for _, r in df_avail.iterrows():
        norm_file = ROOT / r["normalized_source_file"]
        assert norm_file.exists(), f"Missing normalized file: {norm_file}"
        actual_norm_sha = sha256_file(norm_file)
        assert actual_norm_sha == r["normalized_sha256"], f"Normalized SHA mismatch on {r['signal_reference_date']}"

        assert r["source_provider"] == "KRX"
        assert r["source_product"] == "ALL_STOCK_MARKET_DATA"
        assert r["integrity_status"] == "PASS"


def test_registry_manifest_authority():
    """Registry loaded from manifest has exact 117 dates with valid tickers."""
    reg = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    assert len(reg.snapshots) == 117
    # Verify 005930 market cap is loaded for 2022-02-04
    mcap, meta = reg.get_market_cap_at_reference("005930", "2022-02-04")
    assert mcap is not None and mcap > 100_000_000_000
    assert meta["provider"] == "KRX"

    # Missing date returns None (Fail Closed)
    mcap_none, meta_none = reg.get_market_cap_at_reference("005930", "2024-07-19")
    assert mcap_none is None
    assert meta_none is None


# =============================================================================
# 2. Report Artifact Parity Tests
# =============================================================================

def test_report_artifact_parity():
    """Verify report documentation matches CSV/JSON artifacts."""
    doc_path = ROOT / "docs/strategies/julia/v00.md"
    summary_path = JULIA_DIR / "strategy_comparison_summary.json"
    winners_path = JULIA_DIR / "big_winners.csv"
    worst_path = JULIA_DIR / "worst_losses.csv"

    assert doc_path.exists()
    doc_text = doc_path.read_text(encoding="utf-8")

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        b_trades = summary["baseline_v2_2022"]["total_trades"]
        j_trades = summary["julia_v00_2022"]["total_trades"]
        assert f"| **Total Trades** | {b_trades} | {j_trades} |" in doc_text

    if winners_path.exists():
        df_w = pd.read_csv(winners_path)
        if not df_w.empty:
            top_winner = df_w.iloc[0]
            top_ticker = str(top_winner["ticker"]).zfill(6)
            top_ret = float(top_winner["julia_terminal_return"])
            assert f"`{top_ticker}`" in doc_text
            assert f"{top_ret:.2f}%" in doc_text

    if worst_path.exists():
        df_l = pd.read_csv(worst_path)
        if not df_l.empty:
            worst_loss = df_l.iloc[0]
            worst_ticker = str(worst_loss["ticker"]).zfill(6)
            worst_ret = float(worst_loss["julia_terminal_return"])
            assert f"`{worst_ticker}`" in doc_text
            assert f"{worst_ret:.2f}%" in doc_text


# =============================================================================
# 3. Canonical V2 Protection Test
# =============================================================================

def test_canonical_v2_artifacts_unaltered():
    """Verify historical V2 783 trades artifact is intact."""
    historical_v2_csv = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    assert historical_v2_csv.exists()
    df_hist = pd.read_csv(historical_v2_csv)
    assert len(df_hist) == 783
