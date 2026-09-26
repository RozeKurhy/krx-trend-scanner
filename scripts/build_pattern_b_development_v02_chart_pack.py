#!/usr/bin/env python3
"""Pattern B Criteria V02 development set V01: sample selection and blind chart pack.

Protocol: docs/patterns/pattern_b/validation/development_v02_protocol.md

Development only (not a holdout). Same mechanics as the Holdout V02 generator:
- 4 anchors (last KRX session on or before Dec 31 of 2019/2021/2023/2025) x 9.
- Candidates: PIT COMMON segments valid at the anchor, excluding every V01
  primary/backup ticker and every Holdout V02 ticker, ordered by
  sha256("PATTERN_B_DEVELOPMENT_V02|anchor|ticker"); first 9 passing the V02
  data checks (incl. HALTED_AT_AS_OF) per anchor; no ticker reused.
- No feature, state rule, human label, or future return is used or computed.
- sample_id permutation drawn once with ``secrets``; kept only in the private
  manifest; reruns reuse it and fail closed on any difference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys
import zipfile

import pandas as pd

from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_pattern_b_holdout_v02_chart_pack", ROOT / "scripts/build_pattern_b_holdout_v02_chart_pack.py"
)
hold = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hold
_spec.loader.exec_module(hold)
v01 = hold.v01

VERSION = "PATTERN_B_DEVELOPMENT_V02"
SEED_NAMESPACE = "PATTERN_B_DEVELOPMENT_V02"
ANCHOR_YEARS: tuple[int, ...] = (2019, 2021, 2023, 2025)
SAMPLES_PER_ANCHOR = 9
SAMPLE_PREFIX = "PBDEV2_"
SAMPLE_IDS = tuple(f"{SAMPLE_PREFIX}{i:03d}" for i in range(1, 37))
OUT_DIR = ROOT / "artifacts/pattern_b_development_v02"
PRIVATE_DIR = OUT_DIR / "private"
MANIFEST = PRIVATE_DIR / "development_v02_private_manifest.csv"
ZIP_NAME = "pattern_b_development_v02_blind_pack.zip"
V = ROOT / "docs/patterns/pattern_b/validation"
SEAL = V / "development_v02_seal.json"
PROTOCOL = V / "development_v02_protocol.md"
CHART_RECORD = V / "development_v02_chart_pack.md"
CRITERIA = V / "human_ground_truth_criteria_v02.md"
HOLDOUT_V02_MANIFEST = hold.DEFAULT_OUT_DIR / "private/private_manifest.csv"
V01_MANIFEST = ROOT / "artifacts/pattern_b_hgt_v01/private/private_manifest.csv"

EXPECTED_SUMMARY = {
    "sample_count": 36,
    "unique_tickers": 36,
    "per_anchor": {str(y): SAMPLES_PER_ANCHOR for y in ANCHOR_YEARS},
    "v01_ticker_overlap": 0,
    "holdout_v02_ticker_overlap": 0,
    "v01_exact_sample_overlap": 0,
    "holdout_v02_exact_sample_overlap": 0,
    "sample_ids_exact": True,
    "monthly_bar_counts": [84],
    "weekly_bar_counts": [156],
    "daily_after_as_of": 0,
    "bars_after_as_of": 0,
    "samples_with_trailing_halt": 0,
    "png_count": 36,
    "png_sizes": [[1600, 1200]],
    "png_metadata_leaks": 0,
    "zip_entries": 37,
    "zip_name_leaks": 0,
}


def resolve_anchor(calendar: pd.DatetimeIndex, year: int) -> pd.Timestamp:
    """Last KRX session on or before December 31 of ``year``."""
    sessions = calendar[calendar <= pd.Timestamp(year, 12, 31)]
    if sessions.empty or sessions[-1].year != year:
        raise SystemExit(f"CHECK_REQUIRED: no KRX session on or before {year}-12-31")
    return sessions[-1]


def hash_key(anchor: pd.Timestamp, ticker: str) -> str:
    return hashlib.sha256(f"{SEED_NAMESPACE}|{anchor.date().isoformat()}|{ticker}".encode()).hexdigest()


def _manifest_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def excluded_tickers() -> tuple[frozenset[str], frozenset[str]]:
    holdout = frozenset(r["ticker"] for r in _manifest_rows(HOLDOUT_V02_MANIFEST))
    return hold.V01_TICKERS, holdout


def select_samples(anchors, intervals, repository, calendar, excluded: frozenset[str]):
    used: set[str] = set()
    samples, audit = [], {}
    for year, anchor in anchors:
        candidates = sorted(
            (s for s in hold.common_segments_at(intervals, anchor) if s.ticker not in excluded),
            key=lambda s: hash_key(anchor, s.ticker),
        )
        accepted, skipped, skips = 0, 0, {}
        for rank, seg in enumerate(candidates, start=1):
            if accepted == SAMPLES_PER_ANCHOR:
                break
            if seg.ticker in used:
                skips["already_selected"] = skips.get("already_selected", 0) + 1
                skipped += 1
                continue
            loader = RepositoryV2DailyLoader(repository, start=seg.effective_from.date().isoformat(), end=anchor)
            try:
                window = hold.build_window(loader.load(seg.ticker), calendar, anchor)
            except hold.CandidateSkip as exc:
                skips[str(exc)] = skips.get(str(exc), 0) + 1
                skipped += 1
                continue
            used.add(seg.ticker)
            accepted += 1
            samples.append({"ticker": seg.ticker, "anchor_year": year, "as_of": anchor.date().isoformat(),
                            "selection_rank": rank, "skip_count_before_accept": skipped, **window})
            skipped = 0
        if accepted != SAMPLES_PER_ANCHOR:
            raise SystemExit(f"CHECK_REQUIRED: anchor {year} filled {accepted}/{SAMPLES_PER_ANCHOR}")
        audit[str(year)] = {"candidates": len(candidates), "skips": skips}
    return samples, audit


def assign_sample_ids(samples: list[dict]) -> None:
    keys = [(s["ticker"], s["as_of"]) for s in samples]
    if MANIFEST.exists():
        stored = {(r["ticker"], r["as_of"]): r["sample_id"] for r in _manifest_rows(MANIFEST)}
        if set(stored) != set(keys):
            raise SystemExit("CHECK_REQUIRED: existing development manifest differs from the selected set")
        mapping = stored
    else:
        order = list(keys)
        secrets.SystemRandom().shuffle(order)
        mapping = {k: f"{SAMPLE_PREFIX}{i:03d}" for i, k in enumerate(order, start=1)}
    for s in samples:
        s["sample_id"] = mapping[(s["ticker"], s["as_of"])]


def verify(samples, anchors, calendar, forbidden: re.Pattern, v01_keys, v02_keys, v01_tickers, v02_tickers) -> dict:
    from PIL import Image

    blind = OUT_DIR / "blind"
    pngs = sorted(blind.glob("*.png"))
    sizes, meta_leaks = set(), 0
    for png in pngs:
        with Image.open(png) as img:
            sizes.add(img.size)
            meta_leaks += sum(1 for v in img.info.values() if isinstance(v, str) and forbidden.search(v))
    with zipfile.ZipFile(OUT_DIR / ZIP_NAME) as zf:
        names = zf.namelist()
    tickers = [s["ticker"] for s in samples]
    keys = {(s["ticker"], s["as_of"]) for s in samples}
    return {
        "sample_count": len(samples),
        "unique_tickers": len(set(tickers)),
        "per_anchor": {str(y): sum(s["anchor_year"] == y for s in samples) for y, _ in anchors},
        "v01_ticker_overlap": len(set(tickers) & v01_tickers),
        "holdout_v02_ticker_overlap": len(set(tickers) & v02_tickers),
        "v01_exact_sample_overlap": len(keys & v01_keys),
        "holdout_v02_exact_sample_overlap": len(keys & v02_keys),
        "sample_ids_exact": sorted(s["sample_id"] for s in samples) == list(SAMPLE_IDS),
        "monthly_bar_counts": sorted({len(s["monthly"]) for s in samples}),
        "weekly_bar_counts": sorted({len(s["weekly"]) for s in samples}),
        "daily_after_as_of": sum(s["daily_max"] > pd.Timestamp(s["as_of"]) for s in samples),
        "bars_after_as_of": sum(int((s["monthly"].index > pd.Timestamp(s["as_of"])).sum())
                                + int((s["weekly"].index > pd.Timestamp(s["as_of"])).sum()) for s in samples),
        "samples_with_trailing_halt": sum(hold._has_trailing_halt(s, calendar) for s in samples),
        "samples_with_halt_gaps": sum(1 for s in samples if any(s["halt_slots"].values())),
        "png_count": len(pngs),
        "png_sizes": sorted(list(x) for x in sizes),
        "png_metadata_leaks": meta_leaks,
        "zip_entries": len(names),
        "zip_name_leaks": sum(1 for n in names if forbidden.search(n)),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--force", action="store_true", help="re-render with the stored mapping")
    args = parser.parse_args()
    blind = OUT_DIR / "blind"
    if blind.exists() and any(blind.iterdir()) and not args.force:
        raise SystemExit(f"{blind} exists; pass --force to re-render with the same mapping")

    calendar = pd.DatetimeIndex(
        pd.read_parquet(ROOT / "data/reference/krx_trading_calendar.parquet")["trading_date"]
    ).normalize().sort_values()
    anchors = [(y, resolve_anchor(calendar, y)) for y in ANCHOR_YEARS]
    v01_tickers, v02_tickers = excluded_tickers()
    authority = load_effective_authority(ROOT / hold.AUTHORITY_DIR)
    repository = build_repository_v2(args.data_root, end=max(a for _, a in anchors))
    samples, audit = select_samples(anchors, authority.pit_intervals, repository, calendar,
                                    v01_tickers | v02_tickers)
    hold.stock_names(pd.read_parquet(ROOT / "data/reference/krx_instrument_metadata.parquet"), samples)

    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    os.chmod(PRIVATE_DIR, 0o700)
    blind.mkdir(parents=True, exist_ok=True)
    assign_sample_ids(samples)
    samples.sort(key=lambda s: s["sample_id"])
    rows = [{
        "sample_id": s["sample_id"], "ticker": s["ticker"], "stock_name": s["stock_name"],
        "anchor_year": s["anchor_year"], "as_of": s["as_of"],
        "monthly_first_date": s["monthly"].index[0].date().isoformat(),
        "monthly_last_date": s["monthly"].index[-1].date().isoformat(),
        "weekly_first_date": s["weekly"].index[0].date().isoformat(),
        "weekly_last_date": s["weekly"].index[-1].date().isoformat(),
        "selection_rank": s["selection_rank"], "skip_count_before_accept": s["skip_count_before_accept"],
    } for s in samples]
    hold.ensure_manifest(MANIFEST, rows)

    forbidden = hold.forbidden_pattern(samples)
    for s in samples:
        v01.render_sample(s, blind / f"{s['sample_id']}.png", forbidden)
    with (blind / "annotation_template.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sample_id", "label", "confidence", "note"])
        writer.writerows([s["sample_id"], "", "", ""] for s in samples)
    for path in blind.iterdir():
        os.utime(path, (0, 0))
    with zipfile.ZipFile(OUT_DIR / ZIP_NAME, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in [f"{s['sample_id']}.png" for s in samples] + ["annotation_template.csv"]:
            info = zipfile.ZipInfo(name, date_time=v01.ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (blind / name).read_bytes())

    v01_keys = {(r["ticker"], r["as_of"]) for r in _manifest_rows(V01_MANIFEST)}
    v02_keys = {(r["ticker"], r["as_of"]) for r in _manifest_rows(HOLDOUT_V02_MANIFEST)}
    summary = verify(samples, anchors, calendar, forbidden, v01_keys, v02_keys, v01_tickers, v02_tickers)
    hold._private_write(PRIVATE_DIR / "verification_summary.json", json.dumps(summary, indent=2))
    hold._private_write(PRIVATE_DIR / "selection_audit.json", json.dumps(
        {"anchors": {str(y): a.date().isoformat() for y, a in anchors}, "per_anchor": audit}, indent=2))
    mismatched = sorted(k for k, v in EXPECTED_SUMMARY.items() if summary.get(k) != v)
    if mismatched:
        raise SystemExit(f"CHECK_REQUIRED: verification failed: {mismatched}")
    print(json.dumps({"verification": summary, "chart_pack_sha256": sha256(OUT_DIR / ZIP_NAME),
                      "private_manifest_sha256": sha256(MANIFEST),
                      "anchors": [a.date().isoformat() for _, a in anchors], "audit": audit}, indent=2))


if __name__ == "__main__":
    main()
