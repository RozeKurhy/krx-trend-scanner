"""Tests for Pattern A Full Universe Scanner Integration v0.1.

Validates:
1. Official COMMON only contract (excluding PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX)
2. Row count preservation (Official COMMON count == Scanner Output Row count)
3. Missing cache and short history fail-closed handling (INSUFFICIENT_DATA)
4. Partial momentum readiness preservation
5. Direct frozen component reuse (Score v0.2, Stage v0.1, Momentum v0.1 with Completed Periods Only)
6. Exception isolation & deterministic ordering
7. Summary aggregation consistency & artifact export
8. Strict absence of ranking, unified score, cutoff, or BUY/SELL policy fields
9. Temporal Consistency (Shared daily_as_of, Completed Periods Only, Anchor-based Current Momentum)
10. Global official_common_total vs subset scan_target_count separation
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import InvestabilityStatus
from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score_momentum import (
    compute_pattern_a_score_momentum,
)
from trend_scanner.scanner.full_universe_scanner import (
    PatternAUniverseScanResult,
    PatternAUniverseScanRow,
    ScannerRowStatus,
    scan_pattern_a_universe,
)
from trend_scanner.universe.models import (
    AssetType,
    MarketType,
    UniverseSecurity,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot


def _create_mock_daily(
    start_date: str = "2020-01-02",
    end_date: str = "2026-08-14",
    base_price: float = 10000.0,
    slope: float = 5.0,
) -> pd.DataFrame:
    """테스트용 합성 일봉 데이터를 생성한다 (영문 소문자 컬럼)."""
    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    trend = np.linspace(0, slope * n, n)
    noise = np.random.RandomState(42).normal(0, 100, n)
    close = base_price + trend + noise
    close = np.maximum(close, 1000.0)

    df = pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.random.RandomState(42).randint(10000, 500000, n),
            "trading_value": close * 100000,
        },
        index=dates,
    )
    df.index.name = "date"
    return df


@pytest.fixture
def mock_scanner_env(tmp_path: Path):
    """테스트용 캐시 및 가상 유니버스 환경."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    cache = ParquetCache(base_dir=cache_dir)

    # 1. 보통주 (정상 48m+ 데이터)
    df_005930 = _create_mock_daily("2020-01-02", "2026-08-14", 50000.0)
    cache.save("005930", df_005930)

    # 2. 보통주 (정상 48m+ 데이터)
    df_000660 = _create_mock_daily("2020-01-02", "2026-08-14", 80000.0)
    cache.save("000660", df_000660)

    # 3. 보통주 (단기 상장주, 24m)
    df_new = _create_mock_daily("2024-08-01", "2026-08-14", 20000.0)
    cache.save("300001", df_new)

    # 4. 캐시 미존재 보통주: "300002"

    # 가상 유니버스 메타데이터 (보통주 + 우선주 + 스팩 + 리츠 + ETN + KONEX)
    universe_securities = [
        UniverseSecurity("005930", "삼성전자", MarketType.KOSPI),  # COMMON
        UniverseSecurity("005935", "삼성전자우", MarketType.KOSPI),  # PREFERRED
        UniverseSecurity("000660", "SK하이닉스", MarketType.KOSPI),  # COMMON
        UniverseSecurity("300001", "신규보통주", MarketType.KOSDAQ),  # COMMON (short history)
        UniverseSecurity("300002", "캐시누락주", MarketType.KOSDAQ),  # COMMON (missing cache)
        UniverseSecurity("400001", "하나금융21호스팩", MarketType.KOSDAQ),  # SPAC
        UniverseSecurity("400002", "신한알파리츠", MarketType.KOSPI),  # REIT
        UniverseSecurity("500001", "KODEX 레버리지", MarketType.KOSPI),  # ETF
        UniverseSecurity("500002", "삼성 인버스 2X WTI원유 선물 ETN", MarketType.KOSPI),  # ETN
        UniverseSecurity("900001", "코넥스기업", MarketType.KONEX),  # KONEX
    ]

    return {
        "cache": cache,
        "cache_dir": cache_dir,
        "universe": universe_securities,
        "as_of": "2026-08-14",
    }


