"""Focused checks for the FastCore V3 exit A/B and bucket diagnostics."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pandas as pd

from scripts import analyze_fastcore_v3_exit_ab_v00 as analysis
from scripts import run_fastcore_v3_simple_v00 as v3


ROOT = Path(__file__).resolve().parents[1]
OUT = analysis.OUT_DIR


def _matched() -> pd.DataFrame:
    return pd.read_csv(OUT / "matched_control_entries_v2_vs_v0.csv")


def test_control_and_matched_row_counts_are_frozen() -> None:
    control = pd.read_csv(analysis.CONTROL_TRADES_PATH)
    matched = _matched()
    assert len(control) == 973
    assert len(matched) == 973


def test_matched_entries_preserve_control_dates_and_prices() -> None:
    matched = _matched()
    assert matched["v0_entry_date_match_control"].eq(True).all()
    assert matched["v0_entry_open_match_control"].eq(True).all()
    assert matched["entry_execution_date"].notna().all()
    assert matched["entry_open"].notna().all()


def test_ab_diagnostic_does_not_re_evaluate_entry_filters() -> None:
    summary = json.loads((OUT / "matched_control_entries_v2_vs_v0_summary.json").read_text())
    assert summary["control_entry_filter_re_evaluated"] is False
    assert summary["independent_trade_replay"] is True
    assert summary["overlap_removal"] is False


def test_fix01_separates_median_statistics() -> None:
    summary = json.loads((OUT / "matched_control_entries_v2_vs_v0_summary.json").read_text())
    overall = summary["matched_entry_summary"]
    assert overall["median_terminal_return_difference_pp"] == 24.34
    assert overall["median_paired_return_delta_pp"] == 10.23
    assert overall["mean_terminal_return_difference_pp"] == -0.19408
    assert overall["mean_paired_return_delta_pp"] == -0.19408


def test_loss_guard_has_all_v2_v0_tail_fields() -> None:
    frame = pd.read_csv(OUT / "v2_loss_guard_subset_diagnostics.csv")
    for side in ("v2", "v0"):
        for threshold in (20, 30, 40, 50, 60):
            assert f"{side}_le_-{threshold}_count" in frame.columns
            assert f"{side}_le_-{threshold}_rate_pct" in frame.columns


def test_soft_hard_diagnostics_match_source_values() -> None:
    frame = pd.read_csv(OUT / "v0_exit_reason_diagnostics.csv").set_index("group")
    assert frame.loc["SOFT_EXIT", "v2_ge_50_count"] == 110
    assert frame.loc["SOFT_EXIT", "v0_ge_50_count"] == 14
    assert frame.loc["SOFT_EXIT", "v2_ge_100_count"] == 35
    assert frame.loc["SOFT_EXIT", "v0_ge_100_count"] == 5
    assert frame.loc["HARD_EXIT", "v2_ge_50_count"] == 49
    assert frame.loc["HARD_EXIT", "v0_ge_50_count"] == 35
    assert frame.loc["HARD_EXIT", "v2_ge_100_count"] == 22
    assert frame.loc["HARD_EXIT", "v0_ge_100_count"] == 19
    assert frame.loc["SOFT_EXIT", "mean_return_delta_pct"] == 1.853233
    assert frame.loc["HARD_EXIT", "mean_return_delta_pct"] == 17.221398


def test_existing_v3_artifact_and_network_audit_are_unchanged() -> None:
    expected = {
        "fastcore_v3_trades.csv": "0a3fedbd4cc44621fe1f4b5ee2ed91931e9bf48e7a114315c642fb85c9430cbb",
        "fastcore_v3_summary.json": "e7dae73d6df208a7aca9591e790b00741379aa444bde07e782b4b902c87cf7c8",
    }
    for name, digest in expected.items():
        actual = hashlib.sha256((analysis.V3_TRADES_PATH if name.endswith("trades.csv") else analysis.V3_SUMMARY_PATH).read_bytes()).hexdigest()
        assert actual == digest
    summary = json.loads((OUT / "matched_control_entries_v2_vs_v0_summary.json").read_text())
    assert summary["network_requests"] == 0


def test_v0_mfe_boundary_and_exit_contract() -> None:
    assert v3.mfe_tier(19.99) is None
    assert v3.mfe_tier(20.0) == (-10.0, -20.0, "MFE_20_TO_50")
    assert v3.mfe_tier(50.0) == (-15.0, -25.0, "MFE_50_TO_100")
    assert v3.mfe_tier(100.0) == (-20.0, -30.0, "MFE_100_TO_200")
    assert v3.mfe_tier(200.0) == (-25.0, -35.0, "MFE_200_TO_400")
    assert v3.mfe_tier(400.0) == (-30.0, -40.0, "MFE_400_PLUS")
    assert v3.exit_decision(mfe_pct=19.99, hwm_price=120.0, current_close=1.0, fast_state="SETUP")[0] is None
    assert v3.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=108.0, fast_state="WATCH")[0] == "SOFT_EXIT"
    assert v3.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=108.0, fast_state="TREND")[0] is None
    for state in (None, "SETUP", "WATCH", "TREND", "EXTENDED"):
        assert v3.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=96.0, fast_state=state)[0] == "HARD_EXIT"


def test_matched_execution_has_no_lookahead_and_uses_next_open() -> None:
    matched = _matched()
    realized = matched[matched["v0_trade_status"] == "REALIZED"]
    assert (pd.to_datetime(realized["v0_exit_execution_date"]) > pd.to_datetime(realized["v0_exit_signal_date"])).all()
    assert (pd.to_datetime(matched["entry_execution_date"]) > pd.to_datetime(matched["entry_signal_date"])).all()
    assert (pd.to_datetime(realized["v0_exit_signal_date"]) >= pd.to_datetime(realized["entry_execution_date"])).all()


def test_open_at_cutoff_has_no_fake_sell() -> None:
    matched = _matched()
    open_rows = matched[matched["v0_trade_status"] == "OPEN_AT_CUTOFF"]
    assert open_rows["v0_exit_reason"].eq("OPEN_AT_CUTOFF").all()
    assert open_rows["v0_exit_execution_date"].isna().all()
    assert open_rows["v0_exit_price"].isna().all()


def test_bucket_sum_and_mcap_floor_match_current_v3() -> None:
    summary = json.loads((OUT / "matched_control_entries_v2_vs_v0_summary.json").read_text())
    buckets = pd.read_csv(OUT / "v3_market_cap_bucket_diagnostics.csv")
    v3_trades = pd.read_csv(analysis.V3_TRADES_PATH)
    assert len(v3_trades) == 1578
    assert buckets["total_trades"].sum() == 1578
    assert (pd.to_numeric(v3_trades["entry_market_cap"]) >= 100_000_000_000).all()
    assert summary["v3_bucket_sum_total_trades"] == summary["v3_bucket_total_trades"] == 1578


def test_diagnostic_outputs_are_complete() -> None:
    expected = {
        "matched_control_entries_v2_vs_v0.csv",
        "matched_control_entries_v2_vs_v0_summary.json",
        "v0_mfe_tier_diagnostics.csv",
        "v2_loss_guard_subset_diagnostics.csv",
        "v0_exit_reason_diagnostics.csv",
        "v3_market_cap_bucket_diagnostics.csv",
        "fastcore_v3_exit_ab_v00_fix01_report.md",
    }
    assert {path.name for path in OUT.iterdir()} == expected
