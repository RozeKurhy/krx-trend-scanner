import math

import pandas as pd
import pytest

import scripts.analyze_fastcore_v2_winner_loser_profile_v01 as profile


def _ledger(window: str, rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["window"] = window
    return frame


def _row(ticker: str, signal: str, ret: float | None, **extra) -> dict:
    base = {
        "ticker": ticker,
        "isu_cd": f"KR7{ticker}0",
        "entry_signal_date": signal,
        "entry_execution_date": signal,
        "terminal_return": ret,
        "trade_id": f"{ticker}_01",
        "trade_status": "REALIZED",
    }
    base.update(extra)
    return base


def test_rank_auc_matches_mann_whitney_definition():
    assert profile.rank_auc([3, 4], [1, 2]) == 1.0
    assert profile.rank_auc([1, 2], [3, 4]) == 0.0
    assert profile.rank_auc([1, 2], [1, 2]) == 0.5
    # 2 > 1 (1), 2 == 2 (0.5) -> 1.5 / 2
    assert profile.rank_auc([2], [1, 2]) == pytest.approx(0.75)
    assert profile.rank_auc([], [1.0]) is None
    assert profile.rank_auc([float("nan"), 5.0], [1.0]) == 1.0


def test_assign_groups_uses_inclusive_thresholds():
    groups = profile.assign_groups(pd.Series([100.0, 50.0, 0.0, -30.0, -50.0, -60.0, 10.0]))
    assert groups["WIN_100"].tolist() == [True, False, False, False, False, False, False]
    assert groups["WIN_50"].tolist() == [True, True, False, False, False, False, False]
    assert groups["LOSS_ANY"].tolist() == [False, False, True, True, True, True, False]
    assert groups["POSITIVE"].tolist() == [True, True, False, False, False, False, True]
    assert groups["LOSS_30"].sum() == 3
    assert groups["LOSS_50"].sum() == 2
    assert groups["LOSS_60"].sum() == 1
    assert (groups["NOT_WIN_50"] == ~groups["WIN_50"]).all()


def test_deduplicate_prefers_latest_cutoff_priority_and_applies_exclusion_union():
    ledgers = {window: _ledger(window, []) for window in profile.WINDOW_ORDER}
    ledgers["P2-1"] = _ledger("P2-1", [_row("000001", "2021-02-05", 10.0), _row("000002", "2021-03-05", -20.0)])
    ledgers["P2-2"] = _ledger("P2-2", [_row("000001", "2021-02-05", 80.0), _row("000003", "2021-04-02", 5.0)])
    ledgers["P1"] = _ledger("P1", [_row("000001", "2021-02-05", 80.0), _row("000003", "2021-04-02", 5.0),
                                   _row("000004", "2021-05-07", None)])
    ledgers["P3-2"] = _ledger("P3-2", [_row("000003", "2021-04-02", 7.0)])
    for window in profile.WINDOW_ORDER:
        if ledgers[window].empty:
            ledgers[window] = pd.DataFrame(columns=list(_row("0", "2021-01-01", 0.0)) + ["window"])
    exclusions = pd.DataFrame([{"ticker": "000002", "isu_cd": "KR70000020", "source": "TEST"}])

    pooled, audit = profile.deduplicate(ledgers, exclusions)

    by_ticker = pooled.set_index("ticker")
    assert set(by_ticker.index) == {"000001", "000003"}
    assert by_ticker.loc["000001", "representative_window"] == "P1"
    assert by_ticker.loc["000001", "terminal_return"] == 80.0
    assert by_ticker.loc["000001", "observed_windows"] == "P1|P2-1|P2-2"
    # 같은 cutoff(2026-08-31)에서 P1 5.0과 P3-2 7.0이 다르므로 불일치로 센다.
    assert by_ticker.loc["000003", "same_cutoff_return_spread"] == pytest.approx(2.0)
    assert audit["same_cutoff_return_disagreement_count"] == 1
    assert audit["excluded_by_certification_identity_union_rows"] == 1
    assert audit["null_terminal_return_rows"] == 1
    assert audit["dedup_trade_count"] == 2


def test_compare_feature_categorical_share_difference():
    frame = pd.DataFrame({"market": ["KOSDAQ", "KOSDAQ", "KOSPI", "KOSPI", "KOSPI"],
                          "terminal_return": [60.0, 70.0, 60.0, -40.0, -35.0]})
    groups = profile.assign_groups(frame["terminal_return"])
    row = profile.compare_feature(frame, groups, "WIN_50", "LOSS_30", "market", "categorical", "KOSDAQ")
    assert row["group_share_pct"] == pytest.approx(200 / 3)
    assert row["reference_share_pct"] == 0.0
    assert row["effect"] == pytest.approx(66.6667, abs=1e-4)


def _scope(effect: float, n: int = 20) -> dict:
    return {"group_n": n, "reference_n": n, "effect": effect}


def test_grade_rules_are_applied_in_order():
    windows_up = [_scope(0.1)] * 5
    disjoint_up = [_scope(0.1)] * 2
    assert profile.grade(_scope(0.1), windows_up, disjoint_up, "numeric")[0] == "CONSISTENT"
    assert profile.grade(_scope(0.02), windows_up, disjoint_up, "numeric")[0] == "WEAK"
    assert profile.grade(_scope(3.0), windows_up, disjoint_up, "categorical")[0] == "WEAK"
    mixed_windows = [_scope(0.1), _scope(-0.1), _scope(0.1), _scope(-0.1), _scope(0.1)]
    assert profile.grade(_scope(0.1), mixed_windows, disjoint_up, "numeric")[0] == "MIXED"
    # 분리 기간 하나가 반대 방향이면 CONSISTENT가 아니다.
    assert profile.grade(_scope(0.1), windows_up, [_scope(0.1), _scope(-0.1)], "numeric")[0] == "MIXED"
    small = [_scope(0.1, n=5)] * 5
    assert profile.grade(_scope(0.1), small, disjoint_up, "numeric")[0] == "INSUFFICIENT_EVIDENCE"
    assert profile.grade(_scope(0.1, n=9), windows_up, disjoint_up, "numeric")[0] == "INSUFFICIENT_EVIDENCE"


def test_frozen_feature_lists_exclude_post_entry_fields():
    post_entry = set(profile.NUMERIC_POST_ENTRY) | set(profile.CATEGORICAL_POST_ENTRY)
    entry = set(profile.NUMERIC_ENTRY_FEATURES) | set(profile.CATEGORICAL_ENTRY_FEATURES)
    assert not entry & post_entry
    assert {"mfe", "mae", "holding_days", "exit_type"} <= post_entry
    assert not any(math.isnan(x) for x in [profile.GRADE_RULES["weak_auc_abs"], profile.GRADE_RULES["weak_share_pp"]])


def _lifecycle_frame(rows: list[tuple[str, float, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"lifecycle_class": cls, "terminal_return": ret, "trade_status": status,
             "holding_days": 10, "mfe": 1.0, "mae": -1.0, "peak_giveback": 0.5}
            for cls, ret, status in rows
        ]
    )


def test_lifecycle_metrics_counts_inclusive_tails_and_status_rates():
    frame = _lifecycle_frame([
        ("X", 100.0, "REALIZED"), ("X", 50.0, "REALIZED"), ("X", -15.0, "REALIZED"),
        ("X", -60.0, "OPEN_AT_CUTOFF"),
    ])
    row = profile.lifecycle_metrics(frame)
    assert row["trades"] == 4
    assert row["ge_100_count"] == 1 and row["ge_50_count"] == 2
    assert row["le_neg_15_count"] == 2 and row["le_neg_60_count"] == 1
    assert row["open_at_cutoff_rate_pct"] == 25.0 and row["closed_rate_pct"] == 75.0
    assert row["positive_rate_pct"] == 50.0


def test_lifecycle_group_combines_coverage_paths():
    frame = _lifecycle_frame([
        (profile.NORMAL, 10.0, "REALIZED"), (profile.SKIPPED, 0.0, "REALIZED"),
        (profile.WITHOUT_DIRECT, 0.0, "REALIZED"), (profile.NEVER, 0.0, "REALIZED"),
    ])
    assert len(profile.lifecycle_group_frame(frame, profile.COVERAGE)) == 2
    assert len(profile.lifecycle_group_frame(frame, profile.NORMAL)) == 1


def test_lifecycle_compare_counts_ties_as_neither():
    first = _lifecycle_frame([("A", 60.0, "REALIZED"), ("A", 10.0, "REALIZED")])
    second = _lifecycle_frame([("B", 5.0, "REALIZED"), ("B", -10.0, "REALIZED")])
    row = profile.lifecycle_compare(first, second)
    # 평균·중앙값·+50% 유리, +100%와 -30/-50/-60은 양쪽 0이라 TIE
    assert row["favorable"] == 3 and row["unfavorable"] == 0
    assert row["le_neg_60_rate_pct_favorable"] == "TIE"
    assert row["return_auc"] == 1.0


def _consistency_rows(pooled_closed: tuple[int, int], scope_unfavorable: int = 0) -> pd.DataFrame:
    rows = []
    scopes = ["POOLED_DEDUP"] + [f"WINDOW_{w}" for w in profile.WINDOW_ORDER] + ["ENTRY_BEFORE_2021", "ENTRY_FROM_2021"]
    for scope in scopes:
        for version in ("ALL", "CLOSED_ONLY"):
            fav, unfav = (7, 0) if version == "ALL" else (7, 0)
            if scope == "POOLED_DEDUP" and version == "CLOSED_ONLY":
                fav, unfav = pooled_closed
            elif scope != "POOLED_DEDUP" and version == "ALL":
                fav, unfav = 7 - scope_unfavorable, scope_unfavorable
            rows.append({"scope": scope, "version": version, "comparison": "NORMAL_vs_COVERAGE_COMBINED",
                         "first_n": 100, "second_n": 50, "favorable": fav, "unfavorable": unfav,
                         "return_auc": 0.62, "return_auc_effect": 0.12})
    return pd.DataFrame(rows)


def test_lifecycle_verdict_rules():
    strong = profile.lifecycle_verdict(_consistency_rows((7, 0)))[0]
    assert strong == "NORMAL_HANDOFF_STRONGLY_ASSOCIATED_WITH_BETTER_RETURN_DISTRIBUTION"
    moderate = profile.lifecycle_verdict(_consistency_rows((4, 3)))[0]
    assert moderate == "NORMAL_HANDOFF_MODERATELY_ASSOCIATED_WITH_BETTER_RETURN_DISTRIBUTION"
    mixed = profile.lifecycle_verdict(_consistency_rows((3, 4)))[0]
    assert mixed == "LIFECYCLE_RETURN_DIFFERENCE_MIXED"
    small = _consistency_rows((7, 0))
    small.loc[small["scope"].str.startswith("WINDOW_"), "second_n"] = 5
    assert profile.lifecycle_verdict(small)[0] == "INSUFFICIENT_EVIDENCE"
