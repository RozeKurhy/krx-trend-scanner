import pandas as pd

import scripts.analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01 as m


def _seq(*stages):
    return [(pd.Timestamp("2020-01-31") + pd.offsets.MonthEnd(i), s) for i, s in enumerate(stages)]


def test_replicate_ledger_lifecycle_matches_simulator_rules():
    assert m.replicate_ledger_lifecycle("TRANSITION", _seq("EARLY_TREND", "PROGRESSED"))[0] == "NORMAL_EARLY_TREND_HANDOFF"
    assert m.replicate_ledger_lifecycle("TRANSITION", _seq("PROGRESSED"))[0] == "SKIPPED_EARLY_TREND_HANDOFF"
    # EARLY_TREND를 본 뒤 TRANSITION에서 PROGRESSED로 가면 skipped가 아니다.
    assert m.replicate_ledger_lifecycle("TRANSITION", _seq("EARLY_TREND", "TRANSITION", "PROGRESSED"))[0] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
    assert m.replicate_ledger_lifecycle("TRANSITION", _seq("BASE", "WEAK"))[0] == "NEVER_PROGRESSED"
    # UNAVAILABLE은 직전 유효 stage를 바꾸지 않는다.
    label, first = m.replicate_ledger_lifecycle("EARLY_TREND", _seq("UNAVAILABLE", "PROGRESSED"))
    assert label == "NORMAL_EARLY_TREND_HANDOFF" and first == pd.Timestamp("2020-02-29")


def test_holding_partition_first_late_never():
    assert m.classify_holding("EARLY_TREND", _seq("PROGRESSED"))["group"] == m.HOLDING_A
    late = m.classify_holding("TRANSITION", _seq("PROGRESSED", "EARLY_TREND", "PROGRESSED"))
    assert late["group"] == m.HOLDING_B and late["first_progressed_index"] == 1 and late["first_direct_index"] == 3
    c1 = m.classify_holding("TRANSITION", _seq("PROGRESSED", "TRANSITION"))
    assert (c1["group"], c1["subgroup"]) == (m.HOLDING_C, m.HOLDING_C1)
    c2 = m.classify_holding("TRANSITION", _seq("TRANSITION", "BASE"))
    assert (c2["group"], c2["subgroup"]) == (m.HOLDING_C, m.HOLDING_C2)
    assert m.classify_holding("TRANSITION", [])["subgroup"] == m.HOLDING_C2


def test_handoff_origin_walk_back_including_pre_entry():
    pre = _seq("WEAK", "EARLY_TREND")
    # EARLY_TREND 진입이면 진입 전 라벨로 넘어가 WEAK를 찾는다.
    holding = m.classify_holding("EARLY_TREND", _seq("EARLY_TREND", "UNAVAILABLE", "PROGRESSED"))
    assert m.walk_back_origin(holding["sequence"], holding["first_direct_index"], pre) == "WEAK"
    holding = m.classify_holding("TRANSITION", _seq("EARLY_TREND", "PROGRESSED"))
    assert m.walk_back_origin(holding["sequence"], holding["first_direct_index"], pre) == "TRANSITION"
    holding = m.classify_holding("TRANSITION", _seq("PROGRESSED", "EARLY_TREND", "PROGRESSED"))
    assert m.walk_back_origin(holding["sequence"], holding["first_direct_index"], pre) == "PROGRESSED"
    assert m.walk_back_origin([(None, "EARLY_TREND")], 1, []) == "UNKNOWN"
    assert m.origin_group("UNKNOWN") == "OTHER" and m.origin_group("BASE") == "BASE"


def test_strict_examples_from_spec():
    assert m.classify_strict("EARLY_TREND", _seq("EARLY_TREND", "EARLY_TREND", "PROGRESSED")) == m.STRICT_PASS
    assert m.classify_strict("EARLY_TREND", _seq("TRANSITION")) == m.STRICT_FAIL
    assert m.classify_strict("EARLY_TREND", _seq("BASE")) == m.STRICT_FAIL
    assert m.classify_strict("EARLY_TREND", _seq("WEAK")) == m.STRICT_FAIL
    # 나중에 다시 EARLY_TREND → PROGRESSED가 와도 FAIL은 바뀌지 않는다.
    assert m.classify_strict("EARLY_TREND", _seq("TRANSITION", "EARLY_TREND", "PROGRESSED")) == m.STRICT_FAIL
    assert m.classify_strict("EARLY_TREND", _seq("UNAVAILABLE", "PROGRESSED")) == m.STRICT_PASS
    assert m.classify_strict("EARLY_TREND", _seq("EARLY_TREND", "UNAVAILABLE")) == m.STRICT_NONE
    assert m.classify_strict("TRANSITION", _seq("PROGRESSED")) is None


def test_compress_path_and_tier():
    assert m.compress_path(_seq("TRANSITION", "TRANSITION", "EARLY_TREND", "PROGRESSED")) == "TRANSITION(2)>EARLY_TREND>PROGRESSED"
    assert m.tier(25, 20) == "EVALUABLE"
    assert m.tier(25, 12) == "DESCRIPTIVE"
    assert m.tier(9, 100) == "COUNTS_ONLY"


def test_holding_end_prefers_exit_then_settlement_then_cutoff():
    cutoff = pd.Timestamp("2026-08-31")
    assert m.holding_end(pd.Series({"exit_signal_date": "2024-03-15"}), cutoff) == pd.Timestamp("2024-03-15")
    assert m.holding_end(pd.Series({"exit_signal_date": float("nan"), "settlement_date": "2025-01-10"}), cutoff) == pd.Timestamp("2025-01-10")
    assert m.holding_end(pd.Series({"exit_signal_date": float("nan")}), cutoff) == cutoff
