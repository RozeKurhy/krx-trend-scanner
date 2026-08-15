"""Pattern A Real Candidate Chart Review v0.1 Dataset Preparation & Workflow Module.

Extracts CANDIDATE state stocks from Full Universe Scanner artifacts,
validates strict dataset integrity & source lock provenance,
and prepares Manual Chart Review datasets with human annotation columns
and dynamic workflow summary recalculation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.universe.models import AssetType, MarketType

logger = logging.getLogger(__name__)

# Manual Review Column 초기값 정의
DEFAULT_REVIEW_STATUS = "UNREVIEWED"
DEFAULT_MANUAL_PATTERN_FIT = "UNREVIEWED"
DEFAULT_MANUAL_STAGE_FIT = "UNREVIEWED"

# Manual Review 허용 Vocabulary
ALLOWED_REVIEW_STATUS = {"UNREVIEWED", "REVIEWED"}
ALLOWED_MANUAL_PATTERN_FIT = {"UNREVIEWED", "GOOD_FIT", "BORDERLINE", "NOT_FIT", "UNCERTAIN"}
ALLOWED_MANUAL_STAGE_FIT = {"UNREVIEWED", "MATCH", "TOO_EARLY", "TOO_LATE", "UNCLEAR"}

MANUAL_REVIEW_COMPACT_COLUMNS = [
    # Provenance Tracking
    "scanner_commit",
    "scanner_as_of",
    "source_artifact",
    # Identity & Market
    "ticker",
    "name",
    "market",
    "asset_type",
    "requested_as_of",
    # Core Scanner Measurements
    "official_stage",
    "candidate_state",
    "pattern_a_score",
    "score_delta_1m",
    "score_delta_3m",
    "score_delta_6m",
    "freshness_status",
    "quality_flags",
    # Diagnostic Subscores
    "base_score",
    "transition_score",
    "balanced_core_score",
    "alignment_bonus",
    "progressed_penalty",
    # Manual Chart Review Annotation Columns (Empty / UNREVIEWED)
    "review_status",
    "monthly_structure",
    "weekly_structure",
    "daily_entry_context",
    "manual_pattern_fit",
    "manual_stage_fit",
    "manual_notes",
]


@dataclass(frozen=True)
class CandidateReviewSummary:
    """Manual Chart Review 진행 현황 및 Stage별 집계 Summary."""

    scanner_commit: str
    scanner_as_of: str
    source_artifact: str

    total_candidates: int
    transition_total: int
    early_trend_total: int

    reviewed_count: int
    unreviewed_count: int

    good_fit_count: int
    borderline_count: int
    not_fit_count: int
    uncertain_count: int

    # Stage Breakdown
    transition_reviewed: int
    transition_good_fit: int
    transition_borderline: int
    transition_not_fit: int
    transition_uncertain: int

    early_trend_reviewed: int
    early_trend_good_fit: int
    early_trend_borderline: int
    early_trend_not_fit: int
    early_trend_uncertain: int

    def to_dict(self) -> dict[str, Any]:
        """Summary 딕셔너리 직렬화."""
        return asdict(self)


class CandidateReviewIntegrityError(Exception):
    """Candidate Review Dataset 무결성 위반 예외."""


def extract_and_prepare_candidate_review(
    scanner_df: pd.DataFrame,
    as_of: str = "2026-08-14",
    scanner_commit: str = "13ab6f4",
    source_artifact_name: str = "pattern_a_universe_scan_20260814.csv",
) -> tuple[pd.DataFrame, pd.DataFrame, CandidateReviewSummary]:
    """Scanner 결과 DataFrame에서 Candidate 종목을 추출하고 Review Dataset을 구성한다.

    Returns:
        tuple[source_df, manual_review_df, summary]
    """
    # 1. Candidate State 필터링 (candidate_state == 'candidate')
    cand_mask = scanner_df["candidate_state"].astype(str).str.lower() == "candidate"
    candidates = scanner_df[cand_mask].copy()

    # 2. Strict Integrity Checks
    # 2.1 중복 종목 차단
    dup_tickers = candidates[candidates["ticker"].duplicated()]["ticker"].tolist()
    if dup_tickers:
        raise CandidateReviewIntegrityError(f"Duplicate candidate tickers found: {dup_tickers}")

    # 2.2 Asset Type 검증 (100% COMMON 이어야 함)
    non_common = candidates[candidates["asset_type"] != AssetType.COMMON.value]
    if not non_common.empty:
        raise CandidateReviewIntegrityError(
            f"Non-COMMON assets found in candidate list: {non_common['ticker'].tolist()}"
        )

    # 2.3 Official Stage 검증 (TRANSITION 또는 EARLY_TREND 이어야 함)
    allowed_stages = {PatternAStage.TRANSITION.value, PatternAStage.EARLY_TREND.value}
    invalid_stages = candidates[~candidates["official_stage"].isin(allowed_stages)]
    if not invalid_stages.empty:
        raise CandidateReviewIntegrityError(
            f"Invalid stages found in candidates: {invalid_stages[['ticker', 'official_stage']].to_dict('records')}"
        )

    # 2.4 Readiness 검증 (score_ready == True, evaluator_ready == True)
    if "score_ready" in candidates.columns:
        not_score_ready = candidates[candidates["score_ready"] != True]
        if not not_score_ready.empty:
            raise CandidateReviewIntegrityError(
                f"Candidates with score_ready=False: {not_score_ready['ticker'].tolist()}"
            )
    if "evaluator_ready" in candidates.columns:
        not_eval_ready = candidates[candidates["evaluator_ready"] != True]
        if not not_eval_ready.empty:
            raise CandidateReviewIntegrityError(
                f"Candidates with evaluator_ready=False: {not_eval_ready['ticker'].tolist()}"
            )

    # 3. Deterministic Non-Ranking 정렬: (official_stage, market, ticker)
    candidates.sort_values(
        by=["official_stage", "market", "ticker"],
        ascending=[True, True, True],
        inplace=True,
    )
    candidates.reset_index(drop=True, inplace=True)

    # 4. Provenance Metadata 주입
    candidates["scanner_commit"] = str(scanner_commit)
    candidates["scanner_as_of"] = str(as_of)
    candidates["source_artifact"] = str(source_artifact_name)

    # 5. Source DataFrame 준비 (Scanner 전체 원본 필드 보존 + Provenance)
    source_df = candidates.copy()

    # 6. Manual Review DataFrame 준비 (Compact Columns + Human Annotation Columns)
    available_cols = [c for c in MANUAL_REVIEW_COMPACT_COLUMNS if c in candidates.columns]
    manual_review_df = candidates[available_cols].copy()

    # Manual 컬럼 초기값 설정
    manual_review_df["review_status"] = DEFAULT_REVIEW_STATUS
    manual_review_df["monthly_structure"] = ""
    manual_review_df["weekly_structure"] = ""
    manual_review_df["daily_entry_context"] = ""
    manual_review_df["manual_pattern_fit"] = DEFAULT_MANUAL_PATTERN_FIT
    manual_review_df["manual_stage_fit"] = DEFAULT_MANUAL_STAGE_FIT
    manual_review_df["manual_notes"] = ""

    # 컬럼 순서 정렬
    target_cols = [c for c in MANUAL_REVIEW_COMPACT_COLUMNS if c in manual_review_df.columns]
    manual_review_df = manual_review_df[target_cols]

    # 7. Summary 객체 생성
    total_cand = len(candidates)
    trans_total = int(sum(candidates["official_stage"] == PatternAStage.TRANSITION.value))
    early_total = int(sum(candidates["official_stage"] == PatternAStage.EARLY_TREND.value))

    summary = CandidateReviewSummary(
        scanner_commit=str(scanner_commit),
        scanner_as_of=str(as_of),
        source_artifact=str(source_artifact_name),
        total_candidates=total_cand,
        transition_total=trans_total,
        early_trend_total=early_total,
        reviewed_count=0,
        unreviewed_count=total_cand,
        good_fit_count=0,
        borderline_count=0,
        not_fit_count=0,
        uncertain_count=0,
        transition_reviewed=0,
        transition_good_fit=0,
        transition_borderline=0,
        transition_not_fit=0,
        transition_uncertain=0,
        early_trend_reviewed=0,
        early_trend_good_fit=0,
        early_trend_borderline=0,
        early_trend_not_fit=0,
        early_trend_uncertain=0,
    )

    return source_df, manual_review_df, summary


def summarize_manual_review(
    manual_review_df: pd.DataFrame,
    scanner_commit: str | None = None,
    scanner_as_of: str | None = None,
    source_artifact: str | None = None,
) -> CandidateReviewSummary:
    """사용자가 수동으로 작성한 Manual Review DataFrame의 진행 현황을 집계한다.

    Note:
        인간이 입력한 값을 단순히 집계하며, 자동 판단이나 랭킹/필터링을 일체 수행하지 않는다.
    """
    total_cand = len(manual_review_df)

    # Provenance 추출
    commit = str(scanner_commit or manual_review_df.get("scanner_commit", ["UNKNOWN"])[0])
    as_of = str(scanner_as_of or manual_review_df.get("scanner_as_of", ["UNKNOWN"])[0])
    source_art = str(source_artifact or manual_review_df.get("source_artifact", ["UNKNOWN"])[0])

    # Reviewed 여부 판정: review_status == 'REVIEWED' 또는 manual_pattern_fit != 'UNREVIEWED'
    is_reviewed_mask = (
        (manual_review_df["review_status"].astype(str).str.upper() == "REVIEWED")
        | (manual_review_df["manual_pattern_fit"].astype(str).str.upper() != "UNREVIEWED")
    )
    reviewed_cnt = int(is_reviewed_mask.sum())
    unreviewed_cnt = total_cand - reviewed_cnt

    # Consistency Validation Logging
    inconsistent_unrev = manual_review_df[
        (manual_review_df["review_status"].astype(str).str.upper() == "REVIEWED")
        & (manual_review_df["manual_pattern_fit"].astype(str).str.upper() == "UNREVIEWED")
    ]
    if not inconsistent_unrev.empty:
        logger.warning(
            "Found %d rows with review_status=REVIEWED but manual_pattern_fit=UNREVIEWED (e.g. tickers: %s)",
            len(inconsistent_unrev),
            inconsistent_unrev["ticker"].tolist()[:5],
        )

    # Overall Pattern Fit 집계
    fit_series = manual_review_df["manual_pattern_fit"].astype(str).str.upper()
    good_fit_cnt = int((fit_series == "GOOD_FIT").sum())
    borderline_cnt = int((fit_series == "BORDERLINE").sum())
    not_fit_cnt = int((fit_series == "NOT_FIT").sum())
    uncertain_cnt = int((fit_series == "UNCERTAIN").sum())

    # Stage Breakdown 집계
    trans_mask = manual_review_df["official_stage"].astype(str).str.lower() == PatternAStage.TRANSITION.value
    early_mask = manual_review_df["official_stage"].astype(str).str.lower() == PatternAStage.EARLY_TREND.value

    trans_total = int(trans_mask.sum())
    early_total = int(early_mask.sum())

    trans_rev = int((trans_mask & is_reviewed_mask).sum())
    trans_good = int((trans_mask & (fit_series == "GOOD_FIT")).sum())
    trans_border = int((trans_mask & (fit_series == "BORDERLINE")).sum())
    trans_not = int((trans_mask & (fit_series == "NOT_FIT")).sum())
    trans_unc = int((trans_mask & (fit_series == "UNCERTAIN")).sum())

    early_rev = int((early_mask & is_reviewed_mask).sum())
    early_good = int((early_mask & (fit_series == "GOOD_FIT")).sum())
    early_border = int((early_mask & (fit_series == "BORDERLINE")).sum())
    early_not = int((early_mask & (fit_series == "NOT_FIT")).sum())
    early_unc = int((early_mask & (fit_series == "UNCERTAIN")).sum())

    return CandidateReviewSummary(
        scanner_commit=commit,
        scanner_as_of=as_of,
        source_artifact=source_art,
        total_candidates=total_cand,
        transition_total=trans_total,
        early_trend_total=early_total,
        reviewed_count=reviewed_cnt,
        unreviewed_count=unreviewed_cnt,
        good_fit_count=good_fit_cnt,
        borderline_count=borderline_cnt,
        not_fit_count=not_fit_cnt,
        uncertain_count=uncertain_cnt,
        transition_reviewed=trans_rev,
        transition_good_fit=trans_good,
        transition_borderline=trans_border,
        transition_not_fit=trans_not,
        transition_uncertain=trans_unc,
        early_trend_reviewed=early_rev,
        early_trend_good_fit=early_good,
        early_trend_borderline=early_border,
        early_trend_not_fit=early_not,
        early_trend_uncertain=early_unc,
    )


def save_candidate_review_artifacts(
    source_df: pd.DataFrame,
    manual_review_df: pd.DataFrame,
    summary: CandidateReviewSummary,
    output_dir: Path | str = "artifacts/chart_review",
    as_of_tag: str = "20260814",
    overwrite_manual: bool = False,
) -> tuple[Path, Path, Path]:
    """Candidate Review 아티팩트를 디렉토리에 저장한다.

    Strict Lock & Overwrite Protection:
        1. manual_review CSV가 이미 존재하고 overwrite_manual=False인 경우:
           - 기존 파일의 source provenance 및 candidate ticker set을 검증한다.
           - 다른 scanner source이거나 ticker set이 불일치하면 CandidateReviewIntegrityError를 발생시킨다 (Fail-Closed).
           - 동일 source이면 기존 파일의 수동 라벨링을 그대로 보존하고, Summary는 기존 파일 기준 집계치로 저장한다.
        2. overwrite_manual=True인 경우:
           - 경고 로그를 남기고 템플릿을 새로 덮어쓴다.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    source_csv = out_path / f"pattern_a_candidate_source_{as_of_tag}.csv"
    manual_csv = out_path / f"pattern_a_candidate_manual_review_{as_of_tag}.csv"
    summary_json = out_path / f"pattern_a_candidate_review_summary_{as_of_tag}.json"

    # 1. Source CSV 저장 (항상 최신 갱신 가능)
    source_df.to_csv(source_csv, index=False, encoding="utf-8")
    logger.info("Saved candidate source CSV: %s (%d rows)", source_csv, len(source_df))

    # 2. Manual Review CSV 처리 및 Source Lock 검증
    final_summary = summary
    if manual_csv.exists() and not overwrite_manual:
        existing_manual = pd.read_csv(manual_csv, dtype={"ticker": str})

        # Provenance Lock 검증 (scanner_commit / scanner_as_of)
        if "scanner_commit" in existing_manual.columns:
            existing_commit = str(existing_manual["scanner_commit"].iloc[0])
            if existing_commit != summary.scanner_commit:
                raise CandidateReviewIntegrityError(
                    f"Existing manual review at {manual_csv} belongs to scanner_commit '{existing_commit}', "
                    f"which does not match current source commit '{summary.scanner_commit}'. "
                    f"Refusing to overwrite human annotations across different scanner generations. "
                    f"Use a new output directory or specify --overwrite-manual to discard."
                )

        # Candidate Ticker Set Lock 검증
        existing_tickers = set(existing_manual["ticker"].astype(str))
        current_tickers = set(manual_review_df["ticker"].astype(str))
        if existing_tickers != current_tickers:
            diff_missing = current_tickers - existing_tickers
            diff_extra = existing_tickers - current_tickers
            raise CandidateReviewIntegrityError(
                f"Existing manual review ticker set mismatch with new source candidate pool! "
                f"Missing in existing: {list(diff_missing)[:5]}, Extra in existing: {list(diff_extra)[:5]}. "
                f"Refusing to silently mix candidate sets. Use a new output directory."
            )

        logger.info(
            "Preserving existing manual review CSV at %s (Source lock verified: commit=%s, candidates=%d)",
            manual_csv,
            summary.scanner_commit,
            len(existing_manual),
        )
        # 기존 수동 파일 기반으로 Summary 재계산
        final_summary = summarize_manual_review(
            existing_manual,
            scanner_commit=summary.scanner_commit,
            scanner_as_of=summary.scanner_as_of,
            source_artifact=summary.source_artifact,
        )
    else:
        if manual_csv.exists() and overwrite_manual:
            logger.warning("Overwriting existing manual review CSV at %s (--overwrite-manual is True)", manual_csv)
        manual_review_df.to_csv(manual_csv, index=False, encoding="utf-8")
        logger.info("Saved manual review template CSV: %s (%d rows)", manual_csv, len(manual_review_df))

    # 3. Summary JSON 저장
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(final_summary.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info("Saved candidate review summary JSON: %s", summary_json)

    return source_csv, manual_csv, summary_json
