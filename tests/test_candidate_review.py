"""Tests for Pattern A Candidate Chart Review Dataset Module (Evidence Integrity Final Fix).

Validates:
1. Candidate state == 'candidate' only extraction
2. 1 ticker = 1 row preservation
3. Matrix A: Same source full match -> PASS & preserve manual labels & summary recalculated
4. Matrix B: Different scanner_commit -> FAIL & ZERO artifact mutation (Source, Manual, Summary)
5. Matrix C: Different scanner_as_of -> FAIL & ZERO artifact mutation (Source, Manual, Summary)
6. Matrix D: Different source_artifact -> FAIL & ZERO artifact mutation (Source, Manual, Summary)
7. Matrix E1: Different ticker set -> FAIL & ZERO artifact mutation (Source, Manual, Summary)
8. Matrix E2: Official Stage mismatch -> FAIL & ZERO artifact mutation (Source, Manual, Summary)
9. Duplicate manual ticker / row count mismatch -> FAIL & ZERO artifact mutation
10. Full-row provenance uniformity & mixed provenance / NaN fail-closed
11. Manual vocabulary strict validation & NaN / empty string fail-closed
12. 2-way consistency warning logging (Case A & Case B)
13. summarize_manual_review standalone integrity & update-summary-only zero mutation
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
    """Matrix B: Different scanner_commit -> FAIL & ZERO artifact mutation (Source, Manual, Summary)."""
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

    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-08-14", scanner_commit="9999999"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="Provenance mismatch in 'scanner_commit'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_c_diff_as_of_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix C: Different scanner_as_of -> FAIL & ZERO artifact mutation (Source, Manual, Summary)."""
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

    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, as_of="2026-07-31", scanner_commit="13ab6f4"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="Provenance mismatch in 'scanner_as_of'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, as_of_tag="20260814", overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_d_diff_source_artifact_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix D: Different source_artifact -> FAIL & ZERO artifact mutation (Source, Manual, Summary)."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, source_artifact_name="artifact_v1.csv"
    )
    out_dir = tmp_path / "chart_review_diff_artifact"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(
        sample_scanner_csv_df, source_artifact_name="artifact_v2.csv"
    )

    with pytest.raises(CandidateReviewIntegrityError, match="Provenance mismatch in 'source_artifact'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_e1_diff_ticker_set_fail_closed_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """Matrix E1: Different ticker set -> FAIL & ZERO artifact mutation (Source, Manual, Summary)."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir = tmp_path / "chart_review_diff_tickers"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    reduced_df = sample_scanner_csv_df[sample_scanner_csv_df["ticker"] != "000660"].copy()
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(reduced_df)

    with pytest.raises(CandidateReviewIntegrityError, match="Row count mismatch|ticker set mismatch"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_matrix_e2_diff_official_stage_identity_fail_closed(sample_scanner_csv_df, tmp_path: Path):
    """Matrix E2: Same ticker set but official_stage changed -> FAIL & ZERO mutation."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir = tmp_path / "chart_review_diff_stage"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    # 005930의 stage를 transition -> early_trend로 변경한 소스
    modified_stage_df = sample_scanner_csv_df.copy()
    modified_stage_df.loc[modified_stage_df["ticker"] == "005930", "official_stage"] = "early_trend"
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(modified_stage_df)

    with pytest.raises(CandidateReviewIntegrityError, match="candidate identity .* mismatch"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)

    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert manual_csv.read_text(encoding="utf-8") == man_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig


def test_duplicate_manual_row_and_row_count_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """실수로 1개 row를 복제(N+1 rows)한 경우 FAIL & ZERO artifact mutation 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir = tmp_path / "chart_review_dup_row"
    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir)

    src_csv = out_dir / "pattern_a_candidate_source_20260814.csv"
    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    sum_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"

    src_orig = src_csv.read_text(encoding="utf-8")
    man_orig = manual_csv.read_text(encoding="utf-8")
    sum_orig = sum_json.read_text(encoding="utf-8")

    # 005930 row를 복제하여 4행으로 저장
    df_with_dup = pd.read_csv(manual_csv, dtype={"ticker": str})
    df_with_dup = pd.concat([df_with_dup, df_with_dup.iloc[[0]]], ignore_index=True)
    df_with_dup.to_csv(manual_csv, index=False, encoding="utf-8")
    corrupted_man = manual_csv.read_text(encoding="utf-8")

    # save 재시도 -> 에러 발생
    with pytest.raises(CandidateReviewIntegrityError, match="Duplicate ticker rows"):
        save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir, overwrite_manual=False)

    # Source와 Summary는 100% 변경되지 않아야 하고, Manual CSV도 추가 손상 없어야 함
    assert src_csv.read_text(encoding="utf-8") == src_orig
    assert sum_json.read_text(encoding="utf-8") == sum_orig
    assert manual_csv.read_text(encoding="utf-8") == corrupted_man


