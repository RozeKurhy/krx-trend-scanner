"""Focused offline tests for the Stage 5 V2 ↔ Julia execution preparation."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

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
    assert contract["output"]["support_result_files"] == [
        "portfolio_event_ledger.csv",
        "portfolio_daily_equity.csv",
    ]
    assert contract["execution"]["open_at_cutoff"] is True
    assert contract["portfolio"]["partial_fill"] is False

