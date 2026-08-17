#!/usr/bin/env python
"""Phase 13C — Pattern A Fast Human Ground Truth Dataset Preparation (13C-1).

Selects diverse historical PIT reference samples for later Human Chart
Annotation (13C-2). Does NOT assign weekly_stage_at_reference or
human_label — those stay UNLABELED for a human to fill in.

Data access is cache-only (no network). Cohort A samples come from the
existing Phase 8 universe scan's real current CANDIDATE tickers, walked
backward in time with the frozen Pattern A evaluator to find a real BASE
reference point before their (real, already-observed) transition.

Cohort B is split into two sampling strata (Phase 13C-1 Final Sampling
Balance Correction):
  - RECENT_SYSTEMATIC: quarter-end date grid over 2024-09~2026-03, bucketed
    by classify_source_reason and picked top-N by |return| score per bucket.
  - HISTORICAL_COVERAGE: a handful of pre-2024 quarter-end dates where the
    local cache still has enough tickers with >=36 completed monthly bars,
    picked by a stable hash of sample_id (NOT by return magnitude) so
    selection probability is independent of forward outcome.

Both strata use the same fixed classify_source_reason rule — sampling only,
not a Fast Trigger rule.

Usage:
    uv run python scripts/prepare_pattern_a_fast_ground_truth.py
"""

from __future__ import annotations

import hashlib
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

BASE_COMMIT = "5d8af8245fedd5591595d91d06e3b333938e0ff7"
AS_OF = "2026-08-14"
DATA_CUTOFF = pd.Timestamp("2026-08-14")
SCANNER_CSV = Path("artifacts/scanner/pattern_a_universe_scan_20260814.csv")
OUTPUT_DIR = Path("artifacts/pattern_a_fast/ground_truth")

COHORT_A_TARGET = 15
MAX_EPISODES_PER_TICKER = 2

VALID_SOURCE_REASONS = frozenset(
    {
        "FAILED_BREAKOUT",
        "LONG_DOWNTREND_BOUNCE",
        "STRONG_UPTREND_ALREADY_EXTENDED",
        "NEGATIVE_CONTROL",
        "RANGE_BOUND",
        "AMBIGUOUS_STRUCTURE",
    }
)

# --- Cohort B: RECENT_SYSTEMATIC stratum -----------------------------------
# 직전 correction에서 2016~2023 quarter-end는 36개월 게이트 통과 티커가
# 400개 표본 중 3~66개뿐인 반면 2024-09-27부터는 800개 이상으로 급증함이
# 확인됨. 그 결과 top-N by score 선정이 사실상 최근 구간 한 주(2025-06-27)
# 에만 몰리는 문제가 advisor 리뷰로 발견됐고(Cohort B 45개 중 35개), 날짜
# 그리드를 2024-09~2026-03으로 넓혀 35/45→18/45로 개선했었다. 이번
# correction([Phase 13C-1 Final Sampling Balance Correction] w.md)에서는
# 이 stratum을 "Recent Regime Pool"로 명확히 하고, 별도의
# HISTORICAL_COVERAGE stratum(아래)을 추가해 2024-09 이전 시장 국면도
# dataset에 실제로 존재하도록 한다 — RECENT_SYSTEMATIC 자체의 선정 방식
# (quarter-end 날짜 그리드 + 버킷별 top-N by |return| score)은 그대로 둔다.
RECENT_COHORT_B_DATES = [
    "2024-09-27", "2024-12-27", "2025-03-28", "2025-06-27",
    "2025-09-26", "2025-12-26", "2026-03-27",
]
RECENT_COHORT_B_TARGETS = {
    "FAILED_BREAKOUT": 7,
    "LONG_DOWNTREND_BOUNCE": 4,
    "STRONG_UPTREND_ALREADY_EXTENDED": 6,
    "NEGATIVE_CONTROL": 6,
    "RANGE_BOUND": 4,
    "AMBIGUOUS_STRUCTURE": 6,
}  # 이전 버전(10/5/8/8/6/8=45) 대비 Historical Coverage stratum에 자리를
# 내주기 위해 동일 비율로 축소(45→33). 정확한 숫자를 최적화한 것이 아니라
# Cohort B 총량을 45 근처로 유지하면서 "일부만 historical로 교체"하기
# 위한 비례 축소일 뿐이다(w.md §1·§4).

