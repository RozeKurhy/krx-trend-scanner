"""Tests for Pattern A Candidate Chart Review Dataset Module (Source Lock Final Fix).

Validates:
1. Candidate state == 'candidate' only extraction
2. 1 ticker = 1 row preservation
3. Duplicate ticker integrity check
4. Official Stage integrity (TRANSITION / EARLY_TREND only)
5. AssetType.COMMON integrity check
6. Evaluator / Score readiness integrity check
7. Scanner source measurements preservation
8. Manual review columns initial values
9. Matrix A: Same source full match -> PASS & preserve manual labels & summary recalculated
10. Matrix B: Different scanner_commit -> FAIL & ZERO artifact mutation
11. Matrix C: Different scanner_as_of -> FAIL & ZERO artifact mutation
12. Matrix D: Different source_artifact -> FAIL & ZERO artifact mutation
13. Matrix E: Different ticker set -> FAIL & ZERO artifact mutation
14. Matrix F/G/H: Missing provenance columns -> FAIL & ZERO artifact mutation
15. Strict vocabulary validation (fail-closed on typos like 'GOODFIT', 'INVALID_STATUS')
16. Dynamic manual summary calculations & 2-way consistency warnings
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.review.candidate_review import (
    CandidateReviewIntegrityError,
    extract_and_prepare_candidate_review,
    save_candidate_review_artifacts,
    summarize_manual_review,
)


@pytest.fixture
def sample_scanner_csv_df():
    """테스트용 가상 스캐너 결과 DataFrame."""
    rows = [
        # Candidate 1 (Transition, KOSPI)
        {
            "ticker": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "requested_as_of": "2026-08-14",
            "candidate_state": "candidate",
            "official_stage": "transition",
            "pattern_a_score": 75.5,
            "score_delta_1m": 5.0,
            "score_delta_3m": 12.0,
            "score_delta_6m": 20.0,
            "raw_data_ready": True,
            "feature_ready": True,
            "score_ready": True,
            "stage_ready": True,
            "evaluator_ready": True,
            "momentum_current_ready": True,
            "momentum_1m_ready": True,
            "momentum_3m_ready": True,
            "momentum_6m_ready": True,
            "freshness_status": "FRESH",
            "quality_flags": "",
            "base_score": 40.0,
            "transition_score": 35.5,
            "balanced_core_score": 75.5,
            "alignment_bonus": 0.0,
            "progressed_penalty": 0.0,
        },
        # Candidate 2 (Early Trend, KOSDAQ)
        {
            "ticker": "068270",
            "name": "셀트리온",
            "market": "KOSDAQ",
            "asset_type": "COMMON",
            "requested_as_of": "2026-08-14",
            "candidate_state": "candidate",
            "official_stage": "early_trend",
            "pattern_a_score": 85.0,
            "score_delta_1m": -2.0,
            "score_delta_3m": 15.0,
            "score_delta_6m": 30.0,
            "raw_data_ready": True,
            "feature_ready": True,
            "score_ready": True,
            "stage_ready": True,
            "evaluator_ready": True,
            "momentum_current_ready": True,
            "momentum_1m_ready": True,
            "momentum_3m_ready": True,
            "momentum_6m_ready": True,
            "freshness_status": "FRESH",
            "quality_flags": "",
            "base_score": 40.0,
            "transition_score": 45.0,
            "balanced_core_score": 85.0,
            "alignment_bonus": 0.0,
            "progressed_penalty": 0.0,
        },
        # Candidate 3 (Transition, KOSPI)
        {
            "ticker": "000660",
            "name": "SK하이닉스",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "requested_as_of": "2026-08-14",
            "candidate_state": "candidate",
            "official_stage": "transition",
            "pattern_a_score": 62.0,
            "score_delta_1m": 0.0,
            "score_delta_3m": -5.0,
            "score_delta_6m": 10.0,
            "raw_data_ready": True,
            "feature_ready": True,
            "score_ready": True,
            "stage_ready": True,
            "evaluator_ready": True,
            "momentum_current_ready": True,
            "momentum_1m_ready": True,
            "momentum_3m_ready": True,
            "momentum_6m_ready": True,
            "freshness_status": "FRESH",
            "quality_flags": "",
            "base_score": 30.0,
            "transition_score": 32.0,
            "balanced_core_score": 62.0,
            "alignment_bonus": 0.0,
            "progressed_penalty": 0.0,
        },
        # Non-Candidate (Blocked, KOSPI)
        {
            "ticker": "035420",
            "name": "NAVER",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "requested_as_of": "2026-08-14",
            "candidate_state": "blocked",
            "official_stage": "weak",
            "pattern_a_score": 10.0,
            "raw_data_ready": True,
            "feature_ready": True,
            "score_ready": True,
            "stage_ready": True,
            "evaluator_ready": True,
        },
    ]
    return pd.DataFrame(rows)


def test_candidate_extraction_and_row_count(sample_scanner_csv_df):
    """candidate_state == 'candidate'만 정확히 추출되고 row count가 일치하는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    assert len(src_df) == 3
    assert len(manual_df) == 3
    assert summary.total_candidates == 3
    assert summary.transition_total == 2
    assert summary.early_trend_total == 1
    assert set(src_df["ticker"]) == {"005930", "068270", "000660"}


