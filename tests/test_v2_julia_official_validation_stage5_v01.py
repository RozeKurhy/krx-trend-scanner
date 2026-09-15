"""Focused offline tests for the Stage 5 V2 ↔ Julia execution preparation."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import run_v2_julia_official_validation_v01 as runner
from trend_scanner.backtest.raw_investability_panel import evaluate_entry_filter


def _task() -> runner.IdentityTask:
    return runner.IdentityTask(
        ticker="005930",
        isu_cd="KR7005930003",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2021-04-30"),
    )


def test_contract_preflight_is_ready_without_execution_or_results():
    result = runner.preflight(runner.ROOT, write_contract=False)
    assert result["status"] == "READY"
    assert result["official_backtest_executed"] is False
    assert result["result_artifacts_generated"] is False
    assert result["network_requests"] == 0
    assert result["contract_validation"]["status"] == "PASS"


def test_effective_authority_and_repository_v2_paths_are_contract_bound():
    contract = runner.build_execution_contract()
    assert contract["population_pit_authority"]["population_path"] == runner.POPULATION_REL.as_posix()
    assert contract["population_pit_authority"]["pit_path"] == runner.PIT_REL.as_posix()
    assert contract["market_data"]["authority"] == "MarketDataRepositoryV2"
    assert contract["market_data"]["legacy_fallbacks"] is False


def test_contract_has_no_absolute_paths_or_current_list_broadcast():
    contract = runner.build_execution_contract()
    strings = list(runner._walk_strings(contract))
    assert not any(value.startswith("/") or value.startswith("~") or "\\" in value for value in strings)
    assert not any("current universe" in value.lower() for value in strings)
    assert "data/market/raw/krx_stocks/v01" in strings


def test_exact_date_raw_row_has_no_nearest_fallback():
    panel = pd.DataFrame(
        {"market_cap": [100.0], "avg_trading_value_20d": [300.0]},
        index=pd.DatetimeIndex(["2021-01-04"]),
    )
    assert runner._find_exact_raw_row(panel, pd.Timestamp("2021-01-04")) is not None
    assert runner._find_exact_raw_row(panel, pd.Timestamp("2021-01-05")) is None


def test_identity_raw_panel_resets_twenty_observation_average():
    dates = pd.bdate_range("2021-01-01", periods=21)
    ancillary = pd.DataFrame(
        {
            "volume": 1.0,
            "trading_value": 100.0,
            "market_cap": 100_000_000_000.0,
            "listed_shares": 1.0,
        },
        index=dates,
    )
    panel = runner.build_identity_raw_panel(ancillary, _task())
    assert panel["avg_trading_value_20d"].iloc[:19].isna().all()
    assert panel["avg_trading_value_20d"].iloc[19] == 100.0


def test_official_investability_has_100b_and_300m_without_price_floor():
    panel = pd.DataFrame(
        {
            "market_cap": [100_000_000_000.0],
            "avg_trading_value_20d": [300_000_000.0],
            "close": [float("nan")],
        },
        index=pd.DatetimeIndex(["2021-01-04"]),
    )
    result = evaluate_entry_filter(
        panel,
        pd.Timestamp("2021-01-04"),
        market_cap_threshold=runner.MARKET_CAP_THRESHOLD_KRW,
        avg_trading_value_threshold=runner.AVG_TRADING_VALUE_20D_THRESHOLD_KRW,
        close_threshold=None,
    )
    assert result["entry_filter_pass"] is True
    assert result["entry_close_pass"] is True


def test_tax_mapping_uses_execution_date_and_market():
    assert runner._tax_rate("2021-12-31", "KOSPI") == 0.0023
    assert runner._tax_rate("2024-06-03", "KOSDAQ") == 0.0018
    assert runner._tax_rate("2026-08-14", "KOSPI") == 0.0020


def test_contract_freezes_period_start_and_lookback_semantics():
    contract = runner.build_execution_contract()
    assert contract["period"]["evaluation_start"] == "2021-01-01"
    assert contract["period"]["signal_cutoff"] == "2026-08-14"
    assert contract["period"]["final_valuation"] == "2026-08-14 CLOSE"
    assert contract["period"]["pre_start_data"] == "LOOKBACK_ONLY_NO_TRADES"


def test_contract_freezes_one_delta_and_three_axes():
    contract = runner.build_execution_contract()
    assert contract["strategies"]["one_delta_only"] == "PRE_PROGRESSED_LOSS_GUARD_ON_VS_OFF"
    assert contract["result_axes"] == ["Matched-entry", "Sequential", "Realistic 200M Portfolio"]


def test_matched_entry_uses_independent_signal_ledger_not_intersection(monkeypatch):
    task = _task()
    signal = runner.EntrySignal(task, pd.Timestamp("2021-04-02"), pd.Timestamp("2021-04-05"), 200.0, 400.0)
    instance = object.__new__(runner.OfficialValidationRunner)
    calls: list[bool] = []
    instance.identity_tasks = lambda: (task,)
    instance.discover_matched_entry_signals = lambda _task: (signal,)

    def fake_run(_task, *, enable_loss_guard, allowed_signal_dates):
        calls.append(enable_loss_guard)
        return [SimpleNamespace(strategy_id="BASE" if enable_loss_guard else "JULIA")]

    instance.run_identity_strategy = fake_run
    result = instance.run_matched_entry()
    assert result["candidate_signal_count"] == 1
    assert result["pairs"][0]["status"] == "PASS"
    assert calls == [True, False]


def test_sequential_calls_each_strategy_independently():
    tasks = (_task(), _task())
    instance = object.__new__(runner.OfficialValidationRunner)
    calls: list[tuple[str, bool]] = []
    instance.identity_tasks = lambda: tasks

    def fake_run(task, *, enable_loss_guard, allowed_signal_dates=None):
        calls.append((task.ticker, enable_loss_guard))
        return []

    instance.run_identity_strategy = fake_run
    result = instance.run_sequential()
    assert set(result) == {runner.BASE_STRATEGY_ID, runner.JULIA_STRATEGY_ID}
    assert calls == [("005930", True), ("005930", False), ("005930", True), ("005930", False)]


def test_realistic_portfolio_contract_freezes_capital_slots_and_costs():
    instance = object.__new__(runner.OfficialValidationRunner)
    result = instance.run_realistic_portfolio({runner.BASE_STRATEGY_ID: [], runner.JULIA_STRATEGY_ID: []})
    assert result["initial_capital_krw"] == 200_000_000.0
    assert result["per_symbol_cash_budget_krw"] == 5_000_000.0
    assert result["max_positions"] == 40
    assert result["same_open_sale_proceeds_reusable"] is False
    assert result["sell_tax_mapping"] == "execution_date_and_market"


def test_contract_freezes_commission_slippage_and_tax_schedule():
    contract = runner.build_execution_contract()
    costs = contract["costs"]
    assert costs["buy_commission_rate"] == 0.00015
    assert costs["sell_commission_rate"] == 0.00015
    assert costs["buy_slippage_rate"] == 0.001
    assert costs["sell_slippage_rate"] == 0.001
    assert len(costs["historical_sell_tax_schedule"]) == 5


def test_contract_freezes_pit_market_cap_order_and_benchmarks():
    contract = runner.build_execution_contract()
    assert contract["portfolio"]["same_open_signal_order"] == [
        "signal_confirmation_date_pit_market_cap_desc",
        "ticker_asc",
    ]
    assert contract["benchmarks"]["KOSPI_COMMON"] == "1001"
    assert contract["benchmarks"]["KOSDAQ_COMMON"] == "2001"
    assert contract["benchmarks"]["mixed_single_benchmark"] is False


def test_contract_hash_and_authority_hash_validation():
    contract = runner.build_execution_contract()
    report = runner.validate_execution_contract(contract)
    assert report["status"] == "PASS"
    assert report["contract_sha256"] == contract["contract_sha256"]
    assert report["population_count"] == 3149
    assert report["pit_interval_count"] == 3173


def test_unresolved_semantics_are_fail_closed():
    contract = runner.build_execution_contract()
    unresolved = contract["unresolved"]
    assert unresolved["missing_required_evidence"] == "UNRESOLVED"
    assert unresolved["run_status_if_unresolved_gt_zero"] == "INCOMPLETE_REQUIRES_REVIEW"
    assert unresolved["silent_exclusion"] is False
    assert unresolved["nearest_date"] is False


def test_fundamentals_are_excluded_and_production_is_not_rewired():
    contract = runner.build_execution_contract()
    assert contract["strategies"]["fundamentals_included"] is False
    assert "Fundamentals" not in contract["market_data"]["authority"]


def test_preflight_does_not_create_result_files():
    runner.preflight(runner.ROOT, write_contract=False)
    output_dir = runner.ROOT / runner.OUTPUT_DIR_REL
    assert not any((output_dir / name).exists() for name in runner.OFFICIAL_RESULT_FILES)
    assert not any((output_dir / name).exists() for name in runner.SUPPORT_RESULT_FILES)


def test_contract_contains_required_event_and_equity_fields():
    contract = runner.build_execution_contract()
    assert contract["contract_state"] == "FROZEN_BEFORE_RESULTS"
    assert contract["output"]["support_result_files"] == [
        "portfolio_event_ledger.csv",
        "portfolio_daily_equity.csv",
    ]
    assert contract["execution"]["open_at_cutoff"] is True
    assert contract["portfolio"]["partial_fill"] is False


def _portfolio_record(
    ticker: str,
    *,
    entry_date: str = "2021-01-04",
    exit_date: str | None = None,
    entry_open: float = 100.0,
    exit_price: float | None = None,
    market_cap: float | None = 200_000_000_000.0,
    cutoff_close: float | None = 110.0,
    cutoff_date: str = "2026-08-14",
    identity_effective_from: str = "2021-01-01",
    identity_effective_to: str = "2026-08-14",
) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_id=runner.BASE_STRATEGY_ID,
        ticker=ticker,
        isu_cd=f"KR{ticker}",
        name=ticker,
        market="KOSPI",
        trade_id=f"trade-{ticker}-{entry_date}",
        entry_signal_date="2021-01-01",
        entry_execution_date=entry_date,
        entry_open=entry_open,
        entry_market_cap=market_cap,
        exit_type="TEST_EXIT" if exit_date else "NO_EXIT_BEFORE_CUTOFF",
        exit_execution_date=exit_date,
        exit_price=exit_price,
        cutoff_valuation_price=cutoff_close,
        cutoff_date=cutoff_date,
        exit_signal_date="2021-01-03" if exit_date else None,
        trade_status="REALIZED" if exit_date else "OPEN_AT_CUTOFF",
        identity_effective_from=identity_effective_from,
        identity_effective_to=identity_effective_to,
    )


def _portfolio_frame(
    dates: list[str],
    *,
    opens: list[float] | None = None,
    closes: list[float] | None = None,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": opens or [100.0] * len(dates),
            "close": closes or [100.0] * len(dates),
        },
        index=pd.DatetimeIndex(dates),
    )


def _run_synthetic_portfolio(records: list[SimpleNamespace], frame_dates: list[str]) -> dict:
    instance = object.__new__(runner.OfficialValidationRunner)
    frames = {}
    for record in records:
        opens = [record.entry_open] * len(frame_dates)
        exit_date = runner._record_date(record, "exit_execution_date")
        if exit_date is not None and record.exit_price is not None:
            for index, date in enumerate(frame_dates):
                if pd.Timestamp(date).normalize() == exit_date:
                    opens[index] = record.exit_price
        closes = [record.entry_open] * len(frame_dates)
        if record.cutoff_valuation_price is not None:
            closes[-1] = record.cutoff_valuation_price
        else:
            closes[-1] = float("nan")
        key = runner._identity_key_from_record(record)
        if key not in frames:
            frames[key] = _portfolio_frame(frame_dates, opens=opens, closes=closes)
        else:
            existing = frames[key]
            exit_date = runner._record_date(record, "exit_execution_date")
            if exit_date is not None and record.exit_price is not None and exit_date in existing.index:
                existing.loc[exit_date, "open"] = record.exit_price
            if record.cutoff_valuation_price is None:
                existing.loc[pd.Timestamp(frame_dates[-1]), "close"] = float("nan")
    return instance.run_realistic_portfolio(
        {runner.BASE_STRATEGY_ID: records},
        market_data_by_identity=frames,
    )["strategies"][runner.BASE_STRATEGY_ID]


def test_realistic_portfolio_applies_budget_commission_slippage_and_tax():
    record = _portfolio_record("000001", exit_date="2021-01-05", exit_price=110.0)
    result = _run_synthetic_portfolio(record and [record], ["2021-01-04", "2021-01-05", "2026-08-14"])
    entries = [event for event in result["event_ledger"] if event["event_type"] == "ENTRY"]
    exits = [event for event in result["event_ledger"] if event["event_type"] == "EXIT"]
    assert entries[0]["event_status"] == "EXECUTED"
    assert entries[0]["slippage_adjusted_price"] == pytest.approx(100.1)
    assert entries[0]["notional"] + entries[0]["commission"] <= 5_000_000.0
    assert entries[0]["shares"] == int((5_000_000.0 / (100.1 * 1.00015)) // 1)
    assert exits[0]["slippage_adjusted_price"] == pytest.approx(109.89)
    assert exits[0]["sell_tax"] == pytest.approx(exits[0]["notional"] * 0.0023)
    assert exits[0]["commission"] == pytest.approx(exits[0]["notional"] * 0.00015)
    assert result["metrics"]["total_commission"] > 0
    assert result["metrics"]["total_sell_tax"] > 0
    assert result["metrics"]["slippage_impact"] > 0


def test_realistic_portfolio_enforces_slots_cash_priority_and_tie_break():
    initial = [_portfolio_record(f"A{i:03d}") for i in range(40)]
    extra = _portfolio_record("Z999")
    result = _run_synthetic_portfolio(initial + [extra], ["2021-01-04", "2026-08-14"])
    events = result["event_ledger"]
    executed = [event["ticker"] for event in events if event["event_status"] == "EXECUTED" and event["event_type"] == "ENTRY"]
    assert executed == [f"A{i:03d}" for i in range(40)]
    assert next(event for event in events if event["ticker"] == "Z999")["event_status"] == "SKIPPED_POSITION_LIMIT"
    assert result["metrics"]["trade_count"] == 40


def test_realistic_portfolio_delays_sale_proceeds_and_blocks_same_open_reentry():
    records = [_portfolio_record(f"A{i:03d}") for i in range(40)]
    records[0] = _portfolio_record("A000", exit_date="2021-01-05", exit_price=200.0)
    records.extend([
        _portfolio_record("A000", entry_date="2021-01-05"),
        _portfolio_record("B000", entry_date="2021-01-05"),
        _portfolio_record("C000", entry_date="2021-01-06"),
    ])
    frame_dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2026-08-14"]
    result = _run_synthetic_portfolio(records, frame_dates)
    events = result["event_ledger"]
    same_open = next(event for event in events if event["ticker"] == "A000" and event["execution_date"] == "2021-01-05" and event["event_type"] == "ENTRY")
    cash_blocked = next(event for event in events if event["ticker"] == "B000")
    next_open = next(event for event in events if event["ticker"] == "C000")
    assert same_open["event_status"] == "SKIPPED_SAME_OPEN_EXIT_REENTRY"
    assert cash_blocked["event_status"] == "SKIPPED_CASH_UNAVAILABLE"
    assert cash_blocked["pending_sale_proceeds"] > 0
    assert next_open["event_status"] == "EXECUTED"


def test_realistic_portfolio_rejects_zero_shares_and_duplicate_holding():
    high_price = _portfolio_record("HIGH", entry_open=6_000_000.0, cutoff_close=6_000_000.0)
    duplicate = _portfolio_record("DUP", entry_date="2021-01-04")
    duplicate_again = _portfolio_record("DUP", entry_date="2021-01-06")
    result = _run_synthetic_portfolio(
        [high_price, duplicate, duplicate_again],
        ["2021-01-04", "2021-01-06", "2026-08-14"],
    )
    events = result["event_ledger"]
    assert next(event for event in events if event["ticker"] == "HIGH")["event_status"] == "SKIPPED_ZERO_SHARES"
    assert next(event for event in events if event["ticker"] == "DUP" and event["execution_date"] == "2021-01-06")["event_status"] == "SKIPPED_DUPLICATE_HOLDING"


def test_realistic_portfolio_open_at_cutoff_and_daily_equity_are_exact_close_based():
    record = _portfolio_record("OPEN", cutoff_close=125.0)
    result = _run_synthetic_portfolio(record and [record], ["2021-01-04", "2021-01-05", "2026-08-14"])
    assert result["metrics"]["open_at_cutoff"] == 1
    assert result["metrics"]["cash_conservation_pass"] is True
    assert result["daily_equity"][-1]["equity"] is not None
    valuation = next(event for event in result["event_ledger"] if event["event_type"] == "VALUATION")
    assert valuation["open_at_cutoff"] is True
    assert valuation["reference_open"] == 125.0
    assert "mdd" in result["metrics"]


def test_realistic_portfolio_missing_cutoff_close_is_unresolved_without_fallback():
    record = _portfolio_record("MISSING", cutoff_close=None)
    result = _run_synthetic_portfolio(record and [record], ["2021-01-04", "2026-08-14"])
    assert result["status"] == "INCOMPLETE_REQUIRES_REVIEW"
    assert result["metrics"]["unresolved_count"] > 0
    valuation = next(event for event in result["event_ledger"] if event["event_type"] == "VALUATION")
    assert valuation["event_status"] == "UNRESOLVED"
    assert valuation["unresolved_reason"] == "MISSING_EXACT_CUTOFF_CLOSE"
    assert result["metrics"]["total_return"] is None


def test_realistic_portfolio_returns_metrics_and_event_ledger_cash_fields():
    record = _portfolio_record("METRIC", exit_date="2021-01-05", exit_price=105.0)
    result = _run_synthetic_portfolio(record and [record], ["2021-01-04", "2021-01-05", "2026-08-14"])
    metrics = result["metrics"]
    for key in ("total_return", "cagr", "mdd", "exposure", "turnover", "trade_count", "holding_period_days", "win_rate", "payoff_ratio", "open_at_cutoff", "total_commission", "total_sell_tax", "slippage_impact"):
        assert key in metrics
    for event in result["event_ledger"]:
        assert "cash_before" in event and "cash_after" in event
        assert "pending_sale_proceeds" in event


def test_exact_record_price_rejects_lifecycle_outside_date_even_when_ticker_frame_has_row():
    record = _portfolio_record(
        "REUSE",
        cutoff_date="2023-06-30",
        identity_effective_to="2023-06-30",
    )
    frame = _portfolio_frame(
        ["2023-06-30", "2026-08-14"],
        opens=[100.0, 999.0],
        closes=[101.0, 999.0],
    )
    assert runner._exact_record_price(record, frame, pd.Timestamp("2023-06-30"), "close") == 101.0
    assert runner._exact_record_price(record, frame, pd.Timestamp("2026-08-14"), "close") is None


def test_reused_ticker_old_identity_is_unresolved_at_final_valuation():
    old_identity = _portfolio_record(
        "REUSE",
        entry_date="2023-06-29",
        cutoff_date="2023-06-30",
        cutoff_close=999.0,
        identity_effective_from="2023-01-01",
        identity_effective_to="2023-06-30",
    )
    result = _run_synthetic_portfolio(
        [old_identity],
        ["2023-06-29", "2023-06-30", "2024-01-02", "2026-08-14"],
    )
    assert result["status"] == "INCOMPLETE_REQUIRES_REVIEW"
    assert result["metrics"]["total_return"] is None
    valuation = next(event for event in result["event_ledger"] if event["event_type"] == "VALUATION")
    assert valuation["event_status"] == "UNRESOLVED"
    assert valuation["unresolved_reason"] == "IDENTITY_LIFECYCLE_ENDED_BEFORE_FINAL_VALUATION"


def test_portfolio_event_signal_date_uses_event_specific_signal_fields():
    realized = _portfolio_record("SIGNAL", exit_date="2021-01-05", exit_price=105.0)
    result = _run_synthetic_portfolio(realized and [realized], ["2021-01-04", "2021-01-05", "2026-08-14"])
    events = result["event_ledger"]
    entry = next(event for event in events if event["event_type"] == "ENTRY")
    exit_event = next(event for event in events if event["event_type"] == "EXIT")
    assert entry["signal_date"] == "2021-01-01"
    assert exit_event["signal_date"] == "2021-01-03"

    open_record = _portfolio_record("VALUATION")
    open_result = _run_synthetic_portfolio(open_record and [open_record], ["2021-01-04", "2026-08-14"])
    valuation = next(event for event in open_result["event_ledger"] if event["event_type"] == "VALUATION")
    assert valuation["signal_date"] is None


def test_frozen_preflight_reads_contract_without_overwriting(monkeypatch):
    contract_path = runner.ROOT / runner.CONTRACT_REL
    before = contract_path.read_bytes()
    monkeypatch.setattr(runner, "build_execution_contract", lambda *_args, **_kwargs: pytest.fail("contract rebuilt"))
    result = runner.preflight(runner.ROOT)
    assert result["status"] == "READY"
    assert contract_path.read_bytes() == before


def test_write_contract_refuses_to_overwrite_existing_frozen_contract():
    with pytest.raises(runner.OfficialValidationError, match="OVERWRITE_FORBIDDEN"):
        runner.preflight(runner.ROOT, write_contract=True)


@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("stage4_authority", "validation_plan_sha256"), "bad", "STAGE4_VALIDATION_PLAN_SHA_MISMATCH"),
        (("investability", "market_cap_min_krw"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("investability", "avg_trading_value_20d_min_krw"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("costs", "buy_commission_rate"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("costs", "buy_slippage_rate"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("costs", "historical_sell_tax_schedule"), [], "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("portfolio", "initial_capital_krw"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("portfolio", "per_symbol_cash_budget_krw"), 1.0, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("portfolio", "max_positions"), 1, "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("result_axes",), ["wrong"], "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
        (("strategies", "base_strategy_id"), "wrong", "CONTRACT_RUNNER_CONSTANT_MISMATCH"),
    ],
)
def test_frozen_contract_mismatch_blocks_validation(path, value, error):
    contract = copy.deepcopy(runner.build_execution_contract())
    target = contract
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    contract["contract_sha256"] = runner._contract_digest(contract)
    with pytest.raises(runner.OfficialValidationError, match=error):
        runner.validate_execution_contract(contract)
