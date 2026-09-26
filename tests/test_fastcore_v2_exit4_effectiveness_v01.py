import pandas as pd

import scripts.analyze_fastcore_v2_exit4_effectiveness_v01 as m


def _post(*items):
    base = pd.Timestamp("2020-01-31")
    return [(base + pd.offsets.MonthEnd(i), s, sc) for i, (s, sc) in enumerate(items)]


def test_normal_path_exit4_uses_handoff_score_as_initial_hwm():
    post = _post(("EARLY_TREND", 50.0), ("PROGRESSED", 80.0), ("PROGRESSED", 90.0), ("PROGRESSED", 75.0))
    out = m.replicate_exit_path("TRANSITION", post)
    assert out["lifecycle"] == "NORMAL_EARLY_TREND_HANDOFF"
    assert out["exit_type"] == m.EXIT4 and out["signal_label"] == post[3][0]
    assert out["hwm_at_signal"] == 90.0 and out["score_at_signal"] == 75.0


def test_normal_path_exit3_and_unavailable_ignored():
    post = _post(("EARLY_TREND", 50.0), ("PROGRESSED", 80.0), ("UNAVAILABLE", None), ("PROGRESSED", 70.0), ("TRANSITION", 60.0))
    out = m.replicate_exit_path("TRANSITION", post)
    # 80 → 70은 10pt 하락이라 Exit4 아님, TRANSITION에서 Exit3
    assert out["exit_type"] == "EXIT3_PROGRESSED_TO_TRANSITION" and out["signal_label"] == post[4][0]


def test_coverage_path_exit4_and_departure_ends_monitoring():
    post = _post(("PROGRESSED", 70.0), ("PROGRESSED", 85.0), ("PROGRESSED", 69.0))
    out = m.replicate_exit_path("TRANSITION", post)
    assert out["lifecycle"] == "SKIPPED_EARLY_TREND_HANDOFF"
    assert out["exit_type"] == m.EXIT4 and out["hwm_at_signal"] == 85.0
    # coverage에서는 UNAVAILABLE도 감시 종료 → 이후 Exit4가 와도 미청산
    post = _post(("PROGRESSED", 70.0), ("UNAVAILABLE", None), ("PROGRESSED", 50.0))
    assert m.replicate_exit_path("TRANSITION", post)["exit_type"] == "NO_EXIT_BEFORE_CUTOFF"
    assert m.replicate_exit_path("TRANSITION", _post(("BASE", 30.0)))["exit_type"] == "NO_PROGRESSED_BEFORE_CUTOFF"


def test_first_departure_after_skips_unavailable():
    post = _post(("PROGRESSED", 80.0), ("PROGRESSED", 60.0), ("UNAVAILABLE", None), ("PROGRESSED", 70.0), ("WEAK", 40.0))
    label, stage = m.first_departure_after(post, post[1][0])
    assert label == post[4][0] and stage == "WEAK"
    assert m.first_departure_after(post[:4], post[1][0]) == (None, None)


def test_next_session_open_after_label_and_classification():
    daily = pd.DataFrame({"open": [10.0, 11.0]}, index=pd.to_datetime(["2020-02-28", "2020-03-02"]))
    # 라벨이 주말(2020-02-29)이면 다음 거래일
    assert m.next_session_open(daily, pd.Timestamp("2020-02-29"), pd.Timestamp("2020-03-31")) == (pd.Timestamp("2020-03-02"), 11.0)
    assert m.next_session_open(daily, pd.Timestamp("2020-03-02"), pd.Timestamp("2020-03-31")) == (None, None)
    assert m.classify(-10.0) == "EXIT4_CLEARLY_HELPFUL"
    assert m.classify(9.99) == "EXIT4_ROUGHLY_REDUNDANT"
    assert m.classify(10.0) == "EXIT4_POTENTIALLY_HARMFUL"
    assert m.classify(None) == "INSUFFICIENT_EVIDENCE"