# --- Cohort B: HISTORICAL_COVERAGE stratum ----------------------------------
# 2024-09 이전 실제 market regime 사례를 최소 몇 개 연도에 걸쳐 포함하기
# 위한 별도 stratum. 후보는 outcome extreme score top-N으로 뽑지 않는다
# (w.md §3) — 그러면 선정 확률이 forward return 크기 자체에 좌우되어 다시
# 같은 종류의 편향이 생기기 때문. 대신 date+source_reason eligibility를
# 만든 뒤 sample_id의 stable hash로 정렬해 상위 N개를 뽑는다(가격/수익률과
# 무관한 순서). 아래 4개 날짜는 2016~2023 quarter-end 중 실제 eligible
# pool(36개월 게이트 통과 + 유효 source_reason 분류)이 존재하는 지점을
# 사전 실측(400개 표본 스크리닝)으로 확인해 2018/2020/2022/2023 각 연도
# 하나씩 고른 것이다(w.md가 예시로 든 연도와 동일). 이 pool은 원래
# 얇다 — 그 자체는 제외 사유가 아니며(w.md §3), manifest에 pool 크기를
# 그대로 기록한다.
HISTORICAL_COVERAGE_DATES = [
    "2018-06-29", "2020-09-25", "2022-12-30", "2023-06-30",
]
HISTORICAL_COVERAGE_TARGET_PER_DATE = 3  # 날짜당 목표. 얇은 pool에서는 이보다
# 적게 뽑힐 수 있고, 그 경우도 정직하게 그대로 보고한다(연도 quota를
# 억지로 채우지 않는다, w.md §2·§4).

COHORT_B_TICKER_STRIDE = 1  # 전수 screen (두 stratum 공통). 36개월 이력
# 게이트 도입 후 실측 결과 2016~2023년의 eligible 티커가 전체 캐시 중
# 소수뿐인 근본적인 로컬 데이터 커버리지 한계가 확인되어(대부분 티커의
# 캐시 시작일이 최근 3년 내), stride로 후보를 더 줄이지 않기 위해 전수
# screen을 쓴다 — quota를 억지로 맞추기 위한 것이 아니라 존재하는 후보를
# stride로 인위적으로 줄이지 않기 위함(§8 "quota 최적화는 하지 말 것"과
# 구분됨).

cache = ParquetCache()
_daily_cache: dict[str, pd.DataFrame | None] = {}
excluded_candidates: list[dict] = []
recent_selection_stats: dict[str, dict] = {}
historical_selection_stats: dict[str, dict] = {}


def _stable_hash_key(sample_id: str) -> int:
    """sample_id 기반 stable hash — historical stratum 선정 순서를 가격/수익률과
    완전히 무관하게 만든다(deterministic, forward return magnitude와 무관, w.md §3).
    """
    return int(hashlib.sha256(sample_id.encode("utf-8")).hexdigest(), 16)


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


def select_recent_cohort_b(scanner_df: pd.DataFrame, ticker_episode_count: dict[str, int]) -> list[dict]:
    logger.info("== Cohort B: RECENT_SYSTEMATIC stratum ==")
    universe = scanner_df[scanner_df["cache_present"] == True].sort_values("ticker").reset_index(drop=True)  # noqa: E712
    screen_tickers = universe.iloc[::COHORT_B_TICKER_STRIDE]
    logger.info("  screening %d tickers x %d dates", len(screen_tickers), len(RECENT_COHORT_B_DATES))

    bucketed: dict[str, list[tuple]] = {k: [] for k in RECENT_COHORT_B_TARGETS}
    for _, cand in screen_tickers.iterrows():
        ticker, name, market = cand["ticker"], cand["name"], cand["market"]
        daily = get_daily(ticker)
        if daily is None:
            record_exclusion(ticker, None, CACHE_MISSING, "RECENT_SYSTEMATIC")
            continue
        for date_str in RECENT_COHORT_B_DATES:
            ref = resolve_completed_weekly_reference(ticker, name, daily, date_str)
            if ref is None:
                continue
            metrics = weekly_return_screen(daily, ref)
            if metrics is None:
                continue
            bucket = classify_source_reason(metrics)
            if bucket not in RECENT_COHORT_B_TARGETS:
                continue
            score = abs(metrics["trailing_return"]) + abs(metrics["forward_return"])
            bucketed[bucket].append((score, ticker, name, market, ref))

    rows: list[dict] = []
    for bucket, target in RECENT_COHORT_B_TARGETS.items():
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
            row = build_row(ticker, name, market, ref, "RECENT_SYSTEMATIC", bucket, daily)
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
        recent_selection_stats[bucket] = {
            "candidate_pool_size": len(candidates),
            "target": target,
            "picked": picked,
            "score_cutoff_min": min(picked_scores) if picked_scores else None,
            "score_cutoff_max": max(picked_scores) if picked_scores else None,
        }
    return rows


