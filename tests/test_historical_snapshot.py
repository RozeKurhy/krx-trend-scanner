import json
import math
from dataclasses import fields
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    MarketCalendarUnavailableError,
    get_canonical_market_calendar,
    get_reference_market_month_ends,
    is_completed_market_month,
)
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.feature_report import FeatureRow
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
    to_csv_row,
)

ROOT = Path(__file__).resolve().parent.parent


def _daily_frame(n: int, start: str = "2015-01-01", freq: str = "D") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq=freq)
    close = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * n,
            "trading_value": [1.0e8] * n,
        },
        index=index,
    )


def _assert_features_equal(a: FeatureRow, b: FeatureRow) -> None:
    for f in fields(a):
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, float) and isinstance(vb, float) and math.isnan(va) and math.isnan(vb):
            continue
        assert va == vb, f"{f.name}: {va!r} != {vb!r}"


def test_snapshot_excludes_data_after_snapshot_date():
    daily = _daily_frame(1500)
    snapshot_date = daily.index[900]

    snap_from_full = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    truncated = daily[daily.index <= snapshot_date]
    snap_from_truncated = build_historical_snapshot("TEST", "테스트", truncated, snapshot_date)

    assert snap_from_full.effective_as_of == snapshot_date
    _assert_features_equal(snap_from_full.features, snap_from_truncated.features)

    # 미래 데이터가 있는 daily를 넘겨도 daily_rows는 snapshot_date까지만 세어야 한다.
    assert snap_from_full.features.daily_rows == len(truncated)
    assert snap_from_full.features.daily_rows < len(daily)


def test_non_trading_snapshot_date_uses_last_trading_day():
    daily = _daily_frame(400, freq="B")  # 영업일만 있는 데이터 -> 토/일은 index에 없음
    fridays = daily.index[daily.index.weekday == 4]
    friday = fridays[50]
    saturday = friday + pd.Timedelta(days=1)
    assert saturday not in daily.index

    snap_on_saturday = build_historical_snapshot("TEST", "테스트", daily, saturday)
    snap_on_friday = build_historical_snapshot("TEST", "테스트", daily, friday)

    assert snap_on_saturday.requested_snapshot_date == saturday
    assert snap_on_saturday.effective_as_of == friday
    _assert_features_equal(snap_on_saturday.features, snap_on_friday.features)


def test_insufficient_history_returns_nan_without_error():
    daily = _daily_frame(40)  # 약 1.3개월치 -> 36개월 range 계산 불가
    snapshot_date = daily.index[-1]

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.effective_as_of == snapshot_date
    assert math.isnan(snap.features.range_36m)
    assert math.isnan(snap.features.ma24)


def test_snapshot_before_any_data_returns_empty_result_without_error():
    daily = _daily_frame(40)
    snapshot_date = daily.index[0] - pd.Timedelta(days=10)

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.effective_as_of is None
    assert snap.features.as_of is None
    assert snap.features.daily_rows == 0
    assert math.isnan(snap.features.close)


def test_future_data_does_not_change_past_snapshot():
    daily_a = _daily_frame(1200)
    daily_b = _daily_frame(1900)  # daily_a와 같은 산식이라 앞부분이 완전히 동일하다
    snapshot_date = daily_a.index[1000]

    snap_a = build_historical_snapshot("TEST", "테스트", daily_a, snapshot_date)
    snap_b = build_historical_snapshot("TEST", "테스트", daily_b, snapshot_date)

    assert snap_a.effective_as_of == snap_b.effective_as_of == snapshot_date
    _assert_features_equal(snap_a.features, snap_b.features)


def _mid_month_daily_frame() -> pd.DataFrame:
    # 2020-01-01 ~ 2024-05-15(수)까지의 영업일 데이터.
    index = pd.date_range("2020-01-01", "2024-05-15", freq="B")
    close = [100.0 + i * 0.1 for i in range(len(index))]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * len(index),
            "trading_value": [1.0e8] * len(index),
        },
        index=index,
    )


