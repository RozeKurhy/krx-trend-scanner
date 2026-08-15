"""Tests for Pattern A Candidate Chart Review Dataset Module (Final Cleanup).

Validates:
1. Candidate state == 'candidate' only extraction
2. 1 ticker = 1 row preservation
3. Duplicate ticker integrity check
4. Official Stage integrity (TRANSITION / EARLY_TREND only)
5. AssetType.COMMON integrity check
6. Evaluator / Score readiness integrity check
7. Scanner source measurements preservation
8. Manual review columns initial values
9. Scanner source provenance fields (scanner_commit, scanner_as_of, source_artifact)
10. Existing manual review file overwrite protection (same source preserve)
11. Existing manual review different source commit fail-closed
12. Existing manual review different ticker set fail-closed
13. Manual summary reviewed/unreviewed & pattern fit breakdown
14. Stage-specific manual summary breakdown
15. Manual annotations do not alter source measurements
16. Deterministic non-ranking candidate ordering
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

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
        # Candidate 3 (Transition, KOSDAQ)
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
        # Non-Candidate 1 (Blocked, KOSPI)
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
        # Non-Candidate 2 (Late, KOSDAQ)
        {
            "ticker": "035720",
            "name": "카카오",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "requested_as_of": "2026-08-14",
            "candidate_state": "late",
            "official_stage": "progressed",
            "pattern_a_score": 90.0,
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


def test_provenance_fields_in_artifacts(sample_scanner_csv_df):
    """scanner_commit, scanner_as_of, source_artifact가 source 및 manual dataset에 기록되는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(
        sample_scanner_csv_df,
        as_of="2026-08-14",
        scanner_commit="13ab6f4",
        source_artifact_name="pattern_a_universe_scan_20260814.csv",
    )

    for df in (src_df, manual_df):
        assert "scanner_commit" in df.columns
        assert "scanner_as_of" in df.columns
        assert "source_artifact" in df.columns
        assert df["scanner_commit"].iloc[0] == "13ab6f4"
        assert df["scanner_as_of"].iloc[0] == "2026-08-14"
        assert df["source_artifact"].iloc[0] == "pattern_a_universe_scan_20260814.csv"

    assert summary.scanner_commit == "13ab6f4"
    assert summary.scanner_as_of == "2026-08-14"
    assert summary.source_artifact == "pattern_a_universe_scan_20260814.csv"


def test_duplicate_ticker_rejection(sample_scanner_csv_df):
    """후보 목록 내 중복 종목이 있으면 무결성 에러 발생 검증."""
    broken = sample_scanner_csv_df.copy()
    broken.loc[broken.index[0], "ticker"] = "068270"

    with pytest.raises(CandidateReviewIntegrityError, match="Duplicate candidate tickers"):
        extract_and_prepare_candidate_review(broken)


def test_invalid_stage_rejection(sample_scanner_csv_df):
    """CANDIDATE 상태인데 stage가 TRANSITION / EARLY_TREND가 아니면 에러 발생 검증."""
    broken = sample_scanner_csv_df.copy()
    broken.loc[broken.index[0], "official_stage"] = "weak"

    with pytest.raises(CandidateReviewIntegrityError, match="Invalid stages found"):
        extract_and_prepare_candidate_review(broken)


def test_non_common_asset_rejection(sample_scanner_csv_df):
    """보통주가 아닌 자산(우선주/스팩 등)이 후보에 혼입되면 에러 발생 검증."""
    broken = sample_scanner_csv_df.copy()
    broken.loc[broken.index[0], "asset_type"] = "PREFERRED"

    with pytest.raises(CandidateReviewIntegrityError, match="Non-COMMON assets"):
        extract_and_prepare_candidate_review(broken)


def test_readiness_integrity_rejection(sample_scanner_csv_df):
    """evaluator_ready=False 종목이 후보에 포함되어 있으면 에러 발생 검증."""
    broken = sample_scanner_csv_df.copy()
    broken.loc[broken.index[0], "evaluator_ready"] = False

    with pytest.raises(CandidateReviewIntegrityError, match="evaluator_ready=False"):
        extract_and_prepare_candidate_review(broken)


