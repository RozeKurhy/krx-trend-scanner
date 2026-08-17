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
    MONTHLY_HISTORY_MIN_BARS,
    MONTHLY_HISTORY_OK,
    NOT_APPLICABLE,
    NOT_EVALUATED,
    UNLABELED,
    classify_source_reason,
    compute_reference_snapshot,
    find_base_reference_before_entry,
    first_stage_dates_after,
    load_raw_daily,
    make_sample_id,
    monthly_history_status,
    resolve_completed_weekly_reference,
    weekly_return_screen,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_pattern_a_fast_ground_truth")

BASE_COMMIT = "507b5675d480abdf9c8fc7d21355ba661afa94b7"
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
    "2024-09-27", "2024-12-27", "2025-03-28", "2025-06-27",
    "2025-09-26", "2025-12-26", "2026-03-27",
]
COHORT_B_TICKER_STRIDE = 1  # 전수 screen. 36개월 이력 게이트 도입 후 실측 결과
# 2016~2023 quarter-end에서 36개월 이력을 가진 티커가 전체 캐시 중 44~66개뿐인
# 근본적인 로컬 데이터 커버리지 한계가 확인됨(대부분 티커의 캐시 시작일이
# 최근 3년 내). stride로 표집하면 이 소수 후보군을 더 줄이므로 전수 screen으로
# 바꿔 존재하는 후보를 최대한 살린다 — quota를 억지로 맞추기 위한 것이 아니라
# 이미 있는 후보 풀을 stride로 인위적으로 줄이지 않기 위함(§8 "quota 최적화는
# 하지 말 것"과 구분됨).
#
# [correction] 36개월 게이트 도입 직후 실측 결과 2024-09-27 이전 quarter-end는
# eligible 티커가 400개 표본 중 3/175(약 1.7%)에 불과했지만, 2024-09-27부터는
# 표본 대비 약 70~80%(전체 환산 시 800개 이상)로 급증해 유지됨이 확인됨.
# 이 때문에 게이트 통과 후보가 사실상 2025-06-27 한 주에만 집중되어(Cohort B
# 45개 중 35개), FAILED_BREAKOUT/NEGATIVE_CONTROL 등 실패 사례 버킷들이
# "독립적인 여러 시점"이 아니라 "같은 한 시점"에 묶이는 문제가 발생함
# (advisor 리뷰로 발견). 이를 고치기 위해 이미 데이터가 풍부하게 존재하는
# 2024-09 ~ 2026-03 구간에 quarter-end 날짜를 추가로 넣어 후보 풀이 여러
# 주간에 걸쳐 분산되도록 함 — 고정된 bucket target 개수/규칙은 그대로이므로
# quota 최적화가 아니라 stride 완화와 같은 성격의 sampling frame 확장임.

cache = ParquetCache()
_daily_cache: dict[str, pd.DataFrame | None] = {}
excluded_candidates: list[dict] = []
cohort_b_selection_stats: dict[str, dict] = {}


def get_daily(ticker: str) -> pd.DataFrame | None:
    if ticker not in _daily_cache:
        _daily_cache[ticker] = load_raw_daily(ticker, cache)
    return _daily_cache[ticker]


