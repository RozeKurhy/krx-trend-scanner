import pandas as pd

from scripts import run_p3_2_realistic_portfolio_v01 as p3_2


def test_p3_2_runner_has_isolated_output_and_frozen_window_contract():
    assert p3_2.RUN_ID == "run_20260926_realistic_mcap1t_worker10_v01"
    assert p3_2.WORKERS == 10
    assert p3_2.SAMPLE_TICKERS == 40
    assert p3_2.CALENDAR_START == "2022-01-01"
    assert p3_2.CALENDAR_END == "2026-08-31"
    assert "p3_2_neg40_weak_protect_v01" in str(p3_2.OUT_DIR)


def test_sample_adapter_records_p3_contract_and_worker_memory(monkeypatch):
    monkeypatch.setattr(
        p3_2,
        "_LAST_AUTHORITY",
        {"p3_2_population_preflight": {"status": "PASS", "window_id": "P3-2"}},
    )
    sample = p3_2._adapt_sample(
        {
            "window_id": "P2-2",
            "p2_2_window": {"effective_start": "2022-01-03"},
            "worker_count": 10,
            "sample_ticker_count": 40,
        }
    )
    assert sample["window_id"] == "P3-2"
    assert sample["p3_2_window"]["effective_start"] == "2022-01-03"
    assert sample["p3_2_population_preflight"]["status"] == "PASS"
    assert sample["memory"]["process_peak_rss_reported"] > 0


def test_paired_identity_audit_checks_pair_trade_and_entry_parity():
    control = pd.DataFrame(
        [{
            "pair_id": "pair-1", "trade_id": "trade-1", "ticker": "000001",
            "isu_cd": "KR7000000001", "market": "KOSPI",
            "entry_signal_date": "2024-01-02", "entry_execution_date": "2024-01-03",
        }]
    )
    candidate = control.copy()
    audit = p3_2._paired_identity_audit(control, candidate)
    assert len(audit) == 1
    assert bool(audit.iloc[0]["identity_and_entry_match"])

    candidate.loc[0, "trade_id"] = "different-trade"
    audit = p3_2._paired_identity_audit(control, candidate)
    assert not bool(audit.iloc[0]["identity_and_entry_match"])


def test_certification_requires_zero_unresolved_and_no_slot_cap_skips():
    summary = {
        "raw_pit_partition_coverage": {"all_expected_market_dates_complete": True},
        "validation": {
            "matching_pass": True,
            "mcap_unresolved_count": 0,
            "portfolio_unresolved_count": 0,
            "unclassified_valuation_carry_count": 0,
            "daily_equity_complete": True,
            "control_cash_conservation": True,
            "candidate_cash_conservation": True,
        }
    }
    no_cap = {
        "slot_cap_would_block_count": 0,
        "portfolio_engine_source_has_slot_cap_branch": False,
    }
    assert p3_2._certified(summary, no_cap)
    summary["validation"]["mcap_unresolved_count"] = 1
    assert not p3_2._certified(summary, no_cap)
    summary["validation"]["mcap_unresolved_count"] = 0
    assert not p3_2._certified(summary, {**no_cap, "slot_cap_would_block_count": 1})
