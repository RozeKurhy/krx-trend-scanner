"""Display-only B Select Core V1 fundamental status: rule, sources and UI wiring."""

from __future__ import annotations

import json
from pathlib import Path

from trend_scanner.backtest.b_select_core_oi_1q_v03 import evaluate_signal
from trend_scanner.fundamentals.period_models import DATA_UNAVAILABLE, READY, STANDALONE_QUARTER, PeriodizedFinancialObservation
from trend_scanner.strategies import b_select_core_fundamental_status as status_module
from trend_scanner.strategies.b_select_core_fundamental_status import (
    CAUTION,
    EXCELLENT,
    FUNDAMENTAL_STATUSES,
    GOOD,
    NEUTRAL,
    UNKNOWN,
    classify_fundamental_status,
    fundamental_status_for_ticker,
)

ROOT = Path(__file__).resolve().parents[1]
B = 1_000_000_000
FILINGS = [{"bsns_year": "2021", "reprt_code": "11013", "rcept_dt": "2021-05-14"},
           {"bsns_year": "2022", "reprt_code": "11013", "rcept_dt": "2022-05-13"}]


def obs(year, value, *, available, status=READY, basis="CFS"):
    return PeriodizedFinancialObservation(
        ticker="000001", corp_code="00000000", company_family="NON_FINANCIAL", fiscal_year=str(year),
        fiscal_year_start=f"{year}-01-01", fiscal_period="Q1", period_semantics=STANDALONE_QUARTER,
        period_start=None, period_end=f"{year}-03-31", metric="operating_income", value=value, currency="KRW",
        method="TEST", anchor_report_type="Q1", anchor_reprt_code="11013", anchor_rcept_no=f"{year}{available}",
        anchor_rcept_dt=available, fs_div_used=basis, pit_available_from=available, resolution_status=status,
    )


def status(current, prior, *, prior_status=READY, current_status=READY, family="NON_FINANCIAL", basis="CFS"):
    observations = []
    if current is not None or current_status != READY:
        observations.append(obs(2022, current, available="2022-05-13", status=current_status))
    if prior is not None or prior_status != READY:
        observations.append(obs(2021, prior, available="2021-05-14", status=prior_status, basis=basis))
    evaluation = evaluate_signal(company_family=family, filings=FILINGS, observations=observations, as_of="2022-05-31")
    return classify_fundamental_status(evaluation)


def test_excellent_good_neutral_caution_unknown():
    assert status(5 * B, 3 * B) == EXCELLENT
    assert status(15 * B // 10, B) == GOOD
    assert status(5 * B, 6 * B) == NEUTRAL
    assert status(-B, -2 * B) == CAUTION
    assert status(None, B, current_status=DATA_UNAVAILABLE) == UNKNOWN


def test_two_billion_boundary_and_strict_yoy_increase():
    assert status(2 * B, B) == EXCELLENT
    assert status(2 * B - 1, B) == GOOD
    assert status(2 * B, 2 * B) == NEUTRAL  # equal is not an increase
    assert status(B, B) == NEUTRAL
    assert status(0, -B) == CAUTION  # zero operating income is caution


def test_prior_missing_or_incomparable_with_profit_is_neutral():
    assert status(5 * B, None) == NEUTRAL
    assert status(5 * B, None, prior_status=DATA_UNAVAILABLE) == NEUTRAL
    assert status(5 * B, B, basis="OFS") == NEUTRAL  # basis mismatch is not comparable


def test_unavailable_is_never_caution():
    assert status(None, None) == UNKNOWN
    assert status(5 * B, B, family="FINANCIAL") == UNKNOWN
    assert fundamental_status_for_ticker(ROOT, "999999", "2026-09-25") == UNKNOWN


def test_overseas_refiling_labeled_as_current_year_annual_is_not_latest_quarter():
    f2 = {"periodization_builds": [
        {"fiscal_year": "2026", "anchor_selections": [
            {"status": READY, "reprt_code": "11013", "selected_rcept_dt": "20260515"},
            {"status": READY, "reprt_code": "11011", "selected_rcept_dt": "20260430"},
        ]},
    ]}
    december = status_module._filings(f2, "12")
    assert [row["reprt_code"] for row in december] == ["11013"]
    assert len(status_module._filings(f2, "06")) == 2  # non-December fiscal years keep their annual report


def test_published_monitor_uses_one_shared_status_for_b_select_only():
    monitor = json.loads((ROOT / "web/data/strategy-monitor.json").read_text(encoding="utf-8"))
    strategies = {strategy["id"]: strategy for strategy in monitor["strategies"]}
    items = strategies["PATTERN_B_SELECT_CORE_V01"]["items"]
    assert {item["fundamental_status"] for item in items} <= set(FUNDAMENTAL_STATUSES)
    for strategy_id in ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "JULIA_ETF_STRATEGY_V01"):
        assert all("fundamental_status" not in item for item in strategies[strategy_id]["items"])
    as_of = monitor["requested_as_of"]
    for item in items[::97]:
        assert item["fundamental_status"] == fundamental_status_for_ticker(ROOT, item["ticker"], as_of)
    known = {item["ticker"]: item["fundamental_status"] for item in items}
    assert known["005490"] != UNKNOWN  # overseas re-filing no longer hides the real latest quarter


