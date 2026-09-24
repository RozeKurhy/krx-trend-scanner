#!/usr/bin/env python3
"""Pattern B development V02 feature evaluation V01 (development set, not a holdout).

Record: docs/patterns/pattern_b/validation/development_v02_feature_evaluation_v01.md

- Seals checked first: sealed development human labels, development private
  manifest, Criteria V02.
- Features: Feature Contract V01 (baseline KEEP 3) and the fixed candidate
  formulas from robust current-position research V01 (A: close percentile,
  B: q10/q90 robust range), all on the same identity-segment, as_of-truncated
  completed bars as the development chart pack.
- State Rule V01 is applied as sealed. No threshold, quantile, or weight search.
- Error-type flags use fixed rules defined below, not per-sample judgment.
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
LABELS = V / "development_v02_human_labels.csv"
LABEL_SEAL = V / "development_v02_human_labels_seal.json"
PACK_SEAL = V / "development_v02_seal.json"
CRITERIA = V / "human_ground_truth_criteria_v02.md"
RAW_CSV = V / "development_v02_feature_raw_values_v01.csv"
OUT_JSON = V / "development_v02_feature_evaluation_v01.json"
SAMPLE_IDS = [f"PBDEV2_{i:03d}" for i in range(1, 37)]
STATES = rule.STATES
ORD = {s: i for i, s in enumerate(STATES)}  # DEEP_DEPRESSED=0 ... EXTREME_OVERHEATED=4
FEATURE_COLUMNS = (
    "36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION",
    "36M_CLOSE_PERCENTILE_POSITION", "52W_CLOSE_PERCENTILE_POSITION",
    "36M_ROBUST_CLOSE_RANGE_POSITION", "52W_ROBUST_CLOSE_RANGE_POSITION",
)
KEEP = rule.FEATURES
SATURATION = (0.05, 0.95)  # fixed: share of values at the ends


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def verify_seals(dev) -> None:
    labels = json.loads(LABEL_SEAL.read_text(encoding="utf-8"))
    pack = json.loads(PACK_SEAL.read_text(encoding="utf-8"))
    checks = {
        "labels": labels["labels_file_sha256"] == sha256(LABELS),
        "pack seal": labels["development_pack_seal_sha256"] == sha256(PACK_SEAL),
        "manifest": pack["private_manifest_sha256"] == sha256(dev.MANIFEST),
        "criteria": labels["criteria_file_sha256"] == sha256(CRITERIA) == pack["criteria_file_sha256"],
    }
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        raise SystemExit(f"CHECK_REQUIRED: seal mismatch {failed}")


def feature_row(daily: pd.DataFrame, as_of: str, rs) -> dict:
    official = pb.compute_pattern_b_features_v01(daily, as_of)
    for name in KEEP:
        if official.features[name].status != pb.STATUS_OK:
            raise SystemExit(f"CHECK_REQUIRED: {name} {official.features[name].status}")
    pos = rs.position_features(daily, as_of)
    row = {name: official.features[name].value for name in KEEP}
    if (pos["baseline"]["36M"], pos["baseline"]["52W"]) != (row["36M_RANGE_POSITION"], row["52W_RANGE_POSITION"]):
        raise SystemExit("CHECK_REQUIRED: research baseline differs from Feature Contract V01")
    row.update({
        "36M_CLOSE_PERCENTILE_POSITION": pos["percentile"]["36M"],
        "52W_CLOSE_PERCENTILE_POSITION": pos["percentile"]["52W"],
        "36M_ROBUST_CLOSE_RANGE_POSITION": pos["robust_range"]["36M"],
        "52W_ROBUST_CLOSE_RANGE_POSITION": pos["robust_range"]["52W"],
    })
    return {k: float(v) for k, v in row.items()}  # plain floats for a clean CSV repr


def rule_metrics(pred: dict[str, str], labels: dict[str, dict]) -> dict:
    ids = SAMPLE_IDS
    err = {s: ORD[pred[s]] - ORD[labels[s]["label"]] for s in ids}

    def block(sub: list[str]) -> dict:
        a = [abs(err[s]) for s in sub]
        n = len(sub)
        return {
            "n": n,
            "exact": sum(e == 0 for e in a), "within_1": sum(e <= 1 for e in a),
            "mae": round(sum(a) / n, 4) if n else None,
            "error_ge_2": sum(e >= 2 for e in a), "error_ge_3": sum(e >= 3 for e in a),
        }

    per_state = {st: block([s for s in ids if labels[s]["label"] == st]) for st in STATES}
    return {
        "all": block(ids),
        "high": block([s for s in ids if labels[s]["confidence"] == "HIGH"]),
        "extreme": block([s for s in ids if labels[s]["label"] in ("DEEP_DEPRESSED", "EXTREME_OVERHEATED")]),
        "per_state": per_state,
        "confusion": {h: {a: sum(labels[s]["label"] == h and pred[s] == a for s in ids) for a in STATES}
                      for h in STATES},
        "signed_error_counts": {str(k): sum(err[s] == k for s in ids) for k in range(-4, 5)},
        "mean_signed_error": round(sum(err.values()) / len(ids), 4),
    }


def feature_diagnostics(features: dict[str, dict], labels: dict[str, dict], fit) -> dict:
    df = pd.DataFrame([{**features[s], "label": labels[s]["label"], "ordinal": ORD[labels[s]["label"]]}
                       for s in SAMPLE_IDS])
    out = {}
    for name in FEATURE_COLUMNS:
        summary = fit.label_summary(df, name)
        medians = {st: (None if pd.isna(summary.at[st, "median"]) else round(float(summary.at[st, "median"]), 4))
                   for st in STATES}
        iqr = {st: (None if pd.isna(summary.at[st, "q1"]) else
                    [round(float(summary.at[st, "q1"]), 4), round(float(summary.at[st, "q3"]), 4)]) for st in STATES}
        pairs = [(a, b) for a, b in zip(STATES[:-1], STATES[1:])]
        out[name] = {
            "spearman": round(fit.spearman(df[name], df["ordinal"]), 4),
            "medians": medians,
            "iqr": iqr,
            "adjacent_median_increases": sum(
                medians[a] is not None and medians[b] is not None and medians[b] > medians[a] for a, b in pairs),
            "adjacent_iqr_overlaps": [
                f"{a}/{b}" for a, b in pairs
                if iqr[a] and iqr[b] and max(iqr[a][0], iqr[b][0]) <= min(iqr[a][1], iqr[b][1])
            ],
        }
    return out


def candidate_structure(features: dict[str, dict], rs) -> dict:
    positions = {s: {
        "baseline": {"36M": f["36M_RANGE_POSITION"], "52W": f["52W_RANGE_POSITION"]},
        "percentile": {"36M": f["36M_CLOSE_PERCENTILE_POSITION"], "52W": f["52W_CLOSE_PERCENTILE_POSITION"]},
        "robust_range": {"36M": f["36M_ROBUST_CLOSE_RANGE_POSITION"], "52W": f["52W_ROBUST_CLOSE_RANGE_POSITION"]},
    } for s, f in features.items()}
    ma24 = {s: f["MONTHLY_MA24_DISTANCE"] for s, f in features.items()}
    lf = json.loads(json.dumps(rs.label_free_comparison(positions, ma24), default=rs._plain))
    sat = {m: {w: {"le_0_05": sum(p[m][w] <= SATURATION[0] for p in positions.values()),
                   "ge_0_95": sum(p[m][w] >= SATURATION[1] for p in positions.values())}
               for w in ("36M", "52W")} for m in ("baseline", "percentile", "robust_range")}
    return {"label_free": lf, "saturation": sat}


def error_flags(sid: str, f: dict, auto: str, human: str) -> list[str]:
    """Fixed rules (defined before evaluation) for large-error types."""
    b = {k: rule.feature_band(k, f[k]) for k in KEEP}
    side = lambda x: -1 if x < rule.NORMAL else 1 if x > rule.NORMAL else 0  # noqa: E731
    flags = []
    if side(b[KEEP[1]]) != side(b[KEEP[0]]) and ORD[auto] == rule.combine_bands(b[KEEP[0]], b[KEEP[1]], b[KEEP[2]]) \
            and side(ORD[auto]) == side(b[KEEP[0]]) and side(ORD[auto]) != 0:
        flags.append("PRIMARY_DOMINANCE")
    for w, base, alt in (("36M", "36M_RANGE_POSITION", "36M_CLOSE_PERCENTILE_POSITION"),
                         ("52W", "52W_RANGE_POSITION", "52W_CLOSE_PERCENTILE_POSITION")):
        if f[base] < 0.25 and f[alt] >= 0.5:
            flags.append("RANGE_SPIKE_DISTORTION")
            break
    if human in ("DEEP_DEPRESSED", "EXTREME_OVERHEATED") and auto not in ("DEEP_DEPRESSED", "EXTREME_OVERHEATED") \
            and side(ORD[auto]) == side(ORD[human]):
        flags.append("EXTREME_COMPRESSION")
    if {auto, human} & {"NORMAL"} and ({auto, human} & {"DEPRESSED", "DEEP_DEPRESSED"}):
        flags.append("NORMAL_DEPRESSED_BOUNDARY")
    if {side(b[KEEP[0]]), side(b[KEEP[1]])} == {-1, 1}:
        flags.append("MA24_CONFLICT")
    return flags or ["OTHER"]


def one_step_mechanism(features: dict[str, dict], pred: dict[str, str], labels: dict[str, dict]) -> dict:
    """For each 1-step error: did the 36M primary band already differ, or did Family C's later
    steps (extreme relaxation / same-side confirmation) move it? Uses sealed band functions only."""
    out: dict[str, dict] = {}
    for s in SAMPLE_IDS:
        human, auto = labels[s]["label"], pred[s]
        if abs(ORD[auto] - ORD[human]) != 1:
            continue
        b = [rule.feature_band(k, features[s][k]) for k in KEEP]
        stage = "primary_band_differs" if b[0] != ORD[human] else "combine_step_moved_primary"
        key = f"{human}->{auto}"
        entry = out.setdefault(key, {"n": 0, "primary_band_differs": 0, "combine_step_moved_primary": 0,
                                     "band_triples": []})
        entry["n"] += 1
        entry[stage] += 1
        entry["band_triples"].append(b)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT)
    args = parser.parse_args()
    from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
    from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2

    dev = _load("build_pattern_b_development_v02_chart_pack", "scripts/build_pattern_b_development_v02_chart_pack.py")
    rs = _load("research_pattern_b_robust_current_position_v01", "scripts/research_pattern_b_robust_current_position_v01.py")
    fit = _load("analyze_pattern_b_feature_fitness_v01", "scripts/analyze_pattern_b_feature_fitness_v01.py")
    verify_seals(dev)

    labels = {r["sample_id"]: r for r in _read(LABELS)}
    if sorted(labels) != SAMPLE_IDS:
        raise SystemExit("CHECK_REQUIRED: label sample set")
    manifest = {r["sample_id"]: r for r in dev._manifest_rows(dev.MANIFEST)}
    if sorted(manifest) != SAMPLE_IDS:
        raise SystemExit("CHECK_REQUIRED: manifest sample set")
    authority = load_effective_authority(ROOT / dev.hold.AUTHORITY_DIR)
    repository = build_repository_v2(args.data_root, end="2025-12-30")
    features = {}
    for sid in SAMPLE_IDS:
        m = manifest[sid]
        seg = [s for s in dev.hold.common_segments_at(authority.pit_intervals, pd.Timestamp(m["as_of"]))
               if s.ticker == m["ticker"]][0]
        daily = RepositoryV2DailyLoader(repository, start=seg.effective_from.date().isoformat(),
                                        end=m["as_of"]).load(m["ticker"])
        features[sid] = feature_row(daily, m["as_of"], rs)

    pred = {s: rule.classify_pattern_b_state_v01(*(features[s][k] for k in KEEP)) for s in SAMPLE_IDS}
    with RAW_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=("sample_id",) + FEATURE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({"sample_id": s, **{k: repr(features[s][k]) for k in FEATURE_COLUMNS}} for s in SAMPLE_IDS)

    large = []
    for s in SAMPLE_IDS:
        e = ORD[pred[s]] - ORD[labels[s]["label"]]
        if abs(e) >= 2:
            large.append({"sample_id": s, "human_label": labels[s]["label"], "confidence": labels[s]["confidence"],
                          "rule_v01": pred[s], "ordinal_error": e,
                          **{k: round(features[s][k], 4) for k in FEATURE_COLUMNS},
                          "flags": error_flags(s, features[s], pred[s], labels[s]["label"])})
    result = {
        "development_set": True,
        "rule_v01_predictions": pred,
        "rule_v01_metrics": rule_metrics(pred, labels),
        "feature_diagnostics": feature_diagnostics(features, labels, fit),
        "candidate_structure": candidate_structure(features, rs),
        "large_errors": large,
        "one_step_error_mechanism": one_step_mechanism(features, pred, labels),
        "raw_values_sha256": sha256(RAW_CSV),
        "labels_sha256": sha256(LABELS),
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, default=rs._plain) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("rule_v01_metrics", "feature_diagnostics", "candidate_structure",
                                             "large_errors")}, indent=1, default=rs._plain))


if __name__ == "__main__":
    main()