def test_completed_vs_live_monthly_around_mid_month_snapshot():
    daily = _mid_month_daily_frame()
    assert daily.index[-1] == pd.Timestamp("2024-05-15")
    snapshot_date = daily.index[-1]

    monthly_full = to_monthly(daily)
    cal = MarketCalendarAuthority.from_dates(
        pd.date_range("2020-01-01", "2024-05-31", freq="B"),
        last_completed_month="2024-04",
    )

    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True, market_calendar=cal
    )
    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False, market_calendar=cal
    )

    assert snap_live.features.monthly_rows == snap_completed.features.monthly_rows + 1
    assert snap_live.features.close == pytest.approx(monthly_full["close"].iloc[-1])
    assert snap_completed.features.close == pytest.approx(monthly_full["close"].iloc[-2])
    assert snap_completed.features.monthly_bar_may_be_incomplete is False


def test_completed_mode_drops_incomplete_weekly_bar():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]  # 2024-05-15(수), 그 주 금요일(5/17)은 아직 안 옴

    weekly_full = to_weekly(daily)
    cal = MarketCalendarAuthority.from_dates(
        pd.date_range("2020-01-01", "2024-05-31", freq="B"),
        last_completed_month="2024-04",
    )

    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False, market_calendar=cal
    )

    assert snap_completed.weekly_as_of == weekly_full.index[-2]
    assert snap_completed.features.weekly_rows == len(weekly_full) - 1
    assert snap_completed.features.weekly_bar_may_be_incomplete is False


def test_live_mode_keeps_incomplete_weekly_bar():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]

    weekly_full = to_weekly(daily)
    cal = MarketCalendarAuthority.from_dates(
        pd.date_range("2020-01-01", "2024-05-31", freq="B"),
        last_completed_month="2024-04",
    )

    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True, market_calendar=cal
    )

    assert snap_live.weekly_as_of == weekly_full.index[-1]
    assert snap_live.features.weekly_rows == len(weekly_full)


def test_monthly_as_of_and_weekly_as_of_reflect_completed_trim():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]
    monthly_full = to_monthly(daily)
    weekly_full = to_weekly(daily)
    cal = MarketCalendarAuthority.from_dates(
        pd.date_range("2020-01-01", "2024-05-31", freq="B"),
        last_completed_month="2024-04",
    )

    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False, market_calendar=cal
    )
    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True, market_calendar=cal
    )

    assert snap_completed.monthly_as_of == monthly_full.index[-2]
    assert snap_completed.weekly_as_of == weekly_full.index[-2]
    assert snap_live.monthly_as_of == monthly_full.index[-1]
    assert snap_live.weekly_as_of == weekly_full.index[-1]


def test_monthly_as_of_and_weekly_as_of_none_when_no_data():
    daily = _daily_frame(40)
    snapshot_date = daily.index[0] - pd.Timedelta(days=10)

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.monthly_as_of is None
    assert snap.weekly_as_of is None


def test_monthly_field_matches_features_and_excludes_post_snapshot_data():
    daily = _daily_frame(1500)
    snapshot_date = daily.index[900]
    cal = MarketCalendarAuthority.from_dates(daily.index)

    snap = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False, market_calendar=cal
    )

    assert snap.monthly.index.max() <= snapshot_date
    assert float(snap.monthly["close"].iloc[-1]) == pytest.approx(snap.features.close)


def test_to_csv_row_includes_snapshot_metadata_and_feature_fields():
    daily = _daily_frame(1200)
    snapshot_date = daily.index[900]
    cal = MarketCalendarAuthority.from_dates(daily.index)
    snapshot = build_historical_snapshot(
        "068270", "셀트리온", daily, snapshot_date, include_incomplete_periods=False, market_calendar=cal
    )

    row = to_csv_row("pre_breakout", snapshot)

    assert row["label"] == "pre_breakout"
    assert row["requested_snapshot_date"] == snapshot_date
    assert row["effective_as_of"] == snapshot.effective_as_of
    assert row["include_incomplete_periods"] is False
    assert row["monthly_as_of"] == snapshot.monthly_as_of
    assert row["weekly_as_of"] == snapshot.weekly_as_of
    assert row["ticker"] == "068270"
    assert row["close"] == pytest.approx(snapshot.features.close)


