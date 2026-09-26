import pandas as pd
import pytest

import scripts.analyze_fastcore_v2_a_vs_c1_divergence_v01 as m


def _cache(stages, start="2020-01-31", scores=None):
    labels = pd.date_range(start, periods=len(stages), freq="ME")
    return pd.DataFrame({"label": labels, "effective": labels, "stage": stages,
                         "score": scores if scores is not None else [50.0] * len(stages)})


def test_held_labels_never_use_stages_after_holding_end():
    cache = _cache(["TRANSITION", "EARLY_TREND", "PROGRESSED", "WEAK", "PROGRESSED"])
    held = m.held_labels(cache, pd.Timestamp("2020-01-15"), pd.Timestamp("2020-12-31"), pd.Timestamp("2020-03-31"))
    assert list(held["stage"]) == ["TRANSITION", "EARLY_TREND", "PROGRESSED"]
    assert held["effective"].max() <= pd.Timestamp("2020-03-31")


def test_stage_events_anchor_departure_and_score_drawdown():
    held = _cache(["TRANSITION", "PROGRESSED", "UNAVAILABLE", "PROGRESSED", "WEAK", "BASE", "PROGRESSED"],
                  scores=[40.0, 80.0, None, 60.0, 30.0, 35.0, 70.0])
    events = m.stage_events("TRANSITION", held)
    assert events["anchor_label"] == pd.Timestamp("2020-02-29")
    assert events["stage_before_anchor"] == "TRANSITION"
    assert events["progressed_run_labels"] == 2
    assert events["first_departure_stage"] == "WEAK"
    assert events["returned_to_progressed_after_departure"] is True
    assert events["ever_weak_after_anchor"] and events["ever_base_after_anchor"] and not events["ever_transition_after_anchor"]
    # PROGRESSED 스냅샷끼리의 HWM - 점수 최대치: 80 → 60 = 20
    assert events["post_anchor_score_drawdown_max"] == 20.0
    assert events["post_anchor_path"] == "PROGRESSED(2)>WEAK>BASE>PROGRESSED"


def test_stage_events_without_progressed():
    assert m.stage_events("TRANSITION", _cache(["TRANSITION", "BASE"]))["anchor_index"] is None


def _daily():
    idx = pd.bdate_range("2020-01-02", periods=8)
    close = [100, 110, 90, 79, 70, 95, 60, 65]
    return pd.DataFrame({"open": close, "high": [c + 2 for c in close], "low": [c - 2 for c in close], "close": close}, index=idx)


def _row(**extra):
    base = {"entry_execution_date": "2020-01-02", "entry_open": 100.0, "entry_pattern_a_stage": "TRANSITION",
            "exit_execution_date": None, "exit_price": None, "terminal_return": -35.0, "mfe": 12.0, "mae": -42.0,
            "trade_status": "OPEN_AT_CUTOFF", "exit_type": "NO_EXIT_BEFORE_CUTOFF"}
    base.update(extra)
    return pd.Series(base)


def test_price_parity_replicates_runner_holding_window():
    parity = m.price_parity(_daily(), _row(), pd.Timestamp("2020-01-13"))
    assert parity["price_parity"] is True
    assert parity["recomputed_terminal"] == -35.0
    # 청산 거래는 청산 체결일 전날까지 + 청산 시가
    exited = _row(exit_execution_date="2020-01-08", exit_price=72.0, terminal_return=-28.0, mfe=12.0, mae=-28.0, trade_status="REALIZED")
    assert m.price_parity(_daily(), exited, pd.Timestamp("2020-01-13"))["price_parity"] is True
    assert m.price_parity(_daily(), _row(mfe=20.0), pd.Timestamp("2020-01-13"))["price_parity"] is False


def test_path_metrics_thresholds_use_closes_and_stage_at_touch():
    daily = _daily()
    held = pd.DataFrame({"effective": [pd.Timestamp("2020-01-03"), pd.Timestamp("2020-01-07")],
                         "stage": ["PROGRESSED", "WEAK"]})
    events = {"anchor_effective": pd.Timestamp("2020-01-03"), "first_departure_effective": pd.Timestamp("2020-01-07")}
    out = m.path_metrics(daily, _row(), pd.Timestamp("2020-01-13"), events, held)
    assert out["return_at_anchor"] == 10.0
    assert out["entry_to_anchor_trading_days"] == 2
    assert out["return_at_first_departure"] == -21.0
    # 종가 90(-10%)은 -15% 미도달, 79(-21%)에서 -15·-20 도달
    assert out["touch_15_date"] == "2020-01-07" and out["touch_20_date"] == "2020-01-07"
    assert out["touch_15_stage"] == "WEAK" and out["touch_15_prev_stage"] == "PROGRESSED"
    assert out["touch_30_date"] == "2020-01-08" and out["touch_30_after_departure"] is True
    assert out["touch_40_date"] == "2020-01-10" and out["touch_40_recovered_to_breakeven"] is False
    assert out["touch_50_date"] is None


def test_event_sequence_is_robust_to_missing_values():
    row = pd.Series({"entry_pattern_a_stage": "TRANSITION", "entry_to_anchor_trading_days": 10, "return_at_anchor": 12.3,
                     "first_departure_stage": "WEAK", "anchor_to_departure_trading_days": None, "return_at_first_departure": float("nan"),
                     "returned_to_progressed_after_departure": False, "touch_30_date": "2020-02-03", "touch_30_stage": "WEAK",
                     "touch_30_days_from_anchor": 40, "touch_50_date": None, "trade_status": "OPEN_AT_CUTOFF",
                     "exit_type": "NO_EXIT_BEFORE_CUTOFF", "terminal_return": -55.0})
    assert m.event_sequence(row) == "ENTRY[TRANSITION] > PROG@+10d(+12%) > DEPART:WEAK@+?d(?%) > TOUCH-30[WEAK]@+40d > OPEN(-55%)"


def test_tier():
    assert m.tier(20, 25) == "EVALUABLE"
    assert m.tier(20, 12) == "DESCRIPTIVE"
    assert m.tier(5, 100) == "INSUFFICIENT_EVIDENCE"