def select_historical_coverage_cohort_b(
    scanner_df: pd.DataFrame, ticker_episode_count: dict[str, int]
) -> list[dict]:
    """RECENT_SYSTEMATIC과 별개로, 2024-09 이전 실제 market regime 사례를
    포함하기 위한 stratum. Outcome extreme score top-N을 쓰지 않고
    sample_id의 stable hash로 순서를 정해 선택한다 — forward return 크기가
    선정 확률을 결정하지 않도록 하기 위함(w.md §3)."""
    logger.info("== Cohort B: HISTORICAL_COVERAGE stratum ==")
    universe = scanner_df[scanner_df["cache_present"] == True].sort_values("ticker").reset_index(drop=True)  # noqa: E712

    rows: list[dict] = []
    for date_str in HISTORICAL_COVERAGE_DATES:
        eligible: list[tuple] = []
        for _, cand in universe.iterrows():
            ticker, name, market = cand["ticker"], cand["name"], cand["market"]
            daily = get_daily(ticker)
            if daily is None:
                continue
            ref = resolve_completed_weekly_reference(ticker, name, daily, date_str)
            if ref is None:
                continue
            # weekly_return_screen은 lookback/lookahead 12주(~6개월)만 있으면 통과하므로
            # 캐시가 최근에 시작된 티커도 대부분 통과한다 — 여기서 36개월 게이트를
            # 미리 걸지 않으면 "eligible pool" 크기가 실제보다 크게 부풀려진다(예:
            # 2022-12-30에서 weekly screen만 걸렀을 때 2148개였지만, 36개월 게이트까지
            # 적용하면 실제로는 수십 개 수준으로 얇음). build_row가 나중에 어차피
            # 게이트를 적용하지만, pool 크기 자체를 정직하게 보고하려면(w.md §3) 여기서도
            # 미리 걸러야 한다.
            snap = compute_reference_snapshot(ticker, name, daily, ref)
            if monthly_history_status(snap.completed_monthly_bars) != MONTHLY_HISTORY_OK:
                continue
            metrics = weekly_return_screen(daily, ref)
            if metrics is None:
                continue
            bucket = classify_source_reason(metrics)
            if bucket not in VALID_SOURCE_REASONS:
                continue
            sample_id = make_sample_id(ticker, ref)
            eligible.append((sample_id, ticker, name, market, ref, bucket))

        # deterministic, 가격/수익률과 무관한 정렬(w.md §3) — sorted()는 stable하므로
        # 동일 hash key가 나올 일이 없는 한(사실상 불가능) 실행마다 동일한 순서.
        eligible.sort(key=lambda x: _stable_hash_key(x[0]))
        logger.info(
            "  %s: eligible pool=%d (얇은 pool 자체는 exclusion 사유 아님, w.md §3)",
            date_str, len(eligible),
        )

        picked = 0
        for sample_id, ticker, name, market, ref, bucket in eligible:
            if picked >= HISTORICAL_COVERAGE_TARGET_PER_DATE:
                break
            if ticker_episode_count.get(ticker, 0) >= MAX_EPISODES_PER_TICKER:
                record_exclusion(ticker, ref, "MAX_EPISODES_PER_TICKER", "HISTORICAL_COVERAGE")
                continue
            daily = get_daily(ticker)
            row = build_row(ticker, name, market, ref, "HISTORICAL_COVERAGE", bucket, daily)
            if row is None:
                continue
            rows.append(row)
            ticker_episode_count[ticker] = ticker_episode_count.get(ticker, 0) + 1
            picked += 1
            logger.info("  + [HISTORICAL/%s] %s %s @ %s (hash-selected)", bucket, ticker, name, ref.date())
        logger.info(
            "  %s: picked %d / target %d (eligible pool=%d)",
            date_str, picked, HISTORICAL_COVERAGE_TARGET_PER_DATE, len(eligible),
        )
        historical_selection_stats[date_str] = {
            "eligible_pool_size": len(eligible),
            "target_per_date": HISTORICAL_COVERAGE_TARGET_PER_DATE,
            "picked": picked,
            "selection_method": "deterministic_stable_hash(sample_id)",
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
    cohort_b_ticker_episode_count: dict[str, int] = {}
    rows_b_recent = select_recent_cohort_b(scanner_df, cohort_b_ticker_episode_count)
    rows_b_historical = select_historical_coverage_cohort_b(scanner_df, cohort_b_ticker_episode_count)
    all_rows = rows_a + rows_b_recent + rows_b_historical
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
            "cohort_b_recent_systematic": {
                "name": "RECENT_SYSTEMATIC",
                "description": (
                    "cache_present 티커를 stride "
                    f"{COHORT_B_TICKER_STRIDE}로 표집한 뒤 quarter-end 날짜 그리드 "
                    f"{RECENT_COHORT_B_DATES} 각각에서 weekly_return_screen 지표를 계산하고 "
                    "classify_source_reason (src/trend_scanner/validation/"
                    "pattern_a_fast_ground_truth.py)의 고정 규칙으로 버킷팅. "
                    "버킷당 |trailing_return|+|forward_return| 기준 상위 N개 선택 "
                    "(Recent Regime Pool — 2024-09~2026-03만 대상)."
                ),
                "targets": RECENT_COHORT_B_TARGETS,
                "selected": len(rows_b_recent),
                "selection_stats_per_bucket": recent_selection_stats,
            },
            "cohort_b_historical_coverage": {
                "name": "HISTORICAL_COVERAGE",
                "description": (
                    "2024-09 이전 quarter-end 날짜 "
                    f"{HISTORICAL_COVERAGE_DATES} 각각에서 cache_present 티커 전수를 "
                    "screen해 36개월 게이트 + classify_source_reason 유효 버킷을 만족하는 "
                    "eligible pool을 만든 뒤, sample_id의 stable hash(sha256) 순서로 "
                    f"날짜당 상위 {HISTORICAL_COVERAGE_TARGET_PER_DATE}개를 선택. "
                    "Outcome extreme score top-N을 쓰지 않으므로 선정 확률이 forward "
                    "return 크기에 좌우되지 않는다(w.md §3). Pool이 얇은 것 자체는 "
                    "exclusion 사유가 아니며 eligible_pool_size를 그대로 기록한다(w.md §3)."
                ),
                "target_per_date": HISTORICAL_COVERAGE_TARGET_PER_DATE,
                "selected": len(rows_b_historical),
                "selection_stats_per_date": historical_selection_stats,
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
    date_counts = source_df["reference_date"].value_counts()
    max_date_count = int(date_counts.max())
    max_date_share = max_date_count / len(source_df)

    logger.info("==================================================")
    logger.info(
        "Total samples: %d (Cohort A: %d, Recent B: %d, Historical B: %d)",
        len(all_rows), len(rows_a), len(rows_b_recent), len(rows_b_historical),
    )
    logger.info("Unique tickers: %d", len({r["ticker"] for r in all_rows}))
    logger.info("Market: %s", pd.DataFrame(all_rows)["market"].value_counts().to_dict())
    logger.info("Source cohort distribution: %s", pd.DataFrame(all_rows)["source_cohort"].value_counts().to_dict())
    logger.info("Source reason distribution: %s", pd.DataFrame(all_rows)["source_reason"].value_counts().to_dict())
    logger.info("Reference date range: %s ~ %s", min(r["reference_date"] for r in all_rows), max(r["reference_date"] for r in all_rows))
    logger.info("Reference year distribution: %s", pd.to_datetime(source_df["reference_date"]).dt.year.value_counts().sort_index().to_dict())
    logger.info("Exact reference_date distribution: %s", date_counts.sort_index().to_dict())
    logger.info("Max single reference_date count/share: %d / %.1f%%", max_date_count, max_date_share * 100)
    logger.info("Completed monthly bars min/median/max: %d / %.1f / %d", monthly_bars.min(), monthly_bars.median(), monthly_bars.max())
    logger.info("Monthly history gate (%dM) failures during selection: %d", MONTHLY_HISTORY_MIN_BARS, gate_failures)
    logger.info("Excluded candidates total: %d", len(excluded_candidates))
    logger.info("Historical coverage eligible pool per date: %s", historical_selection_stats)
    logger.info("Source CSV: %s (%d rows)", source_path, len(source_df))
    logger.info("Human Review Worksheet: %s (%d rows)", review_path, len(review_df))
    logger.info("Manifest: %s", manifest_path)
    logger.info("Reserved calibration samples: %s", reserved_path)
    logger.info("==================================================")


if __name__ == "__main__":
    main()
