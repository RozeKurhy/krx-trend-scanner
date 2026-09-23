#!/usr/bin/env python3
"""Pattern B Human Ground Truth V01 blind chart pack generator.

Contract: docs/patterns/pattern_b/validation/chart_pack_v01.md

- Fixed 12 tickers x 3 as-of dates (36 samples); backups only on data/identity gaps.
  Trading halts are not a replacement reason: halted periods are skipped.
- Completed bars only: 84 monthly + 156 weekly per sample, from Repository V2
  adjusted prices loaded with ``end=as_of`` (no row after as_of is read).
- No Pattern B feature, future return, or pattern evaluator is computed or imported.
- The blind permutation is drawn once with ``secrets`` and stored only under
  ``private/``; reruns reuse it so the mapping is never derivable from the repo.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import re
import secrets
import sys
import warnings
import zipfile

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.text import Text
import pandas as pd
from PIL import Image

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.resampler import to_monthly, to_weekly


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "artifacts/pattern_b_hgt_v01"

PRIMARY_TICKERS: tuple[tuple[str, str], ...] = (
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("005380", "현대차"),
    ("035420", "NAVER"),
    ("051910", "LG화학"),
    ("005490", "POSCO홀딩스"),
    ("068270", "셀트리온"),
    ("090430", "아모레퍼시픽"),
    ("011200", "HMM"),
    ("034020", "두산에너빌리티"),
    ("086520", "에코프로"),
    ("035900", "JYP Ent."),
)
BACKUP_TICKERS: tuple[tuple[str, str], ...] = (
    ("003490", "대한항공"),
    ("010950", "S-Oil"),
    ("017670", "SK텔레콤"),
    ("009150", "삼성전기"),
)
AS_OF_DATES: tuple[str, ...] = ("2021-06-30", "2023-06-30", "2025-06-30")
MONTHLY_BARS = 84
WEEKLY_BARS = 156
SAMPLE_PREFIX = "PBHGT_"
ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)

MANIFEST_FIELDS = (
    "sample_id", "ticker", "stock_name", "as_of",
    "monthly_first_date", "monthly_last_date", "weekly_first_date", "weekly_last_date",
)
TEMPLATE_FIELDS = ("sample_id", "label", "confidence", "note")


class DataGapError(RuntimeError):
    """Required history is unavailable; the whole ticker moves to the next backup."""


class ContiguityError(RuntimeError):
    """Bars do not line up with KRX calendar periods; requires a human decision."""


def completed_bars(daily: pd.DataFrame, as_of: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return monthly/weekly bars whose calendar period ended on or before ``as_of``.

    Periods with no session for this ticker (a trading halt) produce no bar and
    are skipped rather than drawn as gaps.
    """
    monthly = to_monthly(daily).dropna(subset=["close"])
    weekly = to_weekly(daily).dropna(subset=["close"])
    return monthly[monthly.index <= as_of], weekly[weekly.index <= as_of]