def test_provenance_column_full_row_uniformity_and_nan(sample_scanner_csv_df, tmp_path: Path):
    """중간 row provenance 변경 또는 NaN 발생 시 FAIL-CLOSED 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)
    out_dir1 = tmp_path / "chart_review_prov_mixed"
    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir1)
    manual_csv1 = out_dir1 / "pattern_a_candidate_manual_review_20260814.csv"

    # 1. 중간 row scanner_commit 변경
    df_mixed_commit = pd.read_csv(manual_csv1, dtype={"ticker": str})
    df_mixed_commit.loc[df_mixed_commit.index[1], "scanner_commit"] = "9999999"
    df_mixed_commit.to_csv(manual_csv1, index=False, encoding="utf-8")

    with pytest.raises(CandidateReviewIntegrityError, match="Mixed provenance values in column 'scanner_commit'"):
        save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir1, overwrite_manual=False)

    # 2. 한 row provenance NaN
    out_dir2 = tmp_path / "chart_review_prov_nan"
    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir2)
    manual_csv2 = out_dir2 / "pattern_a_candidate_manual_review_20260814.csv"

    df_nan_prov = pd.read_csv(manual_csv2, dtype={"ticker": str})
    df_nan_prov.loc[df_nan_prov.index[0], "scanner_as_of"] = None
    df_nan_prov.to_csv(manual_csv2, index=False, encoding="utf-8")

    with pytest.raises(CandidateReviewIntegrityError, match="contains NaN/Null values"):
        save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir2, overwrite_manual=False)


def test_manual_vocabulary_nan_and_empty_string_fail_closed(sample_scanner_csv_df):
    """Vocabulary NaN, 빈 문자열, 비정규 오타 시 Fail-Closed 검증."""
    _, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # 1. review_status NaN
    df_nan_status = manual_df.copy()
    df_nan_status.loc[df_nan_status.index[0], "review_status"] = None
    with pytest.raises(CandidateReviewIntegrityError, match="review_status column contains NaN or Null"):
        summarize_manual_review(df_nan_status)

    # 2. manual_pattern_fit 빈 문자열
    df_empty_fit = manual_df.copy()
    df_empty_fit.loc[df_empty_fit.index[0], "manual_pattern_fit"] = "   "
    with pytest.raises(CandidateReviewIntegrityError, match="Invalid manual_pattern_fit values"):
        summarize_manual_review(df_empty_fit)

    # 3. manual_stage_fit 오타
    df_typo_stage = manual_df.copy()
    df_typo_stage.loc[df_typo_stage.index[0], "manual_stage_fit"] = "PERFECT"
    with pytest.raises(CandidateReviewIntegrityError, match="Invalid manual_stage_fit values"):
        summarize_manual_review(df_typo_stage)


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


def test_summarize_manual_review_standalone_integrity_and_zero_mutation(sample_scanner_csv_df, tmp_path: Path):
    """summarize_manual_review 단독 실행 시 duplicate ticker 및 mixed provenance 차단 검증."""
    _, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # duplicate ticker 포함 시
    dup_df = pd.concat([manual_df, manual_df.iloc[[0]]], ignore_index=True)
    with pytest.raises(CandidateReviewIntegrityError, match="Duplicate ticker rows"):
        summarize_manual_review(dup_df)
