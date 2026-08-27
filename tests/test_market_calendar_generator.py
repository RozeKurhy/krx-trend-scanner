"""Tests for KRX Market Calendar Generator and Strict Artifact Invariants."""

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_krx_trading_calendar import build_krx_trading_calendar_from_dates
from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    MarketCalendarUnavailableError,
    get_canonical_market_calendar,
)

ROOT = Path(__file__).resolve().parent.parent


def test_generator_regression_a_actual_market_end_earlier_than_calendar_end(tmp_path):
    """Section 10: Regression A - 실제 시장 월말(2025-08-29 금)이 달력 말일(2025-08-31 일)보다 빠른 경우.
    
    입력:
    - trading_dates: 2025-08-27, 2025-08-28, 2025-08-29
    - cutoff_date: 2025-08-29
    - last_completed_market_month_end: 2025-08-29
    
    기대:
    - 2025-08-29이 completed_month_ends에 정상 포함됨 (8월 completed = True)
    - 달력 말일(31일)이 아니라는 이유로 incomplete 처리되면 안 됨.
    """
    dates = ["2025-08-27", "2025-08-28", "2025-08-29"]
    cal_df, meta = build_krx_trading_calendar_from_dates(
        trading_dates=dates,
        cutoff_date="2025-08-29",
        last_completed_market_month_end="2025-08-29",
        output_dir=tmp_path,
    )

    assert meta["last_completed_market_month"] == "2025-08"
    assert meta["last_completed_market_month_end_date"] == "2025-08-29"
    assert "2025-08-29" in meta["completed_month_ends"]
    assert meta["terminal_partial_month"] is None

    # Load via MarketCalendarAuthority
    cal = MarketCalendarAuthority.from_parquet(tmp_path / "krx_trading_calendar.parquet")
    assert cal.is_completed_month("2025-08-29") is True
    assert cal.get_actual_month_end(2025, 8) == pd.Timestamp("2025-08-29")


def test_generator_regression_b_partial_cutoff(tmp_path):
    """Section 11: Regression B - 월말 전 Cutoff (Terminal Partial Month).
    
    입력:
    - trading_dates: 2025-07-31, 2025-08-01 ... 2025-08-28
    - cutoff_date: 2025-08-28
    - last_completed_market_month_end: 2025-07-31
    
    기대:
    - 7월은 completed_month_ends에 포함.
    - 8월은 completed_month_ends에 미포함 (terminal_partial_month == '2025-08')
    - 2025-08-28이 observed max라는 이유로 8월 month end로 오판 금지.
    """
    dates = ["2025-07-30", "2025-07-31", "2025-08-01", "2025-08-27", "2025-08-28"]
    cal_df, meta = build_krx_trading_calendar_from_dates(
        trading_dates=dates,
        cutoff_date="2025-08-28",
        last_completed_market_month_end="2025-07-31",
        output_dir=tmp_path,
    )

    assert meta["last_completed_market_month"] == "2025-07"
    assert meta["last_completed_market_month_end_date"] == "2025-07-31"
    assert "2025-07-31" in meta["completed_month_ends"]
    assert "2025-08-28" not in meta["completed_month_ends"]
    assert meta["terminal_partial_month"] == "2025-08"

    cal = MarketCalendarAuthority.from_parquet(tmp_path / "krx_trading_calendar.parquet")
    assert cal.is_completed_month("2025-07-31") is True
    assert cal.is_completed_month("2025-08-28") is False
    assert cal.get_actual_month_end(2025, 8) is None


def test_generator_regression_c_terminal_full_month(tmp_path):
    """Section 12: Regression C - Terminal Full Month.
    
    마지막 월이 완전히 종료된 시점에 생성된 경우(cutoff == last_completed == 2026-07-31),
    마지막 달을 무조건 incomplete로 만들지 않고 정상 completed로 인정.
    """
    dates = pd.date_range("2026-07-01", "2026-07-31", freq="B")
    cal_df, meta = build_krx_trading_calendar_from_dates(
        trading_dates=dates,
        cutoff_date="2026-07-31",
        last_completed_market_month_end="2026-07-31",
        output_dir=tmp_path,
    )

    assert meta["last_completed_market_month"] == "2026-07"
    assert meta["last_completed_market_month_end_date"] == "2026-07-31"
    assert "2026-07-31" in meta["completed_month_ends"]
    assert meta["terminal_partial_month"] is None

    cal = MarketCalendarAuthority.from_parquet(tmp_path / "krx_trading_calendar.parquet")
    assert cal.is_completed_month("2026-07-31") is True
    assert cal.get_actual_month_end(2026, 7) == pd.Timestamp("2026-07-31")


