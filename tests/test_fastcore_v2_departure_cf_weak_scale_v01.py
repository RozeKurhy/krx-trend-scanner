import pandas as pd
import pytest

import scripts.analyze_fastcore_v2_departure_cf_weak_scale_v01 as m


def _daily():
    idx = pd.bdate_range("2024-01-02", periods=5)
    return pd.DataFrame({"open": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)


def test_next_session_open_uses_the_session_after_observation_within_support():
    date, price = m.next_session_open(_daily(), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-31"))
    assert date == pd.Timestamp("2024-01-04") and price == 102.0
    # 관측일이 휴일이어도 그 이후 첫 거래일
    assert m.next_session_open(_daily(), pd.Timestamp("2023-12-31"), pd.Timestamp("2024-01-31"))[0] == pd.Timestamp("2024-01-02")
    assert m.next_session_open(_daily(), pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-31")) == (None, None)
    assert m.next_session_open(_daily(), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-03")) == (None, None)


def test_half_exit_and_net_cost_basis():
    assert m.half_exit(-60.0, -10.0) == -35.0
    assert m.pct(90.0, 100.0) == -10.0
    # 비용 없는 0% 가격 수익은 비용 반영 시 음수가 된다
    closed = m.net_return(0.0, 2024, True)
    open_mark = m.net_return(0.0, None, False)
    assert closed < open_mark < 0
    expected = (1.0 / (1.001 * 1.00015)) * (0.999 * (1 - 0.00015 - 0.0018)) - 1.0
    assert closed == pytest.approx(expected * 100.0, abs=1e-4)


def test_weak_return_pattern_and_groups():
    assert m.weak_return_pattern("PROGRESSED(3)")["departed"] is False
    p = m.weak_return_pattern("PROGRESSED(2)>TRANSITION(3)>EARLY_TREND")
    assert p == {"departed": True, "weak_after_departure": False, "returned_after_departure": False, "returned_after_weak": False}
    assert m.departure_group(p) == "NO_WEAK_NO_RETURN"
    p = m.weak_return_pattern("PROGRESSED>TRANSITION>PROGRESSED(2)>BASE")
    assert m.departure_group(p) == "NO_WEAK_RETURN"
    p = m.weak_return_pattern("PROGRESSED>TRANSITION>WEAK(4)>BASE")
    assert m.departure_group(p) == "WEAK_NO_RETURN"
    # WEAK 이전의 복귀는 WEAK 이후 복귀가 아니다
    p = m.weak_return_pattern("PROGRESSED>TRANSITION>PROGRESSED>WEAK>BASE")
    assert p["returned_after_departure"] and not p["returned_after_weak"]
    assert m.departure_group(p) == "WEAK_NO_RETURN"
    p = m.weak_return_pattern("PROGRESSED>WEAK>TRANSITION>PROGRESSED(5)")
    assert m.departure_group(p) == "WEAK_THEN_RETURN"
    assert m.departure_group(m.weak_return_pattern("PROGRESSED(4)")) is None


def test_tier_and_return_stats():
    assert m.tier(20) == "EVALUABLE" and m.tier(10) == "DESCRIPTIVE" and m.tier(3) == "INSUFFICIENT_EVIDENCE"
    stats = m.return_stats(pd.Series([100.0, 50.0, -30.0, -60.0]))
    assert stats["n"] == 4 and stats["ge_50"] == 2 and stats["ge_100"] == 1
    assert stats["le_neg_30"] == 2 and stats["le_neg_60"] == 1
