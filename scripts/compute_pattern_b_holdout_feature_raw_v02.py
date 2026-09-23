#!/usr/bin/env python3
"""Pattern B Holdout V02 raw values for the three KEEP features (no state rule).

Record: docs/patterns/pattern_b/validation/feature_raw_values_v02.md

- sample_id -> ticker/as_of comes only from the sealed Holdout V02 private manifest,
  whose SHA-256 must equal the Holdout seal. The public CSV holds sample_id and the
  three KEEP feature values only.
- Values come from Feature Contract V01 (``compute_pattern_b_features_v01``)
  unchanged. It computes all seven features; only the three KEEP values are kept.
- History is loaded from the PIT COMMON identity segment start through as_of,
  exactly like the Holdout chart pack. Last monthly/weekly bars must equal the
  chart pack's recorded last bars, and an extended (post as_of) load must give
  identical values.
- No HGT label, state rule, threshold, or comparison is used here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pandas as pd

from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.patterns.pattern_b_features_v01 import STATUS_OK, compute_pattern_b_features_v01

ROOT = Path(__file__).resolve().parents[1]
_HOLD = ROOT / "scripts/build_pattern_b_holdout_v02_chart_pack.py"
_spec = importlib.util.spec_from_file_location("build_pattern_b_holdout_v02_chart_pack", _HOLD)
hold = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hold
_spec.loader.exec_module(hold)

VALIDATION_DIR = ROOT / "docs/patterns/pattern_b/validation"
HOLDOUT_SEAL = VALIDATION_DIR / "holdout_v02_seal.json"
DEFAULT_MANIFEST = hold.DEFAULT_OUT_DIR / "private/private_manifest.csv"
DEFAULT_OUT = VALIDATION_DIR / "feature_raw_values_v02.csv"
DEFAULT_PRIVATE_REPORT = hold.DEFAULT_OUT_DIR / "private/feature_raw_run_v02.json"
KEEP_FEATURES: tuple[str, ...] = ("36M_RANGE_POSITION", "MONTHLY_MA24_DISTANCE", "52W_RANGE_POSITION")
OUTPUT_COLUMNS: tuple[str, ...] = ("sample_id",) + KEEP_FEATURES
SAMPLE_IDS: tuple[str, ...] = tuple(f"PBHOLD_{i:03d}" for i in range(1, 37))
FUTURE_CHECK_DAYS = 365


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path, holdout_seal: dict) -> list[dict]:
    if _sha256(path) != holdout_seal["private_manifest_sha256"]:
        raise SystemExit("CHECK_REQUIRED: private manifest differs from the Holdout V02 seal")
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if sorted(r["sample_id"] for r in rows) != list(SAMPLE_IDS):
        raise SystemExit("CHECK_REQUIRED: manifest sample_id set is not PBHOLD_001~036")
    return sorted(rows, key=lambda r: r["sample_id"])


def keep_values(daily: pd.DataFrame, as_of: str) -> tuple[dict, dict]:
    """Public row (sample_id added by caller) and provenance from Feature Contract V01."""
    result = compute_pattern_b_features_v01(daily, as_of)
    values = {}
    for name in KEEP_FEATURES:
        fv = result.features[name]
        if fv.status != STATUS_OK or fv.value is None or not math.isfinite(fv.value):
            raise SystemExit(f"CHECK_REQUIRED: {name} unavailable ({fv.status} {fv.reason})")
        values[name] = repr(fv.value)
    provenance = {
        "effective_history_start": daily.index.min().date().isoformat(),
        "effective_history_end": daily.index.max().date().isoformat(),
        "monthly_last_bar": result.monthly_last_bar.date().isoformat(),
        "weekly_last_bar": result.weekly_last_bar.date().isoformat(),
        "monthly_bar_count": result.monthly_bar_count,
        "weekly_bar_count": result.weekly_bar_count,
    }
    return values, provenance


def validate_public_rows(rows: list[dict]) -> None:
    if [tuple(r) for r in rows] != [OUTPUT_COLUMNS] * len(rows):
        raise SystemExit("CHECK_REQUIRED: public columns differ from sample_id + 3 KEEP features")
    if [r["sample_id"] for r in rows] != list(SAMPLE_IDS):
        raise SystemExit("CHECK_REQUIRED: public sample_id set is not PBHOLD_001~036")
    for r in rows:
        for name in KEEP_FEATURES:
            if not math.isfinite(float(r[name])):
                raise SystemExit(f"CHECK_REQUIRED: non-finite {name}")
        for name in ("36M_RANGE_POSITION", "52W_RANGE_POSITION"):
            if not 0.0 <= float(r[name]) <= 1.0:
                raise SystemExit(f"CHECK_REQUIRED: {name} outside 0~1")
        if float(r["MONTHLY_MA24_DISTANCE"]) <= -1.0:
            raise SystemExit("CHECK_REQUIRED: MONTHLY_MA24_DISTANCE <= -1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repo root that holds data/market (read-only)")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--private-report", type=Path, default=DEFAULT_PRIVATE_REPORT)
    args = parser.parse_args()

    holdout_seal = json.loads(HOLDOUT_SEAL.read_text(encoding="utf-8"))
    chart_pack = hold.DEFAULT_OUT_DIR / hold.ZIP_NAME
    if _sha256(chart_pack) != holdout_seal["chart_pack_sha256"]:
        raise SystemExit("CHECK_REQUIRED: chart pack differs from the Holdout V02 seal")
    manifest = load_manifest(args.manifest, holdout_seal)

    authority = load_effective_authority(ROOT / hold.AUTHORITY_DIR)
    repository = build_repository_v2(args.data_root, end=max(m["as_of"] for m in manifest))
    rows: list[dict] = []
    checks: list[dict] = []
    for sample in manifest:
        as_of = pd.Timestamp(sample["as_of"])
        segments = [s for s in hold.common_segments_at(authority.pit_intervals, as_of) if s.ticker == sample["ticker"]]
        if len(segments) != 1:
            raise SystemExit(f"CHECK_REQUIRED: {sample['sample_id']} identity segment not unique at as_of")
        start = segments[0].effective_from.date().isoformat()
        loader = RepositoryV2DailyLoader(repository, start=start, end=sample["as_of"])
        daily = loader.load(sample["ticker"])
        if daily is None or daily.empty or daily.index.max() > as_of:
            raise SystemExit(f"CHECK_REQUIRED: {sample['sample_id']} history missing or after as_of")
        values, provenance = keep_values(daily, sample["as_of"])

        future_end = (as_of + pd.Timedelta(days=FUTURE_CHECK_DAYS)).date().isoformat()
        future_daily = RepositoryV2DailyLoader(repository, start=start, end=future_end).load(sample["ticker"])
        future_values, _ = keep_values(future_daily, sample["as_of"])
        checks.append({
            "sample_id": sample["sample_id"],
            "request_start": loader.start,
            "request_end": loader.end,
            "request_end_equals_as_of": loader.end == sample["as_of"],
            **provenance,
            "last_bars_match_chart_pack": (
                provenance["monthly_last_bar"] == sample["monthly_last_date"]
                and provenance["weekly_last_bar"] == sample["weekly_last_date"]
            ),
            "future_rows_loaded": int((future_daily.index > as_of).sum()),
            "future_invariant": future_values == values,
        })
        rows.append({"sample_id": sample["sample_id"], **values})

    validate_public_rows(rows)
    failed = [c["sample_id"] for c in checks if not (
        c["request_end_equals_as_of"] and c["last_bars_match_chart_pack"] and c["future_invariant"]
        and c["effective_history_end"] <= c["request_end"]
    )]
    if failed:
        raise SystemExit(f"CHECK_REQUIRED: PIT/provenance checks failed for {len(failed)} samples")

    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "sample_count": len(rows),
        "request_end_equals_as_of": sum(c["request_end_equals_as_of"] for c in checks),
        "last_bars_match_chart_pack": sum(c["last_bars_match_chart_pack"] for c in checks),
        "future_invariant": sum(c["future_invariant"] for c in checks),
        "samples_with_future_rows_loaded": sum(1 for c in checks if c["future_rows_loaded"] > 0),
        "min_monthly_bars": min(c["monthly_bar_count"] for c in checks),
        "min_weekly_bars": min(c["weekly_bar_count"] for c in checks),
    }
    hold._private_write(args.private_report, json.dumps({"summary": summary, "checks": checks}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
