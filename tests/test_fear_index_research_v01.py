import numpy as np
import pandas as pd

from trend_scanner.research.fear_index_v01 import (
    CANDIDATES,
    REGIMES,
    build_candidate_scores,
    build_features,
    classify_regime,
    exact_date_join,
    flicker_summary,
    stabilize_regimes,
)


def _synthetic_joined(rows: int = 320) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=rows, freq="B")
    step = np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "kospi_close": 2000.0 + step * 0.4,
            "trading_value": 1.0e12 + (step % 20) * 1.0e10,
            "v_kospi200_close": 18.0 + (step % 30) * 0.1,
        }
    )


def test_exact_date_join_uses_only_common_dates():
    kospi = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-02", "2020-01-03"]), "kospi_close": [1, 2], "trading_value": [3, 4]}
    )
    v_kospi = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-03", "2020-01-04"]), "v_kospi200_close": [10, 11]}
    )
    joined = exact_date_join(kospi, v_kospi)
    assert joined["date"].tolist() == [pd.Timestamp("2020-01-03")]


def test_features_do_not_use_future_observations():
    base = _synthetic_joined()
    changed = base.copy()
    changed.loc[changed.index[-1], "v_kospi200_close"] = 999.0
    left = build_features(base)
    right = build_features(changed)
    compare_columns = ["v_level_pct_252", "v_z_60", "v_change_20", "kospi_return_20"]
    pd.testing.assert_frame_equal(left.loc[:-2, compare_columns], right.loc[:-2, compare_columns])


def test_candidate_scores_are_finite_and_bounded():
    scored = build_candidate_scores(build_features(_synthetic_joined()))
    for candidate in CANDIDATES:
        values = scored[f"score_{candidate}"].dropna()
        assert np.isfinite(values).all()
        assert values.between(0.0, 100.0).all()


def test_five_regimes_and_directional_guards():
    cases = [
        {"fear_score": 20, "kospi_return_5": 0.02, "kospi_return_20": 0.12, "kospi_return_60": 0.18, "kospi_drawdown_60": -0.01, "participation_pct_252": 0.80, "participation_ratio_20": 1.20},
        {"fear_score": 20, "kospi_return_5": 0.00, "kospi_return_20": 0.01, "kospi_return_60": 0.01, "kospi_drawdown_60": -0.01, "participation_pct_252": 0.50, "participation_ratio_20": 1.00},
        {"fear_score": 60, "kospi_return_5": -0.01, "kospi_return_20": -0.02, "kospi_return_60": 0.00, "kospi_drawdown_60": -0.04, "participation_pct_252": 0.50, "participation_ratio_20": 1.00},
        {"fear_score": 90, "kospi_return_5": -0.08, "kospi_return_20": -0.12, "kospi_return_60": -0.15, "kospi_drawdown_60": -0.15, "participation_pct_252": 0.80, "participation_ratio_20": 1.30},
        {"fear_score": 20, "kospi_return_5": 0.00, "kospi_return_20": 0.00, "kospi_return_60": 0.01, "kospi_drawdown_60": -0.02, "participation_pct_252": 0.20, "participation_ratio_20": 0.70},
    ]
    regimes = {classify_regime(case) for case in cases}
    assert regimes == set(REGIMES)
    assert classify_regime({**cases[0], "fear_score": 95}) == "OVERHEATED"
    assert classify_regime({**cases[4], "fear_score": np.nan}) == "UNAVAILABLE"


def test_flicker_summary_is_deterministic():
    regimes = pd.Series(["NORMAL", "NORMAL", "ANXIOUS", "NORMAL", "NORMAL", "PANIC"])
    expected = flicker_summary(regimes)
    assert expected == flicker_summary(regimes.copy())
    assert expected["two_day_return_flickers"] == 1


def test_candidate_generation_is_deterministic():
    first = build_candidate_scores(build_features(_synthetic_joined()))
    second = build_candidate_scores(build_features(_synthetic_joined()))
    pd.testing.assert_frame_equal(first, second)


def test_low_participation_does_not_raise_fear_score():
    base = pd.DataFrame(
        {
            "v_level_pct_252": [0.90, 0.90],
            "v_z_60": [2.0, 2.0],
            "v_change_20": [0.20, 0.20],
            "kospi_return_20": [-0.10, -0.10],
            "kospi_drawdown_60": [-0.12, -0.12],
            "participation_pct_252": [0.10, 0.90],
            "participation_ratio_20": [0.70, 1.40],
        }
    )
    scored = build_candidate_scores(base)
    assert scored.loc[0, "score_panic_confirmed_v01"] <= scored.loc[1, "score_panic_confirmed_v01"]
    assert scored.loc[0, "score_balanced_no_participation_v01"] == scored.loc[1, "score_balanced_no_participation_v01"]
    assert scored.loc[0, "score_downside_heavy_v01"] == scored.loc[1, "score_downside_heavy_v01"]


def test_official_historical_anchors_regression():
    final = pd.read_csv("artifacts/fear_index/research_v01/final_daily_regimes.csv")
    regimes = final.set_index("date")["regime"]
    assert regimes["2020-03-19"] == "PANIC"
    assert regimes["2024-08-05"] == "PANIC"
    assert regimes["2026-06-18"] != "PANIC"
    assert regimes["2026-06-29"] != "PANIC"
    assert regimes["2022-07-04"] != "PANIC"


def test_stabilization_is_deterministic_and_pit_safe():
    raw = pd.Series(["NORMAL", "PANIC", "ANXIOUS", "NORMAL", "NORMAL", "APATHY"])
    stabilized = stabilize_regimes(raw)
    assert stabilized.tolist() == ["NORMAL", "PANIC", "PANIC", "PANIC", "NORMAL", "NORMAL"]
    changed_future = raw.copy()
    changed_future.iloc[-1] = "PANIC"
    pd.testing.assert_series_equal(stabilized.iloc[:5], stabilize_regimes(changed_future).iloc[:5])


def test_final_formula_artifact_has_exact_numeric_spec():
    formula = open("artifacts/fear_index/research_v01/final_formula.md", encoding="utf-8").read()
    assert "0.40 * v_level_pct_252" in formula
    assert "0.10 * v_spike" in formula
    assert "0.40 * downside" in formula
    assert "0.10 * v_momentum" in formula
    assert "fear_score >= 70" in formula
    assert "participation_pct_252 >= 0.75" in formula
    assert "kospi_return_20 <= -0.07" in formula
