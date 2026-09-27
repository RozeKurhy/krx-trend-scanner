import pandas as pd

import scripts.analyze_fastcore_v2_exit4_effectiveness_v01 as e4
import scripts.analyze_fastcore_v2_exit4_threshold_sensitivity_v01 as m


def _post(*items):
    base = pd.Timestamp("2020-01-31")
    return [(base + pd.offsets.MonthEnd(i), s, sc) for i, (s, sc) in enumerate(items)]


CASES = [
    ("TRANSITION", _post(("EARLY_TREND", 50.0), ("PROGRESSED", 80.0), ("PROGRESSED", 90.0), ("PROGRESSED", 75.0), ("PROGRESSED", 60.0), ("WEAK", 40.0))),
    ("TRANSITION", _post(("PROGRESSED", 70.0), ("PROGRESSED", 85.0), ("PROGRESSED", 72.0), ("PROGRESSED", 61.0))),
    ("TRANSITION", _post(("EARLY_TREND", 50.0), ("PROGRESSED", 80.0), ("UNAVAILABLE", None), ("PROGRESSED", 70.0), ("TRANSITION", 60.0))),
    ("TRANSITION", _post(("BASE", 30.0))),
]


def test_t15_matches_exit4_effectiveness_replication():
    for entry, post in CASES:
        a = m.replicate_exit_path(entry, post, 15.0)
        b = e4.replicate_exit_path(entry, post)
        assert (a["exit_type"], a["signal_label"], a["hwm_at_signal"], a["score_at_signal"]) == \
            (b["exit_type"], b["signal_label"], b["hwm_at_signal"], b["score_at_signal"])


def test_threshold_changes_only_exit4_timing_and_hwm_is_shared():
    entry, post = CASES[0]
    t10, t15, t20, t25 = (m.replicate_exit_path(entry, post, t) for t in (10.0, 15.0, 20.0, 25.0))
    assert t10["exit_type"] == m.EXIT4 and t10["signal_label"] == post[3][0]      # 90 → 75 (15pt) ≥ 10
    assert t15["exit_type"] == m.EXIT4 and t15["signal_label"] == post[3][0]      # 15pt ≥ 15
    assert t20["exit_type"] == m.EXIT4 and t20["signal_label"] == post[4][0]      # 90 → 60 (30pt)
    assert t20["hwm_at_signal"] == t25["hwm_at_signal"] == 90.0
    # T25도 60에서 30pt ≥ 25로 같은 라벨
    assert t25["signal_label"] == post[4][0]
    # 아주 큰 threshold는 Exit3(WEAK)로 넘어간다
    assert m.replicate_exit_path(entry, post, 40.0)["exit_type"] == "EXIT3_PROGRESSED_TO_WEAK"
    # coverage 경로: T10은 85 → 72(13pt)에서, T15는 61(24pt)에서
    entry, post = CASES[1]
    assert m.replicate_exit_path(entry, post, 10.0)["signal_label"] == post[2][0]
    assert m.replicate_exit_path(entry, post, 15.0)["signal_label"] == post[3][0]
    assert m.replicate_exit_path(entry, post, 25.0)["exit_type"] == "NO_EXIT_BEFORE_CUTOFF"


def test_outcome_matches_runner_holding_rules():
    idx = pd.bdate_range("2020-01-02", periods=6)
    daily = pd.DataFrame({"open": [100, 105, 110, 90, 95, 97.0], "high": [102, 112, 115, 95, 99, 99.0],
                          "low": [98, 100, 105, 85, 90, 95.0], "close": [101, 110, 108, 92, 96, 98.0]}, index=idx)
    out = m.outcome(daily, idx[0], 100.0, idx[2], idx[-1], idx[-1])
    assert out["exit_date"] == idx[3] and out["terminal_return"] == -10.0
    assert out["mfe"] == 15.0 and out["mae"] == -10.0 and out["holding_days"] == 4 and out["giveback"] == 25.0
    open_out = m.outcome(daily, idx[0], 100.0, None, idx[-1], idx[-1])
    assert open_out["exit_date"] is None and open_out["terminal_return"] == -2.0 and open_out["holding_days"] == 6


def test_panel_better_and_verdict_rules():
    control = {"median": 40.0, "mean_excl_top5": 50.0, "ge_50": 100, "ge_100": 40, "le_neg_30": 10}
    better = {"median": 42.5, "mean_excl_top5": 51.0, "ge_50": 101, "ge_100": 41, "le_neg_30": 12}
    assert m.panel_better(better, control)[0] is True
    assert m.panel_better({**better, "median": 41.0}, control)[0] is False  # 2pp 미만
    simple = {f"SIMPLE_P{w}": True for w in ("1", "2-1", "2-2", "3-1")} | {"SIMPLE_P3-2": False}
    realistic = {"REALISTIC_P2-1_ELIGIBLE": True, "REALISTIC_P2-2_ELIGIBLE": True, "REALISTIC_P3-2_ELIGIBLE": False}
    flags = {10.0: {**simple, **realistic, "SIMPLE_POOLED_DEDUP": True}, 20.0: {}, 25.0: {}}
    assert m.verdict(flags, 100) == ("ALTERNATIVE_THRESHOLD_PROMISING", m.verdict(flags, 100)[1])
    assert m.verdict({10.0: {}, 20.0: {}, 25.0: {}}, 100)[0] == "T15_ROBUST"
    assert m.verdict({10.0: {"SIMPLE_P1": True, "SIMPLE_P2-1": True}, 20.0: {}, 25.0: {}}, 100)[0] == "MIXED_NO_CLEAR_WINNER"
    assert m.verdict({10.0: {}, 20.0: {}, 25.0: {}}, 5)[0] == "INSUFFICIENT_EVIDENCE"