def test_official_common_only_scanned_and_excluded_assets(mock_scanner_env):
    """보통주만 스캔 대상에 포함되고 비COMMON 자산은 모두 제외되는지 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    scanned_tickers = [r.ticker for r in res.rows]
    assert len(scanned_tickers) == 4
    assert set(scanned_tickers) == {"005930", "000660", "300001", "300002"}

    for r in res.rows:
        assert r.asset_type == AssetType.COMMON

    assert "005935" not in scanned_tickers  # PREFERRED
    assert "400001" not in scanned_tickers  # SPAC
    assert "400002" not in scanned_tickers  # REIT
    assert "500001" not in scanned_tickers  # ETF
    assert "500002" not in scanned_tickers  # ETN
    assert "900001" not in scanned_tickers  # KONEX


def test_output_row_count_matches_resolved_common_count(mock_scanner_env):
    """출력 row 수가 resolved COMMON universe 총수와 정확히 일치하는지 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )
    assert res.summary.official_common_total == 4
    assert res.summary.scan_target_count == 4
    assert res.summary.rows_emitted == 4
    assert len(res.rows) == 4


def test_missing_cache_ticker_row_preserved_and_fail_closed(mock_scanner_env):
    """캐시가 없는 보통주 종목도 row가 삭제되지 않고 INSUFFICIENT_DATA로 fail closed 보존되는지 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    missing_row = next(r for r in res.rows if r.ticker == "300002")
    assert missing_row.cache_present is False
    assert missing_row.raw_data_ready is False
    assert missing_row.evaluator_ready is False
    assert missing_row.pattern_a_score is None
    assert missing_row.official_stage is None
    assert missing_row.candidate_state == PatternACandidateState.INSUFFICIENT_DATA
    assert missing_row.row_status == ScannerRowStatus.UNAVAILABLE
    assert "CACHE_MISSING" in missing_row.evaluator_reason_codes


def test_short_history_row_preserved_and_partial_momentum(mock_scanner_env):
    """36m 미만 단기 상장주도 row가 유지되며 partial/insufficient 데이터가 정확히 기록되는지 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    short_row = next(r for r in res.rows if r.ticker == "300001")
    assert short_row.cache_present is True
    assert short_row.raw_data_ready is True
    assert short_row.candidate_state == PatternACandidateState.INSUFFICIENT_DATA
    assert short_row.momentum_6m_ready is False
    assert short_row.row_status == ScannerRowStatus.UNAVAILABLE


def test_evaluator_and_momentum_direct_reuse_with_completed_periods(mock_scanner_env):
    """Scanner 결과의 Score, Stage, Candidate State, Momentum이 include_incomplete_periods=False 직접 호출과 일치하는지 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    samsung_row = next(r for r in res.rows if r.ticker == "005930")
    daily = mock_scanner_env["cache"].load("005930")

    # Direct Evaluator (include_incomplete_periods=False 명시적 계약)
    snapshot = build_historical_snapshot(
        "005930",
        "삼성전자",
        daily,
        mock_scanner_env["as_of"],
        include_incomplete_periods=False,
    )
    direct_eval = evaluate_pattern_a(snapshot)

    # Direct Momentum
    direct_mom = compute_pattern_a_score_momentum(
        "005930", "삼성전자", daily, mock_scanner_env["as_of"]
    )

    assert samsung_row.pattern_a_score == direct_eval.score
    assert samsung_row.official_stage == direct_eval.lifecycle_stage
    assert samsung_row.candidate_state == direct_eval.candidate_state
    assert samsung_row.score_delta_1m == direct_mom.horizon_1m.score_delta
    assert samsung_row.score_delta_3m == direct_mom.horizon_3m.score_delta
    assert samsung_row.score_delta_6m == direct_mom.horizon_6m.score_delta


def test_current_momentum_readiness_invariants(mock_scanner_env):
    """Horizon ready이면 반드시 Current ready여야 하는 invariant 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    for r in res.rows:
        if r.momentum_1m_ready or r.momentum_3m_ready or r.momentum_6m_ready:
            assert r.momentum_current_ready is True, f"Ticker {r.ticker} horizon is ready but current is not!"

    # 집계 카운트 invariant 검증
    s = res.summary
    assert s.momentum_current_ready_count >= s.momentum_1m_ready_count
    assert s.momentum_current_ready_count >= s.momentum_3m_ready_count
    assert s.momentum_current_ready_count >= s.momentum_6m_ready_count


