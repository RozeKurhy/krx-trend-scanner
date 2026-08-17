#!/usr/bin/env python
"""Phase 13C — Pattern A Fast Human Ground Truth Dataset Preparation (13C-1).

Selects diverse historical PIT reference samples for later Human Chart
Annotation (13C-2). Does NOT assign weekly_stage_at_reference or
human_label — those stay UNLABELED for a human to fill in.

Data access is cache-only (no network). Cohort A samples come from the
existing Phase 8 universe scan's real current CANDIDATE tickers, walked
backward in time with the frozen Pattern A evaluator to find a real BASE
reference point before their (real, already-observed) transition. Cohort B
samples come from a deterministic systematic ticker sample scored with
simple descriptive return metrics (see classify_source_reason in
src/trend_scanner/validation/pattern_a_fast_ground_truth.py for the exact,
fixed rule) — sampling only, not a Fast Trigger rule.

Usage:
    uv run python scripts/prepare_pattern_a_fast_ground_truth.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.pattern_a_fast_ground_truth import (
    CACHE_MISSING,
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    NOT_EVALUATED,
    UNLABELED,
    classify_source_reason,
    compute_reference_snapshot,
    find_base_reference_before_entry,
    first_stage_dates_after,
    load_raw_daily,
    make_sample_id,
    resolve_completed_weekly_reference,
    weekly_return_screen,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_pattern_a_fast_ground_truth")

BASE_COMMIT = "e8cf7e6ee9585e8cc512e6cbe488eaa000497518"
AS_OF = "2026-08-14"
DATA_CUTOFF = pd.Timestamp("2026-08-14")
SCANNER_CSV = Path("artifacts/scanner/pattern_a_universe_scan_20260814.csv")
OUTPUT_DIR = Path("artifacts/pattern_a_fast/ground_truth")

COHORT_A_TARGET = 15
COHORT_B_TARGETS = {
    "FAILED_BREAKOUT": 10,
    "LONG_DOWNTREND_BOUNCE": 5,
    "STRONG_UPTREND_ALREADY_EXTENDED": 8,
    "NEGATIVE_CONTROL": 8,
    "RANGE_BOUND": 6,
    "AMBIGUOUS_STRUCTURE": 8,
}
MAX_EPISODES_PER_TICKER = 2
COHORT_B_DATES = [
    "2016-06-30", "2017-06-30", "2018-06-29", "2018-12-28",
    "2019-06-28", "2020-03-27", "2020-09-25", "2021-06-25",
    "2022-06-24", "2022-12-30", "2023-06-30", "2024-06-28",
    "2025-06-27",
]
COHORT_B_TICKER_STRIDE = 8  # 2528 / 8 ≈ 316 tickers screened

cache = ParquetCache()
_daily_cache: dict[str, pd.DataFrame | None] = {}


def get_daily(ticker: str) -> pd.DataFrame | None:
    if ticker not in _daily_cache:
        _daily_cache[ticker] = load_raw_daily(ticker, cache)
    return _daily_cache[ticker]


def build_row(
    ticker: str,
    name: str,
    market: str,
    reference_date: pd.Timestamp,
    source_cohort: str,
    source_reason: str,
    daily: pd.DataFrame,
) -> dict | None:
    snap = compute_reference_snapshot(ticker, name, daily, reference_date)
    if snap.data_status != "OK":
        logger.warning("  skip %s @ %s: %s", ticker, reference_date.date(), snap.data_status)
        return None

    t_first, e_first = first_stage_dates_after(ticker, name, daily, reference_date, horizon_weeks=104)

    return {
        "sample_id": make_sample_id(ticker, reference_date),
        "episode_id": None,  # filled after dedup/sort per ticker
        "ticker": ticker,
        "name": name,
        "market": market,
        "reference_date": reference_date.strftime("%Y-%m-%d"),
        "source_cohort": source_cohort,
        "source_reason": source_reason,
        "weekly_stage_at_reference": UNLABELED,
        "trigger_event_observed": UNLABELED,
        "trigger_event_date": "",
        "human_label": UNLABELED,
        "human_confidence": "",
        "human_notes": "",
        "pattern_a_stage_at_reference": snap.pattern_a_stage,
        "pattern_a_candidate_state_at_reference": snap.pattern_a_candidate_state,
        "pattern_a_score_at_reference": snap.pattern_a_score,
        "pattern_a_transition_first_after_reference": (
            t_first if isinstance(t_first, str) else t_first.strftime("%Y-%m-%d")
        ),
        "pattern_a_early_trend_first_after_reference": (
            e_first if isinstance(e_first, str) else e_first.strftime("%Y-%m-%d")
        ),
        "lead_weeks_to_pattern_a_transition": NOT_EVALUATED,
        "lead_weeks_to_pattern_a_early_trend": NOT_EVALUATED,
        "pit_data_start": str(daily.index.min().date()),
        "pit_data_end": reference_date.strftime("%Y-%m-%d"),
        "outcome_review_end": min(
            reference_date + pd.Timedelta(weeks=52), daily.index.max()
        ).strftime("%Y-%m-%d"),
        "data_status": "OK",
        "quality_flags": "",
    }


COHORT_A_MIN_LEAD_WEEKS = 12  # Cohort B lookahead horizon과 동일 — 관찰 가능한 최소 리뷰 창 확보용 필터, Fast Trigger threshold 아님


def select_cohort_a(scanner_df: pd.DataFrame) -> list[dict]:
    logger.info("== Cohort A: Pattern A Historical Context ==")
    candidates = scanner_df[scanner_df["candidate_state"] == "candidate"].copy()
    candidates = candidates.sort_values("ticker").reset_index(drop=True)

    rows: list[dict] = []
    skipped_no_base = 0
    for _, cand in candidates.iterrows():
        if len(rows) >= COHORT_A_TARGET:
            break
        ticker, name, market = cand["ticker"], cand["name"], cand["market"]
        daily = get_daily(ticker)
        if daily is None:
            continue

        # entry_boundary(현재 episode가 TRANSITION/EARLY_TREND로 진입한 첫
        # 완료 주봉)를 찾고, 그보다 최소 COHORT_A_MIN_LEAD_WEEKS 이전에 실제
        # BASE였던 완료 주봉을 reference_date로 쓴다 — "entry 바로 직전 BASE"
        # 를 쓰면 관측 가능한 lead time이 구조적으로 12주 미만으로 눌리고
        # Outcome 리뷰 창도 너무 짧아지므로(둘 다 같은 원인), 12주 버퍼를
        # 강제한다.
        found, entry_boundary, entry_stage = find_base_reference_before_entry(
            ticker, name, daily, DATA_CUTOFF, min_lead_weeks=COHORT_A_MIN_LEAD_WEEKS, max_lookback_weeks=104
        )
        if found is None:
            skipped_no_base += 1
            logger.info(
                "  %s: no BASE >= %dw before entry_boundary=%s, skip",
                ticker, COHORT_A_MIN_LEAD_WEEKS, entry_boundary.date() if entry_boundary is not None else None,
            )
            continue

        source_reason = "PATTERN_A_PRE_EARLY" if entry_stage == "early_trend" else "PATTERN_A_PRE_TRANSITION"
        row = build_row(ticker, name, market, found, "PATTERN_A_HISTORICAL_CONTEXT", source_reason, daily)
        if row:
            lead_weeks = (entry_boundary - found).days // 7
            rows.append(row)
            logger.info(
                "  + %s %s @ %s (BASE, entry_boundary=%s, lead=%dw, %s)",
                ticker, name, found.date(), entry_boundary.date(), lead_weeks, source_reason,
            )
    logger.info("  Cohort A: picked %d / target %d (skipped_no_base=%d)", len(rows), COHORT_A_TARGET, skipped_no_base)
    return rows


def select_cohort_b(scanner_df: pd.DataFrame) -> list[dict]:
    logger.info("== Cohort B: Independent Negative / Ambiguous Cohort ==")
    universe = scanner_df[scanner_df["cache_present"] == True].sort_values("ticker").reset_index(drop=True)  # noqa: E712
    screen_tickers = universe.iloc[::COHORT_B_TICKER_STRIDE]
    logger.info("  screening %d tickers x %d dates", len(screen_tickers), len(COHORT_B_DATES))

    bucketed: dict[str, list[tuple]] = {k: [] for k in COHORT_B_TARGETS}
    for _, cand in screen_tickers.iterrows():
        ticker, name, market = cand["ticker"], cand["name"], cand["market"]
        daily = get_daily(ticker)
        if daily is None:
            continue
        for date_str in COHORT_B_DATES:
            ref = resolve_completed_weekly_reference(ticker, name, daily, date_str)
            if ref is None:
                continue
            metrics = weekly_return_screen(daily, ref)
            if metrics is None:
                continue
            bucket = classify_source_reason(metrics)
            if bucket not in COHORT_B_TARGETS:
                continue
            score = abs(metrics["trailing_return"]) + abs(metrics["forward_return"])
            bucketed[bucket].append((score, ticker, name, market, ref))

    rows: list[dict] = []
    ticker_episode_count: dict[str, int] = {}
    for bucket, target in COHORT_B_TARGETS.items():
        candidates = sorted(bucketed[bucket], key=lambda x: -x[0])
        picked = 0
        for score, ticker, name, market, ref in candidates:
            if picked >= target:
                break
            if ticker_episode_count.get(ticker, 0) >= MAX_EPISODES_PER_TICKER:
                continue
            daily = get_daily(ticker)
            row = build_row(ticker, name, market, ref, "INDEPENDENT_NEGATIVE_AMBIGUOUS", bucket, daily)
            if row is None:
                continue
            rows.append(row)
            ticker_episode_count[ticker] = ticker_episode_count.get(ticker, 0) + 1
            picked += 1
            logger.info("  + [%s] %s %s @ %s", bucket, ticker, name, ref.date())
        logger.info("  bucket %s: picked %d / target %d", bucket, picked, target)
    return rows


def assign_episode_ids(rows: list[dict]) -> None:
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    for ticker, group in by_ticker.items():
        group.sort(key=lambda r: r["reference_date"])
        for i, r in enumerate(group, start=1):
            r["episode_id"] = f"{ticker}_E{i:02d}"


def dedupe_near_duplicates(rows: list[dict], min_gap_weeks: int = 8) -> list[dict]:
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    kept: list[dict] = []
    for ticker, group in by_ticker.items():
        group.sort(key=lambda r: r["reference_date"])
        last_date = None
        for r in group:
            d = pd.Timestamp(r["reference_date"])
            if last_date is not None and (d - last_date).days < min_gap_weeks * 7:
                continue
            kept.append(r)
            last_date = d
    return kept


def main() -> None:
    scanner_df = pd.read_csv(SCANNER_CSV, dtype={"ticker": str})
    logger.info("Loaded scanner universe: %d rows", len(scanner_df))

    rows_a = select_cohort_a(scanner_df)
    rows_b = select_cohort_b(scanner_df)
    all_rows = rows_a + rows_b
    all_rows = dedupe_near_duplicates(all_rows)
    all_rows.sort(key=lambda r: (r["ticker"], r["reference_date"]))
    assign_episode_ids(all_rows)

    sample_ids = [r["sample_id"] for r in all_rows]
    assert len(sample_ids) == len(set(sample_ids)), "duplicate sample_id detected"

    source_columns = [
        "sample_id", "episode_id", "ticker", "name", "market", "reference_date",
        "source_cohort", "source_reason",
        "weekly_stage_at_reference", "trigger_event_observed", "trigger_event_date",
        "human_label", "human_confidence", "human_notes",
        "pattern_a_stage_at_reference", "pattern_a_candidate_state_at_reference",
        "pattern_a_score_at_reference",
        "pattern_a_transition_first_after_reference", "pattern_a_early_trend_first_after_reference",
        "lead_weeks_to_pattern_a_transition", "lead_weeks_to_pattern_a_early_trend",
        "pit_data_start", "pit_data_end", "outcome_review_end",
        "data_status", "quality_flags",
    ]
    review_columns = [
        "sample_id", "ticker", "name", "reference_date",
        "weekly_stage_at_reference", "trigger_event_observed", "trigger_event_date",
        "human_label", "human_confidence", "human_notes",
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_df = pd.DataFrame(all_rows)[source_columns]
    review_df = pd.DataFrame(all_rows)[review_columns]

    source_path = OUTPUT_DIR / "pattern_a_fast_ground_truth_source_v01.csv"
    review_path = OUTPUT_DIR / "pattern_a_fast_human_review_v01.csv"
    source_df.to_csv(source_path, index=False)
    review_df.to_csv(review_path, index=False)

    manifest = {
        "phase": "13C-1",
        "base_commit": BASE_COMMIT,
        "as_of": AS_OF,
        "data_cutoff": AS_OF,
        "network_requests": 0,
        "source_datasets": [str(SCANNER_CSV)],
        "selection_strategy": {
            "cohort_a": {
                "name": "PATTERN_A_HISTORICAL_CONTEXT",
                "description": (
                    "artifacts/scanner/pattern_a_universe_scan_20260814.csv 의 실제 "
                    "candidate_state=='candidate'(TRANSITION/EARLY_TREND) 티커를 ticker "
                    "순서로 순회하며, frozen Pattern A evaluator로 2026-08-14부터 backward "
                    "탐색해 현재 episode의 entry_boundary(TRANSITION/EARLY_TREND 최초 진입 "
                    "완료 주봉)를 찾고, 그보다 최소 12주(=Cohort B lookahead 창과 동일, "
                    "reviewability 필터일 뿐 Fast Trigger threshold 아님) 이전 최대 104주 "
                    "이내에서 실제 BASE였던 완료 주봉을 reference_date로 사용. entry_boundary "
                    "시점 stage가 early_trend면 PATTERN_A_PRE_EARLY, 아니면 "
                    "PATTERN_A_PRE_TRANSITION. 12주 버퍼를 만족하는 BASE가 없으면 skip하고 "
                    "다음 후보로 top-up (find_base_reference_before_entry, "
                    "src/trend_scanner/validation/pattern_a_fast_ground_truth.py)."
                ),
                "target": COHORT_A_TARGET,
                "selected": len(rows_a),
            },
            "cohort_b": {
                "name": "INDEPENDENT_NEGATIVE_AMBIGUOUS",
                "description": (
                    "cache_present 티커를 stride "
                    f"{COHORT_B_TICKER_STRIDE}로 표집한 뒤 quarter-end 날짜 그리드 "
                    f"{COHORT_B_DATES} 각각에서 weekly_return_screen 지표를 계산하고 "
                    "classify_source_reason (src/trend_scanner/validation/"
                    "pattern_a_fast_ground_truth.py)의 고정 규칙으로 버킷팅. "
                    "버킷당 |trailing_return|+|forward_return| 기준 상위 N개 선택."
                ),
                "targets": COHORT_B_TARGETS,
                "selected": len(rows_b),
            },
            "max_episodes_per_ticker": MAX_EPISODES_PER_TICKER,
            "min_gap_weeks_same_ticker": 8,
        },
        "included_samples": len(all_rows),
        "excluded_reasons": "생략된 candidate는 DATA_UNAVAILABLE 또는 BASE 미발견(backward 104주 이내)으로 로그에만 기록, dataset에는 포함하지 않음",
    }
    manifest_path = OUTPUT_DIR / "selection_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    reserved = {
        "phase": "13C-1",
        "purpose": "Phase 13I OOS Validation에서 재사용 금지할 calibration sample 목록",
        "samples": [
            {"ticker": r["ticker"], "reference_date": r["reference_date"], "sample_id": r["sample_id"]}
            for r in all_rows
        ],
    }
    reserved_path = OUTPUT_DIR / "reserved_calibration_samples.json"
    reserved_path.write_text(json.dumps(reserved, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("==================================================")
    logger.info("Total samples: %d (Cohort A: %d, Cohort B: %d)", len(all_rows), len(rows_a), len(rows_b))
    logger.info("Unique tickers: %d", len({r["ticker"] for r in all_rows}))
    logger.info("Market: %s", pd.DataFrame(all_rows)["market"].value_counts().to_dict())
    logger.info("Source reason distribution: %s", pd.DataFrame(all_rows)["source_reason"].value_counts().to_dict())
    logger.info("Reference date range: %s ~ %s", min(r["reference_date"] for r in all_rows), max(r["reference_date"] for r in all_rows))
    logger.info("Source CSV: %s (%d rows)", source_path, len(source_df))
    logger.info("Human Review Worksheet: %s (%d rows)", review_path, len(review_df))
    logger.info("Manifest: %s", manifest_path)
    logger.info("Reserved calibration samples: %s", reserved_path)
    logger.info("==================================================")


if __name__ == "__main__":
    main()
