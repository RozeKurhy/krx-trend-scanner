#!/usr/bin/env python3
"""Pattern B State Rule V01 design: threshold candidates and rule-family comparison.

Report: docs/patterns/pattern_b/validation/state_rule_v01.md

Inputs are only the two sealed public V01 files (HGT labels, raw features),
joined on sample_id, and only the three KEEP features. Thresholds come from a
fixed recipe per adjacent label pair (IQR gap midpoint, or median midpoint when
the IQRs overlap), rounded to the nearest 0.05 declared before evaluation. No
cut search, sample override, or model fitting is done.
"""

from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

from trend_scanner.patterns import pattern_b_state_v01 as rule

ROOT = Path(__file__).resolve().parents[1]
_FIT = ROOT / "scripts/analyze_pattern_b_feature_fitness_v01.py"
_spec = importlib.util.spec_from_file_location("analyze_pattern_b_feature_fitness_v01", _FIT)
fit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fit
_spec.loader.exec_module(fit)

KEEP = ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION")
VALIDATION_DIR = ROOT / "docs/patterns/pattern_b/validation"
PREDICTIONS_PATH = VALIDATION_DIR / "state_rule_v01_predictions.csv"
REPORT_PATH = VALIDATION_DIR / "state_rule_v01.md"
SEAL_PATH = VALIDATION_DIR / "state_rule_v01_seal.json"
RULE_PATH = ROOT / "src/trend_scanner/patterns/pattern_b_state_v01.py"
SOURCE_BASE = "d620b5e2eab1a20013c1be6b1722c69a8a2c730d"
FINAL_FAMILY = "C"
STATES = fit.LABEL_ORDER
NORMAL = 2
ROUND_STEP = Decimal("0.05")


def round_step(value: float) -> float:
    return float((Decimal(str(value)) / ROUND_STEP).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * ROUND_STEP)


def threshold_table(df: pd.DataFrame, feature: str) -> list[dict]:
    summary = fit.label_summary(df, feature)
    rows = []
    for left, right in fit.ADJACENT_PAIRS:
        lq3, rq1 = summary.at[left, "q3"], summary.at[right, "q1"]
        lmed, rmed = summary.at[left, "median"], summary.at[right, "median"]
        gap = lq3 < rq1
        raw = (lq3 + rq1) / 2 if gap else (lmed + rmed) / 2
        rows.append({
            "boundary": f"{left}/{right}", "left_median": lmed, "right_median": rmed,
            "left_q3": lq3, "right_q1": rq1, "iqr": "gap" if gap else "overlap",
            "raw": raw, "basis": "IQR gap midpoint" if gap else "median midpoint",
            "threshold": round_step(raw),
        })
    return rows


def band(value: float, thresholds) -> int:
    """0..4: number of thresholds the value reaches (lower bound inclusive)."""
    return sum(value >= t for t in thresholds)


def family_a(m1: int, m2: int, w: int) -> int:
    """Monthly consensus + weekly tie-break."""
    if m1 == m2:
        return m1
    if abs(m1 - m2) == 1:
        return m1 if abs(w - m1) < abs(w - m2) else m2
    if (m1 - NORMAL) * (m2 - NORMAL) < 0:
        return NORMAL
    return m1 if abs(m1 - NORMAL) < abs(m2 - NORMAL) else m2


def family_b(m1: int, m2: int, w: int) -> int:
    """Monthly-only conservative intersection (weekly unused)."""
    if (m1 - NORMAL) * (m2 - NORMAL) < 0:
        return NORMAL
    return m1 if abs(m1 - NORMAL) < abs(m2 - NORMAL) else m2


def family_c(m1: int, m2: int, w: int) -> int:
    """36M primary; MA24 must confirm extremes; MA24 or 52W must confirm the side."""
    state = m1
    if state in (0, 4) and m2 != state:
        state += 1 if state == 0 else -1
    if state != NORMAL:
        side = -1 if state < NORMAL else 1
        if not any((x - NORMAL) * side > 0 for x in (m2, w)):
            state = NORMAL
    return state


FAMILIES = {"A": family_a, "B": family_b, "C": family_c}


def metrics(truth: pd.Series, pred: pd.Series) -> dict:
    err = (pred - truth).abs()
    return {
        "exact": float((err == 0).mean()),
        "within_1": float((err <= 1).mean()),
        "mae": float(err.mean()),
        "big_errors": int((err >= 2).sum()),
        "extreme_errors": int((err >= 3).sum()),
    }


def evaluate(df: pd.DataFrame, thresholds: dict) -> dict:
    bands = pd.DataFrame({f: df[f].map(lambda v, t=thresholds[f]: band(v, t)) for f in KEEP})
    out = {}
    high = df["confidence"] == "HIGH"
    for name, fn in FAMILIES.items():
        pred = pd.Series([fn(*row) for row in bands[list(KEEP)].itertuples(index=False)], index=df.index)
        out[name] = {
            "all": metrics(df["ordinal"], pred),
            "high": metrics(df.loc[high, "ordinal"], pred[high]),
            "pred": pred,
        }
    return out


