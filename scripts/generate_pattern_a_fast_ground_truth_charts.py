#!/usr/bin/env python
"""Phase 13C — Chart Review Packet Generator (PIT / Outcome, blind-review safe).

Reads the source dataset produced by prepare_pattern_a_fast_ground_truth.py
and renders per-sample PNG charts:

    {sample_id}_monthly_pit.png
    {sample_id}_weekly_pit.png
    {sample_id}_daily_pit.png
    {sample_id}_weekly_outcome.png

PIT charts contain no data after reference_date (machine-checked in
build_chart_slices via assert). Outcome charts additionally show data up to
outcome_review_end and mark reference_date with a vertical line so a human
reviewer can see where PIT ended (§26/§27). No Feature is highlighted beyond
price + volume/trading_value — deliberately plain, per §46.

Usage:
    uv run python scripts/generate_pattern_a_fast_ground_truth_charts.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# 종목명(한글) 렌더링을 위한 폰트 지정 — 이 macOS 환경에 설치된 AppleGothic 사용.
# 없는 환경에서는 기본 폰트로 자동 폴백(글자가 네모로 깨지는 대신 기본 sans-serif).
plt.rcParams["font.family"] = ["AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from trend_scanner.data.cache import ParquetCache  # noqa: E402
from trend_scanner.validation.pattern_a_fast_ground_truth import (  # noqa: E402
    build_chart_slices,
    load_raw_daily,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_pattern_a_fast_ground_truth_charts")

SOURCE_CSV = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv")
CHART_DIR = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/charts")
CHART_SUFFIXES = ("_monthly_pit.png", "_weekly_pit.png", "_daily_pit.png", "_weekly_outcome.png")


def expected_chart_filenames(sample_ids: list[str]) -> set[str]:
    """source CSV의 sample_id 목록으로부터 있어야 할 PNG 파일명 전체 집합을 계산한다.
    idempotent 재생성/orphan cleanup(§8)의 기준이 되는 순수 함수."""
    return {f"{sid}{suf}" for sid in sample_ids for suf in CHART_SUFFIXES}


def remove_orphan_charts(chart_dir: Path, expected: set[str]) -> list[str]:
    """expected set에 없는 기존 PNG를 삭제하고, 삭제한 파일명 목록을 반환한다.
    sample 구성이 바뀌어도(예: 58->57 tickers) charts/에 이전 sample의 PNG가
    남아있지 않도록 한다(§8 idempotent 요구사항)."""
    if not chart_dir.exists():
        return []
    removed = []
    for p in chart_dir.glob("*.png"):
        if p.name not in expected:
            p.unlink()
            removed.append(p.name)
    return removed


def _plot_price_volume(df: pd.DataFrame, title: str, ref_line: pd.Timestamp | None, out_path: Path) -> None:
    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(8, 5), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    if not df.empty:
        ax_price.plot(df.index, df["close"], color="#2c6fbb", linewidth=1.2)
        ax_vol.bar(df.index, df["volume"], color="#8a8a8a", width=3.5)
    if ref_line is not None:
        for ax in (ax_price, ax_vol):
            ax.axvline(ref_line, color="#c0392b", linestyle="--", linewidth=1.0)
    ax_price.set_title(title, fontsize=10)
    ax_price.set_ylabel("close")
    ax_vol.set_ylabel("volume")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def main() -> None:
    if not SOURCE_CSV.exists():
        raise SystemExit(f"Source dataset not found: {SOURCE_CSV}. Run preparation script first.")

    df = pd.read_csv(SOURCE_CSV, dtype={"ticker": str})
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    cache = ParquetCache()

    expected = expected_chart_filenames(df.loc[df["data_status"] == "OK", "sample_id"].tolist())
    removed_orphans = remove_orphan_charts(CHART_DIR, expected)
    if removed_orphans:
        logger.info("  removed %d orphan chart(s) not in current sample set", len(removed_orphans))

    generated = 0
    skipped = 0
    for _, row in df.iterrows():
        if row["data_status"] != "OK":
            skipped += 1
            continue
        ticker = row["ticker"]
        sample_id = row["sample_id"]
        reference_date = pd.Timestamp(row["reference_date"])
        outcome_end = pd.Timestamp(row["outcome_review_end"])

        daily = load_raw_daily(ticker, cache)
        if daily is None:
            logger.warning("  CACHE_MISSING for chart: %s", ticker)
            skipped += 1
            continue

        slices = build_chart_slices(daily, reference_date, outcome_end)

        _plot_price_volume(
            slices.monthly_pit,
            f"{sample_id} {row['name']} — Monthly PIT (<= {reference_date.date()})",
            None,
            CHART_DIR / f"{sample_id}_monthly_pit.png",
        )
        _plot_price_volume(
            slices.weekly_pit,
            f"{sample_id} {row['name']} — Weekly PIT (<= {reference_date.date()})",
            None,
            CHART_DIR / f"{sample_id}_weekly_pit.png",
        )
        _plot_price_volume(
            slices.daily_pit,
            f"{sample_id} {row['name']} — Daily PIT (<= {reference_date.date()})",
            None,
            CHART_DIR / f"{sample_id}_daily_pit.png",
        )
        _plot_price_volume(
            slices.weekly_outcome,
            f"{sample_id} {row['name']} — Weekly Outcome (<= {outcome_end.date()}, ref={reference_date.date()})",
            reference_date,
            CHART_DIR / f"{sample_id}_weekly_outcome.png",
        )
        generated += 1

    actual = {p.name for p in CHART_DIR.glob("*.png")}
    orphans = actual - expected
    missing = expected - actual
    total_bytes = sum((CHART_DIR / name).stat().st_size for name in actual)

    logger.info("==================================================")
    logger.info("Charts generated for %d samples (skipped %d)", generated, skipped)
    logger.info("Chart files: %d, total size: %.2f MB", len(actual), total_bytes / 1e6)
    logger.info("Orphan charts: %d, Missing charts: %d", len(orphans), len(missing))
    if orphans:
        logger.warning("  orphan files: %s", sorted(orphans))
    if missing:
        logger.warning("  missing files: %s", sorted(missing))
    logger.info("Chart dir: %s", CHART_DIR)
    logger.info("==================================================")


if __name__ == "__main__":
    main()