def expected_period_labels(calendar: pd.DatetimeIndex, as_of: pd.Timestamp) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Calendar period labels that contain at least one KRX session, completed by ``as_of``."""
    sessions = pd.Series(1, index=calendar[calendar <= as_of])
    months = sessions.resample(pd.offsets.MonthEnd()).count()
    weeks = sessions.resample("W-FRI").count()
    months = months[(months > 0) & (months.index <= as_of)].index
    weeks = weeks[(weeks > 0) & (weeks.index <= as_of)].index
    return months, weeks


def build_window(
    loader: RepositoryV2DailyLoader,
    calendar: pd.DatetimeIndex,
    ticker: str,
    as_of: pd.Timestamp,
) -> dict:
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        raise DataGapError(f"{ticker} {as_of.date()}: Repository V2 returned no data")
    if daily.index.max() > as_of:
        raise AssertionError(f"{ticker}: loader returned rows after as_of")
    monthly, weekly = completed_bars(daily, as_of)
    if len(monthly) < MONTHLY_BARS or len(weekly) < WEEKLY_BARS:
        raise DataGapError(
            f"{ticker} {as_of.date()}: completed monthly={len(monthly)} weekly={len(weekly)}"
        )
    monthly = monthly.iloc[-MONTHLY_BARS:]
    weekly = weekly.iloc[-WEEKLY_BARS:]

    # Every bar must be a KRX calendar period; periods inside the window with no
    # session for this ticker are halts that were skipped (recorded privately).
    exp_months, exp_weeks = expected_period_labels(calendar, as_of)
    skipped: dict[str, int] = {}
    for kind, bars, expected in (("monthly", monthly, exp_months), ("weekly", weekly, exp_weeks)):
        span = expected[(expected >= bars.index[0]) & (expected <= bars.index[-1])]
        if not bars.index.isin(span).all() or bars.index[-1] != expected[-1]:
            raise ContiguityError(f"{ticker} {as_of.date()}: {kind} bars differ from KRX calendar periods")
        skipped[kind] = int(len(span) - len(bars))
        if bars[["open", "high", "low", "close"]].isna().any().any():
            raise AssertionError(f"{ticker} {as_of.date()}: NaN OHLC inside {kind} window")

    window_start = min(monthly.index[0], weekly.index[0]) - pd.offsets.MonthBegin(1)
    cal_sessions = calendar[(calendar > window_start) & (calendar <= as_of)]
    stock_sessions = daily.index[daily.index > window_start]
    summary = daily.attrs.get("session_projection_summary", {})
    return {
        "monthly": monthly,
        "weekly": weekly,
        "daily_max_date": daily.index.max().date().isoformat(),
        "missing_calendar_sessions_in_window": int(len(cal_sessions.difference(stock_sessions))),
        "repository_explicit_exclusion_count": int(summary.get("explicit_exclusion_count", 0) or 0),
        "halt_skipped_months": skipped["monthly"],
        "halt_skipped_weeks": skipped["weekly"],
    }


def select_samples(loader_for, calendar: pd.DatetimeIndex) -> tuple[list[dict], list[dict]]:
    """Resolve the fixed 12 tickers, replacing a whole ticker only on data gaps."""
    backups = list(BACKUP_TICKERS)
    samples: list[dict] = []
    replacements: list[dict] = []
    for ticker, name in PRIMARY_TICKERS:
        candidate = (ticker, name)
        while True:
            try:
                windows = [
                    build_window(loader_for[a], calendar, candidate[0], pd.Timestamp(a))
                    for a in AS_OF_DATES
                ]
                break
            except DataGapError as exc:
                if not backups:
                    raise SystemExit(f"backup list exhausted: {exc}")
                nxt = backups.pop(0)
                replacements.append({"replaced": candidate[0], "by": nxt[0], "reason": str(exc)})
                candidate = nxt
        for as_of, window in zip(AS_OF_DATES, windows):
            samples.append({"ticker": candidate[0], "stock_name": candidate[1], "as_of": as_of, **window})
    return samples, replacements


def assign_sample_ids(samples: list[dict], manifest_path: Path) -> None:
    """Reuse a stored private mapping, otherwise draw one permutation with ``secrets``."""
    keys = [(s["ticker"], s["as_of"]) for s in samples]
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8-sig") as fh:
            stored = {(r["ticker"], r["as_of"]): r["sample_id"] for r in csv.DictReader(fh)}
        if set(stored) != set(keys):
            raise SystemExit("existing private manifest does not match the fixed sample set")
        mapping = stored
    else:
        order = list(keys)
        secrets.SystemRandom().shuffle(order)
        mapping = {key: f"{SAMPLE_PREFIX}{i:03d}" for i, key in enumerate(order, start=1)}
    for sample in samples:
        sample["sample_id"] = mapping[(sample["ticker"], sample["as_of"])]


def _draw_candles(ax, bars: pd.DataFrame) -> None:
    """Monochrome candles on integer x positions; bars are already display-normalized."""
    width = 0.6
    for x, row in enumerate(bars.itertuples(index=False)):
        up = row.close >= row.open
        ax.vlines(x, row.low, row.high, color="#222222", linewidth=0.8, zorder=1)
        bottom = min(row.open, row.close)
        height = max(abs(row.close - row.open), 1e-9)
        ax.add_patch(Rectangle(
            (x - width / 2, bottom), width, height,
            facecolor="#ffffff" if up else "#222222",
            edgecolor="#222222", linewidth=0.7, zorder=2,
        ))
    low, high = float(bars["low"].min()), float(bars["high"].max())
    pad = (high - low) * 0.04 or 1.0
    ax.set_xlim(-1, len(bars))
    ax.set_ylim(low - pad, high + pad)
    ax.set_xticks([])
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def normalize_for_display(bars: pd.DataFrame) -> pd.DataFrame:
    """Scale OHLC so the first visible close is 100. Display only; never stored."""
    base = float(bars["close"].iloc[0])
    return (bars[["open", "high", "low", "close"]] / base * 100.0).reset_index(drop=True)


def render_sample(sample: dict, path: Path, forbidden: re.Pattern) -> None:
    fig, (ax_m, ax_w) = plt.subplots(
        2, 1, figsize=(16, 12), dpi=100, gridspec_kw={"height_ratios": [1, 1]}
    )
    # Fixed margins (no tight bbox) so every PNG has identical pixel size and layout.
    fig.subplots_adjust(left=0.05, right=0.99, top=0.94, bottom=0.03, hspace=0.14)
    _draw_candles(ax_m, normalize_for_display(sample["monthly"]))
    _draw_candles(ax_w, normalize_for_display(sample["weekly"]))
    ax_m.set_title(f"MONTHLY — {MONTHLY_BARS} completed bars", loc="left", fontsize=12)
    ax_w.set_title(f"WEEKLY — {WEEKLY_BARS} completed bars", loc="left", fontsize=12)
    fig.suptitle(sample["sample_id"], x=0.99, y=0.99, ha="right", fontsize=11, color="#555555")
    fig.canvas.draw()
    texts = [t.get_text() for t in fig.findobj(Text) if t.get_text()]
    leaked = [t for t in texts if forbidden.search(t)]
    if leaked:
        raise AssertionError(f"{sample['sample_id']}: identifying text on chart: {leaked}")
    fig.savefig(path, format="png", metadata={"Software": None})
    plt.close(fig)


def forbidden_pattern(samples: list[dict]) -> re.Pattern:
    tokens = {s["ticker"] for s in samples} | {s["stock_name"] for s in samples}
    tokens |= {t for t, _ in PRIMARY_TICKERS + BACKUP_TICKERS} | {n for _, n in PRIMARY_TICKERS + BACKUP_TICKERS}
    parts = [re.escape(t) for t in sorted(tokens, key=len, reverse=True)]
    parts.append(r"(19|20)\d{2}[-./]\d{1,2}")
    return re.compile("|".join(parts))


def verify_pack(out_dir: Path, samples: list[dict], forbidden: re.Pattern) -> dict:
    blind = out_dir / "blind"
    pngs = sorted(blind.glob("*.png"))
    with (blind / "annotation_template.csv").open(encoding="utf-8-sig") as fh:
        template_rows = list(csv.DictReader(fh))
    with (out_dir / "private/private_manifest.csv").open(encoding="utf-8-sig") as fh:
        manifest_rows = list(csv.DictReader(fh))
    metadata_leaks = 0
    for png in pngs:
        with Image.open(png) as img:
            chunks = {**getattr(img, "text", {}), **img.info}
        metadata_leaks += sum(1 for v in chunks.values() if isinstance(v, str) and forbidden.search(v))
    with zipfile.ZipFile(out_dir / "pattern_b_hgt_v01_blind_pack.zip") as zf:
        zip_names = zf.namelist()
    name_leaks = sum(1 for n in [p.name for p in blind.iterdir()] + zip_names if forbidden.search(n))
    loaded_modules = sorted(m for m in sys.modules if m.startswith("trend_scanner."))
    pattern_modules = [m for m in loaded_modules if ".patterns" in m or ".validation" in m or ".strateg" in m]
    return {
        "blind_png_count": len(pngs),
        "annotation_template_rows": len(template_rows),
        "annotation_template_prefilled_fields": sum(
            1 for r in template_rows for k in ("label", "confidence", "note") if r[k]
        ),
        "private_manifest_rows": len(manifest_rows),
        "monthly_bar_counts": sorted({len(s["monthly"]) for s in samples}),
        "weekly_bar_counts": sorted({len(s["weekly"]) for s in samples}),
        "rows_after_as_of": sum(1 for s in samples if s["daily_max_date"] > s["as_of"]),
        "bars_after_as_of": sum(
            int((s["monthly"].index > pd.Timestamp(s["as_of"])).sum())
            + int((s["weekly"].index > pd.Timestamp(s["as_of"])).sum())
            for s in samples
        ),
        "png_metadata_identifier_leaks": metadata_leaks,
        "file_name_identifier_leaks": name_leaks,
        "zip_entries": len(zip_names),
        "zip_contains_private": sum(1 for n in zip_names if "private" in n or "manifest" in n),
        "pattern_feature_modules_loaded": pattern_modules,
        "future_return_computed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repo root that holds data/market and data/reference (read-only)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--force", action="store_true",
                        help="re-render an existing pack; the stored sample_id mapping is kept")
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    blind_dir = out_dir / "blind"
    private_dir = out_dir / "private"
    manifest_path = private_dir / "private_manifest.csv"
    if blind_dir.exists() and any(blind_dir.iterdir()) and not args.force:
        raise SystemExit(f"{blind_dir} already exists; pass --force to re-render with the same mapping")

    calendar = pd.DatetimeIndex(
        pd.read_parquet(args.data_root / "data/reference/krx_trading_calendar.parquet")["trading_date"]
    ).normalize().sort_values()
    repository = build_repository_v2(args.data_root, end=max(AS_OF_DATES))
    loader_for = {a: RepositoryV2DailyLoader(repository, end=a) for a in AS_OF_DATES}

    samples, replacements = select_samples(loader_for, calendar)
    private_dir.mkdir(parents=True, exist_ok=True)
    blind_dir.mkdir(parents=True, exist_ok=True)
    assign_sample_ids(samples, manifest_path)
    samples.sort(key=lambda s: s["sample_id"])
    forbidden = forbidden_pattern(samples)

    for sample in samples:
        render_sample(sample, blind_dir / f"{sample['sample_id']}.png", forbidden)
    with (blind_dir / "annotation_template.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(TEMPLATE_FIELDS)
        writer.writerows([s["sample_id"], "", "", ""] for s in samples)
    # Uniform mtimes so file timestamps carry no ordering signal.
    for path in blind_dir.iterdir():
        os.utime(path, (0, 0))

    with manifest_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for s in samples:
            writer.writerow({
                "sample_id": s["sample_id"], "ticker": s["ticker"], "stock_name": s["stock_name"],
                "as_of": s["as_of"],
                "monthly_first_date": s["monthly"].index[0].date().isoformat(),
                "monthly_last_date": s["monthly"].index[-1].date().isoformat(),
                "weekly_first_date": s["weekly"].index[0].date().isoformat(),
                "weekly_last_date": s["weekly"].index[-1].date().isoformat(),
            })
    (private_dir / "sample_detail.json").write_text(json.dumps({
        "replacements": replacements,
        "samples": [
            {k: s[k] for k in ("sample_id", "ticker", "as_of", "daily_max_date",
                               "missing_calendar_sessions_in_window", "repository_explicit_exclusion_count",
                               "halt_skipped_months", "halt_skipped_weeks")}
            for s in samples
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = out_dir / "pattern_b_hgt_v01_blind_pack.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        names = [f"{s['sample_id']}.png" for s in samples] + ["annotation_template.csv"]
        for name in names:
            info = zipfile.ZipInfo(f"blind/{name}", date_time=ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (blind_dir / name).read_bytes())

    summary = verify_pack(out_dir, samples, forbidden)
    summary["replacement_count"] = len(replacements)
    summary["samples_with_halt_skipped_periods"] = sum(
        1 for s in samples if s["halt_skipped_months"] or s["halt_skipped_weeks"]
    )
    summary["ticker_count"] = len({s["ticker"] for s in samples})
    summary["sample_count"] = len(samples)
    (out_dir / "verification_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
