"""Canonical golden-vs-optimized trade parity comparator (w.md Sections 7, 49, 52).

Root cause of a false-positive parity failure this module fixes: comparing
a CSV-loaded golden DataFrame against a raw in-memory DataFrame built
straight from dataclasses (``pd.DataFrame([asdict(t) for t in trades])``)
is NOT apples-to-apples. ``None`` reads back from CSV as ``NaN``, and some
floats' shortest ``repr`` differs pre- vs post- ``to_csv``/``read_csv``
round-trip (observed: ``1083419202799.9999`` on the raw side vs
``1083419202800.0`` after the golden side's CSV round-trip) purely from
serialization, not from any computation difference. calculate_strategy_metrics
outputs, loss-guard cohort counts, and the proxy-validation summary showed
zero diff on the same run that produced 2001/3779 false "field mismatches"
this way -- proof the underlying trade data was already correct.

The fix here is structural, not cosmetic: BOTH sides of every comparison in
this module MUST be loaded via ``pandas.read_csv`` from an actual on-disk
CSV file (never compared against an in-memory DataFrame). As long as the
optimized engine's trades are persisted to CSV before comparison (see
``scripts/run_backtest_engine_v01_optimized.py``), both sides go through the
identical serialization pathway and the representation mismatch class
described above cannot occur. A float-tolerance / NaN-aware fallback is
still applied per-field as a defensive second layer, and any genuine
semantic/numeric mismatch is always reported with full row context.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

# w.md Section 7 parity-comparison minimum field set.
PARITY_FIELDS = [
    "ticker", "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date",
    "entry_open", "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk",
    "fast_score", "fast_score_state", "investability_status", "investability_market_cap",
    "previous_exit_type", "loss_guard_triggered", "loss_guard_signal_date",
    "loss_guard_execution_date", "loss_guard_execution_price", "first_progressed_date",
    "lifecycle_class", "exit_type", "exit_signal_date", "exit_execution_date", "exit_price",
    "terminal_return", "mfe", "mae", "holding_weeks", "trade_status",
]

FLOAT_TOLERANCE = 1e-6


def _values_equal(a: Any, b: Any) -> bool:
    a_is_nan = isinstance(a, float) and math.isnan(a)
    b_is_nan = isinstance(b, float) and math.isnan(b)
    if a_is_nan and b_is_nan:
        return True
    if a_is_nan != b_is_nan:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= FLOAT_TOLERANCE
    return str(a) == str(b)


def compare_trade_csvs(golden_path: Path, optimized_path: Path, parity_fields: list[str] = PARITY_FIELDS) -> dict[str, Any]:
    """Compares two ON-DISK trade CSVs (never an in-memory DataFrame against
    a CSV) field-by-field on the w.md Section 7 minimum field set."""
    golden = pd.read_csv(golden_path, dtype={"ticker": str})
    optimized = pd.read_csv(optimized_path, dtype={"ticker": str})

    golden_sorted = golden.sort_values(["ticker", "trade_sequence"]).reset_index(drop=True)
    opt_sorted = optimized.sort_values(["ticker", "trade_sequence"]).reset_index(drop=True)

    if len(golden_sorted) != len(opt_sorted):
        return {
            "golden_trade_count": len(golden_sorted),
            "optimized_trade_count": len(opt_sorted),
            "exact_trade_identity": False,
            "field_mismatch_count": None,
            "count_mismatch": True,
            "mismatch_examples": [],
        }

    mismatch_count = 0
    mismatch_examples: list[dict[str, Any]] = []
    for field in parity_fields:
        if field not in golden_sorted.columns or field not in opt_sorted.columns:
            continue
        g_col, o_col = golden_sorted[field], opt_sorted[field]
        for idx in range(len(golden_sorted)):
            if not _values_equal(g_col.iloc[idx], o_col.iloc[idx]):
                mismatch_count += 1
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({
                        "field": field, "row": int(idx),
                        "ticker": str(golden_sorted.loc[idx, "ticker"]) if "ticker" in golden_sorted.columns else None,
                        "trade_id": str(golden_sorted.loc[idx, "trade_id"]) if "trade_id" in golden_sorted.columns else None,
                        "golden": str(g_col.iloc[idx]), "optimized": str(o_col.iloc[idx]),
                    })

    return {
        "golden_trade_count": len(golden_sorted),
        "optimized_trade_count": len(opt_sorted),
        "exact_trade_identity": mismatch_count == 0,
        "field_mismatch_count": mismatch_count,
        "count_mismatch": False,
        "mismatch_examples": mismatch_examples,
    }


def diff_summary_dicts(golden: dict, optimized: dict, path: str = "") -> list[dict[str, Any]]:
    """Field-level diff between two aggregate summary dicts (metrics, loss
    guard cohort, proxy validation) -- these are plain JSON/dict comparisons,
    never routed through CSV, so no representation-mismatch class applies
    here; this is float-tolerant recursive equality only."""
    diffs: list[dict[str, Any]] = []
    for k, gv in golden.items():
        ov = optimized.get(k, "<MISSING>")
        p = f"{path}.{k}" if path else k
        if isinstance(gv, dict) and isinstance(ov, dict):
            diffs.extend(diff_summary_dicts(gv, ov, p))
        elif not _values_equal(gv, ov):
            diffs.append({"field": p, "golden": gv, "optimized": ov})
    return diffs
