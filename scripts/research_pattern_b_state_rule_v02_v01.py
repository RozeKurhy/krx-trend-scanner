#!/usr/bin/env python3
"""Pattern B State Rule V02 research V01: 9 fixed minimal-change candidates (research only).

Record: docs/patterns/pattern_b/validation/state_rule_v02_research_v01.md

Inputs: sealed development V02 human labels and the development feature raw values
(KEEP 3 only). Candidates are exactly A0/A1/A2 (DEEP condition) x B0/B1/B2
(36M DEPRESSED/NORMAL boundary 0.25/0.30/0.35). Everything else delegates to the
sealed State Rule V01 functions; no other threshold changes, no search.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from trend_scanner.patterns import pattern_b_state_v01 as rule

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "docs/patterns/pattern_b/validation"
LABELS = V / "development_v02_human_labels.csv"
RAW = V / "development_v02_feature_raw_values_v01.csv"
LABEL_SEAL = V / "development_v02_human_labels_seal.json"
OUT_JSON = V / "state_rule_v02_research_v01.json"
RAW_SHA256 = "d2d9eebc378fc559b7ca7ec2583c00217cac11154307f650d843117aaa82225e"
SAMPLE_IDS = [f"PBDEV2_{i:03d}" for i in range(1, 37)]
STATES = rule.STATES
ORD = {s: i for i, s in enumerate(STATES)}
DEEP_MODES = ("A0", "A1", "A2")
BOUNDARIES = {"B0": 0.25, "B1": 0.30, "B2": 0.35}
TRANSITIONS = (
    ("DEEP_DEPRESSED", "DEPRESSED"), ("DEPRESSED", "NORMAL"), ("NORMAL", "DEPRESSED"),
    ("NORMAL", "OVERHEATED"), ("OVERHEATED", "NORMAL"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def band_36m(value: float, boundary: float) -> int:
    """36M band with only the DEPRESSED/NORMAL boundary replaced; semantics as V01 (inclusive lower)."""
    t = rule.THRESHOLDS[rule.RANGE_36M]
    return sum(value >= x for x in (t[0], boundary, t[2], t[3]))


def combine_candidate(m36: int, ma24: int, w52: int, deep_mode: str) -> int:
    """A0 = sealed V01. A1/A2 only keep DEEP when 36M is DEEP and the extra condition holds;
    every other case is delegated to the sealed ``combine_bands``."""
    if m36 == 0:
        if deep_mode == "A1" and ma24 < rule.NORMAL:
            return 0
        if deep_mode == "A2" and (ma24 < rule.NORMAL or w52 == 0):
            return 0
    return rule.combine_bands(m36, ma24, w52)


def predict(features: dict[str, dict], deep_mode: str, boundary: float) -> dict[str, str]:
    out = {}
    for s, f in features.items():
        m36 = band_36m(f[rule.RANGE_36M], boundary)
        ma24 = rule.feature_band(rule.MA24_DISTANCE, f[rule.MA24_DISTANCE])
        w52 = rule.feature_band(rule.RANGE_52W, f[rule.RANGE_52W])
        out[s] = STATES[combine_candidate(m36, ma24, w52, deep_mode)]
    return out


def evaluate(pred: dict[str, str], labels: dict[str, str], baseline: dict[str, str]) -> dict:
    err = {s: ORD[pred[s]] - ORD[labels[s]] for s in SAMPLE_IDS}
    base_err = {s: ORD[baseline[s]] - ORD[labels[s]] for s in SAMPLE_IDS}
    a = [abs(e) for e in err.values()]
    per_state = {}
    for st in STATES:
        sub = [s for s in SAMPLE_IDS if labels[s] == st]
        per_state[st] = {"n": len(sub), "exact": sum(err[s] == 0 for s in sub),
                         "within_1": sum(abs(err[s]) <= 1 for s in sub)}
    return {
        "exact": sum(e == 0 for e in a), "within_1": sum(e <= 1 for e in a),
        "mae": round(sum(a) / len(a), 4), "error_ge_2": sum(e >= 2 for e in a), "error_ge_3": sum(e >= 3 for e in a),
        "signed_error_counts": {str(k): sum(e == k for e in err.values()) for k in range(-4, 5)},
        "per_state": per_state,
        "transitions": {f"{h}->{x}": sum(labels[s] == h and pred[s] == x for s in SAMPLE_IDS) for h, x in TRANSITIONS},
        "new_errors_vs_v01": sorted(s for s in SAMPLE_IDS if err[s] != 0 and base_err[s] == 0),
        "fixed_errors_vs_v01": sorted(s for s in SAMPLE_IDS if err[s] == 0 and base_err[s] != 0),
        "changed_predictions_vs_v01": sorted(s for s in SAMPLE_IDS if pred[s] != baseline[s]),
    }


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run() -> dict:
    seal = json.loads(LABEL_SEAL.read_text(encoding="utf-8"))
    if seal["labels_file_sha256"] != sha256(LABELS) or sha256(RAW) != RAW_SHA256:
        raise SystemExit("CHECK_REQUIRED: sealed labels or raw feature values changed")
    labels = {r["sample_id"]: r["label"] for r in _read(LABELS)}
    features = {r["sample_id"]: {k: float(r[k]) for k in rule.FEATURES} for r in _read(RAW)}
    if sorted(labels) != SAMPLE_IDS or sorted(features) != SAMPLE_IDS:
        raise SystemExit("CHECK_REQUIRED: sample set")
    baseline = predict(features, "A0", BOUNDARIES["B0"])
    if baseline != {s: rule.classify_pattern_b_state_v01(*(features[s][k] for k in rule.FEATURES)) for s in SAMPLE_IDS}:
        raise SystemExit("CHECK_REQUIRED: A0/B0 does not reproduce sealed Rule V01")
    candidates = {}
    for a in DEEP_MODES:
        for b, boundary in BOUNDARIES.items():
            pred = predict(features, a, boundary)
            candidates[f"{a}/{b}"] = {"deep_mode": a, "boundary_36m_normal": boundary,
                                      "predictions": pred, **evaluate(pred, labels, baseline)}
    return {"development_set": True, "raw_values_sha256": RAW_SHA256,
            "labels_sha256": seal["labels_file_sha256"], "candidates": candidates}


def main() -> None:
    result = run()
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, c in result["candidates"].items():
        print(name, {k: c[k] for k in ("exact", "within_1", "mae", "error_ge_2", "error_ge_3")},
              c["transitions"], "new", c["new_errors_vs_v01"], "fixed", len(c["fixed_errors_vs_v01"]))


if __name__ == "__main__":
    main()