def test_existing_manual_review_file_overwrite_protection_same_source(sample_scanner_csv_df, tmp_path: Path):
    """동일 source에 대해 manual review CSV 파일의 수동 입력값이 overwrite되지 않고 보존되며 summary가 갱신되는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df, scanner_commit="13ab6f4")

    out_dir = tmp_path / "chart_review"
    out_dir.mkdir(parents=True)

    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir)

    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    assert manual_csv.exists()

    # 사용자가 수동 리뷰 작성 (005930: GOOD_FIT, 068270: NOT_FIT)
    df_edited = pd.read_csv(manual_csv, dtype={"ticker": str})
    df_edited.loc[df_edited["ticker"] == "005930", "manual_pattern_fit"] = "GOOD_FIT"
    df_edited.loc[df_edited["ticker"] == "005930", "review_status"] = "REVIEWED"
    df_edited.loc[df_edited["ticker"] == "068270", "manual_pattern_fit"] = "NOT_FIT"
    df_edited.loc[df_edited["ticker"] == "068270", "review_status"] = "REVIEWED"
    df_edited.to_csv(manual_csv, index=False, encoding="utf-8")

    # 동일 source로 다시 save_candidate_review_artifacts 호출
    save_candidate_review_artifacts(
        src_df, manual_df, summary, output_dir=out_dir, overwrite_manual=False
    )

    df_reloaded = pd.read_csv(manual_csv, dtype={"ticker": str})
    row = df_reloaded[df_reloaded["ticker"] == "005930"].iloc[0]
    assert row["manual_pattern_fit"] == "GOOD_FIT"
    assert row["review_status"] == "REVIEWED"

    # Summary JSON도 기존 수동 입력에 맞춰 재계산되어야 함
    summary_json = out_dir / "pattern_a_candidate_review_summary_20260814.json"
    with open(summary_json, encoding="utf-8") as f:
        s_data = json.load(f)
    assert s_data["reviewed_count"] == 2
    assert s_data["unreviewed_count"] == 1
    assert s_data["good_fit_count"] == 1
    assert s_data["not_fit_count"] == 1


def test_existing_manual_review_different_commit_fail_closed(sample_scanner_csv_df, tmp_path: Path):
    """기존 manual review의 scanner_commit과 새로 준비하려는 scanner_commit이 다르면 fail-closed 에러 발생 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(sample_scanner_csv_df, scanner_commit="13ab6f4")
    out_dir = tmp_path / "chart_review_diff_commit"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    # 새로운 scanner commit (예: "9999999")으로 재시도
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(sample_scanner_csv_df, scanner_commit="9999999")
    with pytest.raises(CandidateReviewIntegrityError, match="belongs to scanner_commit '13ab6f4'"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)


def test_existing_manual_review_different_ticker_set_fail_closed(sample_scanner_csv_df, tmp_path: Path):
    """기존 manual review와 새로운 candidate 종목 pool의 ticker set이 다르면 fail-closed 에러 발생 검증."""
    src_df1, manual_df1, summary1 = extract_and_prepare_candidate_review(sample_scanner_csv_df, scanner_commit="13ab6f4")
    out_dir = tmp_path / "chart_review_diff_tickers"
    save_candidate_review_artifacts(src_df1, manual_df1, summary1, output_dir=out_dir)

    # 다른 후보 목록 (종목 1개 제거된 DataFrame)
    reduced_df = sample_scanner_csv_df[sample_scanner_csv_df["ticker"] != "000660"].copy()
    src_df2, manual_df2, summary2 = extract_and_prepare_candidate_review(reduced_df, scanner_commit="13ab6f4")
    with pytest.raises(CandidateReviewIntegrityError, match="ticker set mismatch"):
        save_candidate_review_artifacts(src_df2, manual_df2, summary2, output_dir=out_dir, overwrite_manual=False)


def test_manual_summary_helper_and_stage_breakdown(sample_scanner_csv_df):
    """summarize_manual_review helper의 정확한 진행률 및 Stage별 집계 검증."""
    _, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # 1. 초기 상태 집계
    init_sum = summarize_manual_review(manual_df)
    assert init_sum.total_candidates == 3
    assert init_sum.reviewed_count == 0
    assert init_sum.unreviewed_count == 3

    # 2. 수동 라벨링 주입 (005930(TRANSITION)=GOOD_FIT, 068270(EARLY_TREND)=BORDERLINE, 000660(TRANSITION)=NOT_FIT)
    df_edited = manual_df.copy()
    df_edited.loc[df_edited["ticker"] == "005930", "manual_pattern_fit"] = "GOOD_FIT"
    df_edited.loc[df_edited["ticker"] == "005930", "review_status"] = "REVIEWED"

    df_edited.loc[df_edited["ticker"] == "068270", "manual_pattern_fit"] = "BORDERLINE"
    df_edited.loc[df_edited["ticker"] == "068270", "review_status"] = "REVIEWED"

    df_edited.loc[df_edited["ticker"] == "000660", "manual_pattern_fit"] = "NOT_FIT"
    df_edited.loc[df_edited["ticker"] == "000660", "review_status"] = "REVIEWED"

    sum_res = summarize_manual_review(df_edited)
    assert sum_res.total_candidates == 3
    assert sum_res.reviewed_count == 3
    assert sum_res.unreviewed_count == 0
    assert sum_res.good_fit_count == 1
    assert sum_res.borderline_count == 1
    assert sum_res.not_fit_count == 1

    # Stage breakdown
    assert sum_res.transition_total == 2
    assert sum_res.transition_reviewed == 2
    assert sum_res.transition_good_fit == 1
    assert sum_res.transition_not_fit == 1

    assert sum_res.early_trend_total == 1
    assert sum_res.early_trend_reviewed == 1
    assert sum_res.early_trend_borderline == 1


def test_manual_annotations_do_not_alter_source_scanner_measurements(sample_scanner_csv_df):
    """수동 라벨링을 입력해도 Scanner 원본 측정값 필드가 변형되지 않음을 검증."""
    src_df, manual_df, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    manual_df.loc[manual_df["ticker"] == "005930", "manual_pattern_fit"] = "GOOD_FIT"
    manual_df.loc[manual_df["ticker"] == "005930", "manual_notes"] = "Strong monthly turnaround"

    row_src = src_df[src_df["ticker"] == "005930"].iloc[0]
    row_man = manual_df[manual_df["ticker"] == "005930"].iloc[0]

    assert row_src["pattern_a_score"] == row_man["pattern_a_score"] == 75.5
    assert row_src["official_stage"] == row_man["official_stage"] == "transition"
    assert row_src["score_delta_3m"] == row_man["score_delta_3m"] == 12.0
    assert row_src["base_score"] == row_man["base_score"] == 40.0
