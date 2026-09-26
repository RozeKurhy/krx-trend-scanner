import pandas as pd
import pytest

import scripts.analyze_realistic_p2_winner_loser_lifecycle_v01 as realistic


def test_classify_vs_broad_thresholds():
    assert realistic.classify_vs_broad(10.0, 20.0) == ("MAINTAINED", 0.5)
    assert realistic.classify_vs_broad(5.0, 20.0) == ("WEAKENED", 0.25)
    assert realistic.classify_vs_broad(3.0, 20.0) == ("VANISHED", 0.15)
    assert realistic.classify_vs_broad(0.0, -2.0) == ("VANISHED", 0.0)
    assert realistic.classify_vs_broad(1.0, -2.0)[0] == "REVERSED"
    assert realistic.classify_vs_broad(1.0, 0.0)[0] == "NOT_COMPARABLE"
    assert realistic.classify_vs_broad(None, 1.0)[0] == "NOT_COMPARABLE"


def test_net_realized_returns_matches_runner_definition_and_checks_haircut():
    trades = pd.DataFrame({"pair_id": ["a"], "terminal_return": [100.0]})
    events = pd.DataFrame([
        {"pair_id": "a", "event_type": "ENTRY", "event_status": "EXECUTED", "notional": 1000.0, "commission": 0.15, "sell_tax": 0.0},
        {"pair_id": "a", "event_type": "EXIT", "event_status": "EXECUTED", "notional": 1996.0, "commission": 0.3, "sell_tax": 3.0},
    ])
    net = realistic.net_realized_returns(trades, events)
    assert net["net_realized_return"].iloc[0] == pytest.approx(((1996.0 - 0.3 - 3.0) / 1000.15 - 1.0) * 100.0)

    bad_events = events.copy()
    bad_events.loc[1, "notional"] = 2100.0  # 비용 차감 후에도 원장 수익률보다 높으면 짝이 틀린 것
    with pytest.raises(RuntimeError, match="NET_RETURN_COST_HAIRCUT_OUT_OF_RANGE"):
        realistic.net_realized_returns(trades, bad_events)


def _panel_rows(eligible_fav=(7, 0), filled_fav=3, mean_diff=20.0, auc=0.12, coverage_n=50):
    rows = []
    for window in realistic.WINDOWS:
        for layer in realistic.LAYERS:
            fav, unfav = eligible_fav if layer == "ELIGIBLE" else (5, 0)
            rows.append({
                "window": window, "layer": layer, "version": "ALL", "comparison": "NORMAL_vs_COVERAGE_COMBINED",
                "first_n": 100, "second_n": coverage_n, "evaluable": coverage_n >= 10,
                "favorable": fav, "unfavorable": unfav, "mean_return_diff": mean_diff,
                "return_auc_effect": auc, "filled_key_favorable": filled_fav if layer == "FILLED" else None,
            })
    return pd.DataFrame(rows)


def _broad_rows(classification="MAINTAINED", reversed_metric=None):
    rows = []
    for window in realistic.WINDOWS:
        for layer in realistic.LAYERS:
            for metric in ["mean_return", "median_return", "ge_50_rate_pct", "ge_100_rate_pct",
                           "le_neg_30_rate_pct", "le_neg_50_rate_pct", "le_neg_60_rate_pct", "return_auc_effect"]:
                label = classification if metric in {"mean_return", "ge_50_rate_pct"} else "MAINTAINED"
                if metric == reversed_metric:
                    label = "REVERSED"
                rows.append({"window": window, "layer": layer, "version": "ALL", "metric": metric, "classification": label})
    return pd.DataFrame(rows)


def test_verdict_order_and_rules():
    assert realistic.verdict(_panel_rows(), _broad_rows())[0] == "REALISTIC_P2_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE"
    # ELIGIBLE 핵심 지표 하나가 반전되면 CONFIRMS가 아니다.
    assert realistic.verdict(_panel_rows(), _broad_rows(reversed_metric="le_neg_50_rate_pct"))[0] == \
        "REALISTIC_P2_PARTIALLY_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE"
    # 방향은 같지만 크기가 broad의 20% 미만이면 PARTIALLY보다 WEAK가 먼저다.
    assert realistic.verdict(_panel_rows(), _broad_rows(classification="VANISHED"))[0] == "REALISTIC_P2_LIFECYCLE_EFFECT_WEAK"
    assert realistic.verdict(_panel_rows(auc=0.02), _broad_rows(classification="WEAKENED"))[0] == "REALISTIC_P2_LIFECYCLE_EFFECT_WEAK"
    assert realistic.verdict(_panel_rows(eligible_fav=(2, 5), mean_diff=-1.0), _broad_rows())[0] == "REALISTIC_P2_LIFECYCLE_EFFECT_MIXED"
    assert realistic.verdict(_panel_rows(coverage_n=5), _broad_rows())[0] == "INSUFFICIENT_EVIDENCE"