# ==============================================================================
# Terminal Partial Month & Architectural Regression Tests (w.md Sections 10-13)
# ==============================================================================

def test_synthetic_terminal_partial_month_regression():
    """Section 10: Terminal Partial Month 오판 방지 회귀 테스트.
    
    Synthetic Calendar: 2026-07-31 및 2026-08-03 ~ 2026-08-14
    max_observed_trading_date = 2026-08-14
    last_completed_market_month = 2026-07
    
    기대:
    - is_completed_month('2026-07-31') == True
    - is_completed_month('2026-08-14') == False
    - get_actual_month_end(2026, 7) == Timestamp('2026-07-31')
    - get_actual_month_end(2026, 8) is None
    """
    dates = pd.date_range("2026-07-01", "2026-07-31", freq="B").union(
        pd.date_range("2026-08-01", "2026-08-14", freq="B")
    )
    cal = MarketCalendarAuthority.from_dates(
        dates=dates,
        last_completed_month="2026-07",
        source_name="SYNTHETIC_PARTIAL_AUGUST",
    )

    assert cal.is_completed_month("2026-07-31") is True
    assert cal.is_completed_month("2026-08-14") is False
    assert cal.get_actual_month_end(2026, 7) == pd.Timestamp("2026-07-31")
    assert cal.get_actual_month_end(2026, 8) is None


def test_synthetic_full_terminal_month_regression():
    """Section 11: Full Month Terminal 회귀 테스트.
    
    마지막 월이 완전히 종료된 시점에 생성된 경우(last_completed = 2026-07),
    2026-07-31은 정상적으로 completed로 인정되어야 함.
    """
    dates = pd.date_range("2026-07-01", "2026-07-31", freq="B")
    cal = MarketCalendarAuthority.from_dates(
        dates=dates,
        last_completed_month="2026-07",
        source_name="SYNTHETIC_FULL_JULY",
    )

    assert cal.is_completed_month("2026-07-31") is True
    assert cal.get_actual_month_end(2026, 7) == pd.Timestamp("2026-07-31")


def test_partial_month_snapshot_regression():
    """Section 12: Partial Month Snapshot 시 미완성 월봉 배제 검증.
    
    2026-08-14 snapshot 시 8월 partial monthly bar가 배제되고
    monthly_as_of는 2026-07-31이어야 한다.
    """
    daily = _daily_frame(600, start="2024-01-01", freq="B")
    # 마지막 날짜를 2026-08-14로 설정
    daily.index = pd.date_range(end="2026-08-14", periods=len(daily), freq="B")
    snapshot_date = pd.Timestamp("2026-08-14")

    snap = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )

    assert snap.monthly_as_of == pd.Timestamp("2026-07-31")
    assert pd.Timestamp("2026-08-31") not in snap.monthly.index


def test_canonical_actual_20260814_regression():
    """Section 13: 실제 Canonical Calendar의 2026-08-14 Cutoff 검증.
    
    - max_observed_trading_date: 2026-08-14
    - 2026-08-14 completed: False
    - 2026-07-31 completed: True
    - get_actual_month_end(2026, 8) is None
    - get_actual_month_end(2026, 7) == 2026-07-31
    """
    cal = get_canonical_market_calendar()

    assert cal.max_observed_trading_date == pd.Timestamp("2026-08-14")
    assert cal.is_completed_month("2026-08-14") is False
    assert cal.is_completed_month("2026-07-31") is True
    assert cal.get_actual_month_end(2026, 8) is None
    assert cal.get_actual_month_end(2026, 7) == pd.Timestamp("2026-07-31")