def confusion(truth: pd.Series, pred: pd.Series) -> pd.DataFrame:
    table = pd.crosstab(truth, pred).reindex(index=range(5), columns=range(5), fill_value=0)
    table.index = [f"HGT {STATES[i]}" for i in table.index]
    table.columns = list(STATES)
    return table


def load() -> pd.DataFrame:
    hgt = pd.read_csv(fit.DEFAULT_HGT, dtype=str, keep_default_na=False)
    raw = pd.read_csv(fit.DEFAULT_RAW, dtype={"sample_id": str})
    return fit.load_joined(hgt, raw)


def recipe_thresholds(df: pd.DataFrame) -> dict[str, tuple[float, ...]]:
    return {f: tuple(r["threshold"] for r in threshold_table(df, f)) for f in KEEP}


def predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Sealed-rule predictions for the 36 V01 samples (sample_id only, no identity)."""
    pred = [rule.classify_pattern_b_state_v01(*row) for row in df[list(KEEP)].itertuples(index=False)]
    out = pd.DataFrame({"sample_id": df["sample_id"], "hgt_label": df["label"], "predicted_state": pred})
    out["ordinal_error"] = out["predicted_state"].map(fit.ORDINAL) - out["hgt_label"].map(fit.ORDINAL)
    out["exact_match"] = out["ordinal_error"] == 0
    return out


def sealed_metrics(df: pd.DataFrame, pred: pd.DataFrame) -> dict:
    ordinal = pred["predicted_state"].map(fit.ORDINAL)
    high = df["confidence"] == "HIGH"
    m_all = metrics(df["ordinal"], ordinal)
    m_high = metrics(df.loc[high, "ordinal"], ordinal[high])
    return {
        "exact_accuracy": round(m_all["exact"], 4),
        "within_1_accuracy": round(m_all["within_1"], 4),
        "ordinal_mae": round(m_all["mae"], 4),
        "errors_ge_2": m_all["big_errors"],
        "errors_ge_3": m_all["extreme_errors"],
        "high_exact_accuracy": round(m_high["exact"], 4),
        "high_ordinal_mae": round(m_high["mae"], 4),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_rule_matches_design(df: pd.DataFrame) -> None:
    if recipe_thresholds(df) != {f: rule.THRESHOLDS[f] for f in KEEP}:
        raise SystemExit("CHECK_REQUIRED: sealed thresholds differ from the design recipe")
    grid = [(a, b, c) for a in range(5) for b in range(5) for c in range(5)]
    if any(rule.combine_bands(*g) != FAMILIES[FINAL_FAMILY](*g) for g in grid):
        raise SystemExit("CHECK_REQUIRED: sealed rule differs from the design family")


def write_predictions(df: pd.DataFrame) -> None:
    check_rule_matches_design(df)
    predictions(df).to_csv(PREDICTIONS_PATH, index=False, lineterminator="\n")


def write_seal(df: pd.DataFrame) -> dict:
    check_rule_matches_design(df)
    pred = predictions(df)
    on_disk = pd.read_csv(PREDICTIONS_PATH, dtype={"sample_id": str})
    if not on_disk.astype(str).equals(pred.astype(str)):
        raise SystemExit("CHECK_REQUIRED: predictions CSV differs from the sealed rule")
    seal = {
        "version": "PATTERN_B_STATE_RULE_V01",
        "source_base": SOURCE_BASE,
        "rule_family": FINAL_FAMILY,
        "feature_names": list(KEEP),
        "thresholds": {f: list(rule.THRESHOLDS[f]) for f in KEEP},
        "threshold_semantics": "band = count of thresholds with value >= threshold (lower bound inclusive)",
        "hgt_sample_count": len(df),
        **sealed_metrics(df, pred),
        "rule_file_sha256": _sha256(RULE_PATH),
        "report_sha256": _sha256(REPORT_PATH),
        "predictions_sha256": _sha256(PREDICTIONS_PATH),
    }
    SEAL_PATH.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    return seal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-predictions", action="store_true")
    parser.add_argument("--write-seal", action="store_true")
    args = parser.parse_args()
    df = load()
    if args.write_predictions:
        write_predictions(df)
    if args.write_seal:
        print(json.dumps(write_seal(df), indent=2))
        return
    tables = {f: threshold_table(df, f) for f in KEEP}
    thresholds = {f: tuple(r["threshold"] for r in tables[f]) for f in KEEP}
    results = evaluate(df, thresholds)
    print(json.dumps({"thresholds": thresholds}, indent=2))
    for f in KEEP:
        for r in tables[f]:
            print(f"{f} {r['boundary']}: {r['iqr']} raw={r['raw']:.4f} -> {r['threshold']}")
    for name, r in results.items():
        print(name, "all", r["all"], "high", r["high"])
    for name, r in results.items():
        print(f"\n{name}\n", confusion(df["ordinal"], r["pred"]).to_string())


if __name__ == "__main__":
    main()
