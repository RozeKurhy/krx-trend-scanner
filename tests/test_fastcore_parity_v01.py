"""FASTCORE_PARITY_V01 comparator and frozen-contract checks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.run_fastcore_parity_v01 import (
    TRADE_COLUMNS,
    compare_trades,
    metrics_parity,
    trade_level_parity_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _trade_row(**overrides: object) -> dict[str, object]:
    row = {column: None for column in TRADE_COLUMNS}
    row.update(
        {
            "ticker": "000001",
            "name": "예시",
            "market": "KOSPI",
            "trade_id": "000001_01",
            "trade_sequence": 1,
            "entry_signal_date": "2026-01-02",
            "entry_execution_date": "2026-01-05",
            "entry_pattern_a_stage": "TRANSITION",
            "fast_stage": "TRIGGER",
            "monthly_regime": "PERMITTED_REGIME",
            "daily_risk": "NORMAL",
            "fast_score_state": "READY",
            "loss_guard_triggered": False,
            "lifecycle_class": "NEVER_PROGRESSED",
            "exit_type": "NO_PROGRESSED_BEFORE_CUTOFF",
            "trade_status": "OPEN_AT_CUTOFF",
        }
    )
    row.update(overrides)
    return row


def test_trade_comparator_is_exact_and_fail_closed():
    authority = pd.DataFrame([_trade_row(entry_open=100.0)])
    production = pd.DataFrame([_trade_row(entry_open=100.0)])
    result = compare_trades(authority, production)
    assert result["missing_trades"] == 0
    assert result["extra_trades"] == 0
    assert result["structural_mismatches"] == 0
    assert result["numeric_mismatches"] == 0

    production.loc[0, "entry_open"] = 100.01
    result = compare_trades(authority, production)
    assert result["numeric_mismatches"] == 1


def test_metrics_and_trade_rows_match_reconciled_frozen_contract():
    authority_path = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
    contract_path = ROOT / "artifacts/patterns/pattern_a_fast/production/strategy_v02/pattern_a_fast_final_strategy_v02.json"
    production_path = ROOT / "artifacts/data/end_to_end_data_parity/v01/fastcore_parity/v01/fix01/production/production_fastcore_trades_20260814.csv"
    parity_path = ROOT / "artifacts/data/end_to_end_data_parity/v01/fastcore_parity/v01/fix01/parity/trade_level_parity.csv"
    authority = pd.read_csv(authority_path, dtype={"ticker": str})
    production = pd.read_csv(production_path, dtype={"ticker": str})
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    result = metrics_parity(authority, production, contract)
    assert result["authority_vs_production_mismatches"] == 0
    assert result["reentry_production"]["ge_100_count"] == 18
    assert result["reentry_frozen_expected"]["ge_100_count"] == 18
    assert result["reentry_cohort_metric_mismatches"] == 0
    assert result["aggregate_metric_mismatches"] == 0
    rows = trade_level_parity_rows(authority, production)
    persisted = pd.read_csv(parity_path, dtype={"ticker": str})
    assert len(rows) == 783
    assert len(persisted) == 783
    assert rows["overall_match"].all()
    assert persisted["overall_match"].all()