def record_exclusion(
    ticker: str, candidate_date: pd.Timestamp | str | None, reason: str, cohort: str | None = None
) -> None:
    """Selection Manifest 재현성(§7)을 위해 후보가 최종 dataset에서 빠진
    이유를 machine-readable로 남긴다. 로그(logger)에만 의존하지 않는다."""
    excluded_candidates.append(
        {
            "ticker": ticker,
            "candidate_reference_date": (
                candidate_date.strftime("%Y-%m-%d")
                if isinstance(candidate_date, pd.Timestamp)
                else candidate_date
            ),
            "reason": reason,
            "cohort": cohort,
        }
    )


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
        record_exclusion(ticker, reference_date, DATA_UNAVAILABLE, source_cohort)
        logger.warning("  skip %s @ %s: %s", ticker, reference_date.date(), snap.data_status)
        return None

    # Monthly Review Data Sufficiency Gate: reference_date 시점 completed
    # monthly bars가 MONTHLY_HISTORY_MIN_BARS 미만이면 사람이 월봉에서
    # 장기 흐름을 판단할 수 없으므로 fail-closed 처리한다. Pattern A Fast
    # Feature/Threshold가 아니라 Human Review Data Quality 기준일 뿐이다.
    mh_status = monthly_history_status(snap.completed_monthly_bars)
    if mh_status != MONTHLY_HISTORY_OK:
        record_exclusion(ticker, reference_date, mh_status, source_cohort)
        logger.info(
            "  skip %s @ %s: %s (%s completed monthly bars < %d)",
            ticker, reference_date.date(), mh_status, snap.completed_monthly_bars, MONTHLY_HISTORY_MIN_BARS,
        )
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
        "completed_monthly_bars_at_reference": snap.completed_monthly_bars,
        "monthly_history_status": mh_status,
        "human_review_eligible": True,  # 이 함수까지 도달했다는 것 자체가 gate 통과를 의미
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
            record_exclusion(ticker, None, CACHE_MISSING, "PATTERN_A_HISTORICAL_CONTEXT")
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
            record_exclusion(
                ticker,
                entry_boundary.strftime("%Y-%m-%d") if entry_boundary is not None else None,
                "NO_PRE_EPISODE_BASE",
                "PATTERN_A_HISTORICAL_CONTEXT",
            )
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
            record_exclusion(ticker, None, CACHE_MISSING, "INDEPENDENT_NEGATIVE_AMBIGUOUS")
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
        picked_scores: list[float] = []
        for score, ticker, name, market, ref in candidates:
            if picked >= target:
                break
            if ticker_episode_count.get(ticker, 0) >= MAX_EPISODES_PER_TICKER:
                record_exclusion(ticker, ref, "MAX_EPISODES_PER_TICKER", bucket)
                continue
            daily = get_daily(ticker)
            row = build_row(ticker, name, market, ref, "INDEPENDENT_NEGATIVE_AMBIGUOUS", bucket, daily)
            if row is None:
                continue
            rows.append(row)
            ticker_episode_count[ticker] = ticker_episode_count.get(ticker, 0) + 1
            picked += 1
            picked_scores.append(score)
            logger.info("  + [%s] %s %s @ %s", bucket, ticker, name, ref.date())
        logger.info("  bucket %s: picked %d / target %d", bucket, picked, target)
        # 재현성(§7): top-N by |score| 선정은 후보 풀 크기와 cutoff score를
        # 알아야 manifest만으로 재현 가능하다(순위에서 밀린 후보는
        # excluded_candidates에 개별 기록되지 않으므로 이 요약이 필요).
        cohort_b_selection_stats[bucket] = {
            "candidate_pool_size": len(candidates),
            "target": target,
            "picked": picked,
            "score_cutoff_min": min(picked_scores) if picked_scores else None,
            "score_cutoff_max": max(picked_scores) if picked_scores else None,
        }
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
                record_exclusion(ticker, r["reference_date"], "NEAR_DUPLICATE", r["source_cohort"])
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
        "completed_monthly_bars_at_reference", "monthly_history_status", "human_review_eligible",
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
                    "순서로 순회하며, frozen Pattern A evaluator로 2026-08-14부터 gap-tolerant "
                    "backward 탐색(비-TRANSITION/EARLY_TREND 주가 gap_tolerance_weeks=4 연속 "
                    "나올 때까지는 산발적 1~3주 dip을 무시)으로 현재 episode의 entry_boundary를 "
                    "찾고, 그보다 최소 min_lead_weeks=12주(=Cohort B lookahead 창과 동일, "
                    "reviewability 필터일 뿐 Fast Trigger threshold 아님) 이전 최대 104주 "
                    "이내에서 forward로 confirm_pre_episode_weeks=4주 연속 TRANSITION/ "
                    "EARLY_TREND가 아님을 확인한 BASE 완료 주봉을 reference_date로 사용(episode "
                    "내부의 1주짜리 dip을 pre-episode로 오인하는 것 방지, 2차 correction에서 "
                    "발견/수정). entry_boundary 시점 stage가 early_trend면 PATTERN_A_PRE_EARLY, "
                    "아니면 PATTERN_A_PRE_TRANSITION. 조건을 만족하는 BASE가 없으면 skip하고 "
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
                "selection_stats_per_bucket": cohort_b_selection_stats,
            },
            "max_episodes_per_ticker": MAX_EPISODES_PER_TICKER,
            "min_gap_weeks_same_ticker": 8,
        },
        "monthly_review_data_sufficiency_gate": {
            "description": (
                "reference_date 시점 completed monthly bars가 min_bars 미만이면 "
                "MONTHLY_HISTORY_INSUFFICIENT로 fail-closed 처리하고 dataset에서 제외한다. "
                "Pattern A Fast Feature/Threshold가 아니라 '월봉에서 장기 흐름을 사람이 "
                "실제로 판단할 수 있는가'를 보장하는 Human Review Data Quality 기준이다 "
                "(monthly_history_status, src/trend_scanner/validation/"
                "pattern_a_fast_ground_truth.py)."
            ),
            "min_bars": MONTHLY_HISTORY_MIN_BARS,
        },
        "included_samples": len(all_rows),
        "included_sample_ids": sample_ids,
        "excluded_candidates": excluded_candidates,
        "excluded_candidates_count": len(excluded_candidates),
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

    monthly_bars = source_df["completed_monthly_bars_at_reference"]
    gate_failures = sum(1 for e in excluded_candidates if e["reason"] == "MONTHLY_HISTORY_INSUFFICIENT")

    logger.info("==================================================")
    logger.info("Total samples: %d (Cohort A: %d, Cohort B: %d)", len(all_rows), len(rows_a), len(rows_b))
    logger.info("Unique tickers: %d", len({r["ticker"] for r in all_rows}))
    logger.info("Market: %s", pd.DataFrame(all_rows)["market"].value_counts().to_dict())
    logger.info("Source reason distribution: %s", pd.DataFrame(all_rows)["source_reason"].value_counts().to_dict())
    logger.info("Reference date range: %s ~ %s", min(r["reference_date"] for r in all_rows), max(r["reference_date"] for r in all_rows))
    logger.info("Reference year distribution: %s", pd.to_datetime(source_df["reference_date"]).dt.year.value_counts().sort_index().to_dict())
    logger.info("Completed monthly bars min/median/max: %d / %.1f / %d", monthly_bars.min(), monthly_bars.median(), monthly_bars.max())
    logger.info("Monthly history gate (%dM) failures during selection: %d", MONTHLY_HISTORY_MIN_BARS, gate_failures)
    logger.info("Excluded candidates total: %d", len(excluded_candidates))
    logger.info("Source CSV: %s (%d rows)", source_path, len(source_df))
    logger.info("Human Review Worksheet: %s (%d rows)", review_path, len(review_df))
    logger.info("Manifest: %s", manifest_path)
    logger.info("Reserved calibration samples: %s", reserved_path)
    logger.info("==================================================")


if __name__ == "__main__":
    main()
