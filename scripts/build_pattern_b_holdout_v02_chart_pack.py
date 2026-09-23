#!/usr/bin/env python3
"""Pattern B Holdout V02 sample selection and blind chart pack (pre-seal).

Protocol: docs/patterns/pattern_b/validation/holdout_v02_protocol.md

- 4 fixed anchor years (last KRX session on or before June 30) x 9 samples.
- Candidates: PIT COMMON identity segments valid at the anchor, excluding every
  V01 primary/backup ticker, ordered by sha256("PATTERN_B_HOLDOUT_V02|anchor|ticker").
  The first 9 per anchor that pass data checks are taken; tickers are never reused.
- Selection uses only identity, anchor, data availability, and hash order. No
  Pattern B feature, pattern evaluator, HGT label, or future return is used.
- A candidate halted at as_of (no bar in the last completed month or week) is
  skipped: its latest price would be stale. Earlier halts stay as calendar gaps.
- Charts reuse the V01 chart-pack rendering (84 monthly + 156 weekly completed
  bars, halt gaps kept). The sample_id permutation is drawn once with ``secrets``
  and kept only in the private manifest; reruns reuse it and fail on mismatch.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import zipfile

import pandas as pd

from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2


ROOT = Path(__file__).resolve().parents[1]
_V01_PATH = ROOT / "scripts/build_pattern_b_hgt_v01_chart_pack.py"
_spec = importlib.util.spec_from_file_location("build_pattern_b_hgt_v01_chart_pack", _V01_PATH)
v01 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v01)

GENERATOR_VERSION = "pattern_b_holdout_v02_chart_pack/1"
SEED_NAMESPACE = "PATTERN_B_HOLDOUT_V02"
ANCHOR_YEARS: tuple[int, ...] = (2020, 2022, 2024, 2026)
SAMPLES_PER_ANCHOR = 9
SAMPLE_PREFIX = "PBHOLD_"
AUTHORITY_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/"
    "v01_spac_corrected_effective_authority"
)
DEFAULT_OUT_DIR = ROOT / "artifacts/pattern_b_holdout_v02"
DEFAULT_SEAL = ROOT / "docs/patterns/pattern_b/validation/holdout_v02_seal.json"
ZIP_NAME = "pattern_b_holdout_v02_blind_pack.zip"
V01_TICKERS = frozenset(t for t, _ in v01.PRIMARY_TICKERS + v01.BACKUP_TICKERS)
MANIFEST_FIELDS = (
    "sample_id", "ticker", "stock_name", "anchor_year", "as_of",
    "monthly_first_date", "monthly_last_date", "weekly_first_date", "weekly_last_date",
    "selection_rank", "skip_count_before_accept",
)


class CandidateSkip(RuntimeError):
    """Candidate lacks usable identity/data; move to the next hash-ordered candidate.

    The message is a skip code: NO_DATA, OHLC_INVALID, INSUFFICIENT_BARS,
    CALENDAR_MISMATCH, HALTED_AT_AS_OF.
    """


@dataclass(frozen=True)
class Segment:
    ticker: str
    effective_from: pd.Timestamp
    effective_to: pd.Timestamp


def resolve_anchor(calendar: pd.DatetimeIndex, year: int) -> pd.Timestamp:
    """Last KRX session on or before June 30 of ``year``."""
    sessions = calendar[calendar <= pd.Timestamp(year, 6, 30)]
    if sessions.empty or sessions[-1].year != year:
        raise RuntimeError(f"no KRX session on or before {year}-06-30")
    return sessions[-1]


def hash_key(anchor: pd.Timestamp, ticker: str) -> str:
    text = f"{SEED_NAMESPACE}|{anchor.date().isoformat()}|{ticker}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def common_segments_at(intervals, anchor: pd.Timestamp) -> list[Segment]:
    """PIT COMMON identity segments covering ``anchor`` (one per ticker)."""
    found: dict[str, Segment] = {}
    for item in intervals:
        if item.get("state") != "COMMON":
            continue
        start = pd.Timestamp(item["effective_from"]).normalize()
        end = pd.Timestamp(item["effective_to"]).normalize()
        if start <= anchor <= end:
            ticker = str(item["ticker"])
            if ticker in found:
                raise RuntimeError(f"{ticker}: overlapping COMMON segments at {anchor.date()}")
            found[ticker] = Segment(ticker, start, end)
    return list(found.values())


def validate_ohlc(daily: pd.DataFrame) -> None:
    cols = ["open", "high", "low", "close"]
    if not set(cols) <= set(daily.columns):
        raise CandidateSkip("OHLC_INVALID")
    values = daily[cols]
    if not values.notna().all().all() or not (values > 0).all().all():
        raise CandidateSkip("OHLC_INVALID")
    body_low = values[["open", "close"]].min(axis=1)
    body_high = values[["open", "close"]].max(axis=1)
    if ((values["low"] > body_low) | (values["high"] < body_high)).any():
        raise CandidateSkip("OHLC_INVALID")


def build_window(daily: pd.DataFrame | None, calendar: pd.DatetimeIndex, as_of: pd.Timestamp) -> dict:
    """Completed 84 monthly / 156 weekly bars within one identity segment.

    Earlier halted periods produce no bar and stay as calendar gaps. A candidate
    without a bar in the last completed month or week (halted at as_of) is skipped.
    Bars must line up with KRX calendar periods.
    """
    if daily is None or daily.empty:
        raise CandidateSkip("NO_DATA")
    if daily.index.max() > as_of:
        raise AssertionError("loader returned rows after as_of")
    validate_ohlc(daily)
    monthly, weekly = v01.completed_bars(daily, as_of)
    if len(monthly) < v01.MONTHLY_BARS or len(weekly) < v01.WEEKLY_BARS:
        raise CandidateSkip("INSUFFICIENT_BARS")
    monthly = monthly.iloc[-v01.MONTHLY_BARS:]
    weekly = weekly.iloc[-v01.WEEKLY_BARS:]
    exp_months, exp_weeks = v01.expected_period_labels(calendar, as_of)
    halt_slots = {}
    for kind, bars, expected in (("monthly", monthly, exp_months), ("weekly", weekly, exp_weeks)):
        if not bars.index.isin(expected).all():
            raise CandidateSkip("CALENDAR_MISMATCH")
        if bars.index[-1] != expected[-1]:
            raise CandidateSkip("HALTED_AT_AS_OF")
        span = expected[(expected >= bars.index[0]) & (expected <= as_of)]
        halt_slots[kind] = int(len(span) - len(bars))
    return {"monthly": monthly, "weekly": weekly, "halt_slots": halt_slots,
            "daily_max": daily.index.max()}


def select_samples(anchors, intervals, repository, calendar) -> tuple[list[dict], dict]:
    """First 9 passing hash-ordered candidates per anchor; no ticker is reused."""
    used: set[str] = set()
    samples: list[dict] = []
    audit: dict = {}
    for year, anchor in anchors:
        candidates = sorted(
            (s for s in common_segments_at(intervals, anchor) if s.ticker not in V01_TICKERS),
            key=lambda s: hash_key(anchor, s.ticker),
        )
        accepted = 0
        skips: dict[str, int] = {}
        skipped_before = 0
        for rank, segment in enumerate(candidates, start=1):
            if accepted == SAMPLES_PER_ANCHOR:
                break
            if segment.ticker in used:
                skips["already_selected"] = skips.get("already_selected", 0) + 1
                skipped_before += 1
                continue
            loader = RepositoryV2DailyLoader(
                repository, start=segment.effective_from.date().isoformat(), end=anchor
            )
            try:
                window = build_window(loader.load(segment.ticker), calendar, anchor)
            except CandidateSkip as exc:
                skips[str(exc)] = skips.get(str(exc), 0) + 1
                skipped_before += 1
                continue
            used.add(segment.ticker)
            accepted += 1
            samples.append({
                "ticker": segment.ticker, "anchor_year": year, "as_of": anchor.date().isoformat(),
                "selection_rank": rank, "skip_count_before_accept": skipped_before, **window,
            })
            skipped_before = 0
        if accepted != SAMPLES_PER_ANCHOR:
            raise SystemExit(f"CHECK_REQUIRED: anchor {year} filled {accepted}/{SAMPLES_PER_ANCHOR}")
        audit[str(year)] = {"candidates": len(candidates), "skips": skips}
    return samples, audit


def stock_names(metadata: pd.DataFrame, samples: list[dict]) -> None:
    for sample in samples:
        rows = metadata[metadata["ticker"] == sample["ticker"]].copy()
        rows["effective_date"] = pd.to_datetime(rows["effective_date"], errors="coerce")
        # PIT only: never borrow a name whose metadata starts after as_of.
        valid = rows[rows["effective_date"] <= pd.Timestamp(sample["as_of"])].sort_values("effective_date")
        sample["stock_name"] = str(valid["name"].iloc[-1]) if not valid.empty else ""


def assign_sample_ids(samples: list[dict], manifest_path: Path) -> None:
    keys = [(s["ticker"], s["as_of"]) for s in samples]
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8-sig") as fh:
            stored = {(r["ticker"], r["as_of"]): r["sample_id"] for r in csv.DictReader(fh)}
        if set(stored) != set(keys):
            raise SystemExit("CHECK_REQUIRED: existing private manifest differs from the selected sample set")
        mapping = stored
    else:
        order = list(keys)
        secrets.SystemRandom().shuffle(order)
        mapping = {key: f"{SAMPLE_PREFIX}{i:03d}" for i, key in enumerate(order, start=1)}
    for sample in samples:
        sample["sample_id"] = mapping[(sample["ticker"], sample["as_of"])]


def forbidden_pattern(samples: list[dict]) -> re.Pattern:
    tokens = {s["ticker"] for s in samples} | {s["stock_name"] for s in samples if s["stock_name"]}
    parts = [re.escape(t) for t in sorted(tokens, key=len, reverse=True)]
    parts.append(r"(19|20)\d{2}[-./]\d{1,2}")
    return re.compile("|".join(parts))


def _has_trailing_halt(sample: dict, calendar: pd.DatetimeIndex) -> bool:
    """True when the last completed calendar period before as_of has no bar (halted at as_of)."""
    exp_months, exp_weeks = v01.expected_period_labels(calendar, pd.Timestamp(sample["as_of"]))
    return sample["monthly"].index[-1] != exp_months[-1] or sample["weekly"].index[-1] != exp_weeks[-1]


def verify_pack(out_dir: Path, samples: list[dict], anchors, calendar: pd.DatetimeIndex,
                forbidden: re.Pattern, seal_text: str) -> dict:
    """Aggregate-only checks (no ticker, name, or as_of is written to the summary)."""
    from PIL import Image

    blind = out_dir / "blind"
    pngs = sorted(blind.glob("*.png"))
    sizes, meta_leaks = set(), 0
    for png in pngs:
        with Image.open(png) as img:
            sizes.add(img.size)
            meta_leaks += sum(1 for v in img.info.values() if isinstance(v, str) and forbidden.search(v))
    with zipfile.ZipFile(out_dir / ZIP_NAME) as zf:
        zip_names = zf.namelist()
    per_anchor = {str(y): sum(1 for s in samples if s["anchor_year"] == y) for y, _ in anchors}
    tickers = [s["ticker"] for s in samples]
    return {
        "sample_count": len(samples),
        "unique_tickers": len(set(tickers)),
        "per_anchor": per_anchor,
        "v01_ticker_overlap": len(set(tickers) & V01_TICKERS),
        "sample_ids_exact": sorted(s["sample_id"] for s in samples)
        == [f"{SAMPLE_PREFIX}{i:03d}" for i in range(1, 37)],
        "monthly_bar_counts": sorted({len(s["monthly"]) for s in samples}),
        "weekly_bar_counts": sorted({len(s["weekly"]) for s in samples}),
        "daily_after_as_of": sum(1 for s in samples if s["daily_max"] > pd.Timestamp(s["as_of"])),
        "bars_after_as_of": sum(
            int((s["monthly"].index > pd.Timestamp(s["as_of"])).sum())
            + int((s["weekly"].index > pd.Timestamp(s["as_of"])).sum())
            for s in samples
        ),
        "samples_with_halt_gaps": sum(1 for s in samples if any(s["halt_slots"].values())),
        "samples_with_trailing_halt": sum(1 for s in samples if _has_trailing_halt(s, calendar)),
        "png_count": len(pngs),
        "png_sizes": sorted(list(size) for size in sizes),
        "png_metadata_leaks": meta_leaks,
        "zip_entries": len(zip_names),
        "zip_name_leaks": sum(1 for n in zip_names if forbidden.search(n)),
        "zip_non_png_entries": sum(1 for n in zip_names if not n.endswith(".png")),
        "seal_leaks": 1 if forbidden.search(seal_text) else 0,
    }


EXPECTED_SUMMARY = {
    "sample_count": 36,
    "unique_tickers": 36,
    "per_anchor": {str(y): SAMPLES_PER_ANCHOR for y in ANCHOR_YEARS},
    "v01_ticker_overlap": 0,
    "sample_ids_exact": True,
    "monthly_bar_counts": [84],
    "weekly_bar_counts": [156],
    "daily_after_as_of": 0,
    "bars_after_as_of": 0,
    "samples_with_trailing_halt": 0,
    "png_count": 36,
    "png_sizes": [[1600, 1200]],
    "png_metadata_leaks": 0,
    "zip_entries": 36,
    "zip_name_leaks": 0,
    "zip_non_png_entries": 0,
    "seal_leaks": 0,
}
SEAL_FROZEN_KEYS = ("chart_pack_sha256", "private_manifest_sha256")


def assert_verification_summary(summary: dict) -> None:
    """Fail closed: every expected aggregate must match exactly."""
    mismatched = sorted(k for k, v in EXPECTED_SUMMARY.items() if summary.get(k) != v)
    if mismatched:
        raise SystemExit(f"CHECK_REQUIRED: verification failed: {mismatched}")


def finalize_seal(seal_path: Path, seal: dict, summary: dict) -> None:
    """Write the public seal only after verification passes and frozen hashes still match."""
    assert_verification_summary(summary)
    if seal_path.exists():
        existing = json.loads(seal_path.read_text(encoding="utf-8"))
        changed = [k for k in SEAL_FROZEN_KEYS if existing.get(k) != seal.get(k)]
        if changed:
            raise SystemExit(f"CHECK_REQUIRED: sealed hashes changed: {changed}")
    seal_path.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")


def ensure_manifest(manifest_path: Path, rows: list[dict]) -> bool:
    """Write a new manifest, or require the existing one to match exactly. Returns reused."""
    expected = [{k: str(v) for k, v in row.items()} for row in rows]
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8-sig") as fh:
            stored = list(csv.DictReader(fh))
        if stored != expected:
            raise SystemExit("CHECK_REQUIRED: private manifest content differs; not overwritten")
        return True
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.chmod(manifest_path, 0o600)
    return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repo root that holds data/market (read-only)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    parser.add_argument("--force", action="store_true", help="re-render; the stored mapping is kept")
    args = parser.parse_args()

    blind_dir = args.out_dir / "blind"
    private_dir = args.out_dir / "private"
    manifest_path = private_dir / "private_manifest.csv"
    if blind_dir.exists() and any(blind_dir.iterdir()) and not args.force:
        raise SystemExit(f"{blind_dir} already exists; pass --force to re-render with the same mapping")

    calendar = pd.DatetimeIndex(
        pd.read_parquet(ROOT / "data/reference/krx_trading_calendar.parquet")["trading_date"]
    ).normalize().sort_values()
    anchors = [(year, resolve_anchor(calendar, year)) for year in ANCHOR_YEARS]
    authority = load_effective_authority(ROOT / AUTHORITY_DIR)
    repository = build_repository_v2(args.data_root, end=max(a for _, a in anchors))
    samples, audit = select_samples(anchors, authority.pit_intervals, repository, calendar)
    stock_names(pd.read_parquet(ROOT / "data/reference/krx_instrument_metadata.parquet"), samples)

    private_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.out_dir, 0o700)
    os.chmod(private_dir, 0o700)
    blind_dir.mkdir(parents=True, exist_ok=True)
    assign_sample_ids(samples, manifest_path)
    samples.sort(key=lambda s: s["sample_id"])
    forbidden = forbidden_pattern(samples)

    rows = [{
        "sample_id": s["sample_id"], "ticker": s["ticker"], "stock_name": s["stock_name"],
        "anchor_year": s["anchor_year"], "as_of": s["as_of"],
        "monthly_first_date": s["monthly"].index[0].date().isoformat(),
        "monthly_last_date": s["monthly"].index[-1].date().isoformat(),
        "weekly_first_date": s["weekly"].index[0].date().isoformat(),
        "weekly_last_date": s["weekly"].index[-1].date().isoformat(),
        "selection_rank": s["selection_rank"], "skip_count_before_accept": s["skip_count_before_accept"],
    } for s in samples]
    manifest_reused = ensure_manifest(manifest_path, rows)

    for sample in samples:
        v01.render_sample(sample, blind_dir / f"{sample['sample_id']}.png", forbidden)
    for path in blind_dir.iterdir():
        os.utime(path, (0, 0))
    zip_path = args.out_dir / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sample in samples:
            name = f"{sample['sample_id']}.png"
            info = zipfile.ZipInfo(name, date_time=v01.ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (blind_dir / name).read_bytes())

    seal = {
        "version": "PATTERN_B_HOLDOUT_V02",
        "generator_version": GENERATOR_VERSION,
        "sample_count": len(samples),
        "unique_ticker_count": len({s["ticker"] for s in samples}),
        "anchor_years": list(ANCHOR_YEARS),
        "samples_per_anchor": SAMPLES_PER_ANCHOR,
        "sample_id_min": min(s["sample_id"] for s in samples),
        "sample_id_max": max(s["sample_id"] for s in samples),
        "chart_count": len(list(blind_dir.glob("*.png"))),
        "chart_pack_zip": ZIP_NAME,
        "chart_pack_sha256": _sha256(zip_path),
        "private_manifest_sha256": _sha256(manifest_path),
    }
    seal_text = json.dumps(seal, indent=2) + "\n"
    summary = verify_pack(args.out_dir, samples, anchors, calendar, forbidden, seal_text)
    _private_write(private_dir / "verification_summary.json", json.dumps(summary, indent=2))
    finalize_seal(args.seal, seal, summary)
    _private_write(private_dir / "selection_audit.json", json.dumps({
        "anchors": {str(y): a.date().isoformat() for y, a in anchors},
        "per_anchor": audit,
        "halt_slots": {s["sample_id"]: s["halt_slots"] for s in samples},
        "manifest_reused": manifest_reused,
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"seal": seal, "verification": summary,
                      "anchors": [a.date().isoformat() for _, a in anchors]}, indent=2))


if __name__ == "__main__":
    main()
