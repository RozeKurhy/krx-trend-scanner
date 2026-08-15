"""Tests for Pattern A Candidate Chart Review Dataset Module.

Validates:
1. Candidate state == 'candidate' only extraction
2. 1 ticker = 1 row preservation
3. Duplicate ticker integrity check
4. Official Stage integrity (TRANSITION / EARLY_TREND only)
5. AssetType.COMMON integrity check
6. Evaluator / Score readiness integrity check
7. Scanner source measurements preservation
8. Manual review columns initial values
9. Existing manual review file overwrite protection
10. Deterministic non-ranking candidate ordering
11. Summary aggregation consistency
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


def test_duplicate_ticker_rejection(sample_scanner_csv_df):
    """후보 목록 내 중복 종목이 있으면 무결성 에러 발생 검증."""
    broken = sample_scanner_csv_df.copy()
    broken.loc[broken.index[0], "ticker"] = "068270"  # 중복 주입

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


def test_scanner_source_values_preserved(sample_scanner_csv_df):
    """Scanner 원본 측정값이 변형 없이 그대로 복사되는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    row_samsung = src_df[src_df["ticker"] == "005930"].iloc[0]
    assert row_samsung["pattern_a_score"] == 75.5
    assert row_samsung["score_delta_1m"] == 5.0
    assert row_samsung["score_delta_3m"] == 12.0
    assert row_samsung["score_delta_6m"] == 20.0
    assert row_samsung["base_score"] == 40.0


def test_manual_review_columns_initial_state(sample_scanner_csv_df):
    """Manual review용 컬럼들이 UNREVIEWED 및 빈 값으로 초기화되는지 검증."""
    _, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    expected_manual_cols = [
        "review_status",
        "monthly_structure",
        "weekly_structure",
        "daily_entry_context",
        "manual_pattern_fit",
        "manual_stage_fit",
        "manual_notes",
    ]
    for col in expected_manual_cols:
        assert col in manual_df.columns

    for _, r in manual_df.iterrows():
        assert r["review_status"] == "UNREVIEWED"
        assert r["manual_pattern_fit"] == "UNREVIEWED"
        assert r["manual_stage_fit"] == "UNREVIEWED"
        assert r["monthly_structure"] == ""
        assert r["manual_notes"] == ""


def test_deterministic_non_ranking_ordering(sample_scanner_csv_df):
    """결과가 (official_stage, market, ticker) 순으로 결정론적으로 정렬되는지 검증."""
    src_df, _, _ = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    # early_trend (1개) -> transition (2개, KOSPI: 000660, 005930)
    ordered_tickers = src_df["ticker"].tolist()
    assert ordered_tickers == ["068270", "000660", "005930"]


def test_existing_manual_review_file_overwrite_protection(sample_scanner_csv_df, tmp_path: Path):
    """이미 존재하는 manual review CSV 파일의 수동 입력값이 overwrite되지 않고 보호되는지 검증."""
    src_df, manual_df, summary = extract_and_prepare_candidate_review(sample_scanner_csv_df)

    out_dir = tmp_path / "chart_review"
    out_dir.mkdir(parents=True)

    # 1. 초기 아티팩트 저장
    save_candidate_review_artifacts(src_df, manual_df, summary, output_dir=out_dir)

    manual_csv = out_dir / "pattern_a_candidate_manual_review_20260814.csv"
    assert manual_csv.exists()

    # 2. 사용자가 수동 리뷰 작성 (005930에 GOOD_FIT 입력)
    df_edited = pd.read_csv(manual_csv, dtype={"ticker": str})
    df_edited.loc[df_edited["ticker"] == "005930", "manual_pattern_fit"] = "GOOD_FIT"
    df_edited.loc[df_edited["ticker"] == "005930", "review_status"] = "REVIEWED"
    df_edited.to_csv(manual_csv, index=False, encoding="utf-8")

    # 3. overwrite_manual=False로 다시 저장 실행
    save_candidate_review_artifacts(
        src_df, manual_df, summary, output_dir=out_dir, overwrite_manual=False
    )

    # 4. 사용자의 수정 내용이 그대로 보존되어 있어야 함
    df_reloaded = pd.read_csv(manual_csv, dtype={"ticker": str})
    row = df_reloaded[df_reloaded["ticker"] == "005930"].iloc[0]
    assert row["manual_pattern_fit"] == "GOOD_FIT"
    assert row["review_status"] == "REVIEWED"
