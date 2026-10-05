"""Display-only B Select lineage historical PIT fundamental status."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from trend_scanner.strategies import b_select_core_fundamental_status as fs
from trend_scanner.strategies.b_select_core_fundamental_status import (
    BASIS_ENTRY_SIGNAL,
    BASIS_PENDING_ENTRY,
    BASIS_REQUESTED_AS_OF,
    CAUTION,
    EXCELLENT,
    FUNDAMENTAL_STATUSES,
    GOOD,
    NEUTRAL,
    UNKNOWN,
    classify_evaluation_row,
    item_status_asof,
    read_ledger,
    status_key,
    status_keys,
    write_ledger,
)

ROOT = Path(__file__).resolve().parents[1]
B = 1_000_000_000


def row(current, prior, status="PASS", quarter="2026Q2", reason="PASS"):
    return {"latest_quarter": quarter, "current_operating_income": current, "prior_operating_income": prior,
            "oi_status": status, "oi_reason": reason}


def test_five_states_and_boundaries():
    assert classify_evaluation_row(row(5 * B, 3 * B)) == EXCELLENT
    assert classify_evaluation_row(row(2 * B, B)) == EXCELLENT          # 20억 boundary
    assert classify_evaluation_row(row(2 * B - 1, B, "FAIL")) == GOOD
    assert classify_evaluation_row(row(2 * B, 2 * B, "FAIL")) == NEUTRAL  # equal is not an increase
    assert classify_evaluation_row(row(5 * B, 6 * B, "FAIL")) == NEUTRAL
    assert classify_evaluation_row(row(0, -B, "FAIL")) == CAUTION
    assert classify_evaluation_row(row(-B, -2 * B, "FAIL")) == CAUTION


def test_prior_missing_with_profit_is_neutral_and_unreadable_current_is_unknown():
    assert classify_evaluation_row(row(5 * B, None, "UNAVAILABLE", reason="PRIOR_YEAR_QUARTER_DATA_UNAVAILABLE")) == NEUTRAL
    assert classify_evaluation_row(row(5 * B, B, "BASIS_OR_CURRENCY_MISMATCH")) == NEUTRAL
    assert classify_evaluation_row(row(None, B, "UNAVAILABLE", reason="CURRENT_QUARTER_DATA_UNAVAILABLE")) == UNKNOWN
    assert classify_evaluation_row(row(None, None, "UNAVAILABLE", quarter=None, reason="FINANCIAL_NOT_APPLICABLE")) == UNKNOWN


def test_status_date_is_entry_signal_date_for_positions_and_requested_date_otherwise():
    held = {"ticker": "1", "isu_cd": "KR1", "current_trade": {"entry_signal_date": "2025-04-30"}, "pending_event": None}
    pending = {"ticker": "2", "isu_cd": "KR2", "current_trade": None,
               "pending_event": {"kind": "ENTRY", "signal_date": "2026-09-23"}}
    flat = {"ticker": "3", "isu_cd": "KR3", "current_trade": None, "pending_event": None,
            "trade_history": [{"entry_signal_date": "2022-05-31"}]}
    assert item_status_asof(held, "2026-09-25") == ("2025-04-30", BASIS_ENTRY_SIGNAL)
    assert item_status_asof(pending, "2026-09-25") == ("2026-09-23", BASIS_PENDING_ENTRY)
    assert item_status_asof(flat, "2026-09-25") == ("2026-09-25", BASIS_REQUESTED_AS_OF)
    keys = status_keys([held, pending, flat], "2026-09-25")
    assert keys[status_key("3", "KR3", "2022-05-31")] == BASIS_ENTRY_SIGNAL


def test_ledger_never_rewrites_a_fixed_status_and_retries_cache_gaps(tmp_path: Path, monkeypatch):
    key = status_key("000001", "KR7000001000", "2024-05-31")
    gap = {**fs.ledger_row({"ticker": "000001", "isu_cd": "KR7000001000", "entry_signal_date": "2024-05-31",
                            "oi_status": "UNAVAILABLE", "oi_reason": "REGISTRY_CACHE_UNAVAILABLE_RuntimeError"})}
    assert gap["fundamental_status"] == UNKNOWN and gap["retryable"] == "true"
    write_ledger(tmp_path, {key: gap})
    fixed = fs.ledger_row({"ticker": "000001", "isu_cd": "KR7000001000", "entry_signal_date": "2024-05-31",
                           "latest_quarter": "2024Q1", "current_operating_income": 5 * B,
                           "prior_operating_income": B, "oi_status": "PASS", "oi_reason": "PASS"})
    write_ledger(tmp_path, {key: fixed})  # a retryable gap may be filled
    assert read_ledger(tmp_path)[key]["fundamental_status"] == EXCELLENT
    with pytest.raises(ValueError):
        write_ledger(tmp_path, {key: {**fixed, "fundamental_status": CAUTION}})
    calls = []
    monkeypatch.setattr(fs, "evaluate_keys", lambda keys, root: calls.append(list(keys)) or {})
    assert fs.resolve_statuses([key], tmp_path)[key]["fundamental_status"] == EXCELLENT
    assert calls == [[]]  # fixed ledger entries are not re-evaluated


def _monitor():
    return json.loads((ROOT / "web/data/strategy-monitor.json").read_text(encoding="utf-8"))


def _ledger():
    with (ROOT / fs.LEDGER_RELATIVE).open(encoding="utf-8", newline="") as handle:
        return {status_key(r["ticker"], r["isu_cd"], r["status_asof_date"]): r for r in csv.DictReader(handle)}


def test_published_statuses_are_historical_pit_and_consistent():
    monitor = _monitor()
    as_of = monitor["requested_as_of"]
    b_select = next(s for s in monitor["strategies"] if s["id"] == "PATTERN_B_SELECT_CORE_V02")
    ledger = _ledger()
    source = json.loads((ROOT / "artifacts/strategies/b_select_core_v2/production" / as_of.replace("-", "") / "status.json").read_text(encoding="utf-8"))
    isu = {item["ticker"]: item["isu_cd"] for item in source["items"]}
    history = {(t["ticker"], t["entry_signal_date"]): t["fundamental_status"] for t in b_select["trade_history"]}
    for item in b_select["items"]:
        asof, _ = item_status_asof(item, as_of)
        record = ledger[status_key(item["ticker"], item["isu_cd"], asof)]
        assert item["fundamental_status"] == record["fundamental_status"]
        assert not record["latest_quarter_first_rcept_dt"] or record["latest_quarter_first_rcept_dt"][:10] <= asof
        if item.get("current_trade"):  # open position: same value as its own trade history row
            assert history[(item["ticker"], item["current_trade"]["entry_signal_date"])] == item["fundamental_status"]
    for trade in b_select["trade_history"]:
        record = ledger[status_key(trade["ticker"], isu[trade["ticker"]], trade["entry_signal_date"])]
        assert trade["fundamental_status"] == record["fundamental_status"] in FUNDAMENTAL_STATUSES
        assert record["status_asof_date"] == trade["entry_signal_date"]
        source_date = record["latest_quarter_first_rcept_dt"][:10]
        assert not source_date or source_date <= trade["entry_signal_date"]
    for strategy_id in ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "JULIA_ETF_STRATEGY_V01"):
        strategy = next(s for s in monitor["strategies"] if s["id"] == strategy_id)
        assert all("fundamental_status" not in item for item in strategy["items"])
        assert all("fundamental_status" not in trade for trade in strategy["trade_history"])


def test_b_select_signals_buckets_and_trades_are_unchanged():
    monitor = _monitor()
    b_select = next(s for s in monitor["strategies"] if s["id"] == "PATTERN_B_SELECT_CORE_V02")
    source = json.loads((ROOT / "artifacts/strategies/b_select_core_v2/production" / monitor["requested_as_of"].replace("-", "") / "status.json").read_text(encoding="utf-8"))
    assert b_select["counts"] == source["counts"]
    projected = [{k: v for k, v in item.items() if k != "fundamental_status"} for item in b_select["items"]]
    assert projected == [{k: v for k, v in item.items() if k != "trade_history"} for item in source["items"]]
    assert len(b_select["trade_history"]) == sum(len(item["trade_history"]) for item in source["items"])


def test_ui_wiring_for_list_history_filters_and_card():
    html = (ROOT / "web/strategy.html").read_text(encoding="utf-8")
    js = (ROOT / "web/js/strategy.js").read_text(encoding="utf-8")
    report_js = (ROOT / "web/js/report.js").read_text(encoding="utf-8")
    css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
    history_css = (ROOT / "web/css/strategy-history.css").read_text(encoding="utf-8")
    for select_id in ("strategy-fundamental-filter", "history-fundamental-filter"):
        start = html.index(f'id="{select_id}"')
        options = html[start:html.index("</select>", start)]
        for value in ("all", "우수", "양호", "보통", "주의", "미상"):
            assert f'<option value="{value}"' in options
        assert '<option value="all" selected>전체</option>' in options
    assert html.index('id="strategy-fundamental-filter-row"') < html.index('id="strategy-hold-sort-row"')
    assert html.index('id="history-filters"') < html.index('id="history-fundamental-filter-row"')
    # History filter is applied where trades are selected, so monthly events follow it too.
    trades_fn = js[js.index("function historyTrades()"):js.index("function compareHistoryTrades")]
    assert "fundamentalStatus(trade) !== historyFundamentalFilter" in trades_fn
    assert 'createField("펀더멘탈", fundamentalStatus(trade), "strategy-item-fundamental")' in js
    # Column header line is removed and not recreated.
    assert "strategy-trade-heading" not in js and "strategy-trade-heading" not in history_css
    assert '"종목", "매수 체결일"' not in js
    assert ".strategy-trade-row-b-select { grid-template-columns:" in history_css
    # Current status fields share a centered 48px field box and 2.4em value height.
    assert ".strategy-item-field { display: flex; align-self: center; flex-direction: column; justify-content: center; gap: 4px; min-height: 48px; }" in css
    assert ".strategy-item-value { display: block; min-height: 2.4em;" in css
    # Report card keeps the "{status}.{action}" form.
    assert "`${status}.${action}`" in report_js