def test_b_select_signals_and_counts_are_unchanged_by_display_status():
    monitor = json.loads((ROOT / "web/data/strategy-monitor.json").read_text(encoding="utf-8"))
    b_select = next(strategy for strategy in monitor["strategies"] if strategy["id"] == "PATTERN_B_SELECT_CORE_V01")
    source = json.loads((ROOT / "artifacts/strategies/b_select_core_v1/production" / monitor["requested_as_of"].replace("-", "") / "status.json").read_text(encoding="utf-8"))
    assert b_select["counts"] == source["counts"]
    projected = [{k: v for k, v in item.items() if k != "fundamental_status"} for item in b_select["items"]]
    expected = [{k: v for k, v in item.items() if k != "trade_history"} for item in source["items"]]
    assert projected == expected


def test_strategy_page_fundamental_column_filter_and_card_wiring():
    html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    report_js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")

    # Filter: left of the sort dropdown, six options, default all.
    assert html.index('id="strategy-fundamental-filter-row"') < html.index('id="strategy-hold-sort-row"')
    options = html[html.index('id="strategy-fundamental-filter"'):html.index("</select>", html.index('id="strategy-fundamental-filter"'))]
    for value, label in (("all", "전체"), ("우수", "우수"), ("양호", "양호"), ("보통", "보통"), ("주의", "주의"), ("미상", "미상")):
        assert f'<option value="{value}"' in options and f">{label}</option>" in options
    assert '<option value="all" selected>전체</option>' in options
    # Filter applies to B Select only and combines with search and the hold sort.
    assert 'activeStrategyId === B_SELECT_STRATEGY_ID && fundamentalFilter !== "all"' in js
    assert "if (!fundamentalMatches(item)) return false;" in js
    assert "filter((item) => item.bucket === category && itemMatches(item))" in js
    assert "items.slice().sort(compareHoldItems)" in js
    # Column: single word, B Select layout only.
    b_select_fields = js[js.index('if (strategyId === "PATTERN_B_SELECT_CORE_V01")'):js.index('} else if (strategyId === "JULIA_ETF_STRATEGY_V01")')]
    assert 'createField("펀더멘탈", fundamentalStatus(item), "strategy-item-fundamental")' in b_select_fields
    # One-line rows: B Select grid has one track per field, values never wrap.
    assert "repeat(3, minmax(80px, 1fr)) minmax(44px, 0.55fr) repeat(3, minmax(80px, 1fr)) auto" in css
    assert ".strategy-item-value { overflow: hidden;" in css and "white-space: nowrap; }" in css
    # Card: only the status word is inserted before the existing action.
    assert "`${status}.${action}`" in report_js
    assert "withFundamentalStatus(bSelectItem, strategyActionLabel(" in report_js
