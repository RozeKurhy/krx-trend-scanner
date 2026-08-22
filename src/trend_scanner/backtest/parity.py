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
identical serialization pathway.

Phase 4 Major Fix 2 (w.md Section 3) strengthened this module further:

  - A required ``PARITY_FIELDS`` field missing from either side's columns is
    NEVER silently skipped: it is reported under ``missing_required_fields``
    and forces ``exact_trade_identity = False``.
  - Row identity is now a merge on ``["ticker", "trade_sequence"]`` (rather
    than independent per-side sort + positional alignment), so a row present
    on only one side is caught explicitly instead of being silently compared
    against whatever happened to land at the same sorted position -- this
    also makes a pure row-ORDER difference a non-issue (merge is
    order-independent), while a genuine identity difference at the same key
    (e.g. same ticker+trade_sequence, different trade_id) still surfaces as
    a ``trade_id`` field mismatch, since ``trade_id`` is itself a required
    parity field.
  - The Golden Exact Parity Gate (``exact_trade_identity``) is now based on
    strict canonical equality (NaN-aware, otherwise exact value equality --
    see ``_canonical_equal``), NOT the ``FLOAT_TOLERANCE`` used previously.
    Because both sides are already forced through the identical
    ``to_csv``/``read_csv`` pathway, two independently-computed-but-correct
    runs produce bit-identical floats here; a blanket tolerance would risk
    silently passing a genuine (if small) numeric regression. Any field that
    is ever proven to need tolerance under this gate must be added to
    ``FIELD_TOLERANCE_OVERRIDES`` with an inline comment stating why --
    never covered by an undocumented blanket value.
  - The previous ``FLOAT_TOLERANCE = 1e-6`` behavior is retained ONLY as a
    separate, clearly-labeled diagnostic
    (``near_equal_diagnostic_mismatch_count``) that must never be used to
    decide ``exact_trade_identity``.
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

# Canonical row-identity key for merge-based alignment (w.md Section 3D).
ROW_KEY = ["ticker", "trade_sequence"]

# Diagnostic-only tolerance (never used for the Exact Parity Gate).
FLOAT_TOLERANCE = 1e-6

# Per-field exact-gate tolerance overrides. Deliberately empty: the Exact
# Parity Gate defaults to true canonical equality for every field. Add an
# entry ONLY when a specific field is proven to need it (e.g. a documented
# pandas CSV parser round-trip quirk for that field specifically), with an
# inline comment explaining why -- never a blanket tolerance.
FIELD_TOLERANCE_OVERRIDES: dict[str, float] = {}


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _values_equal(a: Any, b: Any) -> bool:
    """Diagnostic-only near-equality (FLOAT_TOLERANCE). NOT the Exact Gate."""
    a_is_nan, b_is_nan = _is_nan(a), _is_nan(b)
    if a_is_nan and b_is_nan:
        return True
    if a_is_nan != b_is_nan:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= FLOAT_TOLERANCE
    return str(a) == str(b)


def _canonical_equal(a: Any, b: Any, field: str | None = None) -> bool:
    """Golden Exact Parity Gate equality: NaN-aware, otherwise exact value
    equality (optionally relaxed per-field via FIELD_TOLERANCE_OVERRIDES,
    which is empty by default -- see module docstring)."""
    a_is_nan, b_is_nan = _is_nan(a), _is_nan(b)
    if a_is_nan or b_is_nan:
        return a_is_nan and b_is_nan
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        tol = FIELD_TOLERANCE_OVERRIDES.get(field, 0.0)
        return abs(float(a) - float(b)) <= tol
    return a == b


def compare_trade_csvs(golden_path: Path, optimized_path: Path, parity_fields: list[str] = PARITY_FIELDS) -> dict[str, Any]:
    """Compares two ON-DISK trade CSVs (never an in-memory DataFrame against
    a CSV) field-by-field on the w.md Section 7 minimum field set."""
    golden = pd.read_csv(golden_path, dtype={"ticker": str})
    optimized = pd.read_csv(optimized_path, dtype={"ticker": str})

    missing_golden = [f for f in parity_fields if f not in golden.columns]
    missing_optimized = [f for f in parity_fields if f not in optimized.columns]
    if missing_golden or missing_optimized:
        return {
            "golden_trade_count": len(golden),
            "optimized_trade_count": len(optimized),
            "exact_trade_identity": False,
            "field_mismatch_count": None,
            "count_mismatch": False,
            "missing_required_fields": {"golden": missing_golden, "optimized": missing_optimized},
            "unmatched_trade_identity_count": {"golden_only": None, "optimized_only": None},
            "mismatch_examples": [],
            "near_equal_diagnostic_mismatch_count": None,
        }

    if len(golden) != len(optimized):
        return {
            "golden_trade_count": len(golden),
            "optimized_trade_count": len(optimized),
            "exact_trade_identity": False,
            "field_mismatch_count": None,
            "count_mismatch": True,
            "missing_required_fields": {"golden": [], "optimized": []},
            "unmatched_trade_identity_count": {"golden_only": None, "optimized_only": None},
            "mismatch_examples": [],
            "near_equal_diagnostic_mismatch_count": None,
        }

    merged = golden.merge(optimized, on=ROW_KEY, how="outer", suffixes=("_golden", "_optimized"), indicator=True)
    unmatched_golden_only = int((merged["_merge"] == "left_only").sum())
    unmatched_optimized_only = int((merged["_merge"] == "right_only").sum())

    matched = merged[merged["_merge"] == "both"].reset_index(drop=True)
    compare_fields = [f for f in parity_fields if f not in ROW_KEY]

    mismatch_count = 0
    near_equal_diagnostic_mismatch_count = 0
    mismatch_examples: list[dict[str, Any]] = []
    for field in compare_fields:
        g_col, o_col = matched[f"{field}_golden"], matched[f"{field}_optimized"]
        for idx in range(len(matched)):
            gv, ov = g_col.iloc[idx], o_col.iloc[idx]
            if not _canonical_equal(gv, ov, field):
                mismatch_count += 1
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({
                        "field": field, "row": int(idx),
                        "ticker": str(matched.loc[idx, "ticker"]),
                        "trade_sequence": matched.loc[idx, "trade_sequence"],
                        "golden": str(gv), "optimized": str(ov),
                    })
            if not _values_equal(gv, ov):
                near_equal_diagnostic_mismatch_count += 1

    exact_trade_identity = (
        mismatch_count == 0 and unmatched_golden_only == 0 and unmatched_optimized_only == 0
    )

    return {
        "golden_trade_count": len(golden),
        "optimized_trade_count": len(optimized),
        "exact_trade_identity": exact_trade_identity,
        "field_mismatch_count": mismatch_count,
        "count_mismatch": False,
        "missing_required_fields": {"golden": [], "optimized": []},
        "unmatched_trade_identity_count": {"golden_only": unmatched_golden_only, "optimized_only": unmatched_optimized_only},
        "mismatch_examples": mismatch_examples,
        "near_equal_diagnostic_mismatch_count": near_equal_diagnostic_mismatch_count,
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
