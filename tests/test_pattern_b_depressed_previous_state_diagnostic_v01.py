from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_depressed_previous_state_diagnostic_v01 as runner


IDENTITY = ("000001", "KR7000000001")
COMPONENT = "000001:KR7000000001:000"


def _sample(date: str, state: str) -> dict:
    return {
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "snapshot_date": date,
        "state": state,
        "component_id": COMPONENT,
    }


def _event(date: str, previous_date: str, previous_state: str) -> dict:
    return {
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "entry_signal_date": date,
        "previous_state_date": previous_date,
        "previous_state": previous_state,
        "component_id": COMPONENT,
    }


def test_last_distinct_previous_state_skips_repeated_rows() -> None:
    normal_group = pd.DataFrame([
        _sample("2019-12-30", "NORMAL"),
        _sample("2020-01-31", "NORMAL"),
        _sample("2020-02-28", "NORMAL"),
        _sample("2020-03-31", "DEPRESSED"),
    ])
    deep_group = pd.DataFrame([
        _sample("2019-12-30", "DEEP_DEPRESSED"),
        _sample("2020-01-31", "DEEP_DEPRESSED"),
        _sample("2020-02-28", "DEEP_DEPRESSED"),
        _sample("2020-03-31", "DEPRESSED"),
    ])

    assert runner._last_distinct_previous_state(
        normal_group, _event("2020-03-31", "2020-02-28", "NORMAL")
    ) == ("NORMAL", "2020-02-28", True)
    assert runner._last_distinct_previous_state(
        deep_group, _event("2020-03-31", "2020-02-28", "DEEP_DEPRESSED")
    ) == ("DEEP_DEPRESSED", "2020-02-28", True)


def test_first_state_path_classification_and_exchange_day_gaps() -> None:
    observations = pd.DataFrame([
        _sample("2020-01-31", "DEPRESSED"),
        _sample("2020-02-28", "NORMAL"),
        _sample("2020-03-31", "DEEP_DEPRESSED"),
    ])
    result = runner._path_classification(
        observations,
        _event("2020-01-31", "2019-12-30", "NORMAL"),
        {"2020-01-31": 100, "2020-02-28": 121, "2020-03-31": 143},
    )

    assert result["first_target_state"] == "NORMAL"
    assert result["path_classification"] == "NORMAL_FIRST"
    assert result["days_to_first_normal"] == 21
    assert result["days_to_first_deep_depressed"] == 43


def test_path_classification_covers_deep_first_and_neither() -> None:
    calendar = {"2020-01-31": 1, "2020-02-28": 22}
    deep_first = pd.DataFrame([
        _sample("2020-01-31", "DEPRESSED"),
        _sample("2020-02-28", "DEEP_DEPRESSED"),
    ])
    neither = pd.DataFrame([_sample("2020-01-31", "DEPRESSED")])

    assert runner._path_classification(
        deep_first, _event("2020-01-31", "2019-12-30", "NORMAL"), calendar
    )["path_classification"] == "DEEP_DEPRESSED_FIRST"
    assert runner._path_classification(
        neither, _event("2020-01-31", "2019-12-30", "NORMAL"), calendar
    )["path_classification"] == "NEITHER_BY_STATE_FRONTIER"


def _state_summary(
    state: str,
    *,
    normal_first: float,
    deep_first: float,
    median: float,
    win: float,
    ge50: float,
    le30: float,
    le50: float,
    open_le30: float,
    open_le50: float,
) -> dict:
    return {
        "previous_state": state,
        "normal_first_rate_pct": normal_first,
        "deep_first_rate_pct": deep_first,
        "realized_median_gross_pct": median,
        "realized_win_rate_pct": win,
        "realized_ge_50_rate_pct": ge50,
        "realized_le_30_rate_pct": le30,
        "realized_le_50_rate_pct": le50,
        "open_marked_le_30_rate_pct": open_le30,
        "open_marked_le_50_rate_pct": open_le50,
    }


def test_promising_verdict_does_not_assume_normal_prior_is_better() -> None:
    summary = pd.DataFrame([
        _state_summary(
            "NORMAL", normal_first=45, deep_first=30, median=5, win=60,
            ge50=3, le30=12, le50=4, open_le30=30, open_le50=20,
        ),
        _state_summary(
            "DEEP_DEPRESSED", normal_first=65, deep_first=20, median=15, win=75,
            ge50=7, le30=6, le50=2, open_le30=10, open_le50=0,
        ),
    ])

    verdict, directions = runner._verdict(summary)

    assert verdict == "PATTERN_B_PREVIOUS_STATE_SIGNAL_PROMISING"
    assert directions["path_direction_group"] == "DEEP_PRIOR"
    assert directions["quality_direction_group"] == "DEEP_PRIOR"
    assert directions["risk_direction_group"] == "DEEP_PRIOR"