def test_historical_as_of_shared_context_no_future_date(mock_scanner_env):
    """캐시에 as_of 이후 데이터가 존재해도 shared daily_as_of 덕분에 FUTURE_DATE가 발생하지 않음을 검증."""
    # 2026-09-30까지 미래 데이터가 캐시에 저장된 종목 추가
    df_future = _create_mock_daily("2020-01-02", "2026-09-30", 30000.0)
    mock_scanner_env["cache"].save("005930", df_future)

    # as_of는 2026-08-14로 실행
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of="2026-08-14",
        reference_market_date="2026-08-14",
        universe_securities=mock_scanner_env["universe"],
        target_tickers=["005930"],
    )

    row = res.rows[0]
    # 캐시 원본 마지막 날짜는 2026-09-30
    assert row.cache_last_date == pd.Timestamp("2026-09-30")
    # 하지만 평가 데이터는 2026-08-14까지만 슬라이스되었으므로 FUTURE_DATE가 없어야 함
    assert "FUTURE_DATE" not in row.quality_flags
    assert row.raw_data_ready is True


def test_ticker_exception_isolation(mock_scanner_env):
    """특정 종목 계산 중 예외가 발생해도 격리되고 다른 종목은 정상 처리되는지 검증."""
    corrupt_ticker = "000660"
    p = mock_scanner_env["cache_dir"] / f"{corrupt_ticker}.parquet"
    p.write_text("corrupted non-parquet content")

    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    assert len(res.rows) == 4
    corrupt_row = next(r for r in res.rows if r.ticker == corrupt_ticker)
    assert corrupt_row.row_status == ScannerRowStatus.ERROR
    assert corrupt_row.error_type is not None

    samsung_row = next(r for r in res.rows if r.ticker == "005930")
    assert samsung_row.row_status in (ScannerRowStatus.OK, ScannerRowStatus.PARTIAL)


def test_deterministic_ordering(mock_scanner_env):
    """결과 row가 (MarketType, Ticker) 순으로 결정론적으로 정렬되는지 검증."""
    res1 = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )
    res2 = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    order1 = [(r.market.value, r.ticker) for r in res1.rows]
    order2 = [(r.market.value, r.ticker) for r in res2.rows]
    assert order1 == order2
    assert order1 == sorted(order1)


def test_subset_filters_and_count_separation(mock_scanner_env):
    """Subset 실행 시 official_common_total은 global count를 유지하고 scan_target_count가 subset을 반영하는지 검증."""
    # 1. target_tickers
    res_tickers = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
        target_tickers=["005930", "300001"],
    )
    assert res_tickers.summary.official_common_total == 4  # Global count 유지
    assert res_tickers.summary.scan_target_count == 2      # Subset count
    assert res_tickers.summary.rows_emitted == 2
    assert len(res_tickers.rows) == 2
    assert [r.ticker for r in res_tickers.rows] == ["300001", "005930"]

    # 2. limit
    res_limit = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
        limit=2,
    )
    assert res_limit.summary.official_common_total == 4
    assert res_limit.summary.scan_target_count == 2
    assert res_limit.summary.rows_emitted == 2
    assert len(res_limit.rows) == 2


