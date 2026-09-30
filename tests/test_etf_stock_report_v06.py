from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import pytest

from trend_scanner.reporting.julia_v1_report import (
    ELIGIBILITY_CONTRACT,
    STRATEGY_ID,
    _render_strategy_markdown,
    compute_etf_eligibility,
    generate_official_etf36_reports,
    load_official_etf36,
)


ROOT = Path(__file__).resolve().parents[1]


def test_certified_etf36_corpus_is_read_only_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = ROOT / "artifacts/reporting/etf_stock_reports/20260925"
    summary_path = output_dir / "generation_summary.json"
    before = summary_path.read_bytes()
    before_mtime = summary_path.stat().st_mtime_ns

    def should_not_regenerate(**kwargs: object) -> dict[str, object]:
        pytest.fail("valid certified ETF36 corpus was regenerated")

    monkeypatch.setattr(
        "trend_scanner.reporting.julia_v1_report._generate_official_etf36_reports_into",
        should_not_regenerate,
    )
    result = generate_official_etf36_reports(
        repo_root=ROOT,
        target_as_of="2026-09-25",
        reference_market_date="2026-09-23",
        output_dir=output_dir,
    )

    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["generated_count"] == 36
    assert summary_path.read_bytes() == before
    assert summary_path.stat().st_mtime_ns == before_mtime


def test_partial_etf36_corpus_is_not_accepted_as_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "20260925"
    (output_dir / "json").mkdir(parents=True)
    partial = output_dir / "json" / "partial.json"
    partial.write_text("{}\n", encoding="utf-8")
    calls = 0

    def incomplete_generation(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "target_as_of": "2026-09-25",
            "reference_market_date": "2026-09-23",
            "expected_count": 36,
            "generated_count": 0,
            "generated_tickers": [],
            "strategy_id_counts": {},
            "eligibility_pass_fail_counts": {"PASS": 0, "FAIL": 0},
            "failed_tickers_and_reasons": [],
            "source_universe_sha256": "",
            "network_requests": 0,
            "post_asof_data_references": 0,
            "julia_evaluator_error_tickers": [],
        }

    monkeypatch.setattr(
        "trend_scanner.reporting.julia_v1_report._generate_official_etf36_reports_into",
        incomplete_generation,
    )
    result = generate_official_etf36_reports(
        repo_root=ROOT,
        target_as_of="2026-09-25",
        reference_market_date="2026-09-23",
        output_dir=output_dir,
    )

    assert calls == 1
    assert result["status"] == "FAILED"
    assert result["status"] != "NOOP_ALREADY_COMPLETE"
    assert partial.read_text(encoding="utf-8") == "{}\n"