def test_synthetic_individual_stock_trading_halt_regression():
    """Section 10: 개별 종목 거래정지 시 시장 월말 판정 왜곡 방지 검증."""
    market_dates = pd.to_datetime(["2018-04-25", "2018-04-26", "2018-04-27", "2018-04-30"])
    cal = MarketCalendarAuthority.from_dates(
        market_dates,
        last_completed_month="2018-04",
        source_name="SYNTHETIC_KRX_MARKET",
    )

    # 4/27 시점: 시장 월말(4/30) 이전이므로 4월 월봉은 미완성으로 판정되어야 함
    assert cal.is_completed_month("2018-04-27") is False

    # 4/30 시점: 시장 월말 도달 시점에 비로소 4월 월봉이 완성됨
    assert cal.is_completed_month("2018-04-30") is True


def test_calendar_source_cache_isolation_regression():
    """Section 11: 서로 다른 Calendar Source 간 캐시 오염 방지(Cache Isolation) 검증."""
    cal_a = MarketCalendarAuthority.from_dates(
        ["2025-08-27", "2025-08-28", "2025-08-29"],
        last_completed_month="2025-08",
        source_name="CAL_A",
    )
    cal_b = MarketCalendarAuthority.from_dates(
        ["2025-08-27", "2025-08-28"],
        last_completed_month="2025-08",
        source_name="CAL_B",
    )

    # A에서는 8/28이 월말 미도달(False), 8/29가 월말(True)
    assert cal_a.is_completed_month("2025-08-28") is False
    assert cal_a.is_completed_month("2025-08-29") is True

    # B에서는 8/28이 이미 월말(True)
    assert cal_b.is_completed_month("2025-08-28") is True

    # 교차 재확인: B 호출 후에도 A의 결과가 변하지 않음
    assert cal_a.is_completed_month("2025-08-28") is False
    assert cal_a.is_completed_month("2025-08-29") is True


def test_authority_missing_fail_closed_regression(tmp_path):
    """Section 12: 캘린더 Authority 부재 시 silent calendar fallback 없이 명시적 예외 발생(Fail Closed) 검증."""
    non_existent_path = tmp_path / "non_existent_calendar.parquet"

    with pytest.raises(MarketCalendarUnavailableError) as exc_info:
        MarketCalendarAuthority.from_parquet(non_existent_path)

    assert "KRX canonical trading calendar file not found" in str(exc_info.value)


def test_historical_samsung_2018_trading_halt_month_end_accuracy():
    """Section 15: 2018년 삼성전자(005930) 액면분할 거래정지(4/30) 시 실제 KRX 시장 월말 판정 정확성 검증."""
    cal = get_canonical_market_calendar()
    actual_apr_me = cal.get_actual_month_end(2018, 4)

    assert actual_apr_me == pd.Timestamp("2018-04-30")
    assert cal.is_completed_month("2018-04-27") is False
    assert cal.is_completed_month("2018-04-30") is True


# ==============================================================================
# Mandatory Boundary Regression Tests (Cases A - F)
# ==============================================================================

def test_regression_case_a_actual_market_month_end_earlier_than_calendar_end():
    """Case A: 2025-08-29(금)은 8월 마지막 거래일이나 달력 말일(8/31 일)보다 빠름.
    8월 완성 월봉이 정상 포함되어야 한다 (monthly_as_of == 2025-08-31).
    """
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("035720")
    assert daily is not None

    snap = build_historical_snapshot("035720", "카카오", daily, "2025-08-29", include_incomplete_periods=False)
    assert snap.monthly_as_of == pd.Timestamp("2025-08-31")

    eval_res = evaluate_pattern_a(snap)
    assert eval_res.lifecycle_stage is not None
    assert eval_res.lifecycle_stage.value.upper() == "EARLY_TREND"
    assert eval_res.score == pytest.approx(99.09, abs=0.5)


