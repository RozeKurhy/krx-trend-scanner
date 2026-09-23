#!/usr/bin/env python3
"""Pattern B HGT V01 raw feature runner (36 samples x 7 features).

Record: docs/patterns/pattern_b/validation/feature_raw_values_v01.md

- Joins sample_id -> ticker/as_of through the private manifest only; the public
  CSV holds sample_id plus the 7 feature values/statuses and nothing else.
  Per-sample provenance (history range, last bars, bar counts) stays in the
  private report, since those dates reveal each sample's as_of.
- Loads Repository V2 adjusted history from a fixed 1900-01-01 through as_of and
  calls Feature Contract V01 unchanged. No HGT label, threshold, or score is used.
- Re-computes every sample with an extended (post as_of) load to confirm the
  result does not change (PIT invariance). Per-sample checks stay private.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pandas as pd

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.patterns.pattern_b_features_v01 import (
    FEATURE_NAMES,
    STATUS_OK,
    compute_pattern_b_features_v01,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "artifacts/pattern_b_hgt_v01/private/private_manifest.csv"
DEFAULT_OUT = ROOT / "docs/patterns/pattern_b/validation/feature_raw_values_v01.csv"
DEFAULT_PRIVATE_REPORT = ROOT / "artifacts/pattern_b_hgt_v01/private/feature_raw_run_v01.json"
# First sealed run (published with provenance columns); its 15 public columns must match exactly.
BASELINE_REF = "2aa45d027f9e615ead710a7edc9c0f4dc3713268"
BASELINE_PATH = "docs/patterns/pattern_b/validation/feature_raw_values_v01.csv"
REQUESTED_HISTORY_START = "1900-01-01"
FUTURE_CHECK_DAYS = 365
SAMPLE_IDS: tuple[str, ...] = tuple(f"PBHGT_{i:03d}" for i in range(1, 37))

PROVENANCE_COLUMNS = (
    "requested_history_start",
    "effective_history_start",
    "effective_history_end",
    "monthly_last_bar",
    "weekly_last_bar",
    "monthly_bar_count",
    "weekly_bar_count",
)
OUTPUT_COLUMNS: tuple[str, ...] = ("sample_id",) + tuple(
    col for name in FEATURE_NAMES for col in (name, f"{name}_status")
)
FORBIDDEN_COLUMNS = frozenset(
    {"ticker", "stock_name", "as_of", "label", "confidence", "note"} | set(PROVENANCE_COLUMNS)
)


def validate_sample_ids(sample_ids: list[str]) -> None:
    duplicates = sorted({s for s in sample_ids if sample_ids.count(s) > 1})
    missing = sorted(set(SAMPLE_IDS) - set(sample_ids))
    extra = sorted(set(sample_ids) - set(SAMPLE_IDS))
    if duplicates or missing or extra or len(sample_ids) != len(SAMPLE_IDS):
        raise ValueError(f"sample_id set invalid: duplicates={duplicates} missing={missing} extra={extra}")


def load_manifest(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        rows = [
            {"sample_id": r["sample_id"], "ticker": r["ticker"], "stock_name": r["stock_name"], "as_of": r["as_of"]}
            for r in csv.DictReader(fh)
        ]
    validate_sample_ids([r["sample_id"] for r in rows])
    return sorted(rows, key=lambda r: r["sample_id"])


def _date(value) -> str:
    return "" if value is None else pd.Timestamp(value).date().isoformat()


def feature_row(sample_id: str, daily: pd.DataFrame, as_of: str) -> tuple[dict, dict]:
    """Public row and private provenance for one sample; asserts the PIT invariants."""
    as_of_ts = pd.Timestamp(as_of)
    result = compute_pattern_b_features_v01(daily, as_of_ts)
    history_end = daily.index.max()
    for label, value in (
        ("effective_history_end", history_end),
        ("monthly_last_bar", result.monthly_last_bar),
        ("weekly_last_bar", result.weekly_last_bar),
    ):
        if value is None or value > as_of_ts:
            raise RuntimeError(f"{sample_id}: {label} is missing or after as_of")
    row: dict = {"sample_id": sample_id}
    for name in FEATURE_NAMES:
        fv = result.features[name]
        row[name] = "" if fv.value is None else repr(fv.value)
        row[f"{name}_status"] = fv.status
    provenance = {
        "sample_id": sample_id,
        "requested_history_start": REQUESTED_HISTORY_START,
        "effective_history_start": _date(daily.index.min()),
        "effective_history_end": _date(history_end),
        "monthly_last_bar": _date(result.monthly_last_bar),
        "weekly_last_bar": _date(result.weekly_last_bar),
        "monthly_bar_count": result.monthly_bar_count,
        "weekly_bar_count": result.weekly_bar_count,
    }
    return row, provenance


def validate_public_rows(rows: list[dict], manifest: list[dict]) -> None:
    """Public output: exact 15 columns, 36 sample_ids, and no ticker/name values anywhere."""
    for row in rows:
        if FORBIDDEN_COLUMNS & set(row):
            raise ValueError(f"forbidden public columns: {sorted(FORBIDDEN_COLUMNS & set(row))}")
        if tuple(row) != OUTPUT_COLUMNS:
            raise ValueError(f"unexpected public columns: {sorted(set(row) ^ set(OUTPUT_COLUMNS))}")
    validate_sample_ids([r["sample_id"] for r in rows])
    identifiers = {m["ticker"] for m in manifest} | {m["stock_name"] for m in manifest}
    leaked = [(r["sample_id"], k) for r in rows for k, v in r.items() if str(v) in identifiers]
    if leaked:
        raise ValueError(f"ticker/name value leaked into public output: {leaked[:3]}")


def compare_with_baseline(rows: list[dict], baseline_csv: str) -> list[str]:
    """Differences between ``rows`` and the baseline CSV projected to the public columns."""
    baseline = {
        r["sample_id"]: {c: r[c] for c in OUTPUT_COLUMNS}
        for r in csv.DictReader(io.StringIO(baseline_csv))
    }
    diffs = ["sample set differs"] if set(baseline) != {r["sample_id"] for r in rows} else []
    for row in rows:
        expected = baseline.get(row["sample_id"], {})
        diffs += [f"{row['sample_id']}.{c}" for c in OUTPUT_COLUMNS if str(row[c]) != expected.get(c)]
    return diffs


def _baseline_csv() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{BASELINE_REF}:{BASELINE_PATH}"],
        check=True, capture_output=True, text=True,
    ).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repo root that holds data/market (read-only)")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--private-report", type=Path, default=DEFAULT_PRIVATE_REPORT)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    repository = build_repository_v2(args.data_root, end=max(m["as_of"] for m in manifest))
    rows: list[dict] = []
    checks: list[dict] = []
    for sample in manifest:
        as_of = sample["as_of"]
        loader = RepositoryV2DailyLoader(repository, start=REQUESTED_HISTORY_START, end=as_of)
        daily = loader.load(sample["ticker"])
        if daily is None or daily.empty:
            raise SystemExit(f"CHECK_REQUIRED: {sample['sample_id']} has no Repository V2 data")
        row, provenance = feature_row(sample["sample_id"], daily, as_of)

        future_end = (pd.Timestamp(as_of) + pd.Timedelta(days=FUTURE_CHECK_DAYS)).date().isoformat()
        future_daily = RepositoryV2DailyLoader(repository, start=REQUESTED_HISTORY_START, end=future_end).load(
            sample["ticker"]
        )
        future_row, future_provenance = feature_row(
            sample["sample_id"], future_daily[future_daily.index <= as_of], as_of
        )
        future_full = compute_pattern_b_features_v01(future_daily, as_of)
        invariant = row == future_row and provenance == future_provenance and all(
            (repr(future_full.features[n].value) if future_full.features[n].value is not None else "") == row[n]
            and future_full.features[n].status == row[f"{n}_status"]
            for n in FEATURE_NAMES
        )
        checks.append({
            **provenance,
            "request_start": loader.start,
            "request_end": loader.end,
            "request_end_equals_as_of": loader.end == as_of,
            "future_rows_loaded": int((future_daily.index > pd.Timestamp(as_of)).sum()),
            "future_invariant": bool(invariant),
        })
        rows.append(row)

    validate_public_rows(rows, manifest)
    if not all(c["request_end_equals_as_of"] and c["future_invariant"] for c in checks):
        raise SystemExit("CHECK_REQUIRED: PIT provenance or future-invariance check failed")
    baseline_diffs = compare_with_baseline(rows, _baseline_csv())
    if baseline_diffs:
        raise SystemExit(f"CHECK_REQUIRED: public values differ from {BASELINE_REF[:8]}: {baseline_diffs[:5]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    status_counts = {
        name: dict(pd.Series([r[f"{name}_status"] for r in rows]).value_counts().sort_index())
        for name in FEATURE_NAMES
    }
    summary = {
        "sample_count": len(rows),
        "requested_history_start": REQUESTED_HISTORY_START,
        "status_counts": {k: {s: int(c) for s, c in v.items()} for k, v in status_counts.items()},
        "all_ok": all(r[f"{n}_status"] == STATUS_OK for r in rows for n in FEATURE_NAMES),
        "public_column_count": len(OUTPUT_COLUMNS),
        "baseline_exact_match": f"{BASELINE_REF[:8]}: 0 differences",
        "request_end_equals_as_of": sum(c["request_end_equals_as_of"] for c in checks),
        "future_invariant": sum(c["future_invariant"] for c in checks),
        "samples_with_future_rows_loaded": sum(1 for c in checks if c["future_rows_loaded"] > 0),
    }
    args.private_report.parent.mkdir(parents=True, exist_ok=True)
    args.private_report.write_text(json.dumps({"summary": summary, "checks": checks}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