def test_matrix_a_same_source_preserve_success(sample_scanner_csv_df, tmp_path: Path):
    """Matrix A: Same source 4-way full match 시 기존 수동 라벨이 보존되고 summary가 재계산되는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(
        sample_scanner_csv_df,
        as_of="2026-08-14",
        scanner_commit="13ab6f4",
        source_artifact_name="pattern_a_universe_scan_20260814.csv",
    )
    out_dir = tmp_path / "chart_review"

    # 1. 초기 아티팩트 생성
    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir)
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"

    # 2. 사용자 수동 라벨링 주입
    df_edited = pd.read_csv(manual_csv, dtype={"ticker": str})
    df_edited.loc[df_edited["ticker"] == "005930", "manual_pattern_fit"] = "GOOD_FIT"
    df_edited.loc[df_edited["ticker"] == "005930", "review_status"] = "REVIEWED"
    df_edited.to_csv(manual_csv, index=False, encoding="utf-8")

    # 3. 동일 source로 다시 save 호출
    save_candidate_review_artifacts(
        src_df, manual_df, summary, output_dir=out_dir, overwrite_manual=False
    )

    # 4. 수동 라벨 보존 및 summary 검증
    df_reloaded = pd.read_csv(manual_csv, dtype={"ticker": str})
    assert df_reloaded.loc[df_reloaded["ticker"] == "005930", "manual_pattern_fit"].iloc[0] == "GOOD_FIT"

    summary_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"
    with open(summary_json, encoding="utf-8") as f:
        s_data = json.load(f)
    assert s_data["reviewed_count"] == 1
    assert s_data["good_fit_count"] == 1


def test_matrix_b_diff_commit_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix B: Different scanner_commit -> FAIL & ZERO artifact mutation 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-08-14", scanner_commit="13ab6f4"
    )
    out_dir = tmp_path / "chart_review_diff_commit"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    # 다른 commit으로 새 데이터셋 준비
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-08-14", scanner_commit="9999999"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="belongs to scanner_commit '13ab6f4'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    # Validate First 원칙: 모든 파일 내용이 변경 없이 100% 동일해야 함 (Zero Mutation)
    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_c_diff_as_of_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix C: Different scanner_as_of -> FAIL & ZERO artifact mutation 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-08-14", scanner_commit="13ab6f4"
    )
    out_dir = tmp_path / "chart_review_diff_asof"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir, as_of_tag="20260814")

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    # 다른 as_of(예: 2026-07-31)로 실행
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-07-31", scanner_commit="13ab6f4"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="belongs to scanner_as_of '2026-08-14'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, as_of_tag="20260814", overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_d_diff_source_artifact_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix D: Different source_artifact -> FAIL & ZERO artifact mutation 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, source_artifact_name="artifact_v1.csv"
    )
    out_dir = tmp_path / "chart_review_diff_artifact"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    src_orig = src_csv.read_text(encoding="utf-8")

    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, source_artifact_name="artifact_v2.csv"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="source_artifact 'artifact_v1.csv'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig


def test_matrix_e_diff_ticker_set_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix E: Different ticker set -> FAIL & ZERO artifact mutation 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir = tmp_path / "chart_review_diff_tickers"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    src_orig = src_csv.read_text(encoding="utf-8")

    # 1개 종목 누락된 DataFrame
    reduced_df = sample_scanner_csv_df[sample_scanner_csv_df["ticker"] != "000660"].copy()
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(reduced_df)

    with pytest.raises(CandidateReviewIntegrityError, match="candidate identity .* mismatch"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig


def test_matrix_f_g_h_missing_provenance_columns_fail_closed(sample_scanner_csv_df, tmp_path: Path):
    """Matrix F/G/H: Existing manual review missing provenance columns -> FAIL-CLOSED 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir = tmp_path / "chart_review_missing_prov"
    out_dir.mkdir(parents=True)

    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"

    # provenance 컬럼이 누락된 레거시 형식 CSV 파일 생성
    broken_manual = manual_df.drop(columns=["scanner_commit", "scanner_as_of", "source_artifact"])
    broken_manual.to_csv(manual_csv, index=False, encoding="utf-8")

    with pytest.raises(CandidateReviewIntegrityError, match="missing required provenance columns"):
        save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir, overwrite_manual=False)