def _synthetic_strategy() -> dict:
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": "Julia V1",
        "strategy_version": "V1",
        "asset_scope": "OFFICIAL_ETF_36",
        "applicability": "APPLICABLE",
        "strategy_state": "WAIT",
        "canonical_position": "FLAT",
        "action": "WAIT",
        "action_reason": "NO_OPEN_POSITION",
        "execution_timing": None,
        "entry_conditions": {
            "signal_date": "2026-09-23",
            "official_etf36_membership": True,
            "eligibility_contract": ELIGIBILITY_CONTRACT,
            "listing_date": "2002-10-14",
            "listing_age_pass": True,
            "raw_close_krw": 1000,
            "minimum_raw_close_krw": 1000,
            "raw_close_pass": True,
            "avg_volume_20d_shares": 10000,
            "volume_window_sessions": 20,
            "volume_window_start": "2026-08-27",
            "volume_window_end": "2026-09-23",
            "volume_window_includes_signal_date": True,
            "minimum_avg_volume_20d_shares": 10000,
            "volume_pass": True,
            "pit_eligibility_pass": True,
            "strategy_ready_date": "2017-01-06",
            "clean_ready_date": "2017-01-06",
            "effective_start_date": "2017-01-06",
            "strategy_ready_pass": True,
            "pattern_a_stage": "TRANSITION",
            "pattern_a_stage_pass": True,
            "fast_stage": "TRIGGER",
            "fast_stage_status": "READY",
            "fast_trigger_pass": True,
            "monthly_regime": "PERMITTED_REGIME",
            "monthly_regime_pass": True,
            "daily_risk": "NORMAL",
            "daily_risk_pass": True,
            "fast_score_state": "READY",
            "fast_score_pass": True,
            "no_open_position": True,
            "signal_date_is_current_reference": False,
            "next_krx_session_date": None,
            "next_open_raw_krw": None,
            "exact_next_open_available": False,
            "all_conditions_met": False,
            "failed_conditions": ["SIGNAL_DATE_IS_CURRENT_REFERENCE", "EXACT_NEXT_KRX_OPEN_AVAILABLE"],
        },
        "current_trade": None,
        "protection_state": None,
        "reentry_state": {
            "enabled": True,
            "cooldown": "NONE",
            "maximum_reentries": "NONE",
            "completed_trade_count": 0,
            "current_trade_sequence": None,
            "next_entry_sequence": 1,
        },
        "trade_history": [],
        "interpretation": "Julia V1 대기.",
        "eligibility_contract": ELIGIBILITY_CONTRACT,
        "provenance": {
            "evaluator_id": "JULIA_STRATEGY_V00",
            "loss_guard_enabled": False,
            "data_source": "KRX_RAW_ETF_OHLCV",
            "reference_market_date": "2026-09-23",
            "strategy_ready_date": "2017-01-06",
            "clean_ready_date": "2017-01-06",
            "network_requests": 0,
            "support_evaluator_errors": [],
        },
        "current_snapshot": {
            "as_of": "2026-09-23",
            "official_etf36_membership": True,
            "listing_date": "2002-10-14",
            "listing_age_pass": True,
            "raw_close_krw": 1000,
            "minimum_raw_close_krw": 1000,
            "raw_close_pass": True,
            "avg_volume_20d_shares": 10000,
            "volume_window_sessions": 20,
            "volume_window_start": "2026-08-27",
            "volume_window_end": "2026-09-23",
            "volume_window_includes_signal_date": True,
            "minimum_avg_volume_20d_shares": 10000,
            "volume_pass": True,
            "eligibility_pass": True,
            "eligibility_contract": ELIGIBILITY_CONTRACT,
            "strategy_ready_date": "2017-01-06",
            "clean_ready_date": "2017-01-06",
            "effective_start_date": "2017-01-06",
            "market_cap_applicability": "NOT_APPLICABLE_TO_JULIA_ETF_ELIGIBILITY",
            "phase10_investability_applicability": "NOT_APPLICABLE",
        },
    }


def test_official_etf36_is_exact_frozen_set() -> None:
    rows, _ = load_official_etf36(ROOT)
    assert len(rows) == 36
    assert len({row.ticker for row in rows}) == 36
    assert len({row.isu_cd for row in rows}) == 36
    assert sum(row.major_category == "MARKET_INDEX" for row in rows) == 12
    assert sum(row.major_category == "SECTOR_INDEX" for row in rows) == 19
    assert sum(row.major_category == "COMMODITY_RESOURCE" for row in rows) == 5
    assert "474800" not in {row.ticker for row in rows}


