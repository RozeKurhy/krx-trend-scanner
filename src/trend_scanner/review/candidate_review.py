"""Pattern A Real Candidate Chart Review v0.1 Dataset Preparation & Workflow Module.

Extracts CANDIDATE state stocks from Full Universe Scanner artifacts,
validates strict dataset integrity & source lock provenance,
and prepares Manual Chart Review datasets with human annotation columns
and dynamic workflow summary recalculation.

Guarantees:
- VALIDATE FIRST, WRITE SECOND (Zero artifact mutation on validation failure)
- 4-Way Full Source Lock: scanner_commit, scanner_as_of, source_artifact, (ticker, official_stage)
- Strict Manual Vocabulary Validation (Fail-Closed)
- 2-Way Consistency Warning Logging
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

REQUIRED_PROVENANCE_COLUMNS = {"scanner_commit", "scanner_as_of", "source_artifact", "ticker", "official_stage"}

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


def _validate_manual_vocabulary(df: pd.DataFrame) -> None:
    """Manual review 컬럼들의 값이 허용된 vocabulary 내에 있는지 엄격히 검증한다 (Fail-Closed)."""
    if "review_status" in df.columns:
        statuses = df["review_status"].dropna().astype(str).str.strip().str.upper()
        invalid_status = df[~statuses.isin(ALLOWED_REVIEW_STATUS)]
        if not invalid_status.empty:
            raise CandidateReviewIntegrityError(
                f"Invalid review_status values found in manual review: "
                f"{invalid_status[['ticker', 'review_status']].to_dict('records')}. "
                f"Allowed values: {sorted(ALLOWED_REVIEW_STATUS)}"
            )

    if "manual_pattern_fit" in df.columns:
        fits = df["manual_pattern_fit"].dropna().astype(str).str.strip().str.upper()
        invalid_fit = df[~fits.isin(ALLOWED_MANUAL_PATTERN_FIT)]
        if not invalid_fit.empty:
            raise CandidateReviewIntegrityError(
                f"Invalid manual_pattern_fit values found in manual review: "
                f"{invalid_fit[['ticker', 'manual_pattern_fit']].to_dict('records')}. "
                f"Allowed values: {sorted(ALLOWED_MANUAL_PATTERN_FIT)}"
            )

    if "manual_stage_fit" in df.columns:
        stage_fits = df["manual_stage_fit"].dropna().astype(str).str.strip().str.upper()
        invalid_stage_fit = df[~stage_fits.isin(ALLOWED_MANUAL_STAGE_FIT)]
        if not invalid_stage_fit.empty:
            raise CandidateReviewIntegrityError(
                f"Invalid manual_stage_fit values found in manual review: "
                f"{invalid_stage_fit[['ticker', 'manual_stage_fit']].to_dict('records')}. "
                f"Allowed values: {sorted(ALLOWED_MANUAL_STAGE_FIT)}"
            )


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
    cand_mask = scanner_df["candidate_state"].astype(str).str.strip().str.lower() == "candidate"
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

    Strict Validation:
        - 필수 Provenance 컬럼 부재 시 Fail-Closed
        - Manual Vocabulary 오류 시 Fail-Closed
        - 2-Way Consistency Mismatch 시 Warning 로깅
    """
    total_cand = len(manual_review_df)

    # 1. 필수 Provenance 컬럼 검증
    missing_prov = REQUIRED_PROVENANCE_COLUMNS - set(manual_review_df.columns)
    if missing_prov:
        raise CandidateReviewIntegrityError(
            f"Manual review dataset is missing required provenance columns: {sorted(missing_prov)}"
        )

    # 2. Vocabulary Validation (Fail-Closed)
    _validate_manual_vocabulary(manual_review_df)

    # 3. Provenance 추출
    commit = str(scanner_commit or manual_review_df["scanner_commit"].iloc[0])
    as_of = str(scanner_as_of or manual_review_df["scanner_as_of"].iloc[0])
    source_art = str(source_artifact or manual_review_df["source_artifact"].iloc[0])

    # 4. Normalized Series
    status_series = manual_review_df["review_status"].astype(str).str.strip().str.upper()
    fit_series = manual_review_df["manual_pattern_fit"].astype(str).str.strip().str.upper()

    # 5. Reviewed 여부 판정: review_status == 'REVIEWED' 또는 manual_pattern_fit != 'UNREVIEWED'
    is_reviewed_mask = (status_series == "REVIEWED") | (fit_series != "UNREVIEWED")
    reviewed_cnt = int(is_reviewed_mask.sum())
    unreviewed_cnt = total_cand - reviewed_cnt

    # 6. 2-Way Consistency Warning Logging
    # Case A: status=REVIEWED but fit=UNREVIEWED
    case_a = manual_review_df[(status_series == "REVIEWED") & (fit_series == "UNREVIEWED")]
    if not case_a.empty:
        logger.warning(
            "Consistency Warning (Case A): Found %d rows with review_status=REVIEWED but manual_pattern_fit=UNREVIEWED (e.g. tickers: %s)",
            len(case_a),
            case_a["ticker"].tolist()[:5],
        )

    # Case B: status=UNREVIEWED but fit!=UNREVIEWED
    case_b = manual_review_df[(status_series == "UNREVIEWED") & (fit_series != "UNREVIEWED")]
    if not case_b.empty:
        logger.warning(
            "Consistency Warning (Case B): Found %d rows with review_status=UNREVIEWED but manual_pattern_fit!=UNREVIEWED (e.g. tickers: %s)",
            len(case_b),
            case_b["ticker"].tolist()[:5],
        )

    # 7. Overall Pattern Fit 집계
    good_fit_cnt = int((fit_series == "GOOD_FIT").sum())
    borderline_cnt = int((fit_series == "BORDERLINE").sum())
    not_fit_cnt = int((fit_series == "NOT_FIT").sum())
    uncertain_cnt = int((fit_series == "UNCERTAIN").sum())

    # 8. Stage Breakdown 집계
    trans_mask = manual_review_df["official_stage"].astype(str).str.strip().str.lower() == PatternAStage.TRANSITION.value
    early_mask = manual_review_df["official_stage"].astype(str).str.strip().str.lower() == PatternAStage.EARLY_TREND.value

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

    Strict Atomicity & Lock Contract:
        [VALIDATE FIRST, WRITE SECOND]
        - 어떤 파일도 디스크에 쓰기 전에 모든 Provenance, Lock, Vocabulary 검증을 완료한다.
        - 검증 실패 시 어떤 파일도 변경되지 않는다 (Zero Mutation).
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    source_csv = out_path / f"pattern_a_candidate_source_{as_of_tag}.csv"
    manual_csv = out_path / f"pattern_a_candidate_manual_review_{as_of_tag}.csv"
    summary_json = out_path / f"pattern_a_candidate_review_summary_{as_of_tag}.json"

    # -------------------------------------------------------------
    # 1. VALIDATE FIRST (어떤 write도 수행하기 전에 사전 검증)
    # -------------------------------------------------------------
    final_summary = summary
    should_write_manual = True

    if manual_csv.exists() and not overwrite_manual:
        existing_manual = pd.read_csv(manual_csv, dtype={"ticker": str})

        # 1.1 필수 Provenance 컬럼 존재 검증
        missing_prov = REQUIRED_PROVENANCE_COLUMNS - set(existing_manual.columns)
        if missing_prov:
            raise CandidateReviewIntegrityError(
                f"Existing manual review at {manual_csv} is missing required provenance columns: {sorted(missing_prov)}"
            )

        # 1.2 Manual Vocabulary 검증
        _validate_manual_vocabulary(existing_manual)

        # 1.3 Strict Provenance Lock 검증 (scanner_commit, scanner_as_of, source_artifact)
        existing_commit = str(existing_manual["scanner_commit"].iloc[0])
        if existing_commit != summary.scanner_commit:
            raise CandidateReviewIntegrityError(
                f"Existing manual review at {manual_csv} belongs to scanner_commit '{existing_commit}', "
                f"which does not match new source commit '{summary.scanner_commit}'. "
                f"Refusing to overwrite human annotations across different scanner generations. "
                f"Use a new output directory or specify --overwrite-manual to discard."
            )

        existing_as_of = str(existing_manual["scanner_as_of"].iloc[0])
        if existing_as_of != summary.scanner_as_of:
            raise CandidateReviewIntegrityError(
                f"Existing manual review at {manual_csv} belongs to scanner_as_of '{existing_as_of}', "
                f"which does not match new source as_of '{summary.scanner_as_of}'. "
                f"Refusing to mix different temporal evaluation dates. Use a new output directory."
            )

        existing_artifact = str(existing_manual["source_artifact"].iloc[0])
        if existing_artifact != summary.source_artifact:
            raise CandidateReviewIntegrityError(
                f"Existing manual review at {manual_csv} was generated from source_artifact '{existing_artifact}', "
                f"which does not match new source artifact '{summary.source_artifact}'. "
                f"Refusing to mix different source artifact origins. Use a new output directory."
            )

        # 1.4 Candidate Identity Lock 검증 (ticker + official_stage pair)
        existing_identities = set(zip(existing_manual["ticker"].astype(str), existing_manual["official_stage"].astype(str)))
        current_identities = set(zip(manual_review_df["ticker"].astype(str), manual_review_df["official_stage"].astype(str)))
        if existing_identities != current_identities:
            diff_missing = current_identities - existing_identities
            diff_extra = existing_identities - current_identities
            raise CandidateReviewIntegrityError(
                f"Existing manual review candidate identity (ticker + stage) mismatch with new source pool! "
                f"Missing in existing: {list(diff_missing)[:5]}, Extra in existing: {list(diff_extra)[:5]}. "
                f"Refusing to silently mix candidate sets. Use a new output directory."
            )

        # 검증 완료: 기존 파일 보존 결정 및 Summary 재계산
        logger.info(
            "Preserving existing manual review CSV at %s (Source lock verified: commit=%s, candidates=%d)",
            manual_csv,
            summary.scanner_commit,
            len(existing_manual),
        )
        should_write_manual = False
        final_summary = summarize_manual_review(
            existing_manual,
            scanner_commit=summary.scanner_commit,
            scanner_as_of=summary.scanner_as_of,
            source_artifact=summary.source_artifact,
        )
    elif manual_csv.exists() and overwrite_manual:
        logger.warning(
            "WARNING: Overwriting existing manual review CSV at %s (--overwrite-manual is True). "
            "Existing human annotations will be discarded!",
            manual_csv,
        )

    # -------------------------------------------------------------
    # 2. WRITE SECOND (모든 validation 통과 후에만 파일 쓰기 실행)
    # -------------------------------------------------------------
    # 2.1 Source CSV 저장
    source_df.to_csv(source_csv, index=False, encoding="utf-8")
    logger.info("Saved candidate source CSV: %s (%d rows)", source_csv, len(source_df))

    # 2.2 Manual Review CSV 저장 (필요 시)
    if should_write_manual:
        manual_review_df.to_csv(manual_csv, index=False, encoding="utf-8")
        logger.info("Saved manual review template CSV: %s (%d rows)", manual_csv, len(manual_review_df))

    # 2.3 Summary JSON 저장
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(final_summary.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info("Saved candidate review summary JSON: %s", summary_json)

    return source_csv, manual_csv, summary_json