def test_no_ranking_or_decision_fields_exist(mock_scanner_env):
    """결과 딕셔너리에 rank, cutoff, composite score, buy/sell decision 필드가 존재하지 않음을 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    df = res.to_dataframe()
    cols = set(df.columns)

    forbidden_patterns = [
        "rank", "cutoff", "unified", "composite", "top_n",
        "buy_signal", "sell_signal", "buy_decision", "sell_decision",
        "recommendation", "action",
    ]
    for col in cols:
        for pattern in forbidden_patterns:
            assert pattern not in col.lower(), f"Forbidden field '{col}' found in scanner output!"


def test_summary_and_artifacts_export(mock_scanner_env, tmp_path: Path):
    """Summary 집계 일치 및 CSV / JSON 아티팩트 저장 검증."""
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )

    summary = res.summary
    assert summary.rows_emitted == len(res.rows)
    assert summary.cache_present_count == sum(1 for r in res.rows if r.cache_present)
    assert summary.raw_ready_count == sum(1 for r in res.rows if r.raw_data_ready)

    out_dir = tmp_path / "artifacts"
    csv_path, json_path = res.save_artifacts(output_dir=out_dir)

    assert csv_path.exists()
    assert json_path.exists()

    df_loaded = pd.read_csv(csv_path)
    assert len(df_loaded) == len(res.rows)

    with open(json_path, encoding="utf-8") as f:
        json_data = json.load(f)
    assert json_data["official_common_total"] == summary.official_common_total
    assert json_data["scan_target_count"] == summary.scan_target_count
    assert json_data["rows_emitted"] == summary.rows_emitted


def test_summary_candidate_investability_breakdown_aggregation(mock_scanner_env):
    """Summary의 candidate investability breakdown이 실제 row 값을 올바르게 집계하는지 검증.

    TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_01 (Major 2): 2,528종목
    Full Universe Scan을 다시 돌리지 않고, 이미 이 파일이 쓰는 synthetic
    small universe(mock_scanner_env, 실제 production `scan_pattern_a_universe()`
    코드 경로를 그대로 통과)로 "scanner summary가 row를 제대로 aggregate
    하는가"라는 coverage를 복원한다. hardcoded 숫자끼리 비교하지 않도록,
    expected count는 `res.rows`의 실제 candidate_state/investability_status
    값으로부터 계산한다.
    """
    res = scan_pattern_a_universe(
        cache=mock_scanner_env["cache"],
        as_of=mock_scanner_env["as_of"],
        universe_securities=mock_scanner_env["universe"],
    )
    summary = res.summary

    candidate_rows = [r for r in res.rows if r.candidate_state == PatternACandidateState.CANDIDATE]
    assert len(candidate_rows) > 0, "synthetic universe에 CANDIDATE row가 없어 이 회귀 검증이 무의미함"

    expected_investable = sum(
        1 for r in candidate_rows if r.investability_status == InvestabilityStatus.INVESTABLE
    )
    expected_filtered_market_cap = sum(
        1 for r in candidate_rows if r.investability_status == InvestabilityStatus.FILTERED_MARKET_CAP
    )
    expected_filtered_liquidity = sum(
        1 for r in candidate_rows if r.investability_status == InvestabilityStatus.FILTERED_LIQUIDITY
    )
    expected_data_unavailable = sum(
        1 for r in candidate_rows if r.investability_status == InvestabilityStatus.DATA_UNAVAILABLE
    )

    assert summary.candidate_raw_count == len(candidate_rows)
    assert summary.candidate_investable_count == expected_investable
    assert summary.candidate_filtered_market_cap_count == expected_filtered_market_cap
    assert summary.candidate_filtered_liquidity_count == expected_filtered_liquidity
    assert summary.candidate_data_unavailable_count == expected_data_unavailable

    assert (
        summary.candidate_investable_count
        + summary.candidate_filtered_market_cap_count
        + summary.candidate_filtered_liquidity_count
        + summary.candidate_data_unavailable_count
        == summary.candidate_raw_count
    )