def test_artifact_corruption_regression_rejects_premature_month_end(tmp_path):
    """Section 13: Artifact Corruption Regression.
    
    trading_dates에 2025-08-28, 2025-08-29가 모두 존재하는데
    metadata/parquet에 completed_month_end = 2025-08-28로 잘못 기록된 경우,
    from_parquet()에서 즉시 reject (MarketCalendarUnavailableError)되어야 한다.
    """
    # Create corrupted calendar
    trading_dates = pd.to_datetime(["2025-08-27", "2025-08-28", "2025-08-29"])
    df = pd.DataFrame({
        "trading_date": trading_dates,
        "is_completed_month_end": [False, True, False],  # 8/28을 month end로 잘못 지정
    })
    p_path = tmp_path / "krx_trading_calendar.parquet"
    df.to_parquet(p_path, index=False)

    meta = {
        "calendar_source": "CORRUPTED_TEST",
        "last_completed_market_month": "2025-08",
        "last_completed_market_month_end_date": "2025-08-28",
        "completed_month_ends_count": 1,
        "completed_month_ends": ["2025-08-28"],
    }
    (tmp_path / "krx_trading_calendar.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(MarketCalendarUnavailableError) as exc_info:
        MarketCalendarAuthority.from_parquet(p_path)

    assert "does not match the actual observed month-end trading date" in str(exc_info.value)


def test_generator_input_validation_boundary_errors():
    """Generator 입력 검증 에러 케이스 테스트."""
    dates = ["2025-08-27", "2025-08-28", "2025-08-29"]

    # 1. last_completed가 cutoff보다 미래인 경우
    with pytest.raises(ValueError, match="cannot be in the future beyond cutoff_date"):
        build_krx_trading_calendar_from_dates(dates, cutoff_date="2025-08-28", last_completed_market_month_end="2025-08-29")

    # 2. last_completed가 trading_dates에 없는 날짜인 경우 (예: 8/25와 8/27 사이의 8/26)
    with pytest.raises(ValueError, match="not a valid trading day"):
        build_krx_trading_calendar_from_dates(["2025-08-25", "2025-08-27", "2025-08-29"], cutoff_date="2025-08-29", last_completed_market_month_end="2025-08-26")

    # 3. last_completed가 해당 월의 max trading date와 불일치하는 경우
    with pytest.raises(ValueError, match="must match the actual last trading date of that month"):
        build_krx_trading_calendar_from_dates(dates, cutoff_date="2025-08-29", last_completed_market_month_end="2025-08-28")


def test_current_canonical_artifact_reproducibility():
    """Section 14: 현재 Canonical Artifact 재현성 및 불변성 검증."""
    cal = get_canonical_market_calendar()

    assert cal.min_date == pd.Timestamp("2011-01-03")
    assert cal.max_observed_trading_date in (pd.Timestamp("2026-08-14"), pd.Timestamp("2026-08-21"))
    assert len(cal.trading_dates) in (3840, 3844)

    meta = cal.metadata
    assert meta["last_completed_market_month"] == "2026-07"
    assert meta["last_completed_market_month_end_date"] == "2026-07-31"
    assert meta["completed_month_ends_count"] == 187
    assert meta["terminal_partial_month"] == "2026-08"

    assert cal.is_completed_month("2026-07-31") is True
    assert cal.is_completed_month("2026-08-14") is False
    assert cal.get_actual_month_end(2026, 8) is None
    assert cal.get_actual_month_end(2026, 7) == pd.Timestamp("2026-07-31")