def test_raw_eligibility_exact_thresholds_window_and_no_future_session() -> None:
    sessions = pd.bdate_range("2026-08-20", periods=25)
    raw = pd.DataFrame(
        {"open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1000.0, "volume": 10000.0},
        index=sessions,
    )
    metrics, signal_pass, executable = compute_etf_eligibility(
        raw,
        listing_date="2020-01-01",
        effective_start_date=sessions[0].strftime("%Y-%m-%d"),
        calendar_dates=sessions,
    )
    last = sessions[-1].strftime("%Y-%m-%d")
    assert metrics[last]["raw_close_krw"] == 1000
    assert metrics[last]["avg_volume_20d_shares"] == 10000
    assert metrics[last]["volume_window_sessions"] == 20
    assert metrics[last]["volume_window_includes_signal_date"] is True
    assert last in signal_pass
    assert last not in executable  # no next actual session exists in the as-of authority

    raw.loc[sessions[-1], "close"] = 999
    _, below_close, _ = compute_etf_eligibility(
        raw, listing_date="2020-01-01", effective_start_date=sessions[0].strftime("%Y-%m-%d"), calendar_dates=sessions
    )
    assert last not in below_close

    raw.loc[sessions[-1], "close"] = 1000
    raw.loc[sessions[-1], "volume"] = 9999
    _, below_volume, _ = compute_etf_eligibility(
        raw, listing_date="2020-01-01", effective_start_date=sessions[0].strftime("%Y-%m-%d"), calendar_dates=sessions
    )
    assert last not in below_volume

    raw.loc[sessions[-1], "volume"] = 10000
    raw.loc[sessions[-2], "volume"] = np.nan
    incomplete, missing_window, _ = compute_etf_eligibility(
        raw, listing_date="2020-01-01", effective_start_date=sessions[0].strftime("%Y-%m-%d"), calendar_dates=sessions
    )
    assert incomplete[last]["avg_volume_20d_shares"] is None
    assert last not in missing_window


def test_v06_schema_requires_julia_contract_and_excludes_afast_route() -> None:
    schema = json.loads((ROOT / "docs/reporting/schema_v06.json").read_text(encoding="utf-8"))
    fundamentals = {
        "applicability": "NOT_APPLICABLE",
        "data_status": "NOT_APPLICABLE",
        "reason": None,
        "requested_as_of": "2026-09-25",
        "company_family": None,
        "currency": "KRW",
        "filter_status": "NOT_APPLICABLE",
        "filter_passed": False,
        "filter_reasons": [],
        "summary": {
            "latest_fy": None,
            "latest_quarter": None,
            "latest_fy_revenue_krw": None,
            "latest_4q_avg_revenue_krw": None,
            "ttm_revenue_krw": None,
            "ttm_operating_income_krw": None,
            "ttm_net_income_krw": None,
            "ttm_operating_cash_flow_krw": None,
            "ttm_operating_margin_pct": None,
            "ttm_net_margin_pct": None,
            "ttm_operating_cash_flow_margin_pct": None,
            "ttm_roe_pct": None,
            "latest_debt_ratio_pct": None,
            "filter_status": "NOT_APPLICABLE",
            "filter_passed": False,
            "filter_reasons": [],
        },
        "quarterly": [],
        "annual": [],
        "diagnostics": [],
    }
    strategy = _synthetic_strategy()
    payload = {
        "report_version": "0.6",
        "ticker": "069500",
        "name": "KODEX 200",
        "market": "KOSPI",
        "asset_type": "ETF",
        "requested_as_of": "2026-09-25",
        "reference_market_date": "2026-09-23",
        "header": {},
        "summary": {},
        "current_snapshot": {"etf_eligibility": strategy["current_snapshot"]},
        "official_strategy": strategy,
        "pattern_a_fast": {},
        "monthly_history": {},
        "foreign_flow": {},
        "relative_strength": {},
        "sector_relative_strength": {},
        "trading_value_flow": {},
        "data_quality": {},
        "provenance": {},
        "fundamentals": fundamentals,
        "readiness_status": "READY",
        "readiness_reason": "RAW_PIT_AND_COMMON_REPORT_READY",
    }
    jsonschema.validate(payload, schema)
    invalid = {**payload, "a_fast_core": {"strategy_id": "JULIA_ETF_STRATEGY_V01"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_markdown_uses_julia_strategy_label_and_loss_guard_disabled() -> None:
    markdown = _render_strategy_markdown({"official_strategy": _synthetic_strategy()})
    assert "## 2. Julia V1 전략 상태" in markdown
    assert "Pre-PROGRESSED Loss Guard**: `DISABLED`" in markdown
    assert "A FAST Core V2" not in markdown
    assert "Phase 10" not in markdown