def test_regression_case_b_month_middle_excludes_current_month():
    """Case B: 2025-09-12(금)은 9월 진행 중이므로 9월 bar는 제외되고 8월 bar까지만 포함되어야 한다."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("035720")
    assert daily is not None

    snap = build_historical_snapshot("035720", "카카오", daily, "2025-09-12", include_incomplete_periods=False)
    assert snap.monthly_as_of == pd.Timestamp("2025-08-31")
    assert snap.weekly_as_of == pd.Timestamp("2025-09-12")

    eval_res = evaluate_pattern_a(snap)
    assert eval_res.lifecycle_stage is not None
    assert eval_res.lifecycle_stage.value.upper() == "EARLY_TREND"


def test_regression_case_c_calendar_month_end_equals_actual_market_end():
    """Case C: 2025-09-30(화)은 달력 말일과 시장 말일이 동일하여 9월 bar가 정상 포함된다."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("035720")
    assert daily is not None

    snap = build_historical_snapshot("035720", "카카오", daily, "2025-09-30", include_incomplete_periods=False)
    assert snap.monthly_as_of == pd.Timestamp("2025-09-30")

    eval_res = evaluate_pattern_a(snap)
    assert eval_res.lifecycle_stage is not None
    assert eval_res.lifecycle_stage.value.upper() == "TRANSITION"
    assert eval_res.score == pytest.approx(98.38, abs=0.5)


def test_regression_case_d_year_end_early_closure():
    """Case D: 2025-12-30(화)은 납세/휴장으로 인한 연말 시장 마감일(달력 말일은 12/31)이나 12월 bar가 정상 포함된다."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("035720")
    assert daily is not None

    snap = build_historical_snapshot("035720", "카카오", daily, "2025-12-30", include_incomplete_periods=False)
    assert snap.monthly_as_of == pd.Timestamp("2025-12-31")

    eval_res = evaluate_pattern_a(snap)
    assert eval_res.lifecycle_stage is not None
    assert eval_res.lifecycle_stage.value.upper() == "PROGRESSED"


def test_regression_case_e_future_row_append_pit_invariant():
    """Case E: snapshot 일자 이후의 미래 일봉 데이터를 추가해도 과거 snapshot 결과가 변하지 않는다."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily_full = cache.load("035720")
    assert daily_full is not None

    snap_date = "2025-08-29"
    daily_past_only = daily_full[daily_full.index <= pd.Timestamp(snap_date)]

    snap_from_past = build_historical_snapshot("035720", "카카오", daily_past_only, snap_date, include_incomplete_periods=False)
    snap_from_future = build_historical_snapshot("035720", "카카오", daily_full, snap_date, include_incomplete_periods=False)

    assert snap_from_past.monthly_as_of == snap_from_future.monthly_as_of
    assert snap_from_past.weekly_as_of == snap_from_future.weekly_as_of
    _assert_features_equal(snap_from_past.features, snap_from_future.features)


def test_regression_case_f_fast_evaluator_parity():
    """Case F: historical snapshot correction 이후에도 FAST frozen contract 산식 자체는 불변이다."""
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load("035720")
    assert daily is not None

    score_contract = json.loads((ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json").read_text(encoding="utf-8"))
    stage_contract = json.loads((ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json").read_text(encoding="utf-8"))

    w = pd.Timestamp("2025-09-12")
    res = evaluate_pattern_a_fast("035720", "카카오", daily[daily.index <= w], w, score_contract, stage_contract)

    assert res["fast_machine_stage"] == "TRIGGER"
    assert res["fast_machine_stage_status"] == "READY"
    assert res["fast_monthly_permission_state"] == "PERMITTED_REGIME"
    assert res["fast_daily_risk_state"] == "NORMAL"
    assert res["pattern_a_stage"] == "early_trend"
    assert res["fast_score"] == pytest.approx(74.99, abs=0.1)