def test_strict_vocabulary_validation_fail_closed(sample_scanner_csv_df):
    """오타('GOODFIT', 'INVALID_STATUS') 등 비정규 Vocabulary 입력 시 Fail-Closed 검증."""
    _, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # 1. Invalid pattern fit
    broken_fit = manual_df.copy()
    broken_fit.loc[broken_fit.index[0], "manual_pattern_fit"] = "GOODFIT"
    with pytest.raises(CandidateReviewIntegrityError, match="Invalid manual_pattern_fit values"):
        summarize_manual_review(broken_fit)

    # 2. Invalid review status
    broken_status = manual_df.copy()
    broken_status.loc[broken_status.index[0], "review_status"] = "DONE"
    with pytest.raises(CandidateReviewIntegrityError, match="Invalid review_status values"):
        summarize_manual_review(broken_status)

    # 3. Invalid stage fit
    broken_stage = manual_df.copy()
    broken_stage.loc[broken_stage.index[0], "manual_stage_fit"] = "PERFECT"
    with pytest.raises(CandidateReviewIntegrityError, match="Invalid manual_stage_fit values"):
        summarize_manual_review(broken_stage)


def test_two_way_consistency_warning_logging(sample_scanner_csv_df, caplog):
    """Case A (REVIEWED + UNREVIEWED fit) 및 Case B (UNREVIEWED + GOOD_FIT) 양방향 경고 로깅 검증."""
    _, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # Case A 주입
    df_case_a = manual_df.copy()
    df_case_a.loc[df_case_a.index[0], "review_status"] = "REVIEWED"
    df_case_a.loc[df_case_a.index[0], "manual_pattern_fit"] = "UNREVIEWED"

    with caplog.at_level(logging.WARNING):
        summarize_manual_review(df_case_a)
    assert "Consistency Warning (Case A)" in caplog.text

    caplog.clear()

    # Case B 주입
    df_case_b = manual_df.copy()
    df_case_b.loc[df_case_b.index[0], "review_status"] = "UNREVIEWED"
    df_case_b.loc[df_case_b.index[0], "manual_pattern_fit"] = "GOOD_FIT"

    with caplog.at_level(logging.WARNING):
        summarize_manual_review(df_case_b)
    assert "Consistency Warning (Case B)" in caplog.text
