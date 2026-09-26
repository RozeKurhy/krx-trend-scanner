#!/usr/bin/env python3
"""Pattern B robust current-position feature research V01 (research only).

Record: docs/patterns/pattern_b/validation/robust_current_position_feature_research_v01.md

Compares the baseline range positions with two fixed candidates on the same
completed bars (36 monthly / 52 weekly):
- A: close percentile position = mid-rank of the current close among the other
  closes in the window (Feature Contract V01 ``mid_rank_percentile`` / 100).
- B: robust close range position = (close - q10) / (q90 - q10) over window closes,
  clipped to [0, 1]; q10/q90 fixed (numpy linear interpolation).
No official feature, threshold, or state rule is changed. The V02 comparison is
label-free; V01 labels are used only for a reference median/ordering check.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import numpy as np
import pandas as pd

from trend_scanner.patterns import pattern_b_features_v01 as pb
from trend_scanner.patterns import pattern_b_state_v01 as rule

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "docs/patterns/pattern_b/validation"
OUT_JSON = V / "robust_current_position_feature_research_v01.json"
WINDOWS = {"36M": ("monthly", 36), "52W": ("weekly", 52)}
METHODS = ("baseline", "percentile", "robust_range")
LOW, HIGH = 0.25, 0.75  # fixed a priori for label-free side counts
V01_MANIFEST_SHA256 = "5e8d1dabcf07b816b710d7da2ae69ef602f3b4d3c979d73f6b7ffecee2b84f54"
NOT_APPLICABLE = None


# --- candidate formulas --------------------------------------------------------

def baseline_range_position(bars: pd.DataFrame, n: int) -> float | None:
    if len(bars) < n:
        return NOT_APPLICABLE
    w = bars.iloc[-n:]
    low, high = float(w["low"].min()), float(w["high"].max())
    return NOT_APPLICABLE if high == low else (float(w["close"].iloc[-1]) - low) / (high - low)


def close_percentile_position(bars: pd.DataFrame, n: int) -> float | None:
    if len(bars) < n:
        return NOT_APPLICABLE
    closes = bars["close"].to_numpy(dtype=float)[-n:]
    return pb.mid_rank_percentile(closes[:-1], closes[-1]) / 100.0


def robust_close_range_position(bars: pd.DataFrame, n: int) -> float | None:
    if len(bars) < n:
        return NOT_APPLICABLE
    closes = bars["close"].to_numpy(dtype=float)[-n:]
    q10, q90 = np.percentile(closes, [10, 90])
    if q90 == q10:
        return NOT_APPLICABLE
    return float(np.clip((closes[-1] - q10) / (q90 - q10), 0.0, 1.0))


FORMULAS = {
    "baseline": baseline_range_position,
    "percentile": close_percentile_position,
    "robust_range": robust_close_range_position,
}


def position_features(daily: pd.DataFrame, as_of: str) -> dict:
    """Six positions from completed bars (daily truncated at as_of first)."""
    as_of_ts = pd.Timestamp(as_of)
    frame = daily.loc[daily.index <= as_of_ts, ["high", "low", "close"]]
    bars = {
        "monthly": pb.completed_bars(frame, pd.offsets.MonthEnd(), as_of_ts),
        "weekly": pb.completed_bars(frame, "W-FRI", as_of_ts),
    }
    return {
        method: {w: FORMULAS[method](bars[kind], n) for w, (kind, n) in WINDOWS.items()}
        for method in METHODS
    }


# --- synthetic spike sensitivity ----------------------------------------------

def _synthetic_bars(spike: str | None) -> pd.DataFrame:
    rng = np.random.default_rng(20)
    n = 60
    close = 100 + rng.normal(0, 4, n)
    close[-1] = 112.0  # current close in the upper part of the normal range
    high, low = close * 1.02, close * 0.98
    if spike == "high_only":
        high[-10] = close[-10] * 3.2
    elif spike == "close":
        close[-10] = 320.0
        high[-10], low[-10] = 330.0, 310.0
    return pd.DataFrame({"high": high, "low": low, "close": close},
                        index=pd.date_range("2015-01-31", periods=n, freq="ME"))


def synthetic_sensitivity() -> dict:
    base = _synthetic_bars(None)
    out = {}
    for scenario in ("high_only", "close"):
        spiked = _synthetic_bars(scenario)
        out[scenario] = {
            m: {
                "before": round(FORMULAS[m](base, 36), 4),
                "after": round(FORMULAS[m](spiked, 36), 4),
                "delta": round(FORMULAS[m](spiked, 36) - FORMULAS[m](base, 36), 4),
            }
            for m in METHODS
        }
    return out


# --- label-free comparison on V02 -------------------------------------------------

def _side(x: float | None) -> str | None:
    if x is None:
        return None
    return "low" if x < LOW else "high" if x > HIGH else "mid"


def _ma24_side(ma24: float) -> str:
    band = rule.feature_band(rule.MA24_DISTANCE, ma24)
    return "low" if band < rule.NORMAL else "high" if band > rule.NORMAL else "mid"


def label_free_comparison(positions: dict[str, dict], ma24: dict[str, float]) -> dict:
    """Uses only feature values (no human or post-hoc labels)."""
    out = {}
    conflicts: dict[str, set[str]] = {}
    for m in METHODS:
        vals = {w: [positions[s][m][w] for s in positions] for w in WINDOWS}
        agree = sum(_side(positions[s][m]["36M"]) == _side(positions[s][m]["52W"]) for s in positions)
        conf = sorted(
            s for s in positions
            if any({_side(positions[s][m][w]), _ma24_side(ma24[s])} == {"low", "high"} for w in WINDOWS)
        )
        conflicts[m] = set(conf)
        out[m] = {
            **{f"{w}_summary": {
                "min": round(min(vals[w]), 4), "median": round(float(np.median(vals[w])), 4),
                "max": round(max(vals[w]), 4),
                "le_0_10": sum(v <= 0.10 for v in vals[w]), "ge_0_90": sum(v >= 0.90 for v in vals[w]),
            } for w in WINDOWS},
            "side_agreement_36m_52w": agree,
            "strong_opposite_to_ma24": conf,
        }
    for m in ("percentile", "robust_range"):
        out[m]["resolved_vs_baseline"] = sorted(conflicts["baseline"] - conflicts[m])
        out[m]["new_vs_baseline"] = sorted(conflicts[m] - conflicts["baseline"])
    return out


# --- V01 reference ----------------------------------------------------------------

def v01_reference(positions: dict[str, dict], labels: dict[str, str], fit) -> dict:
    out = {}
    ordinal = pd.Series({s: fit.ORDINAL[labels[s]] for s in positions})
    for m in METHODS:
        for w in WINDOWS:
            series = pd.Series({s: positions[s][m][w] for s in positions})
            medians = {lbl: round(float(series[[s for s in series.index if labels[s] == lbl]].median()), 4)
                       for lbl in fit.LABEL_ORDER}
            ordered = [medians[b] > medians[a] for a, b in fit.ADJACENT_PAIRS]
            out[f"{m}_{w}"] = {
                "label_medians": medians,
                "adjacent_median_increases": sum(ordered),
                "spearman": round(fit.spearman(series[ordinal.index], ordinal), 4),
            }
    return out


# --- data -------------------------------------------------------------------------

def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _plain(value):
    """numpy scalars -> Python scalars for JSON."""
    return value.item()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT)
    args = parser.parse_args()
    from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
    from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2

    raw02 = _load("compute_pattern_b_holdout_feature_raw_v02", "scripts/compute_pattern_b_holdout_feature_raw_v02.py")
    fit = _load("analyze_pattern_b_feature_fitness_v01", "scripts/analyze_pattern_b_feature_fitness_v01.py")
    repository = build_repository_v2(args.data_root, end="2026-06-30")

    # V02: identity-segment load, as in the sealed V02 raw values.
    holdout_seal = json.loads((V / "holdout_v02_seal.json").read_text(encoding="utf-8"))
    v02_manifest = raw02.load_manifest(raw02.DEFAULT_MANIFEST, holdout_seal)
    authority = load_effective_authority(ROOT / raw02.hold.AUTHORITY_DIR)
    sealed02 = {r["sample_id"]: r for r in _read(V / "feature_raw_values_v02.csv")}
    v02 = {}
    for m in v02_manifest:
        seg = [s for s in raw02.hold.common_segments_at(authority.pit_intervals, pd.Timestamp(m["as_of"]))
               if s.ticker == m["ticker"]][0]
        daily = RepositoryV2DailyLoader(repository, start=seg.effective_from.date().isoformat(),
                                        end=m["as_of"]).load(m["ticker"])
        v02[m["sample_id"]] = position_features(daily, m["as_of"])
        for w, feat in (("36M", "36M_RANGE_POSITION"), ("52W", "52W_RANGE_POSITION")):
            if v02[m["sample_id"]]["baseline"][w] != float(sealed02[m["sample_id"]][feat]):
                raise SystemExit(f"CHECK_REQUIRED: {m['sample_id']} baseline differs from sealed V02")

    # V01: 1900 start, as in the sealed V01 raw values.
    v01_manifest_path = ROOT / "artifacts/pattern_b_hgt_v01/private/private_manifest.csv"
    if hashlib.sha256(v01_manifest_path.read_bytes()).hexdigest() != V01_MANIFEST_SHA256:
        raise SystemExit("CHECK_REQUIRED: V01 private manifest differs from its recorded hash")
    with v01_manifest_path.open(encoding="utf-8-sig") as fh:
        v01_manifest = list(csv.DictReader(fh))
    sealed01 = {r["sample_id"]: r for r in _read(V / "feature_raw_values_v01.csv")}
    v01 = {}
    for m in v01_manifest:
        daily = RepositoryV2DailyLoader(repository, start="1900-01-01", end=m["as_of"]).load(m["ticker"])
        v01[m["sample_id"]] = position_features(daily, m["as_of"])
        if v01[m["sample_id"]]["baseline"]["36M"] != float(sealed01[m["sample_id"]]["36M_RANGE_POSITION"]):
            raise SystemExit(f"CHECK_REQUIRED: {m['sample_id']} baseline differs from sealed V01")
    v01_labels = {r["sample_id"]: r["label"] for r in _read(V / "human_ground_truth_labels_v01.csv")}

    ma24_02 = {s: float(r["MONTHLY_MA24_DISTANCE"]) for s, r in sealed02.items()}
    result = {
        "candidates_fixed": {"percentile": "mid-rank vs other window closes",
                             "robust_range": "q10/q90 of window closes, clipped 0~1"},
        "side_cuts_fixed": {"low_lt": LOW, "high_gt": HIGH, "ma24": "State Rule V01 MA24 bands"},
        "pbhold_028": v02["PBHOLD_028"],
        "synthetic": synthetic_sensitivity(),
        "v02_label_free": label_free_comparison(v02, ma24_02),
        "v01_reference": v01_reference(v01, v01_labels, fit),
        "v02_positions": {s: v02[s] for s in sorted(v02)},
        "v01_positions": {s: v01[s] for s in sorted(v01)},
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, default=_plain) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("pbhold_028", "synthetic", "v02_label_free", "v01_reference")}
    print(json.dumps(summary, indent=2, default=_plain))


if __name__ == "__main__":
    main()
