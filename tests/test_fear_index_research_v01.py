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
        {"fear_score": 20, "kospi_return_20": 0.12, "kospi_return_60": 0.18, "kospi_drawdown_60": -0.01, "participation_pct_252": 0.80},
        {"fear_score": 20, "kospi_return_20": 0.01, "kospi_return_60": 0.01, "kospi_drawdown_60": -0.01, "participation_pct_252": 0.50},
        {"fear_score": 60, "kospi_return_20": -0.02, "kospi_return_60": 0.00, "kospi_drawdown_60": -0.04, "participation_pct_252": 0.50},
        {"fear_score": 90, "kospi_return_20": -0.12, "kospi_return_60": -0.15, "kospi_drawdown_60": -0.15, "participation_pct_252": 0.70},
        {"fear_score": 20, "kospi_return_20": 0.00, "kospi_return_60": 0.01, "kospi_drawdown_60": -0.02, "participation_pct_252": 0.20},
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
