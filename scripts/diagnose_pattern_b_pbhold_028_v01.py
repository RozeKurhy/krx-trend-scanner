#!/usr/bin/env python3
"""Read-only structure diagnostic for PBHOLD_028 (Pattern B, Holdout V02).

Record: docs/patterns/pattern_b/validation/pbhold_028_structure_diagnostic_v01.md

- Family C is examined only by calling the sealed ``feature_band`` and
  ``combine_bands`` (including probe calls with other band inputs); no rule logic
  is copied and nothing is changed.
- The seven V01 features and the spike facts need price history, so they use the
  sealed Holdout private manifest and the same identity-segment load as the V02
  raw-value runner. Public output holds ratios to the current close and bar
  offsets only: no ticker, name, as_of, or absolute price.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pandas as pd

from trend_scanner.patterns import pattern_b_features_v01 as pb
from trend_scanner.patterns import pattern_b_state_v01 as rule

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "docs/patterns/pattern_b/validation"
OUT_JSON = V / "pbhold_028_structure_diagnostic_v01.json"
TARGET = "PBHOLD_028"
KEEP = rule.FEATURES
ALL_FEATURES = pb.FEATURE_NAMES


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def family_c_decomposition(values: dict[str, float]) -> dict:
    """Bands and probe calls of the sealed Family C for one sample."""
    bands = {f: rule.feature_band(f, values[f]) for f in KEEP}
    m36, ma24, w52 = (bands[f] for f in KEEP)
    final = rule.combine_bands(m36, ma24, w52)
    return {
        "bands": bands,
        "band_states": {f: rule.STATES[b] for f, b in bands.items()},
        "primary_state": rule.STATES[m36],
        "primary_is_extreme": m36 in (0, 4),
        "final_state": rule.STATES[final],
        "classifier_state": rule.classify_pattern_b_state_v01(*(values[f] for f in KEEP)),
        "probe_52w_neutral": rule.STATES[rule.combine_bands(m36, ma24, rule.NORMAL)],
        "probe_ma24_sweep_given_52w": [rule.STATES[rule.combine_bands(m36, x, w52)] for x in range(5)],
        "reachable_states_given_primary": sorted(
            {rule.STATES[rule.combine_bands(m36, x, w)] for x in range(5) for w in range(5)},
            key=rule.STATES.index,
        ),
    }


def _nearest_v01_median(fit, v01: pd.DataFrame, feature: str, value: float) -> str:
    summary = fit.label_summary(v01, feature)
    return min(fit.LABEL_ORDER, key=lambda lbl: abs(summary.at[lbl, "median"] - value))


def seven_feature_view(daily: pd.DataFrame, as_of: str, fit, v01: pd.DataFrame) -> dict:
    result = pb.compute_pattern_b_features_v01(daily, as_of)
    out = {}
    for name in ALL_FEATURES:
        fv = result.features[name]
        out[name] = {
            "value": fv.value,
            "status": fv.status,
            "nearest_v01_label_median": _nearest_v01_median(fit, v01, name, fv.value) if fv.value is not None else None,
        }
    return out


def spike_view(daily: pd.DataFrame, as_of: str) -> dict:
    """Range geometry as ratios to the current close (no absolute prices)."""
    as_of_ts = pd.Timestamp(as_of)
    frame = daily.loc[daily.index <= as_of_ts, ["high", "low", "close"]]
    monthly = pb.completed_bars(frame, pd.offsets.MonthEnd(), as_of_ts)
    weekly = pb.completed_bars(frame, "W-FRI", as_of_ts)
    close = float(monthly["close"].iloc[-1])
    m36, m84, w52 = monthly.iloc[-36:], monthly.iloc[-84:], weekly.iloc[-52:]
    ma24 = float(monthly["close"].iloc[-24:].mean())
    h36_pos = int(m36["high"].to_numpy().argmax())
    h52_pos = int(w52["high"].to_numpy().argmax())
    return {
        "monthly_36": {
            "low_to_close": round(float(m36["low"].min()) / close, 4),
            "high_to_close": round(float(m36["high"].max()) / close, 4),
            "median_close_to_close": round(statistics.median(m36["close"]) / close, 4),
            "months_since_high": len(m36) - 1 - h36_pos,
        },
        "monthly_84_median_close_to_close": round(statistics.median(m84["close"]) / close, 4),
        "weekly_52": {
            "low_to_close": round(float(w52["low"].min()) / close, 4),
            "high_to_close": round(float(w52["high"].max()) / close, 4),
            "weeks_since_high": len(w52) - 1 - h52_pos,
        },
        "ma24_to_close": round(ma24 / close, 4),
    }


def posthoc_comparison(features: dict[str, dict], posthoc: list[dict]) -> list[dict]:
    rows = []
    for r in posthoc:
        values = {f: float(features[r["sample_id"]][f]) for f in KEEP}
        bands = {f: rule.feature_band(f, values[f]) for f in KEEP}
        rows.append({
            "sample_id": r["sample_id"],
            "values": {f: round(v, 4) for f, v in values.items()},
            "bands": bands,
            "automatic_label": r["automatic_label"],
            "posthoc_label": r["posthoc_label"],
            "range_low_ma24_high_posthoc_high": (
                bands[KEEP[0]] < rule.NORMAL and bands[KEEP[2]] < rule.NORMAL
                and bands[KEEP[1]] > rule.NORMAL and rule.STATES.index(r["posthoc_label"]) > rule.NORMAL
            ),
        })
    return rows


def conflict_counts(features: dict[str, dict]) -> dict:
    """Label-free counts over all 36 V02 samples of range-vs-MA24 opposite-side patterns."""
    low_high = high_low = 0
    for row in features.values():
        b = {f: rule.feature_band(f, float(row[f])) for f in KEEP}
        ranges = (b[KEEP[0]], b[KEEP[2]])
        if all(x < rule.NORMAL for x in ranges) and b[KEEP[1]] > rule.NORMAL:
            low_high += 1
        if all(x > rule.NORMAL for x in ranges) and b[KEEP[1]] < rule.NORMAL:
            high_low += 1
    return {"ranges_depressed_ma24_overheated": low_high, "ranges_overheated_ma24_depressed": high_low}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT)
    args = parser.parse_args()

    raw = _load_module("compute_pattern_b_holdout_feature_raw_v02", "scripts/compute_pattern_b_holdout_feature_raw_v02.py")
    fit = _load_module("analyze_pattern_b_feature_fitness_v01", "scripts/analyze_pattern_b_feature_fitness_v01.py")
    from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
    from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2

    features = {r["sample_id"]: r for r in _read(V / "feature_raw_values_v02.csv")}
    posthoc = _read(V / "holdout_v02_posthoc_adjudication_v01.csv")
    target_values = {f: float(features[TARGET][f]) for f in KEEP}

    holdout_seal = json.loads((V / "holdout_v02_seal.json").read_text(encoding="utf-8"))
    manifest = {m["sample_id"]: m for m in raw.load_manifest(raw.DEFAULT_MANIFEST, holdout_seal)}
    sample = manifest[TARGET]
    authority = load_effective_authority(ROOT / raw.hold.AUTHORITY_DIR)
    segment = [s for s in raw.hold.common_segments_at(authority.pit_intervals, pd.Timestamp(sample["as_of"]))
               if s.ticker == sample["ticker"]][0]
    daily = RepositoryV2DailyLoader(
        build_repository_v2(args.data_root, end=sample["as_of"]),
        start=segment.effective_from.date().isoformat(), end=sample["as_of"],
    ).load(sample["ticker"])
    keep_check, _ = raw.keep_values(daily, sample["as_of"])
    if {f: float(v) for f, v in keep_check.items()} != target_values:
        raise SystemExit("CHECK_REQUIRED: recomputed KEEP values differ from sealed feature V02")

    hgt = _read(fit.DEFAULT_HGT)
    v01 = fit.load_joined(pd.DataFrame(hgt), pd.read_csv(fit.DEFAULT_RAW, dtype={"sample_id": str}))
    result = {
        "sample_id": TARGET,
        "keep_values": target_values,
        "family_c": family_c_decomposition(target_values),
        "seven_features": seven_feature_view(daily, sample["as_of"], fit, v01),
        "seven_features_history_start": "PIT COMMON identity segment start (same as feature V02)",
        "spike": spike_view(daily, sample["as_of"]),
        "posthoc_comparison": posthoc_comparison(features, posthoc),
        "v02_label_free_conflict_counts": conflict_counts(features),
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
